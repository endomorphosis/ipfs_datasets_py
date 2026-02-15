# Phase 2 Critical Items - Implementation Preparation

**Date:** 2026-02-15  
**Status:** Planning Complete → Ready to Implement  
**Branch:** copilot/update-implementation-plan-docs  
**Session Type:** Preparation and Analysis

---

## Session Summary

This session prepared for implementing Phase 2 critical items by:
1. Reviewing comprehensive implementation plans
2. Analyzing current code structure (driver, session, backend)
3. Identifying exact modifications needed
4. Creating detailed implementation guide
5. Storing memory for next session continuity

**Outcome:** Complete implementation roadmap ready for coding

---

## Objectives for Next Session

### Part 1: Multi-Database Support (Task 2.1 Completion)
**Goal:** Enable multiple named databases within single IPFS Graph Database instance

**Status:** 60% → 100%
- Current: Driver and session accept database parameter (unused)
- Need: Database namespace isolation in storage backend

**Time Estimate:** 6 hours

### Part 2: Essential Cypher Extensions (Task 2.3 Partial)
**Goal:** Add 15 essential Cypher functions for Neo4j compatibility

**Status:** 0% → 35%
- Math: abs, ceil, floor, round, sqrt, sign, rand
- Spatial: point, distance
- Temporal: date, datetime, timestamp

**Time Estimate:** 6 hours

**Total Session:** 10-12 hours

---

## Implementation Details

### Multi-Database Support

#### Current State Analysis

**driver.py (Lines 155-192):**
```python
def session(
    self,
    database: Optional[str] = None,  # ✅ Already accepts parameter
    default_access_mode: str = "WRITE",
    bookmarks: Optional[Any] = None,
    **config
) -> IPFSSession:
    return IPFSSession(
        driver=self,
        database=database,  # ✅ Passes to session
        default_access_mode=default_access_mode,
        bookmarks=bookmarks
    )
```

**session.py (Lines 136-150):**
```python
class IPFSSession:
    def __init__(
        self,
        driver: 'IPFSDriver',
        database: Optional[str] = None,  # ✅ Already accepts parameter
        default_access_mode: str = "WRITE",
        bookmarks: Optional[Union[str, List[str], Bookmarks]] = None
    ):
        # Currently not using database parameter
        # Uses driver.backend directly (single shared backend)
```

**ipld_backend.py (Lines 114-141):**
```python
class IPLDBackend:
    def __init__(
        self,
        deps: Optional['RouterDeps'] = None,
        pin_by_default: bool = True,
        cache_capacity: int = 1000
    ):
        # ❌ NO database parameter
        # ❌ NO namespace support
        # All data shares same storage namespace
```

#### Changes Required

**1. IPLDBackend - Add Database Namespace (ipld_backend.py)**

Location: Class `__init__` method (line 114)

```python
class IPLDBackend:
    def __init__(
        self,
        deps: Optional['RouterDeps'] = None,
        database: str = "neo4j",  # NEW: database name
        pin_by_default: bool = True,
        cache_capacity: int = 1000
    ):
        if not HAVE_ROUTER:
            raise ImportError(...)
        
        self.deps = deps if deps is not None else RouterDeps()
        self.database = database  # NEW: store database name
        self._namespace = f"kg:db:{database}:"  # NEW: namespace prefix
        self.pin_by_default = pin_by_default
        self._backend = None
        self._cache = LRUCache(cache_capacity) if cache_capacity > 0 else None
        
        logger.debug("IPLDBackend initialized (database=%s, deps=%s, cache=%s)", 
                    database, self.deps, cache_capacity if self._cache else "disabled")
    
    def _make_key(self, key: str) -> str:
        """
        Add database namespace to key.
        
        This ensures different databases have isolated storage.
        Example: "node:123" -> "kg:db:neo4j:node:123"
        """
        return f"{self._namespace}{key}"
    
    # Then modify store/retrieve methods to use _make_key()
```

**2. Driver - Add Backend Caching (driver.py)**

Location: Class `__init__` method (line 51) and add new method

