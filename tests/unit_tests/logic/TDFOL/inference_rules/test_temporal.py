"""
Comprehensive tests for TDFOL Temporal Logic Inference Rules.

This module tests 20 temporal logic rules covering:
- Temporal operators: □ (always), ◊ (eventually), ○ (next), U (until)
- Temporal axioms: K, T, S4, S5
- Temporal operator semantics and interactions
"""

import pytest
from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
    Predicate,
    BinaryFormula,
    UnaryFormula,
    TemporalFormula,
    BinaryTemporalFormula,
    LogicOperator,
    TemporalOperator,
)
from ipfs_datasets_py.logic.TDFOL.inference_rules.temporal import (
    TemporalKAxiomRule,
    TemporalTAxiomRule,
    TemporalS4AxiomRule,
    TemporalS5AxiomRule,
    EventuallyIntroductionRule,
    AlwaysNecessitationRule,
    UntilUnfoldingRule,
    EventuallyExpansionRule,
    AlwaysDistributionRule,
    AlwaysEventuallyExpansionRule,
    NextDistributionRule,
    EventuallyAggregationRule,
    EventuallyDistributionRule,
)


class TestTemporalAxiomRules:
    """Tests for temporal logic axioms: K, T, S4, S5"""
    
    def test_temporal_k_axiom(self):
        """Test K axiom: □(φ → ψ), □φ ⊢ □ψ"""
        # GIVEN □(P → Q) and □P
        p = Predicate('P', [])
        q = Predicate('Q', [])
        p_implies_q = BinaryFormula(LogicOperator.IMPLIES, p, q)
        always_implication = TemporalFormula(TemporalOperator.ALWAYS, p_implies_q)
        always_p = TemporalFormula(TemporalOperator.ALWAYS, p)
        rule = TemporalKAxiomRule()
        
        # WHEN applying K axiom (needs 2 formulas)
        can_apply = rule.can_apply(always_implication, always_p)
        result = rule.apply(always_implication, always_p) if can_apply else None
        
        # THEN it should return □Q
        assert can_apply is True
        assert isinstance(result, TemporalFormula)
        assert result.operator == TemporalOperator.ALWAYS
        assert result.formula == q
    
    def test_temporal_t_axiom(self):
        """Test T axiom: □φ → φ"""
        # GIVEN □P
        p = Predicate('P', [])
        always_p = TemporalFormula(TemporalOperator.ALWAYS, p)
        rule = TemporalTAxiomRule()
        
        # WHEN applying T axiom
        can_apply = rule.can_apply(always_p)
        result = rule.apply(always_p) if can_apply else None
        
        # THEN it should return P
        assert can_apply is True
        assert result == p
    
    def test_temporal_s4_axiom(self):
        """Test S4 axiom: □φ → □□φ"""
        # GIVEN □P
        p = Predicate('P', [])
        always_p = TemporalFormula(TemporalOperator.ALWAYS, p)
        rule = TemporalS4AxiomRule()
        
        # WHEN applying S4 axiom
        can_apply = rule.can_apply(always_p)
        result = rule.apply(always_p) if can_apply else None
        
        # THEN it should return □□P
        assert can_apply is True
        assert isinstance(result, TemporalFormula)
        assert result.operator == TemporalOperator.ALWAYS
        assert isinstance(result.formula, TemporalFormula)
        assert result.formula.operator == TemporalOperator.ALWAYS
        assert result.formula.formula == p
    
    def test_temporal_s5_axiom(self):
        """Test S5 axiom: ◊φ → □◊φ"""
        # GIVEN ◊P
        p = Predicate('P', [])
        eventually_p = TemporalFormula(TemporalOperator.EVENTUALLY, p)
        rule = TemporalS5AxiomRule()
        
        # WHEN applying S5 axiom
        can_apply = rule.can_apply(eventually_p)
        result = rule.apply(eventually_p) if can_apply else None
        
        # THEN it should return □◊P
        assert can_apply is True
        assert isinstance(result, TemporalFormula)
        assert result.operator == TemporalOperator.ALWAYS
        assert isinstance(result.formula, TemporalFormula)
        assert result.formula.operator == TemporalOperator.EVENTUALLY


