from __future__ import annotations

import dataclasses
import threading
import time

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
    ModalAutoencoderTrainingState,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.snapshot_evaluator import (
    EvaluationSnapshot,
    SnapshotBackpressureTimeout,
    SnapshotBoundary,
    SnapshotEvaluationResult,
    SnapshotEvaluator,
    SnapshotVersions,
    canonical_holdout_version,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner import (
    AUTOENCODER_DAEMON_METRIC_SCHEMA_VERSION,
    autoencoder_for_evaluation_snapshot,
    build_uscode_modal_daemon_arg_parser,
    build_autoencoder_evaluation_snapshot,
)


def snapshot(sequence: int, *, state_value: int | None = None) -> EvaluationSnapshot:
    return EvaluationSnapshot.from_state_json(
        {"value": sequence if state_value is None else state_value},
        sequence=sequence,
        compiler_version="compiler-a",
        holdout_version="holdout-a",
        schema_version="schema-a",
    )


def test_snapshot_is_an_immutable_serialized_state_copy() -> None:
    source = {"weights": [1.0, 2.0]}
    item = EvaluationSnapshot.from_state_json(
        source,
        sequence=7,
        compiler_version="compiler-a",
        holdout_version="holdout-a",
    )

    source["weights"].append(99.0)
    decoded = item.state_json()
    decoded["weights"].append(3.0)

    assert item.state_json() == {"weights": [1.0, 2.0]}
    assert item.snapshot_id.startswith("7:")
    with pytest.raises(TypeError):
        item.metadata["changed"] = True  # type: ignore[index]


def test_publish_does_not_wait_and_full_queue_explicitly_coalesces_unevaluated() -> None:
    evaluation_started = threading.Event()
    release_evaluation = threading.Event()

    def evaluate(item: EvaluationSnapshot) -> dict[str, int]:
        evaluation_started.set()
        assert release_evaluation.wait(2.0)
        return {"sequence": item.sequence}

    evaluator = SnapshotEvaluator(evaluate, queue_capacity=2)
    try:
        started = time.monotonic()
        assert evaluator.publish(snapshot(0)) == ()
        assert time.monotonic() - started < 0.2
        assert evaluation_started.wait(1.0)

        evaluator.publish(snapshot(1))
        evaluator.publish(snapshot(2))
        drops = evaluator.publish(snapshot(3))

        assert len(drops) == 1
        assert drops[0].dropped_sequence == 1
        assert drops[0].replacement_sequence == 3
        assert drops[0].reason == "superseded_unevaluated_snapshot"
        assert evaluator.pending_count == 2
        assert evaluator.summary()["dropped_snapshot_count"] == 1
        assert evaluator.summary()["pending_count"] <= evaluator.queue_capacity
    finally:
        release_evaluation.set()
        assert evaluator.wait_until_idle(2.0)
        evaluator.close()


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("state_version", "state-b"),
        ("compiler_version", "compiler-b"),
        ("holdout_version", "holdout-b"),
        ("schema_version", "schema-b"),
    ],
)
def test_result_acceptance_requires_every_version_dimension(
    field: str,
    replacement: str,
) -> None:
    expected = SnapshotVersions("state-a", "compiler-a", "holdout-a", "schema-a")
    actual = dataclasses.replace(expected, **{field: replacement})
    result = SnapshotEvaluationResult(4, actual, {"loss": 0.1})
    evaluator = SnapshotEvaluator(lambda _: {}, autostart=False)
    try:
        assert not evaluator.accept_result(result, expected, expected_sequence=4)
        rejection = evaluator.rejected_results[-1]
        assert rejection.reason == "version_mismatch"
        assert rejection.mismatch_fields == (field,)
    finally:
        evaluator.close(cancel_pending=True)


def test_failed_and_wrong_boundary_results_cannot_be_promoted() -> None:
    versions = SnapshotVersions("state-a", "compiler-a", "holdout-a", "schema-a")
    result = SnapshotEvaluationResult(5, versions, {"loss": 0.1})
    failed = SnapshotEvaluationResult(5, versions, error="evaluation failed")
    evaluator = SnapshotEvaluator(lambda _: {}, autostart=False)
    promoted: list[float] = []
    try:
        assert not evaluator.accept_result(failed, versions, expected_sequence=5)
        assert evaluator.accept_result(result, versions, expected_sequence=5)

        wrong = evaluator.promote_at_boundary(
            SnapshotBoundary(6, versions),
            promote=lambda evidence: promoted.append(float(evidence.metrics["loss"])),
        )
        assert not wrong.promoted
        assert promoted == []

        decision = evaluator.promote_at_boundary(
            SnapshotBoundary(5, versions),
            promote=lambda evidence: promoted.append(float(evidence.metrics["loss"])),
        )
        assert decision.promoted
        assert decision.reason == "promoted_at_snapshot_boundary"
        assert promoted == [0.1]

        # Accepted evidence is single-use; a later non-boundary poll cannot
        # accidentally promote it a second time.
        assert not evaluator.promote_at_boundary(SnapshotBoundary(5, versions)).promoted
    finally:
        evaluator.close(cancel_pending=True)


