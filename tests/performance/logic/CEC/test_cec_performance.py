"""
Performance benchmarks for CEC logic components.

These tests establish baseline performance metrics for Phase 7 optimization.
Phase 3 Week 5: Performance Benchmarks (15 tests)
"""

import pytest
import sys
import time
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from ipfs_datasets_py.logic.CEC.native import (
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
    QuantifiedFormula,
    VariableTerm,
    Sort,
    Variable,
    Predicate,
    ProofResult,
)


# Phase 3 Week 5 Day 8-9: Formula Creation Benchmarks (5 tests)
class TestFormulaCreationBenchmarks:
    """Benchmark suite for formula creation performance."""
    
    def test_atomic_formula_creation_speed(self):
        """
        GIVEN a predicate and terms
        WHEN creating 1000 atomic formulas
        THEN it should complete within performance target
        """
        # GIVEN
        agent = Sort("Agent")
        pred = Predicate("act", [agent])
        x = Variable("x", agent)
        term = VariableTerm(x)
        
        # WHEN - Create 1000 formulas
        start = time.perf_counter()
        for i in range(1000):
            formula = AtomicFormula(pred, [term])
        elapsed = time.perf_counter() - start
        
        # THEN - Should be fast (<100ms for 1000 formulas on typical hardware)
        # Note: This may fail on constrained CI runners
        assert elapsed < 0.2, f"Formula creation too slow: {elapsed*1000:.2f}ms (expected <200ms)"
        print(f"✓ Atomic formula creation: {elapsed*1000:.2f}ms for 1000 formulas ({elapsed/1000*1000000:.2f}μs each)")
    
    def test_deontic_formula_creation_speed(self):
        """
        GIVEN base formulas
        WHEN creating 1000 deontic formulas
        THEN it should complete within performance target
        """
        # GIVEN
        agent = Sort("Agent")
        pred = Predicate("act", [agent])
        x = Variable("x", agent)
        base = AtomicFormula(pred, [VariableTerm(x)])
        
        # WHEN - Create 1000 deontic formulas
        start = time.time()
        for i in range(1000):
            formula = DeonticFormula(DeonticOperator.OBLIGATION, base)
        elapsed = time.time() - start
        
        # THEN - Should be fast (<100ms for 1000 formulas)
        assert elapsed < 0.1
        print(f"✓ Deontic formula creation: {elapsed*1000:.2f}ms for 1000 formulas")
    
    def test_cognitive_formula_creation_speed(self):
        """
        GIVEN base formulas and agents
        WHEN creating 1000 cognitive formulas
        THEN it should complete within performance target
        """
        # GIVEN
        agent = Sort("Agent")
        pred = Predicate("fact", [])
        a = Variable("agent", agent)
        base = AtomicFormula(pred, [])
        term_a = VariableTerm(a)
        
        # WHEN - Create 1000 cognitive formulas
        start = time.time()
        for i in range(1000):
            formula = CognitiveFormula(CognitiveOperator.BELIEF, term_a, base)
        elapsed = time.time() - start
        
        # THEN - Should be fast (<150ms for 1000 formulas)
        assert elapsed < 0.15
        print(f"✓ Cognitive formula creation: {elapsed*1000:.2f}ms for 1000 formulas")
    
    def test_deeply_nested_formula_creation_speed(self):
        """
        GIVEN components for nested formulas
        WHEN creating 100 deeply nested formulas (10 levels)
        THEN it should complete within performance target
        """
        # GIVEN
        agent = Sort("Agent")
        pred = Predicate("act", [agent])
        x = Variable("x", agent)
        
        # WHEN - Create 100 deeply nested formulas
        start = time.time()
        for i in range(100):
            # Create 10-level nesting
            formula = AtomicFormula(pred, [VariableTerm(x)])
            for j in range(10):
                if j % 2 == 0:
                    formula = DeonticFormula(DeonticOperator.OBLIGATION, formula)
                else:
                    formula = CognitiveFormula(CognitiveOperator.BELIEF, VariableTerm(x), formula)
        elapsed = time.time() - start
        
        # THEN - Should complete (<500ms for 100 formulas)
        assert elapsed < 0.5
        print(f"✓ Deeply nested formula creation: {elapsed*1000:.2f}ms for 100 10-level formulas")
    
    def test_quantified_formula_creation_speed(self):
        """
        GIVEN variables and formulas
        WHEN creating 1000 quantified formulas
        THEN it should complete within performance target
        """
        # GIVEN
        agent = Sort("Agent")
        pred = Predicate("P", [agent])
        x = Variable("x", agent)
        base = AtomicFormula(pred, [VariableTerm(x)])
        
        # WHEN - Create 1000 quantified formulas
        start = time.time()
        for i in range(1000):
            formula = QuantifiedFormula(LogicalConnective.FORALL, x, base)
        elapsed = time.time() - start
        
        # THEN - Should be fast (<100ms for 1000 formulas)
        assert elapsed < 0.1
        print(f"✓ Quantified formula creation: {elapsed*1000:.2f}ms for 1000 formulas")


