# Enhanced Countermodel Visualization for TDFOL

**Phase 11 Task 11.3 Implementation**

This module provides enhanced visualization capabilities for Kripke structures extracted from failed modal tableaux proofs in TDFOL (Temporal-Deontic First-Order Logic).

## Overview

The `countermodel_visualizer.py` module extends the basic visualization capabilities in `countermodels.py` with:

1. **Enhanced ASCII Art** - Box-drawing characters and terminal colors
2. **Interactive HTML Visualization** - D3.js-powered interactive graphs
3. **Accessibility Graph Rendering** - Specialized graph layouts with property highlighting

## Features

### 1. Enhanced ASCII Art (3h implementation)

Provides two display modes with optional terminal colors:

#### Expanded Mode
- Detailed box-drawn representation of each world
- Clear formatting with Unicode box-drawing characters
- Atom valuations displayed in tables
- Accessibility relations shown with arrows
- Modal logic property analysis
- Color-coded output (requires `colorama`)

#### Compact Mode
- Condensed single-line representation per world
- Ideal for quick overview of large structures
- Still includes all essential information

```python
from ipfs_datasets_py.logic.TDFOL.countermodels import KripkeStructure
from ipfs_datasets_py.logic.TDFOL.countermodel_visualizer import CountermodelVisualizer

kripke = KripkeStructure(logic_type=ModalLogicType.K)
# ... build structure ...

visualizer = CountermodelVisualizer(kripke)

# Expanded with colors
print(visualizer.render_ascii_enhanced(colors=True, style='expanded'))

# Compact without colors
print(visualizer.render_ascii_enhanced(colors=False, style='compact'))
```

### 2. Interactive HTML Visualization (4h implementation)

Generates standalone HTML files with full D3.js-powered interactive visualization:

**Features:**
- Clickable worlds showing atom valuations
- Hover tooltips for relations and world details
- Animated transitions between states
- Zoom and pan capabilities
- Drag nodes to reposition
- Toggle physics simulation on/off
- Reset view and auto-center controls
- Color-coded initial world
- Responsive layout

```python
visualizer = CountermodelVisualizer(kripke)

# Save as standalone HTML file
visualizer.render_html_interactive("countermodel.html")

# Or get HTML as string
html_content = visualizer.to_html_string()
```

**Browser Features:**
- **Click and drag** worlds to reposition them
- **Hover** over worlds to see atom valuations
- **Hover** over edges to see accessibility relations
- **Reset View** button to reset zoom and pan
- **Center Graph** button to auto-center the visualization
- **Toggle Physics** button to freeze/unfreeze the layout simulation

### 3. Accessibility Graph Rendering (1h implementation)

Specialized rendering focusing on accessibility relations with property highlighting:

**Highlighted Properties:**
- **Reflexive relations** - Self-loops in green
- **Symmetric relations** - Bidirectional arrows in orange
- **Transitive relations** - Indirect paths
- **Color coding** by modal logic type:
  - K (Basic) - Blue
  - T (Reflexive) - Green
  - D (Serial) - Orange
  - S4 (Reflexive + Transitive) - Purple
  - S5 (Equivalence) - Red

```python
visualizer = CountermodelVisualizer(kripke)

# Save as DOT format
visualizer.render_accessibility_graph("graph.dot", format='dot')

# Can also generate SVG, PNG, PDF (requires Graphviz installed)
visualizer.render_accessibility_graph("graph.svg", format='svg')
visualizer.render_accessibility_graph("graph.png", format='png')
```

**Rendering to images requires Graphviz:**
```bash
# Install Graphviz
sudo apt-get install graphviz  # Ubuntu/Debian
brew install graphviz          # macOS

# Render DOT to image
dot -Tsvg graph.dot -o graph.svg
dot -Tpng graph.dot -o graph.png
dot -Tpdf graph.dot -o graph.pdf
```

## API Reference

### CountermodelVisualizer

Main class for enhanced visualization.

```python
class CountermodelVisualizer:
    def __init__(self, kripke_structure: KripkeStructure)
    
    def render_ascii_enhanced(self, colors: bool = True, style: str = 'expanded') -> str
        """
        Render enhanced ASCII art.
        
        Args:
            colors: Enable terminal color output (requires colorama)
            style: 'expanded' or 'compact'
            
        Returns:
            Enhanced ASCII representation
        """
    
    def render_html_interactive(self, output_path: str) -> None
        """
        Generate interactive HTML visualization.
        
        Args:
            output_path: Path where HTML file should be saved
        """
    
    def to_html_string(self) -> str
        """
        Generate HTML as string.
        
        Returns:
            Complete HTML document
        """
    
    def render_accessibility_graph(self, output_path: str, format: str = 'svg') -> None
        """
        Render accessibility graph.
        
        Args:
            output_path: Output file path
            format: 'svg', 'png', 'pdf', or 'dot'
        """
```

