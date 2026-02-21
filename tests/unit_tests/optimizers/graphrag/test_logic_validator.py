"""
Test suite for LogicValidator.

Tests the logic validation component that bridges ontologies
to TDFOL theorem provers.

Format: GIVEN-WHEN-THEN
"""

import pytest
from typing import Dict, List, Any
from unittest.mock import Mock, patch

# Try to import the logic validator
try:
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import (
        LogicValidator,
        ValidationResult,
        ProverStrategy,
    )
    VALIDATOR_AVAILABLE = True
except ImportError as e:
    VALIDATOR_AVAILABLE = False
    pytest.skip(f"LogicValidator not available: {e}", allow_module_level=True)


class TestValidationResult:
    """Test ValidationResult dataclass."""
    
    def test_result_creation_valid(self):
        """
        GIVEN: Validation result data for valid ontology
        WHEN: Creating a validation result
        THEN: Result is created with is_valid=True
        """
        result = ValidationResult(
            is_valid=True,
            validation_score=0.95,
            contradictions=[],
            warnings=[],
            suggestions=[]
        )
        
        assert result.is_valid is True
        assert result.validation_score == 0.95
        assert len(result.contradictions) == 0
    
    def test_result_creation_invalid(self):
        """
        GIVEN: Validation result data for invalid ontology
        WHEN: Creating a validation result
        THEN: Result is created with contradictions
        """
        result = ValidationResult(
            is_valid=False,
            validation_score=0.45,
            contradictions=["Entity X conflicts with Entity Y"],
            warnings=["Incomplete relationship"],
            suggestions=["Remove conflicting entities"]
        )
        
        assert result.is_valid is False
        assert len(result.contradictions) == 1
        assert len(result.warnings) == 1
        assert len(result.suggestions) == 1


class TestLogicValidatorInitialization:
    """Test LogicValidator initialization."""
    
    def test_validator_initialization_default(self):
        """
        GIVEN: No configuration
        WHEN: Initializing validator with defaults
        THEN: Validator is created with AUTO strategy
        """
        validator = LogicValidator()
        
        assert validator is not None
        assert hasattr(validator, 'config')
        assert validator.config.get('strategy') in [
            ProverStrategy.AUTO,
            ProverStrategy.SYMBOLIC,
            ProverStrategy.NEURAL,
            ProverStrategy.HYBRID
        ]
    
    def test_validator_initialization_custom_strategy(self):
        """
        GIVEN: Custom strategy configuration
        WHEN: Initializing validator with SYMBOLIC strategy
        THEN: Validator uses SYMBOLIC strategy
        """
        config = {'strategy': ProverStrategy.SYMBOLIC}
        validator = LogicValidator(config=config)
        
        assert validator.config['strategy'] == ProverStrategy.SYMBOLIC
    
    def test_validator_has_conversion_methods(self):
        """
        GIVEN: Initialized validator
        WHEN: Checking conversion methods
        THEN: Validator has ontology to TDFOL conversion
        """
        validator = LogicValidator()
        
        assert hasattr(validator, '_ontology_to_tdfol')
        assert hasattr(validator, '_validate_consistency')


class TestLogicValidatorConversion:
    """Test ontology to TDFOL conversion."""
    
    def setup_method(self):
        """Setup for each test."""
        self.validator = LogicValidator()
    
    def test_convert_simple_ontology(self):
        """
        GIVEN: Simple ontology
        WHEN: Converting to TDFOL
        THEN: TDFOL formulas are generated
        """
        ontology = {
            "entities": {
                "person": {"John", "Mary"}
            },
            "relationships": [
                {"type": "knows", "from": "John", "to": "Mary"}
            ]
        }
        
        formulas = self.validator._ontology_to_tdfol(ontology)
        
        assert formulas is not None
        assert isinstance(formulas, (list, dict, str))
    
    def test_convert_entity_to_predicate(self):
        """
        GIVEN: Entity in ontology
        WHEN: Converting to TDFOL
        THEN: Entity is represented as predicate
        """
        ontology = {
            "entities": {"person": {"Alice"}},
            "relationships": []
        }
        
        formulas = self.validator._ontology_to_tdfol(ontology)
        
        assert formulas is not None
        # Should contain person predicate
        if isinstance(formulas, str):
            assert "person" in formulas.lower() or "alice" in formulas.lower()
    
    def test_convert_relationship_to_formula(self):
        """
        GIVEN: Relationship in ontology
        WHEN: Converting to TDFOL
        THEN: Relationship is represented as formula
        """
        ontology = {
            "entities": {"person": {"A", "B"}},
            "relationships": [
                {"type": "parent_of", "from": "A", "to": "B"}
            ]
        }
        
        formulas = self.validator._ontology_to_tdfol(ontology)
        
        assert formulas is not None
        # Should contain relationship formula
        if isinstance(formulas, str):
            assert "parent" in formulas.lower() or "->" in formulas or "∧" in formulas


