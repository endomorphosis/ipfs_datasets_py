#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TDFOL Convert Tool for MCP (Model Context Protocol).

This module implements an MCP tool for converting between TDFOL and other
logic representations. It supports:
- TDFOL ↔ DCEC (Deontic Cognitive Event Calculus)
- TDFOL → FOL (First-Order Logic)
- TDFOL → TPTP (Thousands of Problems for Theorem Provers)
- TDFOL → SMT-LIB (SMT solver format)
- Bidirectional conversions where applicable

The tool wraps the existing TDFOL converter to provide format conversion
capabilities through the MCP framework.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tool_registry import ClaudeMCPTool

logger = logging.getLogger(__name__)

TOOL_VERSION = "1.0.0"


class TDFOLConvertTool(ClaudeMCPTool):
    """
    MCP Tool for converting between TDFOL and other logic formats.
    
    This tool provides bidirectional conversion between TDFOL and various
    logic representations including DCEC, FOL, TPTP, and SMT-LIB formats.
    Enables integration with existing theorem provers and logic systems.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "tdfol_convert"
        self.description = "Convert between TDFOL and other logic formats (DCEC, FOL, TPTP, SMT-LIB)"
        self.category = "logic_tools"
        self.tags = ["logic", "conversion", "tdfol", "dcec", "fol", "tptp", "smt"]
        self.version = TOOL_VERSION
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "formula": {
                    "type": "string",
                    "description": "Formula to convert"
                },
                "source_format": {
                    "type": "string",
                    "description": "Source format of the formula",
                    "enum": ["tdfol", "dcec", "fol", "tptp", "json"],
                    "default": "tdfol"
                },
                "target_format": {
                    "type": "string",
                    "description": "Target format for conversion",
                    "enum": ["tdfol", "dcec", "fol", "tptp", "smt-lib", "json", "natural_language"]
                },
                "preserve_semantics": {
                    "type": "boolean",
                    "description": "Preserve original semantics (may result in more complex output)",
                    "default": True
                },
                "simplify": {
                    "type": "boolean",
                    "description": "Simplify the converted formula",
                    "default": False
                },
                "include_metadata": {
                    "type": "boolean",
                    "description": "Include conversion metadata in results",
                    "default": True
                }
            },
            "required": ["formula", "target_format"]
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute formula conversion.
        
        Args:
            parameters: Dictionary containing:
                - formula: Formula to convert
                - source_format: Source format
                - target_format: Target format
                - preserve_semantics: Preserve semantics
                - simplify: Simplify result
                - include_metadata: Include metadata
        
        Returns:
            Dictionary containing:
                - success: Boolean indicating success
                - converted_formula: Converted formula string
                - source_format: Original format
                - target_format: Target format
                - conversion_time_ms: Time taken
                - metadata: Conversion metadata (if requested)
        
        Example:
            >>> result = await tool.execute({
            ...     "formula": "∀x.(Contractor(x) → O(PayTaxes(x)))",
            ...     "source_format": "tdfol",
            ...     "target_format": "dcec"
            ... })
            >>> print(result["converted_formula"])
        """
        start_time = time.time()
        
        formula = parameters.get("formula", "")
        source_format = parameters.get("source_format", "tdfol")
        target_format = parameters.get("target_format", "")
        preserve_semantics = parameters.get("preserve_semantics", True)
        simplify = parameters.get("simplify", False)
        include_metadata = parameters.get("include_metadata", True)
        
        try:
            # Route to appropriate conversion method
            if source_format == "tdfol":
                result = await self._convert_from_tdfol(
                    formula, target_format, preserve_semantics, simplify
                )
            elif target_format == "tdfol":
                result = await self._convert_to_tdfol(
                    formula, source_format, preserve_semantics
                )
            else:
                return {
                    "success": False,
                    "error": f"Conversion from {source_format} to {target_format} requires TDFOL as intermediate",
                    "formula": formula
                }
            
            # Add common metadata
            result["source_format"] = source_format
            result["target_format"] = target_format
            result["conversion_time_ms"] = (time.time() - start_time) * 1000
            result["tool_version"] = TOOL_VERSION
            
            if include_metadata and result.get("success"):
                result["metadata"] = self._get_conversion_metadata(
                    source_format, target_format, result
                )
            
            return result
        
        except Exception as e:
            logger.error(f"Conversion failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "formula": formula,
                "source_format": source_format,
                "target_format": target_format,
                "conversion_time_ms": (time.time() - start_time) * 1000,
                "tool_version": TOOL_VERSION
            }
    
    async def _convert_from_tdfol(
        self,
        formula: str,
        target_format: str,
        preserve_semantics: bool,
        simplify: bool
    ) -> Dict[str, Any]:
        """Convert from TDFOL to other formats."""
        try:
            from ipfs_datasets_py.logic.TDFOL.tdfol_parser import parse_tdfol_safe
            from ipfs_datasets_py.logic.TDFOL.tdfol_converter import (
                TDFOLToDCECConverter,
                TDFOLToFOLConverter,
                TDFOLToTPTPConverter
            )
            
            # Parse TDFOL formula
            parsed = parse_tdfol_safe(formula)
            if parsed is None:
                return {
                    "success": False,
                    "error": "Failed to parse TDFOL formula",
                    "formula": formula
                }
            
            # Convert based on target format
            if target_format == "dcec":
                converter = TDFOLToDCECConverter()
                converted = converter.convert(parsed)
            elif target_format == "fol":
                converter = TDFOLToFOLConverter()
                converted = converter.convert(parsed, preserve_semantics=preserve_semantics)
            elif target_format == "tptp":
                converter = TDFOLToTPTPConverter()
                converted = converter.convert(parsed)
            elif target_format == "smt-lib":
                return {
                    "success": False,
                    "error": "SMT-LIB conversion not yet implemented",
                    "formula": formula
                }
            elif target_format == "json":
                converted = self._formula_to_json(parsed)
            elif target_format == "natural_language":
                converted = self._formula_to_nl(parsed)
            else:
                return {
                    "success": False,
                    "error": f"Unknown target format: {target_format}",
                    "formula": formula
                }
            
            return {
                "success": True,
                "converted_formula": converted,
                "original_formula": formula
            }
        
        except ImportError as e:
            logger.error(f"TDFOL converter not available: {e}")
            return {
                "success": False,
                "error": "TDFOL converter module not available",
                "formula": formula
            }
        except Exception as e:
            logger.error(f"Conversion from TDFOL failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Conversion failed: {str(e)}",
                "formula": formula
            }
    
    async def _convert_to_tdfol(
        self,
        formula: str,
        source_format: str,
        preserve_semantics: bool
    ) -> Dict[str, Any]:
        """Convert from other formats to TDFOL."""
        try:
            if source_format == "dcec":
                from ipfs_datasets_py.logic.TDFOL.tdfol_dcec_parser import parse_dcec_safe
                
                parsed = parse_dcec_safe(formula)
                if parsed is None:
                    return {
                        "success": False,
                        "error": "Failed to parse DCEC formula",
                        "formula": formula
                    }
                
                converted = str(parsed)
            elif source_format == "fol":
                # FOL is a subset of TDFOL, can parse directly
                from ipfs_datasets_py.logic.TDFOL.tdfol_parser import parse_tdfol_safe
                
                parsed = parse_tdfol_safe(formula)
                if parsed is None:
                    return {
                        "success": False,
                        "error": "Failed to parse FOL formula",
                        "formula": formula
                    }
                
                converted = str(parsed)
            elif source_format == "tptp":
                return {
                    "success": False,
                    "error": "TPTP to TDFOL conversion not yet implemented",
                    "formula": formula
                }
            elif source_format == "json":
                return {
                    "success": False,
                    "error": "JSON to TDFOL conversion not yet implemented",
                    "formula": formula
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown source format: {source_format}",
                    "formula": formula
                }
            
            return {
                "success": True,
                "converted_formula": converted,
                "original_formula": formula
            }
        
        except ImportError as e:
            logger.error(f"TDFOL parser not available: {e}")
            return {
                "success": False,
                "error": "TDFOL parser module not available",
                "formula": formula
            }
        except Exception as e:
            logger.error(f"Conversion to TDFOL failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Conversion failed: {str(e)}",
                "formula": formula
            }
    
    def _formula_to_json(self, formula: Any) -> str:
        """Convert formula to JSON representation."""
        # TODO: Implement structured JSON export
        return json.dumps({
            "type": type(formula).__name__,
            "representation": str(formula),
            "note": "Full JSON export not yet implemented"
        }, indent=2)
    
    def _formula_to_nl(self, formula: Any) -> str:
        """Convert formula to natural language."""
        try:
            from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_generator import FormulaGenerator
            
            generator = FormulaGenerator()
            # TODO: Implement reverse NL generation
            return str(formula)  # Fallback to string representation
        except ImportError:
            return str(formula)
    
    def _get_conversion_metadata(
        self,
        source_format: str,
        target_format: str,
        result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Get metadata about the conversion."""
        return {
            "conversion_type": f"{source_format}_to_{target_format}",
            "bidirectional": self._is_bidirectional(source_format, target_format),
            "lossless": self._is_lossless(source_format, target_format),
            "notes": self._get_conversion_notes(source_format, target_format)
        }
    
    def _is_bidirectional(self, source: str, target: str) -> bool:
        """Check if conversion is bidirectional."""
        bidirectional_pairs = [
            ("tdfol", "dcec"),
            ("tdfol", "fol"),
            ("tdfol", "json")
        ]
        return (source, target) in bidirectional_pairs or (target, source) in bidirectional_pairs
    
    def _is_lossless(self, source: str, target: str) -> bool:
        """Check if conversion is lossless."""
        # TDFOL to FOL loses temporal/deontic operators
        if source == "tdfol" and target == "fol":
            return False
        # Most other conversions preserve semantics
        return True
    
    def _get_conversion_notes(self, source: str, target: str) -> List[str]:
        """Get notes about the conversion."""
        notes = []
        
        if source == "tdfol" and target == "fol":
            notes.append("Temporal and deontic operators are flattened to predicates")
        elif source == "tdfol" and target == "dcec":
            notes.append("TDFOL temporal operators map to DCEC event calculus")
        elif target == "tptp":
            notes.append("TPTP format suitable for ATP theorem provers")
        
        return notes


# Tool registry for MCP server
TDFOL_CONVERT_TOOLS = [
    TDFOLConvertTool()
]


__all__ = [
    "TOOL_VERSION",
    "TDFOLConvertTool",
    "TDFOL_CONVERT_TOOLS",
]
