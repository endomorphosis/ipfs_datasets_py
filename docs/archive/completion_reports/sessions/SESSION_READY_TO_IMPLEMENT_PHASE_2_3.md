# Phase 2 & 3 Implementation - Ready to Code

**Date:** 2026-02-15  
**Status:** Planning Complete → Implementation Starting  
**Branch:** copilot/update-implementation-plan-docs

---

## Session Summary

This session prepared for Phase 2 & 3 implementation by:
1. Reviewing comprehensive plan in `PHASE_2_3_IMPLEMENTATION_PLAN.md`
2. Examining current code structure
3. Identifying implementation targets
4. Storing memory for future sessions

**Status:** Ready to begin coding in next session

---

## Next Session: Implementation Tasks

### Task 2.1: Multi-Database Support (16 hours)

**Goal:** Enable multiple named databases within single IPFS Graph Database instance, matching Neo4j's multi-database capability.

**Files to Modify:**

1. **`ipfs_datasets_py/knowledge_graphs/neo4j_compat/driver.py`**
   - Add `database` parameter to `session()` method
   - Pass database name to session
   - Track databases in driver state

2. **`ipfs_datasets_py/knowledge_graphs/neo4j_compat/session.py`**
   - Already has `database` parameter in `__init__` (line 139)
   - Currently defaults to "default"
   - Enhance to use database-specific backend

3. **`ipfs_datasets_py/knowledge_graphs/storage/ipld_backend.py`**
   - Add database namespace support
   - Prefix CIDs with database identifier
   - Isolate database storage

**Implementation Strategy:**

```python
# driver.py - session() method enhancement
def session(
    self,
    database: Optional[str] = None,
    default_access_mode: str = "WRITE",
    bookmarks: Optional[Union[str, List[str], Bookmarks]] = None,
    **kwargs
) -> IPFSSession:
    """
    Create a new session for specified database.
    
    Args:
        database: Database name (default: "neo4j")
        default_access_mode: "READ" or "WRITE"
        bookmarks: Initial bookmarks for causal consistency
        **kwargs: Additional session configuration
        
    Returns:
        IPFSSession instance
    """
    database = database or "neo4j"  # Neo4j default
    
    # Get or create database-specific backend
    backend = self._get_database_backend(database)
    
    return IPFSSession(
        driver=self,
        backend=backend,
        database=database,
        default_access_mode=default_access_mode,
        bookmarks=bookmarks
    )
```

**Storage Backend Enhancement:**

```python
# ipld_backend.py - add namespace support
class IPLDBackend:
    def __init__(self, deps, database="default", ...):
        self.database = database
        self._namespace = f"kg:db:{database}:"  # Prefix for all CIDs
    
    def _make_key(self, key: str) -> str:
        """Add database namespace to key."""
        return f"{self._namespace}{key}"
```

**Tests to Create:**

File: `tests/unit/knowledge_graphs/test_multi_database.py`

```python
import pytest
from ipfs_datasets_py.knowledge_graphs.neo4j_compat import GraphDatabase

def test_default_database():
    """Test default database is 'neo4j'."""
    driver = GraphDatabase.driver("ipfs+embedded://")
    session = driver.session()
    assert session._database == "neo4j"
    
def test_specify_database():
    """Test specifying database name."""
    driver = GraphDatabase.driver("ipfs+embedded://")
    session = driver.session(database="mydb")
    assert session._database == "mydb"

def test_database_isolation():
    """Test that databases are isolated."""
    driver = GraphDatabase.driver("ipfs+embedded://")
    
    # Create node in database1
    session1 = driver.session(database="db1")
    session1.run("CREATE (n:Person {name: 'Alice'})")
    
    # Query from database2
    session2 = driver.session(database="db2")
    result = session2.run("MATCH (n:Person) RETURN count(n) as c")
    count = result.single()["c"]
    
    # Should be 0 - isolated
    assert count == 0
    
def test_multiple_sessions_same_database():
    """Test multiple sessions can access same database."""
    driver = GraphDatabase.driver("ipfs+embedded://")
    
    # Session 1 creates
    session1 = driver.session(database="shared")
    session1.run("CREATE (n:Person {name: 'Bob'})")
    
    # Session 2 reads
    session2 = driver.session(database="shared")
    result = session2.run("MATCH (n:Person) RETURN count(n) as c")
    count = result.single()["c"]
    
    # Should see the node
    assert count == 1

# 10+ more tests...
```

---

### Task 2.3: Essential Cypher Extensions (20 hours)

