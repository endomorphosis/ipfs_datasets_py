from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, urlparse

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    build_canonical_state_law_output_projection,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
    oregon as oregon_module,
    oregon_session_laws,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    NormalizedStatute,
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oregon import (
    OregonScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oregon_chapter import (
    decode_oregon_html,
    ors_sharepoint_title_groups,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oregon_session_laws import (
    LAWS_MOBILE_URL,
    OregonAffectedReference,
    OregonEnactedBill,
    OregonLawChapterLocator,
    OregonLawDocumentMetadata,
    OregonLawSection,
    ParsedOregonLaw,
    oregon_current_law_sessions,
    oregon_law_chapter_locators,
    oregon_resolution_inventory_url,
    oregon_supplement_inventory_url,
    oregon_supplement_locators,
)


def _title_group_row(*, volume: int, title: int, chapter_count: int) -> str:
    raw_group = f"Volume=Volume {volume};#Title=Title {title} — Synthetic"
    encoded_group = quote(raw_group, safe="")
    return (
        f'<tbody id="titl99-{volume}_{title}_" '
        f'groupString="{encoded_group}">'
        f"<tr><td>Title {title}: Synthetic title ({chapter_count})</td></tr>"
        "</tbody>"
    )


def _strict_seed_html() -> str:
    # A source-derived count of 20 deliberately differs from both the number
    # of title groups (19) and the current live ORS chapter count (689).
    rows = [
        _title_group_row(
            volume=volume,
            title=volume,
            chapter_count=2 if volume == 1 else 1,
        )
        for volume in range(1, 20)
    ]
    return (
        "<html><body><h1>Oregon Revised Statutes (ORS) - 2025 Edition</h1>"
        + "".join(rows)
        + "</body></html>"
    )


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


def test_strict_oregon_rows_bypass_generic_navigation_false_positive() -> None:
    scraper = OregonScraper("OR", "Oregon")
    scraper._last_oregon_strict_closure = {"closed": True}
    row = NormalizedStatute(
        state_code="OR",
        state_name="Oregon",
        statute_id="ORS 1.130",
        code_name="Oregon Revised Statutes",
        chapter_number="1",
        section_number="1.130",
        section_name="Power to adjourn proceedings.",
        full_text=(
            "A court or judicial officer has power to adjourn any proceedings "
            "before the court or the judicial officer, from time to time, as "
            "may be necessary, unless otherwise expressly provided by statute."
        ),
        source_url=(
            "https://www.oregonlegislature.gov/bills_laws/ors/"
            "ors001.html#section-1.130"
        ),
        official_cite="Or. Rev. Stat. § 1.130",
        structured_data={
            "chapter_url": (
                "https://www.oregonlegislature.gov/bills_laws/ors/ors001.html"
            ),
            "content_sha256": "1" * 64,
            "discovery_method": "official_ors_sharepoint_title_inventory",
            "parser_input_receipt_sha256": "2" * 64,
            "skip_hydrate": True,
            "source_kind": "official_oregon_revised_statutes_html",
        },
    )

    assert scraper._looks_like_navigation_text(row.full_text)
    assert not scraper._is_low_quality_statute_record(row)

    row.structured_data.pop("parser_input_receipt_sha256")
    assert scraper._is_low_quality_statute_record(row)


def _chapter_html(chapter: int) -> bytes:
    body = (
        f"This is the official operative text for chapter {chapter}. "
        "It contains enough substantive public-law language to be normalized "
        "and admitted to the exact Oregon statutory corpus."
    )
    return (
        "<html><head><meta charset='windows-1252'></head><body>"
        f"<p>Chapter {chapter} — Synthetic Chapter</p>"
        f"<p><span>{chapter}.001 TOC-only synopsis.</span></p>"
        f"<p><b><span>{chapter}.001 Operative section.</span></b> {body}</p>"
        "<p>This continuation is part of the operative section body.</p>"
        "</body></html>"
    ).encode("windows-1252")


def _session_law_landing_html() -> str:
    return (
        "<html><body>"
        f'<tbody groupString="{quote(";#2026 Regular;#", safe="")}">'
        "<tr><td>Session : 2026 Regular (142)</td></tr></tbody>"
        f'<tbody groupString="{quote(";#2025 Special 1;#", safe="")}">'
        "<tr><td>Session : 2025 Special 1 (2)</td></tr></tbody>"
        "</body></html>"
    )


def _session_law_group_html(prefix: str, count: int) -> bytes:
    return (
        "<html><body>"
        + "".join(
            "<a href='http://www.oregonlegislature.gov/bills_laws/"
            f"lawsstatutes/{prefix}{chapter:04d}.pdf'>"
            f"Chapter {chapter:04d}</a>"
            for chapter in range(1, count + 1)
        )
        + "</body></html>"
    ).encode()


def _session_supplement_html(session_key: str) -> bytes:
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
            "<a href='http://www.oregonlegislature.gov/bills_laws/"
            f"lawsstatutes/{filename}'>{label}</a>"
            for filename, label in rows
        )
        + "</body></html>"
    ).encode()


def _session_resolution_html(session_key: str) -> bytes:
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
    ).encode()


def _complete_synthetic_pdf(index: int) -> bytes:
    return b"%PDF-1.7\n" + bytes([65 + index % 20]) * 1100 + b"\nstartxref\n12\n%%EOF\n"


