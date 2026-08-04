# System context — IPFS Datasets Python

| Field | Value |
| --- | --- |
| Interface | `IPFSDatasetsSystemContext@1` |
| Task | `IPFSDOC-010` |
| Status | `canonical` |
| Owner | architecture |
| Source of truth | `ipfs_datasets_py/` package topology; `pyproject.toml` / `setup.py` packaging; `ipfs_datasets_py/logic/submodule_registry.py`; MCP entry (`mcp_server/__main__.py`, `mcp_server/__init__.py`); root CLI (`ipfs_datasets_cli.py`); tests under `tests/`; baseline `docs/maintenance/CURRENT_STATE_BASELINE.md`; authority `docs/maintenance/SOURCE_AUTHORITY.md` |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent, operator |
| Related | [DOMAIN_MAP.md](DOMAIN_MAP.md), [INFORMATION_ARCHITECTURE.md](../maintenance/INFORMATION_ARCHITECTURE.md), [COVERAGE_MATRIX.md](../maintenance/COVERAGE_MATRIX.md) |
| Review cadence | semi-annual or after major surface changes |

## 1. Purpose

This guide answers: **what is the system, who uses it, through which
supported surfaces, and what is explicitly outside its authority.** It is the
primary mental model for later architecture leaves (end-to-end flow,
dependencies, domain guides). Companion ownership detail lives in
[DOMAIN_MAP.md](DOMAIN_MAP.md).

Facts prefer the source-authority order: tests and schemas → current
implementation → packaging → operator manifests → accepted ADRs → maintained
guides → historical material
([SOURCE_AUTHORITY.md](../maintenance/SOURCE_AUTHORITY.md)).

## 2. Product in one paragraph

**IPFS Datasets Python** (`ipfs_datasets_py` **0.2.0**, `requires-python >= 3.12`)
is an IPFS-native data and AI platform package. It provides dataset
management, multimodal ingestion and processing, embeddings and vector
retrieval, knowledge graphs / GraphRAG, formal logic and IR families (legal,
security, intent), wallet/trust primitives, immutable voice-dataset release
contracts, and a large Model Context Protocol (MCP) tool surface for AI
assistants—wired through a modular package under `ipfs_datasets_py/` with
optional extras and external submodules.

## 3. Actors

| Actor | Role | Typical entry |
| --- | --- | --- |
| **End user / data practitioner** | Load, transform, search, and publish datasets; run scrapers and converters | Python API, CLI, tutorials |
| **AI assistant / MCP client** | Invoke registered tools (datasets, IPFS, graphs, media, legal, logic, etc.) over MCP | MCP stdio or HTTP; VS Code / Claude-style hosts |
| **Developer / contributor** | Extend domains, tools, optimizers, tests | Package imports, `tests/`, developer guides |
| **Architect / agent** | Place features, respect authority boundaries, avoid inventing competing roots | This document, DOMAIN_MAP, ADRs, registries |
| **Operator / deployer** | Run MCP/FastAPI services, Docker, k8s, config, monitoring | `docker/`, `deployments/`, config examples, systemd units |
| **Security / policy consumer** | Rely on IR identity, proof/admissibility gates, audit trails | `logic` IR/admissibility/proof_corpus; `wallet`; audit tools |
| **External prover / binary owner** | Supply Z3, CVC5, Lean, Coq, ErgoAI, CEC/Talos/ShadowProver, Groth16/Provekit assets | Optional installs; submodules; `ipfs-datasets-install-provers` |
| **Adjacent platform services** | IPFS kit, accelerate, agent supervisor (when present) | Git submodules / sibling packages — **not** owned by this tree |

**Authority note:** UI visibility, discovery, or a successful probe is not
authorization, proof, or production capability
([SOURCE_AUTHORITY.md](../maintenance/SOURCE_AUTHORITY.md) §2 kinds of truth).

## 4. Supported product surfaces

### 4.1 Python API (canonical library surface)

| Element | Path / symbol | Notes |
| --- | --- | --- |
| Package root | `ipfs_datasets_py` | Hermetic-by-default import; heavy subsystems opt-in via env flags |
| Explicit init | `ipfs_datasets_py.initialize(...)` | Process-wide router deps; optional SyMAI registration |
| Dataset helpers | `dataset_manager.DatasetManager`, `ipfs_datasets.py` | Used by MCP tools and library callers |
| Domain packages | See [DOMAIN_MAP.md](DOMAIN_MAP.md) | e.g. `processors`, `logic`, `vector_stores`, `knowledge_graphs` |
| Logic registry | `logic.submodule_registry` | Machine-readable map of logic families and public symbols |
| Routers | `*_router.py`, `router_deps` | Backend selection without hard-wiring optional stacks |

