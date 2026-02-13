# Logic Modules - Architecture Guide

This document describes the architecture and design of the logic modules in IPFS Datasets Python.

## Table of Contents

1. [Overview](#overview)
2. [Module Structure](#module-structure)
3. [Component Architecture](#component-architecture)
4. [Data Flow](#data-flow)
5. [Design Patterns](#design-patterns)
6. [Performance Considerations](#performance-considerations)
7. [Extension Points](#extension-points)

---

## Overview

The logic modules provide a comprehensive system for:
- Converting natural language to First-Order Logic (FOL)
- Processing deontic logic (obligations, permissions, prohibitions)
- Executing formal proofs using multiple theorem provers
- Optimizing performance through caching and batch processing
- Providing ML-based quality estimation

### Key Components

```
logic/
├── fol/                    # First-Order Logic conversion
│   ├── text_to_fol.py     # Main conversion entry point
│   └── utils/             # Extraction and parsing utilities
│       ├── predicate_extractor.py      # Regex-based extraction
│       ├── nlp_predicate_extractor.py  # NLP-enhanced extraction
│       └── fol_parser.py              # Formula building
├── deontic/               # Deontic logic
│   └── utils/
│       └── deontic_parser.py  # Conflict detection
├── integration/           # Core integration layer
│   ├── logic_verification.py       # Consistency checking
│   ├── deontological_reasoning.py  # Norm reasoning
│   ├── proof_execution_engine.py   # Proof execution
│   ├── proof_cache.py             # Performance caching
│   └── interactive_fol_constructor.py
├── benchmarks.py          # Performance measurement
├── batch_processing.py    # Scalability
└── ml_confidence.py       # ML-based scoring
```

---

## Module Structure

### Layer Architecture

```
┌─────────────────────────────────────────┐
│         Application Layer               │
│   (User Code, CLI, API Endpoints)       │
└─────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│         High-Level API Layer            │
│  • convert_text_to_fol()                │
│  • detect_normative_conflicts()         │
│  • prove_deontic_formula()              │
└─────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│      Processing & Optimization          │
│  • Batch Processing                     │
│  • ML Confidence Scoring                │
│  • Performance Benchmarking             │
└─────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│         Core Logic Layer                │
│  • FOL Conversion                       │
│  • Deontic Logic                        │
│  • Proof Execution                      │
│  • Logic Verification                   │
└─────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│      Extraction & Parsing Layer         │
│  • Predicate Extraction (Regex/NLP)    │
│  • Quantifier Parsing                   │
│  • Operator Parsing                     │
│  • Formula Building                     │
└─────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│          Storage & Cache Layer          │
│  • Proof Cache (LRU)                    │
│  • Model Persistence                    │
│  • File-based Storage                   │
└─────────────────────────────────────────┘
```

---

## Component Architecture

### 1. FOL Conversion Pipeline

```
Natural Language Text
        ↓
┌───────────────────┐
│  Text Processing  │
│  • Normalization  │
│  • Sentence Split │
└───────────────────┘
        ↓
┌───────────────────┐     ┌─────────────────┐
│ Predicate Extract │────→│   NLP Option    │
│  • Regex (Fast)   │     │ • spaCy (Better)│
│  • Nouns/Verbs    │     │ • NER, POS, Dep │
└───────────────────┘     └─────────────────┘
        ↓
┌───────────────────┐
│ Quantifier Parse  │
│  • ∀ (Universal)  │
│  • ∃ (Existential)│
└───────────────────┘
        ↓
┌───────────────────┐
│ Operator Parse    │
│  • ∧ ∨ → ↔ ¬     │
└───────────────────┘
        ↓
┌───────────────────┐
│ Formula Builder   │
│  • Construct FOL  │
│  • Validate       │
└───────────────────┘
        ↓
┌───────────────────┐     ┌─────────────────┐
│Confidence Scoring │────→│   ML Option     │
│  • Heuristic      │     │ • XGBoost Model │
│  • Feature-based  │     │ • 22 Features   │
└───────────────────┘     └─────────────────┘
        ↓
    FOL Formula
```

### 2. Proof Execution with Caching

```
Deontic Formula
        ↓
┌───────────────────┐
│   Cache Lookup    │──→ Hit? ──→ Return Cached Result (Fast)
└───────────────────┘
        ↓ Miss
┌───────────────────┐
│ Rate Limiting     │
│ & Validation      │
└───────────────────┘
        ↓
┌───────────────────┐
│Formula Translation│
│  • Z3/CVC5: SMT   │
│  • Lean: Lean4    │
│  • Coq: Gallina   │
└───────────────────┘
        ↓
┌───────────────────┐
│ Proof Execution   │
│  • Subprocess     │
│  • Timeout        │
│  • Result Parse   │
└───────────────────┘
        ↓
┌───────────────────┐
│   Cache Store     │
│  • LRU Eviction   │
│  • TTL Tracking   │
└───────────────────┘
        ↓
    Proof Result
```

### 3. Batch Processing Architecture

```
Large Dataset (1000s items)
        ↓
┌───────────────────────────┐
│  ChunkedBatchProcessor    │
│  • Memory-efficient       │
│  • Chunk size: 100        │
└───────────────────────────┘
        ↓
┌───────────────────────────┐
│    Async Semaphore        │
│  • Concurrency: 10        │
│  • Rate limiting          │
└───────────────────────────┘
        ↓
┌───────────────────────────┐
│   asyncio.gather()        │
│  • Parallel execution     │
│  • Error handling         │
└───────────────────────────┘
        ↓
┌───────────────────────────┐
│    Result Aggregation     │
│  • Success/Fail counts    │
│  • Performance metrics    │
└───────────────────────────┘
        ↓
    Batch Result
    (5-8x faster)
```

---

## Data Flow

### End-to-End Flow

```
┌─────────────┐
│   User      │
│   Input     │
└──────┬──────┘
       │
       ↓
┌─────────────────────┐
│  convert_text_to_fol│
│  (High-level API)   │
└──────┬──────────────┘
       │
       ├──→ NLP Extraction (if enabled)
       │    • spaCy processing
       │    • Semantic roles
       │
       ├──→ Regex Extraction (fallback)
       │    • Pattern matching
       │    • Quick processing
       │
       ↓
┌──────────────────────┐
│  Formula Building    │
└──────┬───────────────┘
       │
       ├──→ ML Confidence (if model loaded)
       │    • Feature extraction
       │    • Prediction
       │
       ├──→ Heuristic (fallback)
       │    • Rule-based scoring
       │
       ↓
┌──────────────────────┐
│   Validation         │
│   • Syntax check     │
│   • Confidence       │
└──────┬───────────────┘
       │
       ↓
┌──────────────────────┐
│   Result Object      │
│   • FOL formulas     │
│   • Metadata         │
│   • Statistics       │
└──────────────────────┘
```

### Proof Execution Flow

```
┌─────────────┐
│   Formula   │
└──────┬──────┘
       │
       ↓
┌──────────────────────┐
│  Cache Check         │
└──────┬───────────────┘
       │
       ├──→ Hit: Return immediately (<0.01ms)
       │
       ↓ Miss
┌──────────────────────┐
│  Security Checks     │
│  • Rate limit        │
│  • Validation        │
└──────┬───────────────┘
       │
       ↓
┌──────────────────────┐
│  Translation         │
│  • SMT-LIB2          │
│  • Lean4/Coq         │
└──────┬───────────────┘
       │
       ↓
┌──────────────────────┐
│  Subprocess          │
│  • z3/cvc5/lean/coq  │
│  • Timeout: 60s      │
└──────┬───────────────┘
       │
       ↓
┌──────────────────────┐
│  Result Parsing      │
└──────┬───────────────┘
       │
       ↓
┌──────────────────────┐
│  Cache Storage       │
│  • LRU eviction      │
│  • TTL: 1 hour       │
└──────┬───────────────┘
       │
       ↓
┌──────────────────────┐
│  Proof Result        │
└──────────────────────┘
```

---

## Design Patterns

### 1. Strategy Pattern

**Predicate Extraction**: NLP vs Regex

```python
# Strategy interface
def extract_predicates(text, use_nlp=True):
    if use_nlp and spacy_available:
        return nlp_strategy(text)
    else:
        return regex_strategy(text)
```

**Benefits:**
- Runtime selection of extraction method
- Graceful fallback
- Easy to add new strategies

### 2. Singleton Pattern

**Global Cache**: Single cache instance across application

```python
_global_cache = None

def get_global_cache():
    global _global_cache
    if _global_cache is None:
        _global_cache = ProofCache()
    return _global_cache
```

**Benefits:**
- Shared cache state
- Memory efficiency
- Consistent statistics

### 3. Factory Pattern

**Proof Engine Creation**: Different prover instances

```python
def create_proof_engine(prover_type):
    if prover_type == "z3":
        return Z3ProofEngine()
    elif prover_type == "lean":
        return LeanProofEngine()
    # ...
```

### 4. Decorator Pattern

**Caching Decorator**: Transparent caching

```python
@with_caching
def prove_formula(formula, prover):
    # Actual proof logic
    pass
```

### 5. Observer Pattern

**Benchmark Callbacks**: Track progress

```python
class BenchmarkObserver:
    def on_iteration_complete(self, iteration, time):
        # Update progress
        pass
```

---

## Performance Considerations

### 1. Caching Strategy

**LRU Cache Implementation:**
```
┌────────────────────────────────┐
│  OrderedDict (Python built-in) │
│  • O(1) lookup                 │
│  • O(1) insertion              │
│  • O(1) eviction               │
└────────────────────────────────┘
```

**Cache Key Design:**
```
key = SHA256(formula_string + prover_name)
```

**Performance Impact:**
- Cache hit: <0.01ms
- Cache miss + proof: ~50-200ms
- Hit rate: 60-80% typical
- Memory: ~1KB per entry

### 2. Batch Processing Optimization

**Async Concurrency:**
```python
async def process_batch(items):
    semaphore = asyncio.Semaphore(10)  # Limit concurrency
    
    async def process_one(item):
        async with semaphore:
            return await process_item(item)
    
    return await asyncio.gather(*[process_one(i) for i in items])
```

**Performance Gains:**
- Sequential: 10 items/sec
- Async (10 workers): 60 items/sec
- **6x improvement**

### 3. Memory Optimization

**Chunked Processing:**
```python
# Instead of loading all data:
# results = [process(item) for item in large_dataset]  # OOM risk

# Use chunking:
for chunk in chunks(large_dataset, size=100):
    chunk_results = await process_batch(chunk)
    yield chunk_results  # Process incrementally
```

### 4. ML Model Optimization

**Feature Extraction Cache:**
```python
@lru_cache(maxsize=1000)
def extract_features(sentence, formula):
    # Expensive feature computation
    return features
```

**Model Selection:**
- XGBoost: Faster training, better for tabular data
- LightGBM: Lower memory, faster prediction
- Fallback: Heuristic (no dependencies)

---

## Extension Points

### 1. Adding New Provers

```python
# In proof_execution_engine.py
def _execute_myprover_proof(self, formula, translation):
    """Add custom prover support."""
    # 1. Translate to prover format
    # 2. Execute subprocess
    # 3. Parse result
    # 4. Return ProofResult
    pass
```

### 2. Custom Extraction Methods

```python
# In fol/utils/
def custom_predicate_extractor(text):
    """Add domain-specific extraction."""
    predicates = {
        "nouns": [...],
        "custom_category": [...]  # Your category
    }
    return predicates
```

### 3. Additional Confidence Features

```python
# In ml_confidence.py
class CustomFeatureExtractor(FeatureExtractor):
    def extract_features(self, sentence, formula, ...):
        base_features = super().extract_features(...)
        
        # Add your custom features
        custom_features = [
            my_feature_1(sentence),
            my_feature_2(formula),
        ]
        
        return np.concatenate([base_features, custom_features])
```

### 4. Custom Batch Processors

```python
# In batch_processing.py
class CustomBatchProcessor(BatchProcessor):
    async def process_custom(self, items, **kwargs):
        """Domain-specific batch processing."""
        # Your custom logic
        pass
```

---

## Best Practices

### 1. Error Handling

```python
try:
    result = await convert_text_to_fol(text, use_nlp=True)
except Exception as e:
    # Fallback to regex
    result = await convert_text_to_fol(text, use_nlp=False)
```

### 2. Resource Management

```python
# Use context managers for engines
with ProofExecutionEngine() as engine:
    result = engine.prove_formula(formula)
# Engine cleanup automatic
```

### 3. Performance Monitoring

```python
from ipfs_datasets_py.logic.benchmarks import PerformanceBenchmark

# Regular performance checks
benchmark = PerformanceBenchmark()
result = benchmark.benchmark(name="Production", func=my_function)

if result.mean_time > threshold:
    logger.warning("Performance degradation detected")
```

### 4. Graceful Degradation

```python
# Always provide fallbacks
if not SPACY_AVAILABLE:
    use_nlp = False

if not model.is_trained:
    use_heuristic_confidence = True
```

---

## Security Considerations

### 1. Input Validation

- Formula complexity limits
- Timeout enforcement (60s default)
- Rate limiting (100 calls/minute)

### 2. Subprocess Safety

- No shell=True (command injection protection)
- Sandboxed execution
- Resource limits

### 3. Cache Security

- No sensitive data in cache keys
- Automatic cleanup of expired entries
- Memory limits enforced

---

## Testing Architecture

```
tests/
├── unit_tests/
│   ├── logic/fol/           # FOL unit tests
│   ├── logic/deontic/       # Deontic tests
│   └── logic/integration/   # Integration tests
├── integration/             # End-to-end tests
└── performance/             # Benchmark tests
```

**Test Coverage:**
- Unit tests: 245 tests
- Integration tests: Included
- Performance tests: Benchmarks
- Coverage: 75%+

---

## Deployment

### 1. Dependencies

**Required:**
```bash
pip install ipfs_datasets_py
```

**Optional (NLP):**
```bash
pip install spacy
python -m spacy download en_core_web_sm
```

**Optional (ML):**
```bash
pip install xgboost lightgbm
```

### 2. Configuration

```python
# config.py
PROOF_CACHE_SIZE = 1000
PROOF_CACHE_TTL = 3600
BATCH_CONCURRENCY = 10
USE_NLP = True  # If spaCy available
```

### 3. Monitoring

```python
# Monitor cache performance
stats = cache.get_statistics()
if stats['hit_rate'] < 0.5:
    logger.warning("Low cache hit rate")

# Monitor throughput
if result.items_per_second < 20:
    logger.warning("Low throughput")
```

---

## Future Enhancements

1. **IPFS Backing**: Distributed cache storage
2. **GPU Acceleration**: For ML inference
3. **Additional Provers**: Vampire, E prover integration
4. **Advanced NLP**: Transformer-based models
5. **Distributed Processing**: Multi-node batch processing

---

## References

- [FOL Specification](https://en.wikipedia.org/wiki/First-order_logic)
- [Deontic Logic](https://plato.stanford.edu/entries/logic-deontic/)
- [spaCy Documentation](https://spacy.io/)
- [XGBoost Documentation](https://xgboost.readthedocs.io/)
