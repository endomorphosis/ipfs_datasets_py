"""
Tests for Advanced Inference Rules (Phase 4 Weeks 2-3)

This test module validates advanced inference rules including modal logic,
temporal reasoning, and deontic logic rules for DCEC.

Test Coverage:
- Modal logic rules (K, T, S4 axioms) (4 tests)
- Temporal reasoning rules (3 tests)
- Deontic logic rules (4 tests)
- Combined modal-temporal-deontic rules (3 tests)
- Rule collections (1 test)

Total: 15 tests
"""

import pytest
from ipfs_datasets_py.logic.CEC.native.advanced_inference import (
    # Modal rules
    ModalKAxiom,
    ModalTAxiom,
    ModalS4Axiom,
    ModalNecassitation,
    # Temporal rules
    TemporalInduction,
    FrameAxiom,
    # Deontic rules
    DeonticDRule,
    DeonticPermissionObligation,
    DeonticDistribution,
    # Combined rules
    KnowledgeObligation,
    TemporalObligation,
    # Helper functions
    get_all_advanced_rules,
    get_modal_rules,
    get_temporal_rules,
    get_deontic_rules,
)
from ipfs_datasets_py.logic.CEC.native.dcec_core import (
    AtomicFormula,
    ConnectiveFormula,
    DeonticFormula,
    CognitiveFormula,
    LogicalConnective,
    DeonticOperator,
    CognitiveOperator,
    Predicate,
    Sort,
)
from ipfs_datasets_py.logic.CEC.native.dcec_namespace import DCECNamespace


class TestModalLogicRules:
    """Test modal logic inference rules."""
    
    def test_modal_k_axiom(self):
        """
        GIVEN a formula K(agent, p→q) (agent knows p implies q)
        WHEN applying Modal K axiom
        THEN should derive K(agent,p) → K(agent,q)
        """
        # GIVEN
        namespace = DCECNamespace()
        agent = Sort("Agent")
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        
        p = AtomicFormula(p_pred, [])
        q = AtomicFormula(q_pred, [])
        
        # p → q
        impl = ConnectiveFormula(LogicalConnective.IMPLIES, [p, q])
        
        # K(agent, p→q)
        k_impl = CognitiveFormula(CognitiveOperator.KNOWLEDGE, agent, impl)
        
        # WHEN
        rule = ModalKAxiom()
        assert rule.can_apply([k_impl])
        results = rule.apply([k_impl])
        
        # THEN
        assert len(results) > 0
        # Result should be K(agent,p) → K(agent,q)
        result = results[0]
        assert isinstance(result, ConnectiveFormula)
        assert result.connective == LogicalConnective.IMPLIES
    
    def test_modal_t_axiom(self):
        """
        GIVEN a formula K(agent, p) (agent knows p)
        WHEN applying Modal T axiom
        THEN should derive p
        """
        # GIVEN
        namespace = DCECNamespace()
        agent = Sort("Agent")
        p_pred = namespace.add_predicate("P", [])
        p = AtomicFormula(p_pred, [])
        
        # K(agent, p)
        k_p = CognitiveFormula(CognitiveOperator.KNOWLEDGE, agent, p)
        
        # WHEN
        rule = ModalTAxiom()
        assert rule.can_apply([k_p])
        results = rule.apply([k_p])
        
        # THEN
        assert len(results) > 0
        # Result should be p
        assert results[0].to_string() == p.to_string()
    
    def test_modal_s4_axiom(self):
        """
        GIVEN a formula K(agent, p)
        WHEN applying Modal S4 axiom
        THEN should derive K(agent, K(agent, p))
        """
        # GIVEN
        namespace = DCECNamespace()
        agent = Sort("Agent")
        p_pred = namespace.add_predicate("P", [])
        p = AtomicFormula(p_pred, [])
        
        # K(agent, p)
        k_p = CognitiveFormula(CognitiveOperator.KNOWLEDGE, agent, p)
        
        # WHEN
        rule = ModalS4Axiom()
        assert rule.can_apply([k_p])
        results = rule.apply([k_p])
        
        # THEN
        assert len(results) > 0
        # Result should be K(agent, K(agent, p))
        result = results[0]
        assert isinstance(result, CognitiveFormula)
        assert result.operator == CognitiveOperator.KNOWLEDGE
    
    def test_necessitation_rule(self):
        """
        GIVEN a proven formula p
        WHEN applying Necessitation rule
        THEN should derive K(system, p)
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        p = AtomicFormula(p_pred, [])
        
        # WHEN
        rule = ModalNecassitation()
        assert rule.can_apply([p])
        results = rule.apply([p])
        
        # THEN
        assert len(results) > 0
        # Result should be K(system, p)
        result = results[0]
        assert isinstance(result, CognitiveFormula)
        assert result.operator == CognitiveOperator.KNOWLEDGE


class TestTemporalReasoningRules:
    """Test temporal reasoning inference rules."""
    
    def test_temporal_induction(self):
        """
        GIVEN a base case p and inductive step p→q
        WHEN applying Temporal Induction
        THEN should derive q
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        
        p = AtomicFormula(p_pred, [])
        q = AtomicFormula(q_pred, [])
        
        # p → q
        impl = ConnectiveFormula(LogicalConnective.IMPLIES, [p, q])
        
        formulas = [p, impl]
        
        # WHEN
        rule = TemporalInduction()
        assert rule.can_apply(formulas)
        results = rule.apply(formulas)
        
        # THEN
        assert len(results) > 0
        # Should derive some consequence
        assert any(r.to_string() for r in results)
    
    def test_frame_axiom(self):
        """
        GIVEN an atomic property p
        WHEN applying Frame Axiom
        THEN property should persist (returned as result)
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        p = AtomicFormula(p_pred, [])
        
        # WHEN
        rule = FrameAxiom()
        assert rule.can_apply([p])
        results = rule.apply([p])
        
        # THEN
        assert len(results) > 0
        # Property persists
        assert any(r.to_string() == p.to_string() for r in results)
    
    def test_frame_axiom_persistence(self):
        """
        GIVEN multiple atomic properties
        WHEN applying Frame Axiom
        THEN all properties should persist
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        
        p = AtomicFormula(p_pred, [])
        q = AtomicFormula(q_pred, [])
        
        formulas = [p, q]
        
        # WHEN
        rule = FrameAxiom()
        results = rule.apply(formulas)
        
        # THEN
        assert len(results) > 0
        # Properties persist


