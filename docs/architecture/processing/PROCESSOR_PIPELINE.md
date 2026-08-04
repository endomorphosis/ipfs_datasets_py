# Processor contracts and pipeline architecture

| Field | Value |
| --- | --- |
| Interface | `ProcessorPipelineArchitecture@1` |
| Task | `IPFSDOC-020` |
| Status | `canonical` |
| Owner | architecture / processing domain |
| Source of truth | `ipfs_datasets_py/processors/protocol.py`; `processors/core/{protocol,registry,processor_registry,universal_processor,input_detector}.py`; root `processors/{universal_processor,input_detection,registry}.py`; `processors/adapters/`; `processors/infrastructure/`; package exports in `processors/__init__.py` |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent |
| Related | [FILE_AND_MULTIMEDIA.md](FILE_AND_MULTIMEDIA.md), [DOMAIN_MAP.md](../DOMAIN_MAP.md), [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md), [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md), [INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md) |
| Review cadence | semi-annual or after protocol/registry migration changes |

> **Lifecycle note:** The processors package is in an **active dual-surface
> migration**. Root-level and `core/` types, two registry modules, and two
> `UniversalProcessor` implementations **coexist**. This guide maps that
> reality. Do **not** treat the transition as complete while duplicate
> protocols, result types, detectors, registries, and entry points remain.

## 1. Purpose

This guide answers: **how processing is contracted, registered, detected,
routed, batched, adapted, and handed off**—including which imports are
canonical, which are compatibility shims, and where async and resource
controls apply.

It is the pipeline contract page for the processing domain. File conversion,
PDF/OCR, and multimedia paths are detailed in
[FILE_AND_MULTIMEDIA.md](FILE_AND_MULTIMEDIA.md). Web archive and legal
ingestion are owned by a sibling guide (`WEB_ARCHIVING_AND_LEGAL_INGESTION.md`).

## 2. Audience

- **Primary:** developers and agents implementing or routing processors.
- **Secondary:** architects placing new ingest paths; operators diagnosing
  optional-dep failures.

## 3. Scope and non-goals

### In scope

- Dual root vs core **protocols**, **results**, and **InputType** enums.
- **Registry ownership**, global registry split, and registration APIs.
- **Canonical vs compatibility** import paths and deprecation shims.
- **Input detection**, routing, batching, adapters, auto-registration.
- **Async** expectations (`anyio`), retries, circuit breakers, resource knobs.
- **Output / provenance** handoff shapes to retrieval, storage, and analytics.
- **Failure modes** for missing processors, dual types, and optional tools.

### Non-goals

- Full PDF/OCR/media algorithm detail → [FILE_AND_MULTIMEDIA.md](FILE_AND_MULTIMEDIA.md).
- Web archival / legal scrapers / Common Crawl → sibling web/legal guide.
- MCP transport framing → MCP architecture leaves; tools are thin wrappers.
- Formal IR identity, proof, or authorization → `logic` domain.
- Vector index backends → `vector_stores` / retrieval guides.

## 4. Context

`ipfs_datasets_py.processors` is the largest processing/ingest domain: PDF,
OCR, file conversion, multimedia wrappers, GraphRAG website processors, batch
pipelines, scrapers, and adapters. A unified architecture introduced:

1. A **protocol** so specialized processors can be discovered and routed.
2. A **registry** for priority-based selection.
3. **Input detection** for automatic classification.
4. A **UniversalProcessor** entry point for detect → select → process.
5. **Adapters** wrapping legacy domain classes into the protocol.

That work was not finished as a single type surface. The tree still exports
**two protocol families**, **two registry modules with independent global
singletons**, and **two UniversalProcessor classes**. Adapters currently
implement the **root** protocol (`can_process`) while registration often
targets the **core** registry API. Callers and agents must treat this as a
**compat period**, not a completed unification.

## 5. Ownership and boundaries

