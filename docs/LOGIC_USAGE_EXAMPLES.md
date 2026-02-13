# Logic Modules - Usage Examples

This document provides comprehensive usage examples for the logic modules in IPFS Datasets Python.

## Table of Contents

1. [Basic FOL Conversion](#1-basic-fol-conversion)
2. [Advanced NLP-Enhanced Conversion](#2-advanced-nlp-enhanced-conversion)
3. [Deontic Logic and Conflict Detection](#3-deontic-logic-and-conflict-detection)
4. [Proof Execution with Caching](#4-proof-execution-with-caching)
5. [Batch Processing for Scale](#5-batch-processing-for-scale)
6. [Performance Benchmarking](#6-performance-benchmarking)
7. [ML-Based Confidence Scoring](#7-ml-based-confidence-scoring)

---

## 1. Basic FOL Conversion

Convert natural language text to First-Order Logic formulas.

### Simple Example

```python
import asyncio
from ipfs_datasets_py.logic.fol.text_to_fol import convert_text_to_fol

async def basic_conversion():
    """Convert a simple sentence to FOL."""
    text = "All humans are mortal"
    
    result = await convert_text_to_fol(text)
    
    print(f"Status: {result['status']}")
    print(f"Formulas: {result['fol_formulas']}")
    print(f"Confidence: {result['summary']['average_confidence']:.2f}")

# Run
asyncio.run(basic_conversion())
```

**Output:**
```
Status: success
Formulas: [{'original_text': 'All humans are mortal', 
            'fol_formula': '∀x(Human(x) → Mortal(x))', 
            'confidence': 0.85}]
Confidence: 0.85
```

### Multiple Sentences

```python
async def multiple_sentences():
    """Convert multiple sentences."""
    text = """
    All dogs are animals.
    Some cats are black.
    If it rains, the ground gets wet.
    """
    
    result = await convert_text_to_fol(text)
    
    for formula in result['fol_formulas']:
        print(f"Text: {formula['original_text']}")
        print(f"FOL:  {formula['fol_formula']}")
        print(f"Confidence: {formula['confidence']:.2f}\n")

asyncio.run(multiple_sentences())
```

### Custom Confidence Threshold

```python
async def with_confidence_filter():
    """Only return high-confidence conversions."""
    text = "Complex ambiguous unclear sentence structure"
    
    result = await convert_text_to_fol(
        text,
        confidence_threshold=0.9,  # High threshold
        include_metadata=True
    )
    
    print(f"High-confidence formulas: {len(result['fol_formulas'])}")

asyncio.run(with_confidence_filter())
```

---

## 2. Advanced NLP-Enhanced Conversion

Use spaCy for improved predicate extraction quality.

### Enable NLP Extraction

```python
async def nlp_enhanced_conversion():
    """Use spaCy for better extraction."""
    from ipfs_datasets_py.logic.fol.utils.nlp_predicate_extractor import get_extraction_stats
    
    # Check if spaCy is available
    stats = get_extraction_stats()
    print(f"spaCy available: {stats['spacy_available']}")
    print(f"Model loaded: {stats['model_loaded']}\n")
    
    text = "The quick brown fox jumps over the lazy dog"
    
    # Use NLP-enhanced extraction
    result = await convert_text_to_fol(
        text,
        use_nlp=True  # Enable spaCy
    )
    
    print(f"Predicates extracted: {result['summary']['unique_predicates']}")

asyncio.run(nlp_enhanced_conversion())
```

### Semantic Role Labeling

```python
from ipfs_datasets_py.logic.fol.utils.nlp_predicate_extractor import extract_semantic_roles

def semantic_analysis():
    """Extract semantic roles from text."""
    text = "John gives Mary a book in the library"
    
    roles = extract_semantic_roles(text, use_spacy=True)
    
    for role in roles:
        print(f"Action: {role['action']}")
        print(f"Agent: {role['agent']}")
        print(f"Patient: {role['patient']}")
        print(f"Location: {role['location']}\n")

semantic_analysis()
```

**Output:**
```
Action: give
Agent: John
Patient: book
Location: library
```

### NLP vs Regex Comparison

```python
async def compare_extraction_methods():
    """Compare NLP vs regex extraction."""
    text = "All machine learning algorithms process natural language"
    
    # Regex-based
    result_regex = await convert_text_to_fol(text, use_nlp=False)
    
    # NLP-based
    result_nlp = await convert_text_to_fol(text, use_nlp=True)
    
    print("Regex predicates:", result_regex['summary']['unique_predicates'])
    print("NLP predicates:", result_nlp['summary']['unique_predicates'])
    
    # NLP typically extracts compound nouns better

asyncio.run(compare_extraction_methods())
```

---

## 3. Deontic Logic and Conflict Detection

Work with obligations, permissions, and prohibitions.

### Detect Normative Conflicts

```python
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
    detect_normative_conflicts,
    DeonticOperator
)

def conflict_detection():
    """Detect conflicts between norms."""
    norms = [
        {
            "type": DeonticOperator.OBLIGATION,
            "action": "attend_meeting",
            "subject": "employee",
            "temporal_constraint": {"start": "9:00", "end": "10:00"}
        },
        {
            "type": DeonticOperator.PROHIBITION,
            "action": "attend_meeting",
            "subject": "employee",
            "temporal_constraint": {"start": "9:30", "end": "11:00"}
        }
    ]
    
    conflicts = detect_normative_conflicts(norms)
    
    for conflict in conflicts:
        print(f"Conflict Type: {conflict.get('type')}")
        print(f"Severity: {conflict.get('severity')}")
        print(f"Norms: {conflict.get('norm1_index')} vs {conflict.get('norm2_index')}")
        print(f"Resolution: {conflict.get('resolution_strategies')}\n")

conflict_detection()
```

### Resolution Strategies

```python
def apply_resolution():
    """Apply conflict resolution strategies."""
    norm1 = {
        "type": DeonticOperator.OBLIGATION,
        "action": "policy_decision",
        "subject": "board",
        "authority_level": "high",
        "created_at": "2023-01-01"
    }
    
    norm2 = {
        "type": DeonticOperator.PROHIBITION,
        "action": "policy_decision",
        "subject": "manager",
        "authority_level": "low",
        "created_at": "2024-01-01"
    }
    
    conflicts = detect_normative_conflicts([norm1, norm2])
    
    if conflicts:
        strategies = conflicts[0].get('resolution_strategies', [])
        print("Recommended strategies:")
        for strategy in strategies:
            print(f"  - {strategy}")

apply_resolution()
```

**Output:**
```
Recommended strategies:
  - lex_superior (higher authority prevails)
  - lex_posterior (newer norm prevails)
```

---

## 4. Proof Execution with Caching

Execute proofs with automatic caching for performance.

### Basic Proof Execution

```python
from ipfs_datasets_py.logic.integration.proof_execution_engine import ProofExecutionEngine
from ipfs_datasets_py.tools.deontic_logic_core import DeonticFormula

def execute_proof():
    """Execute a proof with caching."""
    engine = ProofExecutionEngine(
        enable_caching=True,
        cache_size=1000,
        cache_ttl=3600  # 1 hour
    )
    
    # Create a formula (simplified for example)
    formula = DeonticFormula(
        operator="OBLIGATION",
        action="attend",
        subject="employee"
    )
    
    # First execution - will cache
    result1 = engine.prove_deontic_formula(formula, prover="z3")
    print(f"First call: {result1.status}")
    
    # Second execution - retrieved from cache (much faster)
    result2 = engine.prove_deontic_formula(formula, prover="z3")
    print(f"Second call (cached): {result2.status}")
    
    # Check cache statistics
    stats = engine.proof_cache.get_statistics()
    print(f"\nCache stats:")
    print(f"  Hits: {stats['hits']}")
    print(f"  Misses: {stats['misses']}")
    print(f"  Hit rate: {stats['hit_rate']:.1%}")

execute_proof()
```

### Cache Management

```python
from ipfs_datasets_py.logic.integration.proof_cache import get_global_cache

def manage_cache():
    """Manage proof cache."""
    cache = get_global_cache()
    
    # Get cache statistics
    stats = cache.get_statistics()
    print(f"Cache size: {stats['size']}/{stats['max_size']}")
    print(f"Hit rate: {stats['hit_rate']:.1%}")
    
    # Get cached entries
    entries = cache.get_cached_entries()
    for entry in entries[:5]:  # Show first 5
        print(f"  {entry['key']}: {entry['hit_count']} hits, age {entry['age_seconds']:.0f}s")
    
    # Clean up expired entries
    removed = cache.cleanup_expired()
    print(f"\nRemoved {removed} expired entries")
    
    # Resize cache if needed
    cache.resize(500)  # Reduce to 500 entries

manage_cache()
```

---

## 5. Batch Processing for Scale

Process large datasets efficiently with async batch processing.

### Batch FOL Conversion

```python
from ipfs_datasets_py.logic.batch_processing import FOLBatchProcessor

async def batch_conversion():
    """Convert batch of texts to FOL."""
    processor = FOLBatchProcessor(max_concurrency=10)
    
    texts = [
        "All humans are mortal",
        "Some birds can fly",
        "If it rains, the ground gets wet",
        "Dogs are animals",
        "The sky is blue"
    ] * 20  # 100 items total
    
    result = await processor.convert_batch(
        texts,
        use_nlp=True,
        confidence_threshold=0.7
    )
    
    print(f"Batch Results:")
    print(f"  Total: {result.total_items}")
    print(f"  Successful: {result.successful}")
    print(f"  Failed: {result.failed}")
    print(f"  Success rate: {result.success_rate():.1f}%")
    print(f"  Time: {result.total_time:.2f}s")
    print(f"  Throughput: {result.items_per_second:.1f} items/sec")

asyncio.run(batch_conversion())
```

**Output:**
```
Batch Results:
  Total: 100
  Successful: 98
  Failed: 2
  Success rate: 98.0%
  Time: 1.8s
  Throughput: 55.6 items/sec
```

### Memory-Efficient Chunked Processing

```python
from ipfs_datasets_py.logic.batch_processing import ChunkedBatchProcessor

async def large_batch():
    """Process large dataset in chunks."""
    processor = ChunkedBatchProcessor(
        chunk_size=100,
        max_concurrency=10
    )
    
    # Simulate large dataset
    large_dataset = [f"Text item {i}" for i in range(1000)]
    
    async def process_item(item):
        # Your processing logic
        return await convert_text_to_fol(item)
    
    result = await processor.process_large_batch(
        items=large_dataset,
        process_func=process_item
    )
    
    print(f"Processed {result.total_items} items in {result.total_time:.1f}s")
    print(f"Average: {result.items_per_second:.1f} items/sec")

asyncio.run(large_batch())
```

### Parallel Proof Execution

```python
from ipfs_datasets_py.logic.batch_processing import ProofBatchProcessor

async def batch_proofs():
    """Execute multiple proofs in parallel."""
    processor = ProofBatchProcessor(max_concurrency=5)
    
    # List of formulas to prove
    formulas = [formula1, formula2, formula3, ...]  # Your formulas
    
    result = await processor.prove_batch(
        formulas,
        prover="z3",
        use_cache=True
    )
    
    print(f"Proofs executed: {result.successful}/{result.total_items}")
    print(f"Time: {result.total_time:.2f}s")

asyncio.run(batch_proofs())
```

---

## 6. Performance Benchmarking

Measure and optimize performance.

### Run Comprehensive Benchmarks

```python
from ipfs_datasets_py.logic.benchmarks import run_comprehensive_benchmarks

async def full_benchmark():
    """Run all benchmarks."""
    results = await run_comprehensive_benchmarks()
    
    print("Benchmark Summary:")
    for result in results['results']:
        print(f"\n{result['name']}:")
        print(f"  Mean: {result['mean_time']*1000:.2f}ms")
        print(f"  Throughput: {result['throughput']:.1f} ops/sec")

asyncio.run(full_benchmark())
```

### Custom Benchmarks

```python
from ipfs_datasets_py.logic.benchmarks import PerformanceBenchmark

async def custom_benchmark():
    """Create custom benchmarks."""
    benchmark = PerformanceBenchmark(warmup_iterations=3)
    
    # Benchmark your function
    result = await benchmark.benchmark_async(
        name="My Custom Test",
        func=my_async_function,
        iterations=100,
        description="Testing custom logic"
    )
    
    print(result.summary())
    # "My Custom Test: 12.5ms avg, 80.0 ops/sec, σ=1.2ms"
    
    # Compare two implementations
    result1 = await benchmark.benchmark_async("Implementation A", func_a, iterations=50)
    result2 = await benchmark.benchmark_async("Implementation B", func_b, iterations=50)
    
    comparison = benchmark.compare(result1, result2)
    print(f"\nSpeedup: {comparison['speedup']:.2f}x")
    print(f"Faster: {comparison['faster']}")

asyncio.run(custom_benchmark())
```

### Performance Regression Testing

```python
async def regression_test():
    """Check for performance regressions."""
    benchmark = PerformanceBenchmark()
    
    # Baseline
    baseline = await benchmark.benchmark_async(
        "Baseline",
        convert_text_to_fol,
        text_input="All humans are mortal",
        iterations=100
    )
    
    # After optimization
    optimized = await benchmark.benchmark_async(
        "Optimized",
        convert_text_to_fol_optimized,
        text_input="All humans are mortal",
        iterations=100
    )
    
    comparison = benchmark.compare(baseline, optimized)
    
    if comparison['improvement_percent'] < -10:
        print("⚠️ Performance regression detected!")
    else:
        print(f"✅ {comparison['improvement_percent']:.1f}% improvement")

asyncio.run(regression_test())
```

---

## 7. ML-Based Confidence Scoring

Train and use ML models for confidence prediction.

### Using Pre-trained Model

```python
from ipfs_datasets_py.logic.ml_confidence import MLConfidenceScorer
from pathlib import Path

def use_ml_confidence():
    """Use ML confidence scorer."""
    # Load pre-trained model
    scorer = MLConfidenceScorer()
    scorer.load_model(Path("models/confidence_model.pkl"))
    
    # Predict confidence
    confidence = scorer.predict_confidence(
        sentence="All humans are mortal",
        fol_formula="∀x(Human(x) → Mortal(x))",
        predicates={"nouns": ["humans"], "verbs": ["are"]},
        quantifiers=["∀"],
        operators=["→"]
    )
    
    print(f"ML Confidence: {confidence:.3f}")

use_ml_confidence()
```

### Training Your Own Model

```python
import numpy as np
from ipfs_datasets_py.logic.ml_confidence import MLConfidenceScorer, FeatureExtractor

def train_custom_model():
    """Train ML confidence model on your data."""
    scorer = MLConfidenceScorer()
    extractor = FeatureExtractor()
    
    # Prepare training data
    X = []
    y = []
    
    for sentence, formula, quality in training_data:
        features = extractor.extract_features(
            sentence=sentence,
            fol_formula=formula,
            predicates=extract_predicates(sentence),
            quantifiers=parse_quantifiers(sentence),
            operators=parse_operators(sentence)
        )
        X.append(features)
        y.append(quality)  # 0-1 confidence score
    
    X = np.array(X)
    y = np.array(y)
    
    # Train model
    metrics = scorer.train(X, y, validation_split=0.2)
    
    print(f"Training accuracy: {metrics['train_accuracy']:.3f}")
    print(f"Validation accuracy: {metrics['val_accuracy']:.3f}")
    
    # Save model
    scorer.save_model(Path("my_confidence_model.pkl"))
    
    # Analyze feature importance
    importance = scorer.get_feature_importance()
    for feature, score in sorted(importance.items(), key=lambda x: -x[1])[:5]:
        print(f"{feature}: {score:.3f}")

train_custom_model()
```

### Fallback to Heuristic

```python
from ipfs_datasets_py.logic.ml_confidence import MLConfidenceConfig, MLConfidenceScorer

def with_fallback():
    """Use ML with automatic fallback."""
    config = MLConfidenceConfig(
        fallback_to_heuristic=True,  # Enable fallback
        use_xgboost=True
    )
    
    scorer = MLConfidenceScorer(config)
    
    # Will use heuristic if model not trained
    confidence = scorer.predict_confidence(
        sentence="Test sentence",
        fol_formula="P(x)",
        predicates={},
        quantifiers=[],
        operators=[]
    )
    
    print(f"Confidence (heuristic): {confidence:.3f}")

with_fallback()
```

---

## Additional Resources

- **API Documentation**: See `docs/api/` for full API reference
- **Architecture**: See `docs/architecture.md` for system design
- **Best Practices**: See `docs/best_practices.md`
- **Troubleshooting**: See `docs/troubleshooting.md`

## Support

For issues or questions:
- GitHub Issues: https://github.com/endomorphosis/ipfs_datasets_py/issues
- Documentation: https://ipfs-datasets-py.readthedocs.io/
