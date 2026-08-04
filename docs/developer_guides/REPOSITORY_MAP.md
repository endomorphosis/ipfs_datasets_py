# Developer repository map

| Field | Value |
| --- | --- |
| Interface | `DeveloperRepositoryMap@1` |
| Task | `IPFSDOC-070` |
| Status | `canonical` |
| Owner | developer-docs |
| Source of truth | Live worktree inventory; `ipfs_datasets_py/` first-level topology; `pyproject.toml` / `setup.py`; `tests/`; `.gitmodules`; sibling architecture guides |
| Measured at (UTC) | `2026-08-03T08:16:18Z` |
| Commit | `37f99e8a2c6dff4ba58ebc9ac26507bb8b9ee60f` |
| Short commit | `37f99e8a2` |
| Measurement Python | `Python 3.12.3` |
| Audience | developer, agent, architect |
| Related | [DOMAIN_MAP.md](../architecture/DOMAIN_MAP.md), [RUNTIME_ENTRYPOINTS.md](../architecture/RUNTIME_ENTRYPOINTS.md), [INTEGRATION_BOUNDARIES.md](../architecture/INTEGRATION_BOUNDARIES.md), [DEPENDENCY_AND_INITIALIZATION.md](../architecture/DEPENDENCY_AND_INITIALIZATION.md), [CURRENT_STATE_BASELINE.md](../maintenance/CURRENT_STATE_BASELINE.md), [SOURCE_AUTHORITY.md](../maintenance/SOURCE_AUTHORITY.md) |
| Review cadence | after large tree moves, packaging surface changes, or submodule map changes |

## 1. Purpose

This page is the **bounded first context set** for contributors and agents: where
code, tests, examples, deployment, and docs live; which domain **owns** a
change; which imports and entry points are **canonical**; where **compat** and
**archive** material sits; which files are **hot/shared**; how to find **nearest
tests**; which **optional** stacks apply; and what this repository does **not**
own across git submodules.

It does **not** replace domain architecture leaves, extension recipes, or the
testing evidence guide. Prefer those for deep detail after you locate the right
tree with this map.

### Authority

When this map disagrees with older root status reports or session summaries,
prefer: implementation and tests → packaging → accepted architecture guides →
this map’s measured tables → historical docs. See
[SOURCE_AUTHORITY.md](../maintenance/SOURCE_AUTHORITY.md).

Domain ownership authority for product placement is
[DOMAIN_MAP.md](../architecture/DOMAIN_MAP.md). Entry-point authority is
[RUNTIME_ENTRYPOINTS.md](../architecture/RUNTIME_ENTRYPOINTS.md). Cross-repo
boundaries are [INTEGRATION_BOUNDARIES.md](../architecture/INTEGRATION_BOUNDARIES.md).

---

## 2. Provenance and measurement method

Counts below are **current-tree facts** for the commit and timestamp in the
header. They are not copied from badges or historical completion reports.

| Kind | Meaning |
| --- | --- |
| **Tracked fact** | From `git ls-files` or parsed committed config in this worktree |
| **Filesystem fact** | From `find` / directory listing (may include untracked or submodule content) |
| **Derived fact** | Arithmetic over tracked or filesystem facts |
| **Not measured** | Explicitly out of scope (for example full `pytest --collect-only`) |

### Reproducible commands

```bash
date -u +%Y-%m-%dT%H:%M:%SZ
git rev-parse HEAD
python3 --version
git ls-files | wc -l
git ls-files '*.py' | wc -l
git ls-files '*.md' | wc -l
# Path-scoped (repeat for ipfs_datasets_py tests docs scripts examples benchmarks archive deployments docker)
git ls-files ipfs_datasets_py | wc -l
git ls-files ipfs_datasets_py | grep -c '\.py$'
git ls-files ipfs_datasets_py | grep -c '\.md$'
ls -1d ipfs_datasets_py/*/ | sed 's|ipfs_datasets_py/||;s|/$||' | sort
find ipfs_datasets_py -name '__init__.py' | wc -l
```

Package identity (from `pyproject.toml`): name **`ipfs_datasets_py`**, version
**`0.2.0`**, `requires-python = ">=3.12"`. Core runtime dependencies are
`dynamic = ["dependencies"]` (static `project.dependencies` count = **0**);
install extras are declared under `[project.optional-dependencies]`.

---

## 3. Repository top-level layout

```text
.
├── ipfs_datasets_py/     # Primary Python package (product code)
├── tests/                # Primary test suite (pytest testpaths)
├── docs/                 # Hub documentation (MkDocs docs_dir)
├── examples/             # Runnable examples (basic → advanced)
├── deployments/          # Operator deploy scripts, k8s, monitoring
├── docker/               # Dockerfiles and compose variants
├── scripts/              # Dev, CI, migration, documentation utilities
├── benchmarks/           # Performance benches (not product API)
├── archive/              # Historical migrations, experiments, artifacts
├── config/               # Repo-level config samples / templates
├── tools/                # Small tooling (e.g. security_ir inventory)
├── test/                 # Legacy thin test root (2 files; not primary suite)
├── ipfs_kit_py/          # Git submodule (often empty until init)
├── ipfs_accelerate_py/   # Git submodule (often empty until init)
├── pyproject.toml        # Canonical packaging (Python 3.12+)
├── setup.py              # Legacy/alternate packaging (superset scripts)
├── requirements*.txt     # Pip requirement sets (docs, lazy, theorem provers)
├── pytest.ini            # Pytest defaults (testpaths = tests)
├── mkdocs.yml            # Documentation site nav
├── ipfs_datasets_cli.py  # Repo CLI module (checkout convenience)
├── ipfs-datasets         # Shell wrapper for CLI
├── Dockerfile*           # Root container entry points
└── docker-compose.yml    # Root compose
```

