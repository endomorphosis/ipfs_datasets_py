# Knowledge Graphs - Phase 2 & 3 Implementation Plan

**Date:** 2026-02-15  
**Status:** Phase 1 COMPLETE → Phase 2 & 3 In Progress  
**Branch:** copilot/update-implementation-plan-docs  
**Strategy:** Pragmatic parallel completion

---

## 🎯 Executive Summary

With Phase 1 complete (210/210 tests, 87% Cypher compatibility), we're implementing a **pragmatic approach** to complete critical Phase 2 features while establishing Phase 3 foundations. This strategy prioritizes user needs (Neo4j migration) and technical completeness (semantic web) over exhaustive feature coverage.

### Key Decisions

1. **Complete Phase 2 Critical Path:** Multi-database support + essential Cypher extensions
2. **Defer Phase 2 Optimizations:** IPLD-Bolt protocol and APOC procedures (future work)
3. **Start Phase 3 Foundations:** Vocabularies, SHACL, and RDF serialization
4. **Target:** 96% Neo4j API parity, robust semantic web support

---

## 📊 Current Status

### Phase 1: 100% COMPLETE ✅
- 210/210 tests passing
- 87% Cypher compatibility
- Production-ready graph database
- All core features operational

### Phase 2: 22% COMPLETE (50/250 hours)
| Task | Status | Hours | Priority |
|------|--------|-------|----------|
| 2.1 Driver API | 60% | 24/40 | ✅ Critical |
| 2.2 IPLD-Bolt | 0% | 0/60 | ⏸️ Deferred |
| 2.3 Cypher Extensions | 0% | 0/40 | ✅ Critical |
| 2.4 APOC Procedures | 0% | 0/80 | ⏸️ Deferred |
| 2.5 Migration Tools | 100% | 30/30 | ✅ DONE |

**Completed in Phase 2:**
- Connection pooling (thread-safe, configurable)
- Bookmarks (causal consistency)
- Neo4j export/import tools
- Schema compatibility checker
- Data integrity verifier

**Remaining Critical:**
- Multi-database support
- Advanced driver configuration
- Spatial functions (point, distance)
- Temporal functions (date, datetime)
- Math functions (abs, round, sqrt, etc.)

### Phase 3: 40% COMPLETE (~30/80 hours est.)
**Existing Implementation:**
- JSON-LD context management (context.py)
- Type definitions (types.py)
- Translator (translator.py)
- Basic validation (validation.py)
- ~1,200 lines of JSON-LD code

**Remaining:**
- Expanded vocabularies (4+ more)
- Complete SHACL validation
- RDF serialization formats

---

## 🚀 Implementation Plan

### Part 1: Complete Phase 2 Critical Items (36 hours)

#### Task 2.1 Completion: Multi-Database Support (16 hours)

**Goal:** Enable multiple named databases within single instance

**Implementation:**
```python
# driver.py
class IPFSDriver:
    def session(self, database="neo4j", **kwargs):
        """Create session for specific database"""
        return IPFSSession(
            backend=self.backend,
            database=database,
            bookmarks=kwargs.get('bookmarks'),
            default_access_mode=kwargs.get('default_access_mode', 'WRITE')
        )

# session.py
class IPFSSession:
    def __init__(self, backend, database="neo4j", ...):
        self.database = database
        self.backend = backend.get_database(database)
```

**Features:**
- [ ] Database namespace isolation
- [ ] Database creation/deletion
- [ ] Database-specific query routing
- [ ] Cross-database queries (future)
- [ ] Database listing and metadata

**Advanced Configuration:**
- [ ] Trust settings (certificates)
- [ ] Encrypted connections
- [ ] Custom user agent
- [ ] Connection keepalive tuning
- [ ] Timeout configuration

**Tests:** 15+ tests
- Database creation and selection
- Query isolation between databases
- Configuration options
- Error handling

**Files:**
- `ipfs_datasets_py/knowledge_graphs/neo4j_compat/driver.py`
- `ipfs_datasets_py/knowledge_graphs/neo4j_compat/session.py`
- `ipfs_datasets_py/knowledge_graphs/storage/backend.py`
- `tests/unit/knowledge_graphs/test_multi_database.py`

---

#### Task 2.3: Essential Cypher Extensions (20 hours)

**Goal:** Add most-used Neo4j functions for compatibility

