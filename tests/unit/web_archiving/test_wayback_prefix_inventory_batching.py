from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qs, urlparse

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    BaseStateScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.state_archival_fetch import (
    ArchivalFetchClient,
    ArchivalMultiFetchResult,
    FetchResult,
)
from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine


class _InventoryFrontierScraper(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://gc.nh.gov"

    def get_code_list(self):
        return []

    async def scrape_code(self, code_name: str, code_url: str):
        del code_name, code_url
        return []


def _capture(url: str, timestamp: str) -> dict[str, object]:
    cdx_query, _variant_count = wayback_machine_engine._wayback_inventory_query_url(
        url,
        limit=100,
        exact_originals=[url],
    )
    return {
        "original_url": url,
        "status_code": 200,
        "timestamp": timestamp,
        "wayback_url": f"https://web.archive.org/web/{timestamp}id_/{url}",
        "wayback_cdx_query_url": cdx_query,
        "wayback_cdx_response_sha256": "a" * 64,
        "wayback_cdx_fetched_at": "2026-08-25T00:00:00+00:00",
    }


@pytest.mark.anyio
async def test_plural_wayback_inventory_replays_once_and_disables_legacy_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = "https://gc.nh.gov/rsa/html/I/1/1-1.htm"
    second = "https://gc.nh.gov/rsa/html/I/1/1-2.htm"
    urls = [first, second, first]
    timestamp = "20250212203224"
    client = ArchivalFetchClient(
        content_validator=lambda payload: bool(payload),
        enable_common_crawl=False,
        enable_direct=True,
        enable_archive_is=True,
    )
    direct_calls: list[str] = []
    inventory_calls: list[list[str]] = []
    replay_calls: list[str] = []
    archive_is_calls: list[str] = []
    callback_calls: list[tuple[str, str]] = []

    def _direct(url: str):
        direct_calls.append(url)

    async def _inventory(missing):
        inventory_calls.append(list(missing))
        return {
            "status": "success",
            "captures_by_url": {
                first: _capture(first, timestamp),
                second: _capture(second, timestamp),
            },
            "receipts": [{"response_sha256": "a" * 64}],
            "stats": {
                "requested_pages": 2,
                "unique_pages": 2,
                "prefix_queries_planned": 1,
                "prefix_queries_attempted": 1,
                "prefix_queries_succeeded": 1,
                "prefix_queries_failed": 0,
                "matched_pages": 2,
                "unmatched_pages": 0,
            },
        }

    async def _replay(archive_url: str, *, official_url: str | None = None):
        del archive_url
        assert official_url is not None
        replay_calls.append(official_url)
        if official_url == second:
            return None
        body = b"archived exact first section"
        return FetchResult(
            url=official_url,
            content=body,
            source="wayback",
            fetched_at="2026-08-25T00:00:01+00:00",
            status_code=200,
            archive_url=(
                f"https://web.archive.org/web/{timestamp}id_/{official_url}"
            ),
            archive_timestamp=timestamp,
            content_sha256=hashlib.sha256(body).hexdigest(),
        )

    async def _forbid_legacy_wayback(_url: str):
        raise AssertionError("per-page Wayback CDX search must stay disabled")

    async def _archive_is(url: str):
        archive_is_calls.append(url)
        raise AssertionError("per-page archive.is fallback must stay disabled")

    def _callback(url: str, result: FetchResult) -> None:
        callback_calls.append((url, result.source))

    monkeypatch.setattr(client, "_fetch_direct", _direct)
    monkeypatch.setattr(client, "fetch_wayback_replay", _replay)
    monkeypatch.setattr(client, "_fetch_from_wayback", _forbid_legacy_wayback)
    monkeypatch.setattr(client, "_fetch_from_archive_is", _archive_is)

    outcome = await client.fetch_many_with_fallback(
        urls,
        enable_common_crawl=False,
        max_concurrency=2,
        prefer_direct=True,
        result_callback=_callback,
        wayback_inventory_loader=_inventory,
    )

    assert sorted(direct_calls) == sorted([first, second])
    assert inventory_calls == [[first, second]]
    assert sorted(replay_calls) == sorted([first, second])
    assert archive_is_calls == []
    assert [result.content for result in outcome.results if result is not None] == [
        b"archived exact first section",
        b"archived exact first section",
    ]
    assert callback_calls == [(first, "wayback")]
    assert outcome.results[1] is None
    assert "per-page archive fallback is disabled" in str(outcome.errors[1])
    assert outcome.stats["fallback_requests"] == 0
    assert outcome.stats["grouped_inventory_residual_pages"] == 1
    assert outcome.stats["per_page_archive_fallback_disabled"] is True
    assert outcome.stats["wayback_inventory"]["prefix_queries_attempted"] == 1
    assert outcome.stats["wayback_inventory"]["selected_capture_replays"] == 2
    assert outcome.stats["wayback_inventory"]["successful_capture_replays"] == 1
    assert outcome.stats["wayback_inventory"]["failed_capture_replays"] == 1


@pytest.mark.anyio
async def test_plural_wayback_retries_only_11_transient_capture_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls = [
        (
            "https://law.lis.virginia.gov/vacode/"
            f"title58.1/chapter6/section58.1-{600 + index}/"
        )
        for index in range(14)
    ]
    timestamp = "20250212203224"
    client = ArchivalFetchClient(
        content_validator=lambda payload: b"Virginia exact section" in payload,
        enable_common_crawl=False,
        enable_direct=True,
        enable_archive_is=True,
    )
    direct_calls: list[str] = []
    inventory_calls: list[list[str]] = []
    replay_calls: list[str] = []
    callback_calls: list[str] = []
    archive_is_calls: list[str] = []
    attempts_by_url: dict[str, int] = {}
    first_pass_successes = set(urls[:3])

    def _direct(url: str):
        direct_calls.append(url)

    async def _inventory(missing):
        inventory_calls.append(list(missing))
        return {
            "status": "success",
            "captures_by_url": {
                url: _capture(url, timestamp) for url in missing
            },
            "receipts": [{"response_sha256": "a" * 64}],
            "stats": {
                "requested_pages": 14,
                "unique_pages": 14,
                "prefix_queries_planned": 2,
                "prefix_queries_attempted": 2,
                "prefix_queries_succeeded": 2,
                "prefix_queries_failed": 0,
                "cdx_requests": 2,
                "cdx_retries": 0,
                "matched_pages": 14,
                "unmatched_pages": 0,
            },
        }

    async def _replay(archive_url: str, *, official_url: str | None = None):
        del archive_url
        assert official_url is not None
        replay_calls.append(official_url)
        attempts_by_url[official_url] = attempts_by_url.get(official_url, 0) + 1
        if (
            official_url not in first_pass_successes
            and attempts_by_url[official_url] == 1
        ):
            raise TimeoutError("transient exact capture replay timeout")
        body = f"Virginia exact section {official_url}".encode()
        return FetchResult(
            url=official_url,
            content=body,
            source="wayback",
            fetched_at="2026-08-26T00:00:01+00:00",
            status_code=200,
            archive_url=(
                f"https://web.archive.org/web/{timestamp}id_/{official_url}"
            ),
            archive_timestamp=timestamp,
            content_sha256=hashlib.sha256(body).hexdigest(),
        )

    async def _forbid_legacy_wayback(_url: str):
        raise AssertionError("retry must not rediscover a capture per page")

    async def _archive_is(url: str):
        archive_is_calls.append(url)
        raise AssertionError("retry must not use archive.is")

    def _callback(url: str, _result: FetchResult) -> None:
        callback_calls.append(url)

    monkeypatch.setattr(client, "_fetch_direct", _direct)
    monkeypatch.setattr(client, "fetch_wayback_replay", _replay)
    monkeypatch.setattr(client, "_fetch_from_wayback", _forbid_legacy_wayback)
    monkeypatch.setattr(client, "_fetch_from_archive_is", _archive_is)

    outcome = await client.fetch_many_with_fallback(
        urls,
        enable_common_crawl=False,
        max_concurrency=8,
        prefer_direct=True,
        result_callback=_callback,
        wayback_inventory_loader=_inventory,
        wayback_capture_replay_attempts=2,
        wayback_capture_retry_concurrency=3,
    )

    assert sorted(direct_calls) == sorted(urls)
    assert all(direct_calls.count(url) == 1 for url in urls)
    assert inventory_calls == [urls]
    assert len(replay_calls) == 25
    assert all(attempts_by_url[url] == 1 for url in urls[:3])
    assert all(attempts_by_url[url] == 2 for url in urls[3:])
    assert callback_calls == urls
    assert archive_is_calls == []
    assert all(result is not None for result in outcome.results)
    inventory_stats = outcome.stats["wayback_inventory"]
    assert inventory_stats["cdx_requests"] == 2
    assert inventory_stats["cdx_retries"] == 0
    assert inventory_stats["first_pass_replay_calls"] == 14
    assert inventory_stats["first_pass_successful_pages"] == 3
    assert inventory_stats["transient_first_pass_failures"] == 11
    assert inventory_stats["semantic_first_pass_failures"] == 0
    assert inventory_stats["replay_retry_pages"] == 11
    assert inventory_stats["replay_retry_calls"] == 11
    assert inventory_stats["replay_retry_successes"] == 11
    assert inventory_stats["replay_retry_failures"] == 0
    assert inventory_stats["retry_max_concurrency"] == 3
    assert outcome.stats["fallback_requests"] == 0
    assert outcome.stats["grouped_inventory_residual_pages"] == 0


@pytest.mark.anyio
async def test_wayback_capture_retry_does_not_repeat_semantic_replay_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    official = "https://gc.nh.gov/rsa/html/I/1/1-1.htm"
    capture = _capture(official, "20250212203224")
    client = ArchivalFetchClient(content_validator=lambda payload: bool(payload))
    replay_calls: list[str] = []

    async def _semantic_miss(
        _archive_url: str,
        *,
        official_url: str | None = None,
    ):
        assert official_url is not None
        replay_calls.append(official_url)
        return None

    monkeypatch.setattr(client, "fetch_wayback_replay", _semantic_miss)
    outcome = await client.fetch_wayback_captures(
        [(official, capture)],
        replay_attempts=2,
    )

    assert replay_calls == [official]
    assert outcome.results == [None]
    assert outcome.stats["transient_first_pass_failures"] == 0
    assert outcome.stats["semantic_first_pass_failures"] == 1
    assert outcome.stats["replay_retry_pages"] == 0
    assert outcome.stats["replay_retry_calls"] == 0


@pytest.mark.anyio
async def test_same_origin_33_page_residual_uses_bounded_inventory_and_direct_only_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine

    urls = [
        (
            "https://law.lis.virginia.gov/vacode/"
            f"title2.2/chapter{index}/section2.2-{1000 + index}/"
        )
        for index in range(1, 34)
    ]
    direct_calls: list[str] = []
    common_crawl_calls: list[list[str]] = []
    cdx_query_urls: list[str] = []
    legacy_wayback_calls: list[str] = []
    archive_is_calls: list[str] = []

    def _direct(_self, url: str, *, headers=None):
        del headers
        direct_calls.append(url)
        if url != urls[0]:
            return None
        body = b"<html><body>Virginia current section body.</body></html>"
        return FetchResult(
            url=url,
            content=body,
            source="direct",
            fetched_at="2026-08-26T00:00:00+00:00",
            status_code=200,
            content_sha256=hashlib.sha256(body).hexdigest(),
        )

    async def _common_crawl(**kwargs):
        common_crawl_calls.append(list(kwargs.get("url_terms") or ()))
        return []

    async def _cdx(query_url: str, *, timeout_seconds: int):
        del timeout_seconds
        cdx_query_urls.append(query_url)
        return {
            "status": "success",
            "results": [],
            "receipt": {
                "response_sha256": "c" * 64,
                "fetched_at": "2026-08-26T00:00:01+00:00",
            },
        }

    async def _forbid_wayback(_self, url: str):
        legacy_wayback_calls.append(url)
        raise AssertionError("legacy per-page Wayback must stay disabled")

    async def _forbid_archive_is(_self, url: str):
        archive_is_calls.append(url)
        raise AssertionError("per-page archive.is must stay disabled")

    async def _no_cache(**_kwargs):
        return None

    monkeypatch.setattr(ArchivalFetchClient, "_fetch_direct", _direct)
    monkeypatch.setattr(
        ArchivalFetchClient,
        "_fetch_from_wayback",
        _forbid_wayback,
    )
    monkeypatch.setattr(
        ArchivalFetchClient,
        "_fetch_from_archive_is",
        _forbid_archive_is,
    )
    monkeypatch.setattr(wayback_machine_engine, "fetch_wayback_cdx_rows", _cdx)

    scraper = _InventoryFrontierScraper("VA", "Virginia")
    monkeypatch.setattr(scraper, "_search_state_common_crawl_records", _common_crawl)
    monkeypatch.setattr(scraper, "_cache_successful_page_fetch", _no_cache)

    result = await scraper._fetch_page_contents_with_archival_fallback_retrying_residuals(
        urls,
        residual_retry_attempts=1,
        content_validator=lambda payload: b"Virginia current section" in payload,
        media_type="text/html",
        max_concurrency=8,
        prefer_direct=True,
        wayback_prefix_inventory=True,
    )

    assert len(cdx_query_urls) == 4
    for cdx_query_url in cdx_query_urls:
        assert len(cdx_query_url.encode("ascii")) <= 2_048
        query = parse_qs(urlparse(cdx_query_url).query)
        assert query["matchType"] == ["prefix"]
        assert query["url"] == [
            "https://law.lis.virginia.gov/vacode/title2.2/"
        ]
        assert query["filter"][0] == "statuscode:200"
        assert query["filter"][1].startswith("original:^(?:")
        assert not any(value.startswith("mimetype:") for value in query["filter"])
    assert len(common_crawl_calls) == 1
    assert legacy_wayback_calls == []
    assert archive_is_calls == []
    assert direct_calls.count(urls[0]) == 1
    assert all(direct_calls.count(url) == 2 for url in urls[1:])
    assert len(direct_calls) == 65
    assert result.payloads[0]
    assert all(not payload for payload in result.payloads[1:])
    assert result.stats["wayback_inventory"]["cdx_requests"] == 4
    assert result.stats["wayback_inventory"]["cdx_retries"] == 0
    assert result.stats["wayback_inventory"]["query_target_bound"] == 8
    assert result.stats["wayback_inventory"]["max_queries_per_origin"] == 8
    assert result.stats["wayback_inventory"][
        "logical_prefix_groups_by_origin"
    ] == {"https://law.lis.virginia.gov": 1}
    assert result.stats["wayback_inventory"][
        "exact_filter_batches_by_origin"
    ] == {"https://law.lis.virginia.gov": 4}
    assert result.stats["fallback_requests"] == 0
    assert result.stats["residual_retry_rounds_executed"] == 1
    assert result.stats["residual_retry_attempt_batches"][0][
        "archive_recovery_enabled"
    ] is True
    assert result.stats["residual_retry_attempt_batches"][1][
        "archive_recovery_enabled"
    ] is False
    assert result.stats["residual_retry_attempt_batches"][1]["requested_urls"] == urls[
        1:
    ]


@pytest.mark.anyio
async def test_base_300_target_wave_keeps_logical_cap_and_safe_physical_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine

    urls = [
        (
            "https://law.lis.virginia.gov/vacode/"
            f"title2.2/chapter1/section2.2-{1000 + index}/"
        )
        for index in range(300)
    ]
    direct_calls: list[str] = []
    common_crawl_calls: list[list[str]] = []
    observed_batches: list[list[str]] = []
    observed_prefixes: list[str] = []
    legacy_wayback_calls: list[str] = []
    archive_is_calls: list[str] = []

    def _direct(_self, url: str, *, headers=None):
        del headers
        direct_calls.append(url)
        return None

    async def _common_crawl(**kwargs):
        common_crawl_calls.append(list(kwargs.get("url_terms") or ()))
        return []

    async def _cdx(query_url: str, *, timeout_seconds: int):
        del timeout_seconds
        assert len(query_url.encode("ascii")) <= 2_048
        query = parse_qs(urlparse(query_url).query)
        expression = query["filter"][1].split(":", 1)[1]
        members = [url for url in urls if re.fullmatch(expression, url)]
        observed_batches.append(members)
        observed_prefixes.append(query["url"][0])
        return {"status": "success", "results": []}

    async def _forbid_wayback(_self, url: str):
        legacy_wayback_calls.append(url)
        raise AssertionError("large plural wave must not use per-page Wayback")

    async def _forbid_archive_is(_self, url: str):
        archive_is_calls.append(url)
        raise AssertionError("large plural wave must not use per-page archive.is")

    async def _no_cache(**_kwargs):
        return None

    monkeypatch.setattr(ArchivalFetchClient, "_fetch_direct", _direct)
    monkeypatch.setattr(
        ArchivalFetchClient,
        "_fetch_from_wayback",
        _forbid_wayback,
    )
    monkeypatch.setattr(
        ArchivalFetchClient,
        "_fetch_from_archive_is",
        _forbid_archive_is,
    )
    monkeypatch.setattr(wayback_machine_engine, "fetch_wayback_cdx_rows", _cdx)

    scraper = _InventoryFrontierScraper("VA", "Virginia")
    monkeypatch.setattr(scraper, "_search_state_common_crawl_records", _common_crawl)
    monkeypatch.setattr(scraper, "_cache_successful_page_fetch", _no_cache)

    result = await scraper._fetch_page_contents_with_archival_fallback(
        urls,
        content_validator=lambda payload: bool(payload),
        media_type="text/html",
        max_concurrency=16,
        prefer_direct=True,
        wayback_prefix_inventory=True,
    )

    assert sorted(direct_calls) == sorted(urls)
    assert all(direct_calls.count(url) == 1 for url in urls)
    assert len(common_crawl_calls) == 1
    assert 1 < len(observed_batches) < len(urls)
    assert all(1 <= len(batch) <= 8 for batch in observed_batches)
    assert [url for batch in observed_batches for url in batch] == urls
    assert set(observed_prefixes) == {
        "https://law.lis.virginia.gov/vacode/title2.2/chapter1/"
    }
    assert legacy_wayback_calls == []
    assert archive_is_calls == []
    assert all(not payload for payload in result.payloads)
    inventory_stats = result.stats["wayback_inventory"]
    assert inventory_stats["prefix_groups_planned"] == 1
    assert inventory_stats["max_queries_per_origin"] == 8
    assert inventory_stats["logical_prefix_groups_by_origin"] == {
        "https://law.lis.virginia.gov": 1
    }
    assert inventory_stats["exact_filter_query_batches"] == len(observed_batches)
    assert inventory_stats["exact_filter_batches_added"] == len(observed_batches) - 1
    assert inventory_stats["query_target_bound"] == 8
    assert result.stats["fallback_requests"] == 0
    assert result.stats["per_page_archive_fallback_disabled"] is True


@pytest.mark.anyio
async def test_wayback_capture_batch_rejects_identity_drift_without_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    official = "https://gc.nh.gov/rsa/html/I/1/1-1.htm"
    capture = _capture(
        "https://gc.nh.gov/rsa/html/I/1/1-2.htm",
        "20250212203224",
    )
    client = ArchivalFetchClient(content_validator=lambda payload: bool(payload))

    async def _forbid(*_args, **_kwargs):
        raise AssertionError("identity drift must fail before replay")

    monkeypatch.setattr(client, "fetch_wayback_replay", _forbid)
    outcome = await client.fetch_wayback_captures([(official, capture)])

    assert outcome.results == [None]
    assert "changed exact official URL identity" in str(outcome.errors[0])
    assert outcome.stats["replay_calls"] == 0


@pytest.mark.anyio
async def test_base_plural_path_retains_inventory_receipt_and_eager_wayback_input(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine

    official = "https://gc.nh.gov/rsa/html/I/1/1-1.htm"
    timestamp = "20250212203224"
    body = b"<html><body>New Hampshire exact section 1:1.</body></html>"
    discovery_query = str(_capture(official, timestamp)["wayback_cdx_query_url"])
    discovery_receipt = {
        "schema_version": "wayback-cdx-discovery-receipt-v1",
        "source_transport": "wayback_cdx",
        "query_url": discovery_query,
        "response_url": discovery_query,
        "response_status": 200,
        "response_sha256": "b" * 64,
        "response_length": 123,
        "row_count": 1,
        "fetched_at": "2026-08-25T00:00:00+00:00",
    }
    inventory_calls: list[list[str]] = []

    async def _inventory(urls, **_kwargs):
        inventory_calls.append(list(urls))
        capture = _capture(official, timestamp)
        return {
            "status": "success",
            "captures_by_url": {official: capture},
            "receipts": [discovery_receipt],
            "errors": [],
            "stats": {
                "requested_pages": 1,
                "unique_pages": 1,
                "prefix_queries_attempted": 1,
                "prefix_queries_succeeded": 1,
                "matched_pages": 1,
            },
        }

    async def _many(_self, requested, **kwargs):
        requested = list(requested)
        outcome = await kwargs["wayback_inventory_loader"](requested)
        assert official in outcome["captures_by_url"]
        fetched = FetchResult(
            url=official,
            content=body,
            source="wayback",
            fetched_at="2026-08-25T00:00:01+00:00",
            status_code=200,
            archive_url=f"https://web.archive.org/web/{timestamp}id_/{official}",
            archive_timestamp=timestamp,
            content_sha256=hashlib.sha256(body).hexdigest(),
            wayback_cdx_query_url=discovery_receipt["query_url"],
            wayback_cdx_response_sha256=discovery_receipt["response_sha256"],
            wayback_cdx_fetched_at=discovery_receipt["fetched_at"],
        )
        kwargs["result_callback"](official, fetched)
        return ArchivalMultiFetchResult(
            results=[fetched],
            errors=[None],
            stats={"requested_pages": 1, "wayback_inventory": outcome["stats"]},
        )

    async def _no_cache(**_kwargs):
        return None

    monkeypatch.setattr(
        wayback_machine_engine,
        "fetch_wayback_capture_inventory",
        _inventory,
    )
    monkeypatch.setattr(ArchivalFetchClient, "fetch_many_with_fallback", _many)
    scraper = _InventoryFrontierScraper("NH", "New Hampshire")
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="NH",
        parser_name=type(scraper).__name__,
    )
    scraper.attach_state_law_acquisition_ledger(ledger)
    monkeypatch.setattr(scraper, "_cache_successful_page_fetch", _no_cache)

    result = await scraper._fetch_page_contents_with_archival_fallback(
        [official],
        content_validator=lambda payload: b"section 1:1" in payload,
        media_type="text/html",
        prefer_direct=True,
        wayback_prefix_inventory=True,
    )

    assert inventory_calls == [[official]]
    assert result.payloads == [body]
    assert result.errors == [None]
    assert result.transport_receipts[0] == {
        "archive_timestamp": timestamp,
        "archive_url": f"https://web.archive.org/web/{timestamp}id_/{official}",
        "content_sha256": hashlib.sha256(body).hexdigest(),
        "official_url": official,
        "source_transport": "wayback",
        "wayback_cdx_query_url": discovery_query,
        "wayback_cdx_response_sha256": "b" * 64,
        "wayback_cdx_fetched_at": "2026-08-25T00:00:00+00:00",
    }
    assert result.parser_input_envelopes[0] is not None
    assert len(ledger.entries) == 1
    assert scraper._state_law_archive_discovery_receipts == [discovery_receipt]
    assert result.stats["eager_parser_inputs_admitted"] == 1
