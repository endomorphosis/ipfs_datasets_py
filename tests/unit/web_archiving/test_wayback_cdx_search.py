from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import parse_qs, urlparse

import pytest

from ipfs_datasets_py.processors.web_archiving.wayback_machine_engine import (
    fetch_wayback_capture_inventory,
    fetch_wayback_cdx_rows,
    parse_exact_http_locator,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.gov/a/../b",
        "https://example.gov/a/./b",
        "https://example.gov/%65xample",
        "https://example.gov/code%2fsection",
        "https://example.gov/code?q=%2f",
        "https://%65xample.gov/x",
        "https://example.%67ov/x",
        "https://example%2egov/x",
        "https://EXAMPLE.gov/code",
        "https://example.gov/code?",
        "https://example.gov/a{b",
    ],
)
def test_exact_locator_rejects_spellings_mutated_by_request_preparation(url: str) -> None:
    import requests

    assert requests.Request("GET", url).prepare().url != url
    with pytest.raises(ValueError):
        parse_exact_http_locator(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.gov/code/Chapter%201.xml",
        "https://example.gov/code/title%2Fsection?q=a+b&x=%2F",
        "https://example.gov/code/?a=1&b=2",
    ],
)
def test_exact_locator_accepts_request_stable_retained_spellings(url: str) -> None:
    import requests

    assert requests.Request("GET", url).prepare().url == url
    assert parse_exact_http_locator(url).raw == url


@pytest.mark.anyio
async def test_inventory_fans_one_verified_identity_capture_to_every_raw_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine

    canonical = "https://example.gov/code/section-1"
    aliases = [canonical, canonical + "/", canonical.replace(".gov", ".gov:443")]
    calls: list[str] = []

    async def _query(cdx_url: str, *, timeout_seconds: int):
        del timeout_seconds
        calls.append(cdx_url)
        return {
            "status": "success",
            "results": [
                {
                    "timestamp": "20260824010203",
                    "original_url": canonical.replace(".gov", ".gov:443"),
                    "statuscode": "200",
                    "mimetype": "text/html",
                }
            ],
            "receipt": {
                "response_sha256": "a" * 64,
                "fetched_at": "2026-08-24T01:02:04+00:00",
            },
        }

    monkeypatch.setattr(wayback_machine_engine, "fetch_wayback_cdx_rows", _query)
    outcome = await fetch_wayback_capture_inventory(
        aliases,
        max_queries=1,
        query_attempts=1,
    )

    assert len(calls) == 1
    exact_filter = parse_qs(urlparse(calls[0]).query)["filter"][1]
    assert re.escape(canonical) in exact_filter
    assert re.escape(canonical.replace(".gov", ".gov:443")) in exact_filter
    assert set(outcome["captures_by_url"]) == set(aliases)
    for alias in aliases:
        capture = outcome["captures_by_url"][alias]
        assert capture["original_url"] == alias
        assert capture["wayback_url"].endswith("id_/" + alias)
    assert outcome["stats"]["unique_pages"] == 1
    assert outcome["stats"]["matched_pages"] == 1
    assert outcome["stats"]["matched_requested_aliases"] == 3


@pytest.mark.anyio
async def test_shared_wayback_cdx_fetch_normalizes_rows_and_retains_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        [
            "urlkey",
            "timestamp",
            "original",
            "mimetype",
            "statuscode",
            "digest",
            "length",
        ],
        [
            "gov,example)/code/1",
            "20260824000000",
            "https://example.gov/code/1",
            "text/html",
            "200",
            "ABC123",
            "321",
        ],
    ]
    payload = json.dumps(rows, separators=(",", ":")).encode("utf-8")
    observed: dict[str, object] = {}

    class _Response:
        status_code = 200
        url = (
            "https://web.archive.org/cdx/search/cdx?"
            "url=example.gov/code/*&output=json"
        )
        content = payload

        @staticmethod
        def raise_for_status() -> None:
            return None

    def _get(url, **kwargs):
        observed.update(url=url, **kwargs)
        return _Response()

    monkeypatch.setattr("requests.get", _get)

    result = await fetch_wayback_cdx_rows(
        "https://web.archive.org/cdx/search/cdx?url=example.gov/code/*&output=json",
        timeout_seconds=17,
    )

    assert result["status"] == "success"
    assert str(observed["url"]).startswith("https://web.archive.org/")
    assert observed["timeout"] == 17
    assert observed["allow_redirects"] is False
    assert result["rows"] == rows
    assert result["results"] == [
        {
            "urlkey": "gov,example)/code/1",
            "timestamp": "20260824000000",
            "original": "https://example.gov/code/1",
            "mimetype": "text/html",
            "statuscode": "200",
            "digest": "ABC123",
            "length": "321",
            "original_url": "https://example.gov/code/1",
            "wayback_url": (
                "https://web.archive.org/web/20260824000000id_/"
                "https://example.gov/code/1"
            ),
        }
    ]
    receipt = result["receipt"]
    assert receipt["source_transport"] == "wayback_cdx"
    assert receipt["response_sha256"] == hashlib.sha256(payload).hexdigest()
    assert receipt["response_length"] == len(payload)
    assert receipt["row_count"] == 1


