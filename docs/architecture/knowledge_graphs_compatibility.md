# Knowledge Graphs Compatibility ADR

**Program:** `KGP`  
**Task:** `KGP-003` — Ratify the canonical API, identity, and compatibility ADR  
**Status:** Accepted  
**Date:** 2026-07-29  
**Policy version:** `kg-compatibility/v1`  
**Depends on:** KGP-001, KGP-002  
**Companion:** `docs/architecture/knowledge_graphs_service_contract.md`  
**Plan:** `docs/architecture/KNOWLEDGE_GRAPHS_PRODUCTION_HARDENING_PLAN_2026_07_29.md`

This ADR defines **compatibility tiers**, the **adopt / adapt / deprecate**
disposition of legacy graph implementations, warning/removal windows, and the
rule that no producer migrates before its evidence gate passes.

---

## 1. Decision summary

1. Production traffic uses **`GraphService` + `GraphTarget`** only
   (`knowledge_graphs_service_contract.md`).
2. Existing modules are classified **adopt**, **adapt**, or **deprecate**—never
   silently rewritten in place.
3. Compatibility tiers (`T0`–`T3`) describe what callers may rely on during the
   hardening program.
4. Deprecations emit versioned warnings and keep **read paths** until a removal
   gate; destructive conversion in place is forbidden.

---

## 2. Compatibility tiers

| Tier | Name | Meaning | Who may use it |
| --- | --- | --- | --- |
| **T0** | Canonical contract | `GraphTarget`, lifecycle envelopes, typed errors, JSON-safe query envelope, `GraphService` | All new Python / CLI / MCP / MCP++ production code |
| **T1** | Supported adapter | Legacy type kept as a **delegate** behind GraphService or a corpus adapter; stable enough for dual-run | Internal adapters; shadow/canary reads |
| **T2** | Compatibility shim | Public import still works; emits `DeprecationWarning`; maps into T0 where possible | Existing callers during migration windows |
| **T3** | Fixture / legacy only | Not a production catalog; tests, offline tools, nested checkouts, or historical IPLD layouts | Tests, inventory fixtures, one-off migration |

**Rules:**

| Rule ID | Statement |
| --- | --- |
| `TIER-1` | New public APIs **must** be T0. |
| `TIER-2` | T1 modules **must not** invent durable graph identity outside the catalog. |
| `TIER-3` | T2 shims **must** warn on import or first use and document the T0 replacement. |
| `TIER-4` | T3 paths **must not** be selected by ambient MCP/CLI defaults. |
| `TIER-5` | Cross-surface conformance vectors run only against T0 behavior. |

---

## 3. Adopt / adapt / deprecate vocabulary

| Disposition | Definition | Typical actions |
| --- | --- | --- |
| **Adopt** | Keep algorithm, format, or module as a first-class building block of the new stack | Move behind a protocol; extend; cover with shared contracts |
| **Adapt** | Keep valuable logic but change boundaries, identity, or serialization to match T0 | Wrap with adapter; map types to manifests/envelopes; fix signatures |
| **Deprecate** | Stop promoting as public production API; schedule removal after gates | Warning, shim to GraphService, docs, eventual delete |

A component may be **adopt** for one aspect and **deprecate** for another
(e.g. adopt sharded-CAR reader, deprecate process-local manager façade).

---

## 4. Mandatory legacy map

The following five legacies are **in scope for KGP-003** and must remain
explicitly classified as the control plane evolves.

### 4.1 Summary table

| Legacy component | Primary path(s) | Disposition | Tier | T0 replacement |
| --- | --- | --- | --- | --- |
| **GraphEngine** | `ipfs_datasets_py/knowledge_graphs/core/graph_engine.py` | **Adapt** | T1 → T0 delegate | Query/write engine behind `GraphService` (not a catalog) |
| **extraction KnowledgeGraph** | `ipfs_datasets_py/knowledge_graphs/extraction/graph.py` (`KnowledgeGraph`) | **Adapt** | T1 (domain model) | Extraction → publish revision via service/adapters |
| **data_transformation IPLD graph** | `ipfs_datasets_py/processors/storage/ipld/knowledge_graph.py` (migrated from `data_transformation.ipld`); related `knowledge_graphs/ipld.py` `IPLDKnowledgeGraph` | **Adapt** (codec/storage ideas) + **Deprecate** (public graph identity / ambient KG) | T1 storage / T2–T3 public | `GraphStore` profiles `ipfs_ipld` / `ipfs_kit` + manifests |
| **search GraphData / sharded CAR** | Migration DTO `knowledge_graphs/migration/formats.py` `GraphData`; sharded reader `search/graph_query/backends/sharded_car.py` `ShardedCARBackend` + `search/graph_query/sharded_car/*` | **Adopt** (sharded CAR v1 reader/publisher) + **Adapt** (v2 manifest, GraphData as import DTO) | T1 | Unified query backend + v1/v2 shard manifests under GraphService |
| **KnowledgeGraphManager** | `ipfs_datasets_py/core_operations/knowledge_graph_manager.py` | **Deprecate** | T2 shim → remove | `GraphService` + versioned Client/AsyncClient |

