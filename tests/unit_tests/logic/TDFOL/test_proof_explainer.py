"""
Tests for TDFOL Proof Explainer Module

This module tests the proof explanation system for TDFOL following GIVEN-WHEN-THEN format.
Tests cover standard proof explanations, ZKP explanations, and various formatting options.
"""

import pytest
from typing import List, Dict, Any

from ipfs_datasets_py.logic.TDFOL import (
    Predicate,
    Variable,
    create_implication,
    create_conjunction,
    create_negation,
    create_always,
    create_eventually,
    create_obligation,
    create_permission,
)
from ipfs_datasets_py.logic.TDFOL.proof_explainer import (
    ProofExplainer,
    ZKPProofExplainer,
    ProofType,
    ExplanationLevel,
    ProofStep,
    ProofExplanation,
    explain_proof,
    explain_zkp_proof,
)


# ============================================================================
# Standard Explanations (15 tests)
# ============================================================================


class TestStandardExplanations:
    """Test standard proof explanations."""
    
    def test_forward_chaining_explanation(self):
        """Test explaining a forward chaining proof."""
        # GIVEN a formula and forward chaining proof steps
        p = Predicate("P", ())
        q = Predicate("Q", ())
        formula = create_implication(p, q)
        
        proof_steps = [
            {"rule": "ModusPonens", "conclusion": q},
            {"rule": "Assumption", "conclusion": p}
        ]
        
        # WHEN explaining the proof
        explainer = ProofExplainer()
        explanation = explainer.explain_proof(
            formula, 
            proof_steps, 
            ProofType.FORWARD_CHAINING
        )
        
        # THEN explanation should be generated
        assert explanation.formula == formula
        assert explanation.is_proved is True
        assert explanation.proof_type == ProofType.FORWARD_CHAINING
        assert len(explanation.steps) == 2
        assert explanation.steps[0].rule_name == "ModusPonens"
        assert "forward chaining" in explanation.summary.lower()
    
    def test_backward_chaining_explanation(self):
        """Test explaining a backward chaining proof."""
        # GIVEN a formula and backward chaining steps
        p = Predicate("P", ())
        q = Predicate("Q", ())
        formula = create_implication(p, q)
        
        proof_steps = ["Goal: Q", "Subgoal: P", "Proved P"]
        
        # WHEN explaining the proof
        explainer = ProofExplainer()
        explanation = explainer.explain_proof(
            formula, 
            proof_steps, 
            ProofType.BACKWARD_CHAINING
        )
        
        # THEN explanation should show goal-directed reasoning
        assert explanation.proof_type == ProofType.BACKWARD_CHAINING
        assert len(explanation.steps) == 3
        assert "backward chaining" in explanation.summary.lower()
        assert "goal" in explanation.summary.lower()
    
    def test_modal_tableaux_explanation(self):
        """Test explaining a modal tableaux proof."""
        # GIVEN a formula and tableaux proof steps
        p = Predicate("P", ())
        formula = create_always(p)
        
        proof_steps = [
            "Branch 1: P",
            "Branch 2: Closed",
            "All branches closed"
        ]
        
        # WHEN explaining the proof
        explainer = ProofExplainer()
        explanation = explainer.explain_proof(
            formula, 
            proof_steps, 
            ProofType.MODAL_TABLEAUX
        )
        
        # THEN explanation should mention tableaux
        assert explanation.proof_type == ProofType.MODAL_TABLEAUX
        assert "tableaux" in explanation.summary.lower()
        assert len(explanation.steps) == 3
    
    def test_natural_language_conversion(self):
        """Test converting formal proof steps to natural language."""
        # GIVEN a proof step with a rule
        p = Predicate("P", ())
        q = Predicate("Q", ())
        step = ProofStep(
            step_number=1,
            action="Apply modus ponens",
            rule_name="ModusPonens",
            premises=[p, create_implication(p, q)],
            conclusion=q
        )
        
        # WHEN converting to natural language
        nl_text = step.to_natural_language()
        
        # THEN it should be human-readable
        assert "Step 1" in nl_text
        assert "ModusPonens" in nl_text
        assert "derive" in nl_text.lower() or "applied" in nl_text.lower()
    
    def test_inference_rule_naming(self):
        """Test explaining inference rules by name."""
        # GIVEN an explainer and a rule name
        explainer = ProofExplainer()
        rule_name = "ModusPonens"
        
        # WHEN explaining the rule
        explanation = explainer._explain_rule_application(rule_name)
        
        # THEN explanation should describe the rule
        assert explanation is not None
        assert len(explanation) > 0
        assert "→" in explanation or "->" in explanation
    
    def test_step_by_step_breakdown(self):
        """Test generating step-by-step proof breakdown."""
        # GIVEN a multi-step proof
        p = Predicate("P", ())
        q = Predicate("Q", ())
        r = Predicate("R", ())
        formula = create_implication(p, r)
        
        proof_steps = [
            {"rule": "HypotheticalSyllogism", "conclusion": create_implication(p, r)},
            {"rule": "Assumption", "conclusion": create_implication(p, q)},
            {"rule": "Assumption", "conclusion": create_implication(q, r)}
        ]
        
        # WHEN explaining with detailed level
        explainer = ProofExplainer(level=ExplanationLevel.DETAILED)
        explanation = explainer.explain_proof(
            formula,
            proof_steps,
            ProofType.FORWARD_CHAINING
        )
        
        # THEN all steps should be detailed
        assert len(explanation.steps) == 3
        assert explanation.steps[0].rule_name == "HypotheticalSyllogism"
        assert len(explanation.inference_chain) > 0
    
    def test_proof_summary_generation(self):
        """Test generating high-level proof summaries."""
        # GIVEN a successful proof
        p = Predicate("P", ())
        formula = p
        proof_steps = [{"rule": "Assumption", "conclusion": p}]
        
        explainer = ProofExplainer()
        
        # WHEN generating explanation
        explanation = explainer.explain_proof(
            formula,
            proof_steps,
            ProofType.FORWARD_CHAINING,
            is_proved=True
        )
        
        # THEN summary should be informative
        assert len(explanation.summary) > 0
        assert "proved" in explanation.summary.lower()
        assert str(len(proof_steps)) in explanation.summary
    
    def test_failed_proof_explanation(self):
        """Test explaining a failed proof attempt."""
        # GIVEN a formula that could not be proved
        p = Predicate("P", ())
        formula = p
        proof_steps = []
        
        # WHEN explaining the failed proof
        explainer = ProofExplainer()
        explanation = explainer.explain_proof(
            formula,
            proof_steps,
            ProofType.FORWARD_CHAINING,
            is_proved=False
        )
        
        # THEN explanation should indicate failure
        assert explanation.is_proved is False
        assert "failed" in explanation.summary.lower()
    
    def test_temporal_rule_explanation(self):
        """Test explaining temporal logic rules."""
        # GIVEN an explainer with temporal rules
        explainer = ProofExplainer()
        
        # WHEN explaining temporal rules
        always_dist = explainer._explain_rule_application("AlwaysDistribution")
        eventually_agg = explainer._explain_rule_application("EventuallyAggregation")
        
        # THEN explanations should mention temporal concepts
        assert "□" in always_dist or "Always" in always_dist
        assert "◊" in eventually_agg or "Eventually" in eventually_agg
    
    def test_deontic_rule_explanation(self):
        """Test explaining deontic logic rules."""
        # GIVEN an explainer with deontic rules
        explainer = ProofExplainer()
        
        # WHEN explaining deontic rules
        obligation_weak = explainer._explain_rule_application("ObligationWeakening")
        deontic_detach = explainer._explain_rule_application("DeonticDetachment")
        
        # THEN explanations should mention obligations
        assert "obligation" in obligation_weak.lower() or "O(" in obligation_weak
        assert "O(" in deontic_detach or "obligation" in deontic_detach.lower()
    
    def test_reasoning_chain_extraction(self):
        """Test extracting chain of reasoning from proof."""
        # GIVEN proof steps with various rules
        steps = [
            ProofStep(1, "Apply rule 1", rule_name="ModusPonens"),
            ProofStep(2, "Apply rule 2", rule_name="ModusTollens"),
            ProofStep(3, "Conclusion reached")
        ]
        
        explainer = ProofExplainer()
        
        # WHEN extracting reasoning chain
        chain = explainer._extract_reasoning_chain(steps)
        
        # THEN chain should show logical progression
        assert len(chain) == 3
        assert "ModusPonens" in chain[0]
        assert "ModusTollens" in chain[1]
    
    def test_proof_statistics_computation(self):
        """Test computing statistics about proofs."""
        # GIVEN proof steps
        steps = [
            ProofStep(1, "Step 1", rule_name="ModusPonens"),
            ProofStep(2, "Step 2", rule_name="ModusTollens"),
            ProofStep(3, "Step 3", rule_name="ModusPonens"),
            ProofStep(4, "Conclusion")
        ]
        
        explainer = ProofExplainer()
        
        # WHEN computing statistics
        stats = explainer._compute_statistics(steps)
        
        # THEN statistics should be accurate
        assert stats["total_steps"] == 4
        assert stats["rules_used"] == 3
        assert stats["unique_rules"] == 2  # ModusPonens and ModusTollens
    
    def test_inference_rule_detailed_explanation(self):
        """Test detailed explanation of single inference rule."""
        # GIVEN an explainer and rule application
        explainer = ProofExplainer(level=ExplanationLevel.DETAILED)
        p = Predicate("P", ())
        q = Predicate("Q", ())
        
        # WHEN explaining inference rule
        explanation = explainer.explain_inference_rule(
            "ModusPonens",
            [p, create_implication(p, q)],
            q
        )
        
        # THEN explanation should be detailed
        assert "ModusPonens" in explanation
        assert "Premises" in explanation
        assert "Conclusion" in explanation
    
    def test_generic_rule_explanation(self):
        """Test explaining rules not in predefined list."""
        # GIVEN an explainer and unknown rule
        explainer = ProofExplainer()
        
        # WHEN explaining unknown rules
        weakening = explainer._explain_rule_application("CustomWeakening")
        distribution = explainer._explain_rule_application("CustomDistribution")
        
        # THEN generic explanations should be provided
        assert "weaken" in weakening.lower()
        assert "distribution" in distribution.lower() or "distribute" in distribution.lower()
    
    def test_complex_proof_explanation(self):
        """Test explaining a complex multi-step proof."""
        # GIVEN a complex formula with multiple operators
        p = Predicate("P", ())
        q = Predicate("Q", ())
        r = Predicate("R", ())
        
        # (P → Q) ∧ (Q → R) ⊢ (P → R)
        formula = create_implication(p, r)
        
        proof_steps = [
            {"rule": "Assumption", "conclusion": create_implication(p, q)},
            {"rule": "Assumption", "conclusion": create_implication(q, r)},
            {"rule": "HypotheticalSyllogism", "conclusion": formula}
        ]
        
        # WHEN explaining the proof
        explainer = ProofExplainer(level=ExplanationLevel.DETAILED)
        explanation = explainer.explain_proof(
            formula,
            proof_steps,
            ProofType.FORWARD_CHAINING
        )
        
        # THEN explanation should be comprehensive
        assert len(explanation.steps) == 3
        assert "HypotheticalSyllogism" in str(explanation)
        assert explanation.statistics["total_steps"] == 3