### 3.1 Inventory counts (this commit)

| Path | Tracked files | Tracked `*.py` | Tracked `*.md` | Role |
| --- | ---: | ---: | ---: | --- |
| **Repository total** | 11921 | 6839 | 2282 | Entire tracked tree |
| `ipfs_datasets_py/` | 3736 | 3005 | 387 | Product package |
| `tests/` | 3339 | 3005 | 44 | Primary tests |
| `docs/` | 1908 | 10 | 1546 | Hub docs |
| `scripts/` | 490 | 393 | 16 | Dev utilities |
| `archive/` | 1795 | 143 | 161 | Historical only |
| `benchmarks/` | 138 | 126 | 6 | Perf evidence |
| `examples/` | 106 | 94 | 10 | Learning / demos |
| `deployments/` | 59 | 4 | 10 | Ops deploy |
| `docker/` | 16 | 0 | 1 | Container images |
| `config/` | 17 | 2 | 1 | Repo config samples |

Additional filesystem facts:

| Metric | Count | Kind |
| --- | ---: | --- |
| First-level package directories under `ipfs_datasets_py/` | 39 | Filesystem fact |
| Package root `*.py` modules | 24 | Filesystem fact |
| Package `__init__.py` modules | 344 | Filesystem fact |
| Root `docs/*.md` pages | 117 | Filesystem fact |
| `tests/**/*.feature` (Gherkin) | 153 | Filesystem fact |
| Optional extras keys in `pyproject.toml` | 18 | Tracked fact |

---

## 4. Package structure (`ipfs_datasets_py/`)

### 4.1 Domain clusters (navigation)

| Cluster | Domains | Architecture home |
| --- | --- | --- |
| **Processing / ingest** | `processors`, `multimedia`, `web_archiving`, `cli` (ingest CLIs) | `docs/architecture/processing/` |
| **Logic / IR / proof** | `logic` (+ registry families), related `optimizers` theorem loops | `docs/architecture/logic/` |
| **Knowledge / GraphRAG** | `knowledge_graphs`, `optimizers`, parts of `search` | `docs/architecture/knowledge/` |
| **Retrieval** | `embeddings`, `vector_stores`, `search`, `ml` | `docs/architecture/retrieval/` |
| **Storage / release** | `storage`, `caching`, `ipfs_cluster`, `p2p_networking`, `huggingface`, `voice` | `docs/architecture/storage/` |
| **Trust / privacy** | `wallet`, `audit`, package `security.py` | `WALLET_TRUST_AND_PRIVACY.md` |
| **MCP / tools** | `mcp_server` | `docs/architecture/mcp/` |
| **Runtime / platform** | Profile G facades, `accelerate_integration`, `workflow_automation`, `sessions` | `docs/architecture/runtime/` |
| **Cross-cutting ops** | `config`, `dashboards`, `admin`, `alerts`, `analytics`, `error_reporting`, `messaging`, `rate_limiting`, `monitoring*` | ops / MCP observability |
| **Support** | `utils`, `skills`, `scripts`, `static`, `templates`, `install`, in-package `tests` | developer / n/a |

### 4.2 First-level package directory inventory

Python counts are **filesystem** `*.py` under each first-level directory (this
commit). Prefer git-tracked package total (**3005** `*.py`) for “in-repo package
surface.”

| Directory | `*.py` | Files | Domain role |
| --- | ---: | ---: | --- |
| `processors/` | 973 | 1242 | **Canonical** multimodal / domain processing |
| `logic/` | 650 | 679 | **Canonical** IR, provers, admissibility, registry |
| `mcp_server/` | 531 | 751 | **Canonical** MCP/HTTP tool host (~52 tool category dirs) |
| `optimizers/` | 385 | 390 | **Canonical** GraphRAG / agentic / theorem optimizers |
| `knowledge_graphs/` | 103 | 118 | **Canonical** KG extraction / Neo4j-compat engine |
| `utils/` | 46 | 55 | Shared utilities (not a product domain) |
| `search/` | 34 | 40 | Search / query integration |
| `ml/` | 33 | 50 | ML helpers (often optional/heavy) |
| `vector_stores/` | 19 | 31 | **Canonical** vector backends |
| `dashboards/` | 19 | 47 | Dashboard UIs/services |
| `audit/` | 18 | 45 | Audit / provenance package |
| `wallet/` | 17 | 17 | **Canonical** user-controlled trust surface |
| `tests/` (in-package) | 17 | 22 | Package-local helpers; primary suite is repo `tests/` |
| `web_archiving/` | 15 | 15 | Unified archive/scrape engines |
| `voice/` | 13 | 13 | **Canonical** voice dataset contracts |
| `cli/` | 13 | 13 | Domain CLIs |
| `p2p_networking/` | 11 | 11 | libp2p / peer / workflow engines |
| `core_operations/` | 10 | 10 | Dataset load/process/save helpers |
| `error_reporting/` | 9 | 11 | CLI/server error reporting |
| `caching/` | 8 | 8 | Cache layers |
| `workflow_automation/` | 7 | 7 | Workflow automation (sparse) |
| `scripts/` (in-package) | 7 | 8 | Package-local ops scripts |
| `embeddings/` | 7 | 7 | Embedding generation engines |
| `huggingface/` | 6 | 6 | HF publication helpers |
| `analytics/` | 6 | 6 | Analytics / operational provenance |
| `alerts/` | 5 | 5 | Alerting |
| `accelerate_integration/` | 4 | 4 | Accelerate placement (compat with external ownership) |
| `storage/` | 2 | 2 | Thin storage engine facade |
| `sessions/` | 2 | 2 | Session helpers |
| `rate_limiting/` | 2 | 2 | Rate limit helpers |
| `messaging/` | 2 | 2 | SMS bridge |
| `ipfs_cluster/` | 2 | 2 | Cluster helper bindings |
| `config/` | 2 | 8 | Package config helpers |
| `admin/` | 2 | 2 | Admin helpers |
| `skills/` | 1 | 4 | Agent skill references |
| `static/` | 0 | 44 | Static assets |
| `templates/` | 0 | 23 | HTML templates |
| `multimedia/` | 0 | 0 | **Submodule checkout** (empty until init) |
| `install/` | 0 | 1 | Not a product feature surface |