| Owns | Does not own |
| --- | --- |
| Processor protocols, registry, detection, adapters under `processors/` | MCP JSON-RPC / tool registration (`mcp_server`) |
| Domain processors (PDF, media, file conversion, scrapers, batch) | Formal IR identity / digests (`logic.ir_core`) |
| Processing metadata and stage results inside processor outputs | Vector store engine selection (`vector_stores`) |
| Optional-tool probes (OCR, FFmpeg, yt-dlp, backends) | Upstream binary policy for Tesseract/FFmpeg/etc. |
| Compat re-exports and deprecation warnings for moved modules | Package-wide `initialize()` / RouterDeps lifecycle (see dependency guide) |

**Inbound callers:** Python API (`processors` package), domain CLIs
(`processors.cli`, package CLIs), MCP tool families (`pdf_tools`,
`file_converter_tools`, `media_tools`, data processing tools),
`UniversalProcessor` / adapters.

**Outbound dependencies:** optional OCR/LLM stacks, multimedia submodules,
IPFS/IPLD helpers under `processors.storage`, embeddings/GraphRAG engines,
`analytics.data_provenance` when lineage is recorded, external network for
URL/yt-dlp paths.

## 6. Components

### 6.1 Layout (current tree)

```text
ipfs_datasets_py/processors/
  protocol.py                 # ROOT protocol + rich result types  (compat surface)
  input_detection.py          # ROOT InputDetector
  universal_processor.py      # ROOT UniversalProcessor + ProcessorConfig
  registry.py                 # DEPRECATED shim → core.registry
  core/
    protocol.py               # CORE async protocol + ProcessingContext
    input_detector.py         # CORE detector → ProcessingContext
    registry.py               # Consolidated registry (package re-export target)
    processor_registry.py     # Parallel registry still used by core UniversalProcessor
    universal_processor.py    # CORE async UniversalProcessor
  adapters/                   # Root-protocol adapters + auto_register
  infrastructure/             # caching, error_handling, monitoring, profiling
  specialized/{pdf,batch,media,multimodal,graphrag,web_archive}/
  file_converter/             # Unified conversion API
  multimedia/                 # FFmpeg, yt-dlp, MediaProcessor, submodules
  engines/                    # LLM / query engines used by pipelines
```

### 6.2 Component roles

| Component | Path | Role |
| --- | --- | --- |
| Root protocol | `processors/protocol.py` | `ProcessorProtocol` with `can_process` / `process` / `get_supported_types`; typed `KnowledgeGraph`, `VectorStore`, `ProcessingMetadata`, `ProcessingResult` |
| Core protocol | `processors/core/protocol.py` | Async protocol with `can_handle(context)` / `process(context)` / `get_capabilities`; `ProcessingContext`; dict-oriented `ProcessingResult` |
| Root detector | `processors/input_detection.py` | Classifies URL/file/folder/IPFS/text; format helpers for media/docs |
| Core detector | `processors/core/input_detector.py` | Builds `ProcessingContext` with format/MIME/session metadata; magic-byte hints |
| Root UniversalProcessor | `processors/universal_processor.py` | Detect → registry select → process; `ProcessorConfig` (cache, workers, timeout, circuit breaker); batch results |
| Core UniversalProcessor | `processors/core/universal_processor.py` | Async detect → `get_processors` → retry/fallback; requires `anyio` |
| Core registry (exported) | `processors/core/registry.py` | `ProcessorRegistry`, `ProcessorEntry`, `get_global_registry` — claimed consolidation target |
| Core processor_registry | `processors/core/processor_registry.py` | Second registry implementation + **separate** global singleton; imported by core `UniversalProcessor` |
| Compat registry shim | `processors/registry.py` | Deprecation warning; re-exports core.registry |
| Adapters | `processors/adapters/*` | Bridge domain classes to **root** protocol |
| Auto-register | `processors/adapters/auto_register.py` | Best-effort register into global registry |
| Infrastructure | `processors/infrastructure/*` | Retry/circuit breaker, cache, health monitoring used by root UP |

## 7. Dual protocol map (critical)

### 7.1 Side-by-side contracts