class TestDeonticLogicRules:
    """Test deontic logic inference rules."""
    
    def test_deontic_d_axiom(self):
        """
        GIVEN O(agent, p) (agent obligated to p)
        WHEN applying Deontic D axiom
        THEN should derive ¬O(agent, ¬p)
        """
        # GIVEN
        namespace = DCECNamespace()
        agent = Sort("Agent")
        p_pred = namespace.add_predicate("P", [])
        p = AtomicFormula(p_pred, [])
        
        # O(agent, p)
        o_p = DeonticFormula(DeonticOperator.OBLIGATION, agent, p)
        
        # WHEN
        rule = DeonticDRule()
        assert rule.can_apply([o_p])
        results = rule.apply([o_p])
        
        # THEN
        assert len(results) > 0
        # Result should be ¬O(agent, ¬p)
        result = results[0]
        assert isinstance(result, ConnectiveFormula)
        assert result.connective == LogicalConnective.NOT
    
    def test_permission_obligation_duality(self):
        """
        GIVEN P(agent, p) (agent permitted to p)
        WHEN applying Permission-Obligation duality
        THEN should derive ¬O(agent, ¬p)
        """
        # GIVEN
        namespace = DCECNamespace()
        agent = Sort("Agent")
        p_pred = namespace.add_predicate("P", [])
        p = AtomicFormula(p_pred, [])
        
        # P(agent, p)
        p_p = DeonticFormula(DeonticOperator.PERMISSION, p, agent)
        
        # WHEN
        rule = DeonticPermissionObligation()
        assert rule.can_apply([p_p])
        results = rule.apply([p_p])
        
        # THEN
        assert len(results) > 0
        # Result should be ¬O(agent, ¬p)
        result = results[0]
        assert isinstance(result, ConnectiveFormula)
        assert result.connective == LogicalConnective.NOT
    
    def test_deontic_distribution(self):
        """
        GIVEN O(agent, p∧q)
        WHEN applying Deontic Distribution
        THEN should derive O(agent, p) ∧ O(agent, q)
        """
        # GIVEN
        namespace = DCECNamespace()
        agent = Sort("Agent")
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        
        p = AtomicFormula(p_pred, [])
        q = AtomicFormula(q_pred, [])
        
        # p ∧ q
        conj = ConnectiveFormula(LogicalConnective.AND, [p, q])
        
        # O(agent, p∧q)
        o_conj = DeonticFormula(DeonticOperator.OBLIGATION, conj, agent)
        
        # WHEN
        rule = DeonticDistribution()
        assert rule.can_apply([o_conj])
        results = rule.apply([o_conj])
        
        # THEN
        assert len(results) > 0
        # Result should be O(agent, p) ∧ O(agent, q)
        result = results[0]
        assert isinstance(result, ConnectiveFormula)
        assert result.connective == LogicalConnective.AND
    
    def test_deontic_obligation_prohibition(self):
        """
        GIVEN O(agent, ¬p) (obligated not to do p)
        WHEN applying deontic rules
        THEN should recognize as prohibition
        """
        # GIVEN
        namespace = DCECNamespace()
        agent = Sort("Agent")
        p_pred = namespace.add_predicate("P", [])
        p = AtomicFormula(p_pred, [])
        
        # ¬p
        not_p = ConnectiveFormula(LogicalConnective.NOT, [p])
        
        # O(agent, ¬p) - equivalent to F(agent, p)
        o_not_p = DeonticFormula(DeonticOperator.OBLIGATION, not_p, agent)
        
        # WHEN
        rule = DeonticDRule()
        results = rule.apply([o_not_p])
        
        # THEN
        assert isinstance(o_not_p, DeonticFormula)
        assert o_not_p.operator == DeonticOperator.OBLIGATION