**Spatial Functions (5 hours):**
```python
# Cypher: point({x: 1.0, y: 2.0})
def point(properties: Dict) -> Point:
    if 'x' in properties and 'y' in properties:
        return CartesianPoint(properties['x'], properties['y'])
    elif 'latitude' in properties and 'longitude' in properties:
        return GeographicPoint(properties['latitude'], properties['longitude'])

# Cypher: distance(point1, point2)
def distance(p1: Point, p2: Point) -> float:
    # Haversine for geographic, Euclidean for cartesian
```

**Functions:**
- [ ] `point({x, y})` - Cartesian point
- [ ] `point({latitude, longitude})` - Geographic point  
- [ ] `distance(point1, point2)` - Calculate distance

**Temporal Functions (5 hours):**
```python
# Cypher: date(), datetime()
from datetime import date, datetime

def cypher_date(value=None) -> date:
    if value is None:
        return date.today()
    return date.fromisoformat(value)

def cypher_datetime(value=None) -> datetime:
    if value is None:
        return datetime.now()
    return datetime.fromisoformat(value)
```

**Functions:**
- [ ] `date()` - Current date
- [ ] `date(string)` - Parse date
- [ ] `datetime()` - Current datetime
- [ ] `datetime(string)` - Parse datetime
- [ ] `timestamp()` - Unix timestamp

**Math Functions (5 hours):**
```python
import math
import random

MATH_FUNCTIONS = {
    'abs': abs,
    'ceil': math.ceil,
    'floor': math.floor,
    'round': round,
    'sqrt': math.sqrt,
    'sign': lambda x: 1 if x > 0 else (-1 if x < 0 else 0),
    'rand': random.random,
}
```

**Functions:**
- [ ] `abs(n)` - Absolute value
- [ ] `ceil(n)` - Ceiling
- [ ] `floor(n)` - Floor
- [ ] `round(n)` - Round
- [ ] `sqrt(n)` - Square root
- [ ] `sign(n)` - Sign (-1, 0, 1)
- [ ] `rand()` - Random [0, 1)

**Implementation Steps:**
1. Create `Point` class with Cartesian and Geographic variants
2. Add spatial functions to cypher function registry
3. Add temporal functions using Python datetime
4. Add math functions using Python math module
5. Update parser to recognize new functions
6. Update compiler to handle new function calls
7. Update query executor to evaluate functions

**Tests:** 25+ tests
- Spatial: point creation, distance calculation
- Temporal: date/datetime parsing and current values
- Math: all 7 functions with edge cases

**Files:**
- `ipfs_datasets_py/knowledge_graphs/cypher/functions.py` (expand)
- `ipfs_datasets_py/knowledge_graphs/cypher/types.py` (add Point)
- `ipfs_datasets_py/knowledge_graphs/core/query_executor.py` (add evaluation)
- `tests/unit/knowledge_graphs/test_spatial_functions.py` (new)
- `tests/unit/knowledge_graphs/test_temporal_functions.py` (new)
- `tests/unit/knowledge_graphs/test_math_functions.py` (new)

---

### Part 2: Phase 3 Foundations (43 hours)

#### Task 3.1: Expand Vocabularies (15 hours)

**Goal:** Support major semantic web vocabularies

**Current Vocabularies (5):**
- Schema.org (basic)
- Dublin Core (basic)
- FOAF (basic)
- SKOS (basic)
- OWL (basic)

**Add Vocabularies:**

1. **Schema.org (extended)** - 3 hours
   - Person, Organization, Place
   - Product, Offer, Review
   - Article, CreativeWork
   - Event, Action

2. **FOAF (extended)** - 2 hours
   - Person, Agent, Organization
   - knows, member, homepage
   - name, mbox, depiction

3. **Dublin Core Terms** - 2 hours
   - creator, contributor, publisher
   - title, description, subject
   - date, type, format

4. **SKOS (extended)** - 3 hours
   - Concept, ConceptScheme
   - broader, narrower, related
   - prefLabel, altLabel, definition

**Implementation:**
```python
# context.py
VOCABULARIES = {
    'schema': {
        'Person': 'http://schema.org/Person',
        'name': 'http://schema.org/name',
        'email': 'http://schema.org/email',
        # ... 100+ terms
    },
    'foaf': {
        'Person': 'http://xmlns.com/foaf/0.1/Person',
        'knows': 'http://xmlns.com/foaf/0.1/knows',
        # ... 50+ terms
    },
    # ...
}
```

**Tests:** 10+ tests
- Vocabulary loading
- Context expansion
- Term resolution
- Namespace handling

