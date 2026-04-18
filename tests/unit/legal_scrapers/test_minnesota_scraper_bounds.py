from __future__ import annotations

import asyncio
from typing import List

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    BaseStateScraper,
    NormalizedStatute,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.alaska import AlaskaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.delaware import DelawareScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.kentucky import KentuckyScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.minnesota import MinnesotaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.mississippi import MississippiScraper


def _statute(index: int) -> NormalizedStatute:
    return NormalizedStatute(
        state_code="MN",
        state_name="Minnesota",
        statute_id=f"MN-{index}",
        code_name="Minnesota Statutes",
        section_number=f"{index}",
        source_url=f"https://www.revisor.mn.gov/statutes/cite/609.{index}",
        official_cite=f"Minn. Stat. § 609.{index}",
        full_text=f"Section {index}",
    )


class _SlowLegacyScraper(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://example.test"

    def get_code_list(self) -> list[dict[str, str]]:
        return [{"name": "Legacy Code", "url": "https://example.test/code"}]

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        await asyncio.sleep(0.05)
        return [_statute(1)]


@pytest.mark.anyio
async def test_minnesota_scrape_code_honors_max_statutes(monkeypatch) -> None:
    scraper = MinnesotaScraper("MN", "Minnesota")
    observed: dict[str, int] = {}

    async def fake_chapter_sections(code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        observed["max_statutes"] = max_statutes
        return [_statute(index) for index in range(10)]

    monkeypatch.setattr(scraper, "_scrape_chapter_sections", fake_chapter_sections)

    statutes = await scraper.scrape_code(
        "Minnesota Statutes",
        "https://www.revisor.mn.gov/statutes/cite/609.02",
        max_statutes=3,
    )

    assert observed["max_statutes"] == 3
    assert len(statutes) == 3


@pytest.mark.anyio
async def test_minnesota_chapter_section_fetch_is_capped(monkeypatch) -> None:
    scraper = MinnesotaScraper("MN", "Minnesota")
    fetched: list[str] = []

    async def fake_discover_chapter_urls(max_chapters: int) -> list[str]:
        assert max_chapters == 2
        return ["https://www.revisor.mn.gov/statutes/cite/609"]

    async def fake_fetch_page(url: str, **kwargs) -> str:
        return """
        <table>
          <tr><td>609.01 First section</td></tr>
          <tr><td>609.02 Second section</td></tr>
          <tr><td>609.03 Third section</td></tr>
          <tr><td>609.04 Fourth section</td></tr>
        </table>
        """

    async def fake_build(code_name: str, section_url: str) -> NormalizedStatute:
        fetched.append(section_url)
        return _statute(len(fetched))

    monkeypatch.setattr(scraper, "_discover_chapter_urls", fake_discover_chapter_urls)
    monkeypatch.setattr(scraper, "_fetch_page_content_with_archival_fallback", fake_fetch_page)
    monkeypatch.setattr(scraper, "_build_statute_from_section_page", fake_build)

    statutes = await scraper._scrape_chapter_sections("Minnesota Statutes", max_statutes=2)

    assert len(statutes) == 2
    assert len(fetched) == 2


@pytest.mark.anyio
async def test_base_scraper_times_out_legacy_scrape_code_during_bounded_run(monkeypatch) -> None:
    scraper = _SlowLegacyScraper("ZZ", "Test")
    monkeypatch.setenv("STATE_SCRAPER_CODE_TIMEOUT_SECONDS", "0.01")

    statutes = await scraper.scrape_all(max_statutes=1, rate_limit_delay=0.0)

    assert statutes == []


@pytest.mark.anyio
async def test_base_fetch_timeout_is_capped_by_bounded_run_env(monkeypatch) -> None:
    scraper = _SlowLegacyScraper("ZZ", "Test")
    observed: dict[str, int] = {}

    async def fake_load(url: str):
        return None

    async def fake_unified_fetch(*, url: str, timeout_seconds: int) -> bytes:
        observed["timeout_seconds"] = timeout_seconds
        return b"<html>ok</html>"

    async def fake_store(**kwargs):
        return None

    monkeypatch.setenv("STATE_SCRAPER_FETCH_TIMEOUT_SECONDS", "3")
    monkeypatch.setattr(scraper, "_load_page_bytes_from_ipfs_cache", fake_load)
    monkeypatch.setattr(scraper, "_fetch_page_content_with_unified_api", fake_unified_fetch)
    monkeypatch.setattr(scraper, "_store_page_bytes_in_ipfs_cache", fake_store)

    payload = await scraper._fetch_page_content_with_archival_fallback("https://example.test/code", timeout_seconds=30)

    assert payload == b"<html>ok</html>"
    assert observed["timeout_seconds"] == 3


@pytest.mark.anyio
async def test_kentucky_scrape_code_honors_max_statutes(monkeypatch) -> None:
    scraper = KentuckyScraper("KY", "Kentucky")
    built: list[str] = []

    async def fake_discover_chapter_links() -> list[tuple[str, str, str]]:
        return [("https://apps.legislature.ky.gov/law/statutes/chapter.aspx?id=37024", "CHAPTER 1 BOUNDARIES", "1")]

    async def fake_discover_section_links(chapter_url: str, chapter_label: str, chapter_number: str) -> list[tuple[str, str, str, str]]:
        assert chapter_number == "1"
        return [
            (
                f"https://apps.legislature.ky.gov/law/statutes/statute.aspx?id={index}",
                f".0{index} Section {index}",
                f"1.0{index}",
                chapter_label,
            )
            for index in range(10)
        ]

    async def fake_build(*, section_url: str, section_number: str, **kwargs) -> NormalizedStatute:
        built.append(section_url)
        statute = _statute(len(built))
        statute.state_code = "KY"
        statute.state_name = "Kentucky"
        statute.section_number = section_number
        statute.source_url = section_url
        statute.official_cite = f"Ky. Rev. Stat. § {section_number}"
        return statute

    monkeypatch.setattr(scraper, "_discover_chapter_links", fake_discover_chapter_links)
    monkeypatch.setattr(scraper, "_discover_section_links", fake_discover_section_links)
    monkeypatch.setattr(scraper, "_build_statute_from_section_page", fake_build)

    statutes = await scraper.scrape_code(
        "Kentucky Revised Statutes",
        "https://legislature.ky.gov/",
        max_statutes=4,
    )

    assert len(built) == 4
    assert len(statutes) == 4
    assert [statute.section_number for statute in statutes] == ["1.00", "1.01", "1.02", "1.03"]
    assert all("/law/statutes/statute.aspx?id=" in statute.source_url for statute in statutes)


@pytest.mark.anyio
async def test_kentucky_discovers_official_chapters_and_sections(monkeypatch) -> None:
    scraper = KentuckyScraper("KY", "Kentucky")

    async def fake_fetch_html(url: str, timeout_seconds: int = 5) -> str:
        if url.endswith("/law/statutes/"):
            return """
            <a href="chapter.aspx?id=37024">CHAPTER 1 BOUNDARIES</a>
            <a href="/Law/kar/Pages/default.aspx">Administrative Regulations</a>
            """
        return """
        <a href="statute.aspx?id=50298">.010 Legislative intent in establishing Kentucky State Plane Coordinate System.</a>
        <a href="statute.aspx?id=50299">.020 Kentucky State Plane Coordinate System.</a>
        <a href="chapter.aspx?id=bad">Chapter navigation</a>
        """

    monkeypatch.setattr(scraper, "_fetch_html", fake_fetch_html)

    chapters = await scraper._discover_chapter_links()
    sections = await scraper._discover_section_links(
        chapter_url=chapters[0][0],
        chapter_label=chapters[0][1],
        chapter_number=chapters[0][2],
    )

    assert chapters == [
        ("https://apps.legislature.ky.gov/law/statutes/chapter.aspx?id=37024", "CHAPTER 1 BOUNDARIES", "1")
    ]
    assert [section[2] for section in sections] == ["1.010", "1.020"]
    assert all("/law/statutes/statute.aspx?id=" in section[0] for section in sections)


@pytest.mark.anyio
async def test_kentucky_section_builder_rejects_failed_pdf_extraction(monkeypatch) -> None:
    scraper = KentuckyScraper("KY", "Kentucky")

    async def fake_fetch(*args, **kwargs) -> bytes:
        return b"%PDF-1.5 binary-ish stream endobj startxref"

    async def fake_extract(**kwargs) -> dict[str, str]:
        return {"text": "%PDF-1.5 \ufffd\ufffd binary stream endobj startxref", "method": "basic"}

    monkeypatch.setattr(scraper, "_fetch_official_ky_bytes", fake_fetch)
    monkeypatch.setattr(scraper, "_extract_text_from_document_bytes", fake_extract)

    statute = await scraper._build_statute_from_section_page(
        code_name="Kentucky Revised Statutes",
        section_url="https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=1",
        section_label=".010 Definitions",
        section_number="1.010",
        chapter_url="https://apps.legislature.ky.gov/law/statutes/chapter.aspx?id=1",
        chapter_label="Chapter 1",
        chapter_number="1",
    )

    assert statute is not None
    assert not statute.full_text.startswith("%PDF")
    assert statute.full_text == "KRS 1.010: .010 Definitions"
    assert statute.structured_data["extraction_method"] == "failed_pdf_extraction"
    assert statute.structured_data["skip_hydrate"] is True


@pytest.mark.anyio
async def test_kentucky_section_builder_splits_effective_date_from_history(monkeypatch) -> None:
    scraper = KentuckyScraper("KY", "Kentucky")

    async def fake_fetch(*args, **kwargs) -> bytes:
        return b"%PDF fake"

    async def fake_extract(**kwargs) -> dict[str, str]:
        return {
            "text": (
                ".010 Legislative intent.\n"
                "Effective: July 15, 2024 History: Created 2024 Ky. Acts ch. 1."
            ),
            "method": "pdf_processor",
        }

    monkeypatch.setattr(scraper, "_fetch_official_ky_bytes", fake_fetch)
    monkeypatch.setattr(scraper, "_extract_text_from_document_bytes", fake_extract)

    statute = await scraper._build_statute_from_section_page(
        code_name="Kentucky Revised Statutes",
        section_url="https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=1",
        section_label=".010 Legislative intent.",
        section_number="1.010",
        chapter_url="https://apps.legislature.ky.gov/law/statutes/chapter.aspx?id=1",
        chapter_label="Chapter 1",
        chapter_number="1",
    )

    assert statute is not None
    assert statute.metadata.effective_date == "July 15, 2024"
    assert statute.metadata.history == ["Created 2024 Ky. Acts ch. 1."]


@pytest.mark.anyio
async def test_delaware_static_chapter_parser_builds_real_sections(monkeypatch) -> None:
    scraper = DelawareScraper("DE", "Delaware")

    async def fake_discover_title_links() -> list[tuple[str, str]]:
        return [("https://delcode.delaware.gov/title1/index.html", "Title 1 - General Provisions")]

    async def fake_discover_chapter_links(title_url: str) -> list[tuple[str, str]]:
        return [("https://delcode.delaware.gov/title1/c001/index.html", "Chapter 1. DELAWARE CODE")]

    async def fake_fetch_html(url: str, timeout_seconds: int = 6) -> str:
        return """
        <div id="TitleHead">
          <h1>TITLE 1</h1>
          <h4>General Provisions</h4>
          <h3>CHAPTER 1. Delaware Code</h3>
        </div>
        <div id="CodeBody">
          <div class="Section">
            <div class="SectionHead" id="101">§ 101. Designation and citation of Code.</div>
            <p class="subsection">(a) The laws embraced in this title constitute the Delaware Code.</p>
          </div>
          <div class="Section">
            <div class="SectionHead" id="102">§ 102. Effective date of Code.</div>
            <p class="subsection">This Code shall become effective upon enactment.</p>
          </div>
        </div>
        """

    monkeypatch.setattr(scraper, "_discover_title_links", fake_discover_title_links)
    monkeypatch.setattr(scraper, "_discover_chapter_links", fake_discover_chapter_links)
    monkeypatch.setattr(scraper, "_fetch_official_de_html", fake_fetch_html)

    statutes = await scraper.scrape_code(
        "Delaware Code",
        "https://delcode.delaware.gov/index.html",
        max_statutes=1,
    )

    assert len(statutes) == 1
    assert statutes[0].section_number == "101"
    assert statutes[0].official_cite == "1 Del. C. § 101"
    assert statutes[0].source_url == "https://delcode.delaware.gov/title1/c001/index.html#101"
    assert statutes[0].structured_data["source_kind"] == "official_delaware_code_html"


@pytest.mark.anyio
async def test_alaska_ajax_fetch_parser_builds_real_sections(monkeypatch) -> None:
    scraper = AlaskaScraper("AK", "Alaska")

    async def fake_fetch_chunk(sec_start: str, timeout_seconds: int = 8) -> tuple[str, str]:
        assert sec_start == "1"
        return (
            """
            <div class="statute">
              <b><a name="01.05"> </a><h6>Chapter 05. Alaska Statutes.</h6></b>
              <b><a name="01.05.006"> </a>Sec. 01.05.006. Adoption of Alaska Statutes; notes, headings, and references not law.</b>
              The bulk formal revision of the laws of Alaska is adopted and enacted as the general and permanent law of Alaska.
            </div>
            <div class="statute">
              <b><a name="01.05.011"> </a>Sec. 01.05.011. Citation.</b>
              This section may be cited as Alaska Statutes and has enough text for parser acceptance.
            </div>
            """,
            "1.05.011",
        )

    monkeypatch.setattr(scraper, "_fetch_statute_chunk", fake_fetch_chunk)

    statutes = await scraper.scrape_code(
        "Alaska Statutes",
        "https://www.akleg.gov/basis/statutes.asp",
        max_statutes=1,
    )

    assert len(statutes) == 1
    assert statutes[0].section_number == "01.05.006"
    assert statutes[0].official_cite == "Alaska Stat. § 01.05.006"
    assert statutes[0].source_url == "https://www.akleg.gov/basis/statutes.asp#01.05.006"
    assert statutes[0].structured_data["source_kind"] == "official_alaska_statutes_ajax_html"


@pytest.mark.anyio
async def test_mississippi_archive_fallback_uses_bounded_attempts(monkeypatch) -> None:
    scraper = MississippiScraper("MS", "Mississippi")
    calls: list[dict[str, object]] = []
    long_history = (
        "House Bill 0001\n"
        "Description: Test education bill.\n"
        "History of Actions:\n"
        + ("Action taken by chamber. " * 40)
    )

    async def fake_request_text(url: str, headers: dict[str, str], timeout: int, attempts: int = 3) -> str:
        calls.append({"url": url, "timeout": timeout, "attempts": attempts, "bounded": headers.get("X-Bounded-Scrape")})
        if "allmsrs" in url:
            return '<a href="../history/HB0001.htm">HB 1</a>'
        return long_history

    monkeypatch.setattr(scraper, "_request_text", fake_request_text)

    statutes = await scraper._scrape_archived_bill_history("Mississippi Code", max_statutes=1)

    assert len(statutes) == 1
    assert {call["timeout"] for call in calls} == {15}
    assert {call["attempts"] for call in calls} == {1}
    assert {call["bounded"] for call in calls} == {"1"}
