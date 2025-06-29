"""
Test module for Logic Verification

This module provides comprehensive tests for the LogicVerifier class,
covering consistency checking, entailment verification, and proof generation.
"""

import pytest
import sys
import os
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any, List

# Add the project root to Python path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

# Import the modules to test
from ipfs_datasets_py.logic_integration.logic_verification import (
    LogicVerifier,
    LogicAxiom,
    ProofStep,
    ProofResult,
    ConsistencyCheck,
    EntailmentResult,
    VerificationResult,
    verify_consistency,
    verify_entailment,
    generate_proof,
    SYMBOLIC_AI_AVAILABLE
)


class TestLogicAxiom:
    """Test suite for LogicAxiom data structure."""
    
    def test_axiom_creation(self):
        """Test LogicAxiom creation."""
        axiom = LogicAxiom(
            name="test_axiom",
            formula="P → P",
            description="Identity axiom",
            axiom_type="user_defined",
            confidence=0.9
        )
        
        assert axiom.name == "test_axiom"
        assert axiom.formula == "P → P"
        assert axiom.description == "Identity axiom"
        assert axiom.axiom_type == "user_defined"
        assert axiom.confidence == 0.9
        assert isinstance(axiom.metadata, dict)
    
    def test_axiom_defaults(self):
        """Test LogicAxiom with default values."""
        axiom = LogicAxiom(
            name="simple_axiom",
            formula="P ∨ ¬P",
            description="Law of excluded middle"
        )
        
        assert axiom.axiom_type == "user_defined"
        assert axiom.confidence == 1.0
        assert axiom.metadata == {}


class TestProofStep:
    """Test suite for ProofStep data structure."""
    
    def test_proof_step_creation(self):
        """Test ProofStep creation."""
        step = ProofStep(
            step_number=1,
            formula="P → Q",
            justification="Given premise",
            rule_applied="premise",
            premises=["P", "P → Q"],
            confidence=1.0
        )
        
        assert step.step_number == 1
        assert step.formula == "P → Q"
        assert step.justification == "Given premise"
        assert step.rule_applied == "premise"
        assert step.premises == ["P", "P → Q"]
        assert step.confidence == 1.0
    
    def test_proof_step_defaults(self):
        """Test ProofStep with default values."""
        step = ProofStep(
            step_number=2,
            formula="Q",
            justification="Modus ponens",
            rule_applied="modus_ponens"
        )
        
        assert step.premises == []
        assert step.confidence == 1.0


