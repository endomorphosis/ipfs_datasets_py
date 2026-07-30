"""Portable finite-trace MTL/LTLf runtime monitor (RuntimeMTLMonitor@1).

This module defines language-neutral formula, trace, and result schemas plus a
deterministic three-valued evaluator for:

* complete finite traces (LTLf exact semantics; MTL timed finite words); and
* incomplete finite prefixes (conservative monitoring).

Authority is always ``monitor``.  A clean prefix / no-violation-observed
outcome is ``unknown``/``inconclusive`` and never elevates to theorem proof
authority.  Exact rational times avoid host floating-point drift so Python and
TypeScript can agree on interval boundaries and serialization.

Crypto-exchange and supervisor domain monitors remain separate compatibility
consumers; this package owns the generic portable surface.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from fractions import Fraction
from math import gcd
from typing import Any, Final

RUNTIME_MTL_INTERFACE: Final = "RuntimeMTLMonitor@1"
RUNTIME_MTL_SCHEMA_VERSION: Final = "runtime-mtl/v1"
RUNTIME_MTL_RESULT_SCHEMA_VERSION: Final = "runtime-mtl-result/v1"
RUNTIME_MTL_FORMULA_SCHEMA_VERSION: Final = "runtime-mtl-formula/v1"
RUNTIME_MTL_TRACE_SCHEMA_VERSION: Final = "runtime-mtl-trace/v1"
RUNTIME_MTL_INTERVAL_SCHEMA_VERSION: Final = "runtime-mtl-interval/v1"

_ATOM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_ID_RE = _ATOM_RE

_NULLARY = frozenset({"true", "false", "atom"})
_UNARY = frozenset(
    {
        "not",
        "next",
        "previous",
        "eventually",
        "always",
    }
)
_BINARY = frozenset(
    {
        "and",
        "or",
        "implies",
        "until",
        "release",
        "weak_until",
        "since",
    }
)
_TEMPORAL = frozenset(
    {
        "next",
        "previous",
        "eventually",
        "always",
        "until",
        "release",
        "weak_until",
        "since",
    }
)
_FUTURE = frozenset(
    {
        "next",
        "eventually",
        "always",
        "until",
        "release",
        "weak_until",
    }
)


class RuntimeMTLError(ValueError):
    """Raised when a portable monitor input is malformed or domain-mismatched."""


class Verdict(StrEnum):
    TRUE = "true"
    FALSE = "false"
    INCONCLUSIVE = "inconclusive"


class Observation(StrEnum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class Logic(StrEnum):
    LTLF = "ltlf"
    MTL = "mtl"


class TraceKind(StrEnum):
    FINITE = "finite"
    FINITE_PREFIX = "finite_prefix"


class Monitorability(StrEnum):
    FINITE_TRACE = "finite_trace"
    PREFIX = "prefix"
    VIOLATION = "violation"
    SATISFACTION = "satisfaction"
    NOT_FINITE_MONITORABLE = "not_finite_monitorable"


class ObservationPolicyKind(StrEnum):
    CLOSED_WORLD = "closed_world"
    EXPLICIT = "explicit"


class TimeUnit(StrEnum):
    NANOSECOND = "nanosecond"
    MICROSECOND = "microsecond"
    MILLISECOND = "millisecond"
    SECOND = "second"
    MINUTE = "minute"
    HOUR = "hour"
    LOGICAL_TICK = "logical_tick"


class ClockDomain(StrEnum):
    DISCRETE = "discrete"
    DENSE = "dense"


class MonitorAuthority(StrEnum):
    """Closed authority label for runtime monitor results."""

    MONITOR = "monitor"


class MonitorStatus(StrEnum):
    """Wire status values under monitor authority only."""

    SATISFIED = "satisfied"
    VIOLATED = "violated"
    UNKNOWN = "unknown"
    MALFORMED = "malformed"


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or "\x00" in value:
        raise RuntimeMTLError(f"{label} must be a non-empty trimmed string without NUL bytes")
    return value


def _identifier(value: object, label: str) -> str:
    result = _text(value, label)
    if not _ID_RE.fullmatch(result):
        raise RuntimeMTLError(f"{label} must be a stable identifier")
    return result


def _atom(value: object, label: str = "proposition") -> str:
    return _identifier(value, label)


def _enum(value: object, enum_type: type[StrEnum], label: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise RuntimeMTLError(f"{label} must be one of {choices}") from error


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeMTLError(f"{label} must be a mapping")
    return value


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise RuntimeMTLError(f"unknown {label} field(s): {', '.join(unknown)}")


def _sorted_atoms(values: Sequence[str] | object, label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise RuntimeMTLError(f"{label} must be a sequence of identifiers")
    result = tuple(_atom(item, f"{label} item") for item in values)
    if len(result) != len(set(result)):
        raise RuntimeMTLError(f"{label} must not contain duplicates")
    return tuple(sorted(result))


# ---------------------------------------------------------------------------
# Exact time values
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, order=True)
class TimeValue:
    """Non-negative reduced rational number of clock units."""

    numerator: int
    denominator: int = 1

    def __post_init__(self) -> None:
        if isinstance(self.numerator, bool) or not isinstance(self.numerator, int):
            raise RuntimeMTLError("time numerator must be an integer")
        if isinstance(self.denominator, bool) or not isinstance(self.denominator, int):
            raise RuntimeMTLError("time denominator must be an integer")
        if self.numerator < 0:
            raise RuntimeMTLError("time values must be non-negative")
        if self.denominator <= 0:
            raise RuntimeMTLError("time denominator must be positive")
        divisor = gcd(self.numerator, self.denominator)
        object.__setattr__(self, "numerator", self.numerator // divisor)
        object.__setattr__(self, "denominator", self.denominator // divisor)

    @property
    def fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)

    def to_dict(self) -> dict[str, int]:
        return {"denominator": self.denominator, "numerator": self.numerator}

    @classmethod
    def from_value(cls, value: TimeValue | int | Mapping[str, Any]) -> TimeValue:
        if isinstance(value, cls):
            return value
        if isinstance(value, bool):
            raise RuntimeMTLError("time values must not be booleans")
        if isinstance(value, int):
            return cls(value)
        if isinstance(value, float):
            raise RuntimeMTLError("floating-point timestamps are rejected; use exact rationals")
        value = _mapping(value, "time value")
        _reject_unknown(value, frozenset({"numerator", "denominator"}), "time value")
        return cls(
            numerator=value.get("numerator"),  # type: ignore[arg-type]
            denominator=value.get("denominator", 1),  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class TimeInterval:
    """Non-empty exact interval with closed/open endpoints."""

    lower: TimeValue
    upper: TimeValue | None
    unit: TimeUnit
    lower_closed: bool = True
    upper_closed: bool = True
    schema_version: str = RUNTIME_MTL_INTERVAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "lower", TimeValue.from_value(self.lower))
        if self.upper is not None:
            object.__setattr__(self, "upper", TimeValue.from_value(self.upper))
        object.__setattr__(self, "unit", _enum(self.unit, TimeUnit, "unit"))
        if not isinstance(self.lower_closed, bool) or not isinstance(self.upper_closed, bool):
            raise RuntimeMTLError("interval boundary flags must be booleans")
        if self.upper is not None:
            if self.upper.fraction < self.lower.fraction:
                raise RuntimeMTLError("interval upper boundary must not precede lower boundary")
            if self.upper.fraction == self.lower.fraction and not (
                self.lower_closed and self.upper_closed
            ):
                raise RuntimeMTLError("interval must not be empty")
        elif not self.upper_closed:
            raise RuntimeMTLError(
                "an unbounded upper boundary must use upper_closed=True canonically"
            )
        if self.schema_version != RUNTIME_MTL_INTERVAL_SCHEMA_VERSION:
            raise RuntimeMTLError(
                f"unsupported interval schema_version {self.schema_version!r}"
            )

    @classmethod
    def closed(
        cls,
        lower: TimeValue | int,
        upper: TimeValue | int,
        unit: TimeUnit | str,
    ) -> TimeInterval:
        return cls(TimeValue.from_value(lower), TimeValue.from_value(upper), _enum(unit, TimeUnit, "unit"), True, True)

    @classmethod
    def unbounded(cls, unit: TimeUnit | str, lower: TimeValue | int = 0) -> TimeInterval:
        return cls(TimeValue.from_value(lower), None, _enum(unit, TimeUnit, "unit"))

    def contains(self, elapsed: Fraction | TimeValue | int) -> bool:
        value = elapsed.fraction if isinstance(elapsed, TimeValue) else Fraction(elapsed)
        lower_ok = value >= self.lower.fraction if self.lower_closed else value > self.lower.fraction
        if self.upper is None:
            return lower_ok
        upper_ok = value <= self.upper.fraction if self.upper_closed else value < self.upper.fraction
        return lower_ok and upper_ok

    def horizon_is_past(self, elapsed: Fraction) -> bool:
        if self.upper is None:
            return False
        return elapsed > self.upper.fraction if self.upper_closed else elapsed >= self.upper.fraction

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
            frozenset({"lower", "upper", "unit", "lower_closed", "upper_closed", "schema_version"}),
            "time interval",
        )
        upper = value.get("upper")
        return cls(
            lower=TimeValue.from_value(value.get("lower", 0)),
            upper=None if upper is None else TimeValue.from_value(upper),
            unit=value.get("unit", TimeUnit.LOGICAL_TICK.value),
            lower_closed=value.get("lower_closed", True),
            upper_closed=value.get("upper_closed", True),
            schema_version=value.get("schema_version", RUNTIME_MTL_INTERVAL_SCHEMA_VERSION),
        )


# ---------------------------------------------------------------------------
# Portable formula / trace
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Formula:
    """Portable MTL/LTLf formula tree."""

    operator: str
    logic: Logic = Logic.LTLF
    operands: tuple[Formula, ...] = ()
    proposition: str = ""
    interval: TimeInterval | None = None
    node_id: str = ""
    schema_version: str = RUNTIME_MTL_FORMULA_SCHEMA_VERSION

    def __post_init__(self) -> None:
        op = _text(self.operator, "operator").lower()
        object.__setattr__(self, "operator", op)
        object.__setattr__(self, "logic", _enum(self.logic, Logic, "logic"))
        operands = tuple(
            item if isinstance(item, Formula) else Formula.from_dict(_mapping(item, "operand"))
            for item in self.operands
        )
        object.__setattr__(self, "operands", operands)
        interval = self.interval
        if isinstance(interval, Mapping):
            interval = TimeInterval.from_dict(interval)
        if interval is not None and not isinstance(interval, TimeInterval):
            raise RuntimeMTLError("interval must be a TimeInterval")
        object.__setattr__(self, "interval", interval)
        if self.schema_version != RUNTIME_MTL_FORMULA_SCHEMA_VERSION:
            raise RuntimeMTLError(
                f"unsupported formula schema_version {self.schema_version!r}"
            )
        self._validate()
        if not self.node_id:
            object.__setattr__(self, "node_id", self._compute_node_id())

    def _validate(self) -> None:
        if self.operator in _NULLARY:
            expected = 0
        elif self.operator in _UNARY:
            expected = 1
        elif self.operator in _BINARY:
            expected = 2
        else:
            raise RuntimeMTLError(f"unsupported operator {self.operator!r}")
        if len(self.operands) != expected:
            raise RuntimeMTLError(f"{self.operator} requires {expected} operand(s)")
        if any(operand.logic is not self.logic for operand in self.operands):
            raise RuntimeMTLError("every operand must use the same logic as its parent")
        if self.operator == "atom":
            object.__setattr__(self, "proposition", _atom(self.proposition))
        elif self.proposition:
            raise RuntimeMTLError("proposition is only valid for the atom operator")
        if self.logic is Logic.MTL:
            if self.operator in _TEMPORAL and self.interval is None:
                raise RuntimeMTLError("MTL temporal operators require an explicit interval")
        elif self.interval is not None:
            raise RuntimeMTLError("intervals are only valid for MTL")

    def _compute_node_id(self) -> str:
        payload = json.dumps(self.semantic_dict(), sort_keys=True, separators=(",", ":"))
        # Structural hex digest without external crypto dependency (FNV-1a 64-bit).
        hash_value = 0xCBF29CE484222325
        for byte in payload.encode("utf-8"):
            hash_value ^= byte
            hash_value = (hash_value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
        return f"node:{hash_value:016x}"

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "interval": None if self.interval is None else self.interval.to_dict(),
            "logic": self.logic.value,
            "operands": [operand.semantic_dict() for operand in self.operands],
            "operator": self.operator,
            "proposition": self.proposition,
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        result = self.semantic_dict()
        result["node_id"] = self.node_id
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Formula:
        value = _mapping(value, "formula")
        _reject_unknown(
            value,
            frozenset(
                {
                    "operator",
                    "logic",
                    "operands",
                    "proposition",
                    "interval",
                    "node_id",
                    "schema_version",
                }
            ),
            "formula",
        )
        interval = value.get("interval")
        return cls(
            operator=value.get("operator", ""),
            logic=value.get("logic", Logic.LTLF.value),
            operands=tuple(value.get("operands", ())),
            proposition=value.get("proposition", ""),
            interval=None if interval is None else TimeInterval.from_dict(_mapping(interval, "interval")),
            node_id=value.get("node_id", ""),
            schema_version=value.get("schema_version", RUNTIME_MTL_FORMULA_SCHEMA_VERSION),
        )

    @classmethod
    def atom(cls, proposition: str, *, logic: Logic | str = Logic.LTLF) -> Formula:
        return cls("atom", _enum(logic, Logic, "logic"), proposition=proposition)

    @classmethod
    def truth(cls, *, logic: Logic | str = Logic.LTLF) -> Formula:
        return cls("true", _enum(logic, Logic, "logic"))

    @classmethod
    def falsehood(cls, *, logic: Logic | str = Logic.LTLF) -> Formula:
        return cls("false", _enum(logic, Logic, "logic"))


def unary(
    operator: str,
    operand: Formula,
    *,
    interval: TimeInterval | None = None,
) -> Formula:
    return Formula(operator, operand.logic, (operand,), interval=interval)


def binary(
    operator: str,
    left: Formula,
    right: Formula,
    *,
    interval: TimeInterval | None = None,
) -> Formula:
    if left.logic is not right.logic:
        raise RuntimeMTLError("binary operands use different logics")
    return Formula(operator, left.logic, (left, right), interval=interval)


def always(operand: Formula, *, interval: TimeInterval | None = None) -> Formula:
    return unary("always", operand, interval=interval)


def eventually(operand: Formula, *, interval: TimeInterval | None = None) -> Formula:
    return unary("eventually", operand, interval=interval)


def next_time(operand: Formula, *, interval: TimeInterval | None = None) -> Formula:
    return unary("next", operand, interval=interval)


def until(
    left: Formula,
    right: Formula,
    *,
    interval: TimeInterval | None = None,
) -> Formula:
    return binary("until", left, right, interval=interval)


@dataclass(frozen=True, slots=True)
class Clock:
    clock_id: str
    domain: ClockDomain = ClockDomain.DISCRETE
    unit: TimeUnit = TimeUnit.LOGICAL_TICK
    resolution: TimeValue = field(default_factory=lambda: TimeValue(1))

    def __post_init__(self) -> None:
        object.__setattr__(self, "clock_id", _identifier(self.clock_id, "clock_id"))
        object.__setattr__(self, "domain", _enum(self.domain, ClockDomain, "domain"))
        object.__setattr__(self, "unit", _enum(self.unit, TimeUnit, "unit"))
        object.__setattr__(self, "resolution", TimeValue.from_value(self.resolution))
        if self.resolution.numerator == 0:
            raise RuntimeMTLError("clock resolution must be greater than zero")
        if self.domain is ClockDomain.DISCRETE and self.resolution.denominator != 1:
            raise RuntimeMTLError("discrete clock resolution must be a whole number of units")

    def to_dict(self) -> dict[str, Any]:
        return {
            "clock_id": self.clock_id,
            "domain": self.domain.value,
            "resolution": self.resolution.to_dict(),
            "unit": self.unit.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Clock:
        value = _mapping(value, "clock")
        _reject_unknown(
            value,
            frozenset({"clock_id", "domain", "unit", "resolution"}),
            "clock",
        )
        return cls(
            clock_id=value.get("clock_id", ""),
            domain=value.get("domain", ClockDomain.DISCRETE.value),
            unit=value.get("unit", TimeUnit.LOGICAL_TICK.value),
            resolution=TimeValue.from_value(value.get("resolution", 1)),
        )


@dataclass(frozen=True, slots=True)
class Event:
    event_id: str
    event_type: str
    time: TimeValue
    true_propositions: tuple[str, ...] = ()
    false_propositions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _identifier(self.event_id, "event_id"))
        object.__setattr__(self, "event_type", _identifier(self.event_type, "event_type"))
        object.__setattr__(self, "time", TimeValue.from_value(self.time))
        true_values = _sorted_atoms(self.true_propositions, "true_propositions")
        false_values = _sorted_atoms(self.false_propositions, "false_propositions")
        overlap = sorted(set(true_values) & set(false_values))
        if overlap:
            raise RuntimeMTLError(f"propositions cannot be both true and false: {overlap}")
        object.__setattr__(self, "true_propositions", true_values)
        object.__setattr__(self, "false_propositions", false_values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "false": list(self.false_propositions),
            "time": self.time.to_dict(),
            "true": list(self.true_propositions),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Event:
        value = _mapping(value, "event")
        _reject_unknown(
            value,
            frozenset({"event_id", "event_type", "time", "true", "false", "true_propositions", "false_propositions"}),
            "event",
        )
        true_values = value.get("true", value.get("true_propositions", ()))
        false_values = value.get("false", value.get("false_propositions", ()))
        return cls(
            event_id=value.get("event_id", ""),
            event_type=value.get("event_type", "state"),
            time=TimeValue.from_value(value.get("time", 0)),
            true_propositions=tuple(true_values),
            false_propositions=tuple(false_values),
        )


@dataclass(frozen=True, slots=True)
class Trace:
    """Portable finite or finite-prefix timed event trace."""

    clock: Clock
    events: tuple[Event, ...]
    kind: TraceKind
    observation_policy: ObservationPolicyKind = ObservationPolicyKind.CLOSED_WORLD
    schema_version: str = RUNTIME_MTL_TRACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        clock = self.clock if isinstance(self.clock, Clock) else Clock.from_dict(_mapping(self.clock, "clock"))
        events = tuple(
            item if isinstance(item, Event) else Event.from_dict(_mapping(item, "event"))
            for item in self.events
        )
        object.__setattr__(self, "clock", clock)
        object.__setattr__(self, "events", events)
        object.__setattr__(self, "kind", _enum(self.kind, TraceKind, "kind"))
        object.__setattr__(
            self,
            "observation_policy",
            _enum(self.observation_policy, ObservationPolicyKind, "observation_policy"),
        )
        if self.schema_version != RUNTIME_MTL_TRACE_SCHEMA_VERSION:
            raise RuntimeMTLError(f"unsupported trace schema_version {self.schema_version!r}")
        if not events:
            raise RuntimeMTLError("trace requires at least one event")
        event_ids = [event.event_id for event in events]
        if len(event_ids) != len(set(event_ids)):
            raise RuntimeMTLError("event identifiers must be unique")
        resolution = clock.resolution.fraction
        previous: TimeValue | None = None
        for event in events:
            if event.time.fraction % resolution != 0:
                raise RuntimeMTLError(
                    f"event {event.event_id} time is not a multiple of clock resolution"
                )
            if previous is not None and event.time.fraction < previous.fraction:
                raise RuntimeMTLError("event timestamps must be non-decreasing on the primary clock")
            previous = event.time

    @property
    def is_complete(self) -> bool:
        return self.kind is TraceKind.FINITE

    def observe(self, index: int, proposition: str) -> Observation:
        event = self.events[index]
        if proposition in event.true_propositions:
            return Observation.TRUE
        if proposition in event.false_propositions:
            return Observation.FALSE
        if self.observation_policy is ObservationPolicyKind.CLOSED_WORLD:
            return Observation.FALSE
        return Observation.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        return {
            "clock": self.clock.to_dict(),
            "events": [event.to_dict() for event in self.events],
            "kind": self.kind.value,
            "observation_policy": self.observation_policy.value,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Trace:
        value = _mapping(value, "trace")
        _reject_unknown(
            value,
            frozenset({"clock", "events", "kind", "observation_policy", "schema_version"}),
            "trace",
        )
        return cls(
            clock=Clock.from_dict(_mapping(value.get("clock", {}), "clock")),
            events=tuple(value.get("events", ())),
            kind=value.get("kind", TraceKind.FINITE.value),
            observation_policy=value.get(
                "observation_policy", ObservationPolicyKind.CLOSED_WORLD.value
            ),
            schema_version=value.get("schema_version", RUNTIME_MTL_TRACE_SCHEMA_VERSION),
        )


# ---------------------------------------------------------------------------
# Result (always monitor authority)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MonitorEvaluation:
    """Portable monitoring outcome with a hard authority ceiling of monitor."""

    verdict: Verdict
    status: MonitorStatus
    authority: MonitorAuthority
    logic: Logic
    trace_kind: TraceKind
    monitorability: Monitorability
    position: int
    reason: str
    authorizes_global_proof: bool = False
    late_events: bool = False
    missing_observation: bool = False
    schema_version: str = RUNTIME_MTL_RESULT_SCHEMA_VERSION
    interface: str = RUNTIME_MTL_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "verdict", _enum(self.verdict, Verdict, "verdict"))
        object.__setattr__(self, "status", _enum(self.status, MonitorStatus, "status"))
        object.__setattr__(
            self, "authority", _enum(self.authority, MonitorAuthority, "authority")
        )
        object.__setattr__(self, "logic", _enum(self.logic, Logic, "logic"))
        object.__setattr__(self, "trace_kind", _enum(self.trace_kind, TraceKind, "trace_kind"))
        object.__setattr__(
            self,
            "monitorability",
            _enum(self.monitorability, Monitorability, "monitorability"),
        )
        if self.authority is not MonitorAuthority.MONITOR:
            raise RuntimeMTLError("runtime MTL results always have monitor authority")
        if self.authorizes_global_proof:
            raise RuntimeMTLError("no-violation-observed never becomes proof")
        if self.schema_version != RUNTIME_MTL_RESULT_SCHEMA_VERSION:
            raise RuntimeMTLError(
                f"unsupported result schema_version {self.schema_version!r}"
            )
        if self.interface != RUNTIME_MTL_INTERFACE:
            raise RuntimeMTLError(f"unsupported interface {self.interface!r}")
        # Guard: satisfied under monitor authority is observation, not proof.
        if self.status is MonitorStatus.SATISFIED and self.authorizes_global_proof:
            raise RuntimeMTLError("satisfied monitor status cannot authorize proof")

    @property
    def conclusive(self) -> bool:
        return self.verdict is not Verdict.INCONCLUSIVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority.value,
            "authorizes_global_proof": self.authorizes_global_proof,
            "interface": self.interface,
            "late_events": self.late_events,
            "logic": self.logic.value,
            "missing_observation": self.missing_observation,
            "monitorability": self.monitorability.value,
            "position": self.position,
            "reason": self.reason,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "trace_kind": self.trace_kind.value,
            "verdict": self.verdict.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> MonitorEvaluation:
        value = _mapping(value, "monitor evaluation")
        _reject_unknown(
            value,
            frozenset(
                {
                    "authority",
                    "authorizes_global_proof",
                    "interface",
                    "late_events",
                    "logic",
                    "missing_observation",
                    "monitorability",
                    "position",
                    "reason",
                    "schema_version",
                    "status",
                    "trace_kind",
                    "verdict",
                }
            ),
            "monitor evaluation",
        )
        return cls(
            verdict=value.get("verdict", Verdict.INCONCLUSIVE.value),
            status=value.get("status", MonitorStatus.UNKNOWN.value),
            authority=value.get("authority", MonitorAuthority.MONITOR.value),
            logic=value.get("logic", Logic.LTLF.value),
            trace_kind=value.get("trace_kind", TraceKind.FINITE.value),
            monitorability=value.get("monitorability", Monitorability.PREFIX.value),
            position=int(value.get("position", 0)),
            reason=_text(value.get("reason", "unspecified"), "reason"),
            authorizes_global_proof=bool(value.get("authorizes_global_proof", False)),
            late_events=bool(value.get("late_events", False)),
            missing_observation=bool(value.get("missing_observation", False)),
            schema_version=value.get("schema_version", RUNTIME_MTL_RESULT_SCHEMA_VERSION),
            interface=value.get("interface", RUNTIME_MTL_INTERFACE),
        )


def _to_verdict(value: Observation) -> Verdict:
    if value is Observation.TRUE:
        return Verdict.TRUE
    if value is Observation.FALSE:
        return Verdict.FALSE
    return Verdict.INCONCLUSIVE


def _to_status(verdict: Verdict) -> MonitorStatus:
    if verdict is Verdict.TRUE:
        return MonitorStatus.SATISFIED
    if verdict is Verdict.FALSE:
        return MonitorStatus.VIOLATED
    return MonitorStatus.UNKNOWN


def classify_monitorability(formula: Formula) -> Monitorability:
    if formula.logic is Logic.LTLF:
        return Monitorability.FINITE_TRACE
    if formula.logic is Logic.MTL and _all_future_bounds_finite(formula):
        return Monitorability.PREFIX
    if formula.operator == "always":
        return Monitorability.VIOLATION
    if formula.operator in {"eventually", "until"}:
        return Monitorability.SATISFACTION
    if formula.operator in {
        "true",
        "false",
        "atom",
        "not",
        "and",
        "or",
        "implies",
        "next",
        "previous",
        "since",
    }:
        return Monitorability.PREFIX
    return Monitorability.NOT_FINITE_MONITORABLE


def _all_future_bounds_finite(formula: Formula) -> bool:
    if formula.operator in _FUTURE:
        if formula.interval is None or formula.interval.upper is None:
            return False
    return all(_all_future_bounds_finite(operand) for operand in formula.operands)


# ---------------------------------------------------------------------------
# Three-valued evaluation
# ---------------------------------------------------------------------------


def _not(value: Observation) -> Observation:
    if value is Observation.TRUE:
        return Observation.FALSE
    if value is Observation.FALSE:
        return Observation.TRUE
    return Observation.UNKNOWN


def _and(left: Observation, right: Observation) -> Observation:
    if Observation.FALSE in (left, right):
        return Observation.FALSE
    if left is Observation.TRUE and right is Observation.TRUE:
        return Observation.TRUE
    return Observation.UNKNOWN


def _or(left: Observation, right: Observation) -> Observation:
    if Observation.TRUE in (left, right):
        return Observation.TRUE
    if left is Observation.FALSE and right is Observation.FALSE:
        return Observation.FALSE
    return Observation.UNKNOWN


def _fold(
    values: Sequence[Observation],
    operation: Any,
    identity: Observation,
) -> Observation:
    result = identity
    for value in values:
        result = operation(result, value)
    return result


def _check_metric_unit(formula: Formula, trace: Trace) -> None:
    if formula.interval is not None and formula.interval.unit is not trace.clock.unit:
        raise RuntimeMTLError("MTL interval unit does not match the trace primary clock")
    for operand in formula.operands:
        _check_metric_unit(operand, trace)


def _untimed_future_values(
    operator: str,
    children: tuple[tuple[Observation, ...], ...],
    count: int,
    *,
    monitoring: bool,
) -> tuple[Observation, ...]:
    if operator in {"eventually", "until"}:
        carry = Observation.UNKNOWN if monitoring else Observation.FALSE
    else:
        carry = Observation.UNKNOWN if monitoring else Observation.TRUE
    result = [Observation.UNKNOWN] * count
    for index in range(count - 1, -1, -1):
        if operator == "eventually":
            carry = _or(children[0][index], carry)
        elif operator == "always":
            carry = _and(children[0][index], carry)
        elif operator == "until":
            carry = _or(children[1][index], _and(children[0][index], carry))
        elif operator == "release":
            carry = _and(children[1][index], _or(children[0][index], carry))
        else:  # weak_until
            carry = _or(children[1][index], _and(children[0][index], carry))
        result[index] = carry
    return tuple(result)


def _metric_until_at(
    left: tuple[Observation, ...],
    right: tuple[Observation, ...],
    eligible: Sequence[int],
    start: int,
) -> Observation:
    candidates = [
        _and(
            right[witness],
            _fold(
                [left[index] for index in range(start, witness)],
                _and,
                Observation.TRUE,
            ),
        )
        for witness in eligible
    ]
    return _fold(candidates, _or, Observation.FALSE)


def _metric_values(
    node: Formula,
    children: tuple[tuple[Observation, ...], ...],
    trace: Trace,
    *,
    monitoring: bool,
) -> tuple[Observation, ...]:
    interval = node.interval
    assert interval is not None
    count = len(trace.events)
    times = [event.time.fraction for event in trace.events]
    results: list[Observation] = []
    for start in range(count):
        eligible = [
            index
            for index in range(start, count)
            if interval.contains(times[index] - times[start])
        ]
        elapsed = times[-1] - times[start]
        horizon_complete = not monitoring or interval.horizon_is_past(elapsed)
        operator = node.operator
        if operator == "next":
            if start + 1 < count:
                results.append(
                    children[0][start + 1]
                    if interval.contains(times[start + 1] - times[start])
                    else Observation.FALSE
                )
            else:
                results.append(Observation.UNKNOWN if monitoring else Observation.FALSE)
            continue
        if operator == "previous":
            if start == 0:
                results.append(Observation.FALSE)
            else:
                results.append(
                    children[0][start - 1]
                    if interval.contains(times[start] - times[start - 1])
                    else Observation.FALSE
                )
            continue
        if operator == "eventually":
            observed = _fold(
                [children[0][index] for index in eligible],
                _or,
                Observation.FALSE,
            )
            results.append(
                observed
                if observed is Observation.TRUE or horizon_complete
                else Observation.UNKNOWN
            )
            continue
        if operator == "always":
            observed = _fold(
                [children[0][index] for index in eligible],
                _and,
                Observation.TRUE,
            )
            results.append(
                observed
                if observed is Observation.FALSE or horizon_complete
                else Observation.UNKNOWN
            )
            continue
        if operator in {"until", "since"}:
            if operator == "since":
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
                            Observation.TRUE,
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
                            Observation.TRUE,
                        ),
                    )
                    for witness in candidates
                ]
            observed = _fold(candidate_values, _or, Observation.FALSE)
            if operator == "since":
                results.append(observed)
            else:
                observed_left = _fold(
                    [children[0][index] for index in range(start, count)],
                    _and,
                    Observation.TRUE,
                )
                results.append(
                    observed
                    if (
                        observed is Observation.TRUE
                        or observed_left is Observation.FALSE
                        or horizon_complete
                    )
                    else Observation.UNKNOWN
                )
            continue
        if operator in {"release", "weak_until"}:
            until_negated = _metric_until_at(
                tuple(_not(value) for value in children[0]),
                tuple(_not(value) for value in children[1]),
                eligible,
                start,
            )
            release = _not(until_negated)
            if operator == "release":
                observed = release
                until_value = Observation.FALSE
            else:
                until_value = _metric_until_at(children[0], children[1], eligible, start)
                globally_left = _fold(
                    [children[0][index] for index in eligible],
                    _and,
                    Observation.TRUE,
                )
                observed = _or(until_value, globally_left)
            if (
                not horizon_complete
                and observed is Observation.TRUE
                and (operator == "release" or until_value is not Observation.TRUE)
            ):
                observed = Observation.UNKNOWN
            results.append(observed)
            continue
        raise RuntimeMTLError(f"metric semantics are unsupported for {operator}")
    return tuple(results)


def _finite_tables(
    formula: Formula,
    trace: Trace,
    *,
    monitoring: bool,
) -> dict[str, tuple[Observation, ...]]:
    count = len(trace.events)
    cache: dict[str, tuple[Observation, ...]] = {}

    def table(node: Formula) -> tuple[Observation, ...]:
        if node.node_id in cache:
            return cache[node.node_id]
        operator = node.operator
        children = tuple(table(operand) for operand in node.operands)
        if operator == "true":
            values = (Observation.TRUE,) * count
        elif operator == "false":
            values = (Observation.FALSE,) * count
        elif operator == "atom":
            values = tuple(trace.observe(index, node.proposition) for index in range(count))
        elif operator == "not":
            values = tuple(_not(item) for item in children[0])
        elif operator == "and":
            values = tuple(_and(*items) for items in zip(*children, strict=True))
        elif operator == "or":
            values = tuple(_or(*items) for items in zip(*children, strict=True))
        elif operator == "implies":
            values = tuple(_or(_not(left), right) for left, right in zip(*children, strict=True))
        elif operator == "previous" and node.interval is None:
            values = (Observation.FALSE, *children[0][:-1])
        elif operator == "since" and node.interval is None:
            values_list: list[Observation] = []
            carry = Observation.FALSE
            for left, right in zip(*children, strict=True):
                carry = _or(right, _and(left, carry))
                values_list.append(carry)
            values = tuple(values_list)
        elif node.interval is not None:
            values = _metric_values(node, children, trace, monitoring=monitoring)
        elif operator == "next":
            terminal = Observation.UNKNOWN if monitoring else Observation.FALSE
            values = (*children[0][1:], terminal)
        elif operator in {"eventually", "always", "until", "release", "weak_until"}:
            values = _untimed_future_values(operator, children, count, monitoring=monitoring)
        else:
            raise RuntimeMTLError(f"unsupported operator during evaluation: {operator}")
        cache[node.node_id] = tuple(values)
        return cache[node.node_id]

    table(formula)
    return cache


def _has_unknown_atom(formula: Formula, trace: Trace) -> bool:
    if formula.operator == "atom":
        return any(
            trace.observe(index, formula.proposition) is Observation.UNKNOWN
            for index in range(len(trace.events))
        )
    return any(_has_unknown_atom(operand, trace) for operand in formula.operands)


# ---------------------------------------------------------------------------
# Public monitor API
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RuntimeMTLMonitor:
    """RuntimeMTLMonitor@1 — evaluate portable finite-trace MTL/LTLf formulas."""

    formula: Formula
    position: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.formula, Formula):
            self.formula = Formula.from_dict(_mapping(self.formula, "formula"))
        if isinstance(self.position, bool) or not isinstance(self.position, int) or self.position < 0:
            raise RuntimeMTLError("position must be a non-negative integer")

    def evaluate(self, trace: Trace | Mapping[str, Any]) -> MonitorEvaluation:
        if not isinstance(trace, Trace):
            try:
                trace = Trace.from_dict(_mapping(trace, "trace"))
            except RuntimeMTLError as error:
                return self._malformed(str(error), late_events="non-decreasing" in str(error))
        if self.position >= len(trace.events):
            return self._malformed("position is outside the trace")
        formula = self.formula
        # Finite prefixes are always monitored conservatively (LTLf or MTL).
        # Complete finite traces use exact LTLf/MTL semantics.
        monitoring = trace.kind is TraceKind.FINITE_PREFIX
        if formula.logic is Logic.LTLF and not monitoring and trace.kind is not TraceKind.FINITE:
            return self._malformed(
                "LTLf requires a complete finite or finite_prefix trace",
                logic=formula.logic,
                trace_kind=trace.kind,
            )
        if formula.logic is Logic.MTL:
            try:
                _check_metric_unit(formula, trace)
            except RuntimeMTLError as error:
                return self._malformed(str(error), logic=formula.logic, trace_kind=trace.kind)
        tables = _finite_tables(formula, trace, monitoring=monitoring)
        value = tables[formula.node_id][self.position]
        verdict = _to_verdict(value)
        if monitoring:
            reason = (
                "conservative finite-prefix verdict; no-violation-observed never becomes proof"
            )
        elif formula.logic is Logic.MTL:
            reason = "exact MTL semantics over the supplied complete finite timed trace"
        else:
            reason = "exact LTLf semantics over the supplied complete finite trace"
        return MonitorEvaluation(
            verdict=verdict,
            status=_to_status(verdict),
            authority=MonitorAuthority.MONITOR,
            logic=formula.logic,
            trace_kind=trace.kind,
            monitorability=classify_monitorability(formula),
            position=self.position,
            reason=reason,
            authorizes_global_proof=False,
            late_events=False,
            missing_observation=_has_unknown_atom(formula, trace),
        )

    def monitor(self, trace: Trace | Mapping[str, Any]) -> MonitorEvaluation:
        """Force prefix-style monitoring; requires a finite_prefix trace kind."""

        if not isinstance(trace, Trace):
            try:
                trace = Trace.from_dict(_mapping(trace, "trace"))
            except RuntimeMTLError as error:
                return self._malformed(str(error), late_events="non-decreasing" in str(error))
        if trace.kind is not TraceKind.FINITE_PREFIX:
            return self._malformed(
                "prefix monitoring requires a finite_prefix trace",
                logic=self.formula.logic,
                trace_kind=trace.kind,
            )
        return self.evaluate(trace)

    def _malformed(
        self,
        reason: str,
        *,
        late_events: bool = False,
        logic: Logic | None = None,
        trace_kind: TraceKind | None = None,
    ) -> MonitorEvaluation:
        return MonitorEvaluation(
            verdict=Verdict.INCONCLUSIVE,
            status=MonitorStatus.MALFORMED,
            authority=MonitorAuthority.MONITOR,
            logic=logic or self.formula.logic,
            trace_kind=trace_kind or TraceKind.FINITE,
            monitorability=classify_monitorability(self.formula),
            position=self.position,
            reason=reason,
            authorizes_global_proof=False,
            late_events=late_events,
            missing_observation=False,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "formula": self.formula.to_dict(),
            "interface": RUNTIME_MTL_INTERFACE,
            "position": self.position,
            "schema_version": RUNTIME_MTL_SCHEMA_VERSION,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RuntimeMTLMonitor:
        value = _mapping(value, "runtime mtl monitor")
        _reject_unknown(
            value,
            frozenset({"formula", "position", "interface", "schema_version", "trace"}),
            "runtime mtl monitor",
        )
        interface = value.get("interface", RUNTIME_MTL_INTERFACE)
        if interface != RUNTIME_MTL_INTERFACE:
            raise RuntimeMTLError(f"unsupported interface {interface!r}")
        return cls(
            formula=Formula.from_dict(_mapping(value.get("formula", {}), "formula")),
            position=int(value.get("position", 0)),
        )


def evaluate_portable(
    formula: Formula | Mapping[str, Any],
    trace: Trace | Mapping[str, Any],
    *,
    position: int = 0,
) -> MonitorEvaluation:
    """Evaluate a portable formula against a portable trace."""

    formula_obj = formula if isinstance(formula, Formula) else Formula.from_dict(formula)
    return RuntimeMTLMonitor(formula_obj, position=position).evaluate(trace)


def evaluate_case(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate a single portable request envelope used by parity fixtures."""

    payload = _mapping(payload, "evaluation case")
    _reject_unknown(
        payload,
        frozenset(
            {
                "formula",
                "trace",
                "position",
                "case_id",
                "schema_version",
                "interface",
                "expected",
            }
        ),
        "evaluation case",
    )
    result = evaluate_portable(
        _mapping(payload.get("formula", {}), "formula"),
        _mapping(payload.get("trace", {}), "trace"),
        position=int(payload.get("position", 0)),
    )
    return result.to_dict()


