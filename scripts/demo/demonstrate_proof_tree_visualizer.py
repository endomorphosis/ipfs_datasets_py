#!/usr/bin/env python3
"""
Demonstration of TDFOL Proof Tree Visualizer

This script demonstrates the various visualization capabilities of the
proof tree visualizer module, including:
- ASCII tree rendering with different styles
- GraphViz DOT export
- SVG/PNG rendering
- Interactive HTML output
- JSON export

Usage:
    python demonstrate_proof_tree_visualizer.py [--output-dir OUTPUT_DIR]
"""

import argparse
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ipfs_datasets_py.logic.TDFOL.proof_tree_visualizer import (
    ProofTreeVisualizer,
    VerbosityLevel,
    visualize_proof,
)
from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
    BinaryFormula,
    DeonticFormula,
    DeonticOperator,
    LogicOperator,
    Predicate,
    QuantifiedFormula,
    Quantifier,
    TemporalFormula,
    TemporalOperator,
    Variable,
)
from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult, ProofStatus, ProofStep


def create_simple_proof() -> ProofResult:
    """
    Create a simple proof: A, B ⊢ A ∧ B
    
    Returns:
        ProofResult with simple conjunction proof
    """
    print("\n" + "="*70)
    print("Creating Simple Proof: A, B ⊢ A ∧ B")
    print("="*70)
    
    # Step 1: A (axiom)
    step1 = ProofStep(
        formula=Predicate("A", []),
        justification="Given axiom",
        rule_name="Axiom",
        premises=[]
    )
    
    # Step 2: B (axiom)
    step2 = ProofStep(
        formula=Predicate("B", []),
        justification="Given axiom",
        rule_name="Axiom",
        premises=[]
    )
    
    # Step 3: A ∧ B (conjunction)
    step3 = ProofStep(
        formula=BinaryFormula(
            LogicOperator.AND,
            Predicate("A", []),
            Predicate("B", [])
        ),
        justification="Conjunction introduction from A and B",
        rule_name="AND-Introduction",
        premises=[step1.formula, step2.formula]
    )
    
    return ProofResult(
        status=ProofStatus.PROVED,
        formula=step3.formula,
        proof_steps=[step1, step2, step3],
        time_ms=12.5,
        method="forward_chaining",
        message="Simple conjunction proof completed"
    )


def create_complex_proof() -> ProofResult:
    """
    Create a complex proof with modus ponens: P(x), P(x) → Q(y) ⊢ Q(y) ∧ R
    
    Returns:
        ProofResult with branching proof structure
    """
    print("\n" + "="*70)
    print("Creating Complex Proof: P(x), P(x) → Q(y) ⊢ Q(y) ∧ R")
    print("="*70)
    
    # Step 1: P(x) - premise
    step1 = ProofStep(
        formula=Predicate("P", [Variable("x")]),
        justification="Given premise",
        rule_name="Premise",
        premises=[]
    )
    
    # Step 2: P(x) → Q(y) - axiom
    step2 = ProofStep(
        formula=BinaryFormula(
            LogicOperator.IMPLIES,
            Predicate("P", [Variable("x")]),
            Predicate("Q", [Variable("y")])
        ),
        justification="Implication axiom",
        rule_name="Axiom",
        premises=[]
    )
    
    # Step 3: Q(y) - modus ponens
    step3 = ProofStep(
        formula=Predicate("Q", [Variable("y")]),
        justification="Modus Ponens: From P(x) and P(x) → Q(y), derive Q(y)",
        rule_name="ModusPonens",
        premises=[step1.formula, step2.formula]
    )
    
    # Step 4: R - axiom
    step4 = ProofStep(
        formula=Predicate("R", []),
        justification="Additional axiom",
        rule_name="Axiom",
        premises=[]
    )
    
    # Step 5: Q(y) ∧ R - conjunction
    step5 = ProofStep(
        formula=BinaryFormula(
            LogicOperator.AND,
            Predicate("Q", [Variable("y")]),
            Predicate("R", [])
        ),
        justification="Conjunction of Q(y) and R",
        rule_name="AND-Introduction",
        premises=[step3.formula, step4.formula]
    )
    
    return ProofResult(
        status=ProofStatus.PROVED,
        formula=step5.formula,
        proof_steps=[step1, step2, step3, step4, step5],
        time_ms=38.7,
        method="backward_chaining",
        message="Complex proof with branching completed"
    )


