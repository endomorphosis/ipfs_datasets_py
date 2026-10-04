"""Requalify bounded SMT and retained evidence with an unchanged saved pool.

The wrapper only pins the benchmark's process-local default configuration and
redirects the frozen benchmark's exact replay command back through this file.
It does not replace resource samplers, admission, producers, or proof loaders.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import traceback

import bench_codebase_smt_execution as frozen

base = frozen.base
SCHEMA = "codebase-restart-safety-benchmark@1"
PIN_SCHEMA = "codebase-saved-scheduler-config@1"
_frozen_source_pins = frozen.source_pins


def pins():
    return {**_frozen_source_pins(),
            str(Path(__file__).resolve()): base.digest(Path(__file__).read_bytes())}


def read_json(path, maximum=128 * 1024):
    with Path(path).open("rb") as stream:
        raw = stream.read(maximum + 1)
    base.require(len(raw) <= maximum, "bounded JSON input exceeded: " + str(path))
    return json.loads(raw)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def state_summary(path):
    value = read_json(path, 4 * 1024 * 1024)
    return {"schema_version": value["schema_version"], "config": value["config"],
            "active_leases": len(value["leases"]), "waiting_requests": len(value["waiters"]),
            "owned_active_leases": sum(row["owner_pid"] == os.getpid() for row in value["leases"].values()),
            "owned_waiting_requests": sum(row["owner_pid"] == os.getpid() for row in value["waiters"].values()),
            "next_sequence": value["next_sequence"]}


def runtime():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import collect_proof_host_resources
    return {"boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "python": sys.version, "platform": platform.platform(), "pid": os.getpid(),
            "logical_cpus": os.cpu_count(), "host_resources": asdict(collect_proof_host_resources()),
            "recorded_at_utc": datetime.now(timezone.utc).isoformat()}


def capture_config(path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduler
    state_path = scheduler.default_scheduler_state_path().resolve()
    saved = state_summary(state_path)
    config = saved["config"]
    base.require(config["proof_safety_enabled"] is True, "saved proof safety is disabled")
    base.require((config["total_cpu_slots"], config["total_memory_mb"],
                  config["total_child_process_slots"]) in {(4, 9830, 4), (16, 99688, 16)},
                 "saved qualification envelope differs from the two reviewed observed pools")
    base.require(not path.exists(), "saved config pin must have a fresh path")
    write_json(path, {"schema": PIN_SCHEMA, "state_path": str(state_path),
                     "config": config, "state_before": saved, "runtime": runtime(),
                     "allow_foreign_work": True})


def guarded_owner(config):
    """Refuse external reconfiguration inside every real scheduler state lock."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduler

    class PinnedBenchmarkScheduler(scheduler.GlobalResourceScheduler):
        def _validate_state_configuration(self, state, *, allow_reconfigure=False):
            if not self.state_path.exists() or state.get("config") != self.config.persisted_dict():
                raise scheduler.ResourceConfigurationError("benchmark refuses shared pool drift or recreation")
            super()._validate_state_configuration(state, allow_reconfigure=allow_reconfigure)

    return PinnedBenchmarkScheduler(config)


