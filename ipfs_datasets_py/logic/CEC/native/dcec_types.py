"""
Type definitions and operator enums for the Deontic Cognitive Event Calculus (DCEC).

This module contains the core type system: operator enumerations (DeonticOperator,
CognitiveOperator, LogicalConnective, TemporalOperator) and the foundational
data types (Sort, Variable, Function, Predicate).
"""

from enum import Enum
from typing import List, Optional
from dataclasses import dataclass

from .exceptions import ValidationError

__all__ = [
    "DeonticOperator",
    "CognitiveOperator",
    "LogicalConnective",
    "TemporalOperator",
    "Sort",
    "Variable",
    "Function",
    "Predicate",
]


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
        >>> from ipfs_datasets_py.logic.CEC.native.dcec_types import DeonticOperator
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
    OBLIGATORY = "O"         # alias for OBLIGATION (backward compat)
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
        >>> from ipfs_datasets_py.logic.CEC.native.dcec_types import CognitiveOperator
        >>> op = CognitiveOperator.BELIEF
        >>> print(op.value)
        'B'
    
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
    # Backward-compat aliases
    BELIEVES = "B"
    KNOWS = "K"


class LogicalConnective(Enum):
    """
    Logical connectives for building complex formulas.
    
    LogicalConnective defines the standard logical operators used to construct compound
    formulas from simpler ones. These connectives enable propositional and first-order
    logic reasoning within the DCEC framework.
    
    Connectives:
        AND (∧): Logical conjunction
            - P ∧ Q is true when both P and Q are true
        OR (∨): Logical disjunction
            - P ∨ Q is true when at least one of P or Q is true
        NOT (¬): Logical negation
            - ¬P is true when P is false
        IMPLIES (→): Material implication
            - P → Q is false only when P is true and Q is false
        BICONDITIONAL (↔): Logical equivalence
            - P ↔ Q is true when P and Q have the same truth value
        EXISTS (∃): Existential quantifier
            - ∃x.P(x) is true when P(x) is true for at least one x
        FORALL (∀): Universal quantifier
            - ∀x.P(x) is true when P(x) is true for all x
    
    Precedence (highest to lowest):
        1. NOT (¬)
        2. AND (∧)
        3. OR (∨)
        4. IMPLIES (→)
        5. BICONDITIONAL (↔)
        6. Quantifiers (∃, ∀)
    
    Examples:
        >>> from ipfs_datasets_py.logic.CEC.native.dcec_types import LogicalConnective
        >>> and_conn = LogicalConnective.AND
        >>> print(and_conn.value)
        '∧'
    
    Notes:
        - ConnectiveFormula uses AND, OR, NOT, IMPLIES, BICONDITIONAL
        - QuantifiedFormula uses EXISTS, FORALL
        - Truth-functional: output determined solely by input truth values
    """
    AND = "∧"
    OR = "∨"
    NOT = "¬"
    IMPLIES = "→"
    BICONDITIONAL = "↔"
    IFF = "↔"  # backward-compat alias
    EXISTS = "∃"
    FORALL = "∀"


class TemporalOperator(Enum):
    """
    Temporal operators for time-dependent reasoning.
    
    TemporalOperator defines operators for reasoning about time and change in Linear
    Temporal Logic (LTL) style. These operators enable expressing properties about
    sequences of states and temporal evolution of formulas.
    
    Operators:
        ALWAYS (□): Globally/always operator
            - □φ means "φ is true at all time points"
        EVENTUALLY (◊): Finally/eventually operator
            - ◊φ means "φ will be true at some future time point"
        NEXT (X): Next-time operator
            - Xφ means "φ is true at the next time point"
        UNTIL (U): Until operator (binary)
            - φ U ψ means "φ holds until ψ becomes true"
        SINCE (S): Since operator (binary, past-time)
            - φ S ψ means "φ has been true since ψ was true"
    
    Operator Relationships:
        - Duality: □φ ≡ ¬◊¬φ and ◊φ ≡ ¬□¬φ
        - □(φ → ψ) → (□φ → □ψ) (K axiom - distribution)
    
    Examples:
        >>> from ipfs_datasets_py.logic.CEC.native.dcec_types import TemporalOperator
        >>> always = TemporalOperator.ALWAYS
        >>> print(always.value)
        '□'
    
    Notes:
        - UNTIL and SINCE are binary (take two formulas)
        - ALWAYS, EVENTUALLY, NEXT are unary (take one formula)
        - LTL is decidable but PSPACE-complete
    """
    ALWAYS = "□"             # Always/necessarily
    EVENTUALLY = "◊"         # Eventually/possibly
    NEXT = "X"               # Next time point
    UNTIL = "U"              # Until
    SINCE = "S"              # Since


