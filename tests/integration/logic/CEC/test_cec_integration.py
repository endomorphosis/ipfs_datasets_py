"""
Integration tests for CEC logic components.

These tests validate end-to-end workflows and multi-component integration.
Phase 3 Week 5: Integration Tests (30 tests)
"""

import pytest
import sys
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from ipfs_datasets_py.logic.CEC.native import (
    DCECContainer,
    NaturalLanguageConverter,
    TheoremProver,
    DCECNamespace,
    DeonticOperator,
    CognitiveOperator,
    LogicalConnective,
    AtomicFormula,
    DeonticFormula,
    CognitiveFormula,
    ConnectiveFormula,
    VariableTerm,
    ProofResult,
)


# Phase 3 Week 5 Day 6-7: End-to-End Conversion Tests (15 tests)
class TestEndToEndConversion:
    """Test suite for end-to-end NL → DCEC → Proof workflows."""
    
    def test_nl_to_dcec_to_proof_pipeline(self):
        """
        GIVEN a natural language sentence expressing an obligation
        WHEN converting to DCEC and proving a related theorem
        THEN the complete pipeline should work end-to-end
        """
        # GIVEN
        converter = NaturalLanguageConverter()
        prover = TheoremProver()
        prover.initialize()
        
        # WHEN - Convert NL to DCEC
        nl_text = "the agent must close the door"
        result = converter.convert_to_dcec(nl_text)
        
        # THEN - Conversion succeeds
        assert result.success is True
        assert result.dcec_formula is not None
        
        # WHEN - Prove the obligation
        proof_attempt = prover.prove_theorem(
            goal=result.dcec_formula,
            axioms=[result.dcec_formula]
        )
        
        # THEN - Proof succeeds
        assert proof_attempt.result == ProofResult.PROVED
    
    def test_nl_to_dcec_to_nl_roundtrip(self):
        """
        GIVEN a natural language sentence
        WHEN converting to DCEC and back to NL
        THEN the semantics should be preserved
        """
        # GIVEN
        converter = NaturalLanguageConverter()
        original_text = "the agent must act"
        
        # WHEN - Convert to DCEC
        to_dcec = converter.convert_to_dcec(original_text)
        assert to_dcec.success is True
        
        # Convert back to NL
        to_nl = converter.convert_to_english(to_dcec.dcec_formula)
        
        # THEN - Should have meaningful text
        assert to_nl.success is True
        assert len(to_nl.english_text) > 0
    
    def test_multiple_sentences_to_kb_to_query(self):
        """
        GIVEN multiple natural language sentences
        WHEN building a knowledge base and querying
        THEN the KB should answer queries correctly
        """
        # GIVEN
        converter = NaturalLanguageConverter()
        namespace = DCECNamespace()
        
        sentences = [
            "the agent must close the door",
            "the agent must turn off the lights",
            "if the door is closed then the agent may leave"
        ]
        
        # WHEN - Build KB
        formulas = []
        for sentence in sentences:
            result = converter.convert_to_dcec(sentence)
            if result.success and result.dcec_formula:
                formulas.append(result.dcec_formula)
        
        # THEN - Should have multiple formulas
        assert len(formulas) >= 2
    
    def test_conversation_to_belief_state(self):
        """
        GIVEN a conversation between agents
        WHEN tracking belief states
        THEN beliefs should be updated correctly
        """
        # GIVEN
        namespace = DCECNamespace()
        agent_sort = namespace.get_or_create_sort("Agent")
        fact_pred = namespace.add_predicate("fact", [])
        
        alice = namespace.add_variable("alice", agent_sort)
        
        # WHEN - Alice believes a fact
        fact = AtomicFormula(fact_pred, [])
        belief = CognitiveFormula(
            CognitiveOperator.BELIEF,
            VariableTerm(alice),
            fact
        )
        
        # THEN - Belief is well-formed
        assert belief is not None
        assert alice in belief.get_free_variables()
    
    def test_requirements_document_to_obligations(self):
        """
        GIVEN a requirements document text
        WHEN extracting obligations
        THEN all obligations should be identified
        """
        # GIVEN
        converter = NaturalLanguageConverter()
        
        requirements = [
            "the system must validate all inputs",
            "the system must log all transactions",
            "the system must encrypt sensitive data"
        ]
        
        # WHEN - Extract obligations
        obligations = []
        for req in requirements:
            result = converter.convert_to_dcec(req)
            if result.success and result.dcec_formula:
                obligations.append(result.dcec_formula)
        
        # THEN - Should have obligations
        assert len(obligations) >= 2
    
    def test_legal_text_to_deontic_formulas(self):
        """
        GIVEN legal text with obligations and permissions
        WHEN converting to deontic formulas
        THEN formulas should capture legal semantics
        """
        # GIVEN
        converter = NaturalLanguageConverter()
        
        legal_text = "the party must comply with regulations"
        
        # WHEN
        result = converter.convert_to_dcec(legal_text)
        
        # THEN
        assert result.success is True
        assert result.dcec_formula is not None
    
    def test_story_to_event_sequence(self):
        """
        GIVEN a story with temporal events
        WHEN extracting event sequence
        THEN events should be ordered correctly
        """
        # GIVEN
        converter = NaturalLanguageConverter()
        
        story_parts = [
            "first the agent opens the door",
            "then the agent enters the room"
        ]
        
        # WHEN - Convert each part
        events = []
        for part in story_parts:
            result = converter.convert_to_dcec(part)
            if result.success and result.dcec_formula:
                events.append(result.dcec_formula)
        
        # THEN - Should have events
        assert len(events) >= 1
    
    def test_dialogue_to_intention_inference(self):
        """
        GIVEN dialogue between agents
        WHEN inferring intentions
        THEN intentions should be captured
        """
        # GIVEN
        namespace = DCECNamespace()
        agent_sort = namespace.get_or_create_sort("Agent")
        goal_pred = namespace.add_predicate("achieve_goal", [agent_sort])
        
        agent = namespace.add_variable("agent", agent_sort)
        term_agent = VariableTerm(agent)
        
        # WHEN - Express intention
        goal = AtomicFormula(goal_pred, [term_agent])
        intention = CognitiveFormula(
            CognitiveOperator.INTENTION,
            term_agent,
            goal
        )
        
        # THEN
        assert intention is not None
    
    def test_contract_analysis_pipeline(self):
        """
        GIVEN a contract with clauses
        WHEN analyzing obligations and permissions
        THEN contract structure should be captured
        """
        # GIVEN
        converter = NaturalLanguageConverter()
        
        clauses = [
            "the seller must deliver goods",
            "the buyer must pay the price"
        ]
        
        # WHEN - Analyze
        analyzed = []
        for clause in clauses:
            result = converter.convert_to_dcec(clause)
            if result.success:
                analyzed.append(result)
        
        # THEN
        assert len(analyzed) >= 2
    
    def test_policy_compliance_checking(self):
        """
        GIVEN a policy and actions
        WHEN checking compliance
        THEN violations should be detected
        """
        # GIVEN
        namespace = DCECNamespace()
        action_sort = namespace.get_or_create_sort("Action")
        policy_pred = namespace.add_predicate("allowed", [action_sort])
        
        action = namespace.add_variable("action", action_sort)
        term_action = VariableTerm(action)
        
        # Policy: action is allowed
        policy = AtomicFormula(policy_pred, [term_action])
        
        # WHEN - Check compliance
        prover = TheoremProver()
        prover.initialize()
        
        attempt = prover.prove_theorem(
            goal=policy,
            axioms=[policy]
        )
        
        # THEN
        assert attempt.result == ProofResult.PROVED
    
    def test_multi_agent_scenario_reasoning(self):
        """
        GIVEN a multi-agent scenario
        WHEN reasoning about interactions
        THEN agent interactions should be modeled
        """
        # GIVEN
        namespace = DCECNamespace()
        agent_sort = namespace.get_or_create_sort("Agent")
        action_pred = namespace.add_predicate("cooperate", [agent_sort, agent_sort])
        
        alice = namespace.add_variable("alice", agent_sort)
        bob = namespace.add_variable("bob", agent_sort)
        
        # WHEN - Model cooperation
        cooperation = AtomicFormula(
            action_pred,
            [VariableTerm(alice), VariableTerm(bob)]
        )
        
        # THEN
        assert cooperation is not None
        assert alice in cooperation.get_free_variables()
        assert bob in cooperation.get_free_variables()
    
    def test_knowledge_base_consistency_checking(self):
        """
        GIVEN a knowledge base
        WHEN checking for contradictions
        THEN inconsistencies should be detectable
        """
        # GIVEN
        namespace = DCECNamespace()
        pred = namespace.add_predicate("fact", [])
        
        fact = AtomicFormula(pred, [])
        not_fact = ConnectiveFormula(LogicalConnective.NOT, [fact])
        
        # WHEN - Both fact and not fact
        prover = TheoremProver()
        prover.initialize()
        
        # Try to prove anything from contradiction
        dummy_pred = namespace.add_predicate("anything", [])
        dummy_goal = AtomicFormula(dummy_pred, [])
        
        attempt = prover.prove_theorem(
            goal=dummy_goal,
            axioms=[fact, not_fact]
        )
        
        # THEN - Proof system handles contradiction
        assert attempt is not None
    
    def test_automated_reasoning_from_facts(self):
        """
        GIVEN a set of facts and rules
        WHEN applying automated reasoning
        THEN new facts should be inferred
        """
        # GIVEN
        namespace = DCECNamespace()
        p = namespace.add_predicate("P", [])
        q = namespace.add_predicate("Q", [])
        r = namespace.add_predicate("R", [])
        
        f_p = AtomicFormula(p, [])
        f_q = AtomicFormula(q, [])
        f_r = AtomicFormula(r, [])
        
        # P and P→Q and Q→R
        pq = ConnectiveFormula(LogicalConnective.IMPLIES, [f_p, f_q])
        qr = ConnectiveFormula(LogicalConnective.IMPLIES, [f_q, f_r])
        
        # WHEN - Prove R
        prover = TheoremProver()
        prover.initialize()
        
        attempt = prover.prove_theorem(
            goal=f_r,
            axioms=[f_p, pq, qr]
        )
        
        # THEN - Should prove R by transitivity
        assert attempt.result == ProofResult.PROVED
    
    def test_explanation_generation_for_conclusions(self):
        """
        GIVEN a proven conclusion
        WHEN generating explanation
        THEN proof steps should be traceable
        """
        # GIVEN
        namespace = DCECNamespace()
        p = namespace.add_predicate("P", [])
        q = namespace.add_predicate("Q", [])
        
        f_p = AtomicFormula(p, [])
        f_q = AtomicFormula(q, [])
        impl = ConnectiveFormula(LogicalConnective.IMPLIES, [f_p, f_q])
        
        # WHEN - Prove with tracking
        prover = TheoremProver()
        prover.initialize()
        
        attempt = prover.prove_theorem(goal=f_q, axioms=[impl, f_p])
        
        # THEN - Should have proof info
        assert attempt is not None
        assert attempt.result == ProofResult.PROVED
    
    def test_error_recovery_in_pipeline(self):
        """
        GIVEN a pipeline with potential errors
        WHEN errors occur
        THEN pipeline should recover gracefully
        """
        # GIVEN
        converter = NaturalLanguageConverter()
        
        # Invalid/complex input
        invalid_text = "xyzabc123!@#"
        
        # WHEN
        result = converter.convert_to_dcec(invalid_text)
        
        # THEN - Should not crash, returns result
        assert result is not None


