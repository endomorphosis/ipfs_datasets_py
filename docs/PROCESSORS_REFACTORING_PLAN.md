# Comprehensive Refactoring Plan: processors/ and data_transformation/

**Created:** 2026-02-14  
**Status:** Planning Phase  
**Goal:** Create a unified processor architecture with single entrypoint for URLs/files/folders → knowledge graphs and vectors

---

## Executive Summary

This document outlines a comprehensive refactoring plan for the `ipfs_datasets_py/processors/` and `ipfs_datasets_py/data_transformation/` directories. The refactoring addresses:

1. **Fragmentation:** 8+ processor types with no unified interface
2. **Duplication:** Multiple GraphRAG implementations, overlapping audio/batch processing
3. **Inconsistency:** Mixed async/sync patterns, no common base class
4. **Discovery:** No processor registry or automatic routing
5. **Integration Gap:** data_transformation/multimedia separated from processors

**Target Architecture:**
```python
# Single universal entrypoint
from ipfs_datasets_py.processors import UniversalProcessor

processor = UniversalProcessor()

# Automatic routing based on input type
result = await processor.process("https://example.com/page")  # → Website GraphRAG
result = await processor.process("document.pdf")               # → PDF processing
result = await processor.process("/path/to/folder")            # → Batch processing
result = await processor.process("video.mp4")                  # → Media transcription

# All outputs standardized knowledge graph + vectors
print(result.knowledge_graph)  # Entities, relationships, graph
print(result.vectors)          # Vector embeddings
print(result.metadata)         # Processing metadata
```

---

## Current State Analysis

### Processor Categories (8 Types)

| Processor | Files | Purpose | Issues |
|-----------|-------|---------|--------|
| **PDF Processing** | `pdf_processor.py`, `ocr_engine.py` | Text extraction, OCR, entities | ✅ Well-defined |
| **GraphRAG** | 3+ implementations | Knowledge graph from websites/docs | ⚠️ **DUPLICATE** |
| **MultiModal** | `multimodal_processor.py`, `enhanced_multimodal_processor.py` | HTML, PDF, audio, video, images | ⚠️ Overlap with file_converter |
| **File Converter** | `/file_converter/` (13 modules) | Format detection & conversion | ✅ Good architecture |
| **Media Processing** | `advanced_media_processing.py` + `/data_transformation/multimedia/` | Audio/video transcription | ⚠️ Split across folders |
| **Batch Processing** | Multiple implementations | Parallel processing | ⚠️ **DUPLICATE** |
| **Specialized Scrapers** | `/legal_scrapers/`, `patent_scraper.py` | Domain-specific data | ✅ Well-scoped |
| **Analytics** | `llm_optimizer.py`, `geospatial_analysis.py` | LLM chunking, geo analysis | ✅ Specialized |

### data_transformation/ Structure

```
data_transformation/
├── multimedia/                    # 452 Python files (!)
│   ├── ffmpeg_wrapper.py          # Video/audio conversion
│   ├── ytdlp_wrapper.py           # Video downloading
│   ├── media_processor.py         # Orchestrator
│   ├── discord_wrapper.py         # Discord export
│   ├── email_processor.py         # Email export
│   ├── omni_converter_mk2/        # 300+ files (git submodule)
│   └── convert_to_txt_based_on_mime_type/  # 150+ files (git submodule)
├── ipld/                          # IPFS linked data structures
├── ipfs_formats/                  # IPFS format handlers
├── car_conversion.py              # CAR file handling
├── jsonl_to_parquet.py           # Data format conversion
└── dataset_serialization.py      # Dataset serialization
```

### Critical Issues Identified

#### 1. **GraphRAG Duplication** (🔴 HIGH PRIORITY)
- `graphrag_processor.py` (9KB)
- `website_graphrag_processor.py` (21KB)
- `advanced_graphrag_website_processor.py` (64KB)
- `processors/graphrag/complete_advanced_graphrag.py`

**All do essentially the same thing:** Process websites → knowledge graphs + vector search

#### 2. **No Unified Interface**
- Each processor has different method signatures
- Mix of sync and async methods
- Varied return types (dict, dataclass, custom objects)
- No common error handling

#### 3. **Architecture Fragmentation**
```python
# Current state - users need to know which processor to use:
from processors.pdf_processor import PDFProcessor
from processors.website_graphrag_processor import WebsiteGraphRAGProcessor
from processors.advanced_media_processing import AdvancedMediaProcessor

# Different APIs for each:
pdf_result = await pdf_proc.process_pdf(file_path)
web_result = await web_proc.process_website(url, config)
media_result = await media_proc.process_media_file(video_path, options)
```

