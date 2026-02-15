# Logic Theorem Optimizer

A stochastic gradient descent (SGD) based system for generating and optimizing logical theorems from arbitrary data types.

## Quick Start (Recommended)

**Use the unified `LogicTheoremOptimizer` for new code** - it provides the same functionality through a standardized interface:

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import LogicTheoremOptimizer
from ipfs_datasets_py.optimizers.common import OptimizerConfig, OptimizationContext

# Configure optimizer
config = OptimizerConfig(
    max_iterations=10,
    target_score=0.85,
    metrics_enabled=True
)

# Create optimizer
optimizer = LogicTheoremOptimizer(
    config=config,
    use_provers=['z3', 'cvc5'],
    domain='legal'
)

# Run optimization
context = OptimizationContext(
    session_id="session-001",
    input_data="All employees must complete training annually",
    domain="legal"
)

result = optimizer.run_session(
    data="All employees must complete training annually",
    context=context
)

print(f"Score: {result['score']}")
print(f"Valid: {result['valid']}")
print(f"Iterations: {result['iterations']}")
print(f"Metrics: {result['metrics']}")
```

### Why LogicTheoremOptimizer?

- ✅ **Automatic metrics collection** via BaseOptimizer
- ✅ **Consistent API** across all optimizer types
- ✅ **Built-in performance optimization** with caching
- ✅ **Better resource management**
- ✅ **Standardized configuration** with OptimizerConfig

### Migration from Legacy Classes

See [MIGRATION_GUIDE.md](#migration-guide) below for migrating from:
- `TheoremSession` → `LogicTheoremOptimizer`
- `LogicHarness` → `LogicTheoremOptimizer` with batch processing
- `SessionConfig` → `OptimizerConfig`

## Status

✅ **Phase 1 Complete**: Foundation (6 core components, 2,628 LOC)  
✅ **Phase 2 Complete**: Integration Layer (5 integrations, 2,789 LOC)  
✅ **Phase 2.1 Complete**: Unified Optimizer (LogicTheoremOptimizer with BaseOptimizer)  
📊 **Total Delivered**: 5,417 LOC + 36+ tests + comprehensive documentation

**Phase 2 Integrations**:
- ✅ 5 Theorem Provers (Z3, CVC5, Lean, Coq, SymbolicAI)
- ✅ 2 Logic Frameworks (TDFOL, CEC with 127+ inference rules)
- ✅ 5 Logic Formalisms (FOL, TDFOL, CEC, Modal, Deontic)
- ✅ 2 LLM Backends (ipfs_accelerate_py + Mock)
- ✅ 3 Knowledge Graph Components
- ✅ 1 RAG System (LogicEnhancedRAG)
- ✅ 1 Unified Optimizer (BaseOptimizer integration)

See [PHASE2_COMPLETE.md](PHASE2_COMPLETE.md) for full Phase 2 details.

## Overview

This system adapts the adversarial harness architecture from the [complaint-generator](https://github.com/endomorphosis/complaint-generator) repository to create a logic optimizer that:

1. **Extracts** logical statements from arbitrary data using AI models
2. **Evaluates** the quality using theorem provers and consistency checkers
3. **Optimizes** extraction through iterative refinement (SGD-like approach)
4. **Maintains** knowledge graph ontology consistency

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Input Data                               │
│     (Text, JSON, Knowledge Graphs, Structured Data)         │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  Logic Theorem Optimizer                    │
│  ┌────────────────────────────────────────────────────┐     │
│  │  Logic Harness (Parallel Batch Processor)          │     │
│  │  - Runs multiple sessions concurrently             │     │
│  │  - Handles failures and retries                    │     │
│  │  - Aggregates results                              │     │
│  └────────────────────────────────────────────────────┘     │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
         ┌───────────────────────────────────┐
         │    Theorem Session                │
         │  ┌─────────────────────────────┐  │
         │  │  1. LogicExtractor (LLM)    │  │
         │  │     - Parse natural lang.   │  │
         │  │     - Extract FOL/TDFOL     │  │
         │  │     - Maintain consistency  │  │
         │  └─────────────────────────────┘  │
         │            ↓                      │
         │  ┌─────────────────────────────┐  │
         │  │  2. LogicCritic             │  │
         │  │     - Soundness check       │  │
         │  │     - Completeness          │  │
         │  │     - Ontology alignment    │  │
         │  │     - Theorem provers       │  │
         │  └─────────────────────────────┘  │
         │            ↓                      │
         │  ┌─────────────────────────────┐  │
         │  │  3. Feedback Loop           │  │
         │  │     - Refine extraction     │  │
         │  │     - Adjust prompts        │  │
         │  │     - Iterate until conv.   │  │
         │  └─────────────────────────────┘  │
         └───────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    Logic Optimizer                          │
│  - Analyzes critic scores across sessions                   │
│  - Identifies patterns and trends                           │
│  - Generates optimization recommendations                   │
│  - Tracks improvement over SGD cycles                       │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Knowledge Graph Stabilizer                     │
│  - Ensures ontology consistency                             │
│  - Validates new statements                                 │
│  - Tracks stability metrics                                 │
└─────────────────────────────────────────────────────────────┘
```