**Files:**
- `ipfs_datasets_py/knowledge_graphs/jsonld/context.py` (expand)
- `ipfs_datasets_py/knowledge_graphs/jsonld/vocabularies/` (new directory)
  - `schema_org.py`
  - `foaf.py`
  - `dublin_core.py`
  - `skos.py`
- `tests/unit/knowledge_graphs/test_vocabularies.py` (new)

---

#### Task 3.2: Core SHACL Validation (20 hours)

**Goal:** Validate RDF data against shape constraints

**SHACL Basics:**
```turtle
:PersonShape a sh:NodeShape ;
    sh:targetClass schema:Person ;
    sh:property [
        sh:path schema:name ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:datatype xsd:string ;
    ] .
```

**Core Constraints (Implementation):**

1. **Cardinality** - 3 hours
   - `sh:minCount` - Minimum occurrences
   - `sh:maxCount` - Maximum occurrences

2. **Value Type** - 4 hours
   - `sh:datatype` - XSD datatype
   - `sh:class` - RDF class
   - `sh:nodeKind` - IRI, Literal, BlankNode

3. **Value Range** - 4 hours
   - `sh:minInclusive` - Minimum value
   - `sh:maxInclusive` - Maximum value
   - `sh:minExclusive` - Minimum (exclusive)
   - `sh:maxExclusive` - Maximum (exclusive)

4. **String Constraints** - 3 hours
   - `sh:minLength` - Minimum string length
   - `sh:maxLength` - Maximum string length
   - `sh:pattern` - Regex pattern
   - `sh:languageIn` - Language tags

5. **Property Pairs** - 3 hours
   - `sh:equals` - Values must be equal
   - `sh:disjoint` - Values must differ
   - `sh:lessThan` - Value ordering

6. **Validation Report** - 3 hours
   - Collect violations
   - Severity levels (Violation, Warning, Info)
   - Focus nodes and paths
   - Human-readable messages

**Implementation:**
```python
class SHACLValidator:
    def validate(self, data_graph, shapes_graph):
        """Validate RDF data against SHACL shapes"""
        violations = []
        
        for shape in shapes_graph.shapes:
            target_nodes = self._get_target_nodes(shape, data_graph)
            
            for node in target_nodes:
                for constraint in shape.constraints:
                    if not self._check_constraint(node, constraint):
                        violations.append(Violation(
                            severity=constraint.severity,
                            source_shape=shape,
                            focus_node=node,
                            message=constraint.message
                        ))
        
        return ValidationReport(violations)
```

**Tests:** 20+ tests
- Each constraint type
- Combination of constraints
- Violation reporting
- Edge cases

**Files:**
- `ipfs_datasets_py/knowledge_graphs/jsonld/shacl_validator.py` (new)
- `ipfs_datasets_py/knowledge_graphs/jsonld/shacl_shapes.py` (new)
- `tests/unit/knowledge_graphs/test_shacl_validation.py` (new)

---

#### Task 3.3: Turtle RDF Serialization (8 hours)

**Goal:** Export graph data as Turtle RDF

**Turtle Format Example:**
```turtle
@prefix schema: <http://schema.org/> .
@prefix foaf: <http://xmlns.com/foaf/0.1/> .

<http://example.org/alice>
    a schema:Person ;
    schema:name "Alice Smith" ;
    schema:email "alice@example.com" ;
    foaf:knows <http://example.org/bob> .
```

**Implementation:**

1. **Prefix Management** - 2 hours
   - Common prefix registry
   - Prefix compression
   - Namespace handling

2. **Triple Generation** - 3 hours
   - Convert nodes to subjects
   - Convert properties to predicates
   - Convert values to objects
   - Handle literals and IRIs

3. **Pretty Printing** - 2 hours
   - Grouped by subject
   - Property lists with semicolons
   - Object lists with commas
   - Multi-line strings

4. **Round-Trip Validation** - 1 hour
   - Parse generated Turtle
   - Verify data integrity

**Implementation:**
```python
class TurtleSerializer:
    def serialize(self, graph):
        """Convert graph to Turtle format"""
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
        
        return "\n".join(output)
```

**Tests:** 10+ tests
- Basic serialization
- Prefix compression
- Literal types (string, number, boolean)
- Multiple objects per predicate
- Round-trip parsing

**Files:**
- `ipfs_datasets_py/knowledge_graphs/jsonld/rdf_serializer.py` (new)
- `ipfs_datasets_py/knowledge_graphs/jsonld/turtle_writer.py` (new)
- `tests/unit/knowledge_graphs/test_rdf_serialization.py` (new)

