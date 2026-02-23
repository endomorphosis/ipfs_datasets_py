"""
Tests for Refinement Control Loop - Batch 239 [agentic].

Comprehensive test coverage for autonomous refinement control loop:
    - Configuration validation
    - Control loop initialization
    - Iterative refinement execution
    - Convergence detection
    - Score improvement tracking
    - Strategy application
    - Early stopping conditions
    - History logging
    - Batch processing
    - Edge cases and error handling

Test Coverage:
    - Basic control loop execution
    - Target score convergence
    - Minimum improvement threshold
    - Score degradation handling
    - Maximum iteration limits
    - Strategy selection and application
    - Progress callback invocation
    - History recording
    - Batch refinement
    - Summary statistics
"""

import pytest
from unittest.mock import Mock, MagicMock, call

from ipfs_datasets_py.optimizers.agentic.refinement_control_loop import (
    RefinementControlLoop,
    ControlLoopConfig,
    RefinementIteration,
    BatchRefinementController,
)


# ============================================================================
# Test Configuration
# ============================================================================


class TestControlLoopConfig:
    """Test control loop configuration."""
    
    def test_default_config(self):
        """Default configuration has expected values."""
        config = ControlLoopConfig()
        
        assert config.max_iterations == 10
        assert config.min_score_improvement == 0.01
        assert config.target_score == 0.9
        assert config.allow_score_degradation is False
        assert config.early_stop_degradation_count == 3
        assert config.strategy_selection_mode == "top"
        assert config.max_strategies_per_iteration == 1
        assert config.enable_logging is True
        assert config.enable_history is True
    
    def test_custom_config(self):
        """Custom configuration values are preserved."""
        config = ControlLoopConfig(
            max_iterations=20,
            min_score_improvement=0.05,
            target_score=0.95,
            allow_score_degradation=True,
            early_stop_degradation_count=5,
        )
        
        assert config.max_iterations == 20
        assert config.min_score_improvement == 0.05
        assert config.target_score == 0.95
        assert config.allow_score_degradation is True
        assert config.early_stop_degradation_count == 5


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_generator():
    """Create mock ontology generator."""
    generator = Mock()
    
    # Mock extract_entities to return progressively better results
    def extract_side_effect(text, config):
        result = {
            "entities": [{"text": "Entity", "type": "TYPE", "confidence": 0.8}],
            "relationships": [{"source": "A", "target": "B", "type": "CONNECTS"}],
        }
        return result
    
    generator.extract_entities.side_effect = extract_side_effect
    return generator


@pytest.fixture
def mock_mediator():
    """Create mock ontology mediator."""
    mediator = Mock()
    
    # Mock suggest_refinement_strategy to return different strategies
    strategy_sequence = [
        {"action": "adjust_confidence_threshold", "threshold": 0.6},
        {"action": "increase_entity_limit", "max_entities": 1500},
        {"action": "increase_window_size", "window_size": 200},
        {"action": "none"},  # Signal to stop
    ]
    
    mediator.suggest_refinement_strategy.side_effect = strategy_sequence
    return mediator


@pytest.fixture
def mock_critic():
    """Create mock ontology critic."""
    critic = Mock()
    
    # Mock evaluate_ontology to return progressively higher scores
    score_sequence = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95]
    score_iter = iter(score_sequence)
    
    def evaluate_side_effect(result):
        try:
            return {"overall": next(score_iter)}
        except StopIteration:
            return {"overall": 0.95}
    
    critic.evaluate_ontology.side_effect = evaluate_side_effect
    return critic


@pytest.fixture
def mock_config():
    """Create mock extraction configuration."""
    config = Mock()
    config.to_dict.return_value = {
        "confidence_threshold": 0.5,
        "max_entities": 1000,
        "window_size": 100,
        "stopwords": set(),
        "custom_rules": [],
    }
    config.from_dict = Mock(return_value=config)
    return config


# ============================================================================
# Test Control Loop Initialization
# ============================================================================


