"""
Tests for TDFOL Expansion Rules (Phase 1 refactoring).

This module tests the expansion rule base classes and concrete implementations
that were extracted to eliminate code duplication between modal_tableaux.py
and tdfol_inference_rules.py.
"""

import pytest
from ipfs_datasets_py.logic.TDFOL import (
    BinaryFormula,
    ExpansionContext,
    ExpansionResult,
    ExpansionRule,
    Formula,
    LogicOperator,
    Predicate,
    Constant,
    UnaryFormula,
)
from ipfs_datasets_py.logic.TDFOL.expansion_rules import (
    AndExpansionRule,
    OrExpansionRule,
    ImpliesExpansionRule,
    IffExpansionRule,
    NotExpansionRule,
    get_all_expansion_rules,
    select_expansion_rule,
)


class TestExpansionContext:
    """Tests for ExpansionContext dataclass."""
    
    def test_expansion_context_creation(self):
        """Test creating an expansion context."""
        # GIVEN a formula
        formula = Predicate("P", (Constant("a"),))
        
        # WHEN creating an expansion context
        context = ExpansionContext(formula=formula)
        
        # THEN context should have correct properties
        assert context.formula == formula
        assert context.negated == False
        assert context.world_id == 0
        assert context.assumptions == []
        assert context.options == {}
    
    def test_expansion_context_with_negation(self):
        """Test expansion context with negation."""
        # GIVEN a formula
        formula = Predicate("Q", (Constant("b"),))
        
        # WHEN creating a negated context
        context = ExpansionContext(
            formula=formula,
            negated=True,
            world_id=5
        )
        
        # THEN context should reflect negation
        assert context.formula == formula
        assert context.negated == True
        assert context.world_id == 5


class TestExpansionResult:
    """Tests for ExpansionResult class."""
    
    def test_linear_expansion(self):
        """Test creating a linear expansion result."""
        # GIVEN two formulas
        p = Predicate("P", (Constant("a"),))
        q = Predicate("Q", (Constant("b"),))
        
        # WHEN creating a linear expansion
        result = ExpansionResult.linear((p, False), (q, False))
        
        # THEN result should be non-branching with single branch
        assert result.is_branching == False
        assert len(result.branches) == 1
        assert len(result.branches[0]) == 2
        assert result.branches[0][0] == (p, False)
        assert result.branches[0][1] == (q, False)
    
    def test_branching_expansion(self):
        """Test creating a branching expansion result."""
        # GIVEN two formulas
        p = Predicate("P", (Constant("a"),))
        q = Predicate("Q", (Constant("b"),))
        
        # WHEN creating a branching expansion (two branches)
        result = ExpansionResult.branching(
            [(p, False)],
            [(q, False)]
        )
        
        # THEN result should be branching with two branches
        assert result.is_branching == True
        assert len(result.branches) == 2
        assert result.branches[0] == [(p, False)]
        assert result.branches[1] == [(q, False)]


class TestAndExpansionRule:
    """Tests for AND expansion rule."""
    
    def test_can_expand_and_formula(self):
        """Test that AND rule can expand conjunction."""
        # GIVEN an AND formula
        p = Predicate("P", (Constant("a"),))
        q = Predicate("Q", (Constant("b"),))
        formula = BinaryFormula(LogicOperator.AND, p, q)
        
        # WHEN checking if AND rule can expand it
        rule = AndExpansionRule()
        can_expand = rule.can_expand(formula, negated=False)
        
        # THEN it should be expandable
        assert can_expand == True
    
    def test_cannot_expand_non_and_formula(self):
        """Test that AND rule cannot expand non-conjunction."""
        # GIVEN an OR formula
        p = Predicate("P", (Constant("a"),))
        q = Predicate("Q", (Constant("b"),))
        formula = BinaryFormula(LogicOperator.OR, p, q)
        
        # WHEN checking if AND rule can expand it
        rule = AndExpansionRule()
        can_expand = rule.can_expand(formula, negated=False)
        
        # THEN it should not be expandable
        assert can_expand == False
    
    def test_expand_positive_and(self):
        """Test expanding positive AND: φ ∧ ψ → φ, ψ (linear)."""
        # GIVEN a positive AND formula
        p = Predicate("P", (Constant("a"),))
        q = Predicate("Q", (Constant("b"),))
        formula = BinaryFormula(LogicOperator.AND, p, q)
        context = ExpansionContext(formula=formula, negated=False)
        
        # WHEN expanding it
        rule = AndExpansionRule()
        result = rule.expand(context)
        
        # THEN should produce linear expansion with both subformulas
        assert result.is_branching == False
        assert len(result.branches) == 1
        assert len(result.branches[0]) == 2
        assert result.branches[0][0] == (p, False)
        assert result.branches[0][1] == (q, False)
    
    def test_expand_negative_and(self):
        """Test expanding negative AND: ¬(φ ∧ ψ) → ¬φ | ¬ψ (branching)."""
        # GIVEN a negated AND formula
        p = Predicate("P", (Constant("a"),))
        q = Predicate("Q", (Constant("b"),))
        formula = BinaryFormula(LogicOperator.AND, p, q)
        context = ExpansionContext(formula=formula, negated=True)
        
        # WHEN expanding it
        rule = AndExpansionRule()
        result = rule.expand(context)
        
        # THEN should produce branching expansion (De Morgan's law)
        assert result.is_branching == True
        assert len(result.branches) == 2
        assert result.branches[0] == [(p, True)]
        assert result.branches[1] == [(q, True)]