---

## 📈 Success Criteria

### Phase 2 Completion (Partial)
- [ ] Multi-database support fully functional
- [ ] 15+ new Cypher functions working
- [ ] Neo4j API parity: 90% → 96% (+6%)
- [ ] All 210 Phase 1 tests still pass
- [ ] 40+ new Phase 2 tests pass
- [ ] Migration guide updated

### Phase 3 Foundation
- [ ] 9+ vocabularies supported (from 5)
- [ ] Core SHACL validation operational
- [ ] Turtle RDF export working
- [ ] Round-trip validation passing
- [ ] 40+ new Phase 3 tests pass
- [ ] Semantic web examples documented

### Combined Metrics
- [ ] 290+ total tests passing (210 + 80 new)
- [ ] Zero test regressions
- [ ] Production-ready for both Neo4j migration and semantic web
- [ ] Clear documentation for all new features

---

## 📅 Timeline

### Session 1 (Current) - 12 hours
- [ ] Task 2.1: Multi-database support (8 hours)
- [ ] Task 2.3 Part 1: Math functions (4 hours)

### Session 2 - 15 hours
- [ ] Task 2.3 Part 2: Spatial functions (5 hours)
- [ ] Task 2.3 Part 3: Temporal functions (5 hours)
- [ ] Task 3.1 Part 1: Vocabulary expansion start (5 hours)

### Session 3 - 15 hours
- [ ] Task 3.1 Part 2: Complete vocabularies (10 hours)
- [ ] Task 3.2 Part 1: SHACL basics (5 hours)

### Session 4 - 15 hours
- [ ] Task 3.2 Part 2: Complete SHACL (10 hours)
- [ ] Task 3.3: Turtle serialization (5 hours)

### Session 5 - 5 hours
- [ ] Final testing and integration
- [ ] Documentation updates
- [ ] Summary report

**Total:** ~62 hours over 5 sessions

---

## 🎯 Deferred Items

### Phase 2 Deferred (Future Work)
**Task 2.2: IPLD-Bolt Protocol (60 hours)**
- Binary protocol for efficiency
- 2-3x performance improvement
- Lower priority: optimization not blocker

**Task 2.4: APOC Procedures (80 hours)**
- Enterprise features
- Graph algorithms
- Lower priority: niche use cases

### Phase 3 Deferred (Future Work)
**Advanced SHACL:**
- Logical constraints (and, or, not, xone)
- Property paths
- SPARQL-based constraints

**Additional RDF Formats:**
- N-Triples
- RDF/XML
- JSON-LD serialization

**Reasoning:**
- OWL reasoning
- RDFS inference
- Rule-based reasoning

---

## 📚 Documentation Updates

### New Documentation Needed
- [ ] Multi-database usage guide
- [ ] Cypher functions reference
- [ ] Spatial queries examples
- [ ] Temporal queries examples
- [ ] SHACL validation guide
- [ ] RDF serialization guide
- [ ] Vocabulary selection guide

### Updated Documentation
- [ ] KNOWLEDGE_GRAPHS_CURRENT_STATUS.md
- [ ] KNOWLEDGE_GRAPHS_NEO4J_API_MIGRATION.md
- [ ] MIGRATION_TOOLS_USER_GUIDE.md

---

## 🔗 Related Documents

- [Phase 1 Complete](./KNOWLEDGE_GRAPHS_PHASE_1_COMPLETE.md)
- [Current Status](./KNOWLEDGE_GRAPHS_CURRENT_STATUS.md)
- [Next Steps (Original)](./KNOWLEDGE_GRAPHS_NEXT_STEPS.md)
- [Migration Tools Guide](./MIGRATION_TOOLS_USER_GUIDE.md)
- [Refactoring Plan](./KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md)

---

## 📝 Notes

### Why This Approach?

1. **User Value First:** Neo4j compatibility (multi-database + functions) enables migration
2. **Technical Completeness:** Semantic web support (vocabularies + SHACL + RDF) future-proofs
3. **Pragmatic Scope:** Defer optimizations (Bolt) and niche features (APOC) to future
4. **Parallel Progress:** Work on Phase 2 and 3 simultaneously for faster overall completion

### Future Considerations

- IPLD-Bolt Protocol when performance becomes critical
- APOC procedures based on user demand
- Advanced SHACL when validation needs grow
- Additional RDF formats as needed
- Reasoning engines if semantic inference required

---

**Status:** Ready to implement  
**Next Action:** Begin Task 2.1 (Multi-database support)
