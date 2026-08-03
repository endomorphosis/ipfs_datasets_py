# ipfs_datasets_py/mcp_server/tools/graph_tools/__init__.py
"""
Graph tools for the MCP / MCP++ server (KGP-019).

All tools are thin surfaces over a **server-owned**
:class:`~ipfs_datasets_py.knowledge_graphs.service.GraphService` resolved from
process / request context. Every call requires an explicit ``GraphTarget``;
results are canonical JSON-safe lifecycle envelopes; transactions and stream
cursors are preserved across independent tool invocations; each tool declares
MCP++ resource / effect metadata (``fn._mcp_plus``).
"""

from .query_knowledge_graph import query_knowledge_graph
from .graph_create import graph_create
from .graph_list import graph_list
from .graph_describe import graph_describe
from .graph_write import graph_write
from .graph_add_entity import graph_add_entity
from .graph_add_relationship import graph_add_relationship
from .graph_query_cypher import graph_query_cypher
from .graph_query_stream import graph_query_stream
from .graph_stream_cancel import graph_stream_cancel
from .graph_search_hybrid import graph_search_hybrid
from .graph_transaction_begin import graph_transaction_begin
from .graph_transaction_commit import graph_transaction_commit
from .graph_transaction_rollback import graph_transaction_rollback
from .graph_index_create import graph_index_create
from .graph_constraint_add import graph_constraint_add
from .graph_srl_extract import graph_srl_extract
from .graph_ontology_materialize import graph_ontology_materialize
from .graph_distributed_execute import graph_distributed_execute
from .graph_graphql_query import graph_graphql_query
from .graph_visualize import graph_visualize
from .graph_complete_suggestions import graph_complete_suggestions
from .graph_explain import graph_explain
from .graph_provenance_verify import graph_provenance_verify

# MCP++ metadata inventory for hierarchical dispatch / interface descriptors.
GRAPH_TOOL_FUNCTIONS = (
    query_knowledge_graph,
    graph_create,
    graph_list,
    graph_describe,
    graph_write,
    graph_add_entity,
    graph_add_relationship,
    graph_query_cypher,
    graph_query_stream,
    graph_stream_cancel,
    graph_search_hybrid,
    graph_transaction_begin,
    graph_transaction_commit,
    graph_transaction_rollback,
    graph_index_create,
    graph_constraint_add,
    graph_srl_extract,
    graph_ontology_materialize,
    graph_distributed_execute,
    graph_graphql_query,
    graph_visualize,
    graph_complete_suggestions,
    graph_explain,
    graph_provenance_verify,
)


def iter_mcp_plus_metadata():
    """Yield ``(tool_name, mcp_plus_dict)`` for every graph tool."""
    for fn in GRAPH_TOOL_FUNCTIONS:
        meta = getattr(fn, "_mcp_plus", None)
        if meta:
            yield fn.__name__, dict(meta)


__all__ = [
    "query_knowledge_graph",
    "graph_create",
    "graph_list",
    "graph_describe",
    "graph_write",
    "graph_add_entity",
    "graph_add_relationship",
    "graph_query_cypher",
    "graph_query_stream",
    "graph_stream_cancel",
    "graph_search_hybrid",
    "graph_transaction_begin",
    "graph_transaction_commit",
    "graph_transaction_rollback",
    "graph_index_create",
    "graph_constraint_add",
    "graph_srl_extract",
    "graph_ontology_materialize",
    "graph_distributed_execute",
    "graph_graphql_query",
    "graph_visualize",
    "graph_complete_suggestions",
    "graph_explain",
    "graph_provenance_verify",
    "GRAPH_TOOL_FUNCTIONS",
    "iter_mcp_plus_metadata",
]
