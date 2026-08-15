"""LogicProviderProtocol@2 — operation-specific typed provider requests (LPC-050).

Interface: ``LogicProviderProtocol@2``.

Replaces unrestricted JSON ``payload`` routing from ``LogicProvider@1`` with
typed, operation-specific request records:

* :class:`CapabilityRequestV2` — discovery / health only (non-executable)
* :class:`TranslationRequestV2` — translation under finite bounds
* :class:`ProveCheckRequestV2` — prove or check under finite bounds
* :class:`ReconstructRequestV2` — reconstruction under finite bounds
* :class:`VerifyRequestV2` — independent verification under finite bounds
* :class:`AttestRequestV2` — attestation binding under finite bounds

Every **executable** operation requires positive finite
:class:`~ipfs_datasets_py.logic.backends.requests_v2.RequestBounds` and an
admitted :class:`~ipfs_datasets_py.logic.backends.requests_v2.BackendRequestV2`
identity.  Capability is intentionally non-executable: it may not mint proof
authority and does not require execution bounds.

Provider output remains untrusted until validation or reconstruction (see
LPC-032).  v1 generic envelopes are handled by LPC-051 adapters; this module
only admits typed @2 requests.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final, Protocol, Union, runtime_checkable

from ipfs_datasets_py.logic.backends.provider import (
    LOGIC_PROVIDER_PROTOCOL_VERSION as LOGIC_PROVIDER_V1_PROTOCOL_VERSION,
    LogicProviderContractError,
    LogicProviderOperation,
    ProviderCancellation,
    ProviderResourceBudget,
    _nonnegative_int,
    _reject_unknown,
    _text as _provider_text,
    canonical_provider_json,
)
from ipfs_datasets_py.logic.backends.requests_v2 import (
    BACKEND_REQUEST_V2_INTERFACE,
    BackendRequestV2,
    MissingBoundsError,
    RequestBounds,
    RequestV2Error,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
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

LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE: Final = "LogicProviderProtocol@2"
LOGIC_PROVIDER_PROTOCOL_VERSION: Final = 2
LOGIC_PROVIDER_PROTOCOL_V2_MODULE_VERSION: Final = "1.0.0"

LOGIC_PROVIDER_PROTOCOL_V2_SCHEMA: Final = (
    "ipfs_datasets_py/logic-provider-protocol@2"
)
CAPABILITY_REQUEST_V2_SCHEMA: Final = (
    "ipfs_datasets_py/logic-provider-capability-request@2"
)
TRANSLATION_REQUEST_V2_SCHEMA: Final = (
    "ipfs_datasets_py/logic-provider-translation-request@2"
)
PROVE_CHECK_REQUEST_V2_SCHEMA: Final = (
    "ipfs_datasets_py/logic-provider-prove-check-request@2"
)
RECONSTRUCT_REQUEST_V2_SCHEMA: Final = (
    "ipfs_datasets_py/logic-provider-reconstruct-request@2"
)
VERIFY_REQUEST_V2_SCHEMA: Final = (
    "ipfs_datasets_py/logic-provider-verify-request@2"
)
ATTEST_REQUEST_V2_SCHEMA: Final = (
    "ipfs_datasets_py/logic-provider-attest-request@2"
)
PROTOCOL_ENVELOPE_V2_SCHEMA: Final = (
    "ipfs_datasets_py/logic-provider-envelope@2"
)

# Operations that execute work against an admitted BackendRequest@2.
EXECUTABLE_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        "translate",
        "prove",
        "check",
        "reconstruct",
        "verify",
        "attest",
    }
)

# Closed set of operation names admitted by LogicProviderProtocol@2.
PROTOCOL_V2_OPERATIONS: Final[frozenset[str]] = frozenset(
    {"capability", *EXECUTABLE_OPERATIONS}
)


class ProtocolV2Error(LogicProviderContractError):
    """Raised when a LogicProviderProtocol@2 request is malformed."""


class ProtocolV2AdmissionError(ProtocolV2Error):
    """Raised when a request fails closed before provider dispatch."""


class MissingExecutableBoundsError(ProtocolV2AdmissionError, MissingBoundsError):
    """Raised when an executable operation lacks positive finite bounds."""


class ArbitraryPayloadProtocolError(ProtocolV2AdmissionError):
    """Raised when free-form payload routing is attempted on @2."""


class ProveCheckMode(str, Enum):
    """Closed modes for the prove/check request family."""

    PROVE = "prove"
    CHECK = "check"


class ProtocolOperationV2(str, Enum):
    """Closed operation vocabulary for LogicProviderProtocol@2."""

    CAPABILITY = "capability"
    TRANSLATE = "translate"
    PROVE = "prove"
    CHECK = "check"
    RECONSTRUCT = "reconstruct"
    VERIFY = "verify"
    ATTEST = "attest"

    @property
    def executable(self) -> bool:
        return self.value in EXECUTABLE_OPERATIONS

    @property
    def prove_check_family(self) -> bool:
        return self in {ProtocolOperationV2.PROVE, ProtocolOperationV2.CHECK}


def is_executable_operation(operation: ProtocolOperationV2 | str) -> bool:
    """Return whether *operation* requires positive finite execution bounds."""

    value = (
        operation.value
        if isinstance(operation, ProtocolOperationV2)
        else str(operation)
    )
    return value in EXECUTABLE_OPERATIONS


def _new_request_id() -> str:
    return uuid.uuid4().hex


def _coerce_operation(
    value: object, field_name: str = "operation"
) -> ProtocolOperationV2:
    try:
        return ProtocolOperationV2(str(getattr(value, "value", value)))
    except ValueError as error:
        allowed = ", ".join(sorted(PROTOCOL_V2_OPERATIONS))
        raise ProtocolV2Error(
            f"{field_name} must be one of: {allowed}; got {value!r}"
        ) from error


def _coerce_bounds(
    value: object,
    *,
    required: bool,
    field_name: str = "bounds",
) -> RequestBounds | None:
    if value is None:
        if required:
            raise MissingExecutableBoundsError(
                f"{field_name} are required; executable LogicProviderProtocol@2 "
                "operations reject missing bounds"
            )
        return None
    if isinstance(value, RequestBounds):
        return value
    try:
        return RequestBounds.from_dict(_require_mapping(value, field_name))
    except MissingBoundsError as error:
        raise MissingExecutableBoundsError(str(error)) from error
    except RequestV2Error as error:
        raise ProtocolV2Error(str(error)) from error


def _coerce_backend_request(
    value: object,
    *,
    required: bool,
    field_name: str = "backend_request",
) -> BackendRequestV2 | None:
    if value is None:
        if required:
            raise ProtocolV2AdmissionError(
                f"{field_name} is required; executable operations must bind "
                f"an admitted {BACKEND_REQUEST_V2_INTERFACE}"
            )
        return None
    if isinstance(value, BackendRequestV2):
        return value
    if isinstance(value, Mapping):
        try:
            return BackendRequestV2.from_dict(value)
        except Exception as error:
            raise ProtocolV2AdmissionError(
                f"{field_name} must be an admitted BackendRequest@2: {error}"
            ) from error
    raise ProtocolV2AdmissionError(
        f"{field_name} must be BackendRequest@2 or a mapping; got "
        f"{type(value).__name__}"
    )


def _coerce_resource_budget(
    value: object,
) -> ProviderResourceBudget:
    if value is None:
        return ProviderResourceBudget()
    if isinstance(value, ProviderResourceBudget):
        return value
    return ProviderResourceBudget.from_dict(_require_mapping(value, "resource_budget"))


def _coerce_cancellation(
    value: object,
) -> ProviderCancellation | None:
    if value is None:
        return None
    if isinstance(value, ProviderCancellation):
        return value
    return ProviderCancellation.from_dict(_require_mapping(value, "cancellation"))


def _forbid_free_form_payload(payload: Mapping[str, Any], record_name: str) -> None:
    """Reject residual free-form routing keys on typed @2 records."""

    forbidden = {
        "payload",
        "raw_formula",
        "raw_source",
        "opaque_extension",
        "arbitrary_payload",
        "free_form_family",
        "logic_family",
    }
    for key in payload:
        if key in forbidden:
            raise ArbitraryPayloadProtocolError(
                f"{record_name} rejects free-form routing key {key!r}; "
                "LogicProviderProtocol@2 uses operation-specific typed fields only"
            )


def _string_tuple(
    value: object,
    field_name: str,
    *,
    maximum_item: int = 128,
    maximum_items: int = 256,
) -> tuple[str, ...]:
    items = tuple(
        _text(item, f"{field_name} item", maximum=maximum_item)
        for item in _require_sequence(value, field_name)
    )
    if len(items) > maximum_items:
        raise ProtocolV2Error(f"{field_name} exceeds hard ceiling {maximum_items}")
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            raise ProtocolV2Error(f"{field_name} values must be unique")
        seen.add(item)
        ordered.append(item)
    return tuple(ordered)


def _common_post_init(
    self: Any,
    *,
    bounds_required: bool,
    backend_required: bool,
    schema_version: str,
    expected_schema: str,
) -> None:
    object.__setattr__(
        self,
        "request_id",
        _record_id(self.request_id, "request_id")
        if self.request_id
        else _new_request_id(),
    )
    if self.protocol_version != LOGIC_PROVIDER_PROTOCOL_VERSION:
        raise ProtocolV2Error(
            f"unsupported protocol_version {self.protocol_version!r}; "
            f"LogicProviderProtocol@2 requires {LOGIC_PROVIDER_PROTOCOL_VERSION}"
        )
    if schema_version != expected_schema:
        raise ProtocolV2Error(
            f"unsupported schema_version {schema_version!r}; expected "
            f"{expected_schema!r}"
        )
    object.__setattr__(self, "schema_version", schema_version)

    bounds = _coerce_bounds(self.bounds, required=bounds_required)
    object.__setattr__(self, "bounds", bounds)

    backend = _coerce_backend_request(
        self.backend_request, required=backend_required
    )
    object.__setattr__(self, "backend_request", backend)

    budget = _coerce_resource_budget(self.resource_budget)
    object.__setattr__(self, "resource_budget", budget)

    cancellation = _coerce_cancellation(self.cancellation)
    object.__setattr__(self, "cancellation", cancellation)

    if not isinstance(self.network_allowed, bool):
        raise ProtocolV2Error("network_allowed must be a boolean")
    if self.network_allowed and not budget.network_allowed:
        raise ProtocolV2Error(
            "request network access exceeds its resource budget"
        )

    if self.deadline_unix_ms is not None:
        _nonnegative_int(self.deadline_unix_ms, "deadline_unix_ms")

    metadata = _freeze_mapping(self.metadata, "metadata")
    _forbid_free_form_payload(metadata, "metadata")
    object.__setattr__(self, "metadata", metadata)

    if backend is not None and bounds is not None:
        # Executable ops must not loosen the admitted BackendRequest@2 bounds.
        br_bounds = backend.bounds
        assert isinstance(br_bounds, RequestBounds)
        if (
            bounds.timeout_ms > br_bounds.timeout_ms
            or bounds.max_steps > br_bounds.max_steps
            or bounds.max_memory_bytes > br_bounds.max_memory_bytes
            or bounds.max_output_bytes > br_bounds.max_output_bytes
        ):
            raise ProtocolV2AdmissionError(
                "operation bounds cannot exceed admitted BackendRequest@2 bounds"
            )


def _common_dict(self: Any) -> dict[str, Any]:
    return {
        "schema_version": self.schema_version,
        "protocol_version": self.protocol_version,
        "interface": LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE,
        "request_id": self.request_id,
        "operation": self.operation.value
        if isinstance(self.operation, ProtocolOperationV2)
        else str(self.operation),
        "bounds": None if self.bounds is None else self.bounds.to_dict(),
        "backend_request": (
            None
            if self.backend_request is None
            else self.backend_request.to_dict()
        ),
        "resource_budget": self.resource_budget.to_dict(),
        "cancellation": (
            None if self.cancellation is None else self.cancellation.to_dict()
        ),
        "network_allowed": self.network_allowed,
        "deadline_unix_ms": self.deadline_unix_ms,
        "metadata": dict(self.metadata),
    }


# ---------------------------------------------------------------------------
# Capability (non-executable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CapabilityRequestV2:
    """Typed capability / discovery request (non-executable).

    Capability probes report availability and declared features only.  They
    never establish proof authority and do not require execution bounds.
    """

    request_id: str = field(default_factory=_new_request_id)
    provider_id: str = ""
    feature_query: tuple[str, ...] = ()
    include_versions: bool = False
    bounds: RequestBounds | Mapping[str, Any] | None = None
    backend_request: BackendRequestV2 | Mapping[str, Any] | None = None
    resource_budget: ProviderResourceBudget | Mapping[str, Any] = field(
        default_factory=ProviderResourceBudget
    )
    cancellation: ProviderCancellation | Mapping[str, Any] | None = None
    network_allowed: bool = False
    deadline_unix_ms: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    protocol_version: int = LOGIC_PROVIDER_PROTOCOL_VERSION
    schema_version: str = CAPABILITY_REQUEST_V2_SCHEMA

    interface: ClassVar[str] = LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE

    @property
    def operation(self) -> ProtocolOperationV2:
        return ProtocolOperationV2.CAPABILITY

    def __post_init__(self) -> None:
        _common_post_init(
            self,
            bounds_required=False,
            backend_required=False,
            schema_version=self.schema_version,
            expected_schema=CAPABILITY_REQUEST_V2_SCHEMA,
        )
        object.__setattr__(
            self,
            "provider_id",
            _provider_text(
                self.provider_id, "provider_id", optional=True, maximum=128
            ),
        )
        object.__setattr__(
            self,
            "feature_query",
            _string_tuple(self.feature_query, "feature_query"),
        )
        if not isinstance(self.include_versions, bool):
            raise ProtocolV2Error("include_versions must be a boolean")

    def to_dict(self) -> dict[str, Any]:
        payload = _common_dict(self)
        payload.update(
            {
                "provider_id": self.provider_id,
                "feature_query": list(self.feature_query),
                "include_versions": self.include_versions,
            }
        )
        return payload

    def to_json(self) -> str:
        return canonical_provider_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CapabilityRequestV2":
        payload = _require_mapping(value, "CapabilityRequestV2")
        _forbid_free_form_payload(payload, "CapabilityRequestV2")
        _reject_unknown(
            payload,
            frozenset(
                {
                    "schema_version",
                    "protocol_version",
                    "interface",
                    "request_id",
                    "operation",
                    "provider_id",
                    "feature_query",
                    "include_versions",
                    "bounds",
                    "backend_request",
                    "resource_budget",
                    "cancellation",
                    "network_allowed",
                    "deadline_unix_ms",
                    "metadata",
                }
            ),
            "CapabilityRequestV2",
        )
        operation = payload.get("operation", ProtocolOperationV2.CAPABILITY.value)
        if str(getattr(operation, "value", operation)) != ProtocolOperationV2.CAPABILITY.value:
            raise ProtocolV2Error(
                "CapabilityRequestV2 requires operation='capability'"
            )
        return cls(
            request_id=str(payload.get("request_id") or _new_request_id()),
            provider_id=str(payload.get("provider_id") or ""),
            feature_query=tuple(payload.get("feature_query") or ()),
            include_versions=bool(payload.get("include_versions", False)),
            bounds=payload.get("bounds"),
            backend_request=payload.get("backend_request"),
            resource_budget=payload.get("resource_budget") or {},
            cancellation=payload.get("cancellation"),
            network_allowed=bool(payload.get("network_allowed", False)),
            deadline_unix_ms=payload.get("deadline_unix_ms"),
            metadata=payload.get("metadata") or {},
            protocol_version=int(
                payload.get("protocol_version", LOGIC_PROVIDER_PROTOCOL_VERSION)
            ),
            schema_version=str(
                payload.get("schema_version") or CAPABILITY_REQUEST_V2_SCHEMA
            ),
        )


# ---------------------------------------------------------------------------
# Translation (executable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TranslationRequestV2:
    """Typed translation request under positive finite bounds."""

    bounds: RequestBounds | Mapping[str, Any]
    backend_request: BackendRequestV2 | Mapping[str, Any]
    source_encoding: str
    target_encoding: str
    request_id: str = field(default_factory=_new_request_id)
    source_artifact_digest: str = ""
    preservation_claim: str = ""
    resource_budget: ProviderResourceBudget | Mapping[str, Any] = field(
        default_factory=ProviderResourceBudget
    )
    cancellation: ProviderCancellation | Mapping[str, Any] | None = None
    network_allowed: bool = False
    deadline_unix_ms: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    protocol_version: int = LOGIC_PROVIDER_PROTOCOL_VERSION
    schema_version: str = TRANSLATION_REQUEST_V2_SCHEMA

    interface: ClassVar[str] = LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE

    @property
    def operation(self) -> ProtocolOperationV2:
        return ProtocolOperationV2.TRANSLATE

    def __post_init__(self) -> None:
        _common_post_init(
            self,
            bounds_required=True,
            backend_required=True,
            schema_version=self.schema_version,
            expected_schema=TRANSLATION_REQUEST_V2_SCHEMA,
        )
        object.__setattr__(
            self,
            "source_encoding",
            _text(self.source_encoding, "source_encoding", maximum=128),
        )
        object.__setattr__(
            self,
            "target_encoding",
            _text(self.target_encoding, "target_encoding", maximum=128),
        )
        if self.source_artifact_digest:
            object.__setattr__(
                self,
                "source_artifact_digest",
                _sha256_hex(self.source_artifact_digest, "source_artifact_digest"),
            )
        else:
            object.__setattr__(self, "source_artifact_digest", "")
        object.__setattr__(
            self,
            "preservation_claim",
            _provider_text(
                self.preservation_claim,
                "preservation_claim",
                optional=True,
                maximum=128,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = _common_dict(self)
        payload.update(
            {
                "source_encoding": self.source_encoding,
                "target_encoding": self.target_encoding,
                "source_artifact_digest": self.source_artifact_digest,
                "preservation_claim": self.preservation_claim,
            }
        )
        return payload

    def to_json(self) -> str:
        return canonical_provider_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TranslationRequestV2":
        payload = _require_mapping(value, "TranslationRequestV2")
        _forbid_free_form_payload(payload, "TranslationRequestV2")
        _reject_unknown(
            payload,
            frozenset(
                {
                    "schema_version",
                    "protocol_version",
                    "interface",
                    "request_id",
                    "operation",
                    "bounds",
                    "backend_request",
                    "source_encoding",
                    "target_encoding",
                    "source_artifact_digest",
                    "preservation_claim",
                    "resource_budget",
                    "cancellation",
                    "network_allowed",
                    "deadline_unix_ms",
                    "metadata",
                }
            ),
            "TranslationRequestV2",
        )
        operation = payload.get("operation", ProtocolOperationV2.TRANSLATE.value)
        if str(getattr(operation, "value", operation)) != ProtocolOperationV2.TRANSLATE.value:
            raise ProtocolV2Error(
                "TranslationRequestV2 requires operation='translate'"
            )
        if "bounds" not in payload:
            raise MissingExecutableBoundsError(
                "TranslationRequestV2 requires positive finite bounds"
            )
        if "backend_request" not in payload:
            raise ProtocolV2AdmissionError(
                "TranslationRequestV2 requires an admitted BackendRequest@2"
            )
        return cls(
            request_id=str(payload.get("request_id") or _new_request_id()),
            bounds=payload["bounds"],
            backend_request=payload["backend_request"],
            source_encoding=str(payload.get("source_encoding") or ""),
            target_encoding=str(payload.get("target_encoding") or ""),
            source_artifact_digest=str(payload.get("source_artifact_digest") or ""),
            preservation_claim=str(payload.get("preservation_claim") or ""),
            resource_budget=payload.get("resource_budget") or {},
            cancellation=payload.get("cancellation"),
            network_allowed=bool(payload.get("network_allowed", False)),
            deadline_unix_ms=payload.get("deadline_unix_ms"),
            metadata=payload.get("metadata") or {},
            protocol_version=int(
                payload.get("protocol_version", LOGIC_PROVIDER_PROTOCOL_VERSION)
            ),
            schema_version=str(
                payload.get("schema_version") or TRANSLATION_REQUEST_V2_SCHEMA
            ),
        )


# ---------------------------------------------------------------------------
# Prove / check (executable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProveCheckRequestV2:
    """Typed prove or check request under positive finite bounds.

    ``mode`` selects prove vs check within one request family.  Both modes are
    executable and require positive finite bounds plus BackendRequest@2.
    """

    bounds: RequestBounds | Mapping[str, Any]
    backend_request: BackendRequestV2 | Mapping[str, Any]
    mode: ProveCheckMode | str = ProveCheckMode.PROVE
    request_id: str = field(default_factory=_new_request_id)
    statement: str = ""
    goal_digest: str = ""
    resource_budget: ProviderResourceBudget | Mapping[str, Any] = field(
        default_factory=ProviderResourceBudget
    )
    cancellation: ProviderCancellation | Mapping[str, Any] | None = None
    network_allowed: bool = False
    deadline_unix_ms: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    protocol_version: int = LOGIC_PROVIDER_PROTOCOL_VERSION
    schema_version: str = PROVE_CHECK_REQUEST_V2_SCHEMA

    interface: ClassVar[str] = LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE

    @property
    def operation(self) -> ProtocolOperationV2:
        mode = self.mode
        if not isinstance(mode, ProveCheckMode):
            mode = ProveCheckMode(str(mode))
        return (
            ProtocolOperationV2.PROVE
            if mode is ProveCheckMode.PROVE
            else ProtocolOperationV2.CHECK
        )

    def __post_init__(self) -> None:
        try:
            mode = (
                self.mode
                if isinstance(self.mode, ProveCheckMode)
                else ProveCheckMode(str(self.mode))
            )
        except ValueError as error:
            raise ProtocolV2Error(
                "ProveCheckRequestV2.mode must be 'prove' or 'check'"
            ) from error
        object.__setattr__(self, "mode", mode)
        _common_post_init(
            self,
            bounds_required=True,
            backend_required=True,
            schema_version=self.schema_version,
            expected_schema=PROVE_CHECK_REQUEST_V2_SCHEMA,
        )
        object.__setattr__(
            self,
            "statement",
            _provider_text(self.statement, "statement", optional=True, maximum=16384),
        )
        if self.goal_digest:
            object.__setattr__(
                self, "goal_digest", _sha256_hex(self.goal_digest, "goal_digest")
            )
        else:
            object.__setattr__(self, "goal_digest", "")

    def to_dict(self) -> dict[str, Any]:
        payload = _common_dict(self)
        payload.update(
            {
                "mode": self.mode.value
                if isinstance(self.mode, ProveCheckMode)
                else str(self.mode),
                "statement": self.statement,
                "goal_digest": self.goal_digest,
            }
        )
        return payload

    def to_json(self) -> str:
        return canonical_provider_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProveCheckRequestV2":
        payload = _require_mapping(value, "ProveCheckRequestV2")
        _forbid_free_form_payload(payload, "ProveCheckRequestV2")
        _reject_unknown(
            payload,
            frozenset(
                {
                    "schema_version",
                    "protocol_version",
                    "interface",
                    "request_id",
                    "operation",
                    "mode",
                    "bounds",
                    "backend_request",
                    "statement",
                    "goal_digest",
                    "resource_budget",
                    "cancellation",
                    "network_allowed",
                    "deadline_unix_ms",
                    "metadata",
                }
            ),
            "ProveCheckRequestV2",
        )
        if "bounds" not in payload:
            raise MissingExecutableBoundsError(
                "ProveCheckRequestV2 requires positive finite bounds"
            )
        if "backend_request" not in payload:
            raise ProtocolV2AdmissionError(
                "ProveCheckRequestV2 requires an admitted BackendRequest@2"
            )
        mode_value = payload.get("mode")
        if mode_value is None:
            operation = payload.get("operation", ProveCheckMode.PROVE.value)
            mode_value = str(getattr(operation, "value", operation))
            if mode_value not in {
                ProveCheckMode.PROVE.value,
                ProveCheckMode.CHECK.value,
            }:
                raise ProtocolV2Error(
                    "ProveCheckRequestV2 requires mode or operation in "
                    "{'prove', 'check'}"
                )
        return cls(
            request_id=str(payload.get("request_id") or _new_request_id()),
            bounds=payload["bounds"],
            backend_request=payload["backend_request"],
            mode=str(mode_value),
            statement=str(payload.get("statement") or ""),
            goal_digest=str(payload.get("goal_digest") or ""),
            resource_budget=payload.get("resource_budget") or {},
            cancellation=payload.get("cancellation"),
            network_allowed=bool(payload.get("network_allowed", False)),
            deadline_unix_ms=payload.get("deadline_unix_ms"),
            metadata=payload.get("metadata") or {},
            protocol_version=int(
                payload.get("protocol_version", LOGIC_PROVIDER_PROTOCOL_VERSION)
            ),
            schema_version=str(
                payload.get("schema_version") or PROVE_CHECK_REQUEST_V2_SCHEMA
            ),
        )


# ---------------------------------------------------------------------------
# Reconstruct (executable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReconstructRequestV2:
    """Typed reconstruction request under positive finite bounds."""

    bounds: RequestBounds | Mapping[str, Any]
    backend_request: BackendRequestV2 | Mapping[str, Any]
    candidate_digest: str
    request_id: str = field(default_factory=_new_request_id)
    candidate_artifact_id: str = ""
    kernel_id: str = ""
    resource_budget: ProviderResourceBudget | Mapping[str, Any] = field(
        default_factory=ProviderResourceBudget
    )
    cancellation: ProviderCancellation | Mapping[str, Any] | None = None
    network_allowed: bool = False
    deadline_unix_ms: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    protocol_version: int = LOGIC_PROVIDER_PROTOCOL_VERSION
    schema_version: str = RECONSTRUCT_REQUEST_V2_SCHEMA

    interface: ClassVar[str] = LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE

    @property
    def operation(self) -> ProtocolOperationV2:
        return ProtocolOperationV2.RECONSTRUCT

    def __post_init__(self) -> None:
        _common_post_init(
            self,
            bounds_required=True,
            backend_required=True,
            schema_version=self.schema_version,
            expected_schema=RECONSTRUCT_REQUEST_V2_SCHEMA,
        )
        object.__setattr__(
            self,
            "candidate_digest",
            _sha256_hex(self.candidate_digest, "candidate_digest"),
        )
        object.__setattr__(
            self,
            "candidate_artifact_id",
            _provider_text(
                self.candidate_artifact_id,
                "candidate_artifact_id",
                optional=True,
                maximum=256,
            ),
        )
        object.__setattr__(
            self,
            "kernel_id",
            _provider_text(self.kernel_id, "kernel_id", optional=True, maximum=128),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = _common_dict(self)
        payload.update(
            {
                "candidate_digest": self.candidate_digest,
                "candidate_artifact_id": self.candidate_artifact_id,
                "kernel_id": self.kernel_id,
            }
        )
        return payload

    def to_json(self) -> str:
        return canonical_provider_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReconstructRequestV2":
        payload = _require_mapping(value, "ReconstructRequestV2")
        _forbid_free_form_payload(payload, "ReconstructRequestV2")
        _reject_unknown(
            payload,
            frozenset(
                {
                    "schema_version",
                    "protocol_version",
                    "interface",
                    "request_id",
                    "operation",
                    "bounds",
                    "backend_request",
                    "candidate_digest",
                    "candidate_artifact_id",
                    "kernel_id",
                    "resource_budget",
                    "cancellation",
                    "network_allowed",
                    "deadline_unix_ms",
                    "metadata",
                }
            ),
            "ReconstructRequestV2",
        )
        operation = payload.get("operation", ProtocolOperationV2.RECONSTRUCT.value)
        if (
            str(getattr(operation, "value", operation))
            != ProtocolOperationV2.RECONSTRUCT.value
        ):
            raise ProtocolV2Error(
                "ReconstructRequestV2 requires operation='reconstruct'"
            )
        if "bounds" not in payload:
            raise MissingExecutableBoundsError(
                "ReconstructRequestV2 requires positive finite bounds"
            )
        if "backend_request" not in payload:
            raise ProtocolV2AdmissionError(
                "ReconstructRequestV2 requires an admitted BackendRequest@2"
            )
        return cls(
            request_id=str(payload.get("request_id") or _new_request_id()),
            bounds=payload["bounds"],
            backend_request=payload["backend_request"],
            candidate_digest=str(payload.get("candidate_digest") or ""),
            candidate_artifact_id=str(payload.get("candidate_artifact_id") or ""),
            kernel_id=str(payload.get("kernel_id") or ""),
            resource_budget=payload.get("resource_budget") or {},
            cancellation=payload.get("cancellation"),
            network_allowed=bool(payload.get("network_allowed", False)),
            deadline_unix_ms=payload.get("deadline_unix_ms"),
            metadata=payload.get("metadata") or {},
            protocol_version=int(
                payload.get("protocol_version", LOGIC_PROVIDER_PROTOCOL_VERSION)
            ),
            schema_version=str(
                payload.get("schema_version") or RECONSTRUCT_REQUEST_V2_SCHEMA
            ),
        )


# ---------------------------------------------------------------------------
# Verify (executable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VerifyRequestV2:
    """Typed independent verification request under positive finite bounds."""

    bounds: RequestBounds | Mapping[str, Any]
    backend_request: BackendRequestV2 | Mapping[str, Any]
    evidence_digest: str
    request_id: str = field(default_factory=_new_request_id)
    evidence_kind: str = ""
    verifier_id: str = ""
    resource_budget: ProviderResourceBudget | Mapping[str, Any] = field(
        default_factory=ProviderResourceBudget
    )
    cancellation: ProviderCancellation | Mapping[str, Any] | None = None
    network_allowed: bool = False
    deadline_unix_ms: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    protocol_version: int = LOGIC_PROVIDER_PROTOCOL_VERSION
    schema_version: str = VERIFY_REQUEST_V2_SCHEMA

    interface: ClassVar[str] = LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE

    @property
    def operation(self) -> ProtocolOperationV2:
        return ProtocolOperationV2.VERIFY

    def __post_init__(self) -> None:
        _common_post_init(
            self,
            bounds_required=True,
            backend_required=True,
            schema_version=self.schema_version,
            expected_schema=VERIFY_REQUEST_V2_SCHEMA,
        )
        object.__setattr__(
            self,
            "evidence_digest",
            _sha256_hex(self.evidence_digest, "evidence_digest"),
        )
        object.__setattr__(
            self,
            "evidence_kind",
            _provider_text(
                self.evidence_kind, "evidence_kind", optional=True, maximum=128
            ),
        )
        object.__setattr__(
            self,
            "verifier_id",
            _provider_text(
                self.verifier_id, "verifier_id", optional=True, maximum=128
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = _common_dict(self)
        payload.update(
            {
                "evidence_digest": self.evidence_digest,
                "evidence_kind": self.evidence_kind,
                "verifier_id": self.verifier_id,
            }
        )
        return payload

    def to_json(self) -> str:
        return canonical_provider_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "VerifyRequestV2":
        payload = _require_mapping(value, "VerifyRequestV2")
        _forbid_free_form_payload(payload, "VerifyRequestV2")
        _reject_unknown(
            payload,
            frozenset(
                {
                    "schema_version",
                    "protocol_version",
                    "interface",
                    "request_id",
                    "operation",
                    "bounds",
                    "backend_request",
                    "evidence_digest",
                    "evidence_kind",
                    "verifier_id",
                    "resource_budget",
                    "cancellation",
                    "network_allowed",
                    "deadline_unix_ms",
                    "metadata",
                }
            ),
            "VerifyRequestV2",
        )
        operation = payload.get("operation", ProtocolOperationV2.VERIFY.value)
        if str(getattr(operation, "value", operation)) != ProtocolOperationV2.VERIFY.value:
            raise ProtocolV2Error("VerifyRequestV2 requires operation='verify'")
        if "bounds" not in payload:
            raise MissingExecutableBoundsError(
                "VerifyRequestV2 requires positive finite bounds"
            )
        if "backend_request" not in payload:
            raise ProtocolV2AdmissionError(
                "VerifyRequestV2 requires an admitted BackendRequest@2"
            )
        return cls(
            request_id=str(payload.get("request_id") or _new_request_id()),
            bounds=payload["bounds"],
            backend_request=payload["backend_request"],
            evidence_digest=str(payload.get("evidence_digest") or ""),
            evidence_kind=str(payload.get("evidence_kind") or ""),
            verifier_id=str(payload.get("verifier_id") or ""),
            resource_budget=payload.get("resource_budget") or {},
            cancellation=payload.get("cancellation"),
            network_allowed=bool(payload.get("network_allowed", False)),
            deadline_unix_ms=payload.get("deadline_unix_ms"),
            metadata=payload.get("metadata") or {},
            protocol_version=int(
                payload.get("protocol_version", LOGIC_PROVIDER_PROTOCOL_VERSION)
            ),
            schema_version=str(
                payload.get("schema_version") or VERIFY_REQUEST_V2_SCHEMA
            ),
        )


# ---------------------------------------------------------------------------
# Attest (executable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AttestRequestV2:
    """Typed attestation request under positive finite bounds."""

    bounds: RequestBounds | Mapping[str, Any]
    backend_request: BackendRequestV2 | Mapping[str, Any]
    statement_digest: str
    request_id: str = field(default_factory=_new_request_id)
    subject_id: str = ""
    attestation_profile: str = ""
    resource_budget: ProviderResourceBudget | Mapping[str, Any] = field(
        default_factory=ProviderResourceBudget
    )
    cancellation: ProviderCancellation | Mapping[str, Any] | None = None
    network_allowed: bool = False
    deadline_unix_ms: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    protocol_version: int = LOGIC_PROVIDER_PROTOCOL_VERSION
    schema_version: str = ATTEST_REQUEST_V2_SCHEMA

    interface: ClassVar[str] = LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE

    @property
    def operation(self) -> ProtocolOperationV2:
        return ProtocolOperationV2.ATTEST

    def __post_init__(self) -> None:
        _common_post_init(
            self,
            bounds_required=True,
            backend_required=True,
            schema_version=self.schema_version,
            expected_schema=ATTEST_REQUEST_V2_SCHEMA,
        )
        object.__setattr__(
            self,
            "statement_digest",
            _sha256_hex(self.statement_digest, "statement_digest"),
        )
        object.__setattr__(
            self,
            "subject_id",
            _provider_text(self.subject_id, "subject_id", optional=True, maximum=256),
        )
        object.__setattr__(
            self,
            "attestation_profile",
            _provider_text(
                self.attestation_profile,
                "attestation_profile",
                optional=True,
                maximum=128,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = _common_dict(self)
        payload.update(
            {
                "statement_digest": self.statement_digest,
                "subject_id": self.subject_id,
                "attestation_profile": self.attestation_profile,
            }
        )
        return payload

    def to_json(self) -> str:
        return canonical_provider_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AttestRequestV2":
        payload = _require_mapping(value, "AttestRequestV2")
        _forbid_free_form_payload(payload, "AttestRequestV2")
        _reject_unknown(
            payload,
            frozenset(
                {
                    "schema_version",
                    "protocol_version",
                    "interface",
                    "request_id",
                    "operation",
                    "bounds",
                    "backend_request",
                    "statement_digest",
                    "subject_id",
                    "attestation_profile",
                    "resource_budget",
                    "cancellation",
                    "network_allowed",
                    "deadline_unix_ms",
                    "metadata",
                }
            ),
            "AttestRequestV2",
        )
        operation = payload.get("operation", ProtocolOperationV2.ATTEST.value)
        if str(getattr(operation, "value", operation)) != ProtocolOperationV2.ATTEST.value:
            raise ProtocolV2Error("AttestRequestV2 requires operation='attest'")
        if "bounds" not in payload:
            raise MissingExecutableBoundsError(
                "AttestRequestV2 requires positive finite bounds"
            )
        if "backend_request" not in payload:
            raise ProtocolV2AdmissionError(
                "AttestRequestV2 requires an admitted BackendRequest@2"
            )
        return cls(
            request_id=str(payload.get("request_id") or _new_request_id()),
            bounds=payload["bounds"],
            backend_request=payload["backend_request"],
            statement_digest=str(payload.get("statement_digest") or ""),
            subject_id=str(payload.get("subject_id") or ""),
            attestation_profile=str(payload.get("attestation_profile") or ""),
            resource_budget=payload.get("resource_budget") or {},
            cancellation=payload.get("cancellation"),
            network_allowed=bool(payload.get("network_allowed", False)),
            deadline_unix_ms=payload.get("deadline_unix_ms"),
            metadata=payload.get("metadata") or {},
            protocol_version=int(
                payload.get("protocol_version", LOGIC_PROVIDER_PROTOCOL_VERSION)
            ),
            schema_version=str(
                payload.get("schema_version") or ATTEST_REQUEST_V2_SCHEMA
            ),
        )


# ---------------------------------------------------------------------------
# Discriminated envelope + protocol surface
# ---------------------------------------------------------------------------

ProviderRequestV2 = Union[
    CapabilityRequestV2,
    TranslationRequestV2,
    ProveCheckRequestV2,
    ReconstructRequestV2,
    VerifyRequestV2,
    AttestRequestV2,
]

_OPERATION_TO_REQUEST: Final[
    Mapping[str, type[ProviderRequestV2]]
] = {
    ProtocolOperationV2.CAPABILITY.value: CapabilityRequestV2,
    ProtocolOperationV2.TRANSLATE.value: TranslationRequestV2,
    ProtocolOperationV2.PROVE.value: ProveCheckRequestV2,
    ProtocolOperationV2.CHECK.value: ProveCheckRequestV2,
    ProtocolOperationV2.RECONSTRUCT.value: ReconstructRequestV2,
    ProtocolOperationV2.VERIFY.value: VerifyRequestV2,
    ProtocolOperationV2.ATTEST.value: AttestRequestV2,
}


def admit_provider_request_v2(value: Mapping[str, Any] | ProviderRequestV2) -> ProviderRequestV2:
    """Admit a typed LogicProviderProtocol@2 request (fail closed).

    Free-form ``payload`` routing is rejected.  Executable operations without
    positive finite bounds fail closed before any provider dispatch.
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

    payload = _require_mapping(value, "ProviderRequestV2")

    # Explicit rejection of v1-style generic envelopes used as @2 bodies.
    # Checked before free-form key rejection so the diagnostic names the
    # generation gap (LPC-051 adapter) rather than a generic field error.
    schema = str(payload.get("schema_version") or "")
    try:
        protocol_version = int(
            payload.get("protocol_version", LOGIC_PROVIDER_PROTOCOL_VERSION) or 0
        )
    except (TypeError, ValueError):
        protocol_version = -1
    if schema == "ipfs_datasets_py/logic-provider-request@1" or (
        protocol_version == LOGIC_PROVIDER_V1_PROTOCOL_VERSION and "payload" in payload
    ):
        raise ArbitraryPayloadProtocolError(
            "LogicProvider@1 generic payloads cannot be admitted as "
            "LogicProviderProtocol@2; use an explicit v1 adapter (LPC-051)"
        )

    _forbid_free_form_payload(payload, "ProviderRequestV2")

    operation_raw = payload.get("operation")
    if operation_raw is None:
        # Infer from schema_version when operation is omitted.
        schema = str(payload.get("schema_version") or "")
        schema_to_op = {
            CAPABILITY_REQUEST_V2_SCHEMA: ProtocolOperationV2.CAPABILITY.value,
            TRANSLATION_REQUEST_V2_SCHEMA: ProtocolOperationV2.TRANSLATE.value,
            PROVE_CHECK_REQUEST_V2_SCHEMA: ProtocolOperationV2.PROVE.value,
            RECONSTRUCT_REQUEST_V2_SCHEMA: ProtocolOperationV2.RECONSTRUCT.value,
            VERIFY_REQUEST_V2_SCHEMA: ProtocolOperationV2.VERIFY.value,
            ATTEST_REQUEST_V2_SCHEMA: ProtocolOperationV2.ATTEST.value,
        }
        operation_raw = schema_to_op.get(schema)
    if operation_raw is None:
        raise ProtocolV2AdmissionError(
            "ProviderRequestV2 requires a closed operation "
            f"in {sorted(PROTOCOL_V2_OPERATIONS)}"
        )

    operation = _coerce_operation(operation_raw)
    request_cls = _OPERATION_TO_REQUEST[operation.value]
    return request_cls.from_dict(payload)


