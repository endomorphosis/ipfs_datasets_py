# GraphRAG Consolidation Migration Guide

**Created:** 2026-02-15  
**Target Version:** 2.0.0 (6-month deprecation period)  
**Status:** Active - Deprecation warnings in place

---

## Overview

This guide helps you migrate from **deprecated GraphRAG implementations** to the **unified UnifiedGraphRAGProcessor**. The consolidation reduces code duplication by 62-67% while preserving all functionality.

### What's Changing?

**7 GraphRAG implementations** are being consolidated into **1 unified processor**:

| Old Implementation | Status | Replacement |
|-------------------|--------|-------------|
| `GraphRAGProcessor` | ⚠️ DEPRECATED (v1.0) | `UnifiedGraphRAGProcessor` |
| `WebsiteGraphRAGProcessor` | ⚠️ DEPRECATED (v1.0) | `UnifiedGraphRAGProcessor` |
| `AdvancedGraphRAGWebsiteProcessor` | ⚠️ DEPRECATED (v1.0) | `UnifiedGraphRAGProcessor` |
| `CompleteGraphRAGSystem` | ✅ MERGED | Source for Unified |
| `GraphRAGIntegration` | ✅ KEEP | LLM enhancement layer |
| `NeurosymbolicGraphRAG` | ✅ KEEP | Logic enhancement layer |
| `GraphRAGAdapter` | ✅ KEEP | UniversalProcessor integration |

---

## Migration Timeline

| Version | Date | Status |
|---------|------|--------|
| **v1.0+** | 2026-02-15 | Deprecation warnings active, all features work |
| **v1.5** | ~2026-05-15 | Enhanced warnings, migration tools available |
| **v1.9** | ~2026-07-15 | Final warning period, legacy support EOL soon |
| **v2.0** | ~2026-08-15 | **REMOVAL** - Deprecated classes removed |

**⏰ You have ~6 months to migrate before v2.0 removes deprecated classes.**

---

## Quick Migration Examples

### 1. Basic GraphRAGProcessor → UnifiedGraphRAGProcessor

**BEFORE (Deprecated):**
```python
from ipfs_datasets_py.processors.graphrag_processor import GraphRAGProcessor

# Initialize with basic components
processor = GraphRAGProcessor(
    vector_store=my_vector_store,
    knowledge_graph=my_kg,
    embedding_model="sentence-transformers/all-MiniLM-L6-v2"
)

# Query the graph
results = processor.query(
    query_text="What is machine learning?",
    top_k=10
)
```

**AFTER (Unified):**
```python
from ipfs_datasets_py.processors.graphrag.unified_graphrag import (
    UnifiedGraphRAGProcessor,
    GraphRAGConfiguration
)

# Configure the processor
config = GraphRAGConfiguration(
    processing_mode="balanced",  # fast, balanced, quality, comprehensive
    enable_comprehensive_search=True
)

# Initialize
processor = UnifiedGraphRAGProcessor(
    config=config,
    vector_store=my_vector_store,
    knowledge_graph=my_kg
)

# Query the graph (now async)
results = await processor.process_query(
    query="What is machine learning?",
    top_k=10
)
```

**Key Changes:**
- ✅ Configuration object for better organization
- ✅ Async-first API (use `await`)
- ✅ More processing modes available
- ✅ Enhanced search capabilities

---

### 2. WebsiteGraphRAGProcessor → UnifiedGraphRAGProcessor

**BEFORE (Deprecated):**
```python
from ipfs_datasets_py.processors.website_graphrag_processor import (
    WebsiteGraphRAGProcessor,
    WebsiteProcessingConfig
)

# Configure for website processing
config = WebsiteProcessingConfig(
    archive_services=['ia', 'is'],
    crawl_depth=2,
    include_media=True,
    enable_graphrag=True
)

# Process website
processor = WebsiteGraphRAGProcessor(config=config)
graphrag_system = await processor.process_website(
    url="https://example.com",
    output_dir="output/"
)

# Query the result
results = graphrag_system.query("What is this website about?")
```

