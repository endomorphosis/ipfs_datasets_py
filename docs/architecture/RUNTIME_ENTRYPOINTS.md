# Runtime entry points

| Field | Value |
| --- | --- |
| Interface | `RuntimeEntrypointMap@1` |
| Task | `IPFSDOC-011` |
| Status | `canonical` |
| Owner | architecture |
| Source of truth | `pyproject.toml` `[project.scripts]`; `setup.py` `entry_points`; `ipfs_datasets_py.egg-info/entry_points.txt`; `ipfs_datasets_cli.py`; `ipfs_datasets_py/__init__.py`; `mcp_server/__main__.py` / `server.py`; domain `**/cli.py`; [CURRENT_STATE_BASELINE.md](../maintenance/CURRENT_STATE_BASELINE.md) §6; [SYSTEM_CONTEXT.md](SYSTEM_CONTEXT.md) |
| Last verified | 2026-08-03 |
| Audience | operator, developer, architect, agent |
| Related | [END_TO_END_DATA_FLOW.md](END_TO_END_DATA_FLOW.md), [DOMAIN_MAP.md](DOMAIN_MAP.md) |
| Review cadence | after packaging or CLI surface changes |

## 1. Purpose

This guide answers: **how do you actually start or call the product** —
Python API, console scripts, repository CLI wrappers, MCP server modes, and
domain CLIs — and which packaging path exposes which names. It pairs with the
hop-level flows in [END_TO_END_DATA_FLOW.md](END_TO_END_DATA_FLOW.md).

## 2. Authority and packaging drift

| Surface | Authority | Notes |
| --- | --- | --- |
| `pyproject.toml` `[project.scripts]` | **Canonical pure-pyproject install** | 4 scripts |
| `setup.py` `console_scripts` | **Legacy / alternate** install path | 8 scripts (superset) |
| Installed `egg-info/entry_points.txt` | What **this worktree install** exposes | Matches pyproject four |
| Repo wrappers (`ipfs-datasets`, `ipfs_datasets_cli.py`) | Dev checkout convenience | Not setuptools by themselves |

**Drift (documented, not fixed here):** `ipfs-datasets`, `ipfs-datasets-cli`,
`file-converter`, and `fc` are declared in `setup.py` but **not** in
`pyproject.toml`. Whether `pip install` exposes them depends on the packaging
path. Prefer documenting both and stating which install was used.

---

## 3. Entry surface map

```text
                    ┌─────────────────────────────────────┐
                    │  How users arrive                     │
                    └──────────────────┬──────────────────┘
           ┌───────────────┬───────────┼───────────┬────────────────┐
           v               v           v           v                v
    Python import    Console scripts  Repo CLI   MCP module    Domain CLIs
    initialize()     pyproject/setup  ipfs-datasets  -m mcp_server  logic/search/…
           │               │           │           │                │
           └───────────────┴───────────┴─────┬─────┴────────────────┘
                                             v
                              Domain packages + MCP tool tree
```

---

## 4. Python API entry points

### 4.1 Package root

| Callable / symbol | Path | Role |
| --- | --- | --- |
| Package import | `import ipfs_datasets_py` | Hermetic-by-default; heavy stacks gated by env |
| `initialize(...)` | `ipfs_datasets_py.initialize` | Process-wide router deps; optional SyMAI registration |
| Version | `ipfs_datasets_py.__version__` / packaging metadata | Package identity |

**Import environment flags (selected):**

