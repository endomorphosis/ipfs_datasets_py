"""
Example: TDFOL Formula Dependency Graph Analysis

This example demonstrates the comprehensive formula dependency graph module:
1. Building dependency graphs from proofs and knowledge bases
2. Analyzing formula relationships and dependencies
3. Finding critical proof paths
4. Detecting unused axioms and redundant formulas
5. Exporting in multiple formats (DOT, JSON, adjacency matrix)
6. Visualizing with GraphViz

Phase 11 Task 11.2 - Formula Dependency Graph Module
"""

import tempfile
from pathlib import Path

from ipfs_datasets_py.logic.TDFOL import (
    BinaryFormula,
    CircularDependencyError,
    DependencyType,
    FormulaDependencyGraph,
    FormulaType,
    LogicOperator,
    Predicate,
    ProofResult,
    ProofStatus,
    ProofStep,
    TDFOLKnowledgeBase,
    Variable,
    analyze_proof_dependencies,
    create_implication,
    find_proof_chain,
)


def example_simple_linear_proof():
    """Example 1: Simple linear proof chain."""
    print("=" * 70)
    print("Example 1: Simple Linear Proof Chain")
    print("=" * 70)
    
    # Create formulas: P → Q → R
    p = Predicate("Person", (Variable("x"),))
    q = Predicate("Mortal", (Variable("x"),))
    r = Predicate("Dies", (Variable("x"),))
    
    print(f"\nFormulas:")
    print(f"  P: {p}")
    print(f"  Q: {q}")
    print(f"  R: {r}")
    
    # Create proof result
    proof = ProofResult(
        status=ProofStatus.PROVED,
        formula=r,
        proof_steps=[
            ProofStep(p, "Given axiom", "Axiom", []),
            ProofStep(q, "All persons are mortal", "ModusPonens", [p]),
            ProofStep(r, "All mortals die", "ModusPonens", [q])
        ],
        time_ms=5.0,
        method="forward_chaining"
    )
    
    # Build dependency graph
    graph = FormulaDependencyGraph(proof_result=proof)
    
    print(f"\nGraph Statistics:")
    stats = graph.get_statistics()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    # Find critical path
    path = graph.find_critical_path(p, r)
    print(f"\nCritical Path from {p} to {r}:")
    for i, formula in enumerate(path):
        print(f"  Step {i+1}: {formula}")
    
    # Get dependencies
    print(f"\nDependencies of {r}:")
    deps = graph.get_dependencies(r)
    for dep in deps:
        print(f"  - {dep}")
    
    print(f"\nAll transitive dependencies of {r}:")
    all_deps = graph.get_all_dependencies(r)
    for dep in all_deps:
        print(f"  - {dep}")
    
    return graph


def example_branching_proof():
    """Example 2: Branching proof with multiple premises."""
    print("\n" + "=" * 70)
    print("Example 2: Branching Proof (Multiple Premises)")
    print("=" * 70)
    
    # Create formulas
    # P: "It is raining"
    # Q: "The ground is wet"
    # R: "It is cold"
    # S: "Slippery conditions"
    p = Predicate("Raining", ())
    q = Predicate("WetGround", ())
    r = Predicate("Cold", ())
    s = Predicate("Slippery", ())
    
    print(f"\nFormulas:")
    print(f"  P: {p} (It is raining)")
    print(f"  Q: {q} (Ground is wet)")
    print(f"  R: {r} (It is cold)")
    print(f"  S: {s} (Slippery conditions)")
    
    # Build graph manually
    graph = FormulaDependencyGraph()
    
    # Add axioms
    graph.add_formula(p, [], "Axiom", node_type=FormulaType.AXIOM)
    graph.add_formula(r, [], "Axiom", node_type=FormulaType.AXIOM)
    
    # Derive Q from P
    graph.add_formula(q, [p], "ImplicationElimination", 
                     "Rain makes ground wet")
    
    # Derive S from Q and R (both needed)
    graph.add_formula(s, [q, r], "ConjunctionIntro",
                     "Wet + Cold = Slippery")
    
    print(f"\nGraph Statistics:")
    stats = graph.get_statistics()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    # Find paths from each axiom to conclusion
    print(f"\nPath from {p} to {s}:")
    path1 = graph.find_critical_path(p, s)
    if path1:
        for i, formula in enumerate(path1):
            print(f"  Step {i+1}: {formula}")
    
    print(f"\nPath from {r} to {s}:")
    path2 = graph.find_critical_path(r, s)
    if path2:
        for i, formula in enumerate(path2):
            print(f"  Step {i+1}: {formula}")
    
    # Topological sort
    print(f"\nTopological Order:")
    order = graph.topological_sort()
    for i, formula in enumerate(order):
        print(f"  {i+1}. {formula}")
    
    return graph


