# File conversion, PDF/OCR, and multimedia processing

| Field | Value |
| --- | --- |
| Interface | `FileMultimediaProcessing@1` |
| Task | `IPFSDOC-020` |
| Status | `canonical` |
| Owner | architecture / processing domain |
| Source of truth | `ipfs_datasets_py/processors/file_converter/`; `processors/specialized/pdf/`; `processors/specialized/media/`; `processors/multimedia/`; `processors/adapters/{pdf,file_converter,multimedia}_adapter.py`; MCP tools under `mcp_server/tools/{pdf_tools,file_converter_tools,media_tools}/`; git submodules for omni/convert_to_txt |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent, operator |
| Related | [PROCESSOR_PIPELINE.md](PROCESSOR_PIPELINE.md), [DOMAIN_MAP.md](../DOMAIN_MAP.md), [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md), [INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md) |
| Review cadence | semi-annual or after PDF/converter/media submodule changes |

> **Lifecycle note:** Preferred **specialized** and **native converter** paths
> coexist with **deprecated root modules**, **legacy backends**, and **git
> submodules**. This guide maps current code paths and optional tool
> requirements. Do **not** claim migration complete while dual PDF entry
> points, multiple `BatchProcessor` types, and deprecated converter backends
> remain.

## 1. Purpose

This guide answers: **how files and multimedia are detected, converted,
OCR’d, transcribed, and batched**—including canonical imports, optional
native tools, adapters into the processor pipeline, output/provenance
handoff, and failure modes.

Pipeline-wide protocols and registry ownership live in
[PROCESSOR_PIPELINE.md](PROCESSOR_PIPELINE.md).

## 2. Audience

- **Primary:** developers integrating convert/PDF/media paths.
- **Secondary:** operators provisioning FFmpeg/Tesseract/submodules; agents
  choosing MCP tools vs Python APIs.

## 3. Scope and non-goals

### In scope

- Unified **file conversion** (`file_converter`) and backend selection.
- **PDF** pipeline (`specialized.pdf`) and **OCR** multi-engine stack.
- **Multimedia**: FFmpeg, yt-dlp, MediaProcessor, advanced media, submodules.
- Batching and **resource limits** for conversion and PDF/media jobs.
- Adapters and MCP tool surfaces for file/PDF/media.
- Optional dependency matrix and degradation.
- Output shapes and provenance handoff for these families.

### Non-goals

- UniversalProcessor protocol duality (covered in pipeline guide).
- Web archiving / legal scrapers (sibling guide).
- GraphRAG website processors beyond PDF GraphRAG stages.
- Full omni_converter_mk2 internal plugin catalog (submodule-owned).
- Formal proof / IR compilation of extracted text.

## 4. Context

Three overlapping product needs share the processing domain:

1. **Turn arbitrary files into text/metadata** for datasets and RAG
   (`file_converter`).
2. **Deep PDF understanding** with OCR, chunking, embeddings, and GraphRAG
   (`specialized.pdf.PDFProcessor`).
3. **A/V acquisition and transform** via host tools and Python wrappers
   (`processors.multimedia`, optional package-level multimedia submodules).

Historically, converters lived in git submodules and PDF/OCR lived as flat
modules under `processors/`. Consolidation moved PDF/OCR/batch into
`specialized/` and introduced a pluggable `FileConverter`, while leaving
compat shims and submodule backends in place.

## 5. Ownership and boundaries

| Owns | Does not own |
| --- | --- |
| File conversion API and native extractors | Upstream omni/markitdown product roadmaps |
| PDF stage pipeline, OCR engine wrappers | Host package installs for Tesseract/FFmpeg system packages |
| Multimedia wrappers and MediaProcessor coordination | yt-dlp site extractor maintenance |
| Specialized media helpers for GraphRAG A/V | Vector index engines (`vector_stores`) |
| MCP tool wrappers for convert/PDF/media | MCP transport and auth |

**Inbound:** Python API, MCP `file_converter_tools` / `pdf_tools` /
`media_tools`, CLIs, UniversalProcessor adapters.

