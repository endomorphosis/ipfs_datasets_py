"""
Logic Reasoning - Formal Logic and Theorem Proving

This example introduces formal logic and theorem proving capabilities,
including First-Order Logic (FOL), temporal logic, and deontic logic.
These enable automated reasoning and verification.

Requirements:
    - Core ipfs_datasets_py dependencies
    - Optional: z3-solver for advanced proving

Usage:
    python examples/13_logic_reasoning.py
"""

import asyncio


async def demo_first_order_logic():
    """Demonstrate First-Order Logic (FOL)."""
    print("\n" + "="*70)
    print("DEMO 1: First-Order Logic (FOL)")
    print("="*70)
    
    print("\n🧮 First-Order Logic")
    print("   Express statements with quantifiers and predicates")
    
    example_code = '''
from ipfs_datasets_py.logic import FOLEngine

# Initialize FOL engine
fol = FOLEngine()

# Define predicates
fol.define_predicate("Person", arity=1)
fol.define_predicate("Mortal", arity=1)
fol.define_predicate("Human", arity=1)

# Add axioms
fol.add_axiom("∀x (Human(x) → Person(x))")
fol.add_axiom("∀x (Person(x) → Mortal(x))")
fol.add_axiom("Human(Socrates)")

# Prove theorem
theorem = "Mortal(Socrates)"
proof = await fol.prove(theorem)

if proof.is_valid:
    print(f"✅ Proved: {theorem}")
    print(f"\\nProof steps:")
    for i, step in enumerate(proof.steps, 1):
        print(f"{i}. {step.statement} ({step.rule})")
else:
    print(f"❌ Could not prove: {theorem}")
    '''
    
    print(example_code)


async def demo_temporal_logic():
    """Demonstrate temporal logic reasoning."""
    print("\n" + "="*70)
    print("DEMO 2: Temporal Logic")
    print("="*70)
    
    print("\n⏰ Temporal Logic")
    print("   Reason about time and sequences")
    
    example_code = '''
from ipfs_datasets_py.logic import TemporalLogicEngine

# Initialize temporal logic
tl = TemporalLogicEngine()

# Define temporal operators
# G (Globally): always true
# F (Finally): eventually true  
# X (Next): true in next state
# U (Until): true until something else becomes true

# Add temporal axioms
tl.add_axiom("G(Started → F(Completed))")  # If started, eventually completed
tl.add_axiom("G(Completed → X(Archived))")  # After completed, next is archived

# Define states
tl.add_fact("Started", time=0)

# Check temporal properties
will_complete = await tl.check("F(Completed)", time=0)
print(f"Will complete: {will_complete}")

will_archive = await tl.check("F(Archived)", time=0)
print(f"Will archive: {will_archive}")

# Generate timeline
timeline = await tl.generate_timeline(
    initial_state=["Started"],
    max_time=10
)

for t, state in timeline.items():
    print(f"Time {t}: {', '.join(state)}")
    '''
    
    print(example_code)


async def demo_deontic_logic():
    """Demonstrate deontic logic (obligations and permissions)."""
    print("\n" + "="*70)
    print("DEMO 3: Deontic Logic")
    print("="*70)
    
    print("\n⚖️  Deontic Logic")
    print("   Reason about obligations, permissions, and prohibitions")
    
    example_code = '''
from ipfs_datasets_py.logic import DeonticLogicEngine

# Initialize deontic logic
dl = DeonticLogicEngine()

# Define deontic operators
# O (Obligatory): must do
# P (Permitted): may do
# F (Forbidden): must not do

# Add deontic rules
dl.add_rule("O(FileTaxes)")  # Obligated to file taxes
dl.add_rule("P(Vote)")       # Permitted to vote
dl.add_rule("F(Steal)")      # Forbidden to steal

# Logical relationships
dl.add_rule("O(X) → P(X)")   # Obligatory implies permitted
dl.add_rule("F(X) → ¬P(X)")  # Forbidden implies not permitted

# Check deontic properties
must_file = await dl.check("O(FileTaxes)")
print(f"Must file taxes: {must_file}")

can_vote = await dl.check("P(Vote)")
print(f"Can vote: {can_vote}")

can_steal = await dl.check("P(Steal)")
print(f"Can steal: {can_steal}")  # Should be False

# Detect conflicts
conflicts = await dl.find_conflicts()
for conflict in conflicts:
    print(f"Conflict: {conflict}")
    '''
    
    print(example_code)


