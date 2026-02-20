# MCP Server Tools — Comprehensive Improvement Plan 2026

**Date:** 2026-02-20  
**Scope:** `ipfs_datasets_py/mcp_server/tools/` and all subfolders  
**Status:** 🟡 Planning  

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
| `admin_tools` | 2 | 0 | Enhanced admin tools — no docs |
| `alert_tools` | 1 | 0 | Discord alert tools — no docs |
| `analysis_tools` | 1 | 0 | No docs |
| `audit_tools` | 3 | 0 | No docs |
| `auth_tools` | 2 | 0 | Enhanced auth — no docs |
| `background_task_tools` | 3 | 0 | No docs |
| `bespoke_tools` | 7 | 2 | Stub-only auto-generated .md files |
| `cache_tools` | 2 | 0 | No docs |
| `cli` | 2 | 0 | No docs |
| `dashboard_tools` | 3 | 0 | No docs |
| `data_processing_tools` | 1 | 0 | No docs |
| `dataset_tools` | 7 | 0 | Core category — no docs! |
| `development_tools` | 19 | 0 | Large category — no docs |
| `discord_tools` | 4 | 0 | No docs |
| `email_tools` | 3 | 0 | No docs |
| `embedding_tools` | 9 | 0 | No docs |
| `file_converter_tools` | 8 | 0 | No docs |
| `file_detection_tools` | 3 | 0 | No docs |
| `finance_data_tools` | 6 | 3 | README + 2 analysis docs (good) |
| `functions` | 1 | 0 | No docs |
| `geospatial_tools` | 1 | 0 | No docs |
| `graph_tools` | 11 | 0 | No docs |
| `index_management_tools` | 1 | 0 | No docs |
| `investigation_tools` | 7 | 0 | No docs |
| `ipfs_cluster_tools` | 1 | 0 | No docs |
| `ipfs_tools` | 3 | 0 | Core category — no docs! |
| `legacy_mcp_tools` | 32 | 0 | Largest category — no docs |
| `legal_dataset_tools` | 38 | 15 | Over-documented with historical notes |
| `lizardperson_argparse_programs` | 0 | 11 | Legacy program — MCP shim only |
| `lizardpersons_function_tools` | 0 | 0 | Empty category |
| `logic_tools` | 12 | 0 | No docs |
| `mcplusplus` | 3 | 0 | No docs |
| `media_tools` | 9 | 0 | No docs |
| `medical_research_scrapers` | 6 | 0 | No docs |
| `monitoring_tools` | 2 | 0 | No docs |
| `p2p_tools` | 2 | 0 | No docs |
| `p2p_workflow_tools` | 1 | 0 | No docs |
| `pdf_tools` | 8 | 0 | No docs |
| `provenance_tools` | 2 | 0 | No docs |
| `rate_limiting_tools` | 1 | 0 | No docs |
| `search_tools` | 1 | 0 | No docs |
| `security_tools` | 1 | 0 | No docs |
| `session_tools` | 3 | 0 | No docs |
| `software_engineering_tools` | 11 | 1 | Has README (good) |
| `sparse_embedding_tools` | 1 | 0 | No docs |
| `storage_tools` | 2 | 0 | No docs |
| `vector_store_tools` | 3 | 0 | No docs |
| `vector_tools` | 6 | 1 | Has CHANGELOG only |
| `web_archive_tools` | 18 | 0 | Large category — no docs |
| `web_scraping_tools` | 1 | 0 | No docs |
| `workflow_tools` | 2 | 0 | No docs |

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

## 3. Phase A: Documentation Triage & Cleanup

**Goal:** Clean up the existing documentation before adding new material.  
**Estimated effort:** 2-3h  
**Priority:** 🔴 High

### A1: Archive Historical `legal_dataset_tools/` Docs

Create `legal_dataset_tools/ARCHIVE/` and move historical implementation notes there.

**Create `legal_dataset_tools/ARCHIVE/README.md`** explaining what's archived.

**Move to ARCHIVE:**
- `COMPLETION_REPORT.md`
- `IMPLEMENTATION_SUMMARY.md`
- `SCRAPER_FIXES_SUMMARY.md`
- `TESTING_IMPLEMENTATION_SUMMARY.md`
- `TEST_RESULTS_REPORT.md`
- `VALIDATION_REPORT.md`
- `VERIFICATION_README.md`

