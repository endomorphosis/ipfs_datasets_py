# Compatibility Tiers, Legacy Map, and Deprecation Windows

**Policy version:** `kg-compatibility/v1`  
**Executable module:** `ipfs_datasets_py.knowledge_graphs.compat`  
**ADR:** `docs/architecture/knowledge_graphs_compatibility.md`  
**Task:** `KGP-034`

## Compatibility tiers

| Tier | Name | Meaning | Who may use it |
| --- | --- | --- | --- |
| **T0** | Canonical contract | `GraphTarget`, lifecycle envelopes, typed errors, JSON-safe query envelope, `GraphService` / `Client` / `AsyncClient` | All new Python / CLI / MCP / MCP++ production code |
| **T1** | Supported adapter | Legacy type kept as a **delegate** behind GraphService or a corpus adapter; stable enough for dual-run | Internal adapters; shadow/canary reads |
| **T2** | Compatibility shim | Public import still works; emits `DeprecationWarning`; maps into T0 where possible | Existing callers during migration windows |
| **T3** | Fixture / legacy only | Not a production catalog; tests, offline tools, nested checkouts, historical IPLD layouts | Tests, inventory fixtures, one-off migration |

### Tier rules (normative)

| Rule ID | Statement |
| --- | --- |
| `TIER-1` | New public APIs **must** be T0. |
| `TIER-2` | T1 modules **must not** invent durable graph identity outside the catalog. |
| `TIER-3` | T2 shims **must** warn on import or first use and document the T0 replacement. |
| `TIER-4` | T3 paths **must not** be selected by ambient MCP/CLI defaults. |
| `TIER-5` | Cross-surface conformance vectors run only against T0 behavior. |

## Dispositions

| Disposition | Definition | Typical actions |
| --- | --- | --- |
| **adopt** | Keep algorithm, format, or module as a first-class building block | Protocolize; extend; shared contracts |
| **adapt** | Keep valuable logic; change boundaries, identity, or serialization to match T0 | Adapter; map to manifests/envelopes |
| **deprecate** | Stop promoting as public production API; schedule removal after gates | Warning, shim to GraphService, docs, eventual delete |

A component may be **adopt** for one aspect and **deprecate** for another
(e.g. adopt sharded-CAR reader, deprecate process-local manager façade).

## Mandatory legacy map (five-way)

These five legacies are mandatory for KGP-003 / KGP-034 alignment:

| Legacy id | Component | Disposition | Tier | T0 replacement |
| --- | --- | --- | --- | --- |
| `graph_engine` | `GraphEngine` | adapt | T1 | GraphService query/write delegate |
| `extraction_knowledge_graph` | extraction `KnowledgeGraph` | adapt | T1 | extract then publish via GraphService |
| `data_transformation_ipld_graph` | IPLD knowledge graph | adapt (+ deprecate public) | T1 / public T2 | GraphStore `ipfs_ipld` / `ipfs_kit` + manifests |
| `search_graph_data_sharded_car` | GraphData / sharded CAR | adopt (+ adapt) | T1 | unified query backend + v1/v2 shard manifests |
| `knowledge_graph_manager` | `KnowledgeGraphManager` | **deprecate** | T2 | GraphService `Client` / `AsyncClient` |

### Extended public shims

| Legacy id | Component | Disposition | Tier | Removal window |
| --- | --- | --- | --- | --- |
| `legacy_knowledge_graph_extraction_module` | `knowledge_graph_extraction` shim | deprecate | T2 | warn `0.1.0` → remove ≥ `0.2.0` |
| `legacy_root_reexports` | package-root GraphDatabase/GraphEngine re-exports | deprecate | T2 | warn `0.1.0` → remove ≥ `0.2.0` |
| `advanced_knowledge_extractor_shim` | advanced extractor shim | deprecate | T2 | warn `0.1.0` → remove ≥ `0.2.0` |
| `nested_lift_checkout_trees` | nested lift checkouts | deprecate | T3 | fixture-only (never promoted) |

Paths are registered in `compat.LEGACY_MAP` and exported by `policy_dict()`.

## Warning and removal windows

| Phase | Window | Behavior |
| --- | --- | --- |
| **Announce** | From `2026-07-29` (KGP-003 ADR merge) | Docs state disposition; not all paths require runtime warnings yet |
| **Warn** | When T2 shim ships / policy `warn_since_version` | `DeprecationWarning` on import or first use; message cites T0 API |
| **Shadow** | Per-corpus after differential tests | Dual-read; caller always gets primary result |
| **Canary** | Selected `(tenant, graph_id)` pairs | Catalog head points at new revisions; rollback = CAS to last verified head |
| **Remove** | After warn floor **and** G060/G080/G100 gates for that surface/corpus | Delete shim or move to `archive/`; tests assert absence from public `__all__` |

### Policy floors (executable)

| Constant | Value | Meaning |
| --- | --- | --- |
| `PACKAGE_WARN_BASELINE` | `0.1.0` | First package minor that may emit default-on warnings |
| `PACKAGE_MIN_REMOVE_FLOOR` | `0.2.0` | Earliest package minor for default removals |
| `DEFAULT_REMOVAL_EARLIEST` | `2026-10-01` | Calendar floor for default removals |
| `min_warn_minor_releases` | `1` | At least one minor release must separate warn and remove |
| `same_release_warn_and_remove_forbidden` | `true` | **Conflict policy:** never warn and remove in the same release |

```python
from ipfs_datasets_py.knowledge_graphs.compat import removal_allowed

# Same release as first warn → False
assert not removal_allowed("knowledge_graph_manager", package_version="0.1.0")

# One minor later, after calendar floor → True
assert removal_allowed(
    "knowledge_graph_manager",
    package_version="0.2.0",
    calendar_date="2026-10-01",
)

# Security exception (receipt required in change ticket)
assert removal_allowed(
    "knowledge_graph_manager",
    package_version="0.1.1",
    security_receipt=True,
)
```

### Deprecation warning text

```python
from ipfs_datasets_py.knowledge_graphs.compat import warn_legacy, deprecation_message

print(deprecation_message("knowledge_graph_manager"))
warn_legacy("knowledge_graph_manager")  # DeprecationWarning
```

## One-service rule

Compatibility policy **does not** allow a second production orchestrator.
Adapters (T1) may wrap GraphEngine, sharded CAR, or IPLD stores, but:

- lifecycle create/open/write/query/transaction enter through `GraphService`;
- MCP/CLI must not keep a parallel durable manager;
- deprecation of `KnowledgeGraphManager` is **mandatory** for T0 certification.

## Validation

```bash
python -m pytest -q tests/unit/knowledge_graphs/test_compatibility_policy.py
```
