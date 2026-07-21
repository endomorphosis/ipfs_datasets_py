from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Sequence

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
    ModalAutoencoderTrainingState,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.snapshot_evaluator import (
    EvaluationSnapshot,
    SnapshotBoundary,
    SnapshotEvaluator,
    SnapshotShardEvidence,
    SnapshotVersions,
    aggregate_matching_snapshot_shards,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner import (
    PRODUCTION_SNAPSHOT_REQUIRED_ROLES,
    build_autoencoder_evaluation_snapshot,
    evaluate_production_snapshot_bundle,
)


def _sample(title: str, section: str, text: str) -> Any:
    sample = build_us_code_sample(title=title, section=section, text=text)
    # The production sharder accepts explicit family hints where upstream LegalIR
    # target extraction has already supplied them.
    return replace(sample, losses={"deontic": 0.1, "temporal": 0.2})


def test_production_snapshot_bundle_is_complete_and_version_matched() -> None:
    train = [
        _sample("5", "552", "The agency shall provide notice within 30 days."),
        _sample("7", "136", "The Secretary may define eligible applicants."),
    ]
    validation = [
        _sample("8", "1101", "The applicant must file before the deadline."),
    ]
    state = ModalAutoencoderTrainingState(
        decoded_embeddings={train[0].sample_id: [0.1, 0.2, 0.3]}
    )
    trainer = AdaptiveModalAutoencoder(state=state, compute_device="python")
    snapshot = build_autoencoder_evaluation_snapshot(
        trainer.state,
        sequence=11,
        compiler_version="compiler-prod",
        holdout_sample_ids=[sample.sample_id for sample in validation],
        validation_mode="fixed_canary",
    )

    trainer.state.decoded_embeddings[train[0].sample_id][0] = 99.0
    compiler_state_hashes: list[str] = []

    def fake_compiler_metric(
        rows: Sequence[Any],
        feature_codec: Any,
        **kwargs: Any,
    ) -> Mapping[str, Any]:
        del feature_codec
        compiler_state_hashes.append(str(kwargs["state_hash"]))
        guided = bool(kwargs.get("use_autoencoder_guidance"))
        return {
            "autoencoder_guidance_applied_count": len(rows) if guided else 0,
            "autoencoder_guidance_enabled": guided,
            "cosine_similarity": 0.8 if guided else 0.5,
            "cross_entropy_loss": 0.2 if guided else 0.5,
            "evaluation_role": kwargs["evaluation_role"],
            "sample_count": len(rows),
            "source_copy_reward_hack_penalty": 0.01 if guided else 0.05,
        }

    def fake_proof_metric(row: Any) -> Mapping[str, Any]:
        return {
            "attempted_count": 1,
            "error_count": 0,
            "failed_count": 0,
            "sample_id": row.sample_id,
            "unavailable_count": 0,
            "valid_count": 1,
        }

    bundle = evaluate_production_snapshot_bundle(
        snapshot,
        trainer,
        train_rows=train,
        validation_rows=validation,
        validation_mode="fixed_canary",
        feature_codec=trainer.feature_codec,
        compiler_metric_fn=fake_compiler_metric,
        proof_metric_fn=fake_proof_metric,
    )

    aggregate = bundle["aggregate"]
    assert aggregate["complete"] is True
    assert bundle["snapshot_complete"] is True
    assert bundle["promotion"]["snapshot_complete"] is True
    assert aggregate["missing_roles"] == []
    assert set(PRODUCTION_SNAPSHOT_REQUIRED_ROLES).issubset(
        set(aggregate["roles_present"])
    )
    assert bundle["promotion"]["gate"]["promotion_allowed"] is True
    assert set(compiler_state_hashes) == {snapshot.versions.state_version}
    assert all(
        shard["versions"] == snapshot.versions.to_dict()
        for shard in bundle["shards"]
    )
    assert aggregate["metrics_by_role"]["train"]["all"]["sample_count"] == 2
    assert aggregate["metrics_by_role"]["validation"]["all"]["sample_count"] == 1


def test_matching_snapshot_shard_aggregation_rejects_mismatched_versions() -> None:
    expected = SnapshotVersions(
        "state-a",
        "compiler-a",
        "holdout-a",
        "schema-a",
    )
    mismatched = SnapshotVersions(
        "state-b",
        "compiler-a",
        "holdout-a",
        "schema-a",
    )
    aggregate = aggregate_matching_snapshot_shards(
        [
            SnapshotShardEvidence(3, expected, "train", "deontic", {"loss": 0.1}),
            SnapshotShardEvidence(3, mismatched, "validation", "deontic", {"loss": 0.2}),
        ],
        expected,
        expected_sequence=3,
        required_roles=("train", "validation"),
    )

    assert aggregate.complete is False
    assert aggregate.roles_present == ("train",)
    assert aggregate.missing_roles == ("validation",)
    assert len(aggregate.rejected_shards) == 1
    assert aggregate.rejected_shards[0].mismatch_fields == ("state_version",)


def test_snapshot_summary_exposes_production_queue_health_and_promotion_state() -> None:
    snapshot = EvaluationSnapshot.from_state_json(
        {"value": 1},
        sequence=1,
        compiler_version="compiler-a",
        holdout_version="holdout-a",
        schema_version="schema-a",
    )
    evaluator = SnapshotEvaluator(
        lambda item: {"aggregate": {"complete": True}, "sequence": item.sequence},
        queue_capacity=1,
    )
    try:
        evaluator.publish(snapshot)
        result = evaluator.wait_for_result(timeout=1.0)
        assert result is not None
        assert evaluator.accept_result(
            result,
            snapshot.versions,
            expected_sequence=snapshot.sequence,
        )
        promotion = evaluator.promote_at_boundary(SnapshotBoundary.for_snapshot(snapshot))
        assert promotion.promoted is True

        summary = evaluator.summary()
        assert summary["queue_depth"] == summary["pending_count"]
        assert summary["staleness_seconds"] >= 0.0
        assert summary["dropped_work_count"] == summary["dropped_snapshot_count"]
        assert summary["evaluator_health"]["ready_result_count"] == 0
        assert summary["snapshot_complete_promotion_state"]["complete"] is True
        assert summary["snapshot_complete_promotion_state"][
            "latest_promoted_sequence"
        ] == 1
    finally:
        evaluator.close(cancel_pending=True)
