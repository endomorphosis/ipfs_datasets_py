# JSON Log Schema Standardization Guide

**Schema Version:** v3  
**Module:** `ipfs_datasets_py.optimizers.common.log_schema_v3`  
**Status:** RECOMMENDED for all new code, MIGRATION underway for existing code  

---

## Overview

This guide documents the migration from ad-hoc logging to standardized JSON structured logs using schema v3.

**Why Standardize?**
- Consistent field names across all optimizers
- Machine-parseable logs for aggregation/analysis (ELK, Splunk, Datadog)
- Versioned schema for backward compatibility
- Built-in error classification and session tracking
- Reduced noise in logs (structured = filterable)

**What's New in v3?**
- Session lifecycle events
- Iteration/round tracking
- Convergence detection events  
- Cache performance events
- Universal field naming conventions

---

## Schema v3 Anatomy

Every structured log MUST include:

```json
{
  "schema": "ipfs_datasets_py.optimizer_log",
  "schema_version": 3,
  "event": "session.started",
  "timestamp": 1709000000.123
}
```

Every structured log SHOULD include:

```json
{
  "session_id": "sess-abc123",
  "domain": "graph",
  "component": "OntologyGenerator"
}
```

---

## Migration Patterns

### Pattern 1: Basic Info Logs

**BEFORE (ad-hoc):**
```python
logger.info(f"Session round {current_round}/{max_rounds}")
```

**AFTER (structured v3):**
```python
from ipfs_datasets_py.optimizers.common.log_schema_v3 import log_iteration_started

log_iteration_started(
    logger,
    session_id=self.session_id,
    iteration=current_round,
    current_score=self.current_score,
    feedback_count=len(feedback),
    component="TheoremSession",
)
```

**Benefits:**
- Machine-parseable iteration number
- Includes context (score, feedback count)
- Filterable by session_id
- Standard schema

---

### Pattern 2: Session Start/Complete

**BEFORE:**
```python
logger.info(
    "run_session completed session_id=%s domain=%s iterations=%d score=%.4f valid=%s",
    context.session_id,
    context.domain,
    iterations,
    score,
    valid,
)
```

**AFTER:**
```python
from ipfs_datasets_py.optimizers.common.log_schema_v3 import log_session_complete

log_session_complete(
    logger,
    session_id=context.session_id,
    domain=context.domain,
    iterations=iterations,
    final_score=score,
    valid=valid,
    execution_time_ms=execution_time_ms,
    component="BaseOptimizer",
)
```

**Benefits:**
- All fields parseable (no need to regex extract from log message)
- Standard field names
- Timestamp added automatically

---

### Pattern 3: Error Logging

**BEFORE:**
```python
logger.error(f"Extraction failed in round {current_round}")
```

**AFTER:**
```python
from ipfs_datasets_py.optimizers.common.log_schema_v3 import log_error

log_error(
    logger,
    error_type="extraction_failed",
    error_msg=f"Entity extraction timeout in round {current_round}",
    session_id=self.session_id,
    iteration=current_round,
    retryable=True,
    component="OntologyGenerator",
)
```

**Benefits:**
- Error classification (`error_type`)
- Retryable flag for alerting/retry logic
- Structured context (session, iteration)

---

### Pattern 4: Cache Events

**BEFORE:**
```python
logger.debug(f"Cache hit: {key[:12]}... (hit rate: {self.stats.hit_rate:.2%})")
```

**AFTER:**
```python
from ipfs_datasets_py.optimizers.common.log_schema_v3 import log_cache_hit

log_cache_hit(
    logger,
    cache_key=key,
    hit_rate=self.stats.hit_rate,
    component="ValidationCache",
)
```

**Benefits:**
- Standard `cache_key` field (auto-truncated)
- Hit rate as float (not formatted string)
- Filterable cache performance metrics

---

### Pattern 5: Score/Critique Logging

**BEFORE:**
```python
logger.info(f"Score: {score:.3f}, feedback: {len(feedback)} items")
```

**AFTER:**
```python
from ipfs_datasets_py.optimizers.common.log_schema_v3 import log_critique_complete

log_critique_complete(
    logger,
    session_id=self.session_id,
    score=score,
    feedback_count=len(feedback),
    execution_time_ms=critique_time_ms,
    component="OntologyCritic",
)
```

---

### Pattern 6: Convergence Detection

**BEFORE:**
```python
logger.info(f"Session converged at round {current_round} with score {score:.3f}")
```

**AFTER:**
```python
from ipfs_datasets_py.optimizers.common.log_schema_v3 import log_convergence_detected

log_convergence_detected(
    logger,
    session_id=self.session_id,
    iteration=current_round,
    score=score,
    score_delta=score - prev_score,
    threshold=self.convergence_threshold,
    component="OntologySession",
)
```

---

## Helper Functions Reference

