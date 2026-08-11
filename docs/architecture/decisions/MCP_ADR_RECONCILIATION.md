# Package-local MCP ADR Reconciliation

| Field | Value |
| --- | --- |
| Interface | `MCPADRReconciliation@1` |
| Task | `IPFSDOC-016` |
| Status | `canonical` |
| Owner | documentation-governance; architecture; mcp-server maintainers |
| Source of truth | Live package ADR bodies under `ipfs_datasets_py/mcp_server/docs/adr/`; global ADRs ADR-005…ADR-007; [PACKAGE_LOCAL_DOCUMENTATION_MAP.md](../../maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md) §4; [ADR_TEMPLATE.md](ADR_TEMPLATE.md); current MCP implementation |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent, maintainer |
| Goal | `IPFSDOC-G032` |
| Companion index | [README.md](README.md) |
| Non-goals | This document does **not** rewrite, relocate, recreate, renumber, or delete package-local ADR files. It maps disposition only. |

## Purpose

Six accepted Architecture Decision Records already live under the MCP package:

```text
ipfs_datasets_py/mcp_server/docs/adr/
  ADR-001-thin-wrapper-pattern.md
  ADR-002-dual-runtime.md
  ADR-003-hierarchical-tool-system.md
  ADR-004-engine-extraction-pattern.md
  ADR-005-v6-coverage-hardening.md
  ADR-006-mcp++-alignment.md
```

They predate the global `docs/architecture/decisions/` corpus and use a
**package-local number space**. Global ADR-001…ADR-007 are a **different**
namespace. This reconciliation:

1. **Indexes** each package-local ADR from the product decision hub.
2. Assigns each a **disposition** from the vocabulary below (refresh, canonical
   pointer, merge, or historical).
3. Records **evidence**, **related global ADRs**, and **non-actions** so agents
   preserve history instead of inventing a second body.

Authority inventory that deferred this work:
[PACKAGE_LOCAL_DOCUMENTATION_MAP.md](../../maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md)
§4 (“Later reconciliation (IPFSDOC-016)”).

---

## Disposition vocabulary

Every package-local MCP ADR receives exactly one **primary** disposition.
Secondary notes may refine sub-claims (for example, evidence-dated metrics)
without changing the primary label.

| Disposition | May be cited as decision authority? | Meaning | Typical next step |
| --- | --- | --- | --- |
| **`canonical-pointer`** | **Yes** (scoped concern) | Package body remains the decision record for its concern. Global index and related global ADRs **point** to that path. No full-body copy under `docs/architecture/decisions/`. | Keep body fresh against code; link from [README.md](README.md); do not duplicate text |
| **`refresh`** | After claims re-verified | Decision is still accepted, but specific claims (metrics, profile readiness, phase banners) need re-measurement before citation as current fact. Body stays in place. | Re-measure or mark evidence-dated; update exposition guides, not silent ADR rewrite |
| **`merge`** | Partial (see mapping row) | Product-level framing for the same concern is elevated into a **global** ADR (Origin / Related artifacts), while the package body is retained as the detailed or historical decision record. Bodies are **not** text-merged into one file. | Cite global ADR for product framing; package ADR for MCP-specific detail; never delete either without supersession |
| **`historical`** | **No** as evergreen fact | Content is retained for audit trail (phase metrics, dated campaign results). Structural decision may still be accepted; only the **historical claim class** is demoted. | Preserve file; do not restate phase percentages as current product status |

These labels align with
[PACKAGE_LOCAL_DOCUMENTATION_MAP.md](../../maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md)
disposition vocabulary (`canonical`, `refresh-and-surface`, `pointer`,
`historical`) and the acceptance criteria for IPFSDOC-016 (`refresh`,
`canonical pointer`, `merge`, `historical disposition`).

### What is explicitly **not** done

