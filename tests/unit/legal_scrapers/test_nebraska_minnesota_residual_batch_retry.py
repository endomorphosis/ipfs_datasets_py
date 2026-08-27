from __future__ import annotations

from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.minnesota import (
    MinnesotaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.nebraska import (
    NebraskaScraper,
)


NE_RESIDUAL_URLS = [
    f"https://nebraskalegislature.gov/laws/statutes.php?statute=3-{number}"
    for number in (120, 121, 125, 129, 131)
]
MN_RESIDUAL_URLS = [
    f"https://www.revisor.mn.gov/statutes/cite/{section}"
    for section in ("84A.40", "84A.41", "84A.42", "84A.51", "84A.52")
]


def _aligned_result(
    urls: list[str],
    payloads: list[bytes],
    errors: list[str | None],
    *,
    attempt: int,
    stats: dict[str, Any] | None = None,
) -> StateLawPageMultiFetchResult:
    receipts = [
        {"official_url": url, "attempt": attempt} if payload and error is None else None
        for url, payload, error in zip(urls, payloads, errors, strict=True)
    ]
    envelopes = [
        f"envelope:{attempt}:{url}" if payload and error is None else None
        for url, payload, error in zip(urls, payloads, errors, strict=True)
    ]
    return StateLawPageMultiFetchResult(
        urls=list(urls),
        payloads=list(payloads),
        errors=list(errors),
        transport_receipts=receipts,
        parser_input_envelopes=envelopes,
        stats=(
            dict(stats)
            if stats is not None
            else {
                "requested_pages": len(urls),
                "network_requested_pages": len(urls),
            }
        ),
    )


@pytest.mark.anyio
@pytest.mark.parametrize("state", ["NE", "MN"])
async def test_state_residual_retry_resubmits_only_unresolved_plural_rows(
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    if state == "NE":
        scraper = NebraskaScraper("NE", "Nebraska")
        urls = list(NE_RESIDUAL_URLS)
    else:
        scraper = MinnesotaScraper("MN", "Minnesota")
        urls = list(MN_RESIDUAL_URLS)

    calls: list[tuple[list[str], dict[str, Any]]] = []
    payload_by_url = {url: f"official:{url}".encode() for url in urls}
    initially_successful = {urls[0], urls[2]}
    expected_residual = [urls[1], urls[3], urls[4]]

    async def _plural(
        requested_urls,
        **kwargs: Any,
    ) -> StateLawPageMultiFetchResult:
        requested = list(requested_urls)
        calls.append((requested, dict(kwargs)))
        attempt = len(calls) - 1
        if attempt == 0:
            payloads = [
                payload_by_url[url] if url in initially_successful else b""
                for url in requested
            ]
            errors = [
                None if url in initially_successful else "transient batch miss"
                for url in requested
            ]
            return _aligned_result(
                requested,
                payloads,
                errors,
                attempt=attempt,
            )
        assert requested == expected_residual
        return _aligned_result(
            requested,
            [payload_by_url[url] for url in requested],
            [None] * len(requested),
            attempt=attempt,
        )

    monkeypatch.setenv(
        "STATE_SCRAPER_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
        "1",
    )
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )

    if state == "NE":
        payloads = await scraper._fetch_nebraska_section_frontier_batch(urls)
    else:
        payloads = await scraper._fetch_minnesota_frontier_batch(
            urls,
            frontier_name="section",
        )

    assert [requested for requested, _kwargs in calls] == [
        urls,
        expected_residual,
    ]
    if state == "NE":
        retry_kwargs = dict(calls[1][1])
        assert retry_kwargs.pop("archive_recovery_enabled") is False
        assert retry_kwargs == calls[0][1]
        assert calls[0][1]["wayback_prefix_inventory"] is True
    else:
        retry_kwargs = dict(calls[1][1])
        assert retry_kwargs.pop("archive_recovery_enabled") is False
        assert retry_kwargs == calls[0][1]
        assert calls[0][1]["wayback_prefix_inventory"] is True
    assert payloads == [payload_by_url[url] for url in urls]
    assert scraper._last_page_multifetch_stats["residual_retry_requested_pages"] == len(
        expected_residual
    )
    assert scraper._last_page_multifetch_stats["residual_retry_recovered_pages"] == len(
        expected_residual
    )
    assert scraper._last_page_multifetch_stats["residual_retry_unresolved_urls"] == []


@pytest.mark.anyio
async def test_shared_residual_retry_preserves_receipt_and_envelope_alignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = NebraskaScraper("NE", "Nebraska")
    urls = list(NE_RESIDUAL_URLS[:4])
    residual = [urls[1], urls[3]]
    calls: list[list[str]] = []

    async def _plural(
        requested_urls,
        **_kwargs: Any,
    ) -> StateLawPageMultiFetchResult:
        requested = list(requested_urls)
        calls.append(requested)
        attempt = len(calls) - 1
        if attempt == 0:
            return _aligned_result(
                requested,
                [b"first-0", b"", b"first-2", b""],
                [None, "miss-1", None, "miss-3"],
                attempt=attempt,
            )
        assert requested == residual
        return _aligned_result(
            requested,
            [b"retry-1", b"retry-3"],
            [None, None],
            attempt=attempt,
        )

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )

    result = (
        await scraper._fetch_page_contents_with_archival_fallback_retrying_residuals(
            urls,
            residual_retry_attempts=1,
        )
    )

    assert calls == [urls, residual]
    assert result.urls == urls
    assert result.payloads == [b"first-0", b"retry-1", b"first-2", b"retry-3"]
    assert result.errors == [None, None, None, None]
    assert [receipt["attempt"] for receipt in result.transport_receipts] == [
        0,
        1,
        0,
        1,
    ]
    assert result.parser_input_envelopes == [
        f"envelope:0:{urls[0]}",
        f"envelope:1:{urls[1]}",
        f"envelope:0:{urls[2]}",
        f"envelope:1:{urls[3]}",
    ]


