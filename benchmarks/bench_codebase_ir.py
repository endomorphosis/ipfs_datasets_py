"""Bounded structural-only codebase IR benchmark.

Run: python benchmarks/bench_codebase_ir.py --output PATH/benchmark.json
Measures snapshot/scanner/AST/DuckDB/CAS preparation and independent-process
lookup. It does not qualify formalization, proving, training or many-core scaling.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import duckdb

from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import (
    CodebaseScanLimits, RepositoryCodebaseIndex,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import (
    CountingFrontend, DuckDBASTIngestor,
)
from ipfs_datasets_py.logic.software_contracts.python_frontend import PythonASTExtractor
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    get_global_resource_scheduler,
)

DB_CONFIG = {"threads": 1, "memory_limit": "64MB", "max_temp_directory_size": "128MB"}
PREPARATION_MEMORY_MB = 512
TABLES = ("ast_blobs", "source_files", "source_revisions", "symbols", "ast_nodes", "invalidations")
STAGES = ("cold", "unchanged", "one_file_edit", "restore_original")


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def git(repository, *arguments):
    environment = dict(os.environ, GIT_AUTHOR_DATE="2026-10-01T00:00:00Z",
                       GIT_COMMITTER_DATE="2026-10-01T00:00:00Z")
    run = subprocess.run(["git", "-C", str(repository), *arguments], env=environment,
                         capture_output=True, text=True, timeout=15, check=True)
    return run.stdout.strip()


def fixture(repository, files, functions):
    repository.mkdir()
    git(repository, "init", "-q")
    git(repository, "config", "user.name", "Codebase Benchmark")
    git(repository, "config", "user.email", "benchmark@example.invalid")
    originals = {}
    for file_number in range(files):
        text = "\n".join(
            f"def operation_{file_number}_{function}(n: int) -> int:\n"
            f"    return n + {file_number * functions + function + 1}\n"
            for function in range(functions)
        )
        name = f"module_{file_number:03d}.py"
        originals[name] = text.encode("utf-8")
        (repository / name).write_bytes(originals[name])
    (repository / "README.txt").write_text("Structural codebase benchmark fixture.\n", encoding="utf-8")
    git(repository, "add", ".")
    git(repository, "commit", "-qm", "bounded structural fixture")
    return originals


def index_for(database, cas, *, memory_mb=None):
    config = dict(DB_CONFIG)
    if memory_mb is not None:
        config["memory_limit"] = f"{memory_mb}MB"
    connection = duckdb.connect(str(database), config=config)
    frontend = CountingFrontend(PythonASTExtractor())
    ingestor = DuckDBASTIngestor(
        store=DuckDBASTStore(connection=connection), frontends={"python": frontend},
    )
    return RepositoryCodebaseIndex(ingestor=ingestor, artifacts=ImmutableCAS(cas)), connection, frontend


def counts(connection):
    return {table: connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            for table in TABLES}


def cumulative_peak_rss_mib():
    # Linux VmHWM describes the current executable's memory image. In launchers
    # using exec(), getrusage can retain an earlier image's high-water value.
    if sys.platform.startswith("linux"):
        for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) / 1024
    try:
        import resource
    except ImportError:
        return None
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value / (1024**2 if sys.platform == "darwin" else 1024)


def startup_memory_evidence():
    evidence = {"current_image_peak_rss_mib": cumulative_peak_rss_mib()}
    try:
        import resource
        evidence["getrusage_peak_rss_mib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (
            1024**2 if sys.platform == "darwin" else 1024)
    except ImportError:
        pass
    return evidence


def require_own_leases_released():
    remaining = [row for row in get_global_resource_scheduler().active_leases()
                 if row["owner_pid"] == os.getpid() and row["request_id"] == "codebase-ir:prepare"]
    require(not remaining, "benchmark preparation leaked its shared resource lease")


def calibrate_memory(root, originals, memory_mb):
    """Exercise a bounded database allocation failure and prior-view recovery."""
    directory = root / f"calibration-{memory_mb}mb"
    directory.mkdir()
    repository = directory / "repository"
    fixture(repository, 1, 1)
    index, connection, _ = index_for(directory / "ast.duckdb", directory / "cas", memory_mb=memory_mb)
    try:
        first = index.prepare(repository, repository_id="repository:codebase-ir-calibration",
                              memory_mb=PREPARATION_MEMORY_MB)
        require_own_leases_released()
        previous_rows = counts(connection)
        for path, raw in originals.items():
            (repository / path).write_bytes(raw)
        started = time.perf_counter()
        try:
            index.prepare(repository, repository_id="repository:codebase-ir-calibration", previous=first,
                          memory_mb=PREPARATION_MEMORY_MB)
        except duckdb.OutOfMemoryException as error:
            elapsed = time.perf_counter() - started
            require(counts(connection) == previous_rows, "allocation failure changed prior catalog rows")
            require(index.lookup(first, "module_000.py") is not None, "allocation failure invalidated prior AST")
            require_own_leases_released()
            return {"duckdb_memory_mb": memory_mb, "status": "duckdb_buffer_allocation_failed",
                    "error_type": type(error).__name__, "error": str(error), "wall_seconds": elapsed,
                    "prior_catalog_preserved": True, "own_leases_remaining": 0,
                    "host_oom": False, "store_rows_after_rollback": counts(connection)}
        require_own_leases_released()
        return {"duckdb_memory_mb": memory_mb, "status": "completed_within_limit",
                "wall_seconds": time.perf_counter() - started, "own_leases_remaining": 0,
                "host_oom": False}
    finally:
        connection.close()


def validate(index, manifest, expected_sources, expected_functions):
    require(manifest.to_dict()["authority"] == "structural_only", "unexpected proof authority")
    require(manifest.coverage["formalized_properties"] == manifest.coverage["checked_properties"] == 0,
            "structural fixture acquired proof or formalization counts")
    require(manifest.coverage["ast_ok"] == len(expected_sources), "incomplete native AST coverage")
    require(manifest.coverage["ast_failed"] == manifest.coverage["ast_partial"] == 0,
            "fixture contains a failed or partial AST")
    ast_cids = {}
    for path, data in expected_sources.items():
        projection = index.lookup(manifest, path)
        require(projection is not None, "missing active AST: " + path)
        require(sum(symbol.kind == "function" for symbol in projection.symbols) == expected_functions,
                "unexpected function symbol count: " + path)
        require(index.artifacts.get_bytes(projection.source_cid) == data, "source bytes do not replay: " + path)
        ast_cids[path] = projection.ast_cid
    require(index.load(manifest.cid).cid == manifest.cid, "CAS manifest identity does not replay")
    return ast_cids


def replay(request_path):
    request = json.loads(request_path.read_text(encoding="utf-8"))
    index, connection, frontend = index_for(request["database"], request["cas"],
                                          memory_mb=request["duckdb_memory_mb"])
    started = time.perf_counter()
    try:
        manifest = index.load(request["manifest_cid"])
        actual = {}
        for path in request["ast_cids"]:
            projection = index.lookup(manifest, path)
            require(projection is not None, "missing fresh-process AST")
            actual[path] = projection.ast_cid
        elapsed = time.perf_counter() - started
        require(actual == request["ast_cids"], "fresh-process AST identity mismatch")
        require(manifest.coverage == request["coverage"], "fresh-process coverage mismatch")
        require(frontend.parse_invocations == 0, "read unexpectedly invoked a parser")
        return {"manifest_cid": manifest.cid, "ast_cids": actual,
                "lookup_wall_seconds": elapsed, "parse_invocations": frontend.parse_invocations,
                "store_rows": counts(connection), "correctness_passed": True}
    finally:
        connection.close()


def trial(root, repository, originals, functions, number):
    directory = root / f"round-{number}"
    directory.mkdir()
    database, cas = directory / "ast.duckdb", directory / "cas"
    index, connection, frontend = index_for(database, cas)
    limits = CodebaseScanLimits(max_entries=len(originals) + 4, max_file_bytes=16 * 1024)
    paths = sorted(originals)
    changed = dict(originals)
    # Keep the function inventory fixed while changing one implementation body.
    changed[paths[0]] = originals[paths[0]].replace(b"return n + 1\n", b"return n + 1000001\n", 1)
    require(changed[paths[0]] != originals[paths[0]], "fixture mutation did not change code")
    previous = None
    cold = None
    measurements = []
    try:
        for stage, expected_sources, expected_parses in (
            ("cold", originals, len(originals)), ("unchanged", originals, 0),
            ("one_file_edit", changed, 1), ("restore_original", originals, 0),
        ):
            if stage in {"one_file_edit", "restore_original"}:
                (repository / paths[0]).write_bytes(expected_sources[paths[0]])
            before = frontend.parse_invocations
            rows_before = counts(connection)
            started = time.perf_counter()
            # Exercise default shared resource admission; no injected healthy
            # telemetry, private scheduler or bypass of host-pressure backoff.
            try:
                manifest = index.prepare(repository, repository_id="repository:codebase-ir-benchmark",
                                         previous=previous, limits=limits, memory_mb=PREPARATION_MEMORY_MB)
            except duckdb.OutOfMemoryException as error:
                require(counts(connection) == rows_before, "failed trial changed prior catalog rows")
                if previous is not None:
                    for path in paths:
                        require(index.lookup(previous, path) is not None, "failed trial invalidated prior AST")
                require_own_leases_released()
                return {"round": number, "status": "duckdb_buffer_allocation_failed",
                        "stage": stage, "wall_seconds": time.perf_counter() - started,
                        "error_type": type(error).__name__, "error": str(error),
                        "prior_catalog_preserved": True, "own_leases_remaining": 0,
                        "host_oom": False, "measurements": measurements,
                        "process_cumulative_peak_rss_mib": cumulative_peak_rss_mib()}
            elapsed = time.perf_counter() - started
            require_own_leases_released()
            parses = frontend.parse_invocations - before
            require(parses == expected_parses, f"{stage}: {parses} parses, expected {expected_parses}")
            ast_cids = validate(index, manifest, expected_sources, functions)
            if stage == "cold":
                cold = manifest
            elif stage == "one_file_edit":
                require(manifest.cid != cold.cid, "edit did not change manifest")
                require(manifest.snapshot.git_commit == cold.snapshot.git_commit, "dirty edit changed HEAD")
                require(manifest.snapshot.mode == "git-working", "edit not captured as working tree")
            else:
                require(manifest.cid == cold.cid, f"{stage}: original manifest identity changed")
            measurements.append({
                "stage": stage, "prepare_wall_seconds": elapsed,
                "ast_ingestor_parse_invocation_delta": parses, "expected_ast_ingestor_parse_invocations": expected_parses,
                "manifest_cid": manifest.cid, "snapshot_cid": manifest.snapshot.snapshot_cid,
                "semantic_state_cid": manifest.semantic_state.state_cid,
                "ast_revision_id": manifest.ast_revision_id, "ast_cids": ast_cids,
                "snapshot_mode": manifest.snapshot.mode, "git_commit": manifest.snapshot.git_commit,
                "coverage": manifest.coverage, "store_rows": counts(connection),
                "process_cumulative_peak_rss_mib": cumulative_peak_rss_mib(),
                "correctness_passed": True,
            })
            previous = manifest
        replay_request = {
            "database": str(database), "cas": str(cas), "manifest_cid": manifest.cid,
            "ast_cids": ast_cids, "coverage": manifest.coverage,
            "duckdb_memory_mb": int(DB_CONFIG["memory_limit"].removesuffix("MB")),
        }
    finally:
        connection.close()
        # Leave the fixture at its admitted original revision even on failure.
        (repository / paths[0]).write_bytes(originals[paths[0]])
    request_path = directory / "replay-request.json"
    request_path.write_text(json.dumps(replay_request, sort_keys=True), encoding="utf-8")
    started = time.perf_counter()
    run = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--replay", str(request_path)],
                         cwd=REPOSITORY_ROOT, capture_output=True, text=True, timeout=60)
    process_elapsed = time.perf_counter() - started
    require(run.returncode == 0, "fresh-process replay failed: " + run.stderr[-8000:])
    fresh = json.loads(run.stdout.splitlines()[-1])
    require(fresh["manifest_cid"] == manifest.cid and fresh["ast_cids"] == ast_cids,
            "independent process returned different identities")
    fresh["process_wall_seconds_including_startup"] = process_elapsed
    return {"round": number, "status": "completed", "measurements": measurements, "fresh_process_replay": fresh}


def main():
    global PREPARATION_MEMORY_MB
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--files", type=int, default=8)
    parser.add_argument("--functions", type=int, default=4)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--duckdb-memory-mb", type=int, choices=(64, 128, 256), default=64)
    parser.add_argument("--preparation-memory-mb", type=int, choices=(512, 1024), default=512)
    parser.add_argument("--replay", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.replay is not None:
        print(json.dumps(replay(args.replay), sort_keys=True))
        return
    if args.output is None:
        parser.error("--output is required")
    if not (1 <= args.files <= 32 and 1 <= args.functions <= 16 and 1 <= args.rounds <= 5):
        parser.error("bounds: 1..32 files, 1..16 functions per file, 1..5 rounds")
    DB_CONFIG["memory_limit"] = f"{args.duckdb_memory_mb}MB"
    PREPARATION_MEMORY_MB = args.preparation_memory_mb
    scheduler = get_global_resource_scheduler()
    require(scheduler.config.proof_safety_enabled, "benchmark requires default resource safety enabled")
    started_at = datetime.now(timezone.utc).isoformat()
    memory_at_start = startup_memory_evidence()
    with tempfile.TemporaryDirectory(prefix="codebase-ir-benchmark-") as temporary:
        root = Path(temporary)
        repository = root / "repository"
        originals = fixture(repository, args.files, args.functions)
        calibration = [calibrate_memory(root, originals, cap) for cap in (64, 128)]
        results = []
        failed_trials = []
        effective_files, effective_functions = args.files, args.functions
        for number in range(1, args.rounds + 1):
            result = trial(root, repository, originals, args.functions, number)
            if result["status"] != "completed":
                failed_trials.append(result)
                break
            results.append(result)
        if failed_trials:
            fallback_root = root / "smaller-fixture"
            fallback_root.mkdir()
            fallback_repository = fallback_root / "repository"
            effective_files, effective_functions = min(args.files, 2), min(args.functions, 2)
            fallback_sources = fixture(fallback_repository, effective_files, effective_functions)
            results = [trial(fallback_root, fallback_repository, fallback_sources, effective_functions, number)
                       for number in range(1, args.rounds + 1)]
            require(all(result["status"] == "completed" for result in results),
                    "bounded fallback fixture also exceeded the final database cap")
    summary = {}
    for stage in STAGES:
        rows = [row for result in results for row in result["measurements"] if row["stage"] == stage]
        times = [row["prepare_wall_seconds"] for row in rows]
        summary[stage] = {"median_prepare_wall_seconds": statistics.median(times),
                          "min_prepare_wall_seconds": min(times), "max_prepare_wall_seconds": max(times),
                          "ast_ingestor_parse_invocation_deltas": [row["ast_ingestor_parse_invocation_delta"] for row in rows]}
    rss_peak = cumulative_peak_rss_mib()
    report = {
        "schema": "codebase-ir-structural-benchmark@1", "started_at_utc": started_at,
        "scope": "structural_only", "correctness_passed": True,
        "memory_calibration": calibration,
        "memory_envelope_assessment": {
            "measurement": "cumulative parent-process high-water RSS, including calibration, prior rounds and validation",
            "declared_preparation_reservation_mib": PREPARATION_MEMORY_MB,
            "observed_process_cumulative_peak_rss_mib": rss_peak,
            "cumulative_peak_above_reservation_mib": None if rss_peak is None else max(0, rss_peak - PREPARATION_MEMORY_MB),
            "observed_peak_within_reservation": None if rss_peak is None else rss_peak <= PREPARATION_MEMORY_MB,
            "reservation_is_hard_rss_limit": False,
            "child_process_rss_included": False,
            "source": "/proc/self/status VmHWM" if sys.platform.startswith("linux") else "resource.getrusage(RUSAGE_SELF)",
            "startup_evidence": memory_at_start,
        },
        "failed_requested_fixture_trials": failed_trials,
        "not_qualified": ["formalization", "proof_execution", "online_training", "many_core_scaling"],
        "configuration": {"requested_files": args.files, "requested_functions_per_file": args.functions,
                          "files": effective_files, "functions_per_file": effective_functions, "rounds": args.rounds,
                          "duckdb": DB_CONFIG, "scheduler": "shared_default",
                          "resource_safety_enabled": scheduler.config.proof_safety_enabled,
                          "preparation_memory_reservation_mb": PREPARATION_MEMORY_MB},
        "runtime": {"python": sys.version, "duckdb": duckdb.__version__, "platform": platform.platform(),
                    "machine": platform.machine(), "logical_cpu_count": os.cpu_count(),
                    "git": subprocess.check_output(["git", "--version"], text=True, timeout=10).strip(),
                    "component_sha256": {
                        name: hashlib.sha256((REPOSITORY_ROOT / "ipfs_datasets_py/logic/software_contracts" / name).read_bytes()).hexdigest()
                        for name in ("codebase_ir.py", "duckdb_ingest.py", "duckdb_ast_store.py", "cache.py")
                    },
                    "benchmark_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
        "measurement_notes": [
            "Cold means a new ingestor, empty DuckDB catalog and empty CAS; OS filesystem caches are not flushed.",
            "Parse invocation deltas count only native AST-ingestor extraction. The semantic scanner independently re-extracts source on every prepare, including warm runs.",
            "Prepare timing includes default shared scheduler admission and any host-pressure waiting; fixture mutation and correctness validation are outside it.",
            "Fresh-process lookup timing excludes import/connection startup; process_wall_seconds_including_startup includes them.",
            "RSS is cumulative current-image high-water RSS across earlier stages and rounds, not a stage-specific peak; child-process RSS is excluded. Linux uses /proc/self/status VmHWM because getrusage may retain a previous executable image's high-water value across exec; startup evidence records both.",
            "SQL row counts describe the durable catalog, including retained source metadata and invalidation audit rows.",
            "Database buffer limits and shared admission reservations are explicit configuration values. Separate 64MB/128MB calibrations record success or database allocation failures; failure verifies transaction rollback and lease release. This is not a host RAM exhaustion test.",
            "Temporary Git fixture, CAS and database are removed after independent replay; exact identity receipts remain in this report.",
        ],
        "summary": summary, "rounds": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "summary": summary, "correctness_passed": True}, indent=2))


if __name__ == "__main__":
    main()
