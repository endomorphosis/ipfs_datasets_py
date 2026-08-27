from __future__ import annotations

import hashlib
import inspect
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
    build_canonical_state_law_output_projection,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
    michigan as michigan_module,
    new_york_law_pdf as ny_pdf,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.michigan import (
    MichiganScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.michigan_chapter_xml import (
    chapter_xml_url,
    parse_michigan_chapter_xml_closure,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_york import (
    NewYorkScraper,
)


_RETAINED_NY_EVIDENCE_ROOT = (
    Path.home()
    / ".ipfs_datasets"
    / "state_laws"
    / "legal-corpora-reindex-20260824"
    / "full-acquisition-evidence-v20-ny-v1"
    / "NY"
)
_RETAINED_NY_AGM_SELECTOR_ROOT = (
    Path.home()
    / ".ipfs_datasets"
    / "state_laws"
    / "legal-corpora-reindex-20260824"
    / "full-acquisition-evidence-v21-ny-agm28-selector-v1"
    / "NY"
)


def test_michigan_source_bundle_binds_parser_closure_and_plural_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MichiganScraper("MI", "Michigan")
    dependencies = scraper.state_law_frontier_source_dependencies()

    assert [dependency.__name__.rsplit(".", 1)[-1] for dependency in dependencies] == [
        "base_scraper",
        "state_archival_fetch",
        "strict_frontier_closure",
        "michigan_chapter_xml",
        "wayback_machine_engine",
    ]
    baseline = scraper._state_law_frontier_source_software_version()
    assert baseline.startswith(
        "ipfs_datasets_py.processors.legal_scrapers.state_scrapers.michigan."
        "MichiganScraper@sha256:"
    )

    archival_source = inspect.getsourcefile(dependencies[1])
    assert archival_source is not None
    archival_path = Path(archival_source).resolve()
    original_read_bytes = Path.read_bytes

    def _read_mutated_dependency(path: Path) -> bytes:
        payload = original_read_bytes(path)
        if path.resolve() == archival_path:
            return payload + b"\n# synthetic producer-affecting mutation\n"
        return payload

    monkeypatch.setattr(Path, "read_bytes", _read_mutated_dependency)

    assert scraper._state_law_frontier_source_software_version() != baseline


_RETAINED_NY_PROJECTION = {
    "raw": 37_827,
    "source_without_raw": 33,
    "source": 37_441,
    "embedded": 292,
    "lifecycle_alternates": 127,
    "operative": 36_475,
    "terminal": 751,
    "residual": 215,
    "closed_laws": 68,
}
_RETAINED_NY_RESIDUAL_PROJECTION_SHA256 = (
    "4e8865cc8dbfe4706e0fbe931e31df60a4e4f7e20e88ee9f628507c354b22dc3"
)


def _parse_retained_new_york_projection_item(item):
    code, name, body_path = item
    report = ny_pdf.parse_new_york_law_pdf(
        Path(body_path).read_bytes(),
        law_code=code,
        law_name=name,
    )
    return code, report


def _mi_xml(chapter: str, section: str, *, repealed: bool = False) -> bytes:
    catchline = "Expired. 2020, Act 1." if repealed else "Operative provision."
    body = "" if repealed else (
        "&lt;Section-Body&gt;&lt;P&gt;This Michigan provision supplies complete "
        "official statutory text for exact source reconciliation and indexing."
        "&lt;/P&gt;&lt;/Section-Body&gt;"
    )
    padding = "x" * 700
    return f"""<?xml version="1.0" encoding="utf-8"?>
    <MCLChapterInfo>
      <Name>{chapter}</Name><Title>Chapter {chapter}</Title>
      <Commentary>{padding}</Commentary>
      <MCLDocumentInfoCollection><MCLStatuteInfo>
        <Name>Act {chapter} of 2000</Name>
        <MCLDocumentInfoCollection><MCLSectionInfo>
          <MCLNumber>{section}</MCLNumber><CatchLine>{catchline}</CatchLine>
          <Repealed>{str(repealed).lower()}</Repealed><BodyText>{body}</BodyText>
        </MCLSectionInfo></MCLDocumentInfoCollection>
      </MCLStatuteInfo></MCLDocumentInfoCollection>
    </MCLChapterInfo>""".encode()


def _aligned_result(urls, payloads, *, errors=None) -> StateLawPageMultiFetchResult:
    requested = list(urls)
    bodies = list(payloads)
    aligned_errors = list(errors or [None] * len(requested))
    return StateLawPageMultiFetchResult(
        urls=requested,
        payloads=bodies,
        errors=aligned_errors,
        transport_receipts=[
            {
                "official_url": url,
                "content_sha256": hashlib.sha256(body).hexdigest() if body else "",
                "source_transport": "direct",
            }
            for url, body in zip(requested, bodies, strict=True)
        ],
        parser_input_envelopes=[None] * len(requested),
        stats={
            "requested_pages": len(requested),
            "common_crawl": {
                "range_fetch_calls": 1 if len(requested) > 1 else 0,
                "range_fetches_avoided": max(0, len(requested) - 1),
            },
        },
    )


class _RetainedInputLedger:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = dict(payloads)
        self.requests: list[tuple[str, dict]] = []

    def refresh_existing_entries(self) -> None:
        return None

    def replay_retained_parser_input(self, *, official_url: str, sanitized_request):
        request = dict(sanitized_request)
        self.requests.append((official_url, request))
        payload = self.payloads.get(official_url)
        if payload is None:
            return None
        return SimpleNamespace(
            envelope=SimpleNamespace(body=payload),
            transport_receipt={
                "official_url": official_url,
                "content_sha256": hashlib.sha256(payload).hexdigest(),
                "source_transport": "retained_acquisition_replay",
            },
        )


def _canonical_projection(scraper, rows):
    return build_canonical_state_law_output_projection(
        [scraper._enrich_statute_structure(row).to_dict() for row in rows],
        jurisdiction=scraper.state_code,
    )


def test_michigan_official_http_get_uses_imported_urllib_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"<html><body>Michigan official chapter index</body></html>"
    calls = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return payload

    def _urlopen(request, *, timeout, context):
        calls.append((request.full_url, timeout, context))
        return _Response()

    monkeypatch.setattr(michigan_module.urllib.request, "urlopen", _urlopen)
    scraper = MichiganScraper("MI", "Michigan")

    assert scraper._official_http_get(scraper.OFFICIAL_ENTRY_URL) == payload
    assert [(url, timeout) for url, timeout, _context in calls] == [
        (scraper.OFFICIAL_ENTRY_URL, 12)
    ]


def test_michigan_xml_closure_types_terminals_and_constitution_identity() -> None:
    xml = """
    <MCLChapterInfo><Name>1</Name><Title>Constitution of Michigan of 1963</Title>
      <MCLDocumentInfoCollection><MCLStatuteInfo><Name>CONSTITUTION</Name>
        <MCLDocumentInfoCollection>
          <MCLSectionInfo><MCLNumber>Article I § 1</MCLNumber>
            <CatchLine>Political power.</CatchLine><Repealed>false</Repealed>
            <BodyText>&lt;P&gt;All political power is inherent in the people of Michigan.&lt;/P&gt;</BodyText>
          </MCLSectionInfo>
          <MCLSectionInfo><MCLNumber>Article IV § 4</MCLNumber>
            <CatchLine>Expired. 1968.</CatchLine><Repealed>true</Repealed><BodyText />
          </MCLSectionInfo>
        </MCLDocumentInfoCollection>
      </MCLStatuteInfo></MCLDocumentInfoCollection>
    </MCLChapterInfo>
    """

    report = parse_michigan_chapter_xml_closure(xml, chapter_hint="1")

    assert report.closed is True
    assert report.source_section_count == 2
    assert len(report.statutes) == 1
    assert report.terminal_sections[0]["disposition"] == "expired"
    row = report.statutes[0]
    assert row.code_name == "Michigan Constitution"
    assert row.official_cite == "Mich. Const. art. I, § 1"
    assert row.source_url.endswith("objectName=mcl-Article-I-1")


def test_michigan_xml_closure_rejects_terminal_flag_mismatch() -> None:
    xml = _mi_xml("750", "750.1").decode().replace(
        "Operative provision.", "Repealed. 2020, Act 1."
    )
    report = parse_michigan_chapter_xml_closure(xml, chapter_hint="750")
    assert report.closed is False
    assert report.statutes == []
    assert report.unclassified_sections[0]["reason"] == (
        "terminal_disposition_flag_mismatch"
    )


def test_michigan_xml_closure_types_sectionless_repealed_statute() -> None:
    xml = """
    <MCLChapterInfo><Name>340</Name><Title>EDUCATION</Title>
      <MCLDocumentInfoCollection><MCLStatuteInfo>
        <DocumentID>23521</DocumentID><Repealed>true</Repealed>
        <Name>Act 269 of 1955</Name><Heading>SCHOOL CODE OF 1955</Heading>
        <LongTitle>340.1-340.984 Repealed. 1976, Act 451.</LongTitle>
        <MCLDocumentInfoCollection />
      </MCLStatuteInfo></MCLDocumentInfoCollection>
    </MCLChapterInfo>
    """

    report = parse_michigan_chapter_xml_closure(
        xml,
        chapter_hint="340",
        source_bundle_url=(
            "https://www.legislature.mi.gov/documents/mcl/Chapter%20340.xml"
        ),
    )

    assert report.closed is True
    assert report.source_section_count == 1
    assert report.statutes == []
    assert report.unclassified_sections == []
    assert report.terminal_sections == [
        {
            "section_number": "",
            "catchline": "340.1-340.984 Repealed. 1976, Act 451.",
            "disposition": "repealed",
            "source_record_id": "23521",
            "source_record_type": "sectionless_statute",
            "source_url": (
                "https://www.legislature.mi.gov/documents/mcl/Chapter%20340.xml"
            ),
        }
    ]


def test_michigan_xml_closure_rejects_nonrepealed_sectionless_statute() -> None:
    xml = """
    <MCLChapterInfo><Name>999</Name><Title>UNCLASSIFIED</Title>
      <MCLDocumentInfoCollection><MCLStatuteInfo>
        <DocumentID>99901</DocumentID><Repealed>false</Repealed>
        <Name>Act 1 of 2026</Name><Heading>ACTIVE ACT</Heading>
        <MCLDocumentInfoCollection />
      </MCLStatuteInfo></MCLDocumentInfoCollection>
    </MCLChapterInfo>
    """

    report = parse_michigan_chapter_xml_closure(xml, chapter_hint="999")

    assert report.closed is False
    assert report.source_section_count == 1
    assert report.terminal_sections == []
    assert report.unclassified_sections[0]["reason"] == (
        "nonrepealed_statute_without_section_nodes"
    )


def test_new_york_pdf_parser_reconciles_decimal_and_terminal_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = """
    PENAL LAW
      § 1.00 Short title. This chapter shall be known as the penal law and
      supplies enough official statutory body text for exact indexing.
      § 3-a Special provision. A person shall comply with this complete and
      operative statutory command under the laws of New York.
      § 4. Reserved.
      § 5. Expired.
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 2),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-synthetic",
        law_code="PEN",
        law_name="Penal",
    )

    assert report.closed is True
    assert report.raw_section_marker_count == 4
    assert report.source_section_count == 4
    assert report.embedded_section_markers == []
    assert [row.section_number for row in report.statutes] == ["1.00", "3-a"]
    assert [row["disposition"] for row in report.terminal_sections] == [
        "reserved",
        "expired",
    ]
    assert report.statutes[0].statute_id.endswith("§ PEN 1.00")


def test_new_york_pdf_parser_fails_closed_on_unknown_section_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = """
      § 1.00 Complete provision. This is a complete operative section of New York law.
      § 2/3 Unexpected identifier form that must not silently disappear from closure.
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 1),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-synthetic",
        law_code="PEN",
        law_name="Penal",
    )

    assert report.closed is False
    assert report.source_section_count == 2
    assert report.unclassified_sections == [
        {
            "reason": "unparsed_section_header",
            "detail": (
                "§ 2/3 Unexpected identifier form that must not silently disappear "
                "from closure."
            ),
        }
    ]