def example_knowledge_base():
    """Example 3: Building graph from knowledge base."""
    print("\n" + "=" * 70)
    print("Example 3: Knowledge Base with Theorems")
    print("=" * 70)
    
    # Create knowledge base
    kb = TDFOLKnowledgeBase()
    
    # Add axioms
    axiom1 = Predicate("Socrates", ())
    axiom2 = create_implication(
        Predicate("Man", (Variable("x"),)),
        Predicate("Mortal", (Variable("x"),))
    )
    
    kb.add_axiom(axiom1, "socrates_is_man")
    kb.add_axiom(axiom2, "men_are_mortal")
    
    # Add theorem
    theorem = Predicate("Mortal", (Variable("socrates"),))
    kb.add_theorem(theorem, "socrates_is_mortal")
    
    print(f"\nKnowledge Base:")
    print(f"  Axioms: {len(kb.axioms)}")
    print(f"  Theorems: {len(kb.theorems)}")
    
    # Build graph
    graph = FormulaDependencyGraph(kb=kb)
    
    print(f"\nGraph Statistics:")
    stats = graph.get_statistics()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    # Find unused axioms (before adding proof)
    unused = graph.find_unused_axioms()
    print(f"\nUnused Axioms: {len(unused)}")
    for axiom in unused:
        print(f"  - {axiom}")
    
    # Add a proof that uses axiom1
    proof = ProofResult(
        status=ProofStatus.PROVED,
        formula=theorem,
        proof_steps=[
            ProofStep(axiom1, "Given", "Axiom", []),
            ProofStep(axiom2, "Given", "Axiom", []),
            ProofStep(theorem, "By Modus Ponens", "ModusPonens", [axiom1, axiom2])
        ]
    )
    graph.add_proof(proof)
    
    # Check unused axioms again
    unused_after = graph.find_unused_axioms()
    print(f"\nUnused Axioms After Adding Proof: {len(unused_after)}")
    for axiom in unused_after:
        print(f"  - {axiom}")
    
    return graph, kb


def example_cycle_detection():
    """Example 4: Detecting circular dependencies."""
    print("\n" + "=" * 70)
    print("Example 4: Circular Dependency Detection")
    print("=" * 70)
    
    # Create formulas
    p = Predicate("P", ())
    q = Predicate("Q", ())
    r = Predicate("R", ())
    
    print(f"\nAttempting to create circular dependency: P → Q → P")
    
    # Build graph with cycle
    graph = FormulaDependencyGraph()
    graph.add_formula(p, [], "Axiom", node_type=FormulaType.AXIOM)
    graph.add_formula(q, [p], "Rule1", "Q from P")
    graph.add_formula(p, [q], "Rule2", "P from Q (creates cycle!)")
    
    # Detect cycles
    cycles = graph.detect_cycles()
    print(f"\nCycles Detected: {len(cycles)}")
    for i, cycle in enumerate(cycles):
        print(f"\n  Cycle {i+1}:")
        for formula in cycle:
            print(f"    → {formula}")
    
    # Try topological sort (should fail)
    print(f"\nAttempting topological sort...")
    try:
        order = graph.topological_sort()
        print(f"  Success: {len(order)} formulas ordered")
    except CircularDependencyError as e:
        print(f"  ERROR: {e.message}")
    
    # Create acyclic graph
    print(f"\n\nCreating acyclic graph: P → Q → R")
    graph2 = FormulaDependencyGraph()
    graph2.add_formula(p, [], "Axiom", node_type=FormulaType.AXIOM)
    graph2.add_formula(q, [p], "Rule1", "Q from P")
    graph2.add_formula(r, [q], "Rule2", "R from Q")
    
    cycles2 = graph2.detect_cycles()
    print(f"Cycles Detected: {len(cycles2)}")
    
    print(f"\nTopological Sort:")
    order = graph2.topological_sort()
    for i, formula in enumerate(order):
        print(f"  {i+1}. {formula}")


