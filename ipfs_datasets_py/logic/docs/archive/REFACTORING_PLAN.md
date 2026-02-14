# Logic Module Comprehensive Refactoring Plan

**Status:** 📋 Planning Phase  
**Created:** 2026-02-13  
**Target Completion:** 4-6 weeks  
**Estimated Effort:** 80-120 hours

---

## Executive Summary

The `ipfs_datasets_py/logic/` module requires comprehensive refactoring to:
1. **Eliminate code duplication** (tools/ directory mirrors integration/)
2. **Integrate type system** consistently across all modules
3. **Consolidate features** (caching, batch processing, ML confidence, NLP, IPFS, monitoring)
4. **Update outdated documentation** (22 obsolete files)
5. **Reorganize module structure** for better maintainability

### Current State
- **136 Python files**, 51,231 LOC
- **7 duplicate core files** in tools/ directory
- **22 outdated documentation files** (PHASE_COMPLETE.md, SESSION_SUMMARY.md)
- **Type system adoption:** ~40% (integration/ ✅, fol/ ❌, deontic/ ❌, tools/ ❌)
- **Feature integration:** Incomplete across modules

### Key Features to Integrate
1. **Caching System** - ProofCache, IPFSProofCache, TDFOLProofCache
2. **Batch Processing** - FOLBatchProcessor, ProofBatchProcessor, ChunkedBatchProcessor
3. **ML Confidence Scoring** - MLConfidenceScorer with XGBoost/LightGBM
4. **NLP Integration** - spaCy-based predicate extraction
5. **IPFS Integration** - Distributed caching and proof storage
6. **Monitoring** - Prometheus metrics, error tracking, performance monitoring

---

## Phase 1: Critical Issues Analysis ✅ COMPLETE

### 1.1 Code Duplication Identified

| File | Location 1 | Location 2 | Line Count | Status |
|------|-----------|-----------|------------|--------|
| `text_to_fol.py` | fol/ (424 LOC) | tools/ (295 LOC) | Different | ⚠️ Diverged |
| `symbolic_fol_bridge.py` | integration/ (563 LOC) | tools/ (844 LOC) | Different | ⚠️ Diverged |
| `symbolic_logic_primitives.py` | integration/ (550 LOC) | tools/ (667 LOC) | Different | ⚠️ Diverged |
| `deontic_logic_core.py` | integration/ (516 LOC) | tools/ (516 LOC) | Identical | 🔴 Duplicate |
| `modal_logic_extension.py` | integration/ | tools/ | Similar | 🔴 Duplicate |
| `logic_translation_core.py` | integration/ | tools/ | Similar | 🔴 Duplicate |
| `legal_text_to_deontic.py` | deontic/ | tools/ | Similar | 🔴 Duplicate |

**Utility Files Duplicated:**
- `deontic_parser.py` - 3 locations (fol/utils/, deontic/utils/, tools/logic_utils/)
- `fol_parser.py` - 2 locations (fol/utils/, tools/logic_utils/)
- `logic_formatter.py` - 2 locations (fol/utils/, tools/logic_utils/)
- `predicate_extractor.py` - 2 locations (fol/utils/, tools/logic_utils/)

### 1.2 Type System Integration Status

| Module | Files | Type Hints | Imports from logic/types/ | Status |
|--------|-------|------------|---------------------------|--------|
| integration/ | 40+ files | ✅ Yes | ✅ Yes (21 files) | ✅ Complete |
| external_provers/ | 10 files | ✅ Yes | ✅ Yes | ✅ Complete |
| TDFOL/ | 7 files | ✅ Yes | ⚠️ Partial | ⚠️ Needs work |
| CEC/ | 20+ files | ✅ Yes | ⚠️ Partial | ⚠️ Needs work |
| fol/ | 6 files | ⚠️ Partial | ❌ No (1 file only) | 🔴 Missing |
| deontic/ | 3 files | ⚠️ Partial | ❌ No | 🔴 Missing |
| tools/ | 11+ files | ❌ No | ❌ No | 🔴 Delete |
| common/ | 2 files | ✅ Yes | ❌ No | ⚠️ Needs work |

### 1.3 Feature Integration Matrix

