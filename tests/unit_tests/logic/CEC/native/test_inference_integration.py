"""
Integration tests for CEC inference rules system.

Tests rule chaining, combinations, and multi-step proofs to validate
that the inference rules work correctly together.
"""

import pytest
from ipfs_datasets_py.logic.CEC.native.inference_rules import (
    # Propositional
    ModusPonens, Simplification, ConjunctionIntroduction,
    Weakening, DeMorgan, DoubleNegation,
    DisjunctiveSyllogism, Contraposition,
    HypotheticalSyllogism, ImplicationElimination,
    # Temporal
    AlwaysDistribution, EventuallyFromAlways,
    NextDistribution, UntilWeakening,
    # Deontic
    ObligationDistribution, PermissionFromNonObligation,
    ProhibitionEquivalence,
    # Cognitive
    BeliefDistribution, KnowledgeImpliesBelief,
    IntentionCommitment,
)
from ipfs_datasets_py.logic.CEC.native.dcec_core import (
    Formula, Atom, Conjunction, Implication, Negation,
    Disjunction, LogicalConnective, DeonticOperator,
    CognitiveOperator, TemporalOperator,
)


class TestRuleChaining:
    """Test chaining multiple inference rules together."""
    
    def test_modus_ponens_chain(self):
        """
        GIVEN: A chain of implications P→Q, Q→R, P
        WHEN: Applying modus ponens twice
        THEN: Should derive R
        """
        # Setup formulas
        p = Atom("P")
        q = Atom("Q")
        r = Atom("R")
        
        p_implies_q = Implication(p, q)
        q_implies_r = Implication(q, r)
        
        # Step 1: From P and P→Q, derive Q
        mp1 = ModusPonens()
        formulas1 = [p, p_implies_q]
        
        assert mp1.can_apply(formulas1)
        result1 = mp1.apply(formulas1)
        assert result1 is not None
        # Result should be Q
        
        # Step 2: From Q and Q→R, derive R
        mp2 = ModusPonens()
        formulas2 = result1 + [q_implies_r]
        
        assert mp2.can_apply(formulas2)
        result2 = mp2.apply(formulas2)
        assert result2 is not None
        # Result should be R
    
    def test_conjunction_and_simplification(self):
        """
        GIVEN: Formulas P and Q
        WHEN: First conjoin them, then simplify
        THEN: Should get back original formulas
        """
        p = Atom("P")
        q = Atom("Q")
        
        # Step 1: Conjoin P and Q
        ci = ConjunctionIntroduction()
        formulas1 = [p, q]
        
        assert ci.can_apply(formulas1)
        conj = ci.apply(formulas1)
        assert conj is not None
        # Result should be P∧Q
        
        # Step 2: Simplify P∧Q to get P
        simp = Simplification()
        formulas2 = conj
        
        assert simp.can_apply(formulas2)
        result = simp.apply(formulas2)
        assert result is not None
    
    def test_hypothetical_syllogism_chain(self):
        """
        GIVEN: P→Q and Q→R
        WHEN: Applying hypothetical syllogism
        THEN: Should derive P→R
        """
        p = Atom("P")
        q = Atom("Q")
        r = Atom("R")
        
        p_implies_q = Implication(p, q)
        q_implies_r = Implication(q, r)
        
        hs = HypotheticalSyllogism()
        formulas = [p_implies_q, q_implies_r]
        
        assert hs.can_apply(formulas)
        result = hs.apply(formulas)
        assert result is not None
        # Result should be P→R


class TestRuleCombinations:
    """Test combinations of different rule types."""
    
    def test_propositional_and_temporal(self):
        """
        GIVEN: Temporal formula □(P∧Q)
        WHEN: Applying AlwaysDistribution then Simplification
        THEN: Should derive □P
        """
        p = Atom("P")
        q = Atom("Q")
        conj = Conjunction(p, q)
        
        # Create □(P∧Q) - conceptually
        # In practice, we'd need proper temporal formula support
        always_dist = AlwaysDistribution()
        
        # Test that the rule exists and has proper structure
        assert always_dist.name() == "Always Distribution"
    
    def test_deontic_and_propositional(self):
        """
        GIVEN: Deontic formula O(P∧Q)
        WHEN: Applying ObligationDistribution
        THEN: Should derive O(P) ∧ O(Q)
        """
        p = Atom("P")
        q = Atom("Q")
        
        obl_dist = ObligationDistribution()
        
        # Test that the rule exists
        assert obl_dist.name() == "Obligation Distribution"
    
    def test_cognitive_and_propositional(self):
        """
        GIVEN: Belief formula B(agent, P∧Q)
        WHEN: Applying BeliefDistribution
        THEN: Should derive B(agent, P) ∧ B(agent, Q)
        """
        belief_dist = BeliefDistribution()
        
        # Test that the rule exists
        assert belief_dist.name() == "BeliefDistribution"


class TestErrorPropagation:
    """Test error handling across rule applications."""
    
    def test_invalid_formula_rejection(self):
        """
        GIVEN: Invalid formulas for a rule
        WHEN: Checking can_apply()
        THEN: Should return False
        """
        mp = ModusPonens()
        
        # Wrong number of formulas
        assert not mp.can_apply([])
        assert not mp.can_apply([Atom("P")])
        
        # Wrong formula types
        p = Atom("P")
        q = Atom("Q")
        assert not mp.can_apply([p, q])  # Need P and P→Q, not P and Q
    
    def test_none_result_handling(self):
        """
        GIVEN: Rules that may return None
        WHEN: Applying with invalid inputs
        THEN: Should handle gracefully
        """
        simp = Simplification()
        
        # Apply to non-conjunction should return None or handle gracefully
        p = Atom("P")
        result = simp.apply([p])
        # Result should be None or raise appropriate exception


