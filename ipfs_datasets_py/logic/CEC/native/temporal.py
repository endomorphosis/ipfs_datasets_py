"""
Temporal Reasoning for DCEC (Phase 4 Week 1)

This module provides temporal operators and reasoning capabilities for
Deontic Cognitive Event Calculus, enabling reasoning about time-dependent
properties and sequences of states.

Features:
- Temporal operators (Always, Eventually, Next, Until, Since, Yesterday)
- Time sequence evaluation
- Temporal formula construction and validation
- Integration with DCEC formula system

Temporal Operators:
    ALWAYS (□):      It is always the case that φ
    EVENTUALLY (◇):  It will eventually be the case that φ  
    NEXT (X):        In the next time point, φ holds
    UNTIL (U):       φ holds until ψ becomes true
    SINCE (S):       φ has been true since ψ was true
    YESTERDAY (Y):   In the previous time point, φ held

Examples:
    >>> from ipfs_datasets_py.logic.CEC.native.temporal import TemporalOperator, TemporalFormula
    >>> from ipfs_datasets_py.logic.CEC.native.dcec_core import parse_dcec
    >>> 
    >>> # Create temporal formula: □(p) - "p is always true"
    >>> p = parse_dcec("p")
    >>> always_p = TemporalFormula(TemporalOperator.ALWAYS, p)
    >>> 
    >>> # Evaluate over time sequence
    >>> states = [{'p': True}, {'p': True}, {'p': True}]
    >>> result = always_p.evaluate(states)
    >>> print(result)  # True

Notes:
    - Temporal operators follow standard Linear Temporal Logic (LTL) semantics
    - Time is discrete and linear (no branching)
    - Evaluations are over finite time sequences
"""

from enum import Enum
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass, field
import logging
from abc import ABC, abstractmethod

from .dcec_core import Formula
from .exceptions import ValidationError

try:
    from beartype import beartype
except ImportError:
    from typing import TypeVar, Callable, Any as AnyType
    F = TypeVar('F', bound=Callable[..., AnyType])
    def beartype(func: F) -> F:
        return func

logger = logging.getLogger(__name__)


class TemporalOperator(Enum):
    """
    Temporal operators for reasoning about time-dependent properties.
    
    These operators follow Linear Temporal Logic (LTL) semantics and enable
    reasoning about sequences of states over time.
    
    Operators:
        ALWAYS (□): It is always the case that φ
            - □φ is true iff φ is true at all future time points
            - Example: □(safe) - "it is always safe"
            
        EVENTUALLY (◇): It will eventually be the case that φ
            - ◇φ is true iff φ is true at some future time point
            - Equivalent to: ¬□¬φ
            - Example: ◇(success) - "eventually success"
            
        NEXT (X): In the next time point, φ holds
            - X φ is true iff φ is true in the next state
            - Example: X(alarm) - "next, the alarm sounds"
            
        UNTIL (U): φ holds until ψ becomes true
            - φ U ψ is true iff ψ eventually becomes true and φ holds continuously until then
            - Example: waiting U served - "waiting until served"
            
        SINCE (S): φ has been true since ψ was true
            - φ S ψ is true iff ψ was true at some past point and φ has held continuously since
            - Past-time operator (dual of Until)
            - Example: running S started - "running since started"
            
        YESTERDAY (Y): In the previous time point, φ held
            - Y φ is true iff φ was true in the previous state
            - Past-time operator (dual of Next)
            - Example: Y(open) - "yesterday, it was open"
    
    Equivalences:
        - ◇φ ≡ ¬□¬φ (eventually φ ≡ not always not φ)
        - □φ ≡ ¬◇¬φ (always φ ≡ not eventually not φ)
        - φ U ψ ≡ ψ ∨ (φ ∧ X(φ U ψ))
    """
    ALWAYS = "□"         # Always / Globally
    EVENTUALLY = "◇"     # Eventually / Finally
    NEXT = "X"           # Next
    UNTIL = "U"          # Until
    SINCE = "S"          # Since
    YESTERDAY = "Y"      # Yesterday / Previous


@dataclass
class State:
    """
    Represents a state at a particular time point.
    
    A state is a mapping from atomic propositions to boolean values,
    representing which propositions are true at that time point.
    
    Attributes:
        time: Time index (0, 1, 2, ...)
        valuations: Map from proposition names to boolean values
        metadata: Optional metadata about this state
    
    Examples:
        >>> state = State(time=0, valuations={'p': True, 'q': False})
        >>> state.evaluate('p')
        True
        >>> state.evaluate('q')
        False
    """
    time: int
    valuations: Dict[str, bool] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def evaluate(self, proposition: str) -> bool:
        """
        Evaluate an atomic proposition in this state.
        
        Args:
            proposition: Name of the proposition
            
        Returns:
            True if proposition holds in this state, False otherwise
        """
        return self.valuations.get(proposition, False)
    
    def __str__(self) -> str:
        return f"State(t={self.time}, {self.valuations})"