**AFTER (Unified):**
```python
from ipfs_datasets_py.processors.graphrag.unified_graphrag import (
    UnifiedGraphRAGProcessor,
    GraphRAGConfiguration,
    GraphRAGResult
)

# Configure with web archiving enabled
config = GraphRAGConfiguration(
    processing_mode="comprehensive",
    enable_web_archiving=True,
    archive_services=["internet_archive", "archive_is"],
    max_depth=2,
    enable_audio_transcription=False,  # Optional media processing
    enable_video_processing=False,
    output_directory="output/"
)

# Process website
processor = UnifiedGraphRAGProcessor(config=config)
result: GraphRAGResult = await processor.process_website(
    url="https://example.com"
)

# Query the knowledge graph
query_results = await processor.process_query(
    query="What is this website about?",
    context=result  # Pass result for context
)
```

**Key Changes:**
- ✅ Single configuration object
- ✅ Consistent async API
- ✅ Typed result objects
- ✅ Context-aware querying

---

### 3. AdvancedGraphRAGWebsiteProcessor → UnifiedGraphRAGProcessor

**BEFORE (Deprecated):**
```python
from ipfs_datasets_py.processors.advanced_graphrag_website_processor import (
    AdvancedGraphRAGWebsiteProcessor,
    AdvancedProcessingConfig
)

# Advanced configuration
config = AdvancedProcessingConfig(
    enable_multi_pass_extraction=True,
    quality_threshold=0.7,
    enable_domain_patterns=True,
    optimization_level="aggressive"
)

processor = AdvancedGraphRAGWebsiteProcessor(config=config)
result = await processor.process_website_advanced(
    url="https://example.com",
    deep_analysis=True
)
```

**AFTER (Unified):**
```python
from ipfs_datasets_py.processors.graphrag.unified_graphrag import (
    UnifiedGraphRAGProcessor,
    GraphRAGConfiguration
)

# Unified configuration with advanced features
config = GraphRAGConfiguration(
    processing_mode="quality",  # or "comprehensive" for deepest analysis
    enable_multi_pass_extraction=True,
    content_quality_threshold=0.7,
    enable_adaptive_optimization=True,
    enable_web_archiving=True,
    max_depth=3  # Deep analysis
)

processor = UnifiedGraphRAGProcessor(config=config)
result = await processor.process_website(
    url="https://example.com"
)

# Access quality metrics
print(f"Quality score: {result.content_metadata.get('quality_score', 0)}")
print(f"Entities extracted: {len(result.entities)}")
```

**Key Changes:**
- ✅ Unified processing modes
- ✅ Built-in quality assessment
- ✅ Adaptive optimization
- ✅ Comprehensive metadata

---

## Configuration Migration

### Processing Modes

The unified processor has 4 processing modes:

| Mode | Use Case | Speed | Quality | Features |
|------|----------|-------|---------|----------|
| `fast` | Quick prototyping, testing | ⚡⚡⚡ | ⭐ | Basic extraction only |
| `balanced` | **DEFAULT** - Most use cases | ⚡⚡ | ⭐⭐⭐ | Standard features |
| `quality` | High-quality content extraction | ⚡ | ⭐⭐⭐⭐ | Multi-pass, quality checks |
| `comprehensive` | Research, deep analysis | 🐌 | ⭐⭐⭐⭐⭐ | All features, max depth |

### Configuration Mapping

| Old Config | Unified Config | Notes |
|------------|----------------|-------|
| `GraphRAGProcessor(vector_store=vs)` | `config.processing_mode="balanced"` | Standard mode |
| `WebsiteProcessingConfig(archive_services=['ia'])` | `config.archive_services=["internet_archive"]` | Updated names |
| `AdvancedProcessingConfig(quality_threshold=0.7)` | `config.content_quality_threshold=0.7` | Same behavior |
| `crawl_depth=2` | `max_depth=2` | Renamed for clarity |
| `enable_graphrag=True` | `enable_full_pipeline=True` | Default True |

---

## Feature Comparison

### All Features Available in Unified Processor

| Feature | GraphRAGProcessor | WebsiteGraphRAGProcessor | AdvancedGraphRAGWebsiteProcessor | UnifiedGraphRAGProcessor |
|---------|-------------------|-------------------------|----------------------------------|--------------------------|
| Vector search | ✅ | ✅ | ✅ | ✅ |
| Graph traversal | ✅ | ✅ | ✅ | ✅ |
| Web archiving | ❌ | ✅ | ✅ | ✅ |
| Entity extraction | Basic | Basic | ✅ Advanced | ✅ Advanced |
| Multi-pass extraction | ❌ | ❌ | ✅ | ✅ |
| Quality assessment | ❌ | ❌ | ✅ | ✅ |
| Media processing | ❌ | ✅ | ✅ | ✅ |
| IPLD integration | ❌ | ❌ | ❌ | ✅ |
| Async-first | ❌ | ✅ | ✅ | ✅ |
| Adaptive optimization | ❌ | ❌ | ✅ | ✅ |

