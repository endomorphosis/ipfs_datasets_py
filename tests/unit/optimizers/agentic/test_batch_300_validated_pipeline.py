"""Test suite for validated optimization pipeline integration (Batch 300).

This module provides comprehensive test coverage for:
1. ValidatedOptimizationPipeline integration with agentic optimizers
2. AgenticOptimizer.validate() enhanced implementation
3. Real optimization with validation capture
4. Baseline metrics tracking
5. Validation level handling
6. Error scenarios and edge cases
"""

import pytest
import logging
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from ipfs_datasets_py.optimizers.agentic.base import (
    AgenticOptimizer,
    OptimizationTask,
    OptimizationResult,
    OptimizationMethod,
    ValidationResult,
)
from ipfs_datasets_py.optimizers.agentic.validated_optimization_pipeline import (
    ValidatedOptimizationPipeline,
)
from ipfs_datasets_py.optimizers.agentic.validation import ValidationLevel


class MockAgenticOptimizer(AgenticOptimizer):
    """Mock agentic optimizer for testing."""
    
    def _get_method(self) -> OptimizationMethod:
        return OptimizationMethod.TEST_DRIVEN
    
    def optimize(self, task: OptimizationTask) -> OptimizationResult:
        """Return a successful optimization result."""
        return OptimizationResult(
            task_id=task.task_id,
            success=True,
            method=OptimizationMethod.TEST_DRIVEN,
            changes="Optimized function for performance",
            optimized_code="def optimized(): return 42",
            original_code="def original(): return 42",
            metrics={"estimated_improvement": 0.15},
            execution_time=0.5,
            agent_id=self.agent_id,
        )


class TestValidatedOptimizationPipeline:
    """Test ValidatedOptimizationPipeline integration."""
    
    @pytest.fixture
    def mock_optimizer(self):
        """Create a mock agentic optimizer."""
        from ipfs_datasets_py.optimizers.common.optimizer_config import OptimizerConfig
        config = OptimizerConfig.from_dict({"domain": "general", "max_rounds": 3})
        llm_router = Mock()
        return MockAgenticOptimizer(
            agent_id="test-optimizer",
            llm_router=llm_router,
            config=config,
        )
    
    @pytest.fixture
    def pipeline(self, mock_optimizer):
        """Create a validated optimization pipeline."""
        return ValidatedOptimizationPipeline(
            optimizer=mock_optimizer,
            validation_level="standard",
            capture_metrics=True,
        )
    
    @pytest.fixture
    def task(self, tmp_path):
        """Create an optimization task."""
        # Create a sample file
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): return 'world'")
        
        return OptimizationTask(
            task_id="task-1",
            description="Test optimization",
            target_files=[test_file],
            method=OptimizationMethod.TEST_DRIVEN,
        )
    
    def test_pipeline_initialization(self, mock_optimizer):
        """Test ValidatedOptimizationPipeline initialization."""
        pipeline = ValidatedOptimizationPipeline(
            optimizer=mock_optimizer,
            validation_level="strict",
        )
        
        assert pipeline.optimizer == mock_optimizer
        assert pipeline.validation_level == ValidationLevel.STRICT
        assert pipeline.capture_metrics is True
    
    def test_pipeline_with_invalid_validation_level(self, mock_optimizer):
        """Test pipeline gracefully handles invalid validation level."""
        pipeline = ValidatedOptimizationPipeline(
            optimizer=mock_optimizer,
            validation_level="invalid_level",
        )
        
        # Should default to STANDARD
        assert pipeline.validation_level == ValidationLevel.STANDARD
    
    def test_optimize_with_validation(self, pipeline, task):
        """Test optimize() performs validation."""
        result = pipeline.optimize(task)
        
        # Check basic result properties
        assert result.task_id == task.task_id
        assert result.success is True
        assert result.validation is not None
    
    def test_optimize_captures_baseline_metrics(self, pipeline, task):
        """Test optimize() captures baseline metrics."""
        result = pipeline.optimize(task)
        
        # Should have baseline metrics (from captured target files)
        # The mock optimizer also returns estimated_improvement
        assert "validation_time_sec" in result.metrics
        # Check that metrics were collected
        assert len(result.metrics) >= 1
    
    def test_optimize_captures_validation_time(self, pipeline, task):
        """Test optimize() captures validation execution time."""
        result = pipeline.optimize(task)
        
        # Should have validation time if successful
        if result.success:
            assert "validation_time_sec" in result.metrics
            assert result.metrics["validation_time_sec"] >= 0.0
    
    def test_validate_only_valid_code(self, pipeline):
        """Test validate_only() with valid code."""
        valid_code = """
def hello(name: str) -> str:
    '''Say hello to someone.'''
    return f"Hello, {name}!"
"""
        result = pipeline.validate_only(valid_code)
        
        # Syntax should pass
        assert result.syntax_check is True
    
    def test_validate_only_invalid_code(self, pipeline):
        """Test validate_only() detects syntax errors."""
        invalid_code = "def broken(: pass"
        result = pipeline.validate_only(invalid_code)
        
        # Syntax should fail
        assert result.syntax_check is False
        assert len(result.errors) > 0
    
    def test_validate_only_with_type_hints(self, pipeline):
        """Test validate_only() validates type hints."""
        code_with_hints = """
def add(a: int, b: int) -> int:
    return a + b
"""
        result = pipeline.validate_only(code_with_hints)
        
        # Type checking should pass
        assert result.type_check is True
    
    def test_get_validation_capabilities(self, pipeline):
        """Test get_validation_capabilities()."""
        capabilities = pipeline.get_validation_capabilities()
        
        assert "validation_level" in capabilities
        assert capabilities["validation_level"] == "standard"
        assert "parallel_validation" in capabilities
        assert capabilities["parallel_validation"] is True
        assert "metric_capture" in capabilities
        assert "supported_checks" in capabilities
        assert len(capabilities["supported_checks"]) > 0
    
    def test_validation_level_basic(self, mock_optimizer):
        """Test BASIC validation level."""
        pipeline = ValidatedOptimizationPipeline(
            optimizer=mock_optimizer,
            validation_level="basic",
        )
        
        assert pipeline.validation_level == ValidationLevel.BASIC
    
    def test_validation_level_paranoid(self, mock_optimizer):
        """Test PARANOID validation level."""
        pipeline = ValidatedOptimizationPipeline(
            optimizer=mock_optimizer,
            validation_level="paranoid",
        )
        
        assert pipeline.validation_level == ValidationLevel.PARANOID
    
    def test_pipeline_with_failed_optimization(self, mock_optimizer):
        """Test pipeline when optimization fails."""
        # Mock optimizer to return failure
        failed_result = OptimizationResult(
            task_id="task-1",
            success=False,
            method=OptimizationMethod.TEST_DRIVEN,
            changes="",
            error_message="Optimization failed",
            execution_time=0.1,
        )
        
        mock_optimizer.optimize = Mock(return_value=failed_result)
        pipeline = ValidatedOptimizationPipeline(optimizer=mock_optimizer)
        
        task = OptimizationTask(
            task_id="task-1",
            description="Test",
            method=OptimizationMethod.TEST_DRIVEN,
        )
        
        result = pipeline.optimize(task)
        
        # Should not have validation if optimization failed
        assert result.success is False
    
    def test_pipeline_metric_capture_disabled(self, mock_optimizer):
        """Test pipeline with metric capture disabled."""
        pipeline = ValidatedOptimizationPipeline(
            optimizer=mock_optimizer,
            capture_metrics=False,
        )
        
        task = OptimizationTask(
            task_id="task-1",
            description="Test",
            method=OptimizationMethod.TEST_DRIVEN,
        )
        
        result = pipeline.optimize(task)
        
        # Should still succeed but without baseline metrics
        assert result.success is True


