#!/usr/bin/env python3
"""Fresh source replay plus regression tests for a sealed supervisor task."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    os.environ["IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI"] = "0"
    os.environ["IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS"] = "0"
    os.environ["IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE"] = "0"
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import (
        REGRESSION_TESTS, RepairQueueError, read_packet, replay_packet, repair_outputs,
    )
    try:
        packet = read_packet(args.packet, args.sha256)
        if packet["regression_tests"] != list(REGRESSION_TESTS):
            raise RepairQueueError("regression suite differs from validator policy")
        regression = repair_outputs(packet, args.sha256)[-1]
        if not (ROOT / regression).is_file() or (ROOT / regression).is_symlink():
            raise RepairQueueError("task-owned regression test is missing or a symlink")
        result = replay_packet(packet)
    except (RepairQueueError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}))
        return 2
    print(json.dumps(result, sort_keys=True), flush=True)
    if not result["passed"]:
        return 1
    # No source-selected command or shell execution. Keep regression tests
    # fixed in the protected validator, not editable task metadata.
    # Fixed tests use pytest built-ins only. Do not inherit site plugins,
    # skip/caching hooks, source-selected addopts or installer conftests.
    environment = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTEST_ADDOPTS="", PYTEST_PLUGINS="")
    command = [sys.executable, "-m", "pytest", "-c", "pytest.ini", "-o", "addopts=",
               "--noconftest", "--strict-markers", "--import-mode=importlib", "-q",
               *REGRESSION_TESTS, regression]
    try:
        return subprocess.run(command, cwd=ROOT, env=environment, timeout=600, check=False).returncode
    except subprocess.TimeoutExpired:
        return 124


if __name__ == "__main__":
    raise SystemExit(main())
