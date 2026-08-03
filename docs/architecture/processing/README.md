# Processing architecture index

| Field | Value |
| --- | --- |
| Interface | `ProcessingArchitectureIndex@1` |
| Task | `IPFSDOC-022` |
| Status | `canonical` |
| Owner | architecture / processing domain |
| Source of truth | Canonical leaves under `docs/architecture/processing/`; `ipfs_datasets_py/processors/`; [DOMAIN_MAP.md](../DOMAIN_MAP.md) §4.1; [ADR-005](../decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md); [ADR-006](../decisions/ADR-006-PROCESSOR-LAYERING.md) |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent |
| Related | [DOMAIN_MAP.md](../DOMAIN_MAP.md), [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md), [INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md), [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md) |
| Review cadence | after pipeline/registry, file/media, or web/legal surface changes |

> **Lifecycle:** This page is the **canonical routing hub** for processing.
> It does **not** replace leaf architecture guides. Prefer the leaves for
> contracts, failure modes, and extension detail. Historical migration plans
> and session reports under `docs/guides/processors/` and root `*_MIGRATION_*`
> files are **not** architecture authority.

## 1. Purpose

Route developers and agents to the right processing documentation:

| Need | Go to |
| --- | --- |
| Contracts, registry, dual surfaces, UniversalProcessor | [PROCESSOR_PIPELINE.md](PROCESSOR_PIPELINE.md) |
| File conversion, PDF/OCR, multimedia | [FILE_AND_MULTIMEDIA.md](FILE_AND_MULTIMEDIA.md) |
| Web archives, WARC/Common Crawl, legal scrapers, evidence packages | [WEB_ARCHIVING_AND_LEGAL_INGESTION.md](WEB_ARCHIVING_AND_LEGAL_INGESTION.md) |
| Domain ownership of `processors` vs neighbors | [DOMAIN_MAP.md](../DOMAIN_MAP.md) §4.1 |
| Cross-domain hop language | [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) |
| Layering / registry decisions | [ADR-006](../decisions/ADR-006-PROCESSOR-LAYERING.md), [ADR-005](../decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md) |
| Day-to-day layer map (mixed layout, maintained guide) | [PROCESSORS_ARCHITECTURE.md](../../guides/processors/PROCESSORS_ARCHITECTURE.md) |
| Package-local operator detail (CLIs, jurisdiction notes) | In-package docs under `ipfs_datasets_py/processors/**` and MCP tool guides |
| How to extend safely | §6 Extension recipes (this page) + leaf “Extension points” sections |
| Historical migrations only | §7 Historical migrations (labeled; not current authority) |

**Effects of this index:** one entry point for processing without rewriting the
leaf guides. New code and docs should link here for orientation, then drop into
the owning leaf.

## 2. Audience

- **Primary:** developers and agents choosing where to implement or document a
  processing path.
- **Secondary:** architects placing new ingest families; operators locating
  migration vs current-tree guides.

## 3. Scope and non-goals

### In scope

- Index of **canonical** processing architecture leaves.
- **Ownership** and **current / compatibility** status per processing family.
- Routes to maintained processor guides, package-local detail, extension
  seams, and historical migrations.
- Explicit dual-surface honesty (root vs `core/`, dual registries, submodule
  emptiness).

### Non-goals

- Full protocol/registry algorithms → [PROCESSOR_PIPELINE.md](PROCESSOR_PIPELINE.md).
- Full PDF/OCR/media backend matrix → [FILE_AND_MULTIMEDIA.md](FILE_AND_MULTIMEDIA.md).
- Full legal corpus / WARC contracts → [WEB_ARCHIVING_AND_LEGAL_INGESTION.md](WEB_ARCHIVING_AND_LEGAL_INGESTION.md).
- MCP transport and tool lifecycle → [architecture/mcp/](../mcp/).
- Formal IR / proof / admissibility → logic architecture (separate track).
- Storage backends, vector indexes, knowledge graphs → storage/retrieval/knowledge leaves.

