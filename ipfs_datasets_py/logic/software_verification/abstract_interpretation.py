"""Deterministic, conservative abstract interpretation for a Python subset.

This module owns semantic evidence, not operational scheduling or proof
authority.  It deliberately implements a small, documented Python subset and
widens to an explicit opaque state when reflection, dynamic code loading,
native calls, or unknown callbacks cross that boundary.  An analysis receipt
is content addressed, but its CID establishes identity only; it is not a proof
of the represented program.

The initial product domain is::

    constant x integer interval x nullness x exceptions x effects

The lattice and worklist solver are frontend independent.  The Python adapter
provides interprocedural summaries for local functions and preserves source
locations for every recorded program point.
"""

from __future__ import annotations

import ast
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final, Protocol, Self, runtime_checkable

from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.logic.ir_core.identity import CanonicalIdentity, canonical_identity

ABSTRACT_ANALYSIS_INTERFACE: Final = "AbstractAnalysisResult@1"
ABSTRACT_ANALYSIS_SCHEMA_VERSION: Final = "software-abstract-analysis/v1"
ABSTRACT_ANALYSIS_IDENTITY_DOMAIN: Final = "logic.software-verification.abstract-analysis"
ABSTRACT_SOURCE_IDENTITY_DOMAIN: Final = "logic.software-verification.python-source"
ABSTRACT_ANALYZER_IDENTITY_DOMAIN: Final = "logic.software-verification.abstract-analyzer"
ABSTRACT_SUMMARY_IDENTITY_DOMAIN: Final = "logic.software-verification.abstract-summary"
PYTHON_ANALYZER_INTERFACE: Final = "PythonAbstractInterpreter@1"
PYTHON_ANALYZER_VERSION: Final = "python-abstract-interpreter/1.0.0"


class AbstractInterpretationError(ValueError):
    """Raised when analysis input or configuration is malformed."""


class SoundnessClass(StrEnum):
    """Semantic support classification for an abstract result."""

    EXACT = "exact"
    CONSERVATIVE = "conservative"
    OPAQUE = "opaque"


@runtime_checkable
class AbstractDomain(Protocol):
    """Protocol implemented by every immutable abstract lattice value."""

    @classmethod
    def bottom(cls) -> Self:
        """Return the least element."""

    @classmethod
    def top(cls) -> Self:
        """Return the greatest element."""

    def less_equal(self, other: Self) -> bool:
        """Return whether this value denotes a subset of ``other``."""

    def abstract_equal(self, other: Self) -> bool:
        """Return semantic lattice equality."""

    def join(self, other: Self) -> Self:
        """Return the least upper bound."""

    def meet(self, other: Self) -> Self:
        """Return the greatest lower bound."""

    def widen(self, other: Self) -> Self:
        """Return a convergence-accelerating upper bound."""

    def narrow(self, other: Self) -> Self:
        """Refine a widened value without becoming unsound."""


class ConstantKind(StrEnum):
    BOTTOM = "bottom"
    VALUE = "value"
    TOP = "top"


_CONSTANT_TYPES = (str, int, bool, type(None))


@dataclass(frozen=True, slots=True)
class ConstantValue:
    """Flat constant-propagation lattice over canonical scalar values."""

    kind: ConstantKind
    value: str | int | bool | None = None

    def __post_init__(self) -> None:
        kind = self.kind if isinstance(self.kind, ConstantKind) else ConstantKind(self.kind)
        object.__setattr__(self, "kind", kind)
        if kind is ConstantKind.VALUE:
            if not isinstance(self.value, _CONSTANT_TYPES):
                raise AbstractInterpretationError("constant values must be canonical scalars")
        elif self.value is not None:
            raise AbstractInterpretationError("bottom and top constants cannot carry a value")

    @classmethod
    def bottom(cls) -> ConstantValue:
        return cls(ConstantKind.BOTTOM)

    @classmethod
    def top(cls) -> ConstantValue:
        return cls(ConstantKind.TOP)

    @classmethod
    def constant(cls, value: str | int | bool | None) -> ConstantValue:
        return cls(ConstantKind.VALUE, value)

    def less_equal(self, other: ConstantValue) -> bool:
        if self.kind is ConstantKind.BOTTOM or other.kind is ConstantKind.TOP:
            return True
        return self == other

    def abstract_equal(self, other: ConstantValue) -> bool:
        return self == other

    def join(self, other: ConstantValue) -> ConstantValue:
        if self.kind is ConstantKind.BOTTOM:
            return other
        if other.kind is ConstantKind.BOTTOM:
            return self
        return self if self == other else self.top()

    def meet(self, other: ConstantValue) -> ConstantValue:
        if self.kind is ConstantKind.TOP:
            return other
        if other.kind is ConstantKind.TOP:
            return self
        return self if self == other else self.bottom()

    def widen(self, other: ConstantValue) -> ConstantValue:
        return self.join(other)

    def narrow(self, other: ConstantValue) -> ConstantValue:
        return other if self.kind is ConstantKind.TOP else self.meet(other)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "value": self.value}


@dataclass(frozen=True, slots=True)
class IntervalValue:
    """Closed integer interval; ``None`` bounds denote infinities."""

    lower: int | None = None
    upper: int | None = None
    empty: bool = False

    def __post_init__(self) -> None:
        for label, bound in (("lower", self.lower), ("upper", self.upper)):
            if bound is not None and (isinstance(bound, bool) or not isinstance(bound, int)):
                raise AbstractInterpretationError(f"interval {label} must be an integer or None")
        if self.empty and (self.lower is not None or self.upper is not None):
            raise AbstractInterpretationError("a bottom interval cannot carry bounds")
        if not self.empty and self.lower is not None and self.upper is not None:
            if self.lower > self.upper:
                raise AbstractInterpretationError("interval lower bound exceeds upper bound")

    @classmethod
    def bottom(cls) -> IntervalValue:
        return cls(empty=True)

    @classmethod
    def top(cls) -> IntervalValue:
        return cls()

    @classmethod
    def constant(cls, value: int) -> IntervalValue:
        if isinstance(value, bool) or not isinstance(value, int):
            raise AbstractInterpretationError("interval constants must be integers")
        return cls(value, value)

    def less_equal(self, other: IntervalValue) -> bool:
        if self.empty or (other.lower is None and other.upper is None and not other.empty):
            return True
        if other.empty:
            return self.empty
        lower_ok = other.lower is None or (self.lower is not None and other.lower <= self.lower)
        upper_ok = other.upper is None or (self.upper is not None and self.upper <= other.upper)
        return lower_ok and upper_ok

    def abstract_equal(self, other: IntervalValue) -> bool:
        return self == other

    def join(self, other: IntervalValue) -> IntervalValue:
        if self.empty:
            return other
        if other.empty:
            return self
        lower = None if self.lower is None or other.lower is None else min(self.lower, other.lower)
        upper = None if self.upper is None or other.upper is None else max(self.upper, other.upper)
        return IntervalValue(lower, upper)

    def meet(self, other: IntervalValue) -> IntervalValue:
        if self.empty or other.empty:
            return self.bottom()
        lower = (
            other.lower
            if self.lower is None
            else self.lower
            if other.lower is None
            else max(self.lower, other.lower)
        )
        upper = (
            other.upper
            if self.upper is None
            else self.upper
            if other.upper is None
            else min(self.upper, other.upper)
        )
        if lower is not None and upper is not None and lower > upper:
            return self.bottom()
        return IntervalValue(lower, upper)

    def widen(self, other: IntervalValue) -> IntervalValue:
        if self.empty:
            return other
        if other.empty:
            return self
        lower = self.lower
        upper = self.upper
        if self.lower is not None and (other.lower is None or other.lower < self.lower):
            lower = None
        if self.upper is not None and (other.upper is None or other.upper > self.upper):
            upper = None
        return IntervalValue(lower, upper)

    def narrow(self, other: IntervalValue) -> IntervalValue:
        if self.empty or other.empty:
            return self.meet(other)
        lower = other.lower if self.lower is None else self.lower
        upper = other.upper if self.upper is None else self.upper
        candidate = IntervalValue(lower, upper)
        return self.meet(candidate)

    def contains(self, value: int) -> bool:
        if self.empty:
            return False
        return (self.lower is None or self.lower <= value) and (
            self.upper is None or value <= self.upper
        )

    def excludes(self, value: int) -> bool:
        return not self.contains(value)

    def add(self, other: IntervalValue) -> IntervalValue:
        if self.empty or other.empty:
            return self.bottom()
        lower = None if self.lower is None or other.lower is None else self.lower + other.lower
        upper = None if self.upper is None or other.upper is None else self.upper + other.upper
        return IntervalValue(lower, upper)

    def subtract(self, other: IntervalValue) -> IntervalValue:
        if self.empty or other.empty:
            return self.bottom()
        lower = None if self.lower is None or other.upper is None else self.lower - other.upper
        upper = None if self.upper is None or other.lower is None else self.upper - other.lower
        return IntervalValue(lower, upper)

    def multiply(self, other: IntervalValue) -> IntervalValue:
        if self.empty or other.empty:
            return self.bottom()
        left_lower = self.lower
        left_upper = self.upper
        right_lower = other.lower
        right_upper = other.upper
        if None in (left_lower, left_upper, right_lower, right_upper):
            if self == IntervalValue.constant(0) or other == IntervalValue.constant(0):
                return IntervalValue.constant(0)
            return self.top()
        assert left_lower is not None and left_upper is not None
        assert right_lower is not None and right_upper is not None
        products = (
            left_lower * right_lower,
            left_lower * right_upper,
            left_upper * right_lower,
            left_upper * right_upper,
        )
        return IntervalValue(min(products), max(products))

    def to_dict(self) -> dict[str, Any]:
        return {"empty": self.empty, "lower": self.lower, "upper": self.upper}


