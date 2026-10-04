# Optimizer Architecture Diagrams

Visual lifecycle flows for each optimizer type in the `ipfs_datasets_py` optimizers module.

**Purpose**: Quick reference for understanding how each optimizer processes input, generates improvements, and validates results.

---

## 1. Universal Optimizer Lifecycle (All Types)

Every optimizer follows this high-level OODA loop (Observe → Orient → Decide → Act):

```mermaid
graph TD
    A["Start: Receive Input<br/>(code/ontology/theorem)"] --> B["Parse & Validate<br/>(syntax check, schema)"]
    B --> C{"Input Valid?"}
    C -->|No| D["Return Error<br/>(validation details)"]
    C -->|Yes| E["Run Optimization Loop<br/>(method-specific)"]
    E --> F["Generate Candidates<br/>(1+ improvements)"]
    F --> G["Score Improvements<br/>(metrics/heuristics)"]
    G --> H["Validate Changes<br/>(unit tests, types)"]
    H --> I{"Pass Validation?"}
    I -->|No| J["Refine & Retry<br/>(max iterations)"]
    J --> E
    I -->|Yes| K["Apply Change<br/>(commit/patch)"]
    K --> L["Return Result<br/>(metrics + patch)"]
    L --> M["End: Success"]
    D --> M
    style A fill:#e1f5ff
    style M fill:#c8e6c9
    style D fill:#ffcdd2
```

---

## 2. Agentic Optimizer: Test-Driven Method

Generate code improvements by writing tests first, then optimizing to pass tests:

```mermaid
graph TD
    A["Start with Code"] --> B["LLM: Generate Test Suite<br/>(comprehensive coverage)"]
    B --> C["Run Original Code<br/>Against New Tests"]
    C --> D{"Tests Pass?"}
    D -->|No| E["Code is Already Wrong<br/>Capture as Baseline"]
    D -->|Yes| F["Optimization Phase 1:<br/>Fix Functional Issues"]
    E --> F
    F --> G["Run Tests Again"]
    G --> H{"Tests Pass?"}
    H -->|No| I["Debug & Fix Errors"]
    I --> G
    H -->|Yes| J["Optimization Phase 2:<br/>Improve Performance"]
    J --> K["Run Performance Benchmark<br/>(speed, memory)"]
    K --> L["Run Tests Again<br/>(verify no regression)"]
    L --> M{"Tests + Perf OK?"}
    M -->|No| N["Revert to Baseline<br/>Try Different Approach"]
    N --> F
    M -->|Yes| O["Return Optimized Code<br/>+ Test Suite"]
    style A fill:#e1f5ff
    style O fill:#c8e6c9
    style N fill:#ffcdd2
```

---

## 3. Agentic Optimizer: Actor-Critic Method

Learn optimal improvements through reward-based feedback:

```mermaid
graph TD
    A["Initialize Actor<br/>(LLM proposal generator)"] --> B["Initialize Critic<br/>(code quality evaluator)"]
    B --> C["Loop: Iteration 1..N"]
    C --> D["Actor: Generate Code Variant<br/>(test-driven or random exploration)"]
    D --> E["Critic: Score Variant<br/>(speed/complexity/readability)"]
    E --> F["Calculate Reward<br/>score - baseline"]
    F --> G{"Reward > Threshold?"}
    G -->|Yes| H["Keep Variant<br/>Update Actor Policy"]
    G -->|No| I["Discard Variant<br/>Provide Feedback to Actor"]
    H --> J{"Iterations Left?"}
    I --> J
    J -->|Yes| C
    J -->|No| K["Best Variant = Winner<br/>Return with Metrics"]
    style A fill:#e1f5ff
    style K fill:#c8e6c9
    style I fill:#fff3e0
```

---

## 4. Agentic Optimizer: Adversarial Method

Generate competing solutions and select the best:

```mermaid
graph TD
    A["Define Optimization Goal<br/>(e.g., speed 10x faster)"] --> B["Generate N Competing Solutions<br/>(diverse strategies)"]
    B --> C["For Each Candidate:<br/>Run Tests"]
    C --> D{"Tests Pass?"}
    D -->|No| E["Discard Candidate"]
    D -->|Yes| F["Benchmark Against Baseline<br/>(speed/memory/complexity)"]
    E --> G["Score Remaining Candidates"]
    F --> G
    G --> H["Rank by Score"]
    H --> I["Select Top K Candidates"]
    I --> J["Ensemble Vote<br/>Combine Best Features"]
    J --> K["Validate Ensemble<br/>Run Full Test Suite"]
    K --> L{"Ensemble Valid?"}
    L -->|No| M["Fall Back to Top 1"]
    L -->|Yes| M
    M --> N["Return Best Solution<br/>+ Explanation"]
    style A fill:#e1f5ff
    style N fill:#c8e6c9
    style E fill:#ffcdd2
```

---

## 5. Logic Theorem Optimizer

Prove & improve mathematical theorems using formal logic:

```mermaid
graph TD
    A["Start: Receive Theorem<br/>+ Axioms (TDFOL format)"] --> B["Parse TDFOL Statements<br/>Check Syntax"]
    B --> C["Phase 1: Generate<br/>Use LLM + Creativity"]
    C --> D["LLM Proposes N Proofs<br/>(different strategies)"]
    D --> E["Prover Adapter: Validate Each<br/>(can we prove theorem?)"]
    E --> F{"Any Proof Valid?"}
    F -->|No| G["Phase 1 Failed<br/>Generate More Candidates"]
    G --> D
    F -->|Yes| H["Phase 2: Critique<br/>Score Proofs on:<br/>- Elegance<br/>- Length<br/>- Novelty"]
    H --> I["Assign Scores:<br/>Dimension 1: 0-10"]
    I --> J["Select Top-3 Proofs<br/>by Composite Score"]
    J --> K["Phase 3: Optimize<br/>Remove Redundant Steps"]
    K --> L["Generalize Where Possible<br/>(broader theorems)"]
    L --> M["Re-Validate<br/>Prover Adapter"]
    M --> N{"Still Valid?"}
    N -->|No| O["Keep Unoptimized Version"]
    N -->|Yes| O
    O --> P["Return Best Proof<br/>+ Score Breakdown"]
    style A fill:#e1f5ff
    style P fill:#c8e6c9
    style G fill:#fff3e0
```

---

## 6. GraphRAG Optimizer

Generate & improve knowledge graphs from unstructured text:

```mermaid
graph TD
    A["Start: Receive Text<br/>+ Domain Context"] --> B["Phase 1: Extract<br/>(rule-based + optional LLM)"]
    B --> C["Entity Extraction<br/>(regex or NER)"]
    C --> D["Relationship Inference<br/>(verb-frame heuristics)"]
    D --> E["Merge Duplicate Entities<br/>(fuzzy matching)"]
    E --> F["Output: Ontology Dict<br/>{entities, relationships, metadata}"]
    F --> G["Phase 2: Validate<br/>(schema + TDFOL conversion)"]
    G --> H["Check Schema:<br/>required fields, types"]
    H --> I{"Schema Valid?"}
    I -->|No| J["Return Validation Errors<br/>Suggest Fixes"]
    I -->|Yes| K["Convert to TDFOL<br/>(for theorem proving)"]
    K --> L["Critic: Score Ontology<br/>Completeness, Consistency,<br/>Clarity, Granularity"]
    L --> M["Store Metrics"]
    M --> N["Phase 3: Optimize<br/>(iterative refinement)"]
    N --> O["Identify Patterns<br/>from Previous Runs"]
    O --> P["Generate Recommendations<br/>(add/remove/merge)"]
    P --> Q["User Reviews Recommendations"]
    Q --> R["Apply Top-K Changes"]
    R --> G
    R -->|After N iterations| S["Return Optimized Ontology<br/>+ Learning Metrics"]
    style A fill:#e1f5ff
    style S fill:#c8e6c9
    style J fill:#ffcdd2
```

---

## 7. Integration: Multi-Optimizer Pipeline

How optimizers can be chained for compound improvements:

```mermaid
graph TD
    A["Input: Unoptimized Code<br/>+ Domain Context"] --> B["Step 1: GraphRAG<br/>Build Knowledge Graph<br/>of Code Structure"]
    B --> C["Step 2: Logic Theorem<br/>Prove Code Correctness<br/>Against Spec"]
    C --> D{"Proof Successful?"}
    D -->|No| E["Return Proof Gaps<br/>as Improvement Targets"]
    D -->|Yes| F["Step 3: Agentic (Test-Driven)<br/>Generate Tests from KG"]
    E --> F
    F --> G["Step 4: Agentic (Actor-Critic)<br/>Iteratively Improve<br/>While Tests Pass"]
    G --> H["Final Validation:<br/>All Tests + Proof Valid?"]
    H --> I{"Valid?"}
    I -->|No| J["Backtrack to Previous Step"]
    J --> G
    I -->|Yes| K["Return Optimized Code<br/>+ Proof + Tests<br/>+ Knowledge Graph"]
    style A fill:#e1f5ff
    style K fill:#c8e6c9
    style J fill:#fff3e0
```

---

## 8. Configuration & Context Flow

How context objects flow through optimizer layers:

```mermaid
graph LR
    A["OptimizerConfig<br/>-method<br/>-provider<br/>-limits"] --> B["Agentic Optimizer<br/>Input: Task"]
    B --> C["LLM Router<br/>Select Provider<br/>Generate Text"]
    C --> D["Validator<br/>Syntax Check<br/>Type Check"]
    D --> E["Change Controller<br/>Create Patch<br/>Apply Changes"]
    E --> F["Output: OptimizationResult<br/>-success<br/>-metrics<br/>-patch"]
    A -.->|applies to| C
    A -.->|applies to| D
    A -.->|applies to| E
    style A fill:#bbdefb
    style F fill:#c8e6c9
```

---

## 9. Error Handling & Fallback Flow

How optimizers gracefully degrade:

```mermaid
graph TD
    A["Start Optimization"] --> B["Try Preferred Method"]
    B --> C{"Success?"}
    C -->|Yes| D["Return Full Result"]
    C -->|No| E["Log Error<br/>Circuit Breaker -1"]
    E --> F{"Circuit Breaker<br/>Failed < Threshold?"}
    F -->|Yes| G["Try Fallback Method<br/>(different strategy)"]
    F -->|No| H["Circuit Breaker OPEN<br/>Wait timeout"]
    H --> I["Return Degraded Mode<br/>(no optimization,<br/>baseline code only)"]
    G --> J{"Fallback Success?"}
    J -->|Yes| D
    J -->|No| I
    D --> K["End: Return to User"]
    I --> K
    style A fill:#e1f5ff
    style K fill:#c8e6c9
    style I fill:#ffecb3
```

---

## 10. Learning & Metrics Collection

How optimizers capture improvement metrics:

```mermaid
graph TD
    A["Optimization Completes"] --> B["Capture Metrics:<br/>- Baseline score<br/>- Optimized score<br/>- Delta"]
    B --> C["Store Session:<br/>- Input parameters<br/>- Method used<br/>- Execution time<br/>- Errors/warnings"]
    C --> D["Analysis:<br/>Which patterns<br/>led to success?"]
    D --> E["Update Learning State:<br/>Increase weight for<br/>successful patterns"]
    E --> F["Aggregate Stats:<br/>Success rate<br/>Avg improvement %<br/>Most common errors"]
    F --> G["Export for Visualization<br/>(dashboard/reports)"]
    G --> H["Next Optimizer Session<br/>Uses Updated Weights"]
    style A fill:#e1f5ff
    style H fill:#c8e6c9
```

---

## Key Takeaways

| Aspect | Details |
|--------|---------|
| **Input** | Code / Ontology / Theorem (TDFOL) |
| **Validation** | Syntax check + schema validation + type hints |
| **Methods** | Test-Driven, Actor-Critic, Adversarial, Chaos (agentic); Generate-Critique-Optimize (logic/graphrag) |
| **Output** | Optimized code/ontology/proof + metrics + patch |
| **Resilience** | Circuit breaker pattern + retry with exponential backoff |
| **Learning** | Track success patterns; adjust weights for future runs |
| **Integration** | Optimizers can be chained in pipelines |

---

## How to Use These Diagrams

- **For Users**: Start with diagrams 1 + 2/5/6 (depending on your optimizer type)
- **For Contributors**: Use diagrams 3-10 for understanding internal flow
- **For Integration**: See diagram 7 for multi-optimizer composition
- **For Debugging**: See diagrams 9-10 for error handling and observability

See [QUICK_START.md](./agentic/QUICK_START.md) / [QUICK_START.md](./logic_theorem_optimizer/QUICK_START.md) / [QUICK_START.md](./graphrag/QUICK_START.md) for detailed examples.
