"""Tests for typed exception handling paths in LogicCritic."""

from __future__ import annotations

from types import SimpleNamespace

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_critic import LogicCritic


class _FailingProver:
    def prove(self, formula, timeout=5.0):
        raise ValueError("prove failed")


class _BadConfidenceStatement:
    formula = "Must(SubmitReport(Alice))"

    @property
    def confidence(self):
        raise ValueError("bad confidence")


class _FailingAdapter:
    def verify_statement(self, statement):
        raise ValueError("verification failed")

    def get_statistics(self):
        return {"cache_hits": 0, "cache_hit_rate": 0.0}


def _extraction(statements):
    return SimpleNamespace(
        statements=statements,
        context=SimpleNamespace(data="Alice must submit report"),
        ontology_alignment={},
    )


def test_evaluate_soundness_legacy_prover_error_is_non_fatal() -> None:
    critic = LogicCritic(enable_prover_integration=False)
    critic.provers = {"bad": _FailingProver()}

    extraction_result = _extraction([_BadConfidenceStatement()])
    score = critic._evaluate_soundness(extraction_result)

    assert score.score == 0.0
    assert score.dimension.value == "soundness"


def test_evaluate_soundness_with_adapter_error_is_non_fatal() -> None:
    critic = LogicCritic(enable_prover_integration=False)
    critic.prover_adapter = _FailingAdapter()

    extraction_result = _extraction(
        [SimpleNamespace(formula="Must(SubmitReport(Alice))", confidence=0.9)]
    )
    score = critic._evaluate_soundness(extraction_result)

    assert score.score == 0.0
    assert "soundness" == score.dimension.value