def test_new_york_pdf_parser_keeps_source_quoted_compact_inside_parent_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = """
      § 1. First primary provision. This is a complete operative section of
      the containing New York law with a stable top-level identity.
      § 2. Second primary provision. This is another complete operative
      section of the containing New York law with a stable identity.
      § 258-kk. Northeast interstate dairy compact. The compact is as follows:
      NORTHEAST INTERSTATE DAIRY COMPACT
      § 1. Compact title in its internal table of contents.
      § 2. Compact purpose in its internal table of contents.
      § 1. Compact title. This quoted compact text remains part of the full
      statutory body of the containing section and is not a second NY identity.
      § 2. Compact purpose. This quoted compact text also remains in the full
      statutory body of the containing section.
      § 258-ll. Severability. This complete operative provision follows the
      compact and resumes the containing law's top-level section sequence.
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 3),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-synthetic",
        law_code="AGM",
        law_name="Agriculture and Markets",
    )

    assert report.closed is True
    assert report.raw_section_marker_count == 8
    assert report.source_section_count == 4
    assert [row.section_number for row in report.statutes] == [
        "1",
        "2",
        "258-kk",
        "258-ll",
    ]
    assert report.terminal_sections == []
    assert report.unclassified_sections == []
    assert report.embedded_section_markers == [
        {
            "section_number": section,
            "parent_section_number": "258-kk",
            "reason": "embedded_compact_section_header",
        }
        for section in ("1", "2", "1", "2")
    ]
    compact = next(
        row for row in report.statutes if row.section_number == "258-kk"
    )
    assert "§ 1. Compact title in its internal table" in compact.full_text
    assert "§ 2. Compact purpose. This quoted compact text" in compact.full_text


def test_new_york_pdf_parser_does_not_collapse_unproved_duplicate_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = """
      § 1. First primary provision. This is a complete operative section of
      the containing New York law with a stable top-level identity.
      § 1. A second standalone provision with the same printed number must
      remain a typed residual until source hierarchy proves its identity.
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 1),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-synthetic",
        law_code="PBG",
        law_name="Public Housing",
    )

    assert report.closed is False
    assert report.raw_section_marker_count == 2
    assert report.source_section_count == 2
    assert len(report.statutes) == 1
    assert report.embedded_section_markers == []
    assert report.unclassified_sections == [
        {"section_number": "1", "reason": "duplicate_section_header"}
    ]


def test_new_york_pdf_parser_selects_release_dated_lifecycle_variants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = """
    ARTICLE 1
    CURRENT TESTS
    Section 1. Current version.
            2. Expired version.
      * § 1. Current version. This is the operative current body with enough
      official statutory text for exact source reconciliation.
      * NB Effective until January 1, 2027
      * § 1. Future version. This future official body is retained as source
      lifecycle evidence but is not operative on the release date.
      * NB Effective January 1, 2027
      * § 2. Expired version. This expired official body is retained as exact
      source lifecycle evidence.
      * NB Expired January 1, 2020
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 1),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-synthetic",
        law_code="TST",
        law_name="Lifecycle Test",
    )

    assert report.release_date == "2026-08-26"
    assert report.closed is True
    assert report.raw_section_marker_count == 3
    assert report.source_section_count == 2
    assert [row.section_number for row in report.statutes] == ["1"]
    assert report.statutes[0].structured_data["lifecycle_disposition"] == (
        "effective_until"
    )
    assert report.statutes[0].structured_data["release_date"] == "2026-08-26"
    assert [row["disposition"] for row in report.lifecycle_alternate_sections] == [
        "future_effective"
    ]
    assert [row["disposition"] for row in report.terminal_sections] == ["expired"]


@pytest.mark.parametrize(
    ("note", "expected"),
    [
        (
            "Authority terminated 07/01/1974 | There are 4 § 1599-a's",
            ("terminal", "terminated"),
        ),
        (
            "Nonexistent May 5, 1987 | There are 3 § 497's",
            ("terminal", "terminated"),
        ),
        (
            "Not operative per general election November, 1968",
            ("terminal", "never_effective"),
        ),
        (
            "Rpld per ch 414/02, § 1. Benefits continue under another section.",
            ("terminal", "repealed"),
        ),
        (
            "(Expired see § 2 of Ch. 7 of the Laws of 1967)",
            ("terminal", "expired"),
        ),
        (
            "Agency shall continue in existence until July 21, 2016 per act",
            ("terminal", "expired"),
        ),
        (
            "Added Ch. 58/2004 Part B §23, language juxtaposed per act | "
            "Section number supplied by the Legislative Bill Drafting Commission",
            ("current", "official_identity_annotation"),
        ),
        (
            "This section partially repealed by chapter 73/64. Certain "
            "provisions were retained by opinion of the Attorney General.",
            ("current", "partially_repealed_retained_text"),
        ),
    ],
)
def test_new_york_lifecycle_selector_accepts_explicit_official_status(
    note: str,
    expected: tuple[str, str],
) -> None:
    assert ny_pdf._annotated_lifecycle_status(
        note,
        release_date=date(2026, 8, 26),
    ) == expected


@pytest.mark.parametrize(
    ("note", "release_date", "expected"),
    [
        (
            "Authority terminated 07/01/2027",
            date(2026, 8, 26),
            ("current", "future_termination"),
        ),
        (
            "Nonexistent January 1, 2027",
            date(2026, 8, 26),
            ("current", "future_termination"),
        ),
        (
            "Agency shall continue in existence until July 21, 2027 per act",
            date(2026, 8, 26),
            ("current", "effective_until"),
        ),
        (
            "Agency shall continue until its liabilities are fully paid",
            date(2026, 8, 26),
            ("ambiguous", "unrecognized_lifecycle_note"),
        ),
        (
            "Added Ch. 58/2004 Part B §23",
            date(2026, 8, 26),
            ("ambiguous", "unrecognized_lifecycle_note"),
        ),
    ],
)
def test_new_york_lifecycle_selector_does_not_overstate_explicit_status(
    note: str,
    release_date: date,
    expected: tuple[str, str],
) -> None:
    assert ny_pdf._annotated_lifecycle_status(
        note,
        release_date=release_date,
    ) == expected


@pytest.mark.parametrize(
    ("note", "expected_disposition"),
    [
        (
            "Amendments effective upon passage of the same legislation "
            "by New Jersey",
            "event_conditioned_effective",
        ),
        (
            "(Effective until ruling by Commissioner of Internal Revenue)",
            "event_conditioned_effective_until",
        ),
        (
            "Section null and void if the required schedule is submitted",
            "event_conditioned_nullification",
        ),
        (
            "The corporation shall continue for a term ending the later of "
            "July 1, 2008 or one year after its liabilities are fully paid",
            "event_conditioned_expiration",
        ),
    ],
)
def test_new_york_lifecycle_selector_types_retained_event_conditions(
    note: str,
    expected_disposition: str,
) -> None:
    assert ny_pdf._annotated_lifecycle_status(
        note,
        release_date=date(2026, 8, 26),
    ) == ("ambiguous", expected_disposition)


def test_new_york_pdf_extractor_preserves_repeated_statutory_boundary_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repeated_note = "* NB Agency expires per §§ 856 and 882"
    pages = [
        SimpleNamespace(
            extract_text=lambda page=page: (
                f"{repeated_note}\n"
                f"Retained statutory page {page} body.\n"
                f"{page}\n"
            )
        )
        for page in range(1, 4)
    ]
    monkeypatch.setitem(
        sys.modules,
        "pypdf",
        SimpleNamespace(PdfReader=lambda *_args, **_kwargs: SimpleNamespace(pages=pages)),
    )

    text, page_count = ny_pdf.extract_new_york_law_pdf_text(b"%PDF-synthetic")

    assert page_count == 3
    assert text.count(repeated_note) == 3
    assert "\n1\n" not in f"\n{text}\n"
    assert "\n2\n" not in f"\n{text}\n"
    assert "\n3\n" not in f"\n{text}\n"


def test_new_york_pdf_parser_accepts_multi_star_lifecycle_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = """
    ARTICLE 1
    MULTI-STAR STATUS
    Section 31.27. Comprehensive psychiatric emergency programs.
      ** § 31.27 Comprehensive psychiatric emergency programs. This retained
      source body contains complete operative text for exact reconciliation.
      ** NB Repealed July 1, 2027
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 1),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-multi-star-status",
        law_code="MHY",
        law_name="Mental Hygiene",
    )

    assert report.closed is True
    assert len(report.statutes) == 1
    assert report.statutes[0].structured_data["lifecycle_disposition"] == (
        "future_repeal"
    )


def test_new_york_pdf_parser_accepts_exact_adjacent_body_order_inversion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = """
    ARTICLE 1
    ADJACENT BODY ORDER
    Section 1. First provision.
            2. Second provision.
            3. Third provision.
            4. Fourth provision.
      § 1. First provision. This is complete retained statutory body text.
      § 3. Third provision. This exact body is printed one place early.
      § 2. Second provision. This exact body is printed one place late.
      § 4. Fourth provision. This is complete retained statutory body text.
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 1),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-adjacent-order",
        law_code="MHY",
        law_name="Mental Hygiene",
    )

    assert report.closed is True
    assert {row.section_number for row in report.statutes} == {
        "1",
        "2",
        "3",
        "4",
    }
    assert any(
        row.get("section_number") == "3"
        and row.get("reason") == "adjacent_toc_body_order_inversion"
        for row in report.toc_body_corrections
    )


def test_new_york_pdf_parser_binds_separately_amended_heading_alternate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = """
    ARTICLE 1
    HEADING AMENDMENTS
    Section 1. Anchor provision.
          * 28. Meetings for the duration of the state disaster emergency.
          * 28. Electronic meetings.
      * NB § 28 Heading separately amended; cannot be put together
      § 1. Anchor provision. This retained body proves the inventory start.
      § 28. Electronic meetings. This single retained statutory body is
      shared by the two source-proved separately amended headings.
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 1),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-heading-alternate",
        law_code="RCO",
        law_name="Religious Corporations",
    )

    assert report.closed is True
    assert [row.section_number for row in report.statutes] == ["1", "28"]
    assert any(
        row.get("section_number") == "28"
        and row.get("reason")
        == "source_proved_separately_amended_heading_alternate"
        for row in report.toc_body_corrections
    )


