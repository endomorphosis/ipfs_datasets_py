# Knowledge Graphs Public Lifecycle Contract Matrix

**Program:** `KGP`  
**Tasks:** `KGP-001` (baseline capture) · `KGP-048` (reconcile legacy diagnostics with canonical service)  
**Date:** 2026-07-30  
**Executable probes:** `tests/knowledge_graphs/contract/test_public_lifecycle.py`  
**Plan reference:** `docs/architecture/KNOWLEDGE_GRAPHS_PRODUCTION_HARDENING_PLAN_2026_07_29.md`

This matrix distinguishes **two evidence tiers**. They must not be conflated when
judging release readiness.

| Tier | Pytest marker | Counts as release proof? | What it covers |
| --- | --- | --- | --- |
| **Canonical conformance** | `kg_release_eligible` | **Yes** | Explicit `GraphTarget` create / write / query / transaction / reopen via Python `Client`, package CLI, MCP, MCP++ |
| **Legacy compatibility debt** | `kg_legacy_compat` | **No** | Deprecated `KnowledgeGraphManager` and root `ipfs_datasets_cli.py` observations (KGP-001 inventory + strict xfails) |

Production expectations for the release-eligible path are encoded as **strict
passing** assertions (no skips, no expected failures). Legacy diagnostics either
lock observed debt as facts or use issue-linked
`pytest.mark.xfail(strict=True)` markers; those outcomes document residual
manager drift and **must not** be cited as passing release proof.

KGP-001 baseline coverage is **preserved** under `kg_legacy_compat`. KGP-048
**adds** release-eligible GraphService probes; it does not delete or weaken the
legacy inventory.

---

## Tier A — Canonical conformance (release-eligible)

### Surfaces (canonical)

| Surface | Entry point | Process model |
| --- | --- | --- |
| Python API | `ipfs_datasets_py.knowledge_graphs.Client` + `GraphTarget` | Durable catalog + payload store; fresh `Client` reopens committed graphs |
| CLI | `python -m ipfs_datasets_py.ipfs_datasets_cli graph …` | Fresh process per invocation; `--catalog` / `--store` required for durability |
| MCP | `ipfs_datasets_py.mcp_server.tools.graph_tools.*` | Server-owned `GraphService` via `resolve_binding` (shared registry + paths) |
| MCP++ | `tools_dispatch("graph_tools", <tool>, params)` | Same tools as MCP; may attach `request_id` |

### Production contract (enforced, release-eligible)

Every canonical surface must:

1. **Create** a graph with an explicit `GraphTarget` and durable identity (`graph_id`, branch, revision, `kg://…` URI).
2. **Write** entities/relationships through the GraphService mutation path (JSON-safe lifecycle envelope).
3. **Query** with a JSON-serializable lifecycle envelope (`contract_version`, `status`, `operation`, `target`, `result` with rows/revision).
4. **Transact** with begin → stage write → commit that preserve transaction identity on the shared service/catalog.
5. **Reopen** the same graph from catalog/storage paths without ambient empty-graph construction.

Envelope shape: `contract_version == kg-service-contract/v1`, `status == success`,
JSON-safe end-to-end.

### Operation × surface matrix (canonical)

Legend: **PASS** = meets production assertion in `kg_release_eligible` probes.

| Operation | Python Client | Package CLI | MCP | MCP++ |
| --- | --- | --- | --- | --- |
| create (`GraphTarget`) | PASS | PASS | PASS | PASS |
| write / add entity | PASS | PASS | PASS | PASS |
| query (JSON envelope) | PASS | PASS | PASS | PASS |
| transaction begin → stage → commit | PASS | PASS | PASS | PASS |
| reopen (fresh client / process / tool call) | PASS | PASS | PASS | PASS |
| lifecycle tools use server-owned GraphService | N/A (Client owns service) | N/A | PASS (source probe) | PASS (same tools) |

### Release-eligible probe classes

| Class | Surface |
| --- | --- |
| `TestCanonicalPythonLifecycle` | Python `Client` |
| `TestCanonicalCLILifecycle` | Package CLI |
| `TestCanonicalMCPLifecycle` | MCP tools |
| `TestCanonicalMCPPlusLifecycle` | MCP++ dispatch |
| `TestCanonicalCrossSurfaceParity` | Create parity + GraphService wiring |

Filter:

```bash
python -m pytest -q tests/knowledge_graphs/contract/test_public_lifecycle.py -m kg_release_eligible
```

---

## Tier B — Legacy compatibility debt (not release proof)

### Surfaces (legacy / deprecated)