| Feature | Location | Integration Status | Notes |
|---------|----------|-------------------|-------|
| **Caching** | integration/proof_cache.py | ✅ Core implementation | LRU + TTL + file persistence |
| | integration/ipfs_proof_cache.py | ✅ IPFS variant | Distributed caching |
| | TDFOL/tdfol_proof_cache.py | ✅ TDFOL-specific | TDFOL formula caching |
| | external_provers/proof_cache.py | ✅ External prover cache | Per-prover caching |
| | fol/ modules | ❌ Missing | No caching in parsers |
| | deontic/ modules | ❌ Missing | No caching in parsers |
| **Batch Processing** | batch_processing.py | ✅ Core implementation | 5 batch processors |
| | integration/tdfol_grammar_bridge.py | ✅ Integrated | batch_parse() |
| | integration/document_consistency_checker.py | ✅ Integrated | batch_check_documents() |
| | CEC/cec_framework.py | ✅ Integrated | batch_reason() |
| | fol/text_to_fol.py | ❌ Missing | No batch support |
| | deontic/legal_text_to_deontic.py | ❌ Missing | No batch support |
| **ML Confidence** | ml_confidence.py | ✅ Core implementation | XGBoost/LightGBM |
| | integration/ | ❌ Not integrated | Should be in provers |
| | external_provers/ | ❌ Not integrated | Should predict success |
| **NLP Integration** | fol/utils/nlp_predicate_extractor.py | ✅ Implemented | spaCy-based |
| | fol/text_to_fol.py | ✅ Integrated | use_nlp parameter |
| | deontic/ | ❌ Not integrated | Should use NLP |
| **IPFS Integration** | integration/ipfs_proof_cache.py | ✅ Implemented | Pin management |
| | integration/ipld_logic_storage.py | ✅ Implemented | IPLD storage |
| | TDFOL/tdfol_proof_cache.py | ❌ Not integrated | Local only |
| | external_provers/proof_cache.py | ❌ Not integrated | Local only |
| **Monitoring** | monitoring.py | ✅ Core implementation | Prometheus metrics |
| | external_provers/monitoring.py | ✅ Implemented | Prover monitoring |
| | integration/ | ⚠️ Partial | Some modules only |
| | fol/ | ❌ Missing | No monitoring |
| | deontic/ | ❌ Missing | No monitoring |

### 1.4 Documentation Issues

**Outdated Files (22 total):**
```
CEC/PHASE4_COMPLETE_STATUS.md
CEC/PHASE4D_COMPLETE.md
CEC/PHASE4_PROJECT_COMPLETE.md
CEC/SESSION_SUMMARY.md
TDFOL/PHASE2_COMPLETE.md
TDFOL/PHASE3_COMPLETE.md
TDFOL/PHASE4_COMPLETE.md
TDFOL/PHASE5_COMPLETE.md
TDFOL/PHASE6_COMPLETE.md
integration/TODO.md (mostly completed)
integration/TODO_ARCHIVED.md
integration/OLD_TESTS_ARCHIVED.md
tools/modal_logic_extension_stubs.md
tools/symbolic_fol_bridge_stubs.md
tools/symbolic_logic_primitives_stubs.md
```

**Missing Documentation:**
- Comprehensive FEATURES.md consolidating all capabilities
- Migration guide for tools/ → integration/ transition
- Updated architecture diagrams
- Feature integration guide

---

## Phase 2: Documentation Cleanup (Week 1, 8-12 hours)

### Objectives
- Archive obsolete documentation
- Create consolidated feature documentation
- Update main README.md
- Create migration guides

### Tasks

#### 2.1 Archive Obsolete Files
```bash
# Create archive directory
mkdir -p ipfs_datasets_py/logic/docs/archive/

# Move PHASE_COMPLETE files
mv ipfs_datasets_py/logic/TDFOL/PHASE*.md docs/archive/
mv ipfs_datasets_py/logic/CEC/PHASE*.md docs/archive/
mv ipfs_datasets_py/logic/CEC/SESSION*.md docs/archive/

# Move old TODOs
mv ipfs_datasets_py/logic/integration/TODO*.md docs/archive/
mv ipfs_datasets_py/logic/integration/OLD_*.md docs/archive/

# Move stub documentation
mv ipfs_datasets_py/logic/tools/*_stubs.md docs/archive/
```

#### 2.2 Create FEATURES.md
**Location:** `ipfs_datasets_py/logic/FEATURES.md`

**Content:**
- Comprehensive list of all 6 core features
- Integration status matrix
- Usage examples for each feature
- Performance characteristics
- Migration guides

#### 2.3 Update README.md
- Remove references to obsolete phases
- Update architecture diagram
- Add feature integration examples
- Update test count (528+ tests)
- Add troubleshooting section

#### 2.4 Create MIGRATION_GUIDE.md
**For:** Transitioning from tools/ to integration/

**Content:**
```python
# Before (tools/)
from ipfs_datasets_py.logic.tools import text_to_fol

# After (integration/)
from ipfs_datasets_py.logic.fol import text_to_fol
from ipfs_datasets_py.logic.integration import DeonticLogicCore
```

### Deliverables
- [ ] 22 files archived
- [ ] FEATURES.md created (500+ lines)
- [ ] README.md updated
- [ ] MIGRATION_GUIDE.md created
- [ ] All documentation cross-references updated

---

## Phase 3: Eliminate Code Duplication (Week 1-2, 16-24 hours)

### Objectives
- Delete tools/ directory entirely
- Consolidate utility files
- Update all imports
- Maintain backward compatibility

### Tasks

#### 3.1 Analyze Import Dependencies
```bash
# Find all imports from tools/
grep -r "from.*logic.tools" ipfs_datasets_py/ tests/
grep -r "import.*logic.tools" ipfs_datasets_py/ tests/
```

#### 3.2 Create Import Compatibility Layer
**Location:** `ipfs_datasets_py/logic/__init__.py`