### 4.3 Package-root modules (cross-cutting / hot)

These are **not** first-level directories but shape almost every import path:

| Module | Role | Owner boundary |
| --- | --- | --- |
| `__init__.py` (~1439 lines) | Version, hermetic import policy, `initialize()`, lazy exports | Does not import MCP/FastAPI/LLM by default |
| `ipfs_datasets.py` (~1912 lines) | Large dataset API used by tools | Dataset ops; not storage backends |
| `dataset_manager.py` | Dataset manager facade | Dataset ops |
| `logic/submodule_registry.py` (~882 lines) | Machine-readable **logic family** map | Logic domain authority |
| `mcp_server/server.py` (~1254 lines) | MCP server implementation | Protocol host only |
| `router_deps.py`, `*_router.py` | Backend selection / DI | Selection only; backends own behavior |
| `lazy_dependencies.py`, `deps_resolver.py`, `dependency_catalog.py`, `auto_installer.py` | Optional dependency lifecycle | Install surface vs capability honesty |
| `security.py`, `audit.py` | Facades | Defer to logic security / wallet / audit packages |
| `monitoring.py`, `monitoring_engine.py` | Observability | Not proof authority |
| `profile_g.py` | Facade → `logic.profile_g` | Planning/evidence; fail-closed side effects |
| `voice_router.py` | Voice entry router | Voice package owns contracts |
| `config.py`, `database_utils.py`, `content_discovery.py` | Shared config/DB/discovery | Cross-cutting support |

---

## 5. Domain owners (quick placement)

Use this when deciding **where new code goes**. Full ownership tables:
[DOMAIN_MAP.md](../architecture/DOMAIN_MAP.md).

| Concern | Canonical owner path | Does **not** own |
| --- | --- | --- |
| PDF / OCR / scrapers / file conversion / investigation | `ipfs_datasets_py.processors` | MCP framing; formal IR identity |
| IR schemas, compilers, provers, proof corpus, admissibility | `ipfs_datasets_py.logic` | GraphRAG optimizer product loops; Neo4j engine impl |
| MCP protocol, tool wrappers, FastAPI MCP host | `ipfs_datasets_py.mcp_server` | Domain algorithms (must call domains) |
| GraphRAG / ontology / agentic optimization loops | `ipfs_datasets_py.optimizers` | Core IR schemas; production admissibility |
| Graph extraction, lineage, Neo4j-compat engine | `ipfs_datasets_py.knowledge_graphs` | Optimizer product loops; formal deontic compilers |
| Vector backends (FAISS, Qdrant, ES) | `ipfs_datasets_py.vector_stores` | Embedding training; graph structure |
| Embeddings generation / semantic search helpers | `ipfs_datasets_py.embeddings` | Vector DB backends |
| Search / content discovery / hybrid query hooks | `ipfs_datasets_py.search` | Core KG storage |
| User wallet, grants, privacy policy | `ipfs_datasets_py.wallet` | Chain settlement; Security IR sole authority |
| Voice dataset normalize / release contracts | `ipfs_datasets_py.voice` | TTS training; general multimedia conversion |
| Web archive engines | `ipfs_datasets_py.web_archiving` | Legal corpus policy (processors legal) |
| P2P / libp2p / task queue workflows | `ipfs_datasets_py.p2p_networking` | Public DHT governance |
| Dataset load/process/save | `ipfs_datasets_py.core_operations` | Backend storage product |
| Shared utils | `ipfs_datasets_py.utils` | Product domain APIs |

**Rule of thumb:** put business logic in the domain; put MCP/CLI exposure as
**thin wrappers** that call the domain.

---

## 6. Canonical imports and entry points

### 6.1 Preferred import style

