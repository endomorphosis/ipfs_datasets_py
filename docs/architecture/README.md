# Architecture documentation hub

| Field | Value |
| --- | --- |
| Interface | `ArchitectureDocumentationHub@1` |
| Task | `IPFSDOC-090` |
| Status | `canonical` |
| Owner | documentation-governance; architecture |
| Source of truth | Live files under `docs/architecture/`; domain package trees under `ipfs_datasets_py/`; [INFORMATION_ARCHITECTURE.md](../maintenance/INFORMATION_ARCHITECTURE.md); [SOURCE_AUTHORITY.md](../maintenance/SOURCE_AUTHORITY.md); [PACKAGE_LOCAL_DOCUMENTATION_MAP.md](../maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md) |
| Last verified | 2026-08-03 |
| Audience | architect (primary); developer, agent, operator, security reviewer |
| Goal | `IPFSDOC-G111` |
| Review cadence | after any new architecture domain, ADR acceptance, or lifecycle reclassification under this tree |

> **What this page is:** the single **canonical navigation and decision-routing
> entry** for product architecture. Deep contracts live in leaf guides and ADRs.
>
> **What this page is not:** a substitute for [SYSTEM_CONTEXT.md](SYSTEM_CONTEXT.md),
> [DOMAIN_MAP.md](DOMAIN_MAP.md), domain leaves, or accepted ADRs. It does not
> invent new ownership rules. Point-in-time counts and undated marketing claims
> are not architecture authority.

## 1. Purpose

Use this hub when you need to:

1. **Orient** — what the system is, who uses it, and which surface is supported.
2. **Place work** — which domain owns a responsibility (not where a thin wrapper lives).
3. **Follow authority** — evidence vs proof vs policy vs authorization vs control plane.
4. **Pick the right leaf** — processing, storage, retrieval, knowledge, logic, MCP, runtime, wallet.
5. **Separate states** — **current architecture** vs **proposed plans** vs **implementation evidence** vs **compatibility** vs **history**.

Authority order when sources disagree
([SOURCE_AUTHORITY.md](../maintenance/SOURCE_AUTHORITY.md)):

1. executable tests and schemas that define a contract;
2. current implementation and packaging/configuration metadata;
3. current operator configuration and deployment manifests;
4. accepted architecture decision records;
5. maintained guides (including this hub and domain leaves);
6. historical plans, completion reports, generated summaries, and archive material.

---

## 2. Lifecycle labels (read before citing)

Every route below carries a **state**. Only `canonical` / `accepted` pages may
be treated as current product architecture.

| Label | May be current architecture? | Meaning on this hub |
| --- | --- | --- |
| **Current** (`canonical` guide or `accepted` ADR) | **Yes** | Describes shipped behavior or a binding decision verified against the tree |
| **Proposed / plan** | **No** | Intent for future or in-flight work (`*_PLAN.md`, `*.objectives.md`, `*.todo.md`, design gates) |
| **Evidence** | Only for the measured commit/date | Receipts, baselines, coverage matrices, completion artifacts |
| **Compatibility** | Partial — for migration surfaces only | Live transitional names, dual registries, or strangler shims; not a second business-logic home |
| **Historical** | **No** | Superseded design, session reports, migration narratives, static catalogs kept for audit |
| **Template / index** | Meta-authority only | How to write guides/ADRs; not a domain design by itself |

**Hard rule:** Plans are not architecture. A plan may propose a design; only an
accepted ADR or a `canonical` architecture guide records the decision as current.

---

## 3. Audience routes

Start from who you are. Each row lists the **first** pages to open.

