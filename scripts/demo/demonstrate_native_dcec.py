#!/usr/bin/env python3
"""
Demonstration of Native Python 3 DCEC Implementation.

This script showcases the pure Python 3 implementation of
Deontic Cognitive Event Calculus, replacing the Python 2 based submodules.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from ipfs_datasets_py.logic.CEC.native import (
    DCECContainer,
    DeonticOperator,
    CognitiveOperator,
    TemporalOperator,
    LogicalConnective,
    Sort,
    Variable,
    Predicate,
    Function,
    VariableTerm,
    FunctionTerm,
    AtomicFormula,
    DeonticFormula,
    CognitiveFormula,
    TemporalFormula,
    ConnectiveFormula,
    QuantifiedFormula,
)


def print_section(title):
    """Print a formatted section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70 + "\n")


def demo_basic_usage():
    """Demonstrate basic DCEC usage."""
    print_section("Basic DCEC Usage")
    
    # Create container
    print("1. Creating DCEC Container...")
    container = DCECContainer()
    print(f"   Container: {container}")
    print(f"   Built-in sorts: {list(container.namespace.sorts.keys())[:5]}...")
    
    # Add custom sorts
    print("\n2. Adding custom sorts...")
    container.namespace.add_sort("Robot", parent="Agent")
    container.namespace.add_sort("Task", parent="Action")
    print("   ✓ Added Robot (subtype of Agent)")
    print("   ✓ Added Task (subtype of Action)")
    
    return container


def demo_deontic_logic(container):
    """Demonstrate deontic (normative) logic."""
    print_section("Deontic Logic - Obligations and Permissions")
    
    # Create predicate and variable
    pred = container.namespace.add_predicate("performTask", ["Robot", "Task"])
    robot = container.namespace.add_variable("r", "Robot")
    task = container.namespace.add_variable("t", "Task")
    
    # Build formula: O(performTask(r, t))
    base_formula = AtomicFormula(pred, [VariableTerm(robot), VariableTerm(task)])
    obligation = DeonticFormula(DeonticOperator.OBLIGATION, base_formula)
    
    # Add to container
    stmt1 = container.add_statement(obligation, label="task_obligation", is_axiom=True)
    print(f"1. Obligation: {stmt1}")
    
    # Create permission: P(performTask(r, t))
    permission = DeonticFormula(DeonticOperator.PERMISSION, base_formula)
    stmt2 = container.add_statement(permission, label="task_permission")
    print(f"2. Permission: {stmt2}")
    
    # Create prohibition: F(performTask(r, t))
    prohibition = DeonticFormula(DeonticOperator.PROHIBITION, base_formula)
    stmt3 = container.add_statement(prohibition, label="task_prohibition")
    print(f"3. Prohibition: {stmt3}")
    
    print(f"\n   Total deontic statements: 3")


def demo_cognitive_logic(container):
    """Demonstrate cognitive (mental state) logic."""
    print_section("Cognitive Logic - Beliefs, Knowledge, Intentions")
    
    # Create predicates
    goal_pred = container.namespace.add_predicate("goalAchieved", [])
    
    # Get robot variable
    robot = container.namespace.get_variable("r")
    
    # Build formulas
    goal_formula = AtomicFormula(goal_pred, [])
    
    # Belief: B(r, goalAchieved)
    belief = CognitiveFormula(CognitiveOperator.BELIEF, VariableTerm(robot), goal_formula)
    stmt1 = container.add_statement(belief, label="robot_belief")
    print(f"1. Belief: {stmt1}")
    
    # Knowledge: K(r, goalAchieved)
    knowledge = CognitiveFormula(CognitiveOperator.KNOWLEDGE, VariableTerm(robot), goal_formula)
    stmt2 = container.add_statement(knowledge, label="robot_knowledge")
    print(f"2. Knowledge: {stmt2}")
    
    # Intention: I(r, goalAchieved)
    intention = CognitiveFormula(CognitiveOperator.INTENTION, VariableTerm(robot), goal_formula)
    stmt3 = container.add_statement(intention, label="robot_intention")
    print(f"3. Intention: {stmt3}")
    
    print(f"\n   Total cognitive statements: 3")