**✅ No functionality is lost in the consolidation!**

---

## Common Migration Patterns

### Pattern 1: Simple Query

```python
# OLD
processor = GraphRAGProcessor(vector_store=vs)
results = processor.query("search query")

# NEW
processor = UnifiedGraphRAGProcessor()
results = await processor.process_query("search query")
```

### Pattern 2: Website Crawling

```python
# OLD
processor = WebsiteGraphRAGProcessor()
system = await processor.process_website("https://example.com")

# NEW
config = GraphRAGConfiguration(enable_web_archiving=True)
processor = UnifiedGraphRAGProcessor(config=config)
result = await processor.process_website("https://example.com")
```

### Pattern 3: Batch Processing

```python
# OLD
processor = GraphRAGProcessor(vector_store=vs)
for url in urls:
    result = processor.process(url)
    
# NEW (with async)
config = GraphRAGConfiguration(processing_mode="fast")
processor = UnifiedGraphRAGProcessor(config=config)

async def process_batch(urls):
    results = []
    async with anyio.create_task_group() as tg:
        for url in urls:
            tg.start_soon(processor.process_website, url)
    return results

results = await process_batch(urls)
```

### Pattern 4: Custom Configuration

```python
# OLD (separate configs for each processor)
web_config = WebsiteProcessingConfig(crawl_depth=3)
advanced_config = AdvancedProcessingConfig(quality_threshold=0.8)

# NEW (single unified config)
config = GraphRAGConfiguration(
    processing_mode="quality",
    max_depth=3,
    content_quality_threshold=0.8,
    enable_web_archiving=True,
    enable_multi_pass_extraction=True
)
processor = UnifiedGraphRAGProcessor(config=config)
```

---

## Handling Deprecation Warnings

### Suppressing Warnings (Temporary)

If you need time to migrate but want to suppress warnings:

```python
import warnings
from ipfs_datasets_py.processors.graphrag_processor import DeprecatedGraphRAGWarning

# Suppress for testing (NOT recommended for production)
warnings.filterwarnings('ignore', category=DeprecatedGraphRAGWarning)

# Your old code here
from ipfs_datasets_py.processors.graphrag_processor import GraphRAGProcessor
processor = GraphRAGProcessor()
```

**⚠️ Note:** This is temporary. Deprecated classes will be removed in v2.0.

### Testing Both Old and New

```python
import warnings

def test_with_old_processor():
    """Test with deprecated processor (verify warnings appear)"""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        
        from ipfs_datasets_py.processors.graphrag_processor import GraphRAGProcessor
        processor = GraphRAGProcessor()
        
        # Should have at least one deprecation warning
        assert len(w) >= 1
        assert issubclass(w[0].category, DeprecationWarning)

def test_with_new_processor():
    """Test with unified processor (no warnings)"""
    from ipfs_datasets_py.processors.graphrag.unified_graphrag import UnifiedGraphRAGProcessor
    
    processor = UnifiedGraphRAGProcessor()
    # No warnings expected
```

---

## Advanced Topics

### Integrating with Specialized Layers

The unified processor works seamlessly with specialized enhancement layers:

#### 1. LLM-Enhanced Queries (GraphRAGIntegration)

```python
from ipfs_datasets_py.processors.graphrag.unified_graphrag import UnifiedGraphRAGProcessor
from ipfs_datasets_py.search.graphrag_integration import GraphRAGIntegration

# Create unified processor
unified_processor = UnifiedGraphRAGProcessor()
result = await unified_processor.process_website("https://example.com")

# Enhance with LLM reasoning
llm_integration = GraphRAGIntegration(
    knowledge_graph=result.knowledge_graph,
    vector_store=unified_processor.vector_store
)
enhanced_results = llm_integration.query_with_reasoning(
    "Explain the main concepts on this website"
)
```

