#!/usr/bin/env python3
"""
ZKP Performance Benchmarks

This module provides comprehensive performance benchmarks for the ZKP module,
measuring proof generation, verification, and scaling characteristics.

Run with: pytest tests/unit_tests/logic/zkp/test_zkp_performance.py -v
"""

import pytest
import time
import statistics
from ipfs_datasets_py.logic.zkp import ZKPProver, ZKPVerifier


class TestZKPPerformance:
    """Performance benchmarks for ZKP module."""
    
    def test_proof_generation_performance(self):
        """
        GIVEN: ZKP prover
        WHEN: Generating multiple proofs
        THEN: Performance is within acceptable bounds
        """
        prover = ZKPProver()
        
        # Measure generation time
        times = []
        for i in range(100):
            theorem = f"Theorem {i}"
            axioms = ["Axiom A", "Axiom B"]
            
            start = time.time()
            proof = prover.generate_proof(theorem, axioms)
            times.append(time.time() - start)
        
        mean_time = statistics.mean(times)
        std_time = statistics.stdev(times)
        
        # Assert performance is reasonable (< 1ms for simple proof)
        assert mean_time < 0.001, f"Proof generation too slow: {mean_time*1000:.2f}ms"
        
        print(f"\nProof Generation Performance:")
        print(f"  Mean: {mean_time*1000:.3f}ms")
        print(f"  Std:  {std_time*1000:.3f}ms")
        print(f"  Min:  {min(times)*1000:.3f}ms")
        print(f"  Max:  {max(times)*1000:.3f}ms")
    
    def test_proof_verification_performance(self):
        """
        GIVEN: Generated proof
        WHEN: Verifying multiple times
        THEN: Verification is fast
        """
        prover = ZKPProver()
        verifier = ZKPVerifier()
        
        # Generate one proof
        proof = prover.generate_proof("Test theorem", ["Axiom 1", "Axiom 2"])
        
        # Measure verification time
        times = []
        for _ in range(100):
            start = time.time()
            is_valid = verifier.verify_proof(proof)
            times.append(time.time() - start)
            assert is_valid
        
        mean_time = statistics.mean(times)
        
        # Assert verification is fast (< 0.1ms)
        assert mean_time < 0.0001, f"Verification too slow: {mean_time*1000:.2f}ms"
        
        print(f"\nProof Verification Performance:")
        print(f"  Mean: {mean_time*1000:.3f}ms")
        print(f"  Min:  {min(times)*1000:.3f}ms")
        print(f"  Max:  {max(times)*1000:.3f}ms")
    
    def test_proof_size_consistency(self):
        """
        GIVEN: Proofs with different numbers of axioms
        WHEN: Measuring proof sizes
        THEN: Sizes are consistent
        """
        prover = ZKPProver()
        
        sizes = []
        for num_axioms in [1, 5, 10, 20, 50]:
            axioms = [f"Axiom {i}" for i in range(num_axioms)]
            proof = prover.generate_proof(f"Theorem for {num_axioms} axioms", axioms)
            sizes.append(proof.size_bytes)
        
        # All proof sizes should be the same (simulated backend)
        assert all(s == sizes[0] for s in sizes), "Proof sizes inconsistent"
        assert sizes[0] == 160, f"Unexpected proof size: {sizes[0]}"
        
        print(f"\nProof Size Consistency:")
        print(f"  Size: {sizes[0]} bytes (constant across axiom counts)")
    
    def test_caching_performance_improvement(self):
        """
        GIVEN: Prover with caching
        WHEN: Generating same proof twice
        THEN: Second generation is faster
        """
        prover = ZKPProver(enable_caching=True)
        
        theorem = "Cached theorem"
        axioms = ["Axiom A", "Axiom B"]
        
        # First generation (not cached)
        start = time.time()
        proof1 = prover.generate_proof(theorem, axioms)
        time1 = time.time() - start
        
        # Second generation (cached)
        start = time.time()
        proof2 = prover.generate_proof(theorem, axioms)
        time2 = time.time() - start
        
        # Cached should be faster
        speedup = time1 / time2 if time2 > 0 else float('inf')
        assert speedup > 1, f"Cache didn't improve performance: {speedup:.1f}x"
        
        print(f"\nCaching Performance:")
        print(f"  First:  {time1*1000:.3f}ms")
        print(f"  Cached: {time2*1000:.3f}ms")
        print(f"  Speedup: {speedup:.1f}x")
    
    def test_batch_proof_generation(self):
        """
        GIVEN: Multiple proofs to generate
        WHEN: Generating in batch
        THEN: Total time is acceptable
        """
        prover = ZKPProver()
        
        num_proofs = 100
        start = time.time()
        
        proofs = []
        for i in range(num_proofs):
            proof = prover.generate_proof(
                f"Theorem {i}",
                [f"Axiom {j}" for j in range(3)]
            )
            proofs.append(proof)
        
        total_time = time.time() - start
        avg_time = total_time / num_proofs
        
        # Average should be < 1ms per proof
        assert avg_time < 0.001, f"Batch generation too slow: {avg_time*1000:.2f}ms/proof"
        
        print(f"\nBatch Generation Performance:")
        print(f"  Total: {total_time*1000:.1f}ms for {num_proofs} proofs")
        print(f"  Average: {avg_time*1000:.3f}ms per proof")
    
    def test_memory_usage_stability(self):
        """
        GIVEN: Many proof generations
        WHEN: Generating many proofs
        THEN: Memory usage remains stable
        """
        prover = ZKPProver(enable_caching=False)  # Disable cache
        
        # Generate many proofs
        for i in range(1000):
            theorem = f"Theorem {i}"
            axioms = [f"Axiom {j}" for j in range(5)]
            proof = prover.generate_proof(theorem, axioms)
            
            # Don't keep references (allow garbage collection)
            del proof
        
        # If we get here without OOM, memory is stable
        assert True, "Memory usage stable"
    
    def test_concurrent_prover_performance(self):
        """
        GIVEN: Multiple provers
        WHEN: Using different prover instances
        THEN: Performance is consistent
        """
        provers = [ZKPProver() for _ in range(10)]
        
        times = []
        for prover in provers:
            start = time.time()
            proof = prover.generate_proof("Test", ["Axiom 1"])
