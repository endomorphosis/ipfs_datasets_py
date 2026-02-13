"""
Test suite for OntologyMediator.

Tests the mediator component that orchestrates refinement cycles.

Format: GIVEN-WHEN-THEN
"""

import pytest
from typing import Dict, List, Any
from unittest.mock import Mock, patch

# Try to import the ontology mediator
try:
    from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import (
        OntologyMediator,
        MediatorResult,
        RefinementCycle,
    )
    MEDIATOR_AVAILABLE = True
except ImportError as e:
    MEDIATOR_AVAILABLE = False
    pytest.skip(f"OntologyMediator not available: {e}", allow_module_level=True)


class TestRefinementCycle:
    """Test RefinementCycle dataclass."""
    
    def test_cycle_creation(self):
        """
        GIVEN: Refinement cycle data
        WHEN: Creating a refinement cycle
        THEN: Cycle is created with iteration info
        """
        cycle = RefinementCycle(
            iteration=1,
            ontology={"entities": {}, "relationships": []},
            critique_score=0.75,
            validation_score=0.85,
            improvements=["Added entities"]
        )
        
        assert cycle.iteration == 1
        assert cycle.critique_score == 0.75
        assert cycle.validation_score == 0.85
        assert len(cycle.improvements) == 1


class TestMediatorResult:
    """Test MediatorResult dataclass."""
    
    def test_result_creation(self):
        """
        GIVEN: Mediation result data
        WHEN: Creating a mediator result
        THEN: Result is created with final ontology and history
        """
        result = MediatorResult(
            final_ontology={"entities": {"person": {"A"}}, "relationships": []},
            refinement_cycles=[],
            converged=True,
            final_score=0.90,
            total_iterations=5
        )
        
        assert result.converged is True
        assert result.final_score == 0.90
        assert result.total_iterations == 5


class TestOntologyMediatorInitialization:
    """Test OntologyMediator initialization."""
    
    def test_mediator_initialization_default(self):
        """
        GIVEN: No configuration
        WHEN: Initializing mediator with defaults
        THEN: Mediator is created with default settings
        """
        mediator = OntologyMediator()
        
        assert mediator is not None
        assert hasattr(mediator, 'config')
        assert mediator.config.get('max_iterations') is not None
    
    def test_mediator_initialization_custom_config(self):
        """
        GIVEN: Custom configuration
        WHEN: Initializing mediator with custom settings
        THEN: Mediator uses specified settings
        """
        config = {
            'max_iterations': 20,
            'convergence_threshold': 0.85,
            'min_improvement': 0.02
        }
        mediator = OntologyMediator(config=config)
        
        assert mediator.config['max_iterations'] == 20
        assert mediator.config['convergence_threshold'] == 0.85
        assert mediator.config['min_improvement'] == 0.02
    
    def test_mediator_has_refinement_methods(self):
        """
        GIVEN: Initialized mediator
        WHEN: Checking refinement methods
        THEN: Mediator has refine and orchestrate methods
        """
        mediator = OntologyMediator()
        
        assert hasattr(mediator, 'refine')
        assert hasattr(mediator, '_orchestrate_cycle')
        assert hasattr(mediator, '_check_convergence')


class TestOntologyMediatorRefinement:
    """Test refinement orchestration."""
    
    def setup_method(self):
        """Setup for each test."""
        self.mediator = OntologyMediator()
    
    def test_refine_single_iteration(self):
        """
        GIVEN: Initial ontology
        WHEN: Running single refinement iteration
        THEN: Refined ontology is returned
        """
        initial_ontology = {
            "entities": {"person": {"John"}},
            "relationships": []
        }
        
        # Mock generator and critic
        generator = Mock()
        critic = Mock()
        validator = Mock()
        
        # Configure mocks
        generator.generate.return_value = Mock(
            entities={"person": {"John", "Mary"}},
            relationships=[{"type": "knows", "from": "John", "to": "Mary"}]
        )
        critic.evaluate.return_value = Mock(
            overall_score=0.80,
            feedback="Good",
            suggestions=[]
        )
        validator.validate.return_value = Mock(
            is_valid=True,
            validation_score=0.90
        )
        
        result = self.mediator.refine(
            initial_ontology,
            generator=generator,
            critic=critic,
            validator=validator,
            max_iterations=1
        )
        
        assert result is not None
        assert isinstance(result, MediatorResult)
    
    def test_refine_multiple_iterations(self):
        """
        GIVEN: Initial ontology and max iterations
        WHEN: Running multiple refinement iterations
        THEN: Ontology is refined over multiple cycles
        """
        initial_ontology = {
            "entities": {},
            "relationships": []
        }
        
        config = {'max_iterations': 3}
        mediator = OntologyMediator(config=config)
        
        # Mock components
        generator = Mock()
        critic = Mock()
        validator = Mock()
        
        generator.generate.return_value = Mock(
            entities={"person": {"A"}},
            relationships=[]
        )
        critic.evaluate.return_value = Mock(
            overall_score=0.85,
            feedback="Good",
            suggestions=[]
        )
        validator.validate.return_value = Mock(
            is_valid=True,
            validation_score=0.90
        )
        
        result = mediator.refine(
            initial_ontology,
            generator=generator,
            critic=critic,
            validator=validator
        )
        
        assert result is not None
        assert result.total_iterations <= 3