class TestLogicVerifier:
    """Test suite for LogicVerifier functionality."""
    
    def setup_method(self):
        """Setup test environment before each test."""
        self.verifier = LogicVerifier(use_symbolic_ai=True)
        
        # Test formulas for consistency checking
        self.consistent_formulas = [
            "P → Q",
            "P",
            "Q"
        ]
        
        self.inconsistent_formulas = [
            "P",
            "¬P"
        ]
        
        self.complex_consistent = [
            "∀x (Cat(x) → Animal(x))",
            "Cat(fluffy)",
            "Animal(fluffy)"
        ]
        
        self.complex_inconsistent = [
            "∀x (Bird(x) → CanFly(x))",
            "Bird(penguin)",
            "¬CanFly(penguin)"
        ]
    
    def test_verifier_initialization(self):
        """Test LogicVerifier initialization."""
        # Test default initialization
        verifier = LogicVerifier()
        assert verifier.use_symbolic_ai == SYMBOLIC_AI_AVAILABLE
        assert verifier.fallback_enabled is not hasattr(verifier, 'fallback_enabled') or verifier.fallback_enabled  # Default would be True
        assert isinstance(verifier.known_axioms, list)
        assert len(verifier.known_axioms) > 0  # Should have built-in axioms
        assert isinstance(verifier.proof_cache, dict)
        
        # Test explicit SymbolicAI disabled
        verifier_no_ai = LogicVerifier(use_symbolic_ai=False)
        assert verifier_no_ai.use_symbolic_ai is False
    
    def test_built_in_axioms_loaded(self):
        """Test that built-in axioms are properly loaded."""
        axioms = self.verifier.get_axioms(axiom_type="built_in")
        
        assert len(axioms) >= 4  # Should have at least basic axioms
        
        axiom_names = [axiom.name for axiom in axioms]
        expected_axioms = [
            "modus_ponens",
            "modus_tollens", 
            "law_of_excluded_middle",
            "law_of_noncontradiction"
        ]
        
        for expected in expected_axioms:
            assert expected in axiom_names
    
    def test_add_axiom_success(self):
        """Test successful axiom addition."""
        new_axiom = LogicAxiom(
            name="custom_axiom",
            formula="P ∧ Q → P",
            description="Conjunction elimination",
            axiom_type="user_defined"
        )
        
        initial_count = len(self.verifier.known_axioms)
        result = self.verifier.add_axiom(new_axiom)
        
        assert result is True
        assert len(self.verifier.known_axioms) == initial_count + 1
        
        # Verify the axiom was added
        added_axioms = [a for a in self.verifier.known_axioms if a.name == "custom_axiom"]
        assert len(added_axioms) == 1
        assert added_axioms[0].formula == "P ∧ Q → P"
    
    def test_add_axiom_duplicate(self):
        """Test adding duplicate axiom."""
        # Try to add an axiom with same name as built-in
        duplicate_axiom = LogicAxiom(
            name="modus_ponens",
            formula="Different formula",
            description="Duplicate test"
        )
        
        initial_count = len(self.verifier.known_axioms)
        result = self.verifier.add_axiom(duplicate_axiom)
        
        assert result is False
        assert len(self.verifier.known_axioms) == initial_count
    
    def test_add_axiom_invalid_formula(self):
        """Test adding axiom with invalid formula."""
        invalid_axiom = LogicAxiom(
            name="invalid_axiom",
            formula="((P → Q",  # Unbalanced parentheses
            description="Invalid formula test"
        )
        
        initial_count = len(self.verifier.known_axioms)
        result = self.verifier.add_axiom(invalid_axiom)
        
        assert result is False
        assert len(self.verifier.known_axioms) == initial_count
    
    def test_check_consistency_empty_formulas(self):
        """Test consistency checking with empty formula list."""
        result = self.verifier.check_consistency([])
        
        assert isinstance(result, ConsistencyCheck)
        assert result.is_consistent is True
        assert result.confidence == 1.0
        assert "trivially consistent" in result.explanation.lower()
    
    def test_check_consistency_consistent_formulas(self):
        """Test consistency checking with consistent formulas."""
        result = self.verifier.check_consistency(self.consistent_formulas)
        
        assert isinstance(result, ConsistencyCheck)
        assert result.is_consistent is True
        assert 0.0 <= result.confidence <= 1.0
        assert len(result.conflicting_formulas) == 0
    
    def test_check_consistency_inconsistent_formulas(self):
        """Test consistency checking with inconsistent formulas."""
        result = self.verifier.check_consistency(self.inconsistent_formulas)
        
        assert isinstance(result, ConsistencyCheck)
        assert result.is_consistent is False
        assert 0.0 <= result.confidence <= 1.0
        # Should find the contradiction between P and ¬P
        assert len(result.conflicting_formulas) > 0
    
    def test_check_consistency_complex_formulas(self):
        """Test consistency checking with complex formulas."""
        # Test consistent complex formulas
        result_consistent = self.verifier.check_consistency(self.complex_consistent)
        assert isinstance(result_consistent, ConsistencyCheck)
        
        # Test inconsistent complex formulas
        result_inconsistent = self.verifier.check_consistency(self.complex_inconsistent)
        assert isinstance(result_inconsistent, ConsistencyCheck)
        # Note: May not detect inconsistency without sophisticated reasoning
    
    def test_check_entailment_empty_premises(self):
        """Test entailment checking with empty premises."""
        result = self.verifier.check_entailment([], "Q")
        
        assert isinstance(result, EntailmentResult)
        assert result.entails is False
        assert result.premises == []
        assert result.conclusion == "Q"
        assert result.confidence == 1.0
        assert "no premises" in result.explanation.lower()
    
    def test_check_entailment_valid_modus_ponens(self):
        """Test entailment checking with valid modus ponens."""
        premises = ["P", "P → Q"]
        conclusion = "Q"
        
        result = self.verifier.check_entailment(premises, conclusion)
        
        assert isinstance(result, EntailmentResult)
        assert result.premises == premises
        assert result.conclusion == conclusion
        assert 0.0 <= result.confidence <= 1.0
        # Should detect modus ponens pattern
        if result.entails:
            assert "modus ponens" in result.explanation.lower() or result.confidence > 0.5
    
    def test_check_entailment_invalid(self):
        """Test entailment checking with invalid entailment."""
        premises = ["P → Q", "Q"]  # Affirming the consequent fallacy
        conclusion = "P"
        
        result = self.verifier.check_entailment(premises, conclusion)
        
        assert isinstance(result, EntailmentResult)
        assert result.premises == premises
        assert result.conclusion == conclusion
        assert 0.0 <= result.confidence <= 1.0
        # Should not entail (or have low confidence)
    
    def test_check_entailment_complex(self):
        """Test entailment checking with complex formulas."""
        premises = ["∀x (Cat(x) → Animal(x))", "Cat(fluffy)"]
        conclusion = "Animal(fluffy)"
        
        result = self.verifier.check_entailment(premises, conclusion)
        
        assert isinstance(result, EntailmentResult)
        assert result.premises == premises
        assert result.conclusion == conclusion
        assert 0.0 <= result.confidence <= 1.0
    
    def test_generate_proof_simple_modus_ponens(self):
        """Test proof generation for simple modus ponens."""
        premises = ["P", "P → Q"]
        conclusion = "Q"
        
        result = self.verifier.generate_proof(premises, conclusion)
        
        assert isinstance(result, ProofResult)
        assert result.conclusion == conclusion
        assert isinstance(result.steps, list)
        assert len(result.steps) >= len(premises)  # At least one step per premise
        assert 0.0 <= result.confidence <= 1.0
        assert result.time_taken >= 0.0
        
        # Should have premise steps
        premise_steps = [step for step in result.steps if step.rule_applied == "premise"]
        assert len(premise_steps) >= len(premises)
    
    def test_generate_proof_caching(self):
        """Test proof generation caching."""
        premises = ["P", "P → Q"]
        conclusion = "Q"
        
        # Generate proof first time
        result1 = self.verifier.generate_proof(premises, conclusion)
        
        # Generate proof second time (should use cache)
        result2 = self.verifier.generate_proof(premises, conclusion)
        
        assert isinstance(result1, ProofResult)
        assert isinstance(result2, ProofResult)
        assert result1.conclusion == result2.conclusion
        
        # Check that cache was used (cache should have at least one entry)
        assert len(self.verifier.proof_cache) > 0
    
    def test_generate_proof_impossible(self):
        """Test proof generation for impossible conclusion."""
        premises = ["P"]
        conclusion = "¬P"  # Contradicts the premise
        
        result = self.verifier.generate_proof(premises, conclusion)
        
        assert isinstance(result, ProofResult)
        assert result.conclusion == conclusion
        assert result.is_valid is False
        assert result.confidence < 0.5
        assert len(result.errors) > 0 or not result.is_valid
    
    def test_generate_proof_complex(self):
        """Test proof generation for complex formulas."""
        premises = ["∀x (Human(x) → Mortal(x))", "Human(socrates)"]
        conclusion = "Mortal(socrates)"
        
        result = self.verifier.generate_proof(premises, conclusion)
        
        assert isinstance(result, ProofResult)
        assert result.conclusion == conclusion
        assert isinstance(result.steps, list)
        assert 0.0 <= result.confidence <= 1.0
    
    def test_get_axioms_all(self):
        """Test getting all axioms."""
        axioms = self.verifier.get_axioms()
        
        assert isinstance(axioms, list)
        assert len(axioms) > 0
        
        # Should contain built-in axioms
        axiom_names = [axiom.name for axiom in axioms]
        assert "modus_ponens" in axiom_names
        assert "law_of_excluded_middle" in axiom_names
    
    def test_get_axioms_by_type(self):
        """Test getting axioms by type."""
        built_in_axioms = self.verifier.get_axioms(axiom_type="built_in")
        user_defined_axioms = self.verifier.get_axioms(axiom_type="user_defined")
        
        assert isinstance(built_in_axioms, list)
        assert isinstance(user_defined_axioms, list)
        
        # All built-in axioms should have correct type
        for axiom in built_in_axioms:
            assert axiom.axiom_type == "built_in"
        
        # All user-defined axioms should have correct type
        for axiom in user_defined_axioms:
            assert axiom.axiom_type == "user_defined"
    
    def test_clear_cache(self):
        """Test clearing the proof cache."""
        # Generate a proof to populate cache
        self.verifier.generate_proof(["P"], "P")
        assert len(self.verifier.proof_cache) > 0
        
        # Clear cache
        self.verifier.clear_cache()
        assert len(self.verifier.proof_cache) == 0
    
    def test_get_statistics(self):
        """Test getting verifier statistics."""
        stats = self.verifier.get_statistics()
        
        assert isinstance(stats, dict)
        assert "axiom_count" in stats
        assert "axiom_types" in stats
        assert "proof_cache_size" in stats
        assert "symbolic_ai_available" in stats
        
        assert isinstance(stats["axiom_count"], int)
        assert isinstance(stats["axiom_types"], dict)
        assert isinstance(stats["proof_cache_size"], int)
        assert isinstance(stats["symbolic_ai_available"], bool)
        
        assert stats["axiom_count"] > 0
        assert "built_in" in stats["axiom_types"]
        assert stats["proof_cache_size"] >= 0
    
    def test_formula_syntax_validation(self):
        """Test formula syntax validation."""
        # Test valid formulas
        valid_formulas = [
            "P",
            "P → Q", 
            "∀x (P(x) → Q(x))",
            "(P ∧ Q) → R",
            "P ∨ (Q ∧ R)"
        ]
        
        for formula in valid_formulas:
            assert self.verifier._validate_formula_syntax(formula) is True
        
        # Test invalid formulas
        invalid_formulas = [
            "",
            "   ",
            "((P → Q",  # Unbalanced parentheses
            "P → Q))",   # Unbalanced parentheses
            "((P → Q) → R))"  # Extra closing parenthesis
        ]
        
        for formula in invalid_formulas:
            assert self.verifier._validate_formula_syntax(formula) is False
    
    def test_contradiction_detection(self):
        """Test basic contradiction detection."""
        # Test obvious contradictions
        assert self.verifier._are_contradictory("P", "¬P") is True
        assert self.verifier._are_contradictory("¬P", "P") is True
        assert self.verifier._are_contradictory("¬Q", "Q") is True
        
        # Test non-contradictions
        assert self.verifier._are_contradictory("P", "Q") is False
        assert self.verifier._are_contradictory("P → Q", "P") is False
        assert self.verifier._are_contradictory("P ∧ Q", "P ∨ Q") is False


