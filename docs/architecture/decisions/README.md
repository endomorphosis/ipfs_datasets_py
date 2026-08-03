# Architecture Decision Records — Index

| Field | Value |
| --- | --- |
| Interface | `ArchitectureDecisionIndex@1` |
| Task | `IPFSDOC-016` |
| Status | `canonical` |
| Owner | documentation-governance; architecture |
| Source of truth | Live files under `docs/architecture/decisions/`; package-local MCP ADRs under `ipfs_datasets_py/mcp_server/docs/adr/`; [ADR_TEMPLATE.md](ADR_TEMPLATE.md); [INFORMATION_ARCHITECTURE.md](../../maintenance/INFORMATION_ARCHITECTURE.md) §7; [PACKAGE_LOCAL_DOCUMENTATION_MAP.md](../../maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md) §4 |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent, maintainer |
| Goal | `IPFSDOC-G032` |
| Companion | [MCP_ADR_RECONCILIATION.md](MCP_ADR_RECONCILIATION.md) |

## Purpose

This index is the **discoverable decision surface** for product architecture.
It lists every ADR in the canonical decisions directory (accepted, proposed,
deprecated, superseded, or rejected) and points at the six package-local MCP
ADRs without copying their bodies.

When sources disagree, accepted ADRs rank above ordinary guides (see
[SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md)). Tests and current
implementation still outrank ADR narrative for runtime facts (counts, coverage
percentages, import paths).

## How to use this index

1. **Find a decision** by number, title, or concern in the tables below.
2. **Read the ADR body** for context, decision, alternatives, consequences, and
   invariants. Do not restate those sections in guides as a second authority.
3. **Check Status and Superseded by** before treating a decision as binding.
4. **For MCP package-local ADRs**, follow the disposition in
   [MCP_ADR_RECONCILIATION.md](MCP_ADR_RECONCILIATION.md). Bodies stay under
   `ipfs_datasets_py/mcp_server/docs/adr/` until a reviewed task relocates them.
5. **Propose new cross-cutting product ADRs** under this directory using
   [ADR_TEMPLATE.md](ADR_TEMPLATE.md). Use the next free three-digit number
   **here** (package-local numbers are a separate namespace).

## Status vocabulary

| Status | Binding for new work? | Meaning |
| --- | --- | --- |
| `proposed` | No | Under review |
| `accepted` | **Yes** | Binding until superseded or deprecated |
| `deprecated` | No (prefer successor guidance) | Historically accepted; no longer preferred |
| `superseded` | No | Replaced by a named successor ADR |
| `rejected` | No | Considered and not adopted (optional retention) |
| `canonical` | N/A (index/template only) | This index or the template is maintained product authority for its role |

Lifecycle workflow: draft → review → accept → implement with references →
supersede or deprecate (never silent rewrite). Full policy:
[INFORMATION_ARCHITECTURE.md](../../maintenance/INFORMATION_ARCHITECTURE.md) §7.

---

## Canonical ADRs (`docs/architecture/decisions/`)

Cross-cutting product decisions. Numbering is local to this directory.

| ADR | Title | Status | Owner (Decision owners) | Supersedes | Superseded by | Interface | Task | Summary |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [ADR-001](ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) | Content Identity and Provenance | **accepted** | architecture | none | none | `ContentIdentityDecision@1` | IPFSDOC-013 | Content identity is a function of canonical bytes; CIDs are primary portable identifiers; provenance is a separate lineage graph that references identities. |
| [ADR-002](ADR-002-LAZY-OPTIONAL-CAPABILITIES.md) | Lazy Optional Capabilities | **accepted** | architecture | none | none | `LazyCapabilityDecision@1` | IPFSDOC-013 | Optional capabilities stay lazy and opt-in; hermetic import by default; feature degradation is not fail-closed trust. |
| [ADR-003](ADR-003-LAYERED-AUTHORITY.md) | Layered authority (non-interchangeable result kinds) | **accepted** | architecture; logic/admissibility owners | none | none | `LayeredAuthorityDecision@1` | IPFSDOC-014 | Authority layers (evidence, proof, policy, authorization, control plane) are distinct and non-interchangeable. |
| [ADR-004](ADR-004-FAIL-CLOSED-DEGRADATION.md) | Fail-closed trust boundaries and allowed degradation | **accepted** | architecture; logic/admissibility owners; security/policy consumers | none | none | `FailClosedDecision@1` | IPFSDOC-014 | Trust paths fail closed; optional capability degradation is explicitly allowed and labeled. |
| [ADR-005](ADR-005-REGISTRIES-AND-ADAPTERS.md) | Registries and Adapters | **accepted** | architecture; documentation-governance | none | none | `RegistryAdapterDecision@1` | IPFSDOC-015 | One registry per concern as discovery authority; adapters are protocol bridges only; no second business-logic home. |
| [ADR-006](ADR-006-PROCESSOR-LAYERING.md) | Processor Layering (Root / Core Transition) | **accepted** | architecture; processors maintainers | none | none | `ProcessorLayeringDecision@1` | IPFSDOC-015 | Strangler-style processor layering: core is consolidated SoT where shims point; root modules remain live transitional surface. |
| [ADR-007](ADR-007-MCP-RUNTIME-COMPATIBILITY.md) | MCP Runtime Compatibility (Canonical vs Compatibility) | **accepted** | architecture; mcp-server maintainers | none | none | `MCPRuntimeCompatibilityDecision@1` | IPFSDOC-015 | Clear canonical vs compatibility split for MCP runtimes; package-local MCP ADRs remain detailed decision bodies. |

