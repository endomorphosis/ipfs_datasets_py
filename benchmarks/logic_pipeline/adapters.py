"""Versioned, side-effect-free adapters for the benchmark logic pipeline.

The adapters in this module are intentionally thin.  They accept an injected
callable (or no callable when a capability is unavailable), execute it only
when the caller explicitly asks them to, and turn the result into a strict
versioned :class:`~benchmarks.logic_pipeline.contracts.StageRecord`.  No
optional package is imported here and no production router is configured or
modified.

Later stage-specific integrations can provide handlers for the six registered
stages without changing the record format or the baseline route.  A handler
receives :class:`StageRequest` and may return :class:`StageOutput` or a JSON
value.  Raw model output belongs in a bounded stage payload; it never becomes
proof authority merely by passing through an adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import importlib
import json
import re
import time
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping, Sequence

from .contracts import (
    BASELINE_VARIANT,
    CacheMode,
    CaseResultRecord,
    DEFAULT_PROTOCOL_SHA256,
    FailureCode,
    HSSLEV0306C18,
    ProtocolContractError,
    ResourceLane,
    Split,
    StageName,
    StageProvenance,
    StageRecord,
    StageStatus,
    TelemetryRecord,
    canonical_json,
)


ADAPTER_VERSION: Final = "1"
ADAPTER_SOURCE: Final = "benchmarks.logic_pipeline.adapters"
STAGE_ORDER: Final = (
    StageName.COMPILER,
    StageName.SPACY,
    StageName.SYMAI,
    StageName.HAMMER,
    StageName.LEANSTRAL,
    StageName.KERNEL,
)

_SAFE_ID_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")
_MAX_DETAIL_LENGTH: Final = 512

HAMMER_EVIDENCE_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.hammer-evidence.v1"
)
LEANSTRAL_EVIDENCE_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.leanstral-evidence.v1"
)
LEANSTRAL_DRAFT_SCHEMA: Final = (
    "ipfs_accelerate_py/agent-supervisor/leanstral-proof-draft@1"
)
LEANSTRAL_MODEL_RESOURCE_CLASS: Final = "model"
LEANSTRAL_KERNEL_RESOURCE_CLASS: Final = "kernel"
LEANSTRAL_MAX_REPAIR_ATTEMPTS: Final = 1
LEANSTRAL_MAX_CONTEXT_BYTES: Final = 64 * 1024
# StageRecord also bounds individual strings to 4096 characters.  Keep the
# provider output within that durable wire-contract limit.
LEANSTRAL_MAX_DRAFT_BYTES: Final = 4 * 1024
_LEANSTRAL_FORBIDDEN_CONSTRUCT = re.compile(
    r"(?i)(?<![A-Za-z0-9_'])(?:sorry|admit|sorryAx|axiom|unsafe)(?![A-Za-z0-9_'])"
)
_LEANSTRAL_DRAFT_KEYS = frozenset(
    {
        "schema_version",
        "artifact_id",
        "artifact_kind",
        "stage",
        "draft_text",
        "proof_text",
        "request_id",
        "llm_provider",
        "model",
        "obligation_ids",
        "canonical_source_digest",
        "prompt_sha256",
        "output_sha256",
        "timeout_ms",
        "token_budget",
        "resource_class",
        "theorem_id",
        "theorem_equivalence_key",
        "context_capsule_id",
        "proposal_kind",
        "proposal_schema",
        "decomposition",
        "reused_artifact_ids",
        "prompt_tokens",
        "response_tokens",
        "assurance",
        "verified",
        "authoritative",
        "proof_attempted",
        "proof_success",
        "kernel_checked",
        "can_mutate_canonical_source",
        "can_mutate_obligations",
        "metadata",
    }
)


class HammerAdapterContractError(ProtocolContractError):
    """Raised when Hammer records cannot be joined to one proof-search path.

    The underlying Hammer package owns the individual record contracts.  This
    exception is specific to the benchmark boundary: it covers the joins
    between request, portfolio, candidate, reconstruction, and environment
    records that are otherwise easy to lose when serializing a stage result.
    """


def _safe_id(value: object, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or value[0] not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        or any(char not in _SAFE_ID_CHARS for char in value)
        or value in {".", ".."}
    ):
        raise ProtocolContractError(
            f"{field_name} must be a safe 1-128 character identifier"
        )
    return value


def _digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise ProtocolContractError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _freeze_mapping(value: Mapping[str, object], field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise ProtocolContractError(f"{field_name} must be an object with string keys")
    # StageRecord performs the complete bounded/deep-freeze validation.  This
    # shallow proxy also prevents mutation between request construction and
    # handler execution.
    return MappingProxyType(dict(value))


def _input_digest(value: object) -> tuple[str, int]:
    try:
        encoded = canonical_json(value).encode("utf-8")
    except ProtocolContractError:
        raise
    if len(encoded) > 64 * 1024:
        raise ProtocolContractError("stage input exceeds the 64 KiB bound")
    return hashlib.sha256(encoded).hexdigest(), len(encoded)


@dataclass(frozen=True, slots=True)
class StageRequest:
    """Immutable invocation context shared by all stage handlers."""

    run_id: str
    case_id: str
    case_manifest_sha256: str
    variant_id: str = BASELINE_VARIANT
    split: Split = Split.PILOT
    cache_mode: CacheMode = CacheMode.COLD
    input_data: object = field(default_factory=dict)
    requested_identity: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )
    environment_sha256: str | None = None
    source: tuple[str, ...] = ("benchmark_input",)
    upstream_stage_digests: tuple[str, ...] = ()
    protocol_sha256: str = DEFAULT_PROTOCOL_SHA256

    def __post_init__(self) -> None:
        _safe_id(self.run_id, "run_id")
        _safe_id(self.case_id, "case_id")
        _digest(self.case_manifest_sha256, "case_manifest_sha256")
        _safe_id(self.variant_id, "variant_id")
        if self.variant_id not in {f"A{i}" for i in range(13)} | {"S1"}:
            raise ProtocolContractError(f"variant_id is not registered: {self.variant_id!r}")
        if not isinstance(self.split, Split) or not isinstance(self.cache_mode, CacheMode):
            raise ProtocolContractError("split and cache_mode must use protocol enums")
        _digest(self.protocol_sha256, "protocol_sha256")
        if self.protocol_sha256 != DEFAULT_PROTOCOL_SHA256:
            raise ProtocolContractError("request must bind frozen protocol revision 1")
        if self.environment_sha256 is not None:
            _digest(self.environment_sha256, "environment_sha256")
        if not isinstance(self.source, tuple) or not self.source:
            raise ProtocolContractError("source must be a nonempty tuple")
        if len(self.source) > len(STAGE_ORDER):
            raise ProtocolContractError("source contains too many entries")
        for item in self.source:
            if not isinstance(item, str) or not item.strip() or len(item) > 256:
                raise ProtocolContractError("source entries must be bounded strings")
        if not isinstance(self.upstream_stage_digests, tuple):
            raise ProtocolContractError("upstream_stage_digests must be a tuple")
        for digest in self.upstream_stage_digests:
            _digest(digest, "upstream_stage_digests[]")
        _freeze_mapping(self.requested_identity, "requested_identity")
        _input_digest(self.input_data)

    @property
    def input_sha256(self) -> str:
        return _input_digest(self.input_data)[0]

    @property
    def input_bytes(self) -> int:
        return _input_digest(self.input_data)[1]

    def with_upstream(self, digest: str) -> "StageRequest":
        _digest(digest, "upstream_stage_digest")
        return replace(
            self,
            upstream_stage_digests=(*self.upstream_stage_digests, digest),
        )


@dataclass(frozen=True, slots=True)
class StageOutput:
    """Optional handler result with explicit status and effective identity."""

    data: object = field(default_factory=dict)
    status: StageStatus = StageStatus.SUCCESS
    effective_identity: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )
    failure_code: FailureCode | None = None
    failure_detail: str | None = None
    telemetry: TelemetryRecord | None = None
    kernel_accepted: bool = False
    kernel_receipt_sha256: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, StageStatus):
            raise ProtocolContractError("status must be a StageStatus")
        _freeze_mapping(self.effective_identity, "effective_identity")
        if self.failure_code is not None and not isinstance(
            self.failure_code, FailureCode
        ):
            raise ProtocolContractError("failure_code must be a FailureCode")
        if self.failure_detail is not None and (
            not isinstance(self.failure_detail, str)
            or not self.failure_detail.strip()
            or len(self.failure_detail) > _MAX_DETAIL_LENGTH
        ):
            raise ProtocolContractError("failure_detail is empty or too long")
        if self.telemetry is not None and not isinstance(self.telemetry, TelemetryRecord):
            raise ProtocolContractError("telemetry must be a TelemetryRecord")
        if not isinstance(self.kernel_accepted, bool):
            raise ProtocolContractError("kernel_accepted must be a boolean")


StageHandler = Callable[[StageRequest], object]


@dataclass(frozen=True, slots=True)
class StageAdapter:
    """A versioned adapter around one explicitly injected stage callable."""

    stage: StageName
    handler: StageHandler | None = field(default=None, repr=False, compare=False)
    adapter_version: str = ADAPTER_VERSION
    adapter_id: str | None = None
    source: tuple[str, ...] = (ADAPTER_SOURCE,)
    resource_lane: ResourceLane | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.stage, StageName):
            raise ProtocolContractError("stage must be a StageName")
        _safe_id(self.adapter_version, "adapter_version")
        adapter_id = self.adapter_id or f"{self.stage.value}-adapter"
        _safe_id(adapter_id, "adapter_id")
        object.__setattr__(self, "adapter_id", adapter_id)
        if self.resource_lane is None:
            lane = {
                StageName.SYMAI: ResourceLane.MODEL,
                StageName.LEANSTRAL: ResourceLane.MODEL,
                StageName.HAMMER: ResourceLane.SOLVER,
                StageName.KERNEL: ResourceLane.KERNEL,
            }.get(self.stage, ResourceLane.CPU)
            object.__setattr__(self, "resource_lane", lane)
        elif not isinstance(self.resource_lane, ResourceLane):
            raise ProtocolContractError("resource_lane must be a ResourceLane")
        if not isinstance(self.source, tuple) or not self.source:
            raise ProtocolContractError("source must be a nonempty tuple")
        for item in self.source:
            if not isinstance(item, str) or not item.strip() or len(item) > 256:
                raise ProtocolContractError("source entries must be bounded strings")
        if self.handler is not None and not callable(self.handler):
            raise ProtocolContractError("handler must be callable")

    def _telemetry(
        self,
        request: StageRequest,
        *,
        started_wall: float,
        started_cpu: float,
        output: StageOutput | None,
        output_bytes: int = 0,
    ) -> TelemetryRecord:
        supplied = None if output is None else output.telemetry
        if supplied is not None:
            return supplied
        return TelemetryRecord(
            wall_time_ms=round(max(0.0, time.perf_counter() - started_wall) * 1000, 6),
            cpu_time_ms=round(max(0.0, time.process_time() - started_cpu) * 1000, 6),
            input_items=1,
            output_items=1 if output is not None and output.status is StageStatus.SUCCESS else 0,
            model_calls=1 if self.stage in {StageName.SYMAI, StageName.LEANSTRAL} else 0,
            bytes_in=request.input_bytes,
            bytes_out=output_bytes,
            resource_lane=self.resource_lane or ResourceLane.CPU,
        )

    def _provenance(
        self, request: StageRequest, effective_identity: Mapping[str, object]
    ) -> StageProvenance:
        return StageProvenance(
            schema="ipfs-datasets.logic-pipeline-benchmark.stage-provenance.v1",
            adapter_id=self.adapter_id or f"{self.stage.value}-adapter",
            adapter_version=self.adapter_version,
            source=tuple((*self.source, *request.source)),
            requested_identity=request.requested_identity,
            effective_identity=effective_identity,
            input_sha256=request.input_sha256,
            environment_sha256=request.environment_sha256,
            upstream_stage_digests=request.upstream_stage_digests,
        )

    def run(
        self,
        request: StageRequest,
        *,
        telemetry: TelemetryRecord | None = None,
    ) -> StageRecord:
        """Execute the injected handler and always return a strict record."""

        if not isinstance(request, StageRequest):
            raise ProtocolContractError("request must be a StageRequest")
        if request.protocol_sha256 != DEFAULT_PROTOCOL_SHA256:
            raise ProtocolContractError("request must bind frozen protocol revision 1")
        started_wall = time.perf_counter()
        started_cpu = time.process_time()
        result: StageOutput
        if self.handler is None:
            result = StageOutput(
                status=StageStatus.UNAVAILABLE,
                effective_identity=request.requested_identity,
                failure_code=FailureCode.CAPABILITY_UNAVAILABLE,
                failure_detail=f"{self.stage.value} handler was not configured",
            )
        else:
            try:
                raw = self.handler(request)
                result = raw if isinstance(raw, StageOutput) else StageOutput(data=raw)
            except Exception as exc:  # boundary must retain failure, not escape telemetry
                result = StageOutput(
                    status=StageStatus.FAILED,
                    effective_identity=request.requested_identity,
                    failure_code=FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
                    failure_detail=f"{self.stage.value} adapter raised {type(exc).__name__}",
                )
        effective_identity = result.effective_identity or request.requested_identity
        encoded_output = b""
        if result.status is StageStatus.SUCCESS:
            encoded_output = canonical_json(result.data).encode("utf-8")
        measured = telemetry or self._telemetry(
            request,
            started_wall=started_wall,
            started_cpu=started_cpu,
            output=result,
            output_bytes=len(encoded_output),
        )
        if measured.resource_lane is not self.resource_lane:
            raise ProtocolContractError(
                f"{self.stage.value} telemetry must use {self.resource_lane.value} resource lane"
            )
        if self.stage is not StageName.KERNEL and result.kernel_accepted:
            # Convert an accidental model/solver claim into an explicit failed
            # stage rather than allowing it to reach a final result.
            result = StageOutput(
                status=StageStatus.FAILED,
                effective_identity=effective_identity,
                failure_code=FailureCode.SAFETY_CONTROL_FAILURE,
                failure_detail="non-kernel stage attempted kernel acceptance",
                telemetry=measured,
            )
        return StageRecord.create(
            protocol_sha256=request.protocol_sha256,
            run_id=request.run_id,
            case_id=request.case_id,
            case_manifest_sha256=request.case_manifest_sha256,
            variant_id=request.variant_id,
            split=request.split,
            cache_mode=request.cache_mode,
            stage=self.stage,
            adapter_version=self.adapter_version,
            status=result.status,
            provenance=self._provenance(request, effective_identity),
            telemetry=measured,
            data=result.data,
            failure_code=result.failure_code,
            failure_detail=result.failure_detail,
            kernel_accepted=result.kernel_accepted,
            kernel_receipt_sha256=result.kernel_receipt_sha256,
        )

    execute = run


class CompilerAdapter(StageAdapter):
    def __init__(self, handler: StageHandler | None = None, **kwargs: object) -> None:
        super().__init__(StageName.COMPILER, handler=handler, **kwargs)


class SpacyAdapter(StageAdapter):
    def __init__(self, handler: StageHandler | None = None, **kwargs: object) -> None:
        super().__init__(StageName.SPACY, handler=handler, **kwargs)


class SymaiAdapter(StageAdapter):
    def __init__(self, handler: StageHandler | None = None, **kwargs: object) -> None:
        super().__init__(StageName.SYMAI, handler=handler, **kwargs)


def HSSLEV0335D9B() -> str:
    """Return the AST-verifiable Hammer proof-path evidence receipt."""

    return "Hammer request, bounded portfolio, normalization, reconstruction, and receipt records"


def _hammer_contract_types() -> tuple[Any, ...]:
    """Load Hammer record types only when a Hammer handler is executed."""

    from ipfs_datasets_py.logic.hammers.models import (
        EnvironmentLockRecord,
        HammerRequest,
        ProofCandidateRecord,
        ReconstructionRecord,
        SUPPORTED_SCHEMA_VERSIONS,
    )
    from ipfs_datasets_py.logic.hammers.portfolio import PortfolioRunResult

    return (
        HammerRequest,
        PortfolioRunResult,
        ProofCandidateRecord,
        ReconstructionRecord,
        EnvironmentLockRecord,
        SUPPORTED_SCHEMA_VERSIONS,
    )


def _coerce_hammer_record(
    value: object,
    record_type: Any,
    field_name: str,
    *,
    optional: bool = False,
) -> Any:
    if value is None and optional:
        return None
    if isinstance(value, record_type):
        record = value
    elif isinstance(value, Mapping):
        try:
            record = record_type.from_dict(dict(value))
        except (KeyError, TypeError, ValueError) as exc:
            raise HammerAdapterContractError(
                f"{field_name} is not a valid {record_type.__name__}: {exc}"
            ) from exc
    else:
        raise HammerAdapterContractError(
            f"{field_name} must be a {record_type.__name__} or serialized object"
        )
    validator = getattr(record, "validate", None)
    if callable(validator):
        try:
            validator()
        except (TypeError, ValueError) as exc:
            raise HammerAdapterContractError(
                f"{field_name} failed {record_type.__name__} validation: {exc}"
            ) from exc
    return record


def _hammer_record_dict(record: object, field_name: str) -> dict[str, object]:
    to_dict = getattr(record, "to_dict", None)
    if not callable(to_dict):
        raise HammerAdapterContractError(
            f"{field_name} does not expose a serializable to_dict contract"
        )
    value = to_dict()
    if not isinstance(value, dict):
        raise HammerAdapterContractError(f"{field_name}.to_dict() must return an object")
    return value


def _validate_hammer_evidence(
    value: object,
    *,
    request: StageRequest,
) -> dict[str, object]:
    """Validate and serialize one complete Hammer proof-search path.

    The backend handler may return native Hammer records or their serialized
    forms.  The resulting benchmark payload is always JSON data and retains
    each record separately.  Cross-record checks here are intentionally
    stricter than the individual Hammer model validators: a candidate from a
    different request, a reconstruction for a different candidate, or a
    portfolio attempt from a different request must never be presented as one
    stage result.

    Expected payload keys are ``request``, ``portfolio`` (a
    ``PortfolioRunResult``), optional ``proof_candidate``/``candidate``,
    optional ``reconstruction``, optional ``environment_lock``, and optional
    ``normalized_evidence``.  The handler may attach diagnostic keys, but the
    adapter emits only the bounded, contract-defined records below.
    """

    if not isinstance(value, Mapping):
        raise HammerAdapterContractError("Hammer handler output must be an object")
    (
        request_type,
        portfolio_type,
        candidate_type,
        reconstruction_type,
        environment_type,
        supported_schema_versions,
    ) = _hammer_contract_types()

    request_value = value.get("request")
    hammer_request = _coerce_hammer_record(request_value, request_type, "request")
    portfolio_value = value.get("portfolio", value.get("run_result"))
    portfolio = _coerce_hammer_record(portfolio_value, portfolio_type, "portfolio")
    if portfolio.schema_version not in supported_schema_versions:
        raise HammerAdapterContractError(
            f"portfolio.schema_version {portfolio.schema_version!r} is unsupported"
        )
    candidate_value = value.get("proof_candidate", value.get("candidate"))
    candidate = _coerce_hammer_record(
        candidate_value,
        candidate_type,
        "proof_candidate",
        optional=True,
    )
    reconstruction = _coerce_hammer_record(
        value.get("reconstruction"),
        reconstruction_type,
        "reconstruction",
        optional=True,
    )
    environment_lock = _coerce_hammer_record(
        value.get("environment_lock"),
        environment_type,
        "environment_lock",
        optional=True,
    )

    request_id = hammer_request.request_id
    # If the caller supplied a Hammer id in benchmark input/identity, bind it
    # too.  The fields are optional for compatibility with generic stage
    # callers, but when present they prevent a handler from silently switching
    # the request it is answering.
    expected_ids: list[object] = []
    if isinstance(request.input_data, Mapping):
        expected_ids.extend(
            request.input_data.get(name)
            for name in ("hammer_request_id", "request_id")
            if name in request.input_data
        )
    expected_ids.extend(
        request.requested_identity.get(name)
        for name in ("hammer_request_id", "request_id")
        if name in request.requested_identity
    )
    for expected_id in expected_ids:
        if expected_id is not None and expected_id != request_id:
            raise HammerAdapterContractError(
                f"Hammer request_id {request_id!r} does not match benchmark identity "
                f"{expected_id!r}"
            )

    if portfolio.request_id != request_id:
        raise HammerAdapterContractError(
            f"portfolio.request_id {portfolio.request_id!r} does not match "
            f"request.request_id {request_id!r}"
        )
    for attempt in portfolio.attempts:
        try:
            attempt.validate()
        except (TypeError, ValueError) as exc:
            raise HammerAdapterContractError(
                f"portfolio attempt {attempt.attempt_id!r} failed validation: {exc}"
            ) from exc
        if attempt.solver_name not in hammer_request.policy.allowed_solvers:
            raise HammerAdapterContractError(
                f"solver {attempt.solver_name!r} is not allowlisted by request policy"
            )
        if attempt.timeout_seconds > hammer_request.policy.timeout_seconds:
            raise HammerAdapterContractError(
                f"attempt {attempt.attempt_id!r} exceeds the request timeout budget"
            )
        if attempt.network_used and not hammer_request.policy.network_allowed:
            raise HammerAdapterContractError(
                f"attempt {attempt.attempt_id!r} used network under a denied policy"
            )
        if attempt.request_id != request_id:
            raise HammerAdapterContractError(
                f"portfolio attempt {attempt.attempt_id!r} belongs to "
                f"request {attempt.request_id!r}, not {request_id!r}"
            )
    attempt_ids = {attempt.attempt_id for attempt in portfolio.attempts}

    # A policy flag alone is not enough to change the benchmark arm.  The
    # preregistered matrix names the learned and LLM-ranking arms explicitly,
    # so a record cannot smuggle either ranking mode into A0-A9 or A12.
    if hammer_request.policy.allow_learned_premise_selector and request.variant_id != "A10":
        raise HammerAdapterContractError(
            "learned premise selection is only permitted by named variant A10"
        )
    if hammer_request.policy.allow_llm_premise_ranking and request.variant_id != "A11":
        raise HammerAdapterContractError(
            "LLM premise ranking is only permitted by named variant A11"
        )
    if set(portfolio.evidence) - attempt_ids:
        raise HammerAdapterContractError(
            "portfolio evidence contains an unknown solver attempt"
        )

    if candidate is not None:
        if candidate.request_id != request_id:
            raise HammerAdapterContractError(
                f"proof_candidate.request_id {candidate.request_id!r} does not "
                f"match request.request_id {request_id!r}"
            )
        if candidate.solver_attempt_id not in attempt_ids:
            raise HammerAdapterContractError(
                f"proof_candidate.solver_attempt_id {candidate.solver_attempt_id!r} "
                "is not present in portfolio.attempts"
            )

    if reconstruction is not None:
        if reconstruction.request_id != request_id:
            raise HammerAdapterContractError(
                f"reconstruction.request_id {reconstruction.request_id!r} does not "
                f"match request.request_id {request_id!r}"
            )
        if reconstruction.target_itp is not hammer_request.itp:
            raise HammerAdapterContractError(
                f"reconstruction.target_itp {reconstruction.target_itp.value!r} "
                f"does not match request.itp {hammer_request.itp.value!r}"
            )
        if candidate is None:
            raise HammerAdapterContractError(
                "reconstruction requires the corresponding proof_candidate"
            )
        if reconstruction.candidate_id != candidate.candidate_id:
            raise HammerAdapterContractError(
                f"reconstruction.candidate_id {reconstruction.candidate_id!r} "
                f"does not match proof_candidate.candidate_id {candidate.candidate_id!r}"
            )
        if environment_lock is None:
            raise HammerAdapterContractError(
                "reconstruction requires environment_lock"
            )
        if (
            environment_lock is not None
            and reconstruction.environment_lock_id != environment_lock.lock_id
        ):
            raise HammerAdapterContractError(
                "reconstruction.environment_lock_id does not match environment_lock"
            )
        if environment_lock is not None and environment_lock.itp is not hammer_request.itp:
            raise HammerAdapterContractError(
                f"environment_lock.itp {environment_lock.itp.value!r} does not "
                f"match request.itp {hammer_request.itp.value!r}"
            )

    normalized_payload: dict[str, dict[str, object]] = {}
    normalized_value = value.get("normalized_evidence", {})
    if normalized_value is None:
        normalized_value = {}
    if not isinstance(normalized_value, Mapping):
        raise HammerAdapterContractError("normalized_evidence must be an object")
    try:
        from ipfs_datasets_py.logic.hammers.provenance import NormalizedEvidence

        for attempt_id, evidence_value in normalized_value.items():
            if not isinstance(attempt_id, str) or not (
                isinstance(evidence_value, Mapping)
                or isinstance(evidence_value, NormalizedEvidence)
            ):
                raise HammerAdapterContractError(
                    "normalized_evidence keys and values must be objects"
                )
            evidence = (
                evidence_value
                if isinstance(evidence_value, NormalizedEvidence)
                else NormalizedEvidence.from_dict(dict(evidence_value))
            )
            validator = getattr(evidence, "validate", None)
            if callable(validator):
                validator()
            if evidence.request_id != request_id or evidence.attempt_id != attempt_id:
                raise HammerAdapterContractError(
                    f"normalized evidence {attempt_id!r} is not bound to the "
                    "owning request/attempt"
                )
            if attempt_id not in attempt_ids:
                raise HammerAdapterContractError(
                    f"normalized evidence references unknown attempt {attempt_id!r}"
                )
            normalized_payload[attempt_id] = _hammer_record_dict(
                evidence, f"normalized_evidence[{attempt_id!r}]"
            )
    except HammerAdapterContractError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise HammerAdapterContractError(
            f"invalid normalized_evidence payload: {exc}"
        ) from exc

    accepted = bool(reconstruction is not None and reconstruction.kernel_accepted)
    record_payload: dict[str, object] = {
        "request": _hammer_record_dict(hammer_request, "request"),
        "portfolio": _hammer_record_dict(portfolio, "portfolio"),
        "normalized_evidence": normalized_payload,
        "proof_candidate": (
            None if candidate is None else _hammer_record_dict(candidate, "proof_candidate")
        ),
        "reconstruction": (
            None
            if reconstruction is None
            else _hammer_record_dict(reconstruction, "reconstruction")
        ),
        "environment_lock": (
            None
            if environment_lock is None
            else _hammer_record_dict(environment_lock, "environment_lock")
        ),
        "reconstruction_kernel_accepted": accepted,
        "status": "verified" if accepted else ("candidate" if candidate else "unknown"),
    }
    evidence_id = hashlib.sha256(
        canonical_json({"schema": HAMMER_EVIDENCE_SCHEMA, **record_payload}).encode(
            "utf-8"
        )
    ).hexdigest()
    return {
        "schema": HAMMER_EVIDENCE_SCHEMA,
        "evidence_id": evidence_id,
        **record_payload,
        # This is descriptive evidence for the subsequent kernel stage.  It
        # intentionally does not set StageOutput.kernel_accepted: only the
        # benchmark's explicit kernel adapter can establish final authority.
    }


class HammerAdapter(StageAdapter):
    def __init__(self, handler: StageHandler | None = None, **kwargs: object) -> None:
        # Keep the backend callable injected and lazy.  Importing this module
        # must not import Hammer's optional solver/frontend dependencies.
        wrapped = None if handler is None else self._validated_handler(handler)
        super().__init__(StageName.HAMMER, handler=wrapped, **kwargs)

    @staticmethod
    def _validated_handler(handler: StageHandler) -> StageHandler:
        def invoke(request: StageRequest) -> object:
            try:
                raw = handler(request)
                if not isinstance(raw, StageOutput):
                    raw = StageOutput(data=raw)
                if raw.status is StageStatus.SUCCESS:
                    # Preserve the generic StageAdapter behavior for callers
                    # that use Hammer as an opaque stage payload.  Once a
                    # handler opts into the Hammer record vocabulary, the
                    # complete cross-record contract is mandatory.
                    if not isinstance(raw.data, Mapping) or not any(
                        key in raw.data
                        for key in (
                            "request",
                            "portfolio",
                            "run_result",
                            "proof_candidate",
                            "candidate",
                            "reconstruction",
                            "environment_lock",
                            "normalized_evidence",
                        )
                    ):
                        return raw
                    data = _validate_hammer_evidence(
                        raw.data,
                        request=request,
                    )
                    return replace(raw, data=data)
                return raw
            except HammerAdapterContractError as exc:
                return StageOutput(
                    status=StageStatus.FAILED,
                    effective_identity=request.requested_identity,
                    failure_code=FailureCode.RECEIPT_OR_PROVENANCE_FAILURE,
                    failure_detail=str(exc)[:_MAX_DETAIL_LENGTH],
                )
            except ImportError as exc:
                return StageOutput(
                    status=StageStatus.UNAVAILABLE,
                    effective_identity=request.requested_identity,
                    failure_code=FailureCode.CAPABILITY_UNAVAILABLE,
                    failure_detail=f"Hammer contracts unavailable: {exc}",
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise HammerAdapterContractError(
                    f"invalid Hammer evidence payload: {exc}"
                ) from exc

        return invoke


class LeanstralAdapterContractError(ProtocolContractError):
    """Raised when a Leanstral request or draft crosses the benchmark boundary."""


@dataclass(frozen=True, slots=True)
class LeanstralAdapterConfig:
    """Frozen limits for the benchmark's untrusted Leanstral model lane.

    The supervisor provider has its own limits.  These smaller benchmark-side
    limits keep a malformed case from expanding the provider request and make
    the one-repair rule visible in the stage receipt.
    """

    max_context_bytes: int = LEANSTRAL_MAX_CONTEXT_BYTES
    max_draft_bytes: int = LEANSTRAL_MAX_DRAFT_BYTES
    max_repair_attempts: int = LEANSTRAL_MAX_REPAIR_ATTEMPTS
    model_resource_class: str = LEANSTRAL_MODEL_RESOURCE_CLASS
    kernel_resource_class: str = LEANSTRAL_KERNEL_RESOURCE_CLASS

    def __post_init__(self) -> None:
        for name in ("max_context_bytes", "max_draft_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise LeanstralAdapterContractError(f"{name} must be a positive integer")
        if self.max_draft_bytes > LEANSTRAL_MAX_DRAFT_BYTES:
            raise LeanstralAdapterContractError(
                f"max_draft_bytes cannot exceed {LEANSTRAL_MAX_DRAFT_BYTES}"
            )
        if self.max_repair_attempts != LEANSTRAL_MAX_REPAIR_ATTEMPTS:
            raise LeanstralAdapterContractError(
                "Leanstral benchmark repair is fixed to exactly one bounded attempt"
            )
        for name in ("model_resource_class", "kernel_resource_class"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise LeanstralAdapterContractError(f"{name} must be non-empty")
        if self.model_resource_class == self.kernel_resource_class:
            raise LeanstralAdapterContractError(
                "Leanstral model and kernel resource lanes must differ"
            )


def HSSLEV0342A4C() -> str:
    """Return the AST-verifiable Leanstral synthesis/repair evidence receipt."""

    return "Leanstral proof drafts use strict schemas and one bounded unverified repair"


def _bounded_canonical(value: object, field_name: str, maximum: int) -> object:
    try:
        encoded = canonical_json(value).encode("utf-8")
    except ProtocolContractError as exc:
        raise LeanstralAdapterContractError(f"{field_name} is not strict JSON") from exc
    if len(encoded) > maximum:
        raise LeanstralAdapterContractError(
            f"{field_name} exceeds the {maximum} byte bound"
        )
    return json.loads(encoded.decode("utf-8"))


def _leanstral_input(
    request: StageRequest,
    config: LeanstralAdapterConfig,
) -> tuple[dict[str, object], str, int]:
    """Build one fixed-obligation provider request from benchmark input."""

    if not isinstance(request.input_data, Mapping):
        raise LeanstralAdapterContractError("Leanstral input_data must be an object")
    raw = dict(request.input_data)
    raw_ids = raw.get("obligation_ids", raw.get("obligation_id"))
    if isinstance(raw_ids, str):
        obligation_ids = (raw_ids.strip(),)
    elif isinstance(raw_ids, Sequence) and not isinstance(raw_ids, (bytes, bytearray)):
        obligation_ids = tuple(item.strip() for item in raw_ids if isinstance(item, str))
        if len(obligation_ids) != len(raw_ids):
            raise LeanstralAdapterContractError("obligation_ids must contain strings")
    else:
        raise LeanstralAdapterContractError("one fixed obligation_id is required")
    if len(obligation_ids) != 1:
        raise LeanstralAdapterContractError(
            "Leanstral accepts exactly one fixed obligation_id per request"
        )
    obligation_id = _safe_id(obligation_ids[0], "obligation_id")

    repair_value = raw.get("repair")
    supplied_attempt = raw.get("repair_attempt", 0)
    if isinstance(supplied_attempt, bool) or not isinstance(supplied_attempt, int):
        raise LeanstralAdapterContractError("repair_attempt must be an integer")
    if supplied_attempt not in (0, 1):
        raise LeanstralAdapterContractError("repair_attempt exceeds the one-attempt bound")
    repair_attempt = 0
    if repair_value is not None:
        if not isinstance(repair_value, Mapping):
            raise LeanstralAdapterContractError("repair must be an object")
        repair = dict(_bounded_canonical(repair_value, "repair", config.max_context_bytes))
        if supplied_attempt != 1:
            raise LeanstralAdapterContractError(
                "a repair payload must explicitly identify repair_attempt 1"
            )
        failure = repair.get("failure", repair.get("error"))
        failed_draft = repair.get("failed_draft", repair.get("draft"))
        if not isinstance(failure, str) or not failure.strip():
            raise LeanstralAdapterContractError("repair requires a bounded failure message")
        if not isinstance(failed_draft, (str, Mapping)):
            raise LeanstralAdapterContractError("repair requires the failed draft")
        if isinstance(failed_draft, str) and not failed_draft.strip():
            raise LeanstralAdapterContractError("repair failed_draft cannot be empty")
        repair_attempt = 1
    elif supplied_attempt:
        raise LeanstralAdapterContractError(
            "repair_attempt 1 requires a repair payload"
        )

    context_capsule = raw.get(
        "context_capsule",
        raw.get("proof_context_capsule", raw.get("proof_context")),
    )
    prompt = raw.get("prompt")
    if prompt is None:
        context = raw.get("context")
        if isinstance(context, str):
            prompt = context
        elif context is not None and context_capsule is None:
            # Keep generic benchmark callers useful while still sending a
            # strict string prompt to the provider.
            prompt = canonical_json(_bounded_canonical(context, "context", config.max_context_bytes))
    if context_capsule is None and (not isinstance(prompt, str) or not prompt.strip()):
        raise LeanstralAdapterContractError(
            "Leanstral input requires a non-empty prompt or context_capsule"
        )
    if isinstance(prompt, str) and not prompt.strip():
        raise LeanstralAdapterContractError("prompt cannot be empty")

    payload = dict(raw)
    payload["obligation_id"] = obligation_id
    payload["obligation_ids"] = [obligation_id]
    payload["repair_attempt"] = repair_attempt
    payload["max_repair_attempts"] = config.max_repair_attempts
    payload["resource_class"] = config.model_resource_class
    if context_capsule is not None:
        payload["context_capsule"] = _bounded_canonical(
            context_capsule, "context_capsule", config.max_context_bytes
        )
        payload.pop("proof_context_capsule", None)
        payload.pop("proof_context", None)
    else:
        payload["prompt"] = prompt
    if repair_value is not None:
        repair = payload["repair"]
        assert isinstance(repair, Mapping)
        failure = repair.get("failure", repair.get("error"))
        failed_draft = repair.get("failed_draft", repair.get("draft"))
        payload["compact_failures"] = [{"message": failure}]
        if isinstance(failed_draft, Mapping):
            payload["reusable_drafts"] = [dict(failed_draft)]
        elif isinstance(prompt, str):
            payload["prompt"] = (
                prompt
                + "\n\nREPAIR FAILURE (untrusted diagnostic):\n"
                + str(failure).strip()
                + "\nPREVIOUS DRAFT (untrusted):\n"
                + failed_draft.strip()
            )
    normalized = _bounded_canonical(payload, "Leanstral provider payload", config.max_context_bytes)
    if not isinstance(normalized, dict):  # pragma: no cover - guarded above
        raise LeanstralAdapterContractError("Leanstral provider payload must be an object")
    return normalized, obligation_id, repair_attempt


def _draft_mapping(value: object) -> Mapping[str, object]:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        value = value.to_dict()
    if not isinstance(value, Mapping):
        raise LeanstralAdapterContractError("Leanstral response must be a draft object")
    # Permit a transport wrapper, but never permit arbitrary nested response
    # data to pass through as if it were a draft.
    for key in ("draft", "proof_draft", "model_artifact"):
        if key in value:
            if len(value) != 1 or not isinstance(value[key], Mapping):
                raise LeanstralAdapterContractError("Leanstral draft wrapper is malformed")
            value = value[key]
            break
    if not isinstance(value, Mapping):  # pragma: no cover - defensive
        raise LeanstralAdapterContractError("Leanstral draft must be an object")
    unknown = sorted(set(value) - _LEANSTRAL_DRAFT_KEYS)
    if unknown:
        raise LeanstralAdapterContractError(
            f"Leanstral draft contains unknown fields: {', '.join(unknown[:8])}"
        )
    return value


def _validate_leanstral_draft(
    value: object,
    *,
    request: StageRequest,
    obligation_id: str,
    repair_attempt: int,
    config: LeanstralAdapterConfig,
) -> dict[str, object]:
    draft = dict(_draft_mapping(value))
    if draft.get("schema_version") != LEANSTRAL_DRAFT_SCHEMA:
        raise LeanstralAdapterContractError("Leanstral response used the wrong draft schema")
    if draft.get("artifact_kind", "llm_output") != "llm_output":
        raise LeanstralAdapterContractError("Leanstral response is not an LLM draft artifact")
    if draft.get("stage", "model_draft") != "model_draft":
        raise LeanstralAdapterContractError("Leanstral response is not a model draft")
    artifact_id = draft.get("artifact_id")
    if not isinstance(artifact_id, str) or not artifact_id.strip():
        raise LeanstralAdapterContractError("Leanstral draft requires artifact_id")
    text = draft.get("draft_text", draft.get("proof_text"))
    if not isinstance(text, str) or not text.strip():
        raise LeanstralAdapterContractError("Leanstral draft text is empty or missing")
    text = text.strip()
    if len(text.encode("utf-8")) > config.max_draft_bytes:
        raise LeanstralAdapterContractError("Leanstral draft exceeds the byte bound")
    if "proof_text" in draft and draft["proof_text"] != text:
        raise LeanstralAdapterContractError("draft_text and proof_text disagree")
    forbidden = _LEANSTRAL_FORBIDDEN_CONSTRUCT.search(text)
    if forbidden:
        raise LeanstralAdapterContractError(
            f"Leanstral draft contains forbidden construct {forbidden.group(0)!r}"
        )
    raw_ids = draft.get("obligation_ids")
    if isinstance(raw_ids, str):
        draft_ids = (raw_ids.strip(),)
    elif isinstance(raw_ids, Sequence) and not isinstance(raw_ids, (bytes, bytearray)):
        draft_ids = tuple(item.strip() for item in raw_ids if isinstance(item, str))
    else:
        draft_ids = ()
    if draft_ids != (obligation_id,):
        raise LeanstralAdapterContractError(
            "Leanstral draft obligation_ids do not match the fixed request"
        )
    if draft.get("resource_class", config.model_resource_class) != config.model_resource_class:
        raise LeanstralAdapterContractError(
            "Leanstral model draft cannot use the kernel resource lane"
        )
    for field_name in (
        "verified",
        "authoritative",
        "proof_success",
        "kernel_checked",
        "can_mutate_canonical_source",
        "can_mutate_obligations",
    ):
        if field_name in draft and draft[field_name] is not False:
            raise LeanstralAdapterContractError(
                f"Leanstral model draft cannot claim {field_name}"
            )
    if draft.get("assurance", "unverified") not in {"unverified", "none"}:
        raise LeanstralAdapterContractError("Leanstral model draft must be unverified")
    supplied_digest = draft.get("output_sha256")
    calculated_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if supplied_digest is not None and supplied_digest != calculated_digest:
        raise LeanstralAdapterContractError("Leanstral draft output digest is invalid")
    draft["draft_text"] = text
    draft["proof_text"] = text
    draft["obligation_ids"] = [obligation_id]
    draft["output_sha256"] = calculated_digest
    draft["assurance"] = "unverified"
    draft["verified"] = False
    draft["authoritative"] = False
    draft["kernel_checked"] = False
    draft["repair_attempt"] = repair_attempt
    draft["benchmark_request_id"] = f"{request.run_id}:{request.case_id}"
    return draft


def _leanstral_failure(
    request: StageRequest,
    detail: str,
    *,
    unavailable: bool = False,
) -> StageOutput:
    return StageOutput(
        status=StageStatus.UNAVAILABLE if unavailable else StageStatus.FAILED,
        effective_identity=request.requested_identity,
        failure_code=(
            FailureCode.CAPABILITY_UNAVAILABLE
            if unavailable
            else FailureCode.LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT
        ),
        failure_detail=detail[:_MAX_DETAIL_LENGTH],
    )


def _provider_request_id(request: StageRequest, repair_attempt: int) -> str:
    digest = hashlib.sha256(
        f"{request.run_id}:{request.case_id}:{request.input_sha256}:{repair_attempt}".encode(
            "utf-8"
        )
    ).hexdigest()[:48]
    return f"leanstral-{digest}"


def _local_leanstral_handler(
    provider_config: object | None = None,
    adapter_config: LeanstralAdapterConfig | None = None,
) -> StageHandler:
    """Return a lazy handler over the supervisor-owned local provider."""

    provider_holder: dict[str, object] = {}

    def invoke(request: StageRequest) -> object:
        module = importlib.import_module(
            "ipfs_accelerate_py.agent_supervisor.leanstral_proof_provider"
        )
        protocol = importlib.import_module(
            "ipfs_accelerate_py.agent_supervisor.formal_verification_provider"
        )
        capabilities = importlib.import_module(
            "ipfs_accelerate_py.agent_supervisor.formal_verification_capabilities"
        )
        contracts = importlib.import_module(
            "ipfs_accelerate_py.agent_supervisor.formal_verification_contracts"
        )
        provider = provider_holder.get("provider")
        if provider is None:
            factory = getattr(module, "create_leanstral_proof_provider")
            provider = factory(provider_config) if provider_config is not None else factory()
            provider_holder["provider"] = provider
        payload, _, repair_attempt = _leanstral_input(
            request, adapter_config or LeanstralAdapterConfig()
        )
        provider_request = getattr(protocol, "ProviderRequest")(
            operation=getattr(capabilities, "ProofProviderOperation").PROVE,
            payload=payload,
            request_id=_provider_request_id(request, repair_attempt),
            resource_budget=getattr(contracts, "ResourceBudget")(
                wall_time_ms=0,
                model_token_limit=0,
                max_output_bytes=LEANSTRAL_MAX_DRAFT_BYTES,
            ),
            network_allowed=False,
        )
        return getattr(provider, "prove")(provider_request)

    return invoke


class LeanstralAdapter(StageAdapter):
    """Benchmark boundary for untrusted Leanstral synthesis and one repair.

    ``handler`` remains injectable for deterministic benchmark tests.  With no
    handler the local supervisor provider is resolved lazily at execution time;
    an absent router/model is therefore an explicit unavailable result rather
    than an import-time failure or a silent fallback to another arm.
    """

    def __init__(
        self,
        handler: StageHandler | None = None,
        *,
        provider: object | None = None,
        config: LeanstralAdapterConfig | None = None,
        provider_config: object | None = None,
        **kwargs: object,
    ) -> None:
        if handler is not None and provider is not None:
            raise ProtocolContractError("provide either handler or provider, not both")
        object.__setattr__(self, "config", config or LeanstralAdapterConfig())
        selected = handler
        if provider is not None:
            if callable(provider):
                selected = provider  # type: ignore[assignment]
            elif callable(getattr(provider, "prove", None)):
                def invoke(request: StageRequest) -> object:
                    payload, _, repair_attempt = _leanstral_input(request, self.config)
                    # A provider object supplied by a benchmark test follows
                    # the same supervisor ProviderRequest boundary as the
                    # local provider, without importing it at module import.
                    protocol = importlib.import_module(
                        "ipfs_accelerate_py.agent_supervisor.formal_verification_provider"
                    )
                    capabilities = importlib.import_module(
                        "ipfs_accelerate_py.agent_supervisor.formal_verification_capabilities"
                    )
                    verification_contracts = importlib.import_module(
                        "ipfs_accelerate_py.agent_supervisor.formal_verification_contracts"
                    )
                    return provider.prove(
                        protocol.ProviderRequest(
                            operation=capabilities.ProofProviderOperation.PROVE,
                            payload=payload,
                            request_id=_provider_request_id(request, repair_attempt),
                            resource_budget=verification_contracts.ResourceBudget(
                                max_output_bytes=self.config.max_draft_bytes,
                            ),
                            network_allowed=False,
                        )
                    )
                selected = invoke
            else:
                raise ProtocolContractError("provider must be callable or expose prove()")
        elif selected is None:
            selected = _local_leanstral_handler(provider_config, self.config)

        def validated(request: StageRequest) -> object:
            try:
                payload, obligation_id, repair_attempt = _leanstral_input(
                    request, self.config
                )
                normalized_request = replace(request, input_data=payload)
                raw = selected(normalized_request)  # type: ignore[misc]
                if isinstance(raw, StageOutput):
                    if raw.status is not StageStatus.SUCCESS:
                        return raw
                    output = raw
                else:
                    output = StageOutput(data=raw)
                data = _validate_leanstral_draft(
                    output.data,
                    request=request,
                    obligation_id=obligation_id,
                    repair_attempt=repair_attempt,
                    config=self.config,
                )
                evidence_without_id = {
                    "schema": LEANSTRAL_EVIDENCE_SCHEMA,
                    "obligation_id": obligation_id,
                    "mode": "repair" if repair_attempt else "synthesis",
                    "repair_attempts": repair_attempt,
                    "max_repair_attempts": self.config.max_repair_attempts,
                    "draft": data,
                    "trust": {
                        "assurance": "unverified",
                        "verified": False,
                        "authoritative": False,
                        "kernel_checked": False,
                    },
                    "resource_classes": {
                        "model_inference": self.config.model_resource_class,
                        "kernel_check": self.config.kernel_resource_class,
                    },
                }
                evidence_id = hashlib.sha256(
                    canonical_json(evidence_without_id).encode("utf-8")
                ).hexdigest()
                evidence = {"evidence_id": evidence_id, **evidence_without_id}
                identity = {
                    **dict(output.effective_identity),
                    "provider": data.get("llm_provider", "leanstral"),
                    "model": data.get("model", "Leanstral"),
                    "obligation_id": obligation_id,
                    "repair_attempt": repair_attempt,
                    "resource_class": self.config.model_resource_class,
                }
                return replace(output, data=evidence, effective_identity=identity)
            except LeanstralAdapterContractError as exc:
                return _leanstral_failure(request, str(exc))
            except (ImportError, ModuleNotFoundError) as exc:
                return _leanstral_failure(
                    request,
                    f"Leanstral provider unavailable: {type(exc).__name__}",
                    unavailable=True,
                )
            except TimeoutError as exc:
                return _leanstral_failure(request, f"Leanstral provider timed out: {exc}")
            except Exception as exc:
                provider_code = str(getattr(getattr(exc, "code", None), "value", getattr(exc, "code", "")))
                if provider_code in {"unavailable", "optional_dependency"}:
                    return _leanstral_failure(
                        request, "Leanstral provider is unavailable", unavailable=True
                    )
                if provider_code in {"timed_out", "resource_exhausted", "malformed_response", "malformed_request", "unsupported", "provider_error"}:
                    return _leanstral_failure(
                        request,
                        f"Leanstral provider rejected the request ({provider_code})",
                    )
                return StageOutput(
                    status=StageStatus.FAILED,
                    effective_identity=request.requested_identity,
                    failure_code=FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
                    failure_detail=f"Leanstral adapter raised {type(exc).__name__}",
                )

        super().__init__(StageName.LEANSTRAL, handler=validated, **kwargs)


class KernelAdapter(StageAdapter):
    def __init__(self, handler: StageHandler | None = None, **kwargs: object) -> None:
        super().__init__(StageName.KERNEL, handler=handler, **kwargs)


def build_default_adapters(
    handlers: Mapping[StageName, StageHandler] | None = None,
) -> Mapping[StageName, StageAdapter]:
    """Build the registered route without importing or configuring backends."""

    handlers = {} if handlers is None else dict(handlers)
    unknown = set(handlers) - set(STAGE_ORDER)
    if unknown:
        raise ProtocolContractError(f"handlers contain unknown stages: {sorted(unknown, key=str)}")
    adapters = {
        StageName.COMPILER: CompilerAdapter(handlers.get(StageName.COMPILER)),
        StageName.SPACY: SpacyAdapter(handlers.get(StageName.SPACY)),
        StageName.SYMAI: SymaiAdapter(handlers.get(StageName.SYMAI)),
        StageName.HAMMER: HammerAdapter(handlers.get(StageName.HAMMER)),
        StageName.LEANSTRAL: LeanstralAdapter(handlers.get(StageName.LEANSTRAL)),
        StageName.KERNEL: KernelAdapter(handlers.get(StageName.KERNEL)),
    }
    return MappingProxyType(adapters)


def run_stages(
    request: StageRequest,
    adapters: Mapping[StageName, StageAdapter],
    *,
    stages: Sequence[StageName] = STAGE_ORDER,
) -> CaseResultRecord:
    """Run an explicit stage sequence and bind all emitted records."""

    if not isinstance(adapters, Mapping):
        raise ProtocolContractError("adapters must be a mapping")
    records: list[StageRecord] = []
    current_request = request
    for stage in stages:
        if not isinstance(stage, StageName):
            raise ProtocolContractError("stages must contain StageName values")
        adapter = adapters.get(stage)
        if not isinstance(adapter, StageAdapter):
            raise ProtocolContractError(f"missing adapter for {stage.value}")
        record = adapter.run(current_request)
        records.append(record)
        current_request = current_request.with_upstream(record.digest)
    return CaseResultRecord.from_stages(records)


# Descriptive aliases make the public boundary easy to discover for callers
# that use "versioned" terminology from the objective heap.
VersionedStageAdapter = StageAdapter
StageTelemetry = TelemetryRecord
PipelineResult = CaseResultRecord


__all__ = [
    "ADAPTER_SOURCE",
    "ADAPTER_VERSION",
    "CaseResultRecord",
    "CompilerAdapter",
    "HAMMER_EVIDENCE_SCHEMA",
    "HammerAdapter",
    "HammerAdapterContractError",
    "HSSLEV0335D9B",
    "HSSLEV0306C18",
    "HSSLEV0342A4C",
    "KernelAdapter",
    "LEANSTRAL_DRAFT_SCHEMA",
    "LEANSTRAL_EVIDENCE_SCHEMA",
    "LEANSTRAL_KERNEL_RESOURCE_CLASS",
    "LEANSTRAL_MAX_CONTEXT_BYTES",
    "LEANSTRAL_MAX_DRAFT_BYTES",
    "LEANSTRAL_MAX_REPAIR_ATTEMPTS",
    "LEANSTRAL_MODEL_RESOURCE_CLASS",
    "LeanstralAdapterConfig",
    "LeanstralAdapterContractError",
    "LeanstralAdapter",
    "PipelineResult",
    "SpacyAdapter",
    "StageAdapter",
    "StageHandler",
    "StageOutput",
    "StageRequest",
    "StageTelemetry",
    "STAGE_ORDER",
    "SymaiAdapter",
    "VersionedStageAdapter",
    "build_default_adapters",
    "run_stages",
]
