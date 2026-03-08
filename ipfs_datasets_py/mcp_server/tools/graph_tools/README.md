# Graph Tools

MCP tools for building and querying knowledge graphs. These tools wrap the
`KnowledgeGraphManager` from `ipfs_datasets_py.core_operations.knowledge_graph_manager`.
The underlying graph engine supports Neo4j, in-memory, and IPLD-backed backends.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `graph_create.py` | `graph_create()` | Initialize a new knowledge graph (in-memory, Neo4j, or IPLD) |
| `graph_add_entity.py` | `graph_add_entity()` | Add an entity (node) to the graph |
| `graph_add_relationship.py` | `graph_add_relationship()` | Add a relationship (edge) between entities |
| `graph_query_cypher.py` | `graph_query_cypher()` | Execute a Cypher query against the graph |
| `graph_search_hybrid.py` | `graph_search_hybrid()` | Hybrid semantic + graph search |
| `graph_index_create.py` | `graph_index_create()` | Create a full-text or vector index on entity properties |
| `graph_constraint_add.py` | `graph_constraint_add()` | Add a uniqueness or existence constraint |
| `graph_transaction_begin.py` | `graph_transaction_begin()` | Start an explicit transaction |
| `graph_transaction_commit.py` | `graph_transaction_commit()` | Commit an open transaction |
| `graph_transaction_rollback.py` | `graph_transaction_rollback()` | Roll back an open transaction |
| `query_knowledge_graph.py` | `query_knowledge_graph()` | Natural-language knowledge graph query |
| `graph_srl_extract.py` | `graph_srl_extract()` | Extract Semantic Role Labeling (SRL) frames from text |
| `graph_ontology_materialize.py` | `graph_ontology_materialize()` | Materialize OWL/RDFS inferred facts |
| `graph_distributed_execute.py` | `graph_distributed_execute()` | Execute Cypher across distributed (partitioned) graph shards |
| `graph_graphql_query.py` | `graph_graphql_query()` | Execute a GraphQL query against the knowledge graph *(new v3.22.35)* |
| `graph_visualize.py` | `graph_visualize()` | Export graph as DOT / Mermaid / D3 JSON / ASCII *(new v3.22.35)* |
| `graph_complete_suggestions.py` | `graph_complete_suggestions()` | Suggest missing relationships (KG completion) *(new v3.22.35)* |
| `graph_explain.py` | `graph_explain()` | Explainable-AI explanations for entities, relationships, and paths *(new v3.22.35)* |
| `graph_provenance_verify.py` | `graph_provenance_verify()` | Verify integrity of the provenance chain *(new v3.22.35)* |
| `graph_gnn_embed.py` | `graph_gnn_embed()` | Compute GNN node embeddings (GRAPH_CONV / SAGE / ATTENTION) *(new v3.22.37)* |
| `graph_zkp_prove.py` | `graph_zkp_prove()` | Generate zero-knowledge proofs for KG assertions *(new v3.22.37)* |
| `graph_federate_query.py` | `graph_federate_query()` | Query across federated knowledge graphs *(new v3.22.37)* |
| `graph_analytics.py` | `graph_analytics()` | Comprehensive KG analytics: quality metrics, completion, topology *(new v3.22.38)* |
| `graph_link_predict.py` | `graph_link_predict()` | GNN link-prediction score between two entities *(new v3.22.38)* |

## Usage

### Create a graph and add data

```python
from ipfs_datasets_py.mcp_server.tools.graph_tools import (
    graph_create, graph_add_entity, graph_add_relationship, graph_query_cypher
)

# 1. Create graph
graph = await graph_create(
    graph_name="legal_corpus",
    backend="memory"    # "memory" | "neo4j" | "ipld"
)

# 2. Add entities
alice = await graph_add_entity(
    graph_name="legal_corpus",
    entity_type="Person",
    properties={"name": "Alice", "role": "attorney"},
    entity_id="alice_1"   # Optional; auto-generated if omitted
)

# 3. Add relationship
await graph_add_relationship(
    graph_name="legal_corpus",
    relationship_type="REPRESENTS",
    start_entity_id="alice_1",
    end_entity_id="case_42",
    properties={"since": "2024-01-01"}
)

# 4. Query with Cypher
result = await graph_query_cypher(
    graph_name="legal_corpus",
    query="MATCH (p:Person)-[:REPRESENTS]->(c:Case) RETURN p.name, c.id LIMIT 10"
)
```

### Natural-language query

```python
from ipfs_datasets_py.mcp_server.tools.graph_tools import query_knowledge_graph

result = await query_knowledge_graph(
    graph_name="legal_corpus",
    query="Who are the attorneys involved in environmental cases?",
    max_results=20
)
```

### Hybrid search (vector + graph)

```python
from ipfs_datasets_py.mcp_server.tools.graph_tools import graph_search_hybrid

result = await graph_search_hybrid(
    graph_name="legal_corpus",
    query="climate change litigation",
    vector_weight=0.6,   # Balance between vector and graph traversal
    max_results=10
)
```

## Transactions

For multi-step writes that must be atomic:

```python
from ipfs_datasets_py.mcp_server.tools.graph_tools import (
    graph_transaction_begin, graph_transaction_commit, graph_transaction_rollback
)

tx = await graph_transaction_begin(graph_name="my_graph")
try:
    await graph_add_entity(graph_name="my_graph", ..., transaction_id=tx["transaction_id"])
    await graph_add_relationship(graph_name="my_graph", ..., transaction_id=tx["transaction_id"])
    await graph_transaction_commit(transaction_id=tx["transaction_id"])
except Exception:
    await graph_transaction_rollback(transaction_id=tx["transaction_id"])
    raise
```

## Core Module

All business logic delegates to:
- `ipfs_datasets_py.core_operations.knowledge_graph_manager.KnowledgeGraphManager`
- `ipfs_datasets_py.knowledge_graphs` — graph engine, Cypher compiler, IPLD backend

## Dependencies

**Required:**
- Standard library: `logging`, `typing`

**Optional (graceful degradation if missing):**
- `neo4j` — for Neo4j backend (falls back to in-memory)
- `libipld` / `ipld-car` — for IPLD-backed persistent graphs
- Embedding models — for hybrid search vector component

## Status

| Tool | Status |
|------|--------|
| `graph_create` | ✅ Production ready |
| `graph_add_entity` | ✅ Production ready |
| `graph_add_relationship` | ✅ Production ready |
| `graph_query_cypher` | ✅ Production ready |
| `graph_search_hybrid` | ✅ Production ready |
| `graph_index_create` | ✅ Production ready |
| `graph_constraint_add` | ✅ Production ready |
| Transaction tools | ✅ Production ready |
| `query_knowledge_graph` | ✅ Production ready |
| `graph_srl_extract` | ✅ Production ready |
| `graph_ontology_materialize` | ✅ Production ready |
| `graph_distributed_execute` | ✅ Production ready |
| `graph_graphql_query` | ✅ Production ready (v3.22.35) |
| `graph_visualize` | ✅ Production ready (v3.22.35) |
| `graph_complete_suggestions` | ✅ Production ready (v3.22.35) |
| `graph_explain` | ✅ Production ready (v3.22.35) |
| `graph_provenance_verify` | ✅ Production ready (v3.22.35) |
