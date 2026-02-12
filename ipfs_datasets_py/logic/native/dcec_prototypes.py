"""
DCEC Prototype and Advanced Namespace Management

This module provides advanced namespace functionality for DCEC including:
- Sort hierarchy management with inheritance
- Function prototype definitions
- Atomic type definitions
- Type conflict resolution
- Built-in DCEC sorts and functions

Ported from DCEC_Library/prototypes.py to pure Python 3.
"""

from typing import Dict, List, Optional, Tuple
import logging
from .dcec_cleaning import strip_whitespace

logger = logging.getLogger(__name__)


class DCECPrototypeNamespace:
    """
    Advanced namespace management for DCEC with prototype definitions.
    
    Manages sorts (types), functions, and atomics with inheritance and
    type checking. Provides methods to add definitions from both code
    and text expressions.
    
    Attributes:
        functions: Dict mapping function names to list of [return_type, arg_types]
        atomics: Dict mapping atomic names to their types
        sorts: Dict mapping sort names to their parent sorts (inheritance)
        quant_map: Dict for quantifier variable mapping
    """
    
    def __init__(self):
        """Initialize an empty prototype namespace."""
        self.functions: Dict[str, List[List[str]]] = {}
        self.atomics: Dict[str, str] = {}
        self.sorts: Dict[str, List[str]] = {}
        self.quant_map: Dict[str, int] = {"TEMP": 0}
    
    def add_code_sort(self, name: str, inheritance: Optional[List[str]] = None) -> bool:
        """
        Add a sort (type) definition programmatically.
        
        Args:
            name: The name of the sort to add
            inheritance: List of parent sorts (empty list means no parents)
            
        Returns:
            bool: True if successful, False if error
            
        Examples:
            >>> ns = DCECPrototypeNamespace()
            >>> ns.add_code_sort("Object")
            True
            >>> ns.add_code_sort("Agent", ["Object"])
            True
        """
        if inheritance is None:
            inheritance = []
        
        if not (isinstance(name, str) and isinstance(inheritance, list)):
            logger.error("addCodeSort takes arguments of the form: string, list of strings")
            return False
        
        # Check that all parent sorts exist
        for parent in inheritance:
            if parent not in self.sorts:
                logger.error(f"Sort {parent} is not previously defined")
                return False
        
        # Don't redefine existing sorts
        if name in self.sorts:
            return True
        
        self.sorts[name] = inheritance
        return True
    
    def add_text_sort(self, expression: str) -> bool:
        """
        Add a sort definition from a text expression.
        
        Args:
            expression: Text expression like "(typedef Sort)" or "(typedef Child Parent)"
            
        Returns:
            bool: True if successful, False if error
            
        Examples:
            >>> ns = DCECPrototypeNamespace()
            >>> ns.add_text_sort("(typedef Object)")
            True
            >>> ns.add_text_sort("(typedef Agent Object)")
            True
        """
        temp = expression.replace("(", " ")
        temp = temp.replace(")", " ")
        temp = strip_whitespace(temp)
        temp = temp.replace("`", "")
        args = temp.split(",")
        
        if len(args) == 2:
            return self.add_code_sort(args[1])
        elif len(args) > 2:
            return self.add_code_sort(args[1], args[2:])
        else:
            logger.error("Cannot define the sort")
            return False
    
    def find_atomic_type(self, name: str) -> Optional[str]:
        """
        Find the type of an atomic.
        
        Args:
            name: The atomic name to look up
            
        Returns:
            Optional[str]: The type of the atomic, or None if not found
        """
        if name in self.atomics:
            return self.atomics[name]
        return None
    
    def add_code_function(self, name: str, return_type: str, args_types: List[str]) -> bool:
        """
        Add a function definition programmatically.
        
        Args:
            name: The function name
            return_type: The return type of the function
            args_types: List of argument types
            
        Returns:
            bool: True if successful
            
        Examples:
            >>> ns = DCECPrototypeNamespace()
            >>> ns.add_code_sort("Boolean")
            True
            >>> ns.add_code_function("and", "Boolean", ["Boolean", "Boolean"])
            True
        """
        item = [return_type, args_types]
        
        if name in self.functions:
            if item not in self.functions[name]:
                self.functions[name].append(item)
        else:
            self.functions[name] = [item]
        
        return True
    
    def add_text_function(self, expression: str) -> bool:
        """
        Add a function definition from a text expression.
        
        Args:
            expression: Text expression with function prototype
            
        Returns:
            bool: True if successful, False if error
            
        Examples:
            >>> ns = DCECPrototypeNamespace()
            >>> ns.add_code_sort("Boolean")
            True
            >>> ns.add_text_function("(Boolean and Boolean Boolean)")
            True
        """
        temp = expression.replace("(", " ")
        temp = temp.replace(")", " ")
        temp = strip_whitespace(temp)
        temp = temp.replace("`", "")
        args = temp.split(",")
        
        # Handle typedef
        if args[0].lower() == "typedef":
            return self.add_text_sort(expression)
        
        # Handle atomic (2 args)
        if len(args) == 2:
            return self.add_text_atomic(expression)
        
        return_type = ""
        func_name = ""
        func_args = []
        
        # Find the return type
        if args[0] in self.sorts:
            return_type = args[0]
            args.remove(args[0])
        
        # Find the function name
        for arg in args:
            if arg not in self.sorts:
                func_name = arg
                args.remove(arg)
                break
        
        # Find the function args
        for arg in args:
            if arg in self.sorts:
                func_args.append(arg)
        
        # Error checking
        if return_type == "" or func_name == "" or func_args == []:
            logger.error("The function prototype was not formatted correctly")
            return False
        
        # Add the function
        return self.add_code_function(func_name, return_type, func_args)
    
    def add_code_atomic(self, name: str, type_name: str) -> bool:
        """
        Add an atomic (constant) definition programmatically.
        
        Args:
            name: The atomic name
            type_name: The type of the atomic
            
        Returns:
            bool: True if successful, False if error (type conflict)
            
        Examples:
            >>> ns = DCECPrototypeNamespace()
            >>> ns.add_code_sort("Agent")
            True
            >>> ns.add_code_atomic("john", "Agent")
            True
        """
        if name in self.atomics:
            if type_name == self.atomics[name]:
                return True
            else:
                logger.error(
                    f"Item {name} was previously defined as {self.atomics[name]}, "
                    f"you cannot overload atomics"
                )
                return False
        else:
            self.atomics[name] = type_name
        
        return True
    
    def add_text_atomic(self, expression: str) -> bool:
        """
        Add an atomic definition from a text expression.
        
        Args:
            expression: Text expression like "(Type name)"
            
        Returns:
            bool: True if successful, False if error
        """
        temp = expression.replace("(", " ")
        temp = temp.replace(")", " ")
        temp = strip_whitespace(temp)
        temp = temp.replace("`", "")
        args = temp.split(",")
        
        return_type = ""
        func_name = ""
        
        # Find the return type
        for arg in args:
            if arg in self.sorts:
                return_type = arg
                args.remove(arg)
                break
        
        # Find the function name
        for arg in args:
            if arg not in self.sorts:
                func_name = arg
                args.remove(arg)
                break
        
        return self.add_code_atomic(func_name, return_type)
    
    def add_basic_dcec(self) -> None:
        """
        Add basic DCEC sorts and functions to the namespace.
        
        This includes:
        - Basic sorts: Object, Agent, Self, ActionType, Event, Action, Moment, etc.
        - Modal functions: C, B, K, P, I, D, S, O
        - Fluent functions: action, initially, holds, happens, etc.
        - Logical functions: implies, iff, not, and
        - Time functions: lessOrEqual
        """
        # The Basic DCEC Sorts
        self.add_code_sort("Object")
        self.add_code_sort("Agent", ["Object"])
        self.add_code_sort("Self", ["Object", "Agent"])
        self.add_code_sort("ActionType", ["Object"])
        self.add_code_sort("Event", ["Object"])
        self.add_code_sort("Action", ["Object", "Event"])
        self.add_code_sort("Moment", ["Object"])
        self.add_code_sort("Boolean", ["Object"])
        self.add_code_sort("Fluent", ["Object"])
        self.add_code_sort("Numeric", ["Object"])
        self.add_code_sort("Set", ["Object"])
        
        # The Basic DCEC Modal Functions
        self.add_code_function("C", "Boolean", ["Moment", "Boolean"])
        self.add_code_function("B", "Boolean", ["Agent", "Moment", "Boolean"])
        self.add_code_function("K", "Boolean", ["Agent", "Moment", "Boolean"])
        self.add_code_function("P", "Boolean", ["Agent", "Moment", "Boolean"])
        self.add_code_function("I", "Boolean", ["Agent", "Moment", "Boolean"])
        self.add_code_function("D", "Boolean", ["Agent", "Moment", "Boolean"])
        self.add_code_function("S", "Boolean", ["Agent", "Agent", "Moment", "Boolean"])
        self.add_code_function("O", "Boolean", ["Agent", "Moment", "Boolean", "Boolean"])
        
        # Fluent Functions
        self.add_code_function("action", "Action", ["Agent", "ActionType"])
        self.add_code_function("initially", "Boolean", ["Fluent"])
        self.add_code_function("holds", "Boolean", ["Fluent", "Moment"])
        self.add_code_function("happens", "Boolean", ["Event", "Moment"])
        self.add_code_function("clipped", "Boolean", ["Moment", "Fluent", "Moment"])
        self.add_code_function("initiates", "Boolean", ["Event", "Fluent", "Moment"])
        self.add_code_function("terminates", "Boolean", ["Event", "Fluent", "Moment"])
        self.add_code_function("prior", "Boolean", ["Moment", "Moment"])
        self.add_code_function("interval", "Fluent", ["Moment", "Boolean"])
        self.add_code_function("self", "Self", ["Agent"])
        self.add_code_function("payoff", "Numeric", ["Agent", "ActionType", "Moment"])
        
        # Logical Functions
        self.add_code_function("implies", "Boolean", ["Boolean", "Boolean"])
        self.add_code_function("iff", "Boolean", ["Boolean", "Boolean"])
        self.add_code_function("not", "Boolean", ["Boolean"])
        self.add_code_function("and", "Boolean", ["Boolean", "Boolean"])
        
        # Time Functions
        self.add_code_function("lessOrEqual", "Boolean", ["Moment", "Moment"])
    
    def add_basic_logic(self) -> None:
        """Add basic logical functions (or, xor)."""
        self.add_code_function("or", "Boolean", ["Boolean", "Boolean"])
        self.add_code_function("xor", "Boolean", ["Boolean", "Boolean"])
    
    def add_basic_numerics(self) -> None:
        """Add basic numeric and comparison functions."""
        # Numerical Functions
        self.add_code_function("negate", "Numeric", ["Numeric"])
        self.add_code_function("add", "Numeric", ["Numeric", "Numeric"])
        self.add_code_function("sub", "Numeric", ["Numeric", "Numeric"])
        self.add_code_function("multiply", "Numeric", ["Numeric", "Numeric"])
        self.add_code_function("divide", "Numeric", ["Numeric", "Numeric"])
        self.add_code_function("exponent", "Numeric", ["Numeric", "Numeric"])
        
        # Comparison Functions
        self.add_code_function("greater", "Boolean", ["Numeric", "Numeric"])
        self.add_code_function("greaterOrEqual", "Boolean", ["Numeric", "Numeric"])
        self.add_code_function("less", "Boolean", ["Numeric", "Numeric"])
        self.add_code_function("lessOrEqual", "Boolean", ["Numeric", "Numeric"])
        self.add_code_function("equals", "Boolean", ["Numeric", "Numeric"])
    
    def no_conflict(self, type1: str, type2: str, level: int = 0) -> Tuple[bool, int]:
        """
        Check if two types are compatible (no conflict).
        
        Checks if type2 is compatible with type1 through inheritance.
        Returns the inheritance distance if compatible.
        
        Args:
            type1: The expected type
            type2: The actual type
            level: Current recursion level (distance)
            
        Returns:
            Tuple[bool, int]: (compatible, distance)
            
        Examples:
            >>> ns = DCECPrototypeNamespace()
            >>> ns.add_code_sort("Object")
            True
            >>> ns.add_code_sort("Agent", ["Object"])
            True
            >>> ns.no_conflict("Object", "Agent")
            (True, 1)
        """
        # Wildcard type always matches
        if type1 == "?":
            return (True, level)
        
        # Exact match
        if type1 == type2:
            return (True, level)
        
        # Check if type2 is direct parent of type1
        if type1 in self.sorts and type2 in self.sorts[type1]:
            return (True, level + 1)
        
        # Recursively check inheritance chain
        if type1 in self.sorts:
            return_list = []
            for parent in self.sorts[type1]:
                recurse_return = self.no_conflict(parent, type2, level + 1)
                if recurse_return[0]:
                    return_list.append(recurse_return[1])
            
            if len(return_list) > 0:
                return (True, min(return_list))
        
        return (False, level)
    
    def print_namespace(self) -> None:
        """Print the entire namespace (sorts, functions, atomics)."""
        print("=== Sorts ===")
        for item in self.sorts:
            print(f"{item}: {self.sorts[item]}")
        
        print("\n=== Functions ===")
        for item in self.functions:
            print(f"{item}: {self.functions[item]}")
        
        print("\n=== Atomics ===")
        for item in self.atomics:
            print(f"{item}: {self.atomics[item]}")
    
    def get_statistics(self) -> Dict[str, int]:
        """
        Get statistics about the namespace.
        
        Returns:
            Dict with counts of sorts, functions, atomics
        """
        return {
            "sorts": len(self.sorts),
            "functions": len(self.functions),
            "atomics": len(self.atomics),
            "function_overloads": sum(len(v) for v in self.functions.values()),
        }
