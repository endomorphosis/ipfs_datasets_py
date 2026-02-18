"""
Comprehensive tests for Zero-Knowledge Proof (ZKP) module.

Tests cover:
    - ZKP proof generation
    - ZKP proof verification
    - Circuit construction
    - Performance characteristics
    - Integration scenarios
"""

import pytest
import time
from typing import List

from ipfs_datasets_py.logic.zkp import (
    ZKPProver,
    ZKPVerifier,
    ZKPCircuit,
    ZKPProof,
    ZKPError,
    create_implication_circuit,
)


class TestZKPProver:
    """Test ZKPProver functionality."""
    
    def test_initialization(self):
        """
        GIVEN: ZKPProver class
        WHEN: Initializing prover
        THEN: Prover is created with correct defaults
        """
        prover = ZKPProver()
        assert prover.security_level == 128
        assert prover.enable_caching == True
        
        stats = prover.get_stats()
        assert stats['proofs_generated'] == 0
    
    def test_simple_proof_generation(self):
        """
        GIVEN: ZKPProver
        WHEN: Generating proof for simple theorem
        THEN: Proof is created successfully
        """
        prover = ZKPProver()
        proof = prover.generate_proof(
            theorem="Q",
            private_axioms=["P", "P -> Q"]
        )
        
        assert isinstance(proof, ZKPProof)
        assert proof.size_bytes == 160  # Simulated Groth16 size
        assert proof.public_inputs['theorem'] == "Q"
        assert proof.metadata['num_axioms'] == 2
    
    def test_proof_privacy(self):
        """
        GIVEN: ZKPProver with private axioms
        WHEN: Generating proof
        THEN: Axioms are NOT in public inputs
        """
        prover = ZKPProver()
        private_axioms = ["Secret P", "Secret Q", "P -> Q"]
        proof = prover.generate_proof(
            theorem="Q",
            private_axioms=private_axioms
        )
        
        # Check axioms are not exposed
        public_inputs = proof.public_inputs
        for axiom in private_axioms:
            assert axiom not in str(public_inputs)
        
        # Only theorem is public
        assert public_inputs['theorem'] == "Q"
    
    def test_proof_caching(self):
        """
        GIVEN: ZKPProver with caching enabled
        WHEN: Generating same proof twice
        THEN: Second generation uses cache
        """
        prover = ZKPProver(enable_caching=True)
        
        # First proof
        proof1 = prover.generate_proof(
            theorem="Q",
            private_axioms=["P", "P -> Q"]
        )
        
        # Second proof (should hit cache)
        proof2 = prover.generate_proof(
            theorem="Q",
            private_axioms=["P", "P -> Q"]
        )
        
        stats = prover.get_stats()
        assert stats['proofs_generated'] == 1
        assert stats['cache_hits'] == 1
        assert stats['cache_hit_rate'] == 0.5
    
    def test_proof_size_limit(self):
        """
        GIVEN: ZKPProver
        WHEN: Generating proofs
        THEN: All proofs are succinct (<500 bytes)
        """
        prover = ZKPProver()
        
        # Test with different complexities
        test_cases = [
            ("Q", ["P", "P -> Q"]),
            ("R", ["P", "Q", "P AND Q -> R"]),
            ("Z", ["A", "B", "C", "D", "E", "A AND B AND C AND D AND E -> Z"]),
        ]
        
        for theorem, axioms in test_cases:
            proof = prover.generate_proof(theorem=theorem, private_axioms=axioms)
            assert proof.size_bytes < 500, f"Proof too large: {proof.size_bytes} bytes"
            assert proof.size_bytes == 160  # Fixed simulated Groth16 size
    
    def test_empty_inputs_error(self):
        """
        GIVEN: ZKPProver
        WHEN: Generating proof with empty inputs
        THEN: ZKPError is raised
        """
        prover = ZKPProver()
        
        with pytest.raises(ZKPError, match="Theorem cannot be empty"):
            prover.generate_proof(theorem="", private_axioms=["P"])
        
        with pytest.raises(ZKPError, match="At least one axiom required"):
            prover.generate_proof(theorem="Q", private_axioms=[])

    def test_unknown_backend_rejected(self):
        with pytest.raises(ZKPError, match="Unknown ZKP backend"):
            ZKPProver(backend="definitely-not-a-backend")

    def test_groth16_backend_fails_closed(self):
        prover = ZKPProver(backend="groth16")
        with pytest.raises(ZKPError, match="Groth16 backend is not implemented"):
            prover.generate_proof(theorem="Q", private_axioms=["P", "P -> Q"])


