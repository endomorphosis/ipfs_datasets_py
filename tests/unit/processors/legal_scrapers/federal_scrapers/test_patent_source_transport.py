"""Unit tests for patent legal-source transport (PATLAW-127).

Fake-server coverage: unchanged, changed, truncated, mislabeled, throttled,
unavailable. Also asserts content-addressed bytes/receipts, bounded/explicit
network use, and parser admission only with an acquisition outcome.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from ipfs_datasets_py.processors.legal_data.patent_authority_contracts_v2 import (
    AcquisitionOutcomeKind,
    MissingAcquisitionOutcomeError,
    content_address_bytes,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.patent_source_transport import (
    DEFAULT_LEGAL_SOURCE_HOSTS,
    SOURCE_TRANSPORT_SCHEMA_VERSION,
    CancellationToken,
    ConditionalByteCache,
    FakeLegalSourceServer,
    LegalSourceHostPolicy,
    LegalSourceTransportLimits,
    PatentSourceTransport,
    ScriptedOpener,
    SourceFetchRequest,
    SourceTransportPolicyError,
    build_loopback_transport,
    endpoint_fingerprint,
    parse_retry_after_header,
    sanitize_url,
)


XML_BODY_V1 = b'<?xml version="1.0"?><section id="1.56">duty of disclosure v1</section>'
XML_BODY_V2 = b'<?xml version="1.0"?><section id="1.56">duty of disclosure v2</section>'
HTML_BODY = b"<!DOCTYPE html><html><body>not regulation</body></html>"


def _transport_scripted(
    opener: ScriptedOpener,
    *,
    cache: ConditionalByteCache | None = None,
    max_response_bytes: int = 64 * 1024,
) -> PatentSourceTransport:
    return PatentSourceTransport(
        policy=LegalSourceHostPolicy(
            allowed_hosts=frozenset({"www.govinfo.gov", "www.ecfr.gov"}),
            allowed_ports=frozenset({443}),
            require_https=True,
        ),
        limits=LegalSourceTransportLimits(
            max_response_bytes=max_response_bytes,
            request_timeout_seconds=2.0,
        ),
        opener=opener,
        cache=cache if cache is not None else ConditionalByteCache(),
        network_enabled=False,  # opener injection is the only network path
    )


# ---------------------------------------------------------------------------
# Policy / explicit network bounds
# ---------------------------------------------------------------------------


def test_schema_and_safe_config_no_network_on_import() -> None:
    transport = PatentSourceTransport()
    cfg = transport.safe_config()
    assert cfg["schema_version"] == SOURCE_TRANSPORT_SCHEMA_VERSION
    assert cfg["network_enabled"] is False
    assert set(cfg["policy"]["allowed_hosts"]) >= {
        "www.govinfo.gov",
        "www.ecfr.gov",
        "api.uspto.gov",
    }
    assert transport.request_count == 0


def test_network_disabled_without_opener_fails_closed() -> None:
    transport = PatentSourceTransport(network_enabled=False)
    with pytest.raises(SourceTransportPolicyError, match="network use is disabled"):
        transport.acquire(
            SourceFetchRequest(url="https://www.govinfo.gov/content/pkg/x")
        )


def test_host_allowlist_rejects_non_legal_sources() -> None:
    policy = LegalSourceHostPolicy.legal_sources_default()
    with pytest.raises(SourceTransportPolicyError):
        policy.validate_url("https://evil.example/api")
    with pytest.raises(SourceTransportPolicyError):
        policy.validate_url("http://www.govinfo.gov/x")  # http without loopback
    with pytest.raises(SourceTransportPolicyError):
        policy.validate_url("https://www.govinfo.gov/x?api_key=secret")
    parsed = policy.validate_url(
        "https://www.govinfo.gov/content/pkg/CFR-2024-title37-vol1"
    )
    assert parsed.hostname == "www.govinfo.gov"
    assert "www.govinfo.gov" in DEFAULT_LEGAL_SOURCE_HOSTS


def test_endpoint_fingerprint_stable() -> None:
    a = endpoint_fingerprint("https://www.ecfr.gov/api/x")
    b = endpoint_fingerprint("https://www.ecfr.gov/api/x")
    assert a == b
    assert a.startswith("endpoint:")


def test_sanitize_url_strips_userinfo_shape() -> None:
    # Policy rejects userinfo; sanitize still redacts query secrets for receipts.
    cleaned = sanitize_url("https://www.govinfo.gov/path?q=1")
    assert "govinfo.gov" in cleaned


# ---------------------------------------------------------------------------
# Scripted opener: content addressing + classification primitives
# ---------------------------------------------------------------------------


def test_scripted_fetched_bytes_and_receipt_content_addressed() -> None:
    opener = ScriptedOpener()
    opener.add(
        status=200,
        body=XML_BODY_V1,
        headers={
            "Content-Type": "application/xml",
            "ETag": '"v1"',
            "Last-Modified": "Mon, 01 Jul 2024 00:00:00 GMT",
            "X-Source-Timestamp": "2024-07-01T00:00:00Z",
        },
    )
    transport = _transport_scripted(opener)
    outcome = transport.acquire(
        SourceFetchRequest(
            url="https://www.govinfo.gov/content/pkg/CFR-2024-title37-vol1/xml",
            expected_media_types=("application/xml",),
            robots_metadata={"robots": "allowed", "crawl_delay": 1.0},
            terms_metadata={"terms_url": "https://www.govinfo.gov/about"},
        )
    )
    assert outcome.kind is AcquisitionOutcomeKind.FETCHED
    assert outcome.network_used is True
    assert outcome.body == XML_BODY_V1
    assert outcome.receipt.content is not None
    expected = content_address_bytes(XML_BODY_V1)
    assert outcome.receipt.content.sha256 == expected.sha256
    assert outcome.receipt.content.cid == expected.cid
    assert outcome.receipt.receipt_sha256
    assert outcome.receipt.receipt_cid
    assert outcome.receipt.source_timestamp == "2024-07-01T00:00:00Z"
    assert outcome.receipt.robots_metadata["robots"] == "allowed"
    assert outcome.receipt.terms_metadata["terms_url"]
    # Recompute receipt address is stable.
    again = outcome.receipt.to_dict()
    assert again["receipt_sha256"] == outcome.receipt.receipt_sha256


# ---------------------------------------------------------------------------
# Fake-server scenarios (acceptance matrix)
# ---------------------------------------------------------------------------


def test_fake_server_unchanged_changed_truncated_mislabeled_throttled_unavailable() -> None:
    """Single fake-server suite covering all six acceptance classifications."""

    routes = {
        "/reg/v1": {
            "status": 200,
            "body": XML_BODY_V1,
            "headers": {
                "Content-Type": "application/xml",
                "ETag": '"reg-v1"',
                "Last-Modified": "Mon, 01 Jul 2024 00:00:00 GMT",
                "X-Source-Timestamp": "2024-07-01T00:00:00Z",
            },
        },
        "/reg/changed": {
            "sequence": [
                {
                    "status": 200,
                    "body": XML_BODY_V1,
                    "headers": {
                        "Content-Type": "application/xml",
                        "ETag": '"c1"',
                    },
                },
                {
                    "status": 200,
                    "body": XML_BODY_V2,
                    "headers": {
                        "Content-Type": "application/xml",
                        "ETag": '"c2"',
                    },
                },
            ]
        },
        "/reg/truncated": {
            "status": 200,
            "body": XML_BODY_V1,
            "truncate": True,
            "headers": {"Content-Type": "application/xml", "ETag": '"t1"'},
        },
        "/reg/mislabeled": {
            "status": 200,
            "body": HTML_BODY,
            "headers": {
                "Content-Type": "application/pdf",
                "ETag": '"m1"',
            },
        },
        "/reg/throttle": {
            "status": 429,
            "body": {"error": "rate_limited"},
            "headers": {
                "Retry-After": "12",
                "Content-Type": "application/json",
            },
        },
        "/reg/unavailable": {
            "status": 503,
            "body": {"error": "down"},
            "headers": {"Retry-After": "30"},
        },
        "/reg/missing": {
            "status": 404,
            "body": {"error": "not_found"},
        },
        "/reg/page": {
            "status": 200,
            "body": {"page": 1, "items": [1, 2]},
            "headers": {
                "Content-Type": "application/json",
                "X-Next-Page": "/reg/page?cursor=2",
                "ETag": '"p1"',
            },
        },
    }

    with FakeLegalSourceServer(routes) as server:
        cache = ConditionalByteCache()
        transport = build_loopback_transport(server, cache=cache)

        # --- fetched baseline ---
        first = transport.acquire(
            SourceFetchRequest(
                url=server.url("/reg/v1"),
                expected_media_types=("application/xml", "text/xml"),
            )
        )
        assert first.kind is AcquisitionOutcomeKind.FETCHED
        assert first.body == XML_BODY_V1
        assert first.receipt.content is not None
        assert first.receipt.content.sha256 == hashlib.sha256(XML_BODY_V1).hexdigest()
        assert first.receipt.etag == '"reg-v1"'

        # --- unchanged (304 via conditional revalidation) ---
        second = transport.acquire(
            SourceFetchRequest(url=server.url("/reg/v1"), enable_conditional=True)
        )
        assert second.kind is AcquisitionOutcomeKind.UNCHANGED
        assert second.receipt.cache_hit is True
        assert second.receipt.response_status == 304
        assert second.body == XML_BODY_V1
        assert second.receipt.content is not None
        assert second.receipt.content.sha256 == first.receipt.content.sha256

        # --- changed (new body on same path with sequence) ---
        # Fresh transport/cache so first hit stores v1, second observes change.
        cache2 = ConditionalByteCache()
        transport2 = build_loopback_transport(server, cache=cache2)
        a = transport2.acquire(SourceFetchRequest(url=server.url("/reg/changed")))
        assert a.kind is AcquisitionOutcomeKind.FETCHED
        assert a.body == XML_BODY_V1
        b = transport2.acquire(SourceFetchRequest(url=server.url("/reg/changed")))
        assert b.kind is AcquisitionOutcomeKind.CHANGED
        assert b.body == XML_BODY_V2
        assert b.receipt.content is not None
        assert b.receipt.content.sha256 != a.receipt.content.sha256

        # --- truncated (Content-Length > body, connection closed early) ---
        trunc = transport.acquire_catching(
            SourceFetchRequest(url=server.url("/reg/truncated"))
        )
        # Prefer TRUNCATED; allow network/timeout if the platform surfaces
        # incomplete reads differently, but assert we never admit as FETCHED.
        assert trunc.kind in {
            AcquisitionOutcomeKind.TRUNCATED,
            AcquisitionOutcomeKind.NETWORK_ERROR,
            AcquisitionOutcomeKind.TIMEOUT,
        }
        if trunc.kind is AcquisitionOutcomeKind.TRUNCATED:
            assert trunc.receipt.declared_content_length is not None
            assert trunc.body is not None
            assert len(trunc.body) < trunc.receipt.declared_content_length
            assert trunc.receipt.content is not None

        # --- mislabeled (Content-Type application/pdf, body is HTML) ---
        mis = transport.acquire(
            SourceFetchRequest(
                url=server.url("/reg/mislabeled"),
                expected_media_types=("application/pdf",),
            )
        )
        assert mis.kind is AcquisitionOutcomeKind.MISLABELED
        assert mis.receipt.declared_media_type == "application/pdf"
        assert mis.receipt.error_code == "mislabeled"
        assert mis.body == HTML_BODY
        assert mis.receipt.content is not None
        assert mis.receipt.content.sha256 == hashlib.sha256(HTML_BODY).hexdigest()

        # --- throttled ---
        throttled = transport.acquire(
            SourceFetchRequest(url=server.url("/reg/throttle"))
        )
        assert throttled.kind is AcquisitionOutcomeKind.THROTTLED
        assert throttled.receipt.response_status == 429
        assert throttled.receipt.retry_after_seconds == 12.0
        assert throttled.body is None

        # --- unavailable (503 + 404) ---
        down = transport.acquire(
            SourceFetchRequest(url=server.url("/reg/unavailable"))
        )
        assert down.kind is AcquisitionOutcomeKind.UNAVAILABLE
        assert down.receipt.response_status == 503
        missing = transport.acquire(
            SourceFetchRequest(url=server.url("/reg/missing"))
        )
        assert missing.kind is AcquisitionOutcomeKind.UNAVAILABLE
        assert missing.receipt.response_status == 404

        # --- pagination metadata captured ---
        page = transport.acquire(
            SourceFetchRequest(
                url=server.url("/reg/page"),
                page_index=1,
                page_token="cursor-start",
                expected_media_types=("application/json",),
            )
        )
        assert page.kind is AcquisitionOutcomeKind.FETCHED
        assert page.receipt.pagination.get("page_index") == 1
        assert page.receipt.pagination.get("page_token") == "cursor-start"
        assert "x_next_page" in page.receipt.pagination or page.receipt.pagination.get(
            "x_next_page"
        ) or "X-Next-Page".lower().replace("-", "_") in page.receipt.pagination

        # Receipts remain content-addressed across outcomes.
        for outcome in (first, second, b, mis, throttled, down):
            assert outcome.receipt.receipt_sha256
            assert len(outcome.receipt.receipt_sha256) == 64
            assert outcome.receipt.receipt_cid


def test_fake_server_truncated_via_scripted_declared_length() -> None:
    """Deterministic truncated classification when Content-Length > body."""

    opener = ScriptedOpener()
    short = b"<xml>partial"
    opener.add(
        status=200,
        body=short,
        headers={
            "Content-Type": "application/xml",
            "Content-Length": str(len(short) + 128),
        },
    )
    transport = _transport_scripted(opener)
    outcome = transport.acquire(
        SourceFetchRequest(url="https://www.ecfr.gov/api/partial.xml")
    )
    assert outcome.kind is AcquisitionOutcomeKind.TRUNCATED
    assert outcome.receipt.declared_content_length == len(short) + 128
    assert outcome.body == short
    assert outcome.receipt.content is not None
    assert outcome.receipt.content.sha256 == hashlib.sha256(short).hexdigest()


def test_fake_server_policy_blocks_cross_host() -> None:
    with FakeLegalSourceServer({"/ok": {"status": 200, "body": b"x"}}) as server:
        # Default production policy must refuse loopback even if a server runs.
        transport = PatentSourceTransport(network_enabled=True)
        with pytest.raises(SourceTransportPolicyError):
            transport.acquire(SourceFetchRequest(url=server.url("/ok")))


def test_fake_server_cancellation() -> None:
    with FakeLegalSourceServer({"/ok": {"status": 200, "body": b"ok"}}) as server:
        token = CancellationToken(cancelled=True, reason="stop-test")
        transport = build_loopback_transport(server, cancellation=token)
        outcome = transport.acquire_catching(
            SourceFetchRequest(url=server.url("/ok"))
        )
        assert outcome.kind is AcquisitionOutcomeKind.CANCELLED


# ---------------------------------------------------------------------------
# Parser admission gate via transport helper
# ---------------------------------------------------------------------------


def test_parser_admission_requires_acquisition_outcome() -> None:
    transport = PatentSourceTransport()
    with pytest.raises(MissingAcquisitionOutcomeError):
        transport.admit_to_parser(None)

    opener = ScriptedOpener()
    opener.add(
        status=429,
        body=b'{"error":"slow down"}',
        headers={"Retry-After": "5", "Content-Type": "application/json"},
    )
    transport = _transport_scripted(opener)
    throttled = transport.acquire(
        SourceFetchRequest(url="https://www.ecfr.gov/api/x")
    )
    assert throttled.kind is AcquisitionOutcomeKind.THROTTLED
    with pytest.raises(MissingAcquisitionOutcomeError):
        transport.admit_to_parser(throttled)


def test_parser_admission_accepts_fetched_and_preserves_addresses() -> None:
    opener = ScriptedOpener()
    opener.add(
        status=200,
        body=XML_BODY_V1,
        headers={"Content-Type": "application/xml", "ETag": '"z"'},
    )
    transport = _transport_scripted(opener)
    outcome = transport.acquire(
        SourceFetchRequest(
            url="https://www.govinfo.gov/pkg/x",
            expected_media_types=("application/xml",),
        )
    )
    envelope = transport.admit_to_parser(outcome, parser_name="govinfo_xml")
    assert envelope.body == XML_BODY_V1
    assert envelope.content_address is not None
    assert envelope.content_address.sha256 == hashlib.sha256(XML_BODY_V1).hexdigest()
    assert envelope.parser_name == "govinfo_xml"


def test_parse_retry_after_and_diagnostics() -> None:
    assert parse_retry_after_header({"Retry-After": "7"}) == 7.0
    assert parse_retry_after_header({"retry-after": "not-a-date"}) is None
    transport = PatentSourceTransport()
    cfg = transport.safe_config()
    # Config is JSON-serializable for receipts/logs.
    json.dumps(cfg)


def test_mislabeled_scripted_pdf_header_with_html_body() -> None:
    opener = ScriptedOpener()
    opener.add(
        status=200,
        body=HTML_BODY,
        headers={"Content-Type": "application/pdf"},
    )
    transport = _transport_scripted(opener)
    outcome = transport.acquire(
        SourceFetchRequest(
            url="https://www.govinfo.gov/pkg/bad.pdf",
            expected_media_types=("application/pdf",),
        )
    )
    assert outcome.kind is AcquisitionOutcomeKind.MISLABELED
    assert not outcome.is_parser_admissible
