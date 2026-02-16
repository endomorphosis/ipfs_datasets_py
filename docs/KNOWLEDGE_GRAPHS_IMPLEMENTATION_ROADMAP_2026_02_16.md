# Knowledge Graphs Implementation Roadmap
## Actionable Plan Forward from 2026-02-16

**Date:** 2026-02-16  
**Current Status:** Phase 2 (35% complete), continuing from PRs #955 and #960  
**Overall Progress:** Phase 1 ✅ | Phase 2 🔄 | Phase 3 📋 | Phase 4-6 ⏳  

---

## 🎯 Quick Reference

**Where We Are:**
- ✅ Phase 1: Core Graph Database (100% - 210 tests passing)
- 🔄 Phase 2: Neo4j Compatibility (35% - critical items in progress)
- 📋 Phase 3: JSON-LD Enhancement (40% - foundation exists)
- ⏳ Phase 4-6: Not started

**What to Do Next:** Choose one of three paths based on priorities

---

## 📊 Three Implementation Paths

### Path A: Complete Neo4j Compatibility (Recommended for Migration Support)

**Duration:** 26 hours  
**Outcome:** 82% overall Neo4j parity, complete Cypher function support  
**Priority:** 🔴 HIGH - Enables Neo4j migration path  

**Tasks:**
1. Add list functions (10 hours)
2. Add introspection functions (8 hours)
3. Add remaining math functions (8 hours)

**Why This Path:**
- Completes Phase 2 critical path
- Enables Neo4j users to migrate
- Increases compatibility from 79% to 82%
- Natural continuation from PR #960

---

### Path B: GraphRAG Consolidation (Recommended for Code Quality)

**Duration:** 110 hours (3 weeks)  
**Outcome:** 40% code reduction, unified architecture, improved maintainability  
**Priority:** 🔴 HIGHEST - Critical technical debt  

**Tasks:**
1. Create unified query engine (50 hours)
2. Consolidate budget system (10 hours)
3. Extract hybrid search (20 hours)
4. Simplify processors (15 hours)
5. Update integrations (5 hours)
6. Testing & validation (10 hours)

**Why This Path:**
- Eliminates ~4,000 lines of duplicated code
- Unifies 3 fragmented implementations
- Improves maintainability for all future work
- Reduces technical debt significantly

---

### Path C: Semantic Web Foundation (Recommended for RDF/Linked Data)

**Duration:** 48 hours (6 days)  
**Outcome:** Complete semantic web support with 9+ vocabularies, SHACL, RDF  
**Priority:** 🟡 MEDIUM - Niche but important for some use cases  

**Tasks:**
1. Expand vocabularies (15 hours)
2. Implement SHACL validation (20 hours)
3. Add Turtle RDF serialization (8 hours)
4. Testing & documentation (5 hours)

**Why This Path:**
- Completes Phase 3 foundations
- Enables semantic web applications
- Adds RDF/linked data support
- Differentiates from Neo4j

---

## 🗺️ Detailed Roadmap

### Path A Details: Complete Neo4j Compatibility

#### Session 1: List Functions (10 hours)

**Goal:** Add 6 essential list manipulation functions

**Implementation:**
```python
# Add to ipfs_datasets_py/knowledge_graphs/cypher/functions.py

def fn_range(start: int, end: int, step: int = 1) -> List[int]:
    """Generate range of numbers."""
    return list(range(start, end, step))

def fn_head(lst: List) -> Any:
    """Get first element of list."""
    return lst[0] if lst else None

def fn_tail(lst: List) -> List:
    """Get all but first element."""
    return lst[1:] if len(lst) > 1 else []

def fn_last(lst: List) -> Any:
    """Get last element of list."""
    return lst[-1] if lst else None

def fn_reverse(lst: List) -> List:
    """Reverse list."""
    return list(reversed(lst))

def fn_reduce(lst: List, expr: str, accumulator: str, initial: Any) -> Any:
    """Reduce list with accumulator."""
    # Implementation with expression evaluation
    pass
```

