from __future__ import annotations

from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.texas import (
    TexasScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.utah_title_xml import (
    parse_utah_xml_document,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.wisconsin import (
    WisconsinScraper,
)


def _utah_xml(*sections: tuple[str, str]) -> str:
    section_xml = "".join(
        (
            f'<section number="{number}">'
            f"<catchline>Heading for {number}</catchline>"
            f'<subsection number="(1)">{body}</subsection>'
            "</section>"
        )
        for number, body in sections
    )
    return (
        '<title number="76">'
        "<catchline>Utah Criminal Code</catchline>"
        '<chapter number="76-1">'
        "<catchline>General Provisions</catchline>"
        f"{section_xml}"
        "</chapter>"
        "</title>"
    )


def test_texas_acquisition_catalog_matches_all_statutory_codes() -> None:
    scraper = TexasScraper("TX", "Texas")

    codes = scraper.get_code_list()

    expected = list(scraper.OFFICIAL_CODES)
    assert [(row["type"], row["name"]) for row in codes] == expected
    assert len(codes) == scraper.OFFICIAL_CODE_COUNT == 30
    assert {row["type"] for row in codes} >= {
        "BO",
        "CV",
        "ES",
        "I1",
        "SD",
        "WL",
    }
    assert all(row["type"] != "Regulation" for row in codes)


@pytest.mark.anyio
async def test_texas_full_mode_does_not_replace_a_missing_zip_with_code_level_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = TexasScraper("TX", "Texas")

    async def _empty_zip(*args: Any, **kwargs: Any) -> list[Any]:
        del args, kwargs
        return []

    async def _forbidden_page_fetch(*args: Any, **kwargs: Any) -> bytes:
        del args, kwargs
        raise AssertionError("full mode must not fall back to a code landing page")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_scrape_statute_html_zip", _empty_zip)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_content_with_archival_fallback",
        _forbidden_page_fetch,
    )

    rows = await scraper.scrape_code(
        "Agriculture Code",
        scraper.official_html_url("AG"),
        max_statutes=None,
    )

    assert rows == []


def test_utah_title_xml_rejects_cross_title_identity_and_collapses_exact_duplicate() -> (
    None
):
    body = "This is retained official Utah statutory text with enough content."
    rows = parse_utah_xml_document(
        _utah_xml(
            ("76-1-101", body),
            ("76-1-101", body),
            ("9-3-102", "Embedded cross-title quotation with enough content."),
        )
    )

    assert [row.section_number for row in rows] == ["76-1-101"]
    assert rows[0].title_number == "76"


def test_utah_title_xml_fails_closed_on_divergent_duplicate_even_when_bounded() -> None:
    with pytest.raises(
        ValueError,
        match="divergent duplicate section identity: 76-1-101",
    ):
        parse_utah_xml_document(
            _utah_xml(
                ("76-1-101", "First official statutory body with enough content."),
                ("76-1-101", "Different official statutory body with enough content."),
            ),
            max_statutes=1,
        )


@pytest.mark.anyio
async def test_utah_full_mode_rejects_partial_live_title_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.utah import (
        UtahScraper,
    )

    scraper = UtahScraper("UT", "Utah")
    wrapper = '<a href="/xcode/Title76/76.html?v=C76_2025050720250507">Title 76</a>'

    async def _fetch(url: str, timeout: int = 25) -> str:
        del timeout
        if url.endswith("/xcode/code.html"):
            return wrapper
        raise AssertionError("partial discovery must fail before title fetching")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_text_with_archival", _fetch)

    with pytest.raises(RuntimeError, match="did not close the exact title catalog"):
        await scraper._scrape_official_xml_code_tree(
            "Utah Code",
            max_statutes=1_000_000,
        )


@pytest.mark.anyio
async def test_wisconsin_chapter_payload_is_not_fetched_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = WisconsinScraper("WI", "Wisconsin")
    chapter_url = scraper.official_chapter_url(939)
    fetched: list[str] = []
    discovered_sections: list[tuple[str, str]] = []

    async def _discover_chapters() -> list[tuple[str, str]]:
        return [(chapter_url, "Chapter 939")]

    async def _fetch(url: str, timeout_seconds: int = 15) -> bytes:
        del timeout_seconds
        fetched.append(url)
        return (
            '<html><body><a href="/document/statutes/939.50">939.50</a></body></html>'
        ).encode()

    async def _scrape_sections(
        code_name: str,
        section_urls: list[tuple[str, str]],
        max_statutes: Any = None,
    ) -> list[Any]:
        del code_name, max_statutes
        discovered_sections.extend(section_urls)
        return []

    monkeypatch.setattr(scraper, "_discover_chapter_links", _discover_chapters)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_content_with_archival_fallback",
        _fetch,
    )
    monkeypatch.setattr(scraper, "_scrape_section_urls", _scrape_sections)

    await scraper._scrape_official_index("Wisconsin Statutes")

    assert fetched == [chapter_url]
    assert discovered_sections == [
        (f"{scraper.get_base_url()}/document/statutes/939.50", "939.50")
    ]