# ---------------------------------------------------------------------------
# Golden fixtures (shared with TypeScript parity suite)
# ---------------------------------------------------------------------------


def _tv(numerator: int, denominator: int = 1) -> dict[str, int]:
    return {"numerator": numerator, "denominator": denominator}


def _event(
    index: int,
    *true: str,
    false: tuple[str, ...] = (),
    time: tuple[int, int] | int | None = None,
    event_type: str = "state",
) -> dict[str, Any]:
    if time is None:
        time_value = _tv(index)
    elif isinstance(time, int):
        time_value = _tv(time)
    else:
        time_value = _tv(time[0], time[1])
    return {
        "event_id": f"event:{index}",
        "event_type": event_type,
        "time": time_value,
        "true": list(true),
        "false": list(false),
    }


def _clock(
    *,
    unit: str = "logical_tick",
    domain: str = "discrete",
    resolution: tuple[int, int] = (1, 1),
    clock_id: str = "clock:main",
) -> dict[str, Any]:
    return {
        "clock_id": clock_id,
        "domain": domain,
        "unit": unit,
        "resolution": _tv(resolution[0], resolution[1]),
    }


def _trace(
    kind: str,
    events: list[dict[str, Any]],
    *,
    clock: dict[str, Any] | None = None,
    policy: str = "closed_world",
) -> dict[str, Any]:
    return {
        "kind": kind,
        "clock": clock or _clock(),
        "events": events,
        "observation_policy": policy,
        "schema_version": RUNTIME_MTL_TRACE_SCHEMA_VERSION,
    }