**Tests:** Create `tests/unit/knowledge_graphs/test_list_functions.py`
- Test each function with various inputs
- Test NULL handling
- Test edge cases (empty lists, single elements)

**Deliverable:** 6 new functions, 20+ tests

---

#### Session 2: Introspection Functions (8 hours)

**Goal:** Add functions for type inspection and metadata

**Implementation:**
```python
def fn_type(relationship: Relationship) -> str:
    """Get relationship type."""
    return relationship.type

def fn_id(entity: Union[Node, Relationship]) -> str:
    """Get entity ID."""
    return entity.id

def fn_properties(entity: Union[Node, Relationship]) -> Dict:
    """Get all properties."""
    return dict(entity)

def fn_labels(node: Node) -> List[str]:
    """Get node labels."""
    return node.labels

def fn_keys(obj: Union[Dict, Node, Relationship]) -> List[str]:
    """Get keys/property names."""
    if isinstance(obj, (Node, Relationship)):
        return list(obj.properties.keys())
    return list(obj.keys())
```

**Tests:** Create `tests/unit/knowledge_graphs/test_introspection_functions.py`

**Deliverable:** 5 new functions, 15+ tests

---

#### Session 3: Extended Math Functions (8 hours)

**Goal:** Add trigonometric and logarithmic functions

**Implementation:**
```python
import math

# Trigonometric
def fn_sin(n: float) -> float: return math.sin(n)
def fn_cos(n: float) -> float: return math.cos(n)
def fn_tan(n: float) -> float: return math.tan(n)
def fn_asin(n: float) -> float: return math.asin(n)
def fn_acos(n: float) -> float: return math.acos(n)
def fn_atan(n: float) -> float: return math.atan(n)
def fn_atan2(y: float, x: float) -> float: return math.atan2(y, x)

# Logarithmic
def fn_log(n: float) -> float: return math.log(n)
def fn_log10(n: float) -> float: return math.log10(n)
def fn_exp(n: float) -> float: return math.exp(n)

# Constants
def fn_pi() -> float: return math.pi
def fn_e() -> float: return math.e
```

**Tests:** Create `tests/unit/knowledge_graphs/test_extended_math_functions.py`

**Deliverable:** 12 new functions, 25+ tests

---

#### Path A Summary

**Total Time:** 26 hours  
**Total New Functions:** 23  
**Total New Tests:** 60+  
**Neo4j Parity:** 79% → 82%  

**Success Criteria:**
- ✅ All 38 essential Cypher functions implemented
- ✅ 270+ total tests passing
- ✅ Function registry complete
- ✅ Documentation updated

---

### Path B Details: GraphRAG Consolidation

#### Session 1-2: Unified Query Engine (50 hours)

**Goal:** Create single entry point for all query types

**Create:** `ipfs_datasets_py/knowledge_graphs/query/unified_engine.py`