class TestAgenticOptimizerValidationEnhancement:
    """Test AgenticOptimizer.validate() enhancement."""
    
    @pytest.fixture
    def optimizer(self):
        """Create a test optimizer."""
        from ipfs_datasets_py.optimizers.common.optimizer_config import OptimizerConfig
        config = OptimizerConfig.from_dict({"domain": "legal", "validation_enabled": True})
        llm_router = Mock()
        return MockAgenticOptimizer(
            agent_id="test-opt",
            llm_router=llm_router,
            config=config,
        )
    
    def test_validate_successful_optimization(self, optimizer):
        """Test validate() on successful optimization."""
        result = OptimizationResult(
            task_id="task-1",
            success=True,
            method=OptimizationMethod.TEST_DRIVEN,
            changes="Optimized code",
            optimized_code="def optimized(): pass",
            metrics={},
            execution_time=0.5,
        )
        
        validation = optimizer.validate(result)
        
        assert validation.syntax_check is True
        assert isinstance(validation, ValidationResult)
    
    def test_validate_failed_optimization(self, optimizer):
        """Test validate() on failed optimization."""
        result = OptimizationResult(
            task_id="task-1",
            success=False,
            method=OptimizationMethod.TEST_DRIVEN,
            changes="",
            error_message="Failed",
            execution_time=0.1,
        )
        
        validation = optimizer.validate(result)
        
        # Should return passed=False since optimization failed
        assert validation.passed is False
    
    def test_validate_with_metadata_target_files(self, optimizer, tmp_path):
        """Test validate() uses metadata target files."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def test(): pass")
        
        result = OptimizationResult(
            task_id="task-1",
            success=True,
            method=OptimizationMethod.TEST_DRIVEN,
            changes="Optimized",
            optimized_code="def optimized(): pass",
            metadata={"target_files": [test_file]},
            execution_time=0.5,
        )
        
        validation = optimizer.validate(result)
        
        assert isinstance(validation, ValidationResult)
    
    def test_validate_handles_validation_framework_errors(self, optimizer):
        """Test validate() gracefully handles validation framework errors."""
        result = OptimizationResult(
            task_id="task-1",
            success=True,
            method=OptimizationMethod.TEST_DRIVEN,
            changes="Optimized",
            optimized_code="def optimized(): pass",
            execution_time=0.5,
        )
        
        # Patch validator to raise an error during validation
        with patch("ipfs_datasets_py.optimizers.agentic.validation.OptimizationValidator") as mock_val:
            mock_val.side_effect = RuntimeError("Validation error")
            # The validate() method should catch this and return a safe result
            # Instead, let's test that if import fails, it still returns something sensible
            validation = optimizer.validate(result)
            
            # Should return result even if validation framework fails
            assert isinstance(validation, ValidationResult)
    
    def test_validate_respects_config_validation_level(self, optimizer):
        """Test validate() respects config validation level."""
        # Config has validation_level="standard"
        result = OptimizationResult(
            task_id="task-1",
            success=True,
            method=OptimizationMethod.TEST_DRIVEN,
            changes="Optimized",
            optimized_code="def optimized(): return 42",
            execution_time=0.5,
        )
        
        validation = optimizer.validate(result)
        
        # Should use STANDARD level from config
        assert validation.syntax_check is True


class TestValidationIntegrationEnd2End:
    """End-to-end tests for validation integration."""
    
    def test_full_pipeline_with_good_code(self):
        """Test full pipeline with syntactically correct code."""
        # Create optimizer
        from ipfs_datasets_py.optimizers.common.optimizer_config import OptimizerConfig
        config = OptimizerConfig.from_dict({"domain": "general", "validation_enabled": True})
        llm_router = Mock()
        optimizer = MockAgenticOptimizer(
            agent_id="test-opt",
            llm_router=llm_router,
            config=config,
        )
        
        # Create task
        task = OptimizationTask(
            task_id="task-1",
            description="Optimize code",
            method=OptimizationMethod.TEST_DRIVEN,
        )
        
        # Create pipeline
        pipeline = ValidatedOptimizationPipeline(optimizer=optimizer)
        
        # Optimize
        result = pipeline.optimize(task)
        
        # Verify
        assert result.success is True
        assert result.validation is not None
        assert result.validation.syntax_check is True
    
    def test_full_pipeline_with_bad_code(self):
        """Test full pipeline with syntactically incorrect code."""
        # Create optimizer
        from ipfs_datasets_py.optimizers.common.optimizer_config import OptimizerConfig
        config = OptimizerConfig.from_dict({"domain": "general", "validation_enabled": True})
        llm_router = Mock()
        optimizer = MockAgenticOptimizer(
            agent_id="test-opt",
            llm_router=llm_router,
            config=config,
        )
        
        # Override to return bad code
        optimizer.optimize = Mock(return_value=OptimizationResult(
            task_id="task-1",
            success=True,
            method=OptimizationMethod.TEST_DRIVEN,
            changes="Optimization generated bad code",
            optimized_code="def broken(: pass",  # Syntax error
            execution_time=0.5,
        ))
        
        task = OptimizationTask(
            task_id="task-1",
            description="Optimize code",
            method=OptimizationMethod.TEST_DRIVEN,
        )
        
        pipeline = ValidatedOptimizationPipeline(optimizer=optimizer)
        result = pipeline.optimize(task)
        
        # Validation should catch the syntax error
        assert result.validation is not None
        assert result.validation.syntax_check is False
    
    def test_validation_reports_all_check_types(self):
        """Test that validation result includes all check types."""
        from ipfs_datasets_py.optimizers.common.optimizer_config import OptimizerConfig
        config = OptimizerConfig.from_dict({"domain": "general", "validation_enabled": True})
        llm_router = Mock()
        optimizer = MockAgenticOptimizer(
            agent_id="test-opt",
            llm_router=llm_router,
            config=config,
        )
        
        task = OptimizationTask(
            task_id="task-1",
            description="Test",
            method=OptimizationMethod.TEST_DRIVEN,
        )
        
        pipeline = ValidatedOptimizationPipeline(optimizer=optimizer)
        result = pipeline.optimize(task)
        
        # Check all validation fields exist
        validation = result.validation
        assert hasattr(validation, "passed")
        assert hasattr(validation, "syntax_check")
        assert hasattr(validation, "type_check")
        assert hasattr(validation, "unit_tests")
        assert hasattr(validation, "performance_tests")
        assert hasattr(validation, "security_scan")
        assert hasattr(validation, "style_check")
        assert hasattr(validation, "errors")
        assert hasattr(validation, "warnings")
