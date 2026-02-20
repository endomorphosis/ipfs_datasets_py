# Common Pitfalls Guide: Optimizers Module

_This guide documents common mistakes, misconfigurations, and edge cases encountered when using the optimizers module. Use this to troubleshoot issues and understand best practices._

---

## Overview

This guide covers frequent pitfalls across all optimizer types:
- **GraphRAG Optimizers**: ontology generation, validation, query optimization
- **Logic Theorem Optimizers**: statement validation, proof generation
- **Agentic Optimizers**: task configuration, validation levels, change control

Each section includes:
1. **Symptom**: How the problem manifests
2. **Root Cause**: Why it happens
3. **Solution**: How to fix it
4. **Prevention**: How to avoid it in the future

---

## 1. Ontology-Related Pitfalls (GraphRAG)

### 1.1 Incorrect Ontology JSON Shape

**Symptom**:  
```
AttributeError: 'NoneType' object has no attribute 'get'
ValueError: ontology_dict missing required key 'entities'
```

**Root Cause**:  
Ontology must follow a specific schema with required top-level keys: `entities`, `relationships`, `metadata`.

**Common Mistakes**:
```python
# ❌ WRONG: Missing 'entities' and 'relationships'
ontology = {
    "persons": [...],
    "connections": [...]
}

# ❌ WRONG: Top-level is a list instead of dict
ontology = [
    {"id": "person_1", ...},
    {"id": "person_2", ...}
]

# ❌ WRONG: Entities lack required 'id' field
ontology = {
    "entities": [
        {"name": "Alice", "type": "Person"},  # Missing 'id'!
    ],
    "relationships": [],
    "metadata": {}
}
```

**Solution**:
```python
# ✅ CORRECT: Proper structure
ontology = {
    "entities": [
        {
            "id": "person_alice",
            "name": "Alice",
            "type": "Person",
            "description": "Main character",
            "attributes": {}
        },
        {
            "id": "person_bob",
            "name": "Bob",
            "type": "Person",
            "description": "Secondary character",
            "attributes": {}
        }
    ],
    "relationships": [
        {
            "id": "rel_knows",
            "source": "person_alice",
            "target": "person_bob",
            "relation_type": "knows",
            "weight": 0.8
        }
    ],
    "metadata": {
        "created": "2026-02-21",
        "version": 1,
        "domain": "storytelling"
    }
}
```

**Prevention**:
- Always validate against `ontology_validator.py` before using
- Use `OntologyGenerator.generate_ontology()` to create valid ontologies
- Test with the schema validation tests in `test_edge_cases.py`

---

### 1.2 Inconsistent Entity/Relationship References

**Symptom**:  
```
KeyError: Entity 'person_alice' referenced in relationship but not found
Orphaned entities: entity has no incoming or outgoing relationships
```

**Root Cause**:  
Relationships reference entities by `id`, but the entities don't exist or IDs are mistyped.

**Common Mistakes**:
```python
ontology = {
    "entities": [
        {"id": "person_alice", "name": "Alice", "type": "Person", ...},
        {"id": "person_bob", "name": "Bob", "type": "Person", ...}
    ],
    "relationships": [
        {
            "id": "rel_1",
            "source": "alice",          # ❌ Wrong ID! Should be 'person_alice'
            "target": "person_bob",
            "relation_type": "knows",
            "weight": 0.8
        }
    ],
    "metadata": {}
}
```

**Solution**:
```python
# ✅ CORRECT: Entity IDs match exactly
ontology = {
    "entities": [
        {"id": "person_alice", "name": "Alice", ...},
        {"id": "person_bob", "name": "Bob", ...}
    ],
    "relationships": [
        {
            "id": "rel_1",
            "source": "person_alice",   # ✅ Matches entity ID
            "target": "person_bob",      # ✅ Matches entity ID
            "relation_type": "knows",
            "weight": 0.8
        }
    ],
    "metadata": {}
}
```

