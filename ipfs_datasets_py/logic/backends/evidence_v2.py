"""Provider execution and evidence-replay receipt contracts (Wave-2).

Interfaces (LFP2-008):

* ``ProviderExecutionReceipt@2`` — pinned launch/tool/output/result identities
  bound to BackendRequest@2 and CompiledLogicArtifact@1
* ``EvidenceReplayReceipt@1`` — replay disposition bound to an execution
  receipt and decoded evidence identity

Admission is fail-closed on the v2 route:

* metadata-only records cannot claim execution
* mock records cannot claim execution or replay
* execution receipts require compiled-artifact and request lineage
* replay receipts require an executable source receipt and explicit
  disposition
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.artifacts_v2 import (
    ArtifactLineageError,
    CompiledLogicArtifact,
    ParsedTargetArtifact,
)
from ipfs_datasets_py.logic.backends.requests_v2 import (
    BackendRequestV2,
    CrossNamespaceRequestError,
    MissingBoundsError,
    RequestAdmissionError,
    RequestAuthorityCeiling,
    RequestBounds,
    RequestV2Error,
    _check_authority_overclaim,
    _coerce_authority,
    _coerce_identity,
    _forbid_metadata_routing,
    _identity_dict,
    _status_value,
)
from ipfs_datasets_py.logic.families.namespaces import (
    LogicIdentity,
    NamespaceKind,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    SyntaxContractError,
    _freeze_mapping,
    _non_negative_int,
    _record_id,
    _require_mapping,
    _sha256_hex,
    _text,
    _thaw_mapping,
    canonical_json_bytes,
    content_sha256,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

PROVIDER_EXECUTION_RECEIPT_V2_INTERFACE: Final = "ProviderExecutionReceipt@2"
EVIDENCE_REPLAY_RECEIPT_INTERFACE: Final = "EvidenceReplayReceipt@1"

PROVIDER_EXECUTION_RECEIPT_V2_SCHEMA_VERSION: Final = "provider-execution-receipt/v2"
EVIDENCE_REPLAY_RECEIPT_SCHEMA_VERSION: Final = "evidence-replay-receipt/v1"
EVIDENCE_V2_MODULE_VERSION: Final = "1.0.0"

# Legacy dual-read marker (not admitted for new execution claims).
LEGACY_PROVIDER_EXECUTION_RECEIPT_INTERFACE: Final = "ProviderExecutionReceipt@1"
LEGACY_PROVIDER_EXECUTION_RECEIPT_SCHEMA_VERSION: Final = (
    "provider-execution-receipt/v1"
)

_TOOL_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._+:/-]{0,255}$")

_FORBIDDEN_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "payload",
        "raw_formula",
        "raw_source",
        "target_source",
        "raw_target",
        "raw_result",
        "logic_family",
        "family_string",
        "opaque_extension",
        "arbitrary_payload",
        "mock_execution",
        "fake_replay",
        "claimed_execution",
        "claimed_replay",
    }
)


class EvidenceV2Error(SyntaxContractError):
    """Raised when a v2 execution or replay receipt is malformed."""


class EvidenceLineageError(EvidenceV2Error, ArtifactLineageError):
    """Raised when receipt lineage to request/compiled/parsed artifacts breaks."""


class ExecutionClaimError(EvidenceV2Error, RequestAdmissionError):
    """Raised when a non-executable record claims execution on the v2 route."""


class ReplayClaimError(EvidenceV2Error, RequestAdmissionError):
    """Raised when a non-replayable record claims replay on the v2 route."""


class ExecutionRecordKind(str, Enum):
    """Closed set of execution record kinds.

    Only ``live``, ``pinned_tool``, and ``hermetic_fixture`` may claim
    execution through ProviderExecutionReceipt@2.  ``metadata_only`` and
    ``mock`` are admissible as *records* but never as execution or replay
    claims on the v2 route.
    """

    LIVE = "live"
    PINNED_TOOL = "pinned_tool"
    HERMETIC_FIXTURE = "hermetic_fixture"
    METADATA_ONLY = "metadata_only"
    MOCK = "mock"


# Record kinds that may set execution_claimed=True.
_EXECUTABLE_RECORD_KINDS: Final[frozenset[ExecutionRecordKind]] = frozenset(
    {
        ExecutionRecordKind.LIVE,
        ExecutionRecordKind.PINNED_TOOL,
        ExecutionRecordKind.HERMETIC_FIXTURE,
    }
)

# Record kinds that may never seed a successful replay claim.
_NON_REPLAY_SOURCE_KINDS: Final[frozenset[ExecutionRecordKind]] = frozenset(
    {
        ExecutionRecordKind.METADATA_ONLY,
        ExecutionRecordKind.MOCK,
    }
)


class ExecutionOutcome(str, Enum):
    """Closed set of provider execution outcomes."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    REJECTED = "rejected"
    UNSUPPORTED = "unsupported"