@pytest.mark.anyio
async def test_shared_residual_retry_aggregates_warc_and_inventory_stats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = NebraskaScraper("NE", "Nebraska")
    urls = list(NE_RESIDUAL_URLS[:4])
    residual = [urls[1], urls[3]]
    calls: list[list[str]] = []

    async def _plural(
        requested_urls,
        **_kwargs: Any,
    ) -> StateLawPageMultiFetchResult:
        requested = list(requested_urls)
        calls.append(requested)
        attempt = len(calls) - 1
        if attempt == 0:
            return _aligned_result(
                requested,
                [b"first-0", b"", b"first-2", b""],
                [None, "miss-1", None, "miss-3"],
                attempt=attempt,
                stats={
                    "requested_pages": 4,
                    "network_requested_pages": 4,
                    "direct_initial_requests": 4,
                    "direct_initial_successes": 2,
                    "result_callbacks_emitted": 2,
                    "fallback_requests": 2,
                    "duplicate_page_requests_avoided": 1,
                    "common_crawl_pointer_candidates": 3,
                    "common_crawl_selected_pages": 2,
                    "eager_parser_inputs_admitted": 2,
                    "eager_parser_input_retention_failures": 1,
                    "parser_inputs_admitted": 2,
                    "parser_input_retention_failures": 1,
                    "retained_replay_pages": 1,
                    "retained_replay_unique_pages": 1,
                    "cross_instance_retained_replay_pages": 1,
                    "cross_instance_retained_replay_unique_pages": 1,
                    "common_crawl_inventory_queries": 1,
                    "common_crawl_inventory_records": 8,
                    "common_crawl_matched_pointers": 3,
                    "common_crawl_inventory_memo": {
                        "source": "shared",
                        "shared_domain_queries": 1,
                        "shared_domain_cache_hits": 0,
                    },
                    "common_crawl": {
                        "requested_pages": 3,
                        "warc_objects": 1,
                        "range_fetch_calls": 2,
                        "naive_range_fetches": 3,
                        "range_fetches_avoided": 1,
                        "max_slice_bytes": 4096,
                        "batch_transport_available": True,
                        "transport_label": "initial",
                    },
                },
            )
        assert requested == residual
        return _aligned_result(
            requested,
            [b"retry-1", b"retry-3"],
            [None, None],
            attempt=attempt,
            stats={
                "requested_pages": 2,
                "network_requested_pages": 2,
                "direct_initial_requests": 2,
                "direct_initial_successes": 1,
                "result_callbacks_emitted": 2,
                "fallback_requests": 1,
                "duplicate_page_requests_avoided": 2,
                "common_crawl_pointer_candidates": 2,
                "common_crawl_selected_pages": 1,
                "eager_parser_inputs_admitted": 1,
                "eager_parser_input_retention_failures": 2,
                # The merged helper owns this logical count; it must not
                # inherit or add an attempt-local diagnostic.
                "parser_inputs_admitted": 1,
                "parser_input_retention_failures": 3,
                "retained_replay_pages": 2,
                "retained_replay_unique_pages": 1,
                "cross_instance_retained_replay_pages": 2,
                "cross_instance_retained_replay_unique_pages": 1,
                "common_crawl_inventory_queries": 1,
                "common_crawl_inventory_records": 2,
                "common_crawl_matched_pointers": 2,
                "common_crawl_inventory_memo": {
                    "source": "shared_cache",
                    "shared_domain_queries": 0,
                    "shared_domain_cache_hits": 1,
                },
                "common_crawl": {
                    "requested_pages": 2,
                    "warc_objects": 2,
                    "range_fetch_calls": 1,
                    "naive_range_fetches": 2,
                    "range_fetches_avoided": 1,
                    "max_slice_bytes": 4096,
                    "batch_transport_available": True,
                    "transport_label": "retry",
                },
            },
        )

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )

    result = (
        await scraper._fetch_page_contents_with_archival_fallback_retrying_residuals(
            urls,
            residual_retry_attempts=1,
        )
    )

    assert calls == [urls, residual]
    assert result.stats["network_requested_pages"] == 6
    assert result.stats["common_crawl_inventory_queries"] == 2
    assert result.stats["common_crawl_inventory_records"] == 10
    assert result.stats["common_crawl_matched_pointers"] == 5
    assert result.stats["direct_initial_requests"] == 6
    assert result.stats["direct_initial_successes"] == 3
    assert result.stats["result_callbacks_emitted"] == 4
    assert result.stats["fallback_requests"] == 3
    assert result.stats["duplicate_page_requests_avoided"] == 3
    assert result.stats["common_crawl_pointer_candidates"] == 5
    assert result.stats["common_crawl_selected_pages"] == 3
    assert result.stats["eager_parser_inputs_admitted"] == 3
    assert result.stats["eager_parser_input_retention_failures"] == 3
    assert result.stats["parser_input_retention_failures"] == 4
    assert result.stats["retained_replay_pages"] == 3
    assert result.stats["retained_replay_unique_pages"] == 2
    assert result.stats["cross_instance_retained_replay_pages"] == 3
    assert result.stats["cross_instance_retained_replay_unique_pages"] == 2
    assert result.stats["requested_pages"] == 4
    assert result.stats["unique_pages"] == 4
    assert result.stats["successful_pages"] == 4
    assert result.stats["failed_pages"] == 0
    assert result.stats["parser_inputs_admitted"] == 4
    assert result.stats["common_crawl_inventory_memo"] == {
        "source": "shared",
        "shared_domain_queries": 1,
        "shared_domain_cache_hits": 1,
    }
    assert result.stats["common_crawl"] == {
        "requested_pages": 5,
        "warc_objects": 3,
        "range_fetch_calls": 3,
        "naive_range_fetches": 5,
        "range_fetches_avoided": 2,
        # These descriptors are retained once rather than numerically added.
        "max_slice_bytes": 4096,
        "batch_transport_available": True,
        "transport_label": "initial",
    }
    assert scraper._last_common_crawl_batch_stats == result.stats["common_crawl"]
    assert (
        result.stats["residual_retry_attempt_batches"][1]["common_crawl"][
            "transport_label"
        ]
        == "retry"
    )


