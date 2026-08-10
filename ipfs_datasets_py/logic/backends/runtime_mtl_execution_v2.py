"""Wire runtime MTL to real monitoring and verdict replay (LFP2-036).

Interface: ``RuntimeMTLEvidence@2``

Replaces deferred UNKNOWN routing with actual monitor invocation.  Every
evaluated answer binds:

* primary clock / event-time,
* lateness detection,
* finite vs finite-prefix semantics,
* metric intervals (MTL),
* monitorability, and
* three-valued verdicts (true / false / inconclusive).

Authority is always finite-trace **monitor** authority.  A clean prefix or
no-violation-observed outcome never elevates to theorem / proof /
satisfiability.  Mock, fallback, availability, and confidence never establish
monitor authority.

Acceptance (fail-closed):

* Deferred / placeholder unknown remains only an explicit unsupported or
  unavailable outcome — never a silent substitute for evaluation.
* Evaluated verdicts replay against the same formula, trace, position, and
  semantics binding.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.results import (
    MonitorResult,
    ResultAuthority,
    ResultStatus,
)
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.families.namespaces import LogicIdentity, provider_id
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds, ResourceUsage
from ipfs_datasets_py.logic.software_verification.monitoring.runtime_mtl import (
    RUNTIME_MTL_INTERFACE,
    Formula,
    Logic,
    MonitorAuthority,
    MonitorEvaluation,
    MonitorStatus,
    Monitorability,
    RuntimeMTLError,
    RuntimeMTLMonitor,
    Trace,
    TraceKind,
    Verdict,
    classify_monitorability,
    golden_fixtures,
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

RUNTIME_MTL_EVIDENCE_V2_INTERFACE: Final = "RuntimeMTLEvidence@2"
RUNTIME_MTL_EXECUTION_REQUEST_V2_INTERFACE: Final = "RuntimeMTLExecutionRequest@2"
RUNTIME_MTL_EXECUTION_RESULT_V2_INTERFACE: Final = "RuntimeMTLExecutionResult@2"
RUNTIME_MTL_SEMANTICS_BINDING_V2_INTERFACE: Final = "RuntimeMTLSemanticsBinding@2"
RUNTIME_MTL_REPLAY_RECEIPT_V2_INTERFACE: Final = "RuntimeMTLReplayReceipt@2"

RUNTIME_MTL_EVIDENCE_SCHEMA: Final = "runtime-mtl-evidence/v2"
RUNTIME_MTL_EXECUTION_REQUEST_SCHEMA: Final = "runtime-mtl-execution-request/v2"
RUNTIME_MTL_EXECUTION_RESULT_SCHEMA: Final = "runtime-mtl-execution-result/v2"
RUNTIME_MTL_SEMANTICS_BINDING_SCHEMA: Final = "runtime-mtl-semantics-binding/v2"
RUNTIME_MTL_REPLAY_RECEIPT_SCHEMA: Final = "runtime-mtl-replay-receipt/v2"

RUNTIME_MTL_EXECUTION_V2_MODULE_VERSION: Final = "1.0.0"
RUNTIME_MTL_EXECUTION_V2_TASK_ID: Final = "LFP2-036"
RUNTIME_MTL_EXECUTION_V2_GOAL_ID: Final = "LFP2-G060"

RUNTIME_MTL_LANE_ID: Final = "runtime_mtl"
RUNTIME_MTL_EVIDENCE_KIND: Final = "monitor"
RUNTIME_MTL_PROVIDER_ID: Final = "runtime-mtl"
RUNTIME_MTL_EXTERNAL_PROVIDER_ID: Final = "runtime-mtl-external"
RUNTIME_MTL_MONITOR_INTERFACE: Final = RUNTIME_MTL_INTERFACE

_MAX_DIAGNOSTICS: Final = 64
_MAX_METADATA_BYTES: Final = 8_192
_MAX_SOURCE_REFS: Final = 64

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
        "deferred",
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


class RuntimeMTLExecutionError(SyntaxContractError):
    """Raised when runtime MTL execution v2 inputs are malformed."""


class RuntimeMTLAuthorityError(RuntimeMTLExecutionError):
    """Raised when a claim would exceed the finite-trace monitor ceiling."""


class RuntimeMTLProviderKind(StrEnum):
    """Closed set of runtime MTL providers."""

    RUNTIME_MTL = "runtime_mtl"
    RUNTIME_MTL_EXTERNAL = "runtime_mtl_external"


class RuntimeMTLExecutionMode(StrEnum):
    """How the monitoring result was produced.

    Only ``native_monitor`` may establish monitor authority.  Mock, fallback,
    deferred, and unavailable modes never do.
    """

    NATIVE_MONITOR = "native_monitor"
    EXTERNAL_SHADOW = "external_shadow"
    FALLBACK = "fallback"
    MOCK = "mock"
    DEFERRED = "deferred"
    UNAVAILABLE = "unavailable"


class RuntimeMTLDisposition(StrEnum):
    """Closed set of runtime MTL execution dispositions."""

    SATISFIED = "satisfied"
    VIOLATED = "violated"
    INCONCLUSIVE = "inconclusive"
    MALFORMED = "malformed"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    MOCK_REJECTED = "mock_rejected"
    FALLBACK_REJECTED = "fallback_rejected"
    DEFERRED_REJECTED = "deferred_rejected"
    REPLAY_MISMATCH = "replay_mismatch"


class RuntimeMTLClaimKind(StrEnum):
    """Claims that mock / deferred / availability must never establish alone."""

    MONITOR = "monitor"
    PROOF = "proof"
    SATISFIABILITY = "satisfiability"
    THEOREM = "theorem"


_PROVIDER_ALIASES: Final[dict[str, RuntimeMTLProviderKind]] = {
    "runtime_mtl": RuntimeMTLProviderKind.RUNTIME_MTL,
    "runtime-mtl": RuntimeMTLProviderKind.RUNTIME_MTL,
    "runtime.mtl": RuntimeMTLProviderKind.RUNTIME_MTL,
    "mtl": RuntimeMTLProviderKind.RUNTIME_MTL,
    "runtime_mtl_monitoring": RuntimeMTLProviderKind.RUNTIME_MTL,
    "runtime-mtl-monitoring": RuntimeMTLProviderKind.RUNTIME_MTL,
    "runtime_mtl_external": RuntimeMTLProviderKind.RUNTIME_MTL_EXTERNAL,
    "runtime-mtl-external": RuntimeMTLProviderKind.RUNTIME_MTL_EXTERNAL,
    "runtime.mtl.external": RuntimeMTLProviderKind.RUNTIME_MTL_EXTERNAL,
}


def normalize_runtime_mtl_provider(
    value: RuntimeMTLProviderKind | str,
) -> RuntimeMTLProviderKind:
    """Normalize provider labels into the closed runtime MTL provider set."""

    if isinstance(value, RuntimeMTLProviderKind):
        return value
    key = str(value).strip().lower().replace("-", "_").replace(".", "_")
    if key not in _PROVIDER_ALIASES:
        alt = str(value).strip().lower()
        if alt in _PROVIDER_ALIASES:
            return _PROVIDER_ALIASES[alt]
        raise RuntimeMTLExecutionError(
            f"unsupported runtime MTL provider: {value!r}; "
            f"expected runtime_mtl or runtime_mtl_external"
        )
    return _PROVIDER_ALIASES[key]


def provider_backend_id(provider: RuntimeMTLProviderKind) -> str:
    if provider is RuntimeMTLProviderKind.RUNTIME_MTL_EXTERNAL:
        return RUNTIME_MTL_EXTERNAL_PROVIDER_ID
    return RUNTIME_MTL_PROVIDER_ID


def provider_logic_identity(provider: RuntimeMTLProviderKind) -> LogicIdentity:
    return provider_id(provider_backend_id(provider))


def non_authoritative_signal_establishes(
    claim: RuntimeMTLClaimKind | str,
    *,
    mock_output: object = None,
    fallback_output: object = None,
    deferred: bool | None = None,
    available: bool | None = None,
    confidence: float | None = None,
    fluent_text: str | None = None,
) -> bool:
    """Always ``False``: non-monitor signals never establish claims."""

    del (
        claim,
        mock_output,
        fallback_output,
        deferred,
        available,
        confidence,
        fluent_text,
    )
    return False


def deferred_or_mock_establishes_monitor(
    *,
    mock_output: object = None,
    deferred: bool | None = None,
    available: bool | None = None,
) -> bool:
    """Explicit acceptance helper: deferred/mock never establish monitor authority."""

    return non_authoritative_signal_establishes(
        RuntimeMTLClaimKind.MONITOR,
        mock_output=mock_output,
        deferred=deferred,
        available=available,
    )


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
        raise RuntimeMTLExecutionError(
            f"{field_name} must be one of: {allowed}; got {value!r}"
        ) from error


def _optional_bool(value: object, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise RuntimeMTLExecutionError(f"{field_name} must be a boolean")


def _unit_interval(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeMTLExecutionError(f"{field_name} must be numeric")
    conf = float(value)
    if conf != conf or conf < 0.0 or conf > 1.0:
        raise RuntimeMTLExecutionError(f"{field_name} must be finite in [0, 1]")
    return conf


def _digest_of(payload: Mapping[str, Any]) -> str:
    return content_sha256(canonical_json_bytes(dict(payload)))


def _source_ref_ids(value: object, field_name: str = "source_ref_ids") -> tuple[str, ...]:
    items = _require_sequence(value, field_name)
    if len(items) > _MAX_SOURCE_REFS:
        raise RuntimeMTLExecutionError(
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
            raise RuntimeMTLAuthorityError(
                f"{field_name} rejects free-form authority/signal key {key!r}; "
                "use typed runtime MTL evidence fields only"
            )


def _bound_diagnostics(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    items = _require_sequence(value, "diagnostics")
    out: list[str] = []
    for index, item in enumerate(items[:_MAX_DIAGNOSTICS]):
        out.append(_text(item, f"diagnostics[{index}]", maximum=512))
    return tuple(out)


def _coerce_formula(value: object) -> Formula:
    if isinstance(value, Formula):
        return value
    try:
        return Formula.from_dict(_require_mapping(value, "formula"))
    except RuntimeMTLError as error:
        raise RuntimeMTLExecutionError(str(error)) from error


def _coerce_trace(value: object) -> Trace | Mapping[str, Any]:
    """Return a Trace when well-formed; leave mapping for late-event detection."""

    if isinstance(value, Trace):
        return value
    mapping = _require_mapping(value, "trace")
    try:
        return Trace.from_dict(mapping)
    except RuntimeMTLError:
        # Preserve the raw mapping so the monitor can report late_events / malformed.
        return mapping


def _formula_digest(formula: Formula) -> str:
    return _digest_of(formula.to_dict())


def _trace_digest(trace: Trace | Mapping[str, Any]) -> str:
    if isinstance(trace, Trace):
        return _digest_of(trace.to_dict())
    return _digest_of(dict(trace))


def _first_interval_dict(formula: Formula) -> dict[str, Any] | None:
    if formula.interval is not None:
        return formula.interval.to_dict()
    for operand in formula.operands:
        found = _first_interval_dict(operand)
        if found is not None:
            return found
    return None


def _event_times(trace: Trace | Mapping[str, Any]) -> tuple[dict[str, int], ...]:
    if isinstance(trace, Trace):
        return tuple(event.time.to_dict() for event in trace.events)
    events = trace.get("events") if isinstance(trace, Mapping) else None
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes)):
        return ()
    times: list[dict[str, int]] = []
    for event in events:
        if not isinstance(event, Mapping):
            continue
        time = event.get("time")
        if isinstance(time, Mapping):
            times.append(
                {
                    "numerator": int(time.get("numerator", 0)),
                    "denominator": int(time.get("denominator", 1)),
                }
            )
        elif isinstance(time, int) and not isinstance(time, bool):
            times.append({"numerator": int(time), "denominator": 1})
    return tuple(times)


def _clock_dict(trace: Trace | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(trace, Trace):
        return trace.clock.to_dict()
    clock = trace.get("clock") if isinstance(trace, Mapping) else None
    if isinstance(clock, Mapping):
        return dict(clock)
    return {}


def _trace_kind_value(trace: Trace | Mapping[str, Any]) -> str:
    if isinstance(trace, Trace):
        return trace.kind.value
    kind = trace.get("kind") if isinstance(trace, Mapping) else None
    return str(kind or TraceKind.FINITE.value)


def _verdict_to_disposition(
    evaluation: MonitorEvaluation,
) -> RuntimeMTLDisposition:
    if evaluation.status is MonitorStatus.MALFORMED:
        return RuntimeMTLDisposition.MALFORMED
    if evaluation.verdict is Verdict.TRUE:
        return RuntimeMTLDisposition.SATISFIED
    if evaluation.verdict is Verdict.FALSE:
        return RuntimeMTLDisposition.VIOLATED
    return RuntimeMTLDisposition.INCONCLUSIVE


def _verdict_to_result_status(
    evaluation: MonitorEvaluation,
) -> ResultStatus:
    if evaluation.status is MonitorStatus.MALFORMED:
        return ResultStatus.MALFORMED
    if evaluation.verdict is Verdict.TRUE:
        return ResultStatus.SATISFIED
    if evaluation.verdict is Verdict.FALSE:
        return ResultStatus.VIOLATED
    # Three-valued inconclusive is an *evaluated* monitor outcome, not deferred routing.
    return ResultStatus.UNKNOWN


def _disposition_is_evaluated(disposition: RuntimeMTLDisposition) -> bool:
    return disposition in {
        RuntimeMTLDisposition.SATISFIED,
        RuntimeMTLDisposition.VIOLATED,
        RuntimeMTLDisposition.INCONCLUSIVE,
        RuntimeMTLDisposition.MALFORMED,
    }


# ---------------------------------------------------------------------------
# Semantics binding
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RuntimeMTLSemanticsBindingV2:
    """Clock, event-time, lateness, prefix, interval, monitorability, verdict.

    Interface: ``RuntimeMTLSemanticsBinding@2``.
    """

    clock_id: str
    clock_domain: str
    clock_unit: str
    clock_resolution: Mapping[str, int] | dict[str, int]
    event_times: tuple[Mapping[str, int], ...] | Sequence[Mapping[str, int]]
    trace_kind: TraceKind | str
    is_prefix: bool
    late_events: bool
    monitorability: Monitorability | str
    three_valued_verdict: Verdict | str
    logic: Logic | str
    interval: Mapping[str, Any] | None = None
    missing_observation: bool = False
    position: int = 0
    schema_version: str = RUNTIME_MTL_SEMANTICS_BINDING_SCHEMA

    interface: ClassVar[str] = RUNTIME_MTL_SEMANTICS_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "clock_id", _text(self.clock_id, "clock_id", maximum=256)
        )
        object.__setattr__(
            self, "clock_domain", _text(self.clock_domain, "clock_domain", maximum=64)
        )
        object.__setattr__(
            self, "clock_unit", _text(self.clock_unit, "clock_unit", maximum=64)
        )
        resolution = _require_mapping(self.clock_resolution, "clock_resolution")
        object.__setattr__(
            self,
            "clock_resolution",
            {
                "numerator": int(resolution.get("numerator", 1)),
                "denominator": int(resolution.get("denominator", 1)),
            },
        )
        times = tuple(
            {
                "numerator": int(_require_mapping(item, "event_time").get("numerator", 0)),
                "denominator": int(
                    _require_mapping(item, "event_time").get("denominator", 1)
                ),
            }
            for item in _require_sequence(self.event_times, "event_times")
        )
        object.__setattr__(self, "event_times", times)
        object.__setattr__(
            self, "trace_kind", _enum(self.trace_kind, TraceKind, "trace_kind")
        )
        object.__setattr__(self, "is_prefix", _optional_bool(self.is_prefix, "is_prefix"))
        object.__setattr__(
            self, "late_events", _optional_bool(self.late_events, "late_events")
        )
        object.__setattr__(
            self,
            "monitorability",
            _enum(self.monitorability, Monitorability, "monitorability"),
        )
        object.__setattr__(
            self,
            "three_valued_verdict",
            _enum(self.three_valued_verdict, Verdict, "three_valued_verdict"),
        )
        object.__setattr__(self, "logic", _enum(self.logic, Logic, "logic"))
        if self.interval is None:
            object.__setattr__(self, "interval", None)
        else:
            object.__setattr__(
                self, "interval", dict(_require_mapping(self.interval, "interval"))
            )
        object.__setattr__(
            self,
            "missing_observation",
            _optional_bool(self.missing_observation, "missing_observation"),
        )
        if (
            isinstance(self.position, bool)
            or not isinstance(self.position, int)
            or self.position < 0
        ):
            raise RuntimeMTLExecutionError("position must be a non-negative integer")
        if self.schema_version != RUNTIME_MTL_SEMANTICS_BINDING_SCHEMA:
            raise RuntimeMTLExecutionError(
                f"unsupported semantics binding schema: {self.schema_version!r}"
            )
        # Prefix flag must agree with trace kind.
        prefix_kind = self.trace_kind is TraceKind.FINITE_PREFIX  # type: ignore[comparison-overlap]
        if self.is_prefix != prefix_kind:
            raise RuntimeMTLExecutionError(
                "is_prefix must match trace_kind finite_prefix"
            )

    @classmethod
    def from_evaluation(
        cls,
        *,
        formula: Formula,
        trace: Trace | Mapping[str, Any],
        evaluation: MonitorEvaluation,
        position: int = 0,
    ) -> RuntimeMTLSemanticsBindingV2:
        clock = _clock_dict(trace)
        resolution = clock.get("resolution") or {"numerator": 1, "denominator": 1}
        if not isinstance(resolution, Mapping):
            resolution = {"numerator": 1, "denominator": 1}
        trace_kind = evaluation.trace_kind
        return cls(
            clock_id=str(clock.get("clock_id") or "clock:unknown"),
            clock_domain=str(clock.get("domain") or "discrete"),
            clock_unit=str(clock.get("unit") or "logical_tick"),
            clock_resolution={
                "numerator": int(resolution.get("numerator", 1)),
                "denominator": int(resolution.get("denominator", 1)),
            },
            event_times=_event_times(trace),
            trace_kind=trace_kind,
            is_prefix=trace_kind is TraceKind.FINITE_PREFIX
            or str(trace_kind) == TraceKind.FINITE_PREFIX.value,
            late_events=bool(evaluation.late_events),
            monitorability=evaluation.monitorability,
            three_valued_verdict=evaluation.verdict,
            logic=evaluation.logic,
            interval=_first_interval_dict(formula),
            missing_observation=bool(evaluation.missing_observation),
            position=position,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "clock_domain": self.clock_domain,
            "clock_id": self.clock_id,
            "clock_resolution": dict(self.clock_resolution),
            "clock_unit": self.clock_unit,
            "event_times": [dict(item) for item in self.event_times],
            "interface": self.interface,
            "interval": None if self.interval is None else dict(self.interval),
            "is_prefix": self.is_prefix,
            "late_events": self.late_events,
            "logic": (
                self.logic.value if isinstance(self.logic, Logic) else self.logic
            ),
            "missing_observation": self.missing_observation,
            "monitorability": (
                self.monitorability.value
                if isinstance(self.monitorability, Monitorability)
                else self.monitorability
            ),
            "position": self.position,
            "schema_version": self.schema_version,
            "three_valued_verdict": (
                self.three_valued_verdict.value
                if isinstance(self.three_valued_verdict, Verdict)
                else self.three_valued_verdict
            ),
            "trace_kind": (
                self.trace_kind.value
                if isinstance(self.trace_kind, TraceKind)
                else self.trace_kind
            ),
        }

    def content_digest(self) -> str:
        return _digest_of(self.to_dict())


# ---------------------------------------------------------------------------
# Replay receipt
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RuntimeMTLReplayReceiptV2:
    """Verdict replay against the same formula / trace / semantics.

    Interface: ``RuntimeMTLReplayReceipt@2``.

    ``replay_claimed`` is true only when the second evaluation matches the
    original verdict, status, monitorability, and semantics digest.
    """

    replay_id: str
    request_id: str
    formula_digest: str
    trace_digest: str
    semantics_digest: str
    original_verdict: Verdict | str
    replayed_verdict: Verdict | str
    original_status: MonitorStatus | str
    replayed_status: MonitorStatus | str
    original_monitorability: Monitorability | str
    replayed_monitorability: Monitorability | str
    position: int = 0
    matched: bool = False
    replay_claimed: bool = False
    diagnostics: tuple[str, ...] = ()
    schema_version: str = RUNTIME_MTL_REPLAY_RECEIPT_SCHEMA

    interface: ClassVar[str] = RUNTIME_MTL_REPLAY_RECEIPT_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "replay_id", _record_id(self.replay_id, "replay_id"))
        object.__setattr__(
            self, "request_id", _record_id(self.request_id, "request_id")
        )
        object.__setattr__(
            self, "formula_digest", _sha256_hex(self.formula_digest, "formula_digest")
        )
        object.__setattr__(
            self, "trace_digest", _sha256_hex(self.trace_digest, "trace_digest")
        )
        object.__setattr__(
            self,
            "semantics_digest",
            _sha256_hex(self.semantics_digest, "semantics_digest"),
        )
        object.__setattr__(
            self,
            "original_verdict",
            _enum(self.original_verdict, Verdict, "original_verdict"),
        )
        object.__setattr__(
            self,
            "replayed_verdict",
            _enum(self.replayed_verdict, Verdict, "replayed_verdict"),
        )
        object.__setattr__(
            self,
            "original_status",
            _enum(self.original_status, MonitorStatus, "original_status"),
        )
        object.__setattr__(
            self,
            "replayed_status",
            _enum(self.replayed_status, MonitorStatus, "replayed_status"),
        )
        object.__setattr__(
            self,
            "original_monitorability",
            _enum(
                self.original_monitorability,
                Monitorability,
                "original_monitorability",
            ),
        )
        object.__setattr__(
            self,
            "replayed_monitorability",
            _enum(
                self.replayed_monitorability,
                Monitorability,
                "replayed_monitorability",
            ),
        )
        if (
            isinstance(self.position, bool)
            or not isinstance(self.position, int)
            or self.position < 0
        ):
            raise RuntimeMTLExecutionError("position must be a non-negative integer")
        matched = _optional_bool(self.matched, "matched")
        replay_claimed = _optional_bool(self.replay_claimed, "replay_claimed")
        if replay_claimed and not matched:
            raise RuntimeMTLAuthorityError(
                "replay_claimed requires matched verdict/status/monitorability"
            )
        object.__setattr__(self, "matched", matched)
        object.__setattr__(self, "replay_claimed", replay_claimed)
        object.__setattr__(self, "diagnostics", _bound_diagnostics(self.diagnostics))
        if self.schema_version != RUNTIME_MTL_REPLAY_RECEIPT_SCHEMA:
            raise RuntimeMTLExecutionError(
                f"unsupported replay receipt schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostics": list(self.diagnostics),
            "formula_digest": self.formula_digest,
            "interface": self.interface,
            "matched": self.matched,
            "original_monitorability": (
                self.original_monitorability.value
                if isinstance(self.original_monitorability, Monitorability)
                else self.original_monitorability
            ),
            "original_status": (
                self.original_status.value
                if isinstance(self.original_status, MonitorStatus)
                else self.original_status
            ),
            "original_verdict": (
                self.original_verdict.value
                if isinstance(self.original_verdict, Verdict)
                else self.original_verdict
            ),
            "position": self.position,
            "replay_claimed": self.replay_claimed,
            "replay_id": self.replay_id,
            "replayed_monitorability": (
                self.replayed_monitorability.value
                if isinstance(self.replayed_monitorability, Monitorability)
                else self.replayed_monitorability
            ),
            "replayed_status": (
                self.replayed_status.value
                if isinstance(self.replayed_status, MonitorStatus)
                else self.replayed_status
            ),
            "replayed_verdict": (
                self.replayed_verdict.value
                if isinstance(self.replayed_verdict, Verdict)
                else self.replayed_verdict
            ),
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "semantics_digest": self.semantics_digest,
            "trace_digest": self.trace_digest,
        }


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RuntimeMTLExecutionRequestV2:
    """Typed runtime MTL monitoring request.

    Interface: ``RuntimeMTLExecutionRequest@2``.
    """

    request_id: str
    formula: Formula | Mapping[str, Any]
    trace: Trace | Mapping[str, Any]
    provider: RuntimeMTLProviderKind | str = RuntimeMTLProviderKind.RUNTIME_MTL
    position: int = 0
    mode: RuntimeMTLExecutionMode | str = RuntimeMTLExecutionMode.NATIVE_MONITOR
    source_ref_ids: tuple[str, ...] | Sequence[str] = ()
    force_prefix_monitoring: bool = False
    mock_output: Mapping[str, Any] | None = None
    fallback_output: Mapping[str, Any] | None = None
    deferred: bool = False
    available: bool = True
    confidence: float = 0.0
    fluent_text: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = RUNTIME_MTL_EXECUTION_REQUEST_SCHEMA

    interface: ClassVar[str] = RUNTIME_MTL_EXECUTION_REQUEST_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _record_id(self.request_id, "request_id")
        )
        object.__setattr__(
            self, "provider", normalize_runtime_mtl_provider(self.provider)
        )
        object.__setattr__(self, "formula", _coerce_formula(self.formula))
        # Keep raw mapping when the trace is malformed so the monitor can classify lateness.
        if isinstance(self.trace, Trace):
            object.__setattr__(self, "trace", self.trace)
        else:
            object.__setattr__(
                self, "trace", _require_mapping(self.trace, "trace")
            )
        if (
            isinstance(self.position, bool)
            or not isinstance(self.position, int)
            or self.position < 0
        ):
            raise RuntimeMTLExecutionError("position must be a non-negative integer")
        object.__setattr__(
            self, "mode", _enum(self.mode, RuntimeMTLExecutionMode, "mode")
        )
        object.__setattr__(
            self, "source_ref_ids", _source_ref_ids(self.source_ref_ids)
        )
        object.__setattr__(
            self,
            "force_prefix_monitoring",
            _optional_bool(self.force_prefix_monitoring, "force_prefix_monitoring"),
        )
        if self.mock_output is not None:
            object.__setattr__(
                self,
                "mock_output",
                dict(_require_mapping(self.mock_output, "mock_output")),
            )
        if self.fallback_output is not None:
            object.__setattr__(
                self,
                "fallback_output",
                dict(_require_mapping(self.fallback_output, "fallback_output")),
            )
        object.__setattr__(self, "deferred", _optional_bool(self.deferred, "deferred"))
        object.__setattr__(
            self, "available", _optional_bool(self.available, "available")
        )
        object.__setattr__(
            self, "confidence", _unit_interval(self.confidence, "confidence")
        )
        if self.fluent_text:
            object.__setattr__(
                self,
                "fluent_text",
                _text(self.fluent_text, "fluent_text", maximum=4096),
            )
        else:
            object.__setattr__(self, "fluent_text", "")
        metadata = _freeze_mapping(self.metadata, "metadata")
        _forbid_authority_metadata(metadata, "metadata")
        serialized = canonical_json_bytes(_thaw_mapping(metadata))
        if len(serialized) > _MAX_METADATA_BYTES:
            raise RuntimeMTLExecutionError(
                f"metadata exceeds hard limit {_MAX_METADATA_BYTES} bytes"
            )
        object.__setattr__(self, "metadata", metadata)
        if self.schema_version != RUNTIME_MTL_EXECUTION_REQUEST_SCHEMA:
            raise RuntimeMTLExecutionError(
                f"unsupported request schema: {self.schema_version!r}"
            )

    @property
    def has_mock_output(self) -> bool:
        return self.mock_output is not None

    @property
    def has_fallback_output(self) -> bool:
        return self.fallback_output is not None

    @property
    def formula_obj(self) -> Formula:
        return self.formula  # type: ignore[return-value]

    def to_dict(self) -> dict[str, Any]:
        formula = self.formula_obj
        trace = self.trace
        return {
            "available": self.available,
            "confidence": self.confidence,
            "deferred": self.deferred,
            "fallback_output": (
                None if self.fallback_output is None else dict(self.fallback_output)
            ),
            "fluent_text": self.fluent_text,
            "force_prefix_monitoring": self.force_prefix_monitoring,
            "formula": formula.to_dict(),
            "interface": self.interface,
            "metadata": _thaw_mapping(self.metadata),
            "mock_output": (
                None if self.mock_output is None else dict(self.mock_output)
            ),
            "mode": (
                self.mode.value
                if isinstance(self.mode, RuntimeMTLExecutionMode)
                else self.mode
            ),
            "position": self.position,
            "provider": (
                self.provider.value
                if isinstance(self.provider, RuntimeMTLProviderKind)
                else self.provider
            ),
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "trace": (
                trace.to_dict()
                if isinstance(trace, Trace)
                else dict(trace)  # type: ignore[arg-type]
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RuntimeMTLExecutionRequestV2:
        payload = _require_mapping(value, "RuntimeMTLExecutionRequestV2")
        allowed = {
            "request_id",
            "formula",
            "trace",
            "provider",
            "position",
            "mode",
            "source_ref_ids",
            "force_prefix_monitoring",
            "mock_output",
            "fallback_output",
            "deferred",
            "available",
            "confidence",
            "fluent_text",
            "metadata",
            "schema_version",
            "interface",
        }
        return cls(
            **{
                key: payload[key]
                for key in allowed
                if key in payload and key != "interface"
            }
        )


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RuntimeMTLEvidenceV2:
    """Pinned runtime MTL monitoring evidence.

    Interface: ``RuntimeMTLEvidence@2``.

    Monitor authority is established only by native monitor evaluation of a
    bound formula and trace.  Mock / fallback / deferred / availability /
    confidence never establish monitor, proof, satisfiability, or theorem
    authority.
    """

    evidence_id: str
    request_id: str
    request_digest: str
    provider: RuntimeMTLProviderKind | str
    disposition: RuntimeMTLDisposition | str
    mode: RuntimeMTLExecutionMode | str
    formula_digest: str
    trace_digest: str
    semantics: RuntimeMTLSemanticsBindingV2 | Mapping[str, Any]
    evaluation: MonitorEvaluation | Mapping[str, Any] | None = None
    replay: RuntimeMTLReplayReceiptV2 | Mapping[str, Any] | None = None
    source_ref_ids: tuple[str, ...] | Sequence[str] = ()
    result_authority: ResultAuthority | str = ResultAuthority.MONITOR
    result_status: ResultStatus | str = ResultStatus.UNKNOWN
    role: ToolRole | str = ToolRole.AUTHORITY
    authority_ceiling: ToolchainAuthorityCeiling | str = (
        ToolchainAuthorityCeiling.FINITE_TRACE
    )
    monitor_authority_established: bool = False
    mock_output_present: bool = False
    fallback_output_present: bool = False
    deferred_routing: bool = False
    available: bool = False
    confidence: float = 0.0
    fluent_text_present: bool = False
    authorizes_global_proof: bool = False
    diagnostics: tuple[str, ...] = ()
    content_digest: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = RUNTIME_MTL_EVIDENCE_SCHEMA

    interface: ClassVar[str] = RUNTIME_MTL_EVIDENCE_V2_INTERFACE

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
            self, "provider", normalize_runtime_mtl_provider(self.provider)
        )
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, RuntimeMTLDisposition, "disposition"),
        )
        object.__setattr__(
            self, "mode", _enum(self.mode, RuntimeMTLExecutionMode, "mode")
        )
        object.__setattr__(
            self, "formula_digest", _sha256_hex(self.formula_digest, "formula_digest")
        )
        object.__setattr__(
            self, "trace_digest", _sha256_hex(self.trace_digest, "trace_digest")
        )

        if isinstance(self.semantics, RuntimeMTLSemanticsBindingV2):
            semantics = self.semantics
        else:
            semantics = RuntimeMTLSemanticsBindingV2(
                **{
                    key: value
                    for key, value in dict(
                        _require_mapping(self.semantics, "semantics")
                    ).items()
                    if key
                    in {
                        "clock_id",
                        "clock_domain",
                        "clock_unit",
                        "clock_resolution",
                        "event_times",
                        "trace_kind",
                        "is_prefix",
                        "late_events",
                        "monitorability",
                        "three_valued_verdict",
                        "logic",
                        "interval",
                        "missing_observation",
                        "position",
                        "schema_version",
                    }
                }
            )
        object.__setattr__(self, "semantics", semantics)

        if self.evaluation is None:
            object.__setattr__(self, "evaluation", None)
        elif isinstance(self.evaluation, MonitorEvaluation):
            object.__setattr__(self, "evaluation", self.evaluation)
        else:
            object.__setattr__(
                self,
                "evaluation",
                MonitorEvaluation.from_dict(
                    _require_mapping(self.evaluation, "evaluation")
                ),
            )

        if self.replay is None:
            object.__setattr__(self, "replay", None)
        elif isinstance(self.replay, RuntimeMTLReplayReceiptV2):
            object.__setattr__(self, "replay", self.replay)
        else:
            object.__setattr__(
                self,
                "replay",
                RuntimeMTLReplayReceiptV2(
                    **{
                        key: value
                        for key, value in dict(
                            _require_mapping(self.replay, "replay")
                        ).items()
                        if key
                        in {
                            "replay_id",
                            "request_id",
                            "formula_digest",
                            "trace_digest",
                            "semantics_digest",
                            "original_verdict",
                            "replayed_verdict",
                            "original_status",
                            "replayed_status",
                            "original_monitorability",
                            "replayed_monitorability",
                            "position",
                            "matched",
                            "replay_claimed",
                            "diagnostics",
                            "schema_version",
                        }
                    }
                ),
            )

        object.__setattr__(
            self, "source_ref_ids", _source_ref_ids(self.source_ref_ids)
        )

        result_authority = (
            self.result_authority
            if isinstance(self.result_authority, ResultAuthority)
            else ResultAuthority(str(self.result_authority))
        )
        if result_authority is not ResultAuthority.MONITOR:
            raise RuntimeMTLAuthorityError(
                "RuntimeMTLEvidence@2 result_authority must be monitor; "
                f"got {result_authority!r}"
            )
        object.__setattr__(self, "result_authority", ResultAuthority.MONITOR)

        result_status = (
            self.result_status
            if isinstance(self.result_status, ResultStatus)
            else ResultStatus(str(self.result_status))
        )
        if result_status in {ResultStatus.PROVED, ResultStatus.DISPROVED}:
            raise RuntimeMTLAuthorityError(
                "RuntimeMTLEvidence@2 cannot claim theorem result statuses"
            )
        object.__setattr__(self, "result_status", result_status)

        role = self.role if isinstance(self.role, ToolRole) else ToolRole(str(self.role))
        if role not in {ToolRole.AUTHORITY, ToolRole.SHADOW}:
            raise RuntimeMTLAuthorityError(
                f"RuntimeMTLEvidence@2 role must be authority or shadow; got {role!r}"
            )
        object.__setattr__(self, "role", role)

        ceiling = (
            self.authority_ceiling
            if isinstance(self.authority_ceiling, ToolchainAuthorityCeiling)
            else ToolchainAuthorityCeiling(str(self.authority_ceiling))
        )
        if ceiling is not ToolchainAuthorityCeiling.FINITE_TRACE:
            raise RuntimeMTLAuthorityError(
                "RuntimeMTLEvidence@2 authority_ceiling must be finite_trace"
            )
        object.__setattr__(self, "authority_ceiling", ceiling)

        for flag_name in (
            "monitor_authority_established",
            "mock_output_present",
            "fallback_output_present",
            "deferred_routing",
            "available",
            "fluent_text_present",
            "authorizes_global_proof",
        ):
            object.__setattr__(
                self,
                flag_name,
                _optional_bool(getattr(self, flag_name), flag_name),
            )

        if self.authorizes_global_proof:
            raise RuntimeMTLAuthorityError(
                "runtime MTL evidence never authorizes global proof"
            )

        object.__setattr__(
            self, "confidence", _unit_interval(self.confidence, "confidence")
        )
        object.__setattr__(self, "diagnostics", _bound_diagnostics(self.diagnostics))

        # Fail closed: mock / fallback / deferred never establish monitor authority.
        mode = self.mode  # type: ignore[assignment]
        if (
            self.mock_output_present
            or self.fallback_output_present
            or self.deferred_routing
            or mode
            in {
                RuntimeMTLExecutionMode.MOCK,
                RuntimeMTLExecutionMode.FALLBACK,
                RuntimeMTLExecutionMode.DEFERRED,
                RuntimeMTLExecutionMode.UNAVAILABLE,
            }
        ):
            if self.monitor_authority_established:
                raise RuntimeMTLAuthorityError(
                    "mock, fallback, deferred, or unavailable modes cannot "
                    "establish monitor authority"
                )
            object.__setattr__(self, "monitor_authority_established", False)

        if mode is RuntimeMTLExecutionMode.EXTERNAL_SHADOW and self.monitor_authority_established:
            raise RuntimeMTLAuthorityError(
                "external shadow alone cannot establish monitor authority"
            )

        # Evaluated monitor authority requires a concrete evaluation under native mode.
        if self.monitor_authority_established:
            if mode is not RuntimeMTLExecutionMode.NATIVE_MONITOR:
                raise RuntimeMTLAuthorityError(
                    "monitor authority requires native_monitor mode"
                )
            if self.evaluation is None:
                raise RuntimeMTLAuthorityError(
                    "monitor authority requires a concrete MonitorEvaluation"
                )
            evaluation = self.evaluation  # type: ignore[assignment]
            if evaluation.authority is not MonitorAuthority.MONITOR:
                raise RuntimeMTLAuthorityError(
                    "evaluation authority must remain monitor"
                )
            if evaluation.authorizes_global_proof:
                raise RuntimeMTLAuthorityError(
                    "evaluation must not authorize global proof"
                )

        metadata = _freeze_mapping(self.metadata, "metadata")
        _forbid_authority_metadata(metadata, "metadata")
        object.__setattr__(self, "metadata", metadata)

        if self.schema_version != RUNTIME_MTL_EVIDENCE_SCHEMA:
            raise RuntimeMTLExecutionError(
                f"unsupported RuntimeMTLEvidence@2 schema: {self.schema_version!r}"
            )

        if not self.content_digest:
            object.__setattr__(
                self,
                "content_digest",
                _digest_of(
                    {
                        "disposition": (
                            self.disposition.value
                            if isinstance(self.disposition, RuntimeMTLDisposition)
                            else self.disposition
                        ),
                        "formula_digest": self.formula_digest,
                        "mode": (
                            self.mode.value
                            if isinstance(self.mode, RuntimeMTLExecutionMode)
                            else self.mode
                        ),
                        "monitor_authority_established": (
                            self.monitor_authority_established
                        ),
                        "provider": (
                            self.provider.value
                            if isinstance(self.provider, RuntimeMTLProviderKind)
                            else self.provider
                        ),
                        "request_digest": self.request_digest,
                        "request_id": self.request_id,
                        "result_status": (
                            self.result_status.value
                            if isinstance(self.result_status, ResultStatus)
                            else self.result_status
                        ),
                        "semantics": self.semantics.to_dict(),  # type: ignore[union-attr]
                        "trace_digest": self.trace_digest,
                    }
                ),
            )
        else:
            object.__setattr__(
                self,
                "content_digest",
                _sha256_hex(self.content_digest, "content_digest"),
            )

    # --- authority queries (fail closed) -----------------------------------

    @property
    def is_proved(self) -> bool:
        return False

    @property
    def is_theorem_authority(self) -> bool:
        return False

    @property
    def monitor_established(self) -> bool:
        return self.monitor_authority_established

    @property
    def proof_established(self) -> bool:
        return False

    @property
    def satisfiability_established(self) -> bool:
        return False

    @property
    def theorem_established(self) -> bool:
        return False

    @property
    def is_evaluated(self) -> bool:
        return _disposition_is_evaluated(
            self.disposition  # type: ignore[arg-type]
        ) and self.mode is RuntimeMTLExecutionMode.NATIVE_MONITOR

    @property
    def is_deferred_placeholder(self) -> bool:
        """True only for rejected deferred routing (never an evaluated outcome)."""

        return (
            self.disposition is RuntimeMTLDisposition.DEFERRED_REJECTED
            or self.deferred_routing
            or self.mode is RuntimeMTLExecutionMode.DEFERRED
        )

    def bindings_complete(self) -> bool:
        semantics = self.semantics  # type: ignore[assignment]
        return bool(
            self.formula_digest
            and self.trace_digest
            and semantics.clock_id
            and semantics.clock_unit
            and semantics.three_valued_verdict is not None
            and semantics.monitorability is not None
        )

    def claim_established(self, claim: RuntimeMTLClaimKind | str) -> bool:
        kind = (
            claim
            if isinstance(claim, RuntimeMTLClaimKind)
            else RuntimeMTLClaimKind(str(claim))
        )
        if kind is RuntimeMTLClaimKind.MONITOR:
            return self.monitor_authority_established
        return False

    def non_authoritative_claim(
        self, claim: RuntimeMTLClaimKind | str
    ) -> bool:
        return non_authoritative_signal_establishes(
            claim,
            mock_output={} if self.mock_output_present else None,
            fallback_output={} if self.fallback_output_present else None,
            deferred=self.deferred_routing,
            available=self.available,
            confidence=self.confidence,
            fluent_text="present" if self.fluent_text_present else None,
        )

    def to_dict(self) -> dict[str, Any]:
        evaluation = self.evaluation
        replay = self.replay
        return {
            "authority_ceiling": (
                self.authority_ceiling.value
                if isinstance(self.authority_ceiling, ToolchainAuthorityCeiling)
                else self.authority_ceiling
            ),
            "authorizes_global_proof": False,
            "available": self.available,
            "bindings_complete": self.bindings_complete(),
            "claim_monitor": self.monitor_authority_established,
            "claim_proof": False,
            "claim_satisfiability": False,
            "claim_theorem": False,
            "confidence": self.confidence,
            "content_digest": self.content_digest,
            "deferred_routing": self.deferred_routing,
            "diagnostics": list(self.diagnostics),
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, RuntimeMTLDisposition)
                else self.disposition
            ),
            "evaluation": (
                None
                if evaluation is None
                else evaluation.to_dict()  # type: ignore[union-attr]
            ),
            "evidence_id": self.evidence_id,
            "fallback_output_present": self.fallback_output_present,
            "fluent_text_present": self.fluent_text_present,
            "formula_digest": self.formula_digest,
            "interface": self.interface,
            "is_deferred_placeholder": self.is_deferred_placeholder,
            "is_evaluated": self.is_evaluated,
            "is_proved": False,
            "is_theorem_authority": False,
            "metadata": _thaw_mapping(self.metadata),
            "mode": (
                self.mode.value
                if isinstance(self.mode, RuntimeMTLExecutionMode)
                else self.mode
            ),
            "mock_output_present": self.mock_output_present,
            "monitor_authority_established": self.monitor_authority_established,
            "monitor_established": self.monitor_authority_established,
            "monitor_interface": RUNTIME_MTL_MONITOR_INTERFACE,
            "proof_established": False,
            "provider": (
                self.provider.value
                if isinstance(self.provider, RuntimeMTLProviderKind)
                else self.provider
            ),
            "replay": (
                None if replay is None else replay.to_dict()  # type: ignore[union-attr]
            ),
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
            "satisfiability_established": False,
            "schema_version": self.schema_version,
            "semantics": self.semantics.to_dict(),  # type: ignore[union-attr]
            "source_ref_ids": list(self.source_ref_ids),
            "theorem_established": False,
            "trace_digest": self.trace_digest,
        }


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RuntimeMTLExecutionResultV2:
    """Execution result wrapping request + RuntimeMTLEvidence@2."""

    request: RuntimeMTLExecutionRequestV2
    evidence: RuntimeMTLEvidenceV2
    monitor_result: MonitorResult | None = None
    schema_version: str = RUNTIME_MTL_EXECUTION_RESULT_SCHEMA

    interface: ClassVar[str] = RUNTIME_MTL_EXECUTION_RESULT_V2_INTERFACE

    def __post_init__(self) -> None:
        if not isinstance(self.request, RuntimeMTLExecutionRequestV2):
            raise RuntimeMTLExecutionError(
                "request must be RuntimeMTLExecutionRequestV2"
            )
        if not isinstance(self.evidence, RuntimeMTLEvidenceV2):
            raise RuntimeMTLExecutionError("evidence must be RuntimeMTLEvidenceV2")
        if self.request.request_id != self.evidence.request_id:
            raise RuntimeMTLExecutionError(
                "result request_id must match evidence.request_id"
            )
        if self.schema_version != RUNTIME_MTL_EXECUTION_RESULT_SCHEMA:
            raise RuntimeMTLExecutionError(
                f"unsupported result schema: {self.schema_version!r}"
            )

    @property
    def disposition(self) -> RuntimeMTLDisposition:
        return self.evidence.disposition  # type: ignore[return-value]

    @property
    def monitor_established(self) -> bool:
        return self.evidence.monitor_authority_established

    @property
    def is_proved(self) -> bool:
        return False

    @property
    def is_evaluated(self) -> bool:
        return self.evidence.is_evaluated

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence": self.evidence.to_dict(),
            "interface": self.interface,
            "monitor_result": (
                None
                if self.monitor_result is None
                else self.monitor_result.to_dict()
            ),
            "request": self.request.to_dict(),
            "schema_version": self.schema_version,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class RuntimeMTLExecutionEngineV2:
    """Execute runtime MTL monitoring with real evaluation and verdict replay.

    Interface owner: ``RuntimeMTLEvidence@2``.

    Invokes the portable ``RuntimeMTLMonitor@1`` evaluator.  Never returns
    deferred UNKNOWN as a silent substitute for evaluation when a formula and
    trace are present.  Deferred routing is rejected as an explicit
    unsupported/unavailable-class disposition.
    """

    INTERFACE: ClassVar[str] = RUNTIME_MTL_EVIDENCE_V2_INTERFACE
    interface: ClassVar[str] = RUNTIME_MTL_EVIDENCE_V2_INTERFACE
    VERSION: ClassVar[str] = RUNTIME_MTL_EXECUTION_V2_MODULE_VERSION
    TASK_ID: ClassVar[str] = RUNTIME_MTL_EXECUTION_V2_TASK_ID
    GOAL_ID: ClassVar[str] = RUNTIME_MTL_EXECUTION_V2_GOAL_ID

    def execute(
        self,
        request: RuntimeMTLExecutionRequestV2 | Mapping[str, Any],
    ) -> RuntimeMTLExecutionResultV2:
        """Execute one typed runtime MTL monitoring request."""

        req = (
            request
            if isinstance(request, RuntimeMTLExecutionRequestV2)
            else RuntimeMTLExecutionRequestV2.from_dict(request)
        )
        request_digest = _digest_of(req.to_dict())
        formula = req.formula_obj
        formula_digest = _formula_digest(formula)
        trace_digest = _trace_digest(req.trace)  # type: ignore[arg-type]

        # Explicit deferred routing is never evaluation — reject closed.
        if req.deferred or req.mode is RuntimeMTLExecutionMode.DEFERRED:
            return self._reject_non_evaluation(
                req,
                request_digest=request_digest,
                formula_digest=formula_digest,
                trace_digest=trace_digest,
                disposition=RuntimeMTLDisposition.DEFERRED_REJECTED,
                mode=RuntimeMTLExecutionMode.DEFERRED,
                result_status=ResultStatus.UNSUPPORTED,
                diagnostics=(
                    "deferred_routing_cannot_substitute_for_monitor_evaluation",
                    "deferred_unknown_is_only_explicit_unsupported_or_unavailable",
                ),
                deferred_routing=True,
            )

        # Mock path: never establishes monitor authority.
        if req.has_mock_output or req.mode is RuntimeMTLExecutionMode.MOCK:
            return self._reject_non_evaluation(
                req,
                request_digest=request_digest,
                formula_digest=formula_digest,
                trace_digest=trace_digest,
                disposition=RuntimeMTLDisposition.MOCK_REJECTED,
                mode=RuntimeMTLExecutionMode.MOCK,
                result_status=ResultStatus.UNKNOWN,
                diagnostics=(
                    "mock_output_cannot_establish_monitor",
                    "mock_output_cannot_establish_proof",
                    "mock_output_cannot_establish_satisfiability",
                    "mock_output_cannot_establish_theorem",
                ),
                mock_output_present=True,
            )

        # Fallback path: never establishes monitor authority.
        if req.has_fallback_output or req.mode is RuntimeMTLExecutionMode.FALLBACK:
            return self._reject_non_evaluation(
                req,
                request_digest=request_digest,
                formula_digest=formula_digest,
                trace_digest=trace_digest,
                disposition=RuntimeMTLDisposition.FALLBACK_REJECTED,
                mode=RuntimeMTLExecutionMode.FALLBACK,
                result_status=ResultStatus.UNKNOWN,
                diagnostics=(
                    "fallback_output_cannot_establish_monitor",
                    "fallback_output_cannot_establish_proof",
                ),
                fallback_output_present=True,
            )

        # Explicit unavailability (e.g. external tool missing).
        if (
            req.mode is RuntimeMTLExecutionMode.UNAVAILABLE
            or (
                req.provider is RuntimeMTLProviderKind.RUNTIME_MTL_EXTERNAL
                and not req.available
            )
        ):
            return self._reject_non_evaluation(
                req,
                request_digest=request_digest,
                formula_digest=formula_digest,
                trace_digest=trace_digest,
                disposition=RuntimeMTLDisposition.UNAVAILABLE,
                mode=RuntimeMTLExecutionMode.UNAVAILABLE,
                result_status=ResultStatus.UNAVAILABLE,
                diagnostics=(
                    "runtime_mtl_provider_unavailable",
                    "unavailable_is_explicit_non_evaluation_outcome",
                ),
            )

        # External provider without hermetic certification remains unavailable
        # rather than silently deferred; in-process path always evaluates.
        if (
            req.provider is RuntimeMTLProviderKind.RUNTIME_MTL_EXTERNAL
            and req.mode is not RuntimeMTLExecutionMode.NATIVE_MONITOR
        ):
            return self._reject_non_evaluation(
                req,
                request_digest=request_digest,
                formula_digest=formula_digest,
                trace_digest=trace_digest,
                disposition=RuntimeMTLDisposition.UNAVAILABLE,
                mode=RuntimeMTLExecutionMode.UNAVAILABLE,
                result_status=ResultStatus.UNAVAILABLE,
                diagnostics=(
                    "runtime_mtl_external_requires_native_or_certified_path",
                    "unavailable_is_explicit_non_evaluation_outcome",
                ),
            )

        return self._evaluate_native(
            req,
            request_digest=request_digest,
            formula_digest=formula_digest,
            trace_digest=trace_digest,
        )

    def execute_case(
        self,
        case: Mapping[str, Any],
        *,
        request_id: str | None = None,
        provider: RuntimeMTLProviderKind | str = RuntimeMTLProviderKind.RUNTIME_MTL,
    ) -> RuntimeMTLExecutionResultV2:
        """Execute a portable golden / parity case envelope."""

        case = _require_mapping(case, "case")
        case_id = str(case.get("case_id") or "case")
        return self.execute(
            RuntimeMTLExecutionRequestV2(
                request_id=request_id or f"req:runtime-mtl:{case_id}",
                formula=_require_mapping(case.get("formula"), "formula"),
                trace=_require_mapping(case.get("trace"), "trace"),
                provider=provider,
                position=int(case.get("position", 0)),
                source_ref_ids=(f"source:runtime-mtl-golden:{case_id}",),
            )
        )

    def execute_golden_fixtures(
        self,
        *,
        provider: RuntimeMTLProviderKind | str = RuntimeMTLProviderKind.RUNTIME_MTL,
    ) -> tuple[RuntimeMTLExecutionResultV2, ...]:
        """Run the portable golden fixture set through real monitoring + replay."""

        return tuple(
            self.execute_case(case, provider=provider) for case in golden_fixtures()
        )

    def replay(
        self,
        result: RuntimeMTLExecutionResultV2,
    ) -> RuntimeMTLReplayReceiptV2:
        """Re-evaluate the same formula/trace/position and compare verdicts."""

        if not isinstance(result, RuntimeMTLExecutionResultV2):
            raise RuntimeMTLExecutionError(
                "replay requires RuntimeMTLExecutionResultV2"
            )
        if not result.is_evaluated or result.evidence.evaluation is None:
            raise RuntimeMTLExecutionError(
                "only evaluated monitor results can be replayed"
            )
        req = result.request
        formula = req.formula_obj
        original = result.evidence.evaluation  # type: ignore[assignment]
        replayed = self._invoke_monitor(
            formula,
            req.trace,  # type: ignore[arg-type]
            position=req.position,
            force_prefix=req.force_prefix_monitoring,
        )
        semantics = result.evidence.semantics  # type: ignore[assignment]
        matched = (
            replayed.verdict is original.verdict
            and replayed.status is original.status
            and replayed.monitorability is original.monitorability
            and replayed.logic is original.logic
            and bool(replayed.late_events) == bool(original.late_events)
            and bool(replayed.missing_observation)
            == bool(original.missing_observation)
            and replayed.authorizes_global_proof is False
            and original.authorizes_global_proof is False
        )
        diagnostics: list[str] = []
        if not matched:
            diagnostics.append("verdict_or_semantics_mismatch_on_replay")
        return RuntimeMTLReplayReceiptV2(
            replay_id=f"replay:runtime-mtl:{req.request_id}",
            request_id=req.request_id,
            formula_digest=result.evidence.formula_digest,
            trace_digest=result.evidence.trace_digest,
            semantics_digest=semantics.content_digest(),
            original_verdict=original.verdict,
            replayed_verdict=replayed.verdict,
            original_status=original.status,
            replayed_status=replayed.status,
            original_monitorability=original.monitorability,
            replayed_monitorability=replayed.monitorability,
            position=req.position,
            matched=matched,
            replay_claimed=matched,
            diagnostics=tuple(diagnostics),
        )

    # --- internal ----------------------------------------------------------

    def _evaluate_native(
        self,
        req: RuntimeMTLExecutionRequestV2,
        *,
        request_digest: str,
        formula_digest: str,
        trace_digest: str,
    ) -> RuntimeMTLExecutionResultV2:
        formula = req.formula_obj
        evaluation = self._invoke_monitor(
            formula,
            req.trace,  # type: ignore[arg-type]
            position=req.position,
            force_prefix=req.force_prefix_monitoring,
        )
        semantics = RuntimeMTLSemanticsBindingV2.from_evaluation(
            formula=formula,
            trace=req.trace,  # type: ignore[arg-type]
            evaluation=evaluation,
            position=req.position,
        )
        disposition = _verdict_to_disposition(evaluation)
        result_status = _verdict_to_result_status(evaluation)
        # Native evaluation always establishes monitor authority for conclusive
        # *and* inconclusive three-valued outcomes (including malformed traces
        # that the monitor classified).  It never establishes proof.
        monitor_authority = True
        diagnostics: list[str] = []
        if evaluation.status is MonitorStatus.MALFORMED:
            diagnostics.append(f"malformed:{evaluation.reason}")
        if evaluation.late_events:
            diagnostics.append("late_events_detected")
        if evaluation.missing_observation:
            diagnostics.append("missing_observation")
        if evaluation.verdict is Verdict.INCONCLUSIVE:
            diagnostics.append("three_valued_inconclusive")
        diagnostics.append("native_monitor_invoked")
        diagnostics.append("deferred_routing_not_used")

        evidence = RuntimeMTLEvidenceV2(
            evidence_id=(
                f"ev:runtime-mtl:{req.provider.value}:"  # type: ignore[union-attr]
                f"{req.request_id}:{disposition.value}"
            ),
            request_id=req.request_id,
            request_digest=request_digest,
            provider=req.provider,  # type: ignore[arg-type]
            disposition=disposition,
            mode=RuntimeMTLExecutionMode.NATIVE_MONITOR,
            formula_digest=formula_digest,
            trace_digest=trace_digest,
            semantics=semantics,
            evaluation=evaluation,
            source_ref_ids=req.source_ref_ids,
            result_status=result_status,
            monitor_authority_established=monitor_authority,
            mock_output_present=False,
            fallback_output_present=False,
            deferred_routing=False,
            available=req.available,
            confidence=req.confidence,
            fluent_text_present=bool(req.fluent_text),
            authorizes_global_proof=False,
            diagnostics=tuple(diagnostics),
        )

        # Immediate same-trace replay binding.
        replay = self._build_replay(
            req=req,
            formula_digest=formula_digest,
            trace_digest=trace_digest,
            semantics=semantics,
            original=evaluation,
        )
        if not replay.matched:
            # Fail closed: evaluation that does not replay is a mismatch.
            evidence = RuntimeMTLEvidenceV2(
                evidence_id=f"ev:runtime-mtl:{req.provider.value}:{req.request_id}:replay_mismatch",  # type: ignore[union-attr]
                request_id=req.request_id,
                request_digest=request_digest,
                provider=req.provider,  # type: ignore[arg-type]
                disposition=RuntimeMTLDisposition.REPLAY_MISMATCH,
                mode=RuntimeMTLExecutionMode.NATIVE_MONITOR,
                formula_digest=formula_digest,
                trace_digest=trace_digest,
                semantics=semantics,
                evaluation=evaluation,
                replay=replay,
                source_ref_ids=req.source_ref_ids,
                result_status=ResultStatus.ERROR,
                monitor_authority_established=False,
                available=req.available,
                confidence=req.confidence,
                fluent_text_present=bool(req.fluent_text),
                diagnostics=(
                    *diagnostics,
                    "verdict_failed_same_trace_replay",
                ),
            )
        else:
            evidence = RuntimeMTLEvidenceV2(
                evidence_id=evidence.evidence_id,
                request_id=evidence.request_id,
                request_digest=evidence.request_digest,
                provider=evidence.provider,  # type: ignore[arg-type]
                disposition=evidence.disposition,  # type: ignore[arg-type]
                mode=evidence.mode,  # type: ignore[arg-type]
                formula_digest=evidence.formula_digest,
                trace_digest=evidence.trace_digest,
                semantics=semantics,
                evaluation=evaluation,
                replay=replay,
                source_ref_ids=evidence.source_ref_ids,
                result_status=evidence.result_status,  # type: ignore[arg-type]
                monitor_authority_established=True,
                available=req.available,
                confidence=req.confidence,
                fluent_text_present=bool(req.fluent_text),
                diagnostics=evidence.diagnostics,
            )

        final_status = (
            ResultStatus.ERROR
            if evidence.disposition is RuntimeMTLDisposition.REPLAY_MISMATCH
            else result_status
        )
        monitor_result = MonitorResult(
            result_id=f"result:runtime-mtl:{req.request_id}",
            backend_id=provider_backend_id(
                req.provider  # type: ignore[arg-type]
            ),
            backend_version=RUNTIME_MTL_EXECUTION_V2_MODULE_VERSION,
            authority=ResultAuthority.MONITOR,
            status=final_status,
            assumptions=(),
            bounds=ExecutionBounds(timeout_ms=5_000, max_steps=100_000),
            translation_ceiling=EvidenceAuthority.BOUNDED,
            usage=ResourceUsage(),
            witness=FrozenMap(
                {
                    "evaluation": evaluation.to_dict(),
                    "formula_digest": formula_digest,
                    "trace_digest": trace_digest,
                    "semantics_digest": semantics.content_digest(),
                }
            ),
            diagnostics=evidence.diagnostics,
            reason=evaluation.reason,
        )
        return RuntimeMTLExecutionResultV2(
            request=req,
            evidence=evidence,
            monitor_result=monitor_result,
        )

    def _build_replay(
        self,
        *,
        req: RuntimeMTLExecutionRequestV2,
        formula_digest: str,
        trace_digest: str,
        semantics: RuntimeMTLSemanticsBindingV2,
        original: MonitorEvaluation,
    ) -> RuntimeMTLReplayReceiptV2:
        replayed = self._invoke_monitor(
            req.formula_obj,
            req.trace,  # type: ignore[arg-type]
            position=req.position,
            force_prefix=req.force_prefix_monitoring,
        )
        matched = (
            replayed.verdict is original.verdict
            and replayed.status is original.status
            and replayed.monitorability is original.monitorability
            and replayed.logic is original.logic
            and bool(replayed.late_events) == bool(original.late_events)
            and bool(replayed.missing_observation)
            == bool(original.missing_observation)
            and not replayed.authorizes_global_proof
            and not original.authorizes_global_proof
        )
        return RuntimeMTLReplayReceiptV2(
            replay_id=f"replay:runtime-mtl:{req.request_id}",
            request_id=req.request_id,
            formula_digest=formula_digest,
            trace_digest=trace_digest,
            semantics_digest=semantics.content_digest(),
            original_verdict=original.verdict,
            replayed_verdict=replayed.verdict,
            original_status=original.status,
            replayed_status=replayed.status,
            original_monitorability=original.monitorability,
            replayed_monitorability=replayed.monitorability,
            position=req.position,
            matched=matched,
            replay_claimed=matched,
            diagnostics=(
                ()
                if matched
                else ("verdict_or_semantics_mismatch_on_replay",)
            ),
        )

    def _invoke_monitor(
        self,
        formula: Formula,
        trace: Trace | Mapping[str, Any],
        *,
        position: int,
        force_prefix: bool,
    ) -> MonitorEvaluation:
        monitor = RuntimeMTLMonitor(formula=formula, position=position)
        if force_prefix:
            return monitor.monitor(trace)
        return monitor.evaluate(trace)

    def _reject_non_evaluation(
        self,
        req: RuntimeMTLExecutionRequestV2,
        *,
        request_digest: str,
        formula_digest: str,
        trace_digest: str,
        disposition: RuntimeMTLDisposition,
        mode: RuntimeMTLExecutionMode,
        result_status: ResultStatus,
        diagnostics: Sequence[str],
        mock_output_present: bool = False,
        fallback_output_present: bool = False,
        deferred_routing: bool = False,
    ) -> RuntimeMTLExecutionResultV2:
        formula = req.formula_obj
        # Bind semantics from request structure even when not evaluating so
        # clock / event-time / prefix remain explicit.
        try:
            monitorability = classify_monitorability(formula)
        except Exception:
            monitorability = Monitorability.NOT_FINITE_MONITORABLE
        clock = _clock_dict(req.trace)  # type: ignore[arg-type]
        resolution = clock.get("resolution") or {"numerator": 1, "denominator": 1}
        if not isinstance(resolution, Mapping):
            resolution = {"numerator": 1, "denominator": 1}
        trace_kind_raw = _trace_kind_value(req.trace)  # type: ignore[arg-type]
        try:
            trace_kind = TraceKind(trace_kind_raw)
        except ValueError:
            trace_kind = TraceKind.FINITE
        semantics = RuntimeMTLSemanticsBindingV2(
            clock_id=str(clock.get("clock_id") or "clock:unknown"),
            clock_domain=str(clock.get("domain") or "discrete"),
            clock_unit=str(clock.get("unit") or "logical_tick"),
            clock_resolution={
                "numerator": int(resolution.get("numerator", 1)),
                "denominator": int(resolution.get("denominator", 1)),
            },
            event_times=_event_times(req.trace),  # type: ignore[arg-type]
            trace_kind=trace_kind,
            is_prefix=trace_kind is TraceKind.FINITE_PREFIX,
            late_events=False,
            monitorability=monitorability,
            three_valued_verdict=Verdict.INCONCLUSIVE,
            logic=formula.logic,
            interval=_first_interval_dict(formula),
            missing_observation=False,
            position=req.position,
        )
        evidence = RuntimeMTLEvidenceV2(
            evidence_id=(
                f"ev:runtime-mtl:{req.provider.value}:"  # type: ignore[union-attr]
                f"{req.request_id}:{disposition.value}"
            ),
            request_id=req.request_id,
            request_digest=request_digest,
            provider=req.provider,  # type: ignore[arg-type]
            disposition=disposition,
            mode=mode,
            formula_digest=formula_digest,
            trace_digest=trace_digest,
            semantics=semantics,
            evaluation=None,
            source_ref_ids=req.source_ref_ids,
            result_status=result_status,
            monitor_authority_established=False,
            mock_output_present=mock_output_present or req.has_mock_output,
            fallback_output_present=fallback_output_present or req.has_fallback_output,
            deferred_routing=deferred_routing or req.deferred,
            available=req.available,
            confidence=req.confidence,
            fluent_text_present=bool(req.fluent_text),
            authorizes_global_proof=False,
            diagnostics=tuple(diagnostics),
        )
        return RuntimeMTLExecutionResultV2(request=req, evidence=evidence)


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


def execute_runtime_mtl(
    formula: Formula | Mapping[str, Any],
    trace: Trace | Mapping[str, Any],
    *,
    request_id: str = "req:runtime-mtl:1",
    provider: RuntimeMTLProviderKind | str = RuntimeMTLProviderKind.RUNTIME_MTL,
    position: int = 0,
    **kwargs: Any,
) -> RuntimeMTLExecutionResultV2:
    """Execute one formula/trace pair through RuntimeMTLEvidence@2."""

    request = RuntimeMTLExecutionRequestV2(
        request_id=request_id,
        formula=formula,
        trace=trace,
        provider=provider,
        position=position,
        **kwargs,
    )
    return RuntimeMTLExecutionEngineV2().execute(request)


def monitor_and_replay(
    formula: Formula | Mapping[str, Any],
    trace: Trace | Mapping[str, Any],
    *,
    request_id: str = "req:runtime-mtl:replay:1",
    position: int = 0,
) -> tuple[RuntimeMTLExecutionResultV2, RuntimeMTLReplayReceiptV2]:
    """Evaluate then explicitly re-replay; both must agree."""

    engine = RuntimeMTLExecutionEngineV2()
    result = engine.execute(
        RuntimeMTLExecutionRequestV2(
            request_id=request_id,
            formula=formula,
            trace=trace,
            position=position,
        )
    )
    replay = engine.replay(result)
    return result, replay


__all__ = [
    "RUNTIME_MTL_EVIDENCE_V2_INTERFACE",
    "RUNTIME_MTL_EXECUTION_REQUEST_V2_INTERFACE",
    "RUNTIME_MTL_EXECUTION_RESULT_V2_INTERFACE",
    "RUNTIME_MTL_EXECUTION_V2_GOAL_ID",
    "RUNTIME_MTL_EXECUTION_V2_MODULE_VERSION",
    "RUNTIME_MTL_EXECUTION_V2_TASK_ID",
    "RUNTIME_MTL_REPLAY_RECEIPT_V2_INTERFACE",
    "RUNTIME_MTL_SEMANTICS_BINDING_V2_INTERFACE",
    "RuntimeMTLAuthorityError",
    "RuntimeMTLClaimKind",
    "RuntimeMTLDisposition",
    "RuntimeMTLEvidenceV2",
    "RuntimeMTLExecutionEngineV2",
    "RuntimeMTLExecutionError",
    "RuntimeMTLExecutionMode",
    "RuntimeMTLExecutionRequestV2",
    "RuntimeMTLExecutionResultV2",
    "RuntimeMTLProviderKind",
    "RuntimeMTLReplayReceiptV2",
    "RuntimeMTLSemanticsBindingV2",
    "deferred_or_mock_establishes_monitor",
    "execute_runtime_mtl",
    "monitor_and_replay",
    "non_authoritative_signal_establishes",
    "normalize_runtime_mtl_provider",
    "provider_backend_id",
    "provider_logic_identity",
]