```python
# Backward compatibility for tools/ imports
# DEPRECATED: Use direct imports from integration/ or fol/
import warnings

def _deprecated_import(old_path, new_path):
    warnings.warn(
        f"{old_path} is deprecated. Use {new_path} instead.",
        DeprecationWarning,
        stacklevel=2
    )

# Redirect tools.text_to_fol → fol.text_to_fol
from ipfs_datasets_py.logic.fol import text_to_fol as _text_to_fol
# ... etc
```

#### 3.3 Delete tools/ Directory
**Steps:**
1. Create deprecation warnings
2. Update all internal imports
3. Update test imports
4. Run full test suite
5. Delete tools/ directory
6. Update .gitignore

```bash
# After verification
rm -rf ipfs_datasets_py/logic/tools/
```

#### 3.4 Consolidate Utility Files
**Current:** 3 copies of utilities in fol/utils/, deontic/utils/, tools/logic_utils/

**Target Structure:**
```
logic/
├── fol/
│   └── utils/          # FOL-specific utilities
│       ├── fol_parser.py
│       ├── logic_formatter.py
│       └── predicate_extractor.py
├── deontic/
│   └── utils/          # Deontic-specific utilities
│       └── deontic_parser.py
└── common/
    └── utils/          # Shared utilities (NEW)
        ├── base_parser.py
        └── shared_formatter.py
```

**Action:**
- Keep specialized versions in fol/utils/ and deontic/utils/
- Create common/utils/ for truly shared code
- Delete tools/logic_utils/ entirely

### Deliverables
- [ ] Import dependency analysis complete
- [ ] Backward compatibility layer created
- [ ] All imports updated (100+ files)
- [ ] tools/ directory deleted
- [ ] Utility files consolidated
- [ ] Tests passing (528+ tests)

---

## Phase 4: Type System Integration (Week 2-3, 20-30 hours)

### Objectives
- Integrate logic/types/ across ALL modules
- Add comprehensive type hints
- Ensure mypy compliance
- Update Protocol definitions

### Tasks

#### 4.1 Update fol/ Module (6 files)

**Files to update:**
1. `fol/text_to_fol.py` (424 LOC)
2. `fol/utils/fol_parser.py`
3. `fol/utils/predicate_extractor.py`
4. `fol/utils/logic_formatter.py`
5. `fol/utils/nlp_predicate_extractor.py` ✅ (already has types)
6. `fol/utils/deontic_parser.py`

**Type imports to add:**
```python
from ipfs_datasets_py.logic.types import (
    FOLFormula,
    Predicate,
    FOLConversionResult,
    LogicOperator,
    Quantifier,
    ComplexityMetrics
)
from typing import List, Dict, Optional, Union, Tuple, Set
```

**Example transformation:**
```python
# Before
def parse_fol(text):
    result = {"formula": formula, "predicates": predicates}
    return result

# After
def parse_fol(text: str) -> FOLConversionResult:
    """
    Parse FOL text into structured formula.
    
    Args:
        text: Input FOL text
        
    Returns:
        FOLConversionResult with formula and predicates
    """
    formula = FOLFormula(...)
    predicates = [Predicate(...) for ...]
    return FOLConversionResult(
        formula=formula,
        predicates=predicates,
        complexity=ComplexityMetrics(...)
    )
```

#### 4.2 Update deontic/ Module (3 files)

**Files to update:**
1. `deontic/legal_text_to_deontic.py`
2. `deontic/utils/deontic_parser.py`
3. `deontic/__init__.py`

**Type imports to add:**
```python
from ipfs_datasets_py.logic.types import (
    DeonticOperator,
    DeonticFormula,
    DeonticConflict,
    ConflictResolution
)
```

#### 4.3 Update common/ Module (2 files)

**Files to update:**
1. `common/converters.py`
2. `common/errors.py`

**Type imports to add:**
```python
from ipfs_datasets_py.logic.types import (
    BridgeCapability,
    ConversionResult,
    BridgeConfig
)
```

#### 4.4 Add Missing Type Definitions

**New types needed:**
```python
# types/fol_types.py additions
@dataclass
class FOLParseResult:
    """Result of FOL parsing operation."""
    formulas: List[FOLFormula]
    predicates: List[Predicate]
    variables: Set[str]
    complexity: ComplexityMetrics
    parse_time_ms: float

@dataclass
class PredicateExtractionResult:
    """Result of predicate extraction."""
    predicates: List[Predicate]
    entities: List[str]
    relations: List[Tuple[str, str, str]]
    confidence: float
```

#### 4.5 Run Type Checking
```bash
# Type check all updated modules
mypy ipfs_datasets_py/logic/fol/ --strict
mypy ipfs_datasets_py/logic/deontic/ --strict
mypy ipfs_datasets_py/logic/common/ --strict

# Generate type coverage report
mypy ipfs_datasets_py/logic/ --html-report mypy-report/
```

### Deliverables
- [ ] fol/ fully typed (6 files)
- [ ] deontic/ fully typed (3 files)
- [ ] common/ fully typed (2 files)
- [ ] 10+ new type definitions added
- [ ] mypy compliance at 95%+
- [ ] Type coverage report

