"""Integration tests for cleanup_outputs retention logic (real tmp filesystem)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cleanup_outputs import cleanup_outputs

RETENTION = {"retention": {"briefing_retention_days": 5, "raw_extract_retention_days": 2, "keep_logs_days": 14}}


def _date_dir(root, days_ago: int):
    name = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    d = root / name
    d.mkdir()
    (d / "briefing.md").write_text("x")
    return d


def test_deletes_only_stale_run_dirs(tmp_path):
    fresh = _date_dir(tmp_path, days_ago=1)
    stale = _date_dir(tmp_path, days_ago=10)

    stats = cleanup_outputs(tmp_path, RETENTION)
    assert fresh.exists()
    assert not stale.exists()
    assert stats["run_dirs_deleted"] == 1


def test_dry_run_deletes_nothing(tmp_path):
    stale = _date_dir(tmp_path, days_ago=10)
    cleanup_outputs(tmp_path, RETENTION, dry_run=True)
    # Dry run leaves the filesystem untouched (it still tallies what it *would* delete).
    assert stale.exists()


def test_ignores_non_date_dirs(tmp_path):
    (tmp_path / "not-a-date").mkdir()
    stats = cleanup_outputs(tmp_path, RETENTION)
    assert (tmp_path / "not-a-date").exists()
    assert stats["errors"] == 0


def test_missing_output_root_is_safe(tmp_path):
    stats = cleanup_outputs(tmp_path / "nope", RETENTION)
    assert stats["run_dirs_deleted"] == 0