| Audience | Start here | Then | Avoid treating as architecture |
| --- | --- | --- | --- |
| **Architect** | [SYSTEM_CONTEXT.md](SYSTEM_CONTEXT.md) → [DOMAIN_MAP.md](DOMAIN_MAP.md) → [decisions/README.md](decisions/README.md) | Domain index for the boundary you own; [INTEGRATION_BOUNDARIES.md](INTEGRATION_BOUNDARIES.md) | Plans under this directory; root session summaries |
| **Developer / contributor** | [DOMAIN_MAP.md](DOMAIN_MAP.md) → domain `README.md` → leaf guide | [RUNTIME_ENTRYPOINTS.md](RUNTIME_ENTRYPOINTS.md); [DEPENDENCY_AND_INITIALIZATION.md](DEPENDENCY_AND_INITIALIZATION.md); [../developer_guides/REPOSITORY_MAP.md](../developer_guides/REPOSITORY_MAP.md) | Static tool catalogs as ownership truth |
| **Agent / automation** | This hub + [DOMAIN_MAP.md](DOMAIN_MAP.md) + relevant ADR | Domain leaves with stable headings; [../GLOSSARY.md](../GLOSSARY.md); validation sections on leaves | Inventing competing roots; treating discovery as approval |
| **Operator / deployer** | [RUNTIME_ENTRYPOINTS.md](RUNTIME_ENTRYPOINTS.md) → [mcp/README.md](mcp/README.md) | [../guides/operations/MCP_SERVER_RUNBOOK.md](../guides/operations/MCP_SERVER_RUNBOOK.md); [../guides/operations/DEPLOYMENT_AND_RUNTIME.md](../guides/operations/DEPLOYMENT_AND_RUNTIME.md) | Architecture leaves as runbooks (they are not) |
| **Security / policy reviewer** | [ADR-003](decisions/ADR-003-LAYERED-AUTHORITY.md) → [ADR-004](decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) | [logic/RESULT_AUTHORITY.md](logic/RESULT_AUTHORITY.md); [WALLET_TRUST_AND_PRIVACY.md](WALLET_TRUST_AND_PRIVACY.md); [mcp/POLICY_AND_AUTHORIZATION.md](mcp/POLICY_AND_AUTHORIZATION.md); [../guides/security/THREAT_MODEL.md](../guides/security/THREAT_MODEL.md) | Simulated proofs as production soundness |
| **Maintainer / doc owner** | [../maintenance/INFORMATION_ARCHITECTURE.md](../maintenance/INFORMATION_ARCHITECTURE.md) | [../maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md](../maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md); [../maintenance/COVERAGE_MATRIX.md](../maintenance/COVERAGE_MATRIX.md); [ARCHITECTURE_GUIDE_TEMPLATE.md](ARCHITECTURE_GUIDE_TEMPLATE.md) | Promoting historical plans into entry pages without re-verification |

---

## 4. Decision routes (by question)

