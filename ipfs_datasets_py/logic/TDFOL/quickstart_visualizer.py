#!/usr/bin/env python3
"""
Quick Start Example: Enhanced Countermodel Visualization

This example shows how to use the enhanced countermodel visualizer
in just a few lines of code.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from ipfs_datasets_py.logic.TDFOL import (
    # Visualizer
    create_visualizer,
)
from ipfs_datasets_py.logic.TDFOL.countermodels import KripkeStructure
from ipfs_datasets_py.logic.TDFOL.modal_tableaux import ModalLogicType

# Create a simple Kripke structure
kripke = KripkeStructure(logic_type=ModalLogicType.K)

# Add worlds
kripke.add_world(0)
kripke.add_world(1)
kripke.add_world(2)

# Add accessibility relations
kripke.add_accessibility(0, 1)
kripke.add_accessibility(0, 2)
kripke.add_accessibility(1, 2)

# Set atom valuations
kripke.set_atom_true(0, "P")
kripke.set_atom_true(1, "Q")
kripke.set_atom_true(2, "P")
kripke.set_atom_true(2, "Q")

# Set initial world
kripke.initial_world = 0

# Create visualizer
visualizer = create_visualizer(kripke)

# 1. Enhanced ASCII art
print("=" * 80)
print("ENHANCED ASCII VISUALIZATION")
print("=" * 80)
print(visualizer.render_ascii_enhanced(colors=True, style='expanded'))

print("\n" + "=" * 80)
print("COMPACT ASCII VISUALIZATION")
print("=" * 80)
print(visualizer.render_ascii_enhanced(colors=True, style='compact'))

# 2. Interactive HTML (uncomment to generate)
# visualizer.render_html_interactive("countermodel.html")
# print("\nInteractive HTML saved to: countermodel.html")

# 3. Accessibility graph (uncomment to generate)
# visualizer.render_accessibility_graph("graph.svg", format='svg')
# print("Accessibility graph saved to: graph.svg")

print("\n" + "=" * 80)
print("QUICK START COMPLETE")
print("=" * 80)
print("\nFor more examples, see:")
print("  - countermodel_visualizer_README.md")
print("  - demonstrate_countermodel_visualizer.py")