**Outbound:** optional submodules under `processors/multimedia/` and
package `multimedia/`; system binaries; LLM/embedding routers; IPLD storage;
downstream retrieval/knowledge domains.

## 6. Components

### 6.1 File conversion

| Component | Path | Role |
| --- | --- | --- |
| `FileConverter` | `file_converter/converter.py` | Unified async/sync convert API |
| `ConversionResult` | same | `text`, `metadata`, `backend`, `success`, `error` |
| Backends | `file_converter/backends/` | `native`, `markitdown`, `omni`, IPFS-related helpers |
| Format detection | `format_detector.py` | Extension/MIME/content hints |
| Text extractors | `text_extractors.py`, office extractors | Per-format extraction |
| Pipeline primitives | `pipeline.py` | `Result`/`Error` outcomes, stream processing |
| Batch + limits | `batch_processor.py` | `ResourceLimits`, concurrency, cache |
| KG / embedding hooks | `knowledge_graph_integration.py`, `vector_embedding_integration.py` | Optional post-convert enrichment |
| Archive handler | `archive_handler.py` | Zip/tar family extraction |
| Deprecation helpers | `deprecation.py` | Backend deprecation warnings |

**Backends:**

| Backend | Source | Status |
| --- | --- | --- |
| `native` | in-repo extractors | Preferred long-term; always attemptable without submodules |
| `markitdown` | `convert_to_txt_based_on_mime_type` integration | Present; **deprecated** for removal (warnings cite migration to `native`) |
| `omni` | `omni_converter_mk2` | Present; **deprecated** similarly; rich metadata/batch |
| `auto` | selection order in code | **Current auto order:** markitdown → omni → native (see §8.1 discrepancy) |

### 6.2 PDF and OCR

| Component | Path | Role |
| --- | --- | --- |
| `PDFProcessor` | `specialized/pdf/pdf_processor.py` | 10-stage PDF → GraphRAG-oriented pipeline |
| OCR engines | `specialized/pdf/ocr_engine.py` | `OCREngine` ABC; Surya, Tesseract, EasyOCR, TrOCR |
| `MultiEngineOCR` | same | Multi-engine selection/fallback |
| Entity / LLM / batch engines | `entity_extraction_engine.py`, `llm_optimize_engine.py`, `batch_processing_engine.py`, `cross_document_engine.py` | Stage helpers and MCP-facing functions |
| Compat shims | `processors/pdf_processor.py`, `ocr_engine.py` | Deprecated re-exports → specialized.pdf |
| Lazy package export | `processors/__init__.py` `__getattr__` | Still routes some PDF names through `pdf_processing` |

**PDF pipeline stages (as implemented/documented on `PDFProcessor`):**

1. PDF input validation  
2. Decomposition (layers, content, images, metadata)  
3. IPLD structuring  
4. OCR processing  
5. LLM optimization / chunking  
6. Entity extraction  
7. Vector embedding  
8. GraphRAG integration  
9. Cross-document analysis  
10. Query interface setup  

Stages are async-oriented; optional ML/embeddings/cross-doc flags on
constructor control depth (`enable_embeddings`, `use_real_ml_models`,
`enable_cross_document_analysis`, monitoring/audit flags).

### 6.3 Multimedia

| Component | Path | Role |
| --- | --- | --- |
| `FFmpegWrapper` | `multimedia/ffmpeg_wrapper.py` | Convert, info, filters, mux/demux, stream helpers |
| `YtDlpWrapper` | `multimedia/ytdlp_wrapper.py` | Download/metadata for many sites |
| `MediaProcessor` | `multimedia/media_processor.py` | Coordinates FFmpeg + yt-dlp; pydantic models; memory trim |
| Engine modules | `ffmpeg_*_engine.py`, `ytdlp_download_engine.py` | Focused operations used by MCP tools |
| Advanced media | `specialized/media/advanced_processing.py` | Whisper / speech_recognition / OpenCV / ffmpeg for GraphRAG A/V |
| Email / Discord / takeout | `multimedia/email_*`, `discord_wrapper.py`, … | Adjacent media-ish ingest (not full graph pipeline) |
| Submodule trees | `multimedia/omni_converter_mk2`, `multimedia/convert_to_txt_based_on_mime_type` | Optional checkouts; also mirrored under package `ipfs_datasets_py/multimedia/` |

