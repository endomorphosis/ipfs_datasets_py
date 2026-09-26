"""Synthetic worker boundaries and real checkpoint bytes; no native training."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_invocation_contracts as c
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_invocation_worker as worker
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_observation import current_observer
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import ModalAutoencoderTrainingState
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import serialize_checkpoint
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.snapshot_evaluator import canonical_holdout_version


@pytest.fixture
def invocation(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_modal_daemon_runner as runner
    output = tmp_path / "owner-output"
    attempt = output / "attempt-1"
    attempt.mkdir(parents=True)
    monkeypatch.chdir(attempt)
    base = ModalAutoencoderTrainingState(feature_embedding_weights={"synthetic": [0.25, -0.0]})
    base_path = tmp_path / "base.bin"
    base_path.write_bytes(serialize_checkpoint(base))
    snapshot = c.write_new(tmp_path / "input.json", {"synthetic_inputs": True})
    arguments = {"run_id": "synthetic-owned", "train_count": 1, "validation_count": 1,
                 "snapshot_evaluation_enabled": False, "autoencoder_corpus_input": snapshot["path"],
                 "autoencoder_corpus_input_sha256": snapshot["sha256"],
                 "autoencoder_corpus_input_bytes": snapshot["bytes"]}
    environment = dict(os.environ)
    # Pytest itself changes this diagnostic between fixture setup and test call.
    environment["PYTEST_CURRENT_TEST"] = environment["PYTEST_CURRENT_TEST"].replace(" (setup)", " (call)")
    request = {"schema": c.REQUEST_SCHEMA, "run_id": arguments["run_id"], "variant_id": "synthetic-variant",
               "base_version_id": "synthetic-base", "base_artifact": c.describe(base_path),
               "base_identity": base.state_identity_record().to_dict(), "input_snapshot": snapshot,
               "variant_manifest_sha256": "a" * 64, "daemon_argv": ["--synthetic-test-only"],
               "effective_arguments": arguments, "environment": environment,
               "producer_identity": {"synthetic_fixture": True}, "output_directory": str(output),
               "resource_policy": {"synthetic_fixture": True}}
    request_ref = c.write_new(tmp_path / "request.json", request)
    launch = {"schema": c.LAUNCH_SCHEMA, "request": request_ref, "lease": {"run_id": request["run_id"]},
              "attempt_directory": str(attempt), "daemon_argv": request["daemon_argv"],
              "environment": request["environment"], "base_artifact": request["base_artifact"],
              "resource_reservation_id": "synthetic-reservation"}
    launch_ref = c.write_new(attempt / "launch.json", launch)
    monkeypatch.setattr(runner, "_compiler_commit", lambda root: "synthetic-compiler")
    monkeypatch.setattr(c, "effective_configuration", lambda argv: copy.deepcopy(arguments))
    monkeypatch.setattr(c, "producer_identity", lambda args: {"synthetic_fixture": True})
    sessions = []

    class Inputs:
        def __init__(self):
            self.closed = False
            self.boundaries = []
            sessions.append(self)

        def indices_for(self, role):
            return (0,) if role == "train" else (1,)

        def build_sample(self, index):
            return SimpleNamespace(sample_id=f"synthetic-sample-{index}")

        def record_id(self, index):
            return f"synthetic-record-{index}"

        def verify_selected(self, indices, samples, *, role):
            assert indices == list(self.indices_for(role))
            assert [sample.sample_id for sample in samples] == [f"synthetic-sample-{i}" for i in indices]

        def verify_boundary(self, phase):
            assert not self.closed
            self.boundaries.append(phase)

        def close(self):
            self.closed = True

        def summary(self):
            value = {"variant_manifest_sha256": request["variant_manifest_sha256"], "closed": self.closed,
                    "job_spec_sha256": "b" * 64, "corpus_verification": {
                        "dataset_snapshot_id": "dataset:synthetic", "split_snapshot_id": "split:synthetic",
                        "corpus_index_verification": {"index_sha256": "d" * 64},
                        "embedding_production_verification": {"sha256": "e" * 64, "bytes": 123}}}
            if hasattr(case, "arrow_input_summary"):
                value.update(copy.deepcopy(case.arrow_input_summary))
                value["corpus_verification"].update(
                    arrow_embedding_inputs_verified=True,
                    arrow_embedding_inputs_verification=copy.deepcopy(case.arrow_verification))
            return value

    monkeypatch.setattr(worker, "_inputs", lambda ref, args: Inputs())
    case = SimpleNamespace(request=request, launch=launch, launch_ref=launch_ref, request_ref=request_ref,
                           arguments=arguments, base=base, sessions=sessions, attempt=attempt,
                           tmp=tmp_path, main_calls=0)

    def synthetic_main(argv):
        # Fixture computations only; production never substitutes runner.main.
        case.main_calls += 1
        assert argv == request["daemon_argv"]
        observer = current_observer()
        summary_path, log_path, state_path = worker._evidence_paths(request)
        state = c.load_full_checkpoint(c.describe(state_path)).state
        weights = None
        if request["schema"] == c.WEIGHT_REQUEST_SCHEMA:
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_weight_session import current_weight_session
            weights = current_weight_session()
            case.weight_session = weights
            state = weights.attach(state)
        observer.record_state("registered_base", state, cycle=0, metric_lineage=c.METRIC_LINEAGE,
                              metadata={"checkpoint_loaded": True})
        observer.record_state("startup_complete", state, cycle=0, metric_lineage=c.METRIC_LINEAGE)
        inputs = Inputs()
        train, validation = [inputs.build_sample(0)], [inputs.build_sample(1)]
        observer.record_selection(cycle=1, train_indices=[0], train_samples=train,
            validation_indices=[1], validation_samples=validation, corpus_inputs=inputs)
        state.legal_ir_view_logits["synthetic-update"] = 2.0
        if getattr(case, "extra_mutation", None) is not None:
            case.extra_mutation(state)  # Explicit synthetic full-state fixture.
        if getattr(case, "detach_weights", False):
            revision = state.state_revision
            state = state.copy()  # Explicit fixture detachment, not a native TODO acceptance claim.
            state._state_identity_tracker.restore_revision(revision)
        if weights is not None:
            weights.verify_boundary("synthetic_before_persistence", state)
        metadata = {"compiler_version": "synthetic-compiler", "validation_mode": "rotating_holdout",
                    "holdout_version": canonical_holdout_version([validation[0].sample_id], validation_mode="rotating_holdout")}
        observer.record_state("completed_cycle", state, cycle=1, metric_lineage=c.METRIC_LINEAGE, metadata=metadata)
        checkpoint_metadata = {**observer.checkpoint_metadata(), "run_id": request["run_id"], "cycle": 1,
                               "reason": "clean_shutdown",
                               "corpus_input_identity": {k: snapshot[k] for k in ("sha256", "bytes")}}
        provenance = {"descriptor": snapshot, "job_spec_sha256": "b" * 64,
                      "variant_manifest_sha256": "a" * 64,
                      "dataset_snapshot_id": "dataset:synthetic", "split_snapshot_id": "split:synthetic",
                      "index_sha256": "d" * 64, "embedding_production_artifact": {"sha256": "e" * 64, "bytes": 123},
                      "binding": "owner_snapshot_transitive_input_identity", "checkpoint_authority_verified": False}
        provenance.update(copy.deepcopy(getattr(case, "extra_input_provenance", {})))
        checkpoint_metadata["corpus_input_provenance"] = provenance
        if weights is not None:
            checkpoint_metadata["arrow_feature_weights_provenance"] = weights.provenance()
        state_path.write_bytes(serialize_checkpoint(state, metadata=checkpoint_metadata))
        final = c.describe(state_path)
        persisted = {"durable": True, "checkpoint_enqueued": True, "checksum": final["sha256"],
                     "written_bytes": final["bytes"], "checkpoint_bytes": final["bytes"],
                     "checkpoint_identity": state.state_identity(), "checkpoint_revision": state.state_revision}
        summary = {"cycles": 1, "final_state_persistence": persisted,
                   "async_artifact_writer_shutdown": {"drained": True},
                   "async_artifact_writer": {"failed_count": 0, "last_error": ""},
                   "corpus_input_descriptor": snapshot,
                   "corpus_input_provenance": provenance,
                   "corpus_input_identity": checkpoint_metadata["corpus_input_identity"],
                   "corpus_inputs": {"closed": True, "input_integrity_verified": True, "poisoned": False, "failure": None}}
        if weights is not None:
            summary["arrow_feature_weights"] = weights.summary()
        if arguments["snapshot_evaluation_enabled"]:
            versions = {"state_version": state.state_identity(metric_lineage=c.METRIC_LINEAGE),
                        "schema_version": c.METRIC_LINEAGE, "compiler_version": metadata["compiler_version"],
                        "holdout_version": metadata["holdout_version"]}
            summary.update(snapshot_shutdown={"drained": True}, snapshot_evaluator={"closed": True},
                           latest_published_snapshot={"sequence": 1, "versions": versions,
                                                      "metadata": observer.checkpoint_metadata()},
                           latest_promoted_snapshot_evaluation={"sequence": 1, "status": "succeeded", "versions": versions},
                           latest_promoted_snapshot_complete=True)
        summary_path.parent.mkdir(parents=True)
        c.write_new(summary_path, summary)
        c.write_new(log_path, {"event": "cycle", "cycle": 1, "train_indices": [0], "validation_indices": [1],
                               "validation_mode": "rotating_holdout", "feature_projection_report": {"accepted_epochs": 1}})
        observer.record_state("final_shutdown", state, cycle=1, metric_lineage=c.METRIC_LINEAGE,
                              metadata={**metadata, "final_state_persistence": persisted})
        observer.record_return(0)
        inputs.close()
        return 0

    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_modal_daemon_runner as runner
    monkeypatch.setattr(runner, "main", synthetic_main)
    return case


def _executed(case):
    result = {"schema": c.RESULT_SCHEMA, "mode": "execute", "network_guard": {"socket_denial_verified": True}}
    worker._execute(case.launch_ref, result)
    result["success"] = True
    native_ref = c.write_new(case.attempt / "native-result.json", result)
    staged = case.tmp / "staged.bin"
    staged.write_bytes(c.verify(result["final_checkpoint"]))
    return result, {"launch": case.launch_ref, "native_result": native_ref, "candidate": c.describe(staged)}


def test_describe_uses_native_full_state_identity_and_closes_inputs(invocation):
    case = invocation
    result = {}
    worker._describe({key: case.request[key] for key in ("daemon_argv", "base_artifact", "input_snapshot")}, result)
    assert result["base_identity"] == case.request["base_identity"]
    assert result["input_verification"]["closed"] and case.main_calls == 0


def test_execute_and_independent_verify_changed_full_checkpoint(invocation):
    case = invocation
    native, query = _executed(case)
    result = {}
    worker._verify(query, result)
    assert result["state_identity"] == native["state_identity"] != case.request["base_identity"]
    assert native["daemon_seconds_including_shutdown"] >= 0
    assert result["accepted_projection_epochs"] == 1 and result["evaluation_matches_final"] is False
    assert result["intermediate_states_replayed"] is False
    assert "sparse_shadow" not in result and "sparse_shadow" not in native
    assert "arrow_feature_weights" not in result and "arrow_feature_weights" not in native
    assert "arrow_feature_weights" not in native["summary"]
    assert not (case.attempt / "sparse-shadow").exists()
    assert all(session.closed for session in case.sessions)


@pytest.mark.parametrize("mismatch", [None, "missing", "artifact", "storage", "numeric_claim",
                                     "boolean_type", "numeric_type"])
def test_verifier_requires_exact_mapped_input_provenance(invocation, mismatch):
    """Synthetic verified-input declarations exercise real checkpoint verification."""
    case = invocation
    artifact = {"sha256": "f" * 64, "bytes": 5000}
    case.arrow_verification = {
        "schema_version": "autoencoder-embedding-inputs-arrow-v1",
        "production_sha256": "e" * 64, "production_bytes": 123,
        "ordered_record_ids_sha256": "9" * 64, "row_count": 2, "dimension": 384,
        "artifact_sha256": artifact["sha256"], "artifact_bytes": artifact["bytes"],
        "mapped_numeric_bytes": 2 * 384 * 4, "zero_copy_numeric_buffers_verified": True,
        "read_only": True, "whole_training_zero_copy": False,
    }
    case.arrow_input_summary = {
        "job_schema_version": "autoencoder-training-job-v7",
        "row_count": 2,
        "embedding_input_storage": "arrow_mapped_float32",
        "arrow_embedding_inputs_artifact": artifact,
    }
    case.extra_input_provenance = {
        "embedding_input_storage": "arrow_mapped_float32",
        "arrow_embedding_inputs_artifact": copy.deepcopy(artifact),
        "arrow_embedding_inputs_verification": copy.deepcopy(case.arrow_verification),
    }
    if mismatch == "missing":
        case.extra_input_provenance.clear()
    elif mismatch == "artifact":
        case.extra_input_provenance["arrow_embedding_inputs_artifact"]["sha256"] = "8" * 64
    elif mismatch == "storage":
        case.extra_input_provenance["embedding_input_storage"] = "private_list"
    elif mismatch == "numeric_claim":
        case.extra_input_provenance["arrow_embedding_inputs_verification"]["whole_training_zero_copy"] = True
    elif mismatch == "boolean_type":
        case.extra_input_provenance["arrow_embedding_inputs_verification"]["read_only"] = 1
    elif mismatch == "numeric_type":
        case.extra_input_provenance["arrow_embedding_inputs_artifact"]["bytes"] = 5000.0
    _, query = _executed(case)
    if mismatch is not None:
        with pytest.raises(c.DaemonInvocationError, match="candidate input provenance differs"):
            worker._verify(query, {})
    else:
        verified = {}
        worker._verify(query, verified)
        assert verified["input_verification"]["embedding_input_storage"] == "arrow_mapped_float32"
    assert all(session.closed for session in case.sessions)


@pytest.mark.parametrize("changed", ["environment", "arguments", "producer"])
def test_sealed_runtime_changes_fail_before_native_main(invocation, monkeypatch, changed):
    case = invocation
    if changed == "environment":
        monkeypatch.setenv("SYNTHETIC_UNSEALED", "1")
    elif changed == "arguments":
        monkeypatch.setattr(c, "effective_configuration", lambda argv: {})
    else:
        monkeypatch.setattr(c, "producer_identity", lambda args: {"changed": True})
    with pytest.raises(c.DaemonInvocationError):
        worker._execute(case.launch_ref, {})
    assert case.main_calls == 0


def test_existing_private_base_is_not_overwritten(invocation):
    case = invocation
    path = worker._evidence_paths(case.request)[2]
    path.parent.mkdir(parents=True)
    path.write_bytes(b"keep this old attempt")
    with pytest.raises(FileExistsError):
        worker._execute(case.launch_ref, {})
    assert path.read_bytes() == b"keep this old attempt" and case.main_calls == 0
    assert all(session.closed for session in case.sessions)


@pytest.mark.parametrize("tamper", ["sample_id", "record_id", "selection", "base_identity", "final_identity", "binding", "phase", "durability", "source_guard"])
def test_verifier_rejects_resealed_inconsistent_native_evidence(invocation, tamper):
    case = invocation
    native, query = _executed(case)
    selection = next(row for row in native["observation"]["events"] if row["kind"] == "selection")
    states = [row for row in native["observation"]["events"] if row["kind"] == "state"]
    if tamper == "sample_id": selection["train"]["sample_ids"] = ["forged"]
    elif tamper == "record_id": selection["train"]["record_ids"] = ["forged"]
    elif tamper == "selection": selection["train"]["indices"] = [1]
    elif tamper == "base_identity": states[0]["state_identity"]["digest"] = "f" * 64
    elif tamper == "final_identity": states[-1]["state_identity"]["digest"] = "f" * 64
    elif tamper == "binding": native["binding"]["launch_sha256"] = "f" * 64
    elif tamper == "phase": states[-1]["phase"] = "completed_cycle"
    elif tamper == "durability": native["summary"]["final_state_persistence"]["durable"] = False
    elif tamper == "source_guard": native["guards"]["source_after"] = False
    query["native_result"] = c.write_new(case.attempt / "tampered-result.json", native)
    with pytest.raises(c.DaemonInvocationError):
        worker._verify(query, {})


def test_candidate_byte_drift_is_not_hidden_by_matching_receipt(invocation):
    _, query = _executed(invocation)
    Path(query["candidate"]["path"]).write_bytes(b"different")
    with pytest.raises(c.DaemonInvocationError):
        worker._verify(query, {})


@pytest.mark.parametrize("mismatch", [False, True])
def test_snapshot_evidence_attaches_only_to_exact_final_lineage(invocation, mismatch):
    case = invocation
    case.arguments["snapshot_evaluation_enabled"] = True
    case.request_ref = c.write_new(case.tmp / "snapshot-request.json", case.request)
    case.launch["request"] = case.request_ref
    case.launch_ref = c.write_new(case.attempt / "snapshot-launch.json", case.launch)
    native, query = _executed(case)
    if mismatch:
        native["summary"]["latest_promoted_snapshot_evaluation"]["versions"]["state_version"] = "f" * 64
        path = Path(native["summary_artifact"]["path"])
        path.write_bytes(c.canonical(native["summary"]))
        native["summary_artifact"] = c.describe(path)
        query["native_result"] = c.write_new(case.attempt / "mismatched-snapshot-result.json", native)
    result = {}
    worker._verify(query, result)
    assert result["evaluation_matches_final"] is (not mismatch)
    assert result["state_identity"] == native["state_identity"]


def test_primary_execution_error_survives_later_source_guard_error(invocation, monkeypatch):
    case = invocation
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_modal_daemon_runner as runner
    original = ValueError("primary synthetic failure")

    def fail(argv):
        monkeypatch.setattr(c, "producer_identity", lambda args: {"source_drift": True})
        raise original

    monkeypatch.setattr(runner, "main", fail)
    result = {}
    with pytest.raises(ValueError) as caught:
        worker._execute(case.launch_ref, result)
    assert caught.value is original
    assert "final_guard_error" in result and result["observation"]["success"] is False
    assert all(session.closed for session in case.sessions)


def test_real_subprocess_denies_network_and_retains_bounded_failure(tmp_path):
    query = tmp_path / "invalid.json"
    output = tmp_path / "failure.json"
    query.write_text("{}")
    completed = subprocess.run([sys.executable, str(Path(worker.__file__).resolve()), "describe", str(query), str(output)],
                               cwd=tmp_path, env=c.execution_environment(), capture_output=True, timeout=30)
    assert completed.returncode == 1, completed.stderr
    result = json.loads(output.read_text())
    assert not result["success"] and result["network_guard"]["socket_denial_verified"] is True
    assert result["error"]["type"].endswith("DaemonInvocationError")
    assert result["admitted"] is False and result["lease_authority_verified"] is False


def test_receipt_encoding_failure_retains_primary_in_small_exclusive_receipt(tmp_path, monkeypatch):
    query = tmp_path / "query.json"
    output = tmp_path / "failure.json"
    query.write_text("{}")
    monkeypatch.setattr(worker, "_deny_network", lambda: {"synthetic_fixture": True})

    def fail_description(query, result):
        raise RuntimeError("primary synthetic failure")

    monkeypatch.setattr(worker, "_describe", fail_description)
    original = c.write_new
    calls = 0

    def first_write_fails(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("synthetic oversized diagnostic")
        return original(*args, **kwargs)

    monkeypatch.setattr(c, "write_new", first_write_fails)
    assert worker.main(["describe", str(query), str(output)]) == 1
    receipt = json.loads(output.read_text())
    assert receipt["success"] is False
    assert receipt["error"]["message"] == "primary synthetic failure"
    assert receipt["receipt_error"]["message"] == "synthetic oversized diagnostic"


def test_memory_policy_preserves_actual_pass_flags_without_inferring_hits():
    observation = {"events": [
        {"phase": "before_train_evaluation", "cycle": 1, "metadata": {"use_sample_memory": True}},
        {"phase": "before_validation_evaluation", "cycle": 1, "metadata": {"use_sample_memory": False}},
    ]}
    request = {"effective_arguments": {"autoencoder_sample_memory_probe_mode": "off"}}
    cycle = {"feature_projection_report": {"sample_memory_used": False}}
    policy = worker._sample_memory_policy(observation, request, cycle)
    assert [row["use_sample_memory"] for row in policy["evaluation_passes"]] == [True, False]
    assert policy["requested_sample_memory_arguments"] == request["effective_arguments"]
    assert policy["projection_report_sample_memory_used"] is False
    assert policy["memory_hit_counts"] is None


def _enable_sparse_shadow(case):
    case.request.update(schema=c.SHADOW_REQUEST_SCHEMA, sparse_shadow=True)
    case.request_ref = c.write_new(case.tmp / "shadow-request.json", case.request)
    case.launch["request"] = case.request_ref
    case.launch_ref = c.write_new(case.attempt / "shadow-launch.json", case.launch)


def test_opted_in_verifier_replays_multifield_final_state_and_preserves_full_candidate(invocation):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_shadow_evidence import shadow_provenance
    case = invocation
    _enable_sparse_shadow(case)

    def mutate(state):
        del state.feature_embedding_weights["synthetic"]
        state.feature_embedding_weights["replacement"] = [-0.0, 0.5]
        state.family_logits["synthetic-sample"] = {"deontic": -0.0}
        state.applied_todo_ids.extend(["todo-2", "todo-1", "todo-1"])
        state.applied_leanstral_guidance_ids.extend(["guidance-1", "guidance-1"])
        state.applied_proof_feedback_ids.extend(["proof-1", "proof-1"])
        state.proof_feedback_version_fingerprint = "synthetic-proof-version"

    case.extra_mutation = mutate
    native, query = _executed(case)
    candidate_bytes = c.verify(query["candidate"])
    base_bytes = c.verify(case.request["base_artifact"])
    result = {}
    worker._verify(query, result)
    shadow = result["sparse_shadow"]
    assert shadow["passed"] is True and shadow["mode"] == "diagnostic_only"
    assert shadow["full_checkpoint_authoritative"] is True
    assert shadow["registered_base_authority_verified"] is False
    assert shadow["optimizer_acceptance_asserted"] is False
    assert shadow["admitted"] is False and shadow["promoted"] is False
    assert shadow["intermediate_mutations_replayed"] is False
    assert shadow["base_artifact"] == case.request["base_artifact"]
    assert shadow["final_artifact"] == query["candidate"]
    assert shadow["base_version_id"] == case.request["base_version_id"]
    assert shadow["provenance"]["context"] == shadow_provenance(request_ref=case.request_ref,
        launch_ref=query["launch"], native_result_ref=query["native_result"])
    assert shadow["regenerated_compact_checkpoint"] == {key: query["candidate"][key] for key in ("sha256", "bytes")}
    assert shadow["metric_state_identity"] == result["metric_state_identity"]
    assert shadow["capture_report"]["base_snapshot"]["plain_identity"] == case.request["base_identity"]
    assert shadow["capture_report"]["result_snapshot"]["plain_identity"] == native["state_identity"]
    assert set(shadow["capture_report"]["changed_components"]) == {
        "feature_embedding_weights", "family_logits", "legal_ir_view_logits",
        "applied_todo_ids", "applied_leanstral_guidance_ids", "applied_proof_feedback_ids",
        "proof_feedback_version_fingerprint",
    }
    assert shadow["capture_report"]["counts"]["deleted_rows"] == 1
    assert c.verify(query["candidate"]) == candidate_bytes
    assert c.verify(case.request["base_artifact"]) == base_bytes
    assert c.canonical(c.parse_json(c.verify(shadow["receipt_ref"]))) == c.canonical({
        key: value for key, value in shadow.items() if key != "receipt_ref"})
    assert Path(shadow["patch_ref"]["path"]) == case.attempt / "sparse-shadow" / "patch.json"
    assert case.main_calls == 1  # The shadow does not invoke the fixture runner again.
    assert result["guards"] == {"source_before": True, "source_after": True, "inputs_after": True}
    assert all(session.closed for session in case.sessions)


@pytest.mark.parametrize("bad", ["base_identity", "result_identity", "base_revision_bool", "result_revision_bool", "metric_identity", "compact_sha",
                                 "compact_bytes_bool", "missing_check", "integer_check", "passed_false"])
def test_shadow_output_cannot_disagree_with_ordinary_independent_verification(invocation, monkeypatch, bad):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_sparse_shadow as shadows
    case = invocation
    _enable_sparse_shadow(case)
    _, query = _executed(case)
    original = shadows._write_checkpoint_shadow_from_verified_endpoints

    def corrupt(*args, **kwargs):
        value = original(*args, **kwargs)
        if bad == "base_identity":
            value["capture_report"]["base_snapshot"]["plain_identity"]["digest"] = "f" * 64
        elif bad == "result_identity":
            value["capture_report"]["result_snapshot"]["plain_identity"]["digest"] = "f" * 64
        elif bad == "base_revision_bool":
            value["capture_report"]["base_snapshot"]["plain_identity"]["revision"] = False
        elif bad == "result_revision_bool":
            value["capture_report"]["result_snapshot"]["plain_identity"]["revision"] = True
        elif bad == "metric_identity":
            value["metric_state_identity"]["digest"] = "f" * 64
        elif bad == "compact_sha":
            value["regenerated_compact_checkpoint"]["sha256"] = "f" * 64
        elif bad == "compact_bytes_bool":
            value["regenerated_compact_checkpoint"]["bytes"] = True
        elif bad == "missing_check":
            del value["checks"]["all_native_components_exact"]
        elif bad == "integer_check":
            value["checks"]["all_native_components_exact"] = 1
        else:
            value["passed"] = False
        return value

    monkeypatch.setattr(shadows, "_write_checkpoint_shadow_from_verified_endpoints", corrupt)
    result = {}
    with pytest.raises(c.DaemonInvocationError, match="shadow"):
        worker._verify(query, result)
    assert "sparse_shadow" not in result
    assert all(session.closed for session in case.sessions)


@pytest.mark.parametrize("failure", ["source", "input", "candidate"])
def test_late_guards_still_reject_after_successful_shadow(invocation, monkeypatch, failure):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_sparse_shadow as shadows
    case = invocation
    _enable_sparse_shadow(case)
    _, query = _executed(case)
    original = shadows._write_checkpoint_shadow_from_verified_endpoints

    def change_after_shadow(*args, **kwargs):
        value = original(*args, **kwargs)
        if failure == "source":
            monkeypatch.setattr(c, "producer_identity", lambda args: {"late_source_change": True})
        elif failure == "input":
            def rejected_boundary(phase):
                raise c.DaemonInvocationError("late input change")
            case.sessions[-1].verify_boundary = rejected_boundary
        else:
            Path(query["candidate"]["path"]).write_bytes(b"changed after shadow")
        return value

    monkeypatch.setattr(shadows, "_write_checkpoint_shadow_from_verified_endpoints", change_after_shadow)
    result = {}
    with pytest.raises(c.DaemonInvocationError):
        worker._verify(query, result)
    assert result["sparse_shadow"]["passed"] is True
    assert "guards" not in result  # No complete worker verification despite that nested receipt.
    assert all(session.closed for session in case.sessions)


def test_required_shadow_failure_propagates_and_closes_input_session(invocation, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_sparse_shadow as shadows
    case = invocation
    _enable_sparse_shadow(case)
    _, query = _executed(case)
    original = OSError("synthetic shadow publication failure")

    def failed_shadow(*args, **kwargs):
        raise original

    monkeypatch.setattr(shadows, "_write_checkpoint_shadow_from_verified_endpoints", failed_shadow)
    result = {}
    with pytest.raises(OSError) as caught:
        worker._verify(query, result)
    assert caught.value is original
    assert "sparse_shadow" not in result and "guards" not in result
    assert all(session.closed for session in case.sessions)


def test_existing_shadow_directory_is_not_reused(invocation):
    case = invocation
    _enable_sparse_shadow(case)
    _, query = _executed(case)
    directory = case.attempt / "sparse-shadow"
    directory.mkdir()
    preserved = directory / "prior-attempt.txt"
    preserved.write_bytes(b"leave this old evidence untouched")
    with pytest.raises(FileExistsError):
        worker._verify(query, {})
    assert preserved.read_bytes() == b"leave this old evidence untouched"
    assert not (directory / "patch.json").exists()
    assert all(session.closed for session in case.sessions)


def test_shadow_never_runs_before_ordinary_native_verification_succeeds(invocation, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_sparse_shadow as shadows
    case = invocation
    _enable_sparse_shadow(case)
    native, query = _executed(case)
    native["observation"]["success"] = False
    query["native_result"] = c.write_new(case.attempt / "failed-observation.json", native)
    monkeypatch.setattr(shadows, "_write_checkpoint_shadow_from_verified_endpoints", lambda *a, **k: pytest.fail("shadow ran before full verification"))
    with pytest.raises(c.DaemonInvocationError, match="observation"):
        worker._verify(query, {})
    assert not (case.attempt / "sparse-shadow").exists()
    assert all(session.closed for session in case.sessions)


@pytest.mark.parametrize("sparse_shadow,expected_loads", [(False, 2), (True, 3)])
def test_verifier_reuses_mandatory_endpoints_without_three_live_graphs(invocation, monkeypatch, sparse_shadow, expected_loads):
    import gc
    import weakref
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_sparse_shadow as shadows
    case = invocation
    if sparse_shadow:
        _enable_sparse_shadow(case)
    _, query = _executed(case)
    original_load = c.load_full_checkpoint
    graphs, paths = [], []

    def observed_load(ref, *args, **kwargs):
        gc.collect()  # Tracked native states may form normal Python GC cycles.
        assert sum(graph() is not None for graph in graphs) <= 1
        loaded = original_load(ref, *args, **kwargs)
        paths.append(ref["path"])
        graphs.append(weakref.ref(loaded.state))
        assert sum(graph() is not None for graph in graphs) <= 2
        return loaded

    monkeypatch.setattr(c, "load_full_checkpoint", observed_load)
    monkeypatch.setattr(shadows, "load_full_checkpoint", observed_load)
    result = {}
    worker._verify(query, result)
    # Before reuse, opt-in ordinary verification (2) plus public shadow (3)
    # loaded five graphs. The independent replay base remains mandatory.
    expected_paths = [case.request["base_artifact"]["path"], query["candidate"]["path"]]
    if sparse_shadow:
        expected_paths.append(case.request["base_artifact"]["path"])
        assert result["sparse_shadow"]["checks"]["independent_base_reload"] is True
    assert paths == expected_paths and len(graphs) == expected_loads
    gc.collect()
    assert all(graph() is None for graph in graphs)
    assert all(session.closed for session in case.sessions)


@pytest.mark.parametrize("failure", ["observation", "shadow"])
def test_verifier_releases_loader_owned_endpoints_after_failure(invocation, monkeypatch, failure):
    import gc
    import weakref
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_sparse_shadow as shadows
    case = invocation
    _enable_sparse_shadow(case)
    native, query = _executed(case)
    original_load = c.load_full_checkpoint
    graphs, holders = [], []
    original_init = shadows._VerifiedCheckpointEndpoints.__init__

    def observed_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        holders.append(self)

    def observed_load(*args, **kwargs):
        loaded = original_load(*args, **kwargs)
        graphs.append(weakref.ref(loaded.state))
        return loaded

    monkeypatch.setattr(shadows._VerifiedCheckpointEndpoints, "__init__", observed_init)
    monkeypatch.setattr(c, "load_full_checkpoint", observed_load)
    if failure == "observation":
        native["observation"]["success"] = False
        query["native_result"] = c.write_new(case.attempt / "bad-lifetime-observation.json", native)
    else:
        def reject(*args, **kwargs):
            raise OSError("synthetic failure before shadow consumes holder")
        monkeypatch.setattr(shadows, "_write_checkpoint_shadow_from_verified_endpoints", reject)
    with pytest.raises((c.DaemonInvocationError, OSError)) as caught:
        worker._verify(query, {})
    assert len(graphs) == 2 and len(holders) == 1
    with pytest.raises(shadows.SparseShadowError, match="closed|consumed"):
        _ = holders[0].base
    assert all(session.closed for session in case.sessions)
    caught.value.__traceback__ = None
    del caught
    gc.collect()
    assert all(graph() is None for graph in graphs)


def _enable_mapped_weights(case, *, shadow=False, wrong_rows=False, wrong_base=False):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_arrow_weights import build_feature_embedding_weights_ipc
    source = c.load_full_checkpoint(case.request['base_artifact']).state
    if wrong_rows:
        source.feature_embedding_weights['synthetic'][0] = 0.5
    path = case.tmp / 'explicit-feature-weights.arrow'
    build_feature_embedding_weights_ipc(source, path,
        base_checkpoint_sha256='f' * 64 if wrong_base else case.request['base_artifact']['sha256'])
    case.request.update(schema=c.WEIGHT_REQUEST_SCHEMA, sparse_shadow=shadow,
                        arrow_feature_weights=c.describe(path, c.MAX_ARROW_FEATURE_WEIGHT_BYTES))
    case.request_ref = c.write_new(case.tmp / 'weight-request.json', case.request)
    case.launch['request'] = case.request_ref
    case.launch_ref = c.write_new(case.attempt / 'weight-launch.json', case.launch)
    return case.request['arrow_feature_weights']


@pytest.mark.parametrize('shadow,detached', [(False, False), (False, True), (True, False)])
def test_weight_worker_preserves_full_candidate_authority_with_explicit_storage(invocation, shadow, detached):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_weight_session import current_weight_session
    case = invocation
    ref = _enable_mapped_weights(case, shadow=shadow)
    case.detach_weights = detached
    described = {}
    worker._describe({key: case.request[key] for key in
        ('daemon_argv', 'base_artifact', 'input_snapshot', 'arrow_feature_weights')}, described)
    assert described['arrow_feature_weights']['closed'] is True
    assert described['arrow_feature_weights']['base_verified'] is True
    assert described['arrow_feature_weights']['attached'] is False
    native, query = _executed(case)
    verified = {}
    worker._verify(query, verified)
    observed = native['arrow_feature_weights']
    assert observed['closed'] is True and observed['attached'] is True and observed['poisoned'] is False
    assert observed['current_storage'] == ('detached_native' if detached else 'mapped_overlay')
    assert verified['arrow_feature_weights']['closed'] is True
    assert verified['arrow_feature_weights']['attached'] is False
    assert verified['state_identity'] == native['state_identity']
    assert ('sparse_shadow' in verified) is shadow
    assert current_weight_session() is None
    loaded = c.load_full_checkpoint(query['candidate'], compact_only=True)
    assert c.canonical(loaded.manifest.metadata['arrow_feature_weights_provenance']) == c.canonical(observed['provenance'])
    assert observed['provenance']['artifact'] == {key: ref[key] for key in ('sha256', 'bytes')}
    assert observed['provenance']['whole_training_zero_copy'] is False
    assert loaded.state.feature_embedding_weights['synthetic'] == [0.25, -0.0]
    if shadow:
        assert verified['sparse_shadow']['full_checkpoint_authoritative'] is True


@pytest.mark.parametrize('mismatch', ['rows', 'base_sha', 'bytes'])
def test_explicit_weights_fail_before_runner_when_not_exact_authoritative_base(invocation, mismatch):
    case = invocation
    ref = _enable_mapped_weights(case, wrong_rows=mismatch == 'rows', wrong_base=mismatch == 'base_sha')
    if mismatch == 'bytes':
        with Path(ref['path']).open('r+b') as stream:
            stream.write(b'broken')
    with pytest.raises(ValueError):
        worker._execute(case.launch_ref, {})
    assert case.main_calls == 0
    assert all(session.closed for session in case.sessions)


@pytest.mark.parametrize('cause', ['main_failure', 'mutation'])
def test_weight_context_and_mapping_close_when_daemon_fails(invocation, cause):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_weight_session import current_weight_session
    case = invocation
    ref = _enable_mapped_weights(case)
    primary = RuntimeError('synthetic daemon failure after attaching weights')
    def fail(state):
        if cause == 'main_failure':
            raise primary
        with Path(ref['path']).open('r+b') as stream:
            stream.write(b'changed')
    case.extra_mutation = fail
    result = {}
    with pytest.raises((ValueError, RuntimeError)) as caught:
        worker._execute(case.launch_ref, result)
    if cause == 'main_failure':
        assert caught.value is primary
    assert result['arrow_feature_weights']['closed'] is True
    assert result['arrow_feature_weights']['poisoned'] is (cause == 'mutation')
    assert current_weight_session() is None
    assert not worker._evidence_paths(case.request)[0].exists()


@pytest.mark.parametrize('tamper', ['native_not_closed', 'native_bool_type', 'native_artifact', 'summary_not_attached',
                                  'summary_detached_invalid', 'checkpoint_provenance', 'sidecar_changed'])
def test_independent_verifier_rejects_inconsistent_weight_evidence(invocation, tamper):
    case = invocation
    ref = _enable_mapped_weights(case)
    native, query = _executed(case)
    if tamper == 'native_not_closed':
        native['arrow_feature_weights']['closed'] = False
    elif tamper == 'native_bool_type':
        native['arrow_feature_weights']['provenance']['whole_training_zero_copy'] = 0
    elif tamper == 'native_artifact':
        native['arrow_feature_weights']['provenance']['artifact']['sha256'] = 'e' * 64
    elif tamper == 'summary_not_attached':
        native['summary']['arrow_feature_weights']['attached'] = False
    elif tamper == 'summary_detached_invalid':
        native['summary']['arrow_feature_weights']['current_storage'] = 'unverified_fallback'
    elif tamper == 'checkpoint_provenance':
        state = c.load_full_checkpoint(query['candidate'], compact_only=True)
        metadata = dict(state.manifest.metadata)
        metadata['arrow_feature_weights_provenance'] = {**metadata['arrow_feature_weights_provenance'], 'row_count': True}
        raw = serialize_checkpoint(state.state, metadata=metadata, revision=state.state.state_revision)
        Path(native['final_checkpoint']['path']).write_bytes(raw)
        Path(query['candidate']['path']).write_bytes(raw)
        native['final_checkpoint'] = c.describe(native['final_checkpoint']['path'])
        query['candidate'] = c.describe(query['candidate']['path'])
        persisted = native['summary']['final_state_persistence']
        persisted.update(checksum=query['candidate']['sha256'], written_bytes=len(raw), checkpoint_bytes=len(raw))
    else:
        with Path(ref['path']).open('r+b') as stream:
            stream.write(b'changed')
    # Reseal outer descriptors so nested semantic checks are exercised.
    summary_path = Path(native['summary_artifact']['path'])
    summary_path.write_bytes(c.canonical(native['summary']))
    native['summary_artifact'] = c.describe(summary_path)
    query['native_result'] = c.write_new(case.attempt / 'weight-tampered-result.json', native)
    with pytest.raises(ValueError):
        worker._verify(query, {})


@pytest.mark.parametrize('query', [None, True, []])
def test_describe_rejects_non_object_before_optional_weight_dispatch(query):
    with pytest.raises(c.DaemonInvocationError, match='closed worker query'):
        worker._describe(query, {})
