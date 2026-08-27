from __future__ import annotations

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    BaseStateScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.state_archival_fetch import (
    ArchivalFetchClient,
)


class _StrictLedgerScraper(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://example.gov"

    def get_code_list(self):
        return []

    async def scrape_code(self, code_name: str, code_url: str):
        del code_name, code_url
        return []


@pytest.mark.anyio
async def test_strict_ledger_forces_one_grouped_inventory_and_direct_only_residual(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine

    urls = [
        "https://example.gov/code/title1/chapter1/section1/",
        "https://example.gov/code/title1/chapter1/section2/",
    ]
    direct_calls: list[str] = []
    common_crawl_calls: list[tuple[str, ...]] = []
    inventory_calls: list[tuple[str, ...]] = []
    legacy_wayback_calls: list[str] = []
    archive_is_calls: list[str] = []

    def _direct(_self, url: str, *, headers=None):
        del headers
        direct_calls.append(url)
        return None

    async def _common_crawl(**kwargs):
        common_crawl_calls.append(tuple(kwargs.get("url_terms") or ()))
        return []

    async def _inventory(requested, **_kwargs):
        inventory_calls.append(tuple(requested))
        return {
            "status": "success",
            "captures_by_url": {},
            "receipts": [],
            "errors": [],
            "stats": {
                "requested_pages": len(requested),
                "unique_pages": len(set(requested)),
                "prefix_queries_planned": 1,
                "prefix_queries_attempted": 1,
                "prefix_queries_succeeded": 1,
                "prefix_queries_failed": 0,
                "matched_pages": 0,
                "unmatched_pages": len(set(requested)),
            },
        }

    async def _forbid_wayback(_self, url: str):
        legacy_wayback_calls.append(url)
        raise AssertionError("strict plural fetch must not use per-page Wayback")

    async def _forbid_archive_is(_self, url: str):
        archive_is_calls.append(url)
        raise AssertionError("strict plural fetch must not use per-page archive.is")

    monkeypatch.setattr(ArchivalFetchClient, "_fetch_direct", _direct)
    monkeypatch.setattr(ArchivalFetchClient, "_fetch_from_wayback", _forbid_wayback)
    monkeypatch.setattr(ArchivalFetchClient, "_fetch_from_archive_is", _forbid_archive_is)
    monkeypatch.setattr(
        wayback_machine_engine,
        "fetch_wayback_capture_inventory",
        _inventory,
    )

    scraper = _StrictLedgerScraper("NH", "New Hampshire")
    scraper.attach_state_law_acquisition_ledger(
        StateLawMultiFetchAcquisitionLedger(
            tmp_path / "evidence",
            jurisdiction="NH",
            parser_name=type(scraper).__name__,
        )
    )
    monkeypatch.setattr(scraper, "_search_state_common_crawl_records", _common_crawl)

    result = await scraper._fetch_page_contents_with_archival_fallback_retrying_residuals(
        urls,
        residual_retry_attempts=1,
        content_validator=lambda payload: bool(payload),
        media_type="text/html",
        max_concurrency=2,
        prefer_direct=True,
    )

    assert common_crawl_calls and len(common_crawl_calls) == 1
    assert inventory_calls == [tuple(urls)]
    assert legacy_wayback_calls == []
    assert archive_is_calls == []
    assert sorted(direct_calls) == sorted([*urls, *urls])
    assert all(not payload for payload in result.payloads)
    attempts = result.stats["residual_retry_attempt_batches"]
    assert attempts[0]["archive_recovery_enabled"] is True
    assert attempts[1]["archive_recovery_enabled"] is False
    assert result.stats["residual_retry_rounds_executed"] == 1
    assert result.stats["per_page_archive_fallback_disabled"] is True