def test_new_york_pdf_parser_binds_exact_insurance_publisher_special_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = f"""
    ARTICLE 41
    PROPERTY AND CASUALTY INSURANCE COMPANIES
    Section 4102. Powers.
      * § 4102. Powers. This retained Insurance Law body contains complete
      operative text before the exact publisher editorial qualification.
      * SPECIAL NOTE.--{ny_pdf._INSURANCE_UNJUXTAPOSED_SPECIAL_NOTE}
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 1),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-insurance-special-note",
        law_code="ISC",
        law_name="Insurance",
    )

    assert report.closed is True
    assert len(report.statutes) == 1
    assert report.statutes[0].structured_data["lifecycle_disposition"] == (
        "source_proved_unjuxtaposed_insurance_special_note"
    )


def test_new_york_retained_real_94_pdf_projection_is_stable() -> None:
    if not _RETAINED_NY_EVIDENCE_ROOT.is_dir():
        pytest.skip("retained New York 94-PDF evidence root is not present")

    receipts = []
    for receipt_path in sorted(
        (_RETAINED_NY_EVIDENCE_ROOT / "fetches").glob("*.json")
    ):
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipts.append(receipt)
    assert len(receipts) == 95

    by_url = {
        row["transport_receipt"]["official_url"]: row for row in receipts
    }
    catalog = by_url[NewYorkScraper.OFFICIAL_CONSOLIDATED_URL]
    catalog_body = (
        _RETAINED_NY_EVIDENCE_ROOT / catalog["body_relative_path"]
    ).read_bytes()
    assert hashlib.sha256(catalog_body).hexdigest() == (
        "d1113ce9a360c972649722dcfa9e99366b11aaf92464c18e4f5a5a6b24651b0a"
    )

    catalog_rows = NewYorkScraper("NY", "New York")._new_york_source_catalog_rows(
        catalog_body
    )
    items = []
    for code, name, _public_url in catalog_rows:
        url = ny_pdf.full_law_pdf_url(code)
        receipt = by_url[url]
        body_path = _RETAINED_NY_EVIDENCE_ROOT / receipt["body_relative_path"]
        assert body_path.is_file()
        items.append((code, name, body_path))
    assert len(items) == 94

    with ProcessPoolExecutor(max_workers=4) as executor:
        parsed = list(executor.map(_parse_retained_new_york_projection_item, items))

    totals = {
        "raw": sum(report.raw_section_marker_count for _code, report in parsed),
        "source_without_raw": sum(
            report.source_sections_without_raw_markers
            for _code, report in parsed
        ),
        "source": sum(report.source_section_count for _code, report in parsed),
        "embedded": sum(
            len(report.embedded_section_markers) for _code, report in parsed
        ),
        "lifecycle_alternates": sum(
            len(report.lifecycle_alternate_sections) for _code, report in parsed
        ),
        "operative": sum(len(report.statutes) for _code, report in parsed),
        "terminal": sum(
            len(report.terminal_sections) for _code, report in parsed
        ),
        "residual": sum(
            len(report.unclassified_sections) for _code, report in parsed
        ),
        "closed_laws": sum(report.closed for _code, report in parsed),
    }
    assert totals == _RETAINED_NY_PROJECTION
    assert totals["raw"] + totals["source_without_raw"] == (
        totals["source"]
        + totals["embedded"]
        + totals["lifecycle_alternates"]
    )
    assert totals["source"] == (
        totals["operative"] + totals["terminal"] + totals["residual"]
    )

    reports_by_code = dict(parsed)
    mhy = reports_by_code["MHY"]
    assert {
        row.section_number: row.structured_data["lifecycle_disposition"]
        for row in mhy.statutes
        if row.section_number in {"9.63", "31.27"}
    } == {"9.63": "effective_until", "31.27": "future_repeal"}
    assert any(
        row.get("section_number") == "9.63"
        and row.get("reason") == "adjacent_toc_body_order_inversion"
        for row in mhy.toc_body_corrections
    )

    rco = reports_by_code["RCO"]
    assert rco.closed is True
    assert any(
        row.get("section_number") == "28"
        and row.get("reason")
        == "source_proved_separately_amended_heading_alternate"
        for row in rco.toc_body_corrections
    )

    insurance_special_note_sections = {
        "4102",
        "4103",
        "4104",
        "4107",
        "4113",
        "6102",
        "6103",
    }
    isc = reports_by_code["ISC"]
    assert {
        row.section_number
        for row in isc.statutes
        if row.structured_data["lifecycle_disposition"]
        == "source_proved_unjuxtaposed_insurance_special_note"
    } == insurance_special_note_sections

    residual_rows = []
    for code, report in parsed:
        for row in report.unclassified_sections:
            detail = str(row.get("detail") or "")
            disposition = detail.split(":", 1)[0] if ":" in detail else ""
            residual_rows.append(
                "|".join(
                    (
                        code,
                        str(row.get("section_number") or "")
                        + str(row.get("toc_variant") or ""),
                        str(row.get("reason") or ""),
                        disposition,
                    )
                )
            )
    residual_projection = "\n".join(sorted(residual_rows)).encode("utf-8")
    assert hashlib.sha256(residual_projection).hexdigest() == (
        _RETAINED_NY_RESIDUAL_PROJECTION_SHA256
    )
    assert NewYorkScraper._new_york_exact_supplemental_urls(
        [report for _code, report in parsed]
    ) == list(NewYorkScraper.STRICT_CURRENT_SUPPLEMENTAL_SECTION_URLS)


def test_new_york_retained_agm28_registry_closes_exactly_one_residual() -> None:
    if not (
        _RETAINED_NY_EVIDENCE_ROOT.is_dir()
        and _RETAINED_NY_AGM_SELECTOR_ROOT.is_dir()
    ):
        pytest.skip("retained New York AGM selector evidence is not present")

    def _body_for(root: Path, official_url: str) -> bytes:
        matches = []
        for receipt_path in sorted((root / "fetches").glob("*.json")):
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if receipt["transport_receipt"]["official_url"] == official_url:
                matches.append(receipt)
        assert len(matches) == 1
        body_path = root / matches[0]["body_relative_path"]
        payload = body_path.read_bytes()
        assert hashlib.sha256(payload).hexdigest() == matches[0][
            "transport_receipt"
        ]["content_sha256"]
        return payload

    law_payload = _body_for(
        _RETAINED_NY_EVIDENCE_ROOT,
        ny_pdf.full_law_pdf_url("AGM"),
    )
    proof_payload = _body_for(
        _RETAINED_NY_AGM_SELECTOR_ROOT,
        ny_pdf.AGM28_LIFECYCLE_REPORT_URL,
    )
    assert hashlib.sha256(law_payload).hexdigest() == (
        "4fd2665e7d455bb0dc99727a80768063bd958b066d59fd31ba2c189668ffdfde"
    )
    assert hashlib.sha256(proof_payload).hexdigest() == (
        "6abaab50ad7bf3bec0c5c98949de8d543bdb4fb8b869f13a824776d39ed8580d"
    )

    before = ny_pdf.parse_new_york_law_pdf(
        law_payload,
        law_code="AGM",
        law_name="Agriculture and Markets",
    )
    proof = ny_pdf.NewYorkSupplementalProofInput.bind(
        selector_key=ny_pdf.AGM28_LIFECYCLE_SELECTOR_KEY,
        proof_kind="official_event_report",
        official_url=ny_pdf.AGM28_LIFECYCLE_REPORT_URL,
        media_type="application/pdf",
        payload=proof_payload,
    )
    registry = ny_pdf.NewYorkSupplementalProofRegistry([proof])
    after = ny_pdf.parse_new_york_law_pdf(
        law_payload,
        law_code="AGM",
        law_name="Agriculture and Markets",
        supplemental_proof_registry=registry,
    )

    assert (
        before.source_section_count,
        len(before.statutes),
        len(before.terminal_sections),
        len(before.unclassified_sections),
        before.closed,
    ) == (725, 722, 2, 1, False)
    assert (
        after.source_section_count,
        len(after.statutes),
        len(after.terminal_sections),
        len(after.unclassified_sections),
        after.closed,
    ) == (725, 722, 3, 0, True)
    agm28 = [
        row for row in after.terminal_sections if row["section_number"] == "28"
    ]
    assert len(agm28) == 1
    assert agm28[0]["lifecycle_selector"]["status"] == "occurred"


def test_new_york_frontier_accounts_for_raw_lifecycle_alternate_markers() -> None:
    scraper = NewYorkScraper("NY", "New York")
    report = {
        "law_code": "TST",
        "law_name": "Lifecycle Test",
        "source_url": ny_pdf.full_law_pdf_url("TST"),
        "content_sha256": "a" * 64,
        "pages": 1,
        "raw_section_markers": 3,
        "embedded_section_markers": 0,
        "lifecycle_alternate_sections": 1,
        "source_sections_without_raw_markers": 0,
        "source_sections": 2,
        "operative_sections": 1,
        "terminal_sections": 1,
        "closed": True,
    }

    frontier = scraper._new_york_exact_frontier(
        catalog_content_sha256="b" * 64,
        law_reports=[report],
        terminal_dispositions={"expired": 1},
    )

    assert frontier["schema_version"] == (
        "new-york-consolidated-source-frontier-v3"
    )
    assert frontier["raw_section_marker_count"] == 3
    assert frontier["source_section_count"] == 2
    assert frontier["embedded_section_marker_count"] == 0
    assert frontier["lifecycle_alternate_section_count"] == 1
    assert frontier["source_sections_without_raw_marker_count"] == 0

    unaccounted = {**report, "lifecycle_alternate_sections": 0}
    with pytest.raises(RuntimeError, match="raw PDF marker algebra"):
        scraper._new_york_exact_frontier(
            catalog_content_sha256="b" * 64,
            law_reports=[unaccounted],
            terminal_dispositions={"expired": 1},
        )


def test_new_york_pdf_parser_fails_closed_on_event_conditioned_repeal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = """
    ARTICLE 1
    STATUS TEST
    Section 28. Conditional repeal.
      * § 28. Conditional repeal. This official statutory body remains
      conditioned on an event that the retained law PDF does not resolve.
      * NB Repealed after the report required to this section has been delivered.
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 1),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-synthetic",
        law_code="AGM",
        law_name="Agriculture and Markets",
    )

    assert report.closed is False
    assert report.statutes == []
    assert report.unclassified_sections == [
        {
            "section_number": "28",
            "toc_variant": "",
            "reason": "ambiguous_lifecycle_status",
            "detail": (
                "event_conditioned_repeal: Repealed after the report required "
                "to this section has been delivered."
            ),
        }
    ]


def _agm28_selector_pdf(*, include_dates: bool = True) -> bytes:
    dates = (
        "<xmp:CreateDate>2022-12-22T16:40:04-05:00</xmp:CreateDate>"
        "<xmp:ModifyDate>2023-01-20T13:14:10-05:00</xmp:ModifyDate>"
        if include_dates
        else ""
    )
    return (
        "%PDF-1.6\n<x:xmpmeta><rdf:RDF><rdf:Description>"
        f"{dates}"
        "<dc:creator><rdf:Seq><rdf:li>McGovern, Sarah (AGRICULTURE)"
        "</rdf:li></rdf:Seq></dc:creator>"
        "</rdf:Description></rdf:RDF></x:xmpmeta>\n"
        + ("x" * 1_100)
    ).encode()


_AGM28_LAW_TEXT = """
ARTICLE 1
STATUS TEST
Section 28. Conditional repeal.
  * § 28. Conditional repeal. This official statutory body remains
  conditioned on an event that must be proved by independent official evidence.
  * NB Repealed after the report required to this section has been delivered.
"""
_AGM28_REPORT_TITLE = (
    "NYS Advisory Group for Improving Urban and Rural Consumer Access to "
    "Locally Produced, Healthy Foods 2022 Report. "
)
_AGM28_REPORT_RECIPIENTS = (
    "A report shall be delivered by the commissioner to the governor and "
    "the legislature on the findings and recommendations of such advisory group. "
)
_AGM28_REPORT_CONCLUSION = (
    "While the statutory requirement for this group concludes upon submission "
    "of this report, Commissioner Ball plans to continue the group's work."
)


def test_new_york_agm28_selector_requires_exact_report_conjunction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selector_pdf = _agm28_selector_pdf()
    monkeypatch.setattr(
        ny_pdf,
        "AGM28_LIFECYCLE_REPORT_SHA256",
        hashlib.sha256(selector_pdf).hexdigest(),
    )
    report_text = (
        _AGM28_REPORT_TITLE
        + _AGM28_REPORT_RECIPIENTS
        + _AGM28_REPORT_CONCLUSION
    )

    def _extract(payload: bytes):
        return (_AGM28_LAW_TEXT if payload == b"%PDF-law" else report_text, 1)

    monkeypatch.setattr(ny_pdf, "extract_new_york_law_pdf_text", _extract)
    monkeypatch.setattr(
        ny_pdf,
        "_agm28_active_xmp_metadata",
        lambda _payload: {
            "creator": "McGovern, Sarah (AGRICULTURE)",
            "create_date": "2022-12-22T16:40:04-05:00",
            "modify_date": "2023-01-20T13:14:10-05:00",
        },
    )
    outcome = ny_pdf.evaluate_new_york_agm28_lifecycle_report(
        selector_pdf,
        source_url=ny_pdf.AGM28_LIFECYCLE_REPORT_URL,
    )

    assert outcome["status"] == "occurred"
    assert all(outcome["conjuncts"].values())
    assert outcome["metadata"] == {
        "creator": "McGovern, Sarah (AGRICULTURE)",
        "create_date": "2022-12-22T16:40:04-05:00",
        "modify_date": "2023-01-20T13:14:10-05:00",
        "date_basis": "2023-01-20",
    }

    parsed = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-law",
        law_code="AGM",
        law_name="Agriculture and Markets",
        agm28_lifecycle_report_payload=selector_pdf,
        agm28_lifecycle_report_source_url=ny_pdf.AGM28_LIFECYCLE_REPORT_URL,
    )

    assert parsed.closed is True
    assert parsed.statutes == []
    assert parsed.unclassified_sections == []
    assert len(parsed.terminal_sections) == 1
    assert parsed.terminal_sections[0]["section_number"] == "28"
    assert parsed.terminal_sections[0]["disposition"] == "repealed"
    assert parsed.terminal_sections[0]["lifecycle_selector"] == outcome


