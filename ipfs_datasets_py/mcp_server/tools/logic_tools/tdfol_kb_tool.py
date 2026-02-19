"""
TDFOL Knowledge Base Management Tool for MCP Server

This tool provides knowledge base management for TDFOL, wrapping the TDFOLKnowledgeBase
class with MCP server integration. Supports:
- Adding/removing axioms and theorems
- Querying KB contents
- Exporting KB state
- IPFS-backed persistence (optional, requires P2P layer)

Author: Phase 13 Week 2 Implementation
Date: 2026-02-18
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tool_registry import ClaudeMCPTool

logger = logging.getLogger(__name__)

# Try to import TDFOL modules
try:
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import TDFOLKnowledgeBase
    from ipfs_datasets_py.logic.TDFOL.tdfol_parser import parse_tdfol
    TDFOL_AVAILABLE = True
except ImportError as e:
    logger.warning(f"TDFOL modules not available: {e}")
    TDFOL_AVAILABLE = False
    TDFOLKnowledgeBase = None
    parse_tdfol = None


class TDFOLKBTool(ClaudeMCPTool):
    """
    Manage TDFOL knowledge bases - add axioms, theorems, and query contents.
    
    This tool provides comprehensive knowledge base management:
    - Create and initialize knowledge bases
    - Add axioms (assumed true statements)
    - Add theorems (statements with proofs)
    - Query KB contents and statistics
    - Export/import KB state
    
    Future: IPFS-backed persistence for distributed KB management
    """
    
    name = "tdfol_kb"
    description = (
        "Manage TDFOL knowledge bases - add/remove axioms and theorems, "
        "query KB contents, export/import KB state"
    )
    category = "logic_tools"
    tags = ["logic", "tdfol", "knowledge-base", "axioms", "theorems"]
    version = "1.0.0"
    
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "create", "add_axiom", "add_theorem", "remove_axiom",
                    "list_axioms", "list_theorems", "query", "export", "import",
                    "stats", "clear"
                ],
                "description": "KB management action to perform"
            },
            "kb_id": {
                "type": "string",
                "description": "Knowledge base identifier (optional, uses default if not provided)"
            },
            "formula": {
                "type": "string",
                "description": "Formula to add/remove/query"
            },
            "formulas": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Multiple formulas for batch operations"
            },
            "kb_data": {
                "type": "object",
                "description": "KB state data for import action"
            },
            "name": {
                "type": "string",
                "description": "Name for axiom/theorem"
            },
            "description": {
                "type": "string",
                "description": "Description for axiom/theorem"
            }
        },
        "required": ["action"]
    }
    
    # Class-level KB storage (in-memory for now, could be persisted)
    _knowledge_bases: Dict[str, Any] = {}
    _default_kb_id = "default"
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute KB management action.
        
        Args:
            parameters: Tool parameters including action and KB details
            
        Returns:
            Dictionary containing action result and KB state
        """
        if not TDFOL_AVAILABLE:
            return {
                "success": False,
                "error": "TDFOL modules not available",
                "message": "Please install: pip install ipfs_datasets_py[logic]"
            }
        
        action = parameters.get("action")
        kb_id = parameters.get("kb_id", self._default_kb_id)
        
        try:
            if action == "create":
                return await self._create_kb(kb_id)
            elif action == "add_axiom":
                return await self._add_axiom(
                    kb_id,
                    parameters.get("formula"),
                    parameters.get("name"),
                    parameters.get("description")
                )
            elif action == "add_theorem":
                return await self._add_theorem(
                    kb_id,
                    parameters.get("formula"),
                    parameters.get("name"),
                    parameters.get("description")
                )
            elif action == "remove_axiom":
                return await self._remove_axiom(kb_id, parameters.get("formula"))
            elif action == "list_axioms":
                return await self._list_axioms(kb_id)
            elif action == "list_theorems":
                return await self._list_theorems(kb_id)
            elif action == "query":
                return await self._query_kb(kb_id, parameters.get("formula"))
            elif action == "export":
                return await self._export_kb(kb_id)
            elif action == "import":
                return await self._import_kb(kb_id, parameters.get("kb_data"))
            elif action == "stats":
                return await self._get_stats(kb_id)
            elif action == "clear":
                return await self._clear_kb(kb_id)
            else:
                return {
                    "success": False,
                    "error": f"Unknown action: {action}"
                }
                
        except Exception as e:
            logger.error(f"KB operation failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to execute {action}"
            }
    
    async def _create_kb(self, kb_id: str) -> Dict[str, Any]:
        """Create a new knowledge base."""
        if kb_id in self._knowledge_bases:
            return {
                "success": False,
                "error": f"KB '{kb_id}' already exists",
                "message": "Use a different kb_id or clear existing KB"
            }
        
        self._knowledge_bases[kb_id] = TDFOLKnowledgeBase()
        
        return {
            "success": True,
            "action": "create",
            "kb_id": kb_id,
            "message": f"Created knowledge base '{kb_id}'"
        }
    
    async def _add_axiom(
        self,
        kb_id: str,
        formula: Optional[str],
        name: Optional[str],
        description: Optional[str]
    ) -> Dict[str, Any]:
        """Add axiom to knowledge base."""
        if not formula:
            return {"success": False, "error": "formula is required"}
        
        kb = self._get_or_create_kb(kb_id)
        
        try:
            # Parse formula
            parsed = parse_tdfol(formula)
            
            # Add to KB
            kb.add_axiom(parsed)
            
            return {
                "success": True,
                "action": "add_axiom",
                "kb_id": kb_id,
                "formula": formula,
                "name": name,
                "description": description,
                "axiom_count": len(kb.axioms)
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to add axiom: {e}",
                "formula": formula
            }
    
    async def _add_theorem(
        self,
        kb_id: str,
        formula: Optional[str],
        name: Optional[str],
        description: Optional[str]
    ) -> Dict[str, Any]:
        """Add theorem to knowledge base."""
        if not formula:
            return {"success": False, "error": "formula is required"}
        
        kb = self._get_or_create_kb(kb_id)
        
        try:
            # Parse formula
            parsed = parse_tdfol(formula)
            
            # Add to KB theorems
            if not hasattr(kb, 'theorems'):
                kb.theorems = []
            
            kb.theorems.append({
                "formula": parsed,
                "name": name,
                "description": description
            })
            
            return {
                "success": True,
                "action": "add_theorem",
                "kb_id": kb_id,
                "formula": formula,
                "name": name,
                "description": description,
                "theorem_count": len(kb.theorems)
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to add theorem: {e}",
                "formula": formula
            }
    
    async def _remove_axiom(
        self,
        kb_id: str,
        formula: Optional[str]
    ) -> Dict[str, Any]:
        """Remove axiom from knowledge base."""
        if not formula:
            return {"success": False, "error": "formula is required"}
        
        kb = self._get_or_create_kb(kb_id)
        
        try:
            # Parse formula
            parsed = parse_tdfol(formula)
            
            # Find and remove from axioms
            initial_count = len(kb.axioms)
            kb.axioms = [ax for ax in kb.axioms if ax.to_string() != parsed.to_string()]
            removed_count = initial_count - len(kb.axioms)
            
            return {
                "success": True,
                "action": "remove_axiom",
                "kb_id": kb_id,
                "formula": formula,
                "removed_count": removed_count,
                "axiom_count": len(kb.axioms)
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to remove axiom: {e}",
                "formula": formula
            }
    
    async def _list_axioms(self, kb_id: str) -> Dict[str, Any]:
        """List all axioms in KB."""
        kb = self._get_or_create_kb(kb_id)
        
        axioms = [ax.to_string() for ax in kb.axioms]
        
        return {
            "success": True,
            "action": "list_axioms",
            "kb_id": kb_id,
            "axioms": axioms,
            "count": len(axioms)
        }
    
    async def _list_theorems(self, kb_id: str) -> Dict[str, Any]:
        """List all theorems in KB."""
        kb = self._get_or_create_kb(kb_id)
        
        if not hasattr(kb, 'theorems'):
            kb.theorems = []
        
        theorems = [
            {
                "formula": th["formula"].to_string(),
                "name": th.get("name"),
                "description": th.get("description")
            }
            for th in kb.theorems
        ]
        
        return {
            "success": True,
            "action": "list_theorems",
            "kb_id": kb_id,
            "theorems": theorems,
            "count": len(theorems)
        }
    
    async def _query_kb(
        self,
        kb_id: str,
        formula: Optional[str]
    ) -> Dict[str, Any]:
        """Query if formula is in KB."""
        if not formula:
            return {"success": False, "error": "formula is required"}
        
        kb = self._get_or_create_kb(kb_id)
        
        try:
            # Parse formula
            parsed = parse_tdfol(formula)
            formula_str = parsed.to_string()
            
            # Check axioms
            in_axioms = any(ax.to_string() == formula_str for ax in kb.axioms)
            
            # Check theorems
            in_theorems = False
            if hasattr(kb, 'theorems'):
                in_theorems = any(
                    th["formula"].to_string() == formula_str
                    for th in kb.theorems
                )
            
            return {
                "success": True,
                "action": "query",
                "kb_id": kb_id,
                "formula": formula,
                "in_axioms": in_axioms,
                "in_theorems": in_theorems,
                "found": in_axioms or in_theorems
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to query: {e}",
                "formula": formula
            }
    
    async def _export_kb(self, kb_id: str) -> Dict[str, Any]:
        """Export KB state as JSON."""
        kb = self._get_or_create_kb(kb_id)
        
        axioms = [ax.to_string() for ax in kb.axioms]
        theorems = []
        
        if hasattr(kb, 'theorems'):
            theorems = [
                {
                    "formula": th["formula"].to_string(),
                    "name": th.get("name"),
                    "description": th.get("description")
                }
                for th in kb.theorems
            ]
        
        kb_data = {
            "kb_id": kb_id,
            "axioms": axioms,
            "theorems": theorems,
            "version": "1.0"
        }
        
        return {
            "success": True,
            "action": "export",
            "kb_id": kb_id,
            "kb_data": kb_data
        }
    
    async def _import_kb(
        self,
        kb_id: str,
        kb_data: Optional[Dict]
    ) -> Dict[str, Any]:
        """Import KB state from JSON."""
        if not kb_data:
            return {"success": False, "error": "kb_data is required"}
        
        # Clear existing KB
        self._knowledge_bases[kb_id] = TDFOLKnowledgeBase()
        kb = self._knowledge_bases[kb_id]
        
        # Import axioms
        axioms_imported = 0
        for axiom_str in kb_data.get("axioms", []):
            try:
                parsed = parse_tdfol(axiom_str)
                kb.add_axiom(parsed)
                axioms_imported += 1
            except Exception as e:
                logger.warning(f"Failed to import axiom '{axiom_str}': {e}")
        
        # Import theorems
        kb.theorems = []
        theorems_imported = 0
        for theorem in kb_data.get("theorems", []):
            try:
                parsed = parse_tdfol(theorem["formula"])
                kb.theorems.append({
                    "formula": parsed,
                    "name": theorem.get("name"),
                    "description": theorem.get("description")
                })
                theorems_imported += 1
            except Exception as e:
                logger.warning(f"Failed to import theorem: {e}")
        
        return {
            "success": True,
            "action": "import",
            "kb_id": kb_id,
            "axioms_imported": axioms_imported,
            "theorems_imported": theorems_imported
        }
    
    async def _get_stats(self, kb_id: str) -> Dict[str, Any]:
        """Get KB statistics."""
        kb = self._get_or_create_kb(kb_id)
        
        theorem_count = len(kb.theorems) if hasattr(kb, 'theorems') else 0
        
        return {
            "success": True,
            "action": "stats",
            "kb_id": kb_id,
            "axiom_count": len(kb.axioms),
            "theorem_count": theorem_count,
            "total_formulas": len(kb.axioms) + theorem_count
        }
    
    async def _clear_kb(self, kb_id: str) -> Dict[str, Any]:
        """Clear all contents from KB."""
        if kb_id in self._knowledge_bases:
            del self._knowledge_bases[kb_id]
        
        return {
            "success": True,
            "action": "clear",
            "kb_id": kb_id,
            "message": f"Cleared knowledge base '{kb_id}'"
        }
    
    def _get_or_create_kb(self, kb_id: str) -> Any:
        """Get existing KB or create new one."""
        if kb_id not in self._knowledge_bases:
            self._knowledge_bases[kb_id] = TDFOLKnowledgeBase()
        return self._knowledge_bases[kb_id]


# Export tool instance
tools = [TDFOLKBTool()]
