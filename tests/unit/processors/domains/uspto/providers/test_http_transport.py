"""Unit tests for bounded USPTO ODP HTTP transport (PATLAW-120).

Covers recorded (scripted opener) and fake-server paths for success, pagination,
304, 401/403, 404, 429/quota, 5xx, timeout, oversized body, cancellation, and
redacted diagnostics. No live external network is required.
"""

from __future__ import annotations

import json
import re
import socket
from datetime import datetime, timezone
from typing import Any

import pytest

from ipfs_datasets_py.processors.domains.uspto.providers.base import (
    API_KEY_HEADER,
    ApiKeySecret,
    CancellationToken,
    ConditionalCache,
    HttpRequest,
    ProviderHttpClient,
    ProviderOutcomeKind,
    RecordedExchange,
    RecordedHttpTransport,
    RetryPolicy,
    contains_secret_leak,
    sanitize_headers,
)
from ipfs_datasets_py.processors.domains.uspto.providers.credential_resolver import (
    CredentialResolver,
)
from ipfs_datasets_py.processors.domains.uspto.providers.http_transport import (
    DEFAULT_ALLOWED_HOSTS,
    HTTP_TRANSPORT_SCHEMA_VERSION,
    BoundedHttpTransport,
    BoundedTransportLimits,
    FakeOdpHttpServer,
    HostAllowlistPolicy,
    ScriptedOpener,
    TransportNetworkError,
    TransportPolicyError,
    TransportResponseTooLargeError,
    TransportTimeoutError,
    build_bounded_provider_client,
    classify_transport_status,
    endpoint_fingerprint,
    parse_retry_after_header,
    quota_headers_diagnostic,
)

# Synthetic canary — not a live credential.
SECRET = "test-odp-canary-key-DO-NOT-LEAK-7c4e"
SECRET_REF = "vault:odp-test-key"
APP_PATH = "/api/v1/patent/applications/16123456"


def _request_header(request: object, name: str) -> str | None:
    """Read a header from urllib.request.Request regardless of casing."""

    target = name.lower()
    headers = getattr(request, "headers", None) or {}
    for key, value in dict(headers).items():
        if str(key).lower() == target:
            return str(value)
    unredir = getattr(request, "unredirected_hdrs", None) or {}
    for key, value in dict(unredir).items():
        if str(key).lower() == target:
            return str(value)
    getter = getattr(request, "get_header", None)
    if callable(getter):
        for candidate in (name, name.title(), name.capitalize(), name.lower()):
            value = getter(candidate)
            if value is not None:
                return str(value)
    return None


def _assert_no_secret(obj: object, *, secret: str = SECRET) -> None:
    text = obj if isinstance(obj, str) else json.dumps(obj, default=str)
    assert secret not in text
    assert "DO-NOT-LEAK" not in text
    assert not re.search(
        r"x-api-key['\"]?\s*[:=]\s*['\"]?(?!<redacted>)[A-Za-z0-9_\-]{8,}",
        text,
        re.I,
    )
    assert not contains_secret_leak(text, secret=secret)


