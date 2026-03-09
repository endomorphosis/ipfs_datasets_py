# Lifecycle Hooks Reference

Complete documentation of the BaseOptimizer lifecycle hook system for observability, instrumentation, and custom workflow orchestration.

## Overview

The lifecycle hooks system provides a standard way to observe and instrument optimizer sessions. All optimizers that extend `BaseOptimizer` automatically get access to 6 lifecycle hooks that fire at specific points during the `run_session()` workflow.

**Use Cases:**
- Audit logging and compliance tracking
- Custom metrics collection
- Distributed tracing integration
- Progress notifications and real-time dashboards
- Debugging and troubleshooting
- Session replay and analysis

**Design Principles:**
- **Non-fatal:** Hook exceptions never break optimizer execution (caught and logged)
- **Opt-in:** Default implementations are no-ops; override to add behavior
- **Consistent:** All optimizers fire the same hooks in the same order
- **Standard API:** Hooks receive normalized parameters regardless of optimizer type

---

## Available Hooks

### 1. `on_session_start(context, input_data)`

**Fires:** Once at the beginning of `run_session()`, before any processing.

**Parameters:**
- `context` (`OptimizationContext`): Session context with session_id, domain, constraints, metadata
- `input_data` (`Any`): Raw input data passed to `run_session()`

**Use Cases:**
- Initialize session-specific state (timers, counters, audit records)
- Log session start with correlation ID
- Send session start notifications
- Allocate resources (temp files, database connections)

**Example:**
```python
def on_session_start(self, context, input_data):
    self.session_log.append({
        "event": "start",
        "session_id": context.session_id,
        "domain": context.domain,
        "timestamp": datetime.now().isoformat(),
        "input_size": len(str(input_data)),
    })
```

---

### 2. `on_generate_complete(artifact, context)`

**Fires:** Once after `generate()` returns, before initial critique.

**Parameters:**
- `artifact` (`Any`): Generated artifact (type depends on optimizer)
- `context` (`OptimizationContext`): Session context

**Use Cases:**
- Log initial artifact characteristics
- Cache generated artifacts for later comparison
- Validate artifact structure (non-fatal checks)
- Track generation latency

**Example:**
```python
def on_generate_complete(self, artifact, context):
    if isinstance(artifact, dict):
        logger.info(
            "Generated artifact with %d keys for session %s",
            len(artifact.keys()),
            context.session_id,
        )
```

---

### 3. `on_critique_complete(artifact, score, feedback, context)`

**Fires:** Multiple times:
- Once after initial critique (before optimization loop)
- Once after each optimize iteration (during loop)

**Parameters:**
- `artifact` (`Any`): Artifact that was critiqued
- `score` (`float`): Quality score from 0.0 to 1.0
- `feedback` (`List[str]`): List of improvement suggestions
- `context` (`OptimizationContext`): Session context

**Use Cases:**
- Track score progression over time
- Log feedback for debugging
- Detect score plateaus or regressions
- Collect critique latency metrics
- Build score histograms

**Example:**
```python
def on_critique_complete(self, artifact, score, feedback, context):
    self.score_history.append(score)
    
    # Alert on score regression
    if len(self.score_history) >= 2:
        if score < self.score_history[-2]:
            logger.warning(
                "Score regression detected: %.3f -> %.3f",
                self.score_history[-2],
                score,
            )
```

---

### 4. `on_optimize_complete(artifact, score, feedback, iteration, context)`

**Fires:** Once per optimization iteration (inside the loop).

**Parameters:**
- `artifact` (`Any`): Newly optimized artifact
- `score` (`float`): Score BEFORE this optimization (from previous critique)
- `feedback` (`List[str]`): Feedback BEFORE this optimization
- `iteration` (`int`): 1-indexed iteration number
- `context` (`OptimizationContext`): Session context

**Use Cases:**
- Track optimization progress per iteration
- Log intermediate artifacts for debugging
- Collect per-iteration timing
- Build iteration dashboards
- Implement custom early-stopping logic (via external state)

**Example:**
```python
def on_optimize_complete(self, artifact, score, feedback, iteration, context):
    self.iteration_log.append({
        "iteration": iteration,
        "score": score,
        "feedback_count": len(feedback),
        "artifact_hash": hash(str(artifact)),
    })
    
    # Log every 10 iterations
    if iteration % 10 == 0:
        logger.info("Completed iteration %d with score %.3f", iteration, score)
```

---

### 5. `on_validate_complete(artifact, valid, context)`

**Fires:** Once after `validate()` returns (only if `validation_enabled=True`).

**Parameters:**
- `artifact` (`Any`): Final artifact that was validated
- `valid` (`bool`): Validation result
- `context` (`OptimizationContext`): Session context

**Use Cases:**
- Log validation failures with details
- Collect validation failure rates
- Trigger alerts on validation failures
- Store failed artifacts for analysis

**Example:**
```python
def on_validate_complete(self, artifact, valid, context):
    if not valid:
        logger.error(
            "Validation failed for session %s",
            context.session_id,
        )
        # Store failed artifact for debugging
        self.failed_artifacts[context.session_id] = artifact
```

---