@pytest.mark.anyio
async def test_minnesota_residual_retry_fails_with_only_exact_unresolved_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MinnesotaScraper("MN", "Minnesota")
    urls = list(MN_RESIDUAL_URLS)
    calls: list[list[str]] = []

    async def _plural(
        requested_urls,
        **_kwargs: Any,
    ) -> StateLawPageMultiFetchResult:
        requested = list(requested_urls)
        calls.append(requested)
        attempt = len(calls) - 1
        if attempt == 0:
            return _aligned_result(
                requested,
                [b"initial-success", b"", b"", b"", b""],
                [None, "miss-1", "miss-2", "miss-3", "miss-4"],
                attempt=attempt,
            )
        return _aligned_result(
            requested,
            [b"retry-success", b"", b"", b""],
            [None, "still-missing-2", "still-missing-3", "still-missing-4"],
            attempt=attempt,
        )

    monkeypatch.setenv(
        "STATE_SCRAPER_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
        "1",
    )
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )

    with pytest.raises(RuntimeError) as raised:
        await scraper._fetch_minnesota_frontier_batch(
            urls,
            frontier_name="section",
        )

    assert calls == [urls, urls[1:]]
    message = str(raised.value)
    assert "unresolved exact URLs" in message
    assert urls[0] not in message
    assert urls[1] not in message
    for unresolved_url in urls[2:]:
        assert unresolved_url in message
