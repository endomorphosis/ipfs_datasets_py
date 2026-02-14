"""Test suite for actor-critic optimizer."""

import pytest
import json
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, mock_open
import tempfile

from ipfs_datasets_py.optimizers.agentic.methods.actor_critic import (
    ActorCriticOptimizer,
    Policy,
    CriticFeedback,
)
from ipfs_datasets_py.optimizers.agentic.base import (
    OptimizationTask,
    OptimizationResult,
)


class TestPolicy:
    """Test Policy dataclass."""
    
    def test_policy_creation(self):
        """Test creating a policy."""
        policy = Policy(
            pattern="Use list comprehension",
            success_rate=0.8,
            avg_improvement=15.0,
            usage_count=10,
        )
        assert policy.pattern == "Use list comprehension"
        assert policy.success_rate == 0.8
        assert policy.avg_improvement == 15.0
        assert policy.usage_count == 10
    
    def test_policy_to_dict(self):
        """Test policy serialization."""
        policy = Policy("pattern", 0.9, 20.0, 5)
        data = policy.to_dict()
        
        assert isinstance(data, dict)
        assert data["pattern"] == "pattern"
        assert data["success_rate"] == 0.9
        assert data["avg_improvement"] == 20.0
        assert data["usage_count"] == 5
    
    def test_policy_from_dict(self):
        """Test policy deserialization."""
        data = {
            "pattern": "Optimize loops",
            "success_rate": 0.85,
            "avg_improvement": 12.5,
            "usage_count": 8,
        }
        policy = Policy.from_dict(data)
        
        assert policy.pattern == "Optimize loops"
        assert policy.success_rate == 0.85
        assert policy.avg_improvement == 12.5
        assert policy.usage_count == 8


class TestCriticFeedback:
    """Test CriticFeedback dataclass."""
    
    def test_feedback_creation(self):
        """Test creating feedback."""
        feedback = CriticFeedback(
            correctness_score=0.95,
            performance_score=0.80,
            style_score=0.90,
            overall_score=0.88,
            comments=["Good optimization", "Minor style issues"],
        )
        assert feedback.correctness_score == 0.95
        assert feedback.performance_score == 0.80
        assert feedback.overall_score == 0.88
        assert len(feedback.comments) == 2


