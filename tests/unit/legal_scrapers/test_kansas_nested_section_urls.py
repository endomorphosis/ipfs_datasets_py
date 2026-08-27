from __future__ import annotations

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.kansas import (
    KansasScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.kansas_section import (
    classify_kansas_terminal_section_html,
    parse_kansas_section_html,
    section_rows,
)


ARTICLE_URL = (
    "https://www.kslegislature.gov/b2025_26/laws/"
    "025_000_0000_chapter/025_021_0000_article/"
)
SECTION_PATH = (
    "025_000_0000_chapter/025_021_0000_article/025_021_0001_section/025_021_0001_k/"
)


def _article_html(href: str) -> str:
    return (
        '<table id="statute"><tr><td><a href="'
        f'{href}">25-2101 - Official Kansas section</a></td></tr></table>'
    )


def test_kansas_nested_article_resolves_parent_relative_section_exactly() -> None:
    rows = section_rows(
        _article_html(f"../../{SECTION_PATH}"),
        base_url=ARTICLE_URL,
    )

    assert rows == [
        (
            "25-2101",
            "25-2101 - Official Kansas section",
            f"https://www.kslegislature.gov/b2025_26/laws/{SECTION_PATH}",
        )
    ]
    assert "_article/025_000_0000_chapter/" not in rows[0][2]


def test_kansas_section_rows_preserves_alphanumeric_source_token() -> None:
    article_url = (
        "https://www.kslegislature.gov/b2025_26/laws/"
        "013_000_0000_chapter/013_006_0000_article/"
    )
    path = (
        "013_000_0000_chapter/013_006_0000_article/"
        "013_006_0028a_section/013_006_0028a_k/"
    )

    rows = section_rows(
        _article_html(f"../../{path}").replace("25-2101", "13-628a"),
        base_url=article_url,
    )

    assert rows == [
        (
            "13-628a",
            "13-628a - Official Kansas section",
            f"https://www.kslegislature.gov/b2025_26/laws/{path}",
        )
    ]


def test_kansas_section_rows_preserves_distinct_comma_cites() -> None:
    article_url = (
        "https://www.kslegislature.gov/b2025_26/laws/"
        "017_000_0000_chapter/017_078_0000_article/"
    )
    rows = section_rows(
        """
        <table id="statute">
          <tr><td><a href="../../017_000_0000_chapter/017_078_0000_article/017_078_0101_section/017_078_0101_k/">17-78,101 - First.</a></td></tr>
          <tr><td><a href="../../017_000_0000_chapter/017_078_0000_article/017_078_0102_section/017_078_0102_k/">17-78,102 - Second.</a></td></tr>
        </table>
        """,
        base_url=article_url,
    )

    assert [row[0] for row in rows] == ["17-78,101", "17-78,102"]
    assert len({row[2] for row in rows}) == 2


@pytest.mark.parametrize(
    "href",
    [
        f"https://example.test/b2025_26/laws/{SECTION_PATH}",
        f"https://www.kslegislature.gov/b2023_24/laws/{SECTION_PATH}",
        f"../../{SECTION_PATH}?copy=1",
        f"../../{SECTION_PATH}#copy",
    ],
)
def test_kansas_section_rows_rejects_noncanonical_resolved_identity(
    href: str,
) -> None:
    assert section_rows(_article_html(href), base_url=ARTICLE_URL) == []


def test_kansas_partial_repeal_caption_is_operative_and_accepts_p1_body() -> None:
    html = """
    <div class="statute-body">
      <table><tr><td>navigation</td></tr></table>
      <table><tr><td><p class="P1">
        <span class="stat_5f_number">66-1,133.</span>
        <span class="stat_5f_caption">Sections K.S.A. 66-196 through
        66-1,107 repealed in part.</span>
        All inconsistent parts of the earlier enactments are hereby repealed,
        while this codified public-law provision remains operative text.
      </p></td></tr></table>
      <table><tr><td><p class="p_pt">History: L. 1931, ch. 236, § 26.</p></td></tr></table>
    </div>
    """

    row = parse_kansas_section_html(
        html,
        source_url="https://www.kslegislature.gov/laws/66-1-133/",
    )

    assert row is not None
    assert row.section_number == "66-1,133"
    assert "remains operative text" in row.full_text
    assert classify_kansas_terminal_section_html(html) == ""


def test_kansas_exact_terminal_caption_is_excluded() -> None:
    html = """
    <div class="statute-body">
      <table><tr><td>navigation</td></tr></table>
      <table><tr><td><p>
        <span class="stat_5f_number">1-999.</span>
        <span class="stat_5f_caption">Repealed.</span>
      </p></td></tr></table>
    </div>
    """

    assert classify_kansas_terminal_section_html(html) == "repealed"
    assert parse_kansas_section_html(html, source_url="https://example.test/") is None


def test_kansas_split_number_spans_preserve_suffix_identity() -> None:
    html = """
    <div class="statute-body">
      <table><tr><td>navigation</td></tr></table>
      <table><tr><td><p class="P1">
        <span class="stat_5f_number">3-144</span>
        <span class="stat_5f_number"><span class="T1">l</span></span>
        <span class="stat_5f_number"><span class="T2">.</span></span>
        <span class="stat_5f_caption">Sale of an airport.</span>
        This official provision contains enough operative statutory text to
        preserve the source identity and normalized body without truncation.
      </p></td></tr></table>
    </div>
    """

    row = parse_kansas_section_html(html, source_url="https://example.test/")

    assert row is not None
    assert row.section_number == "3-144l"


def test_kansas_nested_number_spans_are_not_double_counted() -> None:
    html = """
    <div class="statute-body">
      <table><tr><td>navigation</td></tr></table>
      <table><tr><td><p class="P1">
        <span class="stat_5f_number"><span class="stat_5f_number">8-143</span></span>
        <span class="stat_5f_number"><span class="stat_5f_number"><span class="T1">l</span></span></span>
        <span class="stat_5f_number"><span class="stat_5f_number">.</span></span>
        <span class="stat_5f_caption">Auction transport permits.</span>
        This official provision contains enough operative statutory text to
        preserve its complete nested-span source identity during normalization.
      </p></td></tr></table>
    </div>
    """

    row = parse_kansas_section_html(html, source_url="https://example.test/")

    assert row is not None
    assert row.section_number == "8-143l"


def test_kansas_catalog_cite_reconciles_separator_only_body_drift() -> None:
    scraper = KansasScraper("KS", "Kansas")
    html = """
    <div class="statute-body">
      <table><tr><td>navigation</td></tr></table>
      <table><tr><td><p class="P1">
        <span class="stat_5f_number">17-78-101.</span>
        <span class="stat_5f_caption">Citation of act.</span>
        This act may be cited as the business entity transactions act and is
        retained verbatim even though the catalog uses a comma separator.
      </p></td></tr></table>
    </div>
    """
    row = parse_kansas_section_html(html, source_url="https://example.test/")
    assert row is not None

    reconciled = scraper._reconcile_kansas_catalog_identity(
        row,
        expected_identity="17-78,101",
        source_url="https://example.test/",
    )

    assert reconciled.section_number == "17-78,101"
    assert reconciled.official_cite == "K.S.A. § 17-78,101"
    assert reconciled.structured_data["source_body_section_number"] == "17-78-101"
    assert reconciled.structured_data["source_identity_reconciliation"] == (
        "separator_only"
    )
    assert "comma separator" in reconciled.full_text


def test_kansas_catalog_cite_rejects_nonseparator_identity_drift() -> None:
    scraper = KansasScraper("KS", "Kansas")
    row = parse_kansas_section_html(
        """
        <div class="statute-body">
          <table><tr><td>navigation</td></tr></table>
          <table><tr><td><p>
            <span class="stat_5f_number">17-78-102.</span>
            <span class="stat_5f_caption">Different section.</span>
            This operative body is intentionally long enough for parsing and
            must not be rebound to a different alphanumeric source identity.
          </p></td></tr></table>
        </div>
        """,
        source_url="https://example.test/",
    )
    assert row is not None

    with pytest.raises(RuntimeError, match="changed catalog identity"):
        scraper._reconcile_kansas_catalog_identity(
            row,
            expected_identity="17-78,101",
            source_url="https://example.test/",
        )


def test_kansas_page_metadata_disambiguates_contextual_appendix_marker() -> None:
    scraper = KansasScraper("KS", "Kansas")
    html = """
    <html><head>
      <meta content="97-2201" name="T_KSASECTEXT_S_KSANUM">
    </head><body><div class="statute-body">
      <table><tr><td>navigation</td></tr></table>
      <table><tr><td><p>
        <span class="stat_5f_number">§ 1.</span>
        <span class="stat_5f_caption">Limitation on presidential terms.</span>
        This official appendix provision is long enough to remain a complete
        normalized public-law source body under its global catalog identity.
      </p></td></tr></table>
    </div></body></html>
    """
    row = parse_kansas_section_html(
        html,
        source_url="https://example.test/97-2201/",
        section_number="97-2201",
    )
    assert row is not None

    reconciled = scraper._reconcile_kansas_catalog_identity(
        row,
        expected_identity="97-2201",
        source_url="https://example.test/97-2201/",
    )

    assert reconciled.section_number == "97-2201"
    assert reconciled.chapter_number == "97"
    assert reconciled.structured_data["source_body_section_number"] == "§ 1"
    assert reconciled.structured_data["source_page_section_number"] == "97-2201"
    assert reconciled.structured_data["source_identity_reconciliation"] == (
        "page_metadata_confirms_catalog"
    )


def test_kansas_aggregate_body_is_one_row_with_nonduplicated_covered_cites() -> None:
    scraper = KansasScraper("KS", "Kansas")
    html = """
    <html><head>
      <meta content="76-114, 76-115" name="T_KSASECTEXT_S_KSANUM">
    </head><body><div class="statute-body">
      <table><tr><td>navigation</td></tr></table>
      <table><tr><td><p>
        <span class="stat_5f_number">76-114, 76-115.</span>
        <span class="stat_5f_caption">Oil and gas well contracts.</span>
        The official source deliberately combines both covered section
        identities into this single retained public-law body.
      </p></td></tr></table>
    </div></body></html>
    """
    row = parse_kansas_section_html(
        html,
        source_url="https://example.test/76-114/",
        section_number="76-114",
    )
    assert row is not None

    reconciled = scraper._reconcile_kansas_catalog_identity(
        row,
        expected_identity="76-114",
        source_url="https://example.test/76-114/",
        catalog_identity_keys={scraper._kansas_identity_key("76-114")},
    )

    assert reconciled.section_number == "76-114"
    assert reconciled.structured_data["source_covered_section_numbers"] == [
        "76-114",
        "76-115",
    ]
    assert reconciled.structured_data["source_aggregate_kind"] == "explicit_list"
    assert reconciled.structured_data["source_identity_reconciliation"] == (
        "aggregate_catalog_entry"
    )


def test_kansas_aggregate_body_rejects_a_separately_cataloged_member() -> None:
    scraper = KansasScraper("KS", "Kansas")
    row = parse_kansas_section_html(
        """
        <html><head>
          <meta content="75-2125 to 75-2129" name="T_KSASECTEXT_S_KSANUM">
        </head><body><div class="statute-body">
          <table><tr><td>navigation</td></tr></table>
          <table><tr><td><p>
            <span class="stat_5f_number">75-2125 </span>
            <span class="stat_5f_number">through</span>
            <span class="stat_5f_number"> 75-2129.</span>
            <span class="stat_5f_caption">Sale of state land.</span>
            This official body covers the complete bounded section range and
            remains long enough for strict normalization.
          </p></td></tr></table>
        </div></body></html>
        """,
        source_url="https://example.test/75-2125/",
        section_number="75-2125",
    )
    assert row is not None

    with pytest.raises(RuntimeError, match="separately cataloged"):
        scraper._reconcile_kansas_catalog_identity(
            row,
            expected_identity="75-2125",
            source_url="https://example.test/75-2125/",
            catalog_identity_keys={
                scraper._kansas_identity_key("75-2125"),
                scraper._kansas_identity_key("75-2127"),
            },
        )


def test_kansas_aggregate_body_expands_observed_letter_suffix_range() -> None:
    scraper = KansasScraper("KS", "Kansas")
    source_url = (
        "https://www.kslegislature.gov/laws/075_000_0000_chapter/"
        "075_021_0000_article/075_021_0029a_section/075_021_0029a_k/"
    )
    row = parse_kansas_section_html(
        """
        <html><head>
          <meta content="75-2129a to 75-2129e" name="T_KSASECTEXT_S_KSANUM">
        </head><body><div class="statute-body">
          <table><tr><td>navigation</td></tr></table>
          <table><tr><td><p>
            <span class="stat_5f_number">75-2129a </span>
            <span class="stat_5f_number">through</span>
            <span class="stat_5f_number"> 75-2129e.</span>
            <span class="stat_5f_caption">Sale of certain land.</span>
            L. 1959, ch. 343, sections 1 to 5, included by reference.
          </p></td></tr></table>
        </div></body></html>
        """,
        source_url=source_url,
        section_number="75-2129a",
    )
    assert row is not None

    reconciled = scraper._reconcile_kansas_catalog_identity(
        row,
        expected_identity="75-2129a",
        source_url=source_url,
        catalog_identity_keys={
            scraper._kansas_identity_key("75-2129a"),
            scraper._kansas_identity_key("75-2129f"),
        },
    )

    assert reconciled.section_number == "75-2129a"
    assert reconciled.structured_data["source_aggregate_kind"] == (
        "inclusive_alpha_suffix_range"
    )
    assert reconciled.structured_data["source_covered_section_numbers"] == [
        "75-2129a",
        "75-2129b",
        "75-2129c",
        "75-2129d",
        "75-2129e",
    ]
    assert reconciled.structured_data["source_identity_reconciliation"] == (
        "aggregate_catalog_entry"
    )


def test_kansas_front_matter_meta_exception_is_exact_url_bound() -> None:
    scraper = KansasScraper("KS", "Kansas")
    html = """
    <html><head>
      <meta content="94-100" name="T_KSASECTEXT_S_KSANUM">
    </head><body><div class="statute-body">
      <table><tr><td>navigation</td></tr></table>
      <table><tr><td><p>
        List of amendments and proposed amendments to the Kansas Constitution,
        retained as one official catalog front-matter document.
      </p></td></tr></table>
    </div></body></html>
    """
    source_url = (
        "https://www.kslegislature.gov/b2025_26/laws/"
        "094_000_0000_chapter/094_000_0000_article/"
        "094_000_0000_section/094_000_0000_k/"
    )
    row = parse_kansas_section_html(
        html,
        source_url=source_url,
        section_number="94-00",
    )
    assert row is not None
    reconciled = scraper._reconcile_kansas_catalog_identity(
        row,
        expected_identity="94-00",
        source_url=source_url,
    )
    assert reconciled.structured_data["source_identity_reconciliation"] == (
        "catalog_front_matter_meta_exception"
    )

    with pytest.raises(RuntimeError, match="page metadata changed"):
        scraper._reconcile_kansas_catalog_identity(
            row,
            expected_identity="94-00",
            source_url="https://example.test/not-the-catalog-document/",
        )
