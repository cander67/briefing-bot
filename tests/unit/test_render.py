"""Unit tests for render_briefing helpers."""

from __future__ import annotations

from datetime import timezone

from render_briefing import _format_published
from send_briefing_email import markdown_to_html


class TestFormatPublished:
    def test_empty_returns_unknown(self):
        assert _format_published("", timezone.utc) == "Unknown"

    def test_parses_iso_utc(self):
        out = _format_published("2026-06-23T17:30:00+00:00", timezone.utc)
        assert "2026" in out and "PM" in out

    def test_handles_z_suffix(self):
        out = _format_published("2026-06-23T17:30:00Z", timezone.utc)
        assert "2026" in out

    def test_unparseable_returns_raw(self):
        assert _format_published("not-a-date", timezone.utc) == "not-a-date"


class TestMarkdownToHtml:
    def test_wraps_html_document(self):
        out = markdown_to_html("# Title\n\nSome text.")
        assert "<html>" in out and "</html>" in out

    def test_heading_becomes_tag(self):
        out = markdown_to_html("# Daily Briefing")
        assert "<h1>" in out and "Daily Briefing" in out
