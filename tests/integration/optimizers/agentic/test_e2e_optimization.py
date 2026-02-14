"""Integration test suite for end-to-end optimization workflows."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from ipfs_datasets_py.optimizers.agentic.base import OptimizationTask
from ipfs_datasets_py.optimizers.agentic.methods import (
    TestDrivenOptimizer,
    AdversarialOptimizer,
    ActorCriticOptimizer,
    ChaosOptimizer,
)
from ipfs_datasets_py.optimizers.agentic.validation import (
    OptimizationValidator,
    ValidationLevel,
)
from ipfs_datasets_py.optimizers.agentic.llm_integration import OptimizerLLMRouter


class TestE2EOptimization:
    """Test end-to-end optimization workflows."""
    
    @pytest.fixture
    def mock_llm_router(self):
        """Create mock LLM router."""
        router = Mock(spec=OptimizerLLMRouter)
        router.generate = Mock(return_value="def optimized(): return 42")
        router.extract_code = Mock(return_value="def optimized(): return 42")
        router.extract_description = Mock(return_value="Optimized version")
        return router
    
    @pytest.fixture
    def sample_code(self):
        """Sample code to optimize."""
        return """
def slow_function(data):
    result = []
    for item in data:
        result.append(item * 2)
    return result
"""
    
    @pytest.fixture
    def optimization_task(self, tmp_path):
        """Create optimization task."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def test(): pass")
        
        return OptimizationTask(
            task_id="test-task-1",
            target_files=[str(test_file)],
            description="Test optimization workflow",
            priority=50,
        )
    
    def test_test_driven_workflow(self, mock_llm_router, sample_code, optimization_task):
        """Test complete test-driven optimization workflow."""
        optimizer = TestDrivenOptimizer(llm_router=mock_llm_router)
        
        # Run optimization
        result = optimizer.optimize(
            task=optimization_task,
            code=sample_code,
            baseline_metrics={"time": 1.0},
        )
        
        # Verify result
        assert result is not None
        assert hasattr(result, 'success')
        assert hasattr(result, 'optimized_code')
    
    def test_adversarial_workflow(self, mock_llm_router, sample_code, optimization_task):
        """Test complete adversarial optimization workflow."""
        optimizer = AdversarialOptimizer(
            llm_router=mock_llm_router,
            n_solutions=3,
        )
        
        result = optimizer.optimize(
            task=optimization_task,
            code=sample_code,
            baseline_metrics={"time": 1.0},
        )
        
        assert result is not None
        assert hasattr(result, 'success')
    
    def test_chaos_workflow(self, mock_llm_router, sample_code, optimization_task):
        """Test complete chaos engineering workflow."""
        optimizer = ChaosOptimizer(llm_router=mock_llm_router)
        
        result = optimizer.optimize(
            task=optimization_task,
            code=sample_code,
        )
        
        assert result is not None
        assert hasattr(result, 'success')
    
    def test_optimization_with_validation(self, mock_llm_router, sample_code, optimization_task):
        """Test optimization with validation integration."""
        optimizer = TestDrivenOptimizer(llm_router=mock_llm_router)
        validator = OptimizationValidator()
        
        # Run optimization
        result = optimizer.optimize(
            task=optimization_task,
            code=sample_code,
            baseline_metrics={"time": 1.0},
        )
        
        # Validate result
        if result.success and result.optimized_code:
            validation_result = validator.validate(
                result.optimized_code,
                level=ValidationLevel.BASIC,
            )
            
            assert validation_result is not None
            assert hasattr(validation_result, 'passed')
    
    def test_validation_at_all_levels(self, sample_code):
        """Test validation at all levels."""
        validator = OptimizationValidator()
        
        levels = [
            ValidationLevel.BASIC,
            ValidationLevel.STANDARD,
            ValidationLevel.STRICT,
            ValidationLevel.PARANOID,
        ]
        
        for level in levels:
            result = validator.validate(sample_code, level=level)
            
            assert result is not None
            assert result.level == level


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