**Import policy (current tree):** Default package import avoids MCP, FastAPI,
LLM/transformers, and finance dashboard stacks unless
`IPFS_DATASETS_PY_ENABLE_*` or related flags are set. Minimal import mode:
`IPFS_DATASETS_PY_MINIMAL_IMPORTS` / `IPFS_DATASETS_PY_BENCHMARK`. Optional
import warnings are opt-in via `IPFS_DATASETS_PY_WARN_OPTIONAL_IMPORTS`.

### 4.2 CLI surfaces

| Surface | How invoked | Authority |
| --- | --- | --- |
| **Primary MCP-oriented CLI** | `ipfs_datasets_cli.py` / `cli_main`; repo wrapper `ipfs-datasets` | Implementation + `setup.py` entry points (see packaging drift below) |
| **Domain CLIs under package** | `ipfs_datasets_py.cli.*` (scraper, finance, discord, docket, workspace, …); `logic.cli`; `optimizers.cli`; `wallet.cli`; `search.cli`; `processors.cli` | Implementation |
| **Console scripts (`pyproject.toml`)** | `ipfs-datasets-install-provers`, `ipfs-datasets-sms-bridge`, `ipfs-netherlands-laws`, `netherlands-laws` | **Canonical install surface** for pure `pyproject` installs |
| **Console scripts (`setup.py` only)** | Also declares `ipfs-datasets`, `ipfs-datasets-cli`, `file-converter`, `fc` | Present in legacy/`setup.py` path; **not** in `pyproject.toml` `[project.scripts]` |

**Packaging drift (documented, not fixed here):** Installs driven only by
`pyproject.toml` expose four scripts; `setup.py` declares eight. Prefer
documenting both and naming which packaging path was used. Baseline:
[CURRENT_STATE_BASELINE.md](../maintenance/CURRENT_STATE_BASELINE.md) §6.

### 4.3 MCP server surface

| Element | Path | Role |
| --- | --- | --- |
| Module entry | `python -m ipfs_datasets_py.mcp_server` | Stdio (default) or HTTP (`--http`) |
| Public start API | `start_server`, `start_stdio_server`, `IPFSDatasetsMCPServer` | Package-exported server lifecycle |
| Client | `IPFSDatasetsMCPClient` | Optional MCP client |
| Tool tree | `mcp_server/tools/*` | Thin wrappers over domain packages (dataset, IPFS, graph, media, logic, legal, …) |
| FastAPI app | `mcp_server/fastapi_service.py` | HTTP/REST + MCP++ host path; Hypercorn+Trio preferred, uvicorn fallback |
| Config | `mcp_server/configs.py`, `config/mcp_config.yaml`, package config | Server and tool configuration |
| MCP++ | `mcp_server/mcplusplus` | Optional peer/workflow extensions |
| ADRs | `ipfs_datasets_py/mcp_server/docs/adr/` | Accepted design boundaries for MCP (package-local) |

**Architecture rule:** Core business logic lives in domain packages
(`processors`, `logic`, `vector_stores`, …). MCP tools **wrap** that logic;
imports flow tools → domains, not the reverse (see package MCP thin-tool
principle and historical `MCP_TOOLS_ARCHITECTURE.md`).

### 4.4 Service / ops surfaces

| Surface | Location | Role |
| --- | --- | --- |
| FastAPI HTTP service | `mcp_server/fastapi_service.py` (+ `extra = api`) | Authenticated HTTP access to tools/embeddings |
| Docker | root `Dockerfile`, `docker/*`, `mcp_server/Dockerfile*` | Containerized MCP / dashboard / test images |
| Compose | `docker-compose.yml`, `docker/docker-compose*.yml` | Local multi-service layouts |
| Deployments | `deployments/` (k8s, nginx, monitoring, SQL init, tdfol) | Production-oriented manifests |
| Systemd | `ipfs-datasets-mcp.service` | Host service unit for MCP |
| SMS bridge | `messaging.sms_bridge` console script | Messaging bridge process |
| Profile G service | `mcp_server/profile_g_service.py`, `profile_g.py` facade | Planning/evidence surface; side effects fail closed unless configured |

## 5. Context diagram (simplified)

