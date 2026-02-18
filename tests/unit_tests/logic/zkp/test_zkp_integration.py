#!/usr/bin/env python3
"""
ZKP Integration Tests

This module provides integration tests for the ZKP module, testing its
integration with other components and realistic use cases.

Run with: pytest tests/unit_tests/logic/zkp/test_zkp_integration.py -v
"""

import os
import pytest
import json
import hashlib
from ipfs_datasets_py.logic.zkp import ZKPProver, ZKPVerifier, ZKPProof


class MockIPFSClient:
    """Mock IPFS client for integration testing."""
    
    def __init__(self):
        self.storage = {}
    
    def add_json(self, data):
        json_str = json.dumps(data, sort_keys=True)
        cid = hashlib.sha256(json_str.encode()).hexdigest()[:46]
        self.storage[cid] = data
        return cid
    
    def get_json(self, cid):
        return self.storage.get(cid)


class TestZKPIntegration:
    """Integration tests for ZKP module."""
    
    def test_end_to_end_workflow(self):
        """
        GIVEN: ZKP prover and verifier
        WHEN: Generating and verifying a proof
        THEN: Complete workflow succeeds
        """
        # Create prover
        prover = ZKPProver()
        
        # Generate proof
        theorem = "Conclusion Q"
        axioms = ["Premise P", "Implication P -> Q"]
        proof = prover.generate_proof(theorem, axioms)
        
        # Create verifier
        verifier = ZKPVerifier()
        
        # Verify proof
        is_valid = verifier.verify_proof(proof)
        
        assert is_valid, "End-to-end workflow failed"
        assert proof.public_inputs['theorem'] == theorem
    
    def test_proof_serialization(self):
        """
        GIVEN: A generated proof
        WHEN: Serializing to dict and back
        THEN: Round-trip succeeds and proof still verifies
        """
        prover = ZKPProver()
        verifier = ZKPVerifier()
        
        # Generate proof
        theorem = "Result R"
        axioms = ["Fact A", "Fact B", "A AND B implies R"]
        proof = prover.generate_proof(theorem, axioms)
        
        # Serialize to dict
        proof_dict = proof.to_dict()
        assert 'proof_data' in proof_dict
        assert 'public_inputs' in proof_dict
        
        # Deserialize
        proof_restored = ZKPProof.from_dict(proof_dict)
        
        # Verify restored proof
        is_valid = verifier.verify_proof(proof_restored)
        assert is_valid, "Deserialized proof failed verification"
    
    def test_ipfs_storage_integration(self):
        """
        GIVEN: Mock IPFS client and a proof
        WHEN: Storing and retrieving proof from IPFS
        THEN: Retrieved proof still verifies
        """
        ipfs = MockIPFSClient()
        prover = ZKPProver()
        verifier = ZKPVerifier()
        
        # Generate proof
        theorem = "Data is valid"
        axioms = ["Signature valid", "Timestamp valid", "Hash valid"]
        proof = prover.generate_proof(theorem, axioms)
        
        # Store in IPFS
        proof_dict = proof.to_dict()
        cid = ipfs.add_json(proof_dict)
        assert cid is not None
        
        # Retrieve from IPFS
        retrieved_dict = ipfs.get_json(cid)
        assert retrieved_dict is not None
        
        # Restore proof
        retrieved_proof = ZKPProof.from_dict(retrieved_dict)
        
        # Verify retrieved proof
        is_valid = verifier.verify_proof(retrieved_proof)
        assert is_valid, "IPFS integration failed"
    
    def test_proof_chain_creation(self):
        """
        GIVEN: Multiple related proofs
        WHEN: Creating a chain of proofs
        THEN: All proofs in chain verify
        """
        prover = ZKPProver()
        verifier = ZKPVerifier()
        
        # Create proof chain
        proofs = []
        
        # Proof 1: Block 1 valid
        proof1 = prover.generate_proof(
            "Block 1 is valid",
            ["Genesis hash correct", "Transactions valid"]
        )
        proofs.append(proof1)
        
        # Proof 2: Block 2 valid (depends on block 1)
        proof2 = prover.generate_proof(
            "Block 2 is valid",
            ["Previous block hash correct", "Transactions valid"]
        )
        proofs.append(proof2)
        
        # Proof 3: Block 3 valid (depends on block 2)
        proof3 = prover.generate_proof(
            "Block 3 is valid",
            ["Previous block hash correct", "Transactions valid"]
        )
        proofs.append(proof3)
        
        # Verify all proofs
        for i, proof in enumerate(proofs):
            is_valid = verifier.verify_proof(proof)
            assert is_valid, f"Proof {i+1} in chain failed"
    
    def test_backend_switching(self):
        """
        GIVEN: Different backend options
        WHEN: Creating provers with different backends
        THEN: Simulated backend works, groth16 fails gracefully
        """
        # Simulated backend works
        prover_sim = ZKPProver(backend="simulated")
        proof = prover_sim.generate_proof("Test", ["Axiom 1"])
        
        verifier_sim = ZKPVerifier(backend="simulated")
        assert verifier_sim.verify_proof(proof)
        
        # Groth16 backend fails closed (not implemented)
        from ipfs_datasets_py.logic.zkp import ZKPError
        with pytest.raises(ZKPError, match="Groth16"):
            prover_groth = ZKPProver(backend="groth16")
            prover_groth.generate_proof("Test", ["Axiom 1"])

    @pytest.mark.skipif(
        os.environ.get("IPFS_DATASETS_ENABLE_GROTH16", "").strip() not in {"1", "true", "TRUE", "yes", "YES"},
        reason="Groth16 backend is disabled by default",
    )
    def test_groth16_end_to_end_when_enabled(self):
        """Runs an end-to-end prove→verify using the Rust Groth16 binary.

        This test is opt-in and will be skipped unless:
        - IPFS_DATASETS_ENABLE_GROTH16=1 (or true/yes)
        - A groth16 binary is discoverable (or overridden via env var)
        """
        from ipfs_datasets_py.logic.zkp.backends.groth16_ffi import Groth16Backend as Groth16FFIBackend

        backend = Groth16FFIBackend()
        if not backend.binary_path:
            pytest.skip("Groth16 binary not available")

        prover = ZKPProver(backend="groth16")
        verifier = ZKPVerifier(backend="groth16")

        proof = prover.generate_proof("Q", ["P", "P -> Q"])
        assert verifier.verify_proof(proof)
    
    def test_proof_caching_integration(self):
        """
        GIVEN: Prover with caching enabled
        WHEN: Generating same proof twice
        THEN: Second generation uses cache
        """
        prover = ZKPProver(enable_caching=True)
        
        theorem = "Cached theorem"
        axioms = ["Axiom A", "Axiom B"]
        
        # First proof (not cached)
        proof1 = prover.generate_proof(theorem, axioms)
        stats1 = prover.get_stats()
        
        # Second proof (cached)
        proof2 = prover.generate_proof(theorem, axioms)
        stats2 = prover.get_stats()
        
        # Cache should have been hit
        assert stats2['cache_hits'] > stats1['cache_hits']
        assert stats2['proofs_generated'] == stats1['proofs_generated']
    
    def test_metadata_propagation(self):
        """
        GIVEN: Proof with custom metadata
        WHEN: Generating proof with metadata
        THEN: Metadata is preserved in proof
        """
        prover = ZKPProver()
        
        metadata = {
            'version': '1.0',
            'purpose': 'test',
            'tags': ['integration', 'test']
        }
        
        proof = prover.generate_proof(
            "Test theorem",
            ["Test axiom"],
            metadata=metadata
        )
        
        # Check metadata preserved
        assert 'version' in proof.metadata
        assert proof.metadata['version'] == '1.0'
        assert 'purpose' in proof.metadata
        assert proof.metadata['purpose'] == 'test'
    
    def test_multiple_verifiers_same_proof(self):
        """
        GIVEN: One proof and multiple verifiers
        WHEN: Multiple verifiers verify same proof
        THEN: All verifiers accept the proof
        """
        prover = ZKPProver()
        proof = prover.generate_proof("Theorem", ["Axiom 1", "Axiom 2"])
        
        # Create multiple verifiers
        verifiers = [ZKPVerifier() for _ in range(5)]
        
        # All should verify successfully