```python
class IPFSDriver:
    def __init__(self, uri: str, auth: Optional[Tuple[str, str]] = None, ...):
        # ... existing initialization ...
        
        # Initialize RouterDeps and backend
        self.deps = deps if deps is not None else RouterDeps()
        # Remove: self.backend = IPLDBackend(deps=self.deps)
        
        # NEW: Backend cache per database
        self._backend_cache: Dict[str, IPLDBackend] = {}
        
        # Initialize connection pool (existing)
        self._connection_pool = ConnectionPool(...)
        
        self._closed = False
        
        logger.info("IPFSDriver initialized: uri=%s, mode=%s, pool_size=%d", 
                   uri, self._mode, max_connection_pool_size)
    
    def _get_database_backend(self, database: str) -> IPLDBackend:
        """
        Get or create backend for specific database.
        
        Each database gets its own IPLDBackend with isolated namespace.
        Backends are cached to avoid recreation.
        
        Args:
            database: Database name (e.g., "neo4j", "users", "products")
            
        Returns:
            IPLDBackend instance for the database
        """
        if database not in self._backend_cache:
            self._backend_cache[database] = IPLDBackend(
                deps=self.deps,
                database=database,
                pin_by_default=True,
                cache_capacity=1000
            )
            logger.debug("Created backend for database: %s", database)
        
        return self._backend_cache[database]
    
    def session(
        self,
        database: Optional[str] = None,
        default_access_mode: str = "WRITE",
        bookmarks: Optional[Any] = None,
        **config
    ) -> IPFSSession:
        """Create a new session (modified to use database-specific backend)."""
        if self._closed:
            raise RuntimeError("Driver is closed")
        
        # Default to "neo4j" (Neo4j's default database name)
        database = database or "neo4j"
        
        # Get database-specific backend
        backend = self._get_database_backend(database)
        
        return IPFSSession(
            driver=self,
            backend=backend,  # NEW: pass database-specific backend
            database=database,
            default_access_mode=default_access_mode,
            bookmarks=bookmarks
        )
```

**3. Session - Use Provided Backend (session.py)**

Location: Class `__init__` method (line 136)

```python
class IPFSSession:
    def __init__(
        self,
        driver: 'IPFSDriver',
        backend: IPLDBackend,  # NEW: accept backend parameter
        database: Optional[str] = None,
        default_access_mode: str = "WRITE",
        bookmarks: Optional[Union[str, List[str], Bookmarks]] = None
    ):
        """Initialize a session."""
        self._driver = driver
        self.backend = backend  # NEW: use provided backend
        self.database = database or "default"
        self.default_access_mode = default_access_mode
        
        # ... rest of initialization ...
```

#### Database Management Methods (Optional Enhancement)

Add to `IPFSDriver` class:

```python
def list_databases(self) -> List[str]:
    """List all databases (currently created backends)."""
    return list(self._backend_cache.keys())

def create_database(self, name: str) -> None:
    """Create a new database (pre-initialize backend)."""
    if name in self._backend_cache:
        logger.warning("Database already exists: %s", name)
        return
    self._get_database_backend(name)
    logger.info("Database created: %s", name)

def drop_database(self, name: str) -> None:
    """Drop a database (remove backend from cache)."""
    if name in self._backend_cache:
        del self._backend_cache[name]
        logger.info("Database dropped: %s", name)
    else:
        logger.warning("Database not found: %s", name)
```

---

### Cypher Functions

#### Create New File: functions.py

**Path:** `ipfs_datasets_py/knowledge_graphs/cypher/functions.py`

