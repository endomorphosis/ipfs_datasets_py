"""
Cypher Function Library

This module implements essential Cypher functions for Neo4j compatibility.

Categories:
- Math: abs, ceil, floor, round, sqrt, sign, rand, sin, cos, tan, log, exp, pi, e
- Spatial: point, distance
- Temporal: date, datetime, timestamp, duration
- List: range, head, tail, last, reverse, size
- Introspection: type, id, properties, labels, keys

Phase 2 Implementation (38 functions - Path A completion)
"""

import math
import random
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Union


class Point:
    """
    2D Point for spatial operations.
    
    Compatible with Neo4j's point() function result.
    
    Attributes:
        x: X coordinate
        y: Y coordinate
        srid: Spatial Reference System Identifier (7203 for Cartesian 2D)
    """
    
    def __init__(self, x: float, y: float, srid: int = 7203):
        """
        Initialize a Point.
        
        Args:
            x: X coordinate
            y: Y coordinate
            srid: Spatial Reference System Identifier
        """
        self.x = float(x)
        self.y = float(y)
        self.srid = srid
    
    def __repr__(self) -> str:
        return f"point({{x: {self.x}, y: {self.y}, srid: {self.srid}}})"
    
    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Point):
            return False
        return self.x == other.x and self.y == other.y and self.srid == other.srid


# ============================================================================
# Math Functions
# ============================================================================

def fn_abs(n: Union[int, float]) -> Union[int, float]:
    """
    Return the absolute value of a number.
    
    Args:
        n: Input number
        
    Returns:
        Absolute value of n
        
    Example:
        abs(-5) → 5
        abs(3.14) → 3.14
    """
    if n is None:
        return None
    return abs(n)


def fn_ceil(n: Union[int, float]) -> int:
    """
    Return the smallest integer greater than or equal to n.
    
    Args:
        n: Input number
        
    Returns:
        Ceiling of n
        
    Example:
        ceil(3.2) → 4
        ceil(-3.2) → -3
    """
    if n is None:
        return None
    return math.ceil(n)


def fn_floor(n: Union[int, float]) -> int:
    """
    Return the largest integer less than or equal to n.
    
    Args:
        n: Input number
        
    Returns:
        Floor of n
        
    Example:
        floor(3.8) → 3
        floor(-3.2) → -4
    """
    if n is None:
        return None
    return math.floor(n)


def fn_round(n: Union[int, float], precision: int = 0) -> Union[int, float]:
    """
    Round a number to the nearest integer or specified decimal places.
    
    Args:
        n: Input number
        precision: Number of decimal places (default: 0)
        
    Returns:
        Rounded value
        
    Example:
        round(3.14159) → 3
        round(3.14159, 2) → 3.14
    """
    if n is None:
        return None
    return round(n, precision)


def fn_sqrt(n: Union[int, float]) -> float:
    """
    Return the square root of a number.
    
    Args:
        n: Input number (must be non-negative)
        
    Returns:
        Square root of n
        
    Raises:
        ValueError: If n is negative
        
    Example:
        sqrt(16) → 4.0
        sqrt(2) → 1.4142135623730951
    """
    if n is None:
        return None
    if n < 0:
        raise ValueError(f"Cannot calculate square root of negative number: {n}")
    return math.sqrt(n)


def fn_sign(n: Union[int, float]) -> int:
    """
    Return the sign of a number.
    
    Args:
        n: Input number
        
    Returns:
        -1 if n < 0, 0 if n == 0, 1 if n > 0
        
    Example:
        sign(-5) → -1
        sign(0) → 0
        sign(3.14) → 1
    """
    if n is None:
        return None
    if n > 0:
        return 1
    elif n < 0:
        return -1
    else:
        return 0


