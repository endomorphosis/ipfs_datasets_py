"""Compositional semantic profiles and family-extension contracts.

``SemanticProfile@1`` makes consequence, world policy, bounds, traces, time,
frames, norms, attacker, hypertrace, SMT theory, and kernel environment
explicit.  ``FamilyComposition@1`` records versioned composition of canonical
family identities without silently replacing those identities.

Profiles fail closed: contradictory or incomplete semantic choices raise
:class:`SemanticProfileError`.  Canonical ``tdfol`` and ``dcec`` IDs are
retained and always carry mandatory composition metadata.  Temporal-FOL is
expressed as a declared composition of ``temporal`` and ``first_order``, not as
an opaque replacement family string.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final, Mapping, Sequence

from .models import DESCRIPTOR_VERSION, TaxonomyError, _enum, _identifier, _strings, _text, _version


PROFILE_INTERFACE: Final = "SemanticProfile@1"
COMPOSITION_INTERFACE: Final = "FamilyComposition@1"
PROFILE_SCHEMA_VERSION: Final = "logic-family-semantic-profile/v1"
COMPOSITION_SCHEMA_VERSION: Final = "logic-family-composition/v1"
COMPOSITION_METADATA_VERSION: Final = "1.0.0"

# Canonical family IDs that must always publish composition metadata.
COMPOSITION_REQUIRED_FAMILY_IDS: Final[frozenset[str]] = frozenset({"tdfol", "dcec"})

# Legacy labels that must never become opaque family strings; they are profiles
# or compositions over retained canonical family IDs.
OPAQUE_REPLACEMENT_FAMILY_STRINGS: Final[frozenset[str]] = frozenset(
    {
        "temporal_first_order",
        "first_order_temporal",
        "temporal-fol",
        "temporal_fol",
        "tfol",
    }
)


class SemanticProfileError(TaxonomyError):
    """Raised when a semantic profile or composition is invalid."""


class ConsequenceRelation(str, Enum):
    """Logical consequence / proof-theoretic stance."""

    CLASSICAL = "classical"
    INTUITIONISTIC = "intuitionistic"
    PARACONSISTENT = "paraconsistent"


class WorldPolicy(str, Enum):
    """Open/closed-world and default-negation policy."""

    OPEN_WORLD = "open_world"
    CLOSED_WORLD = "closed_world"
    DEFAULT_NEGATION = "default_negation"


class DomainBoundedness(str, Enum):
    """Domain cardinality assumptions."""

    UNBOUNDED = "unbounded"
    FINITE = "finite"


class TimeDensity(str, Enum):
    """Temporal carrier density."""

    DISCRETE = "discrete"
    DENSE = "dense"
    NOT_APPLICABLE = "not_applicable"


class TraceModel(str, Enum):
    """Trace length model for temporal/runtime semantics."""

    FINITE = "finite"
    INFINITE = "infinite"
    FINITE_OR_INFINITE = "finite_or_infinite"
    NOT_APPLICABLE = "not_applicable"


class FairnessConstraint(str, Enum):
    """Fairness assumptions over traces/schedulers."""

    NONE = "none"
    WEAK = "weak"
    STRONG = "strong"
    UNCONDITIONAL = "unconditional"
    NOT_APPLICABLE = "not_applicable"


class KripkeFrame(str, Enum):
    """Named Kripke frame constraint packages."""

    NONE = "none"
    K = "k"
    D = "d"
    T = "t"
    S4 = "s4"
    S5 = "s5"
    NOT_APPLICABLE = "not_applicable"


class PermissionStrength(str, Enum):
    """Permission polarity for deontic norms."""

    NONE = "none"
    STRONG = "strong"
    WEAK = "weak"
    NOT_APPLICABLE = "not_applicable"


class NormForm(str, Enum):
    """Norm representation shape."""

    NONE = "none"
    MONADIC = "monadic"
    DYADIC = "dyadic"
    NOT_APPLICABLE = "not_applicable"


class AttackerModel(str, Enum):
    """Symbolic adversary model for protocol profiles."""

    NONE = "none"
    DOLEV_YAO = "dolev_yao"
    CUSTOM = "custom"
    NOT_APPLICABLE = "not_applicable"


class ArithmeticSemantics(str, Enum):
    """Arithmetic interpretation for SMT-facing profiles."""

    NONE = "none"
    LINEAR_INTEGER = "linear_integer"
    NONLINEAR_INTEGER = "nonlinear_integer"
    LINEAR_REAL = "linear_real"
    NONLINEAR_REAL = "nonlinear_real"
    BITVECTOR = "bitvector"
    NOT_APPLICABLE = "not_applicable"


def _profile_enum(value: object, enum_type: type[Enum], field_name: str) -> Any:
    try:
        return _enum(value, enum_type, field_name)
    except TaxonomyError as error:
        raise SemanticProfileError(str(error)) from error


def _profile_text(value: object, field_name: str) -> str:
    try:
        return _text(value, field_name)
    except TaxonomyError as error:
        raise SemanticProfileError(str(error)) from error


def _profile_identifier(value: object, field_name: str) -> str:
    try:
        return _identifier(value, field_name)
    except TaxonomyError as error:
        raise SemanticProfileError(str(error)) from error


def _profile_version(value: object, field_name: str = "version") -> str:
    try:
        return _version(value, field_name)
    except TaxonomyError as error:
        raise SemanticProfileError(str(error)) from error


def _profile_strings(
    value: Sequence[str] | None,
    field_name: str,
    *,
    identifiers: bool = False,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    try:
        result = _strings(value, field_name, identifiers=identifiers)
    except TaxonomyError as error:
        raise SemanticProfileError(str(error)) from error
    if not result and not allow_empty:
        raise SemanticProfileError(f"{field_name} must not be empty")
    return result


def _optional_positive_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise SemanticProfileError(f"{field_name} must be a positive integer or None")
    if value <= 0:
        raise SemanticProfileError(f"{field_name} must be a positive integer or None")
    return value


def _bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise SemanticProfileError(f"{field_name} must be a boolean")
    return value


@dataclass(frozen=True, slots=True)
class BoundProfile:
    """Domain and model-check bound choices."""

    domain: DomainBoundedness | str = DomainBoundedness.UNBOUNDED
    domain_size: int | None = None
    model_check_depth: int | None = None
    step_bound: int | None = None
    resource_bound_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "domain", _profile_enum(self.domain, DomainBoundedness, "bounds.domain")
        )
        object.__setattr__(
            self,
            "domain_size",
            _optional_positive_int(self.domain_size, "bounds.domain_size"),
        )
        object.__setattr__(
            self,
            "model_check_depth",
            _optional_positive_int(self.model_check_depth, "bounds.model_check_depth"),
        )
        object.__setattr__(
            self,
            "step_bound",
            _optional_positive_int(self.step_bound, "bounds.step_bound"),
        )
        object.__setattr__(
            self,
            "resource_bound_names",
            _profile_strings(
                self.resource_bound_names,
                "bounds.resource_bound_names",
                identifiers=True,
            ),
        )
        if self.domain is DomainBoundedness.FINITE and self.domain_size is None:
            raise SemanticProfileError(
                "finite domain bounds require bounds.domain_size"
            )
        if self.domain is DomainBoundedness.UNBOUNDED and self.domain_size is not None:
            raise SemanticProfileError(
                "unbounded domain cannot declare bounds.domain_size"
            )

    @property
    def is_finite(self) -> bool:
        return self.domain is DomainBoundedness.FINITE

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain.value,
            "domain_size": self.domain_size,
            "model_check_depth": self.model_check_depth,
            "resource_bound_names": list(self.resource_bound_names),
            "step_bound": self.step_bound,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BoundProfile":
        return cls(
            domain=value.get("domain", DomainBoundedness.UNBOUNDED),
            domain_size=value.get("domain_size"),
            model_check_depth=value.get("model_check_depth"),
            step_bound=value.get("step_bound"),
            resource_bound_names=tuple(value.get("resource_bound_names", ())),
        )


@dataclass(frozen=True, slots=True)
class TraceProfile:
    """Trace, stuttering, and fairness choices."""

    model: TraceModel | str = TraceModel.NOT_APPLICABLE
    stuttering_allowed: bool | None = None
    fairness: FairnessConstraint | str = FairnessConstraint.NOT_APPLICABLE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "model", _profile_enum(self.model, TraceModel, "traces.model")
        )
        object.__setattr__(
            self,
            "fairness",
            _profile_enum(self.fairness, FairnessConstraint, "traces.fairness"),
        )
        if self.stuttering_allowed is not None:
            object.__setattr__(
                self,
                "stuttering_allowed",
                _bool(self.stuttering_allowed, "traces.stuttering_allowed"),
            )
        if self.model is TraceModel.NOT_APPLICABLE:
            if self.stuttering_allowed is not None:
                raise SemanticProfileError(
                    "traces.stuttering_allowed requires an applicable trace model"
                )
            if self.fairness is not FairnessConstraint.NOT_APPLICABLE:
                raise SemanticProfileError(
                    "traces.fairness requires an applicable trace model"
                )
        else:
            if self.stuttering_allowed is None:
                raise SemanticProfileError(
                    "applicable traces.model requires traces.stuttering_allowed"
                )
            if self.fairness is FairnessConstraint.NOT_APPLICABLE:
                raise SemanticProfileError(
                    "applicable traces.model requires an explicit traces.fairness"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "fairness": self.fairness.value,
            "model": self.model.value,
            "stuttering_allowed": self.stuttering_allowed,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TraceProfile":
        return cls(
            model=value.get("model", TraceModel.NOT_APPLICABLE),
            stuttering_allowed=value.get("stuttering_allowed"),
            fairness=value.get("fairness", FairnessConstraint.NOT_APPLICABLE),
        )


@dataclass(frozen=True, slots=True)
class TimeProfile:
    """Time carrier density and metric interval admission."""

    density: TimeDensity | str = TimeDensity.NOT_APPLICABLE
    metric_intervals: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "density", _profile_enum(self.density, TimeDensity, "time.density")
        )
        object.__setattr__(
            self, "metric_intervals", _bool(self.metric_intervals, "time.metric_intervals")
        )
        if self.density is TimeDensity.NOT_APPLICABLE and self.metric_intervals:
            raise SemanticProfileError(
                "time.metric_intervals requires an applicable time.density"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "density": self.density.value,
            "metric_intervals": self.metric_intervals,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TimeProfile":
        return cls(
            density=value.get("density", TimeDensity.NOT_APPLICABLE),
            metric_intervals=value.get("metric_intervals", False),
        )


@dataclass(frozen=True, slots=True)
class FrameProfile:
    """Modal Kripke frame constraints."""

    frame: KripkeFrame | str = KripkeFrame.NOT_APPLICABLE
    serial: bool | None = None
    reflexive: bool | None = None
    transitive: bool | None = None
    euclidean: bool | None = None
    symmetric: bool | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "frame", _profile_enum(self.frame, KripkeFrame, "frames.frame")
        )
        for name in ("serial", "reflexive", "transitive", "euclidean", "symmetric"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _bool(value, f"frames.{name}"))

        if self.frame is KripkeFrame.NOT_APPLICABLE:
            if any(
                getattr(self, name) is not None
                for name in ("serial", "reflexive", "transitive", "euclidean", "symmetric")
            ):
                raise SemanticProfileError(
                    "frame property flags require an applicable frames.frame"
                )
            return

        if self.frame is KripkeFrame.NONE:
            return

        expected = _FRAME_PROPERTIES[self.frame]
        for name, required in expected.items():
            actual = getattr(self, name)
            if actual is None:
                object.__setattr__(self, name, required)
            elif actual is not required:
                raise SemanticProfileError(
                    f"frames.{name}={actual!r} contradicts Kripke frame {self.frame.value}"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "euclidean": self.euclidean,
            "frame": self.frame.value,
            "reflexive": self.reflexive,
            "serial": self.serial,
            "symmetric": self.symmetric,
            "transitive": self.transitive,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FrameProfile":
        return cls(
            frame=value.get("frame", KripkeFrame.NOT_APPLICABLE),
            serial=value.get("serial"),
            reflexive=value.get("reflexive"),
            transitive=value.get("transitive"),
            euclidean=value.get("euclidean"),
            symmetric=value.get("symmetric"),
        )


_FRAME_PROPERTIES: Final[Mapping[KripkeFrame, Mapping[str, bool]]] = MappingProxyType(
    {
        KripkeFrame.K: MappingProxyType(
            {
                "serial": False,
                "reflexive": False,
                "transitive": False,
                "euclidean": False,
                "symmetric": False,
            }
        ),
        KripkeFrame.D: MappingProxyType(
            {
                "serial": True,
                "reflexive": False,
                "transitive": False,
                "euclidean": False,
                "symmetric": False,
            }
        ),
        KripkeFrame.T: MappingProxyType(
            {
                "serial": True,
                "reflexive": True,
                "transitive": False,
                "euclidean": False,
                "symmetric": False,
            }
        ),
        KripkeFrame.S4: MappingProxyType(
            {
                "serial": True,
                "reflexive": True,
                "transitive": True,
                "euclidean": False,
                "symmetric": False,
            }
        ),
        KripkeFrame.S5: MappingProxyType(
            {
                "serial": True,
                "reflexive": True,
                "transitive": True,
                "euclidean": True,
                "symmetric": True,
            }
        ),
    }
)


@dataclass(frozen=True, slots=True)
class NormProfile:
    """Deontic / normative semantic choices."""

    permission: PermissionStrength | str = PermissionStrength.NOT_APPLICABLE
    form: NormForm | str = NormForm.NOT_APPLICABLE
    priorities: bool = False
    exceptions: bool = False
    contrary_to_duty: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "permission",
            _profile_enum(self.permission, PermissionStrength, "norms.permission"),
        )
        object.__setattr__(
            self, "form", _profile_enum(self.form, NormForm, "norms.form")
        )
        object.__setattr__(self, "priorities", _bool(self.priorities, "norms.priorities"))
        object.__setattr__(self, "exceptions", _bool(self.exceptions, "norms.exceptions"))
        object.__setattr__(
            self,
            "contrary_to_duty",
            _bool(self.contrary_to_duty, "norms.contrary_to_duty"),
        )
        inactive = (
            self.permission is PermissionStrength.NOT_APPLICABLE
            and self.form is NormForm.NOT_APPLICABLE
        )
        if inactive:
            if self.priorities or self.exceptions or self.contrary_to_duty:
                raise SemanticProfileError(
                    "norm flags require applicable norms.permission or norms.form"
                )
            return
        if self.permission is PermissionStrength.NOT_APPLICABLE:
            raise SemanticProfileError(
                "applicable norms require an explicit norms.permission"
            )
        if self.form is NormForm.NOT_APPLICABLE:
            raise SemanticProfileError(
                "applicable norms require an explicit norms.form"
            )
        if self.permission is PermissionStrength.NONE and self.form is not NormForm.NONE:
            raise SemanticProfileError(
                "norms.form cannot be active when norms.permission is none"
            )
        if self.form is NormForm.NONE and self.permission is not PermissionStrength.NONE:
            raise SemanticProfileError(
                "norms.permission cannot be active when norms.form is none"
            )

    @property
    def is_active(self) -> bool:
        return self.permission not in {
            PermissionStrength.NOT_APPLICABLE,
            PermissionStrength.NONE,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "contrary_to_duty": self.contrary_to_duty,
            "exceptions": self.exceptions,
            "form": self.form.value,
            "permission": self.permission.value,
            "priorities": self.priorities,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NormProfile":
        return cls(
            permission=value.get("permission", PermissionStrength.NOT_APPLICABLE),
            form=value.get("form", NormForm.NOT_APPLICABLE),
            priorities=value.get("priorities", False),
            exceptions=value.get("exceptions", False),
            contrary_to_duty=value.get("contrary_to_duty", False),
        )


@dataclass(frozen=True, slots=True)
class AttackerProfile:
    """Symbolic attacker / equational-theory choices."""

    model: AttackerModel | str = AttackerModel.NOT_APPLICABLE
    equational_theories: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "model", _profile_enum(self.model, AttackerModel, "attacker.model")
        )
        object.__setattr__(
            self,
            "equational_theories",
            _profile_strings(
                self.equational_theories,
                "attacker.equational_theories",
                identifiers=True,
            ),
        )
        object.__setattr__(
            self, "notes", _profile_text(self.notes, "attacker.notes") if self.notes else ""
        )
        if self.model is AttackerModel.NOT_APPLICABLE:
            if self.equational_theories:
                raise SemanticProfileError(
                    "attacker.equational_theories require an applicable attacker.model"
                )
            return
        if self.model is AttackerModel.NONE and self.equational_theories:
            raise SemanticProfileError(
                "attacker.model none cannot declare equational theories"
            )
        if self.model is AttackerModel.CUSTOM and not self.equational_theories:
            raise SemanticProfileError(
                "custom attacker.model requires at least one equational theory"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "equational_theories": list(self.equational_theories),
            "model": self.model.value,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AttackerProfile":
        return cls(
            model=value.get("model", AttackerModel.NOT_APPLICABLE),
            equational_theories=tuple(value.get("equational_theories", ())),
            notes=value.get("notes", ""),
        )


@dataclass(frozen=True, slots=True)
class HypertraceProfile:
    """Hyperproperty quantifier-prefix and alternation limits."""

    quantifier_prefix: tuple[str, ...] = ()
    max_alternation: int | None = None
    supported: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "supported", _bool(self.supported, "hypertrace.supported"))
        raw_prefix = self.quantifier_prefix
        if raw_prefix is None:
            prefix: tuple[str, ...] = ()
        elif isinstance(raw_prefix, (str, bytes, bytearray)) or not isinstance(
            raw_prefix, Sequence
        ):
            raise SemanticProfileError(
                "hypertrace.quantifier_prefix must be a sequence of quantifier labels"
            )
        else:
            normalized: list[str] = []
            for item in raw_prefix:
                label = _profile_text(item, "hypertrace.quantifier_prefix item").casefold()
                if label not in {"forall", "exists", "a", "e"}:
                    raise SemanticProfileError(
                        "hypertrace.quantifier_prefix items must be "
                        "'forall', 'exists', 'A', or 'E'"
                    )
                normalized.append("forall" if label in {"forall", "a"} else "exists")
            prefix = tuple(normalized)
        object.__setattr__(self, "quantifier_prefix", prefix)
        if self.max_alternation is not None:
            if isinstance(self.max_alternation, bool) or not isinstance(
                self.max_alternation, int
            ):
                raise SemanticProfileError(
                    "hypertrace.max_alternation must be a non-negative integer or None"
                )
            if self.max_alternation < 0:
                raise SemanticProfileError(
                    "hypertrace.max_alternation must be a non-negative integer or None"
                )
        if self.supported:
            if not self.quantifier_prefix:
                raise SemanticProfileError(
                    "supported hypertrace requires hypertrace.quantifier_prefix"
                )
            if self.max_alternation is None:
                raise SemanticProfileError(
                    "supported hypertrace requires hypertrace.max_alternation"
                )
            actual_alternation = _count_alternation(self.quantifier_prefix)
            if actual_alternation > self.max_alternation:
                raise SemanticProfileError(
                    "hypertrace.quantifier_prefix alternation exceeds max_alternation"
                )
        else:
            if self.quantifier_prefix or self.max_alternation is not None:
                raise SemanticProfileError(
                    "unsupported hypertrace cannot declare prefix or alternation"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_alternation": self.max_alternation,
            "quantifier_prefix": list(self.quantifier_prefix),
            "supported": self.supported,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HypertraceProfile":
        return cls(
            quantifier_prefix=tuple(value.get("quantifier_prefix", ())),
            max_alternation=value.get("max_alternation"),
            supported=value.get("supported", False),
        )


def _count_alternation(prefix: Sequence[str]) -> int:
    if not prefix:
        return 0
    alternation = 0
    current = prefix[0]
    for item in prefix[1:]:
        if item != current:
            alternation += 1
            current = item
    return alternation


@dataclass(frozen=True, slots=True)
class SmtTheoryProfile:
    """SMT theory set and arithmetic / bit-vector semantics."""

    theories: tuple[str, ...] = ()
    arithmetic: ArithmeticSemantics | str = ArithmeticSemantics.NOT_APPLICABLE
    bitvector_width: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "theories",
            _profile_strings(self.theories, "smt_theory.theories", identifiers=True),
        )
        object.__setattr__(
            self,
            "arithmetic",
            _profile_enum(self.arithmetic, ArithmeticSemantics, "smt_theory.arithmetic"),
        )
        object.__setattr__(
            self,
            "bitvector_width",
            _optional_positive_int(self.bitvector_width, "smt_theory.bitvector_width"),
        )
        active = bool(self.theories) or self.arithmetic not in {
            ArithmeticSemantics.NOT_APPLICABLE,
            ArithmeticSemantics.NONE,
        }
        if not active and self.bitvector_width is not None:
            raise SemanticProfileError(
                "smt_theory.bitvector_width requires active SMT theory choices"
            )
        if self.arithmetic is ArithmeticSemantics.BITVECTOR and self.bitvector_width is None:
            raise SemanticProfileError(
                "bitvector arithmetic requires smt_theory.bitvector_width"
            )
        if (
            self.arithmetic is not ArithmeticSemantics.BITVECTOR
            and self.bitvector_width is not None
        ):
            raise SemanticProfileError(
                "smt_theory.bitvector_width is valid only for bitvector arithmetic"
            )
        if self.theories and self.arithmetic is ArithmeticSemantics.NOT_APPLICABLE:
            raise SemanticProfileError(
                "declared SMT theories require explicit smt_theory.arithmetic"
            )

    @property
    def is_active(self) -> bool:
        return bool(self.theories) or self.arithmetic not in {
            ArithmeticSemantics.NOT_APPLICABLE,
            ArithmeticSemantics.NONE,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "arithmetic": self.arithmetic.value,
            "bitvector_width": self.bitvector_width,
            "theories": list(self.theories),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SmtTheoryProfile":
        return cls(
            theories=tuple(value.get("theories", ())),
            arithmetic=value.get("arithmetic", ArithmeticSemantics.NOT_APPLICABLE),
            bitvector_width=value.get("bitvector_width"),
        )


@dataclass(frozen=True, slots=True)
class KernelEnvironmentProfile:
    """Proof-assistant universe / import / axiom environment."""

    universes: tuple[str, ...] = ()
    imports: tuple[str, ...] = ()
    axioms: tuple[str, ...] = ()
    target: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "universes",
            _profile_strings(
                self.universes, "kernel_environment.universes", identifiers=True
            ),
        )
        object.__setattr__(
            self,
            "imports",
            _profile_strings(self.imports, "kernel_environment.imports", identifiers=True),
        )
        object.__setattr__(
            self,
            "axioms",
            _profile_strings(self.axioms, "kernel_environment.axioms", identifiers=True),
        )
        if self.target is not None:
            object.__setattr__(
                self,
                "target",
                _profile_identifier(self.target, "kernel_environment.target"),
            )
        active = bool(self.universes or self.imports or self.axioms)
        if active and self.target is None:
            raise SemanticProfileError(
                "kernel environment declarations require kernel_environment.target"
            )
        if self.target is not None and not active:
            raise SemanticProfileError(
                "kernel_environment.target requires at least one universe, import, or axiom"
            )

    @property
    def is_active(self) -> bool:
        return self.target is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "axioms": list(self.axioms),
            "imports": list(self.imports),
            "target": self.target,
            "universes": list(self.universes),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "KernelEnvironmentProfile":
        return cls(
            universes=tuple(value.get("universes", ())),
            imports=tuple(value.get("imports", ())),
            axioms=tuple(value.get("axioms", ())),
            target=value.get("target"),
        )


@dataclass(frozen=True, slots=True)
class SemanticProfile:
    """Versioned semantic profile (``SemanticProfile@1``).

    Every dimension is an explicit field.  Optional dimensions default to
    not-applicable sentinels; activating a dimension requires complete choices
    and rejects internal contradictions.
    """

    profile_id: str
    name: str
    consequence: ConsequenceRelation | str
    world_policy: WorldPolicy | str
    description: str = ""
    bounds: BoundProfile = field(default_factory=BoundProfile)
    traces: TraceProfile = field(default_factory=TraceProfile)
    time: TimeProfile = field(default_factory=TimeProfile)
    frames: FrameProfile = field(default_factory=FrameProfile)
    norms: NormProfile = field(default_factory=NormProfile)
    attacker: AttackerProfile = field(default_factory=AttackerProfile)
    hypertrace: HypertraceProfile = field(default_factory=HypertraceProfile)
    smt_theory: SmtTheoryProfile = field(default_factory=SmtTheoryProfile)
    kernel_environment: KernelEnvironmentProfile = field(
        default_factory=KernelEnvironmentProfile
    )
    family_ids: tuple[str, ...] = ()
    fragment_ids: tuple[str, ...] = ()
    version: str = DESCRIPTOR_VERSION

    schema_version: ClassVar[str] = PROFILE_SCHEMA_VERSION
    interface: ClassVar[str] = PROFILE_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "profile_id", _profile_identifier(self.profile_id, "profile_id")
        )
        object.__setattr__(self, "name", _profile_text(self.name, "name"))
        object.__setattr__(
            self,
            "description",
            _profile_text(self.description, "description") if self.description else "",
        )
        object.__setattr__(
            self,
            "consequence",
            _profile_enum(self.consequence, ConsequenceRelation, "consequence"),
        )
        object.__setattr__(
            self,
            "world_policy",
            _profile_enum(self.world_policy, WorldPolicy, "world_policy"),
        )
        object.__setattr__(self, "version", _profile_version(self.version))
        object.__setattr__(self, "bounds", _coerce_bounds(self.bounds))
        object.__setattr__(self, "traces", _coerce_traces(self.traces))
        object.__setattr__(self, "time", _coerce_time(self.time))
        object.__setattr__(self, "frames", _coerce_frames(self.frames))
        object.__setattr__(self, "norms", _coerce_norms(self.norms))
        object.__setattr__(self, "attacker", _coerce_attacker(self.attacker))
        object.__setattr__(self, "hypertrace", _coerce_hypertrace(self.hypertrace))
        object.__setattr__(self, "smt_theory", _coerce_smt(self.smt_theory))
        object.__setattr__(
            self,
            "kernel_environment",
            _coerce_kernel(self.kernel_environment),
        )
        object.__setattr__(
            self,
            "family_ids",
            _profile_strings(self.family_ids, "family_ids", identifiers=True),
        )
        object.__setattr__(
            self,
            "fragment_ids",
            _profile_strings(self.fragment_ids, "fragment_ids", identifiers=True),
        )
        _validate_cross_field_profile(self)

    @property
    def id(self) -> str:
        return self.profile_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "attacker": self.attacker.to_dict(),
            "bounds": self.bounds.to_dict(),
            "consequence": self.consequence.value,
            "description": self.description,
            "family_ids": list(self.family_ids),
            "fragment_ids": list(self.fragment_ids),
            "frames": self.frames.to_dict(),
            "hypertrace": self.hypertrace.to_dict(),
            "interface": self.interface,
            "kernel_environment": self.kernel_environment.to_dict(),
            "name": self.name,
            "norms": self.norms.to_dict(),
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
            "smt_theory": self.smt_theory.to_dict(),
            "time": self.time.to_dict(),
            "traces": self.traces.to_dict(),
            "version": self.version,
            "world_policy": self.world_policy.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SemanticProfile":
        if not isinstance(value, Mapping):
            raise SemanticProfileError("SemanticProfile payload must be a mapping")
        return cls(
            profile_id=value["profile_id"],
            name=value["name"],
            consequence=value["consequence"],
            world_policy=value["world_policy"],
            description=value.get("description", ""),
            bounds=BoundProfile.from_dict(value.get("bounds", {})),
            traces=TraceProfile.from_dict(value.get("traces", {})),
            time=TimeProfile.from_dict(value.get("time", {})),
            frames=FrameProfile.from_dict(value.get("frames", {})),
            norms=NormProfile.from_dict(value.get("norms", {})),
            attacker=AttackerProfile.from_dict(value.get("attacker", {})),
            hypertrace=HypertraceProfile.from_dict(value.get("hypertrace", {})),
            smt_theory=SmtTheoryProfile.from_dict(value.get("smt_theory", {})),
            kernel_environment=KernelEnvironmentProfile.from_dict(
                value.get("kernel_environment", {})
            ),
            family_ids=tuple(value.get("family_ids", ())),
            fragment_ids=tuple(value.get("fragment_ids", ())),
            version=value.get("version", DESCRIPTOR_VERSION),
        )


def _coerce_bounds(value: BoundProfile | Mapping[str, Any]) -> BoundProfile:
    if isinstance(value, BoundProfile):
        return value
    if isinstance(value, Mapping):
        return BoundProfile.from_dict(value)
    raise SemanticProfileError("bounds must be a BoundProfile or mapping")


def _coerce_traces(value: TraceProfile | Mapping[str, Any]) -> TraceProfile:
    if isinstance(value, TraceProfile):
        return value
    if isinstance(value, Mapping):
        return TraceProfile.from_dict(value)
    raise SemanticProfileError("traces must be a TraceProfile or mapping")


def _coerce_time(value: TimeProfile | Mapping[str, Any]) -> TimeProfile:
    if isinstance(value, TimeProfile):
        return value
    if isinstance(value, Mapping):
        return TimeProfile.from_dict(value)
    raise SemanticProfileError("time must be a TimeProfile or mapping")


def _coerce_frames(value: FrameProfile | Mapping[str, Any]) -> FrameProfile:
    if isinstance(value, FrameProfile):
        return value
    if isinstance(value, Mapping):
        return FrameProfile.from_dict(value)
    raise SemanticProfileError("frames must be a FrameProfile or mapping")


def _coerce_norms(value: NormProfile | Mapping[str, Any]) -> NormProfile:
    if isinstance(value, NormProfile):
        return value
    if isinstance(value, Mapping):
        return NormProfile.from_dict(value)
    raise SemanticProfileError("norms must be a NormProfile or mapping")


def _coerce_attacker(value: AttackerProfile | Mapping[str, Any]) -> AttackerProfile:
    if isinstance(value, AttackerProfile):
        return value
    if isinstance(value, Mapping):
        return AttackerProfile.from_dict(value)
    raise SemanticProfileError("attacker must be an AttackerProfile or mapping")


def _coerce_hypertrace(
    value: HypertraceProfile | Mapping[str, Any],
) -> HypertraceProfile:
    if isinstance(value, HypertraceProfile):
        return value
    if isinstance(value, Mapping):
        return HypertraceProfile.from_dict(value)
    raise SemanticProfileError("hypertrace must be a HypertraceProfile or mapping")


def _coerce_smt(value: SmtTheoryProfile | Mapping[str, Any]) -> SmtTheoryProfile:
    if isinstance(value, SmtTheoryProfile):
        return value
    if isinstance(value, Mapping):
        return SmtTheoryProfile.from_dict(value)
    raise SemanticProfileError("smt_theory must be a SmtTheoryProfile or mapping")


def _coerce_kernel(
    value: KernelEnvironmentProfile | Mapping[str, Any],
) -> KernelEnvironmentProfile:
    if isinstance(value, KernelEnvironmentProfile):
        return value
    if isinstance(value, Mapping):
        return KernelEnvironmentProfile.from_dict(value)
    raise SemanticProfileError(
        "kernel_environment must be a KernelEnvironmentProfile or mapping"
    )


def _validate_cross_field_profile(profile: SemanticProfile) -> None:
    """Reject incomplete or contradictory combinations across dimensions."""

    temporal_active = (
        profile.time.density is not TimeDensity.NOT_APPLICABLE
        or profile.traces.model is not TraceModel.NOT_APPLICABLE
    )
    if temporal_active:
        if profile.time.density is TimeDensity.NOT_APPLICABLE:
            raise SemanticProfileError(
                "temporal profiles require an explicit time.density"
            )
        if profile.traces.model is TraceModel.NOT_APPLICABLE:
            raise SemanticProfileError(
                "temporal profiles require an explicit traces.model"
            )

    if (
        profile.traces.model is TraceModel.FINITE
        and profile.bounds.model_check_depth is None
        and profile.bounds.step_bound is None
    ):
        raise SemanticProfileError(
            "finite traces require bounds.model_check_depth or bounds.step_bound"
        )

    if (
        profile.world_policy is WorldPolicy.OPEN_WORLD
        and profile.consequence is ConsequenceRelation.CLASSICAL
        and "default_negation" in profile.fragment_ids
    ):
        raise SemanticProfileError(
            "open-world classical profiles cannot claim default_negation fragments"
        )

    if (
        profile.world_policy is WorldPolicy.DEFAULT_NEGATION
        and profile.consequence is ConsequenceRelation.INTUITIONISTIC
    ):
        raise SemanticProfileError(
            "default-negation world policy is incompatible with intuitionistic consequence"
        )

    if profile.hypertrace.supported and profile.traces.model is TraceModel.NOT_APPLICABLE:
        raise SemanticProfileError(
            "supported hypertrace requires an applicable traces.model"
        )

    if profile.attacker.model is AttackerModel.DOLEV_YAO and not profile.family_ids:
        # Attacker models must be anchored to at least one family (usually
        # cryptographic_protocol) so composition consumers can route them.
        raise SemanticProfileError(
            "dolev_yao attacker profiles must declare at least one family_id"
        )


@dataclass(frozen=True, slots=True)
class CompositionMetadata:
    """Mandatory, versioned composition metadata for retained family IDs."""

    composition_version: str
    component_family_ids: tuple[str, ...]
    role_by_family: tuple[tuple[str, str], ...] = ()
    notes: str = ""
    schema_version: str = COMPOSITION_METADATA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "composition_version",
            _profile_version(self.composition_version, "composition_version"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _profile_version(self.schema_version, "composition metadata schema_version"),
        )
        components = _profile_strings(
            self.component_family_ids,
            "component_family_ids",
            identifiers=True,
            allow_empty=False,
        )
        if len(components) < 2:
            raise SemanticProfileError(
                "composition metadata requires at least two component_family_ids"
            )
        object.__setattr__(self, "component_family_ids", components)
        object.__setattr__(
            self, "notes", _profile_text(self.notes, "notes") if self.notes else ""
        )
        raw_roles: object = self.role_by_family
        if isinstance(raw_roles, Mapping):
            raw_roles = tuple(raw_roles.items())
        if (
            isinstance(raw_roles, (str, bytes, bytearray))
            or not isinstance(raw_roles, Sequence)
        ):
            raise SemanticProfileError(
                "role_by_family must be a mapping or key/value sequence"
            )
        roles: list[tuple[str, str]] = []
        for item in raw_roles:
            if (
                not isinstance(item, Sequence)
                or isinstance(item, (str, bytes, bytearray))
                or len(item) != 2
            ):
                raise SemanticProfileError(
                    "role_by_family entries must be family_id/role pairs"
                )
            family_id = _profile_identifier(item[0], "role_by_family family_id")
            role = _profile_identifier(item[1], "role_by_family role")
            roles.append((family_id, role))
        if len({family for family, _ in roles}) != len(roles):
            raise SemanticProfileError("role_by_family must not contain duplicate families")
        unknown = sorted({family for family, _ in roles} - set(components))
        if unknown:
            raise SemanticProfileError(
                "role_by_family references unknown components: " + ", ".join(unknown)
            )
        object.__setattr__(self, "role_by_family", tuple(sorted(roles)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_family_ids": list(self.component_family_ids),
            "composition_version": self.composition_version,
            "notes": self.notes,
            "role_by_family": {family: role for family, role in self.role_by_family},
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CompositionMetadata":
        if not isinstance(value, Mapping):
            raise SemanticProfileError("composition metadata must be a mapping")
        return cls(
            composition_version=value["composition_version"],
            component_family_ids=tuple(value["component_family_ids"]),
            role_by_family=value.get("role_by_family", {}),
            notes=value.get("notes", ""),
            schema_version=value.get("schema_version", COMPOSITION_METADATA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class FamilyComposition:
    """Declared family composition (``FamilyComposition@1``).

    Composition retains a canonical ``family_id`` (for example ``tdfol`` or
    ``dcec``) and never replaces it with an opaque multi-family string.
    Temporal-FOL is the composition of ``temporal`` and ``first_order`` under a
    retained identity or profile label, not a new family name.
    """

    composition_id: str
    family_id: str
    name: str
    metadata: CompositionMetadata
    profile: SemanticProfile
    description: str = ""
    version: str = DESCRIPTOR_VERSION

    schema_version: ClassVar[str] = COMPOSITION_SCHEMA_VERSION
    interface: ClassVar[str] = COMPOSITION_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "composition_id",
            _profile_identifier(self.composition_id, "composition_id"),
        )
        object.__setattr__(
            self, "family_id", _profile_identifier(self.family_id, "family_id")
        )
        if self.family_id in OPAQUE_REPLACEMENT_FAMILY_STRINGS:
            raise SemanticProfileError(
                f"family_id {self.family_id!r} is an opaque replacement string; "
                "retain a canonical family ID and declare component_family_ids"
            )
        object.__setattr__(self, "name", _profile_text(self.name, "name"))
        object.__setattr__(
            self,
            "description",
            _profile_text(self.description, "description") if self.description else "",
        )
        object.__setattr__(self, "version", _profile_version(self.version))
        object.__setattr__(self, "metadata", _coerce_metadata(self.metadata))
        object.__setattr__(self, "profile", _coerce_profile(self.profile))
        if self.family_id in COMPOSITION_REQUIRED_FAMILY_IDS:
            # Mandatory composition metadata is already required for all
            # FamilyComposition values; additionally ensure components match
            # the retained identity's documented linkage.
            required = _REQUIRED_COMPONENTS[self.family_id]
            missing = sorted(set(required) - set(self.metadata.component_family_ids))
            if missing:
                raise SemanticProfileError(
                    f"canonical family {self.family_id!r} composition must include "
                    f"components: {', '.join(missing)}"
                )
        # Retained identity may appear among components when it is the primary
        # family of the composition, but at least one *other* component is
        # required so composition is not a no-op restatement.
        external = tuple(
            item
            for item in self.metadata.component_family_ids
            if item != self.family_id
        )
        if not external:
            raise SemanticProfileError(
                "component_family_ids must include at least one family other "
                "than the retained family_id"
            )
        # Profile family anchors must include the retained identity.
        if self.profile.family_ids and self.family_id not in self.profile.family_ids:
            raise SemanticProfileError(
                "composition profile.family_ids must include the retained family_id"
            )

    @property
    def id(self) -> str:
        return self.composition_id

    @property
    def component_family_ids(self) -> tuple[str, ...]:
        return self.metadata.component_family_ids

    @property
    def composition_version(self) -> str:
        return self.metadata.composition_version

    def to_dict(self) -> dict[str, Any]:
        return {
            "composition_id": self.composition_id,
            "description": self.description,
            "family_id": self.family_id,
            "interface": self.interface,
            "metadata": self.metadata.to_dict(),
            "name": self.name,
            "profile": self.profile.to_dict(),
            "schema_version": self.schema_version,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FamilyComposition":
        if not isinstance(value, Mapping):
            raise SemanticProfileError("FamilyComposition payload must be a mapping")
        return cls(
            composition_id=value["composition_id"],
            family_id=value["family_id"],
            name=value["name"],
            metadata=CompositionMetadata.from_dict(value["metadata"]),
            profile=SemanticProfile.from_dict(value["profile"]),
            description=value.get("description", ""),
            version=value.get("version", DESCRIPTOR_VERSION),
        )


def _coerce_metadata(
    value: CompositionMetadata | Mapping[str, Any],
) -> CompositionMetadata:
    if isinstance(value, CompositionMetadata):
        return value
    if isinstance(value, Mapping):
        return CompositionMetadata.from_dict(value)
    raise SemanticProfileError("metadata must be CompositionMetadata or a mapping")


def _coerce_profile(value: SemanticProfile | Mapping[str, Any]) -> SemanticProfile:
    if isinstance(value, SemanticProfile):
        return value
    if isinstance(value, Mapping):
        return SemanticProfile.from_dict(value)
    raise SemanticProfileError("profile must be a SemanticProfile or mapping")


_REQUIRED_COMPONENTS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "tdfol": ("deontic", "first_order", "temporal"),
        "dcec": ("deontic", "event_calculus"),
    }
)


def classical_open_world_profile(
    profile_id: str,
    name: str,
    *,
    family_ids: Sequence[str] = (),
    fragment_ids: Sequence[str] = (),
    description: str = "",
) -> SemanticProfile:
    """Build a minimal classical open-world profile."""

    return SemanticProfile(
        profile_id=profile_id,
        name=name,
        consequence=ConsequenceRelation.CLASSICAL,
        world_policy=WorldPolicy.OPEN_WORLD,
        description=description,
        family_ids=tuple(family_ids),
        fragment_ids=tuple(fragment_ids),
    )


def build_temporal_first_order_composition(
    *,
    composition_id: str = "temporal_first_order_v1",
    profile_id: str = "temporal_first_order",
    composition_version: str = "1.0.0",
) -> FamilyComposition:
    """Express temporal-FOL as declared composition, not an opaque family string.

    The retained canonical identity is ``tdfol`` for compatibility; components
    are exactly ``temporal`` and ``first_order`` plus the deontic component
    required by the ``tdfol`` retained identity.  Callers that need a pure
    temporal+FOL profile without deontic content should use
    :func:`build_pure_temporal_fol_composition`.
    """

    profile = SemanticProfile(
        profile_id=profile_id,
        name="Temporal first-order composition profile",
        consequence=ConsequenceRelation.CLASSICAL,
        world_policy=WorldPolicy.OPEN_WORLD,
        description=(
            "Declared composition of temporal and first-order semantics; "
            "not an opaque replacement family string."
        ),
        bounds=BoundProfile(domain=DomainBoundedness.UNBOUNDED),
        traces=TraceProfile(
            model=TraceModel.INFINITE,
            stuttering_allowed=True,
            fairness=FairnessConstraint.NONE,
        ),
        time=TimeProfile(density=TimeDensity.DISCRETE, metric_intervals=False),
        frames=FrameProfile(frame=KripkeFrame.NOT_APPLICABLE),
        norms=NormProfile(
            permission=PermissionStrength.STRONG,
            form=NormForm.MONADIC,
            priorities=False,
            exceptions=False,
            contrary_to_duty=False,
        ),
        family_ids=("tdfol", "temporal", "first_order", "deontic"),
        fragment_ids=("linear_time", "quantifiers", "deontic"),
    )
    metadata = CompositionMetadata(
        composition_version=composition_version,
        component_family_ids=("deontic", "first_order", "temporal"),
        role_by_family={
            "temporal": "time_trace",
            "first_order": "quantified_matrix",
            "deontic": "normative_operators",
        },
        notes=(
            "temporal_first_order is a composition label over retained tdfol; "
            "it must not be emitted as a standalone family_id"
        ),
    )
    return FamilyComposition(
        composition_id=composition_id,
        family_id="tdfol",
        name="Temporal-FOL (tdfol retained identity)",
        metadata=metadata,
        profile=profile,
        description=(
            "Temporal-FOL expressed as versioned composition metadata under "
            "canonical family_id tdfol"
        ),
    )


def build_pure_temporal_fol_composition(
    *,
    composition_id: str = "pure_temporal_fol_v1",
    profile_id: str = "temporal_first_order",
    composition_version: str = "1.0.0",
) -> FamilyComposition:
    """Composition of only ``temporal`` and ``first_order`` under ``temporal``.

    This is the plan migration example ``temporal_first_order`` without
    promoting that string to a family ID.  The retained identity is the
    primary temporal family; FOL is a component, not a replacement family.
    The well-known label may appear as ``profile_id`` only.
    """

    profile = SemanticProfile(
        profile_id=profile_id,
        name="Pure temporal first-order composition profile",
        consequence=ConsequenceRelation.CLASSICAL,
        world_policy=WorldPolicy.OPEN_WORLD,
        description="Declared composition of temporal and first_order only.",
        bounds=BoundProfile(domain=DomainBoundedness.UNBOUNDED),
        traces=TraceProfile(
            model=TraceModel.INFINITE,
            stuttering_allowed=False,
            fairness=FairnessConstraint.NONE,
        ),
        time=TimeProfile(density=TimeDensity.DISCRETE, metric_intervals=False),
        family_ids=("temporal", "first_order"),
        fragment_ids=("linear_time", "quantifiers"),
    )
    metadata = CompositionMetadata(
        composition_version=composition_version,
        component_family_ids=("first_order", "temporal"),
        role_by_family={
            "temporal": "time_trace",
            "first_order": "quantified_matrix",
        },
        notes=(
            "temporal_first_order is composition of temporal and first_order; "
            "do not invent a replacement family string"
        ),
    )
    return FamilyComposition(
        composition_id=composition_id,
        family_id="temporal",
        name="Temporal + first-order composition",
        metadata=metadata,
        profile=profile,
        description=(
            "Plan migration: temporal_first_order -> composition of temporal "
            "and first_order under retained temporal identity"
        ),
    )


def build_tdfol_composition(
    *,
    composition_id: str = "tdfol_composition_v1",
    composition_version: str = "1.0.0",
) -> FamilyComposition:
    """Canonical ``tdfol`` retained identity with mandatory composition metadata."""

    return build_temporal_first_order_composition(
        composition_id=composition_id,
        profile_id="tdfol_default",
        composition_version=composition_version,
    )


def build_dcec_composition(
    *,
    composition_id: str = "dcec_composition_v1",
    composition_version: str = "1.0.0",
) -> FamilyComposition:
    """Canonical ``dcec`` retained identity with mandatory composition metadata.

    Components link deontic, event-calculus, and cognitive/modal dimensions
    without replacing the ``dcec`` family ID.
    """

    profile = SemanticProfile(
        profile_id="dcec_default",
        name="DCEC default composition profile",
        consequence=ConsequenceRelation.CLASSICAL,
        world_policy=WorldPolicy.OPEN_WORLD,
        description=(
            "Deontic cognitive event calculus composition: deontic + event_calculus "
            "+ modal/cognitive operators under retained dcec identity."
        ),
        bounds=BoundProfile(domain=DomainBoundedness.UNBOUNDED),
        traces=TraceProfile(
            model=TraceModel.FINITE_OR_INFINITE,
            stuttering_allowed=True,
            fairness=FairnessConstraint.NONE,
        ),
        time=TimeProfile(density=TimeDensity.DISCRETE, metric_intervals=False),
        frames=FrameProfile(frame=KripkeFrame.S5),
        norms=NormProfile(
            permission=PermissionStrength.STRONG,
            form=NormForm.DYADIC,
            priorities=True,
            exceptions=True,
            contrary_to_duty=True,
        ),
        family_ids=("dcec", "deontic", "event_calculus", "modal"),
        fragment_ids=("deontic", "event_calculus", "modal", "quantifiers"),
    )
    metadata = CompositionMetadata(
        composition_version=composition_version,
        component_family_ids=("deontic", "event_calculus", "modal"),
        role_by_family={
            "deontic": "norms",
            "event_calculus": "events_fluents",
            "modal": "cognitive_attitudes",
        },
        notes=(
            "dcec retains its canonical family_id; composition metadata links "
            "deontic, event, and cognitive/modal components"
        ),
    )
    return FamilyComposition(
        composition_id=composition_id,
        family_id="dcec",
        name="DCEC composition",
        metadata=metadata,
        profile=profile,
        description="Canonical dcec with versioned deontic/event/cognitive composition",
    )


def require_composition_metadata(
    family_id: str,
    metadata: CompositionMetadata | Mapping[str, Any] | None,
) -> CompositionMetadata:
    """Fail closed when composition-required families lack metadata.

    Canonical ``tdfol`` and ``dcec`` always require versioned composition
    metadata.  Other families may optionally carry metadata; when provided it
    is validated, and when omitted this helper raises so callers cannot treat
    absence as success for composition-required IDs.
    """

    canonical = _profile_identifier(family_id, "family_id")
    if metadata is None:
        if canonical in COMPOSITION_REQUIRED_FAMILY_IDS:
            raise SemanticProfileError(
                f"canonical family {canonical!r} requires mandatory composition metadata"
            )
        raise SemanticProfileError(
            f"family {canonical!r} was checked for composition metadata but none was provided"
        )
    result = _coerce_metadata(metadata)
    if canonical in COMPOSITION_REQUIRED_FAMILY_IDS:
        required = _REQUIRED_COMPONENTS[canonical]
        missing = sorted(set(required) - set(result.component_family_ids))
        if missing:
            raise SemanticProfileError(
                f"canonical family {canonical!r} composition must include "
                f"components: {', '.join(missing)}"
            )
    return result


def is_opaque_replacement_family_string(value: str) -> bool:
    """Return True when ``value`` is a banned opaque multi-family string."""

    if not isinstance(value, str) or not value.strip():
        return False
    normalized = value.strip().casefold().replace("-", "_")
    return normalized in OPAQUE_REPLACEMENT_FAMILY_STRINGS


def default_compositions() -> tuple[FamilyComposition, ...]:
    """Return the sealed baseline compositions for tdfol, dcec, and temporal-FOL."""

    return (
        build_tdfol_composition(),
        build_dcec_composition(),
        build_pure_temporal_fol_composition(),
    )


def default_composition_map() -> Mapping[str, FamilyComposition]:
    """Map retained family / composition ids onto baseline compositions."""

    items = default_compositions()
    by_id = {item.composition_id: item for item in items}
    by_family = {item.family_id: item for item in items}
    # Prefer explicit composition_id keys; also expose family_id keys for lookup.
    merged = {**by_family, **by_id}
    return MappingProxyType(merged)


__all__ = [
    "COMPOSITION_INTERFACE",
    "COMPOSITION_METADATA_VERSION",
    "COMPOSITION_REQUIRED_FAMILY_IDS",
    "COMPOSITION_SCHEMA_VERSION",
    "ArithmeticSemantics",
    "AttackerModel",
    "AttackerProfile",
    "BoundProfile",
    "CompositionMetadata",
    "ConsequenceRelation",
    "DomainBoundedness",
    "FairnessConstraint",
    "FamilyComposition",
    "FrameProfile",
    "HypertraceProfile",
    "KernelEnvironmentProfile",
    "KripkeFrame",
    "NormForm",
    "NormProfile",
    "OPAQUE_REPLACEMENT_FAMILY_STRINGS",
    "PROFILE_INTERFACE",
    "PROFILE_SCHEMA_VERSION",
    "PermissionStrength",
    "SemanticProfile",
    "SemanticProfileError",
    "SmtTheoryProfile",
    "TimeDensity",
    "TimeProfile",
    "TraceModel",
    "TraceProfile",
    "WorldPolicy",
    "build_dcec_composition",
    "build_pure_temporal_fol_composition",
    "build_tdfol_composition",
    "build_temporal_first_order_composition",
    "classical_open_world_profile",
    "default_composition_map",
    "default_compositions",
    "is_opaque_replacement_family_string",
    "require_composition_metadata",
]
