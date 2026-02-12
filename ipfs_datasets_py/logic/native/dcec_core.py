"""
Native Python 3 implementation of Deontic Cognitive Event Calculus (DCEC).

This module provides a pure Python 3 implementation of DCEC logic system,
replacing the Python 2 based DCEC_Library submodule.
"""

from enum import Enum
from typing import Dict, List, Optional, Any, Set, Union
from dataclasses import dataclass, field
import logging
from abc import ABC, abstractmethod

try:
    from beartype import beartype
except ImportError:
    def beartype(func):
        return func

logger = logging.getLogger(__name__)


class DeonticOperator(Enum):
    """Deontic operators for normative reasoning."""
    OBLIGATION = "O"         # O(φ) - it is obligatory that φ
    PERMISSION = "P"         # P(φ) - it is permitted that φ
    PROHIBITION = "F"        # F(φ) - it is forbidden that φ
    SUPEREROGATION = "S"     # S(φ) - it is supererogatory that φ
    RIGHT = "R"              # R(φ) - φ is a right
    LIBERTY = "L"            # L(φ) - φ is a liberty/privilege
    POWER = "POW"            # POW(φ) - power to bring about φ
    IMMUNITY = "IMM"         # IMM(φ) - immunity from φ


class CognitiveOperator(Enum):
    """Cognitive operators for mental state reasoning."""
    BELIEF = "B"             # B(agent, φ) - agent believes φ
    KNOWLEDGE = "K"          # K(agent, φ) - agent knows φ
    INTENTION = "I"          # I(agent, φ) - agent intends φ
    DESIRE = "D"             # D(agent, φ) - agent desires φ
    GOAL = "G"               # G(agent, φ) - agent has goal φ


class LogicalConnective(Enum):
    """Logical connectives for building complex formulas."""
    AND = "∧"
    OR = "∨"
    NOT = "¬"
    IMPLIES = "→"
    BICONDITIONAL = "↔"
    EXISTS = "∃"
    FORALL = "∀"


class TemporalOperator(Enum):
    """Temporal operators for time-dependent reasoning."""
    ALWAYS = "□"             # Always/necessarily
    EVENTUALLY = "◊"         # Eventually/possibly
    NEXT = "X"               # Next time point
    UNTIL = "U"              # Until
    SINCE = "S"              # Since


@dataclass
class Sort:
    """Represents a type/sort in the logic system."""
    name: str
    parent: Optional['Sort'] = None
    
    def is_subtype_of(self, other: 'Sort') -> bool:
        """Check if this sort is a subtype of another."""
        if self == other:
            return True
        if self.parent is None:
            return False
        return self.parent.is_subtype_of(other)


@dataclass
class Variable:
    """Represents a logical variable."""
    name: str
    sort: Sort
    
    def __str__(self) -> str:
        return f"{self.name}:{self.sort.name}"


@dataclass
class Function:
    """Represents a function symbol."""
    name: str
    argument_sorts: List[Sort]
    return_sort: Sort
    
    def arity(self) -> int:
        """Return the arity (number of arguments) of the function."""
        return len(self.argument_sorts)
    
    def __str__(self) -> str:
        args = ", ".join(s.name for s in self.argument_sorts)
        return f"{self.name}({args}) -> {self.return_sort.name}"


@dataclass
class Predicate:
    """Represents a predicate symbol."""
    name: str
    argument_sorts: List[Sort]
    
    def arity(self) -> int:
        """Return the arity (number of arguments) of the predicate."""
        return len(self.argument_sorts)
    
    def __str__(self) -> str:
        args = ", ".join(s.name for s in self.argument_sorts)
        return f"{self.name}({args})"


class Term(ABC):
    """Abstract base class for terms in DCEC."""
    
    @abstractmethod
    def get_sort(self) -> Sort:
        """Get the sort of this term."""
        pass
    
    @abstractmethod
    def get_free_variables(self) -> Set[Variable]:
        """Get all free variables in this term."""
        pass
    
    @abstractmethod
    def substitute(self, var: Variable, term: 'Term') -> 'Term':
        """Substitute a variable with a term."""
        pass


