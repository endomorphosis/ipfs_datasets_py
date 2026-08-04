# Documentation index (deep map)

| Field | Value |
| --- | --- |
| Interface | `DocumentationDeepIndex@1` |
| Task | `IPFSDOC-095` |
| Status | `canonical` (deep maintained catalog) |
| Owner | documentation-governance / navigation |
| Source of truth | Live `docs/` tree; architecture and API hubs; [PACKAGE_LOCAL_DOCUMENTATION_MAP.md](maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md) |
| Last verified | 2026-08-03 |
| Audience | developer, architect, operator, agent, maintainer (secondary: end-user via product landing) |
| Related | [index.md](index.md) (product landing), [README.md](README.md) (directory roles) |

> **Landing flow:** Start at **[index.md](index.md)** for audience/task routing.
> Use **this file** when you need the full maintained catalog by domain. Use
> **[README.md](README.md)** for maintained vs generated vs historical placement.
>
> This index is a **pointer map**, not a second product home page and not a
> place for February “latest,” tool-count, or completion claims.

---

## 1. Entry triple

| File | Role |
| --- | --- |
| [index.md](index.md) | Canonical product landing |
| [README.md](README.md) | Docs directory overview and lifecycle |
| [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md) (this page) | Deep map of maintained domains |

Superseded: `DOCUMENTATION_INDEX_COMPLETE.md`, `root_DOCUMENTATION_INDEX.md`
(do not expand; prefer this triple).

---

## 2. Getting Started

| Page | Role | Lifecycle |
| --- | --- | --- |
| [getting_started.md](getting_started.md) | Shortest verified first success | Maintained |
| [installation.md](installation.md) | Base + capability install | Maintained |
| [configuration.md](configuration.md) | Config precedence and env | Maintained |
| [user_guide.md](user_guide.md) | Supported user journeys | Maintained |
| [guides/installation/CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md) | Detailed extras / natives / offline | Maintained |
| [guides/installation/CONFIGURATION_REFERENCE.md](guides/installation/CONFIGURATION_REFERENCE.md) | Full configuration catalog | Maintained |
| [FEATURES.md](FEATURES.md) | Capability status matrix | Maintained |
| [faq.md](faq.md) | FAQ | Maintained |
| [GLOSSARY.md](GLOSSARY.md) | Authority vocabulary | Maintained |
| [CHANGELOG.md](CHANGELOG.md) | Release / change policy + history | Maintained |

### Tutorials (maintained workflows)

| Page | Role |
| --- | --- |
| [tutorials/FIRST_DATASET_WORKFLOW.md](tutorials/FIRST_DATASET_WORKFLOW.md) | Offline first dataset path |
| [tutorials/MCP_CLIENT_WORKFLOW.md](tutorials/MCP_CLIENT_WORKFLOW.md) | MCP client workflow |
| [tutorials/RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md](tutorials/RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md) | Retrieval and knowledge |
| [tutorials/LOGIC_AND_PROOF_WORKFLOW.md](tutorials/LOGIC_AND_PROOF_WORKFLOW.md) | Logic and proof (honest bounds) |
| [tutorials/graphrag_tutorial.md](tutorials/graphrag_tutorial.md) | GraphRAG walkthrough |
| [tutorials/web_archive_tutorial.md](tutorials/web_archive_tutorial.md) | Web archive processing |
| [tutorials/media_scraping_tutorial.md](tutorials/media_scraping_tutorial.md) | Media scraping |
| [tutorials/distributed_dataset_tutorial.md](tutorials/distributed_dataset_tutorial.md) | Distributed datasets |
| [tutorials/security_tutorial.md](tutorials/security_tutorial.md) | Security features tutorial |
| [tutorials/security_compliance_tutorial.md](tutorials/security_compliance_tutorial.md) | Compliance-oriented security |
| [tutorials/](tutorials/) | Tutorial index / remaining leaves |

### Examples

| Path | Role |
| --- | --- |
| [examples/](examples/) | Code samples and overviews |
| [examples/README.md](examples/README.md) | Examples hub |
| [user_guides/](user_guides/) | Additional user-oriented notes |

---

## 3. Architecture

Hub: **[architecture/README.md](architecture/README.md)** (maintained).