class TestOrExpansionRule:
    """Tests for OR expansion rule."""
    
    def test_expand_positive_or(self):
        """Test expanding positive OR: φ ∨ ψ → φ | ψ (branching)."""
        # GIVEN a positive OR formula
        p = Predicate("P", (Constant("a"),))
        q = Predicate("Q", (Constant("b"),))
        formula = BinaryFormula(LogicOperator.OR, p, q)
        context = ExpansionContext(formula=formula, negated=False)
        
        # WHEN expanding it
        rule = OrExpansionRule()
        result = rule.expand(context)
        
        # THEN should produce branching expansion
        assert result.is_branching == True
        assert len(result.branches) == 2
        assert result.branches[0] == [(p, False)]
        assert result.branches[1] == [(q, False)]
    
    def test_expand_negative_or(self):
        """Test expanding negative OR: ¬(φ ∨ ψ) → ¬φ, ¬ψ (linear)."""
        # GIVEN a negated OR formula
        p = Predicate("P", (Constant("a"),))
        q = Predicate("Q", (Constant("b"),))
        formula = BinaryFormula(LogicOperator.OR, p, q)
        context = ExpansionContext(formula=formula, negated=True)
        
        # WHEN expanding it
        rule = OrExpansionRule()
        result = rule.expand(context)
        
        # THEN should produce linear expansion (De Morgan's law)
        assert result.is_branching == False
        assert len(result.branches) == 1
        assert len(result.branches[0]) == 2
        assert result.branches[0][0] == (p, True)
        assert result.branches[0][1] == (q, True)


class TestImpliesExpansionRule:
    """Tests for IMPLIES expansion rule."""
    
    def test_expand_positive_implies(self):
        """Test expanding positive IMPLIES: φ → ψ ≡ ¬φ | ψ (branching)."""
        # GIVEN a positive IMPLIES formula
        p = Predicate("P", (Constant("a"),))
        q = Predicate("Q", (Constant("b"),))
        formula = BinaryFormula(LogicOperator.IMPLIES, p, q)
        context = ExpansionContext(formula=formula, negated=False)
        
        # WHEN expanding it
        rule = ImpliesExpansionRule()
        result = rule.expand(context)
        
        # THEN should produce branching: ¬φ | ψ
        assert result.is_branching == True
        assert len(result.branches) == 2
        assert result.branches[0] == [(p, True)]
        assert result.branches[1] == [(q, False)]
    
    def test_expand_negative_implies(self):
        """Test expanding negative IMPLIES: ¬(φ → ψ) → φ, ¬ψ (linear)."""
        # GIVEN a negated IMPLIES formula
        p = Predicate("P", (Constant("a"),))
        q = Predicate("Q", (Constant("b"),))
        formula = BinaryFormula(LogicOperator.IMPLIES, p, q)
        context = ExpansionContext(formula=formula, negated=True)
        
        # WHEN expanding it
        rule = ImpliesExpansionRule()
        result = rule.expand(context)
        
        # THEN should produce linear expansion: φ, ¬ψ
        assert result.is_branching == False
        assert len(result.branches) == 1
        assert len(result.branches[0]) == 2
        assert result.branches[0][0] == (p, False)
        assert result.branches[0][1] == (q, True)


