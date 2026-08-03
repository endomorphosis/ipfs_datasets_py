"""Common live legal-source fetch and receipt layer (PATLAW-127).

Provides a bounded, allowlisted HTTPS acquisition path for official legal
sources (eCFR, GovInfo, Federal Register, USPTO guidance, U.S. Code, GPO)
with:

* conditional download (ETag / If-Modified-Since)
* pagination metadata capture
* content-type and size validation
* content-addressed bytes and immutable acquisition receipts
* local conditional cache
* Retry-After / throttle classification
* robots/terms metadata capture
* source timestamps

Network I/O occurs only when :meth:`PatentSourceTransport.acquire` (or
:meth:`request_raw`) is invoked. Importing this module performs no I/O.

Transport success is **not** source authenticity — verification stays on
authority connectors and the contracts in
:mod:`patent_authority_contracts_v2`.
"""

from __future__ import annotations

import email.utils
import hashlib
import http.client
import ipaddress
import json
import re
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import MappingProxyType
from typing import Any, Final, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ipfs_datasets_py.processors.legal_data.patent_authority_contracts_v2 import (
    AcquisitionOutcome,
    AcquisitionOutcomeKind,
    AcquisitionReceipt,
    ContentAddress,
    ParserInputEnvelope,
    content_address_bytes,
    require_acquisition_outcome,
)

SOURCE_TRANSPORT_SCHEMA_VERSION: Final = "patent.source_transport.v1"

# Official legal-source hosts from source-authority policy discovery list,
# plus common CDN aliases used by those properties.
DEFAULT_LEGAL_SOURCE_HOSTS: Final = frozenset(
    {
        "api.uspto.gov",
        "data.uspto.gov",
        "www.uspto.gov",
        "www.ecfr.gov",
        "www.federalregister.gov",
        "api.federalregister.gov",
        "api.govinfo.gov",
        "www.govinfo.gov",
        "www.gpo.gov",
        "uscode.house.gov",
    }
)
DEFAULT_ALLOWED_PORTS: Final = frozenset({443})
DEFAULT_USER_AGENT: Final = (
    "ipfs-datasets-patent-source-transport/1.0 (+https://github.com; legal-source-acquisition)"
)

_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}\.?$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.?$"
    r"|localhost$"
)
_BLOCKED_HOST_SUFFIXES: Final = (".internal", ".local", ".localhost", ".home.arpa")
_SECRET_QUERY_KEYS: Final = frozenset(
    {
        "access_token",
        "api-key",
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "key",
        "password",
        "secret",
        "signature",
        "token",
    }
)
_REDIRECT_STATUSES: Final = frozenset({301, 302, 303, 307, 308})

# Simple magic-byte hints for mislabel detection.
_MAGIC_HINTS: Final[tuple[tuple[bytes, str], ...]] = (
    (b"%PDF", "application/pdf"),
    (b"PK\x03\x04", "application/zip"),
    (b"\x1f\x8b", "application/gzip"),
    (b"<?xml", "application/xml"),
    (b"<html", "text/html"),
    (b"<!DOCTYPE html", "text/html"),
    (b"{", "application/json"),
    (b"[", "application/json"),
)

Opener = Callable[[urllib.request.Request, float], Any]
Clock = Callable[[], float]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SourceTransportError(Exception):
    """Base error for legal-source transport failures."""

    code = "source_transport_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class SourceTransportPolicyError(SourceTransportError):
    """Request rejected by host/URL policy before any network I/O."""

    code = "transport_policy_violation"


class SourceTransportTimeoutError(SourceTransportError):
    code = "transport_timeout"


class SourceTransportResponseTooLargeError(SourceTransportError):
    code = "response_too_large"


class SourceTransportNetworkError(SourceTransportError):
    code = "transport_error"


class SourceTransportCancelledError(SourceTransportError):
    code = "cancelled"


class SourceTransportConfigError(SourceTransportError):
    code = "config_error"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def endpoint_fingerprint(url: str) -> str:
    """Non-reversible short label suitable for errors and metrics."""

    digest = hashlib.sha256(
        sanitize_url(url).encode("utf-8", errors="replace")
    ).hexdigest()[:12]
    return f"endpoint:{digest}"


def sanitize_url(url: str) -> str:
    """Strip userinfo and secret-looking query parameters."""

    parts = urlsplit(str(url))
    query_pairs = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in _SECRET_QUERY_KEYS:
            query_pairs.append((key, "<redacted>"))
        else:
            query_pairs.append((key, value))
    netloc = parts.hostname or ""
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit(
        (parts.scheme, netloc, parts.path, urlencode(query_pairs), "")
    )


def sanitize_headers(headers: Mapping[str, str]) -> dict[str, str]:
    sensitive = {
        "authorization",
        "proxy-authorization",
        "x-api-key",
        "api-key",
        "cookie",
        "set-cookie",
    }
    out: dict[str, str] = {}
    for key, value in headers.items():
        if str(key).lower() in sensitive:
            out[str(key)] = "<redacted>"
        else:
            out[str(key)] = str(value)
    return out


def _safe_message(category: str, *, url: str | None = None) -> str:
    if url is None:
        return category
    return f"{category} ({endpoint_fingerprint(url)})"


