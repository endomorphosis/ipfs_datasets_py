from __future__ import annotations

from pathlib import Path

import pytest


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "legal_scrapers"


def _fixture_text(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


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


def test_extract_discovery_links_keeps_official_seed_pages():
    from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws_scraper import (
        _extract_discovery_links,
    )

    html = """
    <html>
      <body>
        <a href="/zoeken/zoekresultaat/titel/test/page/2/count/100">Next</a>
        <a href="https://wetten.overheid.nl/uitgebreid_zoeken/">Advanced search</a>
        <a href="/BWBR0001854/">Document page</a>
        <a href="https://example.com/not-official">Ignore me</a>
      </body>
    </html>
    """

    links = _extract_discovery_links(html, "https://wetten.overheid.nl/zoeken/")

    assert links == [
        "https://wetten.overheid.nl/zoeken/zoekresultaat/titel/test/page/2/count/100/",
        "https://wetten.overheid.nl/uitgebreid_zoeken/",
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
    assert parsed["structure"]["articles"][0]["hierarchy_path_text"].startswith("Boek 1")
    assert parsed["structure"]["articles"][0]["hierarchy_path"][-1]["label"] == "Artikel 1"


def test_extract_title_and_text_captures_french_article_headings():
    from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws_scraper import (
        _extract_title_and_text,
    )

    parsed = _extract_title_and_text(
        """
        <main>
          <h1>Loi concernant les Mines, les Minières et les Carrières</h1>
          <h2>Titre I.er Des Mines, Minières et Carrières</h2>
          <h3>Article I.er</h3>
          <p>Les masses de substances minérales ou fossiles renfermées dans le sein de la terre.</p>
          <h3>Article 2</h3>
          <p>Seront considérées comme mines celles connues pour contenir en filons.</p>
        </main>
        """
    )

    assert len(parsed["structure"]["articles"]) == 2
    assert parsed["structure"]["articles"][0]["number"] == "I.er"
    assert parsed["structure"]["articles"][0]["citation"] == "Article I.er"
    assert parsed["structure"]["articles"][1]["number"] == "2"
    assert "Titre I.er" in parsed["structure"]["articles"][0]["hierarchy_path_text"]


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


def test_extract_info_metadata_rejects_greedy_title_fallbacks():
    from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws_scraper import (
        _extract_info_metadata,
    )

    metadata = _extract_info_metadata(
        """
        <html>
          <body>
            <h1>Wetboek van Burgerlijke Rechtsvordering</h1>
            <table>
              <tr><th>Niet officiële titel</th><td>Wetboek van Burgerlijke Rechtsvordering</td></tr>
              <tr><th>Citeertitel</th><td>De citeertitel is door de redactie vastgesteld.</td></tr>
              <tr><th>Soort regeling</th><td>Wet</td></tr>
              <tr><th>Identificatienummer</th><td>BWBR0001827</td></tr>
              <tr><th>Datum van inwerkingtreding</th><td>01-01-2026</td></tr>
            </table>
            <section>Opschrift Wetboek van Burgerlijke Rechtsvordering Citeertitel Soort regeling Identificatienummer BWBR0001827 Rechtsgebied Procesrecht</section>
          </body>
        </html>
        """,
        info_url="https://wetten.overheid.nl/BWBR0001827/informatie",
    )

    assert metadata["canonical_title"] == "Wetboek van Burgerlijke Rechtsvordering"
    assert metadata["aliases"] == []
    assert metadata["effective_date"] == "2026-01-01"
    assert len(metadata["canonical_title"]) < 100


def test_extract_info_metadata_rejects_geen_title_placeholders():
    from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws_scraper import (
        _extract_info_metadata,
    )

    metadata = _extract_info_metadata(
        """
        <html>
          <body>
            <h1>Muziekauteursrecht</h1>
            <table>
              <tr><th>Niet officiële titel</th><td>Geen</td></tr>
              <tr><th>Citeertitel</th><td>Geen</td></tr>
              <tr><th>Identificatienummer</th><td>BWBR0001958</td></tr>
            </table>
          </body>
        </html>
        """,
        info_url="https://wetten.overheid.nl/BWBR0001958/informatie",
    )

    assert metadata["canonical_title"] == "Muziekauteursrecht"
    assert metadata["aliases"] == []


def test_article_missing_diagnostics_flag_likely_parser_misses():
    from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws_scraper import (
        _diagnose_article_extraction,
    )

    diagnostic = _diagnose_article_extraction(
        {
            "law_identifier": "BWBRTESTMISS",
            "title": "Legacy article headings",
            "text": "Aanhef. Article 1 Eerste bepaling. Article 2 Tweede bepaling.",
            "article_count": 0,
        },
        [],
    )

    assert diagnostic["status"] == "article_extraction_missing"
    assert diagnostic["likely_article_heading_matches"] == 2


def test_fixture_document_parsing_builds_full_hierarchy_and_citations():
    from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws_scraper import (
        _build_article_records,
        _extract_title_and_text,
    )

    parsed = _extract_title_and_text(_fixture_text("netherlands_wetten_document.html"))
    document_row = {
        "jurisdiction": "NL",
        "jurisdiction_name": "Netherlands",
        "country": "Netherlands",
        "language": "nl",
        "identifier": "BWBR0001854",
        "official_identifier": "BWBR0001854",
        "title": parsed["title"],
        "canonical_title": parsed["title"],
        "aliases": ["Sr"],
        "document_type": "wet",
        "text": parsed["text"],
        "source_url": "https://wetten.overheid.nl/BWBR0001854/",
        "information_url": "https://wetten.overheid.nl/BWBR0001854/informatie",
        "effective_date": "1994-02-01",
        "publication_date": "1993-01-12",
        "last_modified_date": "2024-10-01",
        "historical_versions": [],
        "articles": parsed["structure"]["articles"],
        "chapters": parsed["structure"]["chapters"],
        "parts": parsed["structure"]["parts"],
        "scraped_at": "2026-04-10T00:00:00",
    }

    article_records = _build_article_records(document_row)

    assert len(parsed["structure"]["articles"]) == 3
    assert article_records[0]["book_label"] == "Boek 1 Algemene bepalingen"
    assert article_records[0]["title_label"] == "Titel I Reikwijdte van de strafwet"
    assert article_records[0]["division_label"] == "Afdeling 1 Strafbaarheid"
    assert article_records[0]["article_number"] == "1"
    assert article_records[1]["article_heading"] == "Strafwet toepasselijkheid"
    assert article_records[0]["citation"] == (
        "Sr, Boek 1 Algemene bepalingen, Titel I Reikwijdte van de strafwet, "
        "Afdeling 1 Strafbaarheid, Artikel 1"
    )
    assert article_records[2]["citation"].endswith("Artikel 92")
    assert article_records[0]["law_identifier"] == "BWBR0001854"
    assert article_records[0]["law_version_identifier"] == "BWBR0001854@1994-02-01"


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


@pytest.mark.anyio
async def test_scrape_netherlands_laws_with_explicit_document_urls(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import netherlands_laws_scraper as scraper

    document_fixture = _fixture_text("netherlands_wetten_document.html")
    info_fixture = _fixture_text("netherlands_wetten_informatie.html")

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
                return _Response(info_fixture)
            if "BWBR0001854" in url:
                return _Response(document_fixture)
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
    assert result["metadata"]["article_records_count"] == 3
    assert result["metadata"]["search_records_count"] == 4
    assert result["data"][0]["identifier"] == "BWBR0001854"
    assert "Strafrecht" in result["data"][0]["title"]
    assert result["data"][0]["article_count"] == 3
    assert result["data"][0]["canonical_title"] == "Wetboek van Strafrecht"
    assert result["data"][0]["aliases"] == ["Sr"]
    assert result["data"][0]["effective_date"] == "1994-02-01"
    assert result["data"][0]["law_identifier"] == "BWBR0001854"
    assert result["data"][0]["law_version_identifier"] == "BWBR0001854@1994-02-01"
    assert result["data"][0]["canonical_law_url"] == "https://wetten.overheid.nl/BWBR0001854/"
    assert result["data"][0]["versioned_law_url"] == "https://wetten.overheid.nl/BWBR0001854/1994-02-01/0/"
    assert result["data"][0]["last_modified_date"] == "2024-10-01"
    assert any(version["effective_date"] == "2012-01-01" for version in result["data"][0]["historical_versions"])
    assert any(version["is_current"] is True for version in result["data"][0]["historical_versions"])
    assert any(version["law_version_identifier"] == "BWBR0001854@2012-01-01" for version in result["data"][0]["historical_versions"])
    assert any(version["version_end_date"] for version in result["data"][0]["historical_versions"] if version["effective_date"] == "2012-01-01")
    assert result["data"][0]["citations"] == ["Artikel 1", "Artikel 2", "Artikel 92"]
    assert result["article_data"][0]["citation"].startswith("Sr, Boek 1 Algemene bepalingen")
    assert result["article_data"][0]["document_version_identifier"] == "BWBR0001854@1994-02-01"
    assert result["article_data"][0]["hierarchy_path_text"].endswith("Artikel 1")
    assert result["article_data"][1]["article_heading"] == "Strafwet toepasselijkheid"
    assert result["data"][0]["metadata"]["verification"]["information_page_verified"] is True
    assert result["data"][0]["metadata"]["verification"]["authoritative_sources_checked"] >= 2
    assert result["data"][0]["metadata"]["verification"]["identifier_consistent"] is True


@pytest.mark.anyio
async def test_scrape_netherlands_laws_reports_non_article_documents(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import netherlands_laws_scraper as scraper

    document_html = """
    <html>
      <main>
        <h1>Muziekauteursrecht</h1>
        <p>De Minister van Justitie;</p>
        <p>Gelet op art. 30a der Auteurswet 1912.</p>
        <p>Heeft goedgevonden en verstaan:</p>
        <p>De toestemming wordt verleend met ingang van 13 april 1933.</p>
      </main>
    </html>
    """
    info_html = """
    <html>
      <body>
        <h1>Muziekauteursrecht</h1>
        <dl>
          <dt>Identificatienummer</dt><dd>BWBR0001958</dd>
          <dt>Soort regeling</dt><dd>Ministeriële regeling</dd>
          <dt>Niet officiële titel</dt><dd>Muziekauteursrecht</dd>
          <dt>Datum van inwerkingtreding</dt><dd>13-04-1933</dd>
        </dl>
      </body>
    </html>
    """

    class _Response:
        def __init__(self, text: str, status_code: int = 200):
            self.text = text
            self.status_code = status_code

    class _Session:
        headers = {}

        def get(self, url, timeout=40):  # noqa: ARG002
            if url == "https://wetten.overheid.nl/BWBR0001958/":
                return _Response(document_html)
            if url == "https://wetten.overheid.nl/BWBR0001958/informatie":
                return _Response(info_html)
            raise AssertionError(f"Unexpected URL fetched: {url}")

    monkeypatch.setattr(scraper, "_make_session", lambda: _Session())
    monkeypatch.setattr(scraper.time, "sleep", lambda _seconds: None)

    result = await scraper.scrape_netherlands_laws(
        document_urls=["https://wetten.overheid.nl/BWBR0001958/"],
        output_dir=str(tmp_path),
    )

    assert result["status"] == "success"
    assert result["metadata"]["records_count"] == 1
    assert result["metadata"]["article_records_count"] == 0
    assert result["metadata"]["article_producing_laws_count"] == 0
    assert result["metadata"]["non_article_producing_laws_count"] == 1
    assert result["metadata"]["genuine_non_article_laws_count"] == 1
    assert result["metadata"]["article_extraction_missing_count"] == 0
    assert result["metadata"]["non_article_producing_laws"][0]["law_identifier"] == "BWBR0001958"
    assert result["data"][0]["article_extraction_status"] == "non_article_document"
    assert "unnumbered or non-article" in result["data"][0]["article_extraction_note"]


@pytest.mark.anyio
async def test_scrape_netherlands_laws_crawls_seed_pages_and_writes_run_metadata(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import netherlands_laws_scraper as scraper

    document_fixture = _fixture_text("netherlands_wetten_document.html")
    info_fixture = _fixture_text("netherlands_wetten_informatie.html")
    bw_fixture = document_fixture.replace("Wetboek van Strafrecht", "Burgerlijk Wetboek Boek 1")
    bw_info_fixture = (
        info_fixture
        .replace("BWBR0001854", "BWBR0002656")
        .replace("Wetboek van Strafrecht", "Burgerlijk Wetboek Boek 1")
        .replace(">Sr<", ">BW Boek 1<")
    )
    seed_one = """
    <html>
      <body>
        <a href="/BWBR0001854/">Wetboek van Strafrecht</a>
        <a href="/zoeken/zoekresultaat/titel/verloten/titelf/0/tekstf/1/d/10-5-2025/dx/0/page/2/count/100/s/2">Volgende pagina</a>
      </body>
    </html>
    """
    seed_two = """
    <html>
      <body>
        <a href="/BWBR0002656/">Burgerlijk Wetboek Boek 1</a>
      </body>
    </html>
    """

    class _Response:
        def __init__(self, text: str, status_code: int = 200):
            self.text = text
            self.status_code = status_code

    class _Session:
        headers = {}

        def get(self, url, timeout=40):  # noqa: ARG002
            if url == "https://wetten.overheid.nl/zoeken/":
                return _Response(seed_one)
            if url == "https://wetten.overheid.nl/zoeken/zoekresultaat/titel/verloten/titelf/0/tekstf/1/d/10-5-2025/dx/0/page/2/count/100/s/2/":
                return _Response(seed_two)
            if url == "https://wetten.overheid.nl/BWBR0001854/informatie":
                return _Response(info_fixture)
            if url == "https://wetten.overheid.nl/BWBR0002656/informatie":
                return _Response(bw_info_fixture)
            if url == "https://wetten.overheid.nl/BWBR0001854/":
                return _Response(document_fixture)
            if url == "https://wetten.overheid.nl/BWBR0002656/":
                return _Response(bw_fixture)
            if "overheid.nl/documenten/BWBR0001854" in url:
                return _Response("<html><body>BWBR0001854 Wetboek van Strafrecht</body></html>")
            if "overheid.nl/documenten/BWBR0002656" in url:
                return _Response("<html><body>BWBR0002656 Burgerlijk Wetboek Boek 1</body></html>")
            raise AssertionError(f"Unexpected URL fetched: {url}")

    monkeypatch.setattr(scraper, "_make_session", lambda: _Session())
    monkeypatch.setattr(scraper.time, "sleep", lambda _seconds: None)

    result = await scraper.scrape_netherlands_laws(
        seed_urls=["https://wetten.overheid.nl/zoeken"],
        output_dir=str(tmp_path),
        crawl_depth=1,
        max_seed_pages=5,
        max_documents=5,
    )

    assert result["status"] == "success"
    assert len(result["data"]) == 2
    assert result["metadata"]["seed_pages_visited"] == 2
    assert result["metadata"]["candidate_links_found"] == 2
    assert result["metadata"]["official_law_documents_accepted"] == 2
    assert result["metadata"]["documents_fetched"] == 2
    assert result["metadata"]["documents_parsed"] == 2
    assert result["metadata"]["documents_skipped"] == 0
    assert result["metadata"]["documents_failed"] == 0
    assert Path(result["metadata"]["index_path"]).exists()
    assert Path(result["metadata"]["article_index_path"]).exists()
    assert Path(result["metadata"]["search_index_path"]).exists()
    assert Path(result["metadata"]["jsonld_files"][0]).exists()
    assert Path(result["metadata"]["run_metadata_path"]).exists()


@pytest.mark.anyio
async def test_scrape_netherlands_laws_resume_skip_existing_preserves_and_extends_outputs(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import netherlands_laws_scraper as scraper

    document_fixture = _fixture_text("netherlands_wetten_document.html")
    info_fixture = _fixture_text("netherlands_wetten_informatie.html")
    bw_fixture = document_fixture.replace("Wetboek van Strafrecht", "Burgerlijk Wetboek Boek 1")
    bw_info_fixture = (
        info_fixture
        .replace("BWBR0001854", "BWBR0002656")
        .replace("Wetboek van Strafrecht", "Burgerlijk Wetboek Boek 1")
        .replace(">Sr<", ">BW Boek 1<")
    )
    seed_html = """
    <html>
      <body>
        <a href="/BWBR0001854/">Wetboek van Strafrecht</a>
        <a href="/BWBR0002656/">Burgerlijk Wetboek Boek 1</a>
      </body>
    </html>
    """

    class _Response:
        def __init__(self, text: str, status_code: int = 200):
            self.text = text
            self.status_code = status_code

    class _Session:
        headers = {}

        def get(self, url, timeout=40):  # noqa: ARG002
            if url == "https://wetten.overheid.nl/zoeken/":
                return _Response(seed_html)
            if url == "https://wetten.overheid.nl/BWBR0001854/informatie":
                return _Response(info_fixture)
            if url == "https://wetten.overheid.nl/BWBR0002656/informatie":
                return _Response(bw_info_fixture)
            if url == "https://wetten.overheid.nl/BWBR0001854/":
                return _Response(document_fixture)
            if url == "https://wetten.overheid.nl/BWBR0002656/":
                return _Response(bw_fixture)
            if "overheid.nl/documenten/BWBR0001854" in url:
                return _Response("<html><body>BWBR0001854 Wetboek van Strafrecht</body></html>")
            if "overheid.nl/documenten/BWBR0002656" in url:
                return _Response("<html><body>BWBR0002656 Burgerlijk Wetboek Boek 1</body></html>")
            raise AssertionError(f"Unexpected URL fetched: {url}")

    monkeypatch.setattr(scraper, "_make_session", lambda: _Session())
    monkeypatch.setattr(scraper.time, "sleep", lambda _seconds: None)

    first = await scraper.scrape_netherlands_laws(
        document_urls=["https://wetten.overheid.nl/BWBR0001854/"],
        output_dir=str(tmp_path),
    )
    second = await scraper.scrape_netherlands_laws(
        seed_urls=["https://wetten.overheid.nl/zoeken"],
        output_dir=str(tmp_path),
        crawl_depth=0,
        max_seed_pages=1,
        max_documents=2,
        skip_existing=True,
    )

    assert first["metadata"]["records_count"] == 1
    assert second["metadata"]["documents_skipped"] == 1
    assert second["metadata"]["documents_fetched"] == 1
    assert second["metadata"]["documents_parsed"] == 1
    assert second["metadata"]["output_records_count"] == 2
    assert second["metadata"]["distinct_law_identifiers_in_outputs"] == 2
    assert second["metadata"]["article_producing_laws_count"] == 2
    assert sorted(row["law_identifier"] for row in second["data"]) == ["BWBR0002656"]


@pytest.mark.anyio
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
