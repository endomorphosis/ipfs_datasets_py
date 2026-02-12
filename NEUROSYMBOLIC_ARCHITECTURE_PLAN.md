# Neurosymbolic Architecture Implementation Plan

## Executive Summary

This document outlines the comprehensive plan to create a **true neurosymbolic architecture** for the ipfs_datasets_py project, integrating:

1. **Symbolic Logic Systems:** TDFOL (Temporal Deontic First-Order Logic) with 50+ inference rules
2. **Neural Components:** Embeddings, LLM-based reasoning, pattern matching
3. **Knowledge Graphs:** Logic-aware GraphRAG with theorem-augmented retrieval
4. **Theorem Provers:** CEC native prover (87 rules) + modal tableaux + TDFOL prover

**Timeline:** 12 weeks (3 months)  
**Status:** Phase 1 Complete ✅ (Weeks 1-2)  
**Next:** Phase 2 (Weeks 3-4) 🔄

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│              Neurosymbolic Architecture                         │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐        │
│  │   Symbolic   │  │    Neural    │  │  Knowledge   │        │
│  │   Reasoning  │◄─┤   Networks   │─►│    Graphs    │        │
│  │  (TDFOL +    │  │ (Embeddings, │  │  (GraphRAG   │        │
│  │   CEC)       │  │   LLM)       │  │   + Logic)   │        │
│  └──────────────┘  └──────────────┘  └──────────────┘        │
│         │                 │                    │               │
│         └─────────────────┴────────────────────┘               │
│                           │                                    │
│                ┌──────────▼──────────┐                        │
│                │  Reasoning Engine   │                        │
│                │  • Hybrid search    │                        │
│                │  • Proof + neural   │                        │
│                │  • Consistency      │                        │
│                └─────────────────────┘                        │
└─────────────────────────────────────────────────────────────────┘
```

### Key Principles

1. **Hybrid Reasoning:** Combine symbolic proofs with neural pattern matching
2. **Bidirectional Integration:** Logic ↔ Embeddings ↔ Knowledge Graphs
3. **Confidence Fusion:** Merge symbolic proof scores with neural confidence
4. **End-to-End Pipeline:** Text → Logic → Proof → Knowledge Graph → Answer

---

## Phase-by-Phase Breakdown

### ✅ Phase 1: TDFOL Foundation (Weeks 1-2) - COMPLETE

**Deliverables:**
- [x] Unified TDFOL core module (542 LOC)
- [x] TDFOL parser (509 LOC)
- [x] TDFOL prover with 10+ rules (542 LOC)
- [x] TDFOL converters (414 LOC)
- [x] Basic tests and verification

**Files Created:**
1. `logic/TDFOL/tdfol_core.py` - Formula representation
2. `logic/TDFOL/tdfol_parser.py` - String → AST parser
3. `logic/TDFOL/tdfol_prover.py` - Theorem prover
4. `logic/TDFOL/tdfol_converter.py` - Format converters
5. `logic/TDFOL/README.md` - Documentation

**Verification:**
```python
from ipfs_datasets_py.logic.TDFOL import parse_tdfol, create_obligation
formula = parse_tdfol("P(x)")
obligation = create_obligation(formula)
assert obligation.to_string() == "O(P(x))"
```

---

### 🔄 Phase 2: Enhanced Prover Integration (Weeks 3-4) - IN PROGRESS

**Goals:**
1. Add 15+ temporal-deontic inference rules
2. Implement modal logic axioms (K, T, D, S4, S5)  
3. Create proof caching and optimization
4. Add comprehensive test coverage (50+ tests)

**Files to Create/Extend:**
```
logic/TDFOL/
├── tdfol_inference_rules.py        # 15+ new rules
├── tdfol_modal_axioms.py           # K, T, D, S4, S5 axioms
├── tdfol_proof_cache.py            # Proof caching
└── tdfol_optimization.py           # Proof search optimization

