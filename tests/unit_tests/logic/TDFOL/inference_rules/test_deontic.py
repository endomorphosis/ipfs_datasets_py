"""
Comprehensive tests for TDFOL Deontic Logic Inference Rules.
"""

import pytest
from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
    Predicate, BinaryFormula, UnaryFormula, DeonticFormula,
    LogicOperator, DeonticOperator,
)
from ipfs_datasets_py.logic.TDFOL.inference_rules.deontic import (
    DeonticKAxiomRule, DeonticDAxiomRule, ProhibitionEquivalenceRule,
    PermissionNegationRule, ObligationConsistencyRule,
    PermissionIntroductionRule, DeonticNecessitationRule,
    ProhibitionFromObligationRule, PermissionProhibitionDualityRule,
    ObligationPermissionImplicationRule,
)


class TestDeonticRules:
    """Tests for deontic logic rules"""
    
    def test_deontic_k_axiom(self):
        """Test K axiom: O(φ → ψ), O(φ) ⊢ O(ψ)"""
        p, q = Predicate('P', []), Predicate('Q', [])
        p_implies_q = BinaryFormula(LogicOperator.IMPLIES, p, q)
        o_impl = DeonticFormula(DeonticOperator.OBLIGATION, p_implies_q)
        o_p = DeonticFormula(DeonticOperator.OBLIGATION, p)
        rule = DeonticKAxiomRule()
        
        assert rule.can_apply(o_impl, o_p) is True
        result = rule.apply(o_impl, o_p)
        assert isinstance(result, DeonticFormula)
        assert result.operator == DeonticOperator.OBLIGATION
        assert result.formula == q
    
    def test_deontic_d_axiom(self):
        """Test D axiom: O(φ) ⊢ P(φ)"""
        p = Predicate('P', [])
        o_p = DeonticFormula(DeonticOperator.OBLIGATION, p)
        rule = DeonticDAxiomRule()
        
        assert rule.can_apply(o_p) is True
        result = rule.apply(o_p)
        assert isinstance(result, DeonticFormula)
        assert result.operator == DeonticOperator.PERMISSION
    
    def test_prohibition_equivalence(self):
        """Test F(φ) ⊢ O(¬φ)"""
        p = Predicate('P', [])
        f_p = DeonticFormula(DeonticOperator.PROHIBITION, p)
        rule = ProhibitionEquivalenceRule()
        
        assert rule.can_apply(f_p) is True
        result = rule.apply(f_p)
        assert isinstance(result, DeonticFormula)
        assert result.operator == DeonticOperator.OBLIGATION
    
    def test_permission_introduction(self):
        """Test φ ⊢ P(φ)"""
        p = Predicate('P', [])
        rule = PermissionIntroductionRule()
        
        assert rule.can_apply(p) is True
        result = rule.apply(p)
        assert isinstance(result, DeonticFormula)
        assert result.operator == DeonticOperator.PERMISSION
    
    def test_permission_negation(self):
        """Test P(φ) ⊢ ¬O(¬φ)"""
        p = Predicate('P', [])
        p_p = DeonticFormula(DeonticOperator.PERMISSION, p)
        rule = PermissionNegationRule()
        
        assert rule.can_apply(p_p) is True
        result = rule.apply(p_p)
        assert isinstance(result, UnaryFormula)
        assert result.operator == LogicOperator.NOT
    
    def test_obligation_consistency(self):
        """Test O(φ) ⊢ ¬O(¬φ)"""
        p = Predicate('P', [])
        o_p = DeonticFormula(DeonticOperator.OBLIGATION, p)
        rule = ObligationConsistencyRule()
        
        assert rule.can_apply(o_p) is True
        result = rule.apply(o_p)
        assert isinstance(result, UnaryFormula)
        assert result.operator == LogicOperator.NOT
    
    def test_deontic_necessitation(self):
        """Test φ ⊢ O(φ)"""
        p = Predicate('P', [])
        rule = DeonticNecessitationRule()
        
        assert rule.can_apply(p) is True
        result = rule.apply(p)
        assert isinstance(result, DeonticFormula)
        assert result.operator == DeonticOperator.OBLIGATION
    
    def test_prohibition_from_obligation(self):
        """Test O(¬φ) ⊢ F(φ)"""
        p = Predicate('P', [])
        not_p = UnaryFormula(LogicOperator.NOT, p)
        o_not_p = DeonticFormula(DeonticOperator.OBLIGATION, not_p)
        rule = ProhibitionFromObligationRule()
        
        assert rule.can_apply(o_not_p) is True
        result = rule.apply(o_not_p)
        assert isinstance(result, DeonticFormula)
        assert result.operator == DeonticOperator.PROHIBITION
    
    def test_permission_prohibition_duality(self):
        """Test P(φ) ⊢ ¬F(φ)"""
        p = Predicate('P', [])
        p_p = DeonticFormula(DeonticOperator.PERMISSION, p)
        rule = PermissionProhibitionDualityRule()
        
        assert rule.can_apply(p_p) is True
        result = rule.apply(p_p)
        assert isinstance(result, UnaryFormula)
        assert result.operator == LogicOperator.NOT
    
    def test_obligation_permission_implication(self):
        """Test O(φ) → P(φ)"""
        p = Predicate('P', [])
        o_p = DeonticFormula(DeonticOperator.OBLIGATION, p)
        rule = ObligationPermissionImplicationRule()
        
        assert rule.can_apply(o_p) is True
        result = rule.apply(o_p)
        assert isinstance(result, DeonticFormula)
        assert result.operator == DeonticOperator.PERMISSION


class TestInvalidInputs:
    """Test invalid inputs"""
    
    def test_k_axiom_wrong_count(self):
        p = Predicate('P', [])
        o_p = DeonticFormula(DeonticOperator.OBLIGATION, p)
        assert DeonticKAxiomRule().can_apply(o_p) is False
    
    def test_d_axiom_wrong_operator(self):
        p = Predicate('P', [])
        p_p = DeonticFormula(DeonticOperator.PERMISSION, p)
        assert DeonticDAxiomRule().can_apply(p_p) is False
    
    def test_prohibition_equiv_wrong_operator(self):
        p = Predicate('P', [])
        o_p = DeonticFormula(DeonticOperator.OBLIGATION, p)
        assert ProhibitionEquivalenceRule().can_apply(o_p) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
