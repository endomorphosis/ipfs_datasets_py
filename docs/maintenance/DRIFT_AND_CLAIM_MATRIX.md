# Drift and claim matrix (claim-level stale-surface inventory)

| Field | Value |
| --- | --- |
| Task | `IPFSDOC-002` |
| Interface | `DocumentationDriftMatrix@1` |
| Measured at (UTC) | `2026-08-03T06:47:19Z` |
| Worktree HEAD | `de225a5c162b5afd8e735675c8461035c06b0bff` |
| Baseline peer | `docs/maintenance/CURRENT_STATE_BASELINE.md` (`IPFSDOC-001`, commit `e5641d787…` at measurement) |
| Scope | High-impact **version**, **Python**, **dependency-extra**, **import**, **command**, **tool-count**, **feature**, **submodule**, **API-signature**, and **completion** claims on primary audience surfaces |
| Authority order | Tests/schemas → current code/packaging → operator config → accepted ADRs → maintained guides → historical plans/status (plan §3.1) |

## How to read this matrix

Each row is one **claim** (or tightly related claim cluster) found in documentation, classified against **current tree** evidence.

| Column | Meaning |
| --- | --- |
| **ID** | Stable claim id (`CLAIM-<category>-NNN`) |
| **Priority** | `P0` user-blocking falsehood on nav spine / install path; `P1` high-impact wrong API/extra/command; `P2` secondary surface or marketing; `P3` historical/status only |
| **Claim kind** | One of: `version`, `python`, `dependency-extra`, `import`, `command`, `tool-count`, `feature`, `submodule`, `api-signature`, `completion` |
| **Source** | Doc path + approximate location (heading / line band) |
| **Claim (summary)** | What the doc asserts |
| **Evidence (current)** | Code, packaging, tests, or config that confirms or refutes |
| **Status** | `stale` / `partial` / `current` / `intentional-migration` / `historical-only` / `unverified` |
| **Owner** | Documentation lane expected to repair or own the surface |
| **Canonical target** | Page that should become the single durable truth for this claim family |
| **Disposition** | What writers must do (not product changes) |

**Rules**

1. Prefer rewriting **maintained guides** to match code; do **not** change product code to satisfy stale prose (plan §4 Out of scope).
2. **Do not blindly replace intentional migration examples.** Rows marked `intentional-migration` keep old paths only when clearly labeled as old/deprecated vs new.
3. Completion reports under `docs/PHASE_*`, `*_COMPLETE.md`, and session summaries are **evidence of past work**, not current product authority.
4. Counts that are estimates (tool totals, test case totals) must be labeled as inventory heuristics until a provisioned measurement gate exists.

### Severity / Priority rubric

| Priority | When to use |
| --- | --- |
| **P0** | Wrong Python floor, install extra names, or nav-spine install/quickstart that fails copy-paste; packaging entry-point contradictions that break first-run |
| **P1** | Wrong primary imports/API signatures on user/developer guides or FEATURES examples; tool-count presented as exact product fact without method |
| **P2** | Secondary guides, README marketing badges, optimizer-only drift, incomplete historical audits |
| **P3** | Dated phase/completion reports; archive/stub trees (route only) |

### Disposition vocabulary

| Disposition | Meaning |
| --- | --- |
| `rewrite-current` | Update prose/examples to match current code and packaging |
| `retarget-import` | Replace import/path with the relocated canonical module; keep a one-line “was:” only if migration still active |
| `align-extra-name` | Use exact extra keys from `pyproject.toml` (and note setup.py supersets if needed) |
| `command-retarget` | Point to existing scripts/entry points; archive or delete references to missing roots |
| `preserve-as-migration` | Keep old/new pairs **only** inside migration guides, clearly labeled |
| `demote-historical` | Mark page as historical; link to canonical; do not present as current status |
| `qualify-estimate` | Keep the claim only with measurement method and date, or remove numeric precision |
| `submodule-gate` | Document that capability requires initialized submodule / optional install; do not claim always-on |
| `split-authority` | Resolve pyproject vs setup.py vs README dual authorities into one packaging story |

---

## 1. Executive priority queue (writers)

| Priority | Count (this matrix) | Immediate writer focus |
| --- | ---: | --- |
| P0 | 8 | `docs/installation.md`, `docs/getting_started.md`, packaging script story, Python version floor |
| P1 | 18 | `docs/user_guide.md`, `docs/FEATURES.md`, `docs/developer_guide.md` imports/commands/APIs |
| P2 | 10 | README badges, optimizer templates, secondary guides |
| P3 | 6 | Phase/completion reports, CHANGELOG shape vs versioning |

Primary repair owners for the MkDocs spine: **installation** → **getting_started** → **user_guide** → **developer_guide** → **FEATURES** cross-links. `docs/CHANGELOG.md` is not a product version ledger (see CLAIM-version-002).

---

## 2. Claim matrix

### 2.1 Version claims

