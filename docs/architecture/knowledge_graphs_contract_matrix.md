# Knowledge Graphs Public Lifecycle Contract Matrix

**Program:** `KGP`  
**Task:** `KGP-001` — Capture failing public lifecycle contracts  
**Date:** 2026-07-29  
**Executable probes:** `tests/knowledge_graphs/contract/test_public_lifecycle.py`  
**Plan reference:** `docs/architecture/KNOWLEDGE_GRAPHS_PRODUCTION_HARDENING_PLAN_2026_07_29.md`

This matrix records **observed** cross-surface behavior for create / add / query /
reopen / transaction. It is evidence for the baseline, not a claim that the
module is production ready. Production expectations are encoded as strict
assertions in the probe tests; known failures use issue-linked
`pytest.mark.xfail(strict=True)` markers rather than permissive exit-code checks.

## Surfaces

| Surface | Entry point | Process model |
| --- | --- | --- |
| Python API | `ipfs_datasets_py.core_operations.KnowledgeGraphManager` | In-process |
| CLI | `python ipfs_datasets_cli.py graph <subcommand>` | Fresh process per invocation |
| MCP | `ipfs_datasets_py.mcp_server.tools.graph_tools.*` | Fresh `KnowledgeGraphManager` per tool call |
| MCP++ | `tools_dispatch("graph_tools", <tool>, params)` | Same tools as MCP via hierarchical dispatch; may attach `request_id` |

## Production contract (target)

Every surface must eventually:

1. **Create** a graph with a durable identity (`graph_id` / `kg://…` URI, branch, revision).
2. **Add** entities/relationships with kwargs matching `storage.types.Entity` / `Relationship`.
3. **Query** with a JSON-serializable result envelope (`status`, `query`, `results`, …).
4. **Reopen** the same graph from identity without ambient process caches.
5. **Transact** with begin/commit/rollback that survive independent calls (shared catalog/service).

## Observed drift inventory

### KGP-001-CREATE-GRAPH — missing `create_graph`

| Surface | Call | Observed |
| --- | --- | --- |
| Python | `KnowledgeGraphManager.create_graph` | **Missing.** Manager exposes `initialize()` only. |
| CLI | `graph create` → `manager.create_graph` | **AttributeError** (`'KnowledgeGraphManager' object has no attribute 'create_graph'`). CLI catches the exception, prints traceback-ish error text, and may still exit **0**. |
| MCP | `graph_create` → `manager.initialize()` | **Shallow success** (`status=success`, `driver_url`). No durable graph id / branch / revision. |
| MCP++ | `tools_dispatch(..., "graph_create")` | Same as MCP; may include `request_id`. |

**Root cause:** CLI and docs (`docs/CORE_OPERATIONS_GUIDE.md`) still name `create_graph`; core manager never implemented it (or renamed to `initialize` without updating callers).

### KGP-001-ENTITY-SIG — `Entity` constructor mismatch

| Surface | Call | Observed |
| --- | --- | --- |
| Python / CLI / MCP / MCP++ | `add_entity` | **Error** envelope: `Entity.__init__() got an unexpected keyword argument 'id'`. |

Manager constructs:

```python
Entity(id=entity_id, type=entity_type, properties=properties)
```

Canonical storage signature:

```python
Entity(entity_id=None, entity_type="entity", name="", properties=None, ...)
```

### KGP-001-REL-SIG — `Relationship` constructor mismatch (new drift)

| Surface | Call | Observed |
| --- | --- | --- |
| Python / CLI / MCP / MCP++ | `add_relationship` | **Error** envelope: `Relationship.__init__() got an unexpected keyword argument 'type'`. |

Manager uses `type=relationship_type`; storage type requires `relationship_type=`.

### KGP-001-QUERY-JSON — non-JSON query results

| Surface | Call | Observed |
| --- | --- | --- |
| Python / MCP / MCP++ | `query_cypher` | `status=success` but `results` is `neo4j_compat.result.Result` (**not** JSON serializable). |
| CLI | `graph query --json` | `print_result` → `json.dumps` → **TypeError: Object of type Result is not JSON serializable**. CLI catches and prints error; exit code may still be 0. |

Pretty CLI mode can print `✅ Success!` without serializing `results`, which hides the defect.

### KGP-001-FRESH-MANAGER — per-call manager / state loss

| Surface | Pattern | Observed |
| --- | --- | --- |
| MCP | Each `graph_*` tool does `manager = KnowledgeGraphManager(...)` | No shared in-process graph, transaction, or session. |
| MCP++ | Dispatch invokes the same tools | Same isolation; write-then-query and begin-then-commit cannot share state. |
| CLI | New process per command | Would require durable catalog/storage; currently no durable graph head. |
| Python | New `KnowledgeGraphManager()` | In-memory `_transaction` and driver are instance-local; no catalog reopen. |

### KGP-001-TX-CTOR — `TransactionManager` construction failure

| Surface | Call | Observed |
| --- | --- | --- |
| Python / CLI / MCP / MCP++ | `transaction_begin` | **Error**: `TransactionManager.__init__() missing 2 required positional arguments: 'graph_engine' and 'storage_backend'`. The `ImportError` mock-UUID fallback never runs because the import succeeds. |
| Commit after independent begin | `transaction_commit` | **Error**: `No active transaction` (fresh manager has `_transaction is None` and no durable tx log). |

