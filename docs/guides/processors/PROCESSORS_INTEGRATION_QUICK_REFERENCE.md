# Processors & Data Transformation Integration: Quick Reference

**Last Updated:** 2026-02-15  
**Full Plan:** [PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN.md](./PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN.md)

---

## 🎯 Quick Summary

**Goal:** Consolidate processors/ and deprecate data_transformation/ to create a unified processing architecture.

**Timeline:** 4 weeks  
**Status:** Planning Complete, Ready for Implementation  

---

## 📁 Directory Structure Changes

### Before
```
ipfs_datasets_py/
├── processors/               # High-level processors
│   ├── core/                # Protocol system
│   ├── adapters/            # 8 adapters
│   ├── file_converter/
│   ├── graphrag/            # 4+ implementations (duplicates)
│   └── [22+ specialized processors]
└── data_transformation/      # Low-level utilities
    ├── ipld/                # IPLD storage (4,384 lines)
    ├── multimedia/          # ⚠️ Moving to processors
    ├── car_conversion.py
    ├── jsonl_to_parquet.py
    └── dataset_serialization.py
```

### After
```
ipfs_datasets_py/
├── processors/               # PRIMARY USER API
│   ├── core/                # Protocol system
│   ├── adapters/            # 9+ adapters (added DataTransformationAdapter)
│   ├── multimedia/          # ✅ MOVED from data_transformation
│   │   ├── ffmpeg_wrapper.py
│   │   ├── ytdlp_wrapper.py
│   │   ├── media_processor.py
│   │   └── converters/      # Simplified conversion systems
│   │       ├── omni_converter/  # From omni_converter_mk2
│   │       └── mime_converter/  # From convert_to_txt_based_on_mime_type
│   ├── file_converter/
│   ├── graphrag/            # ✅ UNIFIED single implementation
│   │   └── unified_graphrag.py
│   └── [specialized processors]
└── data_transformation/      # LOW-LEVEL UTILITIES (simplified)
    ├── ipld/                # ✅ KEEP - Core IPLD storage
    ├── serialization/       # ✅ REORGANIZED
    │   ├── car_conversion.py
    │   ├── jsonl_to_parquet.py
    │   ├── dataset_serialization.py
    │   └── ipfs_parquet_to_car.py
    ├── ipfs_formats/        # ✅ KEEP
    ├── unixfs.py            # ✅ KEEP
    ├── ucan.py              # ✅ KEEP
    └── multimedia/          # ⚠️ DEPRECATED (shim only)
        └── __init__.py      # Deprecation warning + re-exports
```

---

## 🔄 Import Changes

### Multimedia (DEPRECATED → NEW)

**❌ Old (Deprecated):**
```python
from ipfs_datasets_py.data_transformation.multimedia import FFmpegWrapper
from ipfs_datasets_py.data_transformation.multimedia import YtDlpWrapper
from ipfs_datasets_py.data_transformation.multimedia import MediaProcessor
```

**✅ New:**
```python
from ipfs_datasets_py.processors.multimedia import FFmpegWrapper
from ipfs_datasets_py.processors.multimedia import YtDlpWrapper
from ipfs_datasets_py.processors.multimedia import MediaProcessor
```

### Serialization (REORGANIZED)

**❌ Old:**
```python
from ipfs_datasets_py.data_transformation.car_conversion import DataInterchangeUtils
from ipfs_datasets_py.data_transformation.jsonl_to_parquet import convert_jsonl_to_parquet
from ipfs_datasets_py.data_transformation.dataset_serialization import DatasetSerializer
```

**✅ New:**
```python
from ipfs_datasets_py.data_transformation.serialization.car_conversion import DataInterchangeUtils
from ipfs_datasets_py.data_transformation.serialization.jsonl_to_parquet import (
    convert_jsonl_to_parquet,
)
from ipfs_datasets_py.data_transformation.serialization.dataset_serialization import (
    DatasetSerializer,
)
```

**Note:** Old imports will work with deprecation warnings until v2.0.0

### IPLD (NO CHANGE)

**✅ Keep using:**
```python
from ipfs_datasets_py.data_transformation.ipld import IPLDStorage
from ipfs_datasets_py.data_transformation.ipld import IPLDVectorStore
from ipfs_datasets_py.data_transformation.ipld import IPLDKnowledgeGraph
```