| ID | Priority | Claim kind | Source | Claim (summary) | Evidence (current) | Status | Owner | Canonical target | Disposition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CLAIM-version-001 | P1 | version | `ipfs_datasets_py/__init__.py` L8; `pyproject.toml` `version = "0.2.0"`; `setup.py` `version='0.2.0'` | Package version is **0.2.0** (authoritative packaging) | All three packaging/package sources agree on `0.2.0` | **current** | packaging / release docs | `docs/installation.md` verification snippet; future release notes | Keep; ensure all version printouts cite `__version__` / pyproject, not ad-hoc strings |
| CLAIM-version-002 | P2 | version | `docs/CHANGELOG.md` (entire file; dated `## [2025-07-04]` worker sessions) | CHANGELOG presents documentation-worker sessions as product changelog | File has **no** SemVer section headers matching `0.2.0`; content is stub-generation / docstring work logs | **stale** (as product changelog) | docs release owner | `docs/CHANGELOG.md` restructured **or** `docs/maintenance/` session logs + thin root CHANGELOG | Demote worker logs to historical; introduce version-oriented entries only when release process defines them |
| CLAIM-version-003 | P2 | version | `docs/COMPLETE_MIGRATION_GUIDE.md` L1–6, L299–300, L419–420 | Migration to v2.0.0 / August 2026 deprecation of old paths | Package version remains **0.2.0**; migration prose is schedule-oriented, not package tag | **partial** | migration docs owner | `docs/COMPLETE_MIGRATION_GUIDE.md` (keep) + version note in installation | **preserve-as-migration** for path pairs; add explicit “package version still 0.2.0; v2.0.0 is migration milestone label” callout—do not “fix” old paths to new in this guide’s OLD column |
| CLAIM-version-004 | P3 | version | `docs/FILE_CONVERTER_MIGRATION_GUIDE.md` L11 | Deprecated converters removed in **v3.0.0** | No `3.0.0` package version; deprecation module exists at `ipfs_datasets_py/processors/file_converter/deprecation.py` | **historical-only** / schedule claim | file-conversion docs | migration guide + file-conversion architecture page | Preserve schedule language; do not present as current release |

### 2.2 Python version claims

| ID | Priority | Claim kind | Source | Claim (summary) | Evidence (current) | Status | Owner | Canonical target | Disposition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CLAIM-python-001 | P0 | python | `docs/installation.md` L20 | Minimum: **Python 3.7 or higher** | `pyproject.toml` `requires-python = ">=3.12"`; `setup.py` `python_requires='>=3.12'`; README badge Python 3.12+ | **stale** | install guide owner | `docs/installation.md` | `rewrite-current` → **Python 3.12+** only (minimum = recommended floor) |
| CLAIM-python-002 | P0 | python | `docs/installation.md` L27 | Recommended: **Python 3.9 or higher** | Same packaging constraint `>=3.12` | **stale** | install guide owner | `docs/installation.md` | `rewrite-current` → recommended 3.12.x LTS-class; drop 3.9 |
| CLAIM-python-003 | P1 | python | `README.md` L5 | Badge: Python 3.12+ | Matches packaging | **current** | README owner (late index task) | README + installation | Keep aligned with pyproject |
| CLAIM-python-004 | P2 | python | `README.md` L870 (logic/CEC narrative) | CEC framework “native Python 3” + coverage claims | CEC paths are **git submodules** (empty in this worktree); not a Python-version install claim | **partial** | logic domain docs | logic architecture + submodule install | Separate language version from submodule population; see CLAIM-submodule-* |

### 2.3 Dependency-extra claims

**Authoritative extra keys (`pyproject.toml` `[project.optional-dependencies]`, 18):**  
`all`, `api`, `file_conversion`, `groth16`, `ipld`, `knowledge_graphs`, `lazy`, `legal_netherlands`, `logic`, `multimedia`, `ocr`, `profile-f-zk`, `provekit`, `scraping`, `symai_router`, `test`, `theorem-provers`, `vectors`.

`setup.py` `extras_require` is a **superset** (also includes e.g. `dev`, `ml`, `web_archive`, `file_conversion_full`, platform extras). Writers must prefer **pyproject** names for `pip install 'ipfs_datasets_py[…]'` examples unless documenting legacy setup.py installs.