class TestActorCriticOptimizer:
    """Test ActorCriticOptimizer class."""
    
    @pytest.fixture
    def mock_llm_router(self):
        """Create mock LLM router."""
        router = Mock()
        router.generate = Mock(return_value="def optimized(): return 42")
        router.extract_code = Mock(return_value="def optimized(): return 42")
        router.extract_description = Mock(return_value="Actor proposal")
        return router
    
    @pytest.fixture
    def optimizer(self, mock_llm_router, tmp_path):
        """Create actor-critic optimizer instance."""
        policy_file = tmp_path / "test_policy.json"
        return ActorCriticOptimizer(
            llm_router=mock_llm_router,
            policy_file=str(policy_file),
            learning_rate=0.1,
            exploration_rate=0.2,
        )
    
    @pytest.fixture
    def sample_task(self):
        """Create sample optimization task."""
        return OptimizationTask(
            task_id="task-1",
            target_files=["test.py"],
            description="Optimize with actor-critic",
            priority=60,
        )
    
    def test_init(self, mock_llm_router, tmp_path):
        """Test optimizer initialization."""
        policy_file = tmp_path / "policy.json"
        optimizer = ActorCriticOptimizer(
            llm_router=mock_llm_router,
            policy_file=str(policy_file),
            learning_rate=0.15,
            exploration_rate=0.25,
        )
        assert optimizer.llm_router == mock_llm_router
        assert optimizer.learning_rate == 0.15
        assert optimizer.exploration_rate == 0.25
        assert isinstance(optimizer.policies, dict)
    
    def test_init_default_params(self, mock_llm_router):
        """Test initialization with defaults."""
        optimizer = ActorCriticOptimizer(llm_router=mock_llm_router)
        assert optimizer.learning_rate == 0.1
        assert optimizer.exploration_rate == 0.2
    
    def test_load_policies_nonexistent(self, optimizer):
        """Test loading policies when file doesn't exist."""
        optimizer.load_policies()
        assert isinstance(optimizer.policies, dict)
        assert len(optimizer.policies) == 0
    
    def test_load_policies_existing(self, optimizer, tmp_path):
        """Test loading policies from existing file."""
        policy_file = tmp_path / "existing_policy.json"
        policies_data = {
            "pattern1": {
                "pattern": "Use generators",
                "success_rate": 0.9,
                "avg_improvement": 20.0,
                "usage_count": 5,
            }
        }
        with open(policy_file, 'w') as f:
            json.dump(policies_data, f)
        
        optimizer.policy_file = str(policy_file)
        optimizer.load_policies()
        
        assert len(optimizer.policies) == 1
        assert "pattern1" in optimizer.policies
        assert optimizer.policies["pattern1"].success_rate == 0.9
    
    def test_save_policies(self, optimizer, tmp_path):
        """Test saving policies to file."""
        optimizer.policies = {
            "test_pattern": Policy(
                pattern="Test pattern",
                success_rate=0.85,
                avg_improvement=15.0,
                usage_count=3,
            )
        }
        
        optimizer.save_policies()
        
        # Verify file was created and contains data
        policy_file = Path(optimizer.policy_file)
        assert policy_file.exists()
        
        with open(policy_file) as f:
            data = json.load(f)
        
        assert "test_pattern" in data
        assert data["test_pattern"]["success_rate"] == 0.85
    
    def test_actor_propose(self, optimizer, sample_task):
        """Test actor proposal generation."""
        code = "def slow(): return sum(range(1000))"
        baseline_metrics = {"time": 1.0}
        
        proposal = optimizer.actor_propose(
            task=sample_task,
            code=code,
            baseline_metrics=baseline_metrics,
        )
        
        assert isinstance(proposal, str)
        assert len(proposal) > 0
        assert optimizer.llm_router.generate.called
    
    def test_actor_propose_with_exploration(self, optimizer, sample_task):
        """Test actor proposes exploration when rate is high."""
        optimizer.exploration_rate = 1.0  # Always explore
        code = "def test(): pass"
        
        with patch('random.random', return_value=0.5):  # Below exploration rate
            proposal = optimizer.actor_propose(
                task=sample_task,
                code=code,
                baseline_metrics={},
            )
        
        assert isinstance(proposal, str)
    
    def test_critic_evaluate(self, optimizer):
        """Test critic evaluation."""
        original_code = "def slow(): return sum(range(1000))"
        proposed_code = "def fast(): return sum(range(1000))"
        baseline_metrics = {"time": 1.0}
        
        feedback = optimizer.critic_evaluate(
            original_code=original_code,
            proposed_code=proposed_code,
            baseline_metrics=baseline_metrics,
        )
        
        assert isinstance(feedback, CriticFeedback)
        assert 0 <= feedback.correctness_score <= 1
        assert 0 <= feedback.performance_score <= 1
        assert 0 <= feedback.style_score <= 1
        assert 0 <= feedback.overall_score <= 1
        assert isinstance(feedback.comments, list)
    
    def test_critic_evaluate_correctness(self, optimizer):
        """Test critic checks correctness."""
        original = "def add(a, b): return a + b"
        proposed = "def add(a, b): return a - b"  # Wrong!
        
        feedback = optimizer.critic_evaluate(original, proposed, {})
        
        # Should detect incorrectness
        assert feedback.correctness_score < 1.0
    
    def test_update_policy_success(self, optimizer):
        """Test updating policy on success."""
        pattern = "Use list comprehension"
        improvement = 25.0
        
        optimizer.update_policy(pattern, improvement, success=True)
        
        assert pattern in optimizer.policies
        policy = optimizer.policies[pattern]
        assert policy.usage_count == 1
        assert policy.avg_improvement == 25.0
        assert policy.success_rate == 1.0
    
    def test_update_policy_failure(self, optimizer):
        """Test updating policy on failure."""
        pattern = "Bad pattern"
        
        optimizer.update_policy(pattern, 0, success=False)
        
        assert pattern in optimizer.policies
        policy = optimizer.policies[pattern]
        assert policy.usage_count == 1
        assert policy.success_rate == 0.0
    
    def test_update_policy_multiple_uses(self, optimizer):
        """Test policy updates over multiple uses."""
        pattern = "Optimize loops"
        
        # First use: success with 20% improvement
        optimizer.update_policy(pattern, 20.0, success=True)
        assert optimizer.policies[pattern].success_rate == 1.0
        assert optimizer.policies[pattern].avg_improvement == 20.0
        
        # Second use: success with 30% improvement
        optimizer.update_policy(pattern, 30.0, success=True)
        assert optimizer.policies[pattern].usage_count == 2
        assert optimizer.policies[pattern].success_rate == 1.0
        assert optimizer.policies[pattern].avg_improvement == 25.0  # Average
        
        # Third use: failure
        optimizer.update_policy(pattern, 0, success=False)
        assert optimizer.policies[pattern].usage_count == 3
        assert optimizer.policies[pattern].success_rate == 2/3
    
    def test_get_best_policy(self, optimizer):
        """Test selecting best policy."""
        optimizer.policies = {
            "bad": Policy("bad", 0.3, 5.0, 10),
            "good": Policy("good", 0.9, 25.0, 8),
            "medium": Policy("medium", 0.7, 15.0, 5),
        }
        
        best = optimizer.get_best_policy()
        
        assert best is not None
        assert best.pattern == "good"
        assert best.success_rate == 0.9
    
    def test_get_best_policy_empty(self, optimizer):
        """Test get_best_policy with no policies."""
        optimizer.policies = {}
        best = optimizer.get_best_policy()
        assert best is None
    
    def test_optimize_full_workflow(self, optimizer, sample_task):
        """Test complete actor-critic optimization."""
        code = "def original(): return sum(range(100))"
        baseline_metrics = {"time": 1.0}
        
        with patch.object(optimizer, 'actor_propose') as mock_actor:
            with patch.object(optimizer, 'critic_evaluate') as mock_critic:
                with patch.object(optimizer, 'update_policy') as mock_update:
                    # Setup mocks
                    mock_actor.return_value = "def optimized(): return 42"
                    mock_critic.return_value = CriticFeedback(
                        correctness_score=1.0,
                        performance_score=0.9,
                        style_score=0.85,
                        overall_score=0.92,
                        comments=["Great optimization"],
                    )
                    
                    result = optimizer.optimize(
                        task=sample_task,
                        code=code,
                        baseline_metrics=baseline_metrics,
                    )
        
        assert isinstance(result, OptimizationResult)
        assert result.success is True
        assert result.optimized_code is not None
        assert mock_actor.called
        assert mock_critic.called
        assert mock_update.called
    
    def test_optimize_rejection(self, optimizer, sample_task):
        """Test optimization when critic rejects proposal."""
        code = "def test(): pass"
        
        with patch.object(optimizer, 'actor_propose') as mock_actor:
            with patch.object(optimizer, 'critic_evaluate') as mock_critic:
                mock_actor.return_value = "bad code"
                mock_critic.return_value = CriticFeedback(
                    correctness_score=0.3,
                    performance_score=0.4,
                    style_score=0.5,
                    overall_score=0.4,  # Below threshold
                    comments=["Poor quality"],
                )
                
                result = optimizer.optimize(
                    task=sample_task,
                    code=code,
                    baseline_metrics={},
                )
        
        # Should return original code or indicate failure
        assert isinstance(result, OptimizationResult)
        # Either failed or returned original
        assert result.success is False or result.optimized_code == code
    
    def test_policy_persistence(self, optimizer, tmp_path):
        """Test that policies persist across optimizer instances."""
        # Add some policies
        optimizer.policies["pattern1"] = Policy("Use caching", 0.95, 30.0, 10)
        optimizer.save_policies()
        
        # Create new optimizer with same file
        new_optimizer = ActorCriticOptimizer(
            llm_router=optimizer.llm_router,
            policy_file=optimizer.policy_file,
        )
        
        assert "pattern1" in new_optimizer.policies
        assert new_optimizer.policies["pattern1"].success_rate == 0.95


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
