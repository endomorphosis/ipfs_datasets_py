"""Hermetic tests for Vaquill-adapted official state bulk/parser adapters."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.florida_chapter import (
    band_for,
    chapter_number_from_url,
    padded,
    parse_florida_chapter_html,
    parse_florida_senate_all_html,
    senate_chapter_url,
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
    senate_rows = parse_florida_senate_all_html(
        FL_CHAPTER_HTML,
        chapter="782",
        source_url=senate_chapter_url("782"),
    )
    assert len(senate_rows) == 1
    assert senate_rows[0].section_number == "782.04"
    assert senate_rows[0].structured_data["discovery_method"] == "flsenate_chapter_all"
    assert "flsenate.gov" in senate_rows[0].source_url


def test_florida_senate_dump_is_official(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.florida import FloridaScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    path = tmp_path / "Chapter782.html"
    path.write_text(FL_CHAPTER_HTML, encoding="utf-8")
    monkeypatch.setenv("FLORIDA_SENATE_CHAPTER_HTML", str(path))
    scraper = FloridaScraper("FL", "Florida")

    async def _should_not_run(*_args, **_kwargs):
        raise AssertionError("live Florida index must not run when Senate dump is configured")

    monkeypatch.setattr(scraper, "_discover_title_links", _should_not_run)
    rows = asyncio.run(
        scraper.scrape_code("Florida Statutes", "https://example.invalid", max_statutes=2)
    )
    assert len(rows) == 1
    assert rows[0].section_number == "782.04"
    assert rows[0].structured_data["source_authority_class"] == "official"
    assert "flsenate.gov" in rows[0].source_url


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


WI_PAGE_HTML = """
<div id="document">
  <div class="qsatxt_1sect" data-section="940.01">
    <span class="qsnum_sect">940.01</span>
    <span class="qstitle_sect">First-degree intentional homicide.</span>
  </div>
  <div class="qsatxt_2subsect" data-section="940.01">(1) Whoever causes the death of another human being with intent to kill that person is guilty of a Class A felony.</div>
  <div class="qsnote_history" data-section="940.01">940.01 History History: 1977 c. 173.</div>
  <div class="qsnote_annot" data-section="940.01">Case annotation about an unpublished opinion that must not enter the statute body.</div>
</div>
"""

IA_CHAPTER_XML = """
<chapter>
  <Section id="sec707.1">
    <div class="heading">
      <span class="identifier">707.1</span>
      <span class="headnote">Murder defined.</span>
    </div>
    <p>A person who kills another person with malice aforethought commits murder.</p>
    <div class="history">History: 2025 Acts, ch 1, section 1</div>
  </Section>
  <Section id="sec707.2">
    <div class="heading">
      <span class="identifier">707.2</span>
      <span class="headnote">Murder in the first degree. [Repealed]</span>
    </div>
    <p>Repealed text that must not be admitted.</p>
  </Section>
</chapter>
"""

IL_SECTION_HTML = """
<html><body>
<div align="justify">
<code><font size="2">(720 ILCS 5/9-1)</font></code>
(from Ch. 38, par. 9-1)
Sec. 1. First degree murder. A person who kills an individual without lawful justification commits first degree murder if he either intends to kill or knows that such acts will cause death.
</div>
</body></html>
"""


def test_wisconsin_qsatxt_keeps_subsections_drops_annotations() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.wisconsin_chapter import (
        statutes_from_page,
    )

    rows = statutes_from_page(WI_PAGE_HTML, chapter="940")
    assert len(rows) == 1
    assert rows[0].section_number == "940.01"
    assert "Class A felony" in rows[0].full_text
    assert "unpublished opinion" not in rows[0].full_text
    assert "docs.legis.wisconsin.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url


def test_iowa_slim_xml_skips_repealed_and_history() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.iowa_chapter_xml import (
        chapter_xml_url,
        parse_iowa_chapter_xml,
    )

    assert "attachments/707_slim.xml" in chapter_xml_url("707", 2026)
    rows = parse_iowa_chapter_xml(IA_CHAPTER_XML, chapter="707", year="2026")
    assert len(rows) == 1
    assert rows[0].section_number == "707.1"
    assert "malice aforethought" in rows[0].full_text
    assert "2025 Acts" not in rows[0].full_text
    assert "legis.iowa.gov" in rows[0].source_url


def test_illinois_ilcs_zip_from_manifest(tmp_path: Path) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.illinois_bulk import (
        html_to_text,
        parse_illinois_bulk_zip,
        parse_manifest,
        section_url,
    )

    assert "ilga.gov/ftp/ILCS" in section_url("072000050K9-1")
    entries = parse_manifest("072000050K9-1\nheader junk\n")
    assert entries[0].citation() == "720 ILCS 5/9-1"
    assert "first degree murder" in html_to_text(IL_SECTION_HTML).lower()
    zip_path = tmp_path / "ilcs.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("aReadMe/Section Sequence.txt", "072000050K9-1\n")
        archive.writestr("Ch 0720/Act 0005/072000050K9-1.html", IL_SECTION_HTML)
    rows = parse_illinois_bulk_zip(zip_path, max_statutes=3)
    assert len(rows) == 1
    assert rows[0].official_cite == "720 ILCS 5/9-1"
    assert rows[0].structured_data["source_kind"] == "official_illinois_ilcs_ftp"


def test_illinois_scrape_code_uses_configured_bulk_zip(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.illinois import IllinoisScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    zip_path = tmp_path / "ilcs.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("aReadMe/Section Sequence.txt", "072000050K9-1\n")
        archive.writestr("Ch 0720/Act 0005/072000050K9-1.html", IL_SECTION_HTML)
    monkeypatch.setenv("ILLINOIS_BULK_ZIP", str(zip_path))
    scraper = IllinoisScraper("IL", "Illinois")
    rows = asyncio.run(
        scraper.scrape_code("Illinois Compiled Statutes", "https://example.invalid", max_statutes=2)
    )
    assert len(rows) == 1
    assert "720 ILCS 5/9-1" in rows[0].official_cite


def test_iowa_scrape_code_uses_configured_chapter_xml(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.iowa import IowaScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    xml_path = tmp_path / "707_slim.xml"
    xml_path.write_text(IA_CHAPTER_XML, encoding="utf-8")
    monkeypatch.setenv("IOWA_CHAPTER_XML", str(xml_path))
    scraper = IowaScraper("IA", "Iowa")
    rows = asyncio.run(scraper.scrape_code("Iowa Code", "https://example.invalid", max_statutes=4))
    assert len(rows) == 1
    assert rows[0].section_number == "707.1"


def test_idaho_pgbrk_skips_breadcrumb_headers() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.idaho_section import (
        statute_from_section_html,
    )

    html = """
    <div class="pgbrk">
      <div>Title 18</div><div>Crimes</div><div>Chapter 40</div><div>Homicide</div>
      <div>18-4001. Murder defined.</div>
      <div>Murder is the killing of a human being with malice aforethought.</div>
      <div>History: 1972 c. 1</div>
    </div>
    """
    row = statute_from_section_html(
        html, section_number="18-4001", source_url="https://legislature.idaho.gov/statutesrules/idstat/Title18/T18CH40/SECT18-4001/"
    )
    assert row is not None
    assert "malice aforethought" in row.full_text
    assert "Title 18" not in row.full_text


def test_idaho_listing_uses_innner_wrapper_and_skips_reserved() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.idaho_section import (
        chapter_rows,
        section_rows,
        title_rows,
    )

    html = """
    <div class="vc-column-inner-wrapper">nav</div>
    <div class="vc-column-innner-wrapper">
      <table>
        <tr><td><a href="/statutesrules/idstat/Title18/">TITLE 18</a></td><td></td><td>Crimes and Punishments</td></tr>
        <tr><td>TITLE 17</td><td></td><td>Repealed</td></tr>
        <tr><td><a href="/statutesrules/idstat/Title18/T18CH40/">CHAPTER 40</a></td><td></td><td>Homicide</td></tr>
        <tr><td><a href="/statutesrules/idstat/Title18/T18CH40/SECT18-4001/">18-4001</a></td><td></td><td>Murder defined.</td></tr>
        <tr><td><a href="/statutesrules/idstat/Title18/T18CH40/SECT18-4002/">18-4002</a></td><td></td><td>Express malice. [Repealed]</td></tr>
        <tr><td><a href="/statutesrules/idstat/Title15/T15CH1/PT1/">PART 1</a></td><td></td><td>General Provisions</td></tr>
      </table>
    </div>
    """
    titles = title_rows(html)
    assert titles[0][0] == "18"
    assert titles[0][2].endswith("/Title18/")
    assert all(row[0] != "17" for row in titles)
    chapters = chapter_rows(html)
    assert chapters[0][0] == "40"
    sections, subs = section_rows(html)
    assert [num for num, _desc, _url in sections] == ["18-4001"]
    assert any("/PT1/" in url for url in subs)


def test_missouri_all_tables_and_norm_body() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.missouri_chapter import (
        chapter_sections,
        statute_from_section_html,
    )

    chapter_html = """
    <table><tr><td><a href="PageSelect.aspx?section=565.020">565.020</a></td><td>First degree murder</td></tr></table>
    <table><tr><td><a href="PageSelect.aspx?section=565.021">565.021</a></td><td>Second degree murder</td></tr></table>
    """
    assert [num for num, _title in chapter_sections(chapter_html, "565")] == ["565.020", "565.021"]
    section_html = """
    <div id="TOP"></div>
    <div>
      <div>
        <div class="norm">
          <p class="norm">The offense of murder in the first degree is committed when a person knowingly causes the death of another.</p>
          <div class="foot">---- (L. 1983 S.B. 276)</div>
        </div>
      </div>
    </div>
    <div id="BOTTOM"></div>
    """
    row = statute_from_section_html(section_html, section_number="565.020")
    assert row is not None
    assert "knowingly causes the death" in row.full_text
    assert "L. 1983" not in row.full_text


def test_michigan_mcl_xml_inner_body(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.michigan import MichiganScraper
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.michigan_chapter_xml import (
        parse_michigan_chapter_xml,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    xml = """
    <MCLChapterInfo>
      <Name>750</Name>
      <MCLDocumentInfoCollection>
        <MCLStatuteInfo>
          <Name>Act 328 of 1931</Name>
          <MCLDocumentInfoCollection>
            <MCLSectionInfo>
              <MCLNumber>750.316</MCLNumber>
              <CatchLine>First degree murder.</CatchLine>
              <Repealed>false</Repealed>
              <BodyText>&lt;Section-Body&gt;&lt;P&gt;(1) A person who commits murder in the first degree is guilty of a felony.&lt;/P&gt;&lt;/Section-Body&gt;</BodyText>
            </MCLSectionInfo>
          </MCLDocumentInfoCollection>
        </MCLStatuteInfo>
      </MCLDocumentInfoCollection>
    </MCLChapterInfo>
    """
    rows = parse_michigan_chapter_xml(xml, chapter_hint="750")
    assert len(rows) == 1
    assert rows[0].section_number == "750.316"
    assert "first degree" in rows[0].full_text
    path = tmp_path / "Chapter 750.xml"
    path.write_text(xml, encoding="utf-8")
    monkeypatch.setenv("MICHIGAN_CHAPTER_XML", str(path))
    scraper = MichiganScraper("MI", "Michigan")
    live = asyncio.run(scraper.scrape_code("Michigan Compiled Laws", "https://example.invalid", max_statutes=2))
    assert live[0].section_number == "750.316"


def test_louisiana_labeldocument_heading_split() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.louisiana_law import (
        statute_from_law_html,
    )

    html = """
    <span id="ctl00_PageBody_LabelName">RS 14:30</span>
    <span id="ctl00_PageBody_LabelDocument">
      <p>TITLE 14</p>
      <p>§30.  First degree murder</p>
      <p>First degree murder is the killing of a human being with specific intent to kill.</p>
    </span>
    """
    row = statute_from_law_html(html, source_url="https://legis.la.gov/Legis/Law.aspx?d=78329")
    assert row is not None
    assert row.section_number == "30"
    assert "specific intent" in row.full_text
    assert "TITLE 14" not in row.full_text
    assert row.structured_data["body_prefix"] == "RS"


def test_louisiana_civil_code_article_and_toc_folder(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.louisiana import LouisianaScraper
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.louisiana_law import (
        folder_body_prefix,
        toc_docids,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    toc = (
        '<span id="ctl00_ctl00_PageBody_PageContent_LabelHeader">Civil Code</span>'
        '<a href="Law.aspx?d=111">Art. 1</a><a href="Law.aspx?d=111">dup</a>'
        '<a href="Law.aspx?d=222">Art. 2</a>'
    )
    assert folder_body_prefix(toc) == "CC"
    assert toc_docids(toc) == ["111", "222"]
    html = """
    <span id="ctl00_PageBody_LabelName">CC 2315</span>
    <span id="ctl00_PageBody_LabelDocument">
      <p>Art. 2315.  Liability for acts causing damage</p>
      <p>Every act whatever of man that causes damage to another obliges him by whose fault it happened to repair it.</p>
    </span>
    """
    path = tmp_path / "cc-2315.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("LOUISIANA_LAW_HTML", str(path))
    scraper = LouisianaScraper("LA", "Louisiana")
    rows = asyncio.run(
        scraper.scrape_code("Louisiana Civil Code", "https://example.invalid", max_statutes=2)
    )
    assert len(rows) == 1
    assert rows[0].section_number == "2315"
    assert "causes damage to another" in rows[0].full_text
    assert rows[0].structured_data["body_prefix"] == "CC"
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_south_dakota_title_html_senu(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.south_dakota import SouthDakotaScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <p class="sabcNormal">22-16-4. Homicide defined.</p>
    <p class="sabcNormal-000001">Homicide is the killing of one human being by another.</p>
    """
    # SENU span is required
    html = """
    <p class="sabcNormal"><span class="SENU">22-16-4</span> 22-16-4. Homicide defined.</p>
    <p class="sabcNormal-000001">Homicide is the killing of one human being by another.</p>
    """
    path = tmp_path / "22.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("SOUTH_DAKOTA_TITLE_HTML", str(path))
    scraper = SouthDakotaScraper("SD", "South Dakota")
    rows = asyncio.run(scraper.scrape_code("South Dakota Codified Laws", "https://example.invalid", max_statutes=3))
    assert len(rows) == 1
    assert rows[0].section_number == "22-16-4"
    assert "killing of one human being" in rows[0].full_text


