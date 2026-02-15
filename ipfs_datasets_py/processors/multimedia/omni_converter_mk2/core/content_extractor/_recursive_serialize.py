from typing import Any
import base64
import math
from datetime import datetime, date
from decimal import Decimal
from pathlib import Path
from enum import Enum
from uuid import UUID
from types import GeneratorType, ModuleType


def _recursive_serialize(obj: Any, _seen: set = None) -> Any:
    """Recursively serialize objects to JSON-compatible types.
    
    Args:
        obj (Any): The object to serialize.
        _seen (set): Internal parameter to track seen objects for circular reference detection.
    
    Returns:
        JSON-compatible representation of the object.
    
    Raises:
        ValueError: If circular reference is detected.
    """
    # Initialize seen set for circular reference detection
    if _seen is None:
        _seen = set()
    
    # Handle None
    if obj is None:
        return None
    
    # Handle basic JSON-serializable types
    if isinstance(obj, (str, int, float, bool)):
        print(f"Serializing basic type: {obj}")  # Debug print
        # Handle special float values
        if isinstance(obj, float):
            if math.isinf(obj):
                return "Infinity" if obj > 0 else "-Infinity"
            elif math.isnan(obj):
                return "NaN"
        return obj
    
    # Check for circular references using object id
    obj_id = id(obj)
    if obj_id in _seen:
        raise ValueError("Circular reference detected")
    
    # Add current object to seen set for containers
    if hasattr(obj, '__iter__') or hasattr(obj, '__dict__'):
        _seen.add(obj_id)
    
    try:
        # Handle collections
        if isinstance(obj, list):
            return [_recursive_serialize(item, _seen) for item in obj]
        
        elif isinstance(obj, tuple):
            return [_recursive_serialize(item, _seen) for item in obj]
        
        elif isinstance(obj, dict):
            print(f"Serializing dictionary: {obj}")  # Debug print
            result = {}
            for key, value in obj.items():
                print(f"Serializing key: {key}, value: {value}")  # Debug print
                # Convert keys to strings
                if isinstance(key, (int, float, bool)):
                    str_key = str(key)
                elif isinstance(key, tuple):
                    str_key = str(key)
                else:
                    str_key = str(key)
                result[str_key] = _recursive_serialize(value, _seen)
            return result
        
        elif isinstance(obj, (set, frozenset)):
            return [_recursive_serialize(item, _seen) for item in obj]
        
        elif isinstance(obj, range):
            return list(obj)
        
        # Handle datetime objects
        elif isinstance(obj, datetime):
            return obj.strftime("%Y-%m-%dT%H:%M:%S")
        
        elif isinstance(obj, date):
            return obj.strftime("%Y-%m-%d")
        
        # Handle Decimal
        elif isinstance(obj, Decimal):
            return str(obj)
        
        # Handle bytes and bytearray
        elif isinstance(obj, (bytes, bytearray)):
            try:
                # Try to decode as UTF-8 first
                return obj.decode('utf-8')
            except UnicodeDecodeError:
                # Fall back to base64 encoding
                return base64.b64encode(bytes(obj)).decode('ascii')
        
        # Handle numpy types if available
        try:
            import numpy as np
            if isinstance(obj, np.ndarray):
                return _recursive_serialize(obj.tolist(), _seen)
            elif isinstance(obj, np.generic):
                return _recursive_serialize(obj.item(), _seen)
        except ImportError:
            pass
        
        # Handle pandas types if available
        try:
            import pandas as pd
            if isinstance(obj, pd.Series):
                return _recursive_serialize(obj.tolist(), _seen)
            elif isinstance(obj, pd.DataFrame):
                return _recursive_serialize(obj.to_dict('records'), _seen)
        except ImportError:
            pass

        # Handle memoryview
        if isinstance(obj, memoryview):
            return list(obj.tobytes())

        # Handle Path objects
        elif isinstance(obj, Path):
            return str(obj)
        
        # Handle UUID
        elif isinstance(obj, UUID):
            return str(obj)
        
        # Handle Enum
        elif isinstance(obj, Enum):
            return _recursive_serialize(obj.value, _seen)
        
        # Handle complex numbers
        elif isinstance(obj, complex):
            return {"real": obj.real, "imag": obj.imag}
        
        # Handle generator objects
        elif isinstance(obj, GeneratorType):
            return [_recursive_serialize(item, _seen) for item in obj]
        
        # Handle functions and lambdas
        elif callable(obj) and not isinstance(obj, type):
            if hasattr(obj, '__name__'):
                return f"<function {obj.__name__}>"
            else:
                return "<function lambda>"
        
        # Handle module objects
        elif isinstance(obj, ModuleType):
            return f"<module '{obj.__name__}'>"
        
        # Handle class types
        elif isinstance(obj, type):
            return f"<class '{obj.__name__}'>"
        
        # Handle custom objects with __dict__
        elif hasattr(obj, '__dict__'):
            return _recursive_serialize(obj.__dict__, _seen)
        
        # Handle objects with __str__ method as fallback
        elif hasattr(obj, '__str__'):
            return str(obj)
        
        # Final fallback
        else:
            return str(obj)

    except Exception as e:
        # Handle problematic objects that raise exceptions
        if "Cannot access attributes" in str(e):
            return f"<{type(obj).__name__} object>"
        # Re-raise unexpected exceptions
        raise

    finally:
        # Remove from seen set when exiting
        if obj_id in _seen:
            _seen.discard(obj_id)