def _parsed_synthetic_law(
    _payload: bytes,
    *,
    locator: OregonLawChapterLocator,
) -> ParsedOregonLaw:
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
                text="SECTION 1. Complete synthetic official session-law text.",
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


def _parsed_synthetic_enacted(
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


def _parsed_synthetic_affected(
    _payload: bytes,
    *,
    session_key: str,
) -> tuple[OregonAffectedReference, ...]:
    del session_key
    return ()


def test_sharepoint_title_group_url_is_stable_and_not_double_encoded() -> None:
    html = (
        "<html><body>"
        + _title_group_row(volume=1, title=1, chapter_count=9)
        + "</body></html>"
    )

    groups = ors_sharepoint_title_groups(html)

    assert len(groups) == 1
    group = groups[0]
    assert group.volume_index == 1
    assert group.title_index == 1
    assert group.declared_chapter_count == 9
    assert group.group_string == "Volume=Volume 1;#Title=Title 1 — Synthetic"
    parsed_url = urlparse(group.inventory_url)
    query = parse_qs(parsed_url.query)
    assert query["ViewCount"] == ["1"]
    assert query["DrillDown"] == ["1"]
    assert query["GroupString"] == [group.group_string]
    assert "%253D" not in group.inventory_url
    assert "%2520" not in group.inventory_url


def test_cp1252_dom_parser_excludes_toc_and_types_all_terminal_forms() -> None:
    payload = """
        <html><head><meta charset="windows-1252"></head><body>
        <p>2025 Edition</p>
        <p>Chapter 1 — General Provisions</p>
        <p><span>1.001 TOC-only synopsis with a smart “quote.”</span></p>
        <p><span>1.002 Repealed section shown only in the TOC.</span></p>
        <p><b><span>1.001 Definitions.</span></b>
        This operative provision uses a smart “quotation” and supplies
        substantive statutory text for normalization and indexing.</p>
        <p>The operative body continues here and must remain with section 1.001.</p>
        <p><b><span>1.002 Repealed by 2025 c. 1, § 2.</span></b></p>
        <p><b><span>1.003 Renumbered 1.004.</span></b></p>
        </body></html>
    """.encode("windows-1252")
    html = decode_oregon_html(payload)
    assert "“quotation”" in html

    scraper = OregonScraper("OR", "Oregon")
    rows = scraper._parse_chapter_html(
        html=html,
        chapter_url="https://www.oregonlegislature.gov/bills_laws/ors/ors001.html",
        code_name="Oregon Revised Statutes",
        citation_format="Or. Rev. Stat.",
        legal_area="general",
    )
    explicit_terminals = list(scraper._last_oregon_terminal_sections)
    explicit_unclassified = list(scraper._last_oregon_unclassified_sections)

    assert [row.section_number for row in rows] == ["1.001"]
    assert "TOC-only synopsis" not in rows[0].full_text
    assert "operative body continues" in rows[0].full_text.lower()
    assert [row["disposition"] for row in explicit_terminals] == [
        "repealed",
        "renumbered",
    ]
    assert explicit_unclassified == []

    former_html = decode_oregon_html(
        """
        <html><head><meta charset="windows-1252"></head><body>
        <p>Chapter 4 — Former Provisions</p>
        <p><b><span>4.001 Prior statutory provision.</span></b>
        [Former provision retained for source-bound disposition closure.]</p>
        </body></html>
        """.encode("windows-1252")
    )
    former_rows = scraper._parse_chapter_html(
        html=former_html,
        chapter_url="https://www.oregonlegislature.gov/bills_laws/ors/ors004.html",
        code_name="Oregon Revised Statutes",
        citation_format="Or. Rev. Stat.",
        legal_area="general",
    )

    assert former_rows == []
    assert scraper._last_oregon_terminal_sections == [
        {
            "section_number": "4.001",
            "disposition": "former_provisions",
            "source_url": (
                "https://www.oregonlegislature.gov/bills_laws/ors/"
                "ors004.html#section-4.001"
            ),
            "source_text": (
                "Prior statutory provision. [Former provision retained for "
                "source-bound disposition closure.]"
            ),
        }
    ]
    assert scraper._last_oregon_unclassified_sections == []


def test_ors_parser_selects_explicit_dated_variant_and_types_alternate() -> None:
    html = """
        <html><body>
        <p>2025 Edition</p>
        <p>Chapter 25 — Child Support Services</p>
        <p>25.554 Reopening issue of parentage; order.</p>
        <p><b>25.554 Reopening issue of parentage; order.</b>
        Current operative text before the source-printed 2027 boundary.</p>
        <p><b>Note:</b> The amendments to 25.554 by section 98, chapter 592,
        Oregon Laws 2025, become operative January 1, 2027. The text that is
        operative on and after January 1, 2027, is set forth for the user's
        convenience.</p>
        <p><b>25.554.</b> Future operative text after the 2027 boundary.</p>
        </body></html>
    """
    scraper = OregonScraper("OR", "Oregon")

    current_rows = scraper._parse_chapter_html(
        html=html,
        chapter_url="https://www.oregonlegislature.gov/bills_laws/ors/ors025.html",
        code_name="Oregon Revised Statutes",
        citation_format="Or. Rev. Stat.",
        legal_area="general",
        legal_as_of="2026-08-26T04:27:05Z",
    )

    assert len(current_rows) == 1
    assert "Current operative text" in current_rows[0].full_text
    assert "Future operative text" not in current_rows[0].full_text
    assert "user's convenience" not in current_rows[0].full_text
    assert scraper._last_oregon_duplicate_section_identities == []
    assert scraper._last_oregon_section_occurrence_count == 2
    assert scraper._last_oregon_lifecycle_exclusions == [
        {
            "section_number": "25.554",
            "disposition": "future_effective_variant",
            "source_url": (
                "https://www.oregonlegislature.gov/bills_laws/ors/"
                "ors025.html#section-25.554-variant-2"
            ),
            "source_note": (
                "Note: The amendments to 25.554 by section 98, chapter 592, "
                "Oregon Laws 2025, become operative January 1, 2027. The text "
                "that is operative on and after January 1, 2027, is set forth "
                "for the user's convenience."
            ),
            "source_text_sha256": hashlib.sha256(
                b"Future operative text after the 2027 boundary."
            ).hexdigest(),
            "source_text_byte_size": len(
                b"Future operative text after the 2027 boundary."
            ),
            "source_occurrence_kind": "operative",
            "source_occurrence_index": 2,
            "printed_section_number": "25.554",
            "effective_start": "2027-01-01",
            "effective_end": None,
            "interval_kind": "on_and_after",
            "legal_as_of": "2026-08-26",
        }
    ]

    future_rows = scraper._parse_chapter_html(
        html=html,
        chapter_url="https://www.oregonlegislature.gov/bills_laws/ors/ors025.html",
        code_name="Oregon Revised Statutes",
        citation_format="Or. Rev. Stat.",
        legal_area="general",
        legal_as_of="2027-01-01",
    )
    assert len(future_rows) == 1
    assert "Future operative text" in future_rows[0].full_text
    assert scraper._last_oregon_lifecycle_exclusions[0]["disposition"] == (
        "superseded_variant"
    )


def test_ors_parser_does_not_relax_unlabelled_duplicate_rejection() -> None:
    html = """
        <html><body>
        <p>Chapter 25 — Child Support Services</p>
        <p><b>25.554 First body.</b> First substantive version.</p>
        <p><b>25.554 Second body.</b> Second substantive version.</p>
        </body></html>
    """
    scraper = OregonScraper("OR", "Oregon")

    scraper._parse_chapter_html(
        html=html,
        chapter_url="https://www.oregonlegislature.gov/bills_laws/ors/ors025.html",
        code_name="Oregon Revised Statutes",
        citation_format="Or. Rev. Stat.",
        legal_area="general",
        legal_as_of="2026-08-26",
    )

    assert scraper._last_oregon_duplicate_section_identities == ["25.554"]
    assert scraper._last_oregon_lifecycle_exclusions == []


def test_ors_parser_preserves_source_printed_identity_mismatch_evidence() -> None:
    html = """
        <html><body>
        <p>2025 Edition</p>
        <p>Chapter 279C — Public Contracting</p>
        <p><b>279C.800 Definitions.</b> Current operative definition.</p>
        <p><b>Note:</b> The amendments to 279C.800 by section 3, chapter 11,
        Oregon Laws 2025, become operative July 1, 2026. The text that is
        operative until July 1, 2026, is set forth for the user's convenience.</p>
        <p><b>279C.805.</b> Prior operative definition printed with the wrong
        section number in the official chapter export.</p>
        <p><b>279C.805 Enforcement.</b> Independent current section.</p>
        </body></html>
    """
    scraper = OregonScraper("OR", "Oregon")

    rows = scraper._parse_chapter_html(
        html=html,
        chapter_url=(
            "https://www.oregonlegislature.gov/bills_laws/ors/ors279C.html"
        ),
        code_name="Oregon Revised Statutes",
        citation_format="Or. Rev. Stat.",
        legal_area="general",
        legal_as_of="2026-08-26",
    )

    assert [row.section_number for row in rows] == ["279c.800", "279c.805"]
    assert "Current operative definition" in rows[0].full_text
    assert "Independent current section" in rows[1].full_text
    assert scraper._last_oregon_duplicate_section_identities == []
    assert scraper._last_oregon_section_occurrence_count == 3
    assert scraper._last_oregon_lifecycle_exclusions[0][
        "printed_section_number"
    ] == "279c.805"
    assert scraper._last_oregon_lifecycle_exclusions[0]["section_number"] == (
        "279c.800"
    )
    assert scraper._last_oregon_lifecycle_exclusions[0]["disposition"] == (
        "superseded_variant"
    )


def test_ors_parser_selects_explicit_middle_stage_in_multistage_source() -> None:
    html = """
        <html><body>
        <p>2025 Edition</p>
        <p>Chapter 99 — Synthetic Lifecycle</p>
        <p><b>99.001 Default text.</b> Edition-default statutory text.</p>
        <p><b>Note 1:</b> The amendments to 99.001 become operative January 1,
        2026. The text that is operative from January 1, 2026, until January 2,
        2038, is set forth for the user's convenience.</p>
        <p><b>99.001.</b> Explicit middle-stage statutory text.</p>
        <p><b>Note 2:</b> The amendments to 99.001 become operative January 2,
        2038. The text that is operative on and after January 2, 2038, is set
        forth for the user's convenience.</p>
        <p><b>99.001.</b> Explicit final-stage statutory text.</p>
        </body></html>
    """
    scraper = OregonScraper("OR", "Oregon")

    rows = scraper._parse_chapter_html(
        html=html,
        chapter_url="https://www.oregonlegislature.gov/bills_laws/ors/ors099.html",
        code_name="Oregon Revised Statutes",
        citation_format="Or. Rev. Stat.",
        legal_area="general",
        legal_as_of="2026-08-26",
    )

    assert len(rows) == 1
    assert "Explicit middle-stage" in rows[0].full_text
    assert scraper._last_oregon_duplicate_section_identities == []
    assert scraper._last_oregon_section_occurrence_count == 3
    assert {
        row["disposition"] for row in scraper._last_oregon_lifecycle_exclusions
    } == {"superseded_variant", "future_effective_variant"}


def test_ors_parser_requires_retained_event_outcome_for_conditional_variant() -> None:
    html = """
        <html><body>
        <p>2025 Edition</p>
        <p>Chapter 403 — Emergency Communications</p>
        <p><b>403.205 Exemptions.</b> Edition-default exemptions.</p>
        <p><b>Note:</b> The amendments to 403.205 by section 4, chapter 502,
        Oregon Laws 2025, become operative on the date the Public Utility
        Commission adopts necessary rules, no later than December 1, 2026.
        The text that is operative on and after that date is set forth for the
        user's convenience.</p>
        <p><b>403.205.</b> Rules-triggered exemptions.</p>
        </body></html>
    """
    scraper = OregonScraper("OR", "Oregon")
    kwargs = {
        "html": html,
        "chapter_url": (
            "https://www.oregonlegislature.gov/bills_laws/ors/ors403.html"
        ),
        "code_name": "Oregon Revised Statutes",
        "citation_format": "Or. Rev. Stat.",
        "legal_area": "general",
        "legal_as_of": "2026-08-26",
    }

    scraper._parse_chapter_html(**kwargs)
    assert scraper._last_oregon_duplicate_section_identities == ["403.205"]

    rows = scraper._parse_chapter_html(
        **kwargs,
        conditional_outcomes={
            "puc_hb3148_rules": {
                "status": "occurred",
                "alternate_active": True,
                "event_date": "2026-04-01",
                "operative_date": "2026-04-01",
                "observed_at": "2026-08-26T10:00:00Z",
                "selector_evidence_sha256": ["a" * 64],
                "selector_source_urls": [
                    "https://apps.puc.state.or.us/edockets/"
                    "DocketNoLayout.asp?DocketID=24714"
                ],
            }
        },
    )
    assert len(rows) == 1
    assert "Rules-triggered exemptions" in rows[0].full_text
    assert scraper._last_oregon_duplicate_section_identities == []
    exclusion = scraper._last_oregon_lifecycle_exclusions[0]
    assert exclusion["event_key"] == "puc_hb3148_rules"
    assert exclusion["event_status"] == "occurred"
    assert exclusion["selector_evidence_sha256"] == ["a" * 64]


def test_ors_parser_retains_default_when_proven_event_has_not_occurred() -> None:
    html = """
        <html><body>
        <p>2025 Edition</p>
        <p>Chapter 433 — Public Health</p>
        <p><b>433.321 Screening.</b> Current targeted screening text.</p>
        <p><b>Note:</b> The amendments to 433.321 become operative on the date
        the Oregon Health Authority adds cytomegalovirus to the newborn
        bloodspot screening panel. The text that is operative on and after that
        date is set forth for the user's convenience.</p>
        <p><b>433.321.</b> Future bloodspot-panel text.</p>
        </body></html>
    """
    scraper = OregonScraper("OR", "Oregon")

    rows = scraper._parse_chapter_html(
        html=html,
        chapter_url="https://www.oregonlegislature.gov/bills_laws/ors/ors433.html",
        code_name="Oregon Revised Statutes",
        citation_format="Or. Rev. Stat.",
        legal_area="general",
        legal_as_of="2026-08-26",
        conditional_outcomes={
            "cmv_bloodspot_panel": {
                "status": "not_occurred",
                "alternate_active": False,
                "event_date": None,
                "operative_date": None,
                "observed_at": "2026-08-26T10:00:00Z",
                "selector_evidence_sha256": ["b" * 64],
                "selector_source_urls": ["https://www.oregon.gov/oha/cmv"],
            }
        },
    )

    assert len(rows) == 1
    assert "Current targeted screening text" in rows[0].full_text
    assert scraper._last_oregon_duplicate_section_identities == []
    exclusion = scraper._last_oregon_lifecycle_exclusions[0]
    assert exclusion["disposition"] == "inactive_conditional_variant"
    assert exclusion["interval_kind"] == "conditional_event_not_met"
    assert exclusion["event_status"] == "not_occurred"


def test_current_event_selector_catalog_covers_every_conditional_note() -> None:
    expected = set(oregon_module.ORS_CONDITIONAL_EVENT_NOTE_MARKERS)

    assert set(oregon_module.ORS_CONDITIONAL_EVENT_SELECTOR_SPECS) == expected
    assert set(oregon_module.ORS_CONDITIONAL_SECTION_EVENT_KEYS.values()) == expected


def test_ojd_selector_normalization_removes_only_query_highlights() -> None:
    payload = (
        b'{"official":true,"text":"appeal from the General Judgment entered '
        b'on [h8s]June[h8e] [h8s]7[h8e], [h8s]2024[h8e]"}'
    )

    visible, _raw = OregonScraper._ors_event_selector_search_text(payload)

    assert "appeal from the general judgment entered on june 7, 2024" in visible


@pytest.mark.anyio
async def test_conditional_selectors_share_one_mixed_media_plural_frontier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls = [
        "https://evidence.example.gov/first",
        "https://evidence.example.gov/second",
        "https://other.example.gov/third",
    ]
    specs = {
        "alpha": {
            "status": "not_occurred",
            "alternate_active": False,
            "event_date": None,
            "operative_date": None,
            "conclusion": "The alpha trigger has not occurred.",
            "sources": (
                {"url": urls[0], "require_all": ("alpha current",)},
                {"url": urls[1], "require_any": ("alpha absent", "alpha pending")},
            ),
        },
        "beta": {
            "status": "occurred",
            "alternate_active": True,
            "event_date": "2026-01-01",
            "operative_delay_days": 2,
            "operative_date": "2026-01-03",
            "conclusion": "The beta trigger occurred.",
            "sources": (
                {"url": urls[2], "require_all": ("beta occurred",)},
            ),
        },
    }
    pages = {
        urls[0]: b"<html><body>alpha current" + b" x" * 80 + b"</body></html>",
        urls[1]: b"<html><body>alpha pending" + b" x" * 80 + b"</body></html>",
        urls[2]: b"<html><body>beta occurred" + b" x" * 80 + b"</body></html>",
    }
    scraper = OregonScraper("OR", "Oregon")
    calls: list[tuple[list[str], dict[str, object]]] = []

    async def _plural(
        requested: list[str],
        **kwargs: object,
    ) -> StateLawPageMultiFetchResult:
        calls.append((list(requested), dict(kwargs)))
        return _aligned_result(list(requested), pages)

    monkeypatch.setattr(
        oregon_module,
        "ORS_CONDITIONAL_EVENT_SELECTOR_SPECS",
        specs,
    )
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )

    outcomes = await scraper._acquire_ors_conditional_event_outcomes(
        ["beta", "alpha"]
    )

    assert len(calls) == 1
    assert calls[0][0] == urls
    assert calls[0][1]["common_crawl_url_terms"] is None
    assert calls[0][1]["common_crawl_domain_terms"] is None
    assert calls[0][1]["media_type"] == "application/octet-stream"
    assert calls[0][1]["common_crawl_mime_terms"] == (
        "html",
        "text",
        "json",
        "pdf",
    )
    assert outcomes["alpha"]["alternate_active"] is False
    assert outcomes["beta"]["operative_date"] == "2026-01-03"
    assert outcomes["beta"]["selector_source_urls"] == [urls[2]]
    assert len(outcomes["beta"]["selector_decision_sha256"]) == 64