```text
                    ┌──────────────────────────────────────┐
                    │  Actors                              │
                    │  Users · Agents · Operators · Devs   │
                    └──────────────────┬───────────────────┘
                                       │
          ┌────────────────────────────┼────────────────────────────┐
          │                            │                            │
          v                            v                            v
   Python API                   CLI wrappers                  MCP clients
   (import domains)          (cli_main, domain CLIs)     (stdio / HTTP / VS Code)
          │                            │                            │
          └────────────────────────────┼────────────────────────────┘
                                       │
                                       v
                    ┌──────────────────────────────────────┐
                    │  ipfs_datasets_py                     │
                    │  routers · dataset manager · config   │
                    ├──────────┬───────────┬────────────────┤
                    │          │           │                │
                    v          v           v                v
               processors   logic     knowledge/        vector/
               multimedia   IR/proof  optimizers        search
               web/legal    wallet    embeddings        storage
                    │          │           │                │
                    └──────────┴─────┬─────┴────────────────┘
                                     │
                    ┌────────────────┴────────────────┐
                    │  Optional / external             │
                    │  IPFS kit · accelerate · provers │
                    │  HF · Neo4j · FAISS/Qdrant/ES    │
                    │  CEC/Talos · ErgoAI · scrapers   │
                    └─────────────────────────────────┘
```

## 6. Canonical vs compatibility surfaces

| Kind | Examples | Rule for callers |
| --- | --- | --- |
| **Canonical** | Domain packages under `ipfs_datasets_py/`; `logic.integration` over `logic.tools`; `pyproject.toml` scripts and extras; `logic.submodule_registry` manifest; IR packages (`ir_core`, `intent_ir`, `security_ir`, `legal_ir`); MCP tools as thin wrappers | Prefer these paths in new code and docs |
| **Compatibility / alias** | `logic.tools` (deprecated → integration); root `setup.py`-only CLI names; package-root routers that re-export backends; empty submodule checkout dirs that still exist as paths | Supported for migration; do not treat as preferred design |
| **Facade** | `profile_g.py` → `logic.profile_g`; root `security.py`, `audit.py` | Thin entry; authority remains in owning domain |
| **Historical / non-authority** | `docs/archive/`, completion reports, `ARCHIVE/`, stub `*_stubs.md`, plans under `docs/implementation/plans/` | Navigation and intent history only |

## 7. Optional dependencies and external systems

### 7.1 Packaging extras (`pyproject.toml`)

Declared optional-dependency groups (18): `all`, `api`, `file_conversion`,
`groth16`, `ipld`, `knowledge_graphs`, `lazy`, `legal_netherlands`, `logic`,
`multimedia`, `ocr`, `profile-f-zk`, `provekit`, `scraping`, `symai_router`,
`test`, `theorem-provers`, `vectors`.

Core runtime dependencies are **dynamic** (resolved via `setup.py` so vendored
`ipfs_kit_py` / `ipfs_accelerate_py` checkouts can be preferred when present).

### 7.2 Git submodules (external ownership)

Declared in `.gitmodules` (typically **empty until initialized**):

| Path | Purpose |
| --- | --- |
| `ipfs_kit_py` (and `.tools/ipfs_kit_py`) | IPFS kit integration |
| `ipfs_accelerate_py` | Acceleration / distributed inference / agent-supervisor adjacency |
| `logic/CEC/{DCEC_Library,Talos,Eng-DCEC,ShadowProver}` | CEC theorem-prover assets |
| `multimedia/convert_to_txt_based_on_mime_type`, `multimedia/omni_converter_mk2` | Multimedia converters |
| `processors/web_archiving/common_crawl_search_engine` | Common Crawl search engine |

Empty submodule directories are **not** capability evidence. Document
submodule-backed features as optional and checkout-dependent.

### 7.3 External runtimes and services (not owned here)

- IPFS daemons / cluster peers (`ipfs_cluster`, kit-backed ops)
- Vector backends: FAISS, Qdrant, Elasticsearch (extras + `vector_stores`)
- Graph stores: Neo4j-compatible paths in `knowledge_graphs`
- Hugging Face Hub / `datasets` (`huggingface`, voice release paths)
- Theorem provers and ZKP toolchains (Z3, CVC5, Lean, Coq, SymbolicAI, circom/snarkjs, Provekit/Noir, Groth16 Rust)
- Browser automation (Playwright/Selenium) for scrapers and file conversion
- Agent supervisor / taskboards (accelerate family — fail-closed placement only)

## 8. Public contracts and evidence anchors

