# Code Examples: Public Methods Reference

_Comprehensive examples for using all public methods across optimizer types._

---

## GraphRAG Optimizers

### OntologyGenerator

**Example 1: Generate ontology from documents**
```python
from ipfs_datasets_py.optimizers.graphrag import (
    OntologyGenerator,
    OntologyGenerationContext,
)

# Create generator with context
context = OntologyGenerationContext(
    domain="knowledge_graph",
    extraction_model="heuristic",  # Can be 'heuristic', 'rule_based', or custom
    min_entity_score=0.5,
    max_entities=500,
)

generator = OntologyGenerator()

# Extract entities from documents
documents = [
    "Alice works at Acme Corp and reports to Bob.",
    "Bob manages the Engineering team.",
    "Charlie is a software engineer at Acme.",
]

entities = generator.extract_entities(documents)
print(f"Extracted {len(entities)} entities")
for entity in entities[:3]:
    print(f"  - {entity['name']} ({entity['type']})")

# Infer relationships between entities
relationships = generator.infer_relationships(documents)
print(f"Inferred {len(relationships)} relationships")
for rel in relationships[:3]:
    print(f"  {rel['source']} -{rel['relation_type']}-> {rel['target']}")

# Generate complete ontology
ontology = generator.generate_ontology(
    documents=documents,
    context=context,
)
print(f"Ontology has {len(ontology['entities'])} entities and {len(ontology['relationships'])} relationships")
```

**Example 2: Merge ontologies intelligently**
```python
# Create two ontologies
onto1 = {
    "entities": [
        {"id": "alice", "name": "Alice", "type": "Person"},
        {"id": "acme", "name": "Acme Corp", "type": "Organization"},
    ],
    "relationships": [
        {"id": "r1", "source": "alice", "target": "acme", "relation_type": "works_at"}
    ],
    "metadata": {"version": 1}
}

onto2 = {
    "entities": [
        {"id": "bob", "name": "Bob", "type": "Person"},
        {"id": "acme", "name": "Acme Corporation", "type": "Organization"},  # Duplicate!
    ],
    "relationships": [
        {"id": "r2", "source": "bob", "target": "acme", "relation_type": "works_at"}
    ],
    "metadata": {"version": 1}
}

# Merge intelligently (deduplicates entities, merges properties)
generator = OntologyGenerator()
merged = generator._merge_ontologies_safe(onto1, onto2)

print(f"Merged ontology has {len(merged['entities'])} entities (1 dedup)")
for entity in merged['entities']:
    if entity['id'] == 'acme':
        print(f"Acme entity merged: {entity}")
```

---

### OntologyOptimizer

**Example 3: Analyze batch of session results**
```python
from ipfs_datasets_py.optimizers.graphrag import OntologyOptimizer

# Suppose we have session results from running OntologyHarness
# Each session has a critic_score with an overall score

class MockScore:
    def __init__(self, overall):
        self.overall = overall

class MockSession:
    def __init__(self, score):
        self.critic_score = MockScore(overall=score)
        self.critic_scores = [MockScore(overall=score)]

# Create mock sessions with varying scores
sessions = [
    MockSession(0.65),  # Low quality
    MockSession(0.75),  # Medium quality
    MockSession(0.85),  # High quality
    MockSession(0.80),  # High quality
]

# Analyze batch
optimizer = OntologyOptimizer()
report = optimizer.analyze_batch(sessions)

print(f"Average score: {report.average_score:.2f}")
print(f"Trend: {report.trend}")
print(f"Recommendations:")
for rec in report.recommendations:
    print(f"  - {rec}")

# Report contains detailed metrics
print(f"\nDetailed metrics:")
print(f"  Score distribution: {report.score_distribution}")
print(f"  Improvement rate: {report.improvement_rate:.2%}")
```

**Example 4: Analyze trends over multiple batches**
```python
# Track trends across multiple optimization cycles

optimizer = OntologyOptimizer()

# Cycle 1: First batch
batch1_sessions = [MockSession(s) for s in [0.60, 0.65, 0.70]]
report1 = optimizer.analyze_batch(batch1_sessions)

# Cycle 2: Improved batch
batch2_sessions = [MockSession(s) for s in [0.75, 0.80, 0.78]]
report2 = optimizer.analyze_batch(batch2_sessions)

# Cycle 3: Further improvement
batch3_sessions = [MockSession(s) for s in [0.85, 0.88, 0.90]]
report3 = optimizer.analyze_batch(batch3_sessions)

# Analyze overall trend
historical_results = [
    report1,
    report2,
    report3,
]

trend_report = optimizer.analyze_trends(historical_results)
print(f"Overall trend: {trend_report['trend']}")
print(f"Improvement rate: {trend_report['improvement_rate']:.2%}")
print(f"Convergence estimate: {trend_report['convergence_estimate']}")
```

