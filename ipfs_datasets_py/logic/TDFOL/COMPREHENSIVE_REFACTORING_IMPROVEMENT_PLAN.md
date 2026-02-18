# TDFOL Comprehensive Refactoring and Improvement Plan

**Document Version:** 1.0.0  
**Created:** 2026-02-18  
**Status:** 🟡 PLANNING  
**Scope:** Phases 7-12 (Extending completed Phases 1-6)

---

## Executive Summary

This document outlines a comprehensive refactoring and improvement plan for the TDFOL (Temporal Deontic First-Order Logic) module to address current limitations and implement advanced capabilities for production-ready neurosymbolic reasoning.

### Current State (Phases 1-6 Complete)

**Delivered Capabilities:**
- ✅ Unified TDFOL core with 8 formula types (551 LOC)
- ✅ Parser supporting all operators (564 LOC)
- ✅ Prover with 40+ inference rules (777 LOC + 1,215 LOC rules)
- ✅ Proof caching with CID addressing (92 LOC)
- ✅ Converters for DCEC/FOL/TPTP (528 LOC)
- ✅ Neural-symbolic integration hooks
- ✅ GraphRAG integration (Phase 4)
- ✅ End-to-end pipeline (Phase 5)
- ✅ Basic testing (97 tests, 100% pass rate)

**Total Code:** ~4,287 LOC core + ~1,913 LOC tests

### Critical Limitations to Address

Based on the problem statement, the following limitations require immediate attention:

1. **Parser:** Limited to prefix/infix notation, **no natural language support**
2. **Prover:** Only 10-40 TDFOL rules, **needs 50+ for completeness**
3. **Modal Logic:** Integration hooks only, **not fully implemented**
4. **Optimization:** Basic proof caching, **no strategy optimization**
5. **Testing:** 97 tests only, **needs comprehensive coverage**
6. **Visualization:** **None** - needs proof tree and dependency graphs

### Planned Improvements (Phases 7-12)

This plan introduces **6 new phases** to address all limitations:

- **Phase 7:** Natural Language Processing (NL → TDFOL conversion)
- **Phase 8:** Complete Prover (50+ inference rules + modal tableaux)
- **Phase 9:** Advanced Optimization (strategy selection, parallel search)
- **Phase 10:** Comprehensive Testing (330+ tests target)
- **Phase 11:** Visualization Tools (proof trees, dependency graphs)
- **Phase 12:** Production Hardening (performance, security, docs)

**Estimated Timeline:** 16-20 weeks  
**Estimated LOC:** +8,000-10,000 LOC (implementation + tests)

---

## Table of Contents

