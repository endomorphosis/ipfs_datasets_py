"""
Comprehensive tests for TDFOL First-Order Logic Inference Rules.

This module tests the 2 first-order quantifier rules with comprehensive
coverage of:
- Variable substitution
- Term replacement
- Quantifier scope
- Free variable constraints
- Edge cases and invalid inputs
"""

import pytest
from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
    Predicate,
    Variable,
    Constant,
    QuantifiedFormula,
    Quantifier,
)
from ipfs_datasets_py.logic.TDFOL.inference_rules.first_order import (
    UniversalInstantiationRule,
    ExistentialGeneralizationRule,
)


class TestUniversalInstantiationRule:
    """Tests for Universal Instantiation: ∀x.φ(x) ⊢ φ(t)"""
    
    def test_universal_instantiation_basic(self):
        """Test basic universal instantiation with default constant."""
        # GIVEN ∀x.P(x)
        x = Variable('x')
        p_x = Predicate('P', [x])
        forall_x_px = QuantifiedFormula(Quantifier.FORALL, x, p_x)
        rule = UniversalInstantiationRule()
        
        # WHEN applying universal instantiation
        can_apply = rule.can_apply(forall_x_px)
        result = rule.apply(forall_x_px) if can_apply else None
        
        # THEN it should succeed and return P(c) with constant c
        assert can_apply is True
        assert result is not None
        assert isinstance(result, Predicate)
        assert result.name == 'P'
        assert len(result.arguments) == 1
        assert isinstance(result.arguments[0], Constant)
        assert result.arguments[0].name == 'x'  # Default uses variable name
    
    def test_universal_instantiation_with_specific_constant(self):
        """Test universal instantiation with specific constant."""
        # GIVEN ∀x.P(x) and constant 'a'
        x = Variable('x')
        p_x = Predicate('P', [x])
        forall_x_px = QuantifiedFormula(Quantifier.FORALL, x, p_x)
        a = Constant('a')
        rule = UniversalInstantiationRule()
        
        # WHEN applying universal instantiation with constant a
        can_apply = rule.can_apply(forall_x_px, a)
        result = rule.apply(forall_x_px, a) if can_apply else None
        
        # THEN it should return P(a)
        assert can_apply is True
        assert result is not None
        assert isinstance(result, Predicate)
        assert result.name == 'P'
        assert len(result.arguments) == 1
        assert isinstance(result.arguments[0], Constant)
        assert result.arguments[0].name == 'a'
    
    def test_universal_instantiation_with_different_variable(self):
        """Test universal instantiation with variable y."""
        # GIVEN ∀y.Q(y)
        y = Variable('y')
        q_y = Predicate('Q', [y])
        forall_y_qy = QuantifiedFormula(Quantifier.FORALL, y, q_y)
        rule = UniversalInstantiationRule()
        
        # WHEN applying universal instantiation
        can_apply = rule.can_apply(forall_y_qy)
        result = rule.apply(forall_y_qy) if can_apply else None
        
        # THEN it should succeed
        assert can_apply is True
        assert result is not None
        assert isinstance(result, Predicate)
        assert result.name == 'Q'
    
    def test_universal_instantiation_invalid_existential(self):
        """Test that universal instantiation doesn't apply to existential."""
        # GIVEN ∃x.P(x) (not ∀x.P(x))
        x = Variable('x')
        p_x = Predicate('P', [x])
        exists_x_px = QuantifiedFormula(Quantifier.EXISTS, x, p_x)
        rule = UniversalInstantiationRule()
        
        # WHEN checking if rule can apply
        can_apply = rule.can_apply(exists_x_px)
        
        # THEN it should fail
        assert can_apply is False
    
    def test_universal_instantiation_invalid_no_quantifier(self):
        """Test that universal instantiation requires quantified formula."""
        # GIVEN P(x) without quantifier
        x = Variable('x')
        p_x = Predicate('P', [x])
        rule = UniversalInstantiationRule()
        
        # WHEN checking if rule can apply
        can_apply = rule.can_apply(p_x)
        
        # THEN it should fail
        assert can_apply is False
    
    def test_universal_instantiation_multiple_occurrences(self):
        """Test universal instantiation with multiple variable occurrences."""
        # GIVEN ∀x.R(x, x) - variable appears twice
        x = Variable('x')
        r_xx = Predicate('R', [x, x])
        forall_x_rxx = QuantifiedFormula(Quantifier.FORALL, x, r_xx)
        b = Constant('b')
        rule = UniversalInstantiationRule()
        
        # WHEN applying with constant b
        can_apply = rule.can_apply(forall_x_rxx, b)
        result = rule.apply(forall_x_rxx, b) if can_apply else None
        
        # THEN both occurrences should be replaced with b
        assert can_apply is True
        assert result is not None
        assert isinstance(result, Predicate)
        assert result.name == 'R'
        assert len(result.arguments) == 2
        assert all(isinstance(arg, Constant) for arg in result.arguments)
        assert all(arg.name == 'b' for arg in result.arguments)