| Flag | Effect |
| --- | --- |
| `IPFS_DATASETS_PY_MINIMAL_IMPORTS` / `IPFS_DATASETS_PY_BENCHMARK` | Minimal import mode |
| `IPFS_DATASETS_PY_ENABLE_MCP_IMPORTS` | Allow MCP stack import side effects |
| `IPFS_DATASETS_PY_ENABLE_FASTAPI_IMPORTS` | Allow FastAPI stack |
| `IPFS_DATASETS_PY_ENABLE_LLM_IMPORTS` | Allow LLM/transformers-related imports |
| `IPFS_DATASETS_PY_ENABLE_FINANCE_DASHBOARD_IMPORTS` | Finance dashboard imports |
| `IPFS_DATASETS_PY_ENABLE_IPFS_KIT` | Opt-in IPFS kit (also gated by `IPFS_KIT_DISABLE`) |
| `IPFS_DATASETS_PY_WARN_OPTIONAL_IMPORTS` | Emit warnings for optional import failures |
| `IPFS_DATASETS_PY_USE_SYMAI_ENGINE_ROUTER` | SyMAI router registration behavior |
| `IPFS_DATASETS_PY_USE_EMBEDDING_ADAPTER` | Embedding adapter path in search |

### 4.2 High-value library callables (by flow)

| Flow | Preferred callable | Module |
| --- | --- | --- |
| Ingest dataset | `DatasetLoader().load` / `load_sync` | `core_operations.dataset_loader` |
| Process / save | `DataProcessor`, saver helpers | `core_operations` |
| PDF artifact | `PDFProcessor.process_pdf` | `processors.specialized.pdf.pdf_processor` (package may re-export adapters) |
| Embeddings | `generate_embedding`, `generate_batch_embeddings` | `embeddings.generation_engine` |
| Index / search vectors | `create_vector_store`, `add_texts_to_store`, `search_texts` | `vector_stores.api` |
| Semantic search | `semantic_search`, `hybrid_search` | `embeddings.semantic_search_engine` |
| Logic prove | `LogicProcessor` methods | `core_operations.logic_processor` |
| IR provenance | `SourceRef`, related types | `logic.ir_core.provenance` |
| Operational provenance | `ProvenanceManager` | `analytics.data_provenance` |
| Admissibility | gate / `IntentAuthorizationAPI.evaluate` | `logic.admissibility` |
| Proof corpus | store / attest / query APIs | `logic.proof_corpus` |
| Logic registry | `logic_submodule_specs`, `logic_integration_manifest` | `logic.submodule_registry` |
| Dataset manager | `DatasetManager` | `dataset_manager` |
| Profile G facade | `profile_g` | package root re-export → `logic.profile_g` |

### 4.3 Routers (backend selection)

Package-root routers select optional backends without hard-wiring stacks:

| Router module | Concern |
| --- | --- |
| `embedding_router` / `embeddings_router` | Embeddings backends |
| `ipfs_backend_router` | IPFS backends |
| `llm_router` | LLM backends |
| `multimodal_router` | Multimodal |
| `voice_router` | Voice |
| `router_deps` / `_dependencies` | Shared dependency resolution |

---

## 5. Console scripts

### 5.1 `pyproject.toml` (canonical install surface)

| Script | Target |
| --- | --- |
| `ipfs-datasets-install-provers` | `ipfs_datasets_py.logic.integration.bridges.prover_installer:main` |
| `ipfs-datasets-sms-bridge` | `ipfs_datasets_py.messaging.sms_bridge:main` |
| `ipfs-netherlands-laws` | `ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.cli:main` |
| `netherlands-laws` | same as above (alias) |

### 5.2 `setup.py` only (legacy superset)

| Script | Target | In pyproject? |
| --- | --- | --- |
| `ipfs-datasets` | `ipfs_datasets_cli:cli_main` | no |
| `ipfs-datasets-cli` | `ipfs_datasets_cli:cli_main` | no |
| `file-converter` | `ipfs_datasets_py.processors.file_converter.cli:main` | no |
| `fc` | same as `file-converter` | no |
| (plus the four pyproject scripts) | | yes |

### 5.3 Repository wrappers (checkout)

| Path | Kind | Entry |
| --- | --- | --- |
| `ipfs_datasets_cli.py` | Python module | `cli_main()` / `main()` |
| `ipfs-datasets` | shell wrapper at repo root | invokes CLI |

