# Logic Modules - Best Practices & Troubleshooting

This guide covers best practices and solutions to common problems.

## Table of Contents

1. [Best Practices](#best-practices)
2. [Performance Optimization](#performance-optimization)
3. [Common Issues](#common-issues)
4. [Troubleshooting](#troubleshooting)
5. [FAQ](#faq)

---

## Best Practices

### 1. Configuration Management

**DO:** Use configuration objects
```python
# ✅ Good
config = LogicConfig(
    use_nlp=True,
    cache_size=1000,
    batch_concurrency=10
)
service = LogicService(config)
```

**DON'T:** Hardcode configuration
```python
# ❌ Bad
service = LogicService(use_nlp=True, cache_size=1000, ...)  # Too many params
```

### 2. Error Handling

**DO:** Handle errors gracefully with fallbacks
```python
# ✅ Good
try:
    result = await convert_text_to_fol(text, use_nlp=True)
except Exception as e:
    logger.error(f"NLP conversion failed: {e}")
    # Fallback to regex
    result = await convert_text_to_fol(text, use_nlp=False)
```

**DON'T:** Let errors propagate without handling
```python
# ❌ Bad
result = await convert_text_to_fol(text)  # No error handling
```

### 3. Batch Processing

**DO:** Use batch processing for multiple items
```python
# ✅ Good - 5-8x faster
processor = FOLBatchProcessor(max_concurrency=10)
result = await processor.convert_batch(texts)
```

**DON'T:** Process items one by one
```python
# ❌ Bad - Very slow
results = []
for text in texts:
    result = await convert_text_to_fol(text)
    results.append(result)
```

### 4. Caching

**DO:** Enable caching for repeated operations
```python
# ✅ Good
engine = ProofExecutionEngine(
    enable_caching=True,
    cache_size=1000,
    cache_ttl=3600
)
```

**DO:** Monitor cache statistics
```python
# ✅ Good
stats = cache.get_statistics()
if stats['hit_rate'] < 0.5:
    logger.warning("Low cache hit rate - consider increasing cache size")
```

### 5. Resource Management

**DO:** Use context managers and async properly
```python
# ✅ Good
async with get_logic_service() as service:
    result = await service.convert_to_fol(text)
# Cleanup automatic
```

**DON'T:** Forget to clean up resources
```python
# ❌ Bad
service = LogicService(config)
result = service.convert_to_fol(text)
# No cleanup
```

### 6. Testing

**DO:** Test with realistic data
```python
# ✅ Good
test_cases = [
    "All humans are mortal",  # Simple
    "If P then Q",            # Conditional
    "Some birds can't fly",   # Negation
    "",                       # Edge case
    "Complex nested quantification..."  # Complex
]
```

**DO:** Test error conditions
```python
# ✅ Good
def test_handles_empty_input():
    result = await convert_text_to_fol("")
    assert result['status'] == 'success'
    assert len(result['fol_formulas']) == 0
```

### 7. Logging

**DO:** Use structured logging
```python
# ✅ Good
logger.info(
    "Conversion complete",
    extra={
        'text_length': len(text),
        'confidence': result['summary']['average_confidence'],
        'time_ms': elapsed * 1000
    }
)
```

**DON'T:** Use print statements
```python
# ❌ Bad
print(f"Result: {result}")  # No log levels, no structured data
```

### 8. Performance Monitoring

**DO:** Use benchmarks in CI/CD
```python
# ✅ Good - In CI pipeline
def test_performance_regression():
    benchmark = PerformanceBenchmark()
    result = benchmark.benchmark(
        "FOL Conversion",
        convert_text_to_fol,
        iterations=100
    )
    assert result.mean_time < 0.05  # <50ms threshold
```

---

## Performance Optimization

### 1. Cache Tuning

**Optimal cache size:**
```python
# Calculate based on workload
unique_formulas_per_day = 10000
cache_size = int(unique_formulas_per_day * 0.8)  # 80% coverage
cache_ttl = 3600  # 1 hour

engine = ProofExecutionEngine(
    cache_size=cache_size,
    cache_ttl=cache_ttl
)
```

**Monitor and adjust:**
```python
stats = cache.get_statistics()
if stats['evictions'] > stats['hits']:
    # Cache too small
    cache.resize(cache_size * 2)
```

### 2. Batch Size Optimization

**Find optimal batch size:**
```python
async def find_optimal_batch_size():
    test_data = generate_test_data(1000)
    results = {}
    
    for batch_size in [10, 50, 100, 200]:
        processor = ChunkedBatchProcessor(chunk_size=batch_size)
        
        start = time.time()
        result = await processor.process_large_batch(
            test_data,
            convert_text_to_fol
        )
        elapsed = time.time() - start
        
        results[batch_size] = result.items_per_second
    
    optimal = max(results, key=results.get)
    print(f"Optimal batch size: {optimal}")
    return optimal
```

### 3. Concurrency Tuning

**CPU-bound tasks:**
```python
# Use process pool for CPU-bound work
processor = BatchProcessor(
    max_concurrency=os.cpu_count(),
    use_process_pool=True
)
```

**I/O-bound tasks:**
```python
# Use higher concurrency for I/O-bound work
processor = BatchProcessor(
    max_concurrency=50,  # Higher for I/O
    use_process_pool=False
)
```

### 4. NLP vs Regex Trade-off

**Benchm comparison:**
```python
async def compare_extraction_methods():
    benchmark = PerformanceBenchmark()
    
    # Regex (faster)
    regex_result = await benchmark.benchmark_async(
        "Regex",
        convert_text_to_fol,
        text_input=text,
        use_nlp=False,
        iterations=100
    )
    
    # NLP (better quality)
    nlp_result = await benchmark.benchmark_async(
        "NLP",
        convert_text_to_fol,
        text_input=text,
        use_nlp=True,
        iterations=100
    )
    
    print(f"Regex: {regex_result.mean_time*1000:.1f}ms")
    print(f"NLP: {nlp_result.mean_time*1000:.1f}ms")
    print(f"Speedup: {nlp_result.mean_time/regex_result.mean_time:.1f}x")
```

**Choose based on needs:**
- Use **regex** when: Speed critical, simple sentences, high volume
- Use **NLP** when: Quality critical, complex sentences, have GPU

### 5. Memory Management

**Large datasets:**
```python
# ✅ Good - Stream processing
async def process_large_file(file_path):
    processor = ChunkedBatchProcessor(chunk_size=100)
    
    for chunk in read_file_in_chunks(file_path):
        result = await processor.process_large_batch(
            chunk,
            convert_text_to_fol
        )
        yield result  # Process incrementally
```

**DON'T: Load everything into memory:**
```python
# ❌ Bad - OOM risk
all_data = load_entire_file(file_path)  # Millions of items
results = await process_batch(all_data)  # Out of memory!
```

---

## Common Issues

### Issue 1: Low Cache Hit Rate

**Symptoms:**
- Cache hit rate <40%
- Slow performance despite caching enabled

**Causes:**
- Cache too small
- TTL too short
- High variability in formulas

**Solutions:**
```python
# 1. Increase cache size
cache.resize(2000)  # Double the size

# 2. Increase TTL
cache = ProofCache(max_size=1000, default_ttl=7200)  # 2 hours

# 3. Normalize formulas before caching
def normalize_formula(formula):
    # Remove whitespace variations
    return ' '.join(formula.split())

# Use normalized key
cache_key = normalize_formula(formula)
```

### Issue 2: spaCy Model Not Found

**Symptoms:**
```
OSError: [E050] Can't find model 'en_core_web_sm'
```

**Solutions:**
```bash
# Download model
python -m spacy download en_core_web_sm

# Or use pip
pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.0.0/en_core_web_sm-3.0.0.tar.gz
```

**Fallback in code:**
```python
from ipfs_datasets_py.logic.fol.utils.nlp_predicate_extractor import get_extraction_stats

stats = get_extraction_stats()
if not stats['spacy_available']:
    logger.warning("spaCy not available, using regex fallback")
    use_nlp = False
```

### Issue 3: Slow Batch Processing

**Symptoms:**
- Batch processing slower than sequential
- Low CPU utilization

**Causes:**
- Concurrency too low
- Synchronous code in async context
- Resource contention

**Solutions:**
```python
# 1. Increase concurrency
processor = FOLBatchProcessor(max_concurrency=20)  # Increase from 10

# 2. Use process pool for CPU-bound
processor = BatchProcessor(
    max_concurrency=os.cpu_count(),
    use_process_pool=True
)

# 3. Profile to find bottlenecks
import cProfile
cProfile.run('asyncio.run(processor.convert_batch(texts))')
```

### Issue 4: Out of Memory

**Symptoms:**
- MemoryError
- Process killed
- Swap thrashing

**Solutions:**
```python
# 1. Use chunked processing
processor = ChunkedBatchProcessor(
    chunk_size=50,  # Reduce from 100
    max_concurrency=5   # Reduce concurrency
)

# 2. Process in streaming fashion
async for chunk_result in process_stream(large_dataset):
    save_results(chunk_result)  # Save incrementally

# 3. Monitor memory usage
import psutil
process = psutil.Process()
memory_mb = process.memory_info().rss / 1024 / 1024
if memory_mb > 1000:  # >1GB
    logger.warning(f"High memory usage: {memory_mb:.0f}MB")
```

### Issue 5: XGBoost/LightGBM Not Available

**Symptoms:**
```
ImportError: No module named 'xgboost'
```

**Solutions:**
```bash
# Install ML dependencies
pip install xgboost lightgbm
```

**Or use heuristic fallback:**
```python
config = MLConfidenceConfig(
    fallback_to_heuristic=True  # Automatically fall back
)
scorer = MLConfidenceScorer(config)
# Will use heuristic if XGBoost/LightGBM unavailable
```

---

## Troubleshooting

### Debug Mode

Enable detailed logging:
```python
import logging

# Set log level
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Enable module logging
logger = logging.getLogger('ipfs_datasets_py.logic')
logger.setLevel(logging.DEBUG)
```

### Performance Profiling

```python
import cProfile
import pstats
from pstats import SortKey

# Profile code
profiler = cProfile.Profile()
profiler.enable()

# Your code here
result = await convert_text_to_fol(text)

profiler.disable()

# Print stats
stats = pstats.Stats(profiler)
stats.sort_stats(SortKey.CUMULATIVE)
stats.print_stats(10)  # Top 10 functions
```

### Memory Profiling

```python
from memory_profiler import profile

@profile
async def memory_test():
    texts = ['test'] * 10000
    processor = FOLBatchProcessor()
    result = await processor.convert_batch(texts)
    return result

# Run with: python -m memory_profiler script.py
```

### Network Issues (IPFS)

If IPFS backing enabled:
```python
# Test IPFS connectivity
from ipfs_datasets_py.logic.integration.proof_cache import ProofCache

cache = ProofCache(ipfs_backed=True)
try:
    cache.test_ipfs_connection()
except Exception as e:
    logger.error(f"IPFS connection failed: {e}")
    # Disable IPFS backing
    cache = ProofCache(ipfs_backed=False)
```

### Benchmark Regression Detection

```python
def check_performance_regression():
    """Check for performance regressions."""
    benchmark = PerformanceBenchmark()
    
    # Current performance
    current = benchmark.benchmark(
        "Current",
        convert_text_to_fol,
        text_input="All humans are mortal",
        iterations=100
    )
    
    # Load baseline (from previous run)
    baseline = load_baseline_benchmark()
    
    # Compare
    regression = (current.mean_time - baseline.mean_time) / baseline.mean_time
    
    if regression > 0.1:  # >10% slower
        raise AssertionError(
            f"Performance regression detected: {regression*100:.1f}% slower"
        )
```

---

## FAQ

### Q: Should I use NLP or regex extraction?

**A:** Depends on your use case:
- **Use NLP** when:
  - Quality is more important than speed
  - Dealing with complex sentences
  - Have GPU available
  - Compound nouns are common
- **Use Regex** when:
  - Speed is critical
  - Simple sentences
  - High volume processing
  - Resource-constrained environment

### Q: How do I improve cache hit rate?

**A:** Several strategies:
1. Increase cache size
2. Increase TTL
3. Normalize input before caching
4. Pre-warm cache with common queries
5. Use persistent cache across restarts

### Q: What's the optimal batch size?

**A:** Depends on:
- **Memory**: Larger batches use more memory
- **Latency**: Smaller batches have lower latency
- **Throughput**: Medium batches (50-100) often optimal

Test with your specific workload:
```python
optimal_size = await find_optimal_batch_size()
```

### Q: How do I handle timeouts?

**A:** Configure timeouts appropriately:
```python
engine = ProofExecutionEngine(
    timeout=120  # 2 minutes for complex proofs
)

# Or catch timeout exceptions
try:
    result = engine.prove_formula(formula)
except TimeoutError:
    logger.warning("Proof timed out")
    # Use heuristic or skip
```

### Q: Can I use custom extractors?

**A:** Yes, implement custom extraction:
```python
def my_custom_extractor(text):
    """Domain-specific extraction."""
    predicates = {
        "nouns": extract_domain_nouns(text),
        "verbs": extract_domain_verbs(text),
        "custom": my_custom_logic(text)
    }
    return predicates

# Use in conversion
result = await convert_text_to_fol(
    text,
    domain_predicates=my_custom_extractor(text)
)
```

### Q: How do I deploy in production?

**A:** Follow these steps:
1. Use configuration management
2. Enable caching and monitoring
3. Set up proper logging
4. Use health checks
5. Implement graceful degradation
6. Set resource limits
7. Monitor performance metrics

See `docs/LOGIC_INTEGRATION_GUIDE.md` for detailed deployment examples.

### Q: What are the hardware requirements?

**A:** Minimum:
- CPU: 2 cores
- RAM: 4GB
- Disk: 1GB

Recommended:
- CPU: 4+ cores
- RAM: 8GB+
- Disk: 10GB+
- GPU: Optional (for ML/NLP)

### Q: How do I contribute?

**A:** See `CONTRIBUTING.md` for guidelines on:
- Code style
- Testing requirements
- Pull request process
- Documentation standards

---

## Getting Help

**Documentation:**
- Usage Examples: `docs/LOGIC_USAGE_EXAMPLES.md`
- Architecture: `docs/LOGIC_ARCHITECTURE.md`
- API Reference: `docs/LOGIC_API_REFERENCE.md`
- Integration: `docs/LOGIC_INTEGRATION_GUIDE.md`

**Support:**
- GitHub Issues: https://github.com/endomorphosis/ipfs_datasets_py/issues
- Discussions: https://github.com/endomorphosis/ipfs_datasets_py/discussions
- Documentation: https://ipfs-datasets-py.readthedocs.io/

**Reporting Bugs:**
1. Check existing issues
2. Provide minimal reproduction
3. Include versions and environment
4. Attach logs if relevant
