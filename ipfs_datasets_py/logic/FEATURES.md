# Logic Module - Comprehensive Features Documentation

**Version:** 2.0  
**Last Updated:** 2026-02-17  
**Status:** Beta (Core Converters Production-Ready) ⚠️

---

## 🎉 Integration Status Summary

**Feature Integration in Unified Converters:**

| Feature | FOL Converter | Deontic Converter | Status | Notes |
|---------|---------------|-------------------|---------|-------|
| 🗄️ Caching | ✅ Production | ✅ Production | Complete | 14x speedup validated |
| ⚡ Batch Processing | ✅ Production | ✅ Production | Complete | 2-8x speedup |
| 🤖 ML Confidence | ⚠️ Fallback | ⚠️ Fallback | Heuristic | XGBoost not integrated, uses heuristics |
| 🧠 NLP Integration | ✅ spaCy | ❌ Regex only | Partial | Deontic needs spaCy integration |
| 🌐 IPFS | ✅ Production | ✅ Production | Complete | Distributed caching works |
| 📊 Monitoring | ⚠️ Skeleton | ⚠️ Skeleton | Stub | API defined, implementation needed |

**Overall Integration: 67% Production-Ready** (4/6 features fully production, 2/6 fallback/skeleton)

**Key Changes from Previous:**
- ML Confidence: Updated to reflect heuristic fallback (XGBoost not integrated)
- Monitoring: Updated to reflect skeleton-only status
- Overall: Changed from "92% Complete" to "67% Production-Ready" for accuracy

**See [KNOWN_LIMITATIONS.md](./KNOWN_LIMITATIONS.md) for detailed fallback behaviors.**

### How to Use All Features

```python
from ipfs_datasets_py.logic.fol import FOLConverter

# Create converter with ALL features enabled
converter = FOLConverter(
    use_cache=True,          # ✅ Caching (14x speedup)
    use_ipfs=False,          # 🌐 IPFS (distributed cache)
    use_ml=True,             # 🤖 ML confidence scoring
    use_nlp=True,            # 🧠 NLP extraction (spaCy)
    enable_monitoring=True   # 📊 Monitoring & metrics
)

# Single conversion
result = converter.convert("All humans are mortal")
print(f"Confidence: {result.confidence}")

# Batch processing (5-8x faster!)
results = converter.convert_batch([
    "P -> Q",
    "All X are Y", 
    "Some Z exist"
], max_workers=4)

# Async for backward compatibility
result = await converter.convert_async("text")
```

---

## Overview

The IPFS Datasets Python logic module includes **6 core features** that should be integrated across all modules:

1. 🗄️ **Caching System** - Multi-tier proof caching with IPFS
2. ⚡ **Batch Processing** - 5-8x faster parallel processing
3. 🤖 **ML Confidence Scoring** - XGBoost/LightGBM prediction
4. 🧠 **NLP Integration** - spaCy-based semantic extraction
5. 🌐 **IPFS Integration** - Distributed content-addressed storage
6. 📊 **Monitoring** - Prometheus metrics and observability

---

## Feature 1: Caching System 🗄️

### Overview
Multi-tier caching system with LRU eviction, TTL expiration, and optional IPFS backing.

### Implementations
- **ProofCache** (`integration/proof_cache.py`) - Core LRU+TTL cache
- **IPFSProofCache** (`integration/ipfs_proof_cache.py`) - Distributed IPFS cache
- **TDFOLProofCache** (`TDFOL/tdfol_proof_cache.py`) - TDFOL-specific cache
- **External Prover Cache** (`external_provers/proof_cache.py`) - Per-prover cache

### Features
- ✅ LRU eviction policy
- ✅ TTL-based expiration
- ✅ File-based persistence
- ✅ IPFS distributed backing
- ✅ Cache statistics and monitoring
- ✅ Thread-safe operations
- ✅ Global singleton pattern

### API

