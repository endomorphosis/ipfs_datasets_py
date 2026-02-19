"""
Comprehensive tests for TDFOL Propositional Inference Rules.

This module tests all 13 propositional inference rules following the
GIVEN-WHEN-THEN format. Each rule is tested for:
- Basic application (valid inputs)
- Edge cases
- Invalid inputs (should return False for can_apply)
"""

import pytest
from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
    Predicate,
    BinaryFormula,
    UnaryFormula,
    LogicOperator,
)
from ipfs_datasets_py.logic.TDFOL.inference_rules.propositional import (
    ModusPonensRule,
    ModusTollensRule,
    DisjunctiveSyllogismRule,
    HypotheticalSyllogismRule,
    ConjunctionIntroductionRule,
    ConjunctionEliminationLeftRule,
    ConjunctionEliminationRightRule,
    DisjunctionIntroductionLeftRule,
    DoubleNegationEliminationRule,
    DoubleNegationIntroductionRule,
    ContrapositionRule,
    DeMorganAndRule,
    DeMorganOrRule,
)


class TestModusPonensRule:
    """Tests for Modus Ponens: φ, φ → ψ ⊢ ψ"""
    
    def test_modus_ponens_basic_application(self):
        """Test basic modus ponens application."""
        # GIVEN predicates P and Q, and formulas P and P → Q
        p = Predicate('P', [])
        q = Predicate('Q', [])
        p_implies_q = BinaryFormula(LogicOperator.IMPLIES, p, q)
        rule = ModusPonensRule()
        
        # WHEN applying modus ponens
        can_apply = rule.can_apply(p, p_implies_q)
        result = rule.apply(p, p_implies_q) if can_apply else None
        
        # THEN it should succeed and return Q
        assert can_apply is True
        assert result == q
    
    def test_modus_ponens_invalid_wrong_count(self):
        """Test modus ponens with wrong number of formulas."""
        # GIVEN a rule and only one formula
        p = Predicate('P', [])
        rule = ModusPonensRule()
        
        # WHEN checking if rule can apply with wrong count
        can_apply = rule.can_apply(p)
        
        # THEN it should fail
        assert can_apply is False
    
    def test_modus_ponens_invalid_non_matching_antecedent(self):
        """Test modus ponens with non-matching antecedent."""
        # GIVEN P, R, and R → Q (P doesn't match R)
        p = Predicate('P', [])
        q = Predicate('Q', [])
        r = Predicate('R', [])
        r_implies_q = BinaryFormula(LogicOperator.IMPLIES, r, q)
        rule = ModusPonensRule()
        
        # WHEN checking if rule can apply
        can_apply = rule.can_apply(p, r_implies_q)
        
        # THEN it should fail
        assert can_apply is False


class TestModusTollensRule:
    """Tests for Modus Tollens: φ → ψ, ¬ψ ⊢ ¬φ"""
    
    def test_modus_tollens_basic_application(self):
        """Test basic modus tollens application."""
        # GIVEN P → Q and ¬Q
        p = Predicate('P', [])
        q = Predicate('Q', [])
        p_implies_q = BinaryFormula(LogicOperator.IMPLIES, p, q)
        not_q = UnaryFormula(LogicOperator.NOT, q)
        rule = ModusTollensRule()
        
        # WHEN applying modus tollens
        can_apply = rule.can_apply(p_implies_q, not_q)
        result = rule.apply(p_implies_q, not_q) if can_apply else None
        
        # THEN it should return ¬P
        assert can_apply is True
        assert isinstance(result, UnaryFormula)
        assert result.operator == LogicOperator.NOT
        assert result.formula == p
    
    def test_modus_tollens_invalid_non_negation(self):
        """Test modus tollens with non-negated consequent."""
        # GIVEN P → Q and Q (not ¬Q)
        p = Predicate('P', [])
        q = Predicate('Q', [])
        p_implies_q = BinaryFormula(LogicOperator.IMPLIES, p, q)
        rule = ModusTollensRule()
        
        # WHEN checking if rule can apply
        can_apply = rule.can_apply(p_implies_q, q)
        
        # THEN it should fail
        assert can_apply is False


class TestDisjunctiveSyllogismRule:
    """Tests for Disjunctive Syllogism: φ ∨ ψ, ¬φ ⊢ ψ"""
    
    def test_disjunctive_syllogism_basic(self):
        """Test basic disjunctive syllogism."""
        # GIVEN P ∨ Q and ¬P
        p = Predicate('P', [])
        q = Predicate('Q', [])
        p_or_q = BinaryFormula(LogicOperator.OR, p, q)
        not_p = UnaryFormula(LogicOperator.NOT, p)
        rule = DisjunctiveSyllogismRule()
        
        # WHEN applying the rule
        can_apply = rule.can_apply(p_or_q, not_p)
        result = rule.apply(p_or_q, not_p) if can_apply else None
        
        # THEN it should return Q
        assert can_apply is True
        assert result == q
    
    def test_disjunctive_syllogism_invalid_conjunction(self):
        """Test disjunctive syllogism with AND instead of OR."""
        # GIVEN P ∧ Q (not P ∨ Q) and ¬P
        p = Predicate('P', [])
        q = Predicate('Q', [])
        p_and_q = BinaryFormula(LogicOperator.AND, p, q)
        not_p = UnaryFormula(LogicOperator.NOT, p)
        rule = DisjunctiveSyllogismRule()
        
        # WHEN checking if rule can apply
        can_apply = rule.can_apply(p_and_q, not_p)
        
        # THEN it should fail
        assert can_apply is False


