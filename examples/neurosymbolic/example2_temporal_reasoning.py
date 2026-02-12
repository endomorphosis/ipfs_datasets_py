"""
Example 2: Temporal Logic Reasoning

This example demonstrates temporal logic reasoning using the neurosymbolic system:
- Working with temporal operators (□, ◊, X, U)
- Using S4 modal logic prover
- Temporal persistence and eventual satisfaction
"""

from ipfs_datasets_py.logic.integration import NeurosymbolicReasoner
from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
    Predicate,
    TemporalFormula,
    TemporalOperator,
)

def main():
    print("=" * 70)
    print("Example 2: Temporal Logic Reasoning")
    print("=" * 70)
    
    # Create reasoner with modal logic enabled
    print("\n1. Creating reasoner with modal logic support...")
    reasoner = NeurosymbolicReasoner(use_cec=True, use_modal=True, use_nl=True)
    print("   ✅ Reasoner created")
    
    # Define predicates
    print("\n2. Defining temporal formulas...")
    
    # System is always available
    available = Predicate("Available", ())
    always_available = TemporalFormula(TemporalOperator.ALWAYS, available)
    
    print(f"   Formula 1: {always_available.to_string()}")
    print(f"   Meaning: The system is always available (□Available)")
    
    # Eventually respond
    respond = Predicate("Respond", ())
    eventually_respond = TemporalFormula(TemporalOperator.EVENTUALLY, respond)
    
    print(f"   Formula 2: {eventually_respond.to_string()}")
    print(f"   Meaning: The system will eventually respond (◊Respond)")
    
    # Add temporal knowledge
    print("\n3. Adding temporal knowledge...")
    reasoner.add_knowledge(always_available)
    print(f"   ✅ Added: {always_available.to_string()}")
    
    # Prove temporal properties
    print("\n4. Proving: Available now (from □Available)")
    result = reasoner.prove(available, timeout_ms=2000)
    
    print(f"   Goal: {available.to_string()}")
    print(f"   From: {always_available.to_string()}")
    print(f"   Status: {result.status.value}")
    print(f"   Method: {result.method}")
    print(f"   Time: {result.time_ms:.2f}ms")
    
    if result.is_proved():
        print("   ✅ PROVED: □p → p (T axiom)")
        print("   Explanation: If something is always true, it's true now")
    else:
        print(f"   ⚠️  Status: {result.status.value}")
    
    # Prove nested temporal property
    print("\n5. Proving: □□Available (from □Available)")
    nested_always = TemporalFormula(TemporalOperator.ALWAYS, always_available)
    result = reasoner.prove(nested_always, timeout_ms=2000)
    
    print(f"   Goal: {nested_always.to_string()}")
    print(f"   From: {always_available.to_string()}")
    print(f"   Status: {result.status.value}")
    
    if result.is_proved():
        print("   ✅ PROVED: □p → □□p (S4 axiom)")
        print("   Explanation: Necessity is transitive")
    else:
        print(f"   ⚠️  Status: {result.status.value}")
    
    # Explain temporal reasoning
    print("\n6. Temporal reasoning capabilities:")
    print("   - □ (Always/Box): Something holds at all future times")
    print("   - ◊ (Eventually/Diamond): Something holds at some future time")
    print("   - X (Next): Something holds at the next time point")
    print("   - U (Until): p U q means p holds until q becomes true")
    print()
    print("   Temporal axioms available:")
    print("   - K: □(p → q) → (□p → □q) - Distribution")
    print("   - T: □p → p - Truth")
    print("   - S4: □p → □□p - Transitivity")
    print("   - S5: ◊p → □◊p - Euclidean property")
    
    print("\n" + "=" * 70)
    print("Example complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()
