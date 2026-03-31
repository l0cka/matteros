from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer
from pydantic import ValidationError

from matteros.connectors import create_default_registry
from matteros.connectors.ms_graph_auth import DEFAULT_SCOPES, MicrosoftGraphTokenManager
from matteros.core.audit import AuditLogger
from matteros.core.config import (
    MatterOSConfig,
    backup_legacy_config,
    default_config,
    load_config,
    save_config_atomic,
)
from matteros.core.factory import build_ms_graph_token_manager, build_runner, resolve_home
from matteros.core.onboarding import build_onboarding_status, ensure_home_scaffold, smoke_test_dry_run
from matteros.core.playbook import PlaybookError, load_playbook
from matteros.core.policy import PolicyEngine
from matteros.core.runner import RunnerOptions, WorkflowRunner
from matteros.core.store import SQLiteStore
from matteros.core.types import ApprovalDecision, TimeEntrySuggestion
from matteros.llm import LLMAdapter

app = typer.Typer(help="MatterOS legal ops workflow CLI")
connectors_app = typer.Typer(help="Manage connectors")
playbooks_app = typer.Typer(help="Inspect playbooks")
audit_app = typer.Typer(help="Inspect audit logs")
auth_app = typer.Typer(help="Manage authentication")
llm_app = typer.Typer(help="Inspect LLM runtime configuration")
onboard_app = typer.Typer(help="Guided onboarding and readiness checks")

drafts_app = typer.Typer(help="Manage proactive time entry drafts")
daemon_app = typer.Typer(help="Background daemon management")
team_app = typer.Typer(help="Team mode management")

app.add_typer(connectors_app, name="connectors")
app.add_typer(playbooks_app, name="playbooks")
app.add_typer(audit_app, name="audit")
app.add_typer(auth_app, name="auth")
app.add_typer(llm_app, name="llm")
app.add_typer(onboard_app, name="onboard")
app.add_typer(drafts_app, name="drafts")
app.add_typer(daemon_app, name="daemon")
app.add_typer(team_app, name="team")


@app.command("tui")
def tui_command(
    home: Path | None = typer.Option(None, help="MatterOS home directory"),
) -> None:
    """Launch the interactive TUI dashboard."""
    try:
        from matteros.tui.app import run_tui
    except ImportError:
        typer.echo("TUI requires textual: pip install matteros[tui]")
        raise typer.Exit(code=1)
    run_tui(home=home)


@app.command("init")
def init_command(home: Path | None = typer.Option(None, help="MatterOS home directory")) -> None:
    """Create runtime directories, sqlite db, and an example playbook."""
    home_dir = resolve_home(home)
    paths = ensure_home_scaffold(home=home_dir)
    SQLiteStore(home_dir / "matteros.db")

    config_path = home_dir / "config.yml"
    if not config_path.exists():
        cfg = default_config(home=home_dir)
        save_config_atomic(config=cfg, path=config_path)

    typer.echo(f"initialized MatterOS home: {home_dir}")
    typer.echo(f"sqlite db: {home_dir / 'matteros.db'}")
    typer.echo(f"example playbook: {paths['sample_playbook']}")


@connectors_app.command("list")
def connectors_list(
    home: Path | None = typer.Option(None, help="MatterOS home directory"),
) -> None:
    """List installed connectors and permission manifests."""
    home_dir = resolve_home(home)
    registry = create_default_registry(
        auth_cache_path=home_dir / "auth" / "ms_graph_token.json",
        plugin_dir=home_dir / "plugins",
    )
    for manifest in registry.list():
        operations = ", ".join(
            f"{operation}:{mode.value}" for operation, mode in manifest.operations.items()
        )
        typer.echo(
            f"{manifest.connector_id} | default={manifest.default_mode.value} | {operations}"
        )


@auth_app.command("login")
def auth_login(
    home: Path | None = typer.Option(None, help="MatterOS home directory"),
    tenant_id: str = typer.Option("common", "--tenant-id", help="Microsoft Entra tenant id"),
    client_id: str | None = typer.Option(
        None, "--client-id", help="App registration client id (or MATTEROS_MS_GRAPH_CLIENT_ID)"
    ),
    scopes: str = typer.Option(
        DEFAULT_SCOPES,
        "--scopes",
        help="Space-delimited OAuth scopes",
    ),
) -> None:
    """Perform Microsoft Graph device-code login and cache token."""
    home_dir = resolve_home(home)
    home_dir.mkdir(parents=True, exist_ok=True)
    (home_dir / "auth").mkdir(parents=True, exist_ok=True)

    manager = build_ms_graph_token_manager(
        home=home_dir,
        tenant_id=tenant_id,
        client_id=client_id,
        scopes=scopes,
    )

    try:
        manager.login_device_code(print_fn=typer.echo)
    except Exception as exc:
        typer.echo(f"auth login failed: {exc}")
        raise typer.Exit(code=1)

    status = manager.cache_status()
    expires_at = datetime.fromtimestamp(int(status.get("expires_at", 0)), tz=UTC).isoformat()
    typer.echo("microsoft graph login completed")
    typer.echo(f"token_cache: {manager.cache_path}")
    typer.echo(f"expires_at: {expires_at}")


@auth_app.command("status")
def auth_status(
    home: Path | None = typer.Option(None, help="MatterOS home directory"),
) -> None:
    """Show current Microsoft Graph token cache status."""
    home_dir = resolve_home(home)
    manager = build_ms_graph_token_manager(home=home_dir)
    status = manager.cache_status()
    state = str(status.get("status"))

    if state == "missing":
        typer.echo("microsoft_graph_token: missing")
        return

    expires_at = datetime.fromtimestamp(int(status.get("expires_at", 0)), tz=UTC).isoformat()
    typer.echo(f"microsoft_graph_token: {state}")
    typer.echo(f"tenant_id: {status.get('tenant_id')}")
    typer.echo(f"client_id: {status.get('client_id')}")
    typer.echo(f"scopes: {status.get('scopes')}")
    typer.echo(f"expires_at: {expires_at}")
    typer.echo(f"seconds_remaining: {status.get('seconds_remaining')}")