| Area | Path | Lifecycle |
| --- | --- | --- |
| System context | [architecture/SYSTEM_CONTEXT.md](architecture/SYSTEM_CONTEXT.md) | Maintained |
| Domain map | [architecture/DOMAIN_MAP.md](architecture/DOMAIN_MAP.md) | Maintained |
| End-to-end data flow | [architecture/END_TO_END_DATA_FLOW.md](architecture/END_TO_END_DATA_FLOW.md) | Maintained |
| Dependency / init | [architecture/DEPENDENCY_AND_INITIALIZATION.md](architecture/DEPENDENCY_AND_INITIALIZATION.md) | Maintained |
| Integration boundaries | [architecture/INTEGRATION_BOUNDARIES.md](architecture/INTEGRATION_BOUNDARIES.md) | Maintained |
| Runtime entrypoints | [architecture/RUNTIME_ENTRYPOINTS.md](architecture/RUNTIME_ENTRYPOINTS.md) | Maintained |
| Processing | [architecture/processing/](architecture/processing/) | Maintained |
| Storage / IPLD | [architecture/storage/](architecture/storage/) | Maintained |
| Retrieval | [architecture/retrieval/](architecture/retrieval/) | Maintained |
| Knowledge | [architecture/knowledge/](architecture/knowledge/) | Maintained |
| Logic | [architecture/logic/](architecture/logic/) | Maintained |
| MCP | [architecture/mcp/](architecture/mcp/) | Maintained |
| Runtime / agents | [architecture/runtime/](architecture/runtime/) | Maintained |
| Wallet / trust | [architecture/WALLET_TRUST_AND_PRIVACY.md](architecture/WALLET_TRUST_AND_PRIVACY.md) | Maintained |
| ADRs | [architecture/decisions/](architecture/decisions/) | Maintained (`accepted` ADRs) |
| Guide template | [architecture/ARCHITECTURE_GUIDE_TEMPLATE.md](architecture/ARCHITECTURE_GUIDE_TEMPLATE.md) | Template |
| `*_PLAN.md`, `*.objectives.md`, `*.todo.md` under architecture | various | **Plan** (not current architecture) |
| github_actions_*, submodule_*, static mcp_tools_* catalogs | under `architecture/` | **Historical** / discovery |

---

## 4. Developers

| Page | Role | Lifecycle |
| --- | --- | --- |
| [developer_guide.md](developer_guide.md) | Contributor landing | Maintained |
| [developer_guides/REPOSITORY_MAP.md](developer_guides/REPOSITORY_MAP.md) | Repo map | Maintained |
| [developer_guides/EXTENSION_RECIPES.md](developer_guides/EXTENSION_RECIPES.md) | Extension recipes | Maintained |
| [developer_guides/TESTING_AND_EVIDENCE.md](developer_guides/TESTING_AND_EVIDENCE.md) | Testing and evidence | Maintained |
| [developer_guides/FOR_AGENTS.md](developer_guides/FOR_AGENTS.md) | Agent contract | Maintained |
| [developer_guides/TROUBLESHOOTING.md](developer_guides/TROUBLESHOOTING.md) | Troubleshooting | Maintained |
| [developer_guides/CREATING_TOOLS.md](developer_guides/CREATING_TOOLS.md) | Creating tools | Maintained |
| [developer_guides/DOCUMENTATION_CONTRIBUTING.md](developer_guides/DOCUMENTATION_CONTRIBUTING.md) | Doc contribution | Maintained |
| [developer_guides/HANDOFF_CHECKLIST.md](developer_guides/HANDOFF_CHECKLIST.md) | Handoff checklist | Maintained |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | Project contributing | Maintained |

---

## 5. API

Hub: **[api/README.md](api/README.md)** (maintained).

