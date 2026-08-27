"""Strict Iowa full-corpus provenance and frontier regressions."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import iowa_chapter_xml
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.iowa import IowaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.iowa_chapter_xml import (
    parse_iowa_chapter_xml,
    reserved_section_numbers,
)

XML_URL = (
    "https://www.legis.iowa.gov/docs/publications/ICC/2026/"
    "attachments/203A_slim.xml"
)
XML_BODY = b"""<root><Section id="sec203A.1">
<div class="heading"><span class="identifier">203A.1</span>
<span class="headnote">Grain bargaining.</span></div>
<p>This chapter governs grain bargaining agents and their official duties.</p>
</Section></root>"""


def test_iowa_frontier_software_identity_binds_chapter_xml_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = IowaScraper("IA", "Iowa")
    assert scraper.state_law_frontier_source_dependencies() == (
        iowa_chapter_xml,
    )
    baseline = scraper._state_law_frontier_source_software_version()
    helper_path = Path(iowa_chapter_xml.__file__).resolve()
    original_read_bytes = Path.read_bytes

    def _read_with_helper_drift(path: Path) -> bytes:
        payload = original_read_bytes(path)
        if path.resolve() == helper_path:
            return payload + b"\n# simulated helper generation\n"
        return payload

    monkeypatch.setattr(Path, "read_bytes", _read_with_helper_drift)
    changed = scraper._state_law_frontier_source_software_version()

    assert changed != baseline
    assert changed.split("@sha256:", 1)[0] == baseline.split("@sha256:", 1)[0]


def test_iowa_xml_rows_project_exact_retained_input_provenance(tmp_path: Path) -> None:
    scraper = IowaScraper("IA", "Iowa")
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="IA",
        parser_name="IowaScraper",
    )
    scraper.attach_state_law_acquisition_ledger(ledger)
    digest = hashlib.sha256(XML_BODY).hexdigest()
    receipt = {
        "content_sha256": digest,
        "official_url": XML_URL,
        "source_transport": "direct",
    }
    ledger.retain_parser_input(
        official_url=XML_URL,
        body=XML_BODY,
        transport_receipt=receipt,
        media_type="application/xml",
    )
    scraper._last_page_fetch_transport_evidence = receipt
    rows = parse_iowa_chapter_xml(XML_BODY, chapter="203A", year="2026")

    [row] = scraper._bind_parser_input_provenance(rows, parser_input_url=XML_URL)
    enriched = scraper._enrich_statute_structure(row)

    assert enriched.structured_data["content_sha256"] == digest
    assert enriched.structured_data["jsonld"]["provenance"]["content_sha256"] == digest
    coverage = ledger.audit_parser_output_coverage([enriched.to_dict()])
    assert coverage["complete"] is True
    assert coverage["covered_by_content_digest"] == 1


@pytest.mark.anyio
async def test_iowa_reserved_chapter_is_terminal_without_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = IowaScraper("IA", "Iowa")
    scraper._IOWA_TITLE_TOKENS = ("XVI",)
    title_url = "https://www.legis.iowa.gov/law/iowaCode/chapters?title=XVI&year=2026"
    title_html = b"""<table><tr><td>
      <a href="/law/iowaCode/sections?codeChapter=763&amp;year=2026">
      Chapter 763 - RESERVED</a></td></tr></table>"""
    requested: list[str] = []

    async def _fetch(url: str, **kwargs: object) -> bytes:
        requested.append(url)
        return title_html if url == title_url else b""

    monkeypatch.setattr(scraper, "_request_bytes", _fetch)
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", lambda *args, **kwargs: None)

    rows = await scraper._scrape_official_iowa_sections("Iowa Code")

    assert rows == []
    assert requested == [title_url]


@pytest.mark.anyio
async def test_iowa_active_missing_chapter_fails_closed_on_missing_slim_xml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = IowaScraper("IA", "Iowa")
    scraper._IOWA_TITLE_TOKENS = ("VII",)
    title_url = "https://www.legis.iowa.gov/law/iowaCode/chapters?title=VII&year=2026"
    title_html = b"""<table><tr><td>Chapter 203A - GRAIN BARGAINING AGENTS
      <a href="/law/iowaCode/sections?codeChapter=203A&amp;year=2026">203A</a>
      <a href="/docs/publications/ICC/2026/attachments/203A_slim.xml">XML</a>
    </td></tr></table>"""

    async def _fetch(url: str, **kwargs: object) -> bytes:
        return title_html if url == title_url else b""

    monkeypatch.setattr(scraper, "_request_bytes", _fetch)
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match="active official chapter.*203A"):
        await scraper._scrape_official_iowa_sections("Iowa Code")


def test_iowa_slim_xml_types_only_exact_reserved_sections() -> None:
    xml = b"""<root>
      <Section id="sec910.11"><div class="heading"><span class="identifier">910.11</span></div>
        <p>Reserved.</p></Section>
      <Section id="sec910.12"><div class="heading"><span class="identifier">910.12</span>
        <span class="headnote">Reserved.</span></div></Section>
      <Section id="sec910.15"><div class="heading"><span class="identifier">910.15</span>
        <span class="headnote">Reserved funds.</span></div>
        <p>Reserved funds shall be distributed by the department under this section.</p></Section>
    </root>"""

    assert reserved_section_numbers(xml) == ["910.11", "910.12"]
    assert [row.section_number for row in parse_iowa_chapter_xml(xml, chapter="910")] == [
        "910.15"
    ]


@pytest.mark.anyio
async def test_iowa_reserved_section_frontier_uses_xml_terminal_without_document_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = IowaScraper("IA", "Iowa")
    scraper._IOWA_TITLE_TOKENS = ("XVI",)
    title_url = "https://www.legis.iowa.gov/law/iowaCode/chapters?title=XVI&year=2026"
    chapter_url = "https://www.legis.iowa.gov/law/iowaCode/sections?codeChapter=910&year=2026"
    xml_url = (
        "https://www.legis.iowa.gov/docs/publications/ICC/2026/"
        "attachments/910_slim.xml"
    )
    pdf_url = "https://www.legis.iowa.gov/docs/code/2026/910.11.pdf"
    title_html = f"""<table><tr><td>Chapter 910 - RESTITUTION
      <a href="{chapter_url}">910</a><a href="{xml_url}">XML</a>
    </td></tr></table>""".encode()
    chapter_html = f"""<table><tr><td>910.11</td><td>
      <a href="{pdf_url}">PDF</a></td></tr></table>""".encode()
    xml = b"""<root><Section id="sec910.11"><div class="heading">
      <span class="identifier">910.11</span></div><p>Reserved.</p>
    </Section></root>"""
    requested: list[str] = []

    async def _fetch(url: str, **kwargs: object) -> bytes:
        requested.append(url)
        return {title_url: title_html, chapter_url: chapter_html, xml_url: xml}.get(
            url,
            b"",
        )

    monkeypatch.setattr(scraper, "_request_bytes", _fetch)
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", lambda *args, **kwargs: None)

    rows = await scraper._scrape_official_iowa_sections("Iowa Code")

    assert rows == []
    assert requested == [title_url, chapter_url, xml_url]
    assert scraper._last_iowa_terminal_dispositions == [
        {
            "chapter_number": "910",
            "content_sha256": hashlib.sha256(xml).hexdigest(),
            "disposition": "reserved",
            "section_number": "910.11",
            "source_url": xml_url,
        }
    ]
