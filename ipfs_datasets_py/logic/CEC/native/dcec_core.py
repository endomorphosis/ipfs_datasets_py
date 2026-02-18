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

from .exceptions import ValidationError

try:
    from beartype import beartype
except ImportError:
    from typing import TypeVar, Callable, Any
    F = TypeVar('F', bound=Callable[..., Any])
    def beartype(func: F) -> F:
        return func

logger = logging.getLogger(__name__)


class DeonticOperator(Enum):
    """
    Deontic operators for normative reasoning in DCEC.
    
    Deontic logic concerns normative concepts such as obligation, permission, and prohibition.
    These operators enable reasoning about what ought to be, what is permitted, and what is forbidden.
    
    Operators:
        OBLIGATION (O): Represents that something is obligatory
            - O(φ) means "it is obligatory that φ"
            - Example: O(pay_taxes) - "it is obligatory to pay taxes"
        
        PERMISSION (P): Represents that something is permitted
            - P(φ) means "it is permitted that φ"  
            - Example: P(drive_car) - "it is permitted to drive a car"
        
        PROHIBITION (F): Represents that something is forbidden
            - F(φ) means "it is forbidden that φ"
            - Equivalent to O(¬φ) - obligation not to do φ
            - Example: F(steal) - "it is forbidden to steal"
        
        SUPEREROGATION (S): Represents that something is beyond obligation
            - S(φ) means "it is supererogatory that φ"
            - Actions that are good but not obligatory
            - Example: S(donate_to_charity) - "donating to charity is supererogatory"
        
        RIGHT (R): Represents a right
            - R(φ) means "φ is a right"
            - Example: R(free_speech) - "free speech is a right"
        
        LIBERTY (L): Represents a liberty or privilege
            - L(φ) means "φ is a liberty/privilege"
            - Example: L(choose_religion) - "choosing religion is a liberty"
        
        POWER (POW): Represents power to bring about something
            - POW(φ) means "power to bring about φ"
            - Example: POW(sign_contract) - "power to sign a contract"
        
        IMMUNITY (IMM): Represents immunity from something
            - IMM(φ) means "immunity from φ"
            - Example: IMM(search_without_warrant) - "immunity from search without warrant"
    
    Examples:
        >>> from ipfs_datasets_py.logic.CEC.native.dcec_core import DeonticOperator
        >>> op = DeonticOperator.OBLIGATION
        >>> print(op.value)
        'O'
        >>> op = DeonticOperator.PERMISSION
        >>> print(op.value)
        'P'
    
    Notes:
        - Deontic operators can be combined with temporal operators for time-dependent norms
        - Common relationships: F(φ) ≡ O(¬φ) (forbidden ≡ obligatory not)
        - Permission is typically the dual of obligation: P(φ) ≡ ¬O(¬φ)
    """
    OBLIGATION = "O"         # O(φ) - it is obligatory that φ
    PERMISSION = "P"         # P(φ) - it is permitted that φ
    PROHIBITION = "F"        # F(φ) - it is forbidden that φ
    SUPEREROGATION = "S"     # S(φ) - it is supererogatory that φ
    RIGHT = "R"              # R(φ) - φ is a right
    LIBERTY = "L"            # L(φ) - φ is a liberty/privilege
    POWER = "POW"            # POW(φ) - power to bring about φ
    IMMUNITY = "IMM"         # IMM(φ) - immunity from φ