def install_saved_owner(path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduler
    envelope = read_json(path)
    base.require(envelope["schema"] == PIN_SCHEMA, "unknown config pin")
    state_path = Path(envelope["state_path"]).resolve()
    saved = state_summary(state_path)
    base.require(saved["config"] == envelope["config"], "shared capacities changed since pinning")
    base.require(envelope.get("allow_foreign_work") is True or
                 (not saved["active_leases"] and not saved["waiting_requests"]),
                 "this config pin requires no active shared work")
    config = scheduler.ResourceSchedulerConfig(state_path=state_path, **envelope["config"])
    config.validate()
    base.require(config.persisted_dict() == envelope["config"], "persisted config cannot round-trip")
    base.require(config.proof_safety_enabled, "saved proof safety is disabled")
    # Explicit conservative configuration, within this benchmark interpreter.
    # Normal no-argument clients use the same owner, including imported aliases.
    scheduler.default_resource_scheduler_config = lambda: config
    owner = guarded_owner(config)
    with scheduler._GLOBAL_SCHEDULERS_LOCK:
        scheduler._GLOBAL_SCHEDULERS[str(owner.state_path)] = owner
    base.require(scheduler.get_global_resource_scheduler() is owner, "default owner differs")
    base.require(not base.own_leases(owner), "qualification must start without owned leases")
    base.require(state_summary(state_path)["config"] == envelope["config"], "installation changed saved pool")
    return owner, envelope


class ReplayRedirect:
    """Module-local proxy; native producer subprocess calls remain untouched."""

    def __init__(self, config_path):
        self.config_path = config_path.resolve()
        self.redirected = []

    def run(self, command, *args, **kwargs):
        expected = [sys.executable, str(Path(frozen.__file__).resolve()), "--replay"]
        if isinstance(command, list) and len(command) == 4 and command[:3] == expected:
            original = command
            command = [sys.executable, str(Path(__file__).resolve()), "--replay", command[3],
                       "--pinned-config", str(self.config_path)]
            self.redirected.append({"original_argv": original, "actual_argv": command,
                                    "timeout_seconds": kwargs.get("timeout")})
        return subprocess.run(command, *args, **kwargs)


def replay(request_path, config_path):
    owner, envelope = install_saved_owner(config_path)
    runtime_before = runtime()
    before = state_summary(owner.state_path)
    request = read_json(request_path)
    base.require(pins() == request["execution_source_pins"], "source generation changed before replay")
    result = base.replay(request)
    base.require(pins() == request["execution_source_pins"], "source generation changed during replay")
    after = state_summary(owner.state_path)
    base.require(after["config"] == envelope["config"], "child replay changed shared configuration")
    base.require(not after["owned_active_leases"] and not after["owned_waiting_requests"], "child replay did not drain owned work")
    result.update(execution_source_pins=pins(), saved_pool_before=before, saved_pool_after=after,
                  config_pin_sha256=base.digest(config_path.read_bytes()), runtime=runtime_before)
    return result


def artifact_hashes(directory):
    paths = sorted(directory.rglob("*"))
    base.require(len(paths) <= 4096, "retained CAS inventory exceeds qualification bound")
    total, result = 0, {}
    for path in paths:
        if path.is_file():
            total += path.stat().st_size
            base.require(total <= 256 * 1024 * 1024, "retained CAS exceeds qualification byte bound")
            result[str(path.relative_to(directory))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def historical(directory, config_path, database_directory):
    """Read original v2 durable evidence; preserve its historical generation."""
    import duckdb
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog, CodebaseHead
    from ipfs_datasets_py.duckdb_control.codebase_verification_catalog import CodebaseVerificationCatalog
    from ipfs_datasets_py.duckdb_control.codebase_verification_queries import CodebaseVerificationSelector
    from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
    from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex, StaleCodebaseError
    from ipfs_datasets_py.logic.software_contracts.codebase_resources import acquire_codebase_resources
    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
    from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
    owner, envelope = install_saved_owner(config_path)
    runtime_before = runtime()
    before_pins, before_pool = pins(), state_summary(owner.state_path)
    metadata = read_json(directory / "result.json", 32 * 1024 * 1024)
    before_cas = artifact_hashes(directory / "artifacts")
    before_db = base.digest((directory / "catalog.duckdb").read_bytes())
    base.require(not (directory / "catalog.duckdb.wal").exists(), "historical fixture has an active WAL")
    base.require((directory / "catalog.duckdb").stat().st_size <= 256 * 1024 * 1024,
                 "historical database exceeds bounded copy size")
    database_directory.mkdir(parents=True, exist_ok=False)
    database = database_directory / "catalog.duckdb"
    # The native AST owner issues CREATE IF NOT EXISTS even when its tables
    # exist. A closed database copy preserves original bytes while allowing
    # its ordinary constructor; CAS bindings continue to name original CAS.
    shutil.copy2(directory / "catalog.duckdb", database)
    base.require(base.digest(database.read_bytes()) == before_db, "historical database copy differs")
    audit = frozen.ProcessAudit()
    sys.addaudithook(audit.observe)
    projections = []
    deadline = base.Deadline(120, 90)
    cx = None
    try:
        with audit.scope("historical", only_git=True):
            cx = duckdb.connect(str(database), config=base.DB_CONFIG)
            store = DuckDBASTStore(connection=cx)
            artifacts = ImmutableCAS(directory / "artifacts")
            index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=artifacts,
                                           catalog=CodebaseCatalog(store, artifacts))
            catalog = CodebaseVerificationCatalog(index)
            with acquire_codebase_resources(memory_mb=512, timeout_seconds=30) as parent:
                with store._lock, store._transaction():
                    for producer in metadata["producers"]:
                        deadline.options()
                        projection = catalog._read(producer["projection_cid"])
                        v, a = projection.verification.to_dict(), projection.applicability.to_dict()
                        base.require(v["schema"] == "codebase-conditional-verification@2"
                                     and a["schema"] == "codebase-input-applicability@2", "fixture is not retained v2")
                        base.require(v["process_observations"] + a["process_observations"] == producer["observations"],
                                     "retained native observations changed")
                        base.require(not projection.verification.observed_live and not projection.applicability.observed_live,
                                     "historical replay became live evidence")
                        projections.append(projection.projection_cid)
                old_head = CodebaseHead.from_dict(metadata["head"])
                current_head = CodebaseHead.from_dict(metadata["query_controls"]["successor_head"])
                base.require(index.current(current_head.repository_id) == current_head, "retained successor changed")
                try:
                    catalog.query_current(directory / "source", expected_head=old_head,
                        selector=CodebaseVerificationSelector(), parent_lease=parent, **deadline.options())
                except StaleCodebaseError:
                    old_head_rejected = True
                else:
                    raise AssertionError("historical generation became current")
                page = catalog.query_current(directory / "source", expected_head=current_head,
                    selector=CodebaseVerificationSelector(), parent_lease=parent, **deadline.options())
                base.require(page.complete and not page.entries, "historical evidence leaked to successor")
    finally:
        deadline.close()
        if cx is not None:
            cx.close()
    after_cas = artifact_hashes(directory / "artifacts")
    after_db = base.digest((directory / "catalog.duckdb").read_bytes())
    after_pool = state_summary(owner.state_path)
    checks = {"eight_original_v2_projections": len(projections) == 8,
              "cas_bytes_unchanged": before_cas == after_cas, "database_bytes_unchanged": before_db == after_db,
              "old_head_rejected": old_head_rejected, "successor_has_no_inherited_evidence": not page.entries,
              "solver_free": all(event["kind"] == "git" for event in audit.events),
              "pool_config_unchanged": after_pool["config"] == envelope["config"],
              "owned_leases_drained": not after_pool["owned_active_leases"] and not after_pool["owned_waiting_requests"],
              "source_generation_unchanged": before_pins == pins()}
    base.require(all(checks.values()), "retained-v2 historical replay checks failed")
    return {"completed": True, "checks": checks, "original_directory": str(directory),
            "reopened_database_copy": str(database),
            "projection_cids": projections, "cas_sha256": after_cas, "database_sha256": after_db,
            "process_audit": {"counts": audit.counts, "events": audit.events},
            "saved_pool_before": before_pool, "saved_pool_after": after_pool,
            "source_pins_before": before_pins, "source_pins_after": pins(), "runtime": runtime_before}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pinned-config", type=Path)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--historical", type=Path)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--rounds", type=int, choices=range(1, 4), default=3)
    parser.add_argument("--overall-timeout", type=float, default=600)
    parser.add_argument("--operation-timeout", type=float, default=120)
    args = parser.parse_args()
    sys.path[:0] = [str(base.ACCELERATE), str(base.ROOT)]
    from ipfs_accelerate_py.agent_supervisor.planning import conditional_codebase_evidence
    base.require(Path(conditional_codebase_evidence.__file__).resolve() ==
        base.ACCELERATE / "ipfs_accelerate_py/agent_supervisor/planning/conditional_codebase_evidence.py",
        "supervisor matcher resolved outside the pinned accelerate checkout")
    frozen.source_pins = pins
    if args.replay or args.historical:
        base.require(args.pinned_config is not None, "replay requires exact saved config pin")
        if args.historical:
            base.require(args.result is not None and not args.result.exists(), "historical replay requires a fresh --result")
        started = time.perf_counter()
        try:
            result = (replay(args.replay, args.pinned_config) if args.replay else
                      historical(args.historical.resolve(), args.pinned_config,
                                 args.result.resolve().parent / (args.result.stem + "-database")))
        except BaseException as error:
            result = {"completed": False, "error": {"type": type(error).__name__,
                       "message": str(error), "traceback": traceback.format_exc()}}
        result["wall_seconds"] = time.perf_counter() - started
        if args.result:
            base.require(not args.result.exists(), "result path already exists")
            write_json(args.result, result)
        print(json.dumps(result))
        return 0 if result["completed"] else 1
    base.require(args.output is not None, "--output is required")
    base.require(0 < args.operation_timeout <= args.overall_timeout <= 900, "invalid finite deadlines")
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    base.require(not (directory / "result.json").exists() and not (directory / "source").exists(),
                 "qualification output already used")
    config_path = args.pinned_config or directory / "saved-scheduler-config.json"
    if args.pinned_config is None:
        capture_config(config_path)
    owner, envelope = install_saved_owner(config_path)
    proxy = ReplayRedirect(config_path)
    frozen.subprocess = proxy
    report = {"schema": SCHEMA, "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "completed": False, "errors": [], "saved_pool_before": state_summary(owner.state_path),
              "restart_runtime": runtime(), "config_pin": str(config_path.resolve()),
              "config_pin_sha256": base.digest(config_path.read_bytes()),
              "configuration": {"units": 8, "rounds": args.rounds, "page_size": 3, "duckdb": base.DB_CONFIG,
                  "overall_timeout_seconds": args.overall_timeout, "operation_timeout_seconds": args.operation_timeout,
                  "saved_configuration": envelope["config"], "native_per_process_as_bytes": 128 * 1024**2,
                  "native_sampled_tree_rss_bytes": 128 * 1024**2},
              "scope": {"explicit_saved_pool_is_process_local_default": True,
                  "foreign_leases_may_coexist": envelope.get("allow_foreign_work") is True,
                  "locked_configuration_drift_refused": True,
                  "original_benchmarks_edited": False, "samplers_or_admission_replaced": False,
                  "hard_aggregate_cgroup_memory": False, "kernel_checked": False,
                  "runtime_behavior_verified": False, "scaling_qualification": False}}
    write_json(directory / "command.json", {"argv": [sys.executable, *sys.argv],
               "cwd": str(Path.cwd()), "source_pins": pins(), "config_pin_sha256": report["config_pin_sha256"]})
    started = time.perf_counter()
    try:
        frozen.benchmark(directory, report, rounds=args.rounds, seconds=args.overall_timeout,
                         operation_seconds=args.operation_timeout)
    except BaseException as error:
        report["completed"] = False
        report["errors"].append({"type": type(error).__name__, "message": str(error),
                                 "traceback": traceback.format_exc()})
    finally:
        report["saved_pool_after"] = state_summary(owner.state_path)
        report["replay_redirects"] = proxy.redirected
        report["wrapper_checks"] = {
            "saved_pool_unchanged": report["saved_pool_after"]["config"] == envelope["config"],
            "pinned_config_unchanged": report["config_pin_sha256"] == base.digest(config_path.read_bytes()),
            "owned_shared_leases_drained": not report["saved_pool_after"]["owned_active_leases"]
                and not report["saved_pool_after"]["owned_waiting_requests"],
            "one_exact_replay_redirect": len(proxy.redirected) == 1,
            "fresh_child_used_same_config": report.get("restart", {}).get("config_pin_sha256") == report["config_pin_sha256"],
            "same_boot_during_run": Path("/proc/sys/kernel/random/boot_id").read_text().strip()
                == report["restart_runtime"]["boot_id"],
        }
        report["completed"] = report["completed"] and all(report["wrapper_checks"].values())
        report["wall_seconds"] = time.perf_counter() - started
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_json(directory / "result.json", report)
    print(json.dumps({"result": str(directory / "result.json"), "completed": report["completed"],
                      "wall_seconds": report["wall_seconds"], "checks": report.get("checks", {}),
                      "wrapper_checks": report["wrapper_checks"]}))
    return 0 if report["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
