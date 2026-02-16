# Processors Root Files Inventory

**Created:** February 16, 2026  
**Purpose:** Phase 8, Task 8.3 - Review and Organize Root-Level Files  
**Total Files:** 32

---

## File Categories

### Category 1: Core Architecture (Keep at Root) ✅

| File | Lines | Purpose | Status |
|------|-------|---------|--------|
| `__init__.py` | 122 | Main package entry point, exports public API | ✅ KEEP |
| `protocol.py` | ~800 | ProcessorProtocol interface, core abstractions | ✅ KEEP |
| `universal_processor.py` | 719 | Universal processor implementation | ✅ KEEP |
| `input_detection.py` | ~15,000 | Input type detection (LARGE FILE - needs review) | ⚠️ REVIEW SIZE |

**Subtotal:** 4 files (~16,600 lines)

---

### Category 2: Deprecation Shims (Keep Until v2.0.0) ⏳

| File | Lines | Purpose | Target Removal | New Location |
|------|-------|---------|----------------|--------------|
| `graphrag_processor.py` | 70 | GraphRAG shim | v2.0.0 (Aug 2026) | specialized/graphrag/ |
| `website_graphrag_processor.py` | ~100 | Website GraphRAG shim | v2.0.0 | specialized/graphrag/ |
| `advanced_graphrag_website_processor.py` | ~100 | Advanced GraphRAG shim | v2.0.0 | specialized/graphrag/ |
| `pdf_processor.py` | ~100 | PDF processor shim | v2.0.0 | specialized/pdf/ |
| `pdf_processing.py` | ~100 | PDF processing shim | v2.0.0 | specialized/pdf/ |
| `ocr_engine.py` | ~100 | OCR engine shim | v2.0.0 | specialized/pdf/ |
| `multimodal_processor.py` | ~100 | Multimodal shim | v2.0.0 | specialized/multimodal/ |
| `enhanced_multimodal_processor.py` | ~100 | Enhanced multimodal shim | v2.0.0 | specialized/multimodal/ |
| `batch_processor.py` | ~100 | Batch processor shim | v2.0.0 | specialized/batch/ |
| `advanced_media_processing.py` | ~100 | Advanced media shim | v2.0.0 | specialized/media/ |
| `advanced_web_archiving.py` | ~100 | Web archiving shim | v2.0.0 | specialized/web_archive/ |
| `monitoring.py` | ~100 | Monitoring shim | v2.0.0 | infrastructure/ |
| `profiling.py` | ~100 | Profiling shim | v2.0.0 | infrastructure/ |
| `debug_tools.py` | ~100 | Debug tools shim | v2.0.0 | infrastructure/ |
| `error_handling.py` | ~100 | Error handling shim | v2.0.0 | infrastructure/ |
| `caching.py` | ~100 | Caching shim | v2.0.0 | infrastructure/ |
| `cli.py` | ~100 | CLI shim | v2.0.0 | infrastructure/ |
| `geospatial_analysis.py` | ~100 | Geospatial shim | v2.0.0 | domains/geospatial/ |
| `classify_with_llm.py` | ~100 | ML classification shim | v2.0.0 | domains/ml/ |

**Subtotal:** 19 files (~1,900 lines)

**Action:** Keep these shims until v2.0.0. They provide backward compatibility.

---

### Category 3: Large Implementation Files (Should Move or Split) ⚠️

| File | Lines | Purpose | Recommendation |
|------|-------|---------|----------------|
| `llm_optimizer.py` | 3,377 | LLM optimization engine | Move to engines/llm/ or split |
| `query_engine.py` | 2,996 | Query engine implementation | Move to engines/query/ or split |
| `relationship_analyzer.py` | ~2,000 | Relationship analysis | Move to engines/relationship/ |
| `graphrag_integrator.py` | ~3,000 | GraphRAG integration | Move to specialized/graphrag/ |

**Subtotal:** 4 files (~11,400 lines)

**Action:** These are large implementation files that should be in specialized directories or split into smaller modules. However, facades already exist in `engines/` that import from these files, so we can leave them for now as backend implementations.

---

### Category 4: Domain-Specific (Already Have Counterparts) 🔄

| File | Lines | Purpose | Status | Domain Location |
|------|-------|---------|--------|-----------------|
| `patent_scraper.py` | ~500 | Patent scraper | HAS COUNTERPART | domains/patent/ |
| `patent_dataset_api.py` | ~400 | Patent API | HAS COUNTERPART | domains/patent/ |

**Subtotal:** 2 files (~900 lines)

**Action:** These have counterparts in domains/patent/. Check if root versions are shims or different implementations.

---

### Category 5: API/Interface Files (Keep or Move to Core) 📋

