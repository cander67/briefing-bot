#!/usr/bin/env python3
"""Entry point for Hermes news-briefing skill."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    # Project root defaults to ~/hermes-newsbot; override with NEWSBOT_HOME
    # when the repo is cloned elsewhere.
    project_root = Path(os.environ.get("NEWSBOT_HOME", Path.home() / "hermes-newsbot"))
    script = project_root / "scripts" / "run_daily_briefing.py"
    config = project_root / "config" / "daily_ap.yaml"

    if not script.exists():
        print(f"[skill] Script not found: {script}", file=sys.stderr)
        return 1
    if not config.exists():
        print(f"[skill] Config not found: {config}", file=sys.stderr)
        return 1

    cmd = [
        sys.executable,
        str(script),
        "--config", str(config),
        "--phase", "full",
        "--send",
    ]
    print(f"[skill] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=project_root)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())