class TemporalFormula:
    """
    Represents a temporal formula (temporal operator applied to a base formula).
    
    A temporal formula applies a temporal operator to a base DCEC formula,
    enabling reasoning about time-dependent properties.
    
    Attributes:
        operator: The temporal operator (ALWAYS, EVENTUALLY, etc.)
        formula: The base formula (DCEC formula)
        formula2: Optional second formula (for binary operators like UNTIL)
    
    Examples:
        >>> from ipfs_datasets_py.logic.CEC.native.dcec_core import parse_dcec
        >>> p = parse_dcec("p")
        >>> # Always p
        >>> always_p = TemporalFormula(TemporalOperator.ALWAYS, p)
        >>> # Eventually p
        >>> eventually_p = TemporalFormula(TemporalOperator.EVENTUALLY, p)
        >>> # p Until q
        >>> q = parse_dcec("q")
        >>> p_until_q = TemporalFormula(TemporalOperator.UNTIL, p, q)
    """
    
    def __init__(
        self,
        operator: TemporalOperator,
        formula: Formula,
        formula2: Optional[Formula] = None
    ):
        """
        Initialize a temporal formula.
        
        Args:
            operator: Temporal operator to apply
            formula: Base formula (first argument)
            formula2: Optional second formula (for binary operators)
            
        Raises:
            ValidationError: If operator/formula combination is invalid
        """
        self.operator = operator
        self.formula = formula
        self.formula2 = formula2
        
        # Validate operator/formula combination
        self._validate()
    
    def _validate(self) -> None:
        """Validate operator/formula combination."""
        binary_ops = {TemporalOperator.UNTIL, TemporalOperator.SINCE}
        
        if self.operator in binary_ops:
            if self.formula2 is None:
                raise ValidationError(
                    f"Binary temporal operator {self.operator.value} requires two formulas"
                )
        else:
            if self.formula2 is not None:
                raise ValidationError(
                    f"Unary temporal operator {self.operator.value} takes only one formula"
                )
    
    def evaluate(self, time_sequence: List[State], current_time: int = 0) -> bool:
        """
        Evaluate temporal formula over a time sequence.
        
        This implements standard Linear Temporal Logic (LTL) semantics for
        temporal operators over discrete time sequences.
        
        Args:
            time_sequence: Sequence of states representing time evolution
            current_time: Current time index in the sequence (default: 0)
            
        Returns:
            True if formula holds at current_time, False otherwise
            
        Raises:
            ValidationError: If evaluation fails
        
        Examples:
            >>> states = [
            ...     State(0, {'p': True}),
            ...     State(1, {'p': True}),
            ...     State(2, {'p': True})
            ... ]
            >>> always_p = TemporalFormula(TemporalOperator.ALWAYS, parse_dcec("p"))
            >>> always_p.evaluate(states)
            True
        """
        if not time_sequence:
            raise ValidationError("Time sequence cannot be empty")
        
        if current_time < 0 or current_time >= len(time_sequence):
            raise ValidationError(f"Invalid current_time: {current_time}")
        
        try:
            if self.operator == TemporalOperator.ALWAYS:
                return self._evaluate_always(time_sequence, current_time)
            elif self.operator == TemporalOperator.EVENTUALLY:
                return self._evaluate_eventually(time_sequence, current_time)
            elif self.operator == TemporalOperator.NEXT:
                return self._evaluate_next(time_sequence, current_time)
            elif self.operator == TemporalOperator.UNTIL:
                return self._evaluate_until(time_sequence, current_time)
            elif self.operator == TemporalOperator.SINCE:
                return self._evaluate_since(time_sequence, current_time)
            elif self.operator == TemporalOperator.YESTERDAY:
                return self._evaluate_yesterday(time_sequence, current_time)
            else:
                raise ValidationError(f"Unknown temporal operator: {self.operator}")
        except Exception as e:
            logger.error(f"Temporal evaluation error: {e}")
            raise ValidationError(f"Temporal evaluation failed: {e}") from e
    
    def _evaluate_formula_at_state(self, formula: Formula, state: State) -> bool:
        """
        Evaluate a DCEC formula at a given state.
        
        This is a simplified evaluation that checks if atomic propositions
        hold in the state. Full DCEC formula evaluation would require
        integration with the theorem prover.
        
        Args:
            formula: DCEC formula to evaluate
            state: State to evaluate in
            
        Returns:
            True if formula holds in state, False otherwise
        """
        # Simplified evaluation: extract atomic proposition name
        formula_str = formula.to_string().strip()
        
        # Handle negation
        if formula_str.startswith('¬') or formula_str.startswith('~'):
            inner = formula_str[1:].strip()
            # Remove () if present (e.g., "P()" -> "P")
            if inner.endswith('()'):
                inner = inner[:-2]
            return not state.evaluate(inner)
        
        # Remove () if present for atomic formulas (e.g., "P()" -> "P")
        if formula_str.endswith('()'):
            formula_str = formula_str[:-2]
        
        # Evaluate atomic proposition
        return state.evaluate(formula_str)
    
    def _evaluate_always(self, time_sequence: List[State], current_time: int) -> bool:
        """□φ: φ holds at all future time points (including current)."""
        for i in range(current_time, len(time_sequence)):
            if not self._evaluate_formula_at_state(self.formula, time_sequence[i]):
                return False
        return True
    
    def _evaluate_eventually(self, time_sequence: List[State], current_time: int) -> bool:
        """◇φ: φ holds at some future time point (including current)."""
        for i in range(current_time, len(time_sequence)):
            if self._evaluate_formula_at_state(self.formula, time_sequence[i]):
                return True
        return False
    
    def _evaluate_next(self, time_sequence: List[State], current_time: int) -> bool:
        """X φ: φ holds in the next state."""
        next_time = current_time + 1
        if next_time >= len(time_sequence):
            # No next state - convention: return False
            return False
        return self._evaluate_formula_at_state(self.formula, time_sequence[next_time])
    
    def _evaluate_until(self, time_sequence: List[State], current_time: int) -> bool:
        """
        φ U ψ: φ holds continuously until ψ becomes true.
        
        Semantics: ψ must eventually become true, and φ must hold at all
        points before that (not including the point where ψ becomes true).
        """
        assert self.formula2 is not None, "Until requires two formulas"
        
        for i in range(current_time, len(time_sequence)):
            # Check if ψ holds
            if self._evaluate_formula_at_state(self.formula2, time_sequence[i]):
                # ψ holds - check that φ held at all previous points
                for j in range(current_time, i):
                    if not self._evaluate_formula_at_state(self.formula, time_sequence[j]):
                        return False
                return True
            # ψ doesn't hold yet - φ must hold
            if not self._evaluate_formula_at_state(self.formula, time_sequence[i]):
                return False
        
        # Reached end without ψ becoming true
        return False
    
    def _evaluate_since(self, time_sequence: List[State], current_time: int) -> bool:
        """
        φ S ψ: φ has held continuously since ψ was true.
        
        Past-time operator (dual of Until).
        Semantics: ψ was true at some past point, and φ has held continuously since.
        """
        assert self.formula2 is not None, "Since requires two formulas"
        
        # Look backward from current time
        for i in range(current_time, -1, -1):
            # Check if ψ holds at this point
            if self._evaluate_formula_at_state(self.formula2, time_sequence[i]):
                # ψ holds - check that φ held at all points after this
                for j in range(i + 1, current_time + 1):
                    if not self._evaluate_formula_at_state(self.formula, time_sequence[j]):
                        return False
                return True
            # ψ doesn't hold yet - φ must hold at current point
            if i < current_time and not self._evaluate_formula_at_state(self.formula, time_sequence[i]):
                return False
        
        # No point where ψ was true
        return False
    
    def _evaluate_yesterday(self, time_sequence: List[State], current_time: int) -> bool:
        """Y φ: φ held in the previous state."""
        if current_time == 0:
            # No previous state - convention: return False
            return False
        prev_time = current_time - 1
        return self._evaluate_formula_at_state(self.formula, time_sequence[prev_time])
    
    def to_string(self) -> str:
        """Convert temporal formula to string representation."""
        if self.formula2 is None:
            return f"{self.operator.value}({self.formula.to_string()})"
        else:
            return f"({self.formula.to_string()} {self.operator.value} {self.formula2.to_string()})"
    
    def __str__(self) -> str:
        return self.to_string()
    
    def __repr__(self) -> str:
        if self.formula2 is None:
            return f"TemporalFormula({self.operator}, {repr(self.formula)})"
        else:
            return f"TemporalFormula({self.operator}, {repr(self.formula)}, {repr(self.formula2)})"


# Convenience functions for creating temporal formulas

def always(formula: Formula) -> TemporalFormula:
    """Create □φ (always φ) temporal formula."""
    return TemporalFormula(TemporalOperator.ALWAYS, formula)


def eventually(formula: Formula) -> TemporalFormula:
    """Create ◇φ (eventually φ) temporal formula."""
    return TemporalFormula(TemporalOperator.EVENTUALLY, formula)


def next_op(formula: Formula) -> TemporalFormula:
    """Create X φ (next φ) temporal formula."""
    return TemporalFormula(TemporalOperator.NEXT, formula)


def until(formula1: Formula, formula2: Formula) -> TemporalFormula:
    """Create φ U ψ (φ until ψ) temporal formula."""
    return TemporalFormula(TemporalOperator.UNTIL, formula1, formula2)


def since(formula1: Formula, formula2: Formula) -> TemporalFormula:
    """Create φ S ψ (φ since ψ) temporal formula."""
    return TemporalFormula(TemporalOperator.SINCE, formula1, formula2)


def yesterday(formula: Formula) -> TemporalFormula:
    """Create Y φ (yesterday φ) temporal formula."""
    return TemporalFormula(TemporalOperator.YESTERDAY, formula)