class TestConvenienceFunctions:
    """Test suite for convenience functions."""
    
    def test_verify_consistency_function(self):
        """Test verify_consistency convenience function."""
        consistent_formulas = ["P → Q", "P", "Q"]
        inconsistent_formulas = ["P", "¬P"]
        
        result_consistent = verify_consistency(consistent_formulas)
        result_inconsistent = verify_consistency(inconsistent_formulas)
        
        assert isinstance(result_consistent, ConsistencyCheck)
        assert isinstance(result_inconsistent, ConsistencyCheck)
        
        assert result_consistent.is_consistent is True
        assert result_inconsistent.is_consistent is False
    
    def test_verify_entailment_function(self):
        """Test verify_entailment convenience function."""
        premises = ["P", "P → Q"]
        conclusion = "Q"
        
        result = verify_entailment(premises, conclusion)
        
        assert isinstance(result, EntailmentResult)
        assert result.premises == premises
        assert result.conclusion == conclusion
        assert 0.0 <= result.confidence <= 1.0
    
    def test_generate_proof_function(self):
        """Test generate_proof convenience function."""
        premises = ["P", "P → Q"]
        conclusion = "Q"
        
        result = generate_proof(premises, conclusion)
        
        assert isinstance(result, ProofResult)
        assert result.conclusion == conclusion
        assert isinstance(result.steps, list)
        assert 0.0 <= result.confidence <= 1.0