### 6. `on_session_complete(result, context)`

**Fires:** Once at the very end of `run_session()`, after all processing.

**Parameters:**
- `result` (`Dict[str, Any]`): Complete session result with keys:
  - `artifact`: Final artifact
  - `score`: Final quality score
  - `iterations`: Number of iterations completed
  - `valid`: Validation result
  - `execution_time`: Total time in seconds
  - `execution_time_ms`: Total time in milliseconds
  - `metrics` (optional): Additional metrics if `metrics_enabled=True`
- `context` (`OptimizationContext`): Session context

**Use Cases:**
- Log session completion with summary
- Close resources (files, connections)
- Send completion notifications
- Update dashboards
- Write audit records

**Example:**
```python
def on_session_complete(self, result, context):
    logger.info(
        "Session %s complete: %d iterations, score %.3f, valid=%s, time=%.1fms",
        context.session_id,
        result["iterations"],
        result["score"],
        result["valid"],
        result["execution_time_ms"],
    )
    
    # Send to dashboard
    self.dashboard.update_session(context.session_id, result)
```

---

## Hook Execution Order

For a session with **2 iterations**, hooks fire in this order:

```
1. on_session_start(context, input_data)
2. on_generate_complete(artifact, context)
3. on_critique_complete(artifact, score, feedback, context)  # Initial critique
4. on_optimize_complete(artifact, score, feedback, 1, context)  # Iteration 1
5. on_critique_complete(artifact, score, feedback, context)  # After iteration 1
6. on_optimize_complete(artifact, score, feedback, 2, context)  # Iteration 2
7. on_critique_complete(artifact, score, feedback, context)  # After iteration 2
8. on_validate_complete(artifact, valid, context)  # If validation enabled
9. on_session_complete(result, context)
```

**Pattern:** `critique` fires `iterations + 1` times (initial + after each optimize).

---

## Hook Invocation Counts

| Hook | Fires | Count Formula |
|------|-------|---------------|
| `on_session_start` | Always | 1 |
| `on_generate_complete` | Always | 1 |
| `on_critique_complete` | Always | `iterations + 1` |
| `on_optimize_complete` | If iterations > 0 | `iterations` |
| `on_validate_complete` | If `validation_enabled=True` | 0 or 1 |
| `on_session_complete` | Always | 1 |

**Special Cases:**
- **Target score reached early:** If initial `score >= target_score`, the loop enters once (`iterations=1`) but breaks before calling `optimize()`, so `on_optimize_complete` does NOT fire.
- **Validation disabled:** `on_validate_complete` does NOT fire if `config.validation_enabled=False`.
- **Zero max_iterations:** If `max_iterations=0`, only fires: start, generate, critique (initial), validate, complete.

---

## Usage Examples

### Example 1: Audit Logging

```python
from ipfs_datasets_py.optimizers.common import BaseOptimizer, OptimizationContext


class AuditedOptimizer(BaseOptimizer):
    def __init__(self, *args, audit_log_path=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.audit_log = []
        self.audit_log_path = audit_log_path
    
    def on_session_start(self, context, input_data):
        self.audit_log.append({
            "event": "session_start",
            "session_id": context.session_id,
            "domain": context.domain,
            "timestamp": datetime.now().isoformat(),
        })
    
    def on_optimize_complete(self, artifact, score, feedback, iteration, context):
        self.audit_log.append({
            "event": "iteration",
            "session_id": context.session_id,
            "iteration": iteration,
            "score": score,
            "timestamp": datetime.now().isoformat(),
        })
    
    def on_session_complete(self, result, context):
        self.audit_log.append({
            "event": "session_complete",
            "session_id": context.session_id,
            "iterations": result["iterations"],
            "final_score": result["score"],
            "valid": result["valid"],
            "timestamp": datetime.now().isoformat(),
        })
        
        # Persist audit log to file
        if self.audit_log_path:
            with open(self.audit_log_path, "a") as f:
                for record in self.audit_log:
                    f.write(json.dumps(record) + "\n")
            self.audit_log.clear()
```

### Example 2: Real-Time Metrics Collection

```python
class MetricsOptimizer(BaseOptimizer):
    def __init__(self, *args, metrics_collector=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.metrics = metrics_collector or MetricsCollector()
        self.session_start_time = None
    
    def on_session_start(self, context, input_data):
        self.session_start_time = time.time()
        self.metrics.increment("sessions_started", labels={"domain": context.domain})
    
    def on_critique_complete(self, artifact, score, feedback, context):
        self.metrics.record_score(score, labels={"domain": context.domain})
    
    def on_optimize_complete(self, artifact, score, feedback, iteration, context):
        self.metrics.increment("iterations_completed", labels={"domain": context.domain})
        
        # Track iteration latency
        iteration_time = time.time() - getattr(self, "_last_iteration_time", self.session_start_time)
        self.metrics.record_duration("iteration_latency_seconds", iteration_time)
        self._last_iteration_time = time.time()
    
    def on_session_complete(self, result, context):
        session_duration = time.time() - self.session_start_time
        self.metrics.record_duration(
            "session_duration_seconds",
            session_duration,
            labels={"domain": context.domain, "valid": str(result["valid"])}
        )
        
        if result["valid"]:
            self.metrics.increment("sessions_succeeded", labels={"domain": context.domain})
        else:
            self.metrics.increment("sessions_failed", labels={"domain": context.domain})
```