def create_tdfol_proof() -> ProofResult:
    """
    Create a TDFOL-specific proof with temporal and deontic operators.
    
    Proof: Agent(x) → O(□(Responsible(x)))
    "If x is an agent, then it is obligatory that x is always responsible"
    
    Returns:
        ProofResult with TDFOL operators
    """
    print("\n" + "="*70)
    print("Creating TDFOL Proof: Agent(x) → O(□(Responsible(x)))")
    print("="*70)
    
    # Step 1: Agent(x) - premise
    step1 = ProofStep(
        formula=Predicate("Agent", [Variable("x")]),
        justification="Assume x is an agent",
        rule_name="Assumption",
        premises=[]
    )
    
    # Step 2: Responsible(x) - from agent axiom
    step2 = ProofStep(
        formula=Predicate("Responsible", [Variable("x")]),
        justification="Agents must be responsible",
        rule_name="AgentResponsibility",
        premises=[step1.formula]
    )
    
    # Step 3: □(Responsible(x)) - temporal necessity
    step3 = ProofStep(
        formula=TemporalFormula(
            TemporalOperator.ALWAYS,
            Predicate("Responsible", [Variable("x")])
        ),
        justification="Temporal necessitation: Always responsible",
        rule_name="TemporalNecessitation",
        premises=[step2.formula]
    )
    
    # Step 4: O(□(Responsible(x))) - deontic obligation
    step4 = ProofStep(
        formula=DeonticFormula(
            DeonticOperator.OBLIGATION,
            TemporalFormula(
                TemporalOperator.ALWAYS,
                Predicate("Responsible", [Variable("x")])
            )
        ),
        justification="Deontic obligation: It is obligatory",
        rule_name="DeonticNecessitation",
        premises=[step3.formula]
    )
    
    # Step 5: Agent(x) → O(□(Responsible(x))) - implication
    step5 = ProofStep(
        formula=BinaryFormula(
            LogicOperator.IMPLIES,
            Predicate("Agent", [Variable("x")]),
            DeonticFormula(
                DeonticOperator.OBLIGATION,
                TemporalFormula(
                    TemporalOperator.ALWAYS,
                    Predicate("Responsible", [Variable("x")])
                )
            )
        ),
        justification="Implication introduction from assumption",
        rule_name="IMPLIES-Introduction",
        premises=[step1.formula, step4.formula]
    )
    
    return ProofResult(
        status=ProofStatus.PROVED,
        formula=step5.formula,
        proof_steps=[step1, step2, step3, step4, step5],
        time_ms=65.3,
        method="natural_deduction",
        message="TDFOL proof with temporal and deontic operators completed"
    )


def demonstrate_ascii_rendering(proof: ProofResult) -> None:
    """Demonstrate ASCII rendering with different styles."""
    print("\n" + "="*70)
    print("ASCII RENDERING DEMONSTRATIONS")
    print("="*70)
    
    visualizer = ProofTreeVisualizer(proof)
    
    # Compact style
    print("\n--- Compact Style (no colors) ---")
    print(visualizer.render_ascii(style='compact', colors=False, max_width=100))
    
    # Expanded style
    print("\n--- Expanded Style (no colors) ---")
    print(visualizer.render_ascii(style='expanded', colors=False, max_width=100))
    
    # Detailed style
    print("\n--- Detailed Style (with colors) ---")
    print(visualizer.render_ascii(style='detailed', colors=True, max_width=100))
    
    # Minimal verbosity
    print("\n--- Minimal Verbosity ---")
    minimal_viz = ProofTreeVisualizer(proof, VerbosityLevel.MINIMAL)
    print(minimal_viz.render_ascii(colors=False))


