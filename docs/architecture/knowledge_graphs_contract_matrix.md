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
| **Legacy compatibility adapters** | `kg_legacy_compat` | **No** | Deprecated `KnowledgeGraphManager`, root `ipfs_datasets_cli.py`, and `driver_url` MCP call shapes routed to the canonical service |

Production expectations for the release-eligible path are encoded as **strict
passing** assertions (no skips, no expected failures). Legacy diagnostics also
pass, but remain compatibility evidence and **must not** be cited as canonical
release proof.

KGP-001 baseline coverage is **preserved** under `kg_legacy_compat`. KGP-048
added release-eligible GraphService probes; the reconciliation now converts the
recorded manager drift into executable compatibility contracts.

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

## Tier B — Legacy compatibility adapters (not release proof)

### Surfaces (legacy / deprecated)

| Surface | Entry point | Process model |
| --- | --- | --- |
| Python API | `ipfs_datasets_py.core_operations.KnowledgeGraphManager` | Maps `driver_url` to a deterministic legacy `GraphTarget` and canonical durable service |
| Root CLI | `python ipfs_datasets_cli.py graph <subcommand>` | Fresh process using the repaired manager aliases and JSON-safe envelopes |
| Residual MCP / MCP++ calls | Deprecated call shapes supplying `driver_url` instead of `GraphTarget` | Deterministic legacy target on the server-owned service |

Passing tests in this tier prove deprecated calls remain usable. They do **not**
replace the explicit-target lifecycle evidence in Tier A.

### Reconciled KGP-001 drift inventory

| Former defect | Reconciled behavior |
| --- | --- |
| Missing `create_graph` | Manager and root CLI expose `create_graph`; the result includes tenant, graph ID, URI, branch, and revision. |
| Entity / relationship signature drift | Manager constructs the current storage types with `entity_id`, `entity_type`, and `relationship_type`. |
| Non-JSON query result | Manager, root CLI, MCP, and MCP++ return JSON-safe row lists. |
| Fresh manager / transaction state | Independent managers for the same `driver_url` share one canonical service; MCP calls use the server registry. |
| `TransactionManager()` constructor drift | Deprecated begin/commit/rollback delegate to `GraphService` transactions. |
| Root CLI method-name drift | `search_hybrid`, `create_index`, and `add_constraint` compatibility aliases are present. |
| Missing durable identity | `driver_url` deterministically maps to `kg://legacy/driver-<digest>/branches/main`. |
| MCP no-target legacy calls | Supplying deprecated `driver_url` is an explicit compatibility signal; calls without either `target` or `driver_url` still fail closed. |

### Operation × surface matrix (legacy compatibility)

| Operation | Manager Python | Root CLI | MCP / MCP++ with `driver_url` |
| --- | --- | --- | --- |
| create / reopen | PASS | PASS | N/A (create uses explicit target) |
| add entity / relationship | PASS | PASS | PASS |
| query (JSON envelope) | PASS | PASS | PASS |
| transaction begin/commit | PASS | PASS | PASS |
| search / index / constraint aliases | PASS | PASS | N/A |

### Legacy probe classes (KGP-001 coverage retained)

| Class | Role |
| --- | --- |
| `TestDriftInventory` | Compatibility wiring and signature inventory |
| `TestPythonLifecycle` | Deprecated manager lifecycle |
| `TestCLILifecycle` | Root CLI compatibility |
| `TestMCPLifecycle` | Deprecated `driver_url` MCP calls |
| `TestMCPPlusLifecycle` | Deprecated `driver_url` MCP++ dispatch |
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

**Expected:** all 133 G010 tests pass with no skips or expected failures.
`kg_release_eligible` remains the only lifecycle release-proof tier;
`kg_legacy_compat` demonstrates migration safety for deprecated callers.

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
