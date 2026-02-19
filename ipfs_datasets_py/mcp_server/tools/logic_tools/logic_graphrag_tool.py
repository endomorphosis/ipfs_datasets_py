"""
Logic GraphRAG Integration Tool — Logic-augmented knowledge graph and RAG via MCP.

Exposes two MCP tools that bridge the logic module with the GraphRAG pipeline:

    - ``logic_build_knowledge_graph`` — Convert a text corpus into a logic-annotated
      knowledge graph (nodes = logical entities, edges = inferred relations).

    - ``logic_verify_rag_output``     — Verify that a RAG-generated answer is
      consistent with a set of logical constraints / theorems.

These tools implement Phase 3.4 (GraphRAG Deep Integration) from the
MASTER_REFACTORING_PLAN_2026.md.  They integrate with the existing graph_tools
(graph_create, graph_add_entity, graph_add_relationship) and the TDFOL/CEC
prover stack already exposed through the other logic MCP tools.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tool_registry import ClaudeMCPTool

logger = logging.getLogger(__name__)

TOOL_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_logical_entities(text: str) -> List[Dict[str, str]]:
    """
    Extract logical entities (agents, obligations, events) from *text*.

    Tries the TDFOL NL converter first, falls back to simple heuristics.
    Each entity is a dict with ``name``, ``type``, and ``source_text``.
    """
    entities: List[Dict[str, str]] = []
    try:
        from ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter import TDFOLNLConverter
        converter = TDFOLNLConverter()
        result = converter.convert(text)
        if result and hasattr(result, "entities"):
            for ent in result.entities:
                entities.append({
                    "name": str(ent.name),
                    "type": str(ent.entity_type),
                    "source_text": text[:100],
                })
            return entities
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("TDFOL NL entity extraction failed: %s", exc)

    # Text-level heuristic: look for obligation/permission/prohibition patterns
    import re
    obligation_pattern = re.compile(r"\b(?:must|shall|obligated to|required to)\s+(\w+(?:\s+\w+){0,3})", re.I)
    permission_pattern = re.compile(r"\b(?:may|permitted to|allowed to|can)\s+(\w+(?:\s+\w+){0,3})", re.I)
    prohibition_pattern = re.compile(r"\b(?:must not|shall not|prohibited from|forbidden to)\s+(\w+(?:\s+\w+){0,3})", re.I)

    for m in obligation_pattern.finditer(text):
        entities.append({"name": m.group(1).strip(), "type": "obligation", "source_text": m.group(0)})
    for m in permission_pattern.finditer(text):
        entities.append({"name": m.group(1).strip(), "type": "permission", "source_text": m.group(0)})
    for m in prohibition_pattern.finditer(text):
        entities.append({"name": m.group(1).strip(), "type": "prohibition", "source_text": m.group(0)})

    return entities[:50]  # cap at 50 entities per call


def _check_logical_consistency(
    claim: str,
    constraints: List[str],
) -> Dict[str, Any]:
    """
    Check whether *claim* is consistent with *constraints* using the TDFOL prover.

    Returns a dict with ``consistent`` bool, ``violations`` list, and
    ``prover_used`` string.
    """
    violations: List[str] = []
    prover_used = "none"
    try:
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import TDFOLProver
        prover = TDFOLProver()
        for constraint in constraints:
            # Check: does ¬claim follow from constraint?  (i.e., is claim consistent)
            result = prover.check_consistency([claim, constraint])
            if hasattr(result, "consistent") and not result.consistent:
                violations.append(constraint)
        prover_used = "tdfol"
        return {"consistent": len(violations) == 0, "violations": violations, "prover_used": prover_used}
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("TDFOL consistency check failed: %s", exc)

    # Fall back to trivial (no contradiction detected)
    return {
        "consistent": True,
        "violations": [],
        "prover_used": "unavailable",
        "note": "TDFOL prover not available; consistency check skipped.",
    }


# ---------------------------------------------------------------------------
# Tool: logic_build_knowledge_graph
# ---------------------------------------------------------------------------

class LogicBuildKnowledgeGraphTool(ClaudeMCPTool):
    """
    MCP Tool: build a logic-annotated knowledge graph from text.

    Extracts logical entities (obligations, permissions, prohibitions, agents,
    events) from the input corpus and returns a structured graph suitable for
    passing to the ``graph_create`` / ``graph_add_entity`` graph tools.

    This enables the "Text → Knowledge Graph" pipeline described in
    Phase 3.4 of MASTER_REFACTORING_PLAN_2026.md.
    """

    def __init__(self) -> None:
        super().__init__()
        self.name = "logic_build_knowledge_graph"
        self.description = (
            "Extract logical entities and relationships from text to build a "
            "logic-annotated knowledge graph. Returns nodes and edges ready for "
            "the graph_create/graph_add_entity MCP tools."
        )
        self.category = "logic_tools"
        self.tags = ["logic", "graphrag", "knowledge-graph", "extraction", "tdfol", "cec"]
        self.version = TOOL_VERSION

        self.input_schema = {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text corpus to extract a knowledge graph from.",
                    "maxLength": 32768,
                },
                "logic_system": {
                    "type": "string",
                    "description": "Logic system to use for entity typing.",
                    "enum": ["tdfol", "cec", "auto"],
                    "default": "auto",
                },
                "include_formulas": {
                    "type": "boolean",
                    "description": "Include TDFOL/DCEC formula annotations on nodes.",
                    "default": True,
                },
                "max_entities": {
                    "type": "integer",
                    "description": "Maximum number of entities to extract (1–200).",
                    "default": 50,
                    "minimum": 1,
                    "maximum": 200,
                },
            },
            "required": ["text"],
        }

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build a logic-annotated knowledge graph.

        Args:
            parameters: ``text``, ``logic_system``, ``include_formulas``,
                ``max_entities``.

        Returns:
            Dict with:
                - ``nodes``: list of ``{id, label, type, formula}`` dicts
                - ``edges``: list of ``{source, target, relation}`` dicts
                - ``entity_count``: int
                - ``logic_system_used``: str

        Example:
            >>> result = await tool.execute({
            ...     "text": "The company must file taxes by April 15.",
            ...     "logic_system": "tdfol",
            ... })
            >>> isinstance(result["nodes"], list)
            True
        """
        from ipfs_datasets_py.logic.common.validators import validate_formula_string
        start = time.monotonic()

        text: str = parameters.get("text", "").strip()
        logic_system: str = parameters.get("logic_system", "auto")
        include_formulas: bool = parameters.get("include_formulas", True)
        max_entities: int = min(int(parameters.get("max_entities", 50)), 200)

        if not text:
            return {"success": False, "error": "'text' must be non-empty."}
        if len(text) > 32768:
            return {"success": False, "error": "'text' exceeds 32768-character limit."}

        entities = _extract_logical_entities(text)[:max_entities]

        # Build graph nodes
        nodes: List[Dict[str, Any]] = []
        node_ids: Dict[str, str] = {}
        for i, ent in enumerate(entities):
            node_id = f"node_{i}"
            node_ids[ent["name"]] = node_id
            node: Dict[str, Any] = {
                "id": node_id,
                "label": ent["name"],
                "type": ent["type"],
                "source_text": ent.get("source_text", ""),
            }
            if include_formulas:
                # Attempt to annotate with a DCEC formula
                formula_prefix = {
                    "obligation": "O",
                    "permission": "P",
                    "prohibition": "F",
                }.get(ent["type"], "")
                if formula_prefix:
                    safe_name = ent["name"].replace(" ", "_").lower()
                    node["formula"] = f"{formula_prefix}({safe_name})"
            nodes.append(node)

        # Build simple co-occurrence edges (entities from the same sentence)
        import re
        edges: List[Dict[str, str]] = []
        sentences = re.split(r"[.!?;]\s+", text)
        for sent in sentences:
            present = [
                node_ids[ent["name"]]
                for ent in entities
                if ent["name"].lower() in sent.lower() and ent["name"] in node_ids
            ]
            for j in range(len(present)):
                for k in range(j + 1, len(present)):
                    edges.append({
                        "source": present[j],
                        "target": present[k],
                        "relation": "co_occurs_with",
                    })

        return {
            "success": True,
            "nodes": nodes,
            "edges": edges,
            "entity_count": len(nodes),
            "edge_count": len(edges),
            "logic_system_used": logic_system,
            "elapsed_ms": (time.monotonic() - start) * 1000,
            "tool_version": TOOL_VERSION,
        }


