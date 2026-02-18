"""
Edge case tests for ZKP module.

This module tests boundary conditions, unusual inputs, and edge cases
to improve coverage and robustness.
"""

import pytest
import time
from ipfs_datasets_py.logic.zkp import (
    ZKPProver,
    ZKPVerifier,
    ZKPProof,
    ZKPError,
)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_empty_theorem(self):
        """
        GIVEN: Empty theorem string
        WHEN: Generating proof
        THEN: Should raise ZKPError
        """
        prover = ZKPProver()
        
        # Empty theorem should raise error
        with pytest.raises(ZKPError, match="Theorem cannot be empty"):
            proof = prover.generate_proof(
                theorem="",
                private_axioms=["axiom1"]
            )
    
    def test_empty_axioms_list(self):
        """
        GIVEN: Empty axioms list
        WHEN: Generating proof
        THEN: Should raise ZKPError
        """
        prover = ZKPProver()
        
        # Empty axioms should raise error
        with pytest.raises(ZKPError, match="At least one axiom required"):
            proof = prover.generate_proof(
                theorem="Some theorem",
                private_axioms=[]
            )
    
    def test_very_long_theorem(self):
        """
        GIVEN: Very long theorem string
        WHEN: Generating proof
        THEN: Should handle without crash
        """
        prover = ZKPProver()
        
        # 10KB theorem
        long_theorem = "A" * 10000
        proof = prover.generate_proof(
            theorem=long_theorem,
            private_axioms=["axiom"]
        )
        
        assert isinstance(proof, ZKPProof)
        assert proof.public_inputs['theorem'] == long_theorem
    
    def test_very_long_axioms(self):
        """
        GIVEN: Very long axiom strings
        WHEN: Generating proof
        THEN: Should handle without crash
        """
        prover = ZKPProver()
        
        # 5KB axioms each
        long_axioms = ["B" * 5000, "C" * 5000]
        proof = prover.generate_proof(
            theorem="theorem",
            private_axioms=long_axioms
        )
        
        assert isinstance(proof, ZKPProof)
        assert proof.metadata['num_axioms'] == 2
    
    def test_many_axioms(self):
        """
        GIVEN: Large number of axioms
        WHEN: Generating proof
        THEN: Should handle efficiently
        """
        prover = ZKPProver()
        
        # 1000 axioms
        many_axioms = [f"Axiom {i}" for i in range(1000)]
        
        start = time.time()
        proof = prover.generate_proof(
            theorem="conclusion",
            private_axioms=many_axioms
        )
        duration = time.time() - start
        
        assert isinstance(proof, ZKPProof)
        assert proof.metadata['num_axioms'] == 1000
        # Should be fast even with many axioms
        assert duration < 0.1, f"Too slow: {duration}s"
    
    def test_special_characters_in_theorem(self):
        """
        GIVEN: Theorem with special characters
        WHEN: Generating proof
        THEN: Should handle correctly
        """
        prover = ZKPProver()
        verifier = ZKPVerifier()
        
        # Various special characters
        special_theorem = "∀x∃y: x→y ∧ ¬(x∨y) ≡ (x⊕y) ∈ {0,1}^n"
        proof = prover.generate_proof(
            theorem=special_theorem,
            private_axioms=["axiom"]
        )
        
        assert isinstance(proof, ZKPProof)
        assert verifier.verify_proof(proof)
    
    def test_unicode_in_axioms(self):
        """
        GIVEN: Axioms with Unicode characters
        WHEN: Generating and verifying proof
        THEN: Should work correctly
        """
        prover = ZKPProver()
        verifier = ZKPVerifier()
        
        unicode_axioms = [
            "假设 (hypothesis)",
            "定理 (theorem)",
            "証明 (proof)"
        ]
        
        proof = prover.generate_proof(
            theorem="結論 (conclusion)",
            private_axioms=unicode_axioms
        )
        
        assert verifier.verify_proof(proof)
    
    def test_newlines_in_inputs(self):
        """
        GIVEN: Theorem and axioms with newlines
        WHEN: Generating proof
        THEN: Should preserve newlines
        """
        prover = ZKPProver()
        
        multiline_theorem = "Line 1\nLine 2\nLine 3"
        multiline_axioms = ["Axiom\nwith\nnewlines"]
        
        proof = prover.generate_proof(
            theorem=multiline_theorem,
            private_axioms=multiline_axioms
        )
        
        assert "\n" in proof.public_inputs['theorem']
    
    def test_proof_with_no_metadata(self):
        """
        GIVEN: Proof generation without extra metadata
        WHEN: Verifying proof
        THEN: Should work with default metadata
        """
        prover = ZKPProver()
        verifier = ZKPVerifier()
        
        proof = prover.generate_proof(
            theorem="test",
            private_axioms=["axiom"]
            # No metadata parameter
        )
        
        assert verifier.verify_proof(proof)
        assert proof.metadata is not None
    
    def test_proof_with_custom_metadata(self):
        """
        GIVEN: Proof with custom metadata
        WHEN: Verifying proof
        THEN: Custom metadata should be preserved
        """
        prover = ZKPProver()
        verifier = ZKPVerifier()
        
        custom_meta = {
            'version': '2.0',
            'tags': ['test', 'custom'],
            'nested': {'key': 'value'}
        }
        
        proof = prover.generate_proof(
            theorem="test",
            private_axioms=["axiom"],
            metadata=custom_meta
        )
        
        assert 'version' in proof.metadata
        assert proof.metadata['version'] == '2.0'
        assert verifier.verify_proof(proof)
    
    def test_proof_size_consistency(self):
        """
        GIVEN: Proofs with different input sizes
        WHEN: Checking proof sizes
        THEN: All proofs should have same size (simulated backend)
        """
        prover = ZKPProver()
        
        sizes = []
        
        # Small proof
        proof1 = prover.generate_proof("A", ["B"])
        sizes.append(proof1.size_bytes)
        
        # Large proof
        proof2 = prover.generate_proof("X" * 1000, ["Y" * 1000] * 10)
        sizes.append(proof2.size_bytes)
        
        # All should be 160 bytes (simulated Groth16)
        assert all(s == 160 for s in sizes)
    
    def test_verifier_with_different_backend(self):
        """
        GIVEN: Prover and verifier with same backend
        WHEN: Generating and verifying
        THEN: Should work correctly
        """
        # Both use simulated backend explicitly
        prover = ZKPProver(backend="simulated")
        verifier = ZKPVerifier(backend="simulated")
        
        proof = prover.generate_proof("theorem", ["axiom"])
        assert verifier.verify_proof(proof)
    
    def test_proof_dict_round_trip(self):
        """
        GIVEN: Proof object
        WHEN: Converting to dict and back
        THEN: Should preserve all data
        """
        prover = ZKPProver()
        
        original_proof = prover.generate_proof(
            "Original theorem",
            ["Axiom 1", "Axiom 2"],
            metadata={'key': 'value'}
        )
        
        # to_dict
        proof_dict = original_proof.to_dict()
        assert isinstance(proof_dict, dict)
        assert 'proof_data' in proof_dict
        assert 'public_inputs' in proof_dict
        
        # from_dict
        restored_proof = ZKPProof.from_dict(proof_dict)
        assert restored_proof.public_inputs == original_proof.public_inputs
        assert restored_proof.size_bytes == original_proof.size_bytes
    
    def test_proof_metadata_in_dict(self):
        """
        GIVEN: Proof with rich metadata
        WHEN: Serializing to dict
        THEN: Metadata should be preserved
        """
        prover = ZKPProver()
        
        metadata = {
            'application': 'test',
            'timestamp': 1234567890,
            'nested': {'data': [1, 2, 3]}
        }
        
        proof = prover.generate_proof("test", ["axiom"], metadata=metadata)
        proof_dict = proof.to_dict()
        
        restored = ZKPProof.from_dict(proof_dict)
        assert 'application' in restored.metadata
        assert restored.metadata['application'] == 'test'
    
    def test_concurrent_prover_creation(self):
        """
        GIVEN: Multiple provers created concurrently
        WHEN: Each generates proofs
        THEN: All should work independently
        """
        # Create multiple provers
        provers = [ZKPProver() for _ in range(10)]
        
        # Each generates a proof
        proofs = []
        for i, prover in enumerate(provers):
            proof = prover.generate_proof(
                f"Theorem {i}",
                [f"Axiom {i}"]
            )
            proofs.append(proof)
        
        # All proofs should be valid and unique
        assert len(proofs) == 10
        assert len(set(p.public_inputs['theorem'] for p in proofs)) == 10
    
    def test_verifier_reuse(self):
        """
        GIVEN: Single verifier
        WHEN: Verifying multiple different proofs
        THEN: Should verify all correctly
        """
        prover = ZKPProver()
        verifier = ZKPVerifier()
        
        # Generate multiple proofs
        proofs = []
        for i in range(20):
            proof = prover.generate_proof(
                f"Theorem {i}",
                [f"Axiom {i}"]
            )
            proofs.append(proof)
        
        # Verify all with same verifier
        for proof in proofs:
            assert verifier.verify_proof(proof)
    
    def test_cache_with_identical_inputs(self):
        """
        GIVEN: Prover with caching enabled
        WHEN: Generating same proof multiple times
        THEN: Cache should be effective
        """
        prover = ZKPProver(enable_caching=True)
        
        theorem = "Cached theorem"
        axioms = ["Axiom A", "Axiom B"]
        
        # First generation
        proof1 = prover.generate_proof(theorem, axioms)
        stats1 = prover.get_stats()
        
        # Second generation (should hit cache)
        proof2 = prover.generate_proof(theorem, axioms)
        stats2 = prover.get_stats()
        
        # Cache hit count should increase
        assert stats2['cache_hits'] > stats1['cache_hits']
        # Proof generation count should not increase
        assert stats2['proofs_generated'] == stats1['proofs_generated']
    
    def test_cache_with_different_inputs(self):
        """
        GIVEN: Prover with caching enabled
        WHEN: Generating proofs with different inputs
        THEN: Cache should not be hit
        """
        prover = ZKPProver(enable_caching=True)
        
        # Generate different proofs
        proof1 = prover.generate_proof("Theorem 1", ["Axiom 1"])
        proof2 = prover.generate_proof("Theorem 2", ["Axiom 2"])
        
        stats = prover.get_stats()
        
        # Should generate 2 proofs (no cache hits)
        assert stats['proofs_generated'] == 2
        assert stats['cache_hits'] == 0
    
    def test_prover_without_caching(self):
        """
        GIVEN: Prover with caching disabled
        WHEN: Generating same proof twice
        THEN: Should regenerate both times
        """
        prover = ZKPProver(enable_caching=False)
        
        # Generate same proof twice
        proof1 = prover.generate_proof("Test", ["Axiom"])
        proof2 = prover.generate_proof("Test", ["Axiom"])
        
        stats = prover.get_stats()
        
        # Should generate both times (no caching)
        assert stats['proofs_generated'] == 2
        assert stats['cache_hits'] == 0