Package-level `ipfs_datasets_py/multimedia/` holds the same submodule paths
for integration boundary purposes ([INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md)).
Empty checkouts are **availability** issues, not missing domains.

### 6.4 Adapters and MCP

| Surface | Path |
| --- | --- |
| PDF adapter | `adapters/pdf_adapter.py` → specialized.pdf → deprecated → FileConverter fallback |
| File converter adapter | `adapters/file_converter_adapter.py` |
| Multimedia adapter | `adapters/multimedia_adapter.py` |
| MCP PDF tools | `mcp_server/tools/pdf_tools/*` (ingest, OCR-related, batch, query, forms, …) |
| MCP file converter tools | `mcp_server/tools/file_converter_tools/*` |
| MCP media tools | `mcp_server/tools/media_tools/*` (ffmpeg_*, ytdlp_download) |

## 7. Canonical imports

| Intent | Canonical | Compatibility |
| --- | --- | --- |
| Convert file to text | `from ipfs_datasets_py.processors.file_converter import FileConverter, ConversionResult` | Multimedia `UnifiedConverter` (stubs/limited); direct submodule APIs |
| Prefer native backend | `FileConverter(backend='native')` | `backend='auto'` currently may select markitdown/omni first |
| PDF processor | `from ipfs_datasets_py.processors.specialized.pdf import PDFProcessor` | `processors.pdf_processor` (deprecated); some lazy exports via `pdf_processing` |
| OCR | `from ipfs_datasets_py.processors.specialized.pdf import MultiEngineOCR, TesseractOCR, SuryaOCR, EasyOCR, TrOCREngine` | `processors.ocr_engine` (deprecated) |
| Batch PDF/jobs | `from ipfs_datasets_py.processors.specialized.batch import BatchProcessor` | root `batch_processor` shim; `file_converter.batch_processor.BatchProcessor` for convert-only batches |
| FFmpeg / yt-dlp | `from ipfs_datasets_py.processors.multimedia import FFmpegWrapper, YtDlpWrapper` | MCP media tools wrap engines |
| Media coordinator | `from ipfs_datasets_py.processors.multimedia import MediaProcessor` | Requires `pydantic` |
| Pipeline registration | adapters + [PROCESSOR_PIPELINE.md](PROCESSOR_PIPELINE.md) registry notes | Dual registry globals |

## 8. End-to-end flows

### 8.1 File conversion happy path

```text
Caller
  -> FileConverter(backend='auto'|'native'|…)
  -> convert(path_or_url) / convert_sync / convert_batch
  -> FormatDetector + backend extract
  -> ConversionResult(text, metadata, backend, success, error)
  -> optional: archive extract, KG pipeline, vector pipeline, IPFS accelerate helper
```

**Discrepancy (document as current tree):**

- Deprecation utilities **recommend** migrating to `backend='native'`.
- `FileConverter` **`auto` selection** still tries **markitdown, then omni,
  then native**. Callers who want the recommended backend must pass
  `backend='native'` explicitly until auto order is changed in code.

### 8.2 PDF → GraphRAG artifact happy path

Aligned with [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) Flow A:

```text
Caller / MCP pdf_ingest_to_graphrag
  -> PDFProcessor.process_pdf(pdf_path, metadata=…)
  -> stages 1–10 (validate → … → query setup)
  -> dict with status, document_id, ipld_cid, entity/relationship counts,
     stages_completed / errors as implemented
```

OCR stage uses `MultiEngineOCR` when images/scanned pages need recognition.
LLM and embedding stages depend on optional ML configuration.

### 8.3 Multimedia happy paths

**Local media transform:**

```text
Caller
  -> FFmpegWrapper.convert_* / info / filters
  -> output media file + metadata
```

**Remote media acquisition:**

```text
Caller
  -> YtDlpWrapper.download_* / extract info
  -> media file(s) on disk + info dict
  -> optional FFmpeg post-process via MediaProcessor
```

