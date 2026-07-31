"""Typed, immutable event and trace semantics for software verification.

``TraceIR@1`` deliberately distinguishes three domains:

* a complete finite trace, suitable for LTLf;
* an incomplete finite prefix, suitable only for conservative monitoring; and
* an infinite trace represented by a finite lasso (``loop_start``).

Time values are non-negative reduced rationals measured in a declared
canonical unit.  Floating-point timestamps are rejected so serialization and
interval-boundary decisions do not depend on a host's floating-point
implementation.  Event order is semantic and is therefore preserved in the
trace identity, including the order of events with equal timestamps.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from fractions import Fraction
from functools import total_ordering
from math import gcd
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.identity import (
    CanonicalIdentity,
    canonical_identity,
)

TRACE_IR_INTERFACE: Final = "TraceIR@1"
TRACE_IR_SCHEMA_VERSION: Final = "trace-ir/v1"
TRACE_IR_IDENTITY_DOMAIN: Final = "logic.software-verification.trace"
CLOCK_SCHEMA_VERSION: Final = "trace-clock/v1"
TIME_POINT_SCHEMA_VERSION: Final = "trace-time-point/v1"
EVENT_SCHEMA_VERSION: Final = "trace-event/v1"
OBSERVATION_POLICY_SCHEMA_VERSION: Final = "trace-observation-policy/v1"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


class TraceValidationError(ValueError):
    """Raised when an event, clock, policy, or trace is malformed."""


class ClockDomain(StrEnum):
    """The mathematical domain of clock readings."""

    DISCRETE = "discrete"
    DENSE = "dense"


class TimeUnit(StrEnum):
    """Canonical spellings for supported trace time units."""

    NANOSECOND = "nanosecond"
    MICROSECOND = "microsecond"
    MILLISECOND = "millisecond"
    SECOND = "second"
    MINUTE = "minute"
    HOUR = "hour"
    LOGICAL_TICK = "logical_tick"


class TraceKind(StrEnum):
    """Trace domains whose semantics must never be interchanged."""

    FINITE = "finite"
    FINITE_PREFIX = "finite_prefix"
    INFINITE = "infinite"


class ObservationPolicyKind(StrEnum):
    """How absent atomic propositions are interpreted."""

    CLOSED_WORLD = "closed_world"
    EXPLICIT = "explicit"
    PROJECTED = "projected"


class ObservationValue(StrEnum):
    """A proposition's value after applying an observation policy."""

    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or "\x00" in value:
        raise TraceValidationError(f"{label} must be a non-empty trimmed string without NUL bytes")
    return value


def _identifier(value: object, label: str) -> str:
    result = _text(value, label)
    if not _ID_RE.fullmatch(result):
        raise TraceValidationError(f"{label} must be a stable identifier")
    return result