### Counts (this directory, 2026-08-03)

| Lifecycle Status | Count | ADRs |
| --- | ---: | --- |
| accepted | 7 | ADR-001 … ADR-007 |
| proposed | 0 | — |
| deprecated | 0 | — |
| superseded | 0 | — |
| rejected | 0 | — |

There are currently **no** proposed, deprecated, superseded, or rejected ADRs
in this directory. When one appears, add it to the table above with Status and
Superseded by filled in; do not remove accepted history from the index.

### Templates and non-ADR files

| File | Role | Status | Owner |
| --- | --- | --- | --- |
| [ADR_TEMPLATE.md](ADR_TEMPLATE.md) | Skeleton and lifecycle for new ADRs | `canonical` (template) | documentation-governance |
| [MCP_ADR_RECONCILIATION.md](MCP_ADR_RECONCILIATION.md) | Disposition map for package-local MCP ADRs | `canonical` (reconciliation) | documentation-governance; architecture |
| This README | Decision index | `canonical` (index) | documentation-governance; architecture |

---

## Package-local MCP ADRs (indexed, not duplicated)

Six accepted ADRs live under the MCP package. They are **in-scope for this
index** and retain **namespace-scoped** numbers (`package MCP ADR-00N` ≠
global `ADR-00N`). Full disposition for each:

→ **[MCP_ADR_RECONCILIATION.md](MCP_ADR_RECONCILIATION.md)**

| Package ADR | Title | Status | Owner (Author) | Disposition (primary) | Body path |
| --- | --- | --- | --- | --- | --- |
| MCP ADR-001 | Thin Wrapper Pattern | accepted | MCP Server Team | `canonical-pointer` | [`ipfs_datasets_py/mcp_server/docs/adr/ADR-001-thin-wrapper-pattern.md`](../../../ipfs_datasets_py/mcp_server/docs/adr/ADR-001-thin-wrapper-pattern.md) |
| MCP ADR-002 | Dual-Runtime Architecture (FastAPI + Trio) | accepted | MCP Server Team | `canonical-pointer` | [`…/ADR-002-dual-runtime.md`](../../../ipfs_datasets_py/mcp_server/docs/adr/ADR-002-dual-runtime.md) |
| MCP ADR-003 | Hierarchical Tool System | accepted | MCP Server Team | `canonical-pointer` | [`…/ADR-003-hierarchical-tool-system.md`](../../../ipfs_datasets_py/mcp_server/docs/adr/ADR-003-hierarchical-tool-system.md) |
| MCP ADR-004 | Engine Extraction Pattern | accepted | MCP Server Team | `canonical-pointer` | [`…/ADR-004-engine-extraction-pattern.md`](../../../ipfs_datasets_py/mcp_server/docs/adr/ADR-004-engine-extraction-pattern.md) |
| MCP ADR-005 | v6 Coverage Hardening & Ecosystem Integrations | accepted | MCP Server Team | `refresh` | [`…/ADR-005-v6-coverage-hardening.md`](../../../ipfs_datasets_py/mcp_server/docs/adr/ADR-005-v6-coverage-hardening.md) |
| MCP ADR-006 | MCP++ Specification Alignment | accepted | MCP Server Team | `refresh` | [`…/ADR-006-mcp++-alignment.md`](../../../ipfs_datasets_py/mcp_server/docs/adr/ADR-006-mcp++-alignment.md) |

**Rules (summary):**

- Do **not** independently recreate or delete these six files.
- Do **not** copy full ADR bodies into `docs/architecture/decisions/` as a
  second source of truth.
- Global ADRs (especially ADR-005, ADR-006, ADR-007) **point** at package
  bodies; they do not silently supersede them unless Status and Superseded by
  say so.
- Numbering collision is intentional and **namespace-scoped by path** (global
  ADR-007 ≠ package MCP ADR-006).

---

