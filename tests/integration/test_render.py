"""Integration test for render_briefing (real file I/O into tmp_path)."""

from __future__ import annotations

from render_briefing import render_briefing


def _summarized() -> list[dict]:
    return [
        {
            "candidate_id": "us_000",
            "headline": "Major US story",
            "source_title": "Major US story",
            "source": "AP News",
            "url": "https://apnews.com/article/us-one",
            "published_at": "2026-06-23T17:30:00+00:00",
            "summary": "A concise summary.",
            "why_it_matters": "It matters because X.",
            "key_entities": ["Person A"],
            "section": "us",
        },
        {
            "candidate_id": "world_000",
            "headline": "Major world story",
            "source_title": "Major world story",
            "source": "AP News",
            "url": "https://apnews.com/article/world-one",
            "published_at": "2026-06-23T18:00:00+00:00",
            "summary": "Another summary.",
            "why_it_matters": "Global implications.",
            "key_entities": [],
            "section": "world",
        },
    ]


def test_render_writes_both_artifacts(tmp_path, sample_config):
    md_path, txt_path = render_briefing(
        _summarized(), sample_config, tmp_path, "2026-06-23"
    )
    assert md_path.exists() and txt_path.exists()

    md = md_path.read_text()
    assert "Major US story" in md
    assert "Major world story" in md
    assert "It matters because X." in md
    assert "https://apnews.com/article/us-one" in md

    txt = txt_path.read_text()
    assert "Major US story" in txt
