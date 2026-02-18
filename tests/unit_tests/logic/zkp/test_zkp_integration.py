#!/usr/bin/env python3
"""
ZKP Integration Tests

This module provides integration tests for the ZKP module, testing its
integration with other components and realistic use cases.

Run with: pytest tests/unit_tests/logic/zkp/test_zkp_integration.py -v
"""

import pytest
import json
import hashlib
from ipfs_datasets_py.logic.zkp import BooleanCircuit, ArithmeticCircuit, ZKPProver, ZKPVerifier


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
        """Test complete proof generation and verification workflow."""
        # 1. Define circuit
        circuit = BooleanCircuit()
        w1, w2, w3 = [circuit.add_wire() for _ in range(3)]
        circuit.add_gate('AND', [w1, w2], w3)
        circuit.set_private_input(w1)
        circuit.set_private_input(w2)
        circuit.set_public_input(w3)
        
        # 2. Create prover
        prover = ZKPProver(circuit)
        vk = prover.get_verification_key()
        
        # 3. Generate proof
        witness = {w1: True, w2: True}
        proof = prover.generate_proof(witness, [True])
        
        # 4. Create verifier
        verifier = ZKPVerifier(vk)
        
        # 5. Verify proof
        is_valid = verifier.verify_proof(proof, [True])
        
        assert is_valid, "End-to-end workflow failed"
    
    def test_proof_serialization(self):
        """Test proof can be serialized and deserialized."""
        circuit = BooleanCircuit()
        w1, w2, w3 = [circuit.add_wire() for _ in range(3)]
        circuit.add_gate('OR', [w1, w2], w3)
        circuit.set_private_input(w1)
        circuit.set_private_input(w2)
        circuit.set_public_input(w3)
        
        prover = ZKPProver(circuit)
        verifier = ZKPVerifier(prover.get_verification_key())
        
        # Generate proof
        witness = {w1: True, w2: False}
        proof = prover.generate_proof(witness, [True])
        
        # Serialize to JSON
        proof_json = json.dumps(proof)
        
        # Deserialize
        proof_restored = json.loads(proof_json)
        
        # Verify restored proof
        is_valid = verifier.verify_proof(proof_restored, [True])
        assert is_valid, "Deserialized proof failed verification"
    
    def test_ipfs_storage_integration(self):
        """Test integration with IPFS storage."""
        ipfs = MockIPFSClient()
        
        # Generate proof
        circuit = BooleanCircuit()
        w = circuit.add_wire()
        circuit.set_private_input(w)
        
        prover = ZKPProver(circuit)
        proof = prover.generate_proof({w: True}, [])
        vk = prover.get_verification_key()
        
        # Store in IPFS
        package = {'proof': proof, 'vk': vk}
        cid = ipfs.add_json(package)
        
        # Retrieve from IPFS
        retrieved = ipfs.get_json(cid)
        
        # Verify retrieved proof
        verifier = ZKPVerifier(retrieved['vk'])
        is_valid = verifier.verify_proof(retrieved['proof'], [])
        
        assert is_valid, "IPFS integration failed"
    
    def test_proof_chain_creation(self):
        """Test creating a chain of related proofs."""
        circuit = BooleanCircuit()
        w1, w2, w3 = [circuit.add_wire() for _ in range(3)]
        circuit.add_gate('AND', [w1, w2], w3)
        circuit.set_private_input(w1)
        circuit.set_private_input(w2)
        circuit.set_public_input(w3)
        
        prover = ZKPProver(circuit)
        verifier = ZKPVerifier(prover.get_verification_key())
        
        # Create chain of 5 proofs
        chain = []
        for i in range(5):
            witness = {w1: True, w2: i % 2 == 0}
            expected = [i % 2 == 0]
            proof = prover.generate_proof(witness, expected)
            
            # Add previous proof hash to metadata
            if chain:
                proof['previous_hash'] = hashlib.sha256(
                    json.dumps(chain[-1]).encode()
                ).hexdigest()
            
            chain.append(proof)
        
        # Verify chain integrity
        for i, proof in enumerate(chain):
            # Verify proof itself
            is_valid = verifier.verify_proof(proof, [i % 2 == 0])
            assert is_valid, f"Proof {i} in chain invalid"
            
            # Verify chain link
            if i > 0:
                prev_hash = hashlib.sha256(
                    json.dumps(chain[i-1]).encode()
                ).hexdigest()
                assert proof['previous_hash'] == prev_hash, f"Chain broken at {i}"
    
    def test_multiple_verifiers(self):
        """Test multiple verifiers can verify same proof."""
        circuit = BooleanCircuit()
        w1, w2, w3 = [circuit.add_wire() for _ in range(3)]
        circuit.add_gate('OR', [w1, w2], w3)
        circuit.set_private_input(w1)
        circuit.set_private_input(w2)
        circuit.set_public_input(w3)
        
        prover = ZKPProver(circuit)
        vk = prover.get_verification_key()
        
        # Generate proof
        witness = {w1: False, w2: True}
        proof = prover.generate_proof(witness, [True])
        
        # Create multiple independent verifiers
        verifiers = [ZKPVerifier(vk) for _ in range(5)]
        
        # All should verify successfully
        for i, verifier in enumerate(verifiers):
            is_valid = verifier.verify_proof(proof, [True])
            assert is_valid, f"Verifier {i} failed"
    
    def test_proof_reuse_prevention(self):
        """Test that proofs are bound to specific public inputs."""
        circuit = BooleanCircuit()
        w1, w2, w3 = [circuit.add_wire() for _ in range(3)]
        circuit.add_gate('AND', [w1, w2], w3)
        circuit.set_private_input(w1)
        circuit.set_private_input(w2)
        circuit.set_public_input(w3)
        
        prover = ZKPProver(circuit)
        verifier = ZKPVerifier(prover.get_verification_key())
        
        # Generate proof for True
        witness_true = {w1: True, w2: True}
        proof_true = prover.generate_proof(witness_true, [True])
        
        # Should verify for True
        assert verifier.verify_proof(proof_true, [True])
        
        # Should NOT verify for False (proof reuse)
        assert not verifier.verify_proof(proof_true, [False])
    
    def test_complex_circuit_integration(self):
        """Test integration with complex multi-gate circuit."""
        circuit = BooleanCircuit()
        
        # Build XOR circuit
        a, b = circuit.add_wire(), circuit.add_wire()
        a_or_b = circuit.add_wire()
        a_and_b = circuit.add_wire()
        not_a_and_b = circuit.add_wire()
        result = circuit.add_wire()
        
        circuit.set_private_input(a)
        circuit.set_private_input(b)
        circuit.add_gate('OR', [a, b], a_or_b)
        circuit.add_gate('AND', [a, b], a_and_b)
        circuit.add_gate('NOT', [a_and_b], not_a_and_b)
        circuit.add_gate('AND', [a_or_b, not_a_and_b], result)
        circuit.set_public_input(result)
        
        prover = ZKPProver(circuit)
        verifier = ZKPVerifier(prover.get_verification_key())
        
        # Test all XOR cases
        test_cases = [
            ((False, False), False),
            ((False, True), True),
            ((True, False), True),
            ((True, True), False),
        ]
        
        for (a_val, b_val), expected in test_cases:
            witness = {a: a_val, b: b_val}
            proof = prover.generate_proof(witness, [expected])
            is_valid = verifier.verify_proof(proof, [expected])
            assert is_valid, f"XOR({a_val}, {b_val}) = {expected} failed"
    
    def test_arithmetic_circuit_integration(self):
        """Test arithmetic circuit integration."""
        circuit = ArithmeticCircuit()
        
        # x² + 3x - 10 = 0
        x = circuit.create_variable('x', is_public=False)
        x_squared = circuit.create_variable('x_squared', is_public=False)
        three_x = circuit.create_variable('three_x', is_public=False)
        result = circuit.create_variable('result', is_public=True)
        
        # Constraints
        circuit.add_constraint(a={'x': 1}, b={'x': 1}, c={'x_squared': 1})
        circuit.add_constraint(a={'x': 3}, b={}, c={'three_x': 1})
        
        prover = ZKPProver(circuit)
        verifier = ZKPVerifier(prover.get_verification_key())
        
        # Test solution x = 2
        witness = {'x': 2, 'x_squared': 4, 'three_x': 6, 'result': 0}
        proof = prover.generate_proof(witness, [0])
        is_valid = verifier.verify_proof(proof, [0])
        
        assert is_valid, "Arithmetic circuit integration failed"
    
    def test_concurrent_proof_generation(self):
        """Test multiple proofs can be generated concurrently."""
        circuit = BooleanCircuit()
        w1, w2, w3 = [circuit.add_wire() for _ in range(3)]
        circuit.add_gate('AND', [w1, w2], w3)
        circuit.set_private_input(w1)
        circuit.set_private_input(w2)
        circuit.set_public_input(w3)
        
        prover = ZKPProver(circuit)
        verifier = ZKPVerifier(prover.get_verification_key())
        
        # Generate multiple proofs "concurrently" (sequentially in this test)
        witnesses = [
            ({w1: True, w2: True}, [True]),
            ({w1: True, w2: False}, [False]),
            ({w1: False, w2: True}, [False]),
            ({w1: False, w2: False}, [False]),
        ]
        
        proofs = [prover.generate_proof(w, pi) for w, pi in witnesses]
        
        # Verify all
        for proof, (_, expected) in zip(proofs, witnesses):
            is_valid = verifier.verify_proof(proof, expected)
            assert is_valid, "Concurrent proof generation produced invalid proof"
    
    def test_proof_metadata_preservation(self):
        """Test that custom metadata is preserved in proofs."""
        circuit = BooleanCircuit()
        w = circuit.add_wire()
        circuit.set_private_input(w)
        
        prover = ZKPProver(circuit)
        proof = prover.generate_proof({w: True}, [])
        
        # Add custom metadata
        proof['custom_metadata'] = {
            'prover_id': 'Alice',
            'timestamp': '2026-02-18',
            'purpose': 'test'
        }
        
        # Serialize and deserialize
        proof_json = json.dumps(proof)
        proof_restored = json.loads(proof_json)
        
        # Check metadata preserved
        assert 'custom_metadata' in proof_restored
        assert proof_restored['custom_metadata']['prover_id'] == 'Alice'
        
        # Should still verify
        verifier = ZKPVerifier(prover.get_verification_key())
        is_valid = verifier.verify_proof(proof_restored, [])
        assert is_valid, "Proof with metadata failed verification"


if __name__ == '__main__':
    # Run integration tests directly
    print("Running ZKP Integration Tests...")
    test = TestZKPIntegration()
    
    tests = [
        ("End-to-end workflow", test.test_end_to_end_workflow),
        ("Proof serialization", test.test_proof_serialization),
        ("IPFS storage integration", test.test_ipfs_storage_integration),
        ("Proof chain creation", test.test_proof_chain_creation),
        ("Multiple verifiers", test.test_multiple_verifiers),
        ("Proof reuse prevention", test.test_proof_reuse_prevention),
        ("Complex circuit integration", test.test_complex_circuit_integration),
        ("Arithmetic circuit integration", test.test_arithmetic_circuit_integration),
        ("Concurrent proof generation", test.test_concurrent_proof_generation),
        ("Proof metadata preservation", test.test_proof_metadata_preservation),
    ]
    
    for name, test_func in tests:
        print(f"\n{'='*60}")
        print(f"Test: {name}")
        print('='*60)
        try:
            test_func()
            print(f"✓ PASSED")
        except AssertionError as e:
            print(f"✗ FAILED: {e}")
        except Exception as e:
            print(f"✗ ERROR: {e}")
    
    print("\n" + "="*60)
    print("Integration tests complete!")
    print("="*60)