**Goal:** Add essential math, spatial, and temporal functions for Neo4j compatibility.

**Part 1: Math Functions (8 hours)**

File: `ipfs_datasets_py/knowledge_graphs/cypher/functions.py`

Create new functions module with:

```python
"""
Cypher Function Library

Provides built-in functions for Cypher queries, including:
- Mathematical functions (abs, ceil, floor, round, sqrt, sign, rand)
- String functions (existing: toLower, toUpper, substring, trim, etc.)
- Spatial functions (point, distance)
- Temporal functions (date, datetime, timestamp)
- Aggregation functions (handled separately in query_executor)
"""

import math
import random
from typing import Any, Dict, Optional, Union
from datetime import datetime, date

# Math Functions
def abs_func(n: Union[int, float]) -> Union[int, float]:
    """Return absolute value of number."""
    if n is None:
        return None
    return abs(n)

def ceil_func(n: Union[int, float]) -> int:
    """Return smallest integer >= n."""
    if n is None:
        return None
    return math.ceil(n)

def floor_func(n: Union[int, float]) -> int:
    """Return largest integer <= n."""
    if n is None:
        return None
    return math.floor(n)

def round_func(n: Union[int, float], precision: int = 0) -> Union[int, float]:
    """Round number to given precision."""
    if n is None:
        return None
    return round(n, precision)

def sqrt_func(n: Union[int, float]) -> float:
    """Return square root of number."""
    if n is None:
        return None
    if n < 0:
        return float('nan')
    return math.sqrt(n)

def sign_func(n: Union[int, float]) -> int:
    """Return sign of number (-1, 0, or 1)."""
    if n is None:
        return None
    if n > 0:
        return 1
    elif n < 0:
        return -1
    else:
        return 0

def rand_func() -> float:
    """Return random float between 0.0 and 1.0."""
    return random.random()

# Function registry
BUILTIN_FUNCTIONS = {
    # Math functions
    'abs': abs_func,
    'ceil': ceil_func,
    'floor': floor_func,
    'round': round_func,
    'sqrt': sqrt_func,
    'sign': sign_func,
    'rand': rand_func,
    
    # String functions (to be added - exist in query_executor)
    # 'toLower', 'toUpper', 'substring', 'trim', etc.
    
    # Spatial functions (Part 2)
    # 'point', 'distance'
    
    # Temporal functions (Part 2)
    # 'date', 'datetime', 'timestamp'
}
```

**Integration with Query Executor:**

File: `ipfs_datasets_py/knowledge_graphs/core/query_executor.py`

Add function evaluation using the registry:

```python
from ..cypher.functions import BUILTIN_FUNCTIONS

def _evaluate_function(self, func_name: str, args: List[Any]) -> Any:
    """Evaluate a built-in function."""
    if func_name in BUILTIN_FUNCTIONS:
        return BUILTIN_FUNCTIONS[func_name](*args)
    
    # Fall back to existing string function handling
    # ...
```

**Tests:**

File: `tests/unit/knowledge_graphs/test_math_functions.py`

```python
import pytest
from ipfs_datasets_py.knowledge_graphs.neo4j_compat import GraphDatabase

def test_abs_function():
    """Test abs() function."""
    driver = GraphDatabase.driver("ipfs+embedded://")
    session = driver.session()
    
    result = session.run("RETURN abs(-5) as val")
    assert result.single()["val"] == 5
    
    result = session.run("RETURN abs(3.14) as val")
    assert result.single()["val"] == 3.14

def test_ceil_function():
    """Test ceil() function."""
    driver = GraphDatabase.driver("ipfs+embedded://")
    session = driver.session()
    
    result = session.run("RETURN ceil(3.2) as val")
    assert result.single()["val"] == 4
    
    result = session.run("RETURN ceil(-2.8) as val")
    assert result.single()["val"] == -2

def test_floor_function():
    """Test floor() function."""
    driver = GraphDatabase.driver("ipfs+embedded://")
    session = driver.session()
    
    result = session.run("RETURN floor(3.8) as val")
    assert result.single()["val"] == 3

def test_round_function():
    """Test round() function."""
    driver = GraphDatabase.driver("ipfs+embedded://")
    session = driver.session()
    
    result = session.run("RETURN round(3.14159, 2) as val")
    assert result.single()["val"] == 3.14

def test_sqrt_function():
    """Test sqrt() function."""
    driver = GraphDatabase.driver("ipfs+embedded://")
    session = driver.session()
    
    result = session.run("RETURN sqrt(16) as val")
    assert result.single()["val"] == 4.0
    
    result = session.run("RETURN sqrt(2) as val")
    assert abs(result.single()["val"] - 1.414) < 0.001

def test_sign_function():
    """Test sign() function."""
    driver = GraphDatabase.driver("ipfs+embedded://")
    session = driver.session()
    
    result = session.run("RETURN sign(5) as val")
    assert result.single()["val"] == 1
    
    result = session.run("RETURN sign(-3) as val")
    assert result.single()["val"] == -1
    
    result = session.run("RETURN sign(0) as val")
    assert result.single()["val"] == 0

def test_rand_function():
    """Test rand() function."""
    driver = GraphDatabase.driver("ipfs+embedded://")
    session = driver.session()
    
    result = session.run("RETURN rand() as val")
    val = result.single()["val"]
    assert 0.0 <= val <= 1.0

def test_math_functions_with_null():
    """Test math functions handle NULL."""
    driver = GraphDatabase.driver("ipfs+embedded://")
    session = driver.session()
    
    result = session.run("RETURN abs(null) as val")
    assert result.single()["val"] is None

# 15+ more tests...
```