## 4. Canonical processing guides

These three pages are the **architecture authority** for processing under
`docs/architecture/processing/`. All three have status `canonical` as of last
verification.

| Guide | Interface | Owns | Status |
| --- | --- | --- | --- |
| [PROCESSOR_PIPELINE.md](PROCESSOR_PIPELINE.md) | `ProcessorPipelineArchitecture@1` | Protocols, dual root/`core` types, registries, input detection, UniversalProcessor, adapters, batching/resource knobs, provenance handoff shapes | **canonical** — dual-surface migration **active** |
| [FILE_AND_MULTIMEDIA.md](FILE_AND_MULTIMEDIA.md) | `FileMultimediaProcessing@1` | File conversion, PDF/OCR specialized paths, multimedia wrappers, optional binaries/submodules | **canonical** — specialized preferred; deprecated roots and legacy backends remain |
| [WEB_ARCHIVING_AND_LEGAL_INGESTION.md](WEB_ARCHIVING_AND_LEGAL_INGESTION.md) | `WebArchiveLegalEvidencePipeline@1` | Unified web archive search/fetch, Common Crawl/WARC, legal scrapers, CourtListener/RECAP/PACER boundaries, evidence packaging and CID | **canonical** — current-tree; historical migration docs are operational history only |

```text
                    ┌─────────────────────────────────────┐
                    │  docs/architecture/processing/      │
                    │  README.md  (this index)            │
                    └─────────────────┬───────────────────┘
              ┌───────────────────────┼───────────────────────┐
              ▼                       ▼                       ▼
   PROCESSOR_PIPELINE.md   FILE_AND_MULTIMEDIA.md   WEB_ARCHIVING_AND_
   (contracts & routing)   (convert / PDF / media)  LEGAL_INGESTION.md
                                                    (archive & legal)
```

Cross-links among leaves: pipeline points at file/media and web/legal for
algorithms; file/media and web/legal point back for registry/protocol duality.

## 5. Processing families: ownership and status

**Package owner (product domain):** `ipfs_datasets_py.processors`
([DOMAIN_MAP.md](../DOMAIN_MAP.md) §4.1). MCP tools under
`mcp_server/tools/{pdf_tools,file_converter_tools,media_tools,web_archive_tools,legal_dataset_tools}/`
are **thin wrappers**; algorithms stay in processors.

Status legend:

| Status | Meaning |
| --- | --- |
| **canonical** | Preferred import / design for new work |
| **compat** | Supported transitional surface; prefer canonical when writing new code |
| **optional** | Requires extras, host binaries, secrets, or initialized submodules |
| **deprecated** | Still importable with warnings or re-exports; do not extend |
| **historical** | Docs or paths describing past plans/migrations; not live architecture |

### 5.1 Family matrix