def example_multiple_paths():
    """Example 5: Multiple paths between formulas."""
    print("\n" + "=" * 70)
    print("Example 5: Multiple Paths Between Formulas")
    print("=" * 70)
    
    # Create complex graph with multiple paths
    #     P → Q ↘
    #     ↓       → S
    #     R → T ↗
    
    p = Predicate("P", ())
    q = Predicate("Q", ())
    r = Predicate("R", ())
    t = Predicate("T", ())
    s = Predicate("S", ())
    
    graph = FormulaDependencyGraph()
    
    # Build graph
    graph.add_formula(p, [], "Axiom", node_type=FormulaType.AXIOM)
    graph.add_formula(q, [p], "Rule1", "Q from P")
    graph.add_formula(r, [p], "Rule2", "R from P")
    graph.add_formula(t, [r], "Rule3", "T from R")
    graph.add_formula(s, [q], "Rule4", "S from Q")
    graph.add_formula(s, [t], "Rule5", "S from T (alternative)")
    
    print(f"\nGraph Structure:")
    print(f"  P → Q → S")
    print(f"  P → R → T → S")
    print(f"  (Two paths from P to S)")
    
    # Find critical path (shortest)
    critical = graph.find_critical_path(p, s)
    print(f"\nCritical Path (shortest):")
    for i, formula in enumerate(critical):
        print(f"  Step {i+1}: {formula}")
    
    # Find all paths
    all_paths = graph.find_all_paths(p, s, max_length=5)
    print(f"\nAll Paths from P to S: {len(all_paths)}")
    for i, path in enumerate(all_paths):
        print(f"\n  Path {i+1} (length {len(path)}):")
        for j, formula in enumerate(path):
            if j < len(path) - 1:
                print(f"    {formula} →")
            else:
                print(f"    {formula}")
    
    return graph


def example_export_formats():
    """Example 6: Exporting in multiple formats."""
    print("\n" + "=" * 70)
    print("Example 6: Export Formats")
    print("=" * 70)
    
    # Create a proof graph
    p = Predicate("Axiom1", ())
    q = Predicate("Lemma1", ())
    r = Predicate("Theorem1", ())
    
    proof = ProofResult(
        status=ProofStatus.PROVED,
        formula=r,
        proof_steps=[
            ProofStep(p, "Given", "Axiom", []),
            ProofStep(q, "Intermediate", "Lemma", [p]),
            ProofStep(r, "Final result", "Theorem", [q])
        ],
        time_ms=8.5,
        method="forward_chaining"
    )
    
    graph = FormulaDependencyGraph(proof_result=proof)
    
    # Export to different formats
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        
        # DOT format
        dot_path = output_dir / "dependencies.dot"
        graph.export_dot(dot_path, highlight_path=[p, q, r])
        print(f"\n✓ Exported DOT: {dot_path}")
        print(f"  Size: {dot_path.stat().st_size} bytes")
        
        # JSON format
        json_path = output_dir / "dependencies.json"
        graph.export_json(json_path)
        print(f"\n✓ Exported JSON: {json_path}")
        print(f"  Size: {json_path.stat().st_size} bytes")
        
        # Adjacency matrix
        csv_path = output_dir / "matrix.csv"
        graph.export_adjacency_matrix(csv_path)
        print(f"\n✓ Exported Adjacency Matrix: {csv_path}")
        print(f"  Size: {csv_path.stat().st_size} bytes")
        
        # Show DOT content
        print(f"\nDOT Content Preview:")
        dot_content = dot_path.read_text()
        lines = dot_content.split('\n')[:15]
        for line in lines:
            print(f"  {line}")
        if len(dot_content.split('\n')) > 15:
            print(f"  ... ({len(dot_content.split('\n')) - 15} more lines)")