| Surface | Entry point | Process model |
| --- | --- | --- |
| Python API | `ipfs_datasets_py.core_operations.KnowledgeGraphManager` | In-process, no durable GraphTarget catalog |
| Root CLI | `python ipfs_datasets_cli.py graph <subcommand>` | Fresh process; still calls manager methods that do not exist or mismatch storage types |
| Residual MCP / MCP++ no-target calls | Stale call shapes without explicit `GraphTarget` | Fail / xfail; not the canonical lifecycle path |

Passing tests in this tier are **compatibility observations**. They prove the
debt is still visible and issue-linked; they do **not** prove release readiness.

### Observed drift inventory (manager / root CLI)

#### KGP-001-CREATE-GRAPH — missing `create_graph`

| Surface | Call | Observed |
| --- | --- | --- |
| Python | `KnowledgeGraphManager.create_graph` | **Missing.** Manager exposes `initialize()` only. |
| Root CLI | `graph create` → `manager.create_graph` | **AttributeError** (`'KnowledgeGraphManager' object has no attribute 'create_graph'`). CLI may still exit **0**. |
| Canonical MCP / package CLI | GraphService `create` | **Out of scope for this tier** — covered as PASS under Tier A. |

**Root cause:** Root CLI and older docs still name `create_graph`; core manager
never implemented it (or renamed to `initialize` without updating callers).

#### KGP-001-ENTITY-SIG — `Entity` constructor mismatch

| Surface | Call | Observed |
| --- | --- | --- |
| Manager / root CLI | `add_entity` | **Error** envelope: `Entity.__init__() got an unexpected keyword argument 'id'`. |

Manager constructs `Entity(id=…, type=…)`; storage requires
`Entity(entity_id=…, entity_type=…, name=…)`.

#### KGP-001-REL-SIG — `Relationship` constructor mismatch

| Surface | Call | Observed |
| --- | --- | --- |
| Manager | `add_relationship` | **Error** envelope: unexpected keyword argument `type`. |

Manager uses `type=relationship_type`; storage type requires `relationship_type=`.

#### KGP-001-QUERY-JSON — non-JSON query results

| Surface | Call | Observed |
| --- | --- | --- |
| Manager | `query_cypher` | `status=success` but `results` is `neo4j_compat.result.Result` (**not** JSON serializable). |
| Root CLI | `graph query --json` | `print_result` → **TypeError** on non-JSON `Result`. |

#### KGP-001-FRESH-MANAGER — no shared durable service

Manager instances and root CLI processes do not share a GraphTarget catalog;
writes/transactions/reopen cannot meet the production durability contract on
this path. (Canonical MCP tools now use server-owned GraphService — Tier A.)

#### KGP-001-TX-CTOR — `TransactionManager` construction failure

| Surface | Call | Observed |
| --- | --- | --- |
| Manager / root CLI | `transaction_begin` | **Error**: missing `graph_engine` and `storage_backend`. |

#### KGP-001-CLI-METHOD-DRIFT — root CLI vs manager method names

| Root CLI subcommand | CLI call | Manager method that exists |
| --- | --- | --- |
| `graph create` | `create_graph` | `initialize` only |
| `graph search` | `search_hybrid` | `hybrid_search` |
| `graph index` | `create_index` | `index_create` |
| `graph constraint` | `add_constraint` | `constraint_add` |

#### KGP-001-NO-GRAPH-ID — no durable graph identity on manager create

`initialize` success envelopes carry `message` + `driver_url` only — no
`graph_id` / branch / revision / catalog record.

### Operation × surface matrix (legacy debt)

Legend: **DEBT** = fails production assertion (observation or strict xfail) ·
**OBS** = inventory observation locked as a passing fact · **N/A** = not this surface.

| Operation | Manager Python | Root CLI | Notes |
| --- | --- | --- | --- |
| create | DEBT / OBS | DEBT / OBS | Missing `create_graph`; `initialize` SHALLOW |
| add entity | DEBT | DEBT | Entity kwargs mismatch |
| add relationship | DEBT | DEBT | Relationship kwargs mismatch |
| query (JSON envelope) | DEBT | DEBT | Non-JSON `Result` |
| reopen / write→read | DEBT | DEBT | No durable GraphTarget identity |
| transaction begin/commit | DEBT | DEBT | TransactionManager ctor + no shared catalog |
| search / index / constraint | method names OK on manager | DEBT | Root CLI wrong method names |

### Issue IDs used in legacy probes

