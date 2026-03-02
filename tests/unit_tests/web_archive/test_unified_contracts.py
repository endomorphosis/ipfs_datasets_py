#!/usr/bin/env python3

import pytest

from ipfs_datasets_py.processors.web_archiving.contracts import (
    ErrorSeverity,
    ExecutionTrace,
    OperationMode,
    UnifiedDocument,
    UnifiedError,
    UnifiedFetchRequest,
    UnifiedFetchResponse,
    UnifiedSearchHit,
    UnifiedSearchRequest,
    UnifiedSearchResponse,
)


def test_unified_search_request_json_roundtrip() -> None:
    request = UnifiedSearchRequest(
        query="indiana laws",
        mode=OperationMode.MAX_THROUGHPUT,
        max_results=50,
        offset=10,
        timeout_seconds=45,
        min_quality=0.4,
        domain="legal",
        provider_allowlist=["common_crawl", "brave"],
        metadata={"source": "unit-test"},
    )

    payload = request.to_json()
    restored = UnifiedSearchRequest.from_json(payload)

    assert restored.query == request.query
    assert restored.mode == OperationMode.MAX_THROUGHPUT
    assert restored.max_results == 50
    assert restored.offset == 10
    assert restored.domain == "legal"
    assert restored.provider_allowlist == ["common_crawl", "brave"]


@pytest.mark.parametrize(
    "bad_kwargs",
    [
        {"query": "", "max_results": 20},
        {"query": "valid", "max_results": 0},
        {"query": "valid", "offset": -1},
        {"query": "valid", "timeout_seconds": 0},
        {"query": "valid", "min_quality": 1.2},
        {"query": "valid", "domain": ""},
    ],
)
def test_unified_search_request_validation(bad_kwargs) -> None:
    with pytest.raises(ValueError):
        UnifiedSearchRequest(**bad_kwargs)


def test_unified_fetch_request_json_roundtrip() -> None:
    request = UnifiedFetchRequest(
        url="https://example.com/page",
        mode=OperationMode.BALANCED,
        timeout_seconds=20,
        fallback_enabled=True,
        min_quality=0.5,
        domain="finance",
        provider_denylist=["archive_is"],
    )

    payload = request.to_json()
    restored = UnifiedFetchRequest.from_json(payload)

    assert restored.url == "https://example.com/page"
    assert restored.mode == OperationMode.BALANCED
    assert restored.domain == "finance"
    assert restored.provider_denylist == ["archive_is"]


@pytest.mark.parametrize(
    "bad_kwargs",
    [
        {"url": "not-a-url"},
        {"url": "ftp://example.com"},
        {"url": "https://example.com", "timeout_seconds": 0},
        {"url": "https://example.com", "min_quality": -0.1},
        {"url": "https://example.com", "domain": ""},
    ],
)
def test_unified_fetch_request_validation(bad_kwargs) -> None:
    with pytest.raises(ValueError):
        UnifiedFetchRequest(**bad_kwargs)


def test_unified_search_response_json_roundtrip() -> None:
    trace = ExecutionTrace(
        request_id="req-1",
        operation="search",
        mode=OperationMode.MAX_THROUGHPUT,
        providers_attempted=["common_crawl", "brave"],
        provider_selected="common_crawl",
        fallback_count=1,
        total_latency_ms=120.5,
        retries=1,
    )
    response = UnifiedSearchResponse(
        query="indiana statutes",
        results=[
            UnifiedSearchHit(
                title="Indiana Statutes",
                url="https://example.com/statutes",
                snippet="text",
                source="common_crawl",
                score=0.9,
            )
        ],
        trace=trace,
        errors=[
            UnifiedError(
                code="provider_timeout",
                message="timeout",
                provider="brave",
                retryable=True,
                severity=ErrorSeverity.WARNING,
            )
        ],
        success=True,
    )

    payload = response.to_json()
    restored = UnifiedSearchResponse.from_json(payload)

    assert restored.query == "indiana statutes"
    assert len(restored.results) == 1
    assert restored.results[0].url == "https://example.com/statutes"
    assert restored.trace is not None
    assert restored.trace.mode == OperationMode.MAX_THROUGHPUT
    assert len(restored.errors) == 1
    assert restored.errors[0].severity == ErrorSeverity.WARNING


def test_unified_fetch_response_json_roundtrip() -> None:
    trace = ExecutionTrace(
        request_id="req-2",
        operation="fetch",
        mode=OperationMode.BALANCED,
        providers_attempted=["common_crawl"],
        provider_selected="common_crawl",
        total_latency_ms=95.0,
    )
    response = UnifiedFetchResponse(
        url="https://example.com/statute-1",
        document=UnifiedDocument(
            url="https://example.com/statute-1",
            title="Statute",
            text="Body",
            content_type="text/html",
            extraction_provenance={"method": "common_crawl"},
        ),
        trace=trace,
        errors=[],
        success=True,
        quality_score=0.87,
    )

    payload = response.to_json()
    restored = UnifiedFetchResponse.from_json(payload)

    assert restored.url == "https://example.com/statute-1"
    assert restored.document is not None
    assert restored.document.title == "Statute"
    assert restored.trace is not None
    assert restored.trace.operation == "fetch"
    assert restored.quality_score == pytest.approx(0.87)


def test_execution_trace_validation() -> None:
    with pytest.raises(ValueError):
        ExecutionTrace(request_id="", operation="search", mode=OperationMode.BALANCED)

    with pytest.raises(ValueError):
        ExecutionTrace(request_id="r", operation="", mode=OperationMode.BALANCED)

    with pytest.raises(ValueError):
        ExecutionTrace(
            request_id="r",
            operation="search",
            mode=OperationMode.BALANCED,
            retries=-1,
        )