@dataclass(frozen=True, slots=True)
class ProviderProtocolEnvelopeV2:
    """Discriminated envelope carrying exactly one typed @2 request body."""

    request: ProviderRequestV2
    schema_version: str = PROTOCOL_ENVELOPE_V2_SCHEMA
    protocol_version: int = LOGIC_PROVIDER_PROTOCOL_VERSION
    interface: str = LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE

    def __post_init__(self) -> None:
        admitted = admit_provider_request_v2(self.request)
        object.__setattr__(self, "request", admitted)
        if self.protocol_version != LOGIC_PROVIDER_PROTOCOL_VERSION:
            raise ProtocolV2Error(
                "ProviderProtocolEnvelopeV2 requires protocol_version=2"
            )
        if self.schema_version != PROTOCOL_ENVELOPE_V2_SCHEMA:
            raise ProtocolV2Error(
                f"unsupported envelope schema_version {self.schema_version!r}"
            )
        if self.interface != LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE:
            raise ProtocolV2Error(
                f"unsupported envelope interface {self.interface!r}"
            )

    @property
    def operation(self) -> ProtocolOperationV2:
        return ProtocolOperationV2(self.request.operation.value)

    @property
    def executable(self) -> bool:
        return is_executable_operation(self.operation)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "protocol_version": self.protocol_version,
            "interface": self.interface,
            "operation": self.operation.value,
            "request": self.request.to_dict(),
        }

    def to_json(self) -> str:
        return canonical_provider_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProviderProtocolEnvelopeV2":
        payload = _require_mapping(value, "ProviderProtocolEnvelopeV2")
        _forbid_free_form_payload(payload, "ProviderProtocolEnvelopeV2")
        _reject_unknown(
            payload,
            frozenset(
                {
                    "schema_version",
                    "protocol_version",
                    "interface",
                    "operation",
                    "request",
                }
            ),
            "ProviderProtocolEnvelopeV2",
        )
        body = payload.get("request")
        if body is None:
            # Allow flattened envelopes where the body fields sit at the root.
            body = {
                key: item
                for key, item in payload.items()
                if key
                not in {
                    "schema_version",
                    "protocol_version",
                    "interface",
                    "operation",
                    "request",
                }
            }
            if payload.get("operation") is not None:
                body = {**body, "operation": payload["operation"]}
        if not isinstance(body, Mapping):
            raise ProtocolV2Error("envelope request body must be an object")
        if (
            "operation" not in body
            and payload.get("operation") is not None
        ):
            body = {**dict(body), "operation": payload["operation"]}
        return cls(
            request=admit_provider_request_v2(body),
            schema_version=str(
                payload.get("schema_version") or PROTOCOL_ENVELOPE_V2_SCHEMA
            ),
            protocol_version=int(
                payload.get("protocol_version", LOGIC_PROVIDER_PROTOCOL_VERSION)
            ),
            interface=str(
                payload.get("interface") or LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE
            ),
        )


