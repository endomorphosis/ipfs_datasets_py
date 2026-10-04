from ipfs_datasets_py.optimizers.common import OptimizerConfig, OptimizationContext
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.unified_optimizer import (
    LogicTheoremOptimizer,
)


def test_logic_theorem_optimizer_run_session_smoke(monkeypatch):
    optimizer = LogicTheoremOptimizer(
        config=OptimizerConfig(
            max_iterations=2,
            target_score=0.9,
            validation_enabled=True,
            early_stopping=False,
        ),
        use_provers=[],
    )

    critique_calls = {"count": 0}

    def fake_generate(input_data, context):
        return {"step": 0}

    def fake_critique(artifact, context):
        critique_calls["count"] += 1
        if critique_calls["count"] == 1:
            return 0.4, ["improve"]
        return 0.95, []

    def fake_optimize(artifact, score, feedback, context):
        return {"step": artifact["step"] + 1}

    def fake_validate(artifact, context):
        return artifact["step"] >= 1

    monkeypatch.setattr(optimizer, "generate", fake_generate)
    monkeypatch.setattr(optimizer, "critique", fake_critique)
    monkeypatch.setattr(optimizer, "optimize", fake_optimize)
    monkeypatch.setattr(optimizer, "validate", fake_validate)

    context = OptimizationContext(
        session_id="test-logic-session",
        input_data="dummy",
        domain="general",
    )

    result = optimizer.run_session("dummy", context)

    assert result["artifact"]["step"] == 1
    assert result["score"] >= 0.9
    assert result["iterations"] >= 1
    assert result["valid"] is True
    assert "metrics" in result
