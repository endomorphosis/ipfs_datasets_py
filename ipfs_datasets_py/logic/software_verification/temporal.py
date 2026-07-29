"""Provider-neutral LTL, LTLf, MTL, CTL, and CTL-star declarations.

The module supplies executable pointwise semantics for:

* LTL over an infinite lasso trace;
* LTLf over a complete finite trace; and
* MTL over a timed finite trace or prefix.

Finite-prefix monitoring is conservative and three-valued.  In particular, a
clean prefix for ``always(safe)`` is inconclusive, never a proof that the
global property holds.  CTL and CTL-star are intentionally declaration and
translation surfaces only.  Evaluating either raises
:class:`DeclarationOnlySemanticsError` until a separately capability-bound,
semantics-preserving branching-time backend is available.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.logic.ir_core.identity import (
    CanonicalIdentity,
    canonical_identity,
)

from .trace import (
    ObservationValue,
    TimeUnit,
    TimeValue,
    TraceIR,
    TraceKind,
)

TEMPORAL_FORMULA_INTERFACE: Final = "TemporalFormula@1"
TEMPORAL_FORMULA_SCHEMA_VERSION: Final = "temporal-formula/v1"
TEMPORAL_FORMULA_IDENTITY_DOMAIN: Final = "logic.software-verification.temporal"
TIME_INTERVAL_SCHEMA_VERSION: Final = "temporal-interval/v1"
TEMPORAL_EVALUATION_SCHEMA_VERSION: Final = "temporal-evaluation/v1"

_ATOM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


class TemporalValidationError(ValueError):
    """Raised when a temporal declaration or evaluation request is invalid."""


class SemanticsDomainMismatchError(TemporalValidationError):
    """Raised when a formula is paired with the wrong kind of trace."""


class DeclarationOnlySemanticsError(TemporalValidationError):
    """Raised when executable semantics are requested for CTL or CTL-star."""


class TemporalLogic(StrEnum):
    """Canonical temporal-logic family names."""

    LTL = "ltl"
    LTLF = "ltlf"
    MTL = "mtl"
    CTL = "ctl"
    CTL_STAR = "ctl_star"


class PathQuantifier(StrEnum):
    """Universal or existential branching-time path selection."""

    ALL = "all"
    EXISTS = "exists"


class TemporalOperator(StrEnum):
    """Boolean, future/past temporal, and path operators."""

    TRUE = "true"
    FALSE = "false"
    ATOM = "atom"
    NOT = "not"
    AND = "and"
    OR = "or"
    IMPLIES = "implies"
    NEXT = "next"
    PREVIOUS = "previous"
    EVENTUALLY = "eventually"
    ALWAYS = "always"
    UNTIL = "until"
    RELEASE = "release"
    WEAK_UNTIL = "weak_until"
    SINCE = "since"
    PATH = "path"


class TemporalVerdict(StrEnum):
    """A conservative semantic or monitoring result."""

    TRUE = "true"
    FALSE = "false"
    INCONCLUSIVE = "inconclusive"


class Monitorability(StrEnum):
    """What a finite observation can establish for a formula."""

    FINITE_TRACE = "finite_trace"
    PREFIX = "prefix"
    VIOLATION = "violation"
    SATISFACTION = "satisfaction"
    NOT_FINITE_MONITORABLE = "not_finite_monitorable"
    DECLARATION_ONLY = "declaration_only"


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or "\x00" in value:
        raise TemporalValidationError(
            f"{label} must be a non-empty trimmed string without NUL bytes"
        )
    return value


def _atom(value: object, label: str = "proposition") -> str:
    result = _text(value, label)
    if not _ATOM_RE.fullmatch(result):
        raise TemporalValidationError(f"{label} must be a stable identifier")
    return result


def _enum(value: object, enum_type: type[StrEnum], label: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise TemporalValidationError(f"{label} must be one of {choices}") from error


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TemporalValidationError(f"{label} must be a mapping")
    return value


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise TemporalValidationError(f"unknown {label} field(s): {', '.join(unknown)}")


@dataclass(frozen=True, slots=True)
class TimeInterval:
    """A non-empty exact interval in one canonical time unit."""

    lower: TimeValue
    upper: TimeValue | None
    unit: TimeUnit
    lower_closed: bool = True
    upper_closed: bool = True
    schema_version: str = TIME_INTERVAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "lower", TimeValue.from_value(self.lower))
        if self.upper is not None:
            object.__setattr__(self, "upper", TimeValue.from_value(self.upper))
        object.__setattr__(self, "unit", _enum(self.unit, TimeUnit, "unit"))
        if not isinstance(self.lower_closed, bool) or not isinstance(self.upper_closed, bool):
            raise TemporalValidationError("interval boundary flags must be booleans")
        if self.upper is not None:
            lower = self.lower.fraction
            upper = self.upper.fraction
            if upper < lower:
                raise TemporalValidationError(
                    "interval upper boundary must not precede lower boundary"
                )
            if upper == lower and not (self.lower_closed and self.upper_closed):
                raise TemporalValidationError("interval must not be empty")
        elif not self.upper_closed:
            raise TemporalValidationError(
                "an unbounded upper boundary must use upper_closed=True canonically"
            )
        if self.schema_version != TIME_INTERVAL_SCHEMA_VERSION:
            raise TemporalValidationError(
                f"unsupported interval schema_version {self.schema_version!r}"
            )

    @classmethod
    def closed(
        cls,
        lower: TimeValue | int,
        upper: TimeValue | int,
        unit: TimeUnit,
    ) -> TimeInterval:
        return cls(
            TimeValue.from_value(lower),
            TimeValue.from_value(upper),
            unit,
            True,
            True,
        )

    @classmethod
    def unbounded(cls, unit: TimeUnit, lower: TimeValue | int = 0) -> TimeInterval:
        return cls(TimeValue.from_value(lower), None, unit)

    def contains(self, elapsed: Fraction | TimeValue | int) -> bool:
        value = elapsed.fraction if isinstance(elapsed, TimeValue) else Fraction(elapsed)
        lower_ok = (
            value >= self.lower.fraction if self.lower_closed else value > self.lower.fraction
        )
        if self.upper is None:
            return lower_ok
        upper_ok = (
            value <= self.upper.fraction if self.upper_closed else value < self.upper.fraction
        )
        return lower_ok and upper_ok

    def horizon_is_past(self, elapsed: Fraction) -> bool:
        """Whether monotonic future events can no longer enter the interval."""

        if self.upper is None:
            return False
        return (
            elapsed > self.upper.fraction if self.upper_closed else elapsed >= self.upper.fraction
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "lower": self.lower.to_dict(),
            "lower_closed": self.lower_closed,
            "schema_version": self.schema_version,
            "unit": self.unit.value,
            "upper": None if self.upper is None else self.upper.to_dict(),
            "upper_closed": self.upper_closed,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TimeInterval:
        value = _mapping(value, "time interval")
        _reject_unknown(
            value,
            frozenset(
                {
                    "lower",
                    "upper",
                    "unit",
                    "lower_closed",
                    "upper_closed",
                    "schema_version",
                }
            ),
            "time interval",
        )
        raw_upper = value.get("upper")
        return cls(
            lower=TimeValue.from_value(value.get("lower", {})),
            upper=None if raw_upper is None else TimeValue.from_value(raw_upper),
            unit=value.get("unit", ""),
            lower_closed=value.get("lower_closed", True),
            upper_closed=value.get("upper_closed", True),
            schema_version=value.get("schema_version", TIME_INTERVAL_SCHEMA_VERSION),
        )


_NULLARY = frozenset({TemporalOperator.TRUE, TemporalOperator.FALSE, TemporalOperator.ATOM})
_UNARY = frozenset(
    {
        TemporalOperator.NOT,
        TemporalOperator.NEXT,
        TemporalOperator.PREVIOUS,
        TemporalOperator.EVENTUALLY,
        TemporalOperator.ALWAYS,
        TemporalOperator.PATH,
    }
)
_BINARY = frozenset(
    {
        TemporalOperator.AND,
        TemporalOperator.OR,
        TemporalOperator.IMPLIES,
        TemporalOperator.UNTIL,
        TemporalOperator.RELEASE,
        TemporalOperator.WEAK_UNTIL,
        TemporalOperator.SINCE,
    }
)
_TEMPORAL = frozenset(
    {
        TemporalOperator.NEXT,
        TemporalOperator.PREVIOUS,
        TemporalOperator.EVENTUALLY,
        TemporalOperator.ALWAYS,
        TemporalOperator.UNTIL,
        TemporalOperator.RELEASE,
        TemporalOperator.WEAK_UNTIL,
        TemporalOperator.SINCE,
    }
)
_FUTURE = frozenset(
    {
        TemporalOperator.NEXT,
        TemporalOperator.EVENTUALLY,
        TemporalOperator.ALWAYS,
        TemporalOperator.UNTIL,
        TemporalOperator.RELEASE,
        TemporalOperator.WEAK_UNTIL,
    }
)


@dataclass(frozen=True, slots=True)
class TemporalFormula:
    """One immutable typed temporal formula tree."""

    operator: TemporalOperator
    logic: TemporalLogic = TemporalLogic.LTL
    operands: tuple[TemporalFormula, ...] = ()
    proposition: str = ""
    interval: TimeInterval | None = None
    path_quantifier: PathQuantifier | None = None
    source_ref_ids: tuple[str, ...] = ()
    formula_id: str = ""
    schema_version: str = TEMPORAL_FORMULA_SCHEMA_VERSION

    INTERFACE: ClassVar[str] = TEMPORAL_FORMULA_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "operator", _enum(self.operator, TemporalOperator, "operator"))
        object.__setattr__(self, "logic", _enum(self.logic, TemporalLogic, "logic"))
        operands = tuple(
            item
            if isinstance(item, TemporalFormula)
            else TemporalFormula.from_dict(_mapping(item, "operand"))
            for item in self.operands
        )
        object.__setattr__(self, "operands", operands)
        interval = self.interval
        if isinstance(interval, Mapping):
            interval = TimeInterval.from_dict(interval)
        if interval is not None and not isinstance(interval, TimeInterval):
            raise TemporalValidationError("interval must be a TimeInterval")
        object.__setattr__(self, "interval", interval)
        if self.path_quantifier is not None:
            object.__setattr__(
                self,
                "path_quantifier",
                _enum(self.path_quantifier, PathQuantifier, "path_quantifier"),
            )
        if isinstance(self.source_ref_ids, (str, bytes, bytearray)) or not isinstance(
            self.source_ref_ids, Sequence
        ):
            raise TemporalValidationError("source_ref_ids must be a sequence of identifiers")
        sources = tuple(_atom(item, "source_ref_id") for item in self.source_ref_ids)
        if len(sources) != len(set(sources)):
            raise TemporalValidationError("source_ref_ids must not contain duplicates")
        object.__setattr__(self, "source_ref_ids", tuple(sorted(sources)))
        self.validate()
        identity = self._compute_identity()
        if self.formula_id and self.formula_id != identity.cid:
            raise TemporalValidationError("formula_id does not match canonical semantic content")
        object.__setattr__(self, "formula_id", identity.cid)

    @property
    def identity(self) -> CanonicalIdentity:
        return self._compute_identity()

    @property
    def declaration_only(self) -> bool:
        return self.logic in {TemporalLogic.CTL, TemporalLogic.CTL_STAR}

    @property
    def monitorability(self) -> Monitorability:
        return classify_monitorability(self)

    def validate(self) -> None:
        if self.schema_version != TEMPORAL_FORMULA_SCHEMA_VERSION:
            raise TemporalValidationError(
                f"unsupported formula schema_version {self.schema_version!r}"
            )
        expected = 0 if self.operator in _NULLARY else 1 if self.operator in _UNARY else 2
        if len(self.operands) != expected:
            raise TemporalValidationError(f"{self.operator.value} requires {expected} operand(s)")
        if any(operand.logic is not self.logic for operand in self.operands):
            raise TemporalValidationError(
                "every operand must use the same temporal logic as its parent"
            )
        if self.operator is TemporalOperator.ATOM:
            object.__setattr__(self, "proposition", _atom(self.proposition, "proposition"))
        elif self.proposition:
            raise TemporalValidationError("proposition is only valid for the atom operator")
        if self.logic is TemporalLogic.MTL:
            if self.operator in _TEMPORAL and self.interval is None:
                raise TemporalValidationError("MTL temporal operators require an explicit interval")
        elif self.interval is not None:
            raise TemporalValidationError("intervals are only valid for MTL")
        if self.operator is TemporalOperator.PATH:
            if self.logic not in {TemporalLogic.CTL, TemporalLogic.CTL_STAR}:
                raise TemporalValidationError(
                    "path quantification is only valid for CTL or CTL-star"
                )
            if self.path_quantifier is None:
                raise TemporalValidationError("path formulas require a path_quantifier")
            if self.logic is TemporalLogic.CTL and self.operands[0].operator not in _FUTURE:
                raise TemporalValidationError(
                    "CTL path quantifiers must directly bind a future operator"
                )
        elif self.path_quantifier is not None:
            raise TemporalValidationError("path_quantifier is only valid for the path operator")
        if self.logic in {TemporalLogic.LTL, TemporalLogic.LTLF, TemporalLogic.MTL}:
            if self.operator is TemporalOperator.PATH:
                raise TemporalValidationError("linear-time formulas cannot quantify paths")

    def validate_root(self) -> None:
        """Validate constraints that only make sense at a formula-tree root."""

        if self.logic is TemporalLogic.CTL:
            self._validate_ctl_state_formula()

    def _validate_ctl_state_formula(self) -> None:
        if self.operator in _TEMPORAL:
            raise TemporalValidationError(
                "CTL temporal operators must occur directly below a path quantifier"
            )
        if self.operator is TemporalOperator.PATH:
            temporal = self.operands[0]
            for operand in temporal.operands:
                operand._validate_ctl_state_formula()
            return
        for operand in self.operands:
            operand._validate_ctl_state_formula()

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "interval": None if self.interval is None else self.interval.to_dict(),
            "logic": self.logic.value,
            "operands": [operand.semantic_dict() for operand in self.operands],
            "operator": self.operator.value,
            "path_quantifier": (
                None if self.path_quantifier is None else self.path_quantifier.value
            ),
            "proposition": self.proposition,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
        }

    deterministic_dict = semantic_dict

    def to_dict(self) -> dict[str, Any]:
        result = self.semantic_dict()
        result["formula_id"] = self.formula_id
        return result

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=TEMPORAL_FORMULA_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    def evaluate(self, trace: TraceIR, position: int = 0) -> TemporalEvaluation:
        return evaluate_temporal(self, trace, position=position)

    def monitor(self, trace: TraceIR, position: int = 0) -> TemporalEvaluation:
        return monitor_prefix(self, trace, position=position)

    @classmethod
    def atom(cls, proposition: str, *, logic: TemporalLogic = TemporalLogic.LTL) -> TemporalFormula:
        return cls(TemporalOperator.ATOM, logic, proposition=proposition)

    @classmethod
    def truth(cls, *, logic: TemporalLogic = TemporalLogic.LTL) -> TemporalFormula:
        return cls(TemporalOperator.TRUE, logic)

    @classmethod
    def falsehood(cls, *, logic: TemporalLogic = TemporalLogic.LTL) -> TemporalFormula:
        return cls(TemporalOperator.FALSE, logic)

    @classmethod
    def path(cls, quantifier: PathQuantifier, operand: TemporalFormula) -> TemporalFormula:
        return cls(
            TemporalOperator.PATH,
            operand.logic,
            (operand,),
            path_quantifier=quantifier,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TemporalFormula:
        value = _mapping(value, "temporal formula")
        _reject_unknown(
            value,
            frozenset(
                {
                    "operator",
                    "logic",
                    "operands",
                    "proposition",
                    "interval",
                    "path_quantifier",
                    "source_ref_ids",
                    "formula_id",
                    "schema_version",
                }
            ),
            "temporal formula",
        )
        interval = value.get("interval")
        return cls(
            operator=value.get("operator", ""),
            logic=value.get("logic", TemporalLogic.LTL.value),
            operands=tuple(
                cls.from_dict(_mapping(item, "operand")) for item in value.get("operands", ())
            ),
            proposition=value.get("proposition", ""),
            interval=(
                None if interval is None else TimeInterval.from_dict(_mapping(interval, "interval"))
            ),
            path_quantifier=value.get("path_quantifier"),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            formula_id=value.get("formula_id", ""),
            schema_version=value.get("schema_version", TEMPORAL_FORMULA_SCHEMA_VERSION),
        )

    @classmethod
    def from_legacy(
        cls,
        value: object,
        *,
        logic: TemporalLogic = TemporalLogic.LTL,
        atom_adapter: Callable[[object], str | TemporalFormula] | None = None,
    ) -> TemporalFormula:
        """Explicitly adapt legacy unary/binary temporal formula objects.

        Supported legacy objects expose ``operator``, ``formula``, and
        optionally ``formula2``.  Atomic values require either ``atom_adapter``
        or an unambiguous zero-argument ``to_string()`` representation.
        """

        if isinstance(value, cls):
            if value.logic is not logic:
                raise TemporalValidationError(
                    "legacy formula already has a different temporal logic"
                )
            return value
        operator = getattr(value, "operator", None)
        if operator is None:
            if atom_adapter is not None:
                adapted = atom_adapter(value)
                if isinstance(adapted, cls):
                    if adapted.logic is not logic:
                        raise TemporalValidationError(
                            "atom adapter returned a different temporal logic"
                        )
                    return adapted
                return cls.atom(adapted, logic=logic)
            renderer = getattr(value, "to_string", None)
            if not callable(renderer):
                raise TemporalValidationError("legacy atoms need atom_adapter or to_string()")
            rendered = renderer()
            if isinstance(rendered, str) and rendered.endswith("()"):
                rendered = rendered[:-2]
            return cls.atom(rendered, logic=logic)
        token = getattr(operator, "name", None) or getattr(operator, "value", None)
        aliases = {
            "ALWAYS": TemporalOperator.ALWAYS,
            "□": TemporalOperator.ALWAYS,
            "EVENTUALLY": TemporalOperator.EVENTUALLY,
            "◇": TemporalOperator.EVENTUALLY,
            "◊": TemporalOperator.EVENTUALLY,
            "NEXT": TemporalOperator.NEXT,
            "X": TemporalOperator.NEXT,
            "PREVIOUS": TemporalOperator.PREVIOUS,
            "YESTERDAY": TemporalOperator.PREVIOUS,
            "Y": TemporalOperator.PREVIOUS,
            "UNTIL": TemporalOperator.UNTIL,
            "U": TemporalOperator.UNTIL,
            "SINCE": TemporalOperator.SINCE,
            "S": TemporalOperator.SINCE,
        }
        try:
            converted_operator = aliases[token]
        except (KeyError, TypeError) as error:
            raise TemporalValidationError(
                f"unsupported legacy temporal operator {token!r}"
            ) from error
        first = cls.from_legacy(
            getattr(value, "formula", None),
            logic=logic,
            atom_adapter=atom_adapter,
        )
        second_value = getattr(value, "formula2", None)
        operands = (first,)
        if converted_operator in _BINARY:
            if second_value is None:
                raise TemporalValidationError(
                    "legacy binary temporal formula has no second operand"
                )
            operands = (
                first,
                cls.from_legacy(second_value, logic=logic, atom_adapter=atom_adapter),
            )
        return cls(converted_operator, logic, operands)


@dataclass(frozen=True, slots=True)
class TemporalEvaluation:
    """A result with an explicit authority ceiling."""

    verdict: TemporalVerdict
    logic: TemporalLogic
    trace_kind: TraceKind
    monitorability: Monitorability
    position: int
    reason: str
    formula_id: str
    trace_id: str
    authorizes_global_proof: bool = False
    schema_version: str = TEMPORAL_EVALUATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "verdict", _enum(self.verdict, TemporalVerdict, "verdict"))
        object.__setattr__(self, "logic", _enum(self.logic, TemporalLogic, "logic"))
        object.__setattr__(self, "trace_kind", _enum(self.trace_kind, TraceKind, "trace_kind"))
        object.__setattr__(
            self,
            "monitorability",
            _enum(self.monitorability, Monitorability, "monitorability"),
        )
        if self.authorizes_global_proof:
            raise TemporalValidationError("trace evaluation never authorizes a global proof")
        if self.schema_version != TEMPORAL_EVALUATION_SCHEMA_VERSION:
            raise TemporalValidationError(
                f"unsupported evaluation schema_version {self.schema_version!r}"
            )

    @property
    def conclusive(self) -> bool:
        return self.verdict is not TemporalVerdict.INCONCLUSIVE

    @property
    def holds(self) -> bool:
        if not self.conclusive:
            raise TemporalValidationError(
                "an inconclusive temporal evaluation has no boolean truth value"
            )
        return self.verdict is TemporalVerdict.TRUE

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorizes_global_proof": self.authorizes_global_proof,
            "formula_id": self.formula_id,
            "logic": self.logic.value,
            "monitorability": self.monitorability.value,
            "position": self.position,
            "reason": self.reason,
            "schema_version": self.schema_version,
            "trace_id": self.trace_id,
            "trace_kind": self.trace_kind.value,
            "verdict": self.verdict.value,
        }


def _not(value: ObservationValue) -> ObservationValue:
    if value is ObservationValue.TRUE:
        return ObservationValue.FALSE
    if value is ObservationValue.FALSE:
        return ObservationValue.TRUE
    return ObservationValue.UNKNOWN


def _and(left: ObservationValue, right: ObservationValue) -> ObservationValue:
    if ObservationValue.FALSE in (left, right):
        return ObservationValue.FALSE
    if left is ObservationValue.TRUE and right is ObservationValue.TRUE:
        return ObservationValue.TRUE
    return ObservationValue.UNKNOWN


def _or(left: ObservationValue, right: ObservationValue) -> ObservationValue:
    if ObservationValue.TRUE in (left, right):
        return ObservationValue.TRUE
    if left is ObservationValue.FALSE and right is ObservationValue.FALSE:
        return ObservationValue.FALSE
    return ObservationValue.UNKNOWN


def _fold(
    values: Sequence[ObservationValue],
    operation: Callable[[ObservationValue, ObservationValue], ObservationValue],
    identity: ObservationValue,
) -> ObservationValue:
    result = identity
    for value in values:
        result = operation(result, value)
    return result


def _check_position(trace: TraceIR, position: int) -> None:
    if not trace.events:
        raise TemporalValidationError("temporal evaluation requires a non-empty trace")
    if (
        isinstance(position, bool)
        or not isinstance(position, int)
        or not 0 <= position < len(trace.events)
    ):
        raise TemporalValidationError("position is outside the trace")


def _check_metric_unit(formula: TemporalFormula, trace: TraceIR) -> None:
    if formula.interval is not None and formula.interval.unit is not trace.primary_clock.unit:
        raise SemanticsDomainMismatchError(
            "MTL interval unit does not match the trace primary clock"
        )
    for operand in formula.operands:
        _check_metric_unit(operand, trace)


def _finite_tables(
    formula: TemporalFormula,
    trace: TraceIR,
    *,
    monitoring: bool,
) -> dict[str, tuple[ObservationValue, ...]]:
    count = len(trace.events)
    cache: dict[str, tuple[ObservationValue, ...]] = {}

    def table(node: TemporalFormula) -> tuple[ObservationValue, ...]:
        if node.formula_id in cache:
            return cache[node.formula_id]
        operator = node.operator
        children = tuple(table(operand) for operand in node.operands)
        if operator is TemporalOperator.TRUE:
            values = (ObservationValue.TRUE,) * count
        elif operator is TemporalOperator.FALSE:
            values = (ObservationValue.FALSE,) * count
        elif operator is TemporalOperator.ATOM:
            values = tuple(trace.observe(index, node.proposition) for index in range(count))
        elif operator is TemporalOperator.NOT:
            values = tuple(_not(item) for item in children[0])
        elif operator is TemporalOperator.AND:
            values = tuple(_and(*items) for items in zip(*children, strict=True))
        elif operator is TemporalOperator.OR:
            values = tuple(_or(*items) for items in zip(*children, strict=True))
        elif operator is TemporalOperator.IMPLIES:
            values = tuple(_or(_not(left), right) for left, right in zip(*children, strict=True))
        elif operator is TemporalOperator.PREVIOUS and node.interval is None:
            initial = ObservationValue.FALSE
            values = (initial, *children[0][:-1])
        elif operator is TemporalOperator.SINCE and node.interval is None:
            values_list: list[ObservationValue] = []
            carry = ObservationValue.FALSE
            for left, right in zip(*children, strict=True):
                carry = _or(right, _and(left, carry))
                values_list.append(carry)
            values = tuple(values_list)
        elif node.interval is not None:
            values = _metric_values(node, children, trace, monitoring=monitoring)
        elif operator is TemporalOperator.NEXT:
            terminal = ObservationValue.UNKNOWN if monitoring else ObservationValue.FALSE
            values = (*children[0][1:], terminal)
        elif operator in {
            TemporalOperator.EVENTUALLY,
            TemporalOperator.ALWAYS,
            TemporalOperator.UNTIL,
            TemporalOperator.RELEASE,
            TemporalOperator.WEAK_UNTIL,
        }:
            values = _untimed_future_values(operator, children, count, monitoring=monitoring)
        else:
            raise DeclarationOnlySemanticsError(
                "path formulas have no local linear-time evaluation"
            )
        cache[node.formula_id] = tuple(values)
        return cache[node.formula_id]

    table(formula)
    return cache


def _untimed_future_values(
    operator: TemporalOperator,
    children: tuple[tuple[ObservationValue, ...], ...],
    count: int,
    *,
    monitoring: bool,
) -> tuple[ObservationValue, ...]:
    if operator in {TemporalOperator.EVENTUALLY, TemporalOperator.UNTIL}:
        carry = ObservationValue.UNKNOWN if monitoring else ObservationValue.FALSE
    else:
        carry = ObservationValue.UNKNOWN if monitoring else ObservationValue.TRUE
    result = [ObservationValue.UNKNOWN] * count
    for index in range(count - 1, -1, -1):
        if operator is TemporalOperator.EVENTUALLY:
            carry = _or(children[0][index], carry)
        elif operator is TemporalOperator.ALWAYS:
            carry = _and(children[0][index], carry)
        elif operator is TemporalOperator.UNTIL:
            carry = _or(children[1][index], _and(children[0][index], carry))
        elif operator is TemporalOperator.RELEASE:
            carry = _and(children[1][index], _or(children[0][index], carry))
        else:
            carry = _or(children[1][index], _and(children[0][index], carry))
        result[index] = carry
    return tuple(result)


def _metric_values(
    node: TemporalFormula,
    children: tuple[tuple[ObservationValue, ...], ...],
    trace: TraceIR,
    *,
    monitoring: bool,
) -> tuple[ObservationValue, ...]:
    interval = node.interval
    assert interval is not None
    count = len(trace.events)
    times = [event.time.value.fraction for event in trace.events]
    results: list[ObservationValue] = []
    for start in range(count):
        eligible = [
            index for index in range(start, count) if interval.contains(times[index] - times[start])
        ]
        elapsed = times[-1] - times[start]
        horizon_complete = not monitoring or interval.horizon_is_past(elapsed)
        operator = node.operator
        if operator is TemporalOperator.NEXT:
            if start + 1 < count:
                results.append(
                    children[0][start + 1]
                    if interval.contains(times[start + 1] - times[start])
                    else ObservationValue.FALSE
                )
            else:
                results.append(ObservationValue.UNKNOWN if monitoring else ObservationValue.FALSE)
            continue
        if operator is TemporalOperator.PREVIOUS:
            if start == 0:
                results.append(ObservationValue.FALSE)
            else:
                results.append(
                    children[0][start - 1]
                    if interval.contains(times[start] - times[start - 1])
                    else ObservationValue.FALSE
                )
            continue
        if operator is TemporalOperator.EVENTUALLY:
            observed = _fold(
                [children[0][index] for index in eligible],
                _or,
                ObservationValue.FALSE,
            )
            results.append(
                observed
                if observed is ObservationValue.TRUE or horizon_complete
                else ObservationValue.UNKNOWN
            )
            continue
        if operator is TemporalOperator.ALWAYS:
            observed = _fold(
                [children[0][index] for index in eligible],
                _and,
                ObservationValue.TRUE,
            )
            results.append(
                observed
                if observed is ObservationValue.FALSE or horizon_complete
                else ObservationValue.UNKNOWN
            )
            continue
        if operator in {TemporalOperator.UNTIL, TemporalOperator.SINCE}:
            if operator is TemporalOperator.SINCE:
                candidates = list(
                    reversed(
                        [
                            index
                            for index in range(0, start + 1)
                            if interval.contains(times[start] - times[index])
                        ]
                    )
                )
                candidate_values = [
                    _and(
                        children[1][witness],
                        _fold(
                            [children[0][index] for index in range(witness + 1, start + 1)],
                            _and,
                            ObservationValue.TRUE,
                        ),
                    )
                    for witness in candidates
                ]
            else:
                candidates = eligible
                candidate_values = [
                    _and(
                        children[1][witness],
                        _fold(
                            [children[0][index] for index in range(start, witness)],
                            _and,
                            ObservationValue.TRUE,
                        ),
                    )
                    for witness in candidates
                ]
            observed = _fold(candidate_values, _or, ObservationValue.FALSE)
            if operator is TemporalOperator.SINCE:
                results.append(observed)
            else:
                observed_left = _fold(
                    [children[0][index] for index in range(start, count)],
                    _and,
                    ObservationValue.TRUE,
                )
                results.append(
                    observed
                    if (
                        observed is ObservationValue.TRUE
                        or observed_left is ObservationValue.FALSE
                        or horizon_complete
                    )
                    else ObservationValue.UNKNOWN
                )
            continue
        if operator in {
            TemporalOperator.RELEASE,
            TemporalOperator.WEAK_UNTIL,
        }:
            # R is the dual of U.  W is U or globally-left.
            until_negated = _metric_until_at(
                tuple(_not(value) for value in children[0]),
                tuple(_not(value) for value in children[1]),
                eligible,
                start,
            )
            release = _not(until_negated)
            if operator is TemporalOperator.RELEASE:
                observed = release
            else:
                until = _metric_until_at(children[0], children[1], eligible, start)
                globally_left = _fold(
                    [children[0][index] for index in eligible],
                    _and,
                    ObservationValue.TRUE,
                )
                observed = _or(until, globally_left)
            if (
                not horizon_complete
                and observed is ObservationValue.TRUE
                and (operator is TemporalOperator.RELEASE or until is not ObservationValue.TRUE)
            ):
                observed = ObservationValue.UNKNOWN
            results.append(observed)
            continue
        raise TemporalValidationError(f"metric semantics are unsupported for {operator.value}")
    return tuple(results)


def _metric_until_at(
    left: tuple[ObservationValue, ...],
    right: tuple[ObservationValue, ...],
    eligible: Sequence[int],
    start: int,
) -> ObservationValue:
    candidates = [
        _and(
            right[witness],
            _fold(
                [left[index] for index in range(start, witness)],
                _and,
                ObservationValue.TRUE,
            ),
        )
        for witness in eligible
    ]
    return _fold(candidates, _or, ObservationValue.FALSE)


def _infinite_table(formula: TemporalFormula, trace: TraceIR) -> tuple[ObservationValue, ...]:
    count = len(trace.events)
    cache: dict[str, tuple[ObservationValue, ...]] = {}
    successors = tuple(trace.successor(index) for index in range(count))

    def table(node: TemporalFormula) -> tuple[ObservationValue, ...]:
        if node.formula_id in cache:
            return cache[node.formula_id]
        operator = node.operator
        if operator in {TemporalOperator.PREVIOUS, TemporalOperator.SINCE}:
            raise SemanticsDomainMismatchError(
                "past-time operators are not supported over lasso compression"
            )
        children = tuple(table(operand) for operand in node.operands)
        if operator is TemporalOperator.TRUE:
            values = (ObservationValue.TRUE,) * count
        elif operator is TemporalOperator.FALSE:
            values = (ObservationValue.FALSE,) * count
        elif operator is TemporalOperator.ATOM:
            values = tuple(trace.observe(index, node.proposition) for index in range(count))
        elif operator is TemporalOperator.NOT:
            values = tuple(_not(value) for value in children[0])
        elif operator is TemporalOperator.AND:
            values = tuple(_and(*items) for items in zip(*children, strict=True))
        elif operator is TemporalOperator.OR:
            values = tuple(_or(*items) for items in zip(*children, strict=True))
        elif operator is TemporalOperator.IMPLIES:
            values = tuple(_or(_not(left), right) for left, right in zip(*children, strict=True))
        elif operator is TemporalOperator.NEXT:
            values = tuple(children[0][successor] for successor in successors)  # type: ignore[index]
        elif operator in {
            TemporalOperator.EVENTUALLY,
            TemporalOperator.ALWAYS,
            TemporalOperator.UNTIL,
            TemporalOperator.RELEASE,
            TemporalOperator.WEAK_UNTIL,
        }:
            greatest = operator in {
                TemporalOperator.ALWAYS,
                TemporalOperator.RELEASE,
                TemporalOperator.WEAK_UNTIL,
            }
            current = [ObservationValue.TRUE if greatest else ObservationValue.FALSE] * count
            for _ in range(2 * count + 2):
                updated: list[ObservationValue] = []
                for index, successor in enumerate(successors):
                    carried = current[successor]  # type: ignore[index]
                    if operator is TemporalOperator.EVENTUALLY:
                        value = _or(children[0][index], carried)
                    elif operator is TemporalOperator.ALWAYS:
                        value = _and(children[0][index], carried)
                    elif operator is TemporalOperator.UNTIL:
                        value = _or(
                            children[1][index],
                            _and(children[0][index], carried),
                        )
                    elif operator is TemporalOperator.RELEASE:
                        value = _and(
                            children[1][index],
                            _or(children[0][index], carried),
                        )
                    else:
                        value = _or(
                            children[1][index],
                            _and(children[0][index], carried),
                        )
                    updated.append(value)
                if updated == current:
                    break
                current = updated
            else:  # pragma: no cover - finite three-valued lattice guarantees this
                raise TemporalValidationError("temporal fixed point did not converge")
            values = tuple(current)
        else:
            raise DeclarationOnlySemanticsError(
                "path formulas have no local linear-time evaluation"
            )
        cache[node.formula_id] = tuple(values)
        return cache[node.formula_id]

    return table(formula)


def _to_verdict(value: ObservationValue) -> TemporalVerdict:
    if value is ObservationValue.TRUE:
        return TemporalVerdict.TRUE
    if value is ObservationValue.FALSE:
        return TemporalVerdict.FALSE
    return TemporalVerdict.INCONCLUSIVE


def _result(
    formula: TemporalFormula,
    trace: TraceIR,
    position: int,
    value: ObservationValue,
    reason: str,
) -> TemporalEvaluation:
    return TemporalEvaluation(
        verdict=_to_verdict(value),
        logic=formula.logic,
        trace_kind=trace.kind,
        monitorability=formula.monitorability,
        position=position,
        reason=reason,
        formula_id=formula.formula_id,
        trace_id=trace.trace_id,
    )


def evaluate_temporal(
    formula: TemporalFormula, trace: TraceIR, *, position: int = 0
) -> TemporalEvaluation:
    """Evaluate a formula only in its exact declared semantic domain."""

    if not isinstance(formula, TemporalFormula):
        raise TemporalValidationError("formula must be a TemporalFormula")
    if not isinstance(trace, TraceIR):
        raise TemporalValidationError("trace must be a TraceIR")
    formula.validate_root()
    _check_position(trace, position)
    if formula.declaration_only:
        raise DeclarationOnlySemanticsError(
            f"{formula.logic.value} is declaration/translation-only"
        )
    if formula.logic is TemporalLogic.LTL:
        if trace.kind is not TraceKind.INFINITE:
            raise SemanticsDomainMismatchError("LTL requires an infinite trace")
        value = _infinite_table(formula, trace)[position]
        return _result(
            formula,
            trace,
            position,
            value,
            "exact LTL semantics over the supplied infinite lasso trace",
        )
    if formula.logic is TemporalLogic.LTLF:
        if trace.kind is not TraceKind.FINITE:
            raise SemanticsDomainMismatchError("LTLf requires a complete finite trace")
        value = _finite_tables(formula, trace, monitoring=False)[formula.formula_id][position]
        return _result(
            formula,
            trace,
            position,
            value,
            "exact LTLf semantics over the supplied complete finite trace",
        )
    if trace.kind is TraceKind.INFINITE:
        raise SemanticsDomainMismatchError(
            "MTL lasso evaluation is not defined by this finite timed-word model"
        )
    _check_metric_unit(formula, trace)
    monitoring = trace.kind is TraceKind.FINITE_PREFIX
    value = _finite_tables(formula, trace, monitoring=monitoring)[formula.formula_id][position]
    reason = (
        "conservative MTL monitoring over an incomplete finite prefix"
        if monitoring
        else "exact MTL semantics over the supplied complete finite timed trace"
    )
    return _result(formula, trace, position, value, reason)


def monitor_prefix(
    formula: TemporalFormula, trace: TraceIR, *, position: int = 0
) -> TemporalEvaluation:
    """Conservatively monitor a linear-time formula on a finite prefix."""

    if not isinstance(formula, TemporalFormula):
        raise TemporalValidationError("formula must be a TemporalFormula")
    if not isinstance(trace, TraceIR):
        raise TemporalValidationError("trace must be a TraceIR")
    formula.validate_root()
    _check_position(trace, position)
    if formula.declaration_only:
        raise DeclarationOnlySemanticsError(
            f"{formula.logic.value} is declaration/translation-only"
        )
    if trace.kind is not TraceKind.FINITE_PREFIX:
        raise SemanticsDomainMismatchError("prefix monitoring requires a finite_prefix trace")
    if formula.logic is TemporalLogic.MTL:
        _check_metric_unit(formula, trace)
    value = _finite_tables(formula, trace, monitoring=True)[formula.formula_id][position]
    return _result(
        formula,
        trace,
        position,
        value,
        "conservative finite-prefix verdict; it carries no global proof authority",
    )


def classify_monitorability(formula: TemporalFormula) -> Monitorability:
    """Return a conservative, syntactic finite-monitorability declaration."""

    if formula.logic in {TemporalLogic.CTL, TemporalLogic.CTL_STAR}:
        return Monitorability.DECLARATION_ONLY
    if formula.logic is TemporalLogic.LTLF:
        return Monitorability.FINITE_TRACE
    if formula.logic is TemporalLogic.MTL and _all_future_bounds_finite(formula):
        return Monitorability.PREFIX
    if formula.operator is TemporalOperator.ALWAYS:
        return Monitorability.VIOLATION
    if formula.operator in {TemporalOperator.EVENTUALLY, TemporalOperator.UNTIL}:
        return Monitorability.SATISFACTION
    if formula.operator in {
        TemporalOperator.TRUE,
        TemporalOperator.FALSE,
        TemporalOperator.ATOM,
        TemporalOperator.NOT,
        TemporalOperator.AND,
        TemporalOperator.OR,
        TemporalOperator.IMPLIES,
        TemporalOperator.NEXT,
        TemporalOperator.PREVIOUS,
        TemporalOperator.SINCE,
    }:
        return Monitorability.PREFIX
    return Monitorability.NOT_FINITE_MONITORABLE


def _all_future_bounds_finite(formula: TemporalFormula) -> bool:
    if formula.operator in _FUTURE:
        if formula.interval is None or formula.interval.upper is None:
            return False
    return all(_all_future_bounds_finite(operand) for operand in formula.operands)


def unary(
    operator: TemporalOperator,
    operand: TemporalFormula,
    *,
    interval: TimeInterval | None = None,
) -> TemporalFormula:
    """Construct a unary formula while inheriting its operand's logic."""

    return TemporalFormula(operator, operand.logic, (operand,), interval=interval)


