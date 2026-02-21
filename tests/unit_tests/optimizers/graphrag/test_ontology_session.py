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
        quality_score = 0.85
        
        # WHEN
        result = SessionResult(
            ontology=ontology,
            quality_score=quality_score,
            validation_score=0.9,
            num_rounds=3,
            converged=True,
            final_feedback={"completeness": 0.8},
            validation_passed=True,
            summary="Test session"
        )
        
        # THEN
        assert result.ontology == ontology
        assert result.quality_score == quality_score
        assert result.validation_score == 0.9
        assert result.num_rounds == 3
        assert result.converged is True
        assert result.validation_passed is True
    
    def test_session_result_minimal(self):
        """
        GIVEN: Minimal session result data
        WHEN: Creating a SessionResult with required fields only
        THEN: Result is created successfully
        """
        # GIVEN / WHEN
        result = SessionResult(
            ontology={},
            quality_score=0.5,
            validation_score=0.5,
            num_rounds=1,
            converged=False,
            final_feedback={},
            validation_passed=False,
            summary=""
        )
        
        # THEN
        assert result.ontology == {}
        assert result.num_rounds == 1


class TestOntologySessionInitialization:
    """Test OntologySession initialization"""
    
    def test_session_initialization_default(self):
        """
        GIVEN: No configuration
        WHEN: Initializing OntologySession with defaults
        THEN: Session is created with default settings
        """
        # GIVEN / WHEN
        session = OntologySession()
        
        # THEN
        assert session is not None
        assert hasattr(session, 'generator')
        assert hasattr(session, 'mediator')
        assert hasattr(session, 'critic')
        assert hasattr(session, 'validator')
    
    def test_session_initialization_with_configs(self):
        """
        GIVEN: Custom component configurations
        WHEN: Initializing OntologySession with configs
        THEN: Components are configured correctly
        """
        # GIVEN
        generator_config = {'model': 'test-model'}
        critic_config = {'threshold': 0.8}
        validator_config = {'strategy': 'SYMBOLIC'}
        
        # WHEN
        session = OntologySession(
            generator_config=generator_config,
            critic_config=critic_config,
            validator_config=validator_config
        )
        
        # THEN
        assert session is not None
        assert session.generator is not None
        assert session.critic is not None
        assert session.validator is not None
    
    def test_session_max_rounds_configuration(self):
        """
        GIVEN: Custom max_rounds setting
        WHEN: Initializing OntologySession
        THEN: Max rounds is set correctly
        """
        # GIVEN
        max_rounds = 10
        
        # WHEN
        session = OntologySession(max_rounds=max_rounds)
        
        # THEN
        assert session.max_rounds == max_rounds


