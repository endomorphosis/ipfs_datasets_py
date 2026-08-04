# Web Archiving and Legal Evidence Ingestion

| Field | Value |
| --- | --- |
| Interface | `WebArchiveLegalEvidencePipeline@1` |
| Task | `IPFSDOC-021` |
| Status | `canonical` |
| Owner | processing / legal-data |
| Source of truth | `ipfs_datasets_py/processors/web_archiving/`; `ipfs_datasets_py/processors/legal_scrapers/`; `ipfs_datasets_py/processors/legal_data/`; `ipfs_datasets_py/web_archiving/` (compat re-exports); MCP tools under `mcp_server/tools/web_archive_tools/` and `mcp_server/tools/legal_dataset_tools/`; `processors/legal_scrapers/legal_corpus/interfaces.py`; ADR-001 |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent |
| Related ADRs | [ADR-001 Content Identity and Provenance](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) |
| Review cadence | semi-annual or after major scraper, RECAP/PACER, or corpus-jurisdiction changes |

> **Lifecycle:** This guide describes **current-tree** behavior. Historical
> migration notes (`docs/WEB_ARCHIVING_MIGRATION_GUIDE.md`, in-package
> completion reports under `legal_scrapers/`) are operational history, not the
> preferred architecture.

## 1. Purpose

This guide answers: **how web archival capture and legal-source acquisition
become durable, content-addressed evidence packages**, and how those packages
hand off to knowledge graphs, reasoners, and publication targets—while keeping
**source evidence** strictly separated from **model or heuristic enrichment**.

It is the processing-domain leaf for the large post-baseline legal acquisition
and evidence pipeline (`IPFSDOC-G041` / `IPFSDOC-021`). Cross-domain hop
language lives in [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md);
domain ownership in [DOMAIN_MAP.md](../DOMAIN_MAP.md).

## 2. Audience

- **Primary:** architects and agents implementing or reviewing legal ingest,
  WARC/Common Crawl paths, CourtListener/PACER boundaries, and evidence
  packaging
- **Secondary:** operators running scrapers/daemons, developers wiring MCP/CLI
  tools, reasoner/KG integrators

## 3. Scope and non-goals

### In scope

- Official-source-first **discovery → fetch → parse → hierarchy → status**
  contracts (`legal_corpus` jurisdiction protocols)
- Unified web archiving **search/fetch** surfaces and multi-method scrapers
- **Common Crawl**, Wayback, archive.is, and related **archive fallbacks**
- **Cache**, **resume**, and **WARC / CDXJ / pointer** identity
- **CourtListener / RECAP** and **PACER** authentication and authority boundaries
- **Citations**, **PDFs**, and **manifests** for dockets and binders
- **Effective dates** and **versioning** fields on legal rows
- **Content addressing (CID)** of packages and pieces
- **KG / reasoner handoff** with explicit enrichment layering
- **Publication lifecycle** (local packages, IPFS pin, Hugging Face)

### Non-goals

- Generic processor registry and file/multimedia conversion (sibling guides
  under `docs/architecture/processing/`)
- Full IR family / intent-IR / legal-gate proof semantics (see logic architecture
  plans and [LOGIC_INTENT_LEGAL_GATE_PLAN.md](../LOGIC_INTENT_LEGAL_GATE_PLAN.md))
- Storage-backend router internals beyond CID pin/cat used at this boundary
  (content-addressing storage guide / ADR-001)
- Operator runbooks for every jurisdiction CLI flag (see package docs under
  `legal_scrapers/` and `mcp_server/tools/legal_dataset_tools/`)

## 4. Context

Legal and regulatory work requires **reproducible evidence**: not only “what the
page says now,” but **which bytes were obtained, from which authority channel,
at which retrieval time**, and whether downstream structure is **parsed from
source** or **inferred by models**.

The repository therefore composes three cooperating layers:

1. **Web archiving** (`processors/web_archiving/`) — provider-neutral search and
   fetch, WARC tooling, Common Crawl pointer lookup, multi-engine fallbacks.
2. **Legal scrapers** (`processors/legal_scrapers/`) — jurisdiction-aware
   acquisition (federal, state, municipal, RECAP, multi-language corpora),
   scraper registry, shared fetch cache, job resume state, GraphRAG helpers.
3. **Legal data / evidence** (`processors/legal_data/`) — docket packaging,
   CourtListener ingestion, citation linking, PDF/binder manifests, formal
   enrichment, reasoner IR, recovery promotion, workspace CAR/CID bundles.

Product constraints that shape the design:

- Prefer **official sources** over third-party mirrors when both are available.
- Prefer **archives and range-fetched WARC records** when live sites block,
   rate-limit, or rewrite content.