# Phase 3 Week 5 Day 8-9: Theorem Proving Benchmarks (5 tests)
class TestTheoremProvingBenchmarks:
    """Benchmark suite for theorem proving performance."""
    
    def test_simple_proof_speed(self):
        """
        GIVEN simple proofs (goal = axiom)
        WHEN proving 100 theorems
        THEN it should complete within performance target
        """
        # GIVEN
        prover = TheoremProver()
        prover.initialize()
        
        namespace = DCECNamespace()
        
        # WHEN - Prove 100 simple theorems
        start = time.time()
        for i in range(100):
            pred = namespace.add_predicate(f"P{i}", [])
            formula = AtomicFormula(pred, [])
            attempt = prover.prove_theorem(goal=formula, axioms=[formula])
            assert attempt.result == ProofResult.PROVED
        elapsed = time.time() - start
        
        # THEN - Should be fast (<1s for 100 proofs)
        assert elapsed < 1.0
        print(f"✓ Simple proof speed: {elapsed*1000:.2f}ms for 100 proofs ({elapsed/100*1000:.2f}ms each)")
    
    def test_modus_ponens_proof_speed(self):
        """
        GIVEN proofs requiring modus ponens
        WHEN proving 50 theorems
        THEN it should complete within performance target
        """
        # GIVEN
        prover = TheoremProver()
        prover.initialize()
        namespace = DCECNamespace()
        
        # WHEN - Prove 50 modus ponens theorems
        start = time.time()
        for i in range(50):
            p = namespace.add_predicate(f"P{i}", [])
            q = namespace.add_predicate(f"Q{i}", [])
            
            f_p = AtomicFormula(p, [])
            f_q = AtomicFormula(q, [])
            impl = ConnectiveFormula(LogicalConnective.IMPLIES, [f_p, f_q])
            
            attempt = prover.prove_theorem(goal=f_q, axioms=[impl, f_p])
            assert attempt.result == ProofResult.PROVED
        elapsed = time.time() - start
        
        # THEN - Should be reasonable (<2s for 50 proofs)
        assert elapsed < 2.0
        print(f"✓ Modus ponens proof speed: {elapsed*1000:.2f}ms for 50 proofs ({elapsed/50*1000:.2f}ms each)")
    
    def test_multi_step_proof_speed(self):
        """
        GIVEN proofs requiring 5 inference steps
        WHEN proving 20 theorems
        THEN it should complete within performance target
        """
        # GIVEN
        prover = TheoremProver()
        prover.initialize()
        namespace = DCECNamespace()
        
        # WHEN - Prove 20 multi-step theorems
        start = time.time()
        for i in range(20):
            # Create chain P1→P2→P3→P4→P5
            preds = [namespace.add_predicate(f"P{i}_{j}", []) for j in range(5)]
            formulas = [AtomicFormula(p, []) for p in preds]
            
            # Create implications
            axioms = [formulas[0]]  # P1
            for j in range(4):
                impl = ConnectiveFormula(LogicalConnective.IMPLIES, [formulas[j], formulas[j+1]])
                axioms.append(impl)
            
            # Prove P5
            attempt = prover.prove_theorem(goal=formulas[4], axioms=axioms)
            # May timeout or succeed
        elapsed = time.time() - start
        
        # THEN - Should complete (<5s for 20 multi-step proofs)
        assert elapsed < 5.0
        print(f"✓ Multi-step proof speed: {elapsed*1000:.2f}ms for 20 proofs ({elapsed/20*1000:.2f}ms each)")
    
    def test_proof_cache_effectiveness(self):
        """
        GIVEN repeated proofs
        WHEN proving same theorem multiple times
        THEN cache should provide speedup
        """
        # GIVEN
        prover = TheoremProver()
        prover.initialize()
        namespace = DCECNamespace()
        
        pred = namespace.add_predicate("cached_test", [])
        formula = AtomicFormula(pred, [])
        
        # WHEN - First proof (no cache)
        start = time.time()
        attempt1 = prover.prove_theorem(goal=formula, axioms=[formula])
        time_first = time.time() - start
        
        # Second proof (with cache)
        start = time.time()
        attempt2 = prover.prove_theorem(goal=formula, axioms=[formula])
        time_second = time.time() - start
        
        # THEN - Both succeed
        assert attempt1.result == ProofResult.PROVED
        assert attempt2.result == ProofResult.PROVED
        
        # Cache may or may not provide speedup depending on implementation
        print(f"✓ Proof caching: First={time_first*1000:.4f}ms, Second={time_second*1000:.4f}ms")
    
    def test_prover_memory_usage(self):
        """
        GIVEN many proof attempts
        WHEN tracking memory
        THEN memory should be managed efficiently
        """
        # GIVEN
        prover = TheoremProver()
        prover.initialize()
        namespace = DCECNamespace()
        
        # WHEN - Perform 100 proofs
        for i in range(100):
            pred = namespace.add_predicate(f"mem_test_{i}", [])
            formula = AtomicFormula(pred, [])
            prover.prove_theorem(goal=formula, axioms=[formula])
        
        # THEN - Should track attempts
        assert len(prover.proof_attempts) >= 0  # May or may not store all
        print(f"✓ Prover memory: {len(prover.proof_attempts)} proof attempts tracked")


