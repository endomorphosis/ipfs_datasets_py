# Processors Refactoring Quick Reference

**Quick navigation for the comprehensive refactoring plan**

## 🎯 Goal
Create a **single Universal Processor** entry point that handles any URL/file/folder and intelligently routes to specialized processors for knowledge graph and vector generation.

## 📊 Current State
- **138 Python files** in processors/
- **~3,500 lines** of GraphRAG duplication (4 implementations)
- **453 multimedia files** still in data_transformation/
- **No unified entry point** - users must know which processor to use
- **Inconsistent APIs** across processors

## 🎯 Target State
- **Single UniversalProcessor** API for all processing
- **~1,500 lines** of consolidated GraphRAG (57% reduction)
- **All multimedia** in processors/multimedia/
- **Pluggable architecture** with ProcessorProtocol
- **Automatic routing** via InputDetector and ProcessorRegistry

## 🏗️ Architecture

```
UniversalProcessor (single entry)
    ↓
InputDetector (classify: URL/file/folder/text/binary)
    ↓
ProcessorRegistry (map input → processor)
    ↓
Adapters (PDF, GraphRAG, Media, Legal, Wiki, etc.)
    ↓
Specialized Processors
    ↓
KnowledgeGraph + Vectors (standardized output)
```

## 📝 Usage Example

### Before (Old Way)
```python
# Must know which processor to use
from ipfs_datasets_py.processors import graphrag_processor
from ipfs_datasets_py.processors import pdf_processor

if is_pdf(input):
    proc = pdf_processor.PDFProcessor()
elif is_url(input):
    proc = graphrag_processor.GraphRAGProcessor()
    
result = proc.process(input)
```

### After (New Way)
```python
# Single entry point, automatic routing
from ipfs_datasets_py.processors import UniversalProcessor

processor = UniversalProcessor()
result = processor.process(input)  # Handles ANY type

# Returns standardized result:
# - result.knowledge_graph (entities, relationships)
# - result.vectors (embeddings)
# - result.metadata
```

## 📅 Timeline (4 Weeks)

### Week 1: Foundation
- **Phase 1** (Days 1-5): Core infrastructure
  - ProcessorProtocol interface
  - InputDetector (classify inputs)
  - ProcessorRegistry (routing)
  - UniversalProcessor (entry point)

- **Phase 2 Start** (Days 6-7): GraphRAG analysis

### Week 2: Consolidation
- **Phase 2** (Days 8-10): GraphRAG consolidation
  - Merge 4 implementations → 1
  - Deprecate old versions
  - Create GraphRAG adapter

- **Phase 3** (Days 11-14): Multimedia migration
  - Move 453 files to processors/
  - Backward compatibility shims
  - Update all imports

### Week 3: Standardization
- **Phase 4** (Days 15-21): Create adapters
  - 8 adapters: PDF, GraphRAG, Media, Legal, Wiki, Geo, Patent, Multimodal
  - Standardize error handling
  - Consistent interfaces

### Week 4: Polish
- **Phase 5** (Days 22-25): Performance
  - Caching layer
  - Parallel processing
  - Benchmarks

- **Phase 6** (Days 26-28): Documentation
  - Architecture docs
  - API reference
  - Migration guides
  - 50+ test files

## 📦 Core Components

### 1. ProcessorProtocol
```python
class ProcessorProtocol(Protocol):
    def can_handle(self, context: ProcessingContext) -> bool: ...
    def process(self, context: ProcessingContext) -> ProcessingResult: ...
    def get_capabilities(self) -> Dict[str, Any]: ...
```

### 2. InputDetector
- Detects: URLs, files, folders, text, binary
- Extracts: Format, mime type, metadata
- Creates: ProcessingContext for routing

### 3. ProcessorRegistry
- Manages: All processor adapters
- Finds: Best processor for input
- Supports: Priority-based selection

### 4. UniversalProcessor
- Entry point: Single API for all
- Routing: Automatic via detector + registry
- Output: Standardized ProcessingResult

## 🔌 Adapters (8 Total)

