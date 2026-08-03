"""Shared USPTO ODP provider transport primitives.

This module owns injectable HTTP transport, retry/circuit-breaker policy,
sanitized receipts, cancellation, conditional caching, and typed provider
outcomes. It never invents official rate-limit constants: any client-side
rate policy must be injected by the operator after consulting current USPTO
ODP documentation (see https://data.uspto.gov/apis/api-rate-limits).

Secrets (API keys) are held only as opaque references and are never written
into receipts, error messages, logs, or fixture artifacts.
"""

from __future__ import annotations

import email.utils
import hashlib
import json
import math
import random
import re
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Protocol, runtime_checkable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    SourceReceipt,
    canonical_json,
)

PROVIDER_BASE_SCHEMA_VERSION: Final = "uspto.provider.base.v1"
DEFAULT_ODP_BASE_URL: Final = "https://api.uspto.gov"
API_KEY_HEADER: Final = "X-API-KEY"

# Credential header names (lower-case) that must never appear in receipts/logs.
_CREDENTIAL_HEADER_NAMES: Final = frozenset(
    {
        "authorization",
        "cookie",
        "proxy-authorization",
        "x-api-key",
        "api-key",
        "x-api_key",
    }
)

# Query parameter names treated as secrets when sanitizing request URLs.
_CREDENTIAL_QUERY_NAMES: Final = frozenset(
    {
        "api_key",
        "apikey",
        "api-key",
        "key",
        "token",
        "access_token",
        "secret",
    }
)

_SECRET_TEXT_RE = re.compile(
    r"(?i)(x-api-key|api[_-]?key|authorization|bearer|token)\s*[:=]\s*[^\s,;\"']+"
)

Clock = Callable[[], float]
WallClock = Callable[[], datetime]
Sleeper = Callable[[float], None]
RandomSample = Callable[[], float]


# ---------------------------------------------------------------------------
# Errors (messages never include secret material)
# ---------------------------------------------------------------------------


class ProviderError(Exception):
    """Base provider error with a stable machine code and safe text."""

    code: str = "provider_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(sanitize_secret_text(message))
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class ProviderConfigError(ProviderError):
    code = "config_invalid"


class ProviderCancelledError(ProviderError):
    code = "cancelled"


class ProviderRetryBudgetError(ProviderError):
    code = "retry_budget_exhausted"

    def __init__(
        self,
        message: str,
        *,
        attempts: int = 0,
        last_status: int | None = None,
        last_outcome: "ProviderOutcomeKind | str | None" = None,
    ) -> None:
        super().__init__(message, code=self.code)
        self.attempts = int(attempts)
        self.last_status = last_status
        self.last_outcome = (
            last_outcome.value
            if isinstance(last_outcome, ProviderOutcomeKind)
            else last_outcome
        )

    def to_dict(self) -> dict[str, Any]:
        out = super().to_dict()
        out.update(
            {
                "attempts": self.attempts,
                "last_outcome": self.last_outcome,
                "last_status": self.last_status,
            }
        )
        return out


class ProviderCircuitOpenError(ProviderError):
    code = "circuit_open"


class ProviderSchemaError(ProviderError):
    code = "schema_invalid"

    def __init__(
        self,
        message: str,
        *,
        field_name: str | None = None,
        code: str = "schema_invalid",
    ) -> None:
        super().__init__(message, code=code)
        self.field_name = field_name

    def to_dict(self) -> dict[str, Any]:
        out = super().to_dict()
        out["field_name"] = self.field_name
        return out


class ProviderSchemaDriftError(ProviderSchemaError):
    code = "schema_drift"


class ProviderMalformedError(ProviderSchemaError):
    code = "malformed_payload"


# ---------------------------------------------------------------------------
# Outcome taxonomy
# ---------------------------------------------------------------------------


class ProviderOutcomeKind(str, Enum):
    """Typed result kinds for recorded and live ODP interactions."""

    SUCCESS = "success"
    NOT_MODIFIED = "not_modified"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    UPSTREAM_ERROR = "upstream_error"
    CLIENT_ERROR = "client_error"
    MALFORMED = "malformed"
    SCHEMA_DRIFT = "schema_drift"
    CANCELLED = "cancelled"
    RETRY_BUDGET_EXHAUSTED = "retry_budget_exhausted"
    CIRCUIT_OPEN = "circuit_open"
    TRANSPORT_ERROR = "transport_error"


class RetryDisposition(str, Enum):
    SUCCESS = "success"
    THROTTLED = "throttled"
    TRANSIENT = "transient"
    PERMANENT = "permanent"


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# ---------------------------------------------------------------------------
# Secret handling
# ---------------------------------------------------------------------------


class ApiKeySecret:
    """Opaque API-key holder. Value is excluded from every representation."""

    __slots__ = ("_value", "reference_id")

    def __init__(self, value: str, *, reference_id: str = "odp-api-key") -> None:
        if not isinstance(value, str) or not value:
            raise ProviderConfigError("api key must be a non-empty string")
        if "\x00" in value or "\r" in value or "\n" in value:
            raise ProviderConfigError("api key contains invalid characters")
        if not isinstance(reference_id, str) or not reference_id or len(reference_id) > 128:
            raise ProviderConfigError("api key reference_id is invalid")
        self._value = value
        self.reference_id = reference_id

    def reveal(self) -> str:
        """Return the raw key for request construction only."""

        return self._value

    def __repr__(self) -> str:
        return f"ApiKeySecret(reference_id={self.reference_id!r})"

    def __str__(self) -> str:
        return self.__repr__()

    def to_dict(self) -> dict[str, str]:
        return {"kind": "api_key", "reference_id": self.reference_id}


def sanitize_secret_text(text: str) -> str:
    """Strip credential-like substrings from free-form text."""

    if not isinstance(text, str):
        return "<non-string>"
    redacted = _SECRET_TEXT_RE.sub(r"\1=<redacted>", text)
    # Bound length to avoid logging huge upstream bodies.
    if len(redacted) > 512:
        return redacted[:509] + "..."
    return redacted


def sanitize_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    """Return a copy of headers with credential values redacted."""

    if not headers:
        return {}
    out: dict[str, str] = {}
    for key, value in headers.items():
        name = str(key)
        if name.lower() in _CREDENTIAL_HEADER_NAMES:
            out[name] = "<redacted>"
        else:
            out[name] = sanitize_secret_text(str(value))
    return out


def sanitize_url(url: str) -> str:
    """Return a URL with credential query parameters redacted."""

    try:
        parts = urlsplit(url)
    except ValueError:
        return "<invalid-url>"
    if not parts.query:
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))
    pairs: list[tuple[str, str]] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in _CREDENTIAL_QUERY_NAMES:
            pairs.append((key, "<redacted>"))
        else:
            pairs.append((key, value))
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment)
    )