def _atom_f(name: str, logic: str = "ltlf") -> dict[str, Any]:
    return {
        "operator": "atom",
        "logic": logic,
        "operands": [],
        "proposition": name,
        "interval": None,
        "schema_version": RUNTIME_MTL_FORMULA_SCHEMA_VERSION,
    }


def _unary_f(
    operator: str,
    operand: dict[str, Any],
    *,
    logic: str | None = None,
    interval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "operator": operator,
        "logic": logic or operand["logic"],
        "operands": [operand],
        "proposition": "",
        "interval": interval,
        "schema_version": RUNTIME_MTL_FORMULA_SCHEMA_VERSION,
    }


def _binary_f(
    operator: str,
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    logic: str | None = None,
    interval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "operator": operator,
        "logic": logic or left["logic"],
        "operands": [left, right],
        "proposition": "",
        "interval": interval,
        "schema_version": RUNTIME_MTL_FORMULA_SCHEMA_VERSION,
    }


def _interval(
    lower: int | tuple[int, int],
    upper: int | tuple[int, int] | None,
    unit: str,
    *,
    lower_closed: bool = True,
    upper_closed: bool = True,
) -> dict[str, Any]:
    def as_tv(value: int | tuple[int, int]) -> dict[str, int]:
        if isinstance(value, int):
            return _tv(value)
        return _tv(value[0], value[1])

    return {
        "lower": as_tv(lower),
        "upper": None if upper is None else as_tv(upper),
        "unit": unit,
        "lower_closed": lower_closed,
        "upper_closed": upper_closed,
        "schema_version": RUNTIME_MTL_INTERVAL_SCHEMA_VERSION,
    }