class ReplayDisposition(str, Enum):
    """Closed set of evidence replay dispositions.

    ``replayed`` is the only disposition that may set ``replay_claimed``.
    ``non_replayable``, ``not_attempted``, and ``explicit_skip`` document
    why replay did not produce a claim.
    """

    REPLAYED = "replayed"
    NON_REPLAYABLE = "non_replayable"
    NOT_ATTEMPTED = "not_attempted"
    EXPLICIT_SKIP = "explicit_skip"
    MISMATCH = "mismatch"


def _coerce_record_kind(
    value: object, field_name: str = "record_kind"
) -> ExecutionRecordKind:
    if isinstance(value, ExecutionRecordKind):
        return value
    text = _text(value, field_name, maximum=64)
    try:
        return ExecutionRecordKind(text)
    except ValueError as error:
        allowed = ", ".join(item.value for item in ExecutionRecordKind)
        raise EvidenceV2Error(
            f"{field_name} must be one of: {allowed}; got {value!r}"
        ) from error


def _coerce_outcome(
    value: object, field_name: str = "outcome"
) -> ExecutionOutcome:
    if isinstance(value, ExecutionOutcome):
        return value
    text = _text(value, field_name, maximum=64)
    try:
        return ExecutionOutcome(text)
    except ValueError as error:
        allowed = ", ".join(item.value for item in ExecutionOutcome)
        raise EvidenceV2Error(
            f"{field_name} must be one of: {allowed}; got {value!r}"
        ) from error


def _coerce_disposition(
    value: object, field_name: str = "disposition"
) -> ReplayDisposition:
    if isinstance(value, ReplayDisposition):
        return value
    text = _text(value, field_name, maximum=64)
    try:
        return ReplayDisposition(text)
    except ValueError as error:
        allowed = ", ".join(item.value for item in ReplayDisposition)
        raise EvidenceV2Error(
            f"{field_name} must be one of: {allowed}; got {value!r}"
        ) from error


def _identity_or_error(
    value: object,
    expected: NamespaceKind,
    field_name: str,
) -> LogicIdentity:
    try:
        return _coerce_identity(value, expected, field_name)
    except CrossNamespaceRequestError:
        raise
    except RequestV2Error as error:
        message = str(error)
        if "requires namespace" in message:
            raise CrossNamespaceRequestError(message) from error
        raise EvidenceV2Error(message) from error


def _coerce_request_bounds(
    value: object, field_name: str = "bounds"
) -> RequestBounds:
    if value is None:
        raise MissingBoundsError(
            f"{field_name} are required on ProviderExecutionReceipt@2"
        )
    if isinstance(value, RequestBounds):
        return value
    try:
        return RequestBounds.from_dict(_require_mapping(value, field_name))
    except MissingBoundsError:
        raise
    except RequestV2Error as error:
        raise EvidenceV2Error(str(error)) from error


def _tool_identity(value: object, field_name: str) -> str:
    text = _text(value, field_name, maximum=256)
    if not _TOOL_ID_RE.fullmatch(text):
        raise EvidenceV2Error(
            f"{field_name} must be a tool/launch identity; got {text!r}"
        )
    return text


def _forbid_evidence_metadata(metadata: Mapping[str, Any], field_name: str) -> None:
    try:
        _forbid_metadata_routing(metadata, field_name)
    except RequestV2Error as error:
        raise EvidenceV2Error(str(error)) from error
    for key in metadata:
        if key in _FORBIDDEN_METADATA_KEYS:
            raise ExecutionClaimError(
                f"{field_name} rejects free-form claim key {key!r}; "
                "execution and replay claims use typed receipt fields only"
            )


def _optional_sha256(value: object, field_name: str) -> str:
    if value is None or value == "":
        return ""
    return _sha256_hex(value, field_name)