def contains_secret_leak(payload: Any, *, secret: str | None = None) -> bool:
    """Return True if *payload* appears to contain secret material."""

    text = payload if isinstance(payload, str) else json.dumps(payload, default=str)
    if secret and secret and secret in text:
        return True
    lowered = text.lower()
    # Detect unredacted credential header assignments.
    if re.search(r"x-api-key['\"]?\s*[:=]\s*['\"]?(?!<redacted>)[A-Za-z0-9_\-]{8,}", lowered):
        return True
    return False


# ---------------------------------------------------------------------------
# Request / response / cancellation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HttpRequest:
    """Outbound HTTP request. The raw URL is excluded from ``repr``."""

    method: str
    url: str = field(repr=False)
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes | None = field(default=None, repr=False)
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        method = str(self.method or "").strip().upper()
        if method not in {"GET", "POST", "HEAD", "PUT", "DELETE", "PATCH"}:
            raise ProviderConfigError(f"unsupported HTTP method: {self.method!r}")
        object.__setattr__(self, "method", method)
        if not isinstance(self.url, str) or not self.url:
            raise ProviderConfigError("request url must be non-empty")
        if self.body is not None and not isinstance(self.body, (bytes, bytearray)):
            raise ProviderConfigError("request body must be bytes")
        if self.timeout_seconds is not None:
            object.__setattr__(
                self,
                "timeout_seconds",
                _positive_finite(self.timeout_seconds, "timeout_seconds"),
            )
        object.__setattr__(
            self,
            "headers",
            MappingProxyType({str(k): str(v) for k, v in dict(self.headers or {}).items()}),
        )

    def __repr__(self) -> str:
        return (
            f"HttpRequest(method={self.method!r}, "
            f"url={sanitize_url(self.url)!r}, "
            f"headers={sanitize_headers(self.headers)!r}, "
            f"body_bytes={0 if self.body is None else len(self.body)})"
        )

    def sanitized_dict(self) -> dict[str, Any]:
        return {
            "body_bytes": 0 if self.body is None else len(self.body),
            "headers": sanitize_headers(self.headers),
            "method": self.method,
            "url": sanitize_url(self.url),
        }


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """Inbound HTTP response with raw body bytes."""

    status_code: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""
    elapsed_seconds: float = 0.0

    def __post_init__(self) -> None:
        if isinstance(self.status_code, bool) or not isinstance(self.status_code, int):
            raise ProviderConfigError("status_code must be int")
        if not 0 <= self.status_code <= 599:
            raise ProviderConfigError("status_code must be in 0..599")
        if not isinstance(self.body, (bytes, bytearray)):
            raise ProviderConfigError("response body must be bytes")
        object.__setattr__(self, "body", bytes(self.body))
        object.__setattr__(
            self,
            "headers",
            MappingProxyType(
                {str(k): str(v) for k, v in dict(self.headers or {}).items()}
            ),
        )
        object.__setattr__(
            self,
            "elapsed_seconds",
            max(0.0, float(self.elapsed_seconds or 0.0)),
        )

    def header(self, name: str) -> str | None:
        target = name.lower()
        for key, value in self.headers.items():
            if key.lower() == target:
                return value
        return None

    def text(self, *, encoding: str = "utf-8", errors: str = "replace") -> str:
        return self.body.decode(encoding, errors=errors)

    def json(self) -> Any:
        if not self.body:
            return None
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderMalformedError(
                f"response body is not valid JSON: {sanitize_secret_text(str(exc))}",
                field_name="body",
            ) from None


class CancellationToken:
    """Simple cooperative cancellation flag."""

    __slots__ = ("_cancelled", "reason")

    def __init__(self, *, cancelled: bool = False, reason: str = "cancelled") -> None:
        self._cancelled = bool(cancelled)
        self.reason = str(reason or "cancelled")

    def cancel(self, reason: str = "cancelled") -> None:
        self._cancelled = True
        self.reason = str(reason or "cancelled")

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def check(self) -> None:
        if self._cancelled:
            raise ProviderCancelledError(self.reason)


@runtime_checkable
class HttpTransport(Protocol):
    """Injected HTTP boundary (sync). Implementations must not log secrets."""

    def request(self, request: HttpRequest) -> HttpResponse:
        ...


# ---------------------------------------------------------------------------
# Policy records (no invented official rate limits)
# ---------------------------------------------------------------------------


