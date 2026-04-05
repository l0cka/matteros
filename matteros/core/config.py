from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class ConfigError(RuntimeError):
    """Raised when MatterOS config cannot be parsed or saved."""


CURRENT_CONFIG_VERSION = 1


class ProfileConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "default"


class PathsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    default_playbook: str
    fixtures_root: str | None = None


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = "local"
    remote_enabled: bool = False
    model_allowlist: list[str] = Field(default_factory=list)


class MSGraphConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = "common"
    scopes: str = "offline_access User.Read Mail.Read Calendars.Read"
    auth_pending: bool = True


class OnboardingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = CURRENT_CONFIG_VERSION
    completed_at: str | None = None
    last_smoke_test_status: str | None = None
    last_smoke_test_run_id: str | None = None


class ConnectorsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slack_enabled: bool = False
    jira_enabled: bool = False
    github_enabled: bool = False
    ical_enabled: bool = True


class AutomationsConfig(BaseModel):
    model_config = ConfigDict(extra="allow")


class MatterOSConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config_version: int = CURRENT_CONFIG_VERSION
    log_level: str = "info"
    profile: ProfileConfig
    paths: PathsConfig
    llm: LLMConfig = Field(default_factory=LLMConfig)
    ms_graph: MSGraphConfig = Field(default_factory=MSGraphConfig)
    onboarding: OnboardingConfig = Field(default_factory=OnboardingConfig)
    connectors: ConnectorsConfig = Field(default_factory=ConnectorsConfig)
    automations: AutomationsConfig = Field(default_factory=AutomationsConfig)


class LoadedConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: MatterOSConfig
    existed: bool
    migrated: bool = False
    raw_legacy_payload: dict[str, Any] | None = None


def default_config(*, home: Path, profile: str = "default") -> MatterOSConfig:
    workspace = Path.cwd().resolve()
    default_playbook = (home / "playbooks" / "daily_time_capture.yml").resolve()
    fixtures_root = (home / "fixtures" / "ms_graph").resolve()

    return MatterOSConfig(
        profile=ProfileConfig(name=profile),
        paths=PathsConfig(
            workspace_path=str(workspace),
            default_playbook=str(default_playbook),
            fixtures_root=str(fixtures_root),
        ),
    )


def load_config(*, path: Path, home: Path) -> LoadedConfig:
    if not path.exists():
        return LoadedConfig(config=default_config(home=home), existed=False)

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid config yaml at {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("config root must be a mapping")

    # New structured config.
    if "config_version" in raw:
        try:
            parsed = MatterOSConfig.model_validate(raw)
        except Exception as exc:
            raise ConfigError(f"invalid config schema: {exc}") from exc
        return LoadedConfig(config=_normalize_config_paths(parsed), existed=True)

    # Legacy flat config migration.
    migrated_payload = _migrate_legacy_payload(raw, home=home)
    try:
        parsed = MatterOSConfig.model_validate(migrated_payload)
    except Exception as exc:
        raise ConfigError(f"failed to migrate legacy config: {exc}") from exc

    return LoadedConfig(
        config=_normalize_config_paths(parsed),
        existed=True,
        migrated=True,
        raw_legacy_payload=raw,
    )


def save_config_atomic(*, config: MatterOSConfig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")

    payload = config.model_dump(mode="json")
    content = yaml.safe_dump(payload, sort_keys=False)

    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def backup_legacy_config(*, config_path: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    backup_path = config_path.with_name(f"{config_path.name}.bak.{timestamp}")
    backup_path.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup_path


def _normalize_config_paths(config: MatterOSConfig) -> MatterOSConfig:
    normalized = config.model_copy(deep=True)

    normalized.paths.workspace_path = str(Path(normalized.paths.workspace_path).expanduser().resolve())
    normalized.paths.default_playbook = str(Path(normalized.paths.default_playbook).expanduser().resolve())
    if normalized.paths.fixtures_root:
        normalized.paths.fixtures_root = str(Path(normalized.paths.fixtures_root).expanduser().resolve())

    return normalized


def _migrate_legacy_payload(payload: dict[str, Any], *, home: Path) -> dict[str, Any]:
    model_provider = str(payload.get("model_provider", "local"))
    log_level = str(payload.get("log_level", "info"))
    tenant_id = str(payload.get("ms_graph_tenant_id", "common"))
    scopes = str(payload.get("ms_graph_scopes", "offline_access User.Read Mail.Read Calendars.Read"))

    remote_enabled = model_provider in {"openai", "anthropic"}

    migrated = default_config(home=home).model_dump(mode="json")

    # Preserve compatible nested sections when present in pre-versioned configs.
    for section in ("profile", "paths", "llm", "ms_graph", "onboarding", "connectors"):
        value = payload.get(section)
        if isinstance(value, dict):
            merged = dict(migrated.get(section, {}))
            merged.update(value)
            migrated[section] = merged

    # Preserve commonly-seen flat path/profile keys from older config variants.
    workspace_path = payload.get("workspace_path")
    if isinstance(workspace_path, str) and workspace_path.strip():
        migrated["paths"]["workspace_path"] = workspace_path

    default_playbook = payload.get("default_playbook")
    if isinstance(default_playbook, str) and default_playbook.strip():
        migrated["paths"]["default_playbook"] = default_playbook

    fixtures_root = payload.get("fixtures_root")
    if isinstance(fixtures_root, str) and fixtures_root.strip():
        migrated["paths"]["fixtures_root"] = fixtures_root

    profile_name = payload.get("profile_name")
    if isinstance(profile_name, str) and profile_name.strip():
        migrated["profile"]["name"] = profile_name

    profile_payload = payload.get("profile")
    if isinstance(profile_payload, str) and profile_payload.strip():
        migrated["profile"]["name"] = profile_payload

    migrated["log_level"] = log_level
    migrated["llm"]["provider"] = model_provider
    migrated["llm"]["remote_enabled"] = remote_enabled
    migrated["ms_graph"]["tenant_id"] = tenant_id
    migrated["ms_graph"]["scopes"] = scopes

    return migrated


def config_json(config: MatterOSConfig) -> str:
    return json.dumps(config.model_dump(mode="json"), sort_keys=True)
