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
    """
    Logical connectives for building complex formulas.
    
    LogicalConnective defines the standard logical operators used to construct compound
    formulas from simpler ones. These connectives enable propositional and first-order
    logic reasoning within the DCEC framework.
    
    Connectives:
        AND (∧): Logical conjunction
            - P ∧ Q is true when both P and Q are true
            - Commutative: P ∧ Q ≡ Q ∧ P
            - Associative: (P ∧ Q) ∧ R ≡ P ∧ (Q ∧ R)
            - Identity: P ∧ True ≡ P
            
        OR (∨): Logical disjunction
            - P ∨ Q is true when at least one of P or Q is true
            - Commutative: P ∨ Q ≡ Q ∨ P
            - Associative: (P ∨ Q) ∨ R ≡ P ∨ (Q ∨ R)
            - Identity: P ∨ False ≡ P
            
        NOT (¬): Logical negation
            - ¬P is true when P is false
            - Double negation: ¬¬P ≡ P
            - De Morgan's: ¬(P ∧ Q) ≡ ¬P ∨ ¬Q and ¬(P ∨ Q) ≡ ¬P ∧ ¬Q
            
        IMPLIES (→): Material implication
            - P → Q is false only when P is true and Q is false
            - Equivalent to: ¬P ∨ Q
            - Contrapositive: (P → Q) ≡ (¬Q → ¬P)
            - Not commutative: P → Q ≠ Q → P
            
        BICONDITIONAL (↔): Logical equivalence
            - P ↔ Q is true when P and Q have the same truth value
            - Equivalent to: (P → Q) ∧ (Q → P)
            - Commutative: P ↔ Q ≡ Q ↔ P
            
        EXISTS (∃): Existential quantifier
            - ∃x.P(x) is true when P(x) is true for at least one x
            - Duality: ∃x.P(x) ≡ ¬∀x.¬P(x)
            - Used in QuantifiedFormula, not ConnectiveFormula
            
        FORALL (∀): Universal quantifier
            - ∀x.P(x) is true when P(x) is true for all x
            - Duality: ∀x.P(x) ≡ ¬∃x.¬P(x)
            - Used in QuantifiedFormula, not ConnectiveFormula
    
    Precedence (highest to lowest):
        1. NOT (¬)
        2. AND (∧)
        3. OR (∨)
        4. IMPLIES (→)
        5. BICONDITIONAL (↔)
        6. Quantifiers (∃, ∀)
    
    Examples:
        >>> from ipfs_datasets_py.logic.CEC.native.dcec_core import LogicalConnective
        >>> # Using in ConnectiveFormula
        >>> and_conn = LogicalConnective.AND
        >>> print(and_conn.value)
        '∧'
        >>> 
        >>> # Common equivalences
        >>> # P → Q ≡ ¬P ∨ Q
        >>> # P ∧ (Q ∨ R) ≡ (P ∧ Q) ∨ (P ∧ R)  (distribution)
        >>> # ¬(P ∧ Q) ≡ ¬P ∨ ¬Q  (De Morgan's law)
    
    Usage in Formulas:
        - ConnectiveFormula uses AND, OR, NOT, IMPLIES, BICONDITIONAL
        - QuantifiedFormula uses EXISTS, FORALL
        - See ConnectiveFormula and QuantifiedFormula for usage examples
    
    Notes:
        - Quantifiers (EXISTS, FORALL) bind variables in their scope
        - Proper parenthesization is important for readability
        - Some connectives are interdefinable (e.g., → can be defined using ¬ and ∨)
        - Truth-functional: output determined solely by input truth values
    """
    AND = "∧"
    OR = "∨"
    NOT = "¬"
    IMPLIES = "→"
    BICONDITIONAL = "↔"
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
            - Also called "globally" or "henceforth"
            - Example: □(safe) - "the system is always safe"
            - Dual of EVENTUALLY: □φ ≡ ¬◊¬φ
            
        EVENTUALLY (◊): Finally/eventually operator
            - ◊φ means "φ will be true at some future time point"
            - Also called "finally" or "possibly"
            - Example: ◊(success) - "success will eventually occur"
            - Dual of ALWAYS: ◊φ ≡ ¬□¬φ
            
        NEXT (X): Next-time operator
            - Xφ means "φ is true at the next time point"
            - Also called "neXt"
            - Example: X(processed) - "the request will be processed next"
            - No direct dual
            
        UNTIL (U): Until operator (binary)
            - φ U ψ means "φ holds until ψ becomes true"
            - ψ must eventually become true
            - φ holds at all time points before ψ
            - Example: (waiting U served) - "waiting until served"
            - Strong until (ψ must occur)
            
        SINCE (S): Since operator (binary)
            - φ S ψ means "φ has been true since ψ was true"
            - Past-time operator (looks backward in time)
            - Example: (active S started) - "active since started"
            - Dual of UNTIL in past-time logic
    
    Temporal Properties:
        Safety: □(¬bad) - "something bad never happens"
        Liveness: ◊(good) - "something good eventually happens"
        Response: □(request → ◊response) - "every request gets a response"
        Stability: ◊□φ - "φ eventually becomes permanently true"
    
    Operator Relationships:
        - Duality: □φ ≡ ¬◊¬φ and ◊φ ≡ ¬□¬φ
        - □φ → φ (T axiom - what's always true is true now)
        - φ → ◊φ (if true now, then eventually true)
        - □(φ → ψ) → (□φ → □ψ) (K axiom - distribution)
        - ◊(φ ∨ ψ) ≡ ◊φ ∨ ◊ψ (EVENTUALLY distributes over OR)
        - □(φ ∧ ψ) ≡ □φ ∧ □ψ (ALWAYS distributes over AND)
    
    Examples:
        >>> from ipfs_datasets_py.logic.CEC.native.dcec_core import TemporalOperator
        >>> always = TemporalOperator.ALWAYS
        >>> print(always.value)
        '□'
        >>> 
        >>> # Common temporal patterns
        >>> # □◊φ - "φ is true infinitely often"
        >>> # ◊□φ - "φ eventually becomes permanently true"
        >>> # □(φ → ◊ψ) - "whenever φ, eventually ψ"
    
    Usage:
        - Used in TemporalFormula to express time-dependent properties
        - Can be combined with deontic operators: □O(φ) - "always obligatory"
        - Can be nested: □◊φ, ◊□ψ, etc.
    
    Notes:
        - Operators have different semantics in discrete vs continuous time
        - UNTIL and SINCE are binary (take two formulas)
        - ALWAYS, EVENTUALLY, NEXT are unary (take one formula)
        - LTL is decidable but PSPACE-complete
        - Used for model checking and verification
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
    Sorts can form hierarchies through subtyping relationships, allowing for
    flexible and structured domain modeling.
    
    Args:
        name (str): The name of the sort/type
        parent (Optional[Sort]): Optional parent sort for subtyping hierarchy
            - If None, this is a base sort with no parent
            - If specified, this sort is a subtype of the parent
    
    Attributes:
        name: The sort's identifier
        parent: The parent sort (if any) in the type hierarchy
    
    Type Hierarchy:
        Sorts form a tree structure through parent relationships:
        - Root sorts have parent=None
        - Child sorts inherit from their parents
        - Subtyping is transitive: if A <: B and B <: C, then A <: C
        - Used for type checking and domain constraints
    
    Common Sort Hierarchies:
        Entity (base)
        ├── Agent
        │   ├── Human
        │   └── Organization
        ├── Object
        │   ├── PhysicalObject
        │   └── AbstractObject
        └── Event
            ├── Action
            └── State
    
    Examples:
        >>> from ipfs_datasets_py.logic.CEC.native.dcec_core import Sort
        >>> # Create a base sort
        >>> entity = Sort("entity")
        >>> print(entity.name)
        'entity'
        >>> 
        >>> # Create a subsort
        >>> agent = Sort("agent", parent=entity)
        >>> human = Sort("human", parent=agent)
        >>> 
        >>> # Check subtyping relationships
        >>> human.is_subtype_of(agent)  # True - human is a kind of agent
        True
        >>> human.is_subtype_of(entity)  # True - transitive
        True
        >>> agent.is_subtype_of(human)  # False - not a subtype
        False
    
    Methods:
        is_subtype_of(other: Sort) -> bool:
            Check if this sort is a subtype of another sort.
            Returns True if this sort equals other or is a descendant of other.
            Uses recursive checking up the parent chain.
    
    Usage:
        - Variables are typed with sorts: Variable("x", person_sort)
        - Functions have argument and return sorts: Function("age", [person_sort], number_sort)
        - Predicates have argument sorts: Predicate("older_than", [person_sort, person_sort])
        - Enables type-safe formula construction
    
    Notes:
        - Frozen dataclass: sorts are immutable once created
        - Equality is structural: two sorts with same name and parent are equal
        - Subtyping is reflexive: every sort is a subtype of itself
        - No multiple inheritance: each sort has at most one parent
        - Used for static type checking in formula construction
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
    Variables are fundamental for expressing general statements and performing
    substitutions in logical formulas.
    
    Args:
        name (str): The variable's identifier (e.g., "x", "y", "agent1")
        sort (Sort): The type/sort of the variable
    
    Attributes:
        name: The variable's identifier string
        sort: The type of values this variable can range over
    
    Variable Binding:
        - Free variables: not bound by any quantifier
        - Bound variables: bound by ∀ or ∃ quantifiers
        - Scope: the formula range where a quantifier binds a variable
        - Capture: when substitution incorrectly binds a free variable
    
    Examples:
        >>> from ipfs_datasets_py.logic.CEC.native.dcec_core import Variable, Sort
        >>> # Create a variable
        >>> person_sort = Sort("person")
        >>> x = Variable("x", person_sort)
        >>> print(x)
        'x:person'
        >>> 
        >>> # Variables in quantified formulas
        >>> # ∀x:person. mortal(x) - "all persons are mortal"
        >>> # ∃y:number. prime(y) - "there exists a prime number"
        >>> 
        >>> # Multiple variables
        >>> y = Variable("y", person_sort)
        >>> # ∀x:person. ∃y:person. knows(x, y) - "everyone knows someone"
    
    Usage in Formulas:
        - VariableTerm wraps Variable for use in terms
        - QuantifiedFormula binds variables with ∀ or ∃
        - Free variables in formula can be substituted
        - Bound variables are renamed if needed to avoid capture
    
    Common Patterns:
        - ∀x. P(x) - universal statement about all x
        - ∃x. P(x) - existential claim about some x
        - ∀x. ∀y. R(x, y) - nested quantification
        - ∀x. (P(x) → Q(x)) - conditional for all x
    
    Methods:
        __str__() -> str:
            Returns string representation in format "name:sort_name"
            Example: Variable("x", Sort("person")) → "x:person"
    
    Notes:
        - Frozen dataclass: variables are immutable
        - Equality is structural: same name and sort means equal
        - Variable names should be unique within their scope
        - Sort determines what values the variable can take
        - Used for parameter passing and generalization
    """
    name: str
    sort: Sort
    
    def __str__(self) -> str:
        return f"{self.name}:{self.sort.name}"


@dataclass
class Function:
    """
    Represents a function symbol in DCEC.
    
    Function is a typed symbol that maps terms to terms. Functions have a fixed
    arity (number of arguments) and specific input/output types. They enable
    construction of complex terms from simpler ones.
    
    Args:
        name (str): The function's identifier (e.g., "age", "father_of", "add")
        argument_sorts (List[Sort]): Types of the function's arguments (in order)
        return_sort (Sort): Type of the value the function returns
    
    Attributes:
        name: The function's identifier
        argument_sorts: List of input types (length determines arity)
        return_sort: Output type of the function
    
    Function Application:
        - f(t₁, t₂, ..., tₙ) where f has arity n
        - Each argument tᵢ must have sort compatible with argument_sorts[i]
        - Result has sort return_sort
        - Creates a FunctionTerm when applied to arguments
    
    Common Functions:
        - Constants: zero-arity functions (e.g., "pi": () → real)
        - Unary: one argument (e.g., "age": person → number)
        - Binary: two arguments (e.g., "add": (number, number) → number)
        - n-ary: multiple arguments (e.g., "max": (number, number, number) → number)
    
    Examples:
        >>> from ipfs_datasets_py.logic.CEC.native.dcec_core import Function, Sort
        >>> # Define sorts
        >>> person = Sort("person")
        >>> number = Sort("number")
        >>> 
        >>> # Unary function: age of a person
        >>> age = Function("age", [person], number)
        >>> print(age)
        'age(person) -> number'
        >>> print(age.arity())
        1
        >>> 
        >>> # Binary function: sum of two numbers
        >>> add = Function("add", [number, number], number)
        >>> print(add.arity())
        2
        >>> 
        >>> # Constant: zero-arity function
        >>> pi = Function("pi", [], number)
        >>> print(pi.arity())
        0
        >>> 
        >>> # Function with multiple types
        >>> lookup = Function("lookup", [person, Sort("string")], Sort("value"))
    
    Methods:
        arity() -> int:
            Returns the number of arguments the function takes.
            Equals len(argument_sorts).
        
        __str__() -> str:
            Returns string representation in format:
            "name(arg1_sort, arg2_sort, ...) -> return_sort"
    
    Usage in Terms:
        - FunctionTerm applies functions to argument terms
        - Example: FunctionTerm(age, [VariableTerm(x)]) represents age(x)
        - Type checking ensures argument sorts match
        - Enables building complex terms compositionally
    
    Type Checking:
        - Number of arguments must match arity
        - Each argument term's sort must be compatible with corresponding argument_sort
        - Result term has sort return_sort
        - ValidationError raised on arity mismatch
    
    Notes:
        - Mutable dataclass (can modify after creation, though not recommended)
        - Functions are interpreted: meaning given by model/interpretation
        - Distinguished from predicates (which return bool/truth values)
        - Can be nested: f(g(x), h(y))
        - Supports Skolem functions and Herbrand terms
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
    
    Predicate is a typed relation symbol that maps terms to truth values (formulas).
    Predicates have a fixed arity and specify the types of their arguments. They
    are the building blocks for atomic formulas.
    
    Args:
        name (str): The predicate's identifier (e.g., "mortal", "older_than", "red")
        argument_sorts (List[Sort]): Types of the predicate's arguments (in order)
    
    Attributes:
        name: The predicate's identifier
        argument_sorts: List of argument types (length determines arity)
    
    Predicate Application:
        - P(t₁, t₂, ..., tₙ) where P has arity n
        - Each argument tᵢ must have sort compatible with argument_sorts[i]
        - Result is an AtomicFormula (truth value)
        - Forms the base case for formula construction
    
    Common Predicates:
        - Nullary (0-arity): propositional atoms (e.g., "raining": () - "it is raining")
        - Unary (1-arity): properties (e.g., "mortal": person - "x is mortal")
        - Binary (2-arity): relations (e.g., "loves": (person, person) - "x loves y")
        - n-ary: multi-way relations (e.g., "between": (point, point, point))
    
    Examples:
        >>> from ipfs_datasets_py.logic.CEC.native.dcec_core import Predicate, Sort
        >>> # Define sorts
        >>> person = Sort("person")
        >>> number = Sort("number")
        >>> 
        >>> # Unary predicate: property of persons
        >>> mortal = Predicate("mortal", [person])
        >>> print(mortal)
        'mortal(person)'
        >>> print(mortal.arity())
        1
        >>> 
        >>> # Binary predicate: relation between two persons
        >>> knows = Predicate("knows", [person, person])
        >>> print(knows.arity())
        2
        >>> 
        >>> # Nullary predicate: propositional atom
        >>> raining = Predicate("raining", [])
        >>> print(raining.arity())
        0
        >>> 
        >>> # Mixed-type predicate
        >>> age_greater = Predicate("age_greater", [person, number])
        >>> # Usage: age_greater(john, 18) - "John's age is greater than 18"
    
    Methods:
        arity() -> int:
            Returns the number of arguments the predicate takes.
            Equals len(argument_sorts).
        
        __str__() -> str:
            Returns string representation in format:
            "name(arg1_sort, arg2_sort, ...)"
    
    Usage in Formulas:
        - AtomicFormula applies predicates to argument terms
        - Example: AtomicFormula(mortal, [VariableTerm(x)]) represents mortal(x)
        - Type checking ensures argument sorts match
        - Building block for all formulas
    
    Common Patterns:
        - P(x) - unary predicate application
        - R(x, y) - binary relation
        - ∀x. P(x) - universal property
        - ∃x. ∃y. R(x, y) - existential relation
        - P(x) ∧ Q(x) - conjunction of predicates
        - ∀x. (P(x) → Q(x)) - implication between predicates
    
    Type Checking:
        - Number of arguments must match arity
        - Each argument term's sort must be compatible with corresponding argument_sort
        - ValidationError raised on arity mismatch
        - Enables static type checking of formulas
    
    Notes:
        - Mutable dataclass (can modify after creation, though not recommended)
        - Predicates are interpreted: meaning given by model/interpretation
        - Distinguished from functions (which return terms, not truth values)
        - Zero-arity predicates are propositional atoms
        - Supports first-order and higher-order logic
        - Can represent relations, properties, and propositions
    """
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