tests/unit_tests/logic/TDFOL/
├── test_tdfol_inference_rules.py   # Rule tests
├── test_tdfol_modal_axioms.py      # Axiom tests
├── test_tdfol_prover_advanced.py   # Advanced proving
└── test_tdfol_performance.py       # Performance benchmarks
```

**Inference Rules to Implement:**

**Temporal Logic (8 rules):**
1. K axiom: □(φ → ψ) → (□φ → □ψ)
2. T axiom: □φ → φ
3. S4 axiom: □φ → □□φ
4. S5 axiom: ◊φ → □◊φ
5. Temporal induction: φ ∧ □(φ → Xφ) → □φ
6. Until induction: (φ U ψ) → ψ ∨ (φ ∧ X(φ U ψ))
7. Since dual: (φ S ψ) ↔ ψ ∨ (φ ∧ Y(φ S ψ))
8. Eventually expansion: ◊φ ↔ φ ∨ X◊φ

**Deontic Logic (7 rules):**
1. D axiom: O(φ) → P(φ)
2. Distribution: O(φ → ψ) → (O(φ) → O(ψ))
3. Prohibition equivalence: F(φ) ↔ O(¬φ)
4. Permission negation: P(φ) ↔ ¬O(¬φ)
5. Obligation consistency: O(φ) → ¬O(¬φ)
6. Permission introduction: φ → P(φ)
7. Conditional obligation: O(φ|ψ) → (ψ → O(φ))

**Combined Temporal-Deontic (5 rules):**
1. Temporal obligation persistence: O(□φ) → □O(φ)
2. Deontic temporal introduction: O(φ) → O(Xφ)
3. Until obligation: O(φ U ψ) → ◊O(ψ)
4. Always permission: P(□φ) → □P(φ)
5. Eventually forbidden: F(◊φ) → □F(φ)

**Integration with CEC:**
```python
from ipfs_datasets_py.logic.CEC.native.prover_core import InferenceEngine
from ipfs_datasets_py.logic.TDFOL import TDFOLProver

# Extend TDFOL prover with CEC rules
tdfol_prover = TDFOLProver()
tdfol_prover.add_cec_rules(InferenceEngine().get_rules())  # 87 rules
```

**Success Criteria:**
- ✅ 25+ total inference rules (10 TDFOL + 15 new)
- ✅ Modal axioms K, T, D, S4, S5 implemented
- ✅ Proof caching reduces search time by 50%+
- ✅ 50+ comprehensive tests passing
- ✅ Integration with CEC prover verified

---

### 📋 Phase 3: Neural-Symbolic Bridge (Weeks 5-6)

**Goals:**
1. Create neurosymbolic reasoning coordinator
2. Implement embedding-enhanced theorem retrieval
3. Add neural pattern matching for formula similarity
4. Create hybrid confidence scoring (symbolic + neural)
5. Implement neural-guided proof search

**Architecture:**
```
┌─────────────────────────────────────────────────────────┐
│           Neurosymbolic Reasoning Coordinator           │
│                                                         │
│  Symbolic Input         Neural Processing              │
│  (TDFOL Formula)        (Embeddings)                   │
│       │                       │                        │
│       ├──► Formula Embedding ─┤                        │
│       │    (768-dim vector)   │                        │
│       │                       │                        │
│       ├──► Similar Theorems ◄─┤ (FAISS search)        │
│       │    (Top-K retrieval)  │                        │
│       │                       │                        │
│       ├──► Neural Confidence ─┤ (NN classifier)       │
│       │    (0.0 - 1.0)        │                        │
│       │                       │                        │
│       └──► Hybrid Decision ◄──┘                        │
│            (Symbolic + Neural)                         │
│                                                         │
│  Output: Proof + Confidence + Evidence                 │
└─────────────────────────────────────────────────────────┘
```

**Files to Create:**
```
logic/neurosymbolic/
├── __init__.py
├── reasoning_coordinator.py       # Main coordinator (500 LOC)
├── neural_guided_search.py        # Neural-guided proving (400 LOC)
├── embedding_prover.py            # Embedding retrieval (300 LOC)
├── hybrid_confidence.py           # Confidence fusion (200 LOC)
├── formula_embedder.py            # Formula → embedding (300 LOC)
└── pattern_matcher.py             # Neural pattern matching (250 LOC)

