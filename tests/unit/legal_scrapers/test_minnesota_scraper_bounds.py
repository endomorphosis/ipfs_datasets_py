from __future__ import annotations

from typing import List

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import NormalizedStatute
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
async def test_kentucky_scrape_code_honors_max_statutes(monkeypatch) -> None:
    scraper = KentuckyScraper("KY", "Kentucky")
    observed: list[int] = []

    async def fake_generic_scrape(*args, **kwargs) -> List[NormalizedStatute]:
        observed.append(kwargs["max_sections"])
        statutes = [_statute(index) for index in range(10)]
        for index, statute in enumerate(statutes):
            statute.source_url = f"https://apps.legislature.ky.gov/law/statutes/statute.aspx?id={index}"
        return statutes

    monkeypatch.setattr(scraper, "_generic_scrape", fake_generic_scrape)

    statutes = await scraper.scrape_code(
        "Kentucky Revised Statutes",
        "https://legislature.ky.gov/",
        max_statutes=4,
    )

    assert observed == [4]
    assert len(statutes) == 4


@pytest.mark.anyio
async def test_kentucky_scrape_code_keeps_bounded_generic_rows_when_filter_is_empty(monkeypatch) -> None:
    scraper = KentuckyScraper("KY", "Kentucky")

    async def fake_generic_scrape(*args, **kwargs) -> List[NormalizedStatute]:
        statutes = [_statute(index) for index in range(5)]
        for index, statute in enumerate(statutes):
            statute.state_code = "KY"
            statute.state_name = "Kentucky"
            statute.source_url = f"https://apps.legislature.ky.gov/law/statutes/chapter.aspx?id={index}"
        return statutes

    monkeypatch.setattr(scraper, "_generic_scrape", fake_generic_scrape)

    statutes = await scraper.scrape_code(
        "Kentucky Revised Statutes",
        "https://legislature.ky.gov/",
        max_statutes=2,
    )

    assert len(statutes) == 2
    assert all(statute.state_code == "KY" for statute in statutes)


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
