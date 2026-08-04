# IPFS Datasets Python User Guide

| Field | Value |
| --- | --- |
| Interface | `UserGuide@1` |
| Task | `IPFSDOC-092` |
| Status | `canonical` (root user journeys) |
| Owner | user-docs |
| Package | `ipfs_datasets_py` **0.2.0** (`requires-python >= 3.12`) |
| Last verified | 2026-08-03 |
| Audience | end-user, developer, agent, operator |
| Related | [getting_started.md](getting_started.md), [installation.md](installation.md), [configuration.md](configuration.md), [FEATURES.md](FEATURES.md), [tutorials/](tutorials/) |

This guide maps **supported user journeys** to canonical tutorials and API /
architecture references. It replaces legacy package-root demos that imported
missing modules (`ipfs_knn_index`, `knowledge_graph`, invented
`EmbeddingGenerator` / `UnifiedGraphRAGQueryOptimizer` paths, etc.) and invalid
extras (`theorem_proving`, `graphrag`, `vector`, …).

**How to use this page**

1. Complete the [shortest first success](getting_started.md) once.
2. Pick a journey below.
3. Follow the linked **tutorial** for bounded steps, evidence, and cleanup.
4. Use **domain API** and **architecture** pages for signatures and authority—
   not obsolete code blocks on this page.

---

## 1. Core concepts (current)

| Concept | Meaning in this project |
| --- | --- |
| **Dataset processing** | Load/save/convert/transform via `ipfs_datasets_py.core_operations` and related processors |
| **Content identity** | Digests / CIDs for bytes or IPLD structures—not mock pin strings |
| **Optional capabilities** | Extras, natives, submodules; may be **unavailable** without failing base import ([ADR-002](architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md)) |
| **Retrieval** | Embeddings + vector indexes + search **scores** (not facts, not proof) |
| **Knowledge** | Graph entities/relationships as committed facts (not theorem proof) |
| **Logic / proof** | Syntax validation, formalization contracts, provers, **typed result authority**—layers are not interchangeable ([ADR-003](architecture/decisions/ADR-003-LAYERED-AUTHORITY.md)) |
| **MCP / runtime** | Tool discovery, policy, dispatch; transport success ≠ domain success ([ADR-007](architecture/decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md)) |
| **Fail-closed degradation** | Missing deps produce labeled errors / mocks—not silent trust ([ADR-004](architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md)) |

Capability status vocabulary (stable / optional / experimental / compatibility /
deprecated / **unavailable**): [FEATURES.md](FEATURES.md).

---

## 2. Install and configuration (route only)

| Need | Canonical page |
| --- | --- |
| Base install, real extras, natives, offline | [installation.md](installation.md) → [CAPABILITY_INSTALLATION](guides/installation/CAPABILITY_INSTALLATION.md) |
| Env / CLI / hermetic / secrets precedence | [configuration.md](configuration.md) → [CONFIGURATION_REFERENCE](guides/installation/CONFIGURATION_REFERENCE.md) |
| First offline success | [getting_started.md](getting_started.md) |

### Valid vs invalid extras (summary)

| Invalid / stale name | Use instead |
| --- | --- |
| `theorem_proving` / `theorem-prover` | `theorem-provers` (+ managed natives via `ipfs-datasets-install-provers`) |
| `graphrag` | `knowledge_graphs` (+ app GraphRAG config; see retrieval tutorial) |
| `vector` | `vectors` |
| `webarchive` / `web-archive` | `web_archive` |
| `dev` as pyproject extra | Prefer `test` / requirements + developer_guide; not a declared optional product extra on the root install page |

Full catalog: CAPABILITY_INSTALLATION §4.

---

## 3. Journey map

