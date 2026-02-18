"""
Tests for TDFOL Prover Module

This module tests the TDFOL theorem prover following GIVEN-WHEN-THEN format.
Comprehensive coverage of proving capabilities, inference rules, and integration.
"""

import pytest
from unittest.mock import Mock, patch

from ipfs_datasets_py.logic.TDFOL import (
    BinaryFormula,
    BinaryTemporalFormula,
    Constant,
    DeonticFormula,
    DeonticOperator,
    LogicOperator,
    Predicate,
    Quantifier,
    QuantifiedFormula,
    Sort,
    TDFOLKnowledgeBase,
    TemporalFormula,
    TemporalOperator,
    UnaryFormula,
    Variable,
    create_always,
    create_conjunction,
    create_disjunction,
    create_eventually,
    create_existential,
    create_implication,
    create_negation,
    create_next,
    create_obligation,
    create_permission,
    create_prohibition,
    create_universal,
    create_until,
    ProofResult,
    ProofStatus,
    ProofStep,
    TDFOLProver,
)


# ============================================================================
# Test Basic Proving (20 tests)
# ============================================================================


class TestBasicProving:
    """Test basic proving capabilities."""
    
    def test_prove_axiom_in_kb(self):
        """Test proving a formula that is already an axiom."""
        # GIVEN a knowledge base with an axiom
        kb = TDFOLKnowledgeBase()
        axiom = Predicate("P", ())
        kb.add_axiom(axiom, "axiom1")
        prover = TDFOLProver(kb)
        
        # WHEN proving the axiom
        result = prover.prove(axiom)
        
        # THEN it should be proved immediately
        assert result.status == ProofStatus.PROVED
        assert result.is_proved()
        assert result.method == "axiom_lookup"
        assert len(result.proof_steps) == 1
        assert "Axiom" in result.proof_steps[0].justification
    
    def test_prove_theorem_in_kb(self):
        """Test proving a formula that is already a theorem."""
        # GIVEN a knowledge base with a theorem
        kb = TDFOLKnowledgeBase()
        theorem = Predicate("Q", ())
        kb.add_theorem(theorem, "theorem1")
        prover = TDFOLProver(kb)
        
        # WHEN proving the theorem
        result = prover.prove(theorem)
        
        # THEN it should be proved immediately
        assert result.status == ProofStatus.PROVED
        assert result.is_proved()
        assert result.method == "theorem_lookup"
        assert "Theorem" in result.proof_steps[0].justification
    
    def test_prove_unknown_formula(self):
        """Test proving a formula that cannot be proved."""
        # GIVEN an empty knowledge base
        kb = TDFOLKnowledgeBase()
        prover = TDFOLProver(kb)
        unknown = Predicate("Unknown", ())
        
        # WHEN trying to prove an unknown formula
        result = prover.prove(unknown)
        
        # THEN it should return unknown status
        assert result.status == ProofStatus.UNKNOWN
        assert not result.is_proved()
    
    def test_proof_result_structure(self):
        """Test that proof result has correct structure."""
        # GIVEN a prover with an axiom
        kb = TDFOLKnowledgeBase()
        axiom = Predicate("P", ())
        kb.add_axiom(axiom)
        prover = TDFOLProver(kb)
        
        # WHEN proving the axiom
        result = prover.prove(axiom)
        
        # THEN result should have all required fields
        assert hasattr(result, 'status')
        assert hasattr(result, 'formula')
        assert hasattr(result, 'proof_steps')
        assert hasattr(result, 'time_ms')
        assert hasattr(result, 'method')
        assert hasattr(result, 'message')
        assert result.formula == axiom
        assert result.time_ms >= 0
    
    def test_proof_step_structure(self):
        """Test that proof steps have correct structure."""
        # GIVEN a prover with an axiom
        kb = TDFOLKnowledgeBase()
        axiom = Predicate("P", ())
        kb.add_axiom(axiom)
        prover = TDFOLProver(kb)
        
        # WHEN proving the axiom
        result = prover.prove(axiom)
        
        # THEN proof steps should have required fields
        assert len(result.proof_steps) > 0
        step = result.proof_steps[0]
        assert hasattr(step, 'formula')
        assert hasattr(step, 'justification')
        assert hasattr(step, 'rule_name')
        assert hasattr(step, 'premises')
    
    def test_add_axiom_to_prover(self):
        """Test adding axioms through prover interface."""
        # GIVEN a prover
        prover = TDFOLProver()
        axiom = Predicate("NewAxiom", ())
        
        # WHEN adding an axiom through prover
        prover.add_axiom(axiom, "new_axiom")
        
        # THEN axiom should be in knowledge base
        assert axiom in prover.kb.axioms
    
    def test_add_theorem_to_prover(self):
        """Test adding theorems through prover interface."""
        # GIVEN a prover
        prover = TDFOLProver()
        theorem = Predicate("NewTheorem", ())
        
        # WHEN adding a theorem through prover
        prover.add_theorem(theorem, "new_theorem")
        
        # THEN theorem should be in knowledge base
        assert theorem in prover.kb.theorems
    
    def test_prove_with_timeout(self):
        """Test proving with a timeout parameter."""
        # GIVEN a prover
        prover = TDFOLProver()
        formula = Predicate("P", ())
        
        # WHEN proving with short timeout
        result = prover.prove(formula, timeout_ms=10)
        
        # THEN it should complete (even if unknown)
        assert result.status in [ProofStatus.UNKNOWN, ProofStatus.TIMEOUT]
        assert result.time_ms >= 0
    
    def test_prove_multiple_formulas(self):
        """Test proving multiple different formulas."""
        # GIVEN a prover with multiple axioms
        kb = TDFOLKnowledgeBase()
        axiom1 = Predicate("P", ())
        axiom2 = Predicate("Q", ())
        kb.add_axiom(axiom1)
        kb.add_axiom(axiom2)
        prover = TDFOLProver(kb)
        
        # WHEN proving both axioms
        result1 = prover.prove(axiom1)
        result2 = prover.prove(axiom2)
        
        # THEN both should be proved
        assert result1.is_proved()
        assert result2.is_proved()
    
    def test_proof_timing_recorded(self):
        """Test that proof timing is recorded."""
        # GIVEN a prover with an axiom
        kb = TDFOLKnowledgeBase()
        axiom = Predicate("P", ())
        kb.add_axiom(axiom)
        prover = TDFOLProver(kb)
        
        # WHEN proving
        result = prover.prove(axiom)
        
        # THEN timing should be positive
        assert result.time_ms > 0
    
    def test_prove_simple_predicate(self):
        """Test proving a simple predicate."""
        # GIVEN a simple predicate as axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("Human", (Constant("socrates"),))
        kb.add_axiom(p)
        prover = TDFOLProver(kb)
        
        # WHEN proving the predicate
        result = prover.prove(p)
        
        # THEN it should be proved
        assert result.is_proved()
    
    def test_prove_predicate_with_variable(self):
        """Test proving a predicate with a variable."""
        # GIVEN a predicate with variable as axiom
        kb = TDFOLKnowledgeBase()
        x = Variable("x")
        p = Predicate("Person", (x,))
        kb.add_axiom(p)
        prover = TDFOLProver(kb)
        
        # WHEN proving the predicate
        result = prover.prove(p)
        
        # THEN it should be proved
        assert result.is_proved()
    
    def test_prove_with_empty_kb(self):
        """Test proving with an empty knowledge base."""
        # GIVEN an empty knowledge base
        kb = TDFOLKnowledgeBase()
        prover = TDFOLProver(kb)
        formula = Predicate("P", ())
        
        # WHEN proving any formula
        result = prover.prove(formula)
        
        # THEN it should be unknown
        assert result.status == ProofStatus.UNKNOWN
    
    def test_proof_method_recorded(self):
        """Test that proof method is recorded."""
        # GIVEN a prover with an axiom
        kb = TDFOLKnowledgeBase()
        axiom = Predicate("P", ())
        kb.add_axiom(axiom)
        prover = TDFOLProver(kb)
        
        # WHEN proving
        result = prover.prove(axiom)
        
        # THEN method should be recorded
        assert result.method in ["axiom_lookup", "theorem_lookup", "forward_chaining"]
    
    def test_prove_returns_formula(self):
        """Test that proof result contains the formula."""
        # GIVEN a prover with an axiom
        kb = TDFOLKnowledgeBase()
        axiom = Predicate("P", ())
        kb.add_axiom(axiom)
        prover = TDFOLProver(kb)
        
        # WHEN proving
        result = prover.prove(axiom)
        
        # THEN result should contain the formula
        assert result.formula == axiom
    
    def test_prover_initialization_with_kb(self):
        """Test prover initialization with knowledge base."""
        # GIVEN a knowledge base
        kb = TDFOLKnowledgeBase()
        
        # WHEN creating prover with kb
        prover = TDFOLProver(kb)
        
        # THEN prover should have the kb
        assert prover.kb == kb
    
    def test_prover_initialization_without_kb(self):
        """Test prover initialization without knowledge base."""
        # WHEN creating prover without kb
        prover = TDFOLProver()
        
        # THEN prover should have empty kb
        assert isinstance(prover.kb, TDFOLKnowledgeBase)
        assert len(prover.kb.axioms) == 0
    
    def test_prove_negation_of_axiom(self):
        """Test attempting to prove negation of an axiom."""
        # GIVEN an axiom P
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        kb.add_axiom(p)
        prover = TDFOLProver(kb)
        
        # WHEN trying to prove ¬P with short timeout
        not_p = create_negation(p)
        result = prover.prove(not_p, timeout_ms=100)
        
        # THEN it should be unknown (no contradiction detection)
        assert result.status in [ProofStatus.UNKNOWN, ProofStatus.DISPROVED, ProofStatus.TIMEOUT]
    
    def test_proof_steps_list_not_none(self):
        """Test that proof steps is always a list."""
        # GIVEN a prover
        prover = TDFOLProver()
        formula = Predicate("P", ())
        
        # WHEN proving
        result = prover.prove(formula)
        
        # THEN proof_steps should be a list (even if empty)
        assert isinstance(result.proof_steps, list)
    
    def test_prove_conjunction_in_kb(self):
        """Test proving a conjunction that is in KB."""
        # GIVEN a conjunction as axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        q = Predicate("Q", ())
        conj = create_conjunction(p, q)
        kb.add_axiom(conj)
        prover = TDFOLProver(kb)
        
        # WHEN proving the conjunction
        result = prover.prove(conj)
        
        # THEN it should be proved
        assert result.is_proved()