| Issue ID | Marker reason constant | Primary defect | Release proof? |
| --- | --- | --- | --- |
| `KGP-001-CREATE-GRAPH` | `ISSUE_MISSING_CREATE_GRAPH` | Missing `create_graph` / root CLI call site | **No** |
| `KGP-001-ENTITY-SIG` | `ISSUE_ENTITY_SIGNATURE` | `Entity(id=, type=)` vs storage signature | **No** |
| `KGP-001-REL-SIG` | `ISSUE_RELATIONSHIP_SIGNATURE` | `Relationship(type=)` vs `relationship_type` | **No** |
| `KGP-001-QUERY-JSON` | `ISSUE_QUERY_NON_JSON` | Non-JSON `Result` in manager query envelopes | **No** |
| `KGP-001-FRESH-MANAGER` | `ISSUE_FRESH_MANAGER` | Per-instance manager; no shared durable service | **No** |
| `KGP-001-TX-CTOR` | `ISSUE_TX_MANAGER_CTOR` | `TransactionManager()` arity / wiring | **No** |
| `KGP-001-CLI-METHOD-DRIFT` | `ISSUE_CLI_METHOD_DRIFT` | Root CLI method names ≠ manager methods | **No** |
| `KGP-001-NO-GRAPH-ID` | `ISSUE_NO_DURABLE_GRAPH_ID` | No durable graph identity on manager create | **No** |

All issue reason strings are prefixed with `LEGACY-COMPAT` in the probe module so
CI logs never look like release-eligible failures.

When a later task fixes a manager defect, the corresponding strict xfail should
**XPASS** and fail the suite until the marker is removed — that is intentional
for debt tracking only.

### Legacy probe classes (KGP-001 coverage retained)

| Class | Role |
| --- | --- |
| `TestDriftInventory` | Passing inventory facts (debt locks) |
| `TestPythonLifecycle` | Strict xfail / shallow manager Python paths |
| `TestCLILifecycle` | Root CLI debt probes |
| `TestMCPLifecycle` | Residual / partial MCP inventory (not full release lifecycle) |
| `TestMCPPlusLifecycle` | Residual MCP++ no-target paths |
| `TestCrossSurfaceParity` | Legacy cross-surface parity vectors |
| `TestEntityConstructionContract` | Entity/Relationship signature debt locks |

Filter:

```bash
python -m pytest -q tests/knowledge_graphs/contract/test_public_lifecycle.py -m kg_legacy_compat
```

---

## Validation

Full contract file (both tiers):

```bash
python -m pytest -q tests/knowledge_graphs/contract/test_public_lifecycle.py
```

Release-eligible slice only:

```bash
python -m pytest -q tests/knowledge_graphs/contract/test_public_lifecycle.py -m kg_release_eligible
```

Broader KGP-048 validation set (canonical surfaces + conformance):

```bash
python -m pytest -q \
  tests/knowledge_graphs/contract/test_public_lifecycle.py \
  tests/knowledge_graphs/conformance \
  tests/cli/test_graph_commands.py \
  tests/mcp/test_graph_tools.py
```

**Expected for release proof:** every `kg_release_eligible` test **passes** with
no skips and no expected failures. Legacy `kg_legacy_compat` tests may pass as
observations or xfail as debt; neither outcome is counted as GraphService
lifecycle release proof.

---

## Out of scope

- Treating root `ipfs_datasets_cli.py` or `KnowledgeGraphManager` as the
  canonical public lifecycle surface.
- Claiming legacy inventory passes as production readiness.
- Deleting or weakening KGP-001 debt coverage.
- Full UCAN / MCP++ authorization matrix (KGP-G070).
- Corpus inventory (KGP-002).
- Editing protected plan / objectives / todo board files.

## Evidence notes

### Canonical (2026-07-30 / KGP-048)

1. Python `Client.open` + `GraphTarget` create → write → query → begin_tx →
   stage → commit_tx → fresh-client open/query succeeds with durable revision.
2. Package CLI `graph create|write|query|transaction|open` with `--catalog` /
   `--store` round-trips identity across processes.
3. MCP / MCP++ lifecycle tools resolve `binding.service.*` (no per-call
   `KnowledgeGraphManager` on create/write/query/tx tools) and preserve state
   via registry + catalog paths.
4. Cross-surface create parity yields `kg-service-contract/v1` success envelopes
   with `graph_id` + `revision` on Python, CLI, MCP, and MCP++.

### Legacy (retained from KGP-001; still debt)

1. Root CLI `graph create` → AttributeError on `create_graph`.
2. Manager / root CLI `add-entity` → Entity unexpected keyword `id`.
3. Manager `query_cypher` → non-JSON `Result`.
4. Manager `transaction_begin` → TransactionManager missing ctor args.
5. Root CLI method-name drift for search / index / constraint.
6. Stale MCP/MCP++ calls without `GraphTarget` remain issue-linked xfails under
   `kg_legacy_compat` and are not counted as release proof.
