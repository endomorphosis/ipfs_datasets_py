# Quick Start Guide - New Architecture (v1.0+)

Welcome to IPFS Datasets Python with the new consolidated architecture! This guide helps you get started quickly with the unified system.

## 🎯 What's New?

**Clean 3-Tier Architecture:**
1. **Tier 1:** User APIs (`processors/`) - High-level processing
2. **Tier 2:** Transformation (`data_transformation/`) - Format conversion, IPLD
3. **Tier 3:** IPFS Backend - Network operations

**Key Improvements:**
- ✅ Unified GraphRAG processor (7 implementations → 1)
- ✅ Organized multimedia in `processors/multimedia/`
- ✅ Organized serialization in `data_transformation/serialization/`
- ✅ Clear separation of concerns
- ✅ Protocol-based extensibility

## 🚀 Quick Start

### Installation

```bash
git clone https://github.com/endomorphosis/ipfs_datasets_py.git
cd ipfs_datasets_py

# Quick setup (core dependencies)
python scripts/setup/install.py --quick

# Or full installation
pip install -e ".[all]"
```

### Basic Usage

#### 1. GraphRAG Processing (Unified)

```python
from ipfs_datasets_py import UnifiedGraphRAGProcessor, GraphRAGConfiguration

# Create configuration
config = GraphRAGConfiguration(
    processing_mode="balanced",  # fast, balanced, quality, comprehensive
    enable_web_archiving=True,
    max_depth=2
)

# Initialize processor
processor = UnifiedGraphRAGProcessor(config=config)

# Process a website
result = await processor.process_website("https://example.com")

# Query the knowledge graph
query_result = await processor.process_query(
    "What is this website about?",
    context=result
)
```

#### 2. Multimedia Processing

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

#### 3. Serialization

```python
from ipfs_datasets_py.data_transformation.serialization import (
    DataInterchangeUtils,
    DatasetSerializer
)

# Convert dataset to CAR format
serializer = DatasetSerializer()
car_cid = serializer.dataset_to_car(dataset, output="output.car")

# Arrow ↔ CAR conversion
utils = DataInterchangeUtils()
car_data = utils.arrow_to_car(arrow_table)
arrow_back = utils.car_to_arrow(car_data)
```

#### 4. IPLD Storage (Foundational)

```python
from ipfs_datasets_py.data_transformation.ipld import IPLDStorage, KnowledgeGraph

# IPLD storage
storage = IPLDStorage()
cid = storage.put(data)
retrieved = storage.get(cid)

# Knowledge graph storage
kg = KnowledgeGraph()
kg.add_node(node_id="entity1", label="Person", properties={"name": "Alice"})
kg.add_edge(source="entity1", target="entity2", rel_type="knows")
kg_cid = kg.to_ipld()
```

## 📖 Migration from Older Versions

If you're upgrading from pre-v1.0, your old imports still work but show deprecation warnings:

### Multimedia Migration

```python
# ⚠️ OLD (deprecated - works but shows warning)
from ipfs_datasets_py.data_transformation.multimedia import FFmpegWrapper

# ✅ NEW (recommended)
from ipfs_datasets_py.processors.multimedia import FFmpegWrapper
```

### Serialization Migration

```python
# ⚠️ OLD (deprecated - works but shows warning)
from ipfs_datasets_py.data_transformation.car_conversion import DataInterchangeUtils

# ✅ NEW (recommended)
from ipfs_datasets_py.data_transformation.serialization.car_conversion import DataInterchangeUtils
```

### GraphRAG Migration

```python
# ⚠️ OLD (deprecated - works but shows warning)
from ipfs_datasets_py.processors.graphrag_processor import GraphRAGProcessor
processor = GraphRAGProcessor()

# ✅ NEW (unified processor)
from ipfs_datasets_py import UnifiedGraphRAGProcessor, GraphRAGConfiguration
config = GraphRAGConfiguration(processing_mode="balanced")
processor = UnifiedGraphRAGProcessor(config=config)
```

**Timeline:**
- Your old code works until v2.0 (August 2026)
- 6-month window to migrate
- See [MIGRATION_GUIDE_V2.md](MIGRATION_GUIDE_V2.md) for complete guide

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    YOUR APPLICATION                      │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│              Tier 1: User APIs (processors/)            │
│                                                          │
│  • UnifiedGraphRAGProcessor                             │
│  • Multimedia (FFmpeg, yt-dlp)                          │
│  • PDF/Web processors                                   │
│  • Universal processor                                  │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│      Tier 2: Transformation (data_transformation/)      │
│                                                          │
│  • IPLD storage (foundational)                          │
│  • Serialization utilities                              │
│  • Format handlers                                      │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│               Tier 3: IPFS Backend                      │
│                                                          │
│  • ipfs_kit_py                                          │
│  • ipfshttpclient                                       │
│  • ipfs_accelerate_py                                   │
└─────────────────────────────────────────────────────────┘
```

## 💡 Common Patterns

### Pattern 1: Process Website → Knowledge Graph

```python
from ipfs_datasets_py import UnifiedGraphRAGProcessor, GraphRAGConfiguration

# Configure
config = GraphRAGConfiguration(
    processing_mode="quality",
    enable_web_archiving=True,
    archive_services=["internet_archive", "archive_is"],
    enable_multi_pass_extraction=True
)

# Process
processor = UnifiedGraphRAGProcessor(config=config)
result = await processor.process_website("https://example.com")

# Access knowledge graph
entities = result.knowledge_graph.entities
relationships = result.knowledge_graph.relationships