### 4.2 GraphEngine — **Adapt**

| Aspect | Detail |
| --- | --- |
| Why it exists | Low-level node/relationship CRUD and traversal for neo4j-compat and query execution |
| What to keep | In-memory CRUD, path helpers, integration hooks for storage backends |
| What must change | Must not be the public multi-graph catalog; must not imply durable heads without catalog CAS; wire through service-owned snapshots |
| Forbidden | New CLI/MCP entry points that construct a bare `GraphEngine` as the app graph |
| Exit criteria | All surfaces open graphs via `GraphTarget`; engine receives an explicit snapshot/store handle |

### 4.3 extraction `KnowledgeGraph` — **Adapt**

| Aspect | Detail |
| --- | --- |
| Why it exists | Entity/relationship extraction container with indexes, provenance hooks, diffs |
| What to keep | Extraction-time graph mutation API, validation, visualization helpers |
| What must change | Publishing to production requires mapping entities/relationships into write ops or a manifest-backed import against a `GraphTarget` |
| Forbidden | Treating extraction `name=` as durable `kg://` identity |
| Exit criteria | Extract → adapt → `write`/`import` through GraphService with provenance on the revision |

### 4.4 data_transformation IPLD graph — **Adapt** + **Deprecate** (split)

Historical IPLD knowledge graph code lives under processors storage (migrated
from `data_transformation.ipld`) and `knowledge_graphs/ipld.py`
(`IPLDKnowledgeGraph`). Inventory flags `ipld_legacy_knowledge_graph` as
**high** migration risk.

| Aspect | Disposition | Detail |
| --- | --- | --- |
| Block/chunking, CAR export/import, CID linking | **Adopt / Adapt** | Feed `IPLD` / hybrid `GraphStore` design (KGP-010) |
| Class as app-level graph database / identity | **Deprecate** | Replace with catalog + revision manifests |
| Nested dirty lift copies of the same code | **T3 fixture-only** | Never implementation source of truth (KGP-002) |

### 4.5 search GraphData / sharded CAR — **Adopt** + **Adapt**

| Piece | Disposition | Detail |
| --- | --- | --- |
| `ShardedCARBackend` + v1 hash-modulo manifests | **Adopt** | Starting point for sharded read/publish (plan § Storage / Query) |
| v2 virtual shards / rendezvous / cross-shard adjacency | **Adapt** (extend) | New manifest version; keep v1 readable |
| `GraphData` migration DTO | **Adapt** | Interchange for import/export; not a live multi-tenant catalog |
| Search-only ambient graphs without `GraphTarget` | **Deprecate** | Queries require explicit targets; federation lists targets explicitly |

### 4.6 KnowledgeGraphManager — **Deprecate**

KGP-001 evidence: missing `create_graph`, Entity/Relationship signature drift,
non-JSON query results, per-call MCP managers, broken `TransactionManager`
wiring, no durable graph id.

| Aspect | Detail |
| --- | --- |
| Disposition | **Deprecate** as the public façade |
| Near term | Optional T2 shim that delegates to `GraphService` once KGP-006 exists |
| Replacement | Versioned Client/AsyncClient (plan surfaces track) |
| Removal gate | Conformance vectors green on all four surfaces; shim warning window elapsed |

---

## 5. Extended disposition map (informative)

Other inventory kinds inherit the same vocabulary; full migration remains
gated per corpus.

| Kind / module | Disposition | Notes |
| --- | --- | --- |
| Platform graph engine stack (`platform_graph_engine`) | Adapt | Critical path under KGP repair |
| neo4j_compat driver/session/result | Adapt | Keep API familiarity; results must project to JSON envelope at service boundary |
| TransactionManager / WAL | Adapt | Replace private-field coupling with public store/catalog protocols |
| IPLDBackend (knowledge_graphs.storage) | Adapt | Protocol for GraphStore; unused namespace must not fake a catalog |
| SkillCenter / CVEfixes / 211 producers | Adopt artifacts as fixtures; Adapt readers | No producer cutover before stage 6 evidence |
| Supervisor objective/AST/code-evidence graphs | Adopt as graph kinds | Owners remain accelerate/supervisor |
| Nested lift `ipfs_datasets_py` checkouts | T3 fixture-only | Dirty trees never canonical |