@pytest.mark.anyio
async def test_conditional_selector_changed_wording_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://evidence.example.gov/selector"
    scraper = OregonScraper("OR", "Oregon")

    monkeypatch.setattr(
        oregon_module,
        "ORS_CONDITIONAL_EVENT_SELECTOR_SPECS",
        {
            "event": {
                "status": "not_occurred",
                "alternate_active": False,
                "conclusion": "Synthetic negative selector.",
                "sources": (
                    {"url": url, "require_all": ("required exact phrase",)},
                ),
            }
        },
    )

    async def _plural(
        requested: list[str],
        **_kwargs: object,
    ) -> StateLawPageMultiFetchResult:
        return _aligned_result(
            list(requested),
            {url: b"<html><body>changed official wording" + b" x" * 80 + b"</body></html>"},
        )

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )

    with pytest.raises(RuntimeError, match="selector wording changed"):
        await scraper._acquire_ors_conditional_event_outcomes(["event"])


def test_ors_parser_types_reused_historical_terminal_number() -> None:
    html = """
        <html><body>
        <p>2025 Edition</p>
        <p>Chapter 407 — Veterans</p>
        <p><b>407.090.</b> (Original) [Formerly 407.090; renumbered 407.145]</p>
        <p><b>407.090.</b> (Reassigned) [Formerly 407.090; renumbered 407.087]</p>
        </body></html>
    """
    scraper = OregonScraper("OR", "Oregon")

    rows = scraper._parse_chapter_html(
        html=html,
        chapter_url="https://www.oregonlegislature.gov/bills_laws/ors/ors407.html",
        code_name="Oregon Revised Statutes",
        citation_format="Or. Rev. Stat.",
        legal_area="general",
        legal_as_of="2026-08-26",
    )

    assert rows == []
    assert scraper._last_oregon_duplicate_section_identities == []
    assert scraper._last_oregon_section_occurrence_count == 2
    assert len(scraper._last_oregon_terminal_sections) == 1
    assert scraper._last_oregon_terminal_sections[0]["section_number"] == "407.090"
    assert scraper._last_oregon_lifecycle_exclusions[0]["disposition"] == (
        "historical_reused_number_variant"
    )