| Function | Purpose | Log Level |
|----------|---------|-----------|
| `log_session_start()` | Session begins | INFO |
| `log_session_complete()` | Session succeeds | INFO |
| `log_session_failed()` | Session fails | ERROR |
| `log_iteration_started()` | Iteration/round starts | DEBUG |
| `log_iteration_complete()` | Iteration completes | INFO |
| `log_generate_complete()` | Generation done | INFO |
| `log_critique_complete()` | Critique done | INFO |
| `log_validate_complete()` | Validation done | INFO/WARN |
| `log_convergence_detected()` | Convergence detected | INFO |
| `log_target_reached()` | Target score reached | INFO |
| `log_cache_hit()` | Cache hit | DEBUG |
| `log_error()` | Error occurred | WARN/ERROR |

---

## Field Naming Conventions

| Concept | Standard Field Name | Type | Example |
|---------|-------------------|------|---------|
| Session identifier | `session_id` | str | `"sess-abc123"` |
| Optimizer domain | `domain` | str | `"graph"`, `"logic"`, `"code"` |
| Component name | `component` | str | `"OntologyGenerator"` |
| Iteration number | `iteration` | int | 1 (1-indexed) |
| Quality score | `score` | float | 0.75 (0-1 range) |
| Final score | `final_score` | float | 0.85 |
| Score change | `score_delta` | float | 0.05 |
| Execution time | `execution_time_ms` | float | 1234.5 |
| Artifact size | `artifact_size` | int | 10 (entities/lines) |
| Feedback count | `feedback_count` | int | 3 |
| Validation result | `valid` | bool | true |
| Error type | `error_type` | str | `"timeout"` |
| Error message | `error_msg` | str | `"Timeout after 30s"` |
| Cache key | `cache_key` | str | `"abc123..."` (truncated) |
| Hit rate | `hit_rate` | float | 0.85 (0-1 range) |

**Naming Principles:**
- Use snake_case (not camelCase)
- Be explicit: `execution_time_ms` not `time`
- Use standard suffixes: `_ms` for milliseconds, `_count` for counts
- Boolean fields should be adjectives: `valid`, `retryable`

---

## Migration Strategy

### Phase 1: New Code (CURRENT)
- All new logging uses schema v3 helpers
- No ad-hoc f-string logs in new code

### Phase 2: High-Traffic Paths (IN PROGRESS)
- Migrate BaseOptimizer.run_session() logs
- Migrate OntologyGenerator/Critic/Mediator logs
- Migrate LogicTheoremOptimizer session logs

### Phase 3: Low-Frequency Logs (TODO)
- Migrate cache/utility logs
- Migrate formula translation logs
- Migrate CLI logs

### Phase 4: Deprecation (FUTURE)
- Mark old structured_logging.py as deprecated
- All logs use schema v3

---

## Testing Structured Logs

**Capturing JSON logs in tests:**
```python
import json
import logging

def test_session_logs_are_structured(caplog):
    with caplog.at_level(logging.INFO):
        log_session_start(logger, session_id="test", domain="test", input_size=100)
    
    # Parse JSON log
    log_record = caplog.records[0]
    log_data = json.loads(log_record.message)
    
    # Assert schema fields
    assert log_data["schema"] == "ipfs_datasets_py.optimizer_log"
    assert log_data["schema_version"] == 3
    assert log_data["event"] == "session.started"
    assert log_data["session_id"] == "test"
    assert log_data["input_size"] == 100
```

---

## Log Aggregation Queries

**Example ELK query for failed sessions:**
```json
{
  "query": {
    "bool": {
      "must": [
        { "term": { "schema.keyword": "ipfs_datasets_py.optimizer_log" } },
        { "term": { "event.keyword": "session.failed" } },
        { "term": { "domain.keyword": "graph" } }
      ]
    }
  }
}
```

**Example Splunk query for slow iterations:**
```
schema="ipfs_datasets_py.optimizer_log" event="iteration.completed" execution_time_ms>5000
| stats avg(execution_time_ms) by domain, component
```

---

## Checklist for Migrating a File

- [ ] Import schema v3 helpers
- [ ] Identify all logger.info/warning/error calls
- [ ] Map each log to appropriate helper function
- [ ] Add session_id/domain/component context
- [ ] Convert f-strings to function parameters
- [ ] Test that JSON is parseable
- [ ] Remove ad-hoc logging patterns
- [ ] Update component tests to verify structured logs

---

## FAQ

**Q: Can I still use debug logs with f-strings?**  
A: Yes, DEBUG-level logs for local troubleshooting can remain ad-hoc. But INFO/WARNING/ERROR should be structured.

**Q: What if I need custom fields not in the schema?**  
A: Pass them via the `metrics` dict parameter (for session_complete) or contact maintainers to extend schema.

**Q: How do I test structured logs?**  
A: Use pytest `caplog` fixture, parse JSON from log message, assert fields.

**Q: What about backward compatibility?**  
A: Schema v3 is additive. Old parsers ignore new fields. Version field allows parsers to adapt.

---

**Last Updated:** 2026-02-24  
**See Also:** `log_schema_v3.py`, `LIFECYCLE_HOOKS.md`
