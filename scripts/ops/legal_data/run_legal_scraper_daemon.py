#!/usr/bin/env python3
"""Run the comprehensive Bluebook-driven legal scraper daemon."""

from __future__ import annotations

from pathlib import Path
import sys


def _bootstrap_pythonpath() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)


_bootstrap_pythonpath()

from ipfs_datasets_py.processors.legal_scrapers.legal_scraper_daemon import main


if __name__ == "__main__":
    raise SystemExit(main())
