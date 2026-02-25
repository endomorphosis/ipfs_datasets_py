"""Comprehensive test coverage for BaseOptimizer lifecycle hooks.

Tests cover:
- All 6 hooks fire in correct order  - Hook parameters are correct
- Hook exceptions are non-fatal (already tested)
- Hooks fire correct number of times in multi-iteration scenarios
- Hooks can modify external state (audit logging, metrics collection)
- Hooks work correctly when optimization fails/succeeds
- Hooks work correctly with early stopping
- Hooks work correctly with validation disabled
"""

from __future__ import annotations

from ipfs_datasets_py.optimizers.common.base_optimizer import (
    BaseOptimizer,
    OptimizationContext,
    OptimizerConfig,
    OptimizationStrategy,
)


class _InstrumentedOptimizer(BaseOptimizer):
    """Test optimizer that records all hook invocations."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.hook_calls = []
        self.current_round = 0
    
    def generate(self, input_data, context):
        return {"value": input_data, "round": 0}
    
    def critique(self, artifact, context):
        """Return progressively increasing scores."""
        round_num = artifact.get("round", 0)
        score = 0.3 + (round_num * 0.2)
        return min(score, 1.0), [f"improve round {round_num}"]
    
    def optimize(self, artifact, score, feedback, context):
        self.current_round += 1
        return {"value": artifact["value"], "round": self.current_round}
    
    def validate(self, artifact, context):
        return artifact.get("round", 0) >= 0  # Always valid
    
    def on_session_start(self, context, input_data):
        self.hook_calls.append({
            "hook": "on_session_start",
            "session_id": context.session_id,
            "input_data": input_data,
        })
    
    def on_generate_complete(self, artifact, context):
        self.hook_calls.append({
            "hook": "on_generate_complete",
            "artifact_value": artifact["value"],
            "artifact_round": artifact["round"],
        })
    
    def on_critique_complete(self, artifact, score, feedback, context):
        self.hook_calls.append({
            "hook": "on_critique_complete",
            "score": round(score, 2),
            "feedback_count": len(feedback),
            "round": artifact.get("round", 0),
        })
    
    def on_optimize_complete(self, artifact, score, feedback, iteration, context):
        self.hook_calls.append({
            "hook": "on_optimize_complete",
            "iteration": iteration,
            "score": round(score, 2),
        })
    
    def on_validate_complete(self, artifact, valid, context):
        self.hook_calls.append({
            "hook": "on_validate_complete",
            "valid": valid,
            "final_round": artifact.get("round", 0),
        })
    
    def on_session_complete(self, result, context):
        self.hook_calls.append({
            "hook": "on_session_complete",
            "iterations": result["iterations"],
            "final_score": round(result["score"], 2),
            "valid": result["valid"],
        })


def test_all_hooks_fire_with_single_iteration() -> None:
    """Verify all hooks fire exactly once for single-iteration session."""
    optimizer = _InstrumentedOptimizer(
        config=OptimizerConfig(max_iterations=1, early_stopping=False)
    )
    context = OptimizationContext(session_id="single-001", input_data="test", domain="test")
    
    result = optimizer.run_session("test", context)
    
    assert result["iterations"] == 1
    assert len(optimizer.hook_calls) == 7  # start + generate + 2*critique + optimize + validate + complete
    
    hooks = [call["hook"] for call in optimizer.hook_calls]
    assert hooks == [
        "on_session_start",
        "on_generate_complete",
        "on_critique_complete",  # Initial critique
        "on_optimize_complete",  # After first optimize
        "on_critique_complete",  # Critique after optimize
        "on_validate_complete",
        "on_session_complete",
    ]


def test_critique_hook_fires_multiple_times_in_multi_iteration() -> None:
    """Verify on_critique_complete fires initial + once per iterate."""
    optimizer = _InstrumentedOptimizer(
        config=OptimizerConfig(max_iterations=3, early_stopping=False)
    )
    context = OptimizationContext(session_id="multi-001", input_data="test", domain="test")
    
    result = optimizer.run_session("test", context)
    
    assert result["iterations"] == 3
    
    critique_calls = [c for c in optimizer.hook_calls if c["hook"] == "on_critique_complete"]
    optimize_calls = [c for c in optimizer.hook_calls if c["hook"] == "on_optimize_complete"]
    
    # Should have initial critique + one critique per iteration
    assert len(critique_calls) == 4  # 1 initial + 3 iterations
    assert len(optimize_calls) == 3  # 3 iterations


def test_hooks_receive_correct_iteration_numbers() -> None:
    """Verify on_optimize_complete receives 1-indexed iteration numbers."""
    optimizer = _InstrumentedOptimizer(
        config=OptimizerConfig(max_iterations=3, early_stopping=False)
    )
    context = OptimizationContext(session_id="iter-001", input_data="test", domain="test")
    
    optimizer.run_session("test", context)
    
    optimize_calls = [c for c in optimizer.hook_calls if c["hook"] == "on_optimize_complete"]
    iterations = [c["iteration"] for c in optimize_calls]
    
    assert iterations == [1, 2, 3]


def test_hooks_fire_correctly_with_early_stopping() -> None:
    """Verify hooks respect early stopping termination."""
    optimizer = _InstrumentedOptimizer(
        config=OptimizerConfig(
            max_iterations=10,
            early_stopping=True,
            convergence_threshold=0.01,
        )
    )
    context = OptimizationContext(session_id="early-001", input_data="test", domain="test")
    
    result = optimizer.run_session("test", context)
    
    # Should stop early due to small score improvements
    assert result["iterations"] < 10
    
    # Verify complete hook was still called
    complete_calls = [c for c in optimizer.hook_calls if c["hook"] == "on_session_complete"]
    assert len(complete_calls) == 1
    assert complete_calls[0]["iterations"] == result["iterations"]


def test_hooks_fire_correctly_when_validation_disabled() -> None:
    """Verify on_validate_complete does NOT fire when validation disabled."""
    optimizer = _InstrumentedOptimizer(
        config=OptimizerConfig(max_iterations=1, validation_enabled=False)
    )
    context = OptimizationContext(session_id="noval-001", input_data="test", domain="test")
    
    result = optimizer.run_session("test", context)
    
    validate_calls = [c for c in optimizer.hook_calls if c["hook"] == "on_validate_complete"]
    assert len(validate_calls) == 0  # Should not fire
    assert result["valid"] is True  # Defaults to True when validation disabled


def test_hooks_receive_correct_parameters() -> None:
    """Verify hooks receive all expected parameters with correct values."""
    optimizer = _InstrumentedOptimizer(
        config=OptimizerConfig(max_iterations=2, early_stopping=False)
    )
    context = OptimizationContext(
        session_id="params-001",
        input_data="test-input",
        domain="test-domain"
    )
    
    optimizer.run_session("test-input", context)
    
    # Check session_start parameters
    start_call = optimizer.hook_calls[0]
    assert start_call["hook"] == "on_session_start"
    assert start_call["session_id"] == "params-001"
    assert start_call["input_data"] == "test-input"
    
    # Check generate_complete parameters
    generate_call = optimizer.hook_calls[1]
    assert generate_call["hook"] == "on_generate_complete"
    assert generate_call["artifact_value"] == "test-input"
    assert generate_call["artifact_round"] == 0
    
    # Check critique_complete parameters (initial)
    critique_call = optimizer.hook_calls[2]
    assert critique_call["hook"] == "on_critique_complete"
    assert critique_call["score"] == 0.3  # From critique() logic
    assert critique_call["feedback_count"] == 1
    assert critique_call["round"] == 0
    
    # Check optimize_complete parameters
    optimize_call = optimizer.hook_calls[3]
    assert optimize_call["hook"] == "on_optimize_complete"
    assert optimize_call["iteration"] == 1
    
    # Check validate_complete parameters
    validate_calls = [c for c in optimizer.hook_calls if c["hook"] == "on_validate_complete"]
    assert len(validate_calls) == 1
    assert validate_calls[0]["valid"] is True
    
    # Check session_complete parameters
    complete_call = optimizer.hook_calls[-1]
    assert complete_call["hook"] == "on_session_complete"
    assert complete_call["iterations"] == 2
    assert complete_call["valid"] is True


def test_hooks_can_track_external_state() -> None:
    """Verify hooks can modify external state for audit logging."""
    audit_log = []
    
    class _AuditingOptimizer(_InstrumentedOptimizer):
        def on_session_start(self, context, input_data):
            audit_log.append(f"START: {context.session_id}")
        
        def on_optimize_complete(self, artifact, score, feedback, iteration, context):
            audit_log.append(f"ITER {iteration}: score={score:.2f}")
        
        def on_session_complete(self, result, context):
            audit_log.append(f"DONE: {result['iterations']} iterations")
    
    optimizer = _AuditingOptimizer(
        config=OptimizerConfig(max_iterations=2, early_stopping=False)
    )
    context = OptimizationContext(session_id="audit-001", input_data="test", domain="test")
    
    optimizer.run_session("test", context)
    
    assert len(audit_log) == 4  # start + 2 iters + done
    assert audit_log[0] == "START: audit-001"
    assert audit_log[1].startswith("ITER 1:")
    assert audit_log[2].startswith("ITER 2:")
    assert audit_log[3] == "DONE: 2 iterations"


def test_hooks_can_collect_metrics() -> None:
    """Verify hooks can collect custom metrics."""
    metrics = {
        "total_optimize_calls": 0,
        "total_critique_calls": 0,
        "score_deltas": [],
    }
    
    class _MetricsOptimizer(_InstrumentedOptimizer):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.last_score = 0.0
        
        def on_critique_complete(self, artifact, score, feedback, context):
            metrics["total_critique_calls"] += 1
            delta = score - self.last_score
            if metrics["total_critique_calls"] > 1:  # Skip first
                metrics["score_deltas"].append(delta)
            self.last_score = score
        
        def on_optimize_complete(self, artifact, score, feedback, iteration, context):
            metrics["total_optimize_calls"] += 1
    
    optimizer = _MetricsOptimizer(
        config=OptimizerConfig(max_iterations=3, early_stopping=False)
    )
    context = OptimizationContext(session_id="metrics-001", input_data="test", domain="test")
    
    optimizer.run_session("test", context)
    
    assert metrics["total_optimize_calls"] == 3
    assert metrics["total_critique_calls"] == 4  # 1 initial + 3 after optimize
    assert len(metrics["score_deltas"]) == 3


def test_hooks_work_with_dry_run() -> None:
    """Verify hooks work correctly with dry_run() method (should NOT fire)."""
    optimizer = _InstrumentedOptimizer(
        config=OptimizerConfig(max_iterations=5)
    )
    context = OptimizationContext(session_id="dry-001", input_data="test", domain="test")
    
    # Call dry_run instead of run_session
    result = optimizer.dry_run("test", context)
    
    # Dry run should NOT fire lifecycle hooks (it's just generate + critique + validate)
    # This is intentional design - dry_run is for testing, not full session orchestration
    assert len(optimizer.hook_calls) == 0
    assert "artifact" in result
    assert "score" in result
    assert "valid" in result


def test_hooks_with_target_score_termination() -> None:
    """Verify hooks work correctly when target score is reached early."""
    class _HighScoringOptimizer(_InstrumentedOptimizer):
        def critique(self, artifact, context):
            # Return high score immediately
            return 0.95, ["excellent"]
    
    optimizer = _HighScoringOptimizer(
        config=OptimizerConfig(max_iterations=10, target_score=0.9)
    )
    context = OptimizationContext(session_id="target-001", input_data="test", domain="test")
    
    result = optimizer.run_session("test", context)
    
    # Should terminate without running optimize since initial score >= target
    # The loop enters (iterations=1) but breaks immediately on target_score check
    assert result["iterations"] == 1
    assert result["score"] >= 0.9
    
    # Should fire: start, generate, critique (initial), validate, complete
    # Should NOT fire: optimize_complete (breaks before optimize is called)
    hooks = [call["hook"] for call in optimizer.hook_calls]
    assert "on_session_start" in hooks
    assert "on_generate_complete" in hooks
    assert "on_critique_complete" in hooks
    assert "on_validate_complete" in hooks
    assert "on_session_complete" in hooks
    assert "on_optimize_complete" not in hooks  # Breaks before optimize
    
    # Verify only one critique call (the initial one)
    critique_calls = [c for c in optimizer.hook_calls if c["hook"] == "on_critique_complete"]
    assert len(critique_calls) == 1
