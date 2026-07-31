"""Pre-dispatch enforcement and one-time capability consumption (LIG-036).

Interfaces:

* ``PreInvocationEnforcement@1`` — reject every non-allow, revalidate exact
  current context/roots/environment at the dispatch boundary, atomically
  compare-and-consume a one-time capability, then (optionally) invoke a
  side-effect dispatcher **once**.
* ``CapabilityConsumptionStore@1`` — tenant-scoped, fail-closed atomic
  consumption ledger for one-time dispatch capabilities.

This leaf owns generic pre-dispatch runtime, an in-memory reference store,
fake dispatchers, and race-safe consumption.  It does **not** connect to real
tools, edit the authorization service/receipt codecs, or emit theorem-grade
proofs.  Post-dispatch observation is intentionally separate from the
authorization receipt.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Protocol, runtime_checkable

from ..ir_core.claims import FrozenMap, stable_digest
from .compose import InternalDecisionStatus
from .reasons import AdmissibilityStatus
from .receipt import (
    AuthorizationCapability,
    BoundContext,
    BoundRoots,
    DecisionReceipt,
    ReceiptError,
    ReceiptVerificationError,
    verify_capability,
    verify_decision_receipt,
)


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

PRE_INVOCATION_ENFORCEMENT_INTERFACE: Final = "PreInvocationEnforcement@1"
PRE_INVOCATION_ENFORCEMENT_SCHEMA_VERSION: Final = (
    "pre-invocation-enforcement/v1"
)
CAPABILITY_CONSUMPTION_STORE_INTERFACE: Final = "CapabilityConsumptionStore@1"
CAPABILITY_CONSUMPTION_STORE_SCHEMA_VERSION: Final = (
    "capability-consumption-store/v1"
)
DISPATCH_OBSERVATION_SCHEMA_VERSION: Final = "dispatch-observation/v1"
ENFORCEMENT_RESULT_SCHEMA_VERSION: Final = "enforcement-result/v1"
INVOCATION_BINDING_SCHEMA_VERSION: Final = "invocation-binding/v1"

DEFAULT_CONSUMER_ID: Final = "consumer:pre-invocation-enforcement-v1"
DEFAULT_DISPATCHER_ID: Final = "dispatcher:fake-v1"

MAX_IDENTIFIER_CHARS: Final = 256
MAX_STRING_CHARS: Final = 4_096
MAX_COLLECTION_ITEMS: Final = 1_024
MAX_REASON_CHARS: Final = 512


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class EnforcementError(ValueError):
    """Raised when pre-dispatch enforcement fails closed."""


class EnforcementRejection(EnforcementError):
    """Raised (or returned) when an invocation is rejected before dispatch."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str = "enforcement.rejected",
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.details = dict(details or {})


class ConsumptionRaceError(EnforcementError):
    """Raised when compare-and-consume loses a race (already consumed)."""

    def __init__(
        self,
        message: str = "capability already consumed (compare-and-consume race)",
        *,
        capability_id: str = "",
    ) -> None:
        super().__init__(message)
        self.capability_id = capability_id
        self.reason_code = "enforcement.consumption_race"


class ConsumptionStoreError(EnforcementError):
    """Raised when the consumption store encounters an unrecoverable state."""


# ---------------------------------------------------------------------------
# Low-level validators (local; keep leaf self-contained)
# ---------------------------------------------------------------------------


def _text(
    value: Any,
    name: str,
    *,
    allow_empty: bool = False,
    max_chars: int = MAX_STRING_CHARS,
) -> str:
    if not isinstance(value, str):
        raise EnforcementError(f"{name} must be a string")
    if not allow_empty and (not value.strip() or value != value.strip()):
        raise EnforcementError(f"{name} must be a non-empty trimmed string")
    if value and value != value.strip():
        raise EnforcementError(f"{name} must not have surrounding whitespace")
    if len(value) > max_chars:
        raise EnforcementError(f"{name} exceeds maximum length of {max_chars}")
    return value


def _optional_text(value: Any, name: str) -> str:
    if value in (None, ""):
        return ""
    return _text(value, name)