**Keep in root:**
- `README.md`
- `COURTLISTENER_API_GUIDE.md`
- `CRON_SETUP_GUIDE.md`
- `CRON_SETUP_SIMPLE.md`
- `PLAYWRIGHT_SETUP.md`
- `PRIORITY2_CUSTOM_SCRAPERS.md`
- `MUNICODE_SCRAPER_MVP.md`
- `TESTING_GUIDE.md`

**Result:** 15 → 8 root markdown files (47% reduction)

### A2: Update `legal_dataset_tools/README.md` Status

The current README has several `⚠️ Placeholder data` statuses that may be outdated.

**Update the Production Status table to reflect actual current state.**

### A3: Replace `bespoke_tools/` Stub Docs

The auto-generated `__init__.md` and `cache_stats.md` are not useful docs.  
Replace them with a proper `README.md` that describes the category.

### A4: Add `lizardperson_argparse_programs/` Pointer

Add a notice at the top of the key docs that the core package has moved to
`ipfs_datasets_py/processors/legal_scrapers/bluebook_citation_validator/` and that the MCP
wrapper is at `legal_dataset_tools/bluebook_citation_validator_tool.py`.

### A5: Create `tools/README.md` Navigation Index

Add a top-level navigation index listing all 51 categories with one-line descriptions and links.

---

## 4. Phase B: Core Category Documentation

**Goal:** Add README files for the 10 highest-priority undocumented categories.  
**Estimated effort:** 6-8h  
**Priority:** 🔴 High

Priority is determined by:
1. Number of Python tool files (larger = more important to document)
2. Likelihood of being used by external consumers
3. Core vs. peripheral functionality

### Priority Order for Phase B

| # | Category | Files | Why Priority |
|---|----------|-------|--------------|
| 1 | `dataset_tools` | 7 | Core — fundamental dataset operations |
| 2 | `ipfs_tools` | 3 | Core — fundamental IPFS operations |
| 3 | `graph_tools` | 11 | Core — knowledge graph operations |
| 4 | `embedding_tools` | 9 | Core — embeddings and similarity |
| 5 | `logic_tools` | 12 | Core — FOL/deontic logic |
| 6 | `web_archive_tools` | 18 | Large — 18 files, high utility |
| 7 | `media_tools` | 9 | Functional — FFmpeg/yt-dlp |
| 8 | `pdf_tools` | 8 | Functional — PDF processing |
| 9 | `development_tools` | 19 | Large — 19 files including GitHub, Claude, Gemini |
| 10 | `legacy_mcp_tools` | 32 | Largest — migration target for future work |

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

## 5. Phase C: Full Coverage & Advanced Guides

**Goal:** Document all 44 undocumented categories; add advanced guides.  
**Estimated effort:** 15-20h  
**Priority:** 🟡 Medium

### C1: Remaining 34 Undocumented Categories

After Phase B covers the top 10, document the remaining 34 categories:

**Group 1 — Functional tools (3-5 files each):**
`audit_tools`, `auth_tools`, `background_task_tools`, `cache_tools`, `file_converter_tools`,
`file_detection_tools`, `monitoring_tools`, `provenance_tools`, `search_tools`, `session_tools`,
`storage_tools`, `vector_store_tools`, `workflow_tools`

**Group 2 — Specialised tools (1-2 files each):**
`admin_tools`, `alert_tools`, `analysis_tools`, `data_processing_tools`, `discord_tools`,
`email_tools`, `geospatial_tools`, `index_management_tools`, `ipfs_cluster_tools`,
`p2p_tools`, `p2p_workflow_tools`, `rate_limiting_tools`, `security_tools`,
`sparse_embedding_tools`, `web_scraping_tools`

**Group 3 — P2P/MCP++ tools:**
`mcplusplus` (3 files — taskqueue_engine, peer_engine, workflow_engine)

**Group 4 — Specialised scrapers:**
`investigation_tools`, `medical_research_scrapers`

### C2: Cross-Cutting Guides

Add `docs/` subdirectory entries for:
- **Tool dependency matrix** — which categories require which optional packages
- **Tool naming conventions** — how tools are named and registered
- **Testing guide for tools** — how to add tests for new tools

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

## 7. Phase D: Code Quality Improvements

**Goal:** Address code quality issues that affect maintainability.  
**Estimated effort:** 10-14h  
**Priority:** 🟡 Medium

### D1: Audit `legacy_mcp_tools/` (2-3h)

1. For each of the 32 files, determine if it is superseded by a new category
2. Add deprecation notices at the top of superseded files
3. Update `__init__.py` to surface deprecation warnings on import
4. Create migration guide: `legacy_mcp_tools/MIGRATION_GUIDE.md`