def test_new_york_agm28_fixed_registry_preserves_existing_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selector_pdf = _agm28_selector_pdf()
    monkeypatch.setattr(
        ny_pdf,
        "AGM28_LIFECYCLE_REPORT_SHA256",
        hashlib.sha256(selector_pdf).hexdigest(),
    )
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda payload: (
            _AGM28_LAW_TEXT
            if payload == b"%PDF-law"
            else _AGM28_REPORT_TITLE
            + _AGM28_REPORT_RECIPIENTS
            + _AGM28_REPORT_CONCLUSION,
            1,
        ),
    )
    monkeypatch.setattr(
        ny_pdf,
        "_agm28_active_xmp_metadata",
        lambda _payload: {
            "creator": "McGovern, Sarah (AGRICULTURE)",
            "create_date": "2022-12-22T16:40:04-05:00",
            "modify_date": "2023-01-20T13:14:10-05:00",
        },
    )
    proof = ny_pdf.NewYorkSupplementalProofInput.bind(
        selector_key=ny_pdf.AGM28_LIFECYCLE_SELECTOR_KEY,
        proof_kind="official_event_report",
        official_url=ny_pdf.AGM28_LIFECYCLE_REPORT_URL,
        media_type="application/pdf",
        payload=selector_pdf,
    )
    registry = ny_pdf.NewYorkSupplementalProofRegistry([proof])

    parsed = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-law",
        law_code="AGM",
        law_name="Agriculture and Markets",
        supplemental_proof_registry=registry,
    )

    assert parsed.closed is True
    assert parsed.terminal_sections[0]["section_number"] == "28"
    assert parsed.terminal_sections[0]["lifecycle_selector"]["status"] == (
        "occurred"
    )
    assert registry.manifest()[0]["content_sha256"] == hashlib.sha256(
        selector_pdf
    ).hexdigest()


def test_new_york_unimplemented_supplemental_resolver_stays_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    law_text = """
    ARTICLE 1
    UNPROVED EVENT
    Section 1. Conditional provision.
      * § 1. Conditional provision. This retained statutory body contains
      complete source text but depends upon an independently proved event.
      * NB Effective upon notification by the responsible state agency.
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (law_text, 1),
    )
    section_url = "https://www.nysenate.gov/legislation/laws/AAA/1"
    proof = ny_pdf.NewYorkSupplementalProofInput.bind(
        selector_key="AAA:1:source-page",
        proof_kind="official_senate_section",
        official_url=section_url,
        media_type="text/html",
        payload=b"<html>" + (b"official section page " * 80) + b"</html>",
    )
    registry = ny_pdf.NewYorkSupplementalProofRegistry([proof])

    parsed = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-law",
        law_code="AAA",
        law_name="Unproved Event Law",
        supplemental_proof_registry=registry,
    )

    assert parsed.closed is False
    assert parsed.statutes == []
    assert parsed.terminal_sections == []
    assert len(parsed.unclassified_sections) == 1
    assert parsed.supplemental_proof_attempts[0]["status"] == "unknown"
    assert parsed.supplemental_proof_attempts[0]["proof_present"] is True
    assert parsed.supplemental_proof_attempts[0]["decision_action"] is None
    assert parsed.supplemental_proof_attempts[0]["reason"] == (
        "source_bound_resolver_not_implemented"
    )
    assert not hasattr(registry, "register_resolver")


@pytest.mark.parametrize(
    ("case", "report_text", "include_dates", "missing_conjunct"),
    [
        (
            "publication_only",
            _AGM28_REPORT_TITLE,
            True,
            "states_delivery_to_governor_and_legislature",
        ),
        (
            "missing_recipients",
            _AGM28_REPORT_TITLE + _AGM28_REPORT_CONCLUSION,
            True,
            "states_delivery_to_governor_and_legislature",
        ),
        (
            "missing_conclusion",
            _AGM28_REPORT_TITLE + _AGM28_REPORT_RECIPIENTS,
            True,
            "states_submission_of_this_report_concludes_requirement",
        ),
        (
            "missing_date",
            _AGM28_REPORT_TITLE
            + _AGM28_REPORT_RECIPIENTS
            + _AGM28_REPORT_CONCLUSION,
            False,
            "authoritative_dated_metadata_on_or_before_legal_as_of",
        ),
    ],
)
def test_new_york_agm28_selector_negative_conjuncts_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    report_text: str,
    include_dates: bool,
    missing_conjunct: str,
) -> None:
    selector_pdf = _agm28_selector_pdf(include_dates=include_dates)
    monkeypatch.setattr(
        ny_pdf,
        "AGM28_LIFECYCLE_REPORT_SHA256",
        hashlib.sha256(selector_pdf).hexdigest(),
    )

    def _extract(payload: bytes):
        return (_AGM28_LAW_TEXT if payload == b"%PDF-law" else report_text, 1)

    monkeypatch.setattr(ny_pdf, "extract_new_york_law_pdf_text", _extract)
    monkeypatch.setattr(
        ny_pdf,
        "_agm28_active_xmp_metadata",
        lambda _payload: {
            "creator": "McGovern, Sarah (AGRICULTURE)",
            "create_date": (
                "2022-12-22T16:40:04-05:00" if include_dates else ""
            ),
            "modify_date": (
                "2023-01-20T13:14:10-05:00" if include_dates else ""
            ),
        },
    )
    outcome = ny_pdf.evaluate_new_york_agm28_lifecycle_report(
        selector_pdf,
        source_url=ny_pdf.AGM28_LIFECYCLE_REPORT_URL,
    )
    parsed = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-law",
        law_code="AGM",
        law_name="Agriculture and Markets",
        agm28_lifecycle_report_payload=selector_pdf,
        agm28_lifecycle_report_source_url=ny_pdf.AGM28_LIFECYCLE_REPORT_URL,
    )

    assert outcome["status"] == "unknown", case
    assert outcome["conjuncts"][missing_conjunct] is False
    assert parsed.closed is False
    assert parsed.statutes == []
    assert parsed.terminal_sections == []
    assert parsed.unclassified_sections[0]["section_number"] == "28"
    assert parsed.unclassified_sections[0]["reason"] == (
        "ambiguous_lifecycle_status"
    )


def test_new_york_pdf_parser_preserves_source_proved_repeated_identities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = """
    ARTICLE 1
    REPEATED TESTS
    Section 6. First identity.
            6*2. Second identity.
      * § 6. First identity. This is the first distinct official statutory
      body with sufficient text for exact source reconciliation.
      * NB There are 2 § 6's
      * § 6. Second identity. This is the second distinct official statutory
      body with sufficient text for exact source reconciliation.
      * NB There are 2 § 6's
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 1),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-synthetic",
        law_code="TST",
        law_name="Repeated Identity Test",
    )

    assert report.closed is True
    assert report.source_section_count == 2
    assert [row.section_number for row in report.statutes] == ["6", "6"]
    assert len({row.statute_id for row in report.statutes}) == 2
    assert [
        row.structured_data["source_record_id"] for row in report.statutes
    ] == ["TST:6:source-1", "TST:6:variant-2"]


def test_new_york_pdf_parser_preserves_source_proved_separate_amendments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = """
    ARTICLE 1
    SEPARATE AMENDMENT TEST
    Section 6. Separately amended identity.
      * § 6. First amendment. This is the first complete official statutory
      body that the source says cannot be combined with the other amendment.
      * NB Separately amended; cannot be put together
      * § 6. Second amendment. This is the second complete official statutory
      body that the source says cannot be combined with the first amendment.
      * NB Separately amended; cannot be put together
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 1),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-separate-amendments",
        law_code="TST",
        law_name="Separate Amendment Test",
    )

    assert report.closed is True
    assert report.source_section_count == 2
    assert len(report.statutes) == 2
    assert report.lifecycle_alternate_sections == []
    assert {
        row.structured_data["lifecycle_disposition"] for row in report.statutes
    } == {"source_proved_separate_amendment"}


def test_new_york_pdf_parser_propagates_pure_repeated_identity_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = """
    ARTICLE 1
    REPEATED TESTS
    Section 6. Repeated identity.
      * § 6. First identity. This is a complete retained statutory body that
      has no separately printed note after this occurrence.
      * § 6. Second identity. This is another complete retained statutory body.
      * NB There are 3 § 6's
      * § 6. Third identity. This is the final complete retained statutory body
      and also has no separately printed note after this occurrence.
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 1),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-pure-repeated-group-note",
        law_code="TST",
        law_name="Repeated Identity Test",
    )

    assert report.closed is True
    assert report.raw_section_marker_count == 3
    assert report.source_section_count == 3
    assert len(report.statutes) == 3
    assert report.lifecycle_alternate_sections == []
    assert {
        row.structured_data["lifecycle_disposition"] for row in report.statutes
    } == {"source_proved_repeated_identity"}


@pytest.mark.parametrize(
    "note",
    [
        "There are 2 § 6's",
        "Agency expires upon bond redemption | There are 3 § 6's",
    ],
)
def test_new_york_pdf_parser_rejects_unproved_repeated_note_propagation(
    monkeypatch: pytest.MonkeyPatch,
    note: str,
) -> None:
    text = f"""
    ARTICLE 1
    REPEATED TESTS
    Section 6. Repeated identity.
      * § 6. First identity. This is a complete retained statutory body.
      * § 6. Second identity. This is another complete retained statutory body.
      * NB {note}
      * § 6. Third identity. This is the final complete retained statutory body.
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 1),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-unproved-repeated-group-note",
        law_code="TST",
        law_name="Repeated Identity Test",
    )

    assert report.closed is False
    assert report.statutes == []
    assert any(
        row.get("reason") == "ambiguous_lifecycle_status"
        for row in report.unclassified_sections
    )


def test_new_york_pdf_parser_keeps_source_bound_model_law_in_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = """
    ARTICLE 1
    MODEL TESTS
    Section 10. Parent model law.
            11. Following provision.
      § 10. Parent model law. The model local law is as follows:
      § 1. Quoted model identity. This quoted identity stays in the parent body.
      § 2. Another quoted identity. This quoted identity also stays in the parent.
      § 11. Following provision. This is another complete operative official
      statutory provision.
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 1),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-synthetic",
        law_code="TST",
        law_name="Nested Model Test",
    )

    assert report.closed is True
    assert [row.section_number for row in report.statutes] == ["10", "11"]
    assert [row["section_number"] for row in report.embedded_section_markers] == [
        "1",
        "2",
    ]
    assert "§ 2. Another quoted identity" in report.statutes[0].full_text


def test_new_york_pdf_parser_requires_heading_proof_for_printed_correction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = """
    ARTICLE 1
    CORRECTION TEST
    Section 445. Plattsburgh housing authority.
      § 455. Plattsburgh housing authority. This official body has a printed
      number corrected by its identical generated source heading.
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 1),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-synthetic",
        law_code="PBG",
        law_name="Public Housing",
    )

    assert report.closed is True
    assert [row.section_number for row in report.statutes] == ["445"]
    assert report.statutes[0].structured_data["printed_section_number"] == "455"
    assert report.toc_body_corrections == [
        {
            "section_number": "445",
            "printed_section_number": "455",
            "reason": "toc_body_identity_correction",
            "detail": "Plattsburgh housing authority.",
        }
    ]


def test_new_york_pdf_parser_corrects_cursor_bound_nonconfusable_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = """
    TITLE 17
    SOURCE INVENTORY
    Section 71-1719. Summary action.
            71-1721. Commissioner's enforcement power and duty.
            71-1723. Issuance of subpoenas.
      § 71-1719. Summary action. This is complete retained statutory text.
      § 17-1721. Commissioner's enforcement power and duty. This retained
      body has the official PDF's non-confusable printed number error.
      § 71-1723. Issuance of subpoenas. This is complete retained text.
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 1),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-retained-number-error",
        law_code="ENV",
        law_name="Environmental Conservation Law",
    )

    assert report.closed is True
    corrected = next(row for row in report.statutes if row.section_number == "71-1721")
    assert corrected.structured_data["printed_section_number"] == "17-1721"
    assert report.toc_body_corrections[-1]["section_number"] == "71-1721"