| Forbidden action | Why |
| --- | --- |
| Independently recreate package ADR bodies under `docs/architecture/decisions/` | Creates dual sources of truth and drift |
| Delete or archive package ADRs in this task | History and evidence must be preserved |
| Silently supersede package ADRs by rewriting global ADR text | Supersession requires Status + Superseded by on the affected ADR |
| Reuse package numbers as global ADR numbers | Namespaces are path-scoped (see §Numbering) |
| Treat static tool counts or coverage % inside ADRs as evergreen | Rank below tests/implementation ([SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md)) |

---

## Numbering and namespace

| Namespace | Home | Current range | Rule |
| --- | --- | --- | --- |
| **Global** | `docs/architecture/decisions/ADR-NNN-*.md` | ADR-001 … ADR-007 accepted | Next free global number for new product ADRs |
| **Package-local MCP** | `ipfs_datasets_py/mcp_server/docs/adr/ADR-NNN-*.md` | MCP ADR-001 … ADR-006 accepted | Keep existing numbers; do not renumber to “match” global |

**Collision example (intentional):** global [ADR-007](ADR-007-MCP-RUNTIME-COMPATIBILITY.md)
(MCP runtime compatibility) is **not** package MCP ADR-006 (MCP++ alignment).
Always qualify as “global ADR-00N” or “package MCP ADR-00N” / full path.

When a future task **promotes** a package ADR into the global series, either:

- keep the package path as Origin and assign a **new** global number, or  
- leave the package body as `canonical-pointer` and add only framing ADRs

—per [INFORMATION_ARCHITECTURE.md](../../maintenance/INFORMATION_ARCHITECTURE.md)
§7.3. This reconciliation does **not** promote or renumber.

---

## Reconciliation matrix (all six)

| Package ADR | Title | Stated Status | Date | Owner (Author) | Primary disposition | Related global ADR(s) | Superseded by |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [MCP ADR-001](../../../ipfs_datasets_py/mcp_server/docs/adr/ADR-001-thin-wrapper-pattern.md) | Thin Wrapper Pattern | accepted | 2026-02-20 | MCP Server Team | **`canonical-pointer`** | [ADR-005](ADR-005-REGISTRIES-AND-ADAPTERS.md), [ADR-007](ADR-007-MCP-RUNTIME-COMPATIBILITY.md) | none |
| [MCP ADR-002](../../../ipfs_datasets_py/mcp_server/docs/adr/ADR-002-dual-runtime.md) | Dual-Runtime Architecture (FastAPI + Trio) | accepted | 2026-02-18 | MCP Server Team | **`canonical-pointer`** | [ADR-007](ADR-007-MCP-RUNTIME-COMPATIBILITY.md) (frames; does **not** supersede) | none |
| [MCP ADR-003](../../../ipfs_datasets_py/mcp_server/docs/adr/ADR-003-hierarchical-tool-system.md) | Hierarchical Tool System | accepted | 2026-02-19 | MCP Server Team | **`canonical-pointer`** | [ADR-005](ADR-005-REGISTRIES-AND-ADAPTERS.md), [ADR-007](ADR-007-MCP-RUNTIME-COMPATIBILITY.md) | none |
| [MCP ADR-004](../../../ipfs_datasets_py/mcp_server/docs/adr/ADR-004-engine-extraction-pattern.md) | Engine Extraction Pattern | accepted | 2026-02-20 | MCP Server Team | **`canonical-pointer`** | [ADR-005](ADR-005-REGISTRIES-AND-ADAPTERS.md), [ADR-006](ADR-006-PROCESSOR-LAYERING.md) | none |
| [MCP ADR-005](../../../ipfs_datasets_py/mcp_server/docs/adr/ADR-005-v6-coverage-hardening.md) | v6 Coverage Hardening & Ecosystem Integrations | accepted | 2026-02-22 | MCP Server Team | **`refresh`** | [ADR-002](ADR-002-LAZY-OPTIONAL-CAPABILITIES.md), [ADR-007](ADR-007-MCP-RUNTIME-COMPATIBILITY.md) | none |
| [MCP ADR-006](../../../ipfs_datasets_py/mcp_server/docs/adr/ADR-006-mcp++-alignment.md) | MCP++ Specification Alignment | accepted | 2026-02-22 | MCP Server Team | **`refresh`** | [ADR-007](ADR-007-MCP-RUNTIME-COMPATIBILITY.md) | none |