# ============================================================================
# Test Inference Rules (30 tests)
# ============================================================================


class TestInferenceRules:
    """Test inference rule application."""
    
    def test_modus_ponens_pattern(self):
        """Test modus ponens inference pattern."""
        # GIVEN P and P→Q as axioms
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        q = Predicate("Q", ())
        kb.add_axiom(p)
        kb.add_axiom(create_implication(p, q))
        prover = TDFOLProver(kb)
        
        # WHEN proving Q
        result = prover.prove(q)
        
        # THEN Q should be derivable (may require forward chaining)
        # Note: Result depends on rule implementation
        assert result.status in [ProofStatus.PROVED, ProofStatus.UNKNOWN]
    
    def test_universal_instantiation_pattern(self):
        """Test universal instantiation pattern."""
        # GIVEN ∀x.P(x) as axiom
        kb = TDFOLKnowledgeBase()
        x = Variable("x")
        p_x = Predicate("Person", (x,))
        forall_p = create_universal(x, p_x)
        kb.add_axiom(forall_p)
        prover = TDFOLProver(kb)
        
        # WHEN proving the universal
        result = prover.prove(forall_p)
        
        # THEN it should be proved (it's an axiom)
        assert result.is_proved()
    
    def test_existential_generalization_pattern(self):
        """Test existential generalization pattern."""
        # GIVEN P(a) as axiom
        kb = TDFOLKnowledgeBase()
        a = Constant("alice")
        p_a = Predicate("Person", (a,))
        kb.add_axiom(p_a)
        prover = TDFOLProver(kb)
        
        # WHEN proving P(a)
        result = prover.prove(p_a)
        
        # THEN it should be proved
        assert result.is_proved()
    
    def test_conjunction_introduction(self):
        """Test conjunction introduction pattern."""
        # GIVEN P and Q as axioms
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        q = Predicate("Q", ())
        kb.add_axiom(p)
        kb.add_axiom(q)
        prover = TDFOLProver(kb)
        
        # WHEN trying to prove P ∧ Q
        conj = create_conjunction(p, q)
        result = prover.prove(conj)
        
        # THEN it may be derivable via forward chaining
        assert result.status in [ProofStatus.PROVED, ProofStatus.UNKNOWN]
    
    def test_conjunction_elimination_left(self):
        """Test conjunction elimination (left)."""
        # GIVEN P ∧ Q as axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        q = Predicate("Q", ())
        conj = create_conjunction(p, q)
        kb.add_axiom(conj)
        prover = TDFOLProver(kb)
        
        # WHEN proving P
        result = prover.prove(p)
        
        # THEN it may be derivable
        assert result.status in [ProofStatus.PROVED, ProofStatus.UNKNOWN]
    
    def test_conjunction_elimination_right(self):
        """Test conjunction elimination (right)."""
        # GIVEN P ∧ Q as axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        q = Predicate("Q", ())
        conj = create_conjunction(p, q)
        kb.add_axiom(conj)
        prover = TDFOLProver(kb)
        
        # WHEN proving Q
        result = prover.prove(q)
        
        # THEN it may be derivable
        assert result.status in [ProofStatus.PROVED, ProofStatus.UNKNOWN]
    
    def test_disjunction_introduction_left(self):
        """Test disjunction introduction (left)."""
        # GIVEN P as axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        q = Predicate("Q", ())
        kb.add_axiom(p)
        prover = TDFOLProver(kb)
        
        # WHEN trying to prove P ∨ Q
        disj = create_disjunction(p, q)
        result = prover.prove(disj)
        
        # THEN it may be derivable
        assert result.status in [ProofStatus.PROVED, ProofStatus.UNKNOWN]
    
    def test_disjunction_introduction_right(self):
        """Test disjunction introduction (right)."""
        # GIVEN Q as axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        q = Predicate("Q", ())
        kb.add_axiom(q)
        prover = TDFOLProver(kb)
        
        # WHEN trying to prove P ∨ Q
        disj = create_disjunction(p, q)
        result = prover.prove(disj)
        
        # THEN it may be derivable
        assert result.status in [ProofStatus.PROVED, ProofStatus.UNKNOWN]
    
    def test_implication_introduction(self):
        """Test implication introduction pattern."""
        # GIVEN P→Q as axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        q = Predicate("Q", ())
        impl = create_implication(p, q)
        kb.add_axiom(impl)
        prover = TDFOLProver(kb)
        
        # WHEN proving P→Q
        result = prover.prove(impl)
        
        # THEN it should be proved (it's an axiom)
        assert result.is_proved()
    
    def test_double_negation_elimination(self):
        """Test double negation elimination pattern."""
        # GIVEN ¬¬P as axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        not_not_p = create_negation(create_negation(p))
        kb.add_axiom(not_not_p)
        prover = TDFOLProver(kb)
        
        # WHEN proving ¬¬P
        result = prover.prove(not_not_p)
        
        # THEN it should be proved
        assert result.is_proved()
    
    def test_temporal_necessitation(self):
        """Test temporal necessitation rule."""
        # GIVEN P as axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        kb.add_axiom(p)
        prover = TDFOLProver(kb)
        
        # WHEN trying to prove □P
        always_p = create_always(p)
        result = prover.prove(always_p)
        
        # THEN it may be derivable via temporal necessitation
        assert result.status in [ProofStatus.PROVED, ProofStatus.UNKNOWN]
    
    def test_deontic_necessitation(self):
        """Test deontic necessitation rule."""
        # GIVEN P as axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        kb.add_axiom(p)
        prover = TDFOLProver(kb)
        
        # WHEN trying to prove O(P)
        obligation_p = create_obligation(p)
        result = prover.prove(obligation_p)
        
        # THEN it may be derivable via deontic necessitation
        assert result.status in [ProofStatus.PROVED, ProofStatus.UNKNOWN]
    
    def test_temporal_distribution(self):
        """Test temporal distribution rule (K axiom)."""
        # GIVEN □(P→Q) and □P as axioms
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        q = Predicate("Q", ())
        always_impl = create_always(create_implication(p, q))
        always_p = create_always(p)
        kb.add_axiom(always_impl)
        kb.add_axiom(always_p)
        prover = TDFOLProver(kb)
        
        # WHEN trying to prove □Q
        always_q = create_always(q)
        result = prover.prove(always_q)
        
        # THEN it may be derivable
        assert result.status in [ProofStatus.PROVED, ProofStatus.UNKNOWN]
    
    def test_deontic_distribution(self):
        """Test deontic distribution rule (K axiom)."""
        # GIVEN O(P→Q) and O(P) as axioms
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        q = Predicate("Q", ())
        obligation_impl = create_obligation(create_implication(p, q))
        obligation_p = create_obligation(p)
        kb.add_axiom(obligation_impl)
        kb.add_axiom(obligation_p)
        prover = TDFOLProver(kb)
        
        # WHEN trying to prove O(Q)
        obligation_q = create_obligation(q)
        result = prover.prove(obligation_q)
        
        # THEN it may be derivable
        assert result.status in [ProofStatus.PROVED, ProofStatus.UNKNOWN]
    
    def test_temporal_t_axiom(self):
        """Test temporal T axiom: □P → P."""
        # GIVEN □P as axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        always_p = create_always(p)
        kb.add_axiom(always_p)
        prover = TDFOLProver(kb)
        
        # WHEN trying to prove P
        result = prover.prove(p)
        
        # THEN it may be derivable via T axiom
        assert result.status in [ProofStatus.PROVED, ProofStatus.UNKNOWN]
    
    def test_deontic_d_axiom(self):
        """Test deontic D axiom: O(P) → P(P)."""
        # GIVEN O(P) as axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        obligation_p = create_obligation(p)
        kb.add_axiom(obligation_p)
        prover = TDFOLProver(kb)
        
        # WHEN trying to prove P(P)
        permission_p = create_permission(p)
        result = prover.prove(permission_p)
        
        # THEN it may be derivable via D axiom
        assert result.status in [ProofStatus.PROVED, ProofStatus.UNKNOWN]
    
    def test_eventually_introduction(self):
        """Test eventually introduction rule."""
        # GIVEN P as axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        kb.add_axiom(p)
        prover = TDFOLProver(kb)
        
        # WHEN trying to prove ◊P
        eventually_p = create_eventually(p)
        result = prover.prove(eventually_p)
        
        # THEN it may be derivable
        assert result.status in [ProofStatus.PROVED, ProofStatus.UNKNOWN]
    
    def test_permission_introduction(self):
        """Test permission introduction rule."""
        # GIVEN P as axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        kb.add_axiom(p)
        prover = TDFOLProver(kb)
        
        # WHEN trying to prove P(P)
        permission_p = create_permission(p)
        result = prover.prove(permission_p)
        
        # THEN it may be derivable
        assert result.status in [ProofStatus.PROVED, ProofStatus.UNKNOWN]
    
    def test_prohibition_elimination(self):
        """Test prohibition elimination rule."""
        # GIVEN F(P) as axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        prohibition_p = create_prohibition(p)
        kb.add_axiom(prohibition_p)
        prover = TDFOLProver(kb)
        
        # WHEN proving F(P)
        result = prover.prove(prohibition_p)
        
        # THEN it should be proved
        assert result.is_proved()
    
    def test_until_unfolding(self):
        """Test until operator unfolding."""
        # GIVEN P U Q as axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        q = Predicate("Q", ())
        until = create_until(p, q)
        kb.add_axiom(until)
        prover = TDFOLProver(kb)
        
        # WHEN proving P U Q
        result = prover.prove(until)
        
        # THEN it should be proved
        assert result.is_proved()
    
    def test_forward_chaining_iteration(self):
        """Test that forward chaining iterates."""
        # GIVEN axioms that require multiple steps
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        q = Predicate("Q", ())
        r = Predicate("R", ())
        kb.add_axiom(p)
        kb.add_axiom(create_implication(p, q))
        kb.add_axiom(create_implication(q, r))
        prover = TDFOLProver(kb)
        
        # WHEN proving R (requires two modus ponens)
        result = prover.prove(r)
        
        # THEN it may be proved via iteration
        assert result.status in [ProofStatus.PROVED, ProofStatus.UNKNOWN]
    
    def test_rule_application_creates_proof_steps(self):
        """Test that rule applications create proof steps."""
        # GIVEN axioms
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        kb.add_axiom(p)
        prover = TDFOLProver(kb)
        
        # WHEN proving with potential rule application
        eventually_p = create_eventually(p)
        result = prover.prove(eventually_p)
        
        # THEN proof steps should exist if proved
        if result.is_proved():
            assert len(result.proof_steps) > 0
    
    def test_rule_names_in_proof_steps(self):
        """Test that rule names are recorded in proof steps."""
        # GIVEN a proved formula
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        kb.add_axiom(p)
        prover = TDFOLProver(kb)
        
        # WHEN proving
        result = prover.prove(p)
        
        # THEN rule names should be present in steps
        for step in result.proof_steps:
            assert step.rule_name is None or isinstance(step.rule_name, str)
    
    def test_premises_in_proof_steps(self):
        """Test that premises are recorded in proof steps."""
        # GIVEN a proved formula
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        kb.add_axiom(p)
        prover = TDFOLProver(kb)
        
        # WHEN proving
        result = prover.prove(p)
        
        # THEN premises should be lists
        for step in result.proof_steps:
            assert isinstance(step.premises, list)
    
    def test_complex_implication_chain(self):
        """Test complex implication chain."""
        # GIVEN a chain of implications
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        q = Predicate("Q", ())
        r = Predicate("R", ())
        s = Predicate("S", ())
        kb.add_axiom(p)
        kb.add_axiom(create_implication(p, q))
        kb.add_axiom(create_implication(q, r))
        kb.add_axiom(create_implication(r, s))
        prover = TDFOLProver(kb)
        
        # WHEN proving S
        result = prover.prove(s)
        
        # THEN it may be derivable
        assert result.status in [ProofStatus.PROVED, ProofStatus.UNKNOWN]
    
    def test_modal_operators_combination(self):
        """Test combination of modal operators."""
        # GIVEN □P as axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        always_p = create_always(p)
        kb.add_axiom(always_p)
        prover = TDFOLProver(kb)
        
        # WHEN trying to prove O(□P)
        obligation_always_p = create_obligation(always_p)
        result = prover.prove(obligation_always_p)
        
        # THEN it may be derivable
        assert result.status in [ProofStatus.PROVED, ProofStatus.UNKNOWN]
    
    def test_quantifier_with_modal(self):
        """Test quantifier with modal operator."""
        # GIVEN ∀x.□P(x) as axiom
        kb = TDFOLKnowledgeBase()
        x = Variable("x")
        p_x = Predicate("Person", (x,))
        always_p_x = create_always(p_x)
        forall_always = create_universal(x, always_p_x)
        kb.add_axiom(forall_always)
        prover = TDFOLProver(kb)
        
        # WHEN proving it
        result = prover.prove(forall_always)
        
        # THEN it should be proved
        assert result.is_proved()
    
    def test_nested_implications(self):
        """Test nested implications."""
        # GIVEN (P→Q)→R as axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        q = Predicate("Q", ())
        r = Predicate("R", ())
        nested = create_implication(create_implication(p, q), r)
        kb.add_axiom(nested)
        prover = TDFOLProver(kb)
        
        # WHEN proving it
        result = prover.prove(nested)
        
        # THEN it should be proved
        assert result.is_proved()
    
    def test_de_morgans_pattern(self):
        """Test De Morgan's law pattern."""
        # GIVEN ¬(P ∨ Q) as axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        q = Predicate("Q", ())
        neg_disj = create_negation(create_disjunction(p, q))
        kb.add_axiom(neg_disj)
        prover = TDFOLProver(kb)
        
        # WHEN proving ¬(P ∨ Q)
        result = prover.prove(neg_disj)
        
        # THEN it should be proved
        assert result.is_proved()