**GraphRAG-oriented A/V:**

```text
Caller
  -> specialized.media advanced processing
  -> Whisper / speech_recognition / frame extract (optional deps)
  -> text/transcript + media metadata for graph ingest
```

### 8.4 Adapter path (optional façade)

```text
UniversalProcessor / registry
  -> PDFProcessorAdapter | FileConverterProcessorAdapter | MultimediaProcessorAdapter
  -> domain implementation
  -> root ProcessingResult (KG + content + metadata)   # see pipeline guide dual types
```

Adapters are **not** required for MCP tools that call domain classes
directly.

## 9. Detection, batching, and resource controls

### 9.1 Detection

| Layer | Mechanism |
| --- | --- |
| Pipeline input detection | root/core detectors (URL, file, folder, IPFS) — pipeline guide |
| File conversion | `FormatDetector`, extension maps, extractor registry |
| PDF adapter | `.pdf` suffix, URL containing `.pdf`, existing file suffix |
| Multimedia adapter | video/audio extensions; youtube/vimeo/… host patterns |
| OCR | image bytes / page images from PDF decomposition |

Detection is heuristic. Misclassified Office/ZIP containers and
extension-less blobs should be handled by format detectors or explicit
options—not assumed perfect.

### 9.2 Batching

| Family | API | Resource controls |
| --- | --- | --- |
| File conversion | `FileConverter.convert_batch`, `file_converter.BatchProcessor` | `ResourceLimits`: `max_concurrent` (default 5), `timeout_seconds`, `max_file_size_mb`, optional `max_memory_mb`; `anyio.CapacityLimiter` |
| Specialized batch | `specialized.batch.BatchProcessor` | `max_workers` (default ≤ cpu, max 8 default), `max_memory_mb` (≥512), job queue, `stop_processing(timeout)` |
| PDF batch engine | `pdf_batch_process` / batch processing engine | PDF-oriented batching over documents |
| UniversalProcessor | `process_batch` | `parallel_workers` (root config) |
| FFmpeg batch | `ffmpeg_batch` engine / MCP `ffmpeg_batch` | tool-specific batching |

Name collisions: always import from the **module** that matches the workload
(convert vs PDF job queue vs media).

### 9.3 Async expectations

| API | Async model |
| --- | --- |
| `FileConverter.convert` | async (`anyio`); `convert_sync` wrapper |
| `PDFProcessor.process_pdf` | async; examples use `anyio.run` |
| FFmpeg/yt-dlp wrappers | mix of sync subprocess and async engines—check callee |
| MediaProcessor | async coordination patterns with optional monitoring decorator |
| MCP tools | typically async tool functions wrapping domain code |

## 10. Optional tools matrix

| Tool / extra | Used for | Probe / flag pattern | If missing |
| --- | --- | --- | --- |
| System **FFmpeg** | convert, info, filters, mux | wrapper availability constants | convert/info fails; multimedia adapter limited |
| **yt-dlp** | URL download | import / YTDLP_AVAILABLE | download path unavailable |
| **Tesseract** | OCR engine | engine `available` after init | MultiEngineOCR skips engine |
| **Surya / EasyOCR / TrOCR** | OCR alternatives | optional model imports | same |
| **Whisper** / speech_recognition | transcription | `HAS_WHISPER`, `HAS_SPEECH_RECOGNITION` | advanced media degrades |
| **OpenCV** | frames | `HAS_OPENCV` | frame path unavailable |
| **pydantic** | MediaProcessor models | import error | MediaProcessor not exported |
| **omni_converter_mk2** submodule | omni backend / plugins | checkout + import | auto skips omni |
| **convert_to_txt…** submodule | markitdown backend | checkout + import | auto skips markitdown |
| **IPFS** backend / kit | content-addressed convert/PDF storage | env + kit optional | local-only results; no CID |
| Embeddings / LLM routers | PDF stages 5–8 | constructor flags + deps | stages skipped/degraded; check stage lists |
| **numpy** | some scoring / vectors | optional | fallbacks or errors per call site |