@dataclass(frozen=True)
class Sort:
    """
    Represents a type/sort in the logic system.
    
    Sort defines a type in the DCEC type system, enabling typed logic reasoning.
    Sorts can form hierarchies through subtyping relationships.
    
    Args:
        name (str): The name of the sort/type
        parent (Optional[Sort]): Optional parent sort for subtyping hierarchy
    
    Examples:
        >>> from ipfs_datasets_py.logic.CEC.native.dcec_types import Sort
        >>> entity = Sort("entity")
        >>> agent = Sort("agent", parent=entity)
        >>> human = Sort("human", parent=agent)
        >>> human.is_subtype_of(entity)
        True
    
    Notes:
        - Frozen dataclass: sorts are immutable once created
        - Subtyping is reflexive: every sort is a subtype of itself
        - No multiple inheritance: each sort has at most one parent
    """
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
    """
    Represents a logical variable in DCEC formulas.
    
    Variable is a typed symbol that can be quantified over or substituted with terms.
    
    Args:
        name (str): The variable's identifier (e.g., "x", "y", "agent1")
        sort (Sort): The type/sort of the variable
    
    Examples:
        >>> from ipfs_datasets_py.logic.CEC.native.dcec_types import Variable, Sort
        >>> person_sort = Sort("person")
        >>> x = Variable("x", person_sort)
        >>> print(x)
        x:person
    
    Notes:
        - Frozen dataclass: variables are immutable
        - Equality is structural: same name and sort means equal
    """
    name: str
    sort: Sort

    def __str__(self) -> str:
        return f"{self.name}:{self.sort.name}"


@dataclass
class Function:
    """
    Represents a function symbol in DCEC.
    
    Function is a typed symbol that maps terms to terms with a fixed arity.
    
    Args:
        name (str): The function's identifier
        argument_sorts (List[Sort]): Types of the function's arguments
        return_sort (Sort): Type of the value the function returns
    
    Examples:
        >>> from ipfs_datasets_py.logic.CEC.native.dcec_types import Function, Sort
        >>> person = Sort("person")
        >>> number = Sort("number")
        >>> age = Function("age", [person], number)
        >>> print(age.arity())
        1
    
    Notes:
        - Functions are interpreted: meaning given by model/interpretation
        - Distinguished from predicates (which return truth values)
    """
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
    """
    Represents a predicate symbol in DCEC.
    
    Predicate is a typed relation symbol that maps terms to truth values.
    
    Args:
        name (str): The predicate's identifier
        argument_sorts (List[Sort]): Types of the predicate's arguments
    
    Examples:
        >>> from ipfs_datasets_py.logic.CEC.native.dcec_types import Predicate, Sort
        >>> person = Sort("person")
        >>> mortal = Predicate("mortal", [person])
        >>> print(mortal.arity())
        1
    
    Notes:
        - Predicates are interpreted: meaning given by model/interpretation
        - Distinguished from functions (which return terms, not truth values)
        - Zero-arity predicates are propositional atoms
    """
    name: str
    argument_sorts: List[Sort]

    def arity(self) -> int:
        """Return the arity (number of arguments) of the predicate."""
        return len(self.argument_sorts)

    def __str__(self) -> str:
        args = ", ".join(s.name for s in self.argument_sorts)
        return f"{self.name}({args})"
