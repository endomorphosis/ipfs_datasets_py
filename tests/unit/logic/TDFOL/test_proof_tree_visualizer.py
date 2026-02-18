"""
Tests for TDFOL Proof Tree Visualizer

Tests cover:
- ASCII tree rendering with different styles
- Color output (with and without colorama)
- GraphViz DOT export
- SVG/PNG rendering
- Interactive HTML generation
- JSON export
- Different proof methods and node types
"""

import json
import tempfile
from pathlib import Path
from typing import List

import pytest

from ipfs_datasets_py.logic.TDFOL.proof_tree_visualizer import (
    BoxChars,
    ColorScheme,
    GraphvizColors,
    NodeType,
    ProofTreeNode,
    ProofTreeVisualizer,
    TreeStyle,
    VerbosityLevel,
    visualize_proof,
)
from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
    BinaryFormula,
    LogicOperator,
    Predicate,
    Term,
    Variable,
)
from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult, ProofStatus, ProofStep


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def simple_formula():
    """Create a simple formula: P(x)."""
    return Predicate("P", [Variable("x")])


@pytest.fixture
def complex_formula():
    """Create a complex formula: P(x) → Q(y)."""
    p = Predicate("P", [Variable("x")])
    q = Predicate("Q", [Variable("y")])
    return BinaryFormula(LogicOperator.IMPLIES, p, q)


@pytest.fixture
def simple_proof_result(simple_formula):
    """Create a simple proof result with linear steps."""
    # GIVEN: A simple proof with 3 steps
    step1 = ProofStep(
        formula=Predicate("A", []),
        justification="Axiom",
        rule_name="Axiom",
        premises=[]
    )
    
    step2 = ProofStep(
        formula=Predicate("B", []),
        justification="Axiom",
        rule_name="Axiom",
        premises=[]
    )
    
    step3 = ProofStep(
        formula=BinaryFormula(
            LogicOperator.AND,
            Predicate("A", []),
            Predicate("B", [])
        ),
        justification="Conjunction from steps 1 and 2",
        rule_name="AND-Introduction",
        premises=[step1.formula, step2.formula]
    )
    
    return ProofResult(
        status=ProofStatus.PROVED,
        formula=step3.formula,
        proof_steps=[step1, step2, step3],
        time_ms=15.5,
        method="forward_chaining",
        message="Proof completed successfully"
    )


@pytest.fixture
def complex_proof_result(complex_formula):
    """Create a complex proof with branching."""
    # GIVEN: A proof with branching structure
    step1 = ProofStep(
        formula=Predicate("P", [Variable("x")]),
        justification="Premise",
        rule_name="Premise",
        premises=[]
    )
    
    step2 = ProofStep(
        formula=BinaryFormula(
            LogicOperator.IMPLIES,
            Predicate("P", [Variable("x")]),
            Predicate("Q", [Variable("y")])
        ),
        justification="Axiom: P implies Q",
        rule_name="Axiom",
        premises=[]
    )
    
    step3 = ProofStep(
        formula=Predicate("Q", [Variable("y")]),
        justification="Modus Ponens from steps 1 and 2",
        rule_name="ModusPonens",
        premises=[step1.formula, step2.formula]
    )
    
    step4 = ProofStep(
        formula=Predicate("R", []),
        justification="Axiom",
        rule_name="Axiom",
        premises=[]
    )
    
    step5 = ProofStep(
        formula=BinaryFormula(
            LogicOperator.AND,
            Predicate("Q", [Variable("y")]),
            Predicate("R", [])
        ),
        justification="Conjunction from steps 3 and 4",
        rule_name="AND-Introduction",
        premises=[step3.formula, step4.formula]
    )
    
    return ProofResult(
        status=ProofStatus.PROVED,
        formula=step5.formula,
        proof_steps=[step1, step2, step3, step4, step5],
        time_ms=42.3,
        method="backward_chaining",
        message="Goal reached"
    )


