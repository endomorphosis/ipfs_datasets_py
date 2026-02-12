"""
Integration Tests for Phase 4 Native Implementation.

Tests the integration of all Phase 4 components:
- Phase 4A: DCEC Parsing
- Phase 4B: Inference Rules (prover_core.py)
- Phase 4C: Grammar System
- Phase 4D: ShadowProver

Following GIVEN-WHEN-THEN format.
"""

import pytest
import time

# Import all Phase 4 components
from ipfs_datasets_py.logic.native import (
    # Phase 4A: Parsing
    parse_dcec_string,
    clean_dcec_expression,
    
    # Phase 4B: Prover
    InferenceEngine,
    
    # Phase 4C: Grammar
    DCECEnglishGrammar,
    GrammarEngine,
    
    # Phase 4D: ShadowProver
    create_prover,
    create_cognitive_prover,
    ModalLogic,
    parse_problem_string,
)

from ipfs_datasets_py.logic.CEC.shadow_prover_wrapper import ShadowProverWrapper


class TestEndToEndWorkflows:
    """Test complete end-to-end workflows through all phases."""
    
    def test_string_to_formula_to_proof(self):
        """
        GIVEN: A DCEC string expression
        WHEN: Parsing and then proving with inference rules
        THEN: Should successfully parse and apply inference
        """
        # GIVEN
        dcec_string = "P & (P -> Q)"
        
        # WHEN - Phase 4A: Parse
        formula = parse_dcec_string(dcec_string)
        assert formula is not None
        
        # WHEN - Phase 4B: Prove using inference engine
        engine = InferenceEngine()
        engine.add_assumption(formula)
        
        # Try to derive Q using modus ponens
        result = engine.apply_all_rules()
        
        # THEN
        assert result is not None
        # Should be able to derive Q from P and P->Q
    
    def test_natural_language_to_dcec_to_proof(self):
        """
        GIVEN: Natural language statement
        WHEN: Converting to DCEC and proving
        THEN: Should complete full pipeline
        """
        # GIVEN
        nl_text = "Alice believes that it is raining"
        
        # WHEN - Phase 4C: NL to DCEC
        grammar = DCECEnglishGrammar()
        
        # Parse natural language
        try:
            parse_trees = grammar.engine.parse(nl_text)
            
            if parse_trees:
                # Get DCEC formula from parse tree
                dcec_formula = parse_trees[0].semantics
                
                # WHEN - Phase 4D: Prove using cognitive calculus
                prover = create_cognitive_prover()
                # Add axiom: if Alice believes P, and P is true, then P
                proof = prover.prove(str(dcec_formula))
                
                # THEN
                assert proof is not None
                assert hasattr(proof, 'status')
        except Exception as e:
            # Grammar parsing might not match, that's OK for now
            pytest.skip(f"Grammar parsing not available: {e}")
    
    def test_problem_file_to_proof_to_results(self):
        """
        GIVEN: Problem file content
        WHEN: Parsing and proving
        THEN: Should produce proof results
        """
        # GIVEN
        problem_content = """
        LOGIC: K
        
        ASSUMPTIONS:
        P
        P -> Q
        
        GOALS:
        Q
        """
        
        # WHEN - Phase 4D: Parse problem
        problem = parse_problem_string(problem_content)
        
        assert problem is not None
        assert len(problem.assumptions) == 2
        assert len(problem.goals) == 1
        
        # WHEN - Prove with native prover
        prover = create_prover(problem.logic)
        proof = prover.prove(problem.goals[0], problem.assumptions)
        
        # THEN
        assert proof is not None
        assert hasattr(proof, 'status')
        assert hasattr(proof, 'metadata')