#### 4. **Multimedia Split**
- Core multimedia code in `data_transformation/multimedia/`
- Media processing wrappers in `processors/advanced_media_processing.py`
- Audio transcription in `processors/file_converter/audio_processor.py`
- Duplication of FFmpeg/yt-dlp integration

---

## Proposed Architecture

### Design Principles

1. **Single Entrypoint:** `UniversalProcessor` routes based on input type
2. **Protocol-Based:** Common `ProcessorProtocol` for all processors
3. **Standardized Output:** All processors return `ProcessingResult` with knowledge graph + vectors
4. **Automatic Discovery:** Processor registry for dynamic routing
5. **Backward Compatible:** Existing processors continue to work

### Core Components

#### 1. ProcessorProtocol (Base Interface)

```python
from typing import Protocol, Union, runtime_checkable
from pathlib import Path
from dataclasses import dataclass

@dataclass
class ProcessingResult:
    """Standardized output from all processors."""
    
    # Knowledge Graph
    knowledge_graph: KnowledgeGraph  # Entities, relationships, properties
    
    # Vector Embeddings
    vectors: VectorStore  # Embeddings for semantic search
    
    # Raw Content
    content: dict  # Extracted text, metadata, structured data
    
    # Processing Metadata
    metadata: ProcessingMetadata  # Processor used, timing, errors
    
    # Optional: Processor-specific data
    extra: dict = None

@runtime_checkable
class ProcessorProtocol(Protocol):
    """Protocol that all processors must implement."""
    
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
        """Return list of supported input types (URL, PDF, video, etc.)."""
        ...
```

#### 2. UniversalProcessor (Main Entrypoint)

```python
class UniversalProcessor:
    """
    Universal processor that automatically routes inputs to specialized processors.
    
    Features:
    - Automatic input type detection (URL, file, folder)
    - Processor selection based on capabilities
    - Parallel processing for batch inputs
    - Standardized knowledge graph + vector output
    - Error handling and fallback strategies
    
    Example:
        >>> processor = UniversalProcessor()
        >>> 
        >>> # Process any input type
        >>> result = await processor.process("https://arxiv.org/pdf/2301.00001.pdf")
        >>> print(result.knowledge_graph.entities)
        >>> 
        >>> # Batch processing
        >>> results = await processor.process_batch([
        ...     "https://example.com",
        ...     "document.pdf",
        ...     "/path/to/folder"
        ... ])
    """
    
    def __init__(self, config: Optional[ProcessorConfig] = None):
        self.config = config or ProcessorConfig()
        self.registry = ProcessorRegistry()
        self._initialize_processors()
    
    def _initialize_processors(self):
        """Register all available processors."""
        from .pdf import PDFProcessor
        from .graphrag import GraphRAGProcessor
        from .multimedia import MultimediaProcessor
        from .file_converter import FileConverterProcessor
        
        self.registry.register(PDFProcessor())
        self.registry.register(GraphRAGProcessor())
        self.registry.register(MultimediaProcessor())
        self.registry.register(FileConverterProcessor())
    
    async def process(
        self,
        input_source: Union[str, Path, list],
        **options
    ) -> Union[ProcessingResult, list[ProcessingResult]]:
        """
        Process any input: URL, file, folder, or list of inputs.
        
        Automatically detects input type and routes to appropriate processor.
        """
        # Handle batch inputs
        if isinstance(input_source, list):
            return await self.process_batch(input_source, **options)
        
        # Detect input type
        input_type = self._detect_input_type(input_source)
        
        # Find capable processors
        processors = await self.registry.find_processors(input_source)
        
        if not processors:
            raise ValueError(f"No processor found for: {input_source}")
        
        # Select best processor (by priority/capabilities)
        processor = self._select_best_processor(processors, input_type)
        
        # Process and return standardized result
        return await processor.process(input_source, **options)
    
    def _detect_input_type(self, input_source: Union[str, Path]) -> InputType:
        """Detect if input is URL, file, folder, or other."""
        if isinstance(input_source, str):
            if input_source.startswith(('http://', 'https://')):
                return InputType.URL
            if input_source.startswith('ipfs://'):
                return InputType.IPFS
        
        path = Path(input_source)
        if path.is_dir():
            return InputType.FOLDER
        if path.is_file():
            return InputType.FILE
        
        return InputType.UNKNOWN
```

#### 3. ProcessorRegistry (Discovery System)

