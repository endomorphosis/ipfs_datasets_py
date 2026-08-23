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


def test_georgia_archive_strips_nav_and_stays_recovery(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia import GeorgiaScraper
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia_archive import (
        official_title_frontier,
        wayback_cdx_query_url,
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
    assert "justia" not in rows[0].source_url


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