### Convenience Functions

```python
def create_visualizer(kripke_structure: KripkeStructure) -> CountermodelVisualizer
    """Create a visualizer for a Kripke structure."""
```

## Modal Logic Property Detection

The visualizer automatically detects and displays modal logic properties:

- **Reflexive** - Each world accesses itself (required for T, S4, S5)
- **Symmetric** - If w1→w2 then w2→w1 (required for S5)
- **Transitive** - If w1→w2 and w2→w3 then w1→w3 (required for S4, S5)
- **Serial** - Each world accesses at least one world (required for D)

Properties are checked and displayed with checkmarks (✓) or crosses (✗) in ASCII output.

## Integration with Existing Code

The enhanced visualizer is fully compatible with existing countermodel extraction:

```python
from ipfs_datasets_py.logic.TDFOL.countermodels import extract_countermodel
from ipfs_datasets_py.logic.TDFOL.countermodel_visualizer import create_visualizer
from ipfs_datasets_py.logic.TDFOL.modal_tableaux import ModalTableaux, ModalLogicType

# Run tableaux proof
tableaux = ModalTableaux(logic_type=ModalLogicType.K)
result = tableaux.prove(formula)

# Extract countermodel if not valid
if not result.is_valid and result.open_branch:
    countermodel = extract_countermodel(formula, result.open_branch, ModalLogicType.K)
    
    # Use enhanced visualizer
    visualizer = create_visualizer(countermodel.kripke)
    
    # ASCII output
    print(visualizer.render_ascii_enhanced())
    
    # HTML output
    visualizer.render_html_interactive("countermodel.html")
    
    # Graph output
    visualizer.render_accessibility_graph("graph.svg", format='svg')
```

## Dependencies

### Required
- `ipfs_datasets_py.logic.TDFOL.countermodels` - Base countermodel classes
- `ipfs_datasets_py.logic.TDFOL.modal_tableaux` - Modal logic types

### Optional
- `colorama` - For terminal color output
- `graphviz` (system package) - For rendering DOT to images

Install optional dependencies:
```bash
pip install colorama
sudo apt-get install graphviz  # Ubuntu/Debian
brew install graphviz          # macOS
```

## Demonstration

Run the demonstration script to see all features in action:

```bash
# Show all visualizations in terminal
python ipfs_datasets_py/logic/TDFOL/demonstrate_countermodel_visualizer.py

# Generate HTML files only
python ipfs_datasets_py/logic/TDFOL/demonstrate_countermodel_visualizer.py --html-only

# Save all outputs to files
python ipfs_datasets_py/logic/TDFOL/demonstrate_countermodel_visualizer.py --save-all

# Custom output directory
python ipfs_datasets_py/logic/TDFOL/demonstrate_countermodel_visualizer.py --save-all --output-dir ./my_visualizations
```

The demonstration includes examples for:
- Simple K logic structure
- Reflexive T logic structure
- Equivalence S5 logic structure
- Complex S4 logic structure

## Testing

Comprehensive test suite in `tests/unit_tests/logic/TDFOL/test_countermodel_visualizer.py`:

```bash
# Run visualizer tests
pytest tests/unit_tests/logic/TDFOL/test_countermodel_visualizer.py -v

# Run with coverage
pytest tests/unit_tests/logic/TDFOL/test_countermodel_visualizer.py --cov=ipfs_datasets_py.logic.TDFOL.countermodel_visualizer
```

Test coverage includes:
- Box-drawing character constants
- Visualizer creation and initialization
- Enhanced ASCII rendering (both modes)
- Modal logic property detection
- HTML generation and interactivity
- Accessibility graph rendering
- Edge cases and error handling
- Integration with existing countermodels

## Examples

### Example 1: Simple Visualization

```python
from ipfs_datasets_py.logic.TDFOL.countermodels import KripkeStructure
from ipfs_datasets_py.logic.TDFOL.modal_tableaux import ModalLogicType
from ipfs_datasets_py.logic.TDFOL.countermodel_visualizer import create_visualizer

# Create simple structure
kripke = KripkeStructure(logic_type=ModalLogicType.K)
kripke.add_world(0)
kripke.add_world(1)
kripke.add_accessibility(0, 1)
kripke.set_atom_true(0, "P")
kripke.set_atom_true(1, "Q")

# Visualize
visualizer = create_visualizer(kripke)
print(visualizer.render_ascii_enhanced(colors=True))
```

