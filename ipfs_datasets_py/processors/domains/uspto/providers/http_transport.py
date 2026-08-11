"""Bounded production HTTPS transport for USPTO ODP (PATLAW-120).

This module provides a concrete :class:`HttpTransport` implementation with:

* host allowlisting (default ``api.uspto.gov``; loopback only when opted in)
* explicit per-request timeouts
* hard response-size ceilings (streamed read, fail closed)
* cooperative cancellation
* credential attachment from opaque references resolved only at request time
* structured classification helpers and redacted diagnostics

Retries, circuit breaking, rate policy, and conditional caching remain the
responsibility of :class:`~.base.ProviderHttpClient`. This transport is the
single network boundary: no live socket is opened unless :meth:`request` runs,
and tests inject a fake opener or local HTTP server.

Importing this module performs no network I/O.
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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import MappingProxyType
from typing import Any, Final
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .base import (
    API_KEY_HEADER,
    DEFAULT_ODP_BASE_URL,
    ApiKeySecret,
    CancellationToken,
    HttpRequest,
    HttpResponse,
    HttpTransport,
    ProviderCancelledError,
    ProviderConfigError,
    ProviderError,
    ProviderHttpClient,
    ProviderOutcomeKind,
    RetryPolicy,
    TransportLimits,
    classify_http_status,
    contains_secret_leak,
    sanitize_headers,
    sanitize_secret_text,
    sanitize_url,
)
from .credential_resolver import (
    CREDENTIAL_RESOLVER_SCHEMA_VERSION,
    CredentialReference,
    CredentialResolutionError,
    CredentialResolver,
    redact_credential_diagnostics,
)

HTTP_TRANSPORT_SCHEMA_VERSION: Final = "uspto.provider.http_transport.v1"

DEFAULT_ALLOWED_HOSTS: Final = frozenset({"api.uspto.gov"})
DEFAULT_ALLOWED_PORTS: Final = frozenset({443})
DEFAULT_USER_AGENT: Final = "ipfs-datasets-uspto-odp/1.0 (+https://github.com)"

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

# Injected opener: (prepared urllib Request, timeout) -> http.client-like response
Opener = Callable[[urllib.request.Request, float], Any]
Clock = Callable[[], float]


class TransportPolicyError(ProviderConfigError):
    """Request rejected by host/URL policy before any network I/O."""

    code = "transport_policy_violation"


class TransportTimeoutError(ProviderError):
    """Request exceeded the configured timeout."""

    code = "transport_timeout"


class TransportResponseTooLargeError(ProviderError):
    """Response body exceeded max_response_bytes."""

    code = "response_too_large"


class TransportNetworkError(ProviderError):
    """Low-level network / protocol failure (safe message only)."""

    code = "transport_error"


def endpoint_fingerprint(url: str) -> str:
    """Non-reversible short label suitable for errors and metrics."""

    digest = hashlib.sha256(
        sanitize_url(url).encode("utf-8", errors="replace")
    ).hexdigest()[:12]
    return f"endpoint:{digest}"


def _safe_transport_message(category: str, *, url: str | None = None) -> str:
    if url is None:
        return category
    return f"{category} ({endpoint_fingerprint(url)})"


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
    if result != result or result in (float("inf"), float("-inf")) or result <= 0:
        raise ProviderConfigError(f"{name} must be a positive finite number")
    return result


@dataclass(frozen=True, slots=True)
class HostAllowlistPolicy:
    """URL host/scheme/port policy for SSRF-resistant ODP reads."""

    allowed_hosts: frozenset[str] = field(
        default_factory=lambda: frozenset(DEFAULT_ALLOWED_HOSTS)
    )
    allowed_ports: frozenset[int] = field(
        default_factory=lambda: frozenset(DEFAULT_ALLOWED_PORTS)
    )
    allow_http_loopback: bool = False
    max_url_length: int = 2_048
    require_https: bool = True

    def __post_init__(self) -> None:
        hosts = frozenset(
            str(host).rstrip(".").lower() for host in self.allowed_hosts
        )
        for host in hosts:
            if host in {"localhost", "127.0.0.1", "::1"}:
                continue
            try:
                ipaddress.ip_address(host)
            except ValueError:
                if not _HOSTNAME_RE.fullmatch(host):
                    raise ProviderConfigError(
                        f"allowlist contains invalid hostname: {host!r}"
                    ) from None
        ports = frozenset(int(p) for p in self.allowed_ports)
        if not ports or any(not 1 <= p <= 65_535 for p in ports):
            raise ProviderConfigError("allowed_ports must contain valid TCP ports")
        object.__setattr__(self, "allowed_hosts", hosts)
        object.__setattr__(self, "allowed_ports", ports)
        object.__setattr__(
            self,
            "max_url_length",
            _positive_int(self.max_url_length, "max_url_length", maximum=16_384),
        )
        if not isinstance(self.allow_http_loopback, bool):
            raise ProviderConfigError("allow_http_loopback must be bool")
        if not isinstance(self.require_https, bool):
            raise ProviderConfigError("require_https must be bool")

    @classmethod
    def odp_default(cls) -> "HostAllowlistPolicy":
        return cls()

    @classmethod
    def for_loopback_testing(
        cls,
        *,
        port: int | None = None,
        hosts: Sequence[str] = ("127.0.0.1", "localhost"),
    ) -> "HostAllowlistPolicy":
        """Policy for fake-server tests on loopback HTTP only."""

        ports = set(DEFAULT_ALLOWED_PORTS)
        if port is not None:
            ports.add(int(port))
        # Ephemeral ports vary; allow the full non-privileged range in tests.
        ports.update(range(1024, 65_536))
        return cls(
            allowed_hosts=frozenset(h.rstrip(".").lower() for h in hosts),
            allowed_ports=frozenset(ports),
            allow_http_loopback=True,
            require_https=False,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_http_loopback": self.allow_http_loopback,
            "allowed_hosts": sorted(self.allowed_hosts),
            "allowed_ports_count": len(self.allowed_ports),
            "max_url_length": self.max_url_length,
            "require_https": self.require_https,
        }

    def validate_url(self, url: str) -> Any:
        """Validate *url* without performing DNS or network I/O.

        Returns the parsed :func:`urlsplit` result on success.
        """

        if not isinstance(url, str) or not url or len(url) > self.max_url_length:
            raise TransportPolicyError("request URL is invalid")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in url):
            raise TransportPolicyError("request URL contains control characters")
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as exc:
            raise TransportPolicyError("request URL is invalid") from exc

        scheme = (parsed.scheme or "").lower()
        if scheme not in {"https", "http"}:
            raise TransportPolicyError(
                _safe_transport_message("URL scheme is not allowed", url=url)
            )
        if parsed.username is not None or parsed.password is not None:
            raise TransportPolicyError(
                _safe_transport_message("URL userinfo is forbidden", url=url)
            )
        if any(
            key.strip().lower() in _SECRET_QUERY_KEYS
            for key, _ in parse_qsl(parsed.query, keep_blank_values=True)
        ):
            raise TransportPolicyError(
                _safe_transport_message(
                    "credentials are forbidden in query parameters", url=url
                )
            )

        hostname = (parsed.hostname or "").rstrip(".").lower()
        if not hostname:
            raise TransportPolicyError("request URL hostname is required")

        is_loopback_name = hostname in {"localhost", "127.0.0.1", "::1"}
        try:
            literal = ipaddress.ip_address(hostname)
        except ValueError:
            literal = None

        if literal is not None:
            if literal.is_loopback:
                if not self.allow_http_loopback:
                    raise TransportPolicyError(
                        _safe_transport_message("loopback URL is not permitted", url=url)
                    )
            elif not literal.is_global:
                raise TransportPolicyError(
                    _safe_transport_message("URL address is unsafe", url=url)
                )
            elif hostname not in self.allowed_hosts and str(literal) not in self.allowed_hosts:
                # Literal global IPs must still be allowlisted explicitly.
                raise TransportPolicyError(
                    _safe_transport_message("URL host is not allowlisted", url=url)
                )
        else:
            if is_loopback_name:
                if not self.allow_http_loopback:
                    raise TransportPolicyError(
                        _safe_transport_message(
                            "loopback hostname is not permitted", url=url
                        )
                    )
            else:
                if hostname.endswith(_BLOCKED_HOST_SUFFIXES):
                    raise TransportPolicyError(
                        _safe_transport_message("URL hostname is unsafe", url=url)
                    )
                if not _HOSTNAME_RE.fullmatch(hostname):
                    raise TransportPolicyError(
                        _safe_transport_message("URL hostname is invalid", url=url)
                    )
                if hostname not in self.allowed_hosts:
                    raise TransportPolicyError(
                        _safe_transport_message(
                            "URL host is not allowlisted", url=url
                        )
                    )

        if scheme == "http":
            if not self.allow_http_loopback:
                raise TransportPolicyError(
                    _safe_transport_message(
                        "http scheme requires allow_http_loopback", url=url
                    )
                )
            if not (
                is_loopback_name
                or (literal is not None and literal.is_loopback)
            ):
                raise TransportPolicyError(
                    _safe_transport_message(
                        "http is only allowed for loopback", url=url
                    )
                )
        elif self.require_https and scheme != "https":
            raise TransportPolicyError(
                _safe_transport_message("https is required", url=url)
            )

        effective_port = port or (443 if scheme == "https" else 80)
        if effective_port not in self.allowed_ports:
            # Loopback test servers use ephemeral ports already added by
            # for_loopback_testing; production only allows 443.
            if not (self.allow_http_loopback and is_loopback_name):
                raise TransportPolicyError(
                    _safe_transport_message("URL port is not allowed", url=url)
                )
            if not self.allow_http_loopback:
                raise TransportPolicyError(
                    _safe_transport_message("URL port is not allowed", url=url)
                )

        return parsed


@dataclass(frozen=True, slots=True)
class BoundedTransportLimits:
    """Finite safety budgets enforced at the raw HTTP boundary."""

    max_response_bytes: int = 16 * 1024 * 1024
    max_request_bytes: int = 1 * 1024 * 1024
    max_header_bytes: int = 64 * 1024
    request_timeout_seconds: float = 30.0
    max_redirects: int = 0  # ODP clients should not follow redirects by default
    connect_timeout_seconds: float | None = None

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
            _positive_finite(self.request_timeout_seconds, "request_timeout_seconds"),
        )
        object.__setattr__(
            self,
            "max_redirects",
            _nonneg_int(self.max_redirects, "max_redirects"),
        )
        if self.connect_timeout_seconds is not None:
            object.__setattr__(
                self,
                "connect_timeout_seconds",
                _positive_finite(
                    self.connect_timeout_seconds, "connect_timeout_seconds"
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "connect_timeout_seconds": self.connect_timeout_seconds,
            "max_header_bytes": self.max_header_bytes,
            "max_redirects": self.max_redirects,
            "max_request_bytes": self.max_request_bytes,
            "max_response_bytes": self.max_response_bytes,
            "request_timeout_seconds": self.request_timeout_seconds,
        }

    def as_provider_limits(self) -> TransportLimits:
        return TransportLimits(
            max_response_bytes=self.max_response_bytes,
            request_timeout_seconds=self.request_timeout_seconds,
        )


def _default_opener(
    prepared: urllib.request.Request, timeout: float
) -> http.client.HTTPResponse:
    """stdlib opener used in production (no redirect following)."""

    opener = urllib.request.build_opener(urllib.request.HTTPHandler)
    # HTTPErrorProcessor is intentionally omitted so 4xx/5xx are returned
    # as normal responses when possible; HTTPError still surfaces for some paths.
    return opener.open(prepared, timeout=timeout)  # type: ignore[no-any-return]


def _read_bounded(stream: Any, max_bytes: int) -> bytes:
    """Read from *stream* up to *max_bytes* + 1 to detect overflow."""

    chunks: list[bytes] = []
    total = 0
    # Read slightly past the limit so we can fail closed on oversized bodies.
    budget = max_bytes + 1
    while total < budget:
        to_read = min(65_536, budget - total)
        try:
            chunk = stream.read(to_read)
        except Exception as exc:  # noqa: BLE001
            raise TransportNetworkError(
                f"response read failed: {type(exc).__name__}"
            ) from None
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    body = b"".join(chunks)
    if len(body) > max_bytes:
        raise TransportResponseTooLargeError(
            f"response exceeded max_response_bytes ({max_bytes})"
        )
    return body


class BoundedHttpTransport:
    """Production HTTPS transport with allowlist, timeout, and size bounds.

    Implements the :class:`HttpTransport` protocol expected by
    :class:`ProviderHttpClient` and :class:`PatentFileWrapperClient`.
    """

    __slots__ = (
        "_cancellation",
        "_clock",
        "_credential_ref",
        "_credential_resolver",
        "_default_headers",
        "_limits",
        "_opener",
        "_policy",
        "_request_count",
        "_user_agent",
    )

    def __init__(
        self,
        *,
        policy: HostAllowlistPolicy | None = None,
        limits: BoundedTransportLimits | None = None,
        credential_resolver: CredentialResolver | None = None,
        credential_ref: str | CredentialReference | ApiKeySecret | None = None,
        cancellation: CancellationToken | None = None,
        opener: Opener | None = None,
        default_headers: Mapping[str, str] | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        clock: Clock | None = None,
    ) -> None:
        self._policy = policy or HostAllowlistPolicy.odp_default()
        self._limits = limits or BoundedTransportLimits()
        self._credential_resolver = credential_resolver
        self._credential_ref = credential_ref
        self._cancellation = cancellation
        self._opener = opener or _default_opener
        self._default_headers = {
            str(k): str(v) for k, v in dict(default_headers or {}).items()
        }
        self._user_agent = str(user_agent or DEFAULT_USER_AGENT)[:256]
        self._clock = clock or time.monotonic
        self._request_count = 0

    @property
    def policy(self) -> HostAllowlistPolicy:
        return self._policy

    @property
    def limits(self) -> BoundedTransportLimits:
        return self._limits

    @property
    def request_count(self) -> int:
        return self._request_count

    def __repr__(self) -> str:
        return (
            f"BoundedHttpTransport(policy_hosts={sorted(self._policy.allowed_hosts)!r}, "
            f"requests={self._request_count})"
        )

    def safe_config(self) -> dict[str, Any]:
        """Serializable config with no secrets."""

        cred: dict[str, Any] | None = None
        if self._credential_ref is not None:
            if isinstance(self._credential_ref, ApiKeySecret):
                cred = self._credential_ref.to_dict()
            else:
                try:
                    cred = CredentialReference.parse(self._credential_ref).to_dict()
                except ProviderConfigError as exc:
                    cred = {"error": str(exc), "kind": "invalid_reference"}
        return {
            "credential_ref": cred,
            "credential_resolver": None
            if self._credential_resolver is None
            else self._credential_resolver.safe_config(),
            "default_headers": sanitize_headers(self._default_headers),
            "limits": self._limits.to_dict(),
            "policy": self._policy.to_dict(),
            "request_count": self._request_count,
            "schema_version": HTTP_TRANSPORT_SCHEMA_VERSION,
            "user_agent": self._user_agent,
        }

    def diagnostic_dict(
        self,
        *,
        last_request: HttpRequest | None = None,
        last_error: BaseException | None = None,
        secret: str | None = None,
    ) -> dict[str, Any]:
        """Redacted diagnostic snapshot safe for logs and artifacts."""

        payload: dict[str, Any] = {
            "config": self.safe_config(),
            "schema_version": HTTP_TRANSPORT_SCHEMA_VERSION,
        }
        if last_request is not None:
            payload["last_request"] = last_request.sanitized_dict()
        if last_error is not None:
            payload["last_error"] = {
                "code": getattr(last_error, "code", type(last_error).__name__),
                "type": type(last_error).__name__,
                "message": sanitize_secret_text(str(last_error)),
            }
        redacted = redact_credential_diagnostics(payload, secret=secret)
        if secret and contains_secret_leak(redacted, secret=secret):
            # Defensive second pass.
            redacted = json.loads(
                json.dumps(redacted, default=str).replace(secret, "<redacted>")
            )
        return redacted  # type: ignore[no-any-return]

    def _check_cancellation(self) -> None:
        if self._cancellation is not None:
            self._cancellation.check()

    def _merge_headers(self, request: HttpRequest) -> dict[str, str]:
        merged = dict(self._default_headers)
        merged.setdefault("User-Agent", self._user_agent)
        merged.setdefault("Accept", "application/json")
        for key, value in request.headers.items():
            merged[str(key)] = str(value)

        # Resolve credential reference only at request time.
        if self._credential_ref is not None:
            if self._credential_resolver is None and not isinstance(
                self._credential_ref, ApiKeySecret
            ):
                raise CredentialResolutionError(
                    "credential_ref set but no credential_resolver configured"
                )
            if isinstance(self._credential_ref, ApiKeySecret):
                secret = self._credential_ref
            else:
                assert self._credential_resolver is not None
                secret = self._credential_resolver.resolve(self._credential_ref)
            # Official ODP contract: X-API-KEY header (never query string).
            # Do not overwrite an explicit header already on the request.
            if not any(k.lower() == API_KEY_HEADER.lower() for k in merged):
                merged[API_KEY_HEADER] = secret.reveal()
        return merged

    def request(self, request: HttpRequest) -> HttpResponse:
        """Execute one HTTP request under policy and return a bounded response."""

        if not isinstance(request, HttpRequest):
            raise ProviderConfigError("request must be HttpRequest")
        self._check_cancellation()
        self._policy.validate_url(request.url)

        body = request.body
        if body is not None and len(body) > self._limits.max_request_bytes:
            raise TransportPolicyError("request body exceeds max_request_bytes")

        headers = self._merge_headers(request)
        header_bytes = sum(len(k) + len(v) for k, v in headers.items())
        if header_bytes > self._limits.max_header_bytes:
            raise TransportPolicyError("request headers exceed max_header_bytes")

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

        self._request_count += 1
        started = self._clock()
        response_obj: Any = None
        try:
            self._check_cancellation()
            try:
                response_obj = self._opener(prepared, timeout)
            except ProviderCancelledError:
                raise
            except socket.timeout as exc:
                raise TransportTimeoutError(
                    _safe_transport_message("request timed out", url=request.url)
                ) from None
            except TimeoutError as exc:
                raise TransportTimeoutError(
                    _safe_transport_message("request timed out", url=request.url)
                ) from None
            except urllib.error.HTTPError as http_err:
                # HTTPError is also a file-like response — read it as such.
                response_obj = http_err
            except urllib.error.URLError as url_err:
                reason = url_err.reason
                if isinstance(reason, socket.timeout) or "timed out" in str(reason).lower():
                    raise TransportTimeoutError(
                        _safe_transport_message("request timed out", url=request.url)
                    ) from None
                raise TransportNetworkError(
                    _safe_transport_message(
                        f"network error: {type(reason).__name__ if reason else 'URLError'}",
                        url=request.url,
                    )
                ) from None
            except (ConnectionError, OSError) as exc:
                if "timed out" in str(exc).lower():
                    raise TransportTimeoutError(
                        _safe_transport_message("request timed out", url=request.url)
                    ) from None
                raise TransportNetworkError(
                    _safe_transport_message(
                        f"network error: {type(exc).__name__}", url=request.url
                    )
                ) from None

            self._check_cancellation()

            status = int(getattr(response_obj, "status", None) or response_obj.getcode())
            raw_headers = {}
            header_bag = getattr(response_obj, "headers", None)
            if header_bag is not None:
                try:
                    raw_headers = {str(k): str(v) for k, v in header_bag.items()}
                except Exception:  # noqa: BLE001
                    raw_headers = {}

            # Reject redirects unless explicitly permitted (default max_redirects=0).
            if status in _REDIRECT_STATUSES:
                if self._limits.max_redirects <= 0:
                    # Return the redirect response body (usually empty) without
                    # following Location — caller classifies as client/upstream.
                    body_bytes = _read_bounded(response_obj, self._limits.max_response_bytes)
                else:
                    raise TransportPolicyError(
                        _safe_transport_message(
                            "redirect following is not enabled for this transport",
                            url=request.url,
                        )
                    )
            else:
                body_bytes = _read_bounded(response_obj, self._limits.max_response_bytes)

            elapsed = max(0.0, float(self._clock() - started))
            return HttpResponse(
                status_code=status,
                headers=raw_headers,
                body=body_bytes,
                elapsed_seconds=elapsed,
            )
        finally:
            if response_obj is not None:
                try:
                    response_obj.close()
                except Exception:  # noqa: BLE001
                    pass


class ScriptedOpener:
    """Deterministic opener that returns scripted status/body/header triples.

    Used for offline unit tests without a real server or network. Each call
    consumes the next scripted response. Supports delay and raise outcomes.
    """

    def __init__(
        self,
        outcomes: Sequence[Any] | None = None,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._outcomes: list[Any] = list(outcomes or [])
        self.requests: list[urllib.request.Request] = []
        self._clock = clock or time.monotonic

    def add(
        self,
        *,
        status: int = 200,
        body: bytes | str | dict[str, Any] = b"{}",
        headers: Mapping[str, str] | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        if isinstance(body, dict):
            raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
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
            raise TransportNetworkError("scripted opener exhausted")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        delay = float(outcome.get("delay_seconds") or 0.0)
        if delay > 0 and delay > timeout:
            raise socket.timeout("timed out")
        return _ScriptedResponse(
            status=int(outcome["status"]),
            body=bytes(outcome["body"]),
            headers=dict(outcome.get("headers") or {}),
        )


class _ScriptedResponse:
    """Minimal file-like HTTP response for :class:`ScriptedOpener`."""

    def __init__(
        self,
        *,
        status: int,
        body: bytes,
        headers: Mapping[str, str],
    ) -> None:
        self.status = status
        self._body = body
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


class FakeOdpHttpServer:
    """Threading HTTP server for loopback fake-server transport tests.

    Routes are exact path matches. Supports status scripts, pagination
    cursors, 304 conditional responses, and oversized bodies.
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
                return  # silence

            def _handle(self) -> None:
                path = self.path.split("?", 1)[0]
                parent.received_paths.append(self.path)
                parent.received_headers.append({k: v for k, v in self.headers.items()})
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
                else:
                    status = int(route.get("status", 200))
                    body = route.get("body", b"{}")
                    headers = dict(route.get("headers") or {})

                # Conditional 304 support.
                etag = headers.get("ETag") or headers.get("Etag")
                if_none = self.headers.get("If-None-Match")
                if status == 200 and etag and if_none and if_none == etag:
                    status = 304
                    body = b""

                if isinstance(body, dict):
                    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode(
                        "utf-8"
                    )
                elif isinstance(body, str):
                    raw = body.encode("utf-8")
                else:
                    raw = bytes(body)

                # Optional artificial delay (seconds).
                delay = float(route.get("delay_seconds") or 0.0)
                if delay > 0:
                    time.sleep(delay)

                self.send_response(status)
                for key, value in headers.items():
                    if key.lower() == "content-length":
                        continue
                    self.send_header(str(key), str(value))
                if status != 304:
                    self.send_header("Content-Length", str(len(raw)))
                    if "content-type" not in {k.lower() for k in headers}:
                        self.send_header("Content-Type", "application/json")
                self.end_headers()
                if status != 304 and self.command != "HEAD":
                    try:
                        self.wfile.write(raw)
                    except (BrokenPipeError, ConnectionResetError):
                        # Client timed out or cancelled mid-write — expected in tests.
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

    def start(self) -> "FakeOdpHttpServer":
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

    def __enter__(self) -> "FakeOdpHttpServer":
        return self.start()

    def __exit__(self, *args: Any) -> None:
        self.stop()

    def url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def set_route(self, path: str, **kwargs: Any) -> None:
        self._routes[path] = dict(kwargs)