class CognitiveOperator(Enum):
    """
    Cognitive operators for mental state reasoning in DCEC.
    
    Cognitive operators enable reasoning about agents' mental states including beliefs,
    knowledge, intentions, desires, and goals. These are essential for modeling agents'
    internal states and reasoning about their behavior.
    
    Operators:
        BELIEF (B): Represents that an agent believes something
            - B(agent, φ) means "agent believes φ"
            - Beliefs may be false (agents can have incorrect beliefs)
            - Example: B(john, "it will rain") - "John believes it will rain"
        
        KNOWLEDGE (K): Represents that an agent knows something
            - K(agent, φ) means "agent knows φ"
            - Knowledge implies truth (K(agent, φ) → φ)
            - Example: K(mary, "2+2=4") - "Mary knows that 2+2=4"
        
        INTENTION (I): Represents that an agent intends to do something
            - I(agent, φ) means "agent intends φ"
            - Intentions are directed toward future actions
            - Example: I(alice, "buy groceries") - "Alice intends to buy groceries"
        
        DESIRE (D): Represents that an agent desires something
            - D(agent, φ) means "agent desires φ"
            - Desires may conflict and don't always lead to action
            - Example: D(bob, "eat cake") - "Bob desires to eat cake"
        
        GOAL (G): Represents that an agent has a goal
            - G(agent, φ) means "agent has goal φ"
            - Goals are persistent states the agent wants to achieve
            - Example: G(company, "increase profit") - "Company has goal to increase profit"
    
    Args (when used in formulas):
        agent (Term): The agent whose mental state is being represented
        formula (Formula): The content of the mental state
    
    Examples:
        >>> from ipfs_datasets_py.logic.CEC.native.dcec_core import CognitiveOperator, CognitiveFormula
        >>> op = CognitiveOperator.BELIEF
        >>> print(op.value)
        'B'
        >>> # Creating a cognitive formula (see CognitiveFormula class for full example)
        >>> # belief_formula = CognitiveFormula(CognitiveOperator.BELIEF, agent_term, content_formula)
    
    Notes:
        - Knowledge is typically treated as justified true belief (K → B and K → truth)
        - Beliefs and desires can combine to form intentions (BDI model)
        - Agents can have nested beliefs: B(agent1, B(agent2, φ))
        - Cognitive operators enable multi-agent reasoning and theory of mind
    """
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


@dataclass(frozen=True)
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