```python
class ProcessorRegistry:
    """
    Registry for discovering and managing processors.
    
    Features:
    - Dynamic processor registration
    - Capability-based routing
    - Priority-based selection
    - Hot-reloading of processors
    """
    
    def __init__(self):
        self._processors: dict[str, ProcessorProtocol] = {}
        self._capabilities: dict[str, list[str]] = {}
    
    def register(self, processor: ProcessorProtocol, priority: int = 0):
        """Register a processor with optional priority."""
        name = processor.__class__.__name__
        self._processors[name] = processor
        self._capabilities[name] = processor.get_supported_types()
    
    async def find_processors(
        self, 
        input_source: Union[str, Path]
    ) -> list[ProcessorProtocol]:
        """Find all processors that can handle the input."""
        capable = []
        for name, processor in self._processors.items():
            if await processor.can_process(input_source):
                capable.append(processor)
        return capable
    
    def list_processors(self) -> dict[str, list[str]]:
        """List all registered processors and their capabilities."""
        return {
            name: self._capabilities[name]
            for name in self._processors
        }
```

### New Directory Structure

```
ipfs_datasets_py/processors/
├── __init__.py                    # Exports UniversalProcessor
├── protocol.py                    # ProcessorProtocol, ProcessingResult
├── registry.py                    # ProcessorRegistry
├── universal_processor.py         # UniversalProcessor implementation
├── input_detection.py             # Input type detection utilities
│
├── pdf/                           # PDF processing (consolidated)
│   ├── __init__.py
│   ├── processor.py               # PDFProcessor (implements ProcessorProtocol)
│   ├── ocr_engine.py
│   └── extractor.py
│
├── graphrag/                      # GraphRAG (CONSOLIDATED - no more duplicates)
│   ├── __init__.py
│   ├── processor.py               # Single GraphRAGProcessor
│   ├── website_processor.py       # Website-specific logic
│   ├── document_processor.py      # Document-specific logic
│   └── knowledge_graph_builder.py
│
├── multimedia/                    # Multimedia (MOVED from data_transformation)
│   ├── __init__.py
│   ├── processor.py               # MultimediaProcessor
│   ├── ffmpeg_wrapper.py
│   ├── ytdlp_wrapper.py
│   ├── media_processor.py
│   ├── discord_wrapper.py
│   ├── email_processor.py
│   └── submodules/                # Keep git submodules here
│       ├── omni_converter_mk2/
│       └── convert_to_txt_based_on_mime_type/
│
├── file_converter/                # File conversion (mostly unchanged)
│   ├── processor.py               # Implements ProcessorProtocol
│   └── ... (existing files)
│
├── batch/                         # Batch processing (CONSOLIDATED)
│   ├── __init__.py
│   ├── processor.py               # Universal batch processor
│   ├── parallel_executor.py
│   └── job_queue.py
│
├── specialized/                   # Domain-specific processors
│   ├── legal_scrapers/
│   ├── patent_scraper.py
│   ├── wikipedia_x/
│   └── geospatial_analysis.py
│
└── utils/                         # Shared utilities
    ├── knowledge_graph.py         # Standardized KG format
    ├── vector_store.py            # Vector embedding utilities
    └── metadata.py                # Processing metadata
```

---

## Implementation Phases

### Phase 1: Design & Foundation (Week 1)

**Goal:** Establish core architecture without breaking existing code

#### Tasks:
- [ ] Create `ProcessorProtocol` in `processors/protocol.py`
- [ ] Create `ProcessingResult` dataclass with standardized output
- [ ] Create `ProcessorRegistry` in `processors/registry.py`
- [ ] Create `UniversalProcessor` skeleton in `processors/universal_processor.py`
- [ ] Add input type detection utilities in `processors/input_detection.py`
- [ ] Create comprehensive tests for core components

#### Deliverables:
```python
# New files
processors/protocol.py              # 150 lines
processors/registry.py              # 200 lines
processors/universal_processor.py   # 300 lines
processors/input_detection.py       # 150 lines

# Tests
tests/unit/processors/test_protocol.py
tests/unit/processors/test_registry.py
tests/unit/processors/test_universal_processor.py
tests/unit/processors/test_input_detection.py
```

#### Success Criteria:
- All new files pass type checking (mypy)
- 100% test coverage on core components
- Documentation generated
- No impact on existing processors

---

### Phase 2: Consolidate GraphRAG (Week 1-2)

**Goal:** Merge 3-4 GraphRAG implementations into single processor