tests/unit_tests/logic/neurosymbolic/
├── test_reasoning_coordinator.py  # 20+ tests
├── test_neural_guided_search.py   # 15+ tests
├── test_embedding_prover.py       # 15+ tests
└── test_hybrid_confidence.py      # 10+ tests
```

**Key Components:**

**1. Formula Embedder:**
```python
class FormulaEmbedder:
    """Convert TDFOL formulas to embeddings."""
    
    def embed(self, formula: Formula) -> np.ndarray:
        """
        Embed formula into 768-dimensional space.
        
        Strategy:
        1. Convert formula to string representation
        2. Extract structural features (depth, operators, predicates)
        3. Use pre-trained model (e.g., Sentence-BERT)
        4. Combine linguistic and structural embeddings
        """
        # Linguistic embedding (80% weight)
        text = formula.to_string(pretty=True)
        linguistic_emb = self.encoder.encode(text)
        
        # Structural embedding (20% weight)
        structural_emb = self._structural_features(formula)
        
        # Weighted fusion
        return 0.8 * linguistic_emb + 0.2 * structural_emb
```

**2. Neural-Guided Search:**
```python
class NeuralGuidedSearch:
    """Guide proof search using neural networks."""
    
    def select_next_rule(
        self, 
        current_state: Formula,
        available_rules: List[InferenceRule]
    ) -> InferenceRule:
        """
        Select most promising inference rule.
        
        Strategy:
        1. Embed current formula state
        2. Embed each rule's pattern
        3. Compute similarity scores
        4. Return highest-scoring rule
        """
        state_emb = self.embedder.embed(current_state)
        
        scores = []
        for rule in available_rules:
            rule_emb = self.embedder.embed_rule(rule)
            similarity = cosine_similarity(state_emb, rule_emb)
            scores.append(similarity)
        
        best_idx = np.argmax(scores)
        return available_rules[best_idx]
```

**3. Hybrid Confidence:**
```python
class HybridConfidence:
    """Combine symbolic and neural confidence."""
    
    def score(
        self, 
        proof: ProofResult,
        formula: Formula
    ) -> float:
        """
        Compute hybrid confidence score.
        
        Combines:
        - Symbolic: proof length, rule quality
        - Neural: embedding similarity, pattern match
        """
        # Symbolic confidence (60% weight)
        symbolic = self._symbolic_confidence(proof)
        
        # Neural confidence (40% weight)
        neural = self._neural_confidence(formula, proof)
        
        # Weighted fusion
        return 0.6 * symbolic + 0.4 * neural
```

**Success Criteria:**
- ✅ Formula embeddings capture semantic similarity
- ✅ Neural-guided search reduces proof time by 30%+
- ✅ Hybrid confidence correlates 0.85+ with human judgment
- ✅ 60+ comprehensive tests passing
- ✅ Integration with TDFOL prover verified

---

### 📋 Phase 4: GraphRAG Integration (Weeks 7-8)

**Goals:**
1. Extend GraphRAG with logic-aware graph construction
2. Add entity extraction with logical type annotations
3. Implement theorem-augmented knowledge graph
4. Create logical consistency checking for graph edges
5. Add temporal reasoning over knowledge graphs

**Architecture:**
```
┌─────────────────────────────────────────────────────────┐
│          Logic-Aware Knowledge Graph                    │
│                                                         │
│  Entities (typed)     Relations (verified)             │
│  ┌──────────┐        ┌──────────┐                      │
│  │ Person   │        │ employs  │ ✓ Consistent        │
│  │ (Agent)  │───────►│ (Action) │                      │
│  └──────────┘        └──────────┘                      │
│       │                                                 │
│       │ O(PayTax)    ← Theorem attached                │
│       │                                                 │
│  ┌───▼──────┐        ┌──────────┐                      │
│  │ PayTax   │        │ temporal │ ✓ Time-aware        │
│  │ (Action) │◄───────│ (always) │                      │
│  └──────────┘        └──────────┘                      │
│                                                         │
│  + Logical consistency checking                        │
│  + Theorem-based edge validation                       │
│  + Temporal reasoning                                  │
└─────────────────────────────────────────────────────────┘
```

**Files to Create:**
```
graphrag/logic_integration/
├── __init__.py
├── logic_aware_graph.py           # Logic KG (600 LOC)
├── theorem_augmented_rag.py       # RAG + theorems (500 LOC)
├── temporal_graph_reasoning.py    # Temporal reasoning (400 LOC)
├── consistency_checker.py         # Consistency check (300 LOC)
├── entity_type_annotator.py       # Type annotation (200 LOC)
└── logical_query_engine.py        # Query with logic (400 LOC)