def test_backpressure_pauses_next_training_step_until_evidence_finishes() -> None:
    evaluation_started = threading.Event()
    release_evaluation = threading.Event()
    trainer_released = threading.Event()
    waits: list[float] = []

    def evaluate(_: EvaluationSnapshot) -> dict[str, float]:
        evaluation_started.set()
        assert release_evaluation.wait(2.0)
        return {"loss": 0.2}

    evaluator = SnapshotEvaluator(
        evaluate,
        queue_capacity=1,
        max_evidence_lag=1,
    )
    try:
        evaluator.publish(snapshot(0))
        assert evaluation_started.wait(1.0)

        def trainer_gate() -> None:
            waits.append(
                evaluator.before_training_step(next_sequence=2, timeout=1.5)
            )
            trainer_released.set()

        trainer = threading.Thread(target=trainer_gate)
        trainer.start()
        assert not trainer_released.wait(0.05)
        assert evaluator.backpressure_reason(next_sequence=2) == "evidence_version_lag"

        release_evaluation.set()
        assert trainer_released.wait(1.0)
        trainer.join()
        assert waits[0] >= 0.04
        assert evaluator.summary()["backpressure_waits"] == 1
    finally:
        release_evaluation.set()
        evaluator.close()


def test_backpressure_timeout_fails_closed() -> None:
    release = threading.Event()

    def evaluate(_: EvaluationSnapshot) -> dict[str, float]:
        release.wait(1.0)
        return {}

    evaluator = SnapshotEvaluator(evaluate, queue_capacity=1, max_evidence_lag=1)
    try:
        evaluator.publish(snapshot(0))
        with pytest.raises(SnapshotBackpressureTimeout):
            evaluator.before_training_step(next_sequence=2, timeout=0.02)
    finally:
        release.set()
        evaluator.close()


def test_daemon_snapshot_uses_canonical_state_and_cpu_evaluator_clone() -> None:
    state = ModalAutoencoderTrainingState(
        decoded_embeddings={"train-row": [0.1, 0.2]},
        applied_todo_ids=["todo-1"],
    )
    trainer = AdaptiveModalAutoencoder(state=state, compute_device="python")
    item = build_autoencoder_evaluation_snapshot(
        state,
        sequence=9,
        compiler_version="compiler-commit",
        holdout_sample_ids=["held-1", "held-2"],
        validation_mode="fixed_canary",
    )

    state.decoded_embeddings["train-row"][0] = 99.0
    evaluator = autoencoder_for_evaluation_snapshot(item, trainer)

    assert evaluator is not trainer
    assert evaluator.state is not trainer.state
    assert evaluator.state.decoded_embeddings["train-row"] == [0.1, 0.2]
    assert evaluator.compute_device_request == "cpu"
    assert item.versions.holdout_version == canonical_holdout_version(
        ["held-1", "held-2"],
        validation_mode="fixed_canary",
    )
    assert item.versions.schema_version == AUTOENCODER_DAEMON_METRIC_SCHEMA_VERSION


def test_constructor_rejects_invalid_bounds() -> None:
    with pytest.raises(ValueError, match="queue_capacity"):
        SnapshotEvaluator(lambda _: {}, queue_capacity=0)
    with pytest.raises(ValueError, match="max_evidence_lag"):
        SnapshotEvaluator(lambda _: {}, max_evidence_lag=0)
    with pytest.raises(ValueError, match="max_evidence_age_seconds"):
        SnapshotEvaluator(lambda _: {}, max_evidence_age_seconds=-1)


def test_daemon_exposes_bounded_queue_and_backpressure_controls() -> None:
    args = build_uscode_modal_daemon_arg_parser().parse_args(
        [
            "--run-id",
            "snapshot-runtime",
            "--snapshot-evaluation-enabled",
            "true",
            "--snapshot-evaluation-queue-capacity",
            "3",
            "--snapshot-evaluation-max-lag",
            "4",
            "--snapshot-evaluation-max-age-seconds",
            "12.5",
            "--snapshot-evaluation-backpressure-timeout-seconds",
            "7.5",
        ]
    )

    assert args.snapshot_evaluation_enabled is True
    assert args.snapshot_evaluation_queue_capacity == 3
    assert args.snapshot_evaluation_max_lag == 4
    assert args.snapshot_evaluation_max_age_seconds == pytest.approx(12.5)
    assert args.snapshot_evaluation_backpressure_timeout_seconds == pytest.approx(7.5)
