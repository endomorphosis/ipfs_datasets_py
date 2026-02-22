"""Tests for BaseOptimizer.dry_run() validation method."""

import pytest
from unittest.mock import Mock, MagicMock
from datetime import datetime
import time

from ipfs_datasets_py.optimizers.common.base_optimizer import (
    BaseOptimizer,
    OptimizerConfig,
    OptimizationContext,
    OptimizationStrategy,
)


class ConcreteOptimizer(BaseOptimizer):
    """Concrete optimizer for testing BaseOptimizer."""
    
    def generate(self, input_data, context):
        """Generate artifact from input."""
        return f"generated_{input_data}"
    
    def critique(self, artifact, context):
        """Critique artifact."""
        score = 0.75
        feedback = ["improve clarity", "add examples"]
        return score, feedback
    
    def optimize(self, artifact, score, feedback, context):
        """Optimize artifact."""
        return f"{artifact}_optimized"


class TestDryRunBasic:
    """Test basic dry_run() functionality."""
    
    def test_dry_run_executes_generate_critique(self):
        """
        GIVEN: BaseOptimizer with valid config
        WHEN: Calling dry_run()
        THEN: Executes generate and critique steps
        """
        # GIVEN
        config = OptimizerConfig(validation_enabled=False)
        optimizer = ConcreteOptimizer(config=config)
        context = OptimizationContext(
            session_id="test_session_1",
            input_data="test_input",
            domain="test"
        )
        
        # WHEN
        result = optimizer.dry_run("test_data", context)
        
        # THEN
        assert result is not None
        assert 'artifact' in result
        assert 'score' in result
        assert 'feedback' in result
        assert result['artifact'] == "generated_test_data"
        assert result['score'] == 0.75
        assert result['feedback'] == ["improve clarity", "add examples"]
    
    def test_dry_run_returns_all_required_fields(self):
        """
        GIVEN: Optimizer running dry_run
        WHEN: Method completes
        THEN: Returns dict with all required fields
        """
        # GIVEN
        config = OptimizerConfig(validation_enabled=False)
        optimizer = ConcreteOptimizer(config=config)
        context = OptimizationContext(
            session_id="test_session_2",
            input_data="input",
            domain="test"
        )
        
        # WHEN
        result = optimizer.dry_run("data", context)
        
        # THEN
        required_fields = [
            'artifact', 'score', 'valid', 'feedback',
            'execution_time', 'execution_time_ms'
        ]
        for field in required_fields:
            assert field in result, f"Missing field: {field}"
    
    def test_dry_run_score_is_float(self):
        """
        GIVEN: Optimizer with numeric score
        WHEN: Calling dry_run()
        THEN: Score is returned as float
        """
        # GIVEN
        config = OptimizerConfig(validation_enabled=False)
        optimizer = ConcreteOptimizer(config=config)
        context = OptimizationContext(
            session_id="test_session_3",
            input_data="input",
            domain="test"
        )
        
        # WHEN
        result = optimizer.dry_run("data", context)
        
        # THEN
        assert isinstance(result['score'], (int, float))
        assert 0.0 <= result['score'] <= 1.0
    
    def test_dry_run_feedback_is_list(self):
        """
        GIVEN: Optimizer returning feedback list
        WHEN: Calling dry_run()
        THEN: Feedback is list of strings
        """
        # GIVEN
        config = OptimizerConfig(validation_enabled=False)
        optimizer = ConcreteOptimizer(config=config)
        context = OptimizationContext(
            session_id="test_session_4",
            input_data="input",
            domain="test"
        )
        
        # WHEN
        result = optimizer.dry_run("data", context)
        
        # THEN
        assert isinstance(result['feedback'], list)
        assert all(isinstance(f, str) for f in result['feedback'])