def test_new_york_pdf_parser_admits_newer_local_inventory_addition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = """
    CONSOLIDATED SCHEDULE
    Section 101. Short title.
            102. Definitions.
            1101. Fees.
            1102. Records.
            1201. Definitions.
    ARTICLE I
    SHORT TITLE AND DEFINITIONS
      § 101. Short title. This chapter has the title stated in this complete
      retained statutory provision.
      § 102. Definitions. These complete definitions govern the retained law.
    ARTICLE XI
    MISCELLANEOUS
    Section 1101. Fees.
            1102. Records.
            1105. Limited liability geology company.
            1106. Beneficial ownership definitions.
      § 1101. Fees. The department shall collect the fees stated in this
      complete retained statutory provision.
      § 1102. Records. The department shall retain the complete records
      required by this official statutory provision.
      § 1105. Limited liability geology company. An eligible company may
      amend its articles under the requirements of this retained provision.
      § 1106. Beneficial ownership definitions. These complete definitions
      govern the following retained statutory provisions.
    ARTICLE XII
    PROFESSIONAL SERVICES
    Section 1201. Definitions.
      § 1201. Definitions. These complete professional-service definitions
      apply throughout this retained article.
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 1),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-newer-local-inventory",
        law_code="LLC",
        law_name="Limited Liability Company Law",
    )

    assert report.closed is True
    assert [row.section_number for row in report.statutes] == [
        "101",
        "102",
        "1101",
        "1102",
        "1105",
        "1106",
        "1201",
    ]
    assert report.unclassified_sections == []


def test_new_york_pdf_parser_reconciles_retained_agm_variant_to_printed_383(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Reduced structural fragment from retained official AGM PDF body SHA-256
    # 4fd2665e7d455bb0dc99727a80768063bd958b066d59fd31ba2c189668ffdfde.
    # Its generated TOC retains the second source identity as 380*2 while the
    # exact same heading is printed on the statutory body as section 383.
    text = """
    ARTICLE 26
    ANIMALS
    Section 379. Prohibition of the selling of fur, hair, skin or flesh of a
                   dog or cat.
            380. Use of elephants in entertainment acts.
            380*2. Examination of seized animals or animals taken possession
                   of.
            381. Prohibition of the declawing of cats.
            382. Prohibition of the slaughter of race horses and race horse
                   breeding stock.
            384. Special provisions related to the importation of dogs and
                   cats into the state for sale, resale or adoption.
      § 379. Prohibition of the selling of fur, hair, skin or flesh of a dog
      or cat. This retained official body supplies complete statutory text.
      § 380. Use of elephants in entertainment acts. No person shall use or
      cause elephants to be used in an entertainment act in this state.
      § 381. Prohibition of the declawing of cats. This retained official
      body supplies complete statutory text for the source identity.
      § 382. Prohibition of the slaughter of race horses and race horse
      breeding stock. This retained body supplies complete statutory text.
      § 383. Examination of seized animals or animals taken possession of.
      This retained official body requires an identification examination and
      supplies complete statutory text for the source-proved identity.
      § 384. Special provisions related to the importation of dogs and cats
      into the state for sale, resale or adoption. This is complete text.
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 1),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-retained-agm-fragment",
        law_code="AGM",
        law_name="Agriculture and Markets",
    )

    assert report.closed is True
    assert report.raw_section_marker_count == 6
    assert report.source_section_count == 6
    assert report.unclassified_sections == []
    assert report.toc_body_corrections == [
        {
            "section_number": "380",
            "printed_section_number": "383",
            "reason": "toc_body_identity_correction",
            "detail": "Examination of seized animals or animals taken possession",
        }
    ]
    corrected = next(
        row
        for row in report.statutes
        if row.structured_data["printed_section_number"] == "383"
    )
    assert corrected.section_number == "380"
    assert corrected.structured_data["toc_variant"] == "*2"
    assert corrected.structured_data["source_record_id"] == "AGM:380:variant-2"
    assert corrected.full_text.startswith("§ 383. Examination of seized animals")
    assert len({row.statute_id for row in report.statutes}) == 6


def test_new_york_pdf_parser_rejects_ambiguous_variant_heading_correction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = """
    ARTICLE 26
    ANIMALS
    Section 379. Fur prohibition.
            380. Elephant prohibition.
            380*2. Examination of seized animals or animals taken possession.
            381. Declawing prohibition.
            382. Race horse protection.
            384. Importation requirements.
      § 379. Fur prohibition. This is complete official statutory body text.
      § 380. Elephant prohibition. This is complete official statutory text.
      § 381. Declawing prohibition. This is complete official statutory text.
      § 382. Race horse protection. This is complete official statutory text.
      § 383. Examination of seized animals or animals taken possession.
      This is one possible body and cannot establish a unique correction.
      § 387. Examination of seized animals or animals taken possession.
      This second possible body makes the heading correction ambiguous.
      § 384. Importation requirements. This is complete official text.
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 1),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-ambiguous-agm-fragment",
        law_code="AGM",
        law_name="Agriculture and Markets",
    )

    assert report.closed is False
    assert report.toc_body_corrections == []
    assert report.source_sections_without_raw_markers == 1
    assert any(
        row.get("section_number") == "380"
        and row.get("toc_variant") == "*2"
        and row.get("reason") == "toc_section_missing_body_identity"
        for row in report.unclassified_sections
    )


def test_new_york_pdf_parser_admits_heading_proved_rule_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = """
    ARTICLE 3
    JURISDICTION AND SERVICE
    Section 301. Jurisdiction over persons, property or status.
            305. Summons; supplemental summons, amendment.
      § 301. Jurisdiction over persons, property or status. This retained
      provision supplies complete official statutory text for jurisdiction.
      Rule. 305. Summons; supplemental summons, amendment. A summons shall
      specify the basis of venue and contain the information required by this
      rule. This retained body continues with enough official statutory text
      to distinguish a substantive rule body from a generated contents row.
      The supplemental summons shall also comply with every applicable filing
      and service requirement stated by this rule and related provisions.
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 1),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-retained-rule-fragment",
        law_code="CVP",
        law_name="Civil Practice Law and Rules",
    )

    assert report.closed is True
    assert report.raw_section_marker_count == 2
    assert report.source_section_count == 2
    assert [row.section_number for row in report.statutes] == ["301", "305"]
    assert report.statutes[1].full_text.lstrip().startswith("Rule. 305.")


@pytest.mark.parametrize(
    ("rule_heading", "rule_body"),
    [
        (
            "A different rule heading.",
            "This is deliberately long body text. " * 20,
        ),
        (
            "Summons; supplemental summons, amendment.",
            "Too short.",
        ),
    ],
)
def test_new_york_pdf_parser_rejects_unproved_rule_body(
    monkeypatch: pytest.MonkeyPatch,
    rule_heading: str,
    rule_body: str,
) -> None:
    text = f"""
    ARTICLE 3
    JURISDICTION AND SERVICE
    Section 301. Jurisdiction over persons, property or status.
            305. Summons; supplemental summons, amendment.
      § 301. Jurisdiction over persons, property or status. This retained
      provision supplies complete official statutory text for jurisdiction.
      Rule 305. {rule_heading} {rule_body}
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 1),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-unproved-rule-fragment",
        law_code="CVP",
        law_name="Civil Practice Law and Rules",
    )

    assert report.closed is False
    assert report.source_sections_without_raw_markers == 1
    assert any(
        row.get("section_number") == "305"
        and row.get("reason") == "toc_section_missing_body_identity"
        for row in report.unclassified_sections
    )


def test_new_york_pdf_parser_admits_heading_proved_bare_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = """
    ARTICLE 2
    SOURCE INVENTORY
    Section 1. First operative provision.
            2. Priority of liens.
      § 1. First operative provision. This retained source body supplies
      complete statutory text for the first authoritative identity.
      2. Priority of liens. (1) A lien for materials furnished or labor
      performed shall have the priority established in this section. This
      retained source body contains enough additional official statutory text
      to distinguish it from the earlier generated contents row.
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 1),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-retained-bare-body-fragment",
        law_code="LIE",
        law_name="Lien Law",
    )

    assert report.closed is True
    assert report.raw_section_marker_count == 2
    assert report.source_sections_without_raw_markers == 0
    assert [row.section_number for row in report.statutes] == ["1", "2"]
    assert report.statutes[1].full_text.lstrip().startswith("2. Priority")


@pytest.mark.parametrize(
    "bare_body",
    [
        "2. Priority of liens.\n" + ("Long continuation without inline text. " * 12),
        "2. Different heading. This is purported statutory body text. " * 8,
    ],
)
def test_new_york_pdf_parser_rejects_unproved_bare_body(
    monkeypatch: pytest.MonkeyPatch,
    bare_body: str,
) -> None:
    text = f"""
    ARTICLE 2
    SOURCE INVENTORY
    Section 1. First operative provision.
            2. Priority of liens.
      § 1. First operative provision. This retained source body supplies
      complete statutory text for the first authoritative identity.
      {bare_body}
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 1),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-unproved-bare-body-fragment",
        law_code="LIE",
        law_name="Lien Law",
    )

    assert report.closed is False
    assert report.source_sections_without_raw_markers == 1
    assert any(
        row.get("section_number") == "2"
        and row.get("reason") == "toc_section_missing_body_identity"
        for row in report.unclassified_sections
    )


def test_new_york_pdf_parser_rejects_bare_citation_continuation_as_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = """
    ARTICLE 17
    SOURCE INVENTORY
    Section 1. First operative provision.
            19 of article 17.
      § 1. First operative provision. This retained source body supplies
      complete statutory text for the first authoritative identity.
      19 of article 17. This line is a citation continuation inside the
      operative body, not an independently numbered statutory source leaf.
      It therefore must not satisfy the generated inventory residual.
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 1),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-bare-citation-continuation",
        law_code="ENV",
        law_name="Environmental Conservation Law",
    )

    assert report.closed is False
    assert report.raw_section_marker_count == 1
    assert report.source_sections_without_raw_markers == 1
    assert any(
        row.get("section_number") == "19"
        and row.get("reason") == "toc_section_missing_body_identity"
        for row in report.unclassified_sections
    )


def test_new_york_pdf_parser_rejects_deep_toc_heading_citation_as_leaf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = """
    ARTICLE 26
    ESTATE TAX
    Section 979. Report of change in federal taxable estate, adjusted
                     taxable gifts, additional estate tax imposed by section
                     2032A of the internal revenue code.
            979-a. Notification by surrogate to commissioner concerning tax.
      § 979. Report of change in federal taxable estate, adjusted taxable
      gifts and additional estate tax. This is complete retained text.
      § 979-a. Notification by surrogate to commissioner concerning tax.
      This retained source body includes the governing internal revenue code
      context and a quoted federal provision below.
      § 2032A. Valuation of certain farm real property. This is nested federal
      code text and is not a New York Tax Law source identity.
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 1),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-deep-heading-citation",
        law_code="TAX",
        law_name="Tax Law",
    )

    assert report.closed is True
    assert report.raw_section_marker_count == 3
    assert report.source_section_count == 2
    assert [row.section_number for row in report.statutes] == ["979", "979-a"]
    assert report.embedded_section_markers == [
        {
            "section_number": "2032A",
            "parent_section_number": "979-a",
            "reason": "embedded_federal_code_section_header",
        }
    ]


def test_new_york_pdf_parser_keeps_aligned_dotless_toc_leaf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = """
    ARTICLE 1
    SOURCE INVENTORY
    Section 1. First operative provision.
            27.09 Convictions; bail forfeitures; failure to appear.
      § 1. First operative provision. This retained source body supplies
      complete statutory text for the first authoritative identity.
      § 27.09 Convictions; bail forfeitures; failure to appear. This retained
      source body supplies complete statutory text for the dotless TOC row.
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 1),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-aligned-dotless-row",
        law_code="PAR",
        law_name="Parks, Recreation and Historic Preservation Law",
    )

    assert report.closed is True
    assert [row.section_number for row in report.statutes] == ["1", "27.09"]