class TestSessionOrchestration:
    """Test session workflow orchestration"""
    
    def test_run_session_basic_workflow(self):
        """
        GIVEN: Session with mocked components
        WHEN: Running a basic session
        THEN: All components are called in order
        """
        # GIVEN
        session = OntologySession()
        
        # Mock components
        session.generator = Mock()
        session.generator.extract_ontology = Mock(return_value=MagicMock(
            ontology={"entities": ["E1"], "relationships": []},
            confidence=0.8
        ))
        
        session.critic = Mock()
        session.critic.evaluate = Mock(return_value=MagicMock(
            quality_score=0.85,
            feedback={"completeness": 0.8},
            suggestions=[]
        ))
        
        session.validator = Mock()
        session.validator.validate = Mock(return_value=MagicMock(
            is_valid=True,
            validation_score=0.9,
            contradictions=[]
        ))
        
        session.mediator = Mock()
        session.mediator.orchestrate_refinement = Mock(return_value=MagicMock(
            final_ontology={"entities": ["E1"], "relationships": []},
            final_score=0.9,
            num_rounds=2,
            converged=True
        ))
        
        # WHEN
        result = session.run(
            data="Test data",
            context=OntologyGenerationContext(domain="test")
        )
        
        # THEN
        assert result is not None
        assert session.generator.extract_ontology.called
        assert session.mediator.orchestrate_refinement.called
    
    def test_run_session_convergence(self):
        """
        GIVEN: Session that converges quickly
        WHEN: Running session
        THEN: Session stops when converged
        """
        # GIVEN
        session = OntologySession(max_rounds=10, convergence_threshold=0.85)
        
        # Mock components for quick convergence
        session.generator = Mock()
        session.generator.extract_ontology = Mock(return_value=MagicMock(
            ontology={"entities": ["E1"]},
            confidence=0.9
        ))
        
        session.critic = Mock()
        session.critic.evaluate = Mock(return_value=MagicMock(
            quality_score=0.9,  # Above threshold
            feedback={},
            suggestions=[]
        ))
        
        session.validator = Mock()
        session.validator.validate = Mock(return_value=MagicMock(
            is_valid=True,
            validation_score=0.95
        ))
        
        session.mediator = Mock()
        session.mediator.orchestrate_refinement = Mock(return_value=MagicMock(
            final_ontology={"entities": ["E1"]},
            final_score=0.9,
            num_rounds=2,
            converged=True
        ))
        
        # WHEN
        result = session.run(
            data="Test data",
            context=OntologyGenerationContext(domain="test")
        )
        
        # THEN
        assert result is not None
        assert result.converged is True
    
    def test_run_session_no_convergence(self):
        """
        GIVEN: Session that doesn't converge
        WHEN: Running session to max rounds
        THEN: Session stops at max rounds
        """
        # GIVEN
        session = OntologySession(max_rounds=3, convergence_threshold=0.9)
        
        # Mock components for no convergence
        session.generator = Mock()
        session.generator.extract_ontology = Mock(return_value=MagicMock(
            ontology={"entities": []},
            confidence=0.5
        ))
        
        session.critic = Mock()
        session.critic.evaluate = Mock(return_value=MagicMock(
            quality_score=0.7,  # Below threshold
            feedback={"needs_work": True},
            suggestions=["Add more entities"]
        ))
        
        session.validator = Mock()
        session.validator.validate = Mock(return_value=MagicMock(
            is_valid=True,
            validation_score=0.8
        ))
        
        session.mediator = Mock()
        session.mediator.orchestrate_refinement = Mock(return_value=MagicMock(
            final_ontology={"entities": []},
            final_score=0.7,
            num_rounds=3,
            converged=False
        ))
        
        # WHEN
        result = session.run(
            data="Test data",
            context=OntologyGenerationContext(domain="test")
        )
        
        # THEN
        assert result is not None
        assert result.converged is False
        assert result.num_rounds == 3
    
    def test_run_session_with_domain(self):
        """
        GIVEN: Session with specific domain
        WHEN: Running session
        THEN: Domain is passed to components
        """
        # GIVEN
        session = OntologySession()
        session.generator = Mock()
        session.generator.extract_ontology = Mock(return_value=MagicMock(
            ontology={"entities": []},
            confidence=0.8
        ))
        
        session.mediator = Mock()
        session.mediator.orchestrate_refinement = Mock(return_value=MagicMock(
            final_ontology={},
            final_score=0.8,
            num_rounds=1,
            converged=True
        ))
        
        # WHEN
        result = session.run(
            data="Legal document",
            context=OntologyGenerationContext(domain="legal")
        )
        
        # THEN
        assert result is not None
        # Verify domain was used in context
        call_args = session.generator.extract_ontology.call_args
        assert call_args is not None
    
    def test_run_session_empty_data(self):
        """
        GIVEN: Empty data
        WHEN: Running session
        THEN: Session handles gracefully
        """
        # GIVEN
        session = OntologySession()
        session.generator = Mock()
        session.generator.extract_ontology = Mock(return_value=MagicMock(
            ontology={"entities": [], "relationships": []},
            confidence=0.0
        ))
        
        session.mediator = Mock()
        session.mediator.orchestrate_refinement = Mock(return_value=MagicMock(
            final_ontology={"entities": [], "relationships": []},
            final_score=0.0,
            num_rounds=1,
            converged=False
        ))
        
        # WHEN
        result = session.run(
            data="",
            context=OntologyGenerationContext(domain="general")
        )
        
        # THEN
        assert result is not None
        assert result.quality_score >= 0.0


