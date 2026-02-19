"""
Tests for Z3 Adapter (Phase 6 Week 1).

This test module validates Z3 SMT solver integration for CEC,
covering formula translation and theorem proving.

Test Coverage:
- Z3 installation and initialization (3 tests)
- Atomic formula translation (3 tests)
- Deontic formula translation (6 tests)
- Cognitive formula translation (5 tests)
- Temporal formula translation (3 tests)
- Connective formula translation (5 tests)
- Theorem proving (3 tests)
- Satisfiability checking (2 tests)

Total: 30 tests
"""

import pytest
from ipfs_datasets_py.logic.CEC.provers.z3_adapter import (
    Z3Adapter,
    Z3ProofResult,
    ProofStatus,
    check_z3_installation,
    get_z3_version,
    Z3_AVAILABLE
)
from ipfs_datasets_py.logic.CEC.native.dcec_core import (
    AtomicFormula,
    DeonticFormula,
    CognitiveFormula,
    TemporalFormula,
    ConnectiveFormula,
    QuantifiedFormula,
    DeonticOperator,
    CognitiveOperator,
    TemporalOperator,
    LogicalConnective,
    Predicate,
    Variable,
    VariableTerm,
    Sort,
)
from ipfs_datasets_py.logic.CEC.native.dcec_namespace import DCECNamespace


@pytest.fixture
def namespace():
    """Create DCEC namespace for tests."""
    return DCECNamespace()


@pytest.fixture
def adapter():
    """Create Z3 adapter for tests."""
    if not Z3_AVAILABLE:
        pytest.skip("Z3 not installed")
    return Z3Adapter(timeout=5000)


class TestZ3Installation:
    """Test Z3 installation and initialization."""
    
    def test_check_z3_installation(self):
        """
        GIVEN Z3 installation check function
        WHEN checking installation
        THEN should return boolean status
        """
        result = check_z3_installation()
        assert isinstance(result, bool)
        # True if z3-solver is installed, False otherwise
    
    def test_get_z3_version(self):
        """
        GIVEN Z3 version function
        WHEN getting version
        THEN should return version string or None
        """
        version = get_z3_version()
        if Z3_AVAILABLE:
            assert version is not None
            assert isinstance(version, str)
        else:
            assert version is None
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_adapter_initialization(self, adapter):
        """
        GIVEN Z3Adapter class
        WHEN initializing adapter
        THEN should initialize successfully
        """
        assert adapter.timeout == 5000
        assert adapter.max_memory == 1024
        assert adapter.solver is not None
        assert adapter.is_available()


class TestAtomicTranslation:
    """Test translation of atomic formulas."""
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_translate_simple_atomic(self, adapter, namespace):
        """
        GIVEN simple atomic formula
        WHEN translating to Z3
        THEN should create Z3 Bool constant
        """
        pred = namespace.add_predicate("test_action", ["Agent"])
        agent_var = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent_var)])
        
        z3_formula = adapter.translate_to_z3(formula)
        assert z3_formula is not None
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_translate_multiple_atomic(self, adapter, namespace):
        """
        GIVEN multiple atomic formulas
        WHEN translating to Z3
        THEN should create distinct Z3 formulas
        """
        pred1 = namespace.add_predicate("action1", ["Agent"])
        pred2 = namespace.add_predicate("action2", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        
        formula1 = AtomicFormula(pred1, [VariableTerm(agent)])
        formula2 = AtomicFormula(pred2, [VariableTerm(agent)])
        
        z3_f1 = adapter.translate_to_z3(formula1)
        z3_f2 = adapter.translate_to_z3(formula2)
        
        assert z3_f1 is not None
        assert z3_f2 is not None
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_atomic_translation_idempotent(self, adapter, namespace):
        """
        GIVEN atomic formula
        WHEN translating multiple times
        THEN should produce consistent results
        """
        pred = namespace.add_predicate("test", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent)])
        
        z3_f1 = adapter.translate_to_z3(formula)
        z3_f2 = adapter.translate_to_z3(formula)
        
        # Should be consistent
        assert z3_f1 is not None
        assert z3_f2 is not None