#### Analysis of Duplicates:
1. **`graphrag_processor.py`** (9KB) - Basic implementation, mock data
2. **`website_graphrag_processor.py`** (21KB) - Website-specific, uses BeautifulSoup
3. **`advanced_graphrag_website_processor.py`** (64KB) - Most comprehensive
4. **`processors/graphrag/complete_advanced_graphrag.py`** - Another implementation

#### Consolidation Strategy:
```python
# Keep best implementation: advanced_graphrag_website_processor.py
# Migrate features from others, deprecate duplicates

processors/graphrag/
├── __init__.py                    # Export GraphRAGProcessor
├── processor.py                   # Main GraphRAGProcessor (ProcessorProtocol)
├── website_handler.py             # Website-specific logic
├── document_handler.py            # Document-specific logic
├── knowledge_graph_builder.py     # KG construction
├── vector_store_integration.py    # Vector embeddings
└── query_engine.py                # Graph querying
```

#### Migration Path:
1. Refactor `advanced_graphrag_website_processor.py` → `processors/graphrag/processor.py`
2. Implement `ProcessorProtocol` interface
3. Add deprecation warnings to old modules
4. Update all imports across codebase
5. Remove deprecated files after 2 releases

#### Estimated Changes:
- **Lines removed:** ~1,500 (duplicates)
- **Lines refactored:** ~800
- **Lines added:** ~400 (protocol implementation, tests)
- **Net reduction:** ~900 lines

---

### Phase 3: Implement UniversalProcessor (Week 2)

**Goal:** Create working single entrypoint with automatic routing

#### Tasks:
1. Implement adapter for existing processors:
   ```python
   # Wrap existing processors in ProcessorProtocol
   class PDFProcessorAdapter(ProcessorProtocol):
       def __init__(self):
           from .pdf_processor import PDFProcessor
           self._inner = PDFProcessor()
       
       async def can_process(self, input_source):
           return str(input_source).endswith('.pdf')
       
       async def process(self, input_source, **options):
           result = await self._inner.process_pdf(input_source, **options)
           # Convert to ProcessingResult
           return self._convert_result(result)
   ```

2. Register all existing processors:
   ```python
   # In UniversalProcessor._initialize_processors()
   self.registry.register(PDFProcessorAdapter())
   self.registry.register(GraphRAGProcessorAdapter())
   self.registry.register(MultimediaProcessorAdapter())
   # etc.
   ```

3. Implement routing logic:
   - URL detection → GraphRAG or multimedia (check content type)
   - File detection → Check extension, MIME type
   - Folder detection → Batch processor
   - IPFS CID → IPFS handler

4. Add configuration system:
   ```python
   @dataclass
   class ProcessorConfig:
       enable_caching: bool = True
       parallel_workers: int = 4
       timeout_seconds: int = 300
       fallback_enabled: bool = True
       preferred_processors: dict = None  # Override routing
   ```

#### Integration Tests:
```python
async def test_universal_processor_pdf():
    processor = UniversalProcessor()
    result = await processor.process("test.pdf")
    assert isinstance(result, ProcessingResult)
    assert result.knowledge_graph is not None

async def test_universal_processor_url():
    processor = UniversalProcessor()
    result = await processor.process("https://example.com")
    assert result.content['url'] == "https://example.com"

async def test_universal_processor_batch():
    processor = UniversalProcessor()
    results = await processor.process([
        "test.pdf",
        "https://example.com",
        "video.mp4"
    ])
    assert len(results) == 3
```

---

### Phase 4: Merge data_transformation/multimedia (Week 3)

**Goal:** Move multimedia processing into processors/

#### Current State:
```
data_transformation/multimedia/
├── ffmpeg_wrapper.py          # 78KB
├── ytdlp_wrapper.py           # 70KB
├── media_processor.py         # 23KB
├── discord_wrapper.py         # 35KB
├── email_processor.py         # 29KB
└── 452 total files
```

#### Migration Strategy:

1. **Move Files:**
   ```bash
   # Move multimedia to processors
   git mv ipfs_datasets_py/data_transformation/multimedia \
          ipfs_datasets_py/processors/multimedia
   
   # Update submodules
   git submodule update --init processors/multimedia/omni_converter_mk2
   ```

2. **Update Imports:**
   ```python
   # Find all imports
   grep -r "from ipfs_datasets_py.data_transformation.multimedia" . | wc -l
   # Estimated: 100+ import statements to update
   
   # Old:
   from ipfs_datasets_py.data_transformation.multimedia import FFmpegWrapper
   
   # New:
   from ipfs_datasets_py.processors.multimedia import FFmpegWrapper
   ```

