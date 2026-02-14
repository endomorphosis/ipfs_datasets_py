# Processors Refactoring Quick Reference

**Status:** Planning  
**Created:** 2026-02-14  
**Full Plan:** [PROCESSORS_REFACTORING_PLAN.md](./PROCESSORS_REFACTORING_PLAN.md)

---

## TL;DR

**Goal:** Create a single entrypoint (`UniversalProcessor`) that automatically routes URLs/files/folders to appropriate processors and outputs standardized knowledge graphs + vectors.

**Current Issues:**
- 8 processor types with inconsistent APIs
- 3+ duplicate GraphRAG implementations (~1,500 lines)
- Multimedia split between processors/ and data_transformation/
- No unified interface or discovery mechanism

**Solution:**
```python
# One import, handles everything
from ipfs_datasets_py.processors import UniversalProcessor

processor = UniversalProcessor()

# Automatic routing based on input type
result = await processor.process("https://example.com")  # → GraphRAG
result = await processor.process("document.pdf")         # → PDF processing
result = await processor.process("video.mp4")            # → Multimedia
result = await processor.process("/path/to/folder")      # → Batch processing

# Standardized output
print(result.knowledge_graph)  # Always present
print(result.vectors)          # Always present
print(result.metadata)         # Processing info
```

---

## Current Architecture

### Processor Types (8 Categories)

| Processor | Purpose | Files | Issues |
|-----------|---------|-------|--------|
| PDF Processing | Text extraction, OCR | 3 files | ✅ Well-defined |
| GraphRAG | Knowledge graphs from web/docs | **4 implementations** | ⚠️ **DUPLICATE** |
| MultiModal | HTML, PDF, audio, video | 2 files | ⚠️ Overlaps |
| File Converter | Format conversion | 13 files | ✅ Good design |
| Media Processing | Audio/video transcription | Split across folders | ⚠️ **SPLIT** |
| Batch Processing | Parallel processing | 3 implementations | ⚠️ **DUPLICATE** |
| Specialized Scrapers | Legal, patents, Wikipedia | Multiple files | ✅ Well-scoped |
| Analytics | LLM optimization, geospatial | Multiple files | ✅ Specialized |

### GraphRAG Duplication (🔴 HIGH PRIORITY)

**All doing the same thing - process websites/documents into knowledge graphs:**

1. `processors/graphrag_processor.py` (9KB)
2. `processors/website_graphrag_processor.py` (21KB)
3. `processors/advanced_graphrag_website_processor.py` (64KB) ← Most comprehensive
4. `processors/graphrag/complete_advanced_graphrag.py`

**Consolidation Plan:** Merge into single `processors/graphrag/processor.py`

---

## Proposed Architecture

### Core Components

```
processors/
├── __init__.py                    # Exports UniversalProcessor
├── protocol.py                    # ProcessorProtocol interface
├── registry.py                    # Processor discovery system
├── universal_processor.py         # Main entrypoint
│
├── pdf/                           # PDF processing
├── graphrag/                      # Consolidated GraphRAG
├── multimedia/                    # MOVED from data_transformation
├── file_converter/                # File conversion (unchanged)
├── batch/                         # Consolidated batch processing
└── specialized/                   # Domain-specific processors
```

### Key Interfaces

#### ProcessorProtocol

```python
from typing import Protocol, Union
from pathlib import Path

@runtime_checkable
class ProcessorProtocol(Protocol):
    """All processors must implement this interface."""
    
    async def can_process(self, input_source: Union[str, Path]) -> bool:
        """Check if this processor can handle the input."""
        ...
    
    async def process(
        self, 
        input_source: Union[str, Path],
        **options
    ) -> ProcessingResult:
        """Process the input and return standardized result."""
        ...
    
    def get_supported_types(self) -> list[str]:
        """Return list of supported input types."""
        ...
```

#### ProcessingResult (Standardized Output)

```python
@dataclass
class ProcessingResult:
    """Standardized output from all processors."""
    
    knowledge_graph: KnowledgeGraph  # Entities, relationships, graph
    vectors: VectorStore             # Embeddings for semantic search
    content: dict                    # Extracted text, metadata
    metadata: ProcessingMetadata     # Processor used, timing, errors
    extra: dict = None               # Processor-specific data
```

---

## Implementation Phases

### Phase 1: Foundation (Week 1)
- Create ProcessorProtocol, ProcessingResult
- Create ProcessorRegistry for discovery
- Create UniversalProcessor skeleton
- Comprehensive tests

**Deliverables:**
- `processors/protocol.py` (150 lines)
- `processors/registry.py` (200 lines)
- `processors/universal_processor.py` (300 lines)
- Test suite

### Phase 2: GraphRAG Consolidation (Week 1-2)
- Merge 4 GraphRAG implementations into one
- Refactor to ProcessorProtocol interface
- Add deprecation warnings
- Update imports across codebase

**Impact:**
- Remove ~1,500 duplicate lines
- Single GraphRAGProcessor in processors/graphrag/

### Phase 3: UniversalProcessor Implementation (Week 2)
- Implement adapters for existing processors
- Add automatic routing logic
- Register all processors
- Integration tests

**Result:**
- Single entrypoint working for all processor types

### Phase 4: Multimedia Migration (Week 3)
- Move `data_transformation/multimedia/` → `processors/multimedia/`
- Update ~165 import statements (automated)
- Create MultimediaProcessor adapter
- Test MCP tools

**Impact:**
- Better organization
- Unified multimedia + processing in one place