**Dev invocation without install:**

```bash
python ipfs_datasets_cli.py --help
./ipfs-datasets --help
```

---

## 6. Primary CLI (`ipfs_datasets_cli` / `cli_main`)

Lightweight, **lazy-loading** CLI oriented around MCP tool discovery and a set
of first-class command groups.

### 6.1 Command groups (from built-in help)

| Command | Role |
| --- | --- |
| `info` | status, version, defaults |
| `mcp` | start / stop / status / logs for MCP server |
| `tools` | categories, list, execute/run dynamic tools |
| `dataset` | load, convert |
| `ipfs` | pin, get |
| `vector` | create embeddings, search |
| `graph` | create, entities, relationships, Cypher, hybrid search, tx, index |
| `legal` | court rules, Federal Register, Netherlands laws shortcuts |
| `legal-pdf` | render / merge helpers |
| `p2p` | P2P workflow scheduler commands |
| `vscode` / `github` / `copilot` / `gemini` / `claude` | external CLI lifecycle helpers |

### 6.2 Dynamic tool execution

`DynamicToolRunner` scans `ipfs_datasets_py/mcp_server/tools/<category>/*.py`
and imports `ipfs_datasets_py.mcp_server.tools.<category>.<tool>`.

```bash
# Pattern
ipfs-datasets tools categories
ipfs-datasets tools list <category>
ipfs-datasets tools run <category> <tool> --arg value
```

This is the same module tree hierarchical MCP dispatch uses
([END_TO_END_DATA_FLOW.md](END_TO_END_DATA_FLOW.md) Flow E).

### 6.3 Programmatic entry

```python
from ipfs_datasets_cli import cli_main
# or: python -c "from ipfs_datasets_cli import cli_main; cli_main()"
```

---

## 7. Domain CLIs (module entry)

These are **not** all setuptools console scripts. Invoke with
`python -m …` or `python path/to/cli.py` unless packaging adds a script.

| Domain | Entry | Notes |
| --- | --- | --- |
| Logic | `ipfs_datasets_py.logic.cli:main` | Formalization / prover-oriented CLI |
| Optimizers | `ipfs_datasets_py.optimizers.cli:main` | GraphRAG / optimizer loops |
| Search | `ipfs_datasets_py.search.cli:main` | Search-oriented CLI |
| Wallet | `ipfs_datasets_py.wallet.cli:main` | Trust / grant surface |
| Scraper | `ipfs_datasets_py.cli.scraper_cli:main` | Generic scraper |
| Finance | `ipfs_datasets_py.cli.finance_cli:main` | Finance data |
| Discord | `ipfs_datasets_py.cli.discord_cli:main` | Discord ingest |
| Email | `ipfs_datasets_py.cli.email_cli:main` | Email |
| Docket | `ipfs_datasets_py.cli.docket_cli:main` | Docket |
| Workspace | `ipfs_datasets_py.cli.workspace_cli:main` | Workspace |
| Legal PDF | `ipfs_datasets_py.cli.legal_pdf_cli:main` | Legal PDF render helpers |
| History index | `ipfs_datasets_py.cli.history_index_cli:main` | History index |
| Common Crawl | `ipfs_datasets_py.cli.common_crawl_cli` | `__main__` runner |
| Netherlands laws | console scripts above | Official Dutch sources scraper |
| File converter | `processors.file_converter.cli:main` | setup.py scripts `file-converter` / `fc` |
| SMS bridge | `messaging.sms_bridge:main` | Long-running messaging process |
| Prover installer | `logic.integration.bridges.prover_installer:main` | Optional prover install |

---

## 8. MCP server entry points

### 8.1 Process entry