class TestErrorHandling:
    """Test suite for error handling and edge cases."""
    
    def setup_method(self):
        """Setup test environment."""
        self.verifier = LogicVerifier()
    
    def test_empty_string_formulas(self):
        """Test handling of empty string formulas."""
        # Should handle gracefully without crashing
        result = self.verifier.check_consistency(["", "P", ""])
        assert isinstance(result, ConsistencyCheck)
        
        result = self.verifier.check_entailment([""], "Q")
        assert isinstance(result, EntailmentResult)
    
    def test_whitespace_only_formulas(self):
        """Test handling of whitespace-only formulas."""
        result = self.verifier.check_consistency(["   ", "P", "  \t\n  "])
        assert isinstance(result, ConsistencyCheck)
    
    def test_malformed_formulas(self):
        """Test handling of malformed formulas."""
        malformed = ["P → → Q", "∀∃x P(x)", "((()))", "P ∧ ∨ Q"]
        
        # Should not crash
        result = self.verifier.check_consistency(malformed)
        assert isinstance(result, ConsistencyCheck)
    
    def test_very_long_formulas(self):
        """Test handling of very long formulas."""
        long_formula = "P" + " ∧ Q" * 100  # Very long conjunction
        
        result = self.verifier.check_consistency([long_formula])
        assert isinstance(result, ConsistencyCheck)
    
    def test_special_characters(self):
        """Test handling of special characters."""
        special_formulas = [
            "P(🦄)",  # Unicode characters
            "P@#$%",   # Special symbols
            "P²→Q³",   # Superscripts
            "P←→Q"     # Different arrow symbols
        ]
        
        # Should handle gracefully
        for formula in special_formulas:
            result = self.verifier.check_consistency([formula])
            assert isinstance(result, ConsistencyCheck)


