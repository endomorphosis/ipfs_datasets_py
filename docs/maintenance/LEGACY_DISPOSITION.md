# Legacy, duplicate, and historical disposition map

| Field | Value |
| --- | --- |
| Interface | `LegacyDocumentationDisposition@1` |
| Task | `IPFSDOC-094` |
| Status | `evidence` |
| Owner | documentation-governance |
| Source of truth | Live tree under `docs/` and `ipfs_datasets_py/**/*.md`; peers `CURRENT_STATE_BASELINE.md`, `PACKAGE_LOCAL_DOCUMENTATION_MAP.md`, `INFORMATION_ARCHITECTURE.md`, `SOURCE_AUTHORITY.md`, `DRIFT_AND_CLAIM_MATRIX.md`, `COVERAGE_MATRIX.md`, architecture hub `docs/architecture/README.md`; link scan via `docs/maintenance/check_docs.py --checks links` |
| Last verified | 2026-08-03 |
| Measured tree | Documentation refresh worktree aligned with IPFSDOC-001 baseline (`docs/**/*.md` ≈ 1476; `ipfs_datasets_py/**/*.md` ≈ 387; docs root pages = 117) |
| Audience | maintainers, documentation authors, navigation and release agents |
| Non-goals | This map does **not** move, delete, rename, rewrite, or bulk-archive inventoried files. Destructive cleanup is deferred to later **reviewed** tasks that update this map. |

## Purpose

The documentation tree holds concurrent product guides, package-local notes,
generated builds, migration narratives, phase completion reports, versioned
plans, and already-archived history. Without an explicit disposition map,
agents and humans re-cite stale completion language as current status and
duplicate competing hubs.

This document:

1. Classifies **high-priority** root plans, status, and phase reports.
2. Classifies **versioned / old / backup** variants and competing architecture bodies.
3. Records **generated builds** and **package-local** corpora with owners and replacements.
4. Prioritizes **broken-link clusters** from the local link checker.
5. Assigns every row an owner, disposition **status**, **canonical replacement**,
   and a **future move/delete review** recommendation.

**Hard rule (this task):** classify only. Preserve history in place. Do not
present historical completion metrics as product readiness.

Authority order when sources disagree (same as program plan and
`SOURCE_AUTHORITY.md`):

1. executable tests and schemas;
2. current implementation and packaging metadata;
3. operator configuration and deployment manifests;
4. accepted architecture decision records;
5. maintained guides with lifecycle `canonical` / status `current`;
6. historical plans, completion reports, generated summaries, and archive material.

---

## Disposition vocabulary

Every classified unit uses **exactly one** primary **status**. The
**replacement** column names the page or corpus that should be cited instead
(or `—` when none applies / none yet exists).

| Status | May be cited as current product authority? | Meaning | Typical future review |
| --- | --- | --- | --- |
| `current` | **Yes** (for its scoped concern) | Body of record after refresh against ranks 1–5; keep discoverable | Keep in place; refresh on cadence; no archive |
| `superseded` | **No** | A named newer page fully owns the concern; old path retained for URL/history | Banner + pointer; after review window, **move** to `docs/archive/` (do not delete) |
| `historical` | **No** | Point-in-time plan, phase report, session summary, ARCHIVE tree, or completed migration narrative | Prefer **move** into archive subtrees when still under live roots; never rewrite to look current |
| `duplicate` | **No** (except thin pointer) | Parallel body that overlaps a `current` or target canonical page | Merge or demote to pointer; keep one body; optional archive of the loser |
| `review-needed` | **No** until reclassified | Mixed, undated, multi-claim, or high-value page not yet safe to promote or demote | Classify against current tree; prefer code/tests over prose |
| `generated` | Only for regenerated facts | Machine-produced stubs, Sphinx `_build`, MkDocs `site/`, committed HTML/doctrees | Regenerate from source; never hand-author design rationale; optional gitignore of rebuildable trees |
| `plan` | **No** (intent only) | Active or retained planning boards / objectives / todo heaps | Leave under `implementation/plans/` or domain plan paths; not product nav |

### Column definitions used in tables

| Column | Meaning |
| --- | --- |
| **Unit** | Path, path pattern, or named cluster treated as one disposition unit |
| **Owner** | Role accountable for future banner, refresh, or reviewed move (not necessarily original author) |
| **Status** | One vocabulary label above |
| **Canonical replacement** | Path(s) readers and agents must prefer; “replacement” of the unit for citation |
| **Future move/delete review** | Non-binding recommendation for a later reviewed task: `keep`, `banner-in-place`, `move-to-archive`, `merge-then-archive`, `pointer-only`, `delete-after-review` (delete only when no audit value and git history suffices), or `regenerate-or-gitignore` |

`delete-after-review` is rare and never authorized by this map alone.

---

## Explicit non-actions (IPFSDOC-094)

| Action | Status |
| --- | --- |
| Bulk move of root phase/status reports into `docs/archive/` | **Not performed** |
| Bulk delete of versioned plans, backups, ARCHIVE, stubs, or Sphinx builds | **Not performed** |
| Rewrite of protected program plan files | **Forbidden** (read-only) |
| Change of `mkdocs.yml` nav | **Not performed** (owned by navigation tasks) |
| Mark board todo metadata complete | **Not performed** |
| Silent supersession of Accepted ADRs | **Forbidden** |

Agents that later **migrate**, **merge**, or **archive** must update this map
in the same change set.

---

## 1. Inventory summary (high-priority corpora)

