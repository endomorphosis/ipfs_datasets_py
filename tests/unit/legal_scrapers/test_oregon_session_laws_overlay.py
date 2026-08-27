from __future__ import annotations

import hashlib
from dataclasses import replace
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, urlparse

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
    oregon_session_laws as session_laws,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oregon import (
    OregonScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oregon_session_laws import (
    LAWS_MOBILE_URL,
    OregonAffectedReference,
    OregonEnactedBill,
    OregonLawChapterLocator,
    OregonLawDocumentMetadata,
    OregonLawSection,
    ParsedOregonLaw,
    normalized_oregon_law_sections,
    oregon_current_law_sessions,
    oregon_law_chapter_locators,
    oregon_resolution_inventory_url,
    oregon_resolution_locators,
    oregon_supplement_inventory_url,
    oregon_supplement_locators,
    parse_oregon_affected_text,
    parse_oregon_enacted_text,
    parse_oregon_law_text,
    pdftotext_raw,
    reconcile_oregon_session_evidence,
)


def _landing_html(*, special_count: int = 2, regular_count: int = 142) -> str:
    return f"""
    <html><body>
      <tbody groupString="{quote(";#2026 Regular;#", safe="")}">
        <tr><td>Session : 2026 Regular ({regular_count})</td></tr>
      </tbody>
      <tbody groupString="{quote(";#2025 Special 1;#", safe="")}">
        <tr><td>Session : 2025 Special 1 ({special_count})</td></tr>
      </tbody>
      <tbody groupString="{quote(";#2025 Regular;#", safe="")}">
        <tr><td>Session : 2025 Regular (999)</td></tr>
      </tbody>
    </body></html>
    """


def _group_html(prefix: str, count: int, *, omit: int | None = None) -> str:
    links = []
    for chapter in range(1, count + 1):
        if chapter == omit:
            continue
        links.append(
            "<a href='http://www.oregonlegislature.gov/bills_laws/"
            f"lawsstatutes/{prefix}{chapter:04d}.pdf'>"
            f"Chapter {chapter:04d}</a>"
        )
    return "<html><body>" + "".join(links) + "</body></html>"


def _supplement_html(session_key: str) -> str:
    rows = {
        "2025_special_1": (
            ("2025S1Foreword.pdf", "Oregon Laws Foreword"),
            ("2025S1OrLawEnacted.pdf", "Senate and House Bills Enacted"),
            ("2025S1OrLawAR.pdf", "Statutes Affected by Measures"),
        ),
        "2026_regular": (
            ("2026OrLawAuthorizing.pdf", "Law Authorizing this Publication"),
            ("2026OrLawForeword.pdf", "Oregon Laws Foreword"),
            ("2026OrLawIndex.pdf", "Oregon Laws Index"),
            ("2026OrLawEnacted.pdf", "Senate and House Bills Enacted"),
            ("2026OrLawAR.pdf", "Statutes Affected by Measures"),
        ),
    }[session_key]
    return (
        "<html><body>"
        + "".join(
            "<a href='http://www.oregonlegislature.gov/bills_laws/lawsstatutes/"
            f"{filename}'>{label}</a>"
            for filename, label in rows
        )
        + "</body></html>"
    )


def _resolution_html(session_key: str) -> str:
    rows = {
        "2025_special_1": (("2025S1hcr0051.pdf", "House Concurrent Resolution 0051"),),
        "2026_regular": (
            ("2026hcr0201.pdf", "House Concurrent Resolution 0201"),
            ("2026hcr0202.pdf", "House Concurrent Resolution 0202"),
            ("2026scr0201.pdf", "Senate Concurrent Resolution 0201"),
            ("2026scr0203.pdf", "Senate Concurrent Resolution 0203"),
            ("2026scr0204.pdf", "Senate Concurrent Resolution 0204"),
            ("2026scr0205.pdf", "Senate Concurrent Resolution 0205"),
            ("2026scr0206.pdf", "Senate Concurrent Resolution 0206"),
            ("2026scr0207.pdf", "Senate Concurrent Resolution 0207"),
            ("2026scr0209.pdf", "Senate Concurrent Resolution 0209"),
        ),
    }[session_key]
    return (
        "<html><body>"
        + "".join(
            f"<a href='/bills_laws/lawsstatutes/{filename}'>{label}</a>"
            for filename, label in rows
        )
        + "</body></html>"
    )


def _fake_complete_pdf(seed: int = 0) -> bytes:
    return b"%PDF-1.7\n" + bytes([65 + seed % 20]) * 1100 + b"\nstartxref\n12\n%%EOF\n"


def _aligned_result(
    urls: list[str],
    payload_by_url: dict[str, bytes],
) -> StateLawPageMultiFetchResult:
    payloads = [payload_by_url.get(url, b"") for url in urls]
    return StateLawPageMultiFetchResult(
        urls=list(urls),
        payloads=payloads,
        errors=[None if payload else "missing synthetic page" for payload in payloads],
        transport_receipts=[
            {
                "official_url": url,
                "content_sha256": hashlib.sha256(payload).hexdigest(),
                "source_transport": "synthetic-test",
            }
            if payload
            else None
            for url, payload in zip(urls, payloads, strict=True)
        ],
        parser_input_envelopes=[
            SimpleNamespace(body=payload) if payload else None for payload in payloads
        ],
        stats={"requested_pages": len(urls)},
    )


def test_current_session_groups_are_exact_and_stably_encoded() -> None:
    sessions = oregon_current_law_sessions(_landing_html())

    assert [row.key for row in sessions] == ["2025_special_1", "2026_regular"]
    assert [row.declared_chapter_count for row in sessions] == [2, 142]
    for session in sessions:
        parsed = urlparse(session.inventory_url)
        query = parse_qs(parsed.query)
        assert query["GroupString"] == [session.group_string]
        assert query["DrillDown"] == ["1"]
        assert "%253B" not in session.inventory_url

    with pytest.raises(ValueError, match="count changed"):
        oregon_current_law_sessions(_landing_html(regular_count=141))
    with pytest.raises(ValueError, match="missing or duplicated"):
        oregon_current_law_sessions(
            _landing_html() + _landing_html().split("<tbody", 1)[1]
        )


def test_chapter_inventory_canonicalizes_scheme_and_fails_on_gap() -> None:
    session = oregon_current_law_sessions(_landing_html())[0]
    rows = oregon_law_chapter_locators(
        _group_html("2025S1OrLaw", 2),
        session,
    )

    assert [row.chapter_number for row in rows] == [1, 2]
    assert rows[0].declared_url.startswith("http://")
    assert rows[0].canonical_url == (
        "https://www.oregonlegislature.gov/bills_laws/lawsstatutes/2025S1OrLaw0001.pdf"
    )

    with pytest.raises(ValueError, match="not exact and consecutive"):
        oregon_law_chapter_locators(
            _group_html("2025S1OrLaw", 2, omit=1),
            session,
        )


def test_supplement_and_resolution_inventories_close_exact_official_sets() -> None:
    sessions = oregon_current_law_sessions(_landing_html())
    supplements = [
        row
        for session in sessions
        for row in oregon_supplement_locators(
            _supplement_html(session.key),
            session,
        )
    ]
    resolutions = [
        row
        for session in sessions
        for row in oregon_resolution_locators(
            _resolution_html(session.key),
            session,
        )
    ]

    assert len(supplements) == 8
    assert sum(row.document_kind == "enacted_table" for row in supplements) == 2
    assert sum(row.document_kind == "affected_table" for row in supplements) == 2
    assert len(resolutions) == 10
    assert all(
        row.document_kind == "resolution_excluded_nonstatutory" for row in resolutions
    )
    assert all(row.canonical_url.startswith("https://") for row in resolutions)

    with pytest.raises(ValueError, match="inventory changed"):
        oregon_resolution_locators("<html></html>", sessions[0])


def test_enacted_table_covers_consecutive_chapters_and_retains_veto() -> None:
    enacted_lines = [
        f"{4000 + chapter}........{chapter}........01/01/27"
        for chapter in range(1, 143)
    ]
    text = "\n".join(
        (
            "OREGON LAWS 2026 REGULAR SESSION RS26-A-1",
            "SENATE AND HOUSE BILLS ENACTED",
            "HOUSE BILLS",
            *enacted_lines,
            "4177................... ..........Vetoed",
        )
    )

    rows = parse_oregon_enacted_text(text, session_key="2026_regular")

    assert len(rows) == 143
    assert [row.chapter_number for row in rows if row.disposition == "enacted"] == list(
        range(1, 143)
    )
    assert [row.bill_number for row in rows if row.disposition == "vetoed"] == [
        "HB 4177"
    ]


def test_affected_table_inherits_range_and_continuation_targets() -> None:
    ors_rows = [
        "319.510 to)",
        "319.880 ) Add c.1 §70 (HB 3991)",
        "Add c.1 §38 (HB 3991)",
        "319.883 A c.1 §30 (HB 3991)",
        "A c.1 §32 (HB 3991)",
    ]
    # Complete the source-observed 56 A / 4 R / 5 Add exact table algebra.
    ors_rows.extend(
        f"{100 + index}.001 A c.1 §{100 + index} (HB 3991)" for index in range(54)
    )
    ors_rows.extend(
        f"{200 + index}.001 R c.1 §{200 + index} (HB 3991)" for index in range(4)
    )
    ors_rows.extend(
        f"Ch. {300 + index} Add c.1 §{300 + index} (HB 3991)" for index in range(3)
    )
    text = "\n".join(
        (
            "OREGON LAWS 2025 SPECIAL SESSION SS25-T-1",
            "ORS SECTIONS AMENDED, REPEALED OR “ADDED TO”",
            *ors_rows,
            "OREGON RULES OF CIVIL PROCEDURE (ORCP) AMENDED,",
            "There were no amendments, repeals or additions.",
            "SECTIONS IN UNCODIFIED LAW AMENDED,",
            "2019 c. 428 §2 R c.1 §29 (HB 3991)",
            "2019 c. 491 §6 A c.1 §52 (HB 3991)",
            "CONSTITUTIONAL PROVISIONS - AMENDMENTS,",
            "There were no amendments, repeals or additions.",
        )
    )

    rows = parse_oregon_affected_text(text, session_key="2025_special_1")

    assert len(rows) == 67
    assert rows[0].target == "319.510 to 319.880"
    assert rows[1].target == "319.510 to 319.880"
    assert rows[3].target == "319.883"


def test_law_text_parser_splits_every_section_and_captures_semantics() -> None:
    locator = OregonLawChapterLocator(
        session_key="2026_regular",
        session_label="2026 Regular",
        year=2026,
        chapter_number=7,
        chapter_label="Chapter 0007",
        declared_url=(
            "http://www.oregonlegislature.gov/bills_laws/lawsstatutes/2026orlaw0007.pdf"
        ),
        canonical_url=(
            "https://www.oregonlegislature.gov/bills_laws/lawsstatutes/"
            "2026orlaw0007.pdf"
        ),
    )
    text = """
OREGON LAWS 2026 Chap. 7
CHAPTER 7
AN ACT HB 4100
SECTION 1. ORS 123.456 is amended to read:
The complete first section remains present, including this final sentence.
Oregon Laws 2025; this body citation is not a stale page header.
SECTION 1a. If HB 4999 becomes law, this section becomes operative on July 1, 2027.
The conditional section ends with text that must not be truncated.
SECTION 2. ORS 234.567 and 234.568 are repealed.
This section is repealed on January 2, 2030.
SECTION 3. This Act being necessary for the immediate
preservation of the public peace, health and safety, an emergency, is declared
to exist, and takes effect on its passage.
Approved by the Governor March 3, 2026
Filed in the office of Secretary of State March 4, 2026
Effective date March 3, 2026
"""

    parsed = parse_oregon_law_text(text, locator=locator)

    assert parsed.metadata.bill_number == "HB 4100"
    assert parsed.metadata.approved_date == "2026-03-03"
    assert parsed.metadata.filed_date == "2026-03-04"
    assert parsed.metadata.effective_date == "2026-03-03"
    assert [section.number for section in parsed.sections] == ["1", "1A", "2", "3"]
    assert parsed.sections[0].amended_ors_citations == ("ORS 123.456",)
    assert parsed.sections[1].conditional_semantics
    assert parsed.sections[1].operative_semantics[0]["dates"] == ["July 1, 2027"]
    assert parsed.sections[2].repealed_ors_citations == (
        "ORS 234.567",
        "ORS 234.568",
    )
    assert parsed.sections[2].sunset_semantics[0]["dates"] == ["January 2, 2030"]
    assert parsed.sections[3].emergency_clause is True
    assert "must not be truncated" in parsed.sections[1].text
    assert "Approved by" not in parsed.sections[-1].text

    with pytest.raises(ValueError, match="unsupported Oregon Laws session"):
        parse_oregon_law_text(
            text,
            locator=replace(locator, session_key="2026_special_1"),
        )

    rows = normalized_oregon_law_sections(parsed)
    assert len(rows) == 4
    assert rows[0].source_url.endswith("2026orlaw0007.pdf#section-1")
    assert (
        rows[0]
        .structured_data["official_locator"]["declared_url"]
        .startswith("http://")
    )
    assert rows[0].metadata.effective_date == "2026-03-03"


def test_pdftotext_raw_uses_exact_retained_bytes_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _fake_complete_pdf()
    calls: list[tuple[tuple[str, ...], bytes]] = []

    def _run(command: tuple[str, ...], **kwargs: object) -> SimpleNamespace:
        calls.append((command, bytes(kwargs["input"])))
        return SimpleNamespace(returncode=0, stdout=b"converted\n", stderr=b"")

    monkeypatch.setattr(session_laws.subprocess, "run", _run)
    assert pdftotext_raw(payload) == "converted\n"
    assert calls == [(("pdftotext", "-raw", "-", "-"), payload)]

    def _failure(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=1, stdout=b"", stderr=b"damaged")

    monkeypatch.setattr(session_laws.subprocess, "run", _failure)
    with pytest.raises(RuntimeError, match="rejected"):
        pdftotext_raw(payload)


def test_reconciliation_binds_official_insurance_code_range_alias() -> None:
    locator = OregonLawChapterLocator(
        session_key="2026_regular",
        session_label="2026 Regular",
        year=2026,
        chapter_number=109,
        chapter_label="Chapter 0109",
        declared_url="http://www.oregonlegislature.gov/law0109.pdf",
        canonical_url="https://www.oregonlegislature.gov/law0109.pdf",
    )
    law = ParsedOregonLaw(
        locator=locator,
        metadata=OregonLawDocumentMetadata(
            bill_number="HB 4040",
            approved_event="",
            approved_date="",
            filed_date="",
            effective_date="",
        ),
        sections=(
            OregonLawSection(
                number="14",
                text=(
                    "SECTION 14. Section 15 of this 2026 Act is added to and "
                    "made a part of the Insurance\nCode."
                ),
                amended_ors_citations=(),
                repealed_ors_citations=(),
                added_to_ors_chapters=(),
                operative_semantics=(),
                effective_semantics=(),
                sunset_semantics=(),
                conditional_semantics=(),
                emergency_clause=False,
            ),
        ),
    )
    enacted = OregonEnactedBill(
        session_key="2026_regular",
        bill_number="HB 4040",
        disposition="enacted",
        chapter_number=109,
        effective_date="",
        notes=(),
    )
    affected = OregonAffectedReference(
        session_key="2026_regular",
        table_kind="ors",
        target="Ch. 731 to Ch. 750",
        action="Add",
        law_chapter_number=109,
        law_section_number="14",
        bill_number="HB 4040",
        emergency_marker="E",
        raw_text="Ch. 731 to Ch. 750 Add c.109 §14 (HB 4040) E",
    )

    reconciled = reconcile_oregon_session_evidence([law], [enacted], [affected])

    assert reconciled.actions_by_section[("2026_regular", 109, "14")] == (
        affected,
    )


def test_action_extraction_ignores_cross_references_to_another_section() -> None:
    assert session_laws._ors_action_citations(
        "If SB 1507 becomes law, ORS 305.494 is repealed by section 7 of this Act.",
        "repealed",
    ) == ()
    assert session_laws._ors_action_citations(
        "ORS 305.494 is repealed.",
        "repealed",
    ) == ("ORS 305.494",)


@pytest.mark.anyio
async def test_strict_overlay_uses_one_group_and_one_144_pdf_plural_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = oregon_current_law_sessions(_landing_html())
    group_pages = {
        sessions[0].inventory_url: _group_html("2025S1OrLaw", 2).encode(),
        sessions[1].inventory_url: _group_html("2026orlaw", 142).encode(),
    }
    locators = [
        locator
        for session in sessions
        for locator in oregon_law_chapter_locators(
            group_pages[session.inventory_url].decode(),
            session,
        )
    ]
    pdf_pages = {
        locator.canonical_url: _fake_complete_pdf(index)
        for index, locator in enumerate(locators)
    }
    supplement_group_pages = {
        oregon_supplement_inventory_url(session): _supplement_html(session.key).encode()
        for session in sessions
    }
    resolution_group_pages = {
        oregon_resolution_inventory_url(session): _resolution_html(session.key).encode()
        for session in sessions
    }
    table_locators = [
        row
        for session in sessions
        for row in oregon_supplement_locators(
            _supplement_html(session.key),
            session,
        )
        if row.document_kind in {"enacted_table", "affected_table"}
    ]
    table_pages = {
        locator.canonical_url: _fake_complete_pdf(index + 144)
        for index, locator in enumerate(table_locators)
    }
    payloads = {
        LAWS_MOBILE_URL: _landing_html().encode(),
        **group_pages,
        **pdf_pages,
        **supplement_group_pages,
        **resolution_group_pages,
        **table_pages,
    }
    plural_calls: list[tuple[list[str], dict[str, object]]] = []

    async def _plural(
        urls: list[str],
        **kwargs: object,
    ) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        plural_calls.append((requested, dict(kwargs)))
        return _aligned_result(requested, payloads)

    def _parse(_payload: bytes, *, locator: OregonLawChapterLocator) -> ParsedOregonLaw:
        return ParsedOregonLaw(
            locator=locator,
            metadata=OregonLawDocumentMetadata(
                bill_number=f"HB {4000 + locator.chapter_number}",
                approved_event="Approved by the Governor March 1, 2026",
                approved_date="2026-03-01",
                filed_date="2026-03-02",
                effective_date="2026-03-01",
            ),
            sections=(
                OregonLawSection(
                    number="1",
                    text="SECTION 1. Complete synthetic official section text.",
                    amended_ors_citations=(),
                    repealed_ors_citations=(),
                    added_to_ors_chapters=(),
                    operative_semantics=(),
                    effective_semantics=(),
                    sunset_semantics=(),
                    conditional_semantics=(),
                    emergency_clause=False,
                ),
            ),
        )

    def _parse_enacted(
        _payload: bytes,
        *,
        session_key: str,
    ) -> tuple[OregonEnactedBill, ...]:
        count = 2 if session_key == "2025_special_1" else 142
        return tuple(
            OregonEnactedBill(
                session_key=session_key,
                bill_number=f"HB {4000 + chapter}",
                disposition="enacted",
                chapter_number=chapter,
                effective_date="2026-03-01",
                notes=(),
            )
            for chapter in range(1, count + 1)
        )

    def _parse_affected(
        _payload: bytes,
        *,
        session_key: str,
    ) -> tuple[OregonAffectedReference, ...]:
        del session_key
        return ()

    scraper = OregonScraper("OR", "Oregon")
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    monkeypatch.setattr(session_laws, "parse_oregon_law_pdf", _parse)
    monkeypatch.setattr(session_laws, "parse_oregon_enacted_pdf", _parse_enacted)
    monkeypatch.setattr(session_laws, "parse_oregon_affected_pdf", _parse_affected)

    rows = await scraper._scrape_strict_oregon_session_laws(legal_area="general")

    assert len(plural_calls) == 5
    assert plural_calls[0][0] == [LAWS_MOBILE_URL]
    assert plural_calls[1][0] == [session.inventory_url for session in sessions]
    assert plural_calls[2][0] == [locator.canonical_url for locator in locators]
    assert len(plural_calls[2][0]) == 144
    assert plural_calls[2][1]["media_type"] == "application/pdf"
    assert plural_calls[2][1]["common_crawl_mime_terms"] == ("pdf",)
    assert plural_calls[3][0] == [
        *[oregon_supplement_inventory_url(session) for session in sessions],
        *[oregon_resolution_inventory_url(session) for session in sessions],
    ]
    assert plural_calls[4][0] == [locator.canonical_url for locator in table_locators]
    assert len(plural_calls[4][0]) == 4
    assert len(rows) == 144
    assert len({row.statute_id for row in rows}) == 144
    assert all(row.source_url.startswith("https://") for row in rows)
    assert all(
        row.structured_data["official_locator"]["declared_url"].startswith("http://")
        for row in rows
    )
    assert scraper._last_oregon_session_law_closure["closed"] is True
    assert scraper._last_oregon_session_law_closure["chapter_pdf_count"] == 144
    assert scraper._last_oregon_session_law_closure["parity_pdf_count"] == 4
    assert scraper._last_oregon_session_law_closure["resolution_document_count"] == 10
    exclusions = scraper._last_oregon_session_law_closure["resolution_exclusions"]
    assert len(exclusions) == 10
    assert {row["identity"] for row in exclusions} == {
        "House Concurrent Resolution 0051",
        "House Concurrent Resolution 0201",
        "House Concurrent Resolution 0202",
        "Senate Concurrent Resolution 0201",
        "Senate Concurrent Resolution 0203",
        "Senate Concurrent Resolution 0204",
        "Senate Concurrent Resolution 0205",
        "Senate Concurrent Resolution 0206",
        "Senate Concurrent Resolution 0207",
        "Senate Concurrent Resolution 0209",
    }
    assert scraper._last_oregon_session_law_closure["source_document_disposition"] == {
        "discovered": 154,
        "fetched": 144,
        "excluded": 10,
        "failed_final": 0,
        "duplicates": 0,
        "quarantined": 0,
    }
    assert all(row.structured_data["currentness_parity"]["closed"] for row in rows)
