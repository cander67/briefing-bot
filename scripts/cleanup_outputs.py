#!/usr/bin/env python3
"""Cleanup old briefing outputs per retention policy."""

from __future__ import annotations

import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent))

load_dotenv()


def load_config(path: Path) -> dict:
    from config_loader import load_config as _load_config
    return _load_config(path)


def load_retention_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def cleanup_outputs(
    output_root: Path,
    retention_cfg: dict,
    dry_run: bool = False,
) -> dict[str, int]:
    """Delete old run directories and files per retention policy."""

    briefing_retention_days = retention_cfg.get("retention", {}).get("briefing_retention_days", 5)
    raw_extract_retention_days = retention_cfg.get("retention", {}).get("raw_extract_retention_days", 2)
    keep_logs_days = retention_cfg.get("retention", {}).get("keep_logs_days", 14)

    now = datetime.now(timezone.utc)
    briefing_cutoff = now - timedelta(days=briefing_retention_days)
    raw_cutoff = now - timedelta(days=raw_extract_retention_days)
    logs_cutoff = now - timedelta(days=keep_logs_days)

    stats = {
        "run_dirs_deleted": 0,
        "raw_extracts_deleted": 0,
        "log_files_deleted": 0,
        "errors": 0,
    }

    if not output_root.exists():
        print(f"[cleanup] Output root does not exist: {output_root}")
        return stats

    for run_dir in sorted(output_root.iterdir()):
        if not run_dir.is_dir():
            continue

        # Skip non-date directories (e.g., .DS_Store)
        try:
            run_date = datetime.strptime(run_dir.name, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        # Delete entire run directory if older than briefing retention
        if run_date < briefing_cutoff:
            if dry_run:
                print(f"[cleanup] DRY RUN: Would delete run dir {run_dir}")
            else:
                try:
                    shutil.rmtree(run_dir)
                    print(f"[cleanup] Deleted run dir {run_dir}")
                except Exception as e:
                    print(f"[cleanup] Error deleting {run_dir}: {e}")
                    stats["errors"] += 1
                    continue
            stats["run_dirs_deleted"] += 1
            continue

        # Within briefing retention — clean raw extracts if older than raw retention
        raw_dir = run_dir / "raw_extracts"
        if raw_dir.exists() and run_date < raw_cutoff:
            if dry_run:
                print(f"[cleanup] DRY RUN: Would delete raw extracts {raw_dir}")
            else:
                try:
                    shutil.rmtree(raw_dir)
                    print(f"[cleanup] Deleted raw extracts {raw_dir}")
                except Exception as e:
                    print(f"[cleanup] Error deleting raw extracts {raw_dir}: {e}")
                    stats["errors"] += 1
                    continue
            stats["raw_extracts_deleted"] += 1

        # Clean old log files in logs/ directory (separate from run dirs)
        # This is handled separately below

    # Clean old log files in logs/ directory
    logs_dir = output_root.parent / "logs"
    if logs_dir.exists():
        for log_file in logs_dir.iterdir():
            if log_file.is_file() and log_file.suffix in (".log", ".json", ".txt"):
                try:
                    mtime = datetime.fromtimestamp(log_file.stat().st_mtime, tz=timezone.utc)
                    if mtime < logs_cutoff:
                        if dry_run:
                            print(f"[cleanup] DRY RUN: Would delete log file {log_file}")
                        else:
                            log_file.unlink()
                            print(f"[cleanup] Deleted log file {log_file}")
                        stats["log_files_deleted"] += 1
                except Exception as e:
                    print(f"[cleanup] Error deleting log file {log_file}: {e}")
                    stats["errors"] += 1

    return stats


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="Path to briefing config YAML")
    parser.add_argument("--retention-config", default="config/retention.yaml", help="Path to retention config YAML")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    retention_cfg = load_retention_config(Path(args.retention_config))

    output_root = Path(config["output"]["output_dir"]).expanduser().resolve()

    print(f"[cleanup] Output root: {output_root}")
    print(f"[cleanup] Briefing retention: {retention_cfg.get('retention', {}).get('briefing_retention_days', 5)} days")
    print(f"[cleanup] Raw extract retention: {retention_cfg.get('retention', {}).get('raw_extract_retention_days', 2)} days")
    print(f"[cleanup] Logs retention: {retention_cfg.get('retention', {}).get('keep_logs_days', 14)} days")
    print(f"[cleanup] Dry run: {args.dry_run}")

    stats = cleanup_outputs(output_root, retention_cfg, dry_run=args.dry_run)

    print(f"[cleanup] Complete: {stats}")
    if stats["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()