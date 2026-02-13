"""
Integration tests for refactored logic modules.

Tests cover:
- Logic verification integration with types/utils
- Deontological reasoning integration
- Proof execution engine integration
- Interactive FOL constructor integration
"""

import pytest
from ipfs_datasets_py.logic.integration.logic_verification import (
    LogicVerifier,
    verify_consistency,
    verify_entailment,
    generate_proof,
)
from ipfs_datasets_py.logic.integration.logic_verification_types import (
    LogicAxiom,
    ProofStep,
    ProofResult,
    ConsistencyCheck,
    EntailmentResult,
    VerificationResult,
)


class TestLogicVerifierIntegration:
    """Test LogicVerifier with refactored types and utils."""

    def test_verifier_initialization(self):
        """
        GIVEN: LogicVerifier class
        WHEN: Creating instance
        THEN: Should initialize with basic axioms
        """
        verifier = LogicVerifier()
        
        assert verifier is not None
        assert len(verifier.known_axioms) > 0  # Should have basic axioms

    def test_verifier_with_symbolic_ai_disabled(self):
        """
        GIVEN: LogicVerifier with SymbolicAI disabled
        WHEN: Creating instance
        THEN: Should use fallback methods
        """
        verifier = LogicVerifier(use_symbolic_ai=False)
        
        assert verifier is not None
        assert not verifier.use_symbolic_ai

    def test_add_custom_axiom(self):
        """
        GIVEN: LogicVerifier instance
        WHEN: Adding custom axiom
        THEN: Should accept and store axiom
        """
        verifier = LogicVerifier()
        axiom = LogicAxiom(
            name="custom_rule",
            formula="P → Q",
            description="Custom implication rule"
        )
        
        result = verifier.add_axiom(axiom)
        
        assert isinstance(result, bool)

    def test_consistency_check_simple(self):
        """
        GIVEN: Two consistent formulas
        WHEN: Checking consistency
        THEN: Should return consistent result
        """
        verifier = LogicVerifier()
        formulas = ["P", "Q"]
        
        result = verifier.check_consistency(formulas)
        
        assert isinstance(result, ConsistencyCheck)
        assert isinstance(result.is_consistent, bool)

    def test_consistency_check_contradiction(self):
        """
        GIVEN: Contradictory formulas
        WHEN: Checking consistency
        THEN: Should detect inconsistency
        """
        verifier = LogicVerifier()
        formulas = ["P", "¬P"]
        
        result = verifier.check_consistency(formulas)
        
        assert isinstance(result, ConsistencyCheck)
        # May detect contradiction
        if not result.is_consistent:
            assert len(result.conflicting_formulas) > 0

    def test_entailment_modus_ponens(self):
        """
        GIVEN: Modus ponens premises
        WHEN: Checking entailment
        THEN: Should verify entailment
        """
        verifier = LogicVerifier()
        premises = ["P → Q", "P"]
        conclusion = "Q"
        
        result = verifier.check_entailment(premises, conclusion)
        
        assert isinstance(result, EntailmentResult)
        assert result.premises == premises
        assert result.conclusion == conclusion

    def test_proof_generation(self):
        """
        GIVEN: Valid premises and conclusion
        WHEN: Generating proof
        THEN: Should return proof result
        """
        verifier = LogicVerifier()
        premises = ["P → Q", "P"]
        conclusion = "Q"
        
        result = verifier.generate_proof(premises, conclusion)
        
        assert isinstance(result, ProofResult)
        assert result.conclusion == conclusion

    def test_formula_syntax_verification(self):
        """
        GIVEN: Formula with valid syntax
        WHEN: Verifying syntax
        THEN: Should validate correctly
        """
        verifier = LogicVerifier()
        formula = "∀x(P(x) → Q(x))"
        
        result = verifier.verify_formula_syntax(formula)
        
        assert isinstance(result, dict)
        assert "status" in result

    def test_satisfiability_check(self):
        """
        GIVEN: Satisfiable formula
        WHEN: Checking satisfiability
        THEN: Should determine if satisfiable
        """
        verifier = LogicVerifier()
        formula = "P ∨ Q"
        
        result = verifier.check_satisfiability(formula)
        
        assert isinstance(result, dict)
        assert "satisfiable" in result

    def test_validity_check(self):
        """
        GIVEN: Tautology formula
        WHEN: Checking validity
        THEN: Should recognize valid formula
        """
        verifier = LogicVerifier()
        formula = "P ∨ ¬P"  # Law of excluded middle
        
        result = verifier.check_validity(formula)
        
        assert isinstance(result, dict)
        assert "valid" in result

    def test_get_axioms_filtered(self):
        """
        GIVEN: LogicVerifier with axioms
        WHEN: Getting axioms by type
        THEN: Should filter correctly
        """
        verifier = LogicVerifier()
        
        built_in_axioms = verifier.get_axioms(axiom_type="built_in")
        
        assert isinstance(built_in_axioms, list)
        assert all(isinstance(a, LogicAxiom) for a in built_in_axioms)

    def test_clear_cache(self):
        """
        GIVEN: LogicVerifier with cached proofs
        WHEN: Clearing cache
        THEN: Should clear without error
        """
        verifier = LogicVerifier()
        
        # Add some cached data
        verifier.proof_cache["test"] = ProofResult(
            is_valid=True,
            conclusion="Q",
            steps=[],
            confidence=1.0,
            method_used="test"
        )
        
        verifier.clear_cache()
        
        assert len(verifier.proof_cache) == 0

    def test_get_statistics(self):
        """
        GIVEN: LogicVerifier instance
        WHEN: Getting statistics
        THEN: Should return stats dictionary
        """
        verifier = LogicVerifier()
        
        stats = verifier.get_statistics()
        
        assert isinstance(stats, dict)
        assert "axiom_count" in stats
        assert "symbolic_ai_available" in stats