| ID | Priority | Claim kind | Source | Claim (summary) | Evidence (current) | Status | Owner | Canonical target | Disposition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CLAIM-extra-001 | P0 | dependency-extra | `docs/installation.md` L76 | `pip install ipfs-datasets-py[vector]` | Extra key is **`vectors`** (plural) in pyproject; **`vector` does not exist** | **stale** | install guide | `docs/installation.md` | `align-extra-name` → `[vectors]`; list actual deps from pyproject (`sentence-transformers`, `faiss-cpu`, …) |
| CLAIM-extra-002 | P0 | dependency-extra | `docs/installation.md` L88 | `pip install ipfs-datasets-py[graphrag]` | No `graphrag` extra; closest **`knowledge_graphs`** (+ optional `logic`) | **stale** | install guide | `docs/installation.md` | `align-extra-name` → `[knowledge_graphs]`; describe GraphRAG as feature assembled from modules, not an extra name |
| CLAIM-extra-003 | P0 | dependency-extra | `docs/installation.md` L101 | `pip install ipfs-datasets-py[webarchive]` | pyproject has **`scraping`** (and setup.py has `web_archive`); **not** `webarchive` | **stale** | install guide | `docs/installation.md` | `align-extra-name` → document `scraping` (pyproject) and note setup.py `web_archive` if dual packaging is explained |
| CLAIM-extra-004 | P0 | dependency-extra | `docs/getting_started.md` L14 | `pip install ipfs-datasets-py[theorem_proving]` | Canonical key is **`theorem-provers`** (hyphen) | **stale** | getting started | `docs/getting_started.md` | `align-extra-name` → `[theorem-provers]`; point to lazy native installer `ipfs-datasets-install-provers` |
| CLAIM-extra-005 | P1 | dependency-extra | `docs/getting_started.md` L32 | `[graphrag]` extra | Same as CLAIM-extra-002 | **stale** | getting started | `docs/getting_started.md` | `align-extra-name` |
| CLAIM-extra-006 | P1 | dependency-extra | `docs/getting_started.md` L50 | `[multimedia]` | **`multimedia` exists** in pyproject | **current** | getting started | `docs/getting_started.md` | Keep; still note submodule-backed converter paths (CLAIM-submodule-002) |
| CLAIM-extra-007 | P1 | dependency-extra | `docs/getting_started.md` L77 | `[dev]` extra | **`dev` absent from pyproject**; present in **setup.py** extras | **partial** | getting started / packaging story | installation + developer_guide | Prefer `test` extra + `requirements.txt` / `scripts/setup/install.py`; if `dev` kept, mark setuptools-only |
| CLAIM-extra-008 | P1 | dependency-extra | `docs/installation.md` L113; `docs/user_guide.md` L43; `docs/getting_started.md` L99 | `[all]` installs everything | `all` exists (34 entries in baseline); setup.py notes ML may be excluded from `all` | **partial** | install guide | `docs/installation.md` | Qualify: “union of declared non-platform extras in pyproject”; list exclusions if any |
| CLAIM-extra-009 | P1 | dependency-extra | `docs/installation.md` L44; `docs/user_guide.md` L40; README install | Distribution name `ipfs-datasets-py` (hyphens) | `pyproject.toml` `name = "ipfs_datasets_py"` (underscores). Hyphen form is common PyPI normalization but docs should state the declared project name | **partial** | install guide | `docs/installation.md` | Document declared name + note PEP 503 normalization; align examples with how the project is actually published |
| CLAIM-extra-010 | P2 | dependency-extra | `docs/installation.md` L122–127, L304–305 | Pin `torch==1.10.0+cu113` / `faiss-gpu` | Far behind current stack; vectors extra uses modern `faiss-cpu` / sentence-transformers ranges | **stale** | install guide | `docs/installation.md` GPU section | Rewrite to current optional GPU guidance or mark unsupported historical snippet |

### 2.4 Import claims