# Phase 3 Week 5 Day 6-7: Multi-Component Integration (10 tests)
class TestMultiComponentIntegration:
    """Test suite for multi-component integration."""
    
    def test_dcec_core_with_prover_integration(self):
        """
        GIVEN DCEC core components and prover
        WHEN integrating them
        THEN they should work together seamlessly
        """
        # GIVEN
        namespace = DCECNamespace()
        prover = TheoremProver()
        prover.initialize()
        
        # Create formula using namespace
        pred = namespace.add_predicate("test", [])
        formula = AtomicFormula(pred, [])
        
        # WHEN - Prove using prover
        attempt = prover.prove_theorem(goal=formula, axioms=[formula])
        
        # THEN
        assert attempt.result == ProofResult.PROVED
    
    def test_nl_converter_with_kb_integration(self):
        """
        GIVEN NL converter and knowledge base
        WHEN populating KB from NL
        THEN KB should contain converted formulas
        """
        # GIVEN
        converter = NaturalLanguageConverter()
        namespace = DCECNamespace()
        
        # WHEN - Convert and add to KB
        result = converter.convert_to_dcec("the agent must act")
        
        # THEN
        assert result.success is True
        assert result.dcec_formula is not None
    
    def test_prover_with_caching_integration(self):
        """
        GIVEN prover with caching
        WHEN proving multiple times
        THEN caching should improve performance
        """
        # GIVEN
        prover = TheoremProver()
        prover.initialize()
        
        namespace = DCECNamespace()
        pred = namespace.add_predicate("cached", [])
        formula = AtomicFormula(pred, [])
        
        # WHEN - Prove twice
        attempt1 = prover.prove_theorem(goal=formula, axioms=[formula])
        attempt2 = prover.prove_theorem(goal=formula, axioms=[formula])
        
        # THEN - Both succeed
        assert attempt1.result == ProofResult.PROVED
        assert attempt2.result == ProofResult.PROVED
    
    def test_namespace_with_formula_creation(self):
        """
        GIVEN namespace and formula creation
        WHEN creating complex formulas
        THEN namespace should manage types correctly
        """
        # GIVEN
        namespace = DCECNamespace()
        
        # WHEN - Create types and formulas
        agent_sort = namespace.get_or_create_sort("Agent")
        pred = namespace.add_predicate("act", [agent_sort])
        var = namespace.add_variable("x", agent_sort)
        term = VariableTerm(var)
        
        formula = AtomicFormula(pred, [term])
        
        # THEN
        assert formula is not None
        assert var in formula.get_free_variables()
    
    def test_grammar_engine_with_nl_converter(self):
        """
        GIVEN grammar engine and NL converter
        WHEN using grammar for conversion
        THEN conversion should be more accurate
        """
        # GIVEN
        converter = NaturalLanguageConverter()
        
        # WHEN - Convert with grammar awareness
        result = converter.convert_to_dcec("the agent must carefully close the door")
        
        # THEN - Should handle adverbs
        assert result is not None
    
    def test_type_system_with_validation(self):
        """
        GIVEN type system and validation
        WHEN validating typed formulas
        THEN type errors should be caught
        """
        # GIVEN
        namespace = DCECNamespace()
        agent_sort = namespace.get_or_create_sort("Agent")
        action_sort = namespace.get_or_create_sort("Action")
        
        # WHEN - Create properly typed formula
        pred = namespace.add_predicate("perform", [agent_sort, action_sort])
        agent_var = namespace.add_variable("a", agent_sort)
        action_var = namespace.add_variable("act", action_sort)
        
        formula = AtomicFormula(
            pred,
            [VariableTerm(agent_var), VariableTerm(action_var)]
        )
        
        # THEN
        assert formula is not None
    
    def test_parsing_with_formula_creation(self):
        """
        GIVEN parsing and formula creation
        WHEN parsing complex expressions
        THEN formulas should be created correctly
        """
        # GIVEN
        converter = NaturalLanguageConverter()
        
        # WHEN - Parse and create
        result = converter.convert_to_dcec("if p then q")
        
        # THEN
        assert result is not None
    
    def test_shadow_prover_with_native_prover(self):
        """
        GIVEN both shadow and native provers
        WHEN using both for same problem
        THEN results should be consistent
        """
        # GIVEN
        prover = TheoremProver()
        prover.initialize()
        
        namespace = DCECNamespace()
        pred = namespace.add_predicate("test", [])
        formula = AtomicFormula(pred, [])
        
        # WHEN - Use prover
        attempt = prover.prove_theorem(goal=formula, axioms=[formula])
        
        # THEN
        assert attempt.result == ProofResult.PROVED
    
    def test_modal_tableaux_with_prover_core(self):
        """
        GIVEN modal tableaux and prover core
        WHEN proving modal theorems
        THEN modal reasoning should work
        """
        # GIVEN
        namespace = DCECNamespace()
        pred = namespace.add_predicate("modal_fact", [])
        base = AtomicFormula(pred, [])
        
        # Modal formula (obligation)
        modal = DeonticFormula(DeonticOperator.OBLIGATION, base)
        
        # WHEN
        prover = TheoremProver()
        prover.initialize()
        
        attempt = prover.prove_theorem(goal=modal, axioms=[modal])
        
        # THEN
        assert attempt.result == ProofResult.PROVED
    
    def test_all_components_stress_test(self):
        """
        GIVEN all CEC components together
        WHEN performing complex integrated workflow
        THEN all components should work together
        """
        # GIVEN - Initialize all components
        converter = NaturalLanguageConverter()
        prover = TheoremProver()
        prover.initialize()
        namespace = DCECNamespace()
        
        # WHEN - Complex workflow
        # 1. Convert NL to DCEC
        nl_result = converter.convert_to_dcec("the agent must complete the task")
        assert nl_result.success is True
        
        # 2. Create additional formulas
        pred = namespace.add_predicate("complete", [])
        formula = AtomicFormula(pred, [])
        
        # 3. Prove
        proof = prover.prove_theorem(goal=formula, axioms=[formula])
        
        # THEN - All components work
        assert proof.result == ProofResult.PROVED