| Corpus | Approx. size (this worktree) | Default status | Canonical replacement (cluster) | Future move/delete review |
| --- | ---: | --- | --- | --- |
| Docs root `docs/*.md` | 117 | **Split** — see §2 | Product entry + architecture hub + domain leaves | Split per row; bulk archive of historical subset later |
| Root phase / status / completion / session | ~34 | `historical` | Architecture hub + domain leaves + maintenance evidence | `move-to-archive` under `docs/archive/root_status_reports/` or `completion_reports/` |
| Root MCP cluster | ~14 | **Split** | `docs/architecture/mcp/`, MCP ADRs, refreshed tools guide | Plans `historical`; product guides `review-needed` / later `current` |
| Root IPLD / vector cluster | 12 | **Split** | `docs/architecture/storage/CONTENT_ADDRESSING_AND_IPLD.md`, `docs/architecture/retrieval/*` | Completions/sessions → archive; guides → refresh |
| Root migration / deprecation | ~10 | `historical` or migration-preserve | Domain migration guides + deprecation schedule after refresh | Keep migration OLD columns; demote undated status |
| Navigation index triple | 3 (+ domain indexes) | `duplicate` / `review-needed` | `docs/index.md` + `docs/DOCUMENTATION_INDEX.md` (IPFSDOC-095) | Collapse to one index; archive extras |
| `docs/archive/**` | ~249 files | `historical` | Current entry points (`index`, getting started, architecture hub) | `keep` (already archived) |
| `docs/archived_stubs/**` | ~124 files | `generated` + `historical` | Live package source / API maps | `keep` |
| `docs/reports/**` | ~72 md | `historical` | Maintenance matrices + release evidence | `keep` or consolidate README only |
| `docs/logic/` versioned refactor plans | 21 (`v2`…`v22`) | `historical` | `docs/architecture/logic/*` | `move-to-archive` later (series as one unit) |
| `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_*` | 30+ | `historical` | Program plan under `implementation/plans/` (read-only) | `keep` |
| Package-local `ipfs_datasets_py/**/*.md` | ~387 | **Split** | See `PACKAGE_LOCAL_DOCUMENTATION_MAP.md` + §6 | Map-only until package→docs tasks |
| MCP package `ARCHIVE/` | 37 md | `historical` | Architecture MCP leaves + package ADRs | `keep` in package archive |
| Generated stubs / Sphinx / MkDocs site | see §5 | `generated` | Source modules / RST / `mkdocs.yml` | regenerate or gitignore; no hand edit |
| Link-check allowlisted broken links | 276 findings | N/A (defect class) | Fix on `current` pages; allowlist archives | Prioritized in §7 |

---

## 2. High-priority root plans, status, and phase reports

### 2.1 Product entry and navigation spine (prefer as `current` targets)

These are the **replacement** destinations for most demotions. Drift may still
exist (see `DRIFT_AND_CLAIM_MATRIX.md`); disposition here is **lifecycle**, not
claim freshness.

| Unit | Owner | Status | Canonical replacement | Future move/delete review |
| --- | --- | --- | --- | --- |
| `docs/index.md` | documentation-governance / navigation | `current` (hub) | — (is the product portal target) | `keep`; IPFSDOC-095 rebuild |
| `docs/README.md` | documentation-governance | `current` (docs overview) | `docs/index.md` for end-user entry | `keep` |
| `docs/getting_started.md` | install / first-run owner | `current` (nav) | — | `keep`; repair P0 extras claims |
| `docs/installation.md` | install guide owner | `current` (nav) | — | `keep`; rewrite Python/extras (P0) |
| `docs/user_guide.md` | user journey owner | `current` (nav) | — | `keep`; import retarget |
| `docs/developer_guide.md` | developer docs owner | `current` (nav) | — | `keep`; command retarget |
| `docs/configuration.md` | ops / config owner | `current` | config reference under guides when present | `keep` |
| `docs/FEATURES.md` | product docs owner | `current` (catalog) | — | `keep`; fix stale imports |
| `docs/GLOSSARY.md` | documentation-governance | `current` | — | `keep` |
| `docs/architecture/README.md` | architecture / documentation-governance | `current` | — | `keep` |
| `docs/api/OPTIMIZERS_API_REFERENCE.md` | optimizers / API owner | `current` (navigated) | Future domain API maps | `keep` until domain API wave |
| `docs/api/CORE_OPERATIONS_API.md` | core ops / API owner | `current` (navigated) | Future domain API maps | `keep` |
| `docs/DOCUMENTATION_INDEX.md` | navigation | `review-needed` → target `current` after IPFSDOC-095 | `docs/index.md` + this index as deep map | Rebuild; absorb duplicates |
| `docs/DOCUMENTATION_INDEX_COMPLETE.md` | navigation | `duplicate` | `docs/DOCUMENTATION_INDEX.md` | `merge-then-archive` |
| `docs/root_DOCUMENTATION_INDEX.md` | navigation | `duplicate` | `docs/DOCUMENTATION_INDEX.md` | `merge-then-archive` |
| `docs/CHANGELOG.md` | release docs owner | `review-needed` | SemVer product changelog **or** maintenance session logs | Restructure; demote worker logs to `historical` |

### 2.2 Phase / completion / session / status cluster (docs root)

Default status: **`historical`**. Do not cite completion percentages, tool-count
“1100% increases”, or “100% complete” language as live product status
(CLAIM-complete-001…003, CLAIM-tools-003).