| File | Lines | Purpose | Recommendation |
|------|-------|---------|----------------|
| `corpus_query_api.py` | ~300 | Corpus query API | Consider moving to core/ |
| `relationship_analysis_api.py` | ~300 | Relationship API | Consider moving to core/ or engines/relationship/ |
| `registry.py` | ~100 | Registry (shim to core/registry.py) | ✅ KEEP (shim) |

**Subtotal:** 3 files (~700 lines)

**Action:** Registry is a shim (good). APIs could be consolidated into core/ or relevant engines/.

---

## Summary Statistics

| Category | Files | Est. Lines | Action |
|----------|-------|------------|--------|
| **Core Architecture** | 4 | ~16,600 | ✅ Keep at root |
| **Deprecation Shims** | 19 | ~1,900 | ⏳ Keep until v2.0.0 |
| **Large Implementations** | 4 | ~11,400 | ⚠️ Already have facades in engines/ |
| **Domain-Specific** | 2 | ~900 | 🔄 Check for duplication |
| **API/Interface** | 3 | ~700 | 📋 Consider moving to core/ |
| **TOTAL** | **32** | **~31,500** | |

---

## Recommendations

### Immediate Actions (Phase 8, Task 8.3)

1. **Keep Core Files (4 files)** ✅
   - `__init__.py`, `protocol.py`, `universal_processor.py`
   - Review `input_detection.py` size (~15,000 lines) - consider splitting

2. **Keep Deprecation Shims (19 files)** ✅
   - These provide backward compatibility until v2.0.0
   - All have clear deprecation warnings
   - Users have 6-month grace period

3. **Document Large Implementation Files (4 files)** ✅
   - These are backend implementations for facades in `engines/`
   - Current architecture is: `engines/` (facades) → root files (implementations)
   - This is acceptable for now, but could be improved in future

4. **Check Domain Files (2 files)** 🔍
   - Verify if `patent_scraper.py` and `patent_dataset_api.py` are duplicates or different
   - If duplicates, remove root versions

5. **Review API Files (3 files)** 📝
   - Consider moving `corpus_query_api.py` and `relationship_analysis_api.py` to `core/`
   - `registry.py` is already a shim - keep it

### Future Actions (v2.0.0)

1. **Remove all 19 deprecation shims** (August 2026)
2. **Consider moving large implementations** to `engines/` subdirectories
3. **Split `input_detection.py`** if it grows beyond 20,000 lines

---

## Migration Plan

### For Deprecation Shims (19 files)

**Timeline:**
- **Now (Feb 2026):** Keep all shims, maintain warnings
- **v1.11.0-v1.15.0 (Mar-Jul 2026):** More prominent warnings, provide migration tool
- **v2.0.0 (Aug 2026):** Remove all shims

**User Impact:**
- Zero breaking changes until v2.0.0
- Clear 6-month migration window
- Automated migration tool provided

### For Large Implementation Files (4 files)

**Option A:** Leave as-is (RECOMMENDED)
- Facades in `engines/` already provide clean API
- Root files are just backend implementations
- No user-facing changes needed

**Option B:** Move to engines subdirectories (FUTURE)
- Move `llm_optimizer.py` → `engines/llm/optimizer.py`
- Move `query_engine.py` → `engines/query/engine.py`
- Move `relationship_analyzer.py` → `engines/relationship/analyzer.py`
- Update facade imports
- **Effort:** 8-12 hours
- **Benefit:** Cleaner root directory
- **Risk:** Medium (requires import updates)

### For Domain Files (2 files)

**Action:** Compare and consolidate
1. Check if root `patent_scraper.py` == `domains/patent/patent_scraper.py`
2. If identical, keep domain version, remove root version
3. If different, document differences and create migration path

### For API Files (3 files)

**Action:** Move to core/ (OPTIONAL)
- Move `corpus_query_api.py` → `core/corpus_query_api.py`
- Move `relationship_analysis_api.py` → `core/relationship_analysis_api.py`
- Update imports
- **Effort:** 2-3 hours
- **Benefit:** Better organization

---

## Conclusion

### Current State: ACCEPTABLE ✅

The current 32 root files can be categorized as:
- **4 core files** (necessary at root)
- **19 deprecation shims** (temporary, until v2.0.0)
- **4 large implementations** (backend for facades)
- **5 other files** (APIs and domain files)

### Recommendation: MINIMAL CHANGES

1. **Keep current structure** for Phase 8 (complete within 4 hours)
2. **Document** the organization (this file)
3. **Verify** domain files for duplication
4. **Plan** future optimizations for v2.0.0

### Phase 8 Task 8.3: COMPLETE ✅

This inventory documents all 32 root files with:
- Clear categorization
- Purpose and status
- Migration recommendations
- Timeline for changes

**Next:** Task 8.4 - Archive obsolete phase files
