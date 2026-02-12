"""
Example 4: Multi-Format Parsing

This example demonstrates parsing formulas from different formats:
- TDFOL format
- DCEC s-expression format
- Natural language (if grammar available)
- Auto-detection
"""

from ipfs_datasets_py.logic.integration import NeurosymbolicReasoner

def main():
    print("=" * 70)
    print("Example 4: Multi-Format Parsing")
    print("=" * 70)
    
    # Create reasoner
    print("\n1. Creating reasoner...")
    reasoner = NeurosymbolicReasoner(use_cec=True, use_modal=True, use_nl=True)
    print("   ✅ Reasoner created")
    
    # Check parsing capabilities
    caps = reasoner.get_capabilities()
    print(f"   Grammar available: {caps['grammar_available']}")
    print(f"   Natural language: {caps['natural_language']}")
    
    # Parse TDFOL format
    print("\n2. Parsing TDFOL format:")
    
    examples_tdfol = [
        "P",
        "P -> Q",
        "P & Q",
        "P | Q",
        "~P",
        "forall x. P(x)",
        "exists x. Q(x)",
        "forall x. (P(x) -> Q(x))",
    ]
    
    for expr in examples_tdfol:
        formula = reasoner.parse(expr, format="tdfol")
        if formula:
            print(f"   ✅ '{expr}' → {formula.to_string()}")
        else:
            print(f"   ❌ '{expr}' → Failed to parse")
    
    # Parse DCEC format
    print("\n3. Parsing DCEC s-expression format:")
    
    examples_dcec = [
        "P",
        "(and P Q)",
        "(or P Q)",
        "(not P)",
        "(implies P Q)",
        "(iff P Q)",
        "(forall x P(x))",
        "(exists x Q(x))",
        "(O P)",  # Obligation
        "(P Q)",  # Permission (note: might be confused with predicate P)
        "(always P)",  # Temporal always
        "(eventually Q)",  # Temporal eventually
    ]
    
    for expr in examples_dcec:
        formula = reasoner.parse(expr, format="dcec")
        if formula:
            print(f"   ✅ '{expr}' → {formula.to_string()}")
        else:
            print(f"   ❌ '{expr}' → Failed to parse")
    
    # Auto-detection
    print("\n4. Auto-detection of format:")
    
    examples_auto = [
        ("P -> Q", "TDFOL (has ->)"),
        ("(and P Q)", "DCEC (starts with paren)"),
        ("forall x. P(x)", "TDFOL (has forall)"),
        ("(O P)", "DCEC (obligation)"),
    ]
    
    for expr, expected in examples_auto:
        formula = reasoner.parse(expr, format="auto")
        if formula:
            print(f"   ✅ '{expr}' detected as {expected}")
            print(f"      → {formula.to_string()}")
        else:
            print(f"   ❌ '{expr}' → Failed")
    
    # Natural language (if available)
    if caps['natural_language']:
        print("\n5. Natural language parsing:")
        
        examples_nl = [
            "All humans are mortal",
            "Some birds can fly",
            "It is obligatory to report",
            "Always be available",
        ]
        
        for text in examples_nl:
            formula = reasoner.parse(text, format="nl")
            if formula:
                print(f"   ✅ '{text}'")
                print(f"      → {formula.to_string()}")
            else:
                print(f"   ⚠️  '{text}' → Could not parse (grammar may need extension)")
    else:
        print("\n5. Natural language parsing: Not available (grammar not loaded)")
    
    # Explanation
    print("\n6. Format summary:")
    print("   TDFOL:")
    print("     - Standard first-order logic notation")
    print("     - Uses: ->, &, |, ~, forall, exists")
    print("     - Example: forall x. (Human(x) -> Mortal(x))")
    print()
    print("   DCEC:")
    print("     - S-expression (LISP-style) notation")
    print("     - Uses: and, or, not, implies, iff, forall, exists, O, P, F")
    print("     - Example: (forall x (implies (Human x) (Mortal x)))")
    print()
    print("   Natural Language:")
    print("     - English-like statements")
    print("     - Grammar-based parsing with fallback")
    print("     - Example: 'All humans are mortal'")
    
    print("\n" + "=" * 70)
    print("Example complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()