def test_ors_parser_admits_four_digit_ucc_section_identity() -> None:
    html = """
        <html><body>
        <p>2025 Edition</p>
        <p>Chapter 79A — Secured Transactions</p>
        <p><span>79A.1010 UCC 9-101. Short title</span></p>
        <p><b><span>79A.1010 UCC 9-101. Short title.</span></b>
        This chapter may be cited as the Uniform Commercial Code—Secured
        Transactions. See ORS 79A.1020.</p>
        </body></html>
    """
    scraper = OregonScraper("OR", "Oregon")

    rows = scraper._parse_chapter_html(
        html=html,
        chapter_url=(
            "https://www.oregonlegislature.gov/bills_laws/ors/ors079A.html"
        ),
        code_name="Oregon Revised Statutes",
        citation_format="Or. Rev. Stat.",
        legal_area="general",
        legal_as_of="2026-08-26",
    )

    assert [row.section_number for row in rows] == ["79a.1010"]
    assert scraper._last_oregon_toc_section_identities == ["79a.1010"]
    assert rows[0].structured_data["citations"]["ors_citations"] == [
        "79A.1020"
    ]


def test_ors_parser_keeps_mixed_three_and_four_digit_identities_distinct() -> None:
    html = """
        <html><body>
        <p>2025</p><p>EDITION</p>
        <p>Chapter 71 — Uniform Commercial Code</p>
        <p><span>71.101 General provision</span></p>
        <p><span>71.1010 UCC provision</span></p>
        <p><b>71.101 General provision.</b> Three-digit operative text.</p>
        <p><b>71.1010 UCC provision.</b> Four-digit operative text.</p>
        </body></html>
    """
    scraper = OregonScraper("OR", "Oregon")

    rows = scraper._parse_chapter_html(
        html=html,
        chapter_url=(
            "https://www.oregonlegislature.gov/bills_laws/ors/ors071.html"
        ),
        code_name="Oregon Revised Statutes",
        citation_format="Or. Rev. Stat.",
        legal_area="general",
        legal_as_of="2026-08-26",
    )

    assert [row.section_number for row in rows] == ["71.101", "71.1010"]
    assert [row.metadata.enacted_year for row in rows] == ["2025", "2025"]
    assert scraper._last_oregon_section_occurrence_count == 2


