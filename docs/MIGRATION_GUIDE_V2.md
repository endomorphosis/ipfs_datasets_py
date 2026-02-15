# Complete Migration Guide to v2.0

**Created:** 2026-02-15  
**Target Version:** v2.0  
**Migration Timeline:** 6 months (February 2026 - August 2026)  
**Status:** ACTIVE

---

## Table of Contents

1. [Overview](#overview)
2. [Migration Timeline](#migration-timeline)
3. [Component Migrations](#component-migrations)
4. [Step-by-Step Migration Guide](#step-by-step-migration-guide)
5. [Automated Migration Tools](#automated-migration-tools)
6. [Testing Your Migration](#testing-your-migration)
7. [Common Issues](#common-issues)
8. [FAQs](#faqs)

---

## Overview

This comprehensive guide helps you migrate from **v1.x to v2.0** of IPFS Datasets Python. The consolidation effort unified multiple implementations, reorganized modules, and established a clear three-tier architecture.

### What Changed?

**Three Major Consolidations:**

1. **Multimedia Migration** - `data_transformation/multimedia/` → `processors/multimedia/`
2. **Serialization Organization** - Root files → `data_transformation/serialization/`
3. **GraphRAG Unification** - 7 implementations → `UnifiedGraphRAGProcessor`

### Key Benefits

- ✅ **Cleaner Architecture:** Three-tier separation (User APIs, Transformation, IPFS Backend)
- ✅ **Reduced Duplication:** ~170KB of duplicate code eliminated
- ✅ **Better Performance:** Optimized unified implementations
- ✅ **Easier Maintenance:** Single source of truth for each feature
- ✅ **Protocol-Based Design:** Easy to extend with new processors

### Migration Timeline

| Version | Date | Status | Action Required |
|---------|------|--------|-----------------|
| v1.0 | Feb 2026 | ⚠️ Deprecation warnings | Acknowledge warnings |
| v1.5 | May 2026 | 🔧 Migration tools | Run migration checker |
| v1.9 | Jul 2026 | ⏰ Final warning | Complete migration |
| v2.0 | Aug 2026 | 🚫 Breaking changes | Must be migrated |

**You have 6 months to migrate!**

---

## Component Migrations

### 1. Multimedia Components

#### What Changed?

Multimedia processors moved from `data_transformation/multimedia/` to `processors/multimedia/`.

#### Migration Steps

**Step 1: Update Imports**

```python
# OLD (v1.x - deprecated)
from ipfs_datasets_py.data_transformation.multimedia import (
    FFmpegWrapper,
    YtDlpWrapper,
    MediaProcessor,
    MediaUtils,
    EmailProcessor,
    DiscordWrapper
)

# NEW (v2.0)
from ipfs_datasets_py.processors.multimedia import (
    FFmpegWrapper,
    YtDlpWrapper,
    MediaProcessor,
    MediaUtils,
    EmailProcessor,
    DiscordWrapper
)

# Or use main package exports
from ipfs_datasets_py import FFmpegWrapper, YtDlpWrapper
```

**Step 2: No API Changes**

Good news! The APIs remain identical. Only import paths changed.

```python
# Works exactly the same in v2.0
ffmpeg = FFmpegWrapper()
metadata = ffmpeg.get_metadata(video_path)
frame = ffmpeg.extract_frame(video_path, timestamp="00:01:00")
```

**Step 3: Test Your Code**

```bash
python -m pytest tests/test_my_multimedia_code.py
```

#### Complete Example

**Before (v1.x):**
```python
from ipfs_datasets_py.data_transformation.multimedia import FFmpegWrapper, YtDlpWrapper

# Download video
ytdlp = YtDlpWrapper()
video_path = ytdlp.download("https://youtube.com/watch?v=...")

# Process with FFmpeg
ffmpeg = FFmpegWrapper()
ffmpeg.transcode(video_path, output="output.mp4", codec="h264")
```

**After (v2.0):**
```python
from ipfs_datasets_py.processors.multimedia import FFmpegWrapper, YtDlpWrapper

# Download video (SAME API)
ytdlp = YtDlpWrapper()
video_path = ytdlp.download("https://youtube.com/watch?v=...")

# Process with FFmpeg (SAME API)
ffmpeg = FFmpegWrapper()
ffmpeg.transcode(video_path, output="output.mp4", codec="h264")
```

#### Migration Checklist

- [ ] Find all imports from `data_transformation.multimedia`
- [ ] Replace with `processors.multimedia`
- [ ] Test that functionality works identically
- [ ] Remove any deprecation warning suppressions

**Detailed Guide:** [MULTIMEDIA_MIGRATION_GUIDE.md](./MULTIMEDIA_MIGRATION_GUIDE.md)

---

### 2. Serialization Components

#### What Changed?

Serialization utilities reorganized into `data_transformation/serialization/` subfolder.

#### Migration Steps

**Step 1: Update Imports**

```python
# OLD (v1.x - deprecated)
from ipfs_datasets_py.data_transformation.car_conversion import DataInterchangeUtils
from ipfs_datasets_py.data_transformation.jsonl_to_parquet import jsonl_to_parquet
from ipfs_datasets_py.data_transformation.dataset_serialization import DatasetSerializer
from ipfs_datasets_py.data_transformation.ipfs_parquet_to_car import parquet_to_car

# NEW (v2.0)
from ipfs_datasets_py.data_transformation.serialization.car_conversion import DataInterchangeUtils
from ipfs_datasets_py.data_transformation.serialization.jsonl_to_parquet import jsonl_to_parquet
from ipfs_datasets_py.data_transformation.serialization.dataset_serialization import DatasetSerializer
from ipfs_datasets_py.data_transformation.serialization.ipfs_parquet_to_car import parquet_to_car
```

**Step 2: No API Changes**

APIs remain identical - only import paths changed.

```python
# Works exactly the same in v2.0
utils = DataInterchangeUtils()
car_data = utils.arrow_to_car(arrow_table)
arrow_back = utils.car_to_arrow(car_data)
```

**Step 3: Test Serialization**

```bash
python -m pytest tests/test_serialization.py
```

#### Complete Example

**Before (v1.x):**
```python
from ipfs_datasets_py.data_transformation.car_conversion import DataInterchangeUtils
from ipfs_datasets_py.data_transformation.dataset_serialization import DatasetSerializer

# Convert dataset to CAR format
serializer = DatasetSerializer()
car_cid = serializer.dataset_to_car(dataset, output="output.car")

# Or use interchange utils
utils = DataInterchangeUtils()
arrow_table = utils.dataset_to_arrow(dataset)
car_data = utils.arrow_to_car(arrow_table)
```

**After (v2.0):**
```python
from ipfs_datasets_py.data_transformation.serialization.car_conversion import DataInterchangeUtils
from ipfs_datasets_py.data_transformation.serialization.dataset_serialization import DatasetSerializer

# Convert dataset to CAR format (SAME API)
serializer = DatasetSerializer()
car_cid = serializer.dataset_to_car(dataset, output="output.car")

# Or use interchange utils (SAME API)
utils = DataInterchangeUtils()
arrow_table = utils.dataset_to_arrow(dataset)
car_data = utils.arrow_to_car(arrow_table)
```

#### Migration Checklist

- [ ] Find all imports from `data_transformation.car_conversion`
- [ ] Find all imports from `data_transformation.jsonl_to_parquet`
- [ ] Find all imports from `data_transformation.dataset_serialization`
- [ ] Find all imports from `data_transformation.ipfs_parquet_to_car`
- [ ] Add `.serialization` after `data_transformation`
- [ ] Test that serialization works identically

**Detailed Report:** [PHASE_2_SERIALIZATION_COMPLETE.md](./PHASE_2_SERIALIZATION_COMPLETE.md)

---

### 3. GraphRAG Unification

#### What Changed?

**7 GraphRAG implementations unified into 1:**

| Old Implementation | Lines | Status |
|--------------------|-------|--------|
| GraphRAGProcessor | 264 | ⚠️ Deprecated |
| WebsiteGraphRAGProcessor | 585 | ⚠️ Deprecated |
| AdvancedGraphRAGWebsiteProcessor | 1,628 | ⚠️ Deprecated |
| CompleteGraphRAGSystem | 1,220 | ✅ Merged |
| **UnifiedGraphRAGProcessor** | ~550 | ✅ **USE THIS** |

**Result:** ~170KB duplicate code eliminated, all features preserved.

#### Migration Steps

**Step 1: Update Imports**

```python
# OLD (v1.x - deprecated)
from ipfs_datasets_py.processors.graphrag_processor import GraphRAGProcessor
from ipfs_datasets_py.processors.website_graphrag_processor import WebsiteGraphRAGProcessor
from ipfs_datasets_py.processors.advanced_graphrag_website_processor import AdvancedGraphRAGWebsiteProcessor

# NEW (v2.0)
from ipfs_datasets_py.processors.graphrag.unified_graphrag import (
    UnifiedGraphRAGProcessor,
    GraphRAGConfiguration,
    GraphRAGResult
)

# Or from main package
from ipfs_datasets_py import (
    UnifiedGraphRAGProcessor,
    GraphRAGConfiguration,
    GraphRAGResult
)
```

**Step 2: Update Configuration**

The unified processor uses a configuration object for better organization.

```python
# Create configuration
config = GraphRAGConfiguration(
    processing_mode="balanced",  # fast, balanced, quality, comprehensive
    enable_web_archiving=True,
    archive_services=["internet_archive", "archive_is"],
    enable_multi_pass_extraction=True,
    content_quality_threshold=0.6,
    max_depth=2  # Crawl depth
)

# Initialize processor
processor = UnifiedGraphRAGProcessor(config=config)
```

**Step 3: Update API Calls (Async Required)**

```python
# All operations are now async
result = await processor.process_website("https://example.com")
query_results = await processor.process_query("What is this about?", context=result)
```

**If not in async context:**
```python
import anyio
result = anyio.run(processor.process_website, "https://example.com")
```

#### Complete Example

**Before (v1.x - GraphRAGProcessor):**
```python
from ipfs_datasets_py.processors.graphrag_processor import GraphRAGProcessor

processor = GraphRAGProcessor(
    vector_store=my_vector_store,
    knowledge_graph=my_kg,
    embedding_model="sentence-transformers/all-MiniLM-L6-v2"
)

# Query
results = processor.query("What is machine learning?", top_k=10)
```

**Before (v1.x - WebsiteGraphRAGProcessor):**
```python
from ipfs_datasets_py.processors.website_graphrag_processor import (
    WebsiteGraphRAGProcessor,
    WebsiteProcessingConfig
)

config = WebsiteProcessingConfig(
    archive_services=['ia', 'is'],
    crawl_depth=2,
    enable_graphrag=True
)

processor = WebsiteGraphRAGProcessor(config=config)
system = await processor.process_website("https://example.com")
```

**After (v2.0 - UnifiedGraphRAGProcessor):**
```python
from ipfs_datasets_py import UnifiedGraphRAGProcessor, GraphRAGConfiguration

# Unified configuration
config = GraphRAGConfiguration(
    processing_mode="balanced",
    enable_web_archiving=True,
    archive_services=["internet_archive", "archive_is"],
    max_depth=2,
    enable_comprehensive_search=True
)

# Single processor for all use cases
processor = UnifiedGraphRAGProcessor(config=config)

# Query (async)
query_result = await processor.process_query("What is machine learning?", top_k=10)

# Process website (async)
website_result = await processor.process_website("https://example.com")
```

#### Feature Mapping

| Old Feature | Old Processor | New Location |
|-------------|---------------|--------------|
| Basic queries | GraphRAGProcessor | UnifiedGraphRAGProcessor |
| Website crawling | WebsiteGraphRAGProcessor | UnifiedGraphRAGProcessor (enable_web_archiving=True) |
| Multi-pass extraction | AdvancedGraphRAGWebsiteProcessor | UnifiedGraphRAGProcessor (enable_multi_pass_extraction=True) |
| Quality assessment | AdvancedGraphRAGWebsiteProcessor | UnifiedGraphRAGProcessor (content_quality_threshold) |
| Web archiving | WebsiteGraphRAGProcessor | UnifiedGraphRAGProcessor (archive_services) |

#### Migration Checklist

- [ ] Find all uses of `GraphRAGProcessor`
- [ ] Find all uses of `WebsiteGraphRAGProcessor`
- [ ] Find all uses of `AdvancedGraphRAGWebsiteProcessor`
- [ ] Replace with `UnifiedGraphRAGProcessor`
- [ ] Create `GraphRAGConfiguration` objects
- [ ] Add `await` to all processor calls
- [ ] Map old features to new configuration options
- [ ] Test thoroughly

**Detailed Guide:** [GRAPHRAG_CONSOLIDATION_GUIDE.md](./GRAPHRAG_CONSOLIDATION_GUIDE.md)

---

## Step-by-Step Migration Guide

### Phase 1: Assessment (Week 1)

**Goal:** Understand what needs to change in your codebase.

#### Step 1.1: Inventory Your Imports

Search your codebase for deprecated imports:

```bash
# Find multimedia imports
grep -r "from.*data_transformation.multimedia import" . --include="*.py"

# Find serialization imports
grep -r "from.*data_transformation.car_conversion import" . --include="*.py"
grep -r "from.*data_transformation.jsonl_to_parquet import" . --include="*.py"
grep -r "from.*data_transformation.dataset_serialization import" . --include="*.py"

# Find GraphRAG imports
grep -r "from.*processors.graphrag_processor import" . --include="*.py"
grep -r "from.*processors.website_graphrag_processor import" . --include="*.py"
grep -r "from.*processors.advanced_graphrag_website_processor import" . --include="*.py"
```

#### Step 1.2: Create Migration Plan

Document what you found:

```markdown
# My Migration Plan

## Multimedia (X files)
- [ ] file1.py (line 10: FFmpegWrapper)
- [ ] file2.py (line 25: YtDlpWrapper)

## Serialization (Y files)
- [ ] file3.py (line 5: DataInterchangeUtils)
- [ ] file4.py (line 15: DatasetSerializer)

## GraphRAG (Z files)
- [ ] file5.py (line 30: GraphRAGProcessor)
- [ ] file6.py (line 40: WebsiteGraphRAGProcessor)
```

#### Step 1.3: Pin Dependencies

While migrating, pin to v1.x to avoid breaking changes:

```python
# requirements.txt
ipfs_datasets_py>=1.0,<2.0
```

### Phase 2: Development Environment Migration (Week 2)

**Goal:** Update and test in development first.

#### Step 2.1: Update Multimedia Imports

```bash
# Use sed for bulk replacement (BACKUP FIRST!)
# Multimedia
find . -name "*.py" -type f -exec sed -i 's/from ipfs_datasets_py.data_transformation.multimedia/from ipfs_datasets_py.processors.multimedia/g' {} \;
```

Or manually update each file.

#### Step 2.2: Update Serialization Imports

```bash
# Serialization (add .serialization after data_transformation)
# This is more complex - recommend manual update or custom script
```

Manual pattern:
```python
# Find this pattern
from ipfs_datasets_py.data_transformation.car_conversion import X

# Replace with
from ipfs_datasets_py.data_transformation.serialization.car_conversion import X
```

#### Step 2.3: Update GraphRAG Implementations

This requires more careful refactoring:

1. **Review each usage** of deprecated GraphRAG processors
2. **Map features** to unified configuration options
3. **Update to async** if needed
4. **Test thoroughly**

Example refactoring script:

```python
# Before
processor = GraphRAGProcessor(vector_store=vs, knowledge_graph=kg)
result = processor.query("search query")

# After
from ipfs_datasets_py import UnifiedGraphRAGProcessor, GraphRAGConfiguration

config = GraphRAGConfiguration(processing_mode="fast")
processor = UnifiedGraphRAGProcessor(config=config, vector_store=vs, knowledge_graph=kg)
result = await processor.process_query("search query")
# If not in async context:
# import anyio
# result = anyio.run(processor.process_query, "search query")
```

#### Step 2.4: Run Tests

```bash
# Test each component as you migrate
python -m pytest tests/test_multimedia.py
python -m pytest tests/test_serialization.py
python -m pytest tests/test_graphrag.py

# Run full suite
python -m pytest
```

### Phase 3: Staging/Testing Environment (Week 3)

**Goal:** Validate in staging before production.

#### Step 3.1: Deploy to Staging

```bash
# Update dependencies to allow v1.9 for testing
pip install 'ipfs_datasets_py>=1.9,<2.0'
```

#### Step 3.2: Monitor Deprecation Warnings

```python
import warnings
import logging

# Log deprecation warnings
logging.captureWarnings(True)

# Or check for any deprecation warnings
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always", DeprecationWarning)
    
    # Your code here
    from ipfs_datasets_py.data_transformation.multimedia import FFmpegWrapper
    
    if w:
        for warning in w:
            print(f"WARNING: {warning.message}")
```

#### Step 3.3: Performance Testing

Compare performance between old and new:

```python
import time

# Old implementation
start = time.time()
# ... old code ...
old_time = time.time() - start

# New implementation
start = time.time()
# ... new code ...
new_time = time.time() - start

print(f"Old: {old_time}s, New: {new_time}s, Speedup: {old_time/new_time:.2f}x")
```

### Phase 4: Production Deployment (Week 4)

**Goal:** Deploy to production safely.

#### Step 4.1: Final Validation

```bash
# Run full test suite with v1.9
python -m pytest --verbose

# Check for any deprecation warnings
python -W error::DeprecationWarning -m pytest
```

#### Step 4.2: Deploy

```bash
# Update to allow v2.0
# requirements.txt
ipfs_datasets_py>=2.0

# Deploy
pip install -U ipfs_datasets_py
```

#### Step 4.3: Monitor

- Check application logs for errors
- Monitor performance metrics
- Verify all features work as expected

---

## Automated Migration Tools

### Migration Checker (Available in v1.5+)

**Scan your codebase for deprecated imports:**

```bash
python -m ipfs_datasets_py.tools.migration_checker /path/to/your/code
```

**Output Example:**
```
🔍 Scanning for deprecated imports...

Found 15 deprecated imports:

Multimedia (5):
  - src/video_processor.py:10 - FFmpegWrapper
  - src/downloader.py:15 - YtDlpWrapper
  ...

Serialization (3):
  - src/storage.py:5 - DataInterchangeUtils
  ...

GraphRAG (7):
  - src/graphrag_pipeline.py:20 - GraphRAGProcessor
  ...

📝 Run with --verbose for detailed migration instructions
```

### Migration Script Generator (Available in v1.5+)

**Auto-generate migration scripts:**

```bash
python -m ipfs_datasets_py.tools.migration_generator /path/to/your/code
```

**Generates:**
- `migrate_multimedia.sh` - Sed commands for multimedia imports
- `migrate_serialization.py` - Python script for serialization updates
- `migrate_graphrag.md` - Manual migration guide for GraphRAG

### Compatibility Tester (Available in v1.5+)

**Test code with both old and new imports:**

```bash
python -m ipfs_datasets_py.tools.compatibility_tester /path/to/your/code
```

**Output:**
```
✅ All tests pass with v1.x imports
✅ All tests pass with v2.0 imports
✅ No functional differences detected

Ready for v2.0 upgrade!
```

---

## Testing Your Migration

### Unit Tests

Test each migrated component:

```python
import pytest
from ipfs_datasets_py.processors.multimedia import FFmpegWrapper

def test_multimedia_migration():
    """Test multimedia imports work after migration."""
    ffmpeg = FFmpegWrapper()
    assert ffmpeg is not None
    # Add more specific tests

def test_serialization_migration():
    """Test serialization imports work after migration."""
    from ipfs_datasets_py.data_transformation.serialization.car_conversion import DataInterchangeUtils
    utils = DataInterchangeUtils()
    assert utils is not None

def test_graphrag_migration():
    """Test GraphRAG unified processor works."""
    from ipfs_datasets_py import UnifiedGraphRAGProcessor, GraphRAGConfiguration
    config = GraphRAGConfiguration(processing_mode="fast")
    processor = UnifiedGraphRAGProcessor(config=config)
    assert processor is not None
```

### Integration Tests

Test that everything works together:

```python
async def test_full_pipeline():
    """Test complete pipeline with migrated components."""
    from ipfs_datasets_py.processors.multimedia import YtDlpWrapper
    from ipfs_datasets_py import UnifiedGraphRAGProcessor, GraphRAGConfiguration
    from ipfs_datasets_py.data_transformation.serialization.dataset_serialization import DatasetSerializer
    
    # Download video
    ytdlp = YtDlpWrapper()
    video = ytdlp.download("https://example.com/video")
    
    # Process with GraphRAG
    config = GraphRAGConfiguration(processing_mode="fast")
    processor = UnifiedGraphRAGProcessor(config=config)
    result = await processor.process_website("https://example.com")
    
    # Serialize result
    serializer = DatasetSerializer()
    cid = serializer.result_to_car(result, "output.car")
    
    assert cid is not None
```

### Backward Compatibility Tests

Ensure old code still works (in v1.x):

```python
import warnings

def test_backward_compatibility():
    """Test that old imports still work with warnings."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        
        # Old import
        from ipfs_datasets_py.data_transformation.multimedia import FFmpegWrapper
        
        # Should have deprecation warning
        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)
        assert "deprecated" in str(w[0].message).lower()
        
        # But should still work
        ffmpeg = FFmpegWrapper()
        assert ffmpeg is not None
```

---

## Common Issues

### Issue 1: ImportError After Upgrade

**Symptom:**
```python
ImportError: cannot import name 'FFmpegWrapper' from 'ipfs_datasets_py.data_transformation.multimedia'
```

**Cause:** Using deprecated import in v2.0

**Solution:**
```python
# Update import
from ipfs_datasets_py.processors.multimedia import FFmpegWrapper
```

### Issue 2: Async Required for GraphRAG

**Symptom:**
```python
TypeError: object GraphRAGResult can't be used in 'await' expression
```

**Cause:** Not using `await` with async methods

**Solution:**
```python
# Add await
result = await processor.process_website(url)

# Or use anyio.run if not in async context
import anyio
result = anyio.run(processor.process_website, url)
```

### Issue 3: Configuration Mismatch

**Symptom:**
```python
TypeError: __init__() got an unexpected keyword argument 'crawl_depth'
```

**Cause:** Old parameter names used with unified processor

**Solution:**
```python
# OLD parameter names
config = WebsiteProcessingConfig(crawl_depth=3)

# NEW parameter names
config = GraphRAGConfiguration(max_depth=3)
```

See [GRAPHRAG_CONSOLIDATION_GUIDE.md](./GRAPHRAG_CONSOLIDATION_GUIDE.md) for complete parameter mapping.

### Issue 4: Missing Deprecation Warnings

**Symptom:** No warnings shown despite using deprecated imports

**Cause:** Warnings filtered or not enabled

**Solution:**
```python
import warnings
warnings.simplefilter('always', DeprecationWarning)
```

### Issue 5: Performance Regression

**Symptom:** New implementation slower than old

**Cause:** Typically configuration or usage pattern issue

**Solution:**
- Review configuration (e.g., `processing_mode="fast"` for better performance)
- Check for unnecessary async overhead
- Report issue if genuine regression

---

## FAQs

### Q: How long do I have to migrate?

**A:** 6 months from February 2026 to August 2026. Deprecated imports will be removed in v2.0.

### Q: Can I stay on v1.x forever?

**A:** Not recommended. Pin to v1.x temporarily:
```python
ipfs_datasets_py>=1.0,<2.0
```

But you'll miss bug fixes and new features in v2.0+.

### Q: Will my data be affected?

**A:** No. Only Python APIs changed. Data formats (IPLD, CAR, Parquet) remain 100% compatible.

### Q: What if I find a bug in the new implementation?

**A:** Report immediately at https://github.com/endomorphosis/ipfs_datasets_py/issues with label "migration".

### Q: Are there any performance improvements?

**A:** Yes! Unified implementations are more efficient:
- Faster imports (no shim overhead)
- Better memory usage (no duplicate code)
- Optimized async operations

### Q: Can I mix old and new imports during migration?

**A:** Yes, in v1.x. But aim for consistency - use all new imports.

### Q: What about third-party packages that use old APIs?

**A:** Contact package maintainers. Most should update before v2.0.

### Q: Will automated migration tools handle everything?

**A:** They help with most imports, but GraphRAG migration may need manual review due to API changes (async, configuration).

### Q: What happens if I don't migrate before v2.0?

**A:** Your code will break with `ImportError`. Must migrate or pin to v1.x.

### Q: Are there breaking changes besides deprecation removals?

**A:** No. The ONLY breaking changes are removed deprecated components.

---

## Quick Reference

### Import Cheat Sheet

```python
# ========================================
# MULTIMEDIA
# ========================================
# OLD
from ipfs_datasets_py.data_transformation.multimedia import FFmpegWrapper
# NEW
from ipfs_datasets_py.processors.multimedia import FFmpegWrapper

# ========================================
# SERIALIZATION
# ========================================
# OLD
from ipfs_datasets_py.data_transformation.car_conversion import DataInterchangeUtils
# NEW
from ipfs_datasets_py.data_transformation.serialization.car_conversion import DataInterchangeUtils

# ========================================
# GRAPHRAG
# ========================================
# OLD
from ipfs_datasets_py.processors.graphrag_processor import GraphRAGProcessor
# NEW
from ipfs_datasets_py import UnifiedGraphRAGProcessor, GraphRAGConfiguration
```

### Configuration Mapping

```python
# GraphRAGProcessor → UnifiedGraphRAGProcessor
# OLD
processor = GraphRAGProcessor(vector_store=vs)
# NEW
config = GraphRAGConfiguration(processing_mode="fast")
processor = UnifiedGraphRAGProcessor(config=config)

# WebsiteGraphRAGProcessor → UnifiedGraphRAGProcessor
# OLD
config = WebsiteProcessingConfig(crawl_depth=2)
processor = WebsiteGraphRAGProcessor(config=config)
# NEW
config = GraphRAGConfiguration(max_depth=2, enable_web_archiving=True)
processor = UnifiedGraphRAGProcessor(config=config)
```

---

## Additional Resources

### Documentation

- [PROCESSORS_DATA_TRANSFORMATION_ARCHITECTURE.md](./PROCESSORS_DATA_TRANSFORMATION_ARCHITECTURE.md) - Complete architecture
- [DEPRECATION_TIMELINE.md](./DEPRECATION_TIMELINE.md) - Detailed timeline
- [GRAPHRAG_CONSOLIDATION_GUIDE.md](./GRAPHRAG_CONSOLIDATION_GUIDE.md) - GraphRAG specifics
- [MULTIMEDIA_MIGRATION_GUIDE.md](./MULTIMEDIA_MIGRATION_GUIDE.md) - Multimedia specifics

### Support

- GitHub Issues: https://github.com/endomorphosis/ipfs_datasets_py/issues
- Discussions: https://github.com/endomorphosis/ipfs_datasets_py/discussions
- Documentation: https://github.com/endomorphosis/ipfs_datasets_py/tree/main/docs

### Migration Tools

```bash
# Available in v1.5+
python -m ipfs_datasets_py.tools.migration_checker /path/to/code
python -m ipfs_datasets_py.tools.migration_generator /path/to/code
python -m ipfs_datasets_py.tools.compatibility_tester /path/to/code
```

---

## Summary

**Migration Path:**

1. ✅ **Acknowledge** deprecation warnings (v1.0-v1.4)
2. 📋 **Inventory** your deprecated imports
3. 🔧 **Update** imports following this guide
4. ✅ **Test** thoroughly in development
5. 🚀 **Deploy** to staging for validation
6. 📊 **Monitor** performance and errors
7. ✨ **Upgrade** to v2.0 when ready

**Key Dates:**

- **Now (v1.0):** Start planning
- **May 2026 (v1.5):** Use migration tools
- **July 2026 (v1.9):** Final testing
- **August 2026 (v2.0):** Complete migration

**You have 6 months. Start today!** 🚀

---

**Last Updated:** 2026-02-15  
**Status:** Complete  
**Version:** 1.0
