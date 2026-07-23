"""Smoke test for the unified logic theorem optimizer."""

import logging
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.common.base_optimizer import (
    BaseOptimizer,
    OptimizerConfig,
    OptimizationContext,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    LogicTheoremOptimizer,
    SessionConfig,
    TheoremSession,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_extractor import (
    DataType,
    ExtractionMode,
    ExtractionResult,
    LogicExtractionContext,
    LogicalStatement,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_critic import (
    CriticDimensions,
    CriticScore,
    DimensionScore,
)
from ipfs_datasets_py.optimizers.common.extraction_contexts import LogicExtractionConfig


def test_logic_theorem_optimizer_run_session_smoke(monkeypatch):
    config = OptimizerConfig(
        max_iterations=1,
        target_score=0.9,
        early_stopping=False,
        validation_enabled=False,
        metrics_enabled=False,
    )
    optimizer = LogicTheoremOptimizer(config=config, llm_backend=object())

    extraction_context = LogicExtractionContext(
        data="All employees must complete training.",
        data_type=DataType.TEXT,
        domain="general",
        config=LogicExtractionConfig(extraction_mode=ExtractionMode.FOL)
    )
    extraction_result = ExtractionResult(
        statements=[
            LogicalStatement(
                formula="Employee(x) -> Completed(x, training)",
                natural_language="Employees complete training.",
                confidence=0.8,
                formalism="fol",
            )
        ],
        context=extraction_context,
        success=True,
    )

    extract_calls = []

    def fake_extract(ctx):
        extract_calls.append(ctx)
        return extraction_result

    def fake_evaluate(artifact):
        return CriticScore(
            overall=0.6,
            dimension_scores=[
                DimensionScore(
                    dimension=CriticDimensions.SOUNDNESS,
                    score=0.6,
                    feedback="Needs stronger guarantees.",
                )
            ],
            strengths=["Clear structure"],
            weaknesses=["Missing edge cases"],
            recommendations=["Add constraints"],
        )

    monkeypatch.setattr(optimizer.extractor, "extract", fake_extract)
    monkeypatch.setattr(optimizer.critic, "evaluate", fake_evaluate)

    context = OptimizationContext(
        session_id="logic-smoke-1",
        input_data=extraction_context.data,
        domain="general",
    )

    result = optimizer.run_session(extraction_context.data, context)

    assert result["artifact"] is extraction_result
    assert result["score"] == pytest.approx(0.6)
    assert result["valid"] is True
    assert len(extract_calls) == 2


def test_base_optimizer_early_stopping_allows_first_refinement() -> None:
    class FlatOptimizer(BaseOptimizer):
        def __init__(self) -> None:
            super().__init__(
                config=OptimizerConfig(
                    max_iterations=3,
                    target_score=1.0,
                    early_stopping=True,
                    convergence_threshold=0.01,
                    validation_enabled=False,
                    metrics_enabled=False,
                )
            )
            self.optimize_calls = 0

        def generate(self, input_data, context):
            return {"value": 0}

        def critique(self, artifact, context):
            return 0.0, []

        def optimize(self, artifact, score, feedback, context):
            self.optimize_calls += 1
            artifact["value"] += 1
            return artifact

    optimizer = FlatOptimizer()
    result = optimizer.run_session(
        "x",
        OptimizationContext(session_id="early-stop", input_data="x", domain="test"),
    )

    assert optimizer.optimize_calls == 1
    assert result["iterations"] == 1
    assert result["artifact"]["value"] == 1


def test_logic_theorem_optimizer_validate_uses_prover_verify_statement() -> None:
    extraction_context = LogicExtractionContext(
        data="All employees must complete training.",
        data_type=DataType.TEXT,
        domain="general",
        config=LogicExtractionConfig(extraction_mode=ExtractionMode.FOL),
    )
    statement = LogicalStatement(
        formula="Employee(x) -> Completed(x, training)",
        natural_language="Employees complete training.",
        confidence=0.8,
        formalism="fol",
    )
    artifact = ExtractionResult(
        statements=[statement],
        context=extraction_context,
        success=True,
    )

    class FakeProverAdapter:
        def __init__(self) -> None:
            self.seen = []

        def verify_statement(self, statement_arg):
            self.seen.append(statement_arg)
            return SimpleNamespace(overall_valid=True)

    optimizer = LogicTheoremOptimizer.__new__(LogicTheoremOptimizer)
    optimizer._log = logging.getLogger(__name__)
    optimizer.prover_adapter = FakeProverAdapter()

    valid = optimizer.validate(
        artifact,
        OptimizationContext(
            session_id="validate",
            input_data=extraction_context.data,
            domain="general",
        ),
    )

    assert valid is True
    assert optimizer.prover_adapter.seen == [statement]


def test_deprecated_theorem_session_builds_typed_extraction_config() -> None:
    seen_contexts = []

    class FakeExtractor:
        def extract(self, context):
            seen_contexts.append(context)
            return ExtractionResult(
                statements=[
                    LogicalStatement(
                        formula="O(train)",
                        natural_language="Must train.",
                        confidence=0.9,
                        formalism="modal",
                    )
                ],
                context=context,
                success=True,
            )

        def improve_from_feedback(self, feedback):
            return None

    class FakeCritic:
        def evaluate(self, extraction_result):
            return CriticScore(
                overall=1.0,
                dimension_scores=[
                    DimensionScore(
                        dimension=CriticDimensions.SOUNDNESS,
                        score=1.0,
                        feedback="ok",
                    )
                ],
            )

    with pytest.warns(DeprecationWarning):
        config = SessionConfig(max_rounds=1)
    with pytest.warns(DeprecationWarning):
        session = TheoremSession(FakeExtractor(), FakeCritic(), config)

    result = session.run(
        "The agency must publish notice.",
        {"domain": "legal", "extraction_mode": ExtractionMode.MODAL},
    )

    assert result.success is True
    assert seen_contexts[0].config.extraction_mode == ExtractionMode.MODAL