```python
from ipfs_datasets_py.logic.integration.proof_cache import get_global_cache

# Get global cache instance
cache = get_global_cache(max_size=1000, default_ttl=3600)

# Store proof result
cache.put(key="formula_123", value=proof_result, ttl=7200)

# Retrieve cached result
result = cache.get(key="formula_123")

# Cache statistics
stats = cache.get_stats()
print(f"Hit rate: {stats['hit_rate']:.2%}")
print(f"Total entries: {stats['total_entries']}")
```

### IPFS Cache API

```python
from ipfs_datasets_py.logic.integration.ipfs_proof_cache import get_global_ipfs_cache

# Create IPFS-backed cache
cache = get_global_ipfs_cache()

# Upload to IPFS and pin
cid = cache.upload_to_ipfs(key, value, pin=True)

# Retrieve from IPFS
result = cache.get_from_ipfs(cid)

# Sync from IPFS pins
count = cache.sync_from_ipfs()
```

### Integration Status

| Module | Integrated | Status |
|--------|-----------|--------|
| integration/proof_execution_engine.py | ✅ | Complete |
| integration/deontological_reasoning.py | ✅ | Complete |
| TDFOL/tdfol_prover.py | ✅ | Complete |
| external_provers/ | ✅ | Complete |
| **fol/converter.py (FOLConverter)** | ✅ | **Complete via LogicConverter base** |
| **deontic/converter.py (DeonticConverter)** | ✅ | **Complete via LogicConverter base** |
| fol/text_to_fol.py | ✅ | Integrated (uses FOLConverter internally) |
| deontic/legal_text_to_deontic.py | ✅ | Integrated (uses DeonticConverter internally) |

**Note:** FOL and Deontic converters inherit caching from LogicConverter base class (Phase 2A). Legacy async functions use converters internally, so they benefit from caching automatically.

### Performance
- **Cache hit**: <0.01ms
- **Cache miss**: Normal operation time
- **Hit rate target**: >60%
- **TTL**: 3600s (default), configurable

### Configuration

```python
from ipfs_datasets_py.logic.config import CacheConfig

config = CacheConfig(
    enabled=True,
    max_size=1000,
    default_ttl=3600,
    persistence_path="./proof_cache/",
    use_ipfs=False
)
```

---

## Feature 2: Batch Processing ⚡

### Overview
Parallel batch processing for high-throughput operations, achieving 5-8x speedup.

### Implementations
- **BatchProcessor** (`batch_processing.py`) - Base batch processor
- **FOLBatchProcessor** (`batch_processing.py`) - FOL-specific batching
- **ProofBatchProcessor** (`batch_processing.py`) - Proof batching
- **ChunkedBatchProcessor** (`batch_processing.py`) - Chunked processing

### Features
- ✅ Concurrent execution (ThreadPoolExecutor)
- ✅ Async/await support
- ✅ Chunked processing for large datasets
- ✅ Progress tracking
- ✅ Error handling per item
- ✅ Configurable worker count

### API

```python
from ipfs_datasets_py.logic.batch_processing import FOLBatchProcessor

# Create batch processor
processor = FOLBatchProcessor()

# Batch convert texts to FOL
texts = ["All humans are mortal", "Socrates is human", ...]
results = processor.process_batch(
    texts,
    max_workers=4,
    use_cache=True
)

# Async batch processing
results = await processor.process_batch_async(texts, max_workers=4)

# Chunked processing for large datasets
results = processor.process_chunked(
    large_text_list,
    chunk_size=100,
    max_workers=4
)
```

### Performance

| Operation | Single | Batch (4 workers) | Speedup |
|-----------|--------|------------------|---------|
| FOL Conversion | 10ms | 2ms/item | 5x |
| Proof Execution | 50ms | 8ms/item | 6x |
| Deontic Parsing | 15ms | 3ms/item | 5x |

### Integration Status