def _positive_int(value: int, name: str, *, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SourceTransportConfigError(f"{name} must be a positive integer")
    if maximum is not None and value > maximum:
        raise SourceTransportConfigError(f"{name} must be <= {maximum}")
    return value


def _nonneg_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SourceTransportConfigError(f"{name} must be a non-negative integer")
    return value


def _positive_finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SourceTransportConfigError(f"{name} must be a positive finite number")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")) or result <= 0:
        raise SourceTransportConfigError(f"{name} must be a positive finite number")
    return result


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_retry_after_header(
    headers: Mapping[str, str],
    *,
    now: datetime | None = None,
    max_seconds: float = 300.0,
) -> float | None:
    """Parse ``Retry-After`` (delta-seconds or HTTP-date), capped at *max_seconds*."""

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
        current = now or _utc_now()
        delay = (target - current).total_seconds()
    if delay != delay or delay in (float("inf"), float("-inf")):
        return None
    return min(max(0.0, delay), float(max_seconds))


def header_get(headers: Mapping[str, str], name: str) -> str | None:
    target = name.lower()
    for key, value in headers.items():
        if str(key).lower() == target:
            text = str(value).strip()
            return text or None
    return None


def normalize_media_type(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).split(";", 1)[0].strip().lower()
    return text or None


def infer_media_type_from_bytes(data: bytes) -> str | None:
    """Best-effort content sniff (prefix only); never authoritative."""

    if not data:
        return None
    head = data[:64].lstrip()
    lower = head[:32].lower()
    for magic, media in _MAGIC_HINTS:
        if head.startswith(magic) or lower.startswith(magic.lower()):
            return media
    # UTF-8 text heuristic
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        return "application/octet-stream"
    if lower.startswith(b"<"):
        return "application/xml"
    return "text/plain"


def media_types_compatible(declared: str | None, inferred: str | None) -> bool:
    """Return whether declared Content-Type is compatible with sniffed bytes."""

    d = normalize_media_type(declared)
    i = normalize_media_type(inferred)
    if d is None or i is None:
        return True  # insufficient signal — do not flag mislabel
    if d == i:
        return True
    # XML family
    xmlish = {"application/xml", "text/xml", "application/xhtml+xml"}
    if d in xmlish and i in xmlish:
        return True
    if d.endswith("+xml") and i in xmlish:
        return True
    # JSON family
    if d in {"application/json", "text/json"} and i == "application/json":
        return True
    if d.endswith("+json") and i == "application/json":
        return True
    # text/* vs plain
    if d.startswith("text/") and i == "text/plain":
        return True
    # HTML declared but XML-ish sniff is still HTML-family if contains html
    if d == "text/html" and i in {"text/html", "application/xhtml+xml"}:
        return True
    return False


# ---------------------------------------------------------------------------
# Policy / limits / cancellation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LegalSourceHostPolicy:
    """URL host/scheme/port policy for SSRF-resistant legal-source reads."""

    allowed_hosts: frozenset[str] = field(
        default_factory=lambda: frozenset(DEFAULT_LEGAL_SOURCE_HOSTS)
    )
    allowed_ports: frozenset[int] = field(
        default_factory=lambda: frozenset(DEFAULT_ALLOWED_PORTS)
    )
    allow_http_loopback: bool = False
    max_url_length: int = 4_096
    require_https: bool = True

    def __post_init__(self) -> None:
        hosts = frozenset(str(host).rstrip(".").lower() for host in self.allowed_hosts)
        for host in hosts:
            if host in {"localhost", "127.0.0.1", "::1"}:
                continue
            try:
                ipaddress.ip_address(host)
            except ValueError:
                if not _HOSTNAME_RE.fullmatch(host):
                    raise SourceTransportConfigError(
                        f"allowlist contains invalid hostname: {host!r}"
                    ) from None
        ports = frozenset(int(p) for p in self.allowed_ports)
        if not ports or any(not 1 <= p <= 65_535 for p in ports):
            raise SourceTransportConfigError("allowed_ports must contain valid TCP ports")
        object.__setattr__(self, "allowed_hosts", hosts)
        object.__setattr__(self, "allowed_ports", ports)
        object.__setattr__(
            self,
            "max_url_length",
            _positive_int(self.max_url_length, "max_url_length", maximum=65_536),
        )

    @classmethod
    def legal_sources_default(cls) -> "LegalSourceHostPolicy":
        return cls()

    @classmethod
    def for_loopback_testing(
        cls,
        *,
        port: int,
        host: str = "127.0.0.1",
    ) -> "LegalSourceHostPolicy":
        return cls(
            allowed_hosts=frozenset({host, "localhost", "127.0.0.1"}),
            allowed_ports=frozenset({int(port)}),
            allow_http_loopback=True,
            require_https=False,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_http_loopback": bool(self.allow_http_loopback),
            "allowed_hosts": sorted(self.allowed_hosts),
            "allowed_ports": sorted(self.allowed_ports),
            "max_url_length": int(self.max_url_length),
            "require_https": bool(self.require_https),
        }

    def validate_url(self, url: str) -> Any:
        """Validate *url* against policy; return :func:`urlsplit` result."""

        text = str(url)
        if len(text) > self.max_url_length:
            raise SourceTransportPolicyError("url exceeds max_url_length")
        if "\x00" in text:
            raise SourceTransportPolicyError("url must not contain NUL")
        parts = urlsplit(text)
        scheme = (parts.scheme or "").lower()
        host = (parts.hostname or "").rstrip(".").lower()
        if not host:
            raise SourceTransportPolicyError("url host is required")
        if parts.username or parts.password:
            raise SourceTransportPolicyError("url userinfo is not allowed")
        for key, _ in parse_qsl(parts.query, keep_blank_values=True):
            if key.lower() in _SECRET_QUERY_KEYS:
                raise SourceTransportPolicyError(
                    "secret-bearing query parameters are not allowed"
                )
        for suffix in _BLOCKED_HOST_SUFFIXES:
            if host.endswith(suffix) and host not in {"localhost"}:
                raise SourceTransportPolicyError(
                    f"blocked host suffix: {suffix}"
                )

        is_loopback = False
        try:
            ip = ipaddress.ip_address(host)
            is_loopback = ip.is_loopback
        except ValueError:
            is_loopback = host in {"localhost"}

        if scheme == "https":
            port = parts.port or 443
        elif scheme == "http":
            if not (self.allow_http_loopback and is_loopback):
                raise SourceTransportPolicyError(
                    "http is only permitted for explicit loopback testing"
                )
            port = parts.port or 80
        else:
            raise SourceTransportPolicyError(
                f"unsupported url scheme: {scheme!r}"
            )

        if self.require_https and scheme != "https" and not (
            self.allow_http_loopback and is_loopback
        ):
            raise SourceTransportPolicyError("https is required")

        if host not in self.allowed_hosts and not (
            is_loopback and self.allow_http_loopback and host in self.allowed_hosts
        ):
            # Standard path: host must be allowlisted.
            if host not in self.allowed_hosts:
                raise SourceTransportPolicyError(
                    f"host not on legal-source allowlist: {host!r}"
                )

        if port not in self.allowed_ports:
            raise SourceTransportPolicyError(
                f"port {port} not permitted by policy"
            )
        return parts


@dataclass(frozen=True, slots=True)
class LegalSourceTransportLimits:
    """Finite safety budgets enforced at the raw HTTP boundary."""

    max_response_bytes: int = 32 * 1024 * 1024
    max_request_bytes: int = 1 * 1024 * 1024
    max_header_bytes: int = 64 * 1024
    request_timeout_seconds: float = 30.0
    max_redirects: int = 0
    max_retry_after_seconds: float = 300.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_response_bytes",
            _positive_int(self.max_response_bytes, "max_response_bytes"),
        )
        object.__setattr__(
            self,
            "max_request_bytes",
            _positive_int(self.max_request_bytes, "max_request_bytes"),
        )
        object.__setattr__(
            self,
            "max_header_bytes",
            _positive_int(self.max_header_bytes, "max_header_bytes"),
        )
        object.__setattr__(
            self,
            "request_timeout_seconds",
            _positive_finite(
                self.request_timeout_seconds, "request_timeout_seconds"
            ),
        )
        object.__setattr__(
            self, "max_redirects", _nonneg_int(self.max_redirects, "max_redirects")
        )
        object.__setattr__(
            self,
            "max_retry_after_seconds",
            _positive_finite(
                self.max_retry_after_seconds, "max_retry_after_seconds"
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_header_bytes": self.max_header_bytes,
            "max_redirects": self.max_redirects,
            "max_request_bytes": self.max_request_bytes,
            "max_response_bytes": self.max_response_bytes,
            "max_retry_after_seconds": self.max_retry_after_seconds,
            "request_timeout_seconds": self.request_timeout_seconds,
        }


@dataclass
class CancellationToken:
    """Cooperative cancellation flag checked before/around network I/O."""

    cancelled: bool = False
    reason: str = ""

    def cancel(self, reason: str = "cancelled") -> None:
        self.cancelled = True
        self.reason = str(reason or "cancelled")

    def check(self) -> None:
        if self.cancelled:
            raise SourceTransportCancelledError(
                self.reason or "cancelled", code="cancelled"
            )


# ---------------------------------------------------------------------------
# Conditional cache
# ---------------------------------------------------------------------------


@dataclass
class _CacheEntry:
    body: bytes
    content: ContentAddress
    etag: str | None
    last_modified: str | None
    media_type: str | None
    source_timestamp: str | None
    stored_at: datetime
    response_headers: dict[str, str]


class ConditionalByteCache:
    """In-memory ETag / Last-Modified cache for conditional revalidation."""

    def __init__(self) -> None:
        self._entries: dict[str, _CacheEntry] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        self._entries.clear()

    def get(self, cache_key: str) -> _CacheEntry | None:
        return self._entries.get(cache_key)

    def put(
        self,
        cache_key: str,
        *,
        body: bytes,
        content: ContentAddress,
        etag: str | None,
        last_modified: str | None,
        media_type: str | None,
        source_timestamp: str | None,
        response_headers: Mapping[str, str],
        stored_at: datetime | None = None,
    ) -> None:
        self._entries[cache_key] = _CacheEntry(
            body=bytes(body),
            content=content,
            etag=etag,
            last_modified=last_modified,
            media_type=media_type,
            source_timestamp=source_timestamp,
            stored_at=stored_at or _utc_now(),
            response_headers={str(k): str(v) for k, v in response_headers.items()},
        )

    def conditional_headers(self, cache_key: str) -> dict[str, str]:
        entry = self._entries.get(cache_key)
        if entry is None:
            return {}
        headers: dict[str, str] = {}
        if entry.etag:
            headers["If-None-Match"] = entry.etag
        if entry.last_modified:
            headers["If-Modified-Since"] = entry.last_modified
        return headers


def cache_key_for_url(url: str) -> str:
    return f"sha256:{hashlib.sha256(sanitize_url(url).encode('utf-8')).hexdigest()}"


# ---------------------------------------------------------------------------
# Request / raw response
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceFetchRequest:
    """One explicit legal-source fetch request (network only when executed)."""

    url: str
    method: str = "GET"
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes | None = None
    timeout_seconds: float | None = None
    expected_media_types: tuple[str, ...] = ()
    page_token: str | None = None
    page_index: int | None = None
    enable_conditional: bool = True
    cache_key: str | None = None
    robots_metadata: Mapping[str, Any] = field(default_factory=dict)
    terms_metadata: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "url", str(self.url))
        method = str(self.method or "GET").upper()
        if method not in {"GET", "HEAD", "POST"}:
            raise SourceTransportConfigError(f"unsupported method: {method}")
        object.__setattr__(self, "method", method)
        object.__setattr__(
            self,
            "headers",
            MappingProxyType({str(k): str(v) for k, v in dict(self.headers).items()}),
        )
        if self.body is not None:
            object.__setattr__(self, "body", bytes(self.body))
        if self.expected_media_types:
            object.__setattr__(
                self,
                "expected_media_types",
                tuple(
                    normalize_media_type(m) or m for m in self.expected_media_types if m
                ),
            )
        object.__setattr__(
            self,
            "robots_metadata",
            MappingProxyType(dict(self.robots_metadata)),
        )
        object.__setattr__(
            self, "terms_metadata", MappingProxyType(dict(self.terms_metadata))
        )
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def sanitized_dict(self) -> dict[str, Any]:
        return {
            "body_bytes": 0 if self.body is None else len(self.body),
            "cache_key": self.cache_key,
            "enable_conditional": bool(self.enable_conditional),
            "expected_media_types": list(self.expected_media_types),
            "headers": sanitize_headers(self.headers),
            "method": self.method,
            "page_index": self.page_index,
            "page_token": self.page_token,
            "timeout_seconds": self.timeout_seconds,
            "url": sanitize_url(self.url),
        }


