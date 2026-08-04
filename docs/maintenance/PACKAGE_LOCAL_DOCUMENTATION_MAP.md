# Package-local, generated, and competing documentation authorities

| Field | Value |
| --- | --- |
| Interface | `DocumentationAuthorityMap@1` |
| Task | `IPFSDOC-004` |
| Status | `evidence` |
| Owner | documentation-governance |
| Source of truth | Live tree under `ipfs_datasets_py/**/*.md`, `docs/`, `mkdocs.yml`, `docs/tdfol/`, sibling maintenance evidence (`CURRENT_STATE_BASELINE.md`, `INFORMATION_ARCHITECTURE.md`) |
| Last verified | 2026-08-03 |
| Measured tree | worktree inventory aligned with `IPFSDOC-001` baseline (`ipfs_datasets_py/**/*.md` = 387; `docs/**/*.md` = 1476) |
| Audience | maintainers, documentation authors, implementation agents |
| Non-goals | This map does **not** move, delete, rename, or rewrite inventoried files. Destructive disposition is deferred to later reviewed tasks. |

## Purpose

Parallel documentation lanes must not invent a second authority where useful
material already lives under the package or under a competing `docs/` hub.
This map:

1. Inventories **package-local Markdown** under `ipfs_datasets_py/`.
2. Inventories **generated references and build output** (stubs, Sphinx `_build`,
   MkDocs `site/`, committed HTML/RST artifacts).
3. Inventories **competing** logic, optimizer, processor, and MCP guides across
   package-local trees and `docs/`.
4. Records the **six existing MCP ADRs** under
   `ipfs_datasets_py/mcp_server/docs/adr/`.
5. Assigns each corpus or high-value page a **disposition** so later tasks
   refresh, pointer, migrate, or demote—without relocating files in this task.

## How to read this document

