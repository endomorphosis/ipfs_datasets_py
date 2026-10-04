"""Bounded current-source -> typed intent -> native SMT checking benchmark.

Requires the sibling ipfs_accelerate checkout on PYTHONPATH, plus native Z3 and
CVC5. Historical cache hits always reexecute both solvers. No target import,
online training, kernel proof, runtime-behavior or many-core scaling claim.
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
from bench_codebase_current import open_index
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
from ipfs_datasets_py.logic.software_contracts.codebase_ir import StaleCodebaseError
from ipfs_datasets_py.logic.software_contracts.codebase_property_cache import CodebasePropertyCache
from ipfs_accelerate_py.agent_supervisor.planning import checked_integer_codebase as matcher

VIEW = "worktree:conditional-integer-benchmark"
TEXT = "Under python-integer-offset@1, module_000.py::operation_0_0(n) must return n + {offset}."


def check(index, repository, head, cache, offset, expected, history_hit):
    source_text = TEXT.format(offset=offset)
    started = time.perf_counter()
    match = matcher.match_checked_integer_intent(
        index=index, repository=repository, repository_id=VIEW, expected_head=head,
        intent_document=matcher.build_integer_offset_intent(source_text), source_text=source_text,
        cache=cache, timeout_seconds=30, admission_timeout_seconds=10,
    )
    elapsed = time.perf_counter() - started
    checked = match["checked_result"]
    base.require(match["status"] == expected, "incorrect contract match")
    base.require(checked["cache_history_hit"] is history_hit, "unexpected historical cache outcome")
    base.require(checked["solver_replayed"] is True, "native verification was bypassed")
    observations = checked["checks"]["solvers"]
    base.require(len(observations) == 2, "both native solvers must report")
    base.require({item["solver"] for item in observations} == {"z3", "cvc5"}, "wrong solver set")
    base.require(all(item["status"] == checked["status"] for item in observations), "solver disagreement")
    base.require(all(item["workspace_cleaned"] for item in observations), "workspace leaked")
    base.require(match["semantic_alignment_verified"] is True, "exact sentence did not align")
    base.require(match["residual_requirements"] and not match["current_behavioral_facts"], "runtime authority granted")
    base.require(not any(match[key] for key in (
        "behavioral_satisfaction", "execution_authority", "completion_authority", "proof_authority")),
        "conditional contract acquired planner authority")
    base.require_own_leases_released()
    return {"wall_seconds": elapsed, "match": match, "correctness_passed": True}


def replay(request):
    index, connection, frontend = open_index(request["database"], request["artifacts"])
    try:
        result = check(index, request["repository"], CodebaseHead.from_dict(request["head"]),
                       CodebasePropertyCache(request["cache"]), 1, "conditional_contract_matched", True)
        base.require(frontend.parse_invocations == 0, "fresh observation reparsed the AST index")
        return result
    finally:
        connection.close()


def trial(root, number):
    directory = root / f"round-{number}"
    directory.mkdir()
    repository = directory / "repository"
    originals = base.fixture(repository, 1, 1)
    database, artifacts, cache_path = directory / "ast.duckdb", directory / "artifacts", directory / "cache"
    index, connection, _ = open_index(database, artifacts)
    cache = CodebasePropertyCache(cache_path)
    limits = base.CodebaseScanLimits(max_entries=4, max_file_bytes=1024)
    rows = []
    try:
        head = index.prepare_current(repository, repository_id=VIEW, operation_id="initial",
                                     expected_head=None, limits=limits).head
        for stage, offset, status, history in (
            ("cold_check", 1, "conditional_contract_matched", False),
            ("historical_hit_fresh_check", 1, "conditional_contract_matched", True),
            ("wrong_contract", 2, "conditional_contract_refuted", False),
        ):
            rows.append({"stage": stage, **check(index, repository, head, cache, offset, status, history)})
        original = originals["module_000.py"]
        (repository / "module_000.py").write_bytes(original.replace(b"n + 1", b"n + 2"))
        try:
            check(index, repository, head, cache, 1, "conditional_contract_matched", True)
        except StaleCodebaseError:
            pass
        else:
            raise AssertionError("stale source was accepted")
        successor = index.prepare_current(repository, repository_id=VIEW, operation_id="edit",
                                          expected_head=head, limits=limits).head
        rows.append({"stage": "changed_source", **check(index, repository, successor, cache, 2,
                     "conditional_contract_matched", False)})
        (repository / "module_000.py").write_bytes(original)
        restored = index.prepare_current(repository, repository_id=VIEW, operation_id="restore",
                                         expected_head=successor, limits=limits).head
        base.require(restored.generation == 3, "restore lost head generation")
        rows.append({"stage": "restored_source", **check(index, repository, restored, cache, 1,
                     "conditional_contract_matched", True)})
        base.require_own_leases_released()
        request = {"database": str(database), "artifacts": str(artifacts), "cache": str(cache_path),
                   "repository": str(repository), "head": restored.to_dict()}
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
    base.require(fresh["match"]["checked_result"]["cache_binding"] ==
                 rows[0]["match"]["checked_result"]["cache_binding"], "restart cache identity changed")
    return {"round": number, "measurements": rows, "fresh_process_replay": fresh,
            "stale_source_rejections": 1}


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
    started = datetime.now(timezone.utc).isoformat()
    startup = base.startup_memory_evidence()
    with tempfile.TemporaryDirectory(prefix="codebase-integer-benchmark-") as directory:
        rounds = [trial(Path(directory), number) for number in range(1, 4)]
    summary = {}
    for stage in ("cold_check", "historical_hit_fresh_check", "wrong_contract", "changed_source", "restored_source"):
        rows = [row for result in rounds for row in result["measurements"] if row["stage"] == stage]
        summary[stage] = {"median_wall_seconds": statistics.median(row["wall_seconds"] for row in rows),
                          "runs": len(rows)}
    sources = [Path(__file__).resolve(), Path(matcher.__file__).resolve()] + [
        base.REPOSITORY_ROOT / "ipfs_datasets_py/logic/software_contracts" / name for name in (
            "codebase_integer_profile.py", "codebase_integer_verification.py", "codebase_property_cache.py")]
    report = {
        "schema": "codebase-integer-benchmark@1", "started_at_utc": started, "correctness_passed": True,
        "scope": "conditional_integer_contract", "rounds": rounds, "summary": summary,
        "configuration": {"source_files": 1, "functions": 1, "rounds": 3, "duckdb": base.DB_CONFIG,
                          "scheduler": "shared_default", "resource_safety_enabled": True,
                          "verification_memory_reservation_mib": 1024, "solver_memory_cap_mib": 256,
                          "solvers": ["z3", "cvc5"], "solver_execution": "sequential", "native_check_budget_seconds": 10},
        "memory": {"main_process_cumulative_peak_rss_mib": base.cumulative_peak_rss_mib(), "startup": startup,
                   "includes_child_rss": False, "reservation_is_hard_rss_limit": False},
        "runtime": {"python": sys.version, "duckdb": base.duckdb.__version__,
                    "platform": base.platform.platform(), "logical_cpu_count": base.os.cpu_count()},
        "source_sha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
        "measurement_notes": [
            "Wall time includes intent decoding, entry/exit live observations, compilation, solver version probes and fresh solves, cache I/O and result sealing.",
            "All measured matches reexecute both native solvers; refutations also replay SAT with get-model. No proof-execution cache bypass or warm speedup is claimed.",
            "Publication is outside match timings. Cold means empty property cache; OS caches are not flushed.",
            "Default scheduler observes ambient pressure; no host pressure is deliberately induced. Tests inject pressure telemetry separately.",
            "Parent peak RSS is cumulative and excludes child RSS; reservations do not hard-limit the Python process.",
            "Conditional integer arithmetic excludes dynamic module binding, arbitrary Python values, resource failures and asynchronous exceptions; runtime requirements remain residual.",
            "No neural training, broad intent semantics, kernel reconstruction, DuckLake publication, worker admission or many-core scaling is qualified.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"correctness_passed": True, "summary": summary, "memory": report["memory"]}, indent=2))


if __name__ == "__main__":
    main()