| Family | Canonical path(s) | Compat / optional / deprecated | Architecture leaf | Notes |
| --- | --- | --- | --- | --- |
| **Protocol & registry** | `processors.core.registry` (`get_global_registry`); protocol contracts in core + root | Dual: root `protocol.py` vs `core/protocol.py`; `core/processor_registry.py` parallel singleton; root `registry.py` deprecation shim | [PROCESSOR_PIPELINE.md](PROCESSOR_PIPELINE.md) | **compat period**—not one registry process-wide |
| **UniversalProcessor / detection** | Prefer documented core vs root entry matching your protocol family | Two UP classes; root `input_detection` vs core `input_detector` | [PROCESSOR_PIPELINE.md](PROCESSOR_PIPELINE.md) | Callers must use matching protocol + registry |
| **Adapters** | `processors/adapters/` + `auto_register` | Best-effort registration; many adapters implement **root** protocol | [PROCESSOR_PIPELINE.md](PROCESSOR_PIPELINE.md) | Not a second business-logic home (ADR-005) |
| **Infrastructure** | `processors/infrastructure/` (retry, monitor, cache helpers) | Root modules may re-export or overlap naming | [PROCESSOR_PIPELINE.md](PROCESSOR_PIPELINE.md) | No specialized domain logic as required deps |
| **File conversion** | `processors/file_converter/` (`FileConverter`, native backend) | markitdown/omni backends **optional**/legacy; submodule-backed paths | [FILE_AND_MULTIMEDIA.md](FILE_AND_MULTIMEDIA.md) | Native is long-term supported surface |
| **PDF / OCR** | `processors/specialized/pdf/` | Root `pdf_processor` / `ocr_engine` **deprecated** shims | [FILE_AND_MULTIMEDIA.md](FILE_AND_MULTIMEDIA.md) | Multi-engine OCR optional per host install |
| **Multimedia** | `processors.multimedia` wrappers (FFmpeg, yt-dlp, MediaProcessor) | Package `multimedia/` / submodule checkouts **optional**; empty checkout is availability gap, not architecture absence | [FILE_AND_MULTIMEDIA.md](FILE_AND_MULTIMEDIA.md) | Host binaries required for many ops |
| **Batch processing** | specialized/root batch types + batch adapter | Multiple `BatchProcessor` type names—use fully qualified imports | [PROCESSOR_PIPELINE.md](PROCESSOR_PIPELINE.md), [FILE_AND_MULTIMEDIA.md](FILE_AND_MULTIMEDIA.md) | Dual names are current-tree debt |
| **Web archiving** | `processors/web_archiving/` unified API | Top-level `ipfs_datasets_py/web_archiving/` **compat** re-exports; optional engines/Playwright | [WEB_ARCHIVING_AND_LEGAL_INGESTION.md](WEB_ARCHIVING_AND_LEGAL_INGESTION.md) | Prefer processors subtree for new work |
| **Legal scrapers** | `processors/legal_scrapers/` + `legal_corpus` interfaces | Shared cache/resume; Common Crawl/WARC fallbacks **optional** by capability | [WEB_ARCHIVING_AND_LEGAL_INGESTION.md](WEB_ARCHIVING_AND_LEGAL_INGESTION.md) | Official sources first |
| **Legal data / evidence** | `processors/legal_data/` (dockets, CourtListener, manifests, workspace CID) | PACER credentialed paths **optional**/fail-closed without secrets; HF publish optional | [WEB_ARCHIVING_AND_LEGAL_INGESTION.md](WEB_ARCHIVING_AND_LEGAL_INGESTION.md) | Enrichment ≠ source authority (ADR-001) |
| **GraphRAG website processors** | domain GraphRAG modules + adapters | Multiple historical GraphRAG entry modules coexist | Pipeline adapters; deeper KG in knowledge track | Algorithms not owned by MCP |
| **Domain scrapers / corpora** (medical, finance, discord, wikipedia_x, investigation, geospatial, …) | matching `processors/<domain>/` subpackages | Heavy scrapers need extras; not all have architecture leaves yet | Domain package docs; this index for routing only | Extend via specialized package + adapter pattern |
| **Engines** | `processors/engines/` and specialized engines | Placement per package engine-extraction ADR | [PROCESSORS_ENGINES_GUIDE.md](../../guides/processors/PROCESSORS_ENGINES_GUIDE.md) (maintained exposition) | MCP remains shim-only |
| **Serialization / IPLD helpers under processors** | `processors/serialization/`, `processors/storage/` where present | Do not confuse with product **storage** domain authority | Storage architecture track when published | Processing may emit CIDs; storage owns backends |
| **ZKP / provekit backends under processors** | `groth16_backend/`, `provekit_backend/` | **optional** extras | Logic / proof track for formal claims | Processing must not invent proof from extract success |

### 5.2 Ownership boundaries (summary)

