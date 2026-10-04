"""Security primitives for wallet provider transports.

The types in this module are deliberately dependency-free and perform no I/O
at import time.  Provider configuration contains opaque secret references,
never credentials.  Resolution is an injected runtime operation.
"""

from __future__ import annotations

import hashlib
import inspect
import ipaddress
import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TypeAlias
from urllib.parse import SplitResult, parse_qsl, urlsplit

from .errors import (
    InvalidRequestError,
    OperationCancelledError,
    SecretResolutionError,
)
from .protocols import OperationContext, SecretValue


_REFERENCE_RE = re.compile(r"^[a-z][a-z0-9+.-]{1,31}://[A-Za-z0-9._/@:-]{1,220}$")
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}\.?$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.?$"
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


def endpoint_fingerprint(url: str) -> str:
    """Return a stable, non-reversible label suitable for errors and metrics."""

    digest = hashlib.sha256(url.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"endpoint:{digest}"


def safe_exception_text(category: str, *, endpoint: str | None = None) -> str:
    """Build an error message without copying an endpoint or upstream detail."""

    if endpoint is None:
        return category
    return f"{category} ({endpoint_fingerprint(endpoint)})"


@dataclass(frozen=True, slots=True)
class SecretReference:
    """Serializable pointer to secret material held by an external resolver."""

    reference: str

    def __post_init__(self) -> None:
        if not isinstance(self.reference, str) or not _REFERENCE_RE.fullmatch(
            self.reference
        ):
            raise InvalidRequestError(
                "secret reference must use an explicit resolver URI"
            )

    def __repr__(self) -> str:
        return "SecretReference(<redacted-reference>)"

    def __str__(self) -> str:
        return "<redacted-reference>"

    def to_dict(self) -> dict[str, str]:
        """Serialize a reference marker, never its resolver path or value."""

        return {
            "kind": "secret_reference",
            "reference_id": hashlib.sha256(self.reference.encode()).hexdigest()[:12],
        }


class SecretHeaderValue(str):
    """A string usable by HTTP adapters whose container representation is safe."""

    def __new__(cls, value: str) -> "SecretHeaderValue":
        return super().__new__(cls, value)

    def __repr__(self) -> str:
        return "<redacted>"


SecretLookupResult: TypeAlias = SecretValue | bytes | str
SecretLookup: TypeAlias = Callable[
    [str], SecretLookupResult | Awaitable[SecretLookupResult]
]


class SecretResolver:
    """Resolve opaque references through an injected callable.

    No environment, file, keyring, or network source is consulted implicitly.
    The lookup callable is runtime state and is intentionally not serializable.
    """

    __slots__ = ("_lookup",)

    def __init__(self, lookup: SecretLookup) -> None:
        if not callable(lookup):
            raise TypeError("lookup must be callable")
        self._lookup = lookup

    def __repr__(self) -> str:
        return "SecretResolver(<injected>)"

    async def resolve(
        self,
        reference: str | SecretReference,
        *,
        context: OperationContext,
    ) -> SecretValue:
        context.check_active()
        parsed = (
            reference
            if isinstance(reference, SecretReference)
            else SecretReference(reference)
        )
        try:
            result = self._lookup(parsed.reference)
            if inspect.isawaitable(result):
                result = await result
        except OperationCancelledError:
            raise
        except Exception:
            # Resolver errors are untrusted and may echo a secret or endpoint.
            raise SecretResolutionError("secret resolution failed") from None
        context.check_active()
        if isinstance(result, SecretValue):
            value = result
        elif isinstance(result, str):
            value = SecretValue(result.encode("utf-8"))
        elif isinstance(result, bytes):
            value = SecretValue(result)
        else:
            raise SecretResolutionError("secret resolver returned an invalid value")
        if not value.value:
            raise SecretResolutionError("secret resolver returned an empty value")
        return value


@dataclass(frozen=True, slots=True)
class EndpointPolicy:
    """Pure URL and resolved-address policy for SSRF-resistant provider reads."""

    allowed_hosts: frozenset[str] = field(default_factory=frozenset)
    allowed_ports: frozenset[int] = field(default_factory=lambda: frozenset({443}))
    allow_http: bool = False
    max_url_length: int = 2_048

    def __post_init__(self) -> None:
        hosts = frozenset(host.rstrip(".").lower() for host in self.allowed_hosts)
        if any(not _HOSTNAME_RE.fullmatch(host) for host in hosts):
            raise InvalidRequestError("endpoint allowlist contains an invalid hostname")
        ports = frozenset(self.allowed_ports)
        if not ports or any(
            isinstance(port, bool)
            or not isinstance(port, int)
            or not 1 <= port <= 65_535
            for port in ports
        ):
            raise InvalidRequestError("allowed_ports must contain valid TCP ports")
        if (
            isinstance(self.max_url_length, bool)
            or not isinstance(self.max_url_length, int)
            or self.max_url_length <= 0
        ):
            raise InvalidRequestError("max_url_length must be a positive integer")
        object.__setattr__(self, "allowed_hosts", hosts)
        object.__setattr__(self, "allowed_ports", ports)

    def validate_url(self, url: str) -> SplitResult:
        """Validate URL syntax without performing DNS or any other I/O."""

        if not isinstance(url, str) or not url or len(url) > self.max_url_length:
            raise InvalidRequestError("provider endpoint is invalid")
        if any(ord(character) < 32 or ord(character) == 127 for character in url):
            raise InvalidRequestError("provider endpoint contains control characters")
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as exc:
            raise InvalidRequestError("provider endpoint is invalid") from exc
        allowed_schemes = {"https"}
        if self.allow_http:
            allowed_schemes.add("http")
        if parsed.scheme.lower() not in allowed_schemes:
            raise InvalidRequestError(
                safe_exception_text("provider endpoint scheme is not allowed", endpoint=url)
            )
        if parsed.username is not None or parsed.password is not None:
            raise InvalidRequestError(
                safe_exception_text("provider endpoint userinfo is forbidden", endpoint=url)
            )
        if parsed.fragment:
            raise InvalidRequestError(
                safe_exception_text("provider endpoint fragment is forbidden", endpoint=url)
            )
        if any(
            key.strip().lower() in _SECRET_QUERY_KEYS
            for key, _value in parse_qsl(parsed.query, keep_blank_values=True)
        ):
            raise InvalidRequestError(
                safe_exception_text(
                    "provider credentials are forbidden in query parameters",
                    endpoint=url,
                )
            )
        hostname = (parsed.hostname or "").rstrip(".").lower()
        if not hostname:
            raise InvalidRequestError("provider endpoint hostname is required")
        if hostname == "localhost" or hostname.endswith(_BLOCKED_HOST_SUFFIXES):
            raise InvalidRequestError(
                safe_exception_text("provider endpoint hostname is unsafe", endpoint=url)
            )
        try:
            literal = ipaddress.ip_address(hostname)
        except ValueError:
            literal = None
        if literal is not None:
            if not literal.is_global:
                raise InvalidRequestError(
                    safe_exception_text("provider endpoint address is unsafe", endpoint=url)
                )
        elif not _HOSTNAME_RE.fullmatch(hostname):
            raise InvalidRequestError(
                safe_exception_text("provider endpoint hostname is invalid", endpoint=url)
            )
        if self.allowed_hosts and hostname not in self.allowed_hosts:
            raise InvalidRequestError(
                safe_exception_text("provider endpoint is not allowlisted", endpoint=url)
            )
        effective_port = port or (443 if parsed.scheme.lower() == "https" else 80)
        if effective_port not in self.allowed_ports:
            raise InvalidRequestError(
                safe_exception_text("provider endpoint port is not allowed", endpoint=url)
            )
        return parsed

    def validate_resolved_addresses(
        self,
        url: str,
        addresses: Iterable[str],
    ) -> tuple[str, ...]:
        """Reject empty, malformed, private, reserved, or mixed DNS answers."""

        checked: list[str] = []
        for address in addresses:
            try:
                parsed = ipaddress.ip_address(address)
            except ValueError as exc:
                raise InvalidRequestError(
                    safe_exception_text("provider DNS answer is invalid", endpoint=url)
                ) from exc
            if not parsed.is_global:
                raise InvalidRequestError(
                    safe_exception_text("provider DNS answer is unsafe", endpoint=url)
                )
            checked.append(parsed.compressed)
        if not checked:
            raise InvalidRequestError(
                safe_exception_text("provider DNS returned no addresses", endpoint=url)
            )
        return tuple(dict.fromkeys(checked))

    def to_dict(self) -> MappingProxyType[str, object]:
        """Return safe policy metadata; endpoint URLs are not part of the policy."""

        return MappingProxyType(
            {
                "allowed_host_count": len(self.allowed_hosts),
                "allowed_ports": sorted(self.allowed_ports),
                "allow_http": self.allow_http,
                "max_url_length": self.max_url_length,
            }
        )


__all__ = [
    "EndpointPolicy",
    "SecretHeaderValue",
    "SecretReference",
    "SecretResolver",
    "endpoint_fingerprint",
    "safe_exception_text",
]
