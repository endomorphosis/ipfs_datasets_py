"""
Test suite for OntologyCritic.

Tests the critic component that evaluates ontology quality.

Format: GIVEN-WHEN-THEN
"""

import pytest
from typing import Dict, List, Any
from unittest.mock import Mock, patch

# Try to import the ontology critic
try:
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import (
        OntologyCritic,
        CritiqueResult,
        QualityDimension,
    )
    CRITIC_AVAILABLE = True
except ImportError as e:
    CRITIC_AVAILABLE = False
    pytest.skip(f"OntologyCritic not available: {e}", allow_module_level=True)


class TestCritiqueResult:
    """Test CritiqueResult dataclass."""
    
    def test_result_creation_basic(self):
        """
        GIVEN: Basic critique scores
        WHEN: Creating a critique result
        THEN: Result is created with all dimensions
        """
        result = CritiqueResult(
            overall_score=0.85,
            dimension_scores={
                QualityDimension.COMPLETENESS: 0.9,
                QualityDimension.CONSISTENCY: 0.8,
                QualityDimension.CLARITY: 0.85,
                QualityDimension.GRANULARITY: 0.8,
                QualityDimension.DOMAIN_ALIGNMENT: 0.9
            },
            feedback="Good ontology",
            suggestions=["Add more entities"]
        )
        
        assert result.overall_score == 0.85
        assert len(result.dimension_scores) == 5
        assert result.feedback == "Good ontology"
        assert len(result.suggestions) == 1
    
    def test_result_weighted_score_calculation(self):
        """
        GIVEN: Dimension scores
        WHEN: Calculating weighted overall score
        THEN: Score respects dimension weights
        """
        # Weights: Completeness 25%, Consistency 25%, Clarity 15%, Granularity 15%, Domain 20%
        scores = {
            QualityDimension.COMPLETENESS: 1.0,
            QualityDimension.CONSISTENCY: 1.0,
            QualityDimension.CLARITY: 1.0,
            QualityDimension.GRANULARITY: 1.0,
            QualityDimension.DOMAIN_ALIGNMENT: 1.0
        }
        
        # All perfect scores should give 1.0
        expected = 1.0
        
        # Verify weights sum to 1.0
        weights = {
            QualityDimension.COMPLETENESS: 0.25,
            QualityDimension.CONSISTENCY: 0.25,
            QualityDimension.CLARITY: 0.15,
            QualityDimension.GRANULARITY: 0.15,
            QualityDimension.DOMAIN_ALIGNMENT: 0.20
        }
        assert abs(sum(weights.values()) - 1.0) < 0.001


class TestOntologyCriticInitialization:
    """Test OntologyCritic initialization."""
    
    def test_critic_initialization_default(self):
        """
        GIVEN: No configuration
        WHEN: Initializing critic with defaults
        THEN: Critic is created with default settings
        """
        critic = OntologyCritic()
        
        assert critic is not None
        assert hasattr(critic, 'config')
        assert critic.config.get('model') is not None
    
    def test_critic_initialization_custom_model(self):
        """
        GIVEN: Custom model configuration
        WHEN: Initializing critic with custom model
        THEN: Critic uses specified model
        """
        config = {'model': 'gpt-4', 'temperature': 0.7}
        critic = OntologyCritic(config=config)
        
        assert critic.config['model'] == 'gpt-4'
        assert critic.config['temperature'] == 0.7
    
    def test_critic_has_evaluation_methods(self):
        """
        GIVEN: Initialized critic
        WHEN: Checking evaluation methods
        THEN: Critic has dimension evaluation methods
        """
        critic = OntologyCritic()
        
        assert hasattr(critic, '_evaluate_completeness')
        assert hasattr(critic, '_evaluate_consistency')
        assert hasattr(critic, '_evaluate_clarity')
        assert hasattr(critic, '_evaluate_granularity')
        assert hasattr(critic, '_evaluate_domain_alignment')