class TestZKPVerifier:
    """Test ZKPVerifier functionality."""
    
    def test_initialization(self):
        """
        GIVEN: ZKPVerifier class
        WHEN: Initializing verifier
        THEN: Verifier is created with correct defaults
        """
        verifier = ZKPVerifier()
        assert verifier.security_level == 128
        
        stats = verifier.get_stats()
        assert stats['proofs_verified'] == 0
    
    def test_valid_proof_verification(self):
        """
        GIVEN: Valid ZKP proof
        WHEN: Verifying the proof
        THEN: Verification succeeds
        """
        # Generate valid proof
        prover = ZKPProver()
        proof = prover.generate_proof(
            theorem="Q",
            private_axioms=["P", "P -> Q"]
        )
        
        # Verify proof
        verifier = ZKPVerifier()
        is_valid = verifier.verify_proof(proof)
        
        assert is_valid == True
        
        stats = verifier.get_stats()
        assert stats['proofs_verified'] == 1
        assert stats['proofs_rejected'] == 0

    def test_malformed_proof_rejected_without_crash(self):
        """
        GIVEN: A malformed/non-ZKP proof object
        WHEN: Verifying the proof
        THEN: Verification returns False (does not raise)
        """
        verifier = ZKPVerifier()

        class MalformedProof:
            pass

        assert verifier.verify_proof(MalformedProof()) is False

        stats = verifier.get_stats()
        assert stats['proofs_verified'] == 0
        assert stats['proofs_rejected'] == 1

    def test_groth16_verifier_fails_closed(self):
        prover = ZKPProver()
        proof = prover.generate_proof(theorem="Q", private_axioms=["P", "P -> Q"])

        verifier = ZKPVerifier(backend="groth16")
        with pytest.raises(ZKPError, match="Groth16 backend is not implemented"):
            verifier.verify_proof(proof)

    def test_verifier_rejects_missing_public_inputs(self):
        """
        GIVEN: A malformed proof with missing public input keys
        WHEN: Verifying
        THEN: Verification returns False
        """
        verifier = ZKPVerifier()
        
        # Create a proof missing theorem hash
        proof = ZKPProof(
            proof_data=b'x' * 160,
            public_inputs={'theorem': 'Q'},  # missing theorem_hash
            metadata={'proof_system': 'test'},
            timestamp=0.0,
            size_bytes=160
        )
        
        assert verifier.verify_proof(proof) is False
        
        stats = verifier.get_stats()
        assert stats['proofs_rejected'] >= 1

    def test_verifier_rejects_inconsistent_theorem_hash(self):
        """
        GIVEN: A proof with inconsistent theorem/hash pair
        WHEN: Verifying
        THEN: Verification returns False
        """
        verifier = ZKPVerifier()
        
        # Hash doesn't match theorem
        proof = ZKPProof(
            proof_data=b'x' * 160,
            public_inputs={
                'theorem': 'Q',
                'theorem_hash': 'wrong_hash_value'
            },
            metadata={'proof_system': 'test'},
            timestamp=0.0,
            size_bytes=160
        )
        
        assert verifier.verify_proof(proof) is False

    def test_verifier_rejects_proof_with_bad_metadata(self):
        """
        GIVEN: A proof with missing metadata field
        WHEN: Verifying
        THEN: Verification returns False (strict checking)
        """
        verifier = ZKPVerifier()
        
        # Create a proof with metadata missing proof_system
        proof = ZKPProof(
            proof_data=b'x' * 160,
            public_inputs={
                'theorem': 'Q',
                'theorem_hash': __import__('hashlib').sha256(b'Q').hexdigest()
            },
            metadata={},  # missing proof_system
            timestamp=0.0,
            size_bytes=160
        )
        
        # Should reject because metadata is incomplete
        result = verifier.verify_proof(proof)
        # Strict mode: fail if proof_system is missing
        assert result is False