| Journey | Canonical tutorial | Domain API | Architecture |
| --- | --- | --- | --- |
| Processing / storage | [FIRST_DATASET_WORKFLOW.md](tutorials/FIRST_DATASET_WORKFLOW.md) | [CORE_AND_DATA.md](api/domains/CORE_AND_DATA.md) | [storage/README.md](architecture/storage/README.md), [processing/](architecture/processing/) |
| Python / CLI / MCP | [MCP_CLIENT_WORKFLOW.md](tutorials/MCP_CLIENT_WORKFLOW.md) | [MCP_AND_RUNTIME.md](api/domains/MCP_AND_RUNTIME.md) | [mcp/README.md](architecture/mcp/README.md), [MCP_QUICKSTART.md](MCP_QUICKSTART.md) |
| Retrieval / knowledge | [RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md](tutorials/RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md) | [PROCESSING_AND_RETRIEVAL.md](api/domains/PROCESSING_AND_RETRIEVAL.md), [KNOWLEDGE_LOGIC_AND_PROOF.md](api/domains/KNOWLEDGE_LOGIC_AND_PROOF.md) | [retrieval/README.md](architecture/retrieval/README.md), [knowledge/README.md](architecture/knowledge/README.md) |
| Logic / proof | [LOGIC_AND_PROOF_WORKFLOW.md](tutorials/LOGIC_AND_PROOF_WORKFLOW.md) | [KNOWLEDGE_LOGIC_AND_PROOF.md](api/domains/KNOWLEDGE_LOGIC_AND_PROOF.md) | [logic/](architecture/logic/), [RESULT_AUTHORITY.md](architecture/logic/RESULT_AUTHORITY.md) |
| Operations | §7 below + ops runbooks | [OPERATIONS_AND_INTEGRATIONS.md](api/domains/OPERATIONS_AND_INTEGRATIONS.md) | [guides/operations/](guides/operations/), [WALLET_TRUST_AND_PRIVACY.md](architecture/WALLET_TRUST_AND_PRIVACY.md) |

---

## 4. Processing and storage journeys

**Start:** [FIRST_DATASET_WORKFLOW.md](tutorials/FIRST_DATASET_WORKFLOW.md)
(IPFSDOC-083). Upstream for most data work.

### Goals

- Materialize local datasets without network.
- Save / convert / process with `DatasetSaver`, `DatasetConverter`, `DataProcessor`.
- Separate offline JSON I/O from optional Hugging Face `DatasetLoader`.
- Compute content digests; label mock IPFS pins honestly.

### Canonical imports (prefer these)

```python
from ipfs_datasets_py.core_operations import (
    DatasetLoader,
    DatasetSaver,
    DatasetConverter,
    DataProcessor,
    IPFSPinner,
    IPFSGetter,
)
from ipfs_datasets_py.storage import MockStorageManager, StorageType, CompressionType
```

**Offline-first durable write:** prefer plain `pathlib` + `json` (as in
[getting_started.md](getting_started.md) and FIRST_DATASET §4/§6.1). Use
`DataProcessor` for transforms/chunks. `DatasetSaver` / `DatasetConverter`
expose CLI/MCP-shaped **envelopes**; confirm on-disk evidence when you need a
real file. `MockStorageManager` is in-process **mock** storage only.

### Optional requirements

| Optional | If missing |
| --- | --- |
| `datasets` (HF) | `DatasetLoader` → **unavailable**/error; use plain JSON |
| IPFS daemon / pin path | `IPFSPinner` may return **mock** `Qm…` — not identity |
| Parquet/Arrow writers | Stick to JSON for first path |

### Side effects and cleanup

| Action | Side effect | Cleanup |
| --- | --- | --- |
| Temp workspace | Files under system temp | `shutil.rmtree(work)` |
| Real IPFS pin | Network + local repo growth | Unpin / remove only what you own |
| Auto-install | May run `pip` at use time | Disable for hermetic hosts |

### Unavailable / degraded

| Outcome | Treat as |
| --- | --- |
| `status="error"` missing `datasets` | **Unavailable** loader path |
| Mock storage / mock CID | Demo only — not multi-host durability |
| Saver/converter success envelope without observed file | Envelope-only path — not claimed multi-format durability here |
| Convert/save format error | Unsupported or missing writer — not silent success |

**References:** [CORE_AND_DATA.md](api/domains/CORE_AND_DATA.md),
[CONTENT_ADDRESSING_AND_IPLD.md](architecture/storage/CONTENT_ADDRESSING_AND_IPLD.md),
[ADR-001](architecture/decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md).

---

