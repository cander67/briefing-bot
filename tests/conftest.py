"""Shared fixtures: path setup, sample config, and per-stage article data."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"

# scripts/ uses bare intra-package imports (e.g. `from config_loader import ...`),
# mirroring the sys.path.insert the orchestrator does at runtime.
sys.path.insert(0, str(SCRIPTS))


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def sample_config() -> dict:
    """A minimal but valid BriefingConfig-shaped config."""
    return {
        "briefing": {
            "name": "test_briefing",
            "timezone": "America/Los_Angeles",
            "max_total_stories": 10,
            "language": "en",
        },
        "sources": {
            "apnews": {
                "allowed_domains": ["apnews.com"],
                "sections": {
                    "us": {
                        "section_urls": ["https://apnews.com/us-news"],
                        "max_stories": 2,
                        "topic_description": "US news",
                    },
                    "world": {
                        "section_urls": ["https://apnews.com/world-news"],
                        "max_stories": 2,
                        "topic_description": "World news",
                    },
                },
                "require_allowed_domain": True,
                "require_publication_date": True,
                "reject_if_older_than_hours": 36,
                "reject_non_article_pages": True,
            }
        },
        "extraction": {
            "provider": "firecrawl",
            "max_candidate_urls_per_section": 12,
            "max_extract_chars_per_article": 12000,
            "timeout_seconds": 45,
            "retries": 2,
        },
        "llm": {
            "model": "gpt-5-nano",
            "fallback_model": "gpt-5.4-nano",
            "relevance_threshold": 0.70,
        },
        "output": {
            "output_dir": "./outputs",
            "save_raw_extracts": True,
        },
        "email": {
            "enabled": True,
            "subject_template": "Daily AP News Briefing — {date}",
        },
    }


def _recent_iso() -> str:
    """An ISO timestamp comfortably inside the 36h freshness window."""
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


@pytest.fixture
def recent_iso() -> str:
    return _recent_iso()


@pytest.fixture
def extracted_article() -> dict:
    """A single successfully-extracted article dict that passes filters."""
    return {
        "candidate_url": "https://apnews.com/article/example-aaaaaaaa11112222",
        "source": "apnews",
        "section": "us",
        "title": "Example headline",
        "byline": "Jane Reporter",
        "published_at": _recent_iso(),
        "extracted_text": "Body text. " * 100,
        "extracted_markdown": "# Example headline\n\nBody text.",
        "chars_extracted": 1100,
        "extraction_success": True,
        "extraction_error": None,
        "url_after_redirect": "https://apnews.com/article/example-aaaaaaaa11112222",
        "metadata": {},
        "extracted_at": _recent_iso(),
    }


@pytest.fixture
def evaluator_response() -> str:
    """Canned OpenAI JSON for the relevance evaluator."""
    return (
        '{"selected": [{"candidate_id": "us_000", "section": "us", '
        '"relevance_score": 0.92, "newsworthiness_score": 0.9, '
        '"reason": "Major story", "dedupe_group": "g1"}], '
        '"rejected": [{"candidate_id": "us_001", "reason": "Low relevance"}]}'
    )


@pytest.fixture
def summarizer_response() -> str:
    """Canned OpenAI JSON for the article summarizer."""
    return (
        '{"headline": "A clear headline", "source_title": "Example headline", '
        '"source": "AP News", "url": "https://apnews.com/article/example", '
        '"published_at": "2026-06-23T10:00:00+00:00", '
        '"summary": "A concise summary of the story.", '
        '"why_it_matters": "It matters because of X.", '
        '"key_entities": ["Entity A", "Entity B"], "section": "US"}'
    )