class TestHypotheticalSyllogismRule:
    """Tests for Hypothetical Syllogism: φ → ψ, ψ → χ ⊢ φ → χ"""
    
    def test_hypothetical_syllogism_basic(self):
        """Test basic hypothetical syllogism."""
        # GIVEN P → Q and Q → R
        p = Predicate('P', [])
        q = Predicate('Q', [])
        r = Predicate('R', [])
        p_implies_q = BinaryFormula(LogicOperator.IMPLIES, p, q)
        q_implies_r = BinaryFormula(LogicOperator.IMPLIES, q, r)
        rule = HypotheticalSyllogismRule()
        
        # WHEN applying the rule
        can_apply = rule.can_apply(p_implies_q, q_implies_r)
        result = rule.apply(p_implies_q, q_implies_r) if can_apply else None
        
        # THEN it should return P → R
        assert can_apply is True
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.IMPLIES
        assert result.left == p
        assert result.right == r
    
    def test_hypothetical_syllogism_invalid_non_matching(self):
        """Test hypothetical syllogism with non-matching middle."""
        # GIVEN P → Q and R → S (Q doesn't match R)
        p = Predicate('P', [])
        q = Predicate('Q', [])
        r = Predicate('R', [])
        s = Predicate('S', [])
        p_implies_q = BinaryFormula(LogicOperator.IMPLIES, p, q)
        r_implies_s = BinaryFormula(LogicOperator.IMPLIES, r, s)
        rule = HypotheticalSyllogismRule()
        
        # WHEN checking if rule can apply
        can_apply = rule.can_apply(p_implies_q, r_implies_s)
        
        # THEN it should fail
        assert can_apply is False


class TestConjunctionRules:
    """Tests for Conjunction Introduction and Elimination rules."""
    
    def test_conjunction_introduction(self):
        """Test conjunction introduction: φ, ψ ⊢ φ ∧ ψ"""
        # GIVEN P and Q
        p = Predicate('P', [])
        q = Predicate('Q', [])
        rule = ConjunctionIntroductionRule()
        
        # WHEN applying conjunction introduction
        can_apply = rule.can_apply(p, q)
        result = rule.apply(p, q) if can_apply else None
        
        # THEN it should return P ∧ Q
        assert can_apply is True
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.AND
        assert result.left == p
        assert result.right == q
    
    def test_conjunction_elimination_left(self):
        """Test conjunction elimination (left): φ ∧ ψ ⊢ φ"""
        # GIVEN P ∧ Q
        p = Predicate('P', [])
        q = Predicate('Q', [])
        p_and_q = BinaryFormula(LogicOperator.AND, p, q)
        rule = ConjunctionEliminationLeftRule()
        
        # WHEN applying conjunction elimination (left)
        can_apply = rule.can_apply(p_and_q)
        result = rule.apply(p_and_q) if can_apply else None
        
        # THEN it should return P
        assert can_apply is True
        assert result == p
    
    def test_conjunction_elimination_right(self):
        """Test conjunction elimination (right): φ ∧ ψ ⊢ ψ"""
        # GIVEN P ∧ Q
        p = Predicate('P', [])
        q = Predicate('Q', [])
        p_and_q = BinaryFormula(LogicOperator.AND, p, q)
        rule = ConjunctionEliminationRightRule()
        
        # WHEN applying conjunction elimination (right)
        can_apply = rule.can_apply(p_and_q)
        result = rule.apply(p_and_q) if can_apply else None
        
        # THEN it should return Q
        assert can_apply is True
        assert result == q


class TestDoubleNegationRules:
    """Tests for Double Negation Introduction and Elimination."""
    
    def test_double_negation_elimination(self):
        """Test double negation elimination: ¬¬φ ⊢ φ"""
        # GIVEN ¬¬P
        p = Predicate('P', [])
        not_p = UnaryFormula(LogicOperator.NOT, p)
        not_not_p = UnaryFormula(LogicOperator.NOT, not_p)
        rule = DoubleNegationEliminationRule()
        
        # WHEN applying double negation elimination
        can_apply = rule.can_apply(not_not_p)
        result = rule.apply(not_not_p) if can_apply else None
        
        # THEN it should return P
        assert can_apply is True
        assert result == p
    
    def test_double_negation_introduction(self):
        """Test double negation introduction: φ ⊢ ¬¬φ"""
        # GIVEN P
        p = Predicate('P', [])
        rule = DoubleNegationIntroductionRule()
        
        # WHEN applying double negation introduction
        can_apply = rule.can_apply(p)
        result = rule.apply(p) if can_apply else None
        
        # THEN it should return ¬¬P
        assert can_apply is True
        assert isinstance(result, UnaryFormula)
        assert result.operator == LogicOperator.NOT
        assert isinstance(result.formula, UnaryFormula)
        assert result.formula.operator == LogicOperator.NOT
        assert result.formula.formula == p