class TestZKPCircuit:
    """Test ZKPCircuit functionality."""
    
    def test_circuit_initialization(self):
        """
        GIVEN: ZKPCircuit class
        WHEN: Initializing circuit
        THEN: Empty circuit is created
        """
        circuit = ZKPCircuit()
        assert circuit.num_gates() == 0
        assert circuit.num_inputs() == 0
        assert circuit.num_wires() == 0
    
    def test_add_inputs(self):
        """
        GIVEN: ZKPCircuit
        WHEN: Adding input wires
        THEN: Inputs are tracked correctly
        """
        circuit = ZKPCircuit()
        
        p_wire = circuit.add_input("P")
        q_wire = circuit.add_input("Q")
        
        assert p_wire == 0
        assert q_wire == 1
        assert circuit.num_inputs() == 2
    
    def test_and_gate(self):
        """
        GIVEN: ZKPCircuit with inputs
        WHEN: Adding AND gate
        THEN: Gate is created correctly
        """
        circuit = ZKPCircuit()
        p = circuit.add_input("P")
        q = circuit.add_input("Q")
        result = circuit.add_and_gate(p, q)
        
        assert circuit.num_gates() == 1
        assert result == 2  # Third wire


class TestZKPIntegration:
    """Test ZKP integration scenarios."""
    
    def test_end_to_end_workflow(self):
        """
        GIVEN: Complete ZKP system
        WHEN: Proving and verifying theorem
        THEN: Full workflow works correctly
        """
        # Setup
        prover = ZKPProver()
        verifier = ZKPVerifier()
        
        # Prove
        proof = prover.generate_proof(
            theorem="Socrates is mortal",
            private_axioms=[
                "Socrates is human",
                "All humans are mortal"
            ]
        )
        
        # Verify
        is_valid = verifier.verify_proof(proof)
        assert is_valid == True
        
        # Check privacy
        assert "Socrates is human" not in str(proof.public_inputs)
        assert "All humans are mortal" not in str(proof.public_inputs)
    
    def test_proof_serialization(self):
        """
        GIVEN: ZKP proof
        WHEN: Converting to/from dict
        THEN: Proof is preserved correctly
        """
        prover = ZKPProver()
        original_proof = prover.generate_proof(
            theorem="Q",
            private_axioms=["P", "P -> Q"]
        )
        
        # Serialize
        proof_dict = original_proof.to_dict()
        
        # Deserialize
        restored_proof = ZKPProof.from_dict(proof_dict)
        
        # Verify restored proof
        verifier = ZKPVerifier()
        assert verifier.verify_proof(restored_proof) == True

    def test_proof_serialization_preserves_fields(self):
        """
        GIVEN: ZKP proof with metadata
        WHEN: Serializing and deserializing
        THEN: All fields match exactly
        """
        prover = ZKPProver()
        original = prover.generate_proof(
            theorem="Q",
            private_axioms=["P", "P -> Q"],
            metadata={"custom_field": "custom_value"}
        )
        
        # Round-trip
        proof_dict = original.to_dict()
        restored = ZKPProof.from_dict(proof_dict)
        
        # Check all fields
        assert restored.proof_data == original.proof_data
        assert restored.public_inputs == original.public_inputs
        assert restored.metadata == original.metadata
        assert restored.timestamp == original.timestamp
        assert restored.size_bytes == original.size_bytes

    def test_proof_dict_hex_encoding_stability(self):
        """
        GIVEN: Proof with binary data
        WHEN: Serializing to dict (which hex-encodes proof_data)
        THEN: Hex encoding is stable and reversible
        """
        prover = ZKPProver()
        proof = prover.generate_proof(
            theorem="Q",
            private_axioms=["P", "P -> Q"]
        )
        
        original_bytes = proof.proof_data
        proof_dict = proof.to_dict()
        restored = ZKPProof.from_dict(proof_dict)
        
        assert restored.proof_data == original_bytes
        assert proof_dict['proof_data'] == original_bytes.hex()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