```python
"""
Unified Query Engine

Consolidates query execution from:
- processors/graphrag/integration.py
- search/graphrag_integration/
- search/graph_query/executor.py
"""

from typing import Dict, Any, Optional
from ipfs_datasets_py.knowledge_graphs.storage.ipld_backend import IPLDBackend
from ipfs_datasets_py.search.graph_query.budgets import ExecutionBudgets

class UnifiedQueryEngine:
    """
    Single entry point for all query types.
    
    Replaces fragmented implementations with unified architecture.
    """
    
    def __init__(self, backend: IPLDBackend):
        self.backend = backend
        self.graph_engine = GraphEngine(backend)
        self.ir_executor = IRExecutor(backend)
        self.hybrid_search = HybridSearchEngine(backend)
        self.budget_manager = BudgetManager()
    
    def execute_cypher(
        self,
        query: str,
        params: Dict[str, Any],
        budgets: ExecutionBudgets
    ) -> Result:
        """
        Execute Cypher query with budget enforcement.
        
        Args:
            query: Cypher query string
            params: Query parameters
            budgets: Execution budgets
            
        Returns:
            Query results
        """
        # Parse Cypher → AST → IR
        ir = self.cypher_compiler.compile(query, params)
        return self.execute_ir(ir, budgets)
    
    def execute_ir(
        self,
        ir: QueryIR,
        budgets: ExecutionBudgets
    ) -> ExecutionResult:
        """
        Execute IR-based query.
        
        Args:
            ir: Intermediate representation
            budgets: Execution budgets
            
        Returns:
            Execution results with counters
        """
        with self.budget_manager.track(budgets):
            return self.ir_executor.execute(ir)
    
    def execute_hybrid(
        self,
        query: str,
        embeddings: Dict[str, Any],
        budgets: ExecutionBudgets,
        k: int = 10
    ) -> HybridResult:
        """
        Execute hybrid vector+graph search.
        
        Args:
            query: Search query
            embeddings: Vector embeddings
            budgets: Execution budgets
            k: Number of results
            
        Returns:
            Hybrid search results
        """
        # Combine vector similarity with graph traversal
        vector_results = self.hybrid_search.vector_search(
            query, embeddings, k
        )
        graph_results = self.hybrid_search.expand_graph(
            vector_results, depth=2
        )
        return self.hybrid_search.fuse_results(
            vector_results, graph_results, alpha=0.7
        )
    
    def execute_graphrag(
        self,
        question: str,
        context: Dict[str, Any],
        budgets: ExecutionBudgets
    ) -> GraphRAGResult:
        """
        Execute full GraphRAG pipeline with LLM reasoning.
        
        Args:
            question: User question
            context: Context including embeddings
            budgets: Execution budgets
            
        Returns:
            GraphRAG results with reasoning
        """
        # Use hybrid search + LLM reasoning
        search_results = self.execute_hybrid(
            question,
            context.get('embeddings', {}),
            budgets
        )
        reasoning = self.llm_reasoner.reason(
            question, search_results
        )
        return GraphRAGResult(
            results=search_results,
            reasoning=reasoning
        )
```

**Files to Create:**
- `knowledge_graphs/query/__init__.py`
- `knowledge_graphs/query/unified_engine.py` (~500 lines)
- `knowledge_graphs/query/hybrid_search.py` (~300 lines)
- `knowledge_graphs/query/budget_manager.py` (~200 lines)

**Files to Modify:**
- `processors/graphrag/integration.py` - Use unified engine
- `search/graphrag_integration/graphrag_integration.py` - Use unified engine
- `search/graph_query/executor.py` - Merge into unified engine

**Tests:** Create `tests/unit/knowledge_graphs/test_unified_engine.py`

**Deliverable:** Unified architecture, ~1,000 new lines, ~4,000 lines removed

---

#### Session 3: Budget System Consolidation (10 hours)

**Goal:** Adopt canonical budget system

**Strategy:**
1. Make `search/graph_query/budgets.py` canonical
2. Remove duplicate implementations
3. Import from canonical location

```python
# All modules import from here
from ipfs_datasets_py.search.graph_query.budgets import (
    ExecutionBudgets,
    ExecutionCounters,
    budgets_from_preset
)

# Standard usage
budgets = budgets_from_preset('moderate')
result = engine.execute_cypher(query, params, budgets)
```

**Deliverable:** Single source of truth for budgets

---

#### Session 4: Extract Hybrid Search (20 hours)

**Goal:** Create reusable hybrid search component

**Create:** `knowledge_graphs/query/hybrid_search.py`

```python
class HybridSearchEngine:
    """
    Hybrid search combining vector similarity and graph traversal.
    """
    
    def vector_search(
        self,
        query: str,
        embeddings: Dict[str, Any],
        k: int = 10
    ) -> List[Node]:
        """Vector similarity search."""
        # Use vector index for fast similarity search
        pass
    
    def expand_graph(
        self,
        seed_nodes: List[Node],
        depth: int = 2,
        rel_types: Optional[List[str]] = None
    ) -> List[Path]:
        """Expand from seed nodes via graph traversal."""
        # Use graph engine for multi-hop traversal
        pass
    
    def fuse_results(
        self,
        vector_results: List[Node],
        graph_results: List[Path],
        alpha: float = 0.7
    ) -> HybridResult:
        """Fuse vector and graph results with weighted combination."""
        # Combine with reciprocal rank fusion
        pass
```

