# Knowledge Graphs - Deferred Features

**Last Updated:** 2026-02-18  
**Purpose:** Explicitly document features marked for future implementation

---

## Overview

This document clarifies which features in the knowledge_graphs module are **intentionally incomplete** with planned implementation in future versions. These are not bugs or oversights - they are deliberate deferrals based on prioritization and user feedback.

---

## P1: High Priority (v2.1.0 - Q2 2026)

### 1. Cypher NOT Operator

**Status:** 🟡 Planned for v2.1.0  
**Location:** `cypher/compiler.py`  
**Current State:** Commented out implementation  
**Reason for Deferral:** Needed to ship v1.0 quickly; workarounds exist

**Impact:**
- **Medium** - Affects query expressiveness
- Workaround: Rewrite queries using positive logic

**Example:**
```cypher
-- Wanted:
MATCH (p:Person)
WHERE NOT p.age > 30
RETURN p

-- Current workaround:
MATCH (p:Person)
WHERE p.age <= 30
RETURN p
```

**Timeline:** v2.1.0 (June 2026)  
**Effort:** 2-3 hours (implementation + tests)

---

### 2. Cypher CREATE Relationships

**Status:** 🟡 Planned for v2.1.0  
**Location:** `cypher/compiler.py:510`  
**Current State:** `pass` statement with TODO comment  
**Reason for Deferral:** Basic graph construction works via Python API

**Impact:**
- **Medium** - Affects Neo4j API parity
- Workaround: Use property graph API directly

**Example:**
```cypher
-- Wanted:
MATCH (a:Person {name: 'Alice'}), (b:Person {name: 'Bob'})
CREATE (a)-[r:KNOWS]->(b)
RETURN r

-- Current workaround (Python):
graph.add_relationship(alice_node, bob_node, "KNOWS")
```

**Timeline:** v2.1.0 (June 2026)  
**Effort:** 3-4 hours (implementation + tests)

---

## P2: Medium Priority (v2.2.0 - Q3 2026)

### 3. GraphML Format Support

**Status:** 🔴 Not Implemented  
**Location:** `migration/formats.py:171, :198`  
**Current State:** Raises `NotImplementedError`  
**Reason for Deferral:** Limited user demand; CSV/JSON work well

**Impact:**
- **Low** - Affects migration from Gephi/yEd
- Workaround: Export to CSV or JSON first

**Example:**
```python
# Currently raises NotImplementedError
save_to_file(graph, "output.graphml", format="graphml")

# Workaround:
save_to_file(graph, "output.csv", format="csv")
```

**Timeline:** v2.2.0 (August 2026)  
**Effort:** 8-10 hours (parser + serializer + tests)

---

### 4. GEXF Format Support

**Status:** 🔴 Not Implemented  
**Location:** `migration/formats.py:171, :198`  
**Current State:** Raises `NotImplementedError`  
**Reason for Deferral:** Similar to GraphML; limited demand

**Impact:**
- **Low** - Affects Gephi users
- Workaround: Use CSV export instead

**Timeline:** v2.2.0 (August 2026)  
**Effort:** 6-8 hours (similar to GraphML)

---

### 5. Pajek Format Support

**Status:** 🔴 Not Implemented  
**Location:** `migration/formats.py:171, :198`  
**Current State:** Raises `NotImplementedError`  
**Reason for Deferral:** Very limited use case

**Impact:**
- **Very Low** - Affects only Pajek users
- Workaround: Convert via intermediate format

**Timeline:** v2.2.0 (August 2026)  
**Effort:** 4-6 hours (read-only initially)

---

### 6. CAR Format Support

**Status:** ✅ Implemented (v2.1.0 — 2026-02-19)
**Location:** `migration/formats.py` — `_builtin_save_car` / `_builtin_load_car`
**Library decision:**
- **Option 1 — `libipld` (v3.3.2, Rust-backed):** Fast DAG-CBOR encoding/decoding and
  CAR decoding. No `encode_car` function. Used as primary decoder (faster, Rust extension).