### GraphRAG (UNIFIED)

**❌ Old (Multiple implementations):**
```python
from ipfs_datasets_py.processors.graphrag_processor import GraphRAGProcessor
from ipfs_datasets_py.processors.website_graphrag_processor import WebsiteGraphRAGProcessor
from ipfs_datasets_py.processors.advanced_graphrag_website_processor import (
    AdvancedGraphRAGWebsiteProcessor,
)
```

**✅ New (Unified):**
```python
from ipfs_datasets_py.processors.graphrag import UnifiedGraphRAG
```

---

## ⏱️ Deprecation Timeline

| Version | Date (Estimated) | Status | Description |
|---------|------------------|--------|-------------|
| **v1.9** | Q2 2026 | Planning | Add all deprecation warnings |
| **v1.9.x** | Q2-Q3 2026 | Active | 6-month deprecation period |
| **v2.0** | Q4 2026 | Future | Remove deprecated imports |

**Current Status (v1.x):** Multimedia deprecation warnings active, others being added

---

## 🚀 Implementation Phases

### Phase 1: Complete Multimedia Migration (Week 1) 🔄
- [ ] Audit current multimedia state
- [ ] Complete core file migration (6 files)
- [ ] Simplify omni_converter_mk2 → omni_converter
- [ ] Simplify convert_to_txt → mime_converter
- [ ] Write migration guide

**Estimated:** 33 hours

### Phase 2: Organize Serialization (Week 1-2) ⏳
- [ ] Create serialization/ package
- [ ] Move 4 serialization files
- [ ] Update imports across codebase (5+ files)
- [ ] Add deprecation warnings

**Estimated:** 7 hours

### Phase 3: Enhance Adapters (Week 2) ⏳
- [ ] Create DataTransformationAdapter
- [ ] Update IPFSAdapter to use IPLDStorage
- [ ] Update MultimediaAdapter for converters
- [ ] Update BatchAdapter for serialization
- [ ] Write integration tests (10+)

**Estimated:** 22 hours

### Phase 4: Consolidate GraphRAG (Week 2-3) ⏳
- [ ] Audit 7 GraphRAG implementations
- [ ] Design unified architecture
- [ ] Implement UnifiedGraphRAG
- [ ] Deprecate old implementations

**Estimated:** 32 hours

### Phase 5: Documentation (Week 3-4) ⏳
- [ ] Create architecture docs (4)
- [ ] Create migration guides (4)
- [ ] Update existing docs (20+)
- [ ] Create deprecation timeline

**Estimated:** 28 hours

### Phase 6: Testing & Validation (Week 4) ⏳
- [ ] Run full test suite (236+ tests)
- [ ] Create integration tests (20+)
- [ ] Performance benchmarking
- [ ] Backward compatibility validation
- [ ] Documentation review

**Estimated:** 32 hours

---

## 📊 Key Metrics

### Code Volume
- **Processors:** ~82KB production code, 129+ tests
- **Data Transformation IPLD:** ~4,384 lines
- **Data Transformation Multimedia:** ~5,894 lines (moving)
- **Data Transformation Serialization:** ~1,500 lines (reorganizing)

### Test Coverage
- **Current:** 182+ tests across all modules
- **Target:** 236+ tests (54+ new tests)
- **Coverage Goal:** >90%

### Performance
- **Routing:** 73K ops/sec (target: maintain)
- **Cache:** 861K ops/sec (target: maintain)
- **Regressions:** <5% acceptable

---

## 🛠️ Developer Quick Actions

### Check Current Status
```bash
# Check multimedia migration status
ls -la ipfs_datasets_py/processors/multimedia/

# Check for deprecation warnings
python -c "from ipfs_datasets_py.data_transformation.multimedia import FFmpegWrapper"

# Run relevant tests
pytest tests/integration/processors/test_multimedia_adapter.py
pytest tests/unit/processors/multimedia/
```

### Update Your Code
```bash
# Find old imports in your code
grep -r "data_transformation.multimedia" your_project/

# Replace with new imports
sed -i 's/data_transformation\.multimedia/processors.multimedia/g' your_file.py
```

