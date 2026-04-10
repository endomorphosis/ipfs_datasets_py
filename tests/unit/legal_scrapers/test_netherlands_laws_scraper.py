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


def test_extract_title_and_text_captures_articles_and_chapters():
    from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws_scraper import (
        _extract_title_and_text,
    )

    parsed = _extract_title_and_text(
        """
        <html>
          <body>
            <main>
              <h1>Wetboek van Strafrecht</h1>
              <h2>Boek 1 Algemene bepalingen</h2>
              <h3>Titel I Reikwijdte</h3>
              <h4>Artikel 1</h4>
              <p>Geen feit is strafbaar dan uit kracht van een daaraan voorafgegane wettelijke strafbepaling.</p>
              <h4>Artikel 2</h4>
              <p>De Nederlandse strafwet is toepasselijk op ieder die zich in Nederland aan enig strafbaar feit schuldig maakt.</p>
            </main>
          </body>
        </html>
        """
    )

    assert parsed["title"] == "Wetboek van Strafrecht"
    assert len(parsed["structure"]["articles"]) == 2
    assert parsed["structure"]["articles"][0]["number"] == "1"
    assert parsed["structure"]["chapters"][0]["kind"] == "boek"
    assert parsed["structure"]["articles"][0]["citation"] == "Artikel 1"


def test_extract_info_metadata_captures_dates_aliases_and_versions():
    from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws_scraper import (
        _extract_info_metadata,
    )

    metadata = _extract_info_metadata(
        """
        <html>
          <body>
            <h1>Wetboek van Strafrecht</h1>
            <dl>
              <dt>Identificatienummer</dt><dd>BWBR0001854</dd>
              <dt>Soort regeling</dt><dd>Wet</dd>
              <dt>Citeertitel</dt><dd>Sr</dd>
              <dt>Datum inwerkingtreding</dt><dd>01-02-1994</dd>
              <dt>Datum van uitgifte</dt><dd>12 januari 1993</dd>
              <dt>Laatste wijziging</dt><dd>2024-10-01</dd>
            </dl>
            <a href="/BWBR0001854/2024-01-01/0/informatie">Versie 2024</a>
            <a href="https://www.overheid.nl/documenten/BWBR0001854">Overheid</a>
          </body>
        </html>
        """,
        info_url="https://wetten.overheid.nl/BWBR0001854/informatie",
    )

    assert metadata["identifier"] == "BWBR0001854"
    assert metadata["canonical_title"] == "Wetboek van Strafrecht"
    assert metadata["aliases"] == ["Sr"]
    assert metadata["effective_date"] == "1994-02-01"
    assert metadata["publication_date"] == "1993-01-12"
    assert metadata["last_modified_date"] == "2024-10-01"
    assert metadata["historical_versions"][0]["effective_date"] == "2024-01-01"
    assert any("overheid.nl" in url for url in metadata["authority_sources"])


def test_extract_title_and_text_handles_partial_html():
    from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws_scraper import (
        _extract_title_and_text,
    )

    parsed = _extract_title_and_text(
        """
        <main>
          <h1>Participatiewet
          <h3>Hoofdstuk 1 Algemene bepalingen
          <p>Inleidende tekst zonder correcte afsluiting
          <p>Artikel 1
          <p>In deze wet en de daarop berustende bepalingen wordt verstaan onder:
        """
    )

    assert "Participatiewet" in parsed["title"]
    assert len(parsed["structure"]["articles"]) == 1
    assert parsed["structure"]["articles"][0]["number"] == "1"
    assert "In deze wet" in parsed["structure"]["articles"][0]["text"]


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
            if "overheid.nl/documenten/BWBR0001854" in url:
                return _Response(
                    """
                    <html>
                      <body>
                        <h1>Overheid document</h1>
                        <p>BWBR0001854 Wetboek van Strafrecht</p>
                      </body>
                    </html>
                    """
                )
            if "informatie" in url:
                return _Response(
                    """
                    <html>
                      <body>
                        <h1>Wetboek van Strafrecht</h1>
                        <dl>
                          <dt>Soort regeling</dt><dd>Wet</dd>
                          <dt>Identificatienummer</dt><dd>BWBR0001854</dd>
                          <dt>Citeertitel</dt><dd>Sr</dd>
                          <dt>Datum inwerkingtreding</dt><dd>01-02-1994</dd>
                          <dt>Laatste wijziging</dt><dd>2024-10-01</dd>
                        </dl>
                        <a href="/BWBR0001854/2024-01-01/0/informatie">Versie 2024</a>
                        <a href="https://www.overheid.nl/documenten/BWBR0001854">Overheid</a>
                      </body>
                    </html>
                    """
                )
            if "BWBR0001854" in url:
                return _Response(
                    """
                    <html>
                      <head><title>Wetboek van Strafrecht</title></head>
                      <body>
                        <main>
                          <h1>Wetboek van Strafrecht</h1>
                          <h2>Boek 1 Algemene bepalingen</h2>
                          <h3>Artikel 1</h3>
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
    assert result["data"][0]["article_count"] == 1
    assert result["data"][0]["canonical_title"] == "Wetboek van Strafrecht"
    assert result["data"][0]["aliases"] == ["Sr"]
    assert result["data"][0]["effective_date"] == "1994-02-01"
    assert result["data"][0]["last_modified_date"] == "2024-10-01"
    assert result["data"][0]["historical_versions"][0]["effective_date"] == "2024-01-01"
    assert result["data"][0]["citations"] == ["Artikel 1"]
    assert result["data"][0]["metadata"]["verification"]["information_page_verified"] is True
    assert result["data"][0]["metadata"]["verification"]["authoritative_sources_checked"] >= 2
    assert result["data"][0]["metadata"]["verification"]["identifier_consistent"] is True


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
