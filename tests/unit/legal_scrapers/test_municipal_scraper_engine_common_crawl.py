from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.processors.legal_scrapers.municipal_scraper_engine import (
    MunicipalScraperFallbacks,
)


class _FakeIndexLoader:
    last_query_error = None

    def __init__(self) -> None:
        self.calls = []

    def query_municipal_index(self, **kwargs):
        self.calls.append(kwargs)
        return [
            {
                "domain": "portlandoregon.gov",
                "url": "https://www.portland.gov/code",
                "collection": "CC-MAIN-2024-10",
                "timestamp": "20240101000000",
                "mime": "text/html",
                "status": 200,
                "warc_filename": "crawl-data/example.warc.gz",
                "warc_offset": 10,
                "warc_length": 20,
                "gnis": "2411471",
                "place_name": "City of Portland",
                "state_code": "OR",
            }
        ]


class _FakeCcApi:
    def fetch_warc_record(self, **kwargs):
        return (
            SimpleNamespace(ok=True, raw_base64=base64.b64encode(b"fake-warc-member").decode("ascii")),
            "range",
            None,
        )

    def extract_http_from_warc_gzip_member(self, *_args, **_kwargs):
        return SimpleNamespace(
            body_text_preview="<html><title>Portland Code</title><main>Title 33 Planning and Zoning</main></html>",
            http_status=200,
            body_mime="text/html",
            body_charset="utf-8",
            ok=True,
            error=None,
        )


@pytest.mark.asyncio
async def test_municipal_common_crawl_uses_index_records_to_extract_pages() -> None:
    index_loader = _FakeIndexLoader()
    scraper = MunicipalScraperFallbacks()

    result = await scraper._scrape_common_crawl(
        "https://www.portland.gov/code",
        "Portland, OR",
        index_loader=index_loader,
        ccapi=_FakeCcApi(),
        max_results=5,
    )

    assert result["success"] is True
    assert result["metadata"]["place_name"] == "Portland"
    assert result["metadata"]["state_code"] == "OR"
    assert index_loader.calls[0]["place_name"] == "Portland"
    assert index_loader.calls[0]["state_code"] == "OR"
    assert result["data"]["pages"][0]["title"] == "Portland Code"
    assert "Title 33 Planning and Zoning" in result["data"]["pages"][0]["text"]