def _json_body(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _scripted_transport(
    opener: ScriptedOpener,
    *,
    max_response_bytes: int = 64 * 1024,
    timeout: float = 2.0,
    cancellation: CancellationToken | None = None,
    credential_resolver: CredentialResolver | None = None,
    credential_ref: str | ApiKeySecret | None = None,
    policy: HostAllowlistPolicy | None = None,
) -> BoundedHttpTransport:
    return BoundedHttpTransport(
        policy=policy
        or HostAllowlistPolicy(
            allowed_hosts=frozenset({"api.uspto.gov"}),
            allowed_ports=frozenset({443}),
            require_https=True,
        ),
        limits=BoundedTransportLimits(
            max_response_bytes=max_response_bytes,
            request_timeout_seconds=timeout,
        ),
        opener=opener,
        cancellation=cancellation,
        credential_resolver=credential_resolver,
        credential_ref=credential_ref,
    )


# ---------------------------------------------------------------------------
# Policy / config
# ---------------------------------------------------------------------------


def test_schema_version_and_safe_config_redact_secrets() -> None:
    resolver = CredentialResolver.from_mapping({SECRET_REF.split(":", 1)[1]: SECRET})
    transport = BoundedHttpTransport(
        credential_resolver=resolver,
        credential_ref=SECRET_REF,
    )
    cfg = transport.safe_config()
    assert cfg["schema_version"] == HTTP_TRANSPORT_SCHEMA_VERSION
    assert cfg["policy"]["allowed_hosts"] == sorted(DEFAULT_ALLOWED_HOSTS)
    assert SECRET not in json.dumps(cfg)
    assert cfg["credential_ref"]["scheme"] == "vault"
    assert cfg["credential_ref"]["reference_id"] == "odp-test-key"
    _assert_no_secret(cfg)
    _assert_no_secret(transport.diagnostic_dict(secret=SECRET))
    _assert_no_secret(repr(transport))


def test_host_allowlist_rejects_non_odp_and_ssrf_shapes() -> None:
    policy = HostAllowlistPolicy.odp_default()
    with pytest.raises(TransportPolicyError):
        policy.validate_url("https://evil.example/api")
    with pytest.raises(TransportPolicyError):
        policy.validate_url("http://api.uspto.gov/api")  # http without loopback
    with pytest.raises(TransportPolicyError):
        policy.validate_url("https://127.0.0.1/secret")
    with pytest.raises(TransportPolicyError):
        policy.validate_url("https://api.uspto.gov/x?api_key=abc")
    with pytest.raises(TransportPolicyError):
        policy.validate_url("https://user:pass@api.uspto.gov/x")
    # Allowlisted host is accepted.
    parsed = policy.validate_url("https://api.uspto.gov/api/v1/patent/applications/1")
    assert parsed.hostname == "api.uspto.gov"


def test_endpoint_fingerprint_stable_and_non_reversible() -> None:
    a = endpoint_fingerprint("https://api.uspto.gov/api/v1/x")
    b = endpoint_fingerprint("https://api.uspto.gov/api/v1/x")
    assert a == b
    assert a.startswith("endpoint:")
    assert "uspto" not in a


# ---------------------------------------------------------------------------
# Scripted opener: success, 304, auth, quota, 5xx, size, cancel, timeout
# ---------------------------------------------------------------------------


def test_scripted_success_200_and_header_attachment() -> None:
    opener = ScriptedOpener()
    opener.add(
        status=200,
        body={"count": 1, "patentFileWrapperDataBag": [{"applicationNumberText": "16123456"}]},
        headers={"ETag": '"v1"', "Content-Type": "application/json"},
    )
    resolver = CredentialResolver.from_mapping({"odp-test-key": SECRET})
    transport = _scripted_transport(
        opener,
        credential_resolver=resolver,
        credential_ref=SECRET_REF,
    )
    response = transport.request(
        HttpRequest(method="GET", url=f"https://api.uspto.gov{APP_PATH}")
    )
    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert transport.request_count == 1
    # Credential attached at request time via opener-captured Request.
    assert len(opener.requests) == 1
    sent = opener.requests[0]
    assert _request_header(sent, API_KEY_HEADER) == SECRET
    # Diagnostics never include the secret.
    diag = transport.diagnostic_dict(
        last_request=HttpRequest(
            method="GET",
            url=f"https://api.uspto.gov{APP_PATH}",
            headers={API_KEY_HEADER: SECRET},
        ),
        secret=SECRET,
    )
    _assert_no_secret(diag)


def test_scripted_not_modified_304() -> None:
    opener = ScriptedOpener()
    opener.add(status=304, body=b"", headers={"ETag": '"v1"'})
    transport = _scripted_transport(opener)
    response = transport.request(
        HttpRequest(
            method="GET",
            url=f"https://api.uspto.gov{APP_PATH}",
            headers={"If-None-Match": '"v1"'},
        )
    )
    assert response.status_code == 304
    assert response.body == b""
    assert classify_transport_status(304) is ProviderOutcomeKind.NOT_MODIFIED


def test_scripted_auth_and_not_found_matrix() -> None:
    cases = [
        (401, ProviderOutcomeKind.UNAUTHORIZED),
        (403, ProviderOutcomeKind.FORBIDDEN),
        (404, ProviderOutcomeKind.NOT_FOUND),
    ]
    for status, kind in cases:
        opener = ScriptedOpener()
        opener.add(
            status=status,
            body={"error": f"status-{status}", "message": f"fail-{status}"},
        )
        transport = _scripted_transport(opener)
        response = transport.request(
            HttpRequest(method="GET", url=f"https://api.uspto.gov{APP_PATH}")
        )
        assert response.status_code == status
        assert classify_transport_status(status) is kind
        _assert_no_secret(response.text())


def test_scripted_429_quota_headers() -> None:
    opener = ScriptedOpener()
    opener.add(
        status=429,
        body={"error": "rate_limited"},
        headers={
            "Retry-After": "3",
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Limit": "100",
        },
    )
    transport = _scripted_transport(opener)
    response = transport.request(
        HttpRequest(method="GET", url=f"https://api.uspto.gov{APP_PATH}")
    )
    assert response.status_code == 429
    assert classify_transport_status(429) is ProviderOutcomeKind.RATE_LIMITED
    assert parse_retry_after_header(response.headers) == 3.0
    quota = quota_headers_diagnostic(response.headers)
    assert "Retry-After" in quota or "retry-after" in {k.lower() for k in quota}
    _assert_no_secret(quota)


def test_scripted_5xx_upstream() -> None:
    for status in (500, 502, 503):
        opener = ScriptedOpener()
        opener.add(status=status, body={"error": "upstream"})
        transport = _scripted_transport(opener)
        response = transport.request(
            HttpRequest(method="GET", url=f"https://api.uspto.gov{APP_PATH}")
        )
        assert response.status_code == status
        assert classify_transport_status(status) is ProviderOutcomeKind.UPSTREAM_ERROR


def test_scripted_timeout() -> None:
    opener = ScriptedOpener()
    opener.add_error(socket.timeout("timed out"))
    transport = _scripted_transport(opener, timeout=0.5)
    with pytest.raises(TransportTimeoutError) as exc_info:
        transport.request(
            HttpRequest(method="GET", url=f"https://api.uspto.gov{APP_PATH}")
        )
    assert exc_info.value.code == "transport_timeout"
    _assert_no_secret(str(exc_info.value))


def test_scripted_timeout_via_delay_exceeding_budget() -> None:
    opener = ScriptedOpener()
    opener.add(status=200, body=b"{}", delay_seconds=5.0)
    transport = _scripted_transport(opener, timeout=0.1)
    with pytest.raises(TransportTimeoutError):
        transport.request(
            HttpRequest(method="GET", url=f"https://api.uspto.gov{APP_PATH}")
        )


def test_scripted_oversized_body() -> None:
    opener = ScriptedOpener()
    opener.add(status=200, body=b"x" * 1000)
    transport = _scripted_transport(opener, max_response_bytes=100)
    with pytest.raises(TransportResponseTooLargeError) as exc_info:
        transport.request(
            HttpRequest(method="GET", url=f"https://api.uspto.gov{APP_PATH}")
        )
    assert exc_info.value.code == "response_too_large"


def test_scripted_cancellation_before_request() -> None:
    opener = ScriptedOpener()
    opener.add(status=200, body=b"{}")
    token = CancellationToken(cancelled=True, reason="user-cancel")
    transport = _scripted_transport(opener, cancellation=token)
    with pytest.raises(Exception) as exc_info:
        transport.request(
            HttpRequest(method="GET", url=f"https://api.uspto.gov{APP_PATH}")
        )
    assert "cancel" in str(exc_info.value).lower() or getattr(
        exc_info.value, "code", ""
    ) == "cancelled"


def test_scripted_network_error_safe_message() -> None:
    opener = ScriptedOpener()
    opener.add_error(ConnectionError(f"connection reset with {SECRET}"))
    transport = _scripted_transport(opener)
    with pytest.raises(TransportNetworkError) as exc_info:
        transport.request(
            HttpRequest(method="GET", url=f"https://api.uspto.gov{APP_PATH}")
        )
    # Message must not echo the exception detail that contained the secret.
    _assert_no_secret(str(exc_info.value))
    assert "ConnectionError" in str(exc_info.value) or "network" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# Recorded transport + ProviderHttpClient (pagination, 304 cache, retries)
# ---------------------------------------------------------------------------


def test_recorded_pagination_multi_page() -> None:
    """Pagination: sequential page requests via recorded exchanges."""

    page1 = {
        "count": 2,
        "nextCursor": "cursor-2",
        "patentFileWrapperDataBag": [
            {"applicationNumberText": "16123456", "page": 1},
        ],
    }
    page2 = {
        "count": 2,
        "nextCursor": None,
        "patentFileWrapperDataBag": [
            {"applicationNumberText": "16123456", "page": 2},
        ],
    }
    transport = RecordedHttpTransport(
        [
            RecordedExchange(
                method="GET",
                path=APP_PATH,
                status=200,
                body=page1,
                query={"offset": "0"},
            ),
            RecordedExchange(
                method="GET",
                path=APP_PATH,
                status=200,
                body=page2,
                query={"offset": "1"},
            ),
        ]
    )
    client = ProviderHttpClient(
        transport,
        api_key=ApiKeySecret(SECRET, reference_id="odp-test"),
        retry_policy=RetryPolicy(max_attempts=1),
    )
    r1 = client.request("GET", APP_PATH, query={"offset": "0"})
    r2 = client.request("GET", APP_PATH, query={"offset": "1"})
    assert r1.ok and r2.ok
    assert r1.payload["nextCursor"] == "cursor-2"
    assert r2.payload["patentFileWrapperDataBag"][0]["page"] == 2
    _assert_no_secret(r1.to_dict())
    _assert_no_secret(r2.to_dict())
    # Stored recorded requests redacted the API key header.
    for req in transport.requests:
        _assert_no_secret(req.sanitized_dict())
        if API_KEY_HEADER in req.headers or "X-API-KEY" in req.headers:
            assert req.headers.get(API_KEY_HEADER, req.headers.get("X-API-KEY")) == "<redacted>"


def test_recorded_304_conditional_cache_via_provider_client() -> None:
    body = {
        "count": 1,
        "patentFileWrapperDataBag": [{"applicationNumberText": "16123456"}],
    }
    transport = RecordedHttpTransport(
        [
            RecordedExchange(
                method="GET",
                path=APP_PATH,
                status=200,
                body=body,
                headers={"ETag": '"abc"', "Last-Modified": "Mon, 03 Aug 2026 12:00:00 GMT"},
            ),
            RecordedExchange(
                method="GET",
                path=APP_PATH,
                status=304,
                body=None,
                headers={"ETag": '"abc"'},
            ),
        ]
    )
    cache = ConditionalCache()
    client = ProviderHttpClient(
        transport,
        api_key=SECRET,
        cache=cache,
        retry_policy=RetryPolicy(max_attempts=1),
    )
    first = client.request("GET", APP_PATH)
    assert first.ok and first.kind is ProviderOutcomeKind.SUCCESS
    second = client.request("GET", APP_PATH)
    assert second.ok
    assert second.kind is ProviderOutcomeKind.NOT_MODIFIED
    assert second.cache_hit is True
    _assert_no_secret(second.to_dict())


def test_recorded_401_403_404_429_5xx_through_client() -> None:
    cases = [
        (401, ProviderOutcomeKind.UNAUTHORIZED),
        (403, ProviderOutcomeKind.FORBIDDEN),
        (404, ProviderOutcomeKind.NOT_FOUND),
        (429, ProviderOutcomeKind.RATE_LIMITED),
        (503, ProviderOutcomeKind.RETRY_BUDGET_EXHAUSTED),  # with max_attempts=1 may be upstream or budget
    ]
    for status, _expected in cases:
        transport = RecordedHttpTransport(
            [
                RecordedExchange(
                    method="GET",
                    path=APP_PATH,
                    status=status,
                    body={"error": f"e{status}"},
                    headers={"Retry-After": "1"} if status == 429 else {},
                )
            ]
        )
        client = ProviderHttpClient(
            transport,
            api_key=SECRET,
            retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.01),
        )
        result = client.request("GET", APP_PATH)
        assert not result.ok or status < 400
        if status == 401:
            assert result.kind is ProviderOutcomeKind.UNAUTHORIZED
        elif status == 403:
            assert result.kind is ProviderOutcomeKind.FORBIDDEN
        elif status == 404:
            assert result.kind is ProviderOutcomeKind.NOT_FOUND
        elif status == 429:
            assert result.kind is ProviderOutcomeKind.RATE_LIMITED
        elif status == 503:
            assert result.kind in {
                ProviderOutcomeKind.UPSTREAM_ERROR,
                ProviderOutcomeKind.RETRY_BUDGET_EXHAUSTED,
            }
        _assert_no_secret(result.to_dict())


