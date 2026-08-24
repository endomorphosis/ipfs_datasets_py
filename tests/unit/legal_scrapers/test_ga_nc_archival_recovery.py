"""Georgia/North Carolina official HTML recovery via archive transports."""

from __future__ import annotations

from pathlib import Path

import pytest
import requests

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    NormalizedStatute,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia import (
    GeorgiaFullCorpusIncompleteError,
    GeorgiaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina import (
    NorthCarolinaScraper,
)


def test_georgia_archive_transport_is_recovery_not_official() -> None:
    scraper = GeorgiaScraper("GA", "Georgia")
    authority, kind = scraper._classify_html_transport("wayback")
    assert authority == "recovery"
    assert kind.endswith("_via_archive")
    assert "justia" not in kind
    live_authority, live_kind = scraper._classify_html_transport("requests_direct")
    assert live_authority == "official"
    assert live_kind == "official_georgia_code_html"


def test_north_carolina_archive_transport_is_recovery_not_official() -> None:
    scraper = NorthCarolinaScraper("NC", "North Carolina")
    authority, kind = scraper._classify_html_transport("archive_is")
    assert authority == "recovery"
    assert "justia" not in kind
    assert scraper._classify_html_transport("direct")[0] == "official"


@pytest.mark.anyio
async def test_north_carolina_full_mode_never_falls_through_empty_exhaustive_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = NorthCarolinaScraper("NC", "North Carolina")
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    legacy_called = False

    async def _empty_exhaustive(self, code_name, max_statutes=None):
        return []

    async def _partial_legacy(self, code_name, max_statutes=None):
        nonlocal legacy_called
        legacy_called = True
        return [
            NormalizedStatute(
                state_code="NC",
                state_name="North Carolina",
                statute_id="partial",
                code_name=code_name,
                chapter_number="1",
                section_number="1-1",
                full_text=("Partial legacy North Carolina statute. " * 12),
                source_url="https://www.ncleg.gov/Laws/GeneralStatutes",
            )
        ]

    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_scrape_official_bychapter_html",
        _empty_exhaustive,
    )
    monkeypatch.setattr(NorthCarolinaScraper, "_scrape_official_index", _partial_legacy)

    with pytest.raises(RuntimeError, match="refusing legacy index"):
        await scraper.scrape_code(
            "North Carolina General Statutes",
            "https://www.ncleg.gov/Laws/GeneralStatutes",
            max_statutes=None,
        )

    assert legacy_called is False


@pytest.mark.anyio
async def test_georgia_live_miss_uses_archival_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper = GeorgiaScraper("GA", "Georgia")

    async def _no_cache(url: str):
        return b""

    async def _recover(url: str, timeout_seconds: int = 18):
        scraper._record_fetch_event(provider="wayback", success=True)
        return (
            b"<html><body><main><h1>16-1-1</h1><p>"
            b"This title shall be known and may be cited as the Official Code of Georgia Annotated."
            b"</p></main></body></html>"
        )

    monkeypatch.setattr(scraper, "_load_page_bytes_from_any_cache", _no_cache)
    monkeypatch.setattr(scraper, "_fetch_page_content_with_archival_fallback", _recover)
    monkeypatch.setattr(
        requests, "get", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("blocked"))
    )

    html = await scraper._fetch_official_ga_html(
        "https://www.legis.ga.gov/legislation/georgia-code/title-16/chapter-1/section-16-1-1/"
    )
    assert "Official Code of Georgia" in html
    statute = await scraper._parse_section_page(
        code_name="Official Code of Georgia Annotated",
        section_url="https://www.legis.ga.gov/legislation/georgia-code/title-16/chapter-1/section-16-1-1/",
        section_label="16-1-1",
        title_label="Crimes",
        chapter_label="General Provisions",
    )
    assert statute is not None
    assert "legis.ga.gov" in statute.source_url
    assert "justia" not in statute.source_url
    assert statute.structured_data["source_authority_class"] == "recovery"
    assert statute.structured_data["source_kind"] == "official_georgia_code_html_via_archive"


@pytest.mark.anyio
async def test_georgia_rejects_contaminated_archive_html(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper = GeorgiaScraper("GA", "Georgia")

    async def _no_cache(url: str):
        return b""

    async def _recover(url: str, timeout_seconds: int = 18):
        scraper._record_fetch_event(provider="wayback", success=True)
        return (
            b"<html><body><main>"
            b"Skip to main content Privacy Policy Footer navigation Copyright (c) Site Map"
            b"</main></body></html>"
        )

    monkeypatch.setattr(scraper, "_load_page_bytes_from_any_cache", _no_cache)
    monkeypatch.setattr(scraper, "_fetch_page_content_with_archival_fallback", _recover)
    monkeypatch.setattr(
        requests, "get", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("blocked"))
    )

    statute = await scraper._parse_section_page(
        code_name="Official Code of Georgia Annotated",
        section_url="https://www.legis.ga.gov/legislation/georgia-code/title-16/chapter-1/section-16-1-1/",
        section_label="16-1-1",
        title_label="Crimes",
        chapter_label="General Provisions",
    )
    assert statute is None