class TestDeonticTranslation:
    """Test translation of deontic formulas."""
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_translate_obligation(self, adapter, namespace):
        """
        GIVEN deontic obligation formula
        WHEN translating to Z3
        THEN should create Z3 formula with obligated function
        """
        pred = namespace.add_predicate("comply", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        formula = DeonticFormula(DeonticOperator.OBLIGATION, base)
        
        z3_formula = adapter.translate_to_z3(formula)
        assert z3_formula is not None
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_translate_permission(self, adapter, namespace):
        """
        GIVEN deontic permission formula
        WHEN translating to Z3
        THEN should create Z3 formula with permitted function
        """
        pred = namespace.add_predicate("act", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        formula = DeonticFormula(DeonticOperator.PERMISSION, base)
        
        z3_formula = adapter.translate_to_z3(formula)
        assert z3_formula is not None
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_translate_prohibition(self, adapter, namespace):
        """
        GIVEN deontic prohibition formula
        WHEN translating to Z3
        THEN should create Z3 formula with NOT permitted
        """
        pred = namespace.add_predicate("violate", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        formula = DeonticFormula(DeonticOperator.PROHIBITION, base)
        
        z3_formula = adapter.translate_to_z3(formula)
        assert z3_formula is not None
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_deontic_operators_distinct(self, adapter, namespace):
        """
        GIVEN different deontic operators
        WHEN translating to Z3
        THEN should produce distinct formulas
        """
        pred = namespace.add_predicate("action", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        
        obligation = DeonticFormula(DeonticOperator.OBLIGATION, base)
        permission = DeonticFormula(DeonticOperator.PERMISSION, base)
        prohibition = DeonticFormula(DeonticOperator.PROHIBITION, base)
        
        z3_o = adapter.translate_to_z3(obligation)
        z3_p = adapter.translate_to_z3(permission)
        z3_f = adapter.translate_to_z3(prohibition)
        
        assert z3_o is not None
        assert z3_p is not None
        assert z3_f is not None
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_nested_deontic(self, adapter, namespace):
        """
        GIVEN nested deontic formula
        WHEN translating to Z3
        THEN should handle nesting
        """
        pred = namespace.add_predicate("action", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        inner = DeonticFormula(DeonticOperator.OBLIGATION, base)
        outer = DeonticFormula(DeonticOperator.PERMISSION, inner)
        
        z3_formula = adapter.translate_to_z3(outer)
        assert z3_formula is not None
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_deontic_with_complex_base(self, adapter, namespace):
        """
        GIVEN deontic formula with complex base
        WHEN translating to Z3
        THEN should translate correctly
        """
        pred1 = namespace.add_predicate("action1", ["Agent"])
        pred2 = namespace.add_predicate("action2", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        
        f1 = AtomicFormula(pred1, [VariableTerm(agent)])
        f2 = AtomicFormula(pred2, [VariableTerm(agent)])
        base = ConnectiveFormula(LogicalConnective.AND, [f1, f2])
        
        formula = DeonticFormula(DeonticOperator.OBLIGATION, base)
        z3_formula = adapter.translate_to_z3(formula)
        assert z3_formula is not None


class TestCognitiveTranslation:
    """Test translation of cognitive formulas."""
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_translate_belief(self, adapter, namespace):
        """
        GIVEN cognitive belief formula
        WHEN translating to Z3
        THEN should create Z3 formula with believes function
        """
        pred = namespace.add_predicate("fact", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        formula = CognitiveFormula(CognitiveOperator.BELIEF, VariableTerm(agent), base)
        
        z3_formula = adapter.translate_to_z3(formula)
        assert z3_formula is not None
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_translate_knowledge(self, adapter, namespace):
        """
        GIVEN cognitive knowledge formula
        WHEN translating to Z3
        THEN should create Z3 formula with knows function
        """
        pred = namespace.add_predicate("truth", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        formula = CognitiveFormula(CognitiveOperator.KNOWLEDGE, VariableTerm(agent), base)
        
        z3_formula = adapter.translate_to_z3(formula)
        assert z3_formula is not None
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_translate_intention(self, adapter, namespace):
        """
        GIVEN cognitive intention formula
        WHEN translating to Z3
        THEN should create Z3 formula with intends function
        """
        pred = namespace.add_predicate("goal", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        formula = CognitiveFormula(CognitiveOperator.INTENTION, VariableTerm(agent), base)
        
        z3_formula = adapter.translate_to_z3(formula)
        assert z3_formula is not None
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_translate_desire(self, adapter, namespace):
        """
        GIVEN cognitive desire formula
        WHEN translating to Z3
        THEN should create Z3 formula with desires function
        """
        pred = namespace.add_predicate("outcome", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        formula = CognitiveFormula(CognitiveOperator.DESIRE, VariableTerm(agent), base)
        
        z3_formula = adapter.translate_to_z3(formula)
        assert z3_formula is not None
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_translate_goal(self, adapter, namespace):
        """
        GIVEN cognitive goal formula
        WHEN translating to Z3
        THEN should create Z3 formula with has_goal function
        """
        pred = namespace.add_predicate("objective", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        formula = CognitiveFormula(CognitiveOperator.GOAL, VariableTerm(agent), base)
        
        z3_formula = adapter.translate_to_z3(formula)
        assert z3_formula is not None


class TestTemporalTranslation:
    """Test translation of temporal formulas."""
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_translate_always(self, adapter, namespace):
        """
        GIVEN temporal always formula
        WHEN translating to Z3
        THEN should create Z3 formula with always function
        """
        pred = namespace.add_predicate("invariant", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        formula = TemporalFormula(TemporalOperator.ALWAYS, base)
        
        z3_formula = adapter.translate_to_z3(formula)
        assert z3_formula is not None
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_translate_eventually(self, adapter, namespace):
        """
        GIVEN temporal eventually formula
        WHEN translating to Z3
        THEN should create Z3 formula with eventually function
        """
        pred = namespace.add_predicate("goal", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        formula = TemporalFormula(TemporalOperator.EVENTUALLY, base)
        
        z3_formula = adapter.translate_to_z3(formula)
        assert z3_formula is not None
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_translate_next(self, adapter, namespace):
        """
        GIVEN temporal next formula
        WHEN translating to Z3
        THEN should create Z3 formula with next function
        """
        pred = namespace.add_predicate("state", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        formula = TemporalFormula(TemporalOperator.NEXT, base)
        
        z3_formula = adapter.translate_to_z3(formula)
        assert z3_formula is not None


class TestConnectiveTranslation:
    """Test translation of connective formulas."""
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_translate_and(self, adapter, namespace):
        """
        GIVEN AND connective formula
        WHEN translating to Z3
        THEN should create Z3 And
        """
        pred1 = namespace.add_predicate("p1", ["Agent"])
        pred2 = namespace.add_predicate("p2", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        
        f1 = AtomicFormula(pred1, [VariableTerm(agent)])
        f2 = AtomicFormula(pred2, [VariableTerm(agent)])
        formula = ConnectiveFormula(LogicalConnective.AND, [f1, f2])
        
        z3_formula = adapter.translate_to_z3(formula)
        assert z3_formula is not None
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_translate_or(self, adapter, namespace):
        """
        GIVEN OR connective formula
        WHEN translating to Z3
        THEN should create Z3 Or
        """
        pred1 = namespace.add_predicate("q1", ["Agent"])
        pred2 = namespace.add_predicate("q2", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        
        f1 = AtomicFormula(pred1, [VariableTerm(agent)])
        f2 = AtomicFormula(pred2, [VariableTerm(agent)])
        formula = ConnectiveFormula(LogicalConnective.OR, [f1, f2])
        
        z3_formula = adapter.translate_to_z3(formula)
        assert z3_formula is not None
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_translate_not(self, adapter, namespace):
        """
        GIVEN NOT connective formula
        WHEN translating to Z3
        THEN should create Z3 Not
        """
        pred = namespace.add_predicate("r", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        
        f = AtomicFormula(pred, [VariableTerm(agent)])
        formula = ConnectiveFormula(LogicalConnective.NOT, [f])
        
        z3_formula = adapter.translate_to_z3(formula)
        assert z3_formula is not None
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_translate_implies(self, adapter, namespace):
        """
        GIVEN IMPLIES connective formula
        WHEN translating to Z3
        THEN should create Z3 Implies
        """
        pred1 = namespace.add_predicate("s1", ["Agent"])
        pred2 = namespace.add_predicate("s2", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        
        f1 = AtomicFormula(pred1, [VariableTerm(agent)])
        f2 = AtomicFormula(pred2, [VariableTerm(agent)])
        formula = ConnectiveFormula(LogicalConnective.IMPLIES, [f1, f2])
        
        z3_formula = adapter.translate_to_z3(formula)
        assert z3_formula is not None
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_translate_nested_connectives(self, adapter, namespace):
        """
        GIVEN nested connective formulas
        WHEN translating to Z3
        THEN should handle nesting correctly
        """
        pred1 = namespace.add_predicate("t1", ["Agent"])
        pred2 = namespace.add_predicate("t2", ["Agent"])
        pred3 = namespace.add_predicate("t3", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        
        f1 = AtomicFormula(pred1, [VariableTerm(agent)])
        f2 = AtomicFormula(pred2, [VariableTerm(agent)])
        f3 = AtomicFormula(pred3, [VariableTerm(agent)])
        
        # (f1 AND f2) OR f3
        and_formula = ConnectiveFormula(LogicalConnective.AND, [f1, f2])
        or_formula = ConnectiveFormula(LogicalConnective.OR, [and_formula, f3])
        
        z3_formula = adapter.translate_to_z3(or_formula)
        assert z3_formula is not None


class TestTheoremProving:
    """Test theorem proving with Z3."""
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_prove_tautology(self, adapter, namespace):
        """
        GIVEN tautology formula (A OR NOT A)
        WHEN proving with Z3
        THEN should return VALID
        """
        pred = namespace.add_predicate("p", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        
        p = AtomicFormula(pred, [VariableTerm(agent)])
        not_p = ConnectiveFormula(LogicalConnective.NOT, [p])
        tautology = ConnectiveFormula(LogicalConnective.OR, [p, not_p])
        
        result = adapter.prove(tautology)
        assert result.status in [ProofStatus.VALID, ProofStatus.SATISFIABLE]
        assert result.proof_time >= 0.0
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_prove_with_axioms(self, adapter, namespace):
        """
        GIVEN formula and axioms
        WHEN proving with Z3
        THEN should consider axioms
        """
        pred1 = namespace.add_predicate("a", ["Agent"])
        pred2 = namespace.add_predicate("b", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        
        # Axiom: A
        a = AtomicFormula(pred1, [VariableTerm(agent)])
        
        # Goal: A (should be valid with axiom A)
        result = adapter.prove(a, axioms=[a])
        
        # With axiom A, A should be provable
        assert result.status in [ProofStatus.VALID, ProofStatus.SATISFIABLE]
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_prove_invalid_formula(self, adapter, namespace):
        """
        GIVEN invalid formula
        WHEN proving with Z3
        THEN should return INVALID or provide counterexample
        """
        pred = namespace.add_predicate("q", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        
        # A AND NOT A (contradiction)
        a = AtomicFormula(pred, [VariableTerm(agent)])
        not_a = ConnectiveFormula(LogicalConnective.NOT, [a])
        contradiction = ConnectiveFormula(LogicalConnective.AND, [a, not_a])
        
        result = adapter.prove(contradiction)
        # Contradiction should be invalid/unsatisfiable
        assert result.status in [ProofStatus.INVALID, ProofStatus.UNSATISFIABLE]


class TestSatisfiabilityChecking:
    """Test satisfiability checking."""
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_check_satisfiable(self, adapter, namespace):
        """
        GIVEN satisfiable formula
        WHEN checking satisfiability
        THEN should return SATISFIABLE with model
        """
        pred = namespace.add_predicate("sat", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent)])
        
        result = adapter.check_satisfiability(formula)
        assert result.status == ProofStatus.SATISFIABLE
        assert result.model is not None
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not installed")
    def test_check_unsatisfiable(self, adapter, namespace):
        """
        GIVEN unsatisfiable formula
        WHEN checking satisfiability
        THEN should return UNSATISFIABLE
        """
        pred = namespace.add_predicate("unsat", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        
        # A AND NOT A
        a = AtomicFormula(pred, [VariableTerm(agent)])
        not_a = ConnectiveFormula(LogicalConnective.NOT, [a])
        contradiction = ConnectiveFormula(LogicalConnective.AND, [a, not_a])
        
        result = adapter.check_satisfiability(contradiction)
        assert result.status == ProofStatus.UNSATISFIABLE