- Never treat **PACER credentials** as interchangeable with free RECAP/API
  tokens; paid or credentialed boundaries stay fail-closed without secrets.
- Never promote **heuristic or LLM enrichment** into the same authority class
  as source bytes, official metadata, or parser-backed citations.
- Identity of durable artifacts is **content-addressed** (CID), not URL or
  filesystem path alone (ADR-001).

## 5. Ownership and boundaries

| Owns | Does not own |
| --- | --- |
| Web search/fetch contracts and scraper engines | Vector index algorithms beyond corpus builders |
| Official corpus discovery/fetch/parse/status | Policy/proof authorization decisions |
| WARC/CDXJ creation, index, text/link/metadata extract | Generic multimedia decode pipelines |
| Common Crawl pointer search and range fetch | Hugging Face hub platform operations (only client publish) |
| CourtListener RECAP ingest and PACER credential resolution | PACER as a first-party product surface |
| Citation extraction/linking, docket/PDF/manifest packaging | Court filing e-service systems |
| Source-recovery manifests and promotion into canonical rows | Full IR prover correctness proofs |
| Legal GraphRAG construction and reasoner handoff adapters | Global MCP tool registry governance |
| IPFS pin of legal datasets via storage integration | Cluster orchestration and pinset policy |

**Inbound callers:** Python API; CLI (`ipfs_datasets_cli` legal/web paths);
MCP `web_archive_tools`, `legal_dataset_tools`, unified web tools; agent
daemons (`legal_scraper_daemon`); workspace packaging entrypoints.

**Outbound dependencies:** HTTP clients; optional Playwright / Cloudflare
Browser Rendering; Common Crawl / Hugging Face pointer datasets; Wayback and
archive.is; CourtListener REST; optional PACER credentials; IPFS backend
router; Hugging Face Hub; GraphRAG / embeddings when enabled; logic IR
reasoner packages.

**Authority notes:**

- **Source authority** > **archive of source** > **search snippet** > **model
  paraphrase**.
- **CourtListener RECAP** is a redistributed PACER archive channel, not PACER
  itself. Direct PACER fetch requires separate credentials and consent.
- **Enrichment** (entity extraction, deontic norms, KG edges, LLM fields) is
  derived and must carry `source_ref` / provenance pointers back to evidence
  rows; it must not overwrite raw body fields without a distinct layer key.

## 6. Components

### 6.1 Inventory (current tree)

| Component | Path | Role |
| --- | --- | --- |
| Unified web archiving API | `processors/web_archiving/unified_api.py` | Canonical `search` / `fetch` / `search_and_fetch` / health |
| Unified contracts | `processors/web_archiving/contracts.py` | Provider-neutral request/response envelopes |
| Orchestration | `processors/web_archiving/orchestration/` | Planner, scorer, executor, circuit breaker, retry |
| Unified web scraper | `processors/web_archiving/unified_web_scraper.py` | Multi-method fetch with ordered fallbacks |
| Common Crawl integration | `processors/web_archiving/common_crawl_integration.py` | Domain search, WARC range fetch, HF/local pointers |
| Common Crawl search engine package | `processors/web_archiving/common_crawl_search_engine/` | Lower-level CC index engines |
| WARC processor | `processors/web_archiving/web_archive.py`, `web_archive_utils.py` | Create/index WARC; extract text/links/metadata; CDXJ → dataset |
| Search engines | `brave_*`, `wayback_machine_engine.py`, `archive_is_engine.py`, `google_*`, `huggingface_*`, … | Live and archive search providers |
| Compat re-exports | `ipfs_datasets_py/web_archiving/` | Thin shims to processors tree |
| Legal scraper registry | `processors/legal_scrapers/registry.py` | Auto-discovery, capabilities, fallback chains |
| Common Crawl legal scraper | `processors/legal_scrapers/common_crawl_scraper.py` | Legal fallback chain + WARC metadata |
| Federal / state / municipal scrapers | `legal_scrapers/federal_scrapers/`, `state_*`, `municipal_*` | Official jurisdiction acquisition |
| RECAP / CourtListener scraper | `legal_scrapers/recap_archive_scraper.py` | Search/fetch RECAP docs; job resume |
| Legal corpus interfaces | `legal_scrapers/legal_corpus/interfaces.py` | Official-source pipeline protocols |
| Shared fetch cache | `legal_scrapers/shared_fetch_cache.py` | URL-keyed local cache; optional IPFS mirror |
| Scraping state | `legal_scrapers/scraping_state.py` | Resumable job metadata + scraped payload |
| IPFS storage integration | `legal_scrapers/ipfs_storage_integration.py` | Dataset add/get/pin by CID |
| Legal GraphRAG | `legal_scrapers/legal_graphrag.py`, `legal_graphrag_engine.py` | KG build from search/scrape results |
| Legal dataset API | `legal_scrapers/legal_dataset_api.py` | Parameterized scrape/search orchestration |
| CourtListener ingestion | `legal_data/courtlistener_ingestion.py` | Token/PACER resolution; RECAP fetch boundaries |
| Docket dataset / packaging | `legal_data/docket_dataset.py`, `docket_packaging.py` | PACER HTML/JSON normalize; package pieces |
| Citation extraction / Bluebook | `legal_data/citation_extraction.py`, `bluebook_citation_linker.py` | Citation parse and authority link |
| PDF / binder manifests | `legal_pdf_manifest.py`, `exhibit_binder_manifest.py`, `full_evidence_binder_manifest.py`, court PDF exporters | Manifest-driven PDF/binder assembly |
| Source recovery / promotion | `legal_source_recovery.py`, `legal_source_recovery_promotion.py` | Citation → official candidates → canonical merge/publication |
| Formal enrichment | `formal_docket_enrichment.py`, `rich_docket_enrichment.py` | Logic/heuristic layers on dockets |
| Reasoner | `legal_data/reasoner/` | Hybrid IR, KG enrichment apply/rollback, source_ref validation |
| Workspace packaging | `legal_data/workspace_packaging.py` | Bundle manifests, parquet, CAR, root CID |
| MCP web archive tools | `mcp_server/tools/web_archive_tools/` | `create_warc`, extract/index tools, unified API tools |
| MCP legal tools | `mcp_server/tools/legal_dataset_tools/` | Scrape/search/export wrappers over domain packages |

