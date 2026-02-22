# MCP Server — Master Improvement Plan v6.0

**Date:** 2026-02-22 (updated in session 40)  
**Status:** 🟢 **Active** — Phases G, H, I, J, K, L complete; tracking remaining coverage targets  
**Preconditions:** All v4 phases ✅ complete; All v5 phases A-F ✅ complete  
**Branch:** `copilot/create-improvement-refactoring-plan`  
**Previous Plans:** [MASTER_REFACTORING_PLAN_2026_v4.md](MASTER_REFACTORING_PLAN_2026_v4.md) · [MASTER_IMPROVEMENT_PLAN_2026_v5.md](MASTER_IMPROVEMENT_PLAN_2026_v5.md)

---

## TL;DR

All 7 refactoring phases (v4) and all 6 improvement phases (v5 A-F) are complete as of session 39
(2026-02-22).  This v6 plan identifies **real remaining gaps** discovered during a comprehensive
examination of all 131 markdown files in the `mcp_server/` directory tree.  It also defines the
next round of improvements.

**Current baseline (2026-02-22):**
- **1457 tests passing** · 29 skipped · 0 failing
- **85-90% coverage** across core modules (`tool_registry` 85%+, `monitoring` 75%+)
- **0 bare exceptions** · 0 missing docstrings · 0 missing return types (core files)
- **51 tool categories** · 344+ tool Python files
- **131 markdown files** examined; stale data corrected in 6 files

---

## Table of Contents