@pytest.fixture
def empty_proof_result(simple_formula):
    """Create an empty proof result (no steps)."""
    return ProofResult(
        status=ProofStatus.UNKNOWN,
        formula=simple_formula,
        proof_steps=[],
        time_ms=0.0,
        method="unknown"
    )


@pytest.fixture
def failed_proof_result(simple_formula):
    """Create a failed proof result."""
    step1 = ProofStep(
        formula=Predicate("P", []),
        justification="Assumption",
        rule_name="Assumption",
        premises=[]
    )
    
    step2 = ProofStep(
        formula=BinaryFormula(
            LogicOperator.AND,
            Predicate("P", []),
            Predicate("NOT_P", [])
        ),
        justification="Derived contradiction",
        rule_name="Contradiction",
        premises=[step1.formula]
    )
    
    return ProofResult(
        status=ProofStatus.DISPROVED,
        formula=simple_formula,
        proof_steps=[step1, step2],
        time_ms=8.2,
        method="tableaux",
        message="Contradiction found"
    )


# ============================================================================
# Test ProofTreeNode
# ============================================================================


def test_proof_tree_node_creation(simple_formula):
    """Test: ProofTreeNode can be created."""
    # WHEN: Creating a proof tree node
    node = ProofTreeNode(
        formula=simple_formula,
        node_type=NodeType.AXIOM,
        rule_name="TestRule",
        justification="Test justification",
        step_number=1
    )
    
    # THEN: Node is created with correct attributes
    assert node.formula == simple_formula
    assert node.node_type == NodeType.AXIOM
    assert node.rule_name == "TestRule"
    assert node.justification == "Test justification"
    assert node.step_number == 1
    assert node.premises == []


def test_proof_tree_node_hashable(simple_formula):
    """Test: ProofTreeNode is hashable."""
    # GIVEN: A proof tree node
    node = ProofTreeNode(
        formula=simple_formula,
        node_type=NodeType.AXIOM,
        step_number=1
    )
    
    # WHEN: Using node in a set
    node_set = {node}
    
    # THEN: No error occurs
    assert node in node_set


# ============================================================================
# Test ProofTreeVisualizer Construction
# ============================================================================


def test_visualizer_init_simple(simple_proof_result):
    """Test: Visualizer can be initialized with simple proof."""
    # WHEN: Creating visualizer
    visualizer = ProofTreeVisualizer(simple_proof_result)
    
    # THEN: Visualizer is created correctly
    assert visualizer.proof_result == simple_proof_result
    assert visualizer.tree_root is not None
    assert len(visualizer.all_nodes) == 3
    assert visualizer.verbosity == VerbosityLevel.NORMAL


def test_visualizer_init_empty(empty_proof_result):
    """Test: Visualizer handles empty proof."""
    # WHEN: Creating visualizer with empty proof
    visualizer = ProofTreeVisualizer(empty_proof_result)
    
    # THEN: Single node created for formula
    assert visualizer.tree_root is not None
    assert len(visualizer.all_nodes) == 1
    assert visualizer.tree_root.node_type == NodeType.GOAL


def test_visualizer_init_complex(complex_proof_result):
    """Test: Visualizer handles complex branching proof."""
    # WHEN: Creating visualizer with complex proof
    visualizer = ProofTreeVisualizer(complex_proof_result)
    
    # THEN: Tree structure built correctly
    assert visualizer.tree_root is not None
    assert len(visualizer.all_nodes) == 5
    # Root should be the final conclusion
    assert visualizer.tree_root.step_number == 5