| Mode | How | Implementation |
| --- | --- | --- |
| **Stdio (default)** | `python -m ipfs_datasets_py.mcp_server` or `--stdio` | `start_stdio_server()` → `IPFSDatasetsMCPServer.start_stdio` → FastMCP `run_stdio_async` |
| **HTTP** | `python -m ipfs_datasets_py.mcp_server --http [--host] [--port]` | Hypercorn+Trio preferred on FastAPI app; uvicorn fallback; else stdio |
| **Python API** | `from ipfs_datasets_py.mcp_server import start_server, start_stdio_server` | same as above |
| **CLI** | `ipfs-datasets mcp start` | wraps server lifecycle when CLI installed |
| **Systemd** | `ipfs-datasets-mcp.service` (repo unit) | operator-managed service |
| **Docker** | `docker/Dockerfile*`, compose files | containerized MCP / dashboard |

Flags on `__main__`: `--host`, `--port` (default 3002 HTTP), `--config`,
`--debug`, `--stdio`, `--http`.

### 8.2 Public server symbols

| Symbol | Module | Role |
| --- | --- | --- |
| `IPFSDatasetsMCPServer` | `mcp_server.server` | Full server class |
| `start_stdio_server` | `mcp_server.server` | Stdio launcher |
| `start_server` | `mcp_server.server` | HTTP launcher |
| `IPFSDatasetsMCPClient` | `mcp_server.client` | Optional client |
| `SimpleIPFSDatasetsMCPServer` / `start_simple_server` | `simple_server` | Fallback when full MCP stack unavailable |
| `Configs` / `configs` / `load_config_from_yaml` | `mcp_server.configs` | Configuration |
| FastAPI `app` | `mcp_server.fastapi_service` | HTTP/REST + MCP++ host path |
| Hierarchical meta-tools | `hierarchical_tool_manager` | `tools_list_categories`, `tools_list_tools`, `tools_get_schema`, `tools_dispatch` |

### 8.3 Dispatch contract (summary)

1. Client calls `tools_list_categories` → categories under `mcp_server/tools/`.
2. Client calls `tools_list_tools(category)` → tool modules.
3. Client calls `tools_get_schema(category, tool)` → parameters.
4. Client calls `tools_dispatch(category, tool, params)` → domain execution.

Optional: `dispatch_with_trace` attaches CID-native `_trace`
(`ExecutionEnvelope`) for Profile B provenance of tool calls.

Failure modes: FastMCP missing; category/tool not found; circuit breaker open;
server shutting down; domain import/runtime errors returned as structured
error dicts. See Flow E in [END_TO_END_DATA_FLOW.md](END_TO_END_DATA_FLOW.md).

### 8.4 Representative tool categories → domain owners