### 6.2 Boundary diagram

```text
  Callers (Python / CLI / MCP / daemon)
                 |
                 v
  +------------------+     +---------------------------+
  | UnifiedWebArchivingAPI |     | legal_dataset_api / scrapers |
  | search / fetch         |     | federal|state|municipal|RECAP|
  +----------+-----------+     +-------------+-------------+
             |                               |
             v                               v
  +------------------+            +----------------------+
  | UnifiedWebScraper|            | LegalCorpusJurisdiction
  | engines + fallbacks|          | discovery→fetch→parse |
  +--------+---------+            | hierarchy→status→CID  |
           |                      +----------+-----------+
           v                                 |
  Common Crawl pointers / WARC / CDXJ         |
  Wayback / archive.is / live HTTP            v
           |                      legal_data packaging
           +-----------+---------- docket / binder / recovery
                       |
                       v
              SharedFetchCache + ScrapingState
                       |
                       v
         IPFS (CID pin) / HF publish / KG+reasoner
```

## 7. End-to-end flow

### 7.1 Happy path A — Official-source legal corpus

Jurisdiction packages implement `LegalCorpusJurisdiction`
(`legal_corpus/interfaces.py`). Ordered stages:

1. **Discover** (`DiscoveryProvider`) — enumerate official catalog or seed
   URLs; emit `DiscoveryRecord` (`identifier`, `document_url`, `source`,
   optional raw metadata). Prefer `JurisdictionSpec.official_sources`.
2. **Import / queue** — durable catalog import and work queue for resumable
   runs; coverage reports measure official-source completeness.
3. **Fetch** (`FetchProvider`) — retrieve body bytes/HTML for each discovery
   record; support `scrape_batch` and `resume`.
4. **Parse** (`Parser`) — jurisdiction-specific parse into `ParsedLawRecord`
   and `ParsedArticleRecord` rows (structured fields, not free-form model
   summaries).
5. **Hierarchy** (`HierarchyExtractor`) — extract `HierarchyNode` trees
   (title/chapter/section or equivalent) and validate structure.
6. **Status / version** (`StatusClassifier`) — assign `StatusMetadata`:
   `law_status` (`current` | `historical` | `repealed` | `superseded` |
   `unknown`), `effective_date`, `valid_from` / `valid_to`,
   `version_start_date` / `version_end_date`, `status_source`,
   `status_confidence`, `retrieved_at`.
7. **Content address** (`CIDGenerator`) — assign record CIDs; build
   CID-addressed packages.
8. **Package** (`PackageBuilder`) — normalized packages + CID packages;
   manifests under output dirs.
9. **Index** (vector / BM25 / JSON-LD) — optional retrieval and graph indexes
   with their own manifests.
10. **Publish** (`HuggingFacePublisher`) — upload/verify remote dataset
    packages; integrity validation closes the loop.