def test_new_york_toc_parser_rejects_prose_section_candidates() -> None:
    text = """
    ARTICLE 1
    SOURCE INVENTORY
    Section 1. First operative provision.
      § 1. First operative provision. This retained body cites
    section 9.43 of the mental hygiene law before numbered subdivisions.
      3-b. This is a subdivision of section one, not a source leaf.
      § 9.43. Quoted material that must not prove the lowercase citation.
    """

    matches = list(ny_pdf._SECTION_HEADER_RE.finditer(text))
    blocks = ny_pdf._extract_standard_toc_blocks(text, matches)

    assert len(blocks) == 1
    assert [entry.section for entry in blocks[0].entries] == ["1"]


def test_new_york_pdf_parser_admits_applicable_historical_text_without_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = """
    The text of article 5 of the former state housing law continues to be
    applicable alongside the current Public Housing Law.
    ARTICLE 5
    HISTORICAL APPLICATION
    Section 1.Application of article.
      * § 1. Application of article. This historical text remains applicable
      and is complete official statutory text.
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 1),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-synthetic",
        law_code="MHA",
        law_name="Multiple Dwelling Historical Article",
    )

    assert report.closed is True
    assert [row.section_number for row in report.statutes] == ["1"]
    assert report.statutes[0].structured_data["lifecycle_disposition"] == (
        "applicable_historical_text"
    )


def test_new_york_pdf_parser_reconciles_ucc_section_form_and_local_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = """
    TABLE OF CONTENTS
    Section 1--101. Short title.
            1--102. Scope.
    ARTICLE 1
    GENERAL PROVISIONS
    Section 1--101. Short title.
    This act shall be known as the Uniform Commercial Code and supplies
    complete official statutory text.
    Section 1--102. Scope.
    Section 1--102. Scope.
    This section states the complete scope of this official statutory article.
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (text, 1),
    )

    report = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-synthetic",
        law_code="UCC",
        law_name="Uniform Commercial Code",
    )

    assert report.closed is True
    assert report.raw_section_marker_count == 3
    assert report.source_section_count == 2
    assert [row.section_number for row in report.statutes] == [
        "1--101",
        "1--102",
    ]
    assert report.embedded_section_markers == [
        {
            "section_number": "1--102",
            "parent_section_number": "1--101",
            "reason": "source_toc_bounded_nested_section_header",
        }
    ]


