"""
MCP tool for zero-knowledge proof generation over knowledge graph assertions.

Thin wrapper around KnowledgeGraphManager.zkp_prove().
Core implementation: ipfs_datasets_py.core_operations.knowledge_graph_manager
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

from ipfs_datasets_py.core_operations import KnowledgeGraphManager


async def graph_zkp_prove(
    proof_type: str = "entity_exists",
    entity_type: Optional[str] = None,
    entity_name: Optional[str] = None,
    entity_id: Optional[str] = None,
    property_key: Optional[str] = None,
    property_value_hash: Optional[str] = None,
    path_start_type: Optional[str] = None,
    path_end_type: Optional[str] = None,
    min_count: Optional[int] = None,
    actual_count: Optional[int] = None,
    kg_data: Optional[Dict[str, Any]] = None,
    prover_id: str = "default",
    build_tdfol_witness: bool = False,
    circuit_version: int = 1,
) -> Dict[str, Any]:
    """
    Generate a zero-knowledge proof for a knowledge-graph assertion.

    Uses :class:`~ipfs_datasets_py.knowledge_graphs.query.zkp.KGZKProver` to
    produce a :class:`~ipfs_datasets_py.knowledge_graphs.query.zkp.KGProofStatement`
    — a privacy-preserving proof that a property holds over the graph without
    revealing entity IDs or other private data.

    When *build_tdfol_witness* is ``True``, the tool also builds a
    TDFOL_v1-compatible witness dict (via
    :class:`~ipfs_datasets_py.knowledge_graphs.query.groth16_kg_witness.KGWitnessBuilder`)
    ready for submission to the Groth16 Rust backend.

    **Supported proof types:**

    - ``"entity_exists"`` — prove an entity with *entity_type* + *entity_name*
      exists.  Requires *entity_type* and *entity_name*.
    - ``"entity_property"`` — prove an entity has a property value.  Requires
      *entity_id* (or *entity_name*), *property_key*, and *property_value_hash*.
    - ``"path_exists"`` — prove a path between two entity types exists.  Requires
      *path_start_type* and *path_end_type*.
    - ``"query_answer_count"`` — prove the result count is ≥ *min_count*.
      Requires *min_count* and *actual_count*.

    Args:
        proof_type: One of ``"entity_exists"``, ``"entity_property"``,
            ``"path_exists"``, ``"query_answer_count"``.  Default
            ``"entity_exists"``.
        entity_type: Entity type for ``entity_exists`` / ``entity_property``
            proofs.
        entity_name: Entity name for ``entity_exists`` proofs.
        entity_id: Private entity ID used in the witness (not revealed in proof).
        property_key: Property key for ``entity_property`` proofs.
        property_value_hash: 64-char hex SHA-256 of the property value.
        path_start_type: Starting entity type for ``path_exists`` proofs.
        path_end_type: Ending entity type for ``path_exists`` proofs.
        min_count: Minimum count for ``query_answer_count`` proofs.
        actual_count: Actual (private) count for ``query_answer_count`` proofs.
        kg_data: Optional serialised KG dict.  When supplied, the prover
            operates over the provided graph.
        prover_id: Stable identifier for the prover instance (used in
            nullifier computation).  Default ``"default"``.
        build_tdfol_witness: When ``True``, also build and return a
            TDFOL_v1 witness dict for the Groth16 backend.  Default
            ``False``.
        circuit_version: TDFOL_v1 circuit version (1 or 2) used when
            *build_tdfol_witness* is ``True``.  Default 1.

    Returns:
        Dict containing:

        - ``status``: ``"success"`` or ``"error"``
        - ``proof_type``: the proof type used
        - ``proof``: the serialised :class:`KGProofStatement` dict
          (``proof_type``, ``commitment``, ``nullifier``, ``parameters``,
          ``public_inputs``, ``timestamp``)
        - ``valid``: ``True`` if the proof was immediately verified
        - ``tdfol_witness``: TDFOL_v1 witness dict (only when
          *build_tdfol_witness* is ``True``)
    """
    try:
        manager = KnowledgeGraphManager()
        result = await manager.zkp_prove(
            proof_type=proof_type,
            entity_type=entity_type,
            entity_name=entity_name,
            entity_id=entity_id,
            property_key=property_key,
            property_value_hash=property_value_hash,
            path_start_type=path_start_type,
            path_end_type=path_end_type,
            min_count=min_count,
            actual_count=actual_count,
            kg_data=kg_data,
            prover_id=prover_id,
            build_tdfol_witness=build_tdfol_witness,
            circuit_version=circuit_version,
        )
        return result
    except Exception as e:
        logger.error("Error in graph_zkp_prove MCP tool: %s", e)
        return {
            "status": "error",
            "message": str(e),
            "proof_type": proof_type,
            "proof": None,
            "valid": False,
        }