def demo_temporal_logic(container):
    """Demonstrate temporal logic."""
    print_section("Temporal Logic - Time-based Reasoning")
    
    # Get existing predicates and variables
    goal_pred = container.namespace.get_predicate("goalAchieved")
    goal_formula = AtomicFormula(goal_pred, [])
    
    # Eventually: ◊(goalAchieved)
    eventually = TemporalFormula(TemporalOperator.EVENTUALLY, goal_formula)
    stmt1 = container.add_statement(eventually, label="goal_eventually")
    print(f"1. Eventually: {stmt1}")
    
    # Always: □(goalAchieved)
    always = TemporalFormula(TemporalOperator.ALWAYS, goal_formula)
    stmt2 = container.add_statement(always, label="goal_always")
    print(f"2. Always: {stmt2}")
    
    # Next: X(goalAchieved)
    next_time = TemporalFormula(TemporalOperator.NEXT, goal_formula)
    stmt3 = container.add_statement(next_time, label="goal_next")
    print(f"3. Next: {stmt3}")
    
    print(f"\n   Total temporal statements: 3")


def demo_complex_formulas(container):
    """Demonstrate complex formulas with logical connectives."""
    print_section("Complex Formulas - Logical Connectives")
    
    # Create two simple predicates
    p1 = container.namespace.add_predicate("condition1", [])
    p2 = container.namespace.add_predicate("condition2", [])
    
    formula1 = AtomicFormula(p1, [])
    formula2 = AtomicFormula(p2, [])
    
    # AND: condition1 ∧ condition2
    and_formula = ConnectiveFormula(LogicalConnective.AND, [formula1, formula2])
    stmt1 = container.add_statement(and_formula, label="and_formula")
    print(f"1. AND: {stmt1}")
    
    # OR: condition1 ∨ condition2
    or_formula = ConnectiveFormula(LogicalConnective.OR, [formula1, formula2])
    stmt2 = container.add_statement(or_formula, label="or_formula")
    print(f"2. OR: {stmt2}")
    
    # IMPLIES: condition1 → condition2
    implies = ConnectiveFormula(LogicalConnective.IMPLIES, [formula1, formula2])
    stmt3 = container.add_statement(implies, label="implies_formula")
    print(f"3. IMPLIES: {stmt3}")
    
    # NOT: ¬condition1
    not_formula = ConnectiveFormula(LogicalConnective.NOT, [formula1])
    stmt4 = container.add_statement(not_formula, label="not_formula")
    print(f"4. NOT: {stmt4}")
    
    print(f"\n   Total connective formulas: 4")


def demo_quantifiers(container):
    """Demonstrate quantified formulas."""
    print_section("Quantified Formulas - ∀ and ∃")
    
    # Create new variables and predicates for quantification
    x = container.namespace.add_variable("x_quant", "Robot")
    honest_pred = container.namespace.add_predicate("isHonest", ["Robot"])
    
    base_formula = AtomicFormula(honest_pred, [VariableTerm(x)])
    
    # Universal: ∀x(isHonest(x))
    forall = QuantifiedFormula(LogicalConnective.FORALL, x, base_formula)
    stmt1 = container.add_statement(forall, label="all_honest")
    print(f"1. Universal quantification: {stmt1}")
    print(f"   Free variables in formula: {forall.get_free_variables()}")
    
    # Existential: ∃x(isHonest(x))
    exists = QuantifiedFormula(LogicalConnective.EXISTS, x, base_formula)
    stmt2 = container.add_statement(exists, label="some_honest")
    print(f"2. Existential quantification: {stmt2}")
    print(f"   Free variables in formula: {exists.get_free_variables()}")
    
    print(f"\n   Note: Bound variables are not in free variable set")