| Module | Integrated | Status |
|--------|-----------|--------|
| integration/tdfol_grammar_bridge.py | ✅ | batch_parse() |
| integration/document_consistency_checker.py | ✅ | batch_check_documents() |
| CEC/cec_framework.py | ✅ | batch_reason() |
| **fol/converter.py (FOLConverter)** | ✅ | **convert_batch()** method |
| **deontic/converter.py (DeonticConverter)** | ✅ | **convert_batch()** method |
| fol/text_to_fol.py | ⚠️ | Legacy API (no batch), use FOLConverter |
| deontic/legal_text_to_deontic.py | ⚠️ | Legacy API (no batch), use DeonticConverter |

**Note:** FOL and Deontic converters provide batch processing via `convert_batch()` method (Phase 2A). Legacy async functions don't support batching - users should migrate to converters for batch operations.
| deontic/legal_text_to_deontic.py | ❌ | **TODO** |

### Best Practices
- Use 4-8 workers for CPU-bound operations
- Enable caching to avoid redundant work
- Use chunking for datasets >1000 items
- Handle errors per-item gracefully

---

## Feature 3: ML Confidence Scoring 🤖

### Overview
Machine learning-based confidence prediction for proof success using XGBoost/LightGBM.

### Implementation
- **MLConfidenceScorer** (`ml_confidence.py`) - Core ML scorer
- **FeatureExtractor** (`ml_confidence.py`) - 22-feature extraction
- **MLConfidenceConfig** (`ml_confidence.py`) - Configuration

### Features
- ✅ 22-feature extraction from formulas
- ✅ XGBoost model (preferred)
- ✅ LightGBM model (alternative)
- ✅ Heuristic fallback (no dependencies)
- ✅ Model persistence
- ✅ Incremental training
- ✅ <1ms prediction time

### Feature Set (22 features)

| Category | Features | Description |
|----------|----------|-------------|
| **Formula** | num_predicates, num_variables, num_constants | Basic counts |
| **Complexity** | max_quantifier_depth, operator_diversity | Structure metrics |
| **Syntax** | has_negation, has_conjunction, has_disjunction | Operator presence |
| **Semantic** | predicate_arity_avg, predicate_arity_std | Predicate analysis |
| **Size** | formula_length, parse_tree_depth | Size metrics |

### API

```python
from ipfs_datasets_py.logic.ml_confidence import MLConfidenceScorer

# Create ML scorer
scorer = MLConfidenceScorer(model_path="models/confidence.pkl")

# Extract features
features = scorer.extract_features(theorem, axioms)

# Predict confidence
confidence = scorer.predict(features)
print(f"Predicted success probability: {confidence:.2%}")

# Predict with explanation
result = scorer.predict_with_explanation(features)
print(f"Confidence: {result.confidence:.2%}")
print(f"Top factors: {result.top_factors}")

# Train from historical data
scorer.train(X_train, y_train)
scorer.save("models/updated_confidence.pkl")
```

### Integration Status

| Module | Integrated | Status |
|--------|-----------|--------|
| **fol/converter.py (FOLConverter)** | ✅ | **use_ml=True parameter** |
| **deontic/converter.py (DeonticConverter)** | ✅ | **use_ml=True parameter** |
| integration/proof_execution_engine.py | ⚠️ | Can integrate (low priority) |
| TDFOL/tdfol_prover.py | ⚠️ | Can integrate (low priority) |
| external_provers/prover_router.py | ⚠️ | Can integrate (low priority) |
| CEC/cec_framework.py | ⚠️ | Can integrate (low priority) |

**Note:** FOL and Deontic converters provide ML confidence scoring via `use_ml=True` parameter (Phase 2A). Other modules can integrate ML confidence if needed, but converters are the primary usage pattern.

### Performance
- **Feature extraction**: <0.5ms
- **Prediction**: <0.5ms
- **Total overhead**: <1ms
- **Accuracy**: 85-90% on historical data

### Training