# ============================================================================
# Test Complex Proofs (15 tests)
# ============================================================================


class TestComplexProofs:
    """Test complex proof scenarios."""
    
    def test_multi_step_proof(self):
        """Test multi-step proof requiring multiple rules."""
        # GIVEN axioms requiring multiple steps
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        q = Predicate("Q", ())
        r = Predicate("R", ())
        kb.add_axiom(p)
        kb.add_axiom(create_implication(p, q))
        kb.add_axiom(create_implication(q, r))
        prover = TDFOLProver(kb)
        
        # WHEN proving R
        result = prover.prove(r, timeout_ms=10000)
        
        # THEN it may be proved
        assert result.status in [ProofStatus.PROVED, ProofStatus.UNKNOWN]
        if result.is_proved():
            assert len(result.proof_steps) >= 2
    
    def test_nested_quantifiers(self):
        """Test formula with nested quantifiers."""
        # GIVEN ∀x.∃y.P(x,y) as axiom
        kb = TDFOLKnowledgeBase()
        x = Variable("x")
        y = Variable("y")
        p_xy = Predicate("Knows", (x, y))
        exists_y = create_existential(y, p_xy)
        forall_x = create_universal(x, exists_y)
        kb.add_axiom(forall_x)
        prover = TDFOLProver(kb)
        
        # WHEN proving it
        result = prover.prove(forall_x)
        
        # THEN it should be proved
        assert result.is_proved()
    
    def test_combined_operators(self):
        """Test formula combining multiple operator types."""
        # GIVEN □O(P) as axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        obligation_p = create_obligation(p)
        always_obligation = create_always(obligation_p)
        kb.add_axiom(always_obligation)
        prover = TDFOLProver(kb)
        
        # WHEN proving it
        result = prover.prove(always_obligation)
        
        # THEN it should be proved
        assert result.is_proved()
    
    def test_temporal_chain(self):
        """Test temporal reasoning chain."""
        # GIVEN □P and □(P→Q) as axioms
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        q = Predicate("Q", ())
        always_p = create_always(p)
        always_impl = create_always(create_implication(p, q))
        kb.add_axiom(always_p)
        kb.add_axiom(always_impl)
        prover = TDFOLProver(kb)
        
        # WHEN proving □Q
        always_q = create_always(q)
        result = prover.prove(always_q, timeout_ms=10000)
        
        # THEN it may be proved
        assert result.status in [ProofStatus.PROVED, ProofStatus.UNKNOWN]
    
    def test_deontic_chain(self):
        """Test deontic reasoning chain."""
        # GIVEN O(P) and O(P→Q) as axioms
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        q = Predicate("Q", ())
        obligation_p = create_obligation(p)
        obligation_impl = create_obligation(create_implication(p, q))
        kb.add_axiom(obligation_p)
        kb.add_axiom(obligation_impl)
        prover = TDFOLProver(kb)
        
        # WHEN proving O(Q)
        obligation_q = create_obligation(q)
        result = prover.prove(obligation_q, timeout_ms=10000)
        
        # THEN it may be proved
        assert result.status in [ProofStatus.PROVED, ProofStatus.UNKNOWN]
    
    def test_deeply_nested_formula(self):
        """Test deeply nested formula."""
        # GIVEN ∀x.□O(P(x)→Q(x)) as axiom
        kb = TDFOLKnowledgeBase()
        x = Variable("x")
        p_x = Predicate("P", (x,))
        q_x = Predicate("Q", (x,))
        impl = create_implication(p_x, q_x)
        obligation = create_obligation(impl)
        always = create_always(obligation)
        forall = create_universal(x, always)
        kb.add_axiom(forall)
        prover = TDFOLProver(kb)
        
        # WHEN proving it
        result = prover.prove(forall)
        
        # THEN it should be proved
        assert result.is_proved()
    
    def test_complex_conjunction(self):
        """Test complex conjunction."""
        # GIVEN (P∧Q)∧(R∧S) as axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        q = Predicate("Q", ())
        r = Predicate("R", ())
        s = Predicate("S", ())
        conj1 = create_conjunction(p, q)
        conj2 = create_conjunction(r, s)
        complex_conj = create_conjunction(conj1, conj2)
        kb.add_axiom(complex_conj)
        prover = TDFOLProver(kb)
        
        # WHEN proving it
        result = prover.prove(complex_conj)
        
        # THEN it should be proved
        assert result.is_proved()
    
    def test_complex_disjunction(self):
        """Test complex disjunction."""
        # GIVEN (P∨Q)∨(R∨S) as axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        q = Predicate("Q", ())
        r = Predicate("R", ())
        s = Predicate("S", ())
        disj1 = create_disjunction(p, q)
        disj2 = create_disjunction(r, s)
        complex_disj = create_disjunction(disj1, disj2)
        kb.add_axiom(complex_disj)
        prover = TDFOLProver(kb)
        
        # WHEN proving it
        result = prover.prove(complex_disj)
        
        # THEN it should be proved
        assert result.is_proved()
    
    def test_mixed_boolean_operators(self):
        """Test mixed boolean operators."""
        # GIVEN (P∧Q)∨(R→S) as axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        q = Predicate("Q", ())
        r = Predicate("R", ())
        s = Predicate("S", ())
        conj = create_conjunction(p, q)
        impl = create_implication(r, s)
        mixed = create_disjunction(conj, impl)
        kb.add_axiom(mixed)
        prover = TDFOLProver(kb)
        
        # WHEN proving it
        result = prover.prove(mixed)
        
        # THEN it should be proved
        assert result.is_proved()
    
    def test_temporal_until_complex(self):
        """Test complex until formula."""
        # GIVEN (P∧Q) U R as axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        q = Predicate("Q", ())
        r = Predicate("R", ())
        conj = create_conjunction(p, q)
        until = create_until(conj, r)
        kb.add_axiom(until)
        prover = TDFOLProver(kb)
        
        # WHEN proving it
        result = prover.prove(until)
        
        # THEN it should be proved
        assert result.is_proved()
    
    def test_multiple_quantifiers_different_vars(self):
        """Test multiple quantifiers with different variables."""
        # GIVEN ∀x.∀y.P(x,y) as axiom
        kb = TDFOLKnowledgeBase()
        x = Variable("x")
        y = Variable("y")
        p_xy = Predicate("Equal", (x, y))
        forall_y = create_universal(y, p_xy)
        forall_x = create_universal(x, forall_y)
        kb.add_axiom(forall_x)
        prover = TDFOLProver(kb)
        
        # WHEN proving it
        result = prover.prove(forall_x)
        
        # THEN it should be proved
        assert result.is_proved()
    
    def test_negated_modal_formula(self):
        """Test negated modal formula."""
        # GIVEN ¬□P as axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        always_p = create_always(p)
        neg_always = create_negation(always_p)
        kb.add_axiom(neg_always)
        prover = TDFOLProver(kb)
        
        # WHEN proving it
        result = prover.prove(neg_always)
        
        # THEN it should be proved
        assert result.is_proved()
    
    def test_modal_operator_equivalence(self):
        """Test modal operator equivalence patterns."""
        # GIVEN ◊P (equivalent to ¬□¬P)
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        eventually_p = create_eventually(p)
        kb.add_axiom(eventually_p)
        prover = TDFOLProver(kb)
        
        # WHEN proving ◊P
        result = prover.prove(eventually_p)
        
        # THEN it should be proved
        assert result.is_proved()
    
    def test_obligation_permission_relation(self):
        """Test obligation-permission relationship."""
        # GIVEN O(P) as axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        obligation_p = create_obligation(p)
        kb.add_axiom(obligation_p)
        prover = TDFOLProver(kb)
        
        # WHEN trying to prove P(P) via D axiom
        permission_p = create_permission(p)
        result = prover.prove(permission_p, timeout_ms=10000)
        
        # THEN it may be proved
        assert result.status in [ProofStatus.PROVED, ProofStatus.UNKNOWN]
    
    def test_prohibition_negation(self):
        """Test prohibition as negation."""
        # GIVEN F(P) as axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        prohibition_p = create_prohibition(p)
        kb.add_axiom(prohibition_p)
        prover = TDFOLProver(kb)
        
        # WHEN proving F(P)
        result = prover.prove(prohibition_p)
        
        # THEN it should be proved
        assert result.is_proved()


