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


# Fixed F18 adapter controls below use only metadata and fake numerical owners.
# They do not load Torch, retained model/source payloads, or native leases.
def _f18_compute_fixture():
    ref = {"path": "/tmp/f18-owned-metadata.json", "bytes": 1, "sha256": "a" * 64}
    return {name: dict(ref) for name in ("input_descriptors", "initial_parity", "runtime_contract", "population_manifest")} | {
        "max_steps_per_arm": 32, "max_seconds_per_arm": 32}


def test_f18_compute_shape_is_pure_detached_and_has_no_authority(monkeypatch):
    value = _f18_compute_fixture()
    monkeypatch.setattr(worker, "_contracts", lambda: pytest.fail("shape validation opened dependencies"))
    real_path = Path
    class LexicalPath:
        def __init__(self, value):
            self.value = real_path(value)
        def is_absolute(self):
            return self.value.is_absolute()
        @property
        def parts(self):
            return self.value.parts
        def __str__(self):
            return str(self.value)
        def __getattr__(self, name):
            pytest.fail("shape validation accessed filesystem method " + name)
    monkeypatch.setattr(worker, "Path", LexicalPath)
    actual = worker.validate_f18_compute(value)
    assert actual == value and actual is not value
    actual["input_descriptors"]["bytes"] = 2
    assert value["input_descriptors"]["bytes"] == 1
    assert "torch" not in worker.validate_f18_compute.__code__.co_names


@pytest.mark.parametrize("bad", ["unknown", "reference_body", "relative", "escape", "alias_spelling", "nul",
    "bytes_bool", "bytes_zero", "bytes_large", "sha", "ref_extra", "steps_bool", "steps_short", "seconds_float"])
def test_f18_compute_rejects_nonclosed_or_unbounded_inputs_before_access(monkeypatch, bad):
    value = _f18_compute_fixture()
    if bad in {"unknown", "reference_body"}:
        value[bad] = {"gold": "must never be opened"}
    elif bad in {"relative", "escape", "alias_spelling", "nul"}:
        value["initial_parity"]["path"] = {"relative": "relative.json", "escape": "/tmp/../secret.json",
            "alias_spelling": "/tmp//metadata.json", "nul": "/tmp/invalid\x00.json"}[bad]
    elif bad.startswith("bytes_"):
        value["initial_parity"]["bytes"] = {"bytes_bool": True, "bytes_zero": 0, "bytes_large": 131073}[bad]
    elif bad == "sha":
        value["initial_parity"]["sha256"] = "A" * 64
    elif bad == "ref_extra":
        value["initial_parity"]["reference_body"] = []
    elif bad == "steps_bool":
        value["max_steps_per_arm"] = True
    elif bad == "steps_short":
        value["max_steps_per_arm"] = 31
    else:
        value["max_seconds_per_arm"] = 32.0
    monkeypatch.setattr(worker, "_contracts", lambda: pytest.fail("invalid shape opened dependencies"))
    with pytest.raises(ValueError):
        worker.validate_f18_compute(value)


def _f18_source_fixture():
    owner = SimpleNamespace(_raw=c.canonical, checkpoint_digest=c.digest)
    panels, index = {}, 0
    for name, count, _ in worker._F18_PANELS:
        rows = []
        for _ in range(count):
            rows.append({"id": "source-" + str(index), "source_text": "source text " + str(index),
                         "latent": [0.0 if name in {"fresh_dev", "fresh_test"} else 0.125] * 384})
            index += 1
        panels[name] = rows
    training = [dict(row, labels={"TRAIN_fixture_only": True}) for row in panels["training168"]]
    donor = {"teacher_training_examples": training, "training_manifest_sha256": c.digest(training)}
    original = {"schema": "temporal-adapter-source-only-diagnostics-export/v1", "training_rows": training,
        "training_metadata": [{} for _ in training], "diagnostic_sources": {name: panels[name] for name, _, _ in worker._F18_PANELS[1:8]},
        "semantic_gold": False}
    fresh = {"schema": "temporal-attention-fresh-source-export/v1", "populations": {name: panels[name]
        for name in ("fresh_dev", "fresh_test")}, "semantic_gold": False}
    population = {"schema": "retained-final-f18-source-only-632-parity-descriptors/v1", "panels": [
        {"panel": name, "expected_rows": count, "chunk_sizes": list(sizes)} for name, count, sizes in worker._F18_PANELS]}
    return owner, donor, training, original, fresh, population


def test_f18_source_projection_preserves_nonzero_dormant_vectors_and_strips_train_labels():
    owner, donor, records, original, fresh, population = _f18_source_fixture()
    raw = {worker._F18_ROLES[2]: c.canonical(original), worker._F18_ROLES[3]: c.canonical(fresh)}
    panels = worker._f18_source_panels(c, owner, donor, records, raw, population)
    assert sum(map(len, panels.values())) == 632
    assert panels["training168"][0]["latent"] == [0.125] * 384
    assert panels["old_tune"][0]["latent"] == [0.125] * 384
    assert all(set(row) == {"id", "source_text", "latent"} for rows in panels.values() for row in rows)
    assert panels["fresh_test"][0]["latent"] == [0.0] * 384
    assert "labels" in records[0]