class TestContrapositionRule:
    """Tests for Contraposition: φ → ψ ⊢ ¬ψ → ¬φ"""
    
    def test_contraposition_basic(self):
        """Test basic contraposition."""
        # GIVEN P → Q
        p = Predicate('P', [])
        q = Predicate('Q', [])
        p_implies_q = BinaryFormula(LogicOperator.IMPLIES, p, q)
        rule = ContrapositionRule()
        
        # WHEN applying contraposition
        can_apply = rule.can_apply(p_implies_q)
        result = rule.apply(p_implies_q) if can_apply else None
        
        # THEN it should return ¬Q → ¬P
        assert can_apply is True
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.IMPLIES
        assert isinstance(result.left, UnaryFormula)
        assert result.left.operator == LogicOperator.NOT
        assert result.left.formula == q
        assert isinstance(result.right, UnaryFormula)
        assert result.right.operator == LogicOperator.NOT
        assert result.right.formula == p
    
    def test_contraposition_invalid_non_implication(self):
        """Test contraposition with non-implication."""
        # GIVEN P ∧ Q (not an implication)
        p = Predicate('P', [])
        q = Predicate('Q', [])
        p_and_q = BinaryFormula(LogicOperator.AND, p, q)
        rule = ContrapositionRule()
        
        # WHEN checking if rule can apply
        can_apply = rule.can_apply(p_and_q)
        
        # THEN it should fail
        assert can_apply is False


class TestDeMorganRules:
    """Tests for De Morgan's Laws."""
    
    def test_demorgan_and_rule(self):
        """Test De Morgan for AND: ¬(φ ∧ ψ) ⊢ ¬φ ∨ ¬ψ"""
        # GIVEN ¬(P ∧ Q)
        p = Predicate('P', [])
        q = Predicate('Q', [])
        p_and_q = BinaryFormula(LogicOperator.AND, p, q)
        not_p_and_q = UnaryFormula(LogicOperator.NOT, p_and_q)
        rule = DeMorganAndRule()
        
        # WHEN applying De Morgan's AND rule
        can_apply = rule.can_apply(not_p_and_q)
        result = rule.apply(not_p_and_q) if can_apply else None
        
        # THEN it should return ¬P ∨ ¬Q
        assert can_apply is True
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.OR
        assert isinstance(result.left, UnaryFormula)
        assert result.left.operator == LogicOperator.NOT
        assert result.left.formula == p
        assert isinstance(result.right, UnaryFormula)
        assert result.right.operator == LogicOperator.NOT
        assert result.right.formula == q
    
    def test_demorgan_or_rule(self):
        """Test De Morgan for OR: ¬(φ ∨ ψ) ⊢ ¬φ ∧ ¬ψ"""
        # GIVEN ¬(P ∨ Q)
        p = Predicate('P', [])
        q = Predicate('Q', [])
        p_or_q = BinaryFormula(LogicOperator.OR, p, q)
        not_p_or_q = UnaryFormula(LogicOperator.NOT, p_or_q)
        rule = DeMorganOrRule()
        
        # WHEN applying De Morgan's OR rule
        can_apply = rule.can_apply(not_p_or_q)
        result = rule.apply(not_p_or_q) if can_apply else None
        
        # THEN it should return ¬P ∧ ¬Q
        assert can_apply is True
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.AND
        assert isinstance(result.left, UnaryFormula)
        assert result.left.operator == LogicOperator.NOT
        assert result.left.formula == p
        assert isinstance(result.right, UnaryFormula)
        assert result.right.operator == LogicOperator.NOT
        assert result.right.formula == q
    
    def test_demorgan_invalid_non_negated_conjunction(self):
        """Test De Morgan with non-negated conjunction."""
        # GIVEN P ∧ Q (not ¬(P ∧ Q))
        p = Predicate('P', [])
        q = Predicate('Q', [])
        p_and_q = BinaryFormula(LogicOperator.AND, p, q)
        rule = DeMorganAndRule()
        
        # WHEN checking if rule can apply
        can_apply = rule.can_apply(p_and_q)
        
        # THEN it should fail
        assert can_apply is False


class TestDisjunctionIntroductionRule:
    """Tests for Disjunction Introduction."""
    
    def test_disjunction_introduction_left(self):
        """Test disjunction introduction (left): φ ⊢ φ ∨ ψ"""
        # GIVEN P and Q (any formula Q)
        p = Predicate('P', [])
        q = Predicate('Q', [])
        rule = DisjunctionIntroductionLeftRule()
        
        # WHEN applying disjunction introduction
        can_apply = rule.can_apply(p, q)
        result = rule.apply(p, q) if can_apply else None
        
        # THEN it should return P ∨ Q
        assert can_apply is True
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.OR
        assert result.left == p
        assert result.right == q


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
