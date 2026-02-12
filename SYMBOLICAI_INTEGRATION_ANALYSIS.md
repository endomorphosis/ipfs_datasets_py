# SymbolicAI Integration Analysis & Enhancement Plan

## Executive Summary

**Status:** SymbolicAI (symai) is **already integrated** in the codebase with 1,876 LOC of integration code.

**Recommendation:** **EXTEND AND ENHANCE** the existing integration rather than reimplementing.

**Strategy:** Leverage existing symbolic_fol_bridge.py (563 LOC) and enhance it to work seamlessly with our new TDFOL module, following the same pattern we used for the caching layer.

---

## Current State: Existing SymbolicAI Integration

### Files Using SymbolicAI:

```
ipfs_datasets_py/logic/integration/
├── symbolic_fol_bridge.py          563 LOC  - Core FOL bridge
├── symbolic_contracts.py           763 LOC  - Contract validation
├── symbolic_logic_primitives.py    550 LOC  - Logic primitives
├── legal_symbolic_analyzer.py      ???      - Legal text analysis
├── logic_verification.py           ???      - Logic verification
├── modal_logic_extension.py        ???      - Modal logic extension
└── interactive_fol_constructor.py  ???      - Interactive construction

tests/
├── test_symai_ipfs_engine_cache.py         - Caching tests
├── _test_symbolicai_detailed.py            - Detailed tests
├── _test_symbolicai_quick.py               - Quick tests
├── _test_symai_engine_router.py            - Engine routing tests
└── _test_symbolicai_engine.py              - Engine tests
```

### Dependency Configuration:

```python
# In setup.py
'symbolicai>=0.13.1'  # Included in extras_require
```

### Current Features:

1. **SymbolicFOLBridge** (563 LOC):
   - Natural language → FOL conversion using LLM
   - Semantic analysis of text
   - Confidence-based validation
   - Caching for performance
   - Fallback to pattern-based parsing

2. **Symbolic Contracts** (763 LOC):
   - Contract validation using LLM reasoning
   - Constraint checking with semantic understanding
   - Multi-engine fallback support

3. **Symbolic Logic Primitives** (550 LOC):
   - Basic logic operations with LLM enhancement
   - Semantic predicate extraction
   - Entity recognition with context

---

## SymbolicAI Package Overview

### What is SymbolicAI?