**Deliverable:** Reusable hybrid search, ~300 lines

---

#### Session 5: Simplify Processors (15 hours)

**Goal:** Focus processors on content extraction only

**Refactor:** `processors/graphrag/content_processor.py`

```python
class ContentProcessor:
    """
    Focus ONLY on content extraction.
    
    No query logic - use unified engine instead.
    """
    
    def process_website(self, url: str) -> Dict:
        """
        Extract content from website.
        
        Returns:
            Content data (text, media, metadata)
        """
        # Crawl website
        # Extract text, media
        # Archive content
        # Return raw data (no queries!)
        return {'text': ..., 'media': ..., 'archived': ...}
    
    def extract_entities(self, text: str) -> List[Entity]:
        """
        Extract entities from text.
        
        Returns:
            Entity list (no graph operations!)
        """
        # NER, entity linking
        # Return entities only
        return entities
```

**Deliverable:** Simplified processors, clear separation of concerns

---

#### Session 6: Update Integrations & Testing (15 hours)

**Goal:** Update all GraphRAG integrations to use unified engine

**Modifications:**
- `search/graphrag_integration/graphrag_integration.py` (1,000 → 50 lines)
- `processors/graphrag/integration.py` (update to use unified engine)

**Testing:**
- Verify no performance regression
- Test all query types
- Integration tests for GraphRAG pipeline

**Deliverable:** All integrations updated, tests passing

---

#### Path B Summary

**Total Time:** 110 hours  
**Code Reduction:** ~4,000 lines (40%)  
**New Code:** ~1,500 lines (unified architecture)  
**Net Reduction:** ~2,500 lines  

**Success Criteria:**
- ✅ Unified query engine operational
- ✅ All query types working
- ✅ No performance regression
- ✅ 40%+ code reduction achieved
- ✅ Improved maintainability metrics

---

### Path C Details: Semantic Web Foundation

#### Session 1: Expand Vocabularies (15 hours)

**Goal:** Add 4+ vocabularies with extended coverage

**Create:** `ipfs_datasets_py/knowledge_graphs/jsonld/vocabularies/`

**Files to Create:**
1. `schema_org.py` - Extended Schema.org (3 hours)
2. `foaf.py` - Extended FOAF (2 hours)
3. `dublin_core.py` - Complete DC Terms (2 hours)
4. `skos.py` - Extended SKOS (3 hours)
5. `geonames.py` - Geographic entities (2 hours)
6. `dbpedia.py` - Linked data ontology (2 hours)
7. `prov_o.py` - Provenance vocabulary (1 hour)

**Implementation Pattern:**
```python
# vocabularies/schema_org.py

SCHEMA_ORG_VOCABULARY = {
    # Types
    'Person': 'http://schema.org/Person',
    'Organization': 'http://schema.org/Organization',
    'Place': 'http://schema.org/Place',
    'Product': 'http://schema.org/Product',
    'Event': 'http://schema.org/Event',
    
    # Properties
    'name': 'http://schema.org/name',
    'email': 'http://schema.org/email',
    'telephone': 'http://schema.org/telephone',
    'address': 'http://schema.org/address',
    'birthDate': 'http://schema.org/birthDate',
    
    # ... 100+ more terms
}
```

**Update:** `jsonld/context.py` to load vocabularies

**Deliverable:** 9 vocabularies, 500+ terms

---

#### Session 2: SHACL Validation (20 hours)

**Goal:** Implement core SHACL constraint validation

**Create:** `ipfs_datasets_py/knowledge_graphs/jsonld/shacl_validator.py`