```python
# Package (hermetic by default)
import ipfs_datasets_py
from ipfs_datasets_py import initialize

# Domains — prefer package-qualified paths
from ipfs_datasets_py.processors... import ...
from ipfs_datasets_py.logic.ir_core... import ...
from ipfs_datasets_py.logic.integration... import ...  # not logic.tools
from ipfs_datasets_py.mcp_server.tools.<category>.<tool> import ...
from ipfs_datasets_py.vector_stores... import ...
from ipfs_datasets_py.knowledge_graphs... import ...
from ipfs_datasets_py.optimizers... import ...
from ipfs_datasets_py.wallet... import ...
from ipfs_datasets_py.voice... import ...
```

### 6.2 High-value library callables

| Flow | Preferred callable / module |
| --- | --- |
| Ingest dataset | `core_operations.dataset_loader.DatasetLoader` |
| Process / save | `core_operations` processor/saver helpers |
| PDF | `processors` PDF processor paths (specialized / package adapters) |
| Embeddings | `embeddings.generation_engine` |
| Vector index/search | `vector_stores` API helpers |
| Semantic search | `embeddings.semantic_search_engine` |
| Logic prove | `core_operations.logic_processor.LogicProcessor` |
| IR provenance | `logic.ir_core.provenance` |
| Operational provenance | `analytics.data_provenance.ProvenanceManager` |
| Admissibility | `logic.admissibility` |
| Logic registry | `logic.submodule_registry` (`logic_submodule_specs`, `logic_integration_manifest`) |
| Profile G | `logic.profile_g` (root `profile_g` is facade only) |

### 6.3 Console scripts and process entry

| Surface | Authority | Entries |
| --- | --- | --- |
| **`pyproject.toml` `[project.scripts]`** | Canonical pure-pyproject install | `ipfs-datasets-install-provers`, `ipfs-datasets-sms-bridge`, `ipfs-netherlands-laws`, `netherlands-laws` |
| **`setup.py` `console_scripts`** | Legacy / alternate (superset) | Above four **plus** `ipfs-datasets`, `ipfs-datasets-cli`, `file-converter`, `fc` |
| **Repo wrappers** | Dev checkout | `ipfs_datasets_cli.py`, `./ipfs-datasets` |
| **MCP module** | Canonical MCP process | `python -m ipfs_datasets_py.mcp_server` (`--stdio` / `--http`) |
| **Domain CLIs** | Module entry (not all packaged) | `logic.cli`, `optimizers.cli`, `search.cli`, `wallet.cli`, `cli.*_cli`, … |

**Packaging drift (documented):** `ipfs-datasets`, `ipfs-datasets-cli`,
`file-converter`, and `fc` are in `setup.py` but **not** in `pyproject.toml`.
Whether `pip install` exposes them depends on install path. Full map:
[RUNTIME_ENTRYPOINTS.md](../architecture/RUNTIME_ENTRYPOINTS.md).

### 6.4 Import environment flags (selected)

| Flag | Effect |
| --- | --- |
| `IPFS_DATASETS_PY_MINIMAL_IMPORTS` / `IPFS_DATASETS_PY_BENCHMARK` | Minimal import mode |
| `IPFS_DATASETS_PY_ENABLE_MCP_IMPORTS` | Allow MCP stack import side effects |
| `IPFS_DATASETS_PY_ENABLE_FASTAPI_IMPORTS` | Allow FastAPI stack |
| `IPFS_DATASETS_PY_ENABLE_LLM_IMPORTS` | Allow LLM/transformers-related imports |
| `IPFS_DATASETS_PY_ENABLE_IPFS_KIT` | Opt-in IPFS kit (also gated by `IPFS_KIT_DISABLE`) |
| `IPFS_DATASETS_PY_WARN_OPTIONAL_IMPORTS` | Emit warnings for optional import failures |

Lifecycle detail: [DEPENDENCY_AND_INITIALIZATION.md](../architecture/DEPENDENCY_AND_INITIALIZATION.md).

### 6.5 Canonical vs compatibility matrix

| Concern | Canonical | Compatibility / legacy |
| --- | --- | --- |
| Logic integrations | `logic.integration`, family packages | `logic.tools` (**deprecated**) |
| MCP tools | `mcp_server/tools/<category>` thin wrappers | `legacy_mcp_tools`, `simple_server` fallback |
| CLI install names | `pyproject.toml` four scripts | `setup.py` extra names |
| Multimedia converters | Initialized multimedia submodules + `processors.multimedia` | Empty `multimedia/` checkout |
| Profile G | `logic.profile_g` + MCP profile_g service | Root `profile_g.py` facade only |
| Vector search stack | `embeddings` + `vector_stores` + `search` | Historical root IPLD_* guides (mixed age) |
| Authorization | `logic.admissibility` + intent IR | UI/MCP discovery alone is not authz |
| Knowledge extraction | `knowledge_graphs` + `optimizers.graphrag` | Archived extraction experiments |

---

## 7. Tests structure and nearest tests

### 7.1 Test tree overview

Primary suite: **`tests/`** (`pytest.ini` / `pyproject.toml` `testpaths = ["tests"]`).