**Prevention**:
- Run `OntologyValidator.validate_ontology(ontology)` to check consistency
- Use entity ID constants to avoid typos:
  ```python
  ALICE_ID = "person_alice"
  BOB_ID = "person_bob"
  
  ontology = {
      "entities": [
          {"id": ALICE_ID, ...},
          {"id": BOB_ID, ...}
      ],
      "relationships": [
          {"source": ALICE_ID, "target": BOB_ID, ...}
      ],
      "metadata": {}
  }
  ```

---

### 1.3 Missing Optional Dependencies (psutil, numpy, matplotlib)

**Symptom**:  
```
ImportError: No module named 'psutil'
ModuleNotFoundError: No module named 'numpy'
AttributeError during performance monitoring
```

**Root Cause**:  
`query_optimizer.py` optionally uses `psutil`, `numpy`, and `matplotlib` for performance monitoring and visualization. These are not installed in the default environment.

**Solution**:
```bash
# Install optional performance dependencies
pip install psutil numpy matplotlib

# Or install with the dev requirements
pip install -r requirements-dev.txt
```

**Alternative - Graceful Degradation**:
The `query_optimizer.py` has built-in fallbacks for missing dependencies:
```python
try:
    import psutil
except ImportError:
    psutil = None  # Will use stubs

try:
    import numpy as np
except ImportError:
    np = None  # Will use list operations instead
```

**Prevention**:
- Check available imports:
  ```python
  from ipfs_datasets_py.optimizers.graphrag.query_optimizer import HAVE_PSUTIL, HAVE_NUMPY
  if not HAVE_PSUTIL:
      print("Warning: Install psutil for performance monitoring")
  ```
- Run queries still work without these dependencies, just without optional features

---

### 1.4 Incorrect Ontology Parameters in Optimizer Constructors

**Symptom**:  
```
TypeError: __init__() got an unexpected keyword argument 'ontology'
AttributeError: 'OntologyOptimizer' has no attribute 'ontology'
```

**Root Cause**:  
`OntologyOptimizer` doesn't store the ontology in its constructor; it expects session results from `OntologyHarness`.

**Common Mistakes**:
```python
# ❌ WRONG: Trying to pass ontology to optimizer
optimizer = OntologyOptimizer(ontology=my_ontology)

# ❌ WRONG: Expecting optimizer to remember ontology
report = optimizer.analyze_batch(sessions)
print(optimizer.ontology)  # ← Attribute doesn't exist!
```

**Solution**:
```python
# ✅ CORRECT: Use OntologyHarness to manage lifecycle
harness = OntologyHarness(
    config=OntologyGenerationContext(...),
    max_retries=3
)

sessions = harness.run_sessions(data_sources)

optimizer = OntologyOptimizer()
report = optimizer.analyze_batch(sessions)
print(report.average_score)
```

**Prevention**:
- Use `OntologyHarness` for end-to-end workflows
- Or manually manage session results and pass them to `optimizer.analyze_batch()`
- Read the docstrings in `ontology_optimizer.py`

---

## 2. Query Optimization Pitfalls (GraphRAG)

### 2.1 Query Too Complex or Unbounded

**Symptom**:  
```
Timeout: Query optimization exceeded maximum time
MemoryError: Too many entities in query
RecursionError: Query traversal depth exceeded
```

**Root Cause**:  
Queries with many entities or high traversal depth can explode in complexity. The heuristics in `query_optimizer.py` don't cap complexity by default.

**Common Mistakes**:
```python
# ❌ WRONG: Query requesting 1000+ entity paths
query = {
    "entities": list(range(1000)),  # Too many!
    "depth": 10  # Too deep!
}

# ❌ WRONG: Unbounded traversal
query = {
    "relationships": ["*"],  # Match all relationship types
    "depth": "unbounded"
}
```

**Solution**:
```python
# ✅ CORRECT: Bounded, reasonable query
query = {
    "entities": ["entity_1", "entity_2", "entity_5"],  # Few entities
    "relationships": ["knows", "related_to"],  # Specific types
    "depth": 3  # Limited traversal
}

# Or use the optimizer with timeouts
from ipfs_datasets_py.optimizers.graphrag import UnifiedGraphRAGQueryOptimizer

optimizer = UnifiedGraphRAGQueryOptimizer(timeout_seconds=10)
optimized_plan = optimizer.optimize_query(query)
```