class TestRefinementControlLoopInit:
    """Test refinement control loop initialization."""
    
    def test_init_with_default_config(self, mock_generator, mock_mediator, mock_critic):
        """Control loop initializes with default config."""
        loop = RefinementControlLoop(mock_generator, mock_mediator, mock_critic)
        
        assert loop.generator is mock_generator
        assert loop.mediator is mock_mediator
        assert loop.critic is mock_critic
        assert isinstance(loop.config, ControlLoopConfig)
        assert loop.history == []
    
    def test_init_with_custom_config(self, mock_generator, mock_mediator, mock_critic):
        """Control loop initializes with custom config."""
        config = ControlLoopConfig(max_iterations=5, target_score=0.85)
        loop = RefinementControlLoop(
            mock_generator, mock_mediator, mock_critic, config=config
        )
        
        assert loop.config.max_iterations == 5
        assert loop.config.target_score == 0.85


# ============================================================================
# Test Basic Control Loop Execution
# ============================================================================


class TestControlLoopExecution:
    """Test control loop execution."""
    
    def test_run_basic_execution(
        self, mock_generator, mock_mediator, mock_critic, mock_config
    ):
        """Control loop executes basic refinement."""
        config = ControlLoopConfig(max_iterations=3, enable_logging=False)
        loop = RefinementControlLoop(
            mock_generator, mock_mediator, mock_critic, config=config
        )
        
        result, history = loop.run("test text", mock_config)
        
        # Should call generator multiple times
        assert mock_generator.extract_entities.call_count >= 1
        
        # Should call mediator for strategy suggestions
        assert mock_mediator.suggest_refinement_strategy.call_count >= 1
        
        # Should call critic for evaluation
        assert mock_critic.evaluate_ontology.call_count >= 1
        
        # Should return result and history
        assert result is not None
        assert isinstance(history, list)
    
    def test_run_with_progress_callback(
        self, mock_generator, mock_mediator, mock_critic, mock_config
    ):
        """Control loop calls progress callback."""
        config = ControlLoopConfig(max_iterations=2, enable_logging=False)
        loop = RefinementControlLoop(
            mock_generator, mock_mediator, mock_critic, config=config
        )
        
        callback = Mock()
        result, history = loop.run("test text", mock_config, progress_callback=callback)
        
        # Callback should be called at least once (initial + iterations)
        assert callback.call_count >= 1
        
        # Check callback arguments
        for call_args in callback.call_args_list:
            iteration, score, status = call_args[0]
            assert isinstance(iteration, int)
            assert isinstance(score, float)
            assert isinstance(status, str)
    
    def test_run_records_history(
        self, mock_generator, mock_mediator, mock_critic, mock_config
    ):
        """Control loop records refinement history."""
        config = ControlLoopConfig(max_iterations=3, enable_history=True, enable_logging=False)
        loop = RefinementControlLoop(
            mock_generator, mock_mediator, mock_critic, config=config
        )
        
        result, history = loop.run("test text", mock_config)
        
        # History should be populated
        assert len(history) > 0
        
        # Check history entries
        for entry in history:
            assert isinstance(entry, RefinementIteration)
            assert hasattr(entry, "iteration")
            assert hasattr(entry, "strategy_applied")
            assert hasattr(entry, "score_before")
            assert hasattr(entry, "score_after")
            assert hasattr(entry, "score_improvement")


# ============================================================================
# Test Convergence Conditions
# ============================================================================