### Example 3: Progress Notifications

```python
class NotifyingOptimizer(BaseOptimizer):
    def __init__(self, *args, notifier=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.notifier = notifier
    
    def on_session_start(self, context, input_data):
        if self.notifier:
            self.notifier.send(f"Started optimization session {context.session_id}")
    
    def on_optimize_complete(self, artifact, score, feedback, iteration, context):
        # Notify every 5 iterations
        if self.notifier and iteration % 5 == 0:
            self.notifier.send(
                f"Session {context.session_id}: iteration {iteration}, score {score:.3f}"
            )
    
    def on_session_complete(self, result, context):
        if self.notifier:
            status = "✓ succeeded" if result["valid"] else "✗ failed"
            self.notifier.send(
                f"Session {context.session_id} {status} after {result['iterations']} "
                f"iterations (score: {result['score']:.3f}, time: {result['execution_time']:.2f}s)"
            )
```

---

## Best Practices

### 1. Keep Hooks Fast and Non-Blocking

Hooks execute synchronously during `run_session()`. Heavy operations (large file writes, network calls) should be async or background tasks.

**Bad:**
```python
def on_session_complete(self, result, context):
    # Blocks for 5+ seconds!
    requests.post("https://api.example.com/results", json=result, timeout=30)
```

**Good:**
```python
def on_session_complete(self, result, context):
    # Queue for background worker
    self.result_queue.put((context.session_id, result))
```

### 2. Handle Exceptions Gracefully

While the base implementation catches exceptions, it's better to handle them explicitly:

```python
def on_critique_complete(self, artifact, score, feedback, context):
    try:
        self.metrics.record_score(score)
    except (MetricsError, ConnectionError) as e:
        logger.warning("Failed to record score: %s", e)
        # Continue without breaking optimizer
```

### 3. Use Structured Logging

Emit structured logs with stable keys for easy parsing:

```python
def on_optimize_complete(self, artifact, score, feedback, iteration, context):
    logger.info(
        "optimization.iteration.complete",
        extra={
            "session_id": context.session_id,
            "iteration": iteration,
            "score": score,
            "feedback_count": len(feedback),
        }
    )
```

### 4. Avoid State Mutation in Hooks (Usually)

Hooks should observe, not mutate optimizer state. If you must mutate, document it clearly:

**Bad (implicit state mutation):**
```python
def on_generate_complete(self, artifact, context):
    # Modifying artifact in-place - will affect downstream processing!
    artifact["injected_field"] = "value"
```

**Acceptable (explicit caching):**
```python
def on_generate_complete(self, artifact, context):
    # Caching for later comparison - documented behavior
    self._initial_artifact = copy.deepcopy(artifact)
```

### 5. Prefer Composition Over Inheritance

Instead of deeply nested optimizer hierarchies, compose hooks via delegation:

```python
class ComposedOptimizer(BaseOptimizer):
    def __init__(self, *args, hook_handlers=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.hook_handlers = hook_handlers or []
    
    def on_session_start(self, context, input_data):
        for handler in self.hook_handlers:
            if hasattr(handler, "on_session_start"):
                handler.on_session_start(context, input_data)
```

---

## Testing Hooks

See `tests/unit/optimizers/common/test_lifecycle_hooks_comprehensive.py` for complete test examples.

**Key test scenarios:**
- Hook execution order
- Hook invocation counts (especially for `on_critique_complete`)
- Hook exceptions are non-fatal
- Hooks receive correct parameters
- Hooks work with early stopping
- Hooks work with validation disabled
- Hooks work when target score is reached early

**Example test:**
```python
def test_hooks_fire_in_expected_order():
    class TestOptimizer(BaseOptimizer):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.events = []
        
        def on_session_start(self, context, input_data):
            self.events.append("start")
        
        def on_generate_complete(self, artifact, context):
            self.events.append("generate")
        
        # ... etc ...
    
    optimizer = TestOptimizer(config=OptimizerConfig(max_iterations=1))
    context = OptimizationContext(session_id="test", input_data="x", domain="test")
    optimizer.run_session("x", context)
    
    assert optimizerevents == ["start", "generate", "critique", "optimize", "critique", "validate", "complete"]
```

---

## Future Enhancements

Planned additions (see TODO.md):
- **Event bus integration** (P3): Publish hooks to a lightweight pub/sub system
- **Additional hooks**: `on_round_start`, `on_round_end`, `on_score_improve`, `on_converge`
- **Hook timing metrics**: Automatic latency tracking for hook execution
- **Hook chaining**: Multiple handlers per hook with priority ordering

---

## Related Documentation

- [How To Add a New Optimizer](../docs/optimizers/HOW_TO_ADD_NEW_OPTIMIZER.md)
- [BaseOptimizer API Reference](./base_optimizer.py)
- [OptimizerConfig Reference](./base_optimizer.py)

---

**Last Updated:** 2026-02-24