**Prevention**:
- Start with small test queries (5-10 entities max)
- Set `depth <= 4` for safety
- Monitor elapsed time in logs:
  ```python
  import logging
  logging.basicConfig(level=logging.DEBUG)
  # Now you'll see timing logs
  ```

---

### 2.2 Query Results are Null or Empty

**Symptom**:  
```
Query returned empty results
Plan has no execution steps
All entities were filtered out
```

**Root Cause**:  
- Entity IDs in query don't exist in ontology
- Relationship types don't match ontology relationships
- Traversal depth is 0 (no relationships returned)

**Solution**:
```python
# First, validate the query against ontology
validator = OntologyValidator(ontology)

entities_exist = all(
    entity_id in [e["id"] for e in ontology["entities"]]
    for entity_id in query["entities"]
)
print(f"All entities exist: {entities_exist}")

# Then, use explicit debugging
from ipfs_datasets_py.optimizers.graphrag import QueryMetricsCollector
metrics = QueryMetricsCollector()

plan = optimizer.optimize_query(query)
print(f"Plan steps: {len(plan.get('steps', []))}")
if not plan.get('steps'):
    print("DEBUG: No steps in plan. Check entities and relationships.")
```

**Prevention**:
- Always validate query entities exist in ontology:
  ```python
  def validate_query(query, ontology):
      valid_ids = {e["id"] for e in ontology["entities"]}
      for entity_id in query.get("entities", []):
          if entity_id not in valid_ids:
              raise ValueError(f"Entity '{entity_id}' not in ontology")
  ```

---

## 3. Validation-Related Pitfalls

### 3.1 Validation Too Strict or Too Lenient

**Symptom**:  
```
ValidationLevel.PARANOID rejects all code
ValidationLevel.BASIC allows dangerous patterns
All tests pass locally but fail in CI
```

**Root Cause**:  
Different validation levels have different strictness. `PARANOID` can fail on legitimate code; `BASIC` can miss issues.

**Common Mistakes**:
```python
# ❌ WRONG: Using PARANOID on every optimization
for file in files:
    result = validator.validate(
        file,
        level=ValidationLevel.PARANOID  # Gives false positives
    )
    if not result.passed:
        fail_file()

# ❌ WRONG: Using BASIC and missing issues
result = validator.validate(
    file,
    level=ValidationLevel.BASIC  # Misses type errors!
)
```

**Solution**:
```python
# ✅ CORRECT: Use STANDARD for most cases
result = validator.validate(
    file,
    level=ValidationLevel.STANDARD  # Balanced approach
)

if not result.passed:
    for error in result.errors:
        print(f"[{error.type}] {error.message}")

# Use PARANOID only for security-critical code
if is_security_critical(file):
    result = validator.validate(file, level=ValidationLevel.PARANOID)
```

**Prevention**:
- Use ValidationLevel.STANDARD by default
- Escalate to PARANOID only for sensitive files
- Document why BASIC is sufficient (if used)

---

### 3.2 Missing or Mismatched Dependencies During Validation

**Symptom**:  
```
TypeError validator: mypy not found
PerformanceValidator skipped (numpy missing)
Type hints incorrectly flagged as errors
```

**Root Cause**:  
Validators depend on mypy, pytest, etc. If not installed, those validators are skipped or fail silently.

**Solution**:
```bash
# Ensure all validators have dependencies
pip install mypy pytest black flake8

# Or use the validation group
pip install ipfs_datasets_py[validation]
```

**Check Runtime**:
```python
from ipfs_datasets_py.optimizers.agentic.validation import (
    OptimizationValidator,
    HAVE_MYPY,
    HAVE_PYTEST,
    HAVE_PERFORMANCE_VALIDATOR
)

if not HAVE_MYPY:
    print("Warning: mypy not available; type checking skipped")
```