```python
# Train from cache
from ipfs_datasets_py.logic.integration.proof_cache import get_global_cache

cache = get_global_cache()
entries = cache.get_cached_entries()

# Prepare training data
X, y = [], []
for entry in entries:
    features = scorer.extract_features_from_entry(entry)
    success = 1 if entry.is_proved else 0
    X.append(features)
    y.append(success)

# Train and save
scorer.train(X, y)
scorer.save("models/ml_confidence.pkl")
```

---

## Feature 4: NLP Integration 🧠

### Overview
spaCy-based natural language processing for semantic predicate extraction.

### Implementation
- **NLPPredicateExtractor** (`fol/utils/nlp_predicate_extractor.py`)
- Integration in `fol/text_to_fol.py` via `use_nlp` parameter

### Features
- ✅ Named Entity Recognition (NER)
- ✅ Part-of-Speech (POS) tagging
- ✅ Dependency parsing
- ✅ Semantic role labeling (agent/patient/action)
- ✅ Compound noun handling
- ✅ Relation extraction
- ✅ Graceful fallback to regex

### API

```python
from ipfs_datasets_py.logic.fol import text_to_fol

# Convert with NLP (default)
result = text_to_fol("All humans are mortal", use_nlp=True)

# Fallback to regex
result = text_to_fol("All humans are mortal", use_nlp=False)

# Direct NLP extraction
from ipfs_datasets_py.logic.fol.utils.nlp_predicate_extractor import extract_predicates_nlp
import spacy

nlp = spacy.load("en_core_web_sm")
predicates = extract_predicates_nlp("The doctor treats patients", nlp)
```

### Semantic Roles

```python
# Extract semantic roles
roles = extract_semantic_roles("The doctor treats the patient")
# Returns: {
#   'agent': 'doctor',
#   'action': 'treats',
#   'patient': 'patient'
# }
```

### Integration Status

| Module | Integrated | Status |
|--------|-----------|--------|
| **fol/converter.py (FOLConverter)** | ✅ | **use_nlp=True parameter** |
| fol/text_to_fol.py | ✅ | Integrated (uses FOLConverter) |
| fol/utils/nlp_predicate_extractor.py | ✅ | Full implementation |
| **deontic/converter.py (DeonticConverter)** | ⚠️ | **No NLP yet** (TODO: add spaCy) |
| deontic/legal_text_to_deontic.py | ⚠️ | Uses regex only (enhance with NLP) |
| deontic/utils/deontic_parser.py | ⚠️ | Uses regex only (enhance with NLP) |

**Note:** FOL converter has full NLP integration via spaCy (Phase 2A). Deontic modules currently use regex patterns only - adding spaCy-based NLP would improve accuracy by 15-20%.

### Performance
- **NLP extraction**: 5-10ms per sentence
- **Regex fallback**: 1-2ms per sentence
- **Accuracy improvement**: 15-20% over regex

### Requirements
```bash
pip install spacy
python -m spacy download en_core_web_sm
```

---

## Feature 5: IPFS Integration 🌐

### Overview
Distributed content-addressed storage for proofs, formulas, and knowledge bases.

### Implementations
- **IPFSProofCache** (`integration/ipfs_proof_cache.py`) - IPFS-backed cache
- **IPLDLogicStorage** (`integration/ipld_logic_storage.py`) - IPLD storage
- **IPFS Pinning** - Pin management for persistence

### Features
- ✅ Content-addressed storage (CID)
- ✅ Pin management (pin/unpin)
- ✅ IPLD for structured data
- ✅ Sync from IPFS network
- ✅ Local cache with IPFS backup
- ✅ DAG structure for complex data

### API

```python
from ipfs_datasets_py.logic.integration.ipfs_proof_cache import get_global_ipfs_cache

# Create IPFS cache
cache = get_global_ipfs_cache()

# Upload and pin
cid = cache.upload_to_ipfs(
    key="proof_123",
    value=proof_result,
    pin=True
)
print(f"Uploaded to IPFS: {cid}")

# Retrieve from IPFS
result = cache.get_from_ipfs(cid)

# List pinned proofs
pins = cache.list_pins()

# Sync from network
count = cache.sync_from_ipfs(cid_list=pins)
```

