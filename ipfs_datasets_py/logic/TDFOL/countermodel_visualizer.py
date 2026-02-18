"""
Enhanced Countermodel Visualization for TDFOL

This module provides enhanced visualization capabilities for countermodels extracted from
failed modal tableaux proofs. It extends the basic visualization in countermodels.py with:

1. Enhanced ASCII art with box-drawing characters and terminal colors
2. Interactive HTML visualization with D3.js for graph rendering
3. Accessibility graph rendering with specialized layouts
4. Support for multiple modal logic types (K, T, D, S4, S5)

Features:
- Color-coded terminal output using colorama
- Interactive HTML with clickable worlds and tooltips
- Animated transitions and zoom/pan capabilities
- Graph layout algorithms for optimal world positioning
- Reflexive, symmetric, transitive relation highlighting
- Export as standalone HTML files

Example:
    >>> from countermodels import extract_countermodel, CounterModel
    >>> from countermodel_visualizer import CountermodelVisualizer
    >>> 
    >>> visualizer = CountermodelVisualizer(countermodel.kripke)
    >>> print(visualizer.render_ascii_enhanced(colors=True))
    >>> visualizer.render_html_interactive("countermodel.html")
    >>> visualizer.render_accessibility_graph("graph.svg", format="svg")
"""

from __future__ import annotations

import html
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

try:
    from colorama import Fore, Back, Style, init as colorama_init
    COLORAMA_AVAILABLE = True
except ImportError:
    COLORAMA_AVAILABLE = False
    # Fallback stubs
    class _Fore:
        RED = GREEN = BLUE = YELLOW = CYAN = MAGENTA = WHITE = RESET = ""
    class _Back:
        BLACK = BLUE = RED = RESET = ""
    class _Style:
        BRIGHT = DIM = RESET_ALL = ""
    Fore = _Fore()
    Back = _Back()
    Style = _Style()
    def colorama_init(): pass

from .countermodels import KripkeStructure
from .modal_tableaux import ModalLogicType

logger = logging.getLogger(__name__)


# Box-drawing characters for enhanced ASCII
class BoxChars:
    """Unicode box-drawing characters for enhanced ASCII art."""
    HORIZONTAL = "─"
    VERTICAL = "│"
    TOP_LEFT = "┌"
    TOP_RIGHT = "┐"
    BOTTOM_LEFT = "└"
    BOTTOM_RIGHT = "┘"
    T_RIGHT = "├"
    T_LEFT = "┤"
    T_DOWN = "┬"
    T_UP = "┴"
    CROSS = "┼"
    ARROW_RIGHT = "→"
    ARROW_DOWN = "↓"
    DOUBLE_ARROW_RIGHT = "⇒"
    BULLET = "•"
    CHECK = "✓"
    CROSS_MARK = "✗"


@dataclass
class GraphLayout:
    """Layout information for rendering accessibility graphs."""
    positions: Dict[int, Tuple[float, float]]  # world_id -> (x, y)
    width: int
    height: int
    
    def __init__(self, positions: Optional[Dict[int, Tuple[float, float]]] = None,
                 width: int = 800, height: int = 600):
        self.positions = positions or {}
        self.width = width
        self.height = height