| Page | Role | Lifecycle |
| --- | --- | --- |
| [api/domains/CORE_AND_DATA.md](api/domains/CORE_AND_DATA.md) | Core and data surfaces | Maintained |
| [api/domains/PROCESSING_AND_RETRIEVAL.md](api/domains/PROCESSING_AND_RETRIEVAL.md) | Processing and retrieval | Maintained |
| [api/domains/KNOWLEDGE_LOGIC_AND_PROOF.md](api/domains/KNOWLEDGE_LOGIC_AND_PROOF.md) | Knowledge, logic, proof | Maintained |
| [api/domains/MCP_AND_RUNTIME.md](api/domains/MCP_AND_RUNTIME.md) | MCP and runtime | Maintained |
| [api/domains/OPERATIONS_AND_INTEGRATIONS.md](api/domains/OPERATIONS_AND_INTEGRATIONS.md) | Ops and integrations | Maintained |
| [api/GENERATION_AND_FRESHNESS.md](api/GENERATION_AND_FRESHNESS.md) | Generation policy | Maintained |
| [api/CORE_OPERATIONS_API.md](api/CORE_OPERATIONS_API.md) | Core operations API notes | Maintained / review |
| [api/OPTIMIZERS_API_REFERENCE.md](api/OPTIMIZERS_API_REFERENCE.md) | Optimizers dump | **Generated** / discovery |
| [CORE_MODULES_API.md](CORE_MODULES_API.md) | Core modules API | Maintained |
| [CORE_OPERATIONS_GUIDE.md](CORE_OPERATIONS_GUIDE.md) | Core operations guide | Maintained |
| [guides/reference/](guides/reference/) | API reference folder | Mixed — prefer domain pages |
| Package `*_stubs.md`, [archived_stubs/](archived_stubs/), [auto_generated_stubs/](auto_generated_stubs/) | Signature dumps | **Generated** |
| [tdfol/](tdfol/) Sphinx sources + `_build/` | TDFOL reference build | Source maintained; `_build` **generated** |

---

## 6. Operations

| Page | Role | Lifecycle |
| --- | --- | --- |
| [guides/operations/DEPLOYMENT_AND_RUNTIME.md](guides/operations/DEPLOYMENT_AND_RUNTIME.md) | Deployment and runtime | Maintained |
| [guides/operations/MCP_SERVER_RUNBOOK.md](guides/operations/MCP_SERVER_RUNBOOK.md) | MCP server runbook | Maintained |
| [guides/operations/DIAGNOSTICS_AND_RECOVERY.md](guides/operations/DIAGNOSTICS_AND_RECOVERY.md) | Diagnostics and recovery | Maintained |
| [guides/operations/PERFORMANCE_AND_CAPACITY.md](guides/operations/PERFORMANCE_AND_CAPACITY.md) | Performance and capacity | Maintained |
| [guides/deployment/](guides/deployment/) | Docker / runners | Maintained (mixed age) |
| [deployment/](deployment/) | Deployment notes | Maintained / review |
| [guides/DEPLOYMENT_GUIDE.md](guides/DEPLOYMENT_GUIDE.md) | Deployment guide | Review — prefer ops leaves |
| [PERFORMANCE_TUNING_GUIDE.md](PERFORMANCE_TUNING_GUIDE.md) | Performance tuning | Review — cross-link ops |
| [TESTING_STRATEGY.md](TESTING_STRATEGY.md) | Testing strategy | Maintained / review |

---

## 7. Security

| Page | Role | Lifecycle |
| --- | --- | --- |
| [guides/security/README.md](guides/security/README.md) | Security hub | Maintained |
| [guides/security/THREAT_MODEL.md](guides/security/THREAT_MODEL.md) | Threat model | Maintained |
| [guides/security/SECRETS_AND_CREDENTIALS.md](guides/security/SECRETS_AND_CREDENTIALS.md) | Secrets | Maintained |
| [guides/security/security_governance.md](guides/security/security_governance.md) | Governance | Maintained |
| [guides/security/audit_logging.md](guides/security/audit_logging.md) | Audit logging | Maintained |
| [guides/security/audit_reporting.md](guides/security/audit_reporting.md) | Audit reporting | Maintained |
| [guides/security/AUDIT_PROVENANCE_AND_INCIDENTS.md](guides/security/AUDIT_PROVENANCE_AND_INCIDENTS.md) | Provenance and incidents | Maintained |
| [guides/security/auto_healing_security.md](guides/security/auto_healing_security.md) | Auto-healing security notes | Review |
| [architecture/WALLET_TRUST_AND_PRIVACY.md](architecture/WALLET_TRUST_AND_PRIVACY.md) | Wallet trust | Maintained |
| [architecture/decisions/ADR-003-LAYERED-AUTHORITY.md](architecture/decisions/ADR-003-LAYERED-AUTHORITY.md) | Layered authority | Accepted ADR |
| [architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md](architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) | Fail-closed degradation | Accepted ADR |
| [security_verification/](security_verification/) | Verification vectors / notes | Evidence / review |

---

## 8. Domain and product guide clusters

### MCP and tools

| Page | Lifecycle |
| --- | --- |
| [MCP_QUICKSTART.md](MCP_QUICKSTART.md) | Maintained |
| [MCP_TOOLS_GUIDE.md](MCP_TOOLS_GUIDE.md) | Maintained |
| [MCP_TESTING_GUIDE.md](MCP_TESTING_GUIDE.md) | Maintained / review |
| [architecture/mcp/](architecture/mcp/) | Maintained architecture |
| [guides/tools/](guides/tools/) | Mixed — route via MCP architecture + tools guide |
| Root `MCP_*` plans/status/summaries | **Historical** / plan — do not cite as current inventory |