def test_ors_parser_does_not_treat_lifecycle_word_in_title_as_terminal() -> None:
    html = """
        <html><body>
        <p>2025 Edition</p>
        <p>Chapter 79A — Secured Transactions</p>
        <p><span>79A.3250 Priority in transferred collateral</span></p>
        <p><span>79A.3260 Reserved rights in collateral</span></p>
        <p><b>79A.3250 UCC 9-325. Priority of security interests in
        transferred collateral.</b> A security interest created by a debtor
        is subordinate to a security interest in the same collateral.</p>
        <p><b>79A.3260 Reserved rights in collateral.</b> A secured party
        retains the substantive rights specified in this section.</p>
        </body></html>
    """
    scraper = OregonScraper("OR", "Oregon")

    rows = scraper._parse_chapter_html(
        html=html,
        chapter_url=(
            "https://www.oregonlegislature.gov/bills_laws/ors/ors079A.html"
        ),
        code_name="Oregon Revised Statutes",
        citation_format="Or. Rev. Stat.",
        legal_area="general",
        legal_as_of="2026-08-26",
    )

    assert [row.section_number for row in rows] == ["79a.3250", "79a.3260"]
    assert scraper._last_oregon_terminal_sections == []


def test_ors_parser_reassembles_split_substantive_heading() -> None:
    html = """
        <html><body>
        <p>2025 Edition</p>
        <p>Chapter 818 — Vehicle Limits</p>
        <p><span>818.012 Wheel load rules</span></p>
        <p><span>818.020 Violating maximum weight limits; civil liability;
        penalties</span></p>
        <p><b>818.012 Wheel load rules.</b> Existing operative text.</p>
        <p><span>818.020 Violating maximum weight limits; civil liability;</span></p>
        <p><b>penalties.</b> A person commits the offense when the person
        exceeds the statutory maximum weight.</p>
        </body></html>
    """
    scraper = OregonScraper("OR", "Oregon")

    rows = scraper._parse_chapter_html(
        html=html,
        chapter_url=(
            "https://www.oregonlegislature.gov/bills_laws/ors/ors818.html"
        ),
        code_name="Oregon Revised Statutes",
        citation_format="Or. Rev. Stat.",
        legal_area="general",
        legal_as_of="2026-08-26",
    )

    assert [row.section_number for row in rows] == ["818.012", "818.020"]
    assert rows[1].section_name.endswith("penalties.")
    assert "commits the offense" in rows[1].full_text