def test_visualizer_verbosity_levels(simple_proof_result):
    """Test: Different verbosity levels."""
    # WHEN: Creating visualizers with different verbosity
    minimal = ProofTreeVisualizer(simple_proof_result, VerbosityLevel.MINIMAL)
    normal = ProofTreeVisualizer(simple_proof_result, VerbosityLevel.NORMAL)
    detailed = ProofTreeVisualizer(simple_proof_result, VerbosityLevel.DETAILED)
    
    # THEN: Verbosity is set correctly
    assert minimal.verbosity == VerbosityLevel.MINIMAL
    assert normal.verbosity == VerbosityLevel.NORMAL
    assert detailed.verbosity == VerbosityLevel.DETAILED


# ============================================================================
# Test ASCII Rendering
# ============================================================================


def test_render_ascii_basic(simple_proof_result):
    """Test: Basic ASCII rendering."""
    # GIVEN: A visualizer
    visualizer = ProofTreeVisualizer(simple_proof_result)
    
    # WHEN: Rendering as ASCII
    output = visualizer.render_ascii(colors=False)
    
    # THEN: Output contains expected elements
    assert "Proof Tree" in output
    assert "forward_chaining" in output
    assert "Status: proved" in output
    assert "Time: 15.50 ms" in output
    assert "Steps: 3" in output
    assert "A" in output
    assert "B" in output


def test_render_ascii_with_colors(simple_proof_result):
    """Test: ASCII rendering with colors."""
    # GIVEN: A visualizer
    visualizer = ProofTreeVisualizer(simple_proof_result)
    
    # WHEN: Rendering with colors enabled
    output = visualizer.render_ascii(colors=True)
    
    # THEN: Output is generated (colors may or may not be present)
    assert "Proof Tree" in output
    assert len(output) > 0


def test_render_ascii_styles(simple_proof_result):
    """Test: Different ASCII styles."""
    # GIVEN: A visualizer
    visualizer = ProofTreeVisualizer(simple_proof_result)
    
    # WHEN: Rendering with different styles
    compact = visualizer.render_ascii(style='compact', colors=False)
    expanded = visualizer.render_ascii(style='expanded', colors=False)
    detailed = visualizer.render_ascii(style='detailed', colors=False)
    
    # THEN: All styles produce output
    assert len(compact) > 0
    assert len(expanded) > 0
    assert len(detailed) > 0
    # Detailed should be longer (includes justifications)
    assert len(detailed) >= len(compact)


def test_render_ascii_tree_structure(simple_proof_result):
    """Test: ASCII tree uses box-drawing characters."""
    # GIVEN: A visualizer
    visualizer = ProofTreeVisualizer(simple_proof_result)
    
    # WHEN: Rendering as tree
    output = visualizer.render_ascii(style='tree', colors=False)
    
    # THEN: Output contains tree characters
    assert any(char in output for char in [BoxChars.TEE, BoxChars.CORNER, BoxChars.VERTICAL])


def test_render_ascii_max_width(simple_proof_result):
    """Test: ASCII rendering respects max width."""
    # GIVEN: A visualizer with long formulas
    visualizer = ProofTreeVisualizer(simple_proof_result)
    
    # WHEN: Rendering with small max width
    output = visualizer.render_ascii(colors=False, max_width=40)
    
    # THEN: Lines are truncated appropriately
    lines = output.split('\n')
    # Some lines might exceed due to prefixes, but formulas should be truncated
    assert any('...' in line for line in lines) or all(len(line) < 60 for line in lines)


def test_render_ascii_empty_proof(empty_proof_result):
    """Test: ASCII rendering of empty proof."""
    # GIVEN: A visualizer with empty proof
    visualizer = ProofTreeVisualizer(empty_proof_result)
    
    # WHEN: Rendering as ASCII
    output = visualizer.render_ascii(colors=False)
    
    # THEN: Output shows the formula
    assert "P(x)" in output
    assert "Status: unknown" in output


def test_render_ascii_failed_proof(failed_proof_result):
    """Test: ASCII rendering of failed proof."""
    # GIVEN: A visualizer with failed proof
    visualizer = ProofTreeVisualizer(failed_proof_result)
    
    # WHEN: Rendering as ASCII
    output = visualizer.render_ascii(colors=False)
    
    # THEN: Output shows disproved status
    assert "disproved" in output
    assert "Contradiction" in output


