"""
Logic GraphRAG integration tools for MCP / CLI.

Implements Phase 3.4 (GraphRAG Deep Integration) from
``MASTER_REFACTORING_PLAN_2026.md``.

Functions
---------
logic_build_knowledge_graph
    Convert a text corpus into a logic-annotated knowledge graph.
logic_verify_rag_output
    Verify that a RAG-generated answer is consistent with logical constraints.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from ipfs_datasets_py.core_operations.logic_processor import LogicProcessor
    _PROCESSOR = LogicProcessor()
    _AVAILABLE = True
except Exception as _e:
    logger.warning("LogicProcessor not available: %s", _e)
    _PROCESSOR = None  # type: ignore[assignment]
    _AVAILABLE = False


def _unavailable(tool: str) -> Dict[str, Any]:
    return {"success": False, "error": f"{tool}: LogicProcessor not available."}


async def logic_build_knowledge_graph(
    text_corpus: str,
    include_temporal: bool = True,
    include_deontic: bool = True,
    max_entities: int = 100,
) -> Dict[str, Any]:
    """
    Extract logical entities from a text corpus and build an annotated knowledge graph.

    Args:
        text_corpus: Source text (max 1 MB).
        include_temporal: Extract temporal entities (before, after, always, …).
        include_deontic: Extract deontic entities (must, shall, prohibited, …).
        max_entities: Maximum number of nodes to extract (1–500).

    Returns:
        Dict with ``nodes`` (list), ``edges`` (list), ``node_count``, ``edge_count``.
    """
    if not _AVAILABLE:
        return _unavailable("logic_build_knowledge_graph")
    if not text_corpus:
        return {"success": False, "error": "'text_corpus' is required."}
    return await _PROCESSOR.build_knowledge_graph(
        text_corpus=text_corpus,
        include_temporal=include_temporal,
        include_deontic=include_deontic,
        max_entities=max_entities,
    )


async def logic_verify_rag_output(
    answer: str,
    constraints: Optional[List[str]] = None,
    logic_system: str = "tdfol",
    strict_mode: bool = False,
) -> Dict[str, Any]:
    """
    Verify that a RAG-generated answer is consistent with logical constraints.

    Args:
        answer: RAG answer to verify.
        constraints: Logical constraint formulas (max 50).
        logic_system: Logic system to use for verification — tdfol | cec | fol.
        strict_mode: If True, all constraints must be satisfied.

    Returns:
        Dict with ``consistent`` (bool), ``violations`` (list),
        ``verified_count``, ``violation_count``.
    """
    if not _AVAILABLE:
        return _unavailable("logic_verify_rag_output")
    if not answer:
        return {"success": False, "error": "'answer' is required."}
    return await _PROCESSOR.verify_rag_output(
        answer=answer,
        constraints=constraints,
        logic_system=logic_system,
        strict_mode=strict_mode,
    )


__all__ = ["logic_build_knowledge_graph", "logic_verify_rag_output"]
