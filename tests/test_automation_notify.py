"""Tests for privilege-safe Slack notification helper."""
from __future__ import annotations
from matteros.automation.notify import build_alert_message

def test_non_privileged_includes_title():
    msg = build_alert_message(
        matter_id="m1", matter_title="NDA Review", privileged=False,
        text="Deadline approaching: Filing — due in 7 days",
    )
    assert "NDA Review" in msg
    assert "Deadline approaching" in msg

def test_privileged_redacts_title():
    msg = build_alert_message(
        matter_id="m1", matter_title="Secret Litigation", privileged=True,
        text="Deadline approaching: Filing — due in 7 days",
    )
    assert "Secret Litigation" not in msg
    assert "Matter #m1" in msg

def test_privileged_redacts_detail_text():
    msg = build_alert_message(
        matter_id="m1", matter_title="Secret", privileged=True,
        text="No activity for 14 days",
    )
    assert "Secret" not in msg
    assert "m1" in msg