---

## Phase 5: Feature Integration (Week 3-5, 32-48 hours)

### Objectives
- Integrate all 6 core features across modules
- Ensure consistent API patterns
- Add comprehensive monitoring
- Optimize performance

### 5.1 Caching Integration (8-12 hours)

#### Add Caching to FOL Parsers
**Files to update:**
- `fol/text_to_fol.py`
- `fol/utils/fol_parser.py`
- `fol/utils/predicate_extractor.py`

**Implementation:**
```python
from ipfs_datasets_py.logic.integration.proof_cache import get_global_cache
from functools import lru_cache
import hashlib

class FOLParser:
    def __init__(self, use_cache: bool = True):
        self.use_cache = use_cache
        self.cache = get_global_cache() if use_cache else None
    
    def parse(self, text: str) -> FOLFormula:
        if self.use_cache:
            cache_key = hashlib.sha256(text.encode()).hexdigest()
            cached = self.cache.get(cache_key)
            if cached:
                return cached
        
        result = self._parse_impl(text)
        
        if self.use_cache:
            self.cache.put(cache_key, result)
        
        return result
    
    @lru_cache(maxsize=1000)
    def _parse_cached(self, text: str) -> FOLFormula:
        """Cached parsing for frequently used formulas."""
        return self._parse_impl(text)
```

#### Add Caching to Deontic Parsers
**Files to update:**
- `deontic/legal_text_to_deontic.py`
- `deontic/utils/deontic_parser.py`

**Implementation:**
```python
from ipfs_datasets_py.logic.integration.proof_cache import get_global_cache

class DeonticParser:
    def __init__(self, use_cache: bool = True, use_ipfs: bool = False):
        self.use_cache = use_cache
        if use_ipfs:
            from ipfs_datasets_py.logic.integration.ipfs_proof_cache import get_global_ipfs_cache
            self.cache = get_global_ipfs_cache()
        elif use_cache:
            self.cache = get_global_cache()
        else:
            self.cache = None
```

#### Integrate IPFS Caching
**Update files:**
- `TDFOL/tdfol_proof_cache.py` - add IPFS backend
- `external_provers/proof_cache.py` - add IPFS backend

**Add IPFS support:**
```python
class TDFOLProofCache:
    def __init__(self, use_ipfs: bool = False):
        self.use_ipfs = use_ipfs
        if use_ipfs:
            from ipfs_datasets_py.logic.integration.ipfs_proof_cache import IPFSProofCache
            self.ipfs_cache = IPFSProofCache()
    
    def get_with_ipfs_fallback(self, key: str):
        # Try local cache first
        result = self.local_cache.get(key)
        if result:
            return result
        
        # Fallback to IPFS
        if self.use_ipfs:
            return self.ipfs_cache.get(key)
        
        return None
```

### 5.2 Batch Processing Integration (8-12 hours)

#### Add Batch Support to FOL
**File:** `fol/text_to_fol.py`

**Implementation:**
```python
from ipfs_datasets_py.logic.batch_processing import FOLBatchProcessor

class FOLConverter:
    def __init__(self):
        self.batch_processor = FOLBatchProcessor()
    
    def convert_batch(
        self,
        texts: List[str],
        max_workers: int = 4,
        use_cache: bool = True
    ) -> List[FOLConversionResult]:
        """
        Convert multiple texts to FOL in parallel.
        
        Args:
            texts: List of texts to convert
            max_workers: Number of parallel workers
            use_cache: Whether to use caching
            
        Returns:
            List of conversion results
        """
        return self.batch_processor.process(
            texts,
            conversion_func=self.convert,
            max_workers=max_workers,
            use_cache=use_cache
        )
```

#### Add Batch Support to Deontic
**File:** `deontic/legal_text_to_deontic.py`

**Implementation:**
```python
from ipfs_datasets_py.logic.batch_processing import BatchProcessor
import asyncio

class DeonticConverter:
    async def convert_batch_async(
        self,
        texts: List[str],
        max_workers: int = 4
    ) -> List[DeonticFormula]:
        """Async batch conversion for high throughput."""
        tasks = [
            asyncio.create_task(self.convert_async(text))
            for text in texts
        ]
        return await asyncio.gather(*tasks)
```

### 5.3 ML Confidence Integration (8-12 hours)

#### Add ML Confidence to Provers
**Files to update:**
- `integration/proof_execution_engine.py`
- `external_provers/prover_router.py`
- `TDFOL/tdfol_prover.py`

**Implementation:**
```python
from ipfs_datasets_py.logic.ml_confidence import MLConfidenceScorer

class ProofExecutionEngine:
    def __init__(self, use_ml_confidence: bool = True):
        self.use_ml = use_ml_confidence
        if self.use_ml:
            self.ml_scorer = MLConfidenceScorer()
    
    def prove_with_confidence(
        self,
        theorem: str,
        axioms: List[str]
    ) -> ProofResult:
        """
        Prove theorem and predict confidence.
        
        Returns:
            ProofResult with confidence score
        """
        # Extract features
        if self.use_ml:
            features = self.ml_scorer.extract_features(theorem, axioms)
            predicted_confidence = self.ml_scorer.predict(features)
        
        # Run proof
        result = self.prove(theorem, axioms)
        
        # Add confidence to result
        if self.use_ml:
            result.ml_confidence = predicted_confidence
            result.confidence_factors = features
        
        return result
```

