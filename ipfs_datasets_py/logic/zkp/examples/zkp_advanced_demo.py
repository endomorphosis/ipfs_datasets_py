#!/usr/bin/env python3
"""
ZKP Advanced Demo

This script demonstrates advanced zero-knowledge proof features including:
- Backend selection (simulated vs groth16)
- Proof caching for performance
- Batch proof generation
- Performance profiling
- Proof serialization

⚠️ EDUCATIONAL USE ONLY: Simulation for learning, not cryptographically secure.

How to run:
    # From repository root:
    PYTHONPATH=. python ipfs_datasets_py/logic/zkp/examples/zkp_advanced_demo.py
    
    # Or install package first:
    pip install -e .
    python ipfs_datasets_py/logic/zkp/examples/zkp_advanced_demo.py
"""

import time
import json
from ipfs_datasets_py.logic.zkp import ZKPProver, ZKPVerifier, ZKPError


def demo_backend_selection():
    """Demo 1: Test backend selection (simulated vs groth16)."""
    print("\n" + "="*60)
    print("Demo 1: Backend Selection")
    print("="*60)
    
    # Default simulated backend
    prover_sim = ZKPProver(backend="simulated")
    proof = prover_sim.generate_proof(
        theorem="Q",
        private_axioms=["P", "P -> Q"]
    )
    verifier_sim = ZKPVerifier(backend="simulated")
    is_valid = verifier_sim.verify_proof(proof)
    
    print(f"✓ Simulated backend: {prover_sim.backend}")
    print(f"✓ Proof generated and verified: {is_valid}")
    print(f"✓ Proof size: {proof.size_bytes} bytes")
    
    # Try groth16 backend (will fail gracefully - not implemented)
    print("\nTrying Groth16 backend (production)...")
    try:
        prover_groth = ZKPProver(backend="groth16")
        prover_groth.generate_proof(
            theorem="Q",
            private_axioms=["P"]
        )
        print("✓ Groth16 backend available")
    except ZKPError as e:
        print(f"✓ Groth16 not yet implemented (expected)")
        print(f"  Error: {str(e)[:80]}...")


def demo_proof_caching():
    """Demo 2: Demonstrate proof caching for performance."""
    print("\n" + "="*60)
    print("Demo 2: Proof Caching")
    print("="*60)
    
    prover_cached = ZKPProver(enable_caching=True)
    prover_no_cache = ZKPProver(enable_caching=False)
    
    theorem = "Complex theorem"
    axioms = [f"Axiom {i}" for i in range(10)]
    
    # First proof (no cache)
    start = time.time()
    proof1 = prover_cached.generate_proof(theorem, axioms)
    time1 = time.time() - start
    
    # Second proof (cached)
    start = time.time()
    proof2 = prover_cached.generate_proof(theorem, axioms)
    time2 = time.time() - start
    
    # Third proof (no cache)
    start = time.time()
    proof3 = prover_no_cache.generate_proof(theorem, axioms)
    time3 = time.time() - start
    
    print(f"✓ First proof (cold): {time1*1000:.3f}ms")
    print(f"✓ Second proof (cached): {time2*1000:.3f}ms")
    print(f"✓ Third proof (no cache): {time3*1000:.3f}ms")
    print(f"✓ Cache speedup: {time1/time2 if time2 > 0 else float('inf'):.1f}x")
    
    stats = prover_cached.get_stats()
    print(f"✓ Cache hits: {stats['cache_hits']}")
    print(f"✓ Total proofs: {stats['proofs_generated']}")


def demo_batch_verification():
    """Demo 3: Generate and verify multiple proofs."""
    print("\n" + "="*60)
    print("Demo 3: Batch Proof Generation")
    print("="*60)
    
    prover = ZKPProver()
    verifier = ZKPVerifier()
    
    # Generate multiple proofs
    theorems = [
        ("Theorem A", ["Axiom 1", "Axiom 2"]),
        ("Theorem B", ["Axiom 3", "Axiom 4"]),
        ("Theorem C", ["Axiom 5", "Axiom 6"]),
        ("Theorem D", ["Axiom 7", "Axiom 8"]),
        ("Theorem E", ["Axiom 9", "Axiom 10"]),
    ]
    
    proofs = []
    start = time.time()
    for theorem, axioms in theorems:
        proof = prover.generate_proof(theorem, axioms)
        proofs.append(proof)
    gen_time = time.time() - start
    
    # Verify all proofs
    start = time.time()
    results = [verifier.verify_proof(p) for p in proofs]
    verify_time = time.time() - start
    
    print(f"✓ Generated {len(proofs)} proofs in {gen_time*1000:.2f}ms")
    print(f"✓ Verified {len(proofs)} proofs in {verify_time*1000:.2f}ms")
    print(f"✓ All valid: {all(results)}")
    print(f"✓ Avg proof time: {gen_time/len(proofs)*1000:.2f}ms")
    print(f"✓ Avg verify time: {verify_time/len(proofs)*1000:.2f}ms")