# Query
answer = await processor.process_query("What are the main topics?", context=result)
```

### Pattern 2: Download → Process → Store

```python
from ipfs_datasets_py.processors.multimedia import YtDlpWrapper
from ipfs_datasets_py.data_transformation.serialization import DatasetSerializer
from ipfs_datasets_py.data_transformation.ipld import IPLDStorage

# Download
ytdlp = YtDlpWrapper()
video_path = ytdlp.download("https://example.com/video")

# Serialize metadata
serializer = DatasetSerializer()
metadata_car = serializer.dict_to_car({"video": video_path, "source": "youtube"})

# Store in IPLD
storage = IPLDStorage()
cid = storage.put(metadata_car)
print(f"Stored at: {cid}")
```

### Pattern 3: Protocol-Based Processing

```python
from ipfs_datasets_py.processors.core import UniversalProcessor

# Universal processor auto-detects input type
processor = UniversalProcessor()

# Works with URLs, files, text, etc.
result1 = processor.process("https://example.com")  # Auto-routed to web processor
result2 = processor.process("data.pdf")  # Auto-routed to PDF processor
result3 = processor.process("Some text to analyze")  # Auto-routed to text processor
```

## 🔧 Configuration

### GraphRAG Configuration Options

```python
GraphRAGConfiguration(
    # Processing mode
    processing_mode="balanced",  # fast, balanced, quality, comprehensive
    
    # Web archiving
    enable_web_archiving=True,
    archive_services=["internet_archive", "archive_is", "common_crawl"],
    max_depth=2,  # Crawl depth
    
    # Content quality
    content_quality_threshold=0.6,
    enable_multi_pass_extraction=True,
    
    # Knowledge graph
    enable_comprehensive_search=True,
    enable_entity_linking=True,
    
    # Performance
    batch_size=10,
    max_workers=4
)
```

### Processing Modes

| Mode | Speed | Quality | Use Case |
|------|-------|---------|----------|
| `fast` | ⚡⚡⚡ | ⭐ | Quick tests, prototyping |
| `balanced` | ⚡⚡ | ⭐⭐ | General use (default) |
| `quality` | ⚡ | ⭐⭐⭐ | Production, important data |
| `comprehensive` | 🐌 | ⭐⭐⭐⭐ | Research, critical analysis |

## 🧪 Testing Your Setup

```python
# Test imports work
from ipfs_datasets_py import UnifiedGraphRAGProcessor, GraphRAGConfiguration
from ipfs_datasets_py.processors.multimedia import FFmpegWrapper
from ipfs_datasets_py.data_transformation.serialization import DataInterchangeUtils
from ipfs_datasets_py.data_transformation.ipld import IPLDStorage

print("✅ All imports successful!")

# Test basic functionality
config = GraphRAGConfiguration(processing_mode="fast")
processor = UnifiedGraphRAGProcessor(config=config)
print(f"✅ UnifiedGraphRAGProcessor initialized: {processor}")
```

## 📚 Documentation

### Architecture & Migration
- [PROCESSORS_DATA_TRANSFORMATION_ARCHITECTURE.md](guides/processors/PROCESSORS_DATA_TRANSFORMATION_ARCHITECTURE.md) - Complete architecture
- [MIGRATION_GUIDE_V2.md](MIGRATION_GUIDE_V2.md) - v1.x → v2.0 migration
- [DEPRECATION_TIMELINE.md](DEPRECATION_TIMELINE.md) - 6-month timeline

### Component-Specific
- [GRAPHRAG_CONSOLIDATION_GUIDE.md](GRAPHRAG_CONSOLIDATION_GUIDE.md) - GraphRAG details
- [MULTIMEDIA_MIGRATION_GUIDE.md](MULTIMEDIA_MIGRATION_GUIDE.md) - Multimedia details

### Implementation
- [IMPLEMENTATION_ROADMAP_COMPLETE.md](archive/completion_reports/IMPLEMENTATION_ROADMAP_COMPLETE.md) - Roadmap summary
- [PHASE_6_TESTING_VALIDATION_COMPLETE.md](archive/completion_reports/phases/PHASE_6_TESTING_VALIDATION_COMPLETE.md) - Testing report

## 🔍 Migration Tools

Check your codebase for deprecated imports:

```bash
# Scan for deprecated imports
python scripts/tools/migration_checker.py /path/to/your/code

# Verbose output with suggestions
python scripts/tools/migration_checker.py . --verbose

# Check v2.0 compatibility
python scripts/tools/migration_checker.py . --target v2.0
```

## 💬 Support

- **GitHub Issues:** https://github.com/endomorphosis/ipfs_datasets_py/issues
- **Discussions:** https://github.com/endomorphosis/ipfs_datasets_py/discussions
- **Documentation:** [docs/](.)

## 🎉 Next Steps

1. Try the examples above
2. Read [MIGRATION_GUIDE_V2.md](MIGRATION_GUIDE_V2.md) if upgrading
3. Explore [PROCESSORS_DATA_TRANSFORMATION_ARCHITECTURE.md](guides/processors/PROCESSORS_DATA_TRANSFORMATION_ARCHITECTURE.md) for deep dive
4. Check [GRAPHRAG_CONSOLIDATION_GUIDE.md](GRAPHRAG_CONSOLIDATION_GUIDE.md) for advanced GraphRAG usage

---

**Welcome to the new architecture!** 🚀

The consolidation provides a cleaner, more maintainable system while preserving all functionality. Enjoy exploring!
