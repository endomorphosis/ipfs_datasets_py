"""
Example 1: Basic Neurosymbolic Reasoning

This example demonstrates the basic usage of the neurosymbolic reasoning system:
- Creating a reasoner
- Adding knowledge
- Proving theorems
- Checking system capabilities
"""

from ipfs_datasets_py.logic.integration import NeurosymbolicReasoner
from ipfs_datasets_py.logic.TDFOL.tdfol_parser import parse_tdfol

def main():
    print("=" * 70)
    print("Example 1: Basic Neurosymbolic Reasoning")
    print("=" * 70)
    
    # Create a reasoner with all features enabled
    print("\n1. Creating neurosymbolic reasoner...")
    reasoner = NeurosymbolicReasoner(
        use_cec=True,      # Enable CEC integration (87 rules)
        use_modal=True,    # Enable modal logic provers
        use_nl=True        # Enable natural language processing
    )
    print("   ✅ Reasoner created")
    
    # Check system capabilities
    print("\n2. System capabilities:")
    caps = reasoner.get_capabilities()
    print(f"   - TDFOL rules: {caps['tdfol_rules']}")
    print(f"   - CEC rules: {caps['cec_rules']}")
    print(f"   - Total inference rules: {caps['total_inference_rules']}")
    print(f"   - Modal provers: {caps['modal_provers']}")
    print(f"   - Grammar available: {caps['grammar_available']}")
    print(f"   - Natural language: {caps['natural_language']}")
    
    # Add knowledge to the system
    print("\n3. Adding knowledge to the system...")
    reasoner.add_knowledge("P")
    print("   ✅ Added: P")
    
    reasoner.add_knowledge("P -> Q")
    print("   ✅ Added: P → Q")
    
    reasoner.add_knowledge("Q -> R")
    print("   ✅ Added: Q → R")
    
    # Prove a theorem using Modus Ponens
    print("\n4. Proving theorem: Q")
    q = parse_tdfol("Q")
    result = reasoner.prove(q, timeout_ms=2000)
    
    print(f"   Goal: Q")
    print(f"   Status: {result.status.value}")
    print(f"   Method: {result.method}")
    print(f"   Time: {result.time_ms:.2f}ms")
    
    if result.is_proved():
        print("   ✅ PROVED: Q follows from P and P→Q (Modus Ponens)")
    else:
        print(f"   ⚠️  Not proved: {result.message}")
    
    # Prove a more complex theorem
    print("\n5. Proving theorem: R (using transitivity)")
    r = parse_tdfol("R")
    result = reasoner.prove(r, timeout_ms=2000)
    
    print(f"   Goal: R")
    print(f"   Status: {result.status.value}")
    print(f"   Method: {result.method}")
    print(f"   Time: {result.time_ms:.2f}ms")
    
    if result.is_proved():
        print("   ✅ PROVED: R follows from P, P→Q, Q→R (Hypothetical Syllogism)")
    else:
        print(f"   ⚠️  Status: {result.status.value}")
    
    # Try proving something that doesn't follow
    print("\n6. Proving theorem: S (not derivable)")
    s = parse_tdfol("S")
    result = reasoner.prove(s, timeout_ms=1000)
    
    print(f"   Goal: S")
    print(f"   Status: {result.status.value}")
    print(f"   ⚠️  Cannot prove S from available knowledge (expected)")
    
    print("\n" + "=" * 70)
    print("Example complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()