@dataclass
class VariableTerm(Term):
    """A term that is a variable."""
    variable: Variable
    
    def get_sort(self) -> Sort:
        return self.variable.sort
    
    def get_free_variables(self) -> Set[Variable]:
        return {self.variable}
    
    def substitute(self, var: Variable, term: Term) -> Term:
        if self.variable == var:
            return term
        return self
    
    def __str__(self) -> str:
        return str(self.variable)


@dataclass
class FunctionTerm(Term):
    """A term that is a function application."""
    function: Function
    arguments: List[Term]
    
    def __post_init__(self):
        if len(self.arguments) != self.function.arity():
            raise ValueError(f"Function {self.function.name} expects {self.function.arity()} arguments, got {len(self.arguments)}")
    
    def get_sort(self) -> Sort:
        return self.function.return_sort
    
    def get_free_variables(self) -> Set[Variable]:
        result = set()
        for arg in self.arguments:
            result.update(arg.get_free_variables())
        return result
    
    def substitute(self, var: Variable, term: Term) -> Term:
        new_args = [arg.substitute(var, term) for arg in self.arguments]
        return FunctionTerm(self.function, new_args)
    
    def __str__(self) -> str:
        args_str = ", ".join(str(arg) for arg in self.arguments)
        return f"{self.function.name}({args_str})"


class Formula(ABC):
    """Abstract base class for formulas in DCEC."""
    
    @abstractmethod
    def get_free_variables(self) -> Set[Variable]:
        """Get all free variables in this formula."""
        pass
    
    @abstractmethod
    def substitute(self, var: Variable, term: Term) -> 'Formula':
        """Substitute a variable with a term."""
        pass
    
    @abstractmethod
    def to_string(self) -> str:
        """Convert formula to string representation."""
        pass


@dataclass
class AtomicFormula(Formula):
    """An atomic formula (predicate application)."""
    predicate: Predicate
    arguments: List[Term]
    
    def __post_init__(self):
        if len(self.arguments) != self.predicate.arity():
            raise ValueError(f"Predicate {self.predicate.name} expects {self.predicate.arity()} arguments, got {len(self.arguments)}")
    
    def get_free_variables(self) -> Set[Variable]:
        result = set()
        for arg in self.arguments:
            result.update(arg.get_free_variables())
        return result
    
    def substitute(self, var: Variable, term: Term) -> Formula:
        new_args = [arg.substitute(var, term) for arg in self.arguments]
        return AtomicFormula(self.predicate, new_args)
    
    def to_string(self) -> str:
        args_str = ", ".join(str(arg) for arg in self.arguments)
        return f"{self.predicate.name}({args_str})"
    
    def __str__(self) -> str:
        return self.to_string()


@dataclass
class DeonticFormula(Formula):
    """A formula with a deontic operator."""
    operator: DeonticOperator
    formula: Formula
    agent: Optional[Term] = None  # For agent-relative deontic operators
    
    def get_free_variables(self) -> Set[Variable]:
        result = self.formula.get_free_variables()
        if self.agent:
            result.update(self.agent.get_free_variables())
        return result
    
    def substitute(self, var: Variable, term: Term) -> Formula:
        new_formula = self.formula.substitute(var, term)
        new_agent = self.agent.substitute(var, term) if self.agent else None
        return DeonticFormula(self.operator, new_formula, new_agent)
    
    def to_string(self) -> str:
        if self.agent:
            return f"{self.operator.value}[{self.agent}]({self.formula.to_string()})"
        return f"{self.operator.value}({self.formula.to_string()})"
    
    def __str__(self) -> str:
        return self.to_string()


@dataclass
class CognitiveFormula(Formula):
    """A formula with a cognitive operator."""
    operator: CognitiveOperator
    agent: Term
    formula: Formula
    
    def get_free_variables(self) -> Set[Variable]:
        result = self.agent.get_free_variables()
        result.update(self.formula.get_free_variables())
        return result
    
    def substitute(self, var: Variable, term: Term) -> Formula:
        new_agent = self.agent.substitute(var, term)
        new_formula = self.formula.substitute(var, term)
        return CognitiveFormula(self.operator, new_agent, new_formula)
    
    def to_string(self) -> str:
        return f"{self.operator.value}({self.agent}, {self.formula.to_string()})"
    
    def __str__(self) -> str:
        return self.to_string()


