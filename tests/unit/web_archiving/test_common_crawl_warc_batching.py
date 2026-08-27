from __future__ import annotations

import base64
import gzip
import hashlib
from types import SimpleNamespace

import anyio
import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
    state_archival_fetch,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    BaseStateScraper,
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.state_archival_fetch import (
    ArchivalFetchClient,
    CommonCrawlBatchFetchResult,
    FetchResult,
    _same_archived_resource,
)
from ipfs_datasets_py.processors.web_archiving.common_crawl_integration import (
    CommonCrawlSearchEngine,
)
from ipfs_datasets_py.processors.web_archiving.common_crawl_search_engine.ccindex import (
    api as common_crawl_api,
)

TEST_CC_COLLECTION = "CC-MAIN-2026-30"
TEST_SHARED_WARC = f"crawl-data/{TEST_CC_COLLECTION}/warc/shared.warc.gz"
TEST_OTHER_WARC = f"crawl-data/{TEST_CC_COLLECTION}/warc/other.warc.gz"
TEST_WARC_URL = f"https://data.commoncrawl.org/{TEST_SHARED_WARC}"
_AUTO_PAYLOAD_DIGEST = object()


def _payload_sha1_base32(body: bytes) -> str:
    return base64.b32encode(hashlib.sha1(body).digest()).decode("ascii")


def _warc_member(
    body: bytes,
    *,
    target_url: str,
    timestamp: str = "20260824000000",
    payload_digest: object = _AUTO_PAYLOAD_DIGEST,
    response_status: int = 200,
) -> bytes:
    http = (
        f"HTTP/1.1 {response_status} Archived Response\r\n".encode("ascii")
        + b"Content-Type: text/html; charset=utf-8\r\n"
        + f"Content-Length: {len(body)}\r\n".encode("ascii")
        + b"\r\n"
        + body
    )
    if payload_digest is _AUTO_PAYLOAD_DIGEST:
        payload_digest = f"sha1:{_payload_sha1_base32(body)}"
    digest_header = (
        f"WARC-Payload-Digest: {payload_digest}\r\n".encode("ascii")
        if payload_digest is not None
        else b""
    )
    warc = (
        b"WARC/1.0\r\n"
        b"WARC-Type: response\r\n"
        + f"WARC-Target-URI: {target_url}\r\n".encode()
        + (
            "WARC-Date: "
            f"{timestamp[0:4]}-{timestamp[4:6]}-{timestamp[6:8]}T"
            f"{timestamp[8:10]}:{timestamp[10:12]}:{timestamp[12:14]}Z\r\n"
        ).encode("ascii")
        + digest_header
        + f"Content-Length: {len(http)}\r\n".encode("ascii")
        + b"\r\n"
        + http
    )
    return gzip.compress(warc)


def test_range_transport_binds_final_url_status_headers_and_exact_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}
    payload = b"abcde"

    class _Response:
        status = 206
        headers = {
            "Content-Range": "bytes 10-14/100",
            "Content-Length": "5",
        }

        def geturl(self) -> str:
            return TEST_WARC_URL

        def read(self, limit: int) -> bytes:
            observed["read_limit"] = limit
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class _Opener:
        def open(self, request, *, timeout):
            observed["request"] = request
            observed["timeout"] = timeout
            return _Response()

    def _build_opener(handler):
        observed["handler"] = handler
        return _Opener()

    monkeypatch.setattr(common_crawl_api.urllib.request, "build_opener", _build_opener)
    status, data, error = common_crawl_api._http_range_get_cached(
        url=TEST_WARC_URL,
        start=10,
        end_inclusive=14,
        timeout_s=7,
        cache_dir=None,
        cache_max_bytes=0,
        cache_max_item_bytes=0,
    )

    assert (status, data, error) == (206, payload, None)
    assert isinstance(observed["handler"], common_crawl_api._NoHttpRedirectHandler)
    assert observed["request"].get_header("Range") == "bytes=10-14"
    assert observed["read_limit"] == 6


@pytest.mark.parametrize(
    ("status", "final_url", "content_range", "content_length", "payload", "error_text"),
    [
        (200, TEST_WARC_URL, "bytes 10-14/100", "5", b"abcde", "expected 206"),
        (206, TEST_WARC_URL + "?alias=1", "bytes 10-14/100", "5", b"abcde", "locator drifted"),
        (206, TEST_WARC_URL, "bytes 11-15/100", "5", b"abcde", "Content-Range"),
        (206, TEST_WARC_URL, "bytes 10-14/*", "5", b"abcde", "Content-Range"),
        (206, TEST_WARC_URL, "bytes 10-14/100", "6", b"abcde", "Content-Length"),
        (206, TEST_WARC_URL, "bytes 10-14/100", "5", b"abcd", "length mismatch"),
    ],
)
def test_range_transport_rejects_every_response_identity_drift(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    final_url: str,
    content_range: str,
    content_length: str,
    payload: bytes,
    error_text: str,
) -> None:
    class _Response:
        headers = {
            "Content-Range": content_range,
            "Content-Length": content_length,
        }

        def __init__(self) -> None:
            self.status = status

        def geturl(self) -> str:
            return final_url

        def read(self, _limit: int) -> bytes:
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class _Opener:
        def open(self, _request, *, timeout):
            del timeout
            return _Response()

    monkeypatch.setattr(
        common_crawl_api.urllib.request,
        "build_opener",
        lambda _handler: _Opener(),
    )
    observed_status, data, error = common_crawl_api._http_range_get_cached(
        url=TEST_WARC_URL,
        start=10,
        end_inclusive=14,
        timeout_s=7,
        cache_dir=None,
        cache_max_bytes=0,
        cache_max_item_bytes=0,
    )

    assert observed_status == status
    assert data is None
    assert error_text in str(error)


@pytest.mark.parametrize(
    "url",
    [
        TEST_WARC_URL.replace("https://", "http://", 1),
        TEST_WARC_URL.replace("data.commoncrawl.org", "web.archive.org", 1),
        TEST_WARC_URL.replace("data.commoncrawl.org", "data.commoncrawl.org:443", 1),
        TEST_WARC_URL.replace("/warc/", "/warc/%2E%2E/"),
        TEST_WARC_URL + "?download=1",
    ],
)
def test_range_transport_rejects_noncanonical_warc_object_before_network(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
) -> None:
    monkeypatch.setattr(
        common_crawl_api.urllib.request,
        "build_opener",
        lambda *_args: (_ for _ in ()).throw(AssertionError("network must not run")),
    )
    status, data, error = common_crawl_api._http_range_get_cached(
        url=url,
        start=0,
        end_inclusive=9,
        timeout_s=7,
        cache_dir=None,
        cache_max_bytes=0,
        cache_max_item_bytes=0,
    )

    assert status is None
    assert data is None
    assert "Common Crawl WARC URL" in str(error)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("https://example.gov/code", "http://example.gov/code"),
        ("https://example.gov:443/code/", "http://example.gov:80/code"),
        ("https://example.gov/code/?q=/", "http://example.gov/code?q=/"),
    ],
)
def test_common_crawl_identity_retains_only_documented_equivalences(
    left: str,
    right: str,
) -> None:
    assert _same_archived_resource(left, right)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("https://example.gov/code?q=", "http://example.gov/code?q=/"),
        ("https://example.gov/code?a=1&b=2", "http://example.gov/code?b=2&a=1"),
        ("https://example.gov/code?q=%20", "http://example.gov/code?q=+"),
        ("https://example.gov/code?q=%2F", "http://example.gov/code?q=%2f"),
        ("https://example.gov/code/title%2F1", "http://example.gov/code/title/1"),
        ("https://example.gov/code", "http://example.gov/code#"),
        ("https://example.gov/code", "http://example.gov:8080/code"),
        ("https://example.gov/code", "http://user@example.gov/code"),
        ("https://example.gov/code", "http://example.gov/code//"),
    ],
)
def test_common_crawl_identity_rejects_query_path_authority_aliases(
    left: str,
    right: str,
) -> None:
    assert not _same_archived_resource(left, right)