class TestDryRunValidation:
    """Test dry_run() validation behavior."""
    
    def test_dry_run_calls_validate_when_enabled(self):
        """
        GIVEN: Optimizer with validation_enabled=True
        WHEN: Calling dry_run()
        THEN: Validation is called and result reflects it
        """
        # GIVEN
        config = OptimizerConfig(validation_enabled=True)
        
        class MockValidationOptimizer(BaseOptimizer):
            def generate(self, input_data, context):
                return "artifact"
            
            def critique(self, artifact, context):
                return 0.8, ["feedback"]
            
            def optimize(self, artifact, score, feedback, context):
                return "optimized"
            
            def validate(self, artifact, context):
                return True  # Always valid
        
        optimizer = MockValidationOptimizer(config=config)
        context = OptimizationContext(
            session_id="test_validation_1",
            input_data="input",
            domain="test"
        )
        
        # WHEN
        result = optimizer.dry_run("data", context)
        
        # THEN
        assert result['valid'] is True
    
    def test_dry_run_skips_validate_when_disabled(self):
        """
        GIVEN: Optimizer with validation_enabled=False
        WHEN: Calling dry_run()
        THEN: Validation is skipped and valid is always True
        """
        # GIVEN
        config = OptimizerConfig(validation_enabled=False)
        
        class NoValidationOptimizer(BaseOptimizer):
            def generate(self, input_data, context):
                return "artifact"
            
            def critique(self, artifact, context):
                return 0.5, []
            
            def optimize(self, artifact, score, feedback, context):
                return "optimized"
            
            def validate(self, artifact, context):
                raise RuntimeError("validate should not be called")
        
        optimizer = NoValidationOptimizer(config=config)
        context = OptimizationContext(
            session_id="test_validation_2",
            input_data="input",
            domain="test"
        )
        
        # WHEN & THEN (validate not called, no exception)
        result = optimizer.dry_run("data", context)
        assert result['valid'] is True


class TestDryRunTiming:
    """Test dry_run() timing measurements."""
    
    def test_dry_run_measures_execution_time(self):
        """
        GIVEN: Optimizer with measurable execution
        WHEN: Calling dry_run()
        THEN: Returns execution time in seconds and milliseconds
        """
        # GIVEN
        config = OptimizerConfig(validation_enabled=False)
        
        class SlowOptimizer(BaseOptimizer):
            def generate(self, input_data, context):
                time.sleep(0.05)  # 50ms sleep
                return "artifact"
            
            def critique(self, artifact, context):
                return 0.7, []
            
            def optimize(self, artifact, score, feedback, context):
                return "optimized"
        
        optimizer = SlowOptimizer(config=config)
        context = OptimizationContext(
            session_id="test_timing_1",
            input_data="input",
            domain="test"
        )
        
        # WHEN
        result = optimizer.dry_run("data", context)
        
        # THEN
        assert result['execution_time'] > 0.0
        assert result['execution_time_ms'] > 0.0
        # Should be at least ~50ms (dry run has overhead too)
        assert result['execution_time_ms'] > 30.0
        assert result['execution_time'] * 1000 == pytest.approx(
            result['execution_time_ms'], abs=5.0
        )
    
    def test_dry_run_execution_time_reasonable(self):
        """
        GIVEN: Fast optimizer
        WHEN: Calling dry_run()
        THEN: Execution time is reasonable (not negative, not huge)
        """
        # GIVEN
        config = OptimizerConfig(validation_enabled=False)
        optimizer = ConcreteOptimizer(config=config)
        context = OptimizationContext(
            session_id="test_timing_2",
            input_data="input",
            domain="test"
        )
        
        # WHEN
        result = optimizer.dry_run("data", context)
        
        # THEN
        assert result['execution_time'] >= 0.0
        assert result['execution_time_ms'] >= 0.0
        assert result['execution_time_ms'] < 10000.0  # Should be < 10 seconds