@auth_app.command("logout")
def auth_logout(
    home: Path | None = typer.Option(None, help="MatterOS home directory"),
) -> None:
    """Remove cached Microsoft Graph token."""
    home_dir = resolve_home(home)
    manager = build_ms_graph_token_manager(home=home_dir)
    if not manager.cache_path.exists():
        typer.echo("no cached token to remove")
        return

    manager.cache_path.unlink()
    typer.echo(f"removed cached token: {manager.cache_path}")


@onboard_app.callback(invoke_without_command=True)
def onboard(
    ctx: typer.Context,
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        help="Run without prompts; fail if required inputs are missing",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Accept safe defaults and create missing directories",
    ),
    profile: str = typer.Option("default", "--profile", help="Profile name to store"),
    workspace_path: Path | None = typer.Option(
        None,
        "--workspace-path",
        help="Workspace directory used for onboarding smoke run",
    ),
    default_playbook: Path | None = typer.Option(
        None,
        "--default-playbook",
        help="Default playbook path to persist in config",
    ),
    skip_auth: bool = typer.Option(
        False,
        "--skip-auth",
        help="Skip Microsoft auth login during onboarding",
    ),
    skip_smoke_test: bool = typer.Option(
        False,
        "--skip-smoke-test",
        help="Skip dry-run smoke test",
    ),
    dry_run_only: bool = typer.Option(
        False,
        "--dry-run-only",
        help="Force dry-run smoke behavior (default behavior)",
    ),
    tenant_id: str | None = typer.Option(
        None,
        "--tenant-id",
        help="Microsoft Entra tenant id override",
    ),
    scopes: str | None = typer.Option(
        None,
        "--scopes",
        help="Microsoft OAuth scopes override",
    ),
    home: Path | None = typer.Option(None, help="MatterOS home directory"),
) -> None:
    """Guided first-run setup. Use `matteros onboard status` for readiness."""
    if ctx.invoked_subcommand:
        return

    home_dir = resolve_home(home)
    paths = ensure_home_scaffold(home=home_dir)
    SQLiteStore(home_dir / "matteros.db")

    config_path = home_dir / "config.yml"
    loaded = load_config(path=config_path, home=home_dir)
    cfg = loaded.config

    if loaded.migrated and loaded.existed and config_path.exists():
        backup_path = backup_legacy_config(config_path=config_path)
        typer.echo(f"migrated legacy config; backup saved at {backup_path}")

    if loaded.existed and not non_interactive and not yes:
        if not typer.confirm("Existing config detected. Update it?", default=True):
            typer.echo("onboarding aborted")
            raise typer.Exit(code=0)

    cfg.profile.name = profile

    configured_workspace = _resolve_workspace_path(
        workspace_path=workspace_path,
        current_value=cfg.paths.workspace_path,
        non_interactive=non_interactive,
        yes=yes,
    )
    cfg.paths.workspace_path = str(configured_workspace)

    configured_playbook = _resolve_playbook_path(
        playbook_path=default_playbook,
        current_value=cfg.paths.default_playbook,
        sample_playbook=paths["sample_playbook"],
        non_interactive=non_interactive,
        yes=yes,
    )
    cfg.paths.default_playbook = str(configured_playbook)
    cfg.paths.fixtures_root = str(paths["fixtures_dir"])

    _configure_llm_section(cfg=cfg, non_interactive=non_interactive, yes=yes)

    if tenant_id:
        cfg.ms_graph.tenant_id = tenant_id
    if scopes:
        cfg.ms_graph.scopes = scopes

    manager = build_ms_graph_token_manager(
        home=home_dir,
        tenant_id=cfg.ms_graph.tenant_id,
        scopes=cfg.ms_graph.scopes,
    )
    auth_status = manager.cache_status()
    auth_state = str(auth_status.get("status"))

    if skip_auth:
        cfg.ms_graph.auth_pending = True
        typer.echo("auth step skipped (--skip-auth); status marked pending")
    elif auth_state == "valid":
        cfg.ms_graph.auth_pending = False
        typer.echo("microsoft auth token is already valid")
    elif non_interactive:
        cfg.ms_graph.auth_pending = True
        typer.echo("microsoft auth token missing/expired; status marked pending (non-interactive)")
    else:
        prompt = "Microsoft token missing/expired. Run device-code login now?"
        if yes or typer.confirm(prompt, default=True):
            try:
                manager.login_device_code(print_fn=typer.echo)
                cfg.ms_graph.auth_pending = False
            except Exception as exc:
                cfg.ms_graph.auth_pending = True
                typer.echo(f"auth login failed during onboarding: {exc}")
        else:
            cfg.ms_graph.auth_pending = True

    save_config_atomic(config=cfg, path=config_path)

    smoke_status = "skipped"
    smoke_run_id: str | None = None
    smoke_error: str | None = None

    if not skip_smoke_test:
        if dry_run_only:
            typer.echo("dry-run-only mode enabled")
        runner = build_runner(home_dir)
        audit = AuditLogger(SQLiteStore(home_dir / "matteros.db"), home_dir / "audit" / "events.jsonl")
        summary, verify, error = smoke_test_dry_run(
            runner=runner,
            audit=audit,
            playbook_path=Path(cfg.paths.default_playbook),
            workspace_path=Path(cfg.paths.workspace_path),
            fixtures_root=Path(cfg.paths.fixtures_root or paths["fixtures_dir"]),
            output_csv_path=paths["exports_dir"] / "onboard_time_entries.csv",
            reviewer="onboard",
        )
        if error:
            smoke_status = "failed"
            smoke_error = error
        else:
            smoke_status = "passed"
            smoke_run_id = summary.run_id if summary else None
            if verify:
                typer.echo(
                    f"smoke test audit verified: run={verify.run_id} events={verify.checked_events}"
                )

    cfg.onboarding.completed_at = datetime.now(UTC).isoformat()
    cfg.onboarding.last_smoke_test_status = smoke_status
    cfg.onboarding.last_smoke_test_run_id = smoke_run_id
    save_config_atomic(config=cfg, path=config_path)

    typer.echo("onboarding complete")
    typer.echo(f"home: {home_dir}")
    typer.echo(f"profile: {cfg.profile.name}")
    typer.echo(f"default_playbook: {cfg.paths.default_playbook}")
    typer.echo(f"workspace_path: {cfg.paths.workspace_path}")
    typer.echo(f"auth_pending: {cfg.ms_graph.auth_pending}")
    typer.echo(f"smoke_test: {smoke_status}")
    if smoke_run_id:
        typer.echo(f"smoke_run_id: {smoke_run_id}")

    if smoke_error:
        typer.echo(f"smoke_error: {smoke_error}")
        raise typer.Exit(code=1)