@pytest.mark.parametrize(
    ("offset", "length"),
    [
        (True, 10),
        (1.0, 10),
        ("01", 10),
        ("+1", 10),
        (" 1", 10),
        (1, False),
        (1, 10.0),
        (1, "010"),
        (1, "1.5"),
    ],
)
def test_common_crawl_pointer_rejects_integer_coercion(
    offset: object,
    length: object,
) -> None:
    assert ArchivalFetchClient._common_crawl_pointer(
        {
            "warc_filename": TEST_SHARED_WARC,
            "warc_offset": offset,
            "warc_length": length,
        }
    ) is None


def test_common_crawl_pointer_accepts_only_canonical_decimal_spellings() -> None:
    assert ArchivalFetchClient._common_crawl_pointer(
        {
            "warc_filename": TEST_SHARED_WARC,
            "warc_offset": "0",
            "warc_length": "10",
        }
    ) == (TEST_SHARED_WARC, 0, 10)
    assert ArchivalFetchClient._common_crawl_pointer(
        {
            "warc_filename": TEST_SHARED_WARC.replace(
                "/warc/",
                "/warc/%2E%2E/",
            ),
            "warc_offset": 0,
            "warc_length": 10,
        }
    ) is None


def test_common_crawl_search_cannot_launder_wayback_or_indexed_page_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    official_url = "https://codes.example.gov/title/1"

    class _Engine:
        def __init__(self, **_kwargs):
            pass

        @staticmethod
        def is_available() -> bool:
            return True

        @staticmethod
        def search_domain(_domain: str, *, max_matches: int):
            del max_matches
            return [
                {
                    "url": official_url,
                    "timestamp": "20260824000000",
                    "archive_url": (
                        "https://web.archive.org/web/20260824000000/"
                        + official_url
                    ),
                    "wayback_url": (
                        "https://web.archive.org/web/20260824000000/"
                        + official_url
                    ),
                }
            ]

    client = ArchivalFetchClient(content_validator=lambda payload: bool(payload))
    monkeypatch.setattr(state_archival_fetch, "CommonCrawlSearchEngine", _Engine)
    monkeypatch.setattr(
        client,
        "_request_with_retries",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("candidate page transport must not run")
        ),
    )

    assert client._fetch_from_common_crawl(official_url) is None


def test_common_crawl_warc_date_and_payload_digest_bind_cdx_metadata() -> None:
    official_url = "https://codes.example.gov/title/1"
    body = b"<html><body>Archived official title.</body></html>"
    digest = _payload_sha1_base32(body)
    member = _warc_member(
        body,
        target_url=official_url,
        timestamp="20260824010203",
        payload_digest=f"sha1:{digest}",
    )

    class _Engine:
        @staticmethod
        def fetch_warc_record(*_args, **_kwargs):
            return member

    client = ArchivalFetchClient(content_validator=lambda payload: payload == body)
    base_record = {
        "url": official_url,
        "timestamp": "20260824010203",
        "digest": digest,
        "warc_filename": TEST_SHARED_WARC,
        "warc_offset": 100,
        "warc_length": len(member),
    }
    verified = client.fetch_common_crawl_record(
        official_url,
        base_record,
        engine=_Engine(),
    )
    assert verified is not None
    assert verified.archive_timestamp == "20260824010203"

    assert client.fetch_common_crawl_record(
        official_url,
        {**base_record, "timestamp": "20260824010204"},
        engine=_Engine(),
    ) is None
    assert client.fetch_common_crawl_record(
        official_url,
        {**base_record, "digest": "B" * 32},
        engine=_Engine(),
    ) is None

    forged_digest = "A" * 32
    forged_member = _warc_member(
        body,
        target_url=official_url,
        timestamp="20260824010203",
        payload_digest=f"sha1:{forged_digest}",
    )
    assert client.fetch_common_crawl_record(
        official_url,
        {
            **base_record,
            "digest": forged_digest,
            "warc_length": len(forged_member),
        },
        engine=type(
            "_ForgedEngine",
            (),
            {"fetch_warc_record": lambda self, *_args, **_kwargs: forged_member},
        )(),
    ) is None
    assert client.fetch_common_crawl_record(
        official_url,
        {key: value for key, value in base_record.items() if key != "digest"},
        engine=_Engine(),
    ) is None

    missing_warc_digest_member = _warc_member(
        body,
        target_url=official_url,
        timestamp="20260824010203",
        payload_digest=None,
    )
    assert client.fetch_common_crawl_record(
        official_url,
        {**base_record, "warc_length": len(missing_warc_digest_member)},
        engine=type(
            "_MissingDigestEngine",
            (),
            {
                "fetch_warc_record": (
                    lambda self, *_args, **_kwargs: missing_warc_digest_member
                )
            },
        )(),
    ) is None