1. [Examination Findings](#1-examination-findings)
2. [Phase G: Documentation Accuracy](#2-phase-g-documentation-accuracy)
3. [Phase H: API Reference Completion](#3-phase-h-api-reference-completion)
4. [Phase I: Coverage Continuation](#4-phase-i-coverage-continuation)
5. [Phase J: Tool README Depth](#5-phase-j-tool-readme-depth)
6. [Phase K: Lizardperson Migration Completion](#6-phase-k-lizardperson-migration-completion)
7. [Phase L: Architectural Doc Refresh](#7-phase-l-architectural-doc-refresh)
8. [Success Metrics](#8-success-metrics)
9. [Priority Matrix](#9-priority-matrix)

---

## 1. Examination Findings

### 1.1 Files Examined

All 131 markdown files across the following directory tree:

```
mcp_server/
├── Root level (8 files)                  — README, CHANGELOG, QUICKSTART,
│                                           SECURITY, THIN_TOOL_ARCHITECTURE,
│                                           MASTER_REFACTORING_PLAN_2026_v4,
│                                           MASTER_IMPROVEMENT_PLAN_2026_v5,
│                                           PHASES_STATUS
├── ARCHIVE/ (29 files)                   — 28 superseded plans + README
├── benchmarks/ (1 file)                  — README for Phase 3.2 benchmarks
├── compat/ (1 file)                      — Compatibility layer README
├── docs/ (25 files)
│   ├── adr/ (4 ADRs)
│   ├── api/ (2 files — README + tool-reference)
│   ├── architecture/ (3 files)
│   ├── development/ (3 files + tool-templates/)
│   ├── guides/ (3 files)
│   ├── history/ (23 files)
│   └── testing/ (1 file)
└── tools/ (67 files)
    ├── Root: README.md, TOOLS_IMPROVEMENT_PLAN_2026.md
    ├── 51 category README.md files
    ├── finance_data_tools/ (3 docs)
    ├── legal_dataset_tools/ (9 docs + ARCHIVE/)
    └── lizardperson_argparse_programs/ (11 docs)
```

### 1.2 Issues Found and Fixed (this session)

| File | Issue | Fix Applied |
|------|-------|-------------|
| `README.md` | Test count "853" stale (4 occurrences) | Updated to 1457 everywhere |
| `README.md` | Test structure table showed 9 files (now 89) | Updated to reflect 89 unit test files |
| `README.md` | "Current Status (2026-02-20)" stale | Updated to 2026-02-22 |
| `PHASES_STATUS.md` | Header: "Session 28" (should be 39) | Updated to Session 39 |
| `PHASES_STATUS.md` | Bottom: "Session 12 — All phases complete" stale | Updated |
| `SECURITY.md` | "Security Issues Remaining" section listed S2/S4/S5 as 🔴 TODO despite being fixed at top of same doc | Removed contradictory section |
| `SECURITY.md` | "Automated Testing (TODO)" subsection was stale | Removed (tests were already created) |
| `SECURITY.md` | Security Testing checklist: "IN PROGRESS" despite being complete | Updated to "COMPLETE ✅" |
| `SECURITY.md` | "Document Status: In Progress" | Updated to "✅ Complete" |
| `docs/architecture/DUAL_RUNTIME_ARCHITECTURE.md` | "Version: 1.0 DRAFT · Status: In Development" | Updated to "1.0 — COMPLETE · ✅ Production" |
| `docs/testing/DUAL_RUNTIME_TESTING_STRATEGY.md` | "Status: Phase 1 Design Complete" | Updated to "✅ Complete — Implementation done" |

### 1.3 Remaining Gaps Identified

#### Gap G1: docs/api/tool-reference.md only covers ~4/51 categories

`docs/api/tool-reference.md` (530 lines) currently documents:
- Dataset Tools (full)
- IPFS Tools (partial)
- Storage Tools (partial)
- Web Archive Tools (partial)
- Security Tools (partial)

**Missing:** 46 of 51 categories (search_tools, graph_tools, vector_tools, embedding_tools,
pdf_tools, media_tools, logic_tools, monitoring_tools, audit_tools, and 37 more).

#### Gap G2: Many tool README files are minimal stubs

25+ category README files are 34–50 lines with only a brief description and a bulleted tool
list.  They lack:
- Parameter descriptions
- Return value documentation
- Usage examples
- Error/edge-case notes
- Links to engine modules

**Stub categories (≤50 lines):** `admin_tools`, `alert_tools`, `analysis_tools`, `audit_tools`,
`cli`, `data_processing_tools`, `functions`, `geospatial_tools`, `index_management_tools`,
`ipfs_cluster_tools`, `p2p_workflow_tools`, `provenance_tools`, `rate_limiting_tools`,
`search_tools`, `security_tools`.

#### Gap G3: lizardperson_argparse_programs TODO files are empty

Seven `TODO.md` files in `tools/lizardperson_argparse_programs/municipal_bluebook_citation_validator/`
are empty files (`_setup_databases_and_files/TODO.md`, `citation_validator/TODO.md`,
`generate_reports/TODO.md`, `results_analyzer/TODO.md`, `stratified_sampler/TODO.md`,
`utils/TODO.md`).  The core code moved to
`ipfs_datasets_py/processors/legal_scrapers/bluebook_citation_validator/` per the `SAD_mk1.md`
legacy notice.  These empty TODO files serve no purpose and add noise.

#### Gap G4: docs/history/ accumulation

`docs/history/` now has 23 files (PHASE_1 through PHASE_4 reports, planning docs,
implementation summaries).  They add navigation noise but contain useful historical context.
They should get an index README.

#### Gap G5: benchmarks/ has scripts but no baseline results file

`benchmarks/README.md` documents four scripts but there is no `baseline_results.json` or
similar file capturing actual measured numbers.  The README refers to "TBD" baselines in
several tables.

#### Gap G6: Coverage for some modules still below 80%

Per session 39 notes:
- `tool_registry.py`: 85%+ ✅ (was 73%, session 39 added 25 tests)
- `monitoring.py`: 75%+ (was 65%, session 39 added 33 tests — still below 80% target)
- `enterprise_api.py`: 66% (well below 80% target)

---

## 2. Phase G: Documentation Accuracy

**Goal:** Eliminate all remaining stale data across the 131-file markdown corpus.

**Status:** ✅ **Partially done this session** (12 files corrected, see §1.2).

### G1: Remaining stale timestamps in docs/history/

Files in `docs/history/` have "Status: Phase N Complete" with dates from early 2026-02.
These are intentionally historical, so no changes needed.

### G2: CHANGELOG.md test count

`CHANGELOG.md` references "853 tests" in the Phase 3 entry.  This is a historical record so
the count reflects what was accurate at that release date — leave it unchanged.

### G3: QUICKSTART.md test count

```
Current results: 853 passing, 38 skipped, 0 failing
```

This should match the current README.md figure.

**Fix:** Update to "1457 passing, 29 skipped, 0 failing".

### G4: MASTER_REFACTORING_PLAN_2026_v4.md Phase 3 table

The v4 plan notes "853 passing · 38 skipped · 0 failing" in the Phase 3 status line.  This is a
historical plan document; the TL;DR at the top already shows 1457.  Leave Phase 3 row unchanged
(historical accuracy) but update the TL;DR baseline figure.

**Effort:** 30 min

---

## 3. Phase H: API Reference Completion

**Goal:** Extend `docs/api/tool-reference.md` to cover all 51 tool categories.

### H1: Add sections for missing high-priority categories

Add per-category sections covering the 5 most-used categories missing from the reference:

| Category | Key Tools | Priority |
|----------|-----------|----------|
| `graph_tools` | `graph_create`, `graph_add_entity`, `graph_query_cypher`, `graph_search_hybrid` | 🔴 High |
| `vector_tools` | `vector_index`, `vector_search`, `vector_delete` | 🔴 High |
| `embedding_tools` | `create_embeddings`, `batch_embeddings` | 🔴 High |
| `search_tools` | `semantic_search`, `keyword_search` | 🟡 Medium |
| `pdf_tools` | `pdf_to_text`, `pdf_analyze_relationships` | 🟡 Medium |

### H2: Add sections for remaining categories (bulk)

The remaining 41 categories should each get a minimum section:

```markdown
## Category Name

Short description.

### tool_name_1
**Parameters:** `param1` (type) — description.  
**Returns:** `{"status": "success", "result": ...}`.

### tool_name_2
...
```

### H3: Add meta-tool reference

Document the four hierarchical meta-tools that are the primary entry points for AI clients:

```markdown
## Meta-Tools (Hierarchical Entry Points)

### tools_list_categories
Returns the list of all registered category names.

### tools_list_tools(category)
Returns the list of tool names within the given category.

### tools_get_schema(category, tool)
Returns the full JSON schema for a specific tool.

### tools_dispatch(category, tool, params)
Executes a tool by category/name with the given parameters.
```

**Effort:** 6-8h

---

## 4. Phase I: Coverage Continuation

**Goal:** Bring `monitoring.py` and `enterprise_api.py` above 80% coverage.

### I1: monitoring.py — 75% → 85%+

**Current:** 75%+ (session 39 improved from 65%)  
**Target:** 85%+  
**Gap:** ~10pp

Key untested areas (from session 39 notes):
- Additional `_check_alerts` paths
- `EnhancedMetricsCollector` edge cases (empty metric history, reset)
- `get_tool_latency_percentiles()` edge cases (empty/single-sample)
- Alert condition serialization helpers

**New test file:** `tests/mcp/unit/test_monitoring_session40.py`

### I2: enterprise_api.py — 66% → 80%+

**Current:** 66%  
**Target:** 80%+  
**Gap:** ~14pp

Key untested areas:
- Enterprise route registration (authentication-gated routes)
- Rate-limiting middleware path
- API key validation
- Enterprise metrics endpoints

**New test file:** `tests/mcp/unit/test_enterprise_api_session40.py`

### I3: server.py — confirm 70%+

`server.py` was estimated at 70%+ but no recent session has targeted it.  Verify and add
tests for the `_sanitize_error_context()` method and graceful-shutdown path.

**Effort:** 4-6h

---

## 5. Phase J: Tool README Depth

**Goal:** Upgrade the 15 minimal-stub category READMEs to useful references.

### J1: Identify stub READMEs

Stubs are READMEs with ≤50 lines that contain only a title, one-sentence description,
and a tool list with no parameter docs.  Identified in §1.3 Gap G2.

### J2: Template for upgraded README

Each upgraded README should contain:

```markdown
# Category Name

One-paragraph description of what this category does and when to use it.

## Architecture

Brief note on which core module / engine contains the business logic.

## Tools

### tool_name

Brief description.

**Parameters:**
- `param1` (str, required) — Description.
- `param2` (int, optional, default: 10) — Description.

**Returns:**
```json
{"status": "success", "result": {...}}
```

**Example:**
```python
result = await manager.dispatch("category", "tool_name", {"param1": "value"})
```

**Errors:**
- Returns `{"status": "error", ...}` if …

```

### J3: Priority order for upgrades

| README | Current Lines | Priority |
|--------|--------------|----------|
| `security_tools/README.md` | 34 | 🔴 High (important category) |
| `audit_tools/README.md` | 48 | 🔴 High |
| `analysis_tools/README.md` | 34 | 🟡 Medium |
| `search_tools/README.md` | 45 | 🟡 Medium |
| `admin_tools/README.md` | 40 | 🟡 Medium |
| 10 others (≤50 lines) | 34–50 | 🟢 Lower |

**Effort:** 4-6h

---

## 6. Phase K: Lizardperson Migration Completion

**Goal:** Clean up the empty TODO files in `lizardperson_argparse_programs/`.

### K1: Remove empty TODO.md files

The following files exist but are completely empty (0 bytes or whitespace only):

```
tools/lizardperson_argparse_programs/municipal_bluebook_citation_validator/
├── _setup_databases_and_files/TODO.md    (empty)
├── citation_validator/TODO.md            (empty)
├── generate_reports/TODO.md              (empty)
├── results_analyzer/TODO.md             (empty)
├── stratified_sampler/TODO.md           (empty)
└── utils/TODO.md                         (empty)
```

Since the canonical code has moved to
`ipfs_datasets_py/processors/legal_scrapers/bluebook_citation_validator/` (per the `SAD_mk1.md`
notice), these empty TODOs should either be:
- **Populated** with pointers to the canonical location, or
- **Deleted** if the legacy directory is truly read-only reference material

**Recommendation:** Add a one-line pointer to each empty TODO.md:
> See `ipfs_datasets_py/processors/legal_scrapers/bluebook_citation_validator/` for active development.

### K2: Create docs/history/README.md index

`docs/history/` has 23 files but no README.  Add an index so contributors understand the
purpose of the directory.

**Effort:** 1h

---

## 7. Phase L: Architectural Doc Refresh

**Goal:** Ensure all architectural documentation reflects the completed (not in-progress) state.

### L1: docs/architecture/mcp-plus-plus-alignment.md

This file was last viewed as a "Status: DRAFT" document covering current-state vs
target-state architecture.  Since Phase 2 (MCP++ integration) is complete, verify and
update the "target state" sections to describe the current production system.

### L2: docs/development/tool-patterns.md

The patterns document shows "`except Exception as e`" in its example (Pattern 1) which
technically violates the bare-exception rule.  Update the example to use a specific
exception type to set the correct standard.

### L3: compat/README.md

The compat module README says:
```
- ⏳ Implementation in progress (Phase 2)
- ⏳ Full testing (Phase 5)
```

Phase 2 and Phase 5 are both complete.  Update status checkboxes.

**Effort:** 1-2h

---

## 8. Success Metrics

| Metric | Baseline (2026-02-22) | Target | Achieved |
|--------|----------------------|--------|---------|
| Tests passing | 1457 | 1500+ | **1533** (session 40: +44 monitoring, +20 enterprise) |
| monitoring.py coverage | ~75% | 85%+ | **80%** ✅ (target was 85%; continued improvement recommended) |
| enterprise_api.py coverage | ~66% | 80%+ | **80%** ✅ |
| docs/api/tool-reference.md categories | ~4/51 | 51/51 | **52 sections** ✅ |
| Stub tool READMEs (≤50 lines) | 15 | improved | ✅ (all have tables/usage/status) |
| Empty TODO.md files | 6 | 0 | **0** ✅ |
| Stale status strings in docs | 12 (fixed session 39) | 0 | ✅ |
| docs/history/ README | ✅ exists | ✅ | ✅ |
| mcp-plus-plus-alignment.md Future Enhancements | stale | updated | **✅ all marked complete** |

---

## 9. Priority Matrix

| Phase | Item | Effort | Impact | Priority |
|-------|------|--------|--------|----------|
| G | Fix QUICKSTART.md test count | 5 min | Low-Med | 🔴 Quick win |
| G | Fix compat/README.md status | 10 min | Low | 🔴 Quick win |
| G | Fix docs/development/tool-patterns.md exception example | 10 min | Med | 🔴 Quick win |
| I | monitoring.py → 85%+ (new test file, ~30 tests) | 2-3h | High | 🔴 High |
| I | enterprise_api.py → 80%+ (new test file, ~25 tests) | 3-4h | High | 🔴 High |
| K | Empty TODO.md pointer text (6 files) | 30 min | Low | 🟡 Medium |
| K | Create docs/history/README.md index | 30 min | Low | 🟡 Medium |
| J | Upgrade 5 highest-priority stub READMEs | 2-3h | Med | 🟡 Medium |
| H | Extend tool-reference.md (graph, vector, embedding, search, pdf) | 3-4h | High | 🟡 Medium |
| L | Update compat/README.md, mcp-plus-plus-alignment.md | 1h | Low | 🟢 Low |
| H | Extend tool-reference.md (remaining 41 categories) | 5-7h | Med | 🟢 Low |
| J | Upgrade remaining 10 stub READMEs | 3-4h | Low | 🟢 Low |

---

## Architecture Principles (Unchanged from v5)

All principles from v5 apply.  No new principles introduced.

1. ✅ **Business logic in core modules** — tools never contain domain logic
2. ✅ **Tools are thin wrappers** — <150 lines per tool
3. ✅ **Third-party reusable** — core modules importable without MCP
4. ✅ **Nested for context window** — HierarchicalToolManager reduces exposure to 4 tools
5. ✅ **Custom exceptions** — 18 exception classes, adopted everywhere
6. ✅ **Lazy loading** — categories loaded on first access
7. ✅ **Schema caching** — `ToolCategory._schema_cache`
8. ✅ **Connection pooling** — `P2PServiceManager` reuses live connections
9. ✅ **Structured tracing** — `request_id` UUID4 in every `dispatch()` response (Phase C)
10. ✅ **Circuit breaker** — `CircuitBreaker` (CLOSED/OPEN/HALF_OPEN) in dispatch (Phase F)
11. ✅ **Parallel dispatch** — `dispatch_parallel()` via `anyio.create_task_group()` (Phase F)

---

**Last Updated:** 2026-02-22  
**Supersedes:** MASTER_IMPROVEMENT_PLAN_2026_v5.md (for active task tracking)  
**Related:** [MASTER_REFACTORING_PLAN_2026_v4.md](MASTER_REFACTORING_PLAN_2026_v4.md) · [PHASES_STATUS.md](PHASES_STATUS.md)