@onboard_app.command("status")
def onboard_status(
    home: Path | None = typer.Option(None, help="MatterOS home directory"),
) -> None:
    """Show onboarding readiness matrix."""
    home_dir = resolve_home(home)
    config_path = home_dir / "config.yml"
    loaded = load_config(path=config_path, home=home_dir)
    cfg = loaded.config

    manager = build_ms_graph_token_manager(
        home=home_dir,
        tenant_id=cfg.ms_graph.tenant_id,
        scopes=cfg.ms_graph.scopes,
    )
    auth_state = str(manager.cache_status().get("status"))
    auth_ready = auth_state == "valid" and not cfg.ms_graph.auth_pending

    adapter = LLMAdapter(
        default_provider=cfg.llm.provider,
        allow_remote_models=cfg.llm.remote_enabled,
        model_allowlist=cfg.llm.model_allowlist,
    )
    _, llm_findings = _llm_findings(
        adapter=adapter,
        provider_name=cfg.llm.provider,
    )
    llm_ready = len(llm_findings) == 0

    status = build_onboarding_status(
        config_present=config_path.exists(),
        auth_ready=auth_ready,
        llm_ready=llm_ready,
        playbook_path=Path(cfg.paths.default_playbook),
        smoke_status=cfg.onboarding.last_smoke_test_status,
        smoke_run_id=cfg.onboarding.last_smoke_test_run_id,
    )

    typer.echo(f"config_present: {status.config_present}")
    typer.echo(f"auth_ready: {status.auth_ready}")
    typer.echo(f"llm_ready: {status.llm_ready}")
    typer.echo(f"playbook_ready: {status.playbook_ready}")
    typer.echo(f"smoke_test_passed: {status.smoke_test_passed}")
    typer.echo(f"details: {json.dumps(status.details, sort_keys=True)}")

    if not (
        status.config_present
        and status.auth_ready
        and status.llm_ready
        and status.playbook_ready
        and status.smoke_test_passed
    ):
        raise typer.Exit(code=1)


@llm_app.command("doctor")
def llm_doctor(
    provider: str | None = typer.Option(
        None,
        "--provider",
        help="Provider override for check: local|openai|anthropic",
    ),
    home: Path | None = typer.Option(None, help="MatterOS home directory"),
) -> None:
    """Validate LLM provider configuration and policy controls."""
    home_dir = resolve_home(home)
    loaded = load_config(path=home_dir / "config.yml", home=home_dir)
    cfg = loaded.config if loaded.existed else None

    env_provider = os.getenv("MATTEROS_MODEL_PROVIDER")

    if provider:
        if cfg is None:
            adapter = LLMAdapter(default_provider=provider)
        else:
            adapter = LLMAdapter(
                default_provider=provider,
                allow_remote_models=cfg.llm.remote_enabled,
                model_allowlist=cfg.llm.model_allowlist,
            )
        selected_provider = provider
    elif env_provider:
        adapter = LLMAdapter(default_provider=env_provider)
        selected_provider = env_provider
    elif cfg is None:
        adapter = LLMAdapter()
        selected_provider = adapter.default_provider
    else:
        selected_provider = cfg.llm.provider
        adapter = LLMAdapter(
            default_provider=selected_provider,
            allow_remote_models=cfg.llm.remote_enabled,
            model_allowlist=cfg.llm.model_allowlist,
        )

    provider_instance = adapter.providers.get(selected_provider)
    if provider_instance is None:
        typer.echo(f"llm doctor: FAILED - unknown provider '{selected_provider}'")
        raise typer.Exit(code=1)

    model_name, findings = _llm_findings(adapter=adapter, provider_name=selected_provider)

    typer.echo(f"provider: {selected_provider}")
    typer.echo(f"model: {model_name}")
    typer.echo(f"remote_enabled: {adapter.allow_remote_models}")
    typer.echo(f"max_retries: {adapter.max_retries}")
    typer.echo(f"retry_backoff_seconds: {adapter.retry_backoff_seconds}")
    typer.echo(
        "model_allowlist: "
        + (", ".join(adapter.model_allowlist) if adapter.model_allowlist else "<none>")
    )

    if findings:
        typer.echo("llm doctor: FAILED")
        for finding in findings:
            typer.echo(f"- {finding}")
        raise typer.Exit(code=1)

    typer.echo("llm doctor: OK")


@playbooks_app.command("list")
def playbooks_list(
    path: Path = typer.Option(Path("playbooks"), help="Directory to scan for playbooks"),
) -> None:
    """List available playbooks and required connectors."""
    target = path.expanduser().resolve()
    if not target.exists():
        typer.echo(f"playbook directory not found: {target}")
        raise typer.Exit(code=1)

    files = sorted(target.glob("*.yml")) + sorted(target.glob("*.yaml"))
    if not files:
        typer.echo(f"no playbooks found in {target}")
        return

    for file_path in files:
        try:
            playbook = load_playbook(file_path)
        except PlaybookError as exc:
            typer.echo(f"{file_path.name} | invalid | {exc}")
            continue

        connector_list = ", ".join(playbook.connectors)
        typer.echo(
            f"{file_path.name} | steps={len(playbook.steps)} | connectors={connector_list}"
        )


