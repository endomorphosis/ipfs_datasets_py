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
import time
from types import MappingProxyType
from typing import Callable, Final, Mapping, Sequence

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


class HammerAdapter(StageAdapter):
    def __init__(self, handler: StageHandler | None = None, **kwargs: object) -> None:
        super().__init__(StageName.HAMMER, handler=handler, **kwargs)


class LeanstralAdapter(StageAdapter):
    def __init__(self, handler: StageHandler | None = None, **kwargs: object) -> None:
        super().__init__(StageName.LEANSTRAL, handler=handler, **kwargs)


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
    "HammerAdapter",
    "HSSLEV0306C18",
    "KernelAdapter",
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