```python
"""
Cypher Built-in Functions

This module implements built-in functions for Cypher queries,
matching Neo4j's function library.

Categories:
- Math functions (abs, ceil, floor, round, sqrt, sign, rand)
- Spatial functions (point, distance)
- Temporal functions (date, datetime, timestamp)

Usage:
    from ipfs_datasets_py.knowledge_graphs.cypher.functions import FUNCTION_REGISTRY
    
    # Get function
    abs_fn = FUNCTION_REGISTRY['abs']
    result = abs_fn(-5)  # Returns 5
"""

import math
import random
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, Optional, Union


class Point:
    """
    Represents a 2D point for spatial operations.
    
    Attributes:
        x: X-coordinate
        y: Y-coordinate
    """
    
    def __init__(self, x: float, y: float):
        """Initialize a point."""
        self.x = float(x)
        self.y = float(y)
    
    def __repr__(self) -> str:
        """String representation."""
        return f"Point(x={self.x}, y={self.y})"
    
    def __eq__(self, other) -> bool:
        """Equality comparison."""
        if not isinstance(other, Point):
            return False
        return self.x == other.x and self.y == other.y


# ============================================================================
# Math Functions
# ============================================================================

def fn_abs(n: Union[int, float]) -> Union[int, float]:
    """Return the absolute value of a number."""
    return abs(n)


def fn_ceil(n: Union[int, float]) -> int:
    """Return the smallest integer >= n."""
    return math.ceil(n)


def fn_floor(n: Union[int, float]) -> int:
    """Return the largest integer <= n."""
    return math.floor(n)


def fn_round(n: Union[int, float]) -> int:
    """Return n rounded to the nearest integer."""
    return round(n)


def fn_sqrt(n: Union[int, float]) -> float:
    """Return the square root of n."""
    if n < 0:
        raise ValueError("Cannot take square root of negative number")
    return math.sqrt(n)


def fn_sign(n: Union[int, float]) -> int:
    """Return the sign of n: 1 if positive, -1 if negative, 0 if zero."""
    if n > 0:
        return 1
    elif n < 0:
        return -1
    else:
        return 0


def fn_rand() -> float:
    """Return a random float in [0, 1)."""
    return random.random()


# ============================================================================
# Spatial Functions
# ============================================================================

def fn_point(params: Dict[str, float]) -> Point:
    """
    Create a 2D point from coordinates.
    
    Args:
        params: Dictionary with 'x' and 'y' keys
        
    Returns:
        Point object
        
    Example:
        point({x: 3.0, y: 4.0})
    """
    if not isinstance(params, dict):
        raise TypeError("point() requires a dictionary parameter")
    
    x = params.get('x', 0.0)
    y = params.get('y', 0.0)
    
    return Point(x, y)


def fn_distance(p1: Point, p2: Point) -> float:
    """
    Calculate Euclidean distance between two points.
    
    Args:
        p1: First point
        p2: Second point
        
    Returns:
        Distance as float
        
    Example:
        distance(point({x: 0, y: 0}), point({x: 3, y: 4})) => 5.0
    """
    if not isinstance(p1, Point) or not isinstance(p2, Point):
        raise TypeError("distance() requires two Point objects")
    
    dx = p2.x - p1.x
    dy = p2.y - p1.y
    
    return math.sqrt(dx * dx + dy * dy)


# ============================================================================
# Temporal Functions
# ============================================================================

def fn_date(s: Optional[str] = None) -> date:
    """
    Return current date or parse from string.
    
    Args:
        s: Optional ISO format date string (YYYY-MM-DD)
        
    Returns:
        date object
        
    Example:
        date() => today's date
        date("2024-01-15") => 2024-01-15
    """
    if s is None:
        return date.today()
    return date.fromisoformat(s)


def fn_datetime(s: Optional[str] = None) -> datetime:
    """
    Return current datetime or parse from string.
    
    Args:
        s: Optional ISO format datetime string
        
    Returns:
        datetime object
        
    Example:
        datetime() => current datetime
        datetime("2024-01-15T10:30:00") => 2024-01-15 10:30:00
    """
    if s is None:
        return datetime.now()
    return datetime.fromisoformat(s)


def fn_timestamp() -> int:
    """
    Return current timestamp in milliseconds since Unix epoch.
    
    Returns:
        Timestamp as integer (milliseconds)
        
    Example:
        timestamp() => 1705315200000
    """
    return int(datetime.now().timestamp() * 1000)


def fn_duration(s: str) -> timedelta:
    """
    Parse duration string to timedelta.
    
    Args:
        s: Duration string (e.g., "P1D", "PT2H", "PT30M")
        
    Returns:
        timedelta object
        
    Example:
        duration("P1D") => 1 day
        duration("PT2H30M") => 2 hours 30 minutes
    """
    # Basic ISO 8601 duration parsing
    # Format: P[nY][nM][nD][T[nH][nM][nS]]
    
    if not s.startswith('P'):
        raise ValueError("Duration string must start with 'P'")
    
    days = 0
    hours = 0
    minutes = 0
    seconds = 0
    
    # Split on 'T' to separate date and time parts
    parts = s[1:].split('T')
    date_part = parts[0]
    time_part = parts[1] if len(parts) > 1 else ''
    
    # Parse date part
    if 'D' in date_part:
        days = int(date_part.split('D')[0])
    
    # Parse time part
    if 'H' in time_part:
        hours = int(time_part.split('H')[0])
        time_part = time_part.split('H')[1]
    
    if 'M' in time_part:
        minutes = int(time_part.split('M')[0])
        time_part = time_part.split('M')[1]
    
    if 'S' in time_part:
        seconds = int(time_part.split('S')[0])
    
    return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)


# ============================================================================
# Function Registry
# ============================================================================

FUNCTION_REGISTRY: Dict[str, Callable] = {
    # Math functions
    'abs': fn_abs,
    'ceil': fn_ceil,
    'floor': fn_floor,
    'round': fn_round,
    'sqrt': fn_sqrt,
    'sign': fn_sign,
    'rand': fn_rand,
    
    # Spatial functions
    'point': fn_point,
    'distance': fn_distance,
    
    # Temporal functions
    'date': fn_date,
    'datetime': fn_datetime,
    'timestamp': fn_timestamp,
    'duration': fn_duration,
}


def get_function(name: str) -> Optional[Callable]:
    """
    Get function by name.
    
    Args:
        name: Function name (case-insensitive)
        
    Returns:
        Function callable or None if not found
    """
    return FUNCTION_REGISTRY.get(name.lower())
```