1. [Current State Analysis](#1-current-state-analysis)
2. [Gap Analysis](#2-gap-analysis)
3. [Phase 7: Natural Language Processing](#3-phase-7-natural-language-processing)
4. [Phase 8: Complete Prover](#4-phase-8-complete-prover)
5. [Phase 9: Advanced Optimization](#5-phase-9-advanced-optimization)
6. [Phase 10: Comprehensive Testing](#6-phase-10-comprehensive-testing)
7. [Phase 11: Visualization Tools](#7-phase-11-visualization-tools)
8. [Phase 12: Production Hardening](#8-phase-12-production-hardening)
9. [Implementation Roadmap](#9-implementation-roadmap)
10. [Success Metrics](#10-success-metrics)
11. [Risk Assessment](#11-risk-assessment)
12. [Appendix](#12-appendix)

---

## 1. Current State Analysis

### 1.1 File Structure

```
ipfs_datasets_py/logic/TDFOL/
├── __init__.py                    (187 LOC)  - Public API exports
├── tdfol_core.py                  (551 LOC)  - Core data structures
├── tdfol_parser.py                (564 LOC)  - String parsing
├── tdfol_prover.py                (777 LOC)  - Theorem proving
├── tdfol_inference_rules.py       (1,215 LOC) - 40+ inference rules
├── tdfol_proof_cache.py           (92 LOC)   - Proof caching
├── tdfol_converter.py             (528 LOC)  - Format conversion
├── tdfol_dcec_parser.py           (373 LOC)  - DCEC integration
└── README.md                      (544 lines) - Documentation

Total: 4,287 LOC core implementation
```

### 1.2 Feature Completeness Matrix

| Feature Category | Status | Coverage | Notes |
|-----------------|--------|----------|-------|
| Core Data Structures | ✅ Complete | 100% | 8 formula types, frozen dataclasses |
| String Parsing | ✅ Complete | 100% | Symbolic notation only |
| Natural Language | ❌ Missing | 0% | **Critical gap** |
| Inference Rules | 🟡 Partial | 40% | 40/127 rules (need 50+ TDFOL) |
| Modal Tableaux | 🟡 Hooks Only | 10% | Integration stubs only |
| Proof Caching | ✅ Complete | 100% | CID-based, 100-20000x speedup |
| Strategy Optimization | ❌ Missing | 0% | **Critical gap** |
| Parallel Search | ❌ Missing | 0% | **Critical gap** |
| Visualization | ❌ Missing | 0% | **Critical gap** |
| Testing | 🟡 Partial | 30% | 97 tests vs 330+ target |

### 1.3 Integration Status

**Existing Integrations:**
- ✅ CEC Native Prover (87 rules) - `tdfol_prover.py` lines 62-82
- ✅ Modal Tableaux (hooks) - `tdfol_prover.py` lines 84-100
- ✅ GraphRAG (Phase 4) - Via `logic/integration/`
- ✅ Neural-Symbolic (Phase 3) - Via `logic/integration/symbolic/neurosymbolic/`

**Missing Integrations:**
- ❌ Natural language front-ends (spaCy, transformers)
- ❌ Visualization backends (GraphViz, Plotly)
- ❌ Parallel processing frameworks (Ray, Dask)
- ❌ External ATPs (E, Vampire, Z3)

### 1.4 Code Quality Assessment

**Strengths:**
- ✅ Type-safe with frozen dataclasses
- ✅ Clean separation of concerns
- ✅ Comprehensive docstrings
- ✅ Lazy loading for optional dependencies
- ✅ 100% test pass rate (97 tests)

**Weaknesses:**
- ⚠️ Missing phase completion documents (PHASE2-6_COMPLETE.md referenced but not found)
- ⚠️ Limited error handling in parser
- ⚠️ No performance profiling or benchmarking
- ⚠️ Modal tableaux integration incomplete
- ⚠️ No CLI tools for standalone usage

---

## 2. Gap Analysis

### 2.1 Parser Limitations

**Current Capabilities:**
- ✅ Lexical analysis (40+ token types)
- ✅ Recursive descent parsing
- ✅ Operator precedence handling
- ✅ Symbolic notation: ∀∃∧∨¬→↔OPF□◊XUS

**Critical Gaps:**
```
❌ Natural language input: "All agents must pay tax"
❌ Pattern-based extraction: "Contractors are obligated to..."
❌ Context-aware parsing: Entity recognition, coreference
❌ Ambiguity resolution: Multiple interpretations
❌ Error recovery: Partial parsing, suggestions
```

**Impact:** 🔴 **High Priority** - Blocks user-friendly adoption

### 2.2 Prover Limitations

**Current Capabilities:**
- ✅ 40 inference rules (15 basic, 10 temporal, 8 deontic, 7 combined)
- ✅ Forward chaining
- ✅ Backward chaining (goal-directed)
- ✅ CEC prover integration (87 rules)
- ✅ Modal tableaux hooks

**Critical Gaps:**
```
❌ Missing 10+ temporal rules (LTL completeness)
❌ Missing 5+ deontic rules (SDL completeness)
❌ Missing 15+ combined rules (TDFOL-specific)
❌ No modal tableaux implementation (K, T, D, S4, S5)
❌ No bidirectional search
❌ No proof explanation/justification
❌ No incremental proving
```

**Impact:** 🔴 **High Priority** - Limits reasoning capabilities

### 2.3 Optimization Limitations

**Current Capabilities:**
- ✅ Proof caching with CID addressing (92 LOC)
- ✅ 100-20000x speedup on cache hits
- ✅ Thread-safe implementation

**Critical Gaps:**
```
❌ No strategy selection (always forward chaining)
❌ No heuristic search (A*, best-first)
❌ No parallel proof search
❌ No proof reuse across sessions
❌ No adaptive timeout handling
❌ No resource-constrained proving
```

**Impact:** 🟡 **Medium Priority** - Performance bottleneck for complex proofs

### 2.4 Testing Limitations

**Current Coverage:**
- ✅ 97 tests total (100% pass rate)
- ✅ Core: ~6 tests
- ✅ Proof cache: 15 tests
- ✅ GraphRAG integration: 55 tests
- ✅ Pipeline: 21 tests

**Critical Gaps:**
```
❌ Parser: Need 50+ tests (edge cases, error handling)
❌ Prover: Need 100+ tests (all inference rules)
❌ Converters: Need 30+ tests (round-trip, edge cases)
❌ Integration: Need 50+ tests (CEC, modal, neural-symbolic)
❌ Performance: Need 20+ benchmarks
❌ Property-based: Need hypothesis tests
```

**Target:** 330+ comprehensive tests  
**Gap:** 233 tests missing

**Impact:** 🟡 **Medium Priority** - Regression risk

### 2.5 Visualization Limitations

**Current Capabilities:**
- ❌ None

**Critical Gaps:**
```
❌ Proof tree visualization (ASCII, GraphViz, HTML)
❌ Formula dependency graphs
❌ Inference rule application trace
❌ Knowledge base topology
❌ Temporal evolution diagrams
❌ Interactive proof exploration
```

**Impact:** 🟡 **Medium Priority** - Debugging and education

---

## 3. Phase 7: Natural Language Processing

**Goal:** Add pattern-based natural language to TDFOL conversion

**Duration:** 3-4 weeks  
**LOC Estimate:** 1,500-2,000 LOC (implementation + tests)

### 3.1 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                Natural Language Pipeline                     │
└──────────────────┬──────────────────────────────────────────┘
                   │
         ┌─────────┼─────────┐
         │         │         │
         ▼         ▼         ▼
    ┌────────┐ ┌─────────┐ ┌────────────┐
    │ spaCy  │ │ Pattern │ │  Context   │
    │  NLP   │ │ Matcher │ │  Resolver  │
    └────┬───┘ └────┬────┘ └─────┬──────┘
         │          │            │
         └──────────┼────────────┘
                    ▼
         ┌────────────────────┐
         │  TDFOL Generator   │
         │  (Formula Builder) │
         └──────────┬─────────┘
                    │
                    ▼
         ┌────────────────────┐
         │  TDFOL Formula     │
         └────────────────────┘
```

### 3.2 Components to Build

#### 3.2.1 Natural Language Preprocessor

**File:** `tdfol_nl_preprocessor.py` (~300 LOC)

**Features:**
- Sentence splitting and tokenization
- Entity recognition (agents, actions, objects)
- Dependency parsing (subject-verb-object)
- Temporal expression normalization
- Coreference resolution

**Example:**
```python
from ipfs_datasets_py.logic.TDFOL.nl import NLPreprocessor

preprocessor = NLPreprocessor()
doc = preprocessor.process("All contractors must pay taxes within 30 days.")

# doc.entities = [Entity(type="AGENT", text="contractors", ...)]
# doc.temporal = [TemporalExp(type="DEADLINE", value="30 days", ...)]
# doc.modality = ["must"]
```

#### 3.2.2 Pattern Matcher

**File:** `tdfol_nl_patterns.py` (~500 LOC)

**Pattern Categories:**

1. **Universal Quantification Patterns:**
```python
patterns = [
    "all {agent} must {action}",
    "every {agent} is required to {action}",
    "{agent}s are obligated to {action}",
    "any {agent} shall {action}",
]
```

2. **Obligation Patterns:**
```python
patterns = [
    "{agent} must {action}",
    "{agent} is required to {action}",
    "{agent} shall {action}",
    "it is obligatory that {agent} {action}",
]
```

3. **Permission Patterns:**
```python
patterns = [
    "{agent} may {action}",
    "{agent} is allowed to {action}",
    "{agent} can {action}",
    "it is permitted that {agent} {action}",
]
```

4. **Prohibition Patterns:**
```python
patterns = [
    "{agent} must not {action}",
    "{agent} shall not {action}",
    "{agent} is forbidden to {action}",
    "it is prohibited that {agent} {action}",
]
```

5. **Temporal Patterns:**
```python
patterns = [
    "always {formula}",
    "eventually {formula}",
    "{formula} until {condition}",
    "within {time} {formula}",
    "after {event} {formula}",
]
```

6. **Conditional Patterns:**
```python
patterns = [
    "if {condition} then {consequence}",
    "when {event} {consequence}",
    "{consequence} provided that {condition}",
]
```

**Implementation:**
```python
class TDFOLPatternMatcher:
    def __init__(self):
        self.patterns = load_patterns()
        self.matcher = spacy.matcher.Matcher()
        self._register_patterns()
    
    def match(self, doc: spacy.Doc) -> List[PatternMatch]:
        """Match patterns against preprocessed document."""
        matches = []
        for pattern_id, start, end in self.matcher(doc):
            pattern = self.patterns[pattern_id]
            match = PatternMatch(
                pattern=pattern,
                span=doc[start:end],
                entities=extract_entities(doc, start, end),
                confidence=calculate_confidence(pattern, doc)
            )
            matches.append(match)
        return matches
```

#### 3.2.3 TDFOL Generator

**File:** `tdfol_nl_generator.py` (~400 LOC)

**Responsibilities:**
- Convert pattern matches to TDFOL formulas
- Handle entity substitution
- Resolve ambiguities
- Generate well-formed formulas

**Example:**
```python
class TDFOLGenerator:
    def generate(self, matches: List[PatternMatch]) -> Formula:
        """Generate TDFOL formula from pattern matches."""
        if len(matches) == 1:
            return self._generate_single(matches[0])
        else:
            return self._generate_multiple(matches)
    
    def _generate_single(self, match: PatternMatch) -> Formula:
        """Generate formula from single pattern match."""
        pattern = match.pattern
        
        if pattern.type == "UNIVERSAL_OBLIGATION":
            # "All contractors must pay taxes"
            # → ∀x.(Contractor(x) → O(PayTax(x)))
            agent_var = Variable(match.entities["agent"])
            agent_pred = Predicate(match.entities["agent"].capitalize(), (agent_var,))
            action_pred = Predicate(match.entities["action"], (agent_var,))
            obligation = create_obligation(action_pred)
            implication = create_implication(agent_pred, obligation)
            return create_universal(agent_var, implication)
        
        # ... handle other pattern types
```

#### 3.2.4 Context Resolver

**File:** `tdfol_nl_context.py` (~300 LOC)

**Features:**
- Maintain discourse context (entities, events)
- Resolve pronouns and references
- Track temporal context
- Handle implicit information

**Example:**
```python
class ContextResolver:
    def __init__(self):
        self.context = Context()
    
    def resolve(self, doc: spacy.Doc) -> ResolvedDoc:
        """Resolve context-dependent information."""
        # Track entities
        for ent in doc.ents:
            self.context.add_entity(ent)
        
        # Resolve references
        for token in doc:
            if token.pos_ == "PRON":
                referent = self.context.resolve_reference(token)
                token._.referent = referent
        
        return ResolvedDoc(doc, self.context)
```

### 3.3 API Design

```python
from ipfs_datasets_py.logic.TDFOL import parse_natural_language

# Simple API
formula = parse_natural_language("All contractors must pay taxes")
# Returns: ∀x.(Contractor(x) → O(PayTax(x)))

# Advanced API with options
from ipfs_datasets_py.logic.TDFOL.nl import NLParser

parser = NLParser(
    use_spacy=True,
    pattern_file="custom_patterns.json",
    confidence_threshold=0.7
)

result = parser.parse(
    "All contractors must pay taxes within 30 days.",
    context={"domain": "legal"},
    return_alternatives=True
)

print(result.formula)           # Best formula
print(result.confidence)        # 0.85
print(result.alternatives)      # Other interpretations
print(result.explanation)       # How it was parsed
```

### 3.4 Test Plan

**Target:** 60+ tests

1. **Pattern Matching Tests (20 tests)**
   - Each pattern category
   - Edge cases (negation, nested patterns)
   - Ambiguity handling

2. **Entity Recognition Tests (15 tests)**
   - Agent extraction
   - Action extraction
   - Object extraction
   - Complex entities

3. **Formula Generation Tests (15 tests)**
   - Simple sentences
   - Complex sentences
   - Compound sentences
   - Error cases

4. **Integration Tests (10 tests)**
   - End-to-end parsing
   - Context resolution
   - Multi-sentence documents

### 3.5 Success Criteria

- ✅ Parse 20+ common legal/deontic patterns
- ✅ 80%+ accuracy on curated test set
- ✅ Handle ambiguity (return multiple interpretations)
- ✅ Integrate with existing parser
- ✅ Documentation and examples

### 3.6 Dependencies

- spaCy (3.7+): NLP pipeline
- spacy-transformers: Neural entity recognition
- Optional: Hugging Face transformers for advanced NLP

---

## 4. Phase 8: Complete Prover

**Goal:** Implement 50+ TDFOL inference rules and complete modal tableaux

**Duration:** 4-5 weeks  
**LOC Estimate:** 2,500-3,000 LOC (implementation + tests)

### 4.1 Current Rule Inventory

From `tdfol_inference_rules.py`:

**Basic Logic Rules (15):** ✅
- Modus Ponens
- Modus Tollens
- Conjunction Introduction
- Conjunction Elimination
- Disjunction Introduction
- Disjunction Elimination
- Universal Instantiation
- Existential Instantiation
- Universal Generalization
- Existential Generalization
- Implication Introduction
- Implication Elimination
- Negation Introduction
- Negation Elimination
- Double Negation

**Temporal Logic Rules (10):** ✅
- Always Introduction
- Always Elimination
- Eventually Introduction
- Eventually Elimination
- Next Introduction
- Next Elimination
- Until Introduction
- Until Elimination
- Temporal Induction
- Temporal Distribution

**Deontic Logic Rules (8):** ✅
- Obligation Introduction
- Obligation Elimination
- Permission Introduction
- Permission Elimination
- Prohibition Introduction
- Prohibition Elimination
- Deontic Distribution
- D Axiom (O(φ) → P(φ))

**Combined Rules (7):** ✅
- Temporal Obligation Persistence
- Deontic Temporal Introduction
- Until Obligation
- Obligation Always Elimination
- Permission Eventually Introduction
- Prohibition Always Introduction
- Conditional Obligation

**Total: 40 rules implemented**

### 4.2 Missing Rules (30+ to add)

#### 4.2.1 Temporal Logic Extensions (12 rules)

1. **Weak Until Rules:**
```
φ W ψ ↔ (φ U ψ) ∨ □φ
```

2. **Release Rules:**
```
φ R ψ ↔ ¬(¬φ U ¬ψ)
```

3. **Since Rules (Past LTL):**
```
φ S ψ: φ has been true since ψ was true
```

4. **Bounded Temporal Rules:**
```
□[n]φ: φ holds for next n steps
◊[n]φ: φ holds within n steps
```

5. **LTL Equivalences:**
```
□φ ↔ φ ∧ X(□φ)
◊φ ↔ φ ∨ X(◊φ)
φ U ψ ↔ ψ ∨ (φ ∧ X(φ U ψ))
```

6. **Temporal Negation:**
```
¬□φ ↔ ◊¬φ
¬◊φ ↔ □¬φ
```

#### 4.2.2 Deontic Logic Extensions (8 rules)

1. **Contrary-to-Duty Obligations:**
```
O(φ) ∧ ¬φ → O(ψ)  [if φ violated, ψ becomes obligatory]
```

2. **Conditional Obligations:**
```
O(φ|ψ): φ is obligatory given ψ
O(φ|ψ) ∧ ψ → O(φ)
```

3. **Deontic Detachment:**
```
O(φ → ψ) ∧ φ → O(ψ)
```

4. **Permission Closure:**
```
P(φ) ∧ P(ψ) → P(φ ∧ ψ)  [if both permitted, conjunction permitted]
```

5. **Obligation Aggregation:**
```
O(φ) ∧ O(ψ) → O(φ ∧ ψ)
```

6. **Free Choice Permission:**
```
P(φ ∨ ψ) → P(φ) ∧ P(ψ)
```

#### 4.2.3 Combined Temporal-Deontic Rules (10 rules)

1. **Temporal Obligation Evolution:**
```
O(X(φ)) → X(O(φ))
```

2. **Persistent Obligations:**
```
O(□φ) → □O(φ)
```

3. **Deadline Obligations:**
```
O(◊[n]φ): φ must hold within n steps
```

4. **Conditional Temporal Obligations:**
```
O(φ U ψ) ↔ (O(φ) U O(ψ))
```

5. **Deontic Past:**
```
O(P(φ)): It was obligatory that φ (where P is "previously")
```

### 4.3 Modal Tableaux Implementation

**Goal:** Full modal tableaux prover for K, T, D, S4, S5

**File:** `tdfol_modal_tableaux.py` (~800 LOC)

#### 4.3.1 Modal Logic Axioms

```python
class ModalAxiom:
    """Modal logic axioms for different systems."""
    
    K = "□(φ → ψ) → (□φ → □ψ)"      # Distribution
    T = "□φ → φ"                      # Reflexivity
    D = "□φ → ◊φ"                     # Seriality (deontic)
    S4 = "□φ → □□φ"                   # Transitivity
    S5 = "◊φ → □◊φ"                   # Euclidean
    B = "φ → □◊φ"                     # Symmetry
```

#### 4.3.2 Tableaux Rules

```python
class TableauRule:
    """Tableaux expansion rules."""
    
    # Propositional rules
    ALPHA = "α: conjunctive formulas (expand both branches)"
    BETA = "β: disjunctive formulas (branch on alternatives)"
    
    # Modal rules
    BOX = "□φ: add φ to all accessible worlds"
    DIAMOND = "◊φ: create new accessible world with φ"
    
    # Quantifier rules  
    GAMMA = "∀x.φ: instantiate with fresh constants"
    DELTA = "∃x.φ: instantiate with witness"
```

#### 4.3.3 Implementation

```python
class TDFOLModalTableau:
    """Modal tableaux prover for TDFOL."""
    
    def __init__(self, logic_type: ModalLogicType = ModalLogicType.K):
        self.logic_type = logic_type
        self.axioms = self._load_axioms(logic_type)
    
    def prove(self, formula: Formula) -> TableauResult:
        """
        Prove formula using modal tableaux.
        
        Returns:
            TableauResult with proof status, tableau tree, countermodel
        """
        # Start with negation of goal (proof by contradiction)
        root = TableauNode(create_negation(formula))
        tableau = Tableau(root, self.logic_type)
        
        # Expand tableau
        while not tableau.is_closed() and not tableau.is_saturated():
            node = tableau.select_node()
            rule = tableau.select_rule(node)
            tableau.apply_rule(node, rule)
        
        if tableau.is_closed():
            return TableauResult(
                status=ProofStatus.PROVED,
                tableau=tableau,
                countermodel=None
            )
        else:
            countermodel = tableau.extract_countermodel()
            return TableauResult(
                status=ProofStatus.DISPROVED,
                tableau=tableau,
                countermodel=countermodel
            )
```

### 4.4 Integration with Existing Prover

Update `tdfol_prover.py`:

```python
class TDFOLProver:
    def __init__(
        self,
        kb: TDFOLKnowledgeBase,
        use_cec: bool = True,
        use_modal_tableaux: bool = True,
        use_advanced_rules: bool = True,  # NEW: Enable 30+ new rules
        enable_cache: bool = True,
        timeout_seconds: float = 30.0
    ):
        # ... existing initialization ...
        
        if use_advanced_rules:
            self._load_advanced_rules()  # NEW
        
        if use_modal_tableaux:
            self.modal_prover = TDFOLModalTableau(logic_type=ModalLogicType.K)
```

### 4.5 Test Plan

**Target:** 120+ tests

1. **Temporal Rule Tests (30 tests)**
   - Each new temporal rule
   - LTL equivalences
   - Bounded operators

2. **Deontic Rule Tests (20 tests)**
   - Each new deontic rule
   - Contrary-to-duty obligations
   - Conditional obligations

3. **Combined Rule Tests (20 tests)**
   - Temporal-deontic interactions
   - Complex scenarios

4. **Modal Tableaux Tests (30 tests)**
   - K, T, D, S4, S5 systems
   - Tableaux expansion
   - Countermodel generation

5. **Integration Tests (20 tests)**
   - Complete proofs using new rules
   - Performance benchmarks

### 4.6 Success Criteria

- ✅ 50+ TDFOL inference rules total (40 existing + 10+ new)
- ✅ Full modal tableaux for K, T, D, S4, S5
- ✅ Countermodel generation for unprovable formulas
- ✅ Integration with existing prover
- ✅ 120+ passing tests
- ✅ Documentation for all new rules

---

## 5. Phase 9: Advanced Optimization

**Goal:** Implement proof strategy selection, parallel search, and adaptive optimization

**Duration:** 3-4 weeks  
**LOC Estimate:** 1,500-2,000 LOC (implementation + tests)

### 5.1 Strategy Selection

**File:** `tdfol_proof_strategies.py` (~500 LOC)

#### 5.1.1 Proof Strategies

```python
class ProofStrategy(Enum):
    """Available proof strategies."""
    
    FORWARD_CHAINING = "forward"      # Current default
    BACKWARD_CHAINING = "backward"    # Goal-directed
    BIDIRECTIONAL = "bidirectional"   # Meet-in-the-middle
    MODAL_TABLEAUX = "tableaux"       # For modal formulas
    RESOLUTION = "resolution"         # Clause-based
    NATURAL_DEDUCTION = "natural"     # Natural deduction rules
    AUTO = "auto"                     # Automatic selection
```

#### 5.1.2 Strategy Selector

```python
class StrategySelector:
    """Select optimal proof strategy based on formula characteristics."""
    
    def select_strategy(self, goal: Formula, kb: TDFOLKnowledgeBase) -> ProofStrategy:
        """
        Analyze formula and select best strategy.
        
        Heuristics:
        - Modal formulas → tableaux
        - Goal-oriented queries → backward chaining
        - Large KB → forward chaining with indexing
        - Temporal formulas → specialized temporal prover
        """
        if self._has_modal_operators(goal):
            return ProofStrategy.MODAL_TABLEAUX
        
        if self._is_goal_oriented(goal, kb):
            return ProofStrategy.BACKWARD_CHAINING
        
        if len(kb.axioms) > 1000:
            return ProofStrategy.FORWARD_CHAINING
        
        return ProofStrategy.BIDIRECTIONAL
```

### 5.2 Parallel Proof Search

**File:** `tdfol_parallel_prover.py` (~600 LOC)

#### 5.2.1 Architecture

```
┌──────────────────────────────────────────┐
│         Parallel Proof Coordinator       │
└──────────────┬───────────────────────────┘
               │
       ┌───────┼───────┬───────┐
       │       │       │       │
       ▼       ▼       ▼       ▼
   ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐
   │Worker│ │Worker│ │Worker│ │Worker│
   │  1   │ │  2   │ │  3   │ │  4   │
   └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘
      │        │        │        │
      └────────┴────────┴────────┘
               │
               ▼
      ┌────────────────┐
      │ Shared Cache   │
      │ (Thread-safe)  │
      └────────────────┘
```

#### 5.2.2 Implementation

```python
class ParallelProver:
    """Parallel proof search with multiple strategies."""
    
    def __init__(
        self,
        kb: TDFOLKnowledgeBase,
        num_workers: int = 4,
        strategies: List[ProofStrategy] = None
    ):
        self.kb = kb
        self.num_workers = num_workers
        self.strategies = strategies or [
            ProofStrategy.FORWARD_CHAINING,
            ProofStrategy.BACKWARD_CHAINING,
            ProofStrategy.MODAL_TABLEAUX,
            ProofStrategy.RESOLUTION
        ]
        self.cache = get_global_proof_cache()
    
    def prove(self, goal: Formula, timeout: float = 30.0) -> ProofResult:
        """
        Prove goal using parallel search.
        
        Each worker tries a different strategy.
        First to find proof wins.
        """
        with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
            futures = []
            for strategy in self.strategies[:self.num_workers]:
                future = executor.submit(
                    self._prove_with_strategy,
                    goal,
                    strategy,
                    timeout
                )
                futures.append(future)
            
            # Wait for first success
            for future in as_completed(futures, timeout=timeout):
                result = future.result()
                if result.is_proved():
                    # Cancel other workers
                    for f in futures:
                        f.cancel()
                    return result
            
            # All failed
            return ProofResult(status=ProofStatus.TIMEOUT)
```

### 5.3 Heuristic Search

**File:** `tdfol_heuristic_search.py` (~400 LOC)

#### 5.3.1 Search Algorithms

```python
class HeuristicSearch:
    """Heuristic-guided proof search."""
    
    def a_star_search(
        self,
        initial_state: ProofState,
        goal: Formula,
        heuristic: Callable[[ProofState, Formula], float]
    ) -> Optional[ProofPath]:
        """
        A* search for proof.
        
        Heuristic estimates distance to goal.
        """
        open_set = PriorityQueue()
        open_set.put((0, initial_state))
        came_from = {}
        g_score = {initial_state: 0}
        
        while not open_set.empty():
            current = open_set.get()[1]
            
            if self._is_goal(current, goal):
                return self._reconstruct_path(came_from, current)
            
            for neighbor in self._get_neighbors(current):
                tentative_g = g_score[current] + self._cost(current, neighbor)
                
                if tentative_g < g_score.get(neighbor, float('inf')):
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g
                    f_score = tentative_g + heuristic(neighbor, goal)
                    open_set.put((f_score, neighbor))
        
        return None
```

#### 5.3.2 Heuristics

```python
def formula_distance_heuristic(state: ProofState, goal: Formula) -> float:
    """Estimate steps to prove goal from current state."""
    # Count predicates not yet derived
    derived_preds = set(f.get_predicates() for f in state.derived_formulas)
    goal_preds = goal.get_predicates()
    missing = goal_preds - derived_preds
    return len(missing)

def structural_similarity_heuristic(state: ProofState, goal: Formula) -> float:
    """Measure structural similarity between state and goal."""
    best_match = max(
        (similarity(f, goal) for f in state.derived_formulas),
        default=0.0
    )
    return 1.0 - best_match  # Lower is better
```

### 5.4 Adaptive Timeout

**File:** Update `tdfol_prover.py` (~100 LOC additions)

```python
class AdaptiveTimeout:
    """Dynamically adjust timeout based on formula complexity."""
    
    def estimate_timeout(self, formula: Formula, kb: TDFOLKnowledgeBase) -> float:
        """
        Estimate reasonable timeout for proof attempt.
        
        Factors:
        - Formula size and nesting depth
        - Number of quantifiers
        - KB size
        - Historical proof times
        """
        base_timeout = 1.0  # seconds
        
        # Adjust for formula complexity
        complexity = self._calculate_complexity(formula)
        timeout = base_timeout * (1 + complexity / 10)
        
        # Adjust for KB size
        if len(kb.axioms) > 100:
            timeout *= 1.5
        if len(kb.axioms) > 1000:
            timeout *= 2.0
        
        # Cap at reasonable limit
        return min(timeout, 60.0)
    
    def _calculate_complexity(self, formula: Formula) -> int:
        """Calculate formula complexity score."""
        if isinstance(formula, Predicate):
            return 1
        elif isinstance(formula, QuantifiedFormula):
            return 5 + self._calculate_complexity(formula.formula)
        elif isinstance(formula, BinaryFormula):
            return 2 + self._calculate_complexity(formula.left) + \
                   self._calculate_complexity(formula.right)
        # ... handle other types
```

### 5.5 Test Plan

**Target:** 40+ tests

1. **Strategy Selection Tests (10 tests)**
   - Each strategy type
   - Auto-selection heuristics

2. **Parallel Search Tests (10 tests)**
   - Multiple workers
   - Strategy coordination
   - Timeout handling

3. **Heuristic Search Tests (10 tests)**
   - A* correctness
   - Heuristic functions
   - Performance benchmarks

4. **Adaptive Timeout Tests (10 tests)**
   - Complexity estimation
   - Timeout adjustment

### 5.6 Success Criteria

- ✅ 4+ proof strategies implemented
- ✅ Automatic strategy selection
- ✅ Parallel search with 2-8 workers
- ✅ Heuristic-guided search (A*)
- ✅ Adaptive timeout management
- ✅ 2-5x speedup on complex proofs

---

## 6. Phase 10: Comprehensive Testing

**Goal:** Achieve 330+ comprehensive tests with property-based testing

**Duration:** 3-4 weeks  
**LOC Estimate:** 2,000-2,500 LOC tests

### 6.1 Test Coverage Matrix

| Module | Current | Target | Gap | Priority |
|--------|---------|--------|-----|----------|
| Core | 6 | 30 | +24 | P1 |
| Parser | 0 | 50 | +50 | P1 |
| Prover | 0 | 100 | +100 | P0 |
| Inference Rules | 0 | 50 | +50 | P0 |
| Proof Cache | 15 | 20 | +5 | P2 |
| Converters | 0 | 30 | +30 | P1 |
| NL Parser | 0 | 60 | +60 | P1 (Phase 7) |
| Integration | 76 | 100 | +24 | P2 |
| **Total** | **97** | **440** | **+343** | - |

### 6.2 Test Categories

#### 6.2.1 Unit Tests (200+ tests)

**Core Module Tests (30 tests):**
```python
# tests/unit_tests/logic/TDFOL/test_tdfol_core_comprehensive.py

class TestFormulas:
    """Comprehensive formula tests."""
    
    def test_predicate_creation(self):
        """Test predicate with various argument types."""
        
    def test_binary_formula_all_operators(self):
        """Test all binary operators."""
        
    def test_quantified_formula_variable_binding(self):
        """Test variable binding in quantifiers."""
        
    def test_deontic_formula_agent_handling(self):
        """Test deontic formulas with agents."""
        
    def test_temporal_formula_time_bounds(self):
        """Test temporal formulas with time bounds."""
    
    # ... 25 more tests
```

**Parser Tests (50 tests):**
```python
# tests/unit_tests/logic/TDFOL/test_tdfol_parser_comprehensive.py

class TestTDFOLParser:
    """Comprehensive parser tests."""
    
    def test_parse_simple_predicate(self):
        """Parse: Person(john)"""
        
    def test_parse_quantified_formula(self):
        """Parse: forall x. P(x) -> Q(x)"""
        
    def test_parse_deontic_formula(self):
        """Parse: O(P(x))"""
        
    def test_parse_temporal_formula(self):
        """Parse: G(Safe)"""
        
    def test_parse_complex_nested(self):
        """Parse: forall x. (P(x) -> O(G(Q(x))))"""
        
    def test_parse_error_recovery(self):
        """Test error handling and recovery."""
        
    def test_parse_ambiguous_input(self):
        """Test ambiguity handling."""
    
    # ... 43 more tests
```

**Prover Tests (100 tests):**
```python
# tests/unit_tests/logic/TDFOL/test_tdfol_prover_comprehensive.py

class TestTDFOLProver:
    """Comprehensive prover tests."""
    
    # Test each inference rule (50 tests)
    def test_rule_modus_ponens(self):
    def test_rule_modus_tollens(self):
    # ... one test per rule
    
    # Test proof strategies (20 tests)
    def test_forward_chaining(self):
    def test_backward_chaining(self):
    def test_bidirectional_search(self):
    # ...
    
    # Test complex scenarios (30 tests)
    def test_prove_transitive_chain(self):
    def test_prove_with_temporal_reasoning(self):
    def test_prove_with_deontic_reasoning(self):
    # ...
```

#### 6.2.2 Integration Tests (100+ tests)

**CEC Integration (20 tests):**
```python
class TestTDFOLCECIntegration:
    """Test TDFOL-CEC prover integration."""
    
    def test_cec_inference_rules(self):
        """Test using CEC's 87 inference rules."""
        
    def test_dcec_conversion_roundtrip(self):
        """Test TDFOL ↔ DCEC conversion."""
```

**GraphRAG Integration (30 tests):**
- Logic-aware entity extraction
- Theorem-augmented knowledge graphs
- Consistency checking

**Neural-Symbolic Integration (20 tests):**
- Embedding-enhanced retrieval
- Hybrid confidence scoring
- Neural-guided proof search

**Modal Tableaux Integration (30 tests):**
- K, T, D, S4, S5 logics
- Tableaux expansion
- Countermodel generation

#### 6.2.3 Property-Based Tests (40+ tests)

Using `hypothesis` library:

```python
from hypothesis import given, strategies as st

class TestTDFOLProperties:
    """Property-based tests for TDFOL."""
    
    @given(st.text(min_size=1, max_size=100))
    def test_parser_never_crashes(self, text):
        """Parser should handle any text without crashing."""
        try:
            result = parse_tdfol_safe(text)
            assert result is not None or result is None  # May fail to parse
        except Exception as e:
            pytest.fail(f"Parser crashed: {e}")
    
    @given(formula=generate_formula())
    def test_to_string_roundtrip(self, formula):
        """to_string() → parse_tdfol() should roundtrip."""
        text = formula.to_string()
        parsed = parse_tdfol(text)
        assert parsed == formula
    
    @given(formula=generate_formula(), var=generate_variable(), term=generate_term())
    def test_substitution_idempotent(self, formula, var, term):
        """Substituting twice should equal substituting once."""
        once = formula.substitute(var, term)
        twice = once.substitute(var, term)
        assert once == twice
```

#### 6.2.4 Performance Tests (20+ tests)

```python
class TestTDFOLPerformance:
    """Performance benchmarks."""
    
    def test_parse_performance(self):
        """Parsing should be < 5ms for typical formulas."""
        formula_str = "forall x. P(x) -> O(Q(x))"
        start = time.time()
        for _ in range(1000):
            parse_tdfol(formula_str)
        elapsed = time.time() - start
        assert elapsed < 5.0  # < 5ms per parse
    
    def test_proof_cache_speedup(self):
        """Cached proofs should be 100x+ faster."""
        # ... measure with/without cache
        assert speedup > 100
    
    def test_parallel_prover_speedup(self):
        """Parallel prover should be 2-4x faster."""
        # ... measure sequential vs parallel
        assert speedup > 2.0
```

### 6.3 Test Infrastructure

#### 6.3.1 Test Fixtures

```python
# tests/unit_tests/logic/TDFOL/conftest.py

import pytest
from ipfs_datasets_py.logic.TDFOL import *

@pytest.fixture
def simple_kb():
    """Knowledge base with simple axioms."""
    kb = TDFOLKnowledgeBase()
    kb.add_axiom(parse_tdfol("P"))
    kb.add_axiom(parse_tdfol("P -> Q"))
    return kb

@pytest.fixture
def legal_kb():
    """Knowledge base with legal rules."""
    kb = TDFOLKnowledgeBase()
    kb.add_axiom(parse_tdfol("forall x. Contractor(x) -> O(PayTax(x))"))
    kb.add_axiom(parse_tdfol("forall x. O(P(x)) -> P(P(x))"))
    return kb

@pytest.fixture
def prover(simple_kb):
    """Prover with simple knowledge base."""
    return TDFOLProver(simple_kb, enable_cache=True)
```

#### 6.3.2 Test Generators

```python
# tests/unit_tests/logic/TDFOL/generators.py

from hypothesis import strategies as st

def generate_variable():
    """Generate random variable."""
    return st.builds(Variable, name=st.text(min_size=1, max_size=10))

def generate_constant():
    """Generate random constant."""
    return st.builds(Constant, name=st.text(min_size=1, max_size=10))

def generate_predicate():
    """Generate random predicate."""
    return st.builds(
        Predicate,
        name=st.text(min_size=1, max_size=20),
        arguments=st.lists(generate_term(), min_size=0, max_size=3)
    )

def generate_formula(max_depth=3):
    """Generate random formula with bounded depth."""
    if max_depth == 0:
        return generate_predicate()
    
    return st.one_of(
        generate_predicate(),
        st.builds(BinaryFormula, ...),
        st.builds(QuantifiedFormula, ...),
        # ...
    )
```

### 6.4 Success Criteria

- ✅ 330+ comprehensive tests (440+ target with Phase 7)
- ✅ 90%+ code coverage
- ✅ Property-based testing with hypothesis
- ✅ Performance benchmarks
- ✅ All tests passing in CI/CD

---

## 7. Phase 11: Visualization Tools

**Goal:** Build proof tree visualization and formula dependency graphs

**Duration:** 2-3 weeks  
**LOC Estimate:** 1,000-1,500 LOC (implementation + tests)

### 7.1 Proof Tree Visualization

**File:** `tdfol_visualization_proof_tree.py` (~400 LOC)

#### 7.1.1 ASCII Visualization

```python
class ProofTreeVisualizer:
    """Visualize proof trees in various formats."""
    
    def to_ascii(self, proof_result: ProofResult) -> str:
        """
        Generate ASCII proof tree.
        
        Example output:
        
        Goal: Q
        ├─ Rule: ModusPonens
        │  ├─ Premise: P
        │  └─ Premise: P → Q
        │     ├─ Rule: Axiom
        │     └─ (in knowledge base)
        └─ Proved ✓
        """
        lines = [f"Goal: {proof_result.goal}"]
        self._render_node(proof_result.proof_tree, lines, prefix="")
        return "\n".join(lines)
    
    def _render_node(self, node: ProofNode, lines: List[str], prefix: str):
        """Recursively render proof tree node."""
        if node.rule:
            lines.append(f"{prefix}├─ Rule: {node.rule.name}")
            for premise in node.premises:
                self._render_node(premise, lines, prefix + "│  ")
        else:
            lines.append(f"{prefix}└─ Axiom: {node.formula}")
```

#### 7.1.2 GraphViz Visualization

```python
def to_graphviz(self, proof_result: ProofResult) -> str:
    """
    Generate GraphViz DOT format.
    
    Returns DOT string that can be rendered with:
        dot -Tpng proof_tree.dot -o proof_tree.png
    """
    dot = ["digraph ProofTree {"]
    dot.append('  rankdir=TB;')
    dot.append('  node [shape=box];')
    
    node_id = 0
    node_ids = {}
    
    def add_node(node: ProofNode):
        nonlocal node_id
        current_id = node_id
        node_id += 1
        node_ids[id(node)] = current_id
        
        label = node.formula.to_string()
        if node.rule:
            label += f"\\n[{node.rule.name}]"
        
        dot.append(f'  n{current_id} [label="{label}"];')
        
        for premise in node.premises:
            premise_id = add_node(premise)
            dot.append(f'  n{premise_id} -> n{current_id};')
        
        return current_id
    
    add_node(proof_result.proof_tree)
    dot.append('}')
    return "\n".join(dot)
```

#### 7.1.3 HTML Interactive Visualization

```python
def to_html(self, proof_result: ProofResult) -> str:
    """
    Generate interactive HTML visualization.
    
    Uses D3.js for collapsible tree.
    """
    tree_data = self._to_json(proof_result.proof_tree)
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>TDFOL Proof Tree</title>
        <script src="https://d3js.org/d3.v7.min.js"></script>
        <style>
            .node {{ cursor: pointer; }}
            .node circle {{ fill: #fff; stroke: steelblue; stroke-width: 3px; }}
            .node text {{ font: 12px sans-serif; }}
            .link {{ fill: none; stroke: #ccc; stroke-width: 2px; }}
        </style>
    </head>
    <body>
        <div id="tree"></div>
        <script>
            const treeData = {tree_data};
            // D3.js tree rendering code...
        </script>
    </body>
    </html>
    """
    return html
```

### 7.2 Formula Dependency Graph

**File:** `tdfol_visualization_dependencies.py` (~300 LOC)

#### 7.2.1 Dependency Extraction

```python
class DependencyExtractor:
    """Extract dependencies between formulas in a knowledge base."""
    
    def extract_dependencies(self, kb: TDFOLKnowledgeBase) -> DependencyGraph:
        """
        Build dependency graph showing which formulas depend on which.
        
        Dependencies:
        - A → B: B depends on A
        - ∀x.φ: φ depends on quantified formula
        - O(φ): φ depends on obligation
        """
        graph = nx.DiGraph()
        
        for formula in kb.get_all_formulas():
            self._add_formula_dependencies(formula, graph)
        
        return DependencyGraph(graph)
    
    def _add_formula_dependencies(self, formula: Formula, graph: nx.DiGraph):
        """Recursively add formula and its dependencies to graph."""
        formula_id = id(formula)
        graph.add_node(formula_id, formula=formula)
        
        if isinstance(formula, BinaryFormula):
            left_id = id(formula.left)
            right_id = id(formula.right)
            graph.add_edge(left_id, formula_id)
            graph.add_edge(right_id, formula_id)
            self._add_formula_dependencies(formula.left, graph)
            self._add_formula_dependencies(formula.right, graph)
        # ... handle other types
```

#### 7.2.2 Visualization

```python
class DependencyVisualizer:
    """Visualize formula dependency graphs."""
    
    def to_graphviz(self, dep_graph: DependencyGraph) -> str:
        """Generate GraphViz visualization of dependencies."""
        dot = ["digraph Dependencies {"]
        dot.append('  rankdir=LR;')
        
        for node_id in dep_graph.graph.nodes():
            formula = dep_graph.graph.nodes[node_id]['formula']
            label = self._truncate(formula.to_string(), 50)
            dot.append(f'  n{node_id} [label="{label}"];')
        
        for source, target in dep_graph.graph.edges():
            dot.append(f'  n{source} -> n{target};')
        
        dot.append('}')
        return "\n".join(dot)
    
    def to_plotly(self, dep_graph: DependencyGraph):
        """Generate interactive Plotly visualization."""
        import plotly.graph_objects as go
        
        # Use networkx spring layout
        pos = nx.spring_layout(dep_graph.graph)
        
        # Create edges
        edge_trace = go.Scatter(
            x=[], y=[],
            line=dict(width=0.5, color='#888'),
            hoverinfo='none',
            mode='lines'
        )
        
        for edge in dep_graph.graph.edges():
            x0, y0 = pos[edge[0]]
            x1, y1 = pos[edge[1]]
            edge_trace['x'] += (x0, x1, None)
            edge_trace['y'] += (y0, y1, None)
        
        # Create nodes
        node_trace = go.Scatter(
            x=[], y=[],
            mode='markers+text',
            hoverinfo='text',
            marker=dict(size=10, color='blue')
        )
        
        # ... add nodes with labels
        
        fig = go.Figure(data=[edge_trace, node_trace])
        return fig
```

### 7.3 Inference Rule Trace

**File:** `tdfol_visualization_inference_trace.py` (~300 LOC)

```python
class InferenceTraceVisualizer:
    """Visualize which inference rules were applied during proof."""
    
    def to_timeline(self, proof_result: ProofResult) -> str:
        """
        Generate timeline of inference rule applications.
        
        Example output:
        
        Step 1: Axiom - Added P to KB
        Step 2: Axiom - Added P → Q to KB
        Step 3: ModusPonens - From P and P → Q, derived Q
        Step 4: Goal Reached - Q proved ✓
        """
        lines = []
        for i, step in enumerate(proof_result.proof_steps, 1):
            lines.append(f"Step {i}: {step.rule.name}")
            lines.append(f"  From: {[str(p) for p in step.premises]}")
            lines.append(f"  Derived: {step.conclusion}")
        
        if proof_result.is_proved():
            lines.append(f"\nGoal Reached - {proof_result.goal} proved ✓")
        
        return "\n".join(lines)
```

### 7.4 API Integration

```python
# Add to TDFOLProver

class TDFOLProver:
    def prove(self, goal: Formula, visualize: bool = False) -> ProofResult:
        """Prove goal and optionally generate visualizations."""
        result = self._prove_internal(goal)
        
        if visualize and result.is_proved():
            result.visualization = self._generate_visualization(result)
        
        return result
    
    def _generate_visualization(self, result: ProofResult) -> ProofVisualization:
        """Generate all visualizations for proof result."""
        viz = ProofVisualization()
        viz.ascii_tree = ProofTreeVisualizer().to_ascii(result)
        viz.graphviz_dot = ProofTreeVisualizer().to_graphviz(result)
        viz.html = ProofTreeVisualizer().to_html(result)
        return viz

# Usage:
result = prover.prove(goal, visualize=True)
print(result.visualization.ascii_tree)
result.visualization.save_html("proof_tree.html")
```

### 7.5 Test Plan

**Target:** 30+ tests

1. **Proof Tree Tests (10 tests)**
   - ASCII rendering
   - GraphViz generation
   - HTML generation

2. **Dependency Graph Tests (10 tests)**
   - Dependency extraction
   - Graph visualization
   - Complex dependencies

3. **Inference Trace Tests (10 tests)**
   - Timeline generation
   - Rule application tracking

### 7.6 Success Criteria

- ✅ ASCII proof tree visualization
- ✅ GraphViz/DOT export
- ✅ Interactive HTML visualization
- ✅ Formula dependency graphs
- ✅ Inference rule traces
- ✅ Integration with prover API

---

## 8. Phase 12: Production Hardening

**Goal:** Performance optimization, security hardening, and production-ready documentation

**Duration:** 2-3 weeks  
**LOC Estimate:** 500-1,000 LOC (refinements + docs)

### 8.1 Performance Optimization

#### 8.1.1 Profiling

```python
# Add profiling infrastructure

class TDFOLProfiler:
    """Profile TDFOL operations for performance optimization."""
    
    def profile_parsing(self, formulas: List[str]) -> ProfilingReport:
        """Profile parser performance."""
        
    def profile_proving(self, goals: List[Formula], kb: TDFOLKnowledgeBase) -> ProfilingReport:
        """Profile prover performance."""
        
    def generate_report(self) -> str:
        """Generate performance report."""
```

#### 8.1.2 Optimizations

1. **Parser Optimizations:**
   - Memoization of token sequences
   - Lazy formula construction
   - Interned strings for operators

2. **Prover Optimizations:**
   - Indexed knowledge base (by predicate)
   - Rule applicability caching
   - Early termination heuristics

3. **Memory Optimizations:**
   - Shared immutable subformulas
   - Proof tree pruning
   - Cache eviction policies

### 8.2 Security Hardening

#### 8.2.1 Input Validation

```python
class SecurityValidator:
    """Validate inputs for security issues."""
    
    def validate_formula_string(self, text: str) -> ValidationResult:
        """
        Validate formula string for:
        - Maximum length
        - Nesting depth limits
        - Resource exhaustion attacks
        """
        if len(text) > MAX_FORMULA_LENGTH:
            raise ValueError("Formula too long")
        
        if self._calculate_nesting_depth(text) > MAX_NESTING:
            raise ValueError("Formula too deeply nested")
        
        return ValidationResult(valid=True)
```

#### 8.2.2 Resource Limits

```python
class ResourceLimiter:
    """Enforce resource limits on proof search."""
    
    def __init__(
        self,
        max_steps: int = 10000,
        max_memory_mb: int = 1000,
        timeout_seconds: float = 60.0
    ):
        self.max_steps = max_steps
        self.max_memory_mb = max_memory_mb
        self.timeout_seconds = timeout_seconds
    
    def enforce_limits(self, prover: TDFOLProver):
        """Wrap prover with resource limits."""
        # Monitor proof search and abort if limits exceeded
```

### 8.3 Error Handling

#### 8.3.1 Comprehensive Error Types

```python
class TDFOLError(Exception):
    """Base exception for TDFOL module."""

class ParseError(TDFOLError):
    """Error parsing TDFOL formula."""
    def __init__(self, message: str, position: int, context: str):
        self.position = position
        self.context = context
        super().__init__(f"{message} at position {position}: {context}")

class ProofError(TDFOLError):
    """Error during proof search."""

class TimeoutError(TDFOLError):
    """Proof search exceeded timeout."""

class ResourceExhaustedError(TDFOLError):
    """Resource limits exceeded."""
```

#### 8.3.2 Error Recovery

```python
def parse_tdfol_safe(text: str) -> Optional[Formula]:
    """
    Safe parsing that never crashes.
    
    Returns None on parse failure.
    """
    try:
        return parse_tdfol(text)
    except ParseError as e:
        logger.warning(f"Parse failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected parse error: {e}")
        return None
```

### 8.4 Documentation

#### 8.4.1 API Documentation

Complete API documentation for all public classes and functions:

- Comprehensive docstrings with examples
- Type hints for all parameters and returns
- Usage examples for common scenarios
- Performance characteristics

#### 8.4.2 User Guide

Create comprehensive user guide:

- **Getting Started:** Installation, basic usage
- **Tutorials:** Step-by-step examples
- **How-To Guides:** Common tasks
- **Reference:** Complete API reference
- **Troubleshooting:** Common issues and solutions

#### 8.4.3 Developer Guide

Documentation for contributors:

- Architecture overview
- Adding new inference rules
- Adding new patterns
- Testing guidelines
- Performance optimization tips

### 8.5 Success Criteria

- ✅ Performance profiling and optimization
- ✅ Comprehensive error handling
- ✅ Security validation and resource limits
- ✅ Complete API documentation
- ✅ User guide and tutorials
- ✅ Developer guide
- ✅ Production-ready deployment

---

## 9. Implementation Roadmap

### 9.1 Timeline Overview

```
Phases 7-12: 16-20 weeks total

Week 1-4   : Phase 7  - Natural Language Processing
Week 5-9   : Phase 8  - Complete Prover
Week 10-13 : Phase 9  - Advanced Optimization
Week 14-17 : Phase 10 - Comprehensive Testing
Week 18-20 : Phase 11 - Visualization Tools
Week 21-23 : Phase 12 - Production Hardening
```

### 9.2 Detailed Schedule

#### Phase 7: Natural Language Processing (Weeks 1-4)

**Week 1:**
- [ ] Design NL processing architecture
- [ ] Set up spaCy pipeline
- [ ] Implement NL preprocessor
- [ ] Write 10 basic tests

**Week 2:**
- [ ] Implement pattern matcher (basic patterns)
- [ ] Add 20+ deontic patterns
- [ ] Add 10+ temporal patterns
- [ ] Write 20 pattern tests

**Week 3:**
- [ ] Implement TDFOL generator
- [ ] Add context resolver
- [ ] Write 20 generation tests

**Week 4:**
- [ ] Integration with existing parser
- [ ] End-to-end testing
- [ ] Documentation and examples
- [ ] Buffer for issues

#### Phase 8: Complete Prover (Weeks 5-9)

**Week 5:**
- [ ] Design new inference rules
- [ ] Implement 10 temporal rules
- [ ] Write 20 tests

**Week 6:**
- [ ] Implement 8 deontic rules
- [ ] Implement 10 combined rules
- [ ] Write 30 tests

**Week 7-8:**
- [ ] Implement modal tableaux prover
- [ ] Add K, T, D, S4, S5 support
- [ ] Countermodel generation
- [ ] Write 40 tests

**Week 9:**
- [ ] Integration with existing prover
- [ ] End-to-end testing
- [ ] Documentation
- [ ] Buffer for issues

#### Phase 9: Advanced Optimization (Weeks 10-13)

**Week 10:**
- [ ] Implement strategy selector
- [ ] Add backward chaining
- [ ] Add bidirectional search
- [ ] Write 15 tests

**Week 11:**
- [ ] Implement parallel prover
- [ ] Multi-strategy coordination
- [ ] Write 10 tests

**Week 12:**
- [ ] Implement heuristic search (A*)
- [ ] Add adaptive timeout
- [ ] Write 15 tests

**Week 13:**
- [ ] Performance benchmarking
- [ ] Optimization tuning
- [ ] Documentation

#### Phase 10: Comprehensive Testing (Weeks 14-17)

**Week 14:**
- [ ] Write 50 parser tests
- [ ] Write 30 core tests

**Week 15:**
- [ ] Write 100 prover tests
- [ ] Write 50 inference rule tests

**Week 16:**
- [ ] Write 60 NL parser tests (from Phase 7)
- [ ] Write 30 converter tests

**Week 17:**
- [ ] Property-based tests (40)
- [ ] Performance tests (20)
- [ ] CI/CD integration

#### Phase 11: Visualization Tools (Weeks 18-20)

**Week 18:**
- [ ] Implement proof tree visualizer
- [ ] ASCII, GraphViz, HTML output
- [ ] Write 10 tests

**Week 19:**
- [ ] Implement dependency graph visualizer
- [ ] Interactive visualizations
- [ ] Write 10 tests

**Week 20:**
- [ ] Implement inference trace visualizer
- [ ] Integration with prover
- [ ] Documentation

#### Phase 12: Production Hardening (Weeks 21-23)

**Week 21:**
- [ ] Performance profiling
- [ ] Implement optimizations
- [ ] Security audit

**Week 22:**
- [ ] Comprehensive error handling
- [ ] Resource limits
- [ ] Security validation

**Week 23:**
- [ ] Complete documentation
- [ ] User guide and tutorials
- [ ] Final testing and validation

### 9.3 Dependencies Between Phases

```
Phase 7 (NL) ─┐
              ├─→ Phase 10 (Testing) ─→ Phase 12 (Hardening)
Phase 8 (Prover) ─┤                  ↗
              ├─→ Phase 11 (Viz) ────┘
Phase 9 (Opt) ─┘
```

**Critical Path:** Phase 8 → Phase 10 → Phase 12

**Parallelizable:**
- Phase 7 can be partially parallel with Phase 8
- Phase 11 can be partially parallel with Phase 10

### 9.4 Milestone Checklist

**Milestone 1: Phase 7 Complete (Week 4)**
- [ ] NL parser can handle 20+ patterns
- [ ] 80%+ accuracy on test set
- [ ] 60+ tests passing
- [ ] Documentation complete

**Milestone 2: Phase 8 Complete (Week 9)**
- [ ] 50+ inference rules implemented
- [ ] Modal tableaux for K, T, D, S4, S5
- [ ] 120+ tests passing
- [ ] Documentation complete

**Milestone 3: Phase 9 Complete (Week 13)**
- [ ] 4+ proof strategies
- [ ] Parallel search working
- [ ] 2-5x speedup demonstrated
- [ ] 40+ tests passing

**Milestone 4: Phase 10 Complete (Week 17)**
- [ ] 330+ comprehensive tests
- [ ] 90%+ code coverage
- [ ] Property-based testing
- [ ] All tests in CI/CD

**Milestone 5: Phase 11 Complete (Week 20)**
- [ ] Proof tree visualization
- [ ] Dependency graphs
- [ ] Interactive visualizations
- [ ] 30+ tests passing

**Milestone 6: Phase 12 Complete (Week 23)**
- [ ] Performance optimized
- [ ] Security hardened
- [ ] Complete documentation
- [ ] Production-ready

---

## 10. Success Metrics

### 10.1 Functional Metrics

| Metric | Current | Phase 7 | Phase 8 | Phase 9 | Phase 10 | Phase 11 | Phase 12 | Target |
|--------|---------|---------|---------|---------|----------|----------|----------|--------|
| NL Patterns | 0 | 20+ | 20+ | 20+ | 20+ | 20+ | 20+ | 20+ |
| NL Accuracy | - | 80%+ | 80%+ | 80%+ | 80%+ | 80%+ | 85%+ | 85%+ |
| Inference Rules | 40 | 40 | 50+ | 50+ | 50+ | 50+ | 50+ | 50+ |
| Modal Logics | 0 | 0 | 5 | 5 | 5 | 5 | 5 | 5 (K,T,D,S4,S5) |
| Proof Strategies | 1 | 1 | 2 | 4+ | 4+ | 4+ | 4+ | 4+ |
| Tests | 97 | 157 | 277 | 317 | 440+ | 470+ | 470+ | 440+ |
| Code Coverage | ~70% | ~75% | ~80% | ~85% | 90%+ | 90%+ | 90%+ | 90%+ |

### 10.2 Performance Metrics

| Metric | Current | Target | Measurement |
|--------|---------|--------|-------------|
| Parse Time | ~1-5ms | < 3ms | Average for typical formula |
| Simple Proof | ~10-50ms | < 30ms | Direct lookup |
| Complex Proof | ~100-500ms | < 200ms | 10 inference steps |
| Cache Hit Speedup | 100-20000x | 100x+ | Maintained |
| Parallel Speedup | - | 2-5x | vs sequential |
| Memory per Formula | ~200 bytes | < 300 bytes | Average |

### 10.3 Quality Metrics

| Metric | Target | Verification |
|--------|--------|--------------|
| Test Pass Rate | 100% | All tests must pass |
| Code Coverage | 90%+ | pytest-cov |
| Documentation Coverage | 100% | All public APIs |
| Type Checking | 0 errors | mypy strict mode |
| Linting | 0 errors | flake8 |
| Security Issues | 0 | Bandit scan |

### 10.4 Adoption Metrics

| Metric | Target | Timeframe |
|--------|--------|-----------|
| API Stability | Stable | Phase 12 |
| Breaking Changes | 0 | After Phase 12 |
| Examples/Tutorials | 10+ | Phase 12 |
| Integration Examples | 5+ | Phase 12 |
| User Documentation | Complete | Phase 12 |

---

## 11. Risk Assessment

### 11.1 Technical Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| NL parsing accuracy < 80% | Medium | High | Start with high-confidence patterns, iterate |
| Modal tableaux complexity | High | Medium | Incremental implementation, focus on K first |
| Performance degradation | Low | High | Continuous profiling, optimization Phase 9 |
| Integration conflicts | Medium | Medium | Maintain backward compatibility |
| Test coverage gaps | Low | Medium | Comprehensive test plan Phase 10 |

### 11.2 Schedule Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Phase 8 overruns | Medium | High | 2-week buffer, reduce scope if needed |
| Phase 10 insufficient time | Low | Medium | Start tests early in each phase |
| Dependencies delay | Low | High | Parallel work where possible |

### 11.3 Resource Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Complex dependencies (spaCy) | Low | Low | Well-established library |
| Memory constraints | Low | Medium | Optimization Phase 9, resource limits |
| CI/CD capacity | Low | Low | Use existing infrastructure |

### 11.4 Mitigation Strategies

1. **Incremental Development:**
   - Build each phase incrementally
   - Test continuously
   - Maintain backward compatibility

2. **Early Validation:**
   - Start testing from Phase 7
   - Validate architecture decisions early
   - Get feedback on APIs

3. **Fallback Plans:**
   - Phase 7: If NL accuracy low, focus on pattern quality over quantity
   - Phase 8: If modal tableaux too complex, defer S5
   - Phase 9: If parallel speedup insufficient, focus on strategy selection

---

## 12. Appendix

### 12.1 Glossary

**TDFOL:** Temporal Deontic First-Order Logic - unified logic combining FOL, deontic logic, and temporal logic

**Deontic Logic:** Logic of obligations, permissions, and prohibitions (O, P, F operators)

**Temporal Logic:** Logic for reasoning about time (□, ◊, X, U, S operators)

**Modal Logic:** Logic with modal operators (necessarily, possibly) and accessibility relations

**Tableaux:** Proof method using tree structure to systematically explore formula truth

**LTL:** Linear Temporal Logic - temporal logic over linear time

**SDL:** Standard Deontic Logic - basic system for deontic reasoning

**CEC:** Cognitive Event Calculus - existing reasoning system in the repository

**GraphRAG:** Graph-based Retrieval-Augmented Generation

### 12.2 References

**Academic:**
- Chellas, B. F. (1980). Modal Logic: An Introduction.
- Meyer, J. J. Ch. (1988). A Different Approach to Deontic Logic.
- Pnueli, A. (1977). The Temporal Logic of Programs.
- Fitting, M. & Mendelsohn, R. L. (1998). First-Order Modal Logic.

**Implementation:**
- spaCy Documentation: https://spacy.io
- NetworkX: https://networkx.org
- Hypothesis Testing: https://hypothesis.readthedocs.io

**Related Systems:**
- E Prover: https://www.eprover.org
- Vampire: https://vprover.github.io
- Z3: https://github.com/Z3Prover/z3

### 12.3 File Structure (After Phases 7-12)

```
ipfs_datasets_py/logic/TDFOL/
├── __init__.py                           (250 LOC) - Updated exports
├── tdfol_core.py                         (551 LOC) - Core (unchanged)
├── tdfol_parser.py                       (564 LOC) - Parsing (unchanged)
├── tdfol_prover.py                       (900 LOC) - Enhanced prover
├── tdfol_inference_rules.py              (1,500 LOC) - 50+ rules
├── tdfol_proof_cache.py                  (92 LOC) - Cache (unchanged)
├── tdfol_converter.py                    (528 LOC) - Converters (unchanged)
├── tdfol_dcec_parser.py                  (373 LOC) - DCEC (unchanged)
│
├── nl/                                   [NEW] Natural Language Processing
│   ├── __init__.py                       (50 LOC)
│   ├── tdfol_nl_preprocessor.py          (300 LOC)
│   ├── tdfol_nl_patterns.py              (500 LOC)
│   ├── tdfol_nl_generator.py             (400 LOC)
│   └── tdfol_nl_context.py               (300 LOC)
│
├── prover/                               [NEW] Advanced Proving
│   ├── __init__.py                       (50 LOC)
│   ├── tdfol_modal_tableaux.py           (800 LOC)
│   ├── tdfol_proof_strategies.py         (500 LOC)
│   ├── tdfol_parallel_prover.py          (600 LOC)
│   └── tdfol_heuristic_search.py         (400 LOC)
│
├── visualization/                        [NEW] Visualization Tools
│   ├── __init__.py                       (50 LOC)
│   ├── tdfol_visualization_proof_tree.py (400 LOC)
│   ├── tdfol_visualization_dependencies.py (300 LOC)
│   └── tdfol_visualization_inference_trace.py (300 LOC)
│
├── security/                             [NEW] Security & Validation
│   ├── __init__.py                       (50 LOC)
│   ├── validation.py                     (300 LOC)
│   └── resource_limits.py                (200 LOC)
│
├── docs/                                 [NEW] Documentation
│   ├── USER_GUIDE.md
│   ├── DEVELOPER_GUIDE.md
│   ├── API_REFERENCE.md
│   ├── TUTORIALS.md
│   └── TROUBLESHOOTING.md
│
├── README.md                             (700 lines) - Updated
├── COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md (this document)
├── PHASE7_COMPLETE.md                    [Future]
├── PHASE8_COMPLETE.md                    [Future]
├── PHASE9_COMPLETE.md                    [Future]
├── PHASE10_COMPLETE.md                   [Future]
├── PHASE11_COMPLETE.md                   [Future]
└── PHASE12_COMPLETE.md                   [Future]

Total Estimated LOC: ~14,000 LOC (4,287 current + ~9,700 new)
```

### 12.4 Phase Completion Template

Each phase should create a completion document following this template:

```markdown
# Phase X: [Name] - Completion Report

**Status:** ✅ COMPLETE  
**Date:** YYYY-MM-DD  
**Duration:** X weeks (planned) / Y weeks (actual)

## Summary

Brief summary of phase goals and achievements.

## Deliverables

- [x] Component 1 (XXX LOC)
- [x] Component 2 (XXX LOC)
- [x] Tests (XX tests, 100% pass)
- [x] Documentation

## Statistics

- **LOC Added:** X,XXX implementation + Y,YYY tests
- **Tests:** XX tests (100% pass rate)
- **Coverage:** XX%
- **Performance:** Key metrics

## Key Features

1. Feature 1
2. Feature 2
3. Feature 3

## Example Usage

```python
# Code examples
```

## Testing Summary

- Unit tests: XX
- Integration tests: YY
- Property tests: ZZ

## Known Issues

List any known issues or limitations.

## Next Steps

Links to next phase.
```

---

## Document Control

**Version History:**

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2026-02-18 | GitHub Copilot Agent | Initial comprehensive plan |

**Review Status:** 📝 Draft - Awaiting stakeholder review

**Approval:** Pending

---

**END OF DOCUMENT**