@pytest.mark.anyio
async def test_georgia_full_corpus_still_refuses_justia(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper = GeorgiaScraper("GA", "Georgia")
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv("GEORGIA_JUSTIA_ENABLE", "1")

    async def _empty_official(self, *, code_name, code_url, max_statutes):
        return []

    async def _justia(self, code_name, year, max_statutes):
        return [
            NormalizedStatute(
                state_code="GA",
                state_name="Georgia",
                statute_id="justia",
                code_name=code_name,
                section_number="16-1-1",
                section_name="Secondary",
                full_text=("Justia secondary mirror text that must not sole-admit. " * 12),
                source_url="https://law.justia.com/codes/georgia/fixture",
            )
        ]

    monkeypatch.setattr(GeorgiaScraper, "_scrape_official_georgia_code", _empty_official)
    monkeypatch.setattr(GeorgiaScraper, "_scrape_justia_year", _justia)
    rows = await scraper.scrape_code(
        "Official Code of Georgia Annotated",
        "https://www.legis.ga.gov/legislation/georgia-code",
        max_statutes=4,
    )
    assert rows == []


@pytest.mark.anyio
async def test_georgia_full_corpus_never_sole_admits_configured_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = GeorgiaScraper("GA", "Georgia")
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    archive_called = False

    def _archive(**_kwargs):
        nonlocal archive_called
        archive_called = True
        return [
            NormalizedStatute(
                state_code="GA",
                state_name="Georgia",
                statute_id="archive",
                code_name="Official Code of Georgia Annotated",
                section_number="16-1-1",
                section_name="Recovery only",
                full_text=("Archived official-locator recovery text. " * 12),
                source_url=(
                    "https://www.legis.ga.gov/legislation/georgia-code/"
                    "title-16/chapter-1/section-16-1-1"
                ),
                structured_data={"source_authority_class": "recovery"},
            )
        ]

    async def _empty_official(self, *, code_name, code_url, max_statutes):
        return []

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia_archive."
        "parse_configured_georgia_archive",
        _archive,
    )
    monkeypatch.setattr(GeorgiaScraper, "_scrape_official_georgia_code", _empty_official)

    with pytest.raises(GeorgiaFullCorpusIncompleteError) as exc_info:
        await scraper.scrape_code(
            "Official Code of Georgia Annotated",
            "https://www.legis.ga.gov/legislation/georgia-code",
            max_statutes=None,
        )

    assert exc_info.value.evidence["full_corpus_admissible"] is False
    assert archive_called is False


@pytest.mark.anyio
async def test_georgia_uncapped_full_mode_never_calls_partial_legacy_walker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = GeorgiaScraper("GA", "Georgia")
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    legacy_called = False

    async def _partial_recovery(self, *, code_name, code_url, max_statutes):
        nonlocal legacy_called
        legacy_called = True
        return [
            NormalizedStatute(
                state_code="GA",
                state_name="Georgia",
                statute_id="partial-recovery",
                code_name=code_name,
                title_number="16",
                section_number="16-1-1",
                section_name="Partial recovery row",
                full_text=("Archived partial Georgia statute text. " * 12),
                source_url=(
                    "https://www.legis.ga.gov/legislation/georgia-code/"
                    "title-16/chapter-1/section-16-1-1"
                ),
                structured_data={"source_authority_class": "recovery"},
            )
        ]

    monkeypatch.setattr(GeorgiaScraper, "_scrape_official_georgia_code", _partial_recovery)

    with pytest.raises(GeorgiaFullCorpusIncompleteError) as exc_info:
        await scraper.scrape_code(
            "Official Code of Georgia Annotated",
            "https://www.legis.ga.gov/legislation/georgia-code",
            max_statutes=None,
        )

    assert legacy_called is False
    assert exc_info.value.evidence["fresh_live_frontier_verified"] is False
    assert exc_info.value.evidence["full_corpus_admissible"] is False


@pytest.mark.anyio
async def test_georgia_general_code_never_sole_admits_configured_constitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constitution = tmp_path / "georgia-constitution.html"
    constitution.write_text(
        "<html><body><h2>Article I. Bill of Rights</h2>"
        "<h3>Section I. Rights of Persons</h3>"
        "<p>Paragraph I. Life, liberty, and property. No person shall be "
        "deprived of life, liberty, or property except by due process of law.</p>"
        "</body></html>",
        encoding="utf-8",
    )
    monkeypatch.setenv("GEORGIA_CONSTITUTION_HTML", str(constitution))
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")

    with pytest.raises(GeorgiaFullCorpusIncompleteError):
        await GeorgiaScraper("GA", "Georgia").scrape_code(
            "Official Code of Georgia Annotated",
            "https://www.legis.ga.gov/legislation/georgia-code",
            max_statutes=None,
        )


def test_georgia_catalog_archive_refuses_non_official_urls() -> None:
    scraper = GeorgiaScraper("GA", "Georgia")
    assert scraper._official_http_get_via_archive("https://law.justia.com/codes/georgia/") == b""


def test_north_carolina_catalog_archive_refuses_non_official_urls() -> None:
    scraper = NorthCarolinaScraper("NC", "North Carolina")
    assert scraper._official_http_get_via_archive("https://law.justia.com/codes/north-carolina/") == b""