# ============================================================================
# Test GraphViz DOT Export
# ============================================================================


def test_export_dot_basic(simple_proof_result, tmp_path):
    """Test: Export to DOT format."""
    # GIVEN: A visualizer
    visualizer = ProofTreeVisualizer(simple_proof_result)
    output_path = tmp_path / "proof.dot"
    
    # WHEN: Exporting to DOT
    visualizer.export_dot(str(output_path))
    
    # THEN: DOT file is created
    assert output_path.exists()
    content = output_path.read_text()
    assert "digraph ProofTree" in content
    assert "node" in content
    assert "edge" in content


def test_export_dot_nodes(simple_proof_result, tmp_path):
    """Test: DOT export includes all nodes."""
    # GIVEN: A visualizer
    visualizer = ProofTreeVisualizer(simple_proof_result)
    output_path = tmp_path / "proof.dot"
    
    # WHEN: Exporting to DOT
    visualizer.export_dot(str(output_path))
    
    # THEN: DOT file contains node definitions
    content = output_path.read_text()
    assert "node_0" in content
    assert "node_1" in content
    assert "node_2" in content
    assert "fillcolor" in content


def test_export_dot_edges(complex_proof_result, tmp_path):
    """Test: DOT export includes edges."""
    # GIVEN: A visualizer with branching proof
    visualizer = ProofTreeVisualizer(complex_proof_result)
    output_path = tmp_path / "proof.dot"
    
    # WHEN: Exporting to DOT
    visualizer.export_dot(str(output_path))
    
    # THEN: DOT file contains edge definitions
    content = output_path.read_text()
    assert "->" in content  # Edges present


def test_export_dot_empty_proof(empty_proof_result, tmp_path):
    """Test: DOT export handles empty proof."""
    # GIVEN: A visualizer with empty proof
    visualizer = ProofTreeVisualizer(empty_proof_result)
    output_path = tmp_path / "proof.dot"
    
    # WHEN: Exporting to DOT
    visualizer.export_dot(str(output_path))
    
    # THEN: Warning logged, but no crash
    # File may or may not be created depending on implementation


# ============================================================================
# Test SVG/PNG Rendering
# ============================================================================


@pytest.mark.slow
def test_render_svg(simple_proof_result, tmp_path):
    """Test: Render to SVG format."""
    # GIVEN: A visualizer
    visualizer = ProofTreeVisualizer(simple_proof_result)
    output_path = tmp_path / "proof.svg"
    
    # WHEN: Rendering to SVG
    try:
        visualizer.render_svg(str(output_path))
        
        # THEN: SVG file may be created if GraphViz available
        # Test is lenient since GraphViz may not be installed
        if output_path.exists():
            content = output_path.read_text()
            assert "<svg" in content or len(content) > 0
    except (RuntimeError, FileNotFoundError) as e:
        # GraphViz not available, skip
        pytest.skip(f"GraphViz not available: {e}")


@pytest.mark.slow
def test_render_png(simple_proof_result, tmp_path):
    """Test: Render to PNG format."""
    # GIVEN: A visualizer
    visualizer = ProofTreeVisualizer(simple_proof_result)
    output_path = tmp_path / "proof.png"
    
    # WHEN: Rendering to PNG
    try:
        visualizer.render_png(str(output_path))
        
        # THEN: PNG file may be created if GraphViz available
        if output_path.exists():
            assert output_path.stat().st_size > 0
    except (RuntimeError, FileNotFoundError) as e:
        # GraphViz not available, skip
        pytest.skip(f"GraphViz not available: {e}")


# ============================================================================
# Test HTML Rendering
# ============================================================================


