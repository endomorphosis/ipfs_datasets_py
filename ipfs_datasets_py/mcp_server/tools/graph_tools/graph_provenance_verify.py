"""
MCP tool for knowledge-graph provenance chain verification.

Thin wrapper around KnowledgeGraphManager.verify_provenance().
Core implementation: ipfs_datasets_py.core_operations.knowledge_graph_manager
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from ipfs_datasets_py.core_operations import KnowledgeGraphManager


async def graph_provenance_verify(
    provenance_jsonl: Optional[str] = None,
    kg_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Verify the integrity of a knowledge-graph provenance chain.

    Uses ``ProvenanceChain.verify_chain()`` from ``extraction/provenance.py``
    to perform a tamper-detection audit of a content-addressed event chain.

    Each event in a ``ProvenanceChain`` is SHA-256 hashed (forming a CID)
    and linked to the previous event's CID, creating a blockchain-style
    tamper-evident log.  This tool re-computes every CID and checks that
    the chain links are intact.

    **Two input modes:**

    1. ``provenance_jsonl`` — Supply a raw JSONL string previously exported
       via ``ProvenanceChain.to_jsonl()``.
    2. ``kg_data`` — Supply a serialised KG dict.  If the KG has a live
       provenance chain attached (via ``kg.enable_provenance()``) this
       tool will verify it directly.

    If both are ``None`` an empty (trivially valid) chain is created.

    Args:
        provenance_jsonl: Optional JSONL string of provenance events
            (one JSON object per line).
        kg_data: Optional serialised knowledge-graph dict (from
            ``kg.to_dict()``).

    Returns:
        Dict containing:

        - ``status``: ``"success"`` or ``"error"``
        - ``valid``: ``True`` if the chain passes all integrity checks
        - ``event_count``: total number of events in the chain
        - ``errors``: list of error strings (empty when valid)
        - ``latest_cid``: CID of the most recent event (or ``None`` for
          an empty chain)
        - ``depth``: chain depth (number of events)
    """
    try:
        manager = KnowledgeGraphManager()
        result = await manager.verify_provenance(
            provenance_jsonl=provenance_jsonl,
            kg_data=kg_data,
        )
        return result
    except Exception as e:
        logger.error("Error in graph_provenance_verify MCP tool: %s", e)
        return {"status": "error", "message": str(e), "valid": False, "errors": [str(e)]}