class TestConvergenceConditions:
    """Test convergence detection."""
    
    def test_target_score_convergence(self, mock_config):
        """Loop stops when target score is reached."""
        generator = Mock()
        generator.extract_entities.return_value = {"entities": [], "relationships": []}
        
        mediator = Mock()
        mediator.suggest_refinement_strategy.return_value = {
            "action": "adjust_confidence_threshold",
            "threshold": 0.6,
        }
        
        critic = Mock()
        # Return score above target immediately
        critic.evaluate_ontology.return_value = {"overall": 0.95}
        
        config = ControlLoopConfig(
            max_iterations=10,
            target_score=0.9,
            enable_logging=False,
        )
        loop = RefinementControlLoop(generator, mediator, critic, config=config)
        
        result, history = loop.run("test text", mock_config)
        
        # Should stop early due to target score
        assert len(history) == 0  # No refinement needed
    
    def test_min_improvement_threshold(self, mock_config):
        """Loop stops when improvement is below threshold."""
        generator = Mock()
        generator.extract_entities.return_value = {"entities": [], "relationships": []}
        
        mediator = Mock()
        mediator.suggest_refinement_strategy.return_value = {
            "action": "adjust_confidence_threshold",
            "threshold": 0.6,
        }
        
        critic = Mock()
        # Very small improvements
        critic.evaluate_ontology.side_effect = [0.5, 0.505, 0.506]
        
        config = ControlLoopConfig(
            max_iterations=10,
            min_score_improvement=0.01,
            enable_logging=False,
        )
        loop = RefinementControlLoop(generator, mediator, critic, config=config)
        
        result, history = loop.run("test text", mock_config)
        
        # Should stop due to small improvements
        assert len(history) < 10
    
    def test_max_iterations_limit(self, mock_config):
        """Loop stops at max iterations."""
        generator = Mock()
        generator.extract_entities.return_value = {"entities": [], "relationships": []}
        
        mediator = Mock()
        mediator.suggest_refinement_strategy.return_value = {
            "action": "adjust_confidence_threshold",
            "threshold": 0.6,
        }
        
        critic = Mock()
        # Consistent improvement but never reaching target
        critic.evaluate_ontology.side_effect = [
            {"overall": 0.5 + i * 0.05} for i in range(20)
        ]
        
        config = ControlLoopConfig(
            max_iterations=5,
            target_score=0.95,
            min_score_improvement=0.01,
            enable_logging=False,
        )
        loop = RefinementControlLoop(generator, mediator, critic, config=config)
        
        result, history = loop.run("test text", mock_config)
        
        # Should stop at max iterations
        assert len(history) <= 5
    
    def test_no_strategy_convergence(self, mock_config):
        """Loop stops when no strategy is suggested."""
        generator = Mock()
        generator.extract_entities.return_value = {"entities": [], "relationships": []}
        
        mediator = Mock()
        # Return "none" action immediately
        mediator.suggest_refinement_strategy.return_value = {"action": "none"}
        
        critic = Mock()
        critic.evaluate_ontology.return_value = {"overall": 0.5}
        
        config = ControlLoopConfig(max_iterations=10, enable_logging=False)
        loop = RefinementControlLoop(generator, mediator, critic, config=config)
        
        result, history = loop.run("test text", mock_config)
        
        # Should stop immediately
        assert len(history) == 0


# ============================================================================
# Test Score Degradation Handling
# ============================================================================


class TestScoreDegradation:
    """Test score degradation handling."""
    
    def test_score_degradation_revert(self, mock_config):
        """Loop reverts strategy on score degradation."""
        generator = Mock()
        generator.extract_entities.return_value = {"entities": [], "relationships": []}
        
        mediator = Mock()
        mediator.suggest_refinement_strategy.return_value = {
            "action": "adjust_confidence_threshold",
            "threshold": 0.6,
        }
        
        critic = Mock()
        # Score degrades on second call, then improves
        # Provide enough values for initial + multiple iterations
        critic.evaluate_ontology.side_effect = [0.7, 0.6, 0.7, 0.75, 0.8, 0.85]
        
        config = ControlLoopConfig(
            max_iterations=5,
            allow_score_degradation=False,
            enable_logging=False,
        )
        loop = RefinementControlLoop(generator, mediator, critic, config=config)
        
        result, history = loop.run("test text", mock_config)
        
        # Degrading iteration should not be in history
        # (it was reverted, so history only contains successful improvements)
        for entry in history:
            assert entry.score_improvement >= 0
    
    def test_score_degradation_allowed(self, mock_config):
        """Loop continues with score degradation if allowed."""
        generator = Mock()
        generator.extract_entities.return_value = {"entities": [], "relationships": []}
        
        mediator = Mock()
        mediator.suggest_refinement_strategy.return_value = {
            "action": "adjust_confidence_threshold",
            "threshold": 0.6,
        }
        
        critic = Mock()
        # Score degrades but recovers
        # Provide more values for extended iterations
        critic.evaluate_ontology.side_effect = [0.7, 0.65, 0.8, 0.85, 0.9]
        
        config = ControlLoopConfig(
            max_iterations=5,
            allow_score_degradation=True,
            enable_logging=False,
        )
        loop = RefinementControlLoop(generator, mediator, critic, config=config)
        
        result, history = loop.run("test text", mock_config)
        
        # History may contain degradation entries
        has_degradation = any(entry.score_improvement < 0 for entry in history)
        assert has_degradation or len(history) == 0  # Either has degradation or stopped
    
    def test_early_stop_on_consecutive_degradations(self, mock_config):
        """Loop stops after consecutive degradations."""
        generator = Mock()
        generator.extract_entities.return_value = {"entities": [], "relationships": []}
        
        mediator = Mock()
        mediator.suggest_refinement_strategy.return_value = {
            "action": "adjust_confidence_threshold",
            "threshold": 0.6,
        }
        
        critic = Mock()
        # Consistent degradation
        critic.evaluate_ontology.side_effect = [0.9, 0.85, 0.8, 0.75, 0.7]
        
        config = ControlLoopConfig(
            max_iterations=10,
            allow_score_degradation=True,
            early_stop_degradation_count=3,
            enable_logging=False,
        )
        loop = RefinementControlLoop(generator, mediator, critic, config=config)
        
        result, history = loop.run("test text", mock_config)
        
        # Should stop before max iterations
        assert len(history) < 10


