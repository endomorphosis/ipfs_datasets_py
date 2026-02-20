"""
Native Python 3 implementation of Deontic Cognitive Event Calculus (DCEC).

This module provides a pure Python 3 implementation of DCEC logic system,
replacing the Python 2 based DCEC_Library submodule.

Type/operator definitions are in dcec_types.py; this module re-exports them
for backward compatibility and defines the Formula/Term data model.
"""

from typing import Dict, List, Optional, Any, Set, Union
from dataclasses import dataclass, field
import logging
from abc import ABC, abstractmethod

from .exceptions import ValidationError
from .dcec_types import (
    DeonticOperator,
    CognitiveOperator,
    LogicalConnective,
    TemporalOperator,
    Sort,
    Variable,
    Function,
    Predicate,
)

# Backward compatibility re-exports (all names remain importable from dcec_core)
__all__ = [
    "DeonticOperator",
    "CognitiveOperator",
    "LogicalConnective",
    "TemporalOperator",
    "Sort",
    "Variable",
    "Function",
    "Predicate",
    "Term",
    "VariableTerm",
    "FunctionTerm",
    "Formula",
    "AtomicFormula",
    "DeonticFormula",
    "CognitiveFormula",
    "TemporalFormula",
    "ConnectiveFormula",
    "QuantifiedFormula",
    "DCECStatement",
]

try:
    from beartype import beartype
except ImportError:
    from typing import TypeVar, Callable
    F = TypeVar('F', bound=Callable[..., Any])
    def beartype(func: F) -> F:
        return func

logger = logging.getLogger(__name__)


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
                value=len(self.arguments),
                expected_type=f"{self.function.arity()} arguments",
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
    
    def __eq__(self, other: object) -> bool:
        """
        Check structural equality of formulas.
        
        Two formulas are considered equal if they have the same string representation.
        This provides a simple but effective equality check that works across all
        formula types.
        
        Args:
            other: Object to compare with
            
        Returns:
            True if formulas are structurally equal, False otherwise
            
        Examples:
            >>> from ipfs_datasets_py.logic.CEC.native.dcec_core import AtomicFormula, Predicate
            >>> pred = Predicate("P", [])
            >>> f1 = AtomicFormula(pred, [])
            >>> f2 = AtomicFormula(pred, [])
            >>> f1 == f2  # True - same structure
            True
        
        Notes:
            - This enables consistent formula comparison across all formula types
            - String-based comparison is sufficient for most logical reasoning tasks
            - For performance-critical code, consider caching to_string() results
        """
        if not isinstance(other, Formula):
            return False
        return self.to_string() == other.to_string()
    
    # Note: __hash__ is commented out because dataclasses are mutable by default.
    # To enable hashing, formulas would need to be made immutable with frozen=True,
    # which would be a breaking change. The == operator works correctly for comparisons.
    #
    # def __hash__(self) -> int:
    #     """Hash based on string representation for set/dict usage."""
    #     return hash(self.to_string())