| Unit | Owner | Status | Canonical replacement | Future move/delete review |
| --- | --- | --- | --- | --- |
| `docs/PHASE_5_COMPLETE.md` | archive disposition | `historical` | Domain architecture leaves for the phase’s product surface | `move-to-archive` → `docs/archive/completion_reports/` |
| `docs/PHASE_6_COMPLETE.md` | archive disposition | `historical` | Same | `move-to-archive` |
| `docs/PHASE_7_8_COMPLETE.md` | archive disposition | `historical` | Same | `move-to-archive` |
| `docs/PHASE_7_8_COMPREHENSIVE_PLAN.md` | archive disposition | `historical` / `plan` | Current domain plans under `implementation/plans/` or architecture plans | `move-to-archive` |
| `docs/PHASE_9_COMPLETION_REPORT.md` | archive disposition | `historical` | Architecture hub + relevant domain leaves | `move-to-archive` |
| `docs/PHASE_9_PROGRESS_REPORT.md` | archive disposition | `historical` | Same | `move-to-archive` |
| `docs/PHASE_9_PARTS_3-5_SESSION_SUMMARY.md` | archive disposition | `historical` | Same | `move-to-archive` |
| `docs/PHASE_9_PARTS_3-5_FINAL_SESSION_SUMMARY.md` | archive disposition | `historical` | Same | `move-to-archive` |
| `docs/PHASE_2_6_COMPLETION_REPORT.md` | archive disposition | `historical` | Same | `move-to-archive` |
| `docs/PHASE_2_ARCHITECTURE_VALIDATION_SUMMARY.md` | archive disposition | `historical` | `docs/architecture/*` current leaves | `move-to-archive` |
| `docs/PHASES_5_8_STATUS.md` | archive disposition | `historical` | Architecture MCP leaves + ops runbooks | `move-to-archive` |
| `docs/PHASE3C_*.md`, `PHASE3C4_*`…`PHASE3C7_*`, `PHASE3D_4_PLUS_ROADMAP.md` | security / circuit / on-chain docs owner | `historical` (cluster) | Security verification guides + architecture wallet/trust leaves where applicable | `move-to-archive` as **PHASE3C cluster**; keep only if a guide is re-verified as runbook |
| `docs/SESSION_SUMMARY_PHASE3C_COMPLETION.md` | archive disposition | `historical` | Same cluster replacement | `move-to-archive` |
| `docs/PROJECT_STATUS_FINAL.md` | archive disposition | `historical` (**stale** as live status) | Maintenance coverage/drift matrices; not a product dashboard | `move-to-archive`; never cite MCP “77% complete” |
| `docs/BATCH_325_*`, `BATCH_326_*`, `BATCH_327_*` summaries | test / quality owner | `historical` | Testing strategy + evidence guides | `move-to-archive` |
| `docs/WORK_SUMMARY_2026_02_23.md` | archive disposition | `historical` | — | `move-to-archive` |
| `docs/TEST_COVERAGE_SUMMARY.md` | test docs owner | `historical` | Live coverage gates / developer testing guide | `banner-in-place` then archive if undated |
| `docs/SENTENCE_WINDOW_BENCHMARK_REPORT.md` | optimizers / retrieval owner | `historical` | Benchmarks under `docs/benchmarks/` or retrieval leaves | `move-to-archive` or keep under benchmarks with date |
| `docs/ARCHITECTURE_VALIDATION_REPORT.md` | architecture | `historical` | Current architecture leaves + validation sections | `move-to-archive` |
| `docs/ARCHITECTURE_VALIDATION_QUICK_START.md` | architecture | `review-needed` | `docs/architecture/README.md` | Promote only after re-verify; else archive |
| `docs/DOCS_DRIFT_AUDIT_REPORT.md` | documentation-governance | `historical` (prior audit) | `docs/maintenance/DRIFT_AND_CLAIM_MATRIX.md` | `banner-in-place` (superseded by matrix) → optional archive |
| `docs/MASTER_EXECUTION_GUIDE.md` | program / archive | `historical` / `plan` | Protected program plan (read-only) + architecture hub | `move-to-archive` |

### 2.3 Root MCP cluster

| Unit | Owner | Status | Canonical replacement | Future move/delete review |
| --- | --- | --- | --- | --- |
| `docs/MCP_TOOLS_GUIDE.md` | mcp-runtime / docs | `review-needed` → refresh toward `current` | `docs/architecture/mcp/TOOL_LIFECYCLE_AND_REGISTRIES.md` + package registry reality | `keep` after claim audit; qualify tool counts |
| `docs/MCP_QUICKSTART.md` | mcp-runtime | `review-needed` | `docs/architecture/mcp/SERVER_AND_DISPATCH.md` + ops `MCP_SERVER_RUNBOOK.md` | `keep` or merge into ops quickstart |
| `docs/MCP_TESTING_GUIDE.md` | mcp-runtime / test | `review-needed` | Developer testing guide + package dual-runtime notes | `keep` after refresh |
| `docs/CLI_MCP_INTEGRATION_GUIDE.md` | cli + mcp owners | `review-needed` | CLI alignment guide + MCP interfaces leaf | `keep` |
| `docs/CLI_MCP_ALIGNMENT.md` | cli + mcp owners | `review-needed` | Same | Merge with analysis sibling |
| `docs/CLI_MCP_ALIGNMENT_ANALYSIS.md` | cli + mcp owners | `historical` / `duplicate` | `CLI_MCP_ALIGNMENT.md` after refresh | `merge-then-archive` |
| `docs/MCP_ARCHITECTURE_DIAGRAM.md` | architecture | `historical` | `docs/architecture/mcp/README.md` | `move-to-archive` or fold diagram into leaf |
| `docs/MCP_IMPLEMENTATION_STATUS.md` | archive disposition | `historical` | Architecture MCP leaves; never as live % complete | `move-to-archive` |
| `docs/MCP_PHASES_5_8_PLAN.md` | archive disposition | `historical` / `plan` | Architecture MCP + ADR-007 | `move-to-archive` |
| `docs/MCP_REFACTORING_PLAN.md` | archive disposition | `historical` / `plan` | Same | `move-to-archive` |
| `docs/MCP_REFACTORING_SUMMARY.md` | archive disposition | `historical` | Same | `move-to-archive` |
| `docs/MCPPLUSPLUS_INTEGRATION_TODO.md` | archive disposition | `historical` / `plan` | Package ADR-006 (MCP++) + architecture MCP | `move-to-archive` |
| `docs/MCPPLUSPLUS_INTEGRATION_INFINITE_TODO.md` | archive disposition | `historical` | Same | `move-to-archive` |
| `docs/ENHANCEMENT_12_MCP_COMPLETION.md` | archive disposition | `historical` | Same | `move-to-archive` |
| `docs/architecture/MCP_TOOLS_ARCHITECTURE.md` | architecture | `historical` | `docs/architecture/mcp/*` | `banner-in-place`; later `move-to-archive` |
| `docs/architecture/mcp_tools_catalog.md` | architecture | `historical` | Live meta-tools / disk inventory under `mcp_server/tools/` | `banner-in-place`; do not trust static totals |
| `docs/architecture/mcp_tools_comprehensive_documentation.md` | architecture | `historical` / `duplicate` | MCP domain leaves | `move-to-archive` |
| `docs/architecture/mcp_tools_technical_reference.md` | architecture | `historical` / `duplicate` | MCP domain leaves | `move-to-archive` |

### 2.4 Root IPLD / vector cluster