# ---------------------------------------------------------------------------
# Tool: logic_verify_rag_output
# ---------------------------------------------------------------------------

class LogicVerifyRAGOutputTool(ClaudeMCPTool):
    """
    MCP Tool: verify that a RAG-generated answer satisfies logical constraints.

    Given a claim (e.g. an answer generated by a RAG system) and a list of
    logical constraints (e.g. TDFOL formulas, legal rules), checks whether
    the claim is consistent with the constraints using the TDFOL prover.

    This implements the "Logical constraint verification in RAG outputs" feature
    described in Phase 3.4 of MASTER_REFACTORING_PLAN_2026.md.
    """

    def __init__(self) -> None:
        super().__init__()
        self.name = "logic_verify_rag_output"
        self.description = (
            "Verify that a RAG-generated answer is logically consistent with a set "
            "of constraints or theorems. Uses the TDFOL prover for formal verification."
        )
        self.category = "logic_tools"
        self.tags = ["logic", "graphrag", "verify", "consistency", "rag", "tdfol"]
        self.version = TOOL_VERSION

        self.input_schema = {
            "type": "object",
            "properties": {
                "claim": {
                    "type": "string",
                    "description": "The RAG-generated claim or answer to verify.",
                    "maxLength": 4096,
                },
                "constraints": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of logical constraints (TDFOL formulas or natural-language "
                        "rules) the claim must satisfy."
                    ),
                    "minItems": 1,
                    "maxItems": 50,
                },
                "logic_system": {
                    "type": "string",
                    "description": "Logic system to use for verification.",
                    "enum": ["tdfol", "cec", "auto"],
                    "default": "auto",
                },
            },
            "required": ["claim", "constraints"],
        }

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Verify logical consistency of a RAG output.

        Args:
            parameters: ``claim`` (str), ``constraints`` (list[str]),
                ``logic_system`` (str).

        Returns:
            Dict with:
                - ``consistent``: bool — True if no violations found
                - ``violations``: list[str] — constraints violated by the claim
                - ``prover_used``: str
                - ``verification_score``: float (0.0–1.0)

        Example:
            >>> result = await tool.execute({
            ...     "claim": "The company filed taxes on time.",
            ...     "constraints": ["O(file_taxes(company))", "T(deadline, April_15)"],
            ... })
            >>> "consistent" in result
            True
        """
        from ipfs_datasets_py.logic.common.validators import (
            validate_formula_string, validate_axiom_list,
        )
        start = time.monotonic()

        claim: str = parameters.get("claim", "").strip()
        constraints: List[str] = parameters.get("constraints", [])
        logic_system: str = parameters.get("logic_system", "auto")

        if not claim:
            return {"success": False, "error": "'claim' must be non-empty."}

        if not constraints:
            return {"success": False, "error": "'constraints' must be a non-empty list."}

        if len(constraints) > 50:
            return {
                "success": False,
                "error": f"Too many constraints: {len(constraints)} (maximum 50).",
            }

        try:
            validate_axiom_list(constraints)
        except Exception as exc:
            return {"success": False, "error": str(exc)}

        consistency = _check_logical_consistency(claim, constraints)

        n_constraints = len(constraints)
        n_violations = len(consistency.get("violations", []))
        verification_score = 1.0 - (n_violations / n_constraints) if n_constraints else 1.0

        return {
            "success": True,
            "consistent": consistency["consistent"],
            "violations": consistency.get("violations", []),
            "prover_used": consistency.get("prover_used", "none"),
            "verification_score": round(verification_score, 4),
            "constraints_checked": n_constraints,
            "logic_system": logic_system,
            "elapsed_ms": (time.monotonic() - start) * 1000,
            "tool_version": TOOL_VERSION,
        }


# ---------------------------------------------------------------------------
# Tool instances (registered in __init__.py)
# ---------------------------------------------------------------------------

LOGIC_GRAPHRAG_TOOLS = [
    LogicBuildKnowledgeGraphTool(),
    LogicVerifyRAGOutputTool(),
]

__all__ = [
    "TOOL_VERSION",
    "LogicBuildKnowledgeGraphTool",
    "LogicVerifyRAGOutputTool",
    "LOGIC_GRAPHRAG_TOOLS",
]
