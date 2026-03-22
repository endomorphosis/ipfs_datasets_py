from __future__ import annotations

import pytest

from ipfs_datasets_py.processors.legal_scrapers.common_crawl_scraper import (
    CommonCrawlLegalScraper,
    SourceType,
)


def test_detect_source_type_treats_state_gov_hosts_as_state() -> None:
    scraper = CommonCrawlLegalScraper()

    assert (
        scraper._detect_source_type("https://texreg.sos.state.tx.us/public/readtac$ext.ViewTAC")
        == SourceType.STATE
    )
    assert scraper._detect_source_type("https://www.congress.gov/") == SourceType.FEDERAL


@pytest.mark.anyio
async def test_fetch_common_crawl_passes_state_jurisdiction() -> None:
    scraper = CommonCrawlLegalScraper()

    observed: dict[str, object] = {}

    class _FakeEngine:
        def search_domain(self, domain, **kwargs):
            observed["domain"] = domain
            observed.update(kwargs)
            return []

    scraper.cc_engine = _FakeEngine()

    result = await scraper._fetch_common_crawl(
        "https://texreg.sos.state.tx.us/public/readtac$ext.ViewTAC",
        source_type=SourceType.STATE,
    )

    assert result is None
    assert observed["domain"] == "texreg.sos.state.tx.us"
    assert observed["jurisdiction"] == "state"
    assert observed["state_code"] == "TX"
