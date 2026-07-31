"""Deterministic tests for bounded wallet provider transport controls."""

from __future__ import annotations

import asyncio
import email.utils
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback
from datetime import datetime, timedelta, timezone

import pytest

from ipfs_datasets_py.processors.wallets.errors import (
    DeadlineExceededError,
    InvalidRequestError,
    OperationCancelledError,
    ResourceLimitError,
)
from ipfs_datasets_py.processors.wallets.protocols import (
    HttpRequest,
    HttpResponse,
    OperationContext,
    RequestLimits,
)
from ipfs_datasets_py.processors.wallets.providers.http import (
    HttpTransport,
    JsonPage,
    ProviderAuth,
    ProviderEndpoint,
    TransportLimits,
)
from ipfs_datasets_py.processors.wallets.providers.rate_limit import (
    RateLimitPolicy,
    RateLimiter,
)
from ipfs_datasets_py.processors.wallets.providers.retry import (
    CircuitBreaker,
    CircuitBreakerPolicy,
    CircuitOpenError,
    CircuitState,
    PermanentProviderError,
    RetryPolicy,
    TransientProviderError,
)
from ipfs_datasets_py.processors.wallets.security import (
    EndpointPolicy,
    SecretReference,
    SecretResolver,
)


BASE_URL = "https://rpc.provider.example/v1/wallet?network=mainnet"
PUBLIC_ADDRESS = "1.1.1.1"


class Cancellation:
    def __init__(self, cancelled: bool = False) -> None:
        self.cancelled = cancelled


class FakeTime:
    def __init__(self) -> None:
        self.seconds = 0.0
        self.sleeps: list[float] = []
        self.origin = datetime(2030, 1, 1, tzinfo=timezone.utc)

    def monotonic(self) -> float:
        return self.seconds

    def wall(self) -> datetime:
        return self.origin + timedelta(seconds=self.seconds)

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.seconds += seconds


class FakeResolver:
    def __init__(self, *addresses: str) -> None:
        self.addresses = addresses or (PUBLIC_ADDRESS,)
        self.calls: list[tuple[str, int]] = []

    async def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
        self.calls.append((hostname, port))
        return self.addresses


class FakeDelegate:
    def __init__(self, *outcomes: object) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[object] = []

    async def request(
        self, request: HttpRequest, *, context: OperationContext
    ) -> HttpResponse:
        context.check_active()
        self.requests.append(request)
        if not self.outcomes:
            raise AssertionError("fake delegate has no response")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, HttpResponse)
        return outcome


class HangingDelegate:
    def __init__(self) -> None:
        self.calls = 0

    async def request(
        self, request: HttpRequest, *, context: OperationContext
    ) -> HttpResponse:
        self.calls += 1
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


def response(
    status: int = 200,
    body: bytes = b"{}",
    headers: dict[str, str] | None = None,
) -> HttpResponse:
    return HttpResponse(
        status,
        headers or {"content-type": "application/json"},
        body,
    )


def context(
    *,
    cancellation: Cancellation | None = None,
    max_pages: int = 5,
    max_items: int = 20,
) -> OperationContext:
    return OperationContext(
        "transport-test",
        limits=RequestLimits(
            max_items=max_items,
            max_pages=max_pages,
            max_requests=max_pages,
            max_response_bytes=1_024,
        ),
        cancellation=cancellation,
    )


def request(url: str = BASE_URL, *, max_bytes: int = 1_024) -> HttpRequest:
    return HttpRequest("GET", url, max_bytes, headers={"accept": "application/json"})


