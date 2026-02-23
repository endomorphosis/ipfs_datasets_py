"""Knowledge graph query API.

This module contains the *core* implementation behind the MCP tool
`graph_tools.query_knowledge_graph`.

Development pattern:
- Put functionality in importable `ipfs_datasets_py` modules.
- Expose them via CLI and MCP wrappers.

This module is intentionally MCP-agnostic.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def parse_ir_ops_from_query(query: str) -> List[Dict[str, Any]]:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty JSON string when query_type='ir'")
    text = query.strip()
    if not (text.startswith("[") or text.startswith("{")):
        raise ValueError("query_type='ir' requires JSON (list of ops or {ops:[...]})")
    payload = json.loads(text)
    ops = payload.get("ops") if isinstance(payload, dict) else payload
    if not isinstance(ops, list) or not ops:
        raise ValueError("IR payload must be a non-empty list of ops")
    for op in ops:
        if not isinstance(op, dict):
            raise ValueError("Each IR op must be an object/dict")
    return ops


def compile_ir(ops: List[Dict[str, Any]]):
    from ipfs_datasets_py.search.graph_query.ir import Expand, Limit, Project, QueryIR, ScanType, SeedEntities

    compiled_ops = []
    for raw in ops:
        op_name = raw.get("op") or raw.get("type") or raw.get("name")
        if not isinstance(op_name, str) or not op_name:
            raise ValueError("IR op missing 'op' (or 'type'/'name')")

        if op_name == "SeedEntities":
            entity_ids = raw.get("entity_ids")
            if not isinstance(entity_ids, list) or not entity_ids:
                raise ValueError("SeedEntities.entity_ids must be a non-empty list")
            compiled_ops.append(SeedEntities(entity_ids))
        elif op_name == "ScanType":
            entity_type = raw.get("entity_type")
            scope = raw.get("scope")
            if not isinstance(entity_type, str) or not entity_type:
                raise ValueError("ScanType.entity_type must be a non-empty string")
            if scope is not None and not isinstance(scope, list):
                raise ValueError("ScanType.scope must be a list or null")
            compiled_ops.append(ScanType(entity_type=entity_type, scope=scope))
        elif op_name == "Expand":
            relationship_types = raw.get("relationship_types")
            direction = raw.get("direction", "both")
            max_per_node = raw.get("max_per_node")
            if relationship_types is not None and not isinstance(relationship_types, list):
                raise ValueError("Expand.relationship_types must be a list or null")
            if direction not in ("outgoing", "incoming", "both"):
                raise ValueError("Expand.direction must be one of: outgoing, incoming, both")
            if max_per_node is not None and (not isinstance(max_per_node, int) or max_per_node <= 0):
                raise ValueError("Expand.max_per_node must be a positive int or null")
            compiled_ops.append(
                Expand(
                    relationship_types=relationship_types,
                    direction=direction,
                    max_per_node=max_per_node,
                )
            )
        elif op_name == "Limit":
            n = raw.get("n")
            if not isinstance(n, int) or n < 0:
                raise ValueError("Limit.n must be an int >= 0")
            compiled_ops.append(Limit(n=n))
        elif op_name == "Project":
            fields = raw.get("fields")
            if not isinstance(fields, list) or not fields:
                raise ValueError("Project.fields must be a non-empty list")
            compiled_ops.append(Project(fields=fields))
        else:
            raise ValueError(f"Unsupported IR op: {op_name}")

    return QueryIR.from_ops(compiled_ops)


def query_knowledge_graph(
    graph_id: Optional[str] = None,
    query: str = "",
    query_type: str = "ir",
    max_results: int = 100,
    include_metadata: bool = True,
    *,
    manifest_cid: Optional[str] = None,
    ir_ops: Optional[List[Dict[str, Any]]] = None,
    budgets: Optional[Dict[str, Any]] = None,
    budget_preset: Optional[str] = None,
    ipfs_backend: Optional[str] = None,
    car_fetch_mode: str = "auto",
) -> Dict[str, Any]:
    """Query a knowledge graph.

    This is the package-level API used by both CLI and MCP wrappers.
    """

    _ = include_metadata  # v1 IR queries already return explicit projections

    if not isinstance(max_results, int) or max_results <= 0:
        raise ValueError("max_results must be a positive integer")

    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")

    # Legacy/compat mode: small in-memory/mock graphs.
    if query_type in {"sparql", "cypher", "gremlin", "semantic"}:
        if not graph_id:
            raise ValueError("graph_id is required for legacy query types")

        # Keep this lightweight and dependency-free. For PDF graphs, prefer
        # pdf_tools/pdf_query_knowledge_graph.
        # Always import legacy processor for test_graph compatibility
        # noqa: F401 not needed — both GraphRAGProcessor and MockGraphRAGProcessor are used below
        from ipfs_datasets_py.processors.graphrag_processor import GraphRAGProcessor, MockGraphRAGProcessor
        # Import unified processor (recommended) with fallback to legacy
        try:
            from ipfs_datasets_py.processors.specialized.graphrag.unified_graphrag import (
                UnifiedGraphRAGProcessor,
                GraphRAGConfiguration
            )
            # Use unified processor
            config = GraphRAGConfiguration(processing_mode="fast")
            processor = UnifiedGraphRAGProcessor(config=config)
        except ImportError:
            # Fallback to legacy processor (deprecated but still supported)
            processor = GraphRAGProcessor()

        if graph_id == "test_graph":
            processor = MockGraphRAGProcessor()
        else:
            processor = GraphRAGProcessor()

        graph = processor.load_graph(graph_id)
        if query_type == "sparql":
            results = processor.execute_sparql(graph, query, limit=max_results)
        elif query_type == "cypher":
            results = processor.execute_cypher(graph, query, limit=max_results)
        elif query_type == "gremlin":
            results = processor.execute_gremlin(graph, query, limit=max_results)
        else:
            results = processor.execute_semantic_query(graph, query, limit=max_results)

        return {
            "success": True,
            "status": "success",
            "query_type": query_type,
            "graph_id": graph_id,
            "num_results": len(results) if isinstance(results, list) else 0,
            "results": results,
        }

    # Large-graph mode: sharded-CAR + IR.
    if query_type != "ir":
        raise ValueError(
            "Unsupported query_type. Use query_type='ir' (sharded-CAR), or one of: sparql, cypher, gremlin, semantic. "
            "For PDF graphs, use pdf_tools/pdf_query_knowledge_graph."
        )

    if manifest_cid is None:
        raise ValueError("manifest_cid is required for query_type='ir' (sharded-CAR backend)")

    ops = ir_ops if ir_ops is not None else parse_ir_ops_from_query(query)
    ir = compile_ir(ops)

    from ipfs_datasets_py.search.graph_query import GraphQueryExecutor
    from ipfs_datasets_py.search.graph_query.budgets import budgets_from_preset
    from ipfs_datasets_py.search.graph_query.sharded_car import sharded_car_backend_from_manifest_cid

    backend = sharded_car_backend_from_manifest_cid(
        manifest_cid,
        backend=ipfs_backend,
        car_fetch_mode=car_fetch_mode,
    )
    executor = GraphQueryExecutor(backend)
    effective_budgets = budgets_from_preset(
        budget_preset,
        max_results=int(max_results),
        overrides=budgets,
    )
    res = executor.execute(ir, budgets=effective_budgets)

    return {
        "success": True,
        "status": "success",
        "query_type": "ir",
        "graph_id": graph_id,
        "manifest_cid": manifest_cid,
        "num_results": len(res.items),
        "results": res.items,
        "stats": res.stats,
        "effective_budgets": {
            "max_results": effective_budgets.max_results,
            "timeout_ms": effective_budgets.timeout_ms,
            "max_depth": effective_budgets.max_depth,
            "max_nodes_visited": effective_budgets.max_nodes_visited,
            "max_edges_scanned": effective_budgets.max_edges_scanned,
            "max_working_set_entities": effective_budgets.max_working_set_entities,
            "max_degree_per_node": effective_budgets.max_degree_per_node,
            "max_shards_touched": effective_budgets.max_shards_touched,
            "allow_unanchored_scan": effective_budgets.allow_unanchored_scan,
        },
    }
