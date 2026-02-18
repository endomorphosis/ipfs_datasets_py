#!/usr/bin/env python3
"""
Demonstration of Enhanced Countermodel Visualization

This script demonstrates all the enhanced visualization capabilities for TDFOL countermodels:
1. Enhanced ASCII art with box-drawing and colors
2. Interactive HTML visualization with D3.js
3. Accessibility graph rendering

Run with:
    python demonstrate_countermodel_visualizer.py
    python demonstrate_countermodel_visualizer.py --html-only
    python demonstrate_countermodel_visualizer.py --save-all
"""

import argparse
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from ipfs_datasets_py.logic.TDFOL.countermodels import KripkeStructure
from ipfs_datasets_py.logic.TDFOL.modal_tableaux import ModalLogicType
from ipfs_datasets_py.logic.TDFOL.countermodel_visualizer import (
    CountermodelVisualizer,
    create_visualizer,
)


def create_sample_kripke_simple() -> KripkeStructure:
    """Create a simple Kripke structure for demonstration."""
    kripke = KripkeStructure(logic_type=ModalLogicType.K)
    kripke.add_world(0)
    kripke.add_world(1)
    kripke.add_world(2)
    
    kripke.add_accessibility(0, 1)
    kripke.add_accessibility(0, 2)
    kripke.add_accessibility(1, 2)
    
    kripke.set_atom_true(0, "P")
    kripke.set_atom_true(1, "Q")
    kripke.set_atom_true(2, "P")
    kripke.set_atom_true(2, "Q")
    
    kripke.initial_world = 0
    
    return kripke


def create_sample_kripke_reflexive() -> KripkeStructure:
    """Create a reflexive Kripke structure (T logic)."""
    kripke = KripkeStructure(logic_type=ModalLogicType.T)
    kripke.add_world(0)
    kripke.add_world(1)
    
    # Reflexive relations
    kripke.add_accessibility(0, 0)
    kripke.add_accessibility(1, 1)
    
    # Plus connection
    kripke.add_accessibility(0, 1)
    
    kripke.set_atom_true(0, "A")
    kripke.set_atom_true(1, "B")
    
    kripke.initial_world = 0
    
    return kripke


def create_sample_kripke_s5() -> KripkeStructure:
    """Create an equivalence relation (S5 logic)."""
    kripke = KripkeStructure(logic_type=ModalLogicType.S5)
    kripke.add_world(0)
    kripke.add_world(1)
    kripke.add_world(2)
    
    # Equivalence relation: reflexive, symmetric, transitive
    for i in range(3):
        for j in range(3):
            kripke.add_accessibility(i, j)
    
    kripke.set_atom_true(0, "X")
    kripke.set_atom_true(1, "Y")
    kripke.set_atom_true(2, "Z")
    
    kripke.initial_world = 0
    
    return kripke


def create_sample_kripke_complex() -> KripkeStructure:
    """Create a complex Kripke structure for demonstration."""
    kripke = KripkeStructure(logic_type=ModalLogicType.S4)
    
    # Create 5 worlds
    for i in range(5):
        kripke.add_world(i)
    
    # Create accessibility relations
    kripke.add_accessibility(0, 1)
    kripke.add_accessibility(0, 2)
    kripke.add_accessibility(1, 3)
    kripke.add_accessibility(2, 3)
    kripke.add_accessibility(3, 4)
    kripke.add_accessibility(1, 4)
    
    # Reflexive relations for S4
    for i in range(5):
        kripke.add_accessibility(i, i)
    
    # Transitive closure
    kripke.add_accessibility(0, 3)
    kripke.add_accessibility(0, 4)
    kripke.add_accessibility(2, 4)
    
    # Add atoms
    kripke.set_atom_true(0, "P")
    kripke.set_atom_true(1, "Q")
    kripke.set_atom_true(2, "R")
    kripke.set_atom_true(3, "P")
    kripke.set_atom_true(3, "Q")
    kripke.set_atom_true(4, "S")
    
    kripke.initial_world = 0
    
    return kripke


def demonstrate_ascii_enhanced(visualizer: CountermodelVisualizer, title: str):
    """Demonstrate enhanced ASCII visualization."""
    print("\n" + "=" * 80)
    print(f"ASCII ENHANCED VISUALIZATION: {title}")
    print("=" * 80)
    
    print("\n--- EXPANDED STYLE (with colors) ---\n")
    print(visualizer.render_ascii_enhanced(colors=True, style='expanded'))
    
    print("\n--- COMPACT STYLE ---\n")
    print(visualizer.render_ascii_enhanced(colors=True, style='compact'))