| ID | Priority | Claim kind | Source | Claim (summary) | Evidence (current) | Status | Owner | Canonical target | Disposition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CLAIM-import-001 | P1 | import | `docs/user_guide.md` L61 | `from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndex` | Module missing at package root; implementation at `ipfs_datasets_py/ml/embeddings/ipfs_knn_index.py` | **stale** | user guide | `docs/user_guide.md` + embeddings API map | `retarget-import` to `ipfs_datasets_py.ml.embeddings.ipfs_knn_index` (verify export) |
| CLAIM-import-002 | P1 | import | `docs/user_guide.md` L141 | `from ipfs_datasets_py.embeddings import EmbeddingGenerator` | `ipfs_datasets_py/embeddings/__init__.py` exports engines/functions; **no** `EmbeddingGenerator` symbol (class lives under multimodal processor stubs) | **stale** | user guide | embeddings guide | `retarget-import` to documented public embedding APIs (`generate_embedding`, `AdvancedIPFSEmbeddings`, or `ml.embeddings`) |
| CLAIM-import-003 | P1 | import | `docs/user_guide.md` L228, L300 | `from ipfs_datasets_py.knowledge_graph import IPLDKnowledgeGraph` | Package is **`knowledge_graphs`** (plural); class at `ipfs_datasets_py/knowledge_graphs/ipld.py` | **stale** | user guide | knowledge graph guide | `retarget-import` → `ipfs_datasets_py.knowledge_graphs…` |
| CLAIM-import-004 | P1 | import | `docs/user_guide.md` L278 | `from ipfs_datasets_py.knowledge_graph_extraction import KnowledgeGraphExtractor` | File at `ipfs_datasets_py/knowledge_graphs/knowledge_graph_extraction.py` | **stale** | user guide | knowledge graph guide | `retarget-import` |
| CLAIM-import-005 | P1 | import | `docs/user_guide.md` L299 | `from ipfs_datasets_py.llm.llm_graphrag import GraphRAGLLMProcessor` | Lives under `ipfs_datasets_py/ml/llm/llm_graphrag.py` | **stale** | user guide | GraphRAG guide | `retarget-import` |
| CLAIM-import-006 | P1 | import | `docs/user_guide.md` L340 | `from ipfs_datasets_py.rag.rag_query_optimizer import UnifiedGraphRAGQueryOptimizer` | Path **missing** under package (no `rag/` package match for this module name) | **stale** | user guide | optimizers / GraphRAG docs | Locate current optimizer symbol under `ipfs_datasets_py/optimizers/` or demote example |
| CLAIM-import-007 | P1 | import | `docs/user_guide.md` L614 | `from ipfs_datasets_py.duckdb_connector import DuckDBConnector` | **Missing** module | **stale** | user guide | storage / analytics guide | Remove or retarget to actual DuckDB integration module when identified |
| CLAIM-import-008 | P1 | import | `docs/user_guide.md` L665 | `from ipfs_datasets_py.data_provenance import EnhancedProvenanceManager` | Provenance under `ipfs_datasets_py/analytics/data_provenance.py` (+ enhanced) | **stale** | user guide | analytics / provenance guide | `retarget-import` |
| CLAIM-import-009 | P1 | import | `docs/user_guide.md` L738–828 cluster | `access_control`, `p2p`, `federated_search`, `distributed`, `streaming`, `profiling`, `query_optimizer` package-root imports | **Missing** as package-root modules (capabilities may exist under other domains) | **stale** | user guide | domain maps (IPFSDOC domain tasks) | Do not invent paths; replace with inventory-backed imports or remove sections until mapped |
| CLAIM-import-010 | P0 | import | `docs/FEATURES.md` L16 | `from ipfs_datasets_py.logic_integration import LogicProcessor` | `LogicProcessor` is `ipfs_datasets_py.core_operations.LogicProcessor` (`core_operations/logic_processor.py`) | **stale** | features / logic docs | logic user journey + FEATURES | `retarget-import` (canonical export path in core_operations) |
| CLAIM-import-011 | P1 | import | `docs/FEATURES.md` L34–35 | `from ipfs_datasets_py.pdf_processing import PDFProcessor` + `search.logic_integration.LogicEnhancedRAG` | `PDFProcessor` at `ipfs_datasets_py/processors/pdf_processor.py` (and specialized path); `pdf_processing` package **missing**; LogicEnhancedRAG path **missing** | **stale** | features | PDF / GraphRAG guides | `retarget-import` / rewrite example |
| CLAIM-import-012 | P1 | import | `docs/FEATURES.md` L55 | `from ipfs_datasets_py.processors.file_converter import FileConverter` | **Exists** (`processors/file_converter/converter.py` class `FileConverter`) | **current** | features | file conversion guide | Keep; still verify method usage (CLAIM-api-003) |
| CLAIM-import-013 | P1 | import | `docs/FEATURES.md` L74 | `from ipfs_datasets_py.data_transformation.multimedia import YtDlpWrapper` | Canonical: `ipfs_datasets_py.processors.multimedia.YtDlpWrapper`; `data_transformation.multimedia` **missing** | **stale** as current import; **intentional-migration** if shown as OLD | features + migration guide | `docs/COMPLETE_MIGRATION_GUIDE.md` + multimedia guide | In FEATURES: `retarget-import`. In migration guide: **preserve-as-migration** OLD column only |
| CLAIM-import-014 | P1 | import | `docs/developer_guide.md` L7–8 | `ipfs_datasets_py.ipfs_kit` / `libp2p_kit` | Root modules **missing**; IPFS kit is **submodule** `ipfs_kit_py` (unpopulated) | **stale** | developer guide | cross-repo boundaries guide | Describe optional external package/submodule, not in-tree import guarantee |
| CLAIM-import-015 | P2 | import | `docs/developer_guide.md` L83–85 | Post-refactor “correct” imports: dashboards, caching, web_archive | Paths **exist** (`dashboards.mcp_dashboard`, `caching.cache`, `processors.web_archiving.web_archive`) | **current** | developer guide | developer_guide | Keep as positive examples |
| CLAIM-import-016 | P2 | import | `docs/DOCS_DRIFT_AUDIT_REPORT.md` / optimizers validate README | `admin_tools.system_health` | Actual tool: `mcp_server/tools/bespoke_tools/system_health.py` (not under `admin_tools/`) | **stale** | MCP tools docs | MCP tools guide | `retarget-import`; prior audit remains valid evidence |
| CLAIM-import-017 | P1 | import | `docs/user_guide.md` L369 | `from ipfs_datasets_py.processors.web_archiving.web_archive_utils import WebArchiveProcessor` | **Exists**; class `WebArchiveProcessor` present | **current** | user guide | web archiving guide | Keep |
| CLAIM-import-018 | P2 | import | `docs/COMPLETE_MIGRATION_GUIDE.md` L36–42 table | OLD `data_transformation.*` → NEW `processors.*` | Intentional dual listing for migration window | **intentional-migration** | migration docs | `docs/COMPLETE_MIGRATION_GUIDE.md` | **preserve-as-migration** — do not “fix” the OLD column to NEW; verify NEW column still matches tree in a later task |

### 2.5 Command claims