tests/unit_tests/graphrag/logic_integration/
├── test_logic_aware_graph.py      # 20+ tests
├── test_theorem_augmented_rag.py  # 15+ tests
├── test_temporal_graph_reasoning.py # 15+ tests
└── test_consistency_checker.py    # 10+ tests
```

**Key Components:**

**1. Logic-Aware Graph:**
```python
class LogicAwareKnowledgeGraph(KnowledgeGraph):
    """Knowledge graph with logical annotations."""
    
    def add_entity(
        self, 
        entity: str,
        entity_type: Sort,
        properties: Dict[str, Formula]
    ):
        """Add entity with logical type and properties."""
        # Type checking using TDFOL Sort system
        self.validate_type(entity, entity_type)
        
        # Attach logical properties
        for prop_name, formula in properties.items():
            self.add_property(entity, prop_name, formula)
    
    def add_relation(
        self,
        source: str,
        relation: str,
        target: str,
        theorem: Optional[Formula] = None
    ):
        """Add relation with optional theorem justification."""
        # Check consistency with existing theorems
        if not self.is_consistent(source, relation, target):
            raise InconsistencyError(...)
        
        # Attach theorem if provided
        if theorem:
            self.attach_theorem(source, relation, target, theorem)
```

**2. Theorem-Augmented RAG:**
```python
class TheoremAugmentedRAG:
    """RAG system enhanced with theorem proving."""
    
    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        logical_reasoning: bool = True
    ) -> List[RetrievalResult]:
        """
        Retrieve documents with logical reasoning.
        
        Process:
        1. Parse query to TDFOL formula
        2. Retrieve similar theorems from KB
        3. Prove relevant implications
        4. Retrieve documents matching theorems
        5. Rank by relevance + logical confidence
        """
        # Parse query
        query_formula = self.parse_query(query)
        
        # Retrieve theorems
        theorems = self.kb.retrieve_similar(query_formula, top_k=20)
        
        # Prove implications
        relevant_theorems = []
        for theorem in theorems:
            if self.prover.prove_implies(query_formula, theorem):
                relevant_theorems.append(theorem)
        
        # Retrieve documents
        documents = self.doc_store.retrieve_by_theorems(
            relevant_theorems, top_k=top_k
        )
        
        return documents
```

**3. Temporal Graph Reasoning:**
```python
class TemporalGraphReasoner:
    """Reason about temporal properties in knowledge graphs."""
    
    def query_temporal(
        self,
        subject: str,
        relation: str,
        time_constraint: TemporalFormula
    ) -> List[Tuple[str, datetime]]:
        """
        Query graph with temporal constraints.
        
        Examples:
        - "Who was employed at time t?"
        - "What obligations were active in 2020?"
        - "Which permissions eventually expired?"
        """
        # Convert temporal formula to graph query
        query = self._temporal_to_query(time_constraint)
        
        # Execute on temporal graph
        results = self.graph.query_temporal(subject, relation, query)
        
        # Filter by temporal logic
        filtered = []
        for entity, timestamp in results:
            if self._satisfies_temporal(entity, timestamp, time_constraint):
                filtered.append((entity, timestamp))
        
        return filtered