---

## 4. Logging and Debugging Pitfalls

### 4.1 Silent Failures Due to Logging Configuration

**Symptom**:  
```
No optimizer logs appear despite errors
Debug info is lost
Progress is invisible during long-running operations
```

**Root Cause**:  
Python logging defaults to WARNING level; INFO and DEBUG messages are suppressed unless configured.

**Solution**:
```python
import logging

# Enable DEBUG logging for optimizers
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

# Now optimizer logs will show
from ipfs_datasets_py.optimizers.graphrag import OntologyOptimizer
optimizer = OntologyOptimizer()
# Logs will print to console
```

**Alternative - Per-Module Logging**:
```python
import logging

logger = logging.getLogger("ipfs_datasets_py.optimizers.graphrag")
logger.setLevel(logging.DEBUG)

handler = logging.StreamHandler()
handler.setFormatter(
    logging.Formatter('%(asctime)s [%(levelname)s]: %(message)s')
)
logger.addHandler(handler)
```

**Prevention**:
- Always configure logging at application start
- Use environment variables for log levels:
  ```python
  import os
  
  log_level = os.getenv("OPTIMIZER_LOG_LEVEL", "INFO")
  logging.basicConfig(level=log_level)
  ```

---

### 4.2 Structured Logging Keys Are Missing or Wrong

**Symptom**:  
```
Can't correlate logs across sessions
Metrics don't appear in logs
Aggregating on batch_id fails (field not logged)
```

**Root Cause**:  
Optimizers use structured logging with `extra={}` dict. If you're parsing logs, you need the right keys.

**Solution**:
Access structured log fields properly:
```python
import logging
import json

# Set up JSON formatting to capture extra fields
class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            'message': record.getMessage(),
            'level': record.levelname,
            'logger': record.name,
        }
        # Capture extra fields
        if hasattr(record, 'batch_id'):
            log_data['batch_id'] = record.batch_id
        if hasattr(record, 'session_count'):
            log_data['session_count'] = record.session_count
        return json.dumps(log_data)

# Apply formatter
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger = logging.getLogger("ipfs_datasets_py.optimizers")
logger.addHandler(handler)
```

**Available Structured Keys** (per component):

**OntologyOptimizer**:
- `batch_id`: Unique batch identifier
- `session_count`: Number of sessions in batch
- `average_score`: Aggregate score
- `trend`: Trend direction
- `error_type`: If error (e.g., 'empty_batch')

**LogicTheoremOptimizer**:
- `session_id`: Statement handling session ID
- `domain`: Domain (theorem, TDFOL, etc.)
- `score`: Validation/critic score
- `error_type`: Error classification

---

## 5. Performance and Resource Pitfalls

### 5.1 Large Ontologies Cause Memory Issues

**Symptom**:  
```
MemoryError: Cannot allocate X MB
OutOfMemory during ontology merging
Process killed due to excessive memory use
```

**Root Cause**:  
Ontologies with 1000+ entities can consume significant memory, especially during merging or batch operations.

**Common Mistakes**:
```python
# ❌ WRONG: Loading all entities at once on large dataset
ontology = load_ontology("huge_ontology.json")  # 50k entities
# Now trying to generate 100 sessions with this → ~5GB memory

# ❌ WRONG: No cleanup between sessions
for dataset in datasets:
    onto = generate_ontology(dataset)
    # Memory leaks if 'onto' references aren't cleared
```

**Solution**:
```python
# ✅ CORRECT: Use streaming or batch limits
harness = OntologyHarness(
    config=OntologyGenerationContext(
        max_entities_per_session=500,  # Limit session ontology size
        cleanup_after_session=True,     # Free memory
    ),
    max_parallel_sessions=2  # Don't spawn too many
)

# Or manually manage memory
import gc

for dataset in datasets:
    onto = generate_ontology(dataset)
    # Use ontology...
    del onto
    gc.collect()  # Force cleanup
```

