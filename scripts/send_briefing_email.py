#!/usr/bin/env python3
"""Send briefing email via SMTP."""

from __future__ import annotations

import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).parent))

load_dotenv()


class Recipients(BaseModel):
    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)


class RecipientsConfig(BaseModel):
    recipients: Recipients


def load_config(path: Path) -> dict:
    from config_loader import load_config as _load_config
    return _load_config(path)


def load_recipients(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    RecipientsConfig.model_validate(raw)
    return raw


def send_briefing_email(
    config: dict,
    run_date: str,
    dry_run: bool = False,
) -> bool:
    """Send the briefing email to configured recipients."""

    email_cfg = config.get("email", {})
    if not email_cfg.get("enabled", False):
        print("[email] Email sending is disabled in config")
        return False

    # Load recipients
    recipients_file = Path(email_cfg.get("recipients_file", "config/recipients.yaml"))
    if not recipients_file.exists():
        print(f"[email] Recipients file not found: {recipients_file}")
        return False

    recipients_cfg = load_recipients(recipients_file)
    to_emails = recipients_cfg.get("recipients", {}).get("to", [])
    cc_emails = recipients_cfg.get("recipients", {}).get("cc", [])
    bcc_emails = recipients_cfg.get("recipients", {}).get("bcc", [])

    all_recipients = to_emails + cc_emails + bcc_emails
    if not all_recipients:
        print("[email] No recipients configured")
        return False

    # Load email body
    output_root = Path(config["output"]["output_dir"]).expanduser().resolve()
    run_dir = output_root / run_date
    email_body_path = run_dir / "email_body.txt"

    if not email_body_path.exists():
        print(f"[email] Email body not found: {email_body_path}")
        return False

    body = email_body_path.read_text(encoding="utf-8")

    # Build subject
    subject_template = email_cfg.get("subject_template", "Daily AP News Briefing — {date}")
    subject = subject_template.format(date=run_date)

    # Try to attach HTML version from briefing.md
    briefing_path = run_dir / "briefing.md"
    html_body = None
    if briefing_path.exists():
        html_body = markdown_to_html(briefing_path.read_text(encoding="utf-8"))

    return _send_email(
        config,
        subject=subject,
        text_body=body,
        to_emails=to_emails,
        cc_emails=cc_emails,
        bcc_emails=bcc_emails,
        html_body=html_body,
        dry_run=dry_run,
    )


def _resolve_smtp(email_cfg: dict) -> tuple[str | None, int, str | None, str | None]:
    """Resolve SMTP settings from env (preferred) then email config."""
    smtp_host = os.getenv("SMTP_HOST") or email_cfg.get("smtp_host")
    smtp_port = int(os.getenv("SMTP_PORT") or email_cfg.get("smtp_port", 587))
    smtp_user = os.getenv("SMTP_USER") or email_cfg.get("smtp_user")
    smtp_pass = os.getenv("SMTP_PASS") or email_cfg.get("smtp_pass")
    return smtp_host, smtp_port, smtp_user, smtp_pass


def _send_email(
    config: dict,
    subject: str,
    text_body: str,
    to_emails: list[str],
    cc_emails: list[str] | None = None,
    bcc_emails: list[str] | None = None,
    html_body: str | None = None,
    dry_run: bool = False,
) -> bool:
    """Build and send a single email via SMTP. Returns True on success."""
    cc_emails = cc_emails or []
    bcc_emails = bcc_emails or []
    all_recipients = to_emails + cc_emails + bcc_emails
    if not all_recipients:
        print("[email] No recipients configured")
        return False

    smtp_host, smtp_port, smtp_user, smtp_pass = _resolve_smtp(config.get("email", {}))
    if not smtp_host or not smtp_user or not smtp_pass:
        print("[email] Missing SMTP configuration (host, user, pass)")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = ", ".join(to_emails)
    if cc_emails:
        msg["Cc"] = ", ".join(cc_emails)

    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    if html_body:
        msg.attach(MIMEText(html_body, "html", "utf-8"))

    if dry_run:
        print("[email] DRY RUN - would send to:", all_recipients)
        print(f"[email] Subject: {subject}")
        print(f"[email] From: {smtp_user}")
        return True

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        print(f"[email] Sent to {len(all_recipients)} recipients")
        return True
    except Exception as e:
        print(f"[email] Failed to send: {e}")
        return False


def send_failure_alert(config: dict, subject: str, body: str) -> bool:
    """Send a plain-text failure/alert email to the configured recipients."""
    email_cfg = config.get("email", {})
    recipients_file = Path(email_cfg.get("recipients_file", "config/recipients.yaml"))
    if not recipients_file.exists():
        print(f"[email] Recipients file not found for alert: {recipients_file}")
        return False

    recipients_cfg = load_recipients(recipients_file)
    to_emails = recipients_cfg.get("recipients", {}).get("to", [])
    if not to_emails:
        print("[email] No recipients configured for alert")
        return False

    return _send_email(config, subject=subject, text_body=body, to_emails=to_emails)


def markdown_to_html(md: str) -> str:
    """Simple markdown to HTML conversion."""
    lines = md.split("\n")
    html_lines = ["<html><body style='font-family: Arial, sans-serif; line-height: 1.6; max-width: 800px; margin: 0 auto; padding: 20px;'>"]

    for line in lines:
        if line.startswith("# "):
            html_lines.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            html_lines.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("### "):
            html_lines.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("**") and line.endswith("**"):
            html_lines.append(f"<p><strong>{line[2:-2]}</strong></p>")
        elif line.startswith("**"):
            # Bold inline - simple replace
            line = line.replace("**", "<strong>", 1).replace("**", "</strong>", 1)
            html_lines.append(f"<p>{line}</p>")
        elif line and not line.startswith("---"):
            html_lines.append(f"<p>{line}</p>")

    html_lines.append("</body></html>")
    return "\n".join(html_lines)


def main():
    """Standalone test."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    success = send_briefing_email(config, args.date, dry_run=args.dry_run)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()