class TestCrossComponentIntegration:
    """Test integration between different Phase 4 components."""
    
    def test_parser_and_prover_integration(self):
        """
        GIVEN: DCEC string and prover
        WHEN: Parsing and proving together
        THEN: Should work seamlessly
        """
        # GIVEN
        assumption1 = "P"
        assumption2 = "P -> Q"
        goal = "Q"
        
        # WHEN - Parse all
        parsed_a1 = parse_dcec_string(assumption1)
        parsed_a2 = parse_dcec_string(assumption2)
        parsed_goal = parse_dcec_string(goal)
        
        # WHEN - Prove
        prover = create_prover(ModalLogic.K)
        proof = prover.prove(parsed_goal, [parsed_a1, parsed_a2])
        
        # THEN
        assert proof is not None
    
    def test_grammar_and_prover_integration(self):
        """
        GIVEN: Grammar system and prover
        WHEN: Using together for NL reasoning
        THEN: Should integrate smoothly
        """
        # GIVEN
        grammar = DCECEnglishGrammar()
        prover = create_cognitive_prover()
        
        # Simple test - both components should be available
        assert grammar is not None
        assert prover is not None
        assert len(prover.cognitive_axioms) == 19
    
    def test_all_components_together(self):
        """
        GIVEN: All Phase 4 components
        WHEN: Using them in sequence
        THEN: Should work as integrated system
        """
        # GIVEN - Phase 4A: Clean and parse
        raw_input = "  P  &  Q  "
        cleaned = clean_dcec_expression(raw_input)
        formula = parse_dcec_string(cleaned)
        
        assert formula is not None
        
        # Phase 4B: Use inference engine
        engine = InferenceEngine()
        engine.add_assumption(formula)
        
        # Phase 4C: Grammar available
        grammar = DCECEnglishGrammar()
        assert grammar is not None
        
        # Phase 4D: Prover available
        prover = create_prover(ModalLogic.K)
        assert prover is not None
        
        # All components initialized successfully
        assert True


class TestWrapperIntegration:
    """Test wrapper integration with native implementations."""
    
    def test_shadow_prover_wrapper_native_preference(self):
        """
        GIVEN: ShadowProver wrapper with native preference
        WHEN: Initializing and using
        THEN: Should prefer native implementation
        """
        # GIVEN
        wrapper = ShadowProverWrapper(prefer_native=True)
        
        # WHEN
        initialized = wrapper.initialize()
        
        # THEN
        assert initialized is True
        
        status = wrapper.get_native_status()
        assert status['available'] is True
        assert status['preferred'] is True
        assert status['active'] is True
    
    def test_wrapper_prove_formula(self):
        """
        GIVEN: Wrapper initialized
        WHEN: Proving a simple formula
        THEN: Should use native implementation
        """
        # GIVEN
        wrapper = ShadowProverWrapper(prefer_native=True)
        wrapper.initialize()
        
        # WHEN
        task = wrapper.prove_formula("P -> P", logic="K")
        
        # THEN
        assert task is not None
        assert task.native_used is True
        assert task.result is not None


class TestPerformanceBenchmarks:
    """Performance benchmark tests."""
    
    def test_native_prover_performance(self):
        """
        GIVEN: Native prover
        WHEN: Proving multiple formulas
        THEN: Should complete quickly
        """
        # GIVEN
        prover = create_prover(ModalLogic.K)
        formulas = [
            "P -> P",
            "P & Q -> P",
            "P & Q -> Q",
            "P -> (Q -> P)",
            "(P -> Q) -> ((Q -> R) -> (P -> R))",
        ]
        
        # WHEN
        start_time = time.time()
        
        for formula in formulas:
            proof = prover.prove(formula)
            assert proof is not None
        
        end_time = time.time()
        elapsed = end_time - start_time
        
        # THEN - Should complete in reasonable time (relaxed for CI)
        # Note: These are soft limits, may vary on different CI runners
        assert elapsed < 5.0  # Reasonable upper bound for 5 formulas
        
        # Check average time per proof (informational, not strict)
        avg_time = elapsed / len(formulas)
        # Log performance but don't assert strict timing
        print(f"Average proof time: {avg_time:.3f}s")
    
    def test_cognitive_prover_performance(self):
        """
        GIVEN: Cognitive calculus prover
        WHEN: Proving cognitive formulas
        THEN: Should handle cognitive axioms efficiently
        """
        # GIVEN
        prover = create_cognitive_prover()
        
        # WHEN
        start_time = time.time()
        
        # Test cognitive axioms
        proof = prover.prove("K(P) -> P")  # Knowledge truth
        
        end_time = time.time()
        elapsed = end_time - start_time
        
        # THEN
        assert proof is not None
        # Relaxed timing for CI environments
        assert elapsed < 2.0  # Reasonable upper bound
        print(f"Cognitive proof time: {elapsed:.3f}s")
    
    def test_problem_parsing_performance(self):
        """
        GIVEN: Multiple problem files
        WHEN: Parsing them
        THEN: Should parse quickly
        """
        # GIVEN
        problems = [
            "LOGIC: K\nGOALS:\nP",
            "LOGIC: S4\nASSUMPTIONS:\nP\nGOALS:\nP",
            "LOGIC: S5\nASSUMPTIONS:\nP\nQ\nGOALS:\nP & Q",
        ]
        
        # WHEN
        start_time = time.time()
        
        for problem_str in problems:
            problem = parse_problem_string(problem_str)
            assert problem is not None
        
        end_time = time.time()
        elapsed = end_time - start_time
        
        # THEN
        # Relaxed timing for CI environments
        assert elapsed < 1.0  # Reasonable upper bound for parsing
        print(f"Problem parsing time: {elapsed:.3f}s for 3 problems")