**Disposition counts (primary):** `canonical-pointer` × 4; `refresh` × 2;
`merge` × 0 (as primary); `historical` × 0 (as primary). Sub-claim notes below
use `historical` and `merge` where they apply without changing the primary row.

---

## Per-ADR disposition detail

### MCP ADR-001 — Thin Wrapper Pattern → `canonical-pointer`

| Field | Value |
| --- | --- |
| Body | `ipfs_datasets_py/mcp_server/docs/adr/ADR-001-thin-wrapper-pattern.md` |
| Status | accepted |
| Owner | MCP Server Team |
| Primary disposition | **`canonical-pointer`** |
| Supersedes / Superseded by | none / none |

**Decision (preserved summary):** Business logic lives in domain `*_engine`
modules; MCP tool files are thin wrappers (validate, delegate, return).

**Why this disposition:** Still the binding MCP-layer rule for tool thickness.
Global [ADR-005](ADR-005-REGISTRIES-AND-ADAPTERS.md) and
[ADR-007](ADR-007-MCP-RUNTIME-COMPATIBILITY.md) **point** here for “why thin
wrappers / engines” rather than re-deciding the pattern.

**Evidence (current tree, non-exhaustive):**

- `ipfs_datasets_py/mcp_server/tools/` tool modules as dispatch surface
- Package ADR body and `THIN_TOOL_ARCHITECTURE.md` (exposition; ADR outranks)
- Global ADR-005 / ADR-007 Related / Authority map tables

**Later actions (non-destructive):** Keep body; re-verify line-count / layout
claims only if cited as metrics; surface from architecture hubs via pointer.

**Must not:** Copy full body into a new global ADR-00N file.

---

### MCP ADR-002 — Dual-Runtime Architecture → `canonical-pointer`

| Field | Value |
| --- | --- |
| Body | `ipfs_datasets_py/mcp_server/docs/adr/ADR-002-dual-runtime.md` |
| Status | accepted |
| Owner | MCP Server Team |
| Primary disposition | **`canonical-pointer`** |
| Supersedes / Superseded by | none / none |

**Decision (preserved summary):** Dual-runtime via `anyio` for FastAPI/asyncio
and Trio (MCP++ / structured concurrency); tools use portable async primitives.

**Why this disposition:** Global [ADR-007](ADR-007-MCP-RUNTIME-COMPATIBILITY.md)
explicitly **frames** canonical vs compatibility runtimes around this accepted
decision and states it does **not** supersede package MCP ADR-002. Decision
body remains package-local.

**Evidence:**

- `ipfs_datasets_py/mcp_server/trio_bridge.py`
- `ipfs_datasets_py/mcp_server/tool_metadata.py` (`RUNTIME_TRIO`, related)
- Package architecture narrative `mcp_server/docs/architecture/dual-runtime.md`
  (`refresh-and-surface` exposition; ADR outranks on conflict)
- Global ADR-007 Authority map: “Why dual-runtime? → Package ADR-002 body”

**Later actions:** Pointer from global index; refresh dual-runtime exposition
pages against code; do not collapse into a single-runtime story.

**Must not:** Treat simple_server or compat shims as a second dual-runtime SoT.

---

### MCP ADR-003 — Hierarchical Tool System → `canonical-pointer`

| Field | Value |
| --- | --- |
| Body | `ipfs_datasets_py/mcp_server/docs/adr/ADR-003-hierarchical-tool-system.md` |
| Status | accepted |
| Owner | MCP Server Team |
| Primary disposition | **`canonical-pointer`** |
| Supersedes / Superseded by | none / none |

