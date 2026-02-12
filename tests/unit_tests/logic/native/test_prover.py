"""
Unit tests for native theorem prover.

These tests validate the theorem proving functionality.
"""

import pytest
import sys
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from ipfs_datasets_py.logic.native import (
    TheoremProver,
    ProofResult,
    DCECNamespace,
    AtomicFormula,
    DeonticFormula,
    ConnectiveFormula,
    DeonticOperator,
    LogicalConnective,
    VariableTerm,
)


class TestTheoremProver:
    """Test suite for TheoremProver."""
    
    def test_prover_initialization(self):
        """
        GIVEN a theorem prover
        WHEN initializing
        THEN it should be ready to use
        """
        prover = TheoremProver()
        
        assert prover.initialize() is True
        assert prover._initialized is True
        assert len(prover.proof_attempts) == 0
    
    def test_simple_modus_ponens(self):
        """
        GIVEN axioms P and P→Q
        WHEN proving Q
        THEN it should succeed with Modus Ponens
        """
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        
        p = AtomicFormula(p_pred, [])
        q = AtomicFormula(q_pred, [])
        implies = ConnectiveFormula(LogicalConnective.IMPLIES, [p, q])
        
        prover = TheoremProver()
        attempt = prover.prove_theorem(goal=q, axioms=[p, implies])
        
        assert attempt.result == ProofResult.PROVED
        assert attempt.proof_tree is not None
        assert len(attempt.proof_tree.steps) >= 3
    
    def test_goal_is_axiom(self):
        """
        GIVEN goal that is already an axiom
        WHEN proving
        THEN it should succeed immediately
        """
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        p = AtomicFormula(p_pred, [])
        
        prover = TheoremProver()
        attempt = prover.prove_theorem(goal=p, axioms=[p])
        
        assert attempt.result == ProofResult.PROVED
        assert attempt.proof_tree is not None
    
    def test_unprovable_goal(self):
        """
        GIVEN axioms that don't imply goal
        WHEN proving
        THEN result should be UNKNOWN
        """
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        r_pred = namespace.add_predicate("R", [])
        
        p = AtomicFormula(p_pred, [])
        q = AtomicFormula(q_pred, [])
        r = AtomicFormula(r_pred, [])
        
        prover = TheoremProver()
        attempt = prover.prove_theorem(goal=r, axioms=[p, q])
        
        assert attempt.result == ProofResult.UNKNOWN
    
    def test_simplification(self):
        """
        GIVEN axiom P∧Q
        WHEN proving P (or Q)
        THEN it should succeed with Simplification
        """
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        
        p = AtomicFormula(p_pred, [])
        q = AtomicFormula(q_pred, [])
        conjunction = ConnectiveFormula(LogicalConnective.AND, [p, q])
        
        prover = TheoremProver()
        attempt = prover.prove_theorem(goal=p, axioms=[conjunction])
        
        assert attempt.result == ProofResult.PROVED
    
    def test_proof_statistics(self):
        """
        GIVEN multiple proof attempts
        WHEN getting statistics
        THEN they should be accurate
        """
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        
        p = AtomicFormula(p_pred, [])
        q = AtomicFormula(q_pred, [])
        
        prover = TheoremProver()
        
        # Successful proof
        implies = ConnectiveFormula(LogicalConnective.IMPLIES, [p, q])
        prover.prove_theorem(goal=q, axioms=[p, implies])
        
        # Failed proof
        prover.prove_theorem(goal=q, axioms=[p])
        
        stats = prover.get_statistics()
        
        assert stats["total_attempts"] == 2
        assert stats["proved"] == 1
        assert stats["unknown"] == 1
    
    def test_proof_tree_structure(self):
        """
        GIVEN a successful proof
        WHEN examining proof tree
        THEN it should have proper structure
        """
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        
        p = AtomicFormula(p_pred, [])
        q = AtomicFormula(q_pred, [])
        implies = ConnectiveFormula(LogicalConnective.IMPLIES, [p, q])
        
        prover = TheoremProver()
        attempt = prover.prove_theorem(goal=q, axioms=[p, implies])
        
        tree = attempt.proof_tree
        assert tree.goal == q
        assert len(tree.axioms) == 2
        assert len(tree.steps) >= 3
        assert tree.result == ProofResult.PROVED
    
    def test_deontic_formula_proving(self):
        """
        GIVEN deontic formulas
        WHEN proving with them
        THEN prover should handle them
        """
        namespace = DCECNamespace()
        act_pred = namespace.add_predicate("act", ["Agent"])
        agent_var = namespace.add_variable("x", "Agent")
        
        base = AtomicFormula(act_pred, [VariableTerm(agent_var)])
        obligation = DeonticFormula(DeonticOperator.OBLIGATION, base)
        
        prover = TheoremProver()
        attempt = prover.prove_theorem(goal=obligation, axioms=[obligation])
        
        assert attempt.result == ProofResult.PROVED


class TestProofResult:
    """Test suite for ProofResult enum."""
    
    def test_proof_result_values(self):
        """
        GIVEN ProofResult enum
        WHEN accessing values
        THEN they should be correct
        """
        assert ProofResult.PROVED.value == "proved"
        assert ProofResult.DISPROVED.value == "disproved"
        assert ProofResult.TIMEOUT.value == "timeout"
        assert ProofResult.UNKNOWN.value == "unknown"
        assert ProofResult.ERROR.value == "error"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
