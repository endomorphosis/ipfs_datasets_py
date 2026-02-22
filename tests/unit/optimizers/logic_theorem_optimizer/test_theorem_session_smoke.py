"""Smoke test for the unified logic theorem optimizer."""

import pytest

from ipfs_datasets_py.optimizers.common.base_optimizer import (
    OptimizerConfig,
    OptimizationContext,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import LogicTheoremOptimizer
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