---

### Task 3.1: Expand Vocabularies (15 hours)

**Goal:** Add Schema.org, FOAF, Dublin Core, and SKOS vocabularies to existing JSON-LD support.

**Current State:**

File: `ipfs_datasets_py/knowledge_graphs/jsonld/context.py` (existing, ~250 lines)

Already has basic vocabularies:
- RDF/RDFS
- OWL
- Basic Schema.org

**Enhancement Needed:**

```python
# context.py - add to STANDARD_CONTEXTS

# Schema.org (extended)
SCHEMA_ORG_EXTENDED = {
    "@context": {
        "@vocab": "http://schema.org/",
        # Organization types
        "Organization": "Organization",
        "Corporation": "Corporation",
        "GovernmentOrganization": "GovernmentOrganization",
        "NGO": "NGO",
        
        # Place types
        "Place": "Place",
        "City": "City",
        "Country": "Country",
        "PostalAddress": "PostalAddress",
        
        # Event types
        "Event": "Event",
        "SocialEvent": "SocialEvent",
        "BusinessEvent": "BusinessEvent",
        
        # Properties
        "address": "address",
        "location": "location",
        "foundingDate": {"@id": "foundingDate", "@type": "Date"},
        "startDate": {"@id": "startDate", "@type": "DateTime"},
        "endDate": {"@id": "endDate", "@type": "DateTime"},
        # ... 50+ more properties
    }
}

# FOAF (Friend of a Friend)
FOAF_CONTEXT = {
    "@context": {
        "foaf": "http://xmlns.com/foaf/0.1/",
        
        # Classes
        "Person": "foaf:Person",
        "Agent": "foaf:Agent",
        "Document": "foaf:Document",
        "Image": "foaf:Image",
        "OnlineAccount": "foaf:OnlineAccount",
        
        # Properties
        "knows": {"@id": "foaf:knows", "@type": "@id"},
        "friend": {"@id": "foaf:friend", "@type": "@id"},
        "mbox": {"@id": "foaf:mbox", "@type": "@id"},
        "homepage": {"@id": "foaf:homepage", "@type": "@id"},
        "givenName": "foaf:givenName",
        "familyName": "foaf:familyName",
        "nickname": "foaf:nickname",
        "age": {"@id": "foaf:age", "@type": "xsd:int"},
        # ... 30+ more properties
    }
}

# Dublin Core Terms
DUBLIN_CORE_CONTEXT = {
    "@context": {
        "dc": "http://purl.org/dc/terms/",
        
        # Properties
        "title": "dc:title",
        "creator": "dc:creator",
        "subject": "dc:subject",
        "description": "dc:description",
        "publisher": "dc:publisher",
        "contributor": "dc:contributor",
        "date": {"@id": "dc:date", "@type": "xsd:date"},
        "type": "dc:type",
        "format": "dc:format",
        "identifier": "dc:identifier",
        "source": "dc:source",
        "language": "dc:language",
        "relation": "dc:relation",
        "coverage": "dc:coverage",
        "rights": "dc:rights",
        # ... 15+ more
    }
}

# SKOS (Simple Knowledge Organization System)
SKOS_CONTEXT = {
    "@context": {
        "skos": "http://www.w3.org/2004/02/skos/core#",
        
        # Classes
        "Concept": "skos:Concept",
        "ConceptScheme": "skos:ConceptScheme",
        "Collection": "skos:Collection",
        
        # Properties
        "prefLabel": "skos:prefLabel",
        "altLabel": "skos:altLabel",
        "hiddenLabel": "skos:hiddenLabel",
        "broader": {"@id": "skos:broader", "@type": "@id"},
        "narrower": {"@id": "skos:narrower", "@type": "@id"},
        "related": {"@id": "skos:related", "@type": "@id"},
        "inScheme": {"@id": "skos:inScheme", "@type": "@id"},
        "hasTopConcept": {"@id": "skos:hasTopConcept", "@type": "@id"},
        "notation": "skos:notation",
        "definition": "skos:definition",
        "example": "skos:example",
        "note": "skos:note",
        # ... 20+ more
    }
}
```