class NullnessKind(StrEnum):
    BOTTOM = "bottom"
    NULL = "null"
    NONNULL = "nonnull"
    MAYBE = "maybe_null"


@dataclass(frozen=True, slots=True)
class NullnessValue:
    """Four-element nullness diamond."""

    kind: NullnessKind

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            self.kind if isinstance(self.kind, NullnessKind) else NullnessKind(self.kind),
        )

    @classmethod
    def bottom(cls) -> NullnessValue:
        return cls(NullnessKind.BOTTOM)

    @classmethod
    def top(cls) -> NullnessValue:
        return cls(NullnessKind.MAYBE)

    def less_equal(self, other: NullnessValue) -> bool:
        return self.kind is NullnessKind.BOTTOM or other.kind is NullnessKind.MAYBE or self == other

    def abstract_equal(self, other: NullnessValue) -> bool:
        return self == other

    def join(self, other: NullnessValue) -> NullnessValue:
        if self.kind is NullnessKind.BOTTOM:
            return other
        if other.kind is NullnessKind.BOTTOM:
            return self
        return self if self == other else self.top()

    def meet(self, other: NullnessValue) -> NullnessValue:
        if self.kind is NullnessKind.MAYBE:
            return other
        if other.kind is NullnessKind.MAYBE:
            return self
        return self if self == other else self.bottom()

    def widen(self, other: NullnessValue) -> NullnessValue:
        return self.join(other)

    def narrow(self, other: NullnessValue) -> NullnessValue:
        return other if self.kind is NullnessKind.MAYBE else self.meet(other)

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind.value}


@dataclass(frozen=True, slots=True)
class ExceptionState:
    """Powerset domain for possible exception classes."""

    exceptions: frozenset[str] = frozenset()
    unknown: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.unknown, bool):
            raise AbstractInterpretationError("exception unknown marker must be boolean")
        normalized = frozenset(_stable_text(value, "exception") for value in self.exceptions)
        # ``unknown`` is the unique powerset top; retaining a finite subset
        # beside it would create multiple representations of the same lattice
        # element and unstable identities.
        object.__setattr__(self, "exceptions", frozenset() if self.unknown else normalized)

    @classmethod
    def bottom(cls) -> ExceptionState:
        return cls()

    @classmethod
    def top(cls) -> ExceptionState:
        return cls(unknown=True)

    def less_equal(self, other: ExceptionState) -> bool:
        if other.unknown:
            return True
        return not self.unknown and self.exceptions <= other.exceptions

    def abstract_equal(self, other: ExceptionState) -> bool:
        return self == other

    def join(self, other: ExceptionState) -> ExceptionState:
        return ExceptionState(self.exceptions | other.exceptions, self.unknown or other.unknown)

    def meet(self, other: ExceptionState) -> ExceptionState:
        if self.unknown:
            return other
        if other.unknown:
            return self
        return ExceptionState(self.exceptions & other.exceptions)

    def widen(self, other: ExceptionState) -> ExceptionState:
        return self.join(other)

    def narrow(self, other: ExceptionState) -> ExceptionState:
        return other if self.unknown else self.meet(other)

    def add(self, exception: str) -> ExceptionState:
        return ExceptionState(self.exceptions | {_stable_text(exception, "exception")}, self.unknown)

    def to_dict(self) -> dict[str, Any]:
        return {"exceptions": sorted(self.exceptions), "unknown": self.unknown}


class EffectKind(StrEnum):
    READ = "read"
    WRITE = "write"
    ALLOCATION = "allocation"
    IO = "io"
    NETWORK = "network"
    SUBPROCESS = "subprocess"
    FILESYSTEM = "filesystem"
    SECRET = "secret"
    SYNCHRONIZATION = "synchronization"
    IMPORT = "import"
    CALL = "call"


@dataclass(frozen=True, slots=True, order=True)
class EffectAtom:
    """One typed, source-independent effect observation."""

    kind: EffectKind
    target: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            self.kind if isinstance(self.kind, EffectKind) else EffectKind(self.kind),
        )
        object.__setattr__(self, "target", _stable_text(self.target, "effect target"))

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind.value, "target": self.target}


@dataclass(frozen=True, slots=True)
class EffectState:
    """Powerset effect domain with an explicit unknown top marker."""

    effects: frozenset[EffectAtom] = frozenset()
    unknown: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.unknown, bool):
            raise AbstractInterpretationError("effect unknown marker must be boolean")
        # As with exceptions, normalize the unknown powerset top to one wire
        # representation.
        object.__setattr__(self, "effects", frozenset() if self.unknown else frozenset(self.effects))

    @classmethod
    def bottom(cls) -> EffectState:
        return cls()

    @classmethod
    def top(cls) -> EffectState:
        return cls(unknown=True)

    def less_equal(self, other: EffectState) -> bool:
        if other.unknown:
            return True
        return not self.unknown and self.effects <= other.effects

    def abstract_equal(self, other: EffectState) -> bool:
        return self == other

    def join(self, other: EffectState) -> EffectState:
        return EffectState(self.effects | other.effects, self.unknown or other.unknown)

    def meet(self, other: EffectState) -> EffectState:
        if self.unknown:
            return other
        if other.unknown:
            return self
        return EffectState(self.effects & other.effects)

    def widen(self, other: EffectState) -> EffectState:
        return self.join(other)

    def narrow(self, other: EffectState) -> EffectState:
        return other if self.unknown else self.meet(other)

    def add(self, kind: EffectKind, target: str) -> EffectState:
        return EffectState(self.effects | {EffectAtom(kind, target)}, self.unknown)

    def to_dict(self) -> dict[str, Any]:
        return {
            "effects": [effect.to_dict() for effect in sorted(self.effects)],
            "unknown": self.unknown,
        }


