from __future__ import annotations

import pytest


def test_extract_document_links_filters_for_wetten_bwb_documents():
    from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws_scraper import (
        _extract_document_links,
    )

    html = """
    <html>
      <body>
        <a href="/BWBR0001854/">Wetboek van Strafrecht</a>
        <a href="https://wetten.overheid.nl/BWBR0002656/">Burgerlijk Wetboek Boek 1</a>
        <a href="https://example.com/not-a-law">Ignore me</a>
        <a href="/BWBR0001854/#artikel1">Duplicate</a>
      </body>
    </html>
    """

    links = _extract_document_links(html, "https://wetten.overheid.nl/zoeken")

    assert links == [
        "https://wetten.overheid.nl/BWBR0001854/",
        "https://wetten.overheid.nl/BWBR0002656/",
    ]


@pytest.mark.asyncio
async def test_scrape_netherlands_laws_with_explicit_document_urls(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import netherlands_laws_scraper as scraper

    class _Response:
        def __init__(self, text: str, status_code: int = 200):
            self.text = text
            self.status_code = status_code

    class _Session:
        headers = {}

        def get(self, url, timeout=40):  # noqa: ARG002
            if "BWBR0001854" in url:
                return _Response(
                    """
                    <html>
                      <head><title>Wetboek van Strafrecht</title></head>
                      <body>
                        <main>
                          <h1>Wetboek van Strafrecht</h1>
                          <p>Artikel 1 Strafrecht tekst.</p>
                        </main>
                      </body>
                    </html>
                    """
                )
            raise AssertionError(f"Unexpected URL fetched: {url}")

    monkeypatch.setattr(scraper, "_make_session", lambda: _Session())
    monkeypatch.setattr(scraper.time, "sleep", lambda _seconds: None)

    result = await scraper.scrape_netherlands_laws(
        document_urls=["https://wetten.overheid.nl/BWBR0001854/"],
        seed_urls=[],
        output_dir=str(tmp_path),
    )

    assert result["status"] == "success"
    assert result["metadata"]["records_count"] == 1
    assert result["data"][0]["identifier"] == "BWBR0001854"
    assert "Strafrecht" in result["data"][0]["title"]


@pytest.mark.asyncio
async def test_mcp_tool_scrape_netherlands_laws_delegates(monkeypatch):
    from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import mcp_tools
    from ipfs_datasets_py.processors.legal_scrapers import legal_dataset_api

    async def _fake_scrape_netherlands_laws_from_parameters(parameters, *, tool_version="1.0.0"):
        return {
            "status": "success",
            "tool_version": tool_version,
            "echo": parameters,
        }

    monkeypatch.setattr(
        legal_dataset_api,
        "scrape_netherlands_laws_from_parameters",
        _fake_scrape_netherlands_laws_from_parameters,
    )

    result = await mcp_tools.scrape_netherlands_laws({"max_documents": 2})

    assert result["status"] == "success"
    assert result["echo"] == {"max_documents": 2}