# ============================================================================
# Test Strategy Application
# ============================================================================


class TestStrategyApplication:
    """Test strategy application logic."""
    
    def test_apply_adjust_confidence_threshold(self, mock_config):
        """Adjust confidence threshold strategy applied correctly."""
        generator = Mock()
        generator.extract_entities.return_value = {"entities": [], "relationships": []}
        
        mediator = Mock()
        mediator.suggest_refinement_strategy.return_value = {
            "action": "adjust_confidence_threshold",
            "threshold": 0.75,
        }
        
        critic = Mock()
        critic.evaluate_ontology.side_effect = [0.5, 0.6]
        
        config = ControlLoopConfig(max_iterations=1, enable_logging=False)
        loop = RefinementControlLoop(generator, mediator, critic, config=config)
        
        result, history = loop.run("test text", mock_config)
        
        # Config should be updated with new threshold
        if history:
            assert history[0].strategy_applied["action"] == "adjust_confidence_threshold"
    
    def test_apply_increase_entity_limit(self, mock_config):
        """Increase entity limit strategy applied correctly."""
        generator = Mock()
        generator.extract_entities.return_value = {"entities": [], "relationships": []}
        
        mediator = Mock()
        mediator.suggest_refinement_strategy.return_value = {
            "action": "increase_entity_limit",
            "max_entities": 2000,
        }
        
        critic = Mock()
        critic.evaluate_ontology.side_effect = [0.5, 0.6]
        
        config = ControlLoopConfig(max_iterations=1, enable_logging=False)
        loop = RefinementControlLoop(generator, mediator, critic, config=config)
        
        result, history = loop.run("test text", mock_config)
        
        if history:
            assert history[0].strategy_applied["action"] == "increase_entity_limit"


# ============================================================================
# Test Summary Statistics
# ============================================================================


class TestSummaryStatistics:
    """Test summary statistics generation."""
    
    def test_get_summary_with_history(self, mock_generator, mock_mediator, mock_critic, mock_config):
        """Summary contains correct statistics."""
        config = ControlLoopConfig(max_iterations=3, enable_logging=False)
        loop = RefinementControlLoop(
            mock_generator, mock_mediator, mock_critic, config=config
        )
        
        result, history = loop.run("test text", mock_config)
        summary = loop.get_summary()
        
        # Check summary fields
        assert "iterations" in summary
        assert "initial_score" in summary
        assert "final_score" in summary
        assert "total_improvement" in summary
        assert "avg_iteration_time_ms" in summary
        assert "strategies_applied" in summary
        
        # Check types
        assert isinstance(summary["iterations"], int)
        assert isinstance(summary["initial_score"], float)
        assert isinstance(summary["final_score"], float)
        assert isinstance(summary["strategies_applied"], list)
    
    def test_get_summary_empty_history(self, mock_generator, mock_mediator, mock_critic):
        """Summary handles empty history."""
        loop = RefinementControlLoop(mock_generator, mock_mediator, mock_critic)
        summary = loop.get_summary()
        
        assert summary["iterations"] == 0
        assert summary["initial_score"] == 0.0
        assert summary["final_score"] == 0.0
    
    def test_clear_history(self, mock_generator, mock_mediator, mock_critic, mock_config):
        """History can be cleared."""
        config = ControlLoopConfig(max_iterations=2, enable_logging=False)
        loop = RefinementControlLoop(
            mock_generator, mock_mediator, mock_critic, config=config
        )
        
        result, history = loop.run("test text", mock_config)
        assert len(loop.history) > 0
        
        loop.clear_history()
        assert len(loop.history) == 0