| Unit | Owner | Status | Canonical replacement | Future move/delete review |
| --- | --- | --- | --- | --- |
| `docs/IPLD_VECTOR_DATABASE_GUIDE.md` | storage / retrieval docs | `review-needed` | `docs/architecture/storage/CONTENT_ADDRESSING_AND_IPLD.md` + `retrieval/VECTOR_STORES.md` | Refresh one product guide; demote siblings |
| `docs/IPLD_VECTOR_STORE_ARCHITECTURE.md` | storage | `duplicate` / `review-needed` | Same architecture leaves | `merge-then-archive` after refresh |
| `docs/IPLD_VECTOR_STORE_QUICKSTART.md` | storage | `review-needed` | Getting started + vector stores leaf | `keep` if refreshed else archive |
| `docs/IPLD_VECTOR_STORE_EXAMPLES.md` | storage | `review-needed` | Tutorials / examples after verification | `keep` or demote |
| `docs/IPLD_VECTOR_STORE_DOCUMENTATION_INDEX.md` | navigation | `duplicate` | `docs/DOCUMENTATION_INDEX.md` + storage/retrieval hubs | `merge-then-archive` |
| `docs/IPLD_VECTOR_DATABASE_PROJECT_COMPLETE.md` | archive disposition | `historical` | Architecture storage/retrieval leaves | `move-to-archive` (CLAIM-complete-001) |
| `docs/IPLD_VECTOR_DATABASE_SESSION_STATUS.md` | archive disposition | `historical` | Same | `move-to-archive` |
| `docs/IPLD_VECTOR_STORE_FINAL_SUMMARY.md` | archive disposition | `historical` | Same | `move-to-archive` |
| `docs/IPLD_VECTOR_STORE_IMPLEMENTATION_SESSION_STATUS.md` | archive disposition | `historical` | Same | `move-to-archive` |
| `docs/IPLD_VECTOR_STORE_PLANNING_SESSION_SUMMARY.md` | archive disposition | `historical` | Same | `move-to-archive` |
| `docs/IPLD_VECTOR_DATABASE_PRODUCTION_POLISH_PLAN.md` | archive disposition | `historical` / `plan` | Same | `move-to-archive` |
| `docs/IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md` | archive disposition | `historical` / `plan` | Same | `move-to-archive` |

### 2.5 Migration and deprecation cluster (root)

| Unit | Owner | Status | Canonical replacement | Future move/delete review |
| --- | --- | --- | --- | --- |
| `docs/COMPLETE_MIGRATION_GUIDE.md` | migration docs owner | `historical` (preserve OLD→NEW) | Domain architecture + processing leaves for **NEW** side | `keep` with migration banner; never “fix” OLD column |
| `docs/MIGRATION_GUIDE_V2.md` | migration docs owner | `duplicate` / `superseded` candidate | `COMPLETE_MIGRATION_GUIDE.md` if it remains the body of record | `merge-then-archive` after comparison |
| `docs/MIGRATION_CHANGELOG.md` | migration docs owner | `historical` | Product CHANGELOG after restructure | `banner-in-place` |
| `docs/MIGRATION_TOOLS_USER_GUIDE.md` | migration docs owner | `review-needed` | Developer guides + scripts inventory | Classify then keep or archive |
| `docs/FILE_CONVERTER_MIGRATION_GUIDE.md` | file-conversion docs | `historical` (schedule preserve) | Processing file/multimedia architecture | `keep` as migration |
| `docs/MULTIMEDIA_MIGRATION_GUIDE.md` | multimedia docs | `historical` | `docs/architecture/processing/FILE_AND_MULTIMEDIA.md` | `keep` as migration |
| `docs/WEB_ARCHIVING_MIGRATION_GUIDE.md` | web-archiving docs | `historical` | `docs/architecture/processing/WEB_ARCHIVING_AND_LEGAL_INGESTION.md` | `keep` as migration |
| `docs/DATA_TRANSFORMATION_MIGRATION_SUMMARY.md` | processors docs | `historical` | Processors migration guides under `docs/guides/processors/` | `move-to-archive` |
| `docs/DEPRECATION_SCHEDULE.md` | product / packaging | `review-needed` | Single deprecation authority after merge | Merge with timeline |
| `docs/DEPRECATION_TIMELINE.md` | product / packaging | `duplicate` / `review-needed` | `DEPRECATION_SCHEDULE.md` (or reverse after review) | `merge-then-archive` |
| `docs/migration_docs/**` | migration / tooling | `historical` (corpus) | Current CLI/MCP ops guides | `keep` under migration_docs or move whole tree to archive |
| `docs/migration_docs/*_OLD.md`, `CLAUDE.md.backup` | migration | `historical` / backup | Parent non-`_OLD` peer if any | `keep` or delete-after-review only if bit-identical to git history |

### 2.6 Other high-value root pages (selected)