Representative implementations: Netherlands laws package
(`legal_scrapers/netherlands_laws/`), federal US Code / Federal Register
scrapers, state and municipal scrapers with official host maps.

### 7.2 Happy path B — Unified web search and archival fetch

1. Caller builds `UnifiedSearchRequest` or `UnifiedFetchRequest`
   (`contracts.py`), optionally with parsing `domain` (`legal`, `finance`,
   `medical`, `general`—aliases normalized).
2. `UnifiedWebArchivingAPI` plans providers via orchestration scorer
   (`OperationMode`: max_throughput, balanced, max_quality, low_cost).
3. Search engines return `UnifiedSearchHit` rows (title, url, snippet,
   **source**, score, metadata).
4. Fetch path uses `UnifiedWebScraper` method order (default preference includes
   Common Crawl, Playwright, BeautifulSoup, Wayback, archive.is, Cloudflare
   browser rendering, IPWB, newspaper, readability, requests-only). Unavailable
   methods are skipped via capability probes.
5. Successful responses carry structured-fields contract metadata
   (`structured_fields_contract=v1`, `source_schema`, migration flags) when
   domain parsing is enabled—**parser output**, not enrichment.
6. Optional WARC creation (`WebArchiveProcessor.create_warc` /
   MCP `create_warc`) materializes durable response records; index to CDXJ;
   extract text/links/metadata for dataset builders.

### 7.3 Happy path C — Legal search with archive fallbacks

`CommonCrawlLegalScraper` and related legal paths implement a **fallback chain**
(default order in `FallbackMethod`):

1. **Common Crawl** (pointer index → WARC range fetch)
2. **Brave Search** (live discovery when configured)
3. **Wayback Machine**
4. **Archive.is** (and related archive engines)
5. **Unified scraper** / **direct HTTP**

Each attempt is recorded on `ScrapedLegalContent.fallback_methods_tried` and
`method_used`. WARC-oriented successes may attach `warc_metadata` (filename,
offset, length, timestamp). **Official live hosts remain preferred for
jurisdiction scrapers** when they succeed; archive methods are evidence of
historical capture, not a substitute for official discovery policy.

`LegalWebArchiveSearch` merges current Brave (or multi-engine) hits with Common
Crawl historical hits, deduplicates, and can auto-archive `.gov` results into
local WARC storage.

### 7.4 Happy path D — CourtListener / RECAP and optional PACER

1. **Unauthenticated or token-authenticated CourtListener API** searches RECAP
   (`recap_archive_scraper`, `courtlistener_ingestion`). Free tier is
   rate-limited; `COURTLISTENER_API_TOKEN` raises limits.
2. Document hydration pulls opinion/docket metadata and available PDF/text from
   RECAP redistributions—not a PACER login by default.
3. **Direct PACER fetch** (e.g. RECAP Fetch submission paths) requires
   `PACER_USERNAME` / `PACER_PASSWORD` (and optional client code) resolved via
   `resolve_pacer_*` helpers. Missing credentials **fail closed** with an
   explicit error—no silent public-web substitute that pretends to be PACER.
4. Jobs use `ScrapingState` with `job_id` + `resume` so partial RECAP scrapes
   continue without re-downloading processed document IDs.
5. Normalized dockets also accept **operator-supplied** PACER HTML exports or
   Tyler/PACER JSON directories (`docket_dataset`)—local evidence import without
   live PACER credentials.

### 7.5 Happy path E — Citations, PDFs, manifests, packaging

1. Citation extractors produce structured citation records; Bluebook linker
   attaches authorities to parser-backed corpora when possible.
2. Unresolved citations enter **source recovery** (`legal_source_recovery`):
   search, archive, and Common Crawl candidates → recovery **manifest**.
3. **Promotion** (`legal_source_recovery_promotion`) maps recovery manifests to
   canonical corpus rows; optional merge into local or Hugging Face parquet
   with explicit publish flags.
4. Docket / exhibit / full-evidence **manifests** drive PDF rendering and binder
   export (`legal_pdf_manifest`, exhibit binders, court-style packets).
5. Workspace packaging writes `bundle_manifest.json` (or legacy `manifest.json`),
   parquet pieces, optional **CAR** + `manifest_root_cid`.

### 7.6 Happy path F — KG / reasoner handoff and publication

1. **Source package** (normalized rows + CIDs + manifests) is complete.
2. `LegalGraphRAG` builds a knowledge graph from search/scrape results when
   GraphRAG deps are present—edges and entities are **derived**.
3. Formal / rich docket enrichment and `reasoner/` KG enrichment apply layers
   that **reference** source documents via `source_ref`; unknown refs fail
   validation in strict IR schemas.