## Components

### 1. LogicExtractor

LLM-based agent that extracts formal logical statements from arbitrary data.

**Supported Logic Formalisms:**
- FOL (First-Order Logic)
- TDFOL (Temporal Deontic First-Order Logic)
- CEC (Cognitive Event Calculus)
- Modal Logic (K, S4, S5)
- Deontic Logic

**Features:**
- Automatic formalism selection
- Ontology-aware extraction
- Iterative refinement based on feedback
- Confidence scoring

**Example:**
```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import LogicExtractor, LogicExtractionContext

extractor = LogicExtractor(model="gpt-4")
context = LogicExtractionContext(
    data="All employees must complete training within 30 days",
    extraction_mode=ExtractionMode.TDFOL,
    domain="legal"
)
result = extractor.extract(context)
print(result.statements[0].formula)
# Output: ∀x (Employee(x) → ◇≤30 Completed(x, training))
```

### 2. LogicCritic

Evaluates logical statement quality across multiple dimensions using theorem provers.

**Evaluation Dimensions (with weights):**
- **Soundness (30%)**: Logical validity via theorem provers
- **Completeness (20%)**: Coverage of input data
- **Consistency (20%)**: Internal consistency
- **Ontology Alignment (15%)**: Alignment with KG ontology
- **Parsability (10%)**: Can be parsed by provers
- **Expressiveness (5%)**: Captures nuance

**Integrated Theorem Provers:**
- Z3 (SMT solver)
- CVC5 (SMT solver)
- Lean (Interactive theorem prover)
- Coq (Interactive theorem prover)
- SymbolicAI (Neural-symbolic prover)

**Example:**
```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import LogicCritic

critic = LogicCritic(use_provers=['z3', 'cvc5'])
score = critic.evaluate(extraction_result)
print(f"Overall: {score.overall:.2f}")
print(f"Soundness: {score.get_dimension_score(CriticDimensions.SOUNDNESS):.2f}")
print("Recommendations:", score.recommendations)
```

### 3. LogicOptimizer

SGD-based optimizer that analyzes feedback and generates recommendations.

**Analysis Types:**
- Batch analysis (single batch of sessions)
- Trend analysis (multiple batches over time)
- Pattern identification
- Convergence detection

**Example:**
```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import LogicOptimizer

optimizer = LogicOptimizer(convergence_threshold=0.85)

# Analyze batch
report = optimizer.analyze_batch(session_results)
print(f"Average Score: {report.average_score:.2f}")
print(f"Trend: {report.trend}")
print("Top Recommendations:")
for rec in report.recommendations[:3]:
    print(f"  - {rec}")
```