def demonstrate_file_exports(proof: ProofResult, output_dir: Path) -> None:
    """Demonstrate exporting to various file formats."""
    print("\n" + "="*70)
    print("FILE EXPORT DEMONSTRATIONS")
    print("="*70)
    
    visualizer = ProofTreeVisualizer(proof)
    
    # DOT export
    dot_path = output_dir / "proof.dot"
    print(f"\n✓ Exporting to DOT: {dot_path}")
    visualizer.export_dot(str(dot_path))
    print(f"  DOT file created ({dot_path.stat().st_size} bytes)")
    
    # JSON export
    json_path = output_dir / "proof.json"
    print(f"\n✓ Exporting to JSON: {json_path}")
    visualizer.export_json(str(json_path), indent=2)
    print(f"  JSON file created ({json_path.stat().st_size} bytes)")
    
    # SVG export (requires GraphViz)
    svg_path = output_dir / "proof.svg"
    print(f"\n✓ Attempting SVG export: {svg_path}")
    try:
        visualizer.render_svg(str(svg_path))
        print(f"  SVG file created ({svg_path.stat().st_size} bytes)")
    except (RuntimeError, FileNotFoundError) as e:
        print(f"  ⚠ SVG export skipped (GraphViz not available): {e}")
    
    # PNG export (requires GraphViz)
    png_path = output_dir / "proof.png"
    print(f"\n✓ Attempting PNG export: {png_path}")
    try:
        visualizer.render_png(str(png_path))
        print(f"  PNG file created ({png_path.stat().st_size} bytes)")
    except (RuntimeError, FileNotFoundError) as e:
        print(f"  ⚠ PNG export skipped (GraphViz not available): {e}")
    
    # HTML export (requires GraphViz for embedded SVG)
    html_path = output_dir / "proof.html"
    print(f"\n✓ Attempting HTML export: {html_path}")
    try:
        visualizer.render_html(str(html_path), interactive=True)
        print(f"  HTML file created ({html_path.stat().st_size} bytes)")
        print(f"  Open in browser: file://{html_path.absolute()}")
    except (RuntimeError, FileNotFoundError) as e:
        print(f"  ⚠ HTML export skipped (GraphViz not available): {e}")


def demonstrate_convenience_function(proof: ProofResult) -> None:
    """Demonstrate the convenience visualize_proof function."""
    print("\n" + "="*70)
    print("CONVENIENCE FUNCTION DEMONSTRATION")
    print("="*70)
    
    # ASCII output (returned as string)
    print("\n✓ Using visualize_proof() for ASCII:")
    output = visualize_proof(proof, output_format='ascii', colors=False, style='compact')
    print(output[:500] + "...\n" if len(output) > 500 else output)


def main():
    """Main demonstration function."""
    parser = argparse.ArgumentParser(
        description="Demonstrate TDFOL Proof Tree Visualizer"
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        default='./proof_visualizations',
        help='Directory for output files (default: ./proof_visualizations)'
    )
    args = parser.parse_args()
    
    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("\n" + "="*70)
    print("TDFOL PROOF TREE VISUALIZER DEMONSTRATION")
    print("="*70)
    print(f"\nOutput directory: {output_dir.absolute()}")
    
    # 1. Simple proof
    simple_proof = create_simple_proof()
    demonstrate_ascii_rendering(simple_proof)
    
    # 2. Complex proof
    complex_proof = create_complex_proof()
    demonstrate_file_exports(complex_proof, output_dir)
    
    # 3. TDFOL-specific proof
    tdfol_proof = create_tdfol_proof()
    demonstrate_convenience_function(tdfol_proof)
    
    # Create all visualizations for TDFOL proof
    print("\n" + "="*70)
    print("Creating all visualizations for TDFOL proof...")
    print("="*70)
    
    tdfol_visualizer = ProofTreeVisualizer(tdfol_proof)
    
    # Export all formats
    tdfol_visualizer.export_dot(str(output_dir / "tdfol_proof.dot"))
    tdfol_visualizer.export_json(str(output_dir / "tdfol_proof.json"))
    
    try:
        tdfol_visualizer.render_svg(str(output_dir / "tdfol_proof.svg"))
        tdfol_visualizer.render_html(str(output_dir / "tdfol_proof.html"))
    except (RuntimeError, FileNotFoundError):
        pass
    
    # Summary
    print("\n" + "="*70)
    print("DEMONSTRATION COMPLETE")
    print("="*70)
    print(f"\nGenerated files in: {output_dir.absolute()}")
    print("\nFiles created:")
    for file in sorted(output_dir.glob("*")):
        print(f"  - {file.name} ({file.stat().st_size} bytes)")
    
    print("\nVisualization capabilities:")
    print("  ✓ ASCII tree rendering (compact, expanded, detailed)")
    print("  ✓ Terminal colors (colorama)")
    print("  ✓ GraphViz DOT export")
    print("  ✓ SVG rendering (requires GraphViz)")
    print("  ✓ PNG rendering (requires GraphViz)")
    print("  ✓ Interactive HTML (requires GraphViz)")
    print("  ✓ JSON export")
    print("  ✓ Multiple verbosity levels")
    print("  ✓ Collapsible sub-proofs")
    print("  ✓ Inference rule annotations")
    print("  ✓ Node type highlighting")
    
    print("\nNext steps:")
    print("  1. Open HTML files in a browser for interactive visualization")
    print("  2. Open SVG files in an image viewer")
    print("  3. Use DOT files with GraphViz tools (dot, neato, etc.)")
    print("  4. Parse JSON files for programmatic access")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