@app.command("run")
def run_command(
    playbook: Path = typer.Argument(..., help="Path to playbook YAML"),
    input_file: Path | None = typer.Option(None, "--input", help="JSON input file"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Execute without side effects"),
    approve: bool = typer.Option(False, "--approve", help="Enable approval flow for side effects"),
    reviewer: str = typer.Option("cli-user", "--reviewer", help="Approval actor name"),
    approval_file: Path | None = typer.Option(
        None,
        "--approval-file",
        help="Optional JSON decisions for non-interactive approval",
    ),
    home: Path | None = typer.Option(None, help="MatterOS home directory"),
) -> None:
    """Run a playbook with optional dry-run and approval gating."""
    home_dir = resolve_home(home)
    runner = build_runner(home_dir)

    try:
        playbook_def = load_playbook(playbook.resolve())
    except PlaybookError as exc:
        typer.echo(f"playbook error: {exc}")
        raise typer.Exit(code=1)

    inputs: dict[str, Any] = {}
    if input_file is not None:
        payload = json.loads(input_file.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            typer.echo("input JSON must be an object")
            raise typer.Exit(code=1)
        inputs = payload

    approval_handler = None
    if approve:
        if approval_file:
            approval_handler = _approval_handler_from_file(approval_file)
        else:
            approval_handler = _interactive_approval_handler

    options = RunnerOptions(
        dry_run=dry_run,
        approve_mode=approve,
        reviewer=reviewer,
        approval_handler=approval_handler,
    )

    try:
        summary = runner.run(playbook=playbook_def, inputs=inputs, options=options)
    except Exception as exc:
        typer.echo(f"run failed: {exc}")
        raise typer.Exit(code=1)

    typer.echo(f"run_id: {summary.run_id}")
    typer.echo(f"status: {summary.status.value}")

    source_counts: list[str] = []
    for source_key in ("calendar_events", "sent_emails", "file_activity"):
        value = summary.outputs.get(source_key)
        if isinstance(value, list):
            source_counts.append(f"{source_key}={len(value)}")
    if source_counts:
        typer.echo(f"data_sources: {', '.join(source_counts)}")

    suggestions = summary.outputs.get("time_entry_suggestions", [])
    if isinstance(suggestions, list) and suggestions:
        typer.echo("proposed_time_entries:")
        for item in suggestions:
            entry = TimeEntrySuggestion.model_validate(item)
            typer.echo(
                f"- matter={entry.matter_id} duration={entry.duration_minutes}m confidence={entry.confidence} narrative={entry.narrative}"
            )

    apply_result = summary.outputs.get("apply_time_entries")
    if apply_result:
        typer.echo(f"apply_result: {json.dumps(apply_result, sort_keys=True)}")


@audit_app.command("show")
def audit_show(
    last: int = typer.Option(20, "--last", min=1, help="Number of events to show"),
    home: Path | None = typer.Option(None, help="MatterOS home directory"),
) -> None:
    """Show recent audit events."""
    home_dir = resolve_home(home)
    store = SQLiteStore(home_dir / "matteros.db")
    events = store.list_audit_events(limit=last)
    for event in events:
        typer.echo(
            f"#{event['seq']} run={event['run_id']} {event['timestamp']} {event['event_type']} actor={event['actor']} step={event['step_id']}"
        )


@audit_app.command("export")
def audit_export(
    run_id: str = typer.Option(..., "--run-id", help="Run identifier"),
    format: str = typer.Option("json", "--format", help="json|jsonl"),
    output: Path | None = typer.Option(None, "--output", help="Output file path"),
    home: Path | None = typer.Option(None, help="MatterOS home directory"),
) -> None:
    """Export audit events for a run."""
    home_dir = resolve_home(home)
    store = SQLiteStore(home_dir / "matteros.db")
    events = store.export_audit_for_run(run_id)

    if format not in {"json", "jsonl"}:
        typer.echo("format must be json or jsonl")
        raise typer.Exit(code=1)

    if format == "json":
        payload = json.dumps(events, indent=2, sort_keys=True)
    else:
        payload = "\n".join(json.dumps(event, sort_keys=True) for event in events)

    if output:
        output.write_text(payload + ("\n" if not payload.endswith("\n") else ""), encoding="utf-8")
        typer.echo(f"exported {len(events)} events to {output}")
        return

    typer.echo(payload)


@audit_app.command("verify")
def audit_verify(
    run_id: str = typer.Option(..., "--run-id", help="Run identifier"),
    source: str = typer.Option("both", "--source", help="db|jsonl|both"),
    home: Path | None = typer.Option(None, help="MatterOS home directory"),
) -> None:
    """Verify audit hash-chain integrity for a run."""
    source_name = source.strip().lower()
    if source_name not in {"db", "jsonl", "both"}:
        typer.echo("source must be db, jsonl, or both")
        raise typer.Exit(code=2)

    home_dir = resolve_home(home)
    store = SQLiteStore(home_dir / "matteros.db")
    audit = AuditLogger(store, home_dir / "audit" / "events.jsonl")

    try:
        result = audit.verify_run(run_id=run_id, source=source_name)
    except FileNotFoundError as exc:
        typer.echo(f"audit verify error: {exc}")
        raise typer.Exit(code=2)

    if result.ok:
        typer.echo(
            f"audit verified: run={result.run_id} source={result.source} "
            f"events={result.checked_events} last_seq={result.last_seq} "
            f"last_hash={result.last_event_hash}"
        )
        return

    failure = f"audit verification failed: reason={result.reason}"
    if result.failure_seq is not None:
        failure += f" seq={result.failure_seq}"
    if result.details:
        failure += f" details={result.details}"
    typer.echo(failure)

    if result.reason == "missing_event" and result.checked_events == 0:
        raise typer.Exit(code=2)
    raise typer.Exit(code=1)


def _interactive_approval_handler(
    suggestion: TimeEntrySuggestion,
    index: int,
) -> ApprovalDecision:
    typer.echo(
        f"[{index}] matter={suggestion.matter_id} duration={suggestion.duration_minutes}m confidence={suggestion.confidence}"
    )
    typer.echo(f"narrative: {suggestion.narrative}")

    approved = typer.confirm("approve this entry?", default=True)
    if not approved:
        reason = typer.prompt("rejection reason", default="reviewer rejected")
        return ApprovalDecision(decision="reject", reason=reason)

    narrative = typer.prompt("narrative", default=suggestion.narrative)
    duration_input = typer.prompt(
        "duration_minutes",
        default=str(suggestion.duration_minutes),
    )

    try:
        duration = int(duration_input)
    except ValueError as exc:
        raise typer.BadParameter("duration_minutes must be integer") from exc

    edited = suggestion.model_copy(update={"narrative": narrative, "duration_minutes": duration})
    return ApprovalDecision(decision="approve", edited_entry=edited)


def _approval_handler_from_file(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise typer.BadParameter("approval-file must be a list of decisions")

    decisions: dict[int, dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        if "index" not in item:
            continue
        decisions[int(item["index"])] = item

    def handler(suggestion: TimeEntrySuggestion, index: int) -> ApprovalDecision:
        selected = decisions.get(index)
        if not selected:
            return ApprovalDecision(decision="reject", reason="missing decision")

        decision = str(selected.get("decision", "reject"))
        reason = selected.get("reason")
        if decision != "approve":
            return ApprovalDecision(decision="reject", reason=str(reason) if reason else None)

        updated = suggestion.model_copy(
            update={
                "narrative": selected.get("narrative", suggestion.narrative),
                "duration_minutes": int(
                    selected.get("duration_minutes", suggestion.duration_minutes)
                ),
            }
        )
        try:
            return ApprovalDecision(decision="approve", edited_entry=updated)
        except ValidationError as exc:
            raise typer.BadParameter(str(exc)) from exc

    return handler


def _resolve_workspace_path(
    *,
    workspace_path: Path | None,
    current_value: str,
    non_interactive: bool,
    yes: bool,
) -> Path:
    selected = workspace_path.expanduser().resolve() if workspace_path else Path(current_value).expanduser().resolve()
    if selected.exists() and selected.is_dir():
        return selected

    if non_interactive and not yes:
        raise typer.BadParameter(
            f"workspace path does not exist: {selected} (use --yes to create it)"
        )

    if yes or typer.confirm(f"Workspace path {selected} does not exist. Create it?", default=True):
        selected.mkdir(parents=True, exist_ok=True)
        return selected

    raise typer.BadParameter(f"workspace path does not exist: {selected}")


def _resolve_playbook_path(
    *,
    playbook_path: Path | None,
    current_value: str,
    sample_playbook: Path,
    non_interactive: bool,
    yes: bool,
) -> Path:
    selected = playbook_path.expanduser().resolve() if playbook_path else Path(current_value).expanduser().resolve()
    if selected.exists() and selected.is_file():
        return selected

    if selected == sample_playbook:
        return sample_playbook

    if non_interactive:
        if yes:
            return sample_playbook
        raise typer.BadParameter(f"default playbook not found: {selected}")

    if yes or typer.confirm(
        f"Playbook {selected} was not found. Use sample playbook {sample_playbook}?",
        default=True,
    ):
        return sample_playbook

    raise typer.BadParameter(f"default playbook not found: {selected}")


def _configure_llm_section(
    *,
    cfg: MatterOSConfig,
    non_interactive: bool,
    yes: bool,
) -> None:
    if non_interactive:
        if cfg.llm.provider not in {"local", "openai", "anthropic"}:
            cfg.llm.provider = "local"
            cfg.llm.remote_enabled = False
        return

    if yes:
        return

    remote_enabled = typer.confirm(
        "Enable remote LLM providers (OpenAI/Anthropic)?",
        default=cfg.llm.remote_enabled,
    )
    cfg.llm.remote_enabled = remote_enabled
    if not remote_enabled:
        cfg.llm.provider = "local"
        return

    provider = typer.prompt(
        "Remote provider (openai/anthropic)",
        default=cfg.llm.provider if cfg.llm.provider in {"openai", "anthropic"} else "openai",
    ).strip().lower()
    if provider not in {"openai", "anthropic"}:
        raise typer.BadParameter("provider must be openai or anthropic")
    cfg.llm.provider = provider


def _llm_findings(*, adapter: LLMAdapter, provider_name: str) -> tuple[str, list[str]]:
    provider_instance = adapter.providers.get(provider_name)
    if provider_instance is None:
        return "unknown", [f"unknown provider '{provider_name}'"]

    model_name = _llm_model_name(provider_instance)
    findings: list[str] = []

    if provider_name != "local" and not adapter.allow_remote_models:
        findings.append("remote providers are disabled; set MATTEROS_ALLOW_REMOTE_MODELS=true")

    if provider_name == "openai" and not os.getenv("OPENAI_API_KEY"):
        findings.append("OPENAI_API_KEY is not configured")

    if provider_name == "anthropic" and not os.getenv("ANTHROPIC_API_KEY"):
        findings.append("ANTHROPIC_API_KEY is not configured")

    if provider_name != "local" and adapter.model_allowlist and model_name not in adapter.model_allowlist:
        findings.append(f"model '{model_name}' is not allowed by MATTEROS_LLM_MODEL_ALLOWLIST")

    return model_name, findings


def _llm_model_name(provider_instance: Any) -> str:
    value = getattr(provider_instance, "model_name", None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "unknown"


@drafts_app.command("list")
def drafts_list(
    status: str | None = typer.Option(None, "--status", help="Filter by status: pending|approved|rejected|expired"),
    limit: int = typer.Option(20, "--limit", min=1, help="Max entries to show"),
    home: Path | None = typer.Option(None, help="MatterOS home directory"),
) -> None:
    """List proactive time entry drafts."""
    home_dir = resolve_home(home)
    store = SQLiteStore(home_dir / "matteros.db")

    from matteros.drafts.manager import DraftManager

    manager = DraftManager(store)
    drafts = manager.list_drafts(status=status, limit=limit)

    if not drafts:
        typer.echo("no drafts found")
        return

    for draft in drafts:
        entry = draft.get("entry", {})
        typer.echo(
            f"{draft['id'][:8]} | {draft['status']} | matter={entry.get('matter_id', '?')} "
            f"duration={entry.get('duration_minutes', '?')}m | {draft['created_at'][:19]}"
        )


@drafts_app.command("approve")
def drafts_approve(
    draft_id: str = typer.Argument(..., help="Draft ID (or prefix)"),
    home: Path | None = typer.Option(None, help="MatterOS home directory"),
) -> None:
    """Approve a pending draft."""
    home_dir = resolve_home(home)
    store = SQLiteStore(home_dir / "matteros.db")

    from matteros.drafts.manager import DraftManager

    manager = DraftManager(store)
    draft = manager.get_draft(draft_id)
    if not draft:
        typer.echo(f"draft not found: {draft_id}")
        raise typer.Exit(code=1)
    if draft["status"] != "pending":
        typer.echo(f"draft {draft_id[:8]} is already {draft['status']}")
        raise typer.Exit(code=1)

    manager.approve_draft(draft_id)

    from matteros.learning.feedback import FeedbackTracker

    FeedbackTracker(store).record_feedback(draft_id, "approved")
    typer.echo(f"approved draft {draft_id[:8]}")


@drafts_app.command("reject")
def drafts_reject(
    draft_id: str = typer.Argument(..., help="Draft ID (or prefix)"),
    reason: str | None = typer.Option(None, "--reason", "-r", help="Rejection reason"),
    home: Path | None = typer.Option(None, help="MatterOS home directory"),
) -> None:
    """Reject a pending draft."""
    home_dir = resolve_home(home)
    store = SQLiteStore(home_dir / "matteros.db")

    from matteros.drafts.manager import DraftManager

    manager = DraftManager(store)
    draft = manager.get_draft(draft_id)
    if not draft:
        typer.echo(f"draft not found: {draft_id}")
        raise typer.Exit(code=1)

    manager.reject_draft(draft_id)

    from matteros.learning.feedback import FeedbackTracker

    FeedbackTracker(store).record_feedback(draft_id, "rejected", reason=reason)
    typer.echo(f"rejected draft {draft_id[:8]}")


@app.command("web")
def web_command(
    port: int = typer.Option(8741, "--port", help="Port to serve on"),
    open_browser: bool = typer.Option(False, "--open", help="Open browser after start"),
    home: Path | None = typer.Option(None, help="MatterOS home directory"),
) -> None:
    """Launch the web UI dashboard."""
    try:
        from matteros.web.app import create_app
    except ImportError:
        typer.echo("Web UI requires: pip install matteros[web]")
        raise typer.Exit(code=1)

    import uvicorn
    from urllib.parse import quote

    home_dir = resolve_home(home)
    app_instance = create_app(home=home_dir)
    base_url = f"http://127.0.0.1:{port}"
    token = str(getattr(app_instance.state, "web_token", ""))
    token_query_param = str(getattr(app_instance.state, "auth_query_param", "access_token"))
    bootstrap_url = (
        f"{base_url}/?{token_query_param}={quote(token, safe='')}"
        if token
        else base_url
    )

    typer.echo(f"starting MatterOS web UI on {base_url}")
    if token:
        typer.echo(f"web auth bootstrap URL (keep private): {bootstrap_url}")

    if open_browser:
        import webbrowser

        webbrowser.open(bootstrap_url)

    uvicorn.run(app_instance, host="127.0.0.1", port=port, log_level="info")


@daemon_app.command("start")
def daemon_start(
    home: Path | None = typer.Option(None, help="MatterOS home directory"),
) -> None:
    """Start the background daemon (forks into background, writes PID)."""
    import asyncio
    import signal
    import sys

    from matteros.daemon.process import ensure_not_running, remove_pid, write_pid
    from matteros.daemon.scheduler import PlaybookScheduler

    home_dir = resolve_home(home)

    try:
        ensure_not_running(home_dir)
    except RuntimeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)

    log_dir = home_dir / "daemon"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "matteros.log"

    if sys.platform == "win32":
        typer.echo("error: daemon mode requires fork() which is not available on Windows")
        typer.echo("hint: run 'matteros daemon start --foreground' or use WSL")
        raise typer.Exit(code=1)

    pid = os.fork()
    if pid > 0:
        typer.echo(f"daemon started (pid {pid})")
        typer.echo(f"log: {log_file}")
        return

    # Child process: detach and run the scheduler.
    os.setsid()
    sys.stdin.close()
    sys.stdout = open(log_file, "a", encoding="utf-8")  # noqa: SIM115
    sys.stderr = sys.stdout

    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    logger = logging.getLogger("matteros.daemon")

    pid_path = write_pid(home_dir)
    logger.info("daemon pid %d written to %s", os.getpid(), pid_path)

    scheduler = PlaybookScheduler(home_dir)

    # Set up activity watcher for workspace path.
    from matteros.daemon.watcher import ActivityWatcher

    watcher = None
    try:
        loaded = load_config(path=home_dir / "config.yml", home=home_dir)
        workspace = Path(loaded.config.paths.workspace_path).expanduser()
        if workspace.exists():
            def _on_activity(changed_paths: list[Path]) -> None:
                logger.info("activity detected: %d changed files", len(changed_paths))
                for jid in list(scheduler._jobs):
                    asyncio.run_coroutine_threadsafe(scheduler.run_once(jid), loop)

            watcher = ActivityWatcher(
                watch_paths=[workspace],
                callback=_on_activity,
            )
    except Exception:
        logger.warning("could not set up activity watcher", exc_info=True)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _handle_term(_sig: int, _frame: Any) -> None:
        logger.info("received signal %d, stopping", _sig)
        loop.call_soon_threadsafe(loop.stop)

    signal.signal(signal.SIGTERM, _handle_term)
    signal.signal(signal.SIGINT, _handle_term)

    try:
        loop.run_until_complete(scheduler.start())
        if watcher is not None:
            loop.run_until_complete(watcher.start())
        loop.run_forever()
    finally:
        if watcher is not None:
            loop.run_until_complete(watcher.stop())
        loop.run_until_complete(scheduler.stop())
        loop.close()
        remove_pid(home_dir)
        logger.info("daemon stopped")


@daemon_app.command("stop")
def daemon_stop(
    home: Path | None = typer.Option(None, help="MatterOS home directory"),
) -> None:
    """Send SIGTERM to the running daemon."""
    import signal

    from matteros.daemon.process import is_running, read_pid

    home_dir = resolve_home(home)
    pid = read_pid(home_dir)

    if pid is None or not is_running(home_dir):
        typer.echo("daemon is not running")
        raise typer.Exit(code=1)

    os.kill(pid, signal.SIGTERM)
    typer.echo(f"sent SIGTERM to daemon (pid {pid})")


@daemon_app.command("status")
def daemon_status(
    home: Path | None = typer.Option(None, help="MatterOS home directory"),
) -> None:
    """Show daemon status: running/stopped, PID, uptime."""
    from matteros.daemon.process import is_running, read_pid

    home_dir = resolve_home(home)
    pid = read_pid(home_dir)

    if pid is None or not is_running(home_dir):
        typer.echo("daemon: stopped")
        return

    typer.echo(f"daemon: running")
    typer.echo(f"pid: {pid}")

    pid_file = home_dir / "daemon" / "matteros.pid"
    if pid_file.exists():
        mtime = pid_file.stat().st_mtime
        started = datetime.fromtimestamp(mtime, tz=UTC)
        uptime = datetime.now(UTC) - started
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        typer.echo(f"uptime: {hours}h {minutes}m {seconds}s")


@daemon_app.command("logs")
def daemon_logs(
    lines: int = typer.Option(50, "--lines", "-n", min=1, help="Number of lines to show"),
    home: Path | None = typer.Option(None, help="MatterOS home directory"),
) -> None:
    """Show last N lines from daemon log."""
    home_dir = resolve_home(home)
    log_file = home_dir / "daemon" / "matteros.log"

    if not log_file.exists():
        typer.echo("no daemon log found")
        raise typer.Exit(code=1)

    all_lines = log_file.read_text(encoding="utf-8").splitlines()
    for line in all_lines[-lines:]:
        typer.echo(line)


@team_app.command("init")
def team_init(
    admin_username: str = typer.Option("admin", "--admin", help="Admin username"),
    home: Path | None = typer.Option(None, help="MatterOS home directory"),
) -> None:
    """Initialize team mode: create users table, admin account."""
    home_dir = resolve_home(home)
    store = SQLiteStore(home_dir / "matteros.db")

    from matteros.team.users import UserManager

    manager = UserManager(store)

    existing = manager.get_user_by_username(admin_username)
    if existing:
        typer.echo(f"admin user '{admin_username}' already exists")
        return

    import secrets
    from matteros.team.users import hash_password

    temp_password = secrets.token_urlsafe(16)
    password_hash = hash_password(temp_password)

    user_id = manager.create_user(
        username=admin_username,
        role="dev",
        password_hash=password_hash,
    )
    typer.echo(f"team mode initialized")
    typer.echo(f"admin user: {admin_username} (id: {user_id[:8]})")
    typer.echo(f"temporary password: {temp_password}")
    typer.echo("change this password immediately")


@team_app.command("add-user")
def team_add_user(
    username: str = typer.Argument(..., help="Username"),
    role: str = typer.Option("attorney", "--role", help="Role: admin|attorney|reviewer"),
    home: Path | None = typer.Option(None, help="MatterOS home directory"),
) -> None:
    """Add a user to the team."""
    home_dir = resolve_home(home)
    store = SQLiteStore(home_dir / "matteros.db")

    from matteros.team.users import UserManager

    manager = UserManager(store)

    existing = manager.get_user_by_username(username)
    if existing:
        typer.echo(f"user '{username}' already exists")
        raise typer.Exit(code=1)

    import secrets
    from matteros.team.users import hash_password

    temp_password = secrets.token_urlsafe(16)
    password_hash = hash_password(temp_password)

    user_id = manager.create_user(username=username, role=role, password_hash=password_hash)
    typer.echo(f"created user: {username} (role={role}, id={user_id[:8]})")
    typer.echo(f"temporary password: {temp_password}")


@team_app.command("list-users")
def team_list_users(
    home: Path | None = typer.Option(None, help="MatterOS home directory"),
) -> None:
    """List all team users."""
    home_dir = resolve_home(home)
    store = SQLiteStore(home_dir / "matteros.db")

    from matteros.team.users import UserManager

    manager = UserManager(store)
    users = manager.list_users()

    if not users:
        typer.echo("no users found (run `matteros team init` first)")
        return

    for user in users:
        typer.echo(f"{user['id'][:8]} | {user['username']} | role={user['role']} | {user['created_at'][:19]}")


@team_app.command("report")
def team_report(
    report_type: str = typer.Argument("summary", help="Report type: summary|matters|attorneys"),
    home: Path | None = typer.Option(None, help="MatterOS home directory"),
) -> None:
    """Generate team reports."""
    home_dir = resolve_home(home)
    store = SQLiteStore(home_dir / "matteros.db")

    from matteros.team.reports import TeamReports

    reports = TeamReports(store)

    if report_type == "matters":
        data = reports.hours_by_matter()
        if not data:
            typer.echo("no approved entries found")
            return
        typer.echo("hours by matter:")
        for item in data:
            typer.echo(f"  {item['matter_id']}: {item['total_hours']}h ({item['total_minutes']}m)")

    elif report_type == "attorneys":
        data = reports.hours_by_attorney()
        if not data:
            typer.echo("no approved entries found")
            return
        typer.echo("hours by attorney:")
        for item in data:
            typer.echo(f"  {item['attorney']}: {item['total_hours']}h ({item['total_minutes']}m)")

    else:
        queue = reports.approval_queue_depth()
        weekly = reports.weekly_summary()
        typer.echo("approval queue:")
        for decision, count in queue.items():
            typer.echo(f"  {decision}: {count}")
        if weekly:
            typer.echo("weekly summary:")
            for week in weekly:
                typer.echo(
                    f"  {week['week']}: {week['run_count']} runs "
                    f"({week['completed']} completed, {week['failed']} failed)"
                )


@app.command("review")
def review_command(
    limit: int = typer.Option(20, "--limit", help="Max drafts to review"),
    auto_approve: float | None = typer.Option(None, "--auto-approve", help="Auto-approve threshold (0.0-1.0)"),
    home: Path | None = typer.Option(None, help="MatterOS home directory"),
) -> None:
    """Interactive batch review of pending drafts."""
    home_dir = resolve_home(home)
    store = SQLiteStore(home_dir / "matteros.db")

    from matteros.drafts.manager import DraftManager
    from matteros.learning.feedback import FeedbackTracker

    manager = DraftManager(store)
    tracker = FeedbackTracker(store)

    drafts = manager.list_drafts(status="pending", limit=limit)
    if not drafts:
        typer.echo("no pending drafts")
        return

    approved_count = 0
    rejected_count = 0
    skipped_count = 0

    for draft in drafts:
        entry = draft.get("entry", {})
        confidence = float(entry.get("confidence", 0))

        # Auto-approve if above threshold.
        if auto_approve is not None and confidence >= auto_approve:
            manager.approve_draft(draft["id"])
            tracker.record_feedback(draft["id"], "approved")
            approved_count += 1
            typer.echo(f"  auto-approved {draft['id'][:8]} (confidence={confidence:.2f})")
            continue

        typer.echo(f"\n--- Draft {draft['id'][:8]} ---")
        typer.echo(f"  matter:     {entry.get('matter_id', '?')}")
        typer.echo(f"  duration:   {entry.get('duration_minutes', '?')}m")
        typer.echo(f"  confidence: {confidence:.2f}")
        typer.echo(f"  narrative:  {entry.get('narrative', '(none)')}")

        action = typer.prompt("[a]pprove / [r]eject / [e]dit / [s]kip / [q]uit", default="s")
        action = action.strip().lower()

        if action in ("a", "approve"):
            manager.approve_draft(draft["id"])
            tracker.record_feedback(draft["id"], "approved")
            approved_count += 1
        elif action in ("r", "reject"):
            reason = typer.prompt("reason (optional)", default="")
            manager.reject_draft(draft["id"])
            tracker.record_feedback(draft["id"], "rejected", reason=reason or None)
            rejected_count += 1
        elif action in ("e", "edit"):
            new_narrative = typer.prompt("narrative", default=entry.get("narrative", ""))
            new_duration = typer.prompt("duration_minutes", default=str(entry.get("duration_minutes", 0)))
            entry["narrative"] = new_narrative
            try:
                entry["duration_minutes"] = int(new_duration)
            except ValueError:
                pass
            manager.update_entry(draft["id"], entry)
            manager.approve_draft(draft["id"])
            tracker.record_feedback(draft["id"], "edited")
            approved_count += 1
        elif action in ("q", "quit"):
            break
        else:
            skipped_count += 1

    typer.echo(f"\n{approved_count} approved, {rejected_count} rejected, {skipped_count} skipped")


@app.command("learn")
def learn_command(
    run_id: str | None = typer.Option(None, "--run-id", help="Learn from a specific run"),
    all_runs: bool = typer.Option(False, "--all", help="Learn from all runs with approvals"),
    home: Path | None = typer.Option(None, help="MatterOS home directory"),
) -> None:
    """Trigger pattern learning from approval history."""
    home_dir = resolve_home(home)
    store = SQLiteStore(home_dir / "matteros.db")

    from matteros.learning.feedback import FeedbackTracker
    from matteros.learning.patterns import PatternEngine

    engine = PatternEngine(store)

    if run_id:
        patterns = engine.learn_from_approvals(run_id)
        typer.echo(f"learned {len(patterns)} patterns from run {run_id[:8]}")
        for p in patterns:
            typer.echo(f"  {p['pattern_type']} | matter={p['matter_id']} | confidence={p['confidence']:.2f}")
    elif all_runs:
        with store.connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT run_id FROM approvals"
            ).fetchall()
        run_ids = [row["run_id"] for row in rows]
        total_patterns = 0
        for rid in run_ids:
            patterns = engine.learn_from_approvals(rid)
            total_patterns += len(patterns)
        typer.echo(f"learned from {len(run_ids)} runs, {total_patterns} patterns total")
    else:
        typer.echo("specify --run-id ID or --all")
        raise typer.Exit(code=1)

    # Print feedback stats and pattern count.
    tracker = FeedbackTracker(store)
    stats = tracker.get_feedback_stats()
    typer.echo(f"\nfeedback stats: {stats['total']} reviews, "
               f"{stats['approved']} approved, {stats['rejected']} rejected, "
               f"approval rate={stats['approval_rate']:.1%}")

    all_patterns = engine.get_patterns()
    typer.echo(f"total stored patterns: {len(all_patterns)}")


@app.command("digest")
def digest_command(
    period: str = typer.Option("week", "--period", help="Period: day, week, or month"),
    home: Path | None = typer.Option(None, help="MatterOS home directory"),
) -> None:
    """Period summary report of tracked time."""
    from datetime import timedelta

    home_dir = resolve_home(home)
    store = SQLiteStore(home_dir / "matteros.db")

    now = datetime.now(UTC)
    if period == "day":
        cutoff = (now - timedelta(days=1)).isoformat()
    elif period == "month":
        cutoff = (now - timedelta(days=30)).isoformat()
    else:
        cutoff = (now - timedelta(days=7)).isoformat()

    typer.echo(f"--- MatterOS Digest ({period}) ---")

    # Total approved hours from drafts.
    with store.connection() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(json_extract(entry_json, '$.duration_minutes')), 0) as total_minutes
            FROM drafts
            WHERE status = 'approved' AND updated_at >= ?
            """,
            (cutoff,),
        ).fetchone()
        total_minutes = row["total_minutes"] if row else 0
        typer.echo(f"total approved hours: {total_minutes / 60:.1f}h")

        # Hours by matter.
        rows = conn.execute(
            """
            SELECT json_extract(entry_json, '$.matter_id') as matter_id,
                   SUM(json_extract(entry_json, '$.duration_minutes')) as minutes
            FROM drafts
            WHERE status = 'approved' AND updated_at >= ?
            GROUP BY matter_id
            ORDER BY minutes DESC
            """,
            (cutoff,),
        ).fetchall()
        if rows:
            typer.echo("\nhours by matter:")
            for r in rows:
                mid = r["matter_id"] or "UNASSIGNED"
                mins = r["minutes"] or 0
                typer.echo(f"  {mid:20s} {mins / 60:.1f}h")

        # Pending drafts.
        pending_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM drafts WHERE status = 'pending'"
        ).fetchone()
        typer.echo(f"\npending drafts: {pending_row['cnt']}")

        # Approval rate from feedback_log.
        fb_rows = conn.execute(
            "SELECT action, COUNT(*) as cnt FROM feedback_log GROUP BY action"
        ).fetchall()
        fb_counts: dict[str, int] = {r["action"]: r["cnt"] for r in fb_rows}
        fb_total = sum(fb_counts.values())
        fb_approved = fb_counts.get("approved", 0) + fb_counts.get("edited", 0)
        if fb_total > 0:
            typer.echo(f"approval rate: {fb_approved / fb_total:.1%} ({fb_total} reviews)")
        else:
            typer.echo("approval rate: n/a (no reviews)")

        # Weekly trends from runs.
        trend_rows = conn.execute(
            """
            SELECT strftime('%Y-W%W', started_at) as week,
                   COUNT(*) as run_count,
                   SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as ok,
                   SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
            FROM runs
            GROUP BY week
            ORDER BY week DESC
            LIMIT 4
            """
        ).fetchall()
        if trend_rows:
            typer.echo("\nweekly trends:")
            for tr in trend_rows:
                typer.echo(f"  {tr['week']}: {tr['run_count']} runs ({tr['ok']} ok, {tr['failed']} failed)")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
