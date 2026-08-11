"""Split AutoHyper / MCHyper / HyperLTL capability paths (LFP2-032).

Interface: ``HyperProviderEvidence@2``

Runs typed hyperproperty checks through independent engine surfaces:

* AutoHyper, MCHyper, and HyperLTL each own discovery, quantifier ceilings,
  system-model requirements, and witness replay;
* one engine's support **never** establishes another's capability;
* every result binds engine identity, system model, formula, finite bounds,
  and witness status; and
* fallback / mock / availability / confidence never grant theorem authority.

Hyperproperty evidence remains bounded (never universal proof).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.hyperproperties.adapters import (
    AUTOHYPER_CAPABILITY,
    HYPERLTL_CAPABILITY,
    MCHYPER_CAPABILITY,
    AutoHyperBackend,
    FallbackBoundDisclosure,
    HyperCheckOutcome,
    HyperCheckOutcomeStatus,
    HyperCounterexampleTrace,
    HyperEngine,
    HyperEngineCapability,
    HyperEvidencePath,
    HyperLTLBackend,
    HyperpropertyAdapterError,
    HyperpropertyBackend,
    HyperpropertyTranslation,
    MCHyperBackend,
    ObservationMap,
    QuantifierOrder,
    quantifier_alternation_count,
)
from ipfs_datasets_py.logic.backends.process import BoundedToolRunner
from ipfs_datasets_py.logic.backends.results import (
    HyperpropertyResult,
    ResultAuthority,
    ResultStatus,
)
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.families.namespaces import (
    LogicIdentity,
    evidence_id,
    lane_id,
    provider_id,
)
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
from ipfs_datasets_py.logic.software_verification.hyperproperties import (
    ExecutionTrace,
    HyperpropertyIR,
    HyperpropertyValidationError,
    SelfCompositionBound,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    SyntaxContractError,
    _freeze_mapping,
    _record_id,
    _require_mapping,
    _require_sequence,
    _sha256_hex,
    _text,
    _thaw_mapping,
    canonical_json_bytes,
    content_sha256,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

HYPER_PROVIDER_EVIDENCE_V2_INTERFACE: Final = "HyperProviderEvidence@2"
HYPER_EXECUTION_REQUEST_V2_INTERFACE: Final = "HyperExecutionRequest@2"
HYPER_EXECUTION_RESULT_V2_INTERFACE: Final = "HyperExecutionResult@2"
HYPER_FORMULA_BINDING_V2_INTERFACE: Final = "HyperFormulaBinding@2"
HYPER_SYSTEM_BINDING_V2_INTERFACE: Final = "HyperSystemBinding@2"
HYPER_BOUNDS_BINDING_V2_INTERFACE: Final = "HyperBoundsBinding@2"
HYPER_WITNESS_BINDING_V2_INTERFACE: Final = "HyperWitnessBinding@2"
HYPER_CAPABILITY_RECEIPT_V2_INTERFACE: Final = "HyperCapabilityReceipt@2"

HYPER_PROVIDER_EVIDENCE_SCHEMA: Final = "hyper-provider-evidence/v2"
HYPER_EXECUTION_REQUEST_SCHEMA: Final = "hyper-execution-request/v2"
HYPER_EXECUTION_RESULT_SCHEMA: Final = "hyper-execution-result/v2"
HYPER_FORMULA_BINDING_SCHEMA: Final = "hyper-formula-binding/v2"
HYPER_SYSTEM_BINDING_SCHEMA: Final = "hyper-system-binding/v2"
HYPER_BOUNDS_BINDING_SCHEMA: Final = "hyper-bounds-binding/v2"
HYPER_WITNESS_BINDING_SCHEMA: Final = "hyper-witness-binding/v2"
HYPER_CAPABILITY_RECEIPT_SCHEMA: Final = "hyper-capability-receipt/v2"

HYPER_EXECUTION_V2_MODULE_VERSION: Final = "1.0.0"
HYPER_EXECUTION_V2_TASK_ID: Final = "LFP2-032"
HYPER_EXECUTION_V2_GOAL_ID: Final = "LFP2-G060"

HYPER_LANE_ID: Final = "hyperproperty"
HYPER_EVIDENCE_KIND: Final = "hyperproperty"

_MAX_DIAGNOSTICS: Final = 64
_MAX_METADATA_BYTES: Final = 8_192
_MAX_SOURCE_REFS: Final = 64
_MAX_SYSTEM_BYTES: Final = 1_048_576

_FORBIDDEN_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "arbitrary_payload",
        "claimed_execution",
        "claimed_proof",
        "execution_result",
        "fake_replay",
        "family_string",
        "free_form_family",
        "is_proved",
        "logic_family",
        "mock_execution",
        "mock_result",
        "opaque_extension",
        "payload",
        "proof_result",
        "proof_status",
        "proved",
        "raw_formula",
        "raw_result",
        "raw_source",
        "solver_result",
        "target_source",
        "theorem_status",
        "verification_result",
        "verification_status",
    }
)

_NON_AUTHORITATIVE_SIGNAL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "availability",
        "available",
        "confidence",
        "fallback",
        "fallback_output",
        "fluent_text",
        "is_valid",
        "mock",
        "mock_output",
        "similarity",
    }
)

# Canonical capability tables — independent; never cross-copied.
_ENGINE_CAPABILITIES: Final[Mapping[HyperEngine, HyperEngineCapability]] = {
    HyperEngine.HYPERLTL: HYPERLTL_CAPABILITY,
    HyperEngine.AUTOHYPER: AUTOHYPER_CAPABILITY,
    HyperEngine.MCHYPER: MCHYPER_CAPABILITY,
}


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


class HyperExecutionError(SyntaxContractError):
    """Raised when hyperproperty execution v2 inputs are malformed."""


class HyperAuthorityError(HyperExecutionError):
    """Raised when a claim would exceed the hyperproperty authority ceiling."""


class HyperProviderKind(StrEnum):
    """Closed set of hyperproperty engines with independent capability paths."""

    HYPERLTL = "hyperltl"
    AUTOHYPER = "autohyper"
    MCHYPER = "mchyper"


class HyperExecutionMode(StrEnum):
    """How the hyperproperty outcome was produced.

    Only ``engine`` may establish hyperproperty (bounded) evidence.
    ``fallback`` and ``mock`` never do.  ``capability_probe`` only reports
    per-engine discovery and never grants a holds/violated verdict.
    """

    ENGINE = "engine"
    FALLBACK = "fallback"
    MOCK = "mock"
    CAPABILITY_PROBE = "capability_probe"


class HyperDisposition(StrEnum):
    """Closed set of hyperproperty execution dispositions."""

    SATISFIED = "satisfied"
    VIOLATED = "violated"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    ERROR = "error"
    MALFORMED = "malformed"
    MOCK_REJECTED = "mock_rejected"
    FALLBACK_REJECTED = "fallback_rejected"
    BOUNDS_EXHAUSTED = "bounds_exhausted"
    CAPABILITY_ONLY = "capability_only"


class HyperWitnessStatus(StrEnum):
    """Witness attachment status bound into every result."""

    NONE = "none"
    ABSENT = "absent"
    COUNTEREXAMPLE_REPLAYED = "counterexample_replayed"
    COUNTEREXAMPLE_UNREPLAYABLE = "counterexample_unreplayable"
    CLEAN_SAMPLE = "clean_sample"
    FALLBACK_WITNESS = "fallback_witness"


class HyperSystemKind(StrEnum):
    """Closed system-model kinds per engine path."""

    NONE = "none"
    EXPLICIT = "explicit"
    AIGER = "aiger"
    BOUNDED_SELF_COMPOSITION = "bounded_self_composition"


class HyperClaimKind(StrEnum):
    """Claims that mock / fallback / other-engine support must never establish."""

    HYPERPROPERTY = "hyperproperty"
    PROOF = "proof"
    SATISFIABILITY = "satisfiability"
    THEOREM = "theorem"
    OTHER_ENGINE_CAPABILITY = "other_engine_capability"


class HyperSemanticsKind(StrEnum):
    """Finite / bounded semantics declared on every answer."""

    ENGINE_BOUNDED = "engine_bounded"
    FALLBACK_BOUNDED = "fallback_bounded"
    FINITE_BOUNDED = "finite_bounded"
    CAPABILITY_ONLY = "capability_only"
    NONE = "none"


_PROVIDER_ALIASES: Final[dict[str, HyperProviderKind]] = {
    "hyperltl": HyperProviderKind.HYPERLTL,
    "hyper_ltl": HyperProviderKind.HYPERLTL,
    "eahyper": HyperProviderKind.HYPERLTL,
    "autohyper": HyperProviderKind.AUTOHYPER,
    "auto_hyper": HyperProviderKind.AUTOHYPER,
    "mchyper": HyperProviderKind.MCHYPER,
    "mc_hyper": HyperProviderKind.MCHYPER,
}


def normalize_hyper_provider(
    value: HyperProviderKind | HyperEngine | str,
) -> HyperProviderKind:
    """Normalize provider labels into the closed hyperproperty provider set."""

    if isinstance(value, HyperProviderKind):
        return value
    if isinstance(value, HyperEngine):
        return HyperProviderKind(value.value)
    key = str(value).strip().lower().replace("-", "_")
    if key not in _PROVIDER_ALIASES:
        raise HyperExecutionError(
            f"unsupported hyper provider: {value!r}; "
            f"expected hyperltl, autohyper, or mchyper"
        )
    return _PROVIDER_ALIASES[key]


def provider_to_engine(provider: HyperProviderKind) -> HyperEngine:
    return HyperEngine(provider.value)


def engine_to_provider(engine: HyperEngine) -> HyperProviderKind:
    return HyperProviderKind(engine.value)


def provider_logic_identity(provider: HyperProviderKind) -> LogicIdentity:
    """Return the canonical provider identity for matrix / evidence binding."""

    return provider_id(provider.value)


def capability_for(provider: HyperProviderKind | HyperEngine | str) -> HyperEngineCapability:
    """Return the independent capability declaration for one engine only."""

    kind = normalize_hyper_provider(provider)
    return _ENGINE_CAPABILITIES[provider_to_engine(kind)]


def engine_support_establishes_other(
    source: HyperProviderKind | HyperEngine | str,
    target: HyperProviderKind | HyperEngine | str,
    *,
    source_available: bool = True,
    source_supported: bool = True,
) -> bool:
    """Whether *source* support establishes *target* capability.

    Always ``False`` when engines differ (LFP2-032 acceptance).  Same-engine
    identity is not a cross-engine transfer.
    """

    del source_available, source_supported
    src = normalize_hyper_provider(source)
    dst = normalize_hyper_provider(target)
    if src is not dst:
        return False
    # Same engine: support is still not "establishing another's capability".
    return False


def non_authoritative_signal_establishes(
    claim: HyperClaimKind | str,
    *,
    mock_output: object = None,
    fallback_output: object = None,
    available: bool | None = None,
    confidence: float | None = None,
    fluent_text: str | None = None,
    other_engine_available: bool | None = None,
) -> bool:
    """Always ``False``: mock / fallback / availability cannot establish claims."""

    del (
        claim,
        mock_output,
        fallback_output,
        available,
        confidence,
        fluent_text,
        other_engine_available,
    )
    return False


# ---------------------------------------------------------------------------
# Primitive validators
# ---------------------------------------------------------------------------


def _enum(value: object, enum_type: type[StrEnum], field_name: str) -> StrEnum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value).strip())
    except (TypeError, ValueError) as error:
        allowed = ", ".join(item.value for item in enum_type)
        raise HyperExecutionError(
            f"{field_name} must be one of: {allowed}; got {value!r}"
        ) from error


def _optional_bool(value: object, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise HyperExecutionError(f"{field_name} must be a boolean")


def _digest_of(payload: Mapping[str, Any]) -> str:
    return content_sha256(canonical_json_bytes(dict(payload)))


def _source_ref_ids(
    value: object, field_name: str = "source_ref_ids"
) -> tuple[str, ...]:
    items = _require_sequence(value, field_name)
    if len(items) > _MAX_SOURCE_REFS:
        raise HyperExecutionError(
            f"{field_name} exceeds hard limit {_MAX_SOURCE_REFS}"
        )
    refs: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        ref = _record_id(item, f"{field_name}[{index}]")
        if ref not in seen:
            seen.add(ref)
            refs.append(ref)
    return tuple(refs)


def _forbid_authority_metadata(metadata: Mapping[str, Any], field_name: str) -> None:
    for key in metadata:
        if key in _FORBIDDEN_METADATA_KEYS or key in _NON_AUTHORITATIVE_SIGNAL_KEYS:
            raise HyperAuthorityError(
                f"{field_name} rejects free-form authority/signal key {key!r}; "
                "use typed hyper evidence fields only"
            )


def _document_from_value(value: object) -> HyperpropertyIR:
    if isinstance(value, HyperpropertyIR):
        return value
    if isinstance(value, Mapping):
        try:
            return HyperpropertyIR.from_dict(value)
        except (HyperpropertyValidationError, TypeError, ValueError) as error:
            raise HyperExecutionError(
                f"invalid hyperproperty document: {error}"
            ) from error
    raise HyperExecutionError("document must be HyperpropertyIR or mapping")


def _system_digest(system_model: bytes | str | None) -> str:
    if system_model is None:
        return ""
    if isinstance(system_model, bytes):
        raw = system_model
    elif isinstance(system_model, str):
        raw = system_model.encode("utf-8")
    else:
        raise HyperExecutionError("system_model must be bytes, text, or None")
    if len(raw) > _MAX_SYSTEM_BYTES:
        raise HyperExecutionError(
            f"system_model exceeds hard limit {_MAX_SYSTEM_BYTES} bytes"
        )
    return hashlib.sha256(raw).hexdigest()


def _system_kind_for(
    provider: HyperProviderKind,
    *,
    system_model: bytes | str | None,
    evidence_path: HyperEvidencePath | None = None,
) -> HyperSystemKind:
    if evidence_path is HyperEvidencePath.BOUNDED_SELF_COMPOSITION:
        return HyperSystemKind.BOUNDED_SELF_COMPOSITION
    if provider is HyperProviderKind.MCHYPER:
        return HyperSystemKind.AIGER if system_model is not None else HyperSystemKind.NONE
    if provider is HyperProviderKind.AUTOHYPER:
        return HyperSystemKind.EXPLICIT
    return HyperSystemKind.NONE


def _status_to_disposition(status: HyperCheckOutcomeStatus) -> HyperDisposition:
    mapping = {
        HyperCheckOutcomeStatus.SATISFIED: HyperDisposition.SATISFIED,
        HyperCheckOutcomeStatus.VIOLATED: HyperDisposition.VIOLATED,
        HyperCheckOutcomeStatus.UNKNOWN: HyperDisposition.UNKNOWN,
        HyperCheckOutcomeStatus.TIMEOUT: HyperDisposition.TIMEOUT,
        HyperCheckOutcomeStatus.UNAVAILABLE: HyperDisposition.UNAVAILABLE,
        HyperCheckOutcomeStatus.UNSUPPORTED: HyperDisposition.UNSUPPORTED,
        HyperCheckOutcomeStatus.ERROR: HyperDisposition.ERROR,
        HyperCheckOutcomeStatus.MALFORMED: HyperDisposition.MALFORMED,
    }
    return mapping[status]


def _status_to_result_status(status: HyperCheckOutcomeStatus) -> ResultStatus:
    mapping = {
        HyperCheckOutcomeStatus.SATISFIED: ResultStatus.SATISFIED,
        HyperCheckOutcomeStatus.VIOLATED: ResultStatus.VIOLATED,
        HyperCheckOutcomeStatus.UNKNOWN: ResultStatus.UNKNOWN,
        HyperCheckOutcomeStatus.TIMEOUT: ResultStatus.TIMEOUT,
        HyperCheckOutcomeStatus.UNAVAILABLE: ResultStatus.UNAVAILABLE,
        HyperCheckOutcomeStatus.UNSUPPORTED: ResultStatus.UNSUPPORTED,
        HyperCheckOutcomeStatus.ERROR: ResultStatus.ERROR,
        HyperCheckOutcomeStatus.MALFORMED: ResultStatus.MALFORMED,
    }
    return mapping[status]


def _witness_status_from(
    counterexample: HyperCounterexampleTrace | None,
    *,
    evidence_path: HyperEvidencePath,
    disposition: HyperDisposition,
) -> HyperWitnessStatus:
    if counterexample is not None:
        if counterexample.replayed:
            return HyperWitnessStatus.COUNTEREXAMPLE_REPLAYED
        return HyperWitnessStatus.COUNTEREXAMPLE_UNREPLAYABLE
    if evidence_path is HyperEvidencePath.BOUNDED_SELF_COMPOSITION:
        if disposition is HyperDisposition.VIOLATED:
            return HyperWitnessStatus.FALLBACK_WITNESS
        if disposition is HyperDisposition.SATISFIED:
            return HyperWitnessStatus.CLEAN_SAMPLE
        return HyperWitnessStatus.FALLBACK_WITNESS
    if disposition in {
        HyperDisposition.SATISFIED,
        HyperDisposition.VIOLATED,
    }:
        return HyperWitnessStatus.ABSENT
    return HyperWitnessStatus.NONE


# ---------------------------------------------------------------------------
# Bindings
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HyperFormulaBindingV2:
    """Formula identity and quantifier prefix bound into every answer.

    Interface: ``HyperFormulaBinding@2``.
    """

    formula_id: str
    formula_digest: str
    document_digest: str
    quantifier_signature: tuple[str, ...]
    quantifier_prefix: tuple[dict[str, Any], ...]
    matrix_statement: str
    alternation_count: int
    trace_cardinality: int
    formula_text: str = ""
    translation_digest: str = ""
    schema_version: str = HYPER_FORMULA_BINDING_SCHEMA

    interface: ClassVar[str] = HYPER_FORMULA_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "formula_id", _record_id(self.formula_id, "formula_id")
        )
        object.__setattr__(
            self,
            "formula_digest",
            _sha256_hex(self.formula_digest, "formula_digest"),
        )
        object.__setattr__(
            self,
            "document_digest",
            _sha256_hex(self.document_digest, "document_digest"),
        )
        signature = tuple(
            _text(item, f"quantifier_signature[{index}]", maximum=32)
            for index, item in enumerate(self.quantifier_signature)
        )
        object.__setattr__(self, "quantifier_signature", signature)
        prefix = tuple(
            dict(_require_mapping(item, f"quantifier_prefix[{index}]"))
            for index, item in enumerate(self.quantifier_prefix)
        )
        object.__setattr__(self, "quantifier_prefix", prefix)
        object.__setattr__(
            self,
            "matrix_statement",
            _text(self.matrix_statement, "matrix_statement", maximum=8_192),
        )
        if (
            isinstance(self.alternation_count, bool)
            or not isinstance(self.alternation_count, int)
            or self.alternation_count < 0
        ):
            raise HyperExecutionError(
                "alternation_count must be a non-negative integer"
            )
        if (
            isinstance(self.trace_cardinality, bool)
            or not isinstance(self.trace_cardinality, int)
            or self.trace_cardinality < 1
        ):
            raise HyperExecutionError(
                "trace_cardinality must be a positive integer"
            )
        if self.formula_text:
            if not isinstance(self.formula_text, str) or "\x00" in self.formula_text:
                raise HyperExecutionError(
                    "formula_text must be text without NUL bytes"
                )
        else:
            object.__setattr__(self, "formula_text", "")
        if self.translation_digest:
            object.__setattr__(
                self,
                "translation_digest",
                _sha256_hex(self.translation_digest, "translation_digest"),
            )
        else:
            object.__setattr__(self, "translation_digest", "")
        if self.schema_version != HYPER_FORMULA_BINDING_SCHEMA:
            raise HyperExecutionError(
                f"unsupported formula binding schema: {self.schema_version!r}"
            )

    @classmethod
    def from_document(
        cls,
        document: HyperpropertyIR,
        *,
        translation: HyperpropertyTranslation | None = None,
    ) -> HyperFormulaBindingV2:
        formula = document.formula
        formula_digest = content_sha256(
            canonical_json_bytes(formula.semantic_dict())
        )
        document_digest = (
            translation.document_digest
            if translation is not None
            else content_sha256(canonical_json_bytes(document.semantic_dict()))
        )
        order = (
            translation.quantifier_order
            if translation is not None
            else QuantifierOrder.from_document(document)
        )
        return cls(
            formula_id=formula.formula_id,
            formula_digest=formula_digest,
            document_digest=document_digest,
            quantifier_signature=tuple(order.signature),
            quantifier_prefix=tuple(dict(item) for item in order.bindings),
            matrix_statement=formula.matrix_statement,
            alternation_count=quantifier_alternation_count(
                formula.quantifier_prefix
            ),
            trace_cardinality=formula.trace_cardinality,
            formula_text=(
                translation.formula_text if translation is not None else ""
            ),
            translation_digest=(
                translation.translation_digest if translation is not None else ""
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "alternation_count": self.alternation_count,
            "document_digest": self.document_digest,
            "formula_digest": self.formula_digest,
            "formula_id": self.formula_id,
            "formula_text": self.formula_text,
            "interface": self.interface,
            "matrix_statement": self.matrix_statement,
            "quantifier_prefix": [dict(item) for item in self.quantifier_prefix],
            "quantifier_signature": list(self.quantifier_signature),
            "schema_version": self.schema_version,
            "trace_cardinality": self.trace_cardinality,
            "translation_digest": self.translation_digest,
        }


@dataclass(frozen=True, slots=True)
class HyperSystemBindingV2:
    """System-model identity required for the selected engine path.

    Interface: ``HyperSystemBinding@2``.
    """

    system_kind: HyperSystemKind | str
    system_digest: str
    system_id: str
    model_required: bool
    model_present: bool
    observation_policy_id: str = ""
    observation_map: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = HYPER_SYSTEM_BINDING_SCHEMA

    interface: ClassVar[str] = HYPER_SYSTEM_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "system_kind",
            _enum(self.system_kind, HyperSystemKind, "system_kind"),
        )
        if self.system_digest:
            object.__setattr__(
                self,
                "system_digest",
                _sha256_hex(self.system_digest, "system_digest"),
            )
        else:
            object.__setattr__(self, "system_digest", "")
        object.__setattr__(
            self,
            "system_id",
            _text(self.system_id, "system_id", allow_empty=True, maximum=256),
        )
        object.__setattr__(
            self, "model_required", _optional_bool(self.model_required, "model_required")
        )
        object.__setattr__(
            self, "model_present", _optional_bool(self.model_present, "model_present")
        )
        if self.observation_policy_id:
            object.__setattr__(
                self,
                "observation_policy_id",
                _record_id(self.observation_policy_id, "observation_policy_id"),
            )
        else:
            object.__setattr__(self, "observation_policy_id", "")
        obs = _freeze_mapping(self.observation_map, "observation_map")
        object.__setattr__(self, "observation_map", obs)
        if self.schema_version != HYPER_SYSTEM_BINDING_SCHEMA:
            raise HyperExecutionError(
                f"unsupported system binding schema: {self.schema_version!r}"
            )
        if self.model_required and self.model_present and not self.system_digest:
            raise HyperExecutionError(
                "present required system model must carry a system_digest"
            )

    @classmethod
    def from_request(
        cls,
        *,
        provider: HyperProviderKind,
        document: HyperpropertyIR,
        system_model: bytes | str | None,
        translation: HyperpropertyTranslation | None = None,
        evidence_path: HyperEvidencePath | None = None,
    ) -> HyperSystemBindingV2:
        kind = _system_kind_for(
            provider, system_model=system_model, evidence_path=evidence_path
        )
        model_required = provider is HyperProviderKind.MCHYPER
        model_present = system_model is not None
        digest = _system_digest(system_model)
        # AutoHyper always materializes an explicit system (caller or default).
        if provider is HyperProviderKind.AUTOHYPER and not digest and translation:
            explicit = translation.auxiliary_files.get("system.explicit", "")
            if explicit:
                digest = _system_digest(explicit)
                model_present = True
        obs_map = (
            translation.observation_map
            if translation is not None
            else ObservationMap.from_document(document)
        )
        system_id = {
            HyperSystemKind.NONE: "system:none",
            HyperSystemKind.EXPLICIT: "system:explicit",
            HyperSystemKind.AIGER: "system:aiger",
            HyperSystemKind.BOUNDED_SELF_COMPOSITION: "system:self-composition",
        }[kind]
        if digest:
            system_id = f"{system_id}:{digest[:16]}"
        return cls(
            system_kind=kind,
            system_digest=digest,
            system_id=system_id,
            model_required=model_required,
            model_present=model_present or (
                provider is HyperProviderKind.AUTOHYPER and bool(digest)
            ),
            observation_policy_id=obs_map.policy_id,
            observation_map=obs_map.to_dict(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface": self.interface,
            "model_present": self.model_present,
            "model_required": self.model_required,
            "observation_map": _thaw_mapping(self.observation_map),
            "observation_policy_id": self.observation_policy_id,
            "schema_version": self.schema_version,
            "system_digest": self.system_digest,
            "system_id": self.system_id,
            "system_kind": (
                self.system_kind.value
                if isinstance(self.system_kind, HyperSystemKind)
                else self.system_kind
            ),
        }


@dataclass(frozen=True, slots=True)
class HyperBoundsBindingV2:
    """Finite / quantifier-prefix / execution bounds bound into every answer.

    Interface: ``HyperBoundsBinding@2``.
    """

    semantics: HyperSemanticsKind | str
    max_quantifier_alternations: int
    max_trace_variables: int
    timeout_ms: int
    max_steps: int
    max_traces: int
    max_pairs: int
    composition_max_steps: int | None = None
    supports_exists_forall: bool = False
    supports_forall_exists: bool = False
    finite_only: bool = True
    authorizes_universal_proof: bool = False
    schema_version: str = HYPER_BOUNDS_BINDING_SCHEMA

    interface: ClassVar[str] = HYPER_BOUNDS_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "semantics", _enum(self.semantics, HyperSemanticsKind, "semantics")
        )
        for name in (
            "max_quantifier_alternations",
            "max_trace_variables",
            "timeout_ms",
            "max_steps",
            "max_traces",
            "max_pairs",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise HyperExecutionError(
                    f"{name} must be a non-negative integer"
                )
        if self.max_trace_variables < 1:
            raise HyperExecutionError("max_trace_variables must be positive")
        if self.composition_max_steps is not None:
            if (
                isinstance(self.composition_max_steps, bool)
                or not isinstance(self.composition_max_steps, int)
                or self.composition_max_steps < 0
            ):
                raise HyperExecutionError(
                    "composition_max_steps must be a non-negative integer or None"
                )
        for name in (
            "supports_exists_forall",
            "supports_forall_exists",
            "finite_only",
            "authorizes_universal_proof",
        ):
            object.__setattr__(
                self, name, _optional_bool(getattr(self, name), name)
            )
        if self.authorizes_universal_proof:
            raise HyperAuthorityError(
                "hyper bounds cannot authorize universal proof"
            )
        if not self.finite_only:
            raise HyperAuthorityError(
                "hyper bounds must remain finite_only"
            )
        if self.schema_version != HYPER_BOUNDS_BINDING_SCHEMA:
            raise HyperExecutionError(
                f"unsupported bounds binding schema: {self.schema_version!r}"
            )

    @classmethod
    def from_capability(
        cls,
        capability: HyperEngineCapability,
        *,
        bounds: ExecutionBounds,
        document: HyperpropertyIR,
        semantics: HyperSemanticsKind = HyperSemanticsKind.ENGINE_BOUNDED,
        fallback: FallbackBoundDisclosure | SelfCompositionBound | None = None,
    ) -> HyperBoundsBindingV2:
        max_traces = document.self_composition_bound.max_traces
        max_pairs = document.self_composition_bound.max_pairs
        composition_steps = document.self_composition_bound.max_steps
        if isinstance(fallback, FallbackBoundDisclosure):
            max_traces = fallback.max_traces
            max_pairs = fallback.max_pairs
            composition_steps = fallback.max_steps
        elif isinstance(fallback, SelfCompositionBound):
            max_traces = fallback.max_traces
            max_pairs = fallback.max_pairs
            composition_steps = fallback.max_steps
        return cls(
            semantics=semantics,
            max_quantifier_alternations=capability.max_quantifier_alternations,
            max_trace_variables=capability.max_trace_variables,
            timeout_ms=bounds.timeout_ms,
            max_steps=bounds.max_steps,
            max_traces=max_traces,
            max_pairs=max_pairs,
            composition_max_steps=composition_steps,
            supports_exists_forall=capability.supports_exists_forall,
            supports_forall_exists=capability.supports_forall_exists,
            finite_only=True,
            authorizes_universal_proof=False,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorizes_universal_proof": False,
            "composition_max_steps": self.composition_max_steps,
            "finite_only": True,
            "interface": self.interface,
            "max_pairs": self.max_pairs,
            "max_quantifier_alternations": self.max_quantifier_alternations,
            "max_steps": self.max_steps,
            "max_trace_variables": self.max_trace_variables,
            "max_traces": self.max_traces,
            "schema_version": self.schema_version,
            "semantics": (
                self.semantics.value
                if isinstance(self.semantics, HyperSemanticsKind)
                else self.semantics
            ),
            "supports_exists_forall": self.supports_exists_forall,
            "supports_forall_exists": self.supports_forall_exists,
            "timeout_ms": self.timeout_ms,
        }


@dataclass(frozen=True, slots=True)
class HyperWitnessBindingV2:
    """Witness / counterexample status bound into every answer.

    Interface: ``HyperWitnessBinding@2``.
    """

    status: HyperWitnessStatus | str
    formula_id: str
    observation_policy_id: str
    replayed: bool = False
    trace_count: int = 0
    difference_count: int = 0
    authorizes_universal_proof: bool = False
    counterexample: Mapping[str, Any] | None = None
    schema_version: str = HYPER_WITNESS_BINDING_SCHEMA

    interface: ClassVar[str] = HYPER_WITNESS_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "status", _enum(self.status, HyperWitnessStatus, "status")
        )
        object.__setattr__(
            self, "formula_id", _record_id(self.formula_id, "formula_id")
        )
        if self.observation_policy_id:
            object.__setattr__(
                self,
                "observation_policy_id",
                _record_id(self.observation_policy_id, "observation_policy_id"),
            )
        else:
            object.__setattr__(self, "observation_policy_id", "")
        object.__setattr__(self, "replayed", _optional_bool(self.replayed, "replayed"))
        for name in ("trace_count", "difference_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise HyperExecutionError(
                    f"{name} must be a non-negative integer"
                )
        object.__setattr__(
            self,
            "authorizes_universal_proof",
            _optional_bool(
                self.authorizes_universal_proof, "authorizes_universal_proof"
            ),
        )
        if self.authorizes_universal_proof:
            raise HyperAuthorityError(
                "witness binding cannot authorize universal proof"
            )
        if self.counterexample is None:
            object.__setattr__(self, "counterexample", None)
        else:
            cex = _require_mapping(self.counterexample, "counterexample")
            object.__setattr__(
                self, "counterexample", dict(_freeze_mapping(cex, "counterexample"))
            )
        if self.schema_version != HYPER_WITNESS_BINDING_SCHEMA:
            raise HyperExecutionError(
                f"unsupported witness binding schema: {self.schema_version!r}"
            )
        status = self.status  # type: ignore[assignment]
        if status is HyperWitnessStatus.COUNTEREXAMPLE_REPLAYED and not self.replayed:
            raise HyperExecutionError(
                "counterexample_replayed status requires replayed=True"
            )
        if (
            status is HyperWitnessStatus.COUNTEREXAMPLE_UNREPLAYABLE
            and self.replayed
        ):
            raise HyperExecutionError(
                "counterexample_unreplayable status cannot claim replayed=True"
            )

    @classmethod
    def from_outcome(
        cls,
        *,
        document: HyperpropertyIR,
        disposition: HyperDisposition,
        evidence_path: HyperEvidencePath,
        counterexample: HyperCounterexampleTrace | None,
        observation_policy_id: str,
    ) -> HyperWitnessBindingV2:
        status = _witness_status_from(
            counterexample,
            evidence_path=evidence_path,
            disposition=disposition,
        )
        replayed = bool(counterexample is not None and counterexample.replayed)
        trace_count = len(counterexample.traces) if counterexample else 0
        difference_count = (
            len(counterexample.differences) if counterexample else 0
        )
        return cls(
            status=status,
            formula_id=document.formula.formula_id,
            observation_policy_id=observation_policy_id or document.information_flow_policy.policy_id,
            replayed=replayed,
            trace_count=trace_count,
            difference_count=difference_count,
            authorizes_universal_proof=False,
            counterexample=(
                counterexample.to_dict() if counterexample is not None else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorizes_universal_proof": False,
            "counterexample": (
                None if self.counterexample is None else dict(self.counterexample)
            ),
            "difference_count": self.difference_count,
            "formula_id": self.formula_id,
            "interface": self.interface,
            "observation_policy_id": self.observation_policy_id,
            "replayed": self.replayed,
            "schema_version": self.schema_version,
            "status": (
                self.status.value
                if isinstance(self.status, HyperWitnessStatus)
                else self.status
            ),
            "trace_count": self.trace_count,
        }


@dataclass(frozen=True, slots=True)
class HyperCapabilityReceiptV2:
    """Independent capability snapshot for exactly one engine.

    Interface: ``HyperCapabilityReceipt@2``.

    Never transfers support from another engine.
    """

    engine: HyperProviderKind | str
    available: bool
    supported_prefix: bool
    capability: Mapping[str, Any]
    reason: str = ""
    establishes_other_engines: bool = False
    schema_version: str = HYPER_CAPABILITY_RECEIPT_SCHEMA

    interface: ClassVar[str] = HYPER_CAPABILITY_RECEIPT_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "engine", normalize_hyper_provider(self.engine)
        )
        object.__setattr__(
            self, "available", _optional_bool(self.available, "available")
        )
        object.__setattr__(
            self,
            "supported_prefix",
            _optional_bool(self.supported_prefix, "supported_prefix"),
        )
        cap = _require_mapping(self.capability, "capability")
        engine = self.engine  # type: ignore[assignment]
        if cap.get("engine") not in {None, engine.value}:
            raise HyperAuthorityError(
                "capability receipt engine must match the declared engine; "
                "one engine's capability cannot be re-labeled as another"
            )
        # Re-bind to the canonical independent capability for this engine only.
        canonical = capability_for(engine).to_dict()
        object.__setattr__(self, "capability", dict(canonical))
        object.__setattr__(
            self, "reason", _text(self.reason, "reason", allow_empty=True, maximum=1_024)
        )
        object.__setattr__(
            self,
            "establishes_other_engines",
            _optional_bool(
                self.establishes_other_engines, "establishes_other_engines"
            ),
        )
        if self.establishes_other_engines:
            raise HyperAuthorityError(
                "capability receipt cannot establish other engines"
            )
        if self.schema_version != HYPER_CAPABILITY_RECEIPT_SCHEMA:
            raise HyperExecutionError(
                f"unsupported capability receipt schema: {self.schema_version!r}"
            )

    def establishes(self, other: HyperProviderKind | HyperEngine | str) -> bool:
        return engine_support_establishes_other(
            self.engine,  # type: ignore[arg-type]
            other,
            source_available=self.available,
            source_supported=self.supported_prefix,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "capability": dict(self.capability),
            "engine": (
                self.engine.value
                if isinstance(self.engine, HyperProviderKind)
                else self.engine
            ),
            "establishes_other_engines": False,
            "interface": self.interface,
            "reason": self.reason,
            "schema_version": self.schema_version,
            "supported_prefix": self.supported_prefix,
        }


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HyperExecutionRequestV2:
    """Typed AutoHyper / MCHyper / HyperLTL execution request.

    Interface: ``HyperExecutionRequest@2``.
    """

    request_id: str
    provider: HyperProviderKind | str
    document: HyperpropertyIR | Mapping[str, Any]
    system_model: bytes | str | None = None
    traces: tuple[ExecutionTrace, ...] | Sequence[ExecutionTrace] | Sequence[Mapping[str, Any]] = ()
    mode: HyperExecutionMode | str = HyperExecutionMode.ENGINE
    allow_fallback: bool = False
    source_ref_ids: tuple[str, ...] | Sequence[str] = ()
    bounds: ExecutionBounds | None = None
    mock_output: Mapping[str, Any] | None = None
    fallback_output: Mapping[str, Any] | None = None
    available: bool = True
    confidence: float = 0.0
    fluent_text: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = HYPER_EXECUTION_REQUEST_SCHEMA

    interface: ClassVar[str] = HYPER_EXECUTION_REQUEST_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _record_id(self.request_id, "request_id")
        )
        object.__setattr__(
            self, "provider", normalize_hyper_provider(self.provider)
        )
        document = _document_from_value(self.document)
        object.__setattr__(self, "document", document)

        if self.system_model is not None and not isinstance(
            self.system_model, (bytes, str)
        ):
            raise HyperExecutionError("system_model must be bytes, text, or None")
        if isinstance(self.system_model, str) and "\x00" in self.system_model:
            raise HyperExecutionError("system_model text must not contain NUL bytes")
        if isinstance(self.system_model, (bytes, str)):
            size = (
                len(self.system_model)
                if isinstance(self.system_model, bytes)
                else len(self.system_model.encode("utf-8"))
            )
            if size > _MAX_SYSTEM_BYTES:
                raise HyperExecutionError(
                    f"system_model exceeds hard limit {_MAX_SYSTEM_BYTES} bytes"
                )

        traces: list[ExecutionTrace] = []
        for index, item in enumerate(self.traces or ()):
            if isinstance(item, ExecutionTrace):
                traces.append(item)
            elif isinstance(item, Mapping):
                traces.append(
                    ExecutionTrace(
                        trace_id=str(item.get("trace_id", f"trace:{index}")),
                        public_inputs=dict(item.get("public_inputs") or {}),
                        private_inputs=dict(item.get("private_inputs") or {}),
                        observations=dict(item.get("observations") or {}),
                        subject=dict(item.get("subject") or {}),
                    )
                )
            else:
                raise HyperExecutionError(
                    f"traces[{index}] must be ExecutionTrace or mapping"
                )
        object.__setattr__(self, "traces", tuple(traces))

        object.__setattr__(
            self, "mode", _enum(self.mode, HyperExecutionMode, "mode")
        )
        object.__setattr__(
            self, "allow_fallback", _optional_bool(self.allow_fallback, "allow_fallback")
        )
        object.__setattr__(
            self, "source_ref_ids", _source_ref_ids(self.source_ref_ids or ())
        )

        if self.bounds is None:
            object.__setattr__(
                self,
                "bounds",
                ExecutionBounds(timeout_ms=1_000, max_steps=1_000),
            )
        elif not isinstance(self.bounds, ExecutionBounds):
            raise HyperExecutionError("bounds must be ExecutionBounds")

        object.__setattr__(
            self, "available", _optional_bool(self.available, "available")
        )
        if isinstance(self.confidence, bool) or not isinstance(
            self.confidence, (int, float)
        ):
            raise HyperExecutionError("confidence must be numeric")
        conf = float(self.confidence)
        if conf != conf or conf < 0.0 or conf > 1.0:
            raise HyperExecutionError("confidence must be finite in [0, 1]")
        object.__setattr__(self, "confidence", conf)
        object.__setattr__(
            self,
            "fluent_text",
            _text(self.fluent_text, "fluent_text", maximum=8_192, allow_empty=True),
        )

        if self.mock_output is None:
            object.__setattr__(self, "mock_output", None)
        else:
            mock = _require_mapping(self.mock_output, "mock_output")
            object.__setattr__(
                self, "mock_output", dict(_freeze_mapping(mock, "mock_output"))
            )
        if self.fallback_output is None:
            object.__setattr__(self, "fallback_output", None)
        else:
            fallback = _require_mapping(self.fallback_output, "fallback_output")
            object.__setattr__(
                self,
                "fallback_output",
                dict(_freeze_mapping(fallback, "fallback_output")),
            )

        metadata = _freeze_mapping(self.metadata, "metadata")
        _forbid_authority_metadata(metadata, "metadata")
        if len(canonical_json_bytes(dict(metadata))) > _MAX_METADATA_BYTES:
            raise HyperExecutionError("metadata exceeds hard byte limit")
        object.__setattr__(self, "metadata", metadata)

        if self.schema_version != HYPER_EXECUTION_REQUEST_SCHEMA:
            raise HyperExecutionError(
                f"unsupported HyperExecutionRequest@2 schema: "
                f"{self.schema_version!r}"
            )

    @property
    def has_mock_output(self) -> bool:
        return self.mock_output is not None

    @property
    def has_fallback_output(self) -> bool:
        return self.fallback_output is not None

    @property
    def provider_identity(self) -> LogicIdentity:
        return provider_logic_identity(self.provider)  # type: ignore[arg-type]

    @property
    def lane(self) -> LogicIdentity:
        return lane_id(HYPER_LANE_ID)

    @property
    def evidence_kind(self) -> LogicIdentity:
        return evidence_id(HYPER_EVIDENCE_KIND)

    @property
    def document_digest(self) -> str:
        return content_sha256(
            canonical_json_bytes(self.document.semantic_dict())  # type: ignore[union-attr]
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_fallback": self.allow_fallback,
            "available": self.available,
            "bounds": self.bounds.to_dict() if self.bounds else None,  # type: ignore[union-attr]
            "confidence": self.confidence,
            "document_digest": self.document_digest,
            "document_id": self.document.document_id,  # type: ignore[union-attr]
            "evidence_kind": self.evidence_kind.to_dict(),
            "fallback_output": (
                None if self.fallback_output is None else dict(self.fallback_output)
            ),
            "fluent_text": self.fluent_text,
            "has_fallback_output": self.has_fallback_output,
            "has_mock_output": self.has_mock_output,
            "interface": self.interface,
            "lane": self.lane.to_dict(),
            "metadata": _thaw_mapping(self.metadata),
            "mock_output": (
                None if self.mock_output is None else dict(self.mock_output)
            ),
            "mode": (
                self.mode.value
                if isinstance(self.mode, HyperExecutionMode)
                else self.mode
            ),
            "provider": (
                self.provider.value
                if isinstance(self.provider, HyperProviderKind)
                else self.provider
            ),
            "provider_identity": self.provider_identity.to_dict(),
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "system_digest": _system_digest(self.system_model),
            "system_model_present": self.system_model is not None,
            "trace_count": len(self.traces),
        }


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HyperProviderEvidenceV2:
    """Pinned hyperproperty provider evidence with split engine identities.

    Interface: ``HyperProviderEvidence@2``.

    Every answer **must** identify engine, system, formula, bounds, and
    witness status.  One engine's support never establishes another's
    capability.  Hyperproperty evidence remains bounded — never theorem.
    """

    evidence_id: str
    request_id: str
    request_digest: str
    engine: HyperProviderKind | str
    disposition: HyperDisposition | str
    mode: HyperExecutionMode | str
    formula: HyperFormulaBindingV2 | Mapping[str, Any]
    system: HyperSystemBindingV2 | Mapping[str, Any]
    bounds: HyperBoundsBindingV2 | Mapping[str, Any]
    witness: HyperWitnessBindingV2 | Mapping[str, Any]
    capability: HyperCapabilityReceiptV2 | Mapping[str, Any]
    source_ref_ids: tuple[str, ...] | Sequence[str] = ()
    result_authority: ResultAuthority | str = ResultAuthority.HYPERPROPERTY
    result_status: ResultStatus | str = ResultStatus.UNKNOWN
    role: ToolRole | str = ToolRole.AUTHORITY
    authority_ceiling: ToolchainAuthorityCeiling | str = (
        ToolchainAuthorityCeiling.BOUNDED
    )
    translation_ceiling: EvidenceAuthority | str = EvidenceAuthority.BOUNDED
    hyperproperty_established: bool = False
    mock_output_present: bool = False
    fallback_output_present: bool = False
    available: bool = False
    confidence: float = 0.0
    fluent_text_present: bool = False
    evidence_path: HyperEvidencePath | str = HyperEvidencePath.NONE
    external_tool_proof: bool = False
    authorizes_universal_proof: bool = False
    receipt: Mapping[str, Any] | None = None
    diagnostics: tuple[str, ...] = ()
    content_digest: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = HYPER_PROVIDER_EVIDENCE_SCHEMA

    interface: ClassVar[str] = HYPER_PROVIDER_EVIDENCE_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence_id", _record_id(self.evidence_id, "evidence_id")
        )
        object.__setattr__(
            self, "request_id", _record_id(self.request_id, "request_id")
        )
        object.__setattr__(
            self,
            "request_digest",
            _sha256_hex(self.request_digest, "request_digest"),
        )
        object.__setattr__(
            self, "engine", normalize_hyper_provider(self.engine)
        )
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, HyperDisposition, "disposition"),
        )
        object.__setattr__(
            self, "mode", _enum(self.mode, HyperExecutionMode, "mode")
        )

        if isinstance(self.formula, HyperFormulaBindingV2):
            formula = self.formula
        else:
            formula = HyperFormulaBindingV2(
                **_filter_keys(
                    _require_mapping(self.formula, "formula"),
                    {
                        "formula_id",
                        "formula_digest",
                        "document_digest",
                        "quantifier_signature",
                        "quantifier_prefix",
                        "matrix_statement",
                        "alternation_count",
                        "trace_cardinality",
                        "formula_text",
                        "translation_digest",
                        "schema_version",
                    },
                )
            )
        object.__setattr__(self, "formula", formula)

        if isinstance(self.system, HyperSystemBindingV2):
            system = self.system
        else:
            system = HyperSystemBindingV2(
                **_filter_keys(
                    _require_mapping(self.system, "system"),
                    {
                        "system_kind",
                        "system_digest",
                        "system_id",
                        "model_required",
                        "model_present",
                        "observation_policy_id",
                        "observation_map",
                        "schema_version",
                    },
                )
            )
        object.__setattr__(self, "system", system)

        if isinstance(self.bounds, HyperBoundsBindingV2):
            bounds = self.bounds
        else:
            bounds = HyperBoundsBindingV2(
                **_filter_keys(
                    _require_mapping(self.bounds, "bounds"),
                    {
                        "semantics",
                        "max_quantifier_alternations",
                        "max_trace_variables",
                        "timeout_ms",
                        "max_steps",
                        "max_traces",
                        "max_pairs",
                        "composition_max_steps",
                        "supports_exists_forall",
                        "supports_forall_exists",
                        "finite_only",
                        "authorizes_universal_proof",
                        "schema_version",
                    },
                )
            )
        object.__setattr__(self, "bounds", bounds)

        if isinstance(self.witness, HyperWitnessBindingV2):
            witness = self.witness
        else:
            witness = HyperWitnessBindingV2(
                **_filter_keys(
                    _require_mapping(self.witness, "witness"),
                    {
                        "status",
                        "formula_id",
                        "observation_policy_id",
                        "replayed",
                        "trace_count",
                        "difference_count",
                        "authorizes_universal_proof",
                        "counterexample",
                        "schema_version",
                    },
                )
            )
        object.__setattr__(self, "witness", witness)
        if witness.formula_id != formula.formula_id:
            raise HyperExecutionError(
                "witness.formula_id must match formula.formula_id"
            )

        if isinstance(self.capability, HyperCapabilityReceiptV2):
            capability = self.capability
        else:
            capability = HyperCapabilityReceiptV2(
                **_filter_keys(
                    _require_mapping(self.capability, "capability"),
                    {
                        "engine",
                        "available",
                        "supported_prefix",
                        "capability",
                        "reason",
                        "establishes_other_engines",
                        "schema_version",
                    },
                )
            )
        object.__setattr__(self, "capability", capability)
        if capability.engine is not self.engine:  # type: ignore[comparison-overlap]
            raise HyperAuthorityError(
                "capability.engine must match evidence.engine; "
                "one engine's support cannot establish another's capability"
            )

        object.__setattr__(
            self, "source_ref_ids", _source_ref_ids(self.source_ref_ids)
        )

        result_authority = (
            self.result_authority
            if isinstance(self.result_authority, ResultAuthority)
            else ResultAuthority(str(self.result_authority))
        )
        if result_authority is not ResultAuthority.HYPERPROPERTY:
            raise HyperAuthorityError(
                "HyperProviderEvidence@2 result_authority must be hyperproperty; "
                f"got {result_authority!r}"
            )
        object.__setattr__(self, "result_authority", ResultAuthority.HYPERPROPERTY)

        result_status = (
            self.result_status
            if isinstance(self.result_status, ResultStatus)
            else ResultStatus(str(self.result_status))
        )
        if result_status in {ResultStatus.PROVED, ResultStatus.DISPROVED}:
            raise HyperAuthorityError(
                "HyperProviderEvidence@2 cannot claim theorem result statuses"
            )
        object.__setattr__(self, "result_status", result_status)

        role = self.role if isinstance(self.role, ToolRole) else ToolRole(str(self.role))
        if role not in {ToolRole.AUTHORITY, ToolRole.SHADOW}:
            raise HyperAuthorityError(
                f"HyperProviderEvidence@2 role must be authority or shadow; got {role!r}"
            )
        object.__setattr__(self, "role", role)

        ceiling = (
            self.authority_ceiling
            if isinstance(self.authority_ceiling, ToolchainAuthorityCeiling)
            else ToolchainAuthorityCeiling(str(self.authority_ceiling))
        )
        if ceiling is not ToolchainAuthorityCeiling.BOUNDED:
            raise HyperAuthorityError(
                "HyperProviderEvidence@2 authority_ceiling must be bounded"
            )
        object.__setattr__(self, "authority_ceiling", ceiling)

        translation_ceiling = (
            self.translation_ceiling
            if isinstance(self.translation_ceiling, EvidenceAuthority)
            else EvidenceAuthority(str(self.translation_ceiling))
        )
        if translation_ceiling not in {
            EvidenceAuthority.BOUNDED,
            EvidenceAuthority.NONE,
        }:
            raise HyperAuthorityError(
                "HyperProviderEvidence@2 translation_ceiling must remain bounded"
            )
        object.__setattr__(self, "translation_ceiling", translation_ceiling)

        for flag_name in (
            "hyperproperty_established",
            "mock_output_present",
            "fallback_output_present",
            "available",
            "fluent_text_present",
            "external_tool_proof",
            "authorizes_universal_proof",
        ):
            object.__setattr__(
                self,
                flag_name,
                _optional_bool(getattr(self, flag_name), flag_name),
            )
        if self.authorizes_universal_proof:
            raise HyperAuthorityError(
                "hyperproperty evidence cannot authorize universal proof"
            )

        if isinstance(self.confidence, bool) or not isinstance(
            self.confidence, (int, float)
        ):
            raise HyperExecutionError("confidence must be numeric")
        conf = float(self.confidence)
        if conf != conf or conf < 0.0 or conf > 1.0:
            raise HyperExecutionError("confidence must be finite in [0, 1]")
        object.__setattr__(self, "confidence", conf)

        object.__setattr__(
            self,
            "evidence_path",
            _enum(self.evidence_path, HyperEvidencePath, "evidence_path"),
        )

        mode = self.mode  # type: ignore[assignment]
        if (
            self.mock_output_present
            or self.fallback_output_present
            or mode
            in {
                HyperExecutionMode.MOCK,
                HyperExecutionMode.FALLBACK,
                HyperExecutionMode.CAPABILITY_PROBE,
            }
        ):
            if self.hyperproperty_established:
                raise HyperAuthorityError(
                    "fallback, mock, or capability-probe output cannot establish "
                    "hyperproperty authority"
                )
            object.__setattr__(self, "hyperproperty_established", False)
            object.__setattr__(self, "external_tool_proof", False)

        if self.receipt is None:
            object.__setattr__(self, "receipt", None)
        else:
            receipt = _require_mapping(self.receipt, "receipt")
            object.__setattr__(
                self, "receipt", dict(_freeze_mapping(receipt, "receipt"))
            )

        diagnostics: list[str] = []
        for index, item in enumerate(self.diagnostics):
            if not isinstance(item, str) or "\x00" in item:
                raise HyperExecutionError(
                    f"diagnostics[{index}] must be text without NUL bytes"
                )
            text = item.strip()
            if not text:
                continue
            diagnostics.append(text[:512])
            if len(diagnostics) >= _MAX_DIAGNOSTICS:
                break
        object.__setattr__(self, "diagnostics", tuple(diagnostics))

        metadata = _freeze_mapping(self.metadata, "metadata")
        _forbid_authority_metadata(metadata, "metadata")
        object.__setattr__(self, "metadata", metadata)

        if self.schema_version != HYPER_PROVIDER_EVIDENCE_SCHEMA:
            raise HyperExecutionError(
                f"unsupported HyperProviderEvidence@2 schema: "
                f"{self.schema_version!r}"
            )

        if not self.content_digest:
            object.__setattr__(
                self,
                "content_digest",
                _digest_of(
                    {
                        "bounds": self.bounds.to_dict(),  # type: ignore[union-attr]
                        "disposition": (
                            self.disposition.value
                            if isinstance(self.disposition, HyperDisposition)
                            else self.disposition
                        ),
                        "engine": (
                            self.engine.value
                            if isinstance(self.engine, HyperProviderKind)
                            else self.engine
                        ),
                        "formula": self.formula.to_dict(),  # type: ignore[union-attr]
                        "mode": (
                            self.mode.value
                            if isinstance(self.mode, HyperExecutionMode)
                            else self.mode
                        ),
                        "request_digest": self.request_digest,
                        "request_id": self.request_id,
                        "system": self.system.to_dict(),  # type: ignore[union-attr]
                        "witness": self.witness.to_dict(),  # type: ignore[union-attr]
                    }
                ),
            )
        else:
            object.__setattr__(
                self,
                "content_digest",
                _sha256_hex(self.content_digest, "content_digest"),
            )

    # --- identity / authority queries --------------------------------------

    @property
    def provider(self) -> HyperProviderKind:
        return self.engine  # type: ignore[return-value]

    @property
    def is_theorem_authority(self) -> bool:
        return False

    @property
    def is_proved(self) -> bool:
        return False

    @property
    def proof_established(self) -> bool:
        return False

    @property
    def satisfiability_established(self) -> bool:
        return False

    @property
    def theorem_established(self) -> bool:
        return False

    def claim_established(self, claim: HyperClaimKind | str) -> bool:
        kind = (
            claim
            if isinstance(claim, HyperClaimKind)
            else HyperClaimKind(str(claim))
        )
        if kind is HyperClaimKind.HYPERPROPERTY:
            return bool(self.hyperproperty_established)
        if kind is HyperClaimKind.OTHER_ENGINE_CAPABILITY:
            return False
        return False

    def non_authoritative_claim(self, claim: HyperClaimKind | str) -> bool:
        return non_authoritative_signal_establishes(
            claim,
            mock_output={} if self.mock_output_present else None,
            fallback_output={} if self.fallback_output_present else None,
            available=self.available,
            confidence=self.confidence,
            fluent_text="present" if self.fluent_text_present else None,
        )

    def establishes_other_engine(
        self, other: HyperProviderKind | HyperEngine | str
    ) -> bool:
        """Whether this engine's support establishes *other*'s capability."""

        return engine_support_establishes_other(
            self.engine,  # type: ignore[arg-type]
            other,
            source_available=self.available,
            source_supported=self.capability.supported_prefix,  # type: ignore[union-attr]
        )

    def bindings_complete(self) -> bool:
        """Whether engine, system, formula, bounds, and witness are all bound."""

        return bool(
            isinstance(self.engine, HyperProviderKind)
            and isinstance(self.formula, HyperFormulaBindingV2)
            and self.formula.formula_id
            and self.formula.formula_digest
            and isinstance(self.system, HyperSystemBindingV2)
            and self.system.system_id
            and isinstance(self.bounds, HyperBoundsBindingV2)
            and self.bounds.finite_only
            and isinstance(self.witness, HyperWitnessBindingV2)
            and self.witness.formula_id == self.formula.formula_id
            and isinstance(self.capability, HyperCapabilityReceiptV2)
            and self.capability.engine is self.engine
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorizes_universal_proof": False,
            "authority_ceiling": (
                self.authority_ceiling.value
                if isinstance(self.authority_ceiling, ToolchainAuthorityCeiling)
                else self.authority_ceiling
            ),
            "available": self.available,
            "bindings_complete": self.bindings_complete(),
            "bounds": self.bounds.to_dict(),  # type: ignore[union-attr]
            "capability": self.capability.to_dict(),  # type: ignore[union-attr]
            "claim_hyperproperty": bool(self.hyperproperty_established),
            "claim_other_engine_capability": False,
            "claim_proof": False,
            "claim_satisfiability": False,
            "claim_theorem": False,
            "confidence": self.confidence,
            "content_digest": self.content_digest,
            "diagnostics": list(self.diagnostics),
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, HyperDisposition)
                else self.disposition
            ),
            "engine": (
                self.engine.value
                if isinstance(self.engine, HyperProviderKind)
                else self.engine
            ),
            "evidence_id": self.evidence_id,
            "evidence_path": (
                self.evidence_path.value
                if isinstance(self.evidence_path, HyperEvidencePath)
                else self.evidence_path
            ),
            "external_tool_proof": self.external_tool_proof,
            "fallback_output_present": self.fallback_output_present,
            "fluent_text_present": self.fluent_text_present,
            "formula": self.formula.to_dict(),  # type: ignore[union-attr]
            "hyperproperty_established": self.hyperproperty_established,
            "interface": self.interface,
            "is_proved": False,
            "is_theorem_authority": False,
            "metadata": _thaw_mapping(self.metadata),
            "mock_output_present": self.mock_output_present,
            "mode": (
                self.mode.value
                if isinstance(self.mode, HyperExecutionMode)
                else self.mode
            ),
            "proof_established": False,
            "provider": (
                self.engine.value
                if isinstance(self.engine, HyperProviderKind)
                else self.engine
            ),
            "provider_identity": provider_logic_identity(
                self.engine  # type: ignore[arg-type]
            ).to_dict(),
            "receipt": None if self.receipt is None else dict(self.receipt),
            "request_digest": self.request_digest,
            "request_id": self.request_id,
            "result_authority": ResultAuthority.HYPERPROPERTY.value,
            "result_status": (
                self.result_status.value
                if isinstance(self.result_status, ResultStatus)
                else self.result_status
            ),
            "role": (
                self.role.value if isinstance(self.role, ToolRole) else self.role
            ),
            "satisfiability_established": False,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "system": self.system.to_dict(),  # type: ignore[union-attr]
            "theorem_established": False,
            "translation_ceiling": (
                self.translation_ceiling.value
                if isinstance(self.translation_ceiling, EvidenceAuthority)
                else self.translation_ceiling
            ),
            "witness": self.witness.to_dict(),  # type: ignore[union-attr]
            "witness_status": (
                self.witness.status.value  # type: ignore[union-attr]
                if isinstance(self.witness.status, HyperWitnessStatus)  # type: ignore[union-attr]
                else self.witness.status  # type: ignore[union-attr]
            ),
        }


def _filter_keys(
    mapping: Mapping[str, Any], allowed: set[str]
) -> dict[str, Any]:
    return {key: value for key, value in mapping.items() if key in allowed}


def _contract_json_value(value: object, field_name: str) -> Any:
    """Coerce a value into freeze-mapping-safe JSON (no floats).

    ``_freeze_mapping`` rejects float values. Adapter check receipts carry
    ``timeout_seconds`` as a float process bound; project that field (and any
    other floats) into integer milliseconds / whole-number integers so evidence
    binding stays contract-safe without losing the bound.
    """

    if value is None or type(value) in {str, bool, int}:
        if type(value) is int and abs(value) > (1 << 53) - 1:
            raise HyperExecutionError(
                f"{field_name} integer is outside the safe JSON integer range"
            )
        return value
    if type(value) is float:
        if value != value or value in {float("inf"), float("-inf")}:
            raise HyperExecutionError(
                f"{field_name} must be a finite number; got {value!r}"
            )
        # Prefer exact integers; otherwise fixed-point microseconds.
        as_int = int(value)
        if value == as_int:
            if abs(as_int) > (1 << 53) - 1:
                raise HyperExecutionError(
                    f"{field_name} integer is outside the safe JSON integer range"
                )
            return as_int
        micros = int(round(value * 1_000_000))
        if abs(micros) > (1 << 53) - 1:
            raise HyperExecutionError(
                f"{field_name} fixed-point value is outside the safe JSON range"
            )
        return micros
    if isinstance(value, Mapping):
        return {
            str(key): _contract_json_value(item, f"{field_name}.{key}")
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [
            _contract_json_value(item, f"{field_name}[{index}]")
            for index, item in enumerate(value)
        ]
    raise HyperExecutionError(
        f"{field_name} is not a contract-safe JSON value: {type(value).__name__}"
    )


def _evidence_receipt_payload(
    receipt: Mapping[str, Any] | object,
) -> dict[str, Any]:
    """Project a hyper check receipt into freeze-mapping-safe evidence JSON.

    Adapter receipts expose ``timeout_seconds`` as a float. Evidence contracts
    reject floats, so convert that bound to integer ``timeout_ms`` and keep
    whole-second ``timeout_seconds`` only when exact.
    """

    if hasattr(receipt, "to_dict") and callable(receipt.to_dict):
        raw = receipt.to_dict()  # type: ignore[operator]
    else:
        raw = dict(_require_mapping(receipt, "receipt"))
    if not isinstance(raw, Mapping):
        raise HyperExecutionError("receipt.to_dict() must return a mapping")

    payload = dict(raw)
    timeout_seconds = payload.pop("timeout_seconds", None)
    if timeout_seconds is not None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or float(timeout_seconds) != float(timeout_seconds)
            or float(timeout_seconds) <= 0
        ):
            raise HyperExecutionError(
                "receipt.timeout_seconds must be a positive finite number"
            )
        seconds = float(timeout_seconds)
        timeout_ms = max(1, int(round(seconds * 1000.0)))
        payload["timeout_ms"] = timeout_ms
        # Preserve whole-second values as int; fractional bounds live in timeout_ms.
        whole = int(seconds)
        if seconds == whole and whole > 0:
            payload["timeout_seconds"] = whole
    return dict(_contract_json_value(payload, "receipt"))


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HyperExecutionResultV2:
    """Typed result of one hyperproperty engine execution.

    Interface: ``HyperExecutionResult@2``.
    """

    request: HyperExecutionRequestV2
    evidence: HyperProviderEvidenceV2
    backend_result: HyperpropertyResult | None = None
    translation: HyperpropertyTranslation | None = None
    schema_version: str = HYPER_EXECUTION_RESULT_SCHEMA

    interface: ClassVar[str] = HYPER_EXECUTION_RESULT_V2_INTERFACE

    def __post_init__(self) -> None:
        if not isinstance(self.request, HyperExecutionRequestV2):
            raise HyperExecutionError(
                "request must be a HyperExecutionRequestV2"
            )
        if not isinstance(self.evidence, HyperProviderEvidenceV2):
            raise HyperExecutionError(
                "evidence must be a HyperProviderEvidenceV2"
            )
        if self.schema_version != HYPER_EXECUTION_RESULT_SCHEMA:
            raise HyperExecutionError(
                f"unsupported HyperExecutionResult@2 schema: "
                f"{self.schema_version!r}"
            )
        if self.backend_result is not None and not isinstance(
            self.backend_result, HyperpropertyResult
        ):
            raise HyperExecutionError(
                "backend_result must be HyperpropertyResult or None"
            )
        if self.translation is not None and not isinstance(
            self.translation, HyperpropertyTranslation
        ):
            raise HyperExecutionError(
                "translation must be HyperpropertyTranslation or None"
            )
        # Engine identity consistency across request/evidence.
        if self.request.provider is not self.evidence.engine:  # type: ignore[comparison-overlap]
            raise HyperAuthorityError(
                "result engine must match request provider"
            )

    @property
    def disposition(self) -> HyperDisposition:
        return self.evidence.disposition  # type: ignore[return-value]

    @property
    def engine(self) -> HyperProviderKind:
        return self.evidence.engine  # type: ignore[return-value]

    @property
    def hyperproperty_established(self) -> bool:
        return bool(self.evidence.hyperproperty_established)

    @property
    def is_proved(self) -> bool:
        return False

    @property
    def is_theorem_authority(self) -> bool:
        return False

    @property
    def witness_status(self) -> HyperWitnessStatus:
        return self.evidence.witness.status  # type: ignore[return-value, union-attr]

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_result": (
                None
                if self.backend_result is None
                else self.backend_result.to_dict()
            ),
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, HyperDisposition)
                else self.disposition
            ),
            "engine": self.engine.value,
            "evidence": self.evidence.to_dict(),
            "hyperproperty_established": self.hyperproperty_established,
            "interface": self.interface,
            "is_proved": False,
            "is_theorem_authority": False,
            "request": self.request.to_dict(),
            "schema_version": self.schema_version,
            "translation": (
                None if self.translation is None else self.translation.to_dict()
            ),
            "witness_status": (
                self.witness_status.value
                if isinstance(self.witness_status, HyperWitnessStatus)
                else self.witness_status
            ),
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


BackendFactory = Callable[[], HyperpropertyBackend]


class HyperExecutionEngineV2:
    """Execute AutoHyper / MCHyper / HyperLTL on independent capability paths.

    Interface owner: ``HyperProviderEvidence@2``.
    """

    INTERFACE: ClassVar[str] = HYPER_PROVIDER_EVIDENCE_V2_INTERFACE
    interface: ClassVar[str] = HYPER_PROVIDER_EVIDENCE_V2_INTERFACE
    VERSION: ClassVar[str] = HYPER_EXECUTION_V2_MODULE_VERSION
    TASK_ID: ClassVar[str] = HYPER_EXECUTION_V2_TASK_ID
    GOAL_ID: ClassVar[str] = HYPER_EXECUTION_V2_GOAL_ID

    def __init__(
        self,
        *,
        hyperltl: HyperpropertyBackend | None = None,
        autohyper: HyperpropertyBackend | None = None,
        mchyper: HyperpropertyBackend | None = None,
        runner: BoundedToolRunner | None = None,
    ) -> None:
        self._runner = runner
        self._backends: dict[HyperProviderKind, HyperpropertyBackend] = {
            HyperProviderKind.HYPERLTL: hyperltl
            or HyperLTLBackend(runner=runner),
            HyperProviderKind.AUTOHYPER: autohyper
            or AutoHyperBackend(runner=runner),
            HyperProviderKind.MCHYPER: mchyper
            or MCHyperBackend(runner=runner),
        }
        # Enforce engine identity isolation at construction.
        for kind, backend in self._backends.items():
            if backend.engine is not provider_to_engine(kind):
                raise HyperAuthorityError(
                    f"backend for {kind.value} must own engine "
                    f"{provider_to_engine(kind).value}; got {backend.engine.value}"
                )
            # Capability surface must match the declared independent table.
            expected = capability_for(kind)
            if backend.capability.engine is not expected.engine:
                raise HyperAuthorityError(
                    "backend capability engine mismatch"
                )

    def backend(self, provider: HyperProviderKind | str) -> HyperpropertyBackend:
        kind = normalize_hyper_provider(provider)
        return self._backends[kind]

    def capability_of(
        self, provider: HyperProviderKind | str
    ) -> HyperEngineCapability:
        """Return only the named engine's capability (never another's)."""

        kind = normalize_hyper_provider(provider)
        # Prefer the static independent table so a miswired backend cannot
        # smuggle another engine's capability into this path.
        return capability_for(kind)

    def capability_receipt(
        self,
        provider: HyperProviderKind | str,
        *,
        document: HyperpropertyIR | None = None,
    ) -> HyperCapabilityReceiptV2:
        kind = normalize_hyper_provider(provider)
        backend = self.backend(kind)
        available = backend.is_available()
        supported = True
        reason = ""
        if document is not None:
            supported, reason = backend.supports_prefix(document)
        if not available and not reason:
            probe = backend.probe()
            reason = probe.reason or f"{kind.value} executable unavailable"
        return HyperCapabilityReceiptV2(
            engine=kind,
            available=available,
            supported_prefix=supported,
            capability=capability_for(kind).to_dict(),
            reason=reason,
            establishes_other_engines=False,
        )

    def probe_all(self) -> dict[HyperProviderKind, HyperCapabilityReceiptV2]:
        """Probe each engine independently; never cross-establish capability."""

        return {
            kind: self.capability_receipt(kind)
            for kind in HyperProviderKind
        }

    def execute(
        self,
        request: HyperExecutionRequestV2 | Mapping[str, Any],
    ) -> HyperExecutionResultV2:
        """Execute one typed hyperproperty request on a single engine path."""

        req = (
            request
            if isinstance(request, HyperExecutionRequestV2)
            else HyperExecutionRequestV2(
                **_filter_keys(
                    _require_mapping(request, "request"),
                    {
                        "request_id",
                        "provider",
                        "document",
                        "system_model",
                        "traces",
                        "mode",
                        "allow_fallback",
                        "source_ref_ids",
                        "bounds",
                        "mock_output",
                        "fallback_output",
                        "available",
                        "confidence",
                        "fluent_text",
                        "metadata",
                        "schema_version",
                    },
                )
            )
        )
        request_digest = _digest_of(req.to_dict())
        document: HyperpropertyIR = req.document  # type: ignore[assignment]
        provider: HyperProviderKind = req.provider  # type: ignore[assignment]
        capability = self.capability_receipt(provider, document=document)

        # Mock path: never establishes hyperproperty authority.
        if req.has_mock_output or req.mode is HyperExecutionMode.MOCK:
            return self._rejected(
                req,
                request_digest=request_digest,
                disposition=HyperDisposition.MOCK_REJECTED,
                mode=HyperExecutionMode.MOCK,
                capability=capability,
                mock_output_present=True,
                fallback_output_present=req.has_fallback_output,
                diagnostics=(
                    "mock_output_cannot_establish_hyperproperty",
                    "mock_output_cannot_establish_proof",
                    "mock_output_cannot_establish_theorem",
                    "mock_output_cannot_establish_other_engine_capability",
                ),
            )

        # Explicit fallback payload path: never establishes hyperproperty.
        if req.has_fallback_output or req.mode is HyperExecutionMode.FALLBACK:
            return self._rejected(
                req,
                request_digest=request_digest,
                disposition=HyperDisposition.FALLBACK_REJECTED,
                mode=HyperExecutionMode.FALLBACK,
                capability=capability,
                mock_output_present=False,
                fallback_output_present=True,
                diagnostics=(
                    "fallback_output_cannot_establish_hyperproperty",
                    "fallback_output_cannot_establish_proof",
                    "fallback_output_cannot_establish_other_engine_capability",
                ),
            )

        # Capability probe only: discovery without a holds/violated claim.
        if req.mode is HyperExecutionMode.CAPABILITY_PROBE:
            return self._capability_only(
                req,
                request_digest=request_digest,
                capability=capability,
            )

        return self._execute_engine(
            req,
            request_digest=request_digest,
            capability=capability,
        )

    def execute_split_capabilities(
        self,
        document: HyperpropertyIR | Mapping[str, Any],
        *,
        request_id_prefix: str = "req:hyper:split",
        system_models: Mapping[str, bytes | str] | None = None,
        bounds: ExecutionBounds | None = None,
        allow_fallback: bool = False,
    ) -> dict[HyperProviderKind, HyperExecutionResultV2]:
        """Run each engine path independently; results never cross-establish."""

        doc = _document_from_value(document)
        models = dict(system_models or {})
        results: dict[HyperProviderKind, HyperExecutionResultV2] = {}
        for kind in HyperProviderKind:
            model = models.get(kind.value)
            req = HyperExecutionRequestV2(
                request_id=f"{request_id_prefix}:{kind.value}",
                provider=kind,
                document=doc,
                system_model=model,
                bounds=bounds,
                allow_fallback=allow_fallback,
                mode=HyperExecutionMode.ENGINE,
            )
            results[kind] = self.execute(req)
            # Explicit independence assertion on the live result.
            for other in HyperProviderKind:
                if other is kind:
                    continue
                if results[kind].evidence.establishes_other_engine(other):
                    raise HyperAuthorityError(
                        f"{kind.value} result established {other.value} capability"
                    )
        return results

    # --- internal paths ----------------------------------------------------

    def _execute_engine(
        self,
        req: HyperExecutionRequestV2,
        *,
        request_digest: str,
        capability: HyperCapabilityReceiptV2,
    ) -> HyperExecutionResultV2:
        document: HyperpropertyIR = req.document  # type: ignore[assignment]
        provider: HyperProviderKind = req.provider  # type: ignore[assignment]
        bounds: ExecutionBounds = req.bounds  # type: ignore[assignment]
        backend = self.backend(provider)

        try:
            outcome = backend.check(
                document,
                traces=req.traces or None,
                system_model=req.system_model,
                allow_fallback=req.allow_fallback,
            )
        except (HyperpropertyAdapterError, HyperpropertyValidationError, OSError, ValueError, TypeError) as error:
            # Keep engine/system/formula/bounds/witness bindings even when the
            # selected path cannot produce a holds/violated verdict.  Never
            # promote another engine's capability from this failure.
            formula = HyperFormulaBindingV2.from_document(document)
            system = HyperSystemBindingV2.from_request(
                provider=provider,
                document=document,
                system_model=req.system_model,
            )
            bounds_binding = HyperBoundsBindingV2.from_capability(
                capability_for(provider),
                bounds=bounds,
                document=document,
                semantics=HyperSemanticsKind.NONE,
            )
            witness = HyperWitnessBindingV2(
                status=HyperWitnessStatus.NONE,
                formula_id=document.formula.formula_id,
                observation_policy_id=document.information_flow_policy.policy_id,
            )
            evidence = HyperProviderEvidenceV2(
                evidence_id=f"ev:hyper:{req.request_id}",
                request_id=req.request_id,
                request_digest=request_digest,
                engine=provider,
                disposition=HyperDisposition.ERROR,
                mode=HyperExecutionMode.ENGINE,
                formula=formula,
                system=system,
                bounds=bounds_binding,
                witness=witness,
                capability=capability,
                source_ref_ids=req.source_ref_ids,
                result_status=ResultStatus.ERROR,
                hyperproperty_established=False,
                available=capability.available,
                confidence=req.confidence,
                fluent_text_present=bool(req.fluent_text),
                diagnostics=(
                    f"adapter_error:{type(error).__name__}:{error}",
                    "other_engine_capability_not_established",
                ),
            )
            return HyperExecutionResultV2(request=req, evidence=evidence)

        return self._from_outcome(
            req,
            request_digest=request_digest,
            capability=capability,
            outcome=outcome,
        )

    def _from_outcome(
        self,
        req: HyperExecutionRequestV2,
        *,
        request_digest: str,
        capability: HyperCapabilityReceiptV2,
        outcome: HyperCheckOutcome,
    ) -> HyperExecutionResultV2:
        document: HyperpropertyIR = req.document  # type: ignore[assignment]
        provider: HyperProviderKind = req.provider  # type: ignore[assignment]
        bounds: ExecutionBounds = req.bounds  # type: ignore[assignment]
        receipt = outcome.receipt
        translation = outcome.translation

        disposition = _status_to_disposition(receipt.status)
        result_status = _status_to_result_status(receipt.status)
        evidence_path = receipt.evidence_path

        if evidence_path is HyperEvidencePath.BOUNDED_SELF_COMPOSITION:
            semantics = HyperSemanticsKind.FALLBACK_BOUNDED
            mode = HyperExecutionMode.ENGINE  # backend fallback path, still engine mode
        elif evidence_path is HyperEvidencePath.ENGINE:
            semantics = HyperSemanticsKind.ENGINE_BOUNDED
            mode = HyperExecutionMode.ENGINE
        else:
            semantics = HyperSemanticsKind.FINITE_BOUNDED
            mode = HyperExecutionMode.ENGINE

        formula = HyperFormulaBindingV2.from_document(
            document, translation=translation
        )
        system = HyperSystemBindingV2.from_request(
            provider=provider,
            document=document,
            system_model=req.system_model,
            translation=translation,
            evidence_path=evidence_path,
        )
        bounds_binding = HyperBoundsBindingV2.from_capability(
            capability_for(provider),
            bounds=bounds,
            document=document,
            semantics=semantics,
            fallback=receipt.fallback_bounds,
        )
        witness = HyperWitnessBindingV2.from_outcome(
            document=document,
            disposition=disposition,
            evidence_path=evidence_path,
            counterexample=receipt.counterexample,
            observation_policy_id=system.observation_policy_id,
        )

        # Hyperproperty authority only for conclusive engine-path outcomes.
        hyper_ok = (
            evidence_path is HyperEvidencePath.ENGINE
            and disposition
            in {HyperDisposition.SATISFIED, HyperDisposition.VIOLATED}
            and not req.has_mock_output
            and not req.has_fallback_output
        )
        # Refresh capability from live receipt availability.
        live_capability = HyperCapabilityReceiptV2(
            engine=provider,
            available=bool(receipt.executable) or capability.available,
            supported_prefix=(
                disposition is not HyperDisposition.UNSUPPORTED
            ),
            capability=capability_for(provider).to_dict(),
            reason=receipt.reason if disposition is HyperDisposition.UNSUPPORTED else capability.reason,
            establishes_other_engines=False,
        )

        diagnostics: list[str] = []
        if disposition is HyperDisposition.UNAVAILABLE:
            diagnostics.append(f"{provider.value}_unavailable")
        if disposition is HyperDisposition.UNSUPPORTED:
            diagnostics.append(f"{provider.value}_unsupported_prefix_or_model")
        if evidence_path is HyperEvidencePath.BOUNDED_SELF_COMPOSITION:
            diagnostics.append("bounded_self_composition_non_authoritative")
        diagnostics.append("other_engine_capability_not_established")

        evidence = HyperProviderEvidenceV2(
            evidence_id=f"ev:hyper:{req.request_id}",
            request_id=req.request_id,
            request_digest=request_digest,
            engine=provider,
            disposition=disposition,
            mode=mode,
            formula=formula,
            system=system,
            bounds=bounds_binding,
            witness=witness,
            capability=live_capability,
            source_ref_ids=req.source_ref_ids,
            result_status=result_status,
            hyperproperty_established=hyper_ok,
            available=live_capability.available,
            confidence=req.confidence,
            fluent_text_present=bool(req.fluent_text),
            evidence_path=evidence_path,
            external_tool_proof=bool(hyper_ok and receipt.external_tool_proof),
            authorizes_universal_proof=False,
            receipt=_evidence_receipt_payload(receipt),
            diagnostics=tuple(diagnostics),
        )
        return HyperExecutionResultV2(
            request=req,
            evidence=evidence,
            backend_result=outcome.result,
            translation=translation,
        )

    def _rejected(
        self,
        req: HyperExecutionRequestV2,
        *,
        request_digest: str,
        disposition: HyperDisposition,
        mode: HyperExecutionMode,
        capability: HyperCapabilityReceiptV2,
        mock_output_present: bool,
        fallback_output_present: bool,
        diagnostics: tuple[str, ...],
    ) -> HyperExecutionResultV2:
        document: HyperpropertyIR = req.document  # type: ignore[assignment]
        provider: HyperProviderKind = req.provider  # type: ignore[assignment]
        bounds: ExecutionBounds = req.bounds  # type: ignore[assignment]
        formula = HyperFormulaBindingV2.from_document(document)
        system = HyperSystemBindingV2.from_request(
            provider=provider,
            document=document,
            system_model=req.system_model,
        )
        bounds_binding = HyperBoundsBindingV2.from_capability(
            capability_for(provider),
            bounds=bounds,
            document=document,
            semantics=HyperSemanticsKind.NONE,
        )
        witness = HyperWitnessBindingV2(
            status=HyperWitnessStatus.NONE,
            formula_id=document.formula.formula_id,
            observation_policy_id=document.information_flow_policy.policy_id,
        )
        evidence = HyperProviderEvidenceV2(
            evidence_id=f"ev:hyper:{req.request_id}",
            request_id=req.request_id,
            request_digest=request_digest,
            engine=provider,
            disposition=disposition,
            mode=mode,
            formula=formula,
            system=system,
            bounds=bounds_binding,
            witness=witness,
            capability=capability,
            source_ref_ids=req.source_ref_ids,
            result_status=ResultStatus.UNKNOWN,
            hyperproperty_established=False,
            mock_output_present=mock_output_present,
            fallback_output_present=fallback_output_present,
            available=req.available,
            confidence=req.confidence,
            fluent_text_present=bool(req.fluent_text),
            diagnostics=diagnostics,
        )
        return HyperExecutionResultV2(request=req, evidence=evidence)

    def _capability_only(
        self,
        req: HyperExecutionRequestV2,
        *,
        request_digest: str,
        capability: HyperCapabilityReceiptV2,
    ) -> HyperExecutionResultV2:
        document: HyperpropertyIR = req.document  # type: ignore[assignment]
        provider: HyperProviderKind = req.provider  # type: ignore[assignment]
        bounds: ExecutionBounds = req.bounds  # type: ignore[assignment]
        formula = HyperFormulaBindingV2.from_document(document)
        system = HyperSystemBindingV2.from_request(
            provider=provider,
            document=document,
            system_model=req.system_model,
        )
        bounds_binding = HyperBoundsBindingV2.from_capability(
            capability_for(provider),
            bounds=bounds,
            document=document,
            semantics=HyperSemanticsKind.CAPABILITY_ONLY,
        )
        witness = HyperWitnessBindingV2(
            status=HyperWitnessStatus.NONE,
            formula_id=document.formula.formula_id,
            observation_policy_id=document.information_flow_policy.policy_id,
        )
        evidence = HyperProviderEvidenceV2(
            evidence_id=f"ev:hyper:{req.request_id}",
            request_id=req.request_id,
            request_digest=request_digest,
            engine=provider,
            disposition=HyperDisposition.CAPABILITY_ONLY,
            mode=HyperExecutionMode.CAPABILITY_PROBE,
            formula=formula,
            system=system,
            bounds=bounds_binding,
            witness=witness,
            capability=capability,
            source_ref_ids=req.source_ref_ids,
            result_status=ResultStatus.UNKNOWN,
            hyperproperty_established=False,
            available=capability.available,
            confidence=req.confidence,
            fluent_text_present=bool(req.fluent_text),
            diagnostics=(
                "capability_probe_only",
                "other_engine_capability_not_established",
            ),
        )
        return HyperExecutionResultV2(request=req, evidence=evidence)


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------


def execute_hyper(
    document: HyperpropertyIR | Mapping[str, Any],
    *,
    provider: HyperProviderKind | str,
    request_id: str,
    system_model: bytes | str | None = None,
    traces: Sequence[ExecutionTrace] | None = None,
    allow_fallback: bool = False,
    bounds: ExecutionBounds | None = None,
    mock_output: Mapping[str, Any] | None = None,
    fallback_output: Mapping[str, Any] | None = None,
    available: bool = True,
    confidence: float = 0.0,
    fluent_text: str = "",
    engine: HyperExecutionEngineV2 | None = None,
) -> HyperExecutionResultV2:
    """Execute one hyperproperty document through HyperProviderEvidence@2."""

    gate = engine or HyperExecutionEngineV2()
    req = HyperExecutionRequestV2(
        request_id=request_id,
        provider=provider,
        document=document,
        system_model=system_model,
        traces=tuple(traces or ()),
        allow_fallback=allow_fallback,
        bounds=bounds,
        mock_output=mock_output,
        fallback_output=fallback_output,
        available=available,
        confidence=confidence,
        fluent_text=fluent_text,
        mode=HyperExecutionMode.ENGINE,
    )
    return gate.execute(req)


def execute_hyperltl(
    document: HyperpropertyIR | Mapping[str, Any],
    *,
    request_id: str,
    **kwargs: Any,
) -> HyperExecutionResultV2:
    return execute_hyper(
        document,
        provider=HyperProviderKind.HYPERLTL,
        request_id=request_id,
        **kwargs,
    )


def execute_autohyper(
    document: HyperpropertyIR | Mapping[str, Any],
    *,
    request_id: str,
    **kwargs: Any,
) -> HyperExecutionResultV2:
    return execute_hyper(
        document,
        provider=HyperProviderKind.AUTOHYPER,
        request_id=request_id,
        **kwargs,
    )


def execute_mchyper(
    document: HyperpropertyIR | Mapping[str, Any],
    *,
    request_id: str,
    system_model: bytes | str | None = None,
    **kwargs: Any,
) -> HyperExecutionResultV2:
    return execute_hyper(
        document,
        provider=HyperProviderKind.MCHYPER,
        request_id=request_id,
        system_model=system_model,
        **kwargs,
    )