def _identifier(value: Any, name: str) -> str:
    text = _text(value, name, max_chars=MAX_IDENTIFIER_CHARS)
    # Allow the same stable identifier charset used by receipts.
    import re

    if not re.fullmatch(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$", text):
        raise EnforcementError(f"{name} is not a stable identifier")
    return text


def _optional_identifier(value: Any, name: str) -> str:
    if value in (None, ""):
        return ""
    return _identifier(value, name)


def _digest(value: Any, name: str) -> str:
    text = _text(value, name, max_chars=80)
    if text.startswith("sha256:"):
        text = text[len("sha256:") :]
    import re

    if not re.fullmatch(r"^[0-9a-f]{64}$", text):
        raise EnforcementError(f"{name} must be a lowercase SHA-256 hex digest")
    return text


def _optional_digest(value: Any, name: str) -> str:
    if value in (None, ""):
        return ""
    return _digest(value, name)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EnforcementError(f"{name} must be a mapping")
    return value


def _unique_sorted_ids(
    values: Any,
    name: str,
    *,
    require_identifier: bool = False,
) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise EnforcementError(f"{name} must be a sequence of strings")
    if len(values) > MAX_COLLECTION_ITEMS:
        raise EnforcementError(f"{name} exceeds maximum collection size")
    if require_identifier:
        items = tuple(_identifier(item, f"{name} item") for item in values)
    else:
        items = tuple(_text(item, f"{name} item") for item in values)
    if len(items) != len(set(items)):
        raise EnforcementError(f"{name} must be unique")
    return tuple(sorted(items))


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


# ---------------------------------------------------------------------------
# Reason codes
# ---------------------------------------------------------------------------


class EnforcementReasonCode(str, Enum):
    """Closed machine-readable codes for pre-dispatch outcomes."""

    ALLOWED = "enforcement.allowed"
    NON_ALLOW = "enforcement.non_allow"
    RECEIPT_INVALID = "enforcement.receipt_invalid"
    CAPABILITY_INVALID = "enforcement.capability_invalid"
    CONTEXT_MISMATCH = "enforcement.context_mismatch"
    ROOTS_MISMATCH = "enforcement.roots_mismatch"
    ENVIRONMENT_MISMATCH = "enforcement.environment_mismatch"
    EXPIRED = "enforcement.expired"
    CONSUMPTION_RACE = "enforcement.consumption_race"
    CONSUMPTION_ERROR = "enforcement.consumption_error"
    DISPATCH_ERROR = "enforcement.dispatch_error"
    MISSING_CAPABILITY = "enforcement.missing_capability"
    MISSING_RECEIPT = "enforcement.missing_receipt"
    TENANT_MISMATCH = "enforcement.tenant_mismatch"
    INTERNAL_ERROR = "enforcement.internal_error"


# ---------------------------------------------------------------------------
# Invocation binding (live dispatch context)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InvocationBinding:
    """Live invocation facts revalidated immediately before dispatch.

    Every security-relevant field must match the receipt/capability binding.
    Secrets and raw private argument bodies never appear here — only digests
    and stable identifiers.
    """

    tenant_id: str
    actor_id: str
    audience_id: str
    request_digest: str
    arguments_digest: str
    tool_id: str = ""
    tool_version: str = ""
    effect_ids: tuple[str, ...] = ()
    delegation_ids: tuple[str, ...] = ()
    delegation_digest: str = ""
    environment_digest: str = ""
    environment_id: str = ""
    resource_ids: tuple[str, ...] = ()
    nonce: str = ""
    roots: BoundRoots | None = None
    schema_version: str = INVOCATION_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "tenant_id", _identifier(self.tenant_id, "tenant_id")
        )
        object.__setattr__(
            self, "actor_id", _identifier(self.actor_id, "actor_id")
        )
        object.__setattr__(
            self, "audience_id", _identifier(self.audience_id, "audience_id")
        )
        object.__setattr__(
            self,
            "request_digest",
            _digest(self.request_digest, "request_digest"),
        )
        object.__setattr__(
            self,
            "arguments_digest",
            _digest(self.arguments_digest, "arguments_digest"),
        )
        object.__setattr__(
            self, "tool_id", _optional_identifier(self.tool_id, "tool_id")
        )
        object.__setattr__(
            self,
            "tool_version",
            _optional_text(self.tool_version, "tool_version"),
        )
        object.__setattr__(
            self,
            "effect_ids",
            _unique_sorted_ids(
                self.effect_ids, "effect_ids", require_identifier=True
            ),
        )
        object.__setattr__(
            self,
            "delegation_ids",
            _unique_sorted_ids(
                self.delegation_ids, "delegation_ids", require_identifier=True
            ),
        )
        object.__setattr__(
            self,
            "delegation_digest",
            _optional_digest(self.delegation_digest, "delegation_digest"),
        )
        object.__setattr__(
            self,
            "environment_digest",
            _optional_digest(self.environment_digest, "environment_digest"),
        )
        object.__setattr__(
            self,
            "environment_id",
            _optional_identifier(self.environment_id, "environment_id"),
        )
        object.__setattr__(
            self,
            "resource_ids",
            _unique_sorted_ids(
                self.resource_ids, "resource_ids", require_identifier=True
            ),
        )
        object.__setattr__(
            self, "nonce", _text(self.nonce, "nonce", max_chars=128)
        )
        if self.roots is not None and not isinstance(self.roots, BoundRoots):
            if isinstance(self.roots, Mapping):
                object.__setattr__(
                    self, "roots", BoundRoots.from_dict(self.roots)
                )
            else:
                raise EnforcementError("roots must be a BoundRoots or mapping")
        if self.schema_version != INVOCATION_BINDING_SCHEMA_VERSION:
            raise EnforcementError(
                f"unsupported invocation binding schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "arguments_digest": self.arguments_digest,
            "audience_id": self.audience_id,
            "delegation_digest": self.delegation_digest,
            "delegation_ids": list(self.delegation_ids),
            "effect_ids": list(self.effect_ids),
            "environment_digest": self.environment_digest,
            "environment_id": self.environment_id,
            "nonce": self.nonce,
            "request_digest": self.request_digest,
            "resource_ids": list(self.resource_ids),
            "roots": None if self.roots is None else self.roots.to_dict(),
            "schema_version": self.schema_version,
            "tenant_id": self.tenant_id,
            "tool_id": self.tool_id,
            "tool_version": self.tool_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "InvocationBinding":
        value = _mapping(value, "invocation binding")
        return cls(
            tenant_id=value.get("tenant_id", ""),
            actor_id=value.get("actor_id", ""),
            audience_id=value.get("audience_id", ""),
            request_digest=value.get("request_digest", ""),
            arguments_digest=value.get("arguments_digest", ""),
            tool_id=value.get("tool_id", ""),
            tool_version=value.get("tool_version", ""),
            effect_ids=tuple(value.get("effect_ids", ())),
            delegation_ids=tuple(value.get("delegation_ids", ())),
            delegation_digest=value.get("delegation_digest", ""),
            environment_digest=value.get("environment_digest", ""),
            environment_id=value.get("environment_id", ""),
            resource_ids=tuple(value.get("resource_ids", ())),
            nonce=value.get("nonce", ""),
            roots=value.get("roots"),
            schema_version=value.get(
                "schema_version", INVOCATION_BINDING_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_receipt(
        cls,
        receipt: DecisionReceipt,
        *,
        tenant_id: str,
        roots: BoundRoots | None = None,
    ) -> "InvocationBinding":
        """Project a verified receipt context into a live binding template."""

        ctx = receipt.context
        return cls(
            tenant_id=tenant_id,
            actor_id=ctx.actor_id,
            audience_id=ctx.audience_id,
            request_digest=ctx.request_digest,
            arguments_digest=ctx.arguments_digest,
            tool_id=ctx.tool_id,
            tool_version=ctx.tool_version,
            effect_ids=ctx.effect_ids,
            delegation_ids=ctx.delegation_ids,
            delegation_digest=ctx.delegation_digest,
            environment_digest=ctx.environment_digest,
            environment_id=ctx.environment_id,
            resource_ids=ctx.resource_ids,
            nonce=ctx.nonce,
            roots=roots if roots is not None else receipt.roots,
        )


# ---------------------------------------------------------------------------
# Consumption store
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CapabilityConsumptionRecord:
    """Immutable record of a successfully consumed one-time capability."""

    capability_id: str
    capability_digest: str
    nonce: str
    tenant_id: str
    audience_id: str
    receipt_id: str
    consumed_at: str
    consumer_id: str
    request_digest: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)
    interface: str = CAPABILITY_CONSUMPTION_STORE_INTERFACE
    schema_version: str = CAPABILITY_CONSUMPTION_STORE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "capability_id",
            _identifier(self.capability_id, "capability_id"),
        )
        object.__setattr__(
            self,
            "capability_digest",
            _digest(self.capability_digest, "capability_digest"),
        )
        object.__setattr__(
            self, "nonce", _text(self.nonce, "nonce", max_chars=128)
        )
        object.__setattr__(
            self, "tenant_id", _identifier(self.tenant_id, "tenant_id")
        )
        object.__setattr__(
            self, "audience_id", _identifier(self.audience_id, "audience_id")
        )
        object.__setattr__(
            self, "receipt_id", _identifier(self.receipt_id, "receipt_id")
        )
        object.__setattr__(
            self, "consumed_at", _text(self.consumed_at, "consumed_at")
        )
        object.__setattr__(
            self, "consumer_id", _identifier(self.consumer_id, "consumer_id")
        )
        object.__setattr__(
            self,
            "request_digest",
            _optional_digest(self.request_digest, "request_digest"),
        )
        object.__setattr__(
            self,
            "metadata",
            self.metadata
            if isinstance(self.metadata, FrozenMap)
            else FrozenMap(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "audience_id": self.audience_id,
            "capability_digest": self.capability_digest,
            "capability_id": self.capability_id,
            "consumed_at": self.consumed_at,
            "consumer_id": self.consumer_id,
            "interface": self.interface,
            "metadata": self.metadata.to_dict(),
            "nonce": self.nonce,
            "receipt_id": self.receipt_id,
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
            "tenant_id": self.tenant_id,
        }


@runtime_checkable
class CapabilityConsumptionStore(Protocol):
    """``CapabilityConsumptionStore@1`` — atomic one-time consumption ledger."""

    def is_consumed(
        self,
        capability_id: str,
        *,
        tenant_id: str,
        capability_digest: str | None = None,
    ) -> bool:
        """Return True if the capability was already consumed in this tenant."""

    def compare_and_consume(
        self,
        capability: AuthorizationCapability,
        *,
        tenant_id: str,
        now: str,
        consumer_id: str = DEFAULT_CONSUMER_ID,
        metadata: Mapping[str, Any] | None = None,
    ) -> CapabilityConsumptionRecord:
        """Atomically mark *capability* consumed.

        Succeeds only if the capability was not previously consumed under the
        same tenant.  Fail-closed on race, state error, or integrity failure.
        """

    def get_record(
        self,
        capability_id: str,
        *,
        tenant_id: str,
    ) -> CapabilityConsumptionRecord | None:
        """Return the consumption record if present for the tenant."""


class InMemoryCapabilityConsumptionStore:
    """Thread-safe in-memory reference implementation of the consumption store.

    Domain-separates records by ``(tenant_id, capability_id)`` so one tenant
    cannot observe or interfere with another.  Compare-and-consume is atomic
    under a process-wide re-entrant lock.
    """

    interface: Final = CAPABILITY_CONSUMPTION_STORE_INTERFACE
    schema_version: Final = CAPABILITY_CONSUMPTION_STORE_SCHEMA_VERSION

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # Key: (tenant_id, capability_id) → record
        self._records: dict[tuple[str, str], CapabilityConsumptionRecord] = {}
        # Secondary index by (tenant_id, nonce) to defeat nonce replay.
        self._nonces: dict[tuple[str, str], str] = {}

    def is_consumed(
        self,
        capability_id: str,
        *,
        tenant_id: str,
        capability_digest: str | None = None,
    ) -> bool:
        tenant = _identifier(tenant_id, "tenant_id")
        cap_id = _identifier(capability_id, "capability_id")
        with self._lock:
            record = self._records.get((tenant, cap_id))
            if record is None:
                return False
            if capability_digest is not None:
                digest = _digest(capability_digest, "capability_digest")
                if record.capability_digest != digest:
                    # Identity drift — treat as not matching this capability.
                    return False
            return True

    def compare_and_consume(
        self,
        capability: AuthorizationCapability,
        *,
        tenant_id: str,
        now: str,
        consumer_id: str = DEFAULT_CONSUMER_ID,
        metadata: Mapping[str, Any] | None = None,
    ) -> CapabilityConsumptionRecord:
        if not isinstance(capability, AuthorizationCapability):
            raise ConsumptionStoreError(
                "compare_and_consume requires an AuthorizationCapability"
            )
        try:
            capability.verify_integrity()
        except ReceiptError as exc:
            raise ConsumptionStoreError(
                f"capability integrity failed: {exc}"
            ) from exc
        if not capability.one_time:
            raise ConsumptionStoreError(
                "capability missing required one-time marker"
            )

        tenant = _identifier(tenant_id, "tenant_id")
        consumer = _identifier(consumer_id, "consumer_id")
        now_ts = _text(now, "now")
        cap_id = capability.capability_id
        cap_digest = capability.digest
        nonce = capability.nonce

        with self._lock:
            key = (tenant, cap_id)
            if key in self._records:
                raise ConsumptionRaceError(
                    f"capability {cap_id!r} already consumed for tenant "
                    f"{tenant!r}",
                    capability_id=cap_id,
                )
            nonce_key = (tenant, nonce)
            if nonce_key in self._nonces:
                raise ConsumptionRaceError(
                    f"nonce {nonce!r} already consumed for tenant {tenant!r}",
                    capability_id=cap_id,
                )
            # Compare expected digest against any prior partial state (none).
            # Atomic insert is the compare-and-consume.
            record = CapabilityConsumptionRecord(
                capability_id=cap_id,
                capability_digest=cap_digest,
                nonce=nonce,
                tenant_id=tenant,
                audience_id=capability.audience_id,
                receipt_id=capability.receipt_id,
                consumed_at=now_ts,
                consumer_id=consumer,
                request_digest=capability.request_digest,
                metadata=FrozenMap(metadata or {}),
            )
            self._records[key] = record
            self._nonces[nonce_key] = cap_id
            return record

    def get_record(
        self,
        capability_id: str,
        *,
        tenant_id: str,
    ) -> CapabilityConsumptionRecord | None:
        tenant = _identifier(tenant_id, "tenant_id")
        cap_id = _identifier(capability_id, "capability_id")
        with self._lock:
            return self._records.get((tenant, cap_id))

    def size(self) -> int:
        with self._lock:
            return len(self._records)

    def clear(self) -> None:
        """Test helper — wipe all records."""

        with self._lock:
            self._records.clear()
            self._nonces.clear()


# ---------------------------------------------------------------------------
# Fake dispatcher + post-dispatch observation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DispatchObservation:
    """Post-dispatch runtime observation — **not** an authorization receipt.

    Emitted only after a successful (or attempted) side-effect dispatch so
    telemetry/completion tracking stays separate from theorem-grade decision
    identity.
    """

    observation_id: str
    capability_id: str
    receipt_id: str
    tenant_id: str
    audience_id: str
    dispatcher_id: str
    dispatch_status: str
    started_at: str
    completed_at: str
    dispatch_count: int
    request_digest: str = ""
    result_digest: str = ""
    error_message: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = DISPATCH_OBSERVATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "observation_id",
            _identifier(self.observation_id, "observation_id"),
        )
        object.__setattr__(
            self,
            "capability_id",
            _identifier(self.capability_id, "capability_id"),
        )
        object.__setattr__(
            self, "receipt_id", _identifier(self.receipt_id, "receipt_id")
        )
        object.__setattr__(
            self, "tenant_id", _identifier(self.tenant_id, "tenant_id")
        )
        object.__setattr__(
            self, "audience_id", _identifier(self.audience_id, "audience_id")
        )
        object.__setattr__(
            self,
            "dispatcher_id",
            _identifier(self.dispatcher_id, "dispatcher_id"),
        )
        object.__setattr__(
            self,
            "dispatch_status",
            _text(self.dispatch_status, "dispatch_status", max_chars=64),
        )
        if not isinstance(self.dispatch_count, int) or self.dispatch_count < 0:
            raise EnforcementError("dispatch_count must be a non-negative int")
        object.__setattr__(
            self,
            "metadata",
            self.metadata
            if isinstance(self.metadata, FrozenMap)
            else FrozenMap(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "audience_id": self.audience_id,
            "capability_id": self.capability_id,
            "completed_at": self.completed_at,
            "dispatch_count": self.dispatch_count,
            "dispatch_status": self.dispatch_status,
            "dispatcher_id": self.dispatcher_id,
            "error_message": self.error_message,
            "metadata": self.metadata.to_dict(),
            "observation_id": self.observation_id,
            "receipt_id": self.receipt_id,
            "request_digest": self.request_digest,
            "result_digest": self.result_digest,
            "schema_version": self.schema_version,
            "started_at": self.started_at,
            "tenant_id": self.tenant_id,
        }

    @property
    def is_authorization_receipt(self) -> bool:
        """Always False — observations are never authorization receipts."""

        return False


@dataclass
class FakeDispatcher:
    """In-process fake side-effect dispatcher for unit / race tests.

    Records every call so tests can assert zero invocations on rejection and
    exactly one on success.  Never touches real tools or networks.
    """

    dispatcher_id: str = DEFAULT_DISPATCHER_ID
    result_payload: Mapping[str, Any] = field(default_factory=dict)
    raise_on_call: BaseException | None = None
    _calls: list[dict[str, Any]] = field(default_factory=list, init=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)

    @property
    def call_count(self) -> int:
        with self._lock:
            return len(self._calls)

    @property
    def calls(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(dict(c) for c in self._calls)

    def reset(self) -> None:
        with self._lock:
            self._calls.clear()

    def dispatch(
        self,
        *,
        capability: AuthorizationCapability,
        binding: InvocationBinding,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record a dispatch attempt and return a deterministic fake result."""

        entry = {
            "audience_id": binding.audience_id,
            "capability_digest": capability.digest,
            "capability_id": capability.capability_id,
            "nonce": capability.nonce,
            "payload": dict(payload or {}),
            "receipt_id": capability.receipt_id,
            "request_digest": binding.request_digest,
            "tenant_id": binding.tenant_id,
            "tool_id": binding.tool_id,
        }
        with self._lock:
            self._calls.append(entry)
            if self.raise_on_call is not None:
                raise self.raise_on_call
            result = {
                "dispatcher_id": self.dispatcher_id,
                "ok": True,
                "result": dict(self.result_payload),
                "call_index": len(self._calls),
            }
            result["result_digest"] = stable_digest(result)
            return result


# ---------------------------------------------------------------------------
# Enforcement result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EnforcementResult:
    """Outcome of :meth:`PreInvocationEnforcement.enforce_and_dispatch`."""

    allowed: bool
    reason: str
    reason_code: str
    dispatch_ran: bool
    receipt: DecisionReceipt | None = None
    capability: AuthorizationCapability | None = None
    consumption: CapabilityConsumptionRecord | None = None
    observation: DispatchObservation | None = None
    dispatch_result: Mapping[str, Any] | None = None
    details: FrozenMap = field(default_factory=FrozenMap)
    interface: str = PRE_INVOCATION_ENFORCEMENT_INTERFACE
    schema_version: str = ENFORCEMENT_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.allowed, bool):
            raise EnforcementError("allowed must be a bool")
        if not isinstance(self.dispatch_ran, bool):
            raise EnforcementError("dispatch_ran must be a bool")
        # Observation is strictly post-dispatch (success or dispatch error).
        # Authorization rejection before dispatch must not produce one.
        if self.observation is not None and not self.dispatch_ran:
            raise EnforcementError(
                "observation present without dispatch attempt"
            )
        if self.dispatch_ran and self.observation is None:
            raise EnforcementError(
                "dispatch_ran requires a post-dispatch observation"
            )
        # Full success requires both authorization and a successful dispatch.
        if self.allowed and not self.dispatch_ran and self.observation is not None:
            raise EnforcementError(
                "allowed with observation requires dispatch_ran"
            )
        object.__setattr__(
            self,
            "details",
            self.details
            if isinstance(self.details, FrozenMap)
            else FrozenMap(self.details),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "capability": (
                None if self.capability is None else self.capability.to_dict()
            ),
            "consumption": (
                None
                if self.consumption is None
                else self.consumption.to_dict()
            ),
            "details": self.details.to_dict(),
            "dispatch_ran": self.dispatch_ran,
            "dispatch_result": (
                None
                if self.dispatch_result is None
                else dict(self.dispatch_result)
            ),
            "interface": self.interface,
            "observation": (
                None
                if self.observation is None
                else self.observation.to_dict()
            ),
            "reason": self.reason,
            "reason_code": self.reason_code,
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "schema_version": self.schema_version,
        }


# ---------------------------------------------------------------------------
# PreInvocationEnforcement@1
# ---------------------------------------------------------------------------


def _reject(
    reason: str,
    reason_code: str,
    *,
    receipt: DecisionReceipt | None = None,
    capability: AuthorizationCapability | None = None,
    details: Mapping[str, Any] | None = None,
) -> EnforcementResult:
    return EnforcementResult(
        allowed=False,
        reason=reason[:MAX_REASON_CHARS],
        reason_code=reason_code,
        dispatch_ran=False,
        receipt=receipt,
        capability=capability,
        details=FrozenMap(details or {}),
    )


def _environment_digest_from(
    environment: Mapping[str, Any] | None,
    *,
    fallback_digest: str = "",
    fallback_id: str = "",
) -> tuple[str, str]:
    """Derive (environment_digest, environment_id) from a live snapshot."""

    if not environment:
        return fallback_digest, fallback_id
    env_id = _optional_identifier(
        environment.get("environment_id", fallback_id), "environment_id"
    )
    raw = (
        environment.get("environment_digest")
        or environment.get("snapshot_digest")
        or ""
    )
    if raw:
        digest = _digest(str(raw), "environment_digest")
    else:
        # Hash non-secret snapshot fields only.
        safe = {
            k: v
            for k, v in environment.items()
            if k
            not in {
                "secret",
                "secrets",
                "token",
                "password",
                "credential",
                "private_key",
                "api_key",
            }
        }
        digest = stable_digest(safe) if safe else fallback_digest
    return digest, env_id


def verify_invocation_binding(
    receipt: DecisionReceipt,
    binding: InvocationBinding,
    *,
    capability: AuthorizationCapability | None = None,
    live_roots: BoundRoots | None = None,
    live_environment: Mapping[str, Any] | None = None,
    now: str | None = None,
) -> None:
    """Immediately verify receipt/capability against the live binding.

    Checks actor, delegation, audience, request, arguments, tool, version,
    effects, nonce, expiry, policy/corpus/revocation roots, and fresh
    environment.  Raises :class:`EnforcementRejection` on any mismatch.
    """

    try:
        verify_decision_receipt(
            receipt,
            now=now,
            expected_roots=live_roots if live_roots is not None else binding.roots,
            expected_audience=binding.audience_id,
            expected_request_digest=binding.request_digest,
            expected_actor=binding.actor_id,
            expected_nonce=binding.nonce,
            require_not_expired=now is not None,
        )
    except ReceiptVerificationError as exc:
        raise EnforcementRejection(
            str(exc),
            reason_code=EnforcementReasonCode.RECEIPT_INVALID.value,
        ) from exc
    except ReceiptError as exc:
        raise EnforcementRejection(
            str(exc),
            reason_code=EnforcementReasonCode.RECEIPT_INVALID.value,
        ) from exc

    ctx = receipt.context

    if ctx.arguments_digest != binding.arguments_digest:
        raise EnforcementRejection(
            "arguments_digest mismatch (context mutation detected)",
            reason_code=EnforcementReasonCode.CONTEXT_MISMATCH.value,
        )
    if ctx.tool_id != binding.tool_id:
        raise EnforcementRejection(
            f"tool_id mismatch: receipt={ctx.tool_id!r} live={binding.tool_id!r}",
            reason_code=EnforcementReasonCode.CONTEXT_MISMATCH.value,
        )
    if ctx.tool_version != binding.tool_version:
        raise EnforcementRejection(
            f"tool_version mismatch: receipt={ctx.tool_version!r} "
            f"live={binding.tool_version!r}",
            reason_code=EnforcementReasonCode.CONTEXT_MISMATCH.value,
        )
    if tuple(sorted(ctx.effect_ids)) != tuple(sorted(binding.effect_ids)):
        # At dispatch, effects must not widen beyond the receipt.  Exact match
        # is required for the live binding used by the enforcer.
        if set(binding.effect_ids) - set(ctx.effect_ids):
            raise EnforcementRejection(
                "live effect_ids widen beyond receipt effects",
                reason_code=EnforcementReasonCode.CONTEXT_MISMATCH.value,
            )
        # Strict equality of the declared binding set against the receipt
        # (caller must re-present the exact effect set they intend to run).
        if set(binding.effect_ids) != set(ctx.effect_ids):
            # Allow subset attenuation of effects only when a capability is
            # present and its allowed_effects match the live binding.
            if capability is None:
                raise EnforcementRejection(
                    "effect_ids mismatch with receipt (no capability attenuation)",
                    reason_code=EnforcementReasonCode.CONTEXT_MISMATCH.value,
                )
            if set(binding.effect_ids) != set(capability.allowed_effects):
                raise EnforcementRejection(
                    "live effect_ids do not match capability allowed_effects",
                    reason_code=EnforcementReasonCode.CONTEXT_MISMATCH.value,
                )
    if tuple(sorted(ctx.delegation_ids)) != tuple(
        sorted(binding.delegation_ids)
    ):
        raise EnforcementRejection(
            "delegation_ids mismatch",
            reason_code=EnforcementReasonCode.CONTEXT_MISMATCH.value,
        )
    if ctx.delegation_digest and binding.delegation_digest:
        if ctx.delegation_digest != binding.delegation_digest:
            raise EnforcementRejection(
                "delegation_digest mismatch",
                reason_code=EnforcementReasonCode.CONTEXT_MISMATCH.value,
            )

    # Fresh environment (TOCTOU protection).
    live_env_digest, live_env_id = _environment_digest_from(
        live_environment,
        fallback_digest=binding.environment_digest,
        fallback_id=binding.environment_id,
    )
    if ctx.environment_digest:
        if live_env_digest and live_env_digest != ctx.environment_digest:
            raise EnforcementRejection(
                "environment_digest mismatch (fresh environment changed)",
                reason_code=EnforcementReasonCode.ENVIRONMENT_MISMATCH.value,
            )
        if (
            binding.environment_digest
            and binding.environment_digest != ctx.environment_digest
        ):
            raise EnforcementRejection(
                "binding environment_digest mismatch",
                reason_code=EnforcementReasonCode.ENVIRONMENT_MISMATCH.value,
            )
    if ctx.environment_id:
        if live_env_id and live_env_id != ctx.environment_id:
            raise EnforcementRejection(
                "environment_id mismatch (fresh environment changed)",
                reason_code=EnforcementReasonCode.ENVIRONMENT_MISMATCH.value,
            )
        if (
            binding.environment_id
            and binding.environment_id != ctx.environment_id
        ):
            raise EnforcementRejection(
                "binding environment_id mismatch",
                reason_code=EnforcementReasonCode.ENVIRONMENT_MISMATCH.value,
            )

    # Roots: live roots must match receipt roots exactly.
    expected_roots = live_roots if live_roots is not None else binding.roots
    if expected_roots is not None and not receipt.roots.matches(expected_roots):
        raise EnforcementRejection(
            "policy/corpus/revocation/circuit/VK roots are stale or mismatched",
            reason_code=EnforcementReasonCode.ROOTS_MISMATCH.value,
        )

    if capability is not None:
        try:
            verify_capability(
                capability,
                receipt,
                now=now,
                expected_audience=binding.audience_id,
                expected_roots=expected_roots,
                expected_request_digest=binding.request_digest,
                require_not_expired=now is not None,
            )
        except ReceiptVerificationError as exc:
            raise EnforcementRejection(
                str(exc),
                reason_code=EnforcementReasonCode.CAPABILITY_INVALID.value,
            ) from exc
        except ReceiptError as exc:
            raise EnforcementRejection(
                str(exc),
                reason_code=EnforcementReasonCode.CAPABILITY_INVALID.value,
            ) from exc
        if capability.nonce != binding.nonce:
            raise EnforcementRejection(
                "capability nonce mismatch with live binding",
                reason_code=EnforcementReasonCode.CONTEXT_MISMATCH.value,
            )


@dataclass
class PreInvocationEnforcement:
    """``PreInvocationEnforcement@1`` — pre-dispatch gate for side effects.

    Workflow:

    1. Reject unless the receipt is an exact current ``allow``.
    2. Immediately revalidate actor/delegation/audience/request/arguments/
       tool/version/effects, nonce/expiry, policy/corpus/revocation roots,
       and the fresh environment.
    3. Atomically compare-and-consume the one-time capability.
    4. Invoke the (fake or injected) dispatcher **once** on success.
    5. Emit a post-dispatch observation separate from the auth receipt.

    Fail closed on race, state error, or any verification failure.  Dispatch
    runs zero times on rejection.
    """

    store: CapabilityConsumptionStore
    dispatcher: FakeDispatcher | None = None
    consumer_id: str = DEFAULT_CONSUMER_ID
    clock: Callable[[], str] = field(default=_utc_now_iso)
    raise_on_reject: bool = False
    interface: str = PRE_INVOCATION_ENFORCEMENT_INTERFACE
    schema_version: str = PRE_INVOCATION_ENFORCEMENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.store, CapabilityConsumptionStore):
            # Structural check via Protocol methods.
            required = ("compare_and_consume", "is_consumed", "get_record")
            for name in required:
                if not callable(getattr(self.store, name, None)):
                    raise EnforcementError(
                        f"store missing required method {name!r}"
                    )
        object.__setattr__(
            self, "consumer_id", _identifier(self.consumer_id, "consumer_id")
        )
        if self.interface != PRE_INVOCATION_ENFORCEMENT_INTERFACE:
            raise EnforcementError(
                f"unsupported enforcement interface: {self.interface!r}"
            )
        if self.schema_version != PRE_INVOCATION_ENFORCEMENT_SCHEMA_VERSION:
            raise EnforcementError(
                f"unsupported enforcement schema: {self.schema_version!r}"
            )

    def enforce(
        self,
        *,
        receipt: DecisionReceipt | Mapping[str, Any] | None,
        capability: AuthorizationCapability | Mapping[str, Any] | None,
        binding: InvocationBinding | Mapping[str, Any],
        live_roots: BoundRoots | Mapping[str, Any] | None = None,
        live_environment: Mapping[str, Any] | None = None,
        now: str | None = None,
        consume: bool = True,
    ) -> EnforcementResult:
        """Validate and optionally consume without dispatching.

        Use :meth:`enforce_and_dispatch` when a side effect must run.
        """

        return self._run(
            receipt=receipt,
            capability=capability,
            binding=binding,
            live_roots=live_roots,
            live_environment=live_environment,
            now=now,
            consume=consume,
            run_dispatch=False,
            dispatch_payload=None,
        )

    def enforce_and_dispatch(
        self,
        *,
        receipt: DecisionReceipt | Mapping[str, Any] | None,
        capability: AuthorizationCapability | Mapping[str, Any] | None,
        binding: InvocationBinding | Mapping[str, Any],
        live_roots: BoundRoots | Mapping[str, Any] | None = None,
        live_environment: Mapping[str, Any] | None = None,
        now: str | None = None,
        dispatch_payload: Mapping[str, Any] | None = None,
    ) -> EnforcementResult:
        """Full pre-dispatch path: verify → consume → dispatch once → observe."""

        return self._run(
            receipt=receipt,
            capability=capability,
            binding=binding,
            live_roots=live_roots,
            live_environment=live_environment,
            now=now,
            consume=True,
            run_dispatch=True,
            dispatch_payload=dispatch_payload,
        )

    def _run(
        self,
        *,
        receipt: DecisionReceipt | Mapping[str, Any] | None,
        capability: AuthorizationCapability | Mapping[str, Any] | None,
        binding: InvocationBinding | Mapping[str, Any],
        live_roots: BoundRoots | Mapping[str, Any] | None,
        live_environment: Mapping[str, Any] | None,
        now: str | None,
        consume: bool,
        run_dispatch: bool,
        dispatch_payload: Mapping[str, Any] | None,
    ) -> EnforcementResult:
        clock_now = now if now is not None else self.clock()

        try:
            bind = (
                binding
                if isinstance(binding, InvocationBinding)
                else InvocationBinding.from_dict(binding)
            )
        except EnforcementError as exc:
            return self._finish_reject(
                str(exc),
                EnforcementReasonCode.CONTEXT_MISMATCH.value,
            )

        if receipt is None:
            return self._finish_reject(
                "missing decision receipt",
                EnforcementReasonCode.MISSING_RECEIPT.value,
            )
        try:
            if isinstance(receipt, Mapping):
                receipt_obj = DecisionReceipt.from_dict(receipt)
            elif isinstance(receipt, DecisionReceipt):
                receipt_obj = receipt
            else:
                return self._finish_reject(
                    "receipt must be a DecisionReceipt or mapping",
                    EnforcementReasonCode.RECEIPT_INVALID.value,
                )
            receipt_obj.verify_integrity()
        except (ReceiptError, EnforcementError) as exc:
            return self._finish_reject(
                f"receipt invalid: {exc}",
                EnforcementReasonCode.RECEIPT_INVALID.value,
            )

        # Reject every non-allow before any further work or dispatch.
        if not receipt_obj.permits_capability_derivation:
            return self._finish_reject(
                f"non-allow decision rejected at enforcement boundary "
                f"(outcome={receipt_obj.outcome.value!r}, "
                f"wire_status={receipt_obj.wire_status.value!r})",
                EnforcementReasonCode.NON_ALLOW.value,
                receipt=receipt_obj,
                details={
                    "outcome": receipt_obj.outcome.value,
                    "wire_status": receipt_obj.wire_status.value,
                },
            )

        if capability is None:
            return self._finish_reject(
                "missing dispatch capability",
                EnforcementReasonCode.MISSING_CAPABILITY.value,
                receipt=receipt_obj,
            )
        try:
            if isinstance(capability, Mapping):
                cap_obj = AuthorizationCapability.from_dict(capability)
            elif isinstance(capability, AuthorizationCapability):
                cap_obj = capability
            else:
                return self._finish_reject(
                    "capability must be an AuthorizationCapability or mapping",
                    EnforcementReasonCode.CAPABILITY_INVALID.value,
                    receipt=receipt_obj,
                )
            cap_obj.verify_integrity()
        except (ReceiptError, EnforcementError) as exc:
            return self._finish_reject(
                f"capability invalid: {exc}",
                EnforcementReasonCode.CAPABILITY_INVALID.value,
                receipt=receipt_obj,
            )

        roots_obj: BoundRoots | None
        if live_roots is None:
            roots_obj = bind.roots
        elif isinstance(live_roots, BoundRoots):
            roots_obj = live_roots
        elif isinstance(live_roots, Mapping):
            try:
                roots_obj = BoundRoots.from_dict(live_roots)
            except ReceiptError as exc:
                return self._finish_reject(
                    f"live roots invalid: {exc}",
                    EnforcementReasonCode.ROOTS_MISMATCH.value,
                    receipt=receipt_obj,
                    capability=cap_obj,
                )
        else:
            return self._finish_reject(
                "live_roots must be BoundRoots or mapping",
                EnforcementReasonCode.ROOTS_MISMATCH.value,
                receipt=receipt_obj,
                capability=cap_obj,
            )

        try:
            verify_invocation_binding(
                receipt_obj,
                bind,
                capability=cap_obj,
                live_roots=roots_obj,
                live_environment=live_environment,
                now=clock_now,
            )
        except EnforcementRejection as exc:
            return self._finish_reject(
                str(exc),
                exc.reason_code,
                receipt=receipt_obj,
                capability=cap_obj,
                details=exc.details,
            )

        # Tenant isolation on metadata when present.
        receipt_tenant = ""
        if isinstance(receipt_obj.context.metadata, FrozenMap):
            receipt_tenant = str(
                receipt_obj.context.metadata.to_dict().get("tenant_id", "")
                or ""
            )
        if receipt_tenant and receipt_tenant != bind.tenant_id:
            return self._finish_reject(
                f"tenant mismatch: receipt={receipt_tenant!r} "
                f"binding={bind.tenant_id!r}",
                EnforcementReasonCode.TENANT_MISMATCH.value,
                receipt=receipt_obj,
                capability=cap_obj,
            )

        consumption: CapabilityConsumptionRecord | None = None
        if consume:
            try:
                consumption = self.store.compare_and_consume(
                    cap_obj,
                    tenant_id=bind.tenant_id,
                    now=clock_now,
                    consumer_id=self.consumer_id,
                )
            except ConsumptionRaceError as exc:
                return self._finish_reject(
                    str(exc),
                    EnforcementReasonCode.CONSUMPTION_RACE.value,
                    receipt=receipt_obj,
                    capability=cap_obj,
                    details={"capability_id": exc.capability_id},
                )
            except (ConsumptionStoreError, EnforcementError) as exc:
                return self._finish_reject(
                    f"consumption failed closed: {exc}",
                    EnforcementReasonCode.CONSUMPTION_ERROR.value,
                    receipt=receipt_obj,
                    capability=cap_obj,
                )
            except Exception as exc:  # noqa: BLE001 — fail closed
                return self._finish_reject(
                    f"consumption store error: {type(exc).__name__}: {exc}",
                    EnforcementReasonCode.CONSUMPTION_ERROR.value,
                    receipt=receipt_obj,
                    capability=cap_obj,
                )

        if not run_dispatch:
            return EnforcementResult(
                allowed=True,
                reason="capability verified and consumed; dispatch not requested",
                reason_code=EnforcementReasonCode.ALLOWED.value,
                dispatch_ran=False,
                receipt=receipt_obj,
                capability=cap_obj,
                consumption=consumption,
            )

        dispatcher = self.dispatcher
        if dispatcher is None:
            return self._finish_reject(
                "no dispatcher configured for enforce_and_dispatch",
                EnforcementReasonCode.DISPATCH_ERROR.value,
                receipt=receipt_obj,
                capability=cap_obj,
                details={"consumed": consumption is not None},
            )

        started = clock_now
        observation: DispatchObservation | None = None
        dispatch_result: dict[str, Any] | None = None
        try:
            dispatch_result = dispatcher.dispatch(
                capability=cap_obj,
                binding=bind,
                payload=dispatch_payload,
            )
            completed = self.clock() if now is None else clock_now
            result_digest = str(dispatch_result.get("result_digest", "") or "")
            observation = DispatchObservation(
                observation_id=(
                    f"obs:{cap_obj.capability_id}:{consumption.consumed_at if consumption else started}"
                ),
                capability_id=cap_obj.capability_id,
                receipt_id=cap_obj.receipt_id,
                tenant_id=bind.tenant_id,
                audience_id=bind.audience_id,
                dispatcher_id=getattr(
                    dispatcher, "dispatcher_id", DEFAULT_DISPATCHER_ID
                ),
                dispatch_status="ok",
                started_at=started,
                completed_at=completed,
                dispatch_count=1,
                request_digest=bind.request_digest,
                result_digest=result_digest
                if result_digest
                and len(result_digest) == 64
                and all(c in "0123456789abcdef" for c in result_digest)
                else (
                    stable_digest(dispatch_result)
                    if dispatch_result
                    else ""
                ),
                metadata=FrozenMap(
                    {
                        "observation_kind": "post_dispatch",
                        "authorization_receipt_id": receipt_obj.receipt_id,
                    }
                ),
            )
        except Exception as exc:  # noqa: BLE001 — observe failure, fail closed
            completed = self.clock() if now is None else clock_now
            observation = DispatchObservation(
                observation_id=f"obs:{cap_obj.capability_id}:error",
                capability_id=cap_obj.capability_id,
                receipt_id=cap_obj.receipt_id,
                tenant_id=bind.tenant_id,
                audience_id=bind.audience_id,
                dispatcher_id=getattr(
                    dispatcher, "dispatcher_id", DEFAULT_DISPATCHER_ID
                ),
                dispatch_status="error",
                started_at=started,
                completed_at=completed,
                dispatch_count=1,
                request_digest=bind.request_digest,
                error_message=f"{type(exc).__name__}: {exc}"[:MAX_REASON_CHARS],
                metadata=FrozenMap(
                    {
                        "observation_kind": "post_dispatch",
                        "authorization_receipt_id": receipt_obj.receipt_id,
                    }
                ),
            )
            return EnforcementResult(
                allowed=False,
                reason=f"dispatch failed after consumption: {exc}",
                reason_code=EnforcementReasonCode.DISPATCH_ERROR.value,
                dispatch_ran=True,
                receipt=receipt_obj,
                capability=cap_obj,
                consumption=consumption,
                observation=observation,
                details=FrozenMap({"exception_type": type(exc).__name__}),
            )

        return EnforcementResult(
            allowed=True,
            reason="dispatch authorized and executed once",
            reason_code=EnforcementReasonCode.ALLOWED.value,
            dispatch_ran=True,
            receipt=receipt_obj,
            capability=cap_obj,
            consumption=consumption,
            observation=observation,
            dispatch_result=dispatch_result,
        )

    def _finish_reject(
        self,
        reason: str,
        reason_code: str,
        *,
        receipt: DecisionReceipt | None = None,
        capability: AuthorizationCapability | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> EnforcementResult:
        result = _reject(
            reason,
            reason_code,
            receipt=receipt,
            capability=capability,
            details=details,
        )
        if self.raise_on_reject:
            raise EnforcementRejection(
                reason, reason_code=reason_code, details=details
            )
        return result


def consume_dispatch_capability(
    store: CapabilityConsumptionStore,
    capability: AuthorizationCapability | Mapping[str, Any],
    *,
    tenant_id: str,
    now: str | None = None,
    consumer_id: str = DEFAULT_CONSUMER_ID,
) -> CapabilityConsumptionRecord:
    """Public helper matching the plan surface ``consume_dispatch_capability``.

    Atomically marks the capability consumed for *tenant_id*.  Fail closed on
    race or integrity error.
    """

    if isinstance(capability, Mapping):
        capability = AuthorizationCapability.from_dict(capability)
    if not isinstance(capability, AuthorizationCapability):
        raise ConsumptionStoreError(
            "capability must be an AuthorizationCapability or mapping"
        )
    capability.verify_integrity()
    return store.compare_and_consume(
        capability,
        tenant_id=tenant_id,
        now=now or _utc_now_iso(),
        consumer_id=consumer_id,
    )


__all__ = [
    "CAPABILITY_CONSUMPTION_STORE_INTERFACE",
    "CAPABILITY_CONSUMPTION_STORE_SCHEMA_VERSION",
    "DEFAULT_CONSUMER_ID",
    "DEFAULT_DISPATCHER_ID",
    "DISPATCH_OBSERVATION_SCHEMA_VERSION",
    "ENFORCEMENT_RESULT_SCHEMA_VERSION",
    "INVOCATION_BINDING_SCHEMA_VERSION",
    "PRE_INVOCATION_ENFORCEMENT_INTERFACE",
    "PRE_INVOCATION_ENFORCEMENT_SCHEMA_VERSION",
    "CapabilityConsumptionRecord",
    "CapabilityConsumptionStore",
    "ConsumptionRaceError",
    "ConsumptionStoreError",
    "DispatchObservation",
    "EnforcementError",
    "EnforcementReasonCode",
    "EnforcementRejection",
    "EnforcementResult",
    "FakeDispatcher",
    "InMemoryCapabilityConsumptionStore",
    "InvocationBinding",
    "PreInvocationEnforcement",
    "consume_dispatch_capability",
    "verify_invocation_binding",
]
