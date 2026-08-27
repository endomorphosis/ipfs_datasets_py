"""Focused coverage for Oklahoma's official 89-PDF migration."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oklahoma import (
    OklahomaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oklahoma_title import (
    EXPECTED_TITLE_COUNT,
    TITLES_HTML_URL,
    _is_table_of_contents_page,
    _statutory_lines_from_pdf_page,
    inactive_title_frontier_from_text,
    parse_oklahoma_title_text,
    title_pdf_links,
    title_pdf_url,
)

EXPECTED_TITLE_NUMBERS = tuple(
    """
    1 2 3 3A 4 5 6 7 8 9 10 10A 11 12 12A 13 14 14A 15 16 17 18 19 20
    21 22 23 24 25 26 27 27A 28 29 30 31 32 33 34 36 37 37A 38 39 40 41 42
    43 43A 44 45 46 47 49 50 51 52 53 54 56 57 58 59 60 61 62 63 64 65
    66 67 68 69 70 71 72 73 74 74E 75 76 78 79 80 82 83 84 85 85A
    """.split()
)


def _complete_toc_html() -> bytes:
    anchors = "".join(
        f'<a href="{title_pdf_url(number)}">Title {number} - {name}</a>'
        for number, name in OklahomaScraper.OFFICIAL_TITLES
    )
    return f"<!doctype html><html><body>{anchors}</body></html>".encode()


def _direct_evidence(url: str, payload: bytes) -> dict[str, str]:
    return {
        "content_sha256": hashlib.sha256(payload).hexdigest(),
        "official_url": url,
        "source_transport": "direct",
    }


def test_declared_complete_title_frontier_is_exact_and_uses_live_locators() -> None:
    scraper = OklahomaScraper("OK", "Oklahoma")
    declared = tuple(number for number, _name in scraper.OFFICIAL_TITLES)
    codes = scraper.get_code_list()

    assert TITLES_HTML_URL == "https://www.oklegislature.gov/osstatuestitle.html"
    assert EXPECTED_TITLE_COUNT == len(EXPECTED_TITLE_NUMBERS) == 89
    assert declared == EXPECTED_TITLE_NUMBERS
    assert len(codes) == 89
    assert {item["title_number"] for item in codes} == set(EXPECTED_TITLE_NUMBERS)
    assert all(
        item["url"].startswith(
            "https://www.oklegislature.gov/OK_Statutes/CompleteTitles/os"
        )
        for item in codes
    )
    assert title_pdf_url("37A").endswith("/os37a.pdf")


def test_title_toc_parser_deduplicates_and_rejects_nonofficial_members() -> None:
    html = """
    <html><body>
      <a href="/OK_Statutes/CompleteTitles/os21.pdf">Title 21</a>
      <a href="/OK_Statutes/CompleteTitles/os21.pdf">Title 21 duplicate</a>
      <a href="https://www.oklegislature.gov/OK_Statutes/CompleteTitles/os74E.pdf">Title 74E</a>
      <a href="https://mirror.invalid/OK_Statutes/CompleteTitles/os33.pdf">Title 33</a>
    </body></html>
    """

    links = title_pdf_links(html)

    assert [(number, url) for number, _name, url in links] == [
        ("21", title_pdf_url("21")),
        ("74E", title_pdf_url("74E")),
    ]


def test_title_74e_rule_parser_emits_rules_and_skips_history_and_repeals() -> None:
    text = """
    Rule 2.34. Contributions by Limited Committees Registered for Less than
    Twenty-Five Contributors. ..................................................................... 21
    Oklahoma Statutes - Title 74, Appendix I, Ethics Commission Rules Page 2
    Rule 1.1. Purpose and authority
    This rule establishes binding ethics requirements for officials and employees of this state.
    Oklahoma Statutes - Title 74, Appendix I, Ethics Commission Rules Page 6
    Promulgated by Ethics Commission, effective January 1, 2026.
    Rule 1.2. Repealed
    This former rule has no current legal force and must not be admitted as current law.
    Rule 1.3. Definitions
    The following words and phrases have the meanings stated in this rule for all covered persons.
    Amendment promulgated by Ethics Commission, effective February 1, 2026.
    """

    rows = parse_oklahoma_title_text(
        text,
        title_number="74E",
        source_url=title_pdf_url("74E"),
    )

    assert [row.section_number for row in rows] == ["74E-Rule-1.1", "74E-Rule-1.3"]
    assert rows[0].title_number == "74E"
    assert rows[0].official_cite == "Okla. Stat. tit. 74, app. I, Ethics Comm'n R. 1.1"
    assert "Promulgated" not in rows[0].full_text
    assert "Oklahoma Statutes - Title" not in rows[0].full_text


def test_title_33_repealed_frontier_is_typed_byte_bound_and_fail_closed() -> None:
    text = """
    § 33-1. Repealed by Laws 1965, c. 1, § 1.
    Repealed by Laws 1965, c. 1, § 1.
    § 33-2. Repealed by Laws 1965, c. 2, § 2.
    Repealed by Laws 1965, c. 2, § 2.
    § 33-3. Repealed by Laws 1965, c. 3, § 3.
    Repealed by Laws 1965, c. 3, § 3.
    § 33-4. Repealed by Laws 1965, c. 4, § 4.
    Repealed by Laws 1965, c. 4, § 4.
    """
    digest = hashlib.sha256(b"official-title-33-pdf").hexdigest()
    observed_at = datetime.now(UTC).isoformat()

    assert parse_oklahoma_title_text(text, title_number="33") == []
    evidence = inactive_title_frontier_from_text(
        text,
        title_number="33",
        code_name="Oklahoma Statutes Title 33 — Inebriates",
        source_url=title_pdf_url("33"),
        content_sha256=digest,
        observed_at=observed_at,
        transport_receipt={"source_transport": "direct"},
    )

    assert evidence is not None
    assert evidence.title_number == "33"
    assert evidence.disposition == "repealed"
    assert evidence.expected_statute_count == 0
    assert evidence.inactive_section_count == 4
    assert evidence.content_sha256 == digest

    assert (
        inactive_title_frontier_from_text(
            text + "\n§ 33-5. Current section.\nThis section remains current law.",
            title_number="33",
            code_name="Oklahoma Statutes Title 33 — Inebriates",
            source_url=title_pdf_url("33"),
            content_sha256=digest,
            observed_at=observed_at,
            transport_receipt={"source_transport": "direct"},
        )
        is None
    )


def test_active_section_can_reference_a_repealed_provision_without_being_dropped() -> None:
    rows = parse_oklahoma_title_text(
        """
        § 21-2. Scope of current law.
        This current section applies even when a prior provision (repealed) is cited in an official filing or judicial record.
        """,
        title_number="21",
        source_url=title_pdf_url("21"),
    )

    assert len(rows) == 1
    assert rows[0].section_number == "21-2"
    assert "prior provision (repealed)" in rows[0].full_text


def test_parser_distinguishes_decimal_cites_and_accepts_article_letter_cites() -> None:
    rows = parse_oklahoma_title_text(
        """
        §12A-1-9-107. Base section.
        This base provision contains enough operative text to remain current under the parser contract.
        Laws 2024, c. 13, § 1.
        §12A-1-9-107A Control of controllable electronic records.
        A secured party has control under the conditions prescribed by this current operative provision.
        Laws 2024, c. 13, § 2.
        §12A-A-101. Short title.
        This article governs transitional provisions for the Uniform Commercial Code amendments.
        Laws 2024, c. 13, § 98.
        """,
        title_number="12A",
        source_url=title_pdf_url("12A"),
    )

    assert [row.section_number for row in rows] == [
        "12A-1-9-107",
        "12A-1-9-107A",
        "12A-A-101",
    ]


def test_parser_rejects_wrapped_table_of_contents_candidate() -> None:
    rows = parse_oklahoma_title_text(
        """
        §2-5-86. Agricultural linked deposit loan packages - Completion by borrower - Acceptance and
        review by lending institutions - Certification of proposed use - Priority for economic needs of area -
        Submission of package to State Treasurer - Approval or rejection........................................ 219
        §2-5-86. Agricultural linked deposit loan packages - Completion by borrower.
        The State Treasurer shall administer this current linked deposit program according to this section.
        Laws 2025, c. 174, § 2.
        """,
        title_number="2",
        source_url=title_pdf_url("2"),
    )

    assert len(rows) == 1
    assert rows[0].section_number == "2-5-86"
    assert rows[0].full_text.startswith("The State Treasurer")


def test_pdf_page_classifier_requires_dense_toc_evidence() -> None:
    assert _is_table_of_contents_page(
        [
            "§47-1166. Transfer of powers and duties to the Commission -",
            "Records, property, pending matters, funds, and rules. ............ 1442",
            "§47-1167. Fees, fines, and enforcement actions. ............... 1444",
        ]
    )
    assert not _is_table_of_contents_page(
        [
            "§47-1166. Transfer of powers and duties to the Commission.",
            "A. Effective July 1, all powers and responsibilities are transferred.",
            "§47-1167. Fees, fines, and enforcement actions.",
        ]
    )


def test_mixed_toc_page_preserves_only_source_bound_statutory_suffix() -> None:
    lines = [
        "OKLAHOMA STATUTES TITLE 33. INEBRIATES",
        "§33-1. Repealed by Laws 1965, c. 118, § 1. ............ 1",
        "§33-2. Repealed by Laws 1965, c. 118, § 1. ............ 1",
        "§33-1. Repealed by Laws 1965, c. 118, § 1.",
        "§33-2. Repealed by Laws 1965, c. 118, § 1.",
    ]

    assert _statutory_lines_from_pdf_page(lines) == lines[-2:]
    assert _statutory_lines_from_pdf_page(lines[:3]) == []


def test_version_index_is_not_emitted_and_exact_duplicate_is_collapsed() -> None:
    rows = parse_oklahoma_title_text(
        """
        §47-6-301. See the following versions:
        OS 47-6-301v1 (SB 544, Laws 2025, c. 38, § 3)
        OS 47-6-301v2 (HB 2104, Laws 2025, c. 486, § 516)
        §47-6-301v1. Unlawful use of license or identification card.
        It is unlawful to use an identification card in the manner prohibited by this current operative version.
        Laws 2025, c. 38, § 3.
        §47-6-301. Unlawful use of license or identification card.
        This current version prohibits use of an identification card for a fraudulent statutory purpose.
        Laws 2025, c. 486, § 516.
        §47-9-9. Exact publisher duplicate.
        This operative provision is printed twice verbatim in the official complete-title PDF publication.
        Laws 2025, c. 1, § 1.
        §47-9-9. Exact publisher duplicate.
        This operative provision is printed twice verbatim in the official complete-title PDF publication.
        Laws 2025, c. 1, § 1.
        """,
        title_number="47",
        source_url=title_pdf_url("47"),
    )

    assert [row.section_number for row in rows] == [
        "47-6-301v1",
        "47-6-301",
        "47-9-9",
    ]
    assert rows[-1].structured_data["source_duplicate_occurrence_count"] == 2
    assert rows[-1].structured_data["source_duplicate_disposition"] == (
        "collapsed_exact_normalized_official_duplicate"
    )


def test_conflicting_duplicate_section_fails_closed() -> None:
    with pytest.raises(ValueError, match="conflicting duplicate section identity"):
        parse_oklahoma_title_text(
            """
            §21-1. First text.
            This first operative body has enough statutory text to pass the minimum length requirement.
            Laws 2025, c. 1, § 1.
            §21-1. Second text.
            This conflicting operative body also has enough statutory text but must never replace the first.
            Laws 2025, c. 2, § 2.
            """,
            title_number="21",
            source_url=title_pdf_url("21"),
        )


@pytest.mark.anyio
async def test_base_fetch_content_validator_rejects_html_and_records_pdf_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = OklahomaScraper("OK", "Oklahoma")
    source_url = title_pdf_url("21")
    pdf = b"%PDF-1.7\n" + (b"official-pdf-body" * 32)

    async def _invalid_cache(_url: str) -> bytes:
        return b"<html><body>Turnstile challenge</body></html>"

    class _Response:
        status = 200

        def read(self) -> bytes:
            return pdf

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb) -> bool:
            return False

    monkeypatch.setattr(scraper, "_load_page_bytes_from_any_cache", _invalid_cache)
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: _Response())

    payload = await scraper._fetch_page_content_with_archival_fallback(
        source_url,
        content_validator=scraper._looks_like_official_pdf,
        enable_unified=False,
    )

    assert payload == pdf
    assert scraper._last_page_fetch_transport_evidence == _direct_evidence(
        source_url, pdf
    )


def _install_fake_live_title(
    monkeypatch: pytest.MonkeyPatch,
    *,
    scraper: OklahomaScraper,
    title_number: str,
    extracted_text: str,
) -> bytes:
    from ipfs_datasets_py.processors.web_archiving.unified_web_scraper import (
        UnifiedWebScraper,
    )

    toc = _complete_toc_html()
    pdf_url = title_pdf_url(title_number)
    pdf = b"%PDF-1.7\n" + (f"official-title-{title_number}".encode() * 32)

    async def _fetch(
        url: str,
        timeout_seconds: int = 25,
        *,
        content_validator=None,
        enable_unified: bool = True,
    ) -> bytes:
        del timeout_seconds, enable_unified
        payload = toc if url == scraper.OFFICIAL_ENTRY_URL else pdf if url == pdf_url else b""
        assert payload
        assert content_validator is not None and content_validator(payload)
        scraper._last_page_fetch_transport_evidence = _direct_evidence(url, payload)
        return payload

    async def _extract(payload: bytes) -> str:
        assert payload == pdf
        return extracted_text

    monkeypatch.setattr(scraper, "_fetch_page_content_with_archival_fallback", _fetch)
    monkeypatch.setattr(UnifiedWebScraper, "_extract_pdf_text", staticmethod(_extract))
    return pdf


@pytest.mark.anyio
async def test_live_fake_reuses_shared_fetch_receipts_and_unified_pdf_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = OklahomaScraper("OK", "Oklahoma")
    code_info = next(
        item for item in scraper.get_code_list() if item["title_number"] == "21"
    )
    pdf = _install_fake_live_title(
        monkeypatch,
        scraper=scraper,
        title_number="21",
        extracted_text="""
        § 21-1.1. Definitions.
        The words defined in this section govern every criminal statute in this title unless context requires otherwise.
        Laws 2026, c. 1, § 1.
        """,
    )

    rows = await scraper.scrape_code(
        code_info["name"], code_info["url"], max_statutes=5
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.code_name == code_info["name"]
    assert row.source_url == title_pdf_url("21")
    assert row.structured_data["extraction_method"] == (
        "UnifiedWebScraper._extract_pdf_text"
    )
    assert row.structured_data["source_frontier_expected_titles"] == 89
    assert row.structured_data["source_frontier_url"] == scraper.OFFICIAL_ENTRY_URL
    assert (
        row.structured_data["source_frontier_transport_receipt"]["source_transport"]
        == "direct"
    )
    assert row.structured_data["source_document_sha256"] == hashlib.sha256(pdf).hexdigest()
    assert row.structured_data["transport_receipt"]["source_transport"] == "direct"
    assert row.structured_data["full_corpus_admissible"] is True


@pytest.mark.anyio
async def test_live_valid_pdf_uses_page_aware_oklahoma_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        oklahoma_title,
    )

    scraper = OklahomaScraper("OK", "Oklahoma")
    code_info = next(
        item for item in scraper.get_code_list() if item["title_number"] == "21"
    )
    operative_text = """
    § 21-1.1. Definitions.
    The words defined in this section govern every criminal statute in this title unless context requires otherwise.
    Laws 2026, c. 1, § 1.
    """
    _install_fake_live_title(
        monkeypatch,
        scraper=scraper,
        title_number="21",
        extracted_text="fallback extraction must not be used",
    )
    monkeypatch.setattr(
        oklahoma_title,
        "extract_oklahoma_title_pdf_text",
        lambda _payload: operative_text,
    )

    rows = await scraper.scrape_code(
        code_info["name"], code_info["url"], max_statutes=5
    )

    assert [row.section_number for row in rows] == ["21-1.1"]
    assert rows[0].structured_data["extraction_method"] == (
        "oklahoma_title.extract_oklahoma_title_pdf_text"
    )


@pytest.mark.anyio
async def test_live_fake_title_33_closes_with_typed_official_zero_frontier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = OklahomaScraper("OK", "Oklahoma")
    code_info = next(
        item for item in scraper.get_code_list() if item["title_number"] == "33"
    )
    _install_fake_live_title(
        monkeypatch,
        scraper=scraper,
        title_number="33",
        extracted_text="""
        § 33-1. Repealed by Laws 1965, c. 1, § 1.
        Repealed by Laws 1965, c. 1, § 1.
        § 33-2. Repealed by Laws 1965, c. 2, § 2.
        Repealed by Laws 1965, c. 2, § 2.
        § 33-3. Repealed by Laws 1965, c. 3, § 3.
        Repealed by Laws 1965, c. 3, § 3.
        § 33-4. Repealed by Laws 1965, c. 4, § 4.
        Repealed by Laws 1965, c. 4, § 4.
        """,
    )

    rows = await scraper.scrape_code(
        code_info["name"], code_info["url"], max_statutes=5
    )
    exclusion = scraper._closed_zero_result_code_exclusion(code_info)

    assert rows == []
    assert exclusion is not None
    assert exclusion["disposition"] == "repealed"
    assert exclusion["inactive_section_count"] == 4
    assert exclusion["source_frontier_expected_titles"] == 89
    assert exclusion["source_frontier_url"] == scraper.OFFICIAL_ENTRY_URL
    assert scraper._validate_closed_zero_result_code_exclusion(
        code_info, exclusion
    ) == exclusion


def test_fetch_official_requires_and_closes_exact_89_pdf_toc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = OklahomaScraper("OK", "Oklahoma")
    toc = _complete_toc_html()
    monkeypatch.setattr(scraper, "_official_http_get", lambda *_args, **_kwargs: toc)

    fetched = scraper.fetch_official("OK")

    assert len(fetched.rows) == 89
    assert fetched.response_bytes == toc
    assert fetched.source_domain == "www.oklegislature.gov"
    assert fetched.source_path == "/osstatuestitle.html"
    assert fetched.frontier["bundle_closed"] is True
    assert fetched.frontier["method"] == "complete_title_pdf_toc"
    assert fetched.frontier["expected_index_units"] == 89
    assert fetched.frontier["visited_index_units"] == 89
    assert all(row["frontier_member_observed"] is True for row in fetched.rows)

    incomplete = toc.replace(
        f'<a href="{title_pdf_url("33")}">Title 33 - Inebriates</a>'.encode(),
        b"",
    )
    monkeypatch.setattr(
        scraper, "_official_http_get", lambda *_args, **_kwargs: incomplete
    )
    with pytest.raises(RuntimeError, match="incomplete 89-PDF frontier"):
        scraper.fetch_official("OK")
