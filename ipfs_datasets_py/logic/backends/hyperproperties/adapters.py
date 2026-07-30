"""HyperLTL, AutoHyper, and MCHyper backends with typed witness bundles.

``HyperLTLBackend@1``, ``AutoHyperBackend@1``, and ``MCHyperBackend@1`` are
distinct external-execution surfaces for multi-trace hyperproperties:

* each engine has its own discovery, capability declaration, and quantifier
  limits;
* translation preserves quantifier order and observation maps exactly;
* engine counterexamples become redacted :class:`WitnessTraceBundle` values
  that can be replayed against the observation map;
* bounded self-composition is retained as an explicit, non-authoritative
  fallback and must never be represented as external-tool proof.

Absent tools and unsupported quantifier alternation return non-success.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from ...families.models import EvidenceAuthority
from ...ir_core.claims import FrozenMap, stable_digest
from ...ir_core.protocols import (
    BackendCapabilities,
    BackendRequest,
    ExecutionBounds,
    QueryKind,
    ResourceUsage,
)
from ...software_verification.hyperproperties import (
    DEFAULT_MAX_COMPOSITION_PAIRS,
    DEFAULT_MAX_COMPOSITION_TRACES,
    ExecutionTrace,
    HyperpropertyEvidenceKind,
    HyperpropertyIR,
    HyperpropertyValidationError,
    HyperpropertyVerdict,
    ObservationDifference,
    QuantifierBinding,
    SelfCompositionBound,
    TraceQuantifier,
    WitnessRole,
    WitnessTrace,
    WitnessTraceBundle,
    quantifier_order_is_canonical,
)
from ..process import (
    BoundedToolRunner,
    CancellationSignal,
    ToolProbe,
    ToolRunLimits,
    ToolRunRequest,
    ToolRunResult,
    ToolRuntime,
)
from ..results import (
    HyperpropertyResult,
    ResultAuthority,
    ResultStatus,
)

HYPERLTL_BACKEND_VERSION: Final = "HyperLTLBackend@1"
AUTOHYPER_BACKEND_VERSION: Final = "AutoHyperBackend@1"
MCHYPER_BACKEND_VERSION: Final = "MCHyperBackend@1"
HYPERPROPERTY_BACKEND_FAMILY_VERSION: Final = "HyperpropertyBackends@1"

HYPER_ENGINE_CAPABILITY_VERSION: Final = "hyperproperty-engine-capability/v1"
HYPER_TRANSLATION_VERSION: Final = "hyperproperty-translation/v1"
HYPER_COUNTEREXAMPLE_VERSION: Final = "hyperproperty-counterexample/v1"
HYPER_CHECK_RECEIPT_VERSION: Final = "hyperproperty-check-receipt/v1"
HYPER_SOURCE_BINDING_VERSION: Final = "hyperproperty-source-binding/v1"

DEFAULT_VERSION_TIMEOUT_SECONDS: Final = 3.0
DEFAULT_MAX_OUTPUT_BYTES: Final = 2 * 1024 * 1024
DEFAULT_MAX_ALTERNATIONS_HYPERLTL: Final = 4
DEFAULT_MAX_ALTERNATIONS_AUTOHYPER: Final = 2
DEFAULT_MAX_ALTERNATIONS_MCHYPER: Final = 2

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SUCCESS_MARKERS: Final = (
    "holds",
    "verified",
    "satisfied",
    "sat",
    "true",
    "no violation",
    "property holds",
)
_VIOLATION_MARKERS: Final = (
    "violated",
    "violation",
    "counterexample",
    "falsified",
    "unsat",
    "does not hold",
    "property violated",
)
_UNSUPPORTED_MARKERS: Final = (
    "unsupported alternation",
    "unsupported quantifier",
    "too many alternations",
    "quantifier alternation not supported",
    "fragment not supported",
)


class HyperpropertyAdapterError(ValueError):
    """Raised when a hyperproperty request or adapter result violates the contract."""


class HyperEngine(StrEnum):
    """External HyperLTL-family engines with independent capability surfaces."""

    HYPERLTL = "hyperltl"
    AUTOHYPER = "autohyper"
    MCHYPER = "mchyper"


class HyperCheckOutcomeStatus(StrEnum):
    """Operational classification of one hyperproperty check."""

    SATISFIED = "satisfied"
    VIOLATED = "violated"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    ERROR = "error"
    MALFORMED = "malformed"


class HyperEvidencePath(StrEnum):
    """Which execution path produced the outcome.

    Fallback is never an external-tool proof.  Engine results are still
    hyperproperty-authority (not theorem) and remain loss-aware.
    """

    ENGINE = "engine"
    BOUNDED_SELF_COMPOSITION = "bounded_self_composition"
    NONE = "none"


ExecutableFinder = Callable[[str], str | None]


def _text(value: object, field_name: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        qualifier = "an empty or " if optional else "a "
        raise HyperpropertyAdapterError(
            f"{field_name} must be {qualifier}non-empty trimmed string without NUL bytes"
        )
    return value


def _source_text(value: object, field_name: str, *, optional: bool = False) -> str:
    """Validate multi-line source that may end with a trailing newline."""

    if optional and value in ("", None):
        return ""
    if not isinstance(value, str) or "\x00" in value:
        raise HyperpropertyAdapterError(
            f"{field_name} must be text without NUL bytes"
        )
    if not optional and not value.strip():
        raise HyperpropertyAdapterError(
            f"{field_name} must be non-empty text without NUL bytes"
        )
    return value


def _digest(value: object, field_name: str) -> str:
    text = _text(value, field_name)
    candidate = text.removeprefix("sha256:")
    if not _DIGEST.fullmatch(candidate):
        raise HyperpropertyAdapterError(
            f"{field_name} must be a lowercase SHA-256 digest"
        )
    return candidate


def _enum(value: object, enum_type: type[StrEnum], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(str(value))
    except (TypeError, ValueError) as error:
        choices = ", ".join(item.value for item in enum_type)
        raise HyperpropertyAdapterError(
            f"{field_name} must be one of {choices}"
        ) from error


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise HyperpropertyAdapterError(f"{field_name} must be a positive integer")
    return value


def _non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HyperpropertyAdapterError(
            f"{field_name} must be a non-negative integer"
        )
    return value


def _bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise HyperpropertyAdapterError(f"{field_name} must be a boolean")
    return value


def _content_digest(payload: Mapping[str, Any] | str) -> str:
    if isinstance(payload, str):
        return stable_digest({"content": payload})
    return stable_digest(dict(payload))


def quantifier_alternation_count(prefix: Sequence[QuantifierBinding]) -> int:
    """Count quantifier alternations (forall/exists switches) in declaration order."""

    if not prefix:
        return 0
    count = 0
    previous = prefix[0].quantifier
    for binding in prefix[1:]:
        if binding.quantifier is not previous:
            count += 1
            previous = binding.quantifier
    return count


def _document_from_value(value: object) -> HyperpropertyIR:
    if isinstance(value, HyperpropertyIR):
        return value
    if isinstance(value, Mapping):
        try:
            return HyperpropertyIR.from_dict(value)
        except HyperpropertyValidationError as error:
            raise HyperpropertyAdapterError(str(error)) from error
    raise HyperpropertyAdapterError(
        "document must be a HyperpropertyIR or mapping"
    )


@dataclass(frozen=True, slots=True)
class HyperEngineCapability:
    """Tool-specific discovery and bound disclosure for one hyperproperty engine."""

    engine: HyperEngine
    backend_version: str
    executable_candidates: tuple[str, ...]
    max_quantifier_alternations: int
    max_trace_variables: int
    supports_exists_forall: bool
    supports_forall_exists: bool
    supports_self_composition_fallback: bool
    limitations: tuple[str, ...]
    schema_version: str = HYPER_ENGINE_CAPABILITY_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "engine", _enum(self.engine, HyperEngine, "engine"))
        object.__setattr__(
            self, "backend_version", _text(self.backend_version, "backend_version")
        )
        candidates = tuple(
            _text(item, "executable candidate") for item in self.executable_candidates
        )
        if not candidates:
            raise HyperpropertyAdapterError(
                "executable_candidates must not be empty"
            )
        if len(candidates) != len(set(candidates)):
            raise HyperpropertyAdapterError(
                "executable_candidates must not contain duplicates"
            )
        object.__setattr__(self, "executable_candidates", candidates)
        object.__setattr__(
            self,
            "max_quantifier_alternations",
            _non_negative_int(
                self.max_quantifier_alternations, "max_quantifier_alternations"
            ),
        )
        object.__setattr__(
            self,
            "max_trace_variables",
            _positive_int(self.max_trace_variables, "max_trace_variables"),
        )
        for name in (
            "supports_exists_forall",
            "supports_forall_exists",
            "supports_self_composition_fallback",
        ):
            object.__setattr__(self, name, _bool(getattr(self, name), name))
        object.__setattr__(
            self,
            "limitations",
            tuple(_text(item, "limitation") for item in self.limitations),
        )
        if self.schema_version != HYPER_ENGINE_CAPABILITY_VERSION:
            raise HyperpropertyAdapterError(
                f"unsupported capability schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_version": self.backend_version,
            "engine": self.engine.value,
            "executable_candidates": list(self.executable_candidates),
            "limitations": list(self.limitations),
            "max_quantifier_alternations": self.max_quantifier_alternations,
            "max_trace_variables": self.max_trace_variables,
            "schema_version": self.schema_version,
            "supports_exists_forall": self.supports_exists_forall,
            "supports_forall_exists": self.supports_forall_exists,
            "supports_self_composition_fallback": self.supports_self_composition_fallback,
        }


HYPERLTL_CAPABILITY: Final = HyperEngineCapability(
    engine=HyperEngine.HYPERLTL,
    backend_version=HYPERLTL_BACKEND_VERSION,
    executable_candidates=("hyperltl", "hyperltl-sat"),
    max_quantifier_alternations=DEFAULT_MAX_ALTERNATIONS_HYPERLTL,
    max_trace_variables=8,
    supports_exists_forall=True,
    supports_forall_exists=True,
    supports_self_composition_fallback=True,
    limitations=(
        "HyperLTL checks remain model-bounded; a holds outcome is not a theorem proof.",
        "Private/high inputs are never serialized into counterexample witnesses.",
        "Bounded self-composition fallback is non-authoritative and is not engine proof.",
    ),
)

AUTOHYPER_CAPABILITY: Final = HyperEngineCapability(
    engine=HyperEngine.AUTOHYPER,
    backend_version=AUTOHYPER_BACKEND_VERSION,
    executable_candidates=("AutoHyper", "autohyper"),
    max_quantifier_alternations=DEFAULT_MAX_ALTERNATIONS_AUTOHYPER,
    max_trace_variables=4,
    supports_exists_forall=True,
    supports_forall_exists=False,
    supports_self_composition_fallback=True,
    limitations=(
        "AutoHyper targets automata-based HyperLTL fragments with limited alternation.",
        "exists-forall prefixes beyond the declared alternation ceiling are unsupported.",
        "A successful AutoHyper run never grants theorem authority.",
        "Bounded self-composition fallback is non-authoritative and is not engine proof.",
    ),
)

MCHYPER_CAPABILITY: Final = HyperEngineCapability(
    engine=HyperEngine.MCHYPER,
    backend_version=MCHYPER_BACKEND_VERSION,
    executable_candidates=("mchyper", "MCHyper"),
    max_quantifier_alternations=DEFAULT_MAX_ALTERNATIONS_MCHYPER,
    max_trace_variables=4,
    supports_exists_forall=False,
    supports_forall_exists=True,
    supports_self_composition_fallback=True,
    limitations=(
        "MCHyper checks model-checking HyperLTL under finite system models only.",
        "forall-exists prefixes beyond the declared alternation ceiling are unsupported.",
        "A successful MCHyper run is hyperproperty evidence, never an unbounded proof.",
        "Bounded self-composition fallback is non-authoritative and is not engine proof.",
    ),
)


@dataclass(frozen=True, slots=True)
class ObservationMap:
    """Ordered observation projection that must survive translation and replay."""

    policy_id: str
    low_input_fields: tuple[str, ...]
    high_input_fields: tuple[str, ...]
    observation_fields: tuple[str, ...]
    subject_fields: tuple[str, ...]
    observation_kinds: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _text(self.policy_id, "policy_id"))
        object.__setattr__(
            self,
            "low_input_fields",
            tuple(_text(item, "low input field") for item in self.low_input_fields),
        )
        object.__setattr__(
            self,
            "high_input_fields",
            tuple(_text(item, "high input field") for item in self.high_input_fields),
        )
        object.__setattr__(
            self,
            "observation_fields",
            tuple(
                _text(item, "observation field") for item in self.observation_fields
            ),
        )
        object.__setattr__(
            self,
            "subject_fields",
            tuple(_text(item, "subject field") for item in self.subject_fields),
        )
        if not isinstance(self.observation_kinds, Mapping):
            raise HyperpropertyAdapterError("observation_kinds must be a mapping")
        kinds = {
            _text(key, "observation kind key"): _text(
                value, f"observation kind for {key}"
            )
            for key, value in self.observation_kinds.items()
        }
        object.__setattr__(self, "observation_kinds", FrozenMap(kinds).to_dict())

    @classmethod
    def from_document(cls, document: HyperpropertyIR) -> ObservationMap:
        policy = document.information_flow_policy
        kinds = {
            item.field: item.kind.value for item in policy.observations
        } or {field_name: "output" for field_name in policy.observation_fields}
        return cls(
            policy_id=policy.policy_id,
            low_input_fields=policy.low_input_fields,
            high_input_fields=policy.high_input_fields,
            observation_fields=policy.observation_fields,
            subject_fields=policy.subject_fields,
            observation_kinds=kinds,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "high_input_fields": list(self.high_input_fields),
            "low_input_fields": list(self.low_input_fields),
            "observation_fields": list(self.observation_fields),
            "observation_kinds": dict(self.observation_kinds),
            "policy_id": self.policy_id,
            "subject_fields": list(self.subject_fields),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ObservationMap:
        if not isinstance(value, Mapping):
            raise HyperpropertyAdapterError("observation map must be a mapping")
        return cls(
            policy_id=value.get("policy_id", ""),
            low_input_fields=tuple(value.get("low_input_fields") or ()),
            high_input_fields=tuple(value.get("high_input_fields") or ()),
            observation_fields=tuple(value.get("observation_fields") or ()),
            subject_fields=tuple(value.get("subject_fields") or ()),
            observation_kinds=dict(value.get("observation_kinds") or {}),
        )


@dataclass(frozen=True, slots=True)
class QuantifierOrder:
    """Exact quantifier prefix that must survive translation without reordering."""

    signature: tuple[str, ...]
    variable_ids: tuple[str, ...]
    variable_names: tuple[str, ...]
    bindings: tuple[dict[str, Any], ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "signature",
            tuple(_text(item, "quantifier") for item in self.signature),
        )
        object.__setattr__(
            self,
            "variable_ids",
            tuple(_text(item, "variable id") for item in self.variable_ids),
        )
        object.__setattr__(
            self,
            "variable_names",
            tuple(_text(item, "variable name") for item in self.variable_names),
        )
        if not (
            len(self.signature)
            == len(self.variable_ids)
            == len(self.variable_names)
            == len(self.bindings)
        ):
            raise HyperpropertyAdapterError(
                "quantifier order components must have equal length"
            )
        object.__setattr__(
            self,
            "bindings",
            tuple(dict(item) for item in self.bindings),
        )

    @classmethod
    def from_document(cls, document: HyperpropertyIR) -> QuantifierOrder:
        formula = document.formula
        names_by_id = {item.variable_id: item.name for item in formula.variables}
        return cls(
            signature=formula.quantifier_signature,
            variable_ids=tuple(
                item.variable_id for item in formula.quantifier_prefix
            ),
            variable_names=tuple(
                names_by_id[item.variable_id] for item in formula.quantifier_prefix
            ),
            bindings=tuple(item.to_dict() for item in formula.quantifier_prefix),
        )

    def matches_document(self, document: HyperpropertyIR) -> bool:
        formula = document.formula
        if self.signature != formula.quantifier_signature:
            return False
        if self.variable_ids != tuple(
            item.variable_id for item in formula.quantifier_prefix
        ):
            return False
        restored = tuple(
            QuantifierBinding.from_dict(item) for item in self.bindings
        )
        return quantifier_order_is_canonical(restored, formula.quantifier_prefix)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bindings": [dict(item) for item in self.bindings],
            "signature": list(self.signature),
            "variable_ids": list(self.variable_ids),
            "variable_names": list(self.variable_names),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> QuantifierOrder:
        if not isinstance(value, Mapping):
            raise HyperpropertyAdapterError("quantifier order must be a mapping")
        return cls(
            signature=tuple(value.get("signature") or ()),
            variable_ids=tuple(value.get("variable_ids") or ()),
            variable_names=tuple(value.get("variable_names") or ()),
            bindings=tuple(value.get("bindings") or ()),
        )


@dataclass(frozen=True, slots=True)
class HyperpropertyTranslation:
    """Engine input package with order-preserving quantifiers and observations."""

    engine: HyperEngine
    translator_id: str
    formula_text: str
    quantifier_order: QuantifierOrder
    observation_map: ObservationMap
    document_digest: str
    formula_id: str
    matrix_statement: str
    auxiliary_files: Mapping[str, str] = field(default_factory=dict)
    losses: tuple[str, ...] = ()
    schema_version: str = HYPER_TRANSLATION_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "engine", _enum(self.engine, HyperEngine, "engine"))
        object.__setattr__(
            self, "translator_id", _text(self.translator_id, "translator_id")
        )
        object.__setattr__(
            self, "formula_text", _source_text(self.formula_text, "formula_text")
        )
        if not isinstance(self.quantifier_order, QuantifierOrder):
            raise HyperpropertyAdapterError(
                "quantifier_order must be a QuantifierOrder"
            )
        if not isinstance(self.observation_map, ObservationMap):
            raise HyperpropertyAdapterError(
                "observation_map must be an ObservationMap"
            )
        object.__setattr__(
            self, "document_digest", _digest(self.document_digest, "document_digest")
        )
        object.__setattr__(self, "formula_id", _text(self.formula_id, "formula_id"))
        object.__setattr__(
            self,
            "matrix_statement",
            _text(self.matrix_statement, "matrix_statement"),
        )
        if not isinstance(self.auxiliary_files, Mapping):
            raise HyperpropertyAdapterError("auxiliary_files must be a mapping")
        aux = {
            _text(key, "auxiliary file name"): _source_text(
                value, f"auxiliary file {key}", optional=True
            )
            for key, value in self.auxiliary_files.items()
        }
        object.__setattr__(self, "auxiliary_files", FrozenMap(aux).to_dict())
        object.__setattr__(
            self,
            "losses",
            tuple(_text(item, "loss") for item in self.losses),
        )
        if self.schema_version != HYPER_TRANSLATION_VERSION:
            raise HyperpropertyAdapterError(
                f"unsupported translation schema: {self.schema_version!r}"
            )

    @property
    def translation_digest(self) -> str:
        return _content_digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "auxiliary_files": dict(self.auxiliary_files),
            "document_digest": self.document_digest,
            "engine": self.engine.value,
            "formula_id": self.formula_id,
            "formula_text": self.formula_text,
            "losses": list(self.losses),
            "matrix_statement": self.matrix_statement,
            "observation_map": self.observation_map.to_dict(),
            "quantifier_order": self.quantifier_order.to_dict(),
            "schema_version": self.schema_version,
            "translator_id": self.translator_id,
        }
        if include_digest:
            payload["translation_digest"] = self.translation_digest
        return payload


@dataclass(frozen=True, slots=True)
class HyperCounterexampleTrace:
    """One redacted multi-trace counterexample with observation-map replay notes."""

    formula_id: str
    observation_policy_id: str
    observed_fields: tuple[str, ...]
    traces: tuple[WitnessTrace, ...]
    differences: tuple[ObservationDifference, ...]
    raw: str = ""
    replayed: bool = False
    replay_notes: tuple[str, ...] = ()
    schema_version: str = HYPER_COUNTEREXAMPLE_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "formula_id", _text(self.formula_id, "formula_id"))
        object.__setattr__(
            self,
            "observation_policy_id",
            _text(self.observation_policy_id, "observation_policy_id"),
        )
        object.__setattr__(
            self,
            "observed_fields",
            tuple(_text(item, "observed field") for item in self.observed_fields),
        )
        object.__setattr__(self, "traces", tuple(self.traces))
        if not self.traces:
            raise HyperpropertyAdapterError(
                "counterexample requires at least one redacted witness trace"
            )
        for item in self.traces:
            if not isinstance(item, WitnessTrace):
                raise HyperpropertyAdapterError(
                    "counterexample traces must be WitnessTrace values"
                )
        object.__setattr__(self, "differences", tuple(self.differences))
        for item in self.differences:
            if not isinstance(item, ObservationDifference):
                raise HyperpropertyAdapterError(
                    "differences must be ObservationDifference values"
                )
        object.__setattr__(
            self, "raw", _source_text(self.raw, "raw", optional=True)
        )
        object.__setattr__(self, "replayed", _bool(self.replayed, "replayed"))
        object.__setattr__(
            self,
            "replay_notes",
            tuple(_text(item, "replay note") for item in self.replay_notes),
        )
        if self.schema_version != HYPER_COUNTEREXAMPLE_VERSION:
            raise HyperpropertyAdapterError(
                f"unsupported counterexample schema: {self.schema_version!r}"
            )

    def to_witness_bundle(
        self,
        *,
        bundle_id: str = "bundle:engine-counterexample",
    ) -> WitnessTraceBundle:
        return WitnessTraceBundle(
            bundle_id=bundle_id,
            role=WitnessRole.COUNTEREXAMPLE,
            formula_id=self.formula_id,
            traces=self.traces,
            differences=self.differences,
            observed_fields=self.observed_fields,
            description="Engine counterexample with redacted high inputs",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "differences": [item.to_dict() for item in self.differences],
            "formula_id": self.formula_id,
            "observation_policy_id": self.observation_policy_id,
            "observed_fields": list(self.observed_fields),
            "raw": self.raw,
            "replay_notes": list(self.replay_notes),
            "replayed": self.replayed,
            "schema_version": self.schema_version,
            "traces": [item.to_dict() for item in self.traces],
        }


@dataclass(frozen=True, slots=True)
class FallbackBoundDisclosure:
    """Explicit finite bounds used by the non-authoritative self-composition path."""

    max_traces: int
    max_pairs: int
    max_steps: int | None
    bound_id: str
    authoritative: bool = False
    external_tool_proof: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "max_traces", _positive_int(self.max_traces, "max_traces")
        )
        object.__setattr__(
            self, "max_pairs", _positive_int(self.max_pairs, "max_pairs")
        )
        if self.max_steps is not None:
            object.__setattr__(
                self, "max_steps", _positive_int(self.max_steps, "max_steps")
            )
        object.__setattr__(self, "bound_id", _text(self.bound_id, "bound_id"))
        object.__setattr__(
            self, "authoritative", _bool(self.authoritative, "authoritative")
        )
        object.__setattr__(
            self,
            "external_tool_proof",
            _bool(self.external_tool_proof, "external_tool_proof"),
        )
        if self.authoritative or self.external_tool_proof:
            raise HyperpropertyAdapterError(
                "self-composition fallback cannot claim authority or external-tool proof"
            )

    @classmethod
    def from_bound(cls, bound: SelfCompositionBound) -> FallbackBoundDisclosure:
        return cls(
            max_traces=bound.max_traces,
            max_pairs=bound.max_pairs,
            max_steps=bound.max_steps,
            bound_id=bound.bound_id,
            authoritative=False,
            external_tool_proof=False,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authoritative": False,
            "bound_id": self.bound_id,
            "external_tool_proof": False,
            "max_pairs": self.max_pairs,
            "max_steps": self.max_steps,
            "max_traces": self.max_traces,
        }


@dataclass(frozen=True, slots=True)
class HyperCheckReceipt:
    """Self-contained receipt for one exact hyperproperty check."""

    engine: HyperEngine
    status: HyperCheckOutcomeStatus
    evidence_path: HyperEvidencePath
    document_digest: str
    translation_digest: str
    executable: str
    tool_version: str
    command: tuple[str, ...]
    capability: HyperEngineCapability
    quantifier_order: QuantifierOrder
    observation_map: ObservationMap
    returncode: int | None
    stdout: str
    stderr: str
    elapsed_ms: int
    timeout_seconds: float
    output_truncated: bool
    reason: str
    counterexample: HyperCounterexampleTrace | None = None
    fallback_bounds: FallbackBoundDisclosure | None = None
    authorizes_universal_proof: bool = False
    schema_version: str = HYPER_CHECK_RECEIPT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "engine", _enum(self.engine, HyperEngine, "engine"))
        object.__setattr__(
            self, "status", _enum(self.status, HyperCheckOutcomeStatus, "status")
        )
        object.__setattr__(
            self,
            "evidence_path",
            _enum(self.evidence_path, HyperEvidencePath, "evidence_path"),
        )
        object.__setattr__(
            self, "document_digest", _digest(self.document_digest, "document_digest")
        )
        object.__setattr__(
            self,
            "translation_digest",
            _digest(self.translation_digest, "translation_digest"),
        )
        object.__setattr__(
            self, "executable", _text(self.executable, "executable", optional=True)
        )
        object.__setattr__(
            self,
            "tool_version",
            _text(self.tool_version, "tool_version", optional=True),
        )
        object.__setattr__(self, "command", tuple(str(item) for item in self.command))
        if not isinstance(self.capability, HyperEngineCapability):
            raise HyperpropertyAdapterError(
                "capability must be a HyperEngineCapability"
            )
        if not isinstance(self.quantifier_order, QuantifierOrder):
            raise HyperpropertyAdapterError(
                "quantifier_order must be a QuantifierOrder"
            )
        if not isinstance(self.observation_map, ObservationMap):
            raise HyperpropertyAdapterError(
                "observation_map must be an ObservationMap"
            )
        if (
            isinstance(self.elapsed_ms, bool)
            or not isinstance(self.elapsed_ms, int)
            or self.elapsed_ms < 0
        ):
            raise HyperpropertyAdapterError(
                "elapsed_ms must be a non-negative integer"
            )
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or self.timeout_seconds <= 0
        ):
            raise HyperpropertyAdapterError(
                "timeout_seconds must be a positive number"
            )
        object.__setattr__(
            self, "output_truncated", _bool(self.output_truncated, "output_truncated")
        )
        object.__setattr__(self, "reason", _text(self.reason, "reason"))
        object.__setattr__(
            self, "stdout", _source_text(self.stdout, "stdout", optional=True)
        )
        object.__setattr__(
            self, "stderr", _source_text(self.stderr, "stderr", optional=True)
        )
        if self.counterexample is not None and not isinstance(
            self.counterexample, HyperCounterexampleTrace
        ):
            raise HyperpropertyAdapterError(
                "counterexample must be a HyperCounterexampleTrace"
            )
        if self.fallback_bounds is not None and not isinstance(
            self.fallback_bounds, FallbackBoundDisclosure
        ):
            raise HyperpropertyAdapterError(
                "fallback_bounds must be a FallbackBoundDisclosure"
            )
        object.__setattr__(
            self,
            "authorizes_universal_proof",
            _bool(self.authorizes_universal_proof, "authorizes_universal_proof"),
        )
        if self.authorizes_universal_proof:
            raise HyperpropertyAdapterError(
                "hyperproperty receipts cannot authorize universal proof"
            )
        if (
            self.evidence_path is HyperEvidencePath.BOUNDED_SELF_COMPOSITION
            and self.fallback_bounds is None
        ):
            raise HyperpropertyAdapterError(
                "fallback evidence requires explicit fallback bounds"
            )
        if (
            self.evidence_path is HyperEvidencePath.ENGINE
            and self.status is HyperCheckOutcomeStatus.SATISFIED
            and not self.executable
        ):
            raise HyperpropertyAdapterError(
                "engine satisfaction requires a resolved executable"
            )
        if self.schema_version != HYPER_CHECK_RECEIPT_VERSION:
            raise HyperpropertyAdapterError(
                f"unsupported receipt schema: {self.schema_version!r}"
            )

    @property
    def external_tool_proof(self) -> bool:
        """Fallback and non-engine paths never count as external-tool proof."""

        return self.evidence_path is HyperEvidencePath.ENGINE and self.status in {
            HyperCheckOutcomeStatus.SATISFIED,
            HyperCheckOutcomeStatus.VIOLATED,
        }

    @property
    def receipt_id(self) -> str:
        return (
            "hyperproperty-check-receipt:"
            f"{stable_digest(self.to_dict(include_id=False))}"
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload = {
            "authorizes_universal_proof": False,
            "capability": self.capability.to_dict(),
            "command": list(self.command),
            "counterexample": (
                self.counterexample.to_dict()
                if self.counterexample is not None
                else None
            ),
            "document_digest": self.document_digest,
            "elapsed_ms": self.elapsed_ms,
            "engine": self.engine.value,
            "evidence_path": self.evidence_path.value,
            "executable": self.executable,
            "external_tool_proof": self.external_tool_proof,
            "fallback_bounds": (
                self.fallback_bounds.to_dict()
                if self.fallback_bounds is not None
                else None
            ),
            "observation_map": self.observation_map.to_dict(),
            "output_truncated": self.output_truncated,
            "quantifier_order": self.quantifier_order.to_dict(),
            "reason": self.reason,
            "returncode": self.returncode,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "stderr": self.stderr,
            "stdout": self.stdout,
            "timeout_seconds": self.timeout_seconds,
            "tool_version": self.tool_version,
            "translation_digest": self.translation_digest,
        }
        if include_id:
            payload["receipt_id"] = self.receipt_id
        return payload


@dataclass(frozen=True, slots=True)
class HyperCheckOutcome:
    """Normalized hyperproperty result plus the exact receipt."""

    request_digest: str
    result: HyperpropertyResult
    receipt: HyperCheckReceipt
    translation: HyperpropertyTranslation | None = None
    interface_version: str = HYPERPROPERTY_BACKEND_FAMILY_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        if not isinstance(self.result, HyperpropertyResult):
            raise HyperpropertyAdapterError("result must be a HyperpropertyResult")
        if not isinstance(self.receipt, HyperCheckReceipt):
            raise HyperpropertyAdapterError("receipt must be a HyperCheckReceipt")
        if self.translation is not None and not isinstance(
            self.translation, HyperpropertyTranslation
        ):
            raise HyperpropertyAdapterError(
                "translation must be a HyperpropertyTranslation"
            )
        if self.interface_version not in {
            HYPERPROPERTY_BACKEND_FAMILY_VERSION,
            HYPERLTL_BACKEND_VERSION,
            AUTOHYPER_BACKEND_VERSION,
            MCHYPER_BACKEND_VERSION,
        }:
            raise HyperpropertyAdapterError(
                f"unsupported interface version: {self.interface_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface_version": self.interface_version,
            "receipt": self.receipt.to_dict(),
            "request_digest": self.request_digest,
            "result": self.result.to_dict(),
            "translation": (
                self.translation.to_dict() if self.translation is not None else None
            ),
        }


def render_hyperltl_formula(
    document: HyperpropertyIR,
    *,
    engine: HyperEngine,
) -> str:
    """Render HyperLTL-style text without reordering quantifiers or observations.

    The rendered formula is intentionally engine-neutral textual HyperLTL.  Any
    engine-specific packaging (for example AutoHyper explicit systems) is added
    as auxiliary files by :meth:`HyperpropertyBackend.translate`.
    """

    if not isinstance(document, HyperpropertyIR):
        raise HyperpropertyAdapterError("document must be a HyperpropertyIR")
    formula = document.formula
    policy = document.information_flow_policy
    names_by_id = {item.variable_id: item.name for item in formula.variables}
    ordered_names = [
        names_by_id[item.variable_id] for item in formula.quantifier_prefix
    ]
    quantifiers = " ".join(
        f"{binding.quantifier.value} {names_by_id[binding.variable_id]}."
        for binding in formula.quantifier_prefix
    )
    low = ", ".join(policy.low_input_fields) or "true"
    obs = ", ".join(policy.observation_fields) or "true"
    if len(ordered_names) >= 2:
        left, right = ordered_names[0], ordered_names[1]
        body = (
            f"G (({{{low}}}_{{{left}}} = {{{low}}}_{{{right}}}) -> "
            f"({{{obs}}}_{{{left}}} = {{{obs}}}_{{{right}}}))"
        )
    else:
        body = formula.matrix_statement
    header = (
        f"; engine={engine.value}\n"
        f"; formula_id={formula.formula_id}\n"
        f"; quantifier_signature={','.join(formula.quantifier_signature)}\n"
        f"; observation_fields={','.join(policy.observation_fields)}\n"
    )
    return header + f"{quantifiers} {body}\n"


def _autohyper_explicit_system(document: HyperpropertyIR) -> str:
    """Minimal explicit system package for AutoHyper-style tooling."""

    policy = document.information_flow_policy
    low = policy.low_input_fields[0] if policy.low_input_fields else "low"
    obs = policy.observation_fields[0] if policy.observation_fields else "obs"
    return (
        f'Variables: ("{low}" Bool) ("{obs}" Bool)\n'
        "Init: 0 1\n"
        "--BODY--\n"
        f'State: 0 {{("{low}" false) ("{obs}" false)}}\n'
        "0\n"
        f'State: 1 {{("{low}" true) ("{obs}" true)}}\n'
        "1\n"
        "--END--\n"
    )


def parse_hyper_counterexample(
    output: str,
    *,
    formula_id: str,
    observation_map: ObservationMap,
    quantifier_order: QuantifierOrder,
) -> HyperCounterexampleTrace | None:
    """Parse multi-trace counterexample blocks from engine stdout/stderr.

    Recognized forms::

        TRACE pi1:
          public.user_id = alice
          obs.status = ok
        TRACE pi2:
          public.user_id = alice
          obs.status = leak

        DIFF field=status left=... right=...
    """

    text = str(output or "")
    if not text.strip():
        return None
    trace_pattern = re.compile(
        r"(?ms)^TRACE\s+([A-Za-z0-9_.:/-]+)\s*:\s*\n(.*?)(?=^TRACE\s|\Z)"
    )
    parsed: list[WitnessTrace] = []
    for index, match in enumerate(trace_pattern.finditer(text)):
        name = match.group(1).strip()
        body = match.group(2)
        public_inputs: dict[str, str] = {}
        observations: dict[str, str] = {}
        subject: dict[str, str] = {}
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key.startswith("public."):
                public_inputs[key.removeprefix("public.")] = value
            elif key.startswith("obs."):
                observations[key.removeprefix("obs.")] = value
            elif key.startswith("subject."):
                subject[key.removeprefix("subject.")] = value
            elif key in observation_map.observation_fields:
                observations[key] = value
            elif key in observation_map.low_input_fields:
                public_inputs[key] = value
            elif key in observation_map.subject_fields:
                subject[key] = value
        variable_id = (
            quantifier_order.variable_ids[index]
            if index < len(quantifier_order.variable_ids)
            else f"var:{name}"
        )
        # Prefer declared variable names when the TRACE label matches them.
        for offset, declared_name in enumerate(quantifier_order.variable_names):
            if declared_name == name and offset < len(quantifier_order.variable_ids):
                variable_id = quantifier_order.variable_ids[offset]
                break
        parsed.append(
            WitnessTrace.from_execution(
                trace_id=f"trace:{name}",
                variable_id=variable_id,
                public_inputs=public_inputs,
                observations=observations,
                subject=subject,
            )
        )

    if not parsed:
        return None

    differences: list[ObservationDifference] = []
    for match in re.finditer(
        r"(?m)^DIFF\s+field=(\S+)\s+left=(\S+)\s+right=(\S+)\s*$",
        text,
    ):
        field_name = match.group(1)
        left_raw = match.group(2)
        right_raw = match.group(3)
        differences.append(
            ObservationDifference(
                field=field_name,
                left_digest="sha256:" + _content_digest(left_raw),
                right_digest="sha256:" + _content_digest(right_raw),
            )
        )

    if not differences and len(parsed) >= 2:
        left, right = parsed[0], parsed[1]
        for field_name in observation_map.observation_fields:
            left_value = dict(left.observations).get(field_name)
            right_value = dict(right.observations).get(field_name)
            if left_value != right_value:
                differences.append(
                    ObservationDifference(
                        field=field_name,
                        left_digest="sha256:"
                        + _content_digest(
                            "" if left_value is None else str(left_value)
                        ),
                        right_digest="sha256:"
                        + _content_digest(
                            "" if right_value is None else str(right_value)
                        ),
                    )
                )
                break

    if not differences:
        # Still return a parseable multi-trace tuple so callers can replay structure.
        differences = (
            ObservationDifference(
                field=observation_map.observation_fields[0]
                if observation_map.observation_fields
                else "observation",
                left_digest="sha256:" + _content_digest("left"),
                right_digest="sha256:" + _content_digest("right"),
            ),
        )

    return HyperCounterexampleTrace(
        formula_id=formula_id,
        observation_policy_id=observation_map.policy_id,
        observed_fields=observation_map.observation_fields,
        traces=tuple(parsed),
        differences=tuple(differences),
        raw=text,
        replayed=False,
        replay_notes=(),
    )


def replay_hyper_counterexample(
    counterexample: HyperCounterexampleTrace,
    observation_map: ObservationMap,
    quantifier_order: QuantifierOrder,
) -> HyperCounterexampleTrace:
    """Replay a parsed multi-trace counterexample against the observation map.

    Replay is structural: every observation key and TRACE variable must match
    the translation package.  Missing or extra keys become notes; success is
    never invented.
    """

    if not isinstance(counterexample, HyperCounterexampleTrace):
        raise HyperpropertyAdapterError(
            "counterexample must be a HyperCounterexampleTrace"
        )
    notes: list[str] = []
    approved = set(observation_map.observation_fields)
    low_inputs = set(observation_map.low_input_fields)
    subjects = set(observation_map.subject_fields)
    declared_names = set(quantifier_order.variable_names)
    declared_ids = set(quantifier_order.variable_ids)

    if len(counterexample.traces) != len(quantifier_order.variable_ids):
        notes.append(
            "trace arity "
            f"{len(counterexample.traces)} does not match quantifier arity "
            f"{len(quantifier_order.variable_ids)}"
        )

    for index, trace in enumerate(counterexample.traces):
        unknown_obs = sorted(set(trace.observations) - approved)
        if unknown_obs:
            notes.append(
                f"trace {trace.trace_id}: unapproved observation keys: "
                + ", ".join(unknown_obs)
            )
        known_obs = sorted(set(trace.observations) & approved)
        if known_obs:
            notes.append(
                f"trace {trace.trace_id}: replayed observations: "
                + ", ".join(known_obs)
            )
        unknown_public = sorted(set(trace.public_inputs) - low_inputs)
        if unknown_public:
            notes.append(
                f"trace {trace.trace_id}: public keys outside low-input map: "
                + ", ".join(unknown_public)
            )
        unknown_subject = sorted(set(trace.subject) - subjects) if subjects else ()
        if unknown_subject:
            notes.append(
                f"trace {trace.trace_id}: subject keys outside subject map: "
                + ", ".join(unknown_subject)
            )
        if (
            trace.variable_id not in declared_ids
            and index < len(quantifier_order.variable_ids)
        ):
            notes.append(
                f"trace {trace.trace_id}: variable_id {trace.variable_id} "
                "does not match quantifier order"
            )
        # TRACE ids may use names; note whether the name is declared.
        label = trace.trace_id.removeprefix("trace:")
        if label not in declared_names and trace.variable_id not in declared_ids:
            notes.append(
                f"trace {trace.trace_id}: label is not in quantifier variable names"
            )

    for difference in counterexample.differences:
        if difference.field not in approved and approved:
            notes.append(
                f"difference field {difference.field!r} is not an approved observation"
            )
        else:
            notes.append(f"difference field {difference.field!r} is approved")

    if not notes:
        notes.append("counterexample structure matches observation and quantifier maps")

    return HyperCounterexampleTrace(
        formula_id=counterexample.formula_id,
        observation_policy_id=counterexample.observation_policy_id,
        observed_fields=counterexample.observed_fields,
        traces=counterexample.traces,
        differences=counterexample.differences,
        raw=counterexample.raw,
        replayed=True,
        replay_notes=tuple(notes),
    )


class HyperpropertyBackend:
    """Shared lifecycle for HyperLTL-family external tools and fallback."""

    engine: HyperEngine
    backend_id: str
    backend_version: str
    capability: HyperEngineCapability

    def __init__(
        self,
        *,
        runner: BoundedToolRunner | None = None,
        which: ExecutableFinder = shutil.which,
        executable: str | None = None,
    ) -> None:
        self._runner = runner or BoundedToolRunner()
        self._which = which
        self._executable = executable

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            logic_families=(
                "hyperproperty",
                "information_flow",
                "software_verification",
                self.engine.value,
            ),
            query_kinds=(QueryKind.SATISFIABILITY,),
            deterministic=True,
        )

    def engine_capability(self) -> HyperEngineCapability:
        return self.capability

    def is_available(self) -> bool:
        return self.resolve_executable() != ""

    def resolve_executable(self) -> str:
        if self._executable:
            return str(self._executable)
        for candidate in self.capability.executable_candidates:
            path = self._which(candidate)
            if path:
                return path
        return ""

    def probe(self) -> ToolProbe:
        executable = self.resolve_executable()
        available = bool(executable)
        reason = ""
        if not available:
            reason = (
                f"{self.engine.value} executable unavailable; looked for "
                + ", ".join(self.capability.executable_candidates)
            )
        return ToolProbe(
            runtime=ToolRuntime.NATIVE,
            requested_executable=self.capability.executable_candidates[0],
            available=available,
            executable_path=executable if available else "",
            reason=reason,
        )

    def supports_prefix(self, document: HyperpropertyIR) -> tuple[bool, str]:
        """Whether the engine can accept the document's quantifier prefix."""

        formula = document.formula
        alternations = quantifier_alternation_count(formula.quantifier_prefix)
        if formula.trace_cardinality > self.capability.max_trace_variables:
            return (
                False,
                (
                    f"{self.engine.value} supports at most "
                    f"{self.capability.max_trace_variables} trace variables; "
                    f"got {formula.trace_cardinality}"
                ),
            )
        if alternations > self.capability.max_quantifier_alternations:
            return (
                False,
                (
                    f"{self.engine.value} supports at most "
                    f"{self.capability.max_quantifier_alternations} quantifier "
                    f"alternations; got {alternations}"
                ),
            )
        signature = formula.quantifier_signature
        if "exists" in signature and "forall" in signature:
            first_exists = signature.index("exists")
            first_forall = signature.index("forall")
            if first_exists < first_forall and not self.capability.supports_exists_forall:
                return (
                    False,
                    f"{self.engine.value} does not support exists-forall prefixes",
                )
            if first_forall < first_exists and not self.capability.supports_forall_exists:
                return (
                    False,
                    f"{self.engine.value} does not support forall-exists prefixes",
                )
        return True, ""

    def translate(self, document: HyperpropertyIR) -> HyperpropertyTranslation:
        document = _document_from_value(document)
        supported, reason = self.supports_prefix(document)
        losses: list[str] = list(self.capability.limitations)
        if not supported:
            # Translation still materializes so callers can inspect order maps,
            # but check() will return UNSUPPORTED before execution.
            losses.append(reason)
        formula_text = render_hyperltl_formula(document, engine=self.engine)
        auxiliary: dict[str, str] = {
            "observation_map.json": json.dumps(
                ObservationMap.from_document(document).to_dict(),
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            "quantifier_order.json": json.dumps(
                QuantifierOrder.from_document(document).to_dict(),
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
        }
        if self.engine is HyperEngine.AUTOHYPER:
            auxiliary["system.explicit"] = _autohyper_explicit_system(document)
        return HyperpropertyTranslation(
            engine=self.engine,
            translator_id=f"datasets-{self.engine.value}@1",
            formula_text=formula_text,
            quantifier_order=QuantifierOrder.from_document(document),
            observation_map=ObservationMap.from_document(document),
            document_digest=stable_digest(document.semantic_dict()),
            formula_id=document.formula.formula_id,
            matrix_statement=document.formula.matrix_statement,
            auxiliary_files=auxiliary,
            losses=tuple(losses),
        )

    def check(
        self,
        document: HyperpropertyIR,
        *,
        request: BackendRequest | None = None,
        traces: Sequence[ExecutionTrace] | None = None,
        allow_fallback: bool = False,
        cancellation: CancellationSignal | None = None,
    ) -> HyperCheckOutcome:
        document = _document_from_value(document)
        translation = self.translate(document)
        request_digest = (
            request.digest
            if request is not None
            else translation.document_digest
        )
        bounds = (
            request.bounds
            if request is not None
            else ExecutionBounds(timeout_ms=10_000, max_steps=1_000)
        )

        supported, unsupported_reason = self.supports_prefix(document)
        if not supported:
            receipt = self._terminal_receipt(
                document=document,
                translation=translation,
                status=HyperCheckOutcomeStatus.UNSUPPORTED,
                evidence_path=HyperEvidencePath.NONE,
                reason=unsupported_reason,
                bounds=bounds,
            )
            return HyperCheckOutcome(
                request_digest=request_digest,
                result=self._result_from_receipt(
                    receipt, request=request, bounds=bounds
                ),
                receipt=receipt,
                translation=translation,
                interface_version=self.backend_version,
            )

        probe = self.probe()
        if not probe.available:
            if allow_fallback and self.capability.supports_self_composition_fallback:
                return self._fallback_outcome(
                    document,
                    translation=translation,
                    request=request,
                    request_digest=request_digest,
                    bounds=bounds,
                    traces=traces,
                    unavailable_reason=probe.reason
                    or f"{self.engine.value} executable unavailable",
                )
            receipt = self._terminal_receipt(
                document=document,
                translation=translation,
                status=HyperCheckOutcomeStatus.UNAVAILABLE,
                evidence_path=HyperEvidencePath.NONE,
                reason=probe.reason
                or f"{self.engine.value} executable unavailable; no check ran",
                bounds=bounds,
            )
            return HyperCheckOutcome(
                request_digest=request_digest,
                result=self._result_from_receipt(
                    receipt, request=request, bounds=bounds
                ),
                receipt=receipt,
                translation=translation,
                interface_version=self.backend_version,
            )

        executable = probe.executable_path
        timeout_seconds = max(0.001, bounds.timeout_ms / 1000.0)
        formula_name = "property.hltl"
        input_files: dict[str, str] = {formula_name: translation.formula_text}
        input_files.update(
            {name: text for name, text in translation.auxiliary_files.items()}
        )
        if self.engine is HyperEngine.AUTOHYPER:
            argv = (
                executable,
                "--explicit",
                "system.explicit",
                formula_name,
            )
        else:
            argv = (executable, formula_name)

        limits = ToolRunLimits(
            timeout_seconds=timeout_seconds,
            max_output_bytes=min(bounds.max_output_bytes, DEFAULT_MAX_OUTPUT_BYTES),
            max_input_bytes=max(
                len(translation.formula_text.encode("utf-8")),
                4096,
            ),
        )
        process = self._runner.run(
            ToolRunRequest(
                argv=argv,
                runtime=ToolRuntime.NATIVE,
                limits=limits,
                input_files=input_files,
                output_paths=("counterexample.txt", "witness.txt"),
            ),
            cancellation=cancellation,
        )
        version = self._tool_version(executable)
        combined = "\n".join(
            part for part in (process.stdout, process.stderr) if part
        )
        status, reason = self._classify(process, combined)
        counterexample: HyperCounterexampleTrace | None = None
        if status is HyperCheckOutcomeStatus.VIOLATED:
            supplemental = ""
            for name in ("counterexample.txt", "witness.txt"):
                raw = process.output_files.get(name)
                if raw:
                    supplemental = raw.decode("utf-8", errors="replace")
                    break
            parsed = parse_hyper_counterexample(
                supplemental or combined,
                formula_id=document.formula.formula_id,
                observation_map=translation.observation_map,
                quantifier_order=translation.quantifier_order,
            )
            if parsed is not None:
                counterexample = replay_hyper_counterexample(
                    parsed,
                    translation.observation_map,
                    translation.quantifier_order,
                )
            else:
                reason = (
                    reason
                    + "; counterexample markers present but no multi-trace "
                    "tuple could be parsed"
                )

        receipt = HyperCheckReceipt(
            engine=self.engine,
            status=status,
            evidence_path=HyperEvidencePath.ENGINE,
            document_digest=translation.document_digest,
            translation_digest=translation.translation_digest,
            executable=executable,
            tool_version=version,
            command=tuple(str(arg) for arg in argv),
            capability=self.capability,
            quantifier_order=translation.quantifier_order,
            observation_map=translation.observation_map,
            returncode=process.returncode,
            stdout=process.stdout,
            stderr=process.stderr,
            elapsed_ms=max(0, round(process.elapsed_seconds * 1000)),
            timeout_seconds=timeout_seconds,
            output_truncated=process.output_truncated,
            reason=reason,
            counterexample=counterexample,
            fallback_bounds=None,
            authorizes_universal_proof=False,
        )
        return HyperCheckOutcome(
            request_digest=request_digest,
            result=self._result_from_receipt(
                receipt, request=request, bounds=bounds
            ),
            receipt=receipt,
            translation=translation,
            interface_version=self.backend_version,
        )

    def run(
        self,
        request: BackendRequest,
        *,
        cancellation: CancellationSignal | None = None,
    ) -> HyperCheckOutcome:
        if not isinstance(request, BackendRequest):
            raise HyperpropertyAdapterError("request must be a BackendRequest")
        payload = request.payload.to_dict()
        document = payload.get("document") or payload.get("hyperproperty")
        if document is None:
            raise HyperpropertyAdapterError(
                "request payload must include document or hyperproperty"
            )
        traces_payload = payload.get("traces") or ()
        traces: list[ExecutionTrace] = []
        for item in traces_payload:
            if isinstance(item, ExecutionTrace):
                traces.append(item)
            elif isinstance(item, Mapping):
                traces.append(
                    ExecutionTrace(
                        trace_id=str(item.get("trace_id", "")),
                        public_inputs=dict(item.get("public_inputs") or {}),
                        observations=dict(item.get("observations") or {}),
                        private_inputs=dict(item.get("private_inputs") or {}),
                        subject=dict(item.get("subject") or {}),
                    )
                )
            else:
                raise HyperpropertyAdapterError(
                    "traces must be ExecutionTrace values or mappings"
                )
        allow_fallback = bool(payload.get("allow_fallback", False))
        return self.check(
            document,
            request=request,
            traces=tuple(traces),
            allow_fallback=allow_fallback,
            cancellation=cancellation,
        )

    def _fallback_outcome(
        self,
        document: HyperpropertyIR,
        *,
        translation: HyperpropertyTranslation,
        request: BackendRequest | None,
        request_digest: str,
        bounds: ExecutionBounds,
        traces: Sequence[ExecutionTrace] | None,
        unavailable_reason: str,
    ) -> HyperCheckOutcome:
        bound = document.self_composition_bound
        disclosure = FallbackBoundDisclosure.from_bound(bound)
        if traces is None:
            receipt = self._terminal_receipt(
                document=document,
                translation=translation,
                status=HyperCheckOutcomeStatus.UNAVAILABLE,
                evidence_path=HyperEvidencePath.NONE,
                reason=(
                    f"{unavailable_reason}; fallback requested but no traces "
                    "were supplied for bounded self-composition"
                ),
                bounds=bounds,
                fallback_bounds=disclosure,
            )
            return HyperCheckOutcome(
                request_digest=request_digest,
                result=self._result_from_receipt(
                    receipt, request=request, bounds=bounds
                ),
                receipt=receipt,
                translation=translation,
                interface_version=self.backend_version,
            )

        try:
            evaluation = document.evaluate_bounded_noninterference(traces)
        except HyperpropertyValidationError as error:
            receipt = self._terminal_receipt(
                document=document,
                translation=translation,
                status=HyperCheckOutcomeStatus.UNSUPPORTED,
                evidence_path=HyperEvidencePath.BOUNDED_SELF_COMPOSITION,
                reason=(
                    f"bounded self-composition unavailable for this formula: {error}"
                ),
                bounds=bounds,
                fallback_bounds=disclosure,
            )
            return HyperCheckOutcome(
                request_digest=request_digest,
                result=self._result_from_receipt(
                    receipt, request=request, bounds=bounds
                ),
                receipt=receipt,
                translation=translation,
                interface_version=self.backend_version,
            )

        if evaluation.verdict is HyperpropertyVerdict.VIOLATED:
            status = HyperCheckOutcomeStatus.VIOLATED
        elif evaluation.verdict is HyperpropertyVerdict.HOLDS:
            # Bounded holds are inconclusive for universal claims.
            status = HyperCheckOutcomeStatus.UNKNOWN
        else:
            status = HyperCheckOutcomeStatus.UNKNOWN

        counterexample: HyperCounterexampleTrace | None = None
        if evaluation.witness_bundle is not None and evaluation.verdict is HyperpropertyVerdict.VIOLATED:
            bundle = evaluation.witness_bundle
            counterexample = HyperCounterexampleTrace(
                formula_id=bundle.formula_id,
                observation_policy_id=document.information_flow_policy.policy_id,
                observed_fields=bundle.observed_fields,
                traces=bundle.traces,
                differences=bundle.differences,
                raw="",
                replayed=True,
                replay_notes=(
                    "fallback counterexample from bounded self-composition",
                    "not an external-tool proof",
                ),
            )

        reason = (
            f"{unavailable_reason}; used non-authoritative bounded self-composition "
            f"with max_traces={disclosure.max_traces}, max_pairs={disclosure.max_pairs}: "
            f"{evaluation.reason}"
        )
        receipt = HyperCheckReceipt(
            engine=self.engine,
            status=status,
            evidence_path=HyperEvidencePath.BOUNDED_SELF_COMPOSITION,
            document_digest=translation.document_digest,
            translation_digest=translation.translation_digest,
            executable="",
            tool_version="",
            command=(),
            capability=self.capability,
            quantifier_order=translation.quantifier_order,
            observation_map=translation.observation_map,
            returncode=None,
            stdout="",
            stderr="",
            elapsed_ms=0,
            timeout_seconds=max(0.001, bounds.timeout_ms / 1000.0),
            output_truncated=False,
            reason=reason,
            counterexample=counterexample,
            fallback_bounds=disclosure,
            authorizes_universal_proof=False,
        )
        return HyperCheckOutcome(
            request_digest=request_digest,
            result=self._result_from_receipt(
                receipt, request=request, bounds=bounds
            ),
            receipt=receipt,
            translation=translation,
            interface_version=self.backend_version,
        )

    def _terminal_receipt(
        self,
        *,
        document: HyperpropertyIR,
        translation: HyperpropertyTranslation,
        status: HyperCheckOutcomeStatus,
        evidence_path: HyperEvidencePath,
        reason: str,
        bounds: ExecutionBounds,
        fallback_bounds: FallbackBoundDisclosure | None = None,
    ) -> HyperCheckReceipt:
        return HyperCheckReceipt(
            engine=self.engine,
            status=status,
            evidence_path=evidence_path,
            document_digest=translation.document_digest,
            translation_digest=translation.translation_digest,
            executable="",
            tool_version="",
            command=(),
            capability=self.capability,
            quantifier_order=translation.quantifier_order,
            observation_map=translation.observation_map,
            returncode=None,
            stdout="",
            stderr="",
            elapsed_ms=0,
            timeout_seconds=max(0.001, bounds.timeout_ms / 1000.0),
            output_truncated=False,
            reason=reason,
            counterexample=None,
            fallback_bounds=fallback_bounds,
            authorizes_universal_proof=False,
        )

    def _classify(
        self, process: ToolRunResult, combined: str
    ) -> tuple[HyperCheckOutcomeStatus, str]:
        if process.unavailable:
            return (
                HyperCheckOutcomeStatus.UNAVAILABLE,
                "executable became unavailable during run",
            )
        if process.timed_out:
            return (
                HyperCheckOutcomeStatus.TIMEOUT,
                f"{self.engine.value} timed out under declared bounds",
            )
        if process.cancelled:
            return (
                HyperCheckOutcomeStatus.ERROR,
                f"{self.engine.value} run was cancelled",
            )
        folded = combined.casefold()
        if any(marker in folded for marker in _UNSUPPORTED_MARKERS):
            return (
                HyperCheckOutcomeStatus.UNSUPPORTED,
                f"{self.engine.value} reported unsupported quantifier/fragment",
            )
        if any(marker in folded for marker in _VIOLATION_MARKERS):
            return (
                HyperCheckOutcomeStatus.VIOLATED,
                f"{self.engine.value} reported a hyperproperty violation",
            )
        if process.returncode == 0 and any(
            marker in folded for marker in _SUCCESS_MARKERS
        ):
            return (
                HyperCheckOutcomeStatus.SATISFIED,
                f"{self.engine.value} reported the hyperproperty holds under its model",
            )
        if process.returncode not in (0, None) and not combined.strip():
            return (
                HyperCheckOutcomeStatus.ERROR,
                f"{self.engine.value} exited with code {process.returncode}",
            )
        if process.output_truncated:
            return (
                HyperCheckOutcomeStatus.UNKNOWN,
                f"{self.engine.value} output was truncated before a verdict",
            )
        return (
            HyperCheckOutcomeStatus.UNKNOWN,
            f"{self.engine.value} completed without a recognized verdict",
        )

    def _tool_version(self, executable: str) -> str:
        try:
            result = self._runner.run(
                ToolRunRequest(
                    argv=(executable, "--version"),
                    runtime=ToolRuntime.NATIVE,
                    limits=ToolRunLimits(
                        timeout_seconds=DEFAULT_VERSION_TIMEOUT_SECONDS,
                        max_output_bytes=16_384,
                    ),
                )
            )
        except Exception:  # pragma: no cover - defensive
            return ""
        if result.unavailable or result.timed_out:
            return ""
        text = (result.stdout or result.stderr or "").strip().splitlines()
        return text[0][:200] if text else ""

    def _result_from_receipt(
        self,
        receipt: HyperCheckReceipt,
        *,
        request: BackendRequest | None,
        bounds: ExecutionBounds,
    ) -> HyperpropertyResult:
        status_map = {
            HyperCheckOutcomeStatus.SATISFIED: ResultStatus.SATISFIED,
            HyperCheckOutcomeStatus.VIOLATED: ResultStatus.VIOLATED,
            HyperCheckOutcomeStatus.UNKNOWN: ResultStatus.UNKNOWN,
            HyperCheckOutcomeStatus.TIMEOUT: ResultStatus.TIMEOUT,
            HyperCheckOutcomeStatus.UNAVAILABLE: ResultStatus.UNAVAILABLE,
            HyperCheckOutcomeStatus.UNSUPPORTED: ResultStatus.UNSUPPORTED,
            HyperCheckOutcomeStatus.ERROR: ResultStatus.ERROR,
            HyperCheckOutcomeStatus.MALFORMED: ResultStatus.MALFORMED,
        }
        witness: dict[str, Any] = {
            "evidence_path": receipt.evidence_path.value,
            "engine": receipt.engine.value,
            "external_tool_proof": receipt.external_tool_proof,
            "authorizes_universal_proof": False,
            "quantifier_order": receipt.quantifier_order.to_dict(),
            "observation_map": receipt.observation_map.to_dict(),
            "receipt_id": receipt.receipt_id,
        }
        if receipt.counterexample is not None:
            witness["counterexample"] = receipt.counterexample.to_dict()
            witness["witness_bundle"] = (
                receipt.counterexample.to_witness_bundle().to_dict()
            )
        if receipt.fallback_bounds is not None:
            witness["fallback_bounds"] = receipt.fallback_bounds.to_dict()
            witness["evidence_kind"] = (
                HyperpropertyEvidenceKind.BOUNDED_SELF_COMPOSITION.value
            )
        elif receipt.evidence_path is HyperEvidencePath.ENGINE:
            witness["evidence_kind"] = "hyperproperty_engine"
        else:
            witness["evidence_kind"] = "none"

        result_id = (
            f"hyperproperty-result:{stable_digest({'receipt': receipt.receipt_id})}"
        )
        return HyperpropertyResult(
            result_id=result_id,
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            authority=ResultAuthority.HYPERPROPERTY,
            status=status_map[receipt.status],
            assumptions=tuple(request.assumption_ids) if request is not None else (),
            bounds=bounds,
            translation_ceiling=EvidenceAuthority.BOUNDED,
            usage=ResourceUsage(
                elapsed_ms=receipt.elapsed_ms,
                steps=0,
                peak_memory_bytes=0,
                output_bytes=len(receipt.stdout.encode("utf-8"))
                + len(receipt.stderr.encode("utf-8")),
            ),
            witness=FrozenMap(witness),
            diagnostics=tuple(receipt.capability.limitations[:3]),
            reason=receipt.reason,
            metadata=FrozenMap(
                {
                    "engine": receipt.engine.value,
                    "evidence_path": receipt.evidence_path.value,
                    "external_tool_proof": receipt.external_tool_proof,
                }
            ),
        )


class HyperLTLBackend(HyperpropertyBackend):
    """``HyperLTLBackend@1`` external HyperLTL checker."""

    engine = HyperEngine.HYPERLTL
    backend_id = "hyperltl"
    backend_version = HYPERLTL_BACKEND_VERSION
    capability = HYPERLTL_CAPABILITY


class AutoHyperBackend(HyperpropertyBackend):
    """``AutoHyperBackend@1`` automata-based HyperLTL checker."""

    engine = HyperEngine.AUTOHYPER
    backend_id = "autohyper"
    backend_version = AUTOHYPER_BACKEND_VERSION
    capability = AUTOHYPER_CAPABILITY


class MCHyperBackend(HyperpropertyBackend):
    """``MCHyperBackend@1`` model-checking HyperLTL checker."""

    engine = HyperEngine.MCHYPER
    backend_id = "mchyper"
    backend_version = MCHYPER_BACKEND_VERSION
    capability = MCHYPER_CAPABILITY


DEFAULT_HYPERPROPERTY_BACKENDS: Final = (
    HyperLTLBackend,
    AutoHyperBackend,
    MCHyperBackend,
)


def probe_hyperproperty_backends(
    backends: Sequence[HyperpropertyBackend] | None = None,
) -> tuple[ToolProbe, ...]:
    """Probe every engine independently; discovery never implies a proof."""

    selected = (
        tuple(backends)
        if backends is not None
        else tuple(backend_type() for backend_type in DEFAULT_HYPERPROPERTY_BACKENDS)
    )
    probes = tuple(backend.probe() for backend in selected)
    engines = [backend.engine for backend in selected]
    if len(engines) != len(set(engines)):
        raise HyperpropertyAdapterError("hyperproperty backends must be unique")
    return probes


__all__ = [
    "AUTOHYPER_BACKEND_VERSION",
    "AUTOHYPER_CAPABILITY",
    "DEFAULT_HYPERPROPERTY_BACKENDS",
    "DEFAULT_MAX_COMPOSITION_PAIRS",
    "DEFAULT_MAX_COMPOSITION_TRACES",
    "HYPERLTL_BACKEND_VERSION",
    "HYPERLTL_CAPABILITY",
    "HYPERPROPERTY_BACKEND_FAMILY_VERSION",
    "MCHYPER_BACKEND_VERSION",
    "MCHYPER_CAPABILITY",
    "AutoHyperBackend",
    "FallbackBoundDisclosure",
    "HyperCheckOutcome",
    "HyperCheckOutcomeStatus",
    "HyperCheckReceipt",
    "HyperCounterexampleTrace",
    "HyperEngine",
    "HyperEngineCapability",
    "HyperEvidencePath",
    "HyperLTLBackend",
    "HyperpropertyAdapterError",
    "HyperpropertyBackend",
    "HyperpropertyTranslation",
    "MCHyperBackend",
    "ObservationMap",
    "QuantifierOrder",
    "parse_hyper_counterexample",
    "probe_hyperproperty_backends",
    "quantifier_alternation_count",
    "render_hyperltl_formula",
    "replay_hyper_counterexample",
]