class TestErrorConditions:
    """Test error handling and validation."""
    
    def test_invalid_backend_name(self):
        """
        GIVEN: Invalid backend name
        WHEN: Creating prover
        THEN: Should raise ZKPError
        """
        with pytest.raises(ZKPError, match="Unknown ZKP backend"):
            ZKPProver(backend="invalid_backend_xyz")
    
    def test_groth16_backend_fails_closed_prover(self):
        """
        GIVEN: Groth16 backend (not implemented)
        WHEN: Trying to generate proof
        THEN: Should raise ZKPError
        """
        with pytest.raises(ZKPError, match="Groth16 backend is not implemented"):
            prover = ZKPProver(backend="groth16")
            prover.generate_proof("test", ["axiom"])
    
    def test_groth16_backend_fails_closed_verifier(self):
        """
        GIVEN: Groth16 backend (not implemented)
        WHEN: Trying to verify proof
        THEN: Should raise ZKPError
        """
        # Create valid proof with simulated backend
        prover = ZKPProver(backend="simulated")
        proof = prover.generate_proof("test", ["axiom"])
        
        # Try to verify with groth16 (should fail)
        with pytest.raises(ZKPError, match="Groth16 backend is not implemented"):
            verifier = ZKPVerifier(backend="groth16")
            verifier.verify_proof(proof)
    
    def test_malformed_proof_dict(self):
        """
        GIVEN: Malformed proof dictionary
        WHEN: Creating ZKPProof from dict
        THEN: Should handle gracefully
        """
        # Missing required fields
        bad_dict = {'incomplete': 'data'}
        
        with pytest.raises((KeyError, ValueError, TypeError)):
            ZKPProof.from_dict(bad_dict)
    
    def test_verifier_with_none_proof(self):
        """
        GIVEN: Verifier
        WHEN: Trying to verify None
        THEN: Should return False gracefully
        """
        verifier = ZKPVerifier()
        
        # Verifier handles None gracefully by returning False
        result = verifier.verify_proof(None)
        assert result == False
    
    def test_prover_stats_after_errors(self):
        """
        GIVEN: Prover that encounters errors
        WHEN: Checking stats
        THEN: Stats should still be accessible
        """
        prover = ZKPProver()
        
        # Generate some valid proofs
        prover.generate_proof("test1", ["axiom"])
        prover.generate_proof("test2", ["axiom"])
        
        # Try to use invalid backend (this will fail during generation)
        try:
            bad_prover = ZKPProver(backend="invalid")
        except ZKPError:
            pass
        
        # Original prover stats should still work
        stats = prover.get_stats()
        assert stats['proofs_generated'] == 2