---

## 6. Warning and removal windows

| Phase | Window (relative) | Behavior |
| --- | --- | --- |
| **Announce** | On merge of KGP-003 ADRs | Docs state disposition; no runtime warning required yet for all paths |
| **Warn** | When T2 shim ships (post GraphService) | `DeprecationWarning` on import or first call; message cites T0 API |
| **Shadow** | Per-corpus after differential tests | Read dual-path; production write still legacy or dual-write only where safe |
| **Canary** | Selected graph ids | Catalog head points at new revisions; rollback = move head to last verified revision |
| **Remove** | After G060/G080/G100 gates for that surface/corpus | Delete shim or move to `archive/`; tests assert absence from public `__all__` |

Minimum warn period for removed public names: **one minor release** after warn
instrumentation is on by default, unless a security issue requires faster
removal (still needs a receipt).

---

## 7. Migration safety rules (normative)

1. **No in-place destructive conversion** of corpus artifacts.
2. **Producers remain authoritative** until parity evidence passes (plan stage 6).
3. **Fixture-only nested repositories** are never the implementation source of truth.
4. **Identity:** only catalog-backed `kg://` URIs are production graph ids.
5. **Empty graph substitution is forbidden**—queries fail with `NOT_FOUND` /
   `INVALID_TARGET` rather than silently querying an empty engine.
6. **Differential tests** compare old readers vs new adapters before cutover.

---

## 8. One-service rule (compatibility view)

Compatibility policy **does not** allow a second production orchestrator.
Adapters (T1) may wrap GraphEngine, sharded CAR, or IPLD stores, but:

- lifecycle create/open/write/query/transaction enter through `GraphService`;
- MCP/CLI must not keep a parallel durable manager;
- deprecation of `KnowledgeGraphManager` is mandatory, not optional, for T0
  certification.

See service contract §2 for the full rule list (`OSR-1` … `OSR-6`).

---

## 9. Machine-readable disposition map

The following JSON block is normative for tests and future tooling. Keys are
stable legacy ids; values are dispositions and tiers.

```json
{
  "policy_version": "kg-compatibility/v1",
  "one_service_rule": true,
  "canonical_service": "GraphService",
  "canonical_target": "GraphTarget",
  "tiers": ["T0", "T1", "T2", "T3"],
  "dispositions": ["adopt", "adapt", "deprecate"],
  "legacy_map": {
    "graph_engine": {
      "component": "GraphEngine",
      "paths": [
        "ipfs_datasets_py/knowledge_graphs/core/graph_engine.py"
      ],
      "disposition": "adapt",
      "tier": "T1",
      "replacement": "GraphService query/write delegate"
    },
    "extraction_knowledge_graph": {
      "component": "extraction KnowledgeGraph",
      "paths": [
        "ipfs_datasets_py/knowledge_graphs/extraction/graph.py"
      ],
      "disposition": "adapt",
      "tier": "T1",
      "replacement": "extract then publish via GraphService"
    },
    "data_transformation_ipld_graph": {
      "component": "data_transformation IPLD graph",
      "paths": [
        "ipfs_datasets_py/processors/storage/ipld/knowledge_graph.py",
        "ipfs_datasets_py/knowledge_graphs/ipld.py"
      ],
      "disposition": "adapt",
      "secondary_disposition": "deprecate",
      "tier": "T1",
      "public_tier": "T2",
      "replacement": "GraphStore ipfs_ipld/ipfs_kit + manifests"
    },
    "search_graph_data_sharded_car": {
      "component": "search GraphData/sharded CAR",
      "paths": [
        "ipfs_datasets_py/knowledge_graphs/migration/formats.py",
        "ipfs_datasets_py/search/graph_query/backends/sharded_car.py",
        "ipfs_datasets_py/search/graph_query/sharded_car"
      ],
      "disposition": "adopt",
      "secondary_disposition": "adapt",
      "tier": "T1",
      "replacement": "unified query backend + v1/v2 shard manifests"
    },
    "knowledge_graph_manager": {
      "component": "KnowledgeGraphManager",
      "paths": [
        "ipfs_datasets_py/core_operations/knowledge_graph_manager.py"
      ],
      "disposition": "deprecate",
      "tier": "T2",
      "replacement": "GraphService Client/AsyncClient"
    }
  }
}
```

---

## 10. Validation

```bash
python -m pytest -q \
  tests/unit/knowledge_graphs/contracts/test_graph_target.py \
  tests/unit/knowledge_graphs/contracts/test_result_envelope.py
```

Tests assert that this document and the service contract define GraphTarget,
lifecycle envelopes, typed errors, JSON-safe query results, compatibility
tiers, the one-service rule, and the five-way legacy map above.