class TestExistentialGeneralizationRule:
    """Tests for Existential Generalization: φ(t) ⊢ ∃x.φ(x)"""
    
    def test_existential_generalization_basic(self):
        """Test basic existential generalization."""
        # GIVEN P(a) where a is a constant
        a = Constant('a')
        p_a = Predicate('P', [a])
        rule = ExistentialGeneralizationRule()
        
        # WHEN applying existential generalization
        can_apply = rule.can_apply(p_a)
        result = rule.apply(p_a) if can_apply else None
        
        # THEN it should return ∃x.P(x)
        assert can_apply is True
        assert result is not None
        assert isinstance(result, QuantifiedFormula)
        assert result.quantifier == Quantifier.EXISTS
        assert isinstance(result.variable, Variable)
        assert result.variable.name == 'x'  # Default variable name
    
    def test_existential_generalization_with_specific_variable(self):
        """Test existential generalization with specific variable."""
        # GIVEN Q(b) and variable y
        b = Constant('b')
        q_b = Predicate('Q', [b])
        y = Variable('y')
        rule = ExistentialGeneralizationRule()
        
        # WHEN applying with specific variable y
        can_apply = rule.can_apply(q_b, y)
        result = rule.apply(q_b, y) if can_apply else None
        
        # THEN it should return ∃y.Q(b)
        assert can_apply is True
        assert result is not None
        assert isinstance(result, QuantifiedFormula)
        assert result.quantifier == Quantifier.EXISTS
        assert result.variable.name == 'y'
    
    def test_existential_generalization_predicate_with_multiple_args(self):
        """Test existential generalization on predicate with multiple arguments."""
        # GIVEN R(a, b, c)
        a = Constant('a')
        b = Constant('b')
        c = Constant('c')
        r_abc = Predicate('R', [a, b, c])
        rule = ExistentialGeneralizationRule()
        
        # WHEN applying existential generalization
        can_apply = rule.can_apply(r_abc)
        result = rule.apply(r_abc) if can_apply else None
        
        # THEN it should succeed
        assert can_apply is True
        assert result is not None
        assert isinstance(result, QuantifiedFormula)
        assert result.quantifier == Quantifier.EXISTS
    
    def test_existential_generalization_from_variable(self):
        """Test existential generalization from formula with variable."""
        # GIVEN P(x) where x is already a variable
        x = Variable('x')
        p_x = Predicate('P', [x])
        z = Variable('z')
        rule = ExistentialGeneralizationRule()
        
        # WHEN applying existential generalization with variable z
        can_apply = rule.can_apply(p_x, z)
        result = rule.apply(p_x, z) if can_apply else None
        
        # THEN it should return ∃z.P(x)
        assert can_apply is True
        assert result is not None
        assert isinstance(result, QuantifiedFormula)
        assert result.quantifier == Quantifier.EXISTS
        assert result.variable.name == 'z'
    
    def test_existential_generalization_always_succeeds(self):
        """Test that existential generalization can apply to any formula."""
        # GIVEN various formulas
        formulas = [
            Predicate('P', [Constant('a')]),
            Predicate('Q', [Variable('x')]),
            Predicate('R', [Constant('b'), Variable('y')]),
        ]
        rule = ExistentialGeneralizationRule()
        
        # WHEN checking if rule can apply
        # THEN it should always succeed
        for formula in formulas:
            assert rule.can_apply(formula) is True
    
    def test_existential_generalization_preserves_formula_structure(self):
        """Test that existential generalization preserves internal structure."""
        # GIVEN S(a, b)
        a = Constant('a')
        b = Constant('b')
        s_ab = Predicate('S', [a, b])
        rule = ExistentialGeneralizationRule()
        
        # WHEN applying existential generalization
        result = rule.apply(s_ab)
        
        # THEN the inner formula should be preserved
        assert result.formula == s_ab
        assert result.formula.name == 'S'
        assert len(result.formula.arguments) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
