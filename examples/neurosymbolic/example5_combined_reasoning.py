"""
Example 5: Combined Temporal-Deontic Reasoning

This example demonstrates combined temporal and deontic logic:
- Temporal obligations (O(□p), O(◊p))
- Deontic persistence over time
- Real-world legal/contract scenarios
"""

from ipfs_datasets_py.logic.integration import NeurosymbolicReasoner
from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
    Predicate,
    TemporalFormula,
    DeonticFormula,
    TemporalOperator,
    DeonticOperator,
)

def main():
    print("=" * 70)
    print("Example 5: Combined Temporal-Deontic Reasoning")
    print("=" * 70)
    
    # Create reasoner
    print("\n1. Creating reasoner with full capabilities...")
    reasoner = NeurosymbolicReasoner(use_cec=True, use_modal=True, use_nl=True)
    print("   ✅ Reasoner created")
    
    # Define combined formulas
    print("\n2. Defining combined temporal-deontic formulas...")
    
    # Contract: Must always report status
    report = Predicate("ReportStatus", ())
    obligatory_report = DeonticFormula(DeonticOperator.OBLIGATORY, report)
    always_obligatory = TemporalFormula(
        TemporalOperator.ALWAYS,
        obligatory_report
    )
    
    print(f"   Formula 1: {always_obligatory.to_string()}")
    print(f"   Meaning: It is always obligatory to report status")
    print(f"   Contract: 'The contractor shall continuously report status'")
    
    # Must eventually complete
    complete = Predicate("Complete", ())
    obligatory_complete = DeonticFormula(DeonticOperator.OBLIGATORY, complete)
    eventually_obligatory = TemporalFormula(
        TemporalOperator.EVENTUALLY,
        obligatory_complete
    )
    
    print(f"\n   Formula 2: {eventually_obligatory.to_string()}")
    print(f"   Meaning: Eventually, it becomes obligatory to complete")
    print(f"   Contract: 'The work must be completed within deadline'")
    
    # Add knowledge
    print("\n3. Adding temporal-deontic knowledge...")
    reasoner.add_knowledge(always_obligatory)
    print(f"   ✅ Added: {always_obligatory.to_string()}")
    
    # Prove obligation persists
    print("\n4. Proving: Obligation persists (O(Report))")
    result = reasoner.prove(obligatory_report, timeout_ms=2000)
    
    print(f"   Goal: {obligatory_report.to_string()}")
    print(f"   From: {always_obligatory.to_string()}")
    print(f"   Status: {result.status.value}")
    
    if result.is_proved():
        print("   ✅ PROVED: □O(p) → O(p)")
        print("   Explanation: If always obligatory, then obligatory now")
    else:
        print(f"   ⚠️  Status: {result.status.value}")
    
    # Real-world scenarios
    print("\n5. Real-world contract scenarios:")
    print()
    print("   Scenario A: Service Level Agreement (SLA)")
    print("   - □O(Respond): Always obligatory to respond")
    print("   - □(O(Respond) → ◊Respond): If obligatory, must eventually respond")
    print("   - Temporal guarantee: Response within time limit")
    print()
    print("   Scenario B: Data Retention Policy")
    print("   - □O(Backup): Always obligatory to backup")
    print("   - □P(Delete): Always permissible to delete old data")
    print("   - O(□Secure): Obligatory to always secure data")
    print()
    print("   Scenario C: Compliance Requirements")
    print("   - O(◊Audit): Obligatory to eventually audit")
    print("   - □F(Violate): Always forbidden to violate rules")
    print("   - ◊O(Certify): Eventually obligatory to certify")
    
    # Temporal-deontic rules
    print("\n6. Temporal-deontic inference rules available:")
    print("   1. O(□p) ⊢ □O(p) - Temporal obligation persistence")
    print("   2. O(p) ⊢ O(Xp) - Deontic temporal introduction")
    print("   3. O(p U q) ⊢ ◊O(q) - Until obligation")
    print("   4. P(□p) ⊢ □P(p) - Always permission")
    print("   5. F(◊p) ⊢ □F(p) - Eventually forbidden")
    print("   6. O(◊p) ⊢ ◊O(p) - Obligation eventually")
    print("   7. P(p) ⊢ P(◊p) - Permission temporal weakening")
    
    # Use cases
    print("\n7. Common use cases:")
    print("   - Smart contracts: Encoding obligations in blockchain")
    print("   - Legal compliance: Modeling regulatory requirements")
    print("   - SLA verification: Proving service guarantees")
    print("   - Access control: Time-based permissions")
    print("   - Workflow validation: Ensuring process compliance")
    
    print("\n" + "=" * 70)
    print("Example complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()