3. **Create ProcessorProtocol Adapter:**
   ```python
   # processors/multimedia/processor.py
   class MultimediaProcessor(ProcessorProtocol):
       """Unified multimedia processor implementing ProcessorProtocol."""
       
       def __init__(self):
           self.ffmpeg = FFmpegWrapper()
           self.ytdlp = YtDlpWrapper()
           self.media = MediaProcessor()
       
       async def can_process(self, input_source):
           # Check if video, audio, or media URL
           extensions = ('.mp4', '.mp3', '.wav', '.avi', '.mkv', '.webm')
           if isinstance(input_source, str):
               if any(input_source.endswith(ext) for ext in extensions):
                   return True
               # Check if video URL
               if 'youtube.com' in input_source or 'vimeo.com' in input_source:
                   return True
           return False
       
       async def process(self, input_source, **options):
           # Download if URL
           if input_source.startswith('http'):
               local_file = await self.ytdlp.download(input_source)
           else:
               local_file = input_source
           
           # Transcribe or extract metadata
           transcription = await self._transcribe(local_file)
           metadata = await self._extract_metadata(local_file)
           
           # Build knowledge graph from transcription
           kg = await self._build_knowledge_graph(transcription)
           
           # Generate embeddings
           vectors = await self._generate_embeddings(transcription)
           
           return ProcessingResult(
               knowledge_graph=kg,
               vectors=vectors,
               content={
                   'transcription': transcription,
                   'metadata': metadata
               },
               metadata=ProcessingMetadata(
                   processor='MultimediaProcessor',
                   input_type='video/audio',
                   processing_time=elapsed
               )
           )
   ```

#### Impact Analysis:
- **Files affected:** ~150+ (all imports)
- **MCP tools affected:** `media_tools/`, `file_converter_tools/`
- **Tests affected:** `tests/unit_tests/multimedia_/`
- **Breaking changes:** Import paths only (APIs unchanged)

#### Migration Script:
```python
# scripts/migrate_multimedia_imports.py
import re
from pathlib import Path

def update_imports(file_path: Path):
    """Update multimedia imports in a file."""
    content = file_path.read_text()
    
    # Update import statements
    content = re.sub(
        r'from ipfs_datasets_py\.data_transformation\.multimedia',
        r'from ipfs_datasets_py.processors.multimedia',
        content
    )
    content = re.sub(
        r'import ipfs_datasets_py\.data_transformation\.multimedia',
        r'import ipfs_datasets_py.processors.multimedia',
        content
    )
    
    file_path.write_text(content)

def main():
    # Find all Python files
    for py_file in Path('.').rglob('*.py'):
        if 'data_transformation/multimedia' not in str(py_file):
            update_imports(py_file)
    
    print("✓ All imports updated")

if __name__ == '__main__':
    main()
```

---

### Phase 5: Consolidate Batch Processing (Week 3-4)

**Goal:** Single unified batch processor

#### Current Implementations:
1. `processors/batch_processor.py` (88KB) - Comprehensive, parallel, job queue
2. `processors/file_converter/batch_processor.py` - File-specific
3. `data_transformation/multimedia/media_processor.py` - Media batch processing

#### Consolidation Plan:
```python
# processors/batch/processor.py
class UniversalBatchProcessor(ProcessorProtocol):
    """
    Universal batch processor that delegates to UniversalProcessor.
    
    Features:
    - Parallel processing with worker pool
    - Progress tracking and reporting
    - Error isolation (one failure doesn't stop batch)
    - Priority queue for job ordering
    - Resource limiting (CPU, memory, disk)
    - Checkpointing and resume
    """
    
    def __init__(
        self,
        max_workers: int = 4,
        enable_progress: bool = True,
        enable_checkpointing: bool = False
    ):
        self.max_workers = max_workers
        self.enable_progress = enable_progress
        self.enable_checkpointing = enable_checkpointing
        self.universal = UniversalProcessor()
    
    async def process_batch(
        self,
        inputs: list[Union[str, Path]],
        **options
    ) -> BatchProcessingResult:
        """
        Process multiple inputs in parallel.
        
        Returns:
            BatchProcessingResult with:
            - results: List of ProcessingResult
            - errors: List of (input, error) tuples
            - metadata: Timing, success rate, resource usage
        """
        # Use existing batch_processor.py logic
        # But delegate actual processing to UniversalProcessor
        pass
```

#### Migration:
- Keep `processors/batch_processor.py` as implementation
- Create thin adapter in `processors/batch/processor.py`
- Deprecate file_converter batch processor (use universal)
- Update media_processor to use universal batch