```

**Success Criteria:**
- ✅ Knowledge graph supports logical type annotations
- ✅ Theorem-augmented RAG improves precision by 20%+
- ✅ Temporal reasoning handles □, ◊, U operators
- ✅ Consistency checker detects logical conflicts
- ✅ 60+ comprehensive tests passing

---

### 📋 Phase 5: End-to-End Pipeline (Weeks 9-10)

**Goals:**
1. Create unified NeurosymbolicGraphRAG class
2. Implement text → TDFOL → proof → knowledge graph pipeline
3. Add interactive query interface with logical reasoning
4. Create visualization for proof trees + knowledge graphs
5. Add comprehensive examples and tutorials

**Architecture:**
```
┌─────────────────────────────────────────────────────────┐
│       Neurosymbolic GraphRAG Pipeline                   │
│                                                         │
│  Input: Natural Language Query                         │
│          ↓                                              │
│  Step 1: Parse to TDFOL                                │
│          ↓                                              │
│  Step 2: Neural Embedding                              │
│          ↓                                              │
│  Step 3: Retrieve Similar Theorems (Hybrid)           │
│          ↓                                              │
│  Step 4: Theorem Proving (Symbolic)                    │
│          ↓                                              │
│  Step 5: Knowledge Graph Query (Logic-Aware)          │
│          ↓                                              │
│  Step 6: Generate Answer (Neural + Symbolic)          │
│          ↓                                              │
│  Output: Answer + Proof + Evidence + Visualization    │
└─────────────────────────────────────────────────────────┘
```

**Files to Create:**
```
logic/integration/neurosymbolic_graphrag/
├── __init__.py
├── neurosymbolic_graphrag.py      # Main system (800 LOC)
├── query_engine.py                # Query interface (500 LOC)
├── pipeline.py                    # Processing pipeline (600 LOC)
├── visualizer.py                  # Visualization (400 LOC)
├── answer_generator.py            # Answer generation (300 LOC)
└── interactive_interface.py       # CLI/Web interface (400 LOC)

examples/neurosymbolic/
├── legal_reasoning_example.py     # Legal domain
├── medical_reasoning_example.py   # Medical domain
├── autonomous_systems_example.py  # Robotics
└── tutorial_notebook.ipynb        # Jupyter tutorial

tests/integration/neurosymbolic/
├── test_end_to_end_pipeline.py    # 20+ tests
├── test_query_engine.py           # 15+ tests
└── test_visualization.py          # 10+ tests
```

**Key Components:**

**1. Unified NeurosymbolicGraphRAG:**
```python
class NeurosymbolicGraphRAG:
    """Complete neurosymbolic reasoning system."""
    
    def __init__(
        self,
        tdfol_prover: TDFOLProver,
        knowledge_graph: LogicAwareKnowledgeGraph,
        embedder: FormulaEmbedder,
        reasoning_coordinator: ReasoningCoordinator
    ):
        self.prover = tdfol_prover
        self.kg = knowledge_graph
        self.embedder = embedder
        self.coordinator = reasoning_coordinator
    
    def query(
        self,
        question: str,
        reasoning_depth: str = "moderate"  # shallow, moderate, deep
    ) -> AnswerResult:
        """
        Answer question using neurosymbolic reasoning.
        
        Process:
        1. Parse question → TDFOL
        2. Retrieve similar theorems (neural)
        3. Prove relevant theorems (symbolic)
        4. Query knowledge graph (hybrid)
        5. Generate answer (neural + symbolic)
        6. Provide proof + evidence
        """
        # Step 1: Parse
        query_formula = self.parse_question(question)
        
        # Step 2: Neural retrieval
        similar_theorems = self.retrieve_similar(query_formula, top_k=20)
        
        # Step 3: Symbolic proving
        proved_theorems = []
        for theorem in similar_theorems:
            proof = self.prover.prove(theorem)
            if proof.is_proved():
                proved_theorems.append((theorem, proof))
        
        # Step 4: Graph query
        graph_results = self.kg.query_with_theorems(
            query_formula, proved_theorems
        )
        
        # Step 5: Generate answer
        answer = self.coordinator.generate_answer(
            question, proved_theorems, graph_results
        )
        
        return AnswerResult(
            answer=answer.text,
            confidence=answer.confidence,
            proof_trees=[p for _, p in proved_theorems],
            evidence=graph_results,
            reasoning_trace=answer.trace
        )
```

**2. Interactive Query Interface:**
```python
class InteractiveInterface:
    """Interactive CLI/Web interface."""
    
    def run_cli(self):
        """Run command-line interface."""
        print("Neurosymbolic GraphRAG Query System")
        print("=" * 50)
        
        while True:
            query = input("\nQuery> ")
            if query.lower() in ['quit', 'exit']:
                break
            
            # Process query
            result = self.system.query(query)
            
            # Display results
            print(f"\nAnswer: {result.answer}")
            print(f"Confidence: {result.confidence:.2f}")
            print(f"\nProof Steps:")
            for i, step in enumerate(result.proof_trees[0].steps):
                print(f"  {i+1}. {step.justification}")
            
            # Option to visualize
            if input("\nVisualize proof tree? (y/n): ").lower() == 'y':
                self.visualizer.show_proof_tree(result.proof_trees[0])