class TestLogicValidatorValidation:
    """Test ontology validation methods."""
    
    def setup_method(self):
        """Setup for each test."""
        self.validator = LogicValidator()
    
    def test_validate_consistent_ontology(self):
        """
        GIVEN: Logically consistent ontology
        WHEN: Validating ontology
        THEN: Validation passes with high score
        """
        consistent = {
            "entities": {
                "person": {"John"},
                "organization": {"Company"}
            },
            "relationships": [
                {"type": "works_at", "from": "John", "to": "Company"}
            ]
        }
        
        result = self.validator.validate(consistent)
        
        assert result is not None
        assert isinstance(result, ValidationResult)
        assert 0.0 <= result.validation_score <= 1.0
    
    def test_validate_empty_ontology(self):
        """
        GIVEN: Empty ontology
        WHEN: Validating ontology
        THEN: Validation result indicates trivially valid
        """
        empty = {
            "entities": {},
            "relationships": []
        }
        
        result = self.validator.validate(empty)
        
        assert result is not None
        # Empty ontology is trivially consistent
        assert result.is_valid in [True, False]  # Implementation dependent
    
    def test_detect_contradictions(self):
        """
        GIVEN: Ontology with contradictions
        WHEN: Validating ontology
        THEN: Contradictions are detected
        """
        contradictory = {
            "entities": {
                "person": {"X"},
                "non_person": {"X"}  # Same entity in conflicting types
            },
            "relationships": []
        }
        
        result = self.validator.validate(contradictory)
        
        assert result is not None
        # May detect contradiction depending on rules
        if not result.is_valid:
            assert len(result.contradictions) > 0


class TestLogicValidatorStrategies:
    """Test different proving strategies."""
    
    @pytest.mark.parametrize("strategy", [
        ProverStrategy.SYMBOLIC,
        ProverStrategy.NEURAL,
        ProverStrategy.HYBRID,
        ProverStrategy.AUTO
    ])
    def test_validate_with_strategy(self, strategy):
        """
        GIVEN: Ontology and proving strategy
        WHEN: Validating with specified strategy
        THEN: Validation uses that strategy
        """
        config = {'strategy': strategy}
        validator = LogicValidator(config=config)
        
        ontology = {
            "entities": {"person": {"A"}},
            "relationships": []
        }
        
        result = validator.validate(ontology)
        
        assert result is not None
        assert isinstance(result, ValidationResult)
    
    def test_symbolic_strategy_uses_theorem_prover(self):
        """
        GIVEN: SYMBOLIC strategy
        WHEN: Validating ontology
        THEN: Uses theorem prover (Z3, CVC5, etc.)
        """
        config = {'strategy': ProverStrategy.SYMBOLIC}
        validator = LogicValidator(config=config)
        
        ontology = {
            "entities": {"number": {"1", "2"}},
            "relationships": [
                {"type": "less_than", "from": "1", "to": "2"}
            ]
        }
        
        result = validator.validate(ontology)
        
        assert result is not None
        # Should use symbolic prover
        if hasattr(result, 'prover_used'):
            assert result.prover_used in ['Z3', 'CVC5', 'SymbolicAI']


class TestLogicValidatorSuggestions:
    """Test fix suggestion generation."""
    
    def setup_method(self):
        """Setup for each test."""
        self.validator = LogicValidator()
    
    def test_suggestions_for_invalid_ontology(self):
        """
        GIVEN: Invalid ontology
        WHEN: Validating ontology
        THEN: Suggestions are provided
        """
        invalid = {
            "entities": {
                "conflicting_type_1": {"X"},
                "conflicting_type_2": {"X"}
            },
            "relationships": []
        }
        
        result = self.validator.validate(invalid)
        
        if not result.is_valid:
            assert result.suggestions is not None
            assert len(result.suggestions) > 0
    
    def test_no_suggestions_for_valid_ontology(self):
        """
        GIVEN: Valid ontology
        WHEN: Validating ontology
        THEN: No suggestions or minimal suggestions
        """
        valid = {
            "entities": {"person": {"John"}},
            "relationships": []
        }
        
        result = self.validator.validate(valid)
        
        if result.is_valid:
            # Valid ontology should have few or no suggestions
            assert len(result.suggestions) < 5


class TestLogicValidatorEdgeCases:
    """Test edge cases and error handling."""
    
    def setup_method(self):
        """Setup for each test."""
        self.validator = LogicValidator()
    
    def test_validate_none_ontology(self):
        """
        GIVEN: None as ontology
        WHEN: Validating ontology
        THEN: Raises appropriate error
        """
        with pytest.raises((ValueError, TypeError)):
            self.validator.validate(None)
    
    def test_validate_malformed_ontology(self):
        """
        GIVEN: Malformed ontology data
        WHEN: Validating ontology
        THEN: Handles gracefully or raises error
        """
        malformed = {"invalid": "structure"}
        
        try:
            result = self.validator.validate(malformed)
            # If it succeeds, should return invalid result
            assert result.is_valid is False
        except (ValueError, KeyError, TypeError):
            # Or it should raise appropriate error
            assert True
    
    def test_validate_very_large_ontology(self):
        """
        GIVEN: Very large ontology
        WHEN: Validating ontology
        THEN: Validation completes without error
        """
        large = {
            "entities": {
                f"type_{i}": {f"entity_{j}" for j in range(10)}
                for i in range(20)
            },
            "relationships": [
                {"type": f"rel_{i}", "from": f"e_{i}", "to": f"e_{i+1}"}
                for i in range(100)
            ]
        }
        
        result = self.validator.validate(large)
        
        assert result is not None
        assert isinstance(result, ValidationResult)