# ============================================================================
# ZKP Explanations (10 tests)
# ============================================================================


class TestZKPExplanations:
    """Test zero-knowledge proof explanations."""
    
    def test_zkp_proof_explanation(self):
        """Test explaining a ZKP proof."""
        # GIVEN a formula and ZKP result
        p = Predicate("P", ())
        formula = p
        zkp_result = {"verified": True}
        
        # WHEN explaining ZKP proof
        explainer = ZKPProofExplainer()
        explanation = explainer.explain_zkp_proof(
            formula,
            zkp_result,
            backend="simulated"
        )
        
        # THEN explanation should mention ZKP
        assert explanation.proof_type == ProofType.ZKP
        assert "zero-knowledge" in explanation.summary.lower()
        assert "private" in explanation.summary.lower() or "hidden" in explanation.summary.lower()
    
    def test_zkp_private_axiom_handling(self):
        """Test ZKP explanation mentions private axioms."""
        # GIVEN a ZKP proof with private axioms
        p = Predicate("Secret", ())
        formula = p
        zkp_result = {"verified": True}
        
        explainer = ZKPProofExplainer()
        
        # WHEN explaining the proof
        explanation = explainer.explain_zkp_proof(formula, zkp_result)
        
        # THEN explanation should mention privacy
        inference_chain_text = " ".join(explanation.inference_chain)
        assert "private" in inference_chain_text.lower() or "hidden" in inference_chain_text.lower()
        assert "axioms" in explanation.summary.lower() or "axiom" in inference_chain_text.lower()
    
    def test_zkp_verification_explanation(self):
        """Test ZKP verification step explanation."""
        # GIVEN a verified ZKP
        p = Predicate("P", ())
        zkp_result = {"verified": True}
        
        explainer = ZKPProofExplainer()
        
        # WHEN explaining verification
        explanation = explainer.explain_zkp_proof(p, zkp_result)
        
        # THEN verification should be mentioned
        step_texts = [step.action for step in explanation.steps]
        assert any("verif" in text.lower() for text in step_texts)
    
    def test_zkp_backend_explanation(self):
        """Test explaining different ZKP backends."""
        # GIVEN different backends
        p = Predicate("P", ())
        zkp_result = {"verified": True}
        
        explainer = ZKPProofExplainer()
        
        # WHEN explaining with different backends
        simulated = explainer.explain_zkp_proof(p, zkp_result, backend="simulated")
        groth16 = explainer.explain_zkp_proof(p, zkp_result, backend="groth16")
        
        # THEN backend should be mentioned in statistics
        assert simulated.statistics["backend"] == "simulated"
        assert groth16.statistics["backend"] == "groth16"
    
    def test_zkp_security_properties_explanation(self):
        """Test explaining ZKP security properties."""
        # GIVEN a ZKP explainer
        explainer = ZKPProofExplainer()
        
        # WHEN explaining security properties
        security_text = explainer.explain_security_properties("groth16", 128)
        
        # THEN key properties should be mentioned
        assert "completeness" in security_text.lower()
        assert "soundness" in security_text.lower()
        assert "zero-knowledge" in security_text.lower()
        assert "128" in security_text
    
    def test_zkp_simulated_backend_warning(self):
        """Test warning for simulated backend."""
        # GIVEN simulated backend
        explainer = ZKPProofExplainer()
        
        # WHEN explaining security properties
        security_text = explainer.explain_security_properties("simulated", 128)
        
        # THEN warning should be present
        assert "warning" in security_text.lower() or "⚠" in security_text
        assert "not cryptographically secure" in security_text.lower()
    
    def test_zkp_vs_standard_comparison(self):
        """Test comparing ZKP vs standard proofs."""
        # GIVEN a ZKP explainer
        explainer = ZKPProofExplainer()
        
        # WHEN generating comparison
        comparison = explainer.explain_zkp_vs_standard()
        
        # THEN comparison should mention both approaches
        assert "standard" in comparison.lower()
        assert "zkp" in comparison.lower() or "zero-knowledge" in comparison.lower()
        assert "transparent" in comparison.lower()
        assert "private" in comparison.lower()
    
    def test_zkp_proof_size_explanation(self):
        """Test ZKP explanation includes proof size."""
        # GIVEN a ZKP proof
        p = Predicate("P", ())
        zkp_result = {"verified": True}
        
        explainer = ZKPProofExplainer()
        
        # WHEN explaining the proof
        explanation = explainer.explain_zkp_proof(p, zkp_result)
        
        # THEN proof size should be mentioned
        assert "proof_size" in explanation.statistics
        assert "bytes" in explanation.statistics["proof_size"].lower()
    
    def test_zkp_verification_time_explanation(self):
        """Test ZKP explanation includes verification time."""
        # GIVEN a ZKP proof
        p = Predicate("P", ())
        zkp_result = {"verified": True}
        
        explainer = ZKPProofExplainer()
        
        # WHEN explaining the proof
        explanation = explainer.explain_zkp_proof(p, zkp_result, backend="groth16")
        
        # THEN verification time should be mentioned
        assert "verification_time" in explanation.statistics
        assert "ms" in explanation.statistics["verification_time"].lower()
    
    def test_zkp_reasoning_chain(self):
        """Test ZKP proof has clear reasoning chain."""
        # GIVEN a ZKP proof
        p = Predicate("P", ())
        zkp_result = {"verified": True}
        
        explainer = ZKPProofExplainer()
        
        # WHEN explaining the proof
        explanation = explainer.explain_zkp_proof(p, zkp_result)
        
        # THEN reasoning chain should describe ZKP process
        assert len(explanation.inference_chain) > 0
        chain_text = " ".join(explanation.inference_chain).lower()
        assert "axiom" in chain_text or "private" in chain_text
        assert "proof" in chain_text
        assert "verif" in chain_text