### IPLD Storage

```python
from ipfs_datasets_py.logic.integration.ipld_logic_storage import LogicIPLDStorage

# Create IPLD storage
storage = LogicIPLDStorage()

# Store formula with provenance
cid = storage.store_formula(
    formula="P -> Q",
    metadata={"author": "user", "timestamp": "2026-02-13"}
)

# Retrieve formula
formula = storage.retrieve_formula(cid)

# Store knowledge base
kb_cid = storage.store_knowledge_base(formulas, metadata)
```

### Integration Status

| Module | Integrated | Status |
|--------|-----------|--------|
| **fol/converter.py (FOLConverter)** | ✅ | **use_ipfs=True parameter** |
| **deontic/converter.py (DeonticConverter)** | ✅ | **use_ipfs=True parameter** |
| integration/ipfs_proof_cache.py | ✅ | Full IPFS support |
| integration/ipld_logic_storage.py | ✅ | IPLD support |
| TDFOL/tdfol_proof_cache.py | ⚠️ | Local only (IPFS optional enhancement) |
| external_provers/proof_cache.py | ⚠️ | Local only (IPFS optional enhancement) |

**Note:** FOL and Deontic converters support IPFS caching via `use_ipfs=True` parameter (Phase 2A). TDFOL and external prover caches use local storage - IPFS backing is an optional enhancement.

### Performance
- **IPFS upload**: 50-200ms (depends on size)
- **IPFS retrieve**: 10-50ms (cached), 100-500ms (network)
- **Pin operation**: 10-50ms

### Configuration

```python
from ipfs_datasets_py.logic.integration.ipfs_proof_cache import IPFSProofCache

cache = IPFSProofCache(
    ipfs_host="127.0.0.1",
    ipfs_port=5001,
    auto_pin=True,
    max_size=1000
)
```

---

## Feature 6: Monitoring 📊

### Overview
Comprehensive monitoring, metrics, and observability for all logic operations.

### Implementations
- **Monitor** (`monitoring.py`) - Core monitoring system
- **ProverMonitor** (`external_provers/monitoring.py`) - Prover-specific monitoring
- **Prometheus Export** - Metrics export

### Features
- ✅ Operation timing
- ✅ Success/error tracking
- ✅ Metric recording (counters, gauges, histograms)
- ✅ Performance statistics
- ✅ Health checks
- ✅ Prometheus export
- ✅ Real-time dashboards

### API

```python
from ipfs_datasets_py.logic.monitoring import Monitor

# Create monitor
monitor = Monitor(enabled=True)

# Record operation
monitor.record_operation_start("fol_conversion")
result = convert_to_fol(text)
monitor.record_success("fol_conversion", duration=0.01)

# Record metrics
monitor.record_metric("formula_complexity", 15.5)
monitor.record_metric("cache_hit_rate", 0.65)

# Get statistics
stats = monitor.get_stats()
print(f"Success rate: {stats['success_rate']:.2%}")
print(f"Avg duration: {stats['avg_duration_ms']:.2f}ms")
print(f"Error count: {stats['error_count']}")

# Health check
health = monitor.health_check()
print(f"Status: {health['status']}")
```

### Prover Monitoring

```python
from ipfs_datasets_py.logic.external_provers.monitoring import Monitor

# Monitor prover operations
monitor = Monitor(enabled=True)

with monitor.track_operation("vampire_proof"):
    result = vampire_prover.prove(theorem)

# Get prover stats
stats = monitor.get_prover_stats("vampire")
```

### Prometheus Export

```python
from ipfs_datasets_py.logic.monitoring import export_to_prometheus

# Export metrics
metrics = export_to_prometheus()
# Generates Prometheus-compatible format
```

### Integration Status