def _ordered_code_sha256(*codes: str) -> str:
    return hashlib.sha256(
        json.dumps(list(codes), separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _ordered_chapter_sha256(*chapters: str) -> str:
    return hashlib.sha256("\n".join(chapters).encode("utf-8")).hexdigest()


def test_michigan_current_compatibility_catalog_matches_pinned_membership() -> None:
    scraper = MichiganScraper("MI", "Michigan")
    chapters = tuple(str(number) for number in scraper.OFFICIAL_CHAPTERS)

    assert len(chapters) == 227
    assert _ordered_chapter_sha256(*chapters) == (
        scraper.STRICT_CURRENT_CHAPTER_NUMBER_SHA256
    )


def test_michigan_catalog_rejects_ordered_membership_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = (
        "<html><head><title>MCL Chapter Index</title></head><body>"
        "<a href='/Home/GetObject?objectName=mcl-chap1'>Chapter 1</a>"
        "<a href='/Home/GetObject?objectName=mcl-chap2'>Chapter 2</a>"
        "</body></html>"
    ).encode()
    monkeypatch.setattr(MichiganScraper, "STRICT_MINIMUM_CHAPTERS", 2)
    monkeypatch.setattr(
        MichiganScraper,
        "STRICT_CURRENT_CHAPTER_NUMBER_SHA256",
        _ordered_chapter_sha256("2", "1"),
    )

    with pytest.raises(RuntimeError, match="changed exact ordered membership"):
        MichiganScraper("MI", "Michigan")._michigan_source_catalog_rows(root)


@pytest.mark.anyio
async def test_michigan_incomplete_batch_exposes_shared_transport_stats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls = [
        "https://www.legislature.mi.gov/documents/mcl/Chapter%201.xml",
        "https://www.legislature.mi.gov/documents/mcl/Chapter%202.xml",
    ]
    shared_stats = {
        "requested_pages": 2,
        "successful_pages": 0,
        "wayback_inventory": {
            "prefix_groups_planned": 1,
            "prefix_queries_planned": 1,
            "cdx_requests": 1,
            "inventory_rows": 2,
            "eligible_capture_rows": 2,
            "matched_pages": 2,
            "selected_capture_replays": 2,
            "successful_capture_replays": 0,
            "failed_capture_replays": 2,
        },
        "per_page_archive_fallback_disabled": True,
    }

    async def _failed_plural(
        _self,
        requested,
        *,
        residual_retry_attempts,
        repeat_grouped_archive_inventory_on_residual,
        **_kwargs,
    ):
        assert list(requested) == urls
        assert residual_retry_attempts == 1
        assert repeat_grouped_archive_inventory_on_residual is False
        result = _aligned_result(
            urls,
            [b"", b""],
            errors=["Wayback replay miss", "Wayback replay miss"],
        )
        result.stats = shared_stats
        return result

    monkeypatch.setattr(
        MichiganScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _failed_plural,
    )
    scraper = MichiganScraper("MI", "Michigan")

    with pytest.raises(RuntimeError, match="frontier is incomplete"):
        await scraper._fetch_michigan_frontier_batch(
            urls,
            frontier_name="chapter-xml-1-2",
            content_validator=scraper._is_valid_michigan_chapter_xml,
            media_type="text/xml",
            common_crawl_url_terms=("/documents/mcl/",),
        )

    assert scraper._michigan_frontier_batch_stats == [
        {
            **shared_stats,
            "frontier_name": "chapter-xml-1-2",
            "requested_pages": 2,
            "frontier_complete": False,
            "unresolved_pages": 2,
            "unresolved_urls": urls,
        }
    ]
    inventory = scraper._michigan_frontier_batch_stats[0]["wayback_inventory"]
    assert inventory["inventory_rows"] == 2
    assert inventory["selected_capture_replays"] == 2
    assert inventory["failed_capture_replays"] == 2
    assert scraper._michigan_frontier_batch_stats[0][
        "per_page_archive_fallback_disabled"
    ] is True


@pytest.mark.anyio
async def test_michigan_227_xml_wave_partitions_into_bounded_cdx_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import re
    from urllib.parse import parse_qs, urlparse

    from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine

    urls = [
        chapter_xml_url(str(chapter))
        for chapter in MichiganScraper.OFFICIAL_CHAPTERS
    ]
    query_target_counts: list[int] = []
    query_prefixes: list[str] = []

    async def _query(cdx_url: str, *, timeout_seconds: int):
        del timeout_seconds
        assert len(cdx_url.encode("ascii")) <= 2_048
        query = parse_qs(urlparse(cdx_url).query)
        expression = query["filter"][1].split(":", 1)[1]
        matches = [url for url in urls if re.fullmatch(expression, url)]
        query_prefixes.append(query["url"][0])
        query_target_counts.append(len(matches))
        assert 0 < len(matches) <= 8
        return {
            "status": "success",
            "results": [
                {
                    "timestamp": "20260826000000",
                    "original_url": url,
                    "statuscode": "200",
                    "mimetype": "text/xml",
                }
                for url in matches
            ],
        }

    monkeypatch.setattr(wayback_machine_engine, "fetch_wayback_cdx_rows", _query)
    outcome = await wayback_machine_engine.fetch_wayback_capture_inventory(
        urls,
        max_queries=1,
        max_results_per_query=5_000,
        query_attempts=1,
    )

    assert query_target_counts == ([8] * 28) + [3]
    assert set(query_prefixes) == {
        "https://www.legislature.mi.gov/documents/mcl/Chapter%20"
    }
    assert set(outcome["captures_by_url"]) == set(urls)
    assert outcome["stats"]["requested_pages"] == 227
    assert outcome["stats"]["prefix_groups_planned"] == 1
    assert outcome["stats"]["exact_filter_query_batches"] == 29
    assert outcome["stats"]["exact_filter_batches_added"] == 28
    assert outcome["stats"]["query_target_bound"] == 8
    assert outcome["stats"]["query_url_byte_bound"] == 2_048


@pytest.mark.anyio
async def test_michigan_residual_retry_omits_resolved_urls_and_reinventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls = [chapter_xml_url(str(chapter)) for chapter in (1, 2, 3)]
    payloads = [_mi_xml("1", "1.1"), _mi_xml("2", "2.1"), _mi_xml("3", "3.1")]
    calls: list[tuple[list[str], dict]] = []

    async def _fake_plural(_self, requested, **kwargs):
        requested_urls = list(requested)
        calls.append((requested_urls, dict(kwargs)))
        if len(calls) == 1:
            result = _aligned_result(
                requested_urls,
                [payloads[0], b"", payloads[2]],
                errors=[None, "transient direct/archive miss", None],
            )
            result.stats.update(
                {
                    "network_requested_pages": 3,
                    "common_crawl_inventory_queries": 1,
                    "common_crawl_inventory_memo": {"shared_domain_queries": 1},
                }
            )
            return result
        assert requested_urls == [urls[1]]
        result = _aligned_result(requested_urls, [payloads[1]])
        result.stats.update(
            {
                "network_requested_pages": 1,
                "common_crawl_inventory_queries": 0,
                "common_crawl_inventory_memo": {"shared_domain_queries": 0},
            }
        )
        return result

    monkeypatch.setattr(
        MichiganScraper,
        "_fetch_page_contents_with_archival_fallback",
        _fake_plural,
    )
    scraper = MichiganScraper("MI", "Michigan")
    result = await scraper._fetch_michigan_frontier_batch(
        urls,
        frontier_name="chapter-xml-1-3",
        content_validator=scraper._is_valid_michigan_chapter_xml,
        media_type="text/xml",
        common_crawl_url_terms=("/documents/mcl/",),
    )

    assert [requested for requested, _kwargs in calls] == [urls, [urls[1]]]
    assert "archive_recovery_enabled" not in calls[0][1]
    assert calls[1][1]["archive_recovery_enabled"] is False
    assert result.payloads == payloads
    assert result.errors == [None, None, None]
    stats = scraper._michigan_frontier_batch_stats[0]
    assert stats["residual_retry_rounds_executed"] == 1
    assert stats["residual_retry_requested_pages"] == 1
    assert stats["residual_retry_recovered_pages"] == 1
    assert stats["residual_retry_unresolved_pages"] == 0
    assert [
        row["archive_recovery_enabled"]
        for row in stats["residual_retry_attempt_batches"]
    ] == [True, False]
    assert [
        row["requested_urls"] for row in stats["residual_retry_attempt_batches"]
    ] == [urls, [urls[1]]]


@pytest.mark.anyio
async def test_michigan_frontier_rejects_repeated_same_domain_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://www.legislature.mi.gov/documents/mcl/Chapter%201.xml"
    payload = _mi_xml("1", "1.1")

    async def _repeated_inventory(_self, requested, **_kwargs):
        result = _aligned_result(list(requested), [payload])
        result.stats.update(
            {
                "common_crawl_inventory_queries": 1,
                "common_crawl_inventory_memo": {"shared_domain_queries": 2},
            }
        )
        return result

    monkeypatch.setattr(
        MichiganScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _repeated_inventory,
    )

    with pytest.raises(RuntimeError, match="repeated a same-domain Common Crawl"):
        await MichiganScraper("MI", "Michigan")._fetch_michigan_frontier_batch(
            [url],
            frontier_name="chapter-xml-1-1",
            content_validator=MichiganScraper._is_valid_michigan_chapter_xml,
            media_type="text/xml",
            common_crawl_url_terms=("/documents/mcl/",),
        )


def test_new_york_catalog_keeps_statutes_separate_from_other_legal_corpora(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = (
        "<html><head><title>Consolidated Laws of New York</title></head><body>"
        "<a href='/legislation/laws/CNS'>CNS Constitution</a>"
        "<a href='/legislation/laws/NYCRR'>NYCRR Administrative Regulations</a>"
        "<a href='/legislation/laws/UNCONSOLIDATED'>Unconsolidated Laws</a>"
        "<a href='/legislation/laws/RULES'>Court Rules</a>"
        "<a href='https://newyork.public.law/laws/example'>Editorial mirror</a>"
        "<a href='https://web.archive.org/web/20260811192739/"
        "https://www.nysenate.gov/legislation/laws/SAP'>"
        "SAP State Administrative Procedure Act</a>"
        "<a href='/legislation/laws/ABC'>ABC Alcoholic Beverage Control</a>"
        + (" " * 11_000)
        + "</body></html>"
    ).encode()
    monkeypatch.setattr(NewYorkScraper, "STRICT_MINIMUM_CONSOLIDATED_LAWS", 2)
    monkeypatch.setattr(
        NewYorkScraper,
        "STRICT_CURRENT_CONSOLIDATED_CODE_SHA256",
        _ordered_code_sha256("SAP", "ABC"),
    )

    rows = NewYorkScraper("NY", "New York")._new_york_source_catalog_rows(
        catalog
    )

    assert [(code, name) for code, name, _url in rows] == [
        ("SAP", "State Administrative Procedure Act"),
        ("ABC", "Alcoholic Beverage Control"),
    ]


def test_new_york_catalog_rejects_wayback_rewrite_to_secondary_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = (
        "<html><head><title>Consolidated Laws of New York</title></head><body>"
        "<a href='https://web.archive.org/web/20260811192739/"
        "https://newyork.public.law/legislation/laws/ZZZ'>ZZZ Mirror</a>"
        + (" " * 11_000)
        + "</body></html>"
    ).encode()
    monkeypatch.setattr(NewYorkScraper, "STRICT_MINIMUM_CONSOLIDATED_LAWS", 1)
    monkeypatch.setattr(
        NewYorkScraper,
        "STRICT_CURRENT_CONSOLIDATED_CODE_SHA256",
        _ordered_code_sha256("ZZZ"),
    )

    with pytest.raises(RuntimeError, match="changed exact official law identity"):
        NewYorkScraper("NY", "New York")._new_york_source_catalog_rows(catalog)


def test_new_york_catalog_rejects_ordered_membership_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = (
        "<html><head><title>Consolidated Laws of New York</title></head><body>"
        "<a href='/legislation/laws/ABC'>ABC Alcoholic Beverage Control</a>"
        "<a href='/legislation/laws/SAP'>SAP State Administrative Procedure Act</a>"
        + (" " * 11_000)
        + "</body></html>"
    ).encode()
    monkeypatch.setattr(NewYorkScraper, "STRICT_MINIMUM_CONSOLIDATED_LAWS", 2)
    monkeypatch.setattr(
        NewYorkScraper,
        "STRICT_CURRENT_CONSOLIDATED_CODE_SHA256",
        _ordered_code_sha256("SAP", "ABC"),
    )

    with pytest.raises(RuntimeError, match="ordered membership drifted"):
        NewYorkScraper("NY", "New York")._new_york_source_catalog_rows(catalog)


@pytest.mark.anyio
async def test_michigan_full_frontier_uses_one_227_xml_wave_and_closes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    chapters = tuple(str(chapter) for chapter in MichiganScraper.OFFICIAL_CHAPTERS)
    root = (
        "<html><head><title>MCL Chapter Index</title></head><body>"
        + "".join(
            "<a href='/Home/GetObject?objectName=mcl-chap"
            f"{chapter}'>Chapter {chapter}</a>"
            for chapter in chapters
        )
        + (" " * 6_000)
        + "</body></html>"
    ).encode()
    xml_by_url = {
        chapter_xml_url(chapter): _mi_xml(chapter, f"{chapter}.1")
        for chapter in chapters
    }
    calls = []

    async def _fake_plural(self, urls, *, residual_retry_attempts, **kwargs):
        requested = list(urls)
        calls.append((requested, residual_retry_attempts, dict(kwargs)))
        payloads = [root if url == self.OFFICIAL_ENTRY_URL else xml_by_url[url] for url in requested]
        assert all(kwargs["content_validator"](payload) for payload in payloads)
        result = _aligned_result(requested, payloads)
        result.stats.update(
            {
                "unique_pages": len(requested),
                "successful_pages": len(requested),
                "wayback_inventory": {
                    "prefix_groups_planned": 1,
                    "prefix_queries_planned": 29 if len(requested) == 227 else 1,
                    "exact_filter_query_batches": 29 if len(requested) == 227 else 1,
                    "query_target_bound": 8,
                    "query_url_byte_bound": 2_048,
                },
                "per_page_archive_fallback_disabled": True,
            }
        )
        return result

    async def _forbid_single(*_args, **_kwargs):
        raise AssertionError("strict Michigan must not use a per-page archive loop")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        MichiganScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _fake_plural,
    )
    monkeypatch.setattr(
        MichiganScraper,
        "_fetch_page_content_with_archival_fallback",
        _forbid_single,
    )

    scraper = MichiganScraper("MI", "Michigan")
    assert scraper._supports_shared_official_frontier_bridge() is False
    rows = await scraper.scrape_code(
        "Michigan Compiled Laws",
        MichiganScraper.OFFICIAL_ENTRY_URL,
        max_statutes=None,
    )

    assert [row.section_number for row in rows] == [
        f"{chapter}.1" for chapter in chapters
    ]
    assert [len(call[0]) for call in calls] == [1, 227]
    assert calls[1][0] == list(xml_by_url)
    assert all(call[2]["prefer_direct"] is True for call in calls)
    assert all(call[2]["wayback_prefix_inventory"] is True for call in calls)
    assert all(
        call[2]["repeat_grouped_archive_inventory_on_residual"] is False
        for call in calls
    )
    assert all(
        call[2]["common_crawl_domain_terms"] == (scraper.OFFICIAL_DOMAIN,)
        for call in calls
    )
    assert scraper._last_michigan_strict_closure["closed"] is True
    assert scraper._last_michigan_strict_closure["source_sections"] == 227
    batch_stats = scraper._last_michigan_strict_closure["batch_stats"]
    assert [row["frontier_name"] for row in batch_stats] == [
        "chapter-index",
        "chapter-xml-1-227",
    ]
    assert [row["requested_pages"] for row in batch_stats] == [1, 227]
    assert [row["frontier_complete"] for row in batch_stats] == [True, True]
    assert batch_stats[1]["wayback_inventory"]["prefix_groups_planned"] == 1
    assert batch_stats[1]["wayback_inventory"]["exact_filter_query_batches"] == 29

    retained_payloads = {scraper.OFFICIAL_ENTRY_URL: root, **xml_by_url}
    ledger = _RetainedInputLedger(retained_payloads)
    scraper._state_law_acquisition_ledger = ledger
    captured = {}

    def _retain(completion_receipt, **kwargs):
        captured["completion"] = dict(completion_receipt)
        captured["kwargs"] = dict(kwargs)
        return tmp_path / "mi-closure.json"

    def _forbid_legacy_catalog(*_args, **_kwargs):
        raise AssertionError("Michigan certification must not use fetch_official")

    monkeypatch.setattr(
        scraper,
        "retain_state_law_frontier_closure_projection",
        _retain,
    )
    monkeypatch.setattr(
        scraper,
        "_catalog_acquisition_path_ids_for_source",
        lambda _url: ["mi-legislature-mcl"],
    )
    monkeypatch.setattr(
        scraper,
        "_state_law_frontier_source_software_version",
        lambda: "mi-test@sha256:" + ("a" * 64),
    )
    monkeypatch.setattr(scraper, "fetch_official", _forbid_legacy_catalog)

    projection = _canonical_projection(scraper, rows)
    retained_path = await scraper.produce_state_law_frontier_closure(
        canonical_output_projection=projection,
    )

    assert retained_path == tmp_path / "mi-closure.json"
    assert [request[0] for request in ledger.requests] == [
        scraper.OFFICIAL_ENTRY_URL,
        *xml_by_url,
    ]
    assert len(ledger.requests) == 228
    assert all(request[1]["method"] == "GET" for request in ledger.requests)
    completion = captured["completion"]
    assert completion["disposition"] == {
        "discovered": 227,
        "fetched": 227,
        "excluded": 0,
        "quarantined": 0,
        "failed_final": 0,
        "duplicates": 0,
    }
    assert completion["rights"]["basis"] == "public_law_no_state_copyright"
    assert completion["replay"]["network_requests"] == 0
    assert completion["transport"]["grouped_warc_recovery"] is True
    assert completion["transport"]["per_page_archive_loop"] is False
    schema_ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "mi-schema-ledger",
        jurisdiction="MI",
        parser_name="MichiganChapterXmlParser",
    )
    schema_path = schema_ledger.retain_frontier_closure_projection(
        captured["completion"],
        **captured["kwargs"],
    )
    verified = schema_ledger.verify_retained_frontier_closure_projection(
        projection,
        closure_input_path=schema_path,
    )
    assert verified["canonical_row_count"] == 227
    mismatched_projection = dict(projection)
    mismatched_projection["canonical_keys"] = list(
        reversed(projection["canonical_keys"])
    )
    with pytest.raises(RuntimeError, match="final canonical identities"):
        await scraper.produce_state_law_frontier_closure(
            canonical_output_projection=mismatched_projection,
        )


@pytest.mark.anyio
async def test_new_york_full_frontier_batches_source_derived_law_pdfs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    catalog = (
        "<html><head><title>Consolidated Laws of New York</title></head><body>"
        "<a href='/legislation/laws/ALL'>ALL The Laws of New York</a>"
        "<a href='/legislation/laws/AAA'>AAA First Law</a>"
        "<a href='/legislation/laws/BBB'>BBB Second Law</a>"
        + (" " * 11_000)
        + "</body></html>"
    ).encode()
    pdf_by_url = {
        ny_pdf.full_law_pdf_url("AAA"): b"%PDF-AAA" + (b"a" * 1_100),
        ny_pdf.full_law_pdf_url("BBB"): b"%PDF-BBB" + (b"b" * 1_100),
    }
    calls = []

    async def _fake_plural(self, urls, *, residual_retry_attempts, **kwargs):
        requested = list(urls)
        calls.append((requested, residual_retry_attempts, dict(kwargs)))
        payloads = [
            catalog if url == self.OFFICIAL_CONSOLIDATED_URL else pdf_by_url[url]
            for url in requested
        ]
        assert all(kwargs["content_validator"](payload) for payload in payloads)
        return _aligned_result(requested, payloads)

    def _fake_extract(payload: bytes):
        if b"AAA" in payload[:20]:
            return (
                """
                ARTICLE 1
                RELEASE-DATED TEST
                Section 1.01. Current version.
                  * § 1.01. Current version. This New York law supplies enough
                  official statutory body text for exact source reconciliation.
                  * NB Effective until January 1, 2027
                  * § 1.01. Future version. This future official body is retained
                  as lifecycle evidence but is not operative on the release date.
                  * NB Effective January 1, 2027
                """,
                1,
            )
        return (
            (
                "§ 2-a Complete provision. This New York law supplies enough "
                "official statutory body text for exact source reconciliation."
            ),
            1,
        )

    async def _forbid_single(*_args, **_kwargs):
        raise AssertionError("strict New York must not use a per-page archive loop")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(NewYorkScraper, "STRICT_MINIMUM_CONSOLIDATED_LAWS", 2)
    monkeypatch.setattr(
        NewYorkScraper,
        "STRICT_CURRENT_CONSOLIDATED_CODE_SHA256",
        _ordered_code_sha256("AAA", "BBB"),
    )
    monkeypatch.setattr(
        NewYorkScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _fake_plural,
    )
    monkeypatch.setattr(
        NewYorkScraper,
        "_fetch_page_content_with_archival_fallback",
        _forbid_single,
    )
    monkeypatch.setattr(ny_pdf, "extract_new_york_law_pdf_text", _fake_extract)

    scraper = NewYorkScraper("NY", "New York")
    assert scraper._supports_shared_official_frontier_bridge() is False
    rows = await scraper.scrape_code(
        "New York Consolidated Laws",
        NewYorkScraper.OFFICIAL_ENTRY_URL,
        max_statutes=None,
    )

    assert [row.title_number for row in rows] == ["AAA", "BBB"]
    assert [len(call[0]) for call in calls] == [1, 2]
    assert all(call[2]["prefer_direct"] is True for call in calls)
    assert all(call[2]["wayback_prefix_inventory"] is True for call in calls)
    assert scraper._last_new_york_strict_closure["closed"] is True
    assert scraper._last_new_york_strict_closure["catalog_laws"] == 2
    assert scraper._last_new_york_strict_closure["raw_section_markers"] == 3
    assert scraper._last_new_york_strict_closure["source_sections"] == 2
    assert scraper._last_new_york_strict_closure[
        "lifecycle_alternate_sections"
    ] == 1
    assert scraper._last_new_york_strict_closure[
        "source_sections_without_raw_markers"
    ] == 0
    assert scraper._last_new_york_strict_closure["frontier"][
        "lifecycle_alternate_section_count"
    ] == 1

    retained_payloads = {scraper.OFFICIAL_CONSOLIDATED_URL: catalog, **pdf_by_url}
    ledger = _RetainedInputLedger(retained_payloads)
    scraper._state_law_acquisition_ledger = ledger
    captured = {}

    def _retain(completion_receipt, **kwargs):
        captured["completion"] = dict(completion_receipt)
        captured["kwargs"] = dict(kwargs)
        return tmp_path / "ny-closure.json"

    def _forbid_legacy_catalog(*_args, **_kwargs):
        raise AssertionError("New York certification must not use fetch_official")

    monkeypatch.setattr(
        scraper,
        "retain_state_law_frontier_closure_projection",
        _retain,
    )
    monkeypatch.setattr(
        scraper,
        "_catalog_acquisition_path_ids_for_source",
        lambda _url: ["ny-senate-laws"],
    )
    monkeypatch.setattr(
        scraper,
        "_state_law_frontier_source_software_version",
        lambda: "ny-test@sha256:" + ("b" * 64),
    )
    monkeypatch.setattr(scraper, "fetch_official", _forbid_legacy_catalog)

    projection = _canonical_projection(scraper, rows)
    retained_path = await scraper.produce_state_law_frontier_closure(
        canonical_output_projection=projection,
    )

    assert retained_path == tmp_path / "ny-closure.json"
    assert [request[0] for request in ledger.requests] == [
        scraper.OFFICIAL_CONSOLIDATED_URL,
        *pdf_by_url,
    ]
    assert all(request[1]["method"] == "GET" for request in ledger.requests)
    completion = captured["completion"]
    assert completion["disposition"] == {
        "discovered": 2,
        "fetched": 2,
        "excluded": 0,
        "quarantined": 0,
        "failed_final": 0,
        "duplicates": 0,
    }
    assert completion["rights"]["basis"] == "public_law_no_state_copyright"
    assert completion["replay"]["network_requests"] == 0
    assert completion["transport"]["grouped_warc_recovery"] is True
    assert completion["transport"]["per_page_archive_loop"] is False
    assert completion["frontier"]["schema_version"] == (
        "new-york-consolidated-source-frontier-v3"
    )
    assert completion["frontier"]["raw_section_marker_count"] == 3
    assert completion["frontier"]["source_section_count"] == 2
    assert completion["frontier"]["lifecycle_alternate_section_count"] == 1
    assert completion["frontier"][
        "source_sections_without_raw_marker_count"
    ] == 0
    assert captured["kwargs"]["replayed_frontier"][
        "lifecycle_alternate_section_count"
    ] == 1
    assert captured["kwargs"]["replayed_frontier"][
        "source_sections_without_raw_marker_count"
    ] == 0
    schema_ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "ny-schema-ledger",
        jurisdiction="NY",
        parser_name="NewYorkLawPdfParser",
    )
    schema_path = schema_ledger.retain_frontier_closure_projection(
        captured["completion"],
        **captured["kwargs"],
    )
    verified = schema_ledger.verify_retained_frontier_closure_projection(
        projection,
        closure_input_path=schema_path,
    )
    assert verified["canonical_row_count"] == 2