**Prevention**:
- Profile memory with test_memory_profiling.py
- Set entity limits in configuration
- Monitor with queryMetricsCollector.get_health_check()

---

### 5.2 Slow Queries Due to High Traversal Depth

**Symptom**:  
```
Query optimization takes minutes
Timeout: Exceeded 60-second limit
CPU at 100% for hours
```

**Root Cause**:  
Traversal depth of 5+ with many entities creates exponential complexity.

**Solution**:
```python
# ✅ CORRECT: Limit traversal depth
query = {
    "entities": ["e1", "e2"],
    "depth": 2,  # Not 5+
    "timeout_seconds": 10
}

# Or optimize the query plan first
from ipfs_datasets_py.optimizers.graphrag import UnifiedGraphRAGQueryOptimizer

optimizer = UnifiedGraphRAGQueryOptimizer(timeout_seconds=10)
plan = optimizer.optimize_query(query)

# If timeout, plan will be degraded
if plan.get("degraded"):
    print("Query was too complex; using simplified plan")
```

**Prevention**:
- Test with representative data sizes
- Monitor execution time in logs
- Set conservative defaults in config

---

## 6. Agentic Optimizer Pitfalls

### 6.1 Wrong ValidationLevel Masking Real Issues

**Symptom**:  
```
Code passes BASIC validation but has type errors
Tests fail after deploy even though local tests pass
Security issue missed by STANDARD validation
```

**Root Cause**:  
Each ValidationLevel skips different checks. Not understanding the differences causes false confidence.

**Solution**:
```python
# ✅ CORRECT: Know what each level covers

# BASIC: Syntax only (fast)
# STANDARD: Syntax + types + unit tests (recommended)
# STRICT: Standard + performance tests + security checks
# PARANOID: Everything + additional security analysis + style checks

# For production code:
result = validator.validate(
    code,
    level=ValidationLevel.STRICT,
    parallel=True
)

# Check results
if not result.passed:
    for error in sorted(result.errors, key=lambda e: e.severity):
        print(f"[{error.level}] {error.type}: {error.message}")
```

**Prevention**:
- Document why you chose each level
- Use STANDARD by default
- Use STRICT for critical paths

---

### 6.2 TokenMasker Not Properly Initialized

**Symptom**:  
```
API tokens appear in logs unmasked
Sensitive data leaked to stdout
"Your API key is: sk_test_..."
```

**Root Cause**:  
TokenMasker is optional and must be explicitly enabled. Many integrations skip it.

**Solution**:
```python
# ✅ CORRECT: Always use TokenMasker
from ipfs_datasets_py.optimizers.agentic.validation import (
    TokenMasker,
    InputSanitizer
)

# Initialize before any logging
token_masker = TokenMasker(
    mask_openai_tokens=True,
    mask_anthropic_tokens=True,
    mask_github_tokens=True
)

sanitizer = InputSanitizer(token_masker=token_masker)

# Use sanitizer for all external inputs
safe_log_message = sanitizer.sanitize_log(user_input)
print(safe_log_message)  # Tokens redacted
```

**Prevention**:
- Always instantiate sanitizer at module load
- Pass sanitizer to all LLM-related code
- Test with actual tokens (create temporary ones)

---

## 7. Testing Pitfalls

### 7.1 Edge Case Tests Missing from Local Suite

**Symptom**:  
```
Tests pass locally but fail on large datasets
Code works for 10 entities but not 1000
Empty input causes crash only sometimes
```

**Root Cause**:  
Local tests don't cover edge cases: empty inputs, very large inputs, malformed data, boundary conditions.

**Solution**:
Use the edge case test suite:
```python
# tests/unit/optimizers/test_edge_cases.py already covers:
# - Empty inputs (0 entities, 0 sessions)
# - Very large inputs (100+ entities, 1000+ sessions)
# - Malformed JSON / missing fields
# - Boundary conditions (single entity, identical values)
# - Concurrent/parallel edge cases

# Run these before committing:
pytest tests/unit/optimizers/test_edge_cases.py -v
```