def build_bounded_provider_client(
    *,
    transport: HttpTransport | None = None,
    base_url: str = DEFAULT_ODP_BASE_URL,
    credential_resolver: CredentialResolver | None = None,
    credential_ref: str | CredentialReference | ApiKeySecret | None = None,
    api_key: ApiKeySecret | str | None = None,
    policy: HostAllowlistPolicy | None = None,
    limits: BoundedTransportLimits | None = None,
    retry_policy: RetryPolicy | None = None,
    cancellation: CancellationToken | None = None,
    **client_kwargs: Any,
) -> ProviderHttpClient:
    """Wire a :class:`ProviderHttpClient` to a bounded production transport.

    If *api_key* is omitted and *credential_ref* is provided, the secret is
    resolved once at construction for the client header injector. Prefer
    passing *api_key* already resolved when the caller manages lifetime.
    """

    transport_limits = limits or BoundedTransportLimits()
    if transport is None:
        transport = BoundedHttpTransport(
            policy=policy,
            limits=transport_limits,
            credential_resolver=credential_resolver,
            credential_ref=credential_ref if api_key is None else None,
            cancellation=cancellation,
        )

    resolved_key = api_key
    if resolved_key is None and credential_ref is not None:
        if isinstance(credential_ref, ApiKeySecret):
            resolved_key = credential_ref
        elif credential_resolver is not None:
            resolved_key = credential_resolver.resolve(credential_ref)
        # else: transport may attach the key itself if it holds the resolver

    return ProviderHttpClient(
        transport,
        base_url=base_url,
        api_key=resolved_key,
        retry_policy=retry_policy,
        limits=transport_limits.as_provider_limits(),
        cancellation=cancellation,
        **client_kwargs,
    )


