from __future__ import annotations

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oregon import OregonScraper


@pytest.mark.anyio
async def test_oregon_other_rules_entry_discovery_filters_terms(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = (
        '{"value":['
        '{"Title":"Oregon Rules of Civil Procedure","EncodedAbsUrl":"https://example.org/orcp.aspx"},'
        '{"Title":"Random Rule","EncodedAbsUrl":"https://example.org/random.aspx"}'
        ']}'
    ).encode("utf-8")

    async def _fake_fetch(self, url: str, timeout_seconds: int = 25) -> bytes:
        assert "getbytitle" in url
        return payload

    monkeypatch.setattr(OregonScraper, "_fetch_page_content_with_archival_fallback", _fake_fetch)

    scraper = OregonScraper("OR", "Oregon")
    rows = await scraper._discover_other_rules_entries(["civil procedure"])

    assert rows == [{"title": "Oregon Rules of Civil Procedure", "url": "https://example.org/orcp.aspx"}]


def test_oregon_parse_criminal_chapter_selection_with_ranges(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OREGON_CRIMINAL_PROCEDURE_CHAPTERS", "131-133, 136, 140-139")
    scraper = OregonScraper("OR", "Oregon")

    assert scraper._parse_chapter_selection() == ["131", "132", "133", "136", "139", "140"]


@pytest.mark.anyio
async def test_oregon_scrape_code_dispatches_to_court_rule_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_local(self, code_name: str, code_url: str):
        return ["local"]

    async def _fake_civil(self, code_name: str, code_url: str):
        return ["civil"]

    async def _fake_criminal(self, code_name: str):
        return ["criminal"]

    monkeypatch.setattr(OregonScraper, "_scrape_local_court_rules", _fake_local)
    monkeypatch.setattr(OregonScraper, "_scrape_civil_procedure_rules", _fake_civil)
    monkeypatch.setattr(OregonScraper, "_scrape_criminal_procedure_rules", _fake_criminal)

    scraper = OregonScraper("OR", "Oregon")

    local_rows = await scraper.scrape_code("Oregon Local Court Rules", "https://www.courts.oregon.gov/rules/Pages/slr.aspx")
    civil_rows = await scraper.scrape_code("Oregon Rules of Civil Procedure", "https://www.oregonlegislature.gov/bills_laws/Pages/orcp.aspx")
    criminal_rows = await scraper.scrape_code("Oregon Rules of Criminal Procedure", "https://example.org")

    assert local_rows == ["local"]
    assert civil_rows == ["civil"]
    assert criminal_rows == ["criminal"]


def test_oregon_code_list_includes_procedural_and_local_rules() -> None:
    scraper = OregonScraper("OR", "Oregon")
    names = {row["name"] for row in scraper.get_code_list()}

    assert "Oregon Rules of Civil Procedure" in names
    assert "Oregon Rules of Criminal Procedure" in names
    assert "Oregon Local Court Rules" in names