@dataclass
class AtomicFormula(Formula):
    """An atomic formula (predicate application)."""
    predicate: Predicate
    arguments: List[Term]
    
    def __post_init__(self) -> None:
        if len(self.arguments) != self.predicate.arity():
            raise ValidationError(
                f"Predicate arity mismatch for '{self.predicate.name}'",
                value=len(self.arguments),
                expected_type=f"{self.predicate.arity()} arguments",
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
    """
    A formula built from logical connectives.
    
    ConnectiveFormula represents compound formulas built using logical operators like
    AND, OR, NOT, IMPLIES, and BICONDITIONAL. These are the building blocks for
    constructing complex logical statements from simpler formulas.
    
    Args:
        connective (LogicalConnective): The logical operator (AND, OR, NOT, IMPLIES, BICONDITIONAL)
        formulas (List[Formula]): The list of sub-formulas being combined
            - NOT: exactly 1 formula
            - AND, OR: at least 2 formulas
            - IMPLIES, BICONDITIONAL: exactly 2 formulas
    
    Attributes:
        connective: The logical connective being applied
        formulas: List of sub-formulas
    
    Common Patterns:
        - P ∧ Q (AND): "P and Q"
        - P ∨ Q (OR): "P or Q"
        - ¬P (NOT): "not P"
        - P → Q (IMPLIES): "if P then Q" / "P implies Q"
        - P ↔ Q (BICONDITIONAL): "P if and only if Q"
    
    Examples:
        >>> from ipfs_datasets_py.logic.CEC.native.dcec_core import (
        ...     ConnectiveFormula, LogicalConnective, AtomicFormula, Predicate
        ... )
        >>> # Create predicates
        >>> p_pred = Predicate("P", [])
        >>> q_pred = Predicate("Q", [])
        >>> p = AtomicFormula(p_pred, [])
        >>> q = AtomicFormula(q_pred, [])
        >>> 
        >>> # P ∧ Q - "P and Q"
        >>> and_formula = ConnectiveFormula(LogicalConnective.AND, [p, q])
        >>> print(and_formula.to_string())
        '(P() ∧ Q())'
        >>> 
        >>> # ¬P - "not P"
        >>> not_formula = ConnectiveFormula(LogicalConnective.NOT, [p])
        >>> print(not_formula.to_string())
        '¬(P())'
        >>> 
        >>> # P → Q - "if P then Q"
        >>> implies_formula = ConnectiveFormula(LogicalConnective.IMPLIES, [p, q])
        >>> print(implies_formula.to_string())
        '(P() → Q())'
    
    Methods:
        get_free_variables() -> Set[Variable]:
            Returns union of free variables from all sub-formulas
        
        substitute(var: Variable, term: Term) -> Formula:
            Substitutes variable in all sub-formulas
        
        to_string() -> str:
            Returns string representation with appropriate syntax for each connective
    
    Raises:
        ValidationError: If arity requirements are not met for the connective
    
    Notes:
        - Connectives follow standard logical precedence: NOT > AND > OR > IMPLIES
        - AND and OR can take more than 2 arguments for convenience
        - Parentheses are added in string representation to avoid ambiguity
        - Formulas can be nested arbitrarily: (P ∧ Q) ∨ (R ∧ S)
    """
    connective: LogicalConnective
    formulas: List[Formula]

    @property
    def operator(self) -> LogicalConnective:
        """Alias for connective (backward compat)."""
        return self.connective

    def __new__(cls, connective, formulas=None, *extra_formulas):
        """Allow both ConnectiveFormula(op, [p, q]) and ConnectiveFormula(op, p, q)."""
        instance = object.__new__(cls)
        return instance

    def __init__(self, connective, formulas=None, *extra_formulas):
        """Accept formulas as a list or as positional args."""
        if formulas is None:
            formulas = []
        elif not isinstance(formulas, list):
            # Called as ConnectiveFormula(op, p, q) — formulas is the first formula
            formulas = [formulas] + list(extra_formulas)
        self.connective = connective
        self.formulas = formulas
        self.__post_init__()
    
    def __post_init__(self) -> None:
        if self.connective == LogicalConnective.NOT and len(self.formulas) != 1:
            raise ValidationError(
                f"NOT connective arity mismatch",
                value=len(self.formulas),
                expected_type="exactly 1 formula",
                suggestion="Provide exactly one formula for NOT operation"
            )
        elif self.connective in [LogicalConnective.AND, LogicalConnective.OR] and len(self.formulas) < 2:
            raise ValidationError(
                f"{self.connective.name} connective arity mismatch",
                value=len(self.formulas),
                expected_type="at least 2 formulas",
                suggestion=f"Provide at least 2 formulas for {self.connective.name} operation"
            )
        elif self.connective in [LogicalConnective.IMPLIES, LogicalConnective.BICONDITIONAL] and len(self.formulas) != 2:
            raise ValidationError(
                f"{self.connective.name} connective arity mismatch",
                value=len(self.formulas),
                expected_type="exactly 2 formulas",
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
    """
    A formula with quantifiers (∃ or ∀).
    
    QuantifiedFormula represents formulas with existential (∃) or universal (∀) quantification
    over variables. Quantifiers bind variables and are fundamental for expressing general
    statements and existence claims in first-order logic.
    
    Args:
        quantifier (LogicalConnective): Either EXISTS (∃) or FORALL (∀)
        variable (Variable): The variable being quantified (bound variable)
        formula (Formula): The scope of the quantifier
    
    Attributes:
        quantifier: The type of quantification (EXISTS or FORALL)
        variable: The bound variable
        formula: The formula in the scope of the quantifier
    
    Common Patterns:
        - ∃x.P(x): "there exists an x such that P(x)"
        - ∀x.P(x): "for all x, P(x)"
        - ∀x.(P(x) → Q(x)): "for all x, if P(x) then Q(x)"
        - ∃x.(P(x) ∧ Q(x)): "there exists an x such that P(x) and Q(x)"
    
    Examples:
        >>> from ipfs_datasets_py.logic.CEC.native.dcec_core import (
        ...     QuantifiedFormula, LogicalConnective, AtomicFormula, 
        ...     Predicate, Variable, VariableTerm, Sort
        ... )
        >>> # Create a variable and predicate
        >>> person_sort = Sort("person")
        >>> x = Variable("x", person_sort)
        >>> mortal_pred = Predicate("mortal", [person_sort])
        >>> 
        >>> # Create P(x) where P is "mortal"
        >>> x_term = VariableTerm(x)
        >>> mortal_x = AtomicFormula(mortal_pred, [x_term])
        >>> 
        >>> # ∀x.mortal(x) - "all persons are mortal"
        >>> forall_mortal = QuantifiedFormula(LogicalConnective.FORALL, x, mortal_x)
        >>> print(forall_mortal.to_string())
        '∀x:person.(mortal(x:person))'
        >>> 
        >>> # ∃x.mortal(x) - "there exists a mortal person"
        >>> exists_mortal = QuantifiedFormula(LogicalConnective.EXISTS, x, mortal_x)
        >>> print(exists_mortal.to_string())
        '∃x:person.(mortal(x:person))'
    
    Methods:
        get_free_variables() -> Set[Variable]:
            Returns free variables in the formula scope, excluding the bound variable
        
        substitute(var: Variable, term: Term) -> Formula:
            Substitutes variable in the scope, avoiding capture of the bound variable
        
        to_string() -> str:
            Returns string representation like "∀x.φ" or "∃x.φ"
    
    Raises:
        ValidationError: If quantifier is not EXISTS or FORALL
    
    Notes:
        - Bound variables are not free: in ∀x.P(x), x is not a free variable
        - Substitution avoids variable capture (requires alpha-conversion in complete impl)
        - Quantifier scope extends as far right as possible: ∀x.P(x) ∧ Q(x) means ∀x.(P(x) ∧ Q(x))
        - Nested quantifiers: ∀x.∃y.P(x,y) - "for all x there exists y such that P(x,y)"
        - Quantifier duality: ¬∀x.P(x) ≡ ∃x.¬P(x) and ¬∃x.P(x) ≡ ∀x.¬P(x)
    """
    quantifier: LogicalConnective  # EXISTS or FORALL
    variable: Variable
    formula: Formula
    
    def __post_init__(self) -> None:
        if self.quantifier not in [LogicalConnective.EXISTS, LogicalConnective.FORALL]:
            raise ValidationError(
                f"Invalid quantifier",
                value=str(self.quantifier),
                expected_type="EXISTS or FORALL",
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


# ---------------------------------------------------------------------------
# Convenience factory functions / aliases for concise test and example code
# ---------------------------------------------------------------------------

def Atom(name: str) -> 'AtomicFormula':
    """Create a zero-arity atomic formula by predicate name.

    Convenience wrapper so tests can write ``Atom("P")`` instead of
    ``AtomicFormula(Predicate(name, []), [])``.
    """
    pred = Predicate(name, [])
    return AtomicFormula(pred, [])


def Conjunction(*formulas: 'Formula') -> 'ConnectiveFormula':
    """Create a conjunction (AND) of two or more formulas."""
    if len(formulas) < 2:
        raise ValueError("Conjunction requires at least 2 formulas")
    return ConnectiveFormula(LogicalConnective.AND, list(formulas))


def Disjunction(*formulas: 'Formula') -> 'ConnectiveFormula':
    """Create a disjunction (OR) of two or more formulas."""
    if len(formulas) < 2:
        raise ValueError("Disjunction requires at least 2 formulas")
    return ConnectiveFormula(LogicalConnective.OR, list(formulas))


def Negation(formula: 'Formula') -> 'ConnectiveFormula':
    """Create a negation (NOT) of a formula."""
    return ConnectiveFormula(LogicalConnective.NOT, [formula])


def Implication(antecedent: 'Formula', consequent: 'Formula') -> 'ConnectiveFormula':
    """Create an implication (antecedent → consequent)."""
    return ConnectiveFormula(LogicalConnective.IMPLIES, [antecedent, consequent])


# Export convenience aliases
__all__ += [
    "Atom",
    "Conjunction",
    "Disjunction",
    "Negation",
    "Implication",
]