@dataclass(frozen=True, slots=True)
class RawHttpResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes
    elapsed_seconds: float

    def header(self, name: str) -> str | None:
        return header_get(self.headers, name)


# ---------------------------------------------------------------------------
# Transport implementation
# ---------------------------------------------------------------------------


def _default_opener(
    prepared: urllib.request.Request, timeout: float
) -> http.client.HTTPResponse:
    opener = urllib.request.build_opener(urllib.request.HTTPHandler)
    return opener.open(prepared, timeout=timeout)  # type: ignore[no-any-return]


def _read_bounded(stream: Any, max_bytes: int) -> bytes:
    """Read up to *max_bytes*; preserve partial bytes on incomplete transfer."""

    chunks: list[bytes] = []
    total = 0
    budget = max_bytes + 1
    while total < budget:
        to_read = min(65_536, budget - total)
        try:
            chunk = stream.read(to_read)
        except http.client.IncompleteRead as exc:
            # Upstream closed after advertising a larger Content-Length.
            partial = bytes(exc.partial or b"")
            if partial:
                chunks.append(partial)
            break
        except Exception as exc:  # noqa: BLE001
            # Some urllib paths surface IncompleteRead wrapped or as ValueError.
            partial = getattr(exc, "partial", None)
            if partial:
                chunks.append(bytes(partial))
                break
            raise SourceTransportNetworkError(
                f"response read failed: {type(exc).__name__}"
            ) from None
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    body = b"".join(chunks)
    if len(body) > max_bytes:
        raise SourceTransportResponseTooLargeError(
            f"response exceeded max_response_bytes ({max_bytes})"
        )
    return body


