# MCP Server Tools — Comprehensive Improvement Plan 2026

**Date:** 2026-02-20  
**Scope:** `ipfs_datasets_py/mcp_server/tools/` and all subfolders  
**Status:** 🟢 Phase A ✅ · Phase B ✅ · Phase C ✅ · Phase D ✅ Complete  

---

## Executive Summary

The `tools/` directory contains **344 Python tool files** across **51 categories**, exposing the full
functionality of IPFS Datasets Python through the Model Context Protocol. A review of the markdown
documentation in this directory reveals a significant structural gap: only **5 of 51 categories** have
any documentation at all, and several of those contain historical implementation notes rather than
user-facing references. This plan defines three improvement phases to close that gap.

**Baseline (2026-02-20):**

| Metric | Value |
|--------|-------|
| Tool categories | 51 |
| Python tool files | 344 |
| Categories with ≥1 markdown file | 5 (bespoke_tools, finance_data_tools, legal_dataset_tools, software_engineering_tools, vector_tools) |
| Categories with 0 documentation | 44 |
| Total markdown files in tools/ | 33 |
| Historical/internal-only docs | ~14 (in legal_dataset_tools) |
| Stub-only docs (bespoke_tools) | 2 |

---

## Table of Contents

1. [Current State Analysis](#1-current-state-analysis)
2. [Documentation Issues Found](#2-documentation-issues-found)
3. [Phase A: Documentation Triage & Cleanup](#3-phase-a-documentation-triage--cleanup)
4. [Phase B: Core Category Documentation](#4-phase-b-core-category-documentation)
5. [Phase C: Full Coverage & Advanced Guides](#5-phase-c-full-coverage--advanced-guides)
6. [Code Quality Findings](#6-code-quality-findings)
7. [Phase D: Code Quality Improvements](#7-phase-d-code-quality-improvements)
8. [Success Metrics](#8-success-metrics)
9. [Priority Matrix](#9-priority-matrix)

---

## 1. Current State Analysis

### 1.1 Category Inventory

| Category | Python Files | Markdown Files | Notes |
|----------|-------------|----------------|-------|
| `admin_tools` | 2 | 0 | Enhanced admin tools — no docs (Phase C) |
| `alert_tools` | 1 | 0 | Discord alert tools — no docs (Phase C) |
| `analysis_tools` | 1 | 0 | No docs (Phase C) |
| `audit_tools` | 3 | 0 | No docs (Phase C) |
| `auth_tools` | 2 | 0 | Enhanced auth — no docs (Phase C) |
| `background_task_tools` | 3 | 0 | No docs (Phase C) |
| `bespoke_tools` | 7 | 1 | ✅ README.md created (Phase A) |
| `cache_tools` | 2 | 0 | No docs (Phase C) |
| `cli` | 2 | 0 | No docs (Phase C) |
| `dashboard_tools` | 3 | 0 | No docs (Phase C) |
| `data_processing_tools` | 1 | 0 | No docs (Phase C) |
| `dataset_tools` | 7 | 1 | ✅ README.md created (Phase B) |
| `development_tools` | 19 | 1 | ✅ README.md created (Phase B) |
| `discord_tools` | 4 | 0 | No docs (Phase C) |
| `email_tools` | 3 | 0 | No docs (Phase C) |
| `embedding_tools` | 9 | 1 | ✅ README.md created (Phase B) |
| `file_converter_tools` | 8 | 0 | No docs (Phase C) |
| `file_detection_tools` | 3 | 0 | No docs (Phase C) |
| `finance_data_tools` | 6 | 3 | ✅ README updated + 2 analysis docs |
| `functions` | 1 | 0 | No docs (Phase C) |
| `geospatial_tools` | 1 | 0 | No docs (Phase C) |
| `graph_tools` | 11 | 1 | ✅ README.md created (Phase B) |
| `index_management_tools` | 1 | 0 | No docs (Phase C) |
| `investigation_tools` | 7 | 0 | No docs (Phase C) |
| `ipfs_cluster_tools` | 1 | 0 | No docs (Phase C) |
| `ipfs_tools` | 3 | 1 | ✅ README.md created (Phase B) |
| `legacy_mcp_tools` | 32 | 1 | ✅ MIGRATION_GUIDE.md created (Phase B) |
| `legal_dataset_tools` | 38 | 8 | ✅ Phase A cleanup: 7 historical docs archived, statuses fixed |
| `lizardperson_argparse_programs` | 0 | 11 | Legacy program — legacy notice added (Phase A) |
| `lizardpersons_function_tools` | 0 | 0 | Empty category |
| `logic_tools` | 12 | 1 | ✅ README.md created (Phase B) |
| `mcplusplus` | 3 | 0 | No docs (Phase C) |
| `media_tools` | 9 | 1 | ✅ README.md created (Phase B) |
| `medical_research_scrapers` | 6 | 0 | No docs (Phase C) |
| `monitoring_tools` | 2 | 0 | No docs (Phase C) |
| `p2p_tools` | 2 | 0 | No docs (Phase C) |
| `p2p_workflow_tools` | 1 | 0 | No docs (Phase C) |
| `pdf_tools` | 8 | 1 | ✅ README.md created (Phase B) |
| `provenance_tools` | 2 | 0 | No docs (Phase C) |
| `rate_limiting_tools` | 1 | 0 | No docs (Phase C) |
| `search_tools` | 1 | 0 | No docs (Phase C) |
| `security_tools` | 1 | 0 | No docs (Phase C) |
| `session_tools` | 3 | 0 | No docs (Phase C) |
| `software_engineering_tools` | 11 | 1 | ✅ Has README (good) |
| `sparse_embedding_tools` | 1 | 0 | No docs (Phase C) |
| `storage_tools` | 2 | 0 | No docs (Phase C) |
| `vector_store_tools` | 3 | 0 | No docs (Phase C) |
| `vector_tools` | 6 | 1 | Has CHANGELOG only (needs README in Phase C) |
| `web_archive_tools` | 18 | 1 | ✅ README.md created (Phase B) |
| `web_scraping_tools` | 1 | 0 | No docs (Phase C) |
| `workflow_tools` | 2 | 0 | No docs (Phase C) |

### 1.2 Documentation Quality Assessment

| Category | Issue |
|----------|-------|
| `bespoke_tools/__init__.md` | Auto-generated stub; not a real README |
| `bespoke_tools/cache_stats.md` | Auto-generated stub; not a real README |
| `legal_dataset_tools/` | 14 historical/internal docs clutter the directory (completion reports, fix summaries, test summaries) |
| `finance_data_tools/README.md` | Status fields partially outdated ("🔄 In Progress" for Yahoo Finance integration that may be complete) |
| `finance_data_tools/EMBEDDING_CORRELATION.md` | Analysis document, not a developer guide |
| `finance_data_tools/GRAPHRAG_ANALYSIS.md` | Analysis document, not a developer guide |
| `vector_tools/CHANGELOG.md` | CHANGELOG with one entry from 2025-07-04; not a README |
| `software_engineering_tools/README.md` | Good content; complete and accurate |
| `lizardperson_argparse_programs/` | 11 markdown files for a legacy argparse program whose MCP shim is `legal_dataset_tools/bluebook_citation_validator_tool.py` |

---

## 2. Documentation Issues Found

### Issue 1: 44 of 51 categories have zero documentation

The overwhelming majority of tool categories have no README or reference documentation. This makes it
difficult for contributors to:
- Understand what tools are in each category
- Know the calling conventions and expected parameters
- Understand which dependencies are required
- Know the current implementation status

### Issue 2: `legal_dataset_tools/` is over-documented with implementation history

The directory contains 15 markdown files, but only `README.md` is user-facing. The other 14 are
historical implementation notes (completion reports, fix summaries, testing summaries, validation
reports) that belong in an `ARCHIVE/` subfolder.

**Files to archive from `legal_dataset_tools/`:**
- `COMPLETION_REPORT.md` — implementation history
- `IMPLEMENTATION_SUMMARY.md` — implementation history
- `SCRAPER_FIXES_SUMMARY.md` — implementation history
- `TESTING_IMPLEMENTATION_SUMMARY.md` — implementation history
- `TEST_RESULTS_REPORT.md` — testing history
- `VALIDATION_REPORT.md` — testing history
- `VERIFICATION_README.md` — testing history

**Files to keep in `legal_dataset_tools/` (useful guides):**
- `README.md` — primary reference (needs status update)
- `COURTLISTENER_API_GUIDE.md` — useful API reference
- `CRON_SETUP_GUIDE.md` — useful operational guide
- `CRON_SETUP_SIMPLE.md` — useful quick reference
- `PLAYWRIGHT_SETUP.md` — useful setup guide
- `PRIORITY2_CUSTOM_SCRAPERS.md` — useful roadmap
- `MUNICODE_SCRAPER_MVP.md` — useful architecture doc
- `TESTING_GUIDE.md` — useful testing guide

### Issue 3: `lizardperson_argparse_programs/` documentation is misplaced

This directory contains 11 markdown files documenting a legacy argparse-based command-line program
(the Bluebook Citation Validator). The actual MCP tool wrapper is at
`legal_dataset_tools/bluebook_citation_validator_tool.py`, and the core package has been moved to
`ipfs_datasets_py/processors/legal_scrapers/bluebook_citation_validator/`.

The `lizardperson_argparse_programs/` docs are legacy program documentation; a pointer should be
added noting that the core package has moved.

### Issue 4: `bespoke_tools/` has stub-only auto-generated docs

The `__init__.md` and `cache_stats.md` files are auto-generated stubs (not real documentation).
They should be replaced with proper README content.

### Issue 5: `vector_tools/` has only a CHANGELOG

A CHANGELOG entry from one session (2025-07-04) is not a substitute for a category README.

### Issue 6: The `tools/` top-level directory has no index

There is no `tools/README.md` to help contributors navigate 51 categories.

---

## 3. Phase A: Documentation Triage & Cleanup ✅ COMPLETE

**Goal:** Clean up the existing documentation before adding new material.  
**Estimated effort:** 2-3h  
**Priority:** 🔴 High  
**Status:** ✅ Complete (2026-02-20)

### A1: Archive Historical `legal_dataset_tools/` Docs ✅

Created `legal_dataset_tools/ARCHIVE/` and moved 7 historical implementation notes:
`COMPLETION_REPORT.md`, `IMPLEMENTATION_SUMMARY.md`, `SCRAPER_FIXES_SUMMARY.md`,
`TESTING_IMPLEMENTATION_SUMMARY.md`, `TEST_RESULTS_REPORT.md`, `VALIDATION_REPORT.md`,
`VERIFICATION_README.md`.

**Result:** 15 → 8 root markdown files (47% reduction)

### A2: Update `legal_dataset_tools/README.md` Status ✅

Fixed stale status fields: Federal Register and State Laws now correctly marked ✅ Production Ready.
Added `ARCHIVE/` pointer notice at the top. Consistent status format across all scrapers.

### A3: Replace `bespoke_tools/` Stub Docs ✅

Removed auto-generated `__init__.md` and `cache_stats.md`. Created proper `README.md` for the
category with tool table, usage examples, and dependency notes.

### A4: Add `lizardperson_argparse_programs/` Pointer ✅

Added legacy location notice at the top of `SAD_mk1.md` pointing to current core package
(`processors/legal_scrapers/bluebook_citation_validator/`) and MCP wrapper location.

### A5: Create `tools/README.md` Navigation Index ✅

Created top-level `tools/README.md` with all 51 categories organised by functional grouping.

---

## 4. Phase B: Core Category Documentation ✅ COMPLETE

## 4. Phase B: Core Category Documentation ✅ COMPLETE

**Goal:** Add README files for the 10 highest-priority undocumented categories.  
**Estimated effort:** 6-8h  
**Priority:** 🔴 High  
**Status:** ✅ Complete (2026-02-20)

Priority is determined by:
1. Number of Python tool files (larger = more important to document)
2. Likelihood of being used by external consumers
3. Core vs. peripheral functionality

### Results — All 10 Phase B Items Delivered

| # | Category | Files | README Created | Migration Guide |
|---|----------|-------|----------------|-----------------|
| 1 | `dataset_tools` | 7 | ✅ `dataset_tools/README.md` | — |
| 2 | `ipfs_tools` | 3 | ✅ `ipfs_tools/README.md` | — |
| 3 | `graph_tools` | 11 | ✅ `graph_tools/README.md` | — |
| 4 | `embedding_tools` | 9 | ✅ `embedding_tools/README.md` | — |
| 5 | `logic_tools` | 12 | ✅ `logic_tools/README.md` | — |
| 6 | `web_archive_tools` | 18 | ✅ `web_archive_tools/README.md` | — |
| 7 | `media_tools` | 9 | ✅ `media_tools/README.md` | — |
| 8 | `pdf_tools` | 8 | ✅ `pdf_tools/README.md` | — |
| 9 | `development_tools` | 19 | ✅ `development_tools/README.md` | — |
| 10 | `legacy_mcp_tools` | 32 | — | ✅ `legacy_mcp_tools/MIGRATION_GUIDE.md` |

Each README includes:
- Full tool inventory table (file → function(s) → description)
- Code examples for the 3-5 most common use cases
- Core module references (which `ipfs_datasets_py.*` module each tool wraps)
- Dependency table (required vs optional with graceful-degradation notes)
- Per-tool production status table

### README Template for Each Category

```markdown
# [Category Name]

[One-paragraph description of what this category provides.]

## Tools

| Tool | Function | Description |
|------|----------|-------------|
| `tool_name.py` | `function_name()` | Brief description |

## Usage

[Code example showing the most common use case]

## Dependencies

[Required and optional dependencies]

## Status

[Production-ready / Partial / Placeholder]
```

---

## 5. Phase C: Full Coverage & Advanced Guides ✅ COMPLETE

**Goal:** Document all 44 undocumented categories; add advanced guides.  
**Estimated effort:** 15-20h  
**Priority:** 🟡 Medium  
**Status:** ✅ Complete (2026-02-20)

### C1: All 34 Remaining Undocumented Categories — READMEs Created ✅

**Group 1 — Functional tools (3-5 files each):**

| Category | README | Highlights |
|----------|--------|-----------|
| `audit_tools` | ✅ | record_audit_event, generate_audit_report, query_audit_log |
| `auth_tools` | ✅ | validate_token, check_permission, create_user, enhanced auth |
| `background_task_tools` | ✅ | create_task, poll_status, cancel, BackgroundTaskEngine |
| `cache_tools` | ✅ | get/set/clear cache, namespaces, hit rate |
| `file_converter_tools` | ✅ | convert_file, batch_convert, extract_kg, generate_summary |
| `file_detection_tools` | ✅ | detect_file_type, batch_detect, analyze_accuracy |
| `monitoring_tools` | ✅ | get_system_metrics, check_health, alert thresholds |
| `provenance_tools` | ✅ | record_provenance, query lineage |
| `search_tools` | ✅ | keyword_search, semantic_search, hybrid_search |
| `session_tools` | ✅ | create_session, validate_session, SessionEngine |
| `storage_tools` | ✅ | store/retrieve/list across s3/local/ipfs, StorageEngine |
| `vector_store_tools` | ✅ | upsert, search, filtered_search, VectorStoreEngine |
| `workflow_tools` | ✅ | execute_workflow, batch_process, create_pipeline |

**Group 2 — Specialised tools (1-2 files each):**

| Category | README | Highlights |
|----------|--------|-----------|
| `admin_tools` | ✅ | system_health, manage_endpoints, enhanced admin |
| `alert_tools` | ✅ | send_discord_message, create_alert_rule |
| `analysis_tools` | ✅ | analyze_data, generate_statistics, pattern detection |
| `cli` | ✅ | execute_command, medical_research_cli |
| `dashboard_tools` | ✅ | TDFOL performance dashboard, JS error reporter |
| `data_processing_tools` | ✅ | chunk_text, deduplicate, transform_data |
| `discord_tools` | ✅ | export/list/convert/analyze Discord data |
| `email_tools` | ✅ | IMAP/POP3 connect, export emails, analyze inbox |
| `functions` | ✅ | execute_python_snippet (sandboxed) |
| `geospatial_tools` | ✅ | geocode_address, calculate_distance, spatial_query |
| `index_management_tools` | ✅ | create/delete/list/rebuild indices |
| `ipfs_cluster_tools` | ✅ | cluster_pin, cluster_status, list_cluster_peers |
| `p2p_tools` | ✅ | p2p_status, list_peers, workflow_scheduler |
| `p2p_workflow_tools` | ✅ | submit/track/cancel P2P workflows |
| `rate_limiting_tools` | ✅ | check_rate_limit, consume_token, quota status |
| `security_tools` | ✅ | check_access_permission |
| `sparse_embedding_tools` | ✅ | BM25/TF-IDF, hybrid sparse-dense search |
| `web_scraping_tools` | ✅ | unified scraper with auto-fallback strategy |

**Group 3 — P2P/MCP++ tools:**

| Category | README | Highlights |
|----------|--------|-----------|
| `mcplusplus` | ✅ | TaskQueueEngine, PeerEngine, WorkflowEngine (architecture diagram) |

**Group 4 — Specialised scrapers:**

| Category | README | Highlights |
|----------|--------|-----------|
| `investigation_tools` | ✅ | ingest news/web, entity analysis, geospatial, deontic reasoning |
| `medical_research_scrapers` | ✅ | PubMed, ClinicalTrials.gov, biomolecules, AI dataset builder |

**vector_tools (had CHANGELOG only → now has README):** ✅

### C2: Cross-Cutting Guides

See [`../../docs/development/README.md`](../../docs/development/README.md) for:
- Tool development guide (thin wrapper pattern)
- Testing guide for tools
- Debugging guide

---

## 6. Code Quality Findings

During the documentation review, several code quality issues were observed in the tool files.

### 6.1 Thick Tool Files (>500 lines — exceed thin-wrapper target)

These files contain business logic that should be extracted to engine modules:

| File | Lines | Issue |
|------|-------|-------|
| `development_tools/github_cli_server_tools.py` | 765 | Mixed business logic and MCP wrappers |
| `legacy_mcp_tools/temporal_deontic_logic_tools.py` | 717 | All-in-one tool file |
| `legacy_mcp_tools/legal_dataset_mcp_tools.py` | 702 | Duplicate of legal_dataset_tools? |
| `monitoring_tools/enhanced_monitoring_tools.py` | 670 | Complex monitoring logic inlined |
| `legacy_mcp_tools/geospatial_tools.py` | 667 | Superseded by geospatial_tools/? |
| `monitoring_tools/monitoring_tools.py` | 663 | Large monitoring file |
| `web_archive_tools/brave_search.py` | 653 | Complex search logic inlined |
| `finance_data_tools/news_scrapers.py` | 650 | Scraper logic inlined |
| `development_tools/claude_cli_server_tools.py` | 631 | CLI wrapper logic inlined |
| `finance_data_tools/stock_scrapers.py` | 590 | Scraper logic inlined |

### 6.2 Duplicate/Legacy Category Issue

`legacy_mcp_tools/` contains 32 Python files — including apparent duplicates of tools in
newer categories (`legal_dataset_mcp_tools.py` vs `legal_dataset_tools/`, `geospatial_tools.py`
vs `geospatial_tools/`, `vector_store_tools.py` vs `vector_store_tools/`).

**Action needed:** Audit `legacy_mcp_tools/` to identify:
1. Which files are true legacy (superseded by a category) → add deprecation markers
2. Which files are still the canonical source → migrate into proper category directories

### 6.3 Missing `__init__.py` Documentation in Categories

Many `__init__.py` files are empty or have minimal module docstrings. All should have:
- Module-level docstring explaining the category
- `__all__` listing public tool functions
- Lazy-import note (as established by the tools root `__init__.py`)

### 6.4 Test Gaps

From `tests/` analysis, only these categories have active test files:
- `audit_tools` (via `tests/_test_admin_tools.py`)  
- `analysis_tools`, `auth_tools`, `background_task_tools`, `cache_tools`,
  `embedding_tools`, `vector_store_tools`, `vector_tools`, `workflow_tools`
  (via `tests/_test_*.py` files — note: prefixed with `_`, likely disabled)
- `finance_data_tools` (via `tests/finance_dashboard/test_finance_data_tools.py`)

**The `_test_*.py` convention** (underscore prefix = disabled from collection) means many test
files exist but are not actually run. These should be reviewed and either activated or removed.

---

## 7. Phase D: Code Quality Improvements ✅ Complete

**Goal:** Address code quality issues that affect maintainability.  
**Estimated effort:** 10-14h  
**Priority:** 🟡 Medium  
**Status:** ✅ Complete (D1 ✅ D2 ✅ D3 ✅ D4 ✅ D5 ✅)

### D1: Audit `legacy_mcp_tools/` — ✅ Complete

Migration guide created (Phase B) mapping all 32 files → new categories.

`DeprecationWarning` added to **all 32** superseded legacy files (including the 28 files
updated in this session):

| Files updated this session (28) |
|----------------------------------|
| `admin_tools.py` → `admin_tools/` |
| `analysis_tools.py` → `analysis_tools/` |
| `authentication_tools.py` → `auth_tools/` |
| `automated_pr_review_tools.py` → `development_tools/automated_pr_review_tools.py` |
| `background_task_tools.py` → `background_task_tools/` |
| `cache_tools.py` → `cache_tools/` |
| `claude_cli_tools.py` → `development_tools/claude_cli_tools.py` |
| `copilot_cli_tools.py` → `development_tools/copilot_cli_tools.py` |
| `create_embeddings_tool.py` → `embedding_tools/embedding_generation.py` |
| `data_processing_tools.py` → `data_processing_tools/` |
| `gemini_cli_tools.py` → `development_tools/gemini_cli_tools.py` |
| `github_cli_tools.py` → `development_tools/github_cli_tools.py` |
| `index_management_tools.py` → `index_management_tools/` |
| `ipfs_cluster_tools.py` → `ipfs_cluster_tools/` |
| `legal_dataset_mcp_tools.py` → `legal_dataset_tools/` |
| `monitoring_tools.py` → `monitoring_tools/` |
| `municipal_scraper_fallbacks.py` → `legal_dataset_tools/municipal_scraper_fallbacks.py` |
| `patent_dataset_mcp_tools.py` → `legal_dataset_tools/patent_dataset_mcp_tools.py` |
| `patent_scraper.py` → `legal_dataset_tools/` |
| `rate_limiting_tools.py` → `rate_limiting_tools/` |
| `session_management_tools.py` → `session_tools/` |
| `shard_embeddings_tool.py` → `embedding_tools/shard_embeddings_tool.py` |
| `sparse_embedding_tools.py` → `sparse_embedding_tools/` |
| `storage_tools.py` → `storage_tools/` |
| `temporal_deontic_logic_tools.py` → `logic_tools/temporal_deontic_logic_tools.py` |
| `tool_wrapper.py` → `tool_wrapper.py` |
| `vscode_cli_tools.py` → `development_tools/vscode_cli_tools.py` |
| `workflow_tools.py` → `workflow_tools/` |

Plus the 4 files updated in the previous session:
- `embedding_tools.py` → `embedding_tools/`
- `vector_store_tools.py` → `vector_store_tools/`
- `geospatial_tools.py` → `geospatial_tools/`
- `search_tools.py` → `search_tools/`

**Result:** 100% of legacy tool files (32/32) now emit `DeprecationWarning` on import.

### D2: Extract Business Logic from 5 Thickest Tool Files — ✅ Complete

**Action taken:** Domain/business logic classes (data models, scraper engines, service
classes) extracted into dedicated `*_engine.py` modules.  All public symbols are
re-exported from the original files so existing import paths are unchanged.

| Original File | Lines Before | Lines After | Engine File Created | Engine Lines |
|---------------|-------------|-------------|---------------------|--------------|
| `finance_data_tools/stock_scrapers.py` | 590 | **227** | `stock_scraper_engine.py` | 355 |
| `finance_data_tools/news_scrapers.py` | 650 | **242** | `news_scraper_engine.py` | 370 |
| `monitoring_tools/enhanced_monitoring_tools.py` | 670 | **397** | `monitoring_engine.py` | 310 |
| `web_archive_tools/brave_search.py` | 653 | **468** | `brave_search_engine.py` | 225 |
| `development_tools/github_cli_server_tools.py` | 765 | **735** | *(helper only, engine already in `utils/`)* | — |

**Engine files created:**
- `stock_scraper_engine.py`: `StockDataPoint`, `CorporateAction`, `StockDataScraper`, `YahooFinanceScraper`
- `news_scraper_engine.py`: `NewsArticle`, `NewsScraperBase`, `APNewsScraper`, `ReutersScraper`, `BloombergScraper`
- `monitoring_engine.py`: `HealthStatus`, `AlertSeverity`, `SystemMetrics`, `ServiceMetrics`, `Alert`, `MockMonitoringService`
- `brave_search_engine.py`: `BraveSearchAPI` (queue, config, cache methods)

**github_cli_server_tools.py refactoring:**
- Added `_get_cli_or_error(install_dir)` helper function
- Replaced 12 repeated `GitHubCLI(...)` + `if not cli.is_installed()` blocks with 3-line helper calls

**All 9 existing tests in `test_finance_data_tools.py` pass unchanged (backward compatible).**

### D3: Activate Disabled Tests — ✅ Complete (14 test files, 142 tests)

**Action taken:** The `_test_*.py` files were evaluated for activation. Fourteen files
were created in `tests/mcp/unit/` — either migrated from existing disabled tests or
written from scratch to match the actual tool API (fixing incorrect kwarg names or
missing positional arguments).

**Session 3 additions (5 new files, 41 tests):**

| New Test File | Tools Tested | Tests |
|---------------|-------------|-------|
| `tests/mcp/unit/test_dataset_tools.py` | load_dataset, save_dataset, process_dataset, convert_dataset_format | 9 |
| `tests/mcp/unit/test_ipfs_tools.py` | pin_to_ipfs, get_from_ipfs | 7 |
| `tests/mcp/unit/test_audit_tools.py` | record_audit_event, generate_audit_report | 9 |
| `tests/mcp/unit/test_security_tools.py` | check_access_permission | 6 |
| `tests/mcp/unit/test_session_tools.py` | create_session, manage_session_state, cleanup_sessions | 10 |

**Session 3 fixes (5 tests):**
- `test_auth_tools.py`: removed invalid `auth_method` kwarg from `authenticate_user()` call
- `test_vector_tools.py`: corrected `create_vector_index` to use `vectors=` first arg (was `index_name=`) and `search_vector_index` to use `index_id=` (was `index_name=`) + `filter_metadata=` (was `filter_criteria=`)

| New Test File | Tools Tested | Tests |
|---------------|-------------|-------|
| `tests/mcp/unit/test_admin_tools.py` | manage_endpoints, system_maintenance, configure_system, system_health, system_status | 7 |
| `tests/mcp/unit/test_auth_tools.py` | authenticate_user, validate_token, get_user_info | 5 |
| `tests/mcp/unit/test_vector_tools.py` | create_vector_index, search_vector_index, list_vector_indexes, delete_vector_index | 6 |
| `tests/mcp/unit/test_background_task_tools.py` | check_task_status, manage_background_tasks, manage_task_queue | 13 |
| `tests/mcp/unit/test_workflow_tools.py` | execute_workflow, batch_process_datasets, schedule_workflow, create_workflow, run_workflow, list_workflows | 16 |
| `tests/mcp/unit/test_cache_tools.py` | manage_cache, cache_stats, optimize_cache, cache_embeddings | 13 |
| `tests/mcp/unit/test_monitoring_tools.py` | health_check, get_performance_metrics, monitor_services, generate_monitoring_report | 13 |
| `tests/mcp/unit/test_analysis_tools.py` | perform_clustering_analysis, assess_embedding_quality, reduce_dimensionality, detect_outliers, analyze_diversity, detect_drift | 14 |
| `tests/mcp/unit/test_embedding_tools.py` | generate_embedding, generate_batch_embeddings, generate_embeddings_from_file | 14 |
| `tests/mcp/unit/test_dataset_tools.py` | load_dataset, save_dataset, process_dataset, convert_dataset_format | 9 |
| `tests/mcp/unit/test_ipfs_tools.py` | pin_to_ipfs, get_from_ipfs | 7 |
| `tests/mcp/unit/test_audit_tools.py` | record_audit_event, generate_audit_report | 9 |
| `tests/mcp/unit/test_security_tools.py` | check_access_permission | 6 |
| `tests/mcp/unit/test_session_tools.py` | create_session, manage_session_state, cleanup_sessions | 10 |

**Total: 142 active tests across 14 tool categories (0 failures, 2 skipped).**

Note: `test_cache_tools.py`, `test_monitoring_tools.py`, `test_analysis_tools.py`, and
`test_embedding_tools.py` were written from scratch to match the actual API because the
corresponding `_test_*.py` originals used incorrect function names or response key expectations.

**Remaining disabled files and reasons:**
- `tests/original_tests/_test_cache_tools.py` — superseded by new `test_cache_tools.py` (API fixed)
- `tests/original_tests/_test_analysis_tools.py` — superseded by new `test_analysis_tools.py` (API fixed)
- `tests/original_tests/_test_monitoring_tools.py` — superseded by new `test_monitoring_tools.py` (API fixed)
- `tests/original_tests/_test_embedding_tools.py` — superseded by new `test_embedding_tools.py` (API fixed)
- `tests/original_tests/_test_vector_store_tools.py` — `ipfs_datasets_py.embeddings` module missing
- `tests/original_tests/_test_comprehensive_integration.py`, `_test_test_e2e.py` — complex integration tests
- `tests/migration_tests/_test_*.py` (65 files) — historical migration debugging tests

### D4: Fix `tools/__init__.py` Module Coverage — ✅ Complete

`_TOOL_SUBMODULES` expanded from **17 → 51 categories** (all active categories now listed).
`__all__` simplified to `sorted(_TOOL_SUBMODULES)`.

The lazy-loading pattern is preserved — no eager imports were added.

### D5: Add Module Docstrings to Category `__init__.py` Files — ✅ Complete

All 45 category-level `__init__.py` files now have module docstrings explaining the
category purpose, listing core functions, and noting key dependencies.

**7 files updated in session 3:**

| File | Docstring Added |
|------|----------------|
| `embedding_tools/__init__.py` | Category overview + core function list |
| `legacy_mcp_tools/__init__.py` | Deprecation notice + migration pointer |
| `lizardpersons_function_tools/__init__.py` | Empty-category explanation + pointer to active tool |
| `p2p_tools/__init__.py` | P2P layer description + dependency note |
| `rate_limiting_tools/__init__.py` | Token-bucket description + backend note |
| `sparse_embedding_tools/__init__.py` | BM25/TF-IDF description |
| `storage_tools/__init__.py` | Multi-backend storage description |

---

## 8. Success Metrics

| Metric | Baseline | After Phase A | After Phase B | After Phase C+D |
|--------|---------|----------------|----------------|------------------|
| Categories with README | 3 | 4 ✅ | **15** ✅ | **51** ✅ |
| Historical docs in root dirs | 14 (legal) | 0 ✅ | 0 ✅ | 0 ✅ |
| Thick tools (>500 lines) | 10+ | 10+ | 10+ | **5** ✅ (D2 complete: 4 engines extracted) |
| Disabled test files in `tests/` | ~15 | ~15 | ~15 | **~4** (14 activated) |
| `_TOOL_SUBMODULES` coverage | 17/51 | 17/51 | 17/51 | **51/51** ✅ |
| Top-level `tools/README.md` | ❌ | ✅ | ✅ | ✅ |
| `legacy_mcp_tools/` migration guide | ❌ | ❌ | ✅ | ✅ |
| Deprecation warnings in legacy files | 0 | 0 | 0 | **32/32** ✅ |
| New active tests for tool categories | 0 | 0 | 0 | **142** ✅ |
| Category `__init__.py` with docstrings | 38/45 | 38/45 | 38/45 | **45/45** ✅ |

---

## 9. Priority Matrix

| Phase | Item | Effort | Impact | Priority | Status |
|-------|------|--------|--------|----------|--------|
| A | Archive historical legal docs | 30min | High (clutter reduction) | 🔴 Do first | ✅ Done |
| A | Create `tools/README.md` index | 1h | High (navigation) | 🔴 Do first | ✅ Done |
| A | Update `legal_dataset_tools/README.md` status | 30min | Medium | 🔴 Do first | ✅ Done |
| A | Fix `bespoke_tools/` stub docs | 30min | Low | 🟡 Soon | ✅ Done |
| B | `dataset_tools` README | 1h | Very High (core) | 🔴 High | ✅ Done |
| B | `ipfs_tools` README | 45min | Very High (core) | 🔴 High | ✅ Done |
| B | `graph_tools` README | 1h | High | 🔴 High | ✅ Done |
| B | `embedding_tools` README | 1h | High | 🔴 High | ✅ Done |
| B | `logic_tools` README | 1h | High | 🔴 High | ✅ Done |
| B | `web_archive_tools` README | 1h | High (18 files) | 🔴 High | ✅ Done |
| B | `media_tools` README | 45min | Medium | 🟡 Medium | ✅ Done |
| B | `pdf_tools` README | 45min | Medium | 🟡 Medium | ✅ Done |
| B | `development_tools` README | 1h | Medium (19 files) | 🟡 Medium | ✅ Done |
| B | `legacy_mcp_tools` migration guide | 2h | Medium | 🟡 Medium | ✅ Done |
| C | 34 remaining category READMEs | 12-15h | Medium | 🟢 Later | ✅ Done |
| D | `tools/__init__.py` coverage 17→51 | 1h | Low-Medium | 🟢 Later | ✅ Done |
| D | Deprecation warnings — all 32 legacy files | 2h | Medium | 🟡 Medium | ✅ Done |
| D | Activate 3 clean test files (admin/auth/vector) | 1h | Medium | 🟡 Medium | ✅ Done |
| D | Activate 6 more test files (bg_task/workflow/cache/monitoring/analysis/embedding) | 2h | Medium | 🟡 Medium | ✅ Done |
| D | Fix 5 failing tests + 5 new test files (dataset/ipfs/audit/security/session) | 1h | Medium | 🟡 Medium | ✅ Done |
| D | Add module docstrings to 7 category `__init__.py` | 30min | Low-Medium | 🟢 Later | ✅ Done |
| D | Extract 5 thick tool engines | 4-6h | Medium | 🟡 Medium | ✅ Done |
| D | Activate remaining ~4 `_test_*.py` files | 1-2h | Low | 🟢 Later | 🟡 Deferred |
| E+F | Session 1: move 21 engine files to package modules | 4h | High | 🔴 High | ✅ Done |
| E+F | Session 2: thin 5 thick tools (monitoring/analysis/bg_task/sparse_emb/rate_limit) | 3h | High | 🔴 High | ✅ Done |
| E+F | Session 3: thin 5 thick tools (serpstack/openverse/finance_theorems/sw_theorems/ai_dataset_builder) | 3h | High | 🔴 High | ✅ Done |
| E+F | Session 4: thin 5 thick tools (clinical_trials/pubmed/github_repo/patent/session) | 3h | High | 🔴 High | ✅ Done |
| E+F | Session 5: thin 7 thick tools (auth/geospatial/municipal/state_laws/incremental/hf_pipeline) | 3h | High | 🔴 High | ✅ Done |
| E+F | Session 6: thin 9 thick tools (hf_search/gh_search/autoscraper/archive_is/discord/verify_fr/verify_usc/json2py) | 3h | High | 🔴 High | ✅ Done |

---

**Last Updated:** 2026-02-20 (Phase E+F session 6: 9 more tool files thinned to ≤31 lines each; 9 new engine modules in web_archiving/, processors/discord/, processors/legal_scrapers/, processors/development/)
**Related:** [../MASTER_REFACTORING_PLAN_2026_v4.md](../MASTER_REFACTORING_PLAN_2026_v4.md) · [../MASTER_IMPROVEMENT_PLAN_2026_v5.md](../MASTER_IMPROVEMENT_PLAN_2026_v5.md)
