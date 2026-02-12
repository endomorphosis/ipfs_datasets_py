"""
Temporal Deontic First-Order Logic (TDFOL) Core Module

This module provides a unified representation for Temporal Deontic First-Order Logic,
combining three logical systems:
- First-Order Logic (FOL): predicates, quantifiers, variables
- Deontic Logic: obligations (O), permissions (P), prohibitions (F)
- Temporal Logic: temporal operators (□, ◊, X, U, S)

The TDFOL system enables reasoning about:
- What must/may/must-not happen (deontic)
- When things happen (temporal)
- About what things (first-order)

Example TDFOL formulas:
- O(□(Agent(x) → Responsible(x))): "It is obligatory that always, if x is an agent, then x is responsible"
- P(◊(Action(x) ∧ Legal(x))): "It is permitted that eventually, x is an action and x is legal"
- ∀x(Person(x) → O(X(Report(x)))): "For all x, if x is a person, it is obligatory that next, x reports"
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger(__name__)


# ============================================================================
# Enumerations
# ============================================================================


class LogicOperator(Enum):
    """Logical operators for propositional and first-order logic."""
    
    AND = "∧"           # Conjunction
    OR = "∨"            # Disjunction
    NOT = "¬"           # Negation
    IMPLIES = "→"       # Implication
    IFF = "↔"           # Bi-implication (if and only if)
    XOR = "⊕"           # Exclusive or


class Quantifier(Enum):
    """First-order logic quantifiers."""
    
    FORALL = "∀"        # Universal quantifier
    EXISTS = "∃"        # Existential quantifier


class DeonticOperator(Enum):
    """Deontic logic operators for normative reasoning."""
    
    OBLIGATION = "O"     # Obligatory (must)
    PERMISSION = "P"     # Permissible (may)
    PROHIBITION = "F"    # Forbidden (must not)


class TemporalOperator(Enum):
    """Temporal logic operators for reasoning about time."""
    
    ALWAYS = "□"         # Always (necessarily)
    EVENTUALLY = "◊"     # Eventually (possibly)
    NEXT = "X"           # Next time
    UNTIL = "U"          # Until
    SINCE = "S"          # Since
    WEAK_UNTIL = "W"     # Weak until
    RELEASE = "R"        # Release


class Sort(Enum):
    """Types/sorts for terms in first-order logic."""
    
    AGENT = "Agent"
    ACTION = "Action"
    EVENT = "Event"
    TIME = "Time"
    PROPOSITION = "Proposition"
    OBJECT = "Object"
    STATE = "State"
    CONDITION = "Condition"


# ============================================================================
# Abstract Base Classes
# ============================================================================


class TDFOLNode(ABC):
    """Abstract base class for all TDFOL syntax nodes."""
    
    @abstractmethod
    def to_string(self, pretty: bool = False) -> str:
        """Convert node to string representation."""
        pass
    
    @abstractmethod
    def get_free_variables(self) -> Set[str]:
        """Get all free variables in this node."""
        pass
    
    @abstractmethod
    def substitute(self, var: str, term: 'Term') -> 'TDFOLNode':
        """Substitute term for variable throughout this node."""
        pass
    
    def __str__(self) -> str:
        return self.to_string()


# ============================================================================
# Terms
# ============================================================================


class Term(TDFOLNode):
    """Abstract base class for terms."""
    
    @abstractmethod
    def get_variables(self) -> Set[str]:
        """Get all variables in this term."""
        pass


@dataclass(frozen=True)
class Variable(Term):
    """Variable term (e.g., x, y, agent)."""
    
    name: str
    sort: Optional[Sort] = None
    
    def to_string(self, pretty: bool = False) -> str:
        if pretty and self.sort:
            return f"{self.name}:{self.sort.value}"
        return self.name
    
    def get_free_variables(self) -> Set[str]:
        return {self.name}
    
    def get_variables(self) -> Set[str]:
        return {self.name}
    
    def substitute(self, var: str, term: Term) -> Term:
        if self.name == var:
            return term
        return self


@dataclass(frozen=True)
class Constant(Term):
    """Constant term (e.g., john, true, 42)."""
    
    name: str
    sort: Optional[Sort] = None
    
    def to_string(self, pretty: bool = False) -> str:
        return self.name
    
    def get_free_variables(self) -> Set[str]:
        return set()
    
    def get_variables(self) -> Set[str]:
        return set()
    
    def substitute(self, var: str, term: Term) -> Term:
        return self


@dataclass(frozen=True)
class FunctionApplication(Term):
    """Function application term (e.g., f(x), successor(n))."""
    
    function_name: str
    arguments: Tuple[Term, ...]
    sort: Optional[Sort] = None
    
    def to_string(self, pretty: bool = False) -> str:
        args_str = ", ".join(arg.to_string(pretty) for arg in self.arguments)
        return f"{self.function_name}({args_str})"
    
    def get_free_variables(self) -> Set[str]:
        result = set()
        for arg in self.arguments:
            result.update(arg.get_free_variables())
        return result
    
    def get_variables(self) -> Set[str]:
        result = set()
        for arg in self.arguments:
            result.update(arg.get_variables())
        return result
    
    def substitute(self, var: str, term: Term) -> Term:
        new_args = tuple(arg.substitute(var, term) for arg in self.arguments)
        return FunctionApplication(self.function_name, new_args, self.sort)


# ============================================================================
# Formulas
# ============================================================================


@dataclass(frozen=True)
class Formula(TDFOLNode):
    """Abstract base class for formulas."""
    
    @abstractmethod
    def get_predicates(self) -> Set[str]:
        """Get all predicate names in this formula."""
        pass


@dataclass(frozen=True)
class Predicate(Formula):
    """Predicate formula (e.g., Person(x), Greater(x, y))."""
    
    name: str
    arguments: Tuple[Term, ...]
    
    def to_string(self, pretty: bool = False) -> str:
        if not self.arguments:
            return self.name
        args_str = ", ".join(arg.to_string(pretty) for arg in self.arguments)
        return f"{self.name}({args_str})"
    
    def get_free_variables(self) -> Set[str]:
        result = set()
        for arg in self.arguments:
            result.update(arg.get_free_variables())
        return result
    
    def get_predicates(self) -> Set[str]:
        return {self.name}
    
    def substitute(self, var: str, term: Term) -> Formula:
        new_args = tuple(arg.substitute(var, term) for arg in self.arguments)
        return Predicate(self.name, new_args)


@dataclass(frozen=True)
class BinaryFormula(Formula):
    """Binary formula with logical operator (e.g., P ∧ Q, P → Q)."""
    
    operator: LogicOperator
    left: Formula
    right: Formula
    
    def to_string(self, pretty: bool = False) -> str:
        if pretty:
            return f"({self.left.to_string(True)} {self.operator.value} {self.right.to_string(True)})"
        return f"({self.operator.value} {self.left.to_string()} {self.right.to_string()})"
    
    def get_free_variables(self) -> Set[str]:
        return self.left.get_free_variables() | self.right.get_free_variables()
    
    def get_predicates(self) -> Set[str]:
        return self.left.get_predicates() | self.right.get_predicates()
    
    def substitute(self, var: str, term: Term) -> Formula:
        return BinaryFormula(
            self.operator,
            self.left.substitute(var, term),
            self.right.substitute(var, term)
        )


@dataclass(frozen=True)
class UnaryFormula(Formula):
    """Unary formula with negation (e.g., ¬P)."""
    
    operator: LogicOperator
    formula: Formula
    
    def __post_init__(self):
        if self.operator != LogicOperator.NOT:
            raise ValueError("UnaryFormula only supports NOT operator")
    
    def to_string(self, pretty: bool = False) -> str:
        return f"{self.operator.value}{self.formula.to_string(pretty)}"
    
    def get_free_variables(self) -> Set[str]:
        return self.formula.get_free_variables()
    
    def get_predicates(self) -> Set[str]:
        return self.formula.get_predicates()
    
    def substitute(self, var: str, term: Term) -> Formula:
        return UnaryFormula(self.operator, self.formula.substitute(var, term))


@dataclass(frozen=True)
class QuantifiedFormula(Formula):
    """Quantified formula (e.g., ∀x.P(x), ∃y.Q(y))."""
    
    quantifier: Quantifier
    variable: Variable
    formula: Formula
    
    def to_string(self, pretty: bool = False) -> str:
        var_str = self.variable.to_string(pretty)
        return f"{self.quantifier.value}{var_str}.{self.formula.to_string(pretty)}"
    
    def get_free_variables(self) -> Set[str]:
        bound_vars = self.formula.get_free_variables()
        bound_vars.discard(self.variable.name)
        return bound_vars
    
    def get_predicates(self) -> Set[str]:
        return self.formula.get_predicates()
    
    def substitute(self, var: str, term: Term) -> Formula:
        if var == self.variable.name:
            # Don't substitute for bound variable
            return self
        return QuantifiedFormula(
            self.quantifier,
            self.variable,
            self.formula.substitute(var, term)
        )


@dataclass(frozen=True)
class DeonticFormula(Formula):
    """Deontic formula (e.g., O(P), P(Q), F(R))."""
    
    operator: DeonticOperator
    formula: Formula
    agent: Optional[Term] = None
    context: Optional[str] = None
    
    def to_string(self, pretty: bool = False) -> str:
        base = f"{self.operator.value}({self.formula.to_string(pretty)})"
        if pretty and self.agent:
            base = f"{self.operator.value}_{self.agent.to_string(pretty)}({self.formula.to_string(pretty)})"
        return base
    
    def get_free_variables(self) -> Set[str]:
        result = self.formula.get_free_variables()
        if self.agent:
            result.update(self.agent.get_free_variables())
        return result
    
    def get_predicates(self) -> Set[str]:
        return self.formula.get_predicates()
    
    def substitute(self, var: str, term: Term) -> Formula:
        new_agent = self.agent.substitute(var, term) if self.agent else None
        return DeonticFormula(
            self.operator,
            self.formula.substitute(var, term),
            new_agent,
            self.context
        )


@dataclass(frozen=True)
class TemporalFormula(Formula):
    """Temporal formula (e.g., □P, ◊Q, X(R))."""
    
    operator: TemporalOperator
    formula: Formula
    time_bound: Optional[int] = None  # Optional bound for bounded temporal operators
    
    def to_string(self, pretty: bool = False) -> str:
        base = f"{self.operator.value}({self.formula.to_string(pretty)})"
        if pretty and self.time_bound is not None:
            base = f"{self.operator.value}[{self.time_bound}]({self.formula.to_string(pretty)})"
        return base
    
    def get_free_variables(self) -> Set[str]:
        return self.formula.get_free_variables()
    
    def get_predicates(self) -> Set[str]:
        return self.formula.get_predicates()
    
    def substitute(self, var: str, term: Term) -> Formula:
        return TemporalFormula(
            self.operator,
            self.formula.substitute(var, term),
            self.time_bound
        )


@dataclass(frozen=True)
class BinaryTemporalFormula(Formula):
    """Binary temporal formula (e.g., P U Q, P S Q)."""
    
    operator: TemporalOperator
    left: Formula
    right: Formula
    
    def __post_init__(self):
        if self.operator not in [TemporalOperator.UNTIL, TemporalOperator.SINCE, 
                                  TemporalOperator.WEAK_UNTIL, TemporalOperator.RELEASE]:
            raise ValueError(f"BinaryTemporalFormula only supports binary temporal operators")
    
    def to_string(self, pretty: bool = False) -> str:
        return f"({self.left.to_string(pretty)} {self.operator.value} {self.right.to_string(pretty)})"
    
    def get_free_variables(self) -> Set[str]:
        return self.left.get_free_variables() | self.right.get_free_variables()
    
    def get_predicates(self) -> Set[str]:
        return self.left.get_predicates() | self.right.get_predicates()
    
    def substitute(self, var: str, term: Term) -> Formula:
        return BinaryTemporalFormula(
            self.operator,
            self.left.substitute(var, term),
            self.right.substitute(var, term)
        )


# ============================================================================
# Knowledge Base
# ============================================================================


@dataclass
class TDFOLKnowledgeBase:
    """Knowledge base for TDFOL formulas with theorem proving support."""
    
    axioms: List[Formula] = field(default_factory=list)
    theorems: List[Formula] = field(default_factory=list)
    definitions: Dict[str, Formula] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_axiom(self, formula: Formula, name: Optional[str] = None) -> None:
        """Add an axiom to the knowledge base."""
        self.axioms.append(formula)
        if name:
            self.metadata[name] = {"type": "axiom", "formula": formula}
        logger.debug(f"Added axiom: {formula}")
    
    def add_theorem(self, formula: Formula, name: Optional[str] = None) -> None:
        """Add a theorem to the knowledge base."""
        self.theorems.append(formula)
        if name:
            self.metadata[name] = {"type": "theorem", "formula": formula}
        logger.debug(f"Added theorem: {formula}")
    
    def add_definition(self, name: str, formula: Formula) -> None:
        """Add a definition to the knowledge base."""
        self.definitions[name] = formula
        logger.debug(f"Added definition {name}: {formula}")
    
    def get_all_formulas(self) -> List[Formula]:
        """Get all formulas (axioms + theorems)."""
        return self.axioms + self.theorems
    
    def get_predicates(self) -> Set[str]:
        """Get all predicate names used in the knowledge base."""
        result = set()
        for formula in self.get_all_formulas():
            result.update(formula.get_predicates())
        return result
    
    def get_free_variables(self) -> Set[str]:
        """Get all free variables in the knowledge base."""
        result = set()
        for formula in self.get_all_formulas():
            result.update(formula.get_free_variables())
        return result


# ============================================================================
# Utility Functions
# ============================================================================


def create_implication(antecedent: Formula, consequent: Formula) -> BinaryFormula:
    """Create an implication formula: antecedent → consequent."""
    return BinaryFormula(LogicOperator.IMPLIES, antecedent, consequent)


def create_conjunction(*formulas: Formula) -> Formula:
    """Create a conjunction of formulas: F1 ∧ F2 ∧ ... ∧ Fn."""
    if not formulas:
        raise ValueError("Cannot create conjunction of zero formulas")
    if len(formulas) == 1:
        return formulas[0]
    result = formulas[0]
    for formula in formulas[1:]:
        result = BinaryFormula(LogicOperator.AND, result, formula)
    return result


def create_disjunction(*formulas: Formula) -> Formula:
    """Create a disjunction of formulas: F1 ∨ F2 ∨ ... ∨ Fn."""
    if not formulas:
        raise ValueError("Cannot create disjunction of zero formulas")
    if len(formulas) == 1:
        return formulas[0]
    result = formulas[0]
    for formula in formulas[1:]:
        result = BinaryFormula(LogicOperator.OR, result, formula)
    return result


def create_negation(formula: Formula) -> UnaryFormula:
    """Create a negation formula: ¬F."""
    return UnaryFormula(LogicOperator.NOT, formula)


def create_universal(variable: Variable, formula: Formula) -> QuantifiedFormula:
    """Create a universal quantification: ∀x.F."""
    return QuantifiedFormula(Quantifier.FORALL, variable, formula)


def create_existential(variable: Variable, formula: Formula) -> QuantifiedFormula:
    """Create an existential quantification: ∃x.F."""
    return QuantifiedFormula(Quantifier.EXISTS, variable, formula)


def create_obligation(formula: Formula, agent: Optional[Term] = None) -> DeonticFormula:
    """Create an obligation: O(F)."""
    return DeonticFormula(DeonticOperator.OBLIGATION, formula, agent)


def create_permission(formula: Formula, agent: Optional[Term] = None) -> DeonticFormula:
    """Create a permission: P(F)."""
    return DeonticFormula(DeonticOperator.PERMISSION, formula, agent)


def create_prohibition(formula: Formula, agent: Optional[Term] = None) -> DeonticFormula:
    """Create a prohibition: F(F)."""
    return DeonticFormula(DeonticOperator.PROHIBITION, formula, agent)


def create_always(formula: Formula) -> TemporalFormula:
    """Create an always formula: □F."""
    return TemporalFormula(TemporalOperator.ALWAYS, formula)


def create_eventually(formula: Formula) -> TemporalFormula:
    """Create an eventually formula: ◊F."""
    return TemporalFormula(TemporalOperator.EVENTUALLY, formula)


def create_next(formula: Formula) -> TemporalFormula:
    """Create a next formula: XF."""
    return TemporalFormula(TemporalOperator.NEXT, formula)


def create_until(left: Formula, right: Formula) -> BinaryTemporalFormula:
    """Create an until formula: F1 U F2."""
    return BinaryTemporalFormula(TemporalOperator.UNTIL, left, right)
