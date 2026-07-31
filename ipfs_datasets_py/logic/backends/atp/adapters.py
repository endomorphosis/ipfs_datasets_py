"""Canonical, fail-closed adapters for ATP and legacy legal-logic provers.

The historical Vampire, E, DCEC, and TDFOL integrations predate the shared
backend contracts.  In particular, some of them infer success from arbitrary
substrings or attributes such as ``is_valid``.  This module is the compatibility
boundary for new callers:

* every invocation starts from an immutable :class:`BackendRequest`;
* Vampire and E run through :class:`BoundedToolRunner`;
* external output is classified only by an exact TPTP SZS status line;
* an unreconstructed proof/model is a candidate, never theorem authority;
* native bridges must return :class:`NativeProverResult` exactly; and
* artifacts and compatibility receipts are bound to both request and source.

The adapters do not import, initialize, probe, or modify a legacy engine during
capability discovery.  Actual engines are supplied through narrow injection
points, which also keeps integration tests deterministic.
"""

from __future__ import annotations

import json
import re
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
from ..process import (
    BoundedToolRunner,
    CancellationSignal,
    ToolRunLimits,
    ToolRunRequest,
    ToolRunResult,
)
from ..results import (
    CandidateResult,
    ResultAuthority,
    ResultStatus,
    SatisfiabilityResult,
    TheoremResult,
    TypedBackendResult,
)

ATP_COMPATIBILITY_BACKENDS_VERSION: Final = "ATPCompatibilityBackends@1"
ATP_ADAPTER_VERSION: Final = "atp-legacy-adapter/v1"
ATP_SOURCE_BINDING_VERSION: Final = "atp-source-binding/v1"
ATP_PROOF_OBJECT_VERSION: Final = "atp-proof-object/v1"
ATP_COUNTERMODEL_VERSION: Final = "atp-countermodel/v1"
LEGACY_PROVER_RESULT_VERSION: Final = "legacy-prover-result/v1"
LEGACY_COMPATIBILITY_RECEIPT_VERSION: Final = "legacy-compatibility-receipt/v1"

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SZS_STATUS = re.compile(
    r"^[ \t]*[%#][ \t]*SZS[ \t]+status[ \t]+([A-Za-z][A-Za-z0-9_]*)"
    r"(?:[ \t]+for[ \t]+[^\r\n]+)?[ \t]*$",
    re.MULTILINE,
)


class ATPAdapterError(ValueError):
    """Raised when an ATP request or adapter result violates the contract."""


class MalformedATPOutput(ATPAdapterError):
    """Raised when external prover output has no unambiguous SZS status."""


class SZSStatus(StrEnum):
    """Reviewed SZS statuses understood by the compatibility boundary."""

    THEOREM = "Theorem"
    UNSATISFIABLE = "Unsatisfiable"
    CONTRADICTORY_AXIOMS = "ContradictoryAxioms"
    SATISFIABLE = "Satisfiable"
    COUNTER_SATISFIABLE = "CounterSatisfiable"
    UNKNOWN = "Unknown"
    GAVE_UP = "GaveUp"
    TIMEOUT = "Timeout"
    RESOURCE_OUT = "ResourceOut"


class NativeProverStatus(StrEnum):
    """Closed outcomes accepted from an in-process legacy bridge."""

    PROVED = "proved"
    DISPROVED = "disproved"
    SATISFIABLE = "satisfiable"
    UNSATISFIABLE = "unsatisfiable"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    UNSUPPORTED = "unsupported"
    ERROR = "error"


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
        raise ATPAdapterError(
            f"{field_name} must be {qualifier}non-empty trimmed string without NUL bytes"
        )
    return value


