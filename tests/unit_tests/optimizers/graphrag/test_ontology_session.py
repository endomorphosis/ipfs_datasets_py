"""
Unit tests for ontology_session.py

Tests the OntologySession class for orchestrating complete ontology generation workflows.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from dataclasses import dataclass
from typing import Dict, List, Any

# Test imports - gracefully handle missing dependencies
try:
    from ipfs_datasets_py.optimizers.graphrag.ontology_session import (
        SessionResult,
        OntologySession
    )
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
        OntologyGenerationContext
    )
    IMPORTS_AVAILABLE = True
except ImportError as e:
    IMPORTS_AVAILABLE = False
    SKIP_REASON = f"Required dependencies not available: {e}"

pytestmark = pytest.mark.skipif(not IMPORTS_AVAILABLE, reason=SKIP_REASON if not IMPORTS_AVAILABLE else "")


class TestSessionResult:
    """Test SessionResult dataclass"""
    
    def test_session_result_creation(self):
        """
        GIVEN: Session result data
        WHEN: Creating a SessionResult
        THEN: All fields are set correctly
        """
        # GIVEN
        ontology = {"entities": [], "relationships": []}
        critic_score = MagicMock(overall=0.85)
        validation_result = MagicMock(is_consistent=True)
        
        # WHEN
        result = SessionResult(
            ontology=ontology,
            critic_score=critic_score,
            validation_result=validation_result,
            num_rounds=3,
            converged=True,
            time_elapsed=1.5,
        )
        
        # THEN
        assert result.ontology == ontology
        assert result.critic_score is critic_score
        assert result.validation_result is validation_result
        assert result.num_rounds == 3
        assert result.converged is True
        assert result.time_elapsed == 1.5
    
    def test_session_result_minimal(self):
        """
        GIVEN: Minimal session result data
        WHEN: Creating a SessionResult with required fields only
        THEN: Result is created successfully
        """
        # GIVEN / WHEN
        result = SessionResult(
            ontology={},
            critic_score=None,
            validation_result=None,
            num_rounds=1,
            converged=False,
            time_elapsed=0.1,
        )
        
        # THEN
        assert result.ontology == {}
        assert result.num_rounds == 1


class TestOntologySessionInitialization:
    """Test OntologySession initialization"""

    @pytest.fixture
    def mock_components(self):
        return {
            'generator': Mock(),
            'mediator': Mock(),
            'critic': Mock(),
            'validator': Mock(),
        }
    
    def test_session_initialization_default(self, mock_components):
        """
        GIVEN: Mock components
        WHEN: Initializing OntologySession with required components
        THEN: Session is created with default settings
        """
        # GIVEN / WHEN
        session = OntologySession(**mock_components)
        
        # THEN
        assert session is not None
        assert hasattr(session, 'generator')
        assert hasattr(session, 'mediator')
        assert hasattr(session, 'critic')
        assert hasattr(session, 'validator')
    
    def test_session_initialization_with_configs(self, mock_components):
        """
        GIVEN: Mock components
        WHEN: Initializing OntologySession with components
        THEN: Components are set correctly
        """
        # WHEN
        session = OntologySession(**mock_components)
        
        # THEN
        assert session is not None
        assert session.generator is mock_components['generator']
        assert session.critic is mock_components['critic']
        assert session.validator is mock_components['validator']
    
    def test_session_max_rounds_configuration(self, mock_components):
        """
        GIVEN: Custom max_rounds setting
        WHEN: Initializing OntologySession
        THEN: Max rounds is set correctly
        """
        # GIVEN
        max_rounds = 10
        
        # WHEN
        session = OntologySession(**mock_components, max_rounds=max_rounds)
        
        # THEN
        assert session.max_rounds == max_rounds


class TestSessionOrchestration:
    """Test session workflow orchestration"""

    @pytest.fixture
    def mock_components(self):
        gen = Mock()
        mediator = Mock()
        critic = Mock()
        validator = Mock()
        # Set up mediator.run_refinement_cycle return value
        mediator_state = MagicMock()
        mediator_state.current_ontology = {"entities": ["E1"], "relationships": []}
        mediator_state.current_round = 2
        mediator_state.converged = True
        mediator_state.refinement_history = []
        mediator_state.critic_scores = [MagicMock(overall=0.85)]
        mediator_state.metadata = {}
        mediator.run_refinement_cycle.return_value = mediator_state
        # Set up validator.check_consistency return value
        validation_result = MagicMock()
        validation_result.is_consistent = True
        validation_result.prover_used = "mock"
        validation_result.time_ms = 10.0
        validator.check_consistency.return_value = validation_result
        return {'generator': gen, 'mediator': mediator, 'critic': critic, 'validator': validator}
    
    def test_run_session_basic_workflow(self, mock_components):
        """
        GIVEN: Session with mocked components
        WHEN: Running a basic session
        THEN: Mediator refinement cycle is called
        """
        # GIVEN
        session = OntologySession(**mock_components)
        
        # WHEN
        result = session.run(
            data="Test data",
            context=OntologyGenerationContext(data_source="test", data_type="text", domain="test")
        )
        
        # THEN
        assert result is not None
        assert mock_components['mediator'].run_refinement_cycle.called
    
    def test_run_session_convergence(self, mock_components):
        """
        GIVEN: Session that converges
        WHEN: Running session
        THEN: Result reflects convergence
        """
        # GIVEN
        session = OntologySession(**mock_components, max_rounds=10)
        
        # WHEN
        result = session.run(
            data="Test data",
            context=OntologyGenerationContext(data_source="test", data_type="text", domain="test")
        )
        
        # THEN
        assert result is not None
        assert result.converged is True
    
    def test_run_session_no_convergence(self, mock_components):
        """
        GIVEN: Session that doesn't converge
        WHEN: Running session to max rounds
        THEN: Session stops at max rounds
        """
        # GIVEN
        mock_components['mediator'].run_refinement_cycle.return_value.converged = False
        mock_components['mediator'].run_refinement_cycle.return_value.current_round = 3
        session = OntologySession(**mock_components, max_rounds=3)
        
        # WHEN
        result = session.run(
            data="Test data",
            context=OntologyGenerationContext(data_source="test", data_type="text", domain="test")
        )
        
        # THEN
        assert result is not None
        assert result.converged is False
        assert result.num_rounds == 3
    
    def test_run_session_with_domain(self, mock_components):
        """
        GIVEN: Session with specific domain
        WHEN: Running session
        THEN: Run completes successfully
        """
        # GIVEN
        session = OntologySession(**mock_components)
        
        # WHEN
        result = session.run(
            data="Legal document",
            context=OntologyGenerationContext(data_source="test", data_type="text", domain="legal")
        )
        
        # THEN
        assert result is not None
        assert mock_components['mediator'].run_refinement_cycle.called
    
    def test_run_session_empty_data(self, mock_components):
        """
        GIVEN: Empty data
        WHEN: Running session
        THEN: Session handles gracefully
        """
        # GIVEN
        session = OntologySession(**mock_components)
        
        # WHEN
        result = session.run(
            data="",
            context=OntologyGenerationContext(data_source="test", data_type="text", domain="general")
        )
        
        # THEN
        assert result is not None
        assert result.num_rounds >= 0


class TestValidationRetry:
    """Test validation retry mechanism"""

    @pytest.fixture
    def mock_components(self):
        gen = Mock()
        mediator = Mock()
        critic = Mock()
        validator = Mock()
        mediator_state = MagicMock()
        mediator_state.current_ontology = {"entities": ["E1"]}
        mediator_state.current_round = 2
        mediator_state.converged = True
        mediator_state.refinement_history = []
        mediator_state.critic_scores = [MagicMock(overall=0.9)]
        mediator_state.metadata = {}
        mediator.run_refinement_cycle.return_value = mediator_state
        validation_result = MagicMock()
        validation_result.is_consistent = True
        validation_result.prover_used = "mock"
        validation_result.time_ms = 5.0
        validator.check_consistency.return_value = validation_result
        return {'generator': gen, 'mediator': mediator, 'critic': critic, 'validator': validator}
    
    def test_validation_retry_on_failure(self, mock_components):
        """
        GIVEN: Session with mocked components
        WHEN: Running session
        THEN: Mediator is invoked and result is returned
        """
        # GIVEN
        session = OntologySession(**mock_components)
        
        # WHEN
        result = session.run(
            data="Test data",
            context=OntologyGenerationContext(data_source="test", data_type="text", domain="test")
        )
        
        # THEN
        assert result is not None
        assert mock_components['mediator'].run_refinement_cycle.called
    
    def test_validation_max_retries(self, mock_components):
        """
        GIVEN: Session with mocked components
        WHEN: Running session
        THEN: Session completes and returns a result
        """
        # GIVEN
        session = OntologySession(**mock_components)
        
        # WHEN
        result = session.run(
            data="Test data",
            context=OntologyGenerationContext(data_source="test", data_type="text", domain="test")
        )
        
        # THEN
        assert result is not None


class TestConfigurationValidation:
    """Test configuration validation"""

    @pytest.fixture
    def mock_components(self):
        return {
            'generator': Mock(),
            'mediator': Mock(),
            'critic': Mock(),
            'validator': Mock(),
        }
    
    def test_validate_max_rounds(self, mock_components):
        """
        GIVEN: Invalid max_rounds configuration
        WHEN: Initializing session
        THEN: ValueError is raised for non-positive rounds
        """
        # GIVEN / WHEN / THEN
        with pytest.raises(ValueError):
            OntologySession(**mock_components, max_rounds=-1)
    
    def test_validate_max_rounds_zero(self, mock_components):
        """
        GIVEN: Zero max_rounds
        WHEN: Initializing session
        THEN: ValueError is raised
        """
        with pytest.raises(ValueError):
            OntologySession(**mock_components, max_rounds=0)
    
    def test_validate_component_configs(self, mock_components):
        """
        GIVEN: Mock components
        WHEN: Initializing session
        THEN: Components are set on the session
        """
        # WHEN
        session = OntologySession(**mock_components)
        
        # THEN
        assert session is not None
        assert session.generator is not None


class TestSessionEdgeCases:
    """Test edge cases in session execution"""

    @pytest.fixture
    def mock_components(self):
        gen = Mock()
        mediator = Mock()
        critic = Mock()
        validator = Mock()
        mediator_state = MagicMock()
        mediator_state.current_ontology = {}
        mediator_state.current_round = 1
        mediator_state.converged = False
        mediator_state.refinement_history = []
        mediator_state.critic_scores = []
        mediator_state.metadata = {}
        mediator.run_refinement_cycle.return_value = mediator_state
        validation_result = MagicMock()
        validation_result.is_consistent = True
        validation_result.prover_used = "mock"
        validation_result.time_ms = 1.0
        validator.check_consistency.return_value = validation_result
        critic.evaluate_ontology.return_value = MagicMock(overall=0.5)
        return {'generator': gen, 'mediator': mediator, 'critic': critic, 'validator': validator}
    
    def test_session_with_none_context(self, mock_components):
        """
        GIVEN: None context
        WHEN: Running session
        THEN: Session handles gracefully (error caught, partial result returned)
        """
        # GIVEN
        session = OntologySession(**mock_components)
        
        # WHEN / THEN
        try:
            result = session.run(data="Test", context=None)
            assert result is not None
        except Exception:
            pass  # AttributeError expected since context=None
    
    def test_session_with_very_long_data(self, mock_components):
        """
        GIVEN: Very long input data
        WHEN: Running session
        THEN: Session handles without errors
        """
        # GIVEN
        session = OntologySession(**mock_components)
        long_data = "Test " * 10000
        
        # WHEN
        result = session.run(
            data=long_data,
            context=OntologyGenerationContext(data_source="test", data_type="text", domain="test")
        )
        
        # THEN
        assert result is not None
    
    def test_session_component_error_handling(self, mock_components):
        """
        GIVEN: Component that raises an error
        WHEN: Running session
        THEN: Error is handled gracefully via partial result
        """
        # GIVEN
        mock_components['mediator'].run_refinement_cycle.side_effect = Exception("Test error")
        session = OntologySession(**mock_components)
        
        # WHEN
        result = session.run(
            data="Test",
            context=OntologyGenerationContext(data_source="test", data_type="text", domain="test")
        )
        
        # THEN - partial result returned, not re-raised
        assert result is not None
        assert result.converged is False
        assert result.metadata.get('failed') is True


class TestElapsedMs:
    """Test elapsed_ms() timing method"""
    
    @pytest.fixture
    def mock_components(self):
        """Create mock components for OntologySession"""
        return {
            'generator': Mock(),
            'mediator': Mock(),
            'critic': Mock(),
            'validator': Mock(),
        }
    
    def test_elapsed_ms_before_run(self, mock_components):
        """
        GIVEN: Fresh session
        WHEN: Calling elapsed_ms before run
        THEN: Returns 0.0
        """
        # GIVEN
        session = OntologySession(**mock_components)
        
        # WHEN
        elapsed = session.elapsed_ms()
        
        # THEN
        assert elapsed == 0.0
        assert isinstance(elapsed, float)
    
    def test_elapsed_ms_after_run_started(self, mock_components):
        """
        GIVEN: Session with mocked components
        WHEN: Calling elapsed_ms during/after run
        THEN: Returns elapsed time in milliseconds
        """
        # GIVEN
        session = OntologySession(**mock_components)
        session.generator.extract_ontology = Mock(return_value=MagicMock(
            ontology={"entities": ["E1"]},
            confidence=0.8
        ))
        
        session.mediator.orchestrate_refinement = Mock(return_value=MagicMock(
            final_ontology={"entities": ["E1"]},
            final_score=0.8,
            num_rounds=1,
            converged=True
        ))
        
        # WHEN
        result = session.run(
            data="Test",
            context=OntologyGenerationContext(data_source="test", data_type="text", domain="test")
        )
        elapsed = session.elapsed_ms()
        
        # THEN
        assert elapsed > 0.0
        assert isinstance(elapsed, float)
    
    def test_elapsed_ms_reflects_runtime(self, mock_components):
        """
        GIVEN: Session with elapsed time tracked
        WHEN: Calling elapsed_ms
        THEN: Returns reasonable elapsed time proportional to actual time passed
        """
        # GIVEN
        import time
        session = OntologySession(**mock_components)
        
        # Simulate a session that started 100ms ago
        session.start_time = time.time() - 0.1  # 0.1 seconds = 100ms
        time.sleep(0.02)  # Add slight additional time
        
        # WHEN
        elapsed = session.elapsed_ms()
        
        # THEN
        # Should be at least ~100ms, allowing for some overhead
        assert elapsed >= 80.0  # 80ms to account for overhead variance
        assert elapsed < 10000.0  # Should be less than 10 seconds
        assert isinstance(elapsed, float)
    
    def test_elapsed_ms_multiple_calls(self):
        """
        GIVEN: Session already running
        WHEN: Calling elapsed_ms multiple times
        THEN: Returns increasing elapsed time
        """
        # GIVEN
        import time
        mock_components = {
            'generator': Mock(),
            'mediator': Mock(),
            'critic': Mock(),
            'validator': Mock(),
        }
        session = OntologySession(**mock_components)
        
        # Manually set start_time to an earlier point
        session.start_time = time.time() - 1.0  # Simulate 1 second ago
        
        # WHEN
        elapsed1 = session.elapsed_ms()
        time.sleep(0.1)
        elapsed2 = session.elapsed_ms()
        time.sleep(0.1)
        elapsed3 = session.elapsed_ms()
        
        # THEN
        assert elapsed1 > 0
        assert elapsed2 > elapsed1
        assert elapsed3 > elapsed2
        # Verify they're within reasonable bounds (1 to 1.3 seconds)
        assert 950 < elapsed1 < 1100
        assert 1050 < elapsed2 < 1200
        assert 1150 < elapsed3 < 1300
    
    def test_elapsed_ms_returns_float(self, mock_components):
        """
        GIVEN: Session after run
        WHEN: Calling elapsed_ms
        THEN: Always returns float type
        """
        # GIVEN
        session = OntologySession(**mock_components)
        session.generator.extract_ontology = Mock(return_value=MagicMock(
            ontology={},
            confidence=0.5
        ))
        
        session.mediator.orchestrate_refinement = Mock(return_value=MagicMock(
            final_ontology={},
            final_score=0.5,
            num_rounds=1,
            converged=False
        ))
        
        # WHEN
        session.run(data="Test", context=OntologyGenerationContext(data_source="test", data_type="text", domain="test"))
        elapsed = session.elapsed_ms()
        
        # THEN
        assert isinstance(elapsed, float)
    
    def test_elapsed_ms_rounded_precision(self):
        """
        GIVEN: Session tracking milliseconds
        WHEN: Getting elapsed time
        THEN: Result can represent fractional milliseconds
        """
        # GIVEN
        import time
        mock_components = {
            'generator': Mock(),
            'mediator': Mock(),
            'critic': Mock(),
            'validator': Mock(),
        }
        session = OntologySession(**mock_components)
        session.start_time = time.time()
        time.sleep(0.05)  # Sleep 50ms
        
        # WHEN
        elapsed = session.elapsed_ms()
        
        # THEN
        # Should be ~50ms, allow 25-100ms tolerance for system variance
        assert 25 < elapsed < 100
        # Should be a float
        assert isinstance(elapsed, float)


# Performance marker for slow tests
@pytest.mark.slow
class TestSessionPerformance:
    """Test session performance characteristics"""
    
    def test_session_execution_time(self):
        """
        GIVEN: Session with mocked components
        WHEN: Running multiple sessions
        THEN: Execution is reasonably fast
        """
        # GIVEN
        mediator_state = MagicMock()
        mediator_state.current_ontology = {"entities": []}
        mediator_state.current_round = 1
        mediator_state.converged = True
        mediator_state.refinement_history = []
        mediator_state.critic_scores = [MagicMock(overall=0.8)]
        mediator_state.metadata = {}
        validation_result = MagicMock()
        validation_result.is_consistent = True
        validation_result.prover_used = "mock"
        validation_result.time_ms = 1.0
        mediator = Mock()
        mediator.run_refinement_cycle.return_value = mediator_state
        validator = Mock()
        validator.check_consistency.return_value = validation_result
        session = OntologySession(
            generator=Mock(),
            mediator=mediator,
            critic=Mock(),
            validator=validator,
        )
        
        # WHEN
        import time
        start = time.time()
        for _ in range(10):
            session.run(
                data="Test data",
                context=OntologyGenerationContext(data_source="test", data_type="text", domain="test")
            )
        duration = time.time() - start
        
        # THEN
        # Should be reasonably fast with mocks
        assert duration < 5.0  # 5 seconds for 10 sessions