| Area | Approx. `*.py` (filesystem) | Purpose |
| --- | ---: | --- |
| `tests/unit/` | 1432 | Preferred unit mirror of package domains |
| `tests/unit_tests/` | 710 | Older / parallel unit layout (still active) |
| `tests/mcp/` | 217 | MCP tool and server tests |
| `tests/integration/` | 163 | Cross-domain integration |
| `tests/logic/` | 105 | Logic-family focused tests |
| `tests/migration_tests/` | 103 | Migration / historical paths |
| `tests/test_stubs_from_gherkin/` | 63 | Generated/stub paths from Gherkin |
| `tests/performance/` | 29 | Perf tests |
| `tests/reasoner/` | 26 | Reasoner tests |
| `tests/original_tests/` | 15 | Legacy originals |
| `tests/dual_runtime/` | 10 | Dual-runtime |
| Root `tests/test_*.py` | 60 | Top-level suite modules |
| Root `tests/_test_*.py` | 15 | Underscore-prefixed legacy MCP-style modules |
| `tests/*.feature` tree | 153 features | Gherkin features |
| `test/` (repo root) | 2 | Legacy agent-supervisor API tests only |

Package-local tests under `ipfs_datasets_py/tests/` (**17** `*.py`) are helpers /
adjacency — **do not** treat them as the primary suite.

### 7.2 Nearest tests by domain (start here)

Counts are **path-heuristic** `test_*.py` matches under the listed trees (not
collected pytest node counts). Prefer the first path that exists for your change.

| Domain / change | Nearest tests (start) | Broader / integration |
| --- | --- | --- |
| **processors** | `tests/unit/processors/` (~32), `tests/unit/legal_scrapers/` (~45) | `tests/integration/`, root `tests/test_processors_*`, `tests/test_website_graphrag_*` |
| **logic** (IR, registry, provers) | `tests/unit/logic/` (~131–340 path-dependent), `tests/logic/` (~105) | `tests/unit_tests/logic/` (~417), `tests/integration/` logic paths |
| **logic registry** | `tests/unit/logic/test_logic_submodule_registry.py` | import-report / registry completeness |
| **mcp_server / tools** | `tests/mcp/` (~209), `tests/mcp_server/` (~8), `tests/unit/mcp_server/` (~3) | root `_test_*_tools.py`, `tests/unit_tests/mcp/` |
| **optimizers** | `tests/unit/optimizers/` (~765) | `tests/unit_tests/optimizers/`, `benchmarks/` |
| **knowledge_graphs** | `tests/unit/knowledge_graphs/` (~130) | `tests/integration/`, `tests/unit/knowledge_graphs/migration/` |
| **vector_stores** | `tests/unit/vector_stores/` (~2) | root / MCP vector tool tests |
| **embeddings / routers** | `tests/unit/test_embeddings_router_*`, `tests/unit/test_embedding_*` | `tests/mcp/unit/test_embedding_tools.py` |
| **search** | `tests/unit/search/`, root `tests/test_search_*` | `tests/integration/`, `tests/mcp/` search tools |
| **wallet** | `tests/unit/test_data_wallet.py`, `test_wallet_*` | `tests/mcp/test_wallet_tools.py` |
| **voice** | `tests/unit/voice/` (~7) | release/integration as present |
| **web_archiving** | `tests/unit/web_archiving/`, `tests/unit_tests/web_archive/` | processors web_archiving tests |
| **core_operations** | `tests/unit/core_operations/` (~4) | integration dataset load/save |
| **CLI** | `tests/cli/`, root `tests/test_*_cli.py` | MCP alignment tests |
| **error_reporting** | `tests/error_reporting/`, `tests/unit/error_reporting/` | unit_tests standalone reporters |
| **compatibility / migration** | `tests/compatibility/`, `tests/migration_tests/`, `tests/unit/migration/` | archive only for historical reference |
| **deploy / infra** | `tests/test_deployment_infrastructure.py`, `tests/test_infrastructure.py` | `deployments/` scripts (manual) |

### 7.3 How to select a focused run

```bash
# Domain unit slice
python -m pytest tests/unit/logic/ -q
python -m pytest tests/unit/processors/ -q
python -m pytest tests/unit/optimizers/graphrag/ -q

# MCP tools
python -m pytest tests/mcp/ -q

# Single file / node
python -m pytest tests/unit/logic/test_logic_submodule_registry.py -q
```

Shared fixtures: root `conftest.py` and `tests/conftest.py` (~659 lines — **hot**).
Evidence classes and “do not overclaim” rules belong in the testing guide
(sibling task / `TESTING_AND_EVIDENCE.md` when present).

---

## 8. Examples structure

| Path | `*.py` (approx.) | Notes |
| --- | ---: | --- |
| `examples/basic/` | 6 | First-run examples |
| `examples/intermediate/` | 16 | Mid complexity |
| `examples/advanced/` | 8 | Advanced demos |
| `examples/agentic/` | 2 | Agentic optimization |
| `examples/neurosymbolic/` | 5 | Neurosymbolic |
| `examples/processors/` | 5 | Processor demos |
| `examples/external_provers/` | 2 | Prover demos (optional stack) |
| `examples/knowledge_graphs/` | 1 | KG sample |
| `examples/logic/`, `examples/tdfol/` | 1 each | Logic / TDFOL |
| `examples/*.py` (root of examples) | 12 | Standalone scripts |
| `examples/archived/` | 35 | **Archive** — do not treat as current API |
| `examples/CATALOG.md`, `README.md`, `MIGRATION_GUIDE.md` | — | Catalog and migration notes |

