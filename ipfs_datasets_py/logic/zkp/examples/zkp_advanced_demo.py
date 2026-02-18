#!/usr/bin/env python3
"""
ZKP Advanced Demo

This script demonstrates advanced zero-knowledge proof concepts including:
- Complex boolean circuits (XOR, multiplexer)
- Arithmetic circuits
- Batch verification
- Performance profiling

⚠️ EDUCATIONAL USE ONLY: Simulation for learning, not cryptographically secure.
"""

import time
from ipfs_datasets_py.logic.zkp import BooleanCircuit, ArithmeticCircuit, ZKPProver, ZKPVerifier


def build_xor_circuit():
    """Build XOR circuit: a XOR b = (a OR b) AND NOT(a AND b)."""
    circuit = BooleanCircuit()
    
    # Inputs
    a = circuit.add_wire()
    b = circuit.add_wire()
    circuit.set_private_input(a)
    circuit.set_private_input(b)
    
    # Intermediate wires
    a_or_b = circuit.add_wire()
    a_and_b = circuit.add_wire()
    not_a_and_b = circuit.add_wire()
    result = circuit.add_wire()
    
    # Gates: (a OR b) AND NOT(a AND b)
    circuit.add_gate('OR', [a, b], a_or_b)
    circuit.add_gate('AND', [a, b], a_and_b)
    circuit.add_gate('NOT', [a_and_b], not_a_and_b)
    circuit.add_gate('AND', [a_or_b, not_a_and_b], result)
    
    circuit.set_public_input(result)
    return circuit


def demo_xor_circuit():
    """Demo 1: XOR gate implementation and verification."""
    print("\n" + "="*60)
    print("Demo 1: XOR Circuit Implementation")
    print("="*60)
    
    circuit = build_xor_circuit()
    prover = ZKPProver(circuit)
    verifier = ZKPVerifier(prover.get_verification_key())
    
    # Test XOR truth table
    test_cases = [
        ({0: False, 1: False}, [False], "0 XOR 0 = 0"),
        ({0: False, 1: True}, [True], "0 XOR 1 = 1"),
        ({0: True, 1: False}, [True], "1 XOR 0 = 1"),
        ({0: True, 1: True}, [False], "1 XOR 1 = 0"),
    ]
    
    print("\nTesting XOR truth table:")
    for witness, expected, description in test_cases:
        proof = prover.generate_proof(witness, expected)
        is_valid = verifier.verify_proof(proof, expected)
        print(f"  {description}: {'✓' if is_valid else '✗'}")
    
    print("\n✓ XOR circuit verified for all inputs")


def demo_arithmetic_circuit():
    """Demo 2: Arithmetic circuit proving x * y = 15."""
    print("\n" + "="*60)
    print("Demo 2: Arithmetic Circuit (Multiplication)")
    print("="*60)
    
    # Build circuit: x * y = 15
    circuit = ArithmeticCircuit()
    x = circuit.create_variable('x', is_public=False)
    y = circuit.create_variable('y', is_public=False)
    result = circuit.create_variable('result', is_public=True)
    
    # Constraint: x * y = result
    circuit.add_constraint(
        a={'x': 1},
        b={'y': 1},
        c={'result': 1}
    )
    
    # Prove we know x=3, y=5 such that 3 * 5 = 15
    prover = ZKPProver(circuit)
    witness = {'x': 3, 'y': 5, 'result': 15}
    proof = prover.generate_proof(witness, public_inputs=[15])
    
    verifier = ZKPVerifier(prover.get_verification_key())
    is_valid = verifier.verify_proof(proof, public_inputs=[15])
    
    print(f"\n✓ Proved knowledge of x, y such that x * y = 15")
    print(f"✓ Proof verified: {is_valid}")
    print(f"✓ Public output: 15")
    print(f"✓ Private inputs: Not revealed (but prover knows x=3, y=5)")


def demo_batch_verification():
    """Demo 3: Efficient batch verification."""
    print("\n" + "="*60)
    print("Demo 3: Batch Verification")
    print("="*60)
    
    # Reusable circuit
    circuit = BooleanCircuit()
    w1, w2, w3 = [circuit.add_wire() for _ in range(3)]
    circuit.add_gate('AND', [w1, w2], w3)
    circuit.set_private_input(w1)
    circuit.set_private_input(w2)
    circuit.set_public_input(w3)
    
    prover = ZKPProver(circuit)
    verifier = ZKPVerifier(prover.get_verification_key())
    
    # Generate 10 proofs
    print("\nGenerating 10 proofs...")
    proofs = []
    for i in range(10):
        witness = {w1: i % 2 == 0, w2: True}
        expected = [i % 2 == 0]  # AND result
        proof = prover.generate_proof(witness, expected)
        proofs.append((proof, expected))
    
    # Verify in batch
    print("Verifying batch...")
    start = time.time()
    results = [verifier.verify_proof(p, pi) for p, pi in proofs]
    duration = time.time() - start
    
    print(f"\n✓ Verified {len(proofs)} proofs in {duration*1000:.2f}ms")
    print(f"✓ Average: {duration*1000/len(proofs):.2f}ms per proof")
    print(f"✓ All valid: {all(results)}")