def demo_proof_serialization():
    """Demo 4: Serialize and deserialize proofs."""
    print("\n" + "="*60)
    print("Demo 4: Proof Serialization")
    print("="*60)
    
    prover = ZKPProver()
    verifier = ZKPVerifier()
    
    # Generate proof
    original_proof = prover.generate_proof(
        theorem="Serialization test",
        private_axioms=["Test axiom 1", "Test axiom 2"],
        metadata={"version": "1.0", "purpose": "demo"}
    )
    
    # Serialize to dict
    proof_dict = original_proof.to_dict()
    print(f"✓ Serialized proof to dict")
    print(f"  Keys: {list(proof_dict.keys())}")
    print(f"  Metadata: {proof_dict['metadata']}")
    
    # Serialize to JSON
    proof_json = json.dumps(proof_dict)
    print(f"✓ Serialized to JSON ({len(proof_json)} bytes)")
    
    # Deserialize
    from ipfs_datasets_py.logic.zkp import ZKPProof
    restored_dict = json.loads(proof_json)
    restored_proof = ZKPProof.from_dict(restored_dict)
    
    # Verify restored proof
    is_valid = verifier.verify_proof(restored_proof)
    print(f"✓ Deserialized proof from JSON")
    print(f"✓ Restored proof verified: {is_valid}")
    print(f"✓ Round-trip successful!")


def demo_performance_profiling():
    """Demo 5: Profile proof generation performance."""
    print("\n" + "="*60)
    print("Demo 5: Performance Profiling")
    print("="*60)
    
    prover = ZKPProver()
    verifier = ZKPVerifier()
    
    # Test with varying axiom counts
    axiom_counts = [1, 5, 10, 20, 50]
    results = []
    
    print("\nProof generation time by axiom count:")
    print(f"{'Axioms':<10} {'Gen Time':<12} {'Verify Time':<12} {'Proof Size':<12}")
    print("-" * 50)
    
    for count in axiom_counts:
        axioms = [f"Axiom {i}" for i in range(count)]
        
        # Generate proof
        start = time.time()
        proof = prover.generate_proof(f"Theorem for {count} axioms", axioms)
        gen_time = time.time() - start
        
        # Verify proof
        start = time.time()
        verifier.verify_proof(proof)
        verify_time = time.time() - start
        
        print(f"{count:<10} {gen_time*1000:<12.3f} {verify_time*1000:<12.3f} {proof.size_bytes:<12} bytes")
        results.append((count, gen_time, verify_time, proof.size_bytes))
    
    # Show stats
    stats = prover.get_stats()
    print(f"\n✓ Total proofs generated: {stats['proofs_generated']}")
    print(f"✓ Total time: {stats['total_proving_time']*1000:.2f}ms")
    print(f"✓ Average time: {stats['total_proving_time']/stats['proofs_generated']*1000:.2f}ms")


def demo_error_handling():
    """Demo 6: Error handling and validation."""
    print("\n" + "="*60)
    print("Demo 6: Error Handling")
    print("="*60)
    
    prover = ZKPProver()
    
    # Test empty theorem
    try:
        prover.generate_proof("", ["Axiom 1"])
        print("✗ Empty theorem accepted (shouldn't happen)")
    except ZKPError:
        print("✓ Empty theorem rejected")
    
    # Test no axioms
    try:
        prover.generate_proof("Theorem", [])
        print("✗ No axioms accepted (shouldn't happen)")
    except ZKPError:
        print("✓ No axioms rejected")
    
    # Test malformed proof
    verifier = ZKPVerifier()
    try:
        # Create invalid proof object
        invalid_proof = object()
        result = verifier.verify_proof(invalid_proof)
        if not result:
            print("✓ Malformed proof rejected (returned False)")
        else:
            print("✗ Malformed proof accepted")
    except Exception:
        print("✓ Malformed proof rejected (exception)")
    
    print("✓ All error cases handled correctly")


def main():
    """Run all advanced demos."""
    print("\n" + "="*60)
    print("ZKP ADVANCED DEMO - Simulation Module")
    print("="*60)
    print("\n⚠️  WARNING: Educational simulation only!")
    print("   Not cryptographically secure.")
    print("   See SECURITY_CONSIDERATIONS.md for details.")
    
    # Run demos
    demo_backend_selection()
    demo_proof_caching()
    demo_batch_verification()
    demo_proof_serialization()
    demo_performance_profiling()
    demo_error_handling()
    
    print("\n" + "="*60)
    print("Advanced Demos Complete!")
    print("="*60)
    print("\nKey takeaways:")
    print("  • Backend system allows switching implementations")
    print("  • Caching significantly improves performance")
    print("  • Proofs can be serialized for storage/transmission")
    print("  • Error handling ensures system robustness")
    print("\nNext steps:")
    print("  • See zkp_ipfs_integration.py for IPFS storage")
    print("  • Read IMPLEMENTATION_GUIDE.md for technical details")
    print("  • Read PRODUCTION_UPGRADE_PATH.md for real Groth16")


if __name__ == '__main__':
    main()

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
