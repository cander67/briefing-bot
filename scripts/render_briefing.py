#!/usr/bin/env python3
"""Render final briefing markdown from summarized articles."""

from __future__ import annotations

import json
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

load_dotenv()


def _format_published(raw: str, local_tz: Any) -> str:
    """Parse an ISO timestamp and return a human-readable local-time string."""
    if not raw:
        return "Unknown"
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(local_tz).strftime("%-I:%M %p %Z, %b %-d %Y")
    except Exception:
        return raw


def render_briefing(
    summarized_articles: list[dict[str, Any]],
    config: dict[str, Any],
    output_dir: Path,
    run_date: str,
) -> tuple[Path, Path]:
    """Render briefing.md and email_body.txt from summaries."""

    timezone_str = config["briefing"]["timezone"]
    local_tz: tzinfo
    try:
        local_tz = ZoneInfo(timezone_str)
    except Exception:
        local_tz = timezone.utc

    generated = datetime.now(local_tz).strftime("%-I:%M %p %Z, %b %-d %Y")

    # Preserve config section order without emitting section headers.
    section_order = list(config["sources"]["apnews"]["sections"].keys())
    sections: dict[str, list[dict[str, Any]]] = {}
    for a in summarized_articles:
        section = a.get("section", "UNKNOWN").lower()
        sections.setdefault(section, []).append(a)

    # Build markdown
    md_lines = [
        f"# Daily AP News Briefing — {run_date}",
        "",
        f"Generated: {generated}",
        "Sources: AP News",
        "",
    ]

    story_num = 0
    for section_key in section_order:
        for a in sections.get(section_key, []):
            story_num += 1
            pub = _format_published(a.get("published_at", ""), local_tz)
            md_lines.append(f"### {story_num}. {a.get('headline', 'Untitled')}")
            md_lines.append("")
            md_lines.append(f"**Source:** {a.get('source', 'AP News')}")
            md_lines.append(f"**Published:** {pub}")
            md_lines.append(f"**Link:** {a.get('url', '')}")
            md_lines.append("")
            md_lines.append(a.get("summary", ""))
            md_lines.append("")
            why = a.get("why_it_matters", "")
            if why:
                md_lines.append(f"**Why it matters:** {why}")
            md_lines.append("")

    md_content = "\n".join(md_lines)

    briefing_path = output_dir / "briefing.md"
    briefing_path.write_text(md_content, encoding="utf-8")

    # Create email body (plain text version)
    email_lines = [
        f"Daily AP News Briefing — {run_date}",
        "=" * 50,
        f"Generated: {generated}",
        "Sources: AP News",
        "",
    ]

    story_num = 0
    for section_key in section_order:
        for a in sections.get(section_key, []):
            story_num += 1
            pub = _format_published(a.get("published_at", ""), local_tz)
            email_lines.append(f"\n{story_num}. {a.get('headline', 'Untitled')}")
            email_lines.append(f"   Source: {a.get('source', 'AP News')}")
            email_lines.append(f"   Published: {pub}")
            email_lines.append(f"   Link: {a.get('url', '')}")
            email_lines.append(f"   {a.get('summary', '')}")
            why = a.get("why_it_matters", "")
            if why:
                email_lines.append(f"   Why it matters: {why}")

    email_content = "\n".join(email_lines)
    email_path = output_dir / "email_body.txt"
    email_path.write_text(email_content, encoding="utf-8")

    return briefing_path, email_path


def main():
    """Standalone test."""
    config = yaml.safe_load(Path("config/daily_ap.yaml").read_text())
    with open("outputs/2026-06-17/summarized_articles.json") as f:
        summarized = json.load(f)

    output_dir = Path(config["output"]["output_dir"]).expanduser().resolve() / "2026-06-17"
    run_date = "2026-06-17"

    briefing_path, email_path = render_briefing(summarized, config, output_dir, run_date)
    print(f"Rendered briefing to {briefing_path}")
    print(f"Rendered email to {email_path}")


if __name__ == "__main__":
    main()