## 5. Python, CLI, and MCP journeys

**Start:** [MCP_CLIENT_WORKFLOW.md](tutorials/MCP_CLIENT_WORKFLOW.md)
(IPFSDOC-084). Also: [MCP_QUICKSTART.md](MCP_QUICKSTART.md),
[cli_quick_start.md](quickstart/cli_quick_start.md).

### Python

```bash
python -c "import ipfs_datasets_py; print(ipfs_datasets_py.__version__)"
```

Use domain packages documented in [api/domains/](api/domains/) rather than
stale root re-exports.

### CLI

| Entry | Role |
| --- | --- |
| `python ipfs_datasets_cli.py …` | Always available from repository root |
| `ipfs-datasets` / `ipfs-datasets-cli` | setuptools console scripts (when installed) |
| `ipfs-datasets-install-provers` | Managed native prover install (not a dataset CLI) |

```bash
python ipfs_datasets_cli.py --help
python ipfs_datasets_cli.py info version
python ipfs_datasets_cli.py info status
```

Missing console-script on `PATH` after a minimal install is a **packaging/
PATH compatibility** issue—use the tree script. See installation.md console
scripts table.

### MCP (local-first)

The verified tutorial route is **in-process** discovery/dispatch (no required
HTTP daemon). Optional HTTP client / live server paths degrade when the SDK or
server is **unavailable**.

| Step | Tutorial section | Success means |
| --- | --- | --- |
| Discover tools | MCP_CLIENT_WORKFLOW | Catalog / schema probe only |
| Invoke local tool | same | Typed result receipt |
| Denial | same | Unknown tool → fail closed |
| Unavailable | same | Missing SDK/deps labeled — not invent tools |

**Never claim:** tool list presence, HTTP 200, or `allowed` policy as theorem
proof or dataset identity.

### Optional requirements

| Optional | If missing |
| --- | --- |
| `mcp` / MCP SDK + `anyio` | HTTP client path **unavailable** |
| Live MCP server | Skip network path; local hierarchical still usable per tutorial |
| HF `datasets` inside tools | Tool error envelope |

### Side effects and cleanup

| Action | Side effect | Cleanup |
| --- | --- | --- |
| Start MCP server / dashboard | Ports, logs, processes | Stop server; rotate/redact logs |
| Dispatch | Tool-specific I/O | Prefer temp dirs; delete artifacts |
| Auth tokens | Secrets in env | Never commit; see secrets guide |

**References:** [MCP_AND_RUNTIME.md](api/domains/MCP_AND_RUNTIME.md),
[SERVER_AND_DISPATCH.md](architecture/mcp/SERVER_AND_DISPATCH.md),
[POLICY_AND_AUTHORIZATION.md](architecture/mcp/POLICY_AND_AUTHORIZATION.md),
[MCP_SERVER_RUNBOOK.md](guides/operations/MCP_SERVER_RUNBOOK.md).

---

## 6. Retrieval and knowledge journeys

**Start:** [RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md](tutorials/RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md)
(IPFSDOC-083). Complete [FIRST_DATASET_WORKFLOW](tutorials/FIRST_DATASET_WORKFLOW.md)
first if you need local dataset patterns.

### Goals

- Generate embeddings; detect **fallback** constant vectors.
- Build local ANN (FAISS) or mock index; run top-k.
- Create in-memory graph facts; separate score vs fact vs proof.

### Optional requirements

| Extra / dep | If missing |
| --- | --- |
| `vectors` / `sentence-transformers` | Fallback embeddings — **not** production similarity |
| `faiss` / `faiss-cpu` | Use mock vector service; scores synthetic |
| `knowledge_graphs` | NLP extraction may be **unavailable**; memory graph demos may still run |
| Qdrant / ES / Neo4j daemons | Out of scope for offline first path |

### Side effects and cleanup

| Action | Side effect | Cleanup |
| --- | --- | --- |
| First ST model use | May download weights to HF cache | Manage cache size; offline flags when needed |
| FAISS index write | Files under index/metadata paths | Point at temp dirs; delete after demo |
| Graph export | Optional remote DB | Do not leave production credentials in examples |

### Unavailable / degraded