def binary(
    operator: TemporalOperator,
    left: TemporalFormula,
    right: TemporalFormula,
    *,
    interval: TimeInterval | None = None,
) -> TemporalFormula:
    """Construct a binary formula while enforcing one shared logic."""

    if left.logic is not right.logic:
        raise TemporalValidationError("binary operands use different logics")
    return TemporalFormula(operator, left.logic, (left, right), interval=interval)


def always(operand: TemporalFormula, *, interval: TimeInterval | None = None) -> TemporalFormula:
    return unary(TemporalOperator.ALWAYS, operand, interval=interval)


def eventually(
    operand: TemporalFormula, *, interval: TimeInterval | None = None
) -> TemporalFormula:
    return unary(TemporalOperator.EVENTUALLY, operand, interval=interval)


def next_time(operand: TemporalFormula, *, interval: TimeInterval | None = None) -> TemporalFormula:
    return unary(TemporalOperator.NEXT, operand, interval=interval)


def until(
    left: TemporalFormula,
    right: TemporalFormula,
    *,
    interval: TimeInterval | None = None,
) -> TemporalFormula:
    return binary(TemporalOperator.UNTIL, left, right, interval=interval)


__all__ = [
    "TEMPORAL_EVALUATION_SCHEMA_VERSION",
    "TEMPORAL_FORMULA_IDENTITY_DOMAIN",
    "TEMPORAL_FORMULA_INTERFACE",
    "TEMPORAL_FORMULA_SCHEMA_VERSION",
    "TIME_INTERVAL_SCHEMA_VERSION",
    "DeclarationOnlySemanticsError",
    "Monitorability",
    "PathQuantifier",
    "SemanticsDomainMismatchError",
    "TemporalEvaluation",
    "TemporalFormula",
    "TemporalLogic",
    "TemporalOperator",
    "TemporalValidationError",
    "TemporalVerdict",
    "TimeInterval",
    "always",
    "binary",
    "classify_monitorability",
    "evaluate_temporal",
    "eventually",
    "monitor_prefix",
    "next_time",
    "unary",
    "until",
]