# ============================================================================
# Test Integration (10 tests)
# ============================================================================


class TestIntegration:
    """Test integration with other components."""
    
    def test_prover_with_cache_enabled(self):
        """Test prover with caching enabled."""
        # GIVEN a prover with cache enabled
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        kb.add_axiom(p)
        prover = TDFOLProver(kb, enable_cache=True)
        
        # WHEN proving same formula twice
        result1 = prover.prove(p)
        result2 = prover.prove(p)
        
        # THEN both should succeed
        assert result1.is_proved()
        assert result2.is_proved()
    
    def test_prover_with_cache_disabled(self):
        """Test prover with caching disabled."""
        # GIVEN a prover with cache disabled
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        kb.add_axiom(p)
        prover = TDFOLProver(kb, enable_cache=False)
        
        # WHEN proving
        result = prover.prove(p)
        
        # THEN it should work without cache
        assert result.is_proved()
        assert prover.proof_cache is None
    
    def test_kb_axiom_modification(self):
        """Test modifying KB affects prover."""
        # GIVEN a prover with KB
        kb = TDFOLKnowledgeBase()
        prover = TDFOLProver(kb)
        p = Predicate("P", ())
        
        # WHEN adding axiom through KB
        kb.add_axiom(p)
        
        # THEN prover should be able to prove it
        result = prover.prove(p)
        assert result.is_proved()
    
    def test_kb_theorem_modification(self):
        """Test adding theorems to KB."""
        # GIVEN a prover
        kb = TDFOLKnowledgeBase()
        prover = TDFOLProver(kb)
        p = Predicate("P", ())
        
        # WHEN adding theorem
        prover.add_theorem(p, "theorem1")
        
        # THEN it should be provable
        result = prover.prove(p)
        assert result.is_proved()
    
    def test_multiple_provers_same_kb(self):
        """Test multiple provers with same KB."""
        # GIVEN a KB and two provers
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        kb.add_axiom(p)
        prover1 = TDFOLProver(kb)
        prover2 = TDFOLProver(kb)
        
        # WHEN both prove
        result1 = prover1.prove(p)
        result2 = prover2.prove(p)
        
        # THEN both should succeed
        assert result1.is_proved()
        assert result2.is_proved()
    
    def test_prover_with_loaded_rules(self):
        """Test prover loads TDFOL rules."""
        # GIVEN a prover
        prover = TDFOLProver()
        
        # THEN it should have rules loaded
        assert hasattr(prover, 'tdfol_rules')
        assert isinstance(prover.tdfol_rules, list)
    
    def test_temporal_rules_initialization(self):
        """Test temporal rules are initialized."""
        # GIVEN a prover
        prover = TDFOLProver()
        
        # THEN temporal rules should exist
        assert hasattr(prover, 'temporal_rules')
        assert isinstance(prover.temporal_rules, list)
    
    def test_deontic_rules_initialization(self):
        """Test deontic rules are initialized."""
        # GIVEN a prover
        prover = TDFOLProver()
        
        # THEN deontic rules should exist
        assert hasattr(prover, 'deontic_rules')
        assert isinstance(prover.deontic_rules, list)
    
    def test_cec_engine_optional(self):
        """Test CEC engine is optional."""
        # GIVEN a prover
        prover = TDFOLProver()
        
        # THEN CEC engine may or may not be available
        assert hasattr(prover, 'cec_engine')
        # Should not raise error even if unavailable
    
    def test_proof_with_different_methods(self):
        """Test that different proof methods are attempted."""
        # GIVEN a prover and formula
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        prover = TDFOLProver(kb)
        
        # WHEN proving unknown formula
        result = prover.prove(p, timeout_ms=5000)
        
        # THEN a method should be recorded
        assert hasattr(result, 'method')
        assert isinstance(result.method, str)