#### Train ML Models
**Create:** `logic/ml_confidence/train_models.py`

```python
"""Train ML confidence models from historical proof data."""

from ipfs_datasets_py.logic.ml_confidence import MLConfidenceScorer
from ipfs_datasets_py.logic.integration.proof_cache import get_global_cache

def train_from_cache():
    """Train ML models from cached proof results."""
    cache = get_global_cache()
    entries = cache.get_cached_entries()
    
    # Prepare training data
    X, y = [], []
    for entry in entries:
        features = extract_features(entry)
        success = 1 if entry.is_proved else 0
        X.append(features)
        y.append(success)
    
    # Train model
    scorer = MLConfidenceScorer()
    scorer.train(X, y)
    scorer.save("models/ml_confidence.pkl")
```

### 5.4 NLP Integration (4-6 hours)

#### Add NLP to Deontic Parser
**File:** `deontic/legal_text_to_deontic.py`

**Implementation:**
```python
from ipfs_datasets_py.logic.fol.utils.nlp_predicate_extractor import extract_predicates_nlp

class DeonticConverter:
    def __init__(self, use_nlp: bool = True):
        self.use_nlp = use_nlp
        if use_nlp:
            import spacy
            try:
                self.nlp = spacy.load("en_core_web_sm")
            except OSError:
                self.use_nlp = False
    
    def convert(self, text: str, use_nlp: Optional[bool] = None) -> DeonticFormula:
        """
        Convert legal text to deontic logic.
        
        Args:
            text: Legal text
            use_nlp: Override NLP usage
            
        Returns:
            Deontic formula
        """
        use_nlp = use_nlp if use_nlp is not None else self.use_nlp
        
        if use_nlp and self.nlp:
            # Use NLP for entity extraction
            predicates = extract_predicates_nlp(text, self.nlp)
            return self._build_deontic_from_nlp(predicates)
        else:
            # Fallback to regex
            return self._build_deontic_regex(text)
```

### 5.5 IPFS Integration (4-6 hours)

#### Already implemented in:
- ✅ `integration/ipfs_proof_cache.py`
- ✅ `integration/ipld_logic_storage.py`

#### Expand to:
- `TDFOL/tdfol_proof_cache.py` - Add IPFS backend option
- `external_provers/proof_cache.py` - Add IPFS backend option
- `common/converters.py` - Add IPFS storage option

### 5.6 Monitoring Integration (8-12 hours)

#### Add Monitoring to All Modules
**Files to update:**
- `fol/text_to_fol.py`
- `deontic/legal_text_to_deontic.py`
- `TDFOL/tdfol_prover.py`
- `common/converters.py`

**Implementation:**
```python
from ipfs_datasets_py.logic.monitoring import Monitor, get_global_monitor
from ipfs_datasets_py.logic.external_provers.monitoring import Monitor as ProverMonitor
import time

class FOLConverter:
    def __init__(self, enable_monitoring: bool = True):
        self.enable_monitoring = enable_monitoring
        if enable_monitoring:
            self.monitor = get_global_monitor("fol_converter")
    
    def convert(self, text: str) -> FOLConversionResult:
        """Convert text to FOL with monitoring."""
        if self.enable_monitoring:
            self.monitor.record_operation_start("convert")
        
        start_time = time.time()
        
        try:
            result = self._convert_impl(text)
            
            if self.enable_monitoring:
                duration = time.time() - start_time
                self.monitor.record_success("convert", duration)
                self.monitor.record_metric("formula_complexity", result.complexity.total_score)
            
            return result
            
        except Exception as e:
            if self.enable_monitoring:
                self.monitor.record_error("convert", str(e))
            raise
```

#### Create Monitoring Dashboard
**Create:** `logic/monitoring_dashboard.py`

```python
"""Real-time monitoring dashboard for logic modules."""

from ipfs_datasets_py.logic.monitoring import get_global_monitor
from ipfs_datasets_py.logic.external_provers.monitoring import Monitor

def get_system_metrics():
    """Get comprehensive system metrics."""
    return {
        "fol_converter": get_global_monitor("fol_converter").get_stats(),
        "deontic_converter": get_global_monitor("deontic_converter").get_stats(),
        "tdfol_prover": get_global_monitor("tdfol_prover").get_stats(),
        "cache": get_global_cache().get_stats(),
    }
```

### Deliverables
- [ ] Caching integrated in fol/ and deontic/ (6 files)
- [ ] Batch processing in all converters (4 files)
- [ ] ML confidence in all provers (3 files)
- [ ] NLP in deontic converter (1 file)
- [ ] IPFS caching expanded (2 files)
- [ ] Monitoring in all modules (8 files)
- [ ] Performance benchmarks updated
- [ ] Integration tests passing

---