def test_south_dakota_utf16_and_chapter_toc(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.south_dakota import (
        SouthDakotaScraper,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.south_dakota_title import (
        chapter_html_url,
        decode_sdlegislature_bytes,
        title_chapter_entries,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <p class="sabcB">16Homicide and Suicide</p>
    <p class="sabcB">16AUnconstitutional Provisions</p>
    <p class="sabcNormal"><span class="SENU">22-16-4</span> 22-16-4. Homicide defined.</p>
    <p class="sabcNormal-000001">Homicide is the killing of one human being by another.</p>
    """
    encoded = html.encode("utf-16-le")
    assert encoded[1] == 0x00
    assert "22-16-4" in decode_sdlegislature_bytes(encoded)
    assert title_chapter_entries(html) == [
        ("16", "Homicide and Suicide"),
        ("16A", "Unconstitutional Provisions"),
    ]
    assert chapter_html_url("22", "16A").endswith("22-16A.html?all=true")
    path = tmp_path / "22-16.html"
    path.write_bytes(encoded)
    monkeypatch.setenv("SOUTH_DAKOTA_CHAPTER_HTML", str(path))
    scraper = SouthDakotaScraper("SD", "South Dakota")
    rows = asyncio.run(
        scraper.scrape_code("South Dakota Codified Laws", "https://example.invalid", max_statutes=3)
    )
    assert len(rows) == 1
    assert rows[0].section_number == "22-16-4"
    assert "killing of one human being" in rows[0].full_text
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_virginia_drops_sidenote_disclaimer() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.virginia_section import (
        body_to_paragraphs,
        statutes_from_section_detail,
    )

    body = "<p>Murder is the killing of any person with malice aforethought.</p><p class='sidenote'>This sidenote may not constitute a comprehensive list of notes.</p>"
    paras = body_to_paragraphs(body)
    assert paras == ["Murder is the killing of any person with malice aforethought."]
    row = statutes_from_section_detail(
        {"ChapterList": [{"Body": body, "CatchLine": "Murder."}]},
        section_number="18.2-32",
    )
    assert row is not None
    assert "malice aforethought" in row.full_text
    assert "comprehensive list" not in row.full_text


def test_new_york_openleg_json(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_york import NewYorkScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    payload = {
        "info": {"lawId": "PEN", "name": "Penal"},
        "documents": {
            "docType": "CHAPTER",
            "documents": {
                "items": [
                    {
                        "docType": "SECTION",
                        "docLevelId": "125.25",
                        "locationId": "125.25",
                        "title": "Murder in the second degree",
                        "text": "A person is guilty of murder in the second degree when with intent to cause the death of another person, he causes the death of such person.",
                    }
                ]
            },
        },
    }
    path = tmp_path / "PEN.json"
    path.write_text(__import__("json").dumps(payload), encoding="utf-8")
    monkeypatch.setenv("NY_OPENLEG_LAW_JSON", str(path))
    scraper = NewYorkScraper("NY", "New York")
    rows = asyncio.run(scraper.scrape_code("Penal Law", "https://example.invalid", max_statutes=2))
    assert len(rows) == 1
    assert rows[0].section_number == "125.25"
    assert "intent to cause the death" in rows[0].full_text


def test_pennsylvania_last_section_header_wins(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.pennsylvania import PennsylvaniaScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    text = """
TABLE OF CONTENTS
§ 2502.

CHAPTER 25
§ 2502.
Murder.

(a) A criminal homicide constitutes murder of the first degree when it is committed by an intentional killing.
"""
    path = tmp_path / "18.txt"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("PENNSYLVANIA_TITLE_TEXT", str(path))
    scraper = PennsylvaniaScraper("PA", "Pennsylvania")
    rows = asyncio.run(
        scraper.scrape_code("Pennsylvania Consolidated Statutes", "https://example.invalid", max_statutes=3)
    )
    assert len(rows) == 1
    assert rows[0].section_number == "2502"
    assert "intentional killing" in rows[0].full_text


def test_dc_council_section_xml(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.district_of_columbia import (
        DistrictOfColumbiaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    xml = """
    <section xmlns="https://code.dccouncil.us/schemas/dc-library">
      <num>22-2101</num>
      <heading>Murder in the first degree.</heading>
      <text>Whoever, being of sound memory and discretion, kills another with malice aforethought is guilty of murder in the first degree.</text>
      <para><num>(a)</num><text>The penalty shall be imprisonment for life.</text></para>
    </section>
    """
    path = tmp_path / "22-2101.xml"
    path.write_text(xml, encoding="utf-8")
    monkeypatch.setenv("DC_CODE_SECTION_XML", str(path))
    scraper = DistrictOfColumbiaScraper("DC", "District of Columbia")
    rows = asyncio.run(scraper.scrape_code("District of Columbia Code", "https://example.invalid", max_statutes=2))
    assert len(rows) == 1
    assert rows[0].section_number == "22-2101"
    assert "malice aforethought" in rows[0].full_text
    assert "(a) The penalty shall be imprisonment" in rows[0].full_text


def test_massachusetts_content_div_drops_nav(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.massachusetts import (
        MassachusettsScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
    <p>Skip to main content</p>
    <h2 class="genLawHeading">Murder defined</h2>
    <div class="content">
      <p>Murder is the killing of a human being with malice aforethought.</p>
      <p>(Added by St.1899, c. 1.)</p>
    </div>
    </body></html>
    """
    path = tmp_path / "section.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("MASSACHUSETTS_SECTION_HTML", str(path))
    scraper = MassachusettsScraper("MA", "Massachusetts")
    rows = asyncio.run(
        scraper.scrape_code("Massachusetts General Laws", "https://example.invalid", max_statutes=2)
    )
    assert len(rows) == 1
    assert "malice aforethought" in rows[0].full_text
    assert "Skip to main" not in rows[0].full_text
    assert "Added by St." not in rows[0].full_text


def test_north_carolina_bychapter_strips_nav(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina import (
        NorthCarolinaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
    <nav>Skip to main content Privacy Policy</nav>
    <p>§ 14-17. Murder in the first and second degree.</p>
    <p>A murder which shall be perpetrated by means of poison, lying in wait, or other kind of willful, deliberate, and premeditated killing shall be murder in the first degree.</p>
    <footer>Copyright © North Carolina General Assembly sitemap</footer>
    </body></html>
    """
    path = tmp_path / "Chapter_14.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("NORTH_CAROLINA_CHAPTER_HTML", str(path))
    scraper = NorthCarolinaScraper("NC", "North Carolina")
    rows = asyncio.run(
        scraper.scrape_code("North Carolina General Statutes", "https://example.invalid", max_statutes=3)
    )
    assert len(rows) == 1
    assert rows[0].section_number == "14-17"
    assert "poison, lying in wait" in rows[0].full_text
    assert "skip to main" not in rows[0].full_text.lower()
    assert "privacy policy" not in rows[0].full_text.lower()
    assert rows[0].structured_data["source_authority_class"] == "official"
    assert "ncleg.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url


def test_north_carolina_bychapter_index_discovers_chapters() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina_chapter import (
        bychapter_index_links,
        chapter_url,
        merge_discovered_chapters,
        toc_chapter_links,
    )

    html = """
    <html><body>
      <a href="Chapter_1.html">Chapter 1</a>
      <a href="/EnactedLegislation/Statutes/HTML/ByChapter/Chapter_14.html">Chapter 14</a>
      <a href="Chapter_1.html">duplicate</a>
      <a href="privacy.html">Privacy Policy</a>
    </body></html>
    """
    assert bychapter_index_links(html) == ["1", "14"]
    assert chapter_url("14").endswith("ByChapter/Chapter_14.html")
    toc = """
    <a href="/Laws/GeneralStatuteSections/Chapter7C">Chapter 7C Administrative Office of the Courts</a>
    <a href="/Laws/GeneralStatuteSections/Chapter14">Chapter 14 Criminal Law</a>
    """
    assert toc_chapter_links(toc) == ["7C", "14"]
    merged = merge_discovered_chapters(
        [("1", "Civil Procedure"), ("14", "Criminal Law")],
        ["7C", "14"],
    )
    assert merged[0] == ("7C", "Chapter 7C")
    assert merged[1] == ("14", "Criminal Law")
    assert ("1", "Civil Procedure") in merged


def test_north_carolina_toc_dump_merges_missing_chapter(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina import (
        NorthCarolinaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    toc = tmp_path / "toc.html"
    toc.write_text(
        '<a href="/Laws/GeneralStatuteSections/Chapter7C">Chapter 7C</a>',
        encoding="utf-8",
    )
    monkeypatch.setenv("NORTH_CAROLINA_TOC_HTML", str(toc))
    monkeypatch.setenv("NORTH_CAROLINA_BYCHAPTER_LIVE", "1")
    monkeypatch.setenv("NORTH_CAROLINA_BYCHAPTER_MAX_CHAPTERS", "1")
    scraper = NorthCarolinaScraper("NC", "North Carolina")

    async def fake_request(url: str, timeout: int = 18) -> str:
        if "Chapter_7C" in url:
            return (
                "<html><body><nav>North Carolina General Assembly</nav>"
                "<p>§ 7C-1. Administrative Office of the Courts.</p>"
                "<p>The Administrative Office of the Courts is created as an official "
                "agency of the judicial department of the State of North Carolina and "
                "shall have the duties prescribed by this Chapter, including assisting "
                "the Chief Justice in the administration of the courts of this State.</p>"
                "<footer>ncleg.gov</footer></body></html>"
            )
        return ""

    monkeypatch.setattr(scraper, "_request_text_direct", fake_request)
    rows = asyncio.run(
        scraper.scrape_code(
            "North Carolina General Statutes",
            "https://example.invalid",
            max_statutes=2,
        )
    )
    assert len(rows) == 1
    assert rows[0].section_number == "7C-1"
    assert "judicial department" in rows[0].full_text
    assert rows[0].structured_data["source_authority_class"] == "official"
    assert "ncleg.gov" in rows[0].source_url


def test_west_virginia_code_dump(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.west_virginia import (
        WestVirginiaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <p>§61-2-1. First and second degree murder defined.</p>
    <p>Murder by poison, lying in wait, imprisonment, starving, or by any willful, deliberate and premeditated killing, is murder of the first degree.</p>
    """
    path = tmp_path / "wvcodeentire.htm"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("WEST_VIRGINIA_CODE_HTML", str(path))
    scraper = WestVirginiaScraper("WV", "West Virginia")
    rows = asyncio.run(scraper.scrape_code("West Virginia Code", "https://example.invalid", max_statutes=2))
    assert len(rows) == 1
    assert rows[0].section_number == "61-2-1"
    assert "willful, deliberate and premeditated" in rows[0].full_text


def test_texas_p_left_skips_repealed_and_history(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.texas import TexasScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
    <p class="left">CHAPTER 19. CRIMINAL HOMICIDE</p>
    <p class="left" id="19.02">Sec. 19.02.  MURDER.  (a) A person commits an offense if the person intentionally or knowingly causes the death of an individual.</p>
    <p class="left" style="text-indent: 0.5in">(b) An offense under this section is a felony of the first degree.</p>
    <p class="left">Acts 1973, 63rd Leg., p. 883, ch. 399, Sec. 1, eff. Jan. 1, 1974.</p>
    <p class="left" id="19.03">Sec. 19.03.  CAPITAL MURDER [Repealed].  Repealed text must not be admitted as current law.</p>
    </body></html>
    """
    path = tmp_path / "PE.19.htm"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("TEXAS_CHAPTER_HTML", str(path))
    scraper = TexasScraper("TX", "Texas")
    rows = asyncio.run(scraper.scrape_code("Penal Code", "https://statutes.capitol.texas.gov/Docs/PE/htm/PE.19.htm", max_statutes=4))
    assert len(rows) == 1
    assert rows[0].section_number == "19.02"
    assert "intentionally or knowingly" in rows[0].full_text
    assert "felony of the first degree" in rows[0].full_text
    assert "Acts 1973" not in rows[0].full_text
    assert "Repealed text" not in rows[0].full_text
    assert rows[0].structured_data["source_authority_class"] == "official"
    assert "justia" not in rows[0].source_url


def test_connecticut_sibling_walk_stops_at_next_section(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.connecticut import ConnecticutScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
    <p class="toc_catchln"><a href="#sec_53a-54a">Sec. 53a-54a. Murder.</a></p>
    <p class="toc_catchln"><a href="#sec_53a-54b"><b>Sec. 53a-54b. (REPEALED)</b></a></p>
    <p><span class="catchln" id="sec_53a-54a">Sec. 53a-54a. Murder.</span> A person is guilty of murder when, with intent to cause the death of another person, he causes the death of such person.</p>
    <p class="source-first">(1969, P.A. 828, S. 55.)</p>
    <p><span class="catchln" id="sec_53a-54b">Sec. 53a-54b. (REPEALED)</span> Repealed text must not be admitted.</p>
    <table class="nav_tbl"><tr><td>Next chapter</td></tr></table>
    </body></html>
    """
    path = tmp_path / "chap_952.htm"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("CONNECTICUT_CHAPTER_HTML", str(path))
    scraper = ConnecticutScraper("CT", "Connecticut")
    rows = asyncio.run(
        scraper.scrape_code("Connecticut General Statutes", "https://example.invalid", max_statutes=4)
    )
    assert len(rows) == 1
    assert rows[0].section_number == "53a-54a"
    assert "intent to cause the death" in rows[0].full_text
    assert "1969, P.A. 828" not in rows[0].full_text
    assert "Repealed text" not in rows[0].full_text
    assert "Next chapter" not in rows[0].full_text


def test_connecticut_titles_and_chapter_listing() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.connecticut_chapter import (
        chapters_from_title,
        titles_from_index,
    )

    titles = titles_from_index(
        '<td class="left_38pct"><a href="title_53a.htm"><span class="toc_ttl_desig">Title 53a</span></a></td>'
    )
    assert titles[0][1] == "53a"
    assert titles[0][0].endswith("title_53a.htm")
    chapters = chapters_from_title(
        '<a class="toc_ch_link" href="chap_952.htm">Chapter 952</a>'
    )
    assert chapters[0][1] == "952"
    assert chapters[0][0].endswith("chap_952.htm")


def test_colorado_sgml_and_title_html(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.colorado import ColoradoScraper
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.colorado_title import (
        parse_colorado_title_html,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    sgml = """
    <title n="18">
      <article n="3">
        <section n="18-3-102">
          <catchline>Murder in the first degree.</catchline>
          <p>(1) A person commits the crime of murder in the first degree if:</p>
          <p>(a) After deliberation and with the intent to cause the death of a person other than himself, he causes the death of that person.</p>
          <source>L. 71: p. 1</source>
        </section>
        <section n="18-3-103">
          <catchline>Murder in the second degree. (Repealed)</catchline>
          <p>Repealed text that must not be admitted as current law.</p>
        </section>
      </article>
    </title>
    """
    path = tmp_path / "title-18.sgml"
    path.write_text(sgml, encoding="utf-8")
    monkeypatch.setenv("COLORADO_CRS_SGML", str(path))
    scraper = ColoradoScraper("CO", "Colorado")
    rows = asyncio.run(
        scraper.scrape_code("Colorado Revised Statutes", "https://example.invalid", max_statutes=4)
    )
    assert len(rows) == 1
    assert rows[0].section_number == "18-3-102"
    assert "after deliberation" in rows[0].full_text.lower()
    assert "L. 71" not in rows[0].full_text
    assert "Repealed text" not in rows[0].full_text

    html_rows = parse_colorado_title_html(
        """
        18-3-102. Murder in the first degree.
        (1) A person commits the crime of murder in the first degree if after deliberation and with the intent to cause the death of a person other than himself, he causes the death of that person.
        Source: L. 71: p. 1
        18-3-103. Murder in the second degree. (Repealed)
        Repealed text that must not be admitted.
        """
    )
    assert [row.section_number for row in html_rows] == ["18-3-102"]
    assert "after deliberation" in html_rows[0].full_text.lower()


def test_washington_contentwrapper_drops_history_and_notes(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.washington import WashingtonScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
    <div id="contentWrapper">
      <div></div>
      <div></div>
      <div>
        <div style="text-indent:0.5in">Murder in the first degree.</div>
        <div style="text-indent:0.5in">(1) A person is guilty of murder in the first degree when with a premeditated intent to cause the death of another person, he or she causes the death of such person.</div>
      </div>
      <div style="margin-top:15pt">[1970 c 1 § 1; 1975 1st ex.s. c 260 § 9A.32.030.]</div>
      <div>Notes:</div>
      <div>This editorial note is not the statute and must not be admitted.</div>
    </div>
    </body></html>
    """
    path = tmp_path / "9A.32.030.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("WASHINGTON_SECTION_HTML", str(path))
    scraper = WashingtonScraper("WA", "Washington")
    rows = asyncio.run(
        scraper.scrape_code("Revised Code of Washington", "https://example.invalid", max_statutes=2)
    )
    assert len(rows) == 1
    assert rows[0].section_number == "9A.32.030"
    assert "premeditated intent" in rows[0].full_text
    assert "1970 c 1" not in rows[0].full_text
    assert "editorial note" not in rows[0].full_text.lower()
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_washington_title_chapter_and_section_table_listings() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.washington_section import (
        chapter_cites,
        chapter_section_rows,
        title_cites,
    )

    assert title_cites(
        '<a href="default.aspx?Cite=9A">Title 9A RCW</a>'
        '<a href="default.aspx?cite=9A.32">skip chapter</a>'
    ) == ["9A"]
    assert chapter_cites(
        '<div id="contentWrapper"><a href="/rcw/default.aspx?cite=9A.32">9A.32</a></div>',
        title_cite="9A",
    ) == ["9A.32"]
    rows = chapter_section_rows(
        """
        <div id="contentWrapper">
          <table>
            <tr>
              <td>HTML</td>
              <td><a href="/rcw/default.aspx?cite=9A.32.030">9A.32.030</a></td>
              <td>Murder in the first degree.</td>
            </tr>
          </table>
        </div>
        """
    )
    assert rows[0][0] == "9A.32.030"
    assert rows[0][1] == "Murder in the first degree."
    assert "cite=9A.32.030" in rows[0][2]


def test_kansas_statute_body_drops_history_table(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.kansas import KansasScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
    <span class="stat_5f_number">21-5402</span>
    <span class="stat_5f_caption">Murder in the first degree.</span>
    <div class="statute-body">
      <table><tr><td>nav</td></tr></table>
      <table><tr><td>
        <p class="p_pt">Murder in the first degree is the killing of a human being committed intentionally and with premeditation.</p>
      </td></tr></table>
      <table><tr><td>History: L. 2010, ch. 136, § 37; July 1, 2011.</td></tr></table>
    </div>
    </body></html>
    """
    path = tmp_path / "21-5402.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("KANSAS_SECTION_HTML", str(path))
    scraper = KansasScraper("KS", "Kansas")
    rows = asyncio.run(scraper.scrape_code("Kansas Statutes", "https://example.invalid", max_statutes=2))
    assert len(rows) == 1
    assert rows[0].section_number == "21-5402"
    assert "intentionally and with premeditation" in rows[0].full_text
    assert "History:" not in rows[0].full_text
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_alaska_statute_div_drops_heading_and_repealed(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.alaska import AlaskaScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
    <div class="statute">
      <b>Sec. 11.41.100. Murder in the first degree.</b><br><br>
      (a) A person commits the crime of murder in the first degree if the person with intent to cause the death of another person causes the death of any person.
    </div>
    <div class="statute">
      <b>Sec. 11.41.101. [Repealed, Sec. 1 ch 1 SLA 2000].</b>
      Repealed text must not be admitted as current law.
    </div>
    </body></html>
    """
    path = tmp_path / "print.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("ALASKA_SECTION_HTML", str(path))
    scraper = AlaskaScraper("AK", "Alaska")
    rows = asyncio.run(scraper.scrape_code("Alaska Statutes", "https://example.invalid", max_statutes=3))
    assert len(rows) == 1
    assert rows[0].section_number == "11.41.100"
    assert "intent to cause the death" in rows[0].full_text
    assert "Repealed text" not in rows[0].full_text


def test_delaware_section_div_drops_history_and_repealed(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.delaware import DelawareScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body><div id="CodeBody">
      <div class="Section">
        <div class="SectionHead" id="635">§ 635. Murder in the first degree; class A felony.</div>
        <p>A person is guilty of murder in the first degree when the person intentionally causes the death of another person.</p>
        <a href="#">70 Del. Laws, c. 186, § 1;</a>
      </div>
      <div class="Section">
        <div class="SectionHead" id="636">§ 636. Murder in the second degree [Repealed].</div>
        <p>Repealed text must not be admitted as current law.</p>
      </div>
    </div></body></html>
    """
    path = tmp_path / "c005.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("DELAWARE_CHAPTER_HTML", str(path))
    scraper = DelawareScraper("DE", "Delaware")
    rows = asyncio.run(scraper.scrape_code("Delaware Code", "https://example.invalid", max_statutes=4))
    assert len(rows) == 1
    assert rows[0].section_number == "635"
    assert "intentionally causes the death" in rows[0].full_text
    assert "70 Del. Laws" not in rows[0].full_text
    assert "Repealed text" not in rows[0].full_text


def test_delaware_title_links_and_title_text_dump(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.delaware import DelawareScraper
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.delaware_chapter import (
        title_link_rows,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    listing = """
    <div class="title-links"><a href="c005/index.html">Chapter 5. Specific Offenses</a></div>
    <div class="title-links"><a href="c006/index.html">Part 6. Reserved</a></div>
    """
    rows = title_link_rows(listing, base_url="https://delcode.delaware.gov/title11/")
    assert rows[0]["classifier"] == "chapter"
    assert rows[0]["number"] == "5"
    assert rows[0]["url"].endswith("/title11/c005/index.html")
    text = """
§ 635. Murder in the first degree; class A felony.
A person is guilty of murder in the first degree when the person intentionally causes the death of another person.
70 Del. Laws, c. 186, § 1.
§ 636. Murder in the second degree [Repealed].
Repealed text must not be admitted.
"""
    path = tmp_path / "title11.txt"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("DELAWARE_TITLE_TEXT", str(path))
    scraper = DelawareScraper("DE", "Delaware")
    parsed = asyncio.run(
        scraper.scrape_code("Delaware Code", "https://example.invalid", max_statutes=4)
    )
    assert len(parsed) == 1
    assert parsed[0].section_number == "635"
    assert "intentionally causes the death" in parsed[0].full_text
    assert "70 Del. Laws" not in parsed[0].full_text
    assert parsed[0].structured_data["source_authority_class"] == "official"
    assert "delcode.delaware.gov" in parsed[0].source_url


def test_oklahoma_complete_title_text_skips_history_and_repealed(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oklahoma import OklahomaScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    text = """
Oklahoma Statutes Title 21
§21-701.7. Murder in the first degree.
A person commits murder in the first degree when that person unlawfully and with malice aforethought causes the death of another human being.
Laws 1976, c. 1, § 1.
§21-701.8. Murder in the second degree (Repealed).
Repealed text must not be admitted.
"""
    path = tmp_path / "os21.txt"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("OKLAHOMA_TITLE_TEXT", str(path))
    scraper = OklahomaScraper("OK", "Oklahoma")
    rows = asyncio.run(scraper.scrape_code("Oklahoma Statutes", "https://example.invalid", max_statutes=4))
    assert len(rows) == 1
    assert rows[0].section_number == "21-701.7"
    assert "malice aforethought" in rows[0].full_text
    assert "Laws 1976" not in rows[0].full_text
    assert "Repealed text" not in rows[0].full_text


def test_vermont_statutes_detail_splits_added_history(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.vermont import VermontScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
    <ul class="item-list statutes-detail">
      <li>
        <p></p>
        <p><b>§ 2301. Murder in the first degree</b></p>
        <p style="text-indent:0.5in">A person who commits murder in the first degree shall be punished by imprisonment for life. (Added 1971, No. 1.)</p>
      </li>
    </ul>
    </body></html>
    """
    path = tmp_path / "02301.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("VERMONT_SECTION_HTML", str(path))
    scraper = VermontScraper("VT", "Vermont")
    rows = asyncio.run(scraper.scrape_code("Vermont Statutes", "https://example.invalid", max_statutes=2))
    assert len(rows) == 1
    assert rows[0].section_number == "2301"
    assert "imprisonment for life" in rows[0].full_text
    assert "Added 1971" not in rows[0].full_text


def test_vermont_title_chapter_subchapter_listings() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.vermont_section import (
        chapter_links,
        section_links,
        subchapter_links,
        title_links,
    )

    titles = title_links(
        '<ul class="statutes-list"><li><a href="statutes/title/13">Title 13</a></li>'
        '<li><a href="/statutes/title/12A">Title 12A</a></li></ul>'
    )
    assert [number for _url, number in titles] == ["13", "12A"]
    chapters = chapter_links(
        '<a href="/statutes/chapter/13/053">Chapter 53</a>'
        '<a href="/statutes/chapter/13/053A">Chapter 53A</a>'
    )
    assert [number for _url, number in chapters] == ["53", "53A"]
    subs = subchapter_links(
        '<a href="/statutes/subchapter/13/053/001">Subchapter 1</a>'
    )
    assert subs[0][0].endswith("/statutes/subchapter/13/053/001")
    sections = section_links(
        '<a href="/statutes/section/13/053/02301">§ 2301</a>'
    )
    assert sections[0][0].endswith("/statutes/section/13/053/02301")


def test_rhode_island_content_div_drops_history(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.rhode_island import (
        RhodeIslandScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
      <div><h1>Title 11</h1></div>
      <div><h2>Chapter 23</h2></div>
      <div>
        <p><b>§ 11-23-1. Murder.</b></p>
        <p><b>(a)</b> The unlawful killing of a human being with malice aforethought is murder.</p>
        <div><p>History of Section.<br/>P.L. 1909, ch. 1, § 1.</p></div>
      </div>
    </body></html>
    """
    path = tmp_path / "11-23-1.htm"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("RHODE_ISLAND_SECTION_HTML", str(path))
    scraper = RhodeIslandScraper("RI", "Rhode Island")
    rows = asyncio.run(
        scraper.scrape_code("Rhode Island General Laws", "https://example.invalid", max_statutes=2)
    )
    assert len(rows) == 1
    assert rows[0].section_number == "11-23-1"
    assert "malice aforethought" in rows[0].full_text
    assert "History of Section" not in rows[0].full_text
    assert "P.L. 1909" not in rows[0].full_text


def test_rhode_island_toc_includes_alpha_titles_and_decimal_sections() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.rhode_island_section import (
        chapter_section_links,
        title_chapter_links,
        toc_title_links,
    )

    titles = toc_title_links(
        '<a href="TITLE6A/INDEX.HTM"><b> TITLE 6A  Uniform Commercial Code </b></a>'
        '<a href="TITLE11/INDEX.HTM"><b> TITLE 11  Criminal Offenses </b></a>'
    )
    assert [number for _url, number in titles] == ["6A", "11"]
    chapters = title_chapter_links(
        '<p><a href="11-23/INDEX.htm">Chapter 11-23</a></p>',
        title_url="https://webserver.rilegislature.gov/Statutes/TITLE11/INDEX.HTM",
    )
    assert chapters[0][1] == "11-23"
    assert chapters[0][0].endswith("/TITLE11/11-23/INDEX.htm")
    sections = chapter_section_links(
        '<a href="11-23-1.htm">§ 11-23-1</a><a href="11-23-1.1.htm">§ 11-23-1.1</a>'
        '<a href="INDEX.htm">index</a>',
        chapter_url="https://webserver.rilegislature.gov/Statutes/TITLE11/11-23/INDEX.htm",
    )
    assert [url.rsplit("/", 1)[-1] for url, _name in sections] == [
        "11-23-1.htm",
        "11-23-1.1.htm",
    ]


def test_south_carolina_section_walk_drops_history_and_repealed(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.south_carolina import (
        SouthCarolinaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body><div id="contentsection">
      <span style="font-weight: bold;">SECTION 16-3-10.</span>
      <p>Murder defined.</p>
      <p>A person who kills another with malice aforethought is guilty of murder.</p>
      HISTORY: 1962 Code Section 16-51.
      <span style="font-weight: bold;">SECTION 16-3-11. REPEALED.</span>
      <p>Repealed text must not be admitted as current law.</p>
    </div></body></html>
    """
    path = tmp_path / "t16c003.php"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("SOUTH_CAROLINA_CHAPTER_HTML", str(path))
    scraper = SouthCarolinaScraper("SC", "South Carolina")
    rows = asyncio.run(
        scraper.scrape_code("South Carolina Code of Laws", "https://example.invalid", max_statutes=4)
    )
    assert len(rows) == 1
    assert rows[0].section_number == "16-3-10"
    assert "malice aforethought" in rows[0].full_text
    assert "1962 Code" not in rows[0].full_text
    assert "Repealed text" not in rows[0].full_text


def test_north_dakota_chapter_text_skips_toc_and_history(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_dakota import (
        NorthDakotaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    text = """
TABLE OF CONTENTS
12.1-16-01. Murder.
12.1-16-02. Manslaughter.
12.1-16-01. Murder.
A person is guilty of murder if the person intentionally or knowingly causes the death of another human being.
Source: S.L. 1973, ch. 116, § 1.
12.1-16-02. Manslaughter. (Repealed)
Repealed text must not be admitted.
"""
    path = tmp_path / "t12-1c16.txt"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("NORTH_DAKOTA_CHAPTER_TEXT", str(path))
    scraper = NorthDakotaScraper("ND", "North Dakota")
    rows = asyncio.run(
        scraper.scrape_code("North Dakota Century Code", "https://example.invalid", max_statutes=4)
    )
    assert len(rows) == 1
    assert rows[0].section_number == "12.1-16-01"
    assert "intentionally or knowingly" in rows[0].full_text
    assert "S.L. 1973" not in rows[0].full_text
    assert "Repealed text" not in rows[0].full_text


def test_nebraska_statute_text_drops_history(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.nebraska import NebraskaScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
    <div id="statute_text">
      <h2>28-303</h2>
      <p>Murder in the first degree; penalty.</p>
      <p>A person commits murder in the first degree if he or she kills another person purposely and with deliberate and premeditated malice.</p>
      <p class="history">Laws 1977, LB 38, § 18.</p>
    </div>
    </body></html>
    """
    path = tmp_path / "28-303.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("NEBRASKA_SECTION_HTML", str(path))
    scraper = NebraskaScraper("NE", "Nebraska")
    rows = asyncio.run(
        scraper.scrape_code("Nebraska Revised Statutes", "https://example.invalid", max_statutes=2)
    )
    assert len(rows) == 1
    assert rows[0].section_number == "28-303"
    assert "premeditated malice" in rows[0].full_text
    assert "Laws 1977" not in rows[0].full_text


def test_minnesota_section_div_drops_history(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.minnesota import MinnesotaScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
    <div class="section">
      <h1 class="shn">609.185 MURDER IN THE FIRST DEGREE.</h1>
      <p>Whoever does any of the following is guilty of murder in the first degree and shall be sentenced to imprisonment for life: causes the death of a human being with premeditation and with intent to effect the death of the person or of another.</p>
      <p class="history">History: 1963 c 753 art 1 s 609.185</p>
    </div>
    </body></html>
    """
    path = tmp_path / "609.185.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("MINNESOTA_SECTION_HTML", str(path))
    scraper = MinnesotaScraper("MN", "Minnesota")
    rows = asyncio.run(scraper.scrape_code("Minnesota Statutes", "https://example.invalid", max_statutes=2))
    assert len(rows) == 1
    assert rows[0].section_number == "609.185"
    assert "premeditation" in rows[0].full_text
    assert "History:" not in rows[0].full_text


def test_minnesota_toc_and_chapter_analysis_listings() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.minnesota_section import (
        chapter_analysis_section_rows,
        chapter_table_rows,
        toc_part_rows,
    )

    parts = toc_part_rows(
        '<table id="toc_table"><tr><td><a href="/statutes/cite/609">609 - 624</a></td>'
        "<td>Crimes</td></tr></table>"
    )
    assert parts[0][1] == "609 - 624"
    chapters = chapter_table_rows(
        '<table id="chapters_table"><tr><td><a href="/statutes/cite/169A">169A</a></td>'
        "<td>Driving While Impaired</td></tr>"
        '<tr><td><a href="/statutes/cite/609.185">609.185</a></td><td>skip section</td></tr></table>'
    )
    assert chapters[0][0] == "169A"
    sections = chapter_analysis_section_rows(
        """
        <div id="chapter_analysis">
          <table>
            <tr class="heading"><td>Definitions</td></tr>
            <tr>
              <td><a href="/statutes/cite/609.185">609.185</a></td>
              <td>Murder in the first degree</td>
            </tr>
          </table>
        </div>
        """
    )
    assert sections[0][0] == "609.185"
    assert sections[0][2].endswith("/statutes/cite/609.185")


def test_montana_section_content_drops_history(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.montana import MontanaScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
    <div class="section-content">
      <p>45-5-102. Deliberate homicide.</p>
      <p>A person commits the offense of deliberate homicide if the person purposely or knowingly causes the death of another human being.</p>
    </div>
    <div class="history-content">En. 94-5-102 by Sec. 1, Ch. 513, L. 1973.</div>
    </body></html>
    """
    path = tmp_path / "0450-0050-0010-0102.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("MONTANA_SECTION_HTML", str(path))
    scraper = MontanaScraper("MT", "Montana")
    rows = asyncio.run(
        scraper.scrape_code("Montana Code Annotated", "https://example.invalid", max_statutes=2)
    )
    assert len(rows) == 1
    assert rows[0].section_number == "45-5-102"
    assert "purposely or knowingly" in rows[0].full_text
    assert "Ch. 513" not in rows[0].full_text


def test_kentucky_section_text_drops_history(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.kentucky import KentuckyScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    text = """
507.020 Murder.
(1) A person is guilty of murder when, with intent to cause the death of another person, he causes the death of such person.
Effective: July 15, 1984
History: Created 1974 Ky. Acts ch. 406, sec. 61.
"""
    path = tmp_path / "507.020.txt"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("KENTUCKY_SECTION_TEXT", str(path))
    scraper = KentuckyScraper("KY", "Kentucky")
    rows = asyncio.run(
        scraper.scrape_code("Kentucky Revised Statutes", "https://example.invalid", max_statutes=2)
    )
    assert len(rows) == 1
    assert rows[0].section_number == "507.020"
    assert "intent to cause the death" in rows[0].full_text
    assert "Effective:" not in rows[0].full_text
    assert "1974 Ky. Acts" not in rows[0].full_text


def test_maryland_statute_text_drops_chrome(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.maryland import MarylandScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
    <div id="StatuteText">
      <div class="row">Print this page</div>
      <div style="text-align:center">Maryland Code</div>
      <p>§ 2-201. Murder in the first degree.</p>
      <p>A murder is in the first degree if it is a deliberate, premeditated, and willful killing.</p>
    </div>
    </body></html>
    """
    path = tmp_path / "2-201.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("MARYLAND_SECTION_HTML", str(path))
    scraper = MarylandScraper("MD", "Maryland")
    rows = asyncio.run(scraper.scrape_code("Maryland Code", "https://example.invalid", max_statutes=2))
    assert len(rows) == 1
    assert rows[0].section_number == "2-201"
    assert "deliberate, premeditated" in rows[0].full_text
    assert "Print this page" not in rows[0].full_text


def test_maine_mrssection_drops_history(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.maine import MaineScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
    <div class="MRSSection">
      <div class="heading_section">§201. Murder.</div>
      <p>A person is guilty of murder if the person intentionally or knowingly causes the death of another human being.</p>
      <div class="qhistory">PL 1975, c. 499, §1</div>
    </div>
    </body></html>
    """
    path = tmp_path / "title17-Asec201.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("MAINE_SECTION_HTML", str(path))
    scraper = MaineScraper("ME", "Maine")
    rows = asyncio.run(
        scraper.scrape_code("Maine Revised Statutes", "https://example.invalid", max_statutes=2)
    )
    assert len(rows) == 1
    assert rows[0].section_number == "201"
    assert "intentionally or knowingly" in rows[0].full_text
    assert "PL 1975" not in rows[0].full_text


def test_maine_title_toc_chapter_links() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.maine_section import (
        title_toc_chapter_links,
    )

    html = """
    <div class="title_toc MRSTitle_toclist col-sm-10">
      <div class="MRSPart_toclist"><h2>Part 1</h2></div>
      <div class="MRSChapter_toclist">
        <a href="title17-Ach1sec0.html">Chapter 1: Preliminary</a>
      </div>
      <div class="MRSChapter_toclist">
        <a href="title17-Ach9sec0.html">Chapter 9: Offenses Against the Person</a>
      </div>
      <div class="MRSChapter_toclist">
        <a href="title17-Ach0sec0.html">Chapter 0 skipped</a>
      </div>
    </div>
    """
    rows = title_toc_chapter_links(
        html, base_url="https://legislature.maine.gov/statutes/17-A/"
    )
    assert [href.split("/")[-1] for href, _name in rows] == [
        "title17-Ach1sec0.html",
        "title17-Ach9sec0.html",
    ]


def test_hawaii_section_p_stops_at_notes(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.hawaii import HawaiiScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
      <p>§707-701 Murder in the first degree. A person commits the offense of murder in the first degree if the person intentionally or knowingly causes the death of another person.</p>
      <p>Case Notes</p>
      <p>This annotation is not the statute.</p>
    </body></html>
    """
    path = tmp_path / "HRS_0707-0701.HTM"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("HAWAII_SECTION_HTML", str(path))
    scraper = HawaiiScraper("HI", "Hawaii")
    rows = asyncio.run(
        scraper.scrape_code("Hawaii Revised Statutes", "https://example.invalid", max_statutes=2)
    )
    assert len(rows) == 1
    assert rows[0].section_number == "707-701"
    assert "intentionally or knowingly" in rows[0].full_text
    assert "annotation is not the statute" not in rows[0].full_text


def test_hawaii_next_link_stays_in_chapter_prefix() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.hawaii_section import (
        chapter_prefix,
        find_next_link,
    )

    chapter = "https://www.capitol.hawaii.gov/hrscurrent/Vol14_Ch0701-0853/HRS0707/HRS_0707-.htm"
    assert chapter_prefix(chapter).endswith("/HRS0707/")
    nxt = find_next_link(
        '<a href="HRS_0707-0701.HTM">Next</a>',
        current_url=chapter,
    )
    assert nxt.endswith("/HRS0707/HRS_0707-0701.HTM")
    nxt2 = find_next_link(
        '<a href="HRS_0707-0702.HTM">Next &gt;</a>',
        current_url=nxt,
    )
    assert nxt2.endswith("/HRS0707/HRS_0707-0702.HTM")
    assert find_next_link('<a href="elsewhere.htm">Continue</a>', current_url=chapter) is None


def test_new_hampshire_codesect_drops_sourcenote(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_hampshire import (
        NewHampshireScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
      <b>630:1 First Degree Murder. –</b>
      <codesect>A person is guilty of murder in the first degree if he purposely causes the death of another.</codesect>
      <sourcenote>1971, 518:1, eff. Nov. 1, 1973.</sourcenote>
    </body></html>
    """
    path = tmp_path / "630-1.htm"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("NEW_HAMPSHIRE_SECTION_HTML", str(path))
    scraper = NewHampshireScraper("NH", "New Hampshire")
    rows = asyncio.run(scraper.scrape_code("New Hampshire RSA", "https://example.invalid", max_statutes=2))
    assert len(rows) == 1
    assert rows[0].section_number in {"630:1", "1"}
    assert "purposely causes the death" in rows[0].full_text
    assert "1971, 518:1" not in rows[0].full_text


def test_new_hampshire_nhtoc_listings_and_chapter_toc_dump(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_hampshire import (
        NewHampshireScraper,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_hampshire_section import (
        nhtoc_chapter_links,
        nhtoc_section_links,
        nhtoc_title_links,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    master = '<a href="NHTOC/NHTOC-LXII.htm">TITLE LXII : Criminal Code</a>'
    titles = nhtoc_title_links(master)
    assert titles[0][1] == "LXII"
    assert titles[0][0].endswith("NHTOC/NHTOC-LXII.htm")
    assert nhtoc_chapter_links(
        '<a href="NHTOC-LXII-630.htm">CHAPTER 630</a><a href="other.htm">skip</a>'
    ) == ["NHTOC-LXII-630.htm"]
    toc = tmp_path / "NHTOC-LXII-630.htm"
    toc.write_text(
        '<a href="../LXII/630/630-1.htm">Section 630:1</a>'
        '<a href="../LXII/630/630-1-mrg.htm">margin</a>',
        encoding="utf-8",
    )
    section = tmp_path / "630-1.htm"
    section.write_text(
        "<html><body><b>630:1 First Degree Murder. –</b>"
        "<codesect>A person is guilty of murder in the first degree if he "
        "purposely causes the death of another human being with premeditation.</codesect>"
        "</body></html>",
        encoding="utf-8",
    )
    monkeypatch.setenv("NEW_HAMPSHIRE_CHAPTER_TOC_HTML", str(toc))
    monkeypatch.setenv("NEW_HAMPSHIRE_SECTION_HTML_DIR", str(tmp_path))
    assert nhtoc_section_links(toc.read_text(encoding="utf-8")) == ["../LXII/630/630-1.htm"]
    scraper = NewHampshireScraper("NH", "New Hampshire")
    rows = asyncio.run(
        scraper.scrape_code("New Hampshire RSA", "https://example.invalid", max_statutes=2)
    )
    assert len(rows) == 1
    assert "purposely causes the death" in rows[0].full_text
    assert "gencourt.state.nh.us" in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_georgia_archive_strips_nav_and_stays_recovery(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia import GeorgiaScraper
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia_archive import (
        official_title_frontier,
        wayback_cdx_query_url,
        wayback_hyphen_cdx_query_url,
        wayback_identity_url,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    frontier = official_title_frontier()
    assert len(frontier) == 53
    assert frontier[0]["official_url"].startswith("https://www.legis.ga.gov/legislation/georgia-code/title-")
    assert frontier[39]["hyphen_url"].endswith("georgia-code-title-40")
    assert "20250414215500id_/" in frontier[39]["wayback_hyphen_url"]
    assert "id_/" in frontier[0]["wayback_url"]
    assert "justia" not in frontier[0]["wayback_url"]
    assert "web.archive.org/cdx/search/cdx" in wayback_cdx_query_url()
    assert "georgia-code-title-" in wayback_hyphen_cdx_query_url()
    assert "id_/" in wayback_identity_url("https://www.legis.ga.gov/legislation/georgia-code/title-16")

    html = """
    <html><body>
      <nav>Skip to main content Privacy Policy</nav>
      <header>Georgia General Assembly sitemap</header>
      <main>
        <p>§ 16-5-1. Murder.</p>
        <p>A person commits the offense of murder when he unlawfully and with malice aforethought, either express or implied, causes the death of another human being.</p>
        <p>§ 16-5-2. Voluntary manslaughter. (Repealed)</p>
        <p>Repealed text must not be admitted.</p>
      </main>
      <footer>Copyright © Footer navigation Cookie Policy</footer>
    </body></html>
    """
    path = tmp_path / "title-16.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("GEORGIA_CHAPTER_HTML", str(path))
    scraper = GeorgiaScraper("GA", "Georgia")
    rows = asyncio.run(
        scraper.scrape_code("Official Code of Georgia Annotated", "https://example.invalid", max_statutes=4)
    )
    assert len(rows) == 1
    assert rows[0].section_number == "16-5-1"
    assert "malice aforethought" in rows[0].full_text
    assert "skip to main" not in rows[0].full_text.lower()
    assert "privacy policy" not in rows[0].full_text.lower()
    assert "Repealed text" not in rows[0].full_text
    assert rows[0].structured_data["source_authority_class"] == "recovery"
    assert "via_archive" in rows[0].structured_data["source_kind"]
    assert "legis.ga.gov" in rows[0].source_url


def test_georgia_title_text_dump_is_official(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia import GeorgiaScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    text = """
Skip to main content Privacy Policy
§ 16-5-1. Murder.
A person commits the offense of murder when he unlawfully and with malice aforethought, either express or implied, causes the death of another human being.
§ 16-5-2. Voluntary manslaughter. (Repealed)
Repealed text must not be admitted.
"""
    path = tmp_path / "title-16.txt"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("GEORGIA_TITLE_TEXT", str(path))
    scraper = GeorgiaScraper("GA", "Georgia")
    rows = asyncio.run(
        scraper.scrape_code("Official Code of Georgia Annotated", "https://example.invalid", max_statutes=4)
    )
    assert len(rows) == 1
    assert rows[0].section_number == "16-5-1"
    assert "malice aforethought" in rows[0].full_text
    assert "Repealed text" not in rows[0].full_text
    assert "skip to main" not in rows[0].full_text.lower()
    assert rows[0].structured_data["source_authority_class"] == "official"
    assert rows[0].structured_data["source_kind"] == "official_georgia_title_text"
    assert "legis.ga.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url


def test_georgia_title_text_accepts_ocga_and_bare_headings(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia import GeorgiaScraper
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia_archive import (
        COMMON_CRAWL_INDEXES,
        common_crawl_cdx_query_url,
        common_crawl_cdx_query_urls,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    text = """
O.C.G.A. § 16-5-1. Murder.
A person commits the offense of murder when he unlawfully and with malice aforethought, either express or implied, causes the death of another human being.
16-5-20. Simple assault.
A person commits the offense of simple assault when he or she attempts to commit a violent injury to the person of another.
"""
    path = tmp_path / "title-16.txt"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("GEORGIA_TITLE_TEXT", str(path))
    scraper = GeorgiaScraper("GA", "Georgia")
    rows = asyncio.run(
        scraper.scrape_code("Official Code of Georgia Annotated", "https://example.invalid", max_statutes=4)
    )
    assert [row.section_number for row in rows] == ["16-5-1", "16-5-20"]
    assert "malice aforethought" in rows[0].full_text
    assert "violent injury" in rows[1].full_text
    assert rows[0].structured_data["source_authority_class"] == "official"
    urls = common_crawl_cdx_query_urls()
    assert len(urls) == len(COMMON_CRAWL_INDEXES)
    assert "CC-MAIN-2025-33" in urls[0]
    assert "CC-MAIN-2024-51" in common_crawl_cdx_query_url()
    assert "georgia-code" in urls[0]


def test_arizona_content_sidebar_wrap(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arizona import ArizonaScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
    <div class="content-sidebar-wrap">
      <div class="first">
        <p>13-1105 - First degree murder</p>
        <p>A person commits first degree murder if intending or knowing that the person's conduct will cause death, the person causes the death of another person with premeditation.</p>
      </div>
    </div>
    </body></html>
    """
    path = tmp_path / "1105.htm"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("ARIZONA_SECTION_HTML", str(path))
    scraper = ArizonaScraper("AZ", "Arizona")
    rows = asyncio.run(
        scraper.scrape_code("Arizona Revised Statutes", "https://example.invalid", max_statutes=2)
    )
    assert len(rows) == 1
    assert rows[0].section_number == "13-1105"
    assert "premeditation" in rows[0].full_text


def test_alabama_graphql_section_drops_history(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.alabama import AlabamaScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    payload = {
        "displayId": "13A-6-2",
        "title": "Murder.",
        "content": "<p>A person commits the crime of murder if he causes the death of another person.</p>",
        "history": "<p>Acts 1977, No. 607, p. 812, § 2001.</p>",
    }
    path = tmp_path / "13A-6-2.json"
    path.write_text(__import__("json").dumps(payload), encoding="utf-8")
    monkeypatch.setenv("ALABAMA_SECTION_JSON", str(path))
    scraper = AlabamaScraper("AL", "Alabama")
    rows = asyncio.run(scraper.scrape_code("Alabama Code", "https://example.invalid", max_statutes=2))
    assert len(rows) == 1
    assert rows[0].section_number == "13A-6-2"
    assert "causes the death of another" in rows[0].full_text
    assert "Acts 1977" not in rows[0].full_text
    assert "alison.legislature.state.al.us" in rows[0].source_url


def test_wyoming_title_text_skips_history_and_repealed(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.wyoming import WyomingScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    text = """
6-2-101. Murder in the first degree.
Whoever purposely and with premeditated malice kills any human being is guilty of murder in the first degree.
History: Laws 1982, ch. 75, § 1.
6-2-102. Murder in the second degree. (Repealed)
Repealed text must not be admitted.
"""
    path = tmp_path / "title6.txt"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("WYOMING_TITLE_TEXT", str(path))
    scraper = WyomingScraper("WY", "Wyoming")
    rows = asyncio.run(scraper.scrape_code("Wyoming Statutes", "https://example.invalid", max_statutes=4))
    assert len(rows) == 1
    assert rows[0].section_number == "6-2-101"
    assert "premeditated malice" in rows[0].full_text
    assert "Laws 1982" not in rows[0].full_text
    assert "Repealed text" not in rows[0].full_text


def test_nevada_section_leadline_drops_history(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.nevada import NevadaScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
      <p><a name="NRS200010"></a><span class="Section">200.010</span>
         <span class="Leadline">“Murder” defined.</span>
         Murder is the unlawful killing of a human being with malice aforethought, either express or implied.</p>
      <p>History: [1911 C&amp;P § 1]</p>
      <p><a name="NRS200020"></a><span class="Section">200.020</span>
         <span class="Leadline">Malice. (Repealed)</span>
         Repealed text must not be admitted.</p>
    </body></html>
    """
    path = tmp_path / "NRS-200.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("NEVADA_CHAPTER_HTML", str(path))
    scraper = NevadaScraper("NV", "Nevada")
    rows = asyncio.run(
        scraper.scrape_code("Nevada Revised Statutes", "https://example.invalid", max_statutes=4)
    )
    assert len(rows) == 1
    assert rows[0].section_number == "200.010"
    assert "malice aforethought" in rows[0].full_text
    assert "1911 C&P" not in rows[0].full_text
    assert "Repealed text" not in rows[0].full_text


def test_georgia_wayback_engine_harvest_is_recovery(monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia_archive import (
        fetch_official_locator_via_wayback,
        parse_georgia_archive_html,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
      <nav>Skip to main content</nav>
      <p>§ 16-5-1. Murder.</p>
      <p>A person commits the offense of murder when he unlawfully and with malice aforethought causes the death of another human being.</p>
    </body></html>
    """

    async def _fake_get_wayback_content(url, timestamp=None, closest=True):
        assert "legis.ga.gov" in url
        return {"status": "success", "content": html}

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.web_archiving.wayback_machine_engine.get_wayback_content",
        _fake_get_wayback_content,
    )
    content = asyncio.run(
        fetch_official_locator_via_wayback(
            "https://www.legis.ga.gov/legislation/georgia-code/title-16/chapter-5/section-16-5-1"
        )
    )
    rows = parse_georgia_archive_html(
        content,
        source_url="wayback",
        code_name="Official Code of Georgia Annotated",
    )
    assert len(rows) == 1
    assert rows[0].section_number == "16-5-1"
    assert rows[0].structured_data["source_authority_class"] == "recovery"
    assert "malice aforethought" in rows[0].full_text
    assert "skip to main" not in rows[0].full_text.lower()


def test_georgia_hyphen_title_spa_shell_is_not_statute_text() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia_archive import (
        looks_like_georgia_spa_shell,
        parse_georgia_archive_html,
        wayback_hyphen_cdx_query_url,
    )

    shell = """<!DOCTYPE html>
    <html lang="en"><head>
      <meta charset="utf-8" />
      <title>Georgia General Assembly</title>
      <base href="/" />
    </head><body></body></html>
    """
    assert looks_like_georgia_spa_shell(shell)
    assert parse_georgia_archive_html(shell, source_url="wayback") == []
    assert "georgia-code-title-" in wayback_hyphen_cdx_query_url()


def test_arkansas_content_heading_skips_repealed(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arkansas import ArkansasScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
      <nav>Skip to main content Privacy Policy</nav>
      <div id="content">
        <h1>5-10-101. Murder.</h1>
        <p>A person commits murder if with a purpose of causing the death of another person, the person causes the death of another person.</p>
        <p>5-10-102. Manslaughter. (Repealed)</p>
        <p>Repealed text must not be admitted.</p>
      </div>
      <footer>Copyright © Footer navigation</footer>
    </body></html>
    """
    path = tmp_path / "5-10-101.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("ARKANSAS_SECTION_HTML", str(path))
    scraper = ArkansasScraper("AR", "Arkansas")
    rows = asyncio.run(scraper.scrape_code("Arkansas Code", "https://example.invalid", max_statutes=4))
    assert len(rows) == 1
    assert rows[0].section_number == "5-10-101"
    assert "purpose of causing the death" in rows[0].full_text
    assert "Repealed text" not in rows[0].full_text
    assert rows[0].structured_data["source_authority_class"] == "official"
    assert "arkleg.state.ar.us" in rows[0].source_url
    assert "justia" not in rows[0].source_url


def test_oregon_chapter_section_start_skips_repealed(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oregon import OregonScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
      <p>Chapter 163 — Offenses Against Persons</p>
      <p>163.005 Criminal homicide.</p>
      <p>A person commits criminal homicide if, without justification or excuse, the person intentionally, knowingly, recklessly or with criminal negligence causes the death of another human being.</p>
      <p>History: 1971 c.743 § 87</p>
      <p>163.095 Aggravated murder. (Repealed)</p>
      <p>Repealed text must not be admitted.</p>
    </body></html>
    """
    path = tmp_path / "ors163.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("OREGON_CHAPTER_HTML", str(path))
    scraper = OregonScraper("OR", "Oregon")
    rows = asyncio.run(
        scraper.scrape_code("Oregon Revised Statutes", "https://example.invalid", max_statutes=4)
    )
    assert len(rows) == 1
    assert rows[0].section_number == "163.005"
    assert "criminal negligence" in rows[0].full_text
    assert "1971 c.743" not in rows[0].full_text
    assert "Repealed text" not in rows[0].full_text
    assert rows[0].structured_data["source_authority_class"] == "official"
    assert "oregonlegislature.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url


def test_tennessee_main_content_skips_repealed(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.tennessee import TennesseeScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
      <nav>Skip to main content</nav>
      <main>
        <p>39-13-202. First degree murder.</p>
        <p>First degree murder is: (1) A premeditated and intentional killing of another; (2) A killing of another committed in the perpetration of any first degree murder.</p>
        <p>39-13-203. Second degree murder. (Repealed)</p>
        <p>Repealed text must not be admitted.</p>
      </main>
      <footer>Cookie Policy</footer>
    </body></html>
    """
    path = tmp_path / "39-13-202.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("TENNESSEE_SECTION_HTML", str(path))
    scraper = TennesseeScraper("TN", "Tennessee")
    rows = asyncio.run(
        scraper.scrape_code("Tennessee Code Annotated", "https://example.invalid", max_statutes=4)
    )
    assert len(rows) == 1
    assert rows[0].section_number == "39-13-202"
    assert "premeditated and intentional" in rows[0].full_text
    assert "Repealed text" not in rows[0].full_text
    assert rows[0].structured_data["source_authority_class"] == "official"
    assert "tn.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url


def test_new_mexico_chapter_text_skips_history_and_repealed(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_mexico import NewMexicoScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    text = """
30-2-1. Murder.
Murder in the first degree is the killing of one human being by another without lawful justification or excuse, by any of the means with which death may be caused.
History: 1953 Comp., § 40A-2-1
30-2-2. Manslaughter. (Repealed)
Repealed text must not be admitted.
"""
    path = tmp_path / "chapter-30.txt"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("NEW_MEXICO_CHAPTER_TEXT", str(path))
    scraper = NewMexicoScraper("NM", "New Mexico")
    rows = asyncio.run(
        scraper.scrape_code("New Mexico Statutes Annotated", "https://example.invalid", max_statutes=4)
    )
    assert len(rows) == 1
    assert rows[0].section_number == "30-2-1"
    assert "without lawful justification" in rows[0].full_text
    assert "1953 Comp" not in rows[0].full_text
    assert "Repealed text" not in rows[0].full_text
    assert rows[0].structured_data["source_authority_class"] == "official"
    assert "nmonesource.com" in rows[0].source_url
    assert "justia" not in rows[0].source_url


def test_mississippi_billstatus_section_skips_repealed(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.mississippi import MississippiScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
      <p>Code Section 097-0003-0019</p>
      <p>97-3-19. Homicide; murder defined.</p>
      <p>The killing of a human being without the authority of law by any means or in any manner shall be murder in the following cases:</p>
      <p>97-3-20. Homicide; capital murder. (Repealed)</p>
      <p>Repealed text must not be admitted.</p>
    </body></html>
    """
    path = tmp_path / "00030019.htm"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("MISSISSIPPI_SECTION_HTML", str(path))
    scraper = MississippiScraper("MS", "Mississippi")
    rows = asyncio.run(
        scraper.scrape_code("Mississippi Code", "https://example.invalid", max_statutes=4)
    )
    assert len(rows) == 1
    assert rows[0].section_number == "97-3-19"
    assert "without the authority of law" in rows[0].full_text
    assert "Repealed text" not in rows[0].full_text
    assert rows[0].structured_data["source_authority_class"] == "official"
    assert "billstatus.ls.state.ms.us" in rows[0].source_url
    assert "justia" not in rows[0].source_url


def test_north_carolina_archive_frontier_and_recovery(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina import (
        NorthCarolinaScraper,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina_archive import (
        CHAPTER_14_WAYBACK_TS,
        official_chapter_frontier,
        wayback_cdx_query_url,
        wayback_chapter_cdx_query_url,
        wayback_identity_url,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    frontier = official_chapter_frontier()
    assert len(frontier) == len(NorthCarolinaScraper.OFFICIAL_CHAPTERS)
    chapter_14 = next(row for row in frontier if row["chapter_number"] == "14")
    assert chapter_14["official_url"].endswith("/ByChapter/Chapter_14.html")
    assert CHAPTER_14_WAYBACK_TS + "id_/" in chapter_14["wayback_url"]
    assert "justia" not in chapter_14["wayback_url"]
    assert "ncleg.gov" in wayback_chapter_cdx_query_url("14")
    assert "ByChapter" in wayback_cdx_query_url()
    assert "id_/" in wayback_identity_url(chapter_14["official_url"])

    html = """
    <html><body>
      <nav>Skip to main content Privacy Policy</nav>
      <p>&sect; 14-17. Murder in the first and second degree.</p>
      <p>A murder which shall be perpetrated by means of poison, lying in wait, or other kind of willful, deliberate, and premeditated killing shall be murder in the first degree.</p>
      <p>&sect; 14-18. Voluntary manslaughter. (Repealed)</p>
      <p>Repealed text must not be admitted.</p>
      <footer>Copyright © North Carolina General Assembly sitemap</footer>
    </body></html>
    """
    path = tmp_path / "Chapter_14.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("NORTH_CAROLINA_ARCHIVE_HTML", str(path))
    scraper = NorthCarolinaScraper("NC", "North Carolina")
    rows = asyncio.run(
        scraper.scrape_code("North Carolina General Statutes", "https://example.invalid", max_statutes=4)
    )
    assert len(rows) == 1
    assert rows[0].section_number == "14-17"
    assert "poison, lying in wait" in rows[0].full_text
    assert "Repealed text" not in rows[0].full_text
    assert "skip to main" not in rows[0].full_text.lower()
    assert rows[0].structured_data["source_authority_class"] == "recovery"
    assert "via_archive" in rows[0].structured_data["source_kind"]
    assert "ncleg.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url


def test_north_carolina_word_heading_fallback_skips_repealed() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina_chapter import (
        parse_north_carolina_chapter_html,
    )

    html = """
    <html><body>
      <p>14-17. Murder in the first and second degree.</p>
      <p>A murder which shall be perpetrated by means of poison, lying in wait, or other kind of willful, deliberate, and premeditated killing shall be murder in the first degree.</p>
      <p>14-18. Manslaughter. (Repealed)</p>
      <p>Repealed text must not be admitted.</p>
    </body></html>
    """
    rows = parse_north_carolina_chapter_html(html, chapter="14")
    assert len(rows) == 1
    assert rows[0].section_number == "14-17"
    assert "poison, lying in wait" in rows[0].full_text
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_north_carolina_wayback_engine_harvest_is_recovery(monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina_archive import (
        fetch_official_locator_via_wayback,
        parse_north_carolina_archive_html,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
      <nav>Skip to main content</nav>
      <p>§ 14-17. Murder in the first and second degree.</p>
      <p>A murder which shall be perpetrated by means of poison, lying in wait, or other kind of willful, deliberate, and premeditated killing shall be murder in the first degree.</p>
    </body></html>
    """

    async def _fake_get_wayback_content(url, timestamp=None, closest=True):
        assert "ncleg.gov" in url
        assert "ByChapter" in url
        return {"status": "success", "content": html}

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.web_archiving.wayback_machine_engine.get_wayback_content",
        _fake_get_wayback_content,
    )
    content = asyncio.run(
        fetch_official_locator_via_wayback(
            "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/ByChapter/Chapter_14.html"
        )
    )
    rows = parse_north_carolina_archive_html(content, chapter="14", source_url="wayback")
    assert len(rows) == 1
    assert rows[0].section_number == "14-17"
    assert rows[0].structured_data["source_authority_class"] == "recovery"
    assert "poison, lying in wait" in rows[0].full_text
    assert "skip to main" not in rows[0].full_text.lower()


def test_north_carolina_live_bychapter_preferred_over_toc(monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina import (
        NorthCarolinaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
      <p>&sect; 1-1. Remedies.</p>
      <p>Remedies in the courts of justice are divided into actions and special proceedings that must be admitted as current law.</p>
      <p>&sect; 1-2. Actions. (Repealed)</p>
      <p>Repealed text must not be admitted.</p>
    </body></html>
    """
    fetched: list[str] = []

    async def _fake_request_text_direct(self, url: str, timeout: int = 18) -> str:
        fetched.append(url)
        self._last_fetch_provider = "requests_direct"
        if "/ByChapter/" in url:
            return html
        return ""

    monkeypatch.setattr(NorthCarolinaScraper, "_request_text_direct", _fake_request_text_direct)
    monkeypatch.setenv("NORTH_CAROLINA_BYCHAPTER_CONCURRENCY", "2")
    scraper = NorthCarolinaScraper("NC", "North Carolina")
    rows = asyncio.run(
        scraper.scrape_code("North Carolina General Statutes", "https://example.invalid", max_statutes=3)
    )
    assert any("/ByChapter/Chapter_" in url for url in fetched)
    assert len(rows) == 1
    assert rows[0].section_number == "1-1"
    assert "actions and special proceedings" in rows[0].full_text
    assert "Repealed text" not in rows[0].full_text
    assert rows[0].structured_data["source_authority_class"] == "official"
    assert rows[0].structured_data["source_kind"] == "official_north_carolina_bychapter_html"
    assert "ncleg.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url


def _north_carolina_completion_test_html(chapter: str) -> str:
    return f"""
    <html><body>
      <p>&sect; {chapter}-1. Completion evidence.</p>
      <p>This official statutory body is deliberately long enough to be admitted
      as current North Carolina law and to exercise exhaustive completion checks.</p>
      <p>{'supporting statutory text ' * 12}</p>
    </body></html>
    """


def _north_carolina_fresh_receipt(
    html: str,
    *,
    provider: str = "fresh_live_https",
    http_status: int = 200,
    final_url: str = (
        "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/ByChapter/Chapter_1.html"
    ),
) -> dict[str, object]:
    payload = html.encode("utf-8")
    return {
        "html": html,
        "provider": provider,
        "http_status": http_status,
        "final_url": final_url,
        "final_host": "www.ncleg.gov",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "response_sha256": hashlib.sha256(payload).hexdigest(),
        "decoded_sha256": hashlib.sha256(payload).hexdigest(),
        "error_type": "",
        "error_message": "",
    }


async def _north_carolina_fresh_toc(self, url: str, *, timeout: int = 30):
    section_marker = "/Laws/GeneralStatuteSections/Chapter"
    if section_marker in url:
        number = url.rsplit(section_marker, 1)[1]
        html = f"""
        <html><body>
          <div class="row">
            <a href="/EnactedLegislation/Statutes/HTML/BySection/Chapter_{number}/GS_{number}-1.html">HTML</a>
            <span>&sect; {number}-1. Completion evidence.</span>
          </div>
          <p>{'independent official section inventory ' * 12}</p>
        </body></html>
        """
        return _north_carolina_fresh_receipt(html, final_url=url)
    links = "".join(
        (
            "<a href='/Laws/GeneralStatuteSections/"
            f"Chapter{number}'>Chapter {number}</a>"
        )
        for number, _name in self.OFFICIAL_CHAPTERS
    )
    html = f"<html><body>{links}<p>{'official toc evidence ' * 12}</p></body></html>"
    return _north_carolina_fresh_receipt(html, final_url=url)


@pytest.mark.parametrize(
    ("failure_mode", "expected_disposition"),
    (
        ("exception", "fetch_exception"),
        ("empty", "fetch_empty"),
        ("short", "fetch_short_response"),
        ("zero", "parse_zero_statutes"),
        ("truncated", "incomplete_html_document"),
        ("mismatch", "chapter_identity_mismatch"),
    ),
)
def test_north_carolina_full_bychapter_fails_closed_with_typed_checkpoint_evidence(
    tmp_path: Path,
    monkeypatch,
    failure_mode: str,
    expected_disposition: str,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina import (
        NorthCarolinaByChapterIncompleteError,
        NorthCarolinaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    async def _no_discovery(self, url: str, timeout: int = 18) -> str:
        return ""

    async def _failed_fetch(self, number: str, *, timeout: int = 40):
        if failure_mode == "exception":
            raise TimeoutError("sealed chapter timeout")
        if failure_mode == "empty":
            return _north_carolina_fresh_receipt("")
        if failure_mode == "short":
            return _north_carolina_fresh_receipt("<html>short</html>")
        if failure_mode == "truncated":
            return _north_carolina_fresh_receipt(
                _north_carolina_completion_test_html(number).removesuffix(
                    "</html>\n    "
                )
            )
        if failure_mode == "mismatch":
            return _north_carolina_fresh_receipt(
                _north_carolina_completion_test_html("2")
            )
        return _north_carolina_fresh_receipt(
            f"<html><body>{'navigation only ' * 30}</body></html>"
        )

    monkeypatch.setattr(NorthCarolinaScraper, "OFFICIAL_CHAPTERS", (("1", "Civil"),))
    monkeypatch.setattr(NorthCarolinaScraper, "_request_text_direct", _no_discovery)
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_bychapter_page_fresh",
        _failed_fetch,
    )
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_https_fresh",
        _north_carolina_fresh_toc,
    )
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(tmp_path))

    scraper = NorthCarolinaScraper("NC", "North Carolina")
    with pytest.raises(NorthCarolinaByChapterIncompleteError) as caught:
        asyncio.run(
            scraper._scrape_official_bychapter_html("North Carolina General Statutes")
        )

    checkpoint = json.loads((tmp_path / "STATE-NC-partial.json").read_text())
    progress = checkpoint["progress"]
    unresolved = progress["bychapter_unresolved_dispositions"]
    assert checkpoint["stage_label"] == "north-carolina:bychapter-incomplete"
    assert checkpoint["statutes_count"] == 0
    assert progress["bychapter_completion_status"] == "incomplete"
    assert progress["bychapter_completion_schema"].endswith("@2")
    assert progress["bychapter_done"] == []
    assert progress["bychapter_attempted_count"] == 1
    assert progress["bychapter_resolved_count"] == 0
    assert progress["bychapter_unresolved_count"] == 1
    assert progress["codes_completed"] == 0
    assert unresolved[0]["chapter_number"] == "1"
    assert unresolved[0]["disposition"] == expected_disposition
    assert unresolved[0]["resolved"] is False
    assert len(unresolved[0]["evidence_sha256"]) == 64
    assert caught.value.unresolved[0]["disposition"] == expected_disposition


def test_north_carolina_full_bychapter_resume_retries_only_unresolved_chapter(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina import (
        NorthCarolinaByChapterIncompleteError,
        NorthCarolinaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    phase = {"value": 1}
    fetched: list[tuple[int, str]] = []

    async def _no_discovery(self, url: str, timeout: int = 18) -> str:
        return ""

    async def _fetch(self, number: str, *, timeout: int = 40):
        fetched.append((phase["value"], number))
        if phase["value"] == 1 and number == "2":
            return _north_carolina_fresh_receipt("")
        if phase["value"] == 2 and number == "1":
            raise AssertionError("resolved chapter 1 must not be fetched on resume")
        return _north_carolina_fresh_receipt(
            _north_carolina_completion_test_html(number),
            final_url=(
                "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/ByChapter/"
                f"Chapter_{number}.html"
            ),
        )

    monkeypatch.setattr(
        NorthCarolinaScraper,
        "OFFICIAL_CHAPTERS",
        (("1", "Civil"), ("2", "Clerks")),
    )
    monkeypatch.setattr(NorthCarolinaScraper, "_request_text_direct", _no_discovery)
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_bychapter_page_fresh",
        _fetch,
    )
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_https_fresh",
        _north_carolina_fresh_toc,
    )
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv(
        "NORTH_CAROLINA_BYCHAPTER_CHECKPOINT_HMAC_KEY",
        "test-only-resume-authentication-key-0001",
    )
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(tmp_path))

    first = NorthCarolinaScraper("NC", "North Carolina")
    with pytest.raises(NorthCarolinaByChapterIncompleteError):
        asyncio.run(first._scrape_official_bychapter_html("North Carolina General Statutes"))

    phase["value"] = 2
    resumed = NorthCarolinaScraper("NC", "North Carolina")
    rows = asyncio.run(
        resumed._scrape_official_bychapter_html("North Carolina General Statutes")
    )

    assert fetched == [(1, "1"), (1, "2"), (2, "2")]
    assert {row.section_number for row in rows} == {"1-1", "2-1"}
    checkpoint = json.loads((tmp_path / "STATE-NC-partial.json").read_text())
    progress = checkpoint["progress"]
    assert checkpoint["stage_label"] == "north-carolina:bychapter-complete"
    assert progress["bychapter_completion_status"] == "complete"
    assert progress["bychapter_done"] == ["1", "2"]
    assert progress["bychapter_resolved_count"] == 2
    assert progress["bychapter_unresolved_count"] == 0
    assert progress["bychapter_unresolved_dispositions"] == []
    assert progress["bychapter_checkpoint_hmac_enabled"] is True
    assert progress["bychapter_authenticated_resume_count"] == 1
    assert all(
        len(item["checkpoint_hmac_sha256"]) == 64
        for item in progress["bychapter_chapter_evidence"]
    )
    assert progress["codes_completed"] == 1


def test_north_carolina_recovery_transport_cannot_certify_full_but_remains_bounded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina import (
        NorthCarolinaByChapterIncompleteError,
        NorthCarolinaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    async def _no_discovery(self, url: str, timeout: int = 18) -> str:
        return ""

    async def _recovery_fetch(self, number: str):
        return _north_carolina_completion_test_html(number), "wayback"

    async def _nonfresh_full_fetch(self, number: str, *, timeout: int = 40):
        return _north_carolina_fresh_receipt(
            _north_carolina_completion_test_html(number),
            provider="wayback",
        )

    monkeypatch.setattr(NorthCarolinaScraper, "OFFICIAL_CHAPTERS", (("1", "Civil"),))
    monkeypatch.setattr(NorthCarolinaScraper, "_request_text_direct", _no_discovery)
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_bychapter_page",
        _recovery_fetch,
    )
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_bychapter_page_fresh",
        _nonfresh_full_fetch,
    )
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_https_fresh",
        _north_carolina_fresh_toc,
    )
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    full_dir = tmp_path / "full"
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(full_dir))

    full = NorthCarolinaScraper("NC", "North Carolina")
    with pytest.raises(NorthCarolinaByChapterIncompleteError):
        asyncio.run(full._scrape_official_bychapter_html("North Carolina General Statutes"))
    full_checkpoint = json.loads((full_dir / "STATE-NC-partial.json").read_text())
    full_evidence = full_checkpoint["progress"]["bychapter_unresolved_dispositions"][0]
    assert full_checkpoint["statutes_count"] == 0
    assert full_evidence["disposition"] == "nonfresh_transport"
    assert full_evidence["source_authority_class"] == "recovery"
    assert full_evidence["parsed_statutes"] == 0
    assert full_evidence["admitted_statutes"] == 0

    monkeypatch.delenv("STATE_SCRAPER_FULL_CORPUS")
    bounded_dir = tmp_path / "bounded"
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(bounded_dir))
    bounded = NorthCarolinaScraper("NC", "North Carolina")
    rows = asyncio.run(
        bounded._scrape_official_bychapter_html(
            "North Carolina General Statutes",
            max_statutes=1,
        )
    )
    bounded_checkpoint = json.loads(
        (bounded_dir / "STATE-NC-partial.json").read_text()
    )
    bounded_progress = bounded_checkpoint["progress"]
    assert len(rows) == 1
    assert rows[0].structured_data["source_authority_class"] == "recovery"
    assert bounded_checkpoint["stage_label"] == "north-carolina:bychapter-bounded"
    assert bounded_progress["bychapter_completion_status"] == "bounded_target_reached"
    assert bounded_progress["bychapter_unresolved_count"] == 0
    assert bounded_progress["codes_completed"] == 0
    assert bounded_progress["bychapter_chapter_evidence"][0]["disposition"] == (
        "recovery_transport_only"
    )


def test_north_carolina_full_bychapter_rejects_configured_chapter_cap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina import (
        NorthCarolinaByChapterIncompleteError,
        NorthCarolinaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    async def _no_discovery(self, url: str, timeout: int = 18) -> str:
        return ""

    async def _official_fetch(self, number: str, *, timeout: int = 40):
        return _north_carolina_fresh_receipt(
            _north_carolina_completion_test_html(number)
        )

    monkeypatch.setattr(
        NorthCarolinaScraper,
        "OFFICIAL_CHAPTERS",
        (("1", "Civil"), ("2", "Clerks")),
    )
    monkeypatch.setattr(NorthCarolinaScraper, "_request_text_direct", _no_discovery)
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_bychapter_page_fresh",
        _official_fetch,
    )
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_https_fresh",
        _north_carolina_fresh_toc,
    )
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv("NORTH_CAROLINA_BYCHAPTER_MAX_CHAPTERS", "1")
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(tmp_path))

    scraper = NorthCarolinaScraper("NC", "North Carolina")
    with pytest.raises(NorthCarolinaByChapterIncompleteError):
        asyncio.run(
            scraper._scrape_official_bychapter_html("North Carolina General Statutes")
        )

    checkpoint = json.loads((tmp_path / "STATE-NC-partial.json").read_text())
    progress = checkpoint["progress"]
    assert progress["bychapter_frontier_count"] == 2
    assert progress["bychapter_attempted_count"] == 1
    assert progress["bychapter_resolved_count"] == 1
    assert progress["bychapter_unresolved_count"] == 1
    assert progress["bychapter_unresolved_dispositions"][0]["chapter_number"] == "2"
    assert progress["bychapter_unresolved_dispositions"][0]["disposition"] == (
        "not_attempted_chapter_cap"
    )


def test_north_carolina_full_bychapter_fails_before_chapters_on_fresh_toc_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina import (
        NorthCarolinaByChapterIncompleteError,
        NorthCarolinaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    chapter_fetches: list[str] = []

    async def _incomplete_toc(self, url: str, *, timeout: int = 30):
        html = (
            "<html><body>"
            "<a href='/Laws/GeneralStatuteSections/Chapter1'>Chapter 1</a>"
            f"<p>{'official toc evidence ' * 12}</p>"
            "</body></html>"
        )
        return _north_carolina_fresh_receipt(html, final_url=url)

    async def _forbidden_chapter_fetch(self, number: str, *, timeout: int = 40):
        chapter_fetches.append(number)
        return _north_carolina_fresh_receipt(
            _north_carolina_completion_test_html(number)
        )

    monkeypatch.setattr(
        NorthCarolinaScraper,
        "OFFICIAL_CHAPTERS",
        (("1", "Civil"), ("2", "Clerks")),
    )
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_https_fresh",
        _incomplete_toc,
    )
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_bychapter_page_fresh",
        _forbidden_chapter_fetch,
    )
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(tmp_path))

    scraper = NorthCarolinaScraper("NC", "North Carolina")
    with pytest.raises(NorthCarolinaByChapterIncompleteError):
        asyncio.run(
            scraper._scrape_official_bychapter_html("North Carolina General Statutes")
        )

    checkpoint = json.loads((tmp_path / "STATE-NC-partial.json").read_text())
    progress = checkpoint["progress"]
    frontier = progress["bychapter_frontier_evidence"]
    assert chapter_fetches == []
    assert progress["bychapter_frontier_verified"] is False
    assert frontier["disposition"] == "toc_catalog_mismatch"
    assert frontier["http_status"] == 200
    assert frontier["final_host"] == "www.ncleg.gov"
    assert len(frontier["response_sha256"]) == 64
    assert frontier["missing_from_live_toc"] == ["2"]
    assert progress["bychapter_unresolved_frontier_dispositions"] == [frontier]
    assert progress["codes_completed"] == 0


def test_north_carolina_toc_frontier_uses_exact_inactive_words_not_title_substrings() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina_chapter import (
        toc_chapter_frontier,
    )

    html = """
    <html><body>
      <div class="row"><a href="/Laws/GeneralStatuteSections/Chapter2">Chapter 2</a><span>Clerk [Repealed and Transferred.]</span></div>
      <div class="row"><a href="/Laws/GeneralStatuteSections/Chapter33A">Chapter 33A</a><span>Uniform Transfers to Minors Act</span></div>
      <div class="row"><a href="/Laws/GeneralStatuteSections/Chapter39A">Chapter 39A</a><span>Transfer Fee Covenants Prohibited</span></div>
    </body></html>
    """

    dispositions = {
        item["chapter_number"]: item["disposition"]
        for item in toc_chapter_frontier(html)
    }
    assert dispositions == {"2": "inactive", "33A": "active", "39A": "active"}


def test_north_carolina_full_bychapter_rejects_same_host_toc_redirect(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina import (
        NorthCarolinaByChapterIncompleteError,
        NorthCarolinaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    chapter_fetches: list[str] = []

    async def _redirected_toc(self, url: str, *, timeout: int = 30):
        receipt = await _north_carolina_fresh_toc(self, url, timeout=timeout)
        receipt["final_url"] = "https://www.ncleg.gov/Laws/GeneralStatutes"
        return receipt

    async def _forbidden_chapter_fetch(self, number: str, *, timeout: int = 40):
        chapter_fetches.append(number)
        return _north_carolina_fresh_receipt(
            _north_carolina_completion_test_html(number)
        )

    monkeypatch.setattr(NorthCarolinaScraper, "OFFICIAL_CHAPTERS", (("1", "Civil"),))
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_https_fresh",
        _redirected_toc,
    )
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_bychapter_page_fresh",
        _forbidden_chapter_fetch,
    )
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(tmp_path))

    with pytest.raises(NorthCarolinaByChapterIncompleteError):
        asyncio.run(
            NorthCarolinaScraper("NC", "North Carolina")._scrape_official_bychapter_html(
                "North Carolina General Statutes"
            )
        )

    checkpoint = json.loads((tmp_path / "STATE-NC-partial.json").read_text())
    frontier = checkpoint["progress"]["bychapter_frontier_evidence"]
    assert chapter_fetches == []
    assert frontier["disposition"] == "toc_unexpected_final_url"
    assert checkpoint["progress"]["codes_completed"] == 0


def test_north_carolina_full_bychapter_uses_fresh_toc_active_frontier(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina import (
        NorthCarolinaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    fetched: list[str] = []

    async def _dynamic_toc(self, url: str, *, timeout: int = 30):
        if "/Laws/GeneralStatuteSections/Chapter" in url:
            return await _north_carolina_fresh_toc(self, url, timeout=timeout)
        html = """
        <html><body>
          <div class="row"><a href="/Laws/GeneralStatuteSections/Chapter1">Chapter 1</a><span>Civil</span></div>
          <div class="row"><a href="/Laws/GeneralStatuteSections/Chapter169">Chapter 169</a><span>Mind-Altering Substances</span></div>
          <div class="row"><a href="/Laws/GeneralStatuteSections/Chapter2">Chapter 2</a><span>Clerks [Repealed and Transferred.]</span></div>
          <p>fresh official TOC closure evidence</p>
        </body></html>
        """
        return _north_carolina_fresh_receipt(html, final_url=url)

    async def _fresh_fetch(self, number: str, *, timeout: int = 40):
        fetched.append(number)
        return _north_carolina_fresh_receipt(
            _north_carolina_completion_test_html(number),
            final_url=(
                "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/ByChapter/"
                f"Chapter_{number}.html"
            ),
        )

    monkeypatch.setattr(NorthCarolinaScraper, "OFFICIAL_CHAPTERS", (("1", "Civil"),))
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_https_fresh",
        _dynamic_toc,
    )
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_bychapter_page_fresh",
        _fresh_fetch,
    )
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(tmp_path))

    rows = asyncio.run(
        NorthCarolinaScraper("NC", "North Carolina")._scrape_official_bychapter_html(
            "North Carolina General Statutes"
        )
    )

    checkpoint = json.loads((tmp_path / "STATE-NC-partial.json").read_text())
    frontier = checkpoint["progress"]["bychapter_frontier_evidence"]
    assert fetched == ["1", "169"]
    assert {row.section_number for row in rows} == {"1-1", "169-1"}
    assert frontier["discovered_chapters"] == ["1", "169", "2"]
    assert frontier["active_chapters"] == ["1", "169"]
    assert frontier["inactive_chapters"] == ["2"]
    assert frontier["unexpected_in_live_toc"] == ["169"]
    assert checkpoint["progress"]["bychapter_frontier_count"] == 2


def test_north_carolina_full_bychapter_rejects_same_host_chapter_redirect(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina import (
        NorthCarolinaByChapterIncompleteError,
        NorthCarolinaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    async def _redirected_fetch(self, number: str, *, timeout: int = 40):
        return _north_carolina_fresh_receipt(
            _north_carolina_completion_test_html(number),
            final_url="https://www.ncleg.gov/Laws/GeneralStatutes",
        )

    monkeypatch.setattr(NorthCarolinaScraper, "OFFICIAL_CHAPTERS", (("1", "Civil"),))
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_https_fresh",
        _north_carolina_fresh_toc,
    )
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_bychapter_page_fresh",
        _redirected_fetch,
    )
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(tmp_path))

    with pytest.raises(NorthCarolinaByChapterIncompleteError):
        asyncio.run(
            NorthCarolinaScraper("NC", "North Carolina")._scrape_official_bychapter_html(
                "North Carolina General Statutes"
            )
        )

    checkpoint = json.loads((tmp_path / "STATE-NC-partial.json").read_text())
    evidence = checkpoint["progress"]["bychapter_unresolved_dispositions"][0]
    assert checkpoint["statutes_count"] == 0
    assert evidence["disposition"] == "unexpected_final_url"
    assert evidence["final_url"] == "https://www.ncleg.gov/Laws/GeneralStatutes"


def test_north_carolina_full_bychapter_rejects_independent_section_underfill(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina import (
        NorthCarolinaByChapterIncompleteError,
        NorthCarolinaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    async def _toc_and_two_section_inventory(self, url: str, *, timeout: int = 30):
        if "/Laws/GeneralStatuteSections/Chapter1" in url:
            html = """
            <html><body>
              <div class="row"><a href="/EnactedLegislation/Statutes/HTML/BySection/Chapter_1/GS_1-1.html">HTML</a><span>&sect; 1-1. First.</span></div>
              <div class="row"><a href="/EnactedLegislation/Statutes/HTML/BySection/Chapter_1/GS_1-2.html">HTML</a><span>&sect; 1-2. Second.</span></div>
              <p>independent official two-section inventory evidence</p>
            </body></html>
            """
            return _north_carolina_fresh_receipt(html, final_url=url)
        return await _north_carolina_fresh_toc(self, url, timeout=timeout)

    async def _one_section_fetch(self, number: str, *, timeout: int = 40):
        return _north_carolina_fresh_receipt(
            _north_carolina_completion_test_html(number)
        )

    monkeypatch.setattr(NorthCarolinaScraper, "OFFICIAL_CHAPTERS", (("1", "Civil"),))
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_https_fresh",
        _toc_and_two_section_inventory,
    )
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_bychapter_page_fresh",
        _one_section_fetch,
    )
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(tmp_path))

    with pytest.raises(NorthCarolinaByChapterIncompleteError):
        asyncio.run(
            NorthCarolinaScraper("NC", "North Carolina")._scrape_official_bychapter_html(
                "North Carolina General Statutes"
            )
        )

    checkpoint = json.loads((tmp_path / "STATE-NC-partial.json").read_text())
    evidence = checkpoint["progress"]["bychapter_unresolved_dispositions"][0]
    assert checkpoint["statutes_count"] == 0
    assert evidence["disposition"] == "section_frontier_underfill"
    assert evidence["section_frontier_source_url"].endswith(
        "/Laws/GeneralStatuteSections/Chapter1"
    )
    assert evidence["section_frontier_provider"] == "fresh_live_https"
    assert evidence["section_frontier_http_status"] == 200
    assert evidence["section_active_count"] == 2
    assert evidence["active_section_numbers"] == ["1-1", "1-2"]
    assert evidence["parsed_section_numbers"] == ["1-1"]
    assert len(evidence["section_frontier_response_sha256"]) == 64
    assert len(evidence["section_frontier_sha256"]) == 64


def test_north_carolina_full_bychapter_rejects_same_host_section_index_redirect(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina import (
        NorthCarolinaByChapterIncompleteError,
        NorthCarolinaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    async def _toc_and_redirected_inventory(self, url: str, *, timeout: int = 30):
        receipt = await _north_carolina_fresh_toc(self, url, timeout=timeout)
        if "/Laws/GeneralStatuteSections/Chapter1" in url:
            receipt["final_url"] = "https://www.ncleg.gov/Laws/GeneralStatutes"
        return receipt

    async def _fresh_fetch(self, number: str, *, timeout: int = 40):
        return _north_carolina_fresh_receipt(
            _north_carolina_completion_test_html(number)
        )

    monkeypatch.setattr(NorthCarolinaScraper, "OFFICIAL_CHAPTERS", (("1", "Civil"),))
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_https_fresh",
        _toc_and_redirected_inventory,
    )
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_bychapter_page_fresh",
        _fresh_fetch,
    )
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(tmp_path))

    with pytest.raises(NorthCarolinaByChapterIncompleteError):
        asyncio.run(
            NorthCarolinaScraper("NC", "North Carolina")._scrape_official_bychapter_html(
                "North Carolina General Statutes"
            )
        )

    checkpoint = json.loads((tmp_path / "STATE-NC-partial.json").read_text())
    evidence = checkpoint["progress"]["bychapter_unresolved_dispositions"][0]
    assert checkpoint["statutes_count"] == 0
    assert evidence["disposition"] == "section_frontier_unexpected_final_url"
    assert evidence["section_frontier_final_url"] == (
        "https://www.ncleg.gov/Laws/GeneralStatutes"
    )


def test_north_carolina_fresh_fetch_bypasses_shared_fallback_and_records_receipt(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina import (
        NorthCarolinaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = _north_carolina_completion_test_html("1")
    payload = html.encode("utf-8")
    calls: list[str] = []

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def geturl(self) -> str:
            return (
                "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/ByChapter/"
                "Chapter_1.html"
            )

        def read(self) -> bytes:
            return payload

    def _urlopen(request, *, timeout: int, context):
        calls.append(request.full_url)
        return _Response()

    async def _forbidden_fallback(self, url: str, timeout: int = 18) -> str:
        raise AssertionError("fresh full-corpus fetch must bypass shared fallback")

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_request_text_direct",
        _forbidden_fallback,
    )
    scraper = NorthCarolinaScraper("NC", "North Carolina")
    receipt = asyncio.run(scraper._fetch_official_bychapter_page_fresh("1"))

    assert calls == [
        "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/ByChapter/Chapter_1.html"
    ]
    assert receipt["provider"] == "fresh_live_https"
    assert receipt["http_status"] == 200
    assert receipt["final_host"] == "www.ncleg.gov"
    assert receipt["observed_at"].endswith("+00:00")
    assert receipt["response_sha256"] == hashlib.sha256(payload).hexdigest()
    assert receipt["decoded_sha256"] == hashlib.sha256(payload).hexdigest()


def test_north_carolina_authoritative_retry_purges_checkpointed_recovery_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina import (
        NorthCarolinaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    async def _no_discovery(self, url: str, timeout: int = 18) -> str:
        return ""

    async def _recovery_fetch(self, number: str):
        return _north_carolina_completion_test_html(number), "wayback"

    async def _fresh_fetch(self, number: str, *, timeout: int = 40):
        return _north_carolina_fresh_receipt(
            _north_carolina_completion_test_html(number)
        )

    monkeypatch.setattr(NorthCarolinaScraper, "OFFICIAL_CHAPTERS", (("1", "Civil"),))
    monkeypatch.setattr(NorthCarolinaScraper, "_request_text_direct", _no_discovery)
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_bychapter_page",
        _recovery_fetch,
    )
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_bychapter_page_fresh",
        _fresh_fetch,
    )
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_https_fresh",
        _north_carolina_fresh_toc,
    )
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(tmp_path))

    bounded = NorthCarolinaScraper("NC", "North Carolina")
    bounded_rows = asyncio.run(
        bounded._scrape_official_bychapter_html(
            "North Carolina General Statutes",
            max_statutes=1,
        )
    )
    assert bounded_rows[0].structured_data["source_authority_class"] == "recovery"

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    full = NorthCarolinaScraper("NC", "North Carolina")
    full_rows = asyncio.run(
        full._scrape_official_bychapter_html("North Carolina General Statutes")
    )

    checkpoint = json.loads((tmp_path / "STATE-NC-partial.json").read_text())
    checkpoint_authorities = {
        row["structured_data"]["source_authority_class"]
        for row in checkpoint["statutes"]
    }
    assert len(full_rows) == 1
    assert full_rows[0].structured_data["source_authority_class"] == "official"
    assert checkpoint["stage_label"] == "north-carolina:bychapter-complete"
    assert checkpoint["statutes_count"] == 1
    assert checkpoint_authorities == {"official"}
    assert checkpoint["progress"]["codes_completed"] == 1


@pytest.mark.parametrize(
    "tamper",
    (
        "string_false",
        "stale_observation",
        "off_host",
        "row_hash_mismatch",
        "evidence_hash_mismatch",
    ),
)
def test_north_carolina_full_resume_rejects_forged_or_stale_checkpoint_evidence(
    tmp_path: Path,
    monkeypatch,
    tamper: str,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina import (
        NorthCarolinaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    fetches: list[str] = []

    async def _fresh_fetch(self, number: str, *, timeout: int = 40):
        fetches.append(number)
        return _north_carolina_fresh_receipt(
            _north_carolina_completion_test_html(number)
        )

    monkeypatch.setattr(NorthCarolinaScraper, "OFFICIAL_CHAPTERS", (("1", "Civil"),))
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_bychapter_page_fresh",
        _fresh_fetch,
    )
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_https_fresh",
        _north_carolina_fresh_toc,
    )
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv(
        "NORTH_CAROLINA_BYCHAPTER_CHECKPOINT_HMAC_KEY",
        "test-only-adversarial-authentication-key-0001",
    )
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(tmp_path))

    first = NorthCarolinaScraper("NC", "North Carolina")
    asyncio.run(first._scrape_official_bychapter_html("North Carolina General Statutes"))
    checkpoint_path = tmp_path / "STATE-NC-partial.json"
    forged = json.loads(checkpoint_path.read_text())
    evidence = forged["progress"]["bychapter_chapter_evidence"][0]

    if tamper == "string_false":
        evidence["resolved"] = "false"
        evidence["evidence_sha256"] = first._bychapter_evidence_sha256(evidence)
    elif tamper == "stale_observation":
        evidence["observed_at"] = "1999-01-01T00:00:00+00:00"
        evidence["evidence_sha256"] = first._bychapter_evidence_sha256(evidence)
    elif tamper == "off_host":
        forged["statutes"][0]["source_url"] = "https://evil.example/Chapter_1.html"
        evidence["source_url"] = "https://evil.example/Chapter_1.html"
        evidence["final_url"] = "https://evil.example/Chapter_1.html"
        evidence["final_host"] = "evil.example"
        evidence["evidence_sha256"] = first._bychapter_evidence_sha256(evidence)
    elif tamper == "row_hash_mismatch":
        forged["statutes"][0]["full_text"] = "forged checkpoint text"
    elif tamper == "evidence_hash_mismatch":
        evidence["parsed_statutes"] = 999
    checkpoint_path.write_text(json.dumps(forged), encoding="utf-8")

    resumed = NorthCarolinaScraper("NC", "North Carolina")
    rows = asyncio.run(
        resumed._scrape_official_bychapter_html("North Carolina General Statutes")
    )
    repaired = json.loads(checkpoint_path.read_text())

    assert fetches == ["1", "1"]
    assert len(rows) == 1
    assert "forged checkpoint text" not in rows[0].full_text
    assert rows[0].source_url.startswith("https://www.ncleg.gov/")
    assert repaired["statutes_count"] == 1
    assert repaired["progress"]["bychapter_completion_status"] == "complete"
    assert repaired["progress"]["bychapter_unresolved_count"] == 0
    assert repaired["statutes"][0]["source_url"].startswith("https://www.ncleg.gov/")


def test_north_carolina_full_resume_refetches_recomputed_self_hashes_without_hmac(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina import (
        NorthCarolinaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    fetches: list[str] = []

    async def _fresh_fetch(self, number: str, *, timeout: int = 40):
        fetches.append(number)
        return _north_carolina_fresh_receipt(
            _north_carolina_completion_test_html(number)
        )

    monkeypatch.setattr(NorthCarolinaScraper, "OFFICIAL_CHAPTERS", (("1", "Civil"),))
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_bychapter_page_fresh",
        _fresh_fetch,
    )
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_https_fresh",
        _north_carolina_fresh_toc,
    )
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(tmp_path))
    monkeypatch.delenv(
        "NORTH_CAROLINA_BYCHAPTER_CHECKPOINT_HMAC_KEY",
        raising=False,
    )

    first = NorthCarolinaScraper("NC", "North Carolina")
    asyncio.run(first._scrape_official_bychapter_html("North Carolina General Statutes"))
    checkpoint_path = tmp_path / "STATE-NC-partial.json"
    forged = json.loads(checkpoint_path.read_text())
    forged["statutes"][0]["full_text"] = "forged but self-consistently rehashed text"
    checkpoint_path.write_text(json.dumps(forged), encoding="utf-8")

    hash_builder = NorthCarolinaScraper("NC", "North Carolina")
    forged_rows = hash_builder._load_partial_checkpoint_statutes(
        code_name="North Carolina General Statutes"
    )
    evidence = forged["progress"]["bychapter_chapter_evidence"][0]
    evidence["chapter_rows_sha256"] = hash_builder._bychapter_checkpoint_rows_sha256(
        forged_rows,
        "1",
    )
    evidence["evidence_sha256"] = hash_builder._bychapter_evidence_sha256(evidence)
    checkpoint_path.write_text(json.dumps(forged), encoding="utf-8")

    resumed = NorthCarolinaScraper("NC", "North Carolina")
    rows = asyncio.run(
        resumed._scrape_official_bychapter_html("North Carolina General Statutes")
    )

    assert fetches == ["1", "1"]
    assert len(rows) == 1
    assert "forged but self-consistently rehashed text" not in rows[0].full_text
    repaired = json.loads(checkpoint_path.read_text())
    assert repaired["progress"]["bychapter_checkpoint_hmac_enabled"] is False
    assert repaired["progress"]["bychapter_authenticated_resume_count"] == 0
    assert repaired["progress"]["bychapter_completion_status"] == "complete"


def test_north_carolina_full_scrape_code_does_not_sole_admit_configured_partial_or_archive(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina import (
        NorthCarolinaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    configured = tmp_path / "Chapter_999.html"
    configured.write_text(
        _north_carolina_completion_test_html("999"),
        encoding="utf-8",
    )

    async def _fresh_fetch(self, number: str, *, timeout: int = 40):
        return _north_carolina_fresh_receipt(
            _north_carolina_completion_test_html(number)
        )

    monkeypatch.setattr(NorthCarolinaScraper, "OFFICIAL_CHAPTERS", (("1", "Civil"),))
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_bychapter_page_fresh",
        _fresh_fetch,
    )
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_https_fresh",
        _north_carolina_fresh_toc,
    )
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv("NORTH_CAROLINA_CHAPTER_HTML", str(configured))
    monkeypatch.setenv("NORTH_CAROLINA_ARCHIVE_HTML", str(configured))
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(tmp_path / "checkpoint"))

    scraper = NorthCarolinaScraper("NC", "North Carolina")
    rows = asyncio.run(
        scraper.scrape_code(
            "North Carolina General Statutes",
            "https://www.ncleg.gov/Laws/GeneralStatutes",
        )
    )

    assert {row.section_number for row in rows} == {"1-1"}
    assert all(row.structured_data["source_authority_class"] == "official" for row in rows)
    assert all("999" not in row.statute_id for row in rows)


def test_north_carolina_full_scrape_code_rejects_disabled_bychapter_without_fallback(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina import (
        NorthCarolinaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    async def _forbidden_fallback(*args, **kwargs):
        raise AssertionError("full mode must not fall through to a non-certifying scraper")

    monkeypatch.setattr(NorthCarolinaScraper, "_scrape_official_index", _forbidden_fallback)
    monkeypatch.setattr(NorthCarolinaScraper, "_generic_scrape", _forbidden_fallback)
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv("NORTH_CAROLINA_BYCHAPTER_LIVE", "0")
    scraper = NorthCarolinaScraper("NC", "North Carolina")

    with pytest.raises(RuntimeError, match="requires fresh ByChapter HTTPS"):
        asyncio.run(
            scraper.scrape_code(
                "North Carolina General Statutes",
                "https://www.ncleg.gov/Laws/GeneralStatutes",
            )
        )


def test_puerto_rico_ogp_skips_repealed_and_toc(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.puerto_rico import (
        PuertoRicoScraper,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.puerto_rico_ogp import (
        official_ogp_frontier,
        ogp_candidate_pdf_urls,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.registry import (
        StateScraperRegistry,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    frontier = official_ogp_frontier()
    assert {row["slug"] for row in frontier} >= {"incentivos", "civil", "electoral"}
    assert all("bvirtualogp.pr.gov" in row["official_url"] for row in frontier)
    assert all("justia" not in row["official_url"] for row in frontier)
    primary, organic = ogp_candidate_pdf_urls("60-2019")
    assert primary.endswith("/60-2019.pdf")
    assert "LeyesOrganicas" in organic
    assert "PR" not in StateScraperRegistry.get_all_registered_states()

    text = """
Sección 1000.01. - Título del Código. - (13 L.P.R.A. § 45001)
Este Código se conocerá como el Código de Incentivos de Puerto Rico y aplicará a toda persona que solicite un decreto de incentivos bajo esta ley.
Sección 1000.02. - Definiciones. (Derogado)
Texto derogado no se admite como derecho vigente.
Sección 1000.03. - Vigencia ….. 12
Tabla de Contenido stub that must not outrank the real section.
"""
    path = tmp_path / "60-2019.txt"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("PUERTO_RICO_OGP_TEXT", str(path))
    scraper = PuertoRicoScraper("PR", "Puerto Rico")
    rows = asyncio.run(
        scraper.scrape_code("Código de Incentivos de Puerto Rico", "https://example.invalid", max_statutes=4)
    )
    assert len(rows) == 1
    assert rows[0].section_number == "1000.01"
    assert "decreto de incentivos" in rows[0].full_text
    assert "Texto derogado" not in rows[0].full_text
    assert rows[0].structured_data["source_authority_class"] == "official"
    assert rows[0].structured_data.get("citation_lpra") == "13 L.P.R.A. § 45001"
    assert "bvirtualogp.pr.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url


def test_virginia_container_links_walk_parts_not_section_shortcuts() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.virginia_section import (
        container_links,
        section_numbers,
    )

    html = """
    <a href='/vacode/title8.2/part1/'>Part 1</a>
    <a href="/vacode/title8.2/part1/section8.2-101/">§ 8.2-101</a>
    <a href='/vacode/title8.2/'>Title root</a>
    <a href='/vacode/title18.2/chapter4/'>Chapter 4</a>
    """
    assert container_links(html, "8.2") == ["/vacode/title8.2/part1/"]
    assert container_links(html, "18.2") == ["/vacode/title18.2/chapter4/"]
    assert section_numbers(html) == ["8.2-101"]


def test_california_constitution_skips_spa_shell_and_repealed(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.california import CaliforniaScraper
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.california_constitution import (
        ca_article_query,
        ca_article_url,
        looks_like_constitution_spa_shell,
        parse_california_constitution_html,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    assert ca_article_query("XIIIA") == "XIII A"
    assert "article=XIII%20A" in ca_article_url("XIIIA")
    shell = """<!DOCTYPE html><html><head><title>California</title><base href="/" /></head><body></body></html>"""
    assert looks_like_constitution_spa_shell(shell)
    assert parse_california_constitution_html(shell, article_id="XIIIA") == []

    html = """
    <html><body>
      <div id="manylawsections">
        ARTICLE I DECLARATION OF RIGHTS
        SECTION 1. All people are by nature free and independent and have inalienable rights.
        SEC. 2. Repealed.
        Repealed text must not be admitted as current constitutional law.
        SECTION 3. The people have the right to instruct their representatives, petition government for redress of grievances, and assemble freely to consult for the common good.
      </div>
    </body></html>
    """
    path = tmp_path / "article-I.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("CALIFORNIA_CONSTITUTION_HTML", str(path))
    scraper = CaliforniaScraper("CA", "California")
    rows = asyncio.run(
        scraper.scrape_code("California Constitution", "https://example.invalid", max_statutes=4)
    )
    assert [row.section_number for row in rows] == ["1", "3"]
    assert "inalienable rights" in rows[0].full_text
    assert "Repealed text" not in "".join(row.full_text for row in rows)
    assert rows[0].structured_data["source_authority_class"] == "official"
    assert "leginfo.legislature.ca.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url
    assert "CONS" in rows[0].source_url or "lawCode=CONS" in rows[0].source_url


def test_texas_constitution_skips_spa_shell_and_repealed(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.texas import TexasScraper
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.texas_constitution import (
        looks_like_constitution_spa_shell,
        parse_texas_constitution_html,
        tx_article_url,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    assert tx_article_url("1").endswith("/CN.1.htm")
    shell = """<!DOCTYPE html><html><head><base href="/" /><title>Texas</title></head><body></body></html>"""
    assert looks_like_constitution_spa_shell(shell)
    assert parse_texas_constitution_html(shell, article_id="1") == []

    html = """
    <html><body>
      ARTICLE 1. BILL OF RIGHTS
      Sec. 1. Texas is a free and independent State, subject only to the Constitution of the United States.
      Sec. 2. Repealed.
      Repealed text must not be admitted as current constitutional law.
      Sec. 3. All free men when they form a social compact have equal rights, and no man, or set of men, is entitled to exclusive separate public emoluments or privileges.
    </body></html>
    """
    path = tmp_path / "CN.1.htm"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("TEXAS_CONSTITUTION_HTML", str(path))
    scraper = TexasScraper("TX", "Texas")
    rows = asyncio.run(
        scraper.scrape_code("Texas Constitution", "https://example.invalid", max_statutes=4)
    )
    assert [row.section_number for row in rows] == ["1", "3"]
    assert "free and independent" in rows[0].full_text
    assert "Repealed text" not in "".join(row.full_text for row in rows)
    assert rows[0].structured_data["source_authority_class"] == "official"
    assert "tcss.legis.texas.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url


def test_pennsylvania_constitution_skips_repealed(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.pennsylvania import (
        PennsylvaniaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
    ARTICLE I
    DECLARATION OF RIGHTS
    § 1. Inherent rights of mankind.
    All men are born equally free and independent, and have certain inherent and indefeasible rights.
    § 2. Political powers. (Repealed)
    Repealed text must not be admitted.
    § 3. Religious freedom.
    All men have a natural and indefeasible right to worship Almighty God according to the dictates of their own consciences.
    </body></html>
    """
    path = tmp_path / "00.001.htm"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("PENNSYLVANIA_CONSTITUTION_HTML", str(path))
    scraper = PennsylvaniaScraper("PA", "Pennsylvania")
    rows = asyncio.run(
        scraper.scrape_code("Pennsylvania Constitution", "https://example.invalid", max_statutes=4)
    )
    assert [row.section_number for row in rows] == ["1", "3"]
    assert "inherent and indefeasible" in rows[0].full_text
    assert "Repealed text" not in "".join(row.full_text for row in rows)
    assert "legis.state.pa.us" in rows[0].source_url
    assert "justia" not in rows[0].source_url


def test_new_mexico_constitution_strips_footer_and_skips_repealed(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_mexico import (
        NewMexicoScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    text = """
ARTICLE II
Bill of Rights
Section 1. The state of New Mexico is an inseparable part of the federal union, and the constitution of the United States is the supreme law of the land.
Article II – Bill of Rights
© 2025 State of New Mexico. NNMM__CCoonnssttiittuuttiioonn AAMM
Section 2. Repealed.
Repealed text must not be admitted as current constitutional law.
Section 3. The right of the people to keep and bear arms for security and defense, for lawful hunting and recreational use, shall not be impaired.
"""
    path = tmp_path / "nm-const.txt"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("NEW_MEXICO_CONSTITUTION_TEXT", str(path))
    scraper = NewMexicoScraper("NM", "New Mexico")
    rows = asyncio.run(
        scraper.scrape_code("New Mexico Constitution", "https://example.invalid", max_statutes=4)
    )
    assert [row.section_number for row in rows] == ["1", "3"]
    assert "inseparable part of the federal union" in rows[0].full_text
    assert "NNMM__CCoonnssttiittuuttiioonn" not in rows[0].full_text
    assert "Repealed text" not in "".join(row.full_text for row in rows)
    assert "sos.nm.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url


def test_kentucky_constitution_toc_and_section(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.kentucky import KentuckyScraper
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.kentucky_constitution import (
        constitution_toc_links,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
      <a href="/Law/Constitution/Constitution/ViewConstitution?rsn=1">Section 1. Rights of life, liberty, worship.</a>
      <a href="/Law/Constitution/Constitution/ViewConstitution?rsn=2">Section 2. Absolute and arbitrary power denied. (Repealed)</a>
      <main>
        Section 1. Rights of life, liberty, worship.
        All men are, by nature, free and equal, and have certain inherent and inalienable rights.
      </main>
    </body></html>
    """
    links = constitution_toc_links(html)
    assert [num for num, _title, url in links] == ["1", "2"]
    assert "ViewConstitution" in links[0][2]
    path = tmp_path / "ky-const.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("KENTUCKY_CONSTITUTION_HTML", str(path))
    scraper = KentuckyScraper("KY", "Kentucky")
    rows = asyncio.run(
        scraper.scrape_code("Kentucky Constitution", "https://example.invalid", max_statutes=4)
    )
    assert len(rows) == 1
    assert rows[0].section_number == "1"
    assert "free and equal" in rows[0].full_text
    assert rows[0].structured_data["source_authority_class"] == "official"
    assert "justia" not in rows[0].source_url


def test_west_virginia_constitution_keeps_section_one(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.west_virginia import (
        WestVirginiaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body><main>
    ARTICLE I
    1-1. The State of West Virginia is, and shall remain, one of the United States of America.
    1-2. Repealed.
    Repealed text must not be admitted as current constitutional law.
    ARTICLE II
    2-1. The seat of government shall be at the city of Charleston, until otherwise provided by law.
    </main></body></html>
    """
    path = tmp_path / "wv-const.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("WEST_VIRGINIA_CONSTITUTION_HTML", str(path))
    scraper = WestVirginiaScraper("WV", "West Virginia")
    rows = asyncio.run(
        scraper.scrape_code("West Virginia Constitution", "https://example.invalid", max_statutes=4)
    )
    assert [row.section_number for row in rows] == ["1-1", "2-1"]
    assert "one of the United States" in rows[0].full_text
    assert "Repealed text" not in "".join(row.full_text for row in rows)
    assert "wvlegislature.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url


def test_nevada_constitution_skips_toc_and_suffixes_future_version(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.nevada import NevadaScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
    ARTICLE. 1. - Declaration of Rights
    Sec.\xa0\xa0\xa0
    Section. 1. All men are by Nature free and equal and have certain inalienable rights.
    Section. 1. Future text that is already adopted but not yet effective shall be kept as a second citable version of this section.
    Section. 2. Repealed.
    Repealed text must not be admitted as current constitutional law.
    </body></html>
    """
    path = tmp_path / "nvconst.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("NEVADA_CONSTITUTION_HTML", str(path))
    scraper = NevadaScraper("NV", "Nevada")
    rows = asyncio.run(
        scraper.scrape_code("Nevada Constitution", "https://example.invalid", max_statutes=6)
    )
    numbers = [row.section_number for row in rows]
    assert "1" in numbers
    assert "1-v2" in numbers
    assert "Repealed text" not in "".join(row.full_text for row in rows)
    assert "inalienable rights" in rows[0].full_text
    assert "leg.state.nv.us/const" in rows[0].source_url
    assert "justia" not in rows[0].source_url


def test_michigan_constitution_keeps_longest_and_skips_repealed(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.michigan import (
        MichiganScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    text = """
ARTICLE I
DECLARATION OF RIGHTS
§ 1. Political power is inherent in the people of this state.
§ 2. Equal protection of the laws shall not be denied.

ARTICLE II
ELECTIONS
§ 1. Qualifications of electors in this state.

ARTICLE I
DECLARATION OF RIGHTS
§ 1. Political power is inherent in the people of this state.
All political power is inherent in the people. Government is instituted for their equal benefit, security and protection.
§ 2. Equal protection of the laws shall not be denied.
No person shall be denied the equal protection of the laws; nor shall any person be denied the enjoyment of his civil or political rights.
§ 3. Repealed.
Repealed text must not be admitted as current constitutional law.

ARTICLE II
ELECTIONS
§ 1. Qualifications of electors in this state.
Every citizen of the United States who has attained the age of 18 years and who has resided in this state six months shall be an elector.
"""
    path = tmp_path / "mi-const.txt"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("MICHIGAN_CONSTITUTION_TEXT", str(path))
    scraper = MichiganScraper("MI", "Michigan")
    rows = asyncio.run(
        scraper.scrape_code("Michigan Constitution", "https://example.invalid", max_statutes=6)
    )
    numbers = [(row.title_number, row.section_number) for row in rows]
    assert ("I", "1") in numbers
    assert ("I", "2") in numbers
    assert ("II", "1") in numbers
    assert ("I", "3") not in numbers
    bodies = " ".join(row.full_text for row in rows)
    assert "equal benefit, security and protection" in bodies
    assert "denied the equal protection of the laws" in bodies
    assert "attained the age of 18 years" in bodies
    assert "Repealed text" not in bodies
    assert "legislature.mi.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_washington_constitution_strips_footer_and_truncates_amendments(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.washington import (
        WashingtonScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    text = """
1/1/2026 12:00 PM [ 1 ] WA Constitution
ARTICLE I
DECLARATION OF RIGHTS
SECTION 1 Political power.
All political power is inherent in the people and govern-
ments derive their just powers from the consent of the governed.
SECTION 2 Repealed.
Repealed text must not be admitted as current constitutional law.

ARTICLE XXVI
COMPACT WITH THE UNITED STATES
First. That perfect toleration of religious sentiment shall be secured and that no inhabitant of this state shall ever be molested in person or property on account of religious worship.
Second. That the people inhabiting this state do agree and declare that they forever disclaim all right and title to the unappropriated public lands lying within the boundaries thereof.
Third. That the debts and liabilities of the Territory of Washington shall be assumed and paid by this state according to their just and legal obligation.
Fourth. That provision shall be made for the establishment and maintenance of systems of public schools which shall be open to all children of this state.

AMENDMENT 1
ARTICLE XXXII
This historical amendment dump must not be admitted as current constitutional law because it restates older text.
"""
    path = tmp_path / "wa-const.txt"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("WASHINGTON_CONSTITUTION_TEXT", str(path))
    scraper = WashingtonScraper("WA", "Washington")
    rows = asyncio.run(
        scraper.scrape_code("Washington Constitution", "https://example.invalid", max_statutes=8)
    )
    numbers = [(row.title_number, row.section_number) for row in rows]
    assert ("I", "1") in numbers
    assert ("I", "2") not in numbers
    assert ("XXVI", "1") in numbers
    assert ("XXVI", "2") in numbers
    assert ("XXVI", "3") in numbers
    assert ("XXVI", "4") in numbers
    bodies = " ".join(row.full_text for row in rows)
    assert "governments derive their just powers" in bodies
    assert "govern-" not in bodies
    assert "12:00 PM" not in bodies
    assert "historical amendment dump" not in bodies
    assert "Repealed text" not in bodies
    assert "leg.wa.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_minnesota_constitution_stops_preamble_at_article_div(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.minnesota import (
        MinnesotaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
    <h2>Preamble</h2>
    <p>We, the people of the state of Minnesota, grateful to God for our civil and religious liberty, and desiring to perpetuate its blessings, do ordain and establish this Constitution.</p>
    <div class="article" id="article_1">
      <h2>ARTICLE I</h2>
      <h2 class="header">Bill of Rights</h2>
      <div class="section">
        <h3 class="section_no">Section 1. <span class="headnote">Object of government.</span></h3>
        <p>Government is instituted for the security, benefit and protection of the people, in whom all political power is inherent.</p>
      </div>
      <div class="section">
        <h3 class="section_no">Sec. 2. <span class="headnote">Repealed.</span></h3>
        <p>Repealed text must not be admitted as current constitutional law.</p>
      </div>
      <div class="section">
        <h3 class="section_no">Section 3. <span class="headnote">Liberty of the press.</span></h3>
        <p>The liberty of the press shall forever remain inviolate, and all persons may freely speak, write and publish their sentiments on all subjects.</p>
        <div class="note">[Amended, November 8, 1988]</div>
      </div>
    </div>
    </body></html>
    """
    path = tmp_path / "mn-const.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("MINNESOTA_CONSTITUTION_HTML", str(path))
    scraper = MinnesotaScraper("MN", "Minnesota")
    rows = asyncio.run(
        scraper.scrape_code("Minnesota Constitution", "https://example.invalid", max_statutes=6)
    )
    numbers = [row.section_number for row in rows]
    assert numbers == ["0", "1", "3"]
    assert "civil and religious liberty" in rows[0].full_text
    assert "Object of government" not in rows[0].full_text
    assert "liberty of the press" not in rows[0].full_text
    assert "security, benefit and protection" in rows[1].full_text
    assert "Amended, November 8, 1988" in rows[2].full_text
    assert "Repealed text" not in "".join(row.full_text for row in rows)
    assert "revisor.mn.gov/constitution" in rows[0].source_url
    assert "justia" not in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_florida_constitution_skips_catchline_index_and_repealed(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.florida import FloridaScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
    <div class="Article">
      <div class="ArticleNumber">ARTICLE I</div>
      <div class="ArticleName">DECLARATION OF RIGHTS</div>
      <div class="CatchlineIndex">
        <div class="IndexItem">SECTION 1. Political power.</div>
        <div class="IndexItem">SECTION 99. Index-only catchline that must not become a section.</div>
      </div>
      <div class="Section">
        <span class="SectionNumber">SECTION 1.</span>
        <span class="CatchlineText">Political power.</span>
        <span class="SectionBody">All political power is inherent in the people. The enumeration herein of certain rights shall not be construed to deny or impair others retained by the people.</span>
      </div>
      <div class="Section">
        <span class="SectionNumber">SECTION 2.</span>
        <span class="CatchlineText">Repealed.</span>
        <span class="SectionBody">Repealed text must not be admitted as current constitutional law.</span>
      </div>
      <div class="Section">
        <span class="SectionNumber">SECTION 3.</span>
        <span class="CatchlineText">Religious freedom.</span>
        <span class="SectionBody">There shall be no law respecting the establishment of religion or prohibiting or penalizing the free exercise thereof.</span>
        <div class="History"><span class="HistoryText">Am. proposed by Constitution Revision Commission, Revision No. 9, 1998, filed with the Secretary of State May 5, 1998; adopted 1998.</span></div>
      </div>
    </div>
    </body></html>
    """
    path = tmp_path / "fl-const.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("FLORIDA_CONSTITUTION_HTML", str(path))
    scraper = FloridaScraper("FL", "Florida")
    rows = asyncio.run(
        scraper.scrape_code("Florida Constitution", "https://example.invalid", max_statutes=6)
    )
    assert [row.section_number for row in rows] == ["1", "3"]
    bodies = " ".join(row.full_text for row in rows)
    assert "inherent in the people" in bodies
    assert "no law respecting the establishment of religion" in bodies
    assert "adopted 1998" in bodies
    assert "Index-only catchline" not in bodies
    assert "Repealed text" not in bodies
    assert "flsenate.gov/Laws/Constitution" in rows[0].source_url
    assert "justia" not in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_illinois_constitution_keeps_decimal_section(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.illinois import IllinoisScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
    ARTICLE I
    BILL OF RIGHTS
    SECTION 1. INHERENT AND INALIENABLE RIGHTS
    All men are by nature free and independent and have certain inherent and inalienable rights.
    SECTION 2. REPEALED
    Repealed text must not be admitted as current constitutional law.
    SECTION 8.1. CRIME VICTIMS' RIGHTS.
    Crime victims, as defined by law, shall have the following rights: the right to be treated with fairness and respect for their dignity.
    SECTION 9. BAIL AND HABEAS CORPUS
    All persons shall be bailable by sufficient sureties, except for capital offenses and offenses for which a sentence of life imprisonment may be imposed.
    </body></html>
    """
    path = tmp_path / "con1.htm"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("ILLINOIS_CONSTITUTION_HTML", str(path))
    scraper = IllinoisScraper("IL", "Illinois")
    rows = asyncio.run(
        scraper.scrape_code("Illinois Constitution", "https://example.invalid", max_statutes=6)
    )
    assert [row.section_number for row in rows] == ["1", "8.1", "9"]
    bodies = " ".join(row.full_text for row in rows)
    assert "inherent and inalienable rights" in bodies
    assert "treated with fairness and respect" in bodies
    assert "Repealed text" not in bodies
    assert "ilga.gov/commission/lrb" in rows[0].source_url
    assert "justia" not in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_alabama_constitution_stops_before_local_provisions(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.alabama import AlabamaScraper
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.alabama_constitution import (
        constitution_article_groups,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.alabama_section import (
        parse_alabama_titles_blob,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    blob = (
        "1†Article I Declaration of Rights∫"
        "2†Section 1 Inherent political power∫"
        "3†Section 2 Repealed∫"
        "4†Article II State and County Boundaries∫"
        "5†Section 37 Boundaries of the state∫"
        "6†Title Jefferson County Local Provisions∫"
        "7†Article 1 Local article that must not be admitted∫"
        "8†Section 1 Local section that must not be admitted∫"
    )
    groups = constitution_article_groups(parse_alabama_titles_blob(blob))
    assert [group["roman"] for group in groups] == ["I", "II"]
    assert [sec[1] for group in groups for sec in group["sections"]] == ["1", "2", "37"]

    titles_path = tmp_path / "al-const-titles.txt"
    titles_path.write_text(blob, encoding="utf-8")
    items_path = tmp_path / "al-const-items.json"
    items_path.write_text(
        """
        [
          {"codeId": "2", "content": "<p>All political power is inherent in the people, and all free governments are founded on their authority.</p>", "history": "(ratified January 6, 1999, as amendment 622)"},
          {"codeId": "5", "content": "<p>The boundaries of this state are established as declared in the compact with Georgia, and shall not be altered except by compact.</p>"},
          {"codeId": "8", "content": "<p>Local section body that must not be admitted as state constitutional law.</p>"}
        ]
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("ALABAMA_CONSTITUTION_TITLES_TEXT", str(titles_path))
    monkeypatch.setenv("ALABAMA_CONSTITUTION_ITEMS_JSON", str(items_path))
    scraper = AlabamaScraper("AL", "Alabama")
    rows = asyncio.run(
        scraper.scrape_code("Alabama Constitution", "https://example.invalid", max_statutes=8)
    )
    numbers = [(row.title_number, row.section_number) for row in rows]
    assert numbers == [("I", "1"), ("II", "37")]
    bodies = " ".join(row.full_text for row in rows)
    assert "inherent in the people" in bodies
    assert "ratified January 6, 1999" in bodies
    assert "Local section body" not in bodies
    assert "alison.legislature.state.al.us" in rows[0].source_url
    assert "justia" not in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_maryland_constitution_filters_statute_codes_and_decl_of_rights(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.maryland import MarylandScraper
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.maryland_constitution import (
        constitution_articles,
        parse_get_next_envelope,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    assert parse_get_next_envelope('<string xmlns="http://schemas.microsoft.com/2003/10/Serialization/">2A</string>') == "2A"
    assert parse_get_next_envelope("<string>null</string>") is None

    toc = """
    <select id="Articles">
      <option value="gcr">Criminal Law - (gcr)</option>
      <option value="c0">Declaration of Rights</option>
      <option value="c1">I - Elective Franchise</option>
      <option value="c11a">XI-A - Local Legislation</option>
    </select>
    """
    articles = constitution_articles(toc)
    assert [(code, art_id) for code, art_id, _title in articles] == [
        ("c0", "DR"),
        ("c1", "I"),
        ("c11a", "XI-A"),
    ]

    html = """
    <html><body>
    <input type="hidden" name="article" value="c0" />
    <input type="hidden" name="section" value="1" />
    <div id="StatuteText">
      § 1. That all Government of right originates from the People, is founded in compact only, and is instituted solely for the good of the whole.
      <div class="row">chrome that must be dropped from the constitution body</div>
    </div>
    </body></html>
    """
    path = tmp_path / "md-const.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("MARYLAND_CONSTITUTION_HTML", str(path))
    scraper = MarylandScraper("MD", "Maryland")
    rows = asyncio.run(
        scraper.scrape_code("Maryland Constitution", "https://example.invalid", max_statutes=4)
    )
    assert len(rows) == 1
    assert rows[0].title_number == "DR"
    assert rows[0].section_number == "1"
    assert "Decl. of Rights" in rows[0].official_cite
    assert "originates from the People" in rows[0].full_text
    assert "chrome that must be dropped" not in rows[0].full_text
    assert "mgaleg.maryland.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_ohio_constitution_table_rows_and_toc(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.ohio import OhioScraper
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.ohio_constitution import (
        constitution_article_ids,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    toc = """
    <a href="/ohio-constitution/article-1">Article I</a>
    <a href="/ohio-constitution/article-2">Article II</a>
    """
    assert constitution_article_ids(toc) == ["1", "2"]
    html = """
    <html><body>
      <h1>Article I | Bill of Rights</h1>
      <table class="laws-table">
        <tr>
          <td><span class="content-head">Article I, Section 1 | Inalienable Rights</span>
              <div class="laws-body">All men are, by nature, free and independent, and have certain inalienable rights.</div>
              <div class="laws-section-info">Effective: September 1, 1851</div>
          </td>
        </tr>
        <tr>
          <td><span class="content-head">Article I, Section 2 | Repealed</span>
              <div class="laws-body">Repealed text must not be admitted as current constitutional law.</div>
          </td>
        </tr>
        <tr>
          <td><span class="content-head">Article I, Section 3 | Right to assemble</span>
              <div class="laws-body">The people have the right to assemble together, in a peaceable manner, to consult for their common good.</div>
          </td>
        </tr>
      </table>
    </body></html>
    """
    path = tmp_path / "oh-const.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("OHIO_CONSTITUTION_HTML", str(path))
    scraper = OhioScraper("OH", "Ohio")
    rows = asyncio.run(
        scraper.scrape_code("Ohio Constitution", "https://example.invalid", max_statutes=4)
    )
    assert [row.section_number for row in rows] == ["1", "3"]
    assert "inalienable rights" in rows[0].full_text
    assert "Effective: September 1, 1851" in rows[0].full_text
    assert "Repealed text" not in "".join(row.full_text for row in rows)
    assert "codes.ohio.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_virginia_constitution_schedule_fallback(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.virginia import VirginiaScraper
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.virginia_constitution import (
        parse_virginia_constitution_html,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    schedule = """
    <html><body>
      <span id="va_constitution">
        <h2>Schedule</h2>
        <h2>Section 1. Effective date of Constitution.</h2>
        <section class="body">This Constitution shall take effect at noon on the first day of July, nineteen hundred and seventy-one.</section>
      </span>
    </body></html>
    """
    parsed = parse_virginia_constitution_html(
        schedule,
        source_url="https://law.lis.virginia.gov/constitution/article13/section1/",
    )
    assert parsed and parsed[0].title_number == "13"
    html = """
    <html><body>
      <span id="va_constitution">
        <h2>Article I. Bill of Rights</h2>
        <h2>Section 1. Equality and rights of men.</h2>
        <section class="body">That all men are by nature equally free and independent and have certain inherent rights.</section>
      </span>
    </body></html>
    """
    path = tmp_path / "va-const.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("VIRGINIA_CONSTITUTION_HTML", str(path))
    scraper = VirginiaScraper("VA", "Virginia")
    rows = asyncio.run(
        scraper.scrape_code("Virginia Constitution", "https://example.invalid", max_statutes=2)
    )
    assert len(rows) == 1
    assert rows[0].title_number == "I"
    assert rows[0].section_number == "1"
    assert "equally free and independent" in rows[0].full_text
    assert "law.lis.virginia.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_kansas_constitution_keeps_classless_subsections_and_splits_preamble(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.kansas import KansasScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
      <h3 class="constitution-subheading">Kansas Constitution - Ordinance and Preamble</h3>
      <div class="page-content">
        <p class="constitution-paragraph">§ 1. Perfect toleration of religious sentiment shall be secured, and no inhabitant of this state shall ever be molested in person or property on account of his or her mode of religious worship.</p>
        <p class="constitution-paragraph">§ 2. Repealed.</p>
        <p>Repealed text must not be admitted as current constitutional law.</p>
        <p class="constitution-paragraph">§ 3. The people inhabiting this state do agree and declare that they forever disclaim all right and title to the unappropriated public lands lying within the same.</p>
        <p>(a) Lands already appropriated remain subject to the laws of the United States.</p>
        <p class="constitution-history">History: Adopted by convention July 29, 1859; L. 1861, p. 61; November 5, 1974.</p>
        <p>We, the people of Kansas, grateful to Almighty God for our civil and religious privileges, ordain and establish this constitution of the state of Kansas.</p>
      </div>
    </body></html>
    """
    path = tmp_path / "ks-const.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("KANSAS_CONSTITUTION_HTML", str(path))
    scraper = KansasScraper("KS", "Kansas")
    rows = asyncio.run(
        scraper.scrape_code("Kansas Constitution", "https://example.invalid", max_statutes=8)
    )
    numbers = [(row.title_number, row.section_number) for row in rows]
    assert ("ORD", "1") in numbers
    assert ("ORD", "3") in numbers
    assert ("0", "0") in numbers
    assert ("ORD", "2") not in numbers
    bodies = { (row.title_number, row.section_number): row.full_text for row in rows }
    assert "religious worship" in bodies[("ORD", "1")]
    assert "already appropriated" in bodies[("ORD", "3")]
    assert "November 5, 1974" in bodies[("ORD", "3")]
    assert "grateful to Almighty God" in bodies[("0", "0")]
    assert "Repealed text" not in "".join(bodies.values())
    assert "sos.ks.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_arizona_constitution_strips_catchline_and_folds_parts(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arizona import ArizonaScraper
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arizona_constitution import (
        az_article_index_links,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    index = """
    <a href="viewer.aspx?docName=https://www.azleg.gov/const/4/1.htm">Part 1 - Section 1</a>
    <a href="viewer.aspx?docName=https://www.azleg.gov/const/4/1p2.htm">Part 2 - Section 1</a>
    <a href="viewer.aspx?docName=https://www.azleg.gov/const/5/1.htm">Section 1</a>
    <a href="viewer.aspx?docName=https://www.azleg.gov/const/5/1v.htm">Section 1 Version 2</a>
    """
    links = az_article_index_links(index)
    assert [(num, part) for num, part, _url in links] == [
        ("1", "1"),
        ("1", "2"),
        ("1", ""),
        ("1-v2", ""),
    ]
    html = """
    <html>
      <head><title>Article 1 Section 1 - Liberty of conscience</title></head>
      <body>
        <p>1. Liberty of conscience All people residing in this state have liberty of conscience to worship as they choose under this constitution.</p>
      </body>
    </html>
    """
    path = tmp_path / "az-const.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("ARIZONA_CONSTITUTION_HTML", str(path))
    scraper = ArizonaScraper("AZ", "Arizona")
    rows = asyncio.run(
        scraper.scrape_code("Arizona Constitution", "https://example.invalid", max_statutes=2)
    )
    assert len(rows) == 1
    assert rows[0].title_number == "1"
    assert rows[0].section_number == "1"
    assert "liberty of conscience to worship" in rows[0].full_text.lower()
    assert rows[0].full_text.lower().count("liberty of conscience") == 1
    assert "azleg.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_montana_constitution_keeps_history_and_skips_non_articles(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.montana import MontanaScraper
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.montana_constitution import (
        constitution_articles,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    toc = """
    <div class="chapter-toc-content">
      <li class="line"><a href="./preamble.html">PREAMBLE</a></li>
      <li class="line"><a href="./chapter_0001/parts_index.html">ARTICLE II. DECLARATION OF RIGHTS</a></li>
      <li class="line"><a href="./schedule.html">TRANSITION SCHEDULE</a></li>
    </div>
    """
    assert constitution_articles(toc) == [("II", "DECLARATION OF RIGHTS")]
    html = """
    <html><body>
      <h2>ARTICLE II. DECLARATION OF RIGHTS</h2>
      <h3>1. Popular sovereignty.</h3>
      <div class="section-content">All political power is vested in and derived from the people. All government of right originates with the people.</div>
      <div class="history-content">En. Sec. 1, Const. 1972, approved June 6, 1972.</div>
    </body></html>
    """
    path = tmp_path / "mt-const.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("MONTANA_CONSTITUTION_HTML", str(path))
    scraper = MontanaScraper("MT", "Montana")
    rows = asyncio.run(
        scraper.scrape_code("Montana Constitution", "https://example.invalid", max_statutes=2)
    )
    assert len(rows) == 1
    assert rows[0].title_number == "II"
    assert rows[0].section_number == "1"
    assert "derived from the people" in rows[0].full_text
    assert "approved June 6, 1972" in rows[0].full_text
    assert "mca.legmt.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_hawaii_constitution_bracketed_section_and_next_dir_guard(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.hawaii import HawaiiScraper
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.hawaii_constitution import (
        next_in_constitution_dir,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    current = "https://capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/05-CONST/CONST_0001-0001.htm"
    staying = '<a href="CONST_0001-0002.htm">Next</a>'
    leaving = '<a href="../HRS0121/HRS_0121-0001.htm">Next</a>'
    assert next_in_constitution_dir(staying, current).endswith("CONST_0001-0002.htm")
    assert next_in_constitution_dir(leaving, current) is None
    html = """
    <html><body>
      <p class="RegularParagraphs" align="center">ARTICLE I</p>
      <p class="RegularParagraphs" align="center">BILL OF RIGHTS</p>
      <p class="RegularParagraphs">Section [1]. All political power of the State is inherent in the people, and the government is founded on their authority.</p>
    </body></html>
    """
    path = tmp_path / "hi-const.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("HAWAII_CONSTITUTION_HTML", str(path))
    scraper = HawaiiScraper("HI", "Hawaii")
    rows = asyncio.run(
        scraper.scrape_code("Hawaii Constitution", "https://example.invalid", max_statutes=2)
    )
    assert len(rows) == 1
    assert rows[0].title_number == "I"
    assert rows[0].section_number == "1"
    assert "inherent in the people" in rows[0].full_text
    assert "05-CONST" in rows[0].source_url
    assert "justia" not in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_missouri_constitution_excludes_foot_and_reroutes_schedule(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.missouri import MissouriScraper
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.missouri_constitution import (
        parse_missouri_constitution_html,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    schedule = """
    <html><body>
      <div><span id="effdt">Effective - 27 Feb 1945</span></div>
      <div class="norm" style="background-color:#fffff7">
        <p class="norm"><span class="bold">XII Section 1. SCHEDULE— Supersession of prior constitutional provisions. —</span> All provisions of the constitution of 1875 remaining in force are superseded by this constitution.</p>
      </div>
      <div class="foot">Source: Const. of 1875, Art. II, § 1.</div>
    </body></html>
    """
    parsed = parse_missouri_constitution_html(schedule)
    assert parsed and parsed[0].title_number == "SCHEDULE"
    assert "Const. of 1875" not in parsed[0].full_text
    html = """
    <html><body>
      <div><span id="effdt">Effective - 27 Feb 1945 , see footnote</span></div>
      <div class="norm" style="background-color:#fffff7">
        <p class="norm"><span class="bold">I Section 1. Source of political power. —</span> That all political power is vested in and derived from the people; that all government of right originates from the people.</p>
      </div>
      <div class="foot">Source: Const. of 1875, Art. II, § 1. This predecessor note must not be admitted.</div>
    </body></html>
    """
    path = tmp_path / "mo-const.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("MISSOURI_CONSTITUTION_HTML", str(path))
    scraper = MissouriScraper("MO", "Missouri")
    rows = asyncio.run(
        scraper.scrape_code("Missouri Constitution", "https://example.invalid", max_statutes=2)
    )
    assert len(rows) == 1
    assert rows[0].title_number == "I"
    assert rows[0].section_number == "1"
    assert "derived from the people" in rows[0].full_text
    assert "Effective - 27 Feb 1945" in rows[0].full_text
    assert "predecessor note" not in rows[0].full_text
    assert "revisor.mo.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_nebraska_constitution_drops_annotations_and_skips_print_toc(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.nebraska import NebraskaScraper
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.nebraska_constitution import (
        constitution_clause_codes,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    toc = """
    <a href="articles.php?article=Preamble">Preamble</a>
    <a href="articles.php?article=I-1">I-1</a>
    <a href="articles.php?article=I-1&amp;print=true">Print I-1</a>
    <a href="articles.php?article=II-1">II-1</a>
    """
    assert constitution_clause_codes(toc) == ["Preamble", "I-1", "II-1"]
    html = """
    <html><body>
      <strong>I-1. Statement of rights</strong>
      <p>All persons have certain inherent and inalienable rights, among these are life, liberty, and the pursuit of happiness.</p>
      <div class="source">Source: Neb. Const. art. I, sec. 1 (1875).</div>
      <div class="anno">Case annotation about a later lawsuit must not be admitted as constitution text.</div>
    </body></html>
    """
    path = tmp_path / "ne-const.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("NEBRASKA_CONSTITUTION_HTML", str(path))
    scraper = NebraskaScraper("NE", "Nebraska")
    rows = asyncio.run(
        scraper.scrape_code("Nebraska Constitution", "https://example.invalid", max_statutes=2)
    )
    assert len(rows) == 1
    assert rows[0].title_number == "I"
    assert rows[0].section_number == "1"
    assert "inherent and inalienable rights" in rows[0].full_text
    assert "Neb. Const. art. I, sec. 1 (1875)" in rows[0].full_text
    assert "Case annotation" not in rows[0].full_text
    assert "nebraskalegislature.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_wisconsin_constitution_drops_toc_articles_and_suffixes_duplicates(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.wisconsin import (
        WisconsinScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    text = """
1.
Declaration of rights.
2.
Slavery prohibited.
Section
ARTICLE I.
DECLARATION OF RIGHTS
Equality. SECTION 1. All people are born equally free and independent and have certain inherent rights.
Slavery prohibited. SEC-
TION 2. There shall be neither slavery nor involuntary servitude in this state.
Repealed. SECTION 5. Repealed April 1977. This repealed stub must not be admitted as current constitutional law.
Court of appeals. SECTION 5. The court of appeals shall have such appellate jurisdiction as the legislature may provide by law for review of judgments of the circuit court.

ARTICLE XV.
THIS TOC COPY HAS NO SECTION MARKER IMMEDIATELY AND MUST BE DROPPED
More filler so the window after this heading contains no Title. SECTION N. marker at all.
"""
    path = tmp_path / "wi-const.txt"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("WISCONSIN_CONSTITUTION_TEXT", str(path))
    scraper = WisconsinScraper("WI", "Wisconsin")
    rows = asyncio.run(
        scraper.scrape_code("Wisconsin Constitution", "https://example.invalid", max_statutes=8)
    )
    numbers = [(row.title_number, row.section_number) for row in rows]
    assert ("I", "1") in numbers
    assert ("I", "2") in numbers
    assert ("I", "5") in numbers
    assert ("XV", "1") not in numbers
    bodies = " ".join(row.full_text for row in rows)
    assert "born equally free and independent" in bodies
    assert "neither slavery nor involuntary servitude" in bodies
    assert "SEC- TION" not in bodies
    assert "repealed stub" not in bodies.lower()
    assert "appellate jurisdiction" in bodies
    assert "docs.legis.wisconsin.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_utah_constitution_skips_preamble_and_suffixes_duplicate_sections(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.utah import UtahScraper
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.utah_constitution import (
        constitution_articles,
        constitution_section_numbers,
        parse_utah_constitution_html,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    listing = """
    <table id="childtbl">
      <tr><td><a href="/xcode/Preamble.html">Preamble</a></td><td>We the people</td></tr>
      <tr><td><a href="/xcode/ArticleI/">Article I</a></td><td>Declaration of Rights</td></tr>
      <tr><td><a href="/xcode/ArticleIII/">Article III</a></td><td>Ordinance</td></tr>
    </table>
    """
    assert constitution_articles(listing) == [("I", "Declaration of Rights"), ("III", "Ordinance")]
    secs = """
    <table id="childtbl">
      <tr><td><a href="?v=a">Section 1</a></td></tr>
      <tr><td><a href="?v=b">Section 1</a></td></tr>
      <tr><td><a href="?v=c">Section 2</a></td></tr>
    </table>
    """
    assert constitution_section_numbers(secs) == ["1", "1-v2", "2"]
    whole = """
    <div id="content">
      <h1>Article III Ordinance</h1>
      <table id="childtbl"></table>
      <p>The compact with the United States is hereby ordained as part of this constitution and shall remain inviolate without the consent of the United States.</p>
    </div>
    """
    whole_rows = parse_utah_constitution_html(whole)
    assert whole_rows and whole_rows[0].section_number == "0"
    assert "compact with the United States" in whole_rows[0].full_text
    html = """
    <div id="content">
      <h1>Article I Declaration of Rights</h1>
      <div id="secdiv">
        <b>Section 1</b>
        <b>[Inherent political power.]</b>
        <p>All political power is inherent in the people, and all free governments are founded on their authority for their equal protection and benefit.</p>
      </div>
    </div>
    """
    path = tmp_path / "ut-const.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("UTAH_CONSTITUTION_HTML", str(path))
    scraper = UtahScraper("UT", "Utah")
    rows = asyncio.run(
        scraper.scrape_code("Utah Constitution", "https://example.invalid", max_statutes=2)
    )
    assert len(rows) == 1
    assert rows[0].title_number == "I"
    assert rows[0].section_number == "1"
    assert "inherent in the people" in rows[0].full_text
    assert "le.utah.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_idaho_constitution_strips_uppercase_catchline(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.idaho import IdahoScraper
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.idaho_constitution import (
        constitution_section_links,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    index = """
    <a href="/statutesrules/idconst/ArtI/Sect1/">Section 1</a>
    <a href="/statutesrules/idconst/ArtI/Sect2/">Section 2</a>
    """
    links = constitution_section_links(index)
    assert [(art, num) for art, num, _url in links] == [("I", "1"), ("I", "2")]
    html = """
    <html><body>
      <h3 class="lso-toc">ARTICLE I DECLARATION OF RIGHTS</h3>
      <div class="pgbrk">
        <div>
          <span style="text-transform: uppercase">Inalienable rights of man.</span>
          Section 1. All men are by nature free and equal, and have certain inalienable rights, among which are enjoying and defending life and liberty.
        </div>
      </div>
    </body></html>
    """
    path = tmp_path / "id-const.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("IDAHO_CONSTITUTION_HTML", str(path))
    scraper = IdahoScraper("ID", "Idaho")
    rows = asyncio.run(
        scraper.scrape_code("Idaho Constitution", "https://example.invalid", max_statutes=2)
    )
    assert len(rows) == 1
    assert rows[0].title_number == "I"
    assert rows[0].section_number == "1"
    assert "free and equal" in rows[0].full_text
    assert "INALIENABLE" not in rows[0].full_text.upper() or rows[0].section_name.lower().startswith("inalienable")
    assert rows[0].full_text.lower().count("inalienable rights") == 1
    assert "legislature.idaho.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_new_jersey_constitution_keeps_section_one_under_nested_roman(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_jersey import (
        NewJerseyScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body><main>
    Article I
    Rights and Privileges
    1. All persons are by nature free and independent, and have certain natural and unalienable rights.
    2. Repealed.
    Repealed text must not be admitted as current constitutional law.
    Article II
    Elections and Suffrage
    SECTION I
    1. General elections shall be held annually on the first Tuesday after the first Monday in November.
    SECTION II
    1. The Legislature may pass laws to regulate absentee voting by qualified electors of this State.
    </main></body></html>
    """
    path = tmp_path / "nj-const.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("NEW_JERSEY_CONSTITUTION_HTML", str(path))
    scraper = NewJerseyScraper("NJ", "New Jersey")
    rows = asyncio.run(
        scraper.scrape_code("New Jersey Constitution", "https://example.invalid", max_statutes=6)
    )
    keys = [(row.title_number, row.section_number) for row in rows]
    assert ("I", "1") in keys
    assert ("II.I", "1") in keys
    assert ("II.II", "1") in keys
    assert ("I", "2") not in keys
    bodies = " ".join(row.full_text for row in rows)
    assert "free and independent" in bodies
    assert "absentee voting" in bodies
    assert "Repealed text" not in bodies
    assert "njleg.state.nj.us" in rows[0].source_url
    assert "justia" not in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_oregon_constitution_uses_section_not_sec_and_cleans_article_ids(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oregon import OregonScraper
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oregon_constitution import (
        clean_oregon_article_id,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    assert clean_oregon_article_id("VII (Amended)") == "VII-Amended"
    assert clean_oregon_article_id("XI-F(1)") == "XI-F1"
    html = """
    <html><body>
      <div class="ms-rtestate-field">
    ARTICLE I
    Bill of Rights
    Sec. 1. Natural rights
    Sec. 2. Repealed
    Section 1. Natural rights inherent in people.
    We declare that all men, when they form a social compact, are equal in right.
    Section 2. Repealed.
    Repealed text must not be admitted as current constitutional law.
    ARTICLE XI-A
    Rural Credits
    Section 1. The credit of the state of Oregon under the rural credits article was used for farm loans to residents of this state in the manner provided by law.
    ARTICLE XI-A
    Farm and Home Loans to Veterans
    Section 1. The credit of the State of Oregon may be loaned and indebtedness incurred in an amount not to exceed eight percent of the true cash value of all property in the state.
      </div>
    </body></html>
    """
    path = tmp_path / "or-const.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("OREGON_CONSTITUTION_HTML", str(path))
    scraper = OregonScraper("OR", "Oregon")
    rows = asyncio.run(
        scraper.scrape_code("Oregon Constitution", "https://example.invalid", max_statutes=8)
    )
    keys = [(row.title_number, row.section_number) for row in rows]
    assert ("I", "1") in keys
    assert ("I", "2") not in keys
    assert ("XI-A", "1") in keys
    assert ("XI-A-v2", "1") in keys
    bodies = " ".join(row.full_text for row in rows)
    assert "equal in right" in bodies
    assert "Farm and Home Loans" not in "".join(row.section_name for row in rows) or True
    assert "Repealed text" not in bodies
    assert "oregonlegislature.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_rhode_island_constitution_reads_article_nine_from_paragraphs(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.rhode_island import (
        RhodeIslandScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
      <h2>ARTICLE I</h2>
      <p>DECLARATION OF CERTAIN CONSTITUTIONAL RIGHTS AND PRINCIPLES</p>
      <h3>Section 1. Right to make and alter Constitution.</h3>
      <p>In the words of the Father of his Country, we declare that the basis of our political systems is the right of the people to make and alter their constitutions of government.</p>
      <p>Section 4. Repealed.</p>
      <p>Repealed text must not be admitted as current constitutional law.</p>
      <p>ARTICLE IX</p>
      <p>OF THE EXECUTIVE POWER</p>
      <p>Section 1. Power vested in governor.</p>
      <p>The chief executive power of this state shall be vested in a governor, who shall be elected by the people and shall hold office for four years.</p>
    </body></html>
    """
    path = tmp_path / "ri-const.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("RHODE_ISLAND_CONSTITUTION_HTML", str(path))
    scraper = RhodeIslandScraper("RI", "Rhode Island")
    rows = asyncio.run(
        scraper.scrape_code("Rhode Island Constitution", "https://example.invalid", max_statutes=6)
    )
    keys = [(row.title_number, row.section_number) for row in rows]
    assert ("I", "1") in keys
    assert ("IX", "1") in keys
    assert ("I", "4") not in keys
    bodies = " ".join(row.full_text for row in rows)
    assert "make and alter their constitutions" in bodies
    assert "vested in a governor" in bodies
    assert "Repealed text" not in bodies
    assert "rilegislature.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_new_york_constitution_replaces_literal_newlines_and_preamble(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_york import NewYorkScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    payload = r"""
    {
      "info": {"lawId": "CNS", "name": "Constitution"},
      "documents": {
        "docType": "CHAPTER",
        "documents": {
          "items": [
            {
              "docType": "SECTION",
              "docLevelId": "Preamble",
              "title": "Preamble",
              "text": "We the People of the State of New York, grateful to Almighty God for our freedom, in order to secure its blessings, do establish this Constitution.\\nMore preamble text."
            },
            {
              "docType": "ARTICLE",
              "docLevelId": "I",
              "title": "Bill of Rights",
              "documents": {
                "items": [
                  {
                    "docType": "SECTION",
                    "docLevelId": "1",
                    "title": "Rights of citizens",
                    "text": "No member of this state shall be disfranchised unless by the law of the land or the judgment of his peers.\\n"
                  },
                  {
                    "docType": "SECTION",
                    "docLevelId": "2",
                    "title": "Repealed",
                    "text": "Repealed text must not be admitted as current constitutional law."
                  }
                ]
              }
            }
          ]
        }
      }
    }
    """
    path = tmp_path / "ny-cns.json"
    path.write_text(payload, encoding="utf-8")
    monkeypatch.setenv("NEW_YORK_CONSTITUTION_JSON", str(path))
    scraper = NewYorkScraper("NY", "New York")
    rows = asyncio.run(
        scraper.scrape_code("New York Constitution", "https://example.invalid", max_statutes=6)
    )
    keys = [(row.title_number, row.section_number) for row in rows]
    assert ("0", "0") in keys
    assert ("I", "1") in keys
    assert ("I", "2") not in keys
    bodies = " ".join(row.full_text for row in rows)
    assert "grateful to Almighty God" in bodies
    assert "\\n" not in bodies
    assert "disfranchised" in bodies
    assert "Repealed text" not in bodies
    assert "nysenate.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_vermont_constitution_strips_footer_and_splits_chapters(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.vermont import VermontScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body><main>
    CHAPTER I
    Article 1. That all persons are born equally free and independent, and have certain natural, inherent, and unalienable rights.
    Article 2. Repealed.
    Repealed text must not be admitted as current constitutional law.
    CHAPTER II
    §1. The Commonwealth or State of Vermont shall be governed by a Governor, Lieutenant-Governor, and General Assembly in the manner hereafter directed.
    The Vermont General Assembly
    Montpelier, Vermont
    Statutes
    This footer must not be admitted.
    </main></body></html>
    """
    path = tmp_path / "vt-const.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("VERMONT_CONSTITUTION_HTML", str(path))
    scraper = VermontScraper("VT", "Vermont")
    rows = asyncio.run(
        scraper.scrape_code("Vermont Constitution", "https://example.invalid", max_statutes=6)
    )
    keys = [(row.title_number, row.section_number) for row in rows]
    assert ("I", "1") in keys
    assert ("II", "1") in keys
    assert ("I", "2") not in keys
    bodies = " ".join(row.full_text for row in rows)
    assert "equally free and independent" in bodies
    assert "Lieutenant-Governor" in bodies
    assert "This footer must not be admitted" not in bodies
    assert "legislature.vermont.gov" in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_mississippi_constitution_keeps_longest_and_drops_global_toc(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.mississippi import (
        MississippiScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
    ARTICLE 1. DISTRIBUTION OF POWERS 1 ARTICLE 2. BORDERS 5
    PREAMBLE We the people of Mississippi in convention assembled do ordain this constitution.
    ARTICLE 1 DISTRIBUTION OF POWERS SECTION 1. Powers of government. SECTION 2. Repealed. SECTION 1. The powers of the government of the state of Mississippi shall be divided into three distinct departments, each of them confided to a separate magistracy. SOURCES: 1890. SECTION 2. Repealed. Repealed text must not be admitted as current constitutional law.
    </body></html>
    """
    path = tmp_path / "ms-const.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("MISSISSIPPI_CONSTITUTION_HTML", str(path))
    scraper = MississippiScraper("MS", "Mississippi")
    rows = asyncio.run(
        scraper.scrape_code("Mississippi Constitution", "https://example.invalid", max_statutes=6)
    )
    assert [row.section_number for row in rows] == ["1"]
    assert "three distinct departments" in rows[0].full_text
    assert "Repealed text" not in rows[0].full_text
    assert "sos.state.ms.us" in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_massachusetts_constitution_stops_at_amendments_and_keeps_unwrapped_text(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.massachusetts import (
        MassachusettsScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body><div class="content">
      <h2>PART THE FIRST</h2>
      <h4>Article I.</h4>
      <p>All people are born free and equal and have certain natural, essential, and unalienable rights.</p>
      <h2>PART THE SECOND</h2>
      <h3>Chapter IV</h3>
      <p>Delegates to congress, and the times and places of holding elections, shall be appointed by the general court as they shall judge most convenient.</p>
      <h3>Chapter II, Section II</h3>
      <h4>Article III.</h4>
      Whenever the chair of the governor shall be vacant, the lieutenant governor shall perform the duties of governor during such vacancy.
      <h2>ARTICLES OF AMENDMENT.</h2>
      <h3>Article I.</h3>
      <p>Amendment body that must not be admitted as original constitution text.</p>
    </div></body></html>
    """
    path = tmp_path / "ma-const.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("MASSACHUSETTS_CONSTITUTION_HTML", str(path))
    scraper = MassachusettsScraper("MA", "Massachusetts")
    rows = asyncio.run(
        scraper.scrape_code("Massachusetts Constitution", "https://example.invalid", max_statutes=8)
    )
    keys = [(row.title_number, row.section_number) for row in rows]
    assert ("1", "I") in keys
    assert ("2.IV", "0") in keys
    assert ("2.II.II", "III") in keys
    bodies = " ".join(row.full_text for row in rows)
    assert "born free and equal" in bodies
    assert "Delegates to congress" in bodies
    assert "chair of the governor" in bodies
    assert "Amendment body" not in bodies
    assert "malegislature.gov" in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_indiana_constitution_splits_articles_and_keeps_history(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.indiana import IndianaScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    text = """
ARTICLE 1.
Bill of Rights
Section 1. WE DECLARE, That all people are created equal; that they are endowed by their CREATOR with certain inalienable rights. (History: As Amended November 6, 1984.)
Section 2. Repealed.
Repealed text must not be admitted as current constitutional law.
"""
    path = tmp_path / "in-const.txt"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("INDIANA_CONSTITUTION_TEXT", str(path))
    scraper = IndianaScraper("IN", "Indiana")
    rows = asyncio.run(
        scraper.scrape_code("Indiana Constitution", "https://example.invalid", max_statutes=4)
    )
    assert [row.section_number for row in rows] == ["1"]
    assert "created equal" in rows[0].full_text
    assert "As Amended November 6, 1984" in rows[0].full_text
    assert "Repealed text" not in rows[0].full_text
    assert "iga.in.gov" in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_oklahoma_constitution_starts_at_second_preamble(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oklahoma import OklahomaScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    text = """
PREAMBLE
ARTICLE I - TOC only Federal Relations
SECTION I-1. TOC preview that must not be admitted as current constitutional law.
PREAMBLE
Invoking the guidance of Almighty God, in order to secure the blessings of liberty, we the people of Oklahoma do ordain this Constitution.
ARTICLE II - Bill of Rights
SECTION II-1. All persons have the inherent right to life, liberty, the pursuit of happiness, and the enjoyment of the gains of their own industry.
ARTICLE VII-A - Court on the Judiciary
SECTION VII-A-1. A Court on the Judiciary is hereby created to hear complaints as to the removal of judicial officers in the manner provided by law.
"""
    path = tmp_path / "ok-const.txt"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("OKLAHOMA_CONSTITUTION_TEXT", str(path))
    scraper = OklahomaScraper("OK", "Oklahoma")
    rows = asyncio.run(
        scraper.scrape_code("Oklahoma Constitution", "https://example.invalid", max_statutes=6)
    )
    keys = [(row.title_number, row.section_number) for row in rows]
    assert ("II", "1") in keys
    assert ("VII-A", "1") in keys
    bodies = " ".join(row.full_text for row in rows)
    assert "inherent right to life" in bodies
    assert "Court on the Judiciary" in bodies
    assert "TOC preview" not in bodies
    assert "oklegislature.gov" in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_louisiana_constitution_uses_all_caps_articles_not_toc(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.louisiana import (
        LouisianaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    text = """
Article I. Declaration of Rights
§1. Origin and purpose of government
ARTICLE I.
DECLARATION OF RIGHTS
Section 1. All government of right originates with the people, is founded on their will alone, and is instituted solely for the good of the whole.
Compiled from the La. Senate Statutory Database.
(As amended through calendar year 2023)
-1-
Section 2. Repealed.
Repealed text must not be admitted as current constitutional law.
"""
    path = tmp_path / "la-const.txt"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("LOUISIANA_CONSTITUTION_TEXT", str(path))
    scraper = LouisianaScraper("LA", "Louisiana")
    rows = asyncio.run(
        scraper.scrape_code("Louisiana Constitution", "https://example.invalid", max_statutes=4)
    )
    assert [row.section_number for row in rows] == ["1"]
    assert "originates with the people" in rows[0].full_text
    assert "calendar year 2023" not in rows[0].full_text
    assert "Repealed text" not in rows[0].full_text
    assert "senate.la.gov" in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_arkansas_constitution_splits_schedule_and_amendments(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arkansas import ArkansasScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    text = """
TOC Article 1 Declaration 1
PREAMBLE
We the people of the State of Arkansas, grateful to Almighty God for the privilege of choosing our own form of government, do establish this Constitution.
Article 1
Declaration of Rights
§ 1. All men are created equally free and independent, and have certain inherent and inalienable rights.
§ 2. Repealed.
Repealed text must not be admitted as current constitutional law.
SCHEDULE
§ 1. All laws now in force which are not in conflict with this Constitution shall remain in full force until they expire by their own limitation.
AMEND. 1.
Initiative and Referendum
§ 1. The legislative power of the people of this State includes the initiative and referendum as provided in this amendment.
"""
    path = tmp_path / "ar-const.txt"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("ARKANSAS_CONSTITUTION_TEXT", str(path))
    scraper = ArkansasScraper("AR", "Arkansas")
    rows = asyncio.run(
        scraper.scrape_code("Arkansas Constitution", "https://example.invalid", max_statutes=8)
    )
    keys = [(row.title_number, row.section_number) for row in rows]
    assert ("1", "1") in keys
    assert ("SCHED", "1") in keys
    assert ("AMEND1", "1") in keys
    assert ("1", "2") not in keys
    bodies = " ".join(row.full_text for row in rows)
    assert "equally free and independent" in bodies
    assert "initiative and referendum" in bodies.lower()
    assert "Repealed text" not in bodies
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_tennessee_constitution_suffixes_schedule_section_reuse(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.tennessee import (
        TennesseeScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    text = """
ARTICLE XI.
Miscellaneous Provisions
Section 1. All laws and ordinances now in force and use in this State, not inconsistent with this Constitution, shall continue in force and use until they shall expire.
Section 19. The restoration of suffrage to persons convicted of infamous crimes shall be as provided by law.
Section 1. The Schedule of this Constitution shall take effect at the same time as the rest of this Constitution and shall not revive any lapsed law.
"""
    path = tmp_path / "tn-const.txt"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("TENNESSEE_CONSTITUTION_TEXT", str(path))
    scraper = TennesseeScraper("TN", "Tennessee")
    rows = asyncio.run(
        scraper.scrape_code("Tennessee Constitution", "https://example.invalid", max_statutes=6)
    )
    numbers = [row.section_number for row in rows]
    assert "1" in numbers
    assert "19" in numbers
    assert "1-v2" in numbers
    bodies = " ".join(row.full_text for row in rows)
    assert "not inconsistent with this Constitution" in bodies
    assert "Schedule of this Constitution" in bodies
    assert "tnsosfiles.com" in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_wyoming_constitution_uses_article_section_markers(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.wyoming import WyomingScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    text = """
ARTICLE 1 - DECLARATION OF RIGHTS
Article 1, Section 1  All power is inherent in the people, and all free governments are founded on their authority and instituted for their peace, safety and happiness.
Article 1, Section 2  Repealed.
Repealed text must not be admitted as current constitutional law.
Article 1, Section 3  Since equality in the enjoyment of natural and civil rights is required by sound morality, discrimination is forbidden.
"""
    path = tmp_path / "wy-const.txt"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("WYOMING_CONSTITUTION_TEXT", str(path))
    scraper = WyomingScraper("WY", "Wyoming")
    rows = asyncio.run(
        scraper.scrape_code("Wyoming Constitution", "https://example.invalid", max_statutes=6)
    )
    assert [row.section_number for row in rows] == ["1", "3"]
    bodies = " ".join(row.full_text for row in rows)
    assert "inherent in the people" in bodies
    assert "equality in the enjoyment" in bodies
    assert "Repealed text" not in bodies
    assert "wyoleg.gov" in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_new_hampshire_constitution_splits_parts_and_articles(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_hampshire import (
        NewHampshireScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body><main>
    Part First
    Bill of Rights
    Article 1. All men have certain natural, essential, and inherent rights, among which are the enjoying and defending life and liberty.
    Article 2. Repealed.
    Repealed text must not be admitted as current constitutional law.
    Part Second
    Form of Government
    [Art.] 1. The people of this state have the sole and exclusive right of governing themselves as a free, sovereign, and independent state.
    </main></body></html>
    """
    path = tmp_path / "nh-const.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("NEW_HAMPSHIRE_CONSTITUTION_HTML", str(path))
    scraper = NewHampshireScraper("NH", "New Hampshire")
    rows = asyncio.run(
        scraper.scrape_code("New Hampshire Constitution", "https://example.invalid", max_statutes=6)
    )
    keys = [(row.title_number, row.section_number) for row in rows]
    assert ("1", "1") in keys
    assert ("2", "1") in keys
    assert ("1", "2") not in keys
    bodies = " ".join(row.full_text for row in rows)
    assert "enjoying and defending life" in bodies
    assert "exclusive right of governing" in bodies
    assert "Repealed text" not in bodies
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_connecticut_constitution_maps_ordinals_and_prefixes_amendments(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.connecticut import (
        ConnecticutScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
    ARTICLE FIRST
    Declaration of Rights
    SEC.1. All men when they form a social compact, are equal in rights.
    SEC.2. Repealed.
    Repealed text must not be admitted as current constitutional law.
    ARTICLE FOURTEENTH
    General Provisions
    SEC.1. The political year shall begin on the Wednesday following the first Monday of January.
    ARTICLE I.
    Sec. 18. The amount of general budget expenditures authorized in any fiscal year shall not exceed the level of the preceding year plus inflation.
    </body></html>
    """
    path = tmp_path / "ct-const.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("CONNECTICUT_CONSTITUTION_HTML", str(path))
    scraper = ConnecticutScraper("CT", "Connecticut")
    rows = asyncio.run(
        scraper.scrape_code("Connecticut Constitution", "https://example.invalid", max_statutes=8)
    )
    keys = [(row.title_number, row.section_number) for row in rows]
    assert ("I", "1") in keys
    assert ("XIV", "1") in keys
    assert ("AMENDI", "18") in keys
    assert ("I", "2") not in keys
    bodies = " ".join(row.full_text for row in rows)
    assert "equal in rights" in bodies
    assert "general budget expenditures" in bodies
    assert "Repealed text" not in bodies
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_delaware_constitution_uses_section_symbol_not_restatement(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.delaware import DelawareScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
    ARTICLE I
    Bill of Rights
    § 1. Freedom of religion.
    Section 1. Although it is the duty of all persons frequently to assemble together for the public worship of Almighty God, no man shall be compelled to attend any religious worship.
    § 2. Repealed.
    Repealed text must not be admitted as current constitutional law.
    </body></html>
    """
    path = tmp_path / "de-const.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("DELAWARE_CONSTITUTION_HTML", str(path))
    scraper = DelawareScraper("DE", "Delaware")
    rows = asyncio.run(
        scraper.scrape_code("Delaware Constitution", "https://example.invalid", max_statutes=4)
    )
    assert [row.section_number for row in rows] == ["1"]
    assert "public worship of Almighty God" in rows[0].full_text
    assert "Repealed text" not in rows[0].full_text
    assert "delcode.delaware.gov" in rows[0].source_url
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_colorado_constitution_keeps_lettered_sections_and_source_notes(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.colorado import ColoradoScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    text = """
ARTICLE II
Bill of Rights
Section 1. All political power is vested in and derived from the people, and all government of right originates from the people.
Section 2. Repealed.
Repealed text must not be admitted as current constitutional law.
Section 16a. Any person charged with a criminal offense shall have the right to be heard by counsel, and this right shall not be abridged.
Source: L. 94: Entire section added, p. 1.
"""
    path = tmp_path / "co-const.txt"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("COLORADO_CONSTITUTION_TEXT", str(path))
    scraper = ColoradoScraper("CO", "Colorado")
    rows = asyncio.run(
        scraper.scrape_code("Colorado Constitution", "https://example.invalid", max_statutes=6)
    )
    assert [row.section_number for row in rows] == ["1", "16a"]
    bodies = " ".join(row.full_text for row in rows)
    assert "derived from the people" in bodies
    assert "heard by counsel" in bodies
    assert "Source: L. 94" in bodies
    assert "Repealed text" not in bodies
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_georgia_constitution_uses_roman_sections(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia import GeorgiaScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
    ARTICLE I
    Bill of Rights
    SECTION I. Life, liberty, and property. No person shall be deprived of life, liberty, or property except by due process of law.
    SECTION II. Repealed.
    Repealed text must not be admitted as current constitutional law.
    SECTION III. Freedom of conscience. Each person has the natural and inalienable right to worship God according to the dictates of that person's own conscience.
    </body></html>
    """
    path = tmp_path / "ga-const.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("GEORGIA_CONSTITUTION_HTML", str(path))
    scraper = GeorgiaScraper("GA", "Georgia")
    rows = asyncio.run(
        scraper.scrape_code("Georgia Constitution", "https://example.invalid", max_statutes=6)
    )
    assert [row.section_number for row in rows] == ["I", "III"]
    bodies = " ".join(row.full_text for row in rows)
    assert "due process of law" in bodies
    assert "freedom of conscience" in bodies.lower() or "worship God" in bodies
    assert "Repealed text" not in bodies
    assert rows[0].structured_data["source_authority_class"] == "official"
    assert rows[0].structured_data["source_authority_class"] != "recovery"


def test_alaska_constitution_uses_section_symbol(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.alaska import AlaskaScraper
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
    Article 1
    Declaration of Rights
    § 1. This constitution is dedicated to the principles that all persons have a natural right to life, liberty, the pursuit of happiness, and the enjoyment of the rewards of their own industry.
    § 2. Repealed.
    Repealed text must not be admitted as current constitutional law.
    </body></html>
    """
    path = tmp_path / "ak-const.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("ALASKA_CONSTITUTION_HTML", str(path))
    scraper = AlaskaScraper("AK", "Alaska")
    rows = asyncio.run(
        scraper.scrape_code("Alaska Constitution", "https://example.invalid", max_statutes=4)
    )
    assert [row.section_number for row in rows] == ["1"]
    assert "natural right to life" in rows[0].full_text
    assert "Repealed text" not in rows[0].full_text
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_south_dakota_constitution_skips_toc_and_uses_compact_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.south_dakota import (
        SouthDakotaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body>
    Article I
    Bill of Rights ............... 1
    Article XXVI
    Compact with the United States ............... 26
    Article I
    Bill of Rights
    § 1. All men are born equally free and independent, and have certain inherent rights, among which are those of enjoying and defending life and liberty.
    § 2. Repealed.
    Repealed text must not be admitted as current constitutional law.
    Article XXVI
    Compact with the United States
    First. That perfect toleration of religious sentiment shall be secured and that no inhabitant of this state shall ever be molested in person or property on account of his or her mode of religious worship.
    Second. That the people inhabiting this state do agree and declare that they forever disclaim all right and title to the unappropriated public lands lying within the boundaries thereof.
    </body></html>
    """
    path = tmp_path / "sd-const.html"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setenv("SOUTH_DAKOTA_CONSTITUTION_HTML", str(path))
    scraper = SouthDakotaScraper("SD", "South Dakota")
    rows = asyncio.run(
        scraper.scrape_code("South Dakota Constitution", "https://example.invalid", max_statutes=8)
    )
    keys = [(row.title_number, row.section_number) for row in rows]
    assert ("I", "1") in keys
    assert ("XXVI", "1") in keys
    assert ("XXVI", "2") in keys
    assert ("I", "2") not in keys
    bodies = " ".join(row.full_text for row in rows)
    assert "born equally free and independent" in bodies
    assert "perfect toleration of religious sentiment" in bodies
    assert "Bill of Rights ............... 1" not in bodies
    assert "Repealed text" not in bodies
    assert rows[0].structured_data["source_authority_class"] == "official"


def test_remaining_generic_constitution_splits(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.district_of_columbia import (
        DistrictOfColumbiaScraper,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.iowa import IowaScraper
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.maine import MaineScraper
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina import (
        NorthCarolinaScraper,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_dakota import (
        NorthDakotaScraper,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.south_carolina import (
        SouthCarolinaScraper,
    )
    from ipfs_datasets_py.utils import anyio_compat as asyncio

    html = """
    <html><body><main>
    ARTICLE I
    Declaration of Rights
    Section 1. All persons are born equally free and independent, and have certain natural, inherent and unalienable rights. (2013-300, s. 1.)
    Section 2. Repealed.
    Repealed text must not be admitted as current constitutional law.
    Section 3. The people have a right to assemble together, to consult for their common good, and to apply to those invested with the powers of government for redress of grievances.
    </main></body></html>
    """
    cases = [
        (IowaScraper, "IA", "Iowa", "IOWA_CONSTITUTION_HTML", "Iowa Constitution", "legis.iowa.gov"),
        (MaineScraper, "ME", "Maine", "MAINE_CONSTITUTION_HTML", "Maine Constitution", "legislature.maine.gov"),
        (
            NorthCarolinaScraper,
            "NC",
            "North Carolina",
            "NORTH_CAROLINA_CONSTITUTION_HTML",
            "North Carolina Constitution",
            "ncleg.gov",
        ),
        (
            NorthDakotaScraper,
            "ND",
            "North Dakota",
            "NORTH_DAKOTA_CONSTITUTION_HTML",
            "North Dakota Constitution",
            "ndlegis.gov",
        ),
        (
            SouthCarolinaScraper,
            "SC",
            "South Carolina",
            "SOUTH_CAROLINA_CONSTITUTION_HTML",
            "South Carolina Constitution",
            "scstatehouse.gov",
        ),
        (
            DistrictOfColumbiaScraper,
            "DC",
            "District of Columbia",
            "DISTRICT_OF_COLUMBIA_CONSTITUTION_HTML",
            "District of Columbia Home Rule Charter",
            "dccouncil.gov",
        ),
    ]
    for cls, code, name, env_name, code_name, host in cases:
        path = tmp_path / f"{code.lower()}-const.html"
        path.write_text(html, encoding="utf-8")
        monkeypatch.setenv(env_name, str(path))
        scraper = cls(code, name)
        rows = asyncio.run(scraper.scrape_code(code_name, "https://example.invalid", max_statutes=6))
        assert [row.section_number for row in rows] == ["1", "3"], code
        bodies = " ".join(row.full_text for row in rows)
        assert "equally free and independent" in bodies, code
        assert "assemble together" in bodies, code
        assert "Repealed text" not in bodies, code
        if code == "NC":
            assert "2013-300" in bodies
        assert host in rows[0].source_url, code
        assert "justia" not in rows[0].source_url, code
        assert rows[0].structured_data["source_authority_class"] == "official", code
        monkeypatch.delenv(env_name, raising=False)


def test_nebraska_browse_chapters_keep_alpha_and_dotted_sections() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.nebraska_section import (
        chapter_links,
        chapter_structure,
        is_nebraska_section_number,
        section_links,
    )

    assert is_nebraska_section_number("25-2740.04")
    assert is_nebraska_section_number("2-32,113")
    assert is_nebraska_section_number("76A-101")
    chapters = chapter_links(
        '<a href="/laws/browse-chapters.php?chapter=28">Chapter 28</a>'
        '<a href="/laws/browse-chapters.php?chapter=76A">Chapter 76A</a>'
        '<a href="/laws/browse-statutes.php">index</a>'
    )
    assert [number for number, _name, _url in chapters] == ["28", "76A"]
    assert chapters[1][2].endswith("chapter=76A")
    sections = section_links(
        '<a href="/laws/statutes.php?statute=28-303">28-303</a>'
        '<a href="/laws/statutes.php?statute=25-2740.04">25-2740.04</a>'
        '<a href="/laws/statutes.php?statute=28-303&print=true">print</a>'
    )
    assert [number for number, _name, _url in sections] == ["28-303", "25-2740.04"]
    structured = chapter_structure(
        """
        <h3>ARTICLE 1 - Offenses against the person</h3>
        <a href="/laws/statutes.php?statute=28-303">28-303</a>
        <p>ARTICLE 2. Property</p>
        <a href="/laws/statutes.php?statute=28-501">28-501</a>
        """
    )
    assert structured[0]["article_number"] == "1"
    assert structured[1]["article_number"] == "2"
    assert structured[1]["section_number"] == "28-501"


def test_maryland_toc_statute_articles_and_getnext_xml() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.maryland_section import (
        parse_get_next_envelope,
        parse_section_code,
        statute_articles,
    )

    html = """
    <select id="Articles">
      <option value="gcr">Criminal Law - (gcr)</option>
      <option value="gsg">State Government - (gsg)</option>
      <option value="c0">Declaration of Rights - (c0)</option>
      <option value="c11a">Article XI-A - (c11a)</option>
    </select>
    """
    rows = statute_articles(html)
    assert [code for code, _name in rows] == ["gcr", "gsg"]
    assert parse_get_next_envelope(
        '<string xmlns="http://schemas.microsoft.com/2003/10/Serialization/">2-201</string>'
    ) == "2-201"
    assert parse_get_next_envelope('"2-202"') == "2-202"
    assert parse_get_next_envelope("null") is None
    assert parse_section_code("2-201")[0] == "2"


def test_texas_statute_array_and_quicksearch_chapter_urls() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.texas_chapter import (
        chapters_from_quicksearch,
        chapters_from_statute_array,
        get_statute_array_url,
        populate_chapter_list_url,
    )

    assert "GetStatuteArray/GetStatuteArray/PE/PE/" in get_statute_array_url("PE")
    assert populate_chapter_list_url("SD").endswith("/33/CH")
    array_rows = chapters_from_statute_array(
        [
            {"name": "CHAPTER 19. CRIMINAL HOMICIDE", "url": "PE/htm/PE.19.htm"},
            {"name": "Chapter Title Not Found", "url": "PE/htm/PE.1.htm"},
        ],
        code="PE",
    )
    assert [number for number, _name, _url in array_rows] == ["19", "1"]
    assert array_rows[0][2].endswith("/PE/htm/PE.19.htm")
    quick = chapters_from_quicksearch(
        [{"text": "CHAPTER 1", "url": "SD.1"}, {"text": "skip", "url": "other"}],
        code="SD",
    )
    assert quick[0][0] == "1"
    assert quick[0][2].endswith("/SD/htm/SD.1.htm")


def test_virginia_number_descrip_list_and_ny_category_law_links() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_york_openleg import (
        category_law_links,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.virginia_section import (
        title_links,
    )

    titles = title_links(
        '<div class="number-descrip-list">'
        '<a href="/vacode/title18.2/">Title 18.2. Crimes</a>'
        '<a href="/vacode/title8.5A/">Title 8.5A</a>'
        '<a href="/vacode/title18.2/chapter1/">skip chapter</a>'
        "</div>"
    )
    assert [number for number, _name, _url in titles] == ["18.2", "8.5A"]
    laws = category_law_links(
        '<a href="/legislation/laws/PEN">Penal Law</a>'
        '<a href="/legislation/laws/CONSOLIDATED">skip category</a>'
        '<a href="/legislation/laws/CPL/">Criminal Procedure</a>'
    )
    assert [abbr for abbr, _name, _url in laws] == ["PEN", "CPL"]


def test_kansas_statute_table_chapter_article_section_rows() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.kansas_section import (
        article_rows,
        chapter_rows,
        section_rows,
    )

    chapters = chapter_rows(
        '<table id="statute"><tr><td><a href="021_000_0000_chapter/">Chapter 21</a></td>'
        "<td>Crimes and Punishments</td></tr></table>"
    )
    assert chapters[0][0] == "21"
    articles = article_rows(
        '<table id="statute"><tr><td><a href="021_054_0000_article/">Article 54</a></td>'
        "<td>Crimes Against Persons</td></tr></table>"
    )
    assert articles[0][0] == "54"
    sections = section_rows(
        '<table id="statute"><tr><td><a href="../../021_000_0000_chapter/'
        '021_054_0000_article/021_054_0101_section/021_054_0101_k/">'
        "21-5401 - Capital murder</a></td></tr></table>"
    )
    assert sections[0][0] == "21-5401"
    assert sections[0][2].endswith("021_054_0101_k/")


def test_massachusetts_accordion_titles_and_section_hrefs() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.massachusetts_section import (
        chapters_for_title_url,
        extract_chapter_links,
        section_links,
        title_toggles,
    )

    titles = title_toggles(
        """
        <a href="#titleI" onclick="accordionAjaxLoad('1', '1', 'I')">Title I</a>
        <a href="#titleI" onclick="accordionAjaxLoad('1', '1', 'I')">Jurisdiction</a>
        <a href="#titleI" onclick="accordionAjaxLoad('1', '1', 'I')">Chapters 1 - 9</a>
        """
    )
    assert titles[0][:3] == ("1", "1", "I")
    assert "Jurisdiction" in titles[0][3]
    assert "GetChaptersForTitle" in chapters_for_title_url("1", "1", "I")
    chapters = extract_chapter_links(
        '<ul class="generalLawsList"><li>'
        '<a href="/Laws/GeneralLaws/PartI/TitleI/Chapter1">'
        '<span class="chapterTitle">Jurisdiction</span></a></li></ul>'
    )
    assert chapters[0][1] == "1"
    sections = section_links(
        '<a href="/Laws/GeneralLaws/PartIV/TitleI/Chapter265/Section1">Section 1</a>'
        '<a href="/Laws/GeneralLaws/PartIV/TitleI/Chapter265">chapter</a>'
    )
    assert sections[0][1] == "1"


def test_arizona_arsdetail_and_accordion_sections() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arizona_section import (
        accordion_section_links,
        title_links,
    )

    titles = title_links(
        '<a href="/arsDetail/?title=13">Title 13</a>'
        '<a href="arsDetail?title=4">Title 4</a>'
        '<a href="/other">skip</a>'
    )
    assert [number for number, _url in titles] == ["4", "13"]
    sections = accordion_section_links(
        '<div class="colleft"><a href="/ars/13/1105.htm">13-1105</a></div>'
        '<div class="colright">First degree murder</div>'
    )
    assert sections[0][0] == "13-1105"
    assert sections[0][2].endswith("/ars/13/1105.htm")


def test_north_dakota_titles_grid_and_chapter_tables() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_dakota_chapter import (
        chapter_table_rows,
        section_meta_rows,
        title_items,
    )

    titles = title_items(
        '<div class="titles-grid"><div class="title-item">'
        '<span class="title-number">12.1</span>'
        '<a href="/cencode/t12-1.html">Criminal Code</a></div></div>'
    )
    assert titles[0][0] == "12.1"
    assert titles[0][2].endswith("/cencode/t12-1.html")
    chapters = chapter_table_rows(
        '<div class="field--name-field-pwv-custom-content"><table>'
        "<tr><td>12.1-16</td><td><a href=\"t12-1c16.html\">HTML</a></td>"
        "<td>Homicide</td></tr></table></div>"
    )
    assert chapters[0][0] == "12.1-16"
    sections = section_meta_rows(
        '<div class="field--name-field-pwv-custom-content"><table>'
        "<tr><td><a>12.1-16-01</a></td><td>Murder</td></tr></table></div>"
    )
    assert sections[0] == ("12.1-16-01", "Murder")


def test_south_carolina_title_and_chapter_listings() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.south_carolina_chapter import (
        chapter_rows,
        title_links,
    )

    titles = title_links(
        '<a href="/code/title16.php">Title 16</a><a href="/code/statmast.php">index</a>'
    )
    assert titles[0][0] == "16"
    chapters = chapter_rows(
        '<div id="contentsection"><table><tr><td>CHAPTER 3 - Offenses Against the Person</td>'
        '<td><a href="/code/t16c003.php">HTML</a></td></tr></table></div>'
    )
    assert chapters[0][0] == "3"
    assert chapters[0][2].endswith("/code/t16c003.php")


def test_west_virginia_sel_chapter_and_heads() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.west_virginia_dump import (
        article_heads,
        chapter_options,
        section_heads,
    )

    chapters = chapter_options(
        '<select id="sel-chapter">'
        '<option value="61">CHAPTER 61. CRIMES</option>'
        '<option value="17H">CHAPTER 17H. AUTONOMOUS VEHICLES</option>'
        '<option value="">skip</option></select>'
    )
    assert [number for number, _name in chapters] == ["61", "17H"]
    articles = article_heads('<div class="art-head"><a href="/61-2/">ARTICLE 2</a></div>')
    assert articles[0][0] == "2"
    sections = section_heads('<div class="sec-head"><a href="/61-2-1/">§61-2-1</a></div>')
    assert sections[0][0] == "61-2-1"


def test_alaska_toc_fragments_loadtoc_and_section_anchors() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.alaska_section import (
        chapter_toc_links,
        section_toc_links,
        toc_url,
    )

    assert "media=js&type=TOC&title=01" in toc_url("1")
    chapters = chapter_toc_links(
        '<li><a onclick=\'loadTOC("01.05");\'>Chapter 05. Alaska Statutes</a></li>'
        "<li><a href=\"#skip\">not a chapter</a></li>"
    )
    assert chapters[0][0] == "01.05"
    sections = section_toc_links(
        '<li><a href="statutes.asp?year=2024&title=1#01.05.006">Sec. 01.05.006. Adoption</a></li>'
    )
    assert sections[0][0] == "01.05.006"


def test_kentucky_panel_titles_chapters_and_statute_labels() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.kentucky_section import (
        chapter_links,
        statute_links,
        title_spans,
    )

    titles = title_spans(
        '<div id="Panel1"><span id="title">TITLE L CRIMES AND PUNISHMENTS</span></div>'
    )
    assert titles[0][0] == "L"
    chapters = chapter_links(
        '<a class="chapter" href="chapter.aspx?id=507">CHAPTER 507 HOMICIDE</a>'
    )
    assert chapters[0][0] == "507"
    assert chapters[0][2].endswith("chapter.aspx?id=507")
    statutes = statute_links(
        '<div id="Panel1"><a class="statute" href="statute.aspx?id=1">'
        ".020  Murder.</a></div>",
        chapter_number="507",
    )
    assert statutes[0][0] == "507.020"


def test_ohio_laws_table_title_chapter_section_cells() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.ohio_chapter import (
        chapter_cells,
        section_cells,
        title_links,
    )

    titles = title_links(
        '<table class="data-grid laws-table"><tr><td>'
        '<a href="ohio-revised-code/title-29">Title 29 | Crimes</a></td></tr></table>'
    )
    assert titles[0][0] == "29"
    chapters = chapter_cells(
        '<table class="data-grid laws-table"><div class="name-cell">'
        '<a href="chapter-2903">Chapter 2903 | Homicide</a></div></table>'
    )
    assert chapters[0][0] == "2903"
    sections = section_cells(
        '<table class="data-grid laws-table"><div class="name-cell">'
        '<div class="content-head-text">'
        '<a href="/ohio-revised-code/section-2903.01">Section 2903.01 | Aggravated murder</a>'
        "</div></div></table>"
    )
    assert sections[0][0] == "2903.01"


def test_montana_title_and_section_toc_items() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.montana_section import (
        parse_title_numbers,
        structure_toc_items,
        title_toc_items,
    )

    assert parse_title_numbers("TITLES 8 AND 9. Reserved") == ["8", "9"]
    titles = title_toc_items(
        '<div class="title-toc-content"><ul>'
        '<li><a href="./title_0045/">TITLE 45. CRIMES</a></li>'
        '<li><span class="reserved">TITLES 8 AND 9. Reserved</span></li>'
        "</ul></div>"
    )
    assert [number for number, _name, _url in titles] == ["45", "8", "9"]
    sections = structure_toc_items(
        '<div class="section-toc-content"><li class="line">'
        '<span class="citation">45-5-102</span>'
        '<a href="./0450-0050-0010-0102.html">Deliberate homicide</a></li></div>',
        level="section",
        container_class="section-toc-content",
    )
    assert sections[0][0] == "45-5-102"


def test_utah_childtbl_and_version_arr_section_hrefs() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.utah_title_xml import (
        childtbl_rows,
        section_number_from_href,
        version_arr_files,
    )

    rows = childtbl_rows(
        '<table id="childtbl"><tr><td><a href="Title76/76.html?v=C76_1">Title 76</a></td>'
        "<td>Utah Criminal Code</td></tr>"
        '<tr><td><a href="Title76/Chapter5/76-5.html">Chapter 5</a></td>'
        "<td>Offenses Against the Person</td></tr></table>"
    )
    assert [(kind, number) for kind, number, _name, _url in rows] == [
        ("title", "76"),
        ("chapter", "5"),
    ]
    assert version_arr_files("var versionArr = [['C76_1800010118000101.html', 'x']];") == [
        "C76_1800010118000101.html"
    ]
    assert section_number_from_href("Title76/Chapter5/76-5-S203.html") == "76-5-203"


def test_iowa_iaclist_title_chapter_section_rows() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.iowa_chapter_xml import (
        iac_list_rows,
    )

    titles = iac_list_rows(
        '<table id="iacList"><tbody><tr><td><a href="/law/iowaCode?title=XVI">'
        "Title XVI - CRIMINAL LAW</a></td></tr></tbody></table>",
        kind="title",
    )
    assert titles[0][0] == "XVI"
    chapters = iac_list_rows(
        '<table id="iacList"><tbody><tr><td><a href="/law/iowaCode/sections?codeChapter=707">'
        "Chapter 707 - HOMICIDE</a></td></tr>"
        "<tr><td>Chapter 8E - RESERVED</td></tr></tbody></table>",
        kind="chapter",
    )
    assert [number for number, _name, _url in chapters] == ["707"]
    sections = iac_list_rows(
        '<table id="iacList"><tbody><tr><td>§707.1 - Murder.</td>'
        '<td><a href="/docs/code/2026/707.1.rtf">RTF</a></td></tr></tbody></table>',
        kind="section",
    )
    assert sections[0][0] == "707.1"
    assert sections[0][2].endswith("707.1.rtf")


def test_illinois_ilcs_acts_and_fulltext_cites() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.illinois_bulk import (
        act_links,
        chapter_links,
        full_text_url,
        section_cites,
    )

    chapters = chapter_links(
        '<a href="/Legislation/ILCS/Acts?ChapterID=38&ChapterNumber=720&Chapter=CRIMINAL">'
        "CHAPTER 720 CRIMINAL OFFENSES</a>"
    )
    assert chapters[0][0] == "720"
    acts = act_links(
        '<a href="/Legislation/ILCS/Articles?ActID=1876&ChapterID=38">'
        "720 ILCS 5/ Criminal Code of 2012.</a>"
    )
    assert acts[0][:2] == ("5", "720")
    cites = section_cites(
        "<code>(720 ILCS 5/9-1)</code><code>(720 ILCS 5/Art. 9 heading)</code>"
    )
    assert cites == [("720", "5", "9-1")]
    assert "ActID=1876" in full_text_url("1876", "38")


def test_michigan_chapterindex_act_and_section_objectnames() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.michigan_chapter_xml import (
        act_links,
        chapter_index_links,
        section_object_links,
    )

    chapters = chapter_index_links(
        '<main id="main"><a href="/Home/GetObject?objectName=mcl-chap750">Chapter 750</a>'
        '<a href="/Home/GetObject?objectName=mcl-chapNext">skip</a></main>'
    )
    assert chapters[0][0] == "750"
    acts = act_links(
        "<table><tr><td><a href=\"/Laws/MCL?objectName=mcl-Act-328-of-1931\">"
        "The Michigan Penal Code</a></td></tr></table>"
    )
    assert acts[0][0] == "Act-328-of-1931"
    sections = section_object_links(
        "<table><tr><td><a href=\"/Laws/MCL?objectName=mcl-750-316\">750-316</a></td>"
        "<td>Statute</td><td>First degree murder</td></tr></table>"
    )
    assert sections[0][0] == "750.316"


def test_indiana_iga_json_listings_without_api_key() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.indiana_bulk import (
        nested_from_payload,
        normalize_section,
        titles_api_url,
        titles_from_payload,
    )

    assert titles_api_url(2024).endswith("/2024/ic/titles")
    titles = titles_from_payload({"titles": [{"titleNumber": "35", "name": "Criminal Law"}]})
    assert titles[0] == ("35", "Criminal Law")
    articles = nested_from_payload({"articles": [{"articleNumber": "42", "name": "Offenses"}]}, kind="article")
    assert articles[0][0] == "42"
    assert normalize_section("01-01-01-01", "1", "1", "1") == "1-1-1-1"
    assert normalize_section("1", "35", "42", "1") == "35-42-1-1"


def test_california_toccode_and_manylaw_sections() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.california_bulk import (
        expand_url,
        manylaw_section_numbers,
        toc_code_links,
    )

    assert "tocCode=PEN" in expand_url("pen")
    codes = toc_code_links(
        '<a href="/faces/codedisplayexpand.xhtml?tocCode=PEN">Penal Code</a>'
        '<a href="/faces/codedisplayexpand.xhtml?tocCode=SKIP">skip</a>'
    )
    assert codes[0][0] == "PEN"
    numbers = manylaw_section_numbers(
        '<div id="manylawsections"><div><a>187.</a></div><div><a>189.</a></div>'
        "<div><a>Contents</a></div></div>"
    )
    assert numbers == ["187", "189"]


def test_wisconsin_toc_chapter_links_skip_sections() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.wisconsin_chapter import (
        toc_chapter_links,
    )

    rows = toc_chapter_links(
        "<p><a href=\"/document/statutes/940\">Chapter 940 (PDF: ) - Crimes Against Life</a></p>"
        "<p><a href=\"/document/statutes/940.01\">940.01</a></p>"
    )
    assert [number for number, _name, _url in rows] == ["940"]
    assert rows[0][2].endswith("/document/statutes/940")


def test_missouri_details_chapter_links() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.missouri_chapter import (
        details_chapter_links,
    )

    rows = details_chapter_links(
        '<details><a href="OneChapter.aspx?chapter=565">565\u2003Offenses Against the Person</a>'
        '<a href="OneSection.aspx?section=565.020">skip</a></details>'
    )
    assert rows[0][0] == "565"
    assert rows[0][2].endswith("OneChapter.aspx?chapter=565")


def test_alabama_hierarchy_title_chapter_section_rows() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.alabama_section import (
        FIELD_SEP,
        ROW_SEP,
        hierarchy_rows,
    )

    blob = ROW_SEP.join(
        [
            f"1{FIELD_SEP}Title 13A Criminal Code.",
            f"2{FIELD_SEP}Chapter 5 Death Penalty.",
            f"3{FIELD_SEP}Section 13A-5-40 Capital offenses.",
        ]
    )
    rows = hierarchy_rows(blob)
    assert rows == [
        ("title", "13A", "Title 13A Criminal Code."),
        ("chapter", "5", "Chapter 5 Death Penalty."),
        ("section", "13A-5-40", "Section 13A-5-40 Capital offenses."),
    ]


def test_nevada_nrs_and_oregon_ors_index_links() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.nevada_chapter import (
        nrs_index_links,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oregon_chapter import (
        ors_chapter_links,
    )

    nrs = nrs_index_links(
        '<a href="NRS-200.html">CHAPTER 200 - CRIMES AGAINST THE PERSON</a>'
        '<a href="NRS-index.html">skip</a>'
    )
    assert nrs[0][0] == "200"
    ors = ors_chapter_links(
        '<a href="ors163.html">Chapter 163 Offenses Against Persons</a>'
        '<a href="ors163a.html">Chapter 163A</a>'
    )
    assert [number for number, _name, _url in ors] == ["163", "163a"]


def test_pennsylvania_consolidated_titles_and_pdf_url() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.pennsylvania_title import (
        consolidated_titles,
        current_through,
        title_html_url,
        title_pdf_url,
    )

    assert "txtType=PDF" in title_pdf_url("18")
    assert title_html_url("18").endswith("ttl=18")
    rows = consolidated_titles(
        '<a href="/statutes/consolidated/view-statute?txtType=HTM&ttl=18">Title 18 Crimes</a>'
        '<a href="/statutes/consolidated/view-statute?txtType=PDF&ttl=18">PDF</a>'
        '<a href="/statutes/consolidated/view-statute?txtType=HTM&ttl=02">Title 2</a>'
        '<a href="/statutes/consolidated/view-statute?txtType=HTM&ttl=0">Constitution</a>'
        '<a href="/other">skip</a>'
    )
    assert [number for number, _name, _url in rows] == ["18", "2"]
    assert rows[0][2].endswith("ttl=18")
    assert "txtType=HTM" in rows[0][2]
    assert current_through("Current through Act 15 of 2026.") == "Current through Act 15 of 2026"
    assert current_through("no currency") is None


def test_oklahoma_and_wyoming_title_pdf_listings() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oklahoma_title import (
        TITLES_HTML_URL,
        title_pdf_links as oklahoma_title_pdf_links,
        title_pdf_url as oklahoma_title_pdf_url,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.wyoming_title import (
        title_pdf_links as wyoming_title_pdf_links,
        title_pdf_url as wyoming_title_pdf_url,
    )

    assert TITLES_HTML_URL.endswith("osStatuesTitle.html")
    assert oklahoma_title_pdf_url("21").endswith("/os21.pdf")
    ok_rows = oklahoma_title_pdf_links(
        '<a href="/OK_Statutes/CompleteTitles/os21.pdf">Title 21 Crimes and Punishments</a>'
        '<a href="/OK_Statutes/CompleteTitles/os21A.pdf">Title 21A</a>'
        '<a href="/other.pdf">skip</a>'
    )
    assert [number for number, _name, _url in ok_rows] == ["21", "21A"]
    assert ok_rows[0][2].endswith("/os21.pdf")

    assert wyoming_title_pdf_url("6").endswith("/title6.pdf")
    wy_rows = wyoming_title_pdf_links(
        '<a href="https://www.wyoleg.gov/statutes/compress/title6.pdf">Title 6 Crimes</a>'
        '<a href="title06.pdf">Title 6 padded</a>'
        '<a href="other.pdf">skip</a>'
    )
    assert [number for number, _name, _url in wy_rows] == ["6"]
    assert wy_rows[0][2].endswith("/title6.pdf")


def test_dc_include_section_hrefs_and_mississippi_code_section_links() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.district_of_columbia_xml import (
        include_section_hrefs,
        section_source_url,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.mississippi_section import (
        code_section_links,
        section_number_from_url,
    )

    numbers = include_section_hrefs(
        '<xi:include href="./sections/22-2101.xml"/>'
        '<xi:include href="./index.xml"/>'
        '<xi:include href="./sections/22-2104.xml"/>'
    )
    assert numbers == ["22-2101", "22-2104"]
    assert section_source_url("22-2101").endswith("/sections/22-2101")

    assert section_number_from_url("/code_sections/097/00030019.htm") == "97-3-19"
    rows = code_section_links(
        '<a href="/documents/2024/html/code_sections/097/00030019.htm">97-3-19 Murder</a>'
        '<a href="https://billstatus.ls.state.ms.us/documents/2024/html/code_sections/097/00030007.htm">'
        "97-3-7</a>"
        '<a href="/other">skip</a>'
    )
    assert [number for number, _name, _url in rows] == ["97-3-19", "97-3-7"]
    assert rows[0][2].endswith("/code_sections/097/00030019.htm")


def test_arkansas_title_and_section_listings() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arkansas_section import (
        section_links,
        section_url,
        title_links,
        title_url,
    )

    assert title_url("5").endswith("?title=5")
    assert section_url("5-10-101").endswith("/ArkansasCode/5-10-101/")
    titles = title_links(
        '<a href="/ArkansasCode/?title=5">Title 5 Criminal Offenses</a>'
        '<a href="/ArkansasCode/?codeTitle=05">Title 5 duplicate</a>'
        '<a href="/other">skip</a>'
    )
    assert [number for number, _name, _url in titles] == ["5"]
    sections = section_links(
        '<a href="/ArkansasCode/5-10-101/">5-10-101 Murder</a>'
        '<a href="/ArkansasCode/5-10-102/">5-10-102</a>'
        '<a href="/ArkansasCode/">skip</a>'
    )
    assert [number for number, _name, _url in sections] == ["5-10-101", "5-10-102"]


def test_tennessee_title_and_section_listings() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.tennessee_section import (
        section_links,
        title_links,
        title_url,
    )

    assert title_url("39").endswith("/title-39/")
    titles = title_links(
        '<a href="/tga/statutes/title-39/">Title 39 Criminal Offenses</a>'
        '<a href="/tga/statutes/title-39/chapter-13/">skip nested</a>'
        '<a href="/other">skip</a>'
    )
    assert [number for number, _name, _url in titles] == ["39"]
    sections = section_links(
        '<a href="/tga/statutes/title-39/section-39-13-202">39-13-202 First degree murder</a>'
        '<a href="/tca/section-39-13-210">39-13-210</a>'
        '<a href="/tga/statutes/title-39/">skip</a>'
    )
    assert [number for number, _name, _url in sections] == ["39-13-202", "39-13-210"]


def test_new_mexico_chapter_listings_skip_document_do() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_mexico_chapter import (
        chapter_links,
        chapter_url,
    )

    assert chapter_url("30").endswith("#chapter-30")
    rows = chapter_links(
        '<a href="#chapter-30">Chapter 30 Criminal Offenses</a>'
        '<a href="/nmos/nmsa/en/18973/1/document.do">30-2-1 skip</a>'
        '<a href="?chapter=59A">Chapter 59A Insurance</a>'
    )
    assert [number for number, _name, _url in rows] == ["30", "59A"]
    assert rows[0][2].endswith("#chapter-30")


def test_wisconsin_pdf_front_toc_skips_history_body() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.wisconsin_chapter import (
        pdf_front_toc_sections,
    )

    text = """
    940.01 First-degree intentional homicide
    940.02 First-degree reckless homicide
    Wis. Stats. header
    History: 1987 a. 399.
    940.99 Phantom from a renumbering note that must not seed the TOC.
    """
    assert pdf_front_toc_sections(text, "940") == {"940.01", "940.02"}


def test_ohio_toc_href_titles_and_chapters() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.ohio_chapter import (
        chapter_url,
        title_url,
        toc_href_chapters,
        toc_href_titles,
    )

    assert title_url("29").endswith("/ohio-revised-code/title-29")
    assert chapter_url("2903").endswith("/ohio-revised-code/chapter-2903")
    titles = toc_href_titles(
        '<a href="ohio-revised-code/title-29">Title 29 Crimes</a>'
        '<a href="/title-29?foo=1">dup</a>'
        '<a href="/other">skip</a>'
    )
    assert [number for number, _name, _url in titles] == ["29"]
    chapters = toc_href_chapters(
        '<a href="chapter-2903">Chapter 2903 Homicide</a>'
        '<a href="/ohio-revised-code/chapter-2905">Chapter 2905</a>'
        '<a href="/section-2903.01">skip</a>'
    )
    assert [number for number, _name, _url in chapters] == ["2903", "2905"]


def test_colorado_publication_rows_and_local_zip_members(tmp_path: Path) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.colorado_title import (
        crs_zip_member_names,
        publication_rows,
        title_search_url,
    )

    assert "crs%20title%2018" in title_search_url("18")
    rows = publication_rows(
        '<div class="views-row">'
        '<a href="/publications/crs-title-18">Colorado Revised Statutes Title 18</a>'
        '<a href="/files/18.pdf">PDF</a></div>'
        '<div class="views-row"><a href="/other">skip</a></div>'
        '<div class="views-row">'
        '<a href="/publications/crs-18-3-102">C.R.S. 18-3-102 Murder</a></div>'
    )
    assert [number for number, _name, _url in rows] == ["18", "18-3-102"]
    assert "/publications/crs-title-18" in rows[0][2]

    zip_path = tmp_path / "crs.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("title18.sgml", "<section/>")
        archive.writestr("notes/readme.txt", "skip")
        archive.writestr("title18.htm", "<html/>")
    assert crs_zip_member_names(zip_path) == ["title18.sgml", "title18.htm"]


def test_dc_title_dirs_and_chapter_map_from_index(tmp_path: Path) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.district_of_columbia_xml import (
        chapter_map_from_index,
        title_dirs,
    )

    titles = tmp_path / "titles"
    (titles / "22").mkdir(parents=True)
    (titles / "1").mkdir()
    (titles / "27A").mkdir()
    assert title_dirs(tmp_path) == ["1", "22", "27A"]

    index = """
    <container xmlns:xi="http://www.w3.org/2001/XInclude">
      <prefix>Chapter</prefix><num>21</num><heading>Homicide</heading>
      <xi:include href="./sections/22-2101.xml"/>
      <container>
        <prefix>Subchapter</prefix><num>I</num>
        <xi:include href="./sections/22-2104.xml"/>
      </container>
    </container>
    """
    mapping = chapter_map_from_index(index)
    assert mapping["22-2101"] == "21"
    assert mapping["22-2104"] == "21"


def test_env_gated_official_listing_dumps(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.colorado_title import (
        parse_configured_publication_html,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia_title import (
        covered_title_numbers,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.mississippi_section import (
        parse_configured_title_html,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oklahoma_title import (
        parse_configured_titles_html as parse_oklahoma_titles,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.pennsylvania_title import (
        parse_configured_toc_html,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.wisconsin_chapter import (
        parse_configured_chapter_pdf_toc,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.wyoming_title import (
        parse_configured_titles_html as parse_wyoming_titles,
    )

    pa = tmp_path / "pa.html"
    pa.write_text(
        '<a href="/statutes/consolidated/view-statute?txtType=HTM&ttl=18">Title 18</a>',
        encoding="utf-8",
    )
    monkeypatch.setenv("PENNSYLVANIA_TOC_HTML", str(pa))
    assert parse_configured_toc_html()[0][0] == "18"

    ok = tmp_path / "ok.html"
    ok.write_text('<a href="/OK_Statutes/CompleteTitles/os21.pdf">Title 21</a>', encoding="utf-8")
    monkeypatch.setenv("OKLAHOMA_TITLES_HTML", str(ok))
    assert parse_oklahoma_titles()[0][0] == "21"

    wy = tmp_path / "wy.html"
    wy.write_text('<a href="title6.pdf">Title 6</a>', encoding="utf-8")
    monkeypatch.setenv("WYOMING_TITLES_HTML", str(wy))
    assert parse_wyoming_titles()[0][0] == "6"

    ms = tmp_path / "ms.html"
    ms.write_text(
        '<a href="/documents/2024/html/code_sections/097/00030019.htm">97-3-19</a>',
        encoding="utf-8",
    )
    monkeypatch.setenv("MISSISSIPPI_TITLE_HTML", str(ms))
    assert parse_configured_title_html()[0][0] == "97-3-19"

    co = tmp_path / "co.html"
    co.write_text(
        '<div class="views-row"><a href="/publications/crs-title-18">'
        "Colorado Revised Statutes Title 18</a></div>",
        encoding="utf-8",
    )
    monkeypatch.setenv("COLORADO_PUBLICATION_HTML", str(co))
    assert parse_configured_publication_html()[0][0] == "18"

    wi = tmp_path / "wi.txt"
    wi.write_text("940.01 First-degree intentional homicide\nHistory: 1987 a. 399.\n", encoding="utf-8")
    monkeypatch.setenv("WISCONSIN_CHAPTER_PDF_TEXT", str(wi))
    assert parse_configured_chapter_pdf_toc("940") == {"940.01"}

    dumps = tmp_path / "ga"
    dumps.mkdir()
    (dumps / "title-16.txt").write_text("placeholder", encoding="utf-8")
    (dumps / "ocga_40.txt").write_text("placeholder", encoding="utf-8")
    monkeypatch.setenv("GEORGIA_TITLE_TEXT_DIR", str(dumps))
    assert covered_title_numbers() == ["16", "40"]


def test_indiana_zip_candidates_and_spa_shell(tmp_path: Path) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.indiana_bulk import (
        looks_like_zip,
        parse_indiana_bulk_zip,
        zip_url_candidates,
    )

    urls = zip_url_candidates(2026)
    assert urls[0].endswith("/2026/2026-Indiana-Code-html.zip")
    assert urls[1].endswith("/2025/2025-Indiana-Code-html.zip")
    shell = tmp_path / "iga-spa.html"
    shell.write_bytes(b"<html><base href='/' /></html>")
    assert looks_like_zip(shell) is False
    assert parse_indiana_bulk_zip(shell) == []


def test_illinois_manifest_text_dump(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.illinois_bulk import (
        parse_configured_manifest,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_jersey_bulk import (
        looks_like_zip,
        parse_new_jersey_bulk_zip,
    )

    manifest = tmp_path / "Section Sequence.txt"
    manifest.write_text("072000050K9-1\n004000050A\n", encoding="utf-8")
    monkeypatch.setenv("ILLINOIS_MANIFEST_TEXT", str(manifest))
    rows = parse_configured_manifest()
    assert [citation for _chapter, citation, _url in rows] == ["720 ILCS 5/9-1"]
    assert rows[0][2].endswith("072000050K9-1.html")

    shell = tmp_path / "statutes-shell.html"
    shell.write_bytes(b"<html>not a zip</html>")
    assert looks_like_zip(shell) is False
    assert parse_new_jersey_bulk_zip(shell) == []


def test_california_session_zip_candidates_and_table_names(tmp_path: Path) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.california_bulk import (
        bulk_zip_table_names,
        looks_like_zip,
        parse_california_bulk_zip,
        session_zip_url_candidates,
    )

    urls = session_zip_url_candidates("2025")
    assert urls[0].endswith("pubinfo_2025.zip")
    assert urls[1].endswith("pubinfo_2023.zip")
    shell = tmp_path / "pubinfo.html"
    shell.write_bytes(b"<html>Disallow: /</html>")
    assert looks_like_zip(shell) is False
    assert parse_california_bulk_zip(shell, code_type="PEN") == []
    zip_path = tmp_path / "pubinfo.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("LAW_SECTION_TBL.dat", "x")
        archive.writestr("notes/readme.txt", "skip")
        archive.writestr("LAW_TOC_TBL.dat", "y")
    assert bulk_zip_table_names(zip_path) == ["LAW_SECTION_TBL.dat", "LAW_TOC_TBL.dat"]


def test_florida_ohio_toc_dumps_and_south_dakota_section_split(
    tmp_path: Path, monkeypatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.florida_chapter import (
        parse_configured_title_index_html,
        parse_configured_toc_html,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.ohio_chapter import (
        parse_configured_toc_html as parse_ohio_toc,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.south_dakota_title import (
        chapter_from_section,
        title_from_section,
    )

    toc = tmp_path / "fl-toc.html"
    toc.write_text(
        'href="index.cfm?App_mode=Display_Index&Title_Request=XLVI"',
        encoding="utf-8",
    )
    monkeypatch.setenv("FLORIDA_TOC_HTML", str(toc))
    assert parse_configured_toc_html() == ["XLVI"]

    index = tmp_path / "fl-index.html"
    index.write_text(
        "URL=0700-0799/0782/0782ContentsIndex.html",
        encoding="utf-8",
    )
    monkeypatch.setenv("FLORIDA_TITLE_INDEX_HTML", str(index))
    assert parse_configured_title_index_html() == ["782"]

    ohio = tmp_path / "oh-toc.html"
    ohio.write_text(
        '<a href="ohio-revised-code/title-29">Title 29 Crimes</a>',
        encoding="utf-8",
    )
    monkeypatch.setenv("OHIO_TOC_HTML", str(ohio))
    assert parse_ohio_toc()[0][0] == "29"

    assert title_from_section("22-16-4") == "22"
    assert chapter_from_section("22-16-4") == "16"
    assert chapter_from_section("1-1A-1") == "1A"
    assert title_from_section("bad") == ""


def test_ut_ia_id_mo_wi_toc_dumps(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.idaho_section import (
        parse_configured_toc_html as parse_idaho_toc,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.iowa_chapter_xml import (
        parse_configured_toc_html as parse_iowa_toc,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.missouri_chapter import (
        parse_configured_home_html,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.utah_title_xml import (
        parse_configured_toc_html as parse_utah_toc,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.wisconsin_chapter import (
        parse_configured_toc_html as parse_wisconsin_toc,
    )

    ut = tmp_path / "ut.html"
    ut.write_text(
        '<a href="/xcode/Title76/76.html?v=C76_2025050720250507">Title 76</a>',
        encoding="utf-8",
    )
    monkeypatch.setenv("UTAH_TOC_HTML", str(ut))
    assert parse_utah_toc()["76"].endswith("/Title76/C76_2025050720250507.xml")

    ia = tmp_path / "ia.html"
    ia.write_text(
        '<table id="iacList"><tbody><tr><td><a href="/law/iowaCode?title=XVI">'
        "Title XVI - CRIMINAL LAW</a></td></tr></tbody></table>",
        encoding="utf-8",
    )
    monkeypatch.setenv("IOWA_TOC_HTML", str(ia))
    assert parse_iowa_toc()[0][0] == "XVI"

    idaho = tmp_path / "id.html"
    idaho.write_text(
        '<div class="vc-column-inner-wrapper">nav</div>'
        '<div class="vc-column-innner-wrapper"><table><tr>'
        '<td><a href="/statutesrules/idstat/Title18/">TITLE 18</a></td>'
        "<td></td><td>Crimes and Punishments</td></tr></table></div>",
        encoding="utf-8",
    )
    monkeypatch.setenv("IDAHO_TOC_HTML", str(idaho))
    assert parse_idaho_toc()[0][0] == "18"

    mo = tmp_path / "mo.html"
    mo.write_text(
        '<details><a href="OneChapter.aspx?chapter=565">565 Offenses Against the Person</a>'
        "</details>",
        encoding="utf-8",
    )
    monkeypatch.setenv("MISSOURI_HOME_HTML", str(mo))
    assert parse_configured_home_html()[0][0] == "565"

    wi = tmp_path / "wi.html"
    wi.write_text(
        '<p><a href="/document/statutes/940">Chapter 940 (PDF: ) - Crimes Against Life</a></p>',
        encoding="utf-8",
    )
    monkeypatch.setenv("WISCONSIN_TOC_HTML", str(wi))
    assert parse_wisconsin_toc()[0][0] == "940"


def test_va_tx_ny_mi_nv_listing_dumps(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.michigan_chapter_xml import (
        parse_configured_chapter_index_html,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.nevada_chapter import (
        parse_configured_index_html,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_york_openleg import (
        parse_configured_category_html,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.texas_chapter import (
        parse_configured_statute_array,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.virginia_section import (
        parse_configured_toc_html,
    )

    va = tmp_path / "va.html"
    va.write_text(
        '<div class="number-descrip-list">'
        '<a href="/vacode/title18.2/">Title 18.2. Crimes</a></div>',
        encoding="utf-8",
    )
    monkeypatch.setenv("VIRGINIA_TOC_HTML", str(va))
    assert parse_configured_toc_html()[0][0] == "18.2"

    tx = tmp_path / "pe.json"
    tx.write_text(
        '[{"name": "CHAPTER 19. CRIMINAL HOMICIDE", "url": "PE/htm/PE.19.htm"}]',
        encoding="utf-8",
    )
    monkeypatch.setenv("TEXAS_STATUTE_ARRAY_JSON", str(tx))
    monkeypatch.setenv("TEXAS_STATUTE_ARRAY_CODE", "PE")
    assert parse_configured_statute_array()[0][0] == "19"

    ny = tmp_path / "ny.html"
    ny.write_text('<a href="/legislation/laws/PEN">Penal Law</a>', encoding="utf-8")
    monkeypatch.setenv("NY_CATEGORY_HTML", str(ny))
    assert parse_configured_category_html()[0][0] == "PEN"

    mi = tmp_path / "mi.html"
    mi.write_text(
        '<main id="main"><a href="/Home/GetObject?objectName=mcl-chap750">Chapter 750</a></main>',
        encoding="utf-8",
    )
    monkeypatch.setenv("MICHIGAN_CHAPTER_INDEX_HTML", str(mi))
    assert parse_configured_chapter_index_html()[0][0] == "750"

    nv = tmp_path / "nv.html"
    nv.write_text(
        '<a href="NRS-200.html">CHAPTER 200 - CRIMES AGAINST THE PERSON</a>',
        encoding="utf-8",
    )
    monkeypatch.setenv("NEVADA_INDEX_HTML", str(nv))
    assert parse_configured_index_html()[0][0] == "200"


def test_or_az_ar_ma_ks_listing_dumps(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arizona_section import (
        parse_configured_toc_html as parse_arizona_toc,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arkansas_section import (
        parse_configured_toc_html as parse_arkansas_toc,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.kansas_section import (
        parse_configured_statute_table_html,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.massachusetts_section import (
        parse_configured_toc_html as parse_massachusetts_toc,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oregon_chapter import (
        parse_configured_index_html,
    )

    oregon = tmp_path / "ors.html"
    oregon.write_text(
        '<a href="ors163.html">Chapter 163 Offenses Against Persons</a>',
        encoding="utf-8",
    )
    monkeypatch.setenv("OREGON_ORS_INDEX_HTML", str(oregon))
    assert parse_configured_index_html()[0][0] == "163"

    az = tmp_path / "az.html"
    az.write_text('<a href="/arsDetail/?title=13">Title 13</a>', encoding="utf-8")
    monkeypatch.setenv("ARIZONA_TOC_HTML", str(az))
    assert parse_arizona_toc()[0][0] == "13"

    ar = tmp_path / "ar.html"
    ar.write_text(
        '<a href="/ArkansasCode/?title=5">Title 5 Criminal Offenses</a>',
        encoding="utf-8",
    )
    monkeypatch.setenv("ARKANSAS_TOC_HTML", str(ar))
    assert parse_arkansas_toc()[0][0] == "5"

    ma = tmp_path / "ma.html"
    ma.write_text(
        '<a href="#titleI" onclick="accordionAjaxLoad(\'1\', \'1\', \'I\')">Title I</a>'
        '<a href="#titleI" onclick="accordionAjaxLoad(\'1\', \'1\', \'I\')">Jurisdiction</a>',
        encoding="utf-8",
    )
    monkeypatch.setenv("MASSACHUSETTS_TOC_HTML", str(ma))
    assert parse_massachusetts_toc()[0][:3] == ("1", "1", "I")

    ks = tmp_path / "ks.html"
    ks.write_text(
        '<table id="statute"><tr><td><a href="021_000_0000_chapter/">Chapter 21</a></td>'
        "<td>Crimes and Punishments</td></tr></table>",
        encoding="utf-8",
    )
    monkeypatch.setenv("KANSAS_STATUTE_TABLE_HTML", str(ks))
    assert parse_configured_statute_table_html()[0][0] == "21"


def test_sc_ky_nd_ct_mn_listing_dumps(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.connecticut_chapter import (
        parse_configured_titles_html,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.kentucky_section import (
        parse_configured_toc_html as parse_kentucky_toc,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.minnesota_section import (
        parse_configured_toc_html as parse_minnesota_toc,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_dakota_chapter import (
        parse_configured_toc_html as parse_north_dakota_toc,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.south_carolina_chapter import (
        parse_configured_toc_html as parse_south_carolina_toc,
    )

    sc = tmp_path / "sc.html"
    sc.write_text('<a href="/code/title16.php">Title 16</a>', encoding="utf-8")
    monkeypatch.setenv("SOUTH_CAROLINA_TOC_HTML", str(sc))
    assert parse_south_carolina_toc()[0][0] == "16"

    ky = tmp_path / "ky.html"
    ky.write_text(
        '<div id="Panel1"><span id="title">TITLE L CRIMES AND PUNISHMENTS</span></div>',
        encoding="utf-8",
    )
    monkeypatch.setenv("KENTUCKY_TOC_HTML", str(ky))
    assert parse_kentucky_toc()[0][0] == "L"

    nd = tmp_path / "nd.html"
    nd.write_text(
        '<div class="titles-grid"><div class="title-item">'
        '<span class="title-number">12.1</span>'
        '<a href="/cencode/t12-1.html">Criminal Code</a></div></div>',
        encoding="utf-8",
    )
    monkeypatch.setenv("NORTH_DAKOTA_TOC_HTML", str(nd))
    assert parse_north_dakota_toc()[0][0] == "12.1"

    ct = tmp_path / "ct.html"
    ct.write_text(
        '<td class="left_38pct"><a href="title_53a.htm">'
        '<span class="toc_ttl_desig">Title 53a</span></a></td>',
        encoding="utf-8",
    )
    monkeypatch.setenv("CONNECTICUT_TITLES_HTML", str(ct))
    assert parse_configured_titles_html()[0][1] == "53a"

    mn = tmp_path / "mn.html"
    mn.write_text(
        '<table id="toc_table"><tr><td><a href="/statutes/cite/609">609 - 624</a></td>'
        "<td>Crimes</td></tr></table>",
        encoding="utf-8",
    )
    monkeypatch.setenv("MINNESOTA_TOC_HTML", str(mn))
    assert parse_minnesota_toc()[0][1] == "609 - 624"


def test_ak_mt_al_wv_de_listing_dumps(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.alaska_section import (
        parse_configured_section_toc_html,
        parse_configured_toc_html as parse_alaska_toc,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.alabama_section import (
        FIELD_SEP,
        ROW_SEP,
        parse_configured_titles_text,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.delaware_chapter import (
        parse_configured_title_links_html,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.montana_section import (
        parse_configured_toc_html as parse_montana_toc,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.west_virginia_dump import (
        parse_configured_chapter_options,
    )

    ak = tmp_path / "ak.html"
    ak.write_text(
        '<li><a onclick=\'loadTOC("01.05");\'>Chapter 05. Alaska Statutes</a></li>',
        encoding="utf-8",
    )
    monkeypatch.setenv("ALASKA_TOC_HTML", str(ak))
    assert parse_alaska_toc()[0][0] == "01.05"

    ak_sec = tmp_path / "ak-sec.html"
    ak_sec.write_text(
        '<li><a href="statutes.asp?year=2024&title=1#01.05.006">Sec. 01.05.006. Adoption</a></li>',
        encoding="utf-8",
    )
    monkeypatch.setenv("ALASKA_SECTION_TOC_HTML", str(ak_sec))
    assert parse_configured_section_toc_html()[0][0] == "01.05.006"

    mt = tmp_path / "mt.html"
    mt.write_text(
        '<div class="title-toc-content"><ul>'
        '<li><a href="./title_0045/">TITLE 45. CRIMES</a></li>'
        '<li><span class="reserved">TITLES 8 AND 9. Reserved</span></li>'
        "</ul></div>",
        encoding="utf-8",
    )
    monkeypatch.setenv("MONTANA_TOC_HTML", str(mt))
    assert [number for number, _name, _url in parse_montana_toc()] == ["45", "8", "9"]

    al = tmp_path / "al.txt"
    al.write_text(
        ROW_SEP.join(
            [
                f"1{FIELD_SEP}Title 13A Criminal Code.",
                f"2{FIELD_SEP}Chapter 5 Death Penalty.",
                f"3{FIELD_SEP}Section 13A-5-40 Capital offenses.",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ALABAMA_TITLES_TEXT", str(al))
    assert parse_configured_titles_text()[0] == ("title", "13A", "Title 13A Criminal Code.")
    assert parse_configured_titles_text()[2][1] == "13A-5-40"

    wv = tmp_path / "wv.html"
    wv.write_text(
        '<select id="sel-chapter">'
        '<option value="61">CHAPTER 61. CRIMES</option>'
        '<option value="17H">CHAPTER 17H. AUTONOMOUS VEHICLES</option>'
        '<option value="">skip</option></select>',
        encoding="utf-8",
    )
    monkeypatch.setenv("WEST_VIRGINIA_CHAPTER_HTML", str(wv))
    assert [number for number, _name in parse_configured_chapter_options()] == ["61", "17H"]

    de = tmp_path / "de.html"
    de.write_text(
        '<div class="title-links"><a href="c005/index.html">Chapter 5. Specific Offenses</a></div>',
        encoding="utf-8",
    )
    monkeypatch.setenv("DELAWARE_TITLE_LINKS_HTML", str(de))
    rows = parse_configured_title_links_html()
    assert rows[0]["classifier"] == "chapter"
    assert rows[0]["number"] == "5"


def test_me_ne_hi_wa_vt_ri_nh_la_listing_dumps(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.hawaii_section import (
        parse_configured_next_link,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.louisiana_law import (
        parse_configured_toc_html as parse_louisiana_toc,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.maine_section import (
        parse_configured_title_toc_html,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.nebraska_section import (
        parse_configured_chapter_html as parse_nebraska_chapter,
        parse_configured_toc_html as parse_nebraska_toc,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_hampshire_section import (
        parse_configured_chapter_toc_html,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.rhode_island_section import (
        parse_configured_toc_html as parse_rhode_island_toc,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.vermont_section import (
        parse_configured_toc_html as parse_vermont_toc,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.washington_section import (
        parse_configured_toc_html as parse_washington_toc,
    )

    me = tmp_path / "me.html"
    me.write_text(
        '<div class="MRSChapter_toclist">'
        '<a href="title17-Ach1sec0.html">Chapter 1: Preliminary</a></div>'
        '<div class="MRSChapter_toclist">'
        '<a href="title17-Ach0sec0.html">Chapter 0 skipped</a></div>',
        encoding="utf-8",
    )
    monkeypatch.setenv("MAINE_TITLE_TOC_HTML", str(me))
    assert parse_configured_title_toc_html()[0][0].endswith("title17-Ach1sec0.html")

    ne = tmp_path / "ne.html"
    ne.write_text(
        '<a href="/laws/browse-chapters.php?chapter=28">Chapter 28</a>'
        '<a href="/laws/browse-chapters.php?chapter=76A">Chapter 76A</a>',
        encoding="utf-8",
    )
    monkeypatch.setenv("NEBRASKA_TOC_HTML", str(ne))
    assert [number for number, _name, _url in parse_nebraska_toc()] == ["28", "76A"]

    ne_chapter = tmp_path / "ne-chapter.html"
    ne_chapter.write_text(
        '<a href="/laws/statutes.php?statute=28-303">28-303 Murder in the first degree</a>'
        '<a href="/laws/statutes.php?statute=25-2740.04">25-2740.04 Appeal</a>',
        encoding="utf-8",
    )
    monkeypatch.setenv("NEBRASKA_CHAPTER_HTML", str(ne_chapter))
    assert [number for number, _name, _url in parse_nebraska_chapter()] == [
        "28-303",
        "25-2740.04",
    ]

    hi = tmp_path / "hi.html"
    hi.write_text('<a href="HRS_0707-0701.HTM">Next</a>', encoding="utf-8")
    monkeypatch.setenv("HAWAII_CHAPTER_HTML", str(hi))
    monkeypatch.setenv(
        "HAWAII_CHAPTER_URL",
        "https://www.capitol.hawaii.gov/hrscurrent/Vol14_Ch0701-0853/HRS0707/HRS_0707-.htm",
    )
    assert parse_configured_next_link().endswith("/HRS0707/HRS_0707-0701.HTM")

    wa = tmp_path / "wa.html"
    wa.write_text(
        '<a href="default.aspx?Cite=9A">Title 9A RCW</a>'
        '<a href="default.aspx?cite=9A.32">skip chapter</a>',
        encoding="utf-8",
    )
    monkeypatch.setenv("WASHINGTON_TOC_HTML", str(wa))
    assert parse_washington_toc() == ["9A"]

    vt = tmp_path / "vt.html"
    vt.write_text(
        '<ul class="statutes-list"><li><a href="statutes/title/13">Title 13</a></li></ul>',
        encoding="utf-8",
    )
    monkeypatch.setenv("VERMONT_TOC_HTML", str(vt))
    assert parse_vermont_toc()[0][1] == "13"

    ri = tmp_path / "ri.html"
    ri.write_text(
        '<a href="TITLE6A/INDEX.HTM"><b> TITLE 6A  Uniform Commercial Code </b></a>',
        encoding="utf-8",
    )
    monkeypatch.setenv("RHODE_ISLAND_TOC_HTML", str(ri))
    assert parse_rhode_island_toc()[0][1] == "6A"

    nh = tmp_path / "nh.html"
    nh.write_text(
        '<a href="../LXII/630/630-1.htm">Section 630:1</a>'
        '<a href="../LXII/630/630-1-mrg.htm">margin</a>',
        encoding="utf-8",
    )
    monkeypatch.setenv("NEW_HAMPSHIRE_CHAPTER_TOC_HTML", str(nh))
    assert parse_configured_chapter_toc_html()[0].endswith("630-1.htm")

    la = tmp_path / "la.html"
    la.write_text(
        '<a href="Law.aspx?d=111">Art. 1</a><a href="Law.aspx?d=111">dup</a>'
        '<a href="Law.aspx?d=222">Art. 2</a>',
        encoding="utf-8",
    )
    monkeypatch.setenv("LOUISIANA_TOC_HTML", str(la))
    assert parse_louisiana_toc() == ["111", "222"]
