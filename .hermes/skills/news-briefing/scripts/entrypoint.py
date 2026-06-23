#!/usr/bin/env python3
"""Entry point for Hermes news-briefing skill.

Calls the local pipeline script at ~/hermes-newsbot with --phase full --send.

Usage:
    python entrypoint.py                    # Run synchronously (blocks until done)
    python entrypoint.py --background       # Run in background, returns PID immediately
    python entrypoint.py --status           # Check status of background run via progress.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Hermes news-briefing skill entrypoint")
    parser.add_argument("--background", action="store_true",
                        help="Run pipeline in background (non-blocking)")
    parser.add_argument("--status", action="store_true",
                        help="Check status of most recent background run via progress.json")
    parser.add_argument("--force", action="store_true",
                        help="Force re-run even if briefing already exists (passed to pipeline)")
    args = parser.parse_args()

    # Project root defaults to ~/hermes-newsbot; override with NEWSBOT_HOME
    # when the repo is cloned elsewhere.
    project_root = Path(os.environ.get("NEWSBOT_HOME", Path.home() / "hermes-newsbot"))
    script = project_root / "scripts" / "run_daily_briefing.py"
    config = project_root / "config" / "daily_ap.yaml"
    output_root = project_root / "outputs"

    if not script.exists():
        print(f"[skill] Script not found: {script}", file=sys.stderr)
        return 1
    if not config.exists():
        print(f"[skill] Config not found: {config}", file=sys.stderr)
        return 1

    # Determine today's run directory (use same timezone logic as pipeline)
    import yaml  # safe since pyyaml is a dependency
    with open(config) as f:
        cfg = yaml.safe_load(f)
    tz_name = cfg.get("briefing", {}).get("timezone", "UTC")
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    today = datetime.now(tz).strftime("%Y-%m-%d")
    run_dir = output_root / today
    progress_file = run_dir / "progress.json"
    pid_file = project_root / "cache" / "run_pid.txt"

    if args.status:
        # Check status via progress.json
        if progress_file.exists():
            try:
                with open(progress_file) as f:
                    progress = json.load(f)
                print(f"[skill] Phase: {progress.get('phase', 'unknown')}")
                print(f"[skill] Updated: {progress.get('updated_at', 'unknown')}")
                for k, v in progress.items():
                    if k not in ("phase", "updated_at"):
                        print(f"[skill]   {k}: {v}")
            except Exception as e:
                print(f"[skill] Failed to read progress: {e}", file=sys.stderr)
                return 1
        else:
            print("[skill] No progress.json found. Run may not have started yet.")
        return 0

    cmd = [
        sys.executable,
        str(script),
        "--config", str(config),
        "--phase", "full",
        "--send",
    ]
    if args.force:
        cmd.append("--force")

    if args.background:
        # Run in background
        print(f"[skill] Starting background run: {' '.join(cmd)}")
        proc = subprocess.Popen(cmd, cwd=project_root, start_new_session=True)
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(proc.pid))
        print(f"[skill] Background process started with PID {proc.pid}")
        print("[skill] Check status with: python entrypoint.py --status")
        print(f"[skill] Or poll: {progress_file}")
        return 0
    else:
        # Run synchronously (original behavior)
        print(f"[skill] Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=project_root)
        return result.returncode


if __name__ == "__main__":
    sys.exit(main())