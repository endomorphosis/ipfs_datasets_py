"""Bounded 1/2/4-worker native verification and durable-index restart benchmark.

Every measured batch performs fresh Z3/CVC5 checking and owner publication.
No host exhaustion, training, proof execution bypass or general scaling claim.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import threading
import time

import bench_codebase_ir as base
from bench_codebase_current import open_index
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
from ipfs_datasets_py.duckdb_control.codebase_evidence_index import CodebaseEvidenceIndex
from ipfs_datasets_py.logic.software_contracts import codebase_integer_profile as profile
from ipfs_datasets_py.logic.software_contracts.codebase_integer_verification import CodebaseIntegerVerifier
from ipfs_datasets_py.logic.software_contracts.codebase_property_cache import CodebasePropertyCache

VIEW = "worktree:integer-batch-benchmark"


def require_owned_leases_released():
    leases = base.get_global_resource_scheduler().active_leases()
    base.require(not any(row["owner_pid"] == os.getpid() for row in leases),
                 "benchmark process leaked an owned resource lease")


def replay(request):
    index, connection, frontend = open_index(request["database"], request["artifacts"])
    try:
        head = CodebaseHead.from_dict(request["head"])
        index.observe_current(request["repository"], expected_head=head, timeout_seconds=45,
                              admission_timeout_seconds=30)
        historical = CodebaseEvidenceIndex(index.catalog)
        def forbidden(*args, **kwargs):
            raise AssertionError("historical lookup invoked a solver")
        profile.execute_integer_offset = forbidden
        profile.compile_integer_offset = forbidden
        rows = []
        for receipt in request["receipts"]:
            record = historical.get(receipt, expected_head=head)
            base.require(record is not None, "durable receipt missing after restart")
            rows.append(record.to_dict())
        base.require(frontend.parse_invocations == 0, "historical observation reparsed source")
        require_owned_leases_released()
        return {"records": rows, "historical_only": True, "native_checks_executed": 0,
                "correctness_passed": True}
    finally:
        connection.close()


def trial(root, number, width):
    directory = root / f"round-{number}-workers-{width}"
    directory.mkdir()
    repository = directory / "repository"
    base.fixture(repository, 4, 1)
    database, artifacts = directory / "ast.duckdb", directory / "artifacts"
    index, connection, _ = open_index(database, artifacts)
    cache = CodebasePropertyCache(directory / "properties")
    contracts = [profile.IntegerOffsetContract(f"module_{n:03d}.py", f"operation_{n}_0", "n", n + delta)
                 for n in range(4) for delta in (1, 2)]
    active, peak, invocations = 0, 0, 0
    lock = threading.Lock()
    native = profile.run_bounded_stdin_tool
    def measured(*args, **kwargs):
        nonlocal active, peak, invocations
        with lock:
            active += 1
            invocations += 1
            peak = max(peak, active)
        try:
            return native(*args, **kwargs)
        finally:
            with lock:
                active -= 1
    try:
        head = index.prepare_current(repository, repository_id=VIEW, operation_id="initial",
            expected_head=None, limits=base.CodebaseScanLimits(max_entries=8, max_file_bytes=1024)).head
        verifier = CodebaseIntegerVerifier(index, cache)
        profile.run_bounded_stdin_tool = measured
        started = time.perf_counter()
        result = verifier.verify_many(repository, expected_head=head, contracts=contracts,
                                      max_workers=width, timeout_seconds=60)
        elapsed = time.perf_counter() - started
        base.require(result["max_workers"] == width, "requested width unavailable in current host envelope")
        base.require([r["status"] for r in result["results"]] == ["proved", "refuted"] * 4, "wrong outcomes")
        base.require(all(r["solver_replayed"] for r in result["results"]), "native check bypass")
        base.require(result["cache_history_hits"] == 0, "cold property cache was not empty")
        base.require(len(result["evidence_receipt_cids"]) == 8, "incomplete durable publication")
        base.require(peak <= width and active == 0, "bounded invocation lifecycle failed")
        base.require(width == 1 or peak > 1, "native lifecycle calls did not overlap")
        require_owned_leases_released()
        request = {"database": str(database), "artifacts": str(artifacts), "repository": str(repository),
                   "head": head.to_dict(), "receipts": result["evidence_receipt_cids"]}
    finally:
        profile.run_bounded_stdin_tool = native
        connection.close()
    request_path = directory / "replay.json"
    request_path.write_text(json.dumps(request))
    child = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--replay", str(request_path)],
                           capture_output=True, text=True, timeout=60)
    base.require(child.returncode == 0, child.stderr[-8000:])
    restarted = json.loads(child.stdout.splitlines()[-1])
    base.require(len(restarted["records"]) == 8, "incomplete native restart")
    print(f"round={number} workers={width} batch_seconds={elapsed:.3f} restart=passed", file=sys.stderr)
    return {"round": number, "workers": width, "wall_seconds": elapsed,
            "contracts_per_second": len(contracts) / elapsed, "peak_native_lifecycle_calls": peak,
            "native_invocations_including_versions_and_model_replays": invocations,
            "result": result, "fresh_process_lookup": restarted, "correctness_passed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--replay", type=Path)
    args = parser.parse_args()
    if args.replay:
        print(json.dumps(replay(json.loads(args.replay.read_text()))))
        return
    if args.output is None:
        parser.error("--output required")
    base.require(base.get_global_resource_scheduler().config.proof_safety_enabled, "default resource safety disabled")
    started = datetime.now(timezone.utc).isoformat()
    startup = base.startup_memory_evidence()
    with tempfile.TemporaryDirectory(prefix="integer-batch-benchmark-") as directory:
        trials = [trial(Path(directory), number, width) for number in range(1, 4) for width in (1, 2, 4)]
    baseline = statistics.median(row["wall_seconds"] for row in trials if row["workers"] == 1)
    summary = {}
    for width in (1, 2, 4):
        selected = [row for row in trials if row["workers"] == width]
        elapsed = statistics.median(row["wall_seconds"] for row in selected)
        summary[str(width)] = {"median_wall_seconds": elapsed, "contracts_per_second": 8 / elapsed,
                               "relative_speedup": baseline / elapsed,
                               "peak_native_lifecycle_calls": [row["peak_native_lifecycle_calls"] for row in selected]}
    sources = [Path(__file__).resolve(), Path(profile.__file__).resolve()]
    sources += [base.REPOSITORY_ROOT / "ipfs_datasets_py/logic/software_contracts" / name for name in
                ("codebase_integer_batch.py", "codebase_integer_verification.py", "codebase_integer_workers.py", "codebase_resources.py")]
    sources += [base.REPOSITORY_ROOT / "ipfs_datasets_py/duckdb_control/codebase_evidence_index.py",
                base.REPOSITORY_ROOT / "ipfs_datasets_py/logic/backends/process.py"]
    report = {"schema": "codebase-integer-batch-benchmark@1", "started_at_utc": started,
        "correctness_passed": True, "trials": trials, "summary": summary,
        "configuration": {"source_files": 4, "contracts": 8, "rounds": 3, "worker_widths": [1, 2, 4],
                          "scheduler": "shared_default", "resource_safety_enabled": True, "duckdb": base.DB_CONFIG,
                          "memory_reservation_mib": "512 + 512 * workers", "native_memory_cap_mib": 256},
        "memory": {"main_process_cumulative_peak_rss_mib": base.cumulative_peak_rss_mib(), "startup": startup,
                   "includes_children": False, "reservation_is_hard_rss_limit": False},
        "runtime": {"python": sys.version, "duckdb": base.duckdb.__version__, "platform": base.platform.platform()},
        "source_sha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
        "measurement_notes": [
            "Fresh native checks, all owner CAS/cache writes, live-source observations and native index publication are inside batch timings; initial head preparation and restart lookup are outside.",
            "Independent contracts overlap; Z3/CVC5 remain sequential within each contract. Peak lifecycle calls include workspace setup, process monitoring and cleanup, not solely executing solver CPUs.",
            "Native launch concurrency and inherited resource limits are separately covered by real-process tests.",
            "Each trial has an empty property cache and index; OS caches are not flushed. Small bounded formulas are dominated by setup, hashing and publication, so wider execution need not improve throughput.",
            "Every batch reruns native solvers. Fresh-process index lookup is historical-only and explicitly invokes no compiler or solver; it cannot replace checking or grant authority.",
            "No deliberate host pressure, large-repository scaling, model training, mixed-family proof graph or production behavioral admission is qualified.",
        ]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"correctness_passed": True, "summary": summary, "memory": report["memory"]}, indent=2))


if __name__ == "__main__":
    main()