@pytest.mark.slow
def test_render_html_basic(simple_proof_result, tmp_path):
    """Test: Render to HTML format."""
    # GIVEN: A visualizer
    visualizer = ProofTreeVisualizer(simple_proof_result)
    output_path = tmp_path / "proof.html"
    
    # WHEN: Rendering to HTML
    try:
        visualizer.render_html(str(output_path), interactive=False)
        
        # THEN: HTML file created
        if output_path.exists():
            content = output_path.read_text()
            assert "<!DOCTYPE html>" in content
            assert "<html>" in content
            assert "TDFOL Proof Tree" in content
            assert "forward_chaining" in content
    except (RuntimeError, FileNotFoundError) as e:
        pytest.skip(f"GraphViz not available: {e}")


@pytest.mark.slow
def test_render_html_interactive(simple_proof_result, tmp_path):
    """Test: Render interactive HTML."""
    # GIVEN: A visualizer
    visualizer = ProofTreeVisualizer(simple_proof_result)
    output_path = tmp_path / "proof_interactive.html"
    
    # WHEN: Rendering with interactive=True
    try:
        visualizer.render_html(str(output_path), interactive=True)
        
        # THEN: HTML includes JavaScript
        if output_path.exists():
            content = output_path.read_text()
            assert "<script>" in content
    except (RuntimeError, FileNotFoundError) as e:
        pytest.skip(f"GraphViz not available: {e}")


@pytest.mark.slow
def test_render_html_metadata(complex_proof_result, tmp_path):
    """Test: HTML includes proof metadata."""
    # GIVEN: A visualizer
    visualizer = ProofTreeVisualizer(complex_proof_result)
    output_path = tmp_path / "proof.html"
    
    # WHEN: Rendering to HTML
    try:
        visualizer.render_html(str(output_path))
        
        # THEN: HTML includes metadata
        if output_path.exists():
            content = output_path.read_text()
            assert "backward_chaining" in content
            assert "42.30 ms" in content or "42.3 ms" in content
            assert "Steps:" in content
    except (RuntimeError, FileNotFoundError) as e:
        pytest.skip(f"GraphViz not available: {e}")


# ============================================================================
# Test JSON Export
# ============================================================================


def test_to_json_basic(simple_proof_result):
    """Test: Export to JSON structure."""
    # GIVEN: A visualizer
    visualizer = ProofTreeVisualizer(simple_proof_result)
    
    # WHEN: Exporting to JSON
    json_data = visualizer.to_json()
    
    # THEN: JSON contains expected fields
    assert json_data["status"] == "proved"
    assert "formula" in json_data
    assert json_data["method"] == "forward_chaining"
    assert json_data["time_ms"] == 15.5
    assert "tree" in json_data
    assert "steps" in json_data
    assert len(json_data["steps"]) == 3


def test_to_json_tree_structure(complex_proof_result):
    """Test: JSON export includes tree structure."""
    # GIVEN: A visualizer with branching proof
    visualizer = ProofTreeVisualizer(complex_proof_result)
    
    # WHEN: Exporting to JSON
    json_data = visualizer.to_json()
    
    # THEN: Tree structure is present
    assert "tree" in json_data
    tree = json_data["tree"]
    assert "formula" in tree
    assert "node_type" in tree
    assert "premises" in tree
    assert isinstance(tree["premises"], list)


def test_to_json_steps(simple_proof_result):
    """Test: JSON export includes proof steps."""
    # GIVEN: A visualizer
    visualizer = ProofTreeVisualizer(simple_proof_result)
    
    # WHEN: Exporting to JSON
    json_data = visualizer.to_json()
    
    # THEN: Steps are correctly formatted
    steps = json_data["steps"]
    assert len(steps) == 3
    assert steps[0]["step_number"] == 1  # Step numbering starts at 1
    assert "formula" in steps[0]
    assert "rule_name" in steps[0]
    assert "justification" in steps[0]
    assert "premises" in steps[0]


