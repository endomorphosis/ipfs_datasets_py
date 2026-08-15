"""Explicit LogicProvider@1 → LogicProviderProtocol@2 adapter (LPC-051).

Interface: ``LogicProviderProtocolV1Adapter@1``.

``LogicProvider@1`` carries an unrestricted JSON ``payload``.  That envelope
must never silently become executable work or mint a
:class:`~ipfs_datasets_py.logic.backends.requests_v2.BackendRequestV2`.

This module is the only lawful dual-read path for v1 generics.  Every input
receives exactly one disposition:

* **parsed** — closed operation identified and elevated to a typed
  LogicProviderProtocol@2 request (capability always; executable ops only
  when an admitted BackendRequest@2 and positive finite bounds are supplied
  *outside* the free-form payload)
* **rejected** — malformed envelope, unknown operation, or free-form attempt
  to bypass BackendRequest@2
* **advisory** — operation known but not elevatable; retained without
  executable authority and without a synthesised BackendRequest@2

New provider writes use LogicProviderProtocol@2 / BackendRequest@2 directly
via :func:`admit_new_provider_write`.  Provider output remains untrusted until
validation or reconstruction (LPC-032).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from ipfs_datasets_py.logic.backends.protocol_v2 import (
    EXECUTABLE_OPERATIONS,
    LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE,
    ArbitraryPayloadProtocolError,
    AttestRequestV2,
    CapabilityRequestV2,
    ProveCheckMode,
    ProveCheckRequestV2,
    ProtocolOperationV2,
    ProtocolV2AdmissionError,
    ProtocolV2Error,
    ProviderRequestV2,
    ReconstructRequestV2,
    TranslationRequestV2,
    VerifyRequestV2,
    admit_provider_request_v2,
    is_executable_operation,
)
from ipfs_datasets_py.logic.backends.provider import (
    LOGIC_PROVIDER_PROTOCOL_VERSION as LOGIC_PROVIDER_V1_PROTOCOL_VERSION,
    LOGIC_PROVIDER_REQUEST_SCHEMA,
    LogicProviderContractError,
    LogicProviderOperation,
    LogicProviderRequest,
)
from ipfs_datasets_py.logic.backends.requests_v2 import (
    BACKEND_REQUEST_V2_INTERFACE,
    BackendRequestV2,
    RequestBounds,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    SyntaxContractError,
    _freeze_mapping,
    _require_mapping,
    _text,
    canonical_json_bytes,
    content_sha256,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

PROTOCOL_V1_ADAPTER_INTERFACE: Final = "LogicProviderProtocolV1Adapter@1"
PROTOCOL_V1_ADAPTER_VERSION: Final = "1.0.0"
PROTOCOL_V1_ADAPTER_SCHEMA: Final = (
    "ipfs_datasets_py/logic-provider-v1-adapter@1"
)
ADVISORY_V1_RETENTION_SCHEMA: Final = (
    "ipfs_datasets_py/logic-provider-v1-advisory@1"
)

# Keys that must never be treated as a free-form substitute for BackendRequest@2.
_BYPASS_PAYLOAD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "backend_request",
        "backend_request_v2",
        "BackendRequest",
        "BackendRequest@2",
        "obligation",
        "logic_obligation",
        "domain_slice",
        "slice",
    }
)


class V1AdapterError(LogicProviderContractError):
    """Raised when a v1 envelope cannot be dual-read safely."""


class V1BypassBackendRequestError(V1AdapterError):
    """Raised when a free-form payload attempts to mint BackendRequest@2."""


class V1AdapterDisposition(str, Enum):
    """Closed three-way disposition for v1 generic payloads."""

    PARSED = "parsed"
    REJECTED = "rejected"
    ADVISORY = "advisory"


# Map LogicProvider@1 operations onto LogicProviderProtocol@2 operations.
# v1 has no distinct ``check`` wire name; check rides prove in v1.
_V1_TO_V2_OPERATION: Final[
    Mapping[LogicProviderOperation, ProtocolOperationV2]
] = {
    LogicProviderOperation.CAPABILITY: ProtocolOperationV2.CAPABILITY,
    LogicProviderOperation.TRANSLATE: ProtocolOperationV2.TRANSLATE,
    LogicProviderOperation.PROVE: ProtocolOperationV2.PROVE,
    LogicProviderOperation.RECONSTRUCT: ProtocolOperationV2.RECONSTRUCT,
    LogicProviderOperation.VERIFY: ProtocolOperationV2.VERIFY,
    LogicProviderOperation.ATTEST: ProtocolOperationV2.ATTEST,
}


def _is_v1_envelope_dict(payload: Mapping[str, Any]) -> bool:
    schema = str(payload.get("schema_version") or "")
    try:
        protocol_version = int(payload.get("protocol_version", 0) or 0)
    except (TypeError, ValueError):
        protocol_version = -1
    if schema == LOGIC_PROVIDER_REQUEST_SCHEMA:
        return True
    if protocol_version == LOGIC_PROVIDER_V1_PROTOCOL_VERSION and "payload" in payload:
        return True
    if "operation" in payload and "payload" in payload and protocol_version in {
        0,
        LOGIC_PROVIDER_V1_PROTOCOL_VERSION,
    }:
        # Bare dual-read shape without schema stamp.
        return True
    return False


def _is_v2_typed_dict(payload: Mapping[str, Any]) -> bool:
    schema = str(payload.get("schema_version") or "")
    interface = str(payload.get("interface") or "")
    try:
        protocol_version = int(
            payload.get("protocol_version", LOGIC_PROVIDER_V1_PROTOCOL_VERSION) or 0
        )
    except (TypeError, ValueError):
        protocol_version = -1
    if interface == LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE:
        return True
    if protocol_version == 2 and "payload" not in payload:
        return True
    if schema.startswith("ipfs_datasets_py/logic-provider-") and schema.endswith(
        "@2"
    ):
        return True
    return False


def parse_v1_provider_envelope(
    value: LogicProviderRequest | Mapping[str, Any] | str,
) -> LogicProviderRequest:
    """Parse a LogicProvider@1 envelope (fail closed)."""

    if isinstance(value, LogicProviderRequest):
        return value
    if isinstance(value, str):
        try:
            return LogicProviderRequest.from_json(value)
        except LogicProviderContractError as error:
            raise V1AdapterError(f"malformed v1 provider JSON: {error}") from error
    if not isinstance(value, Mapping):
        raise V1AdapterError(
            f"v1 provider envelope must be LogicProviderRequest, mapping, or JSON; "
            f"got {type(value).__name__}"
        )
    payload = dict(value)
    if not _is_v1_envelope_dict(payload) and _is_v2_typed_dict(payload):
        raise V1AdapterError(
            "LogicProviderProtocol@2 bodies are not v1 envelopes; "
            "use admit_provider_request_v2 / admit_new_provider_write"
        )
    # Normalise missing schema/version for dual-read of bare envelopes.
    if "schema_version" not in payload:
        payload["schema_version"] = LOGIC_PROVIDER_REQUEST_SCHEMA
    if "protocol_version" not in payload:
        payload["protocol_version"] = LOGIC_PROVIDER_V1_PROTOCOL_VERSION
    try:
        return LogicProviderRequest.from_dict(payload)
    except LogicProviderContractError as error:
        raise V1AdapterError(f"malformed LogicProvider@1 envelope: {error}") from error


def classify_v1_operation(
    value: (
        LogicProviderRequest
        | Mapping[str, Any]
        | LogicProviderOperation
        | ProtocolOperationV2
        | str
    ),
) -> ProtocolOperationV2:
    """Parse *value* into a closed LogicProviderProtocol@2 operation type.

    Accepts a full v1 envelope, a v1/v2 operation name, or an enum member.
    Unknown operations raise :class:`V1AdapterError` (reject path).
    """

    if isinstance(value, ProtocolOperationV2):
        return value
    if isinstance(value, LogicProviderOperation):
        return _V1_TO_V2_OPERATION[value]
    if isinstance(value, LogicProviderRequest):
        return _V1_TO_V2_OPERATION[LogicProviderOperation(value.operation.value)]
    if isinstance(value, Mapping):
        if _is_v2_typed_dict(value) and not _is_v1_envelope_dict(value):
            raise V1AdapterError(
                "cannot classify LogicProviderProtocol@2 body as a v1 envelope"
            )
        request = parse_v1_provider_envelope(value)
        return _V1_TO_V2_OPERATION[LogicProviderOperation(request.operation.value)]
    if isinstance(value, str) and value.lstrip()[:1] in "{[":
        request = parse_v1_provider_envelope(value)
        return _V1_TO_V2_OPERATION[LogicProviderOperation(request.operation.value)]

    raw = str(getattr(value, "value", value)).strip()
    if not raw:
        raise V1AdapterError("operation is required")
    # Accept @2 check even though v1 wire uses prove for both.
    if raw == ProtocolOperationV2.CHECK.value:
        return ProtocolOperationV2.CHECK
    try:
        v1_op = LogicProviderOperation(raw)
    except ValueError as error:
        raise V1AdapterError(
            f"unknown logic-provider operation {raw!r}; "
            f"expected one of "
            f"{sorted(op.value for op in LogicProviderOperation)}"
        ) from error
    return _V1_TO_V2_OPERATION[v1_op]


def _reject_payload_backend_request_bypass(payload: Mapping[str, Any]) -> None:
    """Fail closed if free-form payload tries to mint BackendRequest@2."""

    for key in payload:
        if key in _BYPASS_PAYLOAD_KEYS:
            raise V1BypassBackendRequestError(
                f"v1 free-form payload key {key!r} cannot mint or bypass "
                f"{BACKEND_REQUEST_V2_INTERFACE}; supply BackendRequest@2 as an "
                "explicit adapter argument"
            )


def _coerce_external_backend_request(
    value: BackendRequestV2 | Mapping[str, Any] | None,
) -> BackendRequestV2 | None:
    if value is None:
        return None
    if isinstance(value, BackendRequestV2):
        return value
    if isinstance(value, Mapping):
        try:
            return BackendRequestV2.from_dict(value)
        except Exception as error:
            raise V1AdapterError(
                f"adapter backend_request must be an admitted "
                f"{BACKEND_REQUEST_V2_INTERFACE}: {error}"
            ) from error
    raise V1AdapterError(
        f"adapter backend_request must be BackendRequest@2 or mapping; "
        f"got {type(value).__name__}"
    )


def _coerce_external_bounds(
    value: RequestBounds | Mapping[str, Any] | None,
    *,
    backend_request: BackendRequestV2 | None,
) -> RequestBounds | None:
    if value is None:
        if backend_request is not None:
            return backend_request.bounds
        return None
    if isinstance(value, RequestBounds):
        bounds = value
    elif isinstance(value, Mapping):
        try:
            bounds = RequestBounds.from_dict(value)
        except Exception as error:
            raise V1AdapterError(f"adapter bounds are invalid: {error}") from error
    else:
        raise V1AdapterError(
            f"adapter bounds must be RequestBounds or mapping; got "
            f"{type(value).__name__}"
        )
    if backend_request is not None:
        br = backend_request.bounds
        if (
            bounds.timeout_ms > br.timeout_ms
            or bounds.max_steps > br.max_steps
            or bounds.max_memory_bytes > br.max_memory_bytes
            or bounds.max_output_bytes > br.max_output_bytes
        ):
            raise V1AdapterError(
                "adapter bounds cannot exceed admitted BackendRequest@2 bounds"
            )
    return bounds


@dataclass(frozen=True, slots=True)
class AdvisoryV1Retention:
    """Non-authoritative retention of a classified v1 envelope.

    Advisory retentions never grant proof authority, never carry a
    BackendRequest@2, and never become executable provider work.
    """

    request_id: str
    operation: ProtocolOperationV2
    payload: Mapping[str, Any] = field(default_factory=dict)
    reason: str = ""
    authority_ceiling: str = "advisory"
    schema_version: str = ADVISORY_V1_RETENTION_SCHEMA
    interface: str = PROTOCOL_V1_ADAPTER_INTERFACE
    v1_schema_version: str = LOGIC_PROVIDER_REQUEST_SCHEMA
    protocol_version: int = LOGIC_PROVIDER_V1_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "request_id",
            _text(self.request_id, "request_id", maximum=128),
        )
        if not isinstance(self.operation, ProtocolOperationV2):
            object.__setattr__(
                self, "operation", classify_v1_operation(self.operation)
            )
        object.__setattr__(
            self, "payload", _freeze_mapping(self.payload, "advisory payload")
        )
        object.__setattr__(
            self,
            "reason",
            _text(self.reason, "reason", allow_empty=True, maximum=1024),
        )
        if self.authority_ceiling != "advisory":
            raise V1AdapterError(
                "AdvisoryV1Retention.authority_ceiling must be 'advisory'"
            )
        if self.schema_version != ADVISORY_V1_RETENTION_SCHEMA:
            raise V1AdapterError(
                f"unsupported advisory schema_version {self.schema_version!r}"
            )

    @property
    def executable(self) -> bool:
        return False

    @property
    def backend_request(self) -> None:
        """Advisory retention never synthesises BackendRequest@2."""

        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "interface": self.interface,
            "protocol_version": self.protocol_version,
            "request_id": self.request_id,
            "operation": self.operation.value,
            "payload": dict(self.payload),
            "authority_ceiling": self.authority_ceiling,
            "reason": self.reason,
            "executable": False,
            "backend_request": None,
            "v1_schema_version": self.v1_schema_version,
        }

    def content_digest(self) -> str:
        return content_sha256(canonical_json_bytes(self.to_dict()))


@dataclass(frozen=True, slots=True)
class V1AdapterResult:
    """Result of adapting one v1 generic provider envelope."""

    disposition: V1AdapterDisposition
    operation: ProtocolOperationV2 | None = None
    request_v2: ProviderRequestV2 | None = None
    advisory: AdvisoryV1Retention | None = None
    reason: str = ""
    v1_request: LogicProviderRequest | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, V1AdapterDisposition):
            object.__setattr__(
                self,
                "disposition",
                V1AdapterDisposition(str(self.disposition)),
            )
        object.__setattr__(
            self,
            "reason",
            _text(self.reason, "reason", allow_empty=True, maximum=1024),
        )
        if self.disposition is V1AdapterDisposition.PARSED:
            if self.request_v2 is None or self.operation is None:
                raise V1AdapterError(
                    "PARSED disposition requires operation and request_v2"
                )
            if self.advisory is not None:
                raise V1AdapterError("PARSED disposition cannot carry advisory")
        elif self.disposition is V1AdapterDisposition.ADVISORY:
            if self.advisory is None or self.operation is None:
                raise V1AdapterError(
                    "ADVISORY disposition requires operation and advisory"
                )
            if self.request_v2 is not None:
                raise V1AdapterError(
                    "ADVISORY disposition cannot carry an elevated request_v2"
                )
        elif self.disposition is V1AdapterDisposition.REJECTED:
            if self.request_v2 is not None or self.advisory is not None:
                raise V1AdapterError(
                    "REJECTED disposition cannot carry request_v2 or advisory"
                )

    @property
    def executable(self) -> bool:
        if self.request_v2 is None:
            return False
        return is_executable_operation(self.request_v2.operation)

    @property
    def backend_request(self) -> BackendRequestV2 | None:
        if self.request_v2 is None:
            return None
        return getattr(self.request_v2, "backend_request", None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PROTOCOL_V1_ADAPTER_SCHEMA,
            "interface": PROTOCOL_V1_ADAPTER_INTERFACE,
            "disposition": self.disposition.value,
            "operation": None if self.operation is None else self.operation.value,
            "request_v2": (
                None if self.request_v2 is None else self.request_v2.to_dict()
            ),
            "advisory": None if self.advisory is None else self.advisory.to_dict(),
            "reason": self.reason,
            "executable": self.executable,
            "backend_request": (
                None
                if self.backend_request is None
                else self.backend_request.to_dict()
            ),
            "v1_request": (
                None if self.v1_request is None else self.v1_request.to_dict()
            ),
        }


def _elevation_common_kwargs(
    v1: LogicProviderRequest,
) -> dict[str, Any]:
    return {
        "request_id": v1.request_id,
        "resource_budget": v1.resource_budget,
        "cancellation": v1.cancellation,
        "network_allowed": v1.network_allowed,
        "deadline_unix_ms": v1.deadline_unix_ms,
        # Never re-introduce free-form routing via metadata.
        "metadata": {},
    }


def _try_elevate(
    v1: LogicProviderRequest,
    operation: ProtocolOperationV2,
    *,
    backend_request: BackendRequestV2 | None,
    bounds: RequestBounds | None,
    mode: ProveCheckMode | str | None,
) -> ProviderRequestV2 | None:
    """Attempt elevation to a typed @2 request; return None when advisory."""

    payload = dict(v1.payload)
    common = _elevation_common_kwargs(v1)

    if operation is ProtocolOperationV2.CAPABILITY:
        feature_query = payload.get("feature_query") or payload.get("features") or ()
        if isinstance(feature_query, str):
            feature_query = (feature_query,)
        return CapabilityRequestV2(
            provider_id=str(
                payload.get("provider_id") or payload.get("backend_id") or ""
            ),
            feature_query=tuple(feature_query) if feature_query else (),
            include_versions=bool(payload.get("include_versions", False)),
            **common,
        )

    # Executable ops require explicit BackendRequest@2 + positive finite bounds.
    if backend_request is None or bounds is None:
        return None

    if operation is ProtocolOperationV2.TRANSLATE:
        source = str(
            payload.get("source_encoding")
            or payload.get("source")
            or payload.get("from_encoding")
            or ""
        ).strip()
        target = str(
            payload.get("target_encoding")
            or payload.get("target")
            or payload.get("to_encoding")
            or ""
        ).strip()
        if not source or not target:
            return None
        return TranslationRequestV2(
            bounds=bounds,
            backend_request=backend_request,
            source_encoding=source,
            target_encoding=target,
            source_artifact_digest=str(
                payload.get("source_artifact_digest") or ""
            ),
            preservation_claim=str(payload.get("preservation_claim") or ""),
            **common,
        )

    if operation in {ProtocolOperationV2.PROVE, ProtocolOperationV2.CHECK}:
        resolved_mode: ProveCheckMode | str
        if mode is not None:
            resolved_mode = mode
        elif operation is ProtocolOperationV2.CHECK:
            resolved_mode = ProveCheckMode.CHECK
        else:
            raw_mode = str(payload.get("mode") or "prove").strip() or "prove"
            if raw_mode == "check":
                resolved_mode = ProveCheckMode.CHECK
            else:
                resolved_mode = ProveCheckMode.PROVE
        statement = str(
            payload.get("statement")
            or payload.get("formula")
            or payload.get("goal")
            or ""
        )
        return ProveCheckRequestV2(
            bounds=bounds,
            backend_request=backend_request,
            mode=resolved_mode,
            statement=statement,
            goal_digest=str(payload.get("goal_digest") or ""),
            **common,
        )

    if operation is ProtocolOperationV2.RECONSTRUCT:
        candidate = str(
            payload.get("candidate_digest")
            or payload.get("digest")
            or ""
        ).strip()
        if not candidate:
            return None
        return ReconstructRequestV2(
            bounds=bounds,
            backend_request=backend_request,
            candidate_digest=candidate,
            candidate_artifact_id=str(
                payload.get("candidate_artifact_id") or ""
            ),
            kernel_id=str(payload.get("kernel_id") or ""),
            **common,
        )

    if operation is ProtocolOperationV2.VERIFY:
        evidence = str(
            payload.get("evidence_digest")
            or payload.get("digest")
            or ""
        ).strip()
        if not evidence:
            return None
        return VerifyRequestV2(
            bounds=bounds,
            backend_request=backend_request,
            evidence_digest=evidence,
            evidence_kind=str(payload.get("evidence_kind") or ""),
            verifier_id=str(payload.get("verifier_id") or ""),
            **common,
        )

    if operation is ProtocolOperationV2.ATTEST:
        statement_digest = str(
            payload.get("statement_digest")
            or payload.get("digest")
            or ""
        ).strip()
        if not statement_digest:
            return None
        return AttestRequestV2(
            bounds=bounds,
            backend_request=backend_request,
            statement_digest=statement_digest,
            subject_id=str(payload.get("subject_id") or ""),
            attestation_profile=str(payload.get("attestation_profile") or ""),
            **common,
        )

    return None


def adapt_v1_provider_request(
    value: LogicProviderRequest | Mapping[str, Any] | str,
    *,
    backend_request: BackendRequestV2 | Mapping[str, Any] | None = None,
    bounds: RequestBounds | Mapping[str, Any] | None = None,
    mode: ProveCheckMode | str | None = None,
) -> V1AdapterResult:
    """Adapt a v1 generic envelope into parsed / rejected / advisory.

    Parameters
    ----------
    value:
        A :class:`LogicProviderRequest`, mapping, or JSON string.
    backend_request:
        Optional admitted :class:`BackendRequestV2` supplied *outside* the
        free-form v1 payload.  Executable elevation requires this argument;
        free-form payload keys cannot provide it.
    bounds:
        Optional operation bounds.  Defaults to ``backend_request.bounds``
        when omitted.  May only tighten relative to the admitted request.
    mode:
        Optional prove/check mode override when elevating prove family ops.
    """

    try:
        # Direct @2 bodies are not dual-read through this adapter.
        if isinstance(value, Mapping) and _is_v2_typed_dict(value) and not _is_v1_envelope_dict(value):
            return V1AdapterResult(
                disposition=V1AdapterDisposition.REJECTED,
                reason=(
                    "LogicProviderProtocol@2 body cannot be dual-read as a v1 "
                    "generic payload; use admit_new_provider_write"
                ),
            )

        v1 = parse_v1_provider_envelope(value)
        operation = classify_v1_operation(v1)
        _reject_payload_backend_request_bypass(v1.payload)

        external_br = _coerce_external_backend_request(backend_request)
        external_bounds = _coerce_external_bounds(bounds, backend_request=external_br)

        elevated = _try_elevate(
            v1,
            operation,
            backend_request=external_br,
            bounds=external_bounds,
            mode=mode,
        )
        if elevated is not None:
            # Re-admit through the @2 gate so elevation cannot loosen contracts.
            admitted = admit_provider_request_v2(elevated)
            return V1AdapterResult(
                disposition=V1AdapterDisposition.PARSED,
                operation=ProtocolOperationV2(admitted.operation.value),
                request_v2=admitted,
                reason=(
                    f"v1 operation {operation.value!r} elevated to "
                    f"{LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE}"
                ),
                v1_request=v1,
            )

        # Operation known but not elevatable → advisory retention.
        if is_executable_operation(operation) and external_br is None:
            reason = (
                f"v1 operation {operation.value!r} retained as advisory; "
                f"executable elevation requires an admitted "
                f"{BACKEND_REQUEST_V2_INTERFACE} supplied outside the free-form "
                "payload"
            )
        elif is_executable_operation(operation) and external_bounds is None:
            reason = (
                f"v1 operation {operation.value!r} retained as advisory; "
                "executable elevation requires positive finite bounds"
            )
        else:
            reason = (
                f"v1 operation {operation.value!r} retained as advisory; "
                "typed elevation fields are incomplete"
            )
        advisory = AdvisoryV1Retention(
            request_id=v1.request_id,
            operation=operation,
            payload=dict(v1.payload),
            reason=reason,
        )
        return V1AdapterResult(
            disposition=V1AdapterDisposition.ADVISORY,
            operation=operation,
            advisory=advisory,
            reason=reason,
            v1_request=v1,
        )
    except V1BypassBackendRequestError as error:
        return V1AdapterResult(
            disposition=V1AdapterDisposition.REJECTED,
            reason=str(error),
        )
    except (
        V1AdapterError,
        LogicProviderContractError,
        ProtocolV2Error,
        SyntaxContractError,
    ) as error:
        return V1AdapterResult(
            disposition=V1AdapterDisposition.REJECTED,
            reason=str(error),
        )


def elevate_v1_to_v2(
    value: LogicProviderRequest | Mapping[str, Any] | str,
    *,
    backend_request: BackendRequestV2 | Mapping[str, Any] | None = None,
    bounds: RequestBounds | Mapping[str, Any] | None = None,
    mode: ProveCheckMode | str | None = None,
) -> ProviderRequestV2:
    """Strict elevation: return a typed @2 request or raise.

    Advisory and rejected dispositions raise :class:`V1AdapterError`.
    """

    result = adapt_v1_provider_request(
        value,
        backend_request=backend_request,
        bounds=bounds,
        mode=mode,
    )
    if result.disposition is V1AdapterDisposition.PARSED and result.request_v2 is not None:
        return result.request_v2
    raise V1AdapterError(
        f"v1 envelope disposition is {result.disposition.value}: {result.reason}"
    )


def retain_v1_as_advisory(
    value: LogicProviderRequest | Mapping[str, Any] | str,
) -> AdvisoryV1Retention:
    """Classify a v1 envelope and retain it as non-authoritative advisory.

    Rejected envelopes raise :class:`V1AdapterError`.  Already-elevatable
    envelopes are still retained as advisory when this function is called
    (no BackendRequest@2 is accepted), matching the fail-closed dual-read
    posture for hosts that only want advisory retention.
    """

    result = adapt_v1_provider_request(value)
    if result.disposition is V1AdapterDisposition.REJECTED:
        raise V1AdapterError(result.reason or "v1 envelope rejected")
    if result.disposition is V1AdapterDisposition.ADVISORY and result.advisory is not None:
        return result.advisory
    # Parsed capability (no backend required) still has a typed request; wrap
    # the original v1 payload as advisory when the caller asked for retention.
    if result.v1_request is None or result.operation is None:
        raise V1AdapterError("cannot retain v1 envelope as advisory")
    return AdvisoryV1Retention(
        request_id=result.v1_request.request_id,
        operation=result.operation,
        payload=dict(result.v1_request.payload),
        reason=(
            f"v1 operation {result.operation.value!r} retained as advisory "
            "by explicit request"
        ),
    )


def reject_v1_backend_request_bypass(
    value: LogicProviderRequest | Mapping[str, Any] | str,
) -> None:
    """Raise if *value* attempts free-form BackendRequest@2 bypass.

    Safe envelopes return ``None``.  Malformed non-v1 inputs raise
    :class:`V1AdapterError`.
    """

    v1 = parse_v1_provider_envelope(value)
    _reject_payload_backend_request_bypass(v1.payload)


def admit_new_provider_write(
    value: Mapping[str, Any] | ProviderRequestV2,
) -> ProviderRequestV2:
    """New-write gate: only LogicProviderProtocol@2 typed requests.

    v1 generic envelopes are rejected.  Callers that must dual-read v1 must
    use :func:`adapt_v1_provider_request` explicitly.
    """

    if isinstance(
        value,
        (
            CapabilityRequestV2,
            TranslationRequestV2,
            ProveCheckRequestV2,
            ReconstructRequestV2,
            VerifyRequestV2,
            AttestRequestV2,
        ),
    ):
        return value

    payload = _require_mapping(value, "new provider write")
    if _is_v1_envelope_dict(payload):
        raise ArbitraryPayloadProtocolError(
            "new provider writes must use LogicProviderProtocol@2; "
            "v1 generic payloads require adapt_v1_provider_request (LPC-051)"
        )
    try:
        return admit_provider_request_v2(payload)
    except ArbitraryPayloadProtocolError:
        raise
    except ProtocolV2Error as error:
        raise ProtocolV2AdmissionError(str(error)) from error


def is_executable_v1_elevation(
    result: V1AdapterResult,
) -> bool:
    """Return whether *result* elevated to an executable @2 request."""

    return (
        result.disposition is V1AdapterDisposition.PARSED
        and result.executable
        and result.backend_request is not None
    )


__all__ = [
    "ADVISORY_V1_RETENTION_SCHEMA",
    "EXECUTABLE_OPERATIONS",
    "PROTOCOL_V1_ADAPTER_INTERFACE",
    "PROTOCOL_V1_ADAPTER_SCHEMA",
    "PROTOCOL_V1_ADAPTER_VERSION",
    "AdvisoryV1Retention",
    "V1AdapterDisposition",
    "V1AdapterError",
    "V1AdapterResult",
    "V1BypassBackendRequestError",
    "adapt_v1_provider_request",
    "admit_new_provider_write",
    "classify_v1_operation",
    "elevate_v1_to_v2",
    "is_executable_v1_elevation",
    "parse_v1_provider_envelope",
    "reject_v1_backend_request_bypass",
    "retain_v1_as_advisory",
]