class _StateFrontierScraper(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://codes.example.gov"

    def get_code_list(self):
        return []

    async def scrape_code(self, code_name: str, code_url: str):
        return []


def test_shared_warc_batch_coalesces_nearby_ranges_and_reports_savings(
    monkeypatch,
) -> None:
    remote = bytearray(b"." * 2_000)
    remote[100:110] = b"A" * 10
    remote[300:320] = b"B" * 20
    remote[800:805] = b"C" * 5
    calls: list[tuple[int, int]] = []

    def _range_get(**kwargs):
        start = int(kwargs["start"])
        end = int(kwargs["end_inclusive"])
        calls.append((start, end))
        return 206, bytes(remote[start : end + 1]), None

    monkeypatch.setattr(common_crawl_api, "_http_range_get_cached", _range_get)
    stats: dict[str, object] = {}

    data_by, error_by = common_crawl_api.fetch_warc_record_ranges_sliced(
        warc_filename="crawl-data/CC-MAIN-TEST/example.warc.gz",
        ranges=[(100, 10), (300, 20), (800, 5), (100, 10)],
        prefix="https://example.invalid/",
        max_slice_bytes=500,
        max_gap_bytes=1_000,
        cache_dir=None,
        stats_out=stats,
    )

    assert error_by == {}
    assert data_by == {
        (100, 10): b"A" * 10,
        (300, 20): b"B" * 20,
        (800, 5): b"C" * 5,
    }
    assert calls == [(100, 319), (800, 804)]
    assert stats["requested_ranges"] == 4
    assert stats["unique_ranges"] == 3
    assert stats["duplicate_ranges"] == 1
    assert stats["planned_range_fetches"] == 2
    assert stats["range_fetch_calls"] == 2
    assert stats["effective_range_fetches_avoided"] == 2


def test_shared_warc_batch_keeps_far_ranges_separate(monkeypatch) -> None:
    calls: list[tuple[int, int]] = []

    def _range_get(**kwargs):
        start = int(kwargs["start"])
        end = int(kwargs["end_inclusive"])
        calls.append((start, end))
        return 206, b"X" * (end - start + 1), None

    monkeypatch.setattr(common_crawl_api, "_http_range_get_cached", _range_get)

    data_by, error_by = common_crawl_api.fetch_warc_record_ranges_sliced(
        warc_filename="crawl-data/CC-MAIN-TEST/example.warc.gz",
        ranges=[(10, 5), (100, 5)],
        prefix="https://example.invalid/",
        max_slice_bytes=1_000,
        max_gap_bytes=20,
        cache_dir=None,
    )

    assert error_by == {}
    assert set(data_by) == {(10, 5), (100, 5)}
    assert calls == [(10, 14), (100, 104)]


def test_shared_warc_batch_rejects_short_bundle_and_short_member_retry(
    monkeypatch,
) -> None:
    calls: list[tuple[int, int]] = []

    def _short_range_get(**kwargs):
        start = int(kwargs["start"])
        end = int(kwargs["end_inclusive"])
        calls.append((start, end))
        requested = end - start + 1
        return 206, b"S" * max(0, requested - 1), None

    monkeypatch.setattr(
        common_crawl_api,
        "_http_range_get_cached",
        _short_range_get,
    )
    stats: dict[str, object] = {}

    data_by, error_by = common_crawl_api.fetch_warc_record_ranges_sliced(
        warc_filename="crawl-data/CC-MAIN-TEST/example.warc.gz",
        ranges=[(100, 10), (120, 10)],
        prefix="https://example.invalid/",
        max_slice_bytes=1_000,
        max_gap_bytes=100,
        cache_dir=None,
        stats_out=stats,
    )

    assert data_by == {}
    assert set(error_by) == {(100, 10), (120, 10)}
    assert all("length mismatch" in message for message in error_by.values())
    assert calls == [(100, 129), (100, 109), (120, 129)]
    assert stats["retry_range_fetches"] == 2
    assert stats["records_failed"] == 2


def test_common_crawl_engine_delegates_batching_to_shared_ccindex_api() -> None:
    observed: dict[str, object] = {}

    def _shared_batch(**kwargs):
        observed.update(kwargs)
        kwargs["stats_out"].update(
            {
                "range_fetch_calls": 1,
                "records_succeeded": 2,
                "records_failed": 0,
            }
        )
        return {(10, 5): b"A" * 5, (20, 5): b"B" * 5}, {}

    engine = object.__new__(CommonCrawlSearchEngine)
    engine._available = True
    engine.mode = "local"
    engine.api = SimpleNamespace(fetch_warc_record_ranges_sliced=_shared_batch)
    stats: dict[str, object] = {}

    data_by, error_by = engine.fetch_warc_record_ranges_sliced(
        "one.warc.gz",
        [(10, 5), (20, 5)],
        max_gap_bytes=12,
        max_slice_bytes=128,
        stats_out=stats,
    )

    assert error_by == {}
    assert data_by[(10, 5)] == b"A" * 5
    assert observed["warc_filename"] == "one.warc.gz"
    assert observed["ranges"] == [(10, 5), (20, 5)]
    assert observed["max_gap_bytes"] == 12
    assert observed["max_slice_bytes"] == 128
    assert stats["range_fetch_calls"] == 1


def test_common_crawl_engine_compat_batch_reports_exact_duplicate_savings() -> None:
    calls: list[tuple[str, int, int]] = []

    engine = object.__new__(CommonCrawlSearchEngine)
    engine._available = True
    engine.mode = "remote"

    def _fetch_one(
        warc_filename: str,
        offset: int,
        length: int,
        **_kwargs,
    ) -> bytes:
        calls.append((warc_filename, offset, length))
        return b"X" * length

    engine.fetch_warc_record = _fetch_one
    stats: dict[str, object] = {}

    data_by, error_by = engine.fetch_warc_record_ranges_sliced(
        "shared.warc.gz",
        [(10, 5), (10, 5)],
        stats_out=stats,
    )

    assert error_by == {}
    assert data_by == {(10, 5): b"X" * 5}
    assert calls == [("shared.warc.gz", 10, 5)]
    assert stats["requested_ranges"] == 2
    assert stats["unique_ranges"] == 1
    assert stats["duplicate_ranges"] == 1
    assert stats["naive_range_fetches"] == 2
    assert stats["range_fetch_calls"] == 1
    assert stats["planned_range_fetches_avoided"] == 1
    assert stats["effective_range_fetches_avoided"] == 1


def test_state_archive_batch_groups_by_warc_and_preserves_per_page_provenance() -> None:
    urls = [
        "https://codes.example.gov/title/1",
        "https://codes.example.gov/title/2",
        "https://other.example.gov/title/3",
    ]
    bodies = [
        b"<html><body>State law title one.</body></html>",
        b"<html><body>State law title two.</body></html>",
        b"<html><body>State law title three.</body></html>",
    ]
    members = [
        _warc_member(
            body,
            target_url=url,
            timestamp=f"2026082400000{index}",
        )
        for index, (body, url) in enumerate(zip(bodies, urls))
    ]
    filenames = [TEST_SHARED_WARC, TEST_SHARED_WARC, TEST_OTHER_WARC]
    offsets = [100, 500, 50]
    records = [
        {
            "url": url,
            "timestamp": f"2026082400000{index}",
            "digest": _payload_sha1_base32(body),
            "collection": TEST_CC_COLLECTION,
            "warc_filename": filename,
            "warc_offset": offset,
            "warc_length": len(member),
        }
        for index, (url, body, filename, offset, member) in enumerate(
            zip(urls, bodies, filenames, offsets, members)
        )
    ]
    payload_by_pointer = {
        (filename, offset, len(member)): member
        for filename, offset, member in zip(filenames, offsets, members)
    }

    class _Engine:
        def __init__(self) -> None:
            self.calls: list[tuple[str, list[tuple[int, int]]]] = []

        def fetch_warc_record_ranges_sliced(
            self,
            warc_filename,
            ranges,
            **kwargs,
        ):
            self.calls.append((warc_filename, list(ranges)))
            unique = sorted(set(ranges))
            kwargs["stats_out"].update(
                {
                    "range_fetch_calls": 1,
                    "naive_range_fetches": len(unique),
                    "planned_range_fetches": 1,
                    "retry_range_fetches": 0,
                    "coalesced_gap_bytes": 0,
                    "requested_member_bytes": sum(length for _offset, length in unique),
                }
            )
            return {
                (offset, length): payload_by_pointer[
                    (warc_filename, offset, length)
                ]
                for offset, length in unique
            }, {}

    engine = _Engine()
    client = ArchivalFetchClient(content_validator=lambda payload: bool(payload))
    emitted: list[tuple[str, bytes]] = []

    batch = client.fetch_common_crawl_records(
        list(zip(urls, records)),
        engine=engine,
        result_callback=lambda url, result: emitted.append((url, result.content)),
        max_gap_bytes=1_000,
        max_slice_bytes=10_000,
    )

    assert [call[0] for call in engine.calls] == [TEST_OTHER_WARC, TEST_SHARED_WARC]
    assert len(engine.calls) == 2
    assert emitted == [
        (urls[2], bodies[2]),
        (urls[0], bodies[0]),
        (urls[1], bodies[1]),
    ]
    assert [result.content for result in batch.results if result is not None] == bodies
    assert [
        result.common_crawl_warc_offset
        for result in batch.results
        if result is not None
    ] == offsets
    assert [
        result.archive_timestamp for result in batch.results if result is not None
    ] == [record["timestamp"] for record in records]
    assert batch.stats["warc_objects"] == 2
    assert batch.stats["requested_ranges"] == 3
    assert batch.stats["unique_ranges"] == 3
    assert batch.stats["duplicate_ranges"] == 0
    assert batch.stats["range_fetch_calls"] == 2
    assert batch.stats["naive_range_fetches"] == 3
    assert batch.stats["range_fetches_avoided"] == 1


def test_state_archive_batch_rejects_non_200_archived_response() -> None:
    url = "https://codes.example.gov/title/1"
    body = b"<html><body>Archived not-found page.</body></html>"
    member = _warc_member(
        body,
        target_url=url,
        response_status=404,
    )
    record = {
        "url": url,
        "timestamp": "20260824000000",
        "digest": _payload_sha1_base32(body),
        "warc_filename": TEST_SHARED_WARC,
        "warc_offset": 100,
        "warc_length": len(member),
    }

    class _Engine:
        def fetch_warc_record_ranges_sliced(self, _filename, ranges, **kwargs):
            kwargs["stats_out"].update(
                {
                    "range_fetch_calls": 1,
                    "naive_range_fetches": 1,
                }
            )
            return {ranges[0]: member}, {}

    batch = ArchivalFetchClient(
        content_validator=lambda payload: bool(payload)
    ).fetch_common_crawl_records(
        [(url, record)],
        engine=_Engine(),
    )

    assert batch.results == [None]
    assert batch.stats["successful_pages"] == 0
    assert batch.stats["failed_pages"] == 1


@pytest.mark.anyio
async def test_multifetch_batches_warc_frontier_then_falls_back_only_for_misses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls = [
        "https://codes.example.gov/title/1",
        "https://codes.example.gov/title/2",
        "https://codes.example.gov/title/3",
        "https://codes.example.gov/title/1",
    ]
    records = [
        (
            urls[index],
            {
                "timestamp": f"2026082400000{index}",
                "url": urls[index],
                "warc_filename": TEST_SHARED_WARC,
                "warc_offset": 100 + index * 500,
                "warc_length": 250,
            },
        )
        for index in range(2)
    ]
    client = ArchivalFetchClient(
        content_validator=lambda payload: bool(payload),
        enable_common_crawl=True,
    )
    observed_batches = []

    def _batch(requests, *, engine, **_kwargs):
        observed_batches.append((list(requests), engine))
        return CommonCrawlBatchFetchResult(
            results=[
                FetchResult(
                    url=url,
                    content=f"archived-{index}".encode(),
                    source="common_crawl",
                    fetched_at="2026-08-24T00:00:00+00:00",
                )
                for index, (url, _record) in enumerate(requests)
            ],
            stats={
                "range_fetch_calls": 1,
                "naive_range_fetches": 2,
                "range_fetches_avoided": 1,
                "successful_pages": 2,
                "warc_objects": 1,
            },
        )

    fallback_urls = []

    async def _fallback(url, **kwargs):
        fallback_urls.append((url, kwargs))
        return FetchResult(
            url=url,
            content=b"direct-fallback",
            source="direct",
            fetched_at="2026-08-24T00:00:01+00:00",
        )

    monkeypatch.setattr(client, "fetch_common_crawl_records", _batch)
    monkeypatch.setattr(client, "fetch_with_fallback", _fallback)
    engine = SimpleNamespace()

    result = await client.fetch_many_with_fallback(
        urls,
        common_crawl_records=records,
        common_crawl_engine=engine,
        max_concurrency=2,
    )

    assert observed_batches == [(records, engine)]
    assert [url for url, _kwargs in fallback_urls] == [urls[2]]
    assert fallback_urls[0][1]["enable_common_crawl"] is False
    assert [item.content for item in result.results if item is not None] == [
        b"archived-0",
        b"archived-1",
        b"direct-fallback",
        b"archived-0",
    ]
    assert result.errors == [None, None, None, None]
    assert result.stats["duplicate_page_requests_avoided"] == 1
    assert result.stats["fallback_requests"] == 1
    assert result.stats["common_crawl"]["range_fetches_avoided"] == 1


@pytest.mark.anyio
async def test_multifetch_direct_first_batches_only_live_misses_without_retrying_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls = [
        "https://codes.example.gov/title/1",
        "https://codes.example.gov/title/2",
        "https://codes.example.gov/title/3",
        "https://codes.example.gov/title/4",
    ]
    records = [
        (
            url,
            {
                "timestamp": f"2026082400000{index}",
                "url": url,
                "warc_filename": TEST_SHARED_WARC,
                "warc_offset": 100 + index * 500,
                "warc_length": 250,
            },
        )
        for index, url in enumerate(urls[:3])
    ]
    client = ArchivalFetchClient(
        content_validator=lambda payload: bool(payload),
        enable_common_crawl=True,
    )
    direct_calls: list[str] = []

    def _direct(url: str):
        direct_calls.append(url)
        if url != urls[0]:
            return None
        return FetchResult(
            url=url,
            content=b"current-official",
            source="direct",
            fetched_at="2026-08-24T00:00:00+00:00",
        )

    observed_batches = []

    def _batch(requests, *, engine, **_kwargs):
        observed_batches.append((list(requests), engine))
        return CommonCrawlBatchFetchResult(
            results=[
                FetchResult(
                    url=url,
                    content=f"archived-{index}".encode(),
                    source="common_crawl",
                    fetched_at="2026-08-24T00:00:01+00:00",
                )
                for index, (url, _record) in enumerate(requests, start=1)
            ],
            stats={
                "range_fetch_calls": 1,
                "naive_range_fetches": 2,
                "range_fetches_avoided": 1,
                "successful_pages": 2,
                "warc_objects": 1,
            },
        )

    final_fallbacks = []
    loader_frontiers = []

    async def _record_loader(missing):
        loader_frontiers.append(list(missing))
        return records

    async def _fallback(url, **kwargs):
        final_fallbacks.append((url, kwargs))
        return FetchResult(
            url=url,
            content=b"wayback-final-fallback",
            source="wayback",
            fetched_at="2026-08-24T00:00:02+00:00",
        )

    monkeypatch.setattr(client, "_fetch_direct", _direct)
    monkeypatch.setattr(client, "fetch_common_crawl_records", _batch)
    monkeypatch.setattr(client, "fetch_with_fallback", _fallback)
    engine = SimpleNamespace()

    result = await client.fetch_many_with_fallback(
        urls,
        common_crawl_record_loader=_record_loader,
        common_crawl_engine=engine,
        max_concurrency=4,
        prefer_direct=True,
    )

    assert sorted(direct_calls) == sorted(urls)
    assert loader_frontiers == [urls[1:]]
    assert observed_batches == [(records[1:], engine)]
    assert final_fallbacks == [
        (
            urls[3],
            {
                "enable_common_crawl": False,
                "enable_direct": False,
                "enable_archive_is": None,
            },
        )
    ]
    assert [item.content for item in result.results if item is not None] == [
        b"current-official",
        b"archived-1",
        b"archived-2",
        b"wayback-final-fallback",
    ]
    assert result.stats["direct_initial_requests"] == 4
    assert result.stats["direct_initial_successes"] == 1
    assert result.stats["common_crawl_selected_pages"] == 2
    assert result.stats["common_crawl"]["range_fetches_avoided"] == 1


@pytest.mark.anyio
async def test_multifetch_direct_first_forwards_one_exact_header_set_per_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls = [
        "https://codes.example.gov/title/1",
        "https://codes.example.gov/title/2",
    ]
    headers = {
        "User-Agent": "state-specific-crawler/2.0",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    }
    calls: list[tuple[str, dict[str, str]]] = []
    client = ArchivalFetchClient(
        content_validator=lambda payload: bool(payload),
        enable_common_crawl=True,
    )

    def _direct(url: str, *, headers: dict[str, str] | None = None):
        calls.append((url, dict(headers or {})))
        return FetchResult(
            url=url,
            content=f"current:{url}".encode(),
            source="direct",
            fetched_at="2026-08-25T07:25:00Z",
        )

    monkeypatch.setattr(client, "_fetch_direct", _direct)
    result = await client.fetch_many_with_fallback(
        urls,
        max_concurrency=2,
        prefer_direct=True,
        request_headers=headers,
    )

    assert sorted(calls) == sorted((url, headers) for url in urls)
    assert [item.content for item in result.results if item is not None] == [
        f"current:{url}".encode() for url in urls
    ]


@pytest.mark.anyio
async def test_multifetch_rejects_misdemultiplexed_warc_target_then_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls = [
        "https://codes.example.gov/title/1",
        "https://codes.example.gov/title/2",
    ]
    bodies = [b"first archived law", b"wrong archived law"]
    members = [
        _warc_member(
            bodies[0],
            target_url=urls[0],
            timestamp="20260824000000",
        ),
        _warc_member(
            bodies[1],
            target_url="https://codes.example.gov/title/not-two",
            timestamp="20260824000001",
        ),
    ]
    records = [
        (
            url,
            {
                "timestamp": f"2026082400000{index}",
                "digest": _payload_sha1_base32(bodies[index]),
                "url": url,
                "warc_filename": TEST_SHARED_WARC,
                "warc_offset": 100 + index * 1_000,
                "warc_length": len(member),
            },
        )
        for index, (url, member) in enumerate(zip(urls, members))
    ]

    class _Engine:
        def fetch_warc_record_ranges_sliced(self, warc_filename, ranges, **kwargs):
            assert warc_filename == TEST_SHARED_WARC
            kwargs["stats_out"].update(
                {
                    "naive_range_fetches": 2,
                    "range_fetch_calls": 1,
                }
            )
            return {
                pointer: member for pointer, member in zip(ranges, members)
            }, {}

    client = ArchivalFetchClient(
        content_validator=lambda payload: bool(payload),
        enable_common_crawl=True,
    )
    fallback_urls: list[str] = []

    async def _fallback(url, **_kwargs):
        fallback_urls.append(url)
        return FetchResult(
            url=url,
            content=b"verified direct fallback",
            source="direct",
            fetched_at="2026-08-24T00:00:01+00:00",
        )

    monkeypatch.setattr(client, "fetch_with_fallback", _fallback)
    result = await client.fetch_many_with_fallback(
        urls,
        common_crawl_records=records,
        common_crawl_engine=_Engine(),
    )

    assert fallback_urls == [urls[1]]
    assert result.results[0] is not None
    assert result.results[0].content == b"first archived law"
    assert result.results[1] is not None
    assert result.results[1].content == b"verified direct fallback"
    assert result.stats["fallback_requests"] == 1
    assert result.stats["common_crawl"]["range_fetch_calls"] == 1


def test_nonbatch_engine_reports_each_duplicate_pointer_call_truthfully() -> None:
    url = "https://codes.example.gov/title/1"
    body = b"one archived law"
    member = _warc_member(body, target_url=url)
    record = {
        "timestamp": "20260824000000",
        "digest": _payload_sha1_base32(body),
        "url": url,
        "warc_filename": TEST_SHARED_WARC,
        "warc_offset": 100,
        "warc_length": len(member),
    }

    class _Engine:
        def __init__(self) -> None:
            self.calls = 0

        def fetch_warc_record(self, *_args, **_kwargs):
            self.calls += 1
            return member

    engine = _Engine()
    client = ArchivalFetchClient(content_validator=lambda payload: bool(payload))
    batch = client.fetch_common_crawl_records(
        [(url, record), (url, record)],
        engine=engine,
    )

    assert engine.calls == 2
    assert all(result is not None for result in batch.results)
    assert batch.stats["requested_ranges"] == 2
    assert batch.stats["unique_ranges"] == 1
    assert batch.stats["duplicate_ranges"] == 1
    assert batch.stats["range_fetch_calls"] == 2
    assert batch.stats["range_fetches_avoided"] == 0


@pytest.mark.asyncio
async def test_base_frontier_queries_inventory_once_and_coalesces_same_warc(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    urls = [
        "https://codes.example.gov/title/1",
        "https://codes.example.gov/title/2",
    ]
    bodies = [
        b"<html><body>Official state law title one.</body></html>",
        b"<html><body>Official state law title two.</body></html>",
    ]
    members = [
        _warc_member(
            body,
            target_url=url,
            timestamp=f"2026082400000{index}",
        )
        for index, (body, url) in enumerate(zip(bodies, urls))
    ]
    offsets = [100, 100 + len(members[0]) + 32]
    remote = bytearray(b"." * (offsets[1] + len(members[1]) + 100))
    for offset, member in zip(offsets, members):
        remote[offset : offset + len(member)] = member
    records = [
        {
            "collection": "CC-MAIN-2026-30",
            "domain": "codes.example.gov",
            "mime": "text/html",
            "timestamp": f"2026082400000{index}",
            "digest": _payload_sha1_base32(body),
            "url": url,
            "warc_filename": "crawl-data/CC-MAIN-2026-30/shared.warc.gz",
            "warc_length": len(member),
            "warc_offset": offset,
        }
        for index, (url, body, offset, member) in enumerate(
            zip(urls, bodies, offsets, members)
        )
    ]
    inventory_queries: list[dict[str, object]] = []
    range_calls: list[tuple[int, int]] = []

    async def _inventory(**kwargs):
        inventory_queries.append(dict(kwargs))
        return records

    def _range_get(**kwargs):
        start = int(kwargs["start"])
        end = int(kwargs["end_inclusive"])
        range_calls.append((start, end))
        return 206, bytes(remote[start : end + 1]), None

    class _Engine:
        def __init__(self, **_kwargs):
            pass

        def fetch_warc_record_ranges_sliced(
            self,
            warc_filename,
            ranges,
            **kwargs,
        ):
            return common_crawl_api.fetch_warc_record_ranges_sliced(
                warc_filename=warc_filename,
                ranges=list(ranges),
                prefix="https://data.commoncrawl.org/",
                timeout_s=float(kwargs.get("timeout_s") or 30.0),
                max_slice_bytes=int(kwargs.get("max_slice_bytes") or 25_000_000),
                max_gap_bytes=int(kwargs.get("max_gap_bytes") or 256_000),
                min_slice_bytes=int(kwargs.get("min_slice_bytes") or 0),
                max_workers=int(kwargs.get("max_workers") or 1),
                cache_dir=None,
                stats_out=kwargs.get("stats_out"),
            )

    async def _no_cache(**_kwargs):
        return None

    monkeypatch.setattr(common_crawl_api, "_http_range_get_cached", _range_get)
    monkeypatch.setattr(state_archival_fetch, "CommonCrawlSearchEngine", _Engine)

    scraper = _StateFrontierScraper("WI", "Wisconsin")
    monkeypatch.setattr(scraper, "_search_state_common_crawl_records", _inventory)
    monkeypatch.setattr(scraper, "_cache_successful_page_fetch", _no_cache)
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name=type(scraper).__name__,
    )
    scraper.attach_state_law_acquisition_ledger(ledger)

    result = await scraper._fetch_page_contents_with_archival_fallback(urls)

    assert len(inventory_queries) == 1
    assert inventory_queries[0]["domain_terms"] == ["codes.example.gov"]
    assert inventory_queries[0]["url_terms"] == ["/title/1", "/title/2"]
    assert result.urls == urls
    assert result.payloads == bodies
    assert result.errors == [None, None]
    assert [receipt["official_url"] for receipt in result.transport_receipts] == urls
    assert all(result.parser_input_envelopes)
    assert len(ledger.entries) == 2
    assert range_calls == [(offsets[0], offsets[1] + len(members[1]) - 1)]
    assert result.stats["common_crawl_inventory_queries"] == 1
    assert result.stats["common_crawl"]["warc_objects"] == 1
    assert result.stats["common_crawl"]["requested_ranges"] == 2
    assert result.stats["common_crawl"]["unique_ranges"] == 2
    assert result.stats["common_crawl"]["duplicate_ranges"] == 0
    assert result.stats["common_crawl"]["planned_range_fetches_avoided"] == 1
    assert result.stats["common_crawl"]["range_fetch_calls"] == 1
    assert result.stats["common_crawl"]["range_fetches_avoided"] == 1


@pytest.mark.asyncio
async def test_large_same_domain_frontier_compacts_inventory_terms_then_exact_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls = [
        f"https://codes.example.gov/legislation/code/title-{index}/section-{index}-1"
        for index in range(1, 66)
    ]
    inventory_queries: list[dict[str, object]] = []

    async def _inventory(**kwargs):
        inventory_queries.append(dict(kwargs))
        return []

    async def _many(self, requested_urls, **kwargs):
        loader = kwargs["common_crawl_record_loader"]
        assert callable(loader)
        await loader(tuple(requested_urls))
        results = [
            FetchResult(
                url=url,
                content=f"<html><body>Law at {url}</body></html>".encode(),
                source="direct",
                fetched_at="2026-08-25T00:00:00+00:00",
                status_code=200,
            )
            for url in requested_urls
        ]
        return SimpleNamespace(
            results=results,
            errors=[None] * len(results),
            stats={"requested_pages": len(results), "common_crawl": {}},
        )

    async def _no_cache(**_kwargs):
        return None

    scraper = _StateFrontierScraper("WI", "Wisconsin")
    monkeypatch.setattr(scraper, "_search_state_common_crawl_records", _inventory)
    monkeypatch.setattr(scraper, "_cache_successful_page_fetch", _no_cache)
    monkeypatch.setattr(ArchivalFetchClient, "fetch_many_with_fallback", _many)

    result = await scraper._fetch_page_contents_with_archival_fallback(
        urls,
        prefer_direct=True,
    )

    assert result.urls == urls
    assert len(inventory_queries) == 1
    assert inventory_queries[0]["domain_terms"] == ["codes.example.gov"]
    assert inventory_queries[0]["url_terms"] == ["/legislation/code/"]


@pytest.mark.asyncio
async def test_generic_discovery_submits_same_depth_pages_as_one_frontier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    landing_url = "https://codes.example.gov/code"
    landing = (
        b"<html><body>"
        b"<a href='/title/1'>Title 1 General Provisions</a>"
        b"<a href='/title/2'>Title 2 Public Officers</a>"
        b"</body></html>"
    )
    child_bodies = [
        b"<html><body><a href='/section/1-1'>Section 1-1 Definitions</a></body></html>",
        b"<html><body><a href='/section/2-1'>Section 2-1 Duties</a></body></html>",
    ]
    observed_frontiers: list[list[str]] = []

    async def _single(url: str, **_kwargs):
        assert url == landing_url
        return landing

    async def _frontier(urls, **_kwargs):
        requested = list(urls)
        observed_frontiers.append(requested)
        return StateLawPageMultiFetchResult(
            urls=requested,
            payloads=list(child_bodies),
            errors=[None, None],
            transport_receipts=[None, None],
            parser_input_envelopes=[None, None],
            stats={"requested_pages": 2},
        )

    scraper = _StateFrontierScraper("WI", "Wisconsin")
    monkeypatch.setattr(
        scraper,
        "_fetch_page_content_with_archival_fallback",
        _single,
    )
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _frontier,
    )

    rows = await scraper._generic_scrape(
        "Wisconsin Code",
        landing_url,
        "Wis. Stat.",
        max_sections=20,
    )

    assert observed_frontiers == [
        [
            "https://codes.example.gov/title/1",
            "https://codes.example.gov/title/2",
        ]
    ]
    assert {row.section_number for row in rows} >= {"1-1", "2-1"}


