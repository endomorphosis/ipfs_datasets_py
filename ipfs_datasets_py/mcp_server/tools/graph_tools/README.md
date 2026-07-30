# Graph Tools (KGP-019)

MCP / MCP++ tools for production knowledge graphs. Every tool is a **thin
surface** over a process- or server-owned
[`GraphService`](../../../knowledge_graphs/service.py) resolved from
`ipfs_datasets_py.mcp_server.graph_service_registry`.

## Contract rules

1. **Explicit target** — every call names a `GraphTarget` via
   `target="kg://tenant/graph/..."` or `tenant` + `graph_id` (+ optional
   `branch` / `revision`). No ambient / default graph.
2. **One-service rule** — tools never construct a fresh manager per invocation.
   Transactions and stream cursors live on the shared service and survive
   independent tool calls in the same process.
3. **Canonical JSON-safe envelopes** — results are
   `kg-service-contract/v1` lifecycle envelopes (`status`, `operation`,
   `target`, `result` / `error`, `request_id`, …). Query payloads use
   `kg-query-envelope/v1`.
4. **MCP++ metadata** — each tool declares `_mcp_plus` with
   `resource_template` (`kg://…`), `ability` (`graph/list|read|query|write|admin`),
   and `effects` (`graph.read|query|write|admin|stream|cancel`).
5. **Tenant isolation** — pass per-client `auth={principal, tenant|allowed_tenants, abilities}`;
   `TenantScopeAuthorizer` forbids cross-tenant observation without grant.

## Store configuration

```bash
export IPFS_DATASETS_KG_CATALOG=/var/lib/kg/catalog.sqlite
export IPFS_DATASETS_KG_STORE=/var/lib/kg/payloads
```

Or bind programmatically:

```python
from ipfs_datasets_py.mcp_server.graph_service_registry import open_graph_service
open_graph_service("/tmp/kg.sqlite", storage_path="/tmp/kg-payloads")
```

`ServerContext` auto-opens the service when catalog path is configured.

## Core tools

| Tool | Operation | Notes |
|------|-----------|--------|
| `graph_create` | create | Register identity; requires target |
| `graph_list` | list | Tenant listing |
| `graph_describe` | describe | Catalog metadata + head |
| `graph_write` | write | Bulk entities/relationships |
| `graph_add_entity` | write | Single entity mutation |
| `graph_add_relationship` | write | Single relationship mutation |
| `graph_query_cypher` | query | Cypher / cypher-lite |
| `graph_search_hybrid` | query | Scan / hybrid search |
| `query_knowledge_graph` | query | NL/scan entry point |
| `graph_query_stream` | query | Page + opaque cursor |
| `graph_stream_cancel` | query | Cancel stream session |
| `graph_transaction_begin` | begin_tx | State held on shared service |
| `graph_transaction_commit` | commit_tx | Requires `transaction_id` + idempotency key |
| `graph_transaction_rollback` | rollback_tx | Requires `transaction_id` |

Specialized tools (`graph_visualize`, `graph_explain`, …) also require an
explicit target and load snapshots through the same service when applicable.

## Example

```python
from ipfs_datasets_py.mcp_server.graph_service_registry import open_graph_service
from ipfs_datasets_py.mcp_server.tools.graph_tools import (
    graph_create, graph_add_entity, graph_query_stream, graph_stream_cancel,
)

open_graph_service("/tmp/kg.sqlite", storage_path="/tmp/payloads")

await graph_create(target="kg://acme/skills/branches/main", idempotency_key="c1")
await graph_add_entity(
    entity_id="ada", entity_type="Person", properties={"name": "Ada"},
    target="kg://acme/skills/branches/main", idempotency_key="w1",
)
page = await graph_query_stream(
    target="kg://acme/skills/branches/main", language="scan", page_size=100,
)
# resume with page["result"]["cursor"] or cancel via graph_stream_cancel
```

## Validation

```bash
python -m pytest -q tests/knowledge_graphs/conformance/test_mcp.py tests/mcp/test_graph_tools.py
```
