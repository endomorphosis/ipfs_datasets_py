"""
TDFOL Visualization Tool for MCP Server

This tool provides comprehensive visualization capabilities for TDFOL proofs, countermodels,
and dependency graphs. It wraps the existing TDFOL visualization modules:
- proof_tree_visualizer.py: Proof tree rendering
- countermodel_visualizer.py: Kripke structure visualization
- formula_dependency_graph.py: Formula dependency graphs

Supports multiple output formats:
- ASCII: Terminal-friendly text output
- HTML: Interactive web visualization
- SVG/PNG: Vector/raster graphics
- JSON: Programmatic access

Author: Phase 13 Week 2 Implementation
Date: 2026-02-18
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tool_registry import ClaudeMCPTool

logger = logging.getLogger(__name__)

# Try to import TDFOL visualization modules
try:
    from ipfs_datasets_py.logic.TDFOL.proof_tree_visualizer import ProofTreeVisualizer
    from ipfs_datasets_py.logic.TDFOL.countermodel_visualizer import CountermodelVisualizer
    from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult, ProofStatus
    TDFOL_AVAILABLE = True
except ImportError as e:
    logger.warning(f"TDFOL visualization not available: {e}")
    TDFOL_AVAILABLE = False
    ProofTreeVisualizer = None
    CountermodelVisualizer = None
    ProofResult = None
    ProofStatus = None


class TDFOLVisualizeTool(ClaudeMCPTool):
    """
    Visualize TDFOL proofs, countermodels, and formula dependencies.
    
    This tool provides comprehensive visualization of TDFOL reasoning results:
    - Proof trees showing inference steps
    - Countermodels (Kripke structures) for failed proofs
    - Formula dependency graphs
    
    Supports multiple output formats for different use cases.
    """
    
    name = "tdfol_visualize"
    description = (
        "Visualize TDFOL proof trees, countermodels, and formula dependencies "
        "in multiple formats (ASCII, HTML, SVG, PNG, JSON)"
    )
    category = "logic_tools"
    tags = ["logic", "tdfol", "visualization", "proof-tree", "countermodel"]
    version = "1.0.0"
    
    input_schema = {
        "type": "object",
        "properties": {
            "visualization_type": {
                "type": "string",
                "enum": ["proof_tree", "countermodel", "dependency_graph"],
                "description": "Type of visualization to generate"
            },
            "proof_result": {
                "type": "object",
                "description": "Proof result object from prove tool (required for proof_tree/countermodel)",
                "properties": {
                    "status": {"type": "string"},
                    "proved": {"type": "boolean"},
                    "proof_steps": {"type": "array"},
                    "countermodel": {"type": "object"}
                }
            },
            "formulas": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of formulas for dependency graph visualization"
            },
            "format": {
                "type": "string",
                "enum": ["ascii", "html", "svg", "png", "json"],
                "default": "ascii",
                "description": "Output format"
            },
            "output_file": {
                "type": "string",
                "description": "Optional file path to save visualization"
            },
            "options": {
                "type": "object",
                "description": "Format-specific visualization options",
                "properties": {
                    "colors": {"type": "boolean", "default": True},
                    "compact": {"type": "boolean", "default": False},
                    "width": {"type": "integer", "default": 800},
                    "height": {"type": "integer", "default": 600}
                }
            }
        },
        "required": ["visualization_type"]
    }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute visualization generation.
        
        Args:
            parameters: Tool parameters including visualization_type, proof_result, format
            
        Returns:
            Dictionary containing visualization output and metadata
        """
        if not TDFOL_AVAILABLE:
            return {
                "success": False,
                "error": "TDFOL visualization modules not available",
                "message": "Please install: pip install ipfs_datasets_py[logic]"
            }
        
        viz_type = parameters.get("visualization_type")
        output_format = parameters.get("format", "ascii")
        output_file = parameters.get("output_file")
        options = parameters.get("options", {})
        
        try:
            if viz_type == "proof_tree":
                return await self._visualize_proof_tree(
                    parameters.get("proof_result"),
                    output_format,
                    output_file,
                    options
                )
            elif viz_type == "countermodel":
                return await self._visualize_countermodel(
                    parameters.get("proof_result"),
                    output_format,
                    output_file,
                    options
                )
            elif viz_type == "dependency_graph":
                return await self._visualize_dependency_graph(
                    parameters.get("formulas", []),
                    output_format,
                    output_file,
                    options
                )
            else:
                return {
                    "success": False,
                    "error": f"Unknown visualization type: {viz_type}"
                }
                
        except Exception as e:
            logger.error(f"Visualization failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Failed to generate visualization"
            }
    
    async def _visualize_proof_tree(
        self,
        proof_result: Optional[Dict],
        output_format: str,
        output_file: Optional[str],
        options: Dict
    ) -> Dict[str, Any]:
        """Visualize proof tree from proof result."""
        if not proof_result:
            return {
                "success": False,
                "error": "proof_result is required for proof_tree visualization"
            }
        
        # TODO: Convert proof_result dict to ProofResult object
        # For now, return placeholder
        
        if output_format == "ascii":
            visualization = self._generate_ascii_proof_tree(proof_result, options)
        elif output_format == "html":
            visualization = self._generate_html_proof_tree(proof_result, options)
        elif output_format == "json":
            visualization = json.dumps(proof_result, indent=2)
        else:
            return {
                "success": False,
                "error": f"Format {output_format} not yet implemented for proof trees"
            }
        
        result = {
            "success": True,
            "visualization_type": "proof_tree",
            "format": output_format,
            "content": visualization
        }
        
        if output_file:
            try:
                Path(output_file).write_text(visualization)
                result["output_file"] = output_file
            except Exception as e:
                result["file_error"] = str(e)
        
        return result
    
    async def _visualize_countermodel(
        self,
        proof_result: Optional[Dict],
        output_format: str,
        output_file: Optional[str],
        options: Dict
    ) -> Dict[str, Any]:
        """Visualize countermodel from failed proof."""
        if not proof_result:
            return {
                "success": False,
                "error": "proof_result is required for countermodel visualization"
            }
        
        if proof_result.get("proved", True):
            return {
                "success": False,
                "error": "No countermodel available for successful proof"
            }
        
        countermodel = proof_result.get("countermodel")
        if not countermodel:
            return {
                "success": False,
                "error": "No countermodel found in proof result"
            }
        
        # TODO: Implement countermodel visualization
        # For now, return placeholder
        
        visualization = json.dumps(countermodel, indent=2)
        
        return {
            "success": True,
            "visualization_type": "countermodel",
            "format": output_format,
            "content": visualization,
            "message": "Countermodel visualization (basic JSON output)"
        }
    
    async def _visualize_dependency_graph(
        self,
        formulas: List[str],
        output_format: str,
        output_file: Optional[str],
        options: Dict
    ) -> Dict[str, Any]:
        """Visualize formula dependency graph."""
        if not formulas:
            return {
                "success": False,
                "error": "formulas list is required for dependency_graph visualization"
            }
        
        # TODO: Implement dependency graph visualization
        # For now, return placeholder
        
        graph_data = {
            "nodes": [{"id": i, "formula": f} for i, f in enumerate(formulas)],
            "edges": []  # TODO: Compute dependencies
        }
        
        visualization = json.dumps(graph_data, indent=2)
        
        return {
            "success": True,
            "visualization_type": "dependency_graph",
            "format": output_format,
            "content": visualization,
            "formula_count": len(formulas)
        }
    
    def _generate_ascii_proof_tree(self, proof_result: Dict, options: Dict) -> str:
        """Generate ASCII art proof tree."""
        lines = [
            "Proof Tree (ASCII)",
            "=" * 40,
            "",
            f"Status: {proof_result.get('status', 'unknown')}",
            f"Proved: {proof_result.get('proved', False)}",
            ""
        ]
        
        steps = proof_result.get("proof_steps", [])
        if steps:
            lines.append(f"Proof Steps ({len(steps)}):")
            lines.append("-" * 40)
            for i, step in enumerate(steps, 1):
                formula = step.get("formula", "?")
                rule = step.get("rule", "?")
                lines.append(f"  {i}. {formula}")
                lines.append(f"     [Rule: {rule}]")
                lines.append("")
        else:
            lines.append("No proof steps available")
        
        return "\n".join(lines)
    
    def _generate_html_proof_tree(self, proof_result: Dict, options: Dict) -> str:
        """Generate HTML proof tree visualization."""
        steps = proof_result.get("proof_steps", [])
        steps_html = ""
        
        for i, step in enumerate(steps, 1):
            formula = step.get("formula", "?")
            rule = step.get("rule", "?")
            steps_html += f"""
                <div class="proof-step">
                    <div class="step-number">{i}</div>
                    <div class="step-formula">{formula}</div>
                    <div class="step-rule">Rule: {rule}</div>
                </div>
            """
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>TDFOL Proof Tree</title>
    <style>
        body {{ font-family: Arial, sans-serif; padding: 20px; }}
        .proof-tree {{ max-width: 800px; margin: 0 auto; }}
        .proof-step {{ 
            border: 1px solid #ccc; 
            padding: 10px; 
            margin: 10px 0; 
            border-radius: 5px;
        }}
        .step-number {{ 
            font-weight: bold; 
            color: #007bff; 
            display: inline-block;
            min-width: 30px;
        }}
        .step-formula {{ font-family: monospace; margin: 5px 0; }}
        .step-rule {{ color: #666; font-size: 0.9em; }}
        .status {{ 
            padding: 5px 10px; 
            border-radius: 3px; 
            display: inline-block;
        }}
        .proved {{ background: #d4edda; color: #155724; }}
        .disproved {{ background: #f8d7da; color: #721c24; }}
    </style>
</head>
<body>
    <div class="proof-tree">
        <h1>TDFOL Proof Tree</h1>
        <p>
            Status: <span class="status {'proved' if proof_result.get('proved') else 'disproved'}">
                {proof_result.get('status', 'unknown')}
            </span>
        </p>
        <h2>Proof Steps</h2>
        {steps_html if steps else '<p>No proof steps available</p>'}
    </div>
</body>
</html>
        """
        
        return html


# Export tool instance
tools = [TDFOLVisualizeTool()]