| Unit | Owner | Status | Canonical replacement | Future move/delete review |
| --- | --- | --- | --- | --- |
| `docs/OPTIMIZERS_QUICK_START.md` | optimizers | `duplicate` / `review-needed` | `docs/optimizers/SELECTION_GUIDE.md` + CLI guide | Point root to cluster; archive root copy |
| `docs/QUERY_OPTIMIZER_MODULARIZATION_PLAN.md` | optimizers | `historical` / `plan` | Optimizers architecture guides | `move-to-archive` |
| `docs/OPTIMIZATION_LOOP_ARCHITECTURE.md` | knowledge / optimizers | `review-needed` | `docs/architecture/knowledge/OPTIMIZATION_LOOPS.md` | Prefer architecture leaf |
| `docs/QUICK_START_NEW_ARCHITECTURE.md` | architecture | `historical` | `docs/architecture/README.md` + getting started | `move-to-archive` |
| `docs/MULTIMEDIA_ARCHITECTURE_ANALYSIS.md` | processors | `historical` / `review-needed` | `FILE_AND_MULTIMEDIA.md` | `move-to-archive` after extract |
| `docs/MULTIMEDIA_STRUCTURE_REVIEW.md` | processors | `historical` | Same | `move-to-archive` |
| `docs/CORE_MODULES_API.md` | API | `review-needed` / `duplicate` | `docs/api/*` domain pages | Demote when domain maps land |
| `docs/CORE_OPERATIONS_GUIDE.md` | core ops | `review-needed` | `docs/api/CORE_OPERATIONS_API.md` + user guide | Merge or point |
| `docs/CROSS_CUTTING_INTEGRATION_GUIDE.md` | architecture | `review-needed` | `INTEGRATION_BOUNDARIES.md` | Prefer architecture leaf |
| `docs/GRAPHRAG_CONSOLIDATION_GUIDE.md` | knowledge | `review-needed` | `docs/architecture/knowledge/GRAPHRAG.md` | Refresh or archive |
| `docs/GRAPH_STORAGE_INTEGRATION.md` | storage / knowledge | `review-needed` | Storage + knowledge leaves | Classify after code check |
| `docs/LEGAL_*`, `AGENTIC_LEGAL_SCRAPER_DAEMON.md` | legal / logic | `review-needed` | Architecture logic legal constraints + package legal scrapers | Split runbooks vs plans |
| `docs/WEB_ARCHIVING_UNIFIED_API_*` | web-archiving | `historical` / `plan` | Web archiving architecture leaf | `move-to-archive` plans after ship |
| `docs/profile_g_datasets_provider.md` | Profile G / runtime | `review-needed` | `docs/architecture/runtime/PROFILE_G_PLANNING_AND_EVIDENCE.md` | Point to architecture |
| `docs/unified_dashboard.md` | ops / UI | `review-needed` | Ops dashboards under `docs/dashboards/` if still shipped | Classify against code |
| `docs/root_EXTRACTION_CONFIG_GUIDE.md` | extraction docs | `duplicate` | `docs/EXTRACTION_CONFIG_GUIDE.md` | `merge-then-archive` |
| `docs/EXTRACTION_CONFIG_GUIDE.md` | extraction docs | `review-needed` | Processing guides after refresh | `keep` or promote |
| `docs/TESTING_STRATEGY.md` | test docs | `review-needed` | Developer testing evidence guide | Refresh |
| `docs/PERFORMANCE_*`, `HOTPATH_*`, `PROFILING_*` | performance | `historical` / `review-needed` | Ops performance guides | Date and demote undated |

---

## 3. Versioned, old, and backup variants

### 3.1 Versioned plan series (treat series as units)

| Unit | Count / span | Owner | Status | Canonical replacement | Future move/delete review |
| --- | --- | --- | --- | --- | --- |
| `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v*.md` | 21 files (`v2`–`v22`) | logic / archive | `historical` (entire series); latest is still **not** product truth | `docs/architecture/logic/*` current leaves; IR plans under `docs/architecture/*_PLAN.md` only as **plan** | `move-to-archive` as one directory later; keep git history; do **not** promote `v22` to architecture |
| `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v*.md` | 30+ | archive | `historical` | Protected documentation refresh plan (read-only) | `keep` (already archived) |
| `docs/archive/reorganization/MASTER_REFACTORING_PLAN_2026_v4.md` | 1 | archive | `historical` | Same | `keep` |
| `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN.md` vs `_V2.md` | pair | processors | `historical` / `superseded` (v1 by v2 for plan intent) | Processing architecture + data-transform guides | Archive both after processing wave; neither is live architecture |
| `docs/guides/legal_data/HYBRID_LEGAL_V2_*` / `V3_*` | versioned plans | legal | `historical` / `plan` | Architecture logic legal + security leaves | Keep until legal program closes; not product nav |
| `docs/MIGRATION_GUIDE_V2.md` | versioned name | migration | `duplicate` | §2.5 | See §2.5 |
| `docs/security_verification/security_ir_v1_compatibility.md` | versioned compat | security | `historical` / compatibility | Current security verification policy docs | `banner-in-place` |

### 3.2 Explicit old / backup / copy artifacts

| Unit | Owner | Status | Canonical replacement | Future move/delete review |
| --- | --- | --- | --- | --- |
| `ipfs_datasets_py/vector_stores/README_OLD.md` | storage package | `historical` / `superseded` | Package `vector_stores/README.md` + architecture retrieval/storage leaves | `delete-after-review` only if content fully superseded; else move under package ARCHIVE |
| `ipfs_datasets_py/processors/multimedia/omni_converter_mk2/CLAUDE_old.md` | multimedia package | `historical` | Active package README / design docs under review | `keep` near package or package archive |
| `ipfs_datasets_py/search/search_embeddings.py.backup` | search (code backup) | `historical` (non-doc) | Live `search_embeddings` module | Code hygiene task; out of docs move scope |
| `docs/migration_docs/CLAUDE.md.backup` | migration | `historical` | `docs/migration_docs/CLAUDE.md` | `delete-after-review` if identical to git |
| `docs/migration_docs/MIGRATION_VERIFICATION_*_OLD.md` | migration | `historical` | Non-`_OLD` verification peers if retained | `keep` with historical banner |
| `docs/logic/archive/code_backups/**` | logic | `historical` | Live `ipfs_datasets_py/logic/` | `keep` in archive |
| `docs/archived_stubs/**/*copy*_stubs.md` | stubs | `generated` + `historical` | Live modules | `keep` in archived_stubs |
| `* copy.py` / workflow copies under package | engineering | `review-needed` (code) | Canonical module names | Not a docs archive task |

---

## 4. Competing architecture documentation

Prefer **`docs/architecture/`** domain leaves and Accepted ADRs over root dumps,
static catalogs, and package session narratives. Package-local MCP ADR **bodies**
remain canonical for MCP design decisions until a dedicated relocation task.

### 4.1 Architecture tree (already labeled on the hub)

