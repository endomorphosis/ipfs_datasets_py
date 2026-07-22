"""Tests for touched-row modal-autoencoder state transactions."""

from __future__ import annotations

import threading

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
    ModalAutoencoderTrainingState,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_state_transaction import (
    StaleStatePatchError,
    StateTransactionConflictError,
)


def _state() -> ModalAutoencoderTrainingState:
    return ModalAutoencoderTrainingState(
        feature_embedding_weights={
            "keep": [9.0, 8.0],
            "update": [1.0, 2.0],
            "delete": [3.0, 4.0],
        },
        feature_family_logits={"existing": {"deontic": 0.25}},
        applied_todo_ids=["todo-before"],
    )


def test_rollback_restores_rows_metadata_revision_identity_and_object() -> None:
    state = _state()
    identity_before = state.state_identity_record()
    stats_before = state.identity_stats
    state_object_id = id(state)
    table_object_id = id(state.feature_embedding_weights)
    untouched_row_id = id(state.feature_embedding_weights["keep"])

    transaction = state.transaction(label="exact-rollback").begin()
    state.feature_embedding_weights["update"][0] = 11.0
    state.feature_embedding_weights["insert"] = [5.0, 6.0]
    del state.feature_embedding_weights["delete"]
    state.applied_todo_ids.append("todo-candidate")
    state.proof_feedback_version_fingerprint = "candidate-version"

    assert transaction.touched_row_count == 3
    assert transaction.inserted_key_count == 1
    assert transaction.touched_component_count == 2
    patch = transaction.rollback()

    assert id(state) == state_object_id
    assert id(state.feature_embedding_weights) == table_object_id
    assert id(state.feature_embedding_weights["keep"]) == untouched_row_id
    assert state.feature_embedding_weights == {
        "keep": [9.0, 8.0],
        "update": [1.0, 2.0],
        "delete": [3.0, 4.0],
    }
    assert state.applied_todo_ids == ["todo-before"]
    assert state.proof_feedback_version_fingerprint == ""
    assert state.state_identity_record() == identity_before
    assert state.identity_stats == stats_before
    assert patch.touched_row_count == 3
    assert patch.inserted_key_count == 1


def test_commit_keeps_changes_and_candidate_patch_replays_exactly() -> None:
    state = _state()
    base_revision = state.state_revision

    candidate = state.transaction(label="candidate").begin()
    state.feature_embedding_weights["update"][1] = 7.5
    state.feature_family_logits["new"] = {"temporal": -0.75}
    patch = candidate.capture_patch()
    candidate_revision = state.state_revision
    candidate.rollback()

    assert state.state_revision == base_revision
    commit = state.transaction(label="commit-candidate").begin()
    patch.apply(commit)
    committed_patch = commit.commit()

    assert state.feature_embedding_weights["update"] == [1.0, 7.5]
    assert state.feature_family_logits["new"] == {"temporal": -0.75}
    assert state.state_revision == candidate_revision == patch.result_revision
    assert committed_patch.touched_row_count == 2
    assert committed_patch.inserted_key_count == 1


def test_nested_and_concurrent_writers_fail_before_mutation() -> None:
    state = _state()
    transaction = state.transaction(label="owner").begin()

    with pytest.raises(StateTransactionConflictError, match="active writer"):
        state.transaction(label="nested").begin()

    errors: list[BaseException] = []

    def conflicting_writer() -> None:
        try:
            state.feature_embedding_weights["update"][0] = 99.0
        except BaseException as exc:  # captured for assertion in the test thread
            errors.append(exc)

    thread = threading.Thread(target=conflicting_writer)
    thread.start()
    thread.join(timeout=5.0)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], StateTransactionConflictError)
    assert state.feature_embedding_weights["update"] == [1.0, 2.0]
    transaction.rollback()


def test_stale_candidate_patch_is_rejected_deterministically() -> None:
    state = _state()
    candidate = state.transaction(label="candidate").begin()
    state.feature_family_logits["existing"]["deontic"] = 1.0
    patch = candidate.capture_patch()
    candidate.rollback()

    with state.transaction(label="other-writer"):
        state.feature_embedding_weights["keep"][0] = 10.0

    replay = state.transaction(label="stale-replay").begin()
    with pytest.raises(StaleStatePatchError, match="revision conflict"):
        patch.apply(replay)
    replay.rollback()
    assert state.feature_family_logits["existing"]["deontic"] == 0.25


def test_journal_scales_with_touched_rows_and_preserves_untouched_references() -> None:
    rows = {f"row-{index}": [float(index)] for index in range(2_000)}
    state = ModalAutoencoderTrainingState(feature_embedding_weights=rows)
    table_id = id(state.feature_embedding_weights)
    untouched_ids = {
        key: id(state.feature_embedding_weights[key])
        for key in ("row-0", "row-999", "row-1999")
    }

    transaction = state.transaction().begin()
    state.feature_embedding_weights["row-1000"][0] = -1.0
    assert transaction.touched_row_count == 1
    assert transaction.touched_components == ("feature_embedding_weights",)
    transaction.rollback()

    assert id(state.feature_embedding_weights) == table_id
    assert {
        key: id(state.feature_embedding_weights[key]) for key in untouched_ids
    } == untouched_ids


def test_exceptional_context_exit_rolls_back() -> None:
    state = _state()
    identity_before = state.state_identity_record()

    with pytest.raises(RuntimeError, match="reject candidate"):
        with state.transaction(label="exceptional"):
            state.feature_embedding_weights["update"] = [100.0]
            raise RuntimeError("reject candidate")

    assert state.feature_embedding_weights["update"] == [1.0, 2.0]
    assert state.state_identity_record() == identity_before


def test_rejected_projection_uses_no_whole_state_copy_and_keeps_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder

    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall publish notice before the order takes effect.",
    )
    autoencoder = AdaptiveModalAutoencoder()
    state_id = id(autoencoder.state)
    identity_before = autoencoder.state.state_identity_record()
    payload_before = autoencoder.state.to_dict()

    def whole_state_copy_forbidden(_state: ModalAutoencoderTrainingState):
        raise AssertionError("projection attempted a whole-state copy")

    monkeypatch.setattr(ModalAutoencoderTrainingState, "copy", whole_state_copy_forbidden)
    monkeypatch.setattr(
        modal_autoencoder,
        "_evaluation_regressions_for_training",
        lambda *args, **kwargs: {"forced_guardrail_regression": 1.0},
    )

    report = autoencoder.train_generalizable_projection(
        [sample],
        validation_samples=[sample],
        legal_ir_bridge_names=(),
        epochs=1,
        max_line_search_attempts=1,
        projection_max_update_families=3,
    )

    assert report["accepted_epochs"] == 0
    assert id(autoencoder.state) == state_id
    assert autoencoder.state.to_dict() == payload_before
    assert autoencoder.state.state_identity_record() == identity_before
    assert any(
        "forced_guardrail_regression" in attempt["pareto_regressions"]
        for candidate in report["epoch_reports"][0]["candidate_reports"]
        for attempt in candidate["attempt_reports"]
    )