Examples are **illustrative**, not packaging authority. Prefer tests for
contract evidence.

---

## 9. Deployment and Docker

### 9.1 `deployments/` (59 tracked files)

| Path | Role |
| --- | --- |
| `deploy.sh`, `backup_recovery.sh`, `performance_test.sh` | Operator scripts |
| `health_check.py`, `production_readiness_check.py`, `validate_infrastructure.py`, `infrastructure_manager.py` | Readiness / health |
| `kubernetes/` | K8s manifests |
| `monitoring/` | Monitoring configs |
| `nginx/nginx.conf` | Reverse proxy sample |
| `sql/` | DB init SQL |
| `tdfol/` | TDFOL-oriented deploy assets |
| `README.md` | Deploy overview |

### 9.2 `docker/` and root containers

| Path | Role |
| --- | --- |
| `docker/Dockerfile*` | MCP, dashboard, GPU, test, minimal variants |
| `docker/docker-compose*.yml` | Compose stacks (MCP, enhanced, default) |
| Root `Dockerfile`, `Dockerfile.sms_bridge` | Primary image / SMS bridge |
| `docker-compose.yml`, `docker-entrypoint.sh` | Root compose / entry |
| `ipfs-datasets-mcp.service` | Systemd unit for MCP |

Ops shape is **rank-4** authority relative to product code: manifests show how
operators run the stack; they do not redefine package APIs.

---

## 10. Documentation structure (`docs/`)

Hub docs live under `docs/` (`mkdocs.yml` `docs_dir: docs`). Package-local docs
also exist (for example `ipfs_datasets_py/mcp_server/docs/`, domain READMEs).

### 10.1 Major doc trees (Markdown counts, filesystem)

| Path | `*.md` | Use |
| --- | ---: | --- |
| `docs/logic/` | 267 | Logic / IR / prover guides |
| `docs/guides/` | 259 | Feature guides |
| `docs/archive/` | 245 | **Historical** completion / reorg reports |
| `docs/archived_stubs/` | 124 | Stub archives |
| `docs/security_verification/` | 93 | Security / prover verification |
| `docs/optimizers/` | 76 | Optimizer guides |
| `docs/reports/` | 72 | Reports / evidence dumps |
| `docs/architecture/` | 72 | **Canonical architecture** (prefer these) |
| `docs/implementation/` | 65 | Plans / implementation program |
| `docs/knowledge_graphs/` | 44 | KG docs |
| `docs/migration_docs/`, `migration_guides/` | ~23 | Migration |
| `docs/maintenance/` | 7 | Baseline, authority, coverage matrix |
| `docs/developer_guides/` | 2+ | **This map**, contributing, recipes (growing) |
| `docs/deployment/` | 3 | Deploy guides |
| `docs/api/` | 4 | API references |
| Root `docs/*.md` | 117 | Audience entry pages + mixed historical roots |

### 10.2 Developer-first doc entry points

| Need | Start here |
| --- | --- |
| Repository placement (this page) | `docs/developer_guides/REPOSITORY_MAP.md` |
| Domain ownership | `docs/architecture/DOMAIN_MAP.md` |
| How to start processes | `docs/architecture/RUNTIME_ENTRYPOINTS.md` |
| Submodules / cross-repo | `docs/architecture/INTEGRATION_BOUNDARIES.md` |
| Import / optional deps lifecycle | `docs/architecture/DEPENDENCY_AND_INITIALIZATION.md` |
| System actors / surfaces | `docs/architecture/SYSTEM_CONTEXT.md` |
| Doc contribution rules | `docs/developer_guides/DOCUMENTATION_CONTRIBUTING.md` |
| Source authority / drift | `docs/maintenance/SOURCE_AUTHORITY.md`, `CURRENT_STATE_BASELINE.md` |
| Coverage gaps | `docs/maintenance/COVERAGE_MATRIX.md` |
| General developer guide | `docs/developer_guide.md` (being refreshed by sibling tasks) |

---

## 11. Compatibility and archive areas

**Do not** put new product logic in these paths. Prefer pointers + deprecation
banners over rewriting history.

### 11.1 In-package compatibility

| Path | Kind |
| --- | --- |
| `ipfs_datasets_py/mcp_server/compat/` | MCP compatibility shims |
| `ipfs_datasets_py/knowledge_graphs/neo4j_compat/` | Neo4j-compat engine surface (named compat; still active domain code) |
| `ipfs_datasets_py/knowledge_graphs/migration/` | KG migration helpers |
| `ipfs_datasets_py/knowledge_graphs/archive/` | KG archive |
| `ipfs_datasets_py/processors/web_archiving/compat/` | Web archiving compat |
| `ipfs_datasets_py/logic/tools/` | **Deprecated** → use `logic.integration` |
| `ipfs_datasets_py/mcp_server/tools/legacy_mcp_tools/` | Legacy MCP tools |
| `ipfs_datasets_py/logic/docs/archive/` | Logic package-local archive docs |
| Root `profile_g.py`, dual `*_router` names | Facades / alias routers — prefer domain canonical modules |

### 11.2 Test compatibility / migration

| Path | Kind |
| --- | --- |
| `tests/compatibility/` | Compatibility tests |
| `tests/migration_tests/` | Migration suite (~103 py) |
| `tests/unit/migration/`, `tests/unit/knowledge_graphs/migration/` | Unit migration |
| `tests/original_tests/` | Historical originals |
| `tests/unit_tests/` | Parallel older unit layout (still run; prefer `tests/unit/` for new tests) |

