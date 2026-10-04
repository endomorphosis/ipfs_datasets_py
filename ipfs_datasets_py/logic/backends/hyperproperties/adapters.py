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

import hashlib
import json
import re
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
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
    normalize_execution_traces,
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
from ..resource_admission import ResourceAdmittedToolRunner
from ..python_admission import admitted_python_work
from ..smt.operation_budget import (
    MAX_OPERATION_TIMEOUT_MS,
    ProofOperationInterrupted,
    _Signals,
    current_proof_operation,
    proof_operation_scope,
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

_CANONICAL_BOUNDED_EVALUATOR = HyperpropertyIR.evaluate_bounded_noninterference


def _operation_checkpoint(phase: str) -> float | None:
    operation = current_proof_operation()
    return operation.checkpoint(phase) if operation is not None else None


DEFAULT_MAX_OUTPUT_BYTES: Final = 2 * 1024 * 1024
DEFAULT_MAX_ALTERNATIONS_HYPERLTL: Final = 4
DEFAULT_MAX_ALTERNATIONS_AUTOHYPER: Final = 2
DEFAULT_MAX_ALTERNATIONS_MCHYPER: Final = 2

# Estimates for a launcher and one sequential solver/tool chain, not OS caps.
HYPER_CPU_SLOTS: Final = 2
HYPER_PROCESS_SLOTS: Final = 4
HYPER_ADDRESS_SPACE_FLOOR_BYTES: Final = 2 * 1024**3
AUTOHYPER_ADDRESS_SPACE_FLOOR_BYTES: Final = 4 * 1024**3

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_UNSUPPORTED_LINES: Final = frozenset(
    (
        "unsupported alternation",
        "unsupported quantifier alternation",
        "unsupported quantifier",
        "too many alternations",
        "quantifier alternation not supported",
        "fragment not supported",
        "at most one quantifier alternation, starting with exists, allowed",
    )
)
_MCHYPER_PROVED_LINE = re.compile(
    r"^Property proved\.\s+Time\s*=\s*[0-9]+(?:\.[0-9]+)?\s+sec$"
)
_MCHYPER_VIOLATION_LINES: Final = frozenset(
    (
        "Counterexample found. Safety violation.",
        "Counterexample found. Liveness involved.",
    )
)
_AUTOHYPER_ERROR_BANNER: Final = "=========== ERROR ==========="
_NATIVE_SYMBOL = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _runtime_environment(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise HyperpropertyAdapterError(
            "runtime_environment must be a mapping"
        )
    environment: dict[str, str] = {}
    for raw_name, raw_value in value.items():
        if (
            not isinstance(raw_name, str)
            or not raw_name
            or "=" in raw_name
            or "\x00" in raw_name
            or not isinstance(raw_value, str)
            or "\x00" in raw_value
        ):
            raise HyperpropertyAdapterError(
                "runtime_environment entries must be valid NUL-free strings"
            )
        environment[raw_name] = raw_value
    return environment


def _native_identity_payload(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        if isinstance(payload, Mapping):
            return dict(payload)
    raise HyperpropertyAdapterError(
        "engine_identity must be a mapping or expose to_dict()"
    )


def _validated_native_identity(
    value: object,
    *,
    engine: HyperEngine,
) -> tuple[str, dict[str, str], str]:
    """Consume a hash-bound vendor identity without importing its installer."""

    payload = _native_identity_payload(value)
    if payload.get("tool_id") != engine.value:
        raise HyperpropertyAdapterError(
            f"engine_identity tool_id must be {engine.value!r}"
        )
    if (
        payload.get("is_vendor_build") is not True
        or payload.get("is_upstream_build") is not True
        or payload.get("is_hermetic_engine") is not False
        or payload.get("authorizes_universal_proof") is not False
        or payload.get("authority_ceiling") != "bounded"
        or payload.get("executable_kind")
        not in {"upstream_compiled_binary", "upstream_python_entrypoint"}
    ):
        raise HyperpropertyAdapterError(
            "engine_identity must be an audited bounded upstream vendor build"
        )
    executable_text = _text(payload.get("executable", ""), "engine executable")
    try:
        executable = Path(executable_text).resolve(strict=True)
    except OSError as exc:
        raise HyperpropertyAdapterError(
            "engine_identity executable is unavailable"
        ) from exc
    if not executable.is_file():
        raise HyperpropertyAdapterError(
            "engine_identity executable must be a file"
        )
    artifact_sha = _digest(
        payload.get("artifact_sha256", ""), "engine artifact_sha256"
    )
    if _sha256_file(executable) != artifact_sha:
        raise HyperpropertyAdapterError(
            "engine_identity executable digest does not match the artifact"
        )
    environment = _runtime_environment(payload.get("runtime_environment") or {})
    version = _text(payload.get("version", ""), "engine version")
    return str(executable), environment, version


def _native_symbol(value: str, *, field_name: str) -> str:
    """Restrict generated formulas to symbols accepted by all native parsers.

    MCHyper's Python 2 wrapper interpolates its formula into an internal shell
    command.  The strict shared alphabet therefore also prevents quotes,
    separators, substitutions, and control characters from reaching it.
    """

    if not _NATIVE_SYMBOL.fullmatch(value):
        raise HyperpropertyAdapterError(
            f"{field_name} {value!r} is not a portable native prover symbol"
        )
    return value


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
        "The .NET runtime is incompatible with finite RLIMIT_FSIZE; AutoHyper "
        "uses the post-run workspace bound while retaining other lifecycle bounds.",
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
        object.__setattr__(self, "observation_kinds", FrozenMap(kinds))

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
    bindings: tuple[Mapping[str, Any], ...]

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
        # Rows contain only the scalar QuantifierBinding contract. Validate
        # before recursive freezing so malformed cycles cannot recurse here.
        for item in self.bindings:
            try:
                QuantifierBinding.from_dict(item)
            except (HyperpropertyValidationError, TypeError, ValueError) as error:
                raise HyperpropertyAdapterError("invalid quantifier binding row") from error
        object.__setattr__(
            self,
            "bindings",
            tuple(FrozenMap(item) for item in self.bindings),
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
            "bindings": [item.to_dict() for item in self.bindings],
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
        object.__setattr__(self, "auxiliary_files", FrozenMap(aux))
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
        observation_map: ObservationMap | None = None,
        quantifier_order: QuantifierOrder | None = None,
        formula_id: str | None = None,
    ) -> WitnessTraceBundle:
        """Build only a context-checked structural projection, not model replay.

        A caller-supplied ``replayed`` flag is not validation evidence. Native
        bundles require the actual request's maps and formula identity.
        """
        if observation_map is None or quantifier_order is None or formula_id is None:
            raise HyperpropertyAdapterError("witness bundle requires observation, quantifier and formula context")
        checked = replay_hyper_counterexample(self, observation_map, quantifier_order,
                                             formula_id=formula_id)
        if not checked.replayed:
            raise HyperpropertyAdapterError("counterexample failed structural projection validation")
        return WitnessTraceBundle(
            bundle_id=bundle_id,
            role=WitnessRole.COUNTEREXAMPLE,
            formula_id=self.formula_id,
            traces=self.traces,
            differences=self.differences,
            observed_fields=self.observed_fields,
            description="Structurally checked observation projection; native model membership and temporal semantics unvalidated",
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
    """Render the exact reviewed syntax accepted by one native engine."""

    if not isinstance(document, HyperpropertyIR):
        raise HyperpropertyAdapterError("document must be a HyperpropertyIR")
    formula = document.formula
    policy = document.information_flow_policy
    names_by_id = {item.variable_id: item.name for item in formula.variables}
    ordered_names = [
        _native_symbol(
            names_by_id[item.variable_id], field_name="trace variable"
        )
        for item in formula.quantifier_prefix
    ]
    fields = tuple(
        _native_symbol(item, field_name="information-flow field")
        for item in (
            *policy.low_input_fields,
            *policy.observation_fields,
        )
    )
    low_fields = fields[: len(policy.low_input_fields)]
    observation_fields = fields[len(policy.low_input_fields) :]
    if len(ordered_names) < 2:
        raise HyperpropertyAdapterError(
            "native information-flow translation requires at least two traces"
        )
    left, right = ordered_names[0], ordered_names[1]

    if engine is HyperEngine.MCHYPER:
        def atom(field: str) -> str:
            return f'Eq (AP "{field}" 0) (AP "{field}" 1)'

        def conjunction(items: Sequence[str]) -> str:
            if not items:
                return "Const True"
            result = items[-1]
            for item in reversed(items[:-1]):
                result = f"And ({item}) ({result})"
            return result

        body = (
            "G (Implies "
            f"({conjunction(tuple(atom(item) for item in low_fields))}) "
            f"({conjunction(tuple(atom(item) for item in observation_fields))}))"
        )
        rendered = body
        for binding in reversed(formula.quantifier_prefix):
            constructor = (
                "Forall"
                if binding.quantifier is TraceQuantifier.FORALL
                else "Exists"
            )
            rendered = f"{constructor} ({rendered})"
        return rendered

    quantifiers = " ".join(
        f"{binding.quantifier.value} {names_by_id[binding.variable_id]}."
        for binding in formula.quantifier_prefix
    )

    if engine is HyperEngine.AUTOHYPER:
        def atom(field: str) -> str:
            return f'{{"{field}"_{left} = "{field}"_{right}}}'

        true = "1"
    else:
        def atom(field: str) -> str:
            return f"({field}_{left} <-> {field}_{right})"

        true = "True"

    low = " & ".join(atom(item) for item in low_fields) or true
    observations = (
        " & ".join(atom(item) for item in observation_fields) or true
    )
    return f"{quantifiers} G (({low}) -> ({observations}))\n"


def _autohyper_explicit_system(document: HyperpropertyIR) -> str:
    """Minimal explicit system package for AutoHyper-style tooling."""

    policy = document.information_flow_policy
    variables = tuple(
        dict.fromkeys(
            _native_symbol(item, field_name="AutoHyper system variable")
            for item in (
                *policy.low_input_fields,
                *policy.observation_fields,
            )
        )
    ) or ("observable",)
    declarations = " ".join(f'("{name}" Bool)' for name in variables)
    false_values = " ".join(f'("{name}" false)' for name in variables)
    true_values = " ".join(f'("{name}" true)' for name in variables)
    return (
        f"Variables: {declarations}\n"
        "Init: 0 1\n"
        "--BODY--\n"
        f"State: 0 {{{false_values}}}\n"
        "0\n"
        f"State: 1 {{{true_values}}}\n"
        "1\n"
        "--END--\n"
    )


_MAX_COUNTEREXAMPLE_BYTES: Final = DEFAULT_MAX_OUTPUT_BYTES
_MAX_COUNTEREXAMPLE_LINES: Final = 4096
_MAX_COUNTEREXAMPLE_FIELDS: Final = 256
_MAX_COUNTEREXAMPLE_TRACES: Final = 8


def _counterexample_maps_valid(
    observation_map: ObservationMap, quantifier_order: QuantifierOrder,
) -> bool:
    """Check context consistency before interpreting any untrusted trace text."""
    if not isinstance(observation_map, ObservationMap) or not isinstance(quantifier_order, QuantifierOrder):
        return False
    groups = (observation_map.low_input_fields, observation_map.high_input_fields,
              observation_map.observation_fields, observation_map.subject_fields)
    if sum(map(len, groups)) > _MAX_COUNTEREXAMPLE_FIELDS or any(len(g) != len(set(g)) for g in groups):
        return False
    if set(observation_map.high_input_fields) & set().union(groups[0], groups[2], groups[3]):
        return False
    order = quantifier_order
    if not (0 < len(order.variable_ids) <= _MAX_COUNTEREXAMPLE_TRACES
            and len(order.variable_ids) == len(set(order.variable_ids))
            and len(order.variable_names) == len(set(order.variable_names))):
        return False
    try:
        bindings = tuple(QuantifierBinding.from_dict(row) for row in order.bindings)
    except (ValueError, TypeError, KeyError):
        return False
    return (len({row.binding_id for row in bindings}) == len(bindings)
            and all(row.index == i and row.variable_id == order.variable_ids[i]
                    and row.quantifier.value == order.signature[i] for i, row in enumerate(bindings)))


def _trace_differences(
    traces: tuple[WitnessTrace, ...], observation_map: ObservationMap,
) -> tuple[ObservationDifference, ...]:
    if len(traces) < 2:
        return ()
    left, right = traces[:2]
    return tuple(ObservationDifference(field=name,
        left_digest="sha256:" + _content_digest(left.observations[name]),
        right_digest="sha256:" + _content_digest(right.observations[name]))
        for name in observation_map.observation_fields
        if left.observations[name] != right.observations[name])


def parse_hyper_counterexample(
    output: str,
    *,
    formula_id: str,
    observation_map: ObservationMap,
    quantifier_order: QuantifierOrder,
) -> HyperCounterexampleTrace | None:
    """Parse complete, unambiguous native TRACE records within finite limits.

    Labels must name declared variables. Assignments cover the complete approved
    projection exactly once. Optional DIFF rows must agree with actual values in
    declaration order. No missing value, trace or difference is fabricated.
    Returned raw text contains only approved assignments, without engine logs.
    Parsing alone does not validate a counterexample or native model membership.
    """
    if (not isinstance(output, str) or len(output) > _MAX_COUNTEREXAMPLE_BYTES
            or not output.strip() or "\x00" in output
            or not _counterexample_maps_valid(observation_map, quantifier_order)):
        return None
    try:
        if len(output.encode("utf-8")) > _MAX_COUNTEREXAMPLE_BYTES:
            return None
    except UnicodeEncodeError:
        return None
    # Accept LF and CRLF records; other control/separator characters must not
    # manufacture trace boundaries or hide extra assignments.
    normalized = output.replace("\r\n", "\n")
    if any((ord(char) < 32 and char not in "\n\t")
           or char in "\x7f\x85\u2028\u2029" for char in normalized):
        return None
    lines = normalized.split("\n")
    if len(lines) > _MAX_COUNTEREXAMPLE_LINES:
        return None
    approved = {"public": set(observation_map.low_input_fields),
                "obs": set(observation_map.observation_fields),
                "subject": set(observation_map.subject_fields)}
    labels = dict(zip(quantifier_order.variable_names, quantifier_order.variable_ids))
    records, supplied_diffs = {}, {}
    current = None
    for raw_line in lines:
        _operation_checkpoint("hyper counterexample parsing")
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        header = re.fullmatch(r"TRACE\s+([A-Za-z0-9_.:/-]+)\s*:", line)
        if header:
            name = header.group(1)
            if name not in labels or name in records:
                return None
            records[name] = {group: {} for group in approved}
            current = records[name]
            continue
        if line.startswith("TRACE"):
            return None
        if line.startswith("DIFF"):
            difference = re.fullmatch(r"DIFF\s+field=(\S+)\s+left=(\S+)\s+right=(\S+)", line)
            if difference is None or current is None:
                return None
            name, left, right = difference.groups()
            if name not in approved["obs"] or name in supplied_diffs:
                return None
            supplied_diffs[name] = (left, right)
            continue
        if current is None:
            # Engine verdicts/log headers are not retained as witness data.
            continue
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not key or not value:
            return None
        group, dot, name = key.partition(".")
        if group in approved and dot:
            candidates = [(group, name)] if name in approved[group] else []
        else:
            candidates = [(group, key) for group, fields in approved.items() if key in fields]
        if len(candidates) != 1:
            return None
        group, name = candidates[0]
        if name in current[group]:
            return None
        current[group][name] = value
    if set(records) != set(labels):
        return None
    if any(set(record[group]) != fields for record in records.values() for group, fields in approved.items()):
        return None
    try:
        traces = tuple(WitnessTrace.from_execution(trace_id="trace:" + name, variable_id=labels[name],
            public_inputs=records[name]["public"], observations=records[name]["obs"],
            subject=records[name]["subject"]) for name in quantifier_order.variable_names)
        differences = _trace_differences(traces, observation_map)
        if supplied_diffs:
            if len(traces) < 2:
                return None
            left, right = traces[:2]
            for name, values in supplied_diffs.items():
                if (values != (left.observations[name], right.observations[name])
                        or values[0] == values[1]):
                    return None
        canonical = []
        for name in quantifier_order.variable_names:
            canonical.append("TRACE " + name + ":")
            for group, fields in (("public", observation_map.low_input_fields),
                                  ("obs", observation_map.observation_fields),
                                  ("subject", observation_map.subject_fields)):
                canonical.extend("  " + group + "." + field + " = " + records[name][group][field]
                                 for field in fields)
        return HyperCounterexampleTrace(formula_id=formula_id,
            observation_policy_id=observation_map.policy_id, observed_fields=observation_map.observation_fields,
            traces=traces, differences=differences, raw="\n".join(canonical) + "\n")
    except (HyperpropertyValidationError, HyperpropertyAdapterError, TypeError, KeyError):
        return None


def replay_hyper_counterexample(
    counterexample: HyperCounterexampleTrace,
    observation_map: ObservationMap,
    quantifier_order: QuantifierOrder,
    *,
    formula_id: str | None = None,
) -> HyperCounterexampleTrace:
    """Validate a two-forall structural observation projection against context.

    The legacy ``replayed`` flag means only this finite structural check. It does
    not attest native system reachability, temporal semantics, high-input
    variation, or authenticity of solver output. Caller flags/notes are ignored.
    Native raw records are reparsed to detect omitted or altered assignments.
    """
    if not isinstance(counterexample, HyperCounterexampleTrace):
        raise HyperpropertyAdapterError("counterexample must be a HyperCounterexampleTrace")
    notes = []
    if not _counterexample_maps_valid(observation_map, quantifier_order):
        return replace(counterexample, replayed=False, replay_notes=("invalid observation or quantifier context",))
    if (len(counterexample.traces) != len(quantifier_order.variable_ids)
            or len(counterexample.differences) > len(observation_map.observation_fields)
            or len(counterexample.observed_fields) > _MAX_COUNTEREXAMPLE_FIELDS):
        return replace(counterexample, replayed=False,
                       replay_notes=("counterexample containers exceed the approved projection",))
    if formula_id is None or counterexample.formula_id != formula_id:
        notes.append("missing or mismatched expected formula identity")
    if counterexample.observation_policy_id != observation_map.policy_id:
        notes.append("observation policy identity mismatch")
    if counterexample.observed_fields != observation_map.observation_fields:
        notes.append("observed fields differ from the approved ordered projection")
    if quantifier_order.signature != ("forall", "forall"):
        notes.append("structural pair validation requires exactly two forall variables")
    parsed = parse_hyper_counterexample(counterexample.raw,
        formula_id=formula_id or counterexample.formula_id,
        observation_map=observation_map, quantifier_order=quantifier_order)
    if parsed is None:
        notes.append("native TRACE records are absent, incomplete, malformed or exceed limits")
    else:
        if tuple(row.to_dict() for row in counterexample.traces) != tuple(row.to_dict() for row in parsed.traces):
            notes.append("trace labels, values or digests do not match the complete raw projection")
        if counterexample.differences != parsed.differences:
            notes.append("difference fields or digests do not match actual observations")
        if len(parsed.traces) == 2:
            left, right = parsed.traces
            if left.public_inputs != right.public_inputs:
                notes.append("traces have different low-input projections")
            if left.subject != right.subject:
                notes.append("traces have different subject projections")
        if not parsed.differences:
            notes.append("no genuine approved observation difference")
    valid = not notes
    if valid:
        notes.append("replayed observations: " + ", ".join(observation_map.observation_fields))
    notes.append("structural projection only; native model membership, temporal semantics and high-input variation unvalidated")
    return replace(counterexample, replayed=valid, replay_notes=tuple(notes))


class HyperpropertyBackend:
    """Shared lifecycle with lazy resource admission for owned default runners.

    Explicit runners retain caller-owned admission and resource profiles.
    Discovery is inert; owned execution never starts a second version process.
    """

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
        engine_identity: object | None = None,
        runtime_environment: Mapping[str, str] | None = None,
    ) -> None:
        self._managed_runner = runner is None
        self._runner = runner if runner is not None else ResourceAdmittedToolRunner(
            cpu_slots=HYPER_CPU_SLOTS, child_process_slots=HYPER_PROCESS_SLOTS,
        )
        self._which = which
        if engine_identity is not None and (
            executable is not None or runtime_environment is not None
        ):
            raise HyperpropertyAdapterError(
                "engine_identity cannot be combined with executable or "
                "runtime_environment overrides"
            )
        self._identity_version = ""
        if engine_identity is not None:
            (
                self._executable,
                self._runtime_environment,
                self._identity_version,
            ) = _validated_native_identity(
                engine_identity,
                engine=self.engine,
            )
        else:
            self._executable = executable
            self._runtime_environment = _runtime_environment(
                runtime_environment or {}
            )

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
            losses.append(
                "The bundled two-state explicit system is a smoke-test "
                "abstraction; pass system_model for software-specific evidence."
            )
        elif self.engine is HyperEngine.MCHYPER:
            losses.append(
                "MCHyper execution requires a caller-supplied AIGER system model."
            )
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
        bounds: ExecutionBounds | None = None,
        traces: Sequence[ExecutionTrace] | None = None,
        system_model: bytes | str | None = None,
        allow_fallback: bool = False,
        cancellation: CancellationSignal | None = None,
    ) -> HyperCheckOutcome:
        """Observe any enclosing proof operation without changing declared bounds.

        Standalone direct checks retain their existing invocation limits. V2 and
        registry scopes also bound preparation, metadata and receipt publication.
        Opaque Python work remains cooperative at callback boundaries.
        """
        _operation_checkpoint("before hyper check")
        operation = current_proof_operation()
        if operation is not None:
            cancellation = (operation if cancellation is None or cancellation is operation
                            else _Signals(operation, cancellation))
        try:
            outcome = self._check(document, request=request, bounds=bounds,
                traces=traces, system_model=system_model, allow_fallback=allow_fallback,
                cancellation=cancellation)
        except Exception:
            _operation_checkpoint("hyper check exception boundary")
            raise
        _operation_checkpoint("after hyper receipt construction")
        return outcome

    def _check(
        self,
        document: HyperpropertyIR,
        *,
        request: BackendRequest | None = None,
        bounds: ExecutionBounds | None = None,
        traces: Sequence[ExecutionTrace] | None = None,
        system_model: bytes | str | None = None,
        allow_fallback: bool = False,
        cancellation: CancellationSignal | None = None,
    ) -> HyperCheckOutcome:
        if bounds is not None and not isinstance(bounds, ExecutionBounds):
            raise HyperpropertyAdapterError("bounds must be ExecutionBounds")
        if request is not None and bounds is not None and bounds != request.bounds:
            raise HyperpropertyAdapterError("bounds must match request.bounds")
        document = _document_from_value(document)
        _operation_checkpoint("after hyper document normalization")
        translation = self.translate(document)
        _operation_checkpoint("after hyper translation")
        request_digest = (
            request.digest
            if request is not None
            else translation.document_digest
        )
        bounds = (
            request.bounds
            if request is not None
            else bounds if bounds is not None
            else ExecutionBounds(timeout_ms=10_000, max_steps=1_000)
        )

        _operation_checkpoint("before hyper prefix check")
        supported, unsupported_reason = self.supports_prefix(document)
        _operation_checkpoint("after hyper prefix check")
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
                    receipt, request=request, bounds=bounds, document=document
                ),
                receipt=receipt,
                translation=translation,
                interface_version=self.backend_version,
            )

        probe = self.probe()
        _operation_checkpoint("after hyper discovery")
        if not probe.available:
            if allow_fallback and self.capability.supports_self_composition_fallback:
                return self._fallback_outcome(
                    document,
                    translation=translation,
                    request=request,
                    request_digest=request_digest,
                    bounds=bounds,
                    traces=traces,
                    cancellation=cancellation,
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
                    receipt, request=request, bounds=bounds, document=document
                ),
                receipt=receipt,
                translation=translation,
                interface_version=self.backend_version,
            )

        if self.engine is HyperEngine.MCHYPER and system_model is None:
            receipt = self._terminal_receipt(
                document=document,
                translation=translation,
                status=HyperCheckOutcomeStatus.UNSUPPORTED,
                evidence_path=HyperEvidencePath.NONE,
                reason=(
                    "mchyper requires an explicit AIGER .aag/.aig system "
                    "model; no model check ran"
                ),
                bounds=bounds,
            )
            return HyperCheckOutcome(
                request_digest=request_digest,
                result=self._result_from_receipt(
                    receipt, request=request, bounds=bounds, document=document
                ),
                receipt=receipt,
                translation=translation,
                interface_version=self.backend_version,
            )

        executable = probe.executable_path
        timeout_seconds = max(0.001, bounds.timeout_ms / 1000.0)
        formula_name = "property.hltl"
        input_files: dict[str, bytes | str] = {
            formula_name: translation.formula_text
        }
        input_files.update(
            {name: text for name, text in translation.auxiliary_files.items()}
        )
        if self.engine is HyperEngine.HYPERLTL:
            argv = (executable, "-f", formula_name)
        elif self.engine is HyperEngine.AUTOHYPER:
            if system_model is not None:
                if not isinstance(system_model, (bytes, str)):
                    raise HyperpropertyAdapterError(
                        "AutoHyper system_model must be bytes or text"
                    )
                input_files["system.explicit"] = system_model
            argv = (
                executable,
                "--explicit",
                "system.explicit",
                formula_name,
            )
        else:
            if not isinstance(system_model, (bytes, str)):
                raise HyperpropertyAdapterError(
                    "MCHyper system_model must be bytes or text"
                )
            input_files.pop(formula_name, None)
            input_files["system.aag"] = system_model
            argv = (
                executable,
                "-f",
                translation.formula_text,
                "system.aag",
                "-pdr",
                "-cex",
                "--cex_file",
                "counterexample.txt",
                "-v",
                "1",
            )

        input_size = sum(
            len(
                content
                if isinstance(content, bytes)
                else content.encode("utf-8")
            )
            for content in input_files.values()
        )
        max_input_bytes = max(input_size, 4096)
        # RSS is the admitted memory estimate and a sampled process-tree guard.
        # Managed runtimes need separate virtual-address-space headroom. Neither
        # this allowance nor sampled RSS establishes hard aggregate containment.
        memory_bytes = None
        resident_memory_bytes = None
        environment = dict(self._runtime_environment)
        if self._managed_runner:
            resident_memory_bytes = bounds.max_memory_bytes
            floor = (AUTOHYPER_ADDRESS_SPACE_FLOOR_BYTES
                     if self.engine is HyperEngine.AUTOHYPER
                     else HYPER_ADDRESS_SPACE_FLOOR_BYTES)
            memory_bytes = max(floor, 4 * bounds.max_memory_bytes)
            environment.pop("GHCRTS", None)
            if self.engine is HyperEngine.AUTOHYPER:
                # Reviewed .NET controls are owned by this execution profile.
                # Remove aliases/per-heap overrides that could defeat it.
                for name in tuple(environment):
                    if name.startswith(("DOTNET_GC", "COMPlus_GC", "DOTNET_gc", "COMPlus_gc")):
                        del environment[name]
                environment.update({
                    "DOTNET_PROCESSOR_COUNT": "1",
                    "DOTNET_gcServer": "0",
                    "DOTNET_GCHeapHardLimit": format(max(1, bounds.max_memory_bytes // 2), "x"),
                })
        remaining = _operation_checkpoint("before hyper native execution")
        effective_timeout = (min(timeout_seconds, remaining)
                             if remaining is not None else timeout_seconds)
        limits = ToolRunLimits(
            timeout_seconds=effective_timeout,
            cpu_seconds=effective_timeout if self._managed_runner else None,
            memory_bytes=memory_bytes,
            resident_memory_bytes=resident_memory_bytes,
            max_output_bytes=min(bounds.max_output_bytes, DEFAULT_MAX_OUTPUT_BYTES),
            max_input_bytes=max_input_bytes,
            max_workspace_bytes=max(16_777_216, max_input_bytes * 2),
            enforce_file_size_limit=(
                self.engine is not HyperEngine.AUTOHYPER
            ),
        )
        process = self._runner.run(
            ToolRunRequest(
                argv=argv,
                runtime=ToolRuntime.NATIVE,
                limits=limits,
                input_files=input_files,
                output_paths=("counterexample.txt", "witness.txt"),
                environment=environment,
            ),
            cancellation=cancellation,
        )
        _operation_checkpoint("after hyper native execution")
        combined = "\n".join(
            part for part in (process.stdout, process.stderr) if part
        )
        status, reason = self._classify(
            process, combined, max_output_bytes=limits.max_output_bytes,
        )
        _operation_checkpoint("after hyper verdict classification")
        version = self._identity_version
        if (not version and not self._managed_runner
                and self._lifecycle_failure(process, limits.max_output_bytes) is None
                and type(process.returncode) is int and process.returncode == 0):
            _operation_checkpoint("before hyper version metadata")
            version = self._tool_version(
                executable, environment=self._runtime_environment,
                cancellation=cancellation,
            )
            _operation_checkpoint("after hyper version metadata")
        counterexample: HyperCounterexampleTrace | None = None
        if status is HyperCheckOutcomeStatus.VIOLATED:
            supplemental = ""
            for name in ("counterexample.txt", "witness.txt"):
                raw = process.output_files.get(name)
                if raw:
                    supplemental = raw.decode("utf-8", errors="replace")
                    break
            _operation_checkpoint("before hyper counterexample parsing")
            parsed = parse_hyper_counterexample(
                supplemental or combined,
                formula_id=document.formula.formula_id,
                observation_map=translation.observation_map,
                quantifier_order=translation.quantifier_order,
            )
            _operation_checkpoint("after hyper counterexample parsing")
            if parsed is not None:
                counterexample = replay_hyper_counterexample(
                    parsed,
                    translation.observation_map,
                    translation.quantifier_order,
                    formula_id=document.formula.formula_id,
                )
                _operation_checkpoint("after hyper counterexample replay")
            else:
                reason = (
                    reason
                    + "; counterexample records absent, malformed, incomplete or over limits; no structural witness validated"
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
            # Receipt text excludes NUL; process metadata retains raw digests.
            stdout=process.stdout.replace("\x00", "\ufffd"),
            stderr=process.stderr.replace("\x00", "\ufffd"),
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
                receipt, request=request, bounds=bounds, document=document, process=process,
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
        # Keep immutable payload fields in place until bounded normalization;
        # exporting the whole payload would first copy every private trace.
        payload = request.payload
        document = payload.get("document") or payload.get("hyperproperty")
        if document is None:
            raise HyperpropertyAdapterError(
                "request payload must include document or hyperproperty"
            )
        traces_payload = payload.get("traces") or ()
        try:
            traces = ()
            if traces_payload:
                with proof_operation_scope(timeout_ms=min(request.bounds.timeout_ms, MAX_OPERATION_TIMEOUT_MS),
                                           cancellation=cancellation):
                    traces = normalize_execution_traces(traces_payload, allow_mappings=True,
                        require_trace_ids=True, checkpoint=_operation_checkpoint)
        except HyperpropertyValidationError:
            raise HyperpropertyAdapterError("invalid or excessive trace inputs") from None
        allow_fallback = bool(payload.get("allow_fallback", False))
        system_model = payload.get("system_model")
        if system_model is None and self.engine is HyperEngine.AUTOHYPER:
            system_model = payload.get("autohyper_explicit_system")
        if system_model is None and self.engine is HyperEngine.MCHYPER:
            system_model = (
                payload.get("mchyper_aiger")
                or payload.get("aiger_model")
            )
        return self.check(
            document,
            request=request,
            traces=traces,
            system_model=system_model,
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
        cancellation: CancellationSignal | None = None,
    ) -> HyperCheckOutcome:
        with proof_operation_scope(timeout_ms=min(bounds.timeout_ms, MAX_OPERATION_TIMEOUT_MS),
                                   cancellation=cancellation):
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
                        receipt, request=request, bounds=bounds, document=document
                    ),
                    receipt=receipt,
                    translation=translation,
                    interface_version=self.backend_version,
                )

            with admitted_python_work(memory_bytes=bounds.max_memory_bytes) as checkpoint:
                try:
                    checkpoint("before bounded fallback evaluation")
                    evaluate = document.evaluate_bounded_noninterference
                    if getattr(evaluate, "__func__", None) is _CANONICAL_BOUNDED_EVALUATOR:
                        evaluation = evaluate(traces, checkpoint=checkpoint)
                    else:
                        # Preserve legacy callback signatures; opaque work is only
                        # cooperative at its boundaries. V2 verifies canonical output.
                        evaluation = evaluate(traces)
                    checkpoint("after bounded fallback evaluation")
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
                            receipt, request=request, bounds=bounds, document=document
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
                        receipt, request=request, bounds=bounds, document=document,
                        fallback_bundle=evaluation.witness_bundle if counterexample is not None else None,
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

    def _lifecycle_failure(
        self, process: ToolRunResult, max_output_bytes: int,
    ) -> tuple[HyperCheckOutcomeStatus, str] | None:
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
        normal_exit = process.termination_reason in {"", "completed"} or (
            process.termination_reason == "nonzero_exit"
            and type(process.returncode) is int and process.returncode != 0
        )
        if (process.resource_exhausted or process.workspace_limit_exceeded
                or process.error or process.process_tree_terminated
                or not process.workspace_cleaned or not normal_exit):
            return (
                HyperCheckOutcomeStatus.ERROR,
                process.error or f"{self.engine.value} did not complete a clean bounded lifecycle",
            )
        output_bytes = len(process.stdout.encode("utf-8")) + len(process.stderr.encode("utf-8"))
        if process.output_truncated or output_bytes > max_output_bytes:
            return (
                HyperCheckOutcomeStatus.UNKNOWN,
                f"{self.engine.value} output exceeded the declared capture bound",
            )
        if "\x00" in process.stdout or "\x00" in process.stderr:
            return (HyperCheckOutcomeStatus.ERROR, "engine output contains NUL bytes")
        return None

    def _classify(
        self, process: ToolRunResult, combined: str, *,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    ) -> tuple[HyperCheckOutcomeStatus, str]:
        failure = self._lifecycle_failure(process, max_output_bytes)
        if failure is not None:
            return failure
        lines = tuple(
            line.strip() for line in combined.splitlines() if line.strip()
        )
        folded_lines = {line.casefold() for line in lines}
        if folded_lines & _UNSUPPORTED_LINES:
            return (
                HyperCheckOutcomeStatus.UNSUPPORTED,
                f"{self.engine.value} reported unsupported quantifier/fragment",
            )
        if type(process.returncode) is not int or process.returncode != 0:
            return (
                HyperCheckOutcomeStatus.ERROR,
                f"{self.engine.value} exited with code {process.returncode}",
            )

        diagnostic = False
        satisfied = False
        violated = False
        if self.engine is HyperEngine.HYPERLTL:
            # EAHyper's non-verbose satisfiability mode emits one exact,
            # lowercase token.  Formula text and diagnostics are deliberately
            # not searched for verdict substrings.
            satisfied = "sat" in lines
            violated = "unsat" in lines
        elif self.engine is HyperEngine.AUTOHYPER:
            # AutoHyper's reviewed CLI contract terminates with an uppercase
            # SAT/UNSAT line and prints a conspicuous error banner on caught
            # exceptions (which otherwise still exit zero).
            diagnostic = _AUTOHYPER_ERROR_BANNER in lines
            satisfied = "SAT" in lines
            violated = "UNSAT" in lines
        else:
            # MCHyper passes ABC's anchored success line through at -v 1 and
            # emits one of two exact counterexample lines itself.
            diagnostic = any(
                line.startswith(
                    (
                        "Error:",
                        "Error (",
                        "Tool error:",
                        "Parsing error ",
                    )
                )
                for line in lines
            )
            satisfied = any(
                _MCHYPER_PROVED_LINE.fullmatch(line) is not None
                for line in lines
            )
            violated = bool(set(lines) & _MCHYPER_VIOLATION_LINES)

        if diagnostic:
            return (
                HyperCheckOutcomeStatus.ERROR,
                f"{self.engine.value} emitted a reviewed error diagnostic",
            )
        if satisfied and violated:
            return (
                HyperCheckOutcomeStatus.UNKNOWN,
                f"{self.engine.value} emitted conflicting verdict tokens",
            )
        if violated:
            return (
                HyperCheckOutcomeStatus.VIOLATED,
                f"{self.engine.value} reported a hyperproperty violation",
            )
        if satisfied:
            return (
                HyperCheckOutcomeStatus.SATISFIED,
                f"{self.engine.value} reported the hyperproperty holds under its model",
            )
        return (
            HyperCheckOutcomeStatus.UNKNOWN,
            f"{self.engine.value} completed without a recognized verdict",
        )

    def _tool_version(
        self,
        executable: str,
        *,
        environment: Mapping[str, str] | None = None,
        cancellation: CancellationSignal | None = None,
    ) -> str:
        remaining = _operation_checkpoint("before hyper version probe")
        if self._managed_runner:
            return self._identity_version
        timeout = DEFAULT_VERSION_TIMEOUT_SECONDS
        if remaining is not None:
            timeout = min(timeout, remaining)
        try:
            result = self._runner.run(
                ToolRunRequest(
                    argv=(executable, "--version"),
                    runtime=ToolRuntime.NATIVE,
                    limits=ToolRunLimits(
                        timeout_seconds=timeout,
                        max_output_bytes=16_384,
                    ),
                    environment=environment or {},
                ),
                cancellation=cancellation,
            )
            _operation_checkpoint("after hyper version probe")
        except ProofOperationInterrupted:
            raise
        except Exception:  # pragma: no cover - defensive
            _operation_checkpoint("hyper version exception boundary")
            return ""
        if (self._lifecycle_failure(result, 16_384) is not None
                or type(result.returncode) is not int or result.returncode != 0):
            return ""
        text = (result.stdout or result.stderr or "").strip().splitlines()
        return text[0][:200] if text else ""

    def _result_from_receipt(
        self,
        receipt: HyperCheckReceipt,
        *,
        request: BackendRequest | None,
        bounds: ExecutionBounds,
        document: HyperpropertyIR | None = None,
        fallback_bundle: WitnessTraceBundle | None = None,
        process: ToolRunResult | None = None,
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
            checked = receipt.counterexample
            if receipt.evidence_path is HyperEvidencePath.ENGINE:
                checked = replay_hyper_counterexample(checked,
                    ObservationMap.from_document(document) if document is not None else receipt.observation_map,
                    QuantifierOrder.from_document(document) if document is not None else receipt.quantifier_order,
                    formula_id=document.formula.formula_id if document is not None else None)
                if checked.replayed and document is not None:
                    witness["witness_bundle"] = checked.to_witness_bundle(
                        observation_map=ObservationMap.from_document(document),
                        quantifier_order=QuantifierOrder.from_document(document),
                        formula_id=document.formula.formula_id).to_dict()
            elif (receipt.evidence_path is HyperEvidencePath.BOUNDED_SELF_COMPOSITION
                  and fallback_bundle is not None):
                # This bundle was built by the bounded evaluator from supplied
                # execution traces. It is never native structural replay.
                witness["witness_bundle"] = fallback_bundle.to_dict()
            witness["counterexample"] = checked.to_dict()
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
        metadata: dict[str, Any] = {
            "engine": receipt.engine.value,
            "evidence_path": receipt.evidence_path.value,
            "external_tool_proof": receipt.external_tool_proof,
        }
        if process is not None:
            metadata["process"] = {
                "cancelled": process.cancelled,
                "command": list(process.command),
                "error": process.error,
                "output_truncated": process.output_truncated,
                "process_tree_terminated": process.process_tree_terminated,
                "returncode": process.returncode,
                "resource_exhausted": process.resource_exhausted,
                "stderr_digest": stable_digest({"content": process.stderr}),
                "stdout_digest": stable_digest({"content": process.stdout}),
                "timed_out": process.timed_out,
                "termination_reason": process.termination_reason,
                "unavailable": process.unavailable,
                "workspace_cleaned": process.workspace_cleaned,
                "workspace_limit_exceeded": process.workspace_limit_exceeded,
            }
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
                output_bytes=(len(process.stdout.encode("utf-8"))
                    + len(process.stderr.encode("utf-8")) if process is not None
                    else len(receipt.stdout.encode("utf-8"))
                    + len(receipt.stderr.encode("utf-8"))),
            ),
            witness=FrozenMap(witness),
            diagnostics=tuple(receipt.capability.limitations[:3]),
            reason=receipt.reason,
            metadata=FrozenMap(metadata),
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

# The registry may interpret a normal False from this native-only discovery
# method as a missing tool for an explicitly requested bounded fallback. Keep
# the original identities so caller overrides remain availability vetoes.
_CANONICAL_NATIVE_AVAILABILITY: Final = HyperpropertyBackend.is_available
_CANONICAL_NATIVE_PROBE: Final = HyperpropertyBackend.probe


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