def test_recorded_cancellation_via_client() -> None:
    transport = RecordedHttpTransport(
        [RecordedExchange(method="GET", path=APP_PATH, status=200, body={"ok": True})]
    )
    token = CancellationToken(cancelled=True, reason="stop")
    client = ProviderHttpClient(
        transport,
        api_key=SECRET,
        cancellation=token,
        retry_policy=RetryPolicy(max_attempts=1),
    )
    result = client.request("GET", APP_PATH)
    assert result.kind is ProviderOutcomeKind.CANCELLED
    _assert_no_secret(result.to_dict())


# ---------------------------------------------------------------------------
# Fake HTTP server (loopback) — full integration of BoundedHttpTransport
# ---------------------------------------------------------------------------


def test_fake_server_success_pagination_auth_quota_errors() -> None:
    routes = {
        "/ok": {
            "status": 200,
            "body": {"page": 1, "next": "/ok?cursor=2"},
            "headers": {"ETag": '"p1"'},
        },
        "/ok2": {
            "status": 200,
            "body": {"page": 2, "next": None},
        },
        "/deny": {"status": 401, "body": {"error": "unauthorized"}},
        "/forbid": {"status": 403, "body": {"error": "forbidden"}},
        "/missing": {"status": 404, "body": {"error": "not_found"}},
        "/throttle": {
            "status": 429,
            "body": {"error": "quota"},
            "headers": {"Retry-After": "2", "X-RateLimit-Remaining": "0"},
        },
        "/boom": {"status": 500, "body": {"error": "upstream"}},
        "/big": {"status": 200, "body": "Z" * 5000},
    }
    with FakeOdpHttpServer(routes) as server:
        policy = HostAllowlistPolicy.for_loopback_testing(port=server.port)
        resolver = CredentialResolver.from_mapping({"k": SECRET})
        transport = BoundedHttpTransport(
            policy=policy,
            limits=BoundedTransportLimits(
                max_response_bytes=1024,
                request_timeout_seconds=2.0,
            ),
            credential_resolver=resolver,
            credential_ref="vault:k",
        )

        # Success page 1.
        r1 = transport.request(HttpRequest(method="GET", url=server.url("/ok")))
        assert r1.status_code == 200
        assert r1.json()["page"] == 1

        # Pagination page 2.
        r2 = transport.request(HttpRequest(method="GET", url=server.url("/ok2")))
        assert r2.status_code == 200
        assert r2.json()["page"] == 2

        # 304 via If-None-Match.
        r304 = transport.request(
            HttpRequest(
                method="GET",
                url=server.url("/ok"),
                headers={"If-None-Match": '"p1"'},
            )
        )
        assert r304.status_code == 304

        # Auth / access.
        assert transport.request(
            HttpRequest(method="GET", url=server.url("/deny"))
        ).status_code == 401
        assert transport.request(
            HttpRequest(method="GET", url=server.url("/forbid"))
        ).status_code == 403
        assert transport.request(
            HttpRequest(method="GET", url=server.url("/missing"))
        ).status_code == 404

        # 429 quota.
        throttled = transport.request(
            HttpRequest(method="GET", url=server.url("/throttle"))
        )
        assert throttled.status_code == 429
        assert parse_retry_after_header(throttled.headers) == 2.0

        # 5xx.
        assert transport.request(
            HttpRequest(method="GET", url=server.url("/boom"))
        ).status_code == 500

        # Oversized body.
        with pytest.raises(TransportResponseTooLargeError):
            transport.request(HttpRequest(method="GET", url=server.url("/big")))

        # API key arrived on the server without leaking into diagnostics.
        assert any(
            h.get("X-Api-Key") == SECRET or h.get("X-API-KEY") == SECRET
            for h in server.received_headers
        )
        diag = transport.diagnostic_dict(secret=SECRET)
        _assert_no_secret(diag)
        _assert_no_secret(transport.safe_config())