### 4. TheoremSession

Single extraction session with iterative refinement.

**Process:**
1. Extract logical statements from data
2. Evaluate with critic
3. Refine based on feedback
4. Repeat until convergence or max rounds

**Example:**
```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import TheoremSession, SessionConfig

extractor = LogicExtractor(model="gpt-4")
critic = LogicCritic(use_provers=['z3'])

session = TheoremSession(
    extractor=extractor,
    critic=critic,
    config=SessionConfig(max_rounds=10, convergence_threshold=0.85)
)

result = session.run(data="All employees must complete training")
print(f"Converged: {result.converged}")
print(f"Score: {result.critic_score.overall:.2f}")
print(f"Rounds: {result.num_rounds}")
```

### 5. LogicHarness

Batch processing with parallel execution.

**Features:**
- Parallel session execution
- Automatic retry on failure
- Progress tracking
- Comprehensive reporting

**Example:**
```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import LogicHarness, HarnessConfig

harness = LogicHarness(
    extractor=extractor,
    critic=critic,
    config=HarnessConfig(parallelism=4, max_retries=3)
)

data_samples = ["Sample 1", "Sample 2", "Sample 3", ...]
result = harness.run_sessions(data_samples)

print(f"Success Rate: {result.successful_sessions / result.total_sessions:.1%}")
print(f"Average Score: {result.average_score:.2f}")
print(f"Best Score: {result.best_score:.2f}")
```

### 6. KnowledgeGraphStabilizer

Maintains knowledge graph ontology consistency.

**Features:**
- Incremental consistency checking
- Ontology evolution tracking
- Stability metrics
- Safe statement addition

**Example:**
```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import KnowledgeGraphStabilizer

ontology = {
    'terms': ['Employee', 'Training', 'Completed'],
    'relations': ['must', 'within'],
    'types': ['Agent', 'Action', 'Temporal']
}

stabilizer = KnowledgeGraphStabilizer(ontology, strict_mode=True)

for statement in extracted_statements:
    if stabilizer.can_add_safely(statement):
        stabilizer.add_statement(statement)
    else:
        print(f"Statement would break consistency: {statement}")

print(f"Stability Score: {stabilizer.get_stability_score():.2f}")
```

## Integration

### With ipfs_accelerate_py

The LogicExtractor integrates with ipfs_accelerate_py for AI model inference:

```python
import ipfs_accelerate_py

extractor = LogicExtractor(
    model="gpt-4",
    use_ipfs_accelerate=True
)
```

### With Theorem Provers

Integrates with existing theorem prover infrastructure:

```python
# Uses existing prover bridges from logic/external_provers/
critic = LogicCritic(use_provers=['z3', 'cvc5', 'lean'])
```

### With TDFOL/CEC

Leverages existing logic frameworks:

```python
context = LogicExtractionContext(
    data="...",
    extraction_mode=ExtractionMode.TDFOL  # or CEC, FOL, etc.
)
```

### With Knowledge Graphs

Maintains consistency with knowledge graph ontologies:

```python
from ipfs_datasets_py.rag.logic_integration import LogicAwareKnowledgeGraph

kg = LogicAwareKnowledgeGraph()
ontology = kg.get_ontology()

stabilizer = KnowledgeGraphStabilizer(ontology)
```

## Usage Patterns

### Basic Single Session

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    LogicExtractor,
    LogicCritic,
    TheoremSession
)

# Setup
extractor = LogicExtractor(model="gpt-4")
critic = LogicCritic(use_provers=['z3'])

# Run session
session = TheoremSession(extractor, critic)
result = session.run("All employees must complete training")