```

**3. Visualization:**
```python
class ReasoningVisualizer:
    """Visualize proofs and knowledge graphs."""
    
    def visualize_proof_tree(
        self,
        proof: ProofResult,
        format: str = "mermaid"  # mermaid, graphviz, json
    ) -> str:
        """
        Generate proof tree visualization.
        
        Example output (Mermaid):
        ```mermaid
        graph TD
        A[Goal: Q] --> B[Modus Ponens]
        B --> C[Premise: P]
        B --> D[Premise: P→Q]
        C --> E[Axiom 1]
        D --> F[Axiom 2]
        ```
        """
        if format == "mermaid":
            return self._generate_mermaid(proof)
        elif format == "graphviz":
            return self._generate_graphviz(proof)
        else:
            return json.dumps(proof.to_dict(), indent=2)
    
    def visualize_knowledge_graph(
        self,
        kg: LogicAwareKnowledgeGraph,
        highlight_entities: List[str] = None
    ) -> str:
        """Generate knowledge graph visualization."""
        # ... implementation ...
```

**Success Criteria:**
- ✅ End-to-end pipeline processes queries in <2 seconds
- ✅ Interactive interface provides real-time feedback
- ✅ Visualizations are clear and informative
- ✅ 5+ comprehensive examples for different domains
- ✅ Tutorial covers all major features
- ✅ 45+ integration tests passing

---

### 📋 Phase 6: Testing & Documentation (Weeks 11-12)

**Goals:**
1. Add 100+ tests for TDFOL module
2. Add 50+ tests for neurosymbolic integration
3. Add 30+ tests for GraphRAG logic integration
4. Create comprehensive API documentation
5. Add usage examples and tutorials
6. Performance benchmarking and optimization

**Deliverables:**

**1. Test Suite:**
```
tests/
├── unit_tests/logic/TDFOL/                  # 100+ tests
│   ├── test_tdfol_core.py
│   ├── test_tdfol_parser.py
│   ├── test_tdfol_prover.py
│   ├── test_tdfol_converter.py
│   ├── test_tdfol_inference_rules.py
│   ├── test_tdfol_modal_axioms.py
│   └── test_tdfol_performance.py
│
├── unit_tests/logic/neurosymbolic/          # 50+ tests
│   ├── test_reasoning_coordinator.py
│   ├── test_neural_guided_search.py
│   ├── test_embedding_prover.py
│   ├── test_hybrid_confidence.py
│   └── test_formula_embedder.py
│
├── unit_tests/graphrag/logic_integration/   # 30+ tests
│   ├── test_logic_aware_graph.py
│   ├── test_theorem_augmented_rag.py
│   └── test_temporal_graph_reasoning.py
│
└── integration/neurosymbolic/               # 50+ tests
    ├── test_end_to_end_pipeline.py
    ├── test_query_engine.py
    ├── test_legal_reasoning.py
    ├── test_medical_reasoning.py
    └── test_performance_benchmarks.py
```

**2. Documentation:**
```
docs/neurosymbolic/
├── ARCHITECTURE.md           # Architecture overview
├── API_REFERENCE.md          # Complete API docs
├── TUTORIAL.md               # Step-by-step tutorial
├── EXAMPLES.md               # Usage examples
├── BENCHMARKS.md             # Performance results
├── TROUBLESHOOTING.md        # Common issues
└── ROADMAP.md                # Future plans
```

**3. Performance Benchmarks:**
```python
# Target Performance Metrics

# Formula Operations
- Creation: <0.01ms
- Parsing: <5ms (typical), <20ms (complex)
- Conversion: <1ms

# Theorem Proving
- Simple (axiom lookup): <1ms
- Medium (5-10 steps): <50ms
- Complex (20+ steps): <500ms
- With neural guidance: 30% faster

# Knowledge Graph
- Entity add: <1ms
- Relation add with check: <10ms
- Temporal query (1000 nodes): <100ms
- Consistency check (100 theorems): <200ms

