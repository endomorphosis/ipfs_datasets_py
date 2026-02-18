#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TDFOL Prove Tool for MCP (Model Context Protocol).

This module implements an MCP tool for theorem proving with TDFOL
(Temporal Deontic First-Order Logic). It supports:
- Single formula proving
- Batch proving for multiple formulas
- Strategy selection (forward, backward, modal tableaux)
- Proof result caching
- P2P distributed proving (foundation for Week 2)

The tool wraps the existing TDFOL prover to provide theorem proving
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


class TDFOLProveTool(ClaudeMCPTool):
    """
    MCP Tool for theorem proving with TDFOL.
    
    This tool provides theorem proving capabilities for TDFOL formulas using
    various proving strategies including forward chaining, backward chaining,
    and modal tableaux. Supports batch proving and proof caching.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "tdfol_prove"
        self.description = "Prove TDFOL formulas using various theorem proving strategies"
        self.category = "logic_tools"
        self.tags = ["logic", "proving", "theorem", "tdfol", "temporal", "deontic"]
        self.version = TOOL_VERSION
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "formula": {
                    "type": "string",
                    "description": "Formula to prove (TDFOL notation)"
                },
                "axioms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of axiom formulas to use in proof",
                    "default": []
                },
                "strategy": {
                    "type": "string",
                    "description": "Proving strategy to use",
                    "enum": ["auto", "forward", "backward", "modal_tableaux", "hybrid"],
                    "default": "auto"
                },
                "timeout_ms": {
                    "type": "integer",
                    "description": "Timeout in milliseconds",
                    "default": 5000,
                    "minimum": 100,
                    "maximum": 60000
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum proof search depth",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 100
                },
                "use_cache": {
                    "type": "boolean",
                    "description": "Use proof result caching",
                    "default": True
                },
                "include_proof_steps": {
                    "type": "boolean",
                    "description": "Include detailed proof steps in results",
                    "default": True
                },
                "distributed": {
                    "type": "boolean",
                    "description": "Enable P2P distributed proving (experimental)",
                    "default": False
                }
            },
            "required": ["formula"]
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute theorem proving.
        
        Args:
            parameters: Dictionary containing:
                - formula: Formula to prove
                - axioms: List of axiom formulas
                - strategy: Proving strategy
                - timeout_ms: Timeout in milliseconds
                - max_depth: Maximum proof depth
                - use_cache: Enable caching
                - include_proof_steps: Include proof steps
                - distributed: Enable P2P proving
        
        Returns:
            Dictionary containing:
                - success: Boolean indicating if proof completed
                - proved: Boolean indicating if formula was proved
                - status: Proof status (proved, disproved, unknown, timeout)
                - formula: Formula that was proved
                - method: Proving method used
                - proof_steps: List of proof steps (if requested)
                - time_ms: Time taken to prove
                - from_cache: Whether result was from cache
        
        Example:
            >>> result = await tool.execute({
            ...     "formula": "∀x.(P(x) → Q(x))",
            ...     "axioms": ["∀x.P(x)"],
            ...     "strategy": "forward"
            ... })
            >>> print(result["proved"])
            True
        """
        start_time = time.time()
        
        formula = parameters.get("formula", "")
        axioms = parameters.get("axioms", [])
        strategy = parameters.get("strategy", "auto")
        timeout_ms = parameters.get("timeout_ms", 5000)
        max_depth = parameters.get("max_depth", 10)
        use_cache = parameters.get("use_cache", True)
        include_proof_steps = parameters.get("include_proof_steps", True)
        distributed = parameters.get("distributed", False)
        
        try:
            # P2P distributed proving (Week 2 implementation)
            if distributed:
                return await self._prove_distributed(
                    formula, axioms, strategy, timeout_ms, max_depth
                )
            
            # Standard local proving
            return await self._prove_local(
                formula, axioms, strategy, timeout_ms, max_depth,
                use_cache, include_proof_steps, start_time
            )
        
        except Exception as e:
            logger.error(f"Failed to prove formula: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "formula": formula,
                "time_ms": (time.time() - start_time) * 1000,
                "tool_version": TOOL_VERSION
            }
    
    async def _prove_local(
        self,
        formula: str,
        axioms: List[str],
        strategy: str,
        timeout_ms: int,
        max_depth: int,
        use_cache: bool,
        include_proof_steps: bool,
        start_time: float
    ) -> Dict[str, Any]:
        """Prove formula locally using TDFOL prover."""
        try:
            from ipfs_datasets_py.logic.TDFOL.tdfol_parser import parse_tdfol_safe
            from ipfs_datasets_py.logic.TDFOL.tdfol_prover import TDFOLProver
            from ipfs_datasets_py.logic.TDFOL.tdfol_core import TDFOLKnowledgeBase
            
            # Parse formula
            parsed_formula = parse_tdfol_safe(formula)
            if parsed_formula is None:
                return {
                    "success": False,
                    "error": "Failed to parse formula",
                    "formula": formula,
                    "time_ms": (time.time() - start_time) * 1000
                }
            
            # Create knowledge base with axioms
            kb = TDFOLKnowledgeBase()
            for axiom_str in axioms:
                axiom = parse_tdfol_safe(axiom_str)
                if axiom:
                    kb.add_formula(axiom)
            
            # Create prover
            prover = TDFOLProver(kb)
            
            # Prove formula
            proof_result = prover.prove(
                parsed_formula,
                strategy=strategy if strategy != "auto" else None,
                timeout_ms=timeout_ms,
                max_depth=max_depth,
                use_cache=use_cache
            )
            
            result = {
                "success": True,
                "proved": proof_result.is_proved(),
                "status": proof_result.status.value,
                "formula": formula,
                "method": proof_result.method,
                "time_ms": proof_result.time_ms,
                "from_cache": getattr(proof_result, "from_cache", False),
                "tool_version": TOOL_VERSION
            }
            
            # Add proof steps if requested
            if include_proof_steps and proof_result.proof_steps:
                result["proof_steps"] = [
                    {
                        "formula": str(step.formula),
                        "justification": step.justification,
                        "rule_name": step.rule_name
                    }
                    for step in proof_result.proof_steps
                ]
                result["num_steps"] = len(proof_result.proof_steps)
            
            return result
        
        except ImportError as e:
            logger.error(f"TDFOL prover not available: {e}")
            return {
                "success": False,
                "error": "TDFOL prover module not available",
                "formula": formula,
                "time_ms": (time.time() - start_time) * 1000
            }
        except Exception as e:
            logger.error(f"Proving failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Proving failed: {str(e)}",
                "formula": formula,
                "time_ms": (time.time() - start_time) * 1000
            }
    
    async def _prove_distributed(
        self,
        formula: str,
        axioms: List[str],
        strategy: str,
        timeout_ms: int,
        max_depth: int
    ) -> Dict[str, Any]:
        """
        Prove formula using P2P distributed proving.
        
        This is a placeholder for Week 2 implementation.
        Will distribute proof search across multiple P2P nodes.
        """
        # TODO: Implement in Week 2
        return {
            "success": False,
            "error": "P2P distributed proving not yet implemented (Week 2)",
            "formula": formula,
            "note": "This feature will be available in Phase 13 Week 2"
        }