## Phase 6: Module Reorganization (Week 5-6, 16-24 hours)

### Objectives
- Restructure integration/ for clarity
- Create unified API entry points
- Improve import ergonomics
- Document new structure

### Tasks

#### 6.1 Restructure integration/ Directory

**Current Issues:**
- 40+ files in flat structure
- No clear separation of concerns
- Difficult to navigate

**Proposed Structure:**
```
integration/
├── __init__.py          # Clean API exports
├── api.py               # Unified API (NEW)
├── bridges/             # All bridge implementations (NEW)
│   ├── __init__.py
│   ├── base_prover_bridge.py
│   ├── symbolic_fol_bridge.py
│   ├── tdfol_cec_bridge.py
│   ├── tdfol_grammar_bridge.py
│   └── tdfol_shadowprover_bridge.py
├── caching/             # All caching implementations (NEW)
│   ├── __init__.py
│   ├── proof_cache.py
│   ├── ipfs_proof_cache.py
│   └── cache_manager.py
├── reasoning/           # Core reasoning engines (NEW)
│   ├── __init__.py
│   ├── deontological_reasoning.py
│   ├── deontological_reasoning_types.py
│   ├── deontological_reasoning_utils.py
│   ├── logic_verification.py
│   ├── logic_verification_types.py
│   ├── logic_verification_utils.py
│   ├── proof_execution_engine.py
│   ├── proof_execution_engine_types.py
│   └── proof_execution_engine_utils.py
├── neurosymbolic/       # Neurosymbolic integration (EXISTS)
│   ├── __init__.py
│   ├── embedding_prover.py
│   ├── hybrid_confidence.py
│   └── reasoning_coordinator.py
├── converters/          # Format converters (NEW)
│   ├── __init__.py
│   ├── deontic_logic_converter.py
│   ├── logic_translation_core.py
│   └── symbolic_logic_primitives.py
├── domain/              # Domain-specific modules (NEW)
│   ├── __init__.py
│   ├── legal_domain_knowledge.py
│   ├── legal_symbolic_analyzer.py
│   ├── medical_theorem_framework.py
│   ├── caselaw_bulk_processor.py
│   └── document_consistency_checker.py
└── storage/             # Storage backends (NEW)
    ├── __init__.py
    ├── ipld_logic_storage.py
    └── temporal_deontic_rag_store.py
```

#### 6.2 Create Unified API
**File:** `integration/api.py`

