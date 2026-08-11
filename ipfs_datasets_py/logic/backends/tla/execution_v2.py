"""Execute TLC and Apalache with typed state/temporal semantics (LFP2-029).

Interface: ``StateProviderEvidence@2``

Runs typed state/temporal model checks through independent checker surfaces:

* TLC (finite-state exploration with optional liveness/fairness) and Apalache
  (step-bounded finite-trace safety) each own capability, bounds, and
  configuration identity;
* one checker's support **never** establishes the other's capability or results;
* every counterexample binds bounds, config, module, property, and replay
  outcome;
* finite-state, step-bounded, safety, liveness, fairness, and approximation
  semantics are separated on every answer; and
* fallback / mock / availability / confidence never grant theorem authority.

State-model evidence remains bounded model-check authority (never theorem).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.process import BoundedToolRunner
from ipfs_datasets_py.logic.backends.results import (
    ModelCheckResult,
    ResultAuthority,
    ResultStatus,
)
from ipfs_datasets_py.logic.backends.tla.compiler import (
    GeneratedTLAArtifacts,
    TLACompileBounds,
    TLACompiler,
    TLACompilerError,
    TLASourceMapEntry,
)
from ipfs_datasets_py.logic.backends.tla.runners import (
    APALACHE_BACKEND_VERSION,
    APALACHE_CAPABILITY,
    TLC_BACKEND_VERSION,
    TLC_CAPABILITY,
    ApalacheBackend,
    CounterexampleTrace,
    ExecutableFinder,
    JvmProbe,
    ModelCheckOutcome,
    ModelCheckOutcomeStatus,
    ModelCheckerCapability,
    ModelCheckerTool,
    TLCBackend,
    TLARunnerError,
    parse_counterexample_trace,
    replay_counterexample,
)
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.families.namespaces import (
    LogicIdentity,
    lane_id,
    provider_id,
)
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.protocols import (
    BackendRequest,
    ExecutionBounds,
    QueryKind,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    SyntaxContractError,
    _freeze_mapping,
    _record_id,
    _require_mapping,
    _require_sequence,
    _sha256_hex,
    _text,
    canonical_json_bytes,
    content_sha256,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

STATE_PROVIDER_EVIDENCE_V2_INTERFACE: Final = "StateProviderEvidence@2"
STATE_EXECUTION_REQUEST_V2_INTERFACE: Final = "StateExecutionRequest@2"
STATE_EXECUTION_RESULT_V2_INTERFACE: Final = "StateExecutionResult@2"
STATE_MODULE_BINDING_V2_INTERFACE: Final = "StateModuleBinding@2"
STATE_CONFIG_BINDING_V2_INTERFACE: Final = "StateConfigBinding@2"
STATE_BOUNDS_BINDING_V2_INTERFACE: Final = "StateBoundsBinding@2"
STATE_PROPERTY_BINDING_V2_INTERFACE: Final = "StatePropertyBinding@2"
STATE_COUNTEREXAMPLE_BINDING_V2_INTERFACE: Final = "StateCounterexampleBinding@2"
STATE_SEMANTICS_BINDING_V2_INTERFACE: Final = "StateSemanticsBinding@2"
STATE_CAPABILITY_RECEIPT_V2_INTERFACE: Final = "StateCapabilityReceipt@2"

STATE_PROVIDER_EVIDENCE_SCHEMA: Final = "state-provider-evidence/v2"
STATE_EXECUTION_REQUEST_SCHEMA: Final = "state-execution-request/v2"
STATE_EXECUTION_RESULT_SCHEMA: Final = "state-execution-result/v2"
STATE_MODULE_BINDING_SCHEMA: Final = "state-module-binding/v2"
STATE_CONFIG_BINDING_SCHEMA: Final = "state-config-binding/v2"
STATE_BOUNDS_BINDING_SCHEMA: Final = "state-bounds-binding/v2"
STATE_PROPERTY_BINDING_SCHEMA: Final = "state-property-binding/v2"
STATE_COUNTEREXAMPLE_BINDING_SCHEMA: Final = "state-counterexample-binding/v2"
STATE_SEMANTICS_BINDING_SCHEMA: Final = "state-semantics-binding/v2"
STATE_CAPABILITY_RECEIPT_SCHEMA: Final = "state-capability-receipt/v2"

STATE_EXECUTION_V2_MODULE_VERSION: Final = "1.0.0"
STATE_EXECUTION_V2_TASK_ID: Final = "LFP2-029"
STATE_EXECUTION_V2_GOAL_ID: Final = "LFP2-G060"

STATE_LANE_ID: Final = "state"
STATE_EVIDENCE_KIND: Final = "state_model"

_MAX_DIAGNOSTICS: Final = 64
_MAX_METADATA_BYTES: Final = 8_192
_MAX_SOURCE_REFS: Final = 64
_MAX_PROPERTIES: Final = 256
_MAX_REPLAY_NOTES: Final = 128
_MAX_TRACE_STATES: Final = 512

_FORBIDDEN_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "arbitrary_payload",
        "claimed_execution",
        "claimed_proof",
        "claimed_replay",
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


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


class StateExecutionError(SyntaxContractError):
    """Raised when state/TLA execution v2 inputs are malformed."""


class StateAuthorityError(StateExecutionError):
    """Raised when a claim would exceed the state model-check authority ceiling."""


class StateProviderKind(StrEnum):
    """Closed set of state-model checkers with independent capability surfaces."""

    TLC = "tlc"
    APALACHE = "apalache"


class StateExecutionMode(StrEnum):
    """How the state-model outcome was produced.

    Only ``engine`` and ``hermetic_fixture`` may establish model-check evidence.
    ``fallback`` and ``mock`` never do.
    """

    ENGINE = "engine"
    HERMETIC_FIXTURE = "hermetic_fixture"
    FALLBACK = "fallback"
    MOCK = "mock"
    CAPABILITY_PROBE = "capability_probe"


class StateDisposition(StrEnum):
    """Closed set of state-model execution dispositions."""

    SATISFIED = "satisfied"
    COUNTEREXAMPLE = "counterexample"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    ERROR = "error"
    MALFORMED = "malformed"
    MOCK_REJECTED = "mock_rejected"
    FALLBACK_REJECTED = "fallback_rejected"
    CAPABILITY_ONLY = "capability_only"


class StateReplayStatus(StrEnum):
    """Replay attachment status bound into every counterexample (or absence)."""

    NONE = "none"
    ABSENT = "absent"
    REPLAYED = "replayed"
    NON_REPLAYABLE = "non_replayable"
    CLEAN_NO_COUNTEREXAMPLE = "clean_no_counterexample"


class StateClaimKind(StrEnum):
    """Claims that mock / fallback / other-checker support must never establish."""

    MODEL_CHECK = "model_check"
    PROOF = "proof"
    SATISFIABILITY = "satisfiability"
    THEOREM = "theorem"
    OTHER_PROVIDER_CAPABILITY = "other_provider_capability"
    LIVENESS = "liveness"
    FAIRNESS = "fairness"


class StateSemanticsAxis(StrEnum):
    """Separated semantic axes disclosed on every answer (LFP2-029 effects)."""

    FINITE_STATE = "finite_state"
    STEP_BOUNDED = "step_bounded"
    SAFETY = "safety"
    LIVENESS = "liveness"
    FAIRNESS = "fairness"
    APPROXIMATION = "approximation"


# ---------------------------------------------------------------------------
# Provider capability tables (independent; never cross-copied)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StateProviderCapability:
    """Static, independent capability declaration for one state-model checker."""

    provider: StateProviderKind
    backend_interface: str
    checks_safety: bool
    checks_liveness: bool
    checks_fairness: bool
    finite_state: bool
    step_bounded: bool
    finite_trace_only: bool
    requires_jvm: bool
    max_declared_steps: int
    executable_candidates: tuple[str, ...]
    limitations: tuple[str, ...]
    approximation_notes: tuple[str, ...]
    dependency_kind: str = "jvm"
    dependency_name: str = "java"

    def to_dict(self) -> dict[str, Any]:
        return {
            "approximation_notes": list(self.approximation_notes),
            "backend_interface": self.backend_interface,
            "checks_fairness": self.checks_fairness,
            "checks_liveness": self.checks_liveness,
            "checks_safety": self.checks_safety,
            "dependency_kind": self.dependency_kind,
            "dependency_name": self.dependency_name,
            "executable_candidates": list(self.executable_candidates),
            "finite_state": self.finite_state,
            "finite_trace_only": self.finite_trace_only,
            "limitations": list(self.limitations),
            "max_declared_steps": self.max_declared_steps,
            "provider": self.provider.value,
            "requires_jvm": self.requires_jvm,
            "step_bounded": self.step_bounded,
        }

    def to_model_checker_capability(self) -> ModelCheckerCapability:
        if self.provider is StateProviderKind.TLC:
            return TLC_CAPABILITY
        return APALACHE_CAPABILITY


TLC_STATE_CAPABILITY: Final = StateProviderCapability(
    provider=StateProviderKind.TLC,
    backend_interface=TLC_BACKEND_VERSION,
    checks_safety=True,
    checks_liveness=True,
    checks_fairness=True,
    finite_state=True,
    step_bounded=True,
    finite_trace_only=False,
    requires_jvm=True,
    max_declared_steps=TLC_CAPABILITY.max_declared_steps,
    executable_candidates=TLC_CAPABILITY.executable_candidates,
    limitations=TLC_CAPABILITY.limitations,
    approximation_notes=(
        "TLC explores a finite state graph under declared MaxSteps and domain bounds.",
        "Liveness and fairness checks remain finite-state approximations, not unbounded proofs.",
    ),
    dependency_kind="jvm",
    dependency_name="java",
)

APALACHE_STATE_CAPABILITY: Final = StateProviderCapability(
    provider=StateProviderKind.APALACHE,
    backend_interface=APALACHE_BACKEND_VERSION,
    checks_safety=True,
    checks_liveness=False,
    checks_fairness=False,
    finite_state=False,
    step_bounded=True,
    finite_trace_only=True,
    requires_jvm=True,
    max_declared_steps=APALACHE_CAPABILITY.max_declared_steps,
    executable_candidates=APALACHE_CAPABILITY.executable_candidates,
    limitations=APALACHE_CAPABILITY.limitations,
    approximation_notes=(
        "Apalache checks safety/invariants over finite traces of length --length only.",
        "Temporal liveness and fairness operators are not checked and must not be claimed.",
    ),
    dependency_kind="jvm",
    dependency_name="java",
)

_PROVIDER_CAPABILITIES: Final[Mapping[StateProviderKind, StateProviderCapability]] = {
    StateProviderKind.TLC: TLC_STATE_CAPABILITY,
    StateProviderKind.APALACHE: APALACHE_STATE_CAPABILITY,
}

_PROVIDER_ALIASES: Final[dict[str, StateProviderKind]] = {
    "tlc": StateProviderKind.TLC,
    "tlc2": StateProviderKind.TLC,
    "tla2tools": StateProviderKind.TLC,
    "tla_tlc": StateProviderKind.TLC,
    "tla-tlc": StateProviderKind.TLC,
    "state_tlc": StateProviderKind.TLC,
    "state-tlc": StateProviderKind.TLC,
    "apalache": StateProviderKind.APALACHE,
    "apalache_mc": StateProviderKind.APALACHE,
    "apalache-mc": StateProviderKind.APALACHE,
    "tla_apalache": StateProviderKind.APALACHE,
    "tla-apalache": StateProviderKind.APALACHE,
    "state_apalache": StateProviderKind.APALACHE,
    "state-apalache": StateProviderKind.APALACHE,
}


def normalize_state_provider(
    value: StateProviderKind | ModelCheckerTool | str,
) -> StateProviderKind:
    """Normalize provider labels into the closed state-provider set."""

    if isinstance(value, StateProviderKind):
        return value
    if isinstance(value, ModelCheckerTool):
        return StateProviderKind(value.value)
    key = str(value).strip().lower().replace("-", "_")
    if key not in _PROVIDER_ALIASES:
        alt = str(value).strip().lower()
        if alt in _PROVIDER_ALIASES:
            return _PROVIDER_ALIASES[alt]
        raise StateExecutionError(
            f"unsupported state provider: {value!r}; expected tlc or apalache"
        )
    return _PROVIDER_ALIASES[key]


def provider_to_tool(provider: StateProviderKind) -> ModelCheckerTool:
    return ModelCheckerTool(provider.value)


def tool_to_provider(tool: ModelCheckerTool) -> StateProviderKind:
    return StateProviderKind(tool.value)


def capability_for(
    provider: StateProviderKind | ModelCheckerTool | str,
) -> StateProviderCapability:
    """Return the independent capability declaration for one provider only."""

    return _PROVIDER_CAPABILITIES[normalize_state_provider(provider)]


def provider_logic_identity(provider: StateProviderKind) -> LogicIdentity:
    """Return the canonical provider identity for matrix / evidence binding."""

    return provider_id(provider.value)


def provider_support_establishes_other(
    source: StateProviderKind | ModelCheckerTool | str,
    target: StateProviderKind | ModelCheckerTool | str,
    *,
    source_available: bool = True,
    source_supported: bool = True,
) -> bool:
    """Whether *source* support establishes *target* capability.

    Always ``False`` when providers differ (LFP2-029 acceptance).  Same-provider
    identity is not a cross-provider transfer either.
    """

    del source_available, source_supported
    src = normalize_state_provider(source)
    dst = normalize_state_provider(target)
    if src is not dst:
        return False
    return False


def non_authoritative_signal_establishes(
    claim: StateClaimKind | str,
    *,
    mock_output: object = None,
    fallback_output: object = None,
    available: bool | None = None,
    confidence: float | None = None,
    fluent_text: str | None = None,
    other_provider_available: bool | None = None,
) -> bool:
    """Always ``False``: mock / fallback / availability cannot establish claims."""

    del (
        claim,
        mock_output,
        fallback_output,
        available,
        confidence,
        fluent_text,
        other_provider_available,
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
        raise StateExecutionError(
            f"{field_name} must be one of: {allowed}; got {value!r}"
        ) from error


def _optional_bool(value: object, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise StateExecutionError(f"{field_name} must be a boolean")


def _digest_of(payload: Mapping[str, Any]) -> str:
    return content_sha256(canonical_json_bytes(dict(payload)))


def _source_ref_ids(
    value: object, field_name: str = "source_ref_ids"
) -> tuple[str, ...]:
    items = _require_sequence(value, field_name)
    if len(items) > _MAX_SOURCE_REFS:
        raise StateExecutionError(
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
            raise StateAuthorityError(
                f"{field_name} rejects free-form authority/signal key {key!r}; "
                "use typed state evidence fields only"
            )


def _filter_keys(mapping: Mapping[str, Any], allowed: set[str]) -> dict[str, Any]:
    return {key: value for key, value in mapping.items() if key in allowed}


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise StateExecutionError(f"{field_name} must be a positive integer")
    return value


def _non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise StateExecutionError(f"{field_name} must be a non-negative integer")
    return value


def _property_names(
    value: object, field_name: str = "properties"
) -> tuple[str, ...]:
    items = _require_sequence(value, field_name)
    if len(items) > _MAX_PROPERTIES:
        raise StateExecutionError(
            f"{field_name} exceeds hard limit {_MAX_PROPERTIES}"
        )
    names: list[str] = []
    for index, item in enumerate(items):
        names.append(_text(item, f"{field_name}[{index}]", maximum=128))
    return tuple(names)


def _status_to_disposition(status: ModelCheckOutcomeStatus) -> StateDisposition:
    mapping = {
        ModelCheckOutcomeStatus.PASSED: StateDisposition.SATISFIED,
        ModelCheckOutcomeStatus.COUNTEREXAMPLE: StateDisposition.COUNTEREXAMPLE,
        ModelCheckOutcomeStatus.UNKNOWN: StateDisposition.UNKNOWN,
        ModelCheckOutcomeStatus.TIMED_OUT: StateDisposition.TIMEOUT,
        ModelCheckOutcomeStatus.UNAVAILABLE: StateDisposition.UNAVAILABLE,
        ModelCheckOutcomeStatus.ERROR: StateDisposition.ERROR,
        ModelCheckOutcomeStatus.MALFORMED: StateDisposition.MALFORMED,
    }
    return mapping[status]


def _status_to_result_status(status: ModelCheckOutcomeStatus) -> ResultStatus:
    mapping = {
        ModelCheckOutcomeStatus.PASSED: ResultStatus.SATISFIED,
        ModelCheckOutcomeStatus.COUNTEREXAMPLE: ResultStatus.VIOLATED,
        ModelCheckOutcomeStatus.UNKNOWN: ResultStatus.UNKNOWN,
        ModelCheckOutcomeStatus.TIMED_OUT: ResultStatus.TIMEOUT,
        ModelCheckOutcomeStatus.UNAVAILABLE: ResultStatus.UNAVAILABLE,
        ModelCheckOutcomeStatus.ERROR: ResultStatus.ERROR,
        ModelCheckOutcomeStatus.MALFORMED: ResultStatus.MALFORMED,
    }
    return mapping[status]


def _contract_json_value(value: object, field_name: str) -> Any:
    if value is None or type(value) in {str, bool, int}:
        if type(value) is int and abs(value) > (1 << 53) - 1:
            raise StateExecutionError(
                f"{field_name} integer is outside the safe JSON integer range"
            )
        return value
    if type(value) is float:
        if value != value or value in {float("inf"), float("-inf")}:
            raise StateExecutionError(
                f"{field_name} must be a finite number; got {value!r}"
            )
        as_int = int(value)
        if value == as_int:
            if abs(as_int) > (1 << 53) - 1:
                raise StateExecutionError(
                    f"{field_name} integer is outside the safe JSON integer range"
                )
            return as_int
        micros = int(round(value * 1_000_000))
        if abs(micros) > (1 << 53) - 1:
            raise StateExecutionError(
                f"{field_name} fixed-point value is outside the safe JSON range"
            )
        return micros
    if isinstance(value, Mapping):
        return {
            str(key): _contract_json_value(item, f"{field_name}.{key}")
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            _contract_json_value(item, f"{field_name}[{index}]")
            for index, item in enumerate(value)
        ]
    raise StateExecutionError(
        f"{field_name} is not a contract-safe JSON value: {type(value).__name__}"
    )


def _evidence_receipt_payload(receipt: Mapping[str, Any] | object) -> dict[str, Any]:
    if hasattr(receipt, "to_dict") and callable(receipt.to_dict):
        raw = receipt.to_dict()  # type: ignore[operator]
    else:
        raw = dict(_require_mapping(receipt, "receipt"))
    if not isinstance(raw, Mapping):
        raise StateExecutionError("receipt.to_dict() must return a mapping")
    return dict(_contract_json_value(dict(raw), "receipt"))


_MODULE_HEADER_RE: Final = re.compile(
    r"----\s*MODULE\s+([A-Za-z][A-Za-z0-9_]*)\s*----"
)
_INVARIANT_VIOLATED_RE: Final = re.compile(
    r"Invariant\s+([A-Za-z][A-Za-z0-9_]*)\s+is\s+violated",
    re.IGNORECASE,
)


def _module_name_from_model_text(model_text: str) -> str:
    """Extract the MODULE header identifier from generated TLA+ source."""

    match = _MODULE_HEADER_RE.search(str(model_text or ""))
    return match.group(1) if match else ""


def _resolve_module_name(
    artifacts: GeneratedTLAArtifacts,
    *,
    module_name: str | None = None,
) -> str:
    """Prefer the request module name, then MODULE header, then artifact field."""

    requested = str(module_name or "").strip()
    if requested:
        return requested
    from_text = _module_name_from_model_text(artifacts.model_text)
    if from_text:
        return from_text
    return str(artifacts.module_name or "StateModel")


def _select_primary_property(
    *,
    safety: Sequence[str],
    liveness: Sequence[str],
    checked_safety: Sequence[str] = (),
    checked_liveness: Sequence[str] = (),
    primary_property: str = "",
    raw_trace: str = "",
) -> str:
    """Choose a stable primary property name for bindings.

    Preference order:
    1. Explicit primary override
    2. Invariant name reported in a counterexample ("Invariant X is violated")
    3. Composite ``Safety`` when present among declared/checked safety props
    4. First ``Inv_*`` concrete invariant
    5. First checked/declared safety property (including TypeOK)
    6. First liveness property
    7. Fallback ``Safety``
    """

    explicit = str(primary_property or "").strip()
    if explicit:
        return explicit

    violated = _INVARIANT_VIOLATED_RE.search(str(raw_trace or ""))
    if violated:
        return violated.group(1)

    safety_pool = tuple(checked_safety) or tuple(safety)
    if "Safety" in safety_pool:
        return "Safety"
    for name in safety_pool:
        if str(name).startswith("Inv"):
            return str(name)
    if safety_pool:
        return str(safety_pool[0])

    liveness_pool = tuple(checked_liveness) or tuple(liveness)
    if liveness_pool:
        return str(liveness_pool[0])
    return "Safety"


def _default_bounds() -> ExecutionBounds:
    return ExecutionBounds(timeout_ms=30_000, max_steps=64)


def _normalize_bounds(value: object) -> ExecutionBounds:
    if value is None:
        return _default_bounds()
    if isinstance(value, ExecutionBounds):
        return value
    if isinstance(value, Mapping):
        return ExecutionBounds(
            timeout_ms=int(value.get("timeout_ms", 30_000)),
            max_steps=int(value.get("max_steps", 64)),
            max_memory_bytes=int(value.get("max_memory_bytes", 256 * 1024 * 1024)),
            max_output_bytes=int(value.get("max_output_bytes", 2 * 1024 * 1024)),
        )
    raise StateExecutionError("bounds must be ExecutionBounds or mapping")


# ---------------------------------------------------------------------------
# Bindings
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StateModuleBindingV2:
    """TLA module identity bound into every answer.

    Interface: ``StateModuleBinding@2``.
    """

    module_name: str
    model_digest: str
    artifact_digest: str
    source_document_id: str = ""
    source_kind: str = ""
    source_map_size: int = 0
    schema_version: str = STATE_MODULE_BINDING_SCHEMA

    interface: ClassVar[str] = STATE_MODULE_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "module_name",
            _text(self.module_name, "module_name", maximum=128),
        )
        object.__setattr__(
            self, "model_digest", _sha256_hex(self.model_digest, "model_digest")
        )
        object.__setattr__(
            self,
            "artifact_digest",
            _sha256_hex(self.artifact_digest, "artifact_digest"),
        )
        object.__setattr__(
            self,
            "source_document_id",
            _text(
                self.source_document_id,
                "source_document_id",
                maximum=256,
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "source_kind",
            _text(self.source_kind, "source_kind", maximum=64, allow_empty=True),
        )
        object.__setattr__(
            self,
            "source_map_size",
            _non_negative_int(self.source_map_size, "source_map_size"),
        )
        if self.schema_version != STATE_MODULE_BINDING_SCHEMA:
            raise StateExecutionError(
                f"unsupported module binding schema: {self.schema_version!r}"
            )

    @classmethod
    def from_artifacts(
        cls,
        artifacts: GeneratedTLAArtifacts,
        *,
        module_name: str | None = None,
    ) -> StateModuleBindingV2:
        return cls(
            module_name=_resolve_module_name(artifacts, module_name=module_name),
            model_digest=artifacts.model_digest,
            artifact_digest=artifacts.artifact_digest,
            source_document_id=artifacts.source_document_id,
            source_kind=artifacts.source_kind,
            source_map_size=len(artifacts.source_map),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_digest": self.artifact_digest,
            "interface": self.interface,
            "model_digest": self.model_digest,
            "module_name": self.module_name,
            "schema_version": self.schema_version,
            "source_document_id": self.source_document_id,
            "source_kind": self.source_kind,
            "source_map_size": self.source_map_size,
        }


@dataclass(frozen=True, slots=True)
class StateConfigBindingV2:
    """Tool-specific configuration identity bound into every answer.

    Interface: ``StateConfigBinding@2``.
    """

    provider: StateProviderKind | str
    configuration_digest: str
    configuration_text: str = ""
    config_kind: str = ""
    schema_version: str = STATE_CONFIG_BINDING_SCHEMA

    interface: ClassVar[str] = STATE_CONFIG_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "provider", normalize_state_provider(self.provider)
        )
        object.__setattr__(
            self,
            "configuration_digest",
            _sha256_hex(self.configuration_digest, "configuration_digest"),
        )
        config_text = str(self.configuration_text or "")
        # Config files are newline-terminated; store without failing _text strip rules.
        if config_text.endswith("\n"):
            config_text = config_text[:-1]
        object.__setattr__(
            self,
            "configuration_text",
            _text(
                config_text,
                "configuration_text",
                maximum=65_536,
                allow_empty=True,
            ),
        )
        provider = self.provider  # type: ignore[assignment]
        if not self.config_kind:
            kind = "tlc_cfg" if provider is StateProviderKind.TLC else "apalache_cfg"
        else:
            kind = _text(self.config_kind, "config_kind", maximum=32)
        object.__setattr__(self, "config_kind", kind)
        if self.schema_version != STATE_CONFIG_BINDING_SCHEMA:
            raise StateExecutionError(
                f"unsupported config binding schema: {self.schema_version!r}"
            )

    @classmethod
    def from_artifacts(
        cls,
        artifacts: GeneratedTLAArtifacts,
        provider: StateProviderKind,
    ) -> StateConfigBindingV2:
        if provider is StateProviderKind.TLC:
            return cls(
                provider=provider,
                configuration_digest=artifacts.tlc_config_digest,
                configuration_text=artifacts.tlc_config_text,
                config_kind="tlc_cfg",
            )
        return cls(
            provider=provider,
            configuration_digest=artifacts.apalache_config_digest,
            configuration_text=artifacts.apalache_config_text,
            config_kind="apalache_cfg",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_kind": self.config_kind,
            "configuration_digest": self.configuration_digest,
            "configuration_text": self.configuration_text,
            "interface": self.interface,
            "provider": (
                self.provider.value
                if isinstance(self.provider, StateProviderKind)
                else self.provider
            ),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class StateBoundsBindingV2:
    """Finite execution/compile bounds bound into every answer.

    Interface: ``StateBoundsBinding@2``.
    """

    max_steps: int
    timeout_ms: int
    max_declared_steps: int
    compile_bounds: Mapping[str, Any] = field(default_factory=dict)
    finite_state: bool = True
    step_bounded: bool = True
    finite_trace_only: bool = False
    schema_version: str = STATE_BOUNDS_BINDING_SCHEMA

    interface: ClassVar[str] = STATE_BOUNDS_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "max_steps", _positive_int(self.max_steps, "max_steps"))
        object.__setattr__(
            self, "timeout_ms", _positive_int(self.timeout_ms, "timeout_ms")
        )
        object.__setattr__(
            self,
            "max_declared_steps",
            _positive_int(self.max_declared_steps, "max_declared_steps"),
        )
        for name in ("finite_state", "step_bounded", "finite_trace_only"):
            object.__setattr__(
                self, name, _optional_bool(getattr(self, name), name)
            )
        bounds = _require_mapping(self.compile_bounds, "compile_bounds")
        object.__setattr__(
            self,
            "compile_bounds",
            dict(_freeze_mapping(bounds, "compile_bounds")),
        )
        if self.schema_version != STATE_BOUNDS_BINDING_SCHEMA:
            raise StateExecutionError(
                f"unsupported bounds binding schema: {self.schema_version!r}"
            )

    @classmethod
    def from_artifacts_and_request(
        cls,
        artifacts: GeneratedTLAArtifacts,
        *,
        provider: StateProviderKind,
        bounds: ExecutionBounds,
    ) -> StateBoundsBindingV2:
        cap = capability_for(provider)
        max_steps = min(bounds.max_steps, artifacts.bounds.max_steps, cap.max_declared_steps)
        return cls(
            max_steps=max(1, max_steps),
            timeout_ms=bounds.timeout_ms,
            max_declared_steps=cap.max_declared_steps,
            compile_bounds=artifacts.bounds.to_dict(),
            finite_state=cap.finite_state,
            step_bounded=cap.step_bounded,
            finite_trace_only=cap.finite_trace_only,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "compile_bounds": dict(self.compile_bounds),
            "finite_state": self.finite_state,
            "finite_trace_only": self.finite_trace_only,
            "interface": self.interface,
            "max_declared_steps": self.max_declared_steps,
            "max_steps": self.max_steps,
            "schema_version": self.schema_version,
            "step_bounded": self.step_bounded,
            "timeout_ms": self.timeout_ms,
        }


@dataclass(frozen=True, slots=True)
class StatePropertyBindingV2:
    """Safety / liveness / fairness properties bound into every answer.

    Interface: ``StatePropertyBinding@2``.
    """

    safety_properties: tuple[str, ...]
    liveness_properties: tuple[str, ...]
    fairness_limitations: tuple[str, ...] = ()
    checked_safety: tuple[str, ...] = ()
    checked_liveness: tuple[str, ...] = ()
    primary_property: str = ""
    schema_version: str = STATE_PROPERTY_BINDING_SCHEMA

    interface: ClassVar[str] = STATE_PROPERTY_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "safety_properties",
            _property_names(self.safety_properties, "safety_properties"),
        )
        object.__setattr__(
            self,
            "liveness_properties",
            _property_names(self.liveness_properties, "liveness_properties"),
        )
        object.__setattr__(
            self,
            "fairness_limitations",
            tuple(
                _text(item, "fairness_limitations item", maximum=512)
                for item in self.fairness_limitations[:_MAX_REPLAY_NOTES]
            ),
        )
        object.__setattr__(
            self,
            "checked_safety",
            _property_names(self.checked_safety, "checked_safety"),
        )
        object.__setattr__(
            self,
            "checked_liveness",
            _property_names(self.checked_liveness, "checked_liveness"),
        )
        object.__setattr__(
            self,
            "primary_property",
            _text(
                self.primary_property,
                "primary_property",
                maximum=128,
                allow_empty=True,
            ),
        )
        if self.schema_version != STATE_PROPERTY_BINDING_SCHEMA:
            raise StateExecutionError(
                f"unsupported property binding schema: {self.schema_version!r}"
            )

    @classmethod
    def from_artifacts_and_receipt(
        cls,
        artifacts: GeneratedTLAArtifacts,
        *,
        checked_safety: Sequence[str] = (),
        checked_liveness: Sequence[str] = (),
        fairness_limitations: Sequence[str] = (),
        primary_property: str = "",
        raw_trace: str = "",
    ) -> StatePropertyBindingV2:
        safety = tuple(artifacts.safety_properties)
        liveness = tuple(artifacts.liveness_properties)
        primary = _select_primary_property(
            safety=safety,
            liveness=liveness,
            checked_safety=checked_safety,
            checked_liveness=checked_liveness,
            primary_property=primary_property,
            raw_trace=raw_trace,
        )
        return cls(
            safety_properties=safety,
            liveness_properties=liveness,
            fairness_limitations=tuple(fairness_limitations)
            or tuple(artifacts.fairness_limitations),
            checked_safety=tuple(checked_safety),
            checked_liveness=tuple(checked_liveness),
            primary_property=primary,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_liveness": list(self.checked_liveness),
            "checked_safety": list(self.checked_safety),
            "fairness_limitations": list(self.fairness_limitations),
            "interface": self.interface,
            "liveness_properties": list(self.liveness_properties),
            "primary_property": self.primary_property,
            "safety_properties": list(self.safety_properties),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class StateSemanticsBindingV2:
    """Separated finite-state / step / safety / liveness / fairness / approximation.

    Interface: ``StateSemanticsBinding@2``.
    """

    provider: StateProviderKind | str
    finite_state: bool
    step_bounded: bool
    safety: bool
    liveness: bool
    fairness: bool
    approximation: bool
    axes: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    schema_version: str = STATE_SEMANTICS_BINDING_SCHEMA

    interface: ClassVar[str] = STATE_SEMANTICS_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "provider", normalize_state_provider(self.provider)
        )
        for name in (
            "finite_state",
            "step_bounded",
            "safety",
            "liveness",
            "fairness",
            "approximation",
        ):
            object.__setattr__(
                self, name, _optional_bool(getattr(self, name), name)
            )
        provider = self.provider  # type: ignore[assignment]
        cap = capability_for(provider)
        # Provider capability gates: Apalache cannot claim liveness/fairness.
        if provider is StateProviderKind.APALACHE:
            if self.liveness or self.fairness:
                raise StateAuthorityError(
                    "Apalache semantics cannot claim liveness or fairness checking"
                )
            if self.finite_state and not cap.finite_state:
                # Apalache is step-bounded finite-trace, not full finite-state graph.
                object.__setattr__(self, "finite_state", False)
        if self.liveness and not cap.checks_liveness:
            raise StateAuthorityError(
                f"{provider.value} cannot claim liveness semantics"
            )
        if self.fairness and not cap.checks_fairness:
            raise StateAuthorityError(
                f"{provider.value} cannot claim fairness semantics"
            )
        if not self.axes:
            active = []
            if self.finite_state:
                active.append(StateSemanticsAxis.FINITE_STATE.value)
            if self.step_bounded:
                active.append(StateSemanticsAxis.STEP_BOUNDED.value)
            if self.safety:
                active.append(StateSemanticsAxis.SAFETY.value)
            if self.liveness:
                active.append(StateSemanticsAxis.LIVENESS.value)
            if self.fairness:
                active.append(StateSemanticsAxis.FAIRNESS.value)
            if self.approximation:
                active.append(StateSemanticsAxis.APPROXIMATION.value)
            object.__setattr__(self, "axes", tuple(active))
        else:
            object.__setattr__(
                self,
                "axes",
                tuple(
                    _text(item, "axes item", maximum=64) for item in self.axes
                ),
            )
        object.__setattr__(
            self,
            "notes",
            tuple(
                _text(item, "notes item", maximum=512)
                for item in self.notes[:_MAX_REPLAY_NOTES]
            ),
        )
        if self.schema_version != STATE_SEMANTICS_BINDING_SCHEMA:
            raise StateExecutionError(
                f"unsupported semantics binding schema: {self.schema_version!r}"
            )

    @classmethod
    def from_capability(
        cls,
        provider: StateProviderKind,
        *,
        notes: Sequence[str] = (),
    ) -> StateSemanticsBindingV2:
        cap = capability_for(provider)
        return cls(
            provider=provider,
            finite_state=cap.finite_state,
            step_bounded=cap.step_bounded,
            safety=cap.checks_safety,
            liveness=cap.checks_liveness,
            fairness=cap.checks_fairness,
            approximation=True,  # all bounded checkers are approximate vs unbounded
            notes=tuple(notes) or cap.approximation_notes + cap.limitations,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "approximation": self.approximation,
            "axes": list(self.axes),
            "fairness": self.fairness,
            "finite_state": self.finite_state,
            "interface": self.interface,
            "liveness": self.liveness,
            "notes": list(self.notes),
            "provider": (
                self.provider.value
                if isinstance(self.provider, StateProviderKind)
                else self.provider
            ),
            "safety": self.safety,
            "schema_version": self.schema_version,
            "step_bounded": self.step_bounded,
        }


@dataclass(frozen=True, slots=True)
class StateCounterexampleBindingV2:
    """Counterexample that always binds bounds, config, module, property, replay.

    Interface: ``StateCounterexampleBinding@2``.

    Acceptance (LFP2-029): every counterexample binds bounds, config, module,
    property, and replay outcome.  When no counterexample is present, status
    is ``clean_no_counterexample`` / ``none`` / ``absent`` with the same
    binding slots filled from the run context.
    """

    status: StateReplayStatus | str
    module: StateModuleBindingV2 | Mapping[str, Any]
    config: StateConfigBindingV2 | Mapping[str, Any]
    bounds: StateBoundsBindingV2 | Mapping[str, Any]
    property_name: str
    property_binding: StatePropertyBindingV2 | Mapping[str, Any]
    replayed: bool = False
    replay_notes: tuple[str, ...] = ()
    state_count: int = 0
    states: tuple[Mapping[str, Any], ...] = ()
    raw_trace: str = ""
    source: str = ""
    schema_version: str = STATE_COUNTEREXAMPLE_BINDING_SCHEMA

    interface: ClassVar[str] = STATE_COUNTEREXAMPLE_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "status", _enum(self.status, StateReplayStatus, "status")
        )

        if isinstance(self.module, StateModuleBindingV2):
            module = self.module
        else:
            module = StateModuleBindingV2(
                **_filter_keys(
                    _require_mapping(self.module, "module"),
                    {
                        "module_name",
                        "model_digest",
                        "artifact_digest",
                        "source_document_id",
                        "source_kind",
                        "source_map_size",
                        "schema_version",
                    },
                )
            )
        object.__setattr__(self, "module", module)

        if isinstance(self.config, StateConfigBindingV2):
            config = self.config
        else:
            config = StateConfigBindingV2(
                **_filter_keys(
                    _require_mapping(self.config, "config"),
                    {
                        "provider",
                        "configuration_digest",
                        "configuration_text",
                        "config_kind",
                        "schema_version",
                    },
                )
            )
        object.__setattr__(self, "config", config)

        if isinstance(self.bounds, StateBoundsBindingV2):
            bounds = self.bounds
        else:
            bounds = StateBoundsBindingV2(
                **_filter_keys(
                    _require_mapping(self.bounds, "bounds"),
                    {
                        "max_steps",
                        "timeout_ms",
                        "max_declared_steps",
                        "compile_bounds",
                        "finite_state",
                        "step_bounded",
                        "finite_trace_only",
                        "schema_version",
                    },
                )
            )
        object.__setattr__(self, "bounds", bounds)

        object.__setattr__(
            self,
            "property_name",
            _text(self.property_name, "property_name", maximum=128),
        )

        if isinstance(self.property_binding, StatePropertyBindingV2):
            props = self.property_binding
        else:
            props = StatePropertyBindingV2(
                **_filter_keys(
                    _require_mapping(self.property_binding, "property_binding"),
                    {
                        "safety_properties",
                        "liveness_properties",
                        "fairness_limitations",
                        "checked_safety",
                        "checked_liveness",
                        "primary_property",
                        "schema_version",
                    },
                )
            )
        object.__setattr__(self, "property_binding", props)

        object.__setattr__(self, "replayed", _optional_bool(self.replayed, "replayed"))
        object.__setattr__(
            self,
            "replay_notes",
            tuple(
                _text(item, "replay_notes item", maximum=512)
                for item in self.replay_notes[:_MAX_REPLAY_NOTES]
            ),
        )
        object.__setattr__(
            self, "state_count", _non_negative_int(self.state_count, "state_count")
        )
        if self.state_count > _MAX_TRACE_STATES:
            raise StateExecutionError(
                f"state_count exceeds hard limit {_MAX_TRACE_STATES}"
            )
        states: list[dict[str, Any]] = []
        for index, item in enumerate(self.states[:_MAX_TRACE_STATES]):
            mapping = _require_mapping(item, f"states[{index}]")
            states.append(dict(_freeze_mapping(mapping, f"states[{index}]")))
        object.__setattr__(self, "states", tuple(states))
        raw = str(self.raw_trace or "")
        if raw.endswith("\n"):
            raw = raw.rstrip("\n")
        object.__setattr__(
            self,
            "raw_trace",
            _text(raw, "raw_trace", maximum=262_144, allow_empty=True),
        )
        object.__setattr__(
            self,
            "source",
            _text(self.source, "source", maximum=128, allow_empty=True),
        )
        if self.schema_version != STATE_COUNTEREXAMPLE_BINDING_SCHEMA:
            raise StateExecutionError(
                f"unsupported counterexample binding schema: {self.schema_version!r}"
            )

        status = self.status  # type: ignore[assignment]
        if status is StateReplayStatus.REPLAYED:
            if not self.replayed:
                raise StateExecutionError(
                    "replayed status requires replayed=True"
                )
            if self.state_count < 1 and not self.raw_trace:
                raise StateExecutionError(
                    "replayed counterexample requires states or raw_trace"
                )
        if status is StateReplayStatus.NON_REPLAYABLE and self.replayed:
            raise StateExecutionError(
                "non_replayable status cannot set replayed=True"
            )
        if status is StateReplayStatus.CLEAN_NO_COUNTEREXAMPLE and (
            self.state_count or self.states
        ):
            raise StateExecutionError(
                "clean_no_counterexample cannot carry counterexample states"
            )

        # Fail-closed: every counterexample binding must expose the five keys.
        if not module.module_name:
            raise StateExecutionError("counterexample must bind module_name")
        if not config.configuration_digest:
            raise StateExecutionError("counterexample must bind configuration_digest")
        if bounds.max_steps < 1:
            raise StateExecutionError("counterexample must bind positive max_steps")
        if not self.property_name:
            raise StateExecutionError("counterexample must bind property_name")

    def bindings_complete(self) -> bool:
        """Return True when bounds, config, module, property, and replay are bound."""

        return bool(
            self.module.module_name  # type: ignore[union-attr]
            and self.module.model_digest  # type: ignore[union-attr]
            and self.config.configuration_digest  # type: ignore[union-attr]
            and self.bounds.max_steps >= 1  # type: ignore[union-attr]
            and self.property_name
            and self.status is not None
        )

    @classmethod
    def from_trace(
        cls,
        *,
        disposition: StateDisposition,
        trace: CounterexampleTrace | None,
        module: StateModuleBindingV2,
        config: StateConfigBindingV2,
        bounds: StateBoundsBindingV2,
        properties: StatePropertyBindingV2,
        property_name: str = "",
    ) -> StateCounterexampleBindingV2:
        primary = property_name or properties.primary_property or "Safety"
        if disposition is StateDisposition.SATISFIED:
            return cls(
                status=StateReplayStatus.CLEAN_NO_COUNTEREXAMPLE,
                module=module,
                config=config,
                bounds=bounds,
                property_name=primary,
                property_binding=properties,
                replayed=False,
                state_count=0,
            )
        if trace is None:
            if disposition is StateDisposition.COUNTEREXAMPLE:
                return cls(
                    status=StateReplayStatus.NON_REPLAYABLE,
                    module=module,
                    config=config,
                    bounds=bounds,
                    property_name=primary,
                    property_binding=properties,
                    replayed=False,
                    replay_notes=(
                        "counterexample reported without parseable State blocks",
                    ),
                    state_count=0,
                )
            if disposition in {
                StateDisposition.UNKNOWN,
                StateDisposition.TIMEOUT,
                StateDisposition.UNAVAILABLE,
                StateDisposition.UNSUPPORTED,
                StateDisposition.ERROR,
                StateDisposition.MALFORMED,
                StateDisposition.MOCK_REJECTED,
                StateDisposition.FALLBACK_REJECTED,
                StateDisposition.CAPABILITY_ONLY,
            }:
                return cls(
                    status=StateReplayStatus.NONE,
                    module=module,
                    config=config,
                    bounds=bounds,
                    property_name=primary,
                    property_binding=properties,
                )
            return cls(
                status=StateReplayStatus.ABSENT,
                module=module,
                config=config,
                bounds=bounds,
                property_name=primary,
                property_binding=properties,
            )

        states = tuple(item.to_dict() for item in trace.states[:_MAX_TRACE_STATES])
        if trace.replayed:
            status = StateReplayStatus.REPLAYED
        elif trace.states:
            status = StateReplayStatus.NON_REPLAYABLE
        else:
            status = StateReplayStatus.NON_REPLAYABLE
        return cls(
            status=status,
            module=module,
            config=config,
            bounds=bounds,
            property_name=primary,
            property_binding=properties,
            replayed=bool(trace.replayed),
            replay_notes=tuple(trace.replay_notes),
            state_count=len(trace.states),
            states=states,
            raw_trace=trace.raw,
            source=trace.source,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bindings_complete": self.bindings_complete(),
            "bounds": self.bounds.to_dict(),  # type: ignore[union-attr]
            "config": self.config.to_dict(),  # type: ignore[union-attr]
            "interface": self.interface,
            "module": self.module.to_dict(),  # type: ignore[union-attr]
            "property": self.property_name,
            "property_binding": self.property_binding.to_dict(),  # type: ignore[union-attr]
            "property_name": self.property_name,
            "raw_trace": self.raw_trace,
            "replay_notes": list(self.replay_notes),
            "replay_outcome": (
                self.status.value
                if isinstance(self.status, StateReplayStatus)
                else self.status
            ),
            "replayed": self.replayed,
            "schema_version": self.schema_version,
            "source": self.source,
            "state_count": self.state_count,
            "states": [dict(item) for item in self.states],
            "status": (
                self.status.value
                if isinstance(self.status, StateReplayStatus)
                else self.status
            ),
        }


@dataclass(frozen=True, slots=True)
class StateCapabilityReceiptV2:
    """Independent capability/availability receipt for one state provider.

    Interface: ``StateCapabilityReceipt@2``.
    """

    provider: StateProviderKind | str
    available: bool
    supported_document: bool = True
    capability: Mapping[str, Any] = field(default_factory=dict)
    reason: str = ""
    establishes_other_providers: bool = False
    jvm_available: bool = False
    tool_version: str = ""
    schema_version: str = STATE_CAPABILITY_RECEIPT_SCHEMA

    interface: ClassVar[str] = STATE_CAPABILITY_RECEIPT_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "provider", normalize_state_provider(self.provider)
        )
        provider = self.provider  # type: ignore[assignment]
        expected = capability_for(provider)
        object.__setattr__(
            self, "available", _optional_bool(self.available, "available")
        )
        object.__setattr__(
            self,
            "supported_document",
            _optional_bool(self.supported_document, "supported_document"),
        )
        cap_payload = (
            dict(self.capability)
            if self.capability
            else expected.to_dict()
        )
        cap_map = _require_mapping(cap_payload, "capability")
        if str(cap_map.get("provider", provider.value)) != provider.value:
            raise StateAuthorityError(
                f"{provider.value} capability receipt cannot be re-labeled "
                f"with provider={cap_map.get('provider')!r}"
            )
        # Ensure capability matches the independent table for critical flags.
        for flag in (
            "checks_liveness",
            "checks_fairness",
            "checks_safety",
            "finite_trace_only",
            "finite_state",
            "step_bounded",
        ):
            if flag in cap_map and bool(cap_map[flag]) != bool(
                getattr(expected, flag)
            ):
                raise StateAuthorityError(
                    f"{provider.value} capability.{flag} must match the "
                    "independent capability table"
                )
        object.__setattr__(
            self, "capability", dict(_freeze_mapping(cap_map, "capability"))
        )
        object.__setattr__(
            self,
            "reason",
            _text(self.reason, "reason", maximum=512, allow_empty=True),
        )
        object.__setattr__(
            self,
            "establishes_other_providers",
            _optional_bool(
                self.establishes_other_providers, "establishes_other_providers"
            ),
        )
        if self.establishes_other_providers:
            raise StateAuthorityError(
                "capability receipt cannot claim establishes_other_providers"
            )
        object.__setattr__(
            self,
            "jvm_available",
            _optional_bool(self.jvm_available, "jvm_available"),
        )
        object.__setattr__(
            self,
            "tool_version",
            _text(self.tool_version, "tool_version", maximum=256, allow_empty=True),
        )
        if self.schema_version != STATE_CAPABILITY_RECEIPT_SCHEMA:
            raise StateExecutionError(
                f"unsupported capability receipt schema: {self.schema_version!r}"
            )

    def establishes(self, other: StateProviderKind | str) -> bool:
        return provider_support_establishes_other(self.provider, other)  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "capability": dict(self.capability),
            "establishes_other_providers": False,
            "interface": self.interface,
            "jvm_available": self.jvm_available,
            "provider": (
                self.provider.value
                if isinstance(self.provider, StateProviderKind)
                else self.provider
            ),
            "reason": self.reason,
            "schema_version": self.schema_version,
            "supported_document": self.supported_document,
            "tool_version": self.tool_version,
        }


# ---------------------------------------------------------------------------
# Request / evidence / result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StateExecutionRequestV2:
    """Typed request for one TLC or Apalache model-check execution.

    Interface: ``StateExecutionRequest@2``.
    """

    request_id: str
    provider: StateProviderKind | str
    mode: StateExecutionMode | str = StateExecutionMode.ENGINE
    document: object | None = None
    artifacts: GeneratedTLAArtifacts | Mapping[str, Any] | None = None
    module_name: str = "StateModel"
    source_ref_ids: tuple[str, ...] | Sequence[str] = ()
    bounds: ExecutionBounds | Mapping[str, Any] | None = None
    mock_output: object = None
    fallback_output: object = None
    available: bool | None = None
    confidence: float = 0.0
    fluent_text: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = STATE_EXECUTION_REQUEST_SCHEMA

    interface: ClassVar[str] = STATE_EXECUTION_REQUEST_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _record_id(self.request_id, "request_id")
        )
        object.__setattr__(
            self, "provider", normalize_state_provider(self.provider)
        )
        object.__setattr__(
            self, "mode", _enum(self.mode, StateExecutionMode, "mode")
        )
        object.__setattr__(
            self,
            "module_name",
            _text(self.module_name, "module_name", maximum=128),
        )
        object.__setattr__(
            self, "source_ref_ids", _source_ref_ids(self.source_ref_ids)
        )
        object.__setattr__(self, "bounds", _normalize_bounds(self.bounds))
        if self.available is not None:
            object.__setattr__(
                self, "available", _optional_bool(self.available, "available")
            )
        if isinstance(self.confidence, bool) or not isinstance(
            self.confidence, (int, float)
        ):
            raise StateExecutionError("confidence must be numeric")
        conf = float(self.confidence)
        if conf != conf or conf < 0.0 or conf > 1.0:
            raise StateExecutionError("confidence must be finite in [0, 1]")
        object.__setattr__(self, "confidence", conf)
        object.__setattr__(
            self,
            "fluent_text",
            _text(self.fluent_text, "fluent_text", maximum=2048, allow_empty=True),
        )
        metadata = _freeze_mapping(self.metadata, "metadata")
        _forbid_authority_metadata(metadata, "metadata")
        object.__setattr__(self, "metadata", metadata)
        if self.schema_version != STATE_EXECUTION_REQUEST_SCHEMA:
            raise StateExecutionError(
                f"unsupported request schema: {self.schema_version!r}"
            )
        if (
            self.document is None
            and self.artifacts is None
            and self.mode
            not in {
                StateExecutionMode.MOCK,
                StateExecutionMode.FALLBACK,
                StateExecutionMode.CAPABILITY_PROBE,
            }
        ):
            # Allow empty only for mock/fallback/probe; engine needs input.
            pass

    @property
    def has_mock_output(self) -> bool:
        return self.mock_output is not None

    @property
    def has_fallback_output(self) -> bool:
        return self.fallback_output is not None

    def to_dict(self) -> dict[str, Any]:
        # Keep digest payload compact and JSON-safe (no full IR dump).
        document_id = ""
        document_digest = ""
        document_kind = ""
        if self.document is not None:
            document_kind = type(self.document).__name__
            if hasattr(self.document, "document_id"):
                document_id = str(getattr(self.document, "document_id") or "")
            if hasattr(self.document, "sha256"):
                document_digest = str(getattr(self.document, "sha256") or "")
            elif hasattr(self.document, "to_dict") and callable(self.document.to_dict):
                try:
                    document_digest = content_sha256(
                        canonical_json_bytes(
                            dict(self.document.to_dict())  # type: ignore[operator]
                        )
                    )
                except Exception:
                    document_digest = ""
        artifact_digest = ""
        if isinstance(self.artifacts, GeneratedTLAArtifacts):
            artifact_digest = self.artifacts.artifact_digest
        elif isinstance(self.artifacts, Mapping):
            artifact_digest = str(self.artifacts.get("artifact_digest") or "")

        bounds = self.bounds
        bounds_payload: dict[str, int] = {}
        if isinstance(bounds, ExecutionBounds):
            bounds_payload = {
                "max_memory_bytes": bounds.max_memory_bytes,
                "max_output_bytes": bounds.max_output_bytes,
                "max_steps": bounds.max_steps,
                "timeout_ms": bounds.timeout_ms,
            }

        # Encode confidence as integer micros for JSON-safe digests.
        confidence_micros = int(round(float(self.confidence) * 1_000_000))

        payload: dict[str, Any] = {
            "artifact_digest": artifact_digest,
            "available": self.available,
            "bounds": bounds_payload,
            "confidence_micros": confidence_micros,
            "document_digest": document_digest,
            "document_id": document_id,
            "document_kind": document_kind,
            "document_present": self.document is not None,
            "fluent_text_present": bool(self.fluent_text),
            "has_fallback_output": self.has_fallback_output,
            "has_mock_output": self.has_mock_output,
            "interface": self.interface,
            "metadata": dict(self.metadata),
            "mode": (
                self.mode.value
                if isinstance(self.mode, StateExecutionMode)
                else self.mode
            ),
            "module_name": self.module_name,
            "provider": (
                self.provider.value
                if isinstance(self.provider, StateProviderKind)
                else self.provider
            ),
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
        }
        return payload


@dataclass(frozen=True, slots=True)
class StateProviderEvidenceV2:
    """Pinned state-provider evidence with distinct TLC/Apalache surfaces.

    Interface: ``StateProviderEvidence@2``.

    Every answer identifies provider, module, config, bounds, properties,
    semantics axes, and counterexample/replay status.  One provider's support
    never establishes the other's capability.  Authority remains model_check
    and bounded — never theorem.
    """

    evidence_id: str
    request_id: str
    request_digest: str
    provider: StateProviderKind | str
    disposition: StateDisposition | str
    mode: StateExecutionMode | str
    module: StateModuleBindingV2 | Mapping[str, Any]
    config: StateConfigBindingV2 | Mapping[str, Any]
    bounds: StateBoundsBindingV2 | Mapping[str, Any]
    properties: StatePropertyBindingV2 | Mapping[str, Any]
    semantics: StateSemanticsBindingV2 | Mapping[str, Any]
    counterexample: StateCounterexampleBindingV2 | Mapping[str, Any]
    capability: StateCapabilityReceiptV2 | Mapping[str, Any]
    source_ref_ids: tuple[str, ...] | Sequence[str] = ()
    result_authority: ResultAuthority | str = ResultAuthority.MODEL_CHECK
    result_status: ResultStatus | str = ResultStatus.UNKNOWN
    role: ToolRole | str = ToolRole.AUTHORITY
    authority_ceiling: ToolchainAuthorityCeiling | str = (
        ToolchainAuthorityCeiling.BOUNDED
    )
    translation_ceiling: EvidenceAuthority | str = EvidenceAuthority.BOUNDED
    model_check_established: bool = False
    mock_output_present: bool = False
    fallback_output_present: bool = False
    available: bool = False
    confidence: float = 0.0
    fluent_text_present: bool = False
    external_tool_proof: bool = False
    authorizes_universal_proof: bool = False
    receipt: Mapping[str, Any] | None = None
    diagnostics: tuple[str, ...] = ()
    content_digest: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = STATE_PROVIDER_EVIDENCE_SCHEMA

    interface: ClassVar[str] = STATE_PROVIDER_EVIDENCE_V2_INTERFACE

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
            self, "provider", normalize_state_provider(self.provider)
        )
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, StateDisposition, "disposition"),
        )
        object.__setattr__(
            self, "mode", _enum(self.mode, StateExecutionMode, "mode")
        )

        if isinstance(self.module, StateModuleBindingV2):
            module = self.module
        else:
            module = StateModuleBindingV2(
                **_filter_keys(
                    _require_mapping(self.module, "module"),
                    {
                        "module_name",
                        "model_digest",
                        "artifact_digest",
                        "source_document_id",
                        "source_kind",
                        "source_map_size",
                        "schema_version",
                    },
                )
            )
        object.__setattr__(self, "module", module)

        if isinstance(self.config, StateConfigBindingV2):
            config = self.config
        else:
            config = StateConfigBindingV2(
                **_filter_keys(
                    _require_mapping(self.config, "config"),
                    {
                        "provider",
                        "configuration_digest",
                        "configuration_text",
                        "config_kind",
                        "schema_version",
                    },
                )
            )
        object.__setattr__(self, "config", config)
        if config.provider is not self.provider:  # type: ignore[comparison-overlap]
            raise StateAuthorityError(
                "config.provider must match evidence.provider; "
                "TLC and Apalache configurations remain distinct"
            )

        if isinstance(self.bounds, StateBoundsBindingV2):
            bounds = self.bounds
        else:
            bounds = StateBoundsBindingV2(
                **_filter_keys(
                    _require_mapping(self.bounds, "bounds"),
                    {
                        "max_steps",
                        "timeout_ms",
                        "max_declared_steps",
                        "compile_bounds",
                        "finite_state",
                        "step_bounded",
                        "finite_trace_only",
                        "schema_version",
                    },
                )
            )
        object.__setattr__(self, "bounds", bounds)

        if isinstance(self.properties, StatePropertyBindingV2):
            properties = self.properties
        else:
            properties = StatePropertyBindingV2(
                **_filter_keys(
                    _require_mapping(self.properties, "properties"),
                    {
                        "safety_properties",
                        "liveness_properties",
                        "fairness_limitations",
                        "checked_safety",
                        "checked_liveness",
                        "primary_property",
                        "schema_version",
                    },
                )
            )
        object.__setattr__(self, "properties", properties)

        if isinstance(self.semantics, StateSemanticsBindingV2):
            semantics = self.semantics
        else:
            semantics = StateSemanticsBindingV2(
                **_filter_keys(
                    _require_mapping(self.semantics, "semantics"),
                    {
                        "provider",
                        "finite_state",
                        "step_bounded",
                        "safety",
                        "liveness",
                        "fairness",
                        "approximation",
                        "axes",
                        "notes",
                        "schema_version",
                    },
                )
            )
        object.__setattr__(self, "semantics", semantics)
        if semantics.provider is not self.provider:  # type: ignore[comparison-overlap]
            raise StateAuthorityError(
                "semantics.provider must match evidence.provider"
            )

        if isinstance(self.counterexample, StateCounterexampleBindingV2):
            counterexample = self.counterexample
        else:
            counterexample = StateCounterexampleBindingV2(
                **_filter_keys(
                    _require_mapping(self.counterexample, "counterexample"),
                    {
                        "status",
                        "module",
                        "config",
                        "bounds",
                        "property_name",
                        "property_binding",
                        "replayed",
                        "replay_notes",
                        "state_count",
                        "states",
                        "raw_trace",
                        "source",
                        "schema_version",
                    },
                )
            )
        object.__setattr__(self, "counterexample", counterexample)
        if not counterexample.bindings_complete():
            raise StateAuthorityError(
                "counterexample must bind bounds, config, module, property, "
                "and replay outcome"
            )

        if isinstance(self.capability, StateCapabilityReceiptV2):
            capability = self.capability
        else:
            capability = StateCapabilityReceiptV2(
                **_filter_keys(
                    _require_mapping(self.capability, "capability"),
                    {
                        "provider",
                        "available",
                        "supported_document",
                        "capability",
                        "reason",
                        "establishes_other_providers",
                        "jvm_available",
                        "tool_version",
                        "schema_version",
                    },
                )
            )
        object.__setattr__(self, "capability", capability)
        if capability.provider is not self.provider:  # type: ignore[comparison-overlap]
            raise StateAuthorityError(
                "capability.provider must match evidence.provider; "
                "one provider's support cannot establish another's capability"
            )

        # Apalache must never claim checked liveness.
        if self.provider is StateProviderKind.APALACHE:
            if properties.checked_liveness:
                raise StateAuthorityError(
                    "Apalache evidence cannot claim checked_liveness properties"
                )
            if semantics.liveness or semantics.fairness:
                raise StateAuthorityError(
                    "Apalache evidence cannot claim liveness or fairness semantics"
                )

        object.__setattr__(
            self, "source_ref_ids", _source_ref_ids(self.source_ref_ids)
        )

        result_authority = (
            self.result_authority
            if isinstance(self.result_authority, ResultAuthority)
            else ResultAuthority(str(self.result_authority))
        )
        if result_authority is not ResultAuthority.MODEL_CHECK:
            raise StateAuthorityError(
                "StateProviderEvidence@2 result_authority must be model_check; "
                f"got {result_authority!r}"
            )
        object.__setattr__(self, "result_authority", ResultAuthority.MODEL_CHECK)

        result_status = (
            self.result_status
            if isinstance(self.result_status, ResultStatus)
            else ResultStatus(str(self.result_status))
        )
        if result_status in {ResultStatus.PROVED, ResultStatus.DISPROVED}:
            raise StateAuthorityError(
                "StateProviderEvidence@2 cannot claim theorem result statuses"
            )
        object.__setattr__(self, "result_status", result_status)

        role = self.role if isinstance(self.role, ToolRole) else ToolRole(str(self.role))
        if role not in {ToolRole.AUTHORITY, ToolRole.SHADOW}:
            raise StateAuthorityError(
                f"StateProviderEvidence@2 role must be authority or shadow; got {role!r}"
            )
        object.__setattr__(self, "role", role)

        ceiling = (
            self.authority_ceiling
            if isinstance(self.authority_ceiling, ToolchainAuthorityCeiling)
            else ToolchainAuthorityCeiling(str(self.authority_ceiling))
        )
        if ceiling is not ToolchainAuthorityCeiling.BOUNDED:
            raise StateAuthorityError(
                "StateProviderEvidence@2 authority_ceiling must be bounded"
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
            raise StateAuthorityError(
                "StateProviderEvidence@2 translation_ceiling must remain bounded"
            )
        object.__setattr__(self, "translation_ceiling", translation_ceiling)

        for flag_name in (
            "model_check_established",
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
            raise StateAuthorityError(
                "state evidence cannot authorize universal proof"
            )

        if isinstance(self.confidence, bool) or not isinstance(
            self.confidence, (int, float)
        ):
            raise StateExecutionError("confidence must be numeric")
        conf = float(self.confidence)
        if conf != conf or conf < 0.0 or conf > 1.0:
            raise StateExecutionError("confidence must be finite in [0, 1]")
        object.__setattr__(self, "confidence", conf)

        mode = self.mode  # type: ignore[assignment]
        if (
            self.mock_output_present
            or self.fallback_output_present
            or mode in {StateExecutionMode.MOCK, StateExecutionMode.FALLBACK}
        ):
            if self.model_check_established:
                raise StateAuthorityError(
                    "fallback or mock output cannot establish model-check authority"
                )
            object.__setattr__(self, "model_check_established", False)
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
                raise StateExecutionError(
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

        if self.schema_version != STATE_PROVIDER_EVIDENCE_SCHEMA:
            raise StateExecutionError(
                f"unsupported StateProviderEvidence@2 schema: "
                f"{self.schema_version!r}"
            )

        if not self.content_digest:
            object.__setattr__(
                self,
                "content_digest",
                _digest_of(
                    {
                        "bounds": self.bounds.to_dict(),  # type: ignore[union-attr]
                        "config": self.config.to_dict(),  # type: ignore[union-attr]
                        "counterexample": self.counterexample.to_dict(),  # type: ignore[union-attr]
                        "disposition": (
                            self.disposition.value
                            if isinstance(self.disposition, StateDisposition)
                            else self.disposition
                        ),
                        "mode": (
                            self.mode.value
                            if isinstance(self.mode, StateExecutionMode)
                            else self.mode
                        ),
                        "module": self.module.to_dict(),  # type: ignore[union-attr]
                        "properties": self.properties.to_dict(),  # type: ignore[union-attr]
                        "provider": (
                            self.provider.value
                            if isinstance(self.provider, StateProviderKind)
                            else self.provider
                        ),
                        "request_digest": self.request_digest,
                        "request_id": self.request_id,
                        "semantics": self.semantics.to_dict(),  # type: ignore[union-attr]
                    }
                ),
            )
        else:
            object.__setattr__(
                self,
                "content_digest",
                _sha256_hex(self.content_digest, "content_digest"),
            )

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
    def theorem_established(self) -> bool:
        return False

    @property
    def claim_theorem(self) -> bool:
        return False

    @property
    def claim_proof(self) -> bool:
        return False

    @property
    def claim_model_check(self) -> bool:
        return bool(self.model_check_established)

    @property
    def claim_other_provider_capability(self) -> bool:
        return False

    @property
    def counterexample_status(self) -> StateReplayStatus:
        status = self.counterexample.status  # type: ignore[union-attr]
        if isinstance(status, StateReplayStatus):
            return status
        return StateReplayStatus(str(status))

    def establishes_other_provider(
        self, other: StateProviderKind | str
    ) -> bool:
        return provider_support_establishes_other(self.provider, other)  # type: ignore[arg-type]

    def bindings_complete(self) -> bool:
        """True when module, config, bounds, properties, semantics, cex bind."""

        return bool(
            self.module
            and self.config
            and self.bounds
            and self.properties
            and self.semantics
            and self.counterexample
            and self.counterexample.bindings_complete()  # type: ignore[union-attr]
            and self.capability
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
            "claim_model_check": self.claim_model_check,
            "claim_other_provider_capability": False,
            "claim_proof": False,
            "claim_theorem": False,
            "confidence": self.confidence,
            "config": self.config.to_dict(),  # type: ignore[union-attr]
            "content_digest": self.content_digest,
            "counterexample": self.counterexample.to_dict(),  # type: ignore[union-attr]
            "counterexample_status": (
                self.counterexample_status.value
                if isinstance(self.counterexample_status, StateReplayStatus)
                else self.counterexample_status
            ),
            "diagnostics": list(self.diagnostics),
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, StateDisposition)
                else self.disposition
            ),
            "evidence_id": self.evidence_id,
            "external_tool_proof": self.external_tool_proof,
            "fallback_output_present": self.fallback_output_present,
            "fluent_text_present": self.fluent_text_present,
            "interface": self.interface,
            "is_proved": False,
            "is_theorem_authority": False,
            "metadata": dict(self.metadata),
            "mock_output_present": self.mock_output_present,
            "mode": (
                self.mode.value
                if isinstance(self.mode, StateExecutionMode)
                else self.mode
            ),
            "model_check_established": self.model_check_established,
            "module": self.module.to_dict(),  # type: ignore[union-attr]
            "proof_established": False,
            "properties": self.properties.to_dict(),  # type: ignore[union-attr]
            "provider": (
                self.provider.value
                if isinstance(self.provider, StateProviderKind)
                else self.provider
            ),
            "receipt": dict(self.receipt) if self.receipt is not None else None,
            "request_digest": self.request_digest,
            "request_id": self.request_id,
            "result_authority": (
                self.result_authority.value
                if isinstance(self.result_authority, ResultAuthority)
                else self.result_authority
            ),
            "result_status": (
                self.result_status.value
                if isinstance(self.result_status, ResultStatus)
                else self.result_status
            ),
            "role": self.role.value if isinstance(self.role, ToolRole) else self.role,
            "schema_version": self.schema_version,
            "semantics": self.semantics.to_dict(),  # type: ignore[union-attr]
            "source_ref_ids": list(self.source_ref_ids),
            "theorem_established": False,
            "translation_ceiling": (
                self.translation_ceiling.value
                if isinstance(self.translation_ceiling, EvidenceAuthority)
                else self.translation_ceiling
            ),
        }


@dataclass(frozen=True, slots=True)
class StateExecutionResultV2:
    """Normalized execution result wrapping :class:`StateProviderEvidenceV2`.

    Interface: ``StateExecutionResult@2``.
    """

    request_id: str
    request_digest: str
    provider: StateProviderKind | str
    disposition: StateDisposition | str
    evidence: StateProviderEvidenceV2
    result: ModelCheckResult | None = None
    outcome: ModelCheckOutcome | None = None
    schema_version: str = STATE_EXECUTION_RESULT_SCHEMA

    interface: ClassVar[str] = STATE_EXECUTION_RESULT_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _record_id(self.request_id, "request_id")
        )
        object.__setattr__(
            self,
            "request_digest",
            _sha256_hex(self.request_digest, "request_digest"),
        )
        object.__setattr__(
            self, "provider", normalize_state_provider(self.provider)
        )
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, StateDisposition, "disposition"),
        )
        if not isinstance(self.evidence, StateProviderEvidenceV2):
            raise StateExecutionError("evidence must be StateProviderEvidenceV2")
        if self.evidence.provider is not self.provider:  # type: ignore[comparison-overlap]
            raise StateAuthorityError(
                "result.provider must match evidence.provider"
            )
        if self.schema_version != STATE_EXECUTION_RESULT_SCHEMA:
            raise StateExecutionError(
                f"unsupported result schema: {self.schema_version!r}"
            )

    @property
    def counterexample_status(self) -> StateReplayStatus:
        return self.evidence.counterexample_status

    def to_dict(self) -> dict[str, Any]:
        return {
            "counterexample_status": self.counterexample_status.value,
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, StateDisposition)
                else self.disposition
            ),
            "evidence": self.evidence.to_dict(),
            "interface": self.interface,
            "outcome": self.outcome.to_dict() if self.outcome is not None else None,
            "provider": (
                self.provider.value
                if isinstance(self.provider, StateProviderKind)
                else self.provider
            ),
            "request_digest": self.request_digest,
            "request_id": self.request_id,
            "result": self.result.to_dict() if self.result is not None else None,
            "schema_version": self.schema_version,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class StateExecutionEngineV2:
    """Execute TLC / Apalache on independent capability surfaces.

    Interface owner: ``StateProviderEvidence@2``.
    """

    INTERFACE: ClassVar[str] = STATE_PROVIDER_EVIDENCE_V2_INTERFACE
    interface: ClassVar[str] = STATE_PROVIDER_EVIDENCE_V2_INTERFACE
    VERSION: ClassVar[str] = STATE_EXECUTION_V2_MODULE_VERSION
    TASK_ID: ClassVar[str] = STATE_EXECUTION_V2_TASK_ID
    GOAL_ID: ClassVar[str] = STATE_EXECUTION_V2_GOAL_ID

    def __init__(
        self,
        *,
        tlc: TLCBackend | None = None,
        apalache: ApalacheBackend | None = None,
        compiler: TLACompiler | None = None,
        runner: BoundedToolRunner | None = None,
        which: ExecutableFinder | None = None,
        jvm_probe: JvmProbe | None = None,
        lazy_install: bool = True,
    ) -> None:
        self._compiler = compiler or TLACompiler()
        self._runner = runner
        self._tlc = tlc or TLCBackend(
            runner=runner,
            which=which,
            jvm_probe=jvm_probe,
            compiler=self._compiler,
            lazy_install=lazy_install,
        )
        self._apalache = apalache or ApalacheBackend(
            runner=runner,
            which=which,
            jvm_probe=jvm_probe,
            compiler=self._compiler,
            lazy_install=lazy_install,
        )
        if not isinstance(self._tlc, TLCBackend):
            raise StateExecutionError("tlc must be a TLCBackend")
        if not isinstance(self._apalache, ApalacheBackend):
            raise StateExecutionError("apalache must be an ApalacheBackend")

    def backend(
        self, provider: StateProviderKind | str
    ) -> TLCBackend | ApalacheBackend:
        kind = normalize_state_provider(provider)
        if kind is StateProviderKind.TLC:
            return self._tlc
        return self._apalache

    def capability_of(
        self, provider: StateProviderKind | str
    ) -> StateProviderCapability:
        """Return only the named provider's capability (never another's)."""

        return capability_for(provider)

    def capability_receipt(
        self,
        provider: StateProviderKind | str,
        *,
        request_liveness: bool = False,
        request_fairness: bool = False,
    ) -> StateCapabilityReceiptV2:
        kind = normalize_state_provider(provider)
        backend = self.backend(kind)
        available = backend.is_available()
        supported = True
        reason = ""
        cap = capability_for(kind)
        if request_liveness and not cap.checks_liveness:
            supported = False
            reason = f"{kind.value} does not check temporal liveness properties"
        if request_fairness and not cap.checks_fairness:
            supported = False
            reason = (
                reason + "; " if reason else ""
            ) + f"{kind.value} does not check fairness assumptions"
        if not available and not reason:
            reason = f"{kind.value} executable or JVM unavailable"
        jvm_ok = True
        try:
            jvm_ok = bool(backend._jvm_probe())  # noqa: SLF001 — intentional probe
        except Exception:
            jvm_ok = False
        return StateCapabilityReceiptV2(
            provider=kind,
            available=available,
            supported_document=supported,
            capability=cap.to_dict(),
            reason=reason,
            establishes_other_providers=False,
            jvm_available=jvm_ok,
            tool_version="",
        )

    def probe_all(self) -> dict[StateProviderKind, StateCapabilityReceiptV2]:
        """Probe each provider independently; never cross-establish capability."""

        return {
            kind: self.capability_receipt(kind) for kind in StateProviderKind
        }

    def execute(
        self,
        request: StateExecutionRequestV2 | Mapping[str, Any],
    ) -> StateExecutionResultV2:
        """Execute one typed state request on a single provider path."""

        req = (
            request
            if isinstance(request, StateExecutionRequestV2)
            else StateExecutionRequestV2(
                **_filter_keys(
                    _require_mapping(request, "request"),
                    {
                        "request_id",
                        "provider",
                        "mode",
                        "document",
                        "artifacts",
                        "module_name",
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
        provider: StateProviderKind = req.provider  # type: ignore[assignment]
        capability = self.capability_receipt(provider)

        if req.has_mock_output or req.mode is StateExecutionMode.MOCK:
            return self._rejected(
                req,
                request_digest=request_digest,
                disposition=StateDisposition.MOCK_REJECTED,
                mode=StateExecutionMode.MOCK,
                capability=capability,
                mock_output_present=True,
                fallback_output_present=req.has_fallback_output,
                diagnostics=(
                    "mock_output_cannot_establish_model_check",
                    "mock_output_cannot_establish_proof",
                    "mock_output_cannot_establish_theorem",
                    "mock_output_cannot_establish_other_provider_capability",
                ),
            )

        if req.has_fallback_output or req.mode is StateExecutionMode.FALLBACK:
            return self._rejected(
                req,
                request_digest=request_digest,
                disposition=StateDisposition.FALLBACK_REJECTED,
                mode=StateExecutionMode.FALLBACK,
                capability=capability,
                mock_output_present=False,
                fallback_output_present=True,
                diagnostics=(
                    "fallback_output_cannot_establish_model_check",
                    "fallback_output_cannot_establish_proof",
                    "fallback_output_cannot_establish_other_provider_capability",
                ),
            )

        if req.mode is StateExecutionMode.CAPABILITY_PROBE:
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

    def execute_split_providers(
        self,
        *,
        document: object | None = None,
        artifacts: GeneratedTLAArtifacts | None = None,
        request_id_prefix: str = "req:state:split",
        bounds: ExecutionBounds | None = None,
        module_name: str = "StateModel",
    ) -> dict[StateProviderKind, StateExecutionResultV2]:
        """Run each provider path independently; results never cross-establish."""

        results: dict[StateProviderKind, StateExecutionResultV2] = {}
        for kind in StateProviderKind:
            req = StateExecutionRequestV2(
                request_id=f"{request_id_prefix}:{kind.value}",
                provider=kind,
                document=document,
                artifacts=artifacts,
                module_name=module_name,
                bounds=bounds,
                mode=StateExecutionMode.ENGINE,
            )
            results[kind] = self.execute(req)
            for other in StateProviderKind:
                if other is kind:
                    continue
                if results[kind].evidence.establishes_other_provider(other):
                    raise StateAuthorityError(
                        f"{kind.value} result established {other.value} capability"
                    )
        return results

    # --- internal paths ----------------------------------------------------

    def _resolve_artifacts(
        self, req: StateExecutionRequestV2
    ) -> GeneratedTLAArtifacts:
        if isinstance(req.artifacts, GeneratedTLAArtifacts):
            return req.artifacts
        if isinstance(req.artifacts, Mapping):
            return self._artifacts_from_mapping(req.artifacts, req.module_name)
        if req.document is not None:
            try:
                return self._compiler.compile(
                    req.document, module_name=req.module_name
                )
            except (TLACompilerError, TypeError, ValueError) as error:
                raise StateExecutionError(
                    f"failed to compile state document: {error}"
                ) from error
        raise StateExecutionError(
            "engine mode requires document or GeneratedTLAArtifacts"
        )

    def _artifacts_from_mapping(
        self, data: Mapping[str, Any], module_name: str
    ) -> GeneratedTLAArtifacts:
        model_text = str(data.get("model_text") or "")
        if not model_text:
            raise StateExecutionError("artifacts payload requires model_text")
        bounds_raw = data.get("bounds")
        if isinstance(bounds_raw, TLACompileBounds):
            bounds = bounds_raw
        elif isinstance(bounds_raw, Mapping):
            bounds = TLACompileBounds.from_dict(bounds_raw)
        else:
            bounds = self._compiler.bounds
        source_map_raw = data.get("source_map") or ()
        source_map: list[TLASourceMapEntry] = []
        for item in source_map_raw:
            if isinstance(item, TLASourceMapEntry):
                source_map.append(item)
            elif isinstance(item, Mapping):
                source_map.append(
                    TLASourceMapEntry(
                        source_id=str(item.get("source_id", "")),
                        source_kind=str(item.get("source_kind", "unknown")),
                        tla_symbol=str(item.get("tla_symbol", "X")),
                        role=str(item.get("role", "symbol")),
                        line_hint=str(item.get("line_hint", "")),
                    )
                )
        return GeneratedTLAArtifacts(
            module_name=str(data.get("module_name", module_name)),
            model_text=model_text if model_text.endswith("\n") else model_text + "\n",
            tlc_config_text=str(
                data.get("tlc_config_text")
                or "SPECIFICATION Spec\nINVARIANT Safety\n"
            ),
            apalache_config_text=str(
                data.get("apalache_config_text")
                or "INIT Init\nNEXT Next\nINVARIANT Safety\n"
            ),
            source_map=tuple(source_map),
            losses=(),
            bounds=bounds,
            source_document_id=str(data.get("source_document_id", "raw")),
            source_kind=str(data.get("source_kind", "payload")),
            safety_properties=tuple(data.get("safety_properties") or ("Safety",)),
            liveness_properties=tuple(data.get("liveness_properties") or ()),
            fairness_limitations=tuple(data.get("fairness_limitations") or ()),
        )

    def _execute_engine(
        self,
        req: StateExecutionRequestV2,
        *,
        request_digest: str,
        capability: StateCapabilityReceiptV2,
    ) -> StateExecutionResultV2:
        provider: StateProviderKind = req.provider  # type: ignore[assignment]
        bounds: ExecutionBounds = req.bounds  # type: ignore[assignment]
        backend = self.backend(provider)

        try:
            artifacts = self._resolve_artifacts(req)
        except StateExecutionError as error:
            return self._error_result(
                req,
                request_digest=request_digest,
                capability=capability,
                disposition=StateDisposition.MALFORMED,
                reason=str(error),
            )

        # Reject Apalache requests that require liveness if only liveness props exist.
        cap = capability_for(provider)
        if (
            provider is StateProviderKind.APALACHE
            and artifacts.liveness_properties
            and not artifacts.safety_properties
        ):
            return self._error_result(
                req,
                request_digest=request_digest,
                capability=StateCapabilityReceiptV2(
                    provider=provider,
                    available=capability.available,
                    supported_document=False,
                    capability=cap.to_dict(),
                    reason="Apalache cannot check pure liveness obligations",
                    jvm_available=capability.jvm_available,
                ),
                disposition=StateDisposition.UNSUPPORTED,
                reason="Apalache cannot check pure liveness obligations",
                artifacts=artifacts,
            )

        backend_request = BackendRequest(
            request_id=req.request_id,
            claim_id=f"claim:state:{req.request_id}",
            declaration_id=f"declaration:state:{req.request_id}",
            claim_digest=request_digest,
            obligation_id=f"obligation:state:{req.request_id}",
            obligation_digest=request_digest,
            assumption_ids=("assumption:bounded-model-check",),
            logic_family="state_transition",
            query_kind=QueryKind.SATISFIABILITY,
            bounds=bounds,
            payload=FrozenMap(
                {
                    "module_name": artifacts.module_name,
                    "provider": provider.value,
                }
            ),
            requested_backend_id=backend.backend_id,
        )

        try:
            outcome = backend.check(
                artifacts, request=backend_request
            )
        except TLARunnerError as error:
            return self._error_result(
                req,
                request_digest=request_digest,
                capability=capability,
                disposition=StateDisposition.ERROR,
                reason=str(error),
                artifacts=artifacts,
            )

        return self._from_outcome(
            req,
            request_digest=request_digest,
            capability=capability,
            outcome=outcome,
            artifacts=artifacts,
        )

    def _from_outcome(
        self,
        req: StateExecutionRequestV2,
        *,
        request_digest: str,
        capability: StateCapabilityReceiptV2,
        outcome: ModelCheckOutcome,
        artifacts: GeneratedTLAArtifacts,
    ) -> StateExecutionResultV2:
        provider: StateProviderKind = req.provider  # type: ignore[assignment]
        bounds: ExecutionBounds = req.bounds  # type: ignore[assignment]
        receipt = outcome.receipt
        disposition = _status_to_disposition(receipt.status)
        result_status = _status_to_result_status(receipt.status)

        # Keep capability tool version from receipt.
        capability = StateCapabilityReceiptV2(
            provider=provider,
            available=capability.available
            and receipt.status is not ModelCheckOutcomeStatus.UNAVAILABLE,
            supported_document=capability.supported_document,
            capability=capability_for(provider).to_dict(),
            reason=receipt.reason if disposition is StateDisposition.UNAVAILABLE else capability.reason,
            jvm_available=receipt.jvm_available,
            tool_version=receipt.tool_version,
        )

        module = StateModuleBindingV2.from_artifacts(
            artifacts, module_name=req.module_name
        )
        config = StateConfigBindingV2.from_artifacts(artifacts, provider)
        bounds_binding = StateBoundsBindingV2.from_artifacts_and_request(
            artifacts, provider=provider, bounds=bounds
        )
        raw_trace = ""
        if receipt.counterexample is not None:
            raw_trace = str(receipt.counterexample.raw or "")
        if not raw_trace:
            raw_trace = str(receipt.stdout or "")
        properties = StatePropertyBindingV2.from_artifacts_and_receipt(
            artifacts,
            checked_safety=receipt.checked_safety_properties,
            checked_liveness=receipt.checked_liveness_properties,
            fairness_limitations=receipt.fairness_limitations,
            raw_trace=raw_trace,
        )
        semantics = StateSemanticsBindingV2.from_capability(
            provider,
            notes=tuple(artifacts.fairness_limitations)
            + capability_for(provider).approximation_notes,
        )
        counterexample = StateCounterexampleBindingV2.from_trace(
            disposition=disposition,
            trace=receipt.counterexample,
            module=module,
            config=config,
            bounds=bounds_binding,
            properties=properties,
        )

        model_check_established = disposition in {
            StateDisposition.SATISFIED,
            StateDisposition.COUNTEREXAMPLE,
        } and req.mode in {
            StateExecutionMode.ENGINE,
            StateExecutionMode.HERMETIC_FIXTURE,
        }

        mode = req.mode
        if isinstance(mode, str):
            mode = StateExecutionMode(mode)
        # Hermetic fixture is still engine-backed when runners are injected.
        if mode is StateExecutionMode.HERMETIC_FIXTURE:
            established_mode = StateExecutionMode.HERMETIC_FIXTURE
        else:
            established_mode = StateExecutionMode.ENGINE

        evidence = StateProviderEvidenceV2(
            evidence_id=f"evidence:state:{provider.value}:{req.request_id}",
            request_id=req.request_id,
            request_digest=request_digest,
            provider=provider,
            disposition=disposition,
            mode=established_mode,
            module=module,
            config=config,
            bounds=bounds_binding,
            properties=properties,
            semantics=semantics,
            counterexample=counterexample,
            capability=capability,
            source_ref_ids=req.source_ref_ids,
            result_authority=ResultAuthority.MODEL_CHECK,
            result_status=result_status,
            role=ToolRole.AUTHORITY,
            authority_ceiling=ToolchainAuthorityCeiling.BOUNDED,
            translation_ceiling=EvidenceAuthority.BOUNDED,
            model_check_established=model_check_established,
            available=capability.available,
            confidence=req.confidence,
            fluent_text_present=bool(req.fluent_text),
            external_tool_proof=model_check_established,
            receipt=_evidence_receipt_payload(receipt),
            diagnostics=tuple(
                item
                for item in (
                    receipt.reason,
                    *(
                        receipt.counterexample.replay_notes
                        if receipt.counterexample is not None
                        else ()
                    ),
                )
                if item
            ),
        )

        return StateExecutionResultV2(
            request_id=req.request_id,
            request_digest=request_digest,
            provider=provider,
            disposition=disposition,
            evidence=evidence,
            result=outcome.result if isinstance(outcome.result, ModelCheckResult) else None,
            outcome=outcome,
        )

    def _placeholder_bindings(
        self,
        req: StateExecutionRequestV2,
        *,
        provider: StateProviderKind,
    ) -> tuple[
        StateModuleBindingV2,
        StateConfigBindingV2,
        StateBoundsBindingV2,
        StatePropertyBindingV2,
        StateSemanticsBindingV2,
        StateCounterexampleBindingV2,
    ]:
        """Build minimal bindings when no artifacts are available (reject paths)."""

        empty_digest = "0" * 64
        try:
            artifacts = self._resolve_artifacts(req)
            module = StateModuleBindingV2.from_artifacts(
                artifacts, module_name=req.module_name
            )
            config = StateConfigBindingV2.from_artifacts(artifacts, provider)
            bounds = StateBoundsBindingV2.from_artifacts_and_request(
                artifacts,
                provider=provider,
                bounds=req.bounds,  # type: ignore[arg-type]
            )
            properties = StatePropertyBindingV2.from_artifacts_and_receipt(
                artifacts
            )
        except StateExecutionError:
            module = StateModuleBindingV2(
                module_name=req.module_name,
                model_digest=empty_digest,
                artifact_digest=empty_digest,
                source_document_id="none",
                source_kind="none",
            )
            config = StateConfigBindingV2(
                provider=provider,
                configuration_digest=empty_digest,
                configuration_text="",
            )
            bounds_obj: ExecutionBounds = req.bounds  # type: ignore[assignment]
            cap = capability_for(provider)
            bounds = StateBoundsBindingV2(
                max_steps=max(1, bounds_obj.max_steps),
                timeout_ms=bounds_obj.timeout_ms,
                max_declared_steps=cap.max_declared_steps,
                compile_bounds={},
                finite_state=cap.finite_state,
                step_bounded=cap.step_bounded,
                finite_trace_only=cap.finite_trace_only,
            )
            properties = StatePropertyBindingV2(
                safety_properties=("Safety",),
                liveness_properties=(),
                primary_property="Safety",
            )
        semantics = StateSemanticsBindingV2.from_capability(provider)
        counterexample = StateCounterexampleBindingV2.from_trace(
            disposition=StateDisposition.UNAVAILABLE,
            trace=None,
            module=module,
            config=config,
            bounds=bounds,
            properties=properties,
        )
        return module, config, bounds, properties, semantics, counterexample

    def _rejected(
        self,
        req: StateExecutionRequestV2,
        *,
        request_digest: str,
        disposition: StateDisposition,
        mode: StateExecutionMode,
        capability: StateCapabilityReceiptV2,
        mock_output_present: bool,
        fallback_output_present: bool,
        diagnostics: tuple[str, ...],
    ) -> StateExecutionResultV2:
        provider: StateProviderKind = req.provider  # type: ignore[assignment]
        (
            module,
            config,
            bounds,
            properties,
            semantics,
            _cex,
        ) = self._placeholder_bindings(req, provider=provider)
        counterexample = StateCounterexampleBindingV2.from_trace(
            disposition=disposition,
            trace=None,
            module=module,
            config=config,
            bounds=bounds,
            properties=properties,
        )
        evidence = StateProviderEvidenceV2(
            evidence_id=f"evidence:state:{provider.value}:{req.request_id}",
            request_id=req.request_id,
            request_digest=request_digest,
            provider=provider,
            disposition=disposition,
            mode=mode,
            module=module,
            config=config,
            bounds=bounds,
            properties=properties,
            semantics=semantics,
            counterexample=counterexample,
            capability=capability,
            source_ref_ids=req.source_ref_ids,
            result_status=ResultStatus.UNKNOWN,
            model_check_established=False,
            mock_output_present=mock_output_present,
            fallback_output_present=fallback_output_present,
            available=False,
            confidence=req.confidence,
            fluent_text_present=bool(req.fluent_text),
            diagnostics=diagnostics,
        )
        return StateExecutionResultV2(
            request_id=req.request_id,
            request_digest=request_digest,
            provider=provider,
            disposition=disposition,
            evidence=evidence,
        )

    def _capability_only(
        self,
        req: StateExecutionRequestV2,
        *,
        request_digest: str,
        capability: StateCapabilityReceiptV2,
    ) -> StateExecutionResultV2:
        provider: StateProviderKind = req.provider  # type: ignore[assignment]
        (
            module,
            config,
            bounds,
            properties,
            semantics,
            counterexample,
        ) = self._placeholder_bindings(req, provider=provider)
        counterexample = StateCounterexampleBindingV2.from_trace(
            disposition=StateDisposition.CAPABILITY_ONLY,
            trace=None,
            module=module,
            config=config,
            bounds=bounds,
            properties=properties,
        )
        evidence = StateProviderEvidenceV2(
            evidence_id=f"evidence:state:{provider.value}:{req.request_id}",
            request_id=req.request_id,
            request_digest=request_digest,
            provider=provider,
            disposition=StateDisposition.CAPABILITY_ONLY,
            mode=StateExecutionMode.CAPABILITY_PROBE,
            module=module,
            config=config,
            bounds=bounds,
            properties=properties,
            semantics=semantics,
            counterexample=counterexample,
            capability=capability,
            source_ref_ids=req.source_ref_ids,
            result_status=ResultStatus.UNKNOWN,
            model_check_established=False,
            available=capability.available,
            confidence=req.confidence,
            diagnostics=("capability_probe_only",),
        )
        return StateExecutionResultV2(
            request_id=req.request_id,
            request_digest=request_digest,
            provider=provider,
            disposition=StateDisposition.CAPABILITY_ONLY,
            evidence=evidence,
        )

    def _error_result(
        self,
        req: StateExecutionRequestV2,
        *,
        request_digest: str,
        capability: StateCapabilityReceiptV2,
        disposition: StateDisposition,
        reason: str,
        artifacts: GeneratedTLAArtifacts | None = None,
    ) -> StateExecutionResultV2:
        provider: StateProviderKind = req.provider  # type: ignore[assignment]
        bounds: ExecutionBounds = req.bounds  # type: ignore[assignment]
        if artifacts is not None:
            module = StateModuleBindingV2.from_artifacts(
                artifacts, module_name=req.module_name
            )
            config = StateConfigBindingV2.from_artifacts(artifacts, provider)
            bounds_binding = StateBoundsBindingV2.from_artifacts_and_request(
                artifacts, provider=provider, bounds=bounds
            )
            properties = StatePropertyBindingV2.from_artifacts_and_receipt(
                artifacts
            )
        else:
            (
                module,
                config,
                bounds_binding,
                properties,
                _,
                _,
            ) = self._placeholder_bindings(req, provider=provider)
        semantics = StateSemanticsBindingV2.from_capability(provider)
        counterexample = StateCounterexampleBindingV2.from_trace(
            disposition=disposition,
            trace=None,
            module=module,
            config=config,
            bounds=bounds_binding,
            properties=properties,
        )
        result_status = {
            StateDisposition.UNAVAILABLE: ResultStatus.UNAVAILABLE,
            StateDisposition.UNSUPPORTED: ResultStatus.UNSUPPORTED,
            StateDisposition.TIMEOUT: ResultStatus.TIMEOUT,
            StateDisposition.ERROR: ResultStatus.ERROR,
            StateDisposition.MALFORMED: ResultStatus.MALFORMED,
        }.get(disposition, ResultStatus.UNKNOWN)
        evidence = StateProviderEvidenceV2(
            evidence_id=f"evidence:state:{provider.value}:{req.request_id}",
            request_id=req.request_id,
            request_digest=request_digest,
            provider=provider,
            disposition=disposition,
            mode=StateExecutionMode.ENGINE,
            module=module,
            config=config,
            bounds=bounds_binding,
            properties=properties,
            semantics=semantics,
            counterexample=counterexample,
            capability=capability,
            source_ref_ids=req.source_ref_ids,
            result_status=result_status,
            model_check_established=False,
            available=capability.available,
            diagnostics=(reason,),
        )
        return StateExecutionResultV2(
            request_id=req.request_id,
            request_digest=request_digest,
            provider=provider,
            disposition=disposition,
            evidence=evidence,
        )


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def execute_state(
    *,
    provider: StateProviderKind | str,
    document: object | None = None,
    artifacts: GeneratedTLAArtifacts | Mapping[str, Any] | None = None,
    request_id: str = "req:state:1",
    module_name: str = "StateModel",
    bounds: ExecutionBounds | None = None,
    mode: StateExecutionMode | str = StateExecutionMode.ENGINE,
    engine: StateExecutionEngineV2 | None = None,
    source_ref_ids: Sequence[str] = (),
    **kwargs: Any,
) -> StateExecutionResultV2:
    """Execute one state-model check on the named provider."""

    eng = engine or StateExecutionEngineV2()
    return eng.execute(
        StateExecutionRequestV2(
            request_id=request_id,
            provider=provider,
            document=document,
            artifacts=artifacts,
            module_name=module_name,
            bounds=bounds,
            mode=mode,
            source_ref_ids=tuple(source_ref_ids),
            **kwargs,
        )
    )


def execute_tlc(
    document: object | None = None,
    *,
    artifacts: GeneratedTLAArtifacts | Mapping[str, Any] | None = None,
    request_id: str = "req:state:tlc",
    module_name: str = "StateModel",
    bounds: ExecutionBounds | None = None,
    engine: StateExecutionEngineV2 | None = None,
    **kwargs: Any,
) -> StateExecutionResultV2:
    """Execute TLC on a document or precompiled artifacts."""

    return execute_state(
        provider=StateProviderKind.TLC,
        document=document,
        artifacts=artifacts,
        request_id=request_id,
        module_name=module_name,
        bounds=bounds,
        engine=engine,
        **kwargs,
    )


def execute_apalache(
    document: object | None = None,
    *,
    artifacts: GeneratedTLAArtifacts | Mapping[str, Any] | None = None,
    request_id: str = "req:state:apalache",
    module_name: str = "StateModel",
    bounds: ExecutionBounds | None = None,
    engine: StateExecutionEngineV2 | None = None,
    **kwargs: Any,
) -> StateExecutionResultV2:
    """Execute Apalache on a document or precompiled artifacts."""

    return execute_state(
        provider=StateProviderKind.APALACHE,
        document=document,
        artifacts=artifacts,
        request_id=request_id,
        module_name=module_name,
        bounds=bounds,
        engine=engine,
        **kwargs,
    )


def hermetic_engine(
    *,
    tlc_stdout: str = "Model checking completed. No error has been found.\n",
    apalache_stdout: str = "Checker reports no error\n",
    tlc_available: bool = True,
    apalache_available: bool = True,
    tlc_returncode: int = 0,
    apalache_returncode: int = 0,
    tlc_timed_out: bool = False,
    apalache_timed_out: bool = False,
    compiler: TLACompiler | None = None,
) -> StateExecutionEngineV2:
    """Build an engine with hermetic fixed stdout for offline tests."""

    from ipfs_datasets_py.logic.backends.process import RawProcessResult

    def _runner(
        stdout: str,
        *,
        available: bool,
        returncode: int,
        timed_out: bool,
    ) -> BoundedToolRunner:
        def execute(invocation, _cancellation):  # noqa: ARG001
            return RawProcessResult(
                returncode=None if not available else returncode,
                stdout="" if not available else stdout,
                elapsed_seconds=0.012,
                timed_out=timed_out,
                process_tree_terminated=timed_out,
                error="executable not found" if not available else "",
            )

        return BoundedToolRunner(executor=execute)

    which_tlc: ExecutableFinder = (
        (lambda name: "/usr/bin/tlc" if name in {"tlc", "tlc2", "tla2tools"} else None)
        if tlc_available
        else (lambda _name: None)
    )
    which_apalache: ExecutableFinder = (
        (
            lambda name: "/usr/bin/apalache-mc"
            if name in {"apalache-mc", "apalache"}
            else None
        )
        if apalache_available
        else (lambda _name: None)
    )

    return StateExecutionEngineV2(
        tlc=TLCBackend(
            runner=_runner(
                tlc_stdout,
                available=tlc_available,
                returncode=tlc_returncode,
                timed_out=tlc_timed_out,
            ),
            which=which_tlc,
            jvm_probe=lambda: tlc_available,
            compiler=compiler,
            lazy_install=False,
        ),
        apalache=ApalacheBackend(
            runner=_runner(
                apalache_stdout,
                available=apalache_available,
                returncode=apalache_returncode,
                timed_out=apalache_timed_out,
            ),
            which=which_apalache,
            jvm_probe=lambda: apalache_available,
            compiler=compiler,
            lazy_install=False,
        ),
        compiler=compiler,
        lazy_install=False,
    )


def lane_logic_identity() -> LogicIdentity:
    return lane_id(STATE_LANE_ID)


__all__ = [
    "APALACHE_STATE_CAPABILITY",
    "STATE_EXECUTION_V2_GOAL_ID",
    "STATE_EXECUTION_V2_MODULE_VERSION",
    "STATE_EXECUTION_V2_TASK_ID",
    "STATE_PROVIDER_EVIDENCE_V2_INTERFACE",
    "TLC_STATE_CAPABILITY",
    "StateAuthorityError",
    "StateBoundsBindingV2",
    "StateCapabilityReceiptV2",
    "StateClaimKind",
    "StateConfigBindingV2",
    "StateCounterexampleBindingV2",
    "StateDisposition",
    "StateExecutionEngineV2",
    "StateExecutionError",
    "StateExecutionMode",
    "StateExecutionRequestV2",
    "StateExecutionResultV2",
    "StateModuleBindingV2",
    "StatePropertyBindingV2",
    "StateProviderCapability",
    "StateProviderEvidenceV2",
    "StateProviderKind",
    "StateReplayStatus",
    "StateSemanticsAxis",
    "StateSemanticsBindingV2",
    "capability_for",
    "execute_apalache",
    "execute_state",
    "execute_tlc",
    "hermetic_engine",
    "non_authoritative_signal_establishes",
    "normalize_state_provider",
    "parse_counterexample_trace",
    "provider_logic_identity",
    "provider_support_establishes_other",
    "replay_counterexample",
]