class TDFOLBatchProveTool(ClaudeMCPTool):
    """
    MCP Tool for batch proving multiple TDFOL formulas.
    
    This tool allows proving multiple formulas in a single call,
    with support for parallel processing and aggregated results.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "tdfol_batch_prove"
        self.description = "Prove multiple TDFOL formulas in batch with optional parallelization"
        self.category = "logic_tools"
        self.tags = ["logic", "proving", "batch", "tdfol", "parallel"]
        self.version = TOOL_VERSION
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "formulas": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of formulas to prove"
                },
                "shared_axioms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Axioms to use for all proofs",
                    "default": []
                },
                "strategy": {
                    "type": "string",
                    "description": "Proving strategy",
                    "enum": ["auto", "forward", "backward", "modal_tableaux"],
                    "default": "auto"
                },
                "timeout_per_formula_ms": {
                    "type": "integer",
                    "description": "Timeout per formula in milliseconds",
                    "default": 5000,
                    "minimum": 100,
                    "maximum": 60000
                },
                "parallel": {
                    "type": "boolean",
                    "description": "Process formulas in parallel",
                    "default": False
                },
                "stop_on_first_failure": {
                    "type": "boolean",
                    "description": "Stop processing if any proof fails",
                    "default": False
                }
            },
            "required": ["formulas"]
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute batch theorem proving.
        
        Args:
            parameters: Dictionary containing:
                - formulas: List of formulas to prove
                - shared_axioms: Axioms for all proofs
                - strategy: Proving strategy
                - timeout_per_formula_ms: Timeout per formula
                - parallel: Enable parallel processing
                - stop_on_first_failure: Stop on failure
        
        Returns:
            Dictionary containing:
                - success: Overall success
                - results: List of individual proof results
                - total_proved: Number of formulas proved
                - total_failed: Number that failed
                - total_time_ms: Total processing time
        """
        start_time = time.time()
        
        formulas = parameters.get("formulas", [])
        shared_axioms = parameters.get("shared_axioms", [])
        strategy = parameters.get("strategy", "auto")
        timeout_per_formula = parameters.get("timeout_per_formula_ms", 5000)
        parallel = parameters.get("parallel", False)
        stop_on_first_failure = parameters.get("stop_on_first_failure", False)
        
        if not formulas:
            return {
                "success": False,
                "error": "No formulas provided",
                "tool_version": TOOL_VERSION
            }
        
        try:
            # Create prove tool instance
            prove_tool = TDFOLProveTool()
            
            results = []
            total_proved = 0
            total_failed = 0
            
            # Process formulas (sequential for now, parallel in Week 2)
            for formula in formulas:
                result = await prove_tool.execute({
                    "formula": formula,
                    "axioms": shared_axioms,
                    "strategy": strategy,
                    "timeout_ms": timeout_per_formula,
                    "include_proof_steps": False  # Save space in batch mode
                })
                
                results.append(result)
                
                if result.get("proved", False):
                    total_proved += 1
                else:
                    total_failed += 1
                    if stop_on_first_failure:
                        break
            
            return {
                "success": True,
                "results": results,
                "total_formulas": len(formulas),
                "total_proved": total_proved,
                "total_failed": total_failed,
                "total_time_ms": (time.time() - start_time) * 1000,
                "tool_version": TOOL_VERSION
            }
        
        except Exception as e:
            logger.error(f"Batch proving failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "total_time_ms": (time.time() - start_time) * 1000,
                "tool_version": TOOL_VERSION
            }


# Tool registry for MCP server
TDFOL_PROVE_TOOLS = [
    TDFOLProveTool(),
    TDFOLBatchProveTool()
]


__all__ = [
    "TOOL_VERSION",
    "TDFOLProveTool",
    "TDFOLBatchProveTool",
    "TDFOL_PROVE_TOOLS",
]
