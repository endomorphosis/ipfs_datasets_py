"""
MCP tool for OWL/RDFS ontology materialization on a knowledge graph.

Thin wrapper around KnowledgeGraphManager.ontology_materialize().
Core implementation: ipfs_datasets_py.core_operations.knowledge_graph_manager
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from ipfs_datasets_py.core_operations import KnowledgeGraphManager


async def graph_ontology_materialize(
    graph_name: str,
    schema: Optional[Dict[str, Any]] = None,
    check_consistency: bool = False,
    explain: bool = False,
    driver_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Apply OWL/RDFS ontology inference rules to a knowledge graph.

    Runs a fixpoint loop that materializes all entailed facts declared in the
    supplied ontology schema.  Supported axioms:

    * **subClassOf** — propagate super-class types to instances
    * **subPropertyOf** — generate super-property relationships
    * **transitive** — transitive closure of a property
    * **symmetric** — add reverse edges for symmetric properties
    * **inverseOf** — add inverse-direction edges
    * **domain / range** — assign types based on property usage
    * **propertyChainAxiom** — multi-step property chain inference
    * **equivalentClass** — mutual subclass treatment

    Args:
        graph_name: Name of the graph to materialise inferences on.
        schema: Ontology schema declaration dict with optional keys:
            ``subclass``, ``subproperty``, ``transitive``, ``symmetric``,
            ``inverse``, ``domain``, ``range``, ``disjoint``,
            ``property_chains``, ``equivalent_classes``.
            All lists/dicts; any omitted key uses an empty default.
        check_consistency: If ``True``, also run the consistency checker
            and return any detected violations.
        explain: If ``True``, return a list of inference traces (which rule
            produced which inferred fact) rather than modifying the graph.
        driver_url: Optional graph database URL.

    Returns:
        Dict containing:
        - ``status``: ``"success"`` or ``"error"``
        - ``inferred_count``: number of new facts inferred (or 0 if *explain*)
        - ``violations``: (if *check_consistency*) list of consistency violation dicts
        - ``traces``: (if *explain*) list of inference trace dicts
    """
    try:
        url = driver_url or "ipfs://localhost:5001"
        manager = KnowledgeGraphManager(driver_url=url)
        result = await manager.ontology_materialize(
            graph_name=graph_name,
            schema=schema or {},
            check_consistency=check_consistency,
            explain=explain,
        )
        return result
    except Exception as e:
        logger.error("Error in graph_ontology_materialize MCP tool: %s", e)
        return {"status": "error", "message": str(e), "graph_name": graph_name}
