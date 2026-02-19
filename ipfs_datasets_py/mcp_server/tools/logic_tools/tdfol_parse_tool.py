#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TDFOL Parse Tool for MCP (Model Context Protocol).

This module implements an MCP tool for parsing formulas into TDFOL
(Temporal Deontic First-Order Logic) format. It supports:
- Symbolic formula parsing (mathematical notation)
- Natural language parsing (English text to logic)
- JSON/dictionary format parsing
- Input validation and error handling

The tool wraps the existing TDFOL parser and NL modules to provide
unified parsing capabilities through the MCP framework.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tool_registry import ClaudeMCPTool

logger = logging.getLogger(__name__)

TOOL_VERSION = "1.0.0"


class TDFOLParseTool(ClaudeMCPTool):
    """
    MCP Tool for parsing formulas into TDFOL format.
    
    This tool provides unified parsing of symbolic formulas, natural language text,
    and structured data into TDFOL (Temporal Deontic First-Order Logic) representations.
    Supports multiple input formats and provides detailed error messages.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "tdfol_parse"
        self.description = "Parse symbolic and natural language formulas into TDFOL (Temporal Deontic First-Order Logic)"
        self.category = "logic_tools"
        self.tags = ["logic", "parsing", "tdfol", "temporal", "deontic", "fol"]
        self.version = TOOL_VERSION
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "formula": {
                    "type": "string",
                    "description": "Formula to parse (symbolic notation or natural language)"
                },
                "format": {
                    "type": "string",
                    "description": "Input format type",
                    "enum": ["symbolic", "natural_language", "json", "auto"],
                    "default": "auto"
                },
                "validate": {
                    "type": "boolean",
                    "description": "Perform validation after parsing",
                    "default": True
                },
                "include_ast": {
                    "type": "boolean",
                    "description": "Include abstract syntax tree in results",
                    "default": False
                },
                "min_confidence": {
                    "type": "number",
                    "description": "Minimum confidence for NL parsing (0.0-1.0)",
                    "default": 0.5,
                    "minimum": 0.0,
                    "maximum": 1.0
                },
                "llm_enabled": {
                    "type": "boolean",
                    "description": "Enable LLM-enhanced parsing for natural language (slower, more accurate)",
                    "default": False
                },
                "llm_provider": {
                    "type": "string",
                    "description": "LLM provider to use (openai, gemini, claude, etc.). Default: auto",
                    "default": None
                },
                "force_llm": {
                    "type": "boolean",
                    "description": "Skip pattern matching and use LLM directly",
                    "default": False
                }
            },
            "required": ["formula"]
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute formula parsing.
        
        Args:
            parameters: Dictionary containing:
                - formula: Formula string to parse
                - format: Input format ("symbolic", "natural_language", "json", "auto")
                - validate: Whether to validate the result
                - include_ast: Include AST in output
                - min_confidence: Minimum confidence for NL parsing
        
        Returns:
            Dictionary containing:
                - success: Boolean indicating success
                - format_detected: Detected input format
                - parsed_formula: Parsed formula object/string
                - formula_type: Type of formula (predicate, temporal, deontic, etc.)
                - parse_time_ms: Time taken to parse
                - validation: Validation results (if requested)
                - ast: Abstract syntax tree (if requested)
                - metadata: Additional parsing metadata
        
        Example:
            >>> result = await tool.execute({
            ...     "formula": "∀x.(Contractor(x) → O(PayTaxes(x)))",
            ...     "format": "symbolic"
            ... })
            >>> print(result["success"])
            True
        """
        start_time = time.time()
        
        formula = parameters.get("formula", "")
        format_type = parameters.get("format", "auto")
        validate = parameters.get("validate", True)
        include_ast = parameters.get("include_ast", False)
        min_confidence = parameters.get("min_confidence", 0.5)
        llm_enabled = parameters.get("llm_enabled", False)
        llm_provider = parameters.get("llm_provider", None)
        force_llm = parameters.get("force_llm", False)
        
        # Auto-detect format if needed
        if format_type == "auto":
            format_type = self._detect_format(formula)
        
        try:
            # Parse based on format
            if format_type == "symbolic":
                result = await self._parse_symbolic(formula, validate, include_ast)
            elif format_type == "natural_language":
                result = await self._parse_natural_language(
                    formula, min_confidence, validate, llm_enabled, llm_provider, force_llm
                )
            elif format_type == "json":
                result = await self._parse_json(formula, validate)
            else:
                return {
                    "success": False,
                    "error": f"Unknown format: {format_type}",
                    "formula": formula
                }
            
            # Add common metadata
            result["format_detected"] = format_type
            result["parse_time_ms"] = (time.time() - start_time) * 1000
            result["tool_version"] = TOOL_VERSION
            
            return result
        
        except Exception as e:
            logger.error(f"Failed to parse formula: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "formula": formula,
                "format_detected": format_type,
                "parse_time_ms": (time.time() - start_time) * 1000,
                "tool_version": TOOL_VERSION
            }
    
    def _detect_format(self, formula: str) -> str:
        """
        Auto-detect the format of input formula.
        
        Args:
            formula: Input formula string
        
        Returns:
            Detected format: "symbolic", "natural_language", or "json"
        """
        formula = formula.strip()
        
        # Check for JSON
        if formula.startswith("{") or formula.startswith("["):
            return "json"
        
        # Check for symbolic logic operators
        symbolic_indicators = ["∀", "∃", "→", "∧", "∨", "¬", "□", "◊", "O(", "P(", "F("]
        if any(indicator in formula for indicator in symbolic_indicators):
            return "symbolic"
        
        # Default to natural language
        return "natural_language"
    
    async def _parse_symbolic(
        self,
        formula: str,
        validate: bool,
        include_ast: bool
    ) -> Dict[str, Any]:
        """Parse symbolic formula notation."""
        try:
            from ipfs_datasets_py.logic.TDFOL.tdfol_parser import parse_tdfol_safe
            from ipfs_datasets_py.logic.TDFOL.tdfol_core import Formula
            
            # Parse the formula
            parsed = parse_tdfol_safe(formula)
            
            if parsed is None:
                return {
                    "success": False,
                    "error": "Failed to parse symbolic formula",
                    "formula": formula
                }
            
            result = {
                "success": True,
                "parsed_formula": str(parsed),
                "formula_type": type(parsed).__name__,
                "formula": formula
            }
            
            # Add validation if requested
            if validate:
                result["validation"] = self._validate_formula(parsed)
            
            # Add AST if requested
            if include_ast:
                result["ast"] = self._extract_ast(parsed)
            
            return result
        
        except ImportError as e:
            logger.error(f"TDFOL parser not available: {e}")
            return {
                "success": False,
                "error": "TDFOL parser module not available",
                "formula": formula
            }
        except Exception as e:
            logger.error(f"Symbolic parsing failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Symbolic parsing failed: {str(e)}",
                "formula": formula
            }
    
    async def _parse_natural_language(
        self,
        text: str,
        min_confidence: float,
        validate: bool,
        llm_enabled: bool = False,
        llm_provider: Optional[str] = None,
        force_llm: bool = False
    ) -> Dict[str, Any]:
        """Parse natural language text to TDFOL."""
        # Try LLM-enhanced parsing if enabled
        if llm_enabled:
            try:
                from ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter import LLMNLConverter
                
                # Create converter with appropriate settings
                converter = LLMNLConverter(
                    confidence_threshold=min_confidence,
                    enable_llm=True,
                    default_provider=llm_provider
                )
                
                # Convert using hybrid approach
                llm_result = converter.convert(
                    text,
                    provider=llm_provider,
                    min_confidence=min_confidence,
                    force_llm=force_llm
                )
                
                if llm_result.success:
                    return {
                        "success": True,
                        "formula": llm_result.formula,
                        "confidence": llm_result.confidence,
                        "method": llm_result.method,
                        "llm_provider": llm_result.llm_provider,
                        "cache_hit": llm_result.cache_hit,
                        "text": text,
                        "metadata": llm_result.metadata
                    }
                else:
                    # LLM parsing failed, fallback to pattern-only
                    logger.warning(f"LLM parsing failed: {llm_result.errors}")
            
            except ImportError as e:
                logger.warning(f"LLM converter not available: {e}")
                # Fall through to pattern-only parsing
            except Exception as e:
                logger.error(f"LLM parsing error: {e}", exc_info=True)
                # Fall through to pattern-only parsing
        
        # Fallback to pattern-only parsing
        try:
            from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api import parse_natural_language
            
            # Parse natural language
            parse_result = parse_natural_language(text, min_confidence=min_confidence)
            
            if not parse_result.success:
                return {
                    "success": False,
                    "error": "Natural language parsing failed",
                    "errors": parse_result.errors,
                    "text": text
                }
            
            result = {
                "success": True,
                "num_formulas": parse_result.num_formulas,
                "formulas": [
                    {
                        "formula": f.formula_string,
                        "confidence": f.confidence,
                        "pattern": f.pattern_name,
                        "type": f.formula_type
                    }
                    for f in parse_result.formulas
                ],
                "confidence": parse_result.confidence,
                "method": "pattern",
                "text": text
            }
            
            # Add metadata
            if parse_result.metadata:
                result["metadata"] = {
                    "entities": parse_result.metadata.get("entities", []),
                    "patterns_matched": parse_result.metadata.get("patterns_matched", [])
                }
            
            return result
        
        except ImportError as e:
            logger.error(f"NL parser not available: {e}")
            return {
                "success": False,
                "error": "Natural language parser not available. Install with: pip install ipfs_datasets_py[knowledge_graphs]",
                "text": text
            }
        except Exception as e:
            logger.error(f"NL parsing failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Natural language parsing failed: {str(e)}",
                "text": text
            }
    
    async def _parse_json(
        self,
        json_str: str,
        validate: bool
    ) -> Dict[str, Any]:
        """Parse JSON/dictionary format."""
        try:
            # Parse JSON string
            data = json.loads(json_str) if isinstance(json_str, str) else json_str
            
            # TODO: Implement JSON to TDFOL conversion
            # This would convert structured JSON representations to TDFOL formulas
            
            return {
                "success": False,
                "error": "JSON format parsing not yet implemented",
                "data": data
            }
        
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "error": f"Invalid JSON: {str(e)}",
                "json": json_str
            }
        except Exception as e:
            logger.error(f"JSON parsing failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"JSON parsing failed: {str(e)}",
                "json": json_str
            }
    
    def _validate_formula(self, formula: Any) -> Dict[str, Any]:
        """
        Validate a parsed formula.
        
        Args:
            formula: Parsed TDFOL formula object
        
        Returns:
            Validation results with is_valid flag and any errors
        """
        # Basic validation - check if formula is valid
        validation = {
            "is_valid": True,
            "errors": [],
            "warnings": []
        }
        
        # TODO: Add more comprehensive validation logic
        # - Check variable scoping
        # - Check type consistency
        # - Check operator compatibility
        
        return validation
    
    def _extract_ast(self, formula: Any) -> Dict[str, Any]:
        """
        Extract abstract syntax tree from formula.
        
        Args:
            formula: Parsed TDFOL formula object
        
        Returns:
            AST representation as nested dictionary
        """
        # TODO: Implement AST extraction
        return {
            "type": type(formula).__name__,
            "note": "AST extraction not fully implemented"
        }


# Tool registry for MCP server
TDFOL_PARSE_TOOLS = [
    TDFOLParseTool()
]


__all__ = [
    "TOOL_VERSION",
    "TDFOLParseTool",
    "TDFOL_PARSE_TOOLS",
]