- **Option 2 — `ipld-car` (v0.0.1) + `ipld-dag-pb` (v0.0.1):** Pure-Python CAR
  encode + decode, supports any codec. `ipld-dag-pb` not needed for graph data.
- **Decision:** Use `libipld` for DAG-CBOR encoding + `ipld-car` for CAR file
  creation. Decode prefers `libipld` (fast), falls back to `ipld-car` + `dag-cbor`.

**Install extras:** `pip install -e ".[ipld]"` (adds `libipld`, `ipld-car`, `dag-cbor`)

**Usage:**
```python
from ipfs_datasets_py.knowledge_graphs.migration.formats import (
    GraphData, MigrationFormat,
)
graph_data.save_to_file("graph.car", format=MigrationFormat.CAR)
loaded = GraphData.load_from_file("graph.car", format=MigrationFormat.CAR)
```

**Timeline:** Delivered in v2.1.0 (February 2026)  
**Effort:** 4 hours (implementation + tests)

---

## P3: Lower Priority (v2.5.0 - Q3-Q4 2026)

### 7. Neural Relationship Extraction

**Status:** 📋 Future (v2.5.0)  
**Location:** `extraction/extractor.py:733`  
**Current State:** `pass` statement with TODO(future) comment  
**Reason for Deferral:** Rule-based extraction works well; neural adds dependencies

**Impact:**
- **Low** - Current extraction is sufficient for most use cases
- No workaround needed - feature is enhancement, not core

**Details:**
- Would use transformer models (REBEL, LUKE) for relationship extraction
- Requires `transformers` library (heavy dependency)
- Needs training data for fine-tuning
- Waiting for production feedback to justify complexity

**Example:**
```python
# Planned for v2.5.0:
extractor = KnowledgeGraphExtractor(use_neural=True, model="facebook/rebel-large")
kg = extractor.extract_knowledge_graph(text)
# Should improve relationship accuracy by 10-15%
```

**Timeline:** v2.5.0 (November 2026)  
**Effort:** 20-24 hours (model integration + evaluation + tests)

---

### 8. Aggressive Entity Extraction (spaCy Dependency Parsing)

**Status:** 📋 Future (v2.5.0)  
**Location:** `extraction/extractor.py:870`  
**Current State:** `pass` statement with TODO(future) comment  
**Reason for Deferral:** Standard extraction covers most use cases

**Impact:**
- **Low** - Enhancement for complex sentences
- No workaround needed - current extraction works

**Details:**
- Would use spaCy's dependency parser for better entity extraction
- spaCy is already installed but not fully utilized
- Features compound noun handling, subject-verb-object extraction
- Waiting for user feedback on current extraction quality

**Example:**
```python
# Planned for v2.5.0:
extractor = KnowledgeGraphExtractor(
    aggressive_extraction=True,
    use_dependency_parsing=True
)
# Should increase entity recall by 15-20%
```

**Timeline:** v2.5.0 (November 2026)  
**Effort:** 16-20 hours (parser integration + tests + evaluation)

---

### 9. Semantic Role Labeling (SRL)

**Status:** 📋 Research (v2.5.0)  
**Location:** Not yet implemented  
**Current State:** Not started  
**Reason for Deferral:** Advanced feature; needs research

**Impact:**
- **Very Low** - Specialized use case
- Not needed for core functionality

**Details:**
- Would use AllenNLP for frame-semantic parsing
- Enables event-centric knowledge graphs
- Improves temporal relationship detection
- Requires significant research and evaluation

**Timeline:** v2.5.0 (November 2026) - Experimental  
**Effort:** 30-40 hours (research + implementation + evaluation)

---

## P4: Long-term (v3.0.0 - Q1 2027)

### 10. Multi-hop Graph Traversal

**Status:** 📋 Future (v3.0.0)  
**Location:** `cross_document_reasoning.py:~400-450`  
**Current State:** Placeholder comments  
**Reason for Deferral:** Single-hop traversal sufficient for v1.0/v2.0

**Impact:**
- **Medium** - Needed for advanced reasoning
- Current: Single-hop queries work fine