4. Publication: local package → IPFS `IPFSStorageManager.add_dataset` (CID +
   pin) and/or Hugging Face upload/verify; integrity validators check
   cross-artifact consistency.

### 7.7 Sequence (legal evidence lifecycle)

```text
Official catalog / URL seeds
        | discover
        v
DiscoveryRecord ----------------+
        | fetch                 |
        v                       | resume / cache hit
FetchedDocument (bytes + meta)  |
        | parse                 |
        v                       |
ParsedLaw/Article + Hierarchy   |
        | status/version        |
        v                       |
StatusMetadata + effective dates|
        | CID assign            |
        v                       |
CID package + manifests  <------+  WARC pointers / SharedFetchCache
        |
        +--> citations / PDFs / binders
        |
        +--> source recovery promote (if gaps)
        |
        +--> KG / reasoner enrichment (separate layer)
        |
        v
IPFS pin (CID) and/or HF publication
```

### 7.8 Initialization and lifecycle

- **Stateless tools:** unified API and most scrapers construct per call; engines
  probe optional deps at init.
- **Caches:** `SharedFetchCache.from_env()` respects
  `IPFS_DATASETS_LEGAL_FETCH_CACHE_*` / `LEGAL_SCRAPER_FETCH_CACHE_*`; optional
  IPFS mirroring of cache entries.
- **Jobs:** `ScrapingState` under `~/.ipfs_datasets/scraping_state` (or
  configured dir); partial state scrapers write checkpoints (e.g. state law
  partial checkpoints).
- **Common Crawl:** local DuckDB/parquet pointer roots, remote HF pointer
  datasets (`Publicus/common_crawl_*` defaults), or CLI mode; range cache mode
  for WARC byte windows.
- **Secrets:** CourtListener token and PACER credentials from env, optional
  vault/keyring with short timeouts for headless runs—never logged in full.

## 8. Contracts

### 8.1 Inputs

| Input | Type / source | Validation |
| --- | --- | --- |
| Search query / domains | `UnifiedSearchRequest`, legal search params | HTTP(S) hits; provider allowlists |
| Fetch URL | `UnifiedFetchRequest.url` | Absolute `http`/`https` |
| Discovery seeds | Official catalogs, JSONL source lists, jurisdiction specs | Prefer official hosts; block non-admin patterns where coded |
| PACER HTML / export dir | Filesystem | Structural parse; `source_type` labeling |
| CourtListener query | API params + optional token | Rate-limit and status handling |
| PACER credentials | Env / vault / explicit args | Required only for PACER paths; fail-closed if missing |
| Recovery / binder manifests | JSON paths | Schema fields for corpus key, citations, PDF inputs |
| Resume job_id | String + state dir | Load prior processed item set |

### 8.2 Outputs

| Output | Type / sink | Guarantees |
| --- | --- | --- |
| `UnifiedSearchResponse` / `UnifiedFetchResponse` | API envelope | Success flag, errors with severity/retryable, execution traces |
| `ScrapedLegalContent` / statute rows | Dict / dataclass | Method used, fallbacks tried, optional WARC metadata |
| `FetchedDocument` / `ParsedLawRecord` | Corpus pipeline | Source URL, retrieved_at, hierarchy, status fields |
| WARC + CDXJ | Filesystem | Replayable capture; indexable pointers |
| Docket package / binders | Dir + PDFs + manifests | Piece inventory; provenance of input type |
| Recovery / promotion reports | JSON | Candidate URLs vs canonical merge outcomes |
| CID / pin / HF repo | Content address / remote | Portable identity separate from path |
| KG / reasoner IR | Graph / IR payload | `source_ref` linkage; enrichment rollback where supported |

### 8.3 Public surfaces

- **Python API:**
  - `ipfs_datasets_py.processors.web_archiving` — `UnifiedWebArchivingAPI`,
    contracts, scrapers, Common Crawl, WARC utils
  - `ipfs_datasets_py.processors.legal_scrapers` — scrapers, registry, legal
    dataset API, RECAP, GraphRAG
  - `ipfs_datasets_py.processors.legal_data` — dockets, CourtListener,
    citations, manifests, reasoner, packaging
  - Compat: `ipfs_datasets_py.web_archiving` re-exports
- **CLI:** legal scrape/search subcommands and corpus jurisdiction CLIs (see
  package `run_cli` / `ipfs_datasets_cli` wiring)