| Unit | Owner | Status | Canonical replacement | Future move/delete review |
| --- | --- | --- | --- | --- |
| `docs/architecture/{SYSTEM_CONTEXT,DOMAIN_MAP,END_TO_END_DATA_FLOW,DEPENDENCY_AND_INITIALIZATION,INTEGRATION_BOUNDARIES,RUNTIME_ENTRYPOINTS,WALLET_TRUST_AND_PRIVACY}.md` | architecture | `current` | — | `keep` |
| `docs/architecture/{processing,storage,retrieval,knowledge,logic,mcp,runtime}/**` leaves | domain owners | `current` | — | `keep` |
| `docs/architecture/decisions/ADR-001`…`ADR-007` | architecture | `current` (Accepted) | — | `keep` |
| `docs/architecture/decisions/MCP_ADR_RECONCILIATION.md` | architecture / mcp | `current` | Package MCP ADR bodies | `keep` |
| `docs/architecture/*_PLAN.md`, `*.objectives.md`, `*.todo.md`, `semantic_roundtrip_canonical_compiler.md` | domain plan owners | `plan` | Matching `current` logic/MCP leaves for shipped behavior | `keep` as plan; never promote without ADR/guide |
| `docs/architecture/project_structure.md` | architecture | `historical` | `DOMAIN_MAP.md` + `developer_guides/REPOSITORY_MAP.md` | `banner-in-place` → `move-to-archive` |
| `docs/architecture/submodule_*.md` | architecture | `historical` | `INTEGRATION_BOUNDARIES.md` | `move-to-archive` |
| `docs/architecture/github_actions_*.md` | ops / CI | `historical` | Ops deployment guides | `move-to-archive` or relocate under guides/operations |

### 4.2 Competing domain hubs (docs vs package)

| Unit | Owner | Status | Canonical replacement | Future move/delete review |
| --- | --- | --- | --- | --- |
| `docs/logic/**` (267 md) excluding versioned plans | logic docs | **Split**: user/architecture candidates `review-needed`; many session files `historical` | `docs/architecture/logic/*` for design; one API + one architecture under `docs/logic/` after dedup | Dedup `ARCHITECTURE.md` vs `logic_ARCHITECTURE.md`; `API_REFERENCE.md` vs `logic_API_REFERENCE.md` |
| `docs/logic/ARCHITECTURE.md` vs `logic_ARCHITECTURE.md` | logic | `duplicate` pair | Single architecture page + `docs/architecture/logic/README.md` | `merge-then-archive` loser |
| `docs/logic/API_REFERENCE.md` vs `logic_API_REFERENCE.md` | logic | `duplicate` pair | Single API reference + future `docs/api/domains/` | `merge-then-archive` loser |
| `docs/logic/QUICKSTART.md` | logic | `review-needed` | Getting started + logic architecture | Refresh |
| `docs/optimizers/**` (76 md) | optimizers | **Split**: selection/how-to `review-needed`→`current`; session/report `historical` | `SELECTION_GUIDE.md`, `HOW_TO_ADD_NEW_OPTIMIZER.md`, architecture knowledge optimization loops | Demote session infinite-todos |
| `docs/guides/processors/PROCESSORS_ARCHITECTURE.md` | processors | `current` candidate (`refresh-and-surface` until fully absorbed) | `docs/architecture/processing/*` | Keep until processing wave fully owns narrative |
| `docs/guides/processors/*SUMMARY*`, `*STATUS*`, `*CHECKLIST*`, `*VISUAL*`, refactoring decks | processors | `historical` | Processing architecture leaves | `move-to-archive` |
| Root MCP vs `ipfs_datasets_py/mcp_server/docs/**` | mcp | **Split** — see package map §3 | Architecture mcp leaves + package ADRs | No dual decision authority |
| `docs/tdfol/**` RST + `_build` | logic / TDFOL | Source `review-needed`; build `generated` | Package TDFOL + architecture logic external provers | Prefer rebuild over committed HTML authority |

### 4.3 Already-archived historical trees

| Unit | Owner | Status | Canonical replacement | Future move/delete review |
| --- | --- | --- | --- | --- |
| `docs/archive/root_status_reports/` (73) | archive | `historical` | Product entry + architecture hub | `keep` |
| `docs/archive/completion_reports/` (59) | archive | `historical` | Same | `keep` |
| `docs/archive/reorganization/` (43) | archive | `historical` | Information architecture + program plan | `keep` |
| `docs/archive/knowledge_graphs/` (37) | archive | `historical` | `docs/architecture/knowledge/*` | `keep` |
| `docs/archive/processors/` (28) | archive | `historical` | Processing architecture | `keep` |
| `docs/archive/deprecated/` (8) | archive | `historical` / `superseded` | Named replacements in each file if any | `keep` |
| `docs/reports/**` | archive / program | `historical` | Maintenance evidence artifacts | `keep`; fix broken relative links opportunistically |
| `docs/archived_stubs/**` | stubs | `generated` + `historical` | Live source | `keep` |
| `ipfs_datasets_py/mcp_server/ARCHIVE/**` | mcp package | `historical` | Architecture mcp + package ADRs | `keep` (do not promote into product nav) |
| `ipfs_datasets_py/mcp_server/docs/history/**` | mcp package | `historical` | Same | `keep` |
| `ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/ARCHIVE/**` | legal tools | `historical` | Legal guides | `keep` |

---

## 5. Generated builds and machine-produced references

| Unit | Owner | Status | Canonical replacement | Future move/delete review |
| --- | --- | --- | --- | --- |
| `ipfs_datasets_py/**/*_stubs.md` (~45) | code owners / docs tooling | `generated` | Live modules + hand API maps | Regenerate or leave; never cite for design |
| `docs/archived_stubs/**` (~124) | documentation-governance | `generated` + `historical` | Live modules | `keep` |
| `docs/auto_generated_stubs/README.md` | documentation-governance | `generated` (policy) | Stub lifecycle policy only | `keep` policy note; tree empty of active stubs |
| `docs/tdfol/_build/**` (~202 html/doctree) | logic / docs tooling | `generated` | `docs/tdfol/**/*.rst` sources | Prefer rebuild; consider untracking rebuildable HTML later |
| `docs/tdfol/**/*.rst` (~40) | logic | Source for `generated` | Architecture logic + package TDFOL | Refresh if product surface remains |
| Tracked `docs/**/*.html` / `*.doctree` | docs tooling | `generated` | Markdown / RST sources | Do not hand-edit |
| MkDocs `site/` | docs tooling | `generated` (absent when not built) | `docs/` + `mkdocs.yml` | **Never** edit `site/` as source; rebuild |
| `docs/dashboards/*.html` | ops / UI | `review-needed` / demo | Ops runbooks if still supported | Classify demos vs shipped UI |
| `docs/performance_snapshots/**` | performance | `historical` evidence | Ops performance guides | `keep` as dated evidence |
| `docs/benchmarks/**` | evaluation owners | **Split**: plans/results `historical` or evidence; policies `review-needed` | Domain architecture + evaluation contracts | Keep dated results; demote undated “final” language |