| Column / term | Meaning |
| --- | --- |
| **Corpus** | A directory, naming pattern, or named competing cluster treated as one authority unit |
| **Count** | Markdown (or file) count from filesystem inventory in this worktree; re-run §Reproducible commands after tree change |
| **Disposition** | One of the six labels in [Disposition vocabulary](#disposition-vocabulary) |
| **Canonical home (target)** | Where current-product authority should live after program convergence (may already exist, or is owned by a later task) |
| **Action (later)** | Non-destructive follow-up for agents; **not** authorization to move/delete now |

Authority order when sources disagree (same as program plan and
`INFORMATION_ARCHITECTURE.md`):

1. executable tests and schemas that define a contract;
2. current implementation and packaging/configuration metadata;
3. current operator configuration and deployment manifests;
4. accepted architecture decision records;
5. maintained guides;
6. historical plans, completion reports, generated summaries, and archive material.

---

## Disposition vocabulary

Every row uses exactly one disposition. These labels are inventory outcomes for
legacy and package-local material; they align with lifecycle states in
`docs/maintenance/INFORMATION_ARCHITECTURE.md` but are more operational for
routing work.

| Disposition | May be cited as current authority? | Meaning | Typical next step |
| --- | --- | --- | --- |
| `canonical` | **Yes** (for its scoped concern) | Body of record for the concern; maintain in place or treat as product authority until a named supersession | Keep fresh; link from hubs; do not duplicate body elsewhere |
| `refresh-and-surface` | After refresh only | Useful, domain-proximate content that is incomplete, drifted, or poorly discoverable from `docs/` | Refresh against current code, then surface via hub links / nav (without inventing a second full body) |
| `pointer` | No (except as navigation) | Secondary copy, package README, or future thin stub that must route to a named canonical home | Add banner/link to canonical; avoid expanding the secondary body |
| `generated` | Only for regenerated facts | Machine-produced listings, stubs, Sphinx/MkDocs build products | Regenerate from source; never hand-author design rationale there |
| `historical` | **No** | Superseded plans, phase reports, ARCHIVE trees, completion-era narrative | Preserve; demote from nav; do not restate as current status |
| `review-needed` | **No** until classified | Mixed, undated, or multi-claim pages not yet safe to promote or demote | Classify against current tree before citing; prefer code/tests over prose |

### Future actions (not dispositions)

Later tasks may **migrate** (relocate or consolidate bodies under an agreed
canonical home), **merge** (combine overlapping pages), or **archive** (move
into `docs/archive/` with a disposition record). This task only **maps**. It
does not migrate, merge, archive, or delete.

---

## 1. Inventory summary

| Surface | Count | Kind | Notes |
| --- | ---: | --- | --- |
| Repo tracked `*.md` | 2212 | Baseline fact (`IPFSDOC-001`) | Includes package, docs, tests, archive |
| `docs/**/*.md` | 1476 | Baseline fact | Maintained + historical + plans + reports |
| `ipfs_datasets_py/**/*.md` | **387** | Package-local | Primary scope of this map |
| Package `README.md` | 128 | Package-local | Module entry READMEs |
| Package `*_stubs.md` | **45** | Generated-adjacent | Signature dumps beside source |
| `ipfs_datasets_py/mcp_server/` Markdown | **176** | Package-local | Largest package doc concentration |
| `ipfs_datasets_py/mcp_server/docs/` | **47** md | Package-local curated docs | Includes **6 ADRs** |
| `ipfs_datasets_py/mcp_server/ARCHIVE/` | **37** md | Historical | Refactoring/session archive |
| `ipfs_datasets_py/mcp_server/tools/**/*.md` | **84** | Mixed | Tool-category READMEs + legal ARCHIVE |
| `ipfs_datasets_py/processors/**/*.md` | **95** | Package-local | Dominated by `omni_converter_mk2` (~60) |
| `ipfs_datasets_py/logic/**/*.md` | **20** | Package-local | Subsystem READMEs; product guides live under `docs/logic/` |
| `ipfs_datasets_py/optimizers/**/*.md` | **4** | Package-local | Thin; product guides under `docs/optimizers/` |
| `docs/logic/**/*.md` | **267** | Competing hub | Versioned plans + user/architecture guides |
| `docs/optimizers/**/*.md` | **76** | Competing hub | Selection, architecture, API-adjacent material |
| `docs/guides/processors/**/*.md` | **29** | Competing hub | Architecture + refactoring + migration set |
| MCP-named pages under `docs/` (non-archive sample) | 30+ | Competing cluster | Root, architecture, guides, reports, plans |
| `docs/archived_stubs/` | **124** files | Historical / generated | Relocated stubs |
| `docs/auto_generated_stubs/` | **1** (README) | Generated policy | Stub home is empty of active stubs |
| `docs/tdfol/_build/` | **202** files | Generated | Committed Sphinx HTML + doctrees |
| `docs/tdfol/**/*.rst` | **40** | Source for generated | Sphinx sources |
| MkDocs `site/` | **absent** | Generated (not present) | Build output only when `mkdocs build` runs |
| `docs/api/` hand pages | **2** | Mixed | Navigated API spine in `mkdocs.yml` |

---

## 2. Package-local Markdown by domain

### 2.1 Concentration table

| Package domain | `*.md` | Dominant content | Disposition (corpus default) | Canonical home (target) |
| --- | ---: | --- | --- | --- |
| `mcp_server/` | 176 | Curated docs, ADRs, ARCHIVE, tool READMEs | **Split** — see §3–§4 | `docs/architecture/mcp/` + `docs/architecture/decisions/` (later); ADR bodies remain package-local until IPFSDOC-016 |
| `processors/` | 95 | omni_converter design, legal scrapers notes, multimedia READMEs | **Split** — see §5.3 | `docs/guides/processors/` architecture + domain guides; package READMEs for subpackage detail |
| `audit/` | 26 | Mostly `*_stubs.md` + README/TODO/CHANGELOG | `generated` for stubs; README `refresh-and-surface` | Future `docs/architecture/` / ops security leaves; stubs stay generated |
| `logic/` | 20 | Subsystem READMEs + archive notes | `pointer` / `refresh-and-surface` | `docs/logic/` + future `docs/architecture/logic/` |
| `ml/` | 17 | LLM/embeddings stubs + READMEs | `generated` + `review-needed` | Future ML/embeddings architecture + API domains |
| `knowledge_graphs/` | 15 | Subpackage READMEs | `refresh-and-surface` | `docs/knowledge_graphs/` + architecture knowledge leaves |
| `vector_stores/` | 12 | README + stubs + TODO/CHANGELOG | `refresh-and-surface` / `generated` / `historical` (`README_OLD.md`) | IPLD/vector guides under `docs/` root + architecture storage |
| `utils/` | 9 | Mixed READMEs + stubs | `review-needed` | Developer guides / API domains as needed |
| `search/` | 5 | READMEs + stubs | `review-needed` | Retrieval architecture leaves |
| `optimizers/` | 4 | Module READMEs | `pointer` | `docs/optimizers/` + `docs/api/OPTIMIZERS_API_REFERENCE.md` |
| `config/` | 3 | Config notes | `review-needed` | `docs/configuration.md` (product entry) |
| `error_reporting/` | 2 | Package notes | `review-needed` | Ops / developer troubleshooting |
| `skills/` | 2 | Skill references | `review-needed` | Agent-facing developer guides |
| `static/` | 1 | Asset note | `historical` / incidental | Not product documentation |
| Other package domains | 0 | No package-local Markdown | n/a | Code + future architecture leaves only |

### 2.2 Package-local README pattern

| Pattern | Count | Disposition | Guidance |
| --- | ---: | --- | --- |
| `ipfs_datasets_py/**/README.md` | 128 | `pointer` or `refresh-and-surface` | Prefer short module purpose, install/import notes, and links to the `docs/` canonical guide. Do not grow competing architecture narratives in deep package leaves without a map update. |
| `CHANGELOG.md` / `TODO.md` beside code | various | `historical` or `review-needed` | Changelogs are evidence of past change; TODOs are plan-like. Neither is product architecture authority. |
| `*_stubs.md` beside modules | 45 | `generated` | Treat as signature dumps; regenerate or archive. Do not cite for behavior contracts. |

---

## 3. MCP package-local documentation (detail)

### 3.1 Curated tree: `ipfs_datasets_py/mcp_server/docs/`

**Count:** 47 Markdown files (+ one Python template under
`development/tool-templates/`).

| Subtree / file | Role | Disposition | Notes / later action |
| --- | --- | --- | --- |
| `docs/README.md` | Package docs hub: request flow, module map | `refresh-and-surface` | Strong local overview; surface from future `docs/architecture/mcp/` without duplicating body |
| `docs/DOCUMENTATION_PLAN.md` | Docs plan for MCP package | `historical` / plan-like | Not product behavior authority |
| `docs/adr/` (6 ADRs) | Accepted MCP design decisions | **`canonical` (bodies)** until IPFSDOC-016 relocates or pointers | See §4; do **not** recreate bodies under `docs/` |
| `docs/architecture/` | Dual-runtime, MCP++ alignment narratives | `refresh-and-surface` | Overlaps ADR-002 / ADR-006; prefer ADR as decision authority; architecture pages as exposition |
| `docs/api/` | Tool reference notes | `refresh-and-surface` | Competing with root `docs/MCP_TOOLS_GUIDE.md` and architecture catalogs—see §5.1 |
| `docs/development/` | Tool patterns + templates | `refresh-and-surface` | Developer extension material; route from developer guides |
| `docs/guides/` | Cookbook, P2P migration, performance | `refresh-and-surface` | Operator/developer how-to; surface selectively |
| `docs/history/` | Phase and refactoring summaries (~23 md) | `historical` | Preserve; do not cite as current status |
| `docs/testing/` | Dual-runtime testing strategy | `refresh-and-surface` | Feed testing/evidence developer guide |
| `docs/tools/README.md` | Tools docs index | `pointer` | Point to tool registry reality + catalog after refresh |

### 3.2 MCP package root and ARCHIVE

| Path | Count / files | Disposition | Notes |
| --- | --- | --- | --- |
| `ipfs_datasets_py/mcp_server/README.md` | 1 | `refresh-and-surface` | Primary package entry for MCP server; should stay discoverable |
| `QUICKSTART.md`, `SECURITY.md`, `THIN_TOOL_ARCHITECTURE.md`, `PHASES_STATUS.md`, `CHANGELOG.md` | 5 | `refresh-and-surface` or `historical` | Thin-tool architecture aligns with ADR-001; phase status is evidence/historical |
| `compat/README.md`, `benchmarks/README.md` | 2 | `pointer` / `review-needed` | Local runtime/compat notes |
| `tools/README.md`, per-tool READMEs | many of 84 | `refresh-and-surface` | Category proximity is valuable; counts must be re-verified against registry |
| `tools/TOOLS_IMPROVEMENT_PLAN_2026.md` | 1 | `historical` | Plan, not current architecture |
| `tools/legal_dataset_tools/ARCHIVE/` | 8 | `historical` | Archive |
| `mcp_server/ARCHIVE/` | 37 | `historical` | Large refactoring/session archive; **do not migrate** into product nav |

### 3.3 Competing MCP guides under `docs/` (authority cluster)

These pages claim overlapping MCP authority with package-local docs. **None are
moved by this task.** Default disposition is classification only.

| Cluster | Example paths | Disposition | Canonical target (program) |
| --- | --- | --- | --- |
| Product / user MCP guides | `docs/MCP_TOOLS_GUIDE.md`, `docs/MCP_QUICKSTART.md`, `docs/MCP_TESTING_GUIDE.md`, `docs/CLI_MCP_INTEGRATION_GUIDE.md`, `docs/CLI_MCP_ALIGNMENT.md` | `refresh-and-surface` or `review-needed` | Future MCP user + operator journeys; one tools guide as primary |
| Architecture / catalog | `docs/architecture/MCP_TOOLS_ARCHITECTURE.md`, `mcp_tools_catalog.md`, `mcp_tools_comprehensive_documentation.md`, `mcp_tools_technical_reference.md`, `docs/MCP_ARCHITECTURE_DIAGRAM.md` | `review-needed` (stale counts common) | `docs/architecture/mcp/` leaves after architecture wave; catalogs re-derived from registry/tests |
| Plans / status / completion | `docs/MCP_REFACTORING_PLAN.md`, `MCP_REFACTORING_SUMMARY.md`, `MCP_IMPLEMENTATION_STATUS.md`, `MCP_PHASES_5_8_PLAN.md`, `MCPPLUSPLUS_INTEGRATION_*.md`, `ENHANCEMENT_12_MCP_COMPLETION.md`, `docs/reports/MCP_*` | `historical` | Archive disposition later; not current status |
| Guides / dashboard | `docs/guides/MCP_*`, `COMPREHENSIVE_MCP_DASHBOARD.md`, `MCP_SYSTEMD_SETUP.md` | `refresh-and-surface` or `historical` | Ops guides that survive refresh; summaries demote |
| Migration-era | `docs/migration_docs/MCP_*` | `historical` | Migration history only |
| Test coverage plans | `docs/implementation/plans/MCP_TOOLS_TEST_COVERAGE_*` | `plan` (treat as non-authority; map as `historical` for product citation) | Planning only |

**Routing rule for MCP:** Decision rationale → package-local
`mcp_server/docs/adr/*` (until IPFSDOC-016 indexes them). Runtime how-it-works →
refresh `mcp_server/docs/README.md` and surface from architecture hub. Tool
inventory → regenerate or re-measure from code/registry; do not trust static
“130+ / 382 tools” prose without verification. Phase completion Markdown →
`historical`.

---

## 4. Existing MCP ADRs (`ipfs_datasets_py/mcp_server/docs/adr/`)

These six ADRs are the **package-local decision authorities** called out by the
documentation refresh plan. Bodies stay in place. IPFSDOC-016 will index and
reconcile them under `docs/architecture/decisions/`; this map forbids
independent recreation or deletion.

| ADR | Title | Stated status | Disposition (this map) | Later reconciliation (IPFSDOC-016) |
| --- | --- | --- | --- | --- |
| `ADR-001-thin-wrapper-pattern.md` | Thin Wrapper Pattern | Accepted (2026-02-20) | **`canonical`** decision body for thin MCP tools | Index + optional `pointer` from `docs/architecture/decisions/`; do not rewrite body in a second tree |
| `ADR-002-dual-runtime.md` | Dual-Runtime (FastAPI + Trio) | Accepted (2026-02-18) | **`canonical`** for dual-runtime decision | Index; exposition may stay in `docs/architecture/dual-runtime.md` package path as `refresh-and-surface` |
| `ADR-003-hierarchical-tool-system.md` | Hierarchical Tool System | Accepted (2026-02-19) | **`canonical`** for hierarchy/meta-tools | Index; catalogs must align with `HierarchicalToolManager` implementation |
| `ADR-004-engine-extraction-pattern.md` | Engine Extraction Pattern | Accepted (2026-02-20) | **`canonical`** for engine placement conventions | Index; cross-link processor/embeddings engine homes |
| `ADR-005-v6-coverage-hardening.md` | v6 Coverage Hardening & Ecosystem Integrations | Accepted (2026-02-22) | **`canonical`** for accepted hardening/integration decisions; metric claims are **evidence-dated** | Index; coverage percentages are not evergreen—re-measure before citing |
| `ADR-006-mcp++-alignment.md` | MCP++ Specification Alignment | Accepted (2026-02-22) | **`canonical`** for MCP++ profile alignment decision | Index; profiles A–E need architecture guide refresh against current code |

### ADR inventory rules

1. **Do not migrate** ADR files in this task. Path
   `ipfs_datasets_py/mcp_server/docs/adr/` remains the body location until a
   dedicated reconciliation task updates indexes and any pointers.
2. **Do not duplicate** ADR sections into new `docs/architecture/decisions/`
   files as full copies. Prefer one body + one index/`pointer`.
3. Package architecture pages that restate ADR decisions are
   `refresh-and-surface` exposition, not a second decision authority.
4. Competing root plans that “decide” MCP architecture without ADR status are
   `historical` or `review-needed`, never silent supersession of Accepted ADRs.

---

## 5. Competing logic, optimizer, and processor authorities

### 5.1 Logic

| Location | Count / role | Disposition | Canonical home (target) |
| --- | --- | --- | --- |
| `ipfs_datasets_py/logic/README.md` | Package entry; links into `docs/logic/` | `pointer` + `refresh-and-surface` | Keep as package entry; product narrative under `docs/logic/` / architecture logic leaves |
| `ipfs_datasets_py/logic/*/README.md` | Subsystem READMEs (fol, deontic, TDFOL, CEC, zkp, intent_ir, external_provers, …) | `refresh-and-surface` | Subsystem detail may remain package-local with architecture pointers |
| `ipfs_datasets_py/logic/docs/archive/` | Archive READMEs | `historical` | Stay archive |
| `docs/logic/` | **267** md: user guides, architecture, ITP hammer contracts, **many versioned** `COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v*.md` | **Split** | User/architecture guides → `refresh-and-surface` then promote carefully; versioned plan series → `historical` (keep latest plan as `plan` only, not product truth) |
| High-value `docs/logic/` candidates | `ARCHITECTURE.md`, `logic_ARCHITECTURE.md`, `API_REFERENCE.md`, `logic_API_REFERENCE.md`, `QUICKSTART.md`, `UNIFIED_CONVERTER_GUIDE.md`, `DOCUMENTATION_INDEX.md`, ITP hammer contract set | `review-needed` (duplicate pairs) | Collapse pairs to one canonical each; until then do not cite both |
| `docs/architecture/LOGIC_*`, `logic_intent_legal_gate.*` | Plans/objectives | `historical` / plan | Not shipped architecture authority |
| `docs/tdfol/` RST + `_build/` | Sphinx TDFOL docs | Source `refresh-and-surface`; build `generated` | Prefer live package `logic/TDFOL` + maintained guides over stale HTML |

**Logic routing rule:** Package subsystem READMEs explain layout near code.
Product behavior and API narrative converge on **one** architecture guide and
**one** API reference under `docs/` (after dedup). Versioned comprehensive
refactoring plans never outrank tests or current package layout.

### 5.2 Optimizers

| Location | Count / role | Disposition | Canonical home (target) |
| --- | --- | --- | --- |
| `ipfs_datasets_py/optimizers/README.md` | Module overview + migration notes (legacy `optimizers.logic` facade) | `refresh-and-surface` | Keep accurate migration notes; link to `docs/optimizers/` |
| `optimizers/common|graphrag|logic_theorem_optimizer/README.md` | Subpackage entries | `pointer` | Point to selection + architecture guides |
| `docs/optimizers/` | **76** md | **Split** | `SELECTION_GUIDE.md`, `ARCHITECTURE_*`, `HOW_TO_ADD_NEW_OPTIMIZER.md`, `CLI_GUIDE.md` → `refresh-and-surface`; session/complete/report/plan files → `historical` |
| `docs/api/OPTIMIZERS_API_REFERENCE.md` | Large API page; **in MkDocs nav** | `refresh-and-surface` (navigated) | Remains navigated API spine until domain API map lands; treat as hand-maintained, verify against code |
| `docs/OPTIMIZERS_QUICK_START.md`, `docs/QUERY_OPTIMIZER_*` (root) | Root duplicates / plans | `review-needed` / `historical` | Prefer `docs/optimizers/` cluster; demote root duplicates later |
| `docs/archived_stubs/*optimizer*` | Stubs | `generated` / `historical` | Do not promote |

**Optimizer routing rule:** Selection and extension guides under
`docs/optimizers/` are the intended user/developer authority after refresh.
Package READMEs stay thin pointers. API detail: navigated
`docs/api/OPTIMIZERS_API_REFERENCE.md` until replaced by domain API pages.

### 5.3 Processors

| Location | Count / role | Disposition | Canonical home (target) |
| --- | --- | --- | --- |
| `docs/guides/processors/PROCESSORS_ARCHITECTURE.md` | Layered architecture; mixed root/core layout note | **`canonical` candidate** → `refresh-and-surface` until architecture wave absorbs it | Future `docs/architecture/processing/`; refresh in place for now |
| `PROCESSORS_ENGINES_GUIDE.md`, `PROCESSORS_MIGRATION_GUIDE.md`, `PROCESSORS_BREAKING_CHANGES.md`, protocol/data-transform guides | Operator/developer how-to | `refresh-and-surface` | Same family; engines guide aligns with ADR-004 |
| Refactoring summaries, visual roadmaps, status 2026-02-16, final project summary, checklists | ~15+ files in same directory | `historical` | Do not treat as current inventory (counts drift) |
| `ipfs_datasets_py/processors/multimedia/**` READMEs | Multimedia package docs | `refresh-and-surface` | Package detail + future processing guides |
| `omni_converter_mk2/**` (~60 md) | PRD, SAD, ROADMAP, CLAUDE, architecture, many TODO/CHANGELOG | **Split**: design docs `review-needed` / `historical`; active README `refresh-and-surface` | Do not promote session TODOs; design docs need owner review before canonical |
| Legal scrapers package md | Implementation reports + jurisdiction docs | `refresh-and-surface` or `historical` | Legal/user guides under `docs/` + package jurisdiction docs |
| `processors/groth16_backend/*`, `provekit_backend/README.md` | Wire format / setup | `refresh-and-surface` | Proof/attestation architecture leaves |
| `processors/storage/ipld/*` | README/TODO/CHANGELOG | `pointer` / `refresh-and-surface` | IPLD vector/storage docs under `docs/` root already compete—classify before expanding |
| Archive under `docs/archive/**/PROCESSORS_*` | Old status | `historical` | Already archived |

**Processor routing rule:** Prefer `PROCESSORS_ARCHITECTURE.md` + engines/migration
guides over refactoring status decks. Package-local omni_converter and legal
scraper docs stay near code until a processing-family guide explicitly adopts
them. ADR-004 remains the decision authority for **engine extraction** placement.

---

## 6. Generated references and build output

| Path / pattern | Count | Disposition | Authority scope | Guidance |
| --- | ---: | --- | --- | --- |
| `ipfs_datasets_py/**/*_stubs.md` | 45 | `generated` | Signatures/docstrings only | Do not hand-edit; regenerate or leave; never cite for design rationale |
| `docs/archived_stubs/` | 124 | `generated` + `historical` | Former stub dumps | Historical relocation target; not product guides |
| `docs/auto_generated_stubs/README.md` | 1 | `generated` (policy note) | Explains stub lifecycle | Directory currently holds policy README only—not an active stub tree |
| `docs/tdfol/_build/` (html + doctrees) | 202 | `generated` | Build artifact | Prefer rebuilding from RST; committed HTML is not source of truth |
| `docs/tdfol/**/*.rst` | 40 | Source for `generated` HTML | TDFOL Sphinx sources | `refresh-and-surface` if TDFOL remains a product surface; else historical |
| `docs/**/*.html` tracked | ~70 | Mostly `generated` | Includes Sphinx output | Not hand-maintained product Markdown |
| `docs/**/*.doctree` | 40 | `generated` | Sphinx intermediate | Ignore for authority |
| `docs/api/*.md` | 2 | Hand-maintained (not auto-gen) | Navigated API | `refresh-and-surface`; not Sphinx-generated despite “reference” naming |
| `ipfs_datasets_py/**/*.html` | 48 | Runtime templates / UI | Not MkDocs | Out of doc-authority scope except dashboard UX docs |
| MkDocs `site/` | absent | `generated` when built | Publish output | **Never** edit `site/` as source; rebuild from `docs/` + `mkdocs.yml` |
| `requirements-docs.txt` / `docs/tdfol/conf.py` | config | tooling | Sphinx-oriented | Distinct from MkDocs spine (`mkdocs.yml` nav = 7 leaves) |

### Generated vs canonical API

- **Generated stubs** support lookup only.
- **Hand-maintained** `docs/api/OPTIMIZERS_API_REFERENCE.md` and
  `docs/api/CORE_OPERATIONS_API.md` are the current navigated API surface;
  disposition `refresh-and-surface` until domain API maps replace them.
- Package-local `mcp_server/docs/api/tool-reference.md` is secondary until
  reconciled with a single tools catalog derived from the live registry.

---

## 7. Cross-cutting authority matrix (quick routing)

Use this table when two pages disagree. Prefer the higher row that matches the
concern; then apply the disposition of the specific file.

| Concern | Prefer first | Then | Avoid as authority |
| --- | --- | --- | --- |
| MCP tool thin-wrapper / engines / hierarchy / dual-runtime / MCP++ profiles | `ipfs_datasets_py/mcp_server/docs/adr/ADR-00N-*.md` | `mcp_server/docs/architecture/*`, refreshed package README | Phase completion reports, ARCHIVE, static tool-count marketing |
| MCP day-to-day usage | Refreshed `docs/MCP_TOOLS_GUIDE.md` / quickstart (after claim audit) | `mcp_server/docs/guides/*`, CLI MCP guides | Unverified catalogs with hard-coded totals |
| Logic product behavior | Tests + current `ipfs_datasets_py/logic/` layout | One architecture + one API page under `docs/logic/` after dedup | `COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v*.md` series |
| Optimizer selection / extension | `docs/optimizers/SELECTION_GUIDE.md`, `HOW_TO_ADD_NEW_OPTIMIZER.md` | Package `optimizers/README.md` migration notes | Session infinite-todo summaries |
| Processor architecture / engines | `docs/guides/processors/PROCESSORS_ARCHITECTURE.md` + engines/migration guides | Package multimedia/legal READMEs | Refactoring visual summaries and dated STATUS files |
| API signatures | Live source + tests | Navigated `docs/api/*` after refresh | `*_stubs.md`, archived stubs, Sphinx `_build` HTML |
| Decisions index (future) | IPFSDOC-016 `docs/architecture/decisions/` index | Package ADR bodies via `pointer` | Copied ADR text in two trees |

---

## 8. Explicit non-actions (this task)

| Action | Status |
| --- | --- |
| Move files between package and `docs/` | **Not performed** |
| Delete ARCHIVE, history, stubs, or plans | **Not performed** |
| Rewrite ADR bodies or renumber ADRs | **Not performed** |
| Bulk-edit competing guides | **Not performed** |
| Change `mkdocs.yml` nav | **Not performed** (owned by navigation tasks) |
| Mark program todo metadata complete | **Not performed** (unless a separate process requires it) |

Agents implementing later tasks must update this map or the legacy disposition
artifact when they **migrate**, merge, or archive any row’s files.

---

## 9. Downstream consumers

| Task / artifact | How it uses this map |
| --- | --- |
| `IPFSDOC-005` `SOURCE_AUTHORITY.md` / `COVERAGE_MATRIX.md` | Inherits package vs `docs/` authority splits for processors, logic, mcp_server, and related domains |
| `IPFSDOC-016` MCP ADR reconciliation | Starts from §4 six ADRs; produces index + `pointer` / merge dispositions without destroying history |
| Architecture wave (`docs/architecture/**`) | Must link package-local ADRs and refreshed guides rather than inventing parallel MCP/logic decisions |
| Legacy disposition (`LEGACY_DISPOSITION.md` target) | Expands `historical` clusters (phase reports, ARCHIVE, versioned plans) for eventual archive moves |
| Nav / MkDocs tasks | May surface only `canonical` and refreshed hubs; package-local history stays unnavigated |

---

## 10. Reproducible commands

Run from repository root. Counts are worktree facts; re-run after significant
doc changes.

```bash
# Package-local Markdown
find ipfs_datasets_py -name '*.md' | wc -l
find ipfs_datasets_py -name 'README.md' | wc -l
find ipfs_datasets_py -name '*_stubs.md' | wc -l

# Domain concentration
for d in mcp_server processors logic optimizers audit ml knowledge_graphs vector_stores; do
  printf '%s %s\n' "$(find "ipfs_datasets_py/$d" -name '*.md' 2>/dev/null | wc -l)" "$d"
done

# MCP curated docs and ADRs
find ipfs_datasets_py/mcp_server/docs -name '*.md' | wc -l
ls -1 ipfs_datasets_py/mcp_server/docs/adr/
find ipfs_datasets_py/mcp_server/ARCHIVE -name '*.md' | wc -l

# Competing hubs under docs/
find docs/logic docs/optimizers docs/guides/processors -name '*.md' | wc -l
find docs -name '*MCP*' -o -name '*mcp*' 2>/dev/null | grep '\.md$' | wc -l

# Generated / build
find docs/tdfol/_build -type f 2>/dev/null | wc -l
find docs/archived_stubs -type f 2>/dev/null | wc -l
find docs/auto_generated_stubs -type f 2>/dev/null | wc -l
test -d site && echo site_present || echo site_absent
```

### Validation for this deliverable

```bash
test -s docs/maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md && \
  rg -n 'mcp_server/docs/adr|generated|canonical|pointer|migrate' \
    docs/maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md
```

---

## 11. Acceptance checklist (IPFSDOC-004)

| Criterion | Evidence in this document |
| --- | --- |
| Inventory package-local Markdown | §1 summary + §2 domain table + §3 MCP detail |
| Inventory generated references/build output | §6 |
| Inventory competing logic/optimizer/processor/MCP guides | §3.3, §5 |
| Inventory existing MCP ADRs | §4 (`ipfs_datasets_py/mcp_server/docs/adr/`) |
| Assign dispositions | Vocabulary + every major table column |
| No move/delete | §8 Explicit non-actions |
| Validation tokens present | `mcp_server/docs/adr`, `generated`, `canonical`, `pointer`, `migrate` |

---

## 12. Discrepancies and limitations

1. **Counts are inventory, not quality scores.** A `canonical` disposition on an
   ADR means “decision body of record,” not “every metric in the ADR is still
   measured true.”
2. **Tool totals in prose disagree** across catalogs (examples observed: “130+”,
   “382 tools”, “49 categories”). Treat as `review-needed` until re-measured
   from the registry/tests.
3. **Duplicate logic pages** (`ARCHITECTURE.md` vs `logic_ARCHITECTURE.md`,
   dual API references) are intentionally `review-needed` rather than forced
   winners in this task.
4. **MkDocs nav is thin (7 leaves)** over 1476 `docs/` pages; absence from nav
   does not equal `historical`—disposition does.
5. **Sphinx vs MkDocs:** committed TDFOL `_build` is `generated`; product Markdown
   under `docs/` is not automatically generated by MkDocs until `site/` is built.
6. This map does not re-open protected planning files under
   `docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH*`.