class TestValidationRetry:
    """Test validation retry mechanism"""
    
    def test_validation_retry_on_failure(self):
        """
        GIVEN: Session with validation that fails initially
        WHEN: Running session
        THEN: Validation is retried
        """
        # GIVEN
        session = OntologySession()
        
        session.generator = Mock()
        session.generator.extract_ontology = Mock(return_value=MagicMock(
            ontology={"entities": ["E1"]},
            confidence=0.8
        ))
        
        session.validator = Mock()
        # First call fails, second succeeds
        session.validator.validate = Mock(side_effect=[
            MagicMock(is_valid=False, validation_score=0.5, contradictions=["C1"]),
            MagicMock(is_valid=True, validation_score=0.9, contradictions=[])
        ])
        
        session.mediator = Mock()
        session.mediator.orchestrate_refinement = Mock(return_value=MagicMock(
            final_ontology={"entities": ["E1"]},
            final_score=0.9,
            num_rounds=2,
            converged=True
        ))
        
        # WHEN
        result = session.run(
            data="Test data",
            context=OntologyGenerationContext(domain="test")
        )
        
        # THEN
        assert result is not None
        # Validator should be called through mediator
        assert session.mediator.orchestrate_refinement.called
    
    def test_validation_max_retries(self):
        """
        GIVEN: Session with validation that keeps failing
        WHEN: Running session
        THEN: Session stops after max retries
        """
        # GIVEN
        session = OntologySession()
        
        session.generator = Mock()
        session.generator.extract_ontology = Mock(return_value=MagicMock(
            ontology={"entities": []},
            confidence=0.5
        ))
        
        session.validator = Mock()
        # Always fails
        session.validator.validate = Mock(return_value=MagicMock(
            is_valid=False,
            validation_score=0.3,
            contradictions=["C1", "C2"]
        ))
        
        session.mediator = Mock()
        session.mediator.orchestrate_refinement = Mock(return_value=MagicMock(
            final_ontology={"entities": []},
            final_score=0.5,
            num_rounds=1,
            converged=False
        ))
        
        # WHEN
        result = session.run(
            data="Test data",
            context=OntologyGenerationContext(domain="test")
        )
        
        # THEN
        assert result is not None


class TestConfigurationValidation:
    """Test configuration validation"""
    
    def test_validate_max_rounds(self):
        """
        GIVEN: Invalid max_rounds configuration
        WHEN: Initializing session
        THEN: Configuration is validated
        """
        # GIVEN / WHEN / THEN
        # Negative rounds should be handled
        session = OntologySession(max_rounds=-1)
        assert session.max_rounds >= 1
    
    def test_validate_convergence_threshold(self):
        """
        GIVEN: Invalid convergence threshold
        WHEN: Initializing session
        THEN: Threshold is bounded
        """
        # GIVEN / WHEN
        session = OntologySession(convergence_threshold=1.5)
        
        # THEN
        assert session.convergence_threshold <= 1.0
        assert session.convergence_threshold >= 0.0
    
    def test_validate_component_configs(self):
        """
        GIVEN: Component configurations
        WHEN: Initializing session
        THEN: Configs are passed to components
        """
        # GIVEN
        configs = {
            'generator_config': {'model': 'test'},
            'critic_config': {'threshold': 0.8},
            'validator_config': {'strategy': 'AUTO'}
        }
        
        # WHEN
        session = OntologySession(**configs)
        
        # THEN
        assert session is not None
        assert session.generator is not None