---

### Phase 6: Testing & Documentation (Week 4)

#### Testing Strategy:

1. **Unit Tests** (New):
   ```
   tests/unit/processors/
   ├── test_protocol.py              # ProcessorProtocol compliance
   ├── test_registry.py              # Registry functionality
   ├── test_universal_processor.py   # Core routing logic
   ├── test_input_detection.py       # Input type detection
   ├── graphrag/
   │   └── test_consolidated_graphrag.py
   └── multimedia/
       └── test_multimedia_processor.py
   ```

2. **Integration Tests** (New):
   ```
   tests/integration/processors/
   ├── test_universal_entrypoint.py  # End-to-end workflows
   ├── test_processor_chaining.py    # Multiple processors in sequence
   └── test_knowledge_graph_output.py # Validate KG format
   ```

3. **Migration Tests** (Validate backward compatibility):
   ```
   tests/migration/
   ├── test_old_imports.py           # Old import paths still work (deprecated)
   ├── test_api_compatibility.py     # Existing APIs unchanged
   └── test_mcp_tools.py             # MCP tools still functional
   ```

#### Documentation Updates:

1. **API Documentation:**
   ```
   docs/processors/
   ├── README.md                     # Overview and quickstart
   ├── universal_processor.md        # UniversalProcessor guide
   ├── protocol.md                   # ProcessorProtocol spec
   ├── migration_guide.md            # Upgrading from old API
   └── examples/
       ├── basic_usage.md
       ├── custom_processors.md
       └── advanced_routing.md
   ```

2. **Architecture Documentation:**
   ```
   docs/architecture/
   ├── processor_architecture.md     # High-level design
   ├── routing_logic.md              # How routing works
   └── knowledge_graph_format.md     # Standardized KG spec
   ```

3. **Tutorial Updates:**
   ```
   docs/tutorials/
   ├── universal_processing_tutorial.md
   ├── graphrag_tutorial_updated.md
   └── multimedia_processing_tutorial.md
   ```

---

## Success Metrics

### Quantitative Goals:

| Metric | Current | Target | Status |
|--------|---------|--------|--------|
| **Lines of Code** | ~50,000 (processors + data_transformation/multimedia) | 45,000 | 🎯 10% reduction |
| **Duplicate Code** | ~1,500 lines (GraphRAG) | 0 | 🎯 Eliminate |
| **Processor Count** | 8 types, 15+ files | 8 types, unified interface | 🎯 Consolidate |
| **Import Complexity** | 3-5 imports per use case | 1 import | 🎯 Simplify |
| **Test Coverage** | ~60% | 90%+ | 🎯 Increase |
| **Documentation** | Scattered, incomplete | Comprehensive | 🎯 Complete |

### Qualitative Goals:

- ✅ Single entrypoint for all processing needs
- ✅ Consistent async/await patterns
- ✅ Standardized knowledge graph output
- ✅ Clear separation of concerns
- ✅ Easy to add new processors
- ✅ Backward compatible (with deprecation warnings)

### Performance Goals:

- No performance regression on existing workloads
- Batch processing: 10% faster (better parallelization)
- Memory usage: 15% lower (shared resources)

---

## Risk Assessment

### High Risk:

1. **Breaking Existing Code**
   - **Risk:** Import path changes break user code
   - **Mitigation:** Deprecation period (2 releases), backward-compatible imports
   - **Impact:** Medium

2. **Git Submodule Movement**
   - **Risk:** Moving multimedia breaks submodule references
   - **Mitigation:** Careful git mv, update .gitmodules, test thoroughly
   - **Impact:** High if done incorrectly

3. **Performance Regression**
   - **Risk:** Additional abstraction layers slow processing
   - **Mitigation:** Benchmark before/after, profile hot paths
   - **Impact:** Medium

### Medium Risk:

4. **MCP Tools Breakage**
   - **Risk:** 200+ MCP tools may have hardcoded imports
   - **Mitigation:** Automated import migration script, comprehensive testing
   - **Impact:** Medium

5. **Test Suite Maintenance**
   - **Risk:** 182+ existing tests need updating
   - **Mitigation:** Phased approach, update tests per phase
   - **Impact:** Low (time-consuming but safe)

### Low Risk:

6. **Documentation Drift**
   - **Risk:** Documentation becomes outdated
   - **Mitigation:** Documentation updates in same PR as code changes
   - **Impact:** Low

---

## Migration Guide for Users

### Before (Old API):