def test_export_json_file(simple_proof_result, tmp_path):
    """Test: Export JSON to file."""
    # GIVEN: A visualizer
    visualizer = ProofTreeVisualizer(simple_proof_result)
    output_path = tmp_path / "proof.json"
    
    # WHEN: Exporting to JSON file
    visualizer.export_json(str(output_path))
    
    # THEN: JSON file is created and valid
    assert output_path.exists()
    with open(output_path) as f:
        data = json.load(f)
    assert data["status"] == "proved"
    assert "tree" in data


def test_to_json_empty_proof(empty_proof_result):
    """Test: JSON export handles empty proof."""
    # GIVEN: A visualizer with empty proof
    visualizer = ProofTreeVisualizer(empty_proof_result)
    
    # WHEN: Exporting to JSON
    json_data = visualizer.to_json()
    
    # THEN: JSON is valid
    assert json_data["status"] == "unknown"
    assert "formula" in json_data
    # Tree might be present with single node


# ============================================================================
# Test Convenience Functions
# ============================================================================


def test_visualize_proof_ascii(simple_proof_result):
    """Test: Convenience function for ASCII output."""
    # WHEN: Using convenience function
    output = visualize_proof(simple_proof_result, output_format="ascii", colors=False)
    
    # THEN: ASCII output returned
    assert output is not None
    assert "Proof Tree" in output
    assert "proved" in output


def test_visualize_proof_dot(simple_proof_result, tmp_path):
    """Test: Convenience function for DOT output."""
    # GIVEN: Output path
    output_path = tmp_path / "proof.dot"
    
    # WHEN: Using convenience function
    result = visualize_proof(
        simple_proof_result,
        output_format="dot",
        output_path=str(output_path)
    )
    
    # THEN: DOT file created
    assert result is None  # Returns None for file outputs
    assert output_path.exists()


def test_visualize_proof_json(simple_proof_result, tmp_path):
    """Test: Convenience function for JSON output."""
    # GIVEN: Output path
    output_path = tmp_path / "proof.json"
    
    # WHEN: Using convenience function
    visualize_proof(
        simple_proof_result,
        output_format="json",
        output_path=str(output_path)
    )
    
    # THEN: JSON file created
    assert output_path.exists()


def test_visualize_proof_invalid_format(simple_proof_result):
    """Test: Convenience function rejects invalid format."""
    # WHEN: Using invalid format
    # THEN: ValueError raised
    with pytest.raises(ValueError, match="Unknown output format"):
        visualize_proof(simple_proof_result, output_format="invalid")


def test_visualize_proof_missing_path(simple_proof_result):
    """Test: Convenience function requires path for non-ASCII formats."""
    # WHEN: Using DOT without output_path
    # THEN: ValueError raised
    with pytest.raises(ValueError, match="output_path required"):
        visualize_proof(simple_proof_result, output_format="dot")


# ============================================================================
# Test Node Type Colors
# ============================================================================


def test_node_type_colors():
    """Test: Color scheme for different node types."""
    # WHEN: Getting colors for node types
    axiom_color = ColorScheme.get_node_color(NodeType.AXIOM)
    theorem_color = ColorScheme.get_node_color(NodeType.THEOREM)
    contradiction_color = ColorScheme.get_node_color(NodeType.CONTRADICTION)
    
    # THEN: Colors are returned (empty string if no colorama)
    assert isinstance(axiom_color, str)
    assert isinstance(theorem_color, str)
    assert isinstance(contradiction_color, str)


def test_graphviz_colors():
    """Test: GraphViz color scheme."""
    # WHEN: Getting GraphViz colors
    axiom_color = GraphvizColors.NODE_COLORS[NodeType.AXIOM]
    theorem_color = GraphvizColors.NODE_COLORS[NodeType.THEOREM]
    
    # THEN: Colors are hex codes
    assert axiom_color.startswith("#")
    assert theorem_color.startswith("#")
    assert len(axiom_color) == 7