### 11.3 Docs and repo archives

| Path | Kind |
| --- | --- |
| `docs/archive/` | Completion reports, deprecated docs, reorg history |
| `docs/archived_stubs/` | Stub markdown archives |
| `docs/migration_docs/`, `docs/migration_guides/` | Migration narratives |
| `docs/auto_generated_stubs/` | Generated stubs |
| `examples/archived/` | Archived examples |
| `archive/` (repo root, **1795** tracked files) | Migrations, experiments, tool results, old configs — **not** product surface |
| `scripts/migration/`, `scripts/migrations/` | Migration utilities |

### 11.4 Empty submodules vs missing features

Empty directories for git submodules (leading `-` in `git submodule status`) are
**availability** issues, not proof that a domain is absent. Do not document empty
checkouts as implemented product capabilities.

---

## 12. Hot and shared files

Touch carefully; many paths import or configure through these.

| File | Why hot / shared |
| --- | --- |
| `ipfs_datasets_py/__init__.py` | Hermetic import policy, `initialize()`, public export surface |
| `ipfs_datasets_py/ipfs_datasets.py` | Large shared dataset API |
| `ipfs_datasets_py/router_deps.py` + `*_router.py` | Process-wide backend selection |
| `ipfs_datasets_py/dependency_catalog.py` / `lazy_dependencies.py` / `auto_installer.py` | Optional dependency resolution |
| `ipfs_datasets_py/logic/submodule_registry.py` | Logic family registry (cross-logic authority) |
| `ipfs_datasets_py/mcp_server/server.py` + `__main__.py` | MCP process entry |
| `ipfs_datasets_py/mcp_server/tools/tool_registration.py` / `tool_wrapper.py` | Tool registration shared path |
| `pyproject.toml` / `setup.py` | Packaging, extras, console scripts (drift risk) |
| `pytest.ini` / `tests/conftest.py` / root `conftest.py` | Test discovery and shared fixtures |
| `requirements.txt` / `requirements-*.txt` | Install matrices |
| `mkdocs.yml` | Docs navigation |
| `config/*.toml` / `config/mcp_config.yaml` | Runtime config samples |
| `.gitmodules` | Cross-repository submodule map |

---

## 13. Optional dependencies

Declared under `[project.optional-dependencies]` in `pyproject.toml` (**18**
extras). Install with `pip install 'ipfs_datasets_py[<extra>]'`.

| Extra | Typical capability | Owning domains (approx.) |
| --- | --- | --- |
| `ipld` | IPLD / CAR codecs | storage, vectors, IPFS paths |
| `knowledge_graphs` | spaCy, networkx, neo4j, viz | `knowledge_graphs`, optimizers |
| `logic` | NLTK, SymbolicAI | `logic` |
| `theorem-provers` | Z3, CVC5, pysmt, SymbolicAI | `logic.external_provers` |
| `file_conversion` | markitdown, playwright, docx, yt-dlp, ffmpeg | `processors.file_converter` |
| `multimedia` | yt-dlp, ffmpeg, pillow, moviepy | multimedia processors / submodules |
| `ocr` | easyocr, opencv, pytesseract | processors OCR |
| `vectors` | sentence-transformers, FAISS, sklearn, qdrant, ES | `embeddings`, `vector_stores` |
| `groth16` / `profile-f-zk` / `provekit` | JSON schema + external prover material | processors backends / ZKP paths |
| `api` | FastAPI, uvicorn, jinja2 | `mcp_server` HTTP, dashboards |
| `symai_router` | SymbolicAI + copilot SDK + opencv | router / SyMAI paths |
| `lazy` | Broad optional media/geo/HTTP helpers | lazy install catalog |
| `legal_netherlands` | Arrow, HF, datasets, FAISS | Netherlands laws scraper |
| `scraping` | BeautifulSoup, newspaper3k, … | scrapers / web |
| `test` | Test-time dependencies | CI / developers |
| `all` | Union-style convenience extra | full optional matrix |

Native theorem-prover **binaries** remain lazy/user-local; managed install via
`ipfs-datasets-install-provers`. See
`docs/security_verification/lazy_theorem_prover_installation.md` and
[DEPENDENCY_AND_INITIALIZATION.md](../architecture/DEPENDENCY_AND_INITIALIZATION.md).

**Policy:** do not eagerly import optional stacks at package import time; do not
claim a capability is present without probing; trust/admissibility paths stay
**fail-closed** when deps are missing.

---

## 14. Cross-repository ownership

Authoritative submodule list: root `.gitmodules` (**10** entries). In this
worktree at measurement time, submodules report **not initialized** (leading
`-` in `git submodule status`).