def classify_transport_status(status_code: int) -> ProviderOutcomeKind:
    """Map HTTP status to :class:`ProviderOutcomeKind` (delegate to base)."""

    return classify_http_status(status_code)


def parse_retry_after_header(
    headers: Mapping[str, str],
    *,
    now: Any = None,
    max_seconds: float = 60.0,
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
        from datetime import datetime, timezone

        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        current = now or datetime.now(timezone.utc)
        delay = (target - current).total_seconds()
    if delay != delay or delay in (float("inf"), float("-inf")):
        return None
    return min(max(0.0, delay), float(max_seconds))


def quota_headers_diagnostic(headers: Mapping[str, str]) -> dict[str, str]:
    """Extract rate/quota related headers for diagnostics (values kept as-is).

    Known secret headers are never included.
    """

    interesting = {
        "retry-after",
        "x-rate-limit-limit",
        "x-rate-limit-remaining",
        "x-rate-limit-reset",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
        "rate-limit",
        "rate-limit-remaining",
    }
    out: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in interesting:
            out[str(key)] = sanitize_secret_text(str(value))
    return out


__all__ = [
    "API_KEY_HEADER",
    "BoundedHttpTransport",
    "BoundedTransportLimits",
    "CREDENTIAL_RESOLVER_SCHEMA_VERSION",
    "DEFAULT_ALLOWED_HOSTS",
    "DEFAULT_ALLOWED_PORTS",
    "DEFAULT_ODP_BASE_URL",
    "DEFAULT_USER_AGENT",
    "FakeOdpHttpServer",
    "HTTP_TRANSPORT_SCHEMA_VERSION",
    "HostAllowlistPolicy",
    "Opener",
    "ScriptedOpener",
    "TransportNetworkError",
    "TransportPolicyError",
    "TransportResponseTooLargeError",
    "TransportTimeoutError",
    "build_bounded_provider_client",
    "classify_transport_status",
    "endpoint_fingerprint",
    "parse_retry_after_header",
    "quota_headers_diagnostic",
]