System packages are **outside** Python extras; documenting an import path
does not install Tesseract or FFmpeg.

## 11. Contracts

### 11.1 File conversion

| | |
| --- | --- |
| **Input** | filesystem path or URL (backend-dependent); options per backend |
| **Output** | `ConversionResult` with text + metadata + backend id |
| **Success** | `success is True` and `error is None` (caller should still check empty text) |
| **Failure** | `success False`, `error` message; batch items may partially fail |

### 11.2 PDF

| | |
| --- | --- |
| **Input** | PDF path (primary); metadata dict; constructor feature flags |
| **Output** | result dict including status, identifiers, counts, stage info |
| **Identity** | `document_id`, optional `ipld_cid` when IPLD storage configured |
| **Partial** | non-fatal stage failures may leave `stages_completed` incomplete |

### 11.3 OCR

| | |
| --- | --- |
| **Input** | image bytes / page images |
| **Output** | dict with text, confidence, engine id, optional boxes |
| **Multi-engine** | tries available engines; unavailable engines skipped |
| **Unavailable engine** | init sets `available=False`; extract raises if forced on dead engine |

### 11.4 Multimedia

| | |
| --- | --- |
| **Input** | media paths, stream URLs, or site URLs |
| **Output** | files on disk + metadata/info structures |
| **Side effects** | large temp/output files; network download; CPU for transcode |
| **Coordinator** | MediaProcessor requires pydantic and available backends |

### 11.5 Output / provenance handoff

| Artifact | Handoff target | Notes |
| --- | --- | --- |
| Converted `text` | datasets, KG builders, embedding pipelines | Caller attaches source path/URL for lineage |
| PDF `ipld_cid` / `document_id` | storage / GraphRAG / query tools | Content address ≠ proof |
| Entities/relationships | knowledge_graphs / vector stores | May be empty if stages disabled |
| Media transcripts | GraphRAG / file_converter-like text consumers | Optional Whisper path |
| Operational lineage | `analytics.ProvenanceManager` | Optional; invoke explicitly |
| Adapter `ProcessingResult` | UniversalProcessor consumers | Root protocol shape; dual-type caution |

## 12. Failure modes

| Failure | Behavior | Guidance |
| --- | --- | --- |
| Backend missing under `auto` | fall through markitdown → omni → native | Prefer explicit `native` if submodules empty |
| Deprecated backend used | `FileConverterDeprecationWarning` | Plan migration to native |
| PDF specialized import fails | adapter falls back to deprecated module then FileConverter | Expect reduced stage fidelity on FileConverter fallback |
| No OCR engines available | OCR stage weak/empty text for scans | Install at least one engine; treat scan PDFs as degraded without OCR |
| FFmpeg not on PATH | convert fails | Operator install; not fixed by pip alone in many environments |
| yt-dlp site change / block | download error | Dependency/external; retry or alternate source |
| `pydantic` missing | MediaProcessor import fails | Install pydantic or use wrappers directly |
| Submodule empty | omni/markitdown backends unavailable | `git submodule update --init` or use native |
| Memory pressure on batch | throttle / job failure (`ResourceError` classification in infra) | Lower `max_concurrent` / `max_workers` / file size limits |
| Timeout | item fails; batch continues if designed so | Raise limits only with care |
| Partial PDF pipeline | status/errors + incomplete stages | Do not assume embeddings/graph exist |
| Dual BatchProcessor confusion | wrong class imported | Use fully qualified imports |
| Stub multimedia UnifiedConverter | incomplete adapters noted in multimedia `__init__` | Use FileConverter or wrappers, not stubs |

## 13. Extension points

1. **New file format:** add extractor under `file_converter` (native path),
   register with `ExtractorRegistry` / format detector; tests for round-trip
   text; avoid adding only an omni plugin if native is the supported surface.
2. **New OCR engine:** subclass `OCREngine`, implement `_initialize` and
   `extract_text`, register with `MultiEngineOCR` selection policy; optional
   dep guards.
3. **New media operation:** prefer a focused engine module + thin MCP wrapper;
   keep FFmpeg/yt-dlp subprocess boundaries explicit.