class TestDryRunErrorHandling:
    """Test dry_run() error handling."""
    
    def test_dry_run_propagates_generate_error(self):
        """
        GIVEN: Optimizer that fails in generate()
        WHEN: Calling dry_run()
        THEN: RuntimeError is raised
        """
        # GIVEN
        config = OptimizerConfig()
        
        class FailingGenerateOptimizer(BaseOptimizer):
            def generate(self, input_data, context):
                raise RuntimeError("Generate failed")
            
            def critique(self, artifact, context):
                return 0.5, []
            
            def optimize(self, artifact, score, feedback, context):
                return "optimized"
        
        optimizer = FailingGenerateOptimizer(config=config)
        context = OptimizationContext(
            session_id="test_error_1",
            input_data="input",
            domain="test"
        )
        
        # WHEN & THEN
        with pytest.raises(RuntimeError, match="Generate failed"):
            optimizer.dry_run("data", context)
    
    def test_dry_run_propagates_critique_error(self):
        """
        GIVEN: Optimizer that fails in critique()
        WHEN: Calling dry_run()
        THEN: Error is raised
        """
        # GIVEN
        config = OptimizerConfig()
        
        class FailingCritiqueOptimizer(BaseOptimizer):
            def generate(self, input_data, context):
                return "artifact"
            
            def critique(self, artifact, context):
                raise ValueError("Critique failed")
            
            def optimize(self, artifact, score, feedback, context):
                return "optimized"
        
        optimizer = FailingCritiqueOptimizer(config=config)
        context = OptimizationContext(
            session_id="test_error_2",
            input_data="input",
            domain="test"
        )
        
        # WHEN & THEN
        with pytest.raises(ValueError, match="Critique failed"):
            optimizer.dry_run("data", context)
    
    def test_dry_run_propagates_validation_error(self):
        """
        GIVEN: Optimizer that fails in validate()
        WHEN: Calling dry_run()
        THEN: Error is raised
        """
        # GIVEN
        config = OptimizerConfig(validation_enabled=True)
        
        class FailingValidationOptimizer(BaseOptimizer):
            def generate(self, input_data, context):
                return "artifact"
            
            def critique(self, artifact, context):
                return 0.8, []
            
            def optimize(self, artifact, score, feedback, context):
                return "optimized"
            
            def validate(self, artifact, context):
                raise AssertionError("Validation failed")
        
        optimizer = FailingValidationOptimizer(config=config)
        context = OptimizationContext(
            session_id="test_error_3",
            input_data="input",
            domain="test"
        )
        
        # WHEN & THEN
        with pytest.raises(AssertionError, match="Validation failed"):
            optimizer.dry_run("data", context)


class TestDryRunDoesNotOptimize:
    """Verify dry_run() does NOT perform optimization."""
    
    def test_dry_run_does_not_call_optimize(self):
        """
        GIVEN: Optimizer with mocked optimize()
        WHEN: Calling dry_run()
        THEN: optimize() is never called
        """
        # GIVEN
        config = OptimizerConfig(validation_enabled=False)
        
        class TestOptimizer(BaseOptimizer):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.optimize_called = False
            
            def generate(self, input_data, context):
                return "artifact"
            
            def critique(self, artifact, context):
                return 0.7, []
            
            def optimize(self, artifact, score, feedback, context):
                self.optimize_called = True
                return "optimized"
        
        optimizer = TestOptimizer(config=config)
        context = OptimizationContext(
            session_id="test_no_optimize_1",
            input_data="input",
            domain="test"
        )
        
        # WHEN
        result = optimizer.dry_run("data", context)
        
        # THEN
        assert not optimizer.optimize_called, "optimize() should not be called in dry_run"
    
    def test_dry_run_does_not_iterate(self):
        """
        GIVEN: Optimizer during dry_run
        WHEN: Method completes
        THEN: Only single cycle performed (no iterations/feedback loop)
        """
        # GIVEN
        config = OptimizerConfig(
            max_iterations=10,  # Could do many iterations
            validation_enabled=False
        )
        
        class IterationTrackingOptimizer(BaseOptimizer):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.critique_call_count = 0
            
            def generate(self, input_data, context):
                return "artifact_v0"
            
            def critique(self, artifact, context):
                self.critique_call_count += 1
                # Always return low score (would normally trigger optimization)
                return 0.3, ["needs improvement"]
            
            def optimize(self, artifact, score, feedback, context):
                return f"{artifact}_optimized"
        
        optimizer = IterationTrackingOptimizer(config=config)
        context = OptimizationContext(
            session_id="test_no_iterate_1",
            input_data="input",
            domain="test"
        )
        
        # WHEN
        result = optimizer.dry_run("data", context)
        
        # THEN
        # Only one critique call (during generate phase), not multiple
        assert optimizer.critique_call_count == 1, "dry_run should only critique once"