| Category (tools dir) | Thin MCP layer | Domain owner |
| --- | --- | --- |
| `dataset_tools` | load/process/save | `core_operations`, datasets |
| `pdf_tools` | ingest/query PDF | `processors` |
| `embedding_tools` | generate/search embeddings | `embeddings` |
| `vector_tools` / `vector_store_tools` / `storage_tools` | vector/storage ops | `vector_stores`, storage |
| `graph_tools` | KG CRUD/query | `knowledge_graphs` |
| `logic_tools` | prove/parse/policy | `logic` |
| `legal_dataset_tools` | legal corpora | `processors` legal scrapers |
| `ipfs_tools` / `ipfs_cluster_tools` | IPFS ops | IPFS integration |
| `provenance_tools` | lineage records | `analytics` / audit |
| `audit_tools` / `security_tools` / `auth_tools` | audit/security/auth | audit, security, wallet-adjacent |
| `media_tools` / `file_converter_tools` | media/convert | `multimedia` / `processors` |
| admin/dashboard/monitoring/* | ops surfaces | dashboards, monitoring packages |

---

## 9. Service and ops entry points

| Surface | Location | How started |
| --- | --- | --- |
| FastAPI HTTP | `mcp_server.fastapi_service.app` | via `start_server` / Hypercorn / uvicorn; extra `api` |
| Profile G service | `mcp_server.profile_g_service` + facade `profile_g` | fail-closed side effects unless configured |
| SMS bridge | console `ipfs-datasets-sms-bridge` | long-running process |
| Docker Compose | `docker-compose.yml`, `docker/docker-compose*.yml` | compose up |
| Deployments | `deployments/` (k8s, nginx, monitoring, SQL) | operator tooling |
| Config examples | `config.yaml.example`, `config/mcp_config.yaml`, `config.toml` | load via configs helpers |

---

## 10. Mapping entry points → end-to-end flows

| Flow | Python | CLI | MCP |
| --- | --- | --- | --- |
| **A Ingestion→artifact** | `DatasetLoader.load`, `PDFProcessor.process_pdf` | `dataset load`, `tools run dataset_tools …`, legal/scraper CLIs | `dataset_tools/*`, `pdf_tools/pdf_ingest_to_graphrag` |
| **B Artifact→index** | `generate_*`, `add_texts_to_store` | `vector create`, graph index commands | `embedding_tools/*`, vector/graph tools |
| **C Query→result** | `search_texts`, `semantic_search`, graph query APIs | `vector search`, `graph search` / `graph query` | search/graph/pdf query tools |
| **D Logic→evidence** | logic modules, admissibility API, proof corpus | `logic.cli`, install-provers script | `logic_tools/*`, admissibility tools |
| **E MCP→dispatch** | `start_*_server`, `tools_dispatch` | `mcp start`, `tools run` | hierarchical meta-tools |

---

## 11. Operator quick reference

```bash
# Library (dev tree)
python -c "import ipfs_datasets_py; print('ok')"

# MCP stdio (hosts like VS Code)
python -m ipfs_datasets_py.mcp_server

# MCP HTTP
python -m ipfs_datasets_py.mcp_server --http --host 127.0.0.1 --port 3002

# CLI (when setup.py scripts installed, or via repo wrapper)
ipfs-datasets info version
ipfs-datasets tools categories
ipfs-datasets tools run dataset_tools load_dataset --source squad

# Provers (optional)
ipfs-datasets-install-provers

# Netherlands laws scraper
ipfs-netherlands-laws --help
```

---

## 12. Non-goals

- Exhaustive list of every file under `mcp_server/tools/` (use
  `tools_list_categories` / catalog docs).
- Guaranteeing optional extras and submodules are present.
- Agent-supervisor taskboard execution (external accelerate family).
- Resolving packaging drift in code (documentation-only task).

---

## 13. Related documents

| Document | Role |
| --- | --- |
| [END_TO_END_DATA_FLOW.md](END_TO_END_DATA_FLOW.md) | Hop-level flows using these entry points |
| [SYSTEM_CONTEXT.md](SYSTEM_CONTEXT.md) | Actors and surfaces |
| [DOMAIN_MAP.md](DOMAIN_MAP.md) | Domain ownership |
| [CURRENT_STATE_BASELINE.md](../maintenance/CURRENT_STATE_BASELINE.md) | Measured script counts |
| [CLI_MCP_INTEGRATION_GUIDE.md](../CLI_MCP_INTEGRATION_GUIDE.md) | CLI/MCP alignment (historical/support) |

---

## 14. Validation

```bash
test -s docs/architecture/END_TO_END_DATA_FLOW.md && test -s docs/architecture/RUNTIME_ENTRYPOINTS.md
rg -n 'Python|CLI|MCP|provenance|failure' docs/architecture/END_TO_END_DATA_FLOW.md
```

Evidence: `pyproject.toml` scripts; `setup.py` entry_points; egg-info;
`ipfs_datasets_cli.py` help and `DynamicToolRunner`; `mcp_server/__main__.py`
and `start_stdio_server` / `start_server`; domain `cli.py` `main` symbols;
SYSTEM_CONTEXT §4 surfaces.