| Outcome | Meaning |
| --- | --- |
| Fallback embedding | Capability degraded — label it |
| Mock search scores | Not ranking evidence |
| Graph fact | Not theorem proof |
| Missing remote store | Feature **unavailable** offline |

**Do not use (legacy on old user_guide pages):**

- `from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndex` (not at package root)
- `from ipfs_datasets_py.embeddings import EmbeddingGenerator` (not a public export)
- `from ipfs_datasets_py.knowledge_graph import IPLDKnowledgeGraph` (package is `knowledge_graphs`)
- Invented optimizers under missing `rag.rag_query_optimizer`

Use tutorial imports and [PROCESSING_AND_RETRIEVAL.md](api/domains/PROCESSING_AND_RETRIEVAL.md).

---

## 7. Logic and proof journeys

**Start:** [LOGIC_AND_PROOF_WORKFLOW.md](tutorials/LOGIC_AND_PROOF_WORKFLOW.md)
(IPFSDOC-084). Sibling service plane: [MCP_CLIENT_WORKFLOW.md](tutorials/MCP_CLIENT_WORKFLOW.md).

### Goals

- Probe logic capabilities without claiming proof.
- Validate formula **syntax** as non-proof evidence.
- Use formalization contracts; probe provers with timeouts.
- Inspect typed `ResultAuthority`; refuse kind substitution.
- Evaluate policy as **policy-layer** only.

### Optional requirements

| Optional | If missing |
| --- | --- |
| `z3-solver` / CVC5 / Lean / Coq | Prover route **unavailable**; fail closed for production trust |
| `theorem-provers` extra | Python bindings may be missing |
| CEC / ErgoAI submodules | Deep engines **unavailable** if empty submodule |
| ZKP extras | Simulated ZKP remains non-authoritative |

### Side effects and cleanup

| Action | Side effect | Cleanup |
| --- | --- | --- |
| First prover use | CPU, processes, possible downloads | Bound timeouts; kill hung solvers |
| Managed installers | Binaries under `~/.local/share/ipfs_datasets_py/…` | Track disk; do not auto-install in prod |
| Artifacts | Proof/policy files | Redact secrets; delete temp workspaces |

### Unavailable / degraded

| Outcome | **Not** |
| --- | --- |
| Parser / NL formalization success | Theorem proof |
| SAT/model/optimizer score | Proof |
| Policy `allowed` | Proof or dataset identity |
| Prover returns unknown | Failure of the math claim — still valid **probe** evidence |

**References:** [KNOWLEDGE_LOGIC_AND_PROOF.md](api/domains/KNOWLEDGE_LOGIC_AND_PROOF.md),
[EXTERNAL_PROVERS.md](architecture/logic/EXTERNAL_PROVERS.md),
[RESULT_AUTHORITY.md](architecture/logic/RESULT_AUTHORITY.md).

---

## 8. Operations journeys

There is no single “ops tutorial” in `docs/tutorials/`; operations are
**runbook- and domain-reference-driven**.

| Concern | Canonical guide |
| --- | --- |
| Deployment / runtime | [DEPLOYMENT_AND_RUNTIME.md](guides/operations/DEPLOYMENT_AND_RUNTIME.md), [deployment.md](deployment.md) |
| MCP server operations | [MCP_SERVER_RUNBOOK.md](guides/operations/MCP_SERVER_RUNBOOK.md) |
| Diagnostics / recovery | [DIAGNOSTICS_AND_RECOVERY.md](guides/operations/DIAGNOSTICS_AND_RECOVERY.md) |
| Performance / capacity | [PERFORMANCE_AND_CAPACITY.md](guides/operations/PERFORMANCE_AND_CAPACITY.md) |
| Audit, wallet, monitoring surfaces | [OPERATIONS_AND_INTEGRATIONS.md](api/domains/OPERATIONS_AND_INTEGRATIONS.md) |
| Secrets / credentials | [SECRETS_AND_CREDENTIALS.md](guides/security/SECRETS_AND_CREDENTIALS.md) |
| Wallet trust / privacy | [WALLET_TRUST_AND_PRIVACY.md](architecture/WALLET_TRUST_AND_PRIVACY.md) |

