#!/usr/bin/env python3
"""Qualify owner-integrated shadow evidence with an explicit synthetic execute.

Preparation and verification are real offline worker subprocesses. Only the
execute boundary is replaced by a separate fixture child: it changes one scalar
and constructs declared synthetic protocol evidence, without calling the daemon,
optimizer, bridge evaluator or asynchronous snapshot evaluator. Full checkpoints
remain authoritative. This is not native training or learning qualification.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
HELPER = Path(__file__).with_name("qualify_owned_daemon_invocation.py")
HELPER_SHA = "c54b99391e7dfdf9515ebd9ced4fa917f6a49efc1f86dbe254a632ef30c0e350"
RUN_ID = "owner-synthetic-shadow-qualification"
MUTATION_KEY = "synthetic.owned_shadow_qualification"
MUTATION_VALUE = 0.125
OWNER_TIMEOUT_SECONDS = 180
MAX_RECEIPT_BYTES = 64 * 1024 * 1024
SYNTHETIC = {
    "schema": "owned-shadow-synthetic-execute-v1", "synthetic_fixture": True,
    "daemon_main_calls": 0, "optimizer_calls": 0, "bridge_evaluation_calls": 0,
    "async_snapshot_evaluator_calls": 0, "accepted_projection_epochs": 0,
    "mutation": {"component": "legal_ir_view_logits", "key": MUTATION_KEY,
                 "value": MUTATION_VALUE, "kind": "direct_fixture_assignment"},
    "protocol_lifecycle_metadata": "constructed fixture values, not observed daemon or snapshot work",
}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def helpers():
    require(sha(HELPER) == HELPER_SHA, "pinned owner qualification helper changed")
    spec = importlib.util.spec_from_file_location("_owned_shadow_pinned_helper", HELPER)
    owner_helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(owner_helper)
    return owner_helper, owner_helper.load_helper()


def progress(label, **values):
    print(json.dumps({"stage": label, **values}, sort_keys=True), flush=True)


def write_new(path, value):
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    require(len(raw) <= MAX_RECEIPT_BYTES, "qualification receipt too large")
    with Path(path).open("xb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    fsync_directory(Path(path).parent)


def fsync_directory(path):
    fd = os.open(path, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def deny_network(helper):
    require(sha(helper.SECCOMP_SCRIPT) == helper.SECCOMP_SHA, "network helper changed")
    sys.path.insert(0, str(HELPER.parent))
    from audit_native_uscode_embedding_production import _deny_network
    return _deny_network()


def synthetic_snapshot_fields(versions, metadata):
    """Required fixture lifecycle fields, explicitly without an evaluation."""
    return {"snapshot_shutdown": {"drained": True}, "snapshot_evaluator": {"closed": True},
        "latest_published_snapshot": {"sequence": 1, "versions": versions,
            "metadata": {**metadata, "synthetic_fixture": True}},
        "latest_promoted_snapshot_complete": False}


def fixture_execute(launch_path, output):
    """Construct synthetic evidence under real current bindings and source guards."""
    _, helper = helpers()
    started = time.perf_counter()
    result = {"schema": "autoencoder-daemon-invocation-result-v1", "mode": "execute", "success": False,
        "synthetic_fixture": True, "synthetic_provenance": SYNTHETIC,
        "admitted": False, "promoted": False, "publication_performed": False,
        "lease_authority_verified": False, "runtime_computation_replayed": False,
        "entrypoint": "qualification.fixture_execute; daemon runner.main was not called",
        "callable_replacements": [], "native_exit_code_is_fixture_return_code": True,
        "daemon_seconds_including_shutdown": None}
    inputs = observer = None
    try:
        result["network_guard"] = deny_network(helper)
        sys.path.insert(0, str(ROOT))
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_invocation_contracts as c
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_invocation_worker as worker
        # Match the real execute worker: compare the sealed environment before
        # effective_configuration imports the runner and its native libraries.
        launch_ref = c.describe(launch_path, c.MAX_REQUEST_BYTES)
        launch, request, arguments, binding = worker._load_launch(launch_ref)
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_observation import observation_session
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import serialize_checkpoint
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.snapshot_evaluator import canonical_holdout_version
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner import _compiler_commit
        require(request.get("sparse_shadow") is True, "shadow must be required by the current request")
        result.update(request=launch["request"], launch=launch_ref, binding=binding, guards={"source_before": True})
        inputs = worker._inputs(request["input_snapshot"], arguments)
        inputs.verify_boundary("synthetic_execute_before")
        summary_path, log_path, state_path = worker._evidence_paths(request)
        require(not summary_path.exists() and not log_path.exists(), "synthetic attempt already has evidence")
        base_ref = worker._copy_base(request["base_artifact"], state_path)
        state = c.load_full_checkpoint(base_ref).state
        require(state.state_identity_record().to_dict() == request["base_identity"], "synthetic base differs")
        result["memory_before"] = helper.memory_observation()
        summary = inputs.summary()
        corpus = summary["corpus_verification"]
        production = corpus["embedding_production_verification"]
        provenance = {"descriptor": request["input_snapshot"], "job_spec_sha256": summary["job_spec_sha256"],
            "variant_manifest_sha256": summary["variant_manifest_sha256"],
            "dataset_snapshot_id": corpus["dataset_snapshot_id"], "split_snapshot_id": corpus["split_snapshot_id"],
            "index_sha256": corpus["corpus_index_verification"]["index_sha256"],
            "embedding_production_artifact": {"sha256": production["sha256"], "bytes": production["bytes"]},
            "binding": "owner_snapshot_transitive_input_identity", "checkpoint_authority_verified": False}
        train_indices, validation_indices = list(inputs.indices_for("train")), list(inputs.indices_for("validation"))
        require(len(train_indices) == len(validation_indices) == 3, "fixed three-plus-three inputs required")
        samples = {role: [inputs.build_sample(index) for index in indices] for role, indices in
                   (("train", train_indices), ("validation", validation_indices))}
        for role, indices in (("train", train_indices), ("validation", validation_indices)):
            inputs.verify_selected(indices, samples[role], role=role)
        with observation_session(binding=binding) as observer:
            observer.record_state("registered_base", state, cycle=0, metric_lineage=c.METRIC_LINEAGE,
                                  metadata={"checkpoint_loaded": True, "synthetic_fixture": True})
            observer.record_state("startup_complete", state, cycle=0, metric_lineage=c.METRIC_LINEAGE,
                                  metadata={"synthetic_fixture": True})
            observer.record_selection(cycle=1, train_indices=train_indices, train_samples=samples["train"],
                validation_indices=validation_indices, validation_samples=samples["validation"], corpus_inputs=inputs)
            require(MUTATION_KEY not in state.legal_ir_view_logits, "synthetic key already exists")
            state.legal_ir_view_logits[MUTATION_KEY] = MUTATION_VALUE
            metadata = {"compiler_version": _compiler_commit(Path.cwd()), "validation_mode": "rotating_holdout",
                "holdout_version": canonical_holdout_version([s.sample_id for s in samples["validation"]],
                    validation_mode="rotating_holdout"), "synthetic_fixture": True}
            observer.record_state("completed_cycle", state, cycle=1, metric_lineage=c.METRIC_LINEAGE, metadata=metadata)
            checkpoint_metadata = {**observer.checkpoint_metadata(), "run_id": request["run_id"], "cycle": 1,
                "reason": "clean_shutdown", "synthetic_fixture": True, "synthetic_provenance": SYNTHETIC,
                "corpus_input_identity": {k: request["input_snapshot"][k] for k in ("sha256", "bytes")},
                "corpus_input_provenance": provenance}
            raw = serialize_checkpoint(state, float_precision="float64", metric_lineage=c.METRIC_LINEAGE,
                                       metadata=checkpoint_metadata)
            staged = state_path.with_name("synthetic-final.tmp")
            with staged.open("xb") as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            c.verify(base_ref, c.MAX_CHECKPOINT_BYTES)
            os.replace(staged, state_path)
            fsync_directory(state_path.parent)
            final = c.describe(state_path, c.MAX_CHECKPOINT_BYTES)
            persisted = {"durable": True, "checkpoint_enqueued": True, "checksum": final["sha256"],
                "written_bytes": final["bytes"], "checkpoint_bytes": final["bytes"],
                "checkpoint_identity": state.state_identity(), "checkpoint_revision": state.state_revision,
                "synthetic_fixture": True}
            summary = {"cycles": 1, "synthetic_fixture": True, "synthetic_provenance": SYNTHETIC,
                "final_state_persistence": persisted, "async_artifact_writer_shutdown": {"drained": True},
                "async_artifact_writer": {"failed_count": 0, "last_error": ""},
                "corpus_input_descriptor": request["input_snapshot"], "corpus_input_provenance": provenance,
                "corpus_input_identity": checkpoint_metadata["corpus_input_identity"],
                "corpus_inputs": {"closed": True, "input_integrity_verified": True, "poisoned": False, "failure": None}}
            if arguments["snapshot_evaluation_enabled"]:
                versions = {"state_version": state.state_identity(metric_lineage=c.METRIC_LINEAGE),
                    "schema_version": c.METRIC_LINEAGE, "compiler_version": metadata["compiler_version"],
                    "holdout_version": metadata["holdout_version"]}
                summary.update(synthetic_snapshot_fields(versions, observer.checkpoint_metadata()))
            cycle = {"event": "cycle", "cycle": 1, "synthetic_fixture": True, "synthetic_provenance": SYNTHETIC,
                "train_indices": train_indices, "validation_indices": validation_indices,
                "validation_mode": "rotating_holdout", "feature_projection_report": {
                    "accepted_epochs": 0, "sample_memory_used": False, "synthetic_fixture": True,
                    "optimizer_called": False}}
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            result["summary_artifact"] = c.write_new(summary_path, summary)
            result["log_artifact"] = c.write_new(log_path, cycle)
            observer.record_state("final_shutdown", state, cycle=1, metric_lineage=c.METRIC_LINEAGE,
                metadata={**metadata, "final_state_persistence": persisted})
            observer.record_return(0)
        result.update(summary=summary, final_checkpoint=final, observation=observer.to_dict(), native_exit_code=0,
            accepted_projection_epochs=0, state_identity=state.state_identity_record().to_dict())
        result["runtime_guards"] = worker._runtime_guards(request, summary, final)
        result["sample_memory_policy"] = worker._sample_memory_policy(result["observation"], request, cycle)
        require(result["state_identity"] != request["base_identity"], "synthetic state did not change")
        inputs.verify_boundary("synthetic_execute_after")
        require(c.producer_identity(arguments) == request["producer_identity"], "fixture source changed")
        for ref in (launch_ref, launch["request"], request["base_artifact"]):
            c.verify(ref, c.MAX_CHECKPOINT_BYTES)
        result["guards"].update(source_after=True, inputs_after=True)
        result["memory_after"] = helper.memory_observation()
        result["success"] = True
    except BaseException as exc:
        result["error"] = {"type": f"{type(exc).__module__}.{type(exc).__qualname__}", "message": str(exc)[:4096]}
    finally:
        if observer is not None:
            result["observation"] = observer.to_dict()
        if inputs is not None:
            inputs.close(); result["input_verification"] = inputs.summary()
        result["elapsed_seconds"] = time.perf_counter() - started
        write_new(output, result)
    return 0 if result["success"] else 1


def fixture_subprocess(query, output, *, cwd, environment, reservation, timeout_seconds, heartbeat):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_resources import _process, _group_usage
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_invocation import _terminate
    process = identity = primary = None
    start = time.monotonic()
    with output.with_suffix(".log").open("xb") as log:
        try:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "execute", str(query), str(output)],
                cwd=cwd, env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            observed = _process(process.pid)
            if observed is not None:
                identity = {key: observed[key] for key in ("pid", "birth")}
            reservation.check_usage(cwd, child_pid=process.pid)
            progress("synthetic_child_started", pid=process.pid, log=str(output.with_suffix(".log")))
            next_usage = time.monotonic() + 5
            while process.poll() is None:
                heartbeat()
                require(time.monotonic() - start < min(timeout_seconds, OWNER_TIMEOUT_SECONDS), "fixture child timed out")
                if time.monotonic() >= next_usage:
                    reservation.check_usage(cwd); next_usage = time.monotonic() + 5
                time.sleep(0.2)
            heartbeat()
            require(process.returncode == 0, f"synthetic child exited {process.returncode}; no retry")
            require(identity is not None and not _group_usage(identity)["live_processes"], "fixture child left live descendants")
            reservation.check_usage(cwd)
            _, helper = helpers()
            result = helper.read(output)
            require(result.get("success") is True and result.get("synthetic_provenance") == SYNTHETIC,
                    "fixture child result differs")
            return result
        except BaseException as exc:
            primary = exc
            raise
        finally:
            try:
                if process is not None:
                    _terminate(process, identity)
                log.flush(); os.fsync(log.fileno())
            except BaseException as exc:
                if primary is None:
                    raise
                primary.add_note(f"fixture cleanup also failed: {type(exc).__name__}")


def hybrid_dispatch(original, calls):
    def dispatch(mode, query, output, **kwargs):
        row = {"mode": mode, "kind": "synthetic_fixture" if mode == "execute" else "actual_worker"}
        calls.append(row)
        start = time.perf_counter()
        try:
            return fixture_subprocess(query, output, **kwargs) if mode == "execute" else original(mode, query, output, **kwargs)
        finally:
            row["wall_seconds"] = time.perf_counter() - start
    return dispatch


def integration_checks(native, independent, completion, evidence, stored_result):
    shadow = independent.get("sparse_shadow", {})
    capture = shadow.get("capture_report", {})
    return {
        "synthetic_execute_explicit": native.get("synthetic_provenance") == SYNTHETIC,
        "zero_accepted_optimizer_epochs": native.get("accepted_projection_epochs") == independent.get("accepted_projection_epochs") == 0,
        "no_evaluation_passes_claimed": native.get("sample_memory_policy", {}).get("evaluation_passes") == [],
        "no_matching_evaluation_claimed": independent.get("evaluation_matches_final") is False
            and stored_result.get("evaluation_matches_final") is False,
        "no_synthetic_promoted_evaluation": not native.get("summary", {}).get("latest_promoted_snapshot_evaluation")
            and native.get("summary", {}).get("latest_promoted_snapshot_complete") is False,
        "real_verifier_success": independent.get("success") is True,
        "shadow_passed": shadow.get("passed") is True,
        "full_checkpoint_authoritative": shadow.get("full_checkpoint_authoritative") is True,
        "exactly_one_changed_component": capture.get("changed_components") == ["legal_ir_view_logits"],
        "exactly_one_inserted_scalar": capture.get("counts") == {"changed_component_count": 1,
            "touched_row_count": 1, "touched_component_count": 0, "inserted_rows": 1,
            "deleted_rows": 0, "revision_witness_count": 0},
        "all_38_fields_compared": all(capture.get(key, {}).get("component_count") == 38
            and len(capture.get(key, {}).get("component_fields", [])) == 38
            for key in ("base_snapshot", "result_snapshot"))
            and capture.get("base_snapshot", {}).get("component_fields") == capture.get("result_snapshot", {}).get("component_fields"),
        "exact_synthetic_revision_transition": capture.get("base_snapshot", {}).get("state_revision") == 0
            and capture.get("result_snapshot", {}).get("state_revision") == 1
            and capture.get("revision_only") is False,
        "shadow_full_comparisons": bool(shadow.get("checks")) and all(v is True for v in shadow["checks"].values()),
        "owner_completed_unpromoted": completion.get("status") == "completed" and completion.get("promoted") is False,
        "seven_evidence_artifacts": set(evidence) == {"launch", "native_result", "owner_verification",
            "summary_artifact", "log_artifact", "sparse_shadow_patch", "sparse_shadow_receipt"},
    }


def shadow_closure_checks(helper, shadow, evidence, candidate):
    """Audit the persisted small evidence without loading or replaying state."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_patch_codec import decode_patch
    for name in ("sparse_shadow_patch", "sparse_shadow_receipt"):
        helper.verify(evidence[name])
    persisted = helper.read(evidence["sparse_shadow_receipt"]["path"])
    segment = decode_patch(Path(evidence["sparse_shadow_patch"]["path"]).read_bytes())
    rows = segment.patch.rows
    return {
        "staged_shadow_refs_exact": all(all(evidence[name][key] == shadow[field][key] for key in ("sha256", "bytes"))
            for name, field in (("sparse_shadow_patch", "patch_ref"), ("sparse_shadow_receipt", "receipt_ref"))),
        "persisted_shadow_receipt_exact": helper.canonical(persisted) == helper.canonical(
            {key: value for key, value in shadow.items() if key != "receipt_ref"}),
        "compact_candidate_reencoding_exact": shadow["regenerated_compact_checkpoint"] ==
            {key: candidate[key] for key in ("sha256", "bytes")},
        "exact_synthetic_patch_scalar": len(rows) == 1 and not segment.patch.components
            and rows[0].component == "legal_ir_view_logits" and rows[0].key == MUTATION_KEY
            and rows[0].before_exists is False and rows[0].after_exists is True
            and type(rows[0].after_value) is float
            and struct.pack(">d", rows[0].after_value) == struct.pack(">d", MUTATION_VALUE),
    }