### Processing, PDF, media

| Page | Lifecycle |
| --- | --- |
| [architecture/processing/](architecture/processing/) | Maintained |
| [guides/pdf_processing.md](guides/pdf_processing.md) | Maintained |
| [guides/processors/](guides/processors/) | Mixed: architecture + migration history |
| [FILE_CONVERTER_MIGRATION_GUIDE.md](FILE_CONVERTER_MIGRATION_GUIDE.md) | Migration (preserve; not evergreen design) |
| [modules/file_converter/](modules/file_converter/) | Module docs |

### Storage, IPLD, vectors

| Page | Lifecycle |
| --- | --- |
| [architecture/storage/](architecture/storage/) | Maintained |
| [architecture/retrieval/](architecture/retrieval/) | Maintained |
| [IPLD_VECTOR_DATABASE_GUIDE.md](IPLD_VECTOR_DATABASE_GUIDE.md) | Maintained product guide |
| [IPLD_VECTOR_STORE_QUICKSTART.md](IPLD_VECTOR_STORE_QUICKSTART.md) | Maintained / review |
| [IPLD_VECTOR_STORE_ARCHITECTURE.md](IPLD_VECTOR_STORE_ARCHITECTURE.md) | Review — prefer architecture/storage |
| Root IPLD `*_SESSION_*`, `*_COMPLETE*`, `*_PLAN*` | **Historical** / plan |

### Knowledge graphs and GraphRAG

| Page | Lifecycle |
| --- | --- |
| [architecture/knowledge/](architecture/knowledge/) | Maintained |
| [knowledge_graphs/](knowledge_graphs/) | Maintained product docs + archive subdir |
| [guides/knowledge_graphs/](guides/knowledge_graphs/) | Mixed guides |
| [GRAPHRAG_CONSOLIDATION_GUIDE.md](GRAPHRAG_CONSOLIDATION_GUIDE.md) | Maintained / review |
| [optimizers/](optimizers/) | Optimizers + GraphRAG material (mixed) |

### Logic, TDFOL, proof

| Page | Lifecycle |
| --- | --- |
| [architecture/logic/](architecture/logic/) | Maintained |
| [logic/](logic/) | Product logic docs; versioned plans → **Historical** |
| [tdfol/](tdfol/) | TDFOL docs; `_build` **generated** |
| [tutorials/LOGIC_AND_PROOF_WORKFLOW.md](tutorials/LOGIC_AND_PROOF_WORKFLOW.md) | Maintained |

### Legal / scrapers / web

| Page | Lifecycle |
| --- | --- |
| [guides/legal_data/](guides/legal_data/) | Domain guides |
| [guides/comprehensive_web_scraping_guide.md](guides/comprehensive_web_scraping_guide.md) | Review |
| [LEGAL_SCRAPERS_COMMON_CRAWL_GUIDE.md](LEGAL_SCRAPERS_COMMON_CRAWL_GUIDE.md) | Review |
| Operator runbooks under root `LEGAL_*` | Ops / review — not architecture authority |

---

## 9. Deep component docs (package-local)

Do **not** orphan package READMEs. Navigation hubs link here; bodies stay local
until a reviewed migration.

| Component | Package README | Docs / architecture route |
| --- | --- | --- |
| Vector stores | [../ipfs_datasets_py/vector_stores/README.md](../ipfs_datasets_py/vector_stores/README.md) | architecture/storage, architecture/retrieval |
| Search | [../ipfs_datasets_py/search/README.md](../ipfs_datasets_py/search/README.md) | architecture/retrieval |
| Knowledge graphs | [../ipfs_datasets_py/knowledge_graphs/README.md](../ipfs_datasets_py/knowledge_graphs/README.md) | architecture/knowledge, knowledge_graphs/ |
| Logic | [../ipfs_datasets_py/logic/README.md](../ipfs_datasets_py/logic/README.md) | architecture/logic, logic/ |
| MCP server | [../ipfs_datasets_py/mcp_server/README.md](../ipfs_datasets_py/mcp_server/README.md) | architecture/mcp; package ADRs under mcp_server/docs/adr/ |
| Optimizers | [../ipfs_datasets_py/optimizers/README.md](../ipfs_datasets_py/optimizers/README.md) | optimizers/, api/ |
| Audit | [../ipfs_datasets_py/audit/README.md](../ipfs_datasets_py/audit/README.md) | guides/security/ |
| Utils | [../ipfs_datasets_py/utils/README.md](../ipfs_datasets_py/utils/README.md) | API / developer routes |
| Error reporting | [../ipfs_datasets_py/error_reporting/README.md](../ipfs_datasets_py/error_reporting/README.md) | Operations / diagnostics |

