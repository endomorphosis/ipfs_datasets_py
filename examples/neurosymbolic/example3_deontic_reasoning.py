"""
Example 3: Deontic Logic Reasoning

This example demonstrates deontic logic reasoning for legal/normative reasoning:
- Obligations (O)
- Permissions (P)
- Prohibitions (F)
- Deontic axioms (K, D)
"""

from ipfs_datasets_py.logic.integration import NeurosymbolicReasoner
from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
    Predicate,
    DeonticFormula,
    DeonticOperator,
)

def main():
    print("=" * 70)
    print("Example 3: Deontic Logic Reasoning")
    print("=" * 70)
    
    # Create reasoner
    print("\n1. Creating reasoner with deontic logic support...")
    reasoner = NeurosymbolicReasoner(use_cec=True, use_modal=True, use_nl=True)
    print("   ✅ Reasoner created")
    
    # Define legal obligations
    print("\n2. Defining deontic formulas (legal obligations)...")
    
    # Contract obligations
    pay = Predicate("PayInvoice", ())
    report = Predicate("SubmitReport", ())
    notify = Predicate("NotifyChanges", ())
    
    # It is obligatory to pay invoices
    obligatory_pay = DeonticFormula(DeonticOperator.OBLIGATORY, pay)
    print(f"   Formula 1: {obligatory_pay.to_string()}")
    print(f"   Meaning: It is obligatory to pay invoices")
    
    # It is forbidden to skip reports
    forbidden_skip = DeonticFormula(DeonticOperator.FORBIDDEN, report)
    print(f"   Formula 2: {forbidden_skip.to_string()}")
    print(f"   Meaning: It is forbidden to not submit reports")
    
    # Add deontic knowledge
    print("\n3. Adding deontic knowledge (contract terms)...")
    reasoner.add_knowledge(obligatory_pay)
    print(f"   ✅ Added: {obligatory_pay.to_string()}")
    
    # Derive permissions from obligations
    print("\n4. Proving: Permission to pay (from obligation)")
    permitted_pay = DeonticFormula(DeonticOperator.PERMISSIBLE, pay)
    result = reasoner.prove(permitted_pay, timeout_ms=2000)
    
    print(f"   Goal: {permitted_pay.to_string()}")
    print(f"   From: {obligatory_pay.to_string()}")
    print(f"   Status: {result.status.value}")
    print(f"   Method: {result.method}")
    
    if result.is_proved():
        print("   ✅ PROVED: O(p) → P(p) (D axiom)")
        print("   Explanation: If something is obligatory, it must be permissible")
    else:
        print(f"   ⚠️  Status: {result.status.value}")
    
    # Check prohibition equivalence
    print("\n5. Deontic equivalences:")
    print("   - F(p) ≡ O(¬p): Forbidden p = Obligatory not-p")
    print("   - P(p) ≡ ¬O(¬p): Permitted p = Not obligatory not-p")
    print("   - O(p) ≡ ¬P(¬p): Obligatory p = Not permitted not-p")
    
    # Real-world scenario
    print("\n6. Real-world legal scenario:")
    print("   Contract: 'The contractor shall pay all invoices within 30 days'")
    print("   Formal: O(PayInvoice)")
    print()
    print("   Derived obligations:")
    print("   ✓ Permitted to pay (D axiom)")
    print("   ✓ Not permitted to skip payment (deontic consistency)")
    print("   ✓ Violation consequences can be modeled")
    
    # Combined reasoning
    print("\n7. Combined deontic reasoning:")
    print("   If O(p) and O(p → q), then O(q) (K axiom for deontic logic)")
    print("   Example: O(PayInvoice) and O(PayInvoice → NotifyPayment)")
    print("   Derives: O(NotifyPayment)")
    
    print("\n8. Deontic axioms available:")
    print("   - K: O(p → q) → (O(p) → O(q)) - Distribution")
    print("   - D: O(p) → P(p) - Consistency")
    print("   - F(p) ↔ O(¬p) - Prohibition equivalence")
    print("   - P(p) ↔ ¬O(¬p) - Permission as absence of prohibition")
    
    print("\n" + "=" * 70)
    print("Example complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()
