#!/usr/bin/env python3
"""
Demonstration of Complete Native Python 3 CEC Implementation.

This script showcases the full native Python 3 implementation including:
- DCEC logic system
- Theorem proving
- Natural language conversion
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from ipfs_datasets_py.logic.CEC.native import (
    # Core DCEC
    DCECContainer,
    DeonticOperator,
    CognitiveOperator,
    TemporalOperator,
    LogicalConnective,
    AtomicFormula,
    DeonticFormula,
    CognitiveFormula,
    TemporalFormula,
    ConnectiveFormula,
    VariableTerm,
    # Theorem Prover
    TheoremProver,
    ProofResult,
    # NL Converter
    NaturalLanguageConverter,
)


def print_section(title):
    """Print a formatted section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70 + "\n")


def demo_theorem_proving():
    """Demonstrate theorem proving capabilities."""
    print_section("Theorem Proving with Native Python 3 Prover")
    
    # Create container and formulas
    container = DCECContainer()
    p_pred = container.namespace.add_predicate("P", [])
    q_pred = container.namespace.add_predicate("Q", [])
    r_pred = container.namespace.add_predicate("R", [])
    
    p = AtomicFormula(p_pred, [])
    q = AtomicFormula(q_pred, [])
    r = AtomicFormula(r_pred, [])
    
    # Create prover
    prover = TheoremProver()
    print("1. Initialized native theorem prover")
    
    # Example 1: Modus Ponens
    print("\n2. Proving with Modus Ponens:")
    print("   Axioms: P, P → Q")
    print("   Goal: Q")
    
    implies = ConnectiveFormula(LogicalConnective.IMPLIES, [p, q])
    attempt1 = prover.prove_theorem(goal=q, axioms=[p, implies])
    
    print(f"   Result: {attempt1.result.value.upper()}")
    print(f"   Execution time: {attempt1.execution_time:.4f}s")
    
    if attempt1.proof_tree:
        print("\n   Proof steps:")
        for step in attempt1.proof_tree.steps:
            print(f"     {step}")
    
    # Example 2: Simplification
    print("\n3. Proving with Simplification:")
    print("   Axiom: P ∧ Q")
    print("   Goal: P")
    
    conjunction = ConnectiveFormula(LogicalConnective.AND, [p, q])
    attempt2 = prover.prove_theorem(goal=p, axioms=[conjunction])
    
    print(f"   Result: {attempt2.result.value.upper()}")
    
    # Example 3: Unprovable goal
    print("\n4. Attempting unprovable goal:")
    print("   Axioms: P")
    print("   Goal: R")
    
    attempt3 = prover.prove_theorem(goal=r, axioms=[p])
    print(f"   Result: {attempt3.result.value.upper()} (as expected)")
    
    # Statistics
    print(f"\n5. Prover statistics:")
    stats = prover.get_statistics()
    for key, value in stats.items():
        print(f"   {key}: {value}")


def demo_natural_language():
    """Demonstrate natural language conversion."""
    print_section("Natural Language Conversion")
    
    converter = NaturalLanguageConverter()
    print("1. Initialized native NL converter")
    
    # Test phrases
    test_cases = [
        ("Deontic Logic", [
            "the agent must act",
            "the robot may move",
            "the system must not fail",
        ]),
        ("Cognitive Logic", [
            "the agent believes that the goal is achieved",
            "the robot knows that the path is clear",
            "the agent intends to complete the task",
        ]),
        ("Temporal Logic", [
            "always the safety property holds",
            "eventually the system stabilizes",
            "next the state transitions",
        ]),
    ]
    
    for category, phrases in test_cases:
        print(f"\n2. {category}:")
        for phrase in phrases:
            result = converter.convert_to_dcec(phrase)
            if result.success:
                print(f"   ✓ '{phrase}'")
                print(f"     → {result.dcec_formula.to_string()}")
                
                # Convert back to English
                back = converter.convert_from_dcec(result.dcec_formula)
                print(f"     ← {back}")
            else:
                print(f"   ✗ '{phrase}' - {result.error_message}")
    
    # Statistics
    print(f"\n3. Converter statistics:")
    stats = converter.get_conversion_statistics()
    for key, value in stats.items():
        if isinstance(value, float):
            print(f"   {key}: {value:.2f}")
        else:
            print(f"   {key}: {value}")


