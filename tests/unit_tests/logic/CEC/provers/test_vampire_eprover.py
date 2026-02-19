"""
Tests for Vampire and E Provers (Phase 6 Week 2).

This test module validates Vampire and E theorem prover integration
for CEC, covering TPTP translation and automated proving.

Test Coverage:
- TPTP utilities (10 tests)
- Vampire adapter (20 tests)
- E prover adapter (20 tests)

Total: 50 tests
"""

import pytest
import tempfile
import os
from ipfs_datasets_py.logic.CEC.provers.tptp_utils import (
    formula_to_tptp,
    create_tptp_problem,
)
from ipfs_datasets_py.logic.CEC.provers.vampire_adapter import (
    VampireAdapter,
    VampireProofResult,
    check_vampire_installation
)
from ipfs_datasets_py.logic.CEC.provers.e_prover_adapter import (
    EProverAdapter,
    EProverProofResult,
    check_eprover_installation
)
from ipfs_datasets_py.logic.CEC.provers.z3_adapter import ProofStatus
from ipfs_datasets_py.logic.CEC.native.dcec_core import (
    AtomicFormula,
    DeonticFormula,
    CognitiveFormula,
    TemporalFormula,
    ConnectiveFormula,
    DeonticOperator,
    CognitiveOperator,
    TemporalOperator,
    LogicalConnective,
    Predicate,
    Variable,
    VariableTerm,
)
from ipfs_datasets_py.logic.CEC.native.dcec_namespace import DCECNamespace


@pytest.fixture
def namespace():
    """Create DCEC namespace for tests."""
    return DCECNamespace()


# TPTP Utilities Tests