def publish_receipt(directory, output, result, reservation):
    """Retain the export disk allowance through fsync, with its CPU lease freed."""
    require(reservation is not None, "no admitted reservation covers receipt publication")
    reservation.check_usage(directory)
    result["receipt_publication"] = {"status": "outstanding_at_publication",
        "reservation": reservation.to_dict(), "max_receipt_bytes": MAX_RECEIPT_BYTES,
        "policy": "export disk claim retained; scheduler lease released at export context exit",
        "release_after_file_and_directory_fsync": True,
        "overall_success_requires_terminal_exit_zero_and_ledger_release": True,
        "release_authority": "durable shared resource ledger; receipt precedes release"}
    write_new(output, result)
    released = reservation.release(artifacts_durable=True)
    require(released["status"] == "released", "receipt reservation did not release")
    return released


def run(directory, output):
    owner_helper, helper = helpers()
    started = time.perf_counter()
    result = {"schema": "owned-daemon-shadow-hybrid-qualification-v1", "passed": False,
        "recorded_at": datetime.now(timezone.utc).isoformat(), "synthetic_fixture": True,
        "synthetic_provenance": SYNTHETIC, "native_training_qualified": False,
        "training_performed": False, "bridge_evaluation_performed": False,
        "fallback_evaluation_performed": False, "proof_execution_performed": False,
        "outer_receipt_max_bytes": MAX_RECEIPT_BYTES,
        "admitted": False, "promoted": False, "publication_performed": False,
        "automatic_retry": False, "speed_claim": False,
        "scope": "Actual describe/verify subprocesses and owner completion around an explicitly synthetic execute child",
        "harness": helper.descriptor(__file__), "helper": helper.descriptor(HELPER),
        "resource_policy": owner_helper.resource_policy(), "child_calls": [], "timings": {}}
    original = owner = reserved = None
    try:
        environment = owner_helper.parent_environment(helper, dict(os.environ))
        os.environ.clear(); os.environ.update(environment)
        result["parent_network_guard"] = deny_network(helper)
        sys.path.insert(0, str(ROOT))
        from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_invocation as owner
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_resources import DaemonResourceReservation
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import get_global_resource_scheduler
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import read_checkpoint_input_metadata
        from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
        result["tree_pin"] = require_workspace_logic_tree()
        scheduler = get_global_resource_scheduler()
        os.environ["IPFS_DATASETS_RESOURCE_SCHEDULER_PATH"] = str(scheduler.state_path)
        result["scheduler"] = {"state_path": str(scheduler.state_path), "configuration": scheduler.config.persisted_dict(),
            "private_configuration_override": False}
        result["environment_before"] = dict(os.environ)
        result["source_manifest_before"] = helper.source_manifest()
        original = owner._child
        owner._child = hybrid_dispatch(original, result["child_calls"])
        policy = owner_helper.resource_policy()
        phase = time.perf_counter()
        with DaemonResourceReservation(policy["ledger_path"], roots=policy["roots"], storage_bytes=policy["storage_bytes"],
                memory_mb=policy["memory_mb"], cpu_slots=1, timeout_seconds=0) as reserved:
            reserved.account_external_bytes("qualification-receipt", MAX_RECEIPT_BYTES)
            result["outer_receipt_bound_charged"] = True
            reserved.check_usage(directory)
            snapshot, payload = helper.historical_export(directory, result)
            result["snapshot"], result["input_walk"] = snapshot, helper.audit_inputs(snapshot, payload)
            reserved.check_usage(directory)
        result["export_reservation"] = reserved.to_dict()
        result["timings"]["historical_export_seconds"] = time.perf_counter() - phase
        private = result["private_owner"]
        database, artifacts = Path(private["database"]), Path(private["artifact_root"])
        variant, base = result["historical_owner"]["variant_id"], payload["base_version_id"]
        invocation = directory / "invocation"; invocation.mkdir()
        argv = owner_helper.daemon_argv(helper, snapshot)
        argv[argv.index("--run-id") + 1] = RUN_ID
        result["sealed_daemon_argv_not_executed"] = argv
        with AutoencoderRegistry(database, artifacts) as registry:
            result["head_before"] = registry.resolve_head(variant, "qualification")
            phase = time.perf_counter(); progress("real_owner_preparation_started")
            try:
                prepared = owner.prepare_daemon_invocation(registry, run_id=RUN_ID, variant_id=variant,
                    base_version_id=base, input_snapshot=snapshot, daemon_argv=argv, output_directory=invocation,
                    resource_policy=policy, sparse_shadow=True)
            finally:
                result["timings"]["preparation_seconds"] = time.perf_counter() - phase
            result["prepared"] = prepared
            require(helper.source_manifest() == result["source_manifest_before"], "source changed before execution")
            phase = time.perf_counter(); progress("hybrid_owner_execution_started", timeout_seconds=OWNER_TIMEOUT_SECONDS)
            try:
                owned = owner.run_owned_daemon_invocation(registry, prepared, lease_seconds=300,
                                                         timeout_seconds=OWNER_TIMEOUT_SECONDS)
            finally:
                result["timings"]["owner_execution_seconds"] = time.perf_counter() - phase
            result["owned_result"] = owned
            completion = owned["completion"]
            execution = registry.get_run(RUN_ID)
            candidate = registry.get_version(completion["version_id"])
            ref = registry.verify_artifact(candidate["artifact"])
            result["candidate"] = {**ref, "path": str(registry.artifact_path(ref))}
            result["candidate_metadata"] = list(read_checkpoint_input_metadata(result["candidate"]["path"]))
            result["candidate_version"], result["execution_run"] = candidate, execution
            result["evidence"] = {}
            for name, item in execution["result"]["evidence"].items():
                ref = registry.verify_artifact(item)
                result["evidence"][name] = {**ref, "path": str(registry.artifact_path(ref))}
            result["head_after"] = registry.resolve_head(variant, "qualification")
            anchor = registry.get_run(private["run_id"])
            result["input_anchor_unleased"] = anchor["status"] == "queued" and anchor["lease"] is None
        owner._child = original
        result["execute_boundary_restored"] = owner._child is original
        before = owner_helper.inspect_private_database(database, RUN_ID)
        with AutoencoderRegistry(database, artifacts) as registry:
            result["restart_replay"] = owner.run_owned_daemon_invocation(registry, prepared,
                lease_seconds=300, timeout_seconds=OWNER_TIMEOUT_SECONDS)
            result["candidate_after_restart"] = registry.get_version(completion["version_id"])
            result["head_after_restart"] = registry.resolve_head(variant, "qualification")
            anchor = registry.get_run(private["run_id"])
            result["input_anchor_unleased_after_restart"] = anchor["status"] == "queued" and anchor["lease"] is None
        after = owner_helper.inspect_private_database(database, RUN_ID)
        result["database_before_replay"], result["database_after_replay"] = before, after
        native = helper.read(result["evidence"]["native_result"]["path"])
        independent = helper.read(result["evidence"]["owner_verification"]["path"])
        result["synthetic_execute_result"], result["actual_verification_result"] = native, independent
        result["checks"] = integration_checks(native, independent, completion, result["evidence"], execution["result"])
        result["checks"].update(shadow_closure_checks(helper, independent["sparse_shadow"], result["evidence"], result["candidate"]))
        result["checks"].update(
            child_dispatch_exact=[r["mode"] for r in result["child_calls"]] == ["describe", "execute", "verify"],
            immutable_full_candidate_replayed=candidate == result["candidate_after_restart"],
            candidate_parent_is_registered_base=candidate["parent_version_id"] == base,
            head_unchanged=result["head_before"] == result["head_after"] == result["head_after_restart"] == private["head_before"],
            replay_exact=result["restart_replay"]["historical_retry"] is True and result["restart_replay"]["completion"] == completion,
            exactly_one_candidate_event=before["candidate_event_count"] == after["candidate_event_count"] == 1,
            candidate_events_unchanged=before["candidate_events"] == after["candidate_events"],
            version_count_unchanged=before["version_count"] == after["version_count"],
            synthetic_checkpoint_labeled=bool(result["candidate_metadata"]) and all(
                m.get("synthetic_provenance") == SYNTHETIC for m in result["candidate_metadata"]),
            outer_receipt_bound_charged=result.get("outer_receipt_bound_charged") is True,
            input_anchor_unleased=result["input_anchor_unleased"] and result["input_anchor_unleased_after_restart"])
        require(all(result["checks"].values()), "hybrid integration checks failed")
        result["passed"] = True
    except BaseException as exc:
        result["error"] = {"type": f"{type(exc).__module__}.{type(exc).__qualname__}", "message": str(exc)[:4096],
            "notes": getattr(exc, "__notes__", [])}
    finally:
        if original is not None:
            owner._child = original
            result["execute_boundary_restored"] = owner._child is original
        try:
            result["environment_unchanged"] = result.get("environment_before") == dict(os.environ)
            result["source_manifest_after"] = helper.source_manifest()
            result["source_unchanged"] = result.get("source_manifest_before") == result["source_manifest_after"]
            result["protected_unchanged"] = sha(helper.PINNED) == helper.PINNED_SHA
            for ref in result.get("historical_guards", []):
                helper.verify(ref)
            result["historical_unchanged"] = bool(result.get("historical_guards"))
            result["helper_unchanged"] = sha(HELPER) == HELPER_SHA and sha(owner_helper.HELPER_PATH) == owner_helper.HELPER_SHA
            result["harness_unchanged"] = sha(__file__) == result["harness"]["sha256"]
            result["artifact_inventory"] = owner_helper.collect_failure_artifacts(helper, directory)
            result["passed"] = result["passed"] and all(result[k] for k in ("environment_unchanged", "source_unchanged",
                "protected_unchanged", "historical_unchanged", "helper_unchanged", "harness_unchanged", "execute_boundary_restored"))
        except BaseException as exc:
            result["passed"] = False
            result["guard_error"] = {"type": type(exc).__name__, "message": str(exc)[:4096]}
        result["timings"]["total_seconds_including_guards"] = time.perf_counter() - started
        released = publish_receipt(directory, output, result, reserved)
        progress("receipt_written_and_reservation_released", path=str(output), passed=result["passed"], sha256=sha(output),
            publication_reservation_id=released["reservation_id"], publication_reservation_status=released["status"])
    return 0 if result["passed"] else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) == 3 and argv[0] == "execute":
        return fixture_execute(Path(argv[1]), Path(argv[2]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--synthetic-owner-integration", action="store_true", required=True)
    args = parser.parse_args(argv)
    owner_helper, _ = helpers()
    directory, output = args.directory.absolute(), args.output.absolute()
    if directory.exists() or output.exists() or directory != directory.resolve() or output != output.resolve():
        parser.error("fresh unaliased directory/output required; no retries")
    if not directory.is_relative_to(owner_helper.STORAGE_ROOTS[0]) or not output.is_relative_to(owner_helper.STORAGE_ROOTS[2]):
        parser.error("fixed campaign roots required")
    directory.mkdir(parents=True); output.parent.mkdir(parents=True, exist_ok=True)
    return run(directory, output)


if __name__ == "__main__":
    raise SystemExit(main())
