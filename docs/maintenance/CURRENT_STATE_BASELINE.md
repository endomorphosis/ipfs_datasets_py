# Current state baseline (documentation and code surface)

| Field | Value |
| --- | --- |
| Task | `IPFSDOC-001` |
| Interface | `DocumentationBaseline@1` |
| Measured at (UTC) | `2026-08-03T06:32:02Z` |
| Measurement host Python | `Python 3.12.3` |
| Branch | `implementation/ipfsdoc-001-8d786d6559c9-attempt-1-1785738657` |
| Working tree | clean (`git status --porcelain` empty) |
| Authority | Fresh measurement of this worktree only. Do **not** treat README badges, prior status reports, or historical plans as count authority. |

## How to read this document

- **Tracked fact** — Obtained from `git`, filesystem inventory, or parsed committed configuration in this worktree. Reproducible with the commands in [Reproducible commands](#reproducible-commands).
- **Derived fact** — Arithmetic or parsing over tracked facts (for example, nav leaf count from `mkdocs.yml`).
- **Estimate** — Useful but non-authoritative approximation (for example, pytest-collectable file names without running `pytest --collect-only`).
- **Not measured** — Explicitly out of scope or unavailable in this environment (called out where relevant).

Counts are for the commit recorded below. Re-run the commands after any tree change.

---

## 1. Commit identity

| Field | Value | Kind |
| --- | --- | --- |
| Full commit | `e5641d78761a8138352cbb06720468a129a591b3` | Tracked fact |
| Short commit | `e5641d787` | Tracked fact |
| Commit subject | `docs: plan comprehensive documentation renewal` | Tracked fact |
| Committer date | `2026-08-03 06:27:34 +0000` | Tracked fact |
| Tree id (this task envelope) | `e5641d78761a8138352cbb06720468a129a591b3` | Tracked fact |
| Upstream tracking | none | Tracked fact |

```bash
git rev-parse HEAD
git log -1 --format='%H %ci %s'
```

---

## 2. Inventory counts (Python / package / test / docs)

### 2.1 Repository-wide tracked inventory

| Metric | Count | Kind | Method |
| --- | ---: | --- | --- |
| Tracked files (all) | 11850 | Tracked fact | `git ls-files \| wc -l` |
| Tracked `*.py` | 6838 | Tracked fact | `git ls-files '*.py' \| wc -l` |
| Tracked `*.md` (Markdown) | 2212 | Tracked fact | `git ls-files '*.md' \| wc -l` |
| Tracked `*.json` | 1555 | Tracked fact | extension histogram from `git ls-files` |
| Tracked `*.html` | 169 | Tracked fact | extension histogram |
| Tracked `*.feature` | 153 | Tracked fact | extension histogram |
| Tracked `*.rst` | 40 | Tracked fact | extension histogram |
| Tracked `*.doctree` | 40 | Tracked fact | extension histogram |

### 2.2 Path-scoped tracked counts

| Path | Tracked files | Tracked `*.py` | Tracked `*.md` | Kind |
| --- | ---: | ---: | ---: | --- |
| `ipfs_datasets_py/` | 3736 | 3005 | 387 | Tracked fact |
| `tests/` | 3339 | 3005 | 44 | Tracked fact |
| `docs/` | 1837 | 9 | 1476 | Tracked fact |
| `scripts/` | 490 | 393 | 16 | Tracked fact |
| `examples/` | 106 | 94 | 10 | Tracked fact |
| `benchmarks/` | 138 | 126 | 6 | Tracked fact |
| `archive/` | 1795 | 143 | 161 | Tracked fact |

```bash
git ls-files ipfs_datasets_py | wc -l
git ls-files ipfs_datasets_py | grep -c '\.py$'
git ls-files ipfs_datasets_py | grep -c '\.md$'
# repeat for tests docs scripts examples benchmarks archive
```

### 2.3 Filesystem package / test Python counts

| Metric | Count | Kind | Notes |
| --- | ---: | --- | --- |
| `ipfs_datasets_py/**/*.py` (no `__pycache__`) | 3006 | Tracked fact (filesystem) | One file not in `git ls-files` (see note) |
| Tracked package `*.py` | 3005 | Tracked fact (git) | Prefer this for “in-repo package surface” |
| `tests/**/*.py` | 3005 | Tracked fact | Matches tracked package py count by coincidence |
| `test/**/*.py` (legacy root) | 2 | Tracked fact | `test/api/test_agent_supervisor_*.py` |
| Package `__init__.py` modules | 344 | Tracked fact | `find ipfs_datasets_py -name '__init__.py'` |

**Note (package py discrepancy):** Filesystem finds one extra path not listed by `git ls-files`:

`ipfs_datasets_py/processors/multimedia/convert_to_txt_based_on_mime_type/test/test_external_interface/test_file_manager.py`

(Related submodule checkout path is `ipfs_datasets_py/multimedia/convert_to_txt_based_on_mime_type`, which is empty in this worktree.)

### 2.4 Test-surface classification (`tests/`)

| Metric | Count | Kind |
| --- | ---: | --- |
| All Python under `tests/` | 3005 | Tracked fact |
| `test_*.py` | 2644 | Tracked fact |
| `*_test.py` | 40 | Tracked fact |
| Union of `test_*.py` ∪ `*_test.py` | 2684 | Derived fact |
| `conftest.py` under `tests/` | 29 | Tracked fact |
| Other Python under `tests/` (helpers/fixtures/support) | 292 | Derived fact |
| `*.feature` under `tests/` | 153 | Tracked fact |

| Metric | Value | Kind |
| --- | --- | --- |
| Pytest collectable modules | ~2686 name-pattern files (`tests/` + `test/`) | **Estimate** — name heuristic only; does not run collection or import |
| Executable test *functions/cases* | not measured | **Not measured** — requires `pytest --collect-only` with full deps |

### 2.5 Markdown / documentation file counts

| Metric | Count | Kind |
| --- | ---: | --- |
| Tracked Markdown (repo) | 2212 | Tracked fact |
| `docs/**/*.md` | 1476 | Tracked fact |
| `ipfs_datasets_py/**/*.md` | 387 | Tracked fact |
| `tests/**/*.md` | 44 | Tracked fact |
| Docs root `docs/*.md` | 117 | Tracked fact |
| Docs tracked HTML | 70 | Tracked fact |
| Docs tracked RST | 40 | Tracked fact |

**Package name / version (from `pyproject.toml`):** `ipfs_datasets_py` **0.2.0**, `requires-python = ">=3.12"`. Core runtime dependencies are declared `dynamic = ["dependencies"]` (count of static `project.dependencies` entries = **0**).

---

## 3. Root-page count

**Definition used:** Markdown files directly under `docs/` (depth 1), not including subdirectories.

| Metric | Count | Kind |
| --- | ---: | --- |
| Root pages (`docs/*.md`) | **117** | Tracked fact |

Canonical audience pages present among root files (existence only; quality not scored):

| Page | Present |
| --- | --- |
| `docs/index.md` | yes |
| `docs/getting_started.md` | yes |
| `docs/installation.md` | yes |
| `docs/user_guide.md` | yes |
| `docs/developer_guide.md` | yes |
| `docs/configuration.md` | yes |
| `docs/README.md` | yes |
| `docs/DOCUMENTATION_INDEX.md` | yes |

Full root-page list (117 names, sorted):

```text
AGENTIC_LEGAL_SCRAPER_DAEMON.md
ARCHITECTURE_VALIDATION_QUICK_START.md
ARCHITECTURE_VALIDATION_REPORT.md
BATCH_325_LIFECYCLE_HOOKS_SUMMARY.md
BATCH_326_MUTATION_TESTING_SUMMARY.md
BATCH_327_PARITY_TESTING_SUMMARY.md
CHANGELOG.md
CLI_MCP_ALIGNMENT.md
CLI_MCP_ALIGNMENT_ANALYSIS.md
CLI_MCP_INTEGRATION_GUIDE.md
COMPLETE_MIGRATION_GUIDE.md
CORE_MODULES_API.md
CORE_OPERATIONS_GUIDE.md
CROSS_CUTTING_INTEGRATION_GUIDE.md
DATA_TRANSFORMATION_MIGRATION_SUMMARY.md
DEPRECATION_SCHEDULE.md
DEPRECATION_TIMELINE.md
DOCS_DRIFT_AUDIT_REPORT.md
DOCUMENTATION_INDEX.md
DOCUMENTATION_INDEX_COMPLETE.md
DOMAIN_AWARE_CONFIG.md
ENHANCEMENT_12_MCP_COMPLETION.md
EXTRACTION_CONFIG_GUIDE.md
EXTRACTION_PERFORMANCE_BASELINE_2026_02_24.md
FEATURES.md
FILE_CONVERTER_MIGRATION_GUIDE.md
GLOSSARY.md
GRAPHRAG_CONSOLIDATION_GUIDE.md
GRAPH_STORAGE_INTEGRATION.md
HOTPATH_PERFORMANCE_ANALYSIS.md
IPLD_VECTOR_DATABASE_GUIDE.md
IPLD_VECTOR_DATABASE_PRODUCTION_POLISH_PLAN.md
IPLD_VECTOR_DATABASE_PROJECT_COMPLETE.md
IPLD_VECTOR_DATABASE_SESSION_STATUS.md
IPLD_VECTOR_STORE_ARCHITECTURE.md
IPLD_VECTOR_STORE_DOCUMENTATION_INDEX.md
IPLD_VECTOR_STORE_EXAMPLES.md
IPLD_VECTOR_STORE_FINAL_SUMMARY.md
IPLD_VECTOR_STORE_IMPLEMENTATION_SESSION_STATUS.md
IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md
IPLD_VECTOR_STORE_PLANNING_SESSION_SUMMARY.md
IPLD_VECTOR_STORE_QUICKSTART.md
LEGAL_IR_HAMMER_LEANSTRAL_AGENT_TODOS.md
LEGAL_IR_HAMMER_LEANSTRAL_OPERATOR_RUNBOOK.md
LEGAL_SCRAPERS_COMMON_CRAWL_GUIDE.md
MASTER_EXECUTION_GUIDE.md
MCPPLUSPLUS_INTEGRATION_INFINITE_TODO.md
MCPPLUSPLUS_INTEGRATION_TODO.md
MCP_ARCHITECTURE_DIAGRAM.md
MCP_IMPLEMENTATION_STATUS.md
MCP_PHASES_5_8_PLAN.md
MCP_QUICKSTART.md
MCP_REFACTORING_PLAN.md
MCP_REFACTORING_SUMMARY.md
MCP_TESTING_GUIDE.md
MCP_TOOLS_GUIDE.md
MIGRATION_CHANGELOG.md
MIGRATION_GUIDE_V2.md
MIGRATION_TOOLS_USER_GUIDE.md
MULTIMEDIA_ARCHITECTURE_ANALYSIS.md
MULTIMEDIA_MIGRATION_GUIDE.md
MULTIMEDIA_STRUCTURE_REVIEW.md
OPTIMIZATION_LOOP_ARCHITECTURE.md
OPTIMIZERS_QUICK_START.md
PERFORMANCE_TUNING_GUIDE.md
PHASE3C4_CIRCUIT_IMPLEMENTATION.md
PHASE3C5_GOLDEN_VECTOR_COMPLETION.md
PHASE3C6_COMPLETION_REPORT.md
PHASE3C6_COST_ANALYSIS_AND_ARCHITECTURE.md
PHASE3C6_ONCHAIN_INTEGRATION_PLAN.md
PHASE3C6_SEPOLIA_DEPLOYMENT_GUIDE.md
PHASE3C7_QUICK_START.md
PHASE3C7_SEPOLIA_DEPLOYMENT_EXECUTION.md
PHASE3C_COMPLETION_1_2.md
PHASE3C_COMPLETION_FULL.md
PHASE3C_GATE_OPENING.md
PHASE3C_QUICK_START.md
PHASE3D_4_PLUS_ROADMAP.md
PHASES_5_8_STATUS.md
PHASE_2_6_COMPLETION_REPORT.md
PHASE_2_ARCHITECTURE_VALIDATION_SUMMARY.md
PHASE_5_COMPLETE.md
PHASE_6_COMPLETE.md
PHASE_7_8_COMPLETE.md
PHASE_7_8_COMPREHENSIVE_PLAN.md
PHASE_9_COMPLETION_REPORT.md
PHASE_9_PARTS_3-5_FINAL_SESSION_SUMMARY.md
PHASE_9_PARTS_3-5_SESSION_SUMMARY.md
PHASE_9_PROGRESS_REPORT.md
PROFILING_EXTRACT_RULE_BASED.md
PROJECT_STATUS_FINAL.md
QUERY_OPTIMIZER_MODULARIZATION_PLAN.md
QUERY_VALIDATION_MIXIN.md
QUICK_START_NEW_ARCHITECTURE.md
README.md
SENTENCE_WINDOW_BENCHMARK_REPORT.md
SESSION_SUMMARY_PHASE3C_COMPLETION.md
TESTING_STRATEGY.md
TEST_COVERAGE_SUMMARY.md
THIRD_PARTY_INTEGRATION.md
USAGE_EXAMPLES.md
WEB_ARCHIVING_MIGRATION_GUIDE.md
WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md
WEB_ARCHIVING_UNIFIED_API_REFACTOR_PLAN.md
WORK_SUMMARY_2026_02_23.md
configuration.md
deployment.md
developer_guide.md
faq.md
getting_started.md
index.md
installation.md
profile_g_datasets_provider.md
root_DOCUMENTATION_INDEX.md
root_EXTRACTION_CONFIG_GUIDE.md
unified_dashboard.md
user_guide.md
```

```bash
find docs -maxdepth 1 -name '*.md' | wc -l
```

---

## 4. Navigated-page count (MkDocs)

**Source:** committed `mkdocs.yml` (theme `mkdocs`, plugin `search`, `docs_dir: docs`, `site_dir: site`).

| Metric | Count | Kind |
| --- | ---: | --- |
| Top-level `nav` entries | 6 | Derived fact |
| Navigated page refs (nav leaf paths) | **7** | Derived fact |
| Unique navigated paths | 7 | Derived fact |
| Nav targets missing on disk | 0 | Tracked fact |
| Markdown under `docs/` not linked in `nav` | 1469 | **Estimate** (= 1476 − 7; ignores non-nav inclusion mechanisms) |

### 4.1 MkDocs navigation map

| Nav label | Path |
| --- | --- |
| Home | `index.md` |
| Getting Started | `getting_started.md` |
| Installation | `installation.md` |
| User Guide | `user_guide.md` |
| Developer Guide | `developer_guide.md` |
| API Reference → Optimizers API | `api/OPTIMIZERS_API_REFERENCE.md` |
| API Reference → Core Operations API | `api/CORE_OPERATIONS_API.md` |

**Observation:** MkDocs publishes a thin spine (7 pages) over a large `docs/` tree (1476 Markdown files). Most documentation is unnavigated from the MkDocs site graph.

**Site build artifact:** no `site/` directory present at measurement time. Optional MkDocs binary availability was not required for this baseline.

```bash
python3 -c "import yaml; from pathlib import Path; d=yaml.safe_load(Path('mkdocs.yml').read_text()); print(d['nav'])"
```

---

## 5. Top-level domains

### 5.1 Package domains (`ipfs_datasets_py/` first-level directories)

**Count: 39** top-level package directories (tracked fact).

| Domain | `*.py` | `*.md` |
| --- | ---: | ---: |
| `accelerate_integration/` | 4 | 0 |
| `admin/` | 2 | 0 |
| `alerts/` | 5 | 0 |
| `analytics/` | 6 | 0 |
| `audit/` | 18 | 26 |
| `caching/` | 8 | 0 |
| `cli/` | 13 | 0 |
| `config/` | 2 | 3 |
| `core_operations/` | 10 | 0 |
| `dashboards/` | 19 | 0 |
| `embeddings/` | 7 | 0 |
| `error_reporting/` | 9 | 2 |
| `huggingface/` | 6 | 0 |
| `install/` | 0 | 0 |
| `ipfs_cluster/` | 2 | 0 |
| `knowledge_graphs/` | 103 | 15 |
| `logic/` | 650 | 20 |
| `mcp_server/` | 531 | 176 |
| `messaging/` | 2 | 0 |
| `ml/` | 33 | 17 |
| `multimedia/` | 0 | 0 |
| `optimizers/` | 385 | 4 |
| `p2p_networking/` | 11 | 0 |
| `processors/` | 974 | 95 |
| `rate_limiting/` | 2 | 0 |
| `scripts/` | 7 | 0 |
| `search/` | 34 | 5 |
| `sessions/` | 2 | 0 |
| `skills/` | 1 | 2 |
| `static/` | 0 | 1 |
| `storage/` | 2 | 0 |
| `templates/` | 0 | 0 |
| `tests/` | 17 | 0 |
| `utils/` | 46 | 9 |
| `vector_stores/` | 19 | 12 |
| `voice/` | 13 | 0 |
| `wallet/` | 17 | 0 |
| `web_archiving/` | 15 | 0 |
| `workflow_automation/` | 7 | 0 |

Largest code domains by Python count: `processors` (974), `logic` (650), `mcp_server` (531), `optimizers` (385), `knowledge_graphs` (103).

**Top-level package modules** (24 `*.py` files at package root, including `__init__.py`):  
`__init__.py`, `_dependencies.py`, `_router_alias.py`, `audit.py`, `auto_installer.py`, `config.py`, `content_discovery.py`, `database_utils.py`, `dataset_manager.py`, `dependency_catalog.py`, `deps_resolver.py`, `embedding_router.py`, `embeddings_router.py`, `ipfs_backend_router.py`, `ipfs_datasets.py`, `lazy_dependencies.py`, `llm_router.py`, `monitoring.py`, `monitoring_engine.py`, `multimodal_router.py`, `profile_g.py`, `router_deps.py`, `security.py`, `voice_router.py`.

### 5.2 Documentation domains (`docs/` first-level directories)

**Count: 30** top-level directories under `docs/` (tracked fact).

| Domain | `*.md` |
| --- | ---: |
| `analysis/` | 12 |
| `api/` | 2 |
| `architecture/` | 21 |
| `archive/` | 245 |
| `archived_stubs/` | 124 |
| `auto_generated_stubs/` | 1 |
| `benchmarks/` | 21 |
| `dashboards/` | 1 |
| `deployment/` | 3 |
| `developer_guides/` | 1 |
| `examples/` | 10 |
| `guides/` | 250 |
| `implementation/` | 65 |
| `knowledge_graphs/` | 44 |
| `logic/` | 267 |
| `migration_docs/` | 22 |
| `migration_guides/` | 1 |
| `modules/` | 1 |
| `optimizers/` | 76 |
| `performance_snapshots/` | 1 |
| `profiling/` | 1 |
| `quickstart/` | 4 |
| `rag_optimizer/` | 4 |
| `reorganization/` | 3 |
| `reports/` | 72 |
| `schemas/` | 0 |
| `security_verification/` | 93 |
| `tdfol/` | 3 |
| `tutorials/` | 9 |
| `user_guides/` | 2 |

Plus **117** root-level Markdown pages (section 3). Largest doc domains by Markdown: `logic` (267), `guides` (250), `archive` (245), `archived_stubs` (124), `security_verification` (93).

### 5.3 MkDocs top-level nav domains

Six top-level nav labels: **Home**, **Getting Started**, **Installation**, **User Guide**, **Developer Guide**, **API Reference** (section 4).

---

## 6. Console entry points

### 6.1 Authoritative packaging surface: `pyproject.toml` `[project.scripts]`

**Count: 4** (tracked fact).

| Console script | Target |
| --- | --- |
| `ipfs-datasets-install-provers` | `ipfs_datasets_py.logic.integration.bridges.prover_installer:main` |
| `ipfs-datasets-sms-bridge` | `ipfs_datasets_py.messaging.sms_bridge:main` |
| `ipfs-netherlands-laws` | `ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.cli:main` |
| `netherlands-laws` | `ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.cli:main` |

`gui-scripts`: 0. No additional `[project.entry-points]` groups.

Installed egg-info (`ipfs_datasets_py.egg-info/entry_points.txt`) matches these four scripts.

### 6.2 Legacy / alternate surface: `setup.py` `console_scripts`

**Count: 8** declared (tracked fact). Superset of pyproject scripts; **not all appear in `pyproject.toml`**.

| Console script | Target | In `pyproject.toml`? |
| --- | --- | --- |
| `ipfs-datasets` | `ipfs_datasets_cli:cli_main` | no |
| `ipfs-datasets-cli` | `ipfs_datasets_cli:cli_main` | no |
| `netherlands-laws` | `…netherlands_laws.cli:main` | yes |
| `ipfs-netherlands-laws` | `…netherlands_laws.cli:main` | yes |
| `ipfs-datasets-sms-bridge` | `…sms_bridge:main` | yes |
| `ipfs-datasets-install-provers` | `…prover_installer:main` | yes |
| `file-converter` | `…file_converter.cli:main` | no |
| `fc` | `…file_converter.cli:main` | no |

### 6.3 Repository CLI wrappers (not setuptools entry points)

| Path | Kind | Notes |
| --- | --- | --- |
| `ipfs-datasets` | shell script | Executable wrapper at repo root |
| `ipfs_datasets_cli.py` | Python CLI module | Large MCP-oriented CLI (`cli_main`) |

**Drift note:** Primary user-facing CLI names (`ipfs-datasets`, `ipfs-datasets-cli`, `file-converter`, `fc`) are declared in `setup.py` but **absent** from `pyproject.toml` `[project.scripts]`. Packaging path determines which install actually exposes them.

---

## 7. Extras (optional dependencies)

**Source:** `pyproject.toml` `[project.optional-dependencies]`.

**Count: 18** extras (tracked fact).

| Extra | Declared dependency entries |
| --- | ---: |
| `all` | 34 |
| `api` | 4 |
| `file_conversion` | 7 |
| `groth16` | 1 |
| `ipld` | 5 |
| `knowledge_graphs` | 9 |
| `lazy` | 20 |
| `legal_netherlands` | 6 |
| `logic` | 2 |
| `multimedia` | 5 |
| `ocr` | 3 |
| `profile-f-zk` | 1 |
| `provekit` | 1 |
| `scraping` | 11 |
| `symai_router` | 3 |
| `test` | 9 |
| `theorem-provers` | 6 |
| `vectors` | 6 |

```bash
python3 -c "import tomllib; from pathlib import Path; d=tomllib.loads(Path('pyproject.toml').read_bytes()); print(sorted((d['project']['optional-dependencies']).keys()))"
```

Related requirement files present (not counted as extras): `requirements.txt`, `requirements-docs.txt`, `requirements-lazy.txt`, `requirements-theorem-provers.txt`.

---

## 8. Submodules

**Declared in `.gitmodules`: 10** (tracked fact).  
**`git submodule status`: 10** entries; all prefixes show `-` (registered, **not checked out / empty working directories** in this worktree).

| Path | URL | Branch | Recorded commit (status) | Populated? |
| --- | --- | --- | --- | --- |
| `ipfs_kit_py` | `https://github.com/endomorphosis/ipfs_kit_py.git` | main | `f6a574375febbcf9a46fcd24bbc7bc5cfb551de5` | no (0 children) |
| `.tools/ipfs_kit_py` | `https://github.com/endomorphosis/ipfs_kit_py.git` | main | `f6a574375febbcf9a46fcd24bbc7bc5cfb551de5` | no |
| `ipfs_accelerate_py` | `https://github.com/endomorphosis/ipfs_accelerate_py.git` | main | `ba5ff24ad7ca2fc158369337f481c16433b50a41` | no |
| `ipfs_datasets_py/logic/CEC/DCEC_Library` | `https://github.com/endomorphosis/DCEC_Library.git` | master | `a4beb5b3280595be6b9221cac3c91dd019e6d371` | no |
| `ipfs_datasets_py/logic/CEC/Talos` | `https://github.com/endomorphosis/Talos.git` | master | `e0b7650d3e3a403924773f8253e924c719748d36` | no |
| `ipfs_datasets_py/logic/CEC/Eng-DCEC` | `https://github.com/endomorphosis/Eng-DCEC.git` | master | `df518c21ef81b8001e6db59f5fd70f10cc04ff6c` | no |
| `ipfs_datasets_py/logic/CEC/ShadowProver` | `https://github.com/endomorphosis/ShadowProver.git` | master | `3060ede1ac1ec3f8ef9f9c9e41386aed1dbbe7f9` | no |
| `ipfs_datasets_py/multimedia/convert_to_txt_based_on_mime_type` | `https://github.com/endomorphosis/convert_to_txt_based_on_mime_type.git` | main | `d58933631a5362b1e2fdc45254ef620fa231223a` | no |
| `ipfs_datasets_py/multimedia/omni_converter_mk2` | `https://github.com/endomorphosis/omni_converter_mk2.git` | main | `c1d9b0d517cea022516aab5b5d8fa5e3bc9a65aa` | no |
| `ipfs_datasets_py/processors/web_archiving/common_crawl_search_engine` | `https://github.com/endomorphosis/common_crawl_search_engine.git` | main | `5c7c2ab8a509073f39359b2a35446183855f460a` | no |

```bash
git config -f .gitmodules --get-regexp path
git submodule status
```

**Implication:** Package-domain empty dirs such as `multimedia/` and empty install trees for CEC / converters are expected until submodules are initialized. Documentation that claims submodule-backed features should treat this worktree as **submodule-empty**.

---

## 9. Generated and package-local documentation

### 9.1 Package-local Markdown

| Location / pattern | Count | Kind |
| --- | ---: | --- |
| All `ipfs_datasets_py/**/*.md` | 387 | Tracked fact |
| `README.md` under package | 128 | Tracked fact |
| `*_stubs.md` under package | 45 | Tracked fact |
| `ipfs_datasets_py/mcp_server/docs/` | 47 md / 48 files | Tracked fact |
| `ipfs_datasets_py/logic/docs/` | 2 md | Tracked fact |
| `ipfs_datasets_py/processors/legal_scrapers/netherlands_laws/docs/` | 1 md | Tracked fact |
| `ipfs_datasets_py/processors/legal_scrapers/legal_corpus/docs/` | 1 md | Tracked fact |

Package Markdown concentration (top): `mcp_server` 176, `processors` 95, `audit` 26, `logic` 20, `ml` 17, `knowledge_graphs` 15, `vector_stores` 12.

### 9.2 Package-local HTML / templates

| Metric | Count | Kind |
| --- | ---: | --- |
| `ipfs_datasets_py/**/*.html` | 48 | Tracked fact |
| `ipfs_datasets_py/**/*.rst` | 0 | Tracked fact |

Primarily dashboard/template HTML under `templates/` and related paths (runtime UI, not MkDocs output).

### 9.3 Generated / stub documentation under `docs/`

| Path / pattern | Count | Kind | Notes |
| --- | ---: | --- | --- |
| `docs/auto_generated_stubs/` files | 1 | Tracked fact | Explicit auto-generated stub area |
| `docs/archived_stubs/` files | 124 | Tracked fact | Archived stub surface |
| Paths under `docs` matching `*stub*` | 132 | Tracked fact | Includes archived + other stub-named files |
| `docs/tdfol/_build/` files | 202 | Tracked fact | Sphinx build products committed |
| Tracked `*.doctree` (repo) | 40 | Tracked fact | Sphinx intermediate artifacts |
| `docs/**/*.html` tracked | 70 | Tracked fact | Includes Sphinx/HTML artifacts |
| `docs/**/*.rst` tracked | 40 | Tracked fact | Sphinx sources/products |

Sphinx config present: `docs/tdfol/conf.py`. `requirements-docs.txt` targets Sphinx (not MkDocs).

### 9.4 MkDocs generated site

| Metric | Value | Kind |
| --- | --- | --- |
| `site/` build directory | absent | Tracked fact |
| MkDocs config | present (`mkdocs.yml`) | Tracked fact |

---

## 10. Summary table (acceptance fields)

| Acceptance field | Value | Kind |
| --- | --- | --- |
| Current commit | `e5641d78761a8138352cbb06720468a129a591b3` | Tracked fact |
| Python (tracked `*.py`) | 6838 | Tracked fact |
| Package Python (tracked under `ipfs_datasets_py/`) | 3005 | Tracked fact |
| Test Python (`tests/`) | 3005 | Tracked fact |
| Docs Markdown (`docs/**/*.md`) | 1476 | Tracked fact |
| Markdown (tracked repo-wide) | 2212 | Tracked fact |
| Root-page count | 117 | Tracked fact |
| Navigated-page count (MkDocs nav leaves) | 7 | Derived fact |
| Top-level package domains | 39 directories | Tracked fact |
| Top-level docs domains | 30 directories (+ 117 root pages) | Tracked fact |
| Console entry points (`pyproject.toml`) | 4 | Tracked fact |
| Console entry points (`setup.py`) | 8 | Tracked fact |
| Extras | 18 | Tracked fact |
| Submodules | 10 declared; 0 populated in this worktree | Tracked fact |
| Package-local Markdown | 387 | Tracked fact |
| Generated/stub-oriented docs | see §9 | Tracked fact |

### Explicit non-authoritative claims (do not copy)

These appear in existing docs/README marketing language and are **not** used as baseline authority:

| Claim source (examples) | Claim | Baseline stance |
| --- | --- | --- |
| README badge | “4500+ tests” | Superseded by measured file inventory; case count not measured |
| README narrative | “790+ tests”, “174 tests”, “418+ tests”, “305+ tests” in feature bullets | Historical/marketing; not re-validated here |
| Any prior plan/status Markdown counts | various | Ignored; re-measured |

---

## 11. Reproducible commands

Run from the repository root on a clean worktree at the recorded commit.

### 11.1 Identity and cleanliness

```bash
git rev-parse HEAD
git log -1 --format='%H %ci %s'
git status --porcelain
git branch --show-current
date -u +%Y-%m-%dT%H:%M:%SZ
python3 --version
```

### 11.2 Tracked inventory

```bash
git ls-files | wc -l
git ls-files '*.py' | wc -l
git ls-files '*.md' | wc -l
git ls-files | sed 's/.*\.//' | sort | uniq -c | sort -rn | head -25

for p in ipfs_datasets_py tests docs scripts examples benchmarks archive; do
  printf '%s files=%s py=%s md=%s\n' "$p" \
    "$(git ls-files "$p" | wc -l)" \
    "$(git ls-files "$p" | grep -c '\.py$' || true)" \
    "$(git ls-files "$p" | grep -c '\.md$' || true)"
done
```

### 11.3 Package / test filesystem counts

```bash
find ipfs_datasets_py -name '*.py' -not -path '*/__pycache__/*' | wc -l
find tests -name '*.py' -not -path '*/__pycache__/*' | wc -l
find tests -name 'test_*.py' -not -path '*/__pycache__/*' | wc -l
find tests -name '*_test.py' -not -path '*/__pycache__/*' | wc -l
find tests -name '*.feature' | wc -l
find docs -name '*.md' | wc -l
find docs -maxdepth 1 -name '*.md' | wc -l
find ipfs_datasets_py -name '*.md' | wc -l
find ipfs_datasets_py -name '__init__.py' | wc -l
```

### 11.4 MkDocs navigated pages

```bash
python3 <<'PY'
from pathlib import Path
import yaml
data = yaml.safe_load(Path('mkdocs.yml').read_text())
pages = []
def walk(items):
    for item in items or []:
        if isinstance(item, str):
            pages.append(item)
        elif isinstance(item, dict):
            for v in item.values():
                if isinstance(v, str):
                    pages.append(v)
                elif isinstance(v, list):
                    walk(v)
walk(data.get('nav'))
print('top_level', len(data.get('nav') or []))
print('navigated_pages', len(pages))
print('unique', len(set(pages)))
for p in pages:
    print(p, 'OK' if (Path('docs')/p).exists() else 'MISSING')
PY
```

### 11.5 Top-level domains

```bash
# package domains
python3 -c "from pathlib import Path; p=Path('ipfs_datasets_py'); print(sorted(x.name for x in p.iterdir() if x.is_dir() and not x.name.startswith('.') and x.name!='__pycache__'))"
# docs domains
python3 -c "from pathlib import Path; p=Path('docs'); print(sorted(x.name for x in p.iterdir() if x.is_dir() and not x.name.startswith('.')))"
```

### 11.6 Console scripts and extras

```bash
python3 <<'PY'
from pathlib import Path
try:
    import tomllib
except ImportError:
    import tomli as tomllib
data = tomllib.loads(Path('pyproject.toml').read_bytes())
scripts = data['project'].get('scripts') or {}
extras = data['project'].get('optional-dependencies') or {}
print('scripts', len(scripts))
for k,v in sorted(scripts.items()):
    print(f'  {k} = {v}')
print('extras', len(extras))
for k in sorted(extras):
    print(f'  {k}: {len(extras[k])}')
PY
# setup.py entry points (legacy)
rg -n "console_scripts" -A20 setup.py | head -40
```

### 11.7 Submodules

```bash
cat .gitmodules
git submodule status
for d in ipfs_kit_py ipfs_accelerate_py \
  ipfs_datasets_py/logic/CEC/DCEC_Library \
  ipfs_datasets_py/logic/CEC/Talos \
  ipfs_datasets_py/logic/CEC/Eng-DCEC \
  ipfs_datasets_py/logic/CEC/ShadowProver \
  ipfs_datasets_py/multimedia/convert_to_txt_based_on_mime_type \
  ipfs_datasets_py/multimedia/omni_converter_mk2 \
  ipfs_datasets_py/processors/web_archiving/common_crawl_search_engine \
  .tools/ipfs_kit_py; do
  printf '%s children=%s\n' "$d" "$(find "$d" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l)"
done
```

### 11.8 Generated / package-local docs

```bash
find ipfs_datasets_py -name '*.md' | wc -l
find ipfs_datasets_py -name 'README.md' | wc -l
find ipfs_datasets_py -name '*_stubs.md' | wc -l
find ipfs_datasets_py -name '*.html' | wc -l
find ipfs_datasets_py -type d -name docs
find docs/tdfol/_build -type f 2>/dev/null | wc -l
find docs/archived_stubs -type f 2>/dev/null | wc -l
find docs/auto_generated_stubs -type f 2>/dev/null | wc -l
test -d site && echo site_present || echo site_absent
```

### 11.9 Validation for this task output

```bash
test -s docs/maintenance/CURRENT_STATE_BASELINE.md && rg -n 'commit|Markdown|package|test|MkDocs|submodule' docs/maintenance/CURRENT_STATE_BASELINE.md
```

---

## 12. Measurement limitations

1. **Submodules empty** — Any code or docs living only inside submodule commits are invisible to package/file counts here.
2. **No pytest collection** — Test *case* cardinality is not measured; only file-level inventory.
3. **No MkDocs build** — Navigated-page count is from config, not from a built `site/` graph or link checker.
4. **Dynamic dependencies** — Runtime dependency cardinality is not expanded from dynamic resolution.
5. **Dual packaging config** — `setup.py` and `pyproject.toml` disagree on console scripts; install path matters.
6. **Estimates** — “Docs not in nav” and “pytest-collectable by name” are labeled estimates and must not be promoted to tracked facts without re-measurement under a stricter definition.

---

## 13. Checkpoint metadata

| Field | Value |
| --- | --- |
| Checkpoint directory | `$IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR` → `…/implementation_checkpoints/ipfsdoc-001-8d786d6559c9` |
| Output path | `docs/maintenance/CURRENT_STATE_BASELINE.md` |
| Protected inputs (read-only) | `docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH_PLAN_2026_08_03.md`, `…REFRESH.objectives.md`, `…REFRESH.todo.md` |

End of baseline.