@pytest.mark.anyio
async def test_page_multifetch_replays_retained_inputs_and_networks_only_misses(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls = [
        "https://codes.example.gov/title/1",
        "https://codes.example.gov/title/2",
    ]
    retained_body = b"retained official title one"
    network_body = b"current official title two"
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="_StateFrontierScraper",
    )
    ledger.retain_parser_input(
        official_url=urls[0],
        body=retained_body,
        transport_receipt={
            "content_sha256": hashlib.sha256(retained_body).hexdigest(),
            "official_url": urls[0],
            "source_transport": "direct",
        },
        retrieved_at="2026-08-24T00:00:00Z",
    )
    inventory_queries = []

    async def _inventory(**kwargs):
        inventory_queries.append(dict(kwargs))
        return []

    network_frontiers = []

    async def _many(_self, requested, **kwargs):
        requested = list(requested)
        network_frontiers.append(requested)
        await kwargs["common_crawl_record_loader"](requested)
        return SimpleNamespace(
            results=[
                FetchResult(
                    url=urls[1],
                    content=network_body,
                    source="direct",
                    fetched_at="2026-08-24T00:00:01Z",
                )
            ],
            errors=[None],
            stats={
                "requested_pages": 1,
                "unique_pages": 1,
                "common_crawl": {},
            },
        )

    async def _no_cache(**_kwargs):
        return None

    scraper = _StateFrontierScraper("WI", "Wisconsin")
    scraper.attach_state_law_acquisition_ledger(ledger)
    monkeypatch.setattr(scraper, "_search_state_common_crawl_records", _inventory)
    monkeypatch.setattr(scraper, "_cache_successful_page_fetch", _no_cache)
    monkeypatch.setattr(ArchivalFetchClient, "fetch_many_with_fallback", _many)

    result = await scraper._fetch_page_contents_with_archival_fallback(
        urls,
        prefer_direct=True,
    )

    assert network_frontiers == [[urls[1]]]
    assert len(inventory_queries) == 1
    assert inventory_queries[0]["url_terms"] == ["/title/2"]
    assert result.urls == urls
    assert result.payloads == [retained_body, network_body]
    assert result.errors == [None, None]
    assert result.stats["network_requested_pages"] == 1
    assert result.stats["retained_replay_pages"] == 1
    assert result.stats["retained_replay_unique_pages"] == 1
    assert len(ledger.entries) == 2