| Question | Go to (current) | Related decisions |
| --- | --- | --- |
| What is the product and who uses it? | [SYSTEM_CONTEXT.md](SYSTEM_CONTEXT.md) | — |
| Which package domain owns this responsibility? | [DOMAIN_MAP.md](DOMAIN_MAP.md) | [ADR-005](decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md) |
| How does data/control move end to end? | [END_TO_END_DATA_FLOW.md](END_TO_END_DATA_FLOW.md) | ADR-001, ADR-003 |
| How do I start the process (CLI / API / MCP)? | [RUNTIME_ENTRYPOINTS.md](RUNTIME_ENTRYPOINTS.md) | [ADR-007](decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md) |
| What is lazy, optional, or hermetic-by-default? | [DEPENDENCY_AND_INITIALIZATION.md](DEPENDENCY_AND_INITIALIZATION.md) | [ADR-002](decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md) |
| Where does this repo stop and siblings begin? | [INTEGRATION_BOUNDARIES.md](INTEGRATION_BOUNDARIES.md) | ADR-004, ADR-007 |
| How is content identified and provenanced? | [storage/CONTENT_ADDRESSING_AND_IPLD.md](storage/CONTENT_ADDRESSING_AND_IPLD.md) | [ADR-001](decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) |
| Processor core vs root shims? | [processing/PROCESSOR_PIPELINE.md](processing/PROCESSOR_PIPELINE.md) | [ADR-006](decisions/ADR-006-PROCESSOR-LAYERING.md) |
| What may a result claim (proof vs policy vs discovery)? | [logic/RESULT_AUTHORITY.md](logic/RESULT_AUTHORITY.md) | [ADR-003](decisions/ADR-003-LAYERED-AUTHORITY.md), [ADR-004](decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| MCP canonical runtime vs compatibility shells? | [mcp/SERVER_AND_DISPATCH.md](mcp/SERVER_AND_DISPATCH.md) | [ADR-007](decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md); [decisions/MCP_ADR_RECONCILIATION.md](decisions/MCP_ADR_RECONCILIATION.md) |
| Wallet / UCAN / private payloads? | [WALLET_TRUST_AND_PRIVACY.md](WALLET_TRUST_AND_PRIVACY.md) | ADR-001, ADR-003, ADR-004 |
| Agent supervisor / taskboards / worktrees? | [runtime/AGENT_SUPERVISOR_AND_TASKBOARDS.md](runtime/AGENT_SUPERVISOR_AND_TASKBOARDS.md) | ADR-003, ADR-004 (supervisor often external) |
| Profile G planning and evidence? | [runtime/PROFILE_G_PLANNING_AND_EVIDENCE.md](runtime/PROFILE_G_PLANNING_AND_EVIDENCE.md) | ADR-003, ADR-004 |
| Vocabulary for identity, proof, receipt, fallback… | [../GLOSSARY.md](../GLOSSARY.md) | ADR-001…ADR-004 |
| Capability status (stable / optional / experimental…)? | [../FEATURES.md](../FEATURES.md) | ADR-002, ADR-004 |

---

## 5. Current system model (canonical)

These pages are the **authoritative mental model**. Prefer them over any
diagram on this hub.

| Page | Role | Status |
| --- | --- | --- |
| [SYSTEM_CONTEXT.md](SYSTEM_CONTEXT.md) | Product, actors, supported surfaces, explicit non-authority | **Current** |
| [DOMAIN_MAP.md](DOMAIN_MAP.md) | Top-level domain ownership and placement rules | **Current** |
| [END_TO_END_DATA_FLOW.md](END_TO_END_DATA_FLOW.md) | Hop-level data and control flows (incl. MCP, logic, retrieval) | **Current** |
| [DEPENDENCY_AND_INITIALIZATION.md](DEPENDENCY_AND_INITIALIZATION.md) | Lazy extras, init order, optional capability load | **Current** |
| [INTEGRATION_BOUNDARIES.md](INTEGRATION_BOUNDARIES.md) | Sibling packages, submodules, external services | **Current** |
| [RUNTIME_ENTRYPOINTS.md](RUNTIME_ENTRYPOINTS.md) | Console scripts, CLI, MCP process entry, domain CLIs | **Current** |

### Orientation diagram (simplified — current topology only)

```text
                    +---------------------------+
                    |  Surfaces (entry)         |
                    |  Python API · CLI · MCP   |
                    +-------------+-------------+
                                  |
          +-----------------------+-----------------------+
          |                       |                       |
          v                       v                       v
   +-------------+        +--------------+        +----------------+
   | processing  |        |  retrieval   |        | knowledge      |
   | processors  |------->|  embeddings  |------->| graphs/GraphRAG|
   +------+------+        |  vector/query|        +--------+-------+
          |               +------+-------+                 |
          |                      |                         |
          v                      v                         v
   +-------------+        +--------------+        +----------------+
   | storage     |<------>|  logic       |<------>| wallet/trust   |
   | CID/IPLD    |        |  IR/proof    |        | UCAN/privacy   |
   | cache/P2P   |        |  policy/authz|        +----------------+
   +------+------+        +------+-------+
          |                      |
          +----------+-----------+
                     |
                     v
            +----------------+
            | mcp (adapter)  |  thin tools → domain engines
            | runtime        |  agent supervisor (often sibling)
            +----------------+
```

Detail and failure modes live in [END_TO_END_DATA_FLOW.md](END_TO_END_DATA_FLOW.md)
and domain leaves—not in this sketch.

---

## 6. Domain routes (current architecture)

Each domain has a **canonical index** (`README.md`) plus leaf guides. Open the
index first; use leaves for contracts, failure modes, and extension.

### 6.1 Processing — `docs/architecture/processing/`

| Page | Concern | Status |
| --- | --- | --- |
| [processing/README.md](processing/README.md) | Processing architecture index | **Current** |
| [processing/PROCESSOR_PIPELINE.md](processing/PROCESSOR_PIPELINE.md) | Registry, pipeline, core vs root layering | **Current** |
| [processing/FILE_AND_MULTIMEDIA.md](processing/FILE_AND_MULTIMEDIA.md) | File, PDF, media conversion | **Current** |
| [processing/WEB_ARCHIVING_AND_LEGAL_INGESTION.md](processing/WEB_ARCHIVING_AND_LEGAL_INGESTION.md) | Web archive and legal ingest paths | **Current** |

### 6.2 Storage — `docs/architecture/storage/`

| Page | Concern | Status |
| --- | --- | --- |
| [storage/README.md](storage/README.md) | Storage and distribution index | **Current** |
| [storage/CONTENT_ADDRESSING_AND_IPLD.md](storage/CONTENT_ADDRESSING_AND_IPLD.md) | CID, IPLD, CAR, identity | **Current** |
| [storage/STORAGE_CACHING_AND_BACKENDS.md](storage/STORAGE_CACHING_AND_BACKENDS.md) | Backends, cache, routers | **Current** |
| [storage/P2P_AND_PUBLICATION.md](storage/P2P_AND_PUBLICATION.md) | P2P, pin/cluster, publication | **Current** |
| [storage/IMMUTABLE_DATASET_RELEASES.md](storage/IMMUTABLE_DATASET_RELEASES.md) | Immutable voice/HF release lifecycle | **Current** |

### 6.3 Retrieval — `docs/architecture/retrieval/`

| Page | Concern | Status |
| --- | --- | --- |
| [retrieval/README.md](retrieval/README.md) | Retrieval architecture index | **Current** |
| [retrieval/EMBEDDINGS_AND_INDEXING.md](retrieval/EMBEDDINGS_AND_INDEXING.md) | Embedding generation and indexes | **Current** |
| [retrieval/VECTOR_STORES.md](retrieval/VECTOR_STORES.md) | Vector store adapters and backends | **Current** |
| [retrieval/SEARCH_AND_QUERY.md](retrieval/SEARCH_AND_QUERY.md) | Search and query surfaces | **Current** |

### 6.4 Knowledge — `docs/architecture/knowledge/`

| Page | Concern | Status |
| --- | --- | --- |
| [knowledge/README.md](knowledge/README.md) | Knowledge architecture index | **Current** |
| [knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md](knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md) | Graph build, store, query lifecycle | **Current** |
| [knowledge/GRAPHRAG.md](knowledge/GRAPHRAG.md) | GraphRAG composition | **Current** |
| [knowledge/OPTIMIZATION_LOOPS.md](knowledge/OPTIMIZATION_LOOPS.md) | Optimizer loops over graph/retrieval | **Current** |

### 6.5 Logic — `docs/architecture/logic/`

| Page | Concern | Status |
| --- | --- | --- |
| [logic/README.md](logic/README.md) | Logic / proof / policy index | **Current** |
| [logic/IR_FAMILY_AND_IDENTITY.md](logic/IR_FAMILY_AND_IDENTITY.md) | IR families and identity | **Current** |
| [logic/COMPILERS_AND_SEMANTIC_ROUND_TRIP.md](logic/COMPILERS_AND_SEMANTIC_ROUND_TRIP.md) | Compilers and semantic round-trip | **Current** |
| [logic/EXTERNAL_PROVERS.md](logic/EXTERNAL_PROVERS.md) | External provers and optional binaries | **Current** |
| [logic/LEGAL_AND_SECURITY_CONSTRAINTS.md](logic/LEGAL_AND_SECURITY_CONSTRAINTS.md) | Legal and security constraint surfaces | **Current** |
| [logic/PROOF_ATTESTATION_AND_ZKP.md](logic/PROOF_ATTESTATION_AND_ZKP.md) | Proof, attestation, ZKP backends | **Current** |
| [logic/GOVERNED_AUTHORIZATION.md](logic/GOVERNED_AUTHORIZATION.md) | Governed authorization | **Current** |
| [logic/RESULT_AUTHORITY.md](logic/RESULT_AUTHORITY.md) | Non-interchangeable result authority kinds | **Current** |

### 6.6 MCP — `docs/architecture/mcp/`

| Page | Concern | Status |
| --- | --- | --- |
| [mcp/README.md](mcp/README.md) | MCP architecture index | **Current** |
| [mcp/SERVER_AND_DISPATCH.md](mcp/SERVER_AND_DISPATCH.md) | Server process, dispatch, canonical entry | **Current** |
| [mcp/TOOL_LIFECYCLE_AND_REGISTRIES.md](mcp/TOOL_LIFECYCLE_AND_REGISTRIES.md) | Tool registration and lifecycle | **Current** |
| [mcp/INTERFACES_AND_TRANSPORTS.md](mcp/INTERFACES_AND_TRANSPORTS.md) | Transports (stdio/HTTP/…) | **Current** |
| [mcp/POLICY_AND_AUTHORIZATION.md](mcp/POLICY_AND_AUTHORIZATION.md) | Policy allow vs domain execution | **Current** |
| [mcp/AUDIT_EVENTS_AND_OBSERVABILITY.md](mcp/AUDIT_EVENTS_AND_OBSERVABILITY.md) | Audit events and observability | **Current** |

MCP tools are **adapters**. Domain engines own business logic
([ADR-005](decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md),
[ADR-007](decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md)).

### 6.7 Runtime — `docs/architecture/runtime/`

| Page | Concern | Status |
| --- | --- | --- |
| [runtime/AGENT_SUPERVISOR_AND_TASKBOARDS.md](runtime/AGENT_SUPERVISOR_AND_TASKBOARDS.md) | Agent supervisor, taskboards, worktrees, merge authority | **Current** (implementation often in sibling `ipfs_accelerate_py`) |
| [runtime/PROFILE_G_PLANNING_AND_EVIDENCE.md](runtime/PROFILE_G_PLANNING_AND_EVIDENCE.md) | Profile G planning, risk, evidence provider | **Current** |

Also use system-level [RUNTIME_ENTRYPOINTS.md](RUNTIME_ENTRYPOINTS.md) for
process start surfaces (not the same as the agent-supervisor runtime domain).

### 6.8 Security / wallet

| Page | Concern | Status |
| --- | --- | --- |
| [WALLET_TRUST_AND_PRIVACY.md](WALLET_TRUST_AND_PRIVACY.md) | Wallet crypto, UCAN, privacy export, simulated proofs | **Current** |
| [../guides/security/THREAT_MODEL.md](../guides/security/THREAT_MODEL.md) | Operator/security threat model | Operations / security (not under this hub body) |
| [../guides/security/SECRETS_AND_CREDENTIALS.md](../guides/security/SECRETS_AND_CREDENTIALS.md) | Secrets handling | Operations / security |
| [../guides/security/AUDIT_PROVENANCE_AND_INCIDENTS.md](../guides/security/AUDIT_PROVENANCE_AND_INCIDENTS.md) | Audit and incidents | Operations / security |

---

## 7. Architecture decisions (ADRs)

| Page | Role | Status |
| --- | --- | --- |
| [decisions/README.md](decisions/README.md) | Decision index (all product ADRs) | **Current** (index) |
| [decisions/ADR_TEMPLATE.md](decisions/ADR_TEMPLATE.md) | ADR authoring template | Template |
| [decisions/MCP_ADR_RECONCILIATION.md](decisions/MCP_ADR_RECONCILIATION.md) | Maps package-local MCP ADRs ↔ product ADR-007 | **Current** |
| [decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md](decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) | Content identity / CID / provenance | **Accepted** |
| [decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md](decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md) | Lazy optional capabilities | **Accepted** |
| [decisions/ADR-003-LAYERED-AUTHORITY.md](decisions/ADR-003-LAYERED-AUTHORITY.md) | Layered authority (non-interchangeable kinds) | **Accepted** |
| [decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md](decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) | Fail-closed trust vs allowed degradation | **Accepted** |
| [decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md](decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md) | Registries and adapters | **Accepted** |
| [decisions/ADR-006-PROCESSOR-LAYERING.md](decisions/ADR-006-PROCESSOR-LAYERING.md) | Processor core / root layering | **Accepted** |
| [decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md](decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md) | MCP canonical vs compatibility runtimes | **Accepted** |

Package-local MCP ADR **bodies** remain under
`ipfs_datasets_py/mcp_server/docs/adr/` until a reviewed relocation task moves
them. Discover via [decisions/MCP_ADR_RECONCILIATION.md](decisions/MCP_ADR_RECONCILIATION.md)
and [PACKAGE_LOCAL_DOCUMENTATION_MAP.md](../maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md).

---

## 8. Operations and package-local details

Architecture leaves describe **what must be true**. Runbooks describe **how to
operate safely**. Package-local trees may hold proximate detail without being
the product authority.

### 8.1 Operations (outside `docs/architecture/`, linked for routing)

| Page | Role |
| --- | --- |
| [../guides/operations/MCP_SERVER_RUNBOOK.md](../guides/operations/MCP_SERVER_RUNBOOK.md) | Local MCP lifecycle procedures |
| [../guides/operations/DEPLOYMENT_AND_RUNTIME.md](../guides/operations/DEPLOYMENT_AND_RUNTIME.md) | Deployment and runtime ops |
| [../guides/operations/DIAGNOSTICS_AND_RECOVERY.md](../guides/operations/DIAGNOSTICS_AND_RECOVERY.md) | Diagnostics and recovery |
| [../guides/operations/PERFORMANCE_AND_CAPACITY.md](../guides/operations/PERFORMANCE_AND_CAPACITY.md) | Performance and capacity |

### 8.2 Package-local and competing documentation

| Resource | Role | Status |
| --- | --- | --- |
| [../maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md](../maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md) | Inventory and disposition of package-local + competing hubs | **Evidence** map (dispositions) |
| `ipfs_datasets_py/**/*.md` | Module READMEs, tool notes, MCP package docs | Mixed — follow map dispositions |
| `ipfs_datasets_py/mcp_server/docs/adr/` | Six package-local MCP ADRs | Decision bodies (MCP namespace); not product ADR-001…007 numbers |
| `docs/logic/`, `docs/optimizers/`, `docs/guides/processors/` | Competing or historical product hubs | Prefer architecture domain leaves for current design |

Do **not** invent a second architecture home under the package when a
`docs/architecture/` leaf already owns the concern.

### 8.3 Templates and contribution

| Page | Role | Status |
| --- | --- | --- |
| [ARCHITECTURE_GUIDE_TEMPLATE.md](ARCHITECTURE_GUIDE_TEMPLATE.md) | How to write a domain architecture guide | Template (**canonical** for process) |
| [decisions/ADR_TEMPLATE.md](decisions/ADR_TEMPLATE.md) | How to write an ADR | Template |
| [../developer_guides/DOCUMENTATION_CONTRIBUTING.md](../developer_guides/DOCUMENTATION_CONTRIBUTING.md) | Documentation contribution workflow | Maintained process |
| [../maintenance/INFORMATION_ARCHITECTURE.md](../maintenance/INFORMATION_ARCHITECTURE.md) | Corpus lifecycle and placement contract | **Current** policy |

---

## 9. Proposed plans (not current architecture)

These files live under `docs/architecture/` for discoverability but are
**plan** state. Cite them only as intent; never as shipped behavior.

| Path | Topic | Status |
| --- | --- | --- |
| [IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md](IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md) | IR family refactor / Intent IR | **Proposed / plan** |
| [ir_family_refactor_intent_ir.objectives.md](ir_family_refactor_intent_ir.objectives.md) | Objectives board for IR refactor | **Proposed / plan** |
| [ir_family_refactor_intent_ir.todo.md](ir_family_refactor_intent_ir.todo.md) | Task board for IR refactor | **Proposed / plan** |
| [INTENT_IR_ATTESTED_AUTHORIZATION_PLAN.md](INTENT_IR_ATTESTED_AUTHORIZATION_PLAN.md) | Attested authorization around Intent IR | **Proposed / plan** |
| [LOGIC_INTENT_LEGAL_GATE_PLAN.md](LOGIC_INTENT_LEGAL_GATE_PLAN.md) | Legal gate around intent/logic | **Proposed / plan** |
| [logic_intent_legal_gate.objectives.md](logic_intent_legal_gate.objectives.md) | Objectives board | **Proposed / plan** |
| [logic_intent_legal_gate.todo.md](logic_intent_legal_gate.todo.md) | Task board | **Proposed / plan** |
| [semantic_roundtrip_canonical_compiler.md](semantic_roundtrip_canonical_compiler.md) | Canonical structured-text round-trip design contract (SRT-015); design gate, not production promotion | **Proposed / design** (not production authority) |

For **current** IR identity, compilers, provers, constraints, and result
authority, use §6.5 **logic** leaves instead.

Program-level documentation refresh plans live under
`docs/implementation/plans/` (protected planning inputs; not edited by this hub).

---

## 10. Compatibility and transitional surfaces

| Topic | Where documented | Label |
| --- | --- | --- |
| Processor root modules vs consolidated core | [processing/PROCESSOR_PIPELINE.md](processing/PROCESSOR_PIPELINE.md), [ADR-006](decisions/ADR-006-PROCESSOR-LAYERING.md) | **Compatibility** (strangler) |
| MCP canonical entry vs legacy/simple shells | [mcp/SERVER_AND_DISPATCH.md](mcp/SERVER_AND_DISPATCH.md), [ADR-007](decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md) | **Compatibility** |
| Optional extras / lazy import | [DEPENDENCY_AND_INITIALIZATION.md](DEPENDENCY_AND_INITIALIZATION.md), [ADR-002](decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md), [../FEATURES.md](../FEATURES.md) | **Current** policy; capabilities may be optional |
| Git submodules / unavailable nested backends | [INTEGRATION_BOUNDARIES.md](INTEGRATION_BOUNDARIES.md), [ADR-004](decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) | Unavailable ≠ trust failure (see ADR-004) |
| CLI name supersets (`setup.py` vs `pyproject.toml`) | [RUNTIME_ENTRYPOINTS.md](RUNTIME_ENTRYPOINTS.md) | Packaging drift called out on that page |

---

## 11. Historical and review-needed material under this tree

These pages remain in the tree for audit or migration narrative. They are
**not** current architecture. Prefer the canonical domain leaves above.

| Path | Historical role | Prefer instead |
| --- | --- | --- |
| [github_actions_architecture.md](github_actions_architecture.md) | CI/CD architecture write-up | Treat as ops/CI history unless re-verified; not a product domain leaf |
| [github_actions_implementation_summary.md](github_actions_implementation_summary.md) | Implementation summary | Historical |
| [github_actions_infrastructure.md](github_actions_infrastructure.md) | Infrastructure notes | Historical / ops-adjacent |
| [project_structure.md](project_structure.md) | Older project layout sketch | [DOMAIN_MAP.md](DOMAIN_MAP.md), [../developer_guides/REPOSITORY_MAP.md](../developer_guides/REPOSITORY_MAP.md) |
| [submodule_architecture.md](submodule_architecture.md) | Submodule design narrative | [INTEGRATION_BOUNDARIES.md](INTEGRATION_BOUNDARIES.md) |
| [submodule_deprecation.md](submodule_deprecation.md) | Deprecation strategy notes | INTEGRATION_BOUNDARIES + FEATURES |
| [submodule_fix.md](submodule_fix.md) | Fix notes | Historical |
| [submodule_migration_verification.md](submodule_migration_verification.md) | Migration verification | Evidence/historical |
| [MCP_TOOLS_ARCHITECTURE.md](MCP_TOOLS_ARCHITECTURE.md) | Earlier MCP tools architecture | [mcp/README.md](mcp/README.md) and leaves |
| [mcp_tools_catalog.md](mcp_tools_catalog.md) | Static tool catalog | Live discovery via meta-tools / disk under `mcp_server/tools/` |
| [mcp_tools_comprehensive_documentation.md](mcp_tools_comprehensive_documentation.md) | Comprehensive MCP dump | mcp domain leaves |
| [mcp_tools_technical_reference.md](mcp_tools_technical_reference.md) | Technical reference dump | mcp domain leaves |

Undated tool counts and marketing inventory claims in historical MCP pages are
**not** architecture authority ([mcp/README.md](mcp/README.md) lifecycle note).

---

## 12. Implementation evidence (point-in-time)

Evidence pages support claims; they are not evergreen design.

| Resource | Role |
| --- | --- |
| [../maintenance/CURRENT_STATE_BASELINE.md](../maintenance/CURRENT_STATE_BASELINE.md) | Tree baseline inventory |
| [../maintenance/COVERAGE_MATRIX.md](../maintenance/COVERAGE_MATRIX.md) | Documentation coverage |
| [../maintenance/DRIFT_AND_CLAIM_MATRIX.md](../maintenance/DRIFT_AND_CLAIM_MATRIX.md) | Claim drift audit |
| [../maintenance/SOURCE_AUTHORITY.md](../maintenance/SOURCE_AUTHORITY.md) | Authority ranking |
| [../maintenance/completion_receipts/](../maintenance/completion_receipts/) | Per-task completion receipts (e.g. this hub: `IPFSDOC-090`) |
| Leaf “Validation” / “Source of truth” sections | How to re-check each guide against the tree |

---

## 13. Full inventory of `docs/architecture/` (navigation completeness)

Every Markdown path under this directory is listed with a lifecycle label so
the hub satisfies “every architecture page appears in the architecture hub.”

### 13.1 Canonical system and cross-cutting

- [README.md](README.md) — this hub (**Current** index)
- [SYSTEM_CONTEXT.md](SYSTEM_CONTEXT.md) — **Current**
- [DOMAIN_MAP.md](DOMAIN_MAP.md) — **Current**
- [END_TO_END_DATA_FLOW.md](END_TO_END_DATA_FLOW.md) — **Current**
- [DEPENDENCY_AND_INITIALIZATION.md](DEPENDENCY_AND_INITIALIZATION.md) — **Current**
- [INTEGRATION_BOUNDARIES.md](INTEGRATION_BOUNDARIES.md) — **Current**
- [RUNTIME_ENTRYPOINTS.md](RUNTIME_ENTRYPOINTS.md) — **Current**
- [WALLET_TRUST_AND_PRIVACY.md](WALLET_TRUST_AND_PRIVACY.md) — **Current**
- [ARCHITECTURE_GUIDE_TEMPLATE.md](ARCHITECTURE_GUIDE_TEMPLATE.md) — Template

### 13.2 Domain trees

- **processing/** — README, PROCESSOR_PIPELINE, FILE_AND_MULTIMEDIA, WEB_ARCHIVING_AND_LEGAL_INGESTION (**Current**)
- **storage/** — README, CONTENT_ADDRESSING_AND_IPLD, STORAGE_CACHING_AND_BACKENDS, P2P_AND_PUBLICATION, IMMUTABLE_DATASET_RELEASES (**Current**)
- **retrieval/** — README, EMBEDDINGS_AND_INDEXING, VECTOR_STORES, SEARCH_AND_QUERY (**Current**)
- **knowledge/** — README, KNOWLEDGE_GRAPH_LIFECYCLE, GRAPHRAG, OPTIMIZATION_LOOPS (**Current**)
- **logic/** — README, IR_FAMILY_AND_IDENTITY, COMPILERS_AND_SEMANTIC_ROUND_TRIP, EXTERNAL_PROVERS, LEGAL_AND_SECURITY_CONSTRAINTS, PROOF_ATTESTATION_AND_ZKP, GOVERNED_AUTHORIZATION, RESULT_AUTHORITY (**Current**)
- **mcp/** — README, SERVER_AND_DISPATCH, TOOL_LIFECYCLE_AND_REGISTRIES, INTERFACES_AND_TRANSPORTS, POLICY_AND_AUTHORIZATION, AUDIT_EVENTS_AND_OBSERVABILITY (**Current**)
- **runtime/** — AGENT_SUPERVISOR_AND_TASKBOARDS, PROFILE_G_PLANNING_AND_EVIDENCE (**Current**)
- **decisions/** — README, ADR_TEMPLATE, MCP_ADR_RECONCILIATION, ADR-001…ADR-007 (**Current** / **Accepted** / Template)

### 13.3 Plans

- INTENT_IR_ATTESTED_AUTHORIZATION_PLAN, IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN, LOGIC_INTENT_LEGAL_GATE_PLAN
- ir_family_refactor_intent_ir.{objectives,todo}.md
- logic_intent_legal_gate.{objectives,todo}.md
- semantic_roundtrip_canonical_compiler.md (**Proposed / design**)

### 13.4 Historical / compatibility-era pages retained here

- github_actions_architecture.md, github_actions_implementation_summary.md, github_actions_infrastructure.md
- project_structure.md
- submodule_architecture.md, submodule_deprecation.md, submodule_fix.md, submodule_migration_verification.md
- MCP_TOOLS_ARCHITECTURE.md, mcp_tools_catalog.md, mcp_tools_comprehensive_documentation.md, mcp_tools_technical_reference.md

---

## 14. Related documentation (outside architecture)

| Need | Link |
| --- | --- |
| Product entry | [../index.md](../index.md), [../README.md](../README.md) |
| Capability matrix | [../FEATURES.md](../FEATURES.md) |
| Glossary / authority vocabulary | [../GLOSSARY.md](../GLOSSARY.md) |
| Developer repository map | [../developer_guides/REPOSITORY_MAP.md](../developer_guides/REPOSITORY_MAP.md) |
| Documentation index | [../DOCUMENTATION_INDEX.md](../DOCUMENTATION_INDEX.md) (when present / refreshed by navigation tasks) |
| Implementation plans (program) | [../implementation/plans/](../implementation/plans/) — **plan** only |

---

## 15. How to validate this hub

From the repository root:

```bash
# Non-empty hub + receipt; required domain tokens present
test -s docs/architecture/README.md \
  && test -s docs/maintenance/completion_receipts/IPFSDOC-090.md \
  && rg -n 'SYSTEM_CONTEXT|DOMAIN_MAP|processing|storage|retrieval|knowledge|logic|mcp|decisions|runtime' docs/architecture/README.md

# Spot-check that canonical domain indexes still exist
test -s docs/architecture/SYSTEM_CONTEXT.md \
  && test -s docs/architecture/DOMAIN_MAP.md \
  && test -s docs/architecture/processing/README.md \
  && test -s docs/architecture/storage/README.md \
  && test -s docs/architecture/retrieval/README.md \
  && test -s docs/architecture/knowledge/README.md \
  && test -s docs/architecture/logic/README.md \
  && test -s docs/architecture/mcp/README.md \
  && test -s docs/architecture/decisions/README.md \
  && test -s docs/architecture/runtime/AGENT_SUPERVISOR_AND_TASKBOARDS.md \
  && test -s docs/architecture/WALLET_TRUST_AND_PRIVACY.md
```

Re-verify leaf “Last verified” dates and paths after major domain moves.

---

## 16. Explicit non-claims

- This hub does **not** replace domain leaves or accepted ADRs.
- Diagrams here are **orientation only**; flows and failure modes live in leaves.
- Plans, boards, and design gates under this directory are **not** current architecture.
- Historical MCP catalogs and undated counts are **not** inventory authority.
- Agent-supervisor implementation may live in a **sibling** package; see INTEGRATION_BOUNDARIES and the runtime guides.
- No production code, packaging, or protected plan files are defined by this page.