def _digest(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if not _DIGEST.fullmatch(result):
        raise ATPAdapterError(f"{field_name} must be a lowercase SHA-256 digest")
    return result


def _frozen(value: Mapping[str, Any] | FrozenMap, field_name: str) -> FrozenMap:
    try:
        return value if isinstance(value, FrozenMap) else FrozenMap(value)
    except (TypeError, ValueError) as error:
        raise ATPAdapterError(
            f"{field_name} must contain immutable JSON-compatible data"
        ) from error


def _strings(value: Sequence[str] | object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ATPAdapterError(f"{field_name} must be a sequence of strings")
    result = tuple(_text(item, f"{field_name} item") for item in value)
    if len(result) != len(set(result)):
        raise ATPAdapterError(f"{field_name} must not contain duplicates")
    return result


def _content_digest(content: str) -> str:
    return stable_digest({"content": content})


def _artifact_content(value: object, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\x00" in value
    ):
        raise ATPAdapterError(
            f"{field_name} must be non-empty text without NUL bytes"
        )
    return value


@dataclass(frozen=True, slots=True)
class ATPSourceBinding:
    """Identity of the exact source submitted for one canonical request."""

    request_digest: str
    source_digest: str
    source_format: str
    schema_version: str = ATP_SOURCE_BINDING_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        object.__setattr__(
            self, "source_digest", _digest(self.source_digest, "source_digest")
        )
        object.__setattr__(
            self, "source_format", _text(self.source_format, "source_format")
        )
        if self.schema_version != ATP_SOURCE_BINDING_VERSION:
            raise ATPAdapterError(
                f"unsupported ATP source binding schema: {self.schema_version!r}"
            )

    @classmethod
    def bind(
        cls, request: BackendRequest, source: str, source_format: str
    ) -> ATPSourceBinding:
        if not isinstance(request, BackendRequest):
            raise ATPAdapterError("request must be a BackendRequest")
        normalized = _text(source, "source")
        normalized_format = _text(source_format, "source_format").lower()
        return cls(
            request_digest=request.digest,
            source_digest=stable_digest(
                {"source": normalized, "source_format": normalized_format}
            ),
            source_format=normalized_format,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "source_format": self.source_format,
        }


@dataclass(frozen=True, slots=True)
class ATPProofObject:
    """A proof artifact whose authority depends on explicit verification."""

    request_digest: str
    source_digest: str
    proof_format: str
    content: str
    verified: bool = False
    checker_id: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = ATP_PROOF_OBJECT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        object.__setattr__(
            self, "source_digest", _digest(self.source_digest, "source_digest")
        )
        object.__setattr__(
            self, "proof_format", _text(self.proof_format, "proof_format")
        )
        object.__setattr__(
            self, "content", _artifact_content(self.content, "content")
        )
        if not isinstance(self.verified, bool):
            raise ATPAdapterError("verified must be a boolean")
        object.__setattr__(
            self, "checker_id", _text(self.checker_id, "checker_id", optional=True)
        )
        if self.verified and not self.checker_id:
            raise ATPAdapterError("verified proof objects require checker_id")
        object.__setattr__(self, "metadata", _frozen(self.metadata, "metadata"))
        if self.schema_version != ATP_PROOF_OBJECT_VERSION:
            raise ATPAdapterError(
                f"unsupported ATP proof object schema: {self.schema_version!r}"
            )

    @property
    def content_digest(self) -> str:
        return _content_digest(self.content)

    def is_bound_to(self, binding: ATPSourceBinding) -> bool:
        return (
            self.request_digest == binding.request_digest
            and self.source_digest == binding.source_digest
        )

    def to_dict(self, *, include_content: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "checker_id": self.checker_id,
            "content_digest": self.content_digest,
            "metadata": self.metadata.to_dict(),
            "proof_format": self.proof_format,
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "verified": self.verified,
        }
        if include_content:
            result["content"] = self.content
        return result


@dataclass(frozen=True, slots=True)
class ATPCountermodel:
    """A source-bound countermodel/model with explicit validation state."""

    request_digest: str
    source_digest: str
    model_format: str
    model: FrozenMap
    validated: bool = False
    validator_id: str = ""
    schema_version: str = ATP_COUNTERMODEL_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        object.__setattr__(
            self, "source_digest", _digest(self.source_digest, "source_digest")
        )
        object.__setattr__(
            self, "model_format", _text(self.model_format, "model_format")
        )
        object.__setattr__(self, "model", _frozen(self.model, "model"))
        if not isinstance(self.validated, bool):
            raise ATPAdapterError("validated must be a boolean")
        object.__setattr__(
            self,
            "validator_id",
            _text(self.validator_id, "validator_id", optional=True),
        )
        if self.validated and not self.validator_id:
            raise ATPAdapterError("validated countermodels require validator_id")
        if self.schema_version != ATP_COUNTERMODEL_VERSION:
            raise ATPAdapterError(
                f"unsupported ATP countermodel schema: {self.schema_version!r}"
            )

    @property
    def model_digest(self) -> str:
        return stable_digest({"model": self.model.to_dict()})

    def is_bound_to(self, binding: ATPSourceBinding) -> bool:
        return (
            self.request_digest == binding.request_digest
            and self.source_digest == binding.source_digest
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model.to_dict(),
            "model_digest": self.model_digest,
            "model_format": self.model_format,
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "validated": self.validated,
            "validator_id": self.validator_id,
        }


@dataclass(frozen=True, slots=True)
class NativeProverInvocation:
    """Explicit input passed to a native DCEC/TDFOL compatibility bridge."""

    request: BackendRequest
    source_binding: ATPSourceBinding
    source: str

    def __post_init__(self) -> None:
        if not isinstance(self.request, BackendRequest):
            raise ATPAdapterError("request must be a BackendRequest")
        if not isinstance(self.source_binding, ATPSourceBinding):
            raise ATPAdapterError("source_binding must be an ATPSourceBinding")
        object.__setattr__(self, "source", _text(self.source, "source"))
        if self.source_binding.request_digest != self.request.digest:
            raise ATPAdapterError("source binding does not match native request")


@dataclass(frozen=True, slots=True)
class NativeProverResult:
    """Only result shape accepted from a native or legacy prover bridge."""

    request_digest: str
    source_digest: str
    status: NativeProverStatus
    native_result_type: str
    elapsed_ms: int = 0
    steps: int = 0
    peak_memory_bytes: int = 0
    output_bytes: int = 0
    diagnostics: tuple[str, ...] = ()
    proof_object: ATPProofObject | None = None
    countermodel: ATPCountermodel | None = None
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = LEGACY_PROVER_RESULT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        object.__setattr__(
            self, "source_digest", _digest(self.source_digest, "source_digest")
        )
        try:
            status = (
                self.status
                if isinstance(self.status, NativeProverStatus)
                else NativeProverStatus(self.status)
            )
        except (TypeError, ValueError) as error:
            raise ATPAdapterError(f"unsupported native prover status: {self.status!r}") from error
        object.__setattr__(self, "status", status)
        object.__setattr__(
            self,
            "native_result_type",
            _text(self.native_result_type, "native_result_type"),
        )
        for field_name in (
            "elapsed_ms",
            "steps",
            "peak_memory_bytes",
            "output_bytes",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ATPAdapterError(f"{field_name} must be a non-negative integer")
        object.__setattr__(
            self, "diagnostics", _strings(self.diagnostics, "diagnostics")
        )
        if self.proof_object is not None and not isinstance(
            self.proof_object, ATPProofObject
        ):
            raise ATPAdapterError("proof_object must be an ATPProofObject")
        if self.countermodel is not None and not isinstance(
            self.countermodel, ATPCountermodel
        ):
            raise ATPAdapterError("countermodel must be an ATPCountermodel")
        object.__setattr__(self, "metadata", _frozen(self.metadata, "metadata"))
        artifact_bytes = sum(
            len(value.encode("utf-8"))
            for value in self.diagnostics
        )
        if self.proof_object is not None:
            artifact_bytes += len(self.proof_object.content.encode("utf-8"))
        if self.countermodel is not None:
            artifact_bytes += len(
                json.dumps(
                    self.countermodel.model.to_dict(),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            )
        artifact_bytes += len(
            json.dumps(
                self.metadata.to_dict(),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )
        object.__setattr__(
            self, "output_bytes", max(self.output_bytes, artifact_bytes)
        )
        if self.schema_version != LEGACY_PROVER_RESULT_VERSION:
            raise ATPAdapterError(
                f"unsupported native prover result schema: {self.schema_version!r}"
            )

    def is_bound_to(self, binding: ATPSourceBinding) -> bool:
        return (
            self.request_digest == binding.request_digest
            and self.source_digest == binding.source_digest
        )


@dataclass(frozen=True, slots=True)
class LegacyCompatibilityReceipt:
    """Audit record for one reviewed legacy-to-canonical normalization."""

    request_digest: str
    source_digest: str
    backend_id: str
    backend_version: str
    native_result_type: str
    native_status: NativeProverStatus
    canonical_result_id: str
    canonical_result_digest: str
    reviewed_behavior: bool
    schema_version: str = LEGACY_COMPATIBILITY_RECEIPT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        object.__setattr__(
            self, "source_digest", _digest(self.source_digest, "source_digest")
        )
        object.__setattr__(self, "backend_id", _text(self.backend_id, "backend_id"))
        object.__setattr__(
            self, "backend_version", _text(self.backend_version, "backend_version")
        )
        object.__setattr__(
            self,
            "native_result_type",
            _text(self.native_result_type, "native_result_type"),
        )
        try:
            object.__setattr__(
                self,
                "native_status",
                (
                    self.native_status
                    if isinstance(self.native_status, NativeProverStatus)
                    else NativeProverStatus(self.native_status)
                ),
            )
        except (TypeError, ValueError) as error:
            raise ATPAdapterError("native_status is invalid") from error
        object.__setattr__(
            self,
            "canonical_result_id",
            _text(self.canonical_result_id, "canonical_result_id"),
        )
        object.__setattr__(
            self,
            "canonical_result_digest",
            _digest(self.canonical_result_digest, "canonical_result_digest"),
        )
        if not isinstance(self.reviewed_behavior, bool):
            raise ATPAdapterError("reviewed_behavior must be a boolean")
        if self.schema_version != LEGACY_COMPATIBILITY_RECEIPT_VERSION:
            raise ATPAdapterError(
                f"unsupported compatibility receipt schema: {self.schema_version!r}"
            )

    @property
    def receipt_id(self) -> str:
        return f"legacy-compatibility:{stable_digest(self.to_dict())}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_id": self.backend_id,
            "backend_version": self.backend_version,
            "canonical_result_digest": self.canonical_result_digest,
            "canonical_result_id": self.canonical_result_id,
            "native_result_type": self.native_result_type,
            "native_status": self.native_status.value,
            "request_digest": self.request_digest,
            "reviewed_behavior": self.reviewed_behavior,
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
        }


@dataclass(frozen=True, slots=True)
class ATPAdapterOutcome:
    """Normalized result plus separately typed evidence and compatibility data."""

    request_digest: str
    source_binding: ATPSourceBinding
    result: TypedBackendResult
    proof_object: ATPProofObject | None = None
    countermodel: ATPCountermodel | None = None
    compatibility_receipt: LegacyCompatibilityReceipt | None = None
    interface_version: str = ATP_COMPATIBILITY_BACKENDS_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        if not isinstance(self.source_binding, ATPSourceBinding):
            raise ATPAdapterError("source_binding must be an ATPSourceBinding")
        if not isinstance(self.result, TypedBackendResult):
            raise ATPAdapterError("result must be a TypedBackendResult")
        if self.request_digest != self.source_binding.request_digest:
            raise ATPAdapterError("outcome request does not match source binding")
        for artifact_name, artifact in (
            ("proof_object", self.proof_object),
            ("countermodel", self.countermodel),
        ):
            if artifact is not None and not artifact.is_bound_to(self.source_binding):
                raise ATPAdapterError(f"{artifact_name} is not bound to this source")
        receipt = self.compatibility_receipt
        if receipt is not None and (
            receipt.request_digest != self.request_digest
            or receipt.source_digest != self.source_binding.source_digest
            or receipt.canonical_result_digest != self.result.digest
        ):
            raise ATPAdapterError("compatibility receipt is not bound to this outcome")
        if self.interface_version != ATP_COMPATIBILITY_BACKENDS_VERSION:
            raise ATPAdapterError(
                f"unsupported ATP compatibility interface: {self.interface_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "compatibility_receipt": (
                self.compatibility_receipt.to_dict()
                if self.compatibility_receipt is not None
                else None
            ),
            "countermodel": (
                self.countermodel.to_dict() if self.countermodel is not None else None
            ),
            "interface_version": self.interface_version,
            "proof_object": (
                self.proof_object.to_dict() if self.proof_object is not None else None
            ),
            "request_digest": self.request_digest,
            "result": self.result.to_dict(),
            "source_binding": self.source_binding.to_dict(),
        }


ProofReconstructor = Callable[
    [ATPSourceBinding, ToolRunResult, SZSStatus], ATPProofObject | None
]
CountermodelParser = Callable[
    [ATPSourceBinding, ToolRunResult, SZSStatus], ATPCountermodel | None
]
NativeProverRunner = Callable[[NativeProverInvocation], NativeProverResult]


def parse_szs_status(output: str) -> SZSStatus:
    """Parse one unambiguous, reviewed SZS status.

    Free-form phrases such as ``"Proof found"`` and ``"Theorem"`` are
    intentionally not accepted.  Multiple identical status lines are allowed;
    conflicting statuses fail closed.
    """

    if not isinstance(output, str):
        raise MalformedATPOutput("ATP output must be text")
    matches = _SZS_STATUS.findall(output)
    if not matches:
        raise MalformedATPOutput("ATP output has no SZS status line")
    unknown = sorted({value for value in matches if value not in SZSStatus._value2member_map_})
    if unknown:
        raise MalformedATPOutput(f"unsupported SZS status: {', '.join(unknown)}")
    statuses = {SZSStatus(value) for value in matches}
    if len(statuses) != 1:
        raise MalformedATPOutput(
            "ATP output contains conflicting SZS statuses: "
            + ", ".join(sorted(status.value for status in statuses))
        )
    return next(iter(statuses))


def _source_from_request(
    request: BackendRequest, accepted_formats: frozenset[str]
) -> tuple[str, ATPSourceBinding]:
    if not isinstance(request, BackendRequest):
        raise ATPAdapterError("request must be a BackendRequest")
    payload = request.payload.to_dict()
    source = payload.get("tptp") if "tptp" in payload else payload.get("source")
    source_format = payload.get(
        "encoding", "tptp" if "tptp" in payload else request.logic_family
    )
    if not isinstance(source_format, str):
        raise ATPAdapterError("request encoding must be a string")
    normalized_format = source_format.strip().lower()
    if normalized_format not in accepted_formats:
        raise ATPAdapterError(
            f"request encoding {source_format!r} is not one of "
            f"{', '.join(sorted(accepted_formats))}"
        )
    normalized_source = _text(source, "request source")
    if len(normalized_source.encode("utf-8")) > request.bounds.max_output_bytes:
        raise ATPAdapterError("request source exceeds the canonical byte bound")
    return (
        normalized_source,
        ATPSourceBinding.bind(request, normalized_source, normalized_format),
    )


def _validate_request(
    request: BackendRequest,
    *,
    backend_id: str,
    aliases: frozenset[str],
    capabilities: BackendCapabilities,
) -> None:
    if not isinstance(request, BackendRequest):
        raise ATPAdapterError("request must be a BackendRequest")
    if request.requested_backend_id and request.requested_backend_id not in {
        backend_id,
        *aliases,
    }:
        raise ATPAdapterError(
            f"request targets {request.requested_backend_id!r}, not {backend_id!r}"
        )
    if not capabilities.supports(request.logic_family, request.query_kind):
        raise ATPAdapterError(
            f"{backend_id} does not support {request.logic_family}/"
            f"{request.query_kind.value}"
        )


def _usage_from_process(process: ToolRunResult) -> ResourceUsage:
    output_bytes = len(process.stdout.encode("utf-8")) + len(
        process.stderr.encode("utf-8")
    )
    return ResourceUsage(
        elapsed_ms=max(0, round(process.elapsed_seconds * 1000)),
        output_bytes=output_bytes,
    )


def _result_id(backend_id: str, request: BackendRequest) -> str:
    return f"result:{backend_id}:{request.digest[:24]}"


def _result_metadata(
    *,
    binding: ATPSourceBinding,
    process: ToolRunResult | None = None,
    szs_status: SZSStatus | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "adapter_interface": ATP_COMPATIBILITY_BACKENDS_VERSION,
        "source_binding": binding.to_dict(),
    }
    if process is not None:
        metadata["process"] = {
            "cancelled": process.cancelled,
            "command": list(process.command),
            "error": process.error,
            "output_truncated": process.output_truncated,
            "returncode": process.returncode,
            "resource_exhausted": process.resource_exhausted,
            "stderr_digest": _content_digest(process.stderr),
            "stdout_digest": _content_digest(process.stdout),
            "timed_out": process.timed_out,
            "unavailable": process.unavailable,
            "workspace_cleaned": process.workspace_cleaned,
        }
    if szs_status is not None:
        metadata["szs_status"] = szs_status.value
    if extra:
        metadata.update(extra)
    return metadata


def _build_result(
    *,
    request: BackendRequest,
    backend_id: str,
    backend_version: str,
    binding: ATPSourceBinding,
    status: ResultStatus,
    usage: ResourceUsage,
    proof_object: ATPProofObject | None = None,
    countermodel: ATPCountermodel | None = None,
    diagnostics: Sequence[str] = (),
    reason: str = "",
    process: ToolRunResult | None = None,
    szs_status: SZSStatus | None = None,
    candidate_kind: str = "",
    extra_metadata: Mapping[str, Any] | None = None,
) -> TypedBackendResult:
    verified_proof = proof_object is not None and proof_object.verified
    validated_model = countermodel is not None and countermodel.validated
    if proof_object is not None and not proof_object.is_bound_to(binding):
        raise ATPAdapterError("proof reconstructor returned an artifact for another source")
    if countermodel is not None and not countermodel.is_bound_to(binding):
        raise ATPAdapterError("countermodel parser returned an artifact for another source")

    metadata = _result_metadata(
        binding=binding,
        process=process,
        szs_status=szs_status,
        extra=extra_metadata,
    )
    common: dict[str, Any] = {
        "assumptions": request.assumption_ids,
        "backend_id": backend_id,
        "backend_version": backend_version,
        "bounds": request.bounds,
        "diagnostics": tuple(diagnostics),
        "metadata": metadata,
        "reason": reason,
        "result_id": _result_id(backend_id, request),
        "status": status,
        "usage": usage,
    }
    if candidate_kind:
        witness: dict[str, Any] = {"candidate_kind": candidate_kind}
        if proof_object is not None:
            witness["proof_object"] = proof_object.to_dict(include_content=False)
        if countermodel is not None:
            witness["countermodel"] = countermodel.to_dict()
        return CandidateResult(
            authority=ResultAuthority.CANDIDATE,
            translation_ceiling=EvidenceAuthority.ADVISORY,
            witness=witness,
            **common,
        )

    if request.query_kind is QueryKind.THEOREM_PROOF:
        if status is ResultStatus.PROVED and not verified_proof:
            raise ATPAdapterError("proved theorem results require a verified proof object")
        if status is ResultStatus.DISPROVED and not validated_model:
            raise ATPAdapterError(
                "disproved theorem results require a validated countermodel"
            )
        return TheoremResult(
            authority=ResultAuthority.THEOREM,
            translation_ceiling=(
                EvidenceAuthority.INDEPENDENTLY_CHECKABLE
                if status is ResultStatus.PROVED
                else EvidenceAuthority.BOUNDED
            ),
            witness=(
                proof_object.to_dict()
                if proof_object is not None
                else countermodel.to_dict()
                if countermodel is not None
                else {}
            ),
            **common,
        )
    if request.query_kind is QueryKind.SATISFIABILITY:
        if status is ResultStatus.UNSATISFIABLE and not verified_proof:
            raise ATPAdapterError(
                "unsatisfiable results require a verified proof object"
            )
        if status is ResultStatus.SATISFIABLE and not validated_model:
            raise ATPAdapterError(
                "satisfiable results require a validated model"
            )
        return SatisfiabilityResult(
            authority=ResultAuthority.SATISFIABILITY,
            translation_ceiling=(
                EvidenceAuthority.INDEPENDENTLY_CHECKABLE
                if status is ResultStatus.UNSATISFIABLE
                else EvidenceAuthority.BOUNDED
            ),
            witness=(
                proof_object.to_dict()
                if proof_object is not None
                else countermodel.to_dict()
                if countermodel is not None
                else {}
            ),
            **common,
        )
    raise ATPAdapterError(f"unsupported ATP query kind: {request.query_kind.value}")


class TPTPBackend:
    """Bounded external TPTP backend shared by Vampire and E."""

    interface_version: Final = ATP_COMPATIBILITY_BACKENDS_VERSION
    accepted_source_formats: Final = frozenset({"tptp", "tptp-fof", "tptp-cnf"})
    aliases: frozenset[str] = frozenset()

    def __init__(
        self,
        *,
        backend_id: str,
        backend_version: str,
        executable: str,
        runner: BoundedToolRunner | None = None,
        proof_reconstructor: ProofReconstructor | None = None,
        countermodel_parser: CountermodelParser | None = None,
        logic_families: Sequence[str] = (
            "first_order",
            "fol",
            "dcec",
            "cec_dcec",
            "tdfol",
        ),
    ) -> None:
        self.backend_id = _text(backend_id, "backend_id")
        self.backend_version = _text(backend_version, "backend_version")
        self.executable = _text(executable, "executable")
        self._runner = runner or BoundedToolRunner()
        if not isinstance(self._runner, BoundedToolRunner):
            raise ATPAdapterError("runner must be a BoundedToolRunner")
        if proof_reconstructor is not None and not callable(proof_reconstructor):
            raise ATPAdapterError("proof_reconstructor must be callable")
        if countermodel_parser is not None and not callable(countermodel_parser):
            raise ATPAdapterError("countermodel_parser must be callable")
        self._proof_reconstructor = proof_reconstructor
        self._countermodel_parser = countermodel_parser
        self.capabilities = BackendCapabilities(
            logic_families=tuple(logic_families),
            query_kinds=(QueryKind.THEOREM_PROOF, QueryKind.SATISFIABILITY),
            deterministic=False,
        )

    def supports(self, logic_family: str, query_kind: QueryKind) -> bool:
        return self.capabilities.supports(logic_family, query_kind)

    def is_available(self) -> bool:
        return self._runner.is_available(self.executable)

    def _argv(self, bounds: ExecutionBounds) -> tuple[str, ...]:
        raise NotImplementedError

    def _tool_request(self, source: str, bounds: ExecutionBounds) -> ToolRunRequest:
        max_workspace_bytes = max(
            bounds.max_output_bytes * 2,
            len(source.encode("utf-8")) + bounds.max_output_bytes + 1024,
        )
        return ToolRunRequest(
            argv=self._argv(bounds),
            limits=ToolRunLimits(
                timeout_seconds=bounds.timeout_ms / 1000,
                cpu_seconds=bounds.timeout_ms / 1000,
                memory_bytes=bounds.max_memory_bytes,
                max_output_bytes=bounds.max_output_bytes,
                max_input_bytes=bounds.max_output_bytes,
                max_workspace_bytes=max_workspace_bytes,
            ),
            input_files={"problem.p": source},
        )

    def run(
        self,
        request: BackendRequest,
        *,
        cancellation: CancellationSignal | Any | None = None,
    ) -> ATPAdapterOutcome:
        _validate_request(
            request,
            backend_id=self.backend_id,
            aliases=self.aliases,
            capabilities=self.capabilities,
        )
        source, binding = _source_from_request(
            request, self.accepted_source_formats
        )
        process = self._runner.run(
            self._tool_request(source, request.bounds), cancellation=cancellation
        )
        usage = _usage_from_process(process)

        operational_status: ResultStatus | None = None
        reason = process.error or process.termination_reason
        if process.unavailable:
            operational_status = ResultStatus.UNAVAILABLE
        elif process.cancelled:
            operational_status = ResultStatus.ERROR
            reason = reason or "ATP execution was cancelled"
        elif process.timed_out:
            operational_status = ResultStatus.TIMEOUT
            reason = reason or "ATP execution exceeded its wall-clock bound"
        elif process.resource_exhausted or process.output_truncated:
            operational_status = ResultStatus.ERROR
            reason = reason or "ATP execution exceeded a resource or output bound"
        elif process.returncode != 0:
            operational_status = ResultStatus.ERROR
            reason = reason or (
                "ATP process did not report an exit status"
                if process.returncode is None
                else f"ATP process exited with status {process.returncode}"
            )

        if operational_status is not None:
            result = _build_result(
                request=request,
                backend_id=self.backend_id,
                backend_version=self.backend_version,
                binding=binding,
                status=operational_status,
                usage=usage,
                diagnostics=(reason,) if reason else (),
                reason=reason,
                process=process,
            )
            return ATPAdapterOutcome(
                request_digest=request.digest,
                source_binding=binding,
                result=result,
            )

        combined_output = "\n".join(
            part for part in (process.stdout, process.stderr) if part
        )
        try:
            szs_status = parse_szs_status(combined_output)
        except MalformedATPOutput as error:
            message = str(error)
            result = _build_result(
                request=request,
                backend_id=self.backend_id,
                backend_version=self.backend_version,
                binding=binding,
                status=ResultStatus.MALFORMED,
                usage=usage,
                diagnostics=(message,),
                reason=message,
                process=process,
            )
            return ATPAdapterOutcome(
                request_digest=request.digest,
                source_binding=binding,
                result=result,
            )

        proof_object = (
            self._proof_reconstructor(binding, process, szs_status)
            if self._proof_reconstructor is not None
            and szs_status
            in {
                SZSStatus.THEOREM,
                SZSStatus.UNSATISFIABLE,
                SZSStatus.CONTRADICTORY_AXIOMS,
            }
            else None
        )
        if (
            proof_object is None
            and szs_status
            in {
                SZSStatus.THEOREM,
                SZSStatus.UNSATISFIABLE,
                SZSStatus.CONTRADICTORY_AXIOMS,
            }
        ):
            # Preserve the bounded ATP evidence for later reconstruction while
            # keeping its authority explicitly unverified.
            proof_object = ATPProofObject(
                request_digest=binding.request_digest,
                source_digest=binding.source_digest,
                proof_format="tptp-atp-output",
                content=combined_output,
                metadata={
                    "backend_id": self.backend_id,
                    "szs_status": szs_status.value,
                },
            )
        countermodel = (
            self._countermodel_parser(binding, process, szs_status)
            if self._countermodel_parser is not None
            and szs_status
            in {SZSStatus.SATISFIABLE, SZSStatus.COUNTER_SATISFIABLE}
            else None
        )
        if proof_object is not None and not isinstance(proof_object, ATPProofObject):
            raise ATPAdapterError(
                "proof_reconstructor must return ATPProofObject or None"
            )
        if countermodel is not None and not isinstance(countermodel, ATPCountermodel):
            raise ATPAdapterError(
                "countermodel_parser must return ATPCountermodel or None"
            )

        positive_proof = szs_status in {
            SZSStatus.THEOREM,
            SZSStatus.UNSATISFIABLE,
            SZSStatus.CONTRADICTORY_AXIOMS,
        }
        positive_model = szs_status in {
            SZSStatus.SATISFIABLE,
            SZSStatus.COUNTER_SATISFIABLE,
        }
        candidate_kind = ""
        if positive_proof and (proof_object is None or not proof_object.verified):
            candidate_kind = "unreconstructed_atp_proof"
        elif positive_model and (countermodel is None or not countermodel.validated):
            candidate_kind = "unvalidated_atp_model"

        if candidate_kind:
            result_status = ResultStatus.CANDIDATE
        elif request.query_kind is QueryKind.THEOREM_PROOF:
            result_status = (
                ResultStatus.PROVED
                if positive_proof
                else ResultStatus.DISPROVED
                if positive_model
                else ResultStatus.TIMEOUT
                if szs_status
                in {SZSStatus.TIMEOUT, SZSStatus.RESOURCE_OUT}
                else ResultStatus.UNKNOWN
            )
        else:
            result_status = (
                ResultStatus.UNSATISFIABLE
                if positive_proof
                else ResultStatus.SATISFIABLE
                if positive_model
                else ResultStatus.TIMEOUT
                if szs_status
                in {SZSStatus.TIMEOUT, SZSStatus.RESOURCE_OUT}
                else ResultStatus.UNKNOWN
            )

        result = _build_result(
            request=request,
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            binding=binding,
            status=result_status,
            usage=usage,
            proof_object=proof_object,
            countermodel=countermodel,
            reason=(
                "ATP evidence requires reconstruction or model validation"
                if candidate_kind
                else ""
            ),
            process=process,
            szs_status=szs_status,
            candidate_kind=candidate_kind,
        )
        return ATPAdapterOutcome(
            request_digest=request.digest,
            source_binding=binding,
            result=result,
            proof_object=proof_object,
            countermodel=countermodel,
        )


class VampireBackend(TPTPBackend):
    """Canonical bounded adapter for Vampire."""

    aliases = frozenset({"atp.vampire"})

    def __init__(
        self,
        *,
        executable: str = "vampire",
        backend_version: str = "unknown",
        runner: BoundedToolRunner | None = None,
        proof_reconstructor: ProofReconstructor | None = None,
        countermodel_parser: CountermodelParser | None = None,
    ) -> None:
        super().__init__(
            backend_id="vampire",
            backend_version=backend_version,
            executable=executable,
            runner=runner,
            proof_reconstructor=proof_reconstructor,
            countermodel_parser=countermodel_parser,
        )

    def _argv(self, bounds: ExecutionBounds) -> tuple[str, ...]:
        seconds = max(1, (bounds.timeout_ms + 999) // 1000)
        return (
            self.executable,
            "{workspace}/problem.p",
            f"--time_limit={seconds}",
            "--output_mode=tptp",
        )


class EProverBackend(TPTPBackend):
    """Canonical bounded adapter for E."""

    aliases = frozenset({"eprover", "atp.e"})

    def __init__(
        self,
        *,
        executable: str = "eprover",
        backend_version: str = "unknown",
        runner: BoundedToolRunner | None = None,
        proof_reconstructor: ProofReconstructor | None = None,
        countermodel_parser: CountermodelParser | None = None,
    ) -> None:
        super().__init__(
            backend_id="e",
            backend_version=backend_version,
            executable=executable,
            runner=runner,
            proof_reconstructor=proof_reconstructor,
            countermodel_parser=countermodel_parser,
        )

    def _argv(self, bounds: ExecutionBounds) -> tuple[str, ...]:
        seconds = max(1, (bounds.timeout_ms + 999) // 1000)
        return (
            self.executable,
            f"--cpu-limit={seconds}",
            "--proof-object",
            "{workspace}/problem.p",
        )


class NativeLegacyBackend:
    """Strict adapter for an injected DCEC or TDFOL native bridge."""

    interface_version: Final = ATP_COMPATIBILITY_BACKENDS_VERSION
    aliases: frozenset[str] = frozenset()

    def __init__(
        self,
        *,
        backend_id: str,
        backend_version: str,
        source_format: str,
        runner: NativeProverRunner,
        reviewed_outcomes: Sequence[NativeProverStatus | str] = tuple(
            NativeProverStatus
        ),
    ) -> None:
        self.backend_id = _text(backend_id, "backend_id")
        self.backend_version = _text(backend_version, "backend_version")
        self.source_format = _text(source_format, "source_format").lower()
        if not callable(runner):
            raise ATPAdapterError("native runner must be callable")
        self._native_runner = runner
        try:
            normalized_reviewed = tuple(
                item
                if isinstance(item, NativeProverStatus)
                else NativeProverStatus(item)
                for item in reviewed_outcomes
            )
        except (TypeError, ValueError) as error:
            raise ATPAdapterError("reviewed_outcomes contains an invalid status") from error
        if len(normalized_reviewed) != len(set(normalized_reviewed)):
            raise ATPAdapterError("reviewed_outcomes must not contain duplicates")
        self._reviewed_outcomes = frozenset(normalized_reviewed)
        self.capabilities = BackendCapabilities(
            logic_families=(self.source_format,),
            query_kinds=(QueryKind.THEOREM_PROOF, QueryKind.SATISFIABILITY),
            deterministic=True,
        )

    def supports(self, logic_family: str, query_kind: QueryKind) -> bool:
        return self.capabilities.supports(logic_family, query_kind)

    def is_available(self) -> bool:
        """An explicitly injected native bridge is available by construction."""

        return True

    def run(self, request: BackendRequest) -> ATPAdapterOutcome:
        _validate_request(
            request,
            backend_id=self.backend_id,
            aliases=self.aliases,
            capabilities=self.capabilities,
        )
        source, binding = _source_from_request(
            request, frozenset({self.source_format})
        )
        native = self._native_runner(
            NativeProverInvocation(
                request=request,
                source_binding=binding,
                source=source,
            )
        )
        if not isinstance(native, NativeProverResult):
            raise ATPAdapterError(
                "native runner must return NativeProverResult; duck-typed "
                "or boolean success values are not accepted"
            )
        if not native.is_bound_to(binding):
            raise ATPAdapterError("native result is not bound to this request/source")
        if native.proof_object is not None and not native.proof_object.is_bound_to(
            binding
        ):
            raise ATPAdapterError("native proof object is not bound to this source")
        if native.countermodel is not None and not native.countermodel.is_bound_to(
            binding
        ):
            raise ATPAdapterError("native countermodel is not bound to this source")

        usage = ResourceUsage(
            elapsed_ms=native.elapsed_ms,
            steps=native.steps,
            peak_memory_bytes=native.peak_memory_bytes,
            output_bytes=native.output_bytes,
        )
        exceeded = usage.exceeds(request.bounds)
        candidate_kind = ""
        if exceeded:
            canonical_status = (
                ResultStatus.TIMEOUT
                if "timeout_ms" in exceeded
                else ResultStatus.ERROR
            )
        elif native.status not in self._reviewed_outcomes and native.status in {
            NativeProverStatus.PROVED,
            NativeProverStatus.DISPROVED,
            NativeProverStatus.SATISFIABLE,
            NativeProverStatus.UNSATISFIABLE,
        }:
            canonical_status = ResultStatus.CANDIDATE
            candidate_kind = "unreviewed_legacy_behavior"
        elif native.status in {
            NativeProverStatus.PROVED,
            NativeProverStatus.UNSATISFIABLE,
        } and (
            native.proof_object is None or not native.proof_object.verified
        ):
            canonical_status = ResultStatus.CANDIDATE
            candidate_kind = "unverified_native_proof"
        elif native.status in {
            NativeProverStatus.DISPROVED,
            NativeProverStatus.SATISFIABLE,
        } and (
            native.countermodel is None or not native.countermodel.validated
        ):
            canonical_status = ResultStatus.CANDIDATE
            candidate_kind = "unvalidated_native_model"
        elif request.query_kind is QueryKind.THEOREM_PROOF:
            canonical_status = {
                NativeProverStatus.PROVED: ResultStatus.PROVED,
                NativeProverStatus.UNSATISFIABLE: ResultStatus.PROVED,
                NativeProverStatus.DISPROVED: ResultStatus.DISPROVED,
                NativeProverStatus.SATISFIABLE: ResultStatus.DISPROVED,
                NativeProverStatus.UNKNOWN: ResultStatus.UNKNOWN,
                NativeProverStatus.TIMEOUT: ResultStatus.TIMEOUT,
                NativeProverStatus.UNSUPPORTED: ResultStatus.UNSUPPORTED,
                NativeProverStatus.ERROR: ResultStatus.ERROR,
            }[native.status]
        else:
            canonical_status = {
                NativeProverStatus.PROVED: ResultStatus.UNSATISFIABLE,
                NativeProverStatus.UNSATISFIABLE: ResultStatus.UNSATISFIABLE,
                NativeProverStatus.DISPROVED: ResultStatus.SATISFIABLE,
                NativeProverStatus.SATISFIABLE: ResultStatus.SATISFIABLE,
                NativeProverStatus.UNKNOWN: ResultStatus.UNKNOWN,
                NativeProverStatus.TIMEOUT: ResultStatus.TIMEOUT,
                NativeProverStatus.UNSUPPORTED: ResultStatus.UNSUPPORTED,
                NativeProverStatus.ERROR: ResultStatus.ERROR,
            }[native.status]

        diagnostics = tuple(native.diagnostics)
        if exceeded:
            diagnostics += (
                "native result exceeded canonical bounds: " + ", ".join(exceeded),
            )
        reason = "; ".join(diagnostics)
        result = _build_result(
            request=request,
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            binding=binding,
            status=canonical_status,
            usage=usage,
            proof_object=native.proof_object,
            countermodel=native.countermodel,
            diagnostics=diagnostics,
            reason=reason,
            candidate_kind=candidate_kind,
            extra_metadata={
                "legacy": {
                    "metadata": native.metadata.to_dict(),
                    "native_result_type": native.native_result_type,
                    "native_status": native.status.value,
                }
            },
        )
        receipt = LegacyCompatibilityReceipt(
            request_digest=request.digest,
            source_digest=binding.source_digest,
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            native_result_type=native.native_result_type,
            native_status=native.status,
            canonical_result_id=result.result_id,
            canonical_result_digest=result.digest,
            reviewed_behavior=native.status in self._reviewed_outcomes,
        )
        return ATPAdapterOutcome(
            request_digest=request.digest,
            source_binding=binding,
            result=result,
            proof_object=native.proof_object,
            countermodel=native.countermodel,
            compatibility_receipt=receipt,
        )


class DCECBackend(NativeLegacyBackend):
    """Canonical adapter boundary for the native DCEC prover family."""

    aliases = frozenset({"native.dcec", "legacy.dcec"})

    def __init__(
        self,
        runner: NativeProverRunner,
        *,
        backend_version: str = "unknown",
        reviewed_outcomes: Sequence[NativeProverStatus | str] = tuple(
            NativeProverStatus
        ),
    ) -> None:
        super().__init__(
            backend_id="dcec",
            backend_version=backend_version,
            source_format="dcec",
            runner=runner,
            reviewed_outcomes=reviewed_outcomes,
        )


class TDFOLBackend(NativeLegacyBackend):
    """Canonical adapter boundary for the native TDFOL prover family."""

    aliases = frozenset({"native.tdfol", "legacy.tdfol"})

    def __init__(
        self,
        runner: NativeProverRunner,
        *,
        backend_version: str = "unknown",
        reviewed_outcomes: Sequence[NativeProverStatus | str] = tuple(
            NativeProverStatus
        ),
    ) -> None:
        super().__init__(
            backend_id="tdfol",
            backend_version=backend_version,
            source_format="tdfol",
            runner=runner,
            reviewed_outcomes=reviewed_outcomes,
        )


# Descriptive compatibility spellings used by early objective drafts.
VampireATPBackend = VampireBackend
EATPBackend = EProverBackend
DCECProverBackend = DCECBackend
TDFOLProverBackend = TDFOLBackend
LegacyProverAdapter = NativeLegacyBackend
VampireAdapter = VampireBackend
EProverAdapter = EProverBackend
DCECAdapter = DCECBackend
TDFOLAdapter = TDFOLBackend


__all__ = [
    "ATPAdapterError",
    "ATPAdapterOutcome",
    "ATPCountermodel",
    "ATPProofObject",
    "ATPSourceBinding",
    "DCECBackend",
    "DCECAdapter",
    "DCECProverBackend",
    "EATPBackend",
    "EProverBackend",
    "EProverAdapter",
    "LegacyCompatibilityReceipt",
    "LegacyProverAdapter",
    "MalformedATPOutput",
    "NativeLegacyBackend",
    "NativeProverInvocation",
    "NativeProverResult",
    "NativeProverStatus",
    "SZSStatus",
    "TDFOLBackend",
    "TDFOLAdapter",
    "TDFOLProverBackend",
    "TPTPBackend",
    "VampireATPBackend",
    "VampireAdapter",
    "VampireBackend",
    "parse_szs_status",
    "ATP_ADAPTER_VERSION",
    "ATP_COMPATIBILITY_BACKENDS_VERSION",
]