# ============================================================================
# Formatting (5 tests)
# ============================================================================


class TestFormatting:
    """Test proof explanation formatting."""
    
    def test_brief_explanation_level(self):
        """Test brief explanation format."""
        # GIVEN an explainer with brief level
        explainer = ProofExplainer(level=ExplanationLevel.BRIEF)
        p = Predicate("P", ())
        q = Predicate("Q", ())
        
        # WHEN explaining an inference rule
        explanation = explainer.explain_inference_rule(
            "ModusPonens",
            [p, create_implication(p, q)],
            q
        )
        
        # THEN explanation should be concise
        assert len(explanation.split('\n')) == 1  # Single line
        assert "ModusPonens" in explanation
    
    def test_normal_explanation_level(self):
        """Test normal explanation format."""
        # GIVEN an explainer with normal level
        explainer = ProofExplainer(level=ExplanationLevel.NORMAL)
        p = Predicate("P", ())
        q = Predicate("Q", ())
        
        # WHEN explaining an inference rule
        explanation = explainer.explain_inference_rule(
            "ModusPonens",
            [p, create_implication(p, q)],
            q
        )
        
        # THEN explanation should be standard length
        assert len(explanation) > 0
        assert "ModusPonens" in explanation
    
    def test_detailed_explanation_level(self):
        """Test detailed explanation format."""
        # GIVEN an explainer with detailed level
        explainer = ProofExplainer(level=ExplanationLevel.DETAILED)
        p = Predicate("P", ())
        q = Predicate("Q", ())
        
        # WHEN explaining an inference rule
        explanation = explainer.explain_inference_rule(
            "ModusPonens",
            [p, create_implication(p, q)],
            q
        )
        
        # THEN explanation should be verbose
        assert "Inference Rule" in explanation
        assert "Premises" in explanation
        assert "Conclusion" in explanation
        assert "Explanation" in explanation
    
    def test_proof_explanation_string_format(self):
        """Test string representation of proof explanation."""
        # GIVEN a proof explanation
        p = Predicate("P", ())
        explanation = ProofExplanation(
            formula=p,
            is_proved=True,
            proof_type=ProofType.FORWARD_CHAINING
        )
        explanation.summary = "Simple proof"
        explanation.steps = [
            ProofStep(1, "Step 1", rule_name="Assumption")
        ]
        
        # WHEN converting to string
        text = str(explanation)
        
        # THEN format should be clear
        assert "Proof of:" in text
        assert "Result:" in text
        assert "Method:" in text
        assert "Summary:" in text
        assert "Proof Steps" in text
    
    def test_proof_comparison_format(self):
        """Test format of proof comparison."""
        # GIVEN standard and ZKP explanations
        p = Predicate("P", ())
        
        standard = ProofExplanation(
            formula=p,
            is_proved=True,
            proof_type=ProofType.FORWARD_CHAINING
        )
        standard.steps = [ProofStep(1, "Step 1", rule_name="Assumption")]
        standard.statistics = {"rules_used": 1}
        
        zkp = ProofExplanation(
            formula=p,
            is_proved=True,
            proof_type=ProofType.ZKP
        )
        
        explainer = ProofExplainer()
        
        # WHEN comparing proofs
        comparison = explainer.compare_proofs(standard, zkp)
        
        # THEN comparison should be formatted
        assert "Standard Proof" in comparison
        assert "ZKP Proof" in comparison
        assert "Trade-offs" in comparison
        assert "Recommendation" in comparison