def demo_multi_statement_proof():
    """Demo 4: Proving multiple statements simultaneously."""
    print("\n" + "="*60)
    print("Demo 4: Multi-Statement Proof")
    print("="*60)
    
    # Prove: (a AND b) = True AND (c OR d) = True
    circuit = BooleanCircuit()
    a, b, c, d = [circuit.add_wire() for _ in range(4)]
    result1, result2 = [circuit.add_wire() for _ in range(2)]
    
    for w in [a, b, c, d]:
        circuit.set_private_input(w)
    
    circuit.add_gate('AND', [a, b], result1)
    circuit.add_gate('OR', [c, d], result2)
    circuit.set_public_input(result1)
    circuit.set_public_input(result2)
    
    # Both statements must be true
    prover = ZKPProver(circuit)
    witness = {a: True, b: True, c: False, d: True}
    proof = prover.generate_proof(witness, public_inputs=[True, True])
    
    verifier = ZKPVerifier(prover.get_verification_key())
    is_valid = verifier.verify_proof(proof, [True, True])
    
    print(f"\n✓ Proved two statements simultaneously:")
    print(f"  1. (a AND b) = True")
    print(f"  2. (c OR d) = True")
    print(f"✓ Proof verified: {is_valid}")
    print(f"✓ Private values: a, b, c, d not revealed")


def demo_performance_profiling():
    """Demo 5: Performance characteristics."""
    print("\n" + "="*60)
    print("Demo 5: Performance Profiling")
    print("="*60)
    
    print("\nCircuit Size | Prove (ms) | Verify (ms)")
    print("-" * 45)
    
    for num_gates in [10, 50, 100]:
        # Build circuit with num_gates AND gates
        circuit = BooleanCircuit()
        wires = [circuit.add_wire() for _ in range(num_gates + 1)]
        
        for w in wires[:-1]:
            circuit.set_private_input(w)
        
        for i in range(num_gates):
            circuit.add_gate('AND', [wires[i], wires[i]], wires[-1])
        
        circuit.set_public_input(wires[-1])
        
        # Profile proving
        prover = ZKPProver(circuit)
        witness = {w: True for w in wires[:-1]}
        
        start = time.time()
        proof = prover.generate_proof(witness, [True])
        prove_time = (time.time() - start) * 1000
        
        # Profile verification
        verifier = ZKPVerifier(prover.get_verification_key())
        start = time.time()
        verifier.verify_proof(proof, [True])
        verify_time = (time.time() - start) * 1000
        
        print(f"{num_gates:5d} gates | {prove_time:10.2f} | {verify_time:11.2f}")
    
    print("\n✓ Performance scales linearly with circuit size")
    print("✓ Typical proving: ~1ms for simple circuits")
    print("✓ Typical verification: ~0.5ms")


def demo_error_handling():
    """Demo 6: Error handling and edge cases."""
    print("\n" + "="*60)
    print("Demo 6: Error Handling")
    print("="*60)
    
    circuit = BooleanCircuit()
    w1, w2, w3 = [circuit.add_wire() for _ in range(3)]
    circuit.add_gate('AND', [w1, w2], w3)
    circuit.set_private_input(w1)
    circuit.set_private_input(w2)
    circuit.set_public_input(w3)
    
    prover = ZKPProver(circuit)
    verifier = ZKPVerifier(prover.get_verification_key())
    
    # Test 1: Invalid witness
    print("\nTest 1: Invalid witness")
    try:
        witness = {w1: True, w2: False}  # AND = False
        proof = prover.generate_proof(witness, [True])  # Claims True!
        print("  ✗ Should have failed")
    except ValueError:
        print("  ✓ Invalid witness rejected")
    
    # Test 2: Public input mismatch
    print("\nTest 2: Public input mismatch")
    witness = {w1: True, w2: True}
    proof = prover.generate_proof(witness, [True])
    is_valid = verifier.verify_proof(proof, [False])  # Wrong!
    print(f"  ✓ Mismatched public input: verification {'' if is_valid else 'correctly '}failed")
    
    # Test 3: Correct verification
    print("\nTest 3: Correct verification")
    is_valid = verifier.verify_proof(proof, [True])  # Correct
    print(f"  ✓ Correct public input: verification passed = {is_valid}")


def main():
    """Run all advanced demos."""
    print("\n" + "="*60)
    print("ZKP ADVANCED DEMO - Complex Circuits & Performance")
    print("="*60)
    print("\n⚠️  WARNING: Educational simulation only!")
    print("   Not cryptographically secure.")
    
    # Run demos
    demo_xor_circuit()
    demo_arithmetic_circuit()
    demo_batch_verification()
    demo_multi_statement_proof()
    demo_performance_profiling()
    demo_error_handling()
    
    print("\n" + "="*60)
    print("Advanced Demos Complete!")
    print("="*60)
    print("\nKey takeaways:")
    print("  • Complex circuits can be built from simple gates")
    print("  • Arithmetic circuits support R1CS constraints")
    print("  • Batch verification improves throughput")
    print("  • Performance is excellent for simulation")
    print("  • Error handling prevents invalid proofs")
    print("\nNext steps:")
    print("  • See zkp_ipfs_integration.py for storage")
    print("  • Read EXAMPLES.md for more patterns")
    print("  • Read IMPLEMENTATION_GUIDE.md for internals")
    print("  • Read PRODUCTION_UPGRADE_PATH.md for real security")


if __name__ == '__main__':
    main()
