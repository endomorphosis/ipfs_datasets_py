"""Bounded interpolation- and core-driven CEGAR over QF_LIA transition systems.

The loop is a refinement adapter, not a second model checker.  It reuses the
qualified interpolation receipt and incremental SMT session contracts:

1. search a boolean abstraction of the supplied control-flow graph;
2. concretize each abstract error trace with a named path formula;
3. keep a feasible trace as a counterexample and stop;
4. refine a spurious trace only with a validated interpolant, a validated
   unsat core, a weakest-precondition formula, or a reviewed predicate; and
5. terminate under a fixed budget with exactly one typed disposition.

No interpolant is fabricated.  Solver availability is not interpolation
support.  Incomplete search never upgrades to ``proved``.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from time import monotonic
from typing import Any, ClassVar, Final, Protocol

from ipfs_datasets_py.logic.backends.smt.compiler import (
    INT_SORT,
    SmtTerm,
    SmtTermKind,
    term_and,
    term_eq,
    term_false,
    term_not,
    term_symbol,
    term_true,
)
from ipfs_datasets_py.logic.backends.smt.incremental import (
    IncrementalSmtError,
    IncrementalSmtUnavailable,
    SmtCheckStatus,
    open_incremental_smt_session,
)
from ipfs_datasets_py.logic.backends.smt.interpolation import (
    DEFAULT_MAX_SYMBOLS,
    DEFAULT_MAX_TERM_NODES,
    DEFAULT_MEMORY_LIMIT_MIB,
    DEFAULT_TIMEOUT_MS,
    QUALIFIED_INTERPOLATION_THEORY,
    InterpolationBounds,
    InterpolationError,
    InterpolationStatus,
    ValidatedInterpolantReceipt,
    compute_and_validate_interpolant,
)
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.identity import canonical_identity


CEGAR_INTERFACE: Final = "BoundedInterpolationCegar@1"
CEGAR_BUDGET_SCHEMA: Final = "bounded-interpolation-cegar-budget/v1"
CEGAR_SYSTEM_SCHEMA: Final = "bounded-interpolation-cegar-system/v1"
CEGAR_PREDICATE_SCHEMA: Final = "bounded-interpolation-cegar-predicate/v1"
CEGAR_TRACE_SCHEMA: Final = "bounded-interpolation-cegar-trace/v1"
CEGAR_REFINEMENT_SCHEMA: Final = "bounded-interpolation-cegar-refinement/v1"
CEGAR_ITERATION_SCHEMA: Final = "bounded-interpolation-cegar-iteration/v1"
CEGAR_RECEIPT_SCHEMA: Final = "bounded-interpolation-cegar-receipt/v1"
CEGAR_SOLVER_RESULT_SCHEMA: Final = "bounded-interpolation-cegar-solver-observation/v1"
TRANSLATOR_IDENTITY: Final = "bounded-interpolation-cegar-structured-term@1"
THEORY_FINGERPRINT: Final = "QF_LIA@1"
LOCAL_CONJUNCTION_PROVIDER: Final = "local-qf-lia-conjunction@1"
DEFAULT_MAX_ITERATIONS: Final = 8
DEFAULT_MAX_PREDICATES: Final = 16
DEFAULT_MAX_ABSTRACT_STATES: Final = 256
DEFAULT_MAX_TRACE_LENGTH: Final = 32
ABSOLUTE_MAX_ITERATIONS: Final = 64
ABSOLUTE_MAX_PREDICATES: Final = 64
ABSOLUTE_MAX_ABSTRACT_STATES: Final = 4096
ABSOLUTE_MAX_TRACE_LENGTH: Final = 256

_COMPARISON_KINDS: Final = frozenset(
    {
        SmtTermKind.EQ,
        SmtTermKind.LT,
        SmtTermKind.LE,
        SmtTermKind.GT,
        SmtTermKind.GE,
        SmtTermKind.DISTINCT,
    }
)
_FLIPPED_COMPARISON: Final = {
    SmtTermKind.LT: SmtTermKind.GE,
    SmtTermKind.LE: SmtTermKind.GT,
    SmtTermKind.GT: SmtTermKind.LE,
    SmtTermKind.GE: SmtTermKind.LT,
    SmtTermKind.EQ: SmtTermKind.DISTINCT,
    SmtTermKind.DISTINCT: SmtTermKind.EQ,
}


class CegarError(ValueError):
    """Raised for a malformed CEGAR request or receipt."""


class CegarDisposition(StrEnum):
    PROVED = "proved"
    DISPROVED = "disproved"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    BUDGET_EXHAUSTED = "budget-exhausted"


class TraceClassification(StrEnum):
    SPURIOUS = "spurious"
    REAL = "real"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"


class RefinementAuthority(StrEnum):
    VALIDATED_INTERPOLANT = "validated_interpolant"
    VALIDATED_UNSAT_CORE = "validated_unsat_core"
    WEAKEST_PRECONDITION = "weakest_precondition"
    REVIEWED_PREDICATE = "reviewed_predicate"


class CegarQueryKind(StrEnum):
    ABSTRACT_INIT = "abstract_init"
    ABSTRACT_STEP = "abstract_step"
    PATH = "path"
    PREFIX = "prefix"


class PredicateOrigin(StrEnum):
    REVIEWED = "reviewed"
    INTERPOLANT = "interpolant"
    UNSAT_CORE = "unsat_core"
    WEAKEST_PRECONDITION = "weakest_precondition"


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or "\x00" in value:
        raise CegarError(f"{label} must be a trimmed non-empty string")
    return value


def _optional_text(value: object, label: str) -> str:
    if value in ("", None):
        return ""
    return _text(value, label)


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CegarError(f"{label} must be a positive integer")
    return value


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise CegarError(f"{label} must be a boolean")
    return value


def _require_term(value: object, label: str) -> SmtTerm:
    if not isinstance(value, SmtTerm):
        raise CegarError(f"{label} must be an SmtTerm")
    return value


def _unique(values: Sequence[str] | object, label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise CegarError(f"{label} must be a sequence")
    result = tuple(_text(item, f"{label} item") for item in values)
    if len(result) != len(set(result)):
        raise CegarError(f"{label} must not contain duplicates")
    return result


def _term_cid(term: SmtTerm, label: str) -> str:
    return canonical_identity(
        term.to_dict(),
        domain=f"logic.software-verification.cegar.{label}",
        schema_version="smt-term/v1",
    ).cid


def _symbols(term: SmtTerm) -> set[str]:
    result = {term.value} if term.kind is SmtTermKind.SYMBOL else set()
    for item in term.arguments:
        result.update(_symbols(item))
    return result


def _substitute(term: SmtTerm, mapping: Mapping[str, SmtTerm]) -> SmtTerm:
    if term.kind is SmtTermKind.SYMBOL and term.value in mapping:
        return mapping[term.value]
    if not term.arguments:
        return term
    return SmtTerm(
        term.kind,
        value=term.value,
        arguments=tuple(_substitute(item, mapping) for item in term.arguments),
        binders=term.binders,
        sort=term.sort,
    )


def _is_true(term: SmtTerm) -> bool:
    return term.kind is SmtTermKind.TRUE


def _is_false(term: SmtTerm) -> bool:
    return term.kind is SmtTermKind.FALSE


def _simplify_and(*args: SmtTerm) -> SmtTerm:
    kept: list[SmtTerm] = []
    for item in args:
        if _is_true(item):
            continue
        if _is_false(item):
            return term_false()
        if item.kind is SmtTermKind.AND:
            nested = _simplify_and(*item.arguments)
            if _is_false(nested):
                return term_false()
            if _is_true(nested):
                continue
            if nested.kind is SmtTermKind.AND:
                kept.extend(nested.arguments)
            else:
                kept.append(nested)
            continue
        kept.append(item)
    return term_and(*kept)


def _negate(term: SmtTerm) -> SmtTerm:
    if _is_true(term):
        return term_false()
    if _is_false(term):
        return term_true()
    if term.kind is SmtTermKind.NOT:
        return term.arguments[0]
    flipped = _FLIPPED_COMPARISON.get(term.kind)
    if flipped is not None:
        return SmtTerm(flipped, arguments=term.arguments)
    return term_not(term)


def _atomic_predicates(term: SmtTerm) -> tuple[SmtTerm, ...]:
    if _is_true(term) or _is_false(term):
        return ()
    if term.kind in {SmtTermKind.AND, SmtTermKind.OR, SmtTermKind.IMPLIES, SmtTermKind.IFF}:
        atoms: list[SmtTerm] = []
        for item in term.arguments:
            atoms.extend(_atomic_predicates(item))
        return tuple(atoms)
    if term.kind is SmtTermKind.NOT:
        inner = term.arguments[0]
        if inner.kind in {SmtTermKind.AND, SmtTermKind.OR, SmtTermKind.IMPLIES}:
            return _atomic_predicates(_negate(inner) if inner.kind is not SmtTermKind.AND else term)
        if inner.kind in _COMPARISON_KINDS:
            return (term,)
        return _atomic_predicates(inner)
    return (term,)


def _same_term(left: SmtTerm, right: SmtTerm) -> bool:
    return (
        left.kind is right.kind
        and left.value == right.value
        and left.binders == right.binders
        and len(left.arguments) == len(right.arguments)
        and all(_same_term(first, second) for first, second in zip(left.arguments, right.arguments))
    )


def _is_trivial_predicate(term: SmtTerm) -> bool:
    """True for tautologies/contradictions that cannot split an abstract state."""

    if _is_true(term) or _is_false(term):
        return True
    if term.kind is SmtTermKind.NOT:
        return _is_trivial_predicate(term.arguments[0])
    if term.kind in {SmtTermKind.EQ, SmtTermKind.IFF, SmtTermKind.LE, SmtTermKind.GE}:
        return _same_term(term.arguments[0], term.arguments[1])
    if term.kind is SmtTermKind.DISTINCT and len(term.arguments) >= 2:
        first = term.arguments[0]
        return all(_same_term(first, item) for item in term.arguments[1:])
    if term.kind in {SmtTermKind.LT, SmtTermKind.GT}:
        return _same_term(term.arguments[0], term.arguments[1])
    return False


def _ssa(name: str, index: int) -> str:
    return f"{name}@{index}"


def _rename_symbols(term: SmtTerm, mapping: Mapping[str, str]) -> SmtTerm:
    renamed = {
        name: term_symbol(mapping[name])
        for name in _symbols(term)
        if name in mapping
    }
    return _substitute(term, renamed) if renamed else term


def _project_to_original(term: SmtTerm, *, index: int, variables: Sequence[str]) -> SmtTerm:
    mapping = {_ssa(name, index): name for name in variables}
    for name in _symbols(term):
        if name in variables:
            mapping[name] = name
            continue
        for variable in variables:
            prefix = f"{variable}@"
            if name.startswith(prefix) and name[len(prefix):].isdigit():
                mapping[name] = variable
                break
            if name == f"post_{variable}":
                mapping[name] = variable
                break
    return _rename_symbols(term, mapping)


@dataclass(frozen=True, slots=True)
class CegarAssignment:
    variable: str
    expression: SmtTerm

    def __post_init__(self) -> None:
        object.__setattr__(self, "variable", _text(self.variable, "assignment variable"))
        object.__setattr__(self, "expression", _require_term(self.expression, "assignment expression"))

    def to_dict(self) -> dict[str, Any]:
        return {"expression": self.expression.to_dict(), "variable": self.variable}


@dataclass(frozen=True, slots=True)
class CegarTransition:
    transition_id: str
    source: str
    target: str
    guard: SmtTerm = field(default_factory=term_true)
    assignments: tuple[CegarAssignment, ...] = ()
    source_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "transition_id", _text(self.transition_id, "transition_id"))
        object.__setattr__(self, "source", _text(self.source, "transition source"))
        object.__setattr__(self, "target", _text(self.target, "transition target"))
        object.__setattr__(self, "guard", _require_term(self.guard, "transition guard"))
        assignments = tuple(self.assignments)
        names = [item.variable for item in assignments]
        if len(names) != len(set(names)):
            raise CegarError(f"transition {self.transition_id} assigns a variable more than once")
        object.__setattr__(self, "assignments", assignments)
        object.__setattr__(self, "source_ref", _optional_text(self.source_ref, "transition source_ref"))

    def assignment_map(self) -> dict[str, SmtTerm]:
        return {item.variable: item.expression for item in self.assignments}

    def to_dict(self) -> dict[str, Any]:
        return {
            "assignments": [item.to_dict() for item in self.assignments],
            "guard": self.guard.to_dict(),
            "source": self.source,
            "source_ref": self.source_ref,
            "target": self.target,
            "transition_id": self.transition_id,
        }


@dataclass(frozen=True, slots=True)
class CegarTransitionSystem:
    """Concrete control-flow graph with QF_LIA guards and assignments."""

    system_id: str
    variables: tuple[str, ...]
    locations: tuple[str, ...]
    initial_location: str
    error_locations: tuple[str, ...]
    initial_condition: SmtTerm
    transitions: tuple[CegarTransition, ...]
    source_identities: FrozenMap | Mapping[str, Any] = field(default_factory=FrozenMap)
    theory: str = QUALIFIED_INTERPOLATION_THEORY
    schema: str = CEGAR_SYSTEM_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "system_id", _text(self.system_id, "system_id"))
        object.__setattr__(self, "variables", _unique(self.variables, "variables"))
        object.__setattr__(self, "locations", _unique(self.locations, "locations"))
        object.__setattr__(self, "initial_location", _text(self.initial_location, "initial_location"))
        object.__setattr__(
            self, "error_locations", _unique(self.error_locations, "error_locations")
        )
        object.__setattr__(
            self, "initial_condition", _require_term(self.initial_condition, "initial_condition")
        )
        transitions = tuple(self.transitions)
        ids = [item.transition_id for item in transitions]
        if len(ids) != len(set(ids)):
            raise CegarError("transition IDs must be unique")
        locations = set(self.locations)
        if self.initial_location not in locations:
            raise CegarError("initial_location must be a declared location")
        if not self.error_locations:
            raise CegarError("system requires at least one error location")
        if not set(self.error_locations) <= locations:
            raise CegarError("error_locations must be declared locations")
        for item in transitions:
            if item.source not in locations or item.target not in locations:
                raise CegarError(f"transition {item.transition_id} references an unknown location")
            used = _symbols(item.guard)
            for assignment in item.assignments:
                used.add(assignment.variable)
                used.update(_symbols(assignment.expression))
            if not used <= set(self.variables):
                raise CegarError(
                    f"transition {item.transition_id} uses undeclared variables "
                    f"{sorted(used - set(self.variables))}"
                )
        object.__setattr__(self, "transitions", transitions)
        identities = (
            self.source_identities
            if isinstance(self.source_identities, FrozenMap)
            else FrozenMap(self.source_identities)
        )
        if not identities:
            raise CegarError("system requires source identities")
        for key, value in identities.items():
            if not isinstance(value, str) or not value or value.strip() != value:
                raise CegarError(f"source identity {key!r} must be a trimmed non-empty string")
        object.__setattr__(self, "source_identities", identities)
        object.__setattr__(self, "theory", _text(self.theory, "theory"))
        if self.schema != CEGAR_SYSTEM_SCHEMA:
            raise CegarError("unsupported CEGAR system schema")
        unknown_init = _symbols(self.initial_condition) - set(self.variables)
        if unknown_init:
            raise CegarError(f"initial_condition uses undeclared variables {sorted(unknown_init)}")

    @property
    def system_cid(self) -> str:
        return canonical_identity(
            self.to_dict(),
            domain="logic.software-verification.cegar-system",
            schema_version=self.schema,
        ).cid

    def outgoing(self, location: str) -> tuple[CegarTransition, ...]:
        return tuple(item for item in self.transitions if item.source == location)

    def transition_by_id(self, transition_id: str) -> CegarTransition:
        for item in self.transitions:
            if item.transition_id == transition_id:
                return item
        raise CegarError(f"unknown transition {transition_id}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_locations": list(self.error_locations),
            "initial_condition": self.initial_condition.to_dict(),
            "initial_location": self.initial_location,
            "locations": list(self.locations),
            "schema": self.schema,
            "source_identities": self.source_identities.to_dict(),
            "system_id": self.system_id,
            "theory": self.theory,
            "transitions": [item.to_dict() for item in self.transitions],
            "variables": list(self.variables),
        }


@dataclass(frozen=True, slots=True)
class CegarBudget:
    """Hard resource bounds.  Exhaustion is a typed terminal disposition."""

    max_iterations: int = DEFAULT_MAX_ITERATIONS
    max_predicates: int = DEFAULT_MAX_PREDICATES
    max_abstract_states: int = DEFAULT_MAX_ABSTRACT_STATES
    max_trace_length: int = DEFAULT_MAX_TRACE_LENGTH
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    memory_limit_mib: int = DEFAULT_MEMORY_LIMIT_MIB
    max_symbols: int = DEFAULT_MAX_SYMBOLS
    max_term_nodes: int = DEFAULT_MAX_TERM_NODES
    allow_interpolation: bool = True
    allow_unsat_core: bool = True
    allow_weakest_precondition: bool = True
    allow_reviewed_predicates: bool = True
    schema: str = CEGAR_BUDGET_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "max_iterations", _positive_int(self.max_iterations, "max_iterations"))
        object.__setattr__(self, "max_predicates", _positive_int(self.max_predicates, "max_predicates"))
        object.__setattr__(
            self, "max_abstract_states", _positive_int(self.max_abstract_states, "max_abstract_states")
        )
        object.__setattr__(
            self, "max_trace_length", _positive_int(self.max_trace_length, "max_trace_length")
        )
        object.__setattr__(self, "timeout_ms", _positive_int(self.timeout_ms, "timeout_ms"))
        object.__setattr__(
            self, "memory_limit_mib", _positive_int(self.memory_limit_mib, "memory_limit_mib")
        )
        object.__setattr__(self, "max_symbols", _positive_int(self.max_symbols, "max_symbols"))
        object.__setattr__(
            self, "max_term_nodes", _positive_int(self.max_term_nodes, "max_term_nodes")
        )
        for name in (
            "allow_interpolation",
            "allow_unsat_core",
            "allow_weakest_precondition",
            "allow_reviewed_predicates",
        ):
            object.__setattr__(self, name, _bool(getattr(self, name), name))
        if self.max_iterations > ABSOLUTE_MAX_ITERATIONS:
            raise CegarError(f"max_iterations exceeds {ABSOLUTE_MAX_ITERATIONS}")
        if self.max_predicates > ABSOLUTE_MAX_PREDICATES:
            raise CegarError(f"max_predicates exceeds {ABSOLUTE_MAX_PREDICATES}")
        if self.max_abstract_states > ABSOLUTE_MAX_ABSTRACT_STATES:
            raise CegarError(f"max_abstract_states exceeds {ABSOLUTE_MAX_ABSTRACT_STATES}")
        if self.max_trace_length > ABSOLUTE_MAX_TRACE_LENGTH:
            raise CegarError(f"max_trace_length exceeds {ABSOLUTE_MAX_TRACE_LENGTH}")
        if self.schema != CEGAR_BUDGET_SCHEMA:
            raise CegarError("unsupported CEGAR budget schema")

    def interpolation_bounds(self, theory: str) -> InterpolationBounds:
        return InterpolationBounds(
            timeout_ms=self.timeout_ms,
            memory_limit_mib=self.memory_limit_mib,
            max_symbols=self.max_symbols,
            max_term_nodes=self.max_term_nodes,
            theory=theory,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_interpolation": self.allow_interpolation,
            "allow_reviewed_predicates": self.allow_reviewed_predicates,
            "allow_unsat_core": self.allow_unsat_core,
            "allow_weakest_precondition": self.allow_weakest_precondition,
            "max_abstract_states": self.max_abstract_states,
            "max_iterations": self.max_iterations,
            "max_predicates": self.max_predicates,
            "max_symbols": self.max_symbols,
            "max_term_nodes": self.max_term_nodes,
            "max_trace_length": self.max_trace_length,
            "memory_limit_mib": self.memory_limit_mib,
            "schema": self.schema,
            "timeout_ms": self.timeout_ms,
        }


@dataclass(frozen=True, slots=True)
class CegarPredicate:
    predicate_id: str
    formula: SmtTerm
    origin: PredicateOrigin | str
    reviewed: bool = False
    reviewer: str = ""
    review_ref: str = ""
    source_ref: str = ""
    schema: str = CEGAR_PREDICATE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "predicate_id", _text(self.predicate_id, "predicate_id"))
        object.__setattr__(self, "formula", _require_term(self.formula, "predicate formula"))
        try:
            origin = (
                self.origin
                if isinstance(self.origin, PredicateOrigin)
                else PredicateOrigin(self.origin)
            )
        except ValueError as error:
            raise CegarError(str(error)) from error
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "reviewed", _bool(self.reviewed, "reviewed"))
        object.__setattr__(self, "reviewer", _optional_text(self.reviewer, "reviewer"))
        object.__setattr__(self, "review_ref", _optional_text(self.review_ref, "review_ref"))
        object.__setattr__(self, "source_ref", _optional_text(self.source_ref, "predicate source_ref"))
        if origin is PredicateOrigin.REVIEWED:
            if not self.reviewed or not self.reviewer or not self.review_ref:
                raise CegarError("reviewed predicates require reviewer and review_ref")
        elif self.reviewed:
            raise CegarError("only reviewed-origin predicates may set reviewed=True")
        if self.schema != CEGAR_PREDICATE_SCHEMA:
            raise CegarError("unsupported CEGAR predicate schema")

    @property
    def formula_cid(self) -> str:
        return _term_cid(self.formula, "predicate")

    def to_dict(self) -> dict[str, Any]:
        origin = self.origin
        return {
            "formula": self.formula.to_dict(),
            "formula_cid": self.formula_cid,
            "origin": origin.value if isinstance(origin, PredicateOrigin) else origin,
            "predicate_id": self.predicate_id,
            "review_ref": self.review_ref,
            "reviewed": self.reviewed,
            "reviewer": self.reviewer,
            "schema": self.schema,
            "source_ref": self.source_ref,
        }


def reviewed_predicate(
    predicate_id: str,
    formula: SmtTerm,
    *,
    reviewer: str,
    review_ref: str,
    source_ref: str = "",
) -> CegarPredicate:
    """Admit a human-reviewed predicate.  Unreviewed formulas are rejected."""

    return CegarPredicate(
        predicate_id=predicate_id,
        formula=formula,
        origin=PredicateOrigin.REVIEWED,
        reviewed=True,
        reviewer=reviewer,
        review_ref=review_ref,
        source_ref=source_ref,
    )


@dataclass(frozen=True, slots=True)
class CegarTraceStep:
    transition_id: str
    source: str
    target: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "transition_id": self.transition_id,
        }


@dataclass(frozen=True, slots=True)
class CegarTrace:
    locations: tuple[str, ...]
    steps: tuple[CegarTraceStep, ...]
    classification: TraceClassification | str
    model: FrozenMap | Mapping[str, Any] = field(default_factory=FrozenMap)
    reason: str = ""
    solver_receipt_id: str = ""
    schema: str = CEGAR_TRACE_SCHEMA

    def __post_init__(self) -> None:
        locations = tuple(_text(item, "trace location") for item in self.locations)
        steps = tuple(self.steps)
        if not locations:
            raise CegarError("trace requires at least the initial location")
        if len(locations) != len(steps) + 1:
            raise CegarError("trace locations must be one longer than steps")
        for index, step in enumerate(steps):
            if step.source != locations[index] or step.target != locations[index + 1]:
                raise CegarError("trace steps must match the location sequence")
        object.__setattr__(self, "locations", locations)
        object.__setattr__(self, "steps", steps)
        try:
            classification = (
                self.classification
                if isinstance(self.classification, TraceClassification)
                else TraceClassification(self.classification)
            )
        except ValueError as error:
            raise CegarError(str(error)) from error
        object.__setattr__(self, "classification", classification)
        object.__setattr__(
            self,
            "model",
            self.model if isinstance(self.model, FrozenMap) else FrozenMap(self.model),
        )
        object.__setattr__(self, "reason", str(self.reason))
        object.__setattr__(self, "solver_receipt_id", str(self.solver_receipt_id))
        if self.schema != CEGAR_TRACE_SCHEMA:
            raise CegarError("unsupported CEGAR trace schema")

    @property
    def transition_ids(self) -> tuple[str, ...]:
        return tuple(item.transition_id for item in self.steps)

    @property
    def trace_cid(self) -> str:
        return canonical_identity(
            self.to_dict(),
            domain="logic.software-verification.cegar-trace",
            schema_version=self.schema,
        ).cid

    def to_dict(self) -> dict[str, Any]:
        classification = self.classification
        return {
            "classification": (
                classification.value
                if isinstance(classification, TraceClassification)
                else classification
            ),
            "locations": list(self.locations),
            "model": self.model.to_dict(),
            "reason": self.reason,
            "schema": self.schema,
            "solver_receipt_id": self.solver_receipt_id,
            "steps": [item.to_dict() for item in self.steps],
            "transition_ids": list(self.transition_ids),
        }


@dataclass(frozen=True, slots=True)
class CegarSolverObservation:
    status: SmtCheckStatus | str
    model: FrozenMap | Mapping[str, Any] = field(default_factory=FrozenMap)
    unsat_core: tuple[str, ...] = ()
    receipt_id: str = ""
    reason: str = ""
    core_validated: bool = False
    model_validated: bool = False
    provider: str = ""
    provider_version: str = ""
    schema: str = CEGAR_SOLVER_RESULT_SCHEMA

    def __post_init__(self) -> None:
        try:
            status = (
                self.status if isinstance(self.status, SmtCheckStatus) else SmtCheckStatus(self.status)
            )
        except ValueError as error:
            raise CegarError(str(error)) from error
        object.__setattr__(self, "status", status)
        object.__setattr__(
            self,
            "model",
            self.model if isinstance(self.model, FrozenMap) else FrozenMap(self.model),
        )
        object.__setattr__(self, "unsat_core", tuple(self.unsat_core))
        object.__setattr__(self, "receipt_id", str(self.receipt_id))
        object.__setattr__(self, "reason", str(self.reason))
        object.__setattr__(self, "core_validated", _bool(self.core_validated, "core_validated"))
        object.__setattr__(self, "model_validated", _bool(self.model_validated, "model_validated"))
        object.__setattr__(self, "provider", str(self.provider))
        object.__setattr__(self, "provider_version", str(self.provider_version))
        if self.schema != CEGAR_SOLVER_RESULT_SCHEMA:
            raise CegarError("unsupported CEGAR solver observation schema")

    def to_dict(self) -> dict[str, Any]:
        status = self.status
        return {
            "core_validated": self.core_validated,
            "model": self.model.to_dict(),
            "model_validated": self.model_validated,
            "provider": self.provider,
            "provider_version": self.provider_version,
            "reason": self.reason,
            "receipt_id": self.receipt_id,
            "schema": self.schema,
            "status": status.value if isinstance(status, SmtCheckStatus) else status,
            "unsat_core": list(self.unsat_core),
        }


@dataclass(frozen=True, slots=True)
class CegarSolverQuery:
    query_id: str
    kind: CegarQueryKind | str
    symbols: tuple[str, ...]
    assertions: tuple[tuple[str, SmtTerm, str], ...]
    timeout_ms: int
    metadata: FrozenMap | Mapping[str, Any] = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_id", _text(self.query_id, "query_id"))
        try:
            kind = self.kind if isinstance(self.kind, CegarQueryKind) else CegarQueryKind(self.kind)
        except ValueError as error:
            raise CegarError(str(error)) from error
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "symbols", _unique(self.symbols, "query symbols"))
        assertions = tuple(
            (_text(item[0], "assertion id"), _require_term(item[1], "assertion formula"), str(item[2]))
            for item in self.assertions
        )
        ids = [item[0] for item in assertions]
        if len(ids) != len(set(ids)):
            raise CegarError("query assertion IDs must be unique")
        object.__setattr__(self, "assertions", assertions)
        object.__setattr__(self, "timeout_ms", _positive_int(self.timeout_ms, "query timeout_ms"))
        object.__setattr__(
            self,
            "metadata",
            self.metadata if isinstance(self.metadata, FrozenMap) else FrozenMap(self.metadata),
        )


class CegarSolverBackend(Protocol):
    def check(self, query: CegarSolverQuery) -> CegarSolverObservation:
        """Return a typed SAT/UNSAT/unknown/timeout/unavailable observation."""


class CegarInterpolator(Protocol):
    def interpolate(
        self,
        partition_a: SmtTerm,
        partition_b: SmtTerm,
        *,
        bounds: InterpolationBounds,
        theory: str,
    ) -> ValidatedInterpolantReceipt:
        """Return an independently admitted interpolant or a typed non-success."""


@dataclass(frozen=True, slots=True)
class CegarRefinement:
    iteration: int
    authority: RefinementAuthority | str
    predicates: tuple[CegarPredicate, ...]
    partition_a_cid: str
    partition_b_cid: str
    shared_vocabulary: tuple[str, ...]
    interpolant_vocabulary: tuple[str, ...]
    theory: str
    provider: str
    provider_version: str
    bounds: InterpolationBounds | Mapping[str, Any]
    source_identities: FrozenMap | Mapping[str, Any]
    interpolant_status: str = ""
    interpolant_cid: str = ""
    interpolant_receipt_cid: str = ""
    fallback_kind: str = ""
    fallback_core: tuple[str, ...] = ()
    fallback_receipt: str = ""
    reason: str = ""
    schema: str = CEGAR_REFINEMENT_SCHEMA

    def __post_init__(self) -> None:
        if isinstance(self.iteration, bool) or not isinstance(self.iteration, int) or self.iteration < 0:
            raise CegarError("refinement iteration must be a non-negative integer")
        try:
            authority = (
                self.authority
                if isinstance(self.authority, RefinementAuthority)
                else RefinementAuthority(self.authority)
            )
        except ValueError as error:
            raise CegarError(str(error)) from error
        object.__setattr__(self, "authority", authority)
        predicates = tuple(self.predicates)
        if not predicates:
            raise CegarError("refinement requires at least one admitted predicate")
        object.__setattr__(self, "predicates", predicates)
        object.__setattr__(self, "partition_a_cid", _text(self.partition_a_cid, "partition_a_cid"))
        object.__setattr__(self, "partition_b_cid", _text(self.partition_b_cid, "partition_b_cid"))
        object.__setattr__(
            self, "shared_vocabulary", tuple(sorted(set(self.shared_vocabulary)))
        )
        object.__setattr__(
            self, "interpolant_vocabulary", tuple(sorted(set(self.interpolant_vocabulary)))
        )
        object.__setattr__(self, "theory", _text(self.theory, "theory"))
        object.__setattr__(self, "provider", _text(self.provider, "provider"))
        object.__setattr__(self, "provider_version", str(self.provider_version))
        bounds = (
            self.bounds
            if isinstance(self.bounds, InterpolationBounds)
            else InterpolationBounds(**dict(self.bounds))
        )
        object.__setattr__(self, "bounds", bounds)
        object.__setattr__(
            self,
            "source_identities",
            self.source_identities
            if isinstance(self.source_identities, FrozenMap)
            else FrozenMap(self.source_identities),
        )
        object.__setattr__(self, "interpolant_status", str(self.interpolant_status))
        object.__setattr__(self, "interpolant_cid", str(self.interpolant_cid))
        object.__setattr__(self, "interpolant_receipt_cid", str(self.interpolant_receipt_cid))
        object.__setattr__(self, "fallback_kind", str(self.fallback_kind))
        object.__setattr__(self, "fallback_core", tuple(sorted(set(self.fallback_core))))
        object.__setattr__(self, "fallback_receipt", str(self.fallback_receipt))
        object.__setattr__(self, "reason", str(self.reason))
        if self.schema != CEGAR_REFINEMENT_SCHEMA:
            raise CegarError("unsupported CEGAR refinement schema")
        if authority is RefinementAuthority.VALIDATED_INTERPOLANT:
            if self.interpolant_status != InterpolationStatus.VALIDATED.value or not self.interpolant_cid:
                raise CegarError("interpolant refinement requires a validated interpolant identity")
        else:
            if self.interpolant_cid:
                raise CegarError("non-interpolant refinement must not fabricate an interpolant identity")

    @property
    def refinement_cid(self) -> str:
        return canonical_identity(
            self.to_dict(),
            domain="logic.software-verification.cegar-refinement",
            schema_version=self.schema,
        ).cid

    def to_dict(self) -> dict[str, Any]:
        authority = self.authority
        return {
            "authority": authority.value if isinstance(authority, RefinementAuthority) else authority,
            "bounds": self.bounds.to_dict(),
            "fallback_core": list(self.fallback_core),
            "fallback_kind": self.fallback_kind,
            "fallback_receipt": self.fallback_receipt,
            "interpolant_cid": self.interpolant_cid,
            "interpolant_receipt_cid": self.interpolant_receipt_cid,
            "interpolant_status": self.interpolant_status,
            "interpolant_vocabulary": list(self.interpolant_vocabulary),
            "iteration": self.iteration,
            "partition_a_cid": self.partition_a_cid,
            "partition_b_cid": self.partition_b_cid,
            "predicates": [item.to_dict() for item in self.predicates],
            "provider": self.provider,
            "provider_version": self.provider_version,
            "reason": self.reason,
            "schema": self.schema,
            "shared_vocabulary": list(self.shared_vocabulary),
            "source_identities": self.source_identities.to_dict(),
            "theory": self.theory,
        }


@dataclass(frozen=True, slots=True)
class CegarIteration:
    iteration: int
    abstract_states_explored: int
    search_complete: bool
    trace: CegarTrace | None
    refinement: CegarRefinement | None
    solver_receipt_ids: tuple[str, ...] = ()
    reason: str = ""
    schema: str = CEGAR_ITERATION_SCHEMA

    def __post_init__(self) -> None:
        if isinstance(self.iteration, bool) or not isinstance(self.iteration, int) or self.iteration < 0:
            raise CegarError("iteration must be a non-negative integer")
        if (
            isinstance(self.abstract_states_explored, bool)
            or not isinstance(self.abstract_states_explored, int)
            or self.abstract_states_explored < 0
        ):
            raise CegarError("abstract_states_explored must be a non-negative integer")
        object.__setattr__(self, "search_complete", _bool(self.search_complete, "search_complete"))
        if self.trace is not None and not isinstance(self.trace, CegarTrace):
            raise CegarError("iteration trace must be a CegarTrace or None")
        if self.refinement is not None and not isinstance(self.refinement, CegarRefinement):
            raise CegarError("iteration refinement must be a CegarRefinement or None")
        object.__setattr__(self, "solver_receipt_ids", tuple(self.solver_receipt_ids))
        object.__setattr__(self, "reason", str(self.reason))
        if self.schema != CEGAR_ITERATION_SCHEMA:
            raise CegarError("unsupported CEGAR iteration schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "abstract_states_explored": self.abstract_states_explored,
            "reason": self.reason,
            "refinement": None if self.refinement is None else self.refinement.to_dict(),
            "schema": self.schema,
            "search_complete": self.search_complete,
            "solver_receipt_ids": list(self.solver_receipt_ids),
            "trace": None if self.trace is None else self.trace.to_dict(),
            "iteration": self.iteration,
        }


@dataclass(frozen=True, slots=True)
class CegarRunReceipt:
    disposition: CegarDisposition | str
    system_cid: str
    theory: str
    provider: str
    provider_version: str
    bounds: CegarBudget | Mapping[str, Any]
    source_identities: FrozenMap | Mapping[str, Any]
    predicates: tuple[CegarPredicate, ...]
    refinements: tuple[CegarRefinement, ...]
    counterexamples: tuple[CegarTrace, ...]
    spurious_traces: tuple[CegarTrace, ...]
    iterations: tuple[CegarIteration, ...]
    reason: str = ""
    limitations: tuple[str, ...] = ()
    schema: str = CEGAR_RECEIPT_SCHEMA
    interface: str = CEGAR_INTERFACE

    INTERFACE: ClassVar[str] = CEGAR_INTERFACE

    def __post_init__(self) -> None:
        try:
            disposition = (
                self.disposition
                if isinstance(self.disposition, CegarDisposition)
                else CegarDisposition(self.disposition)
            )
        except ValueError as error:
            raise CegarError(str(error)) from error
        object.__setattr__(self, "disposition", disposition)
        object.__setattr__(self, "system_cid", _text(self.system_cid, "system_cid"))
        object.__setattr__(self, "theory", _text(self.theory, "theory"))
        object.__setattr__(self, "provider", _text(self.provider, "provider"))
        object.__setattr__(self, "provider_version", str(self.provider_version))
        bounds = self.bounds if isinstance(self.bounds, CegarBudget) else CegarBudget(**dict(self.bounds))
        object.__setattr__(self, "bounds", bounds)
        object.__setattr__(
            self,
            "source_identities",
            self.source_identities
            if isinstance(self.source_identities, FrozenMap)
            else FrozenMap(self.source_identities),
        )
        object.__setattr__(self, "predicates", tuple(self.predicates))
        object.__setattr__(self, "refinements", tuple(self.refinements))
        object.__setattr__(self, "counterexamples", tuple(self.counterexamples))
        object.__setattr__(self, "spurious_traces", tuple(self.spurious_traces))
        object.__setattr__(self, "iterations", tuple(self.iterations))
        object.__setattr__(self, "reason", str(self.reason))
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))
        object.__setattr__(self, "interface", _text(self.interface, "interface"))
        if self.schema != CEGAR_RECEIPT_SCHEMA:
            raise CegarError("unsupported CEGAR receipt schema")
        if self.interface != CEGAR_INTERFACE:
            raise CegarError("unsupported CEGAR interface")
        if any(item.classification is not TraceClassification.REAL for item in self.counterexamples):
            raise CegarError("counterexamples may contain only real traces")
        if any(item.classification is not TraceClassification.SPURIOUS for item in self.spurious_traces):
            raise CegarError("spurious_traces may contain only spurious traces")
        if disposition is CegarDisposition.DISPROVED:
            if not self.counterexamples:
                raise CegarError("disproved receipt requires a real counterexample")
            if self.iterations:
                last = self.iterations[-1]
                if last.trace is None or last.trace.classification is not TraceClassification.REAL:
                    raise CegarError("disproved receipt requires the last iteration to retain a real trace")
        if disposition is CegarDisposition.PROVED:
            if self.counterexamples:
                raise CegarError("proved receipt cannot retain a real counterexample")
            if not self.iterations:
                raise CegarError("incomplete search never upgrades to proved")
            last = self.iterations[-1]
            if not last.search_complete:
                raise CegarError("incomplete search never upgrades to proved")
            if last.trace is not None and last.trace.classification is TraceClassification.REAL:
                raise CegarError("proved receipt cannot retain a real counterexample")

    @property
    def receipt_cid(self) -> str:
        return canonical_identity(
            self.to_dict(),
            domain="logic.software-verification.cegar-receipt",
            schema_version=self.schema,
        ).cid

    def to_dict(self) -> dict[str, Any]:
        disposition = self.disposition
        return {
            "bounds": self.bounds.to_dict(),
            "counterexamples": [item.to_dict() for item in self.counterexamples],
            "disposition": (
                disposition.value if isinstance(disposition, CegarDisposition) else disposition
            ),
            "interface": self.interface,
            "iterations": [item.to_dict() for item in self.iterations],
            "limitations": list(self.limitations),
            "predicates": [item.to_dict() for item in self.predicates],
            "provider": self.provider,
            "provider_version": self.provider_version,
            "reason": self.reason,
            "refinements": [item.to_dict() for item in self.refinements],
            "schema": self.schema,
            "source_identities": self.source_identities.to_dict(),
            "spurious_traces": [item.to_dict() for item in self.spurious_traces],
            "system_cid": self.system_cid,
            "theory": self.theory,
        }


def _eval_term(term: SmtTerm, model: Mapping[str, int]) -> int | bool:
    kind = term.kind
    args = [_eval_term(item, model) for item in term.arguments]
    if kind is SmtTermKind.TRUE:
        return True
    if kind is SmtTermKind.FALSE:
        return False
    if kind is SmtTermKind.INT:
        return int(term.value)
    if kind is SmtTermKind.SYMBOL:
        if term.value not in model:
            raise CegarError(f"model is missing {term.value}")
        return model[term.value]
    if kind is SmtTermKind.NOT:
        return not bool(args[0])
    if kind is SmtTermKind.AND:
        return all(bool(item) for item in args)
    if kind is SmtTermKind.OR:
        return any(bool(item) for item in args)
    if kind is SmtTermKind.IMPLIES:
        return (not bool(args[0])) or bool(args[1])
    if kind is SmtTermKind.IFF or kind is SmtTermKind.EQ:
        return args[0] == args[1]
    if kind is SmtTermKind.DISTINCT:
        return len(set(args)) == len(args)
    if kind is SmtTermKind.LT:
        return args[0] < args[1]
    if kind is SmtTermKind.LE:
        return args[0] <= args[1]
    if kind is SmtTermKind.GT:
        return args[0] > args[1]
    if kind is SmtTermKind.GE:
        return args[0] >= args[1]
    if kind is SmtTermKind.ADD:
        return int(sum(int(item) for item in args))
    if kind is SmtTermKind.SUB:
        return int(args[0]) - int(args[1])
    if kind is SmtTermKind.MUL:
        result = 1
        for item in args:
            result *= int(item)
        return result
    if kind is SmtTermKind.NEG:
        return -int(args[0])
    if kind is SmtTermKind.ITE:
        return args[1] if bool(args[0]) else args[2]
    raise CegarError(f"local conjunction solver cannot evaluate {kind.value}")


def _flatten_conjunction(term: SmtTerm) -> list[SmtTerm]:
    if _is_true(term):
        return []
    if term.kind is SmtTermKind.AND:
        items: list[SmtTerm] = []
        for argument in term.arguments:
            items.extend(_flatten_conjunction(argument))
        return items
    return [term]


def _nnf_atom(term: SmtTerm) -> SmtTerm | None:
    if term.kind is SmtTermKind.NOT:
        inner = term.arguments[0]
        if inner.kind is SmtTermKind.NOT:
            return _nnf_atom(inner.arguments[0])
        flipped = _FLIPPED_COMPARISON.get(inner.kind)
        if flipped is not None:
            return SmtTerm(flipped, arguments=inner.arguments)
        if _is_true(inner):
            return term_false()
        if _is_false(inner):
            return term_true()
        return None
    return term


def _as_int(term: SmtTerm) -> int | None:
    if term.kind is SmtTermKind.INT:
        return int(term.value)
    if term.kind is SmtTermKind.NEG and term.arguments[0].kind is SmtTermKind.INT:
        return -int(term.arguments[0].value)
    return None


def _offset_sum(term: SmtTerm) -> tuple[dict[str, int], int] | None:
    if term.kind is SmtTermKind.SYMBOL:
        return {term.value: 1}, 0
    constant = _as_int(term)
    if constant is not None:
        return {}, constant
    if term.kind is SmtTermKind.NEG:
        inner = _offset_sum(term.arguments[0])
        if inner is None:
            return None
        coeffs, constant = inner
        return {name: -value for name, value in coeffs.items()}, -constant
    if term.kind is SmtTermKind.ADD:
        coeffs: dict[str, int] = {}
        constant = 0
        for argument in term.arguments:
            part = _offset_sum(argument)
            if part is None:
                return None
            part_coeffs, part_constant = part
            constant += part_constant
            for name, value in part_coeffs.items():
                coeffs[name] = coeffs.get(name, 0) + value
        return {name: value for name, value in coeffs.items() if value}, constant
    if term.kind is SmtTermKind.SUB:
        left = _offset_sum(term.arguments[0])
        right = _offset_sum(term.arguments[1])
        if left is None or right is None:
            return None
        coeffs = dict(left[0])
        for name, value in right[0].items():
            coeffs[name] = coeffs.get(name, 0) - value
        return {name: value for name, value in coeffs.items() if value}, left[1] - right[1]
    return None


def decide_qf_lia_conjunction(formulas: Sequence[SmtTerm]) -> tuple[SmtCheckStatus, dict[str, int], str]:
    """Sound incomplete decision procedure for QF_LIA conjunctions.

    SAT is returned only with a model that evaluates every formula.  UNSAT is
    returned only after substitution yields a contradiction.  Everything else
    is ``unknown`` and must not be treated as a proof.
    """

    atoms: list[SmtTerm] = []
    for formula in formulas:
        for item in _flatten_conjunction(formula):
            if _is_false(item):
                return SmtCheckStatus.UNSAT, {}, "false atom"
            if _is_true(item):
                continue
            if item.kind in {SmtTermKind.OR, SmtTermKind.IMPLIES, SmtTermKind.ITE}:
                return SmtCheckStatus.UNKNOWN, {}, "boolean structure is outside the local fragment"
            normalized = _nnf_atom(item)
            if normalized is None:
                return SmtCheckStatus.UNKNOWN, {}, "negation is outside the local fragment"
            if _is_false(normalized):
                return SmtCheckStatus.UNSAT, {}, "false atom"
            if _is_true(normalized):
                continue
            atoms.append(normalized)
    equals: dict[str, int] = {}
    bounds: dict[str, list[int | None]] = {}
    residuals: list[SmtTerm] = []
    symbols: set[str] = set()
    for atom in atoms:
        if atom.kind is SmtTermKind.DISTINCT and len(atom.arguments) >= 2:
            first = atom.arguments[0]
            if all(_same_term(first, item) for item in atom.arguments[1:]):
                return SmtCheckStatus.UNSAT, {}, "distinct arguments are identical"
        symbols.update(_symbols(atom))
        if atom.kind is SmtTermKind.EQ:
            left, right = _offset_sum(atom.arguments[0]), _offset_sum(atom.arguments[1])
            if left is not None and right is not None:
                coeffs = dict(left[0])
                for name, value in right[0].items():
                    coeffs[name] = coeffs.get(name, 0) - value
                constant = right[1] - left[1]
                nonzero = [(name, value) for name, value in coeffs.items() if value]
                if not nonzero:
                    if constant != 0:
                        return SmtCheckStatus.UNSAT, {}, "equality contradiction"
                    continue
                if len(nonzero) == 1 and abs(nonzero[0][1]) == 1:
                    name, coeff = nonzero[0]
                    value = constant if coeff == 1 else -constant
                    if name in equals and equals[name] != value:
                        return SmtCheckStatus.UNSAT, {}, f"{name} has conflicting equalities"
                    equals[name] = value
                    continue
        residuals.append(atom)
        if atom.kind in {SmtTermKind.LT, SmtTermKind.LE, SmtTermKind.GT, SmtTermKind.GE}:
            left, right = _offset_sum(atom.arguments[0]), _offset_sum(atom.arguments[1])
            if left is None or right is None:
                continue
            coeffs = dict(left[0])
            for name, value in right[0].items():
                coeffs[name] = coeffs.get(name, 0) - value
            constant = right[1] - left[1]
            nonzero = [(name, value) for name, value in coeffs.items() if value]
            if len(nonzero) != 1 or abs(nonzero[0][1]) != 1:
                continue
            name, coeff = nonzero[0]
            lo, hi = bounds.setdefault(name, [None, None])
            if coeff == 1:
                if atom.kind is SmtTermKind.LT:
                    candidate = constant - 1
                    bounds[name][1] = candidate if hi is None else min(hi, candidate)
                elif atom.kind is SmtTermKind.LE:
                    bounds[name][1] = constant if hi is None else min(hi, constant)
                elif atom.kind is SmtTermKind.GT:
                    candidate = constant + 1
                    bounds[name][0] = candidate if lo is None else max(lo, candidate)
                else:
                    bounds[name][0] = constant if lo is None else max(lo, constant)
            else:
                flipped = {
                    SmtTermKind.LT: SmtTermKind.GT,
                    SmtTermKind.LE: SmtTermKind.GE,
                    SmtTermKind.GT: SmtTermKind.LT,
                    SmtTermKind.GE: SmtTermKind.LE,
                }[atom.kind]
                negated = -constant
                if flipped is SmtTermKind.LT:
                    candidate = negated - 1
                    bounds[name][1] = candidate if hi is None else min(hi, candidate)
                elif flipped is SmtTermKind.LE:
                    bounds[name][1] = negated if hi is None else min(hi, negated)
                elif flipped is SmtTermKind.GT:
                    candidate = negated + 1
                    bounds[name][0] = candidate if lo is None else max(lo, candidate)
                else:
                    bounds[name][0] = negated if lo is None else max(lo, negated)
    for name, (lo, hi) in bounds.items():
        if lo is not None and hi is not None and lo > hi:
            return SmtCheckStatus.UNSAT, {}, f"{name} has an empty interval"
        if name in equals:
            value = equals[name]
            if (lo is not None and value < lo) or (hi is not None and value > hi):
                return SmtCheckStatus.UNSAT, {}, f"{name} equality is outside its interval"
    literals: set[int] = set(equals.values())
    for atom in atoms:
        for symbol in _walk_ints(atom):
            literals.add(symbol)
    candidates = sorted(literals | {item + delta for item in literals for delta in (-2, -1, 0, 1, 2)} | {0, -1, 1})
    free = [name for name in sorted(symbols) if name not in equals]
    if len(free) > 3:
        return SmtCheckStatus.UNKNOWN, {}, "too many free symbols for the local fragment"
    domains: list[list[int]] = []
    fully_enumerated = True
    for name in free:
        lo, hi = bounds.get(name, [None, None])
        if lo is not None and hi is not None:
            if hi - lo > 16:
                fully_enumerated = False
                mid = (lo + hi) // 2
                sample = sorted({lo, lo + 1, mid, hi - 1, hi})
                domains.append([value for value in sample if lo <= value <= hi])
            else:
                domains.append(list(range(lo, hi + 1)))
        else:
            fully_enumerated = False
            window = list(candidates)
            if lo is not None:
                window = [item for item in window if item >= lo] or [lo, lo + 1, lo + 2]
            if hi is not None:
                window = [item for item in window if item <= hi] or [hi - 2, hi - 1, hi]
            domains.append(window or [0, -1, 1])

    def _search(index: int, model: dict[str, int]) -> dict[str, int] | None:
        if index == len(free):
            try:
                if all(bool(_eval_term(atom, model)) for atom in atoms):
                    return dict(model)
            except CegarError:
                return None
            return None
        name = free[index]
        for value in domains[index]:
            model[name] = value
            found = _search(index + 1, model)
            if found is not None:
                return found
        model.pop(name, None)
        return None

    seed = dict(equals)
    if not free:
        try:
            if all(bool(_eval_term(atom, seed)) for atom in atoms):
                return SmtCheckStatus.SAT, seed, ""
            return SmtCheckStatus.UNSAT, {}, "ground conjunction is false"
        except CegarError:
            return SmtCheckStatus.UNKNOWN, {}, "ground evaluation failed"
    found = _search(0, seed)
    if found is not None:
        return SmtCheckStatus.SAT, found, ""
    if fully_enumerated and all(
        bounds.get(name, [None, None])[0] is not None and bounds.get(name, [None, None])[1] is not None
        for name in free
    ):
        return SmtCheckStatus.UNSAT, {}, "no model inside derived intervals"
    return SmtCheckStatus.UNKNOWN, {}, "local conjunction solver could not decide"


def _walk_ints(term: SmtTerm) -> set[int]:
    values = {int(term.value)} if term.kind is SmtTermKind.INT else set()
    for item in term.arguments:
        values.update(_walk_ints(item))
    return values


class LocalConjunctionSolver:
    """Sound incomplete backend used when a scripted or local fragment is enough."""

    provider = LOCAL_CONJUNCTION_PROVIDER
    provider_version = "1"

    def check(self, query: CegarSolverQuery) -> CegarSolverObservation:
        formulas = [item[1] for item in query.assertions]
        status, model, reason = decide_qf_lia_conjunction(formulas)
        core = tuple(item[0] for item in query.assertions) if status is SmtCheckStatus.UNSAT else ()
        receipt = canonical_identity(
            {
                "assertions": [item[0] for item in query.assertions],
                "kind": query.kind.value if isinstance(query.kind, CegarQueryKind) else query.kind,
                "model": model,
                "query_id": query.query_id,
                "status": status.value,
            },
            domain="logic.software-verification.cegar-local-solver",
            schema_version=CEGAR_SOLVER_RESULT_SCHEMA,
        ).cid
        return CegarSolverObservation(
            status=status,
            model=FrozenMap({name: str(value) for name, value in model.items()}),
            unsat_core=core,
            receipt_id=receipt,
            reason=reason,
            core_validated=status is SmtCheckStatus.UNSAT,
            model_validated=status is SmtCheckStatus.SAT,
            provider=self.provider,
            provider_version=self.provider_version,
        )


class IncrementalSmtCegarSolver:
    """Default backend: a fresh incremental Z3 session per query."""

    provider = "z3"

    def check(self, query: CegarSolverQuery) -> CegarSolverObservation:
        session = None
        try:
            session = open_incremental_smt_session(
                session_id=query.query_id,
                translator_identity=TRANSLATOR_IDENTITY,
                theory_fingerprint=THEORY_FINGERPRINT,
                policy_root=query.query_id,
                configuration_root=query.query_id,
                environment_root="local-cegar-smt@1",
                timeout_ms=query.timeout_ms,
            )
            for symbol in query.symbols:
                session.declare_symbol(symbol, INT_SORT)
            for assertion_id, formula, source_ref in query.assertions:
                session.add_named_assertion(
                    assertion_id,
                    formula,
                    source_ref=source_ref or assertion_id,
                    obligation_id=query.query_id,
                )
            result = session.check()
            provider = session.fingerprint.provider
            provider_version = session.fingerprint.provider_version
        except IncrementalSmtUnavailable as error:
            return CegarSolverObservation(
                status=SmtCheckStatus.UNAVAILABLE,
                reason=str(error),
                provider=self.provider,
                provider_version="unavailable",
            )
        except IncrementalSmtError as error:
            return CegarSolverObservation(
                status=SmtCheckStatus.UNKNOWN,
                reason=str(error),
                provider=self.provider,
                provider_version="unknown",
            )
        finally:
            if session is not None:
                session.close()
        return CegarSolverObservation(
            status=result.status,
            model=result.model,
            unsat_core=result.unsat_core,
            receipt_id=result.receipt_id,
            reason=result.unknown_reason,
            core_validated=result.core_validated,
            model_validated=result.model_validated,
            provider=provider,
            provider_version=provider_version,
        )


class ValidatedInterpolantBackend:
    """Default interpolator: never admits a term that failed independent checks."""

    def interpolate(
        self,
        partition_a: SmtTerm,
        partition_b: SmtTerm,
        *,
        bounds: InterpolationBounds,
        theory: str,
    ) -> ValidatedInterpolantReceipt:
        return compute_and_validate_interpolant(
            partition_a,
            partition_b,
            theory=theory,
            bounds=bounds,
        )


class ScriptedCegarSolver:
    """Test/double backend that answers by query kind and optional script."""

    def __init__(
        self,
        script: Mapping[str, CegarSolverObservation] | None = None,
        *,
        default: CegarSolverObservation | None = None,
        fallback: CegarSolverBackend | None = None,
    ) -> None:
        self._script = dict(script or {})
        self._default = default
        self._fallback = fallback

    def check(self, query: CegarSolverQuery) -> CegarSolverObservation:
        if query.query_id in self._script:
            return self._script[query.query_id]
        key = query.kind.value if isinstance(query.kind, CegarQueryKind) else query.kind
        if key in self._script:
            return self._script[key]
        locations = query.metadata.get("locations")
        if isinstance(locations, tuple):
            location_key = "locations:" + ">".join(str(item) for item in locations)
            if location_key in self._script:
                return self._script[location_key]
        if self._fallback is not None:
            return self._fallback.check(query)
        if self._default is not None:
            return self._default
        raise CegarError(f"scripted solver has no answer for {query.query_id}")


@dataclass
class _SearchOutcome:
    trace: CegarTrace | None
    explored: int
    complete: bool
    observation: CegarSolverObservation | None
    reason: str


def _predicate_literal(predicate: CegarPredicate, truth: bool, mapping: Mapping[str, SmtTerm]) -> SmtTerm:
    formula = _substitute(predicate.formula, mapping)
    return formula if truth else _negate(formula)


def _valuation_space(count: int) -> tuple[tuple[bool, ...], ...]:
    if count == 0:
        return ((),)
    return tuple(tuple(bool(index >> bit & 1) for bit in range(count)) for index in range(1 << count))


def _path_assertions(
    system: CegarTransitionSystem,
    trace: CegarTrace,
) -> tuple[tuple[str, ...], tuple[tuple[str, SmtTerm, str], ...]]:
    symbols: list[str] = []
    for index in range(len(trace.locations)):
        for name in system.variables:
            symbols.append(_ssa(name, index))
    assertions: list[tuple[str, SmtTerm, str]] = []
    init_map = {name: term_symbol(_ssa(name, 0)) for name in system.variables}
    assertions.append(
        ("init", _substitute(system.initial_condition, init_map), system.system_cid)
    )
    for step_index, step in enumerate(trace.steps):
        transition = system.transition_by_id(step.transition_id)
        current = {name: term_symbol(_ssa(name, step_index)) for name in system.variables}
        nxt = {name: term_symbol(_ssa(name, step_index + 1)) for name in system.variables}
        if not _is_true(transition.guard):
            assertions.append(
                (
                    f"guard:{transition.transition_id}:{step_index}",
                    _substitute(transition.guard, current),
                    transition.source_ref or transition.transition_id,
                )
            )
        assigned = transition.assignment_map()
        for name in system.variables:
            rhs = _substitute(assigned[name], current) if name in assigned else current[name]
            assertions.append(
                (
                    f"assign:{transition.transition_id}:{name}:{step_index}",
                    term_eq(nxt[name], rhs),
                    transition.source_ref or transition.transition_id,
                )
            )
    return tuple(symbols), tuple(assertions)


def _partition_terms(
    system: CegarTransitionSystem,
    trace: CegarTrace,
    cut: int,
) -> tuple[SmtTerm, SmtTerm, int]:
    _symbols_unused, assertions = _path_assertions(system, trace)
    if cut <= 0 or cut >= len(assertions):
        cut = max(1, min(len(assertions) - 1, cut))
    prefix = _simplify_and(*(item[1] for item in assertions[:cut]))
    suffix = _simplify_and(*(item[1] for item in assertions[cut:]))
    return prefix, suffix, cut


def _reach_condition(system: CegarTransitionSystem, transitions: Sequence[CegarTransition]) -> SmtTerm:
    condition = term_true()
    for transition in reversed(tuple(transitions)):
        assigned = transition.assignment_map()
        if assigned:
            condition = _substitute(condition, assigned)
        if not _is_true(transition.guard):
            condition = _simplify_and(transition.guard, condition)
    return condition


class _CegarEngine:
    def __init__(
        self,
        system: CegarTransitionSystem,
        *,
        budget: CegarBudget,
        reviewed: tuple[CegarPredicate, ...],
        solver: CegarSolverBackend,
        interpolator: CegarInterpolator,
        clock: Callable[[], float],
    ) -> None:
        self.system = system
        self.budget = budget
        self.reviewed = reviewed
        self.solver = solver
        self.interpolator = interpolator
        self.clock = clock
        self.started = clock()
        self.predicates: list[CegarPredicate] = []
        self.used_reviewed: set[str] = set()
        self.counterexamples: list[CegarTrace] = []
        self.spurious: list[CegarTrace] = []
        self.refinements: list[CegarRefinement] = []
        self.iterations: list[CegarIteration] = []
        self.limitations: list[str] = []
        self.provider = "unspecified"
        self.provider_version = ""
        self.query_serial = 0

    def elapsed_ms(self) -> int:
        return int((self.clock() - self.started) * 1000)

    def remaining_ms(self) -> int:
        return max(1, self.budget.timeout_ms - self.elapsed_ms())

    def timed_out(self) -> bool:
        return self.elapsed_ms() >= self.budget.timeout_ms

    def next_query_id(self, label: str) -> str:
        self.query_serial += 1
        return f"cegar-{label}-{self.query_serial}"

    def remember_provider(self, observation: CegarSolverObservation) -> None:
        if observation.provider:
            self.provider = observation.provider
            self.provider_version = observation.provider_version

    def check(self, query: CegarSolverQuery) -> CegarSolverObservation:
        observation = self.solver.check(query)
        self.remember_provider(observation)
        return observation

    def predicate_bits(self) -> int:
        return len(self.predicates)

    def abstract_init(self, valuation: tuple[bool, ...]) -> CegarSolverObservation:
        mapping = {name: term_symbol(name) for name in self.system.variables}
        assertions: list[tuple[str, SmtTerm, str]] = [
            ("init", _substitute(self.system.initial_condition, mapping), self.system.system_cid)
        ]
        for predicate, truth in zip(self.predicates, valuation, strict=True):
            assertions.append(
                (
                    f"pred:{predicate.predicate_id}:{int(truth)}",
                    _predicate_literal(predicate, truth, mapping),
                    predicate.source_ref or predicate.predicate_id,
                )
            )
        return self.check(
            CegarSolverQuery(
                query_id=self.next_query_id("abs-init"),
                kind=CegarQueryKind.ABSTRACT_INIT,
                symbols=self.system.variables,
                assertions=tuple(assertions),
                timeout_ms=self.remaining_ms(),
                metadata={"location": self.system.initial_location},
            )
        )

    def abstract_step(
        self,
        transition: CegarTransition,
        current: tuple[bool, ...],
        nxt: tuple[bool, ...],
    ) -> CegarSolverObservation:
        pre = {name: term_symbol(name) for name in self.system.variables}
        post = {name: term_symbol(f"post_{name}") for name in self.system.variables}
        symbols = self.system.variables + tuple(f"post_{name}" for name in self.system.variables)
        assertions: list[tuple[str, SmtTerm, str]] = []
        for predicate, truth in zip(self.predicates, current, strict=True):
            assertions.append(
                (
                    f"pre:{predicate.predicate_id}:{int(truth)}",
                    _predicate_literal(predicate, truth, pre),
                    predicate.predicate_id,
                )
            )
        if not _is_true(transition.guard):
            assertions.append(
                (
                    f"guard:{transition.transition_id}",
                    _substitute(transition.guard, pre),
                    transition.source_ref or transition.transition_id,
                )
            )
        assigned = transition.assignment_map()
        for name in self.system.variables:
            rhs = _substitute(assigned[name], pre) if name in assigned else pre[name]
            assertions.append(
                (
                    f"assign:{name}",
                    term_eq(post[name], rhs),
                    transition.transition_id,
                )
            )
        for predicate, truth in zip(self.predicates, nxt, strict=True):
            assertions.append(
                (
                    f"post:{predicate.predicate_id}:{int(truth)}",
                    _predicate_literal(predicate, truth, post),
                    predicate.predicate_id,
                )
            )
        return self.check(
            CegarSolverQuery(
                query_id=self.next_query_id("abs-step"),
                kind=CegarQueryKind.ABSTRACT_STEP,
                symbols=symbols,
                assertions=tuple(assertions),
                timeout_ms=self.remaining_ms(),
                metadata={
                    "source": transition.source,
                    "target": transition.target,
                    "transition_id": transition.transition_id,
                },
            )
        )

    def search(self) -> _SearchOutcome:
        valuations = _valuation_space(self.predicate_bits())
        queue: deque[tuple[str, tuple[bool, ...]]] = deque()
        parent: dict[tuple[str, tuple[bool, ...]], tuple[tuple[str, tuple[bool, ...]], CegarTransition] | None] = {}
        explored = 0
        last_observation: CegarSolverObservation | None = None
        truncated = False
        for valuation in valuations:
            if self.timed_out():
                return _SearchOutcome(None, explored, False, last_observation, "timeout")
            observation = self.abstract_init(valuation)
            last_observation = observation
            if observation.status is SmtCheckStatus.TIMEOUT:
                return _SearchOutcome(None, explored, False, observation, observation.reason or "timeout")
            if observation.status is SmtCheckStatus.UNAVAILABLE:
                return _SearchOutcome(None, explored, False, observation, observation.reason or "unavailable")
            if observation.status is SmtCheckStatus.UNKNOWN:
                # Incomplete init must stay enabled; skipping it would unsoundly prove.
                self.limitations.append("abstract_init_unknown_overapproximated")
            elif observation.status is not SmtCheckStatus.SAT:
                continue
            state = (self.system.initial_location, valuation)
            parent[state] = None
            queue.append(state)
            explored += 1
            if self.system.initial_location in self.system.error_locations:
                return _SearchOutcome(
                    self._rebuild(parent, state),
                    explored,
                    True,
                    observation,
                    "abstract error path",
                )
            if explored >= self.budget.max_abstract_states:
                return _SearchOutcome(
                    None,
                    explored,
                    False,
                    observation,
                    "abstract state budget exhausted",
                )
        if not queue:
            return _SearchOutcome(None, explored, True, last_observation, "no abstract initial state")
        while queue:
            if self.timed_out():
                return _SearchOutcome(None, explored, False, last_observation, "timeout")
            location, valuation = queue.popleft()
            depth = self._depth(parent, (location, valuation))
            if depth >= self.budget.max_trace_length:
                truncated = True
                continue
            for transition in self.system.outgoing(location):
                for nxt in valuations:
                    if self.timed_out():
                        return _SearchOutcome(None, explored, False, last_observation, "timeout")
                    if not self.predicates:
                        observation = CegarSolverObservation(
                            status=SmtCheckStatus.SAT,
                            model_validated=True,
                            provider=self.provider or LOCAL_CONJUNCTION_PROVIDER,
                            provider_version=self.provider_version or "1",
                            receipt_id="cfg-edge",
                        )
                    else:
                        observation = self.abstract_step(transition, valuation, nxt)
                    last_observation = observation
                    if observation.status is SmtCheckStatus.TIMEOUT:
                        return _SearchOutcome(None, explored, False, observation, observation.reason or "timeout")
                    if observation.status is SmtCheckStatus.UNAVAILABLE:
                        return _SearchOutcome(
                            None, explored, False, observation, observation.reason or "unavailable"
                        )
                    if observation.status is SmtCheckStatus.UNKNOWN:
                        # Undecided steps stay enabled so weak interpolants can still exhaust.
                        self.limitations.append("abstract_step_unknown_overapproximated")
                    elif observation.status is not SmtCheckStatus.SAT:
                        continue
                    successor = (transition.target, nxt)
                    if successor in parent:
                        continue
                    parent[successor] = ((location, valuation), transition)
                    queue.append(successor)
                    explored += 1
                    if transition.target in self.system.error_locations:
                        return _SearchOutcome(
                            self._rebuild(parent, successor),
                            explored,
                            True,
                            observation,
                            "abstract error path",
                        )
                    if explored >= self.budget.max_abstract_states:
                        return _SearchOutcome(
                            None,
                            explored,
                            False,
                            observation,
                            "abstract state budget exhausted",
                        )
        if truncated:
            return _SearchOutcome(
                None,
                explored,
                False,
                last_observation,
                "max_trace_length truncated remaining abstract successors",
            )
        return _SearchOutcome(None, explored, True, last_observation, "abstract error unreachable")

    def _depth(
        self,
        parent: Mapping[
            tuple[str, tuple[bool, ...]],
            tuple[tuple[str, tuple[bool, ...]], CegarTransition] | None,
        ],
        state: tuple[str, tuple[bool, ...]],
    ) -> int:
        depth = 0
        current = state
        while parent[current] is not None:
            current = parent[current][0]
            depth += 1
        return depth

    def _rebuild(
        self,
        parent: Mapping[
            tuple[str, tuple[bool, ...]],
            tuple[tuple[str, tuple[bool, ...]], CegarTransition] | None,
        ],
        state: tuple[str, tuple[bool, ...]],
    ) -> CegarTrace:
        locations = [state[0]]
        steps: list[CegarTraceStep] = []
        current = state
        while parent[current] is not None:
            previous, transition = parent[current]
            steps.append(
                CegarTraceStep(
                    transition_id=transition.transition_id,
                    source=previous[0],
                    target=current[0],
                )
            )
            locations.append(previous[0])
            current = previous
        locations.reverse()
        steps.reverse()
        return CegarTrace(
            locations=tuple(locations),
            steps=tuple(steps),
            classification=TraceClassification.UNKNOWN,
            reason="abstract error path",
        )

    def concretize(self, trace: CegarTrace) -> tuple[CegarTrace, CegarSolverObservation]:
        symbols, assertions = _path_assertions(self.system, trace)
        observation = self.check(
            CegarSolverQuery(
                query_id=self.next_query_id("path"),
                kind=CegarQueryKind.PATH,
                symbols=symbols,
                assertions=assertions,
                timeout_ms=self.remaining_ms(),
                metadata={"locations": trace.locations, "transition_ids": trace.transition_ids},
            )
        )
        if observation.status is SmtCheckStatus.SAT and observation.model_validated:
            classified = TraceClassification.REAL
            reason = "concrete model satisfies the error path"
        elif observation.status is SmtCheckStatus.UNSAT:
            classified = TraceClassification.SPURIOUS
            reason = "path formula is unsatisfiable"
        elif observation.status is SmtCheckStatus.TIMEOUT:
            classified = TraceClassification.TIMEOUT
            reason = observation.reason or "path check timed out"
        elif observation.status is SmtCheckStatus.UNAVAILABLE:
            classified = TraceClassification.UNAVAILABLE
            reason = observation.reason or "path check unavailable"
        else:
            classified = TraceClassification.UNKNOWN
            reason = observation.reason or "path check returned unknown"
        return (
            CegarTrace(
                locations=trace.locations,
                steps=trace.steps,
                classification=classified,
                model=observation.model,
                reason=reason,
                solver_receipt_id=observation.receipt_id,
            ),
            observation,
        )

    def first_infeasible_cut(self, trace: CegarTrace) -> tuple[int, CegarSolverObservation | None]:
        symbols, assertions = _path_assertions(self.system, trace)
        last: CegarSolverObservation | None = None
        for cut in range(1, len(assertions) + 1):
            observation = self.check(
                CegarSolverQuery(
                    query_id=self.next_query_id("prefix"),
                    kind=CegarQueryKind.PREFIX,
                    symbols=symbols,
                    assertions=assertions[:cut],
                    timeout_ms=self.remaining_ms(),
                    metadata={"cut": cut},
                )
            )
            last = observation
            if observation.status is SmtCheckStatus.UNSAT:
                return cut, observation
            if observation.status in {
                SmtCheckStatus.TIMEOUT,
                SmtCheckStatus.UNAVAILABLE,
                SmtCheckStatus.UNKNOWN,
            }:
                return cut, observation
        return max(1, len(assertions) - 1), last

    def known_formula_cids(self) -> set[str]:
        known: set[str] = set()
        for predicate in self.predicates:
            known.add(predicate.formula_cid)
            known.add(_term_cid(_negate(predicate.formula), "predicate"))
        return known

    def admit_formulas(
        self,
        formulas: Sequence[SmtTerm],
        *,
        origin: PredicateOrigin,
        source_ref: str,
        reviewed: bool = False,
        reviewer: str = "",
        review_ref: str = "",
        prefix: str,
    ) -> list[CegarPredicate]:
        admitted: list[CegarPredicate] = []
        known = self.known_formula_cids()
        for formula in formulas:
            if _is_true(formula) or _is_false(formula) or _is_trivial_predicate(formula):
                continue
            if not _symbols(formula) <= set(self.system.variables):
                continue
            cid = _term_cid(formula, "predicate")
            if cid in known:
                continue
            predicate = CegarPredicate(
                predicate_id=f"{prefix}:{cid[-12:]}",
                formula=formula,
                origin=origin,
                reviewed=reviewed,
                reviewer=reviewer,
                review_ref=review_ref,
                source_ref=source_ref,
            )
            admitted.append(predicate)
            known.add(cid)
            known.add(_term_cid(_negate(formula), "predicate"))
            if len(self.predicates) + len(admitted) >= self.budget.max_predicates:
                break
        return admitted

    def refine(
        self,
        iteration: int,
        trace: CegarTrace,
        path_observation: CegarSolverObservation,
    ) -> CegarRefinement | CegarDisposition | CegarSolverObservation:
        if self.timed_out():
            return CegarDisposition.TIMEOUT
        cut, prefix_observation = self.first_infeasible_cut(trace)
        if prefix_observation is not None and prefix_observation.status is SmtCheckStatus.TIMEOUT:
            return prefix_observation
        if prefix_observation is not None and prefix_observation.status is SmtCheckStatus.UNAVAILABLE:
            return prefix_observation
        if prefix_observation is not None and prefix_observation.status is SmtCheckStatus.UNKNOWN:
            self.limitations.append("prefix_cut_unknown")
        split = max(1, cut - 1)
        partition_a, partition_b, used_cut = _partition_terms(self.system, trace, split)
        partition_a_cid = _term_cid(partition_a, "a")
        partition_b_cid = _term_cid(partition_b, "b")
        shared = tuple(sorted(_symbols(partition_a) & _symbols(partition_b)))
        bounds = self.budget.interpolation_bounds(self.system.theory)
        interpolant_receipt: ValidatedInterpolantReceipt | None = None
        if self.budget.allow_interpolation:
            try:
                interpolant_receipt = self.interpolator.interpolate(
                    partition_a,
                    partition_b,
                    bounds=bounds,
                    theory=self.system.theory,
                )
            except (
                InterpolationError,
                IncrementalSmtError,
                ImportError,
                OSError,
                AttributeError,
                TypeError,
                ValueError,
                RuntimeError,
            ):
                self.limitations.append("interpolator_raised")
                interpolant_receipt = None
            if interpolant_receipt is not None and interpolant_receipt.status is InterpolationStatus.VALIDATED:
                if interpolant_receipt.interpolant is None:
                    raise CegarError("validated interpolant receipt fabricated a missing term")
                cut_index = min(len(trace.steps), max(0, used_cut - 1))
                formulas = [
                    _project_to_original(atom, index=cut_index, variables=self.system.variables)
                    for atom in _atomic_predicates(interpolant_receipt.interpolant)
                ]
                admitted = self.admit_formulas(
                    formulas,
                    origin=PredicateOrigin.INTERPOLANT,
                    source_ref=interpolant_receipt.receipt_cid,
                    prefix=f"itp-{iteration}",
                )
                if admitted:
                    return CegarRefinement(
                        iteration=iteration,
                        authority=RefinementAuthority.VALIDATED_INTERPOLANT,
                        predicates=tuple(admitted),
                        partition_a_cid=partition_a_cid,
                        partition_b_cid=partition_b_cid,
                        shared_vocabulary=shared,
                        interpolant_vocabulary=interpolant_receipt.interpolant_vocabulary,
                        theory=interpolant_receipt.theory,
                        provider=interpolant_receipt.provider,
                        provider_version=interpolant_receipt.provider_version,
                        bounds=bounds,
                        source_identities=self.system.source_identities,
                        interpolant_status=InterpolationStatus.VALIDATED.value,
                        interpolant_cid=interpolant_receipt.interpolant_cid,
                        interpolant_receipt_cid=interpolant_receipt.receipt_cid,
                        reason="validated interpolant admitted as refinement predicates",
                    )
        core_ids = ()
        core_receipt = ""
        if (
            prefix_observation is not None
            and prefix_observation.status is SmtCheckStatus.UNSAT
            and prefix_observation.core_validated
            and prefix_observation.unsat_core
        ):
            # Prefer the first unsat prefix; later frame equalities project to tautologies.
            core_ids = prefix_observation.unsat_core
            core_receipt = prefix_observation.receipt_id
        elif path_observation.core_validated and path_observation.unsat_core:
            core_ids = path_observation.unsat_core
            core_receipt = path_observation.receipt_id
        elif (
            interpolant_receipt is not None
            and interpolant_receipt.status is InterpolationStatus.FALLBACK
            and interpolant_receipt.fallback_validated
        ):
            core_ids = interpolant_receipt.fallback_core
            core_receipt = interpolant_receipt.fallback_receipt
        if self.budget.allow_unsat_core and core_ids:
            _, assertions = _path_assertions(self.system, trace)
            by_id = {item[0]: item[1] for item in assertions}
            formulas: list[SmtTerm] = []
            for assertion_id in core_ids:
                if assertion_id not in by_id:
                    continue
                formulas.extend(
                    _project_to_original(atom, index=min(len(trace.steps), max(0, used_cut - 1)), variables=self.system.variables)
                    for atom in _atomic_predicates(by_id[assertion_id])
                )
            admitted = self.admit_formulas(
                formulas,
                origin=PredicateOrigin.UNSAT_CORE,
                source_ref=core_receipt or path_observation.receipt_id,
                prefix=f"core-{iteration}",
            )
            if admitted:
                return CegarRefinement(
                    iteration=iteration,
                    authority=RefinementAuthority.VALIDATED_UNSAT_CORE,
                    predicates=tuple(admitted),
                    partition_a_cid=partition_a_cid,
                    partition_b_cid=partition_b_cid,
                    shared_vocabulary=shared,
                    interpolant_vocabulary=(),
                    theory=self.system.theory,
                    provider=path_observation.provider or self.provider or "unsat-core",
                    provider_version=path_observation.provider_version or self.provider_version,
                    bounds=bounds,
                    source_identities=self.system.source_identities,
                    interpolant_status=(
                        interpolant_receipt.status.value if interpolant_receipt is not None else ""
                    ),
                    fallback_kind="validated_unsat_core",
                    fallback_core=core_ids,
                    fallback_receipt=core_receipt,
                    reason="validated unsat core admitted as refinement predicates",
                )
        if self.budget.allow_weakest_precondition:
            suffix = [
                self.system.transition_by_id(step.transition_id)
                for step in trace.steps[max(0, min(len(trace.steps) - 1, used_cut - 1)) :]
            ]
            if not suffix:
                suffix = [self.system.transition_by_id(step.transition_id) for step in trace.steps]
            condition = _reach_condition(self.system, suffix)
            admitted = self.admit_formulas(
                (condition, *_atomic_predicates(condition)),
                origin=PredicateOrigin.WEAKEST_PRECONDITION,
                source_ref=trace.trace_cid,
                prefix=f"wp-{iteration}",
            )
            if admitted:
                return CegarRefinement(
                    iteration=iteration,
                    authority=RefinementAuthority.WEAKEST_PRECONDITION,
                    predicates=tuple(admitted),
                    partition_a_cid=partition_a_cid,
                    partition_b_cid=partition_b_cid,
                    shared_vocabulary=shared,
                    interpolant_vocabulary=(),
                    theory=self.system.theory,
                    provider="weakest-precondition",
                    provider_version="1",
                    bounds=bounds,
                    source_identities=self.system.source_identities,
                    interpolant_status=(
                        interpolant_receipt.status.value if interpolant_receipt is not None else ""
                    ),
                    reason="weakest-precondition of the infeasible suffix admitted",
                )
        if self.budget.allow_reviewed_predicates:
            remaining = [
                item
                for item in self.reviewed
                if item.predicate_id not in self.used_reviewed
                and item.formula_cid not in self.known_formula_cids()
            ]
            if remaining:
                chosen = remaining[0]
                self.used_reviewed.add(chosen.predicate_id)
                return CegarRefinement(
                    iteration=iteration,
                    authority=RefinementAuthority.REVIEWED_PREDICATE,
                    predicates=(chosen,),
                    partition_a_cid=partition_a_cid,
                    partition_b_cid=partition_b_cid,
                    shared_vocabulary=shared,
                    interpolant_vocabulary=(),
                    theory=self.system.theory,
                    provider="reviewed-predicate",
                    provider_version=chosen.reviewer,
                    bounds=bounds,
                    source_identities=self.system.source_identities,
                    interpolant_status=(
                        interpolant_receipt.status.value if interpolant_receipt is not None else ""
                    ),
                    reason=f"reviewed predicate {chosen.predicate_id} admitted",
                )
        return CegarDisposition.UNKNOWN

    def finish(
        self,
        disposition: CegarDisposition,
        reason: str,
        extra_limitations: Sequence[str] = (),
    ) -> CegarRunReceipt:
        limitations = tuple(self.limitations) + tuple(extra_limitations)
        if self.provider == LOCAL_CONJUNCTION_PROVIDER:
            limitations = limitations + (
                "local_conjunction_solver_is_sound_incomplete_and_not_kernel_evidence",
            )
        return CegarRunReceipt(
            disposition=disposition,
            system_cid=self.system.system_cid,
            theory=self.system.theory,
            provider=self.provider or "unspecified",
            provider_version=self.provider_version,
            bounds=self.budget,
            source_identities=self.system.source_identities,
            predicates=tuple(self.predicates),
            refinements=tuple(self.refinements),
            counterexamples=tuple(self.counterexamples),
            spurious_traces=tuple(self.spurious),
            iterations=tuple(self.iterations),
            reason=reason,
            limitations=limitations,
        )

    def run(self) -> CegarRunReceipt:
        if self.system.theory != QUALIFIED_INTERPOLATION_THEORY:
            return self.finish(
                CegarDisposition.UNKNOWN,
                "CEGAR adapter is qualified only for QF_LIA",
                extra_limitations=("unqualified_theory",),
            )
        for iteration in range(self.budget.max_iterations):
            if self.timed_out():
                return self.finish(CegarDisposition.TIMEOUT, "CEGAR budget timeout_ms elapsed")
            search = self.search()
            search_timeout = search.reason == "timeout" or (
                search.observation is not None and search.observation.status is SmtCheckStatus.TIMEOUT
            )
            if search_timeout:
                self.iterations.append(
                    CegarIteration(
                        iteration=iteration,
                        abstract_states_explored=search.explored,
                        search_complete=False,
                        trace=None,
                        refinement=None,
                        solver_receipt_ids=(
                            (search.observation.receipt_id,)
                            if search.observation is not None and search.observation.receipt_id
                            else ()
                        ),
                        reason=search.reason,
                    )
                )
                return self.finish(CegarDisposition.TIMEOUT, search.reason or "abstract search timed out")
            if search.observation is not None and search.observation.status is SmtCheckStatus.UNAVAILABLE:
                self.iterations.append(
                    CegarIteration(
                        iteration=iteration,
                        abstract_states_explored=search.explored,
                        search_complete=False,
                        trace=None,
                        refinement=None,
                        solver_receipt_ids=((search.observation.receipt_id,) if search.observation.receipt_id else ()),
                        reason=search.reason,
                    )
                )
                return self.finish(
                    CegarDisposition.UNAVAILABLE, search.reason or "solver unavailable"
                )
            if search.trace is None and search.complete:
                self.iterations.append(
                    CegarIteration(
                        iteration=iteration,
                        abstract_states_explored=search.explored,
                        search_complete=True,
                        trace=None,
                        refinement=None,
                        reason=search.reason or "abstract error unreachable",
                    )
                )
                return self.finish(
                    CegarDisposition.PROVED,
                    "boolean abstraction has no error path",
                )
            if search.trace is None:
                self.iterations.append(
                    CegarIteration(
                        iteration=iteration,
                        abstract_states_explored=search.explored,
                        search_complete=False,
                        trace=None,
                        refinement=None,
                        reason=search.reason,
                    )
                )
                return self.finish(
                    CegarDisposition.BUDGET_EXHAUSTED,
                    search.reason or "abstract search budget exhausted",
                )
            concrete, observation = self.concretize(search.trace)
            if concrete.classification is TraceClassification.REAL:
                self.counterexamples.append(concrete)
                self.iterations.append(
                    CegarIteration(
                        iteration=iteration,
                        abstract_states_explored=search.explored,
                        search_complete=True,
                        trace=concrete,
                        refinement=None,
                        solver_receipt_ids=(observation.receipt_id,) if observation.receipt_id else (),
                        reason=concrete.reason,
                    )
                )
                return self.finish(
                    CegarDisposition.DISPROVED,
                    "real counterexample is feasible in the concrete system",
                )
            if concrete.classification is TraceClassification.TIMEOUT:
                self.iterations.append(
                    CegarIteration(
                        iteration=iteration,
                        abstract_states_explored=search.explored,
                        search_complete=True,
                        trace=concrete,
                        refinement=None,
                        solver_receipt_ids=(observation.receipt_id,) if observation.receipt_id else (),
                        reason=concrete.reason,
                    )
                )
                return self.finish(CegarDisposition.TIMEOUT, concrete.reason)
            if concrete.classification is TraceClassification.UNAVAILABLE:
                self.iterations.append(
                    CegarIteration(
                        iteration=iteration,
                        abstract_states_explored=search.explored,
                        search_complete=True,
                        trace=concrete,
                        refinement=None,
                        solver_receipt_ids=(observation.receipt_id,) if observation.receipt_id else (),
                        reason=concrete.reason,
                    )
                )
                return self.finish(CegarDisposition.UNAVAILABLE, concrete.reason)
            if concrete.classification is TraceClassification.UNKNOWN:
                self.iterations.append(
                    CegarIteration(
                        iteration=iteration,
                        abstract_states_explored=search.explored,
                        search_complete=True,
                        trace=concrete,
                        refinement=None,
                        solver_receipt_ids=(observation.receipt_id,) if observation.receipt_id else (),
                        reason=concrete.reason,
                    )
                )
                return self.finish(CegarDisposition.UNKNOWN, concrete.reason)
            self.spurious.append(concrete)
            if len(self.predicates) >= self.budget.max_predicates:
                self.iterations.append(
                    CegarIteration(
                        iteration=iteration,
                        abstract_states_explored=search.explored,
                        search_complete=True,
                        trace=concrete,
                        refinement=None,
                        solver_receipt_ids=(observation.receipt_id,) if observation.receipt_id else (),
                        reason="predicate budget exhausted",
                    )
                )
                return self.finish(
                    CegarDisposition.BUDGET_EXHAUSTED,
                    "max_predicates reached before the spurious trace could be refined",
                )
            if iteration == self.budget.max_iterations - 1:
                self.iterations.append(
                    CegarIteration(
                        iteration=iteration,
                        abstract_states_explored=search.explored,
                        search_complete=True,
                        trace=concrete,
                        refinement=None,
                        solver_receipt_ids=(observation.receipt_id,) if observation.receipt_id else (),
                        reason="iteration budget exhausted after a spurious trace",
                    )
                )
                return self.finish(
                    CegarDisposition.BUDGET_EXHAUSTED,
                    "max_iterations reached with a remaining spurious trace",
                )
            refined = self.refine(iteration, concrete, observation)
            if isinstance(refined, CegarDisposition):
                self.iterations.append(
                    CegarIteration(
                        iteration=iteration,
                        abstract_states_explored=search.explored,
                        search_complete=True,
                        trace=concrete,
                        refinement=None,
                        solver_receipt_ids=(observation.receipt_id,) if observation.receipt_id else (),
                        reason="refinement could not admit a new predicate",
                    )
                )
                if refined is CegarDisposition.UNKNOWN:
                    return self.finish(
                        CegarDisposition.UNKNOWN,
                        "no validated interpolant, core, weakest precondition, or reviewed predicate refined the spurious trace",
                    )
                if refined is CegarDisposition.TIMEOUT:
                    return self.finish(CegarDisposition.TIMEOUT, "CEGAR budget timeout_ms elapsed")
                return self.finish(refined, "refinement terminated without new predicates")
            if isinstance(refined, CegarSolverObservation):
                if refined.status is SmtCheckStatus.TIMEOUT:
                    return self.finish(CegarDisposition.TIMEOUT, refined.reason or "refinement timed out")
                if refined.status is SmtCheckStatus.UNAVAILABLE:
                    return self.finish(
                        CegarDisposition.UNAVAILABLE, refined.reason or "refinement unavailable"
                    )
                return self.finish(CegarDisposition.UNKNOWN, refined.reason or "refinement unknown")
            self.refinements.append(refined)
            self.predicates.extend(refined.predicates)
            self.iterations.append(
                CegarIteration(
                    iteration=iteration,
                    abstract_states_explored=search.explored,
                    search_complete=True,
                    trace=concrete,
                    refinement=refined,
                    solver_receipt_ids=(observation.receipt_id,) if observation.receipt_id else (),
                    reason=refined.reason,
                )
            )
        return self.finish(
            CegarDisposition.BUDGET_EXHAUSTED,
            "max_iterations reached",
        )


def run_cegar(
    system: CegarTransitionSystem,
    *,
    budget: CegarBudget | None = None,
    reviewed_predicates: Sequence[CegarPredicate] = (),
    solver: CegarSolverBackend | None = None,
    interpolator: CegarInterpolator | None = None,
    clock: Callable[[], float] | None = None,
) -> CegarRunReceipt:
    """Run the bounded interpolation/core-driven CEGAR loop to a typed terminal."""

    if not isinstance(system, CegarTransitionSystem):
        raise CegarError("system must be a CegarTransitionSystem")
    budget = budget or CegarBudget()
    reviewed = tuple(reviewed_predicates)
    for item in reviewed:
        if not isinstance(item, CegarPredicate):
            raise CegarError("reviewed_predicates must contain CegarPredicate values")
        if item.origin is not PredicateOrigin.REVIEWED or not item.reviewed:
            raise CegarError("reviewed_predicates must be reviewed")
    engine = _CegarEngine(
        system,
        budget=budget,
        reviewed=reviewed,
        solver=solver or IncrementalSmtCegarSolver(),
        interpolator=interpolator or ValidatedInterpolantBackend(),
        clock=clock or monotonic,
    )
    return engine.run()


__all__ = [
    "CEGAR_BUDGET_SCHEMA",
    "CEGAR_INTERFACE",
    "CEGAR_RECEIPT_SCHEMA",
    "CEGAR_REFINEMENT_SCHEMA",
    "CEGAR_SYSTEM_SCHEMA",
    "CEGAR_TRACE_SCHEMA",
    "CegarAssignment",
    "CegarBudget",
    "CegarDisposition",
    "CegarError",
    "CegarInterpolator",
    "CegarIteration",
    "CegarPredicate",
    "CegarQueryKind",
    "CegarRefinement",
    "CegarRunReceipt",
    "CegarSolverBackend",
    "CegarSolverObservation",
    "CegarSolverQuery",
    "CegarTrace",
    "CegarTraceStep",
    "CegarTransition",
    "CegarTransitionSystem",
    "IncrementalSmtCegarSolver",
    "LocalConjunctionSolver",
    "PredicateOrigin",
    "RefinementAuthority",
    "ScriptedCegarSolver",
    "TraceClassification",
    "ValidatedInterpolantBackend",
    "decide_qf_lia_conjunction",
    "reviewed_predicate",
    "run_cegar",
]