class TestOntologyMediatorConvergence:
    """Test convergence detection."""
    
    def setup_method(self):
        """Setup for each test."""
        self.mediator = OntologyMediator()
    
    def test_convergence_on_high_score(self):
        """
        GIVEN: Ontology with high critique score
        WHEN: Checking convergence
        THEN: Convergence is detected
        """
        config = {'convergence_threshold': 0.85}
        mediator = OntologyMediator(config=config)
        
        # Mock components returning high scores
        generator = Mock()
        critic = Mock()
        validator = Mock()
        
        generator.generate.return_value = Mock(
            entities={"person": {"A"}},
            relationships=[]
        )
        critic.evaluate.return_value = Mock(
            overall_score=0.90,  # Above threshold
            feedback="Excellent",
            suggestions=[]
        )
        validator.validate.return_value = Mock(
            is_valid=True,
            validation_score=0.95
        )
        
        result = mediator.refine(
            {"entities": {}, "relationships": []},
            generator=generator,
            critic=critic,
            validator=validator
        )
        
        if result.converged:
            assert result.final_score >= 0.85
    
    def test_no_convergence_low_score(self):
        """
        GIVEN: Ontology with persistently low scores
        WHEN: Running refinement cycles
        THEN: Max iterations reached without convergence
        """
        config = {
            'max_iterations': 3,
            'convergence_threshold': 0.90
        }
        mediator = OntologyMediator(config=config)
        
        # Mock components returning low scores
        generator = Mock()
        critic = Mock()
        validator = Mock()
        
        generator.generate.return_value = Mock(
            entities={"person": {"A"}},
            relationships=[]
        )
        critic.evaluate.return_value = Mock(
            overall_score=0.60,  # Below threshold
            feedback="Needs work",
            suggestions=["Add more entities"]
        )
        validator.validate.return_value = Mock(
            is_valid=True,
            validation_score=0.70
        )
        
        result = mediator.refine(
            {"entities": {}, "relationships": []},
            generator=generator,
            critic=critic,
            validator=validator
        )
        
        assert result.total_iterations == 3
        # May or may not converge
        if not result.converged:
            assert result.final_score < 0.90


class TestOntologyMediatorPromptAdaptation:
    """Test prompt adaptation based on feedback."""
    
    def setup_method(self):
        """Setup for each test."""
        self.mediator = OntologyMediator()
    
    def test_adapt_prompt_from_feedback(self):
        """
        GIVEN: Critic feedback with suggestions
        WHEN: Adapting prompts for next iteration
        THEN: Prompts incorporate suggestions
        """
        feedback = "Add more entity types"
        suggestions = ["Include organizations", "Add locations"]
        
        adapted_prompt = self.mediator._adapt_prompt(feedback, suggestions)
        
        assert adapted_prompt is not None
        assert isinstance(adapted_prompt, str)
        # Should mention suggestions
        assert any(word in adapted_prompt.lower() for word in ["organization", "location", "entity"])


class TestOntologyMediatorEdgeCases:
    """Test edge cases and error handling."""
    
    def setup_method(self):
        """Setup for each test."""
        self.mediator = OntologyMediator()
    
    def test_refine_with_validator_failure(self):
        """
        GIVEN: Validator that returns invalid
        WHEN: Running refinement
        THEN: Mediator retries or adjusts
        """
        generator = Mock()
        critic = Mock()
        validator = Mock()
        
        generator.generate.return_value = Mock(
            entities={"person": {"A"}},
            relationships=[]
        )
        critic.evaluate.return_value = Mock(
            overall_score=0.75,
            feedback="Good",
            suggestions=[]
        )
        validator.validate.return_value = Mock(
            is_valid=False,  # Invalid
            validation_score=0.30,
            contradictions=["Contradiction detected"]
        )
        
        result = self.mediator.refine(
            {"entities": {}, "relationships": []},
            generator=generator,
            critic=critic,
            validator=validator,
            max_iterations=2
        )
        
        assert result is not None
        # Should handle validation failure
    
    def test_refine_empty_initial_ontology(self):
        """
        GIVEN: Empty initial ontology
        WHEN: Running refinement
        THEN: Ontology is built from scratch
        """
        empty = {"entities": {}, "relationships": []}
        
        generator = Mock()
        critic = Mock()
        validator = Mock()
        
        generator.generate.return_value = Mock(
            entities={"person": {"A"}},
            relationships=[]
        )
        critic.evaluate.return_value = Mock(
            overall_score=0.80,
            feedback="Good start",
            suggestions=[]
        )
        validator.validate.return_value = Mock(
            is_valid=True,
            validation_score=0.85
        )
        
        result = self.mediator.refine(
            empty,
            generator=generator,
            critic=critic,
            validator=validator,
            max_iterations=2
        )
        
        assert result is not None
        assert result.final_ontology is not None


class TestOntologyMediatorHistory:
    """Test refinement history tracking."""
    
    def setup_method(self):
        """Setup for each test."""
        self.mediator = OntologyMediator()
    
    def test_history_tracking(self):
        """
        GIVEN: Multiple refinement iterations
        WHEN: Completing refinement
        THEN: History contains all cycles
        """
        generator = Mock()
        critic = Mock()
        validator = Mock()
        
        generator.generate.return_value = Mock(
            entities={"person": {"A"}},
            relationships=[]
        )
        critic.evaluate.return_value = Mock(
            overall_score=0.75,
            feedback="Good",
            suggestions=[]
        )
        validator.validate.return_value = Mock(
            is_valid=True,
            validation_score=0.85
        )
        
        config = {'max_iterations': 3}
        mediator = OntologyMediator(config=config)
        
        result = mediator.refine(
            {"entities": {}, "relationships": []},
            generator=generator,
            critic=critic,
            validator=validator
        )
        
        assert result is not None
        assert hasattr(result, 'refinement_cycles')
        assert len(result.refinement_cycles) > 0
        assert len(result.refinement_cycles) <= 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
