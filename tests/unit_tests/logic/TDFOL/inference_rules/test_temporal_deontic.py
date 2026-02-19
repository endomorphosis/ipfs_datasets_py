"""Tests for Temporal-Deontic rules"""
import pytest
from ipfs_datasets_py.logic.TDFOL.tdfol_core import *
from ipfs_datasets_py.logic.TDFOL.inference_rules.temporal_deontic import *

class TestTemporalDeonticRules:
    def test_deontic_temporal_intro(self):
        p = Predicate('P', [])
        o_p = DeonticFormula(DeonticOperator.OBLIGATION, p)
        rule = DeonticTemporalIntroductionRule()
        assert rule.can_apply(o_p) is True
    
    def test_until_obligation(self):
        p, q = Predicate('P', []), Predicate('Q', [])
        p_until_q = BinaryTemporalFormula(TemporalOperator.UNTIL, p, q)
        o_until = DeonticFormula(DeonticOperator.OBLIGATION, p_until_q)
        rule = UntilObligationRule()
        assert rule.can_apply(o_until) is True
    
    def test_obligation_eventually(self):
        p = Predicate('P', [])
        eventually_p = TemporalFormula(TemporalOperator.EVENTUALLY, p)
        o_eventually_p = DeonticFormula(DeonticOperator.OBLIGATION, eventually_p)
        rule = ObligationEventuallyRule()
        assert rule.can_apply(o_eventually_p) is True
    
    def test_permission_temporal_weakening(self):
        p = Predicate('P', [])
        p_p = DeonticFormula(DeonticOperator.PERMISSION, p)
        rule = PermissionTemporalWeakeningRule()
        assert rule.can_apply(p_p) is True

class TestInvalidInputs:
    def test_deontic_temporal_invalid(self):
        p = Predicate('P', [])
        p_p = DeonticFormula(DeonticOperator.PERMISSION, p)
        rule = DeonticTemporalIntroductionRule()
        assert rule.can_apply(p_p) is False

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