| Concern | Root (`processors.protocol`) | Core (`processors.core.protocol`) |
| --- | --- | --- |
| Capability check | `async can_process(input_source)` | `async can_handle(context: ProcessingContext)` |
| Process method | `async process(input_source, **options)` | `async process(context: ProcessingContext)` |
| Discovery metadata | `get_supported_types() -> list[str]` | `get_capabilities() -> dict` |
| Input envelope | raw path/URL/str | `ProcessingContext` (type, source, metadata, options, session_id) |
| Result success model | `ProcessingMetadata.status` (`SUCCESS`/`PARTIAL`/`FAILED`/`SKIPPED`) + structured fields | `success: bool` + `errors`/`warnings` lists |
| Knowledge graph | `KnowledgeGraph` dataclass (Entity/Relationship) | `dict` with entities/relationships keys |
| Vectors | `VectorStore` dataclass | `List[List[float]]` |
| Content payload | `content: dict` + `extra` | primarily `raw_output` + `metadata` |
| IPFS input enum | `InputType.IPFS` | `InputType.IPFS_CID`, `InputType.IPNS` (no single `IPFS`) |
| Unknown type | `InputType.UNKNOWN` | not present on core enum |
| Protocol check helper | `@runtime_checkable` Protocol | `is_processor()` inspects async methods |

### 7.2 Implications

1. **Types are not interchangeable.** Importing `ProcessingResult` from root vs
   core yields different shapes. Downstream code must not assume a single
   schema without converting.
2. **Adapters implement root protocol** (`can_process`), not core
   `can_handle`. Registering them into a core registry that calls
   `can_handle(context)` is a **protocol mismatch** unless a bridge exists in
   the call path. Treat adapter+core-registry combinations as **compat/fragile**,
   not fully unified.
3. **Package `__init__` re-exports** lean root protocol types and
   `core.registry` together—callers can mix symbols from both families in one
   import list.

### 7.3 Canonical import guidance (current)

Prefer explicit modules. When both exist, prefer the **specialized** or
**core.registry** path for *new* registration work, and prefer **domain
classes** (`specialized.pdf`, `file_converter`) for direct processing.

| Intent | Canonical (preferred) | Compatibility / dual |
| --- | --- | --- |
| Package façade | `from ipfs_datasets_py.processors import …` | Mixes root types + core registry |
| Core protocol + context | `from ipfs_datasets_py.processors.core.protocol import …` | Root `processors.protocol` remains widely used by adapters |
| Registry type + register | `from ipfs_datasets_py.processors.core.registry import ProcessorRegistry, get_global_registry` | `processors.registry` (deprecated shim); **also** `core.processor_registry.get_global_registry` (parallel singleton) |
| Root UniversalProcessor + config | `from ipfs_datasets_py.processors.universal_processor import UniversalProcessor, ProcessorConfig` | Core UP: `processors.core.universal_processor` |
| Core convenience | `from ipfs_datasets_py.processors.core import process, process_batch` | Requires `anyio` |
| Adapters | `from ipfs_datasets_py.processors.adapters import …` | Classes may be `None` if optional imports fail |
| PDF | `from ipfs_datasets_py.processors.specialized.pdf import PDFProcessor` | `processors.pdf_processor` (deprecated); lazy `__getattr__` via `pdf_processing` |
| Batch | `from ipfs_datasets_py.processors.specialized.batch import BatchProcessor` | `processors.batch_processor` (deprecated); separate `file_converter.batch_processor` |
| OCR | `from ipfs_datasets_py.processors.specialized.pdf import MultiEngineOCR, …` | `processors.ocr_engine` (deprecated) |

**Do not claim** a single registry singleton or a single protocol is the only
live surface: dual modules remain in-tree.

## 8. Registry ownership

### 8.1 Declared ownership

| Layer | Module | Ownership claim in source |
| --- | --- | --- |
| Consolidated registry | `core/registry.py` | Documented as unified registry combining legacy features; `ProcessorEntry`, stats, enable/disable, priority sort |
| Parallel registry | `core/processor_registry.py` | Still present; **core UniversalProcessor imports this module**, not `registry.py` |
| Package export | `core/__init__.py` | Re-exports **`registry`** (not `processor_registry`) |
| Deprecated root | `processors/registry.py` | Shim to `core.registry` with `DeprecationWarning` (removal target v2.0.0) |

