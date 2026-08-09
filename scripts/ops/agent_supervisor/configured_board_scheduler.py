#!/usr/bin/env python3
"""Thin source-checkout entry for the configured-board scheduler."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ipfs_accelerate_py.agent_supervisor.runtime.configured_board_scheduler import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