### KGP-001-CLI-METHOD-DRIFT — CLI vs manager method names (new drift)

| CLI subcommand | CLI call | Manager method that exists |
| --- | --- | --- |
| `graph create` | `create_graph` | `initialize` only |
| `graph search` | `search_hybrid` | `hybrid_search` |
| `graph index` | `create_index` | `index_create` |
| `graph constraint` | `add_constraint` | `constraint_add` |

### KGP-001-NO-GRAPH-ID — no durable graph identity

Even when `initialize` / MCP `graph_create` returns `status=success`, the envelope
has only `message` + `driver_url`. There is no:

- `graph_id` / `kg://tenant/graph` URI  
- branch head or revision CID  
- storage profile / catalog record  

Reopen therefore cannot target a stable graph; ambient process state is required
and is discarded on every CLI/MCP call.

## Operation × surface matrix

Legend: **PASS** = meets production assertion today · **FAIL** = fails production assertion (strict xfail in probes) · **SHALLOW** = returns success without durability/identity.

| Operation | Python | CLI | MCP | MCP++ |
| --- | --- | --- | --- | --- |
| create | FAIL (`create_graph` missing; `initialize` SHALLOW) | FAIL (`create_graph` AttributeError; exit may be 0) | SHALLOW (`initialize`) | SHALLOW (`initialize` + `request_id`) |
| add entity | FAIL (Entity kwargs) | FAIL (Entity kwargs) | FAIL (Entity kwargs) | FAIL (Entity kwargs) |
| add relationship | FAIL (Relationship kwargs) | FAIL (same path) | FAIL (same path) | FAIL (same path) |
| query (JSON envelope) | FAIL (`Result` not JSON) | FAIL (`TypeError` on `--json`) | FAIL (`Result` not JSON) | FAIL (`Result` not JSON) |
| reopen / independent write→read | FAIL (no durable identity + add broken) | FAIL (process-local) | FAIL (fresh manager) | FAIL (fresh manager) |
| transaction begin | FAIL (TransactionManager ctor) | FAIL (same) | FAIL (same) | FAIL (same) |
| transaction begin→commit independent | FAIL (ctor + fresh manager) | FAIL | FAIL | FAIL |
| search / index / constraint | method names OK on manager | FAIL (wrong method names) | N/A / separate tools | N/A / separate tools |

## Issue IDs used in tests

| Issue ID | Marker reason constant | Primary defect |
| --- | --- | --- |
| `KGP-001-CREATE-GRAPH` | `ISSUE_MISSING_CREATE_GRAPH` | Missing `create_graph` / CLI call site |
| `KGP-001-ENTITY-SIG` | `ISSUE_ENTITY_SIGNATURE` | `Entity(id=, type=)` vs storage signature |
| `KGP-001-REL-SIG` | `ISSUE_RELATIONSHIP_SIGNATURE` | `Relationship(type=)` vs `relationship_type` |
| `KGP-001-QUERY-JSON` | `ISSUE_QUERY_NON_JSON` | Non-JSON `Result` in query envelopes |
| `KGP-001-FRESH-MANAGER` | `ISSUE_FRESH_MANAGER` | Per-call manager; no shared durable service |
| `KGP-001-TX-CTOR` | `ISSUE_TX_MANAGER_CTOR` | `TransactionManager()` arity / wiring |
| `KGP-001-CLI-METHOD-DRIFT` | `ISSUE_CLI_METHOD_DRIFT` | CLI method names ≠ manager methods |
| `KGP-001-NO-GRAPH-ID` | `ISSUE_NO_DURABLE_GRAPH_ID` | No durable graph identity on create |

When a later task fixes a defect, the corresponding strict xfail should **XPASS** and
fail the suite until the marker is removed — that is intentional.

## Validation

```bash
python -m pytest -q tests/knowledge_graphs/contract/test_public_lifecycle.py
```

Expected: all aspirational lifecycle probes either **pass** (inventory / shallow
create where currently true) or **xfail** (known issues). No bare “accept any
exit code 1” assertions.

## Out of scope for KGP-001

- Fixing production code under `ipfs_datasets_py/**` (later KGP tasks).
- Full UCAN / MCP++ authorization matrix (KGP-G070).
- Corpus inventory (KGP-002).
- GraphService / catalog implementation (KGP-003+).

## Evidence notes (2026-07-29 tree)

Direct smoke against this worktree:

1. CLI `graph create` → AttributeError on `create_graph` (message on stdout/stderr).
2. CLI / Python / MCP `add-entity` → Entity unexpected keyword `id`.
3. Python / MCP `query_cypher` → `Result(records=0, …)` not JSON serializable.
4. CLI `graph query --json` → TypeError inside `print_result`.
5. MCP/MCP++ sources each instantiate `KnowledgeGraphManager(...)`.
6. `transaction_begin` → TransactionManager missing `graph_engine` / `storage_backend`.
7. CLI also calls `search_hybrid` / `create_index` / `add_constraint` (absent on manager).