def test_ors_repeal_note_does_not_alias_the_following_section() -> None:
    html = """
        <html><body>
        <p>2025 Edition</p>
        <p>Chapter 409 — Human Services</p>
        <p><span>409.800 Existing assessment provision</span></p>
        <p><span>409.801 Long term care facility assessment</span></p>
        <p><b>409.800 Existing assessment provision.</b> Existing text.</p>
        <p><b>Note:</b> 409.800 is repealed January 2, 2034.</p>
        <p><b>409.801 Long term care facility assessment.</b> A long term care
        facility assessment is imposed on each facility in this state.</p>
        </body></html>
    """
    scraper = OregonScraper("OR", "Oregon")

    rows = scraper._parse_chapter_html(
        html=html,
        chapter_url=(
            "https://www.oregonlegislature.gov/bills_laws/ors/ors409.html"
        ),
        code_name="Oregon Revised Statutes",
        citation_format="Or. Rev. Stat.",
        legal_area="general",
        legal_as_of="2026-08-26",
    )

    assert [row.section_number for row in rows] == ["409.800", "409.801"]
    assert scraper._last_oregon_lifecycle_exclusions == []


def test_ors_chapter_edition_gate_rejects_explicit_stale_archive() -> None:
    assert oregon_module._ors_chapter_matches_edition(
        "<p>2025</p><p>EDITION</p><p>79A.1010 Current text.</p>",
        2025,
    )
    assert oregon_module._ors_chapter_matches_edition(
        "<p>Former Provisions</p><p>27.010 Repealed.</p>",
        2025,
    )
    assert not oregon_module._ors_chapter_matches_edition(
        "<p>2015</p><p>EDITION</p><p>79A.1010 Stale text.</p>",
        2025,
    )