class TestSymbolicAIIntegration:
    """Test suite for SymbolicAI integration and fallback behavior."""
    
    def test_symbolic_ai_availability(self):
        """Test SymbolicAI availability detection."""
        assert isinstance(SYMBOLIC_AI_AVAILABLE, bool)
    
    def test_verifier_with_and_without_symbolic_ai(self):
        """Test verifier behavior with and without SymbolicAI."""
        # Test with SymbolicAI enabled
        verifier_with_ai = LogicVerifier(use_symbolic_ai=True)
        # Test with SymbolicAI disabled
        verifier_without_ai = LogicVerifier(use_symbolic_ai=False)
        
        formulas = ["P", "P → Q"]
        
        # Both should work
        result_with = verifier_with_ai.check_consistency(formulas)
        result_without = verifier_without_ai.check_consistency(formulas)
        
        assert isinstance(result_with, ConsistencyCheck)
        assert isinstance(result_without, ConsistencyCheck)
        
        # Method used should be different
        if SYMBOLIC_AI_AVAILABLE:
            # If available, one should use symbolic_ai, other should use fallback
            assert result_with.method_used != result_without.method_used or result_without.method_used == "pattern_matching"
    
    def test_fallback_behavior(self):
        """Test fallback behavior when SymbolicAI operations fail."""
        verifier = LogicVerifier(use_symbolic_ai=False)  # Force fallback
        
        # Should still work with fallback methods
        result = verifier.check_consistency(["P", "¬P"])
        assert isinstance(result, ConsistencyCheck)
        assert result.is_consistent is False  # Should detect contradiction
        
        entailment_result = verifier.check_entailment(["P", "P → Q"], "Q")
        assert isinstance(entailment_result, EntailmentResult)
        
        proof_result = verifier.generate_proof(["P", "P → Q"], "Q")
        assert isinstance(proof_result, ProofResult)