| ID | Priority | Claim kind | Source | Claim (summary) | Evidence (current) | Status | Owner | Canonical target | Disposition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CLAIM-cmd-001 | P0 | command | README Quick Start; vs `docs/installation.md` | Canonical install via `python scripts/setup/install.py --quick` (README) vs bare `pip install` / `pip install -e .` + missing `requirements-dev.txt` (installation.md) | `scripts/setup/install.py` **exists** (unified installer); `requirements-dev.txt` **missing**; `requirements.txt` exists | **stale** (installation.md) | install guide | `docs/installation.md` + README | Rewrite installation to lead with `scripts/setup/install.py`; list pip/editable as alternatives |
| CLAIM-cmd-002 | P1 | command | `docs/developer_guide.md` L24 | `python comprehensive_mcp_test.py` | Root file **missing**; archived at `archive/validation/comprehensive_mcp_test.py` | **stale** | developer guide / testing docs | testing strategy guide | `command-retarget` to current pytest MCP suites under `tests/` |
| CLAIM-cmd-003 | P1 | command | `docs/developer_guide.md` L25 | `python systematic_validation.py` | **Missing** at repo root | **stale** | developer guide | testing docs | Remove or retarget |
| CLAIM-cmd-004 | P1 | command | `docs/developer_guide.md` L26 | `python start_fastapi.py` | **Missing** at repo root | **stale** | developer guide | API/deployment guide | Retarget to actual FastAPI entry if present under package |
| CLAIM-cmd-005 | P1 | command | `docs/developer_guide.md` L27 | `python -m ipfs_datasets_py.mcp_server --stdio` | `mcp_server/__main__.py` supports `--stdio` / HTTP; module launch is valid pattern | **current** (flags) | developer guide | MCP server guide | Keep; document default stdio behavior from `__main__.py` |
| CLAIM-cmd-006 | P1 | command | `docs/developer_guide.md` L28 | `python -m pytest tests/test_embedding_tools.py` | Path **missing** | **stale** | developer guide | testing docs | Point to existing embedding-related tests under `tests/` |
| CLAIM-cmd-007 | P0 | command | README CLI; baseline §6 | Primary CLI `ipfs-datasets` | Declared in **setup.py** console_scripts; **absent** from `pyproject.toml` `[project.scripts]` (only 4 scripts there: netherlands-laws, ipfs-netherlands-laws, sms-bridge, install-provers). Repo root shell wrapper `ipfs-datasets` also exists | **partial** / packaging drift | install + CLI docs | CLI guide + installation | `split-authority`: document which install path exposes which entry points; do not claim pyproject-only install yields `ipfs-datasets` until packaging aligned (product fix is out of scope—document current behavior) |
| CLAIM-cmd-008 | P1 | command | FEATURES / setup.py | `file-converter` / `fc` CLIs | In setup.py only; not in pyproject scripts | **partial** | CLI / file conversion docs | CLI guide | Same split-authority treatment as CLAIM-cmd-007 |
| CLAIM-cmd-009 | P1 | command | `docs/developer_guide.md` L20–22 | `pip install -e .`, `pip install -r requirements.txt`, `python setup.py build` | requirements.txt exists; setuptools build is legacy vs pyproject | **partial** | developer guide | developer_guide | Prefer editable install via pyproject + installer script; demote `setup.py build` |
| CLAIM-cmd-010 | P2 | command | `docs/installation.md` L66 | `pip install -r requirements-dev.txt` | File **missing** | **stale** | install guide | installation / developer | Use `requirements.txt`, `[test]` extra, or installer flags |

### 2.6 Tool-count claims

| ID | Priority | Claim kind | Source | Claim (summary) | Evidence (current) | Status | Owner | Canonical target | Disposition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CLAIM-tools-001 | P1 | tool-count | `docs/FEATURES.md` L122; README L43, L381 | **200+ tools across 50+ categories** | Inventory: **47** `*_tools` category directories under `mcp_server/tools/`; **~394** non-`__init__` tool `.py` files (baseline-style filesystem count); rough `def` count ≫ 200 but **not** a registered-tool census | **partial** | MCP docs | MCP tools guide + FEATURES | `qualify-estimate`: state measurement method (categories on disk vs registered callable tools vs CLI discover). “50+ categories” is roughly consistent with 47 `*_tools` dirs; “200+ tools” needs registry-based count before hard marketing |
| CLAIM-tools-002 | P2 | tool-count | `docs/FEATURES.md` L125–154 list | Named categories (`dataset_tools`, `vscode_cli_tools`, …) | Many names match directories; some listed names may not exist as dirs (e.g. verify `vscode_cli_tools`, `github_cli_tools`, `knowledge_graph_tools` vs `graph_tools`) | **partial** | MCP docs | MCP tools guide | Reconcile list against `ls ipfs_datasets_py/mcp_server/tools` in a follow-on claim pass |
| CLAIM-tools-003 | P2 | tool-count | `docs/PHASE_5_COMPLETE.md` / `PROJECT_STATUS_FINAL.md` | Knowledge graph tools “1 → 11 (1100% increase)” | Historical phase metric; not a current registry audit | **historical-only** | archive disposition | demote phase reports | `demote-historical` |
| CLAIM-tools-004 | P2 | tool-count | README badge L8 | **4500+ tests** | Baseline: ~2684 name-pattern test modules under `tests/`; case count **not measured** without `pytest --collect-only` | **stale** as exact claim | README (late) | testing docs + baseline | `qualify-estimate` or remove badge precision; cite CURRENT_STATE_BASELINE |

### 2.7 Feature claims