**Tests:**

File: `tests/unit/knowledge_graphs/test_vocabularies.py`

```python
import pytest
from ipfs_datasets_py.knowledge_graphs.jsonld import (
    JSONLDContext,
    SCHEMA_ORG_EXTENDED,
    FOAF_CONTEXT,
    DUBLIN_CORE_CONTEXT,
    SKOS_CONTEXT
)

def test_schema_org_extended():
    """Test Schema.org extended vocabulary."""
    context = JSONLDContext(SCHEMA_ORG_EXTENDED)
    
    # Test organization types
    assert "Organization" in context.get_terms()
    assert "Corporation" in context.get_terms()
    
    # Test properties
    assert context.expand_term("address") == "http://schema.org/address"

def test_foaf_vocabulary():
    """Test FOAF vocabulary."""
    context = JSONLDContext(FOAF_CONTEXT)
    
    # Test classes
    assert context.expand_term("Person") == "http://xmlns.com/foaf/0.1/Person"
    
    # Test properties
    assert context.expand_term("knows") == "http://xmlns.com/foaf/0.1/knows"
    assert context.expand_term("givenName") == "http://xmlns.com/foaf/0.1/givenName"

def test_dublin_core():
    """Test Dublin Core vocabulary."""
    context = JSONLDContext(DUBLIN_CORE_CONTEXT)
    
    assert context.expand_term("title") == "http://purl.org/dc/terms/title"
    assert context.expand_term("creator") == "http://purl.org/dc/terms/creator"

def test_skos_vocabulary():
    """Test SKOS vocabulary."""
    context = JSONLDContext(SKOS_CONTEXT)
    
    assert context.expand_term("Concept") == "http://www.w3.org/2004/02/skos/core#Concept"
    assert context.expand_term("prefLabel") == "http://www.w3.org/2004/02/skos/core#prefLabel"

# 10+ more tests...
```

---

## Summary: Next Session TODO

### High Priority (Start Immediately)

1. **Task 2.1: Multi-Database Support**
   - Modify `driver.py` session() method
   - Enhance `ipld_backend.py` with namespace support
   - Create `test_multi_database.py` with 15+ tests
   - **Time:** 4-6 hours

2. **Task 2.3 Part 1: Math Functions**
   - Create `cypher/functions.py` module
   - Integrate with `query_executor.py`
   - Create `test_math_functions.py` with 15+ tests
   - **Time:** 3-4 hours

### Medium Priority (Second Half)

3. **Task 3.1: Expand Vocabularies**
   - Extend `jsonld/context.py` with 4 vocabularies
   - Add ~200 new terms across vocabularies
   - Create `test_vocabularies.py` with 10+ tests
   - **Time:** 3-4 hours

### Total Session Estimate: 10-14 hours

---

## Success Metrics

**Code Changes:**
- 3-4 files modified (driver, backend, query_executor, context)
- 1 new file (functions.py)
- 3 new test files
- ~800 lines new code (400 production + 400 test)

**Test Coverage:**
- 40+ new tests
- All 210 Phase 1 tests still passing
- Total: 250+ tests

**Feature Progress:**
- Task 2.1: 60% → 100% complete
- Task 2.3: 0% → 35% complete (math functions done)
- Task 3.1: 0% → 70% complete (vocabularies done, SHACL pending)

**Neo4j API Parity:**
- Current: 94%
- After: 96%

---

## Notes for Implementation

1. **Test-Driven Development:** Write tests first, then implementation
2. **Incremental Commits:** Commit after each task completion
3. **Backward Compatibility:** All Phase 1 tests must continue passing
4. **Documentation:** Update docstrings as you add features
5. **Error Handling:** Match Neo4j error messages where possible

---

**Status:** Documentation complete, ready for implementation! 🚀