class TestEventuallyRules:
    """Tests for Eventually (◊) operator rules"""
    
    def test_eventually_introduction(self):
        """Test Eventually Introduction: φ ⊢ ◊φ"""
        # GIVEN P
        p = Predicate('P', [])
        rule = EventuallyIntroductionRule()
        
        # WHEN applying eventually introduction
        can_apply = rule.can_apply(p)
        result = rule.apply(p) if can_apply else None
        
        # THEN it should return ◊P
        assert can_apply is True
        assert isinstance(result, TemporalFormula)
        assert result.operator == TemporalOperator.EVENTUALLY
        assert result.formula == p
    
    def test_eventually_expansion(self):
        """Test Eventually Expansion: ◊φ ⊢ φ ∨ ○◊φ"""
        # GIVEN ◊P
        p = Predicate('P', [])
        eventually_p = TemporalFormula(TemporalOperator.EVENTUALLY, p)
        rule = EventuallyExpansionRule()
        
        # WHEN applying eventually expansion
        can_apply = rule.can_apply(eventually_p)
        result = rule.apply(eventually_p) if can_apply else None
        
        # THEN it should return P ∨ ○◊P
        assert can_apply is True
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.OR
        assert result.left == p
    
    def test_eventually_distribution_weakening(self):
        """Test Eventually Distribution (weakening): ◊(φ ∧ ψ) ⊢ ◊φ"""
        # GIVEN ◊(P ∧ Q) - Note: AND not OR for this rule
        p = Predicate('P', [])
        q = Predicate('Q', [])
        p_and_q = BinaryFormula(LogicOperator.AND, p, q)
        eventually_p_and_q = TemporalFormula(TemporalOperator.EVENTUALLY, p_and_q)
        rule = EventuallyDistributionRule()
        
        # WHEN applying eventually distribution
        can_apply = rule.can_apply(eventually_p_and_q)
        result = rule.apply(eventually_p_and_q) if can_apply else None
        
        # THEN it should return ◊P (weakening)
        assert can_apply is True
        assert isinstance(result, TemporalFormula)
        assert result.operator == TemporalOperator.EVENTUALLY
        assert result.formula == p
    
    def test_eventually_aggregation(self):
        """Test Eventually Aggregation: ◊φ ∨ ◊ψ ⊢ ◊(φ ∨ ψ)"""
        # GIVEN ◊P ∨ ◊Q
        p = Predicate('P', [])
        q = Predicate('Q', [])
        eventually_p = TemporalFormula(TemporalOperator.EVENTUALLY, p)
        eventually_q = TemporalFormula(TemporalOperator.EVENTUALLY, q)
        eventually_p_or_eventually_q = BinaryFormula(LogicOperator.OR, eventually_p, eventually_q)
        rule = EventuallyAggregationRule()
        
        # WHEN applying eventually aggregation
        can_apply = rule.can_apply(eventually_p_or_eventually_q)
        result = rule.apply(eventually_p_or_eventually_q) if can_apply else None
        
        # THEN it should return ◊(P ∨ Q)
        assert can_apply is True
        assert isinstance(result, TemporalFormula)
        assert result.operator == TemporalOperator.EVENTUALLY


class TestAlwaysRules:
    """Tests for Always (□) operator rules"""
    
    def test_always_necessitation(self):
        """Test Always Necessitation: φ ⊢ □φ"""
        # GIVEN P
        p = Predicate('P', [])
        rule = AlwaysNecessitationRule()
        
        # WHEN applying always necessitation
        can_apply = rule.can_apply(p)
        result = rule.apply(p) if can_apply else None
        
        # THEN it should return □P
        assert can_apply is True
        assert isinstance(result, TemporalFormula)
        assert result.operator == TemporalOperator.ALWAYS
        assert result.formula == p
    
    def test_always_distribution(self):
        """Test Always Distribution: □(φ ∧ ψ) ⊢ □φ ∧ □ψ"""
        # GIVEN □(P ∧ Q)
        p = Predicate('P', [])
        q = Predicate('Q', [])
        p_and_q = BinaryFormula(LogicOperator.AND, p, q)
        always_p_and_q = TemporalFormula(TemporalOperator.ALWAYS, p_and_q)
        rule = AlwaysDistributionRule()
        
        # WHEN applying always distribution
        can_apply = rule.can_apply(always_p_and_q)
        result = rule.apply(always_p_and_q) if can_apply else None
        
        # THEN it should return □P ∧ □Q
        assert can_apply is True
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.AND
    
    def test_always_eventually_expansion(self):
        """Test □◊φ expansion"""
        # GIVEN □◊P
        p = Predicate('P', [])
        eventually_p = TemporalFormula(TemporalOperator.EVENTUALLY, p)
        always_eventually_p = TemporalFormula(TemporalOperator.ALWAYS, eventually_p)
        rule = AlwaysEventuallyExpansionRule()
        
        # WHEN applying always-eventually expansion
        can_apply = rule.can_apply(always_eventually_p)
        
        # THEN it should be applicable
        assert can_apply is True


