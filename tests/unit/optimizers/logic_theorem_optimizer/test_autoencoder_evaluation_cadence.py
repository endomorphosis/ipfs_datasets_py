"""Evaluation cadence, lineage reuse, and promotion-safety contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_evaluation_cache import (
    DETERMINISTIC_COMPILER_STATE_HASH,
    EvaluationResultLineage,
    LegalIREvaluationResultCache,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AutoencoderEvaluation,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    uscode_modal_daemon_runner as runner,
)


def _sample(sample_id: str = "sample-1", text: str = "The agency shall report."):
    return SimpleNamespace(
        sample_id=sample_id,
        text=text,
        citation="1 USC 1",
        source="unit",
        title="1",
        section="1",
        embedding_model="unit",
        embedding_vector=[0.25, 0.75],
    )


def _evaluation(value: float = 0.2) -> AutoencoderEvaluation:
    return AutoencoderEvaluation(
        sample_count=1,
        embedding_cosine_similarity=1.0 - value,
        cosine_loss=value,
        reconstruction_loss=value,
        cross_entropy_loss=value,
        frame_ranking_loss=value,
        symbolic_validity_penalty=0.0,
        decoded_embeddings={"sample-1": [value, 1.0 - value]},
        legal_ir_target_count=1,
        legal_ir_losses={"deontic": value},
        legal_ir_target_hashes={"sample-1": "target-sha"},
        legal_ir_view_distribution={"deontic": 1.0},
    )


def _lineage(
    *,
    state_hash: str = "state-a",
    sample_id: str = "sample-1",
    use_sample_memory: bool = True,
) -> EvaluationResultLineage:
    return EvaluationResultLineage.for_samples(
        [_sample(sample_id)],
        state_hash=state_hash,
        metric_schema=runner.AUTOENCODER_DAEMON_METRIC_SCHEMA_VERSION,
        evaluator_configuration={
            "bridges": ["deontic_norms"],
            "use_sample_memory": use_sample_memory,
        },
    )


@pytest.mark.parametrize(
    ("mode", "cycle", "every", "expected"),
    [
        ("off", 4, 4, False),
        ("none", 4, 4, False),
        ("every_cycle", 1, 4, True),
        ("always", 3, 0, True),
        ("periodic", 3, 4, False),
        ("periodic", 4, 4, True),
        ("periodic", 4, 0, False),
    ],
)
def test_cycle_cadence_modes_control_execution(
    mode: str,
    cycle: int,
    every: int,
    expected: bool,
) -> None:
    assert runner._should_run_cycle_cadence(
        cycle=cycle,
        mode=mode,
        every_n_cycles=every,
    ) is expected


def test_prior_after_result_is_deeply_immutable_and_exact_lineage_only() -> None:
    cache = LegalIREvaluationResultCache(max_entries=2)
    source = _evaluation()
    artifact = cache.put_after(
        _lineage(),
        source,
        role="after_train",
        cycle=1,
        computation_seconds=0.75,
    )

    source.decoded_embeddings["sample-1"][0] = 99.0
    with pytest.raises(TypeError):
        artifact.payload["decoded_embeddings"]["sample-1"] = [1.0]  # type: ignore[index]

    reused = cache.get_before(
        _lineage(),
        AutoencoderEvaluation,
        role="before_train",
        current_cycle=2,
    )
    assert reused is not None
    assert reused.decoded_embeddings["sample-1"][0] == pytest.approx(0.2)
    reused.decoded_embeddings["sample-1"][0] = 88.0
    repeated = cache.get_before(
        _lineage(),
        AutoencoderEvaluation,
        role="before_train",
        current_cycle=3,
    )
    assert repeated is not None
    assert repeated.decoded_embeddings["sample-1"][0] == pytest.approx(0.2)

    assert cache.get_before(
        _lineage(state_hash="state-b"),
        AutoencoderEvaluation,
        role="before_train",
        current_cycle=2,
    ) is None
    assert cache.get_before(
        _lineage(sample_id="other"),
        AutoencoderEvaluation,
        role="before_train",
        current_cycle=2,
    ) is None
    assert cache.get_before(
        _lineage(use_sample_memory=False),
        AutoencoderEvaluation,
        role="before_train",
        current_cycle=2,
    ) is None
    assert cache.summary()["saved_wall_time_seconds"] == pytest.approx(1.5)


def test_same_cycle_or_before_role_cannot_seed_reuse() -> None:
    cache = LegalIREvaluationResultCache()
    cache.put_after(_lineage(), _evaluation(), role="after_validation", cycle=2)
    assert cache.get_before(
        _lineage(),
        AutoencoderEvaluation,
        role="before_validation",
        current_cycle=2,
    ) is None
    with pytest.raises(ValueError, match="only after-evaluations"):
        cache.put_after(_lineage(), _evaluation(), role="before_train", cycle=2)


def test_before_train_uses_core_pass_off_cadence_and_full_pass_when_due() -> None:
    cache = LegalIREvaluationResultCache()
    calls = {"core": 0, "full": 0}

    def core() -> AutoencoderEvaluation:
        calls["core"] += 1
        return _evaluation(0.4)

    def full() -> AutoencoderEvaluation:
        calls["full"] += 1
        return _evaluation(0.3)

    skipped, skipped_control = runner.evaluate_autoencoder_before_train_with_cadence(
        cycle=3,
        mode="periodic",
        every_n_cycles=4,
        lineage=_lineage(),
        result_cache=cache,
        full_family_evaluator=full,
        core_evaluator=core,
    )
    assert skipped.cross_entropy_loss == pytest.approx(0.4)
    assert skipped_control["full_family"] is False
    assert skipped_control["skipped_expensive_full_family_pass"] is True
    assert calls == {"core": 1, "full": 0}

    due, due_control = runner.evaluate_autoencoder_before_train_with_cadence(
        cycle=4,
        mode="periodic",
        every_n_cycles=4,
        lineage=_lineage(state_hash="state-b"),
        result_cache=cache,
        full_family_evaluator=full,
        core_evaluator=core,
    )
    assert due.cross_entropy_loss == pytest.approx(0.3)
    assert due_control["full_family"] is True
    assert calls == {"core": 1, "full": 1}


def test_lineage_matched_after_result_wins_without_any_execution() -> None:
    cache = LegalIREvaluationResultCache()
    cache.put_after(_lineage(), _evaluation(0.1), role="after_train", cycle=1)

    def unexpected() -> AutoencoderEvaluation:
        raise AssertionError("a lineage-matched result should be reused")

    result, control = runner.evaluate_autoencoder_before_train_with_cadence(
        cycle=2,
        mode="every_cycle",
        every_n_cycles=1,
        lineage=_lineage(),
        result_cache=cache,
        full_family_evaluator=unexpected,
        core_evaluator=unexpected,
    )
    assert result.cross_entropy_loss == pytest.approx(0.1)
    assert control["reused"] is True
    assert control["full_family"] is True
    assert control["executed"] is False


def test_unguided_compiler_artifact_digest_ignores_autoencoder_state() -> None:
    codec = SimpleNamespace(config=SimpleNamespace(parser_backend="unit"))
    common = {
        "sample": _sample(),
        "codec": codec,
        "compiler_guidance": None,
        "use_autoencoder_guidance": False,
        "guidance_top_k": 16,
        "compiler_commit": "compiler-a",
        "metric_schema": "metric-a",
        "config_hash": "",
    }
    first = runner._legal_ir_evaluation_key(state_hash="state-a", **common)
    second = runner._legal_ir_evaluation_key(state_hash="state-b", **common)
    assert first == second
    assert first.state_hash == DETERMINISTIC_COMPILER_STATE_HASH

    guided_a = runner._legal_ir_evaluation_key(
        **{
            **common,
            "compiler_guidance": {"family": "deontic"},
            "use_autoencoder_guidance": True,
            "state_hash": "state-a",
        }
    )
    guided_b = runner._legal_ir_evaluation_key(
        **{
            **common,
            "compiler_guidance": {"family": "deontic"},
            "use_autoencoder_guidance": True,
            "state_hash": "state-b",
        }
    )
    assert guided_a.digest != guided_b.digest


def test_reduced_before_baseline_is_never_reused_for_candidate_acceptance() -> None:
    evaluation = _evaluation()
    train, validation = runner._todo_supervisor_precomputed_evaluations(
        feature_projection_report={},
        train_samples=[_sample()],
        validation_samples=[_sample()],
        before_train=evaluation,
        before_validation=evaluation,
        before_train_full_family=False,
    )
    assert train is None
    assert validation is evaluation


def test_skipped_compiler_train_block_is_explicitly_non_promotional() -> None:
    block = runner.skipped_compiler_train_metric_block(
        cycle=3,
        mode="periodic",
        every_n_cycles=4,
        evaluation_role="guided_train",
        sample_count=8,
    )
    assert block["skipped"] is True
    assert block["full_family_gates_required"] is False
    assert block["sample_count"] == 8
    assert block["evaluated_count"] == 0