@runtime_checkable
class LogicProviderProtocolV2(Protocol):
    """Structural LogicProviderProtocol@2 surface for concrete providers."""

    provider_id: str
    provider_version: str
    protocol_version: int

    def capability(
        self, request: CapabilityRequestV2
    ) -> Mapping[str, Any]:
        ...

    def translate(
        self, request: TranslationRequestV2
    ) -> Mapping[str, Any]:
        ...

    def prove(
        self, request: ProveCheckRequestV2
    ) -> Mapping[str, Any]:
        ...

    def check(
        self, request: ProveCheckRequestV2
    ) -> Mapping[str, Any]:
        ...

    def reconstruct(
        self, request: ReconstructRequestV2
    ) -> Mapping[str, Any]:
        ...

    def verify(
        self, request: VerifyRequestV2
    ) -> Mapping[str, Any]:
        ...

    def attest(
        self, request: AttestRequestV2
    ) -> Mapping[str, Any]:
        ...


def require_executable_bounds(request: ProviderRequestV2) -> RequestBounds:
    """Return positive finite bounds for an executable request (fail closed)."""

    operation = ProtocolOperationV2(request.operation.value)
    if not operation.executable:
        raise ProtocolV2Error(
            f"{operation.value} is not executable; bounds are not required"
        )
    bounds = getattr(request, "bounds", None)
    if not isinstance(bounds, RequestBounds):
        raise MissingExecutableBoundsError(
            f"{operation.value} requires positive finite bounds"
        )
    # RequestBounds already rejects non-positive values at construction.
    for field_name in (
        "timeout_ms",
        "max_steps",
        "max_memory_bytes",
        "max_output_bytes",
    ):
        value = getattr(bounds, field_name)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise MissingExecutableBoundsError(
                f"{field_name} must be a positive finite bound"
            )
    return bounds