```python
# PDF processing
from ipfs_datasets_py.processors.pdf_processor import PDFProcessor
pdf_proc = PDFProcessor()
result = await pdf_proc.process_pdf("doc.pdf")

# Website GraphRAG
from ipfs_datasets_py.processors.website_graphrag_processor import WebsiteGraphRAGProcessor
web_proc = WebsiteGraphRAGProcessor()
result = await web_proc.process_website("https://example.com")

# Multimedia
from ipfs_datasets_py.data_transformation.multimedia import FFmpegWrapper
ffmpeg = FFmpegWrapper()
result = await ffmpeg.convert("video.mp4")
```

### After (New API):

```python
# Universal processor - single entrypoint
from ipfs_datasets_py.processors import UniversalProcessor

processor = UniversalProcessor()

# Automatic routing
pdf_result = await processor.process("doc.pdf")
web_result = await processor.process("https://example.com")
video_result = await processor.process("video.mp4")

# All results have consistent structure
for result in [pdf_result, web_result, video_result]:
    print(result.knowledge_graph)  # Standardized KG
    print(result.vectors)          # Vector embeddings
    print(result.metadata)         # Processing info
```

### Backward Compatibility:

```python
# Old imports still work with deprecation warnings
from ipfs_datasets_py.processors.pdf_processor import PDFProcessor
# DeprecationWarning: Use UniversalProcessor instead

# Old APIs still work
result = await pdf_proc.process_pdf("doc.pdf")
# Returns old format, but works
```

---

## Timeline

### Week 1: Foundation
- [ ] Design ProcessorProtocol, ProcessingResult
- [ ] Implement ProcessorRegistry
- [ ] Create UniversalProcessor skeleton
- [ ] Write comprehensive tests

### Week 2: GraphRAG Consolidation
- [ ] Merge GraphRAG implementations
- [ ] Refactor to ProcessorProtocol
- [ ] Add deprecation warnings
- [ ] Update imports across codebase

### Week 3: Multimedia Migration
- [ ] Move data_transformation/multimedia to processors/
- [ ] Update all imports (automated script)
- [ ] Create MultimediaProcessor adapter
- [ ] Test MCP tools

### Week 4: Testing & Documentation
- [ ] Comprehensive test suite
- [ ] Integration tests
- [ ] Documentation updates
- [ ] Migration guide
- [ ] Performance benchmarking

### Total: 4 weeks (1 month)

---

## Appendix A: File Inventory

### Files to Consolidate/Remove:

```
processors/graphrag_processor.py               → REMOVE (merged)
processors/website_graphrag_processor.py       → REMOVE (merged)
processors/advanced_graphrag_website_processor.py → REFACTOR → processors/graphrag/processor.py
processors/graphrag/complete_advanced_graphrag.py → MERGE
processors/file_converter/batch_processor.py   → DEPRECATE (use universal)
```

### Files to Move:

```
data_transformation/multimedia/*               → processors/multimedia/
```

### Files to Create:

```
processors/protocol.py                         # 150 lines
processors/registry.py                         # 200 lines
processors/universal_processor.py              # 300 lines
processors/input_detection.py                  # 150 lines
processors/graphrag/processor.py               # 400 lines
processors/multimedia/processor.py             # 300 lines
processors/batch/processor.py                  # 200 lines
```

**Total New Code:** ~1,700 lines  
**Total Removed Code:** ~2,500 lines  
**Net Reduction:** ~800 lines

---

## Appendix B: Import Migration Map

### Old → New Import Paths:

```python
# Multimedia
OLD: from ipfs_datasets_py.data_transformation.multimedia import FFmpegWrapper
NEW: from ipfs_datasets_py.processors.multimedia import FFmpegWrapper

OLD: from ipfs_datasets_py.data_transformation.multimedia import YtDlpWrapper
NEW: from ipfs_datasets_py.processors.multimedia import YtDlpWrapper

# GraphRAG (consolidated)
OLD: from ipfs_datasets_py.processors.graphrag_processor import GraphRAGProcessor
NEW: from ipfs_datasets_py.processors.graphrag import GraphRAGProcessor

OLD: from ipfs_datasets_py.processors.website_graphrag_processor import WebsiteGraphRAGProcessor
NEW: from ipfs_datasets_py.processors.graphrag import GraphRAGProcessor

OLD: from ipfs_datasets_py.processors.advanced_graphrag_website_processor import AdvancedGraphRAGWebsiteProcessor
NEW: from ipfs_datasets_py.processors.graphrag import GraphRAGProcessor

# Universal Processor (new)
NEW: from ipfs_datasets_py.processors import UniversalProcessor
```

