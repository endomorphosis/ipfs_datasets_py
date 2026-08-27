"""Regression coverage for the Florida and Delaware live corpus repairs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
)
from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import (
    _write_state_jsonld_files,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    NormalizedStatute,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.delaware import (
    DelawareScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.delaware_chapter import (
    parse_delaware_chapter_html,
    title_link_rows,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.florida import (
    FloridaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.florida_chapter import (
    parse_florida_chapter_html,
)


FL_CHAPTER_URL = (
    "https://www.leg.state.fl.us/Statutes/index.cfm?App_mode=Display_Statute&"
    "URL=0000-0099/0001/0001.html"
)


@pytest.mark.anyio
async def test_florida_live_heading_is_normalized_and_short_law_is_retained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = """
    <a href="index.cfm?App_mode=Display_Index&amp;Title_Request=I#TitleI">Title I</a>
    <div class="ChapterNumber">CHAPTER 1</div>
    <div class="ChapterName">DEFINITIONS</div>
    <div class="Section">
      <span class="SectionNumber">1.99</span>
      <span class="CatchlineText">Effect.</span>
      <span class="SectionBody">It is.</span>
    </div>
    """
    scraper = FloridaScraper("FL", "Florida")

    async def _fetch(url: str, timeout_seconds: int = 12) -> str:
        scraper._record_fetch_event(provider="requests_direct", success=True)
        return html

    monkeypatch.setattr(scraper, "_fetch_official_fl_html", _fetch)
    rows = await scraper._parse_chapter_sections(
        code_name="Florida Statutes",
        chapter_url=FL_CHAPTER_URL,
        chapter_label="Chapter 1",
        max_statutes=1,
    )

    assert [(row.title_number, row.chapter_number, row.section_number) for row in rows] == [
        ("I", "1", "1.99")
    ]
    assert rows[0].full_text == "It is."
    assert rows[0].structured_data["retrieval_transport"] == "live_https"


@pytest.mark.anyio
async def test_florida_chapter_rows_retain_exact_input_digest_in_jsonld(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    html = (
        "<a href='index.cfm?App_mode=Display_Index&amp;Title_Request=I#TitleI'>"
        "Title I</a><div class='ChapterNumber'>CHAPTER 1</div>"
        "<div class='ChapterName'>DEFINITIONS</div>"
        "<div class='Section'><span class='SectionNumber'>1.99</span>"
        "<span class='CatchlineText'>Effect.</span>"
        "<span class='SectionBody'>It is.</span></div>"
    )
    body = html.encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    receipt = {
        "content_sha256": digest,
        "official_url": FL_CHAPTER_URL,
        "source_transport": "direct",
    }
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="FL",
        parser_name="FloridaScraper",
    )
    ledger.retain_parser_input(
        official_url=FL_CHAPTER_URL,
        body=body,
        transport_receipt=receipt,
        media_type="text/html",
    )
    scraper = FloridaScraper("FL", "Florida")
    scraper.attach_state_law_acquisition_ledger(ledger)
    scraper._last_page_fetch_transport_evidence = receipt

    async def _fetch(url: str, timeout_seconds: int = 12) -> str:
        assert url == FL_CHAPTER_URL
        return html

    monkeypatch.setattr(scraper, "_fetch_official_fl_html", _fetch)
    rows = await scraper._parse_chapter_sections(
        code_name="Florida Statutes",
        chapter_url=FL_CHAPTER_URL,
        chapter_label="Chapter 1",
        max_statutes=None,
    )

    assert len(rows) == 1
    assert rows[0].source_url != FL_CHAPTER_URL
    assert rows[0].structured_data["content_sha256"] == digest
    row_coverage = ledger.audit_parser_output_coverage([rows[0].to_dict()])
    assert row_coverage["complete"] is True
    assert row_coverage["covered_by_content_digest"] == 1

    enriched = scraper._enrich_statute_structure(rows[0])
    jsonld_dir = tmp_path / "jsonld"
    jsonld_dir.mkdir()
    [written] = _write_state_jsonld_files(
        [
            {
                "state_code": "FL",
                "state_name": "Florida",
                "statutes": [enriched.to_dict()],
            }
        ],
        jsonld_dir,
    )
    payload = json.loads(Path(written).read_text(encoding="utf-8"))
    assert payload["provenance"]["content_sha256"] == digest
    jsonld_coverage = ledger.audit_canonical_jsonld_coverage(written)
    assert jsonld_coverage["complete"] is True
    assert jsonld_coverage["covered_by_content_digest"] == 1


@pytest.mark.anyio
async def test_florida_chapter_rows_fail_closed_without_exact_input_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = (
        "<div class='ChapterNumber'>CHAPTER 1</div>"
        "<div class='Section'><span class='SectionNumber'>1.99</span>"
        "<span class='CatchlineText'>Effect.</span>"
        "<span class='SectionBody'>It is.</span></div>"
    )
    scraper = FloridaScraper("FL", "Florida")
    scraper._state_law_acquisition_ledger = object()

    async def _fetch(url: str, timeout_seconds: int = 12) -> str:
        return html

    monkeypatch.setattr(scraper, "_fetch_official_fl_html", _fetch)

    with pytest.raises(RuntimeError, match="exact retained parser-input provenance"):
        await scraper._parse_chapter_sections(
            code_name="Florida Statutes",
            chapter_url=FL_CHAPTER_URL,
            chapter_label="Chapter 1",
            max_statutes=None,
        )


def test_florida_parser_does_not_truncate_long_or_short_enacted_text() -> None:
    long_body = "x" * 16050
    html = (
        "<div class='Section'><span class='SectionNumber'>1.98</span>"
        "<span class='CatchlineText'>Long section.</span>"
        f"<span class='SectionBody'>{long_body}</span></div>"
        "<div class='Section'><span class='SectionNumber'>1.99</span>"
        "<span class='CatchlineText'>Short section.</span>"
        "<span class='SectionBody'>Yes.</span></div>"
    )

    rows = parse_florida_chapter_html(html, chapter="CHAPTER 1")

    assert [row.section_number for row in rows] == ["1.98", "1.99"]
    assert len(rows[0].full_text) == len(long_body)
    assert rows[1].full_text == "Yes."


@pytest.mark.anyio
async def test_florida_transport_failure_uses_web_archiving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = FloridaScraper("FL", "Florida")

    async def _no_cache(url: str) -> bytes:
        return b""

    async def _recover(
        url: str,
        timeout_seconds: int = 12,
        content_validator=None,
    ) -> bytes:
        scraper._record_fetch_event(provider="web_archiving_fixture", success=True)
        return b"<html>archived official Florida page</html>"

    monkeypatch.setattr(scraper, "_load_page_bytes_from_any_cache", _no_cache)
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("unavailable")),
    )
    monkeypatch.setattr(scraper, "_fetch_page_content_with_archival_fallback", _recover)

    html = await scraper._fetch_official_fl_html(FL_CHAPTER_URL, timeout_seconds=1)

    assert "archived official Florida page" in html
    assert scraper._current_fetch_provider() == "web_archiving_fixture"


@pytest.mark.anyio
async def test_florida_full_mode_fails_closed_on_partial_title_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = FloridaScraper("FL", "Florida")

    async def _partial_titles(code_url: str):
        return [(scraper.official_title_url("I"), "Title I")]

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_discover_title_links", _partial_titles)

    with pytest.raises(RuntimeError, match="title enumeration did not close"):
        await scraper.scrape_code(
            "Florida Statutes",
            scraper.OFFICIAL_ENTRY_URL,
            max_statutes=None,
        )
    assert scraper._last_full_corpus_frontier["closed"] is False
    assert "49" in scraper._last_full_corpus_frontier["missing_titles"]


def test_florida_catalog_includes_current_title_xlix() -> None:
    scraper = FloridaScraper("FL", "Florida")
    last = scraper.official_title_catalog()[-1]

    assert last["title_number"] == "49"
    assert last["title_roman"] == "XLIX"
    assert "TEACHERS" in last["name"].upper()


def test_delaware_relative_and_non_numeric_chapter_links_are_preserved() -> None:
    html = """
    <div class="title-links">
      <a href="../title6/c002a/index.html">Article 2A. Leases</a>
    </div>
    <div class="title-links">
      <a href="../title6/c012_1/index.html">Chapter 12. False Claims</a>
    </div>
    """

    rows = title_link_rows(
        html,
        base_url="https://delcode.delaware.gov/title6/index.html",
    )

    assert [row["url"] for row in rows] == [
        "https://delcode.delaware.gov/title6/c002a/index.html",
        "https://delcode.delaware.gov/title6/c012_1/index.html",
    ]


@pytest.mark.anyio
async def test_delaware_article_descendant_frontier_is_traversed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = "https://delcode.delaware.gov/title6/c002a/index.html"
    child = "https://delcode.delaware.gov/title6/c002a/sc01/index.html"
    pages = {
        root: (
            "<div class='title-links'>"
            "<a href='../../title6/c002a/sc01/index.html'>Part 1. General</a>"
            "</div>"
        ),
        child: (
            "<div class='Section'><div class='SectionHead' id='2A-101'>"
            "§ 2A-101. Short title.</div><p>Valid.</p></div>"
        ),
    }
    scraper = DelawareScraper("DE", "Delaware")

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        scraper._record_fetch_event(provider="requests_direct", success=True)
        return pages.get(url, "")

    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)
    rows = await scraper._parse_chapter_sections(
        code_name="Delaware Code",
        chapter_url=root,
        chapter_label="Article 2A. Leases",
        max_statutes=None,
    )

    assert [row.section_number for row in rows] == ["2A-101"]
    assert rows[0].full_text == "Valid."
    assert rows[0].chapter_number == "2A"
    assert rows[0].source_url == f"{child}#2A-101"


def test_delaware_parser_does_not_truncate_long_or_short_enacted_text() -> None:
    long_body = "z" * 16050
    html = (
        "<div class='Section'><div class='SectionHead' id='101'>"
        "§ 101. Long.</div>"
        f"<p>{long_body}</p></div>"
        "<div class='Section'><div class='SectionHead' id='102'>"
        "§ 102. Short.</div><p>Yes.</p></div>"
    )

    rows = parse_delaware_chapter_html(
        html,
        source_url="https://delcode.delaware.gov/title1/c001/index.html",
    )

    assert [row.statute_id for row in rows] == ["DE-1-101", "DE-1-102"]
    assert len(rows[0].full_text) == len(long_body)
    assert rows[1].full_text == "Yes."


def test_delaware_table_only_section_is_retained_without_history() -> None:
    """Replay the substantive DOM shape retained for 10 Del. C. § 9707."""

    html = (
        "<div class='Section'><div class='SectionHead' id='9707'>"
        "§ 9707. Depositions in appeals.</div><p class='subsection'></p>"
        "<div class='code-table'><table id='9707-1'><tbody>"
        "<tr><td>For each deposition taken in an appeal from a justice</td>"
        "<td class='right bottom'>$\u2002.50</td></tr>"
        "<tr><td>But not more than $5.00 shall be allowed for depositions "
        "in 1 appeal.</td><td class='right'></td></tr>"
        "</tbody></table></div>"
        "Code 1852, § 2814; Code 1915, § 4871;"
        "</div>"
    )

    rows = parse_delaware_chapter_html(
        html,
        source_url="https://delcode.delaware.gov/title10/c097/index.html",
    )

    assert [row.statute_id for row in rows] == ["DE-10-9707"]
    assert rows[0].full_text == (
        "For each deposition taken in an appeal from a justice $ .50 "
        "But not more than $5.00 shall be allowed for depositions in 1 appeal."
    )
    assert "Code 1852" not in rows[0].full_text


@pytest.mark.anyio
async def test_delaware_transport_failure_uses_web_archiving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")

    async def _no_cache(url: str) -> bytes:
        return b""

    async def _recover(
        url: str,
        timeout_seconds: int = 6,
        content_validator=None,
    ) -> bytes:
        scraper._record_fetch_event(provider="web_archiving_fixture", success=True)
        return b"<html>archived official Delaware page</html>"

    monkeypatch.setattr(scraper, "_load_page_bytes_from_any_cache", _no_cache)
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("unavailable")),
    )
    monkeypatch.setattr(scraper, "_fetch_page_content_with_archival_fallback", _recover)

    html = await scraper._fetch_official_de_html(
        "https://delcode.delaware.gov/title1/index.html",
        timeout_seconds=1,
    )

    assert "archived official Delaware page" in html
    assert scraper._current_fetch_provider() == "web_archiving_fixture"


@pytest.mark.anyio
async def test_delaware_full_mode_fails_closed_on_partial_title_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")

    async def _partial_titles():
        return [(scraper.official_title_url(1), "Title 1")]

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_discover_title_links", _partial_titles)

    with pytest.raises(RuntimeError, match="title enumeration did not close"):
        await scraper.scrape_code(
            "Delaware Code",
            scraper.OFFICIAL_ENTRY_URL,
            max_statutes=None,
        )
    assert scraper._last_full_corpus_frontier["closed"] is False
    assert "31" in scraper._last_full_corpus_frontier["missing_titles"]


@pytest.mark.anyio
async def test_delaware_full_mode_is_uncapped_and_closes_frontier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")
    received_limits: list[Optional[int]] = []
    plural_calls: list[tuple[str, list[str]]] = []

    async def _titles():
        return [
            (scraper.official_title_url(number), f"Title {number}")
            for number in range(1, scraper.OFFICIAL_TITLE_COUNT + 1)
        ]

    async def _chapters(title_url: str, *, _html: str | None = None):
        assert _html == f"retained:{title_url}"
        title = scraper._title_number_from_url(title_url)
        return [(f"https://delcode.delaware.gov/title{title}/c001/index.html", "Chapter 1")]

    async def _frontier(urls, *, frontier_name: str):
        requested = list(urls)
        plural_calls.append((frontier_name, requested))
        return {
            url: (f"retained:{url}", {}, "test_plural")
            for url in requested
        }

    async def _parse(
        *,
        code_name: str,
        chapter_url: str,
        chapter_label: str,
        max_statutes: Optional[int] = None,
        _sibling_frontier_urls: set[str] | None = None,
        _html: str | None = None,
        _page_row_provenance=None,
        _retrieval_provider: str = "",
    ):
        assert _html == f"retained:{chapter_url}"
        assert _retrieval_provider == "test_plural"
        received_limits.append(max_statutes)
        title = scraper._title_number_from_url(chapter_url)
        return [
            NormalizedStatute(
                state_code="DE",
                state_name="Delaware",
                statute_id=f"DE-{title}-{number}",
                code_name=code_name,
                title_number=title,
                chapter_number="1",
                section_number=str(number),
                section_name="Official section",
                full_text="Law.",
                source_url=f"{chapter_url}#{number}",
                official_cite=f"{title} Del. C. § {number}",
                structured_data={"source_authority_class": "official"},
            )
            for number in range(1, 6)
        ]

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_discover_title_links", _titles)
    monkeypatch.setattr(scraper, "_discover_chapter_links", _chapters)
    monkeypatch.setattr(scraper, "_fetch_de_html_frontier", _frontier)
    monkeypatch.setattr(scraper, "_parse_chapter_sections", _parse)

    rows = await scraper.scrape_code(
        "Delaware Code",
        scraper.OFFICIAL_ENTRY_URL,
        max_statutes=None,
    )

    assert len(rows) == 155
    assert received_limits == [None] * scraper.OFFICIAL_TITLE_COUNT
    assert [name for name, _urls in plural_calls] == [
        "title catalog",
        "chapter catalog",
    ]
    assert [len(urls) for _name, urls in plural_calls] == [31, 31]
    assert scraper._last_full_corpus_frontier["closed"] is True
    assert all(row.structured_data["official_frontier_closed"] is True for row in rows)


@pytest.mark.anyio
async def test_delaware_full_mode_rejects_an_unparsed_active_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")
    html = (
        "<div class='Section'><div class='SectionHead' id='101'>"
        "§ 101. Active section.</div><p></p></div>"
    )

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        scraper._record_fetch_event(provider="requests_direct", success=True)
        return html

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)

    with pytest.raises(RuntimeError, match="omitted active official sections"):
        await scraper._parse_chapter_sections(
            code_name="Delaware Code",
            chapter_url="https://delcode.delaware.gov/title1/c001/index.html",
            chapter_label="Chapter 1",
            max_statutes=None,
        )


@pytest.mark.anyio
async def test_delaware_expired_section_history_is_not_an_active_parser_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")
    html = (
        "<div id='CodeBody'>"
        "<div class='Section'><div class='SectionHead' id='2509E'>"
        "§ 2509E. Maximum rate of interest on debts incurred before the "
        "shutdown</div>"
        "<a href='https://legis.delaware.gov/SessionLaws?volume=82&amp;chapter=2'>"
        "82 Del. Laws, c. 2, § 1</a>"
        "<a href='https://legis.delaware.gov/SessionLaws?volume=82&amp;chapter=78'>"
        "expired by operation of 82 Del. Laws, c. 78, § 9, eff. July 1, 2019"
        "</a></div>"
        "<div class='Section'><div class='SectionHead' id='2510E'>"
        "§ 2510E. Enforcement.</div>"
        "<p>The Attorney General shall enforce this chapter.</p></div>"
        "</div>"
    )

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        scraper._record_fetch_event(provider="requests_direct", success=True)
        return html

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)

    rows = await scraper._parse_chapter_sections(
        code_name="Delaware Code",
        chapter_url="https://delcode.delaware.gov/title6/c025e/index.html",
        chapter_label="Chapter 25E",
        max_statutes=None,
    )

    assert [row.section_number for row in rows] == ["2510E"]


@pytest.mark.anyio
async def test_delaware_retained_section_id_variants_close_parser_parity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")
    html = (
        "<div id='CodeBody'>"
        "<div class='Section'><div class='SectionHead' id='§\u20092735'>"
        "§ §\u20092735. Remedies.</div><p>Consumers may recover damages.</p>"
        "</div>"
        "<div class='Section'><div class='SectionHead' id='17-1201 '>"
        "§ 17-1201 . Law applicable.</div><p>This chapter applies.</p></div>"
        "<div class='Section'><div class='SectionHead' id='1811. '>"
        "§ 1811. . Quota management system implementation.</div>"
        "<p>The quota system requires legislative action.</p></div>"
        "<div class='Section'><div class='SectionHead' id='704'>"
        "§ 704. Reserved power of State to amend or repeal this chapter.</div>"
        "<p>The General Assembly retains this power.</p></div>"
        "<div class='Section'><div class='SectionHead' id='1355'>"
        "§ 1355. Finality [Repealed effective Oct. 21, 2026].</div>"
        "<p>An applicant may appeal before the operative repeal date.</p></div>"
        "<div class='Section'><div class='SectionHead' id='3149, 3150'>"
        "§§ 3149, 3150. Jurisdiction and appeals [Transferred].</div>"
        "<p>Transferred.</p></div>"
        "</div>"
    )

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        scraper._record_fetch_event(provider="requests_direct", success=True)
        return html

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)

    rows = await scraper._parse_chapter_sections(
        code_name="Delaware Code",
        chapter_url="https://delcode.delaware.gov/title6/c027/sc04/index.html",
        chapter_label="Subchapter IV",
        max_statutes=None,
    )

    assert [row.section_number for row in rows] == [
        "2735",
        "17-1201",
        "1811",
        "704",
        "1355",
    ]


@pytest.mark.anyio
async def test_delaware_all_inactive_page_does_not_enter_manual_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")
    html = (
        "<div id='CodeBody'><div class='Section'>"
        "<div class='SectionHead' id='3201-3204'>"
        "§§ 3201-3204. Compact provisions [Repealed].</div>"
        "<p>Repealed by 77 Del. Laws, c. 357, § 1.</p>"
        "</div></div>"
    )

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        scraper._record_fetch_event(provider="requests_direct", success=True)
        return html

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)

    rows = await scraper._parse_chapter_sections(
        code_name="Delaware Code",
        chapter_url="https://delcode.delaware.gov/title3/c032/index.html",
        chapter_label="Chapter 32",
        max_statutes=None,
    )

    assert rows == []


@pytest.mark.anyio
async def test_delaware_verified_superseded_index_is_covered_by_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = "https://delcode.delaware.gov/title5/c007/index.html"
    old = "https://delcode.delaware.gov/title5/c007/sc07/index.html"
    replacement = "https://delcode.delaware.gov/title5/c007/sc07_1/index.html"
    pages = {
        root: (
            "<div class='title-links'><a href='sc07/index.html'>"
            "Subchapter VII. Merger or Consolidation with Out-Of-State Banks"
            "</a></div>"
            "<div class='title-links'><a href='sc07_1/index.html'>"
            "Subchapter VII. Merger, Consolidation or Conversion with or of "
            "Out-of-State Trust Companies</a></div>"
        ),
        old: (
            "<div id='TitleHead'><h1>TITLE 5</h1><h4>Banking</h4>"
            "<h3>CHAPTER 7</h3><h4>Subchapter VII. Merger or Consolidation "
            "with Out-Of-State Banks</h4></div>"
            "<div id='CodeBody'><a href='https://legis.delaware.gov/SessionLaws?"
            "volume=85&amp;chapter=337'>85 Del. Laws, c. 337, § 12</a>; </div>"
        ),
        replacement: (
            "<div id='TitleHead'><h1>TITLE 5</h1><h4>Banking</h4>"
            "<h3>CHAPTER 7</h3><h4>Subchapter VII. Current</h4></div>"
            "<div class='Section'><div class='SectionHead' id='795'>"
            "§ 795. Definitions.</div><p>As used in this subchapter, bank "
            "means an authorized banking institution.</p></div>"
        ),
    }
    scraper = DelawareScraper("DE", "Delaware")
    singleton_calls: list[str] = []
    plural_calls: list[list[str]] = []

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        singleton_calls.append(url)
        scraper._record_fetch_event(provider="requests_direct", success=True)
        return pages.get(url, "")

    async def _fetch_frontier(urls, *, frontier_name: str):
        requested = list(urls)
        plural_calls.append(requested)
        return {
            url: (pages[url], {}, "requests_direct")
            for url in requested
        }

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)
    monkeypatch.setattr(scraper, "_fetch_de_html_frontier", _fetch_frontier)

    rows = await scraper._parse_chapter_sections(
        code_name="Delaware Code",
        chapter_url=root,
        chapter_label="Chapter 7",
        max_statutes=None,
    )

    assert [row.section_number for row in rows] == ["795"]
    assert rows[0].source_url == f"{replacement}#795"
    assert rows[0].structured_data["official_supersedes_empty_index_url"] == old
    assert rows[0].structured_data["official_descendant_pages_visited"] == 2
    assert singleton_calls == [root]
    assert plural_calls == [[old, replacement]]


@pytest.mark.anyio
async def test_delaware_superseded_index_requires_replacement_in_parent_frontier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = "https://delcode.delaware.gov/title5/c007/index.html"
    scraper = DelawareScraper("DE", "Delaware")

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        scraper._record_fetch_event(provider="requests_direct", success=True)
        return (
            "<div class='title-links'><a href='sc07/index.html'>"
            "Subchapter VII. Merger or Consolidation with Out-Of-State Banks"
            "</a></div>"
        )

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)

    with pytest.raises(RuntimeError, match="replacement was absent"):
        await scraper._parse_chapter_sections(
            code_name="Delaware Code",
            chapter_url=root,
            chapter_label="Chapter 7",
            max_statutes=None,
        )


@pytest.mark.anyio
async def test_delaware_citation_only_page_without_parent_binding_still_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = "https://delcode.delaware.gov/title5/c007/sc07/index.html"
    scraper = DelawareScraper("DE", "Delaware")
    html = (
        "<div id='TitleHead'><h1>TITLE 5</h1><h4>Banking</h4>"
        "<h3>CHAPTER 7</h3><h4>Subchapter VII. Merger or Consolidation "
        "with Out-Of-State Banks</h4></div>"
        "<div id='CodeBody'><a href='https://legis.delaware.gov/SessionLaws?"
        "volume=85&amp;chapter=337'>85 Del. Laws, c. 337, § 12</a>; </div>"
    )

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        scraper._record_fetch_event(provider="requests_direct", success=True)
        return html

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)

    with pytest.raises(RuntimeError, match="exposed no section frontier"):
        await scraper._parse_chapter_sections(
            code_name="Delaware Code",
            chapter_url=old,
            chapter_label=(
                "Subchapter VII. Merger or Consolidation with Out-Of-State Banks"
            ),
            max_statutes=None,
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("part", "subject"),
    [
        ("7", "Advice of International Sight Draft"),
        ("8", "Miscellaneous"),
    ],
)
async def test_delaware_exact_vacated_ucc_part_is_a_closed_empty_frontier(
    monkeypatch: pytest.MonkeyPatch,
    part: str,
    subject: str,
) -> None:
    page_url = f"https://delcode.delaware.gov/title6/c003/sc0{part}/index.html"
    scraper = DelawareScraper("DE", "Delaware")
    html = (
        "<div id='TitleHead'><h1>TITLE 6</h1><h3>Commerce and Trade</h3>"
        "<h2>SUBTITLE I</h2><h3>Uniform Commercial Code</h3>"
        "<h3>ARTICLE 3. Negotiable Instruments</h3>"
        f"<h4>Part {part}</h4><h4>{subject}</h4></div>"
        "<div id='CodeBody'></div>"
    )

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        scraper._record_fetch_event(provider="requests_direct", success=True)
        return html

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)

    rows = await scraper._parse_chapter_sections(
        code_name="Delaware Code",
        chapter_url=page_url,
        chapter_label=f"Part {part} {subject}",
        max_statutes=None,
        _sibling_frontier_urls={page_url},
    )

    assert rows == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("body", "siblings"),
    [
        ("<div id='CodeBody'></div>", set()),
        ("<div id='CodeBody'>Unexpected statutory text.</div>", {
            "https://delcode.delaware.gov/title6/c003/sc07/index.html"
        }),
    ],
)
async def test_delaware_vacated_ucc_part_remains_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    body: str,
    siblings: set[str],
) -> None:
    page_url = "https://delcode.delaware.gov/title6/c003/sc07/index.html"
    scraper = DelawareScraper("DE", "Delaware")
    html = (
        "<div id='TitleHead'><h1>TITLE 6</h1><h3>Commerce and Trade</h3>"
        "<h2>SUBTITLE I</h2><h3>Uniform Commercial Code</h3>"
        "<h3>ARTICLE 3. Negotiable Instruments</h3><h4>Part 7</h4>"
        "<h4>Advice of International Sight Draft</h4></div>"
        f"{body}"
    )

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        scraper._record_fetch_event(provider="requests_direct", success=True)
        return html

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)

    with pytest.raises(RuntimeError, match="exposed no section frontier"):
        await scraper._parse_chapter_sections(
            code_name="Delaware Code",
            chapter_url=page_url,
            chapter_label="Part 7 Advice of International Sight Draft",
            max_statutes=None,
            _sibling_frontier_urls=siblings,
        )