def transport(
    delegate: object,
    *,
    fake_time: FakeTime | None = None,
    resolver: FakeResolver | None = None,
    retry_policy: RetryPolicy | None = None,
    rate_limiter: RateLimiter | None = None,
    circuit_breaker: CircuitBreaker | None = None,
    auth: ProviderAuth | None = None,
    secret_resolver: SecretResolver | None = None,
    limits: TransportLimits | None = None,
) -> HttpTransport:
    clock = fake_time or FakeTime()
    return HttpTransport(
        delegate,  # type: ignore[arg-type]
        endpoint=ProviderEndpoint(BASE_URL, "fixture"),
        endpoint_policy=EndpointPolicy(
            allowed_hosts=frozenset({"rpc.provider.example"})
        ),
        address_resolver=resolver or FakeResolver(),
        auth=auth,
        secret_resolver=secret_resolver,
        limits=limits
        or TransportLimits(
            max_request_bytes=1_024,
            max_response_bytes=1_024,
            max_pages=5,
            max_items=20,
            max_range_size=100,
            request_timeout_seconds=2,
            operation_timeout_seconds=10,
        ),
        retry_policy=retry_policy
        or RetryPolicy(
            max_attempts=3,
            base_delay_seconds=1,
            max_delay_seconds=4,
            jitter_fraction=0,
        ),
        rate_limiter=rate_limiter
        or RateLimiter(
            RateLimitPolicy(requests_per_second=100, burst=100),
            clock=clock.monotonic,
            sleep=clock.sleep,
        ),
        circuit_breaker=circuit_breaker
        or CircuitBreaker(
            CircuitBreakerPolicy(failure_threshold=2, recovery_timeout_seconds=5),
            clock=clock.monotonic,
        ),
        sleep=clock.sleep,
        wall_clock=clock.wall,
    )