### D2: Extract Business Logic from 5 Thickest Tool Files (4-6h)

Following the engine extraction pattern from MASTER_REFACTORING_PLAN v4:

| Tool File | Target Engine Module | Estimate |
|-----------|---------------------|---------|
| `development_tools/github_cli_server_tools.py` (765 lines) | `github_cli_engine.py` | 1.5h |
| `monitoring_tools/enhanced_monitoring_tools.py` (670 lines) | Already exists? Check | 0.5h |
| `web_archive_tools/brave_search.py` (653 lines) | `brave_search_engine.py` | 1h |
| `finance_data_tools/news_scrapers.py` (650 lines) | `news_scraper_engine.py` | 1h |
| `finance_data_tools/stock_scrapers.py` (590 lines) | `stock_scraper_engine.py` | 1h |

### D3: Activate or Remove Disabled Tests (2-3h)

Review all `tests/_test_*.py` files:
1. Remove the `_` prefix for files with valid tests that can pass
2. Update test fixtures/mocks for tests that fail due to missing dependencies
3. Remove test files that test functionality that no longer exists
4. Target: all active tool categories have at least 1 non-disabled test file

### D4: Fix `tools/__init__.py` Module Coverage (1-2h)

The root `_TOOL_SUBMODULES` set only lists 17 of 51 categories. All active categories should
be listed to enable lazy loading:

```python
_TOOL_SUBMODULES: Final[set[str]] = {
    "admin_tools",
    "alert_tools",
    "analysis_tools",
    "audit_tools",
    "auth_tools",
    "background_task_tools",
    "bespoke_tools",
    "cache_tools",
    # ... all 51 categories
}
```

---

## 8. Success Metrics

| Metric | Current | Phase A Target | Phase B Target | Phase C+D Target |
|--------|---------|----------------|----------------|------------------|
| Categories with README | 3 | 4 | 14 | 51 |
| Historical docs in root dirs | 14 (legal) | 0 | 0 | 0 |
| Thick tools (>500 lines) | 10+ | 10+ | 10+ | ≤5 |
| Disabled test files | ~10 | ~10 | ~10 | ≤3 |
| `_TOOL_SUBMODULES` coverage | 17/51 | 17/51 | 17/51 | 51/51 |
| Top-level `tools/README.md` | ❌ | ✅ | ✅ | ✅ |

---

## 9. Priority Matrix

| Phase | Item | Effort | Impact | Priority |
|-------|------|--------|--------|----------|
| A | Archive historical legal docs | 30min | High (clutter reduction) | 🔴 Do first |
| A | Create `tools/README.md` index | 1h | High (navigation) | 🔴 Do first |
| A | Update `legal_dataset_tools/README.md` status | 30min | Medium | 🔴 Do first |
| A | Fix `bespoke_tools/` stub docs | 30min | Low | 🟡 Soon |
| B | `dataset_tools` README | 1h | Very High (core) | 🔴 High |
| B | `ipfs_tools` README | 45min | Very High (core) | 🔴 High |
| B | `graph_tools` README | 1h | High | 🔴 High |
| B | `embedding_tools` README | 1h | High | 🔴 High |
| B | `logic_tools` README | 1h | High | 🔴 High |
| B | `web_archive_tools` README | 1h | High (18 files) | 🔴 High |
| B | `media_tools` README | 45min | Medium | 🟡 Medium |
| B | `pdf_tools` README | 45min | Medium | 🟡 Medium |
| B | `development_tools` README | 1h | Medium (19 files) | 🟡 Medium |
| B | `legacy_mcp_tools` migration guide | 2h | Medium | 🟡 Medium |
| C | Remaining 34 categories | 12-15h | Medium | 🟢 Later |
| D | `legacy_mcp_tools/` audit | 2-3h | Medium | 🟡 Medium |
| D | Extract 5 thick tool engines | 4-6h | Medium | 🟡 Medium |
| D | Activate disabled tests | 2-3h | Medium | 🟡 Medium |
| D | Fix `tools/__init__.py` coverage | 1h | Low-Medium | 🟢 Later |

---

**Last Updated:** 2026-02-20  
**Related:** [../MASTER_REFACTORING_PLAN_2026_v4.md](../MASTER_REFACTORING_PLAN_2026_v4.md) · [../MASTER_IMPROVEMENT_PLAN_2026_v5.md](../MASTER_IMPROVEMENT_PLAN_2026_v5.md)