```python
"""
Unified API for IPFS Datasets Python Logic Module.

This module provides a single entry point for all logic capabilities:
- FOL conversion
- Deontic reasoning
- Theorem proving
- TDFOL reasoning
- CEC inference
- Modal logic
- Batch processing
- ML confidence scoring
"""

from typing import List, Optional, Dict, Any
from ipfs_datasets_py.logic.types import *
from ipfs_datasets_py.logic.fol import text_to_fol
from ipfs_datasets_py.logic.deontic import legal_text_to_deontic
from ipfs_datasets_py.logic.integration.reasoning import ProofExecutionEngine
from ipfs_datasets_py.logic.TDFOL import TDFOLProver
from ipfs_datasets_py.logic.CEC import CECFramework
from ipfs_datasets_py.logic.batch_processing import BatchProcessor
from ipfs_datasets_py.logic.ml_confidence import MLConfidenceScorer

class LogicAPI:
    """
    Unified API for all logic operations.
    
    Features:
    - Text to FOL conversion (with NLP)
    - Legal text to deontic logic
    - Theorem proving (multiple provers)
    - Batch processing (6x faster)
    - ML confidence scoring
    - IPFS caching
    - Real-time monitoring
    
    Examples:
        >>> api = LogicAPI()
        >>> result = api.convert_to_fol("All humans are mortal")
        >>> proof = api.prove("Q", axioms=["P", "P -> Q"])
        >>> batch_results = api.convert_batch(texts)
    """
    
    def __init__(
        self,
        use_cache: bool = True,
        use_ipfs: bool = False,
        use_ml: bool = True,
        use_nlp: bool = True,
        enable_monitoring: bool = True
    ):
        """
        Initialize Logic API.
        
        Args:
            use_cache: Enable proof caching
            use_ipfs: Use IPFS for distributed caching
            use_ml: Enable ML confidence scoring
            use_nlp: Enable NLP predicate extraction
            enable_monitoring: Enable monitoring and metrics
        """
        self.use_cache = use_cache
        self.use_ipfs = use_ipfs
        self.use_ml = use_ml
        self.use_nlp = use_nlp
        self.enable_monitoring = enable_monitoring
        
        # Initialize components
        self._init_components()
    
    def _init_components(self):
        """Initialize all logic components."""
        from ipfs_datasets_py.logic.fol import FOLConverter
        from ipfs_datasets_py.logic.deontic import DeonticConverter
        
        self.fol_converter = FOLConverter(
            use_cache=self.use_cache,
            use_nlp=self.use_nlp,
            enable_monitoring=self.enable_monitoring
        )
        
        self.deontic_converter = DeonticConverter(
            use_cache=self.use_cache,
            use_nlp=self.use_nlp,
            enable_monitoring=self.enable_monitoring
        )
        
        self.prover = ProofExecutionEngine(
            use_cache=self.use_cache,
            use_ipfs=self.use_ipfs,
            use_ml_confidence=self.use_ml,
            enable_monitoring=self.enable_monitoring
        )
        
        if self.use_ml:
            self.ml_scorer = MLConfidenceScorer()
        
        self.batch_processor = BatchProcessor()
    
    # FOL Operations
    def convert_to_fol(
        self,
        text: str,
        use_nlp: Optional[bool] = None
    ) -> FOLConversionResult:
        """Convert natural language text to FOL."""
        return self.fol_converter.convert(text, use_nlp=use_nlp)
    
    def convert_to_fol_batch(
        self,
        texts: List[str],
        max_workers: int = 4
    ) -> List[FOLConversionResult]:
        """Convert multiple texts to FOL in parallel."""
        return self.fol_converter.convert_batch(texts, max_workers=max_workers)
    
    # Deontic Operations
    def convert_to_deontic(
        self,
        text: str,
        domain: str = "legal"
    ) -> DeonticFormula:
        """Convert legal/normative text to deontic logic."""
        return self.deontic_converter.convert(text, domain=domain)
    
    def detect_conflicts(
        self,
        formulas: List[DeonticFormula]
    ) -> List[DeonticConflict]:
        """Detect conflicts in deontic formulas."""
        return self.deontic_converter.detect_conflicts(formulas)
    
    # Proof Operations
    def prove(
        self,
        theorem: str,
        axioms: List[str],
        method: str = "auto"
    ) -> ProofResult:
        """Prove theorem from axioms."""
        return self.prover.prove(theorem, axioms, method=method)
    
    def prove_with_confidence(
        self,
        theorem: str,
        axioms: List[str]
    ) -> ProofResultWithConfidence:
        """Prove theorem and predict confidence."""
        return self.prover.prove_with_confidence(theorem, axioms)
    
    def prove_batch(
        self,
        theorems: List[str],
        axioms: List[List[str]],
        max_workers: int = 4
    ) -> List[ProofResult]:
        """Prove multiple theorems in parallel."""
        return self.prover.prove_batch(theorems, axioms, max_workers=max_workers)
    
    # Monitoring
    def get_metrics(self) -> Dict[str, Any]:
        """Get system metrics and statistics."""
        from ipfs_datasets_py.logic.monitoring import get_global_monitor
        
        return {
            "fol_converter": self.fol_converter.get_stats(),
            "deontic_converter": self.deontic_converter.get_stats(),
            "prover": self.prover.get_stats(),
            "cache": self._get_cache_stats(),
        }
    
    def _get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        if self.use_ipfs:
            from ipfs_datasets_py.logic.integration.ipfs_proof_cache import get_global_ipfs_cache
            return get_global_ipfs_cache().get_stats()
        elif self.use_cache:
            from ipfs_datasets_py.logic.integration.proof_cache import get_global_cache
            return get_global_cache().get_stats()
        return {}


# Convenience function
def create_logic_api(**kwargs) -> LogicAPI:
    """
    Create Logic API with configuration.
    
    Args:
        use_cache: Enable caching (default: True)
        use_ipfs: Use IPFS for distributed caching (default: False)
        use_ml: Enable ML confidence (default: True)
        use_nlp: Enable NLP (default: True)
        enable_monitoring: Enable monitoring (default: True)
    
    Returns:
        Configured LogicAPI instance
    
    Examples:
        >>> api = create_logic_api(use_ipfs=True, use_ml=True)
        >>> result = api.prove("Q", axioms=["P", "P -> Q"])
    """
    return LogicAPI(**kwargs)
```

#### 6.3 Update __init__.py Files

**logic/__init__.py:**
```python
"""
IPFS Datasets Python - Logic Module

Comprehensive neurosymbolic reasoning system combining:
- Temporal Deontic First-Order Logic (TDFOL)
- Cognitive Event Calculus (CEC)
- Modal Logic Provers (K, S4, S5, D, Cognitive)
- Grammar-Based Natural Language Processing
- ML Confidence Scoring
- IPFS Distributed Caching
- Real-time Monitoring
"""

# Unified API (Recommended)
from ipfs_datasets_py.logic.integration.api import (
    LogicAPI,
    create_logic_api
)

# Core converters
from ipfs_datasets_py.logic.fol import text_to_fol, FOLConverter
from ipfs_datasets_py.logic.deontic import legal_text_to_deontic, DeonticConverter

# Provers
from ipfs_datasets_py.logic.integration.reasoning import ProofExecutionEngine
from ipfs_datasets_py.logic.TDFOL import TDFOLProver
from ipfs_datasets_py.logic.CEC import CECFramework

# Features
from ipfs_datasets_py.logic.batch_processing import (
    BatchProcessor,
    FOLBatchProcessor,
    ProofBatchProcessor
)
from ipfs_datasets_py.logic.ml_confidence import MLConfidenceScorer
from ipfs_datasets_py.logic.integration.caching import (
    get_global_cache,
    get_global_ipfs_cache
)

# Types
from ipfs_datasets_py.logic.types import *

__version__ = "1.0.0"

__all__ = [
    # Unified API
    "LogicAPI",
    "create_logic_api",
    
    # Converters
    "FOLConverter",
    "text_to_fol",
    "DeonticConverter", 
    "legal_text_to_deontic",
    
    # Provers
    "ProofExecutionEngine",
    "TDFOLProver",
    "CECFramework",
    
    # Features
    "BatchProcessor",
    "FOLBatchProcessor",
    "ProofBatchProcessor",
    "MLConfidenceScorer",
    "get_global_cache",
    "get_global_ipfs_cache",
]
```

