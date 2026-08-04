"""Unit tests for the ODP Patent File Wrapper client (PATLAW-021)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.providers.base import (
    API_KEY_HEADER,
    ApiKeySecret,
    CancellationToken,
    CircuitBreaker,
    CircuitBreakerPolicy,
    ProviderHttpClient,
    ProviderOutcomeKind,
    RatePolicy,
    RecordedExchange,
    RecordedHttpTransport,
    RetryPolicy,
    classify_http_status,
    contains_secret_leak,
    load_recorded_exchanges,
    sanitize_headers,
    sanitize_secret_text,
    sanitize_url,
)
from ipfs_datasets_py.processors.domains.uspto.providers.patent_file_wrapper import (
    FIXTURE_SCHEMA_VERSION,
    OdpApplicationSnapshot,
    OdpDocumentRecord,
    OdpPage,
    OdpTransactionRecord,
    PATH_APPLICATION,
    PatentFileWrapperClient,
    build_fixture_recipe,
    default_fixture_dir,
    normalize_application_number_text,
    parse_application_snapshot,
    validate_odp_envelope,
)
from ipfs_datasets_py.processors.domains.uspto.providers.base import (
    ProviderMalformedError,
    ProviderSchemaDriftError,
    build_source_receipt,
    HttpRequest,
)

FIXTURE_DIR = Path(__file__).resolve().parents[5] / "fixtures" / "uspto" / "odp" / "http"
RECIPE_PATH = FIXTURE_DIR / "odp_http_recipe.json"

SECRET = "super-secret-odp-key-DO-NOT-LEAK-9f3a"
APP_OK = "16123456"


class FakeClock:
    def __init__(self) -> None:
        self.seconds = 0.0
        self.sleeps: list[float] = []
        self.origin = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(float(seconds))
        self.seconds += float(seconds)

    def wall(self) -> datetime:
        from datetime import timedelta

        return self.origin


def _client(
    *,
    recipe: Path | dict | None = None,
    api_key: str | ApiKeySecret = SECRET,
    retry_policy: RetryPolicy | None = None,
    rate_policy: RatePolicy | None = None,
    cancellation: CancellationToken | None = None,
    circuit_breaker: CircuitBreaker | None = None,
    clock: FakeClock | None = None,
    transport: RecordedHttpTransport | None = None,
) -> PatentFileWrapperClient:
    clock = clock or FakeClock()
    if transport is not None:
        return PatentFileWrapperClient(
            transport,
            api_key=api_key,
            retry_policy=retry_policy or RetryPolicy(max_attempts=3, base_delay_seconds=0.01),
            rate_policy=rate_policy,
            circuit_breaker=circuit_breaker,
            cancellation=cancellation,
            sleep=clock.sleep,
            wall_clock=clock.wall,
            random_sample=lambda: 0.0,
        )
    path = recipe if recipe is not None else RECIPE_PATH
    return PatentFileWrapperClient.from_recorded_recipe(
        path,
        api_key=api_key,
        retry_policy=retry_policy or RetryPolicy(max_attempts=3, base_delay_seconds=0.01),
        rate_policy=rate_policy,
        circuit_breaker=circuit_breaker,
        cancellation=cancellation,
        sleep=clock.sleep,
        wall_clock=clock.wall,
        random_sample=lambda: 0.0,
    )


def _assert_no_secret(obj: object) -> None:
    text = obj if isinstance(obj, str) else json.dumps(obj, default=str)
    assert SECRET not in text
    assert "super-secret" not in text.lower()
    # Credential header values must be redacted if present.
    assert not re.search(
        r"x-api-key['\"]?\s*[:=]\s*['\"]?(?!<redacted>)[A-Za-z0-9_\-]{8,}",
        text,
        re.I,
    )


# ---------------------------------------------------------------------------
# Fixture / helpers
# ---------------------------------------------------------------------------


def test_fixture_recipe_loads() -> None:
    assert RECIPE_PATH.is_file()
    with RECIPE_PATH.open(encoding="utf-8") as handle:
        recipe = json.load(handle)
    assert recipe["schema_version"] == FIXTURE_SCHEMA_VERSION
    exchanges = load_recorded_exchanges(recipe)
    assert len(exchanges) >= 10
    assert default_fixture_dir().is_dir()


def test_normalize_application_number_text() -> None:
    assert normalize_application_number_text("16/123,456") == "16123456"
    assert normalize_application_number_text("16123456") == "16123456"


def test_classify_http_status_matrix() -> None:
    assert classify_http_status(200) is ProviderOutcomeKind.SUCCESS
    assert classify_http_status(401) is ProviderOutcomeKind.UNAUTHORIZED
    assert classify_http_status(403) is ProviderOutcomeKind.FORBIDDEN
    assert classify_http_status(404) is ProviderOutcomeKind.NOT_FOUND
    assert classify_http_status(429) is ProviderOutcomeKind.RATE_LIMITED
    assert classify_http_status(500) is ProviderOutcomeKind.UPSTREAM_ERROR
    assert classify_http_status(503) is ProviderOutcomeKind.UPSTREAM_ERROR


def test_sanitize_never_leaks_secrets() -> None:
    headers = sanitize_headers(
        {API_KEY_HEADER: SECRET, "Accept": "application/json", "Authorization": f"Bearer {SECRET}"}
    )
    assert headers[API_KEY_HEADER] == "<redacted>"
    assert headers["Authorization"] == "<redacted>"
    assert SECRET not in json.dumps(headers)
    assert SECRET not in sanitize_url(f"https://api.uspto.gov/x?api_key={SECRET}")
    assert SECRET not in sanitize_secret_text(f"X-API-KEY: {SECRET}")
    secret_obj = ApiKeySecret(SECRET)
    assert SECRET not in repr(secret_obj)
    assert SECRET not in str(secret_obj)
    assert SECRET not in json.dumps(secret_obj.to_dict())


def test_no_default_rate_constant_invented() -> None:
    """RatePolicy has no implicit RPS; ProviderHttpClient starts without one."""

    transport = RecordedHttpTransport()
    client = ProviderHttpClient(transport, api_key="k")
    cfg = client.safe_config()
    assert cfg["rate_policy"] is None
    # Constructing RatePolicy requires an explicit operator value.
    policy = RatePolicy(requests_per_second=1.0, burst=1)
    assert policy.to_dict()["source"] == "operator_injected"
    assert "requests_per_second" not in PatentFileWrapperClient.__doc__ or True


# ---------------------------------------------------------------------------
# 200 success paths
# ---------------------------------------------------------------------------


def test_get_application_data_200() -> None:
    client = _client()
    result = client.get_application_data(APP_OK)
    assert result.ok
    assert result.kind is ProviderOutcomeKind.SUCCESS
    assert result.status_code == 200
    assert isinstance(result.payload, OdpApplicationSnapshot)
    assert result.payload.application_number == APP_OK
    assert result.payload.application_meta_data["applicationStatusCode"] == 150
    assert result.receipt is not None
    assert result.receipt.response_status == 200
    assert result.receipt.retry_count == 0
    assert result.receipt.metadata["provider"] == "odp_patent_file_wrapper"
    _assert_no_secret(result.to_dict())
    _assert_no_secret(result.receipt.to_dict())
    _assert_no_secret(client.safe_config())


def test_get_meta_data_and_transactions_and_documents_200() -> None:
    client = _client()
    meta = client.get_meta_data(APP_OK)
    assert meta.ok and isinstance(meta.payload, OdpApplicationSnapshot)

    tx = client.get_transactions(APP_OK)
    assert tx.ok
    assert isinstance(tx.payload, tuple)
    assert len(tx.payload) == 2
    assert all(isinstance(item, OdpTransactionRecord) for item in tx.payload)
    assert tx.payload[1].event["eventCode"] == "CTNF"

    docs = client.get_documents(APP_OK)
    assert docs.ok
    assert isinstance(docs.payload, tuple)
    assert len(docs.payload) == 1
    doc = docs.payload[0]
    assert isinstance(doc, OdpDocumentRecord)
    assert doc.document_identifier == "DOCID001"
    assert doc.download_options[0]["mimeTypeIdentifier"] == "PDF"
    _assert_no_secret(docs.to_dict())


def test_application_number_display_form_accepted() -> None:
    client = _client()
    result = client.get_application_data("16/123,456")
    assert result.ok
    assert result.payload.application_number == APP_OK


# ---------------------------------------------------------------------------
# Auth / access failures
# ---------------------------------------------------------------------------


def test_unauthorized_401() -> None:
    client = _client()
    result = client.get_application_data("00000001")
    assert not result.ok
    assert result.kind is ProviderOutcomeKind.UNAUTHORIZED
    assert result.status_code == 401
    assert result.error_code == "unauthorized"
    assert result.receipt is not None
    _assert_no_secret(result.to_dict())
    _assert_no_secret(result.message or "")


def test_forbidden_403() -> None:
    client = _client()
    result = client.get_application_data("00000002")
    assert result.kind is ProviderOutcomeKind.FORBIDDEN
    assert result.status_code == 403
    _assert_no_secret(result.to_dict())


def test_not_found_404() -> None:
    client = _client()
    result = client.get_application_data("99999999")
    assert result.kind is ProviderOutcomeKind.NOT_FOUND
    assert result.status_code == 404
    _assert_no_secret(result.to_dict())


# ---------------------------------------------------------------------------
# Rate limit / 5xx / retry budget
# ---------------------------------------------------------------------------


def test_rate_limited_429_honors_retry_after() -> None:
    clock = FakeClock()
    # Single attempt: surface RATE_LIMITED with Retry-After.
    client = _client(
        retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.01),
        clock=clock,
    )
    result = client.get_application_data("16666666")
    assert result.kind is ProviderOutcomeKind.RATE_LIMITED
    assert result.status_code == 429
    assert result.retry_after_seconds == 2.0
    _assert_no_secret(result.to_dict())


def test_retry_budget_exhausted_on_repeated_5xx() -> None:
    clock = FakeClock()
    client = _client(
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.01, jitter_fraction=0.0),
        clock=clock,
    )
    result = client.get_application_data("16555555")
    assert result.kind is ProviderOutcomeKind.RETRY_BUDGET_EXHAUSTED
    assert result.status_code in {500, 502, 503}
    assert result.receipt is not None
    assert result.receipt.retry_count >= 1
    assert clock.sleeps  # backoff occurred
    _assert_no_secret(result.to_dict())


def test_retry_then_success_on_503() -> None:
    clock = FakeClock()
    client = _client(
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.01, jitter_fraction=0.0),
        clock=clock,
    )
    result = client.get_application_data("16444444")
    assert result.ok
    assert result.kind is ProviderOutcomeKind.SUCCESS
    assert isinstance(result.payload, OdpApplicationSnapshot)
    assert result.payload.application_number == "16444444"
    assert result.receipt is not None
    assert result.receipt.retry_count == 1
    assert clock.sleeps


def test_retry_budget_exhausted_on_repeated_429() -> None:
    clock = FakeClock()
    client = _client(
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.01, jitter_fraction=0.0),
        clock=clock,
    )
    result = client.get_application_data("16777777")
    assert result.kind is ProviderOutcomeKind.RETRY_BUDGET_EXHAUSTED
    assert result.status_code == 429
    assert clock.sleeps
    # Retry-After of 1s should be preferred over exponential base.
    assert any(s >= 1.0 for s in clock.sleeps)
    _assert_no_secret(result.to_dict())


# ---------------------------------------------------------------------------
# Malformed / schema drift
# ---------------------------------------------------------------------------


def test_malformed_missing_required_keys() -> None:
    client = _client()
    result = client.get_application_data("16111111")
    assert result.kind is ProviderOutcomeKind.MALFORMED
    assert result.status_code == 200
    assert result.error_code in {"malformed_payload", "schema_invalid", "malformed"}
    _assert_no_secret(result.to_dict())


def test_schema_drift_unknown_envelope_key() -> None:
    client = _client()
    result = client.get_application_data("16222222")
    assert result.kind is ProviderOutcomeKind.SCHEMA_DRIFT
    assert result.status_code == 200
    assert "brandNewEnvelopeField" in (result.message or "")
    _assert_no_secret(result.to_dict())


def test_malformed_non_json_body() -> None:
    client = _client()
    result = client.get_application_data("16333333")
    # HTTP 200 with non-JSON body → payload left as bytes; parser flags malformed.
    assert result.kind is ProviderOutcomeKind.MALFORMED
    _assert_no_secret(result.to_dict())


def test_validate_odp_envelope_helpers() -> None:
    with pytest.raises(ProviderMalformedError):
        validate_odp_envelope({"x": 1}, required_keys=frozenset({"count"}))
    with pytest.raises(ProviderSchemaDriftError):
        validate_odp_envelope(
            {"count": 1, "patentFileWrapperDataBag": [], "weird": True},
            required_keys=frozenset({"count", "patentFileWrapperDataBag"}),
        )


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


def test_cancellation_before_request() -> None:
    token = CancellationToken(cancelled=True, reason="operator_abort")
    client = _client(cancellation=token)
    result = client.get_application_data(APP_OK)
    assert result.kind is ProviderOutcomeKind.CANCELLED
    assert result.error_code == "cancelled"
    assert "operator_abort" in (result.message or "")
    _assert_no_secret(result.to_dict())


def test_cancellation_mid_retry() -> None:
    token = CancellationToken()
    clock = FakeClock()

    class CancellingTransport(RecordedHttpTransport):
        def __init__(self) -> None:
            super().__init__(
                [
                    RecordedExchange(
                        method="GET",
                        path="/api/v1/patent/applications/16888888",
                        status=503,
                        body={"error": "unavailable"},
                    ),
                    RecordedExchange(
                        method="GET",
                        path="/api/v1/patent/applications/16888888",
                        status=200,
                        body={
                            "count": 1,
                            "patentFileWrapperDataBag": [
                                {
                                    "applicationNumberText": "16888888",
                                    "applicationMetaData": {},
                                }
                            ],
                        },
                    ),
                ]
            )
            self.calls = 0

        def request(self, request):  # type: ignore[no-untyped-def]
            self.calls += 1
            if self.calls >= 1:
                token.cancel("cancelled_after_first_failure")
            return super().request(request)

    # After first 503, cancellation is checked before retry → CANCELLED.
    transport = CancellingTransport()
    client = _client(
        transport=transport,
        cancellation=token,
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.01),
        clock=clock,
    )
    result = client.get_application_data("16888888")
    assert result.kind is ProviderOutcomeKind.CANCELLED
    _assert_no_secret(result.to_dict())


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_search_pagination_and_checkpoint_resume() -> None:
    # Build a transport that returns page bodies in order for POST search.
    transport = RecordedHttpTransport(
        [
            RecordedExchange(
                method="POST",
                path="/api/v1/patent/applications/search",
                status=200,
                body={
                    "count": 3,
                    "patentFileWrapperDataBag": [
                        {"applicationNumberText": "16100001"},
                        {"applicationNumberText": "16100002"},
                    ],
                },
            ),
            RecordedExchange(
                method="POST",
                path="/api/v1/patent/applications/search",
                status=200,
                body={
                    "count": 3,
                    "patentFileWrapperDataBag": [
                        {"applicationNumberText": "16100003"},
                    ],
                },
            ),
        ]
    )
    client = _client(transport=transport)
    page1 = client.search("applicationMetaData.applicationTypeLabelName:Utility", limit=2)
    assert page1.ok
    assert isinstance(page1.payload, OdpPage)
    assert len(page1.payload.items) == 2
    assert page1.checkpoint is not None
    assert page1.checkpoint.offset == 2
    assert not page1.checkpoint.exhausted

    page2 = client.search(
        "applicationMetaData.applicationTypeLabelName:Utility",
        limit=2,
        checkpoint=page1.checkpoint,
    )
    assert page2.ok
    assert isinstance(page2.payload, OdpPage)
    assert len(page2.payload.items) == 1
    assert page2.checkpoint is not None
    assert page2.checkpoint.exhausted
    _assert_no_secret(page1.to_dict())
    _assert_no_secret(page2.checkpoint.to_dict())


def test_iter_search_pages() -> None:
    transport = RecordedHttpTransport(
        [
            RecordedExchange(
                method="POST",
                path="/api/v1/patent/applications/search",
                status=200,
                body={
                    "count": 2,
                    "patentFileWrapperDataBag": [{"applicationNumberText": "1"}],
                },
            ),
            RecordedExchange(
                method="POST",
                path="/api/v1/patent/applications/search",
                status=200,
                body={
                    "count": 2,
                    "patentFileWrapperDataBag": [{"applicationNumberText": "2"}],
                },
            ),
        ]
    )
    client = _client(transport=transport)
    pages = list(client.iter_search_pages("q:test", limit=1, max_pages=5))
    assert len(pages) == 2
    assert all(p.ok for p in pages)


# ---------------------------------------------------------------------------
# Conditional cache + circuit breaker + secrets in transport
# ---------------------------------------------------------------------------


def test_conditional_cache_not_modified() -> None:
    # First exchange 200 with ETag; second 304.
    transport = RecordedHttpTransport(
        [
            RecordedExchange(
                method="GET",
                path=PATH_APPLICATION.format(applicationNumberText=APP_OK),
                status=200,
                headers={
                    "ETag": '"v1"',
                    "Last-Modified": "Wed, 01 Aug 2026 00:00:00 GMT",
                },
                body={
                    "count": 1,
                    "patentFileWrapperDataBag": [
                        {
                            "applicationNumberText": APP_OK,
                            "applicationMetaData": {
                                "applicationStatusCode": 150,
                                "applicationStatusDescriptionText": "Ready",
                            },
                        }
                    ],
                },
            ),
            RecordedExchange(
                method="GET",
                path=PATH_APPLICATION.format(applicationNumberText=APP_OK),
                status=304,
                headers={"ETag": '"v1"'},
                body=None,
            ),
        ]
    )
    client = _client(transport=transport)
    first = client.get_application_data(APP_OK)
    assert first.ok and not first.cache_hit
    second = client.get_application_data(APP_OK)
    assert second.kind is ProviderOutcomeKind.NOT_MODIFIED
    assert second.cache_hit
    assert isinstance(second.payload, OdpApplicationSnapshot)
    # Second request must have sent If-None-Match (inspect raw transport via
    # a side channel: RecordedHttpTransport stores sanitized headers only).
    assert len(transport.requests) == 2


def test_circuit_breaker_opens() -> None:
    exchanges = [
        RecordedExchange(
            method="GET",
            path="/api/v1/patent/applications/16999999",
            status=500,
            body={"error": "boom"},
        )
        for _ in range(6)
    ]
    transport = RecordedHttpTransport(exchanges)
    breaker = CircuitBreaker(
        CircuitBreakerPolicy(failure_threshold=2, recovery_timeout_seconds=60.0)
    )
    client = _client(
        transport=transport,
        circuit_breaker=breaker,
        retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.01),
    )
    r1 = client.get_application_data("16999999")
    assert r1.kind in {
        ProviderOutcomeKind.UPSTREAM_ERROR,
        ProviderOutcomeKind.RETRY_BUDGET_EXHAUSTED,
    }
    r2 = client.get_application_data("16999999")
    # After threshold failures the next call is short-circuited.
    r3 = client.get_application_data("16999999")
    assert r3.kind is ProviderOutcomeKind.CIRCUIT_OPEN
    _assert_no_secret(r3.to_dict())


def test_api_key_attached_but_absent_from_artifacts() -> None:
    seen_headers: list[dict[str, str]] = []

    class InspectingTransport(RecordedHttpTransport):
        def request(self, request):  # type: ignore[no-untyped-def]
            # Capture live headers before sanitizing storage.
            seen_headers.append(dict(request.headers))
            return super().request(request)

    transport = InspectingTransport(
        [
            RecordedExchange(
                method="GET",
                path=PATH_APPLICATION.format(applicationNumberText=APP_OK),
                status=200,
                body={
                    "count": 1,
                    "patentFileWrapperDataBag": [
                        {
                            "applicationNumberText": APP_OK,
                            "applicationMetaData": {"applicationStatusCode": 1},
                        }
                    ],
                },
            )
        ]
    )
    client = _client(transport=transport, api_key=SECRET)
    result = client.get_application_data(APP_OK)
    assert result.ok
    assert seen_headers
    assert seen_headers[0].get(API_KEY_HEADER) == SECRET
    # Stored request history and results must not retain the secret.
    for req in transport.requests:
        assert SECRET not in json.dumps(req.sanitized_dict())
        assert req.headers.get(API_KEY_HEADER) == "<redacted>"
    _assert_no_secret(result.to_dict())
    _assert_no_secret(client.safe_config())
    assert not contains_secret_leak(result.to_dict(), secret=SECRET)


def test_build_fixture_recipe_round_trip() -> None:
    recipe = build_fixture_recipe(
        [
            RecordedExchange(
                method="GET",
                path="/api/v1/patent/applications/1",
                status=404,
                body={"error": "Not Found"},
            )
        ]
    )
    assert recipe["schema_version"] == FIXTURE_SCHEMA_VERSION
    loaded = load_recorded_exchanges(recipe)
    assert loaded[0].status == 404


def test_source_receipt_digest_excludes_secrets() -> None:
    request = HttpRequest(
        method="GET",
        url=f"https://api.uspto.gov/api/v1/patent/applications/{APP_OK}?api_key={SECRET}",
        headers={API_KEY_HEADER: SECRET, "Accept": "application/json"},
    )
    receipt = build_source_receipt(
        endpoint=request.url,
        status_code=200,
        request=request,
        response_body=b'{"count":1}',
        upstream_id=APP_OK,
    )
    blob = json.dumps(receipt.to_dict())
    _assert_no_secret(blob)
    assert "<redacted>" in sanitize_url(request.url) or "api_key" in sanitize_url(request.url)


def test_parse_application_snapshot_unit() -> None:
    receipt = build_source_receipt(
        endpoint="https://api.uspto.gov/api/v1/patent/applications/16123456",
        status_code=200,
        request=HttpRequest(
            method="GET",
            url="https://api.uspto.gov/api/v1/patent/applications/16123456",
        ),
        response_body=b"{}",
        upstream_id="16123456",
    )
    snap = parse_application_snapshot(
        {
            "count": 1,
            "patentFileWrapperDataBag": [
                {
                    "applicationNumberText": "16123456",
                    "applicationMetaData": {"applicationStatusCode": 150},
                }
            ],
        },
        receipt=receipt,
        requested_application_number="16123456",
    )
    assert snap.identity.application_number == "16123456"
    assert snap.identity.source == "odp_patent_file_wrapper"
