"""
MCP tool for distributed/federated Cypher query execution.

Thin wrapper around KnowledgeGraphManager.distributed_execute().
Core implementation: ipfs_datasets_py.core_operations.knowledge_graph_manager
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from ipfs_datasets_py.core_operations import KnowledgeGraphManager


async def graph_distributed_execute(
    query: str,
    num_partitions: int = 4,
    partition_strategy: str = "hash",
    parallel: bool = False,
    explain: bool = False,
    driver_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute a Cypher query across a distributed (partitioned) knowledge graph.

    Partitions the current graph into *num_partitions* shards using the chosen
    *partition_strategy*, fans the query out to each partition, and merges the
    deduplicated results.

    Args:
        query: Cypher query to execute (e.g. ``"MATCH (n:Person) RETURN n.name"``).
        num_partitions: Number of partitions to split the graph into (default 4).
        partition_strategy: One of ``"hash"`` (SHA1 of node ID), ``"range"``
            (sorted ID ranges), or ``"round_robin"`` (balanced sequential
            assignment). Default ``"hash"``.
        parallel: If ``True``, run partition queries in a thread pool (faster
            for large graphs, slightly higher overhead for small ones).
        explain: If ``True``, return a query plan (partition sizes + estimated
            result counts) without executing the query.
        driver_url: Optional graph database URL.

    Returns:
        Dict containing:
        - ``status``: ``"success"`` or ``"error"``
        - ``result_count``: number of deduplicated result records
        - ``results``: list of result record dicts
        - ``partition_stats``: per-partition node/edge counts
        - ``plan``: (if *explain* is True) QueryPlan dict instead of results
    """
    try:
        url = driver_url or "ipfs://localhost:5001"
        manager = KnowledgeGraphManager(driver_url=url)
        result = await manager.distributed_execute(
            query=query,
            num_partitions=num_partitions,
            partition_strategy=partition_strategy,
            parallel=parallel,
            explain=explain,
        )
        return result
    except Exception as e:
        logger.error("Error in graph_distributed_execute MCP tool: %s", e)
        return {"status": "error", "message": str(e), "query": query}