def test_fake_server_timeout() -> None:
    routes = {"/slow": {"status": 200, "body": {"ok": True}, "delay_seconds": 1.5}}
    with FakeOdpHttpServer(routes) as server:
        transport = BoundedHttpTransport(
            policy=HostAllowlistPolicy.for_loopback_testing(port=server.port),
            limits=BoundedTransportLimits(request_timeout_seconds=0.2),
        )
        with pytest.raises(TransportTimeoutError):
            transport.request(
                HttpRequest(
                    method="GET",
                    url=server.url("/slow"),
                    timeout_seconds=0.2,
                )
            )


def test_fake_server_cancellation() -> None:
    routes = {"/ok": {"status": 200, "body": {"ok": True}}}
    with FakeOdpHttpServer(routes) as server:
        token = CancellationToken(cancelled=True, reason="cancel-test")
        transport = BoundedHttpTransport(
            policy=HostAllowlistPolicy.for_loopback_testing(port=server.port),
            cancellation=token,
        )
        with pytest.raises(Exception):
            transport.request(HttpRequest(method="GET", url=server.url("/ok")))


def test_fake_server_policy_blocks_cross_host() -> None:
    with FakeOdpHttpServer({"/ok": {"status": 200, "body": {}}}) as server:
        # Default ODP policy must refuse loopback even if a server is running.
        transport = BoundedHttpTransport()
        with pytest.raises(TransportPolicyError):
            transport.request(HttpRequest(method="GET", url=server.url("/ok")))