# End-to-End Query
- Parse + embed: <10ms
- Retrieve theorems: <50ms
- Prove (3 theorems): <150ms
- Graph query: <100ms
- Generate answer: <50ms
- Total: <400ms (target: <500ms)

# Memory Usage
- Single formula: ~200 bytes
- Knowledge base (1000 formulas): ~200KB
- Embeddings (1000 formulas): ~3MB
- Knowledge graph (1000 nodes): ~5MB
- Total system: <50MB (target: <100MB)
```

**Success Criteria:**
- ✅ 230+ total tests passing
- ✅ >85% code coverage
- ✅ All performance targets met
- ✅ API documentation complete
- ✅ Tutorial covers all major workflows
- ✅ Zero critical bugs
- ✅ Ready for production use

---

## Integration Points

### 1. CEC (Cognitive Event Calculus)

**Current:**
- CEC native prover: 87 inference rules
- Modal tableaux: K, S4, S5 support
- DCEC parsing and namespace management

**TDFOL Integration:**
- TDFOL prover uses CEC inference rules
- Bidirectional TDFOL ↔ DCEC conversion
- Modal axioms extend CEC modal tableaux

**Example:**
```python
from ipfs_datasets_py.logic.CEC.native import InferenceEngine
from ipfs_datasets_py.logic.TDFOL import TDFOLProver

# Create unified prover
prover = TDFOLProver()
prover.add_cec_rules(InferenceEngine().get_rules())

# Prove with combined rules (87 CEC + 25 TDFOL = 112 total)
result = prover.prove(goal)
```

### 2. GraphRAG

**Current:**
- Vector-based retrieval with FAISS
- Hybrid vector-graph search (60:40)
- Cross-document reasoning
- Knowledge graph construction

**TDFOL Integration:**
- Logic-aware graph construction
- Theorem-augmented retrieval
- Consistency checking with theorems
- Temporal reasoning over graphs

**Example:**
```python
from ipfs_datasets_py.graphrag.integrations import GraphRAGQueryEngine
from ipfs_datasets_py.logic.TDFOL import TDFOLProver

# Create logic-enhanced GraphRAG
engine = GraphRAGQueryEngine(
    logic_prover=TDFOLProver(),
    enable_logical_consistency=True,
    enable_temporal_reasoning=True
)

# Query with logical reasoning
result = engine.query(
    "What legal obligations apply to data processing?",
    logical_reasoning=True,
    temporal_scope=(start_date, end_date)
)
```

### 3. FOL and Deontic Modules

**Current:**
- `logic/fol/text_to_fol.py` - Text → FOL conversion
- `logic/deontic/legal_text_to_deontic.py` - Legal text → deontic
- Separate processing pipelines

**TDFOL Integration:**
- Unified TDFOL representation
- Single parser for all three logics
- Converters maintain compatibility

**Example:**
```python
from ipfs_datasets_py.logic.fol import convert_text_to_fol
from ipfs_datasets_py.logic.deontic import convert_legal_text_to_deontic
from ipfs_datasets_py.logic.TDFOL import parse_tdfol, tdfol_to_fol

# Legacy approach (separate)
fol_result = await convert_text_to_fol("All humans are mortal")
deontic_result = await convert_legal_text_to_deontic("Must pay tax")

