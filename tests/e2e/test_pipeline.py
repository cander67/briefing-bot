"""End-to-end pipeline tests.

The default test drives the full orchestrator offline (discovery + extraction
patched, LLM/email skipped via --dry-run). The live test is opt-in.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest
import run_daily_briefing
from discover_articles import CandidateArticle
from extract_articles import ExtractedArticle


def _fresh_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


class FakeExtractor:
    """Stand-in for FirecrawlExtractor that returns fresh, filter-passing articles."""

    def __init__(self, **kwargs):
        pass

    def extract_batch(self, candidates: list[dict]) -> list[ExtractedArticle]:
        return [
            ExtractedArticle(
                candidate_url=c["url"],
                source="apnews",
                section=c.get("section", "us"),
                title=f"Title for {c['url']}",
                published_at=_fresh_iso(),
                extracted_text="Body text. " * 100,
                extracted_markdown="# Title\n\nBody.",
                chars_extracted=1100,
                extraction_success=True,
                url_after_redirect=c["url"],
            )
            for c in candidates
        ]


def _candidates() -> list[CandidateArticle]:
    return [
        CandidateArticle(
            source="apnews", section="us",
            url="https://apnews.com/article/us-one-aaaaaaaa11112222", title="US One",
        ),
        CandidateArticle(
            source="apnews", section="world",
            url="https://apnews.com/article/world-one-bbbbbbbb33334444", title="World One",
        ),
    ]


def test_full_pipeline_dry_run(monkeypatch, tmp_path, repo_root):
    monkeypatch.setenv("BRIEFING_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(run_daily_briefing, "discover_all_sections", lambda cfg: _candidates())
    monkeypatch.setattr(run_daily_briefing, "FirecrawlExtractor", FakeExtractor)

    config_path = repo_root / "config" / "daily_ap.yaml"
    monkeypatch.setattr(
        "sys.argv",
        ["run_daily_briefing.py", "--config", str(config_path), "--dry-run", "--force"],
    )
    # Orchestrator reads prompt files / cwd-relative paths from the repo root.
    monkeypatch.chdir(repo_root)

    rc = run_daily_briefing.main()
    assert rc == 0

    run_dirs = list(tmp_path.iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]

    for name in (
        "candidate_articles.json",
        "extracted_articles.json",
        "filtered_articles.json",
        "evaluated_articles.json",
        "summarized_articles.json",
        "briefing.md",
        "email_body.txt",
        "run_log.json",
    ):
        assert (run_dir / name).exists(), f"missing artifact: {name}"

    candidates = json.loads((run_dir / "candidate_articles.json").read_text())
    assert sorted(candidates[0].keys()) == [
        "discovered_at", "section", "source", "title", "url",
    ]
    run_log = json.loads((run_dir / "run_log.json").read_text())
    assert run_log["status"] == "completed"


@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("RUN_LIVE_TESTS") != "1",
    reason="live test: set RUN_LIVE_TESTS=1 to run against real Firecrawl",
)
def test_live_firecrawl_extraction():
    from extract_articles import FirecrawlExtractor

    ext = FirecrawlExtractor()  # requires FIRECRAWL_API_KEY
    art = ext.extract_article(
        {
            "url": "https://apnews.com/hub/ap-top-news",
            "source": "apnews",
            "section": "us",
        }
    )
    assert art.extraction_success is True
    assert art.chars_extracted > 0