```python
class SHACLValidator:
    """
    SHACL (Shapes Constraint Language) validator.
    
    Validates RDF data against shape constraints.
    """
    
    def validate(
        self,
        data_graph: Graph,
        shapes_graph: ShapesGraph
    ) -> ValidationReport:
        """
        Validate RDF data against SHACL shapes.
        
        Args:
            data_graph: RDF data to validate
            shapes_graph: SHACL shapes defining constraints
            
        Returns:
            Validation report with violations
        """
        violations = []
        
        for shape in shapes_graph.shapes:
            target_nodes = self._get_target_nodes(shape, data_graph)
            
            for node in target_nodes:
                # Check each constraint
                for constraint in shape.constraints:
                    if not self._check_constraint(node, constraint):
                        violations.append(
                            Violation(
                                severity=constraint.severity,
                                source_shape=shape,
                                focus_node=node,
                                path=constraint.path,
                                message=constraint.message
                            )
                        )
        
        return ValidationReport(violations)
    
    def _check_constraint(
        self,
        node: Node,
        constraint: Constraint
    ) -> bool:
        """Check single constraint."""
        if constraint.type == 'minCount':
            return self._check_min_count(node, constraint)
        elif constraint.type == 'maxCount':
            return self._check_max_count(node, constraint)
        elif constraint.type == 'datatype':
            return self._check_datatype(node, constraint)
        # ... more constraint types
```

**Constraints to Implement:**
1. Cardinality: minCount, maxCount (3 hours)
2. Value Type: datatype, class, nodeKind (4 hours)
3. Value Range: minInclusive, maxInclusive (4 hours)
4. String: minLength, maxLength, pattern (3 hours)
5. Property Pairs: equals, disjoint, lessThan (3 hours)
6. Reporting: violations, severity, messages (3 hours)

**Deliverable:** SHACL validator, ~600 lines

---

#### Session 3: Turtle RDF Serialization (8 hours)

**Goal:** Export graph data as Turtle RDF

**Create:** `ipfs_datasets_py/knowledge_graphs/jsonld/turtle_serializer.py`

```python
class TurtleSerializer:
    """
    Turtle RDF serialization.
    
    Exports graph data in Turtle format.
    """
    
    def serialize(self, graph: Graph) -> str:
        """
        Convert graph to Turtle format.
        
        Args:
            graph: Graph to serialize
            
        Returns:
            Turtle RDF string
        """
        output = []
        
        # Prefixes
        for prefix, uri in self.prefixes.items():
            output.append(f"@prefix {prefix}: <{uri}> .")
        output.append("")
        
        # Triples grouped by subject
        for subject in graph.subjects():
            output.append(f"<{subject}>")
            
            properties = graph.properties(subject)
            for i, (pred, obj) in enumerate(properties):
                sep = ";" if i < len(properties) - 1 else "."
                output.append(f"    {pred} {obj} {sep}")
            output.append("")
        
        return "\n".join(output)
```

**Features:**
1. Prefix management (2 hours)
2. Triple generation (3 hours)
3. Pretty printing (2 hours)
4. Round-trip validation (1 hour)

**Deliverable:** Turtle serializer, ~400 lines

---

#### Path C Summary

**Total Time:** 48 hours  
**New Vocabularies:** 7 (total 12)  
**New Terms:** 500+  
**New Validation:** Core SHACL  
**New Serialization:** Turtle RDF  

**Success Criteria:**
- ✅ 9+ vocabularies supported
- ✅ SHACL validation operational
- ✅ Turtle RDF export working
- ✅ Round-trip validation passing
- ✅ 40+ Phase 3 tests

---

## 🎯 Recommended Sequence

### Option 1: User-Focused Path
**For enabling Neo4j migration**

1. **Path A** (26 hours) - Complete Neo4j compatibility
2. **Path B** (110 hours) - GraphRAG consolidation
3. **Path C** (48 hours) - Semantic web foundation

**Total:** 184 hours (~5 weeks)  
**Result:** Complete Phase 2 & 3, ready for Phase 4-5

---

### Option 2: Quality-Focused Path
**For technical excellence**

1. **Path B** (110 hours) - GraphRAG consolidation
2. **Path A** (26 hours) - Complete Neo4j compatibility
3. **Path C** (48 hours) - Semantic web foundation

**Total:** 184 hours (~5 weeks)  
**Result:** Clean architecture first, then features

---

### Option 3: Balanced Path
**For parallel progress**