class CountermodelVisualizer:
    """
    Enhanced visualizer for Kripke structures from countermodels.
    
    Provides multiple visualization formats with enhanced features:
    - Enhanced ASCII art with colors and box-drawing
    - Interactive HTML with D3.js
    - Accessibility graph rendering
    
    Args:
        kripke_structure: The Kripke structure to visualize
        
    Example:
        >>> kripke = KripkeStructure(logic_type=ModalLogicType.K)
        >>> kripke.add_world(0)
        >>> kripke.add_world(1)
        >>> kripke.add_accessibility(0, 1)
        >>> visualizer = CountermodelVisualizer(kripke)
        >>> print(visualizer.render_ascii_enhanced())
    """
    
    def __init__(self, kripke_structure: KripkeStructure):
        """Initialize the visualizer with a Kripke structure."""
        self.kripke = kripke_structure
        if COLORAMA_AVAILABLE:
            colorama_init(autoreset=True)
    
    def render_ascii_enhanced(self, colors: bool = True, style: str = 'expanded') -> str:
        """
        Render enhanced ASCII art visualization with box-drawing and colors.
        
        Args:
            colors: Enable terminal color output (requires colorama)
            style: Display style - 'expanded' or 'compact'
            
        Returns:
            Enhanced ASCII art representation
            
        Example:
            >>> visualizer.render_ascii_enhanced(colors=True, style='expanded')
            ┌─────────────────────────────────┐
            │ Kripke Structure (Logic: K)     │
            │ Worlds: 2, Relations: 1         │
            └─────────────────────────────────┘
            ...
        """
        if colors and not COLORAMA_AVAILABLE:
            logger.warning("colorama not available, rendering without colors")
            colors = False
        
        if style == 'expanded':
            return self._render_ascii_expanded(colors)
        elif style == 'compact':
            return self._render_ascii_compact(colors)
        else:
            raise ValueError(f"Unknown style: {style}. Use 'expanded' or 'compact'")
    
    def _render_ascii_expanded(self, colors: bool) -> str:
        """Render expanded ASCII art with detailed formatting."""
        lines = []
        
        # Header box
        header_text = f"Kripke Structure (Logic: {self.kripke.logic_type.value})"
        info_text = f"Worlds: {len(self.kripke.worlds)}, Relations: {sum(len(v) for v in self.kripke.accessibility.values())}"
        
        max_width = max(len(header_text), len(info_text)) + 4
        
        # Top border
        lines.append(BoxChars.TOP_LEFT + BoxChars.HORIZONTAL * (max_width - 2) + BoxChars.TOP_RIGHT)
        lines.append(BoxChars.VERTICAL + f" {header_text}".ljust(max_width - 2) + BoxChars.VERTICAL)
        lines.append(BoxChars.VERTICAL + f" {info_text}".ljust(max_width - 2) + BoxChars.VERTICAL)
        lines.append(BoxChars.BOTTOM_LEFT + BoxChars.HORIZONTAL * (max_width - 2) + BoxChars.BOTTOM_RIGHT)
        lines.append("")
        
        # Render each world
        for world_id in sorted(self.kripke.worlds):
            lines.extend(self._render_world_expanded(world_id, colors))
            lines.append("")
        
        # Accessibility table
        lines.append(self._render_accessibility_table(colors))
        
        # Logic properties
        lines.append("")
        lines.append(self._render_logic_properties(colors))
        
        return '\n'.join(lines)
    
    def _render_world_expanded(self, world_id: int, colors: bool) -> List[str]:
        """Render a single world in expanded format."""
        lines = []
        atoms = sorted(self.kripke.valuation.get(world_id, set()))
        accessible = sorted(self.kripke.get_accessible_worlds(world_id))
        
        # World header
        is_initial = (world_id == self.kripke.initial_world)
        if colors:
            if is_initial:
                world_label = f"{Fore.GREEN}{Style.BRIGHT}→ World w{world_id} (initial){Style.RESET_ALL}"
            else:
                world_label = f"{Fore.CYAN}  World w{world_id}{Style.RESET_ALL}"
        else:
            world_label = f"{'→' if is_initial else ' '} World w{world_id}{'(initial)' if is_initial else ''}"
        
        lines.append(world_label)
        lines.append(BoxChars.T_RIGHT + BoxChars.HORIZONTAL * 40)
        
        # Atoms (valuation)
        if atoms:
            if colors:
                atoms_str = f"{Fore.YELLOW}Atoms: {', '.join(atoms)}{Style.RESET_ALL}"
            else:
                atoms_str = f"Atoms: {', '.join(atoms)}"
        else:
            if colors:
                atoms_str = f"{Fore.RED}Atoms: ∅ (none){Style.RESET_ALL}"
            else:
                atoms_str = "Atoms: ∅ (none)"
        
        lines.append(BoxChars.VERTICAL + " " + atoms_str)
        
        # Accessible worlds
        if accessible:
            if colors:
                access_str = f"{Fore.MAGENTA}Accessible: {', '.join(f'w{w}' for w in accessible)}{Style.RESET_ALL}"
            else:
                access_str = f"Accessible: {', '.join(f'w{w}' for w in accessible)}"
            lines.append(BoxChars.VERTICAL + " " + access_str)
            
            # Draw arrows to accessible worlds
            for target in accessible:
                if colors:
                    arrow = f"{Fore.BLUE}{BoxChars.VERTICAL}  {BoxChars.ARROW_RIGHT} w{target}{Style.RESET_ALL}"
                else:
                    arrow = f"{BoxChars.VERTICAL}  {BoxChars.ARROW_RIGHT} w{target}"
                lines.append(arrow)
        else:
            if colors:
                access_str = f"{Fore.RED}Accessible: (none){Style.RESET_ALL}"
            else:
                access_str = "Accessible: (none)"
            lines.append(BoxChars.VERTICAL + " " + access_str)
        
        lines.append(BoxChars.BOTTOM_LEFT + BoxChars.HORIZONTAL * 40)
        
        return lines
    
    def _render_ascii_compact(self, colors: bool) -> str:
        """Render compact ASCII art."""
        lines = []
        
        # Compact header
        if colors:
            header = f"{Style.BRIGHT}Kripke({self.kripke.logic_type.value}){Style.RESET_ALL} " + \
                     f"W={len(self.kripke.worlds)} R={sum(len(v) for v in self.kripke.accessibility.values())}"
        else:
            header = f"Kripke({self.kripke.logic_type.value}) W={len(self.kripke.worlds)} " + \
                     f"R={sum(len(v) for v in self.kripke.accessibility.values())}"
        
        lines.append(header)
        lines.append(BoxChars.HORIZONTAL * 50)
        
        # Compact world listing
        for world_id in sorted(self.kripke.worlds):
            atoms = sorted(self.kripke.valuation.get(world_id, set()))
            accessible = sorted(self.kripke.get_accessible_worlds(world_id))
            
            is_initial = (world_id == self.kripke.initial_world)
            prefix = BoxChars.DOUBLE_ARROW_RIGHT if is_initial else BoxChars.BULLET
            
            atoms_str = ','.join(atoms) if atoms else "∅"
            access_str = ','.join(f"w{w}" for w in accessible) if accessible else "∅"
            
            if colors:
                line = f"{Fore.GREEN if is_initial else Fore.CYAN}{prefix} w{world_id}: " + \
                       f"{Fore.YELLOW}{{{atoms_str}}} {Fore.MAGENTA}{BoxChars.ARROW_RIGHT} {{{access_str}}}{Style.RESET_ALL}"
            else:
                line = f"{prefix} w{world_id}: {{{atoms_str}}} {BoxChars.ARROW_RIGHT} {{{access_str}}}"
            
            lines.append(line)
        
        return '\n'.join(lines)
    
    def _render_accessibility_table(self, colors: bool) -> str:
        """Render accessibility relations as a formatted table."""
        lines = []
        
        if colors:
            lines.append(f"{Style.BRIGHT}Accessibility Relations:{Style.RESET_ALL}")
        else:
            lines.append("Accessibility Relations:")
        
        lines.append(BoxChars.TOP_LEFT + BoxChars.HORIZONTAL * 12 + BoxChars.T_DOWN + 
                     BoxChars.HORIZONTAL * 30 + BoxChars.TOP_RIGHT)
        lines.append(BoxChars.VERTICAL + " From World ".ljust(13) + BoxChars.VERTICAL + 
                     " To Worlds".ljust(31) + BoxChars.VERTICAL)
        lines.append(BoxChars.T_RIGHT + BoxChars.HORIZONTAL * 12 + BoxChars.CROSS + 
                     BoxChars.HORIZONTAL * 30 + BoxChars.T_LEFT)
        
        for world_id in sorted(self.kripke.worlds):
            accessible = sorted(self.kripke.get_accessible_worlds(world_id))
            
            from_str = f"w{world_id}".ljust(12)
            to_str = (', '.join(f"w{w}" for w in accessible) if accessible else "(none)").ljust(30)
            
            if colors:
                if accessible:
                    line = BoxChars.VERTICAL + f" {Fore.CYAN}{from_str}{Style.RESET_ALL} " + \
                           BoxChars.VERTICAL + f" {Fore.MAGENTA}{to_str}{Style.RESET_ALL} " + BoxChars.VERTICAL
                else:
                    line = BoxChars.VERTICAL + f" {Fore.CYAN}{from_str}{Style.RESET_ALL} " + \
                           BoxChars.VERTICAL + f" {Fore.RED}{to_str}{Style.RESET_ALL} " + BoxChars.VERTICAL
            else:
                line = BoxChars.VERTICAL + f" {from_str} " + BoxChars.VERTICAL + f" {to_str} " + BoxChars.VERTICAL
            
            lines.append(line)
        
        lines.append(BoxChars.BOTTOM_LEFT + BoxChars.HORIZONTAL * 12 + BoxChars.T_UP + 
                     BoxChars.HORIZONTAL * 30 + BoxChars.BOTTOM_RIGHT)
        
        return '\n'.join(lines)
    
    def _render_logic_properties(self, colors: bool) -> str:
        """Render modal logic properties analysis."""
        lines = []
        
        if colors:
            lines.append(f"{Style.BRIGHT}Modal Logic Properties ({self.kripke.logic_type.value}):{Style.RESET_ALL}")
        else:
            lines.append(f"Modal Logic Properties ({self.kripke.logic_type.value}):")
        
        # Check properties
        is_reflexive = self._check_reflexive()
        is_symmetric = self._check_symmetric()
        is_transitive = self._check_transitive()
        is_serial = self._check_serial()
        
        check_mark = BoxChars.CHECK
        cross_mark = BoxChars.CROSS_MARK
        
        if colors:
            ref_str = f"{Fore.GREEN}{check_mark}{Style.RESET_ALL}" if is_reflexive else f"{Fore.RED}{cross_mark}{Style.RESET_ALL}"
            sym_str = f"{Fore.GREEN}{check_mark}{Style.RESET_ALL}" if is_symmetric else f"{Fore.RED}{cross_mark}{Style.RESET_ALL}"
            trans_str = f"{Fore.GREEN}{check_mark}{Style.RESET_ALL}" if is_transitive else f"{Fore.RED}{cross_mark}{Style.RESET_ALL}"
            ser_str = f"{Fore.GREEN}{check_mark}{Style.RESET_ALL}" if is_serial else f"{Fore.RED}{cross_mark}{Style.RESET_ALL}"
        else:
            ref_str = check_mark if is_reflexive else cross_mark
            sym_str = check_mark if is_symmetric else cross_mark
            trans_str = check_mark if is_transitive else cross_mark
            ser_str = check_mark if is_serial else cross_mark
        
        lines.append(f"  {ref_str} Reflexive: {is_reflexive}")
        lines.append(f"  {sym_str} Symmetric: {is_symmetric}")
        lines.append(f"  {trans_str} Transitive: {is_transitive}")
        lines.append(f"  {ser_str} Serial: {is_serial}")
        
        # Expected properties
        expected = self._get_expected_properties()
        if expected:
            lines.append("")
            if colors:
                lines.append(f"{Fore.YELLOW}Expected for {self.kripke.logic_type.value}: {', '.join(expected)}{Style.RESET_ALL}")
            else:
                lines.append(f"Expected for {self.kripke.logic_type.value}: {', '.join(expected)}")
        
        return '\n'.join(lines)
    
    def _check_reflexive(self) -> bool:
        """Check if accessibility relation is reflexive."""
        for world_id in self.kripke.worlds:
            if world_id not in self.kripke.get_accessible_worlds(world_id):
                return False
        return True
    
    def _check_symmetric(self) -> bool:
        """Check if accessibility relation is symmetric."""
        for from_world in self.kripke.worlds:
            for to_world in self.kripke.get_accessible_worlds(from_world):
                if from_world not in self.kripke.get_accessible_worlds(to_world):
                    return False
        return True
    
    def _check_transitive(self) -> bool:
        """Check if accessibility relation is transitive."""
        for w1 in self.kripke.worlds:
            for w2 in self.kripke.get_accessible_worlds(w1):
                for w3 in self.kripke.get_accessible_worlds(w2):
                    if w3 not in self.kripke.get_accessible_worlds(w1):
                        return False
        return True
    
    def _check_serial(self) -> bool:
        """Check if accessibility relation is serial (each world accesses at least one world)."""
        for world_id in self.kripke.worlds:
            if len(self.kripke.get_accessible_worlds(world_id)) == 0:
                return False
        return True
    
    def _get_expected_properties(self) -> List[str]:
        """Get expected properties for the logic type."""
        if self.kripke.logic_type == ModalLogicType.K:
            return []
        elif self.kripke.logic_type == ModalLogicType.T:
            return ["Reflexive"]
        elif self.kripke.logic_type == ModalLogicType.D:
            return ["Serial"]
        elif self.kripke.logic_type == ModalLogicType.S4:
            return ["Reflexive", "Transitive"]
        elif self.kripke.logic_type == ModalLogicType.S5:
            return ["Reflexive", "Symmetric", "Transitive"]
        return []
    
    def render_html_interactive(self, output_path: str) -> None:
        """
        Generate interactive HTML visualization with D3.js.
        
        Creates a standalone HTML file with:
        - Interactive graph visualization
        - Clickable worlds showing atom valuations
        - Hover tooltips for relations
        - Zoom and pan capabilities
        - Animated transitions
        
        Args:
            output_path: Path where HTML file should be saved
            
        Example:
            >>> visualizer.render_html_interactive("countermodel.html")
        """
        html_content = self.to_html_string()
        
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"Interactive HTML saved to {output_path}")
    
    def to_html_string(self) -> str:
        """
        Generate interactive HTML as a string.
        
        Returns:
            Complete HTML document as string
        """
        # Prepare data for D3.js
        nodes = []
        links = []
        
        for world_id in sorted(self.kripke.worlds):
            atoms = sorted(self.kripke.valuation.get(world_id, set()))
            is_initial = (world_id == self.kripke.initial_world)
            
            nodes.append({
                'id': f"w{world_id}",
                'label': f"w{world_id}",
                'atoms': atoms,
                'is_initial': is_initial,
                'world_id': world_id
            })
        
        for from_world in sorted(self.kripke.worlds):
            for to_world in sorted(self.kripke.get_accessible_worlds(from_world)):
                links.append({
                    'source': f"w{from_world}",
                    'target': f"w{to_world}",
                    'from': from_world,
                    'to': to_world
                })
        
        data = {
            'nodes': nodes,
            'links': links,
            'logic_type': self.kripke.logic_type.value,
            'num_worlds': len(self.kripke.worlds),
            'num_relations': len(links)
        }
        
        return self._generate_html_template(data)
    
    def _generate_html_template(self, data: dict) -> str:
        """Generate HTML template with embedded D3.js visualization."""
        json_data = json.dumps(data, indent=2)
        
        html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Kripke Structure - {html.escape(data['logic_type'])} Logic</title>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <style>
        body {{
            margin: 0;
            padding: 20px;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #f5f5f5;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            padding: 20px;
        }}
        
        h1 {{
            color: #333;
            margin-top: 0;
            border-bottom: 3px solid #4CAF50;
            padding-bottom: 10px;
        }}
        
        .info-panel {{
            background: #e8f5e9;
            padding: 15px;
            border-radius: 4px;
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        
        .info-item {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        
        .info-label {{
            font-weight: bold;
            color: #2e7d32;
        }}
        
        .info-value {{
            color: #555;
        }}
        
        #graph {{
            border: 1px solid #ddd;
            border-radius: 4px;
            background: #fafafa;
        }}
        
        .node {{
            cursor: pointer;
            transition: all 0.3s ease;
        }}
        
        .node:hover {{
            filter: brightness(1.1);
        }}
        
        .node circle {{
            stroke: #fff;
            stroke-width: 2px;
        }}
        
        .node.initial circle {{
            stroke: #ff9800;
            stroke-width: 4px;
        }}
        
        .node text {{
            font-size: 14px;
            font-weight: bold;
            text-anchor: middle;
            pointer-events: none;
            fill: #333;
        }}
        
        .link {{
            stroke: #999;
            stroke-width: 2px;
            fill: none;
            marker-end: url(#arrowhead);
        }}
        
        .link:hover {{
            stroke: #4CAF50;
            stroke-width: 3px;
        }}
        
        .tooltip {{
            position: absolute;
            background: rgba(0, 0, 0, 0.9);
            color: white;
            padding: 12px;
            border-radius: 4px;
            pointer-events: none;
            opacity: 0;
            transition: opacity 0.3s;
            font-size: 14px;
            max-width: 300px;
            z-index: 1000;
        }}
        
        .tooltip.visible {{
            opacity: 1;
        }}
        
        .tooltip h3 {{
            margin: 0 0 8px 0;
            font-size: 16px;
            border-bottom: 1px solid #666;
            padding-bottom: 4px;
        }}
        
        .tooltip .atoms {{
            margin-top: 8px;
        }}
        
        .tooltip .atom-badge {{
            display: inline-block;
            background: #4CAF50;
            padding: 2px 8px;
            border-radius: 3px;
            margin: 2px;
            font-size: 12px;
        }}
        
        .controls {{
            margin-top: 20px;
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }}
        
        .btn {{
            padding: 8px 16px;
            background: #4CAF50;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
            transition: background 0.3s;
        }}
        
        .btn:hover {{
            background: #45a049;
        }}
        
        .btn:active {{
            transform: scale(0.98);
        }}
        
        .legend {{
            margin-top: 20px;
            padding: 15px;
            background: #fff3e0;
            border-radius: 4px;
            border-left: 4px solid #ff9800;
        }}
        
        .legend h3 {{
            margin-top: 0;
            color: #e65100;
        }}
        
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin: 8px 0;
        }}
        
        .legend-symbol {{
            width: 30px;
            height: 30px;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Kripke Structure Visualization</h1>
        
        <div class="info-panel">
            <div class="info-item">
                <span class="info-label">Logic Type:</span>
                <span class="info-value" id="logic-type"></span>
            </div>
            <div class="info-item">
                <span class="info-label">Worlds:</span>
                <span class="info-value" id="num-worlds"></span>
            </div>
            <div class="info-item">
                <span class="info-label">Relations:</span>
                <span class="info-value" id="num-relations"></span>
            </div>
        </div>
        
        <svg id="graph" width="1200" height="600"></svg>
        
        <div class="controls">
            <button class="btn" onclick="resetZoom()">Reset View</button>
            <button class="btn" onclick="centerGraph()">Center Graph</button>
            <button class="btn" onclick="togglePhysics()">Toggle Physics</button>
        </div>
        
        <div class="legend">
            <h3>Legend</h3>
            <div class="legend-item">
                <div class="legend-symbol">
                    <svg width="30" height="30">
                        <circle cx="15" cy="15" r="12" fill="#4CAF50" stroke="#ff9800" stroke-width="3"/>
                    </svg>
                </div>
                <span>Initial world (orange border)</span>
            </div>
            <div class="legend-item">
                <div class="legend-symbol">
                    <svg width="30" height="30">
                        <circle cx="15" cy="15" r="12" fill="#2196F3" stroke="#fff" stroke-width="2"/>
                    </svg>
                </div>
                <span>Regular world</span>
            </div>
            <div class="legend-item">
                <div class="legend-symbol">
                    <svg width="30" height="30">
                        <line x1="5" y1="15" x2="25" y2="15" stroke="#999" stroke-width="2" marker-end="url(#arrowhead-legend)"/>
                        <defs>
                            <marker id="arrowhead-legend" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto">
                                <polygon points="0 0, 10 3, 0 6" fill="#999"/>
                            </marker>
                        </defs>
                    </svg>
                </div>
                <span>Accessibility relation</span>
            </div>
        </div>
        
        <div class="tooltip" id="tooltip"></div>
    </div>
    
    <script>
        // Data
        const data = {json_data};
        
        // Update info panel
        document.getElementById('logic-type').textContent = data.logic_type;
        document.getElementById('num-worlds').textContent = data.num_worlds;
        document.getElementById('num-relations').textContent = data.num_relations;
        
        // Set up SVG
        const svg = d3.select("#graph");
        const width = +svg.attr("width");
        const height = +svg.attr("height");
        
        // Create main group for zoom
        const g = svg.append("g");
        
        // Define arrowhead marker
        svg.append("defs").append("marker")
            .attr("id", "arrowhead")
            .attr("viewBox", "0 0 10 10")
            .attr("refX", 25)
            .attr("refY", 5)
            .attr("markerWidth", 6)
            .attr("markerHeight", 6)
            .attr("orient", "auto")
            .append("path")
            .attr("d", "M 0 0 L 10 5 L 0 10 z")
            .attr("fill", "#999");
        
        // Zoom behavior
        const zoom = d3.zoom()
            .scaleExtent([0.1, 4])
            .on("zoom", (event) => {{
                g.attr("transform", event.transform);
            }});
        
        svg.call(zoom);
        
        // Physics simulation
        let physicsEnabled = true;
        const simulation = d3.forceSimulation(data.nodes)
            .force("link", d3.forceLink(data.links).id(d => d.id).distance(150))
            .force("charge", d3.forceManyBody().strength(-500))
            .force("center", d3.forceCenter(width / 2, height / 2))
            .force("collision", d3.forceCollide().radius(40));
        
        // Create links
        const link = g.append("g")
            .selectAll("path")
            .data(data.links)
            .enter()
            .append("path")
            .attr("class", "link")
            .on("mouseover", function(event, d) {{
                showTooltip(event, `Accessibility: w${{d.from}} → w${{d.to}}`);
            }})
            .on("mouseout", hideTooltip);
        
        // Create nodes
        const node = g.append("g")
            .selectAll("g")
            .data(data.nodes)
            .enter()
            .append("g")
            .attr("class", d => d.is_initial ? "node initial" : "node")
            .call(d3.drag()
                .on("start", dragStarted)
                .on("drag", dragged)
                .on("end", dragEnded))
            .on("click", function(event, d) {{
                highlightNode(this, d);
            }})
            .on("mouseover", function(event, d) {{
                showNodeTooltip(event, d);
            }})
            .on("mouseout", hideTooltip);
        
        // Add circles to nodes
        node.append("circle")
            .attr("r", 20)
            .attr("fill", d => d.is_initial ? "#4CAF50" : "#2196F3");
        
        // Add text to nodes
        node.append("text")
            .text(d => d.label)
            .attr("dy", 5);
        
        // Simulation tick
        simulation.on("tick", () => {{
            link.attr("d", d => {{
                const dx = d.target.x - d.source.x;
                const dy = d.target.y - d.source.y;
                const dr = Math.sqrt(dx * dx + dy * dy);
                return `M${{d.source.x}},${{d.source.y}}A${{dr}},${{dr}} 0 0,1 ${{d.target.x}},${{d.target.y}}`;
            }});
            
            node.attr("transform", d => `translate(${{d.x}},${{d.y}})`);
        }});
        
        // Drag functions
        function dragStarted(event, d) {{
            if (!event.active && physicsEnabled) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
        }}
        
        function dragged(event, d) {{
            d.fx = event.x;
            d.fy = event.y;
        }}
        
        function dragEnded(event, d) {{
            if (!event.active && physicsEnabled) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
        }}
        
        // Tooltip functions
        const tooltip = d3.select("#tooltip");
        
        function showNodeTooltip(event, d) {{
            let content = `<h3>${{d.label}}</h3>`;
            if (d.is_initial) {{
                content += '<p style="color: #ff9800;">★ Initial World</p>';
            }}
            content += '<div class="atoms"><strong>Atoms:</strong><br>';
            if (d.atoms.length > 0) {{
                d.atoms.forEach(atom => {{
                    content += `<span class="atom-badge">${{atom}}</span>`;
                }});
            }} else {{
                content += '<span style="color: #999;">∅ (none)</span>';
            }}
            content += '</div>';
            
            tooltip.html(content)
                .style("left", (event.pageX + 10) + "px")
                .style("top", (event.pageY - 10) + "px")
                .classed("visible", true);
        }}
        
        function showTooltip(event, text) {{
            tooltip.html(text)
                .style("left", (event.pageX + 10) + "px")
                .style("top", (event.pageY - 10) + "px")
                .classed("visible", true);
        }}
        
        function hideTooltip() {{
            tooltip.classed("visible", false);
        }}
        
        function highlightNode(element, d) {{
            // Reset all nodes
            node.selectAll("circle")
                .transition()
                .duration(300)
                .attr("r", 20);
            
            // Highlight selected node
            d3.select(element).select("circle")
                .transition()
                .duration(300)
                .attr("r", 25);
        }}
        
        // Control functions
        function resetZoom() {{
            svg.transition().duration(750).call(
                zoom.transform,
                d3.zoomIdentity
            );
        }}
        
        function centerGraph() {{
            const bounds = g.node().getBBox();
            const fullWidth = width;
            const fullHeight = height;
            const midX = bounds.x + bounds.width / 2;
            const midY = bounds.y + bounds.height / 2;
            const scale = 0.8 / Math.max(bounds.width / fullWidth, bounds.height / fullHeight);
            const translate = [fullWidth / 2 - scale * midX, fullHeight / 2 - scale * midY];
            
            svg.transition().duration(750).call(
                zoom.transform,
                d3.zoomIdentity.translate(translate[0], translate[1]).scale(scale)
            );
        }}
        
        function togglePhysics() {{
            physicsEnabled = !physicsEnabled;
            if (physicsEnabled) {{
                simulation.alphaTarget(0.3).restart();
                setTimeout(() => simulation.alphaTarget(0), 1000);
            }} else {{
                simulation.stop();
            }}
        }}
        
        // Center graph on load
        setTimeout(centerGraph, 1000);
    </script>
</body>
</html>"""
        
        return html_template
    
    def render_accessibility_graph(self, output_path: str, format: str = 'svg') -> None:
        """
        Render accessibility graph with specialized layout.
        
        Creates a graph visualization highlighting:
        - Reflexive relations (self-loops)
        - Symmetric relations (bidirectional arrows)
        - Transitive relations (indirect paths)
        - Color coding for different modal logics
        
        Args:
            output_path: Path where graph file should be saved
            format: Output format - 'svg', 'png', 'pdf', or 'dot'
            
        Example:
            >>> visualizer.render_accessibility_graph("graph.svg", format="svg")
        """
        if format not in ['svg', 'png', 'pdf', 'dot']:
            raise ValueError(f"Unsupported format: {format}. Use 'svg', 'png', 'pdf', or 'dot'")
        
        dot_content = self._generate_accessibility_dot()
        
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        if format == 'dot':
            with open(output_file, 'w') as f:
                f.write(dot_content)
        else:
            # Write DOT content to temp file and use graphviz if available
            try:
                import subprocess
                import tempfile
                
                with tempfile.NamedTemporaryFile(mode='w', suffix='.dot', delete=False) as f:
                    f.write(dot_content)
                    temp_dot = f.name
                
                # Run graphviz
                result = subprocess.run(
                    ['dot', f'-T{format}', temp_dot, '-o', str(output_file)],
                    capture_output=True,
                    text=True
                )
                
                if result.returncode != 0:
                    logger.warning(f"Graphviz failed: {result.stderr}")
                    logger.info("Saving as DOT format instead")
                    with open(output_file.with_suffix('.dot'), 'w') as f:
                        f.write(dot_content)
                else:
                    logger.info(f"Accessibility graph saved to {output_path}")
                
                # Clean up temp file
                Path(temp_dot).unlink()
                
            except (ImportError, FileNotFoundError):
                logger.warning("Graphviz not available, saving as DOT format")
                with open(output_file.with_suffix('.dot'), 'w') as f:
                    f.write(dot_content)
    
    def _generate_accessibility_dot(self) -> str:
        """Generate DOT format for accessibility graph with property highlighting."""
        lines = []
        
        # Header with styling
        lines.append('digraph AccessibilityGraph {')
        lines.append(f'  label="Accessibility Graph ({self.kripke.logic_type.value} Logic)";')
        lines.append('  labelloc="t";')
        lines.append('  fontsize=16;')
        lines.append('  fontname="Arial";')
        lines.append('  rankdir=LR;')
        lines.append('  node [shape=circle, style=filled, fontname="Arial"];')
        lines.append('')
        
        # Color scheme based on logic type
        color_map = {
            ModalLogicType.K: '#2196F3',  # Blue
            ModalLogicType.T: '#4CAF50',  # Green
            ModalLogicType.D: '#FF9800',  # Orange
            ModalLogicType.S4: '#9C27B0', # Purple
            ModalLogicType.S5: '#F44336', # Red
        }
        node_color = color_map.get(self.kripke.logic_type, '#2196F3')
        
        # Nodes
        for world_id in sorted(self.kripke.worlds):
            if world_id == self.kripke.initial_world:
                lines.append(f'  w{world_id} [label="w{world_id}", fillcolor="{node_color}", '
                           f'penwidth=3, color="#FF9800"];')
            else:
                lines.append(f'  w{world_id} [label="w{world_id}", fillcolor="{node_color}"];')
        
        lines.append('')
        
        # Edges with property highlighting
        reflexive_edges = []
        symmetric_pairs = set()
        regular_edges = []
        
        for from_world in sorted(self.kripke.worlds):
            for to_world in sorted(self.kripke.get_accessible_worlds(from_world)):
                if from_world == to_world:
                    reflexive_edges.append((from_world, to_world))
                elif to_world in self.kripke.get_accessible_worlds(from_world) and \
                     from_world in self.kripke.get_accessible_worlds(to_world):
                    pair = tuple(sorted([from_world, to_world]))
                    if pair not in symmetric_pairs:
                        symmetric_pairs.add(pair)
                else:
                    regular_edges.append((from_world, to_world))
        
        # Reflexive edges (self-loops)
        if reflexive_edges:
            lines.append('  // Reflexive relations')
            for from_w, to_w in reflexive_edges:
                lines.append(f'  w{from_w} -> w{to_w} [color="#4CAF50", penwidth=2, label="reflexive"];')
            lines.append('')
        
        # Symmetric edges
        if symmetric_pairs:
            lines.append('  // Symmetric relations')
            for w1, w2 in sorted(symmetric_pairs):
                lines.append(f'  w{w1} -> w{w2} [color="#FF9800", penwidth=2, dir=both, label="symmetric"];')
            lines.append('')
        
        # Regular edges
        if regular_edges:
            lines.append('  // Regular accessibility relations')
            for from_w, to_w in regular_edges:
                lines.append(f'  w{from_w} -> w{to_w} [color="#999", penwidth=1.5];')
        
        lines.append('}')
        
        return '\n'.join(lines)


def create_visualizer(kripke_structure: KripkeStructure) -> CountermodelVisualizer:
    """
    Convenience function to create a visualizer.
    
    Args:
        kripke_structure: The Kripke structure to visualize
        
    Returns:
        CountermodelVisualizer instance
        
    Example:
        >>> from countermodels import KripkeStructure
        >>> kripke = KripkeStructure()
        >>> visualizer = create_visualizer(kripke)
    """
    return CountermodelVisualizer(kripke_structure)