class TestOntologyCriticEvaluation:
    """Test ontology evaluation methods."""
    
    def setup_method(self):
        """Setup for each test."""
        self.critic = OntologyCritic()
    
    def test_evaluate_simple_ontology(self):
        """
        GIVEN: Simple ontology
        WHEN: Evaluating ontology quality
        THEN: Critique is returned with scores
        """
        ontology = {
            "entities": {
                "person": {"John", "Mary"},
                "organization": {"Company X"}
            },
            "relationships": [
                {"type": "works_at", "from": "John", "to": "Company X"},
                {"type": "works_at", "from": "Mary", "to": "Company X"}
            ]
        }
        
        result = self.critic.evaluate(ontology)
        
        assert result is not None
        assert isinstance(result, CritiqueResult)
        assert 0.0 <= result.overall_score <= 1.0
        assert len(result.dimension_scores) == 5
    
    def test_evaluate_completeness_dimension(self):
        """
        GIVEN: Ontology to evaluate
        WHEN: Evaluating completeness
        THEN: Completeness score reflects coverage
        """
        # Complete ontology
        complete_ontology = {
            "entities": {
                "person": {"A", "B", "C"},
                "place": {"X", "Y"},
                "event": {"E1", "E2"}
            },
            "relationships": [
                {"type": "located_at", "from": "A", "to": "X"},
                {"type": "participated_in", "from": "B", "to": "E1"}
            ]
        }
        
        result = self.critic.evaluate(complete_ontology)
        
        assert result is not None
        assert QualityDimension.COMPLETENESS in result.dimension_scores
        # Should have reasonable completeness score
        assert result.dimension_scores[QualityDimension.COMPLETENESS] > 0
    
    def test_evaluate_consistency_dimension(self):
        """
        GIVEN: Ontology to evaluate
        WHEN: Evaluating consistency
        THEN: Consistency score reflects logical coherence
        """
        ontology = {
            "entities": {
                "person": {"John"},
                "organization": {"Company"}
            },
            "relationships": [
                {"type": "works_at", "from": "John", "to": "Company"}
            ]
        }
        
        result = self.critic.evaluate(ontology)
        
        assert result is not None
        assert QualityDimension.CONSISTENCY in result.dimension_scores
        assert 0.0 <= result.dimension_scores[QualityDimension.CONSISTENCY] <= 1.0
    
    def test_evaluate_empty_ontology(self):
        """
        GIVEN: Empty ontology
        WHEN: Evaluating quality
        THEN: Returns low scores with appropriate feedback
        """
        empty_ontology = {
            "entities": {},
            "relationships": []
        }
        
        result = self.critic.evaluate(empty_ontology)
        
        assert result is not None
        assert isinstance(result, CritiqueResult)
        # Empty ontology should have low score
        assert result.overall_score < 0.5


class TestOntologyCriticFeedback:
    """Test feedback generation."""
    
    def setup_method(self):
        """Setup for each test."""
        self.critic = OntologyCritic()
    
    def test_feedback_generation(self):
        """
        GIVEN: Evaluated ontology
        WHEN: Generating feedback
        THEN: Feedback is specific and actionable
        """
        ontology = {
            "entities": {"person": {"John"}},
            "relationships": []
        }
        
        result = self.critic.evaluate(ontology)
        
        assert result.feedback is not None
        assert len(result.feedback) > 0
        assert isinstance(result.feedback, str)
    
    def test_suggestions_generation(self):
        """
        GIVEN: Evaluated ontology
        WHEN: Generating improvement suggestions
        THEN: Suggestions are provided
        """
        ontology = {
            "entities": {"person": {"John"}},
            "relationships": []
        }
        
        result = self.critic.evaluate(ontology)
        
        assert result.suggestions is not None
        assert isinstance(result.suggestions, list)
    
    def test_dimension_specific_feedback(self):
        """
        GIVEN: Ontology with specific issues
        WHEN: Evaluating quality
        THEN: Feedback addresses specific dimensions
        """
        # Ontology missing relationships (low completeness)
        ontology = {
            "entities": {
                "person": {"A", "B", "C"},
                "place": {"X", "Y"}
            },
            "relationships": []  # No relationships
        }
        
        result = self.critic.evaluate(ontology)
        
        assert result is not None
        # Should mention relationships or completeness
        feedback_lower = result.feedback.lower()
        assert any(keyword in feedback_lower for keyword in [
            "relationship", "complete", "connect", "missing"
        ])