## Concern → ADR map

| Concern | Prefer first | Also see |
| --- | --- | --- |
| Content identity, CID, provenance | Global [ADR-001](ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) | Domain storage / IR guides |
| Lazy import, optional extras, capability probes | Global [ADR-002](ADR-002-LAZY-OPTIONAL-CAPABILITIES.md) | [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md) |
| Proof / policy / authorization result kinds | Global [ADR-003](ADR-003-LAYERED-AUTHORITY.md) | Logic admissibility modules |
| Fail-closed trust vs allowed degradation | Global [ADR-004](ADR-004-FAIL-CLOSED-DEGRADATION.md) | Global ADR-002 |
| Registries, adapters, discovery SoT | Global [ADR-005](ADR-005-REGISTRIES-AND-ADAPTERS.md) | Package MCP ADR-001, 003, 004 |
| Processors root vs core layout | Global [ADR-006](ADR-006-PROCESSOR-LAYERING.md) | Package MCP ADR-004 |
| MCP full vs simple/compat runtime | Global [ADR-007](ADR-007-MCP-RUNTIME-COMPATIBILITY.md) | Package MCP ADR-002 |
| Thin MCP tools / no business logic in tools | Package MCP ADR-001 | Global ADR-005, ADR-007 |
| Dual-runtime (anyio / FastAPI + Trio) | Package MCP ADR-002 | Global ADR-007 |
| Hierarchical meta-tools | Package MCP ADR-003 | Global ADR-005 |
| Engine placement (`*_engine`) | Package MCP ADR-004 | Global ADR-005, ADR-006 |
| Optional gRPC / Prometheus / OTEL; dated coverage | Package MCP ADR-005 (**refresh** metrics) | Global ADR-002, ADR-007 |
| MCP++ profiles A–E | Package MCP ADR-006 (**refresh** implementation status) | Global ADR-007 |

---

## Creating or changing ADRs

1. Copy [ADR_TEMPLATE.md](ADR_TEMPLATE.md) to
   `docs/architecture/decisions/ADR-NNN-short-kebab-title.md` with the next free
   **global** number.
2. Set Status `proposed`; fill Context, Decision, Alternatives, Consequences,
   Invariants, Compliance, Status, Owner fields.
3. Review with Decision owners; set Status `accepted` and Date accepted.
4. **Update this index** (Status, Owner, Supersedes / Superseded by).
5. Link from the relevant architecture guide.
6. To reverse a decision: add a new ADR or set Status `superseded` /
   `deprecated` with Superseded by. Never delete an accepted ADR body.

Contributor workflow:
[DOCUMENTATION_CONTRIBUTING.md](../../developer_guides/DOCUMENTATION_CONTRIBUTING.md).

---

## Explicit non-actions (this index task)

| Action | Status |
| --- | --- |
| Rewrite package-local MCP ADR bodies | **Not performed** |
| Delete, rename, or relocate package ADR files | **Not performed** |
| Full-body copy of package ADRs into this directory | **Not performed** |
| Mark package ADRs superseded without a reviewed successor | **Not performed** |
| Invent parallel MCP architecture decisions outside existing ADRs | **Not performed** |

Disposition detail and evidence paths for the six package-local ADRs:
[MCP_ADR_RECONCILIATION.md](MCP_ADR_RECONCILIATION.md).

---

## Related artifacts

| Artifact | Relationship |
| --- | --- |
| [ADR_TEMPLATE.md](ADR_TEMPLATE.md) | New ADR skeleton and lifecycle |
| [MCP_ADR_RECONCILIATION.md](MCP_ADR_RECONCILIATION.md) | Package-local MCP ADR disposition map |
| [INFORMATION_ARCHITECTURE.md](../../maintenance/INFORMATION_ARCHITECTURE.md) §7 | ADR lifecycle policy |
| [PACKAGE_LOCAL_DOCUMENTATION_MAP.md](../../maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md) §4 | Pre-index inventory of the six MCP ADRs |
| [SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md) | Authority rank (ADRs above guides) |
| [ARCHITECTURE_GUIDE_TEMPLATE.md](../ARCHITECTURE_GUIDE_TEMPLATE.md) | Architecture guide skeleton (not ADR) |
| [DOMAIN_MAP.md](../DOMAIN_MAP.md) | Domain ownership |
| [RUNTIME_ENTRYPOINTS.md](../RUNTIME_ENTRYPOINTS.md) | Operator entry map (MCP paths) |

---

## Document history

| Date | Change |
| --- | --- |
| 2026-08-03 | Initial index as IPFSDOC-016 artifact (`ArchitectureDecisionIndex@1`): seven accepted global ADRs; six package-local MCP ADRs indexed with pointer to reconciliation map |
