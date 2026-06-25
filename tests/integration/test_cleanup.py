"""Integration tests for cleanup_outputs retention logic (real tmp filesystem)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import cleanup_outputs
from datetime import datetime, timedelta, timezone

from cleanup_outputs import cleanup_outputs as run_cleanup

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

    stats = run_cleanup(tmp_path, RETENTION)
    assert fresh.exists()
    assert not stale.exists()
    assert stats["run_dirs_deleted"] == 1


def test_dry_run_deletes_nothing(tmp_path):
    stale = _date_dir(tmp_path, days_ago=10)
    run_cleanup(tmp_path, RETENTION, dry_run=True)
    # Dry run leaves the filesystem untouched (it still tallies what it *would* delete).
    assert stale.exists()


def test_ignores_non_date_dirs(tmp_path):
    (tmp_path / "not-a-date").mkdir()
    stats = run_cleanup(tmp_path, RETENTION)
    assert (tmp_path / "not-a-date").exists()
    assert stats["errors"] == 0


def test_missing_output_root_is_safe(tmp_path):
    stats = run_cleanup(tmp_path / "nope", RETENTION)
    assert stats["run_dirs_deleted"] == 0


def test_deletes_stale_raw_extracts_but_keeps_run_dir(tmp_path):
    run_dir = _date_dir(tmp_path, days_ago=3)
    raw_dir = run_dir / "raw_extracts"
    raw_dir.mkdir()
    (raw_dir / "article.md").write_text("raw")

    stats = run_cleanup(tmp_path, RETENTION)
    assert run_dir.exists()
    assert not raw_dir.exists()
    assert stats["raw_extracts_deleted"] == 1


def test_dry_run_keeps_raw_extracts_and_old_logs(tmp_path):
    output_root = tmp_path / "outputs"
    output_root.mkdir()
    run_dir = _date_dir(output_root, days_ago=3)
    raw_dir = run_dir / "raw_extracts"
    raw_dir.mkdir()
    (raw_dir / "article.md").write_text("raw")

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    log_file = logs_dir / "cron.log"
    log_file.write_text("old log")
    old = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
    os.utime(log_file, (old, old))

    stats = run_cleanup(output_root, RETENTION, dry_run=True)
    assert raw_dir.exists()
    assert log_file.exists()
    assert stats["raw_extracts_deleted"] == 1
    assert stats["log_files_deleted"] == 1


def test_deletes_old_log_files_from_sibling_logs_dir(tmp_path):
    output_root = tmp_path / "outputs"
    output_root.mkdir()
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    old_log = logs_dir / "cron.log"
    fresh_log = logs_dir / "recent.log"
    ignored = logs_dir / "notes.md"
    old_log.write_text("old")
    fresh_log.write_text("fresh")
    ignored.write_text("ignore")

    old = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
    fresh = (datetime.now(timezone.utc) - timedelta(days=1)).timestamp()
    os.utime(old_log, (old, old))
    os.utime(fresh_log, (fresh, fresh))

    stats = run_cleanup(output_root, RETENTION)
    assert not old_log.exists()
    assert fresh_log.exists()
    assert ignored.exists()
    assert stats["log_files_deleted"] == 1


def test_counts_error_when_run_dir_delete_fails(tmp_path, monkeypatch):
    stale = _date_dir(tmp_path, days_ago=10)

    def boom(path):
        raise OSError("permission denied")

    monkeypatch.setattr(cleanup_outputs.shutil, "rmtree", boom)

    stats = run_cleanup(tmp_path, RETENTION)
    assert stale.exists()
    assert stats["errors"] == 1
    assert stats["run_dirs_deleted"] == 0


def test_counts_error_when_log_delete_fails(tmp_path, monkeypatch):
    output_root = tmp_path / "outputs"
    output_root.mkdir()
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    old_log = logs_dir / "cron.log"
    old_log.write_text("old")
    old = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
    os.utime(old_log, (old, old))

    def boom(self):
        raise OSError("busy")

    monkeypatch.setattr(Path, "unlink", boom)

    stats = run_cleanup(output_root, RETENTION)
    assert old_log.exists()
    assert stats["errors"] == 1


def test_load_retention_config_reads_yaml(tmp_path):
    config_path = tmp_path / "retention.yaml"
    config_path.write_text("retention:\n  keep_logs_days: 7\n")

    cfg = cleanup_outputs.load_retention_config(config_path)
    assert cfg["retention"]["keep_logs_days"] == 7


def test_main_runs_dry_run_with_real_config(monkeypatch, tmp_path, repo_root, capsys):
    output_root = tmp_path / "outputs"
    output_root.mkdir()
    retention_path = tmp_path / "retention.yaml"
    retention_path.write_text(
        "retention:\n"
        "  briefing_retention_days: 5\n"
        "  raw_extract_retention_days: 2\n"
        "  keep_logs_days: 14\n"
    )

    monkeypatch.setenv("BRIEFING_OUTPUT_DIR", str(output_root))
    monkeypatch.setattr(
        "sys.argv",
        [
            "cleanup_outputs.py",
            "--config",
            str(repo_root / "config" / "daily_ap.yaml"),
            "--retention-config",
            str(retention_path),
            "--dry-run",
        ],
    )

    cleanup_outputs.main()
    assert "[cleanup] Output root:" in capsys.readouterr().out


def test_main_exits_nonzero_when_cleanup_reports_errors(monkeypatch, tmp_path, repo_root):
    retention_path = tmp_path / "retention.yaml"
    retention_path.write_text("retention:\n  keep_logs_days: 14\n")
    monkeypatch.setenv("BRIEFING_OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setattr(cleanup_outputs, "cleanup_outputs", lambda *a, **k: {
        "run_dirs_deleted": 0,
        "raw_extracts_deleted": 0,
        "log_files_deleted": 0,
        "errors": 1,
    })
    monkeypatch.setattr(
        "sys.argv",
        [
            "cleanup_outputs.py",
            "--config",
            str(repo_root / "config" / "daily_ap.yaml"),
            "--retention-config",
            str(retention_path),
        ],
    )

    with pytest.raises(SystemExit, match="1"):
        cleanup_outputs.main()