print(f"Score: {result.critic_score.overall:.2f}")
print(f"Statements: {len(result.extraction_result.statements)}")
```

### Batch Processing

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import LogicHarness

harness = LogicHarness(extractor, critic)

data_samples = [
    "All employees must complete training",
    "Contractors may access the building",
    "Managers should approve requests within 48 hours"
]

result = harness.run_sessions(data_samples)
print(f"Success Rate: {result.successful_sessions / result.total_sessions:.1%}")
```

### SGD Optimization Cycles

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import LogicOptimizer

optimizer = LogicOptimizer()
harness = LogicHarness(extractor, critic)

# Run multiple optimization cycles
for cycle in range(10):
    # Run batch
    results = harness.run_sessions(data_samples)
    
    # Analyze and optimize
    report = optimizer.analyze_batch(results.session_results)
    
    print(f"Cycle {cycle + 1}:")
    print(f"  Score: {report.average_score:.2f}")
    print(f"  Trend: {report.trend}")
    
    # Check convergence
    if report.convergence_status == "converged":
        print(f"Converged after {cycle + 1} cycles!")
        break
```

### With Ontology Consistency

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import KnowledgeGraphStabilizer

# Define ontology
ontology = {
    'terms': ['Employee', 'Training', 'Manager', 'Request'],
    'relations': ['must', 'should', 'may'],
    'types': ['Agent', 'Action']
}

# Create stabilizer
stabilizer = KnowledgeGraphStabilizer(ontology, strict_mode=True)

# Run extraction with stability checking
for data in data_samples:
    result = session.run(data)
    
    if result.success:
        added = stabilizer.add_statements(result.extraction_result.statements)
        print(f"Added {added}/{len(result.extraction_result.statements)} statements")
        print(f"Stability: {stabilizer.get_stability_score():.2f}")
```

## Key Features

1. **SGD-Based Optimization**: Iterative improvement through feedback loops
2. **Multi-Prover Integration**: Uses Z3, CVC5, Lean, Coq, SymbolicAI
3. **Ontology Consistency**: Maintains knowledge graph stability
4. **Parallel Processing**: Efficient batch processing with parallelism
5. **Multi-Dimensional Evaluation**: 6 evaluation dimensions with weights
6. **Adaptive Learning**: Improves from critic feedback
7. **Multiple Logic Formalisms**: FOL, TDFOL, CEC, Modal, Deontic

## Performance Metrics

- **Convergence Rate**: Percentage of sessions reaching convergence
- **Average Rounds**: Average refinement rounds per session
- **Success Rate**: Percentage of successful extractions
- **Stability Score**: Knowledge graph ontology stability (0-1)
- **Dimension Scores**: Per-dimension quality metrics

## Best Practices

1. **Start Small**: Begin with single sessions before batch processing
2. **Choose Appropriate Formalism**: Use domain-specific logic (TDFOL for legal, CEC for temporal)
3. **Monitor Convergence**: Track improvement over SGD cycles
4. **Maintain Ontology**: Keep knowledge graph consistent with stabilizer
5. **Use Multiple Provers**: Leverage different provers for robustness
6. **Iterate on Feedback**: Apply critic recommendations between cycles

## Future Enhancements

- [x] ~~Neural-symbolic hybrid provers~~ **IMPLEMENTED** ✅
- [x] ~~Advanced prompt optimization strategies~~ **IMPLEMENTED** ✅
- [x] ~~Real-time ontology evolution~~ **IMPLEMENTED** ✅
- [x] ~~Distributed processing support~~ **IMPLEMENTED** ✅
- [ ] Integration with more theorem provers
- [ ] Advanced conflict resolution
- [ ] Automated prompt engineering

### Completed Enhancements

#### 1. Neural-Symbolic Hybrid Prover (Phase 1) ✅

Combines neural LLM-based reasoning with symbolic theorem proving for robust verification.

**Module**: `neural_symbolic_prover.py` (693 LOC)

**Features**:
- 5 combination strategies: NEURAL_FIRST, SYMBOLIC_FIRST, PARALLEL, ENSEMBLE, ADAPTIVE
- Intelligent fallback when one approach fails
- Confidence score combination from both paradigms
- Natural language explanations from neural component
- Formal verification from symbolic component

