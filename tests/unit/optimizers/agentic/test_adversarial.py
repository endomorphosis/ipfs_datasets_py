"""Test suite for adversarial optimizer."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, call
import ast

from ipfs_datasets_py.optimizers.agentic.methods.adversarial import (
    AdversarialOptimizer,
    Solution,
    BenchmarkResult,
)
from ipfs_datasets_py.optimizers.agentic.base import (
    OptimizationTask,
    OptimizationResult,
    ValidationResult,
)


class TestSolution:
    """Test Solution dataclass."""
    
    def test_solution_creation(self):
        """Test creating a solution."""
        solution = Solution(
            id="sol-1",
            code="def test(): pass",
            description="Test solution",
            benchmark_result=None,
        )
        assert solution.id == "sol-1"
        assert "def test(): pass" in solution.code
        assert solution.description == "Test solution"
        assert solution.benchmark_result is None
    
    def test_solution_with_benchmark(self):
        """Test solution with benchmark result."""
        benchmark = BenchmarkResult(
            execution_time=1.5,
            memory_usage=100.0,
            correctness_score=0.95,
        )
        solution = Solution(
            id="sol-2",
            code="optimized code",
            description="Optimized",
            benchmark_result=benchmark,
        )
        assert solution.benchmark_result.execution_time == 1.5
        assert solution.benchmark_result.correctness_score == 0.95


class TestBenchmarkResult:
    """Test BenchmarkResult dataclass."""
    
    def test_benchmark_creation(self):
        """Test creating benchmark result."""
        benchmark = BenchmarkResult(
            execution_time=2.0,
            memory_usage=150.0,
            correctness_score=1.0,
        )
        assert benchmark.execution_time == 2.0
        assert benchmark.memory_usage == 150.0
        assert benchmark.correctness_score == 1.0


class TestAdversarialOptimizer:
    """Test AdversarialOptimizer class."""
    
    @pytest.fixture
    def mock_llm_router(self):
        """Create mock LLM router."""
        router = Mock()
        router.generate = Mock(return_value="def optimized(): return 42")
        router.extract_code = Mock(return_value="def optimized(): return 42")
        router.extract_description = Mock(return_value="Optimized version")
        return router
    
    @pytest.fixture
    def optimizer(self, mock_llm_router):
        """Create adversarial optimizer instance."""
        return AdversarialOptimizer(
            llm_router=mock_llm_router,
            n_solutions=3,
            enable_benchmarking=True,
        )
    
    @pytest.fixture
    def sample_task(self):
        """Create sample optimization task."""
        return OptimizationTask(
            task_id="task-1",
            target_files=["test.py"],
            description="Optimize test function",
            priority=50,
        )
    
    def test_init(self, mock_llm_router):
        """Test optimizer initialization."""
        optimizer = AdversarialOptimizer(
            llm_router=mock_llm_router,
            n_solutions=5,
        )
        assert optimizer.llm_router == mock_llm_router
        assert optimizer.n_solutions == 5
        assert optimizer.enable_benchmarking is True
    
    def test_init_default_params(self, mock_llm_router):
        """Test initialization with default parameters."""
        optimizer = AdversarialOptimizer(llm_router=mock_llm_router)
        assert optimizer.n_solutions == 5
        assert optimizer.enable_benchmarking is True
    
    def test_generate_solutions(self, optimizer, sample_task):
        """Test generating multiple solutions."""
        code = "def original(): return 1"
        baseline_metrics = {"time": 1.0}
        
        solutions = optimizer.generate_solutions(
            task=sample_task,
            code=code,
            baseline_metrics=baseline_metrics,
        )
        
        assert len(solutions) == 3  # n_solutions=3
        assert all(isinstance(s, Solution) for s in solutions)
        assert all(s.code is not None for s in solutions)
        assert optimizer.llm_router.generate.call_count == 3
    
    def test_generate_solutions_error_handling(self, optimizer, sample_task):
        """Test error handling in solution generation."""
        optimizer.llm_router.generate.side_effect = Exception("LLM error")
        code = "def test(): pass"
        
        solutions = optimizer.generate_solutions(
            task=sample_task,
            code=code,
            baseline_metrics={},
        )
        
        # Should return empty list on error
        assert len(solutions) == 0 or all(s.code for s in solutions)
    
    def test_benchmark_solution(self, optimizer):
        """Test benchmarking a solution."""
        solution = Solution(
            id="sol-1",
            code="def fast(): return 42",
            description="Fast version",
            benchmark_result=None,
        )
        
        with patch('time.time', side_effect=[0, 0.5]):  # Mock timing
            with patch('tracemalloc.get_traced_memory', return_value=(1000, 2000)):
                benchmark = optimizer.benchmark_solution(solution, timeout=5)
        
        assert isinstance(benchmark, BenchmarkResult)
        assert benchmark.execution_time > 0
        assert benchmark.correctness_score >= 0
    
    def test_benchmark_solution_timeout(self, optimizer):
        """Test benchmark timeout handling."""
        solution = Solution(
            id="sol-1",
            code="import time\nwhile True: time.sleep(1)",
            description="Infinite loop",
            benchmark_result=None,
        )
        
        benchmark = optimizer.benchmark_solution(solution, timeout=1)
        
        # Should handle timeout gracefully
        assert isinstance(benchmark, BenchmarkResult)
        assert benchmark.correctness_score == 0  # Failed due to timeout
    
    def test_score_solution(self, optimizer):
        """Test scoring a solution."""
        benchmark = BenchmarkResult(
            execution_time=1.0,
            memory_usage=100.0,
            correctness_score=0.9,
        )
        solution = Solution(
            id="sol-1",
            code="def test(): pass",
            description="Test",
            benchmark_result=benchmark,
        )
        baseline_metrics = {"time": 2.0, "memory": 200.0}
        
        score = optimizer.score_solution(solution, baseline_metrics)
        
        assert isinstance(score, dict)
        assert "total" in score
        assert "performance" in score
        assert "readability" in score
        assert "maintainability" in score
        assert 0 <= score["total"] <= 100
    
    def test_score_solution_weights(self, optimizer):
        """Test that scoring uses correct weights."""
        benchmark = BenchmarkResult(
            execution_time=0.5,  # 2x faster
            memory_usage=50.0,   # 2x less memory
            correctness_score=1.0,
        )
        solution = Solution(
            id="sol-1",
            code="def optimized(): return 42",
            description="Highly optimized",
            benchmark_result=benchmark,
        )
        baseline_metrics = {"time": 1.0, "memory": 100.0}
        
        score = optimizer.score_solution(solution, baseline_metrics)
        
        # Performance should be high due to 2x improvement
        assert score["performance"] > 50
        # Total should be weighted average
        assert score["total"] > 0
    
    def test_select_winner(self, optimizer):
        """Test selecting best solution."""
        solutions = [
            Solution(
                id="sol-1",
                code="slow",
                description="Slow",
                benchmark_result=BenchmarkResult(1.5, 150, 0.9),
            ),
            Solution(
                id="sol-2",
                code="fast",
                description="Fast",
                benchmark_result=BenchmarkResult(0.5, 50, 1.0),
            ),
            Solution(
                id="sol-3",
                code="medium",
                description="Medium",
                benchmark_result=BenchmarkResult(1.0, 100, 0.95),
            ),
        ]
        baseline_metrics = {"time": 2.0, "memory": 200.0}
        
        winner, scores = optimizer.select_winner(solutions, baseline_metrics)
        
        assert winner is not None
        assert isinstance(scores, dict)
        assert len(scores) == 3
        # Fast solution should win
        assert winner.id == "sol-2"
        assert scores["sol-2"]["total"] >= scores["sol-1"]["total"]
    
    def test_select_winner_no_solutions(self, optimizer):
        """Test winner selection with no solutions."""
        winner, scores = optimizer.select_winner([], {})
        
        assert winner is None
        assert scores == {}
    
    def test_optimize(self, optimizer, sample_task):
        """Test full optimization workflow."""
        code = "def original(): return 1"
        baseline_metrics = {"time": 1.0}
        
        with patch.object(optimizer, 'generate_solutions') as mock_gen:
            with patch.object(optimizer, 'benchmark_solution') as mock_bench:
                with patch.object(optimizer, 'select_winner') as mock_select:
                    # Setup mocks
                    mock_solutions = [
                        Solution("sol-1", "code1", "desc1", None),
                        Solution("sol-2", "code2", "desc2", None),
                    ]
                    mock_gen.return_value = mock_solutions
                    mock_bench.return_value = BenchmarkResult(0.5, 50, 1.0)
                    mock_select.return_value = (mock_solutions[0], {"sol-1": {"total": 80}})
                    
                    result = optimizer.optimize(
                        task=sample_task,
                        code=code,
                        baseline_metrics=baseline_metrics,
                    )
        
        assert isinstance(result, OptimizationResult)
        assert result.success is True
        assert result.optimized_code is not None
        assert mock_gen.called
        assert mock_bench.called
        assert mock_select.called
    
    def test_optimize_no_winner(self, optimizer, sample_task):
        """Test optimization when no winner found."""
        code = "def test(): pass"
        
        with patch.object(optimizer, 'generate_solutions', return_value=[]):
            result = optimizer.optimize(
                task=sample_task,
                code=code,
                baseline_metrics={},
            )
        
        assert isinstance(result, OptimizationResult)
        assert result.success is False
        assert "No solutions" in result.description or result.optimized_code == code


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