### Optional requirements

Container images, GPU wheels, live IPFS, and production IdP are **environment-
specific**. Do not invent placeholder registries (`yourorga/…`). Prefer building
from this repository when you need a known tree.

### Side effects and cleanup

| Action | Side effect | Cleanup |
| --- | --- | --- |
| Deploy services | Host ports, volumes, credentials | Tear down non-prod stacks; rotate secrets |
| Enable auto-install | Mutable dependency surface | `IPFS_DATASETS_AUTO_INSTALL=false` in prod |
| Monitoring / audit | Log volume, PII risk | Retention + redaction policy |

### Unavailable / degraded

| Outcome | Operator action |
| --- | --- |
| Empty git submodules | Nested backends **unavailable** until initialized |
| Missing native tools | Feature disabled; document, do not fake success |
| Probe green, policy deny | Fail closed — probe ≠ authorize |

---

## 9. Cross-cutting: optional, side effects, cleanup, compatibility, unavailable

| Concern | Rule of thumb |
| --- | --- |
| **Optional requirements** | Declare extras/binaries per journey; base install stays lean |
| **Side effects** | Downloads, temp files, ports, auto-install, prover CPU |
| **Cleanup** | Temp dirs, local indexes, stopped servers, redacted logs |
| **Compatibility** | Prefer current domain imports; treat root lazy re-exports as compatibility only |
| **Unavailable / degraded** | Label error/mock/fallback; never upgrade them to “proven” or “pinned” |

### Removed / do-not-follow legacy patterns

These appeared on older user-guide and getting-started pages and are **not**
authoritative:

| Stale pattern | Replacement |
| --- | --- |
| `pip install …[theorem_proving]` / `[graphrag]` / `[dev]` as primary paths | Real extras + tutorials above |
| `ipfs_datasets.load_dataset` as primary API | Offline JSON + `core_operations` / HF when available |
| Package-root `IPFSKnnIndex`, `IPLDKnowledgeGraph`, `EmbeddingGenerator`, `DuckDBConnector`, `EnhancedProvenanceManager` demos | Domain maps + tutorials |
| “100% success / under 5 minutes / production ready” marketing claims | Evidence tables in tutorials + EXAMPLE_VERIFICATION |
| Placeholder orgs / Docker `yourorga` | `endomorphosis/ipfs_datasets_py` and real deploy docs |

---

## 10. Troubleshooting (short)

| Symptom | Check |
| --- | --- |
| Import works, feature fails later | Missing **optional** extra/binary → **unavailable** path |
| HF load fails offline | Expected without `datasets`/network — use FIRST_DATASET offline JSON |
| CLI not found | Use `python ipfs_datasets_cli.py` from repo root |
| MCP HTTP client None | Install SDK or use local hierarchical route in MCP_CLIENT_WORKFLOW |
| Prover unknown / missing | Not proof; install `theorem-provers` / natives only if needed |
| Mock CID treated as identity | Stop — re-read ADR-001 and FIRST_DATASET storage section |

More: [DIAGNOSTICS_AND_RECOVERY.md](guides/operations/DIAGNOSTICS_AND_RECOVERY.md),
[faq.md](faq.md), [EXAMPLE_VERIFICATION.md](maintenance/EXAMPLE_VERIFICATION.md).

---

## 11. Related indexes

| Index | Role |
| --- | --- |
| [getting_started.md](getting_started.md) | Shortest first success |
| [tutorials/README.md](tutorials/README.md) / [tutorials/index.md](tutorials/index.md) | Tutorial hub |
| [api/README.md](api/README.md) | Domain API map |
| [architecture/README.md](architecture/README.md) | Architecture hub |
| [FEATURES.md](FEATURES.md) | Capability matrix |
| [developer_guide.md](developer_guide.md) | Contributor entry |

---

**Non-claims:** this guide does not re-certify production readiness of optional
stacks, invent missing modules, or treat probe/tool/policy success as proof.
Authority order: tests/schemas → current code → packaging → ADRs → guides →
history ([SOURCE_AUTHORITY.md](maintenance/SOURCE_AUTHORITY.md)).
