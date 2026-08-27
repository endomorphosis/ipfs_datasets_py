from __future__ import annotations

import time
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_scrapers import common_crawl_index_loader
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.connecticut import (
    ConnecticutScraper,
)
from ipfs_datasets_py.processors.web_archiving import common_crawl_integration


@pytest.mark.asyncio
async def test_state_inventory_reuses_one_shared_domain_query_and_exact_pointers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    loader_modes: list[bool] = []

    class _Loader:
        def __init__(self, **kwargs: Any) -> None:
            self.use_hf_fallback = bool(kwargs["use_hf_fallback"])

        def query_state_index(self, **_kwargs: Any) -> list[dict[str, Any]]:
            loader_modes.append(self.use_hf_fallback)
            return []

    domain_queries: list[tuple[str, int]] = []

    class _Engine:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def is_available(self) -> bool:
            return True

        def search_domain(
            self,
            domain: str,
            max_matches: int,
            **_kwargs: Any,
        ) -> list[dict[str, Any]]:
            domain_queries.append((domain, max_matches))
            return [
                {
                    "url": "https://www.cga.ct.gov/current/pub/title_1.htm",
                    "timestamp": "20260701010101",
                    "status": 200,
                    "mime": "text/html",
                    "filename": "crawl-data/CC-MAIN-2026-26/ct.warc.gz",
                    "offset": "120",
                    "length": "450",
                },
                {
                    "url": "https://www.cga.ct.gov/current/pub/unrequested.htm",
                    "timestamp": "20260701010102",
                    "status": 200,
                    "mime": "text/html",
                    "warc_filename": "crawl-data/unrequested.warc.gz",
                    "warc_offset": 600,
                    "warc_length": 300,
                },
                {
                    "url": "https://www.cga.ct.gov/current/pub/title_2.htm",
                    "timestamp": "20260701010103",
                    "status": 200,
                    "mime": "text/html",
                    "warc_filename": "",
                    "warc_offset": 900,
                    "warc_length": 300,
                },
            ]

    monkeypatch.setattr(common_crawl_index_loader, "CommonCrawlIndexLoader", _Loader)
    monkeypatch.setattr(common_crawl_integration, "CommonCrawlSearchEngine", _Engine)
    monkeypatch.setenv(
        "LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR",
        str(tmp_path / "page-cache"),
    )

    scraper = ConnecticutScraper("CT", "Connecticut")
    records = await scraper._search_state_common_crawl_records(
        domain_terms=["www.cga.ct.gov", "https://www.cga.ct.gov/current/pub/"],
        url_terms=["/current/pub/title_1.htm", "/current/pub/title_2.htm"],
        mime_terms=["html"],
        max_results=25,
    )

    assert loader_modes == [False]
    assert domain_queries == [("www.cga.ct.gov", 25)]
    assert len(records) == 1
    assert records[0]["state_code"] == "CT"
    assert records[0]["warc_filename"] == "crawl-data/CC-MAIN-2026-26/ct.warc.gz"
    assert records[0]["warc_offset"] == 120
    assert records[0]["warc_length"] == 450