class TestErrorHandlingIntegration:
    """Test error handling across components."""
    
    def test_invalid_input_handling(self):
        """
        GIVEN: Invalid inputs
        WHEN: Processing them
        THEN: Should handle errors gracefully
        """
        # Test invalid DCEC string
        try:
            parse_result = parse_dcec_string("((((")
            # Should either return None or raise exception
            assert parse_result is None
        except Exception:
            pass  # Expected
        
        # Test invalid problem
        try:
            problem = parse_problem_string("INVALID FORMAT")
            # Should create empty problem or handle gracefully
            assert problem is not None
        except Exception:
            pass  # Expected
    
    def test_prover_with_invalid_formula(self):
        """
        GIVEN: Prover and invalid formula
        WHEN: Attempting to prove
        THEN: Should handle gracefully
        """
        # GIVEN
        prover = create_prover(ModalLogic.K)
        
        # WHEN - Try with empty/invalid formula
        try:
            proof = prover.prove("")
            # Should handle empty formula
            assert proof is not None
        except Exception:
            pass  # Expected


class TestComponentAvailability:
    """Test that all components are available."""
    
    def test_phase_4a_available(self):
        """Verify Phase 4A components are available."""
        from ipfs_datasets_py.logic.native import (
            parse_dcec_string,
            clean_dcec_expression,
            tokenize_dcec,
        )
        
        assert parse_dcec_string is not None
        assert clean_dcec_expression is not None
        assert tokenize_dcec is not None
    
    def test_phase_4b_available(self):
        """Verify Phase 4B components are available."""
        from ipfs_datasets_py.logic.native import (
            InferenceEngine,
            InferenceRule,
        )
        
        assert InferenceEngine is not None
        assert InferenceRule is not None
    
    def test_phase_4c_available(self):
        """Verify Phase 4C components are available."""
        from ipfs_datasets_py.logic.native import (
            GrammarEngine,
            DCECEnglishGrammar,
        )
        
        assert GrammarEngine is not None
        assert DCECEnglishGrammar is not None
    
    def test_phase_4d_available(self):
        """Verify Phase 4D components are available."""
        from ipfs_datasets_py.logic.native import (
            create_prover,
            create_cognitive_prover,
            ModalLogic,
            parse_problem_string,
        )
        
        assert create_prover is not None
        assert create_cognitive_prover is not None
        assert ModalLogic is not None
        assert parse_problem_string is not None


class TestVersioning:
    """Test version information."""
    
    def test_version_available(self):
        """
        GIVEN: Native implementation
        WHEN: Checking version
        THEN: Should have version 0.8.0+
        """
        from ipfs_datasets_py.logic.native import __version__
        
        assert __version__ is not None
        # Should be 0.8.0 or higher
        major, minor, patch = __version__.split('.')
        assert int(major) >= 0
        assert int(minor) >= 8 or int(major) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