| Contract class | Anchors |
| --- | --- |
| Package identity | `pyproject.toml` name/version/python; `ipfs_datasets_py.__version__` |
| Console entry points | `pyproject.toml` `[project.scripts]`; `setup.py` `console_scripts`; egg-info |
| MCP lifecycle | `mcp_server.__main__`, `start_server` / `start_stdio_server` |
| Logic topology | `logic.submodule_registry.logic_integration_manifest`, `logic_submodule_specs` |
| Tests (examples) | `tests/unit/logic/test_logic_submodule_registry.py`; IR/authz integration under `tests/integration/logic/`; broad `tests/` tree (~3000 Python modules) |
| Config / deploy | `config.yaml.example`, `config/mcp_config.yaml`, `docker/`, `deployments/` |
| MCP design ADRs | `ipfs_datasets_py/mcp_server/docs/adr/` |

## 9. Responsibility and authority boundaries (system level)

| This system **owns** | This system **does not own** |
| --- | --- |
| Dataset-centric library APIs and processing pipelines in-tree | External IPFS daemon lifecycle and network policy |
| MCP tool registration and protocol adapters for those APIs | Third-party MCP host products (VS Code, Claude Desktop) |
| IR schemas, canonicalization, and local admissibility gates | Production authorization of remote side effects without configured validators |
| Packaging extras and declared install surface | Guaranteeing optional extras or empty submodules are present |
| Wallet models, grants, and privacy policy code in `wallet/` | Custody of user keys or real-world multi-sig infrastructure outside the package |
| Voice dataset schema, normalize, and release contracts | Hosting of Hugging Face or IPFS content |
| Documentation under `docs/` when marked canonical | Historical plans and session reports as product truth |

**Hard system invariants** (documentation and runtime framing):

1. Discovery ≠ capability; syntax ≠ semantics; model output ≠ proof.
2. Proof ≠ authorization; monitoring ≠ proof; UI visibility ≠ execution authority.
3. Simulated ZKP or stub backends are never production-authoritative
   (logic registry notes on `proof_corpus`, `admissibility`, `zkp`).
4. Profile G placement is advisory; leases and side effects remain external and
   fail closed unless validators are configured.

## 10. Non-goals

This system context document and the product boundary **do not** claim to:

- Replace end-to-end data-flow detail ([END_TO_END_DATA_FLOW.md](END_TO_END_DATA_FLOW.md) — planned sibling).
- Own agent-supervisor taskboard execution (accelerate / external runtime docs).
- Guarantee full capability without declared extras, prover binaries, or submodule checkout.
- Treat every file under `docs/` or package `*.md` as current architecture.
- Document session completion narratives as evergreen status.
- Change production code, protected plan files, or packaging as part of this guide.
- Assert a single “production ready” score from historical reports.

## 11. Related documents

| Document | Role |
| --- | --- |
| [DOMAIN_MAP.md](DOMAIN_MAP.md) | Per-domain ownership and boundaries |
| [CURRENT_STATE_BASELINE.md](../maintenance/CURRENT_STATE_BASELINE.md) | Measured inventory (domains, scripts, extras, submodules) |
| [COVERAGE_MATRIX.md](../maintenance/COVERAGE_MATRIX.md) | Doc coverage status per domain |
| [SOURCE_AUTHORITY.md](../maintenance/SOURCE_AUTHORITY.md) | Authority order and truth kinds |
| [PACKAGE_LOCAL_DOCUMENTATION_MAP.md](../maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md) | Package-local vs `docs/` ownership |
| MCP ADRs under `ipfs_datasets_py/mcp_server/docs/adr/` | MCP design decisions |
| Planned: `END_TO_END_DATA_FLOW.md`, `DEPENDENCY_AND_INITIALIZATION.md`, `INTEGRATION_BOUNDARIES.md` | Flow, init, and cross-repo boundaries |

## 12. Validation

Re-check this guide against the live tree when:

- Top-level package directories or console scripts change.
- Logic submodule registry specs change.
- MCP entry modes or FastAPI service ownership change.
- Submodule set in `.gitmodules` changes.

Focused commands (documentation task gate):

```bash
test -s docs/architecture/SYSTEM_CONTEXT.md && test -s docs/architecture/DOMAIN_MAP.md
rg -n 'processors|logic|mcp_server|optimizers|knowledge_graphs|vector_stores|wallet|voice' docs/architecture/DOMAIN_MAP.md
```

Evidence used for this revision: package directory inventory; `pyproject.toml`
scripts/extras; `logic/submodule_registry.py` (32 specs); MCP `__main__` /
`__init__`; baseline and coverage matrix measured 2026-08-03; CLI root module;
wallet/voice/optimizers package purposes from their `__init__` modules.