async def demo_theorem_proving():
    """Use Z3 theorem prover for complex proofs."""
    print("\n" + "="*70)
    print("DEMO 4: Theorem Proving with Z3")
    print("="*70)
    
    print("\n🔬 Z3 Theorem Prover")
    print("   SMT (Satisfiability Modulo Theories) solving")
    
    example_code = '''
from ipfs_datasets_py.logic import Z3TheoremProver

prover = Z3TheoremProver()

# Define variables
prover.declare_int("x")
prover.declare_int("y")

# Add constraints
prover.add_constraint("x + y == 10")
prover.add_constraint("x > y")
prover.add_constraint("x > 0")
prover.add_constraint("y > 0")

# Find solution
solution = await prover.solve()

if solution.is_satisfiable:
    print("✅ Solution found:")
    print(f"   x = {solution.model['x']}")
    print(f"   y = {solution.model['y']}")
else:
    print("❌ No solution exists")

# Prove theorem
theorem = "x > 5"
proof = await prover.prove(theorem)

print(f"\\nTheorem '{theorem}': {proof.is_valid}")
    '''
    
    print(example_code)
    
    print("\n💡 Install Z3: pip install z3-solver")


async def demo_logic_to_text():
    """Convert between natural language and formal logic."""
    print("\n" + "="*70)
    print("DEMO 5: Natural Language ↔ Logic")
    print("="*70)
    
    print("\n💬 Natural Language to Logic")
    print("   Parse and generate logical statements")
    
    example_code = '''
from ipfs_datasets_py.logic import LogicParser, LogicGenerator

# Parse natural language to logic
parser = LogicParser()

text = "All humans are mortal. Socrates is human."
statements = await parser.parse(text)

for stmt in statements:
    print(f"Text: {stmt.text}")
    print(f"Logic: {stmt.formula}")
    print(f"Type: {stmt.type}")
    print()

# Generate natural language from logic
generator = LogicGenerator()

formula = "∀x (Human(x) → Mortal(x))"
text = await generator.generate(formula)

print(f"Formula: {formula}")
print(f"Text: {text}")

# Complex example
legal_text = """
If a person is over 18 and has not been convicted of a felony,
then they are permitted to vote.
"""

logic = await parser.parse(legal_text)
print(f"\\nLegal text as logic:")
print(f"{logic[0].formula}")
    '''
    
    print(example_code)


async def demo_constraint_solving():
    """Solve constraint satisfaction problems."""
    print("\n" + "="*70)
    print("DEMO 6: Constraint Satisfaction")
    print("="*70)
    
    print("\n🧩 Constraint Satisfaction Problems")
    
    example_code = '''
from ipfs_datasets_py.logic import ConstraintSolver

solver = ConstraintSolver()

# Example: Schedule meetings
# 3 meetings, 4 time slots, constraints on conflicts

solver.declare_vars({
    "meeting1": [0, 1, 2, 3],  # Possible time slots
    "meeting2": [0, 1, 2, 3],
    "meeting3": [0, 1, 2, 3],
})

# Constraints
solver.add_constraint("meeting1 != meeting2")  # Can't overlap
solver.add_constraint("meeting2 != meeting3")
solver.add_constraint("meeting1 < meeting3")   # Meeting 1 before 3

# Solve
solution = await solver.solve()

if solution:
    print("Schedule found:")
    print(f"  Meeting 1: Time slot {solution['meeting1']}")
    print(f"  Meeting 2: Time slot {solution['meeting2']}")
    print(f"  Meeting 3: Time slot {solution['meeting3']}")

# Find all solutions
all_solutions = await solver.solve_all()
print(f"\\nFound {len(all_solutions)} possible schedules")
    '''
    
    print(example_code)