@dataclass(frozen=True, slots=True)
class ProductValue:
    """Minimal product domain used for Python expression values."""

    constant: ConstantValue = field(default_factory=ConstantValue.top)
    interval: IntervalValue = field(default_factory=IntervalValue.top)
    nullness: NullnessValue = field(default_factory=NullnessValue.top)
    exceptions: ExceptionState = field(default_factory=ExceptionState.bottom)
    effects: EffectState = field(default_factory=EffectState.bottom)

    @classmethod
    def bottom(cls) -> ProductValue:
        return cls(
            ConstantValue.bottom(),
            IntervalValue.bottom(),
            NullnessValue.bottom(),
            ExceptionState.bottom(),
            EffectState.bottom(),
        )

    @classmethod
    def top(cls) -> ProductValue:
        return cls(
            ConstantValue.top(),
            IntervalValue.top(),
            NullnessValue.top(),
            ExceptionState.top(),
            EffectState.top(),
        )

    @classmethod
    def unknown_scalar(cls) -> ProductValue:
        """Unknown scalar with no inferred exceptions or effects."""

        return cls()

    @classmethod
    def from_constant(cls, value: str | int | bool | None) -> ProductValue:
        interval = (
            IntervalValue.constant(value)
            if isinstance(value, int) and not isinstance(value, bool)
            else IntervalValue.bottom()
        )
        nullness = NullnessValue(
            NullnessKind.NULL if value is None else NullnessKind.NONNULL
        )
        return cls(ConstantValue.constant(value), interval, nullness)

    @classmethod
    def from_interval(cls, interval: IntervalValue) -> ProductValue:
        constant = (
            ConstantValue.constant(interval.lower)
            if not interval.empty
            and interval.lower is not None
            and interval.lower == interval.upper
            else ConstantValue.top()
        )
        nullness = NullnessValue.bottom() if interval.empty else NullnessValue(NullnessKind.NONNULL)
        return cls(constant, interval, nullness)

    def less_equal(self, other: ProductValue) -> bool:
        return (
            self.constant.less_equal(other.constant)
            and self.interval.less_equal(other.interval)
            and self.nullness.less_equal(other.nullness)
            and self.exceptions.less_equal(other.exceptions)
            and self.effects.less_equal(other.effects)
        )

    def abstract_equal(self, other: ProductValue) -> bool:
        return self.less_equal(other) and other.less_equal(self)

    def join(self, other: ProductValue) -> ProductValue:
        return ProductValue(
            self.constant.join(other.constant),
            self.interval.join(other.interval),
            self.nullness.join(other.nullness),
            self.exceptions.join(other.exceptions),
            self.effects.join(other.effects),
        )

    def meet(self, other: ProductValue) -> ProductValue:
        return ProductValue(
            self.constant.meet(other.constant),
            self.interval.meet(other.interval),
            self.nullness.meet(other.nullness),
            self.exceptions.meet(other.exceptions),
            self.effects.meet(other.effects),
        )

    def widen(self, other: ProductValue) -> ProductValue:
        return ProductValue(
            self.constant.widen(other.constant),
            self.interval.widen(other.interval),
            self.nullness.widen(other.nullness),
            self.exceptions.widen(other.exceptions),
            self.effects.widen(other.effects),
        )

    def narrow(self, other: ProductValue) -> ProductValue:
        return ProductValue(
            self.constant.narrow(other.constant),
            self.interval.narrow(other.interval),
            self.nullness.narrow(other.nullness),
            self.exceptions.narrow(other.exceptions),
            self.effects.narrow(other.effects),
        )

    def with_exception(self, exception: str) -> ProductValue:
        return ProductValue(
            self.constant,
            self.interval,
            self.nullness,
            self.exceptions.add(exception),
            self.effects,
        )

    def with_effect(self, kind: EffectKind, target: str) -> ProductValue:
        return ProductValue(
            self.constant,
            self.interval,
            self.nullness,
            self.exceptions,
            self.effects.add(kind, target),
        )

    def as_opaque(self) -> ProductValue:
        return ProductValue(
            ConstantValue.top(),
            IntervalValue.top(),
            NullnessValue.top(),
            self.exceptions.join(ExceptionState.top()),
            self.effects.join(EffectState.top()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "constant": self.constant.to_dict(),
            "effects": self.effects.to_dict(),
            "exceptions": self.exceptions.to_dict(),
            "interval": self.interval.to_dict(),
            "nullness": self.nullness.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class AbstractStore:
    """Immutable variable environment plus accumulated control-flow effects."""

    bindings: tuple[tuple[str, ProductValue], ...] = ()
    reachable: bool = True
    exceptions: ExceptionState = field(default_factory=ExceptionState.bottom)
    effects: EffectState = field(default_factory=EffectState.bottom)
    opaque_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        names = [name for name, _ in self.bindings]
        if len(names) != len(set(names)):
            raise AbstractInterpretationError("abstract-store bindings must be unique")
        normalized = tuple(sorted((_stable_text(name, "binding"), value) for name, value in self.bindings))
        object.__setattr__(self, "bindings", normalized)
        object.__setattr__(self, "opaque_reasons", tuple(sorted(set(self.opaque_reasons))))

    @classmethod
    def bottom(cls) -> AbstractStore:
        return cls(reachable=False)

    @classmethod
    def top(cls) -> AbstractStore:
        return cls(exceptions=ExceptionState.top(), effects=EffectState.top(), opaque_reasons=("top",))

    @property
    def values(self) -> Mapping[str, ProductValue]:
        return dict(self.bindings)

    def get(self, name: str) -> ProductValue:
        if not self.reachable:
            return ProductValue.bottom()
        return self.values.get(name, ProductValue.unknown_scalar().with_exception("NameError"))

    def set(self, name: str, value: ProductValue) -> AbstractStore:
        if not self.reachable:
            return self
        updated = dict(self.bindings)
        updated[_stable_text(name, "binding")] = ProductValue(
            value.constant,
            value.interval,
            value.nullness,
            ExceptionState.bottom(),
            EffectState.bottom(),
        )
        return AbstractStore(
            tuple(updated.items()),
            True,
            self.exceptions.join(value.exceptions),
            self.effects.join(value.effects).add(EffectKind.WRITE, name),
            self.opaque_reasons,
        )

    def refine(self, name: str, value: ProductValue) -> AbstractStore:
        """Replace one binding as a logical refinement, without a write effect."""

        if not self.reachable:
            return self
        updated = dict(self.bindings)
        updated[_stable_text(name, "binding")] = ProductValue(
            value.constant,
            value.interval,
            value.nullness,
            ExceptionState.bottom(),
            EffectState.bottom(),
        )
        return AbstractStore(
            tuple(updated.items()),
            True,
            self.exceptions,
            self.effects,
            self.opaque_reasons,
        )

    def observe(self, value: ProductValue) -> AbstractStore:
        if not self.reachable:
            return self
        return AbstractStore(
            self.bindings,
            True,
            self.exceptions.join(value.exceptions),
            self.effects.join(value.effects),
            self.opaque_reasons,
        )

    def terminate(self) -> AbstractStore:
        return AbstractStore(
            self.bindings,
            False,
            self.exceptions,
            self.effects,
            self.opaque_reasons,
        )

    def make_opaque(self, reason: str) -> AbstractStore:
        if not self.reachable:
            return self
        widened = tuple((name, value.as_opaque()) for name, value in self.bindings)
        return AbstractStore(
            widened,
            True,
            self.exceptions.join(ExceptionState.top()),
            self.effects.join(EffectState.top()),
            self.opaque_reasons + (_stable_text(reason, "opaque reason"),),
        )

    def less_equal(self, other: AbstractStore) -> bool:
        if not self.reachable:
            return True
        if not other.reachable:
            return False
        names = set(self.values) | set(other.values)
        missing = ProductValue.unknown_scalar().with_exception("UnboundLocalError")
        left = self.values
        right = other.values
        return (
            all(left.get(name, missing).less_equal(right.get(name, missing)) for name in names)
            and self.exceptions.less_equal(other.exceptions)
            and self.effects.less_equal(other.effects)
        )

    def abstract_equal(self, other: AbstractStore) -> bool:
        return self.less_equal(other) and other.less_equal(self)

    def join(self, other: AbstractStore) -> AbstractStore:
        if not self.reachable:
            return other
        if not other.reachable:
            return self
        names = set(self.values) | set(other.values)
        missing = ProductValue.unknown_scalar().with_exception("UnboundLocalError")
        left = self.values
        right = other.values
        return AbstractStore(
            tuple(
                (name, left.get(name, missing).join(right.get(name, missing)))
                for name in sorted(names)
            ),
            True,
            self.exceptions.join(other.exceptions),
            self.effects.join(other.effects),
            tuple(sorted(set(self.opaque_reasons) | set(other.opaque_reasons))),
        )

    def meet(self, other: AbstractStore) -> AbstractStore:
        if not self.reachable or not other.reachable:
            return self.bottom()
        names = set(self.values) | set(other.values)
        missing = ProductValue.unknown_scalar().with_exception("UnboundLocalError")
        left = self.values
        right = other.values
        return AbstractStore(
            tuple(
                (name, left.get(name, missing).meet(right.get(name, missing)))
                for name in sorted(names)
            ),
            True,
            self.exceptions.meet(other.exceptions),
            self.effects.meet(other.effects),
            tuple(sorted(set(self.opaque_reasons) & set(other.opaque_reasons))),
        )

    def widen(self, other: AbstractStore) -> AbstractStore:
        if not self.reachable:
            return other
        if not other.reachable:
            return self
        names = set(self.values) | set(other.values)
        missing = ProductValue.unknown_scalar().with_exception("UnboundLocalError")
        left = self.values
        right = other.values
        return AbstractStore(
            tuple(
                (name, left.get(name, missing).widen(right.get(name, missing)))
                for name in sorted(names)
            ),
            True,
            self.exceptions.widen(other.exceptions),
            self.effects.widen(other.effects),
            tuple(sorted(set(self.opaque_reasons) | set(other.opaque_reasons))),
        )

    def narrow(self, other: AbstractStore) -> AbstractStore:
        if not self.reachable or not other.reachable:
            return self.meet(other)
        names = set(self.values) | set(other.values)
        missing = ProductValue.unknown_scalar().with_exception("UnboundLocalError")
        left = self.values
        right = other.values
        return AbstractStore(
            tuple(
                (name, left.get(name, missing).narrow(right.get(name, missing)))
                for name in sorted(names)
            ),
            True,
            self.exceptions.narrow(other.exceptions),
            self.effects.narrow(other.effects),
            tuple(sorted(set(self.opaque_reasons) & set(other.opaque_reasons))),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bindings": {name: value.to_dict() for name, value in self.bindings},
            "effects": self.effects.to_dict(),
            "exceptions": self.exceptions.to_dict(),
            "opaque_reasons": list(self.opaque_reasons),
            "reachable": self.reachable,
        }


@dataclass(frozen=True, slots=True)
class FixpointResult:
    """Result of a bounded monotone worklist iteration."""

    states: tuple[tuple[str, AbstractStore], ...]
    iterations: int
    converged: bool
    widened_nodes: tuple[str, ...]
    narrowing_iterations: int

    @property
    def by_node(self) -> Mapping[str, AbstractStore]:
        return dict(self.states)


def solve_worklist_fixpoint(
    *,
    entry_node: str,
    initial_state: AbstractStore,
    successors: Mapping[str, Sequence[str]],
    transfer: Callable[[str, AbstractStore], AbstractStore],
    max_iterations: int = 128,
    widening_after: int = 3,
    narrowing_iterations: int = 1,
) -> FixpointResult:
    """Compute a bounded forward fixpoint over an explicit control-flow graph.

    ``transfer`` must be monotone.  Widening happens per destination after its
    configured update threshold.  If the main worklist converges, bounded
    narrowing recomputes predecessor contributions and can recover finite
    bounds lost to widening.
    """

    entry = _stable_text(entry_node, "entry node")
    if isinstance(max_iterations, bool) or max_iterations <= 0:
        raise AbstractInterpretationError("max_iterations must be positive")
    if isinstance(widening_after, bool) or widening_after < 0:
        raise AbstractInterpretationError("widening_after must be non-negative")
    if isinstance(narrowing_iterations, bool) or narrowing_iterations < 0:
        raise AbstractInterpretationError("narrowing_iterations must be non-negative")
    nodes = {entry} | set(successors)
    for source, targets in successors.items():
        _stable_text(source, "control-flow node")
        nodes.update(_stable_text(target, "control-flow successor") for target in targets)
    states = {node: AbstractStore.bottom() for node in nodes}
    states[entry] = initial_state
    queue: deque[str] = deque((entry,))
    queued = {entry}
    updates = {node: 0 for node in nodes}
    widened: set[str] = set()
    iterations = 0
    while queue and iterations < max_iterations:
        node = queue.popleft()
        queued.remove(node)
        iterations += 1
        output = transfer(node, states[node])
        if not isinstance(output, AbstractStore):
            raise AbstractInterpretationError("transfer must return AbstractStore")
        for target in successors.get(node, ()):
            current = states[target]
            joined = current.join(output)
            if joined.less_equal(current):
                continue
            updates[target] += 1
            if updates[target] > widening_after:
                joined = current.widen(joined)
                widened.add(target)
            states[target] = joined
            if target not in queued:
                queue.append(target)
                queued.add(target)
    converged = not queue

    actual_narrowing = 0
    if converged and narrowing_iterations:
        predecessors: dict[str, list[str]] = {node: [] for node in nodes}
        for source, targets in successors.items():
            for target in targets:
                predecessors[target].append(source)
        for _ in range(narrowing_iterations):
            changed = False
            for node in sorted(nodes):
                if node == entry or not predecessors[node]:
                    continue
                incoming = AbstractStore.bottom()
                for predecessor in predecessors[node]:
                    incoming = incoming.join(transfer(predecessor, states[predecessor]))
                candidate = states[node].narrow(incoming)
                if not candidate.abstract_equal(states[node]):
                    states[node] = candidate
                    changed = True
            actual_narrowing += 1
            if not changed:
                break
    return FixpointResult(
        tuple(sorted(states.items())),
        iterations,
        converged,
        tuple(sorted(widened)),
        actual_narrowing,
    )


@dataclass(frozen=True, slots=True)
class AnalysisConfig:
    """Deterministic budgets and sensitivity controls."""

    max_iterations: int = 64
    widening_after: int = 3
    narrowing_iterations: int = 1
    path_sensitive: bool = True
    context_sensitive: bool = True
    call_string_limit: int = 3

    def __post_init__(self) -> None:
        for name in ("max_iterations", "call_string_limit"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise AbstractInterpretationError(f"{name} must be a positive integer")
        for name in ("widening_after", "narrowing_iterations"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise AbstractInterpretationError(f"{name} must be a non-negative integer")
        if not isinstance(self.path_sensitive, bool) or not isinstance(self.context_sensitive, bool):
            raise AbstractInterpretationError("sensitivity controls must be boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_string_limit": self.call_string_limit,
            "context_sensitive": self.context_sensitive,
            "max_iterations": self.max_iterations,
            "narrowing_iterations": self.narrowing_iterations,
            "path_sensitive": self.path_sensitive,
            "widening_after": self.widening_after,
        }


@dataclass(frozen=True, slots=True)
class ProgramPointState:
    """Abstract state bound to an exact Python source coordinate."""

    line: int
    column: int
    node_kind: str
    state: AbstractStore

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "line": self.line,
            "node_kind": self.node_kind,
            "state": self.state.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class AbstractContractCandidate:
    """Candidate contract inferred from one function summary.

    The record is deliberately candidate-tier.  Consumers must compile and
    independently discharge it before it can become contract evidence.
    """

    function_name: str
    return_interval: IntervalValue
    return_nullness: NullnessValue
    possible_exceptions: ExceptionState
    effects: EffectState
    support: SoundnessClass

    def to_dict(self) -> dict[str, Any]:
        return {
            "effects": self.effects.to_dict(),
            "function_name": self.function_name,
            "possible_exceptions": self.possible_exceptions.to_dict(),
            "return_interval": self.return_interval.to_dict(),
            "return_nullness": self.return_nullness.to_dict(),
            "support": self.support.value,
        }


@dataclass(frozen=True, slots=True)
class FunctionSummary:
    """Interprocedural abstract summary for one local Python function."""

    function_name: str
    parameters: tuple[str, ...]
    entry_state: AbstractStore
    exit_state: AbstractStore
    return_value: ProductValue
    program_points: tuple[ProgramPointState, ...]
    unsupported_constructs: tuple[str, ...]
    iterations: int
    converged: bool
    assumptions: tuple[str, ...]
    generated_invariants: tuple[str, ...]
    contract_candidate: AbstractContractCandidate
    proof_obligations: tuple[str, ...]
    source_start_line: int
    source_end_line: int
    summary_id: str = ""

    def __post_init__(self) -> None:
        semantic = self.semantic_dict()
        expected = canonical_identity(
            semantic,
            domain=ABSTRACT_SUMMARY_IDENTITY_DOMAIN,
            schema_version=ABSTRACT_ANALYSIS_SCHEMA_VERSION,
        ).cid
        if self.summary_id and self.summary_id != expected:
            raise AbstractInterpretationError("function summary identity mismatch")
        object.__setattr__(self, "summary_id", expected)

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "assumptions": list(self.assumptions),
            "contract_candidate": self.contract_candidate.to_dict(),
            "converged": self.converged,
            "entry_state": self.entry_state.to_dict(),
            "exit_state": self.exit_state.to_dict(),
            "function_name": self.function_name,
            "generated_invariants": list(self.generated_invariants),
            "iterations": self.iterations,
            "parameters": list(self.parameters),
            "program_points": [point.to_dict() for point in self.program_points],
            "proof_obligations": list(self.proof_obligations),
            "return_value": self.return_value.to_dict(),
            "source_end_line": self.source_end_line,
            "source_start_line": self.source_start_line,
            "unsupported_constructs": list(self.unsupported_constructs),
        }

    def to_dict(self) -> dict[str, Any]:
        result = self.semantic_dict()
        result["summary_id"] = self.summary_id
        return result


@dataclass(frozen=True, slots=True)
class AbstractAnalysisResult:
    """Content-addressed analysis result for one exact source body."""

    source_uri: str
    source_identity: str
    analyzer_identity: str
    config: AnalysisConfig
    summaries: tuple[FunctionSummary, ...]
    unsupported_constructs: tuple[str, ...]
    supported_syntax: tuple[str, ...]
    soundness: SoundnessClass
    iterations: int
    converged: bool
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]
    analysis_id: str = ""
    schema_version: str = ABSTRACT_ANALYSIS_SCHEMA_VERSION

    INTERFACE: ClassVar[str] = ABSTRACT_ANALYSIS_INTERFACE

    def __post_init__(self) -> None:
        if self.schema_version != ABSTRACT_ANALYSIS_SCHEMA_VERSION:
            raise AbstractInterpretationError("unsupported abstract-analysis schema version")
        semantic = self.semantic_dict()
        expected = canonical_identity(
            semantic,
            domain=ABSTRACT_ANALYSIS_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        ).cid
        if self.analysis_id and self.analysis_id != expected:
            raise AbstractInterpretationError("abstract-analysis identity mismatch")
        object.__setattr__(self, "analysis_id", expected)

    @property
    def summaries_by_name(self) -> Mapping[str, FunctionSummary]:
        return {summary.function_name: summary for summary in self.summaries}

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "analyzer_identity": self.analyzer_identity,
            "assumptions": list(self.assumptions),
            "config": self.config.to_dict(),
            "converged": self.converged,
            "interface": ABSTRACT_ANALYSIS_INTERFACE,
            "iterations": self.iterations,
            "limitations": list(self.limitations),
            "schema_version": self.schema_version,
            "soundness": self.soundness.value,
            "source_identity": self.source_identity,
            "source_uri": self.source_uri,
            "summaries": [summary.to_dict() for summary in self.summaries],
            "supported_syntax": list(self.supported_syntax),
            "unsupported_constructs": list(self.unsupported_constructs),
        }

    def to_dict(self) -> dict[str, Any]:
        result = self.semantic_dict()
        result["analysis_id"] = self.analysis_id
        return result

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=ABSTRACT_ANALYSIS_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )


@dataclass(slots=True)
class _FunctionFrame:
    returns: ProductValue = field(default_factory=ProductValue.bottom)
    return_states: list[AbstractStore] = field(default_factory=list)
    points: list[ProgramPointState] = field(default_factory=list)
    unsupported: set[str] = field(default_factory=set)
    iterations: int = 0
    converged: bool = True
    invariants: set[str] = field(default_factory=set)


_SUPPORTED_SYNTAX: Final = (
    "arguments",
    "assert",
    "assignment",
    "boolean_operator",
    "breakless_while",
    "comparison",
    "conditional",
    "constant",
    "function_call_local",
    "function_definition",
    "integer_binary_operator",
    "name",
    "raise",
    "return",
    "static_import",
    "unary_operator",
)
_DYNAMIC_CALLS: Final = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "import_module",
        "reload",
    }
)
_NATIVE_MODULES: Final = frozenset({"ctypes", "cffi", "cython", "numpy.ctypeslib"})
_IO_CALLS: Final = frozenset({"open", "input", "print"})
_SUBPROCESS_CALLS: Final = frozenset({"system", "popen", "run", "call", "check_call", "check_output"})
_NETWORK_CALLS: Final = frozenset({"urlopen", "request", "connect", "send", "recv"})


class PythonAbstractInterpreter:
    """Bounded interprocedural analyzer for a conservative Python subset."""

    INTERFACE: ClassVar[str] = PYTHON_ANALYZER_INTERFACE

    def __init__(self, config: AnalysisConfig | None = None) -> None:
        self.config = config or AnalysisConfig()
        self._functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        self._context_cache: dict[tuple[str, tuple[bytes, ...]], FunctionSummary] = {}
        self._global_unsupported: set[str] = set()

    @property
    def analyzer_identity(self) -> str:
        return canonical_identity(
            {
                "config": self.config.to_dict(),
                "interface": self.INTERFACE,
                "supported_syntax": list(_SUPPORTED_SYNTAX),
                "version": PYTHON_ANALYZER_VERSION,
            },
            domain=ABSTRACT_ANALYZER_IDENTITY_DOMAIN,
            schema_version=ABSTRACT_ANALYSIS_SCHEMA_VERSION,
        ).cid

    def analyze(self, source: str, *, source_uri: str = "memory://python-source") -> AbstractAnalysisResult:
        if not isinstance(source, str):
            raise AbstractInterpretationError("source must be text")
        uri = _stable_text(source_uri, "source_uri")
        try:
            tree = ast.parse(source, filename=uri)
        except (SyntaxError, ValueError) as error:
            raise AbstractInterpretationError(f"cannot parse Python source: {error}") from error
        self._functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self._context_cache.clear()
        self._global_unsupported.clear()
        self._inspect_module_frontier(tree)

        summaries: list[FunctionSummary] = []
        for name in sorted(self._functions):
            function = self._functions[name]
            arguments = tuple(
                self._value_for_annotation(argument.annotation)
                for argument in _positional_parameters(function)
            )
            summaries.append(self._interpret_function(function, arguments, ()))
        unsupported = set(self._global_unsupported)
        for summary in summaries:
            unsupported.update(summary.unsupported_constructs)
        converged = all(summary.converged for summary in summaries)
        soundness = (
            SoundnessClass.OPAQUE
            if unsupported or any(summary.exit_state.opaque_reasons for summary in summaries)
            else SoundnessClass.CONSERVATIVE
        )
        source_identity = canonical_identity(
            {"encoding": "utf-8", "source": source, "source_uri": uri},
            domain=ABSTRACT_SOURCE_IDENTITY_DOMAIN,
            schema_version=ABSTRACT_ANALYSIS_SCHEMA_VERSION,
        ).cid
        return AbstractAnalysisResult(
            source_uri=uri,
            source_identity=source_identity,
            analyzer_identity=self.analyzer_identity,
            config=self.config,
            summaries=tuple(summaries),
            unsupported_constructs=tuple(sorted(unsupported)),
            supported_syntax=_SUPPORTED_SYNTAX,
            soundness=soundness,
            iterations=sum(summary.iterations for summary in summaries),
            converged=converged,
            assumptions=(
                "Python integer arithmetic is modeled as mathematical unbounded integers.",
                "Only local functions in the exact analyzed source are summarized interprocedurally.",
            ),
            limitations=(
                "Aliases, descriptors, metaclasses, native extensions, and opaque callbacks widen state.",
                "The analysis is a conservative abstract interpretation, not kernel-checked proof evidence.",
                "Loop control with break, continue, or try/finally is outside the initial subset.",
            ),
        )

    def _inspect_module_frontier(self, tree: ast.Module) -> None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.decorator_list:
                self._record_global(node, "decorated_function")
            elif isinstance(node, ast.ClassDef):
                if node.keywords:
                    self._record_global(node, "metaclass_or_dynamic_class")
                if node.decorator_list:
                    self._record_global(node, "decorated_class")
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.decorator_list:
                        self._record_global(item, "descriptor_or_decorated_method")
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                module_names = (
                    [alias.name for alias in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                )
                if any(name.split(".")[0] in _NATIVE_MODULES for name in module_names):
                    self._record_global(node, "native_extension_import")

    def _record_global(self, node: ast.AST, kind: str) -> None:
        self._global_unsupported.add(_construct_id(node, kind))

    def _value_for_annotation(self, annotation: ast.expr | None) -> ProductValue:
        if isinstance(annotation, ast.Name) and annotation.id == "int":
            return ProductValue.from_interval(IntervalValue.top())
        if isinstance(annotation, ast.Name) and annotation.id in {"str", "bool", "bytes"}:
            return ProductValue(
                ConstantValue.top(),
                IntervalValue.bottom(),
                NullnessValue(NullnessKind.NONNULL),
            )
        return ProductValue.unknown_scalar()

    def _interpret_function(
        self,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        arguments: tuple[ProductValue, ...],
        call_stack: tuple[str, ...],
    ) -> FunctionSummary:
        parameters = tuple(argument.arg for argument in _positional_parameters(function))
        normalized_arguments = arguments + tuple(
            ProductValue.unknown_scalar() for _ in range(max(0, len(parameters) - len(arguments)))
        )
        cache_key = (
            function.name,
            tuple(canonical_json_bytes(value.to_dict()) for value in normalized_arguments[: len(parameters)]),
        )
        if self.config.context_sensitive and cache_key in self._context_cache:
            return self._context_cache[cache_key]
        frame = _FunctionFrame()
        bindings = tuple(zip(parameters, normalized_arguments, strict=False))
        entry = AbstractStore(bindings)
        if isinstance(function, ast.AsyncFunctionDef):
            frame.unsupported.add(_construct_id(function, "async_function"))
            entry = entry.make_opaque("async_function")
        if function.decorator_list:
            frame.unsupported.add(_construct_id(function, "decorated_function"))
            entry = entry.make_opaque("decorated_function")
        if function.args.vararg or function.args.kwarg or function.args.kwonlyargs:
            frame.unsupported.add(_construct_id(function, "variadic_or_keyword_only_parameters"))
            entry = entry.make_opaque("variadic_or_keyword_only_parameters")
        exit_state = self._execute_block(function.body, entry, frame, call_stack + (function.name,))
        if not frame.return_states and exit_state.reachable:
            frame.returns = frame.returns.join(ProductValue.from_constant(None))
            frame.return_states.append(exit_state)
        merged_exit = AbstractStore.bottom()
        for state in frame.return_states:
            merged_exit = merged_exit.join(state)
        if exit_state.reachable:
            merged_exit = merged_exit.join(exit_state)
        if not merged_exit.reachable:
            merged_exit = exit_state
        support = SoundnessClass.OPAQUE if frame.unsupported or merged_exit.opaque_reasons else SoundnessClass.CONSERVATIVE
        candidate = AbstractContractCandidate(
            function.name,
            frame.returns.interval,
            frame.returns.nullness,
            merged_exit.exceptions.join(frame.returns.exceptions),
            merged_exit.effects.join(frame.returns.effects),
            support,
        )
        obligations: list[str] = []
        if frame.unsupported:
            obligations.append("review_dynamic_or_unsupported_frontier")
        if not frame.converged:
            obligations.append("reanalyze_with_larger_fixpoint_budget_or_review")
        summary = FunctionSummary(
            function_name=function.name,
            parameters=parameters,
            entry_state=entry,
            exit_state=merged_exit,
            return_value=frame.returns,
            program_points=tuple(frame.points),
            unsupported_constructs=tuple(sorted(frame.unsupported)),
            iterations=frame.iterations,
            converged=frame.converged,
            assumptions=("unbounded_integer_arithmetic",),
            generated_invariants=tuple(sorted(frame.invariants)),
            contract_candidate=candidate,
            proof_obligations=tuple(obligations),
            source_start_line=function.lineno,
            source_end_line=getattr(function, "end_lineno", function.lineno),
        )
        if self.config.context_sensitive:
            self._context_cache[cache_key] = summary
        return summary

    def _execute_block(
        self,
        statements: Sequence[ast.stmt],
        state: AbstractStore,
        frame: _FunctionFrame,
        call_stack: tuple[str, ...],
    ) -> AbstractStore:
        current = state
        for statement in statements:
            if not current.reachable:
                frame.points.append(_point(statement, current))
                continue
            frame.points.append(_point(statement, current))
            current = self._execute_statement(statement, current, frame, call_stack)
        return current

    def _execute_statement(
        self,
        statement: ast.stmt,
        state: AbstractStore,
        frame: _FunctionFrame,
        call_stack: tuple[str, ...],
    ) -> AbstractStore:
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            expression = statement.value
            if expression is None:
                return state
            value = self._evaluate(expression, state, frame, call_stack)
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            updated = state.observe(value)
            for target in targets:
                if isinstance(target, ast.Name):
                    updated = updated.set(target.id, value)
                else:
                    return self._opaque_statement(statement, updated, frame, "aliasing_assignment")
            return updated
        if isinstance(statement, ast.AugAssign) and isinstance(statement.target, ast.Name):
            left = state.get(statement.target.id).with_effect(EffectKind.READ, statement.target.id)
            right = self._evaluate(statement.value, state, frame, call_stack)
            value = self._binary_value(statement.op, left, right, statement, frame)
            return state.observe(value).set(statement.target.id, value)
        if isinstance(statement, ast.Return):
            value = (
                ProductValue.from_constant(None)
                if statement.value is None
                else self._evaluate(statement.value, state, frame, call_stack)
            )
            observed = state.observe(value)
            frame.returns = frame.returns.join(value)
            frame.return_states.append(observed)
            return observed.terminate()
        if isinstance(statement, ast.Raise):
            exception = _raised_exception_name(statement.exc)
            value = ProductValue.bottom().with_exception(exception)
            observed = state.observe(value)
            frame.return_states.append(observed)
            return observed.terminate()
        if isinstance(statement, ast.Expr):
            return state.observe(self._evaluate(statement.value, state, frame, call_stack))
        if isinstance(statement, ast.Assert):
            condition = self._evaluate(statement.test, state, frame, call_stack)
            observed = state.observe(condition)
            truth = _constant_truth(condition)
            if truth is False:
                observed = observed.observe(ProductValue.bottom().with_exception("AssertionError"))
                frame.return_states.append(observed)
                return observed.terminate()
            if truth is None:
                observed = observed.observe(ProductValue.bottom().with_exception("AssertionError"))
                return self._refine_condition(statement.test, observed, truth=True)
            return observed
        if isinstance(statement, ast.If):
            condition = self._evaluate(statement.test, state, frame, call_stack)
            observed = state.observe(condition)
            truth = _constant_truth(condition)
            if truth is True:
                return self._execute_block(statement.body, observed, frame, call_stack)
            if truth is False:
                return self._execute_block(statement.orelse, observed, frame, call_stack)
            then_state = self._execute_block(
                statement.body,
                self._refine_condition(statement.test, observed, truth=True),
                frame,
                call_stack,
            )
            else_state = self._execute_block(
                statement.orelse,
                self._refine_condition(statement.test, observed, truth=False),
                frame,
                call_stack,
            )
            return then_state.join(else_state)
        if isinstance(statement, ast.While):
            return self._execute_while(statement, state, frame, call_stack)
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            names = (
                [alias.name for alias in statement.names]
                if isinstance(statement, ast.Import)
                else [statement.module or "relative"]
            )
            updated = state
            for name in names:
                updated = updated.observe(
                    ProductValue.unknown_scalar().with_effect(EffectKind.IMPORT, name)
                )
            if any(name.split(".")[0] in _NATIVE_MODULES for name in names):
                return self._opaque_statement(statement, updated, frame, "native_extension_import")
            return updated
        if isinstance(statement, ast.Pass):
            return state
        return self._opaque_statement(statement, state, frame, f"unsupported_{type(statement).__name__}")

    def _execute_while(
        self,
        statement: ast.While,
        state: AbstractStore,
        frame: _FunctionFrame,
        call_stack: tuple[str, ...],
    ) -> AbstractStore:
        if any(isinstance(node, (ast.Break, ast.Continue, ast.Try)) for node in ast.walk(statement)):
            return self._opaque_statement(statement, state, frame, "unsupported_loop_control")
        head = state
        converged = False
        for iteration in range(1, self.config.max_iterations + 1):
            frame.iterations += 1
            condition = self._evaluate(statement.test, head, frame, call_stack)
            truth = _constant_truth(condition)
            if truth is False:
                converged = True
                break
            body_entry = self._refine_condition(statement.test, head.observe(condition), truth=True)
            body_exit = self._execute_block(statement.body, body_entry, frame, call_stack)
            joined = state.join(body_exit)
            candidate = head.widen(joined) if iteration > self.config.widening_after else head.join(joined)
            if candidate.less_equal(head):
                converged = True
                break
            head = candidate
        if not converged:
            frame.converged = False
            head = head.make_opaque("fixpoint_budget_exhausted")
        else:
            for _ in range(self.config.narrowing_iterations):
                condition = self._evaluate(statement.test, head, frame, call_stack)
                body_entry = self._refine_condition(statement.test, head.observe(condition), truth=True)
                body_exit = self._execute_block(statement.body, body_entry, frame, call_stack)
                candidate = head.narrow(state.join(body_exit))
                if candidate.abstract_equal(head):
                    break
                head = candidate
        condition = self._evaluate(statement.test, head, frame, call_stack)
        exit_state = self._refine_condition(statement.test, head.observe(condition), truth=False)
        frame.invariants.update(_store_interval_invariants(head))
        if statement.orelse:
            exit_state = self._execute_block(statement.orelse, exit_state, frame, call_stack)
        return exit_state

    def _evaluate(
        self,
        expression: ast.expr,
        state: AbstractStore,
        frame: _FunctionFrame,
        call_stack: tuple[str, ...],
    ) -> ProductValue:
        if isinstance(expression, ast.Constant):
            if isinstance(expression.value, _CONSTANT_TYPES):
                return ProductValue.from_constant(expression.value)
            return self._opaque_expression(expression, frame, "unsupported_constant")
        if isinstance(expression, ast.Name):
            return state.get(expression.id).with_effect(EffectKind.READ, expression.id)
        if isinstance(expression, ast.BinOp):
            left = self._evaluate(expression.left, state, frame, call_stack)
            right = self._evaluate(expression.right, state, frame, call_stack)
            return self._binary_value(expression.op, left, right, expression, frame)
        if isinstance(expression, ast.UnaryOp):
            operand = self._evaluate(expression.operand, state, frame, call_stack)
            if isinstance(expression.op, ast.USub):
                if operand.constant.kind is ConstantKind.VALUE and isinstance(operand.constant.value, int):
                    return _merge_flow(ProductValue.from_constant(-operand.constant.value), operand)
                interval = operand.interval
                negated = (
                    IntervalValue(
                        None if interval.upper is None else -interval.upper,
                        None if interval.lower is None else -interval.lower,
                    )
                    if not interval.empty
                    else interval
                )
                return _merge_flow(ProductValue.from_interval(negated), operand)
            if isinstance(expression.op, ast.UAdd):
                return operand
            if isinstance(expression.op, ast.Not):
                truth = _constant_truth(operand)
                value = ProductValue.from_constant(not truth) if truth is not None else ProductValue(
                    ConstantValue.top(), IntervalValue.bottom(), NullnessValue(NullnessKind.NONNULL)
                )
                return _merge_flow(value, operand)
            return self._opaque_expression(expression, frame, "unsupported_unary_operator", operand)
        if isinstance(expression, ast.Compare):
            values = [self._evaluate(expression.left, state, frame, call_stack)]
            values.extend(self._evaluate(item, state, frame, call_stack) for item in expression.comparators)
            result: bool | None = True
            for left, operator, right in zip(
                values[:-1], expression.ops, values[1:], strict=True
            ):
                comparison = _compare_values(left, operator, right)
                if comparison is False:
                    result = False
                    break
                if comparison is None:
                    result = None
            boolean = (
                ProductValue.from_constant(result)
                if result is not None
                else ProductValue(ConstantValue.top(), IntervalValue.bottom(), NullnessValue(NullnessKind.NONNULL))
            )
            return _merge_many_flow(boolean, values)
        if isinstance(expression, ast.BoolOp):
            values = [self._evaluate(item, state, frame, call_stack) for item in expression.values]
            truths = [_constant_truth(value) for value in values]
            boolean_result: bool | None
            if isinstance(expression.op, ast.And):
                boolean_result = False if False in truths else True if all(item is True for item in truths) else None
            else:
                boolean_result = True if True in truths else False if all(item is False for item in truths) else None
            boolean = (
                ProductValue.from_constant(boolean_result)
                if boolean_result is not None
                else ProductValue(ConstantValue.top(), IntervalValue.bottom(), NullnessValue(NullnessKind.NONNULL))
            )
            return _merge_many_flow(boolean, values)
        if isinstance(expression, ast.IfExp):
            condition = self._evaluate(expression.test, state, frame, call_stack)
            truth = _constant_truth(condition)
            if truth is True:
                return _merge_flow(self._evaluate(expression.body, state, frame, call_stack), condition)
            if truth is False:
                return _merge_flow(self._evaluate(expression.orelse, state, frame, call_stack), condition)
            left = self._evaluate(expression.body, state, frame, call_stack)
            right = self._evaluate(expression.orelse, state, frame, call_stack)
            return _merge_flow(left.join(right), condition)
        if isinstance(expression, ast.Call):
            return self._evaluate_call(expression, state, frame, call_stack)
        if isinstance(expression, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
            children = [self._evaluate(item, state, frame, call_stack) for item in _container_values(expression)]
            value = ProductValue(
                ConstantValue.top(), IntervalValue.bottom(), NullnessValue(NullnessKind.NONNULL)
            ).with_effect(EffectKind.ALLOCATION, type(expression).__name__.lower())
            return _merge_many_flow(value, children)
        return self._opaque_expression(expression, frame, f"unsupported_{type(expression).__name__}")

    def _evaluate_call(
        self,
        expression: ast.Call,
        state: AbstractStore,
        frame: _FunctionFrame,
        call_stack: tuple[str, ...],
    ) -> ProductValue:
        arguments = tuple(self._evaluate(argument, state, frame, call_stack) for argument in expression.args)
        keyword_values = tuple(
            self._evaluate(keyword.value, state, frame, call_stack)
            for keyword in expression.keywords
        )
        name = _call_name(expression.func)
        flow = _merge_many_flow(ProductValue.unknown_scalar(), arguments + keyword_values)
        if expression.keywords:
            return self._opaque_expression(expression, frame, "keyword_or_unpack_call", flow)
        if name in _DYNAMIC_CALLS or name.rsplit(".", 1)[-1] in _DYNAMIC_CALLS:
            return self._opaque_expression(expression, frame, f"dynamic_call:{name}", flow)
        if name in _IO_CALLS:
            effects = flow.effects.add(EffectKind.IO, name)
            if name == "open":
                effects = effects.add(EffectKind.FILESYSTEM, "open")
            io_value = ProductValue(
                ConstantValue.top(), IntervalValue.top(), NullnessValue.top(),
                flow.exceptions.join(ExceptionState(frozenset({"OSError"}))), effects,
            )
            return self._opaque_expression(
                expression, frame, f"uncontrolled_io:{name}", io_value
            )
        short_name = name.rsplit(".", 1)[-1]
        if short_name in _SUBPROCESS_CALLS:
            return self._opaque_expression(
                expression,
                frame,
                f"uncontrolled_subprocess:{name}",
                flow.with_effect(EffectKind.SUBPROCESS, name),
            )
        if short_name in _NETWORK_CALLS:
            return self._opaque_expression(
                expression,
                frame,
                f"uncontrolled_network:{name}",
                flow.with_effect(EffectKind.NETWORK, name),
            )
        if name in self._functions:
            if name in call_stack or len(call_stack) >= self.config.call_string_limit:
                return self._opaque_expression(expression, frame, f"recursive_or_deep_call:{name}", flow)
            target = self._functions[name]
            positional = _positional_parameters(target)
            required = len(positional) - len(target.args.defaults)
            if len(arguments) < required or (
                target.args.vararg is None and len(arguments) > len(positional)
            ):
                return _merge_flow(
                    ProductValue.unknown_scalar().with_exception("TypeError"), flow
                )
            summary_arguments = arguments
            if not self.config.context_sensitive:
                summary_arguments = tuple(
                    self._value_for_annotation(parameter.annotation)
                    for parameter in positional
                )
            summary = self._interpret_function(target, summary_arguments, call_stack)
            result = ProductValue(
                summary.return_value.constant,
                summary.return_value.interval,
                summary.return_value.nullness,
                summary.return_value.exceptions.join(summary.exit_state.exceptions),
                summary.return_value.effects.join(summary.exit_state.effects).add(EffectKind.CALL, name),
            )
            return _merge_flow(result, flow)
        if name in {"abs", "min", "max", "len", "bool", "int", "str"}:
            return self._evaluate_builtin(name, arguments, expression, frame, flow)
        return self._opaque_expression(expression, frame, f"opaque_callback:{name or 'callable'}", flow)

    def _evaluate_builtin(
        self,
        name: str,
        arguments: tuple[ProductValue, ...],
        expression: ast.Call,
        frame: _FunctionFrame,
        flow: ProductValue,
    ) -> ProductValue:
        if name == "abs" and len(arguments) == 1:
            interval = arguments[0].interval
            if interval.empty:
                value = ProductValue.bottom()
            elif interval.lower is not None and interval.lower >= 0:
                value = ProductValue.from_interval(interval)
            elif interval.upper is not None and interval.upper <= 0:
                value = ProductValue.from_interval(IntervalValue(-interval.upper, None if interval.lower is None else -interval.lower))
            elif interval.lower is not None and interval.upper is not None:
                value = ProductValue.from_interval(IntervalValue(0, max(-interval.lower, interval.upper)))
            else:
                value = ProductValue.from_interval(IntervalValue(0, None))
            return _merge_flow(value, flow)
        if name in {"min", "max"} and arguments:
            constants = [item.constant.value for item in arguments]
            if all(isinstance(item, int) and not isinstance(item, bool) for item in constants):
                integer_constants = [item for item in constants if isinstance(item, int)]
                minmax_value = (
                    min(integer_constants) if name == "min" else max(integer_constants)
                )
                return _merge_flow(ProductValue.from_constant(minmax_value), flow)
            return _merge_flow(ProductValue.from_interval(IntervalValue.top()), flow)
        if name == "bool" and len(arguments) <= 1:
            truth = False if not arguments else _constant_truth(arguments[0])
            value = ProductValue.from_constant(truth) if truth is not None else ProductValue(
                ConstantValue.top(), IntervalValue.bottom(), NullnessValue(NullnessKind.NONNULL)
            )
            return _merge_flow(value, flow)
        if name == "int":
            return _merge_flow(ProductValue.from_interval(IntervalValue.top()).with_exception("ValueError"), flow)
        if name == "str":
            return _merge_flow(ProductValue(ConstantValue.top(), IntervalValue.bottom(), NullnessValue(NullnessKind.NONNULL)), flow)
        if name == "len":
            return _merge_flow(ProductValue.from_interval(IntervalValue(0, None)).with_exception("TypeError"), flow)
        return self._opaque_expression(expression, frame, f"unsupported_builtin:{name}", flow)

    def _binary_value(
        self,
        operator: ast.operator,
        left: ProductValue,
        right: ProductValue,
        node: ast.AST,
        frame: _FunctionFrame,
    ) -> ProductValue:
        exceptions = left.exceptions.join(right.exceptions)
        effects = left.effects.join(right.effects)
        constant: int | str | None = None
        known = (
            left.constant.kind is ConstantKind.VALUE
            and right.constant.kind is ConstantKind.VALUE
        )
        try:
            if known and isinstance(operator, ast.Add):
                constant = left.constant.value + right.constant.value  # type: ignore[operator]
            elif known and isinstance(operator, ast.Sub):
                constant = left.constant.value - right.constant.value  # type: ignore[operator]
            elif known and isinstance(operator, ast.Mult):
                constant = left.constant.value * right.constant.value  # type: ignore[operator]
            elif known and isinstance(operator, ast.FloorDiv):
                constant = left.constant.value // right.constant.value  # type: ignore[operator]
            elif known and isinstance(operator, ast.Mod):
                constant = left.constant.value % right.constant.value  # type: ignore[operator]
        except (TypeError, ZeroDivisionError):
            constant = None
        if constant is not None and isinstance(constant, _CONSTANT_TYPES):
            return ProductValue.from_constant(constant).join(
                ProductValue(
                    ConstantValue.bottom(), IntervalValue.bottom(), NullnessValue.bottom(), exceptions, effects
                )
            )
        if isinstance(operator, ast.Add):
            interval = left.interval.add(right.interval)
        elif isinstance(operator, ast.Sub):
            interval = left.interval.subtract(right.interval)
        elif isinstance(operator, ast.Mult):
            interval = left.interval.multiply(right.interval)
        elif isinstance(operator, (ast.FloorDiv, ast.Mod)):
            if right.interval.contains(0):
                exceptions = exceptions.add("ZeroDivisionError")
            interval = IntervalValue.top()
        else:
            return self._opaque_expression(node, frame, f"unsupported_binary_{type(operator).__name__}", _merge_flow(left, right))
        return ProductValue(ConstantValue.top(), interval, NullnessValue(NullnessKind.NONNULL), exceptions, effects)

    def _refine_condition(self, expression: ast.expr, state: AbstractStore, *, truth: bool) -> AbstractStore:
        if not self.config.path_sensitive or not state.reachable:
            return state
        if isinstance(expression, ast.Constant):
            if bool(expression.value) != truth:
                return state.terminate()
            return state
        if isinstance(expression, ast.Compare) and len(expression.ops) == len(expression.comparators) == 1:
            left = expression.left
            right = expression.comparators[0]
            operator = expression.ops[0]
            if isinstance(left, ast.Name) and isinstance(right, ast.Constant):
                value = right.value
                if value is None and isinstance(operator, (ast.Is, ast.IsNot, ast.Eq, ast.NotEq)):
                    target_null = truth == isinstance(operator, (ast.Is, ast.Eq))
                    refinement = NullnessValue(NullnessKind.NULL if target_null else NullnessKind.NONNULL)
                    current = state.get(left.id)
                    return state.refine(left.id, ProductValue(
                        current.constant,
                        current.interval,
                        current.nullness.meet(refinement),
                        current.exceptions,
                        current.effects,
                    ))
                if isinstance(value, int) and not isinstance(value, bool):
                    interval = _comparison_interval(operator, value, truth)
                    current = state.get(left.id)
                    refined = current.interval.meet(interval)
                    if refined.empty:
                        return state.terminate()
                    return state.refine(left.id, ProductValue.from_interval(refined))
        return state

    def _opaque_expression(
        self,
        node: ast.AST,
        frame: _FunctionFrame,
        reason: str,
        flow: ProductValue | None = None,
    ) -> ProductValue:
        frame.unsupported.add(_construct_id(node, reason))
        base = flow or ProductValue.unknown_scalar()
        return base.as_opaque()

    def _opaque_statement(
        self,
        node: ast.AST,
        state: AbstractStore,
        frame: _FunctionFrame,
        reason: str,
    ) -> AbstractStore:
        frame.unsupported.add(_construct_id(node, reason))
        return state.make_opaque(reason)


def analyze_abstract_state(
    source: str,
    *,
    source_uri: str = "memory://python-source",
    language: str = "python",
    config: AnalysisConfig | None = None,
) -> AbstractAnalysisResult:
    """Analyze one source body through the registered initial Python adapter."""

    if language != "python":
        raise AbstractInterpretationError("only the Python adapter is available")
    return PythonAbstractInterpreter(config).analyze(source, source_uri=source_uri)


def _stable_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or "\x00" in value:
        raise AbstractInterpretationError(f"{label} must be non-empty trimmed text without NUL")
    return value


def _point(node: ast.AST, state: AbstractStore) -> ProgramPointState:
    return ProgramPointState(
        getattr(node, "lineno", 0),
        getattr(node, "col_offset", 0),
        type(node).__name__,
        state,
    )


def _construct_id(node: ast.AST, kind: str) -> str:
    return f"{kind}@{getattr(node, 'lineno', 0)}:{getattr(node, 'col_offset', 0)}"


def _call_name(expression: ast.expr) -> str:
    if isinstance(expression, ast.Name):
        return expression.id
    if isinstance(expression, ast.Attribute):
        prefix = _call_name(expression.value)
        return f"{prefix}.{expression.attr}" if prefix else expression.attr
    return ""


def _positional_parameters(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[ast.arg, ...]:
    return tuple(function.args.posonlyargs) + tuple(function.args.args)


def _raised_exception_name(expression: ast.expr | None) -> str:
    if expression is None:
        return "ReraisedException"
    if isinstance(expression, ast.Call):
        return _call_name(expression.func) or "BaseException"
    if isinstance(expression, ast.Name):
        return expression.id
    return "BaseException"


def _container_values(expression: ast.List | ast.Tuple | ast.Set | ast.Dict) -> list[ast.expr]:
    if isinstance(expression, ast.Dict):
        return [item for item in (*expression.keys, *expression.values) if item is not None]
    return list(expression.elts)


def _merge_flow(value: ProductValue, flow: ProductValue) -> ProductValue:
    return ProductValue(
        value.constant,
        value.interval,
        value.nullness,
        value.exceptions.join(flow.exceptions),
        value.effects.join(flow.effects),
    )


def _merge_many_flow(value: ProductValue, flows: Sequence[ProductValue]) -> ProductValue:
    result = value
    for flow in flows:
        result = _merge_flow(result, flow)
    return result


def _constant_truth(value: ProductValue) -> bool | None:
    if value.constant.kind is ConstantKind.VALUE:
        return bool(value.constant.value)
    if value.interval.empty:
        return None
    if value.interval.excludes(0):
        return True
    if value.interval.lower == value.interval.upper == 0:
        return False
    if value.nullness.kind is NullnessKind.NULL:
        return False
    return None


def _compare_values(left: ProductValue, operator: ast.cmpop, right: ProductValue) -> bool | None:
    if left.constant.kind is ConstantKind.VALUE and right.constant.kind is ConstantKind.VALUE:
        lhs = left.constant.value
        rhs = right.constant.value
        try:
            if isinstance(operator, (ast.Eq, ast.Is)):
                return lhs == rhs
            if isinstance(operator, (ast.NotEq, ast.IsNot)):
                return lhs != rhs
            if isinstance(operator, ast.Lt):
                return lhs < rhs  # type: ignore[operator]
            if isinstance(operator, ast.LtE):
                return lhs <= rhs  # type: ignore[operator]
            if isinstance(operator, ast.Gt):
                return lhs > rhs  # type: ignore[operator]
            if isinstance(operator, ast.GtE):
                return lhs >= rhs  # type: ignore[operator]
        except TypeError:
            return None
    left_interval = left.interval
    right_interval = right.interval
    if left_interval.empty or right_interval.empty:
        return None
    if isinstance(operator, ast.Lt):
        if left_interval.upper is not None and right_interval.lower is not None and left_interval.upper < right_interval.lower:
            return True
        if left_interval.lower is not None and right_interval.upper is not None and left_interval.lower >= right_interval.upper:
            return False
    if isinstance(operator, ast.LtE):
        if left_interval.upper is not None and right_interval.lower is not None and left_interval.upper <= right_interval.lower:
            return True
        if left_interval.lower is not None and right_interval.upper is not None and left_interval.lower > right_interval.upper:
            return False
    if isinstance(operator, ast.Gt):
        return _compare_values(right, ast.Lt(), left)
    if isinstance(operator, ast.GtE):
        return _compare_values(right, ast.LtE(), left)
    return None


def _comparison_interval(operator: ast.cmpop, constant: int, truth: bool) -> IntervalValue:
    if isinstance(operator, ast.Lt):
        return IntervalValue(None, constant - 1) if truth else IntervalValue(constant, None)
    if isinstance(operator, ast.LtE):
        return IntervalValue(None, constant) if truth else IntervalValue(constant + 1, None)
    if isinstance(operator, ast.Gt):
        return IntervalValue(constant + 1, None) if truth else IntervalValue(None, constant)
    if isinstance(operator, ast.GtE):
        return IntervalValue(constant, None) if truth else IntervalValue(None, constant - 1)
    if isinstance(operator, (ast.Eq, ast.Is)) and truth:
        return IntervalValue.constant(constant)
    if isinstance(operator, (ast.NotEq, ast.IsNot)) and not truth:
        return IntervalValue.constant(constant)
    return IntervalValue.top()


def _store_interval_invariants(state: AbstractStore) -> set[str]:
    invariants: set[str] = set()
    for name, value in state.bindings:
        interval = value.interval
        if interval.empty:
            continue
        if interval.lower is not None:
            invariants.add(f"{name} >= {interval.lower}")
        if interval.upper is not None:
            invariants.add(f"{name} <= {interval.upper}")
    return invariants


__all__ = [
    "ABSTRACT_ANALYSIS_INTERFACE",
    "ABSTRACT_ANALYSIS_SCHEMA_VERSION",
    "PYTHON_ANALYZER_INTERFACE",
    "AbstractAnalysisResult",
    "AbstractContractCandidate",
    "AbstractDomain",
    "AbstractInterpretationError",
    "AbstractStore",
    "AnalysisConfig",
    "ConstantKind",
    "ConstantValue",
    "EffectAtom",
    "EffectKind",
    "EffectState",
    "ExceptionState",
    "FixpointResult",
    "FunctionSummary",
    "IntervalValue",
    "NullnessKind",
    "NullnessValue",
    "ProductValue",
    "ProgramPointState",
    "PythonAbstractInterpreter",
    "SoundnessClass",
    "analyze_abstract_state",
    "solve_worklist_fixpoint",
]