| Owns (processing) | Does not own |
| --- | --- |
| Processor protocols, registries, adapters | MCP framing and hierarchical tool dispatch |
| File/PDF/media conversion and batch pipelines | Vector index engines (`vector_stores`) |
| Web archive engines and legal acquisition/packaging | Formal IR identity, admissibility, provers (`logic`) |
| Domain scrapers under `processors/*` | Wallet grants, UCAN policy bodies |
| Provenance-friendly process metadata handoff | Authoritative content-addressed **storage backends** (storage domain) |

**Inbound:** Python API, MCP tool wrappers, CLIs (`processors.cli` / domain CLIs).  
**Outbound:** optional submodules and host tools; storage/IPFS helpers; LLM/embedding routers; knowledge/retrieval consumers.

## 6. Extension recipes (where to implement)

Do **not** put new business logic only in MCP tool modules. Prefer:

1. Domain package under `processors/` (specialized, file_converter, multimedia,
   web_archiving, legal_scrapers, legal_data, or a domain subpackage).
2. Optional **adapter** implementing the chosen protocol family.
3. Registration on the **same** registry singleton the chosen UniversalProcessor
   uses (dual-registry warning in the pipeline guide).
4. Thin MCP wrapper if agent-facing.

| Extension | Recipe summary | Detail |
| --- | --- | --- |
| New processor type / route | Domain logic + protocol + register with unique name/priority | [PROCESSOR_PIPELINE.md](PROCESSOR_PIPELINE.md) §14 Extension points |
| New file format | Native extractor + format detector; avoid omni-only if native is supported | [FILE_AND_MULTIMEDIA.md](FILE_AND_MULTIMEDIA.md) §13 |
| New OCR engine | Subclass `OCREngine`, optional dep guards, selection policy | [FILE_AND_MULTIMEDIA.md](FILE_AND_MULTIMEDIA.md) §13 |
| New media op | Focused engine + explicit FFmpeg/yt-dlp boundary | [FILE_AND_MULTIMEDIA.md](FILE_AND_MULTIMEDIA.md) §13 |
| New archive provider | Engine under `processors/web_archiving/`, planner/scorer + unified API | [WEB_ARCHIVING_AND_LEGAL_INGESTION.md](WEB_ARCHIVING_AND_LEGAL_INGESTION.md) §10 |
| New jurisdiction corpus | Implement `LegalCorpusJurisdiction` protocols; declare official sources | [WEB_ARCHIVING_AND_LEGAL_INGESTION.md](WEB_ARCHIVING_AND_LEGAL_INGESTION.md) §10 |
| New enrichment | Versioned schema under legal_data; `source_ref` required; no promotion into source fields | [WEB_ARCHIVING_AND_LEGAL_INGESTION.md](WEB_ARCHIVING_AND_LEGAL_INGESTION.md) §10 |
| Layering / import authority | Prefer `processors.core` for new layered contracts; root is compat convenience | [ADR-006](../decisions/ADR-006-PROCESSOR-LAYERING.md) |
| Registry vs adapter rules | One registry per concern; adapters are bridges only | [ADR-005](../decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md) |

**Anti-patterns (all leaves agree):** dual silent semantics, inventing CIDs/IR
digests from convert success, treating model enrichment as official text,
business logic only in MCP files, assuming empty multimedia submodule means
the feature is undocumented rather than unprovisioned.

## 7. Documentation routes by authority class

### 7.1 Canonical architecture (preferred)

| Document | Role |
| --- | --- |
| **This index** | Routing, family status, extension map |
| [PROCESSOR_PIPELINE.md](PROCESSOR_PIPELINE.md) | Contracts and pipeline |
| [FILE_AND_MULTIMEDIA.md](FILE_AND_MULTIMEDIA.md) | Convert / PDF / media |
| [WEB_ARCHIVING_AND_LEGAL_INGESTION.md](WEB_ARCHIVING_AND_LEGAL_INGESTION.md) | Archive and legal evidence |
| [DOMAIN_MAP.md](../DOMAIN_MAP.md) | Product domain map |
| [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) | Cross-domain hops |
| [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) | CID / provenance |
| [ADR-005](../decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md) | Registries and adapters |
| [ADR-006](../decisions/ADR-006-PROCESSOR-LAYERING.md) | Root / core layering |