# ============================================================================
# Convenience Functions (5 additional tests)
# ============================================================================


class TestConvenienceFunctions:
    """Test convenience functions for proof explanation."""
    
    def test_explain_proof_convenience_function(self):
        """Test explain_proof convenience function."""
        # GIVEN a formula and proof steps
        p = Predicate("P", ())
        proof_steps = [{"rule": "Assumption", "conclusion": p}]
        
        # WHEN using convenience function
        explanation = explain_proof(p, proof_steps)
        
        # THEN explanation should be generated
        assert explanation.formula == p
        assert explanation.proof_type == ProofType.FORWARD_CHAINING
        assert len(explanation.steps) > 0
    
    def test_explain_zkp_proof_convenience_function(self):
        """Test explain_zkp_proof convenience function."""
        # GIVEN a formula and ZKP result
        p = Predicate("P", ())
        zkp_result = {"verified": True}
        
        # WHEN using convenience function
        explanation = explain_zkp_proof(p, zkp_result)
        
        # THEN ZKP explanation should be generated
        assert explanation.formula == p
        assert explanation.proof_type == ProofType.ZKP
        assert "zero-knowledge" in explanation.summary.lower()
    
    def test_convenience_function_with_level(self):
        """Test convenience function with custom explanation level."""
        # GIVEN a formula and proof steps
        p = Predicate("P", ())
        proof_steps = [{"rule": "Assumption", "conclusion": p}]
        
        # WHEN using convenience function with detailed level
        explanation = explain_proof(
            p,
            proof_steps,
            level=ExplanationLevel.DETAILED
        )
        
        # THEN detailed explanation should be generated
        assert explanation is not None
        assert len(explanation.steps) > 0
    
    def test_convenience_function_with_proof_type(self):
        """Test convenience function with different proof type."""
        # GIVEN a formula and proof steps
        p = Predicate("P", ())
        proof_steps = ["Branch 1", "Branch 2"]
        
        # WHEN using convenience function with tableaux type
        explanation = explain_proof(
            p,
            proof_steps,
            proof_type=ProofType.MODAL_TABLEAUX
        )
        
        # THEN tableaux explanation should be generated
        assert explanation.proof_type == ProofType.MODAL_TABLEAUX
        assert "tableaux" in explanation.summary.lower()
    
    def test_zkp_convenience_function_with_backend(self):
        """Test ZKP convenience function with custom backend."""
        # GIVEN a formula and ZKP result
        p = Predicate("P", ())
        zkp_result = {"verified": True}
        
        # WHEN using convenience function with groth16 backend
        explanation = explain_zkp_proof(
            p,
            zkp_result,
            backend="groth16",
            security_level=256
        )
        
        # THEN explanation should reflect backend choice
        assert explanation.statistics["backend"] == "groth16"
        assert "256" in explanation.statistics["security_level"]