**Decision (preserved summary):** Two-level category → tool hierarchy with
meta-tools (`tools_list_categories`, `tools_list_tools`, `tools_get_schema`,
`tools_dispatch`) managed by `HierarchicalToolManager`.

**Why this disposition:** Still the binding discovery/dispatch decision for the
large tool surface. Global [ADR-005](ADR-005-REGISTRIES-AND-ADAPTERS.md) cites
this body for hierarchical registry behavior.

**Evidence:**

- `ipfs_datasets_py/mcp_server/hierarchical_tool_manager.py`
- Live tool tree under `ipfs_datasets_py/mcp_server/tools/`
- Tool inventory authority is **live code/registry**, not static Markdown counts
  in this or other guides ([SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md))

**Secondary note (`historical` sub-claim):** Embedded tool totals (for example
“382 tools / 49 categories”) are **evidence-dated** campaign figures. Re-measure
before citing as current inventory. That does not demote the hierarchical
**pattern** itself.

**Later actions:** Align catalogs with `HierarchicalToolManager`; index pointer
only.

---

### MCP ADR-004 — Engine Extraction Pattern → `canonical-pointer`

| Field | Value |
| --- | --- |
| Body | `ipfs_datasets_py/mcp_server/docs/adr/ADR-004-engine-extraction-pattern.md` |
| Status | accepted |
| Owner | MCP Server Team |
| Primary disposition | **`canonical-pointer`** |
| Secondary note | Product **layering** narrative is complemented by global ADR-006 (`merge`-adjacent framing, not body merge) |
| Supersedes / Superseded by | none / none |

**Decision (preserved summary):** Extracted engines follow canonical package
locations and `*_engine` naming; old MCP files become thin shims.

**Why this disposition:** Placement conventions for engines remain the package
decision authority for MCP extraction. Global
[ADR-005](ADR-005-REGISTRIES-AND-ADAPTERS.md) (registries/adapters) and
[ADR-006](ADR-006-PROCESSOR-LAYERING.md) (processors root/core strangler)
**complement** this ADR; they do not replace its body.

**Merge note (framing only):** Concerns about *where processors live during the
strangler* appear in global ADR-006 with Origin/evidence pointing at package
MCP ADR-004. That is **`merge` of product framing**, not concatenation of
Markdown files. Package body stays.

**Evidence:**

- `ipfs_datasets_py/processors/` (and domain `*_engine` modules)
- Compat shims under MCP tools that re-export engines
- Global ADR-006 Origin field references package ADR-004

**Later actions:** Cross-link processor/embeddings engine homes from architecture
guides; keep package body as SoT for extraction convention.

---

### MCP ADR-005 — v6 Coverage Hardening & Ecosystem Integrations → `refresh`

| Field | Value |
| --- | --- |
| Body | `ipfs_datasets_py/mcp_server/docs/adr/ADR-005-v6-coverage-hardening.md` |
| Status | accepted |
| Owner | MCP Server Team |
| Primary disposition | **`refresh`** |
| Secondary note | Coverage percentage tables → **`historical`** (evidence-dated); graceful-degradation integrations remain citable after re-check |
| Supersedes / Superseded by | none / none |

**Decision (preserved summary):** Raise coverage on named MCP modules; add JWT
revocation hooks; adaptive `dispatch_parallel` concurrency; optional gRPC /
Prometheus / OpenTelemetry integrations that **degrade gracefully** when extras
are absent.

**Why this disposition:**

1. **Accepted structural choices** (optional integrations importable without
   hard deps; revocation hooks; batching parameter) remain relevant and align
   with global [ADR-002](ADR-002-LAZY-OPTIONAL-CAPABILITIES.md) lazy/optional
   policy and [ADR-007](ADR-007-MCP-RUNTIME-COMPATIBILITY.md) optional extension
   notes.