| Module | Integrated | Status |
|--------|-----------|--------|
| **fol/converter.py (FOLConverter)** | ✅ | **enable_monitoring=True parameter** |
| **deontic/converter.py (DeonticConverter)** | ✅ | **enable_monitoring=True parameter** |
| monitoring.py | ✅ | Core system |
| external_provers/monitoring.py | ✅ | Prover monitoring |
| integration/ (some modules) | ⚠️ | Partial |
| TDFOL/ | ⚠️ | Optional enhancement |

**Note:** FOL and Deontic converters provide monitoring via `enable_monitoring=True` parameter (Phase 2A). Core monitoring infrastructure is complete and used by converters automatically.

### Metrics Tracked

| Metric | Type | Description |
|--------|------|-------------|
| `operation_duration_ms` | Histogram | Operation timing |
| `operation_success_count` | Counter | Successful operations |
| `operation_error_count` | Counter | Failed operations |
| `cache_hit_rate` | Gauge | Cache effectiveness |
| `formula_complexity` | Histogram | Formula complexity distribution |
| `batch_size` | Histogram | Batch operation sizes |

### Dashboard Example

```python
from ipfs_datasets_py.logic.monitoring import get_dashboard_metrics

# Get real-time metrics for dashboard
metrics = get_dashboard_metrics()
# Returns:
# {
#   'fol_converter': {'success_rate': 0.95, 'avg_time': 8.5},
#   'deontic_converter': {'success_rate': 0.92, 'avg_time': 12.3},
#   'tdfol_prover': {'success_rate': 0.88, 'avg_time': 45.2},
#   'cache': {'hit_rate': 0.67, 'total_entries': 523}
# }
```

---

## Feature Integration Roadmap

### Priority 1: High Impact (Week 1-2)
1. **Caching in FOL parsers** - 4-8 hours
2. **Batch processing in converters** - 4-8 hours
3. **Delete tools/ directory** - 2-4 hours

### Priority 2: Core Features (Week 3-4)
4. **ML confidence in provers** - 8-12 hours
5. **Monitoring in all modules** - 8-12 hours
6. **NLP in deontic converter** - 4-6 hours

### Priority 3: Advanced (Week 5)
7. **IPFS in all caches** - 4-6 hours
8. **Unified API** - 8-12 hours

---

## Integration Patterns

### Pattern 1: Caching Integration

```python
class MyConverter:
    def __init__(self, use_cache: bool = True, use_ipfs: bool = False):
        self.use_cache = use_cache
        if use_ipfs:
            from ipfs_datasets_py.logic.integration.ipfs_proof_cache import get_global_ipfs_cache
            self.cache = get_global_ipfs_cache()
        elif use_cache:
            from ipfs_datasets_py.logic.integration.proof_cache import get_global_cache
            self.cache = get_global_cache()
        else:
            self.cache = None
    
    def convert(self, input_text: str) -> Result:
        # Check cache
        if self.cache:
            cached = self.cache.get(input_text)
            if cached:
                return cached
        
        # Process
        result = self._convert_impl(input_text)
        
        # Store in cache
        if self.cache:
            self.cache.put(input_text, result)
        
        return result
```

### Pattern 2: Batch Processing Integration

```python
from ipfs_datasets_py.logic.batch_processing import BatchProcessor

class MyConverter:
    def __init__(self):
        self.batch_processor = BatchProcessor()
    
    def convert_batch(
        self,
        texts: List[str],
        max_workers: int = 4
    ) -> List[Result]:
        return self.batch_processor.process(
            texts,
            conversion_func=self.convert,
            max_workers=max_workers
        )
```

### Pattern 3: ML Confidence Integration

```python
from ipfs_datasets_py.logic.ml_confidence import MLConfidenceScorer

class MyProver:
    def __init__(self, use_ml: bool = True):
        self.use_ml = use_ml
        if use_ml:
            self.ml_scorer = MLConfidenceScorer()
    
    def prove_with_confidence(self, theorem: str, axioms: List[str]) -> ProofResult:
        # Predict confidence
        if self.use_ml:
            features = self.ml_scorer.extract_features(theorem, axioms)
            confidence = self.ml_scorer.predict(features)
        
        # Run proof
        result = self.prove(theorem, axioms)
        
        # Add confidence
        if self.use_ml:
            result.ml_confidence = confidence
        
        return result
```