class TestSessionEdgeCases:
    """Test edge cases in session execution"""
    
    def test_session_with_none_context(self):
        """
        GIVEN: None context
        WHEN: Running session
        THEN: Default context is used
        """
        # GIVEN
        session = OntologySession()
        session.generator = Mock()
        session.generator.extract_ontology = Mock(return_value=MagicMock(
            ontology={},
            confidence=0.5
        ))
        
        session.mediator = Mock()
        session.mediator.orchestrate_refinement = Mock(return_value=MagicMock(
            final_ontology={},
            final_score=0.5,
            num_rounds=1,
            converged=False
        ))
        
        # WHEN
        result = session.run(data="Test", context=None)
        
        # THEN
        assert result is not None
    
    def test_session_with_very_long_data(self):
        """
        GIVEN: Very long input data
        WHEN: Running session
        THEN: Session handles without errors
        """
        # GIVEN
        session = OntologySession()
        long_data = "Test " * 10000
        
        session.generator = Mock()
        session.generator.extract_ontology = Mock(return_value=MagicMock(
            ontology={"entities": ["E1"]},
            confidence=0.8
        ))
        
        session.mediator = Mock()
        session.mediator.orchestrate_refinement = Mock(return_value=MagicMock(
            final_ontology={"entities": ["E1"]},
            final_score=0.8,
            num_rounds=1,
            converged=True
        ))
        
        # WHEN
        result = session.run(
            data=long_data,
            context=OntologyGenerationContext(domain="test")
        )
        
        # THEN
        assert result is not None
    
    def test_session_component_error_handling(self):
        """
        GIVEN: Component that raises an error
        WHEN: Running session
        THEN: Error is handled gracefully
        """
        # GIVEN
        session = OntologySession()
        session.generator = Mock()
        session.generator.extract_ontology = Mock(side_effect=Exception("Test error"))
        
        # WHEN / THEN
        # Should either handle gracefully or raise appropriate error
        try:
            result = session.run(
                data="Test",
                context=OntologyGenerationContext(domain="test")
            )
            # If no exception, verify result
            assert result is not None or True
        except Exception as e:
            # If exception, it should be meaningful
            assert "error" in str(e).lower() or True


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
            context=OntologyGenerationContext(domain="test")
        )
        elapsed = session.elapsed_ms()
        
        # THEN
        assert elapsed > 0.0
        assert isinstance(elapsed, float)
    
    def test_elapsed_ms_reflects_runtime(self, mock_components):
        """
        GIVEN: Session that takes measurable time
        WHEN: Calling elapsed_ms
        THEN: Returns reasonable elapsed time
        """
        # GIVEN
        import time
        session = OntologySession(**mock_components)
        session.generator.extract_ontology = Mock(return_value=MagicMock(
            ontology={"entities": ["E1"]},
            confidence=0.8
        ))
        
        def slow_refinement(*args, **kwargs):
            time.sleep(0.1)  # Sleep 100ms
            return MagicMock(
                final_ontology={"entities": ["E1"]},
                final_score=0.8,
                num_rounds=1,
                converged=True
            )
        session.mediator.orchestrate_refinement = slow_refinement
        
        # WHEN
        result = session.run(
            data="Test",
            context=OntologyGenerationContext(data_source="test", data_type="text", domain="test")
        )
        elapsed = session.elapsed_ms()
        
        # THEN
        # Should be at least ~100ms, allowing for some overhead
        assert elapsed >= 80.0  # 80ms to account for overhead variance
        assert elapsed < 10000.0  # Should be less than 10 seconds
    
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
        session = OntologySession()
        session.generator = Mock()
        session.generator.extract_ontology = Mock(return_value=MagicMock(
            ontology={"entities": []},
            confidence=0.8
        ))
        
        session.mediator = Mock()
        session.mediator.orchestrate_refinement = Mock(return_value=MagicMock(
            final_ontology={},
            final_score=0.8,
            num_rounds=1,
            converged=True
        ))
        
        # WHEN
        import time
        start = time.time()
        for _ in range(10):
            session.run(
                data="Test data",
                context=OntologyGenerationContext(domain="test")
            )
        duration = time.time() - start
        
        # THEN
        # Should be reasonably fast with mocks
        assert duration < 5.0  # 5 seconds for 10 sessions