2. **Metric claims** (module coverage “before/after” percentages, phase labels)
   are **point-in-time evidence**. Global ADR-007 Notes already warn that
   metric claims inside package ADR-005 are evidence-dated, not evergreen.
   Citing them as current product status requires **refresh** (re-measure) or
   explicit dating.

**Historical sub-claims (preserve, do not delete):**

| Claim class | Disposition | Guidance |
| --- | --- | --- |
| Phase G–H coverage % tables | `historical` | Do not restate as current CI gate without new measurement |
| Phase plan references (`MASTER_IMPROVEMENT_PLAN_2026_v6.md`) | `historical` / plan | Intent history only |
| Graceful degradation pattern for optional transports | accepted pattern → **refresh** against current modules before deep citation | `grpc_transport.py`, `prometheus_exporter.py`, `otel_tracing.py` (or successors) |

**Evidence:**

- Package ADR body (retained)
- Optional integration modules under `ipfs_datasets_py/mcp_server/` (verify paths
  before quoting)
- Global ADR-002 / ADR-007 related optional-capability and extension language

**Later actions:** Re-measure coverage if needed for quality claims; keep
integration decision; optional follow-up may split metrics into a dated evidence
page without deleting this ADR.

**Must not:** Delete the ADR because metrics aged; do not promote phase % into
product entry docs.

---

### MCP ADR-006 — MCP++ Specification Alignment → `refresh`

| Field | Value |
| --- | --- |
| Body | `ipfs_datasets_py/mcp_server/docs/adr/ADR-006-mcp++-alignment.md` |
| Status | accepted |
| Owner | MCP Server Team |
| Primary disposition | **`refresh`** |
| Supersedes / Superseded by | none / none |

**Decision (preserved summary):** Align with MCP++ optional profiles A–E
(interface descriptors, CID-native artifacts, UCAN, temporal deontic policy,
`mcp+p2p` transport); implement optional modules without changing core MCP
JSON-RPC; Profile E remains via `mcplusplus/` wrappers.

**Why this disposition:** The **decision to align** with optional, backward-
compatible profiles remains accepted and is referenced by global
[ADR-007](ADR-007-MCP-RUNTIME-COMPATIBILITY.md). **Implementation status** of
each profile (which modules exist, which are stubs, default-on vs opt-in) must
be **refreshed against the current tree** before product docs claim full
Profile A–E readiness. Package map already labeled architecture exposition
overlapping this ADR as `refresh-and-surface`.

**Evidence:**

- Package ADR body
- `ipfs_datasets_py/mcp_server/mcplusplus/` (and related modules named in the ADR:
  `interface_descriptor.py`, `cid_artifacts.py`, `temporal_policy.py`, etc.—verify
  presence before citing as complete)
- External spec reference recorded in the ADR header (not re-fetched by this task)

**Later actions:** Architecture / MCP guides should re-verify profile modules
and label optional extensions per ADR-007 (absence must not redefine the
canonical tool contract). Keep package body as profile-alignment decision SoT.

**Must not:** Treat MCP++ as the default process entry; that remains full MCP
server per global ADR-007.

---

## Cross-map: package ↔ global

| Question | Authority (first) | Pointer / framing |
| --- | --- | --- |
| Why thin MCP tools? | Package MCP ADR-001 | Global ADR-005, ADR-007 |
| Why dual-runtime? | Package MCP ADR-002 | Global ADR-007 (canonical vs compat frame) |
| Why hierarchical meta-tools? | Package MCP ADR-003 | Global ADR-005 |
| Why `*_engine` placement? | Package MCP ADR-004 | Global ADR-005, ADR-006 |
| Why optional gRPC/Prom/OTEL degrade? | Package MCP ADR-005 (refresh metrics) | Global ADR-002, ADR-007 |
| Why MCP++ profiles optional? | Package MCP ADR-006 (refresh status) | Global ADR-007 |
| Which process is production-preferred? | Global ADR-007 + [RUNTIME_ENTRYPOINTS.md](../RUNTIME_ENTRYPOINTS.md) | Not answered solely by package ADRs |
| Content identity / fail-closed trust | Global ADR-001 … ADR-004 | Package ADRs do not redefine |