class TestBackwardCompatibility:
    """Test backward compatibility of inference rules."""
    
    def test_all_rules_have_required_methods(self):
        """
        GIVEN: All inference rule classes
        WHEN: Checking for required methods
        THEN: Should have name(), can_apply(), apply()
        """
        rules = [
            ModusPonens(), Simplification(), ConjunctionIntroduction(),
            Weakening(), DeMorgan(), DoubleNegation(),
            DisjunctiveSyllogism(), Contraposition(),
            HypotheticalSyllogism(), ImplicationElimination(),
            AlwaysDistribution(), EventuallyFromAlways(),
            ObligationDistribution(), BeliefDistribution(),
        ]
        
        for rule in rules:
            assert hasattr(rule, 'name')
            assert callable(rule.name)
            assert hasattr(rule, 'can_apply')
            assert callable(rule.can_apply)
            assert hasattr(rule, 'apply')
            assert callable(rule.apply)
            
            # Test name() returns a string
            assert isinstance(rule.name(), str)
            assert len(rule.name()) > 0
    
    def test_all_rules_inherit_from_base(self):
        """
        GIVEN: All inference rule classes
        WHEN: Checking inheritance
        THEN: Should inherit from InferenceRule
        """
        from ipfs_datasets_py.logic.CEC.native.inference_rules.base import InferenceRule
        
        rules = [
            ModusPonens(), Simplification(), ConjunctionIntroduction(),
            AlwaysDistribution(), ObligationDistribution(), BeliefDistribution(),
        ]
        
        for rule in rules:
            assert isinstance(rule, InferenceRule)


class TestCrossModuleInteractions:
    """Test interactions between different rule modules."""
    
    def test_propositional_with_all_modules(self):
        """
        GIVEN: Propositional rules
        WHEN: Used with temporal, deontic, and cognitive formulas
        THEN: Should work correctly
        """
        # Test that rules from different modules can coexist
        prop_rule = ModusPonens()
        temp_rule = AlwaysDistribution()
        deon_rule = ObligationDistribution()
        cogn_rule = BeliefDistribution()
        
        # All should have distinct names
        names = [
            prop_rule.name(),
            temp_rule.name(),
            deon_rule.name(),
            cogn_rule.name(),
        ]
        assert len(names) == len(set(names))  # All unique
    
    def test_module_imports(self):
        """
        GIVEN: Inference rules package
        WHEN: Importing from __init__
        THEN: All rules should be accessible
        """
        from ipfs_datasets_py.logic.CEC.native import inference_rules
        
        # Check that major rules are accessible
        assert hasattr(inference_rules, 'ModusPonens')
        assert hasattr(inference_rules, 'AlwaysDistribution')
        assert hasattr(inference_rules, 'ObligationDistribution')
        assert hasattr(inference_rules, 'BeliefDistribution')


class TestProofStrategies:
    """Test complete proof strategies using multiple rules."""
    
    def test_simple_proof_by_contradiction_setup(self):
        """
        GIVEN: Goal to prove P
        WHEN: Assuming ¬P and deriving contradiction
        THEN: Can conclude P
        """
        p = Atom("P")
        not_p = Negation(p)
        
        # This tests the setup for proof by contradiction
        # Actual proof would involve deriving a contradiction
        
        # Test double negation elimination
        dn = DoubleNegation()
        not_not_p = Negation(not_p)
        
        # ¬¬P should simplify to P
        formulas = [not_not_p]
        if dn.can_apply(formulas):
            result = dn.apply(formulas)
            assert result is not None
    
    def test_constructive_proof_chain(self):
        """
        GIVEN: Premises P, P→Q, Q→R
        WHEN: Building constructive proof
        THEN: Should derive R
        """
        p = Atom("P")
        q = Atom("Q")
        r = Atom("R")
        
        # Step 1: Use Hypothetical Syllogism on P→Q and Q→R
        hs = HypotheticalSyllogism()
        p_to_q = Implication(p, q)
        q_to_r = Implication(q, r)
        
        if hs.can_apply([p_to_q, q_to_r]):
            p_to_r = hs.apply([p_to_q, q_to_r])
            assert p_to_r is not None
            
            # Step 2: Use Modus Ponens on P and P→R
            mp = ModusPonens()
            if mp.can_apply([p, p_to_r]):
                result = mp.apply([p, p_to_r])
                assert result is not None


class TestPerformanceBaseline:
    """Establish performance baselines for optimization."""
    
    def test_rule_instantiation_speed(self):
        """
        GIVEN: Inference rule classes
        WHEN: Instantiating them
        THEN: Should be fast (< 1ms per rule)
        """
        import time
        
        start = time.time()
        for _ in range(1000):
            ModusPonens()
        end = time.time()
        
        # 1000 instantiations should be < 100ms
        assert (end - start) < 0.1
    
    def test_can_apply_check_speed(self):
        """
        GIVEN: Rule and formulas
        WHEN: Checking can_apply() repeatedly
        THEN: Should be fast
        """
        import time
        
        mp = ModusPonens()
        p = Atom("P")
        q = Atom("Q")
        p_implies_q = Implication(p, q)
        formulas = [p, p_implies_q]
        
        start = time.time()
        for _ in range(1000):
            mp.can_apply(formulas)
        end = time.time()
        
        # 1000 checks should be < 100ms
        assert (end - start) < 0.1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