@pytest.mark.anyio
async def test_page_multifetch_forwards_headers_and_retains_sanitized_exact_identity(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://codes.example.gov/title/1"
    body = b"current official title one"
    headers = {
        "User-Agent": "state-specific-crawler/2.0",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    }
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="_StateFrontierScraper",
    )
    observed_headers: list[dict[str, str]] = []

    async def _many(_self, requested, **kwargs):
        assert list(requested) == [url]
        observed_headers.append(dict(kwargs["request_headers"]))
        fetched = FetchResult(
            url=url,
            content=body,
            source="direct",
            fetched_at="2026-08-25T07:25:00Z",
        )
        callback = kwargs["result_callback"]
        assert callback is not None
        callback(url, fetched)
        return SimpleNamespace(
            results=[fetched],
            errors=[None],
            stats={"requested_pages": 1, "common_crawl": {}},
        )

    async def _no_cache(**_kwargs):
        return None

    scraper = _StateFrontierScraper("WI", "Wisconsin")
    scraper.attach_state_law_acquisition_ledger(ledger)
    monkeypatch.setattr(ArchivalFetchClient, "fetch_many_with_fallback", _many)
    monkeypatch.setattr(scraper, "_cache_successful_page_fetch", _no_cache)

    result = await scraper._fetch_page_contents_with_archival_fallback(
        [url],
        headers=headers,
        prefer_direct=True,
    )

    expected_request = {
        "headers": {"Accept": headers["Accept"]},
        "method": "GET",
        "url": url,
    }
    assert observed_headers == [headers]
    assert result.payloads == [body]
    assert ledger.replay_retained_parser_input(
        official_url=url,
        sanitized_request=expected_request,
    ) is not None
    assert ledger.replay_retained_parser_input(
        official_url=url,
        sanitized_request={"method": "GET", "url": url},
    ) is None


