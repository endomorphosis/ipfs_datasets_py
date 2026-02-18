#!/usr/bin/env python3
"""
ZKP Basic Demo

This script demonstrates the basics of zero-knowledge proofs using the
simulation ZKP module. It covers proof generation and verification for
simple boolean circuits.

⚠️ EDUCATIONAL USE ONLY: This is a simulation for learning purposes,
not cryptographically secure.
"""

from ipfs_datasets_py.logic.zkp import BooleanCircuit, ZKPProver, ZKPVerifier


def demo_simple_secret():
    """Demo 1: Prove knowledge of a secret bit."""
    print("\n" + "="*60)
    print("Demo 1: Proving Knowledge of a Secret Bit")
    print("="*60)
    
    # Build circuit with one private input
    circuit = BooleanCircuit()
    secret_wire = circuit.add_wire()
    circuit.set_private_input(secret_wire)
    
    # Create prover and verifier
    prover = ZKPProver(circuit)
    verifier = ZKPVerifier(prover.get_verification_key())
    
    # Prover knows secret=True
    witness = {secret_wire: True}
    proof = prover.generate_proof(witness, public_inputs=[])
    
    # Verifier checks proof
    is_valid = verifier.verify_proof(proof, public_inputs=[])
    
    print(f"✓ Prover generated proof (secret not revealed)")
    print(f"✓ Verifier validated proof: {is_valid}")
    print(f"✓ Verifier learned: Prover has a secret bit")
    print(f"✓ Verifier did NOT learn: Whether bit is True or False")


def demo_and_gate():
    """Demo 2: Prove two secrets AND to True."""
    print("\n" + "="*60)
    print("Demo 2: Proving AND Gate Result")
    print("="*60)
    
    # Circuit: secret1 AND secret2 = True (public)
    circuit = BooleanCircuit()
    w1 = circuit.add_wire()  # secret1
    w2 = circuit.add_wire()  # secret2
    w3 = circuit.add_wire()  # result
    
    circuit.add_gate('AND', [w1, w2], w3)
    circuit.set_private_input(w1)
    circuit.set_private_input(w2)
    circuit.set_public_input(w3)
    
    # Generate proof
    prover = ZKPProver(circuit)
    witness = {w1: True, w2: True}
    proof = prover.generate_proof(witness, public_inputs=[True])
    
    # Verify proof
    verifier = ZKPVerifier(prover.get_verification_key())
    is_valid = verifier.verify_proof(proof, public_inputs=[True])
    
    print(f"✓ Prover knows two secret bits")
    print(f"✓ Public result: True (both secrets must be True)")
    print(f"✓ Proof verified: {is_valid}")
    print(f"✓ Verifier learned: Result is True")
    print(f"✓ Verifier did NOT learn: Individual secret values")


def demo_invalid_proof():
    """Demo 3: Show what happens with invalid witness."""
    print("\n" + "="*60)
    print("Demo 3: Invalid Witness Detection")
    print("="*60)
    
    # Same circuit as Demo 2
    circuit = BooleanCircuit()
    w1, w2, w3 = [circuit.add_wire() for _ in range(3)]
    circuit.add_gate('AND', [w1, w2], w3)
    circuit.set_private_input(w1)
    circuit.set_private_input(w2)
    circuit.set_public_input(w3)
    
    prover = ZKPProver(circuit)
    
    # Try to prove (True AND False = True) - impossible!
    try:
        witness = {w1: True, w2: False}  # AND = False
        proof = prover.generate_proof(witness, public_inputs=[True])  # Claims True!
        print("❌ Proof generated (shouldn't happen!)")
    except ValueError as e:
        print(f"✓ Invalid witness rejected: {str(e)[:50]}...")
        print(f"✓ System prevents false proofs")


def main():
    """Run all demos."""
    print("\n" + "="*60)
    print("ZKP BASIC DEMO - Simulation Module")
    print("="*60)
    print("\n⚠️  WARNING: Educational simulation only!")
    print("   Not cryptographically secure.")
    print("   See SECURITY_CONSIDERATIONS.md for details.")
    
    # Run demos
    demo_simple_secret()
    demo_and_gate()
    demo_invalid_proof()
    
    print("\n" + "="*60)
    print("Demos Complete!")
    print("="*60)
    print("\nNext steps:")
    print("  • See zkp_advanced_demo.py for complex circuits")
    print("  • See zkp_ipfs_integration.py for storage")
    print("  • Read QUICKSTART.md for more examples")
    print("  • Read PRODUCTION_UPGRADE_PATH.md for real security")


if __name__ == '__main__':
    main()
