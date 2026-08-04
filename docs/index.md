# IPFS Datasets Python — documentation portal

| Field | Value |
| --- | --- |
| Interface | `DocumentationNavigationRoot@1` |
| Task | `IPFSDOC-095` |
| Status | `canonical` (product entry) |
| Owner | documentation-governance / navigation |
| Source of truth | Live tree under `docs/`; packaging in `pyproject.toml`; [INFORMATION_ARCHITECTURE.md](maintenance/INFORMATION_ARCHITECTURE.md); [SOURCE_AUTHORITY.md](maintenance/SOURCE_AUTHORITY.md) |
| Last verified | 2026-08-03 |
| Audience | end-user (primary); developer, operator, architect, agent, maintainer |
| Package | `ipfs_datasets_py` **0.2.0** (`requires-python >= 3.12`) |
| Related | [README.md](README.md) (docs directory roles), [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md) (deep map) |

> **What this page is:** the **single canonical product landing** for
> documentation. Start here, then follow audience or task routes.
>
> **What this page is not:** a second competing index, a completion report, a
> feature-count marketing page, or a substitute for architecture leaves, API
> domain maps, or package-local module READMEs.
>
> **Landing flow (authoritative):**
> 1. **This file** (`docs/index.md`) — choose audience / task.
> 2. **Journey pages** — Getting Started, Installation, User Guide, Developer Guide.
> 3. **Domain hubs** — Architecture, API, Operations, Security, deep map.
> 4. **[DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md)** — full domain catalog when you need every maintained route.
> 5. **[README.md](README.md)** — what lives under `docs/` (maintained vs generated vs historical).

Authority order when sources disagree
([SOURCE_AUTHORITY.md](maintenance/SOURCE_AUTHORITY.md)):

1. executable tests and schemas that define a contract;
2. current implementation and packaging/configuration metadata;
3. current operator configuration and deployment manifests;
4. accepted architecture decision records;
5. maintained guides (including this portal);
6. historical plans, completion reports, generated summaries, and archive material.

---

## 1. Lifecycle labels (read before citing)

| Label | May be current product authority? | Where it lives |
| --- | --- | --- |
| **Maintained** (`canonical` / refreshed `current`) | **Yes** | Entry guides, architecture hubs, developer guides, ops/security, API domain pages |
| **Generated** | Only for regenerated facts | API stubs, Sphinx/MkDocs build output, auto indexes |
| **Plan** | **No** | `docs/implementation/plans/`, domain `*_PLAN.md` / `*.objectives.md` / `*.todo.md` |
| **Evidence** | Only for the measured commit/date | `docs/maintenance/*`, completion receipts, baselines |
| **Historical** | **No** | `docs/archive/`, `docs/archived_stubs/`, session/phase reports, undated status summaries |

Do not promote historical completion percentages, undated “latest features,” or
tool-count marketing claims into this portal.

---

## 2. Getting Started (shortest path)

| Step | Page | Why |
| --- | --- | --- |
| 1 | [getting_started.md](getting_started.md) | Shortest verified first success (Python 3.12+) |
| 2 | [installation.md](installation.md) | Base install + capability extras |
| 3 | [configuration.md](configuration.md) | Precedence, env vars, security-sensitive settings |
| 4 | [user_guide.md](user_guide.md) | Supported user journeys (Python / CLI / MCP) |
| 5 | [FEATURES.md](FEATURES.md) | Capability status matrix (stable / optional / unavailable) |

**First-success tutorials**

| Tutorial | Audience need |
| --- | --- |
| [FIRST_DATASET_WORKFLOW.md](tutorials/FIRST_DATASET_WORKFLOW.md) | Offline first dataset load/save |
| [MCP_CLIENT_WORKFLOW.md](tutorials/MCP_CLIENT_WORKFLOW.md) | MCP client / hierarchical tools |
| [RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md](tutorials/RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md) | Retrieval + knowledge graph path |
| [LOGIC_AND_PROOF_WORKFLOW.md](tutorials/LOGIC_AND_PROOF_WORKFLOW.md) | Logic / proof surfaces (honest non-proof bounds) |

Related: [tutorials/](tutorials/), [examples/](examples/), [faq.md](faq.md),
[GLOSSARY.md](GLOSSARY.md).

---

## 3. By audience