#### Modify query_executor.py

Location: `_evaluate_compiled_expression` method

```python
# Add import at top
from ..cypher.functions import FUNCTION_REGISTRY

# In _evaluate_compiled_expression method, add function evaluation:
def _evaluate_compiled_expression(self, expr: Any, bindings: Dict[str, Any]) -> Any:
    """Evaluate a compiled expression."""
    
    # ... existing code for property access, literals, etc. ...
    
    # NEW: Function call evaluation
    if isinstance(expr, dict) and 'function' in expr:
        func_name = expr['function'].lower()
        
        if func_name in FUNCTION_REGISTRY:
            # Evaluate arguments
            args = []
            for arg in expr.get('args', []):
                arg_value = self._evaluate_compiled_expression(arg, bindings)
                args.append(arg_value)
            
            # Call function
            func = FUNCTION_REGISTRY[func_name]
            try:
                return func(*args)
            except Exception as e:
                logger.warning("Function %s failed: %s", func_name, e)
                return None
        else:
            logger.warning("Unknown function: %s", func_name)
            return None
    
    # ... rest of existing evaluation code ...
```

---

## Test Files to Create

### test_multi_database.py

**Path:** `tests/unit/knowledge_graphs/test_multi_database.py`

```python
"""
Tests for multi-database support.

Verifies that different databases have isolated storage and
that database management methods work correctly.
"""

import pytest
from ipfs_datasets_py.knowledge_graphs.neo4j_compat import GraphDatabase


def test_database_isolation():
    """Test that databases have isolated storage."""
    driver = GraphDatabase.driver("ipfs+embedded://./test_data")
    
    # Create data in database A
    with driver.session(database="db_a") as session:
        session.run("CREATE (n:Person {name: 'Alice'})")
    
    # Create data in database B
    with driver.session(database="db_b") as session:
        session.run("CREATE (n:Person {name: 'Bob'})")
    
    # Verify database A only has Alice
    with driver.session(database="db_a") as session:
        result = session.run("MATCH (n:Person) RETURN n.name AS name")
        names = [r["name"] for r in result]
        assert names == ["Alice"]
    
    # Verify database B only has Bob
    with driver.session(database="db_b") as session:
        result = session.run("MATCH (n:Person) RETURN n.name AS name")
        names = [r["name"] for r in result]
        assert names == ["Bob"]
    
    driver.close()


def test_database_management():
    """Test database creation and listing."""
    driver = GraphDatabase.driver("ipfs+embedded://./test_data")
    
    # Create databases
    driver.create_database("users")
    driver.create_database("products")
    
    # List databases
    databases = driver.list_databases()
    assert "users" in databases
    assert "products" in databases
    
    # Drop database
    driver.drop_database("products")
    databases = driver.list_databases()
    assert "products" not in databases
    
    driver.close()


# ... 13 more tests ...
```

### test_cypher_functions.py

**Path:** `tests/unit/knowledge_graphs/test_cypher_functions.py`

