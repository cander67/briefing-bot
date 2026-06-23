"""Integration tests for email sending (SMTP mocked)."""

from __future__ import annotations

import pytest
import send_briefing_email
from pydantic import ValidationError
from send_briefing_email import _send_email, load_recipients


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