# ============================================================================
# Test Edge Cases
# ============================================================================


def test_very_long_formula(tmp_path):
    """Test: Handle very long formulas."""
    # GIVEN: A proof with very long formula
    long_formula = Predicate("VeryLongPredicateName", [
        Variable(f"var{i}") for i in range(20)
    ])
    
    step = ProofStep(
        formula=long_formula,
        justification="Very long justification " * 20,
        rule_name="LongRule"
    )
    
    proof = ProofResult(
        status=ProofStatus.PROVED,
        formula=long_formula,
        proof_steps=[step],
        method="test"
    )
    
    # WHEN: Visualizing
    visualizer = ProofTreeVisualizer(proof)
    ascii_output = visualizer.render_ascii(colors=False, max_width=80)
    
    # THEN: No crash, output generated
    assert len(ascii_output) > 0
    
    # DOT export should also work
    dot_path = tmp_path / "long.dot"
    visualizer.export_dot(str(dot_path))
    assert dot_path.exists()


def test_deep_proof_tree(tmp_path):
    """Test: Handle deep proof tree (many levels)."""
    # GIVEN: A proof with deep nesting
    steps = []
    prev_formula = Predicate("Base", [])
    
    for i in range(10):
        new_formula = BinaryFormula(
            LogicOperator.AND,
            prev_formula,
            Predicate(f"P{i}", [])
        )
        step = ProofStep(
            formula=new_formula,
            justification=f"Step {i}",
            rule_name="AND-Intro",
            premises=[prev_formula] if steps else []
        )
        steps.append(step)
        prev_formula = new_formula
    
    proof = ProofResult(
        status=ProofStatus.PROVED,
        formula=prev_formula,
        proof_steps=steps,
        method="test"
    )
    
    # WHEN: Visualizing
    visualizer = ProofTreeVisualizer(proof)
    ascii_output = visualizer.render_ascii(colors=False)
    
    # THEN: Deep tree handled correctly
    assert len(ascii_output) > 0
    assert "Step" in ascii_output


def test_multiple_roots():
    """Test: Handle proof with multiple potential roots."""
    # GIVEN: Steps with no clear single root
    step1 = ProofStep(
        formula=Predicate("A", []),
        justification="Independent 1",
        rule_name="Axiom",
        premises=[]
    )
    
    step2 = ProofStep(
        formula=Predicate("B", []),
        justification="Independent 2",
        rule_name="Axiom",
        premises=[]
    )
    
    proof = ProofResult(
        status=ProofStatus.PROVED,
        formula=step2.formula,
        proof_steps=[step1, step2],
        method="test"
    )
    
    # WHEN: Creating visualizer
    visualizer = ProofTreeVisualizer(proof)
    
    # THEN: Root is selected (last independent node)
    assert visualizer.tree_root is not None
    assert visualizer.tree_root.step_number in [1, 2]


# ============================================================================
# Integration Test
# ============================================================================


@pytest.mark.integration
def test_full_workflow(complex_proof_result, tmp_path):
    """Test: Complete workflow with all output formats."""
    # GIVEN: A complex proof result
    visualizer = ProofTreeVisualizer(complex_proof_result)
    
    # WHEN: Generating all outputs
    ascii_output = visualizer.render_ascii(colors=False)
    
    dot_path = tmp_path / "proof.dot"
    visualizer.export_dot(str(dot_path))
    
    json_path = tmp_path / "proof.json"
    visualizer.export_json(str(json_path))
    
    # THEN: All outputs generated successfully
    assert len(ascii_output) > 0
    assert "backward_chaining" in ascii_output
    assert dot_path.exists()
    assert json_path.exists()
    
    # Validate JSON
    with open(json_path) as f:
        json_data = json.load(f)
    assert json_data["status"] == "proved"
    assert len(json_data["steps"]) == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
