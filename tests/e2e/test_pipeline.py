"""End-to-end pipeline tests.

The default test drives the full orchestrator offline (discovery + extraction
patched, LLM/email skipped via --dry-run). The live test is opt-in.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

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


def test_full_pipeline_skips_when_briefing_already_exists(monkeypatch, tmp_path, repo_root):
    monkeypatch.setenv("BRIEFING_OUTPUT_DIR", str(tmp_path))
    monkeypatch.chdir(repo_root)

    today = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")
    run_dir = tmp_path / today
    run_dir.mkdir(parents=True)
    (run_dir / "briefing.md").write_text("already rendered")

    config_path = repo_root / "config" / "daily_ap.yaml"
    monkeypatch.setattr(
        "sys.argv",
        ["run_daily_briefing.py", "--config", str(config_path)],
    )

    rc = run_daily_briefing.main()
    assert rc == 0
    assert not (run_dir / "progress.json").exists()
    assert not (run_dir / "run_log.json").exists()


def test_extract_phase_reuses_cached_extractions(monkeypatch, tmp_path, repo_root):
    class TrackingExtractor:
        seen_urls: list[str] = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def extract_batch(self, candidates: list[dict]) -> list[ExtractedArticle]:
            TrackingExtractor.seen_urls = [c["url"] for c in candidates]
            return [
                ExtractedArticle(
                    candidate_url=candidates[0]["url"],
                    source="apnews",
                    section="world",
                    title="Fresh title",
                    published_at=_fresh_iso(),
                    extracted_text="Body text. " * 100,
                    extracted_markdown="# Fresh\n\nBody.",
                    chars_extracted=1100,
                    extraction_success=True,
                    url_after_redirect=candidates[0]["url"],
                )
            ]

    monkeypatch.setenv("BRIEFING_OUTPUT_DIR", str(tmp_path))
    monkeypatch.chdir(repo_root)
    monkeypatch.setattr(run_daily_briefing, "FirecrawlExtractor", TrackingExtractor)

    today = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")
    run_dir = tmp_path / today
    run_dir.mkdir(parents=True)

    candidates = [c.model_dump(mode="json") for c in _candidates()]
    (run_dir / "candidate_articles.json").write_text(json.dumps(candidates))
    cached = [
        {
            "candidate_url": candidates[0]["url"],
            "source": "apnews",
            "section": "us",
            "title": "Cached title",
            "published_at": _fresh_iso(),
            "extracted_text": "Body text. " * 100,
            "extracted_markdown": "# Cached\n\nBody.",
            "chars_extracted": 1100,
            "extraction_success": True,
            "url_after_redirect": candidates[0]["url"],
            "metadata": {},
        }
    ]
    (run_dir / "extracted_articles.json").write_text(json.dumps(cached))

    config_path = repo_root / "config" / "daily_ap.yaml"
    monkeypatch.setattr(
        "sys.argv",
        ["run_daily_briefing.py", "--config", str(config_path), "--phase", "extract"],
    )

    rc = run_daily_briefing.main()
    assert rc == 0
    assert TrackingExtractor.seen_urls == [candidates[1]["url"]]

    extracted = json.loads((run_dir / "extracted_articles.json").read_text())
    assert [item["candidate_url"] for item in extracted] == [c["url"] for c in candidates]

    run_log = json.loads((run_dir / "run_log.json").read_text())
    assert run_log["steps"]["extraction"]["from_cache"] == 1
    assert run_log["status"] == "completed"


def test_send_phase_marks_run_failed_and_alerts_when_email_send_fails(monkeypatch, tmp_path, repo_root):
    alerts: list[tuple[str, str]] = []

    def fake_render_briefing(candidates_data, cfg, run_dir, today):
        briefing_path = run_dir / "briefing.md"
        email_path = run_dir / "email_body.txt"
        briefing_path.write_text("# Briefing")
        email_path.write_text("body")
        return briefing_path, email_path

    def fake_alert_failure(cfg, subject, body):
        alerts.append((subject, body))

    monkeypatch.setenv("BRIEFING_OUTPUT_DIR", str(tmp_path))
    monkeypatch.chdir(repo_root)
    monkeypatch.setattr("render_briefing.render_briefing", fake_render_briefing)
    monkeypatch.setattr("send_briefing_email.send_briefing_email", lambda *a, **k: False)
    monkeypatch.setattr(run_daily_briefing, "alert_failure", fake_alert_failure)

    today = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")
    run_dir = tmp_path / today
    run_dir.mkdir(parents=True)
    (run_dir / "candidate_articles.json").write_text(json.dumps([_candidates()[0].model_dump(mode="json")]))

    config_path = repo_root / "config" / "daily_ap.yaml"
    monkeypatch.setattr(
        "sys.argv",
        ["run_daily_briefing.py", "--config", str(config_path), "--phase", "send", "--send"],
    )

    with pytest.raises(RuntimeError, match="Briefing email failed to send"):
        run_daily_briefing.main()

    assert alerts
    assert "FAILED" in alerts[0][0]

    progress = json.loads((run_dir / "progress.json").read_text())
    assert progress["phase"] == "failed"

    run_log = json.loads((run_dir / "run_log.json").read_text())
    assert run_log["status"] == "failed"
    assert run_log["steps"]["email"]["status"] == "failed"


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
