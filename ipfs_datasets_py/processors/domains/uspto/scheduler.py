"""Checkpointed USPTO polling, change detection, and redacted alerts (PATLAW-062).

Resilient application-matter synchronisation:

* bounded per-service / per-content-kind queues (metadata before binary);
* workers **release capacity** while waiting (delayed reschedule, no slot hold);
* 401/403 produce credential-health actions (redacted);
* 429 honors ``Retry-After`` (bounded);
* repeated 5xx opens a per-service circuit breaker;
* parse / security failures go to dead-letter (reviewable, not infinite retry);
* durable checkpoints so restart resumes without duplicate alerts or artifacts;
* heartbeat / progress is content-free (no document bodies or secrets).

The scheduler never signs, pays, files, scrapes, or returns credential secrets.
Poll execution is injected so operators can wire the canonical API/provider
without the scheduler owning analysis logic.
"""

from __future__ import annotations

import email.utils
import hashlib
import json
import math
import os
import re
import time
import uuid
from collections import deque
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Protocol, runtime_checkable

from ipfs_datasets_py.processors.domains.uspto.contracts import canonical_json
from ipfs_datasets_py.processors.domains.uspto.providers.base import (
    CircuitBreaker,
    CircuitBreakerPolicy,
    CircuitState,
    ProviderOutcomeKind,
    format_utc,
    sanitize_secret_text,
    sha256_hex,
)

SCHEDULER_SCHEMA_VERSION: Final = "uspto.application-scheduler.v1"
SCHEDULER_INTERFACE: Final = "USPTOApplicationScheduler@1"

# Hard bounds (transport safety, not USPTO-published rate limits).
DEFAULT_MAX_QUEUE_DEPTH: Final = 256
DEFAULT_MAX_WORKERS: Final = 4
DEFAULT_MAX_RETRY_AFTER_SECONDS: Final = 300.0
DEFAULT_BASE_BACKOFF_SECONDS: Final = 1.0
DEFAULT_MAX_BACKOFF_SECONDS: Final = 120.0
DEFAULT_CIRCUIT_FAILURE_THRESHOLD: Final = 3
DEFAULT_CIRCUIT_RECOVERY_SECONDS: Final = 30.0
DEFAULT_HEARTBEAT_INTERVAL_SECONDS: Final = 30.0
DEFAULT_MAX_ALERTS_RETAINED: Final = 10_000
DEFAULT_MAX_DEAD_LETTERS: Final = 5_000

_SECRET_KEY_FRAGMENTS: Final = frozenset(
    {
        "api_key",
        "apikey",
        "password",
        "secret",
        "token",
        "authorization",
        "cookie",
        "bearer",
        "session",
        "mfa",
        "x-api-key",
    }
)
_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9._:=\-+]+")
_ALERT_BODY_MAX: Final = 512

Clock = Callable[[], float]
WallClock = Callable[[], datetime]
IdFactory = Callable[[], str]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ContentKind(str, Enum):
    """Queue / poll content class. Metadata always precedes binary."""

    METADATA = "metadata"
    BINARY = "binary"


class ServiceName(str, Enum):
    """Supported public services. Private interactive access is out of scope."""

    PATENT_FILE_WRAPPER = "patent_file_wrapper"
    APPLICATION_STATUS = "application_status"
    DOCUMENT_INVENTORY = "document_inventory"
    DOCUMENT_BYTES = "document_bytes"


class JobState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"  # delayed; does **not** hold a worker slot
    SUCCEEDED = "succeeded"
    DEAD_LETTERED = "dead_lettered"
    CANCELLED = "cancelled"


class PollDisposition(str, Enum):
    """High-level classification of one poll attempt."""

    SUCCESS = "success"
    UNCHANGED = "unchanged"
    CHANGED = "changed"
    RATE_LIMITED = "rate_limited"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    UPSTREAM_ERROR = "upstream_error"
    CLIENT_ERROR = "client_error"
    PARSE_FAILURE = "parse_failure"
    SECURITY_FAILURE = "security_failure"
    CIRCUIT_OPEN = "circuit_open"
    NOT_FOUND = "not_found"
    CANCELLED = "cancelled"
    TRANSPORT_ERROR = "transport_error"


class AlertKind(str, Enum):
    CREDENTIAL_HEALTH = "credential_health"
    RATE_LIMIT = "rate_limit"
    CIRCUIT_OPEN = "circuit_open"
    CIRCUIT_CLOSED = "circuit_closed"
    DEAD_LETTER = "dead_letter"
    CHANGE_DETECTED = "change_detected"
    HEARTBEAT = "heartbeat"
    JOB_SUCCEEDED = "job_succeeded"
    JOB_WAITING = "job_waiting"


class ActionKind(str, Enum):
    """Operator-facing actions produced by the scheduler (never automated file/pay)."""

    CREDENTIAL_HEALTH = "credential_health"
    REVIEW_DEAD_LETTER = "review_dead_letter"
    CIRCUIT_RECOVERY = "circuit_recovery"
    RESUME_POLL = "resume_poll"


class DeadLetterReason(str, Enum):
    PARSE_FAILURE = "parse_failure"
    SECURITY_FAILURE = "security_failure"
    PERMANENT_CLIENT_ERROR = "permanent_client_error"
    OPERATOR = "operator"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SchedulerError(ValueError):
    """Fail-closed scheduler configuration or contract error."""

    def __init__(self, message: str, *, code: str = "scheduler_error") -> None:
        super().__init__(sanitize_secret_text(message))
        self.code = code

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