@pytest.mark.anyio
async def test_shared_wayback_cdx_fetch_rejects_non_wayback_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def _get(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("network must not be attempted")

    monkeypatch.setattr("requests.get", _get)

    result = await fetch_wayback_cdx_rows(
        "https://example.invalid/cdx/search/cdx?url=example.gov/*"
    )

    assert result["status"] == "error"
    assert result["rows"] == []
    assert called is False


@pytest.mark.anyio
@pytest.mark.parametrize(
    "query_url",
    [
        "http://web.archive.org/cdx/search/cdx?url=https://example.gov/code",
        "https://www.web.archive.org/cdx/search/cdx?url=https://example.gov/code",
        "https://web.archive.org:443/cdx/search/cdx?url=https://example.gov/code",
        "https://web.archive.org/prefix/cdx/search/cdx?url=https://example.gov/code",
        "https://web.archive.org/cdx/search/cdx/?url=https://example.gov/code",
        "https://user@web.archive.org/cdx/search/cdx?url=https://example.gov/code",
        "https://web.archive.org/cdx/search/cdx?url=https://example.gov/code#",
    ],
)
async def test_shared_wayback_cdx_fetch_rejects_noncanonical_locator_before_network(
    monkeypatch: pytest.MonkeyPatch,
    query_url: str,
) -> None:
    called = False

    def _get(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("noncanonical CDX URL must fail before network")

    monkeypatch.setattr("requests.get", _get)
    result = await fetch_wayback_cdx_rows(query_url)

    assert result["status"] == "error"
    assert called is False


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status_code", "response_url"),
    [
        (302, "https://web.archive.org/cdx/search/cdx?url=https://example.gov/code"),
        (200, ""),
        (200, "https://web.archive.org/cdx/search/cdx?url=https://example.gov/other"),
        (200, "https://web.archive.org/cdx/search/cdx?url=https://example.gov/code#"),
    ],
)
async def test_shared_wayback_cdx_fetch_rejects_status_or_final_locator_drift(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    response_url: str,
) -> None:
    request_url = (
        "https://web.archive.org/cdx/search/cdx?url=https://example.gov/code"
    )

    class _Response:
        content = b"[]"

        def __init__(self) -> None:
            self.status_code = status_code
            self.url = response_url
            self.headers: dict[str, str] = {}

    observed: dict[str, object] = {}

    def _get(url: str, **kwargs):
        observed.update(url=url, **kwargs)
        return _Response()

    monkeypatch.setattr("requests.get", _get)
    result = await fetch_wayback_cdx_rows(request_url)

    assert result["status"] == "error"
    assert observed["allow_redirects"] is False


@pytest.mark.anyio
@pytest.mark.parametrize(
    "official_url",
    [
        "https://example.gov/code#",
        "https://user@example.gov/code",
        "https://example.gov:444/code",
        "https://example.gov:80/code",
        "https://example.gov:/code",
        " https://example.gov/code",
    ],
)
async def test_wayback_inventory_rejects_invalid_official_locator_before_network(
    monkeypatch: pytest.MonkeyPatch,
    official_url: str,
) -> None:
    from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine

    async def _forbid(*_args, **_kwargs):
        raise AssertionError("invalid official URL must fail before CDX transport")

    monkeypatch.setattr(wayback_machine_engine, "fetch_wayback_cdx_rows", _forbid)
    with pytest.raises(ValueError):
        await fetch_wayback_capture_inventory([official_url], query_attempts=1)


@pytest.mark.anyio
async def test_wayback_capture_inventory_groups_prefixes_and_isolates_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine

    first = "https://gc.nh.gov/rsa/html/I/1/1-1.htm"
    second = "https://gc.nh.gov/rsa/html/I/1/1-2.htm"
    isolated = "https://gc.nh.gov/rsa/html/II/12/12-1.htm"
    calls: list[str] = []

    async def _query(cdx_url: str, *, timeout_seconds: int):
        calls.append(cdx_url)
        assert timeout_seconds == 11
        query = parse_qs(urlparse(cdx_url).query)
        assert query["matchType"] == ["prefix"]
        assert query["sort"] == ["reverse"]
        assert query["collapse"] == ["urlkey"]
        assert query["filter"][0] == "statuscode:200"
        assert query["filter"][1].startswith("original:^(?:")
        assert not any(value.startswith("mimetype:") for value in query["filter"])
        assert int(query["limit"][0]) <= 240
        prefix = query["url"][0]
        if "/II/12/" in prefix:
            return {
                "status": "error",
                "error": "TimeoutError: isolated prefix timed out",
                "results": [],
            }
        return {
            "status": "success",
            "results": [
                {
                    "timestamp": "20250101000000",
                    "original_url": first,
                    "statuscode": "200",
                    "mimetype": "text/html",
                },
                {
                    "timestamp": "20260101000000",
                    "original_url": first,
                    "statuscode": "200",
                    "mimetype": "text/html",
                },
                {
                    "timestamp": "20250202000000",
                    "original_url": second,
                    "statuscode": "200",
                    "mimetype": "text/html",
                },
            ],
            "receipt": {
                "response_sha256": "a" * 64,
                "fetched_at": "2026-08-25T00:00:00+00:00",
            },
        }

    monkeypatch.setattr(wayback_machine_engine, "fetch_wayback_cdx_rows", _query)
    outcome = await fetch_wayback_capture_inventory(
        [first, second, isolated],
        timeout_seconds=11,
        max_queries=4,
        max_results_per_query=240,
        query_attempts=1,
    )

    assert outcome["status"] == "partial"
    assert len(calls) == 2
    assert set(outcome["captures_by_url"]) == {first, second}
    assert outcome["captures_by_url"][first]["timestamp"] == "20260101000000"
    assert outcome["captures_by_url"][first]["wayback_url"] == (
        "https://web.archive.org/web/20260101000000id_/"
        f"{first}"
    )
    assert outcome["captures_by_url"][second]["original_url"] == second
    assert outcome["stats"]["prefix_queries_succeeded"] == 1
    assert outcome["stats"]["prefix_queries_failed"] == 1
    assert outcome["stats"]["matched_pages"] == 2
    assert outcome["receipts"][0]["query_target_count"] == 2


@pytest.mark.anyio
async def test_wayback_capture_inventory_collapses_latest_capture_per_exact_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine

    first = "https://law.lis.virginia.gov/vacode/title1/chapter1/section1-1/"
    second = "https://law.lis.virginia.gov/vacode/title1/chapter1/section1-2/"
    histories = {
        first: ["20210102030405", "20250809010203"],
        second: ["20221213141516", "20260708091011"],
    }
    calls: list[str] = []

    async def _query(cdx_url: str, *, timeout_seconds: int):
        del timeout_seconds
        calls.append(cdx_url)
        query = parse_qs(urlparse(cdx_url).query)
        reverse = query.get("sort") == ["reverse"]
        rows = []
        for original_url, timestamps in histories.items():
            ordered = sorted(timestamps, reverse=reverse)
            # Model CDX collapse=urlkey: only the first adjacent capture for
            # each exact URL key survives.  Without sort=reverse this is the
            # stale, earliest capture that caused the VA selector drift.
            rows.append(
                {
                    "urlkey": original_url,
                    "timestamp": ordered[0],
                    "original_url": original_url,
                    "statuscode": "200",
                    "mimetype": "text/html",
                }
            )
        return {"status": "success", "results": rows}

    monkeypatch.setattr(wayback_machine_engine, "fetch_wayback_cdx_rows", _query)
    outcome = await fetch_wayback_capture_inventory(
        [first, second],
        max_queries=1,
        query_attempts=1,
    )

    assert len(calls) == 1
    query = parse_qs(urlparse(calls[0]).query)
    assert query["sort"] == ["reverse"]
    assert query["collapse"] == ["urlkey"]
    assert outcome["captures_by_url"][first]["timestamp"] == "20250809010203"
    assert outcome["captures_by_url"][second]["timestamp"] == "20260708091011"
    assert outcome["captures_by_url"][first]["wayback_url"] == (
        "https://web.archive.org/web/20250809010203id_/"
        f"{first}"
    )
    assert outcome["stats"]["prefix_queries_attempted"] == 1
    assert outcome["stats"]["exact_filter_query_batches"] == 1
    assert outcome["stats"]["server_side_latest_capture_order"] == "reverse"
    assert outcome["stats"]["server_side_collapse"] == "urlkey"


@pytest.mark.anyio
async def test_wayback_capture_inventory_admits_html_xml_pdf_and_blank_mime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine

    media_by_url = {
        "https://example.gov/code/page.html": "text/html",
        "https://example.gov/code/chapter.xml": "application/xml",
        "https://example.gov/code/title.pdf": "application/pdf",
        # Blank and mislabeled CDX MIME values must not hide a replay whose
        # body can still pass the corpus-specific validator.
        "https://example.gov/code/unlabelled": "",
    }
    non_eligible_rows = {
        "https://example.gov/code/not-found.xml": {
            "timestamp": "20260826000000",
            "statuscode": "404",
            "mimetype": "application/xml",
        },
        "https://example.gov/code/impossible-date.pdf": {
            "timestamp": "20260230000000",
            "statuscode": "200",
            "mimetype": "application/pdf",
        },
    }
    observed_query_urls: list[str] = []

    async def _query(cdx_url: str, *, timeout_seconds: int):
        del timeout_seconds
        observed_query_urls.append(cdx_url)
        query = parse_qs(urlparse(cdx_url).query)
        assert query["filter"][0] == "statuscode:200"
        assert query["filter"][1].startswith("original:^(?:")
        assert not any(value.startswith("mimetype:") for value in query["filter"])
        expression = query["filter"][1].split(":", 1)[1]
        eligible = [
            {
                "timestamp": "20260826000000",
                "original_url": url,
                "statuscode": "200",
                "mimetype": mime_type,
            }
            for url, mime_type in media_by_url.items()
            if re.fullmatch(expression, url)
        ]
        ineligible = [
            {"original_url": url, **row}
            for url, row in non_eligible_rows.items()
            if re.fullmatch(expression, url)
        ]
        return {
            "status": "success",
            "results": [*eligible, *ineligible],
        }

    monkeypatch.setattr(wayback_machine_engine, "fetch_wayback_cdx_rows", _query)
    outcome = await fetch_wayback_capture_inventory(
        [*media_by_url, *non_eligible_rows],
        max_queries=1,
        query_attempts=1,
    )

    assert len(observed_query_urls) == 1
    assert len(observed_query_urls[0].encode("ascii")) <= 2_048
    assert set(outcome["captures_by_url"]) == set(media_by_url)
    assert {
        url: capture.get("mimetype", "")
        for url, capture in outcome["captures_by_url"].items()
    } == media_by_url
    assert outcome["stats"]["eligible_capture_rows"] == len(media_by_url)
    assert outcome["stats"]["unmatched_pages"] == len(non_eligible_rows)
    assert outcome["stats"]["server_side_exact_original_filter"] is True
    assert outcome["stats"]["server_side_mimetype_filter"] is False


@pytest.mark.anyio
async def test_wayback_capture_inventory_enforces_query_bound_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine

    async def _forbid(*_args, **_kwargs):
        raise AssertionError("query bound must fail before network")

    monkeypatch.setattr(wayback_machine_engine, "fetch_wayback_cdx_rows", _forbid)
    with pytest.raises(ValueError, match="more prefix queries"):
        await fetch_wayback_capture_inventory(
            [
                "https://gc.nh.gov/rsa/page.htm?id=1",
                "https://gc.nh.gov/rsa/page.htm?id=2",
            ],
            max_queries=1,
        )


@pytest.mark.anyio
async def test_wayback_capture_inventory_coalesces_sibling_paths_to_query_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine

    urls = [
        "https://gc.nh.gov/rsa/html/I/1/1-1.htm",
        "https://gc.nh.gov/rsa/html/II/2/2-1.htm",
    ]
    observed_prefixes: list[str] = []

    async def _query(cdx_url: str, *, timeout_seconds: int):
        del timeout_seconds
        observed_prefixes.append(parse_qs(urlparse(cdx_url).query)["url"][0])
        return {
            "status": "success",
            "results": [
                {
                    "timestamp": f"2025010100000{index}",
                    "original_url": url,
                    "statuscode": "200",
                    "mimetype": "text/html",
                }
                for index, url in enumerate(urls)
            ],
            "receipt": {"response_sha256": "c" * 64},
        }

    monkeypatch.setattr(wayback_machine_engine, "fetch_wayback_cdx_rows", _query)
    outcome = await fetch_wayback_capture_inventory(urls, max_queries=1)

    assert observed_prefixes == ["https://gc.nh.gov/rsa/html/"]
    assert set(outcome["captures_by_url"]) == set(urls)
    assert outcome["stats"]["prefix_queries_planned"] == 1


@pytest.mark.anyio
async def test_va_residual_inventory_merges_at_vacode_and_partitions_8_8_6(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine

    urls = [
        (
            "https://law.lis.virginia.gov/vacode/"
            f"title58.1/chapter{chapter}/section58.1-{1000 + chapter}/"
        )
        for chapter in range(1, 14)
    ] + [
        (
            "https://law.lis.virginia.gov/vacode/"
            f"title{title}.1/chapter1/section{title}.1-{2000 + title}/"
        )
        for title in range(1, 10)
    ]
    observed_batches: list[list[str]] = []
    observed_prefixes: list[str] = []
    observed_query_bytes: list[int] = []
    attempts_by_batch: dict[tuple[str, ...], int] = {}
    ordered_urls = sorted(urls)
    transient_batch = tuple(ordered_urls[8:16])

    async def _query(cdx_url: str, *, timeout_seconds: int):
        del timeout_seconds
        query = parse_qs(urlparse(cdx_url).query)
        expression = query["filter"][1].split(":", 1)[1]
        members = [url for url in ordered_urls if re.fullmatch(expression, url)]
        observed_batches.append(members)
        observed_prefixes.append(query["url"][0])
        observed_query_bytes.append(len(cdx_url.encode("ascii")))
        batch_key = tuple(members)
        attempts_by_batch[batch_key] = attempts_by_batch.get(batch_key, 0) + 1
        if batch_key == transient_batch and attempts_by_batch[batch_key] == 1:
            return {
                "status": "error",
                "error": "ReadTimeout: exact grouped CDX request timed out",
            }
        return {
            "status": "success",
            "results": [
                {
                    "timestamp": "20260101000000",
                    "original_url": url,
                    "statuscode": "200",
                    "mimetype": "text/html",
                }
                for url in members
            ],
            "receipt": {"response_sha256": "f" * 64},
        }

    monkeypatch.setattr(wayback_machine_engine, "fetch_wayback_cdx_rows", _query)
    outcome = await fetch_wayback_capture_inventory(
        list(reversed(urls)),
        max_queries=1,
        query_attempts=2,
        retry_delay_seconds=0,
    )

    assert [len(batch) for batch in observed_batches] == [8, 8, 8, 6]
    assert list(attempts_by_batch) == [
        tuple(ordered_urls[:8]),
        transient_batch,
        tuple(ordered_urls[16:]),
    ]
    assert sorted(attempts_by_batch.values()) == [1, 1, 2]
    assert observed_prefixes == [
        "https://law.lis.virginia.gov/vacode/",
    ] * 4
    assert max(observed_query_bytes) <= 2_048
    assert set(outcome["captures_by_url"]) == set(urls)
    assert outcome["stats"]["prefix_groups_planned"] == 1
    assert outcome["stats"]["prefix_queries_planned"] == 3
    assert outcome["stats"]["cdx_requests"] == 4
    assert outcome["stats"]["cdx_retries"] == 1
    assert outcome["stats"]["query_target_bound"] == 8


@pytest.mark.anyio
async def test_va_mixed_title_inventory_preserves_tight_prefixes_under_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine

    section_paths = [
        ("19.2", "25", "19.2-399"),
        ("46.2", "10", "46.2-1135"),
        ("46.2", "6", "46.2-694"),
        ("46.2", "6", "46.2-694.1"),
        ("46.2", "6", "46.2-697"),
        ("46.2", "6", "46.2-698"),
        ("58.1", "24", "58.1-2402"),
        ("58.1", "24", "58.1-2425"),
        ("58.1", "27", "58.1-2701"),
        ("58.1", "3", "58.1-416"),
        ("58.1", "3", "58.1-520"),
        ("58.1", "3", "58.1-530"),
        ("58.1", "6", "58.1-603.1"),
        ("58.1", "6", "58.1-604"),
        ("58.1", "6", "58.1-604.01"),
        ("58.1", "6", "58.1-604.1"),
        ("58.1", "6", "58.1-614"),
        ("58.1", "8", "58.1-811"),
        ("58.1", "8", "58.1-816"),
    ]
    urls = [
        (
            "https://law.lis.virginia.gov/vacode/"
            f"title{title}/chapter{chapter}/section{section}/"
        )
        for title, chapter, section in section_paths
    ]
    observed_prefixes: list[str] = []
    observed_members: list[list[str]] = []

    async def _query(cdx_url: str, *, timeout_seconds: int):
        del timeout_seconds
        assert len(cdx_url.encode("ascii")) <= 2_048
        query = parse_qs(urlparse(cdx_url).query)
        prefix = query["url"][0]
        expression = query["filter"][1].split(":", 1)[1]
        members = [url for url in sorted(urls) if re.fullmatch(expression, url)]
        observed_prefixes.append(prefix)
        observed_members.append(members)
        return {
            "status": "success",
            "results": [
                {
                    "timestamp": "20260101000000",
                    "original_url": url,
                    "statuscode": "200",
                    "mimetype": "text/html",
                }
                for url in members
            ],
            "receipt": {"response_sha256": "e" * 64},
        }

    monkeypatch.setattr(wayback_machine_engine, "fetch_wayback_cdx_rows", _query)
    outcome = await fetch_wayback_capture_inventory(
        list(reversed(urls)),
        max_queries=8,
        max_queries_per_origin=8,
        query_attempts=1,
    )

    assert len(observed_prefixes) == 8
    assert len(observed_prefixes) < len(urls)
    assert all(1 <= len(members) <= 8 for members in observed_members)
    assert [url for members in observed_members for url in members] == sorted(urls)
    assert all(
        prefix.startswith("https://law.lis.virginia.gov/vacode/title")
        and "/chapter" in prefix
        for prefix in observed_prefixes
    )
    assert "https://law.lis.virginia.gov/" not in observed_prefixes
    assert "https://law.lis.virginia.gov/vacode/" not in observed_prefixes
    assert set(outcome["captures_by_url"]) == set(urls)
    assert outcome["stats"]["prefix_groups_planned"] == 8
    assert outcome["stats"]["prefix_queries_planned"] == 8
    assert outcome["stats"]["cdx_requests"] == 8
    assert outcome["stats"]["max_queries_per_origin"] == 8
    assert outcome["stats"]["logical_prefix_groups_by_origin"] == {
        "https://law.lis.virginia.gov": 8
    }
    assert outcome["stats"]["exact_filter_batches_by_origin"] == {
        "https://law.lis.virginia.gov": 8
    }


@pytest.mark.anyio
async def test_broad_inventory_server_filter_precedes_limit_and_recovers_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine

    targets = [
        (
            "https://law.lis.virginia.gov/vacode/"
            f"title2.2/chapter{index}/section2.2-{1000 + index}/"
        )
        for index in range(1, 6)
    ]
    unrelated = [
        {
            "timestamp": "20250101000000",
            "original_url": (
                "https://law.lis.virginia.gov/vacode/"
                f"title2.2/chapter999/section2.2-{index}/"
            ),
            "statuscode": "200",
            "mimetype": "text/html",
        }
        for index in range(500)
    ]
    exact = [
        {
            "timestamp": f"2026010100000{index}",
            "original_url": target,
            "statuscode": "200",
            "mimetype": "text/html",
        }
        for index, target in enumerate(targets)
    ]
    calls: list[str] = []

    async def _query(cdx_url: str, *, timeout_seconds: int):
        del timeout_seconds
        calls.append(cdx_url)
        query = parse_qs(urlparse(cdx_url).query)
        assert query["url"] == [
            "https://law.lis.virginia.gov/vacode/title2.2/"
        ]
        exact_filter = query["filter"][1]
        assert exact_filter.startswith("original:")
        expression = exact_filter.split(":", 1)[1]
        limit = int(query["limit"][0])
        # Model CDX semantics: the exact-original server filter is evaluated
        # before limit.  Without that filter, the 500 unrelated rows would
        # consume the whole bounded response before any target appeared.
        filtered = [
            row
            for row in [*unrelated, *exact]
            if re.fullmatch(expression, str(row["original_url"]))
        ]
        return {
            "status": "success",
            "results": filtered[:limit],
            "receipt": {"response_sha256": "e" * 64},
        }

    monkeypatch.setattr(wayback_machine_engine, "fetch_wayback_cdx_rows", _query)
    outcome = await fetch_wayback_capture_inventory(
        targets,
        max_queries=1,
        query_attempts=1,
    )

    assert len(calls) == 1
    assert set(outcome["captures_by_url"]) == set(targets)
    assert outcome["stats"]["inventory_rows"] == len(targets)
    assert outcome["stats"]["server_side_exact_original_filter"] is True
    assert outcome["stats"]["exact_original_filter_variants"] == len(targets) * 2
    assert outcome["stats"]["exact_filter_non_truncation_proved"] is True


@pytest.mark.anyio
async def test_exact_inventory_rejects_server_filter_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine

    target = "https://example.gov/code/section-1/"

    async def _query(_cdx_url: str, *, timeout_seconds: int):
        del timeout_seconds
        return {
            "status": "success",
            "results": [
                {
                    "timestamp": "20260101000000",
                    "original_url": "https://example.gov/code/unrelated/",
                    "statuscode": "200",
                    "mimetype": "text/html",
                }
            ],
        }

    monkeypatch.setattr(wayback_machine_engine, "fetch_wayback_cdx_rows", _query)
    outcome = await fetch_wayback_capture_inventory([target], query_attempts=1)

    assert outcome["status"] == "error"
    assert outcome["captures_by_url"] == {}
    assert "violated the exact-original" in outcome["errors"][0]["error"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "returned_original",
    [
        "https://example.gov/code?b=%2F&a=1+2",
        "https://example.gov/code?a=1%202&b=%2F",
        "https://example.gov/code?a=1+2&b=%2f",
        "https://example.gov/code?a=1+2&b=%2F/",
        "https://example.gov/code//?a=1+2&b=%2F",
    ],
)
async def test_exact_inventory_rejects_raw_query_and_path_aliases(
    monkeypatch: pytest.MonkeyPatch,
    returned_original: str,
) -> None:
    from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine

    target = "https://example.gov/code?a=1+2&b=%2F"

    async def _query(_cdx_url: str, *, timeout_seconds: int):
        del timeout_seconds
        return {
            "status": "success",
            "results": [
                {
                    "timestamp": "20260101000000",
                    "original_url": returned_original,
                    "statuscode": "200",
                }
            ],
        }

    monkeypatch.setattr(wayback_machine_engine, "fetch_wayback_cdx_rows", _query)
    outcome = await fetch_wayback_capture_inventory([target], query_attempts=1)

    assert outcome["status"] == "error"
    assert outcome["captures_by_url"] == {}


@pytest.mark.anyio
async def test_exact_inventory_partitions_oversized_filter_into_bounded_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine

    urls = [
        "https://example.gov/code/"
        + ("very-long-segment-" * 4)
        + f"{index}/"
        for index in range(300)
    ]
    calls: list[str] = []

    async def _query(cdx_url: str, *, timeout_seconds: int):
        del timeout_seconds
        calls.append(cdx_url)
        assert len(cdx_url.encode("ascii")) <= 2_048
        query = parse_qs(urlparse(cdx_url).query)
        expression = query["filter"][1].split(":", 1)[1]
        limit = int(query["limit"][0])
        matches = [url for url in urls if re.fullmatch(expression, url)]
        assert len(matches) <= 8
        return {
            "status": "success",
            "results": [
                {
                    "timestamp": "20260101000000",
                    "original_url": url,
                    "statuscode": "200",
                    "mimetype": "text/html",
                }
                for url in matches[:limit]
            ],
        }

    monkeypatch.setattr(wayback_machine_engine, "fetch_wayback_cdx_rows", _query)
    outcome = await fetch_wayback_capture_inventory(
        urls,
        max_queries=1,
        max_results_per_query=5_000,
        query_attempts=1,
    )

    assert 1 < len(calls) < len(urls)
    assert set(outcome["captures_by_url"]) == set(urls)
    assert outcome["stats"]["prefix_groups_planned"] == 1
    assert outcome["stats"]["prefix_queries_planned"] == len(calls)
    assert outcome["stats"]["exact_filter_query_batches"] == len(calls)
    assert outcome["stats"]["exact_filter_batches_added"] == len(calls) - 1
    assert outcome["stats"]["query_target_bound"] == 8
    assert outcome["stats"]["query_url_byte_bound"] == 2_048


@pytest.mark.anyio
async def test_wayback_capture_inventory_retries_only_transient_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine

    first = "https://gc.nh.gov/rsa/html/I/1/1-1.htm"
    second = "https://gc.nh.gov/rsa/html/II/2/2-1.htm"
    attempts_by_prefix: dict[str, int] = {}

    async def _query(cdx_url: str, *, timeout_seconds: int):
        del timeout_seconds
        prefix = parse_qs(urlparse(cdx_url).query)["url"][0]
        attempts_by_prefix[prefix] = attempts_by_prefix.get(prefix, 0) + 1
        if "/I/1/" in prefix and attempts_by_prefix[prefix] == 1:
            return {
                "status": "error",
                "response_status": 429,
                "retry_after": "0",
                "error": "HTTPError: 429 Too Many Requests",
            }
        official = first if "/I/1/" in prefix else second
        return {
            "status": "success",
            "results": [
                {
                    "timestamp": "20250212203224",
                    "original_url": official,
                    "statuscode": "200",
                    "mimetype": "text/html",
                }
            ],
            "receipt": {"response_sha256": "d" * 64},
        }

    monkeypatch.setattr(wayback_machine_engine, "fetch_wayback_cdx_rows", _query)
    outcome = await fetch_wayback_capture_inventory(
        [first, second],
        max_queries=4,
        query_attempts=2,
        retry_delay_seconds=0,
    )

    assert outcome["status"] == "success"
    assert set(outcome["captures_by_url"]) == {first, second}
    assert sorted(attempts_by_prefix.values()) == [1, 2]
    assert outcome["stats"]["cdx_requests"] == 3
    assert outcome["stats"]["cdx_retries"] == 1


@pytest.mark.anyio
async def test_state_scraper_retains_cdx_discovery_receipt_separately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.iowa import (
        IowaScraper,
    )
    from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine

    rows = [
        ["urlkey", "timestamp", "original"],
        ["gov,iowa,legis)/docs/code/1", "20260824000000", "https://www.legis.iowa.gov/docs/code/1.html"],
    ]
    receipt = {
        "source_transport": "wayback_cdx",
        "response_sha256": "a" * 64,
    }

    async def _shared_query(url: str, *, timeout_seconds: int):
        assert "web.archive.org/cdx/search/cdx" in url
        assert timeout_seconds == 19
        return {
            "status": "success",
            "rows": rows,
            "results": [],
            "receipt": receipt,
        }

    monkeypatch.setattr(
        wayback_machine_engine,
        "fetch_wayback_cdx_rows",
        _shared_query,
    )
    scraper = IowaScraper("IA", "Iowa")

    observed = await scraper._fetch_cdx_rows(
        "https://web.archive.org/cdx/search/cdx?url=www.legis.iowa.gov/docs/code/*",
        timeout=19,
    )

    assert observed == rows
    assert scraper._state_law_archive_discovery_receipts == [receipt]