### Affected Codebases:

1. **MCP Server Tools:** ~50 files
   - `ipfs_datasets_py/mcp_server/tools/media_tools/`
   - `ipfs_datasets_py/mcp_server/tools/file_converter_tools/`
   - `ipfs_datasets_py/mcp_server/tools/pdf_tools/`

2. **Tests:** ~80 files
   - `tests/unit_tests/multimedia_/`
   - `tests/integration/multimedia/`
   - `tests/unit/processors/`

3. **Examples/Demos:** ~15 files
   - `scripts/demo/demonstrate_*.py`
   - `examples/`

4. **Documentation:** ~20 files
   - Code examples in markdown files

**Total Estimated Files to Update:** ~165 files

---

## Appendix C: Knowledge Graph Standardization

### ProcessingResult.knowledge_graph Format:

```python
@dataclass
class KnowledgeGraph:
    """Standardized knowledge graph format."""
    
    # Graph structure
    entities: list[Entity]         # Nodes
    relationships: list[Relationship]  # Edges
    properties: dict[str, Any]     # Graph-level properties
    
    # Metadata
    source: str                    # Source document/URL
    created_at: datetime
    schema_version: str = "1.0"
    
    # Query support
    def query(self, sparql: str) -> list[dict]:
        """Execute SPARQL query."""
        pass
    
    def find_entities(self, entity_type: str) -> list[Entity]:
        """Find entities by type."""
        pass
    
    def find_relationships(self, rel_type: str) -> list[Relationship]:
        """Find relationships by type."""
        pass
    
    # Export formats
    def to_rdf(self) -> str:
        """Export as RDF/XML."""
        pass
    
    def to_neo4j(self) -> dict:
        """Export as Neo4j Cypher."""
        pass
    
    def to_networkx(self):
        """Convert to NetworkX graph."""
        pass

@dataclass
class Entity:
    """Knowledge graph entity (node)."""
    id: str
    type: str                      # Entity type (Person, Organization, etc.)
    label: str                     # Human-readable label
    properties: dict[str, Any]     # Entity properties
    embedding: Optional[np.ndarray] = None  # Vector embedding

@dataclass
class Relationship:
    """Knowledge graph relationship (edge)."""
    id: str
    source: str                    # Source entity ID
    target: str                    # Target entity ID
    type: str                      # Relationship type
    properties: dict[str, Any]     # Edge properties
    confidence: float = 1.0        # Confidence score
```

---

## Questions & Decisions

### Open Questions:

1. **Q:** Should we keep data_transformation/ for IPFS-specific formats (CAR, IPLD)?  
   **A:** YES - Keep data_transformation/ for IPFS formats. Only move multimedia.

2. **Q:** How to handle git submodules when moving multimedia?  
   **A:** Use `git mv` to preserve history. Update `.gitmodules`. Test thoroughly.

3. **Q:** Should UniversalProcessor support plugins for custom processors?  
   **A:** YES - Add plugin system in Phase 6 (future work).

4. **Q:** How to handle processors that need GPU vs. CPU?  
   **A:** Add resource requirements to ProcessorProtocol. Registry checks availability.

5. **Q:** Should we version the ProcessorProtocol interface?  
   **A:** YES - Add `protocol_version` attribute. Support multiple versions.

### Design Decisions:

1. ✅ Use Protocol (PEP 544) for duck typing - flexible, not inheritance-heavy
2. ✅ Standardize on async/await - all processors must support async
3. ✅ Knowledge graph is required output - all processors generate KG
4. ✅ Backward compatibility via deprecation - 2 release cycles
5. ✅ Move multimedia but keep data_transformation for IPFS formats

---

## Conclusion

This comprehensive refactoring plan addresses the key issues in the processors/ and data_transformation/ directories:

- ✅ **Single Entrypoint:** UniversalProcessor provides one API for all processing
- ✅ **Eliminate Duplication:** Consolidate GraphRAG, batch processing
- ✅ **Standardization:** ProcessorProtocol ensures consistency
- ✅ **Better Organization:** Multimedia in processors/, IPFS formats in data_transformation/
- ✅ **Backward Compatible:** Existing code continues to work with deprecation warnings
- ✅ **Extensible:** Easy to add new processors via registry

**Timeline:** 4 weeks  
**Risk Level:** Medium (mitigated with careful testing)  
**Impact:** High (major improvement to usability and maintainability)

---

**Next Steps:**
1. Review this plan with maintainers
2. Get approval for architectural direction
3. Begin Phase 1 implementation
4. Weekly progress reports and demos