class QueueFullError(SchedulerError):
    def __init__(self, service: str, content_kind: str) -> None:
        super().__init__(
            f"queue full for service={service!r} content_kind={content_kind!r}",
            code="queue_full",
        )
        self.service = service
        self.content_kind = content_kind


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _positive_int(value: int, name: str, *, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SchedulerError(f"{name} must be a positive integer", code="invalid_config")
    if maximum is not None and value > maximum:
        raise SchedulerError(
            f"{name} must not exceed {maximum}",
            code="invalid_config",
        )
    return value


def _nonneg_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SchedulerError(
            f"{name} must be a non-negative integer", code="invalid_config"
        )
    return value


def _nonneg_float(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchedulerError(
            f"{name} must be a non-negative finite number", code="invalid_config"
        )
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise SchedulerError(
            f"{name} must be a non-negative finite number", code="invalid_config"
        )
    return result


def _positive_float(value: float, name: str) -> float:
    result = _nonneg_float(value, name)
    if result <= 0:
        raise SchedulerError(
            f"{name} must be a positive finite number", code="invalid_config"
        )
    return result


def _safe_id(value: str, *, field_name: str = "id") -> str:
    text = str(value or "").strip()
    if not text or len(text) > 256:
        raise SchedulerError(
            f"{field_name} must be a non-empty string ≤256 chars",
            code="invalid_id",
        )
    if any(ch in text for ch in ("\x00", "\r", "\n")):
        raise SchedulerError(f"{field_name} contains control characters", code="invalid_id")
    return text


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _redact_mapping(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Drop secret-bearing keys and sanitize free-form strings."""
    if not payload:
        return {}
    out: dict[str, Any] = {}
    for key, val in payload.items():
        key_s = str(key)
        key_l = key_s.lower()
        if key_l in _SECRET_KEY_FRAGMENTS or any(
            frag in key_l for frag in _SECRET_KEY_FRAGMENTS
        ):
            continue
        if isinstance(val, Mapping):
            out[key_s] = _redact_mapping(val)
        elif isinstance(val, (list, tuple)):
            out[key_s] = [
                _redact_mapping(v) if isinstance(v, Mapping) else (
                    sanitize_secret_text(str(v)) if isinstance(v, str) else v
                )
                for v in val
            ]
        elif isinstance(val, str):
            out[key_s] = sanitize_secret_text(val)
        elif isinstance(val, (int, float, bool)) or val is None:
            out[key_s] = val
        else:
            out[key_s] = sanitize_secret_text(str(val))
    return out


def parse_retry_after(
    headers: Mapping[str, str] | None,
    *,
    now: datetime | None = None,
    max_seconds: float = DEFAULT_MAX_RETRY_AFTER_SECONDS,
) -> float | None:
    """Parse HTTP ``Retry-After`` (seconds or HTTP-date). Returns capped delay."""
    if not headers:
        return None
    value = None
    for key, item in headers.items():
        if str(key).lower() == "retry-after":
            value = item
            break
    if value is None:
        return None
    stripped = str(value).strip()
    try:
        delay = float(stripped)
    except ValueError:
        try:
            target = email.utils.parsedate_to_datetime(stripped)
        except (TypeError, ValueError, OverflowError):
            return None
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        current = now or datetime.now(timezone.utc)
        delay = (target - current).total_seconds()
    if not math.isfinite(delay):
        return None
    cap = _nonneg_float(max_seconds, "max_seconds")
    return min(max(0.0, delay), cap)


def disposition_from_status(status_code: int | None) -> PollDisposition:
    if status_code is None:
        return PollDisposition.TRANSPORT_ERROR
    if status_code == 401:
        return PollDisposition.UNAUTHORIZED
    if status_code == 403:
        return PollDisposition.FORBIDDEN
    if status_code == 404:
        return PollDisposition.NOT_FOUND
    if status_code == 429:
        return PollDisposition.RATE_LIMITED
    if 200 <= status_code < 300 or status_code == 304:
        return PollDisposition.SUCCESS
    if 500 <= status_code <= 599:
        return PollDisposition.UPSTREAM_ERROR
    if 400 <= status_code <= 499:
        return PollDisposition.CLIENT_ERROR
    return PollDisposition.TRANSPORT_ERROR


def disposition_from_provider_kind(kind: ProviderOutcomeKind | str) -> PollDisposition:
    key = kind.value if isinstance(kind, ProviderOutcomeKind) else str(kind)
    mapping = {
        ProviderOutcomeKind.SUCCESS.value: PollDisposition.SUCCESS,
        ProviderOutcomeKind.NOT_MODIFIED.value: PollDisposition.UNCHANGED,
        ProviderOutcomeKind.UNAUTHORIZED.value: PollDisposition.UNAUTHORIZED,
        ProviderOutcomeKind.FORBIDDEN.value: PollDisposition.FORBIDDEN,
        ProviderOutcomeKind.NOT_FOUND.value: PollDisposition.NOT_FOUND,
        ProviderOutcomeKind.RATE_LIMITED.value: PollDisposition.RATE_LIMITED,
        ProviderOutcomeKind.UPSTREAM_ERROR.value: PollDisposition.UPSTREAM_ERROR,
        ProviderOutcomeKind.CLIENT_ERROR.value: PollDisposition.CLIENT_ERROR,
        ProviderOutcomeKind.MALFORMED.value: PollDisposition.PARSE_FAILURE,
        ProviderOutcomeKind.SCHEMA_DRIFT.value: PollDisposition.PARSE_FAILURE,
        ProviderOutcomeKind.CANCELLED.value: PollDisposition.CANCELLED,
        ProviderOutcomeKind.CIRCUIT_OPEN.value: PollDisposition.CIRCUIT_OPEN,
        ProviderOutcomeKind.TRANSPORT_ERROR.value: PollDisposition.TRANSPORT_ERROR,
        ProviderOutcomeKind.RETRY_BUDGET_EXHAUSTED.value: PollDisposition.UPSTREAM_ERROR,
    }
    return mapping.get(key, PollDisposition.TRANSPORT_ERROR)


def _default_id_factory() -> str:
    return uuid.uuid4().hex


def _fingerprint_material(
    *,
    content_sha256: str | None,
    etag: str | None,
    last_modified: str | None,
    payload_digest: str | None,
) -> str:
    material = {
        "content_sha256": content_sha256 or "",
        "etag": etag or "",
        "last_modified": last_modified or "",
        "payload_digest": payload_digest or "",
    }
    return sha256_hex(canonical_json(material))


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SchedulerConfig:
    """Operator-injected scheduler bounds (no invented USPTO rate constants)."""

    max_workers: int = DEFAULT_MAX_WORKERS
    max_queue_depth: int = DEFAULT_MAX_QUEUE_DEPTH
    max_retry_after_seconds: float = DEFAULT_MAX_RETRY_AFTER_SECONDS
    base_backoff_seconds: float = DEFAULT_BASE_BACKOFF_SECONDS
    max_backoff_seconds: float = DEFAULT_MAX_BACKOFF_SECONDS
    circuit_failure_threshold: int = DEFAULT_CIRCUIT_FAILURE_THRESHOLD
    circuit_recovery_seconds: float = DEFAULT_CIRCUIT_RECOVERY_SECONDS
    heartbeat_interval_seconds: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS
    max_alerts_retained: int = DEFAULT_MAX_ALERTS_RETAINED
    max_dead_letters: int = DEFAULT_MAX_DEAD_LETTERS
    metadata_before_binary: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "max_workers", _positive_int(self.max_workers, "max_workers", maximum=256)
        )
        object.__setattr__(
            self,
            "max_queue_depth",
            _positive_int(self.max_queue_depth, "max_queue_depth", maximum=100_000),
        )
        object.__setattr__(
            self,
            "max_retry_after_seconds",
            _nonneg_float(self.max_retry_after_seconds, "max_retry_after_seconds"),
        )
        base = _nonneg_float(self.base_backoff_seconds, "base_backoff_seconds")
        maximum = _nonneg_float(self.max_backoff_seconds, "max_backoff_seconds")
        if maximum < base:
            raise SchedulerError(
                "max_backoff_seconds must not be less than base_backoff_seconds",
                code="invalid_config",
            )
        object.__setattr__(self, "base_backoff_seconds", base)
        object.__setattr__(self, "max_backoff_seconds", maximum)
        object.__setattr__(
            self,
            "circuit_failure_threshold",
            _positive_int(self.circuit_failure_threshold, "circuit_failure_threshold"),
        )
        object.__setattr__(
            self,
            "circuit_recovery_seconds",
            _nonneg_float(self.circuit_recovery_seconds, "circuit_recovery_seconds"),
        )
        object.__setattr__(
            self,
            "heartbeat_interval_seconds",
            _positive_float(
                self.heartbeat_interval_seconds, "heartbeat_interval_seconds"
            ),
        )
        object.__setattr__(
            self,
            "max_alerts_retained",
            _positive_int(self.max_alerts_retained, "max_alerts_retained"),
        )
        object.__setattr__(
            self,
            "max_dead_letters",
            _positive_int(self.max_dead_letters, "max_dead_letters"),
        )
        if not isinstance(self.metadata_before_binary, bool):
            raise SchedulerError(
                "metadata_before_binary must be bool", code="invalid_config"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_backoff_seconds": self.base_backoff_seconds,
            "circuit_failure_threshold": self.circuit_failure_threshold,
            "circuit_recovery_seconds": self.circuit_recovery_seconds,
            "heartbeat_interval_seconds": self.heartbeat_interval_seconds,
            "max_alerts_retained": self.max_alerts_retained,
            "max_backoff_seconds": self.max_backoff_seconds,
            "max_dead_letters": self.max_dead_letters,
            "max_queue_depth": self.max_queue_depth,
            "max_retry_after_seconds": self.max_retry_after_seconds,
            "max_workers": self.max_workers,
            "metadata_before_binary": self.metadata_before_binary,
        }


# ---------------------------------------------------------------------------
# Domain records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChangeFingerprint:
    """Dedupe key for change detection (content-free identity)."""

    fingerprint: str
    content_sha256: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    payload_digest: str | None = None

    def __post_init__(self) -> None:
        fp = str(self.fingerprint or "").strip()
        if not fp:
            raise SchedulerError("fingerprint is required", code="invalid_fingerprint")
        object.__setattr__(self, "fingerprint", fp)

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_sha256": self.content_sha256,
            "etag": self.etag,
            "fingerprint": self.fingerprint,
            "last_modified": self.last_modified,
            "payload_digest": self.payload_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "ChangeFingerprint | None":
        if not value or not isinstance(value, Mapping):
            return None
        fp = str(value.get("fingerprint") or "").strip()
        if not fp:
            return None
        return cls(
            fingerprint=fp,
            content_sha256=_optional_str(value.get("content_sha256")),
            etag=_optional_str(value.get("etag")),
            last_modified=_optional_str(value.get("last_modified")),
            payload_digest=_optional_str(value.get("payload_digest")),
        )

    @classmethod
    def build(
        cls,
        *,
        content_sha256: str | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
        payload_digest: str | None = None,
        payload: Any = None,
    ) -> "ChangeFingerprint":
        digest = payload_digest
        if digest is None and payload is not None:
            if isinstance(payload, (bytes, bytearray)):
                digest = sha256_hex(bytes(payload))
            elif isinstance(payload, str):
                digest = sha256_hex(payload)
            else:
                digest = sha256_hex(canonical_json(payload))
        fp = _fingerprint_material(
            content_sha256=content_sha256,
            etag=etag,
            last_modified=last_modified,
            payload_digest=digest,
        )
        return cls(
            fingerprint=fp,
            content_sha256=content_sha256,
            etag=etag,
            last_modified=last_modified,
            payload_digest=digest,
        )


@dataclass(frozen=True, slots=True)
class PollResult:
    """Typed outcome of one injected poll attempt (no secret material)."""

    disposition: PollDisposition
    status_code: int | None = None
    retry_after_seconds: float | None = None
    headers: Mapping[str, str] = field(default_factory=dict)
    fingerprint: ChangeFingerprint | None = None
    artifact_id: str | None = None
    message: str | None = None
    error_code: str | None = None
    labels: Mapping[str, str] = field(default_factory=dict)
    # Optional binary follow-up signal (metadata poll may request binary).
    enqueue_binary: bool = False
    binary_resource_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, PollDisposition):
            object.__setattr__(
                self, "disposition", PollDisposition(str(self.disposition))
            )
        object.__setattr__(
            self,
            "headers",
            MappingProxyType(
                {str(k): str(v) for k, v in dict(self.headers or {}).items()}
            ),
        )
        object.__setattr__(
            self,
            "labels",
            MappingProxyType(
                {str(k): sanitize_secret_text(str(v)) for k, v in dict(self.labels or {}).items()}
            ),
        )
        if self.message is not None:
            object.__setattr__(self, "message", sanitize_secret_text(str(self.message)))
        if self.retry_after_seconds is not None:
            object.__setattr__(
                self,
                "retry_after_seconds",
                _nonneg_float(float(self.retry_after_seconds), "retry_after_seconds"),
            )
        if not isinstance(self.enqueue_binary, bool):
            raise SchedulerError("enqueue_binary must be bool", code="invalid_poll_result")

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "binary_resource_id": self.binary_resource_id,
            "disposition": self.disposition.value,
            "enqueue_binary": self.enqueue_binary,
            "error_code": self.error_code,
            "fingerprint": None
            if self.fingerprint is None
            else self.fingerprint.to_dict(),
            "headers": dict(self.headers),
            "labels": dict(self.labels),
            "message": self.message,
            "retry_after_seconds": self.retry_after_seconds,
            "status_code": self.status_code,
        }

    @classmethod
    def from_http(
        cls,
        status_code: int,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | str | None = None,
        artifact_id: str | None = None,
        message: str | None = None,
        error_code: str | None = None,
        parse_error: bool = False,
        security_error: bool = False,
        enqueue_binary: bool = False,
        binary_resource_id: str | None = None,
        max_retry_after: float = DEFAULT_MAX_RETRY_AFTER_SECONDS,
        wall_now: datetime | None = None,
    ) -> "PollResult":
        """Build a :class:`PollResult` from an HTTP-like response."""
        if security_error:
            disposition = PollDisposition.SECURITY_FAILURE
        elif parse_error:
            disposition = PollDisposition.PARSE_FAILURE
        else:
            disposition = disposition_from_status(status_code)
            if disposition is PollDisposition.SUCCESS and status_code == 304:
                disposition = PollDisposition.UNCHANGED
        headers_map = {str(k): str(v) for k, v in dict(headers or {}).items()}
        retry_after = None
        if disposition is PollDisposition.RATE_LIMITED:
            retry_after = parse_retry_after(
                headers_map, now=wall_now, max_seconds=max_retry_after
            )
        fingerprint = None
        if disposition in (
            PollDisposition.SUCCESS,
            PollDisposition.UNCHANGED,
            PollDisposition.CHANGED,
        ):
            etag = None
            last_modified = None
            for key, val in headers_map.items():
                kl = key.lower()
                if kl == "etag":
                    etag = val
                elif kl == "last-modified":
                    last_modified = val
            content_sha = None
            if isinstance(body, (bytes, bytearray)):
                content_sha = sha256_hex(bytes(body))
            elif isinstance(body, str):
                content_sha = sha256_hex(body)
            fingerprint = ChangeFingerprint.build(
                content_sha256=content_sha,
                etag=etag,
                last_modified=last_modified,
            )
            if disposition is PollDisposition.SUCCESS:
                # Caller may reclassify to CHANGED/UNCHANGED via fingerprint compare.
                pass
        return cls(
            disposition=disposition,
            status_code=status_code,
            retry_after_seconds=retry_after,
            headers=headers_map,
            fingerprint=fingerprint,
            artifact_id=artifact_id,
            message=message,
            error_code=error_code,
            enqueue_binary=enqueue_binary,
            binary_resource_id=binary_resource_id,
        )


@dataclass
class PollJob:
    """One unit of scheduled work (metadata or binary) for a matter/resource."""

    job_id: str
    service: str
    content_kind: ContentKind
    application_number: str
    matter_id: str | None = None
    resource_id: str | None = None
    state: JobState = JobState.PENDING
    attempt: int = 0
    consecutive_upstream_failures: int = 0
    next_run_at: float = 0.0  # monotonic clock
    created_at_utc: str | None = None
    updated_at_utc: str | None = None
    last_disposition: str | None = None
    last_status_code: int | None = None
    last_fingerprint: ChangeFingerprint | None = None
    last_artifact_id: str | None = None
    known_artifact_ids: tuple[str, ...] = ()
    emitted_alert_ids: tuple[str, ...] = ()
    credential_ref_id: str | None = None
    labels: Mapping[str, str] = field(default_factory=dict)
    parent_job_id: str | None = None  # binary jobs may reference metadata parent
    metadata_ready: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_id", _safe_id(self.job_id, field_name="job_id"))
        object.__setattr__(
            self, "service", _safe_id(str(self.service), field_name="service")
        )
        if isinstance(self.content_kind, str):
            self.content_kind = ContentKind(self.content_kind)
        if isinstance(self.state, str):
            self.state = JobState(self.state)
        object.__setattr__(
            self,
            "application_number",
            _safe_id(self.application_number, field_name="application_number"),
        )
        if self.matter_id is not None:
            object.__setattr__(
                self, "matter_id", _safe_id(self.matter_id, field_name="matter_id")
            )
        object.__setattr__(self, "attempt", _nonneg_int(int(self.attempt), "attempt"))
        object.__setattr__(
            self,
            "consecutive_upstream_failures",
            _nonneg_int(
                int(self.consecutive_upstream_failures), "consecutive_upstream_failures"
            ),
        )
        object.__setattr__(
            self,
            "labels",
            MappingProxyType(
                {
                    str(k): sanitize_secret_text(str(v))
                    for k, v in dict(self.labels or {}).items()
                }
            ),
        )
        if not isinstance(self.known_artifact_ids, tuple):
            self.known_artifact_ids = tuple(str(x) for x in self.known_artifact_ids)
        if not isinstance(self.emitted_alert_ids, tuple):
            self.emitted_alert_ids = tuple(str(x) for x in self.emitted_alert_ids)

    def queue_key(self) -> tuple[str, str]:
        return (self.service, self.content_kind.value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_number": self.application_number,
            "attempt": self.attempt,
            "consecutive_upstream_failures": self.consecutive_upstream_failures,
            "content_kind": self.content_kind.value,
            "created_at_utc": self.created_at_utc,
            "credential_ref_id": self.credential_ref_id,
            "emitted_alert_ids": list(self.emitted_alert_ids),
            "job_id": self.job_id,
            "known_artifact_ids": list(self.known_artifact_ids),
            "labels": dict(self.labels),
            "last_artifact_id": self.last_artifact_id,
            "last_disposition": self.last_disposition,
            "last_fingerprint": None
            if self.last_fingerprint is None
            else self.last_fingerprint.to_dict(),
            "last_status_code": self.last_status_code,
            "matter_id": self.matter_id,
            "metadata_ready": self.metadata_ready,
            "next_run_at": self.next_run_at,
            "parent_job_id": self.parent_job_id,
            "resource_id": self.resource_id,
            "service": self.service,
            "state": self.state.value,
            "updated_at_utc": self.updated_at_utc,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PollJob":
        if not isinstance(value, Mapping):
            raise SchedulerError("job payload must be a mapping", code="invalid_job")
        fp = ChangeFingerprint.from_dict(value.get("last_fingerprint"))
        return cls(
            job_id=str(value.get("job_id") or ""),
            service=str(value.get("service") or ""),
            content_kind=ContentKind(str(value.get("content_kind") or "metadata")),
            application_number=str(value.get("application_number") or ""),
            matter_id=_optional_str(value.get("matter_id")),
            resource_id=_optional_str(value.get("resource_id")),
            state=JobState(str(value.get("state") or "pending")),
            attempt=int(value.get("attempt") or 0),
            consecutive_upstream_failures=int(
                value.get("consecutive_upstream_failures") or 0
            ),
            next_run_at=float(value.get("next_run_at") or 0.0),
            created_at_utc=_optional_str(value.get("created_at_utc")),
            updated_at_utc=_optional_str(value.get("updated_at_utc")),
            last_disposition=_optional_str(value.get("last_disposition")),
            last_status_code=(
                None
                if value.get("last_status_code") is None
                else int(value["last_status_code"])
            ),
            last_fingerprint=fp,
            last_artifact_id=_optional_str(value.get("last_artifact_id")),
            known_artifact_ids=tuple(value.get("known_artifact_ids") or ()),
            emitted_alert_ids=tuple(value.get("emitted_alert_ids") or ()),
            credential_ref_id=_optional_str(value.get("credential_ref_id")),
            labels=value.get("labels") or {},
            parent_job_id=_optional_str(value.get("parent_job_id")),
            metadata_ready=bool(value.get("metadata_ready", False)),
        )


@dataclass(frozen=True, slots=True)
class SchedulerAlert:
    """Redacted, dedupe-keyed alert (safe to log / persist)."""

    alert_id: str
    kind: AlertKind
    created_at_utc: str
    service: str | None = None
    job_id: str | None = None
    application_number: str | None = None
    matter_id: str | None = None
    action: ActionKind | None = None
    message: str = ""
    status_code: int | None = None
    labels: Mapping[str, str] = field(default_factory=dict)
    # Stable dedupe key distinct from alert_id (alert_id is unique per emission attempt).
    dedupe_key: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "alert_id", _safe_id(self.alert_id, field_name="alert_id"))
        if isinstance(self.kind, str):
            object.__setattr__(self, "kind", AlertKind(self.kind))
        if self.action is not None and isinstance(self.action, str):
            object.__setattr__(self, "action", ActionKind(self.action))
        msg = sanitize_secret_text(str(self.message or ""))
        if len(msg) > _ALERT_BODY_MAX:
            msg = msg[:_ALERT_BODY_MAX] + "…"
        object.__setattr__(self, "message", msg)
        object.__setattr__(
            self,
            "labels",
            MappingProxyType(
                {
                    str(k): sanitize_secret_text(str(v))
                    for k, v in dict(self.labels or {}).items()
                }
            ),
        )
        if not self.dedupe_key:
            material = {
                "action": None if self.action is None else self.action.value,
                "application_number": self.application_number or "",
                "job_id": self.job_id or "",
                "kind": self.kind.value,
                "matter_id": self.matter_id or "",
                "service": self.service or "",
                "status_code": self.status_code,
            }
            object.__setattr__(self, "dedupe_key", sha256_hex(canonical_json(material)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": None if self.action is None else self.action.value,
            "alert_id": self.alert_id,
            "application_number": self.application_number,
            "created_at_utc": self.created_at_utc,
            "dedupe_key": self.dedupe_key,
            "job_id": self.job_id,
            "kind": self.kind.value,
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "message": self.message,
            "service": self.service,
            "status_code": self.status_code,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SchedulerAlert":
        action_raw = value.get("action")
        return cls(
            alert_id=str(value.get("alert_id") or ""),
            kind=AlertKind(str(value.get("kind") or "heartbeat")),
            created_at_utc=str(value.get("created_at_utc") or ""),
            service=_optional_str(value.get("service")),
            job_id=_optional_str(value.get("job_id")),
            application_number=_optional_str(value.get("application_number")),
            matter_id=_optional_str(value.get("matter_id")),
            action=None if action_raw is None else ActionKind(str(action_raw)),
            message=str(value.get("message") or ""),
            status_code=(
                None if value.get("status_code") is None else int(value["status_code"])
            ),
            labels=value.get("labels") or {},
            dedupe_key=str(value.get("dedupe_key") or ""),
        )


@dataclass(frozen=True, slots=True)
class DeadLetterRecord:
    """Reviewable permanent failure (parse/security); never auto-retried."""

    dead_letter_id: str
    job_id: str
    reason: DeadLetterReason
    created_at_utc: str
    service: str
    content_kind: str
    application_number: str
    matter_id: str | None = None
    status_code: int | None = None
    error_code: str | None = None
    message: str = ""
    job_snapshot: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "dead_letter_id", _safe_id(self.dead_letter_id, field_name="dead_letter_id")
        )
        if isinstance(self.reason, str):
            object.__setattr__(self, "reason", DeadLetterReason(self.reason))
        object.__setattr__(self, "message", sanitize_secret_text(str(self.message or "")))
        object.__setattr__(
            self,
            "job_snapshot",
            MappingProxyType(_redact_mapping(dict(self.job_snapshot or {}))),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_number": self.application_number,
            "content_kind": self.content_kind,
            "created_at_utc": self.created_at_utc,
            "dead_letter_id": self.dead_letter_id,
            "error_code": self.error_code,
            "job_id": self.job_id,
            "job_snapshot": dict(self.job_snapshot),
            "matter_id": self.matter_id,
            "message": self.message,
            "reason": self.reason.value,
            "service": self.service,
            "status_code": self.status_code,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DeadLetterRecord":
        return cls(
            dead_letter_id=str(value.get("dead_letter_id") or ""),
            job_id=str(value.get("job_id") or ""),
            reason=DeadLetterReason(str(value.get("reason") or "operator")),
            created_at_utc=str(value.get("created_at_utc") or ""),
            service=str(value.get("service") or ""),
            content_kind=str(value.get("content_kind") or ""),
            application_number=str(value.get("application_number") or ""),
            matter_id=_optional_str(value.get("matter_id")),
            status_code=(
                None if value.get("status_code") is None else int(value["status_code"])
            ),
            error_code=_optional_str(value.get("error_code")),
            message=str(value.get("message") or ""),
            job_snapshot=value.get("job_snapshot") or {},
        )


@dataclass(frozen=True, slots=True)
class OperatorAction:
    """Actionable item for operators (credential health, dead-letter review, …)."""

    action_id: str
    kind: ActionKind
    created_at_utc: str
    job_id: str | None = None
    service: str | None = None
    application_number: str | None = None
    matter_id: str | None = None
    status_code: int | None = None
    message: str = ""
    labels: Mapping[str, str] = field(default_factory=dict)
    resolved: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "action_id", _safe_id(self.action_id, field_name="action_id")
        )
        if isinstance(self.kind, str):
            object.__setattr__(self, "kind", ActionKind(self.kind))
        object.__setattr__(self, "message", sanitize_secret_text(str(self.message or "")))
        object.__setattr__(
            self,
            "labels",
            MappingProxyType(
                {
                    str(k): sanitize_secret_text(str(v))
                    for k, v in dict(self.labels or {}).items()
                }
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "application_number": self.application_number,
            "created_at_utc": self.created_at_utc,
            "job_id": self.job_id,
            "kind": self.kind.value,
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "message": self.message,
            "resolved": self.resolved,
            "service": self.service,
            "status_code": self.status_code,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperatorAction":
        return cls(
            action_id=str(value.get("action_id") or ""),
            kind=ActionKind(str(value.get("kind") or "resume_poll")),
            created_at_utc=str(value.get("created_at_utc") or ""),
            job_id=_optional_str(value.get("job_id")),
            service=_optional_str(value.get("service")),
            application_number=_optional_str(value.get("application_number")),
            matter_id=_optional_str(value.get("matter_id")),
            status_code=(
                None if value.get("status_code") is None else int(value["status_code"])
            ),
            message=str(value.get("message") or ""),
            labels=value.get("labels") or {},
            resolved=bool(value.get("resolved", False)),
        )


@dataclass
class SchedulerProgress:
    """Content-free liveness / progress counters."""

    schema_version: str = SCHEDULER_SCHEMA_VERSION
    jobs_enqueued: int = 0
    jobs_completed: int = 0
    jobs_waiting: int = 0
    jobs_running: int = 0
    jobs_dead_lettered: int = 0
    alerts_emitted: int = 0
    changes_detected: int = 0
    circuits_open: int = 0
    workers_in_use: int = 0
    workers_available: int = 0
    last_heartbeat_utc: str | None = None
    last_tick_utc: str | None = None
    ticks: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "alerts_emitted": self.alerts_emitted,
            "changes_detected": self.changes_detected,
            "circuits_open": self.circuits_open,
            "jobs_completed": self.jobs_completed,
            "jobs_dead_lettered": self.jobs_dead_lettered,
            "jobs_enqueued": self.jobs_enqueued,
            "jobs_running": self.jobs_running,
            "jobs_waiting": self.jobs_waiting,
            "last_heartbeat_utc": self.last_heartbeat_utc,
            "last_tick_utc": self.last_tick_utc,
            "schema_version": self.schema_version,
            "ticks": self.ticks,
            "workers_available": self.workers_available,
            "workers_in_use": self.workers_in_use,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "SchedulerProgress":
        if not value or not isinstance(value, Mapping):
            return cls()
        return cls(
            schema_version=str(
                value.get("schema_version") or SCHEDULER_SCHEMA_VERSION
            ),
            jobs_enqueued=int(value.get("jobs_enqueued") or 0),
            jobs_completed=int(value.get("jobs_completed") or 0),
            jobs_waiting=int(value.get("jobs_waiting") or 0),
            jobs_running=int(value.get("jobs_running") or 0),
            jobs_dead_lettered=int(value.get("jobs_dead_lettered") or 0),
            alerts_emitted=int(value.get("alerts_emitted") or 0),
            changes_detected=int(value.get("changes_detected") or 0),
            circuits_open=int(value.get("circuits_open") or 0),
            workers_in_use=int(value.get("workers_in_use") or 0),
            workers_available=int(value.get("workers_available") or 0),
            last_heartbeat_utc=_optional_str(value.get("last_heartbeat_utc")),
            last_tick_utc=_optional_str(value.get("last_tick_utc")),
            ticks=int(value.get("ticks") or 0),
        )


@dataclass
class SchedulerCheckpoint:
    """Durable scheduler state for crash-safe resume."""

    schema_version: str
    jobs: dict[str, PollJob] = field(default_factory=dict)
    alerts: list[SchedulerAlert] = field(default_factory=list)
    # dedupe_key → alert_id for restart-safe uniqueness
    alert_dedupe_index: dict[str, str] = field(default_factory=dict)
    dead_letters: list[DeadLetterRecord] = field(default_factory=list)
    actions: list[OperatorAction] = field(default_factory=list)
    # service → circuit snapshot
    circuit_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    # global set of artifact ids already admitted (prevents duplicate artifacts)
    known_artifact_ids: set[str] = field(default_factory=set)
    # fingerprint by job resource key
    fingerprints: dict[str, str] = field(default_factory=dict)
    progress: SchedulerProgress = field(default_factory=SchedulerProgress)
    # services that completed metadata successfully (gate binary)
    metadata_ready_keys: set[str] = field(default_factory=set)

    def resource_key(
        self,
        service: str,
        content_kind: str,
        application_number: str,
        resource_id: str | None = None,
    ) -> str:
        base = f"{service}|{content_kind}|{application_number}"
        if resource_id:
            return f"{base}|{resource_id}"
        return base

    def to_dict(self) -> dict[str, Any]:
        return {
            "actions": [a.to_dict() for a in self.actions],
            "alert_dedupe_index": dict(sorted(self.alert_dedupe_index.items())),
            "alerts": [a.to_dict() for a in self.alerts],
            "circuit_states": {
                k: dict(v) for k, v in sorted(self.circuit_states.items())
            },
            "dead_letters": [d.to_dict() for d in self.dead_letters],
            "fingerprints": dict(sorted(self.fingerprints.items())),
            "jobs": {jid: job.to_dict() for jid, job in sorted(self.jobs.items())},
            "known_artifact_ids": sorted(self.known_artifact_ids),
            "metadata_ready_keys": sorted(self.metadata_ready_keys),
            "progress": self.progress.to_dict(),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SchedulerCheckpoint":
        if not isinstance(value, Mapping):
            raise SchedulerError(
                "checkpoint payload must be a mapping", code="invalid_checkpoint"
            )
        jobs: dict[str, PollJob] = {}
        raw_jobs = value.get("jobs") or {}
        if isinstance(raw_jobs, Mapping):
            for jid, raw in raw_jobs.items():
                if isinstance(raw, Mapping):
                    job = PollJob.from_dict(raw)
                    jobs[str(jid)] = job
        alerts = [
            SchedulerAlert.from_dict(a)
            for a in (value.get("alerts") or [])
            if isinstance(a, Mapping)
        ]
        dead_letters = [
            DeadLetterRecord.from_dict(d)
            for d in (value.get("dead_letters") or [])
            if isinstance(d, Mapping)
        ]
        actions = [
            OperatorAction.from_dict(a)
            for a in (value.get("actions") or [])
            if isinstance(a, Mapping)
        ]
        alert_dedupe = {
            str(k): str(v)
            for k, v in dict(value.get("alert_dedupe_index") or {}).items()
        }
        circuits = {
            str(k): dict(v)
            for k, v in dict(value.get("circuit_states") or {}).items()
            if isinstance(v, Mapping)
        }
        known = set(str(x) for x in (value.get("known_artifact_ids") or []))
        fps = {str(k): str(v) for k, v in dict(value.get("fingerprints") or {}).items()}
        meta_ready = set(str(x) for x in (value.get("metadata_ready_keys") or []))
        return cls(
            schema_version=str(
                value.get("schema_version") or SCHEDULER_SCHEMA_VERSION
            ),
            jobs=jobs,
            alerts=alerts,
            alert_dedupe_index=alert_dedupe,
            dead_letters=dead_letters,
            actions=actions,
            circuit_states=circuits,
            known_artifact_ids=known,
            fingerprints=fps,
            progress=SchedulerProgress.from_dict(value.get("progress")),
            metadata_ready_keys=meta_ready,
        )


# ---------------------------------------------------------------------------
# Checkpoint store
# ---------------------------------------------------------------------------


class SchedulerCheckpointStore:
    """Filesystem or in-memory atomic checkpoint persistence."""

    def __init__(self, *, root: Path | None = None, name: str = "scheduler") -> None:
        self._root = Path(root) if root is not None else None
        self._name = _ID_SAFE_RE.sub("_", str(name or "scheduler"))[:64] or "scheduler"
        if self._root is not None:
            self._root.mkdir(parents=True, exist_ok=True)
        self._memory: SchedulerCheckpoint | None = None

    @property
    def path(self) -> Path | None:
        if self._root is None:
            return None
        return self._root / f"{self._name}-checkpoint.json"

    def load(self) -> SchedulerCheckpoint:
        if self._root is not None:
            path = self.path
            assert path is not None
            if path.is_file():
                with path.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                if isinstance(payload, Mapping):
                    ckpt = SchedulerCheckpoint.from_dict(payload)
                    self._memory = ckpt
                    return ckpt
        if self._memory is not None:
            return self._memory
        return SchedulerCheckpoint(schema_version=SCHEDULER_SCHEMA_VERSION)

    def save(self, checkpoint: SchedulerCheckpoint) -> None:
        self._memory = checkpoint
        if self._root is None:
            return
        path = self.path
        assert path is not None
        tmp = path.with_suffix(".tmp")
        payload = checkpoint.to_dict()
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Poller protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Poller(Protocol):
    """Injected poll execution. Must not return secret material."""

    def poll(self, job: PollJob) -> PollResult:
        """Execute one poll attempt for *job*."""
        ...


# ---------------------------------------------------------------------------
# Bounded multi-queue
# ---------------------------------------------------------------------------


class BoundedServiceQueues:
    """Per-(service, content_kind) FIFO queues with depth bounds.

    Metadata queues are preferred over binary when selecting work so that
    metadata-before-binary ordering is honored under contention.
    """

    def __init__(self, max_depth: int) -> None:
        self._max_depth = _positive_int(max_depth, "max_depth")
        self._queues: dict[tuple[str, str], deque[str]] = {}

    def depth(self, service: str, content_kind: ContentKind | str) -> int:
        kind = (
            content_kind.value
            if isinstance(content_kind, ContentKind)
            else str(content_kind)
        )
        return len(self._queues.get((service, kind), ()))

    def total_depth(self) -> int:
        return sum(len(q) for q in self._queues.values())

    def enqueue(self, job: PollJob) -> None:
        key = job.queue_key()
        q = self._queues.setdefault(key, deque())
        if job.job_id in q:
            return  # already queued
        if len(q) >= self._max_depth:
            raise QueueFullError(job.service, job.content_kind.value)
        q.append(job.job_id)

    def requeue_front(self, job: PollJob) -> None:
        """Put job back at the front (e.g. circuit open, not ready)."""
        key = job.queue_key()
        q = self._queues.setdefault(key, deque())
        if job.job_id in q:
            return
        if len(q) >= self._max_depth:
            # Drop to end of waiting path handled by caller state machine.
            q.append(job.job_id)
            return
        q.appendleft(job.job_id)

    def pop_ready(
        self,
        jobs: Mapping[str, PollJob],
        *,
        now: float,
        metadata_before_binary: bool,
        is_service_available: Callable[[str], bool],
        is_binary_allowed: Callable[[PollJob], bool],
    ) -> PollJob | None:
        """Select next ready job, preferring metadata queues."""
        keys = list(self._queues.keys())
        if metadata_before_binary:
            keys.sort(key=lambda k: (0 if k[1] == ContentKind.METADATA.value else 1, k[0]))
        else:
            keys.sort()
        for key in keys:
            service, _kind = key
            if not is_service_available(service):
                continue
            q = self._queues.get(key)
            if not q:
                continue
            # Scan for a ready job without holding capacity for waiters.
            skipped: list[str] = []
            chosen: PollJob | None = None
            while q:
                jid = q.popleft()
                job = jobs.get(jid)
                if job is None:
                    continue
                if job.state in (JobState.SUCCEEDED, JobState.DEAD_LETTERED, JobState.CANCELLED):
                    continue
                if job.state is JobState.WAITING and job.next_run_at > now:
                    skipped.append(jid)
                    continue
                if job.content_kind is ContentKind.BINARY and not is_binary_allowed(job):
                    skipped.append(jid)
                    continue
                chosen = job
                break
            for jid in skipped:
                q.append(jid)
            if chosen is not None:
                return chosen
        return None


# ---------------------------------------------------------------------------
# Worker capacity
# ---------------------------------------------------------------------------


class WorkerPool:
    """Bounded worker slots. Waiting jobs must release capacity."""

    def __init__(self, max_workers: int) -> None:
        self._max = _positive_int(max_workers, "max_workers")
        self._in_use = 0
        self._held_jobs: set[str] = set()

    @property
    def max_workers(self) -> int:
        return self._max

    @property
    def in_use(self) -> int:
        return self._in_use

    @property
    def available(self) -> int:
        return max(0, self._max - self._in_use)

    def acquire(self, job_id: str) -> bool:
        if job_id in self._held_jobs:
            return True
        if self._in_use >= self._max:
            return False
        self._in_use += 1
        self._held_jobs.add(job_id)
        return True

    def release(self, job_id: str) -> None:
        if job_id not in self._held_jobs:
            return
        self._held_jobs.discard(job_id)
        self._in_use = max(0, self._in_use - 1)

    def is_held(self, job_id: str) -> bool:
        return job_id in self._held_jobs


# ---------------------------------------------------------------------------
# Main scheduler
# ---------------------------------------------------------------------------


class USPTOApplicationScheduler:
    """Checkpointed polling scheduler with change detection and redacted alerts.

    Workers only hold capacity while actively polling (``JobState.RUNNING``).
    Any delayed path (429 / backoff / circuit) moves the job to ``WAITING`` and
    **releases** the worker so other work can proceed.
    """

    schema_version: str = SCHEDULER_SCHEMA_VERSION
    interface: str = SCHEDULER_INTERFACE

    def __init__(
        self,
        *,
        poller: Poller | Callable[[PollJob], PollResult],
        config: SchedulerConfig | None = None,
        checkpoint_store: SchedulerCheckpointStore | None = None,
        clock: Clock = time.monotonic,
        wall_clock: WallClock | None = None,
        id_factory: IdFactory | None = None,
    ) -> None:
        if poller is None:
            raise SchedulerError("poller is required", code="missing_poller")
        self._poller = poller
        self._config = config or SchedulerConfig()
        self._store = checkpoint_store or SchedulerCheckpointStore()
        self._clock = clock
        self._wall = wall_clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or _default_id_factory
        self._queues = BoundedServiceQueues(self._config.max_queue_depth)
        self._workers = WorkerPool(self._config.max_workers)
        self._circuits: dict[str, CircuitBreaker] = {}
        self._checkpoint = self._store.load()
        self._restore_runtime_from_checkpoint()
        self._last_heartbeat_mono = float(self._clock())
        self._closed = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def config(self) -> SchedulerConfig:
        return self._config

    @property
    def checkpoint(self) -> SchedulerCheckpoint:
        return self._checkpoint

    @property
    def workers(self) -> WorkerPool:
        return self._workers

    @property
    def alerts(self) -> Sequence[SchedulerAlert]:
        return tuple(self._checkpoint.alerts)

    @property
    def dead_letters(self) -> Sequence[DeadLetterRecord]:
        return tuple(self._checkpoint.dead_letters)

    @property
    def actions(self) -> Sequence[OperatorAction]:
        return tuple(self._checkpoint.actions)

    @property
    def jobs(self) -> Mapping[str, PollJob]:
        return MappingProxyType(self._checkpoint.jobs)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _restore_runtime_from_checkpoint(self) -> None:
        """Rebuild queues and circuit breakers from durable state."""
        # Circuits
        for service, snap in self._checkpoint.circuit_states.items():
            breaker = self._get_circuit(service)
            state = str(snap.get("state") or CircuitState.CLOSED.value)
            failures = int(snap.get("consecutive_failures") or 0)
            # Replay failures to approximate open state without private clock glue.
            if state == CircuitState.OPEN.value:
                for _ in range(max(failures, self._config.circuit_failure_threshold)):
                    breaker.record_failure()
            elif state == CircuitState.HALF_OPEN.value:
                for _ in range(self._config.circuit_failure_threshold):
                    breaker.record_failure()
                # Force half-open by advancing internal clock path: open then wait.
                # CircuitBreaker uses its own clock; policy recovery is operator-tuned.
            elif failures > 0:
                for _ in range(failures):
                    breaker.record_failure()
                    if breaker.state is CircuitState.OPEN:
                        break
        # Re-queue incomplete jobs (WAITING/PENDING). RUNNING → PENDING (crash mid-run).
        for job in self._checkpoint.jobs.values():
            if job.state is JobState.RUNNING:
                job.state = JobState.PENDING
                job.updated_at_utc = self._now_utc()
            if job.state in (JobState.PENDING, JobState.WAITING):
                try:
                    self._queues.enqueue(job)
                except QueueFullError:
                    # Preserve job in checkpoint; it remains WAITING for later drain.
                    job.state = JobState.WAITING
        self._refresh_progress()

    def _get_circuit(self, service: str) -> CircuitBreaker:
        if service not in self._circuits:
            policy = CircuitBreakerPolicy(
                failure_threshold=self._config.circuit_failure_threshold,
                recovery_timeout_seconds=self._config.circuit_recovery_seconds,
            )
            self._circuits[service] = CircuitBreaker(policy, clock=self._clock)
        return self._circuits[service]

    def _now_utc(self) -> str:
        return format_utc(self._wall())

    def _now_mono(self) -> float:
        return float(self._clock())

    def _persist(self) -> None:
        self._snapshot_circuits()
        self._refresh_progress()
        self._store.save(self._checkpoint)

    def _snapshot_circuits(self) -> None:
        out: dict[str, dict[str, Any]] = {}
        open_count = 0
        for service, breaker in self._circuits.items():
            state = breaker.state
            if state is CircuitState.OPEN:
                open_count += 1
            out[service] = {
                "consecutive_failures": getattr(
                    breaker, "_consecutive_failures", 0
                ),
                "state": state.value,
            }
        self._checkpoint.circuit_states = out
        self._checkpoint.progress.circuits_open = open_count

    def _refresh_progress(self) -> None:
        p = self._checkpoint.progress
        p.schema_version = SCHEDULER_SCHEMA_VERSION
        waiting = running = completed = dead = 0
        for job in self._checkpoint.jobs.values():
            if job.state is JobState.WAITING:
                waiting += 1
            elif job.state is JobState.RUNNING:
                running += 1
            elif job.state is JobState.SUCCEEDED:
                completed += 1
            elif job.state is JobState.DEAD_LETTERED:
                dead += 1
        p.jobs_waiting = waiting
        p.jobs_running = running
        p.jobs_completed = completed
        p.jobs_dead_lettered = dead
        p.jobs_enqueued = len(self._checkpoint.jobs)
        p.alerts_emitted = len(self._checkpoint.alerts)
        p.workers_in_use = self._workers.in_use
        p.workers_available = self._workers.available

    def progress(self) -> SchedulerProgress:
        self._refresh_progress()
        return self._checkpoint.progress

    def health(self) -> dict[str, Any]:
        """Content-free health snapshot for operators."""
        self._snapshot_circuits()
        self._refresh_progress()
        return {
            "circuit_states": {
                k: dict(v) for k, v in sorted(self._checkpoint.circuit_states.items())
            },
            "interface": self.interface,
            "progress": self._checkpoint.progress.to_dict(),
            "queue_depth": self._queues.total_depth(),
            "schema_version": self.schema_version,
            "workers_available": self._workers.available,
            "workers_in_use": self._workers.in_use,
        }

    # ------------------------------------------------------------------
    # Enqueue
    # ------------------------------------------------------------------

    def enqueue(
        self,
        *,
        application_number: str,
        service: str | ServiceName = ServiceName.PATENT_FILE_WRAPPER,
        content_kind: ContentKind | str = ContentKind.METADATA,
        matter_id: str | None = None,
        resource_id: str | None = None,
        credential_ref_id: str | None = None,
        labels: Mapping[str, str] | None = None,
        job_id: str | None = None,
        parent_job_id: str | None = None,
        next_run_at: float | None = None,
    ) -> PollJob:
        if self._closed:
            raise SchedulerError("scheduler is closed", code="scheduler_closed")
        service_s = (
            service.value if isinstance(service, ServiceName) else str(service)
        )
        kind = (
            content_kind
            if isinstance(content_kind, ContentKind)
            else ContentKind(str(content_kind))
        )
        jid = job_id or self._id_factory()
        if jid in self._checkpoint.jobs:
            existing = self._checkpoint.jobs[jid]
            if existing.state in (JobState.PENDING, JobState.WAITING):
                try:
                    self._queues.enqueue(existing)
                except QueueFullError:
                    pass
            return existing
        now_utc = self._now_utc()
        job = PollJob(
            job_id=jid,
            service=service_s,
            content_kind=kind,
            application_number=application_number,
            matter_id=matter_id,
            resource_id=resource_id,
            state=JobState.PENDING,
            next_run_at=float(self._now_mono() if next_run_at is None else next_run_at),
            created_at_utc=now_utc,
            updated_at_utc=now_utc,
            credential_ref_id=credential_ref_id,
            labels=labels or {},
            parent_job_id=parent_job_id,
            known_artifact_ids=tuple(
                sorted(
                    a
                    for a in self._checkpoint.known_artifact_ids
                    if True  # full set filtered at admission
                )
            )[:0],  # start empty; global set consulted at admission
        )
        # Carry prior fingerprint if we have one for this resource.
        rkey = self._checkpoint.resource_key(
            service_s, kind.value, application_number, resource_id
        )
        prior_fp = self._checkpoint.fingerprints.get(rkey)
        if prior_fp:
            job.last_fingerprint = ChangeFingerprint(fingerprint=prior_fp)
        if rkey in self._checkpoint.metadata_ready_keys and kind is ContentKind.METADATA:
            job.metadata_ready = True
        self._checkpoint.jobs[job.job_id] = job
        self._queues.enqueue(job)
        self._persist()
        return job

    def enqueue_matter_poll(
        self,
        *,
        application_number: str,
        matter_id: str | None = None,
        credential_ref_id: str | None = None,
        include_binary: bool = False,
        labels: Mapping[str, str] | None = None,
    ) -> list[PollJob]:
        """Enqueue metadata poll; optionally a binary job gated on metadata."""
        jobs = [
            self.enqueue(
                application_number=application_number,
                service=ServiceName.APPLICATION_STATUS,
                content_kind=ContentKind.METADATA,
                matter_id=matter_id,
                credential_ref_id=credential_ref_id,
                labels=labels,
            )
        ]
        if include_binary:
            jobs.append(
                self.enqueue(
                    application_number=application_number,
                    service=ServiceName.DOCUMENT_BYTES,
                    content_kind=ContentKind.BINARY,
                    matter_id=matter_id,
                    credential_ref_id=credential_ref_id,
                    labels=labels,
                    parent_job_id=jobs[0].job_id,
                )
            )
        return jobs

    # ------------------------------------------------------------------
    # Alert / action / dead-letter emission (deduped)
    # ------------------------------------------------------------------

    def _emit_alert(
        self,
        *,
        kind: AlertKind,
        job: PollJob | None = None,
        action: ActionKind | None = None,
        message: str = "",
        status_code: int | None = None,
        service: str | None = None,
        labels: Mapping[str, str] | None = None,
        force: bool = False,
    ) -> SchedulerAlert | None:
        """Emit alert if dedupe_key is new. Returns None when suppressed as duplicate."""
        created = self._now_utc()
        # Provisional alert to compute dedupe_key
        provisional = SchedulerAlert(
            alert_id=self._id_factory(),
            kind=kind,
            created_at_utc=created,
            service=service or (None if job is None else job.service),
            job_id=None if job is None else job.job_id,
            application_number=None if job is None else job.application_number,
            matter_id=None if job is None else job.matter_id,
            action=action,
            message=message,
            status_code=status_code,
            labels=labels or {},
        )
        if not force and provisional.dedupe_key in self._checkpoint.alert_dedupe_index:
            return None
        # Heartbeats always unique by forcing timestamp into labels when force=True
        self._checkpoint.alert_dedupe_index[provisional.dedupe_key] = provisional.alert_id
        self._checkpoint.alerts.append(provisional)
        if len(self._checkpoint.alerts) > self._config.max_alerts_retained:
            # Drop oldest but keep dedupe index (prevents re-emission of old keys).
            overflow = len(self._checkpoint.alerts) - self._config.max_alerts_retained
            del self._checkpoint.alerts[:overflow]
        if job is not None:
            job.emitted_alert_ids = tuple(
                list(job.emitted_alert_ids) + [provisional.alert_id]
            )
        return provisional

    def _emit_action(
        self,
        *,
        kind: ActionKind,
        job: PollJob | None = None,
        message: str = "",
        status_code: int | None = None,
        service: str | None = None,
        labels: Mapping[str, str] | None = None,
    ) -> OperatorAction:
        # Dedupe open actions of same kind+job
        for existing in self._checkpoint.actions:
            if (
                not existing.resolved
                and existing.kind is kind
                and existing.job_id == (None if job is None else job.job_id)
                and existing.service == (service or (None if job is None else job.service))
            ):
                return existing
        action = OperatorAction(
            action_id=self._id_factory(),
            kind=kind,
            created_at_utc=self._now_utc(),
            job_id=None if job is None else job.job_id,
            service=service or (None if job is None else job.service),
            application_number=None if job is None else job.application_number,
            matter_id=None if job is None else job.matter_id,
            status_code=status_code,
            message=message,
            labels=labels or {},
        )
        self._checkpoint.actions.append(action)
        return action

    def _dead_letter(
        self,
        job: PollJob,
        *,
        reason: DeadLetterReason,
        message: str = "",
        status_code: int | None = None,
        error_code: str | None = None,
    ) -> DeadLetterRecord:
        job.state = JobState.DEAD_LETTERED
        job.updated_at_utc = self._now_utc()
        job.last_disposition = reason.value
        if status_code is not None:
            job.last_status_code = status_code
        self._workers.release(job.job_id)
        record = DeadLetterRecord(
            dead_letter_id=self._id_factory(),
            job_id=job.job_id,
            reason=reason,
            created_at_utc=self._now_utc(),
            service=job.service,
            content_kind=job.content_kind.value,
            application_number=job.application_number,
            matter_id=job.matter_id,
            status_code=status_code,
            error_code=error_code,
            message=message,
            job_snapshot=job.to_dict(),
        )
        self._checkpoint.dead_letters.append(record)
        if len(self._checkpoint.dead_letters) > self._config.max_dead_letters:
            overflow = (
                len(self._checkpoint.dead_letters) - self._config.max_dead_letters
            )
            del self._checkpoint.dead_letters[:overflow]
        self._emit_alert(
            kind=AlertKind.DEAD_LETTER,
            job=job,
            action=ActionKind.REVIEW_DEAD_LETTER,
            message=message or f"job dead-lettered: {reason.value}",
            status_code=status_code,
        )
        self._emit_action(
            kind=ActionKind.REVIEW_DEAD_LETTER,
            job=job,
            message=message or f"review dead-letter {record.dead_letter_id}",
            status_code=status_code,
        )
        return record

    # ------------------------------------------------------------------
    # Delay / wait (capacity release)
    # ------------------------------------------------------------------

    def _backoff_delay(self, attempt: int, *, retry_after: float | None = None) -> float:
        if retry_after is not None:
            return min(
                float(retry_after),
                self._config.max_retry_after_seconds,
            )
        exp = self._config.base_backoff_seconds * (2 ** max(0, attempt - 1))
        return min(self._config.max_backoff_seconds, max(0.0, exp))

    def _enter_waiting(
        self,
        job: PollJob,
        *,
        delay_seconds: float,
        disposition: PollDisposition,
        status_code: int | None = None,
        message: str | None = None,
        emit_waiting_alert: bool = False,
    ) -> None:
        """Mark job WAITING and **release** worker capacity."""
        job.state = JobState.WAITING
        job.next_run_at = self._now_mono() + max(0.0, float(delay_seconds))
        job.last_disposition = disposition.value
        job.updated_at_utc = self._now_utc()
        if status_code is not None:
            job.last_status_code = status_code
        # Critical acceptance: release capacity while waiting.
        self._workers.release(job.job_id)
        try:
            self._queues.enqueue(job)
        except QueueFullError:
            # Job remains in checkpoint as WAITING; next restart/load can requeue.
            pass
        if emit_waiting_alert:
            self._emit_alert(
                kind=AlertKind.JOB_WAITING,
                job=job,
                message=message or f"waiting {delay_seconds:.3f}s ({disposition.value})",
                status_code=status_code,
                force=True,
            )

    # ------------------------------------------------------------------
    # Poll execution helpers
    # ------------------------------------------------------------------

    def _invoke_poller(self, job: PollJob) -> PollResult:
        poller = self._poller
        if callable(poller) and not isinstance(poller, Poller):
            result = poller(job)
        else:
            result = poller.poll(job)  # type: ignore[union-attr]
        if not isinstance(result, PollResult):
            raise SchedulerError(
                "poller must return PollResult",
                code="invalid_poll_result",
            )
        return result

    def _service_available(self, service: str) -> bool:
        breaker = self._get_circuit(service)
        try:
            # Peek without mutating: CircuitBreaker.before_request raises if open.
            if breaker.state is CircuitState.OPEN:
                return False
            return True
        except Exception:
            return False

    def _binary_allowed(self, job: PollJob) -> bool:
        if not self._config.metadata_before_binary:
            return True
        if job.content_kind is not ContentKind.BINARY:
            return True
        # Require metadata ready for this application (any metadata service).
        app = job.application_number
        for key in self._checkpoint.metadata_ready_keys:
            if f"|{ContentKind.METADATA.value}|{app}" in f"|{key}" or key.endswith(
                f"|{app}"
            ):
                return True
            # resource_key format: service|content_kind|application_number[|resource]
            parts = key.split("|")
            if len(parts) >= 3 and parts[1] == ContentKind.METADATA.value and parts[2] == app:
                return True
        # Parent metadata job succeeded?
        if job.parent_job_id:
            parent = self._checkpoint.jobs.get(job.parent_job_id)
            if parent is not None and (
                parent.state is JobState.SUCCEEDED or parent.metadata_ready
            ):
                return True
        return False

    def _mark_metadata_ready(self, job: PollJob) -> None:
        if job.content_kind is not ContentKind.METADATA:
            return
        rkey = self._checkpoint.resource_key(
            job.service,
            job.content_kind.value,
            job.application_number,
            job.resource_id,
        )
        self._checkpoint.metadata_ready_keys.add(rkey)
        job.metadata_ready = True

    def _record_fingerprint_and_change(
        self, job: PollJob, result: PollResult
    ) -> PollDisposition:
        """Compare fingerprints; return CHANGED / UNCHANGED / SUCCESS."""
        if result.fingerprint is None:
            return result.disposition
        rkey = self._checkpoint.resource_key(
            job.service,
            job.content_kind.value,
            job.application_number,
            job.resource_id,
        )
        prior = self._checkpoint.fingerprints.get(rkey)
        new_fp = result.fingerprint.fingerprint
        job.last_fingerprint = result.fingerprint
        if prior is None:
            self._checkpoint.fingerprints[rkey] = new_fp
            if result.disposition is PollDisposition.SUCCESS:
                return PollDisposition.CHANGED
            return result.disposition
        if prior == new_fp:
            return PollDisposition.UNCHANGED
        self._checkpoint.fingerprints[rkey] = new_fp
        return PollDisposition.CHANGED

    def _admit_artifact(self, job: PollJob, artifact_id: str | None) -> bool:
        """Record artifact id if new. Returns False if duplicate (already known)."""
        if not artifact_id:
            return True
        aid = str(artifact_id).strip()
        if not aid:
            return True
        if aid in self._checkpoint.known_artifact_ids:
            return False
        self._checkpoint.known_artifact_ids.add(aid)
        job.last_artifact_id = aid
        if aid not in job.known_artifact_ids:
            job.known_artifact_ids = tuple(list(job.known_artifact_ids) + [aid])
        return True

    def _handle_success(self, job: PollJob, result: PollResult) -> None:
        breaker = self._get_circuit(job.service)
        breaker.record_success()
        disposition = self._record_fingerprint_and_change(job, result)
        # Artifact dedupe
        if result.artifact_id:
            is_new = self._admit_artifact(job, result.artifact_id)
            if not is_new:
                # Duplicate artifact on restart — treat as unchanged success.
                disposition = PollDisposition.UNCHANGED
        job.last_disposition = disposition.value
        job.last_status_code = result.status_code
        job.consecutive_upstream_failures = 0
        job.attempt += 1
        job.updated_at_utc = self._now_utc()
        self._mark_metadata_ready(job)

        if disposition is PollDisposition.CHANGED:
            self._checkpoint.progress.changes_detected += 1
            self._emit_alert(
                kind=AlertKind.CHANGE_DETECTED,
                job=job,
                message="change detected",
                status_code=result.status_code,
                labels={
                    "fingerprint": (
                        result.fingerprint.fingerprint if result.fingerprint else ""
                    )[:64],
                },
            )

        # Optionally enqueue binary follow-up from metadata poll.
        if (
            result.enqueue_binary
            and job.content_kind is ContentKind.METADATA
            and self._config.metadata_before_binary
        ):
            self.enqueue(
                application_number=job.application_number,
                service=ServiceName.DOCUMENT_BYTES,
                content_kind=ContentKind.BINARY,
                matter_id=job.matter_id,
                resource_id=result.binary_resource_id,
                credential_ref_id=job.credential_ref_id,
                labels=job.labels,
                parent_job_id=job.job_id,
            )

        job.state = JobState.SUCCEEDED
        self._workers.release(job.job_id)
        self._emit_alert(
            kind=AlertKind.JOB_SUCCEEDED,
            job=job,
            message=f"job succeeded ({disposition.value})",
            status_code=result.status_code,
            force=True,
        )

    def _handle_auth_failure(self, job: PollJob, result: PollResult) -> None:
        """401/403 → credential-health action; release capacity; wait (no tight loop)."""
        job.attempt += 1
        status = result.status_code
        msg = result.message or (
            "authentication/authorization failure; credential health check required"
        )
        self._emit_alert(
            kind=AlertKind.CREDENTIAL_HEALTH,
            job=job,
            action=ActionKind.CREDENTIAL_HEALTH,
            message=msg,
            status_code=status,
        )
        self._emit_action(
            kind=ActionKind.CREDENTIAL_HEALTH,
            job=job,
            message=msg,
            status_code=status,
            labels={"credential_ref_id": job.credential_ref_id or ""},
        )
        delay = self._backoff_delay(job.attempt)
        self._enter_waiting(
            job,
            delay_seconds=delay,
            disposition=result.disposition,
            status_code=status,
            message=msg,
        )

    def _handle_rate_limit(self, job: PollJob, result: PollResult) -> None:
        """429 → honor Retry-After; release capacity."""
        job.attempt += 1
        retry_after = result.retry_after_seconds
        if retry_after is None:
            retry_after = parse_retry_after(
                result.headers,
                now=self._wall(),
                max_seconds=self._config.max_retry_after_seconds,
            )
        delay = self._backoff_delay(job.attempt, retry_after=retry_after)
        self._emit_alert(
            kind=AlertKind.RATE_LIMIT,
            job=job,
            message=f"rate limited; retry after {delay:.3f}s",
            status_code=result.status_code or 429,
            force=True,
        )
        self._enter_waiting(
            job,
            delay_seconds=delay,
            disposition=PollDisposition.RATE_LIMITED,
            status_code=result.status_code or 429,
            message=f"Retry-After honored ({delay:.3f}s)",
        )

    def _handle_upstream_error(self, job: PollJob, result: PollResult) -> None:
        """5xx / transport → count toward circuit; open when threshold hit."""
        job.attempt += 1
        job.consecutive_upstream_failures += 1
        breaker = self._get_circuit(job.service)
        was_open = breaker.state is CircuitState.OPEN
        breaker.record_failure()
        now_open = breaker.state is CircuitState.OPEN
        if now_open and not was_open:
            self._emit_alert(
                kind=AlertKind.CIRCUIT_OPEN,
                job=job,
                action=ActionKind.CIRCUIT_RECOVERY,
                message=f"circuit open for service={job.service}",
                status_code=result.status_code,
            )
            self._emit_action(
                kind=ActionKind.CIRCUIT_RECOVERY,
                job=job,
                message=f"circuit open for service={job.service}",
                status_code=result.status_code,
            )
        delay = self._backoff_delay(
            job.consecutive_upstream_failures,
            retry_after=result.retry_after_seconds,
        )
        if now_open:
            delay = max(delay, self._config.circuit_recovery_seconds)
        self._enter_waiting(
            job,
            delay_seconds=delay,
            disposition=PollDisposition.UPSTREAM_ERROR
            if result.disposition is not PollDisposition.TRANSPORT_ERROR
            else result.disposition,
            status_code=result.status_code,
            message=result.message,
        )

    def _handle_circuit_open_short_circuit(self, job: PollJob) -> None:
        """Service circuit is open — do not poll; wait and release capacity."""
        job.attempt += 1
        self._enter_waiting(
            job,
            delay_seconds=self._config.circuit_recovery_seconds,
            disposition=PollDisposition.CIRCUIT_OPEN,
            message=f"circuit open for service={job.service}",
        )

    # ------------------------------------------------------------------
    # Tick / run
    # ------------------------------------------------------------------

    def tick(self, *, max_jobs: int | None = None) -> dict[str, Any]:
        """Run up to *max_jobs* (default: available workers) ready jobs once each."""
        if self._closed:
            raise SchedulerError("scheduler is closed", code="scheduler_closed")
        limit = self._workers.available if max_jobs is None else max(0, int(max_jobs))
        processed = 0
        outcomes: list[dict[str, Any]] = []
        now = self._now_mono()

        # Promote WAITING jobs whose delay elapsed back to PENDING (still queued).
        for job in self._checkpoint.jobs.values():
            if job.state is JobState.WAITING and job.next_run_at <= now:
                job.state = JobState.PENDING
                job.updated_at_utc = self._now_utc()
                try:
                    self._queues.enqueue(job)
                except QueueFullError:
                    pass

        while processed < limit and self._workers.available > 0:
            job = self._queues.pop_ready(
                self._checkpoint.jobs,
                now=self._now_mono(),
                metadata_before_binary=self._config.metadata_before_binary,
                is_service_available=self._service_available,
                is_binary_allowed=self._binary_allowed,
            )
            if job is None:
                # Maybe all services circuit-open: try to pull a job to park in wait.
                job = self._queues.pop_ready(
                    self._checkpoint.jobs,
                    now=self._now_mono(),
                    metadata_before_binary=self._config.metadata_before_binary,
                    is_service_available=lambda _s: True,
                    is_binary_allowed=self._binary_allowed,
                )
                if job is None:
                    break
                if not self._service_available(job.service):
                    if not self._workers.acquire(job.job_id):
                        self._queues.requeue_front(job)
                        break
                    job.state = JobState.RUNNING
                    self._handle_circuit_open_short_circuit(job)
                    outcomes.append(
                        {
                            "disposition": PollDisposition.CIRCUIT_OPEN.value,
                            "job_id": job.job_id,
                        }
                    )
                    processed += 1
                    continue

            if not self._workers.acquire(job.job_id):
                self._queues.requeue_front(job)
                break

            job.state = JobState.RUNNING
            job.updated_at_utc = self._now_utc()
            # Double-check circuit after acquire.
            if not self._service_available(job.service):
                self._handle_circuit_open_short_circuit(job)
                outcomes.append(
                    {
                        "disposition": PollDisposition.CIRCUIT_OPEN.value,
                        "job_id": job.job_id,
                    }
                )
                processed += 1
                continue

            # Binary gating: if not allowed, release and requeue as waiting briefly.
            if job.content_kind is ContentKind.BINARY and not self._binary_allowed(job):
                self._enter_waiting(
                    job,
                    delay_seconds=min(1.0, self._config.base_backoff_seconds),
                    disposition=PollDisposition.CLIENT_ERROR,
                    message="metadata-before-binary gate: metadata not ready",
                )
                outcomes.append(
                    {
                        "disposition": "metadata_gate",
                        "job_id": job.job_id,
                    }
                )
                processed += 1
                continue

            try:
                breaker = self._get_circuit(job.service)
                breaker.before_request()
            except Exception:
                self._handle_circuit_open_short_circuit(job)
                outcomes.append(
                    {
                        "disposition": PollDisposition.CIRCUIT_OPEN.value,
                        "job_id": job.job_id,
                    }
                )
                processed += 1
                continue

            try:
                result = self._invoke_poller(job)
            except Exception as exc:  # noqa: BLE001 — poller faults → dead-letter
                self._dead_letter(
                    job,
                    reason=DeadLetterReason.PARSE_FAILURE,
                    message=sanitize_secret_text(f"poller raised: {exc}"),
                    error_code="poller_exception",
                )
                outcomes.append(
                    {
                        "disposition": PollDisposition.PARSE_FAILURE.value,
                        "job_id": job.job_id,
                    }
                )
                processed += 1
                continue

            disposition = result.disposition
            outcome_record: dict[str, Any] = {
                "disposition": disposition.value,
                "job_id": job.job_id,
                "status_code": result.status_code,
            }

            if disposition in (
                PollDisposition.SUCCESS,
                PollDisposition.UNCHANGED,
                PollDisposition.CHANGED,
            ):
                self._handle_success(job, result)
                outcome_record["disposition"] = job.last_disposition
            elif disposition in (
                PollDisposition.UNAUTHORIZED,
                PollDisposition.FORBIDDEN,
            ):
                self._handle_auth_failure(job, result)
            elif disposition is PollDisposition.RATE_LIMITED:
                self._handle_rate_limit(job, result)
            elif disposition in (
                PollDisposition.UPSTREAM_ERROR,
                PollDisposition.TRANSPORT_ERROR,
            ):
                self._handle_upstream_error(job, result)
            elif disposition is PollDisposition.PARSE_FAILURE:
                self._dead_letter(
                    job,
                    reason=DeadLetterReason.PARSE_FAILURE,
                    message=result.message or "parse failure",
                    status_code=result.status_code,
                    error_code=result.error_code or "parse_failure",
                )
            elif disposition is PollDisposition.SECURITY_FAILURE:
                self._dead_letter(
                    job,
                    reason=DeadLetterReason.SECURITY_FAILURE,
                    message=result.message or "security failure",
                    status_code=result.status_code,
                    error_code=result.error_code or "security_failure",
                )
            elif disposition is PollDisposition.CIRCUIT_OPEN:
                self._handle_circuit_open_short_circuit(job)
            elif disposition is PollDisposition.NOT_FOUND:
                # Not found is a terminal success-like outcome (gap, not nonreceipt).
                job.attempt += 1
                job.last_disposition = disposition.value
                job.last_status_code = result.status_code
                job.state = JobState.SUCCEEDED
                job.updated_at_utc = self._now_utc()
                self._workers.release(job.job_id)
                self._get_circuit(job.service).record_success()
            elif disposition is PollDisposition.CLIENT_ERROR:
                # Permanent client errors dead-letter; avoid infinite retry storms.
                self._dead_letter(
                    job,
                    reason=DeadLetterReason.PERMANENT_CLIENT_ERROR,
                    message=result.message or "permanent client error",
                    status_code=result.status_code,
                    error_code=result.error_code or "client_error",
                )
            elif disposition is PollDisposition.CANCELLED:
                job.state = JobState.CANCELLED
                job.updated_at_utc = self._now_utc()
                job.last_disposition = disposition.value
                self._workers.release(job.job_id)
            else:
                self._handle_upstream_error(job, result)

            # Invariant: RUNNING must not retain capacity after handling.
            if job.state is not JobState.RUNNING:
                self._workers.release(job.job_id)
            else:
                # Safety net — never leave a job stuck RUNNING holding a slot.
                self._enter_waiting(
                    job,
                    delay_seconds=self._config.base_backoff_seconds,
                    disposition=PollDisposition.TRANSPORT_ERROR,
                    message="safety release of worker capacity",
                )

            outcomes.append(outcome_record)
            processed += 1

        self._maybe_heartbeat()
        self._checkpoint.progress.ticks += 1
        self._checkpoint.progress.last_tick_utc = self._now_utc()
        self._persist()
        return {
            "outcomes": outcomes,
            "processed": processed,
            "progress": self.progress().to_dict(),
            "workers_available": self._workers.available,
            "workers_in_use": self._workers.in_use,
        }

    def run_until_idle(
        self,
        *,
        max_ticks: int = 10_000,
        max_wall_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Drive ticks until no ready work remains or bounds are hit.

        Does **not** busy-wait on delayed jobs: if only WAITING jobs remain,
        returns with ``idle_reason=waiting`` without holding workers.
        """
        start = self._now_mono()
        ticks = 0
        total_processed = 0
        last: dict[str, Any] = {}
        while ticks < max_ticks:
            if max_wall_seconds is not None and (
                self._now_mono() - start
            ) >= float(max_wall_seconds):
                return {
                    "idle_reason": "max_wall_seconds",
                    "last": last,
                    "ticks": ticks,
                    "total_processed": total_processed,
                }
            last = self.tick()
            ticks += 1
            total_processed += int(last.get("processed") or 0)
            if int(last.get("processed") or 0) == 0:
                # Distinguish pure idle vs delayed waiters.
                now = self._now_mono()
                has_future = any(
                    j.state is JobState.WAITING and j.next_run_at > now
                    for j in self._checkpoint.jobs.values()
                )
                has_pending = any(
                    j.state is JobState.PENDING for j in self._checkpoint.jobs.values()
                )
                if has_future and not has_pending:
                    return {
                        "idle_reason": "waiting",
                        "last": last,
                        "ticks": ticks,
                        "total_processed": total_processed,
                    }
                if not has_pending and not has_future:
                    return {
                        "idle_reason": "idle",
                        "last": last,
                        "ticks": ticks,
                        "total_processed": total_processed,
                    }
                # Pending but gated (binary without metadata) or circuit — avoid spin.
                if has_pending:
                    # One more soft wait: park pending gated jobs.
                    for j in list(self._checkpoint.jobs.values()):
                        if j.state is JobState.PENDING and j.content_kind is ContentKind.BINARY:
                            if not self._binary_allowed(j):
                                j.state = JobState.WAITING
                                j.next_run_at = now + self._config.base_backoff_seconds
                    self._persist()
                    return {
                        "idle_reason": "gated_or_circuit",
                        "last": last,
                        "ticks": ticks,
                        "total_processed": total_processed,
                    }
        return {
            "idle_reason": "max_ticks",
            "last": last,
            "ticks": ticks,
            "total_processed": total_processed,
        }

    def _maybe_heartbeat(self) -> None:
        now = self._now_mono()
        if now - self._last_heartbeat_mono < self._config.heartbeat_interval_seconds:
            return
        self._last_heartbeat_mono = now
        self._checkpoint.progress.last_heartbeat_utc = self._now_utc()
        self._emit_alert(
            kind=AlertKind.HEARTBEAT,
            message="scheduler heartbeat",
            labels={
                "jobs_waiting": str(self._checkpoint.progress.jobs_waiting),
                "workers_available": str(self._workers.available),
                "workers_in_use": str(self._workers.in_use),
            },
            force=True,
        )

    def force_heartbeat(self) -> SchedulerAlert | None:
        """Emit a heartbeat immediately (tests / operator probe)."""
        self._last_heartbeat_mono = 0.0
        self._maybe_heartbeat()
        self._persist()
        for alert in reversed(self._checkpoint.alerts):
            if alert.kind is AlertKind.HEARTBEAT:
                return alert
        return None

    # ------------------------------------------------------------------
    # Restart / reload
    # ------------------------------------------------------------------

    def reload(self) -> None:
        """Reload checkpoint from store (simulates process restart)."""
        # Drop in-memory worker holds — restart releases all capacity.
        for jid in list(self._workers._held_jobs):
            self._workers.release(jid)
        self._queues = BoundedServiceQueues(self._config.max_queue_depth)
        self._circuits = {}
        self._checkpoint = self._store.load()
        self._restore_runtime_from_checkpoint()
        self._persist()

    def close(self) -> None:
        self._persist()
        self._closed = True

    # ------------------------------------------------------------------
    # Inspection helpers
    # ------------------------------------------------------------------

    def list_dead_letters(self) -> list[dict[str, Any]]:
        return [d.to_dict() for d in self._checkpoint.dead_letters]

    def list_alerts(self, *, kind: AlertKind | str | None = None) -> list[dict[str, Any]]:
        if kind is None:
            return [a.to_dict() for a in self._checkpoint.alerts]
        kind_v = kind.value if isinstance(kind, AlertKind) else str(kind)
        return [
            a.to_dict() for a in self._checkpoint.alerts if a.kind.value == kind_v
        ]

    def list_actions(
        self, *, kind: ActionKind | str | None = None, open_only: bool = True
    ) -> list[dict[str, Any]]:
        items = self._checkpoint.actions
        if open_only:
            items = [a for a in items if not a.resolved]
        if kind is not None:
            kind_v = kind.value if isinstance(kind, ActionKind) else str(kind)
            items = [a for a in items if a.kind.value == kind_v]
        return [a.to_dict() for a in items]

    def credential_health_actions(self) -> list[dict[str, Any]]:
        return self.list_actions(kind=ActionKind.CREDENTIAL_HEALTH, open_only=True)

    def circuit_state(self, service: str) -> str:
        return self._get_circuit(service).state.value


def create_scheduler(
    poller: Poller | Callable[[PollJob], PollResult],
    *,
    config: SchedulerConfig | None = None,
    checkpoint_dir: Path | str | None = None,
    checkpoint_name: str = "scheduler",
    clock: Clock = time.monotonic,
    wall_clock: WallClock | None = None,
    id_factory: IdFactory | None = None,
) -> USPTOApplicationScheduler:
    """Factory for a filesystem- or memory-backed scheduler."""
    store = SchedulerCheckpointStore(
        root=Path(checkpoint_dir) if checkpoint_dir is not None else None,
        name=checkpoint_name,
    )
    return USPTOApplicationScheduler(
        poller=poller,
        config=config,
        checkpoint_store=store,
        clock=clock,
        wall_clock=wall_clock,
        id_factory=id_factory,
    )


__all__ = [
    "SCHEDULER_INTERFACE",
    "SCHEDULER_SCHEMA_VERSION",
    "ActionKind",
    "AlertKind",
    "BoundedServiceQueues",
    "ChangeFingerprint",
    "ContentKind",
    "DeadLetterReason",
    "DeadLetterRecord",
    "JobState",
    "OperatorAction",
    "PollDisposition",
    "PollJob",
    "PollResult",
    "Poller",
    "QueueFullError",
    "SchedulerAlert",
    "SchedulerCheckpoint",
    "SchedulerCheckpointStore",
    "SchedulerConfig",
    "SchedulerError",
    "SchedulerProgress",
    "ServiceName",
    "USPTOApplicationScheduler",
    "WorkerPool",
    "create_scheduler",
    "disposition_from_provider_kind",
    "disposition_from_status",
    "parse_retry_after",
]