### 8.2 Global registry split (explicit discrepancy)

Both `core.registry` and `core.processor_registry` define:

- module-level `_global_registry`
- `get_global_registry()` that lazy-creates **its own** singleton

Therefore:

```text
processors.core.registry.get_global_registry()
    !=  processors.core.processor_registry.get_global_registry()
```

unless something externally unifies them (nothing in-tree currently does).

| Caller path | Which global it uses |
| --- | --- |
| `from processors.core import get_global_registry` / `adapters.auto_register` | `core.registry` |
| `core.universal_processor.UniversalProcessor()` default | `core.processor_registry` |
| `processors.registry` (compat) | `core.registry` |
| Root `UniversalProcessor` | constructs / accepts `core.registry.ProcessorRegistry` (import path in source) |

**Operational consequence:** adapters registered via `register_all_adapters()`
may not be visible to a default core `UniversalProcessor` instance, and the
reverse may also hold. Always pass an explicit `registry=` when composing
pipelines, or register on the same module that the entry point imports.

### 8.3 Registration API (consolidated `core.registry`)

| Method | Behavior |
| --- | --- |
| `register(processor, priority=None, name=None, enabled=True, capabilities=None, **metadata)` | Inserts `ProcessorEntry`; sorts by priority descending; duplicate **name** raises `ValueError`; warns if not a `ProcessorProtocol` instance |
| `unregister(name)` | Removes by name |
| `get_processor(name)` | Lookup by name |
| `get_processors(context, limit=…)` | **Async**; walks enabled entries by priority; calls each processor’s handle check |
| enable / disable | Toggle without unregistering |
| statistics | Per-entry call/success/failure/time aggregates |

Default priority is **10** unless the processor exposes `get_priority()` or the
caller passes one.

### 8.4 Adapter auto-registration priorities

From `adapters/auto_register.py` (best-effort; failures log and continue):

| Name | Priority | Adapter |
| --- | ---: | --- |
| IPFSProcessor | 20 | `IPFSProcessorAdapter` |
| BatchProcessor | 15 | `BatchProcessorAdapter` |
| SpecializedScraper | 12 | `SpecializedScraperAdapter` |
| PDFProcessor | 10 | `PDFProcessorAdapter` |
| GraphRAGProcessor | 10 | `GraphRAGProcessorAdapter` |
| MultimediaProcessor | 10 | `MultimediaProcessorAdapter` |
| WebArchiveProcessor | 8 | `WebArchiveProcessorAdapter` |
| FileConverterProcessor | 5 | `FileConverterProcessorAdapter` |

Missing optional dependencies skip that adapter; count returned is
`registered / attempted`.

## 9. End-to-end flow

### 9.1 Happy path — root UniversalProcessor

```text
Caller
  -> UniversalProcessor.process(source, **options)   # processors.universal_processor
  -> InputDetector.detect_type / classify              # root detector
  -> registry selection by preferred_processors or capabilities
  -> processor.can_process / process                   # root protocol
  -> optional SmartCache, RetryWithBackoff, CircuitBreaker
  -> ProcessingResult (root shape: KG + VectorStore + content + metadata)
  -> optional downstream: embeddings / vector_stores / ProvenanceManager
```

`ProcessorConfig` knobs: `enable_caching`, `parallel_workers`,
`timeout_seconds` (default 300), `fallback_enabled`, `preferred_processors`,
`max_retries`, `raise_on_error`, cache size/TTL/eviction, monitoring and
circuit-breaker threshold.

### 9.2 Happy path — core UniversalProcessor

```text
Caller (anyio.run / async)
  -> core.UniversalProcessor.process(input_data, context=None, …)
  -> InputDetector.detect → ProcessingContext                 # core detector
  -> await registry.get_processors(context)                  # processor_registry global by default
  -> for each candidate: retries with delay; optional multi-processor merge
  -> ProcessingResult (core shape: success + dict KG + vectors list)
```