- **MCP tools:**
  - Web: `create_warc`, `index_warc`, `extract_*_from_warc`,
    `extract_dataset_from_cdxj`, unified search/fetch tools, engine-specific
    search tools
  - Legal: RECAP/CourtListener tools, federal/state/municipal scrapers, legal
    web archive tools, citation tools, GraphRAG tool, IPFS storage integration
- **Config / env (representative):**
  - `COURTLISTENER_API_TOKEN`
  - `PACER_USERNAME`, `PACER_PASSWORD`, `PACER_CLIENT_CODE` (+ CourtListener-prefixed aliases)
  - `IPFS_DATASETS_LEGAL_FETCH_CACHE_ENABLED`, `…_CACHE_DIR`, `…_IPFS_MIRROR`
  - Common Crawl: `CCINDEX_MASTER_DB`, HF pointer dataset overrides, range cache
  - HF tokens: `HF_TOKEN`, `HUGGINGFACE_HUB_TOKEN`, related aliases

### 8.4 Persistence and identity

| Kind | Identity | Notes |
| --- | --- | --- |
| Live URL | Location only | Not durable identity |
| WARC record | File + offset/length (+ Target-URI, date) | Pointers into CC or local WARC |
| CDXJ entry | Surrogate for WARC location | Dataset extract input |
| Shared fetch cache key | Normalized URL hash under cache dir | Optional IPFS mirror CID |
| Scraping job | `job_id` state files | Resume, not content identity |
| Legal row / package | **CID** (record and package roots) | ADR-001; `cid_utils` / package builders |
| Manifest | Path + embedded piece digests/CIDs | Bundle inventory |
| Enrichment node | Derived id + **source_ref** | Must not replace source body |

### 8.5 Evidence vs enrichment (normative separation)

| Layer | Examples | May rewrite raw source bytes? | Required linkage |
| --- | --- | --- | --- |
| **Source evidence** | Official HTML/PDF, WARC payload, RECAP document body, operator PACER export | N/A (is the source) | URL, retrieved_at, method, credentials class |
| **Parser-backed structure** | Hierarchy nodes, section numbers, effective dates from official metadata, citation strings extracted by deterministic parsers | No—produce parallel fields | Source identifier / document id |
| **Archive provenance** | CC WARC filename/offset, Wayback timestamp | No | warc_metadata / archive URL |
| **Heuristic / model enrichment** | GraphRAG entities, deontic extraction fallbacks, LLM structured fields, formal logic overlays | **No** | `source_ref`, enrichment version, reversible apply where coded |
| **Publication metadata** | HF repo id, pin set membership | No | Points at CID of package |

Callers and agents **must** treat enrichment outputs as advisory unless a
downstream policy gate explicitly admits them. Strict reasoner validation
rejects unknown `source_ref` values.

## 9. Failure modes and fallbacks

| Failure | Detection | Caller-visible behavior | Fallback |
| --- | --- | --- | --- |
| Optional engine missing (Playwright, CC, IPWB, …) | Import/capability probe | Method marked unavailable | Next method in chain |
| Live site block / challenge page | Heuristic challenge detect / empty body | Method fails; recorded in tried list | Archive methods (CC, Wayback, archive.is) |
| Common Crawl index miss | Empty pointer search | No WARC fetch | Next fallback or error |
| HF rate limit on remote CC | Exception classification | Retry/backoff in worker path | Local index if configured |
| Shared cache corrupt | Deserialize error | Warning; ignore entry | Live fetch |
| CourtListener rate limit / non-200 | HTTP status | Error envelope with status text | Backoff; reduce concurrency; require token |
| PACER credentials missing | Resolver returns empty | Hard error on PACER-only ops | Use RECAP/public or operator-supplied exports |
| RECAP job interrupt | Exception during scrape | State saved; status failed | `resume=True` with same `job_id` |
| Citation without official source | Audit / recovery candidate list | Recovery manifest with candidates | Promote after human/policy accept |
| Enrichment without source_ref | IR schema validation | Strict fail | Fix linkage or disable enrichment |
| IPFS pin failure | Router exception | Dataset may still have CID; pin=false | Retry pin; local retain |
| HF publish without hydrate | Guard in promotion merge | Explicit error | Hydrate first or publish local-only |

Distinguish:

- **Not installed** (method unavailable) vs **installed but failed** (tried,
  error recorded).
- **Structural parse failure** vs **semantic/policy** rejection of enrichment.
- **Compatibility shims** (`web_archiving/` top-level re-exports, legacy MCP
  search wrappers) vs **canonical** `processors/web_archiving` unified API.

## 10. Extension points

1. **New search/fetch provider:** implement engine under
   `processors/web_archiving/`, register in planner/scorer allowlists and
   unified API; add MCP thin wrapper if agent-facing.
