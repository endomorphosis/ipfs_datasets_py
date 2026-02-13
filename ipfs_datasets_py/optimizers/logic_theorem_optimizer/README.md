# Logic Theorem Optimizer

A stochastic gradient descent (SGD) based system for generating and optimizing logical theorems from arbitrary data types.

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

- [ ] Neural-symbolic hybrid provers
- [ ] Advanced prompt optimization strategies
- [ ] Real-time ontology evolution
- [ ] Distributed processing support
- [ ] Integration with more theorem provers
- [ ] Advanced conflict resolution
- [ ] Automated prompt engineering

## See Also

- [complaint-generator](https://github.com/endomorphosis/complaint-generator) - Original adversarial harness inspiration
- [Logic Integration](/ipfs_datasets_py/logic/README.md) - Existing logic frameworks
- [GraphRAG Integration](/ipfs_datasets_py/rag/README.md) - Knowledge graph integration
- [Theorem Provers](/ipfs_datasets_py/logic/external_provers/README.md) - Integrated provers