def _enum(value: object, enum_type: type[StrEnum], label: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise TraceValidationError(f"{label} must be one of {choices}") from error


def _strings(values: Sequence[str] | object, label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise TraceValidationError(f"{label} must be a sequence of identifiers")
    result = tuple(_identifier(item, f"{label} item") for item in values)
    if len(result) != len(set(result)):
        raise TraceValidationError(f"{label} must not contain duplicates")
    return tuple(sorted(result))


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TraceValidationError(f"{label} must be a mapping")
    return value


def _frozen(value: Mapping[str, Any] | FrozenMap, label: str) -> FrozenMap:
    try:
        return value if isinstance(value, FrozenMap) else FrozenMap(value)
    except (TypeError, ValueError) as error:
        raise TraceValidationError(
            f"{label} must contain immutable JSON-compatible data"
        ) from error


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise TraceValidationError(f"unknown {label} field(s): {', '.join(unknown)}")


@total_ordering
@dataclass(frozen=True, slots=True)
class TimeValue:
    """An exact, non-negative rational number of clock units."""

    numerator: int
    denominator: int = 1

    def __post_init__(self) -> None:
        if isinstance(self.numerator, bool) or not isinstance(self.numerator, int):
            raise TraceValidationError("time numerator must be an integer")
        if isinstance(self.denominator, bool) or not isinstance(self.denominator, int):
            raise TraceValidationError("time denominator must be an integer")
        if self.numerator < 0:
            raise TraceValidationError("time values must be non-negative")
        if self.denominator <= 0:
            raise TraceValidationError("time denominator must be positive")
        divisor = gcd(self.numerator, self.denominator)
        object.__setattr__(self, "numerator", self.numerator // divisor)
        object.__setattr__(self, "denominator", self.denominator // divisor)

    @property
    def fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)

    def to_dict(self) -> dict[str, int]:
        return {
            "denominator": self.denominator,
            "numerator": self.numerator,
        }

    @classmethod
    def from_value(cls, value: TimeValue | int | Mapping[str, Any]) -> TimeValue:
        if isinstance(value, cls):
            return value
        if isinstance(value, bool):
            raise TraceValidationError("time values must not be booleans")
        if isinstance(value, int):
            return cls(value)
        value = _mapping(value, "time value")
        _reject_unknown(value, frozenset({"numerator", "denominator"}), "time value")
        return cls(
            numerator=value.get("numerator"),  # type: ignore[arg-type]
            denominator=value.get("denominator", 1),  # type: ignore[arg-type]
        )

    def __sub__(self, other: TimeValue) -> Fraction:
        return self.fraction - other.fraction

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, TimeValue):
            return NotImplemented
        return self.fraction < other.fraction


@dataclass(frozen=True, slots=True)
class Clock:
    """A named trace clock with an exact resolution."""

    clock_id: str
    domain: ClockDomain = ClockDomain.DISCRETE
    unit: TimeUnit = TimeUnit.LOGICAL_TICK
    resolution: TimeValue = field(default_factory=lambda: TimeValue(1))
    epoch: str = ""
    schema_version: str = CLOCK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "clock_id", _identifier(self.clock_id, "clock_id"))
        object.__setattr__(self, "domain", _enum(self.domain, ClockDomain, "domain"))
        object.__setattr__(self, "unit", _enum(self.unit, TimeUnit, "unit"))
        object.__setattr__(self, "resolution", TimeValue.from_value(self.resolution))
        if self.resolution.numerator == 0:
            raise TraceValidationError("clock resolution must be greater than zero")
        if self.domain is ClockDomain.DISCRETE and self.resolution.denominator != 1:
            raise TraceValidationError("discrete clock resolution must be a whole number of units")
        if self.epoch:
            object.__setattr__(self, "epoch", _text(self.epoch, "epoch"))
        if self.schema_version != CLOCK_SCHEMA_VERSION:
            raise TraceValidationError(f"unsupported clock schema_version {self.schema_version!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "clock_id": self.clock_id,
            "domain": self.domain.value,
            "epoch": self.epoch,
            "resolution": self.resolution.to_dict(),
            "schema_version": self.schema_version,
            "unit": self.unit.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Clock:
        value = _mapping(value, "clock")
        _reject_unknown(
            value,
            frozenset(
                {
                    "clock_id",
                    "domain",
                    "unit",
                    "resolution",
                    "epoch",
                    "schema_version",
                }
            ),
            "clock",
        )
        return cls(
            clock_id=value.get("clock_id", ""),
            domain=value.get("domain", ClockDomain.DISCRETE.value),
            unit=value.get("unit", TimeUnit.LOGICAL_TICK.value),
            resolution=TimeValue.from_value(value.get("resolution", 1)),
            epoch=value.get("epoch", ""),
            schema_version=value.get("schema_version", CLOCK_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class TimePoint:
    """One exact reading on a declared clock."""

    clock_id: str
    value: TimeValue
    schema_version: str = TIME_POINT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "clock_id", _identifier(self.clock_id, "clock_id"))
        object.__setattr__(self, "value", TimeValue.from_value(self.value))
        if self.schema_version != TIME_POINT_SCHEMA_VERSION:
            raise TraceValidationError(
                f"unsupported time-point schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "clock_id": self.clock_id,
            "schema_version": self.schema_version,
            "value": self.value.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TimePoint:
        value = _mapping(value, "time point")
        _reject_unknown(
            value,
            frozenset({"clock_id", "value", "schema_version"}),
            "time point",
        )
        return cls(
            clock_id=value.get("clock_id", ""),
            value=TimeValue.from_value(value.get("value", {})),
            schema_version=value.get("schema_version", TIME_POINT_SCHEMA_VERSION),
        )


# A domain-friendly spelling for adapters that expose clock readings.
ClockReading = TimePoint


@dataclass(frozen=True, slots=True)
class Event:
    """A typed observation at one exact time point."""

    event_id: str
    event_type: str
    time: TimePoint
    propositions: tuple[str, ...] = ()
    false_propositions: tuple[str, ...] = ()
    payload: FrozenMap = field(default_factory=FrozenMap)
    source_ref_ids: tuple[str, ...] = ()
    schema_version: str = EVENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _identifier(self.event_id, "event_id"))
        object.__setattr__(self, "event_type", _identifier(self.event_type, "event_type"))
        if isinstance(self.time, Mapping):
            object.__setattr__(self, "time", TimePoint.from_dict(self.time))
        if not isinstance(self.time, TimePoint):
            raise TraceValidationError("event time must be a TimePoint")
        true_values = _strings(self.propositions, "propositions")
        false_values = _strings(self.false_propositions, "false_propositions")
        overlap = sorted(set(true_values) & set(false_values))
        if overlap:
            raise TraceValidationError(f"propositions cannot be both true and false: {overlap}")
        object.__setattr__(self, "propositions", true_values)
        object.__setattr__(self, "false_propositions", false_values)
        object.__setattr__(self, "payload", _frozen(self.payload, "payload"))
        object.__setattr__(self, "source_ref_ids", _strings(self.source_ref_ids, "source_ref_ids"))
        if self.schema_version != EVENT_SCHEMA_VERSION:
            raise TraceValidationError(f"unsupported event schema_version {self.schema_version!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "false_propositions": list(self.false_propositions),
            "payload": self.payload.to_dict(),
            "propositions": list(self.propositions),
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "time": self.time.to_dict(),
        }

    @property
    def kind(self) -> str:
        """Compatibility spelling for domain adapters."""

        return self.event_type

    @property
    def timestamp(self) -> TimeValue:
        """Return the exact primary-clock reading."""

        return self.time.value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Event:
        value = _mapping(value, "event")
        _reject_unknown(
            value,
            frozenset(
                {
                    "event_id",
                    "event_type",
                    "time",
                    "propositions",
                    "false_propositions",
                    "payload",
                    "source_ref_ids",
                    "schema_version",
                }
            ),
            "event",
        )
        return cls(
            event_id=value.get("event_id", ""),
            event_type=value.get("event_type", ""),
            time=TimePoint.from_dict(_mapping(value.get("time", {}), "event time")),
            propositions=tuple(value.get("propositions", ())),
            false_propositions=tuple(value.get("false_propositions", ())),
            payload=_frozen(_mapping(value.get("payload", {}), "payload"), "payload"),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            schema_version=value.get("schema_version", EVENT_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class ObservationPolicy:
    """Declare which truth value an event supplies for an absent atom."""

    policy_id: str
    kind: ObservationPolicyKind = ObservationPolicyKind.CLOSED_WORLD
    visible_propositions: tuple[str, ...] = ()
    schema_version: str = OBSERVATION_POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _identifier(self.policy_id, "policy_id"))
        object.__setattr__(self, "kind", _enum(self.kind, ObservationPolicyKind, "kind"))
        visible = _strings(self.visible_propositions, "visible_propositions")
        object.__setattr__(self, "visible_propositions", visible)
        if self.kind is ObservationPolicyKind.PROJECTED and not visible:
            raise TraceValidationError(
                "projected observation policies require visible_propositions"
            )
        if self.kind is not ObservationPolicyKind.PROJECTED and visible:
            raise TraceValidationError("visible_propositions are only valid for projected policies")
        if self.schema_version != OBSERVATION_POLICY_SCHEMA_VERSION:
            raise TraceValidationError(
                f"unsupported observation-policy schema_version {self.schema_version!r}"
            )

    def observe(self, event: Event, proposition: str) -> ObservationValue:
        proposition = _identifier(proposition, "proposition")
        if proposition in event.propositions:
            return ObservationValue.TRUE
        if proposition in event.false_propositions:
            return ObservationValue.FALSE
        if self.kind is ObservationPolicyKind.CLOSED_WORLD:
            return ObservationValue.FALSE
        if self.kind is ObservationPolicyKind.PROJECTED:
            return (
                ObservationValue.FALSE
                if proposition in self.visible_propositions
                else ObservationValue.UNKNOWN
            )
        return ObservationValue.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "policy_id": self.policy_id,
            "schema_version": self.schema_version,
            "visible_propositions": list(self.visible_propositions),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ObservationPolicy:
        value = _mapping(value, "observation policy")
        _reject_unknown(
            value,
            frozenset(
                {
                    "policy_id",
                    "kind",
                    "visible_propositions",
                    "schema_version",
                }
            ),
            "observation policy",
        )
        return cls(
            policy_id=value.get("policy_id", ""),
            kind=value.get("kind", ObservationPolicyKind.CLOSED_WORLD.value),
            visible_propositions=tuple(value.get("visible_propositions", ())),
            schema_version=value.get("schema_version", OBSERVATION_POLICY_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class TraceIR:
    """An immutable, content-addressed timed event trace."""

    clocks: tuple[Clock, ...]
    events: tuple[Event, ...]
    kind: TraceKind
    observation_policy: ObservationPolicy
    primary_clock_id: str
    loop_start: int | None = None
    metadata: FrozenMap = field(default_factory=FrozenMap)
    trace_id: str = ""
    schema_version: str = TRACE_IR_SCHEMA_VERSION

    INTERFACE: ClassVar[str] = TRACE_IR_INTERFACE

    def __post_init__(self) -> None:
        clocks = tuple(
            item if isinstance(item, Clock) else Clock.from_dict(_mapping(item, "clock"))
            for item in self.clocks
        )
        events = tuple(
            item if isinstance(item, Event) else Event.from_dict(_mapping(item, "event"))
            for item in self.events
        )
        object.__setattr__(self, "clocks", clocks)
        object.__setattr__(self, "events", events)
        object.__setattr__(self, "kind", _enum(self.kind, TraceKind, "kind"))
        policy = self.observation_policy
        if isinstance(policy, Mapping):
            policy = ObservationPolicy.from_dict(policy)
        if not isinstance(policy, ObservationPolicy):
            raise TraceValidationError("observation_policy must be an ObservationPolicy")
        object.__setattr__(self, "observation_policy", policy)
        object.__setattr__(
            self,
            "primary_clock_id",
            _identifier(self.primary_clock_id, "primary_clock_id"),
        )
        object.__setattr__(self, "metadata", _frozen(self.metadata, "metadata"))
        self.validate()
        identity = self._compute_identity()
        if self.trace_id and self.trace_id != identity.cid:
            raise TraceValidationError("trace_id does not match canonical semantic content")
        object.__setattr__(self, "trace_id", identity.cid)

    @property
    def identity(self) -> CanonicalIdentity:
        return self._compute_identity()

    @property
    def canonical_id(self) -> str:
        return self.trace_id

    @property
    def primary_clock(self) -> Clock:
        return next(clock for clock in self.clocks if clock.clock_id == self.primary_clock_id)

    @property
    def is_complete(self) -> bool:
        return self.kind is not TraceKind.FINITE_PREFIX

    @property
    def trace_kind(self) -> TraceKind:
        """An explicit spelling useful at API boundaries."""

        return self.kind

    def validate(self) -> None:
        if self.schema_version != TRACE_IR_SCHEMA_VERSION:
            raise TraceValidationError(f"unsupported trace schema_version {self.schema_version!r}")
        if not self.clocks:
            raise TraceValidationError("a trace requires at least one clock")
        clock_ids = [clock.clock_id for clock in self.clocks]
        if len(clock_ids) != len(set(clock_ids)):
            raise TraceValidationError("clock identifiers must be unique")
        if self.primary_clock_id not in clock_ids:
            raise TraceValidationError("primary_clock_id references an unknown clock")
        event_ids = [event.event_id for event in self.events]
        if len(event_ids) != len(set(event_ids)):
            raise TraceValidationError("event identifiers must be unique")
        for event in self.events:
            if event.time.clock_id != self.primary_clock_id:
                raise TraceValidationError(
                    f"event {event.event_id} is not measured by the primary clock"
                )
        for previous, current in zip(self.events, self.events[1:], strict=False):
            if current.time.value.fraction < previous.time.value.fraction:
                raise TraceValidationError(
                    "events must be ordered by non-decreasing primary-clock time"
                )
        if self.primary_clock.domain is ClockDomain.DISCRETE:
            for event in self.events:
                if event.time.value.denominator != 1:
                    raise TraceValidationError("discrete-clock event readings must be whole units")
        resolution = self.primary_clock.resolution.fraction
        for event in self.events:
            if (event.time.value.fraction / resolution).denominator != 1:
                raise TraceValidationError(
                    f"event {event.event_id} does not align with clock resolution"
                )
        if self.kind is TraceKind.INFINITE:
            if not self.events:
                raise TraceValidationError("an infinite lasso requires events")
            if (
                isinstance(self.loop_start, bool)
                or not isinstance(self.loop_start, int)
                or not 0 <= self.loop_start < len(self.events)
            ):
                raise TraceValidationError(
                    "an infinite trace requires loop_start within its events"
                )
        elif self.loop_start is not None:
            raise TraceValidationError("loop_start is only valid for an infinite trace")

    def successor(self, position: int) -> int | None:
        """Return the semantic successor, following an infinite lasso's loop."""

        self._require_position(position)
        if position + 1 < len(self.events):
            return position + 1
        if self.kind is TraceKind.INFINITE:
            assert self.loop_start is not None
            return self.loop_start
        return None

    def observe(self, position: int, proposition: str) -> ObservationValue:
        self._require_position(position)
        return self.observation_policy.observe(self.events[position], proposition)

    def _require_position(self, position: int) -> None:
        if (
            isinstance(position, bool)
            or not isinstance(position, int)
            or not 0 <= position < len(self.events)
        ):
            raise TraceValidationError("position is outside the trace")

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "clocks": [
                item.to_dict() for item in sorted(self.clocks, key=lambda item: item.clock_id)
            ],
            "events": [item.to_dict() for item in self.events],
            "kind": self.kind.value,
            "loop_start": self.loop_start,
            "metadata": self.metadata.to_dict(),
            "observation_policy": self.observation_policy.to_dict(),
            "primary_clock_id": self.primary_clock_id,
            "schema_version": self.schema_version,
        }

    deterministic_dict = semantic_dict

    def to_dict(self) -> dict[str, Any]:
        result = self.semantic_dict()
        result["trace_id"] = self.trace_id
        return result

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=TRACE_IR_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TraceIR:
        value = _mapping(value, "trace")
        _reject_unknown(
            value,
            frozenset(
                {
                    "clocks",
                    "events",
                    "kind",
                    "observation_policy",
                    "primary_clock_id",
                    "loop_start",
                    "metadata",
                    "trace_id",
                    "schema_version",
                }
            ),
            "trace",
        )
        return cls(
            clocks=tuple(
                Clock.from_dict(_mapping(item, "clock")) for item in value.get("clocks", ())
            ),
            events=tuple(
                Event.from_dict(_mapping(item, "event")) for item in value.get("events", ())
            ),
            kind=value.get("kind", ""),
            observation_policy=ObservationPolicy.from_dict(
                _mapping(value.get("observation_policy", {}), "observation policy")
            ),
            primary_clock_id=value.get("primary_clock_id", ""),
            loop_start=value.get("loop_start"),
            metadata=_frozen(_mapping(value.get("metadata", {}), "metadata"), "metadata"),
            trace_id=value.get("trace_id", ""),
            schema_version=value.get("schema_version", TRACE_IR_SCHEMA_VERSION),
        )

    @classmethod
    def from_state_sequence(
        cls,
        states: Sequence[object],
        *,
        trace_kind: TraceKind = TraceKind.FINITE,
        clock_id: str = "clock:legacy",
        observation_policy: ObservationPolicy | None = None,
        loop_start: int | None = None,
        proposition_adapter: Callable[[object], Mapping[str, bool]] | None = None,
    ) -> TraceIR:
        """Explicitly adapt legacy ``time``/``valuations`` state objects.

        No implicit conversion occurs in constructors.  Callers may supply an
        adapter for other state shapes; its result must be a boolean mapping.
        """

        if isinstance(states, (str, bytes, bytearray)) or not isinstance(states, Sequence):
            raise TraceValidationError("states must be a sequence")
        events: list[Event] = []
        for index, state in enumerate(states):
            if proposition_adapter is None:
                valuations = getattr(state, "valuations", None)
            else:
                valuations = proposition_adapter(state)
            if not isinstance(valuations, Mapping) or not all(
                isinstance(name, str) and isinstance(value, bool)
                for name, value in valuations.items()
            ):
                raise TraceValidationError(
                    "legacy state valuations must map proposition names to booleans"
                )
            raw_time = getattr(state, "time", index)
            if isinstance(raw_time, bool) or not isinstance(raw_time, int):
                raise TraceValidationError("legacy state times must be non-negative integers")
            events.append(
                Event(
                    event_id=f"event:{index}",
                    event_type="legacy_state",
                    time=TimePoint(clock_id, TimeValue(raw_time)),
                    propositions=tuple(name for name, value in valuations.items() if value),
                    false_propositions=tuple(
                        name for name, value in valuations.items() if not value
                    ),
                )
            )
        return cls(
            clocks=(Clock(clock_id),),
            events=tuple(events),
            kind=trace_kind,
            observation_policy=observation_policy
            or ObservationPolicy("policy:legacy-explicit", ObservationPolicyKind.EXPLICIT),
            primary_clock_id=clock_id,
            loop_start=loop_start,
        )


__all__ = [
    "CLOCK_SCHEMA_VERSION",
    "EVENT_SCHEMA_VERSION",
    "OBSERVATION_POLICY_SCHEMA_VERSION",
    "TIME_POINT_SCHEMA_VERSION",
    "TRACE_IR_IDENTITY_DOMAIN",
    "TRACE_IR_INTERFACE",
    "TRACE_IR_SCHEMA_VERSION",
    "Clock",
    "ClockDomain",
    "ClockReading",
    "Event",
    "ObservationPolicy",
    "ObservationPolicyKind",
    "ObservationValue",
    "TimePoint",
    "TimeUnit",
    "TimeValue",
    "TraceIR",
    "TraceKind",
    "TraceValidationError",
]