Global ADR-007 invariant: package-local MCP ADR bodies under
`mcp_server/docs/adr/` are **not** rewritten or fully copied into
`docs/architecture/decisions/` by that decision (or by this reconciliation).

---

## Index obligations

After this reconciliation, the product index
[README.md](README.md) (`ArchitectureDecisionIndex@1`) must:

1. List every global ADR with **Status**, **Owner**, **Supersedes**, and
   **Superseded by**.
2. List all six package-local MCP ADRs with **Status**, **Owner**, primary
   **disposition**, and body path.
3. Link here for disposition detail.
4. State that package-local numbers are a separate namespace.

Agents proposing MCP architecture changes must:

1. Read the relevant package MCP ADR body (not only this summary).
2. Check global ADR-005…007 for product framing.
3. Prefer supersession over silent contradiction.
4. Never invent a parallel “MCP architecture” novel outside these records.

---

## Validation

```bash
# Declared outputs exist and are non-empty
test -s docs/architecture/decisions/README.md
test -s docs/architecture/decisions/MCP_ADR_RECONCILIATION.md

# Required tokens for this task
rg -n 'Status|Owner|Supersed|package-local' \
  docs/architecture/decisions/README.md \
  docs/architecture/decisions/MCP_ADR_RECONCILIATION.md

# All six package bodies still present (preserve history)
test -s ipfs_datasets_py/mcp_server/docs/adr/ADR-001-thin-wrapper-pattern.md
test -s ipfs_datasets_py/mcp_server/docs/adr/ADR-002-dual-runtime.md
test -s ipfs_datasets_py/mcp_server/docs/adr/ADR-003-hierarchical-tool-system.md
test -s ipfs_datasets_py/mcp_server/docs/adr/ADR-004-engine-extraction-pattern.md
test -s ipfs_datasets_py/mcp_server/docs/adr/ADR-005-v6-coverage-hardening.md
test -s ipfs_datasets_py/mcp_server/docs/adr/ADR-006-mcp++-alignment.md

# Disposition vocabulary present
rg -n 'canonical-pointer|refresh|merge|historical' \
  docs/architecture/decisions/MCP_ADR_RECONCILIATION.md
```

---

## Related artifacts

| Artifact | Relationship |
| --- | --- |
| [README.md](README.md) | Global + package-local decision index |
| [ADR-005-REGISTRIES-AND-ADAPTERS.md](ADR-005-REGISTRIES-AND-ADAPTERS.md) | Points at package MCP ADR-001/003/004 |
| [ADR-006-PROCESSOR-LAYERING.md](ADR-006-PROCESSOR-LAYERING.md) | Complements package MCP ADR-004 |
| [ADR-007-MCP-RUNTIME-COMPATIBILITY.md](ADR-007-MCP-RUNTIME-COMPATIBILITY.md) | Frames package MCP ADR-002; points at 001/003–006 |
| [PACKAGE_LOCAL_DOCUMENTATION_MAP.md](../../maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md) §4 | Pre-reconciliation inventory and ADR rules |
| [ADR_TEMPLATE.md](ADR_TEMPLATE.md) | Global ADR skeleton; lists the six package precedents |
| [INFORMATION_ARCHITECTURE.md](../../maintenance/INFORMATION_ARCHITECTURE.md) §7 | Lifecycle and numbering |
| [SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md) | Authority rank for ADRs vs guides vs metrics |

---

## Document history

| Date | Change |
| --- | --- |
| 2026-08-03 | Initial reconciliation as IPFSDOC-016 artifact (`MCPADRReconciliation@1`): map six package-local MCP ADRs to `canonical-pointer` (001–004) and `refresh` (005–006); record merge/historical as sub-claim notes only; preserve all bodies |