### Deliverables
- [ ] integration/ restructured into 7 subdirectories
- [ ] Unified LogicAPI created (500+ LOC)
- [ ] All __init__.py files updated
- [ ] Import paths maintained for backward compatibility
- [ ] Documentation updated
- [ ] All tests passing

---

## Phase 7: Testing & Validation (Week 6, 8-12 hours)

### Objectives
- Validate all refactoring
- Update test suite
- Run performance benchmarks
- Update CI/CD

### Tasks

#### 7.1 Update Tests
- Update import statements (100+ files)
- Add tests for new API
- Add tests for feature integration
- Add tests for monitoring

#### 7.2 Run Test Suite
```bash
# Full test suite
pytest tests/unit_tests/logic/ -v --cov=ipfs_datasets_py/logic/

# Specific modules
pytest tests/unit_tests/logic/fol/ -v
pytest tests/unit_tests/logic/deontic/ -v
pytest tests/unit_tests/logic/integration/ -v

# Performance tests
pytest tests/unit_tests/logic/test_benchmarks.py -v
```

#### 7.3 Performance Benchmarks
```bash
# Run benchmarks
python -m ipfs_datasets_py.logic.benchmarks

# Compare before/after
python scripts/logic_performance_comparison.py
```

#### 7.4 Update CI/CD
- Update GitHub Actions workflows
- Add type checking to CI
- Add performance regression tests
- Update documentation builds

### Deliverables
- [ ] All tests passing (528+ tests)
- [ ] Test coverage >80%
- [ ] Performance benchmarks showing improvement
- [ ] CI/CD updated
- [ ] Documentation complete

---

## Success Metrics

### Code Quality
- [ ] Zero code duplication (tools/ deleted)
- [ ] 95%+ type hint coverage
- [ ] 80%+ test coverage
- [ ] 100% mypy compliance

### Performance
- [ ] Cache hit rate >60%
- [ ] Batch processing 5-8x faster
- [ ] ML confidence <1ms
- [ ] FOL conversion <10ms

### Features
- [ ] Caching integrated in all modules
- [ ] Batch processing in all converters
- [ ] ML confidence in all provers
- [ ] NLP in FOL and deontic
- [ ] IPFS caching available everywhere
- [ ] Monitoring in all operations

### Documentation
- [ ] 22 obsolete files archived
- [ ] FEATURES.md created
- [ ] MIGRATION_GUIDE.md created
- [ ] All READMEs updated
- [ ] API documentation complete

---

## Risk Mitigation

### Backward Compatibility
- Maintain compatibility layer for tools/ imports
- Deprecation warnings for 2 releases
- Comprehensive migration guide

### Testing
- Run full test suite after each phase
- Incremental changes with git commits
- Feature flags for new capabilities

### Performance
- Benchmark before/after each change
- Profile critical paths
- Cache optimization

---

## Timeline Summary

| Phase | Duration | Effort | Status |
|-------|----------|--------|--------|
| 1. Analysis | Week 1 | 4h | ✅ Complete |
| 2. Documentation | Week 1 | 8-12h | 🔜 Next |
| 3. Duplication | Week 1-2 | 16-24h | ⏳ Pending |
| 4. Type System | Week 2-3 | 20-30h | ⏳ Pending |
| 5. Features | Week 3-5 | 32-48h | ⏳ Pending |
| 6. Reorganization | Week 5-6 | 16-24h | ⏳ Pending |
| 7. Testing | Week 6 | 8-12h | ⏳ Pending |
| **Total** | **6 weeks** | **104-154h** | **1/7 complete** |

---

## Next Steps

1. **Archive documentation** (Phase 2)
2. **Delete tools/ directory** (Phase 3)
3. **Add type hints to fol/** (Phase 4)
4. **Integrate caching** (Phase 5.1)
5. **Create unified API** (Phase 6.2)

---

## Questions & Decisions

### Q1: Should we maintain tools/ for backward compatibility?
**Decision:** No. Delete tools/ and provide deprecation layer in __init__.py.

### Q2: Should IPFS caching be default?
**Decision:** No. Make it opt-in via use_ipfs parameter.

### Q3: Should we use async everywhere?
**Decision:** Provide both sync and async APIs where appropriate.

### Q4: Should ML confidence be always-on?
**Decision:** Yes, but with heuristic fallback if models not available.

---

**Last Updated:** 2026-02-13  
**Next Review:** After Phase 2 completion