Requires **`anyio`**. Supports `timeout` via `anyio.fail_after`,
`use_multiple` aggregation, and `max_processors` limit.

### 9.3 Happy path — direct domain call (often preferred)

Many production paths **bypass** UniversalProcessor:

```text
Caller / MCP tool
  -> specialized.pdf.PDFProcessor.process_pdf(...)
  -> or file_converter.FileConverter.convert(...)
  -> or multimedia.FFmpegWrapper / YtDlpWrapper / MediaProcessor
  -> domain-native result dict / ConversionResult / media metadata
```

This is valid and common. The protocol/registry layer is a **routing façade**,
not a mandatory choke point for every ingest.

### 9.4 Detection

| Detector | Returns | Notes |
| --- | --- | --- |
| Root `InputDetector` | `InputType`, format strings, category helpers (video/audio/doc/archive) | Uses extensions, URL schemes, CID heuristics |
| Core `InputDetector.detect` | `ProcessingContext` | Magic-byte map, MIME via `mimetypes`, session id, format/extension metadata |

Both are imperfect for extension-less paths and multi-format containers
(e.g. ZIP-based Office). File conversion has its own
`FormatDetector` under `file_converter/`.

### 9.5 Batching

| Surface | Path | Controls |
| --- | --- | --- |
| Root UP batch | `UniversalProcessor.process_batch` | `parallel_workers`; returns `BatchProcessingResult` (results + errors + metadata) |
| Core UP batch | `process_batch` convenience / UP methods | anyio concurrency patterns |
| Specialized batch | `specialized.batch.BatchProcessor` | `max_workers`, `max_memory_mb` (≥512), job queue, graceful `stop_processing(timeout)` |
| File converter batch | `file_converter.batch_processor.BatchProcessor` | `ResourceLimits` (`max_concurrent`, `timeout_seconds`, `max_file_size_mb`, memory) + `anyio.CapacityLimiter` |
| Batch adapter | `adapters.batch_adapter` | Treats folders/globs as batch inputs via root protocol |

Multiple classes named `BatchProcessor` exist; import the specialized or
file_converter module explicitly.

### 9.6 Sequence (routing façade)

```text
                 +------------------+
  input -------> | Input detector   |
                 +--------+---------+
                          |
                          v
                 +------------------+     priority order
                 | ProcessorRegistry| ------------------+
                 +--------+---------+                   |
                          |                             v
                          |                   +-------------------+
                          +-----------------> | Adapter / domain  |
                                              | processor         |
                                              +---------+---------+
                                                        |
                          +-----------------------------v----------+
                          | ProcessingResult (root OR core shape)  |
                          +-------------------+--------------------+
                                              |
                    +-------------------------+-------------------------+
                    v                         v                         v
             embeddings/VS              IPLD / storage           ProvenanceManager
```

## 10. Contracts

### 10.1 Inputs

| Input | Type / source | Validation |
| --- | --- | --- |
| Source | path, URL, folder, IPFS CID/URI, raw text/binary | Detector classification; domain validators (e.g. PDF existence) |
| Options | `**options` or `ProcessingContext.options` | Processor-specific; unknown keys often ignored |
| Registry | optional `ProcessorRegistry` instance | Must match protocol family expected by the entry point |
| Config | `ProcessorConfig` (root UP) | Validates workers ≥1, timeout ≥1, cache policy enum, retries ≥0 |

### 10.2 Outputs

| Output | Shape family | Guarantees |
| --- | --- | --- |
| Root `ProcessingResult` | KG + vectors + content + `ProcessingMetadata` | `is_successful()` true for SUCCESS or PARTIAL; errors may still be present |
| Core `ProcessingResult` | `success`, dict KG, vector lists, errors/warnings | `success` flipped false on merged failures / `add_error` |
| Domain native results | e.g. PDF stage dict with `status`, `ipld_cid`, counts | Not automatically coerced to either protocol result |
| Batch aggregate | list of per-item results + error tuples | Partial success is normal; inspect `success_rate()` where available |