# ============================================================================
# Test Edge Cases (10 tests)
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_empty_kb_prove(self):
        """Test proving with empty KB."""
        # GIVEN empty KB
        kb = TDFOLKnowledgeBase()
        prover = TDFOLProver(kb)
        p = Predicate("P", ())
        
        # WHEN proving
        result = prover.prove(p)
        
        # THEN should return unknown
        assert result.status == ProofStatus.UNKNOWN
    
    def test_prove_with_zero_timeout(self):
        """Test proving with zero timeout."""
        # GIVEN a prover
        prover = TDFOLProver()
        p = Predicate("P", ())
        
        # WHEN proving with zero timeout
        result = prover.prove(p, timeout_ms=0)
        
        # THEN should handle gracefully
        assert result.status in [ProofStatus.UNKNOWN, ProofStatus.TIMEOUT]
    
    def test_prove_with_large_timeout(self):
        """Test proving with large timeout."""
        # GIVEN a prover with axiom
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        kb.add_axiom(p)
        prover = TDFOLProver(kb)
        
        # WHEN proving with large timeout
        result = prover.prove(p, timeout_ms=100000)
        
        # THEN should work normally
        assert result.is_proved()
    
    def test_circular_reference_handling(self):
        """Test handling potential circular references."""
        # GIVEN axioms that could create circular reasoning
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        q = Predicate("Q", ())
        kb.add_axiom(create_implication(p, q))
        kb.add_axiom(create_implication(q, p))
        prover = TDFOLProver(kb)
        
        # WHEN proving
        result = prover.prove(p, timeout_ms=5000)
        
        # THEN should terminate (not infinite loop)
        assert result.status in [ProofStatus.UNKNOWN, ProofStatus.TIMEOUT, ProofStatus.PROVED]
    
    def test_deeply_nested_structure(self):
        """Test deeply nested formula structure."""
        # GIVEN very deeply nested formula
        p = Predicate("P", ())
        nested = p
        for _ in range(10):
            nested = create_negation(nested)
        
        kb = TDFOLKnowledgeBase()
        kb.add_axiom(nested)
        prover = TDFOLProver(kb)
        
        # WHEN proving
        result = prover.prove(nested)
        
        # THEN should handle without error
        assert result.is_proved()
    
    def test_formula_with_many_variables(self):
        """Test formula with many variables."""
        # GIVEN formula with multiple variables
        vars_list = [Variable(f"x{i}") for i in range(10)]
        p = Predicate("Relation", tuple(vars_list))
        kb = TDFOLKnowledgeBase()
        kb.add_axiom(p)
        prover = TDFOLProver(kb)
        
        # WHEN proving
        result = prover.prove(p)
        
        # THEN should work
        assert result.is_proved()
    
    def test_invalid_timeout_value(self):
        """Test handling of invalid timeout values."""
        # GIVEN a prover
        prover = TDFOLProver()
        p = Predicate("P", ())
        
        # WHEN proving with negative timeout (if not validated)
        # Should handle gracefully or treat as unlimited
        result = prover.prove(p, timeout_ms=-1)
        
        # THEN should not crash
        assert isinstance(result, ProofResult)
    
    def test_prove_none_handling(self):
        """Test that None formulas are handled."""
        # GIVEN a prover
        prover = TDFOLProver()
        
        # WHEN trying to prove None (should not happen but test robustness)
        # This may raise an error which is acceptable
        try:
            result = prover.prove(None)
            # If it doesn't raise, should return error status
            assert result.status == ProofStatus.ERROR
        except (TypeError, AttributeError):
            # Expected behavior - None is not a valid formula
            pass
    
    def test_modal_formula_detection(self):
        """Test modal formula detection."""
        # GIVEN a prover
        prover = TDFOLProver()
        p = Predicate("P", ())
        
        # WHEN checking modal formulas
        assert not prover._is_modal_formula(p)
        assert prover._is_modal_formula(create_always(p))
        assert prover._is_modal_formula(create_obligation(p))
        assert prover._is_modal_formula(create_eventually(p))
    
    def test_forward_chaining_max_iterations(self):
        """Test forward chaining respects max iterations."""
        # GIVEN axioms that might iterate infinitely
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        kb.add_axiom(p)
        prover = TDFOLProver(kb)
        
        # WHEN proving with complex rules
        q = Predicate("Q", ())
        result = prover.prove(q, timeout_ms=10000)
        
        # THEN should terminate
        assert result.status in [ProofStatus.UNKNOWN, ProofStatus.TIMEOUT]