def content_digest_for_request(request: ProviderRequestV2) -> str:
    """Stable content digest over the typed request body."""

    return content_sha256(canonical_json_bytes(request.to_dict()))


# Map @2 operations onto the v1 operation vocabulary where names align.
_V1_OPERATION_MAP: Final[Mapping[ProtocolOperationV2, LogicProviderOperation]] = {
    ProtocolOperationV2.CAPABILITY: LogicProviderOperation.CAPABILITY,
    ProtocolOperationV2.TRANSLATE: LogicProviderOperation.TRANSLATE,
    ProtocolOperationV2.PROVE: LogicProviderOperation.PROVE,
    ProtocolOperationV2.CHECK: LogicProviderOperation.PROVE,  # check rides prove wire in v1
    ProtocolOperationV2.RECONSTRUCT: LogicProviderOperation.RECONSTRUCT,
    ProtocolOperationV2.VERIFY: LogicProviderOperation.VERIFY,
    ProtocolOperationV2.ATTEST: LogicProviderOperation.ATTEST,
}


def v1_operation_for(operation: ProtocolOperationV2 | str) -> LogicProviderOperation:
    """Map a @2 operation onto the closest LogicProvider@1 operation name."""

    op = (
        operation
        if isinstance(operation, ProtocolOperationV2)
        else _coerce_operation(operation)
    )
    return _V1_OPERATION_MAP[op]


