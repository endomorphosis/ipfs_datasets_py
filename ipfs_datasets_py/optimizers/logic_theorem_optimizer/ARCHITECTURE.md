# Logic Theorem Optimizer - Architecture Overview

## Executive Summary

The Logic Theorem Optimizer is a production-ready system for extracting, evaluating, and optimizing logical theorems from arbitrary data types using stochastic gradient descent (SGD) principles. Inspired by the [adversarial harness pattern](https://github.com/endomorphosis/complaint-generator/blob/master/adversarial_harness/README.md) from the complaint-generator repository, this system applies adversarial optimization techniques to logic extraction and theorem proving.

## System Architecture

### Core Philosophy

The system follows a **three-agent pattern**:
1. **Generator (LogicExtractor)** - Produces logical statements
2. **Evaluator (LogicCritic)** - Assesses quality across multiple dimensions
3. **Optimizer (LogicOptimizer)** - Analyzes feedback and drives improvement

This mirrors the complaint-generator's Complainant-Mediator-Critic pattern, adapted for logic extraction.

### Component Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     INPUT DATA LAYER                            │
│  Text | JSON | Knowledge Graphs | Structured Data | Mixed       │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                  EXTRACTION LAYER                               │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  LogicExtractor (LLM-based Agent)                        │   │
│  │  • Parses natural language → formal logic                │   │
│  │  • Supports FOL, TDFOL, CEC, Modal, Deontic              │   │
│  │  • Automatic formalism selection                         │   │
│  │  • Ontology-aware extraction                             │   │
│  │  • Confidence scoring                                    │   │
│  └──────────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                   EVALUATION LAYER                              │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  LogicCritic (Multi-Dimensional Evaluator)               │   │
│  │  • Soundness (30%): Theorem prover verification          │   │
│  │  • Completeness (20%): Coverage analysis                 │   │
│  │  • Consistency (20%): Contradiction detection            │   │
│  │  • Ontology Alignment (15%): KG compatibility            │   │
│  │  • Parsability (10%): Prover compatibility               │   │
│  │  • Expressiveness (5%): Nuance capture                   │   │
│  └──────────────────────────────────────────────────────────┘   │
│  Integration: Z3, CVC5, Lean, Coq, SymbolicAI                   │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                  OPTIMIZATION LAYER                             │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  LogicOptimizer (SGD Engine)                             │   │
│  │  • Batch analysis                                        │   │
│  │  • Trend detection                                       │   │
│  │  • Pattern identification                                │   │
│  │  • Convergence monitoring                                │   │
│  │  • Recommendation generation                             │   │
│  └──────────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                 ORCHESTRATION LAYER                             │
│  ┌────────────────────┐  ┌──────────────────────────────────┐   │
│  │  TheoremSession    │  │  LogicHarness                    │   │
│  │  • Single cycle    │  │  • Batch processing              │   │
│  │  • Refinement loop │  │  • Parallel execution            │   │
│  │  • Convergence     │  │  • Retry logic                   │   │
│  └────────────────────┘  └──────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                  CONSISTENCY LAYER                              │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  KnowledgeGraphStabilizer                                │   │
│  │  • Ontology consistency checking                         │   │
│  │  • Safe statement addition                               │   │
│  │  • Stability metrics                                     │   │
│  │  • Ontology evolution                                    │   │
│  └──────────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
                 ┌───────────────┐
                 │ Verified      │
                 │ Theorems      │
                 └───────────────┘
```

## Detailed Component Design

### 1. LogicExtractor (Generator Agent)

**Purpose**: Extract formal logical statements from arbitrary data using LLM inference.

**Key Features**:
- Multi-formalism support (FOL, TDFOL, CEC, Modal, Deontic)
- Automatic formalism selection based on domain and data characteristics
- Iterative refinement based on critic feedback
- Ontology-aware extraction
- Confidence scoring for each extracted statement

**Implementation Strategy**:
```python
class LogicExtractor:
    def extract(context: LogicExtractionContext) -> ExtractionResult:
        # 1. Determine extraction mode (if AUTO)
        mode = determine_mode(context)
        
        # 2. Build LLM prompt with:
        #    - Domain context
        #    - Ontology constraints
        #    - Previous extractions (for consistency)
        #    - Hints from critic
        prompt = build_prompt(context)
        
        # 3. Query LLM (via ipfs_accelerate_py)
        response = query_llm(prompt)
        
        # 4. Parse response into structured statements
        statements = parse_response(response, context)
        
        # 5. Check ontology alignment
        alignment = check_alignment(statements, context.ontology)
        
        return ExtractionResult(statements, alignment)
```

**Integration Points**:
- `ipfs_accelerate_py` for LLM inference
- Existing logic frameworks (TDFOL, CEC) for parsing validation
- Knowledge graphs for ontology constraints

### 2. LogicCritic (Evaluator Agent)

**Purpose**: Multi-dimensional evaluation of extracted logical statements.

**Evaluation Dimensions**:

| Dimension | Weight | Description | Method |
|-----------|--------|-------------|--------|
| Soundness | 30% | Logical validity | Theorem prover verification |
| Completeness | 20% | Coverage of input | Term overlap analysis |
| Consistency | 20% | No contradictions | Inter-statement checking |
| Ontology Alignment | 15% | KG compatibility | Terminology + structure |
| Parsability | 10% | Prover compatible | Syntax validation |
| Expressiveness | 5% | Captures nuance | Complexity metrics |

**Theorem Prover Integration**:
```python
class LogicCritic:
    def __init__(use_provers=['z3', 'cvc5', 'lean']):
        self.provers = {
            'z3': Z3ProverBridge(),
            'cvc5': CVC5ProverBridge(),
            'lean': LeanProverBridge()
        }
    
    def evaluate_soundness(statements):
        for stmt in statements:
            for prover in self.provers.values():
                result = prover.verify(stmt.formula)
                if result.valid:
                    return high_score
        return low_score
```

**Feedback Generation**:
- Identifies specific weaknesses
- Generates actionable recommendations
- Provides dimension-specific guidance

### 3. LogicOptimizer (SGD Engine)

**Purpose**: Analyze feedback across sessions and drive iterative improvement.

**SGD-Like Optimization**:
```python
class LogicOptimizer:
    def analyze_batch(session_results):
        # 1. Calculate average score
        avg_score = mean(r.critic_score.overall for r in results)
        
        # 2. Analyze trend (improving/stable/declining)
        trend = analyze_trend(score_history)
        
        # 3. Aggregate dimension scores
        dim_metrics = aggregate_dimensions(results)
        
        # 4. Identify patterns (common weaknesses)
        insights = identify_patterns(results)
        
        # 5. Generate recommendations
        recommendations = generate_recommendations(
            dim_metrics, insights, avg_score
        )
        
        # 6. Check convergence
        convergence = check_convergence(avg_score, trend)
        
        return OptimizationReport(
            avg_score, trend, recommendations, convergence
        )
```

**Convergence Criteria**:
- Score threshold (e.g., 0.85)
- Minimal improvement rate (e.g., 0.01 per cycle)
- Trend stability

### 4. TheoremSession (Single Cycle Orchestrator)

**Purpose**: Coordinate a single extraction-evaluation-refinement cycle.

**Iterative Refinement Loop**:
```python
class TheoremSession:
    def run(data):
        for round in range(max_rounds):
            # Extract
            result = extractor.extract(context)
            
            # Evaluate
            score = critic.evaluate(result)
            
            # Check convergence
            if score.overall >= threshold:
                return SessionResult(converged=True)
            
            # Refine: provide feedback to extractor
            feedback = prepare_feedback(score, result)
            extractor.improve_from_feedback(feedback)
            
            # Update context for next round
            context.previous_extractions.append(result)
            context.hints = score.recommendations[:3]
```

**Convergence Strategy**:
- Early termination when score threshold reached
- Maximum rounds limit prevents infinite loops
- Best result tracking across rounds

### 5. LogicHarness (Batch Orchestrator)

**Purpose**: Parallel batch processing with fault tolerance.

**Parallel Execution**:
```python
class LogicHarness:
    def run_sessions(data_samples):
        with ThreadPoolExecutor(max_workers=parallelism) as executor:
            futures = []
            for data in data_samples:
                session = TheoremSession(extractor, critic)
                future = executor.submit(
                    run_with_retry, session, data
                )
                futures.append(future)
            
            results = [f.result() for f in as_completed(futures)]
        
        return HarnessResult(aggregated_metrics)
```

**Fault Tolerance**:
- Automatic retry with exponential backoff
- Timeout protection
- Graceful degradation

### 6. KnowledgeGraphStabilizer (Consistency Guardian)

**Purpose**: Ensure knowledge graph ontology stability as statements are added.

**Consistency Checking**:
```python
class KnowledgeGraphStabilizer:
    def can_add_safely(statement):
        # Check individual statement
        report = checker.check_statements([statement])
        if not report.is_consistent:
            return False
        
        # Check with existing statements
        combined = existing_statements + [statement]
        combined_report = checker.check_statements(combined)
        return combined_report.is_consistent
    
    def add_statement(statement):
        if strict_mode and not can_add_safely(statement):
            return False
        
        statements.append(statement)
        update_stability_metrics()
        return True
```

**Stability Metrics**:
- Consistency score (0-1)
- Ontology coverage
- Violation tracking
- Evolution history

## SGD Optimization Flow

### Multi-Cycle Optimization

```python
# Initialize
extractor = LogicExtractor()
critic = LogicCritic()
optimizer = LogicOptimizer()
harness = LogicHarness(extractor, critic)

# Run SGD cycles
for cycle in range(max_cycles):
    # 1. Run batch of sessions
    results = harness.run_sessions(data_samples)
    
    # 2. Analyze and optimize
    report = optimizer.analyze_batch(results.session_results)
    
    # 3. Apply recommendations (gradient descent step)
    apply_optimization(extractor, critic, report.recommendations)
    
    # 4. Check convergence
    if report.convergence_status == "converged":
        break

# Final optimized extractor
return extractor
```

### Gradient Descent Analogy

| Traditional SGD | Logic Optimizer |
|-----------------|-----------------|
| Loss function | Critic score (inverted) |
| Gradient | Recommendations |
| Parameters | Extractor prompts, thresholds |
| Learning rate | Feedback weight |
| Batch | Session batch |
| Epoch | Optimization cycle |

## Integration Architecture

### Theorem Prover Integration

```
LogicCritic
    ├── SMT Solvers
    │   ├── Z3ProverBridge
    │   └── CVC5ProverBridge
    ├── Interactive Provers
    │   ├── LeanProverBridge
    │   └── CoqProverBridge
    └── Neural-Symbolic
        └── SymbolicAIProverBridge
```

### Logic Framework Integration

```
LogicExtractor
    ├── TDFOL (Temporal Deontic FOL)
    │   └── 40 inference rules
    ├── CEC (Cognitive Event Calculus)
    │   └── 87 inference rules
    ├── FOL (First-Order Logic)
    ├── Modal Logic (K, S4, S5)
    └── Deontic Logic
```

### Knowledge Graph Integration

```
KnowledgeGraphStabilizer
    ├── LogicAwareKnowledgeGraph
    ├── LogicAwareEntityExtractor
    └── TheoremAugmentedRAG
```

## Performance Characteristics

### Complexity Analysis

| Component | Time Complexity | Space Complexity |
|-----------|----------------|------------------|
| LogicExtractor.extract | O(L) | O(S) |
| LogicCritic.evaluate | O(S × P) | O(S + P) |
| TheoremSession.run | O(R × (L + S × P)) | O(R × S) |
| LogicHarness.run_sessions | O(N/W × R × (L + S × P)) | O(N × S) |

Where:
- L = LLM inference time
- S = Number of statements
- P = Number of provers
- R = Number of refinement rounds
- N = Number of data samples
- W = Parallelism factor

### Scalability

**Horizontal Scaling**:
- Parallel session execution (configurable parallelism)
- Independent batch processing
- Stateless components (except history tracking)

**Vertical Scaling**:
- LLM model size
- Theorem prover timeout
- Batch size

## Error Handling & Resilience

### Fault Tolerance Strategy

1. **Extraction Failures**: Mock responses for testing, graceful degradation
2. **Prover Failures**: Try multiple provers, skip on timeout
3. **Session Failures**: Automatic retry with exponential backoff
4. **Batch Failures**: Partial results, continue processing

### Logging & Monitoring

- Structured logging at each layer
- Performance metrics tracking
- Error aggregation
- Convergence monitoring

## Extension Points

### Adding New Logic Formalisms

```python
# 1. Add to ExtractionMode enum
class ExtractionMode(Enum):
    MY_LOGIC = "my_logic"

# 2. Update extractor mode determination
def _determine_mode(context):
    if context.domain == "my_domain":
        return ExtractionMode.MY_LOGIC

# 3. Update prompt building
def _build_extraction_prompt(context):
    if context.extraction_mode == ExtractionMode.MY_LOGIC:
        return my_logic_prompt(context)
```

### Adding New Evaluation Dimensions

```python
# 1. Add to CriticDimensions enum
class CriticDimensions(Enum):
    MY_DIMENSION = "my_dimension"

# 2. Add weight
DIMENSION_WEIGHTS = {
    CriticDimensions.MY_DIMENSION: 0.10,
    # Adjust other weights to sum to 1.0
}

# 3. Implement evaluation method
def _evaluate_my_dimension(self, result):
    # Custom evaluation logic
    return DimensionScore(...)
```

### Adding New Theorem Provers

```python
# 1. Create prover bridge
class MyProverBridge:
    def verify(self, formula):
        # Prover-specific logic
        return result

# 2. Register in LogicCritic
def _init_provers(self):
    if 'my_prover' in self.use_provers:
        self.provers['my_prover'] = MyProverBridge()
```

## Best Practices

### For Users

1. **Start with single sessions** before batch processing
2. **Use domain-specific modes** (TDFOL for legal, CEC for temporal)
3. **Monitor convergence** - don't over-optimize
4. **Validate with stabilizer** - maintain ontology consistency
5. **Use multiple provers** - cross-validation improves confidence

### For Developers

1. **Follow the pattern** - Generator-Evaluator-Optimizer
2. **Keep components stateless** where possible
3. **Use structured feedback** - make recommendations actionable
4. **Log comprehensively** - debugging iterative systems is hard
5. **Test with mock LLMs** - don't depend on external services for tests

## Future Enhancements

### Planned Features

1. **Neural-Symbolic Integration**
   - Hybrid prover combining symbolic and neural approaches
   - Embedding-based similarity for consistency checking

2. **Advanced Prompt Engineering**
   - Automated prompt optimization
   - Domain-specific prompt templates
   - Few-shot learning from successful extractions

3. **Real-Time Ontology Evolution**
   - Automatic term extraction
   - Relation discovery
   - Conflict resolution strategies

4. **Distributed Processing**
   - Multi-machine parallelism
   - Shared state management
   - Federated optimization

5. **Interactive Mode**
   - Human-in-the-loop refinement
   - Interactive prompt adjustment
   - Real-time visualization

## Conclusion

The Logic Theorem Optimizer successfully adapts the adversarial harness pattern to create a robust, scalable system for extracting and optimizing logical theorems. By combining LLM-based extraction, multi-dimensional evaluation with theorem provers, and SGD-based optimization, it provides a complete pipeline for converting arbitrary data into verified formal logic while maintaining knowledge graph consistency.

The architecture is **production-ready**, **extensible**, and **well-tested**, with clear integration points for existing systems (TDFOL, CEC, theorem provers, knowledge graphs) and well-defined extension mechanisms for future enhancements.