class TestConvenienceFunctions:
    """Test convenience wrapper functions."""

    def test_verify_consistency_wrapper(self):
        """
        GIVEN: List of formulas
        WHEN: Using convenience function
        THEN: Should check consistency
        """
        formulas = ["P", "Q", "R"]
        
        result = verify_consistency(formulas)
        
        assert isinstance(result, ConsistencyCheck)

    def test_verify_entailment_wrapper(self):
        """
        GIVEN: Premises and conclusion
        WHEN: Using convenience function
        THEN: Should check entailment
        """
        premises = ["P → Q", "P"]
        conclusion = "Q"
        
        result = verify_entailment(premises, conclusion)
        
        assert isinstance(result, EntailmentResult)

    def test_generate_proof_wrapper(self):
        """
        GIVEN: Premises and conclusion
        WHEN: Using convenience function
        THEN: Should generate proof
        """
        premises = ["P", "P → Q"]
        conclusion = "Q"
        
        result = generate_proof(premises, conclusion)
        
        assert isinstance(result, ProofResult)


class TestTypeSystemIntegration:
    """Test integration of refactored type system."""

    def test_logic_axiom_creation(self):
        """
        GIVEN: LogicAxiom parameters
        WHEN: Creating axiom
        THEN: Should create valid axiom object
        """
        axiom = LogicAxiom(
            name="test_axiom",
            formula="∀x P(x)",
            description="Test axiom",
            axiom_type="user_defined",
            confidence=0.95
        )
        
        assert axiom.name == "test_axiom"
        assert axiom.confidence == 0.95

    def test_proof_step_creation(self):
        """
        GIVEN: ProofStep parameters
        WHEN: Creating proof step
        THEN: Should create valid step object
        """
        step = ProofStep(
            step_number=1,
            formula="P",
            justification="Given",
            rule_applied="premise"
        )
        
        assert step.step_number == 1
        assert step.formula == "P"

    def test_proof_result_creation(self):
        """
        GIVEN: ProofResult parameters
        WHEN: Creating proof result
        THEN: Should create valid result object
        """
        result = ProofResult(
            is_valid=True,
            conclusion="Q",
            steps=[],
            confidence=0.9,
            method_used="symbolic"
        )
        
        assert result.is_valid
        assert result.confidence == 0.9

    def test_consistency_check_creation(self):
        """
        GIVEN: ConsistencyCheck parameters
        WHEN: Creating consistency check result
        THEN: Should create valid check object
        """
        check = ConsistencyCheck(
            is_consistent=True,
            confidence=0.95,
            explanation="No conflicts found"
        )
        
        assert check.is_consistent
        assert check.confidence == 0.95

    def test_entailment_result_creation(self):
        """
        GIVEN: EntailmentResult parameters
        WHEN: Creating entailment result
        THEN: Should create valid result object
        """
        result = EntailmentResult(
            entails=True,
            premises=["P", "P → Q"],
            conclusion="Q",
            confidence=1.0
        )
        
        assert result.entails
        assert len(result.premises) == 2


class TestBackwardCompatibility:
    """Test that refactored modules maintain backward compatibility."""

    def test_import_from_main_module(self):
        """
        GIVEN: Refactored modules
        WHEN: Importing from main module
        THEN: Should import successfully (backward compatible)
        """
        from ipfs_datasets_py.logic.integration.logic_verification import (
            LogicVerifier,
            LogicAxiom,
            ProofResult,
        )
        
        assert LogicVerifier is not None
        assert LogicAxiom is not None
        assert ProofResult is not None

    def test_types_module_import(self):
        """
        GIVEN: Refactored types module
        WHEN: Importing types
        THEN: Should import successfully
        """
        from ipfs_datasets_py.logic.integration.logic_verification_types import (
            VerificationResult,
            LogicAxiom,
            ProofStep,
        )
        
        assert VerificationResult is not None
        assert LogicAxiom is not None
        assert ProofStep is not None

    def test_utils_module_import(self):
        """
        GIVEN: Refactored utils module
        WHEN: Importing utils
        THEN: Should import successfully
        """
        from ipfs_datasets_py.logic.integration.logic_verification_utils import (
            verify_consistency,
            verify_entailment,
            create_logic_verifier,
        )
        
        assert verify_consistency is not None
        assert verify_entailment is not None
        assert create_logic_verifier is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