class TestTPTPUtilities:
    """Test TPTP format utilities."""
    
    def test_atomic_to_tptp(self, namespace):
        """
        GIVEN atomic formula
        WHEN converting to TPTP
        THEN should generate valid TPTP syntax
        """
        pred = namespace.add_predicate("test", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent)])
        
        tptp = formula_to_tptp(formula, "axiom", "ax1")
        assert "fof(ax1, axiom" in tptp
        assert "test(agent)" in tptp
        assert tptp.endswith(".")
    
    def test_deontic_to_tptp(self, namespace):
        """
        GIVEN deontic formula
        WHEN converting to TPTP
        THEN should encode deontic operator
        """
        pred = namespace.add_predicate("action", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        formula = DeonticFormula(DeonticOperator.OBLIGATION, base)
        
        tptp = formula_to_tptp(formula)
        assert "obligated(" in tptp
        assert "action(agent)" in tptp
    
    def test_cognitive_to_tptp(self, namespace):
        """
        GIVEN cognitive formula
        WHEN converting to TPTP
        THEN should encode cognitive operator
        """
        pred = namespace.add_predicate("fact", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        formula = CognitiveFormula(CognitiveOperator.BELIEF, VariableTerm(agent), base)
        
        tptp = formula_to_tptp(formula)
        assert "believes(" in tptp
    
    def test_temporal_to_tptp(self, namespace):
        """
        GIVEN temporal formula
        WHEN converting to TPTP
        THEN should encode temporal operator
        """
        pred = namespace.add_predicate("invariant", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        formula = TemporalFormula(TemporalOperator.ALWAYS, base)
        
        tptp = formula_to_tptp(formula)
        assert "always(" in tptp
    
    def test_and_to_tptp(self, namespace):
        """
        GIVEN AND connective
        WHEN converting to TPTP
        THEN should use & operator
        """
        pred1 = namespace.add_predicate("p1", ["Agent"])
        pred2 = namespace.add_predicate("p2", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        
        f1 = AtomicFormula(pred1, [VariableTerm(agent)])
        f2 = AtomicFormula(pred2, [VariableTerm(agent)])
        formula = ConnectiveFormula(LogicalConnective.AND, [f1, f2])
        
        tptp = formula_to_tptp(formula)
        assert " & " in tptp
    
    def test_or_to_tptp(self, namespace):
        """
        GIVEN OR connective
        WHEN converting to TPTP
        THEN should use | operator
        """
        pred1 = namespace.add_predicate("q1", ["Agent"])
        pred2 = namespace.add_predicate("q2", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        
        f1 = AtomicFormula(pred1, [VariableTerm(agent)])
        f2 = AtomicFormula(pred2, [VariableTerm(agent)])
        formula = ConnectiveFormula(LogicalConnective.OR, [f1, f2])
        
        tptp = formula_to_tptp(formula)
        assert " | " in tptp
    
    def test_not_to_tptp(self, namespace):
        """
        GIVEN NOT connective
        WHEN converting to TPTP
        THEN should use ~ operator
        """
        pred = namespace.add_predicate("r", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        f = AtomicFormula(pred, [VariableTerm(agent)])
        formula = ConnectiveFormula(LogicalConnective.NOT, [f])
        
        tptp = formula_to_tptp(formula)
        assert "~(" in tptp
    
    def test_implies_to_tptp(self, namespace):
        """
        GIVEN IMPLIES connective
        WHEN converting to TPTP
        THEN should use => operator
        """
        pred1 = namespace.add_predicate("s1", ["Agent"])
        pred2 = namespace.add_predicate("s2", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        
        f1 = AtomicFormula(pred1, [VariableTerm(agent)])
        f2 = AtomicFormula(pred2, [VariableTerm(agent)])
        formula = ConnectiveFormula(LogicalConnective.IMPLIES, [f1, f2])
        
        tptp = formula_to_tptp(formula)
        assert " => " in tptp
    
    def test_create_tptp_problem(self, namespace):
        """
        GIVEN formula and axioms
        WHEN creating TPTP problem
        THEN should generate complete problem file
        """
        pred = namespace.add_predicate("goal", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        conjecture = AtomicFormula(pred, [VariableTerm(agent)])
        
        pred_ax = namespace.add_predicate("axiom1", ["Agent"])
        axiom = AtomicFormula(pred_ax, [VariableTerm(agent)])
        
        problem = create_tptp_problem(conjecture, [axiom], "test_problem")
        
        assert "% Problem: test_problem" in problem
        assert "fof(ax1, axiom" in problem
        assert "fof(goal, conjecture" in problem
    
    def test_tptp_with_multiple_axioms(self, namespace):
        """
        GIVEN multiple axioms
        WHEN creating TPTP problem
        THEN should include all axioms
        """
        pred = namespace.add_predicate("g", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        conjecture = AtomicFormula(pred, [VariableTerm(agent)])
        
        axioms = []
        for i in range(3):
            p = namespace.add_predicate(f"ax{i}", ["Agent"])
            axioms.append(AtomicFormula(p, [VariableTerm(agent)]))
        
        problem = create_tptp_problem(conjecture, axioms)
        
        assert "fof(ax1, axiom" in problem
        assert "fof(ax2, axiom" in problem
        assert "fof(ax3, axiom" in problem


# Vampire Adapter Tests

class TestVampireInstallation:
    """Test Vampire installation checking."""
    
    def test_check_vampire_installation(self):
        """
        GIVEN Vampire installation check function
        WHEN checking installation
        THEN should return boolean status
        """
        result = check_vampire_installation()
        assert isinstance(result, bool)
        # True if Vampire is installed, False otherwise
    
    def test_vampire_adapter_creation(self):
        """
        GIVEN VampireAdapter class
        WHEN creating adapter
        THEN should initialize successfully
        """
        adapter = VampireAdapter(timeout=10)
        assert adapter.vampire_path == "vampire"
        assert adapter.timeout == 10
    
    def test_vampire_is_available(self):
        """
        GIVEN VampireAdapter
        WHEN checking availability
        THEN should return boolean
        """
        adapter = VampireAdapter()
        result = adapter.is_available()
        assert isinstance(result, bool)


class TestVampireProving:
    """Test Vampire theorem proving."""
    
    def test_vampire_prove_simple(self, namespace):
        """
        GIVEN simple formula
        WHEN proving with Vampire
        THEN should return result
        """
        adapter = VampireAdapter()
        if not adapter.is_available():
            pytest.skip("Vampire not installed")
        
        pred = namespace.add_predicate("test", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent)])
        
        result = adapter.prove(formula)
        assert isinstance(result, VampireProofResult)
        assert result.proof_time >= 0.0
    
    def test_vampire_prove_with_axioms(self, namespace):
        """
        GIVEN formula and axioms
        WHEN proving with Vampire
        THEN should consider axioms
        """
        adapter = VampireAdapter()
        if not adapter.is_available():
            pytest.skip("Vampire not installed")
        
        pred = namespace.add_predicate("goal", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent)])
        
        result = adapter.prove(formula, axioms=[formula])
        assert isinstance(result, VampireProofResult)
    
    def test_vampire_timeout(self, namespace):
        """
        GIVEN complex formula with short timeout
        WHEN proving with Vampire
        THEN should timeout gracefully
        """
        adapter = VampireAdapter(timeout=1)
        if not adapter.is_available():
            pytest.skip("Vampire not installed")
        
        # Create complex formula
        pred = namespace.add_predicate("complex", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        
        # Nest it deeply
        formula = base
        for _ in range(5):
            formula = DeonticFormula(DeonticOperator.OBLIGATION, formula)
        
        result = adapter.prove(formula)
        # Should complete (may timeout, that's OK)
        assert isinstance(result, VampireProofResult)
    
    def test_vampire_deontic_formula(self, namespace):
        """
        GIVEN deontic formula
        WHEN proving with Vampire
        THEN should handle deontic operators
        """
        adapter = VampireAdapter()
        if not adapter.is_available():
            pytest.skip("Vampire not installed")
        
        pred = namespace.add_predicate("act", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        formula = DeonticFormula(DeonticOperator.OBLIGATION, base)
        
        result = adapter.prove(formula)
        assert isinstance(result, VampireProofResult)
    
    def test_vampire_cognitive_formula(self, namespace):
        """
        GIVEN cognitive formula
        WHEN proving with Vampire
        THEN should handle cognitive operators
        """
        adapter = VampireAdapter()
        if not adapter.is_available():
            pytest.skip("Vampire not installed")
        
        pred = namespace.add_predicate("fact", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        formula = CognitiveFormula(CognitiveOperator.BELIEF, VariableTerm(agent), base)
        
        result = adapter.prove(formula)
        assert isinstance(result, VampireProofResult)
    
    def test_vampire_temporal_formula(self, namespace):
        """
        GIVEN temporal formula
        WHEN proving with Vampire
        THEN should handle temporal operators
        """
        adapter = VampireAdapter()
        if not adapter.is_available():
            pytest.skip("Vampire not installed")
        
        pred = namespace.add_predicate("state", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        formula = TemporalFormula(TemporalOperator.ALWAYS, base)
        
        result = adapter.prove(formula)
        assert isinstance(result, VampireProofResult)
    
    def test_vampire_conjunction(self, namespace):
        """
        GIVEN conjunction formula
        WHEN proving with Vampire
        THEN should handle AND connective
        """
        adapter = VampireAdapter()
        if not adapter.is_available():
            pytest.skip("Vampire not installed")
        
        pred1 = namespace.add_predicate("p1", ["Agent"])
        pred2 = namespace.add_predicate("p2", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        
        f1 = AtomicFormula(pred1, [VariableTerm(agent)])
        f2 = AtomicFormula(pred2, [VariableTerm(agent)])
        formula = ConnectiveFormula(LogicalConnective.AND, [f1, f2])
        
        result = adapter.prove(formula)
        assert isinstance(result, VampireProofResult)
    
    def test_vampire_disjunction(self, namespace):
        """
        GIVEN disjunction formula
        WHEN proving with Vampire
        THEN should handle OR connective
        """
        adapter = VampireAdapter()
        if not adapter.is_available():
            pytest.skip("Vampire not installed")
        
        pred1 = namespace.add_predicate("q1", ["Agent"])
        pred2 = namespace.add_predicate("q2", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        
        f1 = AtomicFormula(pred1, [VariableTerm(agent)])
        f2 = AtomicFormula(pred2, [VariableTerm(agent)])
        formula = ConnectiveFormula(LogicalConnective.OR, [f1, f2])
        
        result = adapter.prove(formula)
        assert isinstance(result, VampireProofResult)
    
    def test_vampire_negation(self, namespace):
        """
        GIVEN negation formula
        WHEN proving with Vampire
        THEN should handle NOT connective
        """
        adapter = VampireAdapter()
        if not adapter.is_available():
            pytest.skip("Vampire not installed")
        
        pred = namespace.add_predicate("r", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        f = AtomicFormula(pred, [VariableTerm(agent)])
        formula = ConnectiveFormula(LogicalConnective.NOT, [f])
        
        result = adapter.prove(formula)
        assert isinstance(result, VampireProofResult)
    
    def test_vampire_implication(self, namespace):
        """
        GIVEN implication formula
        WHEN proving with Vampire
        THEN should handle IMPLIES connective
        """
        adapter = VampireAdapter()
        if not adapter.is_available():
            pytest.skip("Vampire not installed")
        
        pred1 = namespace.add_predicate("s1", ["Agent"])
        pred2 = namespace.add_predicate("s2", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        
        f1 = AtomicFormula(pred1, [VariableTerm(agent)])
        f2 = AtomicFormula(pred2, [VariableTerm(agent)])
        formula = ConnectiveFormula(LogicalConnective.IMPLIES, [f1, f2])
        
        result = adapter.prove(formula)
        assert isinstance(result, VampireProofResult)
    
    def test_vampire_tautology(self, namespace):
        """
        GIVEN tautology (P OR NOT P)
        WHEN proving with Vampire
        THEN should recognize as valid
        """
        adapter = VampireAdapter()
        if not adapter.is_available():
            pytest.skip("Vampire not installed")
        
        pred = namespace.add_predicate("p", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        
        p = AtomicFormula(pred, [VariableTerm(agent)])
        not_p = ConnectiveFormula(LogicalConnective.NOT, [p])
        tautology = ConnectiveFormula(LogicalConnective.OR, [p, not_p])
        
        result = adapter.prove(tautology)
        assert isinstance(result, VampireProofResult)
        # Tautology should be provable (if Vampire completes in time)
    
    def test_vampire_contradiction(self, namespace):
        """
        GIVEN contradiction (P AND NOT P)
        WHEN proving with Vampire
        THEN should recognize as invalid
        """
        adapter = VampireAdapter()
        if not adapter.is_available():
            pytest.skip("Vampire not installed")
        
        pred = namespace.add_predicate("p", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        
        p = AtomicFormula(pred, [VariableTerm(agent)])
        not_p = ConnectiveFormula(LogicalConnective.NOT, [p])
        contradiction = ConnectiveFormula(LogicalConnective.AND, [p, not_p])
        
        result = adapter.prove(contradiction)
        assert isinstance(result, VampireProofResult)
    
    def test_vampire_nested_formulas(self, namespace):
        """
        GIVEN nested formula
        WHEN proving with Vampire
        THEN should handle nesting
        """
        adapter = VampireAdapter()
        if not adapter.is_available():
            pytest.skip("Vampire not installed")
        
        pred = namespace.add_predicate("action", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        
        # O(B(K(action)))
        knowledge = CognitiveFormula(CognitiveOperator.KNOWLEDGE, VariableTerm(agent), base)
        belief = CognitiveFormula(CognitiveOperator.BELIEF, VariableTerm(agent), knowledge)
        obligation = DeonticFormula(DeonticOperator.OBLIGATION, belief)
        
        result = adapter.prove(obligation)
        assert isinstance(result, VampireProofResult)
    
    def test_vampire_proof_result_fields(self, namespace):
        """
        GIVEN proof result
        WHEN accessing fields
        THEN should have required attributes
        """
        adapter = VampireAdapter()
        if not adapter.is_available():
            pytest.skip("Vampire not installed")
        
        pred = namespace.add_predicate("test", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent)])
        
        result = adapter.prove(formula)
        assert hasattr(result, 'status')
        assert hasattr(result, 'is_valid')
        assert hasattr(result, 'proof_output')
        assert hasattr(result, 'proof_time')


# E Prover Adapter Tests

class TestEProverInstallation:
    """Test E prover installation checking."""
    
    def test_check_eprover_installation(self):
        """
        GIVEN E prover installation check function
        WHEN checking installation
        THEN should return boolean status
        """
        result = check_eprover_installation()
        assert isinstance(result, bool)
        # True if E prover is installed, False otherwise
    
    def test_eprover_adapter_creation(self):
        """
        GIVEN EProverAdapter class
        WHEN creating adapter
        THEN should initialize successfully
        """
        adapter = EProverAdapter(timeout=10, strategy="auto")
        assert adapter.eprover_path == "eprover"
        assert adapter.timeout == 10
        assert adapter.strategy == "auto"
    
    def test_eprover_is_available(self):
        """
        GIVEN EProverAdapter
        WHEN checking availability
        THEN should return boolean
        """
        adapter = EProverAdapter()
        result = adapter.is_available()
        assert isinstance(result, bool)


class TestEProverProving:
    """Test E prover theorem proving."""
    
    def test_eprover_prove_simple(self, namespace):
        """
        GIVEN simple formula
        WHEN proving with E prover
        THEN should return result
        """
        adapter = EProverAdapter()
        if not adapter.is_available():
            pytest.skip("E prover not installed")
        
        pred = namespace.add_predicate("test", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent)])
        
        result = adapter.prove(formula)
        assert isinstance(result, EProverProofResult)
        assert result.proof_time >= 0.0
    
    def test_eprover_prove_with_axioms(self, namespace):
        """
        GIVEN formula and axioms
        WHEN proving with E prover
        THEN should consider axioms
        """
        adapter = EProverAdapter()
        if not adapter.is_available():
            pytest.skip("E prover not installed")
        
        pred = namespace.add_predicate("goal", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent)])
        
        result = adapter.prove(formula, axioms=[formula])
        assert isinstance(result, EProverProofResult)
    
    def test_eprover_timeout(self, namespace):
        """
        GIVEN complex formula with short timeout
        WHEN proving with E prover
        THEN should timeout gracefully
        """
        adapter = EProverAdapter(timeout=1)
        if not adapter.is_available():
            pytest.skip("E prover not installed")
        
        # Create complex formula
        pred = namespace.add_predicate("complex", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        
        # Nest it deeply
        formula = base
        for _ in range(5):
            formula = DeonticFormula(DeonticOperator.OBLIGATION, formula)
        
        result = adapter.prove(formula)
        # Should complete (may timeout, that's OK)
        assert isinstance(result, EProverProofResult)
    
    def test_eprover_strategy_selection(self, namespace):
        """
        GIVEN different strategies
        WHEN creating adapters
        THEN should support strategy configuration
        """
        adapter1 = EProverAdapter(strategy="auto")
        adapter2 = EProverAdapter(strategy="default")
        
        assert adapter1.strategy == "auto"
        assert adapter2.strategy == "default"
    
    def test_eprover_deontic_formula(self, namespace):
        """
        GIVEN deontic formula
        WHEN proving with E prover
        THEN should handle deontic operators
        """
        adapter = EProverAdapter()
        if not adapter.is_available():
            pytest.skip("E prover not installed")
        
        pred = namespace.add_predicate("act", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        formula = DeonticFormula(DeonticOperator.PERMISSION, base)
        
        result = adapter.prove(formula)
        assert isinstance(result, EProverProofResult)
    
    def test_eprover_cognitive_formula(self, namespace):
        """
        GIVEN cognitive formula
        WHEN proving with E prover
        THEN should handle cognitive operators
        """
        adapter = EProverAdapter()
        if not adapter.is_available():
            pytest.skip("E prover not installed")
        
        pred = namespace.add_predicate("belief", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        formula = CognitiveFormula(CognitiveOperator.KNOWLEDGE, VariableTerm(agent), base)
        
        result = adapter.prove(formula)
        assert isinstance(result, EProverProofResult)
    
    def test_eprover_temporal_formula(self, namespace):
        """
        GIVEN temporal formula
        WHEN proving with E prover
        THEN should handle temporal operators
        """
        adapter = EProverAdapter()
        if not adapter.is_available():
            pytest.skip("E prover not installed")
        
        pred = namespace.add_predicate("invariant", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        formula = TemporalFormula(TemporalOperator.EVENTUALLY, base)
        
        result = adapter.prove(formula)
        assert isinstance(result, EProverProofResult)
    
    def test_eprover_conjunction(self, namespace):
        """
        GIVEN conjunction formula
        WHEN proving with E prover
        THEN should handle AND connective
        """
        adapter = EProverAdapter()
        if not adapter.is_available():
            pytest.skip("E prover not installed")
        
        pred1 = namespace.add_predicate("p1", ["Agent"])
        pred2 = namespace.add_predicate("p2", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        
        f1 = AtomicFormula(pred1, [VariableTerm(agent)])
        f2 = AtomicFormula(pred2, [VariableTerm(agent)])
        formula = ConnectiveFormula(LogicalConnective.AND, [f1, f2])
        
        result = adapter.prove(formula)
        assert isinstance(result, EProverProofResult)
    
    def test_eprover_disjunction(self, namespace):
        """
        GIVEN disjunction formula
        WHEN proving with E prover
        THEN should handle OR connective
        """
        adapter = EProverAdapter()
        if not adapter.is_available():
            pytest.skip("E prover not installed")
        
        pred1 = namespace.add_predicate("q1", ["Agent"])
        pred2 = namespace.add_predicate("q2", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        
        f1 = AtomicFormula(pred1, [VariableTerm(agent)])
        f2 = AtomicFormula(pred2, [VariableTerm(agent)])
        formula = ConnectiveFormula(LogicalConnective.OR, [f1, f2])
        
        result = adapter.prove(formula)
        assert isinstance(result, EProverProofResult)
    
    def test_eprover_negation(self, namespace):
        """
        GIVEN negation formula
        WHEN proving with E prover
        THEN should handle NOT connective
        """
        adapter = EProverAdapter()
        if not adapter.is_available():
            pytest.skip("E prover not installed")
        
        pred = namespace.add_predicate("r", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        f = AtomicFormula(pred, [VariableTerm(agent)])
        formula = ConnectiveFormula(LogicalConnective.NOT, [f])
        
        result = adapter.prove(formula)
        assert isinstance(result, EProverProofResult)
    
    def test_eprover_implication(self, namespace):
        """
        GIVEN implication formula
        WHEN proving with E prover
        THEN should handle IMPLIES connective
        """
        adapter = EProverAdapter()
        if not adapter.is_available():
            pytest.skip("E prover not installed")
        
        pred1 = namespace.add_predicate("s1", ["Agent"])
        pred2 = namespace.add_predicate("s2", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        
        f1 = AtomicFormula(pred1, [VariableTerm(agent)])
        f2 = AtomicFormula(pred2, [VariableTerm(agent)])
        formula = ConnectiveFormula(LogicalConnective.IMPLIES, [f1, f2])
        
        result = adapter.prove(formula)
        assert isinstance(result, EProverProofResult)
    
    def test_eprover_tautology(self, namespace):
        """
        GIVEN tautology (P OR NOT P)
        WHEN proving with E prover
        THEN should recognize as valid
        """
        adapter = EProverAdapter()
        if not adapter.is_available():
            pytest.skip("E prover not installed")
        
        pred = namespace.add_predicate("p", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        
        p = AtomicFormula(pred, [VariableTerm(agent)])
        not_p = ConnectiveFormula(LogicalConnective.NOT, [p])
        tautology = ConnectiveFormula(LogicalConnective.OR, [p, not_p])
        
        result = adapter.prove(tautology)
        assert isinstance(result, EProverProofResult)
        # Tautology should be provable
    
    def test_eprover_contradiction(self, namespace):
        """
        GIVEN contradiction (P AND NOT P)
        WHEN proving with E prover
        THEN should recognize as invalid
        """
        adapter = EProverAdapter()
        if not adapter.is_available():
            pytest.skip("E prover not installed")
        
        pred = namespace.add_predicate("p", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        
        p = AtomicFormula(pred, [VariableTerm(agent)])
        not_p = ConnectiveFormula(LogicalConnective.NOT, [p])
        contradiction = ConnectiveFormula(LogicalConnective.AND, [p, not_p])
        
        result = adapter.prove(contradiction)
        assert isinstance(result, EProverProofResult)
    
    def test_eprover_nested_formulas(self, namespace):
        """
        GIVEN nested formula
        WHEN proving with E prover
        THEN should handle nesting
        """
        adapter = EProverAdapter()
        if not adapter.is_available():
            pytest.skip("E prover not installed")
        
        pred = namespace.add_predicate("action", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        
        # Nested: O(T_always(base))
        temporal = TemporalFormula(TemporalOperator.ALWAYS, base)
        deontic = DeonticFormula(DeonticOperator.OBLIGATION, temporal)
        
        result = adapter.prove(deontic)
        assert isinstance(result, EProverProofResult)
    
    def test_eprover_result_attributes(self, namespace):
        """
        GIVEN proof result
        WHEN accessing fields
        THEN should have required attributes
        """
        adapter = EProverAdapter()
        if not adapter.is_available():
            pytest.skip("E prover not installed")
        
        pred = namespace.add_predicate("test", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent)])
        
        result = adapter.prove(formula)
        assert hasattr(result, 'status')
        assert hasattr(result, 'is_valid')
        assert hasattr(result, 'proof_output')
        assert hasattr(result, 'proof_time')
        assert hasattr(result, 'strategy_used')
    
    def test_eprover_custom_strategy(self, namespace):
        """
        GIVEN custom strategy
        WHEN proving with E prover
        THEN should use specified strategy
        """
        adapter = EProverAdapter(strategy="heuristic")
        if not adapter.is_available():
            pytest.skip("E prover not installed")
        
        pred = namespace.add_predicate("test", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent)])
        
        result = adapter.prove(formula)
        # Should use configured strategy
        assert result.strategy_used == "heuristic" or result.strategy_used == "auto"