# ---------------------------------------------------------------------------
# build_bounded_provider_client wiring
# ---------------------------------------------------------------------------


def test_build_bounded_provider_client_resolves_credential_ref() -> None:
    opener = ScriptedOpener()
    opener.add(
        status=200,
        body={"count": 0, "patentFileWrapperDataBag": []},
    )
    resolver = CredentialResolver.from_mapping({"prod-key": SECRET})
    transport = BoundedHttpTransport(
        opener=opener,
        policy=HostAllowlistPolicy(
            allowed_hosts=frozenset({"api.uspto.gov"}),
            allowed_ports=frozenset({443}),
        ),
    )
    client = build_bounded_provider_client(
        transport=transport,
        credential_resolver=resolver,
        credential_ref="vault:prod-key",
        retry_policy=RetryPolicy(max_attempts=1),
    )
    result = client.request("GET", APP_PATH)
    assert result.ok
    cfg = client.safe_config()
    _assert_no_secret(cfg)
    _assert_no_secret(result.to_dict())
    # Key present on wire via client merge, redacted in recorded views.
    assert opener.requests
    assert _request_header(opener.requests[0], API_KEY_HEADER) == SECRET


def test_sanitize_headers_on_outbound_diagnostics() -> None:
    headers = sanitize_headers({API_KEY_HEADER: SECRET, "Accept": "application/json"})
    assert headers[API_KEY_HEADER] == "<redacted>"
    _assert_no_secret(headers)


def test_classify_and_retry_after_http_date() -> None:
    assert classify_transport_status(200) is ProviderOutcomeKind.SUCCESS
    future = email_http_date_seconds_from_now(30)
    delay = parse_retry_after_header({"Retry-After": future}, max_seconds=60.0)
    assert delay is not None
    assert 0.0 <= delay <= 60.0


def email_http_date_seconds_from_now(seconds: int) -> str:
    from datetime import timedelta
    import email.utils

    when = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    return email.utils.format_datetime(when, usegmt=True)