def demo_integrated_workflow():
    """Demonstrate integrated workflow."""
    print_section("Integrated Workflow: NL → DCEC → Theorem Proving")
    
    converter = NaturalLanguageConverter()
    prover = TheoremProver()
    
    print("Scenario: Proving a robot's obligation")
    print()
    
    # Step 1: Convert NL to DCEC
    print("1. Convert natural language to DCEC:")
    
    axiom_text = "the robot must act"
    goal_text = "the robot must act"
    
    axiom_result = converter.convert_to_dcec(axiom_text)
    goal_result = converter.convert_to_dcec(goal_text)
    
    print(f"   Axiom: '{axiom_text}'")
    print(f"   → {axiom_result.dcec_formula.to_string()}")
    print()
    print(f"   Goal: '{goal_text}'")
    print(f"   → {goal_result.dcec_formula.to_string()}")
    
    # Step 2: Prove with theorem prover
    print("\n2. Prove with theorem prover:")
    
    attempt = prover.prove_theorem(
        goal=goal_result.dcec_formula,
        axioms=[axiom_result.dcec_formula]
    )
    
    print(f"   Result: {attempt.result.value.upper()}")
    print(f"   (Goal is identical to axiom, so immediately proved)")
    
    # More complex example
    print("\n3. More complex example:")
    print("   Axioms:")
    print("     - 'the robot must act'")
    print("     - 'if the robot must act then the robot may act'")
    print("   Goal: 'the robot may act'")
    
    must_act = converter.convert_to_dcec("the robot must act").dcec_formula
    may_act = converter.convert_to_dcec("the robot may act").dcec_formula
    
    # Create implication manually
    implies = ConnectiveFormula(LogicalConnective.IMPLIES, [must_act, may_act])
    
    attempt2 = prover.prove_theorem(goal=may_act, axioms=[must_act, implies])
    
    print(f"   Result: {attempt2.result.value.upper()}")
    if attempt2.result == ProofResult.PROVED:
        print("   ✓ Successfully proved using Modus Ponens!")


def demo_complete_example():
    """Demonstrate a complete real-world scenario."""
    print_section("Complete Example: Robot Safety Rules")
    
    container = DCECContainer()
    converter = NaturalLanguageConverter()
    prover = TheoremProver()
    
    print("Scenario: A robot operating in a warehouse")
    print()
    
    # Define rules in natural language
    rules = [
        "the robot must detect obstacles",
        "the robot must not collide with humans",
        "if the robot detects an obstacle then the robot must stop",
        "the robot believes that safety is important",
        "eventually the robot completes the task",
    ]
    
    print("1. Safety rules (in natural language):")
    for i, rule in enumerate(rules, 1):
        print(f"   {i}. {rule}")
    
    # Convert to DCEC
    print("\n2. Converted to DCEC formulas:")
    formulas = []
    for rule in rules:
        result = converter.convert_to_dcec(rule)
        if result.success:
            formulas.append(result.dcec_formula)
            print(f"   → {result.dcec_formula.to_string()}")
    
    # Add to knowledge base
    print(f"\n3. Knowledge base created with {len(formulas)} formulas")
    for formula in formulas:
        container.add_statement(formula, is_axiom=True)
    
    print(f"   Container stats: {container.get_statistics()}")
    
    # Summary
    print("\n4. Summary:")
    print("   ✓ Natural language rules converted to formal logic")
    print("   ✓ Formulas stored in knowledge base")
    print("   ✓ Ready for automated reasoning")
    print("   ✓ Can prove theorems about robot behavior")


def main():
    """Main demonstration function."""
    print("\n" + "╔" + "═" * 68 + "╗")
    print("║" + " " * 6 + "Complete Native Python 3 CEC Implementation Demo" + " " * 13 + "║")
    print("║" + " " * 10 + "DCEC Logic + Theorem Proving + NL Conversion" + " " * 14 + "║")
    print("╚" + "═" * 68 + "╝")
    
    try:
        # Run demonstrations
        demo_theorem_proving()
        demo_natural_language()
        demo_integrated_workflow()
        demo_complete_example()
        
        # Final summary
        print_section("Summary")
        print("The complete native Python 3 CEC implementation provides:")
        print()
        print("✓ Core DCEC Logic:")
        print("  - Deontic operators (O, P, F, R, etc.)")
        print("  - Cognitive operators (B, K, I, D, G)")
        print("  - Temporal operators (□, ◊, X, U, S)")
        print("  - Logical connectives (∧, ∨, ¬, →, etc.)")
        print()
        print("✓ Theorem Proving:")
        print("  - Forward chaining prover")
        print("  - Modus Ponens, Simplification, etc.")
        print("  - Proof tree generation")
        print("  - Success/failure tracking")
        print()
        print("✓ Natural Language Conversion:")
        print("  - English to DCEC conversion")
        print("  - DCEC to English linearization")
        print("  - Pattern-based matching")
        print("  - 15+ supported patterns")
        print()
        print("✓ Production Ready:")
        print("  - Zero Python 2 dependencies")
        print("  - Full type hints")
        print("  - Comprehensive error handling")
        print("  - Statistics and logging")
        print()
        print("✅ All demonstrations completed successfully!")
        print()
        
    except Exception as e:
        print(f"\n❌ Error during demonstration: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