**Example 5: Run batch analysis in parallel**
```python
import concurrent.futures

# For large numbers of sessions, use parallel analysis
optimizer = OntologyOptimizer()
large_batch = [MockSession(0.5 + (i % 100) * 0.005) for i in range(1000)]

# Parallel analysis
report = optimizer.analyze_batch_parallel(
    session_results=large_batch,
    max_workers=8  # Use 8 threads
)

print(f"Parallel analysis complete: {len(large_batch)} sessions")
print(f"Average score: {report.average_score:.2f}")
```

---

### OntologyValidator

**Example 6: Validate ontology schema**
```python
from ipfs_datasets_py.optimizers.graphrag import OntologyValidator

ontology = {
    "entities": [
        {"id": "alice", "name": "Alice", "type": "Person"},
    ],
    "relationships": [
        {"id": "r1", "source": "alice", "target": "acme", "relation_type": "works_at"}
    ],
    "metadata": {"version": 1}
}

validator = OntologyValidator(ontology)

# Validate structure
errors = validator.validate_ontology()

if errors:
    for error in errors:
        print(f"Validation error: {error}")
else:
    print("Ontology is valid!")

# The above will report:
# "Entity 'acme' referenced in relationship but not found in entities"
```

---

### OntologyHarness

**Example 7: Run complete optimization harness**
```python
from ipfs_datasets_py.optimizers.graphrag import (
    OntologyHarness,
    OntologyGenerationContext,
)

# Configure the refinement context
context = OntologyGenerationContext(
    domain="knowledge_graph",
    extraction_model="heuristic",
    min_entity_score=0.5
)

# Create harness
harness = OntologyHarness(
    config=context,
    max_retries=3  # Retry failed sessions
)

# Run sessions on data sources
data_sources = [
    "Document 1 content...",
    "Document 2 content...",
    "Document 3 content...",
]

sessions = harness.run_sessions(
    data_sources=data_sources,
    batch_size=5
)

print(f"Ran {len(sessions)} sessions")

# Sessions now contain ontology results that can be analyzed
optimizer = OntologyOptimizer()
report = optimizer.analyze_batch(sessions)
print(f"Optimization report: {report.average_score:.2f}")
```

---

## Logic Theorem Optimizer

### LogicTheoremOptimizer

**Example 8: Generate and validate logical statements**
```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import LogicTheoremOptimizer

optimizer = LogicTheoremOptimizer()

# Generate logical statements from natural language
statements = optimizer.generate([
    "All humans are mortal",
    "Socrates is human",
])

print(f"Generated {len(statements)} formal statements")
for stmt in statements:
    print(f"  {stmt}")

# Validate statements
valid_count = len(optimizer.validate_statements(statements))
print(f"Valid statements: {valid_count}/{len(statements)}")

# Critique statements
critique = optimizer.critique(statements)
print(f"Critique score: {critique['overall_score']:.2f}")
print(f"Issues: {critique['issues']}")
```

**Example 9: Prove theorems**
```python
# Prove logical theorems
axioms = [
    "forall x, human(x) -> mortal(x)",
    "human(socrates)"
]

theorem = "mortal(socrates)"

result = optimizer.validate_statements(axioms + [theorem])
print(f"Theorem '{theorem}' is valid given axioms: {result}")

# The optimizer attempts to prove the theorem using its prover backend
```

---

## Agentic Optimizers

### TestDrivenOptimizer

**Example 10: Optimize code using test-driven development**
```python
from ipfs_datasets_py.optimizers.agentic import (
    OptimizationTask,
    TestDrivenOptimizer,
    ChangeControlMethod,
)
from pathlib import Path

# Define optimization task
task = OptimizationTask(
    task_id="opt_001",
    description="Optimize caching performance in data loader",
    target_files=[Path("ipfs_datasets_py/data_loader.py")],
    priority=80,
)

# Create optimizer
optimizer = TestDrivenOptimizer(
    agent_id="agent_001",
    llm_router=your_llm_router,  # Must provide LLM router
    change_control=ChangeControlMethod.PATCH,  # Or GITHUB
)

# Run optimization
result = optimizer.optimize(task)

print(f"Tests passed: {result['tests_passed']}")
print(f"Coverage improvement: {result['coverage_delta']:.2%}")
print(f"Performance delta: {result['performance_delta']:.2%}")
```