**Usage**:
```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    NeuralSymbolicHybridProver,
    HybridStrategy
)

# Initialize with parallel strategy
prover = NeuralSymbolicHybridProver(
    strategy=HybridStrategy.PARALLEL,
    neural_provers=['symbolicai'],
    symbolic_provers=['z3', 'cvc5'],
    neural_weight=0.4,
    symbolic_weight=0.6
)

# Prove a formula
result = prover.prove("∀x (P(x) → Q(x))")

print(f"Valid: {result.is_valid}")
print(f"Confidence: {result.confidence:.2f}")
print(f"Agreement: {result.agreement}")
print(f"Explanation: {result.explanation}")

# Get statistics
stats = prover.get_statistics()
print(f"Cache size: {stats['cache_size']}")
```

**Tests**: 30 comprehensive tests covering all strategies and edge cases

#### 2. Advanced Prompt Optimization (Phase 2) ✅

Optimizes prompts for logic extraction using multiple strategies and metrics.

**Module**: `prompt_optimizer.py` (622 LOC)

**Features**:
- 6 optimization strategies: A/B testing, multi-armed bandit, genetic algorithm, hill climbing, simulated annealing, reinforcement learning
- Comprehensive metrics: success rate, confidence, critic score, extraction time
- Domain and formalism-specific performance tracking
- Prompt library with versioning
- Export/import for sharing prompt libraries

**Usage**:
```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    PromptOptimizer,
    OptimizationStrategy
)

# Initialize optimizer
optimizer = PromptOptimizer(
    strategy=OptimizationStrategy.MULTI_ARMED_BANDIT,
    exploration_rate=0.1
)

# Add baseline prompt
optimizer.add_baseline_prompt("Extract logic from: {data}")

# Add alternative prompts
optimizer.add_prompt(
    "Analyze {data} and extract {formalism} logical statements",
    parameters={"formalism": "TDFOL"}
)

optimizer.add_prompt(
    "Convert the following to formal logic: {data}"
)

# Record usage
optimizer.record_usage(
    prompt_id="prompt1",
    success=True,
    confidence=0.9,
    critic_score=0.85,
    extraction_time=1.5,
    domain="legal",
    formalism="tdfol"
)

# Get best prompt for a domain
best_prompt = optimizer.get_best_prompt(domain="legal")
print(f"Best prompt: {best_prompt.template}")

# Optimize prompts
result = optimizer.optimize(training_data, max_iterations=20)
print(f"Best score: {result.best_score:.2f}")
print(f"Improvement: {result.improvement_over_baseline:.2f}")

# Export library
optimizer.export_library("prompts.json")
```

**Tests**: 31 comprehensive tests covering all strategies and metrics


## Migration Guide

### Migrating from TheoremSession

**Old Code (Deprecated):**
```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    TheoremSession, LogicExtractor, LogicCritic, SessionConfig
)

extractor = LogicExtractor(model="gpt-4")
critic = LogicCritic(use_provers=['z3'])
session = TheoremSession(
    extractor=extractor,
    critic=critic,
    config=SessionConfig(
        max_rounds=10,
        convergence_threshold=0.85
    )
)

result = session.run(
    data="All employees must complete training",
    context={'domain': 'legal'}
)

print(f"Converged: {result.converged}")
print(f"Score: {result.critic_score.overall}")
```

**New Code (Recommended):**
```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import LogicTheoremOptimizer
from ipfs_datasets_py.optimizers.common import OptimizerConfig, OptimizationContext

optimizer = LogicTheoremOptimizer(
    config=OptimizerConfig(
        max_iterations=10,
        target_score=0.85
    ),
    use_provers=['z3'],
    domain='legal'
)

context = OptimizationContext(
    session_id="session-001",
    input_data="All employees must complete training",
    domain="legal"
)

result = optimizer.run_session(
    data="All employees must complete training",
    context=context
)

print(f"Valid: {result['valid']}")
print(f"Score: {result['score']}")
print(f"Iterations: {result['iterations']}")
print(f"Metrics: {result['metrics']}")
```