| ID | Priority | Claim kind | Source | Claim (summary) | Evidence (current) | Status | Owner | Canonical target | Disposition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CLAIM-feature-001 | P1 | feature | `docs/FEATURES.md` L7–12; README | Theorem proving: Z3, CVC5, Lean 4, Coq | `theorem-provers` extra provides Python bindings; native Lean/Coq/etc. are **lazy/local** install via `ipfs-datasets-install-provers` (comments in pyproject/setup) | **partial** | logic docs | theorem prover architecture + installation | Separate pip extra from native prover install; never imply all provers ship in-wheel |
| CLAIM-feature-002 | P1 | feature | `docs/FEATURES.md` L30; README test bullets | “4,400+ test functions” / “790+ tests” domain claims | Not re-validated; conflicts with unmeasured case counts in baseline | **unverified** | features / domain docs | domain guides with last-verified | Remove or attach measurement command + date |
| CLAIM-feature-003 | P1 | feature | README L36–48 Key Features | Production-ready IPLD vector DB, GraphRAG, MCP, ZK, etc. | Large code domains exist (`vector_stores`, `optimizers`, `mcp_server`, `logic`); production-ready is a **quality claim** not proven by file presence | **partial** | product docs | architecture guides + evidence links | Feature existence OK; tone down universal “production ready” without per-surface evidence |
| CLAIM-feature-004 | P2 | feature | `docs/FEATURES.md` L45–50 | Universal file conversion 60+ formats, async/sync | `FileConverter` with `convert` / `convert_sync` exists under processors | **partial** | file conversion docs | file conversion guide | Keep capability claim; verify format count against backend registry before hard “60+” |
| CLAIM-feature-005 | P2 | feature | `docs/FEATURES.md` L62–69 | 1000+ platforms via yt-dlp | yt-dlp wrapper exists; “1000+” is upstream yt-dlp marketing, not local enumeration | **partial** | multimedia docs | multimedia guide | Attribute count to yt-dlp upstream; document optional deps/ffmpeg |
| CLAIM-feature-006 | P1 | feature | README / FEATURES hardware acceleration | `ipfs_accelerate_py` 2–20× speedup always available | Submodule **unpopulated** in this worktree; optional integration package | **partial** | accelerate docs | cross-repo + performance | `submodule-gate` + optional dependency language |
| CLAIM-feature-007 | P1 | feature | README / FEATURES decentralized storage | `ipfs_kit_py` comprehensive IPFS operations | Submodule **unpopulated**; not a guaranteed import | **partial** | IPFS docs | storage architecture | `submodule-gate` |
| CLAIM-feature-008 | P2 | feature | `docs/developer_guide.md` L53–58 | FastAPI endpoint map `/datasets/`, `/vectors/`, … | FastAPI surface may exist under package; root `start_fastapi.py` missing—paths need map task | **unverified** | API docs | API reference | Verify against actual app routes before keeping |

### 2.8 Submodule claims

| ID | Priority | Claim kind | Source | Claim (summary) | Evidence (current) | Status | Owner | Canonical target | Disposition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CLAIM-submodule-001 | P0 | submodule | Docs that assume kit/accelerate/CEC always present | Features requiring nested repos work out of the box | `.gitmodules`: **10** submodules; `git submodule status` all **`-`** (not checked out); empty working trees | **stale** (implicit always-on) | install + domain guides | installation “optional components” + baseline §8 | Document `git submodule update --init` (or product-approved alternative); mark features as gated |
| CLAIM-submodule-002 | P1 | submodule | Multimedia converter docs / package layout | `multimedia/convert_to_txt…` and `omni_converter_mk2` available | Declared submodules; **empty** in worktree; processors may still ship root wrappers | **partial** | multimedia docs | multimedia guide | Distinguish in-tree wrappers vs submodule backends |
| CLAIM-submodule-003 | P1 | submodule | Logic/CEC documentation | DCEC_Library, Talos, Eng-DCEC, ShadowProver available | All four CEC submodules **empty** | **partial** | logic docs | CEC/DCEC architecture | `submodule-gate` + test markers for native deps |
| CLAIM-submodule-004 | P2 | submodule | Web archiving Common Crawl engine | Nested `common_crawl_search_engine` | Submodule empty | **partial** | web archiving docs | web archiving guide | `submodule-gate` |
| CLAIM-submodule-005 | P2 | submodule | Dual `ipfs_kit_py` and `.tools/ipfs_kit_py` | Single kit checkout | Two gitlink paths, same URL/commit in status | **partial** | developer environment docs | contributor setup | Explain dual path or consolidate in packaging docs (docs only) |

### 2.9 API-signature claims

| ID | Priority | Claim kind | Source | Claim (summary) | Evidence (current) | Status | Owner | Canonical target | Disposition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CLAIM-api-001 | P0 | api-signature | README Basic Usage | `DatasetManager().load_dataset(...); manager.save_dataset(dataset, path)` | `DatasetManager` has **`get_dataset`**, **`save_dataset(dataset_id, dataset)`** — **no** `load_dataset` method; `save_dataset` signature differs from README | **stale** | getting started / README | user_guide datasets section | Rewrite example to real methods |
| CLAIM-api-002 | P1 | api-signature | `docs/FEATURES.md` L16–20 | `LogicProcessor().convert_to_logic(...); result.generate_proof()` | Public class exists in `core_operations`; method names need verification against `logic_processor.py` before trust | **unverified** / likely stale import path | logic docs | logic API map | After import fix, align methods to actual public API (read source, not completion reports) |
| CLAIM-api-003 | P1 | api-signature | `docs/FEATURES.md` L55–59 | `FileConverter().convert` returns object with `.text` | `async def convert` / `convert_sync` exist; result type must match `ConversionResult` contract | **partial** | file conversion | file conversion guide | Verify attribute names on result monad; prefer typed example from tests |
| CLAIM-api-004 | P1 | api-signature | `docs/FEATURES.md` L74–79 | `YtDlpWrapper().download_video(...)` | `async def download_video` exists on wrapper | **partial** (import path wrong; method plausible) | multimedia | multimedia guide | Fix import; keep async example pattern |
| CLAIM-api-005 | P1 | api-signature | `docs/optimizers/HOW_TO_ADD_NEW_OPTIMIZER.md` (audit L30–50) | Template: `generate(source_data, context: Dict)`, `critique`→Dict, `optimize(..., feedback: Dict)` | Actual `BaseOptimizer` (`optimizers/common/base_optimizer.py`): `generate(input_data, context)`, `critique`→score/feedback structure, `optimize(artifact, score, feedback, context)` with `OptimizationContext` | **stale** | optimizers docs | optimizers developer guide | `rewrite-current` template to match ABC (prior `docs/DOCS_DRIFT_AUDIT_REPORT.md`) |
| CLAIM-api-006 | P2 | api-signature | `docs/user_guide.md` IPFSKnnIndex usage | `IPFSKnnIndex(dimension=…); add_vectors; search` | Class relocated under `ml/embeddings`; signatures need re-check after import retarget | **unverified** | user guide | vector/embeddings guide | Retarget then verify against class body / tests |
| CLAIM-api-007 | P2 | api-signature | `docs/user_guide.md` media tools | Imports `ffmpeg_convert` from `media_tools` | `media_tools/__init__.py` exports `ffmpeg_convert` | **current** (export) | user guide | media tools | Keep; ensure await/async matches function |