@pytest.mark.asyncio
async def test_state_inventory_pushes_one_broad_prefix_into_one_collection_query(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class _Loader:
        def __init__(self, **kwargs: Any) -> None:
            self.use_hf_fallback = bool(kwargs["use_hf_fallback"])

        def query_state_index(self, **_kwargs: Any) -> list[dict[str, Any]]:
            return []

    observed: list[tuple[str, int, dict[str, Any]]] = []

    class _Engine:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def is_available(self) -> bool:
            return True

        def search_domain(
            self,
            domain: str,
            max_matches: int,
            **kwargs: Any,
        ) -> list[dict[str, Any]]:
            observed.append((domain, max_matches, dict(kwargs)))
            return [
                {
                    "url": "http://www.cga.ct.gov/current/pub/title_1.htm",
                    "timestamp": "20260701010101",
                    "status": 200,
                    "mime": "text/html",
                    "filename": "crawl-data/CC-MAIN-2026-34/ct.warc.gz",
                    "offset": "120",
                    "length": "450",
                }
            ]

    monkeypatch.setattr(common_crawl_index_loader, "CommonCrawlIndexLoader", _Loader)
    monkeypatch.setattr(common_crawl_integration, "CommonCrawlSearchEngine", _Engine)
    monkeypatch.setenv(
        "STATE_SCRAPER_COMMON_CRAWL_COLLECTION",
        "CC-MAIN-2026-34",
    )
    monkeypatch.setenv(
        "LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR",
        str(tmp_path / "page-cache"),
    )

    scraper = ConnecticutScraper("CT", "Connecticut")
    records = await scraper._search_state_common_crawl_records(
        domain_terms=["www.cga.ct.gov"],
        url_terms=["/current/pub/"],
        mime_terms=["html"],
        max_results=25,
    )

    assert len(records) == 1
    assert observed == [
        (
            "www.cga.ct.gov",
            25,
            {
                "collection": "CC-MAIN-2026-34",
                "url_prefixes": (
                    "https://www.cga.ct.gov/current/pub/",
                    "http://www.cga.ct.gov/current/pub/",
                ),
            },
        )
    ]


@pytest.mark.asyncio
async def test_state_inventory_retains_legacy_remote_as_last_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    loader_modes: list[bool] = []
    legacy_record = {
        "url": "https://www.cga.ct.gov/current/pub/title_1.htm",
        "warc_filename": "crawl-data/legacy-ct.warc.gz",
        "warc_offset": 10,
        "warc_length": 20,
    }

    class _Loader:
        def __init__(self, **kwargs: Any) -> None:
            self.use_hf_fallback = bool(kwargs["use_hf_fallback"])

        def query_state_index(self, **_kwargs: Any) -> list[dict[str, Any]]:
            loader_modes.append(self.use_hf_fallback)
            return [legacy_record] if self.use_hf_fallback else []

    class _Engine:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def is_available(self) -> bool:
            return True

        def search_domain(self, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
            return []

    monkeypatch.setattr(common_crawl_index_loader, "CommonCrawlIndexLoader", _Loader)
    monkeypatch.setattr(common_crawl_integration, "CommonCrawlSearchEngine", _Engine)
    monkeypatch.setenv(
        "LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR",
        str(tmp_path / "page-cache"),
    )

    scraper = ConnecticutScraper("CT", "Connecticut")
    records = await scraper._search_state_common_crawl_records(
        domain_terms=["www.cga.ct.gov"],
        url_terms=["/current/pub/title_1.htm"],
        mime_terms=["html"],
        max_results=10,
    )

    assert loader_modes == [False, True]
    assert records == [legacy_record]


@pytest.mark.asyncio
async def test_state_inventory_reuses_only_equal_or_larger_domain_inventory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class _Loader:
        def __init__(self, **kwargs: Any) -> None:
            self.use_hf_fallback = bool(kwargs["use_hf_fallback"])
            self.last_query_error = None

        def query_state_index(self, **_kwargs: Any) -> list[dict[str, Any]]:
            return []

    raw_records = [
        {
            "url": f"https://www.cga.ct.gov/current/pub/title_{number}.htm",
            "timestamp": f"2026070101010{number}",
            "status": 200,
            "mime": "text/html",
            "warc_filename": "crawl-data/CC-MAIN-2026-26/ct.warc.gz",
            "warc_offset": number * 100,
            "warc_length": 50,
        }
        for number in (1, 2)
    ]
    domain_queries: list[tuple[str, int]] = []

    class _Engine:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def is_available(self) -> bool:
            return True

        def search_domain(
            self,
            domain: str,
            max_matches: int,
            **_kwargs: Any,
        ) -> list[dict[str, Any]]:
            domain_queries.append((domain, max_matches))
            return list(raw_records)

    monkeypatch.setattr(common_crawl_index_loader, "CommonCrawlIndexLoader", _Loader)
    monkeypatch.setattr(common_crawl_integration, "CommonCrawlSearchEngine", _Engine)
    monkeypatch.setenv(
        "LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR",
        str(tmp_path / "page-cache"),
    )

    scraper = ConnecticutScraper("CT", "Connecticut")
    first = await scraper._search_state_common_crawl_records(
        domain_terms=["www.cga.ct.gov"],
        url_terms=["/current/pub/title_1.htm"],
        mime_terms=["html"],
        max_results=100,
    )
    cached_superset = await scraper._search_state_common_crawl_records(
        domain_terms=["www.cga.ct.gov"],
        url_terms=["/current/pub/title_2.htm"],
        mime_terms=["html"],
        max_results=50,
    )
    cache_too_small = await scraper._search_state_common_crawl_records(
        domain_terms=["www.cga.ct.gov"],
        url_terms=["/current/pub/title_2.htm"],
        mime_terms=["html"],
        max_results=200,
    )

    assert [record["url"] for record in first] == [raw_records[0]["url"]]
    assert [record["url"] for record in cached_superset] == [raw_records[1]["url"]]
    assert [record["url"] for record in cache_too_small] == [raw_records[1]["url"]]
    assert domain_queries == [
        ("www.cga.ct.gov", 100),
        ("www.cga.ct.gov", 200),
    ]


@pytest.mark.asyncio
async def test_state_inventory_backs_off_shared_and_legacy_429s_for_one_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    loader_modes: list[bool] = []

    class _Loader:
        def __init__(self, **kwargs: Any) -> None:
            self.use_hf_fallback = bool(kwargs["use_hf_fallback"])
            self.last_query_error = None

        def query_state_index(self, **_kwargs: Any) -> list[dict[str, Any]]:
            loader_modes.append(self.use_hf_fallback)
            self.last_query_error = (
                "HTTP 429 Too Many Requests"
                if self.use_hf_fallback
                else "No local index"
            )
            return []

    domain_queries: list[tuple[str, int]] = []

    class _Engine:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def is_available(self) -> bool:
            return True

        def search_domain(
            self,
            domain: str,
            max_matches: int,
            **_kwargs: Any,
        ) -> list[dict[str, Any]]:
            domain_queries.append((domain, max_matches))
            raise RuntimeError("HTTP 429 Too Many Requests")

    monkeypatch.setattr(common_crawl_index_loader, "CommonCrawlIndexLoader", _Loader)
    monkeypatch.setattr(common_crawl_integration, "CommonCrawlSearchEngine", _Engine)
    monkeypatch.setenv("STATE_SCRAPER_COMMON_CRAWL_FAILURE_BACKOFF_SECONDS", "600")
    monkeypatch.setenv(
        "LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR",
        str(tmp_path / "page-cache"),
    )

    scraper = ConnecticutScraper("CT", "Connecticut")
    first = await scraper._search_state_common_crawl_records(
        domain_terms=["www.cga.ct.gov"],
        url_terms=["/current/pub/title_1.htm"],
        mime_terms=["html"],
        max_results=100,
    )
    second = await scraper._search_state_common_crawl_records(
        domain_terms=["www.cga.ct.gov"],
        url_terms=["/current/pub/title_2.htm"],
        mime_terms=["html"],
        max_results=200,
    )

    assert first == []
    assert second == []
    assert domain_queries == [("www.cga.ct.gov", 100)]
    assert loader_modes == [False, True, False]
    assert scraper._last_state_common_crawl_inventory_stats[
        "shared_domain_backoff_skips"
    ] == 1
    assert scraper._last_state_common_crawl_inventory_stats["legacy_backoff_skips"] == 1
    assert scraper._last_state_common_crawl_inventory_stats["source"] == "failure_backoff"


@pytest.mark.asyncio
async def test_state_inventory_domain_query_has_a_hard_async_deadline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class _Loader:
        def __init__(self, **kwargs: Any) -> None:
            self.use_hf_fallback = bool(kwargs["use_hf_fallback"])
            self.last_query_error = None

        def query_state_index(self, **_kwargs: Any) -> list[dict[str, Any]]:
            return []

    domain_queries: list[tuple[str, int]] = []

    class _Engine:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def is_available(self) -> bool:
            return True

        def search_domain(
            self,
            domain: str,
            max_matches: int,
            **_kwargs: Any,
        ) -> list[dict[str, Any]]:
            domain_queries.append((domain, max_matches))
            time.sleep(1.2)
            return []

    monkeypatch.setattr(common_crawl_index_loader, "CommonCrawlIndexLoader", _Loader)
    monkeypatch.setattr(common_crawl_integration, "CommonCrawlSearchEngine", _Engine)
    monkeypatch.setenv(
        "STATE_SCRAPER_COMMON_CRAWL_INVENTORY_TIMEOUT_SECONDS",
        "1",
    )
    monkeypatch.setenv(
        "STATE_SCRAPER_COMMON_CRAWL_FAILURE_BACKOFF_SECONDS",
        "600",
    )
    monkeypatch.setenv(
        "LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR",
        str(tmp_path / "page-cache"),
    )

    scraper = ConnecticutScraper("CT", "Connecticut")
    started = time.perf_counter()
    records = await scraper._search_state_common_crawl_records(
        domain_terms=["timeout.cga.ct.gov"],
        url_terms=["/current/pub/title_1.htm"],
        mime_terms=["html"],
        max_results=25,
    )
    elapsed = time.perf_counter() - started

    assert records == []
    assert domain_queries == [("timeout.cga.ct.gov", 25)]
    assert elapsed < 1.15
    assert scraper._last_state_common_crawl_inventory_stats[
        "shared_domain_query_timeouts"
    ] == 1
    assert scraper._last_state_common_crawl_inventory_stats[
        "shared_domain_query_failures"
    ] == 1