@pytest.mark.anyio
async def test_page_multifetch_retains_each_warc_result_before_batch_interruption(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls = [
        "https://codes.example.gov/title/1",
        "https://codes.example.gov/title/2",
    ]
    bodies = [b"archived official title one", b"archived official title two"]
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="_StateFrontierScraper",
    )

    def _result(index: int) -> FetchResult:
        body = bodies[index]
        return FetchResult(
            url=urls[index],
            content=body,
            source="common_crawl",
            fetched_at=f"2026-08-24T00:00:0{index}Z",
            status_code=200,
            archive_url="https://data.commoncrawl.org/crawl-data/test/shared.warc.gz",
            archive_timestamp=f"2026082400000{index}",
            common_crawl_indexed_url=urls[index],
            common_crawl_warc_filename="crawl-data/test/shared.warc.gz",
            common_crawl_warc_offset=100 + index * 100,
            common_crawl_warc_length=50,
            common_crawl_collection="test",
            content_sha256=hashlib.sha256(body).hexdigest(),
        )

    first_network_frontiers: list[list[str]] = []

    async def _interrupted(_self, requested, **kwargs):
        requested = list(requested)
        first_network_frontiers.append(requested)
        callback = kwargs["result_callback"]
        assert callback is not None
        callback(urls[0], _result(0))
        raise RuntimeError("simulated interruption after first WARC result")

    async def _no_cache(**_kwargs):
        return None

    monkeypatch.setenv(
        "LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR",
        str(tmp_path / "page-cache"),
    )
    scraper = _StateFrontierScraper("WI", "Wisconsin")
    scraper.attach_state_law_acquisition_ledger(ledger)
    monkeypatch.setattr(scraper, "_cache_successful_page_fetch", _no_cache)
    monkeypatch.setattr(ArchivalFetchClient, "fetch_many_with_fallback", _interrupted)

    with pytest.raises(RuntimeError, match="simulated interruption"):
        await scraper._fetch_page_contents_with_archival_fallback(
            urls,
            prefer_direct=True,
        )

    assert first_network_frontiers == [urls]
    assert len(ledger.entries) == 1
    assert ledger.replay_retained_parser_input(
        official_url=urls[0],
        sanitized_request={"method": "GET", "url": urls[0]},
    ) is not None

    resumed_network_frontiers: list[list[str]] = []

    async def _resumed(_self, requested, **kwargs):
        requested = list(requested)
        resumed_network_frontiers.append(requested)
        assert requested == [urls[1]]
        callback = kwargs["result_callback"]
        assert callback is not None
        second = _result(1)
        callback(urls[1], second)
        return SimpleNamespace(
            results=[second],
            errors=[None],
            stats={"requested_pages": 1, "common_crawl": {}},
        )

    monkeypatch.setattr(ArchivalFetchClient, "fetch_many_with_fallback", _resumed)
    resumed = await scraper._fetch_page_contents_with_archival_fallback(
        urls,
        prefer_direct=True,
    )

    assert resumed_network_frontiers == [[urls[1]]]
    assert resumed.payloads == bodies
    assert resumed.errors == [None, None]
    assert resumed.stats["retained_replay_pages"] == 1
    assert resumed.stats["eager_parser_inputs_admitted"] == 1
    assert len(ledger.entries) == 2


