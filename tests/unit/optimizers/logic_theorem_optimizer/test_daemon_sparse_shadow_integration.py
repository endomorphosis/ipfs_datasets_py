"""Endpoint replay of actual daemon persistence with synthetic mutation sources.

These fixtures exercise native state/compaction/checkpoint code and actual runner
orchestration. Their model, corpus and late writes are explicitly synthetic;
they do not qualify native learning, supervisor acceptance or trusted guidance.
The full final checkpoint remains authoritative throughout the shadow check.
"""

import hashlib
import math

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_modal_daemon_runner as runner
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_observation import observation_session
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import (
    CHECKPOINT_MAGIC, deserialize_checkpoint, load_checkpoint, serialize_checkpoint,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_patch_codec import decode_patch, replay_patch
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_state_diff import (
    capture_endpoint_patch, exact_state_snapshot,
)
from tests.unit.optimizers.logic_theorem_optimizer.test_daemon_shared_target_integration import actual_run
from tests.unit.optimizers.logic_theorem_optimizer.test_daemon_corpus_input_integration import corpus_run
from tests.unit.optimizers.logic_theorem_optimizer.test_daemon_owned_observation_integration import _main


BINDING = {"request_sha256": "a" * 64, "launch_sha256": "b" * 64}


def _seed_registered_base(case, state):
    """Preserve original bytes separately from the runner's mutable state path."""
    raw = serialize_checkpoint(state, metadata={"reason": "synthetic_registered_base"})
    base_path = case.root / "registered-base.compact"
    base_path.write_bytes(raw)
    state_path = case.root / "workspace/todo-queues" / f"{case.args.run_id}.state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_bytes(raw)
    return base_path, state_path, raw


def _run(case, monkeypatch):
    with observation_session(binding=BINDING) as collector:
        assert _main(case, monkeypatch) == 0
    receipt = collector.to_dict()
    assert receipt["success"] and receipt["closed"]
    assert all(writer._closed for writer in case.seen.writers)
    return {row["phase"]: row for row in receipt["events"] if row["kind"] == "state"}


def _assert_complete_shadow(case, base_path, state_path, original_base_bytes):
    base = load_checkpoint(base_path, recover=False).state
    final_bytes = state_path.read_bytes()
    final = load_checkpoint(state_path, recover=False)
    assert final_bytes.startswith(CHECKPOINT_MAGIC)
    assert final.manifest.metadata["reason"] == "clean_shutdown"
    assert final.manifest.metadata["daemon_invocation"] == BINDING
    base_before, final_before = exact_state_snapshot(base), exact_state_snapshot(final.state)
    version = "sha256:" + hashlib.sha256(original_base_bytes).hexdigest()
    endpoint = capture_endpoint_patch(
        base, final.state, base_version_id=version,
        provenance={"scope": "synthetic_daemon_endpoint_shadow", **BINDING},
    )
    assert endpoint.report["base_snapshot"] == base_before
    assert endpoint.report["result_snapshot"] == final_before
    assert exact_state_snapshot(base) == base_before
    assert exact_state_snapshot(final.state) == final_before

    replayed = load_checkpoint(base_path, recover=False).state
    replay = replay_patch(replayed, endpoint.data, expected_base_version_id=version,
                          expected_sequence=0)
    snapshot = exact_state_snapshot(replayed)
    assert snapshot == final_before
    assert snapshot["component_count"] == 38
    assert snapshot["component_fields"] == list(MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS)
    assert set(snapshot["components"]) == set(MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS)
    assert replayed.to_json() == final.state.to_json()
    assert replayed.state_revision == final.state.state_revision == final.manifest.revision
    assert replay["admitted"] is False

    # The shadow also survives the same native float64 compact transport without
    # replacing the authoritative daemon file or normalizing its revision.
    round_trip = deserialize_checkpoint(serialize_checkpoint(
        replayed, metadata=final.manifest.metadata,
    ))
    assert exact_state_snapshot(round_trip.state) == final_before
    assert round_trip.state.to_json() == final.state.to_json()
    assert round_trip.manifest.revision == final.manifest.revision
    assert base_path.read_bytes() == original_base_bytes
    assert state_path.read_bytes() == final_bytes
    persistence = case.summary()["final_state_persistence"]
    assert persistence["durable"] is True
    assert persistence["checksum"] == hashlib.sha256(final_bytes).hexdigest()
    assert persistence["checkpoint_revision"] == replayed.state_revision
    return endpoint, final, snapshot


def test_shadow_covers_real_startup_compaction_and_synthetic_late_metadata_and_deletions(corpus_run, monkeypatch):
    case = corpus_run
    case.args.autoencoder_max_generalizable_entries_per_group = 1
    base = runner.ModalAutoencoderTrainingState(
        feature_embedding_weights={"low": [0.25], "middle": [0.5], "keep": [0.75]},
        feature_family_logits={"low": {"deontic": 0.25}, "middle": {"deontic": 0.5}, "keep": {"deontic": 0.75}},
        decoded_embeddings={"remove-memory": [1.0], "keep-memory": [0.25]},
        legal_ir_view_logits={"bias": 0.0},
        applied_todo_ids=["prior-todo"],
    )
    base_path, state_path, original = _seed_registered_base(case, base)
    original_guidance = runner.project_verified_leanstral_guidance_artifacts_into_queue

    def synthetic_late_mutations(**kwargs):
        result = original_guidance(**kwargs)
        state = kwargs["autoencoder"].state
        # Deliberate test writes after evaluation, not genuine guidance/TODO
        # acceptance. Retain duplicate/order semantics of all applied-ID lists.
        state.applied_todo_ids.extend(["synthetic-todo", "synthetic-todo"])
        state.applied_leanstral_guidance_ids.append("synthetic-guidance")
        state.applied_proof_feedback_ids.extend(["synthetic-proof-b", "synthetic-proof-a"])
        state.proof_feedback_version_fingerprint = "synthetic-proof-version"
        state.legal_ir_view_logits["bias"] = -0.0
        del state.decoded_embeddings["remove-memory"]
        state.decoded_embeddings["new-empty-memory"] = []
        return result

    monkeypatch.setattr(runner, "project_verified_leanstral_guidance_artifacts_into_queue",
                        synthetic_late_mutations)
    events = _run(case, monkeypatch)
    endpoint, final, _ = _assert_complete_shadow(case, base_path, state_path, original)
    assert events["registered_base"]["state_identity"] == base.state_identity_record().to_dict()
    assert events["startup_complete"]["state_identity"] != events["registered_base"]["state_identity"]
    assert events["before_after_validation_evaluation"]["state_identity"] != events["completed_cycle"]["state_identity"]
    assert events["final_shutdown"]["state_identity"] == final.state.state_identity_record().to_dict()
    assert set(final.state.feature_embedding_weights) == set(final.state.feature_family_logits) == {"keep"}
    assert "remove-memory" not in final.state.decoded_embeddings
    assert final.state.decoded_embeddings["new-empty-memory"] == []
    assert final.state.applied_todo_ids == ["prior-todo", "synthetic-todo", "synthetic-todo"]
    assert final.state.applied_leanstral_guidance_ids == ["synthetic-guidance"]
    assert final.state.applied_proof_feedback_ids == ["synthetic-proof-b", "synthetic-proof-a"]
    assert math.copysign(1.0, final.state.legal_ir_view_logits["bias"]) == -1
    assert endpoint.report["counts"]["deleted_rows"] >= 5
    assert {"applied_todo_ids", "applied_leanstral_guidance_ids", "applied_proof_feedback_ids",
            "proof_feedback_version_fingerprint", "legal_ir_view_logits"} <= set(endpoint.report["changed_components"])
    assert case.seen.checkpoint_writes[0]["metadata"]["reason"] == "bounded_startup_state"


def test_shadow_includes_distinct_real_final_compaction_after_synthetic_shutdown_write(corpus_run, monkeypatch):
    case = corpus_run
    case.args.autoencoder_max_generalizable_entries_per_group = 2
    base = runner.ModalAutoencoderTrainingState(
        feature_embedding_weights={"drop-at-shutdown": [0.25], "keep": [0.5]},
        feature_family_logits={"drop-at-shutdown": {"deontic": 0.25}, "keep": {"deontic": 0.5}},
    )
    base_path, state_path, original = _seed_registered_base(case, base)
    state_holder = {}
    original_guidance = runner.project_verified_leanstral_guidance_artifacts_into_queue
    original_guard = runner._daemon_verify_corpus

    def retain_fixture_state(**kwargs):
        state_holder["state"] = kwargs["autoencoder"].state
        return original_guidance(**kwargs)

    def synthetic_shutdown_write(context, phase, **kwargs):
        result = original_guard(context, phase, **kwargs)
        if phase == "shutdown":
            state = state_holder["state"]
            assert not state.generalizable_capacity_exceeded(2)
            state.feature_embedding_weights["synthetic-late-high"] = [4.0]
            state.feature_family_logits["synthetic-late-high"] = {"deontic": 4.0}
            state_holder["before_final_compaction"] = exact_state_snapshot(state)
        return result

    monkeypatch.setattr(runner, "project_verified_leanstral_guidance_artifacts_into_queue", retain_fixture_state)
    # Exercise the defensive shutdown branch without asserting an ordinary
    # async evaluator is allowed to mutate live state: this write is synthetic.
    monkeypatch.setattr(runner, "_daemon_verify_corpus", synthetic_shutdown_write)
    events = _run(case, monkeypatch)
    endpoint, final, snapshot = _assert_complete_shadow(case, base_path, state_path, original)
    assert events["startup_complete"]["state_identity"] == events["registered_base"]["state_identity"]
    assert events["completed_cycle"]["state_identity"] != events["final_shutdown"]["state_identity"]
    assert state_holder["before_final_compaction"] != snapshot
    assert set(final.state.feature_embedding_weights) == set(final.state.feature_family_logits) == {"keep", "synthetic-late-high"}
    capacity = case.summary()["latest_autoencoder_generalizable_capacity"]
    assert capacity["reason"] == "clean_shutdown" and capacity["compacted"] is True
    assert case.summary()["autoencoder_generalizable_capacity_compactions_total"] == 1
    segment = decode_patch(endpoint.data)
    deletions = {(row.component, row.key) for row in segment.patch.rows if not row.after_exists}
    assert {("feature_embedding_weights", "drop-at-shutdown"),
            ("feature_family_logits", "drop-at-shutdown")} <= deletions
    assert not any(row["metadata"].get("reason") == "bounded_startup_state" for row in case.seen.checkpoint_writes)


def test_zero_update_shadow_keeps_full_final_checkpoint_authoritative(corpus_run, monkeypatch):
    case = corpus_run
    case.args.generalizable_projection_epochs = 0
    base = runner.ModalAutoencoderTrainingState(applied_todo_ids=["prior-only"])
    base_path, state_path, original = _seed_registered_base(case, base)
    events = _run(case, monkeypatch)
    endpoint, final, _ = _assert_complete_shadow(case, base_path, state_path, original)
    assert events["registered_base"]["state_identity"] == events["final_shutdown"]["state_identity"]
    assert endpoint.report["changed_components"] == []
    assert endpoint.report["counts"]["touched_row_count"] == endpoint.report["counts"]["touched_component_count"] == 0
    assert final.state.applied_todo_ids == ["prior-only"]
    assert case.seen.projections == []