4. **Pipeline exposure:** optional root-protocol adapter + registry entry with
   unique name/priority (see pipeline guide dual-registry warning).
5. **Do not** put convert/PDF logic solely in MCP tool files.

## 14. Invariants

1. **Specialized PDF/OCR paths are preferred** over deprecated root modules.
2. **Native file conversion is the supported long-term backend**; legacy
   backends remain until removed.
3. **Optional binaries and models degrade features**—they do not invent
   successful OCR/transcode.
4. **Partial results are first-class** for multi-stage PDF and multi-item
   batches.
5. **Provenance and CIDs are layered** and optional; conversion success alone
   is not trust evidence.
6. **Submodule emptiness is availability**, not architecture absence.
7. **Duplicate type names** (`BatchProcessor`, historical `PDFProcessor`)
   require explicit module paths—docs must not pretend a single class exists.

## 15. Rationale

| Topic | Why |
| --- | --- |
| Pluggable FileConverter | Migrate off submodule-only converters without big-bang rewrite |
| Specialized PDF package | Consolidate OCR + pipeline away from flat deprecated modules |
| Multi-engine OCR | Different engines vary by script/layout; fallback improves coverage |
| Host FFmpeg/yt-dlp | Mature native ecosystems; wrap rather than reimplement codecs |
| Adapters | Optional participation in UniversalProcessor without rewriting MCP |

## 16. Security, privacy, and trust

- PDF/media paths may embed scripts, huge media, or tracking URLs—treat as
  untrusted.
- yt-dlp and scrapers perform egress network I/O.
- OCR/LLM/embedding stages may load heavy models or call remote routers when
  configured—data residency is a deployment concern.
- Form-filling and legal PDF tools can mutate documents; separate from
  read-only extract paths.
- No convert/OCR outcome grants wallet or admissibility rights.

## 17. Observability

- Domain loggers on converter, PDF processor, multimedia wrappers.
- Optional PDF monitoring/audit flags on `PDFProcessor`.
- MediaProcessor monitoring decorator when infrastructure available.
- MCP tools return structured error payloads for missing processors/deps.

## 18. Validation

```bash
# Task outputs
test -s docs/architecture/processing/PROCESSOR_PIPELINE.md
test -s docs/architecture/processing/FILE_AND_MULTIMEDIA.md
rg -n 'protocol|registry|compat|optional|provenance' docs/architecture/processing/PROCESSOR_PIPELINE.md

# Source anchors
test -e ipfs_datasets_py/processors/file_converter/converter.py
test -e ipfs_datasets_py/processors/file_converter/backends/native_backend.py
test -e ipfs_datasets_py/processors/specialized/pdf/pdf_processor.py
test -e ipfs_datasets_py/processors/specialized/pdf/ocr_engine.py
test -e ipfs_datasets_py/processors/multimedia/ffmpeg_wrapper.py
test -e ipfs_datasets_py/processors/multimedia/ytdlp_wrapper.py
test -e ipfs_datasets_py/processors/adapters/pdf_adapter.py

# Canonical vs deprecated markers still accurate
rg -n 'deprecated|specialized.pdf' ipfs_datasets_py/processors/pdf_processor.py \
  ipfs_datasets_py/processors/ocr_engine.py
rg -n "backend.*=.*'auto'|markitdown|native" \
  ipfs_datasets_py/processors/file_converter/converter.py | head
```

Known limits: OCR/FFmpeg integration tests need host packages; submodule
tests need initialized checkouts; hermetic CI may only collect tests.

## 19. Related documentation

| Document | Relationship |
| --- | --- |
| [PROCESSOR_PIPELINE.md](PROCESSOR_PIPELINE.md) | Protocols, registry, adapters, dual surfaces |
| [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) | PDF ingest hop table |
| [INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md) | Multimedia submodule ownership |
| [DOMAIN_MAP.md](../DOMAIN_MAP.md) | `processors` domain ownership |
| `docs/MULTIMEDIA_*.md`, file conversion plans | Historical migration detail |
| Planned processing README / web-legal guide | Sibling architecture leaves |