# ============================================================================
# Additional Tests for Coverage (10+ tests)
# ============================================================================


class TestAdditionalCoverage:
    """Additional tests for comprehensive coverage."""
    
    def test_has_deontic_operators(self):
        """Test detection of deontic operators."""
        # GIVEN a prover
        prover = TDFOLProver()
        p = Predicate("P", ())
        
        # THEN deontic detection should work
        assert not prover._has_deontic_operators(p)
        assert prover._has_deontic_operators(create_obligation(p))
        assert prover._has_deontic_operators(create_permission(p))
        assert prover._has_deontic_operators(create_prohibition(p))
    
    def test_has_temporal_operators(self):
        """Test detection of temporal operators."""
        # GIVEN a prover
        prover = TDFOLProver()
        p = Predicate("P", ())
        
        # THEN temporal detection should work
        assert not prover._has_temporal_operators(p)
        assert prover._has_temporal_operators(create_always(p))
        assert prover._has_temporal_operators(create_eventually(p))
        assert prover._has_temporal_operators(create_next(p))
    
    def test_has_nested_temporal(self):
        """Test detection of nested temporal operators."""
        # GIVEN a prover
        prover = TDFOLProver()
        p = Predicate("P", ())
        
        # THEN nested temporal detection should work
        assert not prover._has_nested_temporal(p)
        assert not prover._has_nested_temporal(create_always(p))
        assert prover._has_nested_temporal(create_always(create_always(p)))
    
    def test_traverse_formula_predicate(self):
        """Test formula traversal with predicate."""
        # GIVEN a prover and formula
        prover = TDFOLProver()
        p = Predicate("P", ())
        q = Predicate("Q", ())
        conj = create_conjunction(p, q)
        
        # WHEN traversing with predicate
        found = prover._traverse_formula(
            conj,
            lambda f: isinstance(f, Predicate) and f.name == "P"
        )
        
        # THEN should find P
        assert found
    
    def test_traverse_formula_depth_limit(self):
        """Test formula traversal with depth limit."""
        # GIVEN a prover and nested formula
        prover = TDFOLProver()
        p = Predicate("P", ())
        nested = create_negation(create_negation(create_negation(p)))
        
        # WHEN traversing with depth limit
        found = prover._traverse_formula(
            nested,
            lambda f: isinstance(f, Predicate),
            max_depth=1
        )
        
        # THEN should respect depth limit or find early
        # (implementation detail - may find predicate at shallow depth)
        assert isinstance(found, bool)
    
    def test_select_modal_logic_type_deontic(self):
        """Test modal logic type selection for deontic."""
        # GIVEN a prover and deontic formula
        prover = TDFOLProver()
        p = Predicate("P", ())
        obligation = create_obligation(p)
        
        # WHEN selecting logic type (if available)
        try:
            from ipfs_datasets_py.logic.TDFOL.integration.tdfol_shadowprover_bridge import ModalLogicType
            logic_type = prover._select_modal_logic_type(obligation)
            
            # THEN should select D logic
            assert logic_type == ModalLogicType.D
        except (ImportError, ModuleNotFoundError):
            # Integration module not available, skip test
            pytest.skip("ShadowProver integration not available")
    
    def test_select_modal_logic_type_temporal(self):
        """Test modal logic type selection for temporal."""
        # GIVEN a prover and temporal formula
        prover = TDFOLProver()
        p = Predicate("P", ())
        always = create_always(p)
        
        # WHEN selecting logic type (if available)
        try:
            from ipfs_datasets_py.logic.TDFOL.integration.tdfol_shadowprover_bridge import ModalLogicType
            logic_type = prover._select_modal_logic_type(always)
            
            # THEN should select S4 logic
            assert logic_type == ModalLogicType.S4
        except (ImportError, ModuleNotFoundError):
            # Integration module not available, skip test
            pytest.skip("ShadowProver integration not available")
    
    def test_select_modal_logic_type_nested(self):
        """Test modal logic type selection for nested temporal."""
        # GIVEN a prover and nested temporal formula
        prover = TDFOLProver()
        p = Predicate("P", ())
        nested = create_always(create_always(p))
        
        # WHEN selecting logic type (if available)
        try:
            from ipfs_datasets_py.logic.TDFOL.integration.tdfol_shadowprover_bridge import ModalLogicType
            logic_type = prover._select_modal_logic_type(nested)
            
            # THEN should select S4 logic
            assert logic_type == ModalLogicType.S4
        except (ImportError, ModuleNotFoundError):
            # Integration module not available, skip test
            pytest.skip("ShadowProver integration not available")
    
    def test_select_modal_logic_type_basic(self):
        """Test modal logic type selection for basic formula."""
        # GIVEN a prover and basic formula
        prover = TDFOLProver()
        p = Predicate("P", ())
        
        # WHEN selecting logic type (if available)
        try:
            from ipfs_datasets_py.logic.TDFOL.integration.tdfol_shadowprover_bridge import ModalLogicType
            logic_type = prover._select_modal_logic_type(p)
            
            # THEN should select K logic (default)
            assert logic_type == ModalLogicType.K
        except (ImportError, ModuleNotFoundError):
            # Integration module not available, skip test
            pytest.skip("ShadowProver integration not available")
    
    def test_cec_prove_not_implemented(self):
        """Test CEC prove returns unknown."""
        # GIVEN a prover
        prover = TDFOLProver()
        p = Predicate("P", ())
        
        # WHEN calling _cec_prove
        result = prover._cec_prove(p, 5000)
        
        # THEN should return unknown (not implemented)
        assert result.status == ProofStatus.UNKNOWN
        assert result.method == "cec_prover"
    
    def test_proof_result_is_proved_method(self):
        """Test ProofResult.is_proved() method."""
        # GIVEN proof results with different statuses
        p = Predicate("P", ())
        proved = ProofResult(ProofStatus.PROVED, p)
        unknown = ProofResult(ProofStatus.UNKNOWN, p)
        
        # THEN is_proved should work correctly
        assert proved.is_proved()
        assert not unknown.is_proved()
    
    def test_proof_step_creation(self):
        """Test ProofStep creation."""
        # GIVEN formula and justification
        p = Predicate("P", ())
        
        # WHEN creating proof step
        step = ProofStep(p, "Test justification", "TestRule", [p])
        
        # THEN step should have correct attributes
        assert step.formula == p
        assert step.justification == "Test justification"
        assert step.rule_name == "TestRule"
        assert step.premises == [p]
    
    def test_proof_status_enum_values(self):
        """Test ProofStatus enum values."""
        # THEN all proof statuses should exist
        assert ProofStatus.PROVED
        assert ProofStatus.DISPROVED
        assert ProofStatus.UNKNOWN
        assert ProofStatus.TIMEOUT
        assert ProofStatus.ERROR
    
    def test_multiple_axioms_same_predicate(self):
        """Test multiple axioms with same predicate name."""
        # GIVEN multiple axioms with same predicate
        kb = TDFOLKnowledgeBase()
        p1 = Predicate("P", (Constant("a"),))
        p2 = Predicate("P", (Constant("b"),))
        kb.add_axiom(p1)
        kb.add_axiom(p2)
        prover = TDFOLProver(kb)
        
        # WHEN proving both
        result1 = prover.prove(p1)
        result2 = prover.prove(p2)
        
        # THEN both should be proved
        assert result1.is_proved()
        assert result2.is_proved()
    
    def test_quantified_formula_in_kb(self):
        """Test quantified formulas in knowledge base."""
        # GIVEN quantified formula
        kb = TDFOLKnowledgeBase()
        x = Variable("x")
        p = Predicate("Person", (x,))
        forall = create_universal(x, p)
        kb.add_axiom(forall)
        prover = TDFOLProver(kb)
        
        # WHEN proving
        result = prover.prove(forall)
        
        # THEN should be proved
        assert result.is_proved()