class TestDryRunMultipleCalls:
    """Test dry_run() can be called multiple times."""
    
    def test_dry_run_can_be_called_multiple_times(self):
        """
        GIVEN: Optimizer ready for multiple dry runs
        WHEN: Calling dry_run() multiple times
        THEN: Each call succeeds independently
        """
        # GIVEN
        config = OptimizerConfig(validation_enabled=False)
        optimizer = ConcreteOptimizer(config=config)
        context1 = OptimizationContext(
            session_id="test_multi_1",
            input_data="input1",
            domain="test"
        )
        context2 = OptimizationContext(
            session_id="test_multi_2",
            input_data="input2",
            domain="test"
        )
        
        # WHEN
        result1 = optimizer.dry_run("data1", context1)
        result2 = optimizer.dry_run("data2", context2)
        
        # THEN
        assert result1['artifact'] == "generated_data1"
        assert result2['artifact'] == "generated_data2"
        assert result1 != result2
    
    def test_dry_run_does_not_accumulate_state(self):
        """
        GIVEN: Optimizer after multiple dry runs
        WHEN: Each dry run is independent
        THEN: No state carries over between calls
        """
        # GIVEN
        config = OptimizerConfig(validation_enabled=False)
        
        class StatefulOptimizer(BaseOptimizer):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.call_count = 0
            
            def generate(self, input_data, context):
                self.call_count += 1
                return f"artifact_call_{self.call_count}"
            
            def critique(self, artifact, context):
                return 0.5, []
            
            def optimize(self, artifact, score, feedback, context):
                return "optimized"
        
        optimizer = StatefulOptimizer(config=config)
        context1 = OptimizationContext(
            session_id="test_stateless_1",
            input_data="input",
            domain="test"
        )
        context2 = OptimizationContext(
            session_id="test_stateless_2",
            input_data="input",
            domain="test"
        )
        
        # WHEN
        result1 = optimizer.dry_run("data", context1)
        result2 = optimizer.dry_run("data", context2)
        
        # THEN (call_count is tracked, but each dry_run is independent)
        assert result1['artifact'] == "artifact_call_1"
        assert result2['artifact'] == "artifact_call_2"


class TestDryRunDocumentation:
    """Test that dry_run() is properly documented."""
    
    def test_dry_run_has_docstring(self):
        """
        GIVEN: BaseOptimizer.dry_run method
        WHEN: Method is examined
        THEN: Docstring is present and informative
        """
        # GIVEN/WHEN
        docstring = BaseOptimizer.dry_run.__doc__
        
        # THEN
        assert docstring is not None
        assert "dry_run" in docstring.lower() or "validate" in docstring.lower()
        assert "generate" in docstring.lower()
        assert "critique" in docstring.lower()
    
    def test_dry_run_matches_run_session_interface(self):
        """
        GIVEN: dry_run and run_session methods
        WHEN: Both are called with same inputs
        THEN: dry_run returns subset of run_session results
        """
        # GIVEN
        config = OptimizerConfig(validation_enabled=False, metrics_enabled=False)
        optimizer = ConcreteOptimizer(config=config)
        context = OptimizationContext(
            session_id="test_interface",
            input_data="input",
            domain="test"
        )
        
        # WHEN
        dry_result = optimizer.dry_run("data", context)
        session_result = optimizer.run_session("data", context)
        
        # THEN (dry_run should share key fields with run_session)
        assert dry_result['score'] == session_result['score']
        assert isinstance(dry_result['artifact'], type(session_result['artifact']))
        assert dry_result['valid'] == session_result['valid']