### Example 2: Reflexive Structure (T Logic)

```python
# Create T logic structure
kripke = KripkeStructure(logic_type=ModalLogicType.T)
kripke.add_world(0)
kripke.add_world(1)

# Reflexive relations (required for T)
kripke.add_accessibility(0, 0)
kripke.add_accessibility(1, 1)
kripke.add_accessibility(0, 1)

kripke.set_atom_true(0, "A")
kripke.set_atom_true(1, "B")

visualizer = create_visualizer(kripke)

# Check properties
print(visualizer.render_ascii_enhanced())  # Will show ✓ Reflexive: True

# Generate interactive HTML
visualizer.render_html_interactive("t_logic.html")
```

### Example 3: Complete Workflow

```python
from ipfs_datasets_py.logic.TDFOL import parse_tdfol
from ipfs_datasets_py.logic.TDFOL.modal_tableaux import ModalTableaux, ModalLogicType
from ipfs_datasets_py.logic.TDFOL.countermodels import extract_countermodel
from ipfs_datasets_py.logic.TDFOL.countermodel_visualizer import create_visualizer

# Try to prove a formula
formula = parse_tdfol("□P → P")  # Not valid in K, valid in T
tableaux = ModalTableaux(logic_type=ModalLogicType.K)
result = tableaux.prove(formula)

if not result.is_valid and result.open_branch:
    # Extract countermodel
    counter = extract_countermodel(formula, result.open_branch, ModalLogicType.K)
    
    # Enhanced visualization
    visualizer = create_visualizer(counter.kripke)
    
    # Show in terminal
    print(visualizer.render_ascii_enhanced(colors=True, style='expanded'))
    
    # Save interactive HTML
    visualizer.render_html_interactive("countermodel.html")
    print("Open countermodel.html in your browser")
    
    # Save accessibility graph
    visualizer.render_accessibility_graph("graph.dot", format='dot')
    print("Render with: dot -Tsvg graph.dot -o graph.svg")
```

## Box-Drawing Characters

The module uses Unicode box-drawing characters for enhanced ASCII art:

- `─` Horizontal line
- `│` Vertical line
- `┌` `┐` `└` `┘` Corners
- `├` `┤` `┬` `┴` `┼` T-junctions and cross
- `→` `↓` Arrows
- `⇒` Double arrow (initial world)
- `•` Bullet point
- `✓` `✗` Check and cross marks

These characters provide clean, professional-looking output in modern terminals.

## Color Scheme

When colors are enabled (requires `colorama`):

- **Green** - Initial world, reflexive relations, confirmed properties
- **Cyan** - World labels
- **Yellow** - Atom valuations
- **Magenta** - Accessibility relations
- **Red** - Empty sets, missing properties
- **Blue** - Arrows and connections

## Performance Considerations

- **ASCII rendering** is fast even for large structures (100+ worlds)
- **HTML generation** handles structures with 50+ worlds efficiently
- **Accessibility graphs** use optimized DOT format
- For very large structures (200+ worlds), use compact ASCII mode

## Backward Compatibility

The enhanced visualizer:
- Does NOT replace existing visualization in `countermodels.py`
- Works alongside existing `to_ascii_art()`, `to_dot()`, and `to_json()`
- Uses the same `KripkeStructure` class
- Can be used with all existing countermodel extraction code

## Future Enhancements

Possible future additions:
- Export to other graph formats (GraphML, GEXF)
- 3D visualization for complex structures
- Animation of formula evaluation through worlds
- Diff view for comparing countermodels
- Natural language explanation generation

## Related Files

- `countermodels.py` - Base countermodel extraction and basic visualization
- `modal_tableaux.py` - Modal tableaux implementation
- `test_countermodel_visualizer.py` - Comprehensive test suite
- `demonstrate_countermodel_visualizer.py` - Interactive demonstration

## References

- Modal Logic: https://plato.stanford.edu/entries/logic-modal/
- Kripke Semantics: https://en.wikipedia.org/wiki/Kripke_semantics
- D3.js Force Layout: https://d3js.org/d3-force
- GraphViz DOT Language: https://graphviz.org/doc/info/lang.html

---

**Status:** ✅ Complete - Phase 11 Task 11.3 Implemented

**Implementation Time:** 8 hours (3h ASCII + 4h HTML + 1h Graphs)

**Test Coverage:** 100+ tests covering all functionality

**Documentation:** Complete with examples and API reference