#### 2. Logic-Enhanced Queries (NeurosymbolicGraphRAG)

```python
from ipfs_datasets_py.processors.graphrag.unified_graphrag import UnifiedGraphRAGProcessor
from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic_graphrag import NeurosymbolicGraphRAG

# Process legal document
unified_processor = UnifiedGraphRAGProcessor()
result = await unified_processor.process_document("contract.pdf")

# Add logic reasoning for contract analysis
neurosymbolic = NeurosymbolicGraphRAG(
    knowledge_graph=result.knowledge_graph,
    logic_engine="tdfol"  # Time-dependent first-order logic
)
legal_analysis = neurosymbolic.analyze_contract(result)
```

### IPLD Integration

The unified processor has built-in IPLD support:

```python
from ipfs_datasets_py.processors.graphrag.unified_graphrag import (
    UnifiedGraphRAGProcessor,
    GraphRAGConfiguration
)

config = GraphRAGConfiguration(
    processing_mode="comprehensive",
    output_directory="ipld_output"
)

processor = UnifiedGraphRAGProcessor(config=config)
result = await processor.process_website("https://example.com")

# Knowledge graph is automatically stored in IPLD
ipld_cid = result.knowledge_graph.ipld_cid
print(f"Knowledge graph stored at: {ipld_cid}")

# Can retrieve later
from ipfs_datasets_py.data_transformation.ipld import IPLDStorage
storage = IPLDStorage()
kg = storage.get_knowledge_graph(ipld_cid)
```

---

## Troubleshooting

### Issue: Import Error

**Problem:**
```python
ImportError: cannot import name 'GraphRAGProcessor' from 'ipfs_datasets_py.processors.graphrag'
```

**Solution:**
Update import path - the old processor is in `processors/` root, not `processors/graphrag/`:
```python
# OLD - still works with warning
from ipfs_datasets_py.processors.graphrag_processor import GraphRAGProcessor

# NEW - unified processor
from ipfs_datasets_py.processors.graphrag.unified_graphrag import UnifiedGraphRAGProcessor
```

### Issue: Async Required

**Problem:**
```python
TypeError: object GraphRAGResult can't be used in 'await' expression
```

**Solution:**
The unified processor is async-first. Use `await`:
```python
# Wrong
result = processor.process_website("https://example.com")

# Correct
result = await processor.process_website("https://example.com")

# Or use anyio.run() if not in async context
import anyio
result = anyio.run(processor.process_website, "https://example.com")
```

### Issue: Configuration Mismatch

**Problem:**
```python
TypeError: __init__() got an unexpected keyword argument 'crawl_depth'
```

**Solution:**
Configuration parameter names changed. Use `GraphRAGConfiguration`:
```python
# OLD
config = WebsiteProcessingConfig(crawl_depth=3)

# NEW
config = GraphRAGConfiguration(max_depth=3)
```

### Issue: Missing Features

**Problem:**
"The old processor had feature X, but I can't find it in the unified processor."

**Solution:**
All features are preserved! Check the feature mapping:
- `enable_graphrag` → `enable_full_pipeline`
- `crawl_depth` → `max_depth`
- `quality_threshold` → `content_quality_threshold`
- `archive_services=['ia']` → `archive_services=["internet_archive"]`

If still missing, check the processing mode - some features require `quality` or `comprehensive` mode.

---

## Migration Checklist

### Pre-Migration

- [ ] Identify all usages of deprecated GraphRAG processors in your code
- [ ] Review this migration guide
- [ ] Test existing code to understand current behavior
- [ ] Plan testing strategy for migrated code

### During Migration

- [ ] Update imports to use `UnifiedGraphRAGProcessor`
- [ ] Create `GraphRAGConfiguration` objects
- [ ] Add `await` to all processor calls
- [ ] Update configuration parameter names
- [ ] Update result handling (use `GraphRAGResult` type)
- [ ] Test migrated code thoroughly

### Post-Migration

- [ ] Remove any deprecation warning suppressions
- [ ] Update documentation
- [ ] Update tests to use new processor
- [ ] Remove old processor imports
- [ ] Verify no functionality is lost

### Validation

- [ ] All tests pass
- [ ] No deprecation warnings in logs
- [ ] Performance is equal or better
- [ ] All features working as expected

---

## Getting Help

### Resources