# ============================================================================
# Edge Cases and Error Handling (5 additional tests)
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_empty_proof_steps(self):
        """Test handling empty proof steps."""
        # GIVEN a formula with no proof steps
        p = Predicate("P", ())
        proof_steps = []
        
        # WHEN explaining the proof
        explainer = ProofExplainer()
        explanation = explainer.explain_proof(
            p,
            proof_steps,
            ProofType.FORWARD_CHAINING
        )
        
        # THEN explanation should handle empty steps
        assert len(explanation.steps) == 0
        assert explanation.statistics["total_steps"] == 0
    
    def test_none_rule_name(self):
        """Test handling steps with no rule name."""
        # GIVEN proof steps without rule names
        proof_steps = [
            {"conclusion": Predicate("P", ())},
            {"conclusion": Predicate("Q", ())}
        ]
        
        explainer = ProofExplainer()
        
        # WHEN explaining the proof
        explanation = explainer._explain_forward_chaining(proof_steps)
        
        # THEN steps should be created without errors
        assert len(explanation) == 2
    
    def test_string_proof_steps(self):
        """Test handling string-based proof steps."""
        # GIVEN string-only proof steps
        proof_steps = ["Step 1", "Step 2", "Step 3"]
        
        explainer = ProofExplainer()
        
        # WHEN explaining forward chaining
        explanation = explainer._explain_forward_chaining(proof_steps)
        
        # THEN steps should be processed
        assert len(explanation) == 3
        assert all(step.action for step in explanation)
    
    def test_unknown_proof_type(self):
        """Test handling unknown proof types."""
        # GIVEN a proof with hybrid type
        p = Predicate("P", ())
        proof_steps = [{"rule": "Custom", "conclusion": p}]
        
        explainer = ProofExplainer()
        
        # WHEN explaining with hybrid type
        explanation = explainer.explain_proof(
            p,
            proof_steps,
            ProofType.HYBRID
        )
        
        # THEN explanation should still be generated
        assert explanation.proof_type == ProofType.HYBRID
        assert len(explanation.summary) > 0
    
    def test_explanation_with_complex_formula(self):
        """Test explanation with complex nested formula."""
        # GIVEN a complex formula with multiple operators
        p = Predicate("P", ())
        q = Predicate("Q", ())
        r = Predicate("R", ())
        
        # O(□(P ∧ Q)) → ◊R
        formula = create_implication(
            create_obligation(create_always(create_conjunction(p, q))),
            create_eventually(r)
        )
        
        proof_steps = [{"rule": "Complex", "conclusion": formula}]
        
        # WHEN explaining the proof
        explainer = ProofExplainer()
        explanation = explainer.explain_proof(
            formula,
            proof_steps,
            ProofType.FORWARD_CHAINING
        )
        
        # THEN explanation should handle complexity
        assert explanation.formula == formula
        assert len(explanation.steps) > 0