```python
"""
Tests for Cypher built-in functions.

Tests all math, spatial, and temporal functions.
"""

import pytest
import math
from datetime import date, datetime
from ipfs_datasets_py.knowledge_graphs.cypher.functions import *


class TestMathFunctions:
    """Test math functions."""
    
    def test_abs(self):
        assert fn_abs(-5) == 5
        assert fn_abs(5) == 5
        assert fn_abs(0) == 0
    
    def test_ceil(self):
        assert fn_ceil(1.2) == 2
        assert fn_ceil(-1.2) == -1
    
    def test_floor(self):
        assert fn_floor(1.8) == 1
        assert fn_floor(-1.2) == -2
    
    def test_round(self):
        assert fn_round(1.5) == 2
        assert fn_round(1.4) == 1
    
    def test_sqrt(self):
        assert fn_sqrt(4) == 2.0
        assert fn_sqrt(9) == 3.0
        with pytest.raises(ValueError):
            fn_sqrt(-1)
    
    def test_sign(self):
        assert fn_sign(5) == 1
        assert fn_sign(-5) == -1
        assert fn_sign(0) == 0
    
    def test_rand(self):
        r = fn_rand()
        assert 0 <= r < 1


class TestSpatialFunctions:
    """Test spatial functions."""
    
    def test_point(self):
        p = fn_point({'x': 3.0, 'y': 4.0})
        assert isinstance(p, Point)
        assert p.x == 3.0
        assert p.y == 4.0
    
    def test_distance(self):
        p1 = Point(0, 0)
        p2 = Point(3, 4)
        d = fn_distance(p1, p2)
        assert d == 5.0


class TestTemporalFunctions:
    """Test temporal functions."""
    
    def test_date_current(self):
        d = fn_date()
        assert isinstance(d, date)
        assert d == date.today()
    
    def test_date_parse(self):
        d = fn_date("2024-01-15")
        assert d.year == 2024
        assert d.month == 1
        assert d.day == 15
    
    def test_datetime_current(self):
        dt = fn_datetime()
        assert isinstance(dt, datetime)
    
    def test_datetime_parse(self):
        dt = fn_datetime("2024-01-15T10:30:00")
        assert dt.year == 2024
        assert dt.hour == 10
    
    def test_timestamp(self):
        ts = fn_timestamp()
        assert isinstance(ts, int)
        assert ts > 1700000000000  # After 2023


# ... more tests ...
```

---

## Success Metrics

### Code Changes
- 3 files modified: driver.py, session.py, ipld_backend.py
- 2 files created: functions.py, (plus 2 test files)
- ~1,000 lines total (+500 production, +500 test)

### Test Coverage
- 15+ multi-database tests
- 15+ function tests
- Total: 30+ new tests
- All 210 Phase 1 tests still pass
- **Grand total: 240+ tests passing**

### Feature Metrics
- Task 2.1: 60% → 100% ✅
- Task 2.3: 0% → 35%
- Neo4j API parity: 94% → 96%
- Phase 2: 22% → 32%

---

## Next Session Checklist

### Hour 1-3: Multi-Database (3 hours)
- [ ] Modify IPLDBackend.__init__() - add database, namespace
- [ ] Add IPLDBackend._make_key() method
- [ ] Update IPLDBackend.store() to use _make_key()
- [ ] Update IPLDBackend.retrieve() to use _make_key()

### Hour 4-6: Driver & Session (3 hours)
- [ ] Modify Driver.__init__() - add _backend_cache
- [ ] Add Driver._get_database_backend() method
- [ ] Modify Driver.session() - use database-specific backend
- [ ] Modify Session.__init__() - accept backend parameter
- [ ] Add Driver.list_databases() method (optional)
- [ ] Add Driver.create_database() method (optional)
- [ ] Add Driver.drop_database() method (optional)

### Hour 7-9: Cypher Functions (3 hours)
- [ ] Create functions.py
- [ ] Implement Point class
- [ ] Implement 7 math functions
- [ ] Implement 2 spatial functions
- [ ] Implement 4 temporal functions
- [ ] Create FUNCTION_REGISTRY

### Hour 10-12: Integration & Testing (3 hours)
- [ ] Modify query_executor.py - add function evaluation
- [ ] Create test_multi_database.py
- [ ] Create test_cypher_functions.py
- [ ] Run all tests
- [ ] Fix any failures
- [ ] Commit and document

---

## Memory for Next Session

✅ **Stored implementation memory:**
- Current status documented
- Exact code changes specified
- Test requirements defined
- Success metrics clear

**To Resume:** Review this document, then implement in order above

---

## Summary

**Status:** Ready to implement Phase 2 critical items

**Preparation Complete:**
- ✅ All planning documents reviewed
- ✅ Current code analyzed
- ✅ Exact changes documented
- ✅ Test strategy defined
- ✅ Success criteria established
- ✅ Memory stored

**Next Action:** Begin implementation in next coding session

**Confidence:** HIGH - Clear roadmap, realistic timeline, proven patterns

---

**Session End:** Preparation complete, ready to code! 🚀