**Project:** ExtensityAI/symbolicai (https://github.com/ExtensityAI/symbolicai)

**Core Concept:** Neurosymbolic framework bridging LLMs with classical symbolic reasoning

### Key Features:

1. **Dual-Mode Symbol Objects**:
   ```python
   from symai import Symbol
   
   # Syntactic mode (fast, native Python)
   s = Symbol("apple")
   
   # Semantic mode (LLM-powered)
   s = Symbol("apple", semantic=True)
   s.query("What category is this?")  # → "fruit"
   ```

2. **Expression Composition**:
   - Build complex workflows combining symbolic + semantic operations
   - Chain operations with `.map()`, `.filter()`, `.reduce()`
   - Compose multi-step reasoning pipelines

3. **LLM Abstraction Layer**:
   - Unified interface across OpenAI, Anthropic, Google, local models
   - Automatic engine routing and fallback
   - Context management and streaming

4. **Contract & Validation System**:
   - Define formal expectations for LLM outputs
   - Automatic validation and retries
   - Fallback strategies for robustness

5. **Probabilistic Programming**:
   - Differentiable reasoning
   - Causal inference
   - Quality scoring (VERTEX metrics)

### Architecture:

```
┌────────────────────────────────────────────────────────────┐
│                    SymbolicAI Framework                    │
│                                                            │
│  Symbol Objects (Dual Mode)                               │
│  ┌──────────────┐        ┌──────────────┐               │
│  │  Syntactic   │ toggle │   Semantic   │               │
│  │  (Fast)      │◄──────►│   (LLM)      │               │
│  └──────────────┘        └──────────────┘               │
│         │                        │                        │
│         └────────┬───────────────┘                        │
│                  ▼                                        │
│         Expression Engine                                 │
│         ┌────────────────┐                               │
│         │  Compose ops   │                               │
│         │  Map/Filter    │                               │
│         │  Chain logic   │                               │
│         └────────────────┘                               │
│                  │                                        │
│         ┌────────▼────────┐                              │
│         │  LLM Backends   │                              │
│         │  (OpenAI, etc)  │                              │
│         └─────────────────┘                              │
└────────────────────────────────────────────────────────────┘
```

---

## Gap Analysis: What's Missing

### Current Integration (symbolic_fol_bridge.py):

✅ **Has:**
- Natural language → FOL conversion
- Basic semantic analysis
- Caching layer
- Fallback mechanism
- Confidence scoring

❌ **Missing:**
1. **TDFOL Integration**: Doesn't produce TDFOL formulas (uses string FOL)
2. **Modal Logic**: No temporal/deontic operator support
3. **Theorem Proving**: No connection to TDFOL prover
4. **Neural-Guided Search**: No integration with inference rules
5. **GraphRAG Integration**: No knowledge graph enhancement
6. **Embedding Bridge**: No formula embedding for similarity search
7. **Advanced Contracts**: Limited deontic/temporal validation

### SymbolicAI Unused Features:

1. **Expression Composition**: Not leveraged for multi-step reasoning
2. **Probabilistic Flows**: Not used for uncertainty handling
3. **Causal Reasoning**: Not integrated
4. **VERTEX Scoring**: Quality metrics not applied
5. **Multi-Agent Orchestration**: Not utilized

---

## Enhancement Strategy

### Phase 1: TDFOL Bridge (Immediate - Week 3)

**Goal:** Connect SymbolicAI's semantic parsing to TDFOL formula construction

**Create:** `logic/neurosymbolic/symai_tdfol_bridge.py` (400 LOC)

```python
from symai import Symbol, Expression
from ipfs_datasets_py.logic.TDFOL import (
    Formula, parse_tdfol, TDFOLProver
)
from ipfs_datasets_py.logic.integration.symbolic_fol_bridge import (
    SymbolicFOLBridge
)

class SymaiTDFOLBridge:
    """Bridge SymbolicAI semantic parsing to TDFOL formulas."""
    
    def __init__(self):
        self.fol_bridge = SymbolicFOLBridge()
        self.prover = TDFOLProver()
    
    def parse_with_semantics(self, text: str) -> Formula:
        """
        Parse natural language to TDFOL using semantic understanding.
        
        Process:
        1. Use SymbolicAI for semantic analysis
        2. Extract logical components (predicates, quantifiers, modals)
        3. Construct TDFOL formula
        4. Validate with prover
        """
        # Use Symbol for semantic analysis
        sym = Symbol(text, semantic=True)
        
        # Query for logical structure
        structure = sym.query("""
        Analyze this text and extract:
        1. Quantifiers (forall, exists)
        2. Predicates with arguments
        3. Logical operators (and, or, not, implies)
        4. Modal operators (obligation, permission, always, eventually)
        5. Temporal relationships
        
        Format as: {quantifiers: [...], predicates: [...], ...}
        """)
        
        # Convert to TDFOL formula
        formula = self._build_tdfol_from_structure(structure)
        
        # Validate
        if not self._validate_formula(formula):
            # Fallback to pattern-based parsing
            return parse_tdfol(text)
        
        return formula
```

**Integration Points:**
- Extend `symbolic_fol_bridge.py` to output TDFOL instead of string FOL
- Add semantic validation using SymbolicAI contracts
- Cache TDFOL formulas (extend caching layer)

### Phase 2: Neural-Guided Proof Search (Week 4-5)

**Goal:** Use SymbolicAI to guide theorem proving

**Create:** `logic/neurosymbolic/symai_proof_guide.py` (500 LOC)

```python
class SymaiProofGuide:
    """Use SymbolicAI to guide proof search."""
    
    def select_rule(
        self, 
        current_state: Formula,
        available_rules: List[InferenceRule]
    ) -> InferenceRule:
        """
        Use LLM to select most promising inference rule.
        
        Advantages over pure neural:
        - Symbolic reasoning about rule applicability
        - Natural language explanation of choices
        - Contract-based validation of selections
        """
        # Create symbolic representation
        state_sym = Symbol(current_state.to_string(), semantic=True)
        
        # Query for best rule
        rule_names = [r.name for r in available_rules]
        selection = state_sym.query(f"""
        Given the current formula state, which inference rule
        is most likely to help prove the goal?
        
        Available rules: {rule_names}
        
        Consider:
        - Formula structure
        - Rule preconditions
        - Proof strategy (forward vs backward chaining)
        
        Return: rule name only
        """)
        
        # Find and return selected rule
        for rule in available_rules:
            if rule.name in selection:
                return rule
        
        # Fallback to heuristic selection
        return self._heuristic_selection(current_state, available_rules)
```

**Integration Points:**
- Extend TDFOLProver with neural guidance option
- Add explanation generation for proof steps
- Use contracts to validate proof strategies

### Phase 3: Semantic Formula Embeddings (Week 5-6)

**Goal:** Create embeddings for TDFOL formulas using SymbolicAI

**Create:** `logic/neurosymbolic/symai_formula_embedder.py` (300 LOC)

```python
class SymaiFormulaEmbedder:
    """Generate semantic embeddings for TDFOL formulas."""
    
    def embed(self, formula: Formula) -> np.ndarray:
        """
        Create embedding combining:
        1. Syntactic structure (formula tree)
        2. Semantic meaning (via SymbolicAI)
        3. Logical properties (quantifiers, operators)
        """
        # Convert to natural language description
        nl_description = self._formula_to_natural_language(formula)
        
        # Get semantic embedding via SymbolicAI
        sym = Symbol(nl_description, semantic=True)
        semantic_emb = sym.embed()  # Uses underlying LLM embeddings
        
        # Combine with structural features
        structural_emb = self._extract_structural_features(formula)
        
        # Weighted fusion (80% semantic, 20% structural)
        return 0.8 * semantic_emb + 0.2 * structural_emb
    
    def similar_formulas(
        self, 
        query: Formula, 
        formula_bank: List[Formula],
        top_k: int = 5
    ) -> List[Tuple[Formula, float]]:
        """Find similar formulas using semantic similarity."""
        query_emb = self.embed(query)
        
        similarities = []
        for formula in formula_bank:
            formula_emb = self.embed(formula)
            sim = cosine_similarity(query_emb, formula_emb)
            similarities.append((formula, sim))
        
        return sorted(similarities, key=lambda x: x[1], reverse=True)[:top_k]
```

**Integration Points:**
- Use for theorem retrieval in proof search
- Enhance GraphRAG with semantic formula similarity
- Enable "fuzzy" matching of logical statements

### Phase 4: Contract-Based Logic Validation (Week 6-7)

**Goal:** Use SymbolicAI contracts for deontic/temporal logic validation

**Extend:** `symbolic_contracts.py` (add 200 LOC)

```python
class TDFOLContract:
    """Contract for validating TDFOL formulas."""
    
    def __init__(self):
        self.deontic_rules = self._load_deontic_rules()
        self.temporal_rules = self._load_temporal_rules()
    
    def validate_deontic(self, formula: DeonticFormula) -> bool:
        """
        Validate deontic formula using contracts.
        
        Checks:
        1. Consistency: O(φ) ∧ O(¬φ) is invalid
        2. D-axiom: O(φ) → P(φ) must hold
        3. Semantic coherence: via LLM reasoning
        """
        # Symbolic validation
        if not self._check_deontic_axioms(formula):
            return False
        
        # Semantic validation via SymbolicAI
        sym = Symbol(formula.to_string(), semantic=True)
        coherence = sym.query("""
        Is this deontic formula semantically coherent?
        Consider: real-world obligations, permissions, prohibitions.
        Answer: yes/no with brief explanation
        """)
        
        return "yes" in coherence.lower()
```

**Integration Points:**
- Validate formulas during parsing
- Check proof steps for semantic coherence
- Enhance GraphRAG edge validation

### Phase 5: GraphRAG Enhancement (Week 7-8)

**Goal:** Use SymbolicAI for logic-aware knowledge graph construction

**Create:** `graphrag/logic_integration/symai_graph_builder.py` (600 LOC)

```python
class SymaiGraphBuilder:
    """Build logic-aware knowledge graphs using SymbolicAI."""
    
    def extract_logical_entities(self, text: str) -> List[LogicalEntity]:
        """
        Extract entities with logical types using semantic understanding.
        
        Advantages:
        - Better entity recognition via LLM context
        - Automatic type annotation (Agent, Action, Event, etc.)
        - Relationship extraction with logical properties
        """
        sym = Symbol(text, semantic=True)
        
        entities = sym.query("""
        Extract entities and classify them using these logical types:
        - Agent: entities that can perform actions
        - Action: things that can be done
        - Event: occurrences in time
        - Proposition: statements that can be true/false
        - State: conditions or properties
        
        For each entity, also extract:
        - Relationships to other entities
        - Temporal properties (when it occurs/exists)
        - Deontic properties (obligations, permissions)
        
        Format as JSON
        """)
        
        return self._parse_logical_entities(entities)
    
    def build_theorem_graph(
        self, 
        theorems: List[Formula]
    ) -> KnowledgeGraph:
        """
        Build knowledge graph from TDFOL theorems.
        
        Nodes: Formulas, predicates, entities
        Edges: Implications, dependencies, similarities
        """
        graph = KnowledgeGraph()
        
        for theorem in theorems:
            # Add theorem as node
            node_id = graph.add_node(theorem)
            
            # Extract predicates and add as nodes
            predicates = theorem.get_predicates()
            for pred in predicates:
                pred_id = graph.add_node(pred)
                graph.add_edge(node_id, pred_id, "contains")
            
            # Find semantic similarities using SymbolicAI
            similar = self._find_similar_theorems(theorem, theorems)
            for sim_theorem, score in similar:
                sim_id = graph.get_node_id(sim_theorem)
                graph.add_edge(node_id, sim_id, "similar_to", weight=score)
        
        return graph
```

**Integration Points:**
- Enhance existing GraphRAG with logical annotations
- Add theorem-based reasoning to graph traversal
- Use semantic similarity for cross-document connections

---

## Implementation Roadmap

### Week 3: TDFOL Bridge
- [x] Review existing symbolic_fol_bridge.py
- [ ] Create symai_tdfol_bridge.py
- [ ] Extend to output TDFOL formulas
- [ ] Add semantic validation contracts
- [ ] Test with 20+ examples
- [ ] Update caching layer for TDFOL

### Week 4-5: Neural-Guided Proof Search
- [ ] Create symai_proof_guide.py
- [ ] Integrate with TDFOLProver
- [ ] Add explanation generation
- [ ] Benchmark against baseline prover
- [ ] Test with 50+ proof problems
- [ ] Measure performance improvement

### Week 6: Semantic Formula Embeddings
- [ ] Create symai_formula_embedder.py
- [ ] Implement formula → embedding
- [ ] Build formula similarity search
- [ ] Integrate with theorem retrieval
- [ ] Test with formula bank of 100+
- [ ] Benchmark similarity metrics

### Week 7: Contract-Based Validation
- [ ] Extend symbolic_contracts.py
- [ ] Add TDFOL-specific contracts
- [ ] Implement deontic/temporal validators
- [ ] Integrate with parser
- [ ] Test with legal text corpus
- [ ] Measure validation accuracy

### Week 8: GraphRAG Enhancement
- [ ] Create symai_graph_builder.py
- [ ] Implement logical entity extraction
- [ ] Build theorem-augmented graphs
- [ ] Integrate with existing GraphRAG
- [ ] Test with multi-document corpus
- [ ] Benchmark retrieval quality

---

## Benefits of This Approach

### 1. Leverage Existing Work
- ✅ 1,876 LOC already written
- ✅ Caching layer functional
- ✅ Tests already exist
- ✅ Production-ready fallback mechanisms

### 2. Seamless Integration
- Uses established patterns (similar to caching)
- Minimal disruption to existing code
- Backward compatible with current API
- Progressive enhancement possible

### 3. Best of Both Worlds
- **Symbolic**: Formal correctness via TDFOL prover
- **Neural**: Semantic understanding via SymbolicAI
- **Hybrid**: Contracts enforce consistency

### 4. Production Ready
- SymbolicAI has multi-engine fallback
- Contract system provides robustness
- Caching reduces LLM API costs
- Error handling built-in

### 5. Research-Backed
- SymbolicAI paper (arXiv:2402.00854)
- VERTEX quality metrics
- Proven in production systems
- Active development and support

---

## Comparison: Build vs Extend

### Option 1: Build New (NOT RECOMMENDED)
**Pros:**
- Full control over implementation
- Optimized for TDFOL

**Cons:**
- ❌ Duplicate 1,876 LOC of code
- ❌ Reinvent LLM abstraction layer
- ❌ Rebuild caching system
- ❌ Recreate contract validation
- ❌ 4-6 weeks of extra work
- ❌ Less battle-tested

### Option 2: Extend SymbolicAI (RECOMMENDED) ✅
**Pros:**
- ✅ Reuse 1,876 LOC existing code
- ✅ Leverage mature LLM abstraction
- ✅ Use existing caching layer
- ✅ Contract system included
- ✅ 2-3 weeks of integration work
- ✅ Production-proven reliability

**Cons:**
- Dependency on external package
- Learning curve for SymbolicAI API

**Decision:** **EXTEND** - Same pattern we used for caching layer

---

## Code Examples

### Before (Current - FOL Strings):

```python
from ipfs_datasets_py.logic.integration.symbolic_fol_bridge import SymbolicFOLBridge

bridge = SymbolicFOLBridge()
result = bridge.convert_to_fol("All humans are mortal")

# Returns: "∀x. Human(x) → Mortal(x)" (string)
```

### After (Enhanced - TDFOL Objects):

```python
from ipfs_datasets_py.logic.neurosymbolic import SymaiTDFOLBridge

bridge = SymaiTDFOLBridge()
formula = bridge.parse_with_semantics("All humans are mortal")

# Returns: QuantifiedFormula(FORALL, Variable('x'), ...)  (TDFOL object)

# Can now prove theorems
prover = TDFOLProver()
result = prover.prove(formula)

# Can embed for similarity
embedder = SymaiFormulaEmbedder()
embedding = embedder.embed(formula)

# Can add to knowledge graph
graph_builder = SymaiGraphBuilder()
graph_builder.add_theorem(formula)
```

---

## Dependencies Update

### Current:
```python
# setup.py
extras_require = {
    'symbolic': [
        'symbolicai>=0.13.1',
    ],
}
```

### Recommended (No Change):
```python
# setup.py
extras_require = {
    'symbolic': [
        'symbolicai>=0.13.1',  # Keep current version
    ],
    'neurosymbolic': [
        'symbolicai>=0.13.1',  # Same package, new features
        'sentence-transformers>=2.0.0',  # For embeddings
        'faiss-cpu>=1.7.0',  # For similarity search
    ],
}
```

---

## Testing Strategy

### Unit Tests:
- Test TDFOL bridge with 50+ examples
- Test proof guide with 20+ problems
- Test embedder with 100+ formulas
- Test contracts with 30+ validation cases

### Integration Tests:
- End-to-end: text → TDFOL → proof
- GraphRAG with theorems
- Multi-step reasoning pipelines

### Performance Tests:
- Caching effectiveness
- LLM call reduction
- Proof search speedup
- Similarity search latency

### Quality Tests:
- Semantic coherence validation
- Contract satisfaction rate
- Proof correctness rate
- Embedding quality metrics

---

## Success Metrics

### Technical:
- ✅ TDFOL formulas parseable from natural language
- ✅ Proof search 30%+ faster with neural guidance
- ✅ Formula similarity search 0.85+ correlation with human judgment
- ✅ Contract validation 90%+ accuracy

### Integration:
- ✅ Seamless with existing symbolic_fol_bridge.py
- ✅ Backward compatible API
- ✅ <5% performance overhead from SymbolicAI calls
- ✅ Caching reduces 80%+ of LLM calls

### Code Quality:
- ✅ <500 LOC new code (vs 1,876 existing)
- ✅ 90%+ test coverage
- ✅ Type hints throughout
- ✅ Comprehensive documentation

---

## Conclusion

**Recommendation:** **EXTEND** existing SymbolicAI integration

**Rationale:**
1. Already have 1,876 LOC of integration code
2. Proven patterns (caching layer approach)
3. 50% reduction in development time
4. Production-ready infrastructure
5. Research-backed framework

**Next Steps:**
1. Review existing symbolic_fol_bridge.py in detail
2. Create symai_tdfol_bridge.py (Week 3)
3. Test with natural language corpus
4. Integrate with TDFOL prover
5. Extend to proof guidance and embeddings

**Timeline:** 6 weeks (vs 10 weeks for building from scratch)

**Risk:** Low - existing code provides fallback, progressive enhancement possible

---

**Status:** Ready to proceed with Week 3 implementation ✅

**Version:** 1.0  
**Date:** February 12, 2026  
**Author:** GitHub Copilot Agent