### 10.3 Public surfaces

| Surface | Entry |
| --- | --- |
| Python | `ipfs_datasets_py.processors` exports; `processors.core`; domain packages |
| CLI | `processors.cli` / infrastructure CLI; domain CLIs |
| MCP | `mcp_server/tools/{pdf_tools,file_converter_tools,media_tools,…}` thin wrappers |
| Convenience | `core.process`, `core.process_batch` (async, anyio) |

### 10.4 Output and provenance handoff

Processing does **not** own formal IR provenance (`logic.ir_core`) or proof
receipts. Handoff layers:

| Layer | Where | What processing provides |
| --- | --- | --- |
| **Processor metadata** | `ProcessingMetadata` / result `metadata` / stage lists | Processor name/version, timing, errors, resource_usage, stages completed |
| **Content identity** | PDF/IPLD path (`ipld_cid`, `document_id`) | Content-addressed document structure when storage backend present |
| **Operational lineage** | `analytics.data_provenance.ProvenanceManager` | Optional SOURCE/TRANSFORM records; caller must invoke |
| **Retrieval identity** | embeddings / vector IDs / graph entity ids | Downstream of successful extract/embed stages |

**Rules:**

- Successful convert/OCR is **not** authorization or proof.
- Missing provenance recording is normal for ad-hoc CLI use.
- CIDs from IPLD stages are **content addresses**, not theorem attestations
  ([END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md)).

## 11. Async and resource controls

| Control | Where | Behavior |
| --- | --- | --- |
| `anyio` | Core protocol/UP; file_converter batch; media engines | Unified async backends; core UP hard-requires anyio |
| Timeouts | Root `ProcessorConfig.timeout_seconds`; core `timeout=`; ResourceLimits | Per-item or per-process fail_after / timeout |
| Concurrency | `parallel_workers`; `ResourceLimits.max_concurrent`; batch `max_workers` | Capacity limiters / worker pools |
| Memory | batch `max_memory_mb`; media malloc_trim helper on Linux | Throttle / GC; not a hard cgroup |
| Retry | Root infrastructure `RetryConfig` / `RetryWithBackoff`; core UP `max_retries` + delay | Transient errors may retry; permanent should not |
| Circuit breaker | Root UP `CircuitBreaker` when enabled | Opens after threshold failures |
| Cache | Root `SmartCache` (size MB, TTL, lru/lfu/fifo) | Optional result caching |
| Monitoring | `infrastructure.monitoring`, health hooks | Optional metrics/health |

Error classification (`infrastructure.error_handling`):

- `TRANSIENT` — retry candidate  
- `PERMANENT` — bad input / unsupported  
- `RESOURCE` — memory/disk  
- `DEPENDENCY` — missing extra/binary/service  
- `UNKNOWN` — default  

## 12. Optional tools and adapters

### 12.1 Optional dependencies (pipeline-relevant)

| Dependency | Used by | Absence behavior |
| --- | --- | --- |
| `anyio` | Core UP, many async paths | Core UP raises `ImportError` |
| `numpy` | Root `VectorStore.search` | Search raises `RuntimeError` |
| OCR engines (Tesseract, Surya, EasyOCR, TrOCR) | PDF pipeline | Engine marked unavailable; multi-engine falls through |
| FFmpeg binary / wrapper | multimedia | Convert/info fail or adapter skips |
| yt-dlp | media URL download | Download path unavailable |
| `pydantic` | `MediaProcessor` | Import fails; `HAVE_MEDIA_PROCESSOR` false |
| omni / convert_to_txt submodules | file_converter backends | Backend auto-fallback |
| IPFS kit / daemon | IPFS adapter, IPLD storage | Optional; hermetic defaults elsewhere |
| LLM / embedding stacks | PDF GraphRAG stages | Stages skip or degrade when flags/deps off |

### 12.2 Adapter responsibilities