def demo_combined_example(container):
    """Demonstrate a complex combined example."""
    print_section("Combined Example - Real-world Scenario")
    
    print("Scenario: A robot must complete a task, and it believes it can")
    print()
    
    # Get existing components
    robot = container.namespace.get_variable("r")
    task = container.namespace.get_variable("t")
    perform_pred = container.namespace.get_predicate("performTask")
    
    # Base: performTask(r, t)
    base = AtomicFormula(perform_pred, [VariableTerm(robot), VariableTerm(task)])
    
    # Obligation: O(performTask(r, t))
    obligation = DeonticFormula(DeonticOperator.OBLIGATION, base)
    
    # Belief about obligation: B(r, O(performTask(r, t)))
    belief_obligation = CognitiveFormula(
        CognitiveOperator.BELIEF,
        VariableTerm(robot),
        obligation
    )
    
    # Eventually: ◊(B(r, O(performTask(r, t))))
    eventually_belief = TemporalFormula(TemporalOperator.EVENTUALLY, belief_obligation)
    
    # Add to container
    stmt = container.add_statement(
        eventually_belief,
        label="complex_scenario",
        is_axiom=True
    )
    
    print(f"Combined formula: {stmt}")
    print(f"\nBreakdown:")
    print(f"  - ◊ (Eventually)")
    print(f"  - B(r, ...) (Robot believes)")
    print(f"  - O(...) (Obligation)")
    print(f"  - performTask(r, t) (Base action)")
    print(f"\nMeaning: Eventually, the robot will believe it is obligated to perform the task")


def demo_statistics(container):
    """Show container statistics."""
    print_section("Container Statistics")
    
    stats = container.get_statistics()
    
    print(f"Total statements: {stats['total_statements']}")
    print(f"Axioms: {stats['axioms']}")
    print(f"Theorems: {stats['theorems']}")
    print(f"Labeled statements: {stats['labeled_statements']}")
    print(f"\nNamespace statistics:")
    print(f"  Sorts: {stats['namespace']['sorts']}")
    print(f"  Variables: {stats['namespace']['variables']}")
    print(f"  Functions: {stats['namespace']['functions']}")
    print(f"  Predicates: {stats['namespace']['predicates']}")


def main():
    """Main demonstration function."""
    print("\n" + "╔" + "═" * 68 + "╗")
    print("║" + " " * 8 + "Native Python 3 DCEC Implementation Demo" + " " * 19 + "║")
    print("║" + " " * 8 + "Pure Python 3 - No Legacy Dependencies" + " " * 21 + "║")
    print("╚" + "═" * 68 + "╝")
    
    try:
        # Run demonstrations
        container = demo_basic_usage()
        demo_deontic_logic(container)
        demo_cognitive_logic(container)
        demo_temporal_logic(container)
        demo_complex_formulas(container)
        demo_quantifiers(container)
        demo_combined_example(container)
        demo_statistics(container)
        
        # Summary
        print_section("Summary")
        print("The native Python 3 DCEC implementation provides:")
        print("  ✓ Pure Python 3 - no Python 2 dependencies")
        print("  ✓ Deontic operators (Obligation, Permission, Prohibition, etc.)")
        print("  ✓ Cognitive operators (Belief, Knowledge, Intention, etc.)")
        print("  ✓ Temporal operators (Always, Eventually, Next, etc.)")
        print("  ✓ Logical connectives (AND, OR, NOT, IMPLIES, etc.)")
        print("  ✓ Quantifiers (∀, ∃) with proper variable binding")
        print("  ✓ Type-safe namespace management")
        print("  ✓ Full type hints with beartype validation")
        print()
        print("✅ Demonstration completed successfully!")
        print()
        
    except Exception as e:
        print(f"\n❌ Error during demonstration: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
