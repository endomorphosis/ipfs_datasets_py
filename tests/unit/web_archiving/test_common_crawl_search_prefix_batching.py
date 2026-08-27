from __future__ import annotations

import asyncio
import queue
import sys
import types
from types import SimpleNamespace
from typing import Any

import pytest

from ipfs_datasets_py.mcp_server.tools.web_archive_tools import common_crawl_search


class _InlineProcess:
    """Execute a multiprocessing target inline so test observations stay local."""

    def __init__(
        self,
        *,
        target: Any,
        kwargs: dict[str, Any],
        daemon: bool,
    ) -> None:
        self._target = target
        self._kwargs = kwargs
        self.daemon = daemon
        self.exitcode: int | None = None

    def start(self) -> None:
        self._target(**self._kwargs)
        self.exitcode = 0

    def join(self, _timeout: float | None = None) -> None:
        return None

    def is_alive(self) -> bool:
        return False

    def terminate(self) -> None:
        raise AssertionError("a completed inline worker must not be terminated")


@pytest.fixture
def mocked_cdx(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    observed = SimpleNamespace(
        fetcher_calls=[],
        iter_calls=[],
        records=[],
        constructor_error=None,
        iterator_error=None,
    )

    class _CDXFetcher:
        def __init__(self, **kwargs: Any) -> None:
            observed.fetcher_calls.append(kwargs)
            if observed.constructor_error is not None:
                raise observed.constructor_error

        def iter(self, **kwargs: Any):
            observed.iter_calls.append(kwargs)

            def _records():
                for data in observed.records:
                    yield SimpleNamespace(data=data)
                if observed.iterator_error is not None:
                    raise observed.iterator_error

            return _records()

    monkeypatch.setitem(sys.modules, "cdx_toolkit", types.SimpleNamespace(CDXFetcher=_CDXFetcher))
    monkeypatch.setattr(common_crawl_search.mp, "Queue", queue.Queue)
    monkeypatch.setattr(common_crawl_search.mp, "Process", _InlineProcess)
    return observed


def _record(url: str, *, sequence: int = 1) -> dict[str, Any]:
    return {
        "url": url,
        "timestamp": f"2026082500000{sequence}",
        "status": "200",
        "mime": "text/html",
        "digest": f"sha1:{sequence}",
        "filename": f"crawl-data/CC-MAIN-2026-30/segment-{sequence}.warc.gz",
        "offset": str(sequence * 100),
        "length": str(sequence * 10),
    }


def test_prefix_search_uses_one_scoped_iterator_and_filters_exact_urls_locally(
    mocked_cdx: SimpleNamespace,
) -> None:
    prefix = "https://codes.example.gov/current/title-"
    targets = [f"{prefix}1", f"{prefix}2"]
    mocked_cdx.records = [
        _record(targets[0], sequence=1),
        _record(f"{prefix}not-requested", sequence=2),
        _record(targets[1], sequence=3),
    ]

    result = asyncio.run(
        common_crawl_search.search_common_crawl(
            url_prefix=prefix,
            canonical_urls=targets,
            crawl_id="CC-MAIN-2026-30",
            limit=10,
            from_timestamp="20260101",
            to_timestamp="20261231",
        )
    )

    assert result["status"] == "success"
    assert result["complete"] is True
    assert result["truncated"] is False
    assert [record["url"] for record in result["results"]] == targets
    assert mocked_cdx.fetcher_calls == [
        {"source": "cc", "crawl": ["CC-MAIN-2026-30"]}
    ]
    assert mocked_cdx.iter_calls == [
        {
            "url": f"{prefix}*",
            "limit": 11,
            "from_ts": "20260101",
            "to": "20261231",
        }
    ]
    assert all(call["url"] not in targets for call in mocked_cdx.iter_calls)

    first = result["results"][0]
    assert first["page"] == targets[0]
    assert first["status"] == first["status_code"] == "200"
    assert first["mime"] == first["mime_type"] == "text/html"
    assert first["filename"] == first["warc_filename"]
    assert first["offset"] == first["warc_offset"]
    assert first["length"] == first["warc_length"]


@pytest.mark.parametrize(
    ("record_count", "expected_complete", "expected_truncated", "expected_count"),
    [
        (2, True, False, 2),
        (3, False, True, 2),
    ],
)
def test_record_cap_reads_cap_plus_one_and_reports_clean_exhaustion_or_extra(
    mocked_cdx: SimpleNamespace,
    record_count: int,
    expected_complete: bool,
    expected_truncated: bool,
    expected_count: int,
) -> None:
    mocked_cdx.records = [
        _record(f"https://codes.example.gov/law/{index}", sequence=index)
        for index in range(1, record_count + 1)
    ]

    result = asyncio.run(
        common_crawl_search.search_common_crawl(
            url_pattern="https://codes.example.gov/law/*",
            limit=2,
        )
    )

    assert result["status"] == "success"
    assert result["complete"] is expected_complete
    assert result["truncated"] is expected_truncated
    assert result["count"] == expected_count
    assert result["records_examined"] == record_count
    assert mocked_cdx.iter_calls == [
        {"url": "https://codes.example.gov/law/*", "limit": 3}
    ]


def test_domain_search_remains_backward_compatible(mocked_cdx: SimpleNamespace) -> None:
    mocked_cdx.records = [_record("https://sub.example.gov/law/1")]

    result = asyncio.run(common_crawl_search.search_common_crawl("example.gov", limit=4))

    assert result["status"] == "success"
    assert result["complete"] is True
    assert mocked_cdx.fetcher_calls == [{"source": "cc"}]
    assert mocked_cdx.iter_calls == [{"url": "*.example.gov", "limit": 5}]
    assert result["crawl_info"]["domain"] == "example.gov"


@pytest.mark.parametrize("failure_location", ["constructor", "iterator"])
def test_transport_failures_are_errors_not_successful_empty_results(
    mocked_cdx: SimpleNamespace,
    failure_location: str,
) -> None:
    error = RuntimeError(f"{failure_location} transport failure")
    if failure_location == "constructor":
        mocked_cdx.constructor_error = error
    else:
        mocked_cdx.iterator_error = error

    result = asyncio.run(
        common_crawl_search.search_common_crawl(
            url_prefix="https://codes.example.gov/law/",
            limit=5,
        )
    )

    assert result["status"] == "error"
    assert result["results"] == []
    assert result["complete"] is False
    assert result["truncated"] is False
    assert "transport failure" in result["error"]


def test_invalid_or_incompatible_selectors_fail_before_a_query(
    mocked_cdx: SimpleNamespace,
) -> None:
    conflicting = asyncio.run(
        common_crawl_search.search_common_crawl(
            domain="example.gov",
            url_prefix="https://example.gov/law/",
        )
    )
    incompatible = asyncio.run(
        common_crawl_search.search_common_crawl(
            url_pattern="https://example.gov/law/*",
            canonical_urls=["https://other.example.net/law/1"],
        )
    )
    malformed = asyncio.run(
        common_crawl_search.search_common_crawl(
            url_pattern="https://example.gov/law/*/section/*",
        )
    )

    for result in (conflicting, incompatible, malformed):
        assert result["status"] == "error"
        assert result["results"] == []
        assert result["complete"] is False
        assert "configuration" in result["error"].lower()
    assert mocked_cdx.fetcher_calls == []
    assert mocked_cdx.iter_calls == []


def test_timeout_is_an_error_not_successful_empty_results(
    mocked_cdx: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del mocked_cdx

    class _HangingProcess:
        exitcode = None

        def __init__(self, **_kwargs: Any) -> None:
            self.alive = True

        def start(self) -> None:
            return None

        def join(self, _timeout: float | None = None) -> None:
            return None

        def is_alive(self) -> bool:
            return self.alive

        def terminate(self) -> None:
            self.alive = False
            self.exitcode = -15

    monkeypatch.setattr(common_crawl_search.mp, "Process", _HangingProcess)
    monkeypatch.setenv("COMMON_CRAWL_CDX_SEARCH_TIMEOUT_SECONDS", "0.01")

    result = asyncio.run(
        common_crawl_search.search_common_crawl(
            url_prefix="https://codes.example.gov/law/",
            limit=5,
        )
    )

    assert result["status"] == "error"
    assert result["results"] == []
    assert result["complete"] is False
    assert "timed out" in result["error"]