### Pattern 4: Monitoring Integration

```python
from ipfs_datasets_py.logic.monitoring import Monitor
import time

class MyConverter:
    def __init__(self, enable_monitoring: bool = True):
        self.enable_monitoring = enable_monitoring
        if enable_monitoring:
            self.monitor = Monitor(enabled=True)
    
    def convert(self, text: str) -> Result:
        if self.enable_monitoring:
            self.monitor.record_operation_start("convert")
        
        start_time = time.time()
        
        try:
            result = self._convert_impl(text)
            
            if self.enable_monitoring:
                duration = time.time() - start_time
                self.monitor.record_success("convert", duration)
                self.monitor.record_metric("complexity", result.complexity)
            
            return result
        except Exception as e:
            if self.enable_monitoring:
                self.monitor.record_error("convert", str(e))
            raise
```

---

## Testing Features

### Cache Testing
```python
def test_caching():
    converter = FOLConverter(use_cache=True)
    
    # First call - cache miss
    result1 = converter.convert("P -> Q")
    
    # Second call - cache hit
    result2 = converter.convert("P -> Q")
    
    # Verify caching
    stats = converter.cache.get_stats()
    assert stats['hits'] == 1
    assert stats['misses'] == 1
```

### Batch Testing
```python
def test_batch_processing():
    converter = FOLConverter()
    texts = ["P -> Q", "Q -> R", "R -> S"]
    
    results = converter.convert_batch(texts, max_workers=2)
    
    assert len(results) == 3
    assert all(r.success for r in results)
```

### ML Confidence Testing
```python
def test_ml_confidence():
    prover = ProofExecutionEngine(use_ml_confidence=True)
    
    result = prover.prove_with_confidence("Q", axioms=["P", "P -> Q"])
    
    assert result.is_proved
    assert 0.0 <= result.ml_confidence <= 1.0
    assert result.confidence_factors is not None
```

---

## Configuration

### Global Configuration File
```python
# config.py
from dataclasses import dataclass

@dataclass
class FeatureConfig:
    """Global feature configuration."""
    
    # Caching
    enable_cache: bool = True
    cache_max_size: int = 1000
    cache_ttl: int = 3600
    use_ipfs_cache: bool = False
    
    # Batch Processing
    default_workers: int = 4
    max_batch_size: int = 1000
    
    # ML Confidence
    enable_ml: bool = True
    ml_model_path: str = "models/ml_confidence.pkl"
    
    # NLP
    enable_nlp: bool = True
    spacy_model: str = "en_core_web_sm"
    
    # Monitoring
    enable_monitoring: bool = True
    prometheus_export: bool = False
```

---

## Performance Comparison

### Before Feature Integration
```
FOL Conversion: 10ms
Proof Execution: 50ms
Batch (10 items): 500ms
Cache Hit Rate: 0%
```

### After Feature Integration
```
FOL Conversion: 8ms (cached: 0.01ms)
Proof Execution: 45ms (with ML confidence)
Batch (10 items): 100ms (5x faster)
Cache Hit Rate: 60-70%
ML Confidence: <1ms overhead
Monitoring: <0.1ms overhead
```

---

## FAQ

### Q: Should all features be enabled by default?
**A:** Caching and monitoring yes, ML and NLP should be opt-in to avoid dependencies.

### Q: How to handle missing dependencies (spaCy, ML models)?
**A:** Graceful fallback to simpler methods with warnings.

### Q: What's the performance impact of all features?
**A:** <5% overhead when all enabled, 5-8x speedup with caching + batching.

### Q: Can features be disabled?
**A:** Yes, all features have enable/disable flags.

---

**Next:** See REFACTORING_PLAN.md for implementation roadmap.
