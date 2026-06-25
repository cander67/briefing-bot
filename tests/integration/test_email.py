"""Integration tests for email sending (SMTP mocked)."""

from __future__ import annotations

import pytest
import send_briefing_email
from pydantic import ValidationError
from send_briefing_email import (
    _resolve_smtp,
    _send_email,
    load_config,
    load_recipients,
    send_briefing_email as send_daily_briefing_email,
    send_failure_alert,
)


class FakeSMTP:
    sent: list = []

    def __init__(self, host, port):
        self.host = host
        self.port = port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        self.user = user

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


class BrokenSMTP(FakeSMTP):
    def send_message(self, msg):
        raise RuntimeError("smtp exploded")


@pytest.fixture
def smtp_env(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "bot@test")
    monkeypatch.setenv("SMTP_PASS", "secret")
    FakeSMTP.sent = []
    monkeypatch.setattr(send_briefing_email.smtplib, "SMTP", FakeSMTP)


def test_send_email_builds_and_sends(smtp_env):
    ok = _send_email(
        {"email": {}},
        subject="Test",
        text_body="hello",
        to_emails=["a@test"],
        cc_emails=["b@test"],
        html_body="<p>hello</p>",
    )
    assert ok is True
    assert len(FakeSMTP.sent) == 1
    msg = FakeSMTP.sent[0]
    assert msg["Subject"] == "Test"
    assert "a@test" in msg["To"]


def test_dry_run_sends_nothing(smtp_env):
    ok = _send_email(
        {"email": {}}, subject="T", text_body="b", to_emails=["a@test"], dry_run=True
    )
    assert ok is True
    assert FakeSMTP.sent == []


def test_missing_smtp_config_returns_false(monkeypatch):
    for var in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS"):
        monkeypatch.delenv(var, raising=False)
    ok = _send_email({"email": {}}, subject="T", text_body="b", to_emails=["a@test"])
    assert ok is False


def test_no_recipients_returns_false(smtp_env):
    ok = _send_email({"email": {}}, subject="T", text_body="b", to_emails=[])
    assert ok is False


def test_resolve_smtp_prefers_env_over_config(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "env.smtp.test")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_USER", "env-user")
    monkeypatch.setenv("SMTP_PASS", "env-pass")

    out = _resolve_smtp(
        {
            "smtp_host": "cfg.smtp.test",
            "smtp_port": 587,
            "smtp_user": "cfg-user",
            "smtp_pass": "cfg-pass",
        }
    )
    assert out == ("env.smtp.test", 2525, "env-user", "env-pass")


def test_send_email_returns_false_on_smtp_exception(monkeypatch, smtp_env):
    monkeypatch.setattr(send_briefing_email.smtplib, "SMTP", BrokenSMTP)

    ok = _send_email({"email": {}}, subject="T", text_body="b", to_emails=["a@test"])
    assert ok is False


def test_load_config_reads_real_config(repo_root):
    cfg = load_config(repo_root / "config" / "daily_ap.yaml")
    assert cfg["briefing"]["name"]


def test_send_briefing_email_returns_false_when_disabled(sample_config):
    sample_config["email"]["enabled"] = False
    assert send_daily_briefing_email(sample_config, "2026-06-25") is False


def test_send_briefing_email_returns_false_when_recipients_file_missing(sample_config, tmp_path):
    sample_config["output"]["output_dir"] = str(tmp_path)
    sample_config["email"]["recipients_file"] = str(tmp_path / "missing.yaml")

    assert send_daily_briefing_email(sample_config, "2026-06-25") is False


def test_send_briefing_email_returns_false_when_email_body_missing(sample_config, tmp_path):
    recipients_path = tmp_path / "recipients.yaml"
    recipients_path.write_text("recipients:\n  to:\n    - a@test\n  cc: []\n  bcc: []\n")
    sample_config["output"]["output_dir"] = str(tmp_path)
    sample_config["email"]["recipients_file"] = str(recipients_path)

    run_dir = tmp_path / "2026-06-25"
    run_dir.mkdir()

    assert send_daily_briefing_email(sample_config, "2026-06-25") is False