class TestIffExpansionRule:
    """Tests for IFF (bi-implication) expansion rule."""
    
    def test_expand_positive_iff(self):
        """Test expanding positive IFF: φ ↔ ψ → (φ, ψ) | (¬φ, ¬ψ) (branching)."""
        # GIVEN a positive IFF formula
        p = Predicate("P", (Constant("a"),))
        q = Predicate("Q", (Constant("b"),))
        formula = BinaryFormula(LogicOperator.IFF, p, q)
        context = ExpansionContext(formula=formula, negated=False)
        
        # WHEN expanding it
        rule = IffExpansionRule()
        result = rule.expand(context)
        
        # THEN should produce branching: (φ, ψ) | (¬φ, ¬ψ)
        assert result.is_branching == True
        assert len(result.branches) == 2
        assert result.branches[0] == [(p, False), (q, False)]
        assert result.branches[1] == [(p, True), (q, True)]
    
    def test_expand_negative_iff(self):
        """Test expanding negative IFF: ¬(φ ↔ ψ) → (φ, ¬ψ) | (¬φ, ψ) (branching)."""
        # GIVEN a negated IFF formula
        p = Predicate("P", (Constant("a"),))
        q = Predicate("Q", (Constant("b"),))
        formula = BinaryFormula(LogicOperator.IFF, p, q)
        context = ExpansionContext(formula=formula, negated=True)
        
        # WHEN expanding it
        rule = IffExpansionRule()
        result = rule.expand(context)
        
        # THEN should produce branching: (φ, ¬ψ) | (¬φ, ψ)
        assert result.is_branching == True
        assert len(result.branches) == 2
        assert result.branches[0] == [(p, False), (q, True)]
        assert result.branches[1] == [(p, True), (q, False)]


class TestNotExpansionRule:
    """Tests for NOT (double negation) expansion rule."""
    
    def test_expand_double_negation(self):
        """Test expanding double negation: ¬¬φ → φ."""
        # GIVEN a NOT formula (¬φ)
        p = Predicate("P", (Constant("a"),))
        formula = UnaryFormula(LogicOperator.NOT, p)
        context = ExpansionContext(formula=formula, negated=False)
        
        # WHEN expanding it
        rule = NotExpansionRule()
        result = rule.expand(context)
        
        # THEN should flip negation
        assert result.is_branching == False
        assert len(result.branches) == 1
        assert len(result.branches[0]) == 1
        assert result.branches[0][0] == (p, True)  # negated=True (opposite of context.negated)


class TestExpansionRuleRegistry:
    """Tests for expansion rule registry functions."""
    
    def test_get_all_expansion_rules(self):
        """Test getting all expansion rules."""
        # GIVEN the rule registry
        # WHEN getting all rules
        rules = get_all_expansion_rules()
        
        # THEN should return 5 rules
        assert len(rules) == 5
        assert any(isinstance(r, AndExpansionRule) for r in rules)
        assert any(isinstance(r, OrExpansionRule) for r in rules)
        assert any(isinstance(r, ImpliesExpansionRule) for r in rules)
        assert any(isinstance(r, IffExpansionRule) for r in rules)
        assert any(isinstance(r, NotExpansionRule) for r in rules)
    
    def test_select_expansion_rule_for_and(self):
        """Test selecting expansion rule for AND formula."""
        # GIVEN an AND formula
        p = Predicate("P", (Constant("a"),))
        q = Predicate("Q", (Constant("b"),))
        formula = BinaryFormula(LogicOperator.AND, p, q)
        
        # WHEN selecting a rule
        rule = select_expansion_rule(formula, negated=False)
        
        # THEN should select AND rule
        assert rule is not None
        assert isinstance(rule, AndExpansionRule)
    
    def test_select_expansion_rule_for_or(self):
        """Test selecting expansion rule for OR formula."""
        # GIVEN an OR formula
        p = Predicate("P", (Constant("a"),))
        q = Predicate("Q", (Constant("b"),))
        formula = BinaryFormula(LogicOperator.OR, p, q)
        
        # WHEN selecting a rule
        rule = select_expansion_rule(formula, negated=False)
        
        # THEN should select OR rule
        assert rule is not None
        assert isinstance(rule, OrExpansionRule)
    
    def test_select_expansion_rule_for_atomic(self):
        """Test selecting expansion rule for atomic formula (no rule)."""
        # GIVEN an atomic formula (no expansion needed)
        formula = Predicate("P", (Constant("a"),))
        
        # WHEN selecting a rule
        rule = select_expansion_rule(formula, negated=False)
        
        # THEN should return None (no expansion)
        assert rule is None
