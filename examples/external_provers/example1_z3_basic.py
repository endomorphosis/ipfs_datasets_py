#!/usr/bin/env python3
"""
Example 1: Basic Z3 Integration

This example demonstrates basic usage of Z3 for proving TDFOL formulas.

Demonstrates:
- Simple tautologies
- Modus Ponens
- Quantified formulas
- Proof with axioms
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

def main():
    print("=" * 70)
    print("Example 1: Basic Z3 Integration")
    print("=" * 70)
    print()
    
    # Check if Z3 is available
    from ipfs_datasets_py.logic.external_provers import Z3_AVAILABLE, check_prover_availability
    
    if not Z3_AVAILABLE:
        print("❌ Z3 is not available. Install with: pip install z3-solver")
        return
    
    print("✓ Z3 is available")
    print()
    
    # Import required modules
    from ipfs_datasets_py.logic.external_provers import Z3ProverBridge
    from ipfs_datasets_py.logic.TDFOL import parse_tdfol
    
    # Create Z3 prover
    prover = Z3ProverBridge(timeout=5.0)
    print("Created Z3 prover with 5 second timeout")
    print()
    
    # Example 1: Simple tautology (P -> P)
    print("1. Proving simple tautology: P -> P")
    print("-" * 70)
    formula1 = parse_tdfol("P -> P")
    result1 = prover.prove(formula1)
    
    print(f"Formula: {formula1}")
    print(f"Result: {'✓ PROVED' if result1.is_proved() else '✗ NOT PROVED'}")
    print(f"Time: {result1.proof_time:.3f}s")
    print(f"Reason: {result1.reason}")
    print()
    
    # Example 2: Modus Ponens
    print("2. Proving Modus Ponens: P, P -> Q ⊢ Q")
    print("-" * 70)
    axiom1 = parse_tdfol("P")
    axiom2 = parse_tdfol("P -> Q")
    goal = parse_tdfol("Q")
    
    result2 = prover.prove(goal, axioms=[axiom1, axiom2])
    
    print(f"Axiom 1: {axiom1}")
    print(f"Axiom 2: {axiom2}")
    print(f"Goal: {goal}")
    print(f"Result: {'✓ PROVED' if result2.is_proved() else '✗ NOT PROVED'}")
    print(f"Time: {result2.proof_time:.3f}s")
    print()
    
    # Example 3: Law of Excluded Middle (P ∨ ¬P)
    print("3. Proving Law of Excluded Middle: P | ~P")
    print("-" * 70)
    formula3 = parse_tdfol("P | ~P")
    result3 = prover.prove(formula3)
    
    print(f"Formula: {formula3}")
    print(f"Result: {'✓ PROVED' if result3.is_proved() else '✗ NOT PROVED'}")
    print(f"Time: {result3.proof_time:.3f}s")
    print()
    
    # Example 4: De Morgan's Law
    print("4. Proving De Morgan's Law: ~(P & Q) -> (~P | ~Q)")
    print("-" * 70)
    formula4 = parse_tdfol("~(P & Q) -> (~P | ~Q)")
    result4 = prover.prove(formula4)
    
    print(f"Formula: {formula4}")
    print(f"Result: {'✓ PROVED' if result4.is_proved() else '✗ NOT PROVED'}")
    print(f"Time: {result4.proof_time:.3f}s")
    print()
    
    # Example 5: Quantified formula (∀x. P(x) -> P(x))
    print("5. Proving quantified tautology: forall x. P(x) -> P(x)")
    print("-" * 70)
    formula5 = parse_tdfol("forall x. P(x) -> P(x)")
    result5 = prover.prove(formula5)
    
    print(f"Formula: {formula5}")
    print(f"Result: {'✓ PROVED' if result5.is_proved() else '✗ NOT PROVED'}")
    print(f"Time: {result5.proof_time:.3f}s")
    print()
    
    # Example 6: Non-theorem (should not be proved)
    print("6. Attempting to prove non-theorem: P -> Q")
    print("-" * 70)
    formula6 = parse_tdfol("P -> Q")
    result6 = prover.prove(formula6)
    
    print(f"Formula: {formula6}")
    print(f"Result: {'✓ PROVED' if result6.is_proved() else '✗ NOT PROVED (expected)'}")
    print(f"Time: {result6.proof_time:.3f}s")
    print(f"Reason: {result6.reason}")
    if result6.model:
        print(f"Counterexample model exists: {result6.model}")
    print()
    
    # Summary
    print("=" * 70)
    print("Summary:")
    print(f"  Example 1 (P -> P): {'✓' if result1.is_proved() else '✗'}")
    print(f"  Example 2 (Modus Ponens): {'✓' if result2.is_proved() else '✗'}")
    print(f"  Example 3 (Excluded Middle): {'✓' if result3.is_proved() else '✗'}")
    print(f"  Example 4 (De Morgan): {'✓' if result4.is_proved() else '✗'}")
    print(f"  Example 5 (Quantified): {'✓' if result5.is_proved() else '✗'}")
    print(f"  Example 6 (Non-theorem): {'✗' if not result6.is_proved() else '✓ (unexpected)'}")
    print()
    
    total_time = sum([r.proof_time for r in [result1, result2, result3, result4, result5, result6]])
    print(f"Total proving time: {total_time:.3f}s")
    print("=" * 70)


if __name__ == "__main__":
    main()