async def demo_logic_validation():
    """Validate logical consistency."""
    print("\n" + "="*70)
    print("DEMO 7: Logic Validation")
    print("="*70)
    
    print("\n✅ Consistency Checking")
    
    example_code = '''
from ipfs_datasets_py.logic import LogicValidator

validator = LogicValidator()

# Check if set of statements is consistent
statements = [
    "∀x (Bird(x) → CanFly(x))",
    "Bird(Penguin)",
    "¬CanFly(Penguin)"
]

is_consistent = await validator.check_consistency(statements)
print(f"Consistent: {is_consistent}")

if not is_consistent:
    # Find minimal inconsistent subset
    conflicts = await validator.find_conflicts(statements)
    print("\\nConflicting statements:")
    for conflict in conflicts:
        for stmt in conflict:
            print(f"  - {stmt}")

# Suggest fixes
fixes = await validator.suggest_fixes(statements)
print("\\nSuggested fixes:")
for fix in fixes:
    print(f"  - {fix.description}")
    print(f"    Change: {fix.original} → {fix.fixed}")
    '''
    
    print(example_code)


def show_tips():
    """Show tips for logic reasoning."""
    print("\n" + "="*70)
    print("TIPS FOR LOGIC REASONING")
    print("="*70)
    
    print("\n1. Choosing Logic Systems:")
    print("   - FOL: General purpose, most expressive")
    print("   - Temporal: Time-based reasoning, workflows")
    print("   - Deontic: Legal/ethical reasoning")
    print("   - Modal: Necessity and possibility")
    
    print("\n2. Theorem Proving:")
    print("   - Start with simple proofs")
    print("   - Use Z3 for complex constraints")
    print("   - Cache proven theorems")
    print("   - Limit proof search depth")
    
    print("\n3. Performance:")
    print("   - Logic reasoning can be computationally expensive")
    print("   - Use caching aggressively")
    print("   - Simplify formulas when possible")
    print("   - Consider approximate reasoning for scale")
    
    print("\n4. Practical Applications:")
    print("   - Verification and validation")
    print("   - Policy compliance checking")
    print("   - Automated reasoning in RAG")
    print("   - Knowledge base consistency")
    
    print("\n5. Integration:")
    print("   - Combine with knowledge graphs")
    print("   - Use in RAG for constraint-based retrieval")
    print("   - Validate extracted information")
    print("   - Generate explanations")
    
    print("\n6. Debugging:")
    print("   - Check axiom consistency")
    print("   - Validate predicate definitions")
    print("   - Test with simple examples first")
    print("   - Use proof visualization")
    
    print("\n7. Advanced Topics:")
    print("   - See neurosymbolic/ examples for neural+symbolic")
    print("   - See external_provers/ for Z3 integration")
    print("   - See 16_logic_enhanced_rag.py for RAG integration")
    
    print("\n8. Resources:")
    print("   - Learn formal logic fundamentals")
    print("   - Study SMT solving")
    print("   - Practice with simple examples")


async def main():
    """Run all logic reasoning demonstrations."""
    print("\n" + "="*70)
    print("IPFS DATASETS PYTHON - LOGIC REASONING")
    print("="*70)
    
    await demo_first_order_logic()
    await demo_temporal_logic()
    await demo_deontic_logic()
    await demo_theorem_proving()
    await demo_logic_to_text()
    await demo_constraint_solving()
    await demo_logic_validation()
    
    show_tips()
    
    print("\n" + "="*70)
    print("✅ LOGIC REASONING EXAMPLES COMPLETE")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