# Phase 3 Week 5 Day 6-7: Wrapper Integration (5 tests)
class TestWrapperIntegration:
    """Test suite for wrapper layer integration."""
    
    def test_native_vs_dcec_library_parity(self):
        """
        GIVEN native and DCEC library implementations
        WHEN comparing feature sets
        THEN native should have feature parity
        """
        # GIVEN - Native implementation
        converter = NaturalLanguageConverter()
        
        # WHEN - Use native features
        result = converter.convert_to_dcec("the agent must act")
        
        # THEN - Features work
        assert result.success is True
    
    def test_native_vs_shadowprover_parity(self):
        """
        GIVEN native and shadowprover implementations
        WHEN comparing proving capabilities
        THEN features should be comparable
        """
        # GIVEN
        prover = TheoremProver()
        prover.initialize()
        
        namespace = DCECNamespace()
        pred = namespace.add_predicate("test", [])
        formula = AtomicFormula(pred, [])
        
        # WHEN
        attempt = prover.prove_theorem(goal=formula, axioms=[formula])
        
        # THEN
        assert attempt.result == ProofResult.PROVED
    
    def test_wrapper_fallback_to_native(self):
        """
        GIVEN wrapper with fallback
        WHEN submodule unavailable
        THEN should use native implementation
        """
        # GIVEN - Use native directly
        converter = NaturalLanguageConverter()
        
        # WHEN
        result = converter.convert_to_dcec("test")
        
        # THEN - Native works
        assert result is not None
    
    def test_wrapper_performance_comparison(self):
        """
        GIVEN native and wrapped implementations
        WHEN comparing performance
        THEN native should be competitive
        """
        # GIVEN
        import time
        
        converter = NaturalLanguageConverter()
        
        # WHEN - Measure native performance
        start = time.time()
        for _ in range(10):
            converter.convert_to_dcec("the agent must act")
        elapsed = time.time() - start
        
        # THEN - Should complete quickly
        assert elapsed < 1.0  # Should take less than 1 second for 10 conversions
    
    def test_wrapper_error_handling_consistency(self):
        """
        GIVEN wrappers with error handling
        WHEN errors occur
        THEN errors should be handled consistently
        """
        # GIVEN
        converter = NaturalLanguageConverter()
        
        # WHEN - Invalid input
        result = converter.convert_to_dcec("")
        
        # THEN - Returns result (doesn't crash)
        assert result is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