2. **New jurisdiction corpus:** implement `LegalCorpusJurisdiction` protocols
   (discovery, fetch, parse, hierarchy, status, CID, packaging, indexes,
   publisher, integrity); declare `official_sources` on `JurisdictionSpec`.
3. **New legal scraper type:** extend registry capabilities
   (`WARC_PARSING`, `FALLBACK_SUPPORT`, …); keep official hosts first for
   primary scrape paths.
4. **New fallback method:** add `FallbackMethod` / `ScraperMethod` values and
   wire capability checks; never insert ahead of official policy without
   explicit config.
5. **New enrichment:** add under `legal_data` or `reasoner/` with versioned
   schema, `source_ref` requirements, and prefer apply/rollback pairs.
6. **Tests:** unit tests for contracts and parsers; integration tests with
   fixtures (offline HTML/WARC); no live PACER in CI without secrets gates.
7. **Docs:** update this guide and sibling processing index when surfaces
   change; do not only update historical completion reports.

**Anti-patterns:**

- Business logic only in MCP wrappers without domain package implementation
- Treating search snippets as statute text
- Writing model summaries into fields reserved for official body text
- Using PACER credentials for unauthenticated RECAP queries (unnecessary
  exposure)
- Using URL strings as the only long-term identity of a package
- Skipping resume/state for multi-hour scrapes

## 11. Invariants

1. **Official-source-first:** primary discovery and fetch for corpus
   jurisdictions target `official_sources` / official host maps before
   commercial search or archives, unless an explicit recovery or historical
   mode is engaged.
2. **Fallback transparency:** every multi-method fetch records methods tried
   and the method that succeeded (or final failure).
3. **WARC pointers are first-class:** Common Crawl hits expose filename +
   offset (+ length) sufficient to re-fetch the same record; local WARC tools
   preserve Target-URI and dates.
4. **Resume safety:** job state must not mark an item processed unless durable
   payload was stored or explicitly skipped.
5. **Auth boundaries:** CourtListener tokens ≠ PACER passwords; PACER paths
   fail closed without credentials.
6. **Status fields are data, not vibes:** `effective_date` / version windows
   come from official metadata or deterministic parse; `status_confidence`
   and `status_source` explain provenance of the classification.
7. **CID is portable identity** for published packages; pins and HF paths are
   location/publication concerns.
8. **Enrichment never silently becomes evidence:** derived layers reference
   sources; strict IR validation rejects dangling `source_ref`.
9. **Manifests inventory pieces:** binder/docket/workspace packages enumerate
   components so consumers do not reconstruct membership by directory walk
   alone.
10. **Thin wrappers stay thin:** MCP/CLI invoke domain APIs; contracts live in
    processors packages.

## 12. Rationale and decisions

| Topic | Summary | ADR / source |
| --- | --- | --- |
| Content identity | Packages and records use CID over path/URL | [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) |
| Unified web API | Single provider-neutral envelope reduces ad hoc engine wiring | `web_archiving/contracts.py`, `unified_api.py` |
| Ordered archive fallbacks | Legal sites often block automation; archives preserve historical law | `common_crawl_scraper.py`, `unified_web_scraper.py` |
| Jurisdiction protocol split | Discovery/fetch/parse/hierarchy/status/CID/publish as separate protocols | `legal_corpus/interfaces.py` |
| RECAP vs PACER | Free redistributed archive vs paid credentialed system | `recap_archive_scraper.py`, `courtlistener_ingestion.py` |
| Shared fetch cache | Cross-scraper URL cache cuts load and enables offline resume | `shared_fetch_cache.py` |
| Recovery promotion | Citation gaps close via manifest → canonical merge with optional HF publish | `legal_source_recovery_promotion.py` |
| Enrichment layering | Reasoner/KG apply with source_ref and rollback | `legal_data/reasoner/` |

Alternatives rejected (brief):

- **Search-only legal ingest** — rejected: snippets lack hierarchy, status, and
  durable bytes.
- **Always-live scrape without archives** — rejected: brittle against blocks and
  loses historical versions.
- **Single auth blob for CourtListener+PACER** — rejected: different terms,
  liability, and rate models.
- **In-place LLM overwrite of statute text** — rejected: destroys evidence
  auditability.

## 13. Security, privacy, and trust boundaries

- **Trust boundaries:** public web and archive providers are untrusted for
  *authenticity claims* beyond “this is what the channel returned”; official
  sources are preferred for authority but still recorded with retrieval
  metadata. Operator-supplied PACER exports are trusted as **operator inputs**,
  not as cryptographically notarized court feeds.