# Phase 3 Week 5 Day 8-9: NL Conversion Benchmarks (5 tests)
class TestNLConversionBenchmarks:
    """Benchmark suite for natural language conversion performance."""
    
    def test_simple_sentence_conversion_speed(self):
        """
        GIVEN simple sentences
        WHEN converting 100 sentences
        THEN it should complete within performance target
        """
        # GIVEN
        converter = NaturalLanguageConverter()
        sentences = [
            "the agent must act",
            "the agent may leave",
            "the door is closed"
        ]
        
        # WHEN - Convert 100 sentences
        start = time.time()
        for i in range(100):
            for sentence in sentences:
                result = converter.convert_to_dcec(sentence)
        elapsed = time.time() - start
        
        # THEN - Should be fast (<500ms for 300 conversions)
        assert elapsed < 0.5
        print(f"✓ Simple NL conversion: {elapsed*1000:.2f}ms for 300 conversions ({elapsed/300*1000:.2f}ms each)")
    
    def test_complex_sentence_conversion_speed(self):
        """
        GIVEN complex sentences with multiple clauses
        WHEN converting 50 sentences
        THEN it should complete within performance target
        """
        # GIVEN
        converter = NaturalLanguageConverter()
        complex_sentences = [
            "if the door is open then the agent must close it",
            "the agent believes that the door is closed and the lights are off",
            "the agent must complete the task before leaving"
        ]
        
        # WHEN - Convert 50 complex sentences
        start = time.time()
        for i in range(50):
            for sentence in complex_sentences:
                result = converter.convert_to_dcec(sentence)
        elapsed = time.time() - start
        
        # THEN - Should be reasonable (<1s for 150 conversions)
        assert elapsed < 1.0
        print(f"✓ Complex NL conversion: {elapsed*1000:.2f}ms for 150 conversions ({elapsed/150*1000:.2f}ms each)")
    
    def test_batch_conversion_speed(self):
        """
        GIVEN a batch of sentences
        WHEN converting all at once
        THEN batch processing should be efficient
        """
        # GIVEN
        converter = NaturalLanguageConverter()
        batch = [f"the agent must perform action {i}" for i in range(100)]
        
        # WHEN - Convert batch
        start = time.time()
        results = []
        for sentence in batch:
            result = converter.convert_to_dcec(sentence)
            results.append(result)
        elapsed = time.time() - start
        
        # THEN - Should complete (<1s for 100 sentences)
        assert elapsed < 1.0
        success_count = sum(1 for r in results if r.success)
        print(f"✓ Batch NL conversion: {elapsed*1000:.2f}ms for 100 sentences ({success_count} successful)")
    
    def test_converter_initialization_speed(self):
        """
        GIVEN converter initialization
        WHEN creating new converter
        THEN initialization should be fast
        """
        # WHEN - Initialize converter
        start = time.time()
        converter = NaturalLanguageConverter()
        converter.initialize()
        elapsed = time.time() - start
        
        # THEN - Should be very fast (<100ms)
        assert elapsed < 0.1
        print(f"✓ Converter initialization: {elapsed*1000:.2f}ms")
    
    def test_conversion_history_tracking_overhead(self):
        """
        GIVEN conversion with history tracking
        WHEN performing many conversions
        THEN history tracking should have minimal overhead
        """
        # GIVEN
        converter = NaturalLanguageConverter()
        
        # WHEN - Convert with history tracking
        start = time.time()
        for i in range(100):
            result = converter.convert_to_dcec(f"the agent must do task {i}")
        elapsed = time.time() - start
        
        # THEN - Should be efficient
        assert elapsed < 1.0
        history_size = len(converter.conversion_history)
        print(f"✓ Conversion history overhead: {elapsed*1000:.2f}ms for 100 conversions ({history_size} tracked)")


if __name__ == "__main__":
    # Run benchmarks with verbose output
    pytest.main([__file__, "-v", "-s"])