### Test Your Changes
```bash
# Run tests with deprecation warnings visible
pytest -W default::DeprecationWarning tests/

# Check for import issues
python -m mypy your_file.py

# Performance check
pytest tests/performance/ -v
```

---

## 📝 Migration Checklist

### For Users of Multimedia
- [ ] Update imports: `data_transformation.multimedia` → `processors.multimedia`
- [ ] Test with deprecation warnings enabled
- [ ] Update documentation/examples
- [ ] Check for breaking changes (should be none)
- [ ] Plan upgrade before v2.0.0 (6 months)

### For Users of Serialization
- [ ] Update imports: Add `.serialization` to path
- [ ] Or wait for deprecation warnings to appear
- [ ] Update before v2.0.0

### For Users of GraphRAG
- [ ] Review new UnifiedGraphRAG API
- [ ] Plan migration from specific implementations
- [ ] Test with your use cases
- [ ] Report any missing features

### For Core Developers
- [ ] Don't import from `data_transformation.multimedia`
- [ ] Use `processors.multimedia` for new code
- [ ] Use `data_transformation.ipld` for storage
- [ ] Use `data_transformation.serialization` for conversion
- [ ] Follow ProcessorProtocol for new processors

---

## 🆘 Common Issues & Solutions

### Issue: Import Warning
```
DeprecationWarning: data_transformation.multimedia is deprecated
```
**Solution:** Update import to `processors.multimedia`

### Issue: Module Not Found
```
ModuleNotFoundError: No module named 'ipfs_datasets_py.processors.multimedia'
```
**Solution:** Migration may not be complete yet, check status

### Issue: Test Failures After Update
**Solution:**
1. Check import paths
2. Update test imports
3. Clear `__pycache__`
4. Reinstall package: `pip install -e .`

### Issue: Functionality Missing
**Solution:** Check if feature is in simplified converters, report if missing

---

## 📚 Documentation

### Main Documents
- **[Integration Plan](./PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN.md)** - Comprehensive plan (24KB)
- **[Task Breakdown](./PROCESSORS_INTEGRATION_TASKS.md)** - Detailed tasks (26KB)
- **[This Document](./PROCESSORS_INTEGRATION_QUICK_REFERENCE.md)** - Quick reference

### Migration Guides (To Be Created)
- `MULTIMEDIA_MIGRATION_GUIDE.md` - Multimedia users
- `SERIALIZATION_MIGRATION_GUIDE.md` - Serialization users
- `GRAPHRAG_MIGRATION_GUIDE.md` - GraphRAG users
- `MIGRATION_GUIDE_V2.md` - Overall v1 → v2

### Architecture Docs (To Be Created)
- `PROCESSORS_DATA_TRANSFORMATION_ARCHITECTURE.md` - Overall architecture
- `MULTIMEDIA_ARCHITECTURE.md` - Multimedia processing
- `SERIALIZATION_ARCHITECTURE.md` - Serialization utilities
- `GRAPHRAG_ARCHITECTURE.md` - Unified GraphRAG

---

## 🎯 Success Criteria

### Functional
- ✅ All 182+ existing tests pass
- ✅ 54+ new tests added and passing
- ✅ 100% backward compatibility maintained
- ✅ No performance regression (<5%)
- ✅ All deprecated imports have warnings

### Organizational
- ✅ Clear separation: processors/ (user API) vs data_transformation/ (utilities)
- ✅ Multimedia fully migrated
- ✅ Serialization organized
- ✅ GraphRAG unified
- ✅ Comprehensive documentation

### User Impact
- ✅ Clear migration path
- ✅ 6-month deprecation period
- ✅ No breaking changes before v2.0
- ✅ Improved discoverability
- ✅ Better organization

---

## 📞 Contact & Support

- **GitHub Issues:** Report problems or ask questions
- **Pull Requests:** Contribute improvements
- **Documentation:** Check docs/ for detailed information
- **Deprecation Warnings:** Follow instructions in warnings

---

**Status:** Planning Complete ✅  
**Next Step:** Start Phase 1, Task 1.1 (Audit Current Multimedia State)  
**Questions?** See [PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN.md](./PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN.md)
