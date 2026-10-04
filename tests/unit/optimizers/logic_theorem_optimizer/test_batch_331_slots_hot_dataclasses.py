"""Batch 331: __slots__ checks for hot-path logic theorem dataclasses."""

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_critic import (
    CriticDimensions,
    CriticScore,
    DimensionScore,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.prover_integration import (
    AggregatedProverResult,
    ProverStatus,
    ProverVerificationResult,
)


def test_logic_critic_hot_dataclasses_use_slots():
    dim = DimensionScore(
        dimension=CriticDimensions.SOUNDNESS,
        score=0.9,
        feedback="ok",
    )
    score = CriticScore(overall=0.8, dimension_scores=[dim])

    assert "__dict__" not in dir(dim)
    assert "__dict__" not in dir(score)


def test_prover_integration_hot_dataclasses_use_slots():
    single = ProverVerificationResult(
        prover_name="z3",
        status=ProverStatus.VALID,
        is_valid=True,
        confidence=0.95,
        proof_time=0.01,
    )
    agg = AggregatedProverResult(
        overall_valid=True,
        confidence=0.95,
        prover_results=[single],
        agreement_rate=1.0,
        verified_by=["z3"],
    )

    assert "__dict__" not in dir(single)
    assert "__dict__" not in dir(agg)