**Details:**
- Would implement shortest path algorithms
- All paths enumeration with filtering
- Path ranking and scoring
- Graph pattern matching (beyond Cypher)

**Example:**
```cypher
-- Planned for v3.0.0:
MATCH path = (a:Person)-[*1..5]-(b:Person)
WHERE a.name = 'Alice' AND b.name = 'Charlie'
RETURN path, length(path)
ORDER BY length(path)
```

**Timeline:** v3.0.0 (February 2027)  
**Effort:** 40-50 hours (algorithms + optimization + tests)

---

### 11. LLM API Integration

**Status:** 📋 Future (v3.0.0)  
**Location:** `cross_document_reasoning.py:740`  
**Current State:** Placeholder comments  
**Reason for Deferral:** LLM APIs still evolving; waiting for stability

**Impact:**
- **Low to Medium** - Enhancement for natural language queries
- Not core functionality

**Details:**
- Would integrate OpenAI, Anthropic, local models
- Natural language to Cypher translation
- Entity/relationship extraction enhancement
- Graph question answering
- Semantic similarity via embeddings

**Example:**
```python
# Planned for v3.0.0:
engine = UnifiedQueryEngine(
    backend=backend,
    llm_provider="openai",
    llm_model="gpt-4"
)

# Natural language query
results = engine.natural_language_query(
    "Who did Marie Curie collaborate with at the University of Paris?"
)
```

**Timeline:** v3.0.0 (February 2027)  
**Effort:** 60-80 hours (multiple providers + evaluation + tests)

---

### 12. Inference Rules and Ontology Reasoning

**Status:** 📋 Research (v3.0.0+)  
**Location:** Not yet implemented  
**Current State:** Not started  
**Reason for Deferral:** Advanced feature requiring research

**Impact:**
- **Low** - Specialized reasoning use cases
- Not needed for most users

**Details:**
- OWL/RDFS reasoning
- Custom inference rules
- Consistency checking
- Automated fact derivation

**Timeline:** v3.0.0+ (Q1 2027 or later)  
**Effort:** 80-100 hours (significant research + implementation)

---

### 13. Distributed Query Execution

**Status:** 📋 Research (v3.0.0+)  
**Location:** Not yet implemented  
**Current State:** Not started  
**Reason for Deferral:** Not needed for current scale targets

**Impact:**
- **Low** - Only needed for massive graphs (100M+ nodes)
- Current implementation handles up to 10M nodes efficiently

**Timeline:** v3.0.0+ (Q1 2027 or later)  
**Effort:** 100-120 hours (partitioning + federation + tests)

---

## How to Use This Document

### For Users

**Encountering a missing feature?**
1. Check this document to see if it's intentionally deferred
2. Check the workaround section for alternatives
3. See the timeline for when it might be implemented
4. Open a GitHub issue if you need it sooner (helps prioritization)

### For Contributors

**Want to implement a deferred feature?**
1. Check the timeline and priority
2. Review the effort estimate
3. See [CONTRIBUTING.md](../../docs/knowledge_graphs/CONTRIBUTING.md) for guidelines
4. Open an issue to discuss before starting work
5. Reference this document in your PR

### For Maintainers

**Adding a new deferred feature:**
1. Add entry to appropriate priority section
2. Include location, status, reason, impact, example, timeline, effort
3. Update ROADMAP.md with the same information
4. Update MASTER_STATUS.md to reflect the updated deferred feature list/status

---

## See Also

- [ROADMAP.md](ROADMAP.md) - Complete development timeline
- [MASTER_STATUS.md](./MASTER_STATUS.md) - Current status (single source of truth)
- [COMPREHENSIVE_ANALYSIS_2026_02_18.md](./COMPREHENSIVE_ANALYSIS_2026_02_18.md) - Comprehensive analysis
- [IMPROVEMENT_TODO.md](./IMPROVEMENT_TODO.md) - Infinite improvement backlog

---

**Last Updated:** 2026-02-18  
**Next Review:** Q2 2026 (after v2.1.0 release)  
**Maintainer:** Knowledge Graphs Team