@pytest.mark.parametrize("bad", ["raw_training", "reference_row", "fresh_nonzero", "bool_vector", "duplicate_source"])
def test_f18_source_projection_refuses_crossed_training_gold_or_population(bad):
    owner, donor, records, original, fresh, population = _f18_source_fixture()
    if bad == "raw_training":
        original = copy.deepcopy(original)
        original["training_rows"][0]["source_text"] = "different original bank"
    elif bad == "reference_row":
        original["diagnostic_sources"]["law"][0]["canonical_ir"] = {"must_not_reach_decoder": True}
    elif bad == "fresh_nonzero":
        fresh["populations"]["fresh_dev"][0]["latent"][0] = 0.125
    elif bad == "bool_vector":
        original["diagnostic_sources"]["law"][0]["latent"][0] = False
    else:
        fresh["populations"]["fresh_dev"][0]["source_text"] = records[0]["source_text"]
    raw = {worker._F18_ROLES[2]: c.canonical(original), worker._F18_ROLES[3]: c.canonical(fresh)}
    with pytest.raises(ValueError):
        worker._f18_source_panels(c, owner, donor, records, raw, population)


class _F18FakeProfile:
    """Metadata-only owner stub: no tensor, model, optimizer or lease exists."""
    checkpoint_digest = staticmethod(c.digest)

    def __init__(self, *, steps=32):
        self.steps, self.events = steps, []

    def build_checkpoint(self, **kwargs):
        self.events.append(("build", kwargs["margin_weight"], kwargs["state"]))
        return {"model_state_sha256": "b" * 64, "progress": {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0}}

    def save_checkpoint(self, checkpoint, path, **kwargs):
        self.events.append(("save", path.name, kwargs["margin_weight"]))
        return c.write_new(path, checkpoint)

    def load_checkpoint(self, path, *, expected_sha256, **kwargs):
        self.events.append(("load", kwargs["margin_weight"]))
        raw = Path(path).read_bytes()
        assert c.digest(json.loads(raw)) == expected_sha256
        return json.loads(raw)

    def run_admitted_updates(self, checkpoint, *, torch, max_steps, max_seconds, **kwargs):
        self.events.append(("run", kwargs["margin_weight"], max_steps, max_seconds))
        steps = self.steps
        trained = {"model_state_sha256": "c" * 64, "progress": {"epochs_completed": (steps * 12) // 168,
            "row_cursor": (steps * 12) % 168, "optimizer_steps": steps}}
        report = {"optimizer_steps": steps, "batch_trace": [{} for _ in range(steps)], "requested_steps": 32,
            "before_progress": checkpoint["progress"], "after_progress": trained["progress"],
            "checkpoint_sha256": c.digest(trained), "all_requested_steps_completed": steps == 32}
        return trained, report


def test_f18_fit_pair_uses_two_fixed_fresh_arms_and_persisted_capture_inputs(tmp_path, monkeypatch):
    profile = _F18FakeProfile()
    donor = {"model_state": {"same_donor": True}, "teacher_training": {}, "row_weight_training": {}}
    captures = []
    def capture(*args):
        captures.append((args[5], args[6]["margin_weight"], args[-1].name))
        return [{"panel": name} for name, _, _ in worker._F18_PANELS]
    monkeypatch.setattr(worker, "_f18_capture_arm", capture)
    arms, updates, forwards, complete = worker._f18_fit_pair(c, None, profile, None, object(), donor,
        [], {}, {}, {}, tmp_path)
    assert complete is True and updates == 64 and forwards == 1264
    assert [row["margin_weight"] for row in arms] == [0.0, 0.25]
    assert [event for event in profile.events if event[0] == "run"] == [("run", 0.0, 32, 32), ("run", 0.25, 32, 32)]
    assert [event[2] for event in profile.events if event[0] == "build"] == [donor["model_state"], donor["model_state"]]
    assert [row[1:] for row in captures] == [(0.0, "arm-0"), (0.25, "arm-025")]
    assert all(c.digest(row[0]) == c.digest(json.loads(Path(arm["checkpoint"]["path"]).read_bytes()))
               for row, arm in zip(captures, arms, strict=True))
    assert profile.events.index(("load", 0.0)) < profile.events.index(("build", 0.25, donor["model_state"]))


@pytest.mark.parametrize("steps", [0, 3, 31])
def test_f18_partial_arm_is_saved_without_capture_second_arm_or_retry(tmp_path, monkeypatch, steps):
    profile = _F18FakeProfile(steps=steps)
    monkeypatch.setattr(worker, "_f18_capture_arm", lambda *a: pytest.fail("partial arm captured"))
    arms, updates, captures, complete = worker._f18_fit_pair(c, None, profile, None, object(),
        {"model_state": {}, "teacher_training": {}, "row_weight_training": {}}, [], {}, {}, {}, tmp_path)
    assert complete is False and updates == steps and captures == 0 and len(arms) == 1
    assert Path(arms[0]["checkpoint"]["path"]).is_file() and Path(arms[0]["report"]["path"]).is_file()
    assert len([event for event in profile.events if event[0] == "run"]) == 1
    assert not (tmp_path / "arm-025").exists()