1. **PDFAdapter** - PDF documents
2. **GraphRAGAdapter** - URLs, text, documents
3. **MultimediaAdapter** - Video, audio, images
4. **LegalAdapter** - Legal documents
5. **WikipediaAdapter** - Wikipedia URLs
6. **GeospatialAdapter** - Geo data
7. **PatentAdapter** - Patent documents
8. **BatchAdapter** - Folders, multiple files

Each adapter:
- Implements ProcessorProtocol
- Wraps existing processor
- Returns standardized ProcessingResult

## 📁 New File Structure

```
processors/
├── universal_processor.py (main entry, ~400 lines)
├── core/
│   ├── protocol.py (interface, ~150 lines)
│   ├── input_detector.py (~300 lines)
│   ├── registry.py (~250 lines)
│   ├── errors.py (~100 lines)
│   ├── cache.py (~200 lines)
│   └── parallel.py (~150 lines)
├── adapters/ (8 adapters, ~1,500 lines total)
├── graphrag/unified_graphrag.py (~1,500 lines consolidated)
├── multimedia/ (453 files moved from data_transformation)
└── [deprecated with warnings]
```

## 📈 Benefits

### Users
- ✅ Single API to learn
- ✅ Automatic routing
- ✅ Consistent results
- ✅ Built-in caching/parallelization

### Developers
- ✅ Clear interfaces
- ✅ Pluggable architecture
- ✅ Easy testing
- ✅ Better organization

### Codebase
- ✅ ~2,500 lines eliminated
- ✅ Reduced duplication
- ✅ Standardized APIs
- ✅ Improved maintainability

## 🎓 Migration Guide

### Simple Case
```python
# Old
from ipfs_datasets_py.processors.graphrag_processor import GraphRAGProcessor
processor = GraphRAGProcessor()
result = processor.process(url)

# New
from ipfs_datasets_py.processors import UniversalProcessor
processor = UniversalProcessor()
result = processor.process(url)  # Same result format
```

### Batch Processing
```python
# Old - manual loop
results = []
for file in files:
    result = processor.process(file)
    results.append(result)

# New - built-in parallel
processor = UniversalProcessor()
results = processor.process_batch(files)
```

### Folder Processing
```python
# Old - manual scanning
import os
for file in os.listdir(folder):
    path = os.path.join(folder, file)
    result = processor.process(path)

# New - automatic
processor = UniversalProcessor()
results = processor.process_folder(folder)
```

## 🚀 Getting Started

### For Users
```python
# Install (once refactoring complete)
pip install ipfs_datasets_py

# Import
from ipfs_datasets_py.processors import UniversalProcessor

# Use
processor = UniversalProcessor()
result = processor.process("any/input/here")
```

### For Developers
```python
# Create custom processor
from ipfs_datasets_py.processors.core import ProcessorProtocol

class MyCustomProcessor:
    def can_handle(self, context): ...
    def process(self, context): ...
    def get_capabilities(self): ...

# Register
from ipfs_datasets_py.processors import UniversalProcessor
processor = UniversalProcessor()
processor.registry.register("my_processor", MyCustomProcessor())

# Use
result = processor.process(input)  # Will route to your processor if applicable
```

## 📚 Documentation

After refactoring, see:
- `docs/PROCESSORS_ARCHITECTURE.md` - Detailed architecture
- `docs/PROCESSORS_API_REFERENCE.md` - Complete API docs
- `docs/PROCESSORS_MIGRATION_GUIDE.md` - Migration examples
- `docs/PROCESSORS_ADDING_NEW.md` - Add custom processors

## ✅ Success Criteria

- [ ] Single UniversalProcessor handles 95%+ of cases
- [ ] ~2,500 lines eliminated (GraphRAG + duplication)
- [ ] 100% backward compatible (old APIs still work)
- [ ] Test coverage >90%
- [ ] Performance targets met:
  - Input detection: <1ms
  - Routing: <5ms
  - PDF: <2s per page
  - URL: <10s per page
  - Batch: 10+ files/sec

## 📞 Support

Questions? See comprehensive plan:
`docs/PROCESSORS_COMPREHENSIVE_REFACTORING_PLAN.md`

---

**Status:** Planning Complete  
**Timeline:** 4 weeks  
**Next:** Phase 1 - Core Infrastructure