| Audience | Start here | Then |
| --- | --- | --- |
| **New user / practitioner** | [getting_started.md](getting_started.md) | [installation.md](installation.md) → [user_guide.md](user_guide.md) → tutorials |
| **Developers / contributors** | [developer_guide.md](developer_guide.md) | [developer_guides/REPOSITORY_MAP.md](developer_guides/REPOSITORY_MAP.md), [EXTENSION_RECIPES.md](developer_guides/EXTENSION_RECIPES.md), [TESTING_AND_EVIDENCE.md](developer_guides/TESTING_AND_EVIDENCE.md), [../CONTRIBUTING.md](../CONTRIBUTING.md) |
| **Architect** | [architecture/README.md](architecture/README.md) | [SYSTEM_CONTEXT.md](architecture/SYSTEM_CONTEXT.md), [DOMAIN_MAP.md](architecture/DOMAIN_MAP.md), [decisions/](architecture/decisions/) |
| **Operator / deployer** | [guides/operations/DEPLOYMENT_AND_RUNTIME.md](guides/operations/DEPLOYMENT_AND_RUNTIME.md) | [MCP_SERVER_RUNBOOK.md](guides/operations/MCP_SERVER_RUNBOOK.md), [DIAGNOSTICS_AND_RECOVERY.md](guides/operations/DIAGNOSTICS_AND_RECOVERY.md), [PERFORMANCE_AND_CAPACITY.md](guides/operations/PERFORMANCE_AND_CAPACITY.md) |
| **Security reviewer** | [guides/security/THREAT_MODEL.md](guides/security/THREAT_MODEL.md) | [SECRETS_AND_CREDENTIALS.md](guides/security/SECRETS_AND_CREDENTIALS.md), [AUDIT_PROVENANCE_AND_INCIDENTS.md](guides/security/AUDIT_PROVENANCE_AND_INCIDENTS.md), [architecture/WALLET_TRUST_AND_PRIVACY.md](architecture/WALLET_TRUST_AND_PRIVACY.md) |
| **Agent / automation** | [developer_guides/FOR_AGENTS.md](developer_guides/FOR_AGENTS.md) | This portal + architecture hub + API index; prefer stable headings and validation commands |
| **Maintainer / doc owner** | [maintenance/INFORMATION_ARCHITECTURE.md](maintenance/INFORMATION_ARCHITECTURE.md) | [LEGACY_DISPOSITION.md](maintenance/LEGACY_DISPOSITION.md), [PACKAGE_LOCAL_DOCUMENTATION_MAP.md](maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md), [COVERAGE_MATRIX.md](maintenance/COVERAGE_MATRIX.md) |

---

## 4. Architecture

Canonical hub: **[architecture/README.md](architecture/README.md)**.

| Domain | Hub |
| --- | --- |
| System model | [SYSTEM_CONTEXT.md](architecture/SYSTEM_CONTEXT.md), [DOMAIN_MAP.md](architecture/DOMAIN_MAP.md), [END_TO_END_DATA_FLOW.md](architecture/END_TO_END_DATA_FLOW.md) |
| Processing | [architecture/processing/](architecture/processing/) |
| Storage / IPLD | [architecture/storage/](architecture/storage/) |
| Retrieval | [architecture/retrieval/](architecture/retrieval/) |
| Knowledge | [architecture/knowledge/](architecture/knowledge/) |
| Logic / proof | [architecture/logic/](architecture/logic/) |
| MCP | [architecture/mcp/](architecture/mcp/) |
| Runtime / agents | [architecture/runtime/](architecture/runtime/) |
| Wallet / trust | [WALLET_TRUST_AND_PRIVACY.md](architecture/WALLET_TRUST_AND_PRIVACY.md) |
| ADRs | [architecture/decisions/](architecture/decisions/) |

Plans under `architecture/*_PLAN.md` and `implementation/plans/` are **not**
current architecture.

---

## 5. Developers

| Page | Role |
| --- | --- |
| [developer_guide.md](developer_guide.md) | Contributor landing (setup + routes) |
| [developer_guides/REPOSITORY_MAP.md](developer_guides/REPOSITORY_MAP.md) | Repository layout |
| [developer_guides/EXTENSION_RECIPES.md](developer_guides/EXTENSION_RECIPES.md) | Extension patterns |
| [developer_guides/TESTING_AND_EVIDENCE.md](developer_guides/TESTING_AND_EVIDENCE.md) | Tests and evidence |
| [developer_guides/TROUBLESHOOTING.md](developer_guides/TROUBLESHOOTING.md) | Contributor troubleshooting |
| [developer_guides/CREATING_TOOLS.md](developer_guides/CREATING_TOOLS.md) | MCP / tool authoring |
| [developer_guides/DOCUMENTATION_CONTRIBUTING.md](developer_guides/DOCUMENTATION_CONTRIBUTING.md) | Doc authoring contract |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | Project contribution policy |

---

## 6. API

Canonical index: **[api/README.md](api/README.md)**.