@pytest.mark.anyio
async def test_page_multifetch_overlap_replays_other_live_attempt_without_duplicate_request(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://codes.example.gov/title/1"
    body = b"current official title one"
    evidence_root = tmp_path / "evidence"
    # Both attempts exist before either has retained the response.  This is
    # the stale in-memory view created by a timed-out worker plus its retry.
    first_ledger = StateLawMultiFetchAcquisitionLedger(
        evidence_root,
        jurisdiction="WI",
        parser_name="_StateFrontierScraper",
    )
    second_ledger = StateLawMultiFetchAcquisitionLedger(
        evidence_root,
        jurisdiction="WI",
        parser_name="_StateFrontierScraper",
    )
    first_scraper = _StateFrontierScraper("WI", "Wisconsin")
    second_scraper = _StateFrontierScraper("WI", "Wisconsin")
    first_scraper.attach_state_law_acquisition_ledger(first_ledger)
    second_scraper.attach_state_law_acquisition_ledger(second_ledger)

    first_network_entered = anyio.Event()
    release_first_network = anyio.Event()
    network_frontiers: list[list[str]] = []

    async def _many(_self, requested, **kwargs):
        requested = list(requested)
        network_frontiers.append(requested)
        if len(network_frontiers) != 1:
            raise AssertionError("overlapping retry duplicated the retained request")
        fetched = FetchResult(
            url=url,
            content=body,
            source="direct",
            fetched_at="2026-08-25T01:30:51Z",
        )
        callback = kwargs["result_callback"]
        assert callback is not None
        callback(url, fetched)
        first_network_entered.set()
        await release_first_network.wait()
        return SimpleNamespace(
            results=[fetched],
            errors=[None],
            stats={"requested_pages": 1, "common_crawl": {}},
        )

    async def _no_cache(**_kwargs):
        return None

    monkeypatch.setattr(
        ArchivalFetchClient,
        "fetch_many_with_fallback",
        _many,
    )
    monkeypatch.setattr(
        first_scraper,
        "_cache_successful_page_fetch",
        _no_cache,
    )
    monkeypatch.setattr(
        second_scraper,
        "_cache_successful_page_fetch",
        _no_cache,
    )
    observed = {}

    async def _run(name, scraper):
        observed[name] = await scraper._fetch_page_contents_with_archival_fallback(
            [url],
            prefer_direct=True,
        )

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(_run, "first", first_scraper)
        await first_network_entered.wait()
        task_group.start_soon(_run, "second", second_scraper)
        await anyio.sleep(0.05)
        assert network_frontiers == [[url]]
        release_first_network.set()

    assert observed["first"].payloads == [body]
    assert observed["second"].payloads == [body]
    assert observed["second"].stats["network_requested_pages"] == 0
    assert observed["second"].stats["retained_replay_pages"] == 1
    assert len(first_ledger.entries) == 1
    assert len(second_ledger.entries) == 1


@pytest.mark.anyio
async def test_page_multifetch_archive_first_overlap_runs_one_inventory_and_network_path(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://codes.example.gov/title/1"
    body = b"archived official title one"
    evidence_root = tmp_path / "evidence"
    first_ledger = StateLawMultiFetchAcquisitionLedger(
        evidence_root,
        jurisdiction="WI",
        parser_name="_StateFrontierScraper",
    )
    second_ledger = StateLawMultiFetchAcquisitionLedger(
        evidence_root,
        jurisdiction="WI",
        parser_name="_StateFrontierScraper",
    )
    first_scraper = _StateFrontierScraper("WI", "Wisconsin")
    second_scraper = _StateFrontierScraper("WI", "Wisconsin")
    first_scraper.attach_state_law_acquisition_ledger(first_ledger)
    second_scraper.attach_state_law_acquisition_ledger(second_ledger)

    inventory_queries: list[dict[str, object]] = []
    network_frontiers: list[list[str]] = []
    first_network_entered = anyio.Event()
    release_first_network = anyio.Event()

    async def _inventory(**kwargs):
        inventory_queries.append(dict(kwargs))
        return []

    async def _many(_self, requested, **kwargs):
        requested = list(requested)
        network_frontiers.append(requested)
        if len(network_frontiers) != 1:
            raise AssertionError("archive-first retry duplicated the network path")
        assert kwargs["common_crawl_records"] == []
        assert kwargs["common_crawl_record_loader"] is None
        fetched = FetchResult(
            url=url,
            content=body,
            source="direct",
            fetched_at="2026-08-25T02:10:00Z",
        )
        callback = kwargs["result_callback"]
        assert callback is not None
        callback(url, fetched)
        first_network_entered.set()
        await release_first_network.wait()
        return SimpleNamespace(
            results=[fetched],
            errors=[None],
            stats={"requested_pages": 1, "common_crawl": {}},
        )

    async def _no_cache(**_kwargs):
        return None

    for scraper in (first_scraper, second_scraper):
        monkeypatch.setattr(
            scraper,
            "_search_state_common_crawl_records",
            _inventory,
        )
        monkeypatch.setattr(
            scraper,
            "_cache_successful_page_fetch",
            _no_cache,
        )
    monkeypatch.setattr(
        ArchivalFetchClient,
        "fetch_many_with_fallback",
        _many,
    )
    observed = {}

    async def _run(name, scraper):
        observed[name] = await scraper._fetch_page_contents_with_archival_fallback(
            [url]
        )

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(_run, "first", first_scraper)
        await first_network_entered.wait()
        task_group.start_soon(_run, "second", second_scraper)
        await anyio.sleep(0.05)
        assert len(inventory_queries) == 1
        assert network_frontiers == [[url]]
        release_first_network.set()

    assert observed["first"].payloads == [body]
    assert observed["second"].payloads == [body]
    assert observed["second"].stats["network_requested_pages"] == 0
    assert len(inventory_queries) == 1
    assert inventory_queries[0]["domain_terms"] == ["codes.example.gov"]


@pytest.mark.anyio
async def test_page_multifetch_reservations_release_after_error_and_do_not_block_other_urls(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_url = "https://codes.example.gov/title/1"
    other_url = "https://codes.example.gov/title/2"
    first_body = b"current official title one"
    other_body = b"current official title two"
    evidence_root = tmp_path / "evidence"
    scrapers = []
    for _index in range(3):
        ledger = StateLawMultiFetchAcquisitionLedger(
            evidence_root,
            jurisdiction="WI",
            parser_name="_StateFrontierScraper",
        )
        scraper = _StateFrontierScraper("WI", "Wisconsin")
        scraper.attach_state_law_acquisition_ledger(ledger)
        scrapers.append(scraper)

    first_entered = anyio.Event()
    other_entered = anyio.Event()
    release_failure = anyio.Event()
    first_failed = anyio.Event()
    retry_finished = anyio.Event()
    first_url_calls = 0
    network_frontiers: list[list[str]] = []

    async def _many(_self, requested, **kwargs):
        nonlocal first_url_calls
        requested = list(requested)
        network_frontiers.append(requested)
        assert len(requested) == 1
        url = requested[0]
        if url == first_url:
            first_url_calls += 1
            if first_url_calls == 1:
                first_entered.set()
                await release_failure.wait()
                raise RuntimeError("simulated failed live attempt")
            body = first_body
        else:
            assert url == other_url
            other_entered.set()
            body = other_body
        fetched = FetchResult(
            url=url,
            content=body,
            source="direct",
            fetched_at="2026-08-25T02:00:00Z",
        )
        callback = kwargs["result_callback"]
        assert callback is not None
        callback(url, fetched)
        return SimpleNamespace(
            results=[fetched],
            errors=[None],
            stats={"requested_pages": 1, "common_crawl": {}},
        )

    async def _no_cache(**_kwargs):
        return None

    monkeypatch.setattr(
        ArchivalFetchClient,
        "fetch_many_with_fallback",
        _many,
    )
    for scraper in scrapers:
        monkeypatch.setattr(
            scraper,
            "_cache_successful_page_fetch",
            _no_cache,
        )

    observed = {}

    async def _run_failed_attempt():
        try:
            await scrapers[0]._fetch_page_contents_with_archival_fallback(
                [first_url],
                prefer_direct=True,
            )
        except RuntimeError as exc:
            observed["first_error"] = str(exc)
            first_failed.set()

    async def _run_other_url():
        observed["other"] = await scrapers[
            1
        ]._fetch_page_contents_with_archival_fallback(
            [other_url],
            prefer_direct=True,
        )

    async def _run_retry():
        observed["retry"] = await scrapers[
            2
        ]._fetch_page_contents_with_archival_fallback(
            [first_url],
            prefer_direct=True,
        )
        retry_finished.set()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(_run_failed_attempt)
        await first_entered.wait()
        task_group.start_soon(_run_other_url)
        with anyio.fail_after(1.0):
            await other_entered.wait()
        release_failure.set()
        with anyio.fail_after(1.0):
            await first_failed.wait()
        task_group.start_soon(_run_retry)
        with anyio.fail_after(1.0):
            await retry_finished.wait()

    assert observed["first_error"] == "simulated failed live attempt"
    assert observed["other"].payloads == [other_body]
    assert observed["retry"].payloads == [first_body]
    assert network_frontiers == [[first_url], [other_url], [first_url]]


@pytest.mark.anyio
async def test_page_multifetch_direct_successes_skip_archive_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls = [
        "https://codes.example.gov/title/1",
        "https://codes.example.gov/title/2",
    ]
    direct_calls: list[str] = []

    def _direct(_self, url: str):
        direct_calls.append(url)
        return FetchResult(
            url=url,
            content=f"current:{url}".encode(),
            source="direct",
            fetched_at="2026-08-24T00:00:00Z",
        )

    async def _inventory_must_not_run(**_kwargs):
        raise AssertionError("archive inventory is only a live-source fallback")

    async def _no_cache(**_kwargs):
        return None

    scraper = _StateFrontierScraper("WI", "Wisconsin")
    monkeypatch.setattr(ArchivalFetchClient, "_fetch_direct", _direct)
    monkeypatch.setattr(
        scraper,
        "_search_state_common_crawl_records",
        _inventory_must_not_run,
    )
    monkeypatch.setattr(scraper, "_cache_successful_page_fetch", _no_cache)

    result = await scraper._fetch_page_contents_with_archival_fallback(
        urls,
        prefer_direct=True,
    )

    assert sorted(direct_calls) == sorted(urls)
    assert result.payloads == [f"current:{url}".encode() for url in urls]
    assert result.stats["direct_initial_successes"] == 2
    assert result.stats["common_crawl_inventory_queries"] == 0
    assert result.stats["common_crawl_matched_pointers"] == 0