### Phase 5: Batch Processing Consolidation (Week 3-4)
- Consolidate 3 batch processor implementations
- Create universal batch processor
- Update file_converter to use universal batch

### Phase 6: Testing & Documentation (Week 4)
- Comprehensive test suite
- Integration tests
- API documentation
- Migration guide
- Performance benchmarking

---

## Migration Guide

### Old API (Before)

```python
# Different imports for each processor type
from ipfs_datasets_py.processors.pdf_processor import PDFProcessor
from ipfs_datasets_py.processors.website_graphrag_processor import WebsiteGraphRAGProcessor
from ipfs_datasets_py.data_transformation.multimedia import FFmpegWrapper

# Different APIs for each
pdf_proc = PDFProcessor()
pdf_result = await pdf_proc.process_pdf("doc.pdf")

web_proc = WebsiteGraphRAGProcessor()
web_result = await web_proc.process_website("https://example.com")

ffmpeg = FFmpegWrapper()
video_result = await ffmpeg.convert("video.mp4")

# Different result formats
```

### New API (After)

```python
# Single import
from ipfs_datasets_py.processors import UniversalProcessor

# Single API
processor = UniversalProcessor()

# Automatic routing
pdf_result = await processor.process("doc.pdf")
web_result = await processor.process("https://example.com")
video_result = await processor.process("video.mp4")

# Standardized result format
for result in [pdf_result, web_result, video_result]:
    print(result.knowledge_graph)  # Always present
    print(result.vectors)          # Always present
    print(result.metadata)         # Processing info
```

### Backward Compatibility

Old imports will continue to work for 2 release cycles with deprecation warnings:

```python
# Still works, but warns
from ipfs_datasets_py.processors.pdf_processor import PDFProcessor
# DeprecationWarning: Use UniversalProcessor instead

pdf_proc = PDFProcessor()
result = await pdf_proc.process_pdf("doc.pdf")  # Still works
```

---

## Impact Summary

### Files Affected

| Category | Count | Notes |
|----------|-------|-------|
| Processors to consolidate | 4 | GraphRAG implementations |
| Files to move | 452 | multimedia/ directory |
| Import statements to update | ~165 | Automated with script |
| New files to create | 7 | Protocol, registry, universal processor, adapters |
| Tests to create | ~20 | Unit + integration |
| Documentation updates | ~15 | API docs, guides, tutorials |

### Code Metrics

| Metric | Current | Target | Change |
|--------|---------|--------|--------|
| Total lines | ~50,000 | ~45,000 | -10% (5,000 lines) |
| Duplicate lines | ~1,500 | 0 | -100% |
| Import complexity | 3-5 imports | 1 import | -70% |
| Test coverage | ~60% | 90%+ | +30% |

### Timeline

- **Week 1:** Foundation + GraphRAG consolidation
- **Week 2:** UniversalProcessor implementation
- **Week 3:** Multimedia migration + batch consolidation
- **Week 4:** Testing + documentation

**Total:** 4 weeks (1 month)

---

## Key Benefits

### For Users

✅ **Single API** - One import handles all processing needs  
✅ **Automatic Routing** - No need to know which processor to use  
✅ **Consistent Output** - All processors return knowledge graphs + vectors  
✅ **Better Documentation** - Clear guides and examples  
✅ **Backward Compatible** - Existing code continues to work

### For Developers

✅ **Less Duplication** - Remove ~1,500 duplicate lines  
✅ **Better Organization** - Clear directory structure  
✅ **Easier Maintenance** - Single interface to maintain  
✅ **Extensibility** - Easy to add new processors  
✅ **Type Safety** - Protocol ensures consistent implementation

### For Performance

✅ **Shared Resources** - Better resource pooling  
✅ **Optimized Routing** - Smart processor selection  
✅ **Parallel Processing** - Unified batch processor  

---

## Risk Assessment

### High Risk Items

1. **Git submodule movement** (multimedia/)
   - **Mitigation:** Careful git mv, thorough testing
   
2. **Breaking changes** (import paths)
   - **Mitigation:** 2-release deprecation period

3. **Performance regression**
   - **Mitigation:** Before/after benchmarking

### Medium Risk Items

4. **MCP tools** (~200 tools affected)
   - **Mitigation:** Automated migration script
   
5. **Test suite maintenance** (182+ tests)
   - **Mitigation:** Phased updates

---

## Decision Log

| Decision | Rationale |
|----------|-----------|
| Use Protocol, not inheritance | More flexible, duck typing |
| Keep data_transformation/ for IPFS formats | Different concerns (IPFS vs. processing) |
| Move multimedia to processors/ | Better organization, related functionality |
| Standardize on async/await | Modern, efficient, consistent |
| 2-release deprecation period | Give users time to migrate |
| Knowledge graph required output | Core value proposition |

---

## Next Steps

1. ✅ Create comprehensive plan (this document)
2. ⏳ Review with maintainers
3. ⏳ Get approval for architecture
4. ⏳ Begin Phase 1 implementation
5. ⏳ Weekly progress reports

---

## References

- **Full Plan:** [PROCESSORS_REFACTORING_PLAN.md](./PROCESSORS_REFACTORING_PLAN.md)
- **Current Code:** `ipfs_datasets_py/processors/`
- **Current Multimedia:** `ipfs_datasets_py/data_transformation/multimedia/`
- **MCP Tools:** `ipfs_datasets_py/mcp_server/tools/`
- **Tests:** `tests/unit_tests/`, `tests/integration/`

---

## Questions?

See the full plan for detailed implementation notes, code examples, and architectural decisions.