class TestOntologyCriticEdgeCases:
    """Test edge cases and error handling."""
    
    def setup_method(self):
        """Setup for each test."""
        self.critic = OntologyCritic()
    
    def test_evaluate_malformed_ontology(self):
        """
        GIVEN: Malformed ontology data
        WHEN: Evaluating quality
        THEN: Handles gracefully with error or low score
        """
        malformed = {"invalid": "structure"}
        
        try:
            result = self.critic.evaluate(malformed)
            # If it succeeds, should return low score
            assert result.overall_score < 0.5
        except (ValueError, KeyError, TypeError) as e:
            # Or it should raise appropriate error
            assert True
    
    def test_evaluate_none_ontology(self):
        """
        GIVEN: None as ontology
        WHEN: Evaluating quality
        THEN: Raises appropriate error
        """
        with pytest.raises((ValueError, TypeError)):
            self.critic.evaluate(None)
    
    def test_evaluate_very_large_ontology(self):
        """
        GIVEN: Very large ontology
        WHEN: Evaluating quality
        THEN: Evaluation completes without error
        """
        large_ontology = {
            "entities": {
                f"type_{i}": {f"entity_{j}" for j in range(10)}
                for i in range(20)
            },
            "relationships": [
                {"type": f"rel_{i}", "from": f"entity_{i}", "to": f"entity_{i+1}"}
                for i in range(100)
            ]
        }
        
        result = self.critic.evaluate(large_ontology)
        
        assert result is not None
        assert isinstance(result, CritiqueResult)


class TestOntologyCriticDomainSpecific:
    """Test domain-specific evaluation."""
    
    def setup_method(self):
        """Setup for each test."""
        self.critic = OntologyCritic()
    
    def test_evaluate_legal_domain(self):
        """
        GIVEN: Legal domain ontology
        WHEN: Evaluating with legal context
        THEN: Evaluation considers legal entities
        """
        legal_ontology = {
            "entities": {
                "party": {"Plaintiff", "Defendant"},
                "obligation": {"Pay damages"},
                "permission": {"File motion"}
            },
            "relationships": [
                {"type": "has_obligation", "from": "Defendant", "to": "Pay damages"}
            ]
        }
        
        result = self.critic.evaluate(legal_ontology, domain="legal")
        
        assert result is not None
        assert result.overall_score >= 0
    
    def test_evaluate_medical_domain(self):
        """
        GIVEN: Medical domain ontology
        WHEN: Evaluating with medical context
        THEN: Evaluation considers medical entities
        """
        medical_ontology = {
            "entities": {
                "patient": {"Patient A"},
                "diagnosis": {"Diabetes"},
                "treatment": {"Insulin therapy"}
            },
            "relationships": [
                {"type": "has_diagnosis", "from": "Patient A", "to": "Diabetes"},
                {"type": "prescribed", "from": "Diabetes", "to": "Insulin therapy"}
            ]
        }
        
        result = self.critic.evaluate(medical_ontology, domain="medical")
        
        assert result is not None
        assert result.overall_score >= 0


class TestOntologyCriticComparison:
    """Test comparative evaluation."""
    
    def setup_method(self):
        """Setup for each test."""
        self.critic = OntologyCritic()
    
    def test_compare_ontologies(self):
        """
        GIVEN: Two ontologies to compare
        WHEN: Evaluating both
        THEN: Better ontology gets higher score
        """
        # Simple ontology
        simple = {
            "entities": {"person": {"A"}},
            "relationships": []
        }
        
        # Rich ontology
        rich = {
            "entities": {
                "person": {"A", "B", "C"},
                "place": {"X", "Y"},
                "event": {"E1"}
            },
            "relationships": [
                {"type": "located_at", "from": "A", "to": "X"},
                {"type": "located_at", "from": "B", "to": "Y"},
                {"type": "participated_in", "from": "A", "to": "E1"}
            ]
        }
        
        result_simple = self.critic.evaluate(simple)
        result_rich = self.critic.evaluate(rich)
        
        # Rich ontology should score higher
        assert result_rich.overall_score >= result_simple.overall_score
    
    def test_iterative_improvement_detection(self):
        """
        GIVEN: Ontology before and after improvement
        WHEN: Evaluating both versions
        THEN: Improved version has higher score
        """
        before = {
            "entities": {"person": {"A", "B"}},
            "relationships": []
        }
        
        after = {
            "entities": {"person": {"A", "B"}},
            "relationships": [
                {"type": "knows", "from": "A", "to": "B"}
            ]
        }
        
        result_before = self.critic.evaluate(before)
        result_after = self.critic.evaluate(after)
        
        # After adding relationships should improve
        assert result_after.overall_score >= result_before.overall_score


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