- **Secrets:** PACER passwords, CourtListener tokens, Cloudflare API tokens, HF
  tokens—env/vault only; never embed in manifests or CIDs of public packages.
- **PACER compliance:** credentialed access may incur fees and is subject to
  PACER terms; code paths that purchase documents must not be enabled without
  operator intent.
- **PII:** dockets and emails may contain sensitive personal data; packaging and
  HF publication are operator-controlled side effects.
- **What this layer must not claim:** that a GraphRAG edge or deontic extraction
  is “the law”; that a CID pin equals court authentication; that RECAP equals
  complete PACER coverage.

## 14. Observability and operations

- Execution traces on unified API responses; circuit breakers and retries in
  orchestration.
- Scraper metrics / `@monitor` hooks on legal scrapers where present.
- Job status in `ScrapingState` (`initialized` → `running` → `completed` /
  `failed`) with error lists.
- Verifiers (e.g. state laws / federal register verifiers) report fallback
  ratios and quality signals for gate thresholds.
- Operator guides: `docs/LEGAL_SCRAPERS_COMMON_CRAWL_GUIDE.md`,
  `docs/WEB_ARCHIVING_MIGRATION_GUIDE.md`,
  `mcp_server/tools/legal_dataset_tools/COURTLISTENER_API_GUIDE.md`,
  `docs/AGENTIC_LEGAL_SCRAPER_DAEMON.md`.

## 15. Validation

Commands and checks that prove this guide still matches the repository.
Prefer **bounded, offline** checks.

```bash
# Declared output present and non-empty; keyword coverage
test -s docs/architecture/processing/WEB_ARCHIVING_AND_LEGAL_INGESTION.md
rg -n 'official|Common Crawl|WARC|effective|citation|CID|publication' \
  docs/architecture/processing/WEB_ARCHIVING_AND_LEGAL_INGESTION.md

# Core packages and contracts exist
test -e ipfs_datasets_py/processors/web_archiving/unified_api.py
test -e ipfs_datasets_py/processors/web_archiving/contracts.py
test -e ipfs_datasets_py/processors/web_archiving/common_crawl_integration.py
test -e ipfs_datasets_py/processors/legal_scrapers/common_crawl_scraper.py
test -e ipfs_datasets_py/processors/legal_scrapers/recap_archive_scraper.py
test -e ipfs_datasets_py/processors/legal_scrapers/legal_corpus/interfaces.py
test -e ipfs_datasets_py/processors/legal_scrapers/shared_fetch_cache.py
test -e ipfs_datasets_py/processors/legal_scrapers/scraping_state.py
test -e ipfs_datasets_py/processors/legal_data/courtlistener_ingestion.py
test -e ipfs_datasets_py/processors/legal_data/docket_dataset.py
test -e ipfs_datasets_py/processors/legal_data/workspace_packaging.py
test -e ipfs_datasets_py/mcp_server/tools/web_archive_tools/create_warc.py

# Optional focused collection (may skip without optional deps)
# pytest tests/ -q --collect-only -k 'web_archive or warc or courtlistener or recap or legal_scraper' 2>/dev/null | head
```

**Known validation limits:** live Common Crawl, CourtListener, PACER, and HF
publish paths need network and secrets; CI typically uses fixtures and mocks.
Optional native tools (wget/squidwarc, Playwright) may be absent in minimal
environments—capability probes document degradation rather than implying full
system proof.

## 16. Related documentation

| Document | Relationship |
| --- | --- |
| [architecture/README.md](../README.md) | Architecture hub |
| [DOMAIN_MAP.md](../DOMAIN_MAP.md) | Processing / web_archiving / legal ownership |
| [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) | Cross-domain hop language |
| [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) | CID and provenance rules |
| [ARCHITECTURE_GUIDE_TEMPLATE.md](../ARCHITECTURE_GUIDE_TEMPLATE.md) | Guide contract |
| [LEGAL_SCRAPERS_COMMON_CRAWL_GUIDE.md](../../LEGAL_SCRAPERS_COMMON_CRAWL_GUIDE.md) | Operator Common Crawl usage |
| [WEB_ARCHIVING_MIGRATION_GUIDE.md](../../WEB_ARCHIVING_MIGRATION_GUIDE.md) | Legacy → unified API migration |
| Sibling `docs/architecture/processing/*` | Pipeline / file-multimedia index (when present) |
| In-package guides under `legal_scrapers/` and `legal_dataset_tools/` | Feature-level detail |

## 17. Document history

| Date | Change |
| --- | --- |
| 2026-08-03 | Initial canonical guide for `IPFSDOC-021` / `WebArchiveLegalEvidencePipeline@1` |
