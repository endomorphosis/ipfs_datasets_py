"""Bounded HTTP and JSON-RPC transport for wallet providers.

``HttpTransport`` is a policy-enforcing wrapper around an injected delegate.
It does not select an HTTP library, open sockets, resolve DNS, or read secrets
until ``request`` is awaited.  The wrapper owns the safety invariants shared by
all chain providers: endpoint/DNS validation, finite byte/time/retry budgets,
rate limiting, circuit breaking, cancellation, and safe failures.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import socket
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit

from ..errors import (
    DeadlineExceededError,
    InvalidRequestError,
    OperationCancelledError,
    ProviderError,
    ResourceLimitError,
    SecretResolutionError,
)
from ..protocols import (
    HttpRequest,
    HttpResponse,
    HttpTransport as HttpTransportProtocol,
    OperationContext,
    RequestLimits,
)
from ..security import (
    EndpointPolicy,
    SecretHeaderValue,
    SecretReference,
    SecretResolver,
    endpoint_fingerprint,
    safe_exception_text,
)
from .rate_limit import RateLimiter
from .retry import (
    CircuitBreaker,
    PermanentProviderError,
    RetryDisposition,
    RetryPolicy,
    ThrottledProviderError,
    TransientProviderError,
)


_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]{1,128}$")
_JSON_CONTENT_TYPE = "application/json"
_CREDENTIAL_HEADER_NAMES = frozenset(
    {
        "api-key",
        "authorization",
        "cookie",
        "proxy-authorization",
        "x-api-key",
    }
)


class ProviderCapability(StrEnum):
    """Transport features a provider may safely advertise in manifests."""

    HTTP = "http"
    JSON_RPC = "json_rpc"
    PAGINATION = "pagination"
    RETRY_AFTER = "retry_after"
    RATE_LIMITED = "rate_limited"
    CIRCUIT_BREAKER = "circuit_breaker"
    SSRF_PROTECTED = "ssrf_protected"


@runtime_checkable
class AddressResolver(Protocol):
    """Injected async DNS boundary."""

    async def resolve(self, hostname: str, port: int) -> Sequence[str]:
        """Return textual IP addresses for a hostname and port."""

        ...


class SystemAddressResolver:
    """Resolve through the active asyncio loop when a request is executed."""

    __slots__ = ()

    async def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
        loop = asyncio.get_running_loop()
        answers = await loop.getaddrinfo(
            hostname,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
        return tuple(dict.fromkeys(answer[4][0] for answer in answers))


class ProviderEndpoint:
    """Runtime endpoint whose URL is excluded from every representation."""

    __slots__ = ("_url", "name")

    def __init__(self, url: str, name: str = "provider") -> None:
        if not isinstance(url, str) or not url:
            raise InvalidRequestError("provider endpoint must not be empty")
        if (
            not isinstance(name, str)
            or not name
            or len(name) > 64
            or not all(character.isalnum() or character in "-_." for character in name)
        ):
            raise InvalidRequestError("provider endpoint name is invalid")
        self._url = url
        self.name = name

    @property
    def url(self) -> str:
        """Return the runtime URL for request construction."""

        return self._url

    @property
    def endpoint_id(self) -> str:
        return endpoint_fingerprint(self.url).partition(":")[2]

    def __repr__(self) -> str:
        return (
            f"ProviderEndpoint(name={self.name!r}, "
            f"endpoint_id={self.endpoint_id!r})"
        )

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "endpoint_id": self.endpoint_id}


@dataclass(frozen=True, slots=True)
class ProviderAuth:
    """Header authentication configured only by an opaque secret reference."""

    secret_reference: SecretReference
    header_name: str = "Authorization"
    prefix: str = "Bearer "

    def __post_init__(self) -> None:
        if not isinstance(self.secret_reference, SecretReference):
            raise InvalidRequestError(
                "provider authentication requires a SecretReference"
            )
        if not _HEADER_NAME_RE.fullmatch(self.header_name):
            raise InvalidRequestError("provider authentication header is invalid")
        if "\r" in self.prefix or "\n" in self.prefix or len(self.prefix) > 64:
            raise InvalidRequestError("provider authentication prefix is invalid")

    def __repr__(self) -> str:
        return (
            f"ProviderAuth(secret_reference={self.secret_reference!r}, "
            f"header_name={self.header_name!r}, prefix=<redacted>)"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "secret_reference": self.secret_reference.to_dict(),
            "header_name": self.header_name,
            "kind": "header",
        }


def _positive_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidRequestError(f"{name} must be a positive integer")
    return value


def _positive_finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidRequestError(f"{name} must be a positive finite number")
    converted = float(value)
    if not math.isfinite(converted) or converted <= 0:
        raise InvalidRequestError(f"{name} must be a positive finite number")
    return converted


@dataclass(frozen=True, slots=True)
class TransportLimits:
    """Mandatory finite budgets for every transport operation."""

    max_request_bytes: int = 1 * 1024 * 1024
    max_response_bytes: int = 16 * 1024 * 1024
    max_pages: int = 100
    max_items: int = 10_000
    max_range_size: int = 10_000
    request_timeout_seconds: float = 15.0
    operation_timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        for name in (
            "max_request_bytes",
            "max_response_bytes",
            "max_pages",
            "max_items",
            "max_range_size",
        ):
            object.__setattr__(self, name, _positive_int(getattr(self, name), name))
        object.__setattr__(
            self,
            "request_timeout_seconds",
            _positive_finite(
                self.request_timeout_seconds, "request_timeout_seconds"
            ),
        )
        object.__setattr__(
            self,
            "operation_timeout_seconds",
            _positive_finite(
                self.operation_timeout_seconds, "operation_timeout_seconds"
            ),
        )
        if self.operation_timeout_seconds < self.request_timeout_seconds:
            raise InvalidRequestError(
                "operation_timeout_seconds must cover at least one request"
            )


@dataclass(frozen=True, slots=True)
class JsonPage:
    """One parsed page and its opaque continuation cursor."""

    items: tuple[object, ...]
    next_cursor: str | None = None

    def __post_init__(self) -> None:
        if self.next_cursor == "":
            raise InvalidRequestError("pagination cursor must be non-empty")


@dataclass(frozen=True, slots=True)
class _SafeHttpRequest:
    """Duck-typed HttpRequest whose repr redacts the complete URL."""

    method: str
    url: str = field(repr=False)
    max_response_bytes: int
    headers: Mapping[str, str]
    body: bytes | None = field(default=None, repr=False)

    def __repr__(self) -> str:
        return (
            f"HttpRequest(method={self.method!r}, "
            f"endpoint={endpoint_fingerprint(self.url)!r}, "
            f"max_response_bytes={self.max_response_bytes!r}, "
            f"headers={self.headers!r}, body=<redacted>)"
        )


PageParser = Callable[[object], JsonPage]
PageRequestFactory = Callable[[str], HttpRequest]
Sleeper = Callable[[float], Awaitable[None]]


class HttpTransport:
    """Policy-enforcing injected HTTP/JSON-RPC transport."""

    __slots__ = (
        "_auth",
        "_circuit_breaker",
        "_delegate",
        "_endpoint",
        "_endpoint_policy",
        "_limits",
        "_rate_limiter",
        "_resolver",
        "_retry_policy",
        "_secret_resolver",
        "_sleep",
        "_wall_clock",
    )

    capabilities = frozenset(
        {
            ProviderCapability.HTTP,
            ProviderCapability.JSON_RPC,
            ProviderCapability.PAGINATION,
            ProviderCapability.RETRY_AFTER,
            ProviderCapability.RATE_LIMITED,
            ProviderCapability.CIRCUIT_BREAKER,
            ProviderCapability.SSRF_PROTECTED,
        }
    )

    def __init__(
        self,
        delegate: HttpTransportProtocol,
        *,
        endpoint: ProviderEndpoint | None = None,
        endpoint_policy: EndpointPolicy | None = None,
        address_resolver: AddressResolver | None = None,
        auth: ProviderAuth | None = None,
        secret_resolver: SecretResolver | None = None,
        limits: TransportLimits | None = None,
        retry_policy: RetryPolicy | None = None,
        rate_limiter: RateLimiter | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        sleep: Sleeper = asyncio.sleep,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if not isinstance(delegate, HttpTransportProtocol):
            raise TypeError("delegate must implement the HttpTransport protocol")
        if (auth is None) != (secret_resolver is None):
            raise InvalidRequestError(
                "provider auth and secret resolver must be configured together"
            )
        self._delegate = delegate
        self._endpoint = endpoint
        self._endpoint_policy = endpoint_policy or EndpointPolicy()
        self._resolver = address_resolver or SystemAddressResolver()
        self._auth = auth
        self._secret_resolver = secret_resolver
        self._limits = limits or TransportLimits()
        self._retry_policy = retry_policy or RetryPolicy()
        self._rate_limiter = rate_limiter or RateLimiter()
        self._circuit_breaker = circuit_breaker or CircuitBreaker()
        self._sleep = sleep
        self._wall_clock = wall_clock
        if endpoint is not None:
            self._endpoint_policy.validate_url(endpoint.url)

    def __repr__(self) -> str:
        endpoint_id = self._endpoint.endpoint_id if self._endpoint else "<unbound>"
        return (
            f"HttpTransport(endpoint_id={endpoint_id!r}, "
            f"limits={self._limits!r}, retry_policy={self._retry_policy!r})"
        )

    @property
    def limits(self) -> TransportLimits:
        return self._limits

    def safe_config(self) -> dict[str, object]:
        """Return serializable metadata without URLs, headers, or secret material."""

        return {
            "endpoint": self._endpoint.to_dict() if self._endpoint else None,
            "authentication": self._auth.to_dict() if self._auth else None,
            "capabilities": sorted(capability.value for capability in self.capabilities),
            "limits": {
                name: getattr(self._limits, name)
                for name in self._limits.__dataclass_fields__
            },
            "retry": {
                "max_attempts": self._retry_policy.max_attempts,
                "base_delay_seconds": self._retry_policy.base_delay_seconds,
                "max_delay_seconds": self._retry_policy.max_delay_seconds,
                "max_retry_after_seconds": (
                    self._retry_policy.max_retry_after_seconds
                ),
            },
        }

    def validate_range(self, start: int, end: int) -> range:
        """Validate an inclusive, non-negative, finite ledger range."""

        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in (start, end)
        ):
            raise InvalidRequestError("provider range positions must be non-negative")
        if end < start:
            raise InvalidRequestError("provider range end precedes its start")
        if end - start + 1 > self._limits.max_range_size:
            raise ResourceLimitError("provider range exceeds max_range_size")
        return range(start, end + 1)

    def _bounded_context(self, context: OperationContext) -> OperationContext:
        now = self._wall_clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise InvalidRequestError("transport clock must be timezone-aware")
        local_deadline = now + timedelta(seconds=self._limits.operation_timeout_seconds)
        deadline = (
            min(context.deadline, local_deadline)
            if context.deadline is not None
            else local_deadline
        )
        return OperationContext(
            context.request_id,
            limits=RequestLimits(
                max_items=min(context.limits.max_items, self._limits.max_items),
                max_pages=min(context.limits.max_pages, self._limits.max_pages),
                max_requests=min(
                    context.limits.max_requests,
                    context.limits.max_pages,
                    self._limits.max_pages,
                ),
                max_response_bytes=min(
                    context.limits.max_response_bytes,
                    self._limits.max_response_bytes,
                ),
            ),
            deadline=deadline,
            cancellation=context.cancellation,
        )

    def _validate_bound_endpoint(self, url: str) -> None:
        if self._endpoint is None:
            return
        expected = urlsplit(self._endpoint.url)
        actual = urlsplit(url)
        expected_port = expected.port or (443 if expected.scheme == "https" else 80)
        actual_port = actual.port or (443 if actual.scheme == "https" else 80)
        if (
            expected.scheme.lower(),
            (expected.hostname or "").rstrip(".").lower(),
            expected_port,
        ) != (
            actual.scheme.lower(),
            (actual.hostname or "").rstrip(".").lower(),
            actual_port,
        ):
            raise InvalidRequestError(
                safe_exception_text(
                    "request endpoint differs from configured provider", endpoint=url
                )
            )

    async def _validate_endpoint(
        self,
        url: str,
        *,
        context: OperationContext,
    ) -> None:
        parsed = self._endpoint_policy.validate_url(url)
        self._validate_bound_endpoint(url)
        context.check_active(now=self._wall_clock)
        hostname = parsed.hostname
        assert hostname is not None
        try:
            socket.inet_pton(socket.AF_INET, hostname)
            addresses = (hostname,)
        except OSError:
            try:
                socket.inet_pton(socket.AF_INET6, hostname)
                addresses = (hostname,)
            except OSError:
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                remaining = context.remaining_seconds(now=self._wall_clock)
                timeout = min(
                    self._limits.request_timeout_seconds,
                    remaining if remaining is not None else self._limits.request_timeout_seconds,
                )
                if timeout <= 0:
                    raise DeadlineExceededError(
                        "provider DNS resolution exceeded its deadline"
                    )
                try:
                    addresses = await asyncio.wait_for(
                        self._resolver.resolve(hostname, port),
                        timeout=timeout,
                    )
                except asyncio.CancelledError:
                    raise
                except TimeoutError:
                    raise TransientProviderError(
                        safe_exception_text(
                            "provider DNS resolution timed out", endpoint=url
                        )
                    ) from None
                except Exception:
                    raise TransientProviderError(
                        safe_exception_text("provider DNS resolution failed", endpoint=url)
                    ) from None
        self._endpoint_policy.validate_resolved_addresses(url, addresses)

    async def _authorized_headers(
        self,
        request: HttpRequest,
        *,
        context: OperationContext,
    ) -> MappingProxyType[str, str]:
        headers: dict[str, str] = dict(request.headers)
        configured_auth_name = (
            self._auth.header_name.lower() if self._auth is not None else None
        )
        if any(
            key.lower() in _CREDENTIAL_HEADER_NAMES
            or key.lower() == configured_auth_name
            for key in headers
        ):
            raise InvalidRequestError(
                "provider credential headers require a SecretReference"
            )
        if self._auth is None:
            return MappingProxyType(headers)
        assert self._secret_resolver is not None
        try:
            secret = await self._secret_resolver.resolve(
                self._auth.secret_reference,
                context=context,
            )
            decoded = secret.value.decode("utf-8")
        except UnicodeDecodeError:
            raise SecretResolutionError(
                "provider authentication secret is not valid UTF-8"
            ) from None
        if "\r" in decoded or "\n" in decoded:
            raise SecretResolutionError(
                "provider authentication secret contains invalid characters"
            )
        headers[self._auth.header_name] = SecretHeaderValue(
            f"{self._auth.prefix}{decoded}"
        )
        return MappingProxyType(headers)

    async def request(
        self,
        request: HttpRequest,
        *,
        context: OperationContext,
    ) -> HttpResponse:
        """Execute one request under finite security and availability budgets."""

        bounded = self._bounded_context(context)
        bounded.check_active(now=self._wall_clock)
        if request.max_response_bytes > bounded.limits.max_response_bytes:
            raise ResourceLimitError(
                "request max_response_bytes exceeds the transport budget"
            )
        if request.body is not None and len(request.body) > self._limits.max_request_bytes:
            raise ResourceLimitError("request body exceeds max_request_bytes")
        await self._validate_endpoint(request.url, context=bounded)
        headers = await self._authorized_headers(request, context=bounded)
        safe_request = _SafeHttpRequest(
            method=request.method,
            url=request.url,
            max_response_bytes=request.max_response_bytes,
            headers=headers,
            body=request.body,
        )
        self._circuit_breaker.before_request()

        last_error: TransientProviderError | None = None
        for attempt in range(1, self._retry_policy.max_attempts + 1):
            bounded.check_active(now=self._wall_clock)
            await self._rate_limiter.acquire(context=bounded)
            remaining = bounded.remaining_seconds(now=self._wall_clock)
            timeout = min(
                self._limits.request_timeout_seconds,
                remaining if remaining is not None else self._limits.request_timeout_seconds,
            )
            if timeout <= 0:
                self._circuit_breaker.record_failure()
                raise DeadlineExceededError("provider request exceeded its deadline")
            retry_after: float | None = None
            try:
                response = await asyncio.wait_for(
                    self._delegate.request(safe_request, context=bounded),
                    timeout=timeout,
                )
            except asyncio.CancelledError:
                raise
            except OperationCancelledError:
                raise
            except TimeoutError:
                last_error = TransientProviderError(
                    safe_exception_text(
                        "provider request timed out", endpoint=request.url
                    )
                )
            except (ConnectionError, OSError):
                last_error = TransientProviderError(
                    safe_exception_text(
                        "provider connection failed", endpoint=request.url
                    )
                )
            except ThrottledProviderError as exc:
                retry_after = (
                    None
                    if exc.retry_after is None
                    else min(
                        max(0.0, exc.retry_after),
                        self._retry_policy.max_retry_after_seconds,
                    )
                )
                last_error = ThrottledProviderError(
                    safe_exception_text(
                        "provider throttled the request", endpoint=request.url
                    ),
                    retry_after=retry_after,
                )
            except TransientProviderError:
                last_error = TransientProviderError(
                    safe_exception_text(
                        "provider request failed transiently", endpoint=request.url
                    )
                )
            except ProviderError:
                raise PermanentProviderError(
                    safe_exception_text(
                        "provider delegate failed", endpoint=request.url
                    )
                ) from None
            except Exception:
                raise PermanentProviderError(
                    safe_exception_text(
                        "provider delegate failed", endpoint=request.url
                    )
                ) from None
            else:
                if not isinstance(response, HttpResponse):
                    raise PermanentProviderError(
                        safe_exception_text(
                            "provider returned an invalid response", endpoint=request.url
                        )
                    )
                if len(response.body) > request.max_response_bytes:
                    self._circuit_breaker.record_failure()
                    raise ResourceLimitError(
                        safe_exception_text(
                            "provider response exceeded its byte budget",
                            endpoint=request.url,
                        )
                    )
                disposition = self._retry_policy.classify_status(response.status)
                if disposition is RetryDisposition.SUCCESS:
                    self._circuit_breaker.record_success()
                    return response
                if disposition is RetryDisposition.PERMANENT:
                    self._circuit_breaker.record_permanent_failure()
                    raise PermanentProviderError(
                        safe_exception_text(
                            "provider returned a permanent HTTP error",
                            endpoint=request.url,
                        )
                    )
                retry_after = self._retry_policy.retry_after_seconds(
                    response.headers,
                    now=self._wall_clock(),
                )
                error_type = (
                    ThrottledProviderError
                    if disposition is RetryDisposition.THROTTLED
                    else TransientProviderError
                )
                if error_type is ThrottledProviderError:
                    last_error = ThrottledProviderError(
                        safe_exception_text(
                            "provider throttled the request", endpoint=request.url
                        ),
                        retry_after=retry_after,
                    )
                else:
                    last_error = TransientProviderError(
                        safe_exception_text(
                            "provider returned a transient HTTP error",
                            endpoint=request.url,
                        )
                    )

            if attempt >= self._retry_policy.max_attempts:
                break
            delay = self._retry_policy.delay_seconds(
                attempt,
                retry_after=retry_after,
            )
            remaining = bounded.remaining_seconds(now=self._wall_clock)
            if remaining is not None and delay >= remaining:
                break
            if delay:
                await self._sleep(delay)

        self._circuit_breaker.record_failure()
        assert last_error is not None
        raise last_error

    async def request_json(
        self,
        request: HttpRequest,
        *,
        context: OperationContext,
    ) -> object:
        """Execute and strictly decode a JSON response."""

        response = await self.request(request, context=context)
        content_type = next(
            (
                value.split(";", 1)[0].strip().lower()
                for key, value in response.headers.items()
                if key.lower() == "content-type"
            ),
            None,
        )
        if content_type not in {_JSON_CONTENT_TYPE, "application/json-rpc"}:
            raise PermanentProviderError(
                safe_exception_text(
                    "provider response is not JSON", endpoint=request.url
                )
            )
        try:
            text = response.body.decode("utf-8")
            return json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise PermanentProviderError(
                safe_exception_text(
                    "provider returned malformed JSON", endpoint=request.url
                )
            ) from None

    async def json_rpc(
        self,
        url: str,
        method: str,
        params: Mapping[str, object] | Sequence[object],
        *,
        context: OperationContext,
        request_id: int | str = 1,
        headers: Mapping[str, str] | None = None,
    ) -> object:
        """Execute a bounded JSON-RPC 2.0 call and validate its envelope."""

        if (
            not isinstance(method, str)
            or not method
            or len(method) > 128
            or any(character.isspace() for character in method)
        ):
            raise InvalidRequestError("JSON-RPC method is invalid")
        if isinstance(request_id, bool) or not isinstance(request_id, (int, str)):
            raise InvalidRequestError("JSON-RPC request id must be an integer or string")
        try:
            body = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": params,
                    "id": request_id,
                },
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError):
            raise InvalidRequestError(
                "JSON-RPC params are not serializable"
            ) from None
        request = HttpRequest(
            "POST",
            url,
            min(context.limits.max_response_bytes, self._limits.max_response_bytes),
            headers={
                "accept": _JSON_CONTENT_TYPE,
                "content-type": _JSON_CONTENT_TYPE,
                **dict(headers or {}),
            },
            body=body,
        )
        payload = await self.request_json(request, context=context)
        if (
            not isinstance(payload, Mapping)
            or payload.get("jsonrpc") != "2.0"
            or payload.get("id") != request_id
            or ("result" in payload) == ("error" in payload)
        ):
            raise PermanentProviderError(
                safe_exception_text(
                    "provider returned an invalid JSON-RPC envelope", endpoint=url
                )
            )
        if "error" in payload:
            raise PermanentProviderError(
                safe_exception_text("provider returned a JSON-RPC error", endpoint=url)
            )
        return payload["result"]

    async def paginate_json(
        self,
        initial_request: HttpRequest,
        *,
        context: OperationContext,
        parse_page: PageParser,
        request_for_cursor: PageRequestFactory,
    ) -> AsyncIterator[tuple[object, ...]]:
        """Yield parsed pages while enforcing page/item/request and cycle bounds."""

        bounded = self._bounded_context(context)
        max_pages = min(
            bounded.limits.max_pages,
            bounded.limits.max_requests,
            self._limits.max_pages,
        )
        max_items = min(bounded.limits.max_items, self._limits.max_items)
        request = initial_request
        seen_cursors: set[str] = set()
        item_count = 0

        for _page_number in range(1, max_pages + 1):
            bounded.check_active(now=self._wall_clock)
            payload = await self.request_json(request, context=bounded)
            try:
                page = parse_page(payload)
            except (InvalidRequestError, ResourceLimitError):
                raise
            except Exception:
                raise PermanentProviderError(
                    safe_exception_text(
                        "provider page could not be parsed", endpoint=request.url
                    )
                ) from None
            if not isinstance(page, JsonPage):
                raise PermanentProviderError(
                    safe_exception_text(
                        "provider page parser returned an invalid page",
                        endpoint=request.url,
                    )
                )
            item_count += len(page.items)
            if item_count > max_items:
                raise ResourceLimitError("provider pagination exceeded max_items")
            yield page.items
            if page.next_cursor is None:
                return
            if page.next_cursor in seen_cursors:
                raise ResourceLimitError("provider pagination cursor loop detected")
            seen_cursors.add(page.next_cursor)
            try:
                request = request_for_cursor(page.next_cursor)
            except Exception:
                raise InvalidRequestError(
                    "pagination request factory rejected a cursor"
                ) from None
            if not isinstance(request, HttpRequest):
                raise InvalidRequestError(
                    "pagination request factory must return HttpRequest"
                )
        raise ResourceLimitError("provider pagination exceeded max_pages")


__all__ = [
    "AddressResolver",
    "HttpTransport",
    "JsonPage",
    "ProviderAuth",
    "ProviderCapability",
    "ProviderEndpoint",
    "SystemAddressResolver",
    "TransportLimits",
]