| Domain page | Concern |
| --- | --- |
| [domains/CORE_AND_DATA.md](api/domains/CORE_AND_DATA.md) | Datasets, loaders, core data |
| [domains/PROCESSING_AND_RETRIEVAL.md](api/domains/PROCESSING_AND_RETRIEVAL.md) | Processors, embeddings, search |
| [domains/KNOWLEDGE_LOGIC_AND_PROOF.md](api/domains/KNOWLEDGE_LOGIC_AND_PROOF.md) | Knowledge graphs, logic, proof |
| [domains/MCP_AND_RUNTIME.md](api/domains/MCP_AND_RUNTIME.md) | MCP tools, runtime entrypoints |
| [domains/OPERATIONS_AND_INTEGRATIONS.md](api/domains/OPERATIONS_AND_INTEGRATIONS.md) | Ops, integrations, monitoring |
| [GENERATION_AND_FRESHNESS.md](api/GENERATION_AND_FRESHNESS.md) | Generated vs hand-maintained |

Legacy dumps (`OPTIMIZERS_API_REFERENCE.md`, TDFOL Sphinx under `tdfol/_build/`,
`*_stubs.md`) are **generated/historical discovery**, not public contract by
themselves. Prefer domain pages and package `__all__` / tests.

Also: [CORE_MODULES_API.md](CORE_MODULES_API.md), [CORE_OPERATIONS_GUIDE.md](CORE_OPERATIONS_GUIDE.md),
[guides/reference/](guides/reference/).

---

## 7. Operations

| Page | Role |
| --- | --- |
| [guides/operations/DEPLOYMENT_AND_RUNTIME.md](guides/operations/DEPLOYMENT_AND_RUNTIME.md) | Deploy and runtime surfaces |
| [guides/operations/MCP_SERVER_RUNBOOK.md](guides/operations/MCP_SERVER_RUNBOOK.md) | MCP server operations |
| [guides/operations/DIAGNOSTICS_AND_RECOVERY.md](guides/operations/DIAGNOSTICS_AND_RECOVERY.md) | Diagnostics and recovery |
| [guides/operations/PERFORMANCE_AND_CAPACITY.md](guides/operations/PERFORMANCE_AND_CAPACITY.md) | Performance and capacity |
| [guides/deployment/](guides/deployment/) | Docker / runner setup guides |
| [deployment/](deployment/) | Additional deployment notes |
| [guides/installation/CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md) | Capability extras detail |
| [guides/installation/CONFIGURATION_REFERENCE.md](guides/installation/CONFIGURATION_REFERENCE.md) | Full configuration catalog |

---

## 8. Security

| Page | Role |
| --- | --- |
| [guides/security/README.md](guides/security/README.md) | Security guides hub |
| [guides/security/THREAT_MODEL.md](guides/security/THREAT_MODEL.md) | Threat model |
| [guides/security/SECRETS_AND_CREDENTIALS.md](guides/security/SECRETS_AND_CREDENTIALS.md) | Secrets handling |
| [guides/security/security_governance.md](guides/security/security_governance.md) | Governance framework |
| [guides/security/audit_logging.md](guides/security/audit_logging.md) | Audit logging |
| [guides/security/AUDIT_PROVENANCE_AND_INCIDENTS.md](guides/security/AUDIT_PROVENANCE_AND_INCIDENTS.md) | Provenance and incidents |
| [architecture/WALLET_TRUST_AND_PRIVACY.md](architecture/WALLET_TRUST_AND_PRIVACY.md) | Wallet trust and privacy |
| [architecture/decisions/ADR-003-LAYERED-AUTHORITY.md](architecture/decisions/ADR-003-LAYERED-AUTHORITY.md) | Layered authority |
| [architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md](architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) | Fail-closed degradation |

---

## 9. Task routes (by job)

| I need to… | Go to |
| --- | --- |
| Install the package | [installation.md](installation.md) → [CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md) |
| Load or transform data | [user_guide.md](user_guide.md), [CORE_OPERATIONS_GUIDE.md](CORE_OPERATIONS_GUIDE.md), [architecture/processing/](architecture/processing/) |
| Run vector / RAG / GraphRAG | [tutorials/RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md](tutorials/RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md), [architecture/retrieval/](architecture/retrieval/), [architecture/knowledge/](architecture/knowledge/) |
| Process PDFs / files / media | [guides/pdf_processing.md](guides/pdf_processing.md), [guides/processors/](guides/processors/), [architecture/processing/](architecture/processing/) |
| Use MCP tools | [MCP_QUICKSTART.md](MCP_QUICKSTART.md), [MCP_TOOLS_GUIDE.md](MCP_TOOLS_GUIDE.md), [architecture/mcp/](architecture/mcp/), [api/domains/MCP_AND_RUNTIME.md](api/domains/MCP_AND_RUNTIME.md) |
| Work with IPLD / content addressing | [architecture/storage/](architecture/storage/), [IPLD_VECTOR_DATABASE_GUIDE.md](IPLD_VECTOR_DATABASE_GUIDE.md) (maintained product guide; plans/status siblings are historical) |
| Logic, provers, Intent IR | [architecture/logic/](architecture/logic/), [LOGIC_AND_PROOF_WORKFLOW.md](tutorials/LOGIC_AND_PROOF_WORKFLOW.md), [logic/](logic/) |
| Deploy / operate | §7 Operations |
| Review security / wallet | §8 Security |
| Extend the codebase | §5 Developers |
| Look up terms / authority words | [GLOSSARY.md](GLOSSARY.md) |
| See capability status | [FEATURES.md](FEATURES.md) |
| Understand release notes policy | [CHANGELOG.md](CHANGELOG.md) |