**Prevention**:
- Run edge case tests before deploying
- Use property-based tests (hypothesis) for invariant testing
- Test with production-scale data

---

### 7.2 Flaky Tests Due to Randomness or Timing

**Symptom**:  
```
Test passes when run alone but fails with others
"order-dependent" test failures
Rare timeout failures that don't reproduce
```

**Root Cause**:  
Optimizers sometimes use randomization (e.g., scoring), or tests share state.

**Solution**:
```python
# ✅ CORRECT: Use seeds for reproducibility
import random
import numpy as np

# At test start:
random.seed(42)
np.random.seed(42)

# Or use hypothesis settings in property-based tests
from hypothesis import settings, HealthCheck

@settings(
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None  # Disable timeout
)
def test_my_property(self, data):
    ...
```

**Prevention**:
- Run tests multiple times locally
- Use CI/CD to catch flakiness
- Avoid randomness in assertions; seed randomness if needed

---

## Troubleshooting Checklist

When something breaks, investigate in this order:

1. **Check logs**: Enable DEBUG logging first
   ```python
   logging.basicConfig(level=logging.DEBUG)
   ```

2. **Validate inputs**: Use validator before optimizer
   ```python
   from ipfs_datasets_py.optimizers.graphrag import OntologyValidator
   validator = OntologyValidator(ontology)
   errors = validator.validate_ontology()
   ```

3. **Check dependencies**: Verify optional packages
   ```python
   from ipfs_datasets_py.optimizers.graphrag.query_optimizer import HAVE_PSUTIL
   print(f"psutil available: {HAVE_PSUTIL}")
   ```

4. **Test with minimal inputs**: Reduce to smallest failing case

5. **Check resource usage**: Memory, CPU, disk
   ```python
   from ipfs_datasets_py.optimizers.graphrag import QueryMetricsCollector
   health = collector.get_health_check()
   print(f"Memory: {health['memory_usage_bytes']} bytes")
   ```

6. **Review logs for structured fields**: Extract context
   ```python
   # Look for batch_id, session_id, error_type in logs
   ```

7. **Consult test files**: Look at passing tests for examples
   - `tests/unit/optimizers/test_edge_cases.py`
   - `tests/unit/optimizers/test_memory_profiling.py`
   - `tests/unit/optimizers/test_property_based_optimizers.py`

---

## Quick Reference: Common Solutions

| Problem | Quick Fix |
|---------|-----------|
| Ontology schema errors | Use `OntologyGenerator.generate_ontology()` |
| Entity/relationship mismatches | Run `OntologyValidator.validate_ontology()` |
| Missing psutil/numpy | `pip install psutil numpy matplotlib` |
| No optimizer logs | `logging.basicConfig(level=logging.DEBUG)` |
| Query too slow | Reduce depth to ≤3, limit entities to ≤10 |
| Memory issues | Enable session cleanup: `cleanup_after_session=True` |
| Token leakage | Initialize `TokenMasker` before logging |
| Flaky tests | Set random seeds: `random.seed(42)` |
| Silent failures | Check validation result errors explicitly |
| Local pass / CI fail | Run with production-scale test data |

---

## See Also

- [QUICK_START.md](QUICK_START.md) - Get started with optimizers
- [ARCHITECTURE_DIAGRAMS.md](ARCHITECTURE_DIAGRAMS.md) - Visual architecture
- [README.md](README.md) - Module overview
- [test_edge_cases.py](../tests/unit/optimizers/test_edge_cases.py) - Edge case examples
- [test_memory_profiling.py](../tests/unit/optimizers/test_memory_profiling.py) - Performance examples
- [test_property_based_optimizers.py](../tests/unit/optimizers/test_property_based_optimizers.py) - Invariant testing examples

---

## Feedback and Issues

Found a pitfall not covered here? Please:
1. Document the symptom, root cause, and solution
2. Add a test to prevent regression
3. Update this guide
4. Share with the team for collective learning

Remember: **Common pitfalls make the best test cases!**