Full inventory and disposition labels:
[PACKAGE_LOCAL_DOCUMENTATION_MAP.md](maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md).

---

## 10. Historical material

| Location | Role |
| --- | --- |
| [archive/](archive/) | Archived completion, deprecated, reorganization, status reports |
| [archived_stubs/](archived_stubs/) | Relocated generated stubs |
| [reports/](reports/) | Project and session reports |
| [reorganization/](reorganization/) | Reorganization notes |
| Root phase/session/completion clusters | Prefer architecture + maintenance evidence |
| [LEGACY_DISPOSITION.md](maintenance/LEGACY_DISPOSITION.md) | Disposition map for legacy units |

**Historical is preserved for audit.** It is not current product or architecture
authority.

---

## 11. Generated material

| Location | Role |
| --- | --- |
| [auto_generated_stubs/](auto_generated_stubs/) | Stub home / policy |
| Package and archived `*_stubs.md` | Signature dumps |
| [tdfol/_build/](tdfol/_build/) | Sphinx HTML output |
| MkDocs `site/` | Build output when present |
| [api/GENERATION_AND_FRESHNESS.md](api/GENERATION_AND_FRESHNESS.md) | How generation is governed |

---

## 12. Plans and evidence

| Location | Lifecycle |
| --- | --- |
| [implementation/plans/](implementation/plans/) | **Plan** (program inputs; some protected) |
| Architecture / domain `*_PLAN.md` | **Plan** |
| [maintenance/](maintenance/) | **Evidence** + governance policy |
| [maintenance/completion_receipts/](maintenance/completion_receipts/) | **Evidence** (task receipts) |
| [benchmarks/](benchmarks/), [performance_snapshots/](performance_snapshots/), [profiling/](profiling/) | **Evidence** / review |

---

## 13. Maintenance and quality

| Page | Role |
| --- | --- |
| [maintenance/INFORMATION_ARCHITECTURE.md](maintenance/INFORMATION_ARCHITECTURE.md) | Writing and lifecycle contract |
| [maintenance/SOURCE_AUTHORITY.md](maintenance/SOURCE_AUTHORITY.md) | Authority order |
| [maintenance/COVERAGE_MATRIX.md](maintenance/COVERAGE_MATRIX.md) | Coverage matrix |
| [maintenance/CURRENT_STATE_BASELINE.md](maintenance/CURRENT_STATE_BASELINE.md) | Measured baseline |
| [maintenance/DRIFT_AND_CLAIM_MATRIX.md](maintenance/DRIFT_AND_CLAIM_MATRIX.md) | Claim drift |
| [maintenance/LEGACY_DISPOSITION.md](maintenance/LEGACY_DISPOSITION.md) | Legacy disposition |
| [maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md](maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md) | Package-local map |
| [maintenance/EXAMPLE_VERIFICATION.md](maintenance/EXAMPLE_VERIFICATION.md) | Example verification |
| [maintenance/VALIDATION_RUNBOOK.md](maintenance/VALIDATION_RUNBOOK.md) | Validation runbook |
| [maintenance/check_docs.py](maintenance/check_docs.py) | Doc check tool |

---

## 14. How to update this index

1. Prefer **one maintained home** per concern ([INFORMATION_ARCHITECTURE.md](maintenance/INFORMATION_ARCHITECTURE.md)).
2. Add repository-relative links from this file when a **maintained** page is
   created or promoted.
3. Route entry-relevant changes through [index.md](index.md) as well.
4. Classify new material as maintained, generated, plan, evidence, or
   historical—never as undated “latest.”
5. Do not reintroduce competing root indexes.

Validation (navigation owner):

```bash
test -s docs/index.md && test -s docs/README.md && test -s docs/DOCUMENTATION_INDEX.md && \
  rg -n 'Getting Started|Architecture|Developers|API|Operations|Security|Historical' \
  docs/index.md docs/README.md docs/DOCUMENTATION_INDEX.md
```
