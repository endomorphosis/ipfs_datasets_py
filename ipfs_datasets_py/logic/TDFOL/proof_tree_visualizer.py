"""
TDFOL Proof Tree Visualizer - Comprehensive proof visualization for TDFOL

This module provides multiple visualization formats for TDFOL proof trees:
1. ASCII tree rendering with box-drawing characters
2. GraphViz DOT/SVG/PNG export
3. Interactive HTML output
4. JSON export for programmatic access

Supports different proof methods:
- Forward chaining
- Backward chaining
- Modal tableaux
- Resolution

Features:
- Colored terminal output
- Collapsible sub-proofs
- Inference rule annotations
- Node type highlighting
- Interactive hover tooltips
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from .tdfol_core import Formula
from .tdfol_prover import ProofResult, ProofStatus, ProofStep

logger = logging.getLogger(__name__)

# Try to import optional dependencies
try:
    import colorama
    from colorama import Fore, Back, Style
    colorama.init(autoreset=True)
    HAS_COLORAMA = True
except ImportError:
    HAS_COLORAMA = False
    logger.debug("colorama not available, colors disabled")

try:
    import graphviz
    HAS_GRAPHVIZ = True
except ImportError:
    HAS_GRAPHVIZ = False
    logger.debug("graphviz not available, DOT export only")


# ============================================================================
# Node Types and Tree Structure
# ============================================================================


class NodeType(Enum):
    """Type of node in proof tree."""
    
    AXIOM = "axiom"           # Given axiom
    PREMISE = "premise"       # Premise/assumption
    INFERRED = "inferred"     # Inferred via rule
    THEOREM = "theorem"       # Proved theorem
    GOAL = "goal"             # Goal to prove
    CONTRADICTION = "contradiction"  # Contradiction (for refutation)
    LEMMA = "lemma"           # Intermediate lemma


class TreeStyle(Enum):
    """Style for ASCII tree rendering."""
    
    COMPACT = "compact"       # Minimal spacing
    EXPANDED = "expanded"     # More spacing
    DETAILED = "detailed"     # Full details with extra info


class VerbosityLevel(Enum):
    """Verbosity level for output."""
    
    MINIMAL = "minimal"       # Only formula
    NORMAL = "normal"         # Formula + rule
    DETAILED = "detailed"     # Formula + rule + premises + justification


@dataclass
class ProofTreeNode:
    """Node in proof tree structure."""
    
    formula: Formula
    node_type: NodeType
    rule_name: Optional[str] = None
    justification: str = ""
    step_number: int = 0
    premises: List[ProofTreeNode] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __hash__(self) -> int:
        """Make node hashable for use in sets/dicts."""
        return hash((id(self), self.step_number))


# ============================================================================
# ASCII Box Drawing Characters
# ============================================================================


class BoxChars:
    """Box-drawing characters for ASCII trees."""
    
    # Tree structure
    VERTICAL = "│"
    HORIZONTAL = "─"
    TEE = "├"
    CORNER = "└"
    
    # Extended
    TEE_RIGHT = "├─"
    CORNER_RIGHT = "└─"
    VERTICAL_RIGHT = "│ "
    SPACE = "  "
    
    # Compact variants
    COMPACT_TEE = "├"
    COMPACT_CORNER = "└"
    COMPACT_VERTICAL = "│"
    
    # Double-line variants for emphasis
    DOUBLE_HORIZONTAL = "═"
    DOUBLE_VERTICAL = "║"


# ============================================================================
# Color Schemes
# ============================================================================


class ColorScheme:
    """Color scheme for terminal output."""
    
    if HAS_COLORAMA:
        AXIOM = Fore.GREEN
        PREMISE = Fore.CYAN
        INFERRED = Fore.YELLOW
        THEOREM = Fore.BLUE
        GOAL = Fore.MAGENTA
        CONTRADICTION = Fore.RED
        LEMMA = Fore.WHITE
        
        RULE = Fore.LIGHTBLACK_EX
        JUSTIFICATION = Fore.LIGHTBLACK_EX
        STEP_NUMBER = Fore.LIGHTBLACK_EX
        
        RESET = Style.RESET_ALL
        BOLD = Style.BRIGHT
    else:
        # No-op if colorama not available
        AXIOM = PREMISE = INFERRED = THEOREM = GOAL = ""
        CONTRADICTION = LEMMA = RULE = JUSTIFICATION = ""
        STEP_NUMBER = RESET = BOLD = ""
    
    @classmethod
    def get_node_color(cls, node_type: NodeType) -> str:
        """Get color for node type."""
        mapping = {
            NodeType.AXIOM: cls.AXIOM,
            NodeType.PREMISE: cls.PREMISE,
            NodeType.INFERRED: cls.INFERRED,
            NodeType.THEOREM: cls.THEOREM,
            NodeType.GOAL: cls.GOAL,
            NodeType.CONTRADICTION: cls.CONTRADICTION,
            NodeType.LEMMA: cls.LEMMA,
        }
        return mapping.get(node_type, "")


# ============================================================================
# GraphViz Color Schemes
# ============================================================================


class GraphvizColors:
    """Color scheme for GraphViz visualization."""
    
    NODE_COLORS = {
        NodeType.AXIOM: "#90EE90",           # Light green
        NodeType.PREMISE: "#87CEEB",         # Sky blue
        NodeType.INFERRED: "#FFFFE0",        # Light yellow
        NodeType.THEOREM: "#4169E1",         # Royal blue
        NodeType.GOAL: "#DDA0DD",            # Plum
        NodeType.CONTRADICTION: "#FF6B6B",   # Light red
        NodeType.LEMMA: "#F0F0F0",           # Light gray
    }
    
    NODE_FONT_COLORS = {
        NodeType.AXIOM: "#006400",           # Dark green
        NodeType.PREMISE: "#00008B",         # Dark blue
        NodeType.INFERRED: "#8B8B00",        # Dark yellow
        NodeType.THEOREM: "#FFFFFF",         # White
        NodeType.GOAL: "#800080",            # Purple
        NodeType.CONTRADICTION: "#8B0000",   # Dark red
        NodeType.LEMMA: "#000000",           # Black
    }
    
    EDGE_COLOR = "#666666"
    EDGE_FONT_COLOR = "#333333"


# ============================================================================
# ProofTreeVisualizer - Main Class
# ============================================================================


class ProofTreeVisualizer:
    """
    Comprehensive visualization for TDFOL proof trees.
    
    Provides multiple output formats:
    - ASCII tree (terminal-friendly with colors)
    - GraphViz DOT (for external rendering)
    - SVG (via GraphViz)
    - PNG (via GraphViz)
    - Interactive HTML
    - JSON (structured data)
    
    Example:
        >>> visualizer = ProofTreeVisualizer(proof_result)
        >>> print(visualizer.render_ascii(style='tree', colors=True))
        >>> visualizer.render_svg("proof_tree.svg")
        >>> visualizer.render_html("proof_tree.html", interactive=True)
    """
    
    def __init__(
        self,
        proof_result: ProofResult,
        verbosity: VerbosityLevel = VerbosityLevel.NORMAL
    ):
        """
        Initialize visualizer with proof result.
        
        Args:
            proof_result: Result from TDFOL prover
            verbosity: Level of detail in output
        """
        self.proof_result = proof_result
        self.verbosity = verbosity
        self.tree_root: Optional[ProofTreeNode] = None
        self.all_nodes: List[ProofTreeNode] = []
        self.node_id_map: Dict[ProofTreeNode, str] = {}
        
        # Build tree structure from proof steps
        self._build_tree()
    
    def _build_tree(self) -> None:
        """Build tree structure from proof steps."""
        if not self.proof_result.proof_steps:
            # No steps, create single node for formula
            self.tree_root = ProofTreeNode(
                formula=self.proof_result.formula,
                node_type=self._get_node_type_from_status(),
                step_number=1
            )
            self.all_nodes = [self.tree_root]
            return
        
        # Map formulas to nodes
        formula_to_node: Dict[str, ProofTreeNode] = {}
        nodes_in_order: List[ProofTreeNode] = []
        
        for i, step in enumerate(self.proof_result.proof_steps, 1):
            node_type = self._infer_node_type(step, i)
            
            node = ProofTreeNode(
                formula=step.formula,
                node_type=node_type,
                rule_name=step.rule_name,
                justification=step.justification,
                step_number=i,
                premises=[]
            )
            
            # Link premises
            for premise_formula in step.premises:
                premise_key = premise_formula.to_string()
                if premise_key in formula_to_node:
                    premise_node = formula_to_node[premise_key]
                    node.premises.append(premise_node)
            
            formula_key = step.formula.to_string()
            formula_to_node[formula_key] = node
            nodes_in_order.append(node)
            self.all_nodes.append(node)
        
        # Root is last node (conclusion) or find nodes with no dependents
        if nodes_in_order:
            # Find root: node that is not a premise of any other node
            dependent_nodes = set()
            for node in nodes_in_order:
                for premise in node.premises:
                    dependent_nodes.add(premise)
            
            root_candidates = [n for n in nodes_in_order if n not in dependent_nodes]
            self.tree_root = root_candidates[-1] if root_candidates else nodes_in_order[-1]
        else:
            self.tree_root = None
    
    def _get_node_type_from_status(self) -> NodeType:
        """Get node type from proof status."""
        if self.proof_result.status == ProofStatus.PROVED:
            return NodeType.THEOREM
        elif self.proof_result.status == ProofStatus.DISPROVED:
            return NodeType.CONTRADICTION
        else:
            return NodeType.GOAL
    
    def _infer_node_type(self, step: ProofStep, step_num: int) -> NodeType:
        """Infer node type from proof step."""
        # First steps with no premises are axioms/premises
        if not step.premises:
            if step_num <= 3:  # First few steps typically axioms
                return NodeType.AXIOM
            return NodeType.PREMISE
        
        # Check if this is the final conclusion
        if step_num == len(self.proof_result.proof_steps):
            if self.proof_result.status == ProofStatus.PROVED:
                return NodeType.THEOREM
            elif self.proof_result.status == ProofStatus.DISPROVED:
                return NodeType.CONTRADICTION
        
        # Check for contradiction in justification
        if "contradiction" in step.justification.lower():
            return NodeType.CONTRADICTION
        
        # Intermediate inferred steps
        return NodeType.INFERRED
    
    # ========================================================================
    # ASCII Rendering
    # ========================================================================
    
    def render_ascii(
        self,
        style: str = 'tree',
        colors: bool = True,
        max_width: int = 100
    ) -> str:
        """
        Render proof tree as ASCII art.
        
        Args:
            style: Tree style ('tree', 'compact', 'expanded', 'detailed')
            colors: Enable terminal colors (requires colorama)
            max_width: Maximum line width
        
        Returns:
            ASCII representation of proof tree
        """
        if not colors or not HAS_COLORAMA:
            colors = False
        
        tree_style = TreeStyle.COMPACT
        if style == 'expanded':
            tree_style = TreeStyle.EXPANDED
        elif style == 'detailed':
            tree_style = TreeStyle.DETAILED
        
        if not self.tree_root:
            return "Empty proof tree"
        
        lines = []
        
        # Header
        if colors:
            header = f"{ColorScheme.BOLD}Proof Tree - {self.proof_result.method}{ColorScheme.RESET}"
        else:
            header = f"Proof Tree - {self.proof_result.method}"
        lines.append(header)
        lines.append("=" * min(len(self.proof_result.method) + 13, max_width))
        lines.append("")
        
        # Status line
        status_color = ColorScheme.THEOREM if self.proof_result.is_proved() else ColorScheme.CONTRADICTION
        if colors:
            status_line = f"Status: {status_color}{self.proof_result.status.value}{ColorScheme.RESET}"
        else:
            status_line = f"Status: {self.proof_result.status.value}"
        lines.append(status_line)
        
        if self.proof_result.message:
            lines.append(f"Message: {self.proof_result.message}")
        
        lines.append(f"Time: {self.proof_result.time_ms:.2f} ms")
        lines.append(f"Steps: {len(self.proof_result.proof_steps)}")
        lines.append("")
        
        # Render tree
        tree_lines = self._render_node_ascii(
            self.tree_root,
            prefix="",
            is_last=True,
            colors=colors,
            style=tree_style,
            max_width=max_width
        )
        lines.extend(tree_lines)
        
        return "\n".join(lines)
    
    def _render_node_ascii(
        self,
        node: ProofTreeNode,
        prefix: str,
        is_last: bool,
        colors: bool,
        style: TreeStyle,
        max_width: int
    ) -> List[str]:
        """Render single node and children as ASCII."""
        lines = []
        
        # Node connector
        if prefix:
            connector = BoxChars.CORNER_RIGHT if is_last else BoxChars.TEE_RIGHT
        else:
            connector = ""
        
        # Format formula
        formula_str = node.formula.to_string(pretty=True)
        if len(formula_str) > max_width - len(prefix) - 10:
            formula_str = formula_str[:max_width - len(prefix) - 13] + "..."
        
        # Color formula by node type
        if colors:
            node_color = ColorScheme.get_node_color(node.node_type)
            formula_str = f"{node_color}{formula_str}{ColorScheme.RESET}"
        
        # Build node line
        if self.verbosity == VerbosityLevel.MINIMAL:
            node_line = f"{prefix}{connector}{formula_str}"
        else:
            step_num_str = f"[{node.step_number}]"
            if colors:
                step_num_str = f"{ColorScheme.STEP_NUMBER}{step_num_str}{ColorScheme.RESET}"
            
            node_line = f"{prefix}{connector}{step_num_str} {formula_str}"
            
            # Add rule name
            if node.rule_name and self.verbosity != VerbosityLevel.MINIMAL:
                rule_str = f"  ({node.rule_name})"
                if colors:
                    rule_str = f"{ColorScheme.RULE}{rule_str}{ColorScheme.RESET}"
                node_line += rule_str
        
        lines.append(node_line)
        
        # Add justification for detailed mode
        if style == TreeStyle.DETAILED and node.justification:
            just_prefix = prefix + (BoxChars.SPACE if is_last else BoxChars.VERTICAL_RIGHT)
            just_str = f"    └─ {node.justification}"
            if colors:
                just_str = f"{ColorScheme.JUSTIFICATION}{just_str}{ColorScheme.RESET}"
            lines.append(just_prefix + just_str)
        
        # Render premises (children)
        if node.premises:
            for i, premise in enumerate(node.premises):
                is_last_child = (i == len(node.premises) - 1)
                
                if is_last:
                    child_prefix = prefix + BoxChars.SPACE
                else:
                    child_prefix = prefix + BoxChars.VERTICAL_RIGHT
                
                child_lines = self._render_node_ascii(
                    premise,
                    child_prefix,
                    is_last_child,
                    colors,
                    style,
                    max_width
                )
                lines.extend(child_lines)
        
        return lines
    
    # ========================================================================
    # GraphViz DOT Export
    # ========================================================================
    
    def export_dot(self, output_path: str) -> None:
        """
        Export proof tree as GraphViz DOT file.
        
        Args:
            output_path: Path to output DOT file
        """
        if not self.tree_root:
            logger.warning("Empty proof tree, nothing to export")
            return
        
        dot_lines = []
        dot_lines.append("digraph ProofTree {")
        dot_lines.append("    rankdir=TB;")  # Top to bottom
        dot_lines.append("    node [shape=box, style=filled];")
        dot_lines.append("    edge [dir=back];")  # Arrows point from conclusion to premises
        dot_lines.append("")
        
        # Assign IDs to nodes
        self._assign_node_ids()
        
        # Generate nodes
        for node in self.all_nodes:
            node_id = self.node_id_map[node]
            label = self._get_dot_node_label(node)
            color = GraphvizColors.NODE_COLORS.get(node.node_type, "#FFFFFF")
            font_color = GraphvizColors.NODE_FONT_COLORS.get(node.node_type, "#000000")
            
            dot_lines.append(
                f'    {node_id} [label="{label}", '
                f'fillcolor="{color}", fontcolor="{font_color}"];'
            )
        
        dot_lines.append("")
        
        # Generate edges
        for node in self.all_nodes:
            node_id = self.node_id_map[node]
            for premise in node.premises:
                premise_id = self.node_id_map[premise]
                edge_label = node.rule_name or ""
                
                dot_lines.append(
                    f'    {node_id} -> {premise_id} '
                    f'[label="{edge_label}", color="{GraphvizColors.EDGE_COLOR}", '
                    f'fontcolor="{GraphvizColors.EDGE_FONT_COLOR}"];'
                )
        
        dot_lines.append("}")
        
        # Write to file
        output_file = Path(output_path)
        output_file.write_text("\n".join(dot_lines))
        logger.info(f"Exported DOT file to {output_path}")
    
    def _assign_node_ids(self) -> None:
        """Assign unique IDs to all nodes."""
        for i, node in enumerate(self.all_nodes):
            self.node_id_map[node] = f"node_{i}"
    
    def _get_dot_node_label(self, node: ProofTreeNode) -> str:
        """Get label for DOT node."""
        formula_str = node.formula.to_string(pretty=True)
        # Escape quotes for DOT
        formula_str = formula_str.replace('"', '\\"')
        
        if self.verbosity == VerbosityLevel.MINIMAL:
            return formula_str
        
        label_parts = [f"[{node.step_number}] {formula_str}"]
        
        if node.node_type != NodeType.INFERRED:
            label_parts.append(f"({node.node_type.value})")
        
        return "\\n".join(label_parts)
    
    # ========================================================================
    # SVG and PNG Rendering (via GraphViz)
    # ========================================================================
    
    def render_svg(self, output_path: str) -> None:
        """
        Render proof tree as SVG using GraphViz.
        
        Args:
            output_path: Path to output SVG file
        """
        if not HAS_GRAPHVIZ:
            # Fall back to command-line dot if available
            self._render_via_command_line(output_path, "svg")
        else:
            self._render_via_graphviz_lib(output_path, "svg")
    
    def render_png(self, output_path: str) -> None:
        """
        Render proof tree as PNG using GraphViz.
        
        Args:
            output_path: Path to output PNG file
        """
        if not HAS_GRAPHVIZ:
            self._render_via_command_line(output_path, "png")
        else:
            self._render_via_graphviz_lib(output_path, "png")
    
    def _render_via_graphviz_lib(self, output_path: str, format: str) -> None:
        """Render using graphviz Python library."""
        if not self.tree_root:
            logger.warning("Empty proof tree, nothing to render")
            return
        
        import graphviz
        
        dot = graphviz.Digraph(comment='Proof Tree')
        dot.attr(rankdir='TB')
        dot.attr('node', shape='box', style='filled')
        dot.attr('edge', dir='back')
        
        # Assign IDs
        self._assign_node_ids()
        
        # Add nodes
        for node in self.all_nodes:
            node_id = self.node_id_map[node]
            label = self._get_dot_node_label(node)
            color = GraphvizColors.NODE_COLORS.get(node.node_type, "#FFFFFF")
            font_color = GraphvizColors.NODE_FONT_COLORS.get(node.node_type, "#000000")
            
            dot.node(node_id, label, fillcolor=color, fontcolor=font_color)
        
        # Add edges
        for node in self.all_nodes:
            node_id = self.node_id_map[node]
            for premise in node.premises:
                premise_id = self.node_id_map[premise]
                edge_label = node.rule_name or ""
                dot.edge(
                    node_id,
                    premise_id,
                    label=edge_label,
                    color=GraphvizColors.EDGE_COLOR,
                    fontcolor=GraphvizColors.EDGE_FONT_COLOR
                )
        
        # Render
        output_file = Path(output_path)
        dot.render(
            filename=str(output_file.with_suffix('')),
            format=format,
            cleanup=True
        )
        logger.info(f"Rendered {format.upper()} to {output_path}")
    
    def _render_via_command_line(self, output_path: str, format: str) -> None:
        """Render using command-line dot tool."""
        # Create temporary DOT file
        import tempfile
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.dot', delete=False) as f:
            temp_dot = f.name
            self.export_dot(temp_dot)
        
        try:
            # Run dot command
            result = subprocess.run(
                ['dot', f'-T{format}', temp_dot, '-o', output_path],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                logger.info(f"Rendered {format.upper()} to {output_path}")
            else:
                logger.error(f"GraphViz error: {result.stderr}")
                raise RuntimeError(f"Failed to render {format}: {result.stderr}")
        finally:
            # Clean up temp file
            Path(temp_dot).unlink(missing_ok=True)
    
    # ========================================================================
    # Interactive HTML Output
    # ========================================================================
    
    def render_html(self, output_path: str, interactive: bool = True) -> None:
        """
        Render proof tree as interactive HTML.
        
        Args:
            output_path: Path to output HTML file
            interactive: Enable interactive features (collapsible nodes, tooltips)
        """
        if not self.tree_root:
            logger.warning("Empty proof tree, nothing to render")
            return
        
        # Generate SVG first
        import tempfile
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.svg', delete=False) as f:
            temp_svg = f.name
        
        try:
            self.render_svg(temp_svg)
            svg_content = Path(temp_svg).read_text()
        finally:
            Path(temp_svg).unlink(missing_ok=True)
        
        # Build HTML
        html_parts = []
        html_parts.append("<!DOCTYPE html>")
        html_parts.append("<html>")
        html_parts.append("<head>")
        html_parts.append("    <meta charset='UTF-8'>")
        html_parts.append("    <title>TDFOL Proof Tree</title>")
        html_parts.append("    <style>")
        html_parts.append(self._get_html_css(interactive))
        html_parts.append("    </style>")
        html_parts.append("</head>")
        html_parts.append("<body>")
        html_parts.append("    <div class='container'>")
        html_parts.append("        <h1>TDFOL Proof Tree Visualization</h1>")
        
        # Metadata
        html_parts.append("        <div class='metadata'>")
        html_parts.append(f"            <p><strong>Method:</strong> {self.proof_result.method}</p>")
        html_parts.append(f"            <p><strong>Status:</strong> <span class='status-{self.proof_result.status.value}'>{self.proof_result.status.value}</span></p>")
        html_parts.append(f"            <p><strong>Time:</strong> {self.proof_result.time_ms:.2f} ms</p>")
        html_parts.append(f"            <p><strong>Steps:</strong> {len(self.proof_result.proof_steps)}</p>")
        if self.proof_result.message:
            html_parts.append(f"            <p><strong>Message:</strong> {self.proof_result.message}</p>")
        html_parts.append("        </div>")
        
        # SVG
        html_parts.append("        <div class='svg-container'>")
        html_parts.append(svg_content)
        html_parts.append("        </div>")
        
        # Step-by-step proof
        html_parts.append("        <div class='proof-steps'>")
        html_parts.append("            <h2>Proof Steps</h2>")
        html_parts.append("            <ol>")
        for step in self.proof_result.proof_steps:
            formula_str = step.formula.to_string(pretty=True)
            html_parts.append(f"                <li>")
            html_parts.append(f"                    <strong>{formula_str}</strong>")
            if step.rule_name:
                html_parts.append(f"                    <span class='rule-name'>({step.rule_name})</span>")
            if step.justification:
                html_parts.append(f"                    <div class='justification'>{step.justification}</div>")
            html_parts.append(f"                </li>")
        html_parts.append("            </ol>")
        html_parts.append("        </div>")
        
        if interactive:
            html_parts.append("    <script>")
            html_parts.append(self._get_html_javascript())
            html_parts.append("    </script>")
        
        html_parts.append("    </div>")
        html_parts.append("</body>")
        html_parts.append("</html>")
        
        # Write to file
        output_file = Path(output_path)
        output_file.write_text("\n".join(html_parts))
        logger.info(f"Rendered interactive HTML to {output_path}")
    
    def _get_html_css(self, interactive: bool) -> str:
        """Get CSS for HTML output."""
        css = """
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background-color: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        h1 {
            color: #333;
            border-bottom: 3px solid #4169E1;
            padding-bottom: 10px;
        }
        h2 {
            color: #555;
            margin-top: 30px;
        }
        .metadata {
            background-color: #f9f9f9;
            padding: 15px;
            border-radius: 4px;
            margin: 20px 0;
        }
        .metadata p {
            margin: 5px 0;
        }
        .status-proved {
            color: #28a745;
            font-weight: bold;
        }
        .status-disproved {
            color: #dc3545;
            font-weight: bold;
        }
        .status-unknown {
            color: #ffc107;
            font-weight: bold;
        }
        .svg-container {
            margin: 30px 0;
            text-align: center;
            background-color: white;
            border: 1px solid #ddd;
            border-radius: 4px;
            padding: 20px;
        }
        .svg-container svg {
            max-width: 100%;
            height: auto;
        }
        .proof-steps {
            margin-top: 30px;
        }
        .proof-steps ol {
            line-height: 1.8;
        }
        .proof-steps li {
            margin-bottom: 10px;
        }
        .rule-name {
            color: #666;
            font-style: italic;
            margin-left: 10px;
        }
        .justification {
            color: #888;
            font-size: 0.9em;
            margin-top: 5px;
            margin-left: 20px;
        }
        """
        
        if interactive:
            css += """
        .node:hover {
            cursor: pointer;
            opacity: 0.8;
        }
        .tooltip {
            position: absolute;
            background-color: #333;
            color: white;
            padding: 8px;
            border-radius: 4px;
            font-size: 12px;
            pointer-events: none;
            opacity: 0;
            transition: opacity 0.3s;
        }
            """
        
        return css
    
    def _get_html_javascript(self) -> str:
        """Get JavaScript for interactive HTML."""
        return """
        // Add interactivity
        document.addEventListener('DOMContentLoaded', function() {
            const nodes = document.querySelectorAll('.node');
            
            nodes.forEach(node => {
                node.addEventListener('click', function() {
                    this.classList.toggle('highlighted');
                });
            });
        });
        """
    
    # ========================================================================
    # JSON Export
    # ========================================================================
    
    def to_json(self) -> Dict[str, Any]:
        """
        Export proof tree as JSON structure.
        
        Returns:
            Dictionary representation of proof tree
        """
        if not self.tree_root:
            return {
                "status": self.proof_result.status.value,
                "formula": self.proof_result.formula.to_string(),
                "nodes": []
            }
        
        return {
            "status": self.proof_result.status.value,
            "formula": self.proof_result.formula.to_string(),
            "method": self.proof_result.method,
            "time_ms": self.proof_result.time_ms,
            "message": self.proof_result.message,
            "tree": self._node_to_dict(self.tree_root),
            "steps": [
                {
                    "step_number": i,
                    "formula": step.formula.to_string(),
                    "rule_name": step.rule_name,
                    "justification": step.justification,
                    "premises": [p.to_string() for p in step.premises]
                }
                for i, step in enumerate(self.proof_result.proof_steps, 1)
            ]
        }
    
    def _node_to_dict(self, node: ProofTreeNode) -> Dict[str, Any]:
        """Convert node to dictionary."""
        return {
            "formula": node.formula.to_string(),
            "node_type": node.node_type.value,
            "step_number": node.step_number,
            "rule_name": node.rule_name,
            "justification": node.justification,
            "premises": [self._node_to_dict(p) for p in node.premises]
        }
    
    def export_json(self, output_path: str, indent: int = 2) -> None:
        """
        Export proof tree as JSON file.
        
        Args:
            output_path: Path to output JSON file
            indent: Indentation level for pretty printing
        """
        json_data = self.to_json()
        output_file = Path(output_path)
        output_file.write_text(json.dumps(json_data, indent=indent))
        logger.info(f"Exported JSON to {output_path}")


# ============================================================================
# Convenience Functions
# ============================================================================


def visualize_proof(
    proof_result: ProofResult,
    output_format: str = "ascii",
    output_path: Optional[str] = None,
    **kwargs
) -> Optional[str]:
    """
    Convenience function to visualize a proof result.
    
    Args:
        proof_result: Result from TDFOL prover
        output_format: Format ('ascii', 'dot', 'svg', 'png', 'html', 'json')
        output_path: Output file path (required for non-ascii formats)
        **kwargs: Additional arguments passed to visualization method
    
    Returns:
        ASCII string if output_format is 'ascii', None otherwise
    
    Example:
        >>> # ASCII output
        >>> print(visualize_proof(proof_result, output_format='ascii', colors=True))
        
        >>> # SVG output
        >>> visualize_proof(proof_result, output_format='svg', output_path='proof.svg')
    """
    visualizer = ProofTreeVisualizer(proof_result)
    
    if output_format == "ascii":
        return visualizer.render_ascii(**kwargs)
    elif output_format == "dot":
        if not output_path:
            raise ValueError("output_path required for DOT format")
        visualizer.export_dot(output_path)
    elif output_format == "svg":
        if not output_path:
            raise ValueError("output_path required for SVG format")
        visualizer.render_svg(output_path)
    elif output_format == "png":
        if not output_path:
            raise ValueError("output_path required for PNG format")
        visualizer.render_png(output_path)
    elif output_format == "html":
        if not output_path:
            raise ValueError("output_path required for HTML format")
        visualizer.render_html(output_path, **kwargs)
    elif output_format == "json":
        if not output_path:
            raise ValueError("output_path required for JSON format")
        visualizer.export_json(output_path, **kwargs)
    else:
        raise ValueError(f"Unknown output format: {output_format}")
    
    return None