def fn_rand() -> float:
    """
    Return a random float in the range [0.0, 1.0).
    
    Returns:
        Random number
        
    Example:
        rand() → 0.37454011862460303
    """
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
        point({x: 3.0, y: 4.0}) → point({x: 3.0, y: 4.0, srid: 7203})
    """
    if params is None:
        return None
    
    x = params.get('x', 0)
    y = params.get('y', 0)
    srid = params.get('srid', 7203)  # Default to Cartesian 2D
    
    return Point(x, y, srid)


def fn_distance(point1: Point, point2: Point) -> float:
    """
    Calculate Euclidean distance between two points.
    
    Args:
        point1: First point
        point2: Second point
        
    Returns:
        Distance between points
        
    Example:
        distance(point({x: 0, y: 0}), point({x: 3, y: 4})) → 5.0
    """
    if point1 is None or point2 is None:
        return None
    
    if not isinstance(point1, Point) or not isinstance(point2, Point):
        raise TypeError("distance() requires Point objects")
    
    dx = point2.x - point1.x
    dy = point2.y - point1.y
    return math.sqrt(dx * dx + dy * dy)


# ============================================================================
# Temporal Functions
# ============================================================================

def fn_date(value: Optional[str] = None) -> date:
    """
    Create or parse a date.
    
    Args:
        value: ISO format date string (YYYY-MM-DD), or None for today
        
    Returns:
        Date object
        
    Example:
        date() → today's date
        date("2024-01-15") → 2024-01-15
    """
    if value is None:
        return date.today()
    
    if isinstance(value, date):
        return value
    
    if isinstance(value, str):
        return date.fromisoformat(value)
    
    raise TypeError(f"Cannot create date from: {type(value)}")


def fn_datetime(value: Optional[str] = None) -> datetime:
    """
    Create or parse a datetime.
    
    Args:
        value: ISO format datetime string, or None for now
        
    Returns:
        Datetime object
        
    Example:
        datetime() → current datetime
        datetime("2024-01-15T14:30:00") → 2024-01-15 14:30:00
    """
    if value is None:
        return datetime.now()
    
    if isinstance(value, datetime):
        return value
    
    if isinstance(value, str):
        # Try parsing with various formats
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            # Try alternative formats
            for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
            raise ValueError(f"Cannot parse datetime: {value}")
    
    raise TypeError(f"Cannot create datetime from: {type(value)}")


def fn_timestamp() -> int:
    """
    Return current timestamp in milliseconds since epoch.
    
    Returns:
        Timestamp in milliseconds
        
    Example:
        timestamp() → 1705329000000
    """
    return int(datetime.now().timestamp() * 1000)


def fn_duration(value: str) -> timedelta:
    """
    Parse a duration string.
    
    Args:
        value: Duration string (e.g., "P1DT2H" for 1 day 2 hours)
        
    Returns:
        Timedelta object
        
    Example:
        duration("P1D") → 1 day
        duration("PT2H30M") → 2 hours 30 minutes
    """
    if value is None:
        return None
    
    # Simple ISO 8601 duration parsing
    # Format: P[n]Y[n]M[n]DT[n]H[n]M[n]S
    import re
    
    pattern = r'P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?'
    match = re.match(pattern, value)
    
    if not match:
        raise ValueError(f"Invalid duration format: {value}")
    
    years, months, days, hours, minutes, seconds = match.groups()
    
    # Convert to timedelta (approximate for years and months)
    total_days = 0
    if years:
        total_days += int(years) * 365
    if months:
        total_days += int(months) * 30
    if days:
        total_days += int(days)
    
    total_seconds = 0
    if hours:
        total_seconds += int(hours) * 3600
    if minutes:
        total_seconds += int(minutes) * 60
    if seconds:
        total_seconds += float(seconds)
    
    return timedelta(days=total_days, seconds=total_seconds)


# ============================================================================
# List Functions
# ============================================================================

def fn_range(start: int, end: int, step: int = 1) -> List[int]:
    """
    Generate a range of integers.
    
    Args:
        start: Start value (inclusive)
        end: End value (exclusive)
        step: Step size (default: 1)
        
    Returns:
        List of integers from start to end (exclusive)
        
    Example:
        range(0, 5) → [0, 1, 2, 3, 4]
        range(0, 10, 2) → [0, 2, 4, 6, 8]
        range(5, 0, -1) → [5, 4, 3, 2, 1]
    """
    if start is None or end is None:
        return None
    return list(range(start, end, step))


def fn_head(lst: List) -> Any:
    """
    Get the first element of a list.
    
    Args:
        lst: Input list
        
    Returns:
        First element, or None if list is empty
        
    Example:
        head([1, 2, 3]) → 1
        head([]) → None
        head(None) → None
    """
    if lst is None or not lst:
        return None
    return lst[0]


def fn_tail(lst: List) -> List:
    """
    Get all but the first element of a list.
    
    Args:
        lst: Input list
        
    Returns:
        List with all elements except the first, or empty list
        
    Example:
        tail([1, 2, 3]) → [2, 3]
        tail([1]) → []
        tail([]) → []
    """
    if lst is None:
        return None
    if len(lst) <= 1:
        return []
    return lst[1:]


def fn_last(lst: List) -> Any:
    """
    Get the last element of a list.
    
    Args:
        lst: Input list
        
    Returns:
        Last element, or None if list is empty
        
    Example:
        last([1, 2, 3]) → 3
        last([]) → None
        last(None) → None
    """
    if lst is None or not lst:
        return None
    return lst[-1]


def fn_reverse(obj: Union[List, str]) -> Union[List, str]:
    """
    Reverse a list or string.
    
    Args:
        obj: Input list or string
        
    Returns:
        Reversed list or string
        
    Example:
        reverse([1, 2, 3]) → [3, 2, 1]
        reverse("hello") → "olleh"
        reverse([]) → []
        reverse(None) → None
    """
    if obj is None:
        return None
    if isinstance(obj, str):
        return obj[::-1]
    return list(reversed(obj))


def fn_size(obj: Union[List, str, Dict]) -> int:
    """
    Get the size/length of a collection.
    
    Args:
        obj: Input list, string, or map
        
    Returns:
        Size of the collection
        
    Example:
        size([1, 2, 3]) → 3
        size("hello") → 5
        size({a: 1, b: 2}) → 2
        size(None) → None
    """
    if obj is None:
        return None
    return len(obj)


# ============================================================================
# Introspection Functions
# ============================================================================

def fn_type(relationship: Any) -> str:
    """
    Get the type of a relationship.
    
    Args:
        relationship: Relationship object
        
    Returns:
        Relationship type as string
        
    Example:
        type(r) → "KNOWS" (where r is a KNOWS relationship)
    """
    if relationship is None:
        return None
    if hasattr(relationship, 'type'):
        return relationship.type
    return None


def fn_id(entity: Any) -> str:
    """
    Get the ID of a node or relationship.
    
    Args:
        entity: Node or Relationship object
        
    Returns:
        Entity ID
        
    Example:
        id(n) → "bafybeiabc123..."
    """
    if entity is None:
        return None
    if hasattr(entity, 'id'):
        return entity.id
    return None


def fn_properties(entity: Any) -> Dict:
    """
    Get all properties of a node or relationship.
    
    Args:
        entity: Node or Relationship object
        
    Returns:
        Dictionary of all properties
        
    Example:
        properties(n) → {name: "Alice", age: 30}
    """
    if entity is None:
        return None
    if hasattr(entity, 'properties'):
        return dict(entity.properties)
    if hasattr(entity, '__dict__'):
        # Filter out private attributes
        return {k: v for k, v in entity.__dict__.items() if not k.startswith('_')}
    return {}


def fn_labels(node: Any) -> List[str]:
    """
    Get the labels of a node.
    
    Args:
        node: Node object
        
    Returns:
        List of label strings
        
    Example:
        labels(n) → ["Person", "Employee"]
    """
    if node is None:
        return None
    if hasattr(node, 'labels'):
        return list(node.labels)
    return []


def fn_keys(obj: Union[Dict, Any]) -> List[str]:
    """
    Get the keys/property names of a map or entity.
    
    Args:
        obj: Dictionary, Node, or Relationship
        
    Returns:
        List of key names
        
    Example:
        keys({a: 1, b: 2}) → ["a", "b"]
        keys(n) → ["name", "age"]
    """
    if obj is None:
        return None
    if isinstance(obj, dict):
        return list(obj.keys())
    if hasattr(obj, 'properties'):
        return list(obj.properties.keys())
    if hasattr(obj, '__dict__'):
        return [k for k in obj.__dict__.keys() if not k.startswith('_')]
    return []


# ============================================================================
# Extended Math Functions
# ============================================================================

def fn_sin(n: Union[int, float]) -> float:
    """
    Return the sine of a number (in radians).
    
    Args:
        n: Input number in radians
        
    Returns:
        Sine of n
        
    Example:
        sin(0) → 0.0
        sin(pi()/2) → 1.0
    """
    if n is None:
        return None
    return math.sin(n)


def fn_cos(n: Union[int, float]) -> float:
    """
    Return the cosine of a number (in radians).
    
    Args:
        n: Input number in radians
        
    Returns:
        Cosine of n
        
    Example:
        cos(0) → 1.0
        cos(pi()) → -1.0
    """
    if n is None:
        return None
    return math.cos(n)


def fn_tan(n: Union[int, float]) -> float:
    """
    Return the tangent of a number (in radians).
    
    Args:
        n: Input number in radians
        
    Returns:
        Tangent of n
        
    Example:
        tan(0) → 0.0
    """
    if n is None:
        return None
    return math.tan(n)


def fn_asin(n: Union[int, float]) -> float:
    """
    Return the arc sine of a number.
    
    Args:
        n: Input number (must be between -1 and 1)
        
    Returns:
        Arc sine in radians
        
    Example:
        asin(1) → π/2
    """
    if n is None:
        return None
    return math.asin(n)


def fn_acos(n: Union[int, float]) -> float:
    """
    Return the arc cosine of a number.
    
    Args:
        n: Input number (must be between -1 and 1)
        
    Returns:
        Arc cosine in radians
        
    Example:
        acos(1) → 0
    """
    if n is None:
        return None
    return math.acos(n)


def fn_atan(n: Union[int, float]) -> float:
    """
    Return the arc tangent of a number.
    
    Args:
        n: Input number
        
    Returns:
        Arc tangent in radians
        
    Example:
        atan(0) → 0
    """
    if n is None:
        return None
    return math.atan(n)


def fn_atan2(y: Union[int, float], x: Union[int, float]) -> float:
    """
    Return the arc tangent of y/x in radians.
    
    Args:
        y: Y coordinate
        x: X coordinate
        
    Returns:
        Arc tangent of y/x in radians
        
    Example:
        atan2(1, 1) → π/4
    """
    if y is None or x is None:
        return None
    return math.atan2(y, x)


def fn_log(n: Union[int, float]) -> float:
    """
    Return the natural logarithm (base e) of a number.
    
    Args:
        n: Input number (must be positive)
        
    Returns:
        Natural logarithm of n
        
    Example:
        log(e()) → 1.0
    """
    if n is None:
        return None
    return math.log(n)


def fn_log10(n: Union[int, float]) -> float:
    """
    Return the base-10 logarithm of a number.
    
    Args:
        n: Input number (must be positive)
        
    Returns:
        Base-10 logarithm of n
        
    Example:
        log10(100) → 2.0
    """
    if n is None:
        return None
    return math.log10(n)


def fn_exp(n: Union[int, float]) -> float:
    """
    Return e raised to the power of a number.
    
    Args:
        n: Input number
        
    Returns:
        e^n
        
    Example:
        exp(1) → e
        exp(0) → 1.0
    """
    if n is None:
        return None
    return math.exp(n)


def fn_pi() -> float:
    """
    Return the value of π (pi).
    
    Returns:
        Value of π
        
    Example:
        pi() → 3.141592653589793
    """
    return math.pi


def fn_e() -> float:
    """
    Return the value of e (Euler's number).
    
    Returns:
        Value of e
        
    Example:
        e() → 2.718281828459045
    """
    return math.e


# ============================================================================
# Function Registry
# ============================================================================

FUNCTION_REGISTRY = {
    # Math functions (basic)
    'abs': fn_abs,
    'ceil': fn_ceil,
    'floor': fn_floor,
    'round': fn_round,
    'sqrt': fn_sqrt,
    'sign': fn_sign,
    'rand': fn_rand,
    
    # Math functions (trigonometric)
    'sin': fn_sin,
    'cos': fn_cos,
    'tan': fn_tan,
    'asin': fn_asin,
    'acos': fn_acos,
    'atan': fn_atan,
    'atan2': fn_atan2,
    
    # Math functions (logarithmic and exponential)
    'log': fn_log,
    'log10': fn_log10,
    'exp': fn_exp,
    'pi': fn_pi,
    'e': fn_e,
    
    # Spatial functions
    'point': fn_point,
    'distance': fn_distance,
    
    # Temporal functions
    'date': fn_date,
    'datetime': fn_datetime,
    'timestamp': fn_timestamp,
    'duration': fn_duration,
    
    # List functions
    'range': fn_range,
    'head': fn_head,
    'tail': fn_tail,
    'last': fn_last,
    'reverse': fn_reverse,
    'size': fn_size,
    
    # Introspection functions
    'type': fn_type,
    'id': fn_id,
    'properties': fn_properties,
    'labels': fn_labels,
    'keys': fn_keys,
}


def evaluate_function(name: str, *args, **kwargs) -> Any:
    """
    Evaluate a Cypher function by name.
    
    Args:
        name: Function name
        *args: Positional arguments
        **kwargs: Keyword arguments
        
    Returns:
        Function result
        
    Raises:
        ValueError: If function not found
        
    Example:
        evaluate_function('abs', -5) → 5
        evaluate_function('point', {'x': 3, 'y': 4}) → Point(3, 4)
    """
    if name not in FUNCTION_REGISTRY:
        raise ValueError(f"Unknown function: {name}")
    
    func = FUNCTION_REGISTRY[name]
    return func(*args, **kwargs)