---

## 10. Deep component docs (not orphaned)

Product hubs above are the **navigation** authority. Module detail still lives
next to code and in domain leaves—link through, do not duplicate:

| Component | Package-local | Docs route |
| --- | --- | --- |
| Vector stores | [../ipfs_datasets_py/vector_stores/README.md](../ipfs_datasets_py/vector_stores/README.md) | [architecture/storage/](architecture/storage/), [architecture/retrieval/](architecture/retrieval/) |
| Search / RAG | [../ipfs_datasets_py/search/README.md](../ipfs_datasets_py/search/README.md) | [architecture/retrieval/](architecture/retrieval/) |
| Knowledge graphs | [../ipfs_datasets_py/knowledge_graphs/README.md](../ipfs_datasets_py/knowledge_graphs/README.md) | [architecture/knowledge/](architecture/knowledge/), [knowledge_graphs/](knowledge_graphs/) |
| Logic | [../ipfs_datasets_py/logic/README.md](../ipfs_datasets_py/logic/README.md) | [architecture/logic/](architecture/logic/), [logic/](logic/) |
| MCP server | [../ipfs_datasets_py/mcp_server/README.md](../ipfs_datasets_py/mcp_server/README.md) | [architecture/mcp/](architecture/mcp/) |
| Optimizers | [../ipfs_datasets_py/optimizers/README.md](../ipfs_datasets_py/optimizers/README.md) | [optimizers/](optimizers/), [api/README.md](api/README.md) |
| Audit | [../ipfs_datasets_py/audit/README.md](../ipfs_datasets_py/audit/README.md) | [guides/security/](guides/security/) |
| Utils | [../ipfs_datasets_py/utils/README.md](../ipfs_datasets_py/utils/README.md) | developer / API domain pages |

Full package-local inventory and disposition:
[PACKAGE_LOCAL_DOCUMENTATION_MAP.md](maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md).

The complete catalog of maintained routes is
**[DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md)**.

---

## 11. Historical, generated, and plans

| Kind | Location | Use |
| --- | --- | --- |
| **Historical** | [archive/](archive/), [archived_stubs/](archived_stubs/), [reports/](reports/), many root `*_COMPLETE.md` / session summaries | Audit trail only; not current product truth |
| **Generated** | [auto_generated_stubs/](auto_generated_stubs/), package `*_stubs.md`, [tdfol/_build/](tdfol/_build/), MkDocs `site/` (when built) | Regenerate from source; do not hand-author design here |
| **Plans** | [implementation/plans/](implementation/plans/), architecture `*_PLAN.md` | Intent / in-flight work; not shipped architecture |
| **Evidence** | [maintenance/](maintenance/), [maintenance/completion_receipts/](maintenance/completion_receipts/) | Point-in-time measurements and task receipts |

Directory roles and MkDocs notes: [README.md](README.md).

---

## 12. Sibling entry files (do not treat as competing landings)

| File | Role in the landing flow |
| --- | --- |
| **[index.md](index.md)** (this page) | **Canonical product landing** — audience and task routing |
| **[README.md](README.md)** | Docs-directory overview and lifecycle map; points here first |
| **[DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md)** | Deep maintained catalog by domain; not a second home page |

Older duplicates such as `DOCUMENTATION_INDEX_COMPLETE.md` and
`root_DOCUMENTATION_INDEX.md` are **superseded** by this triple; prefer the three
files above.

---

## 13. Explicit non-claims

This portal does **not**:

- assert February “latest features,” tool counts, test-coverage percentages, or
  phase-completion checkmarks as current product status;
- replace domain architecture leaves, ADRs, or API domain maps;
- promote plans, archives, or generated dumps to evergreen guidance;
- invent public API stability for every importable symbol.

For capability truth see [FEATURES.md](FEATURES.md). For architecture truth see
[architecture/README.md](architecture/README.md).
