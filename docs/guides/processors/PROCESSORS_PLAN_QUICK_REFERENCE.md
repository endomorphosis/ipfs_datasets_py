# Processors Refactoring Plan - Quick Reference

**Last Updated:** February 16, 2026  
**Full Plan:** See `PROCESSORS_COMPREHENSIVE_PLAN_2026.md`  
**Status:** Planning → Implementation  

---

## 🎯 Quick Summary

**Goal:** Complete the processors directory refactoring by organizing remaining files, splitting large monoliths, and achieving >90% test coverage.

**Effort:** 92 hours over 4 weeks  
**Phases:** 7 phases, from critical consolidation to final polish  

---

## 📊 Current State vs Target

| Metric | Current | Target |
|--------|---------|--------|
| Root-level files | 32 | <15 |
| Largest file | 3,377 lines | <800 lines |
| Test coverage | ~40% | >90% |
| Documentation files | 35 | <10 |

---

## 📁 Target Directory Structure

```
processors/
├── specialized/        # Domain-specific processors
│   ├── graphrag/      # Knowledge graphs
│   ├── pdf/           # PDF processing
│   ├── multimodal/    # Multi-modal content
│   ├── batch/         # Batch processing
│   ├── media/         # Advanced media (NEW)
│   └── web_archive/   # Web archiving (NEW)
│
├── infrastructure/     # Cross-cutting tools
│   ├── caching/       # Multi-tier caching (NEW)
│   ├── monitoring/    # Metrics & monitoring (NEW)
│   ├── optimization/  # Performance (NEW)
│   └── ... (other utils)
│
├── domains/           # Business logic
│   ├── patent/       # Patent processing
│   ├── geospatial/   # Geographic data
│   ├── ml/           # ML classification
│   └── legal/        # Legal documents (NEW)
│
├── core/              # Framework
│   ├── protocol.py   # ProcessorProtocol
│   ├── registry.py   # Unified registry (consolidated)
│   ├── routing.py    # Input routing
│   └── universal.py  # Universal processor
│
└── engines/           # Processing engines (NEW)
    ├── llm/          # LLM optimization (split from llm_optimizer.py)
    ├── query/        # Query engine (split from query_engine.py)
    └── relationship/ # Relationship analysis
```

---

## 🗓️ 7 Phases Overview

### Phase 1: Critical Consolidation (8h)
- Consolidate registry (registry.py → core/registry.py)
- Move advanced files to proper locations
- Move input_detection to core/
- **Deliverable:** Clearer organization, 3 fewer root files

### Phase 2: Large File Refactoring (16h)
- Split llm_optimizer.py (3,377 lines) → engines/llm/
- Split query_engine.py (2,996 lines) → engines/query/
- Consolidate relationship_*.py → engines/relationship/
- **Deliverable:** No file >800 lines

### Phase 3: Integration & Testing (20h)
- Create integration tests for all modules
- Unit tests for infrastructure/, domains/, engines/
- Deprecation warning tests
- **Deliverable:** >90% test coverage

### Phase 4: Performance Optimization (16h)
- Profile and identify bottlenecks
- Implement multi-tier caching
- Parallel processing improvements
- **Deliverable:** 2x performance improvement

### Phase 5: Documentation Consolidation (12h)
- Audit 35 documentation files
- Create single MASTER_GUIDE.md
- Archive old time-stamped docs
- **Deliverable:** Clear, comprehensive docs

### Phase 6: Quality & Security (16h)
- Code review and type checking
- Linting and formatting
- Security audit
- **Deliverable:** Production-ready code

### Phase 7: Final Polish (8h)
- Changelog and release notes
- Final testing and validation
- Cleanup and polish
- **Deliverable:** v1.10.0 release

---

## 🎯 Key Files to Refactor

### Priority 1: Must Consolidate
- **llm_optimizer.py** (3,377 lines) → Split into 7 modules in `engines/llm/`
- **query_engine.py** (2,996 lines) → Split into 6 modules in `engines/query/`
- **registry.py** (383 lines) → Merge with `core/processor_registry.py`

### Priority 2: Should Move
- **advanced_media_processing.py** (639 lines) → `specialized/media/`
- **advanced_web_archiving.py** (971 lines) → `specialized/web_archive/`
- **advanced_graphrag_website_processor.py** → Consolidate into `specialized/graphrag/`
- **input_detection.py** (486 lines) → `core/input_detection.py`

### Priority 3: Should Consolidate
- **relationship_analyzer.py** (260 lines) → `engines/relationship/analyzer.py`
- **relationship_analysis_api.py** (139 lines) → `engines/relationship/api.py`
- **corpus_query_api.py** (129 lines) → `engines/relationship/corpus.py`

---

## 🧪 Testing Strategy

### Coverage Targets
- **Core modules:** 100%
- **Specialized processors:** 95%
- **Infrastructure:** 95%
- **Domains:** 90%
- **Engines:** 95%

### Test Types
- **Unit Tests (60%):** Individual functions/classes
- **Integration Tests (30%):** Multi-module interactions
- **E2E Tests (10%):** Complete workflows