Adapters **wrap** domain implementations and map to root `ProcessingResult`.
They lazy-import domain code so missing deps do not break adapter module
import where guarded.

| Adapter | Domain target | Typical inputs |
| --- | --- | --- |
| `PDFProcessorAdapter` | `specialized.pdf.PDFProcessor` → deprecated `pdf_processor` → `FileConverter` fallback | `.pdf`, PDF URLs |
| `FileConverterProcessorAdapter` | `file_converter.FileConverter` | broad files / some URLs |
| `MultimediaProcessorAdapter` | FFmpeg / yt-dlp / MediaProcessor | video/audio paths and streaming sites |
| `BatchProcessorAdapter` | specialized/root batch + nested UP | folders, globs |
| `GraphRAGProcessorAdapter` | GraphRAG website processors | site URLs |
| `WebArchiveProcessorAdapter` | web archiving engines | archive URLs / WARC-related |
| `IPFSProcessorAdapter` | IPFS content fetch/process | CIDs / ipfs URIs |
| `SpecializedScraperAdapter` | domain scrapers | scraper-specific URLs |

## 13. Failure modes and fallbacks

| Failure | Detection | Visible behavior | Fallback / notes |
| --- | --- | --- | --- |
| No processor matches | empty registry selection | error result / “No suitable processors” | Register adapters or call domain API directly |
| Dual global registries | separate modules | “registered but not found” at runtime | Pass explicit shared registry |
| Protocol mismatch (root adapter vs core `can_handle`) | runtime AttributeError / always-false handle | routing skips or errors | Bridge adapter or use matching UP family |
| Optional adapter ImportError | auto_register catch | warning log; adapter omitted | Feature absent ≠ crash of registration loop |
| Deprecated module import | `DeprecationWarning` | still works via re-export until removal target | Prefer specialized/core paths |
| Transient network | TransientError / retries | retry then fail | Circuit breaker may open |
| Permanent bad input | PermanentError / validation | failed result or raised if `raise_on_error` | Do not retry indefinitely |
| Missing anyio | import guard | core UP unusable | Use root UP or sync domain APIs where available |
| Partial pipeline | stage errors / PARTIAL status | partial KG/content | Inspect errors/warnings/stages_completed |
| Cache miss/disable | config | full recompute | Correctness unaffected |
| Duplicate processor name | register | `ValueError` | Unregister or rename |

**Explicit non-claims:**

- Unification is **not** complete while root and core types both ship.
- Auto-registration is **not** guaranteed at import time; callers must invoke
  `register_all_adapters()` (or manual register).
- Deprecation “removed in v2.0.0” labels are **planned**; shims still function.

## 14. Extension points

To add a processor **correctly** during the dual-surface period:

1. Implement domain logic under the appropriate `specialized/*`,
   `file_converter`, `multimedia`, or domain package—not inside MCP tools.
2. Decide protocol family:
   - Prefer implementing **one** family fully; if targeting core routing,
     implement `can_handle` / `process(context)` / `get_capabilities`.
   - If wrapping legacy APIs like existing adapters, implement root
     `can_process` / `process` / `get_supported_types` and document the bridge.
3. Register on the **same** registry module the chosen UniversalProcessor uses,
   with unique `name` and explicit `priority`.
4. Keep optional deps lazy; fail with `DependencyError` classification when
   appropriate.
5. Return provenance-friendly metadata (source path/URL, processor name,
   timing, errors)—do not invent CIDs or IR digests.
6. Add focused unit tests for `can_*` selection and one process success/failure
   path; update this guide if a dual surface is removed.

**Anti-patterns:**

- Putting business logic only in MCP tool modules.
- Assuming `get_global_registry()` is process-wide unique across modules.
- Silently converting root ↔ core results without documenting field mapping.
- Claiming complete migration while duplicate types remain.

## 15. Invariants

1. **Dual types must be documented as dual** until one family is deleted.
2. **MCP/CLI are thin wrappers** over domain processors.
3. **Optional tools degrade or error**—they do not become proof or authz.
4. **Registry priority is descending** (higher checked first).
5. **Partial success is first-class** (PARTIAL / success with warnings / batch
   partial lists).