**Key Differences:**
- ✅ No need to manually create extractor/critic instances
- ✅ Automatic metrics collection via `result['metrics']`
- ✅ Standardized configuration with `OptimizerConfig`
- ✅ Better error handling and resource management

### Migrating from LogicHarness (Batch Processing)

**Old Code (Deprecated):**
```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    LogicHarness, LogicExtractor, LogicCritic, HarnessConfig
)

extractor = LogicExtractor(model="gpt-4")
critic = LogicCritic(use_provers=['z3', 'cvc5'])
harness = LogicHarness(
    extractor=extractor,
    critic=critic,
    config=HarnessConfig(parallelism=4)
)

data_samples = ["Sample 1", "Sample 2", "Sample 3"]
result = harness.run_sessions(data_samples)

print(f"Success rate: {result.successful_sessions / result.total_sessions}")
print(f"Average score: {result.average_score}")
```

**New Code (Recommended):**
```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import LogicTheoremOptimizer
from ipfs_datasets_py.optimizers.common import OptimizerConfig, OptimizationContext
from concurrent.futures import ThreadPoolExecutor, as_completed

optimizer = LogicTheoremOptimizer(
    config=OptimizerConfig(
        max_iterations=10,
        target_score=0.85,
        metrics_enabled=True
    ),
    use_provers=['z3', 'cvc5']
)

data_samples = ["Sample 1", "Sample 2", "Sample 3"]
results = []

# Process in parallel
with ThreadPoolExecutor(max_workers=4) as executor:
    futures = []
    for i, sample in enumerate(data_samples):
        context = OptimizationContext(
            session_id=f"session-{i}",
            input_data=sample,
            domain="general"
        )
        future = executor.submit(optimizer.run_session, sample, context)
        futures.append(future)
    
    for future in as_completed(futures):
        result = future.result()
        results.append(result)

# Calculate metrics
successful = [r for r in results if r['valid']]
success_rate = len(successful) / len(results)
avg_score = sum(r['score'] for r in successful) / len(successful)

print(f"Success rate: {success_rate}")
print(f"Average score: {avg_score}")
```

**Key Differences:**
- ✅ More control over parallelism using standard Python libraries
- ✅ Better error handling with futures
- ✅ Each session gets full metrics automatically
- ✅ Can customize per-session configurations

### Configuration Mapping

| Old (SessionConfig/HarnessConfig) | New (OptimizerConfig) |
|-----------------------------------|----------------------|
| `max_rounds` | `max_iterations` |
| `convergence_threshold` | `target_score` |
| `parallelism` | Use `ThreadPoolExecutor(max_workers=N)` |
| `max_retries` | Handle in executor submit |
| `timeout_per_session` | Use `future.result(timeout=...)` |

### Result Mapping

| Old (SessionResult) | New (result dict) |
|--------------------|-------------------|
| `result.converged` | `result['score'] >= config.target_score` |
| `result.critic_score.overall` | `result['score']` |
| `result.num_rounds` | `result['iterations']` |
| `result.success` | `result['valid']` |
| `result.total_time` | `result['execution_time']` |
| `result.extraction_result` | `result['artifact']` |

## See Also

- [complaint-generator](https://github.com/endomorphosis/complaint-generator) - Original adversarial harness inspiration
- [Logic Integration](/ipfs_datasets_py/logic/README.md) - Existing logic frameworks
- [GraphRAG Integration](/ipfs_datasets_py/rag/README.md) - Knowledge graph integration
- [Theorem Provers](/ipfs_datasets_py/logic/external_provers/README.md) - Integrated provers