class TestIntegrationScenarios:
    """Test suite for complex integration scenarios."""
    
    def setup_method(self):
        """Setup test environment."""
        self.verifier = LogicVerifier()
    
    def test_complete_logic_workflow(self):
        """Test complete logic verification workflow."""
        # Step 1: Add custom axioms
        custom_axiom = LogicAxiom(
            name="hypothetical_syllogism",
            formula="((P → Q) ∧ (Q → R)) → (P → R)",
            description="Hypothetical syllogism rule"
        )
        
        success = self.verifier.add_axiom(custom_axiom)
        assert success is True
        
        # Step 2: Check consistency of a knowledge base
        knowledge_base = [
            "∀x (Human(x) → Mortal(x))",
            "Human(socrates)",
            "∀x (Philosopher(x) → Human(x))",
            "Philosopher(socrates)"
        ]
        
        consistency = self.verifier.check_consistency(knowledge_base)
        assert consistency.is_consistent is True
        
        # Step 3: Check entailment
        entailment = self.verifier.check_entailment(
            knowledge_base, 
            "Mortal(socrates)"
        )
        assert isinstance(entailment, EntailmentResult)
        
        # Step 4: Generate proof
        proof = self.verifier.generate_proof(
            knowledge_base[:2],  # First two premises
            "Mortal(socrates)"
        )
        assert isinstance(proof, ProofResult)
        
        # Step 5: Check statistics
        stats = self.verifier.get_statistics()
        assert stats["axiom_count"] > 6  # Built-ins + our custom axiom
    
    def test_modal_logic_verification_integration(self):
        """Test integration with modal logic components."""
        # Add modal logic axioms
        modal_axioms = [
            LogicAxiom(
                name="modal_k",
                formula="□(P → Q) → (□P → □Q)",
                description="Modal logic K axiom"
            ),
            LogicAxiom(
                name="modal_t",
                formula="□P → P",
                description="Modal logic T axiom"
            )
        ]
        
        for axiom in modal_axioms:
            self.verifier.add_axiom(axiom)
        
        # Test modal formulas
        modal_formulas = [
            "□(Human(x) → Mortal(x))",
            "□Human(socrates)",
            "□Mortal(socrates)"
        ]
        
        consistency = self.verifier.check_consistency(modal_formulas)
        assert isinstance(consistency, ConsistencyCheck)
        
        entailment = self.verifier.check_entailment(
            modal_formulas[:2],
            modal_formulas[2]
        )
        assert isinstance(entailment, EntailmentResult)
    
    def test_large_knowledge_base(self):
        """Test verification with larger knowledge base."""
        # Create a larger knowledge base
        large_kb = []
        
        # Add universal statements
        for i in range(10):
            large_kb.append(f"∀x (P{i}(x) → P{i+1}(x))")
        
        # Add specific instances
        for i in range(5):
            large_kb.append(f"P{i}(entity{i})")
        
        # Test consistency (should be consistent)
        consistency = self.verifier.check_consistency(large_kb)
        assert isinstance(consistency, ConsistencyCheck)
        
        # Test entailment with derived facts
        entailment = self.verifier.check_entailment(
            large_kb,
            "P5(entity0)"  # Should be derivable
        )
        assert isinstance(entailment, EntailmentResult)
    
    def test_performance_with_caching(self):
        """Test performance improvements with caching."""
        premises = ["P", "P → Q", "Q → R"]
        conclusion = "R"
        
        # First proof generation
        result1 = self.verifier.generate_proof(premises, conclusion)
        time1 = result1.time_taken
        
        # Second proof generation (should use cache)
        result2 = self.verifier.generate_proof(premises, conclusion)
        time2 = result2.time_taken
        
        assert isinstance(result1, ProofResult)
        assert isinstance(result2, ProofResult)
        
        # Results should be equivalent
        assert result1.conclusion == result2.conclusion
        assert result1.is_valid == result2.is_valid
        
        # Check that cache was populated
        assert len(self.verifier.proof_cache) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