class PatentSourceTransport:
    """Bounded legal-source HTTP transport with acquisition receipts.

    Parameters
    ----------
    policy:
        Host allowlist (defaults to official legal-source hosts).
    limits:
        Response size / timeout budgets.
    opener:
        Injected callable for tests; production uses stdlib urllib.
    cache:
        Optional conditional byte cache.
    cancellation:
        Cooperative cancellation token.
    network_enabled:
        When ``False`` (default), :meth:`acquire` refuses live network unless
        an injected *opener* is provided. Set ``True`` for intentional live
        acquisition. Fake-server tests inject an opener or set this true with
        loopback policy.
    """

    __slots__ = (
        "_cache",
        "_cancellation",
        "_clock",
        "_default_headers",
        "_limits",
        "_network_enabled",
        "_opener",
        "_policy",
        "_request_count",
        "_user_agent",
        "_wall_clock",
    )

    def __init__(
        self,
        *,
        policy: LegalSourceHostPolicy | None = None,
        limits: LegalSourceTransportLimits | None = None,
        opener: Opener | None = None,
        cache: ConditionalByteCache | None = None,
        cancellation: CancellationToken | None = None,
        default_headers: Mapping[str, str] | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        network_enabled: bool = False,
        clock: Clock | None = None,
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._policy = policy or LegalSourceHostPolicy.legal_sources_default()
        self._limits = limits or LegalSourceTransportLimits()
        self._opener = opener
        self._cache = cache if cache is not None else ConditionalByteCache()
        self._cancellation = cancellation
        self._default_headers = {
            str(k): str(v) for k, v in dict(default_headers or {}).items()
        }
        self._user_agent = str(user_agent or DEFAULT_USER_AGENT)[:256]
        self._network_enabled = bool(network_enabled)
        self._clock = clock or time.monotonic
        self._wall_clock = wall_clock or _utc_now
        self._request_count = 0

    @property
    def policy(self) -> LegalSourceHostPolicy:
        return self._policy

    @property
    def limits(self) -> LegalSourceTransportLimits:
        return self._limits

    @property
    def cache(self) -> ConditionalByteCache:
        return self._cache

    @property
    def request_count(self) -> int:
        return self._request_count

    @property
    def network_enabled(self) -> bool:
        return self._network_enabled

    def safe_config(self) -> dict[str, Any]:
        return {
            "cache_entries": len(self._cache),
            "default_headers": sanitize_headers(self._default_headers),
            "limits": self._limits.to_dict(),
            "network_enabled": bool(self._network_enabled),
            "opener_injected": self._opener is not None,
            "policy": self._policy.to_dict(),
            "request_count": self._request_count,
            "schema_version": SOURCE_TRANSPORT_SCHEMA_VERSION,
            "user_agent": self._user_agent,
        }

    def _check_cancellation(self) -> None:
        if self._cancellation is not None:
            self._cancellation.check()

    def _resolve_opener(self) -> Opener:
        if self._opener is not None:
            return self._opener
        if not self._network_enabled:
            raise SourceTransportPolicyError(
                "network use is disabled; set network_enabled=True for live "
                "acquisition or inject a test opener"
            )
        return _default_opener

    def request_raw(self, request: SourceFetchRequest) -> RawHttpResponse:
        """Execute one HTTP request under policy; return bounded raw response.

        This is the explicit network boundary. Prefer :meth:`acquire` which
        classifies outcomes and emits content-addressed receipts.
        """

        if not isinstance(request, SourceFetchRequest):
            raise SourceTransportConfigError("request must be SourceFetchRequest")
        self._check_cancellation()
        self._policy.validate_url(request.url)

        body = request.body
        if body is not None and len(body) > self._limits.max_request_bytes:
            raise SourceTransportPolicyError("request body exceeds max_request_bytes")

        headers = dict(self._default_headers)
        headers.setdefault("User-Agent", self._user_agent)
        headers.setdefault("Accept", "*/*")
        for key, value in request.headers.items():
            headers[str(key)] = str(value)

        header_bytes = sum(len(k) + len(v) for k, v in headers.items())
        if header_bytes > self._limits.max_header_bytes:
            raise SourceTransportPolicyError("request headers exceed max_header_bytes")

        timeout = (
            request.timeout_seconds
            if request.timeout_seconds is not None
            else self._limits.request_timeout_seconds
        )
        timeout = _positive_finite(timeout, "timeout_seconds")

        prepared = urllib.request.Request(
            url=request.url,
            data=body,
            headers=headers,
            method=request.method,
        )
        opener = self._resolve_opener()
        self._request_count += 1
        started = self._clock()
        response_obj: Any = None
        try:
            self._check_cancellation()
            try:
                response_obj = opener(prepared, timeout)
            except SourceTransportCancelledError:
                raise
            except socket.timeout:
                raise SourceTransportTimeoutError(
                    _safe_message("request timed out", url=request.url)
                ) from None
            except TimeoutError:
                raise SourceTransportTimeoutError(
                    _safe_message("request timed out", url=request.url)
                ) from None
            except urllib.error.HTTPError as http_err:
                response_obj = http_err
            except urllib.error.URLError as url_err:
                reason = url_err.reason
                if isinstance(reason, socket.timeout) or "timed out" in str(
                    reason
                ).lower():
                    raise SourceTransportTimeoutError(
                        _safe_message("request timed out", url=request.url)
                    ) from None
                raise SourceTransportNetworkError(
                    _safe_message(
                        f"network error: {type(reason).__name__ if reason else 'URLError'}",
                        url=request.url,
                    )
                ) from None
            except (ConnectionError, OSError) as exc:
                if "timed out" in str(exc).lower():
                    raise SourceTransportTimeoutError(
                        _safe_message("request timed out", url=request.url)
                    ) from None
                raise SourceTransportNetworkError(
                    _safe_message(
                        f"network error: {type(exc).__name__}", url=request.url
                    )
                ) from None

            self._check_cancellation()
            status = int(
                getattr(response_obj, "status", None) or response_obj.getcode()
            )
            raw_headers: dict[str, str] = {}
            header_bag = getattr(response_obj, "headers", None)
            if header_bag is not None:
                try:
                    raw_headers = {str(k): str(v) for k, v in header_bag.items()}
                except Exception:  # noqa: BLE001
                    raw_headers = {}

            if status in _REDIRECT_STATUSES and self._limits.max_redirects <= 0:
                body_bytes = _read_bounded(
                    response_obj, self._limits.max_response_bytes
                )
            else:
                body_bytes = _read_bounded(
                    response_obj, self._limits.max_response_bytes
                )

            elapsed = max(0.0, float(self._clock() - started))
            return RawHttpResponse(
                status_code=status,
                headers=MappingProxyType(raw_headers),
                body=body_bytes,
                elapsed_seconds=elapsed,
            )
        finally:
            if response_obj is not None:
                try:
                    response_obj.close()
                except Exception:  # noqa: BLE001
                    pass

    def acquire(self, request: SourceFetchRequest) -> AcquisitionOutcome:
        """Fetch *request* and return a content-addressed acquisition outcome.

        Classifies unchanged (304 / cache), changed, truncated, mislabeled,
        throttled, unavailable, and transport failures without raising for
        ordinary HTTP outcomes. Policy/timeout/size errors still raise when
        they occur before a classifiable response, except size overflow which
        is also available as an outcome when preferred by callers via
        :meth:`acquire_catching`.
        """

        return self._acquire_impl(request, catch_transport_errors=False)

    def acquire_catching(self, request: SourceFetchRequest) -> AcquisitionOutcome:
        """Like :meth:`acquire` but maps transport exceptions to outcomes."""

        return self._acquire_impl(request, catch_transport_errors=True)

    def _acquire_impl(
        self,
        request: SourceFetchRequest,
        *,
        catch_transport_errors: bool,
    ) -> AcquisitionOutcome:
        if not isinstance(request, SourceFetchRequest):
            raise SourceTransportConfigError("request must be SourceFetchRequest")

        retrieved_at = self._wall_clock()
        if retrieved_at.tzinfo is None:
            retrieved_at = retrieved_at.replace(tzinfo=timezone.utc)

        key = request.cache_key or cache_key_for_url(request.url)
        headers = dict(request.headers)
        conditional = False
        prior = self._cache.get(key) if request.enable_conditional else None
        if prior is not None and request.enable_conditional:
            cond = self._cache.conditional_headers(key)
            for hk, hv in cond.items():
                headers.setdefault(hk, hv)
            conditional = bool(cond)

        fetch_request = SourceFetchRequest(
            url=request.url,
            method=request.method,
            headers=headers,
            body=request.body,
            timeout_seconds=request.timeout_seconds,
            expected_media_types=request.expected_media_types,
            page_token=request.page_token,
            page_index=request.page_index,
            enable_conditional=request.enable_conditional,
            cache_key=key,
            robots_metadata=dict(request.robots_metadata),
            terms_metadata=dict(request.terms_metadata),
            metadata=dict(request.metadata),
        )

        network_used = False
        try:
            raw = self.request_raw(fetch_request)
            network_used = True
        except SourceTransportCancelledError as exc:
            if not catch_transport_errors:
                raise
            return self._error_outcome(
                fetch_request,
                retrieved_at=retrieved_at,
                kind=AcquisitionOutcomeKind.CANCELLED,
                status=0,
                error_code=exc.code,
                error_message=str(exc),
                network_used=False,
                conditional=conditional,
            )
        except SourceTransportPolicyError as exc:
            if not catch_transport_errors:
                raise
            return self._error_outcome(
                fetch_request,
                retrieved_at=retrieved_at,
                kind=AcquisitionOutcomeKind.POLICY_REJECTED,
                status=0,
                error_code=exc.code,
                error_message=str(exc),
                network_used=False,
                conditional=conditional,
            )
        except SourceTransportTimeoutError as exc:
            if not catch_transport_errors:
                raise
            return self._error_outcome(
                fetch_request,
                retrieved_at=retrieved_at,
                kind=AcquisitionOutcomeKind.TIMEOUT,
                status=0,
                error_code=exc.code,
                error_message=str(exc),
                network_used=True,
                conditional=conditional,
            )
        except SourceTransportResponseTooLargeError as exc:
            if not catch_transport_errors:
                raise
            return self._error_outcome(
                fetch_request,
                retrieved_at=retrieved_at,
                kind=AcquisitionOutcomeKind.SIZE_EXCEEDED,
                status=0,
                error_code=exc.code,
                error_message=str(exc),
                network_used=True,
                conditional=conditional,
            )
        except SourceTransportNetworkError as exc:
            if not catch_transport_errors:
                raise
            return self._error_outcome(
                fetch_request,
                retrieved_at=retrieved_at,
                kind=AcquisitionOutcomeKind.NETWORK_ERROR,
                status=0,
                error_code=exc.code,
                error_message=str(exc),
                network_used=True,
                conditional=conditional,
            )

        return self._classify_response(
            fetch_request,
            raw=raw,
            retrieved_at=retrieved_at,
            cache_key=key,
            prior=prior,
            conditional=conditional,
            network_used=network_used,
        )

    def _error_outcome(
        self,
        request: SourceFetchRequest,
        *,
        retrieved_at: datetime,
        kind: AcquisitionOutcomeKind,
        status: int,
        error_code: str,
        error_message: str,
        network_used: bool,
        conditional: bool,
    ) -> AcquisitionOutcome:
        receipt = AcquisitionReceipt(
            endpoint=sanitize_url(request.url),
            retrieved_at=retrieved_at,
            outcome_kind=kind,
            response_status=status,
            sanitized_request=request.sanitized_dict(),
            conditional_request=conditional,
            robots_metadata=dict(request.robots_metadata),
            terms_metadata=dict(request.terms_metadata),
            pagination=_pagination_meta(request),
            error_code=error_code,
            error_message=error_message,
            metadata=dict(request.metadata),
        )
        return AcquisitionOutcome(
            kind=kind, receipt=receipt, body=None, network_used=network_used
        )

    def _classify_response(
        self,
        request: SourceFetchRequest,
        *,
        raw: RawHttpResponse,
        retrieved_at: datetime,
        cache_key: str,
        prior: _CacheEntry | None,
        conditional: bool,
        network_used: bool,
    ) -> AcquisitionOutcome:
        status = int(raw.status_code)
        headers = dict(raw.headers)
        etag = header_get(headers, "ETag")
        last_modified = header_get(headers, "Last-Modified")
        source_timestamp = (
            header_get(headers, "X-Source-Timestamp")
            or header_get(headers, "X-Timestamp")
            or last_modified
        )
        declared_media = normalize_media_type(header_get(headers, "Content-Type"))
        declared_length = _parse_content_length(headers)
        retry_after = parse_retry_after_header(
            headers, max_seconds=self._limits.max_retry_after_seconds
        )
        body = bytes(raw.body)

        # --- Throttled ---
        if status == 429:
            receipt = AcquisitionReceipt(
                endpoint=sanitize_url(request.url),
                retrieved_at=retrieved_at,
                outcome_kind=AcquisitionOutcomeKind.THROTTLED,
                response_status=status,
                sanitized_request=request.sanitized_dict(),
                etag=etag,
                upstream_last_modified=last_modified,
                source_timestamp=source_timestamp,
                media_type=declared_media,
                declared_media_type=declared_media,
                declared_content_length=declared_length,
                retry_after_seconds=retry_after,
                conditional_request=conditional,
                robots_metadata=dict(request.robots_metadata),
                terms_metadata=dict(request.terms_metadata),
                pagination=_pagination_meta(request, headers),
                error_code="throttled",
                error_message="source returned 429 Too Many Requests",
                metadata=dict(request.metadata),
            )
            return AcquisitionOutcome(
                kind=AcquisitionOutcomeKind.THROTTLED,
                receipt=receipt,
                body=None,
                network_used=network_used,
            )

        # --- Unavailable ---
        if status in {404, 410, 502, 503, 504} or status >= 500:
            receipt = AcquisitionReceipt(
                endpoint=sanitize_url(request.url),
                retrieved_at=retrieved_at,
                outcome_kind=AcquisitionOutcomeKind.UNAVAILABLE,
                response_status=status,
                sanitized_request=request.sanitized_dict(),
                etag=etag,
                upstream_last_modified=last_modified,
                source_timestamp=source_timestamp,
                media_type=declared_media,
                declared_media_type=declared_media,
                declared_content_length=declared_length,
                retry_after_seconds=retry_after,
                conditional_request=conditional,
                robots_metadata=dict(request.robots_metadata),
                terms_metadata=dict(request.terms_metadata),
                pagination=_pagination_meta(request, headers),
                error_code="unavailable",
                error_message=f"source unavailable with HTTP {status}",
                metadata=dict(request.metadata),
            )
            return AcquisitionOutcome(
                kind=AcquisitionOutcomeKind.UNAVAILABLE,
                receipt=receipt,
                body=None,
                network_used=network_used,
            )

        # --- Unchanged (304) ---
        if status == 304:
            if prior is None:
                receipt = AcquisitionReceipt(
                    endpoint=sanitize_url(request.url),
                    retrieved_at=retrieved_at,
                    outcome_kind=AcquisitionOutcomeKind.UNCHANGED,
                    response_status=status,
                    sanitized_request=request.sanitized_dict(),
                    etag=etag,
                    upstream_last_modified=last_modified,
                    source_timestamp=source_timestamp or last_modified,
                    conditional_request=conditional,
                    cache_hit=False,
                    robots_metadata=dict(request.robots_metadata),
                    terms_metadata=dict(request.terms_metadata),
                    pagination=_pagination_meta(request, headers),
                    error_code="unchanged_without_cache",
                    error_message="304 received but no cached body available",
                    metadata=dict(request.metadata),
                )
                return AcquisitionOutcome(
                    kind=AcquisitionOutcomeKind.UNCHANGED,
                    receipt=receipt,
                    body=None,
                    network_used=network_used,
                )
            receipt = AcquisitionReceipt(
                endpoint=sanitize_url(request.url),
                retrieved_at=retrieved_at,
                outcome_kind=AcquisitionOutcomeKind.UNCHANGED,
                response_status=status,
                sanitized_request=request.sanitized_dict(),
                content=prior.content,
                etag=etag or prior.etag,
                upstream_last_modified=last_modified or prior.last_modified,
                source_timestamp=source_timestamp or prior.source_timestamp,
                media_type=prior.media_type,
                declared_media_type=declared_media or prior.media_type,
                declared_content_length=declared_length,
                conditional_request=conditional,
                cache_hit=True,
                robots_metadata=dict(request.robots_metadata),
                terms_metadata=dict(request.terms_metadata),
                pagination=_pagination_meta(request, headers),
                metadata=dict(request.metadata),
            )
            return AcquisitionOutcome(
                kind=AcquisitionOutcomeKind.UNCHANGED,
                receipt=receipt,
                body=prior.body,
                network_used=network_used,
            )

        # Non-success client errors (other than handled above).
        if status < 200 or status >= 300:
            if status in {401, 403}:
                kind = AcquisitionOutcomeKind.UNAVAILABLE
                code = "forbidden" if status == 403 else "unauthorized"
            else:
                kind = AcquisitionOutcomeKind.UNAVAILABLE
                code = f"http_{status}"
            receipt = AcquisitionReceipt(
                endpoint=sanitize_url(request.url),
                retrieved_at=retrieved_at,
                outcome_kind=kind,
                response_status=status,
                sanitized_request=request.sanitized_dict(),
                etag=etag,
                upstream_last_modified=last_modified,
                source_timestamp=source_timestamp,
                media_type=declared_media,
                declared_media_type=declared_media,
                declared_content_length=declared_length,
                conditional_request=conditional,
                robots_metadata=dict(request.robots_metadata),
                terms_metadata=dict(request.terms_metadata),
                pagination=_pagination_meta(request, headers),
                error_code=code,
                error_message=f"source returned HTTP {status}",
                metadata=dict(request.metadata),
            )
            return AcquisitionOutcome(
                kind=kind, receipt=receipt, body=None, network_used=network_used
            )

        # --- Truncated: declared Content-Length exceeds actual body ---
        if declared_length is not None and len(body) < declared_length:
            content = content_address_bytes(body)
            receipt = AcquisitionReceipt(
                endpoint=sanitize_url(request.url),
                retrieved_at=retrieved_at,
                outcome_kind=AcquisitionOutcomeKind.TRUNCATED,
                response_status=status,
                sanitized_request=request.sanitized_dict(),
                content=content,
                etag=etag,
                upstream_last_modified=last_modified,
                source_timestamp=source_timestamp,
                media_type=declared_media,
                declared_media_type=declared_media,
                declared_content_length=declared_length,
                conditional_request=conditional,
                robots_metadata=dict(request.robots_metadata),
                terms_metadata=dict(request.terms_metadata),
                pagination=_pagination_meta(request, headers),
                error_code="truncated",
                error_message=(
                    f"body length {len(body)} < Content-Length {declared_length}"
                ),
                metadata=dict(request.metadata),
            )
            return AcquisitionOutcome(
                kind=AcquisitionOutcomeKind.TRUNCATED,
                receipt=receipt,
                body=body,
                network_used=network_used,
            )

        # --- Mislabeled content-type ---
        inferred = infer_media_type_from_bytes(body)
        mislabeled = False
        if declared_media and not media_types_compatible(declared_media, inferred):
            mislabeled = True
        if request.expected_media_types and declared_media:
            expected_norm = {
                normalize_media_type(m) for m in request.expected_media_types
            }
            if declared_media not in expected_norm and not any(
                media_types_compatible(declared_media, e) for e in expected_norm if e
            ):
                # Declared type not in expected set — still check body.
                if inferred and inferred not in expected_norm:
                    mislabeled = True
        if request.expected_media_types and inferred:
            expected_norm = {
                normalize_media_type(m) for m in request.expected_media_types
            }
            if inferred not in expected_norm and not any(
                media_types_compatible(e, inferred) for e in expected_norm if e
            ):
                if declared_media and not media_types_compatible(
                    declared_media, inferred
                ):
                    mislabeled = True
                elif declared_media is None:
                    mislabeled = True

        content = content_address_bytes(body)
        effective_media = declared_media or inferred

        if mislabeled:
            receipt = AcquisitionReceipt(
                endpoint=sanitize_url(request.url),
                retrieved_at=retrieved_at,
                outcome_kind=AcquisitionOutcomeKind.MISLABELED,
                response_status=status,
                sanitized_request=request.sanitized_dict(),
                content=content,
                etag=etag,
                upstream_last_modified=last_modified,
                source_timestamp=source_timestamp,
                media_type=effective_media,
                declared_media_type=declared_media,
                declared_content_length=declared_length,
                conditional_request=conditional,
                robots_metadata=dict(request.robots_metadata),
                terms_metadata=dict(request.terms_metadata),
                pagination=_pagination_meta(request, headers),
                error_code="mislabeled",
                error_message=(
                    f"declared media type {declared_media!r} incompatible with "
                    f"inferred {inferred!r}"
                ),
                metadata={
                    **dict(request.metadata),
                    "inferred_media_type": inferred,
                },
            )
            return AcquisitionOutcome(
                kind=AcquisitionOutcomeKind.MISLABELED,
                receipt=receipt,
                body=body,
                network_used=network_used,
            )

        # --- Changed vs first fetch ---
        changed = False
        if prior is not None and prior.content.sha256 != content.sha256:
            changed = True

        kind = (
            AcquisitionOutcomeKind.CHANGED
            if changed
            else AcquisitionOutcomeKind.FETCHED
        )

        # Update cache on successful body.
        self._cache.put(
            cache_key,
            body=body,
            content=content,
            etag=etag,
            last_modified=last_modified,
            media_type=effective_media,
            source_timestamp=source_timestamp,
            response_headers=headers,
            stored_at=retrieved_at,
        )

        receipt = AcquisitionReceipt(
            endpoint=sanitize_url(request.url),
            retrieved_at=retrieved_at,
            outcome_kind=kind,
            response_status=status,
            sanitized_request=request.sanitized_dict(),
            content=content,
            etag=etag,
            upstream_last_modified=last_modified,
            source_timestamp=source_timestamp,
            media_type=effective_media,
            declared_media_type=declared_media,
            declared_content_length=declared_length,
            conditional_request=conditional,
            cache_hit=False,
            robots_metadata=dict(request.robots_metadata),
            terms_metadata=dict(request.terms_metadata),
            pagination=_pagination_meta(request, headers),
            metadata=dict(request.metadata),
        )
        return AcquisitionOutcome(
            kind=kind, receipt=receipt, body=body, network_used=network_used
        )

    def admit_to_parser(
        self,
        outcome: AcquisitionOutcome | None,
        *,
        parser_name: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ParserInputEnvelope:
        """Gate parser admission on a successful acquisition outcome."""

        require_acquisition_outcome(outcome)
        assert outcome is not None
        return ParserInputEnvelope.admit(
            outcome, parser_name=parser_name, metadata=metadata
        )


def _parse_content_length(headers: Mapping[str, str]) -> int | None:
    raw = header_get(headers, "Content-Length")
    if raw is None:
        return None
    try:
        value = int(str(raw).strip())
    except ValueError:
        return None
    if value < 0:
        return None
    return value


def _pagination_meta(
    request: SourceFetchRequest,
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    if request.page_token is not None:
        meta["page_token"] = request.page_token
    if request.page_index is not None:
        meta["page_index"] = request.page_index
    if headers is not None:
        for key in ("Link", "X-Next-Page", "X-Page", "X-Total-Count"):
            value = header_get(headers, key)
            if value is not None:
                meta[key.lower().replace("-", "_")] = value
    return meta


# ---------------------------------------------------------------------------
# Test doubles: scripted opener + fake server
# ---------------------------------------------------------------------------


class ScriptedOpener:
    """Deterministic opener for offline unit tests (no real sockets)."""

    def __init__(self, outcomes: Sequence[Any] | None = None) -> None:
        self._outcomes: list[Any] = list(outcomes or [])
        self.requests: list[urllib.request.Request] = []

    def add(
        self,
        *,
        status: int = 200,
        body: bytes | str | dict[str, Any] = b"{}",
        headers: Mapping[str, str] | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        if isinstance(body, dict):
            raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode(
                "utf-8"
            )
        elif isinstance(body, str):
            raw = body.encode("utf-8")
        else:
            raw = bytes(body)
        self._outcomes.append(
            {
                "status": int(status),
                "body": raw,
                "headers": {str(k): str(v) for k, v in dict(headers or {}).items()},
                "delay_seconds": float(delay_seconds),
            }
        )

    def add_error(self, exc: BaseException) -> None:
        self._outcomes.append(exc)

    def __call__(self, prepared: urllib.request.Request, timeout: float) -> Any:
        self.requests.append(prepared)
        if not self._outcomes:
            raise SourceTransportNetworkError("scripted opener exhausted")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        delay = float(outcome.get("delay_seconds") or 0.0)
        if delay > 0:
            # Honour timeout for scripted delays.
            if delay > float(timeout):
                raise socket.timeout("scripted delay exceeded timeout")
            time.sleep(min(delay, 0.05))  # keep unit tests fast
        return _ScriptedResponse(
            status=int(outcome["status"]),
            body=bytes(outcome["body"]),
            headers=dict(outcome.get("headers") or {}),
        )


class _ScriptedResponse:
    def __init__(
        self,
        *,
        status: int,
        body: bytes,
        headers: Mapping[str, str],
    ) -> None:
        self.status = int(status)
        self._body = bytes(body)
        self._offset = 0
        self.headers = {str(k): str(v) for k, v in headers.items()}

    def getcode(self) -> int:
        return self.status

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            chunk = self._body[self._offset :]
            self._offset = len(self._body)
            return chunk
        chunk = self._body[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def close(self) -> None:
        return None


class FakeLegalSourceServer:
    """Threading HTTP server for loopback legal-source transport tests.

    Supports sequences for changed bodies, forced truncation (declared
    Content-Length larger than payload), mislabeled Content-Type, throttle
    (429 + Retry-After), unavailable (404/503), and conditional 304.
    """

    def __init__(
        self,
        routes: Mapping[str, Mapping[str, Any]] | None = None,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        self._routes: dict[str, dict[str, Any]] = {
            str(k): dict(v) for k, v in dict(routes or {}).items()
        }
        self._hit_counts: dict[str, int] = {}
        self.received_headers: list[dict[str, str]] = []
        self.received_paths: list[str] = []
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                return

            def _handle(self) -> None:
                path = self.path.split("?", 1)[0]
                parent.received_paths.append(self.path)
                parent.received_headers.append(
                    {k: v for k, v in self.headers.items()}
                )
                route = parent._routes.get(path) or parent._routes.get(self.path)
                if route is None:
                    self.send_response(404)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"error":"not_found"}')
                    return

                parent._hit_counts[path] = parent._hit_counts.get(path, 0) + 1
                sequence = route.get("sequence")
                if sequence:
                    idx = min(
                        parent._hit_counts[path] - 1,
                        len(sequence) - 1,
                    )
                    step = sequence[idx]
                    status = int(step.get("status", 200))
                    body = step.get("body", b"{}")
                    headers = dict(step.get("headers") or {})
                    truncate = bool(step.get("truncate", False))
                    declared_length = step.get("declared_content_length")
                else:
                    status = int(route.get("status", 200))
                    body = route.get("body", b"{}")
                    headers = dict(route.get("headers") or {})
                    truncate = bool(route.get("truncate", False))
                    declared_length = route.get("declared_content_length")

                etag = headers.get("ETag") or headers.get("Etag")
                if_none = self.headers.get("If-None-Match")
                if status == 200 and etag and if_none and if_none == etag:
                    status = 304
                    body = b""

                if isinstance(body, dict):
                    raw = json.dumps(
                        body, separators=(",", ":"), sort_keys=True
                    ).encode("utf-8")
                elif isinstance(body, str):
                    raw = body.encode("utf-8")
                else:
                    raw = bytes(body)

                delay = float(route.get("delay_seconds") or 0.0)
                if delay > 0:
                    time.sleep(delay)

                self.send_response(status)
                for key, value in headers.items():
                    if key.lower() == "content-length":
                        continue
                    self.send_header(str(key), str(value))

                if status != 304:
                    if declared_length is not None:
                        length_value = int(declared_length)
                    elif truncate:
                        # Advertise more bytes than we will send, then close
                        # so the client observes an incomplete transfer.
                        length_value = len(raw) + 64
                    else:
                        length_value = len(raw)
                    self.send_header("Content-Length", str(length_value))
                    self.send_header("Connection", "close")
                    if "content-type" not in {k.lower() for k in headers}:
                        self.send_header("Content-Type", "application/json")
                self.end_headers()
                if status != 304 and self.command != "HEAD":
                    try:
                        self.wfile.write(raw)
                        self.wfile.flush()
                        if truncate or (
                            declared_length is not None
                            and int(declared_length) > len(raw)
                        ):
                            # Force TCP close so clients do not block on the
                            # remaining Content-Length budget.
                            try:
                                self.connection.shutdown(socket.SHUT_RDWR)
                            except Exception:  # noqa: BLE001
                                pass
                            try:
                                self.connection.close()
                            except Exception:  # noqa: BLE001
                                pass
                            self.close_connection = True
                    except (BrokenPipeError, ConnectionResetError):
                        return

            def do_GET(self) -> None:  # noqa: N802
                self._handle()

            def do_HEAD(self) -> None:  # noqa: N802
                self._handle()

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    _ = self.rfile.read(length)
                self._handle()

        self._server = ThreadingHTTPServer((host, port), Handler)
        self.host = host
        self.port = int(self._server.server_address[1])
        self._thread: Thread | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> "FakeLegalSourceServer":
        if self._thread is not None:
            return self
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        try:
            self._server.shutdown()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._server.server_close()
        except Exception:  # noqa: BLE001
            pass
        self._thread = None

    def __enter__(self) -> "FakeLegalSourceServer":
        return self.start()

    def __exit__(self, *args: Any) -> None:
        self.stop()

    def url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def set_route(self, path: str, **kwargs: Any) -> None:
        self._routes[path] = dict(kwargs)

    def hit_count(self, path: str) -> int:
        return int(self._hit_counts.get(path, 0))


def build_loopback_transport(
    server: FakeLegalSourceServer,
    *,
    max_response_bytes: int = 1024 * 1024,
    timeout: float = 2.0,
    cache: ConditionalByteCache | None = None,
    cancellation: CancellationToken | None = None,
) -> PatentSourceTransport:
    """Wire a transport to *server* with loopback policy and network enabled."""

    return PatentSourceTransport(
        policy=LegalSourceHostPolicy.for_loopback_testing(port=server.port),
        limits=LegalSourceTransportLimits(
            max_response_bytes=max_response_bytes,
            request_timeout_seconds=timeout,
        ),
        cache=cache,
        cancellation=cancellation,
        network_enabled=True,
    )


__all__ = [
    "DEFAULT_ALLOWED_PORTS",
    "DEFAULT_LEGAL_SOURCE_HOSTS",
    "DEFAULT_USER_AGENT",
    "SOURCE_TRANSPORT_SCHEMA_VERSION",
    "CancellationToken",
    "ConditionalByteCache",
    "FakeLegalSourceServer",
    "LegalSourceHostPolicy",
    "LegalSourceTransportLimits",
    "Opener",
    "PatentSourceTransport",
    "RawHttpResponse",
    "ScriptedOpener",
    "SourceFetchRequest",
    "SourceTransportCancelledError",
    "SourceTransportConfigError",
    "SourceTransportError",
    "SourceTransportNetworkError",
    "SourceTransportPolicyError",
    "SourceTransportResponseTooLargeError",
    "SourceTransportTimeoutError",
    "build_loopback_transport",
    "cache_key_for_url",
    "endpoint_fingerprint",
    "header_get",
    "infer_media_type_from_bytes",
    "media_types_compatible",
    "normalize_media_type",
    "parse_retry_after_header",
    "sanitize_headers",
    "sanitize_url",
]