### New Test Files Needed
```
tests/
├── unit/
│   ├── infrastructure/
│   │   ├── test_caching.py
│   │   ├── test_monitoring.py
│   │   └── test_profiling.py
│   ├── domains/
│   │   ├── test_patent.py
│   │   ├── test_geospatial.py
│   │   └── test_ml.py
│   └── engines/
│       ├── test_llm_optimizer.py
│       ├── test_query_engine.py
│       └── test_relationship.py
├── integration/
│   ├── test_specialized_processors.py
│   ├── test_cross_module.py
│   └── test_backward_compat.py
└── e2e/
    └── test_complete_workflows.py
```

---

## 🔄 Migration Quick Reference

### Most Common Migrations

```python
# Registry
from ipfs_datasets_py.processors.registry import ProcessorRegistry

# ↓ NEW
from ipfs_datasets_py.processors.core.registry import ProcessorRegistry

# GraphRAG
from ipfs_datasets_py.processors.graphrag_processor import GraphRAGProcessor

# ↓ NEW
from ipfs_datasets_py.processors.specialized.graphrag import UnifiedGraphRAGProcessor

# PDF
from ipfs_datasets_py.processors.pdf_processor import PDFProcessor

# ↓ NEW
from ipfs_datasets_py.processors.specialized.pdf import PDFProcessor

# LLM Optimizer
from ipfs_datasets_py.processors.llm_optimizer import LLMOptimizer

# ↓ NEW
from ipfs_datasets_py.processors.engines.llm import LLMOptimizer

# Query Engine
from ipfs_datasets_py.processors.query_engine import QueryEngine

# ↓ NEW
from ipfs_datasets_py.processors.engines.query import QueryEngine

# Advanced Media
from ipfs_datasets_py.processors.advanced_media_processing import AdvancedMediaProcessor

# ↓ NEW
from ipfs_datasets_py.processors.specialized.media import AdvancedMediaProcessor
```

### Automated Migration
```bash
# Use migration script
python scripts/migrate_processors_imports.py --path /your/code
```

---

## ⚡ Performance Targets

| Operation | Current | Target | Improvement |
|-----------|---------|--------|-------------|
| PDF processing | 2.5s/page | 1.5s/page | 40% faster |
| GraphRAG extraction | 15s/URL | 8s/URL | 47% faster |
| Batch processing | 100/min | 200/min | 2x faster |
| LLM optimization | 1s/1k tok | 0.5s/1k tok | 2x faster |
| Query execution | 200ms | 100ms | 2x faster |

---

## 📋 Weekly Milestones

### Week 1 (20h)
- ✅ Registry consolidated
- ✅ Advanced files moved
- ✅ Start llm_optimizer split
- **Goal:** Phase 1 complete + 50% Phase 2

### Week 2 (24h)
- ✅ llm_optimizer & query_engine refactored
- ✅ Integration tests created
- ✅ 80% test coverage
- **Goal:** Phases 2 & 3 mostly complete

### Week 3 (24h)
- ✅ Performance optimizations done
- ✅ Caching subsystem implemented
- ✅ Documentation drafted
- **Goal:** Phases 4 & 5 complete

### Week 4 (24h)
- ✅ Code quality checks pass
- ✅ Security audit complete
- ✅ Final testing done
- ✅ v1.10.0 ready
- **Goal:** Phases 6 & 7 complete, release!

---

## ✅ Acceptance Criteria

**Ready for Release When:**
- [ ] All root files justified (<15 total)
- [ ] No file exceeds 800 lines
- [ ] Test coverage >90%
- [ ] Performance targets met
- [ ] Single master documentation guide
- [ ] Type checking passes (mypy)
- [ ] Linting clean (flake8)
- [ ] Security scan clear
- [ ] All deprecation warnings tested
- [ ] Migration paths validated
- [ ] Release notes published

---

## 🚀 Getting Started

### 1. Review Full Plan
Read `PROCESSORS_COMPREHENSIVE_PLAN_2026.md` for complete details.

### 2. Set Up Tracking
Create GitHub issues for each phase/task.

### 3. Start Phase 1
Begin with Task 1.1 (Registry Consolidation).

### 4. Follow TDD
Write tests first, then implement changes.

### 5. Update Documentation
Keep docs current as you progress.

---

## 📞 Communication

**Weekly Updates:** Every Friday  
**Reviews:** Week 2 mid-point, Week 4 final  
**Questions:** Open GitHub issues  

---

## 🔗 Related Documents

- **Full Plan:** `PROCESSORS_COMPREHENSIVE_PLAN_2026.md`
- **Migration Guide:** `PROCESSORS_MIGRATION_GUIDE.md`
- **Architecture:** `PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md`
- **Previous Work:** `PROCESSORS_PHASES_1_7_COMPLETE.md`

---

**Status:** 🟡 READY TO START  
**Next Step:** Review plan → Begin Phase 1  
**Timeline:** 4 weeks starting Week of Feb 16, 2026  