def test_send_briefing_email_builds_html_body_when_briefing_exists(sample_config, tmp_path, monkeypatch):
    captured = {}

    def fake_send_email(config, subject, text_body, to_emails, cc_emails=None, bcc_emails=None, html_body=None, dry_run=False):
        captured["subject"] = subject
        captured["text_body"] = text_body
        captured["to_emails"] = to_emails
        captured["html_body"] = html_body
        captured["dry_run"] = dry_run
        return True

    recipients_path = tmp_path / "recipients.yaml"
    recipients_path.write_text("recipients:\n  to:\n    - a@test\n  cc:\n    - c@test\n  bcc:\n    - b@test\n")
    run_dir = tmp_path / "2026-06-25"
    run_dir.mkdir()
    (run_dir / "email_body.txt").write_text("plain body")
    (run_dir / "briefing.md").write_text("# Daily Briefing\n\n**Lead**")

    sample_config["output"]["output_dir"] = str(tmp_path)
    sample_config["email"]["recipients_file"] = str(recipients_path)
    monkeypatch.setattr(send_briefing_email, "_send_email", fake_send_email)

    ok = send_daily_briefing_email(sample_config, "2026-06-25", dry_run=True)
    assert ok is True
    assert captured["subject"] == "Daily AP News Briefing — 2026-06-25"
    assert captured["to_emails"] == ["a@test"]
    assert "<h1>Daily Briefing</h1>" in captured["html_body"]
    assert "<p><strong>Lead</strong></p>" in captured["html_body"]
    assert captured["dry_run"] is True


def test_send_failure_alert_returns_false_when_recipients_file_missing(sample_config, tmp_path):
    sample_config["email"]["recipients_file"] = str(tmp_path / "missing.yaml")
    assert send_failure_alert(sample_config, "Subject", "Body") is False


def test_send_failure_alert_returns_false_when_to_list_empty(sample_config, tmp_path):
    recipients_path = tmp_path / "recipients.yaml"
    recipients_path.write_text("recipients:\n  to: []\n  cc:\n    - c@test\n  bcc: []\n")
    sample_config["email"]["recipients_file"] = str(recipients_path)

    assert send_failure_alert(sample_config, "Subject", "Body") is False


def test_send_failure_alert_delegates_to_send_email(sample_config, tmp_path, monkeypatch):
    captured = {}

    def fake_send_email(config, subject, text_body, to_emails, cc_emails=None, bcc_emails=None, html_body=None, dry_run=False):
        captured["subject"] = subject
        captured["text_body"] = text_body
        captured["to_emails"] = to_emails
        return True

    recipients_path = tmp_path / "recipients.yaml"
    recipients_path.write_text("recipients:\n  to:\n    - a@test\n  cc: []\n  bcc: []\n")
    sample_config["email"]["recipients_file"] = str(recipients_path)
    monkeypatch.setattr(send_briefing_email, "_send_email", fake_send_email)

    assert send_failure_alert(sample_config, "Failure", "Body") is True
    assert captured == {
        "subject": "Failure",
        "text_body": "Body",
        "to_emails": ["a@test"],
    }


def test_main_exits_with_success_code(monkeypatch):
    monkeypatch.setattr(send_briefing_email, "load_config", lambda path: {"ok": True})
    monkeypatch.setattr(send_briefing_email, "send_briefing_email", lambda config, run_date, dry_run=False: True)
    monkeypatch.setattr(
        "sys.argv",
        ["send_briefing_email.py", "--config", "config/daily_ap.yaml", "--date", "2026-06-25", "--dry-run"],
    )

    with pytest.raises(SystemExit, match="0"):
        send_briefing_email.main()


class TestLoadRecipients:
    def test_valid(self, tmp_path):
        f = tmp_path / "recipients.yaml"
        f.write_text("recipients:\n  to:\n    - a@test\n  cc: []\n  bcc: []\n")
        out = load_recipients(f)
        assert out["recipients"]["to"] == ["a@test"]

    def test_malformed_fails(self, tmp_path):
        f = tmp_path / "recipients.yaml"
        f.write_text("to:\n  - a@test\n")  # missing top-level 'recipients'
        with pytest.raises(ValidationError):
            load_recipients(f)
