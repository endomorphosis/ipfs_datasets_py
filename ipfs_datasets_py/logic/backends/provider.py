"""Canonical, package-neutral wire contract for optional logic providers.

The datasets package owns the semantic/provider boundary.  This module is
therefore intentionally a standard-library leaf: it does not import the agent
supervisor, a backend registry, a solver, an installer, or an optional provider
implementation.  Importing it is safe during capability discovery.

Version 1 uses strict JSON-compatible request and response envelopes.  Resource
limits, deadlines, network policy, and cooperative cancellation are data in
the request rather than ambient provider configuration.  A successful
response is still only provider output; consumers must independently interpret
typed evidence before granting proof authority.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final, Protocol, runtime_checkable

LOGIC_PROVIDER_PROTOCOL_VERSION: Final = 1
LOGIC_PROVIDER_SUPPORTED_PROTOCOL_VERSIONS: Final = (
    LOGIC_PROVIDER_PROTOCOL_VERSION,
)
LOGIC_PROVIDER_REQUEST_SCHEMA: Final = "ipfs_datasets_py/logic-provider-request@1"
LOGIC_PROVIDER_RESPONSE_SCHEMA: Final = "ipfs_datasets_py/logic-provider-response@1"
LOGIC_PROVIDER_RESOURCE_SCHEMA: Final = "ipfs_datasets_py/logic-provider-resource-budget@1"
LOGIC_PROVIDER_CANCELLATION_SCHEMA: Final = (
    "ipfs_datasets_py/logic-provider-cancellation@1"
)


class LogicProviderContractError(ValueError):
    """Raised when provider wire data is malformed or version-incompatible."""


class LogicProviderOperation(StrEnum):
    """Operations shared by datasets backends and supervisor adapters."""

    CAPABILITY = "capability"
    TRANSLATE = "translate"
    PROVE = "prove"
    RECONSTRUCT = "reconstruct"
    VERIFY = "verify"
    ATTEST = "attest"


class LogicProviderFailureCode(StrEnum):
    """Closed failure vocabulary for the version-1 provider boundary."""

    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    NETWORK_DENIED = "network_denied"
    MALFORMED_REQUEST = "malformed_request"
    MALFORMED_RESPONSE = "malformed_response"
    PROTOCOL_ERROR = "protocol_error"
    PROVIDER_ERROR = "provider_error"


def _strict_json_value(value: Any, field_name: str) -> Any:
    """Return a detached strict-JSON value and reject floats and custom types."""

    def validate(item: Any) -> None:
        if item is None or isinstance(item, (str, bool, int)):
            return
        if isinstance(item, float):
            raise LogicProviderContractError(
                f"{field_name} cannot contain floating-point values"
            )
        if isinstance(item, Mapping):
            if not all(isinstance(key, str) for key in item):
                raise LogicProviderContractError(
                    f"{field_name} object keys must be strings"
                )
            for nested in item.values():
                validate(nested)
            return
        if isinstance(item, (list, tuple)):
            for nested in item:
                validate(nested)
            return
        raise LogicProviderContractError(
            f"{field_name} contains unsupported value {type(item).__name__}"
        )

    try:
        validate(value)
        return json.loads(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        )
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        if isinstance(error, LogicProviderContractError):
            raise
        raise LogicProviderContractError(
            f"{field_name} must contain strict JSON values"
        ) from error


def _strict_json_object(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise LogicProviderContractError(f"{field_name} must be an object")
    normalized = _strict_json_value(dict(value), field_name)
    if not isinstance(normalized, dict):  # defensive; the input check implies this
        raise LogicProviderContractError(f"{field_name} must be an object")
    return normalized


def _text(
    value: Any,
    field_name: str,
    *,
    optional: bool = False,
    maximum: int = 4096,
) -> str:
    if optional and value == "":
        return ""
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
        or len(value) > maximum
    ):
        raise LogicProviderContractError(
            f"{field_name} must be a trimmed string of 1-{maximum} characters"
        )
    return value


def _nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LogicProviderContractError(
            f"{field_name} must be a non-negative integer"
        )
    return value


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise LogicProviderContractError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def canonical_provider_json(value: Mapping[str, Any]) -> str:
    """Serialize a provider envelope deterministically."""

    normalized = _strict_json_object(value, "provider envelope")
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _strict_json_loads(value: str, field_name: str) -> Any:
    def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise LogicProviderContractError(
                    f"{field_name} contains duplicate object key {key!r}"
                )
            result[key] = item
        return result

    try:
        return json.loads(
            value,
            object_pairs_hook=no_duplicate_keys,
            parse_constant=lambda constant: (_ for _ in ()).throw(
                LogicProviderContractError(
                    f"{field_name} contains non-finite number {constant}"
                )
            ),
        )
    except (TypeError, json.JSONDecodeError) as error:
        raise LogicProviderContractError(f"{field_name} JSON is malformed") from error


@dataclass(frozen=True, slots=True)
class ProviderResourceBudget:
    """Portable integer-unit resource limits for one provider invocation.

    The fields are the union already used by supervisor proof scheduling.  A
    zero value means that the host did not grant a positive amount; it never
    means unlimited.  Backend-specific semantic bounds remain in the request
    payload or its typed IR.
    """

    wall_time_ms: int = 0
    cpu_time_ms: int = 0
    memory_bytes: int = 0
    disk_bytes: int = 0
    max_processes: int = 0
    max_premises: int = 0
    max_output_bytes: int = 0
    model_token_limit: int = 0
    provider_quota: int = 0
    network_allowed: bool = False
    schema_version: str = LOGIC_PROVIDER_RESOURCE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != LOGIC_PROVIDER_RESOURCE_SCHEMA:
            raise LogicProviderContractError(
                "unsupported logic-provider resource schema"
            )
        for field_name in (
            "wall_time_ms",
            "cpu_time_ms",
            "memory_bytes",
            "disk_bytes",
            "max_processes",
            "max_premises",
            "max_output_bytes",
            "model_token_limit",
            "provider_quota",
        ):
            object.__setattr__(
                self,
                field_name,
                _nonnegative_int(getattr(self, field_name), field_name),
            )
        if not isinstance(self.network_allowed, bool):
            raise LogicProviderContractError(
                "resource budget network_allowed must be a boolean"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "wall_time_ms": self.wall_time_ms,
            "cpu_time_ms": self.cpu_time_ms,
            "memory_bytes": self.memory_bytes,
            "disk_bytes": self.disk_bytes,
            "max_processes": self.max_processes,
            "max_premises": self.max_premises,
            "max_output_bytes": self.max_output_bytes,
            "model_token_limit": self.model_token_limit,
            "provider_quota": self.provider_quota,
            "network_allowed": self.network_allowed,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProviderResourceBudget:
        if not isinstance(value, Mapping):
            raise LogicProviderContractError("resource budget must be an object")
        allowed = frozenset(
            {
                "schema_version",
                "wall_time_ms",
                "cpu_time_ms",
                "memory_bytes",
                "disk_bytes",
                "max_processes",
                "max_premises",
                "max_output_bytes",
                "model_token_limit",
                "provider_quota",
                "network_allowed",
            }
        )
        _reject_unknown(value, allowed, "resource budget")
        return cls(
            **{
                field_name: value[field_name]
                for field_name in allowed
                if field_name in value
            }
        )


@dataclass(frozen=True, slots=True)
class ProviderCancellation:
    """Serializable snapshot of cooperative cancellation state."""

    cancellation_id: str
    cancelled: bool = False
    reason: str = ""
    schema_version: str = LOGIC_PROVIDER_CANCELLATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != LOGIC_PROVIDER_CANCELLATION_SCHEMA:
            raise LogicProviderContractError(
                "unsupported logic-provider cancellation schema"
            )
        object.__setattr__(
            self,
            "cancellation_id",
            _text(self.cancellation_id, "cancellation_id", maximum=128),
        )
        if not isinstance(self.cancelled, bool):
            raise LogicProviderContractError("cancelled must be a boolean")
        object.__setattr__(
            self,
            "reason",
            _text(self.reason, "cancellation reason", optional=True, maximum=512),
        )
        if self.reason and not self.cancelled:
            raise LogicProviderContractError(
                "a cancellation reason requires cancelled=true"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "cancellation_id": self.cancellation_id,
            "cancelled": self.cancelled,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProviderCancellation:
        if not isinstance(value, Mapping):
            raise LogicProviderContractError("cancellation must be an object")
        _reject_unknown(
            value,
            frozenset(
                {"schema_version", "cancellation_id", "cancelled", "reason"}
            ),
            "cancellation",
        )
        return cls(
            schema_version=value.get(
                "schema_version", LOGIC_PROVIDER_CANCELLATION_SCHEMA
            ),
            cancellation_id=value.get("cancellation_id", ""),
            cancelled=value.get("cancelled", False),
            reason=value.get("reason", ""),
        )


@dataclass(frozen=True, slots=True)
class LogicProviderFailure:
    """Typed expected provider failure with non-authoritative details."""

    code: LogicProviderFailureCode | str
    message: str
    retryable: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            code = LogicProviderFailureCode(
                str(getattr(self.code, "value", self.code))
            )
        except ValueError as error:
            raise LogicProviderContractError(
                "unknown logic-provider failure code"
            ) from error
        object.__setattr__(self, "code", code)
        object.__setattr__(
            self, "message", _text(self.message, "failure message", maximum=4096)
        )
        if not isinstance(self.retryable, bool):
            raise LogicProviderContractError("retryable must be a boolean")
        object.__setattr__(
            self,
            "details",
            _strict_json_object(self.details, "failure details"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "retryable": self.retryable,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> LogicProviderFailure:
        if not isinstance(value, Mapping):
            raise LogicProviderContractError("provider failure must be an object")
        _reject_unknown(
            value,
            frozenset({"code", "message", "retryable", "details"}),
            "provider failure",
        )
        return cls(
            code=value.get("code", ""),
            message=value.get("message", ""),
            retryable=value.get("retryable", False),
            details=value.get("details", {}),
        )


@dataclass(frozen=True, slots=True)
class LogicProviderRequest:
    """Strict, correlated request envelope shared by every operation."""

    operation: LogicProviderOperation | str
    payload: Mapping[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    resource_budget: ProviderResourceBudget | Mapping[str, Any] = field(
        default_factory=ProviderResourceBudget
    )
    cancellation: ProviderCancellation | Mapping[str, Any] | None = None
    network_allowed: bool = False
    deadline_unix_ms: int | None = None
    protocol_version: int = LOGIC_PROVIDER_PROTOCOL_VERSION
    schema_version: str = LOGIC_PROVIDER_REQUEST_SCHEMA

    def __post_init__(self) -> None:
        try:
            operation = LogicProviderOperation(
                str(getattr(self.operation, "value", self.operation))
            )
        except ValueError as error:
            raise LogicProviderContractError(
                "unsupported logic-provider operation"
            ) from error
        if (
            isinstance(self.protocol_version, bool)
            or not isinstance(self.protocol_version, int)
            or self.protocol_version not in LOGIC_PROVIDER_SUPPORTED_PROTOCOL_VERSIONS
        ):
            raise LogicProviderContractError(
                "unsupported logic-provider protocol version"
            )
        if self.schema_version != LOGIC_PROVIDER_REQUEST_SCHEMA:
            raise LogicProviderContractError(
                "unsupported logic-provider request schema"
            )
        if not isinstance(self.network_allowed, bool):
            raise LogicProviderContractError("network_allowed must be a boolean")
        if self.deadline_unix_ms is not None:
            _nonnegative_int(self.deadline_unix_ms, "deadline_unix_ms")

        budget = (
            self.resource_budget
            if isinstance(self.resource_budget, ProviderResourceBudget)
            else ProviderResourceBudget.from_dict(self.resource_budget)
        )
        cancellation = self.cancellation
        if cancellation is not None and not isinstance(
            cancellation, ProviderCancellation
        ):
            cancellation = ProviderCancellation.from_dict(cancellation)
        if self.network_allowed and not budget.network_allowed:
            raise LogicProviderContractError(
                "request network access exceeds its resource budget"
            )

        object.__setattr__(self, "operation", operation)
        object.__setattr__(
            self, "request_id", _text(self.request_id, "request_id", maximum=128)
        )
        object.__setattr__(
            self, "payload", _strict_json_object(self.payload, "request payload")
        )
        object.__setattr__(self, "resource_budget", budget)
        object.__setattr__(self, "cancellation", cancellation)

    @property
    def cancelled(self) -> bool:
        return self.cancellation is not None and self.cancellation.cancelled

    @property
    def expired(self) -> bool:
        return (
            self.deadline_unix_ms is not None
            and int(time.time() * 1000) >= self.deadline_unix_ms
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "protocol_version": self.protocol_version,
            "request_id": self.request_id,
            "operation": self.operation.value,
            "payload": dict(self.payload),
            "resource_budget": self.resource_budget.to_dict(),
            "cancellation": (
                None if self.cancellation is None else self.cancellation.to_dict()
            ),
            "network_allowed": self.network_allowed,
            "deadline_unix_ms": self.deadline_unix_ms,
        }

    def to_json(self) -> str:
        return canonical_provider_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> LogicProviderRequest:
        if not isinstance(value, Mapping):
            raise LogicProviderContractError("provider request must be an object")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "protocol_version",
                    "request_id",
                    "operation",
                    "payload",
                    "resource_budget",
                    "cancellation",
                    "network_allowed",
                    "deadline_unix_ms",
                }
            ),
            "provider request",
        )
        return cls(
            schema_version=value.get("schema_version", ""),
            protocol_version=value.get("protocol_version", 0),
            request_id=value.get("request_id", ""),
            operation=value.get("operation", ""),
            payload=value.get("payload", {}),
            resource_budget=value.get("resource_budget", {}),
            cancellation=value.get("cancellation"),
            network_allowed=value.get("network_allowed", False),
            deadline_unix_ms=value.get("deadline_unix_ms"),
        )

    @classmethod
    def from_json(cls, value: str) -> LogicProviderRequest:
        return cls.from_dict(_strict_json_loads(value, "provider request"))


@dataclass(frozen=True, slots=True)
class LogicProviderResponse:
    """Correlated result envelope; success and failure are mutually exclusive."""

    request_id: str
    operation: LogicProviderOperation | str
    ok: bool
    result: Mapping[str, Any] | None = None
    error: LogicProviderFailure | Mapping[str, Any] | None = None
    provider_id: str = ""
    provider_version: str = ""
    duration_ms: int = 0
    protocol_version: int = LOGIC_PROVIDER_PROTOCOL_VERSION
    schema_version: str = LOGIC_PROVIDER_RESPONSE_SCHEMA

    def __post_init__(self) -> None:
        try:
            operation = LogicProviderOperation(
                str(getattr(self.operation, "value", self.operation))
            )
        except ValueError as error:
            raise LogicProviderContractError(
                "unsupported logic-provider response operation"
            ) from error
        if (
            isinstance(self.protocol_version, bool)
            or not isinstance(self.protocol_version, int)
            or self.protocol_version not in LOGIC_PROVIDER_SUPPORTED_PROTOCOL_VERSIONS
        ):
            raise LogicProviderContractError(
                "unsupported logic-provider response protocol version"
            )
        if self.schema_version != LOGIC_PROVIDER_RESPONSE_SCHEMA:
            raise LogicProviderContractError(
                "unsupported logic-provider response schema"
            )
        if not isinstance(self.ok, bool):
            raise LogicProviderContractError("response ok must be a boolean")
        duration_ms = _nonnegative_int(self.duration_ms, "duration_ms")
        result = (
            None
            if self.result is None
            else _strict_json_object(self.result, "response result")
        )
        error = self.error
        if error is not None and not isinstance(error, LogicProviderFailure):
            error = LogicProviderFailure.from_dict(error)
        if self.ok and (result is None or error is not None):
            raise LogicProviderContractError(
                "successful provider response requires only a result"
            )
        if not self.ok and (error is None or result is not None):
            raise LogicProviderContractError(
                "failed provider response requires only an error"
            )

        object.__setattr__(self, "operation", operation)
        object.__setattr__(
            self, "request_id", _text(self.request_id, "request_id", maximum=128)
        )
        object.__setattr__(self, "result", result)
        object.__setattr__(self, "error", error)
        object.__setattr__(
            self,
            "provider_id",
            _text(self.provider_id, "provider_id", optional=True, maximum=128),
        )
        object.__setattr__(
            self,
            "provider_version",
            _text(
                self.provider_version,
                "provider_version",
                optional=True,
                maximum=128,
            ),
        )
        object.__setattr__(self, "duration_ms", duration_ms)

    @classmethod
    def success(
        cls,
        request: LogicProviderRequest,
        result: Mapping[str, Any],
        *,
        provider_id: str = "",
        provider_version: str = "",
        duration_ms: int = 0,
    ) -> LogicProviderResponse:
        return cls(
            request_id=request.request_id,
            operation=request.operation,
            ok=True,
            result=result,
            provider_id=provider_id,
            provider_version=provider_version,
            duration_ms=duration_ms,
        )

    @classmethod
    def failure(
        cls,
        request: LogicProviderRequest,
        code: LogicProviderFailureCode | str,
        message: str,
        *,
        retryable: bool = False,
        details: Mapping[str, Any] | None = None,
        provider_id: str = "",
        provider_version: str = "",
        duration_ms: int = 0,
    ) -> LogicProviderResponse:
        return cls(
            request_id=request.request_id,
            operation=request.operation,
            ok=False,
            error=LogicProviderFailure(
                code=code,
                message=message,
                retryable=retryable,
                details=details or {},
            ),
            provider_id=provider_id,
            provider_version=provider_version,
            duration_ms=duration_ms,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "protocol_version": self.protocol_version,
            "request_id": self.request_id,
            "operation": self.operation.value,
            "ok": self.ok,
            "result": None if self.result is None else dict(self.result),
            "error": None if self.error is None else self.error.to_dict(),
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "duration_ms": self.duration_ms,
        }

    def to_json(self) -> str:
        return canonical_provider_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> LogicProviderResponse:
        if not isinstance(value, Mapping):
            raise LogicProviderContractError("provider response must be an object")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "protocol_version",
                    "request_id",
                    "operation",
                    "ok",
                    "result",
                    "error",
                    "provider_id",
                    "provider_version",
                    "duration_ms",
                }
            ),
            "provider response",
        )
        if "ok" not in value:
            raise LogicProviderContractError("provider response is missing ok")
        return cls(
            schema_version=value.get("schema_version", ""),
            protocol_version=value.get("protocol_version", 0),
            request_id=value.get("request_id", ""),
            operation=value.get("operation", ""),
            ok=value["ok"],
            result=value.get("result"),
            error=value.get("error"),
            provider_id=value.get("provider_id", ""),
            provider_version=value.get("provider_version", ""),
            duration_ms=value.get("duration_ms", 0),
        )

    @classmethod
    def from_json(cls, value: str) -> LogicProviderResponse:
        return cls.from_dict(_strict_json_loads(value, "provider response"))


@runtime_checkable
class LogicProvider(Protocol):
    """Structural version-1 interface for a concrete logic provider."""

    provider_id: str
    provider_version: str
    protocol_version: int

    def capability(
        self, request: LogicProviderRequest
    ) -> Mapping[str, Any] | LogicProviderResponse:
        ...

    def translate(
        self, request: LogicProviderRequest
    ) -> Mapping[str, Any] | LogicProviderResponse:
        ...

    def prove(
        self, request: LogicProviderRequest
    ) -> Mapping[str, Any] | LogicProviderResponse:
        ...

    def reconstruct(
        self, request: LogicProviderRequest
    ) -> Mapping[str, Any] | LogicProviderResponse:
        ...

    def verify(
        self, request: LogicProviderRequest
    ) -> Mapping[str, Any] | LogicProviderResponse:
        ...

    def attest(
        self, request: LogicProviderRequest
    ) -> Mapping[str, Any] | LogicProviderResponse:
        ...


def dispatch_logic_provider_request(
    provider: LogicProvider, request: LogicProviderRequest
) -> LogicProviderResponse:
    """Dispatch one already-admitted request without discovery or routing."""

    if not isinstance(request, LogicProviderRequest):
        raise TypeError("request must be a LogicProviderRequest")
    provider_id = str(getattr(provider, "provider_id", "")).strip()
    provider_version = str(getattr(provider, "provider_version", "")).strip()
    provider_protocol_version = getattr(provider, "protocol_version", None)

    if provider_protocol_version != request.protocol_version:
        return LogicProviderResponse.failure(
            request,
            LogicProviderFailureCode.PROTOCOL_ERROR,
            "provider does not support the requested protocol version",
            provider_id=provider_id,
            provider_version=provider_version,
        )
    if request.cancelled:
        return LogicProviderResponse.failure(
            request,
            LogicProviderFailureCode.CANCELLED,
            request.cancellation.reason or "logic-provider request was cancelled",
            provider_id=provider_id,
            provider_version=provider_version,
        )
    if request.expired:
        return LogicProviderResponse.failure(
            request,
            LogicProviderFailureCode.TIMED_OUT,
            "logic-provider request deadline has expired",
            provider_id=provider_id,
            provider_version=provider_version,
        )
    operation = getattr(provider, request.operation.value, None)
    if not callable(operation):
        return LogicProviderResponse.failure(
            request,
            LogicProviderFailureCode.UNSUPPORTED,
            f"provider does not implement {request.operation.value}",
            provider_id=provider_id,
            provider_version=provider_version,
        )
    started = time.monotonic()
    try:
        raw_response = operation(request)
        if isinstance(raw_response, LogicProviderResponse):
            response = raw_response
        elif isinstance(raw_response, Mapping):
            response = LogicProviderResponse.success(
                request,
                raw_response,
                provider_id=provider_id,
                provider_version=provider_version,
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            )
        else:
            raise LogicProviderContractError(
                "provider operation must return an object or LogicProviderResponse"
            )
    except LogicProviderContractError as error:
        return LogicProviderResponse.failure(
            request,
            LogicProviderFailureCode.MALFORMED_RESPONSE,
            str(error),
            provider_id=provider_id,
            provider_version=provider_version,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        )
    except Exception as error:
        return LogicProviderResponse.failure(
            request,
            LogicProviderFailureCode.PROVIDER_ERROR,
            f"provider raised {type(error).__name__}",
            provider_id=provider_id,
            provider_version=provider_version,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        )

    if response.request_id != request.request_id or response.operation is not request.operation:
        return LogicProviderResponse.failure(
            request,
            LogicProviderFailureCode.MALFORMED_RESPONSE,
            "provider response correlation mismatch",
            provider_id=provider_id,
            provider_version=provider_version,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        )
    if response.protocol_version != request.protocol_version:
        return LogicProviderResponse.failure(
            request,
            LogicProviderFailureCode.MALFORMED_RESPONSE,
            "provider response protocol version mismatch",
            provider_id=provider_id,
            provider_version=provider_version,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        )
    if response.provider_id != provider_id or response.provider_version != provider_version:
        return LogicProviderResponse.failure(
            request,
            LogicProviderFailureCode.MALFORMED_RESPONSE,
            "provider response identity mismatch",
            provider_id=provider_id,
            provider_version=provider_version,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        )
    return response


__all__ = [
    "LOGIC_PROVIDER_CANCELLATION_SCHEMA",
    "LOGIC_PROVIDER_PROTOCOL_VERSION",
    "LOGIC_PROVIDER_REQUEST_SCHEMA",
    "LOGIC_PROVIDER_RESOURCE_SCHEMA",
    "LOGIC_PROVIDER_RESPONSE_SCHEMA",
    "LOGIC_PROVIDER_SUPPORTED_PROTOCOL_VERSIONS",
    "LogicProvider",
    "LogicProviderContractError",
    "LogicProviderFailure",
    "LogicProviderFailureCode",
    "LogicProviderOperation",
    "LogicProviderRequest",
    "LogicProviderResponse",
    "ProviderCancellation",
    "ProviderResourceBudget",
    "canonical_provider_json",
    "dispatch_logic_provider_request",
]