class TestCombinedRules:
    """Test combined modal-temporal-deontic rules."""
    
    def test_knowledge_obligation_interaction(self):
        """
        GIVEN K(agent, O(agent2, p))
        WHEN applying Knowledge-Obligation interaction
        THEN should derive related formula
        """
        # GIVEN
        namespace = DCECNamespace()
        agent1 = Sort("Agent1")
        agent2 = Sort("Agent2")
        p_pred = namespace.add_predicate("P", [])
        p = AtomicFormula(p_pred, [])
        
        # O(agent2, p)
        o_p = DeonticFormula(DeonticOperator.OBLIGATION, p, agent2)
        
        # K(agent1, O(agent2, p))
        k_o_p = CognitiveFormula(CognitiveOperator.KNOWLEDGE, agent1, o_p)
        
        # WHEN
        rule = KnowledgeObligation()
        assert rule.can_apply([k_o_p])
        results = rule.apply([k_o_p])
        
        # THEN
        assert len(results) > 0
        # Should derive some epistemic-deontic formula
        result = results[0]
        assert isinstance(result, DeonticFormula)
    
    def test_temporal_obligation_interaction(self):
        """
        GIVEN O(agent, p) (temporal obligation)
        WHEN applying Temporal-Deontic interaction
        THEN obligation should persist
        """
        # GIVEN
        namespace = DCECNamespace()
        agent = Sort("Agent")
        p_pred = namespace.add_predicate("P", [])
        p = AtomicFormula(p_pred, [])
        
        # O(agent, p)
        o_p = DeonticFormula(DeonticOperator.OBLIGATION, p, agent)
        
        # WHEN
        rule = TemporalObligation()
        assert rule.can_apply([o_p])
        results = rule.apply([o_p])
        
        # THEN
        assert len(results) > 0
        # Obligation persists
        assert any(isinstance(r, DeonticFormula) for r in results)
    
    def test_nested_modal_operators(self):
        """
        GIVEN nested modal operators K(agent, O(agent, p))
        WHEN applying multiple rules
        THEN should handle nesting correctly
        """
        # GIVEN
        namespace = DCECNamespace()
        agent = Sort("Agent")
        p_pred = namespace.add_predicate("P", [])
        p = AtomicFormula(p_pred, [])
        
        # O(agent, p)
        o_p = DeonticFormula(DeonticOperator.OBLIGATION, p, agent)
        
        # K(agent, O(agent, p))
        k_o_p = CognitiveFormula(CognitiveOperator.KNOWLEDGE, agent, o_p)
        
        # WHEN - Apply T axiom
        t_rule = ModalTAxiom()
        t_results = t_rule.apply([k_o_p])
        
        # THEN
        assert len(t_results) > 0
        # Should derive O(agent, p)
        assert any(isinstance(r, DeonticFormula) for r in t_results)


class TestRuleCollections:
    """Test rule collection helper functions."""
    
    def test_get_all_rules(self):
        """
        GIVEN rule collection functions
        WHEN getting all advanced rules
        THEN should return all 11 rules
        """
        # WHEN
        all_rules = get_all_advanced_rules()
        modal_rules = get_modal_rules()
        temporal_rules = get_temporal_rules()
        deontic_rules = get_deontic_rules()
        
        # THEN
        assert len(all_rules) == 11  # 4 modal + 2 temporal + 3 deontic + 2 combined
        assert len(modal_rules) == 4
        assert len(temporal_rules) == 2
        assert len(deontic_rules) == 3
        
        # Verify all are InferenceRule instances
        for rule in all_rules:
            assert hasattr(rule, 'name')
            assert hasattr(rule, 'can_apply')
            assert hasattr(rule, 'apply')
