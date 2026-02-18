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
from ipfs_datasets_py.logic.zkp import BooleanCircuit, ArithmeticCircuit, ZKPProver, ZKPVerifier


class TestZKPPerformance:
    """Performance benchmarks for ZKP module."""
    
    def test_proof_generation_performance(self, benchmark_if_available):
        """Benchmark proof generation time."""
        # Build simple circuit
        circuit = BooleanCircuit()
        w1, w2, w3 = [circuit.add_wire() for _ in range(3)]
        circuit.add_gate('AND', [w1, w2], w3)
        circuit.set_private_input(w1)
        circuit.set_private_input(w2)
        circuit.set_public_input(w3)
        
        prover = ZKPProver(circuit)
        witness = {w1: True, w2: True}
        
        # Measure generation time
        times = []
        for _ in range(100):
            start = time.time()
            proof = prover.generate_proof(witness, [True])
            times.append(time.time() - start)
        
        mean_time = statistics.mean(times)
        std_time = statistics.stdev(times)
        
        # Assert performance is reasonable (< 10ms for simple circuit)
        assert mean_time < 0.01, f"Proof generation too slow: {mean_time*1000:.2f}ms"
        
        print(f"\nProof Generation Performance:")
        print(f"  Mean: {mean_time*1000:.2f}ms")
        print(f"  Std:  {std_time*1000:.2f}ms")
        print(f"  Min:  {min(times)*1000:.2f}ms")
        print(f"  Max:  {max(times)*1000:.2f}ms")
    
    def test_proof_verification_performance(self, benchmark_if_available):
        """Benchmark proof verification time."""
        circuit = BooleanCircuit()
        w1, w2, w3 = [circuit.add_wire() for _ in range(3)]
        circuit.add_gate('AND', [w1, w2], w3)
        circuit.set_private_input(w1)
        circuit.set_private_input(w2)
        circuit.set_public_input(w3)
        
        prover = ZKPProver(circuit)
        verifier = ZKPVerifier(prover.get_verification_key())
        witness = {w1: True, w2: True}
        proof = prover.generate_proof(witness, [True])
        
        # Measure verification time
        times = []
        for _ in range(100):
            start = time.time()
            is_valid = verifier.verify_proof(proof, [True])
            times.append(time.time() - start)
            assert is_valid
        
        mean_time = statistics.mean(times)
        
        # Verification should be faster than generation
        assert mean_time < 0.005, f"Verification too slow: {mean_time*1000:.2f}ms"
        
        print(f"\nProof Verification Performance:")
        print(f"  Mean: {mean_time*1000:.2f}ms")
        print(f"  Std:  {statistics.stdev(times)*1000:.2f}ms")
    
    def test_circuit_size_scaling(self):
        """Test performance scaling with circuit size."""
        results = []
        
        for num_gates in [10, 50, 100, 200]:
            # Build circuit with num_gates AND gates
            circuit = BooleanCircuit()
            wires = [circuit.add_wire() for _ in range(num_gates + 1)]
            
            for w in wires[:-1]:
                circuit.set_private_input(w)
            
            for i in range(num_gates):
                circuit.add_gate('AND', [wires[i], wires[i]], wires[-1])
            
            circuit.set_public_input(wires[-1])
            
            # Measure performance
            prover = ZKPProver(circuit)
            witness = {w: True for w in wires[:-1]}
            
            start = time.time()
            proof = prover.generate_proof(witness, [True])
            prove_time = time.time() - start
            
            verifier = ZKPVerifier(prover.get_verification_key())
            start = time.time()
            is_valid = verifier.verify_proof(proof, [True])
            verify_time = time.time() - start
            
            assert is_valid
            results.append((num_gates, prove_time, verify_time))
        
        print(f"\nCircuit Size Scaling:")
        print(f"Gates | Prove (ms) | Verify (ms)")
        print("-" * 40)
        for gates, prove_t, verify_t in results:
            print(f"{gates:5d} | {prove_t*1000:10.2f} | {verify_t*1000:11.2f}")
        
        # Verify roughly linear scaling
        # (Doubled gates should not more than triple time)
        if len(results) >= 2:
            ratio = results[-1][1] / results[0][1]
            gate_ratio = results[-1][0] / results[0][0]
            assert ratio < gate_ratio * 1.5, "Non-linear scaling detected"
    
    def test_batch_verification_performance(self):
        """Test performance of batch verification."""
        circuit = BooleanCircuit()
        w1, w2, w3 = [circuit.add_wire() for _ in range(3)]
        circuit.add_gate('AND', [w1, w2], w3)
        circuit.set_private_input(w1)
        circuit.set_private_input(w2)
        circuit.set_public_input(w3)
        
        prover = ZKPProver(circuit)
        verifier = ZKPVerifier(prover.get_verification_key())
        
        # Generate batch of proofs
        num_proofs = 100
        proofs = []
        for i in range(num_proofs):
            witness = {w1: True, w2: i % 2 == 0}
            expected = [i % 2 == 0]
            proof = prover.generate_proof(witness, expected)
            proofs.append((proof, expected))
        
        # Measure batch verification
        start = time.time()
        results = [verifier.verify_proof(p, pi) for p, pi in proofs]
        batch_time = time.time() - start
        
        assert all(results)
        avg_time = batch_time / num_proofs
        
        print(f"\nBatch Verification ({num_proofs} proofs):")
        print(f"  Total time: {batch_time*1000:.2f}ms")
        print(f"  Average:    {avg_time*1000:.2f}ms per proof")
        print(f"  Throughput: {num_proofs/batch_time:.0f} proofs/sec")
        
        # Should be < 1ms per proof on average
        assert avg_time < 0.001, f"Batch verification too slow: {avg_time*1000:.2f}ms"
    
    def test_arithmetic_circuit_performance(self):
        """Benchmark arithmetic circuit performance."""
        circuit = ArithmeticCircuit()
        x = circuit.create_variable('x', is_public=False)
        y = circuit.create_variable('y', is_public=False)
        result = circuit.create_variable('result', is_public=True)
        
        # Single multiplication constraint
        circuit.add_constraint(
            a={'x': 1},
            b={'y': 1},
            c={'result': 1}
        )
        
        prover = ZKPProver(circuit)
        witness = {'x': 3, 'y': 5, 'result': 15}
        
        # Measure performance
        times = []
        for _ in range(50):
            start = time.time()
            proof = prover.generate_proof(witness, [15])
            times.append(time.time() - start)
        
        mean_time = statistics.mean(times)
        
        print(f"\nArithmetic Circuit Performance:")
        print(f"  Mean: {mean_time*1000:.2f}ms")
        
        # Should be comparable to boolean circuits
        assert mean_time < 0.01, f"Arithmetic proving too slow: {mean_time*1000:.2f}ms"
    
    def test_memory_usage(self):
        """Test memory usage doesn't grow excessively."""
        import sys
        
        circuit = BooleanCircuit()
        w1, w2, w3 = [circuit.add_wire() for _ in range(3)]
        circuit.add_gate('AND', [w1, w2], w3)
        circuit.set_private_input(w1)
        circuit.set_private_input(w2)
        circuit.set_public_input(w3)
        
        prover = ZKPProver(circuit)
        witness = {w1: True, w2: True}
        
        # Generate many proofs and check memory
        proofs = []
        for _ in range(1000):
            proof = prover.generate_proof(witness, [True])
            proofs.append(proof)
        
        # Each proof should be < 1KB
        proof_size = sys.getsizeof(str(proof))
        assert proof_size < 1000, f"Proof too large: {proof_size} bytes"
        
        print(f"\nMemory Usage:")
        print(f"  Proof size: ~{proof_size} bytes")
        print(f"  1000 proofs: ~{proof_size * 1000 / 1024:.1f} KB")


@pytest.fixture
def benchmark_if_available():
    """Fixture that works with or without pytest-benchmark."""
    try:
        import pytest_benchmark
        return True
    except ImportError:
        return False


if __name__ == '__main__':
    # Run benchmarks directly
    print("Running ZKP Performance Benchmarks...")
    test = TestZKPPerformance()
    
    print("\n" + "="*60)
    test.test_proof_generation_performance(False)
    print("="*60)
    test.test_proof_verification_performance(False)
    print("="*60)
    test.test_circuit_size_scaling()
    print("="*60)
    test.test_batch_verification_performance()
    print("="*60)
    test.test_arithmetic_circuit_performance()
    print("="*60)
    test.test_memory_usage()
    print("="*60)
    
    print("\n✓ All performance benchmarks passed!")