---

## 6. Package-local documentation (summary)

Full corpus inventory and six-label map live in
[`PACKAGE_LOCAL_DOCUMENTATION_MAP.md`](PACKAGE_LOCAL_DOCUMENTATION_MAP.md).
This section only records **legacy disposition** outcomes needed for navigation
and future archive moves.

| Unit | Owner | Status | Canonical replacement | Future move/delete review |
| --- | --- | --- | --- | --- |
| `ipfs_datasets_py/mcp_server/docs/adr/ADR-001`…`006` | mcp-runtime | `current` (decision bodies) | Indexed via `docs/architecture/decisions/MCP_ADR_RECONCILIATION.md` | **Do not** duplicate bodies; relocation only with index update |
| `ipfs_datasets_py/mcp_server/docs/README.md` | mcp-runtime | `review-needed` → surface | `docs/architecture/mcp/README.md` | Pointer from hub; refresh body in place |
| `ipfs_datasets_py/mcp_server/docs/DOCUMENTATION_PLAN.md` | mcp | `historical` / `plan` | Program documentation plan (protected) | `keep` |
| `ipfs_datasets_py/mcp_server/ARCHIVE/**` | mcp | `historical` | Architecture mcp leaves | `keep` |
| `ipfs_datasets_py/mcp_server/tools/**/README.md` | mcp tools | `review-needed` | Tool lifecycle architecture + live registry | Refresh counts from code |
| `ipfs_datasets_py/logic/**/README.md` | logic | `review-needed` / pointer | `docs/architecture/logic/*` | Thin package READMEs |
| `ipfs_datasets_py/optimizers/**/README.md` | optimizers | pointer | `docs/optimizers/*` | Thin pointers |
| `ipfs_datasets_py/processors/**` design TODOs / omni_converter PRDs | processors | `review-needed` / `historical` | Processing architecture + engines guide | Do not promote session TODOs |
| Package `CHANGELOG.md` / `TODO.md` beside code | local owners | `historical` / `review-needed` | Product CHANGELOG / issue tracker | Not architecture authority |
| Package `*_stubs.md` | tooling | `generated` | Source modules | Regenerate |

---

## 7. Prioritized broken-link clusters

Source measurement (this worktree):

```bash
python docs/maintenance/check_docs.py --root docs --checks links --fail-on never --json-report /tmp/docs_links.json
```

Observed summary at last verification: **1568** files scanned; **8** `error`;
**276** `allowlisted`; **276** `info` (external links skipped, no network).

### 7.1 Priority P0/P1 — hard errors on maintained surfaces (fix or allowlist-token)

| Cluster / path | Count | Owner | Status (link defect class) | Canonical replacement / fix target | Future move/delete review |
| --- | ---: | --- | --- | --- | --- |
| `docs/architecture/ARCHITECTURE_GUIDE_TEMPLATE.md` placeholder `decisions/ADR-NNN-....md` | 1 | architecture | `review-needed` (template example, not a real path) | Use `decisions/ADR_TEMPLATE.md` or a real ADR path in examples | Fix template link text; not an archive candidate |
| `docs/guides/THEOREM_PROVER_INTEGRATION_GUIDE.md` example anchors (`proposition`, long exercise slug) | 4 | logic / guides | `review-needed` | Architecture `logic/EXTERNAL_PROVERS.md` + real anchors or fence as non-links | Repair examples; do not delete guide without replacement |
| `docs/security_verification/production_release_decision_policy.md` → missing `security_ir_artifacts/...json` | 1 | security | `review-needed` | In-tree security policy JSON if still shipped; else document path as external | Fix path or mark historical policy |
| `docs/reports/DOCS_ACTION_CHECKLIST_2026_01_31.md` → `archive/deprecated/` | 2 | archive / reports | `historical` host page | `docs/archive/deprecated/` with correct relative depth | Fix relative links or leave allowlisted as historical |

### 7.2 Priority P2 — large allowlisted clusters (historical hosts)

Allowlisted findings do **not** fail the default gate; they still block treating
those trees as navigable product docs.

| Cluster | Approx. allowlisted link findings | Owner | Status | Canonical replacement | Future move/delete review |
| --- | ---: | --- | --- | --- | --- |
| `docs/archive/**` (all subtrees) | ~175 | archive | `historical` hosts | Product entry + architecture hub | `keep`; optional link scrub only if someone reuses text |
| `docs/logic/**` (incl. CEC, zkp, TDFOL subdocs) | ~67 | logic | Mix `historical` + `review-needed` hosts | `docs/architecture/logic/*` | Prefer fixing only pages promoted to `current`; archive rest |
| `docs/knowledge_graphs/**` (incl. archive) | ~32 | knowledge | `historical` / `review-needed` | `docs/architecture/knowledge/*` | Archive stale subgraph docs; fix if kept in nav |
| `docs/archived_stubs/**` | ~2+ | stubs | `generated` + `historical` | Live processors guides | `keep` |
| Other guides/implementation/plans noise | remainder | various | mostly `historical` | Domain leaves | No bulk delete |

### 7.3 Priority P3 — external / info

| Cluster | Owner | Status | Canonical replacement | Future move/delete review |
| --- | --- | --- | --- | --- |
| External `https://` links (info, not fetched) | page owners | N/A | Prefer stable project URLs; re-check in provisioned network gate | No local move |

### 7.4 Link policy for future cleanup tasks

1. **Fix errors on `current` / navigated pages first** (P0/P1).
2. **Do not expand allowlists** to hide failures on maintained pages
   (`VALIDATION_RUNBOOK.md`).
3. **Historical trees** may keep broken internal links until moved; when moving,
   either fix relative paths or accept allowlist under archive prefixes.