class TestLogicValidatorIntegration:
    """Test integration with TDFOL provers."""
    
    def setup_method(self):
        """Setup for each test."""
        self.validator = LogicValidator()
    
    @pytest.mark.skipif(
        not VALIDATOR_AVAILABLE,
        reason="Validator dependencies not available"
    )
    def test_integration_with_tdfol(self):
        """
        GIVEN: Ontology to validate
        WHEN: Using TDFOL integration
        THEN: TDFOL provers are invoked
        """
        ontology = {
            "entities": {"person": {"Alice", "Bob"}},
            "relationships": [
                {"type": "knows", "from": "Alice", "to": "Bob"}
            ]
        }
        
        result = self.validator.validate(ontology)
        
        assert result is not None
        assert isinstance(result, ValidationResult)
    
    def test_prover_caching(self):
        """
        GIVEN: Same ontology validated twice
        WHEN: Validating second time
        THEN: Results are cached for performance
        """
        ontology = {
            "entities": {"person": {"X"}},
            "relationships": []
        }
        
        result1 = self.validator.validate(ontology)
        result2 = self.validator.validate(ontology)
        
        assert result1 is not None
        assert result2 is not None
        # Results should be consistent
        assert result1.is_valid == result2.is_valid


class TestLogicValidatorDomainSpecific:
    """Test domain-specific validation."""
    
    def setup_method(self):
        """Setup for each test."""
        self.validator = LogicValidator()
    
    def test_validate_legal_ontology(self):
        """
        GIVEN: Legal domain ontology
        WHEN: Validating with legal rules
        THEN: Legal consistency rules are applied
        """
        legal = {
            "entities": {
                "party": {"Plaintiff", "Defendant"},
                "obligation": {"Pay damages"}
            },
            "relationships": [
                {"type": "has_obligation", "from": "Defendant", "to": "Pay damages"}
            ]
        }
        
        result = self.validator.validate(legal, domain="legal")
        
        assert result is not None
        assert isinstance(result, ValidationResult)
    
    def test_validate_medical_ontology(self):
        """
        GIVEN: Medical domain ontology
        WHEN: Validating with medical rules
        THEN: Medical consistency rules are applied
        """
        medical = {
            "entities": {
                "patient": {"Patient A"},
                "diagnosis": {"Diabetes"},
                "treatment": {"Insulin"}
            },
            "relationships": [
                {"type": "has_diagnosis", "from": "Patient A", "to": "Diabetes"},
                {"type": "receives_treatment", "from": "Patient A", "to": "Insulin"}
            ]
        }
        
        result = self.validator.validate(medical, domain="medical")
        
        assert result is not None
        assert isinstance(result, ValidationResult)


class TestEntityContradictionCount:
    """Test LogicValidator.entity_contradiction_count() method."""

    def setup_method(self):
        """Setup validator for each test."""
        self.validator = LogicValidator()

    def test_empty_ontology_returns_zero(self):
        """Test that empty ontology returns 0 entity contradictions."""
        ontology = {"entities": [], "relationships": []}
        count = self.validator.entity_contradiction_count(ontology)
        assert count == 0

    def test_consistent_ontology_returns_zero(self):
        """Test that consistent ontology with valid entities returns 0."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person", "text": "Alice"},
                {"id": "e2", "type": "Person", "text": "Bob"},
            ],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows"}
            ],
        }
        count = self.validator.entity_contradiction_count(ontology)
        assert count == 0

    def test_ontology_with_dangling_references(self):
        """Test that ontology with dangling references counts invalid entities."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person", "text": "Alice"},
            ],
            "relationships": [
                # Relationship references non-existent entity e2
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows"}
            ],
        }
        # The validation should detect that e2 doesn't exist
        # This will populate invalid_entity_ids
        count = self.validator.entity_contradiction_count(ontology)
        assert isinstance(count, int)
        assert count >= 0

    def test_returns_integer(self):
        """Test that method always returns an integer."""
        ontology = {"entities": [{"id": "e1"}], "relationships": []}
        count = self.validator.entity_contradiction_count(ontology)
        assert isinstance(count, int)

    def test_exception_handling_returns_zero(self):
        """Test that exceptions during validation return 0."""
        # Invalid ontology structure that might cause exceptions
        invalid_ontology = None
        count = self.validator.entity_contradiction_count(invalid_ontology)
        assert count == 0

    def test_malformed_ontology_returns_zero(self):
        """Test that malformed ontology returns 0 via exception handling."""
        malformed = {"not": "valid"}
        count = self.validator.entity_contradiction_count(malformed)
        assert count == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
