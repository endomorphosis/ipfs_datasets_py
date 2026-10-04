"""Bounded, allowlisted acquisition transport for smart-contract artifacts.

CRYPTOIR-G210: URL schemes, hosts, DNS answers, redirects, response counts,
bytes, archives, recursion, time, retries, and credentials are bounded.
Offline fixtures are the default path; live network clients must be injected.

Importing this module performs no network I/O.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from types import MappingProxyType
from typing import Protocol
from urllib.parse import parse_qsl, urljoin, urlsplit

from .artifacts import TransportEvidence, bytes_digest
from .canonical import content_digest, format_datetime
from .errors import (
    AcquisitionError,
    InvalidRequestError,
    ProviderError,
    ResourceLimitError,
)
from .models import AcquisitionBounds, ProviderPolicy
from .protocols import OperationContext


_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}\.?$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.?$"
    r"|localhost$"
)
_BLOCKED_HOST_SUFFIXES = (".internal", ".local", ".localhost", ".home.arpa")
_SECRET_QUERY_KEYS = frozenset(
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
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


def url_digest(url: str) -> str:
    """Stable digest of a URL string for public provenance records."""

    return f"sha256:{sha256(url.encode('utf-8', errors='replace')).hexdigest()}"


def endpoint_fingerprint(url: str) -> str:
    """Non-reversible short label suitable for error messages."""

    return f"endpoint:{sha256(url.encode('utf-8', errors='replace')).hexdigest()[:12]}"


def _safe_error(category: str, *, endpoint: str | None = None) -> str:
    if endpoint is None:
        return category
    return f"{category} ({endpoint_fingerprint(endpoint)})"


@dataclass(frozen=True, slots=True)
class TransportLimits:
    """Finite ceilings enforced on every acquisition hop."""

    max_requests: int = 32
    max_response_bytes: int = 16 * 1024 * 1024
    max_redirects: int = 3
    max_retries: int = 0
    max_url_length: int = 2_048
    max_header_bytes: int = 16_384
    request_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        for name in (
            "max_requests",
            "max_response_bytes",
            "max_url_length",
            "max_header_bytes",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise InvalidRequestError(f"{name} must be a positive integer")
        for name in ("max_redirects", "max_retries"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise InvalidRequestError(f"{name} must be a non-negative integer")
        if (
            isinstance(self.request_timeout_seconds, bool)
            or not isinstance(self.request_timeout_seconds, (int, float))
            or self.request_timeout_seconds <= 0
        ):
            raise InvalidRequestError(
                "request_timeout_seconds must be a positive number"
            )

    @classmethod
    def from_bounds(
        cls,
        bounds: AcquisitionBounds,
        *,
        max_retries: int = 0,
        request_timeout_seconds: float = 30.0,
    ) -> "TransportLimits":
        return cls(
            max_requests=bounds.max_requests,
            max_response_bytes=bounds.max_response_bytes,
            max_redirects=bounds.max_redirects,
            max_retries=max_retries,
            request_timeout_seconds=request_timeout_seconds,
        )


@dataclass(frozen=True, slots=True)
class TransportRequest:
    """One outbound acquisition request (headers must not carry secrets)."""

    url: str
    method: str = "GET"
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""

    def __post_init__(self) -> None:
        object.__setattr__(self, "url", self.url.strip() if self.url else "")
        method = (self.method or "GET").upper()
        if method not in {"GET", "HEAD"}:
            raise InvalidRequestError(
                "acquisition transport allows only read-only GET/HEAD methods"
            )
        object.__setattr__(self, "method", method)
        headers = {
            str(key).strip(): str(value)
            for key, value in dict(self.headers).items()
            if str(key).strip()
        }
        lowered = {key.casefold() for key in headers}
        if lowered & {"authorization", "proxy-authorization", "cookie", "set-cookie"}:
            raise InvalidRequestError(
                "credentials must not appear in transport headers"
            )
        object.__setattr__(self, "headers", MappingProxyType(headers))
        if type(self.body) is not bytes:
            raise InvalidRequestError("request body must be exact bytes")
        if self.body and method == "GET":
            raise InvalidRequestError("GET requests must not carry a body")

    def content_digest(self) -> str:
        return content_digest(
            {
                "body_digest": bytes_digest(self.body) if self.body else "",
                "headers": dict(self.headers),
                "method": self.method,
                "url": self.url,
            }
        )


@dataclass(frozen=True, slots=True)
class TransportResponse:
    """One inbound response with untouched body bytes."""

    url: str
    status_code: int
    headers: Mapping[str, str]
    body: bytes
    elapsed_seconds: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.url, str) or not self.url.strip():
            raise InvalidRequestError("response url must not be empty")
        if isinstance(self.status_code, bool) or not isinstance(
            self.status_code, int
        ):
            raise InvalidRequestError("status_code must be an integer")
        if type(self.body) is not bytes:
            raise InvalidRequestError("response body must be exact bytes")
        headers = {
            str(key).strip().casefold(): str(value)
            for key, value in dict(self.headers).items()
            if str(key).strip()
        }
        object.__setattr__(self, "headers", MappingProxyType(headers))
        if (
            isinstance(self.elapsed_seconds, bool)
            or not isinstance(self.elapsed_seconds, (int, float))
            or self.elapsed_seconds < 0
        ):
            raise InvalidRequestError("elapsed_seconds must be non-negative")

    @property
    def body_digest(self) -> str:
        return bytes_digest(self.body)

    def headers_digest(self) -> str:
        return content_digest(dict(self.headers))


class ResponseSource(Protocol):
    """Injected offline or live response source."""

    def fetch(
        self,
        request: TransportRequest,
        *,
        context: OperationContext,
    ) -> TransportResponse:
        """Return one response without performing unbounded work."""

        ...


class AddressResolver(Protocol):
    """Injected DNS / address resolution surface."""

    def resolve(self, hostname: str) -> Sequence[str]:
        """Return textual IP addresses for *hostname*."""

        ...


@dataclass(frozen=True, slots=True)
class FixtureEntry:
    """Static offline response bound to an exact URL."""

    status_code: int = 200
    body: bytes = b""
    headers: Mapping[str, str] = field(default_factory=dict)
    redirect_to: str = ""

    def __post_init__(self) -> None:
        if type(self.body) is not bytes:
            raise InvalidRequestError("fixture body must be exact bytes")
        object.__setattr__(
            self,
            "headers",
            MappingProxyType({str(k).casefold(): str(v) for k, v in dict(self.headers).items()}),
        )
        object.__setattr__(
            self, "redirect_to", self.redirect_to.strip() if self.redirect_to else ""
        )


class FixtureResponseSource:
    """Default offline response source: exact URL map, no network."""

    __slots__ = ("_fixtures",)

    def __init__(self, fixtures: Mapping[str, FixtureEntry] | None = None) -> None:
        self._fixtures: dict[str, FixtureEntry] = dict(fixtures or {})

    def register(self, url: str, entry: FixtureEntry) -> None:
        if not isinstance(url, str) or not url.strip():
            raise InvalidRequestError("fixture url must not be empty")
        self._fixtures[url] = entry

    def fetch(
        self,
        request: TransportRequest,
        *,
        context: OperationContext,
    ) -> TransportResponse:
        context.check_active()
        entry = self._fixtures.get(request.url)
        if entry is None:
            raise ProviderError(
                _safe_error("fixture not registered for URL", endpoint=request.url)
            )
        headers = dict(entry.headers)
        if entry.redirect_to:
            headers.setdefault("location", entry.redirect_to)
        return TransportResponse(
            url=request.url,
            status_code=entry.status_code,
            headers=headers,
            body=entry.body if entry.status_code not in _REDIRECT_STATUSES else b"",
            elapsed_seconds=0.0,
        )


class StaticAddressResolver:
    """Injected hostname → addresses map used by tests and offline runs."""

    __slots__ = ("_records",)

    def __init__(self, records: Mapping[str, Sequence[str]] | None = None) -> None:
        self._records = {
            host.rstrip(".").casefold(): tuple(addresses)
            for host, addresses in dict(records or {}).items()
        }

    def resolve(self, hostname: str) -> Sequence[str]:
        key = hostname.rstrip(".").casefold()
        if key not in self._records:
            raise ProviderError(
                _safe_error("DNS resolution unavailable offline", endpoint=hostname)
            )
        return self._records[key]


class AcquisitionTransport:
    """SSRF-resistant, bounded acquisition transport.

    Defaults to offline fixtures.  Live network clients are never constructed
    implicitly; callers must inject a :class:`ResponseSource`.
    """

    __slots__ = (
        "_limits",
        "_policy",
        "_request_count",
        "_resolver",
        "_source",
        "_transport_name",
    )

    def __init__(
        self,
        *,
        policy: ProviderPolicy | None = None,
        limits: TransportLimits | None = None,
        source: ResponseSource | None = None,
        resolver: AddressResolver | None = None,
        transport_name: str = "offline_fixture",
    ) -> None:
        self._policy = policy or ProviderPolicy()
        self._limits = limits or TransportLimits()
        self._source = source if source is not None else FixtureResponseSource()
        self._resolver = resolver if resolver is not None else StaticAddressResolver()
        self._transport_name = transport_name.strip() or "offline_fixture"
        self._request_count = 0

    @property
    def policy(self) -> ProviderPolicy:
        return self._policy

    @property
    def limits(self) -> TransportLimits:
        return self._limits

    @property
    def request_count(self) -> int:
        return self._request_count

    def reset_budget(self) -> None:
        """Reset the per-transport request counter (new logical acquisition)."""

        self._request_count = 0

    def validate_url(self, url: str) -> None:
        """Validate URL syntax and policy without performing I/O."""

        self._parse_and_validate_url(url)

    def _parse_and_validate_url(self, url: str):
        if not isinstance(url, str) or not url or len(url) > self._limits.max_url_length:
            raise InvalidRequestError("acquisition URL is invalid")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in url):
            raise InvalidRequestError("acquisition URL contains control characters")
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as exc:
            raise InvalidRequestError("acquisition URL is invalid") from exc

        scheme = (parsed.scheme or "").casefold()
        if scheme not in self._policy.allowed_schemes:
            raise InvalidRequestError(
                _safe_error("URL scheme is not allowlisted", endpoint=url)
            )
        if parsed.username is not None or parsed.password is not None:
            raise InvalidRequestError(
                _safe_error("URL userinfo/credentials are forbidden", endpoint=url)
            )
        if parsed.fragment:
            raise InvalidRequestError(
                _safe_error("URL fragments are forbidden", endpoint=url)
            )
        if any(
            key.strip().casefold() in _SECRET_QUERY_KEYS
            for key, _value in parse_qsl(parsed.query, keep_blank_values=True)
        ):
            raise InvalidRequestError(
                _safe_error(
                    "credentials are forbidden in query parameters", endpoint=url
                )
            )

        hostname = (parsed.hostname or "").rstrip(".").casefold()
        if not hostname:
            raise InvalidRequestError("acquisition URL hostname is required")

        is_loopback_name = hostname == "localhost"
        try:
            literal = ipaddress.ip_address(hostname)
        except ValueError:
            literal = None

        if literal is not None:
            if literal.is_loopback:
                if not self._policy.allow_http_loopback or scheme != "http":
                    raise InvalidRequestError(
                        _safe_error("loopback URL is not permitted", endpoint=url)
                    )
            elif not literal.is_global:
                raise InvalidRequestError(
                    _safe_error("URL address is unsafe", endpoint=url)
                )
        else:
            if is_loopback_name:
                if not self._policy.allow_http_loopback or scheme != "http":
                    raise InvalidRequestError(
                        _safe_error("loopback hostname is not permitted", endpoint=url)
                    )
            else:
                if hostname.endswith(_BLOCKED_HOST_SUFFIXES):
                    raise InvalidRequestError(
                        _safe_error("URL hostname is unsafe", endpoint=url)
                    )
                if not _HOSTNAME_RE.fullmatch(hostname):
                    raise InvalidRequestError(
                        _safe_error("URL hostname is invalid", endpoint=url)
                    )
            if not self._policy.permits_host(hostname):
                raise InvalidRequestError(
                    _safe_error("URL host is not allowlisted", endpoint=url)
                )

        if scheme == "http" and not self._policy.allow_http_loopback:
            raise InvalidRequestError(
                _safe_error("http scheme requires allow_http_loopback", endpoint=url)
            )
        if scheme == "http" and not (
            is_loopback_name
            or (literal is not None and literal.is_loopback)
        ):
            raise InvalidRequestError(
                _safe_error("http is only allowed for loopback", endpoint=url)
            )

        # Port policy: https→443, http loopback→80 unless explicit.
        effective_port = port or (443 if scheme == "https" else 80)
        if scheme == "https" and effective_port not in {443}:
            # Non-standard HTTPS ports are allowed only when explicitly
            # present and host is allowlisted; still reject privileged
            # internal conventions below 1024 except 443.
            if effective_port < 1024 and effective_port != 443:
                raise InvalidRequestError(
                    _safe_error("URL port is not allowed", endpoint=url)
                )
        return parsed

    def validate_resolved_addresses(
        self,
        url: str,
        addresses: Sequence[str],
    ) -> tuple[str, ...]:
        """Reject empty, private, reserved, or mixed-unsafe DNS answers."""

        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").rstrip(".").casefold()
        scheme = (parsed.scheme or "").casefold()
        allow_loopback = self._policy.allow_http_loopback and scheme == "http"

        if not addresses:
            raise InvalidRequestError(
                _safe_error("DNS answer is empty", endpoint=url)
            )
        checked: list[str] = []
        for address in addresses:
            try:
                parsed_ip = ipaddress.ip_address(address)
            except ValueError as exc:
                raise InvalidRequestError(
                    _safe_error("DNS answer is invalid", endpoint=url)
                ) from exc
            if parsed_ip.is_loopback:
                if not allow_loopback:
                    raise InvalidRequestError(
                        _safe_error("DNS answer is unsafe", endpoint=url)
                    )
            elif not parsed_ip.is_global:
                raise InvalidRequestError(
                    _safe_error("DNS answer is unsafe", endpoint=url)
                )
            checked.append(parsed_ip.compressed)

        # Hostname literals already validated; for names, ensure answers
        # do not silently mix loopback and global.
        kinds = {
            "loopback" if ipaddress.ip_address(item).is_loopback else "global"
            for item in checked
        }
        if len(kinds) > 1:
            raise InvalidRequestError(
                _safe_error("DNS answer mixes address scopes", endpoint=url)
            )
        # Touch hostname for offline resolvers that key on it.
        _ = hostname
        return tuple(checked)

    def _consume_request(self, context: OperationContext) -> None:
        context.check_active()
        self._request_count += 1
        if self._request_count > self._limits.max_requests:
            raise ResourceLimitError("acquisition request count exceeded")

    def _enforce_response_size(self, response: TransportResponse, url: str) -> None:
        if len(response.body) > self._limits.max_response_bytes:
            raise ResourceLimitError(
                _safe_error("response exceeds max_response_bytes", endpoint=url)
            )
        header_bytes = sum(
            len(key) + len(value) for key, value in response.headers.items()
        )
        if header_bytes > self._limits.max_header_bytes:
            raise ResourceLimitError(
                _safe_error("response headers exceed max_header_bytes", endpoint=url)
            )
        if response.elapsed_seconds > self._limits.request_timeout_seconds:
            raise ResourceLimitError(
                _safe_error("response exceeded request time budget", endpoint=url)
            )

    def fetch(
        self,
        request: TransportRequest,
        *,
        context: OperationContext,
    ) -> tuple[TransportResponse, TransportEvidence]:
        """Fetch *request* under policy and return body plus transport evidence."""

        redirects: list[str] = []
        current = request
        retries_left = self._limits.max_retries
        final: TransportResponse | None = None

        while True:
            self._parse_and_validate_url(current.url)
            hostname = (urlsplit(current.url).hostname or "").rstrip(".").casefold()
            try:
                literal = ipaddress.ip_address(hostname)
            except ValueError:
                literal = None
            if literal is None and hostname and hostname != "localhost":
                addresses = self._resolver.resolve(hostname)
                self.validate_resolved_addresses(current.url, addresses)

            attempt = 0
            while True:
                self._consume_request(context)
                try:
                    response = self._source.fetch(current, context=context)
                except (
                    InvalidRequestError,
                    ResourceLimitError,
                    ProviderError,
                    AcquisitionError,
                ):
                    # Preserve structured provider failures (e.g. missing fixture).
                    raise
                except Exception as exc:
                    if attempt < retries_left:
                        attempt += 1
                        continue
                    raise ProviderError(
                        _safe_error("transport source failed", endpoint=current.url)
                    ) from exc
                break

            self._enforce_response_size(response, current.url)

            if response.status_code in _REDIRECT_STATUSES:
                location = response.headers.get("location", "").strip()
                if not location:
                    raise ProviderError(
                        _safe_error("redirect without location", endpoint=current.url)
                    )
                # Relative redirects resolve against the current URL.
                next_url = urljoin(current.url, location)
                redirects.append(current.url)
                if len(redirects) > self._limits.max_redirects:
                    raise ResourceLimitError(
                        _safe_error("redirect count exceeded", endpoint=current.url)
                    )
                current = TransportRequest(
                    url=next_url,
                    method="GET",
                    headers=current.headers,
                )
                continue

            final = response
            break

        assert final is not None
        evidence = TransportEvidence(
            request_digest=request.content_digest(),
            response_digest=final.body_digest,
            final_url_digest=url_digest(final.url),
            status_code=final.status_code,
            byte_length=len(final.body),
            redirect_count=len(redirects),
            transport=self._transport_name,
            headers_digest=final.headers_digest(),
            attributes={
                "redirect_chain_digests": [url_digest(item) for item in redirects],
                "observed_at": format_datetime(datetime.now(timezone.utc)),
            },
        )
        return final, evidence

    def fetch_bytes(
        self,
        url: str,
        *,
        context: OperationContext,
        headers: Mapping[str, str] | None = None,
    ) -> tuple[bytes, TransportEvidence]:
        """Convenience wrapper for a single GET that returns body bytes."""

        response, evidence = self.fetch(
            TransportRequest(url=url, headers=dict(headers or {})),
            context=context,
        )
        if response.status_code != 200:
            raise ProviderError(
                _safe_error(
                    f"unexpected status {response.status_code}",
                    endpoint=url,
                )
            )
        return response.body, evidence


def build_offline_transport(
    fixtures: Mapping[str, FixtureEntry],
    *,
    policy: ProviderPolicy | None = None,
    limits: TransportLimits | None = None,
    dns: Mapping[str, Sequence[str]] | None = None,
) -> AcquisitionTransport:
    """Construct the default offline acquisition transport."""

    return AcquisitionTransport(
        policy=policy,
        limits=limits,
        source=FixtureResponseSource(fixtures),
        resolver=StaticAddressResolver(dns),
        transport_name="offline_fixture",
    )


__all__ = [
    "AcquisitionTransport",
    "AddressResolver",
    "FixtureEntry",
    "FixtureResponseSource",
    "ResponseSource",
    "StaticAddressResolver",
    "TransportLimits",
    "TransportRequest",
    "TransportResponse",
    "build_offline_transport",
    "endpoint_fingerprint",
    "url_digest",
]
