#!/usr/bin/env python3
"""
ZKP Basic Demo

This script demonstrates the basics of zero-knowledge proofs using the
simulation ZKP module. It shows how to prove theorems without revealing
the private axioms used.

⚠️ EDUCATIONAL USE ONLY: This is a simulation for learning purposes,
not cryptographically secure.

How to run:
    # From repository root:
    PYTHONPATH=. python ipfs_datasets_py/logic/zkp/examples/zkp_basic_demo.py
    
    # Or install package first:
    pip install -e .
    python ipfs_datasets_py/logic/zkp/examples/zkp_basic_demo.py
"""

from ipfs_datasets_py.logic.zkp import ZKPProver, ZKPVerifier


def demo_simple_proof():
    """Demo 1: Prove knowledge of axioms that derive a theorem."""
    print("\n" + "="*60)
    print("Demo 1: Simple Theorem Proving")
    print("="*60)
    
    # Create prover and verifier
    prover = ZKPProver()
    verifier = ZKPVerifier()
    
    # Prover has private axioms
    private_axioms = [
        "Socrates is human",
        "All humans are mortal"
    ]
    
    # Generate proof for public theorem
    theorem = "Socrates is mortal"
    proof = prover.generate_proof(
        theorem=theorem,
        private_axioms=private_axioms
    )
    
    # Verifier checks proof without seeing axioms
    is_valid = verifier.verify_proof(proof)
    
    print(f"Theorem (public): {theorem}")
    print(f"Axioms (private): Hidden from verifier")
    print(f"✓ Proof generated: {proof.size_bytes} bytes")
    print(f"✓ Proof verified: {is_valid}")
    print(f"✓ Verifier learned: Theorem is true")
    print(f"✓ Verifier did NOT learn: Which axioms were used")


def demo_logical_inference():
    """Demo 2: Prove logical inference P AND (P -> Q) => Q."""
    print("\n" + "="*60)
    print("Demo 2: Logical Inference")
    print("="*60)
    
    prover = ZKPProver()
    verifier = ZKPVerifier()
    
    # Private: Prover knows P and P -> Q
    private_axioms = [
        "P",           # Secret fact P
        "P -> Q"       # Secret implication
    ]
    
    # Public: Claim Q is true
    theorem = "Q"
    
    # Generate and verify proof
    proof = prover.generate_proof(
        theorem=theorem,
        private_axioms=private_axioms
    )
    
    is_valid = verifier.verify_proof(proof)
    
    print(f"Theorem (public): {theorem}")
    print(f"Axioms (private): P, P -> Q (hidden)")
    print(f"✓ Proof verified: {is_valid}")
    print(f"✓ Logic: P AND (P -> Q) implies Q")
    print(f"✓ Privacy: Verifier doesn't learn P or P -> Q")


def demo_multiple_axioms():
    """Demo 3: Prove theorem from multiple axioms."""
    print("\n" + "="*60)
    print("Demo 3: Multiple Private Axioms")
    print("="*60)
    
    prover = ZKPProver(enable_caching=True)
    verifier = ZKPVerifier()
    
    # Company proving compliance without revealing policies
    private_axioms = [
        "Company has policy A",
        "Company has policy B",
        "Company has policy C",
        "Policies A, B, C satisfy regulation X"
    ]
    
    theorem = "Company complies with regulation X"
    
    proof = prover.generate_proof(
        theorem=theorem,
        private_axioms=private_axioms
    )
    
    is_valid = verifier.verify_proof(proof)
    
    print(f"Theorem (public): {theorem}")
    print(f"Axioms (private): 4 internal policies (hidden)")
    print(f"✓ Proof verified: {is_valid}")
    print(f"✓ Proof size: {proof.size_bytes} bytes")
    
    # Show stats
    stats = prover.get_stats()
    print(f"✓ Prover stats: {stats['proofs_generated']} proofs generated")


def main():
    """Run all demos."""
    print("\n" + "="*60)
    print("ZKP BASIC DEMO - Simulation Module")
    print("="*60)
    print("\n⚠️  WARNING: Educational simulation only!")
    print("   Not cryptographically secure.")
    print("   See SECURITY_CONSIDERATIONS.md for details.")
    
    # Run demos
    demo_simple_proof()
    demo_logical_inference()
    demo_multiple_axioms()
    
    print("\n" + "="*60)
    print("Demos Complete!")
    print("="*60)
    print("\nNext steps:")
    print("  • See zkp_advanced_demo.py for advanced features")
    print("  • See zkp_ipfs_integration.py for IPFS storage")
    print("  • Read QUICKSTART.md for more examples")
    print("  • Read PRODUCTION_UPGRADE_PATH.md for real security")


if __name__ == '__main__':
    main()