def _bool_flag(value: object, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise EvidenceV2Error(f"{field_name} must be a boolean")


# ---------------------------------------------------------------------------
# ProviderExecutionReceipt@2
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProviderExecutionReceiptV2:
    """Pinned provider execution receipt for the v2 route.

    Interface: ``ProviderExecutionReceipt@2``.

    Binds launch, tool, output, and result identities to BackendRequest@2
    and CompiledLogicArtifact@1.  ``execution_claimed`` may only be true
    when ``record_kind`` is an executable kind (live / pinned_tool /
    hermetic_fixture).  Metadata-only and mock records are admitted as
    non-claiming records only.
    """

    receipt_id: str
    request_id: str
    request_digest: str
    compiled_artifact_id: str
    compiled_artifact_digest: str
    provider: LogicIdentity | Mapping[str, Any] | str
    evidence_kind: LogicIdentity | Mapping[str, Any] | str
    launch_id: str
    tool_id: str
    output_digest: str
    result_digest: str
    bounds: RequestBounds | Mapping[str, Any]
    record_kind: ExecutionRecordKind | str = ExecutionRecordKind.LIVE
    execution_claimed: bool = True
    outcome: ExecutionOutcome | str = ExecutionOutcome.SUCCEEDED
    parsed_target_id: str = ""
    parsed_target_digest: str = ""
    target_digest: str = ""
    toolchain_id: str = ""
    exit_code: int | None = None
    duration_ms: int = 0
    authority_ceiling: RequestAuthorityCeiling | str = RequestAuthorityCeiling.BOUNDED
    content_digest: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = PROVIDER_EXECUTION_RECEIPT_V2_SCHEMA_VERSION

    interface: ClassVar[str] = PROVIDER_EXECUTION_RECEIPT_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", _record_id(self.receipt_id, "receipt_id")
        )
        object.__setattr__(
            self, "request_id", _record_id(self.request_id, "request_id")
        )
        object.__setattr__(
            self, "request_digest", _sha256_hex(self.request_digest, "request_digest")
        )
        object.__setattr__(
            self,
            "compiled_artifact_id",
            _record_id(self.compiled_artifact_id, "compiled_artifact_id"),
        )
        object.__setattr__(
            self,
            "compiled_artifact_digest",
            _sha256_hex(self.compiled_artifact_digest, "compiled_artifact_digest"),
        )
        object.__setattr__(
            self,
            "provider",
            _identity_or_error(self.provider, NamespaceKind.PROVIDER, "provider"),
        )
        object.__setattr__(
            self,
            "evidence_kind",
            _identity_or_error(
                self.evidence_kind, NamespaceKind.EVIDENCE, "evidence_kind"
            ),
        )
        object.__setattr__(self, "launch_id", _tool_identity(self.launch_id, "launch_id"))
        object.__setattr__(self, "tool_id", _tool_identity(self.tool_id, "tool_id"))
        object.__setattr__(
            self, "output_digest", _sha256_hex(self.output_digest, "output_digest")
        )
        object.__setattr__(
            self, "result_digest", _sha256_hex(self.result_digest, "result_digest")
        )

        bounds = _coerce_request_bounds(self.bounds, "bounds")
        object.__setattr__(self, "bounds", bounds)

        record_kind = _coerce_record_kind(self.record_kind)
        object.__setattr__(self, "record_kind", record_kind)

        execution_claimed = _bool_flag(self.execution_claimed, "execution_claimed")
        if execution_claimed and record_kind not in _EXECUTABLE_RECORD_KINDS:
            raise ExecutionClaimError(
                f"record_kind {record_kind.value!r} cannot claim execution "
                "through ProviderExecutionReceipt@2; metadata-only and mock "
                "records are non-claiming on the v2 route"
            )
        object.__setattr__(self, "execution_claimed", execution_claimed)

        outcome = _coerce_outcome(self.outcome)
        object.__setattr__(self, "outcome", outcome)

        if self.parsed_target_id:
            object.__setattr__(
                self,
                "parsed_target_id",
                _record_id(self.parsed_target_id, "parsed_target_id"),
            )
        if self.parsed_target_digest:
            object.__setattr__(
                self,
                "parsed_target_digest",
                _sha256_hex(self.parsed_target_digest, "parsed_target_digest"),
            )
        object.__setattr__(
            self, "target_digest", _optional_sha256(self.target_digest, "target_digest")
        )
        if self.toolchain_id:
            object.__setattr__(
                self, "toolchain_id", _record_id(self.toolchain_id, "toolchain_id")
            )

        if self.exit_code is not None:
            if isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int):
                raise EvidenceV2Error("exit_code must be an integer or null")
            if self.exit_code < -2147483648 or self.exit_code > 2147483647:
                raise EvidenceV2Error("exit_code out of int32 range")
        duration = _non_negative_int(self.duration_ms, "duration_ms")
        if duration > 86_400_000:
            raise EvidenceV2Error("duration_ms exceeds hard ceiling of 86400000")
        object.__setattr__(self, "duration_ms", duration)

        ceiling = _coerce_authority(self.authority_ceiling)
        _check_authority_overclaim(ceiling, self.evidence_kind)  # type: ignore[arg-type]
        object.__setattr__(self, "authority_ceiling", ceiling)

        metadata = _freeze_mapping(self.metadata, "metadata")
        _forbid_evidence_metadata(metadata, "metadata")
        object.__setattr__(self, "metadata", metadata)

        if self.schema_version != PROVIDER_EXECUTION_RECEIPT_V2_SCHEMA_VERSION:
            raise EvidenceV2Error(
                f"unsupported ProviderExecutionReceiptV2 schema_version "
                f"{self.schema_version!r}"
            )

        # Executable claims require full identity binding.
        if execution_claimed:
            if not self.compiled_artifact_id or not self.compiled_artifact_digest:
                raise ExecutionClaimError(
                    "execution-claimed ProviderExecutionReceipt@2 requires "
                    "compiled_artifact identity"
                )
            if not self.request_id or not self.request_digest:
                raise ExecutionClaimError(
                    "execution-claimed ProviderExecutionReceipt@2 requires "
                    "request identity"
                )
            if not self.output_digest or not self.result_digest:
                raise ExecutionClaimError(
                    "execution-claimed ProviderExecutionReceipt@2 requires "
                    "output_digest and result_digest"
                )
            if outcome is ExecutionOutcome.SUCCEEDED and not (
                self.parsed_target_id and self.parsed_target_digest
            ):
                raise ExecutionClaimError(
                    "successful execution claims require parsed_target "
                    "identity; unidentifiable raw results cannot claim "
                    "execution on the v2 route"
                )

        content = content_sha256(canonical_json_bytes(self._identity_payload()))
        if self.content_digest:
            provided = _sha256_hex(self.content_digest, "content_digest")
            if provided != content:
                raise EvidenceV2Error(
                    "content_digest does not match ProviderExecutionReceiptV2 "
                    "content"
                )
            object.__setattr__(self, "content_digest", provided)
        else:
            object.__setattr__(self, "content_digest", content)

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "authority_ceiling": _status_value(self.authority_ceiling),
            "bounds": self.bounds.to_dict(),  # type: ignore[union-attr]
            "compiled_artifact_digest": self.compiled_artifact_digest,
            "compiled_artifact_id": self.compiled_artifact_id,
            "duration_ms": self.duration_ms,
            "evidence_kind": _identity_dict(self.evidence_kind),  # type: ignore[arg-type]
            "execution_claimed": self.execution_claimed,
            "exit_code": self.exit_code,
            "interface": self.interface,
            "launch_id": self.launch_id,
            "outcome": _status_value(self.outcome),
            "output_digest": self.output_digest,
            "parsed_target_digest": self.parsed_target_digest,
            "parsed_target_id": self.parsed_target_id,
            "provider": _identity_dict(self.provider),  # type: ignore[arg-type]
            "receipt_id": self.receipt_id,
            "record_kind": _status_value(self.record_kind),
            "request_digest": self.request_digest,
            "request_id": self.request_id,
            "result_digest": self.result_digest,
            "schema_version": self.schema_version,
            "target_digest": self.target_digest,
            "tool_id": self.tool_id,
            "toolchain_id": self.toolchain_id,
        }

    @property
    def is_executable_claim(self) -> bool:
        return (
            self.execution_claimed
            and self.record_kind in _EXECUTABLE_RECORD_KINDS
        )

    def require_execution_claim(self) -> "ProviderExecutionReceiptV2":
        """Return self when this receipt may be treated as an execution claim."""

        if self.record_kind in _NON_REPLAY_SOURCE_KINDS:
            raise ExecutionClaimError(
                f"ProviderExecutionReceipt {self.receipt_id} has record_kind "
                f"{_status_value(self.record_kind)!r}; metadata-only and mock "
                "records cannot claim execution through the v2 route"
            )
        if not self.execution_claimed:
            raise ExecutionClaimError(
                f"ProviderExecutionReceipt {self.receipt_id} does not claim "
                "execution (execution_claimed=false)"
            )
        if not self.is_executable_claim:
            raise ExecutionClaimError(
                f"ProviderExecutionReceipt {self.receipt_id} is not an "
                "admitted executable claim"
            )
        return self

    def validate_against(
        self,
        *,
        request: BackendRequestV2 | None = None,
        compiled: CompiledLogicArtifact | None = None,
        parsed: ParsedTargetArtifact | None = None,
    ) -> None:
        """Cross-check lineage against parent request/compiled/parsed artifacts."""

        if request is not None:
            if not isinstance(request, BackendRequestV2):
                raise EvidenceV2Error("request must be BackendRequestV2")
            if request.request_id != self.request_id:
                raise EvidenceLineageError(
                    "request_id does not match BackendRequestV2.request_id"
                )
            if request.content_digest != self.request_digest:
                raise EvidenceLineageError(
                    "request_digest does not match BackendRequestV2.content_digest"
                )
        if compiled is not None:
            if not isinstance(compiled, CompiledLogicArtifact):
                raise EvidenceV2Error("compiled must be CompiledLogicArtifact")
            if compiled.artifact_id != self.compiled_artifact_id:
                raise EvidenceLineageError(
                    "compiled_artifact_id does not match CompiledLogicArtifact"
                )
            if compiled.content_digest != self.compiled_artifact_digest:
                raise EvidenceLineageError(
                    "compiled_artifact_digest does not match "
                    "CompiledLogicArtifact.content_digest"
                )
            if compiled.request_id != self.request_id:
                raise EvidenceLineageError(
                    "request_id does not match CompiledLogicArtifact.request_id"
                )
            if (
                self.target_digest
                and compiled.target_digest
                and self.target_digest != compiled.target_digest
            ):
                raise EvidenceLineageError(
                    "target_digest does not match CompiledLogicArtifact."
                    "target_digest"
                )
        if parsed is not None:
            if not isinstance(parsed, ParsedTargetArtifact):
                raise EvidenceV2Error("parsed must be ParsedTargetArtifact")
            if self.parsed_target_id and parsed.artifact_id != self.parsed_target_id:
                raise EvidenceLineageError(
                    "parsed_target_id does not match ParsedTargetArtifact"
                )
            if (
                self.parsed_target_digest
                and parsed.content_digest != self.parsed_target_digest
            ):
                raise EvidenceLineageError(
                    "parsed_target_digest does not match "
                    "ParsedTargetArtifact.content_digest"
                )
            if parsed.output_digest != self.output_digest:
                raise EvidenceLineageError(
                    "output_digest does not match ParsedTargetArtifact."
                    "output_digest"
                )
            if parsed.result_digest != self.result_digest:
                raise EvidenceLineageError(
                    "result_digest does not match ParsedTargetArtifact."
                    "result_digest"
                )

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["content_digest"] = self.content_digest
        payload["metadata"] = _thaw_mapping(self.metadata)
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProviderExecutionReceiptV2":
        payload = _require_mapping(data, "ProviderExecutionReceiptV2")
        interface = payload.get("interface")
        if (
            interface is not None
            and interface != PROVIDER_EXECUTION_RECEIPT_V2_INTERFACE
        ):
            raise EvidenceV2Error(
                f"unsupported ProviderExecutionReceiptV2 interface {interface!r}"
            )
        if "bounds" not in payload or payload.get("bounds") is None:
            raise MissingBoundsError(
                "ProviderExecutionReceipt@2 requires bounds"
            )
        if "mock_execution" in payload:
            raise ExecutionClaimError(
                "ProviderExecutionReceipt@2 rejects mock_execution fields; "
                "use record_kind=mock with execution_claimed=false"
            )
        return cls(
            receipt_id=str(payload.get("receipt_id") or ""),
            request_id=str(payload.get("request_id") or ""),
            request_digest=str(payload.get("request_digest") or ""),
            compiled_artifact_id=str(payload.get("compiled_artifact_id") or ""),
            compiled_artifact_digest=str(
                payload.get("compiled_artifact_digest") or ""
            ),
            provider=payload.get("provider") or "",
            evidence_kind=payload.get("evidence_kind") or "",
            launch_id=str(payload.get("launch_id") or ""),
            tool_id=str(payload.get("tool_id") or ""),
            output_digest=str(payload.get("output_digest") or ""),
            result_digest=str(payload.get("result_digest") or ""),
            bounds=payload["bounds"],
            record_kind=str(
                payload.get("record_kind") or ExecutionRecordKind.LIVE.value
            ),
            execution_claimed=bool(payload.get("execution_claimed", True)),
            outcome=str(payload.get("outcome") or ExecutionOutcome.SUCCEEDED.value),
            parsed_target_id=str(payload.get("parsed_target_id") or ""),
            parsed_target_digest=str(payload.get("parsed_target_digest") or ""),
            target_digest=str(payload.get("target_digest") or ""),
            toolchain_id=str(payload.get("toolchain_id") or ""),
            exit_code=payload.get("exit_code"),
            duration_ms=int(payload.get("duration_ms") or 0),
            authority_ceiling=str(
                payload.get("authority_ceiling")
                or RequestAuthorityCeiling.BOUNDED.value
            ),
            content_digest=str(payload.get("content_digest") or ""),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version")
                or PROVIDER_EXECUTION_RECEIPT_V2_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_parsed_target(
        cls,
        parsed: ParsedTargetArtifact,
        *,
        receipt_id: str,
        launch_id: str,
        tool_id: str,
        bounds: RequestBounds | Mapping[str, Any],
        record_kind: ExecutionRecordKind | str = ExecutionRecordKind.LIVE,
        execution_claimed: bool = True,
        outcome: ExecutionOutcome | str = ExecutionOutcome.SUCCEEDED,
        exit_code: int | None = 0,
        duration_ms: int = 0,
        toolchain_id: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> "ProviderExecutionReceiptV2":
        """Build an execution receipt from an admitted parsed target result."""

        if not isinstance(parsed, ParsedTargetArtifact):
            raise EvidenceV2Error("from_parsed_target requires ParsedTargetArtifact")
        admitted = parsed.require_admitted()
        return cls(
            receipt_id=receipt_id,
            request_id=admitted.request_id,
            request_digest=admitted.request_digest,
            compiled_artifact_id=admitted.compiled_artifact_id,
            compiled_artifact_digest=admitted.compiled_artifact_digest,
            provider=admitted.provider,
            evidence_kind=admitted.evidence_kind,
            launch_id=launch_id,
            tool_id=tool_id,
            output_digest=admitted.output_digest,
            result_digest=admitted.result_digest,
            bounds=bounds,
            record_kind=record_kind,
            execution_claimed=execution_claimed,
            outcome=outcome,
            parsed_target_id=admitted.artifact_id,
            parsed_target_digest=admitted.content_digest,
            target_digest=admitted.target_digest,
            toolchain_id=toolchain_id,
            exit_code=exit_code,
            duration_ms=duration_ms,
            authority_ceiling=admitted.authority_ceiling,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def metadata_only(
        cls,
        *,
        receipt_id: str,
        request_id: str,
        request_digest: str,
        compiled_artifact_id: str,
        compiled_artifact_digest: str,
        provider: LogicIdentity | Mapping[str, Any] | str,
        evidence_kind: LogicIdentity | Mapping[str, Any] | str,
        bounds: RequestBounds | Mapping[str, Any],
        reason: str = "declaration_only",
        metadata: Mapping[str, Any] | None = None,
    ) -> "ProviderExecutionReceiptV2":
        """Build a non-claiming metadata-only record (never claims execution)."""

        placeholder = content_sha256(
            canonical_json_bytes(
                {
                    "kind": "metadata_only",
                    "reason": reason,
                    "receipt_id": receipt_id,
                }
            )
        )
        meta = dict(metadata or {})
        meta["metadata_only_reason"] = reason
        return cls(
            receipt_id=receipt_id,
            request_id=request_id,
            request_digest=request_digest,
            compiled_artifact_id=compiled_artifact_id,
            compiled_artifact_digest=compiled_artifact_digest,
            provider=provider,
            evidence_kind=evidence_kind,
            launch_id="launch:none",
            tool_id="tool:none",
            output_digest=placeholder,
            result_digest=placeholder,
            bounds=bounds,
            record_kind=ExecutionRecordKind.METADATA_ONLY,
            execution_claimed=False,
            outcome=ExecutionOutcome.UNAVAILABLE,
            authority_ceiling=RequestAuthorityCeiling.NONE,
            metadata=meta,
        )

    @classmethod
    def mock_record(
        cls,
        *,
        receipt_id: str,
        request_id: str,
        request_digest: str,
        compiled_artifact_id: str,
        compiled_artifact_digest: str,
        provider: LogicIdentity | Mapping[str, Any] | str,
        evidence_kind: LogicIdentity | Mapping[str, Any] | str,
        bounds: RequestBounds | Mapping[str, Any],
        reason: str = "unit_test_double",
        metadata: Mapping[str, Any] | None = None,
    ) -> "ProviderExecutionReceiptV2":
        """Build a non-claiming mock record (never claims execution or replay)."""

        placeholder = content_sha256(
            canonical_json_bytes(
                {
                    "kind": "mock",
                    "reason": reason,
                    "receipt_id": receipt_id,
                }
            )
        )
        meta = dict(metadata or {})
        meta["mock_reason"] = reason
        return cls(
            receipt_id=receipt_id,
            request_id=request_id,
            request_digest=request_digest,
            compiled_artifact_id=compiled_artifact_id,
            compiled_artifact_digest=compiled_artifact_digest,
            provider=provider,
            evidence_kind=evidence_kind,
            launch_id="launch:mock",
            tool_id="tool:mock",
            output_digest=placeholder,
            result_digest=placeholder,
            bounds=bounds,
            record_kind=ExecutionRecordKind.MOCK,
            execution_claimed=False,
            outcome=ExecutionOutcome.UNSUPPORTED,
            authority_ceiling=RequestAuthorityCeiling.NONE,
            metadata=meta,
        )


def require_executable_receipt(
    receipt: ProviderExecutionReceiptV2,
) -> ProviderExecutionReceiptV2:
    """Fail closed when a non-executable record is presented as execution."""

    if not isinstance(receipt, ProviderExecutionReceiptV2):
        raise ExecutionClaimError(
            "require_executable_receipt requires ProviderExecutionReceipt@2"
        )
    return receipt.require_execution_claim()


# ---------------------------------------------------------------------------
# EvidenceReplayReceipt@1
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvidenceReplayReceipt:
    """Replay disposition bound to a provider execution receipt.

    Interface: ``EvidenceReplayReceipt@1``.

    ``replay_claimed`` may only be true when:

    * ``disposition`` is ``replayed``
    * the source execution receipt is an executable claim
    * source ``record_kind`` is not metadata-only or mock
    """

    receipt_id: str
    execution_receipt_id: str
    execution_receipt_digest: str
    disposition: ReplayDisposition | str
    source_record_kind: ExecutionRecordKind | str
    replay_claimed: bool = False
    match_digest: str = ""
    decoded_evidence_digest: str = ""
    output_digest: str = ""
    result_digest: str = ""
    reason: str = ""
    content_digest: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = EVIDENCE_REPLAY_RECEIPT_SCHEMA_VERSION

    interface: ClassVar[str] = EVIDENCE_REPLAY_RECEIPT_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", _record_id(self.receipt_id, "receipt_id")
        )
        object.__setattr__(
            self,
            "execution_receipt_id",
            _record_id(self.execution_receipt_id, "execution_receipt_id"),
        )
        object.__setattr__(
            self,
            "execution_receipt_digest",
            _sha256_hex(self.execution_receipt_digest, "execution_receipt_digest"),
        )

        disposition = _coerce_disposition(self.disposition)
        object.__setattr__(self, "disposition", disposition)

        source_kind = _coerce_record_kind(
            self.source_record_kind, "source_record_kind"
        )
        object.__setattr__(self, "source_record_kind", source_kind)

        replay_claimed = _bool_flag(self.replay_claimed, "replay_claimed")
        if replay_claimed:
            if disposition is not ReplayDisposition.REPLAYED:
                raise ReplayClaimError(
                    "replay_claimed requires disposition=replayed"
                )
            if source_kind in _NON_REPLAY_SOURCE_KINDS:
                raise ReplayClaimError(
                    f"source_record_kind {source_kind.value!r} cannot claim "
                    "replay through EvidenceReplayReceipt@1; metadata-only "
                    "and mock records are non-claiming on the v2 route"
                )
            if not self.match_digest:
                raise ReplayClaimError(
                    "replay_claimed EvidenceReplayReceipt requires match_digest"
                )
        if (
            disposition is ReplayDisposition.REPLAYED
            and source_kind in _NON_REPLAY_SOURCE_KINDS
        ):
            raise ReplayClaimError(
                f"disposition=replayed is forbidden for source_record_kind "
                f"{source_kind.value!r}"
            )
        object.__setattr__(self, "replay_claimed", replay_claimed)

        object.__setattr__(
            self, "match_digest", _optional_sha256(self.match_digest, "match_digest")
        )
        object.__setattr__(
            self,
            "decoded_evidence_digest",
            _optional_sha256(
                self.decoded_evidence_digest, "decoded_evidence_digest"
            ),
        )
        object.__setattr__(
            self, "output_digest", _optional_sha256(self.output_digest, "output_digest")
        )
        object.__setattr__(
            self, "result_digest", _optional_sha256(self.result_digest, "result_digest")
        )
        if self.reason:
            object.__setattr__(
                self, "reason", _text(self.reason, "reason", maximum=512)
            )

        metadata = _freeze_mapping(self.metadata, "metadata")
        _forbid_evidence_metadata(metadata, "metadata")
        object.__setattr__(self, "metadata", metadata)

        if self.schema_version != EVIDENCE_REPLAY_RECEIPT_SCHEMA_VERSION:
            raise EvidenceV2Error(
                f"unsupported EvidenceReplayReceipt schema_version "
                f"{self.schema_version!r}"
            )

        content = content_sha256(canonical_json_bytes(self._identity_payload()))
        if self.content_digest:
            provided = _sha256_hex(self.content_digest, "content_digest")
            if provided != content:
                raise EvidenceV2Error(
                    "content_digest does not match EvidenceReplayReceipt content"
                )
            object.__setattr__(self, "content_digest", provided)
        else:
            object.__setattr__(self, "content_digest", content)

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "decoded_evidence_digest": self.decoded_evidence_digest,
            "disposition": _status_value(self.disposition),
            "execution_receipt_digest": self.execution_receipt_digest,
            "execution_receipt_id": self.execution_receipt_id,
            "interface": self.interface,
            "match_digest": self.match_digest,
            "output_digest": self.output_digest,
            "reason": self.reason,
            "receipt_id": self.receipt_id,
            "replay_claimed": self.replay_claimed,
            "result_digest": self.result_digest,
            "schema_version": self.schema_version,
            "source_record_kind": _status_value(self.source_record_kind),
        }

    @property
    def is_replay_claim(self) -> bool:
        return (
            self.replay_claimed
            and self.disposition is ReplayDisposition.REPLAYED
            and self.source_record_kind not in _NON_REPLAY_SOURCE_KINDS
        )

    def require_replay_claim(self) -> "EvidenceReplayReceipt":
        """Return self when this receipt may be treated as a replay claim."""

        if self.source_record_kind in _NON_REPLAY_SOURCE_KINDS:
            raise ReplayClaimError(
                f"EvidenceReplayReceipt {self.receipt_id} has source_record_kind "
                f"{_status_value(self.source_record_kind)!r}; metadata-only and "
                "mock records cannot claim replay through the v2 route"
            )
        if not self.replay_claimed:
            raise ReplayClaimError(
                f"EvidenceReplayReceipt {self.receipt_id} does not claim replay "
                "(replay_claimed=false)"
            )
        if not self.is_replay_claim:
            raise ReplayClaimError(
                f"EvidenceReplayReceipt {self.receipt_id} is not an admitted "
                "replay claim"
            )
        return self

    def validate_against_execution(
        self, execution: ProviderExecutionReceiptV2
    ) -> None:
        """Cross-check lineage against a concrete execution receipt."""

        if not isinstance(execution, ProviderExecutionReceiptV2):
            raise EvidenceV2Error(
                "validate_against_execution requires ProviderExecutionReceiptV2"
            )
        if execution.receipt_id != self.execution_receipt_id:
            raise EvidenceLineageError(
                "execution_receipt_id does not match ProviderExecutionReceipt"
            )
        if execution.content_digest != self.execution_receipt_digest:
            raise EvidenceLineageError(
                "execution_receipt_digest does not match "
                "ProviderExecutionReceipt.content_digest"
            )
        if execution.record_kind != self.source_record_kind:
            raise EvidenceLineageError(
                "source_record_kind does not match "
                "ProviderExecutionReceipt.record_kind"
            )
        if self.replay_claimed and not execution.is_executable_claim:
            raise ReplayClaimError(
                "replay claims require an executable source execution receipt"
            )
        if self.output_digest and self.output_digest != execution.output_digest:
            raise EvidenceLineageError(
                "output_digest does not match ProviderExecutionReceipt."
                "output_digest"
            )
        if self.result_digest and self.result_digest != execution.result_digest:
            raise EvidenceLineageError(
                "result_digest does not match ProviderExecutionReceipt."
                "result_digest"
            )

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["content_digest"] = self.content_digest
        payload["metadata"] = _thaw_mapping(self.metadata)
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvidenceReplayReceipt":
        payload = _require_mapping(data, "EvidenceReplayReceipt")
        interface = payload.get("interface")
        if interface is not None and interface != EVIDENCE_REPLAY_RECEIPT_INTERFACE:
            raise EvidenceV2Error(
                f"unsupported EvidenceReplayReceipt interface {interface!r}"
            )
        if "fake_replay" in payload or "claimed_replay" in payload:
            raise ReplayClaimError(
                "EvidenceReplayReceipt@1 rejects free-form claimed_replay/"
                "fake_replay fields; use disposition and replay_claimed"
            )
        return cls(
            receipt_id=str(payload.get("receipt_id") or ""),
            execution_receipt_id=str(payload.get("execution_receipt_id") or ""),
            execution_receipt_digest=str(
                payload.get("execution_receipt_digest") or ""
            ),
            disposition=str(
                payload.get("disposition") or ReplayDisposition.NOT_ATTEMPTED.value
            ),
            source_record_kind=str(
                payload.get("source_record_kind")
                or ExecutionRecordKind.LIVE.value
            ),
            replay_claimed=bool(payload.get("replay_claimed", False)),
            match_digest=str(payload.get("match_digest") or ""),
            decoded_evidence_digest=str(
                payload.get("decoded_evidence_digest") or ""
            ),
            output_digest=str(payload.get("output_digest") or ""),
            result_digest=str(payload.get("result_digest") or ""),
            reason=str(payload.get("reason") or ""),
            content_digest=str(payload.get("content_digest") or ""),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version") or EVIDENCE_REPLAY_RECEIPT_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_execution(
        cls,
        execution: ProviderExecutionReceiptV2,
        *,
        receipt_id: str,
        disposition: ReplayDisposition | str,
        replay_claimed: bool = False,
        match_digest: str = "",
        decoded_evidence_digest: str = "",
        reason: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> "EvidenceReplayReceipt":
        """Build a replay receipt bound to a concrete execution receipt."""

        if not isinstance(execution, ProviderExecutionReceiptV2):
            raise EvidenceV2Error(
                "from_execution requires ProviderExecutionReceiptV2"
            )
        if replay_claimed:
            try:
                execution.require_execution_claim()
            except ExecutionClaimError as error:
                raise ReplayClaimError(
                    f"replay claims require an executable source receipt: {error}"
                ) from error
        return cls(
            receipt_id=receipt_id,
            execution_receipt_id=execution.receipt_id,
            execution_receipt_digest=execution.content_digest,
            disposition=disposition,
            source_record_kind=execution.record_kind,
            replay_claimed=replay_claimed,
            match_digest=match_digest,
            decoded_evidence_digest=decoded_evidence_digest,
            output_digest=execution.output_digest,
            result_digest=execution.result_digest,
            reason=reason,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def explicit_non_replay(
        cls,
        execution: ProviderExecutionReceiptV2,
        *,
        receipt_id: str,
        reason: str,
        disposition: ReplayDisposition | str = ReplayDisposition.NON_REPLAYABLE,
        metadata: Mapping[str, Any] | None = None,
    ) -> "EvidenceReplayReceipt":
        """Record an explicit non-replay disposition (never claims replay)."""

        coerced = _coerce_disposition(disposition)
        if coerced is ReplayDisposition.REPLAYED:
            raise ReplayClaimError(
                "explicit_non_replay cannot use disposition=replayed"
            )
        return cls.from_execution(
            execution,
            receipt_id=receipt_id,
            disposition=coerced,
            replay_claimed=False,
            reason=reason,
            metadata=metadata,
        )


def require_replay_receipt(
    receipt: EvidenceReplayReceipt,
) -> EvidenceReplayReceipt:
    """Fail closed when a non-replayable record is presented as replay."""

    if not isinstance(receipt, EvidenceReplayReceipt):
        raise ReplayClaimError(
            "require_replay_receipt requires EvidenceReplayReceipt@1"
        )
    return receipt.require_replay_claim()


__all__ = [
    "EVIDENCE_REPLAY_RECEIPT_INTERFACE",
    "EVIDENCE_REPLAY_RECEIPT_SCHEMA_VERSION",
    "EVIDENCE_V2_MODULE_VERSION",
    "LEGACY_PROVIDER_EXECUTION_RECEIPT_INTERFACE",
    "LEGACY_PROVIDER_EXECUTION_RECEIPT_SCHEMA_VERSION",
    "PROVIDER_EXECUTION_RECEIPT_V2_INTERFACE",
    "PROVIDER_EXECUTION_RECEIPT_V2_SCHEMA_VERSION",
    "EvidenceLineageError",
    "EvidenceReplayReceipt",
    "EvidenceV2Error",
    "ExecutionClaimError",
    "ExecutionOutcome",
    "ExecutionRecordKind",
    "ProviderExecutionReceiptV2",
    "ReplayClaimError",
    "ReplayDisposition",
    "require_executable_receipt",
    "require_replay_receipt",
]