| # | Path | Upstream | This repo owns | Upstream owns |
| --- | --- | --- | --- | --- |
| 1 | `ipfs_kit_py` | `endomorphosis/ipfs_kit_py` | Thin adapters, env gates, MCP kit tools | Kit product roadmap/release |
| 2 | `.tools/ipfs_kit_py` | same kit | Tooling layout mirror | Kit internals |
| 3 | `ipfs_accelerate_py` | `endomorphosis/ipfs_accelerate_py` | Dataset manager accelerate path, router aliases | Accelerate routers, agent-supervisor runtime |
| 4–7 | `logic/CEC/{DCEC_Library,Talos,Eng-DCEC,ShadowProver}` | respective repos | CEC integration wrappers | Prover/library internals |
| 8 | `multimedia/convert_to_txt_based_on_mime_type` | convert_to_txt… | Processors multimedia integration | Converter pipeline |
| 9 | `multimedia/omni_converter_mk2` | omni_converter_mk2 | Integration surface | Converter + system deps |
| 10 | `processors/web_archiving/common_crawl_search_engine` | common_crawl_search_engine | Processors / web_archiving wrappers | Search engine implementation |

### 14.1 External services (not vendored as product core)

| External | Integration points | Owner of truth |
| --- | --- | --- |
| Kubo / IPFS daemon | kit tools, pin/get paths | Operator / IPFS project |
| FAISS / Qdrant / Elasticsearch | `vector_stores` | Those projects |
| Neo4j | `knowledge_graphs` | Neo4j / deploy ops |
| Hugging Face Hub | `huggingface`, `voice` release | Hub + local contracts |
| Playwright / Scrapy / Selenium | processors / `scraping` extra | Those projects |
| Theorem prover vendors | `logic.external_provers` | Vendors + install policy |
| Docker / Kubernetes | `docker/`, `deployments/` | Operator manifests |

Full boundary narrative:
[INTEGRATION_BOUNDARIES.md](../architecture/INTEGRATION_BOUNDARIES.md).

---

## 15. Scripts and benchmarks (non-product)

| Tree | Tracked files | Role |
| --- | ---: | --- |
| `scripts/` | 490 | CI, copilot automation, docs audit, migrations, demos — **dev utility**, not product domain |
| `benchmarks/` | 138 | Performance suites (`bench_*.py`, logic_pipeline, semantic_roundtrip) — **evidence**, not public API |

Mention in maps and operator docs; do not place user-facing features here.

---

## 16. Contributor decision tree

1. **What responsibility is changing?** Map to a domain in §5 / DOMAIN_MAP.
2. **Where does code live?** Canonical package path under `ipfs_datasets_py/<domain>/`.
3. **Is this only exposure?** Prefer thin MCP tool under `mcp_server/tools/<category>/` or domain CLI — no duplicated algorithms.
4. **Optional stack?** Pick the extra in §13; keep imports lazy; update dependency docs if install story changes.
5. **Tests?** Add nearest unit test under `tests/unit/<domain>/` (preferred) or extend the existing nearest file in §7.2.
6. **Docs?** Architecture truth in `docs/architecture/`; how-to in `docs/guides/` or domain trees; do not add a parallel root status page.
7. **Archive/compat?** Never extend deprecated `logic.tools` or archive trees for new features.
8. **Cross-repo?** If behavior belongs in kit/accelerate/CEC/multimedia submodule, change upstream or the thin wrapper only — record ownership honestly.

---

## 17. Related sibling guides

| Guide | Relationship |
| --- | --- |
| [DOMAIN_MAP.md](../architecture/DOMAIN_MAP.md) | Full domain ownership (IPFSDOC-010) |
| [RUNTIME_ENTRYPOINTS.md](../architecture/RUNTIME_ENTRYPOINTS.md) | Console scripts, MCP, CLI (IPFSDOC-011) |
| [INTEGRATION_BOUNDARIES.md](../architecture/INTEGRATION_BOUNDARIES.md) | Submodules and external ownership |
| [DEPENDENCY_AND_INITIALIZATION.md](../architecture/DEPENDENCY_AND_INITIALIZATION.md) | Import hermeticity and optional deps |
| [DOCUMENTATION_CONTRIBUTING.md](DOCUMENTATION_CONTRIBUTING.md) | How to add docs under IA rules |
| `EXTENSION_RECIPES.md` (sibling) | How to extend processors/tools/provers |
| `TESTING_AND_EVIDENCE.md` (sibling) | Test selection and evidence classes |
| [developer_guide.md](../developer_guide.md) | Late-owned contributor entry (aggregates this map) |

---

## 18. Validation

```bash
test -s docs/developer_guides/REPOSITORY_MAP.md && rg -n 'owner|canonical|compat|tests|optional|docs' docs/developer_guides/REPOSITORY_MAP.md
```

Optional re-inventory after large tree changes:

```bash
date -u +%Y-%m-%dT%H:%M:%SZ
git rev-parse HEAD
git ls-files ipfs_datasets_py | grep -c '\.py$'
ls -1d ipfs_datasets_py/*/ | sed 's|ipfs_datasets_py/||;s|/$||' | sort
git submodule status
```

---

## 19. Non-goals

- Exhaustive per-tool MCP catalog (see MCP architecture / package MCP docs).
- Claiming pytest collect counts without running collection.
- Resolving packaging CLI drift in code (documented only).
- Treating empty submodules or archive trees as current features.
- Replacing domain architecture leaves or extension recipes.
- Editing protected documentation-refresh plan files.

---

## 20. Change log (this page)

| Date (UTC) | Change |
| --- | --- |
| 2026-08-03 | Initial `DeveloperRepositoryMap@1` from live worktree inventory for IPFSDOC-070 at commit `37f99e8a2`. |