@pytest.mark.anyio
async def test_new_york_strict_frontier_fails_closed_on_pdf_residual(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = (
        "<html><body>Consolidated Laws of New York"
        "<a href='/legislation/laws/AAA'>AAA First Law</a>"
        + (" " * 11_000)
        + "</body></html>"
    ).encode()

    async def _fake_plural(self, urls, *, residual_retry_attempts, **kwargs):
        requested = list(urls)
        if requested == [self.OFFICIAL_CONSOLIDATED_URL]:
            return _aligned_result(requested, [catalog])
        return _aligned_result(requested, [b""], errors=["archive residual"])

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(NewYorkScraper, "STRICT_MINIMUM_CONSOLIDATED_LAWS", 1)
    monkeypatch.setattr(
        NewYorkScraper,
        "STRICT_CURRENT_CONSOLIDATED_CODE_SHA256",
        _ordered_code_sha256("AAA"),
    )
    monkeypatch.setattr(
        NewYorkScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _fake_plural,
    )
    scraper = NewYorkScraper("NY", "New York")

    with pytest.raises(RuntimeError, match="unresolved exact URLs"):
        await scraper.scrape_code(
            "New York Consolidated Laws",
            NewYorkScraper.OFFICIAL_ENTRY_URL,
            max_statutes=None,
        )


@pytest.mark.anyio
async def test_new_york_exact_supplemental_wave_is_plural_and_stays_unresolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = (
        "<html><body>Consolidated Laws of New York"
        "<a href='/legislation/laws/AAA'>AAA First Law</a>"
        "<a href='/legislation/laws/BBB'>BBB Second Law</a>"
        + (" " * 11_000)
        + "</body></html>"
    ).encode()
    pdf_by_url = {
        ny_pdf.full_law_pdf_url("AAA"): b"%PDF-AAA" + (b"a" * 1_100),
        ny_pdf.full_law_pdf_url("BBB"): b"%PDF-BBB" + (b"b" * 1_100),
    }
    supplemental_urls = (
        "https://www.nysenate.gov/legislation/laws/AAA/1",
        "https://www.nysenate.gov/legislation/laws/BBB/2",
    )
    section_html = {
        url: (
            b"<html><body>New York State Senate /legislation/laws/ "
            + (url.encode() + b" ") * 40
            + b"</body></html>"
        )
        for url in supplemental_urls
    }
    calls = []

    async def _fake_plural(self, urls, *, residual_retry_attempts, **kwargs):
        requested = list(urls)
        calls.append((requested, residual_retry_attempts, dict(kwargs)))
        payloads = []
        for url in requested:
            if url == self.OFFICIAL_CONSOLIDATED_URL:
                payloads.append(catalog)
            elif url in pdf_by_url:
                payloads.append(pdf_by_url[url])
            else:
                payloads.append(section_html[url])
        assert all(kwargs["content_validator"](body) for body in payloads)
        return _aligned_result(requested, payloads)

    parse_registry_manifests = []
    resolution_attempts = []

    def _fake_parse(
        _payload,
        *,
        law_code,
        law_name,
        supplemental_proof_registry,
        **_kwargs,
    ):
        row = (
            {
                "section_number": "1",
                "toc_variant": "",
                "reason": "ambiguous_lifecycle_status",
                "detail": "missing_lifecycle_note:",
            }
            if law_code == "AAA"
            else {
                "section_number": "2",
                "toc_variant": "*2",
                "reason": "toc_section_missing_body_identity",
                "detail": "toc_offset=1",
            }
        )
        parse_registry_manifests.append(supplemental_proof_registry.manifest())
        resolution_attempts.append(
            supplemental_proof_registry.resolve_residual(
                law_code=law_code,
                residual=row,
            )
        )
        return SimpleNamespace(
            closed=False,
            law_code=law_code,
            law_name=law_name,
            source_section_count=1,
            statutes=[],
            terminal_sections=[],
            unclassified_sections=[row],
        )

    async def _forbid_single(*_args, **_kwargs):
        raise AssertionError("strict New York must not use a per-page archive loop")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(NewYorkScraper, "STRICT_MINIMUM_CONSOLIDATED_LAWS", 2)
    monkeypatch.setattr(
        NewYorkScraper,
        "STRICT_CURRENT_CONSOLIDATED_CODE_SHA256",
        _ordered_code_sha256("AAA", "BBB"),
    )
    monkeypatch.setattr(
        NewYorkScraper,
        "STRICT_CURRENT_SUPPLEMENTAL_RESIDUAL_ROWS",
        (
            ("AAA", "1", "", "missing_lifecycle_note"),
            ("BBB", "2", "*2", "toc_section_missing_body_identity"),
        ),
    )
    monkeypatch.setattr(
        NewYorkScraper,
        "STRICT_CURRENT_SUPPLEMENTAL_SECTION_URLS",
        supplemental_urls,
    )
    monkeypatch.setattr(
        NewYorkScraper,
        "STRICT_CURRENT_SUPPLEMENTAL_URL_SHA256",
        hashlib.sha256("\n".join(supplemental_urls).encode()).hexdigest(),
    )
    monkeypatch.setattr(
        NewYorkScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _fake_plural,
    )
    monkeypatch.setattr(
        NewYorkScraper,
        "_fetch_page_content_with_archival_fallback",
        _forbid_single,
    )
    monkeypatch.setattr(ny_pdf, "parse_new_york_law_pdf", _fake_parse)
    scraper = NewYorkScraper("NY", "New York")

    with pytest.raises(RuntimeError, match="law=AAA"):
        await scraper.scrape_code(
            "New York Consolidated Laws",
            NewYorkScraper.OFFICIAL_ENTRY_URL,
            max_statutes=None,
        )

    assert [call[0] for call in calls] == [
        [scraper.OFFICIAL_CONSOLIDATED_URL],
        list(pdf_by_url),
        list(supplemental_urls),
    ]
    assert calls[-1][2]["common_crawl_domain_terms"] == (
        scraper.OFFICIAL_DOMAIN,
    )
    assert calls[-1][2]["common_crawl_url_terms"] == (
        "/legislation/laws/",
    )
    assert calls[-1][2]["wayback_prefix_inventory"] is True
    assert parse_registry_manifests[:2] == [[], []]
    assert all(len(manifest) == 2 for manifest in parse_registry_manifests[2:])
    assert [row["proof_present"] for row in resolution_attempts] == [
        False,
        False,
        True,
        True,
    ]
    assert all(row["status"] == "unknown" for row in resolution_attempts)
    assert all(row["decision_action"] is None for row in resolution_attempts)


@pytest.mark.anyio
async def test_new_york_frontier_rejects_repeated_exact_host_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = ny_pdf.full_law_pdf_url("AAA")
    payload = b"%PDF-AAA" + (b"a" * 1_100)

    async def _fake_plural(self, urls, **_kwargs):
        result = _aligned_result(list(urls), [payload])
        result.stats["common_crawl_inventory_memo"] = {
            "shared_domain_queries": 2
        }
        return result

    monkeypatch.setattr(
        NewYorkScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _fake_plural,
    )
    scraper = NewYorkScraper("NY", "New York")

    with pytest.raises(RuntimeError, match="repeated a Common Crawl domain"):
        await scraper._fetch_new_york_frontier_batch(
            [url],
            frontier_name="one-exact-host",
            content_validator=scraper._is_valid_new_york_law_pdf,
            media_type="application/pdf",
            common_crawl_domains=(scraper.OFFICIAL_PDF_DOMAIN,),
            common_crawl_url_terms=("/pdf/laws/",),
        )


def test_new_york_supplemental_wave_rejects_partial_residual_drift() -> None:
    report = SimpleNamespace(
        law_code="EPT",
        unclassified_sections=[
            {
                "section_number": "3-6.5",
                "toc_variant": "",
                "reason": "ambiguous_lifecycle_status",
                "detail": "missing_lifecycle_note:",
            }
        ],
    )

    with pytest.raises(RuntimeError, match="membership drifted"):
        NewYorkScraper._new_york_exact_supplemental_urls([report])