def test_ors_parser_types_collective_former_provisions_note() -> None:
    html = """
        <html><body>
        <p>Chapter 27 (Former Provisions)</p>
        <p>Submitting Controversy Without Action or Suit</p>
        <p><b>Note:</b></p>
        <p>27.010, 27.020 and 27.030 repealed by 1981 c.898 §53.</p>
        </body></html>
    """
    scraper = OregonScraper("OR", "Oregon")

    rows = scraper._parse_chapter_html(
        html=html,
        chapter_url=(
            "https://www.oregonlegislature.gov/bills_laws/ors/ors027.html"
        ),
        code_name="Oregon Revised Statutes",
        citation_format="Or. Rev. Stat.",
        legal_area="general",
        legal_as_of="2026-08-26",
    )

    assert rows == []
    assert [
        row["section_number"] for row in scraper._last_oregon_terminal_sections
    ] == ["27.010", "27.020", "27.030"]
    assert {
        row["disposition"] for row in scraper._last_oregon_terminal_sections
    } == {"repealed"}
    assert scraper._last_oregon_section_occurrence_count == 3


@pytest.mark.anyio
async def test_strict_full_tree_merges_ors_and_current_session_law_frontiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_html = _strict_seed_html()
    groups = ors_sharepoint_title_groups(seed_html)
    assert len(groups) == 19
    assert {group.volume_index for group in groups} == set(range(1, 20))
    assert sum(group.declared_chapter_count for group in groups) == 20

    chapters_by_group: dict[str, list[int]] = {}
    for group in groups:
        chapters_by_group[group.inventory_url] = (
            [1, 20] if group.volume_index == 1 else [group.volume_index]
        )

    group_pages = {
        group_url: (
            "<html><body>"
            + "".join(
                (
                    f"<a href='/bills_laws/ors/ors{chapter:03d}.html'>"
                    f"Chapter {chapter}</a>"
                )
                for chapter in chapters
            )
            + "</body></html>"
        ).encode()
        for group_url, chapters in chapters_by_group.items()
    }
    chapter_urls = [
        f"https://www.oregonlegislature.gov/bills_laws/ors/ors{chapter:03d}.html"
        for chapters in chapters_by_group.values()
        for chapter in chapters
    ]
    chapter_pages = {
        url: _chapter_html(int(url.rsplit("ors", 1)[1].split(".", 1)[0]))
        for url in chapter_urls
    }
    law_landing = _session_law_landing_html()
    law_sessions = oregon_current_law_sessions(law_landing)
    law_group_pages = {
        law_sessions[0].inventory_url: _session_law_group_html("2025S1OrLaw", 2),
        law_sessions[1].inventory_url: _session_law_group_html("2026orlaw", 142),
    }
    law_locators = [
        locator
        for session in law_sessions
        for locator in oregon_law_chapter_locators(
            law_group_pages[session.inventory_url].decode(),
            session,
        )
    ]
    law_pdf_pages = {
        locator.canonical_url: _complete_synthetic_pdf(index)
        for index, locator in enumerate(law_locators)
    }
    supplement_group_pages = {
        oregon_supplement_inventory_url(session): _session_supplement_html(session.key)
        for session in law_sessions
    }
    resolution_group_pages = {
        oregon_resolution_inventory_url(session): _session_resolution_html(session.key)
        for session in law_sessions
    }
    table_locators = [
        row
        for session in law_sessions
        for row in oregon_supplement_locators(
            _session_supplement_html(session.key).decode(),
            session,
        )
        if row.document_kind in {"enacted_table", "affected_table"}
    ]
    table_pdf_pages = {
        locator.canonical_url: _complete_synthetic_pdf(index + 144)
        for index, locator in enumerate(table_locators)
    }
    all_plural_pages = {
        OregonScraper.OFFICIAL_ENTRY_URL: seed_html.encode(),
        **group_pages,
        **chapter_pages,
        LAWS_MOBILE_URL: law_landing.encode(),
        **law_group_pages,
        **law_pdf_pages,
        **supplement_group_pages,
        **resolution_group_pages,
        **table_pdf_pages,
    }

    scraper = OregonScraper("OR", "Oregon")
    singleton_calls: list[tuple[str, dict[str, object]]] = []
    plural_calls: list[tuple[list[str], dict[str, object]]] = []

    async def _singleton(url: str, **kwargs: object) -> bytes:
        singleton_calls.append((url, dict(kwargs)))
        return seed_html.encode()

    async def _plural(
        urls: list[str],
        **kwargs: object,
    ) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        plural_calls.append((requested, dict(kwargs)))
        return _aligned_result(requested, all_plural_pages)

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        scraper,
        "_fetch_page_content_with_archival_fallback",
        _singleton,
    )
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    monkeypatch.setattr(
        oregon_session_laws,
        "parse_oregon_law_pdf",
        _parsed_synthetic_law,
    )
    monkeypatch.setattr(
        oregon_session_laws,
        "parse_oregon_enacted_pdf",
        _parsed_synthetic_enacted,
    )
    monkeypatch.setattr(
        oregon_session_laws,
        "parse_oregon_affected_pdf",
        _parsed_synthetic_affected,
    )

    rows = await scraper._scrape_official_ors_chapter_tree(
        "Oregon Revised Statutes",
        scraper.OFFICIAL_ENTRY_URL,
        max_statutes=None,
    )

    assert singleton_calls == []
    assert len(plural_calls) == 8
    assert plural_calls[0][0] == [scraper.OFFICIAL_ENTRY_URL]
    assert plural_calls[0][1]["headers"] == {
        "User-Agent": "ipfs-datasets-oregon-statutes/2.0"
    }
    assert plural_calls[1][0] == [group.inventory_url for group in groups]
    assert plural_calls[2][0] == chapter_urls
    assert plural_calls[3][0] == [LAWS_MOBILE_URL]
    assert plural_calls[4][0] == [session.inventory_url for session in law_sessions]
    assert plural_calls[5][0] == [locator.canonical_url for locator in law_locators]
    assert len(plural_calls[5][0]) == 144
    assert plural_calls[6][0] == [
        *[oregon_supplement_inventory_url(session) for session in law_sessions],
        *[oregon_resolution_inventory_url(session) for session in law_sessions],
    ]
    assert plural_calls[7][0] == [locator.canonical_url for locator in table_locators]
    assert all(
        urlparse(url).hostname == scraper.OFFICIAL_DOMAIN
        for requested, _kwargs in plural_calls
        for url in requested
    )
    assert len(rows) == 164
    assert len({row.statute_id for row in rows}) == 164
    assert all("TOC-only synopsis" not in row.full_text for row in rows)

    closure = scraper._last_oregon_strict_closure
    assert closure["closed"] is True
    assert closure["title_group_count"] == 19
    assert closure["declared_chapter_count"] == 20
    assert closure["chapter_page_count"] == 20
    assert closure["ors_operative_section_count"] == 20
    assert closure["session_law_section_count"] == 144
    assert closure["operative_section_count"] == 164
    assert closure["terminal_section_count"] == 0
    assert closure["unclassified_section_count"] == 0

    projection = build_canonical_state_law_output_projection(
        [scraper._enrich_statute_structure(row).to_dict() for row in rows],
        jurisdiction="OR",
    )
    retained: dict[str, object] = {}

    def _evidence(**kwargs: object) -> dict[str, object]:
        payload = bytes(kwargs["payload"])
        return {
            "content_sha256": hashlib.sha256(payload).hexdigest(),
            "parser_input_receipt_sha256": "a" * 64,
            "source_retrieved_at": "2026-08-25T00:00:00+00:00",
            "source_transport": "direct",
            "source_transport_chain": ["direct"],
            "transport_receipt": {},
        }

    def _retain(completion: dict[str, object], **kwargs: object) -> Path:
        retained["completion"] = completion
        retained["kwargs"] = kwargs
        return Path("/synthetic/STATE-OR.frontier-closure.json")

    scraper._state_law_acquisition_ledger = object()
    monkeypatch.setattr(scraper, "_oregon_input_evidence_context", _evidence)
    monkeypatch.setattr(
        scraper,
        "retain_state_law_frontier_closure_projection",
        _retain,
    )
    retained_path = await scraper.produce_state_law_frontier_closure(
        canonical_output_projection=projection,
    )

    assert retained_path == Path("/synthetic/STATE-OR.frontier-closure.json")
    assert singleton_calls == []
    assert len(plural_calls) == 16
    for offset in range(8):
        assert plural_calls[8 + offset][0] == plural_calls[offset][0]
    completion = retained["completion"]
    assert isinstance(completion, dict)
    assert completion["disposition"]["discovered"] == 164
    assert completion["disposition"]["fetched"] == 164
    assert completion["disposition"]["excluded"] == 0
    assert completion["frontier"] == retained["kwargs"]["replayed_frontier"]
    assert completion["frontier"]["session_law_source_document_disposition"] == {
        "discovered": 154,
        "fetched": 144,
        "excluded": 10,
        "failed_final": 0,
        "duplicates": 0,
        "quarantined": 0,
    }
    assert len(completion["frontier"]["session_law_resolution_exclusions"]) == 10
    assert completion["rights"] == {
        "basis": "public_law_no_state_copyright",
        "decision": "admit",
        "scope": "statutory_text",
    }