@dataclass
class TemporalFormula(Formula):
    """A formula with a temporal operator."""
    operator: TemporalOperator
    formula: Formula
    time: Optional[Term] = None  # For explicit time points
    
    def get_free_variables(self) -> Set[Variable]:
        result = self.formula.get_free_variables()
        if self.time:
            result.update(self.time.get_free_variables())
        return result
    
    def substitute(self, var: Variable, term: Term) -> Formula:
        new_formula = self.formula.substitute(var, term)
        new_time = self.time.substitute(var, term) if self.time else None
        return TemporalFormula(self.operator, new_formula, new_time)
    
    def to_string(self) -> str:
        if self.time:
            return f"{self.operator.value}[{self.time}]({self.formula.to_string()})"
        return f"{self.operator.value}({self.formula.to_string()})"
    
    def __str__(self) -> str:
        return self.to_string()


@dataclass
class ConnectiveFormula(Formula):
    """A formula built from logical connectives."""
    connective: LogicalConnective
    formulas: List[Formula]
    
    def __post_init__(self):
        if self.connective == LogicalConnective.NOT and len(self.formulas) != 1:
            raise ValueError("NOT connective requires exactly 1 formula")
        elif self.connective in [LogicalConnective.AND, LogicalConnective.OR] and len(self.formulas) < 2:
            raise ValueError(f"{self.connective.name} connective requires at least 2 formulas")
        elif self.connective in [LogicalConnective.IMPLIES, LogicalConnective.BICONDITIONAL] and len(self.formulas) != 2:
            raise ValueError(f"{self.connective.name} connective requires exactly 2 formulas")
    
    def get_free_variables(self) -> Set[Variable]:
        result = set()
        for formula in self.formulas:
            result.update(formula.get_free_variables())
        return result
    
    def substitute(self, var: Variable, term: Term) -> Formula:
        new_formulas = [f.substitute(var, term) for f in self.formulas]
        return ConnectiveFormula(self.connective, new_formulas)
    
    def to_string(self) -> str:
        if self.connective == LogicalConnective.NOT:
            return f"¬({self.formulas[0].to_string()})"
        elif self.connective in [LogicalConnective.IMPLIES, LogicalConnective.BICONDITIONAL]:
            return f"({self.formulas[0].to_string()} {self.connective.value} {self.formulas[1].to_string()})"
        else:
            formula_strs = [f.to_string() for f in self.formulas]
            return f"({f' {self.connective.value} '.join(formula_strs)})"
    
    def __str__(self) -> str:
        return self.to_string()


@dataclass
class QuantifiedFormula(Formula):
    """A formula with quantifiers."""
    quantifier: LogicalConnective  # EXISTS or FORALL
    variable: Variable
    formula: Formula
    
    def __post_init__(self):
        if self.quantifier not in [LogicalConnective.EXISTS, LogicalConnective.FORALL]:
            raise ValueError(f"Invalid quantifier: {self.quantifier}")
    
    def get_free_variables(self) -> Set[Variable]:
        result = self.formula.get_free_variables()
        result.discard(self.variable)  # Bound variable is not free
        return result
    
    def substitute(self, var: Variable, term: Term) -> Formula:
        if var == self.variable:
            # Don't substitute bound variable
            return self
        # Check for variable capture
        if self.variable in term.get_free_variables():
            # Would need alpha-conversion here in a complete implementation
            logger.warning("Variable capture detected in substitution")
        new_formula = self.formula.substitute(var, term)
        return QuantifiedFormula(self.quantifier, self.variable, new_formula)
    
    def to_string(self) -> str:
        return f"{self.quantifier.value}{self.variable}({self.formula.to_string()})"
    
    def __str__(self) -> str:
        return self.to_string()


@dataclass
class DCECStatement:
    """Represents a complete DCEC statement."""
    formula: Formula
    label: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __str__(self) -> str:
        if self.label:
            return f"{self.label}: {self.formula.to_string()}"
        return self.formula.to_string()