@dataclass(frozen=True)
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
    
    def __post_init__(self) -> None:
        if len(self.arguments) != self.function.arity():
            raise ValidationError(
                f"Function arity mismatch for '{self.function.name}'",
                expected=f"{self.function.arity()} arguments",
                actual=f"{len(self.arguments)} arguments",
                suggestion=f"Provide exactly {self.function.arity()} arguments to function '{self.function.name}'"
            )
    
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
    """
    Abstract base class for formulas in DCEC.
    
    A Formula represents a logical statement in the Deontic Cognitive Event Calculus.
    Formulas can be combined using logical connectives, quantified over variables,
    and modified with deontic, cognitive, or temporal operators.
    
    All Formula subclasses must implement methods for:
    - Getting free variables
    - Substituting variables with terms
    - Converting to string representation
    
    Types of Formulas:
        - AtomicFormula: Basic predicate applications like P(x, y)
        - ConnectiveFormula: Formulas combined with logical operators (AND, OR, NOT, IMPLIES, etc.)
        - QuantifiedFormula: Formulas with quantifiers (∃x.φ or ∀x.φ)
        - DeonticFormula: Formulas with normative operators (O(φ), P(φ), F(φ))
        - CognitiveFormula: Formulas about agent mental states (B(a, φ), K(a, φ), I(a, φ))
        - TemporalFormula: Formulas about time (□φ, ◊φ, Xφ)
    
    Abstract Methods:
        get_free_variables() -> Set[Variable]:
            Returns all variables that appear free (unbound by quantifiers) in the formula
        
        substitute(var: Variable, term: Term) -> Formula:
            Substitutes all free occurrences of var with term, returning a new formula
        
        to_string() -> str:
            Returns a string representation of the formula
    
    Examples:
        >>> # See specific subclasses for concrete examples:
        >>> # - AtomicFormula: P(x, y)
        >>> # - DeonticFormula: O(pay_taxes)
        >>> # - CognitiveFormula: B(john, rain)
        >>> # - TemporalFormula: □(safe)
        >>> # - ConnectiveFormula: P(x) ∧ Q(x)
        >>> # - QuantifiedFormula: ∀x.(P(x) → Q(x))
    
    Notes:
        - Formulas are immutable when possible (use dataclasses with frozen=True where applicable)
        - Free variables in formulas can be bound by quantifiers
        - Substitution must avoid variable capture (use fresh variables when needed)
    """
    
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
    
    def __post_init__(self) -> None:
        if len(self.arguments) != self.predicate.arity():
            raise ValidationError(
                f"Predicate arity mismatch for '{self.predicate.name}'",
                expected=f"{self.predicate.arity()} arguments",
                actual=f"{len(self.arguments)} arguments",
                suggestion=f"Provide exactly {self.predicate.arity()} arguments to predicate '{self.predicate.name}'"
            )
    
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
    """
    A formula with a deontic (normative) operator.
    
    DeonticFormula represents normative statements about what ought to be, what is permitted,
    or what is forbidden. It combines a deontic operator with an inner formula, optionally
    relativized to a specific agent.
    
    Deontic formulas enable reasoning about norms, obligations, permissions, rights, and
    other normative concepts central to legal, ethical, and social reasoning.
    
    Args:
        operator (DeonticOperator): The deontic operator (OBLIGATION, PERMISSION, PROHIBITION, etc.)
        formula (Formula): The formula that the deontic operator applies to
        agent (Optional[Term]): Optional agent for agent-relative deontic statements
            - When provided: O[agent](φ) means "agent is obligated to ensure φ"
            - When None: O(φ) means "it is obligatory that φ" (general obligation)
    
    Attributes:
        operator: The deontic operator being applied
        formula: The inner formula being modified
        agent: Optional agent term for agent-relative deontic statements
    
    Common Patterns:
        - O(φ): "it is obligatory that φ"
        - P(φ): "it is permitted that φ"
        - F(φ): "it is forbidden that φ" (equivalent to O(¬φ))
        - O[agent](action): "agent is obligated to perform action"
        - P[agent](action): "agent is permitted to perform action"
    
    Examples:
        >>> from ipfs_datasets_py.logic.CEC.native.dcec_core import (
        ...     DeonticFormula, DeonticOperator, AtomicFormula, Predicate, Sort
        ... )
        >>> # Create a predicate for "pay taxes"
        >>> action_sort = Sort("action")
        >>> pay_taxes = Predicate("pay_taxes", [])
        >>> formula = AtomicFormula(pay_taxes, [])
        >>> 
        >>> # O(pay_taxes) - "it is obligatory to pay taxes"
        >>> obligation = DeonticFormula(DeonticOperator.OBLIGATION, formula)
        >>> print(obligation.to_string())
        'O(pay_taxes())'
        >>> 
        >>> # P(drive_car) - "it is permitted to drive a car"
        >>> drive = Predicate("drive_car", [])
        >>> drive_formula = AtomicFormula(drive, [])
        >>> permission = DeonticFormula(DeonticOperator.PERMISSION, drive_formula)
        >>> print(permission.to_string())
        'P(drive_car())'
    
    Methods:
        get_free_variables() -> Set[Variable]:
            Returns free variables from both the inner formula and the agent term (if present)
        
        substitute(var: Variable, term: Term) -> Formula:
            Substitutes variable in both inner formula and agent term (if present)
        
        to_string() -> str:
            Returns string representation like "O(φ)" or "O[agent](φ)"
    
    Notes:
        - F(φ) is typically defined as O(¬φ) - forbidden means obligatory not to do
        - P(φ) is the dual of O: P(φ) ≡ ¬O(¬φ) - permitted means not obligatory not to do
        - Deontic operators can be combined with temporal operators: □O(φ) - "always obligatory"
        - Agent-relative deontic statements enable multi-agent normative reasoning
        - Deontic conflicts occur when O(φ) ∧ O(¬φ) - both φ and ¬φ are obligatory
    """
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
    """
    A formula with a cognitive operator representing an agent's mental state.
    
    CognitiveFormula represents statements about what agents believe, know, intend, desire,
    or have as goals. These formulas enable reasoning about agents' internal mental states
    and how they relate to actions and the external world.
    
    Args:
        operator (CognitiveOperator): The cognitive operator (BELIEF, KNOWLEDGE, INTENTION, etc.)
        agent (Term): The agent whose mental state is being described
        formula (Formula): The content of the mental state (what is believed, known, intended, etc.)
    
    Attributes:
        operator: The cognitive operator being applied
        agent: The agent term (required - cognitive states always belong to an agent)
        formula: The inner formula representing the content of the mental state
    
    Common Patterns:
        - B(agent, φ): "agent believes φ"
        - K(agent, φ): "agent knows φ" (implies truth: K(agent, φ) → φ)
        - I(agent, action): "agent intends to perform action"
        - D(agent, state): "agent desires state"
        - G(agent, goal): "agent has goal"
    
    Examples:
        >>> from ipfs_datasets_py.logic.CEC.native.dcec_core import (
        ...     CognitiveFormula, CognitiveOperator, AtomicFormula, 
        ...     Predicate, VariableTerm, Variable, Sort
        ... )
        >>> # Create agent and content
        >>> agent_sort = Sort("agent")
        >>> agent_var = Variable("john", agent_sort)
        >>> agent_term = VariableTerm(agent_var)
        >>> 
        >>> # Create a formula for "it will rain"
        >>> rain_pred = Predicate("rain", [])
        >>> rain_formula = AtomicFormula(rain_pred, [])
        >>> 
        >>> # B(john, rain) - "John believes it will rain"
        >>> belief = CognitiveFormula(CognitiveOperator.BELIEF, agent_term, rain_formula)
        >>> print(belief.to_string())
        'B(john:agent, rain())'
        >>> 
        >>> # K(mary, 2+2=4) - "Mary knows 2+2=4"
        >>> mary_term = VariableTerm(Variable("mary", agent_sort))
        >>> math_pred = Predicate("equals_four", [])
        >>> math_formula = AtomicFormula(math_pred, [])
        >>> knowledge = CognitiveFormula(CognitiveOperator.KNOWLEDGE, mary_term, math_formula)
        >>> print(knowledge.to_string())
        'K(mary:agent, equals_four())'
    
    Methods:
        get_free_variables() -> Set[Variable]:
            Returns free variables from both the agent term and the inner formula
        
        substitute(var: Variable, term: Term) -> Formula:
            Substitutes variable in both agent term and inner formula
        
        to_string() -> str:
            Returns string representation like "B(agent, φ)"
    
    Notes:
        - Knowledge implies truth: if K(agent, φ) then φ must be true
        - Beliefs don't imply truth: B(agent, φ) doesn't mean φ is true
        - Agents can have nested beliefs: B(john, B(mary, φ)) - "John believes Mary believes φ"
        - BDI (Belief-Desire-Intention) model: beliefs + desires → intentions → actions
        - Cognitive operators enable theory of mind and multi-agent coordination
        - Common axioms: K(agent, φ) → φ (knowledge implies truth)
        - Common axioms: K(agent, φ) → B(agent, φ) (knowledge implies belief)
    """
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
    """
    A formula with a temporal operator for time-dependent reasoning.
    
    TemporalFormula represents statements about what is always true, eventually true,
    true at the next moment, or true at specific time points. These enable reasoning
    about change over time and temporal relationships between events.
    
    Args:
        operator (TemporalOperator): The temporal operator (ALWAYS, EVENTUALLY, NEXT, UNTIL, SINCE)
        formula (Formula): The formula that the temporal operator applies to
        time (Optional[Term]): Optional explicit time point for the temporal statement
    
    Attributes:
        operator: The temporal operator being applied
        formula: The main formula being temporally modified
        time: Optional time term for explicit temporal references
    
    Common Patterns:
        - □φ (ALWAYS): "φ is always true" / "necessarily φ"
        - ◊φ (EVENTUALLY): "φ will eventually be true" / "possibly φ"
        - Xφ (NEXT): "φ is true at the next moment"
        - □[t](φ): "φ is always true at time t"
    
    Examples:
        >>> from ipfs_datasets_py.logic.CEC.native.dcec_core import (
        ...     TemporalFormula, TemporalOperator, AtomicFormula, Predicate
        ... )
        >>> # Create a formula for "safe"
        >>> safe_pred = Predicate("safe", [])
        >>> safe_formula = AtomicFormula(safe_pred, [])
        >>> 
        >>> # □(safe) - "always safe"
        >>> always_safe = TemporalFormula(TemporalOperator.ALWAYS, safe_formula)
        >>> print(always_safe.to_string())
        '□(safe())'
        >>> 
        >>> # ◊(success) - "eventually successful"
        >>> success_pred = Predicate("success", [])
        >>> success_formula = AtomicFormula(success_pred, [])
        >>> eventually_success = TemporalFormula(TemporalOperator.EVENTUALLY, success_formula)
        >>> print(eventually_success.to_string())
        '◊(success())'
    
    Methods:
        get_free_variables() -> Set[Variable]:
            Returns free variables from formula and time term (if specified)
        
        substitute(var: Variable, term: Term) -> Formula:
            Substitutes variable in both formula and time term (if specified)
        
        to_string() -> str:
            Returns string representation like "□φ" or "□[t](φ)"
    
    Notes:
        - □φ and ◊φ are dual: □φ ≡ ¬◊¬φ and ◊φ ≡ ¬□¬φ
        - Linear Temporal Logic (LTL): uses ALWAYS, EVENTUALLY, NEXT, UNTIL, SINCE
        - Common axioms: □(φ → ψ) → (□φ → □ψ) - K axiom
        - Common axioms: □φ → φ - T axiom (reflexivity)
        - Temporal operators combine with deontic: □O(φ) - "always obligatory that φ"
        - Liveness property: ◊φ - something good eventually happens
        - Safety property: □φ - something bad never happens
    """
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
    
    def __post_init__(self) -> None:
        if self.connective == LogicalConnective.NOT and len(self.formulas) != 1:
            raise ValidationError(
                f"NOT connective arity mismatch",
                expected="exactly 1 formula",
                actual=f"{len(self.formulas)} formulas",
                suggestion="Provide exactly one formula for NOT operation"
            )
        elif self.connective in [LogicalConnective.AND, LogicalConnective.OR] and len(self.formulas) < 2:
            raise ValidationError(
                f"{self.connective.name} connective arity mismatch",
                expected="at least 2 formulas",
                actual=f"{len(self.formulas)} formulas",
                suggestion=f"Provide at least 2 formulas for {self.connective.name} operation"
            )
        elif self.connective in [LogicalConnective.IMPLIES, LogicalConnective.BICONDITIONAL] and len(self.formulas) != 2:
            raise ValidationError(
                f"{self.connective.name} connective arity mismatch",
                expected="exactly 2 formulas",
                actual=f"{len(self.formulas)} formulas",
                suggestion=f"Provide exactly 2 formulas for {self.connective.name} operation"
            )
    
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
    
    def __post_init__(self) -> None:
        if self.quantifier not in [LogicalConnective.EXISTS, LogicalConnective.FORALL]:
            raise ValidationError(
                f"Invalid quantifier",
                expected="EXISTS or FORALL",
                actual=str(self.quantifier),
                suggestion="Use LogicalConnective.EXISTS or LogicalConnective.FORALL as quantifier"
            )
    
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