### AdversarialOptimizer

**Example 11: Generate multiple candidate solutions**
```python
# Generate adversarial solutions (N competing approaches)
adversarial_optimizer = AdversarialOptimizer(
    agent_id="agent_002",
    llm_router=your_llm_router,
    num_solutions=5,  # Generate 5 competing solutions
)

result = adversarial_optimizer.optimize(task)

print(f"Generated {len(result['solutions'])} competing solutions")
print(f"Winner: {result['winner_approach']} (score: {result['winner_score']:.2f})")

for i, solution in enumerate(result['solutions']):
    print(f"  Solution {i+1}: {solution['approach']} (score: {solution['score']:.2f})")
```

### ActorCriticOptimizer

**Example 12: Learn from feedback**
```python
# Actor-Critic learning across multiple optimizations
actor_critic = ActorCriticOptimizer(
    agent_id="agent_003",
    llm_router=your_llm_router,
    learning_rate=0.01,
)

# Learn from multiple tasks
for task in optimization_tasks:
    result = actor_critic.optimize(task)
    
    # Optimizer learns which strategies work best
    print(f"Task {task.task_id}: {result['approach']} (reward: {result['reward']:.2f})")

# Over time, optimizer specializes in successful patterns
print(f"Learned policy: {actor_critic.policy}")
```

### ValidationValidator Examples

**Example 13: Validate code at different levels**
```python
from ipfs_datasets_py.optimizers.agentic import (
    OptimizationValidator,
    ValidationLevel,
)

validator = OptimizationValidator(level=ValidationLevel.STANDARD)

# Fast validation: syntax only
basic_result = validator.validate_sync(code, level=ValidationLevel.BASIC)
print(f"Syntax OK: {basic_result.passed}")

# Comprehensive validation: syntax + types + tests + performance
strict_result = validator.validate_sync(code, level=ValidationLevel.STRICT)
print(f"Comprehensive validation passed: {strict_result.passed}")

if not strict_result.passed:
    for error in strict_result.errors:
        print(f"[{error.severity}] {error.type}: {error.message}")
```

---

## Common Patterns

### Pattern 1: Error Handling
```python
# Always wrap optimizer calls in try-except
try:
    report = optimizer.analyze_batch(sessions)
except ValueError as e:
    print(f"Invalid input: {e}")
except RuntimeError as e:
    print(f"Optimizer error: {e}")
```

### Pattern 2: Logging Integration
```python
import logging

# Configure logging to see optimizer operations
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

# Now optimizer logs will be visible
report = optimizer.analyze_batch(sessions)
```

### Pattern 3: Structured Metrics Collection
```python
# Extract structured metrics from logs
metrics = {
    'batch_id': id(sessions),
    'session_count': len(sessions),
    'average_score': report.average_score,
    'trend': report.trend,
}

# Log metrics for analysis
import json
print(json.dumps(metrics))
```

### Pattern 4: Graceful Degradation
```python
# Handle missing optional dependencies
try:
    from ipfs_datasets_py.optimizers.graphrag.query_optimizer import HAVE_PSUTIL
    if not HAVE_PSUTIL:
        print("Warning: psutil not available; performance monitoring disabled")
except ImportError:
    print("Warning: Query optimizer not available")
```

---

## See Also

- [QUICK_START.md](QUICK_START.md) - Fast guide for common tasks
- [COMMON_PITFALLS.md](COMMON_PITFALLS.md) - Troubleshooting and pitfalls
- [ARCHITECTURE_DIAGRAMS.md](ARCHITECTURE_DIAGRAMS.md) - Visual architecture
- [README.md](README.md) - Module overview
- Source code docstrings: `BaseOptimizer`, `OntologyOptimizer`, `LogicTheoremOptimizer`

---

## Contributing More Examples

Found a useful pattern? Add it here:
1. Copy an existing example
2. Adapt it to your use case
3. Add a comment explaining the pattern
4. Update the "See Also" section if needed
5. Submit PR with improved documentation

Great examples help everyone use the optimizers effectively!