- **Documentation:** `docs/PHASE_3_4_GRAPHRAG_CONSOLIDATION_PLAN.md`
- **Architecture:** `docs/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN.md`
- **Tests:** `tests/unit/processors/test_graphrag_consolidation.py`
- **Examples:** `archive/examples_from_ipfs_datasets_py_dir/graphrag_example.py`

### Common Questions

**Q: Will my old code break immediately?**
A: No! Deprecated classes still work with warnings. You have ~6 months until v2.0 removes them.

**Q: What if I can't migrate before v2.0?**
A: Pin your version to `ipfs_datasets_py<2.0` in requirements.txt, but plan to migrate soon.

**Q: Are there any breaking changes?**
A: Only in v2.0 when deprecated classes are removed. v1.x maintains full backward compatibility.

**Q: What if I need features from multiple old processors?**
A: Use `UnifiedGraphRAGProcessor` with appropriate configuration - it combines ALL features.

**Q: Can I use old and new processors together?**
A: Yes, during the migration period. But aim to consolidate to unified processor for consistency.

---

## Examples

### Complete Migration Example

**Before (3 separate processors):**
```python
from ipfs_datasets_py.processors.graphrag_processor import GraphRAGProcessor
from ipfs_datasets_py.processors.website_graphrag_processor import WebsiteGraphRAGProcessor
from ipfs_datasets_py.processors.advanced_graphrag_website_processor import AdvancedGraphRAGWebsiteProcessor

# Different processors for different tasks
basic_processor = GraphRAGProcessor()
web_processor = WebsiteGraphRAGProcessor()
advanced_processor = AdvancedGraphRAGWebsiteProcessor()

# Manual orchestration
basic_result = basic_processor.query("What is AI?")
web_result = await web_processor.process_website("https://example.com")
advanced_result = await advanced_processor.process_website_advanced("https://example.com")
```

**After (single unified processor):**
```python
from ipfs_datasets_py.processors.graphrag.unified_graphrag import (
    UnifiedGraphRAGProcessor,
    GraphRAGConfiguration
)

# Single processor with different modes
async def process_all():
    # Fast mode for quick queries
    fast_processor = UnifiedGraphRAGProcessor(
        config=GraphRAGConfiguration(processing_mode="fast")
    )
    basic_result = await fast_processor.process_query("What is AI?")
    
    # Balanced mode for websites
    balanced_processor = UnifiedGraphRAGProcessor(
        config=GraphRAGConfiguration(
            processing_mode="balanced",
            enable_web_archiving=True
        )
    )
    web_result = await balanced_processor.process_website("https://example.com")
    
    # Quality mode for advanced processing
    advanced_processor = UnifiedGraphRAGProcessor(
        config=GraphRAGConfiguration(
            processing_mode="quality",
            enable_multi_pass_extraction=True,
            enable_adaptive_optimization=True
        )
    )
    advanced_result = await advanced_processor.process_website("https://example.com")
    
    return basic_result, web_result, advanced_result

results = anyio.run(process_all)
```

---

## Summary

### What You Need to Do

1. **Update imports** - Use `UnifiedGraphRAGProcessor` from `processors.graphrag.unified_graphrag`
2. **Create configuration** - Use `GraphRAGConfiguration` object
3. **Add async** - All methods are now async, use `await`
4. **Update parameter names** - Some parameters renamed for consistency
5. **Test thoroughly** - Verify all functionality works as expected

### What You Get

- ✅ **Single unified API** - No more choosing between processors
- ✅ **All features preserved** - Nothing is lost
- ✅ **Better performance** - Async-first architecture
- ✅ **IPLD integration** - Built-in decentralized storage
- ✅ **Consistent configuration** - One config object for everything
- ✅ **Improved maintainability** - 62-67% less duplicate code

### Timeline

- **Now - 6 months:** Migrate at your pace, old code still works
- **v1.9 (~Jul 2026):** Final warnings, prepare for removal
- **v2.0 (~Aug 2026):** Deprecated classes removed

---

**Ready to migrate?** Start with the quick examples above, then follow the checklist!

**Questions?** Check the troubleshooting section or review the consolidation plan.

**Found a bug?** Report it with details on what you were trying to migrate.

---

**Last Updated:** 2026-02-15  
**Next Review:** After Phase 4 implementation complete