1. **Path A** (26 hours) - Complete Neo4j compatibility
2. **Path C** (48 hours) - Semantic web foundation
3. **Path B** (110 hours) - GraphRAG consolidation

**Total:** 184 hours (~5 weeks)  
**Result:** Feature complete, then refactor

---

## 📈 Success Metrics

### By End of Path A
- ✅ 82% Neo4j API parity (from 79%)
- ✅ 38 Cypher functions (from 15)
- ✅ 270+ tests passing
- ✅ Neo4j migration path complete

### By End of Path B
- ✅ 40% code reduction (~2,500 lines)
- ✅ Unified query engine
- ✅ Zero duplication in GraphRAG
- ✅ Improved maintainability

### By End of Path C
- ✅ 12 vocabularies (from 5)
- ✅ Core SHACL validation
- ✅ Turtle RDF serialization
- ✅ Semantic web ready

### Overall (All Paths Complete)
- ✅ Phase 2: 90%+ complete
- ✅ Phase 3: 100% complete
- ✅ Phase 4: Not started (requires new plan)
- ✅ 300+ tests passing
- ✅ Production-ready for all use cases

---

## 📚 Supporting Documentation

### Before Starting
Read these documents in order:
1. [KNOWLEDGE_GRAPHS_DOCUMENTATION_INDEX.md](./KNOWLEDGE_GRAPHS_DOCUMENTATION_INDEX.md) - Navigation guide
2. [KNOWLEDGE_GRAPHS_IMPLEMENTATION_STATUS_2026_02_16.md](./KNOWLEDGE_GRAPHS_IMPLEMENTATION_STATUS_2026_02_16.md) - Current status
3. [PHASE_2_3_IMPLEMENTATION_PLAN.md](./PHASE_2_3_IMPLEMENTATION_PLAN.md) - Detailed plans

### During Implementation
Reference these as needed:
- [KNOWLEDGE_GRAPHS_QUICK_REFERENCE.md](./KNOWLEDGE_GRAPHS_QUICK_REFERENCE.md) - Quick lookup
- [KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md](./KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md) - Complete plan
- [SESSION_PHASE_2_CRITICAL_IMPLEMENTATION_COMPLETE.md](./SESSION_PHASE_2_CRITICAL_IMPLEMENTATION_COMPLETE.md) - Recent work

### After Completion
Update these documents:
- [KNOWLEDGE_GRAPHS_CURRENT_STATUS.md](./KNOWLEDGE_GRAPHS_CURRENT_STATUS.md) - Update status
- [KNOWLEDGE_GRAPHS_IMPLEMENTATION_STATUS_2026_02_16.md](./KNOWLEDGE_GRAPHS_IMPLEMENTATION_STATUS_2026_02_16.md) - Update metrics
- Create new completion report

---

## 🔗 Related Pull Requests

### Completed
- **PR #955:** Phase 1 implementation
- **PR #960:** Phase 2 critical items

### Planned
- **PR #961:** Path A - Complete Cypher functions
- **PR #962:** Path B - GraphRAG consolidation
- **PR #963:** Path C - Semantic web foundation

---

## 📝 Implementation Notes

### Development Environment
```bash
# Setup
cd /home/runner/work/ipfs_datasets_py/ipfs_datasets_py
python install.py --quick
pip install -e ".[all]"

# Run tests
pytest tests/unit/knowledge_graphs/ -v

# Run specific test
pytest tests/unit/knowledge_graphs/test_cypher_integration.py -v
```

### Code Style
- Follow existing patterns in `cypher/functions.py`
- Add comprehensive docstrings
- Include type hints
- Handle NULL/None gracefully
- Write tests first (TDD)

### Commit Messages
- Use semantic commit messages
- Reference issue/PR numbers
- Keep commits focused and small

### Testing Strategy
- Write tests before implementation
- Test NULL handling
- Test edge cases
- Maintain 95%+ coverage

---

**Status:** Ready for implementation  
**Next Action:** Choose Path A, B, or C  
**Prepared by:** GitHub Copilot Agent  
**Last Updated:** 2026-02-16  
