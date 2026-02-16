# Processors & Data Transformation Architecture

**Created:** 2026-02-15  
**Status:** PRODUCTION  
**Version:** v1.0 (Post-Consolidation)

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Architecture Overview](#architecture-overview)
3. [Three-Tier Architecture](#three-tier-architecture)
4. [Component Details](#component-details)
5. [Data Flow](#data-flow)
6. [API Reference](#api-reference)
7. [Design Patterns](#design-patterns)
8. [Migration from Legacy](#migration-from-legacy)
9. [Best Practices](#best-practices)

---

## Executive Summary

The IPFS Datasets Python architecture has been consolidated into a clean **three-tier system** that separates concerns between user-facing APIs, data transformation utilities, and IPFS backend operations.

### Key Achievements

- **✅ Unified GraphRAG:** 7 implementations consolidated into `UnifiedGraphRAGProcessor`
- **✅ Clean Multimedia:** Core processors in `processors/multimedia/` with deprecation shims
- **✅ Organized Serialization:** All serialization utilities in `data_transformation/serialization/`
- **✅ Foundational IPLD:** Core IPLD storage remains in `data_transformation/ipld/`
- **✅ 100% Backward Compatible:** All legacy imports work with deprecation warnings

### Architecture Goals

1. **Separation of Concerns:** Clear boundaries between API, transformation, and storage layers
2. **Discoverability:** Intuitive module organization and import paths
3. **Maintainability:** Reduced duplication (eliminated ~170KB duplicate code)
4. **Extensibility:** Protocol-based design allows easy addition of new processors
5. **Backward Compatibility:** 6-month deprecation period for smooth migration

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                          USER APPLICATIONS                           │
│                    (Scripts, Notebooks, Services)                    │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        TIER 1: USER APIs                             │
│                    processors/ - High-level APIs                     │
│                                                                      │
│  ┌────────────────┐  ┌─────────────────┐  ┌───────────────────┐  │
│  │ UniversalProc  │  │  GraphRAG       │  │   Multimedia      │  │
│  │   (Protocol)   │  │  Unified        │  │   Processors      │  │
│  └────────────────┘  └─────────────────┘  └───────────────────┘  │
│                                                                      │
│  ┌────────────────┐  ┌─────────────────┐  ┌───────────────────┐  │
│  │  PDF           │  │  Web Archive    │  │   Legal           │  │
│  │  Processors    │  │  Processors     │  │   Scrapers        │  │
│  └────────────────┘  └─────────────────┘  └───────────────────┘  │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   TIER 2: TRANSFORMATION LAYER                       │
│              data_transformation/ - Core utilities                   │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐│
│  │  IPLD Storage & Knowledge Graphs (FOUNDATIONAL)                ││
│  │  • IPLDStorage, dag_pb, optimized_codec                        ││
│  │  • vector_store, knowledge_graph                               ││
│  │  • Used by 25+ modules across the codebase                     ││
│  └────────────────────────────────────────────────────────────────┘│
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐│
│  │  Serialization Utilities                                        ││
│  │  • car_conversion: Arrow ↔ CAR format                          ││
│  │  • jsonl_to_parquet: JSONL → Parquet/Arrow                     ││
│  │  • dataset_serialization: Dataset ↔ IPLD                       ││
│  │  • ipfs_parquet_to_car: Parquet → CAR                          ││
│  └────────────────────────────────────────────────────────────────┘│
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐│
│  │  Format Utilities                                               ││
│  │  • ipfs_formats: Multiformats handlers                         ││
│  │  • unixfs: UnixFS chunking & operations                        ││
│  │  • ucan: UCAN authorization                                    ││
│  └────────────────────────────────────────────────────────────────┘│
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      TIER 3: IPFS BACKEND                            │
│                                                                      │
│  ┌────────────────┐  ┌─────────────────┐  ┌───────────────────┐  │
│  │  ipfs_kit_py   │  │ ipfshttpclient  │  │ ipfs_accelerate   │  │
│  │                │  │                 │  │                   │  │
│  └────────────────┘  └─────────────────┘  └───────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Three-Tier Architecture

### Tier 1: User APIs (`processors/`)

**Purpose:** High-level, user-facing processing APIs

**Responsibilities:**
- Content processing and transformation
- Orchestration of multiple operations
- User-friendly interfaces
- Error handling and monitoring
- Caching and performance optimization

**Key Components:**

1. **Universal Processor** (`processors/core/`)
   - Protocol-based architecture
   - Input detection (7 types)
   - Priority-based routing (8+ adapters)
   - Single entry point for all processing

2. **GraphRAG Unified** (`processors/graphrag/`)
   - `UnifiedGraphRAGProcessor` - Consolidated implementation
   - 8-phase async pipeline
   - Web archiving, entity extraction, knowledge graphs
   - IPLD integration

3. **Multimedia** (`processors/multimedia/`)
   - FFmpeg wrapper for video/audio processing
   - yt-dlp wrapper for downloads
   - Media processor orchestration
   - Email and Discord processors

4. **Specialized Processors**
   - PDF processing and GraphRAG
   - Web archiving (Internet Archive, Archive.is, Common Crawl)
   - Legal document scraping
   - File conversion (27+ formats)

**Import Pattern:**
```python
# Main package exports (recommended)
from ipfs_datasets_py import UnifiedGraphRAGProcessor, GraphRAGConfiguration

# Direct imports (explicit)
from ipfs_datasets_py.processors.graphrag.unified_graphrag import UnifiedGraphRAGProcessor
from ipfs_datasets_py.processors.multimedia import FFmpegWrapper, YtDlpWrapper
```

### Tier 2: Transformation Layer (`data_transformation/`)

**Purpose:** Low-level data format conversion and storage primitives

**Responsibilities:**
- Format conversion (CAR, Parquet, JSONL, Arrow)
- IPLD storage operations
- Knowledge graph storage
- Serialization/deserialization
- Codec optimization

**Key Components:**

1. **IPLD Infrastructure** (`data_transformation/ipld/`)
   - **Status:** FOUNDATIONAL - DO NOT DEPRECATE
   - Used by 25+ modules across analytics, search, ML, vector stores, logic
   - Core components:
     - `IPLDStorage` - Main storage interface
     - `dag_pb` - DAG-PB format implementation
     - `optimized_codec` - High-performance encoding/decoding
     - `vector_store` - IPLD-based vector storage
     - `knowledge_graph` - IPLD-based knowledge graph storage

2. **Serialization Utilities** (`data_transformation/serialization/`)
   - `car_conversion.py` - DataInterchangeUtils for Arrow ↔ CAR
   - `jsonl_to_parquet.py` - JSONL to Parquet/Arrow conversion
   - `dataset_serialization.py` - Dataset ↔ IPLD serialization (8,263 lines)
   - `ipfs_parquet_to_car.py` - Parquet to CAR conversion

3. **Format Handlers**
   - `ipfs_formats/` - Multiformats support
   - `unixfs.py` - UnixFS chunking and operations
   - `ucan.py` - UCAN authorization

**Import Pattern:**
```python
# IPLD (stable, no deprecation)
from ipfs_datasets_py.data_transformation.ipld import IPLDStorage, KnowledgeGraph

# Serialization (new organized location)
from ipfs_datasets_py.data_transformation.serialization import (
    DataInterchangeUtils,
    DatasetSerializer,
    jsonl_to_parquet
)
```

### Tier 3: IPFS Backend

**Purpose:** Low-level IPFS operations and network communication

**Components:**
- `ipfs_kit_py` - High-level IPFS toolkit
- `ipfshttpclient` - HTTP API client for IPFS daemon
- `ipfs_accelerate_py` - Performance acceleration

**Usage:**
- Typically used indirectly through Tier 2 (IPLD storage)
- Direct use for advanced IPFS operations

---

## Component Details

### UnifiedGraphRAGProcessor

**Location:** `ipfs_datasets_py/processors/graphrag/unified_graphrag.py`

**Features:**
- Consolidates 4 deprecated implementations
- 8-phase async pipeline (web archiving → analytics)
- Multiple processing modes (fast, balanced, quality, comprehensive)
- IPLD knowledge graph integration
- Multi-service web archiving

**Configuration:**
```python
from ipfs_datasets_py.processors.graphrag.unified_graphrag import (
    UnifiedGraphRAGProcessor,
    GraphRAGConfiguration
)

config = GraphRAGConfiguration(
    processing_mode="balanced",  # fast, balanced, quality, comprehensive
    enable_web_archiving=True,
    archive_services=["internet_archive", "archive_is"],
    enable_multi_pass_extraction=True,
    content_quality_threshold=0.6,
    max_depth=2  # Crawl depth
)

processor = UnifiedGraphRAGProcessor(config=config)
result = await processor.process_website("https://example.com")
```

**Replaces:**
- `GraphRAGProcessor` (deprecated)
- `WebsiteGraphRAGProcessor` (deprecated)
- `AdvancedGraphRAGWebsiteProcessor` (deprecated)
- `CompleteGraphRAGSystem` (merged into Unified)

### Multimedia Processors

**Location:** `ipfs_datasets_py/processors/multimedia/`

**Core Components:**
1. **FFmpegWrapper** - Video/audio processing
2. **YtDlpWrapper** - Download from 1000+ platforms
3. **MediaProcessor** - Orchestration
4. **MediaUtils** - Utilities
5. **EmailProcessor** - Email handling
6. **DiscordWrapper** - Discord integration

**Example:**
```python
from ipfs_datasets_py.processors.multimedia import FFmpegWrapper, YtDlpWrapper

# Download video
ytdlp = YtDlpWrapper()
video_path = ytdlp.download("https://youtube.com/watch?v=...")

# Process with FFmpeg
ffmpeg = FFmpegWrapper()
metadata = ffmpeg.get_metadata(video_path)
thumbnail = ffmpeg.extract_frame(video_path, timestamp="00:01:00")
```

### IPLD Storage

**Location:** `ipfs_datasets_py/data_transformation/ipld/`

**Status:** FOUNDATIONAL - Stable, no deprecation planned

**Core Classes:**

1. **IPLDStorage** - Main storage interface
```python
from ipfs_datasets_py.data_transformation.ipld import IPLDStorage

storage = IPLDStorage()
cid = storage.put(data)  # Store data, get CID
retrieved = storage.get(cid)  # Retrieve by CID
```

2. **KnowledgeGraph** - IPLD-based knowledge graph
```python
from ipfs_datasets_py.data_transformation.ipld import KnowledgeGraph

kg = KnowledgeGraph()
kg.add_node(node_id="entity1", label="Person", properties={"name": "Alice"})
kg.add_edge(source="entity1", target="entity2", rel_type="knows")
cid = kg.to_ipld()  # Store in IPLD
```

3. **VectorStore** - IPLD-based vector storage
```python
from ipfs_datasets_py.data_transformation.ipld import VectorStore

vs = VectorStore()
vs.add_embedding(doc_id="doc1", embedding=vector, metadata={...})
results = vs.search(query_vector, top_k=10)
```

---

## Data Flow

### Example: Processing a Website with GraphRAG

```
User Request
    │
    ▼
┌─────────────────────────────────────────┐
│ UnifiedGraphRAGProcessor                 │
│ (Tier 1: User API)                      │
│                                          │
│ 1. Web archiving                        │
│ 2. Content extraction                   │
│ 3. Entity recognition                   │
│ 4. Relationship extraction              │
│ 5. Knowledge graph construction         │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│ Serialization & Storage                  │
│ (Tier 2: Transformation Layer)          │
│                                          │
│ • Dataset serialization                 │
│ • Knowledge graph storage               │
│ • Vector embeddings storage             │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│ IPLD Storage                             │
│ (Tier 2: IPLD Infrastructure)           │
│                                          │
│ • Put data → Get CID                    │
│ • Store in IPLD DAG                     │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│ IPFS Backend                             │
│ (Tier 3: Network Layer)                 │
│                                          │
│ • Persist to IPFS network               │
│ • Content addressing                    │
│ • Retrieval by CID                      │
└─────────────────────────────────────────┘
```

### Example: Multimedia Processing

```
Video URL
    │
    ▼
┌─────────────────────────────────────────┐
│ YtDlpWrapper                             │
│ (Tier 1: Multimedia Processor)          │
│                                          │
│ • Download video                        │
│ • Extract metadata                      │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│ FFmpegWrapper                            │
│ (Tier 1: Media Processing)              │
│                                          │
│ • Transcode formats                     │
│ • Extract frames/audio                  │
│ • Generate thumbnails                   │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│ DatasetSerializer                        │
│ (Tier 2: Serialization)                 │
│                                          │
│ • Serialize media metadata              │
│ • Convert to IPLD format                │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│ IPLD Storage → IPFS                     │
│ (Tiers 2-3: Storage & Network)          │
└─────────────────────────────────────────┘
```

---

## API Reference

### Main Package Exports

**Recommended Imports:**
```python
from ipfs_datasets_py import (
    # GraphRAG
    UnifiedGraphRAGProcessor,
    GraphRAGConfiguration,
    GraphRAGResult,
    
    # Legacy (deprecated but still work)
    GraphRAGProcessor,  # ⚠️ Deprecated
    
    # IPLD
    IPLDStorage,
    
    # Serialization
    DataInterchangeUtils,
    DatasetSerializer,
)
```

### Processor Protocol

All processors in Tier 1 implement `ProcessorProtocol`:

```python
from ipfs_datasets_py.processors.core import ProcessorProtocol

class ProcessorProtocol(Protocol):
    def process(self, input_data: Any, **kwargs) -> ProcessingResult:
        """Process input data and return structured result."""
        ...
    
    def supports(self, input_type: str) -> bool:
        """Check if processor supports given input type."""
        ...
    
    @property
    def priority(self) -> int:
        """Priority for processor routing (higher = earlier)."""
        ...
```

### Universal Processor

```python
from ipfs_datasets_py.processors.core import UniversalProcessor

# Auto-detection and routing
processor = UniversalProcessor()
result = processor.process(input_data)  # Automatically routes to correct processor

# Manual processor selection
result = processor.process(input_data, processor_type="graphrag")
```

---

## Design Patterns

### 1. Protocol-Based Design

All processors implement `ProcessorProtocol` for consistent interfaces:
- Enables polymorphism and easy extension
- Facilitates testing and mocking
- Supports priority-based routing

### 2. Configuration Objects

Use dataclass-based configuration for complex processors:
```python
@dataclass
class GraphRAGConfiguration:
    processing_mode: str = "balanced"
    enable_web_archiving: bool = True
    max_depth: int = 2
    # ... more options
```

Benefits:
- Type safety
- Default values
- Easy serialization
- Self-documenting

### 3. Async-First Architecture

Modern processors use `anyio` for async operations:
```python
async def process_website(self, url: str) -> GraphRAGResult:
    async with anyio.create_task_group() as tg:
        tg.start_soon(self._archive_website, url)
        tg.start_soon(self._extract_entities, url)
    # Process results
```

Benefits:
- Concurrent operations
- Better resource utilization
- Cancellation support

### 4. Deprecation Shims

Maintain backward compatibility with deprecation warnings:
```python
# Old location (deprecated)
# data_transformation/multimedia/__init__.py
warnings.warn(
    "data_transformation.multimedia is deprecated. "
    "Use processors.multimedia instead.",
    DeprecationWarning,
    stacklevel=2
)
from ipfs_datasets_py.processors.multimedia import *
```

### 5. Layered Architecture

Clear separation of concerns:
- **Tier 1:** Business logic and orchestration
- **Tier 2:** Data transformation and storage
- **Tier 3:** Network and persistence

Benefits:
- Testability (can mock lower layers)
- Maintainability (changes isolated to layers)
- Reusability (lower layers used by multiple upper layers)

---

## Migration from Legacy

### Multimedia Migration

**Old (Deprecated):**
```python
from ipfs_datasets_py.data_transformation.multimedia import FFmpegWrapper
```

**New:**
```python
from ipfs_datasets_py.processors.multimedia import FFmpegWrapper
```

**Status:** Deprecation warnings active, removal in v2.0 (6 months)

### Serialization Migration

**Old (Deprecated):**
```python
from ipfs_datasets_py.data_transformation.car_conversion import DataInterchangeUtils
```

**New:**
```python
from ipfs_datasets_py.data_transformation.serialization.car_conversion import DataInterchangeUtils
```

**Status:** Deprecation warnings active, removal in v2.0 (6 months)

### GraphRAG Migration

**Old (Deprecated):**
```python
from ipfs_datasets_py.processors.graphrag_processor import GraphRAGProcessor
processor = GraphRAGProcessor()
```

**New:**
```python
from ipfs_datasets_py.processors.graphrag.unified_graphrag import (
    UnifiedGraphRAGProcessor,
    GraphRAGConfiguration
)
config = GraphRAGConfiguration(processing_mode="balanced")
processor = UnifiedGraphRAGProcessor(config=config)
```

**Status:** All features from 4 deprecated implementations consolidated

### Complete Migration Guide

See [MIGRATION_GUIDE_V2.md](./MIGRATION_GUIDE_V2.md) for comprehensive migration instructions.

---

## Best Practices

### 1. Use Main Package Exports

**✅ Recommended:**
```python
from ipfs_datasets_py import UnifiedGraphRAGProcessor, GraphRAGConfiguration
```

**⚠️ Not recommended:**
```python
from ipfs_datasets_py.processors.graphrag.unified_graphrag import UnifiedGraphRAGProcessor
```

### 2. Configure with Objects

**✅ Recommended:**
```python
config = GraphRAGConfiguration(
    processing_mode="quality",
    enable_web_archiving=True
)
processor = UnifiedGraphRAGProcessor(config=config)
```

**⚠️ Not recommended:**
```python
processor = UnifiedGraphRAGProcessor(
    mode="quality",
    archive=True  # Parameter name unclear
)
```

### 3. Use Async Where Supported

**✅ Recommended:**
```python
result = await processor.process_website(url)
```

**⚠️ Fallback for sync contexts:**
```python
import anyio
result = anyio.run(processor.process_website, url)
```

### 4. Handle Deprecation Warnings

**✅ Acknowledge and plan migration:**
```python
import warnings

# Temporarily suppress while planning migration
with warnings.catch_warnings():
    warnings.filterwarnings('ignore', category=DeprecationWarning)
    from ipfs_datasets_py.processors.graphrag_processor import GraphRAGProcessor
    
# Plan migration within 6 months
```

### 5. Leverage IPLD for Persistence

**✅ Recommended:**
```python
from ipfs_datasets_py.data_transformation.ipld import IPLDStorage

storage = IPLDStorage()
cid = storage.put(data)  # Content-addressed storage
later = storage.get(cid)  # Retrieve by CID
```

Benefits:
- Immutable content addressing
- Decentralized storage
- Deduplication
- Versioning

### 6. Use Protocol-Based Processors

**✅ For extensibility:**
```python
from ipfs_datasets_py.processors.core import ProcessorProtocol

class MyCustomProcessor:
    """Implements ProcessorProtocol."""
    
    def process(self, input_data, **kwargs):
        # Your logic
        return result
    
    def supports(self, input_type: str) -> bool:
        return input_type in ["my_custom_type"]
    
    @property
    def priority(self) -> int:
        return 15  # Priority for routing
```

---

## Architecture Evolution

### Version History

**v0.x - v0.9:** Initial development
- Fragmented organization
- Multiple duplicate implementations
- Mixed concerns

**v1.0 (Current):** Post-consolidation
- ✅ Three-tier architecture
- ✅ Unified GraphRAG
- ✅ Organized multimedia and serialization
- ✅ Backward compatibility with deprecation warnings

**v2.0 (Future - 6 months):** Clean architecture
- Removal of deprecated components
- Enhanced protocol support
- Performance optimizations
- Extended processor ecosystem

### Consolidation Benefits

**Code Reduction:**
- ~170KB duplicate GraphRAG code eliminated
- ~361KB multimedia duplicates removed
- Cleaner import structure

**Improved Maintainability:**
- Single source of truth for each feature
- Clear module boundaries
- Reduced cognitive load

**Better Performance:**
- Unified implementations can be optimized globally
- Reduced memory footprint
- Faster imports

---

## Related Documentation

- [MIGRATION_GUIDE_V2.md](./MIGRATION_GUIDE_V2.md) - Complete v2.0 migration guide
- [DEPRECATION_TIMELINE.md](./DEPRECATION_TIMELINE.md) - Deprecation schedule
- [GRAPHRAG_CONSOLIDATION_GUIDE.md](./GRAPHRAG_CONSOLIDATION_GUIDE.md) - GraphRAG migration
- [MULTIMEDIA_MIGRATION_GUIDE.md](./MULTIMEDIA_MIGRATION_GUIDE.md) - Multimedia migration
- [PHASE_4_GRAPHRAG_IMPLEMENTATION_COMPLETE.md](./PHASE_4_GRAPHRAG_IMPLEMENTATION_COMPLETE.md) - Implementation details

---

## Summary

The IPFS Datasets Python architecture provides a **clean, maintainable, and extensible** foundation for data processing and decentralized storage:

1. **Three-Tier Architecture:** Clear separation between user APIs, transformation utilities, and IPFS backend
2. **Unified GraphRAG:** Consolidated 7 implementations into single processor
3. **Organized Components:** Multimedia in `processors/`, serialization in `data_transformation/serialization/`, IPLD stays foundational
4. **Backward Compatible:** 6-month deprecation period with helpful warnings
5. **Protocol-Based:** Easy to extend with new processors
6. **Production-Ready:** 182+ tests, comprehensive documentation

**Next Steps:**
1. Review [MIGRATION_GUIDE_V2.md](./MIGRATION_GUIDE_V2.md) for migration planning
2. Check [DEPRECATION_TIMELINE.md](./DEPRECATION_TIMELINE.md) for important dates
3. Start migrating deprecated imports to unified APIs
4. Plan for v2.0 upgrade within 6 months

---

**Last Updated:** 2026-02-15  
**Status:** Complete  
**Maintainer:** IPFS Datasets Python Team
