"""Hermetic tests for Vaquill-adapted official state bulk/parser adapters."""

from __future__ import annotations

import zipfile
from pathlib import Path

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.florida_chapter import (
    band_for,
    chapter_number_from_url,
    padded,
    parse_florida_chapter_html,
    title_romans,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.indiana_bulk import (
    parse_indiana_bulk_zip,
    zip_url,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_jersey_bulk import (
    parse_new_jersey_bulk_zip,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.ohio_chapter import (
    parse_ohio_chapter_html,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.utah_title_xml import (
    discover_title_xml_urls_from_html,
    parse_utah_xml_document,
    title_xml_url,
)


OH_CHAPTER_HTML = """
<html><body>
<div>Chapter 2903 | Homicide and assault</div>
<div>Section 2903.01 | Aggravated murder.</div>
<div>Effective: March 22, 2019</div>
<div>Latest Legislation: HB 136</div>
<div>PDF: Download Authenticated PDF</div>
<div>No person shall purposely, and with prior calculation and design, cause the death of another or the unlawful termination of another's pregnancy.</div>
<div>Section 2903.02 | Murder [Repealed].</div>
<div>This section was repealed by the general assembly and must not be admitted.</div>
<div>Section 2903.04 | Involuntary manslaughter.</div>
<div>No person shall cause the death of another as a proximate result of the offender's committing or attempting to commit a felony.</div>
</body></html>
"""

UT_TITLE_XML = """
<title number="76">
  <catchline>Utah Criminal Code</catchline>
  <chapter number="76-5">
    <catchline>Offenses Against the Person</catchline>
    <part number="76-5-2">
      <catchline>Criminal Homicide</catchline>
      <section number="76-5-203">
        <histories><history>Amended by Chapter 99, 2025 General Session</history></histories>
        <catchline>Murder.</catchline>
        Actor commits murder if the actor intentionally or knowingly causes the death of another individual.
        <subsection number="76-5-203(1)">(1) As used in this section, actor means a person.</subsection>
      </section>
    </part>
  </chapter>
</title>
"""

FL_CHAPTER_HTML = """
<html><body>
<div class="Part"><span class="PartNumber">PART I</span>
<div class="Section">
  <span class="SectionNumber">782.04</span>
  <span class="CatchlineText">Murder.</span>
  <div class="SectionBody"><p>(1) The unlawful killing of a human being when perpetrated from a premeditated design to effect the death of the person killed is murder in the first degree.</p></div>
  <div class="History">History.—s. 1, ch. 71-136</div>
</div>
<div class="Section">
  <span class="SectionNumber">782.05</span>
  <span class="CatchlineText">Abandoned murder [Repealed by s. 7, ch. 99-3.]</span>
  <div class="SectionBody"><p>Repealed text that must not be admitted as current law.</p></div>
</div>
</div>
</body></html>
"""

NJ_RTF = r"""{\rtf1\ansi
\pard\s2 TITLE 2C THE NEW JERSEY CODE OF CRIMINAL JUSTICE
\pard\s3 2C:11-3. Murder.
\pard A person is guilty of murder if the actor purposely causes death or serious bodily injury resulting in death.
\pard\s3 2C:11-4. Manslaughter.
\pard Criminal homicide constitutes manslaughter when it is committed recklessly.
}"""

IN_TITLE_HTML = """
<div class="title" id="35"><span id="ic_number">IC 35</span><span id="shortdescription">TITLE 35 Criminal Law and Procedure</span></div>
<div class="chapter" id="35-42-1"><span id="shortdescription">CHAPTER 1. HOMICIDE</span></div>
<div class="section" id="35-42-1-1"><span id="ic_number">IC 35-42-1-1</span><span id="shortdescription">Murder</span></div>
<p>Sec. 1. A person who:</p>
<p>(1) knowingly or intentionally kills another human being;</p>
<p>commits murder, a felony.</p>
<div class="section" id="35-42-1-0.5"><span id="ic_number">IC 35-42-1-0.5</span><span id="shortdescription">Repealed</span></div>
<p>Repealed by P.L.1-1990.</p>
"""


def test_ohio_chapter_inline_skips_repealed_and_strips_trailers() -> None:
    rows = parse_ohio_chapter_html(
        OH_CHAPTER_HTML,
        title_num="29",
        chapter_num="2903",
        code_name="Ohio Revised Code",
    )
    numbers = [row.section_number for row in rows]
    assert numbers == ["2903.01", "2903.04"]
    assert "prior calculation" in rows[0].full_text
    assert "Effective:" not in rows[0].full_text
    assert "Download Authenticated PDF" not in rows[0].full_text
    assert rows[0].structured_data["source_authority_class"] == "official"
    assert "codes.ohio.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url


def test_utah_title_xml_skips_histories_and_walks_parts() -> None:
    rows = parse_utah_xml_document(UT_TITLE_XML, code_name="Utah Code")
    assert len(rows) == 1
    assert rows[0].section_number == "76-5-203"
    assert "intentionally or knowingly" in rows[0].full_text
    assert "Amended by Chapter 99" not in rows[0].full_text
    assert "(1) As used in this section" in rows[0].full_text
    assert rows[0].chapter_number == "76-5"
    assert "le.utah.gov" in rows[0].source_url or rows[0].source_url.endswith("/xcode/")
    assert "justia" not in rows[0].source_url


def test_utah_title_xml_url_discovery() -> None:
    html = '<a href="/xcode/Title76/76.html?v=C76_2025050720250507">Title 76</a>'
    urls = discover_title_xml_urls_from_html(html)
    assert urls["76"] == "https://le.utah.gov/xcode/Title76/C76_2025050720250507.xml"
    assert title_xml_url("3", "C3_1800010118000101").startswith("https://le.utah.gov/xcode/Title3/")


def test_florida_chapter_parser_skips_repealed_and_history() -> None:
    assert band_for("782") == "0700-0799"
    assert padded("782") == "0782"
    assert chapter_number_from_url(
        "https://www.leg.state.fl.us/Statutes/index.cfm?App_mode=Display_Statute&URL=0700-0799/0782/0782.html"
    ) == "782"
    romans = title_romans('href="index.cfm?App_mode=Display_Index&Title_Request=XLVI"')
    assert romans == ["XLVI"]
    rows = parse_florida_chapter_html(FL_CHAPTER_HTML, chapter="782", title_roman="XLVI")
    assert len(rows) == 1
    assert rows[0].section_number == "782.04"
    assert "premeditated design" in rows[0].full_text
    assert "71-136" not in rows[0].full_text
    assert rows[0].structured_data["part_roman"] == "I"
    assert "leg.state.fl.us" in rows[0].source_url
    assert "justia" not in rows[0].source_url
    sibling = parse_florida_chapter_html(
        "<div class='Section'><span class='SectionNumber'>775.01</span>"
        "<span class='Catchline'>Common law of England.</span>"
        "<p>The common law of England in relation to crimes shall be of full force.</p></div>",
        chapter="775",
    )
    assert len(sibling) == 1
    assert "full force" in sibling[0].full_text


def test_new_jersey_rtf_zip_parses_style_tagged_sections(tmp_path: Path) -> None:
    zip_path = tmp_path / "STATUTES-TEXT.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("STATUTES.RTF", NJ_RTF)
    rows = parse_new_jersey_bulk_zip(zip_path, max_statutes=4)
    assert [row.section_number for row in rows] == ["2C:11-3", "2C:11-4"]
    assert "purposely causes death" in rows[0].full_text
    assert rows[0].official_cite == "N.J. Stat. § 2C:11-3"
    assert rows[0].structured_data["source_kind"] == "official_new_jersey_statutes_rtf"
    assert "pub.njleg.state.nj.us" == rows[0].structured_data["bulk_host"]
    assert "justia" not in rows[0].source_url


def test_indiana_html_zip_skips_repealed(tmp_path: Path) -> None:
    assert zip_url(2026) == "https://iga.in.gov/ic/2026/2026-Indiana-Code-html.zip"
    zip_path = tmp_path / "2026-Indiana-Code-html.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("2026_Indiana_Code_HTML/35.html", IN_TITLE_HTML)
    rows = parse_indiana_bulk_zip(zip_path, max_statutes=8)
    assert len(rows) == 1
    assert rows[0].section_number == "35-42-1-1"
    assert "knowingly or intentionally kills" in rows[0].full_text
    assert "iga.in.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url


def test_nj_scrape_code_uses_configured_bulk_zip(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_jersey import NewJerseyScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    zip_path = tmp_path / "STATUTES-TEXT.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("STATUTES.RTF", NJ_RTF)
    monkeypatch.setenv("NEW_JERSEY_BULK_ZIP", str(zip_path))
    scraper = NewJerseyScraper("NJ", "New Jersey")

    async def _should_not_run(*_args, **_kwargs):
        raise AssertionError("LIS index must not run when official RTF zip is configured")

    monkeypatch.setattr(scraper, "_scrape_official_index", _should_not_run)
    rows = asyncio.run(
        scraper.scrape_code("New Jersey Statutes", "https://example.invalid", max_statutes=2)
    )
    assert len(rows) == 2
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_utah_scrape_code_uses_configured_title_xml(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.utah import UtahScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    xml_path = tmp_path / "Title76.xml"
    xml_path.write_text(UT_TITLE_XML, encoding="utf-8")
    monkeypatch.setenv("UTAH_TITLE_XML", str(xml_path))
    scraper = UtahScraper("UT", "Utah")

    async def _should_not_run(*_args, **_kwargs):
        raise AssertionError("live XML crawl must not run when UTAH_TITLE_XML is set")

    monkeypatch.setattr(scraper, "_scrape_official_xml_code_tree", _should_not_run)
    rows = asyncio.run(scraper.scrape_code("Utah Code", "https://example.invalid", max_statutes=4))
    assert len(rows) == 1
    assert rows[0].section_number == "76-5-203"


def test_ohio_official_tree_uses_chapter_inline(monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.ohio import OhioScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    scraper = OhioScraper("OH", "Ohio")
    toc = '<a href="/ohio-revised-code/title-29">Title 29</a>'
    title = '<a href="/ohio-revised-code/chapter-2903">Chapter 2903</a>'

    async def _fake_fetch(url: str, timeout_seconds: int = 20):
        del timeout_seconds
        if url.endswith("/ohio-revised-code"):
            return toc
        if "title-29" in url:
            return title
        if "chapter-2903" in url:
            return OH_CHAPTER_HTML
        return ""

    monkeypatch.setattr(scraper, "_fetch_page_content_with_archival_fallback", _fake_fetch)
    rows = asyncio.run(
        scraper._scrape_official_title_chapter_section_tree("Ohio Revised Code", max_statutes=8)
    )
    assert [row.section_number for row in rows] == ["2903.01", "2903.04"]
    assert rows[0].structured_data["source_kind"] == "official_ohio_chapter_inline"


def test_florida_parse_chapter_uses_section_body(monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.florida import FloridaScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    scraper = FloridaScraper("FL", "Florida")

    async def _fake_html(url: str, timeout_seconds: int = 12):
        del url, timeout_seconds
        return FL_CHAPTER_HTML

    monkeypatch.setattr(scraper, "_fetch_official_fl_html", _fake_html)
    chapter_url = (
        "https://www.leg.state.fl.us/Statutes/index.cfm"
        "?App_mode=Display_Statute&URL=0700-0799/0782/0782.html"
    )
    rows = asyncio.run(
        scraper._parse_chapter_sections(
            code_name="Florida Statutes",
            chapter_url=chapter_url,
            chapter_label="Chapter 782",
            max_statutes=4,
        )
    )
    assert len(rows) == 1
    assert rows[0].section_number == "782.04"
    assert rows[0].structured_data["source_kind"] == "official_florida_chapter_html"


def test_indiana_scrape_code_uses_configured_bulk_zip(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.indiana import IndianaScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    zip_path = tmp_path / "ic.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("35.html", IN_TITLE_HTML)
    monkeypatch.setenv("INDIANA_BULK_ZIP", str(zip_path))
    scraper = IndianaScraper("IN", "Indiana")
    rows = asyncio.run(scraper.scrape_code("Indiana Code", "https://example.invalid", max_statutes=4))
    assert len(rows) == 1
    assert rows[0].section_number == "35-42-1-1"
    assert rows[0].structured_data["source_kind"] == "official_indiana_code_html_zip"