### 7.2 Maintained processor pages (developer exposition)

These live under `docs/guides/processors/`. Prefer them for **layer maps and
engines exposition**, but treat **architecture contracts** as owned by the
canonical leaves above when they disagree.

| Page | Use for |
| --- | --- |
| [PROCESSORS_ARCHITECTURE.md](../../guides/processors/PROCESSORS_ARCHITECTURE.md) | Five-layer layout; mixed root/core honesty |
| [PROCESSORS_ENGINES_GUIDE.md](../../guides/processors/PROCESSORS_ENGINES_GUIDE.md) | Engine placement and usage patterns |
| [PROCESSORS_QUICK_REFERENCE.md](../../guides/processors/PROCESSORS_QUICK_REFERENCE.md) | Short navigation (verify against current tree) |
| [PROCESSORS_PROTOCOL_MIGRATION_GUIDE.md](../../guides/processors/PROCESSORS_PROTOCOL_MIGRATION_GUIDE.md) | Protocol migration narrative |
| [PROCESSORS_BREAKING_CHANGES.md](../../guides/processors/PROCESSORS_BREAKING_CHANGES.md) / changelog siblings | Change notes—not sole architecture |

Related product-facing guides outside that folder (feature detail, not domain
architecture authority):

- [docs/guides/pdf_processing.md](../../guides/pdf_processing.md) — PDF/LLM consumption narrative
- [docs/LEGAL_SCRAPERS_COMMON_CRAWL_GUIDE.md](../../LEGAL_SCRAPERS_COMMON_CRAWL_GUIDE.md) — operator Common Crawl
- [docs/AGENTIC_LEGAL_SCRAPER_DAEMON.md](../../AGENTIC_LEGAL_SCRAPER_DAEMON.md) — daemon ops

### 7.3 Package-local details

| Location | Role |
| --- | --- |
| `ipfs_datasets_py/processors/**` (docstrings, package READMEs) | Implementation-level contracts and module notes |
| `ipfs_datasets_py/processors/legal_scrapers/*.md` | Scraper integration notes, shared components, HF index notes |
| `ipfs_datasets_py/processors/multimedia/**` (submodule READMEs when checked out) | Submodule-owned converter catalogs |
| `ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/` | CourtListener, cron, Playwright setup, testing |
| `ipfs_datasets_py/mcp_server/tools/{pdf_tools,file_converter_tools,media_tools,web_archive_tools}/` | Thin tool surfaces; link algorithms to processors |

Package-local completion reports and “PROJECT_COMPLETE” files are **historical
session evidence**, not the preferred architecture description.

### 7.4 Historical migrations (do not treat as current architecture)

Use only to understand **how** the tree got here or to migrate old call sites.
Always re-verify against the **canonical** leaves and live code.

| Document | Topic | Label |
| --- | --- | --- |
| [WEB_ARCHIVING_MIGRATION_GUIDE.md](../../WEB_ARCHIVING_MIGRATION_GUIDE.md) | Legacy → unified web archive API | **historical / operator migration** |
| [MULTIMEDIA_MIGRATION_GUIDE.md](../../MULTIMEDIA_MIGRATION_GUIDE.md) | Multimedia relocation | **historical** |
| [FILE_CONVERTER_MIGRATION_GUIDE.md](../../FILE_CONVERTER_MIGRATION_GUIDE.md) | Converter unification | **historical** |
| [PROCESSORS_MIGRATION_GUIDE.md](../../guides/processors/PROCESSORS_MIGRATION_GUIDE.md) and `PROCESSORS_*INTEGRATION*`, `PROCESSORS_DATA_TRANSFORMATION_*` | Processors / data_transformation consolidation plans | **historical / plan** |
| `docs/WEB_ARCHIVING_UNIFIED_API_REFACTOR_PLAN.md`, execution tickets | Refactor plan tickets | **historical plan** |
| `docs/archive/processors/**`, `docs/archive/root_status_reports/PROCESSORS_*` | Session and phase completion | **archive** |
| Root `MULTIMEDIA_*` analysis docs, integration visual summaries | Snapshots with fixed file counts | **historical**—do not use counts as inventory authority |