def _positive_int(value: int, name: str, *, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProviderConfigError(f"{name} must be a positive integer")
    if maximum is not None and value > maximum:
        raise ProviderConfigError(f"{name} must be <= {maximum}")
    return value


def _nonneg_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProviderConfigError(f"{name} must be a non-negative integer")
    return value


def _positive_finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderConfigError(f"{name} must be a positive finite number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ProviderConfigError(f"{name} must be a positive finite number")
    return result


def _nonneg_finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderConfigError(f"{name} must be a non-negative finite number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ProviderConfigError(f"{name} must be a non-negative finite number")
    return result


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded exponential backoff with optional Retry-After honor.

    Backoff parameters are transport safety bounds, not USPTO-published rate
    limits. Official rate ceilings must be supplied separately via
    :class:`RatePolicy` when the operator has an authorized current value.
    """

    max_attempts: int = 3
    base_delay_seconds: float = 0.25
    max_delay_seconds: float = 30.0
    max_retry_after_seconds: float = 60.0
    jitter_fraction: float = 0.2
    honor_retry_after: bool = True
    retry_statuses: frozenset[int] = field(
        default_factory=lambda: frozenset({408, 425, 429, 500, 502, 503, 504})
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "max_attempts", _positive_int(self.max_attempts, "max_attempts", maximum=20)
        )
        base = _nonneg_finite(self.base_delay_seconds, "base_delay_seconds")
        maximum = _nonneg_finite(self.max_delay_seconds, "max_delay_seconds")
        retry_after = _nonneg_finite(
            self.max_retry_after_seconds, "max_retry_after_seconds"
        )
        jitter = _nonneg_finite(self.jitter_fraction, "jitter_fraction")
        if maximum < base:
            raise ProviderConfigError(
                "max_delay_seconds must not be less than base_delay_seconds"
            )
        if jitter > 1:
            raise ProviderConfigError("jitter_fraction must not exceed 1")
        statuses = frozenset(int(s) for s in self.retry_statuses)
        if any(not 100 <= s <= 599 for s in statuses):
            raise ProviderConfigError("retry_statuses contains an invalid HTTP status")
        object.__setattr__(self, "base_delay_seconds", base)
        object.__setattr__(self, "max_delay_seconds", maximum)
        object.__setattr__(self, "max_retry_after_seconds", retry_after)
        object.__setattr__(self, "jitter_fraction", jitter)
        object.__setattr__(self, "retry_statuses", statuses)
        if not isinstance(self.honor_retry_after, bool):
            raise ProviderConfigError("honor_retry_after must be bool")

    def classify_status(self, status: int) -> RetryDisposition:
        if 200 <= status < 300 or status == 304:
            return RetryDisposition.SUCCESS
        if status == 429:
            return RetryDisposition.THROTTLED
        if status in self.retry_statuses:
            return RetryDisposition.TRANSIENT
        return RetryDisposition.PERMANENT

    def retry_after_seconds(
        self,
        headers: Mapping[str, str],
        *,
        now: datetime | None = None,
    ) -> float | None:
        if not self.honor_retry_after:
            return None
        value = None
        for key, item in headers.items():
            if key.lower() == "retry-after":
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
        return min(max(0.0, delay), self.max_retry_after_seconds)

    def delay_seconds(
        self,
        failed_attempt: int,
        *,
        retry_after: float | None = None,
        random_value: float | None = None,
    ) -> float:
        if (
            isinstance(failed_attempt, bool)
            or not isinstance(failed_attempt, int)
            or failed_attempt <= 0
        ):
            raise ProviderConfigError("failed_attempt must be a positive integer")
        if retry_after is not None:
            return min(
                _nonneg_finite(retry_after, "retry_after"),
                self.max_retry_after_seconds,
            )
        base = min(
            self.max_delay_seconds,
            self.base_delay_seconds * (2 ** (failed_attempt - 1)),
        )
        sample = random.random() if random_value is None else float(random_value)
        if not 0.0 <= sample <= 1.0:
            raise ProviderConfigError("random_value must be between 0 and 1")
        factor = 1.0 - self.jitter_fraction + (2.0 * self.jitter_fraction * sample)
        return min(self.max_delay_seconds, max(0.0, base * factor))

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_delay_seconds": self.base_delay_seconds,
            "honor_retry_after": self.honor_retry_after,
            "jitter_fraction": self.jitter_fraction,
            "max_attempts": self.max_attempts,
            "max_delay_seconds": self.max_delay_seconds,
            "max_retry_after_seconds": self.max_retry_after_seconds,
            "retry_statuses": sorted(self.retry_statuses),
        }


@dataclass(frozen=True, slots=True)
class RatePolicy:
    """Optional client-side rate bound.

    There is **no default**. Operators must construct this only with values
    authorized by current official ODP rate documentation; this library never
    invents a requests-per-second constant as if it were USPTO-published.
    """

    requests_per_second: float
    burst: int = 1
    max_wait_seconds: float = 30.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "requests_per_second",
            _positive_finite(self.requests_per_second, "requests_per_second"),
        )
        object.__setattr__(self, "burst", _positive_int(self.burst, "burst"))
        object.__setattr__(
            self,
            "max_wait_seconds",
            _positive_finite(self.max_wait_seconds, "max_wait_seconds"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "burst": self.burst,
            "max_wait_seconds": self.max_wait_seconds,
            "requests_per_second": self.requests_per_second,
            "source": "operator_injected",
        }


class RateLimiter:
    """Token-bucket limiter activated only when a :class:`RatePolicy` is set."""

    __slots__ = ("_clock", "_last", "_policy", "_sleep", "_tokens")

    def __init__(
        self,
        policy: RatePolicy,
        *,
        clock: Clock = time.monotonic,
        sleep: Sleeper = time.sleep,
    ) -> None:
        if not isinstance(policy, RatePolicy):
            raise ProviderConfigError("rate limiter requires an explicit RatePolicy")
        self._policy = policy
        self._clock = clock
        self._sleep = sleep
        self._tokens = float(policy.burst)
        self._last = float(clock())

    @property
    def policy(self) -> RatePolicy:
        return self._policy

    def acquire(self, *, cancellation: CancellationToken | None = None) -> float:
        total_wait = 0.0
        while True:
            if cancellation is not None:
                cancellation.check()
            now = float(self._clock())
            elapsed = max(0.0, now - self._last)
            self._tokens = min(
                float(self._policy.burst),
                self._tokens + elapsed * self._policy.requests_per_second,
            )
            self._last = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return total_wait
            wait = (1.0 - self._tokens) / self._policy.requests_per_second
            if total_wait + wait > self._policy.max_wait_seconds:
                raise ProviderRetryBudgetError(
                    "rate-limit wait exceeded its bound",
                    attempts=0,
                    last_outcome=ProviderOutcomeKind.RATE_LIMITED,
                )
            self._sleep(wait)
            total_wait += wait


@dataclass(frozen=True, slots=True)
class CircuitBreakerPolicy:
    failure_threshold: int = 5
    recovery_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "failure_threshold",
            _positive_int(self.failure_threshold, "failure_threshold"),
        )
        object.__setattr__(
            self,
            "recovery_timeout_seconds",
            _nonneg_finite(
                self.recovery_timeout_seconds, "recovery_timeout_seconds"
            ),
        )


class CircuitBreaker:
    """Simple closed/open/half-open breaker for repeated upstream failures."""

    __slots__ = (
        "_clock",
        "_consecutive_failures",
        "_opened_at",
        "_policy",
        "_state",
    )

    def __init__(
        self,
        policy: CircuitBreakerPolicy | None = None,
        *,
        clock: Clock = time.monotonic,
    ) -> None:
        self._policy = policy or CircuitBreakerPolicy()
        self._clock = clock
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> CircuitState:
        self._maybe_half_open()
        return self._state

    def _maybe_half_open(self) -> None:
        if self._state is CircuitState.OPEN and self._opened_at is not None:
            if float(self._clock()) - self._opened_at >= self._policy.recovery_timeout_seconds:
                self._state = CircuitState.HALF_OPEN

    def before_request(self) -> None:
        self._maybe_half_open()
        if self._state is CircuitState.OPEN:
            raise ProviderCircuitOpenError("provider circuit breaker is open")

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._state = CircuitState.CLOSED
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if (
            self._state is CircuitState.HALF_OPEN
            or self._consecutive_failures >= self._policy.failure_threshold
        ):
            self._state = CircuitState.OPEN
            self._opened_at = float(self._clock())


@dataclass(frozen=True, slots=True)
class ConditionalCacheEntry:
    """ETag / Last-Modified cache entry for conditional revalidation."""

    etag: str | None = None
    last_modified: str | None = None
    body: bytes = b""
    status_code: int = 200
    headers: Mapping[str, str] = field(default_factory=dict)
    stored_at_utc: str | None = None

    def __post_init__(self) -> None:
        if self.etag is not None and (not isinstance(self.etag, str) or not self.etag.strip()):
            raise ProviderConfigError("etag must be non-empty when provided")
        if self.last_modified is not None and (
            not isinstance(self.last_modified, str) or not self.last_modified.strip()
        ):
            raise ProviderConfigError("last_modified must be non-empty when provided")
        object.__setattr__(self, "body", bytes(self.body or b""))
        object.__setattr__(
            self,
            "headers",
            MappingProxyType({str(k): str(v) for k, v in dict(self.headers or {}).items()}),
        )


class ConditionalCache:
    """In-memory conditional response cache keyed by sanitized request identity."""

    __slots__ = ("_entries",)

    def __init__(self) -> None:
        self._entries: dict[str, ConditionalCacheEntry] = {}

    def get(self, cache_key: str) -> ConditionalCacheEntry | None:
        return self._entries.get(cache_key)

    def put(self, cache_key: str, entry: ConditionalCacheEntry) -> None:
        self._entries[cache_key] = entry

    def clear(self) -> None:
        self._entries.clear()


@dataclass(frozen=True, slots=True)
class PageCheckpoint:
    """Resumable pagination checkpoint (offset/limit or opaque cursor)."""

    resource: str
    offset: int = 0
    limit: int | None = None
    cursor: str | None = None
    pages_completed: int = 0
    items_completed: int = 0
    exhausted: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.resource, str) or not self.resource:
            raise ProviderConfigError("page checkpoint resource must be non-empty")
        object.__setattr__(self, "offset", _nonneg_int(self.offset, "offset"))
        if self.limit is not None:
            object.__setattr__(self, "limit", _positive_int(self.limit, "limit"))
        if self.cursor is not None and (not isinstance(self.cursor, str) or not self.cursor):
            raise ProviderConfigError("cursor must be non-empty when provided")
        object.__setattr__(
            self, "pages_completed", _nonneg_int(self.pages_completed, "pages_completed")
        )
        object.__setattr__(
            self, "items_completed", _nonneg_int(self.items_completed, "items_completed")
        )
        if not isinstance(self.exhausted, bool):
            raise ProviderConfigError("exhausted must be bool")
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType({str(k): str(v) for k, v in dict(self.metadata or {}).items()}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cursor": self.cursor,
            "exhausted": self.exhausted,
            "items_completed": self.items_completed,
            "limit": self.limit,
            "metadata": dict(self.metadata),
            "offset": self.offset,
            "pages_completed": self.pages_completed,
            "resource": self.resource,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PageCheckpoint":
        if not isinstance(value, Mapping):
            raise ProviderConfigError("page checkpoint must be a mapping")
        return cls(
            resource=str(value.get("resource") or ""),
            offset=int(value.get("offset") or 0),
            limit=value.get("limit"),
            cursor=value.get("cursor"),
            pages_completed=int(value.get("pages_completed") or 0),
            items_completed=int(value.get("items_completed") or 0),
            exhausted=bool(value.get("exhausted", False)),
            metadata=value.get("metadata") or {},
        )


# ---------------------------------------------------------------------------
# Typed results
# ---------------------------------------------------------------------------


def classify_http_status(status: int) -> ProviderOutcomeKind:
    if status == 200:
        return ProviderOutcomeKind.SUCCESS
    if status == 304:
        return ProviderOutcomeKind.NOT_MODIFIED
    if status == 401:
        return ProviderOutcomeKind.UNAUTHORIZED
    if status == 403:
        return ProviderOutcomeKind.FORBIDDEN
    if status == 404:
        return ProviderOutcomeKind.NOT_FOUND
    if status == 429:
        return ProviderOutcomeKind.RATE_LIMITED
    if 500 <= status <= 599:
        return ProviderOutcomeKind.UPSTREAM_ERROR
    if 400 <= status <= 499:
        return ProviderOutcomeKind.CLIENT_ERROR
    return ProviderOutcomeKind.TRANSPORT_ERROR


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """Typed outcome for one provider operation (success or recorded failure)."""

    kind: ProviderOutcomeKind
    status_code: int | None
    receipt: SourceReceipt | None
    payload: Any = None
    error_code: str | None = None
    message: str | None = None
    retry_after_seconds: float | None = None
    checkpoint: PageCheckpoint | None = None
    cache_hit: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "kind", _coerce_outcome(self.kind)
        )
        if self.status_code is not None:
            if isinstance(self.status_code, bool) or not isinstance(self.status_code, int):
                raise ProviderConfigError("status_code must be int or None")
        if self.message is not None:
            object.__setattr__(self, "message", sanitize_secret_text(str(self.message)))
        if self.error_code is not None:
            object.__setattr__(self, "error_code", str(self.error_code)[:128])
        if self.retry_after_seconds is not None:
            object.__setattr__(
                self,
                "retry_after_seconds",
                _nonneg_finite(self.retry_after_seconds, "retry_after_seconds"),
            )
        if not isinstance(self.cache_hit, bool):
            raise ProviderConfigError("cache_hit must be bool")
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType({str(k): str(v) for k, v in dict(self.metadata or {}).items()}),
        )

    @property
    def ok(self) -> bool:
        return self.kind in {
            ProviderOutcomeKind.SUCCESS,
            ProviderOutcomeKind.NOT_MODIFIED,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "cache_hit": self.cache_hit,
            "checkpoint": None if self.checkpoint is None else self.checkpoint.to_dict(),
            "error_code": self.error_code,
            "kind": self.kind.value,
            "message": self.message,
            "metadata": dict(self.metadata),
            "payload": self.payload,
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "retry_after_seconds": self.retry_after_seconds,
            "status_code": self.status_code,
        }


def _coerce_outcome(value: ProviderOutcomeKind | str) -> ProviderOutcomeKind:
    if isinstance(value, ProviderOutcomeKind):
        return value
    return ProviderOutcomeKind(str(value))


# ---------------------------------------------------------------------------
# Digests and receipts
# ---------------------------------------------------------------------------


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def request_digest(request: HttpRequest) -> str:
    """Stable digest over sanitized method/url/headers/body length (no secrets)."""

    material = {
        "body_sha256": None if request.body is None else sha256_hex(request.body),
        "headers": sanitize_headers(request.headers),
        "method": request.method,
        "url": sanitize_url(request.url),
    }
    return sha256_hex(canonical_json(material))


def format_utc(dt: datetime | None = None) -> str:
    current = dt or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)
    # Millisecond precision, Zulu form.
    current = current.replace(microsecond=(current.microsecond // 1000) * 1000)
    return current.isoformat().replace("+00:00", "Z")


def build_source_receipt(
    *,
    endpoint: str,
    status_code: int,
    request: HttpRequest,
    response_body: bytes | None = None,
    upstream_id: str | None = None,
    last_modified: str | None = None,
    cache_hit: bool = False,
    retry_count: int = 0,
    retrieval_utc: str | None = None,
    metadata: Mapping[str, str] | None = None,
    receipt_id: str | None = None,
) -> SourceReceipt:
    """Build a contracts.SourceReceipt that never embeds secrets."""

    meta = {str(k): str(v) for k, v in dict(metadata or {}).items()}
    meta.setdefault("provider", "odp_patent_file_wrapper")
    # Never allow credential-like metadata keys.
    for banned in ("api_key", "authorization", "token", "secret", "x-api-key"):
        meta.pop(banned, None)
    return SourceReceipt(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        receipt_id=receipt_id or f"receipt:odp:{uuid.uuid4().hex}",
        endpoint=sanitize_url(endpoint),
        retrieval_utc=retrieval_utc or format_utc(),
        response_status=int(status_code),
        upstream_id=upstream_id,
        last_modified=last_modified,
        request_digest=request_digest(request),
        response_digest=None if response_body is None else sha256_hex(response_body),
        cache_hit=bool(cache_hit),
        retry_count=_nonneg_int(retry_count, "retry_count"),
        metadata=meta,
    )


# ---------------------------------------------------------------------------
# Transport executor
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TransportLimits:
    """Finite safety budgets (not official rate limits)."""

    max_response_bytes: int = 16 * 1024 * 1024
    request_timeout_seconds: float = 30.0
    max_pages: int = 100
    max_items: int = 10_000

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_response_bytes",
            _positive_int(self.max_response_bytes, "max_response_bytes"),
        )
        object.__setattr__(
            self,
            "request_timeout_seconds",
            _positive_finite(self.request_timeout_seconds, "request_timeout_seconds"),
        )
        object.__setattr__(self, "max_pages", _positive_int(self.max_pages, "max_pages"))
        object.__setattr__(self, "max_items", _positive_int(self.max_items, "max_items"))


class ProviderHttpClient:
    """Policy-enforcing wrapper around an injected :class:`HttpTransport`.

    Responsibilities:
    * attach API key without leaking it into receipts/errors
    * honor Retry-After and bounded exponential backoff with jitter
    * optional operator-injected rate policy (never a hard-coded ODP RPS)
    * circuit breaker for repeated upstream failures
    * conditional caching (ETag / If-None-Match, Last-Modified)
    * cooperative cancellation
    * typed :class:`ProviderResult` for every terminal status class
    """

    __slots__ = (
        "_api_key",
        "_base_url",
        "_cache",
        "_cancellation",
        "_circuit",
        "_default_headers",
        "_limits",
        "_random",
        "_rate_limiter",
        "_retry_policy",
        "_sleep",
        "_transport",
        "_wall_clock",
    )

    def __init__(
        self,
        transport: HttpTransport,
        *,
        base_url: str = DEFAULT_ODP_BASE_URL,
        api_key: ApiKeySecret | str | None = None,
        retry_policy: RetryPolicy | None = None,
        rate_policy: RatePolicy | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        limits: TransportLimits | None = None,
        cache: ConditionalCache | None = None,
        cancellation: CancellationToken | None = None,
        default_headers: Mapping[str, str] | None = None,
        sleep: Sleeper = time.sleep,
        wall_clock: WallClock | None = None,
        random_sample: RandomSample | None = None,
    ) -> None:
        if not isinstance(transport, HttpTransport):
            # Structural check: require .request callable.
            if not callable(getattr(transport, "request", None)):
                raise ProviderConfigError("transport must implement HttpTransport.request")
        self._transport = transport
        self._base_url = _normalize_base_url(base_url)
        if api_key is None:
            self._api_key = None
        elif isinstance(api_key, ApiKeySecret):
            self._api_key = api_key
        else:
            self._api_key = ApiKeySecret(str(api_key))
        self._retry_policy = retry_policy or RetryPolicy()
        if rate_policy is None:
            self._rate_limiter = None
        else:
            self._rate_limiter = RateLimiter(rate_policy, sleep=sleep)
        self._circuit = circuit_breaker or CircuitBreaker()
        self._limits = limits or TransportLimits()
        self._cache = cache if cache is not None else ConditionalCache()
        self._cancellation = cancellation
        self._default_headers = {
            str(k): str(v) for k, v in dict(default_headers or {}).items()
        }
        self._default_headers.setdefault("Accept", "application/json")
        self._sleep = sleep
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self._random = random_sample or random.random

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def retry_policy(self) -> RetryPolicy:
        return self._retry_policy

    @property
    def rate_policy(self) -> RatePolicy | None:
        if self._rate_limiter is None:
            return None
        return self._rate_limiter.policy

    def safe_config(self) -> dict[str, Any]:
        """Serializable config with no secrets or absolute credentials."""

        return {
            "api_key": None if self._api_key is None else self._api_key.to_dict(),
            "base_url": self._base_url,
            "circuit_state": self._circuit.state.value,
            "limits": {
                "max_items": self._limits.max_items,
                "max_pages": self._limits.max_pages,
                "max_response_bytes": self._limits.max_response_bytes,
                "request_timeout_seconds": self._limits.request_timeout_seconds,
            },
            "rate_policy": None
            if self._rate_limiter is None
            else self._rate_limiter.policy.to_dict(),
            "retry_policy": self._retry_policy.to_dict(),
            "schema_version": PROVIDER_BASE_SCHEMA_VERSION,
        }

    def build_url(self, path: str, *, query: Mapping[str, Any] | None = None) -> str:
        base = self._base_url.rstrip("/")
        if not path.startswith("/"):
            path = "/" + path
        url = f"{base}{path}"
        if query:
            pairs = [
                (str(k), str(v))
                for k, v in query.items()
                if v is not None and v != ""
            ]
            if pairs:
                url = f"{url}?{urlencode(pairs)}"
        return url

    def _merge_headers(
        self,
        headers: Mapping[str, str] | None,
        *,
        conditional: ConditionalCacheEntry | None = None,
    ) -> dict[str, str]:
        merged = dict(self._default_headers)
        if headers:
            merged.update({str(k): str(v) for k, v in headers.items()})
        if self._api_key is not None:
            # Official ODP contract: X-API-KEY header (never query string).
            merged[API_KEY_HEADER] = self._api_key.reveal()
        if conditional is not None:
            if conditional.etag:
                merged.setdefault("If-None-Match", conditional.etag)
            if conditional.last_modified:
                merged.setdefault("If-Modified-Since", conditional.last_modified)
        return merged

    def _cache_key(self, method: str, url: str) -> str:
        return sha256_hex(f"{method}:{sanitize_url(url)}")

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        json_body: Any = None,
        enable_conditional_cache: bool = True,
        upstream_id: str | None = None,
        metadata: Mapping[str, str] | None = None,
        raise_on_error: bool = False,
    ) -> ProviderResult:
        """Execute one logical request with retry, returning a typed result."""

        if json_body is not None:
            body = json.dumps(json_body, separators=(",", ":"), sort_keys=True).encode(
                "utf-8"
            )
            headers = dict(headers or {})
            headers.setdefault("Content-Type", "application/json")

        url = self.build_url(path, query=query)
        cache_key = self._cache_key(method, url)
        cached = self._cache.get(cache_key) if enable_conditional_cache else None

        attempts = 0
        last_status: int | None = None
        last_kind: ProviderOutcomeKind | None = None
        retry_after_seen: float | None = None

        while attempts < self._retry_policy.max_attempts:
            if self._cancellation is not None:
                try:
                    self._cancellation.check()
                except ProviderCancelledError as exc:
                    return self._terminal(
                        kind=ProviderOutcomeKind.CANCELLED,
                        status_code=None,
                        request=HttpRequest(
                            method=method,
                            url=url,
                            headers=sanitize_headers(headers),
                        ),
                        response_body=None,
                        error_code=exc.code,
                        message=str(exc),
                        retry_count=attempts,
                        upstream_id=upstream_id,
                        metadata=metadata,
                        raise_on_error=raise_on_error,
                    )

            try:
                self._circuit.before_request()
            except ProviderCircuitOpenError as exc:
                return self._terminal(
                    kind=ProviderOutcomeKind.CIRCUIT_OPEN,
                    status_code=None,
                    request=HttpRequest(
                        method=method,
                        url=url,
                        headers=sanitize_headers(headers),
                    ),
                    response_body=None,
                    error_code=exc.code,
                    message=str(exc),
                    retry_count=attempts,
                    upstream_id=upstream_id,
                    metadata=metadata,
                    raise_on_error=raise_on_error,
                )

            if self._rate_limiter is not None:
                try:
                    self._rate_limiter.acquire(cancellation=self._cancellation)
                except ProviderCancelledError as exc:
                    return self._terminal(
                        kind=ProviderOutcomeKind.CANCELLED,
                        status_code=None,
                        request=HttpRequest(
                            method=method, url=url, headers=sanitize_headers(headers)
                        ),
                        response_body=None,
                        error_code=exc.code,
                        message=str(exc),
                        retry_count=attempts,
                        upstream_id=upstream_id,
                        metadata=metadata,
                        raise_on_error=raise_on_error,
                    )

            request_headers = self._merge_headers(headers, conditional=cached)
            request = HttpRequest(
                method=method,
                url=url,
                headers=request_headers,
                body=body,
                timeout_seconds=self._limits.request_timeout_seconds,
            )
            attempts += 1

            try:
                response = self._transport.request(request)
            except ProviderCancelledError as exc:
                return self._terminal(
                    kind=ProviderOutcomeKind.CANCELLED,
                    status_code=None,
                    request=request,
                    response_body=None,
                    error_code=exc.code,
                    message=str(exc),
                    retry_count=attempts - 1,
                    upstream_id=upstream_id,
                    metadata=metadata,
                    raise_on_error=raise_on_error,
                )
            except Exception as exc:  # noqa: BLE001 — transport boundary
                last_kind = ProviderOutcomeKind.TRANSPORT_ERROR
                self._circuit.record_failure()
                disposition = RetryDisposition.TRANSIENT
                if attempts >= self._retry_policy.max_attempts:
                    return self._terminal(
                        kind=ProviderOutcomeKind.RETRY_BUDGET_EXHAUSTED,
                        status_code=last_status,
                        request=request,
                        response_body=None,
                        error_code="retry_budget_exhausted",
                        message=f"transport error after {attempts} attempt(s): "
                        f"{sanitize_secret_text(type(exc).__name__)}",
                        retry_count=attempts - 1,
                        upstream_id=upstream_id,
                        metadata=metadata,
                        raise_on_error=raise_on_error,
                    )
                delay = self._retry_policy.delay_seconds(
                    attempts, random_value=self._random()
                )
                self._sleep(delay)
                continue

            if len(response.body) > self._limits.max_response_bytes:
                return self._terminal(
                    kind=ProviderOutcomeKind.CLIENT_ERROR,
                    status_code=response.status_code,
                    request=request,
                    response_body=response.body[:0],
                    error_code="response_too_large",
                    message="response exceeded max_response_bytes",
                    retry_count=attempts - 1,
                    upstream_id=upstream_id,
                    metadata=metadata,
                    raise_on_error=raise_on_error,
                )

            last_status = response.status_code
            kind = classify_http_status(response.status_code)
            last_kind = kind
            disposition = self._retry_policy.classify_status(response.status_code)
            retry_after = self._retry_policy.retry_after_seconds(
                response.headers, now=self._wall_clock()
            )
            if retry_after is not None:
                retry_after_seen = retry_after

            if disposition is RetryDisposition.SUCCESS:
                self._circuit.record_success()
                cache_hit = False
                body_bytes = response.body
                effective_status = response.status_code
                effective_headers = dict(response.headers)

                if response.status_code == 304 and cached is not None:
                    cache_hit = True
                    body_bytes = cached.body
                    effective_status = cached.status_code
                    effective_headers = dict(cached.headers)
                    kind = ProviderOutcomeKind.NOT_MODIFIED

                # Store successful 200 bodies for future conditional requests.
                if (
                    enable_conditional_cache
                    and response.status_code == 200
                    and (response.header("ETag") or response.header("Last-Modified"))
                ):
                    self._cache.put(
                        cache_key,
                        ConditionalCacheEntry(
                            etag=response.header("ETag"),
                            last_modified=response.header("Last-Modified"),
                            body=response.body,
                            status_code=response.status_code,
                            headers=dict(response.headers),
                            stored_at_utc=format_utc(self._wall_clock()),
                        ),
                    )

                receipt = build_source_receipt(
                    endpoint=url,
                    status_code=effective_status,
                    request=request,
                    response_body=body_bytes,
                    upstream_id=upstream_id,
                    last_modified=effective_headers.get("Last-Modified")
                    or effective_headers.get("last-modified"),
                    cache_hit=cache_hit,
                    retry_count=attempts - 1,
                    retrieval_utc=format_utc(self._wall_clock()),
                    metadata=metadata,
                )
                payload: Any
                try:
                    payload = (
                        None
                        if not body_bytes
                        else json.loads(body_bytes.decode("utf-8"))
                    )
                except (UnicodeDecodeError, json.JSONDecodeError):
                    # Successful HTTP with non-JSON body is still returned; callers
                    # that require JSON re-validate via schema helpers.
                    payload = body_bytes

                result = ProviderResult(
                    kind=kind if response.status_code != 200 else ProviderOutcomeKind.SUCCESS,
                    status_code=effective_status,
                    receipt=receipt,
                    payload=payload,
                    cache_hit=cache_hit,
                    metadata={
                        "attempts": str(attempts),
                        **{str(k): str(v) for k, v in dict(metadata or {}).items()},
                    },
                )
                return result

            # Non-success: decide whether to retry.
            if disposition in {RetryDisposition.THROTTLED, RetryDisposition.TRANSIENT}:
                self._circuit.record_failure()
                if attempts >= self._retry_policy.max_attempts:
                    return self._terminal(
                        kind=ProviderOutcomeKind.RETRY_BUDGET_EXHAUSTED
                        if disposition is not RetryDisposition.THROTTLED
                        or attempts > 1
                        else kind,
                        status_code=response.status_code,
                        request=request,
                        response_body=response.body,
                        error_code=kind.value,
                        message=_safe_error_message(response),
                        retry_count=attempts - 1,
                        retry_after_seconds=retry_after_seen,
                        upstream_id=upstream_id,
                        metadata=metadata,
                        raise_on_error=raise_on_error,
                        prefer_kind_on_exhaustion=True,
                        last_kind=kind,
                    )
                delay = self._retry_policy.delay_seconds(
                    attempts,
                    retry_after=retry_after,
                    random_value=self._random(),
                )
                self._sleep(delay)
                continue

            # Permanent failure (401/403/404/other 4xx).
            self._circuit.record_failure()
            return self._terminal(
                kind=kind,
                status_code=response.status_code,
                request=request,
                response_body=response.body,
                error_code=kind.value,
                message=_safe_error_message(response),
                retry_count=attempts - 1,
                retry_after_seconds=retry_after_seen,
                upstream_id=upstream_id,
                metadata=metadata,
                raise_on_error=raise_on_error,
            )

        # Exhausted without returning (defensive).
        return self._terminal(
            kind=ProviderOutcomeKind.RETRY_BUDGET_EXHAUSTED,
            status_code=last_status,
            request=HttpRequest(method=method, url=url, headers=sanitize_headers(headers)),
            response_body=None,
            error_code="retry_budget_exhausted",
            message=f"retry budget exhausted after {attempts} attempt(s)",
            retry_count=max(0, attempts - 1),
            retry_after_seconds=retry_after_seen,
            upstream_id=upstream_id,
            metadata=metadata,
            raise_on_error=raise_on_error,
            last_kind=last_kind,
        )

    def _terminal(
        self,
        *,
        kind: ProviderOutcomeKind,
        status_code: int | None,
        request: HttpRequest,
        response_body: bytes | None,
        error_code: str | None,
        message: str | None,
        retry_count: int,
        upstream_id: str | None,
        metadata: Mapping[str, str] | None,
        raise_on_error: bool,
        retry_after_seconds: float | None = None,
        prefer_kind_on_exhaustion: bool = False,
        last_kind: ProviderOutcomeKind | None = None,
    ) -> ProviderResult:
        final_kind = kind
        if prefer_kind_on_exhaustion and last_kind is not None:
            # Surface the last upstream class (e.g. rate_limited) when budget ends
            # after only throttled responses; multi-attempt 5xx → budget exhausted.
            if last_kind is ProviderOutcomeKind.RATE_LIMITED and retry_count == 0:
                final_kind = ProviderOutcomeKind.RATE_LIMITED
            elif kind is not ProviderOutcomeKind.RETRY_BUDGET_EXHAUSTED:
                final_kind = kind
            else:
                final_kind = ProviderOutcomeKind.RETRY_BUDGET_EXHAUSTED

        receipt = build_source_receipt(
            endpoint=request.url,
            status_code=0 if status_code is None else status_code,
            request=request,
            response_body=response_body,
            upstream_id=upstream_id,
            cache_hit=False,
            retry_count=retry_count,
            retrieval_utc=format_utc(self._wall_clock()),
            metadata=metadata,
        )
        result = ProviderResult(
            kind=final_kind,
            status_code=status_code,
            receipt=receipt,
            payload=_safe_error_payload(response_body),
            error_code=error_code,
            message=message,
            retry_after_seconds=retry_after_seconds,
            metadata={
                "attempts": str(retry_count + 1),
                **{str(k): str(v) for k, v in dict(metadata or {}).items()},
            },
        )
        if raise_on_error and not result.ok:
            if final_kind is ProviderOutcomeKind.CANCELLED:
                raise ProviderCancelledError(message or "cancelled")
            if final_kind is ProviderOutcomeKind.CIRCUIT_OPEN:
                raise ProviderCircuitOpenError(message or "circuit open")
            if final_kind is ProviderOutcomeKind.RETRY_BUDGET_EXHAUSTED:
                raise ProviderRetryBudgetError(
                    message or "retry budget exhausted",
                    attempts=retry_count + 1,
                    last_status=status_code,
                    last_outcome=last_kind or final_kind,
                )
            raise ProviderError(message or final_kind.value, code=final_kind.value)
        return result


def _normalize_base_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise ProviderConfigError("base_url must be non-empty")
    text = url.strip().rstrip("/")
    parts = urlsplit(text)
    if parts.scheme not in {"https", "http"}:
        raise ProviderConfigError("base_url must be http(s)")
    if not parts.netloc:
        raise ProviderConfigError("base_url must include a host")
    return text


def _safe_error_message(response: HttpResponse) -> str:
    """Build a short safe message from an error response body."""

    try:
        payload = response.json()
    except ProviderMalformedError:
        return f"HTTP {response.status_code}"
    if isinstance(payload, Mapping):
        parts: list[str] = [f"HTTP {response.status_code}"]
        for key in ("error", "errorDetails", "errorDetailed", "message", "code"):
            if key in payload and payload[key] is not None:
                parts.append(sanitize_secret_text(str(payload[key]))[:160])
        return ": ".join(parts)
    return f"HTTP {response.status_code}"


def _safe_error_payload(body: bytes | None) -> Any:
    if not body:
        return None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if isinstance(payload, Mapping):
        # Drop any accidental secret-bearing fields.
        return {
            str(k): v
            for k, v in payload.items()
            if str(k).lower()
            not in {"api_key", "authorization", "token", "secret", "x-api-key"}
        }
    return payload


# ---------------------------------------------------------------------------
# Recorded fixture transport
# ---------------------------------------------------------------------------


@dataclass
class RecordedExchange:
    """One request/response pair in a compact ODP HTTP fixture recipe."""

    method: str
    path: str
    status: int
    body: Any = None
    headers: Mapping[str, str] = field(default_factory=dict)
    query: Mapping[str, str] | None = None
    match_body_sha256: str | None = None

    def matches(self, request: HttpRequest) -> bool:
        parts = urlsplit(request.url)
        if request.method.upper() != self.method.upper():
            return False
        if parts.path.rstrip("/") != self.path.rstrip("/"):
            return False
        if self.query:
            actual = dict(parse_qsl(parts.query, keep_blank_values=True))
            for key, value in self.query.items():
                if actual.get(key) != str(value):
                    return False
        if self.match_body_sha256 is not None:
            digest = sha256_hex(request.body or b"")
            if digest != self.match_body_sha256:
                return False
        return True

    def as_response(self) -> HttpResponse:
        if self.body is None:
            raw = b""
        elif isinstance(self.body, (bytes, bytearray)):
            raw = bytes(self.body)
        elif isinstance(self.body, str):
            raw = self.body.encode("utf-8")
        else:
            raw = json.dumps(self.body, separators=(",", ":"), sort_keys=True).encode(
                "utf-8"
            )
        headers = {str(k): str(v) for k, v in dict(self.headers or {}).items()}
        if raw and "Content-Type" not in {h.title() for h in headers}:
            headers.setdefault("Content-Type", "application/json")
        return HttpResponse(status_code=int(self.status), headers=headers, body=raw)


class RecordedHttpTransport:
    """Deterministic transport that replays compact recorded exchanges.

    Supports ordered multi-status sequences for the same path (e.g. 500 then
    200) by consuming matched exchanges from the front of the list.
    """

    def __init__(
        self,
        exchanges: Sequence[RecordedExchange] | None = None,
        *,
        on_request: Callable[[HttpRequest], None] | None = None,
    ) -> None:
        self._exchanges: list[RecordedExchange] = list(exchanges or [])
        self.requests: list[HttpRequest] = []
        self._on_request = on_request

    def add(self, exchange: RecordedExchange) -> None:
        self._exchanges.append(exchange)

    def extend(self, exchanges: Sequence[RecordedExchange]) -> None:
        self._exchanges.extend(exchanges)

    def request(self, request: HttpRequest) -> HttpResponse:
        # Ensure secrets never linger in stored request headers for inspection.
        self.requests.append(
            HttpRequest(
                method=request.method,
                url=request.url,
                headers=sanitize_headers(request.headers),
                body=request.body,
                timeout_seconds=request.timeout_seconds,
            )
        )
        if self._on_request is not None:
            self._on_request(request)
        for index, exchange in enumerate(self._exchanges):
            if exchange.matches(request):
                self._exchanges.pop(index)
                return exchange.as_response()
        raise ProviderError(
            f"no recorded exchange for {request.method} {sanitize_url(request.url)}",
            code="fixture_miss",
        )


def load_recorded_exchanges(recipe: Mapping[str, Any]) -> list[RecordedExchange]:
    """Load exchanges from a compact ODP HTTP fixture recipe."""

    if not isinstance(recipe, Mapping):
        raise ProviderSchemaError("fixture recipe must be a mapping", field_name="root")
    raw_list = recipe.get("exchanges") or recipe.get("cases") or []
    if isinstance(raw_list, Mapping):
        items: list[Any] = list(raw_list.values())
    elif isinstance(raw_list, Sequence) and not isinstance(raw_list, (str, bytes)):
        items = list(raw_list)
    else:
        raise ProviderSchemaError(
            "fixture exchanges must be a list or mapping", field_name="exchanges"
        )
    out: list[RecordedExchange] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise ProviderSchemaError(
                "each exchange must be a mapping", field_name="exchanges"
            )
        method = str(item.get("method") or "GET")
        path = str(item.get("path") or item.get("url_path") or "")
        if not path:
            raise ProviderSchemaError("exchange path is required", field_name="path")
        status = int(item.get("status") or item.get("status_code") or 0)
        if not status:
            raise ProviderSchemaError("exchange status is required", field_name="status")
        out.append(
            RecordedExchange(
                method=method,
                path=path,
                status=status,
                body=item.get("body", item.get("response_body")),
                headers=item.get("headers") or item.get("response_headers") or {},
                query=item.get("query"),
                match_body_sha256=item.get("match_body_sha256"),
            )
        )
    # Optional ordered sequences: expand "sequence" entries.
    for item in recipe.get("sequences") or []:
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("path") or "")
        method = str(item.get("method") or "GET")
        for step in item.get("steps") or []:
            if not isinstance(step, Mapping):
                continue
            out.append(
                RecordedExchange(
                    method=method,
                    path=path,
                    status=int(step["status"]),
                    body=step.get("body"),
                    headers=step.get("headers") or {},
                    query=item.get("query"),
                )
            )
    return out


__all__ = [
    "API_KEY_HEADER",
    "ApiKeySecret",
    "CancellationToken",
    "CircuitBreaker",
    "CircuitBreakerPolicy",
    "CircuitState",
    "ConditionalCache",
    "ConditionalCacheEntry",
    "DEFAULT_ODP_BASE_URL",
    "HttpRequest",
    "HttpResponse",
    "HttpTransport",
    "PROVIDER_BASE_SCHEMA_VERSION",
    "PageCheckpoint",
    "ProviderCancelledError",
    "ProviderCircuitOpenError",
    "ProviderConfigError",
    "ProviderError",
    "ProviderHttpClient",
    "ProviderMalformedError",
    "ProviderOutcomeKind",
    "ProviderResult",
    "ProviderRetryBudgetError",
    "ProviderSchemaDriftError",
    "ProviderSchemaError",
    "RateLimiter",
    "RatePolicy",
    "RecordedExchange",
    "RecordedHttpTransport",
    "RetryDisposition",
    "RetryPolicy",
    "TransportLimits",
    "build_source_receipt",
    "classify_http_status",
    "contains_secret_leak",
    "format_utc",
    "load_recorded_exchanges",
    "request_digest",
    "sanitize_headers",
    "sanitize_secret_text",
    "sanitize_url",
    "sha256_hex",
]