### 2.10 Completion claims

| ID | Priority | Claim kind | Source | Claim (summary) | Evidence (current) | Status | Owner | Canonical target | Disposition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CLAIM-complete-001 | P3 | completion | `docs/IPLD_VECTOR_DATABASE_PROJECT_COMPLETE.md` | “ALL 8 PHASES 100% COMPLETE” | Historical project report; not continuous verification against current tree | **historical-only** | archive disposition (IPFSDOC legacy tasks) | IPLD vector **architecture** guide (to be maintained) | `demote-historical`; do not use as current status in nav |
| CLAIM-complete-002 | P3 | completion | `docs/PHASE_5_COMPLETE.md`, `docs/PHASE_6_COMPLETE.md`, `docs/PHASE_7_8_COMPLETE.md`, etc. | Phase N complete with 100% metrics | Point-in-time engineering reports | **historical-only** | archive disposition | phase archive index | `demote-historical` |
| CLAIM-complete-003 | P2 | completion | `docs/PROJECT_STATUS_FINAL.md` | MCP refactoring **77% complete**, 4 weeks to 100% | Contradicts phase-complete docs and undated relative to 2026 tree | **stale** as live status | program status | replace with maintenance dashboards / not product docs | `demote-historical`; never cite as current completion |
| CLAIM-complete-004 | P2 | completion | README badge L6–7 | “Production Ready” | Marketing badge without per-surface SLOs | **partial** | README | release criteria (program) | Soften or scope to specific surfaces with evidence |
| CLAIM-complete-005 | P2 | completion | README L44 | Auto-fix “100% verified” | Unverified absolute claim | **stale** / marketing | README / SE tools docs | software engineering tools guide | Remove absolute % or cite test gate |
| CLAIM-complete-006 | P3 | completion | `docs/CHANGELOG.md` worker sessions | “Technical Debt Resolved”, “All core package classes now have comprehensive docstrings” | Aspirational session notes; not a continuous doc coverage proof | **historical-only** | docs quality | documentation metrics (later tasks) | Demote; use inventory-based coverage matrix instead |
| CLAIM-complete-007 | P1 | completion | Any guide stating “full functionality without IPFS daemon” vs “requires daemon” | installation.md says daemon optional for full functionality (L162 area) | Capability matrix depends on feature; needs domain-specific truth | **partial** | install + storage | installation + storage guides | Split optional vs required by feature table |

---

## 3. Surface-level rollup (MkDocs spine + required guides)

| Surface | Role | Highest open Priority | Dominant failure modes | Writer action |
| --- | --- | --- | --- | --- |
| `docs/installation.md` | Install authority (nav) | **P0** | Python 3.7/3.9; extras `vector`/`graphrag`/`webarchive`; missing requirements-dev; ancient torch pins | Full rewrite against pyproject + `scripts/setup/install.py` |
| `docs/getting_started.md` | First success path (nav) | **P0** | `theorem_proving`, `graphrag`, `dev` extras | Align extras; match working README installer story |
| `docs/user_guide.md` | User journeys (nav) | **P1** | Mass package-root import rot; missing modules | Section-by-section retarget using package inventory |
| `docs/developer_guide.md` | Contributor spine (nav) | **P1** | Missing root test/server scripts; submodule imports | Commands → tests/; optional deps explicit |
| `docs/FEATURES.md` | Feature catalog (root) | **P0/P1** | Wrong LogicProcessor/PDF/YtDlp imports; tool counts | Fix examples; qualify counts |
| `docs/CHANGELOG.md` | Release history (root) | **P2** | Not SemVer product changelog | Restructure or demote |
| `README.md` | External landing | **P0/P1** | Entry-point vs pyproject; DatasetManager API; badges | Coordinate with late navigation owner; do not invent second install truth |
| `docs/COMPLETE_MIGRATION_GUIDE.md` | Migration | — | Old paths intentional | **preserve-as-migration** |
| `docs/DOCS_DRIFT_AUDIT_REPORT.md` | Prior audit (2026-02-24) | P2 | Optimizers/admin_tools subset | Incorporate findings; not full-repo authority |
| Phase `*_COMPLETE.md` | Historical | P3 | Completion language | Disposition map only |

---

## 4. Intentional migration examples (do not blindly rewrite)

These documents **must** keep pre-migration paths when labeled as deprecated/OLD:

| Document | Why preserve | Correct handling |
| --- | --- | --- |
| `docs/COMPLETE_MIGRATION_GUIDE.md` | Explicit OLD → NEW table for `data_transformation` → `processors` | Verify NEW side; never delete OLD column |
| `docs/FILE_CONVERTER_MIGRATION_GUIDE.md` | Deprecation schedule for legacy converters | Keep deprecation list; update only incorrect “current” recommendations |
| `docs/MULTIMEDIA_MIGRATION_GUIDE.md` / `docs/WEB_ARCHIVING_MIGRATION_GUIDE.md` / related | Migration narrative | Same rule |
| `docs/developer_guide.md` “Don’t use old import paths” | Negative examples | Keep as warnings; ensure “correct” side stays valid (CLAIM-import-015) |

If a **current** guide (installation, user_guide, FEATURES) uses an old path **without** migration labeling, treat it as **stale**, not as intentional migration (see CLAIM-import-013).

---

## 5. Packaging dual-authority (cross-cutting)

| Topic | `pyproject.toml` | `setup.py` | Doc implication |
| --- | --- | --- | --- |
| Project version | `0.2.0` | `0.2.0` | Aligned |
| Python | `>=3.12` | `>=3.12` | Aligned; docs behind |
| Console scripts | 4 specialized | 8 including `ipfs-datasets`, `file-converter` | Docs must say which install backend users use |
| Extras | 18 keys | Superset + alternate names (`web_archive`, `dev`, `ml`, …) | Prefer pyproject keys in all new examples |
| Dependencies | dynamic in pyproject | concrete lists in setup/requirements | Installer script is practical authority for editable workspaces |

---

## 6. Evidence index (commands used)

```bash
# Packaging
python3 -c "import tomllib; from pathlib import Path; p=tomllib.loads(Path('pyproject.toml').read_bytes()); print(p['project']['version'], p['project']['requires-python'], sorted(p['project']['optional-dependencies']), p['project'].get('scripts'))"

# Version
rg -n '__version__' ipfs_datasets_py/__init__.py

# Submodules
git submodule status
git config -f .gitmodules --get-regexp path

# MCP inventory
find ipfs_datasets_py/mcp_server/tools -maxdepth 1 -type d -name '*_tools' | wc -l
find ipfs_datasets_py/mcp_server/tools -name '*.py' ! -name '__init__.py' | wc -l

# Import existence spot-check (examples)
test -e ipfs_datasets_py/ml/embeddings/ipfs_knn_index.py
test -e ipfs_datasets_py/knowledge_graphs/ipld.py
test -e ipfs_datasets_py/core_operations/logic_processor.py
test ! -e ipfs_datasets_py/ipfs_knn_index.py

# Prior specialized audit
test -s docs/DOCS_DRIFT_AUDIT_REPORT.md

# Baseline peer
test -s docs/maintenance/CURRENT_STATE_BASELINE.md
```

Baseline peer document: `docs/maintenance/CURRENT_STATE_BASELINE.md` (inventory counts, extras table, entry points, submodules).

---

## 7. Recommended repair order (for downstream guide tasks)

1. **P0 install/python/extras** — `docs/installation.md`, `docs/getting_started.md` (CLAIM-python-*, CLAIM-extra-001–004, CLAIM-cmd-001/007).
2. **P0/P1 FEATURES + LogicProcessor / media imports** — stop advertising impossible imports (CLAIM-import-010–013, CLAIM-api-001).
3. **P1 user_guide import sweep** — CLAIM-import-001–009.
4. **P1 developer commands** — CLAIM-cmd-002–006, CLAIM-cmd-010.
5. **P1 tool-count qualification** — CLAIM-tools-001 with registry-based method when provisioned.
6. **P2 README badges / marketing** — CLAIM-tools-004, CLAIM-complete-004/005 (late shared-owner).
7. **P3 historical completion demotion** — CLAIM-complete-001–003, CLAIM-complete-006 (legacy disposition task).
8. **Always** leave intentional migration OLD paths in place (section 4).

---

## 8. Explicit non-goals / out of scope for this artifact

- Editing production code, packaging, or tests to match documentation.
- Deleting or moving historical Markdown (disposition only).
- Exhaustive audit of all 1476 `docs/**/*.md` pages (this matrix prioritizes **high-impact** spine and catalog claims; domain deep-dives continue in later IPFSDOC tasks).
- Live PyPI publication verification or network install tests.
- Full MCP tool registry runtime enumeration (requires importable env with deps).

---

## 9. Acceptance mapping

| Acceptance requirement | Where satisfied |
| --- | --- |
| Classify version / Python / dependency-extra / import / command / tool-count / feature / submodule / API-signature / completion claims | Sections 2.1–2.10 |
| Exact source evidence | Source + Evidence columns |
| Severity | Priority column + section 1 |
| Owner | Owner column |
| Canonical target | Canonical target column |
| Disposition | Disposition column + vocabulary |
| Do not blindly replace intentional migration examples | Section 4 + `intentional-migration` status rows |
| Touches installation.md, user_guide.md, developer_guide.md, FEATURES.md, CHANGELOG.md, Priority | Sections 2–3 throughout |

---

## 10. Document control

| Item | Value |
| --- | --- |
| Produced by | `IPFSDOC-002` implementation |
| Depends on | `IPFSDOC-001` baseline inventory |
| Feeds | Guide rewrite tasks, coverage matrix, legacy disposition, claim-check gates |
| Refresh when | Packaging extras/scripts change, major import renames, or nav spine rewrite lands |