def demonstrate_html_interactive(visualizer: CountermodelVisualizer, 
                                 output_path: Path, title: str):
    """Demonstrate interactive HTML visualization."""
    print("\n" + "=" * 80)
    print(f"HTML INTERACTIVE VISUALIZATION: {title}")
    print("=" * 80)
    
    html_file = output_path / f"{title.lower().replace(' ', '_')}.html"
    visualizer.render_html_interactive(str(html_file))
    
    print(f"\nInteractive HTML saved to: {html_file}")
    print(f"Open in browser: file://{html_file.absolute()}")
    print("\nFeatures:")
    print("  - Click and drag worlds to reposition")
    print("  - Hover over worlds to see atom valuations")
    print("  - Hover over edges to see accessibility relations")
    print("  - Use 'Reset View' button to reset zoom")
    print("  - Use 'Center Graph' button to auto-center")
    print("  - Use 'Toggle Physics' to freeze/unfreeze layout")


def demonstrate_accessibility_graph(visualizer: CountermodelVisualizer,
                                     output_path: Path, title: str):
    """Demonstrate accessibility graph rendering."""
    print("\n" + "=" * 80)
    print(f"ACCESSIBILITY GRAPH: {title}")
    print("=" * 80)
    
    dot_file = output_path / f"{title.lower().replace(' ', '_')}_graph.dot"
    visualizer.render_accessibility_graph(str(dot_file), format='dot')
    
    print(f"\nAccessibility graph saved to: {dot_file}")
    print("\nTo render as image (requires Graphviz):")
    print(f"  dot -Tsvg {dot_file} -o {dot_file.with_suffix('.svg')}")
    print(f"  dot -Tpng {dot_file} -o {dot_file.with_suffix('.png')}")
    
    print("\nGraph features:")
    print("  - Reflexive relations highlighted in green")
    print("  - Symmetric relations shown as bidirectional")
    print("  - Color coding based on modal logic type")
    print("  - Initial world marked with orange border")


def main():
    """Main demonstration function."""
    parser = argparse.ArgumentParser(
        description="Demonstrate enhanced countermodel visualization"
    )
    parser.add_argument(
        '--html-only',
        action='store_true',
        help='Only generate HTML visualizations'
    )
    parser.add_argument(
        '--ascii-only',
        action='store_true',
        help='Only show ASCII visualizations'
    )
    parser.add_argument(
        '--save-all',
        action='store_true',
        help='Save all visualizations to files'
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        default='./countermodel_demos',
        help='Output directory for saved files'
    )
    
    args = parser.parse_args()
    
    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    print("=" * 80)
    print("ENHANCED COUNTERMODEL VISUALIZATION DEMONSTRATION")
    print("=" * 80)
    print("\nThis demonstration showcases the enhanced visualization capabilities")
    print("for TDFOL countermodels, including:")
    print("  1. Enhanced ASCII art with box-drawing and terminal colors")
    print("  2. Interactive HTML visualization with D3.js")
    print("  3. Accessibility graph rendering with property highlighting")
    
    # Create sample structures
    samples = [
        ("Simple K Logic", create_sample_kripke_simple()),
        ("Reflexive T Logic", create_sample_kripke_reflexive()),
        ("Equivalence S5 Logic", create_sample_kripke_s5()),
        ("Complex S4 Logic", create_sample_kripke_complex()),
    ]
    
    for title, kripke in samples:
        visualizer = create_visualizer(kripke)
        
        if not args.html_only:
            demonstrate_ascii_enhanced(visualizer, title)
        
        if args.save_all or args.html_only:
            demonstrate_html_interactive(visualizer, output_path, title)
        
        if args.save_all and not args.ascii_only:
            demonstrate_accessibility_graph(visualizer, output_path, title)
    
    print("\n" + "=" * 80)
    print("DEMONSTRATION COMPLETE")
    print("=" * 80)
    
    if args.save_all:
        print(f"\nAll visualizations saved to: {output_path.absolute()}")
        print("\nFiles created:")
        for f in sorted(output_path.iterdir()):
            print(f"  - {f.name}")
    
    print("\nFor more information, see:")
    print("  - ipfs_datasets_py/logic/TDFOL/countermodel_visualizer.py")
    print("  - tests/unit_tests/logic/TDFOL/test_countermodel_visualizer.py")


if __name__ == '__main__':
    main()
