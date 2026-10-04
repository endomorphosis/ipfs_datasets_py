"""Bounded structural head publication, freshness and native restart benchmark.

Run with --output PATH. No training, proving, real pressure or scaling claim.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

import bench_codebase_ir as base
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog, CodebaseHead
from ipfs_datasets_py.logic.software_contracts.codebase_ir import (
    RepositoryCodebaseIndex, StaleCodebaseError,
)

VIEW = "worktree:structural-head-benchmark"


def open_index(database, artifacts):
    historical, connection, frontend = base.index_for(database, artifacts)
    catalog = CodebaseCatalog(historical.ingestor.store, historical.artifacts)
    return RepositoryCodebaseIndex(ingestor=historical.ingestor,
                                   artifacts=historical.artifacts, catalog=catalog), connection, frontend


def replay(request):
    index, connection, frontend = open_index(request["database"], request["artifacts"])
    try:
        expected = CodebaseHead.from_dict(request["head"])
        started = time.perf_counter()
        observed = index.observe_current(request["repository"], expected_head=expected)
        base.require(frontend.parse_invocations == 0, "observation parsed source")
        base.require(observed.manifest.cid == expected.manifest_cid, "wrong restart manifest")
        base.require_own_leases_released()
        return {"head": observed.head.to_dict(), "parse_invocations": frontend.parse_invocations,
                "observe_wall_seconds": time.perf_counter() - started, "correctness_passed": True}
    finally:
        connection.close()


def trial(root, number):
    directory = root / f"round-{number}"
    directory.mkdir()
    repository = directory / "repository"
    originals = base.fixture(repository, 8, 4)
    database, artifacts = directory / "ast.duckdb", directory / "artifacts"
    index, connection, frontend = open_index(database, artifacts)
    limits = base.CodebaseScanLimits(max_entries=16, max_file_bytes=16 * 1024)
    first_path = sorted(originals)[0]
    original = originals[first_path]
    changed = original.replace(b"return n + 1\n", b"return n + 999\n", 1)
    previous = None
    rows = []
    try:
        for stage, raw, expected_parses in (("cold", original, 8), ("exact_retry", original, 0),
                                            ("one_file_edit", changed, 1), ("restore_original", original, 0)):
            (repository / first_path).write_bytes(raw)
            if stage in {"one_file_edit", "restore_original"}:
                try:
                    index.observe_current(repository, expected_head=previous)
                except StaleCodebaseError:
                    pass
                else:
                    raise AssertionError("unindexed source change was accepted")
            before = frontend.parse_invocations
            started = time.perf_counter()
            receipt = index.prepare_current(
                repository, repository_id=VIEW,
                operation_id="cold" if stage == "exact_retry" else stage,
                expected_head=None if stage == "exact_retry" else previous,
                limits=limits,
            )
            publication_time = time.perf_counter() - started
            parses = frontend.parse_invocations - before
            base.require(parses == expected_parses, "unexpected AST parse count")
            if stage == "exact_retry":
                base.require(receipt.head == previous, "retry changed generation")
            started = time.perf_counter()
            observation = index.observe_current(repository, expected_head=receipt.head)
            observation_time = time.perf_counter() - started
            base.require(frontend.parse_invocations == before + parses, "observation invoked AST parser")
            expected_sources = dict(originals)
            expected_sources[first_path] = raw
            base.validate(index, observation.manifest, expected_sources, 4)
            base.require_own_leases_released()
            rows.append({"stage": stage, "publish_wall_seconds": publication_time,
                         "observe_wall_seconds": observation_time, "ast_ingestor_parses": parses,
                         "head": receipt.head.to_dict(), "correctness_passed": True})
            previous = receipt.head
        base.require(previous.generation == 3, "unexpected final generation")
        # Exact old command replay remains history, even when content has returned
        # to A. It must not overwrite the generation-3 head or active ASTs.
        old = index.prepare_current(repository, repository_id=VIEW, operation_id="cold",
                                    expected_head=None, limits=limits)
        base.require(old.head.generation == 1 and index.current(VIEW) == previous,
                     "historical operation replay changed current head")
        index.observe_current(repository, expected_head=previous)
        base.require_own_leases_released()
        request = {"database": str(database), "artifacts": str(artifacts),
                   "repository": str(repository), "head": previous.to_dict()}
    finally:
        connection.close()
    request_path = directory / "replay.json"
    request_path.write_text(json.dumps(request))
    started = time.perf_counter()
    child = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--replay", str(request_path)],
                           capture_output=True, text=True, timeout=60)
    base.require(child.returncode == 0, child.stderr[-8000:])
    fresh = json.loads(child.stdout.splitlines()[-1])
    fresh["process_wall_seconds_including_startup"] = time.perf_counter() - started
    base.require(fresh["head"] == previous.to_dict(), "fresh process returned another head")
    return {"round": number, "measurements": rows, "fresh_process_replay": fresh,
            "stale_source_rejections": 2, "historical_replay_preserved_current_head": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--replay", type=Path)
    args = parser.parse_args()
    if args.replay:
        print(json.dumps(replay(json.loads(args.replay.read_text()))))
        return
    if args.output is None:
        parser.error("--output is required")
    base.require(base.get_global_resource_scheduler().config.proof_safety_enabled,
                 "default shared resource safety must be enabled")
    started_at = datetime.now(timezone.utc).isoformat()
    startup = base.startup_memory_evidence()
    with tempfile.TemporaryDirectory(prefix="codebase-current-benchmark-") as directory:
        rounds = [trial(Path(directory), number) for number in range(1, 4)]
    summary = {}
    for stage in ("cold", "exact_retry", "one_file_edit", "restore_original"):
        rows = [row for result in rounds for row in result["measurements"] if row["stage"] == stage]
        summary[stage] = {"median_publish_wall_seconds": statistics.median(r["publish_wall_seconds"] for r in rows),
                          "median_observe_wall_seconds": statistics.median(r["observe_wall_seconds"] for r in rows),
                          "ast_ingestor_parses": [r["ast_ingestor_parses"] for r in rows]}
    sources = ["benchmarks/bench_codebase_current.py", "benchmarks/bench_codebase_ir.py",
               "ipfs_datasets_py/duckdb_control/codebase_catalog.py"] + [
        "ipfs_datasets_py/logic/software_contracts/" + name for name in
        ("codebase_ir.py", "codebase_resources.py", "duckdb_ast_store.py", "duckdb_ingest.py", "cache.py")]
    report = {
        "schema": "codebase-current-structural-benchmark@1", "started_at_utc": started_at,
        "correctness_passed": True, "scope": "bounded_structural_only", "rounds": rounds, "summary": summary,
        "configuration": {"files": 8, "functions_per_file": 4, "rounds": 3,
                          "duckdb": base.DB_CONFIG, "preparation_memory_reservation_mib": 512,
                          "scheduler": "shared_default", "resource_safety_enabled": True},
        "memory": {"main_process_cumulative_peak_rss_mib": base.cumulative_peak_rss_mib(),
                   "startup": startup, "source": "/proc/self/status VmHWM on Linux",
                   "includes_child_rss": False, "reservation_is_hard_rss_limit": False},
        "runtime": {"python": sys.version, "duckdb": base.duckdb.__version__,
                    "platform": base.platform.platform(), "logical_cpu_count": base.os.cpu_count()},
        "source_sha256": {name: hashlib.sha256((base.REPOSITORY_ROOT / name).read_bytes()).hexdigest()
                          for name in sources},
        "measurement_notes": [
            "Publication includes default admission, scan, extraction, artifact verification, source recapture and catalog commit/replay.",
            "Observation includes default admission, canonical artifact/active AST reads and live source capture; it performs no extraction.",
            "Parse counts measure the AST ingestor; semantic extraction still repeats during publication preparation.",
            "Per round, one additional historical command replay and source observation are correctness checks outside reported stage timings.",
            "Cold means empty database/CAS; OS caches are not flushed. Peak RSS is cumulative, excludes child RSS, and is not a per-stage peak.",
            "This is sequential indexing evidence, not training, proof, many-core scaling, real host-pressure or hard-memory qualification.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"correctness_passed": True, "summary": summary, "memory": report["memory"]}, indent=2))


if __name__ == "__main__":
    main()