4. **Replacement** for almost all historical link targets is a **domain hub**,
   not another completion report.

---

## 8. Crosswalk: status → writer / agent action

| If status is… | Writers and agents must… |
| --- | --- |
| `current` | Cite as home; refresh against `SOURCE_AUTHORITY` ranks 1–5; keep in nav when appropriate |
| `superseded` | Follow **replacement**; add banner; do not expand the old body |
| `historical` | Do not cite as live status; use only for provenance; eventual `move-to-archive` |
| `duplicate` | Pick one survivor; convert loser to pointer or archive after merge |
| `review-needed` | Do not promote to nav spine until classified against code/tests |
| `generated` | Regenerate from source; never hand-author decisions there |
| `plan` | Treat as intent; requires ADR or `current` guide before “shipped” language |

---

## 9. Future move/delete review queue (non-destructive schedule)

Recommended **later** reviewed tasks (not performed here), ordered by risk
reduction:

| Order | Action | Units | Prerequisite |
| --- | --- | --- | --- |
| 1 | Banner high-traffic root historical pages that still rank in search | Phase complete set, `PROJECT_STATUS_FINAL.md`, IPLD “PROJECT_COMPLETE”, MCP status | This map |
| 2 | Collapse navigation index duplicates | `DOCUMENTATION_INDEX_COMPLETE`, `root_DOCUMENTATION_INDEX`, domain indexes | IPFSDOC-095 |
| 3 | Move root phase/session/completion cluster into `docs/archive/completion_reports/` or `root_status_reports/` | §2.2–§2.4 historical rows | Banner + inbound link retarget from `current` pages only |
| 4 | Dedup logic architecture/API pairs and versioned plan series | §3.1, §4.2 | Architecture logic leaves stable |
| 5 | Demote architecture-tree historical MCP catalogs and submodule narratives | §4.1 historical rows | Hub already labels them |
| 6 | Package-local ARCHIVE stay put; optional pointer-only cleanup | §6 | Package map updates |
| 7 | Generated Sphinx HTML untrack or CI rebuild policy | §5 | Docs tooling owner decision |
| 8 | **Delete** only bit-identical backups after human review | `*.backup`, `*_OLD` when identical to git | Explicit task; update this map |

**Delete is never the default.** Prefer `move-to-archive` + git history.

---

## 10. Relationship to peer maintenance artifacts

| Artifact | Relationship |
| --- | --- |
| [`PACKAGE_LOCAL_DOCUMENTATION_MAP.md`](PACKAGE_LOCAL_DOCUMENTATION_MAP.md) | Authority/disposition for package-local and competing hubs; this map expands **legacy** historical/duplicate routing and root phase clusters |
| [`INFORMATION_ARCHITECTURE.md`](INFORMATION_ARCHITECTURE.md) | Lifecycle states, deprecation and archive **policy**; this map is the instance inventory |
| [`SOURCE_AUTHORITY.md`](SOURCE_AUTHORITY.md) | Rank order; historical rank 7 material is classified here |
| [`DRIFT_AND_CLAIM_MATRIX.md`](DRIFT_AND_CLAIM_MATRIX.md) | Claim-level staleness; completion claims route to this disposition map |
| [`COVERAGE_MATRIX.md`](COVERAGE_MATRIX.md) | Coverage gaps; G-P1-08 closed by publishing this file |
| [`CURRENT_STATE_BASELINE.md`](CURRENT_STATE_BASELINE.md) | Count authority for inventory sizes |
| [`VALIDATION_RUNBOOK.md`](VALIDATION_RUNBOOK.md) | How link/metadata gates treat archive allowlists |
| `docs/architecture/README.md` | Architecture hub lifecycle labels; historical architecture paths mirrored in §4 |

---

## 11. Reproducible commands

```bash
# Root page inventory
ls docs/*.md | wc -l

# Phase/status-like root names
ls docs/*.md | rg -i 'PHASE|STATUS|COMPLETE|SESSION|SUMMARY|REPORT'

# Versioned logic plans
ls docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v*.md | wc -l

# Archive sizes
for d in docs/archive/*/; do printf '%s %s\n' "$(find "$d" -type f | wc -l)" "$d"; done

# Package-local and generated
find ipfs_datasets_py -name '*.md' | wc -l
find ipfs_datasets_py -name '*_stubs.md' | wc -l
find docs/tdfol/_build -type f 2>/dev/null | wc -l
test -d site && echo site_present || echo site_absent

# Link clusters (offline)
python docs/maintenance/check_docs.py --root docs --checks links --fail-on never --json-report /tmp/docs_links.json
```

### Validation for this deliverable

```bash
test -s docs/maintenance/LEGACY_DISPOSITION.md && \
  rg -n 'current|superseded|historical|duplicate|review-needed|replacement' \
    docs/maintenance/LEGACY_DISPOSITION.md
```

---

## 12. Acceptance checklist (IPFSDOC-094)

| Criterion | Evidence in this document |
| --- | --- |
| High-priority root plans/status/phase reports classified | §2.2–§2.6 with owner, status, replacement, future review |
| Versioned / old / backup variants classified | §3 |
| Competing architecture docs classified | §4 |
| Generated builds classified | §5 |
| Package-local docs classified (summary + peer map) | §6 + `PACKAGE_LOCAL_DOCUMENTATION_MAP.md` |
| Prioritized broken-link clusters | §7 with P0–P3 and measured counts |
| Owner, status, canonical replacement, future move/delete review on rows | Table columns throughout |
| No bulk move or delete in this task | Explicit non-actions + §9 queue only |
| Vocabulary includes current / superseded / historical / duplicate / review-needed / replacement | Disposition vocabulary + tables |

---

## 13. Change control

| Field | Value |
| --- | --- |
| Created for | `IPFSDOC-094` — Publish the legacy duplicate and historical disposition map |
| Interface | `LegacyDocumentationDisposition@1` |
| Update when | Any reviewed migrate/merge/archive of rows in this map; after major nav rebuild (IPFSDOC-095+); after new baseline recount |
| Forbidden without review | Bulk deletion of historical Markdown; silent removal of Accepted ADR bodies; treating phase completion reports as release evidence |
