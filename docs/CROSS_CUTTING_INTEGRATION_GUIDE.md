# Cross-Cutting Integration Guide

**Version:** 1.0  
**Date:** February 16, 2026  
**Status:** Production Ready

---

## Table of Contents

1. [Overview](#overview)
2. [Monitoring Integration](#monitoring-integration)
3. [Caching Integration](#caching-integration)
4. [Error Handling](#error-handling)
5. [Best Practices](#best-practices)
6. [Examples](#examples)
7. [Troubleshooting](#troubleshooting)

---

## Overview

This guide covers the cross-cutting concerns implemented across the `processors/` package, providing standardized patterns for monitoring, caching, error handling, and dependency injection.

### Architecture

```
processors/
├── infrastructure/          # Cross-cutting infrastructure
│   ├── monitoring.py       # @monitor decorator
│   ├── caching.py          # @cached decorator
│   ├── error_handling.py   # Error management
│   └── profiling.py        # Performance profiling
├── specialized/            # Domain processors
│   ├── graphrag/          # ✅ Monitoring integrated
│   ├── pdf/               # ✅ Monitoring integrated
│   ├── multimodal/        # 🔄 Monitoring in progress
│   ├── batch/             # 🔄 Monitoring in progress
│   ├── media/             # 🔄 Monitoring in progress
│   └── web_archive/       # 🔄 Monitoring in progress
└── engines/               # Facade layer
    ├── llm/
    ├── query/
    └── relationship/
```

---

## Monitoring Integration

### The @monitor Decorator

The `@monitor` decorator provides automatic tracking of processor performance and health.

#### Basic Usage

```python
from ipfs_datasets_py.processors.infrastructure.monitoring import monitor

class MyProcessor:
    @monitor
    async def process_document(self, document):
        """Process a document with automatic monitoring."""
        # Your processing logic here
        result = await self._do_processing(document)
        return result
```

#### What Gets Tracked

The `@monitor` decorator automatically tracks:

- **Latency:** Execution time for each call
- **Success Rate:** Ratio of successful to failed calls
- **Error Messages:** Last 10 errors with timestamps
- **Call Count:** Total number of invocations
- **Slow Operations:** Automatic warnings for operations >5 seconds

#### Features

1. **Zero Configuration:** Just add the decorator
2. **Async Support:** Works with both sync and async methods
3. **Thread-Safe:** Safe for concurrent execution
4. **Low Overhead:** Minimal performance impact (~1-2ms)
5. **Automatic Logging:** Warns on slow operations

### Querying Metrics

```python
from ipfs_datasets_py.processors.infrastructure.monitoring import (
    get_processor_metrics,
    get_monitoring_summary,
    reset_processor_metrics
)

# Get metrics for a specific processor
metrics = get_processor_metrics("MyProcessor.process_document")
print(f"Success rate: {metrics['success_rate']:.1f}%")
print(f"Avg latency: {metrics['avg_time']:.3f}s")

# Get summary of all processors
summary = get_monitoring_summary()
for name, metrics in summary.items():
    print(f"{name}: {metrics['calls']} calls, {metrics['success_rate']:.1f}% success")

# Reset metrics for a processor
reset_processor_metrics("MyProcessor.process_document")

# Reset all metrics
reset_processor_metrics()
```

### Monitoring Dashboard

Use the CLI dashboard to view live metrics:

```bash
# View current metrics
python scripts/monitoring/processor_dashboard.py

# Export as JSON
python scripts/monitoring/processor_dashboard.py --json > metrics.json

# Reset all metrics
python scripts/monitoring/processor_dashboard.py --reset
```

**Dashboard Output:**

```
================================================================================
PROCESSOR MONITORING DASHBOARD
================================================================================
Timestamp: 2026-02-16 03:30:00
Total Processors: 5
Total Calls: 127

PROCESSOR DETAILS:
--------------------------------------------------------------------------------
UnifiedGraphRAGProcessor.process_website:
  Calls: 45
  Success Rate: 95.6%
  Avg Time: 2.345s
  Last Success: 2026-02-16 03:29:45
  Last Failure: 2026-02-16 03:15:23
  
PDFProcessor.process_pdf:
  Calls: 82
  Success Rate: 100.0%
  Avg Time: 1.234s
  Last Success: 2026-02-16 03:29:58
================================================================================
```

### Integration Examples

#### GraphRAG Processor

```python
from ipfs_datasets_py.processors.infrastructure.monitoring import monitor

class UnifiedGraphRAGProcessor:
    @monitor
    async def process_website(self, url: str, **options) -> Dict[str, Any]:
        """Process a website with automatic monitoring."""
        result = await self._extract_and_build_graph(url, **options)
        return result
    
    @monitor
    async def process_multiple_websites(self, urls: List[str], **options) -> List[Dict]:
        """Process multiple websites with monitoring."""
        results = []
        for url in urls:
            result = await self.process_website(url, **options)
            results.append(result)
        return results
```

#### PDF Processor

```python
from ipfs_datasets_py.processors.infrastructure.monitoring import monitor

class PDFProcessor:
    @monitor
    def process_pdf(self, pdf_path: str, **options) -> Dict[str, Any]:
        """Process PDF with automatic monitoring."""
        # Extract text
        text = self._extract_text(pdf_path)
        
        # Extract structure
        structure = self._extract_structure(pdf_path)
        
        return {
            'text': text,
            'structure': structure,
            'metadata': self._extract_metadata(pdf_path)
        }
```

#### Multimodal Processor

```python
from ipfs_datasets_py.processors.infrastructure.monitoring import monitor

class MultimodalProcessor:
    @monitor
    async def process_multimodal(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Process multimodal inputs with monitoring."""
        # Process each modality
        text_result = await self._process_text(inputs.get('text'))
        image_result = await self._process_images(inputs.get('images'))
        audio_result = await self._process_audio(inputs.get('audio'))
        
        # Fuse results
        return self._fuse_modalities(text_result, image_result, audio_result)
```

---

## Caching Integration

### The @cached Decorator (Coming Soon)

The `@cached` decorator provides automatic result caching for expensive operations.

**Status:** Infrastructure exists in `infrastructure/caching.py` but integration deferred to Phase 14.

#### Planned Usage

```python
from ipfs_datasets_py.processors.infrastructure.caching import cached

class MyProcessor:
    @cached(ttl=3600, key_func=lambda self, doc: doc['id'])
    @monitor
    async def process_document(self, document):
        """Cached and monitored processing."""
        result = await self._expensive_operation(document)
        return result
```

**Target:** 70%+ cache hit rate for repeated operations.

---

## Error Handling

### Standardized Error Patterns (Coming Soon)

**Status:** Deferred to future phases.

#### Planned Pattern

```python
from ipfs_datasets_py.processors.infrastructure.error_handling import (
    handle_processor_error,
    ProcessorError,
    RetryableError
)

class MyProcessor:
    @monitor
    @handle_processor_error(retry=3, backoff=2.0)
    async def process_document(self, document):
        """Processing with automatic error handling and retry."""
        try:
            result = await self._process(document)
            return result
        except TransientError as e:
            raise RetryableError(f"Transient failure: {e}")
        except Exception as e:
            raise ProcessorError(f"Processing failed: {e}")
```

---

## Best Practices

### 1. Always Use @monitor for Public Methods

**DO:**
```python
@monitor
async def process_website(self, url: str) -> Dict:
    """Public API method - always monitored."""
    return await self._internal_process(url)

async def _internal_process(self, url: str) -> Dict:
    """Private method - monitoring optional."""
    return self._extract_data(url)
```

**DON'T:**
```python
# Missing monitoring on public API
async def process_website(self, url: str) -> Dict:
    return await self._internal_process(url)
```

### 2. Place @monitor as Outermost Decorator

**DO:**
```python
@monitor
@cached(ttl=3600)
async def process_document(self, doc):
    """Monitor wraps cache for accurate metrics."""
    pass
```

**DON'T:**
```python
@cached(ttl=3600)
@monitor  # Metrics won't include cache hits
async def process_document(self, doc):
    pass
```

### 3. Use Descriptive Method Names

Method names appear in monitoring dashboard - make them meaningful:

**DO:**
```python
@monitor
async def process_pdf_with_ocr(self, path: str):
    """Clear, descriptive name."""
    pass
```

**DON'T:**
```python
@monitor
async def proc(self, p):
    """Unclear name in monitoring."""
    pass
```

### 4. Handle Errors Gracefully

Let exceptions propagate after logging:

```python
@monitor
async def process_document(self, doc):
    """Monitoring tracks the error automatically."""
    try:
        result = await self._risky_operation(doc)
        return result
    except Exception as e:
        # Log additional context if needed
        logger.error(f"Failed to process {doc['id']}: {e}")
        # Re-raise - @monitor records it
        raise
```

### 5. Check Dashboard Regularly

```bash
# View metrics during development
python scripts/monitoring/processor_dashboard.py

# Look for:
# - Low success rates (<95%)
# - High latency (>5s avg)
# - Frequent errors
```

---

## Examples

### Complete Processor with Monitoring

```python
from typing import Dict, List, Any
from ipfs_datasets_py.processors.infrastructure.monitoring import monitor
import logging

logger = logging.getLogger(__name__)


class MyCustomProcessor:
    """Custom processor with comprehensive monitoring."""
    
    def __init__(self):
        self.config = self._load_config()
    
    @monitor
    async def process_single(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a single item with automatic monitoring.
        
        Tracks: latency, success/failure, errors
        """
        # Validate input
        self._validate_item(item)
        
        # Process
        result = await self._do_processing(item)
        
        # Post-process
        return self._enhance_result(result)
    
    @monitor
    async def process_batch(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Process multiple items with monitoring.
        
        Note: Each item is processed individually, so process_single
        metrics will also be tracked.
        """
        results = []
        for item in items:
            try:
                result = await self.process_single(item)
                results.append(result)
            except Exception as e:
                logger.warning(f"Failed to process item {item.get('id')}: {e}")
                # Continue with other items
                continue
        
        return results
    
    @monitor
    def get_statistics(self) -> Dict[str, Any]:
        """Get processor statistics (also monitored)."""
        from ipfs_datasets_py.processors.infrastructure.monitoring import (
            get_processor_metrics
        )
        
        return {
            'single_metrics': get_processor_metrics('MyCustomProcessor.process_single'),
            'batch_metrics': get_processor_metrics('MyCustomProcessor.process_batch'),
        }
    
    # Private methods - not monitored
    def _validate_item(self, item: Dict) -> None:
        """Internal validation - no monitoring needed."""
        if 'id' not in item:
            raise ValueError("Item missing required 'id' field")
    
    async def _do_processing(self, item: Dict) -> Dict:
        """Internal processing - no monitoring needed."""
        # Processing logic
        return {'result': 'processed'}
    
    def _enhance_result(self, result: Dict) -> Dict:
        """Internal enhancement - no monitoring needed."""
        result['enhanced'] = True
        return result
    
    def _load_config(self) -> Dict:
        """Internal configuration - no monitoring needed."""
        return {}
```

### Using Metrics Programmatically

```python
from ipfs_datasets_py.processors.infrastructure.monitoring import (
    get_processor_metrics,
    get_monitoring_summary
)


def check_processor_health(processor_name: str) -> bool:
    """Check if a processor is healthy."""
    metrics = get_processor_metrics(processor_name)
    
    if not metrics:
        return True  # No data yet, assume healthy
    
    # Health criteria
    success_rate_threshold = 95.0  # 95% success rate required
    latency_threshold = 10.0  # 10 seconds max avg latency
    
    is_healthy = (
        metrics['success_rate'] >= success_rate_threshold and
        metrics['avg_time'] <= latency_threshold
    )
    
    if not is_healthy:
        print(f"⚠️ {processor_name} unhealthy:")
        print(f"  Success rate: {metrics['success_rate']:.1f}% (need {success_rate_threshold}%)")
        print(f"  Avg latency: {metrics['avg_time']:.2f}s (max {latency_threshold}s)")
    
    return is_healthy


def generate_health_report() -> Dict[str, Any]:
    """Generate health report for all processors."""
    summary = get_monitoring_summary()
    
    healthy = []
    unhealthy = []
    
    for name, metrics in summary.items():
        if check_processor_health(name):
            healthy.append(name)
        else:
            unhealthy.append(name)
    
    return {
        'total_processors': len(summary),
        'healthy': len(healthy),
        'unhealthy': len(unhealthy),
        'unhealthy_list': unhealthy,
        'summary': summary
    }
```

---

## Troubleshooting

### Metrics Not Appearing

**Problem:** Decorated method not showing metrics.

**Solutions:**
1. Ensure `@monitor` is applied to instance methods (has `self` parameter)
2. Check method is being called at runtime
3. Verify import path is correct
4. Check logs for any decorator warnings

```python
# Correct
class MyProcessor:
    @monitor
    def process(self, data):  # ✅ Instance method
        pass

# Incorrect
@monitor
def process(data):  # ❌ Function, not method
    pass
```

### High Latency Warnings

**Problem:** Seeing many "slow operation" warnings.

**Solutions:**
1. Optimize the slow operation
2. Adjust threshold in monitoring.py if expected
3. Consider async/parallel processing
4. Add caching (Phase 14)

### Memory Usage Growing

**Problem:** Metrics storage growing over time.

**Solution:** Regularly reset metrics:

```python
from ipfs_datasets_py.processors.infrastructure.monitoring import reset_processor_metrics

# Reset specific processor
reset_processor_metrics("MyProcessor.process")

# Reset all (e.g., daily cron job)
reset_processor_metrics()
```

### Decorator Order Issues

**Problem:** Metrics incorrect when using multiple decorators.

**Solution:** Always place `@monitor` outermost:

```python
# Correct order
@monitor          # Outermost - tracks everything
@cached           # Middle - caching
@retry            # Innermost - retry logic
def process(self):
    pass
```

---

## Future Enhancements

### Phase 14: Performance Optimization

**Planned additions:**
- `@cached` decorator integration
- Cache hit rate tracking
- Distributed tracing support
- Prometheus metrics export
- Grafana dashboard templates

### Phase 12: Testing & Validation

**Planned additions:**
- Monitoring test utilities
- Metrics assertion helpers
- Mock monitoring for tests
- Performance regression tests

---

## Summary

### Quick Start Checklist

- [ ] Import `@monitor` from `infrastructure/monitoring`
- [ ] Add `@monitor` to all public processor methods
- [ ] Run `processor_dashboard.py` to view metrics
- [ ] Check success rates and latency regularly
- [ ] Follow best practices (monitor outermost, descriptive names)

### Key Benefits

✅ **Zero Configuration:** Just add decorator  
✅ **Automatic Tracking:** Latency, success, errors  
✅ **Operational Visibility:** Live dashboard  
✅ **Production Ready:** Thread-safe, low overhead  
✅ **Zero Breaking Changes:** Non-intrusive integration

### Resources

- **Monitoring Code:** `ipfs_datasets_py/processors/infrastructure/monitoring.py`
- **Dashboard:** `scripts/monitoring/processor_dashboard.py`
- **Examples:** This guide (see Examples section)
- **Phase 10 Report:** `docs/PHASE_9_10_PROGRESS_REPORT.md`

---

**Version History:**
- v1.0 (2026-02-16): Initial release with @monitor decorator

**Maintainer:** Processors Refactoring Team  
**Status:** Production Ready ✅