# TDFOL approach (unified)
tdfol_formula = parse_tdfol("forall x. Human(x) -> O(PayTax(x))")
fol_formula = tdfol_to_fol(tdfol_formula)  # Extract FOL part
```

---

## Success Metrics

### Functional Metrics

**Phase 2:**
- ✅ 25+ inference rules implemented
- ✅ Modal axioms K, T, D, S4, S5 working
- ✅ 50+ tests passing
- ✅ Proof caching reduces time by 50%+

**Phase 3:**
- ✅ Formula embeddings capture semantics
- ✅ Neural guidance improves speed by 30%+
- ✅ Hybrid confidence correlates 0.85+ with humans
- ✅ 60+ tests passing

**Phase 4:**
- ✅ Logic-aware KG supports type annotations
- ✅ Theorem-augmented RAG improves precision by 20%+
- ✅ Temporal reasoning handles □, ◊, U
- ✅ 60+ tests passing

**Phase 5:**
- ✅ End-to-end query processing <2 seconds
- ✅ Interactive interface functional
- ✅ 5+ domain examples working
- ✅ 45+ integration tests passing

**Phase 6:**
- ✅ 230+ total tests passing
- ✅ >85% code coverage
- ✅ All documentation complete
- ✅ Performance targets met

### Performance Metrics

**Latency:**
- Simple query: <500ms
- Medium query: <2 seconds
- Complex query: <5 seconds

**Throughput:**
- 10 queries/second (simple)
- 2 queries/second (complex)

**Memory:**
- System footprint: <100MB
- Per-query overhead: <10MB

**Accuracy:**
- Theorem proving: >95% correct
- Neural guidance: >80% useful
- Hybrid confidence: 0.85+ correlation

---

## Risk Mitigation

### Technical Risks

**Risk 1: CEC Integration Complexity**
- *Mitigation:* Start with wrapper API, gradual integration
- *Fallback:* Use TDFOL prover standalone if needed

**Risk 2: Neural Component Performance**
- *Mitigation:* Caching, batch processing, model optimization
- *Fallback:* Symbolic-only mode without neural components

**Risk 3: GraphRAG Scalability**
- *Mitigation:* Incremental indexing, distributed graph store
- *Fallback:* Simplified graph with pruning

**Risk 4: Testing Coverage**
- *Mitigation:* Automated test generation, property-based testing
- *Fallback:* Focus on critical paths first

### Timeline Risks

**Risk: Phase Overrun**
- *Mitigation:* Weekly checkpoints, scope adjustment if needed
- *Fallback:* Defer non-critical features to future phases

**Risk: Integration Issues**
- *Mitigation:* Early integration testing, modular design
- *Fallback:* Fallback to standalone components

---

## Dependencies

### System Requirements

**Python:**
- Python 3.12+ (required)
- Type hints support

**Core Dependencies:**
- No external dependencies for TDFOL core
- CEC native prover (included)

**Optional Dependencies:**
- NumPy (for neural components)
- Sentence-Transformers (for embeddings)
- FAISS (for vector search)
- Transformers (for LLM integration)

**Development Dependencies:**
- pytest (testing)
- mypy (type checking)
- black (code formatting)

### External Systems

**Optional:**
- SPASS (automated theorem prover)
- TPTP library (test problems)
- Hugging Face models (embeddings)

---

## Timeline Summary

| Phase | Weeks | Status | Deliverables |
|-------|-------|--------|--------------|
| **1** | 1-2 | ✅ Complete | TDFOL core, parser, prover, converter (2,007 LOC) |
| **2** | 3-4 | 🔄 Next | 25+ inference rules, modal axioms, tests (1,500 LOC) |
| **3** | 5-6 | 📋 Planned | Neurosymbolic bridge, neural guidance (2,000 LOC) |
| **4** | 7-8 | 📋 Planned | GraphRAG integration, logic-aware KG (2,400 LOC) |
| **5** | 9-10 | 📋 Planned | End-to-end pipeline, examples (3,000 LOC) |
| **6** | 11-12 | 📋 Planned | Testing, documentation, optimization (230+ tests) |

**Total:** 12 weeks, ~11,000 LOC production code, 230+ tests

---

## Conclusion

This plan provides a **comprehensive roadmap** for building a true neurosymbolic architecture that combines:

- ✅ **Symbolic Logic:** TDFOL with 50+ inference rules
- ✅ **Neural Networks:** Embeddings, LLM-based reasoning
- ✅ **Knowledge Graphs:** Logic-aware GraphRAG
- ✅ **Theorem Provers:** CEC + TDFOL + modal tableaux

**Current Status:** Phase 1 Complete (Weeks 1-2) ✅  
**Next Milestone:** Phase 2 (Weeks 3-4) - Enhanced Prover with 25+ rules 🔄

The foundation is solid, and the path forward is clear. Each phase builds incrementally, with comprehensive testing and integration at every step.

---

**Version:** 1.0.0  
**Date:** February 12, 2026  
**Author:** GitHub Copilot Agent  
**Status:** Phase 1 Complete, Phase 2 In Progress