## 8. Decision guide (quick chooser)

```text
What are you doing?
│
├─ Register, route, or unify processor entry?
│    → PROCESSOR_PIPELINE.md  (+ ADR-005 / ADR-006)
│
├─ Convert files, PDF/OCR, or A/V?
│    → FILE_AND_MULTIMEDIA.md
│    → empty submodule / missing FFmpeg?  read optional-deps & INTEGRATION_BOUNDARIES
│
├─ Capture web evidence, WARC, Common Crawl, legal dockets?
│    → WEB_ARCHIVING_AND_LEGAL_INGESTION.md
│    → credentialed PACER / HF publish?  fail-closed + operator guides
│
├─ Add a new capability?
│    → §6 Extension recipes → owning leaf § Extension points
│
├─ Only updating an old import path from a migration doc?
│    → §7.4 historical, then re-check canonical leaf import tables
│
└─ Cross-domain “where does the artifact go next?”
     → END_TO_END_DATA_FLOW.md, then storage / retrieval / knowledge / logic leaves
```

## 9. Related architecture and governance

| Document | Relationship |
| --- | --- |
| [architecture/README.md](../README.md) | Architecture documentation hub |
| [ARCHITECTURE_GUIDE_TEMPLATE.md](../ARCHITECTURE_GUIDE_TEMPLATE.md) | Guide contract |
| [SYSTEM_CONTEXT.md](../SYSTEM_CONTEXT.md) | Product context |
| [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md) | Hermetic imports and extras |
| [INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md) | Submodule and external engine boundaries |
| [RUNTIME_ENTRYPOINTS.md](../RUNTIME_ENTRYPOINTS.md) | CLI/module entry points |
| [SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md) | Evidence precedence |
| [INFORMATION_ARCHITECTURE.md](../../maintenance/INFORMATION_ARCHITECTURE.md) | Doc IA |

## 10. Validation

Bounded offline checks for this index:

```bash
# Declared output present and keyword coverage
test -s docs/architecture/processing/README.md
rg -n 'PROCESSOR_PIPELINE|FILE_AND_MULTIMEDIA|WEB_ARCHIVING_AND_LEGAL_INGESTION|canonical' \
  docs/architecture/processing/README.md

# Canonical leaves still present
test -s docs/architecture/processing/PROCESSOR_PIPELINE.md
test -s docs/architecture/processing/FILE_AND_MULTIMEDIA.md
test -s docs/architecture/processing/WEB_ARCHIVING_AND_LEGAL_INGESTION.md

# Package anchors for major families
test -d ipfs_datasets_py/processors/core
test -d ipfs_datasets_py/processors/file_converter
test -d ipfs_datasets_py/processors/specialized
test -d ipfs_datasets_py/processors/multimedia
test -d ipfs_datasets_py/processors/web_archiving
test -d ipfs_datasets_py/processors/legal_scrapers
test -d ipfs_datasets_py/processors/legal_data
test -d ipfs_datasets_py/processors/adapters
```

Known limits: optional OCR/FFmpeg, initialized multimedia submodules, live
CourtListener/PACER/Common Crawl, and HF publish paths are environment-gated.
This index only proves **routing and ownership language**, not full pipeline
runtime proof.

## 11. Document history

| Date | Change |
| --- | --- |
| 2026-08-03 | Initial **canonical** processing architecture index for `IPFSDOC-022` / `ProcessingArchitectureIndex@1` |