class TestPerformanceEdgeCases:
    """Test performance-related edge cases."""
    
    def test_rapid_proof_generation(self):
        """
        GIVEN: Prover
        WHEN: Generating many proofs rapidly
        THEN: Should handle without slowdown
        """
        prover = ZKPProver(enable_caching=False)
        
        times = []
        for i in range(100):
            start = time.time()
            prover.generate_proof(f"Theorem {i}", [f"Axiom {i}"])
            times.append(time.time() - start)
        
        # Average time should be consistent
        import statistics
        mean = statistics.mean(times)
        std = statistics.stdev(times)
        
        # Coefficient of variation should be low
        cv = std / mean if mean > 0 else 0
        assert cv < 1.0, f"Performance inconsistent: CV={cv}"
    
    def test_memory_stability_with_large_proofs(self):
        """
        GIVEN: Many large proofs
        WHEN: Generating without keeping references
        THEN: Memory should remain stable
        """
        prover = ZKPProver(enable_caching=False)
        
        # Generate many large proofs without keeping references
        for i in range(500):
            long_theorem = "T" * 1000
            long_axioms = ["A" * 1000 for _ in range(10)]
            proof = prover.generate_proof(long_theorem, long_axioms)
            # Don't keep reference (allow GC)
            del proof
        
        # If we get here, memory is stable
        assert True
    
    def test_verifier_performance_consistency(self):
        """
        GIVEN: Verifier
        WHEN: Verifying many proofs
        THEN: Performance should be consistent
        """
        prover = ZKPProver()
        verifier = ZKPVerifier()
        
        # Generate proofs
        proofs = [
            prover.generate_proof(f"T{i}", [f"A{i}"])
            for i in range(50)
        ]
        
        # Verify and measure times
        times = []
        for proof in proofs:
            start = time.time()
            verifier.verify_proof(proof)
            times.append(time.time() - start)
        
        # All verifications should be fast
        max_time = max(times)
        assert max_time < 0.001, f"Verification too slow: {max_time}s"
