"""
Rule Engine for IPFS Datasets Alert System

This module provides a safe rule evaluation engine using JSON-Logic style predicates.
Rules can be defined to check conditions on streaming market data and trigger alerts.

The engine supports:
- Standard operators: and, or, not, comparison operators
- Custom predicates: zscore, sma, ema
- Safe evaluation without using eval()
- First-order logic approximation with variable bindings
"""

from __future__ import annotations

import logging
import statistics
from typing import Any, Dict, List, Optional, Union, Callable
from collections import deque
import math

logger = logging.getLogger(__name__)


class RuleEvaluationError(Exception):
    """Exception raised when rule evaluation fails."""
    pass


class RuleEngine:
    """
    Safe rule evaluation engine for alert conditions.
    
    Rules are defined using a JSON-Logic style format that can be safely evaluated
    without using Python's eval() function.
    
    Example rule format:
    {
        "and": [
            {">": [{"var": "price"}, 100]},
            {"<": [{"var": "volume"}, 1000]}
        ]
    }
    """
    
    def __init__(self, custom_predicates: Optional[Dict[str, Callable]] = None):
        """
        Initialize rule engine.
        
        Args:
            custom_predicates: Dictionary mapping predicate names to callables
        """
        self.operators = {
            # Logical operators
            'and': self._op_and,
            'or': self._op_or,
            'not': self._op_not,
            
            # Comparison operators
            '>': self._op_gt,
            '<': self._op_lt,
            '>=': self._op_gte,
            '<=': self._op_lte,
            '==': self._op_eq,
            '!=': self._op_ne,
            
            # Collection operators
            'in': self._op_in,
            'any': self._op_any,
            'all': self._op_all,
            
            # Math operators
            'abs': self._op_abs,
            'max': self._op_max,
            'min': self._op_min,
            '+': self._op_add,
            '-': self._op_sub,
            '*': self._op_mul,
            '/': self._op_div,
            
            # Variable access
            'var': self._op_var,
        }
        
        # Statistical/financial predicates
        self.custom_predicates = {
            'zscore': self._pred_zscore,
            'sma': self._pred_sma,
            'ema': self._pred_ema,
            'stddev': self._pred_stddev,
            'percent_change': self._pred_percent_change,
        }
        
        if custom_predicates:
            self.custom_predicates.update(custom_predicates)
        
        # Merge custom predicates into operators
        self.operators.update(self.custom_predicates)
        
        # History buffer for time-series operations
        self.history: Dict[str, deque] = {}
        self.history_size = 100  # Keep last N values
    
    def evaluate(
        self,
        rule: Union[Dict, List, Any],
        context: Dict[str, Any]
    ) -> bool:
        """
        Evaluate a rule against a context.
        
        Args:
            rule: Rule definition (dict, list, or literal)
            context: Variable bindings for the rule
            
        Returns:
            Boolean result of rule evaluation
            
        Raises:
            RuleEvaluationError: If evaluation fails
        """
        try:
            result = self._evaluate_node(rule, context)
            # Coerce to boolean
            return bool(result)
        except Exception as e:
            logger.error(f"Error evaluating rule: {e}", exc_info=True)
            raise RuleEvaluationError(f"Rule evaluation failed: {e}") from e
    
    def _evaluate_node(
        self,
        node: Union[Dict, List, Any],
        context: Dict[str, Any]
    ) -> Any:
        """Recursively evaluate a rule node."""
        # Literal values
        if not isinstance(node, (dict, list)):
            return node
        
        # List of operations
        if isinstance(node, list):
            return [self._evaluate_node(item, context) for item in node]
        
        # Dictionary operation
        if isinstance(node, dict):
            # Should have exactly one key (the operator)
            if len(node) != 1:
                raise RuleEvaluationError(
                    f"Rule node must have exactly one key, got {len(node)}"
                )
            
            operator, args = next(iter(node.items()))
            
            if operator not in self.operators:
                raise RuleEvaluationError(f"Unknown operator: {operator}")
            
            # Evaluate arguments recursively
            if isinstance(args, list):
                eval_args = [self._evaluate_node(arg, context) for arg in args]
            else:
                eval_args = [self._evaluate_node(args, context)]
            
            # Apply operator
            return self.operators[operator](*eval_args, context=context)
        
        return node
    
    # Logical operators
    
    def _op_and(self, *args, context: Dict[str, Any]) -> bool:
        """Logical AND."""
        return all(bool(arg) for arg in args)
    
    def _op_or(self, *args, context: Dict[str, Any]) -> bool:
        """Logical OR."""
        return any(bool(arg) for arg in args)
    
    def _op_not(self, arg, context: Dict[str, Any]) -> bool:
        """Logical NOT."""
        return not bool(arg)
    
    # Comparison operators
    
    def _op_gt(self, a, b, context: Dict[str, Any]) -> bool:
        """Greater than."""
        return a > b
    
    def _op_lt(self, a, b, context: Dict[str, Any]) -> bool:
        """Less than."""
        return a < b
    
    def _op_gte(self, a, b, context: Dict[str, Any]) -> bool:
        """Greater than or equal."""
        return a >= b
    
    def _op_lte(self, a, b, context: Dict[str, Any]) -> bool:
        """Less than or equal."""
        return a <= b
    
    def _op_eq(self, a, b, context: Dict[str, Any]) -> bool:
        """Equal."""
        return a == b
    
    def _op_ne(self, a, b, context: Dict[str, Any]) -> bool:
        """Not equal."""
        return a != b
    
    # Collection operators
    
    def _op_in(self, item, collection, context: Dict[str, Any]) -> bool:
        """Check if item is in collection."""
        return item in collection
    
    def _op_any(self, *args, context: Dict[str, Any]) -> bool:
        """Check if any item is truthy."""
        # Flatten if args is a single list
        if len(args) == 1 and isinstance(args[0], list):
            items = args[0]
        else:
            items = args
        return any(bool(item) for item in items)
    
    def _op_all(self, *args, context: Dict[str, Any]) -> bool:
        """Check if all items are truthy."""
        # Flatten if args is a single list
        if len(args) == 1 and isinstance(args[0], list):
            items = args[0]
        else:
            items = args
        return all(bool(item) for item in items)
    
    # Math operators
    
    def _op_abs(self, value, context: Dict[str, Any]) -> float:
        """Absolute value."""
        return abs(value)
    
    def _op_max(self, *args, context: Dict[str, Any]) -> float:
        """Maximum value."""
        return max(args)
    
    def _op_min(self, *args, context: Dict[str, Any]) -> float:
        """Minimum value."""
        return min(args)
    
    def _op_add(self, *args, context: Dict[str, Any]) -> float:
        """Addition."""
        return sum(args)
    
    def _op_sub(self, a, b, context: Dict[str, Any]) -> float:
        """Subtraction."""
        return a - b
    
    def _op_mul(self, *args, context: Dict[str, Any]) -> float:
        """Multiplication."""
        result = 1
        for arg in args:
            result *= arg
        return result
    
    def _op_div(self, a, b, context: Dict[str, Any]) -> float:
        """Division."""
        if b == 0:
            raise RuleEvaluationError("Division by zero")
        return a / b
    
    # Variable access
    
    def _op_var(self, path: str, default=None, context: Dict[str, Any] = None) -> Any:
        """
        Access a variable from context.
        
        Supports dot notation for nested access: "user.name"
        """
        if context is None:
            return default
        
        parts = path.split('.')
        value = context
        
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
                if value is None:
                    return default
            else:
                return default
        
        return value
    
    # Statistical/Financial predicates
    
    def _pred_zscore(
        self,
        var_path: str,
        window: int = 20,
        context: Dict[str, Any] = None
    ) -> float:
        """
        Calculate z-score for a variable over a rolling window.
        
        Z-score = (value - mean) / stddev
        """
        if context is None:
            raise RuleEvaluationError("Context required for zscore")
        
        value = self._op_var(var_path, context=context)
        if value is None:
            raise RuleEvaluationError(f"Variable not found: {var_path}")
        
        # Update history
        if var_path not in self.history:
            self.history[var_path] = deque(maxlen=self.history_size)
        self.history[var_path].append(float(value))
        
        # Need at least 2 values for stddev
        if len(self.history[var_path]) < 2:
            return 0.0
        
        # Get window
        hist = list(self.history[var_path])[-window:]
        
        mean = statistics.mean(hist)
        stddev = statistics.stdev(hist)
        
        if stddev == 0:
            return 0.0
        
        return (float(value) - mean) / stddev
    
    def _pred_sma(
        self,
        var_path: str,
        window: int = 20,
        context: Dict[str, Any] = None
    ) -> float:
        """Calculate simple moving average."""
        if context is None:
            raise RuleEvaluationError("Context required for sma")
        
        value = self._op_var(var_path, context=context)
        if value is None:
            raise RuleEvaluationError(f"Variable not found: {var_path}")
        
        # Update history
        if var_path not in self.history:
            self.history[var_path] = deque(maxlen=self.history_size)
        self.history[var_path].append(float(value))
        
        # Get window
        hist = list(self.history[var_path])[-window:]
        
        return statistics.mean(hist)
    
    def _pred_ema(
        self,
        var_path: str,
        window: int = 20,
        context: Dict[str, Any] = None
    ) -> float:
        """Calculate exponential moving average."""
        if context is None:
            raise RuleEvaluationError("Context required for ema")
        
        value = self._op_var(var_path, context=context)
        if value is None:
            raise RuleEvaluationError(f"Variable not found: {var_path}")
        
        # Update history
        key = f"{var_path}_ema_{window}"
        if key not in self.history:
            self.history[key] = deque(maxlen=self.history_size)
        
        alpha = 2.0 / (window + 1)
        
        if not self.history[key]:
            # First value
            ema = float(value)
        else:
            # EMA = alpha * value + (1 - alpha) * previous_ema
            previous_ema = self.history[key][-1]
            ema = alpha * float(value) + (1 - alpha) * previous_ema
        
        self.history[key].append(ema)
        return ema
    
    def _pred_stddev(
        self,
        var_path: str,
        window: int = 20,
        context: Dict[str, Any] = None
    ) -> float:
        """Calculate standard deviation over a rolling window."""
        if context is None:
            raise RuleEvaluationError("Context required for stddev")
        
        value = self._op_var(var_path, context=context)
        if value is None:
            raise RuleEvaluationError(f"Variable not found: {var_path}")
        
        # Update history
        if var_path not in self.history:
            self.history[var_path] = deque(maxlen=self.history_size)
        self.history[var_path].append(float(value))
        
        # Need at least 2 values
        if len(self.history[var_path]) < 2:
            return 0.0
        
        # Get window
        hist = list(self.history[var_path])[-window:]
        
        return statistics.stdev(hist)
    
    def _pred_percent_change(
        self,
        var_path: str,
        periods: int = 1,
        context: Dict[str, Any] = None
    ) -> float:
        """
        Calculate percent change over N periods.
        
        Returns: ((current - previous) / previous) * 100
        """
        if context is None:
            raise RuleEvaluationError("Context required for percent_change")
        
        value = self._op_var(var_path, context=context)
        if value is None:
            raise RuleEvaluationError(f"Variable not found: {var_path}")
        
        # Update history
        if var_path not in self.history:
            self.history[var_path] = deque(maxlen=self.history_size)
        self.history[var_path].append(float(value))
        
        # Need at least periods + 1 values
        if len(self.history[var_path]) <= periods:
            return 0.0
        
        hist = list(self.history[var_path])
        current = hist[-1]
        previous = hist[-(periods + 1)]
        
        if previous == 0:
            return 0.0
        
        return ((current - previous) / previous) * 100.0
    
    def reset_history(self, var_path: Optional[str] = None):
        """
        Reset history buffer.
        
        Args:
            var_path: If provided, reset only this variable's history.
                     If None, reset all history.
        """
        if var_path:
            if var_path in self.history:
                self.history[var_path].clear()
        else:
            self.history.clear()
    
    def register_predicate(self, name: str, func: Callable):
        """
        Register a custom predicate.
        
        Args:
            name: Name of the predicate
            func: Callable that implements the predicate.
                 Must accept context as a keyword argument.
        """
        self.custom_predicates[name] = func
        self.operators[name] = func