def example_convenience_functions():
    """Example 7: Using convenience functions."""
    print("\n" + "=" * 70)
    print("Example 7: Convenience Functions")
    print("=" * 70)
    
    # Create proof
    p = Predicate("Premise", ())
    q = Predicate("Intermediate", ())
    r = Predicate("Conclusion", ())
    
    proof = ProofResult(
        status=ProofStatus.PROVED,
        formula=r,
        proof_steps=[
            ProofStep(p, "Given", "Axiom", []),
            ProofStep(q, "Step 1", "Rule1", [p]),
            ProofStep(r, "Step 2", "Rule2", [q])
        ],
        time_ms=12.0,
        method="forward_chaining"
    )
    
    # Use analyze_proof_dependencies
    print(f"\n1. Analyzing proof with automatic export...")
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        graph = analyze_proof_dependencies(proof, output_dir)
        
        print(f"   ✓ Created graph with {len(graph.nodes)} nodes")
        print(f"   ✓ Exported to: {output_dir}")
        
        files = list(output_dir.glob("*"))
        for f in files:
            print(f"     - {f.name}")
    
    # Use find_proof_chain
    print(f"\n2. Finding proof chain...")
    kb = TDFOLKnowledgeBase()
    kb.add_axiom(p, "axiom_p")
    
    chain = find_proof_chain(p, r, kb, [proof])
    if chain:
        print(f"   ✓ Found chain with {len(chain)} steps:")
        for i, formula in enumerate(chain):
            print(f"     {i+1}. {formula}")


def example_redundant_formulas():
    """Example 8: Finding redundant formulas."""
    print("\n" + "=" * 70)
    print("Example 8: Finding Redundant Formulas")
    print("=" * 70)
    
    # Create graph where some formulas are redundant
    p = Predicate("P", ())
    q = Predicate("Q", ())
    r = Predicate("R", ())
    s = Predicate("S", ())
    
    graph = FormulaDependencyGraph()
    
    # P is axiom
    graph.add_formula(p, [], "Axiom", node_type=FormulaType.AXIOM)
    
    # Q depends on P
    graph.add_formula(q, [p], "Rule1")
    
    # R depends on Q (and transitively on P)
    graph.add_formula(r, [q], "Rule2")
    
    # S is independent axiom
    graph.add_formula(s, [], "Axiom", node_type=FormulaType.AXIOM)
    
    print(f"\nGraph Structure:")
    print(f"  P → Q → R")
    print(f"  S (independent)")
    
    # Find redundant formulas
    redundant = graph.find_redundant_formulas()
    print(f"\nRedundant Formulas: {len(redundant)}")
    for f1, f2 in redundant:
        print(f"  - {f1} depends on {f2}")
    
    # Show dependency relationships
    print(f"\nAll Dependencies of R:")
    r_deps = graph.get_all_dependencies(r)
    for dep in r_deps:
        print(f"  - {dep}")


def main():
    """Run all examples."""
    print("\n" + "=" * 70)
    print("TDFOL Formula Dependency Graph - Comprehensive Examples")
    print("Phase 11 Task 11.2")
    print("=" * 70)
    
    # Run examples
    example_simple_linear_proof()
    example_branching_proof()
    example_knowledge_base()
    example_cycle_detection()
    example_multiple_paths()
    example_export_formats()
    example_convenience_functions()
    example_redundant_formulas()
    
    print("\n" + "=" * 70)
    print("All Examples Completed Successfully!")
    print("=" * 70)


if __name__ == "__main__":
    main()
