"""Measure native scheduler IO for a fixed healthy nested lease topology.

The fixture reserves synthetic accounting envelopes; it launches no solver and
allocates no declared worker memory. Real advisory locks, JSON reads and fsyncs
remain enabled. Instrumentation is scoped to this single-threaded process and
does not alter source files. Results are diagnostics, not a throughput claim.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

# Direct script execution otherwise puts only benchmarks/ on sys.path and may
# silently measure a separately installed checkout. Bind this qualification to
# the source tree containing the script, and retain its exact source digests.
REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as resources
if Path(resources.__file__).resolve() != REPOSITORY / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py":
    raise RuntimeError("microprofile imported a different datasets checkout")


def sources():
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (Path(__file__).resolve(), Path(resources.__file__).resolve())}


def profile(iterations):
    source_hashes = sources()
    results = {}
    with TemporaryDirectory(prefix="scheduler-read-profile-") as directory:
        scheduler = resources.GlobalResourceScheduler(resources.ResourceSchedulerConfig(
            state_path=Path(directory) / "state.json", total_cpu_slots=4,
            total_memory_mb=400, total_child_process_slots=4, lane_reservations={},
            auto_renew_leases=False, lease_ttl_seconds=120,
        ))
        root = scheduler.acquire("orchestration", cpu_slots=4, memory_mb=400,
                                 child_process_slots=4, timeout=0)
        leases = [root]
        try:
            for _ in range(4):
                node = root
                for _ in range(3):
                    node = node.acquire_child(cpu_slots=1, memory_mb=100,
                                              child_process_slots=1, timeout=0)
                    leases.append(node)
            scheduler.snapshot()
            state_bytes = scheduler.state_path.stat().st_size
            native_alive, native_sync = resources._owner_is_alive, os.fsync
            for name, action in (
                ("snapshot", scheduler.snapshot), ("active_leases", scheduler.active_leases),
                ("is_cancelled", lambda: scheduler.is_cancelled(leases[-1].lease_id)),
                ("renew", leases[-1].renew),
            ):
                metrics = defaultdict(float)
                def measured_alive(*arguments):
                    started = time.perf_counter()
                    try:
                        return native_alive(*arguments)
                    finally:
                        metrics["owner_probe_calls"] += 1
                        metrics["owner_probe_seconds"] += time.perf_counter() - started
                def measured_sync(*arguments):
                    started = time.perf_counter()
                    try:
                        return native_sync(*arguments)
                    finally:
                        metrics["fsync_calls"] += 1
                        metrics["fsync_seconds"] += time.perf_counter() - started
                started = time.perf_counter()
                with patch.object(resources, "_owner_is_alive", measured_alive), patch.object(os, "fsync", measured_sync):
                    for _ in range(iterations):
                        action()
                metrics["wall_seconds"] = time.perf_counter() - started
                results[name] = {"calls": iterations,
                    "owner_probe_calls": int(metrics["owner_probe_calls"]),
                    "fsync_calls": int(metrics["fsync_calls"]),
                    "owner_probe_seconds": metrics["owner_probe_seconds"],
                    "fsync_seconds": metrics["fsync_seconds"],
                    "wall_seconds": metrics["wall_seconds"]}
        finally:
            for lease in reversed(leases):
                lease.release()
        final = scheduler.snapshot()
        if final["active_lease_count"] or final["waiting_request_count"]:
            raise RuntimeError("microprofile leaked owned scheduler state")
    if sources() != source_hashes:
        raise RuntimeError("microprofile implementation changed during measurement")
    return {"schema": "resource-scheduler-microprofile@1",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version, "platform": platform.platform(),
        "configuration": {"iterations": iterations, "active_leases": 13,
            "root_count": 1, "branches": 4, "branch_depth": 3, "unique_owner_processes": 1,
            "auto_renew_leases": False, "state_bytes": state_bytes,
            "real_io_enabled": True, "solver_processes_launched": False},
        "measurements": results, "owned_leases_after": 0, "sources": source_hashes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=20, choices=range(1, 1001))
    arguments = parser.parse_args()
    if arguments.output.exists():
        parser.error("output already exists; preserve prior qualification evidence")
    result = profile(arguments.iterations)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps(result["measurements"], sort_keys=True))


if __name__ == "__main__":
    main()