6. **Provenance handoff is optional** and layered; processing metadata ≠ IR
   provenance ≠ proof.
7. **Compat shims warn** and re-export; new code must not add new root
   duplicates of specialized modules.

## 16. Rationale and decisions

| Topic | Summary | Source |
| --- | --- | --- |
| Protocol façade | Enable one entry point over many domain processors | `protocol.py`, `core/protocol.py` |
| Priority registry | Deterministic selection among overlapping handlers | `core/registry.py` |
| Adapters | Migrate legacy classes without rewriting all domains | `adapters/` |
| Specialized package | Move PDF/OCR/batch off flat root modules | `specialized/*`, deprecation shims |
| Dual registry modules | Incomplete consolidation; core UP still on `processor_registry` | current imports |

Alternatives rejected (implicit in tree):

- **Hard cutover to core-only types** — not done; adapters still root-shaped.
- **Mandatory UniversalProcessor for all MCP tools** — many tools call domain
  APIs directly for reliability and clearer errors.

## 17. Security, privacy, and trust boundaries

- Processing untrusted files/URLs can execute heavy native tools (FFmpeg,
  OCR, downloaders). Treat paths and URLs as untrusted input.
- Scrapers and yt-dlp perform network I/O; respect site ToS and rate limits
  outside this guide’s scope.
- OCR/LLM stages may send content to local or remote models depending on
  configuration—do not assume data stays local.
- This layer **must not** claim wallet grants, admissibility allow, or formal
  proof from a successful extract.

## 18. Observability and operations

| Mechanism | Path |
| --- | --- |
| Logging | stdlib loggers on registry, UP, adapters |
| Health / monitor | `infrastructure.monitoring` |
| Profiling / debug | `processors.profiling`, `debug_tools` |
| CLI diagnostics | `processors.cli`, infrastructure CLI modules |
| Per-processor stats | `ProcessorEntry.statistics` on consolidated registry |

## 19. Validation

Bounded offline checks for this guide:

```bash
# Declared outputs and keyword coverage
test -s docs/architecture/processing/PROCESSOR_PIPELINE.md
test -s docs/architecture/processing/FILE_AND_MULTIMEDIA.md
rg -n 'protocol|registry|compat|optional|provenance' docs/architecture/processing/PROCESSOR_PIPELINE.md

# Source anchors still present
test -e ipfs_datasets_py/processors/protocol.py
test -e ipfs_datasets_py/processors/core/protocol.py
test -e ipfs_datasets_py/processors/core/registry.py
test -e ipfs_datasets_py/processors/core/processor_registry.py
test -e ipfs_datasets_py/processors/adapters/auto_register.py
test -e ipfs_datasets_py/processors/universal_processor.py
test -e ipfs_datasets_py/processors/core/universal_processor.py

# Dual global registry symbols (expect matches in BOTH modules)
rg -n 'def get_global_registry' ipfs_datasets_py/processors/core/registry.py \
  ipfs_datasets_py/processors/core/processor_registry.py
```

Known validation limits: full integration tests may need optional OCR/FFmpeg
binaries and initialized multimedia submodules; hermetic environments only
prove structure and import graphs.

## 20. Related documentation

| Document | Relationship |
| --- | --- |
| [FILE_AND_MULTIMEDIA.md](FILE_AND_MULTIMEDIA.md) | Conversion, PDF/OCR, media paths |
| [DOMAIN_MAP.md](../DOMAIN_MAP.md) | Domain ownership of `processors` |
| [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) | Ingest and provenance hop tables |
| [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md) | Package import hermeticity and extras |
| [INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md) | Multimedia/Common Crawl submodules |
| `docs/PROCESSORS_*` / `MULTIMEDIA_*` / file conversion plans | Historical migration material—not sole authority |
| Planned `processing/README.md` | Domain hub (later task) |
| Planned web/legal processing guide | Archive and legal ingest |