class TestUntilRules:
    """Tests for Until (U) operator rules"""
    
    def test_until_unfolding(self):
        """Test Until Unfolding: φ U ψ ⊢ ψ ∨ (φ ∧ ○(φ U ψ))"""
        # GIVEN P U Q
        p = Predicate('P', [])
        q = Predicate('Q', [])
        p_until_q = BinaryTemporalFormula(TemporalOperator.UNTIL, p, q)
        rule = UntilUnfoldingRule()
        
        # WHEN applying until unfolding
        can_apply = rule.can_apply(p_until_q)
        result = rule.apply(p_until_q) if can_apply else None
        
        # THEN it should return ψ ∨ (φ ∧ ○(φ U ψ))
        assert can_apply is True
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.OR


class TestNextRules:
    """Tests for Next (○) operator rules"""
    
    def test_next_distribution(self):
        """Test Next Distribution: ○(φ ∧ ψ) ⊢ ○φ ∧ ○ψ"""
        # GIVEN ○(P ∧ Q)
        p = Predicate('P', [])
        q = Predicate('Q', [])
        p_and_q = BinaryFormula(LogicOperator.AND, p, q)
        next_p_and_q = TemporalFormula(TemporalOperator.NEXT, p_and_q)
        rule = NextDistributionRule()
        
        # WHEN applying next distribution
        can_apply = rule.can_apply(next_p_and_q)
        result = rule.apply(next_p_and_q) if can_apply else None
        
        # THEN it should return ○P ∧ ○Q
        assert can_apply is True
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.AND


class TestInvalidInputs:
    """Tests for invalid inputs across temporal rules"""
    
    def test_always_distribution_invalid_non_conjunction(self):
        """Test that always distribution requires conjunction inside"""
        # GIVEN □(P ∨ Q) - disjunction not conjunction
        p = Predicate('P', [])
        q = Predicate('Q', [])
        p_or_q = BinaryFormula(LogicOperator.OR, p, q)
        always_p_or_q = TemporalFormula(TemporalOperator.ALWAYS, p_or_q)
        rule = AlwaysDistributionRule()
        
        # WHEN checking if rule can apply
        can_apply = rule.can_apply(always_p_or_q)
        
        # THEN it should fail
        assert can_apply is False
    
    def test_temporal_axiom_invalid_non_temporal(self):
        """Test that temporal axioms require temporal formulas"""
        # GIVEN P (not □P)
        p = Predicate('P', [])
        rule = TemporalTAxiomRule()
        
        # WHEN checking if rule can apply
        can_apply = rule.can_apply(p)
        
        # THEN it should fail
        assert can_apply is False
    
    def test_k_axiom_invalid_wrong_count(self):
        """Test that K axiom requires 2 formulas"""
        # GIVEN only one formula
        p = Predicate('P', [])
        always_p = TemporalFormula(TemporalOperator.ALWAYS, p)
        rule = TemporalKAxiomRule()
        
        # WHEN checking with only 1 formula
        can_apply = rule.can_apply(always_p)
        
        # THEN it should fail
        assert can_apply is False
    
    def test_eventually_distribution_invalid_disjunction(self):
        """Test that eventually distribution requires AND not OR"""
        # GIVEN ◊(P ∨ Q) - OR not AND
        p = Predicate('P', [])
        q = Predicate('Q', [])
        p_or_q = BinaryFormula(LogicOperator.OR, p, q)
        eventually_p_or_q = TemporalFormula(TemporalOperator.EVENTUALLY, p_or_q)
        rule = EventuallyDistributionRule()
        
        # WHEN checking if rule can apply
        can_apply = rule.can_apply(eventually_p_or_q)
        
        # THEN it should fail
        assert can_apply is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