__all__ = [
    "ATTEST_REQUEST_V2_SCHEMA",
    "CAPABILITY_REQUEST_V2_SCHEMA",
    "EXECUTABLE_OPERATIONS",
    "LOGIC_PROVIDER_PROTOCOL_VERSION",
    "LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE",
    "LOGIC_PROVIDER_PROTOCOL_V2_MODULE_VERSION",
    "LOGIC_PROVIDER_PROTOCOL_V2_SCHEMA",
    "PROTOCOL_ENVELOPE_V2_SCHEMA",
    "PROTOCOL_V2_OPERATIONS",
    "PROVE_CHECK_REQUEST_V2_SCHEMA",
    "RECONSTRUCT_REQUEST_V2_SCHEMA",
    "TRANSLATION_REQUEST_V2_SCHEMA",
    "VERIFY_REQUEST_V2_SCHEMA",
    "ArbitraryPayloadProtocolError",
    "AttestRequestV2",
    "CapabilityRequestV2",
    "LogicProviderProtocolV2",
    "MissingExecutableBoundsError",
    "ProveCheckMode",
    "ProveCheckRequestV2",
    "ProtocolOperationV2",
    "ProtocolV2AdmissionError",
    "ProtocolV2Error",
    "ProviderProtocolEnvelopeV2",
    "ProviderRequestV2",
    "ReconstructRequestV2",
    "TranslationRequestV2",
    "VerifyRequestV2",
    "admit_provider_request_v2",
    "content_digest_for_request",
    "is_executable_operation",
    "require_executable_bounds",
    "v1_operation_for",
]
