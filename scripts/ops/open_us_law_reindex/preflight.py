#!/usr/bin/env python3
"""Fail-closed preflight for the Open US Law reindex supervisor."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = Path("config/agent_supervisor_open_us_law_reindex_scheduler.json")
if not any(arg == "--config" or arg.startswith("--config=") for arg in sys.argv[1:]):
    sys.argv.extend(["--config", DEFAULT_CONFIG.as_posix()])
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ops.legal_corpora_reindex.preflight import run_preflight


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = args.repo_root.resolve()
    config = args.config if args.config.is_absolute() else root / args.config
    try:
        report = run_preflight(root, config.resolve())
        report["schema"] = "ipfs_datasets_py/open-us-law-reindex-preflight@1"
    except Exception as exc:
        report = {
            "schema": "ipfs_datasets_py/open-us-law-reindex-preflight@1",
            "valid": False,
            "errors": [f"{type(exc).__name__}: {exc}"],
        }
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        print("valid" if report.get("valid") else "invalid")
        for error in report.get("errors", []):
            print(f"ERROR: {error}")
    return 0 if report.get("valid") else 2


if __name__ == "__main__":
    raise SystemExit(main())