def test_import_performs_no_network_or_secret_resolution() -> None:
    project_root = Path(__file__).resolve().parents[4]
    script = """
import socket
def forbidden(*args, **kwargs):
    raise AssertionError("network I/O during import")
socket.getaddrinfo = forbidden
import ipfs_datasets_py.processors.wallets.security
import ipfs_datasets_py.processors.wallets.providers.http
import ipfs_datasets_py.processors.wallets.providers.retry
import ipfs_datasets_py.processors.wallets.providers.rate_limit
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(project_root)
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_success_validates_dns_and_returns_bounded_response() -> None:
    delegate = FakeDelegate(response(body=b'{"ok":true}'))
    resolver = FakeResolver()
    value = asyncio.run(
        transport(delegate, resolver=resolver).request_json(
            request(), context=context()
        )
    )
    assert value == {"ok": True}
    assert resolver.calls == [("rpc.provider.example", 443)]
    assert len(delegate.requests) == 1
    assert BASE_URL not in repr(delegate.requests[0])


def test_malformed_json_and_json_rpc_envelopes_fail_safely() -> None:
    malformed = transport(FakeDelegate(response(body=b"{broken")))
    with pytest.raises(PermanentProviderError, match="malformed JSON") as caught:
        asyncio.run(malformed.request_json(request(), context=context()))
    assert BASE_URL not in str(caught.value)
    assert "{broken" not in str(caught.value)

    invalid_envelope = transport(
        FakeDelegate(response(body=b'{"jsonrpc":"2.0","id":2,"result":true}'))
    )
    with pytest.raises(PermanentProviderError, match="invalid JSON-RPC envelope"):
        asyncio.run(
            invalid_envelope.json_rpc(
                BASE_URL,
                "eth_blockNumber",
                [],
                request_id=1,
                context=context(),
            )
        )


def test_timeout_is_retried_only_to_the_finite_attempt_budget() -> None:
    delegate = HangingDelegate()
    limits = TransportLimits(
        max_request_bytes=1_024,
        max_response_bytes=1_024,
        max_pages=2,
        max_items=20,
        max_range_size=100,
        request_timeout_seconds=0.01,
        operation_timeout_seconds=1,
    )
    retry = RetryPolicy(
        max_attempts=2,
        base_delay_seconds=0,
        max_delay_seconds=0,
        jitter_fraction=0,
    )
    with pytest.raises(TransientProviderError, match="timed out"):
        asyncio.run(
            transport(delegate, limits=limits, retry_policy=retry).request(
                request(), context=context(max_pages=2)
            )
        )
    assert delegate.calls == 2


def test_cancellation_stops_before_dns_or_delegate_io() -> None:
    delegate = FakeDelegate(response())
    resolver = FakeResolver()
    with pytest.raises(OperationCancelledError):
        asyncio.run(
            transport(delegate, resolver=resolver).request(
                request(),
                context=context(cancellation=Cancellation(cancelled=True)),
            )
        )
    assert resolver.calls == []
    assert delegate.requests == []


def test_retry_after_throttling_uses_clamped_server_delay() -> None:
    fake_time = FakeTime()
    delegate = FakeDelegate(
        response(429, headers={"Retry-After": "50"}),
        response(body=b'{"ok":true}'),
    )
    retry = RetryPolicy(
        max_attempts=2,
        base_delay_seconds=1,
        max_delay_seconds=1,
        max_retry_after_seconds=3,
        jitter_fraction=0,
    )
    result = asyncio.run(
        transport(
            delegate,
            fake_time=fake_time,
            retry_policy=retry,
        ).request_json(request(), context=context())
    )
    assert result == {"ok": True}
    assert fake_time.sleeps == [3]


def test_retry_policy_handles_http_dates_and_deterministic_jitter_bounds() -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    retry = RetryPolicy(
        max_attempts=3,
        base_delay_seconds=2,
        max_delay_seconds=10,
        max_retry_after_seconds=3,
        jitter_fraction=0.5,
    )
    assert retry.retry_after_seconds(
        {"retry-after": email.utils.format_datetime(now + timedelta(seconds=20))},
        now=now,
    ) == 3
    assert retry.delay_seconds(1, random_value=0) == 1
    assert retry.delay_seconds(1, random_value=1) == 3


def test_transient_errors_retry_but_permanent_errors_do_not() -> None:
    retry = RetryPolicy(
        max_attempts=3,
        base_delay_seconds=0,
        max_delay_seconds=0,
        jitter_fraction=0,
    )
    transient_delegate = FakeDelegate(response(503), response())
    asyncio.run(
        transport(transient_delegate, retry_policy=retry).request(
            request(), context=context()
        )
    )
    assert len(transient_delegate.requests) == 2

    permanent_delegate = FakeDelegate(response(401), response())
    with pytest.raises(PermanentProviderError, match="permanent HTTP error"):
        asyncio.run(
            transport(permanent_delegate, retry_policy=retry).request(
                request(), context=context()
            )
        )
    assert len(permanent_delegate.requests) == 1

    redirect_delegate = FakeDelegate(response(302, headers={"location": BASE_URL}))
    with pytest.raises(PermanentProviderError):
        asyncio.run(
            transport(redirect_delegate, retry_policy=retry).request(
                request(), context=context()
            )
        )
    assert len(redirect_delegate.requests) == 1


def test_oversized_request_and_response_fail_closed() -> None:
    wrapper = transport(FakeDelegate(response(body=b"x" * 9)))
    with pytest.raises(ResourceLimitError, match="response exceeded") as caught:
        asyncio.run(
            wrapper.request(request(max_bytes=8), context=context())
        )
    assert BASE_URL not in str(caught.value)

    large_body = HttpRequest(
        "POST",
        BASE_URL,
        100,
        body=b"x" * 1_025,
    )
    with pytest.raises(ResourceLimitError, match="request body"):
        asyncio.run(wrapper.request(large_body, context=context()))


def test_pagination_detects_cursor_loops_and_page_limits() -> None:
    loop_delegate = FakeDelegate(
        response(body=b'{"items":[1],"next":"same"}'),
        response(body=b'{"items":[2],"next":"same"}'),
    )
    wrapper = transport(loop_delegate)

    def parse(payload: object) -> JsonPage:
        assert isinstance(payload, dict)
        return JsonPage(tuple(payload["items"]), payload.get("next"))

    def next_request(cursor: str) -> HttpRequest:
        return request(f"https://rpc.provider.example/v1/page?cursor={cursor}")

    async def collect_loop() -> list[tuple[object, ...]]:
        return [
            page
            async for page in wrapper.paginate_json(
                request(),
                context=context(),
                parse_page=parse,
                request_for_cursor=next_request,
            )
        ]

    with pytest.raises(ResourceLimitError, match="cursor loop"):
        asyncio.run(collect_loop())

    page_delegate = FakeDelegate(
        response(body=b'{"items":[1],"next":"a"}'),
        response(body=b'{"items":[2],"next":"b"}'),
    )
    page_wrapper = transport(page_delegate)

    async def collect_pages() -> list[tuple[object, ...]]:
        return [
            page
            async for page in page_wrapper.paginate_json(
                request(),
                context=context(max_pages=2),
                parse_page=parse,
                request_for_cursor=next_request,
            )
        ]

    with pytest.raises(ResourceLimitError, match="max_pages"):
        asyncio.run(collect_pages())


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "http://rpc.provider.example/v1",
        "https://127.0.0.1/rpc",
        "https://169.254.169.254/latest/meta-data",
        "https://user:password@rpc.provider.example/v1",
        "https://rpc.provider.example:444/v1",
        "https://other.example/v1",
        "https://rpc.provider.example/v1?api_key=plaintext",
    ],
)
def test_unsafe_endpoints_are_rejected_before_delegate_io(unsafe_url: str) -> None:
    delegate = FakeDelegate(response())
    with pytest.raises(InvalidRequestError) as caught:
        asyncio.run(
            transport(delegate).request(request(unsafe_url), context=context())
        )
    assert unsafe_url not in str(caught.value)
    assert delegate.requests == []


def test_dns_rebinding_to_private_address_is_rejected() -> None:
    delegate = FakeDelegate(response())
    with pytest.raises(InvalidRequestError, match="DNS answer is unsafe"):
        asyncio.run(
            transport(
                delegate,
                resolver=FakeResolver(PUBLIC_ADDRESS, "127.0.0.1"),
            ).request(request(), context=context())
        )
    assert delegate.requests == []


def test_token_bucket_throttles_with_injected_clock() -> None:
    fake_time = FakeTime()
    limiter = RateLimiter(
        RateLimitPolicy(
            requests_per_second=2,
            burst=1,
            max_wait_seconds=2,
        ),
        clock=fake_time.monotonic,
        sleep=fake_time.sleep,
    )

    async def exercise() -> None:
        await limiter.acquire(context=context())
        waited = await limiter.acquire(context=context())
        assert waited == 0.5

    asyncio.run(exercise())
    assert fake_time.sleeps == [0.5]


def test_circuit_breaker_opens_then_allows_one_recovery_probe() -> None:
    fake_time = FakeTime()
    breaker = CircuitBreaker(
        CircuitBreakerPolicy(failure_threshold=1, recovery_timeout_seconds=5),
        clock=fake_time.monotonic,
    )
    retry = RetryPolicy(
        max_attempts=1,
        base_delay_seconds=0,
        max_delay_seconds=0,
        jitter_fraction=0,
    )
    delegate = FakeDelegate(response(503), response())
    wrapper = transport(
        delegate,
        fake_time=fake_time,
        retry_policy=retry,
        circuit_breaker=breaker,
    )
    with pytest.raises(TransientProviderError):
        asyncio.run(wrapper.request(request(), context=context()))
    assert breaker.state is CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        asyncio.run(wrapper.request(request(), context=context()))
    assert len(delegate.requests) == 1

    fake_time.seconds = 5
    asyncio.run(wrapper.request(request(), context=context()))
    assert breaker.state is CircuitState.CLOSED
    assert len(delegate.requests) == 2


def test_secret_reference_auth_is_runtime_only_and_all_representations_are_safe() -> None:
    secret = "super-secret-wallet-token"
    endpoint = ProviderEndpoint(BASE_URL, "fixture")
    auth = ProviderAuth(SecretReference("vault://wallet/provider-token"))
    resolver = SecretResolver(lambda reference: secret)
    delegate = FakeDelegate(response())
    wrapper = transport(
        delegate,
        auth=auth,
        secret_resolver=resolver,
    )

    serialized = json.dumps(wrapper.safe_config(), sort_keys=True)
    combined = " ".join(
        [
            repr(endpoint),
            repr(auth),
            repr(resolver),
            repr(wrapper),
            serialized,
        ]
    )
    assert secret not in combined
    assert BASE_URL not in combined
    assert "vault://wallet/provider-token" not in combined
    assert "secret_reference" in serialized
    with pytest.raises(InvalidRequestError, match="SecretReference"):
        ProviderAuth("plaintext")  # type: ignore[arg-type]

    asyncio.run(wrapper.request(request(), context=context()))
    sent = delegate.requests[0]
    assert str(sent.headers["Authorization"]) == f"Bearer {secret}"
    assert secret not in repr(sent)
    assert BASE_URL not in repr(sent)


def test_request_cannot_bypass_secret_reference_auth_with_plaintext_headers() -> None:
    plaintext = HttpRequest(
        "GET",
        BASE_URL,
        1_024,
        headers={"Authorization": "Bearer plaintext"},
    )
    delegate = FakeDelegate(response())
    with pytest.raises(InvalidRequestError, match="SecretReference"):
        asyncio.run(transport(delegate).request(plaintext, context=context()))
    assert delegate.requests == []


def test_secret_resolution_failures_do_not_echo_reference_or_upstream_error() -> None:
    reference = "vault://wallet/provider-token"

    def fail(_reference: str) -> str:
        raise RuntimeError(f"could not resolve {reference} at {BASE_URL}")

    wrapper = transport(
        FakeDelegate(response()),
        auth=ProviderAuth(SecretReference(reference)),
        secret_resolver=SecretResolver(fail),
    )
    with pytest.raises(Exception, match="secret resolution failed") as caught:
        asyncio.run(wrapper.request(request(), context=context()))
    assert reference not in str(caught.value)
    assert BASE_URL not in str(caught.value)
    rendered = "".join(
        traceback.format_exception(
            type(caught.value),
            caught.value,
            caught.value.__traceback__,
        )
    )
    assert reference not in rendered
    assert BASE_URL not in rendered


def test_untrusted_delegate_errors_are_redacted_and_not_chained() -> None:
    secret = "delegate-leaked-secret"
    wrapper = transport(
        FakeDelegate(RuntimeError(f"{BASE_URL}: Authorization: Bearer {secret}"))
    )
    with pytest.raises(PermanentProviderError, match="delegate failed") as caught:
        asyncio.run(wrapper.request(request(), context=context()))
    rendered = "".join(
        traceback.format_exception(
            type(caught.value),
            caught.value,
            caught.value.__traceback__,
        )
    )
    assert BASE_URL not in rendered
    assert secret not in rendered
    assert caught.value.__cause__ is None


def test_every_budget_is_finite_and_range_is_bounded() -> None:
    limits = TransportLimits()
    assert all(
        isinstance(getattr(limits, name), (int, float))
        and getattr(limits, name) > 0
        for name in limits.__dataclass_fields__
    )
    wrapper = transport(FakeDelegate(response()))
    assert list(wrapper.validate_range(10, 12)) == [10, 11, 12]
    with pytest.raises(ResourceLimitError, match="max_range_size"):
        wrapper.validate_range(0, 100)
    with pytest.raises(InvalidRequestError):
        RetryPolicy(max_attempts=0)
    with pytest.raises(InvalidRequestError):
        TransportLimits(request_timeout_seconds=float("inf"))


def test_expired_deadline_stops_before_network_io() -> None:
    delegate = FakeDelegate(response())
    wrapper = transport(delegate)
    expired = OperationContext(
        "expired",
        limits=context().limits,
        deadline=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    with pytest.raises(DeadlineExceededError):
        asyncio.run(wrapper.request(request(), context=expired))
    assert delegate.requests == []
