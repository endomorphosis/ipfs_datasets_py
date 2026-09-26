#!/usr/bin/env python3
"""One explicitly requested owner-leased native daemon qualification.

Uses the real owner, immutable request, isolated offline workers, native daemon
and independent checkpoint verifier. Historical evidence is read-only. This is
one six-record integration qualification, not a throughput or theorem claim.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
HELPER_PATH = Path(__file__).with_name("qualify_daemon_corpus_inputs.py")
HELPER_SHA = "cc8b6ed99be0790b58cbf2e5585d9b20d3b48f68c5541edae50b1269a991e16f"
RUN_ID = "owner-leased-qualification"
STORAGE_ROOTS = (ROOT / "workspace/test-logs", ROOT / "workspace/todo-queues",
                 ROOT / "docs/implementation/reports/evidence", Path("/tmp/pytest-of-barberb"))
LEDGER = ROOT / "workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json"
STORAGE_BYTES, MEMORY_MB, CAPACITY = 1_000_000_000, 3072, 88319
TIMEOUT_SECONDS, LEASE_SECONDS = 900, 300
SCHEDULER_ENV = ("IPFS_DATASETS_RESOURCE_SCHEDULER_PATH", "IPFS_DATASETS_RESOURCE_CPU_SLOTS",
    "IPFS_DATASETS_RESOURCE_MEMORY_MB", "IPFS_DATASETS_RESOURCE_GPU_MEMORY_MB",
    "IPFS_DATASETS_RESOURCE_UNIFIED_MEMORY_MB", "IPFS_DATASETS_RESOURCE_CHILD_PROCESS_SLOTS")


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_helper():
    if sha(HELPER_PATH) != HELPER_SHA:
        raise ValueError("historical qualification helper changed")
    spec = importlib.util.spec_from_file_location("_owned_qualification_pinned_helper", HELPER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parent_environment(helper, inherited):
    value = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8",
        "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1",
        "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1", **helper.ENVIRONMENT}
    for key in ("HOME", "XDG_CACHE_HOME", "HF_HOME", "HF_HUB_CACHE", "TRANSFORMERS_CACHE", *SCHEDULER_ENV):
        if key in inherited:
            value[key] = inherited[key]
    return value


def resource_policy():
    return {"ledger_path": str(LEDGER), "roots": [str(path) for path in STORAGE_ROOTS],
            "storage_bytes": STORAGE_BYTES, "memory_mb": MEMORY_MB, "cpu_slots": 1}


def daemon_argv(helper, snapshot):
    result = helper.daemon_argv(snapshot, CAPACITY, native_cycle=True)
    result[result.index("--run-id") + 1] = RUN_ID
    return result


def require(condition, message):
    if not condition:
        raise ValueError(message)


def stage(label, **values):
    print(json.dumps({"stage": label, **values}, sort_keys=True), flush=True)


def cycle_from_log(helper, reference):
    helper.verify(reference)
    require(reference["bytes"] <= helper.MAX_JSON_BYTES, "native log exceeds audit bound")
    rows = []
    with Path(reference["path"]).open() as stream:
        for line in stream:
            value = json.loads(line)
            if value.get("event") == "cycle":
                rows.append(value)
    require(len(rows) == 1, "expected exactly one native cycle event")
    return rows[0]


def qualification_checks(helper, native, independent, request, cycle, input_walk):
    summary = native["summary"]
    bridges = helper.BRIDGES
    selected = {role: set(cycle.get(role + "_indices", [])) ==
        {row["index"] for row in input_walk["roles"][role]}
        and len(cycle.get(role + "_indices", [])) == 3 for role in ("train", "validation")}
    arguments = request["effective_arguments"]
    passes = native.get("sample_memory_policy", {}).get("evaluation_passes", [])
    memory = {row["phase"]: row["use_sample_memory"] for row in passes}
    expected_memory = {"before_train_evaluation": True, "before_after_train_evaluation": True,
                       "before_validation_evaluation": False, "before_after_validation_evaluation": False}
    # Observation phase names are matched explicitly, never inferred from timing.
    memory_checks = {name: memory.get(name) is wanted for name, wanted in expected_memory.items()}
    result = {
        "native_success": native.get("success") is True and native.get("native_exit_code") == 0,
        "independent_success": independent.get("success") is True,
        "independent_final_evaluation_matches": independent.get("evaluation_matches_final") is True,
        "no_callable_replacements": native.get("callable_replacements") == [],
        "native_network_denied": native.get("network_guard", {}).get("socket_denial_verified") is True,
        "independent_network_denied": independent.get("network_guard", {}).get("socket_denial_verified") is True,
        "default_async_enabled": arguments.get("snapshot_evaluation_enabled") is True,
        "default_async_flag_omitted": "--snapshot-evaluation-enabled" not in request["daemon_argv"],
        "snapshot_lifecycle": all(helper.snapshot_checks(summary).values()),
        "selection_train_exact_three": selected["train"], "selection_validation_exact_three": selected["validation"],
        "four_positive_three_target_evaluations": all(cycle.get(name, {}).get("legal_ir_target_count") == 3 for name in helper.EVALUATIONS),
        "five_diagnostics_train": helper.bridge_diagnostics_complete(cycle.get("logic_bridge_train", {})),
        "five_diagnostics_validation": helper.bridge_diagnostics_complete(cycle.get("logic_bridge_validation", {})),
        "five_requested_bridge_names": all(arguments.get(name) == ",".join(bridges) for name in
            ("bridge_loss_adapters", "autoencoder_metric_bridge_adapters", "autoencoder_diagnostic_bridge_adapters")),
        "bridge_provers_false": arguments.get("bridge_evaluate_provers") is False,
        "one_bridge_worker": arguments.get("autoencoder_bridge_workers") == 1,
        "metric_disk_cache_disabled": request["environment"].get("IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE") == "0",
        "whole_optimizer_and_bridge_text": arguments.get("max_sample_text_chars") == 0
            and arguments.get("autoencoder_metric_bridge_max_sample_text_chars") == 0,
        "sample_memory_passes": len(passes) == 4 and set(memory) == set(expected_memory)
            and all(memory_checks.values()),
        "projection_report_memory_false": native.get("sample_memory_policy", {}).get("projection_report_sample_memory_used") is False,
        "independent_memory_observation_matches": native.get("sample_memory_policy") == independent.get("sample_memory_policy"),
        "native_runtime_guards": bool(native.get("runtime_guards")) and all(native["runtime_guards"].values()),
        "independent_runtime_guards": bool(independent.get("runtime_guards")) and all(independent["runtime_guards"].values()),
    }
    return result, memory_checks


def inspect_private_database(database, run_id):
    import duckdb
    connection = duckdb.connect(str(database), read_only=True)
    try:
        events = [{"event_id": row[0], "kind": row[1], "data": json.loads(row[2])} for row in
                  connection.execute("SELECT event_id,kind,event_data FROM autoencoder_control.events WHERE kind='candidate_durable' ORDER BY event_id").fetchall()]
        selected = [row for row in events if row["data"].get("run_id") == run_id]
        versions = connection.execute("SELECT count(*) FROM autoencoder_control.versions").fetchone()[0]
        generation = connection.execute("SELECT owner_generation FROM autoencoder_control.meta WHERE singleton=1").fetchone()[0]
    finally:
        connection.close()
    return {"candidate_events": selected, "candidate_event_count": len(selected),
            "version_count": versions, "owner_generation": generation}


def collect_failure_artifacts(helper, directory):
    result = []
    for path in sorted(directory.rglob("*")):
        if path.is_file() and not path.is_symlink() and path.suffix in {".json", ".log"}:
            require(len(result) < 128, "failure artifact inventory bound exceeded")
            result.append(helper.descriptor(path))
    return result


def run(directory, output, helper):
    started = time.perf_counter()
    result = {"schema": "owned-native-daemon-qualification-v1", "passed": False,
        "recorded_at": datetime.now(timezone.utc).isoformat(), "automatic_retry": False,
        "native_cycle_requested": True, "admitted": False, "formalized": False,
        "publication_performed": False, "owner_head_promotion_performed": False,
        "heldout_canary_qualified": False, "speed_claim": False,
        "scope": "one actual owner-leased native six-record cycle and independent full-checkpoint verification",
        "cold_scope": "fresh child processes/private attempt; persisted pretrained base and actual default in-process caches; OS cache uncontrolled",
        "harness": helper.descriptor(__file__), "helper": helper.descriptor(HELPER_PATH),
        "resource_policy": resource_policy(), "timings": {}}
    prepared = None
    try:
        environment = parent_environment(helper, dict(os.environ))
        os.environ.clear(); os.environ.update(environment)
        sys.path.insert(0, str(ROOT))
        # The script is its own dedicated process; install the irreversible
        # filter before importing package ancestors or opening owner artifacts.
        require(sha(helper.SECCOMP_SCRIPT) == helper.SECCOMP_SHA, "network guard helper changed")
        sys.path.insert(0, str(HELPER_PATH.parent))
        from audit_native_uscode_embedding_production import _deny_network
        result["parent_network_guard"] = _deny_network()
        from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import get_global_resource_scheduler
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_resources import DaemonResourceReservation
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_invocation import prepare_daemon_invocation, run_owned_daemon_invocation
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import read_checkpoint_input_metadata
        from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
        result["tree_pin"] = require_workspace_logic_tree()
        scheduler = get_global_resource_scheduler()
        os.environ["IPFS_DATASETS_RESOURCE_SCHEDULER_PATH"] = str(scheduler.state_path)
        result["scheduler"] = {"state_path": str(scheduler.state_path),
            "configuration": scheduler.config.persisted_dict(), "private_configuration_override": False}
        result["environment_before"] = dict(os.environ)
        result["source_manifest_before"] = helper.source_manifest()
        helper.verify({"path": str(helper.PINNED), "sha256": helper.PINNED_SHA, "bytes": helper.PINNED_BYTES})
        for root in STORAGE_ROOTS:
            require(root.is_dir() and root == root.resolve(), "required storage root missing or aliased")
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        policy = resource_policy()
        export_start = time.perf_counter()
        with DaemonResourceReservation(LEDGER, roots=STORAGE_ROOTS, storage_bytes=STORAGE_BYTES,
                memory_mb=MEMORY_MB, cpu_slots=1, timeout_seconds=0) as export_reservation:
            export_reservation.check_usage(directory)
            stage("historical_export_started", resource_reservation_id=export_reservation.reservation_id)
            snapshot, payload = helper.historical_export(directory, result)
            result["snapshot"], result["exported_job"] = snapshot, payload
            result["input_walk_before"] = helper.audit_inputs(snapshot, payload)
            export_reservation.check_usage(directory)
            result["export_reservation"] = export_reservation.release(artifacts_durable=True)
        result["timings"]["historical_export_seconds"] = time.perf_counter() - export_start
        invocation = directory / "invocation"; invocation.mkdir()
        private = result["private_owner"]
        database, artifacts = Path(private["database"]), Path(private["artifact_root"])
        variant, base = result["historical_owner"]["variant_id"], payload["base_version_id"]
        argv = daemon_argv(helper, snapshot)
        result["daemon_argv"] = argv
        with AutoencoderRegistry(database, artifacts) as owner:
            result["private_head_before_execution"] = owner.resolve_head(variant, "qualification")
            prepare_start = time.perf_counter()
            stage("owner_preparation_started")
            try:
                prepared = prepare_daemon_invocation(owner, run_id=RUN_ID, variant_id=variant,
                    base_version_id=base, input_snapshot=snapshot, daemon_argv=argv,
                    output_directory=invocation, resource_policy=policy)
            finally:
                result["timings"]["owner_preparation_seconds"] = time.perf_counter() - prepare_start
            result["prepared"] = prepared
            require(helper.source_manifest() == result["source_manifest_before"], "source changed before execution")
            execute_start = time.perf_counter()
            stage("owner_execution_started", run_id=RUN_ID, timeout_seconds=TIMEOUT_SECONDS,
                  invocation_directory=str(invocation))
            try:
                owned = run_owned_daemon_invocation(owner, prepared, lease_seconds=LEASE_SECONDS,
                                                     timeout_seconds=TIMEOUT_SECONDS)
            finally:
                result["timings"]["owner_execution_seconds"] = time.perf_counter() - execute_start
            result["owned_result"] = owned
            complete = owned["completion"]
            execution = owner.get_run(RUN_ID)
            version = owner.get_version(complete["version_id"])
            candidate = owner.verify_artifact(version["artifact"])
            candidate_ref = {**candidate, "path": str(owner.artifact_path(candidate))}
            result["candidate"] = candidate_ref
            result["candidate_version"] = version
            result["candidate_metadata"] = list(read_checkpoint_input_metadata(candidate_ref["path"]))
            result["execution_run"] = execution
            result["private_head_after_execution"] = owner.resolve_head(variant, "qualification")
            anchor = owner.get_run(private["run_id"])
            result["input_anchor_unleased"] = anchor["status"] == "queued" and anchor["lease"] is None
            result["candidate_parent_is_registered_base"] = version["parent_version_id"] == base
            result["evidence_closure"] = {}
            for name, ref in execution["result"]["evidence"].items():
                verified = owner.verify_artifact(ref)
                result["evidence_closure"][name] = {**verified, "path": str(owner.artifact_path(verified))}
            require(execution["status"] == "completed" and complete["promoted"] is False, "owner completion differs")
        result["database_before_replay"] = inspect_private_database(database, RUN_ID)
        with AutoencoderRegistry(database, artifacts) as owner:
            replay = run_owned_daemon_invocation(owner, prepared, lease_seconds=LEASE_SECONDS, timeout_seconds=TIMEOUT_SECONDS)
            result["restart_replay"] = replay
            result["private_head_after_restart"] = owner.resolve_head(variant, "qualification")
            result["candidate_after_restart"] = owner.get_version(complete["version_id"])
            anchor = owner.get_run(private["run_id"])
            result["input_anchor_unleased_after_restart"] = anchor["status"] == "queued" and anchor["lease"] is None
            owner.verify_artifact(candidate)
        result["database_after_replay"] = inspect_private_database(database, RUN_ID)
        result["completion_replayed_identically"] = replay["historical_retry"] is True and replay["completion"] == complete
        result["candidate_unchanged_after_replay"] = result["candidate_after_restart"] == result["candidate_version"]
        result["one_candidate_event_after_replay"] = result["database_before_replay"]["candidate_event_count"] == result["database_after_replay"]["candidate_event_count"] == 1
        result["candidate_events_unchanged_after_replay"] = result["database_before_replay"]["candidate_events"] == result["database_after_replay"]["candidate_events"]
        result["version_count_unchanged_after_replay"] = result["database_before_replay"]["version_count"] == result["database_after_replay"]["version_count"]
        result["private_head_unchanged"] = private["head_before"] == result["private_head_before_execution"] == result["private_head_after_execution"] == result["private_head_after_restart"]
        request = helper.read(prepared["request"]["path"])
        native = helper.read(result["evidence_closure"]["native_result"]["path"])
        independent = helper.read(result["evidence_closure"]["owner_verification"]["path"])
        cycle = cycle_from_log(helper, native["log_artifact"])
        result["native_result"], result["independent_verification"] = native, independent
        result["cycle"] = cycle
        result["qualification_checks"], result["memory_policy_checks"] = qualification_checks(
            helper, native, independent, request, cycle, result["input_walk_before"])
        result["input_walk_after"] = helper.audit_inputs(snapshot, payload)
        result["timings"].update(daemon_seconds_including_shutdown=native.get("daemon_seconds_including_shutdown"),
            execute_child_seconds=native.get("elapsed_seconds"), verify_child_seconds=independent.get("elapsed_seconds"),
            cycle_phase_seconds=native["summary"].get("latest_cycle_phase_timings"))
        result["timing_scope"] = "Owner execution includes staging, independent verifier and completion; daemon timer includes native shutdown; phases include heartbeat persistence. No cold/warm speed comparison."
        result["snapshot_proof_scope"] = "Successful modal compilation/routing observations can include local tableaux or compile-only routes. bridge_evaluate_provers=false does not disable snapshot routing; no theorem/admission count inferred."
        required = ("input_anchor_unleased", "input_anchor_unleased_after_restart", "candidate_parent_is_registered_base",
            "completion_replayed_identically", "one_candidate_event_after_replay", "candidate_events_unchanged_after_replay",
            "version_count_unchanged_after_replay", "private_head_unchanged", "candidate_unchanged_after_replay")
        require(all(result[name] for name in required) and all(result["qualification_checks"].values()), "owned qualification checks failed")
        result["passed"] = True
        stage("qualification_completed", version_id=complete["version_id"])
    except BaseException as exc:
        result["error"] = {"type": f"{type(exc).__module__}.{type(exc).__qualname__}", "message": str(exc)[:4096]}
        result["passed"] = False
        stage("qualification_failed", error_type=type(exc).__name__, error=str(exc)[:512])
    finally:
        try:
            result["environment_after"] = dict(os.environ)
            result["environment_unchanged"] = result.get("environment_before") == result["environment_after"]
            result["source_manifest_after"] = helper.source_manifest()
            result["source_unchanged"] = result.get("source_manifest_before") == result["source_manifest_after"]
            result["protected_checkpoint_unchanged"] = sha(helper.PINNED) == helper.PINNED_SHA
            result["historical_inputs_unchanged"] = False
            for ref in result.get("historical_guards", []): helper.verify(ref)
            result["historical_inputs_unchanged"] = bool(result.get("historical_guards"))
            result["helper_unchanged"] = sha(HELPER_PATH) == HELPER_SHA
            result["harness_unchanged"] = sha(__file__) == result["harness"]["sha256"]
            result["failure_or_attempt_artifacts"] = collect_failure_artifacts(helper, directory)
            result["passed"] = bool(result["passed"] and all(result[name] for name in
                ("environment_unchanged", "source_unchanged", "protected_checkpoint_unchanged",
                 "historical_inputs_unchanged", "helper_unchanged", "harness_unchanged")))
        except BaseException as exc:
            result["passed"] = False
            result["final_guard_error"] = {"type": type(exc).__name__, "message": str(exc)[:4096]}
        result["timings"]["total_seconds"] = time.perf_counter() - started
        raw = (json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
        require(len(raw) <= helper.MAX_JSON_BYTES, "qualification receipt exceeds bounded output")
        with output.open("xb") as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        parent_fd = os.open(output.parent, os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        stage("receipt_written", path=str(output), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), passed=result["passed"])
    return 0 if result["passed"] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--native-cycle", action="store_true", required=True,
                        help="Explicitly authorize exactly one full native owner invocation")
    args = parser.parse_args(argv)
    helper = load_helper()
    directory, output = args.directory.absolute(), args.output.absolute()
    if directory != directory.resolve() or output != output.resolve() or directory.exists() or output.exists():
        parser.error("fresh unaliased directory and receipt paths are mandatory; no retries")
    if not directory.is_relative_to(STORAGE_ROOTS[0]) or not output.is_relative_to(STORAGE_ROOTS[2]):
        parser.error("directory must be under canonical test-logs and output under canonical evidence")
    output.parent.mkdir(parents=True, exist_ok=True)
    directory.mkdir(parents=True)
    return run(directory, output, helper)


if __name__ == "__main__":
    raise SystemExit(main())
