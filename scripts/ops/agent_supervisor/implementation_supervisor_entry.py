#!/usr/bin/env python3
"""Stable module entry point for multi-supervisor implementation tracks."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_supervisor import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