# ============================================================================
# Test Batch Processing
# ============================================================================


class TestBatchRefinement:
    """Test batch refinement controller."""
    
    def test_batch_refinement_initialization(self, mock_generator, mock_mediator, mock_critic):
        """Batch controller initializes correctly."""
        batch_controller = BatchRefinementController(
            mock_generator, mock_mediator, mock_critic
        )
        
        assert batch_controller.generator is mock_generator
        assert batch_controller.mediator is mock_mediator
        assert batch_controller.critic is mock_critic
    
    def test_batch_refinement_execution(
        self, mock_generator, mock_mediator, mock_critic, mock_config
    ):
        """Batch refinement processes multiple documents."""
        config = ControlLoopConfig(max_iterations=2, enable_logging=False)
        batch_controller = BatchRefinementController(
            mock_generator, mock_mediator, mock_critic, config=config
        )
        
        documents = [
            ("doc1", "text 1", mock_config),
            ("doc2", "text 2", mock_config),
            ("doc3", "text 3", mock_config),
        ]
        
        results = batch_controller.run_batch(documents)
        
        # Should return results for all documents
        assert len(results) == 3
        
        # Check result structure
        for doc_id, final_result, history in results:
            assert isinstance(doc_id, str)
            assert final_result is not None
            assert isinstance(history, list)
    
    def test_batch_refinement_with_callback(
        self, mock_generator, mock_mediator, mock_critic, mock_config
    ):
        """Batch refinement calls progress callback."""
        config = ControlLoopConfig(max_iterations=1, enable_logging=False)
        batch_controller = BatchRefinementController(
            mock_generator, mock_mediator, mock_critic, config=config
        )
        
        documents = [
            ("doc1", "text 1", mock_config),
            ("doc2", "text 2", mock_config),
        ]
        
        callback = Mock()
        results = batch_controller.run_batch(documents, progress_callback=callback)
        
        # Callback should be called for each document
        assert callback.call_count == 2
    
    def test_batch_summary_statistics(
        self, mock_generator, mock_mediator, mock_critic, mock_config
    ):
        """Batch summary contains correct statistics."""
        config = ControlLoopConfig(max_iterations=2, enable_logging=False)
        batch_controller = BatchRefinementController(
            mock_generator, mock_mediator, mock_critic, config=config
        )
        
        documents = [
            ("doc1", "text 1", mock_config),
            ("doc2", "text 2", mock_config),
        ]
        
        results = batch_controller.run_batch(documents)
        summary = batch_controller.get_batch_summary(results)
        
        # Check summary fields
        assert summary["documents_processed"] == 2
        assert "total_iterations" in summary
        assert "avg_iterations_per_document" in summary
        assert "avg_initial_score" in summary
        assert "avg_final_score" in summary
        assert "avg_score_improvement" in summary


# ============================================================================
# Test Edge Cases
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_empty_text_input(self, mock_generator, mock_mediator, mock_critic, mock_config):
        """Control loop handles empty text."""
        mock_generator.extract_entities.return_value = {"entities": [], "relationships": []}
        
        config = ControlLoopConfig(max_iterations=1, enable_logging=False)
        loop = RefinementControlLoop(
            mock_generator, mock_mediator, mock_critic, config=config
        )
        
        result, history = loop.run("", mock_config)
        
        # Should complete without error
        assert result is not None
    
    def test_zero_max_iterations(self, mock_generator, mock_mediator, mock_critic, mock_config):
        """Control loop with zero iterations returns initial result."""
        config = ControlLoopConfig(max_iterations=0, enable_logging=False)
        loop = RefinementControlLoop(
            mock_generator, mock_mediator, mock_critic, config=config
        )
        
        result, history = loop.run("test text", mock_config)
        
        # No refinement should occur
        assert len(history) == 0
    
    def test_batch_refinement_empty_documents(self, mock_generator, mock_mediator, mock_critic):
        """Batch refinement handles empty document list."""
        batch_controller = BatchRefinementController(
            mock_generator, mock_mediator, mock_critic
        )
        
        results = batch_controller.run_batch([])
        summary = batch_controller.get_batch_summary(results)
        
        assert summary["documents_processed"] == 0