def golden_fixtures() -> list[dict[str, Any]]:
    """Canonical portable cases shared with the TypeScript reference package."""

    safe = _atom_f("safe")
    done = _atom_f("done")
    ready_mtl = _atom_f("ready", logic="mtl")
    safe_mtl = _atom_f("safe", logic="mtl")

    cases: list[dict[str, Any]] = [
        {
            "case_id": "ltlf-always-holds",
            "formula": _unary_f("always", safe),
            "trace": _trace(
                "finite",
                [_event(0, "safe"), _event(1, "safe"), _event(2, "safe", "done")],
            ),
            "position": 0,
            "expected": {
                "verdict": "true",
                "status": "satisfied",
                "authority": "monitor",
                "authorizes_global_proof": False,
                "trace_kind": "finite",
                "logic": "ltlf",
            },
        },
        {
            "case_id": "ltlf-until-done",
            "formula": _binary_f("until", safe, done),
            "trace": _trace(
                "finite",
                [_event(0, "safe"), _event(1, "safe"), _event(2, "safe", "done")],
            ),
            "position": 0,
            "expected": {
                "verdict": "true",
                "status": "satisfied",
                "authority": "monitor",
                "authorizes_global_proof": False,
                "trace_kind": "finite",
                "logic": "ltlf",
            },
        },
        {
            "case_id": "prefix-always-inconclusive",
            "formula": _unary_f("always", safe),
            "trace": _trace(
                "finite_prefix",
                [_event(0, "safe"), _event(1, "safe")],
            ),
            "position": 0,
            "expected": {
                "verdict": "inconclusive",
                "status": "unknown",
                "authority": "monitor",
                "authorizes_global_proof": False,
                "trace_kind": "finite_prefix",
                "logic": "ltlf",
            },
        },
        {
            "case_id": "prefix-always-violation",
            "formula": _unary_f("always", safe),
            "trace": _trace(
                "finite_prefix",
                [
                    _event(0, "safe"),
                    _event(1, "safe", "done"),
                    _event(2, false=("safe",)),
                ],
                policy="explicit",
            ),
            "position": 0,
            "expected": {
                "verdict": "false",
                "status": "violated",
                "authority": "monitor",
                "authorizes_global_proof": False,
                "trace_kind": "finite_prefix",
                "logic": "ltlf",
            },
        },
        {
            "case_id": "prefix-eventually-witness",
            "formula": _unary_f("eventually", done),
            "trace": _trace(
                "finite_prefix",
                [_event(0, "safe"), _event(1, "safe", "done")],
            ),
            "position": 0,
            "expected": {
                "verdict": "true",
                "status": "satisfied",
                "authority": "monitor",
                "authorizes_global_proof": False,
                "trace_kind": "finite_prefix",
                "logic": "ltlf",
            },
        },
        {
            "case_id": "explicit-missing-atom-inconclusive",
            "formula": _atom_f("unobserved"),
            "trace": _trace(
                "finite",
                [_event(0)],
                policy="explicit",
            ),
            "position": 0,
            "expected": {
                "verdict": "inconclusive",
                "status": "unknown",
                "authority": "monitor",
                "authorizes_global_proof": False,
                "missing_observation": True,
                "logic": "ltlf",
            },
        },
        {
            "case_id": "mtl-closed-interval-includes-boundary",
            "formula": _unary_f(
                "eventually",
                ready_mtl,
                interval=_interval(0, 1, "second"),
            ),
            "trace": _trace(
                "finite",
                [
                    _event(0, time=(0, 1)),
                    _event(1, time=(1, 2)),
                    _event(2, "ready", time=(1, 1)),
                ],
                clock=_clock(unit="second", domain="dense", resolution=(1, 2)),
            ),
            "position": 0,
            "expected": {
                "verdict": "true",
                "status": "satisfied",
                "authority": "monitor",
                "authorizes_global_proof": False,
                "logic": "mtl",
            },
        },
        {
            "case_id": "mtl-open-upper-excludes-boundary",
            "formula": _unary_f(
                "eventually",
                ready_mtl,
                interval=_interval(0, 1, "second", upper_closed=False),
            ),
            "trace": _trace(
                "finite",
                [
                    _event(0, time=(0, 1)),
                    _event(1, time=(1, 2)),
                    _event(2, "ready", time=(1, 1)),
                ],
                clock=_clock(unit="second", domain="dense", resolution=(1, 2)),
            ),
            "position": 0,
            "expected": {
                "verdict": "false",
                "status": "violated",
                "authority": "monitor",
                "authorizes_global_proof": False,
                "logic": "mtl",
            },
        },
        {
            "case_id": "mtl-prefix-before-horizon-inconclusive",
            "formula": _unary_f(
                "eventually",
                ready_mtl,
                interval=_interval(0, 2, "second"),
            ),
            "trace": _trace(
                "finite_prefix",
                [_event(0, time=0), _event(1, time=1)],
                clock=_clock(unit="second"),
            ),
            "position": 0,
            "expected": {
                "verdict": "inconclusive",
                "status": "unknown",
                "authority": "monitor",
                "authorizes_global_proof": False,
                "logic": "mtl",
                "trace_kind": "finite_prefix",
            },
        },
        {
            "case_id": "mtl-prefix-past-horizon-false",
            "formula": _unary_f(
                "eventually",
                ready_mtl,
                interval=_interval(0, 2, "second"),
            ),
            "trace": _trace(
                "finite_prefix",
                [_event(0, time=0), _event(1, time=1), _event(2, time=3)],
                clock=_clock(unit="second"),
            ),
            "position": 0,
            "expected": {
                "verdict": "false",
                "status": "violated",
                "authority": "monitor",
                "authorizes_global_proof": False,
                "logic": "mtl",
                "trace_kind": "finite_prefix",
            },
        },
        {
            "case_id": "late-event-malformed",
            "formula": _unary_f("always", safe),
            "trace": {
                "kind": "finite",
                "clock": _clock(),
                "events": [
                    _event(0, "safe", time=2),
                    _event(1, "safe", time=1),
                ],
                "observation_policy": "closed_world",
                "schema_version": RUNTIME_MTL_TRACE_SCHEMA_VERSION,
            },
            "position": 0,
            "expected": {
                "verdict": "inconclusive",
                "status": "malformed",
                "authority": "monitor",
                "authorizes_global_proof": False,
                "late_events": True,
            },
        },
        {
            "case_id": "serialization-roundtrip-next",
            "formula": _unary_f("next", safe),
            "trace": _trace(
                "finite",
                [_event(0, "ready"), _event(1, "safe")],
            ),
            "position": 0,
            "expected": {
                "verdict": "true",
                "status": "satisfied",
                "authority": "monitor",
                "authorizes_global_proof": False,
                "logic": "ltlf",
            },
        },
        {
            "case_id": "mtl-always-bounded-holds",
            "formula": _unary_f(
                "always",
                safe_mtl,
                interval=_interval(0, 1, "logical_tick"),
            ),
            "trace": _trace(
                "finite",
                [_event(0, "safe"), _event(1, "safe")],
            ),
            "position": 0,
            "expected": {
                "verdict": "true",
                "status": "satisfied",
                "authority": "monitor",
                "authorizes_global_proof": False,
                "logic": "mtl",
            },
        },
    ]
    for case in cases:
        case["schema_version"] = RUNTIME_MTL_SCHEMA_VERSION
        case["interface"] = RUNTIME_MTL_INTERFACE
    return cases


def golden_fixtures_json() -> str:
    """Stable JSON encoding of golden fixtures for cross-language consumers."""

    return json.dumps(golden_fixtures(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


__all__ = [
    "RUNTIME_MTL_INTERFACE",
    "RUNTIME_MTL_RESULT_SCHEMA_VERSION",
    "RUNTIME_MTL_SCHEMA_VERSION",
    "Clock",
    "ClockDomain",
    "Event",
    "Formula",
    "Logic",
    "MonitorAuthority",
    "MonitorEvaluation",
    "MonitorStatus",
    "Monitorability",
    "Observation",
    "ObservationPolicyKind",
    "RuntimeMTLError",
    "RuntimeMTLMonitor",
    "TimeInterval",
    "TimeUnit",
    "TimeValue",
    "Trace",
    "TraceKind",
    "Verdict",
    "always",
    "binary",
    "classify_monitorability",
    "evaluate_case",
    "evaluate_portable",
    "eventually",
    "golden_fixtures",
    "golden_fixtures_json",
    "next_time",
    "unary",
    "until",
]