def test_f18_existing_arm_output_is_never_reused_or_overwritten(tmp_path, monkeypatch):
    arm = tmp_path / "arm-0"
    arm.mkdir()
    prior = arm / "prior.json"
    prior.write_bytes(b"retain original failure")
    profile = _F18FakeProfile()
    with pytest.raises(FileExistsError):
        worker._f18_fit_pair(c, None, profile, None, object(),
            {"model_state": {}, "teacher_training": {}, "row_weight_training": {}}, [], {}, {}, {}, tmp_path)
    assert prior.read_bytes() == b"retain original failure" and profile.events == []


def test_f18_parity_gate_binds_original_population_and_donor_before_fit():
    bindings = {"donor_checkpoint_sha256": "a" * 64, "donor_model_state_sha256": worker._F18_MODEL_ROOT,
        "training_manifest_sha256": "b" * 64, "prepared_training_records_sha256": "c" * 64}
    compute = _f18_compute_fixture()
    descriptors = [{"bytes": 1, "sha256": str(i) * 64} for i in range(6)]
    population = {"source_inputs": {name: dict(descriptors[i]) for name, i in
        (("authenticated_final_F18_checkpoint", 0), ("original_source_export", 2), ("fresh_source_export", 3))}}
    parity = {"evidence_id": "f18-initial632-parity-qualified-20261027-01",
        "selected_product_source": {"profile_sha256": worker._F18_PROFILE_SHA256},
        "parity": {"qualified": True, "compared_head_scalars": 194812,
            "all_heads_binary32_bits_including_signed_zero_equal": True,
            "complete_original_greedy_formal_decoded_rows_equal": True, "complete_pure_joint_result_records_equal": True},
        "population": {"total_rows": 632}, "evidence_inputs": {"source_population_manifest": compute["population_manifest"]},
        "authenticated_roots": {"final_F18_physical_sha256": bindings["donor_checkpoint_sha256"],
            "all42_model_state_sha256": worker._F18_MODEL_ROOT, "frozen38_sha256_including_modality": worker._F18_FROZEN_ROOT,
            "raw_TRAIN168_manifest_sha256": bindings["training_manifest_sha256"],
            "prepared_TRAIN168_records_sha256": bindings["prepared_training_records_sha256"]}}
    worker._f18_parity(parity, bindings, compute, population, descriptors)
    changed = copy.deepcopy(population)
    changed["source_inputs"]["original_source_export"]["sha256"] = "f" * 64
    with pytest.raises(ValueError, match="source asset identity"):
        worker._f18_parity(parity, bindings, compute, changed, descriptors)
    changed = copy.deepcopy(parity)
    changed["selected_product_source"]["profile_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="initial632"):
        worker._f18_parity(changed, bindings, compute, population, descriptors)


class _F18FakeCaptureProfile(_F18FakeProfile):
    def restore_optimizer(self, torch, checkpoint, **kwargs):
        self.events.append(("capture_restore", kwargs["margin_weight"]))
        return {"model_forwards": 0}

    def captured_inference(self, runtime, checkpoint, rows, **kwargs):
        import hashlib
        self.events.append(("capture", kwargs["margin_weight"], len(rows)))
        runtime["model_forwards"] += len(rows)
        return {"actual_source_forwards": len(rows), "extra_capture_forwards": 0,
            "cumulative_source_forwards": runtime["model_forwards"],
            "forward_counter_deltas": {"actor": {"source": len(rows)}, "conditions": {"source": len(rows)}},
            "target_access": False, "teacher_forcing": False,
            "occurrences": [{"id": row["id"], "source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(),
                "scores": {"synthetic_metadata_only": True}} for row in rows]}


def _f18_fake_panels():
    return {name: [{"id": name + str(i), "source_text": name + " source " + str(i), "latent": []}
                   for i in range(count)] for name, count, _ in worker._F18_PANELS}


def test_f18_capture_uses_one_restore_eleven_chunks_and_complete_twenty_outputs(tmp_path):
    profile = _F18FakeCaptureProfile()
    selector = SimpleNamespace(select_joint_spans=lambda text, scores, **kw: {
        "source": text, "top_k": kw["top_k"], "nodes": kw["max_search_nodes"]})
    refs = worker._f18_capture_arm(c, None, profile, selector, object(), {},
        {"margin_weight": 0.25}, _f18_fake_panels(), tmp_path)
    assert len(refs) == 10 and sum(row["rows"] for row in refs) == 632
    assert len(list(tmp_path.iterdir())) == 20
    assert len([row for row in profile.events if row[0] == "capture_restore"]) == 1
    assert [row[2] for row in profile.events if row[0] == "capture"] == [128, 40, 96, 36, 36, 72, 72, 72, 8, 36, 36]
    assert all(c.parse_json(c.verify(row["joint"]))["reference_scoring_performed"] is False for row in refs)


def _f18_fake_entry(tmp_path, monkeypatch, *, partial=False, drift=False):
    from contextlib import contextmanager
    meta = tmp_path / "metadata"
    meta.mkdir()
    assets = [{"role": role, **c.write_new(meta / (str(i) + ".json"), {"fixture": i})}
              for i, role in enumerate(worker._F18_ROLES)]
    values = {"input_descriptors": {"schema": "retained-f18-input-authentication-descriptors/v1", "assets": assets},
              "initial_parity": {}, "runtime_contract": {}, "population_manifest": {}}
    compute = {key: c.write_new(meta / (key + ".json"), value) for key, value in values.items()}
    compute.update(max_steps_per_arm=32, max_seconds_per_arm=32)
    output = tmp_path / "exports"
    output.mkdir()
    request = {"schema": "owned-f18-conditions-training-request/v1", "mode": "paired_fit", "compute": compute,
               "outputs": {"exports": str(output)}}
    profile = _F18FakeCaptureProfile(steps=3 if partial else 32)
    selector = SimpleNamespace(select_joint_spans=lambda text, scores, **kw: {"source": text, **kw})
    monkeypatch.setattr(worker, "_f18_owners", lambda request: (None, profile, selector))
    monkeypatch.setattr(worker, "_f18_authenticate", lambda *args: (
        {"model_state": {}, "teacher_training": {}, "row_weight_training": {}}, [], {}, {}))
    monkeypatch.setattr(worker, "_f18_parity", lambda *args: None)
    monkeypatch.setattr(worker, "_f18_source_panels", lambda *args: _f18_fake_panels())
    @contextmanager
    def runtime(*args):
        yield object(), {"external_process_attempts": [], "scoped_dl_resolver_calls": [], "resolver_restored": True}
    monkeypatch.setattr(worker, "_f18_runtime", runtime)
    old_close = worker._f18_close
    closed = []
    def closing(caller, opened):
        closed.append((output / "f18-paired/pair-output-freeze.json").exists())
        if drift:
            Path(compute["input_descriptors"]["path"]).write_bytes(b"changed after output freeze")
        old_close(caller, opened)
    monkeypatch.setattr(worker, "_f18_close", closing)
    return request, output, profile, closed


def test_f18_fixed_entry_freezes_both_arms_and_closes_inputs_before_completed(tmp_path, monkeypatch):
    request, output, profile, closed = _f18_fake_entry(tmp_path, monkeypatch)
    result = worker.run_f18_paired_training(request, output_directory=output)
    assert result["completed"] is True and result["optimizer_updates"] == 64
    assert result["model_forwards"] == 1328 and result["capture_source_forwards"] == 1264
    assert result["fit_fresh4_restore_calls"] == result["capture_fresh4_restore_calls"] == 2
    assert closed == [True]
    freeze = c.parse_json(c.verify(result["output_freeze"]))
    assert freeze["raw_joint_files"] == 40 and freeze["evaluation_gold_reference_or_comparator_bodies_opened"] == 0
    assert freeze["future_scoring_performed"] is False
    assert all(result[key] is False for key in worker._F18_FALSE)
    assert len([event for event in profile.events if event[0] == "capture"]) == 22


def test_f18_fixed_entry_returns_saved_partial_without_a_complete_freeze(tmp_path, monkeypatch):
    request, output, profile, closed = _f18_fake_entry(tmp_path, monkeypatch, partial=True)
    result = worker.run_f18_paired_training(request, output_directory=output)
    assert result["completed"] is False and result["optimizer_updates"] == 3
    assert result["model_forwards"] == 3 and result["capture_source_forwards"] == 0
    assert result["output_freeze"] is None and closed == [False]
    assert len([event for event in profile.events if event[0] == "run"]) == 1


def test_f18_late_input_drift_refuses_success_after_preserving_frozen_outputs(tmp_path, monkeypatch):
    request, output, profile, closed = _f18_fake_entry(tmp_path, monkeypatch, drift=True)
    with pytest.raises(ValueError, match="changed"):
        worker.run_f18_paired_training(request, output_directory=output)
    assert closed == [True]
    assert (output / "f18-paired/pair-output-freeze.json").is_file()
    assert len([event for event in profile.events if event[0] == "run"]) == 2


# Explicit v2 trainer controls use authored metadata and fake numerical owners.
# The fixture rate .003 selects no retained experiment and no tensor is created.
def _f18_v2_compute_fixture():
    return {**_f18_compute_fixture(), "learning_rate": 0.003}


def test_f18_v2_compute_is_explicit_detached_and_lexical(monkeypatch):
    value = _f18_v2_compute_fixture()
    monkeypatch.setattr(worker, "_contracts", lambda: pytest.fail("compute parser opened dependencies"))
    actual = worker.validate_f18_compute(value, version=2)
    assert actual == value and actual is not value
    actual["input_descriptors"]["bytes"] = 2
    assert value["input_descriptors"]["bytes"] == 1
    assert actual["learning_rate"] == 0.003


@pytest.mark.parametrize("rate", [True, False, None, "0.003", 0, -0.003,
    float("nan"), float("inf"), -float("inf")])
def test_f18_v2_compute_refuses_invalid_rate_before_access(monkeypatch, rate):
    value = _f18_v2_compute_fixture()
    value["learning_rate"] = rate
    monkeypatch.setattr(worker, "_contracts", lambda: pytest.fail("invalid rate opened dependencies"))
    with pytest.raises(ValueError, match="learning_rate"):
        worker.validate_f18_compute(value, version=2)


@pytest.mark.parametrize("version", [True, False, None, "2", 0, 3])
def test_f18_compute_refuses_implicit_or_unknown_version(version):
    with pytest.raises(ValueError, match="version"):
        worker.validate_f18_compute(_f18_v2_compute_fixture(), version=version)


@pytest.mark.parametrize("version,extra_rate", [(1, True), (2, False)])
def test_f18_compute_refuses_cross_version_fields(version, extra_rate):
    value = _f18_v2_compute_fixture() if extra_rate else _f18_compute_fixture()
    with pytest.raises(ValueError, match="closed"):
        worker.validate_f18_compute(value, version=version)


@pytest.mark.parametrize("damage", ["steps", "seconds", "reference", "extra"])
def test_f18_v2_compute_keeps_original_bounds(damage):
    value = _f18_v2_compute_fixture()
    if damage == "steps": value["max_steps_per_arm"] = 33
    elif damage == "seconds": value["max_seconds_per_arm"] = 32.0
    elif damage == "reference": value["initial_parity"]["bytes"] = True
    else: value["argv"] = ["forbidden generic command"]
    with pytest.raises(ValueError):
        worker.validate_f18_compute(value, version=2)


def _f18_v2_parity_fixture():
    """Authored gate input; no assertion of physical receipt authenticity."""
    compute = _f18_v2_compute_fixture()
    compute["initial_parity"].update(bytes=30633, sha256=worker._F18_V2_PARITY_SHA256)
    descriptors = [{"role": role, "path": "/tmp/f18-v2-asset-" + str(i),
                    "bytes": i + 1, "sha256": str(i) * 64}
                   for i, role in enumerate(worker._F18_ROLES)]
    bindings = {"donor_checkpoint_sha256": descriptors[0]["sha256"],
                "donor_model_state_sha256": worker._F18_MODEL_ROOT,
                "training_manifest_sha256": "b" * 64,
                "prepared_training_records_sha256": "c" * 64}
    population = {"source_inputs": {name: dict(descriptors[i]) for name, i in
        (("authenticated_final_F18_checkpoint", 0), ("original_source_export", 2), ("fresh_source_export", 3))}}
    counts = (51204, 33564, 9108, 9108, 20232, 20232, 20232, 4852, 12924, 13356)
    parity = {"schema": "retained-f18-four-tensor-initial632-parity-result/v2",
        "profile_source_sha256": worker._F18_V2_PROFILE_SHA256,
        "original_f18_source_sha256": worker._F18_SOURCE_SHA256,
        "initial632_parity_qualified": True, "parity_receipt_fabricated": False,
        "expected_input_bindings": copy.deepcopy(bindings),
        "inputs_sha256": compute["input_descriptors"]["sha256"],
        "parity_manifest_sha256": compute["population_manifest"]["sha256"],
        "runtime_contract_sha256": compute["runtime_contract"]["sha256"],
        "verified_assets": copy.deepcopy(descriptors),
        "authenticated_final_F18_whole_sha256": bindings["donor_checkpoint_sha256"],
        "all42_model_state_sha256": worker._F18_MODEL_ROOT,
        "frozen38_sha256_including_modality": worker._F18_FROZEN_ROOT,
        "head_binary32_scalar_comparisons": 194812,
        "canonical_capture_source_forwards": 632, "canonical_capture_chunks": 11,
        "training_rows": 168, "conditions_present": 72, "conditions_absent": 96,
        "optimizer_updates": 0, "gradient_calls": 0, "teacher_model_restores": 0,
        "fit_executed": False, "scoring_executed": False, "new_trained_weights": False,
        "admitted": False, "formalized": False, "promoted": False,
        "experiment_rate_selected": None, "parity_optimizer_learning_rate": 0.001,
        "donor_config_learning_rate": 0.001,
        "panel_comparisons": [{"panel": name, "rows": count, "binary32_head_scalars": scalars,
            "all_heads_bitwise_equal": True, "entire_greedy_formal_rows_equal": True,
            "complete_joint_rows_equal": True}
            for (name, count, _), scalars in zip(worker._F18_PANELS, counts, strict=True)]}
    return parity, bindings, compute, population, descriptors


def test_f18_v2_parity_reuses_bound_zero_step_control_independent_of_train_rate(monkeypatch):
    parity, bindings, compute, population, descriptors = _f18_v2_parity_fixture()
    monkeypatch.setattr(worker, "_contracts", lambda: pytest.fail("pure parity gate opened dependencies"))
    before = copy.deepcopy((parity, bindings, compute, population, descriptors))
    worker._f18_v2_parity(parity, bindings, compute, population, descriptors)
    assert (parity, bindings, compute, population, descriptors) == before
    assert compute["learning_rate"] == 0.003 and parity["parity_optimizer_learning_rate"] == 0.001


@pytest.mark.parametrize("damage", ["receipt_hash", "receipt_bytes", "old_schema", "profile", "f18_source",
    "qualified_boolean", "fabricated", "input_binding", "inputs", "population_digest", "runtime",
    "asset_role", "asset_bytes", "asset_hash", "asset_missing", "donor", "all42", "frozen38",
    "heads_count", "updates_boolean", "gradient", "fit", "scoring", "authority", "selected_rate",
    "donor_rate", "panel_missing", "panel_order", "panel_rows", "panel_heads_sum", "panel_greedy",
    "panel_joint", "population_asset"])
def test_f18_v2_parity_refuses_crossed_or_incomplete_evidence(damage):
    parity, bindings, compute, population, descriptors = _f18_v2_parity_fixture()
    if damage == "receipt_hash": compute["initial_parity"]["sha256"] = "f" * 64
    elif damage == "receipt_bytes": compute["initial_parity"]["bytes"] = 30632
    elif damage == "old_schema": parity["schema"] = "retained-f18-four-tensor-initial632-parity-result/v1"
    elif damage == "profile": parity["profile_source_sha256"] = worker._F18_PROFILE_SHA256
    elif damage == "f18_source": parity["original_f18_source_sha256"] = "f" * 64
    elif damage == "qualified_boolean": parity["initial632_parity_qualified"] = 1
    elif damage == "fabricated": parity["parity_receipt_fabricated"] = True
    elif damage == "input_binding": bindings["prepared_training_records_sha256"] = "f" * 64
    elif damage == "inputs": parity["inputs_sha256"] = "f" * 64
    elif damage == "population_digest": parity["parity_manifest_sha256"] = "f" * 64
    elif damage == "runtime": parity["runtime_contract_sha256"] = "f" * 64
    elif damage == "asset_role": parity["verified_assets"][1]["role"] = worker._F18_ROLES[0]
    elif damage == "asset_bytes": parity["verified_assets"][1]["bytes"] += 1
    elif damage == "asset_hash": parity["verified_assets"][1]["sha256"] = "f" * 64
    elif damage == "asset_missing": parity["verified_assets"].pop()
    elif damage == "donor": parity["authenticated_final_F18_whole_sha256"] = "f" * 64
    elif damage == "all42": parity["all42_model_state_sha256"] = "f" * 64
    elif damage == "frozen38": parity["frozen38_sha256_including_modality"] = "f" * 64
    elif damage == "heads_count": parity["head_binary32_scalar_comparisons"] -= 1
    elif damage == "updates_boolean": parity["optimizer_updates"] = False
    elif damage == "gradient": parity["gradient_calls"] = 1
    elif damage == "fit": parity["fit_executed"] = True
    elif damage == "scoring": parity["scoring_executed"] = True
    elif damage == "authority": parity["admitted"] = True
    elif damage == "selected_rate": parity["experiment_rate_selected"] = 0.003
    elif damage == "donor_rate": parity["donor_config_learning_rate"] = 0.003
    elif damage == "panel_missing": parity["panel_comparisons"].pop()
    elif damage == "panel_order": parity["panel_comparisons"].reverse()
    elif damage == "panel_rows": parity["panel_comparisons"][0]["rows"] = 167
    elif damage == "panel_heads_sum": parity["panel_comparisons"][0]["binary32_head_scalars"] -= 1
    elif damage == "panel_greedy": parity["panel_comparisons"][0]["entire_greedy_formal_rows_equal"] = False
    elif damage == "panel_joint": parity["panel_comparisons"][0]["complete_joint_rows_equal"] = False
    else: population["source_inputs"]["original_source_export"]["sha256"] = "f" * 64
    with pytest.raises(ValueError):
        worker._f18_v2_parity(parity, bindings, compute, population, descriptors)


class _F18FakeV2Recipes:
    """No numerical state or authority: records independently supplied kwargs."""
    recipe_digest = staticmethod(c.digest)

    def __init__(self, directory, *, refuse_second=False):
        self.directory, self.refuse_second, self.events = directory, refuse_second, []

    def build_optimizer_recipe(self, **kwargs):
        assert not tuple(self.directory.iterdir()), "an arm existed before both recipes were validated"
        self.events.append(("build", copy.deepcopy(kwargs)))
        return {"synthetic_metadata_only": True, **copy.deepcopy(kwargs)}

    def validate_optimizer_recipe(self, recipe, **kwargs):
        assert not tuple(self.directory.iterdir()), "an arm existed before both recipes were validated"
        self.events.append(("validate", copy.deepcopy(kwargs)))
        assert recipe == {"synthetic_metadata_only": True, **kwargs}
        if self.refuse_second and kwargs["margin_weight"] == 0.25:
            raise ValueError("authored second recipe refusal")
        return copy.deepcopy(recipe)


class _F18FakeV2Profile(_F18FakeCaptureProfile):
    def __init__(self, directory, *, steps=32, refuse_second=False):
        super().__init__(steps=steps)
        self.recipes = _F18FakeV2Recipes(directory, refuse_second=refuse_second)
        self.v2_kwargs = []

    def build_checkpoint(self, **kwargs):
        assert kwargs["learning_rate"] == kwargs["recipe"]["learning_rate"] == 0.003
        assert kwargs["margin_weight"] == kwargs["recipe"]["margin_weight"]
        self.v2_kwargs.append(copy.deepcopy(kwargs))
        return super().build_checkpoint(**kwargs)


def _f18_v2_fit_fixture(directory, *, steps=32, refuse_second=False):
    profile = _F18FakeV2Profile(directory, steps=steps, refuse_second=refuse_second)
    donor = {"model_state": {"same_original_donor": True}, "teacher_training": {}, "row_weight_training": {}}
    provenance = {"config": {"learning_rate": 0.001, "synthetic_metadata_only": True}}
    bindings = {"independent_bindings": True}
    return profile, donor, provenance, bindings


def test_f18_v2_fit_validates_both_recipes_before_arms_and_persists_independent_rate(tmp_path, monkeypatch):
    profile, donor, provenance, bindings = _f18_v2_fit_fixture(tmp_path)
    captured = []
    def capture(*args):
        captured.append(copy.deepcopy(args[6]))
        return [{"panel": name} for name, _, _ in worker._F18_PANELS]
    monkeypatch.setattr(worker, "_f18_capture_arm", capture)
    arms, updates, forwards, complete = worker._f18_fit_pair(c, None, profile, None, object(), donor,
        [], provenance, bindings, {}, tmp_path, learning_rate=0.003)
    assert complete is True and updates == 64 and forwards == 1264
    assert [event[0] for event in profile.recipes.events] == ["build", "validate", "build", "validate"]
    assert [event[1]["margin_weight"] for event in profile.recipes.events] == [0.0, 0.0, 0.25, 0.25]
    assert all(event[1]["donor_config"] == provenance["config"] and event[1]["expected_bindings"] == bindings
               and event[1]["learning_rate"] == 0.003 for event in profile.recipes.events)
    assert [row["learning_rate"] for row in arms] == [0.003, 0.003]
    assert all(row["donor_config_learning_rate"] == 0.001 for row in arms)
    for row, kwargs in zip(arms, captured, strict=True):
        saved = c.parse_json(c.verify(row["optimizer_recipe"]))
        assert saved == kwargs["recipe"] and kwargs["learning_rate"] == 0.003
        assert saved["donor_config"]["learning_rate"] == 0.001
        assert kwargs["expected_bindings"] == bindings
    assert provenance["config"]["learning_rate"] == 0.001


def test_f18_v2_second_recipe_refusal_creates_no_arm_or_model_stub_call(tmp_path, monkeypatch):
    profile, donor, provenance, bindings = _f18_v2_fit_fixture(tmp_path, refuse_second=True)
    monkeypatch.setattr(worker, "_f18_capture_arm", lambda *a: pytest.fail("refused recipe captured"))
    with pytest.raises(ValueError, match="second recipe"):
        worker._f18_fit_pair(c, None, profile, None, object(), donor, [], provenance, bindings,
            {}, tmp_path, learning_rate=0.003)
    assert tuple(tmp_path.iterdir()) == () and profile.events == []
    assert len(profile.recipes.events) == 4


@pytest.mark.parametrize("steps", [0, 3, 31])
def test_f18_v2_partial_arm_preserves_recipe_without_capture_second_arm_or_retry(tmp_path, monkeypatch, steps):
    profile, donor, provenance, bindings = _f18_v2_fit_fixture(tmp_path, steps=steps)
    monkeypatch.setattr(worker, "_f18_capture_arm", lambda *a: pytest.fail("partial v2 arm captured"))
    arms, updates, captures, complete = worker._f18_fit_pair(c, None, profile, None, object(), donor,
        [], provenance, bindings, {}, tmp_path, learning_rate=0.003)
    assert complete is False and updates == steps and captures == 0 and len(arms) == 1
    assert c.parse_json(c.verify(arms[0]["optimizer_recipe"]))["learning_rate"] == 0.003
    assert Path(arms[0]["checkpoint"]["path"]).is_file()
    assert len([event for event in profile.events if event[0] == "run"]) == 1
    assert not (tmp_path / "arm-025").exists()


def test_f18_v2_capture_keeps_versioned_outer_panel_and_original_joint_limits(tmp_path):
    profile = _F18FakeCaptureProfile()
    calls = []
    def select(text, scores, **kwargs):
        calls.append(dict(kwargs))
        return {"source": text, **kwargs}
    refs = worker._f18_capture_arm(c, None, profile, SimpleNamespace(select_joint_spans=select), object(), {},
        {"margin_weight": 0.25, "recipe": {"synthetic_metadata_only": True}, "learning_rate": 0.003},
        _f18_fake_panels(), tmp_path)
    assert len(refs) == 10 and len(calls) == 632
    assert all(call == {"top_k": 8, "max_search_nodes": 50000} for call in calls)
    assert all(c.parse_json(c.verify(row["raw"]))["schema"] == "f18-paired-target-free-panel/v2" for row in refs)
    assert all(c.parse_json(c.verify(row["joint"]))["schema"] == "modality-conditions-retention-joint-panel/v1" for row in refs)
    assert len([event for event in profile.events if event[0] == "capture_restore"]) == 1


@pytest.mark.parametrize("damage", [None, "missing_request_pin", "changed_profile", "changed_recipe", "foreign_root"])
def test_f18_v2_profile_selection_binds_both_owners_before_implementation(tmp_path, monkeypatch, damage):
    import hashlib
    import ipfs_datasets_py.optimizers.logic_theorem_optimizer as package
    profile_file, recipe_file = tmp_path / "profile.py", tmp_path / "recipe.py"
    profile_file.write_text("# authored profile metadata fixture\n")
    recipe_file.write_text("# authored recipe metadata fixture\n")
    profile_pin = hashlib.sha256(profile_file.read_bytes()).hexdigest()
    recipe_pin = hashlib.sha256(recipe_file.read_bytes()).hexdigest()
    checked = []
    profile = SimpleNamespace(__file__=str(profile_file), recipes=SimpleNamespace(__file__=str(recipe_file)),
                              _implementation=lambda: checked.append(True))
    monkeypatch.setattr(package, "legal_span_conditions_fullspan_training_v2", profile, raising=False)
    monkeypatch.setattr(worker, "_F18_V2_PROFILE_SHA256", profile_pin)
    monkeypatch.setattr(worker, "_F18_RECIPE_SHA256", recipe_pin)
    request = {"cwd": str(tmp_path), "source_sha256": {str(profile_file): profile_pin, str(recipe_file): recipe_pin}}
    if damage == "missing_request_pin": request["source_sha256"].pop(str(recipe_file))
    elif damage == "changed_profile": profile_file.write_text("# changed profile fixture\n")
    elif damage == "changed_recipe": recipe_file.write_text("# changed recipe fixture\n")
    elif damage == "foreign_root": request["cwd"] = str(tmp_path / "foreign")
    if damage is None:
        assert worker._f18_v2_profile(request) is profile and checked == [True]
    else:
        with pytest.raises(ValueError, match="source generation"):
            worker._f18_v2_profile(request)
        assert checked == []


def _f18_v2_fake_entry(tmp_path, monkeypatch, *, partial=False, drift=False):
    request, output, original_profile, closed = _f18_fake_entry(tmp_path, monkeypatch, partial=partial, drift=drift)
    request["schema"] = "owned-f18-conditions-training-request/v2"
    request["compute"]["learning_rate"] = 0.003
    directory = output / "f18-paired"
    numerical = _F18FakeV2Profile(directory, steps=3 if partial else 32)
    dispatch = []
    donor = {"model_state": {}, "teacher_training": {}, "row_weight_training": {}}
    provenance = {"config": {"learning_rate": 0.001}}
    def authenticate(caller, f18, profile, *args):
        assert profile is original_profile
        dispatch.append("original_authentication")
        return donor, [], provenance, {}
    def parity(*args):
        dispatch.append("v2_parity")
    def select_profile(value):
        assert value is request
        dispatch.append("v2_profile")
        return numerical
    monkeypatch.setattr(worker, "_f18_authenticate", authenticate)
    monkeypatch.setattr(worker, "_f18_parity", lambda *a: pytest.fail("v2 request borrowed v1 parity"))
    monkeypatch.setattr(worker, "_f18_v2_parity", parity)
    monkeypatch.setattr(worker, "_f18_v2_profile", select_profile)
    return request, output, original_profile, numerical, closed, dispatch


def test_f18_v2_entry_dispatches_original_authentication_and_freezes_versioned_outputs(tmp_path, monkeypatch):
    request, output, original, numerical, closed, dispatch = _f18_v2_fake_entry(tmp_path, monkeypatch)
    result = worker.run_f18_paired_training(request, output_directory=output)
    assert dispatch == ["original_authentication", "v2_parity", "v2_profile"] and original.events == []
    assert result["schema"] == "f18-paired-conditions-training-result/v2"
    assert result["completed"] is True and result["optimizer_updates"] == 64
    assert result["training_learning_rate"] == 0.003 and result["donor_config_learning_rate"] == 0.001
    assert result["profile_source_sha256"] == worker._F18_V2_PROFILE_SHA256
    assert result["optimizer_recipe_source_sha256"] == worker._F18_RECIPE_SHA256
    freeze = c.parse_json(c.verify(result["output_freeze"]))
    assert freeze["schema"] == "f18-paired-training-output-freeze/v2" and closed == [True]
    assert freeze["training_learning_rate"] == 0.003 and freeze["raw_joint_files"] == 40
    assert freeze["evaluation_gold_reference_or_comparator_bodies_opened"] == 0
    assert all(result[key] is False for key in worker._F18_FALSE)
    assert all(c.parse_json(c.verify(row["raw"]))["schema"] == "f18-paired-target-free-panel/v2"
               for arm in result["arms"] for row in arm["captures"])
    assert len(numerical.v2_kwargs) == 2


def test_f18_v2_entry_preserves_partial_and_closes_inputs_without_complete_freeze(tmp_path, monkeypatch):
    request, output, original, numerical, closed, dispatch = _f18_v2_fake_entry(tmp_path, monkeypatch, partial=True)
    result = worker.run_f18_paired_training(request, output_directory=output)
    assert result["completed"] is False and result["optimizer_updates"] == 3
    assert result["output_freeze"] is None and result["capture_source_forwards"] == 0
    assert closed == [False] and len(result["arms"]) == 1
    assert c.parse_json(c.verify(result["arms"][0]["optimizer_recipe"]))["learning_rate"] == 0.003
    assert not (output / "f18-paired/arm-025").exists()


def test_f18_v2_entry_late_input_drift_refuses_after_preserving_frozen_outputs(tmp_path, monkeypatch):
    request, output, original, numerical, closed, dispatch = _f18_v2_fake_entry(tmp_path, monkeypatch, drift=True)
    with pytest.raises(ValueError, match="changed"):
        worker.run_f18_paired_training(request, output_directory=output)
    assert closed == [True] and (output / "f18-paired/pair-output-freeze.json").is_file()
    assert len([event for event in numerical.events if event[0] == "run"]) == 2
