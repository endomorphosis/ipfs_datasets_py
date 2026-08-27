from __future__ import annotations

import hashlib
from typing import Optional
from urllib.parse import urlsplit

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_source_policy import (
    get_official_source_catalog,
)
from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import (
    _filter_strict_full_text_statutes,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import hawaii_section
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    BaseStateScraper,
    NormalizedStatute,
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.hawaii import (
    HawaiiScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.hawaii_section import (
    HAWAII_EXPECTED_OPERATIVE_SECTION_COUNT,
    HAWAII_EXPECTED_OPERATIVE_SECTION_INVENTORY_SHA256,
    HAWAII_EXPECTED_TOTAL_SECTION_LOCATOR_COUNT,
    is_source_bound_nonoperative_hawaii_section_html,
    is_source_bound_operative_hawaii_statute,
    nonoperative_chapter_marker_url,
    nonoperative_hawaii_chapter_disposition,
    nonoperative_hawaii_section_disposition,
    parse_hawaii_section_html,
    section_number_from_url,
)


def _section_html(number: str, name: str = "Definitions", body: str = "") -> str:
    enacted = body or (
        "The following official statutory rule applies throughout this chapter "
        "and binds every person within the jurisdiction."
    )
    return (
        "<html><body><p>ARTICLE 1</p><p>GENERAL PROVISIONS</p>"
        f"<p>§{number} {name}. {enacted} [L 2024, c 1, §1]</p>"
        "<p>Case Notes</p><p>Publisher annotation must not be included.</p>"
        "</body></html>"
    )


def _seal_hawaii_operative_row(row: NormalizedStatute) -> NormalizedStatute:
    structured = dict(getattr(row, "structured_data", {}) or {})
    structured.update(
        {
            "frontier_closed": True,
            "frontier_section_locator_count": (
                HAWAII_EXPECTED_TOTAL_SECTION_LOCATOR_COUNT
            ),
            "frontier_operative_section_count": (
                HAWAII_EXPECTED_OPERATIVE_SECTION_COUNT
            ),
            "frontier_operative_section_inventory_sha256": (
                HAWAII_EXPECTED_OPERATIVE_SECTION_INVENTORY_SHA256
            ),
        }
    )
    row.structured_data = structured
    return row


def _chapter_autoindex(chapter_url: str, *, extra_link: str = "") -> str:
    parsed = urlsplit(chapter_url)
    path = parsed.path if parsed.path.endswith("/") else f"{parsed.path}/"
    chapter = path.rstrip("/").rsplit("/HRS", 1)[-1]
    volume_path = path.rstrip("/").rsplit("/", 1)[0] + "/"
    identity = f"{parsed.hostname} - {path}"
    return (
        f"<html><head><title>{identity}</title></head><body><h1>{identity}</h1>"
        f"<a href='{volume_path}'>[To Parent Directory]</a>"
        f"<a href='{path}HRS_{chapter}-.htm'>HRS_{chapter}-.htm</a>"
        f"{extra_link}</body></html>"
    )


def _chapter_sentinel_html(
    chapter: str,
    volume: str,
    *,
    disposition: str = "repealed",
    extra_body: str = "",
    extra_link: str = "",
) -> str:
    printed = chapter.lstrip("0") or "0"
    marker = (
        f"<p>CHAPTER {printed}</p><p>REPEALED. L 2024, c 1, §1.</p>"
        if disposition == "repealed"
        else f"<p>[CHAPTER {printed} RESERVED.]</p>"
    )
    return (
        f"<html><body>{marker}{extra_body}"
        f"<a href='../../{volume}/HRS0431/HRS_0431-0001-0001.htm'>Previous</a>"
        f"<a href='../../{volume}'>{volume}</a>"
        f"<a href='../../{volume}/HRS0431/HRS_0431-0002-0001.htm'>Next</a>"
        f"{extra_link}</body></html>"
    )


def _reserved_article_html(*, extra_article: str = "", extra_link: str = "") -> str:
    return (
        "<html><head><title>ARTICLE 18</title></head><body>"
        "<div class='WordSection1'><p>ARTICLE 18</p><p>[RESERVED]</p>"
        f"{extra_article}</div><div id='pageLinks'>"
        "<a href='../../Vol09_Ch0431-0435H/HRS0431/"
        "HRS_0431-0017-0101.htm'>Previous</a>"
        "<a href='../../Vol09_Ch0431-0435H'>Vol09_Ch0431-0435H</a>"
        "<a href='../../Vol09_Ch0431-0435H/HRS0431/"
        "HRS_0431-0019-0101.htm'>Next</a>"
        f"{extra_link}</div></body></html>"
    )


def _official_section_html(
    source_url: str,
    paragraphs: list[str],
    *,
    extra_link: str = "",
) -> str:
    parsed = urlsplit(source_url)
    volume = parsed.path.split("/")[2]
    chapter_path = parsed.path.rsplit("/", 1)[0]
    return (
        "<html><body><div class='WordSection1'>"
        + "".join(f"<p>{paragraph}</p>" for paragraph in paragraphs)
        + "</div><div id='pageLinks'>"
        + f"<a href='{chapter_path}/HRS_0001-0001.htm'>Previous</a>"
        + f"<a href='/hrscurrent/{volume}'>{volume}</a>"
        + f"<a href='{chapter_path}/HRS_0001-0011.htm'>Next</a>"
        + extra_link
        + "</div></body></html>"
    )


def test_hawaii_uses_official_static_data_host() -> None:
    scraper = HawaiiScraper("HI", "Hawaii")

    assert scraper.get_code_list()[0]["url"] == scraper.OFFICIAL_DATA_ENTRY_URL
    assert scraper.is_official_hi_url(scraper.OFFICIAL_DATA_ENTRY_URL)
    assert not scraper.is_official_hi_url("https://law.justia.com/codes/hawaii/")

    hawaii = get_official_source_catalog().get("HI")
    assert hawaii is not None
    assert "data.capitol.hawaii.gov" in hawaii.acquisition_paths[0].allowed_domains


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://data.capitol.hawaii.gov/x/HRS_0001B-0001.htm", "1B-1"),
        ("https://data.capitol.hawaii.gov/x/HRS_0010-0014_0005_0005.htm", "10-14.55"),
        ("https://data.capitol.hawaii.gov/x/HRS_0412-0001-0100.htm", "412:1-100"),
        ("https://data.capitol.hawaii.gov/x/HRS_0431-0002-0201_0005.htm", "431:2-201.5"),
        ("https://data.capitol.hawaii.gov/x/HRS_0291-0024%C2%AD_0004.htm", "291-24.4"),
        ("https://data.capitol.hawaii.gov/x/HRS_0431-0009A-0101_[OLD].htm", "431:9A-101"),
        ("https://data.capitol.hawaii.gov/x/HRS_0663E-0010.docx.htm", "663E-10"),
    ],
)
def test_hawaii_decodes_every_official_filename_family(url: str, expected: str) -> None:
    assert section_number_from_url(url) == expected


def test_hawaii_parser_skips_article_headings_keeps_complete_enacted_text() -> None:
    body = "A" * 15050
    source_url = (
        "https://data.capitol.hawaii.gov/hrscurrent/Vol08_Ch0401-0429/"
        "HRS0412/HRS_0412-0001-0100.htm"
    )

    statute = parse_hawaii_section_html(
        _section_html("412:1-100", "Short title", body),
        source_url=source_url,
    )

    assert statute is not None
    assert statute.section_number == "412:1-100"
    assert statute.section_name == "Short title"
    assert len(statute.full_text) == len(body)
    assert "[L 2024" not in statute.full_text
    assert "Publisher annotation" not in statute.full_text


def test_hawaii_parser_strips_history_at_end_of_later_body_paragraph() -> None:
    html = (
        "<html><body><p>§1B-1 Rural areas. (a) First operative paragraph.</p>"
        "<p>(b) Second operative paragraph. [L 2013, c 144, §2]</p>"
        "<p>Case Notes</p></body></html>"
    )
    statute = parse_hawaii_section_html(
        html,
        source_url="https://data.capitol.hawaii.gov/x/HRS_0001B-0001.htm",
    )

    assert statute is not None
    assert "Second operative paragraph" in statute.full_text
    assert "[L 2013" not in statute.full_text


@pytest.mark.parametrize(
    ("source_url", "printed_heading", "expected"),
    [
        (
            "https://data.capitol.hawaii.gov/x/HRS_0005-0015_0007.htm",
            "[§5 -15.7] State limu",
            "5-15.7",
        ),
        (
            "https://data.capitol.hawaii.gov/x/HRS_0008-0036.htm",
            "[§8- 36] La Kuokoa",
            "8-36",
        ),
        (
            "https://data.capitol.hawaii.gov/x/HRS_0431-0010A-0122.htm",
            "[§431: 10A-122] Colon cancer screening coverage",
            "431:10A-122",
        ),
        (
            "https://data.capitol.hawaii.gov/x/HRS_0006F-0007.htm",
            "[§6F‑7] Judiciary history center trust fund",
            "6F-7",
        ),
        (
            "https://data.capitol.hawaii.gov/x/HRS_0206E-0241.htm",
            "§2 06E- 241 Findings and purpose",
            "206E-241",
        ),
        (
            "https://data.capitol.hawaii.gov/x/HRS_0431-0003-0203_0005.htm",
            "§431:3-203 . 5 Foreign insurer; certification",
            "431:3-203.5",
        ),
    ],
)
def test_hawaii_parser_reconciles_official_heading_typography_to_filename_identity(
    source_url: str,
    printed_heading: str,
    expected: str,
) -> None:
    html = (
        f"<html><body><p>{printed_heading}. The official enacted body applies.</p>"
        "</body></html>"
    )

    statute = parse_hawaii_section_html(html, source_url=source_url)

    assert statute is not None
    assert statute.section_number == expected
    assert statute.statute_id == f"Hawaii Revised Statutes § {expected}"


def test_hawaii_parser_selects_filename_matching_heading_after_cross_references() -> None:
    source_url = (
        "https://data.capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/"
        "HRS0037/HRS_0037-0051.htm"
    )
    html = (
        "<html><body><p>PART III. BUDGETARY CONTROL OF SPECIAL FUNDS</p>"
        "<p>Cross References</p>"
        "<p>Establishing new accounts annually, see §40-89.</p>"
        "<p>§37-51 Abolition of special funds; legislative purpose. "
        "The official enacted body remains in force. [L 1957, c 320, §1]</p>"
        "<p>Case Notes</p></body></html>"
    )

    statute = parse_hawaii_section_html(html, source_url=source_url)

    assert statute is not None
    assert statute.section_number == "37-51"
    assert statute.section_name == "Abolition of special funds; legislative purpose"
    assert "official enacted body" in statute.full_text
    assert "Establishing new accounts" not in statute.full_text


def test_hawaii_parser_binds_hre_rule_heading_to_exact_filename_identity() -> None:
    source_url = (
        "https://data.capitol.hawaii.gov/hrscurrent/Vol13_Ch0601-0676/"
        "HRS0626/HRS_0626-0001-0100.htm"
    )
    html = (
        "<html><body><p>HAWAII RULES OF EVIDENCE</p><p>ARTICLE I.</p>"
        "<p>GENERAL PROVISIONS</p><p>Rule 100 Title and citation. "
        "These rules shall be cited by their number. [L 1980, c 164, pt of §1]</p>"
        "<p>RULE 100 COMMENTARY</p><p>Publisher commentary.</p></body></html>"
    )

    statute = parse_hawaii_section_html(html, source_url=source_url)

    assert statute is not None
    assert statute.section_number == "626:1-100"
    assert statute.section_name == "Title and citation"
    assert statute.full_text == "These rules shall be cited by their number."
    assert "COMMENTARY" not in statute.full_text

    mismatch_url = source_url.replace("0100.htm", "0101.htm")
    assert parse_hawaii_section_html(html, source_url=mismatch_url) is None


def test_hawaii_parser_source_bound_printed_citation_mismatch_fails_on_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_url = (
        "https://data.capitol.hawaii.gov/hrscurrent/Vol13_Ch0601-0676/"
        "HRS0634G/HRS_0634G-0002.htm"
    )
    html = (
        "<html><body><p>[§643G-2] Scope of chapter. "
        "The official enacted body applies.</p></body></html>"
    )
    monkeypatch.setattr(
        hawaii_section,
        "_SOURCE_BOUND_SECTION_CITATION_MISMATCHES",
        {
            source_url: {
                "content_sha256": hashlib.sha256(html.encode()).hexdigest(),
                "printed_section": "643G-2",
            }
        },
    )

    statute = parse_hawaii_section_html(html, source_url=source_url)
    assert statute is not None
    assert statute.section_number == "634G-2"
    assert statute.section_name == "Scope of chapter"

    assert parse_hawaii_section_html(f"{html} ", source_url=source_url) is None
    assert parse_hawaii_section_html(html, source_url=f"{source_url}?copy=1") is None

    printed_drift = html.replace("643G-2", "643G-3")
    monkeypatch.setattr(
        hawaii_section,
        "_SOURCE_BOUND_SECTION_CITATION_MISMATCHES",
        {
            source_url: {
                "content_sha256": hashlib.sha256(printed_drift.encode()).hexdigest(),
                "printed_section": "643G-2",
            }
        },
    )
    assert parse_hawaii_section_html(printed_drift, source_url=source_url) is None


def test_hawaii_parser_rejects_unbound_official_filename_heading_mismatch() -> None:
    source_url = "https://data.capitol.hawaii.gov/x/HRS_0634G-0002.htm"
    html = (
        "<html><body><p>[§643G-2] Scope of chapter. "
        "The official enacted body applies.</p></body></html>"
    )

    assert parse_hawaii_section_html(html, source_url=source_url) is None


@pytest.mark.parametrize(
    ("source_url", "number", "name", "body"),
    [
        (
            (
                "https://data.capitol.hawaii.gov/hrscurrent/Vol14_Ch0701-0853/"
                "HRS0846/HRS_0846-0054.htm"
            ),
            "846-54",
            "Annual reports",
            (
                "The attorney general shall transmit an annual report to the "
                "governor and the legislature."
            ),
        ),
        (
            (
                "https://data.capitol.hawaii.gov/hrscurrent/Vol14_Ch0701-0853/"
                "HRS0846E/HRS_0846E-0008.htm"
            ),
            "846E-8",
            "Good faith immunity",
            (
                "Law enforcement agencies and their employees shall be immune "
                "from liability for good faith conduct under this chapter."
            ),
        ),
        (
            (
                "https://data.capitol.hawaii.gov/hrscurrent/Vol14_Ch0701-0853/"
                "HRS0846E/HRS_0846E-0012.htm"
            ),
            "846E-12",
            "Tolling",
            (
                "The time periods shall be tolled while the offender is confined "
                "to a halfway house or equivalent facility."
            ),
        ),
    ],
)
def test_hawaii_source_bound_short_operative_rows_survive_both_quality_filters(
    source_url: str,
    number: str,
    name: str,
    body: str,
) -> None:
    row = parse_hawaii_section_html(
        _section_html(number, name, body),
        source_url=source_url,
    )
    assert row is not None
    scraper = HawaiiScraper("HI", "Hawaii")

    # These are the three exact v8 false positives.  Without the closed
    # source-bound proof, the generic substring heuristic rejects each one.
    assert scraper._is_low_quality_statute_record(row) is True
    _seal_hawaii_operative_row(row)

    assert is_source_bound_operative_hawaii_statute(row)
    assert scraper._is_low_quality_statute_record(row) is False
    kept, removed = _filter_strict_full_text_statutes(
        [row],
        min_full_text_chars=1,
    )
    assert kept == [row]
    assert removed == 0


@pytest.mark.parametrize(
    ("chapter", "file_suffix", "number"),
    [
        ("0412", "0013-0221", "412:13-221"),
        ("0431", "0002-0304", "431:2-304"),
        ("0431", "0003-0309", "431:3-309"),
        ("0431", "0004-0208", "431:4-208"),
        ("0431", "0004-0314", "431:4-314"),
        ("0431", "0008-0313", "431:8-313"),
        ("0431", "0010A-0119", "431:10A-119"),
        ("0431", "0010A-0408", "431:10A-408"),
        ("0431", "0010E-0142", "431:10E-142"),
        ("0431", "0030-0111", "431:30-111"),
        ("0432", "0001-0608", "432:1-608"),
    ],
)
def test_hawaii_source_bound_colon_sections_survive_strict_calendar_heuristic(
    chapter: str,
    file_suffix: str,
    number: str,
) -> None:
    volume = (
        "Vol08_Ch0401-0429" if chapter == "0412" else "Vol09_Ch0431-0435H"
    )
    source_url = (
        f"https://data.capitol.hawaii.gov/hrscurrent/{volume}/HRS{chapter}/"
        f"HRS_{chapter}-{file_suffix}.htm"
    )
    row = parse_hawaii_section_html(
        _section_html(
            number,
            "Official calendar provision",
            "The annual calendar shall govern every required filing and report.",
        ),
        source_url=source_url,
    )
    assert row is not None
    scraper = HawaiiScraper("HI", "Hawaii")
    assert scraper._is_low_quality_statute_record(row) is True
    assert _filter_strict_full_text_statutes(
        [row],
        min_full_text_chars=1,
    ) == ([], 1)

    _seal_hawaii_operative_row(row)

    assert scraper._is_low_quality_statute_record(row) is False
    assert _filter_strict_full_text_statutes(
        [row],
        min_full_text_chars=1,
    ) == ([row], 0)


def test_hawaii_source_bound_operative_admission_rejects_every_proof_drift() -> None:
    source_url = (
        "https://data.capitol.hawaii.gov/hrscurrent/Vol14_Ch0701-0853/"
        "HRS0846E/HRS_0846E-0012.htm"
    )
    row = parse_hawaii_section_html(
        _section_html(
            "846E-12",
            "Tolling",
            "The period is tolled while confined to a halfway house.",
        ),
        source_url=source_url,
    )
    assert row is not None
    _seal_hawaii_operative_row(row)
    assert is_source_bound_operative_hawaii_statute(row)

    base = row.to_dict()
    variants = []
    for field, value in (
        ("source_url", source_url.replace("data.capitol", "example")),
        ("section_number", "846E-13"),
        ("statute_id", "Hawaii Revised Statutes § 846E-13"),
        ("official_cite", "Haw. Rev. Stat. § 846E-13"),
        ("full_text", "Section Section-1: placeholder navigation"),
    ):
        variant = {**base, field: value}
        variants.append(variant)
    for field, value in (
        ("source_kind", "official_hawaii_emergency_stub"),
        ("source_authority_class", "mirror"),
        ("discovery_method", "link_guess"),
        ("frontier_closed", False),
        ("frontier_section_locator_count", 22_972),
        ("frontier_operative_section_count", 22_599),
        ("frontier_operative_section_inventory_sha256", "0" * 64),
    ):
        variant = dict(base)
        variant["structured_data"] = dict(base["structured_data"])
        variant["structured_data"][field] = value
        variants.append(variant)

    assert all(
        not is_source_bound_operative_hawaii_statute(variant)
        for variant in variants
    )


@pytest.mark.anyio
async def test_hawaii_transport_failure_uses_shared_web_archiving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://data.capitol.hawaii.gov/hrscurrent/example.htm"
    html = _section_html("1-1").encode()

    async def _no_cache(self, candidate: str) -> bytes:
        return b""

    async def _archival(
        self,
        candidate: str,
        timeout_seconds: int = 25,
    ) -> bytes:
        assert candidate == url
        self._record_fetch_event(provider="common_crawl", success=True)
        return html

    async def _direct_miss(self, candidate: str, **kwargs: object) -> bytes:
        assert candidate == url
        assert kwargs["allow_archival_fallback"] is False
        return b""

    monkeypatch.setattr(HawaiiScraper, "_load_page_bytes_from_any_cache", _no_cache)
    monkeypatch.setattr(
        BaseStateScraper,
        "_fetch_parser_input_with_transport",
        _direct_miss,
    )
    monkeypatch.setattr(
        BaseStateScraper,
        "_fetch_page_content_with_archival_fallback",
        _archival,
    )

    scraper = HawaiiScraper("HI", "Hawaii")
    recovered = await scraper._fetch_official_hi_html(url, timeout_seconds=1)

    assert "§1-1" in recovered
    assert scraper._hi_fetch_provenance()[url] == "common_crawl"


@pytest.mark.anyio
async def test_hawaii_bounded_tree_discovers_complex_section_filename(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = HawaiiScraper.OFFICIAL_DATA_ENTRY_URL
    volume = f"{root}Vol08_Ch0401-0429/"
    chapter = f"{volume}HRS0412/"
    section = f"{chapter}HRS_0412-0001-0100.htm"
    pages = {
        root: f"<a href='{volume}'>Volume 8</a>",
        volume: f"<a href='{chapter}'>Chapter 412</a>",
        chapter: f"<a href='{section}'>§412:1-100</a>",
        section: _section_html("412:1-100", "Short title"),
    }

    async def _fake_html(self, url: str, timeout_seconds: int = 18) -> str:
        return pages.get(url, "")

    monkeypatch.setattr(HawaiiScraper, "_fetch_official_hi_html", _fake_html)
    scraper = HawaiiScraper("HI", "Hawaii")
    rows = await scraper._scrape_official_hrs_tree(
        code_name="Hawaii Revised Statutes",
        code_url=root,
        max_statutes=1,
    )

    assert [row.section_number for row in rows] == ["412:1-100"]
    assert rows[0].structured_data["frontier_bounded_probe"] is True
    assert rows[0].structured_data["frontier_closed"] is False


@pytest.mark.anyio
async def test_hawaii_uncapped_tree_fails_closed_when_hierarchy_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = HawaiiScraper.OFFICIAL_DATA_ENTRY_URL
    volume = f"{root}Vol01_Ch0001-0042F/"
    chapter = f"{volume}HRS0001/"
    section = f"{chapter}HRS_0001-0001.htm"
    pages = {
        root: f"<a href='{volume}'>Volume 1</a>",
        volume: f"<a href='{chapter}'>Chapter 1</a>",
        chapter: f"<a href='{section}'>§1-1</a>",
        section: _section_html("1-1"),
    }

    async def _fake_html(self, url: str, timeout_seconds: int = 18) -> str:
        return pages.get(url, "")

    plural_calls: list[list[str]] = []

    async def _frontier(self, urls, *, frontier_name: str):
        requested = list(urls)
        plural_calls.append(requested)
        return {url: pages[url] for url in requested}

    monkeypatch.setattr(HawaiiScraper, "_fetch_official_hi_html", _fake_html)
    monkeypatch.setattr(HawaiiScraper, "_fetch_hi_html_frontier", _frontier)
    scraper = HawaiiScraper("HI", "Hawaii")
    rows = await scraper._scrape_official_hrs_tree(
        code_name="Hawaii Revised Statutes",
        code_url=root,
        max_statutes=None,
    )

    assert rows == []
    assert scraper._hawaii_frontier["closed"] is False
    assert scraper._hawaii_frontier["unresolved_count"] == 6
    assert {
        row["kind"] for row in scraper._hawaii_frontier["unresolved"]
    } >= {
        "nonoperative_chapter_inventory_drift",
        "nonoperative_section_inventory_drift",
        "operative_section_inventory_drift",
    }
    assert plural_calls == [[volume], [chapter], [section]]


@pytest.mark.anyio
async def test_hawaii_full_tree_classifies_nonoperative_slot_without_opening_frontier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = HawaiiScraper("HI", "Hawaii")
    url = (
        "https://data.capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/"
        "HRS0001/HRS_0001-0009.htm"
    )
    html = _official_section_html(url, ["§§1-9 to 1-10 REPEALED. L 2024, c 1, §1."])

    async def _fake_html(self, candidate: str, timeout_seconds: int = 18) -> str:
        assert candidate == url
        return html

    monkeypatch.setattr(HawaiiScraper, "_fetch_official_hi_html", _fake_html)
    row: Optional[object] = await scraper._parse_live_section_page(
        code_name="Hawaii Revised Statutes",
        section_url=url,
        section_label="§1-9",
        chapter_label="Chapter 1",
        volume_label="Volume 1",
    )

    assert row is None
    assert scraper._hi_section_outcomes()[url] == "nonoperative"
    observation = scraper._hi_nonoperative_section_observations()[url]
    assert observation["disposition"] == "repealed"
    assert observation["content_sha256"] == hashlib.sha256(html.encode()).hexdigest()


def test_hawaii_group_disposition_requires_exact_url_identity_and_page_shape() -> None:
    url = (
        "https://data.capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/"
        "HRS0001/HRS_0001-0009.htm"
    )
    marker = "§§1-9 to 1-10 REPEALED. L 2024, c 1, §1."
    html = _official_section_html(url, ["PART II. OLD PROVISIONS", marker])

    assert nonoperative_hawaii_section_disposition(html, source_url=url) == "repealed"
    assert (
        nonoperative_hawaii_section_disposition(html, source_url=f"{url}?copy=1")
        is None
    )
    assert (
        nonoperative_hawaii_section_disposition(
            html.replace("§§1-9", "§§1-8"),
            source_url=url,
        )
        is None
    )
    assert (
        nonoperative_hawaii_section_disposition(
            _official_section_html(
                url,
                [marker, "§1-9 This section remains operative."],
            ),
            source_url=url,
        )
        is None
    )
    assert (
        nonoperative_hawaii_section_disposition(
            _official_section_html(
                url,
                [marker],
                extra_link="<a href='unexpected.htm'>extra</a>",
            ),
            source_url=url,
        )
        is None
    )


@pytest.mark.parametrize(
    ("url", "paragraphs"),
    [
        (
            "https://data.capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/"
            + "HRS0011/HRS_0011-0191.htm",
            [
                "B. Election Campaign Contributions",
                "and Expenditures--Repealed",
                "§§11-191 to 11-213 [OLD] REPEALED. L 1979, c 224.",
                "§ §11-191 to 11-225 REPEALED. L 2010, c 211, §9.",
            ],
        ),
        (
            "https://data.capitol.hawaii.gov/hrscurrent/Vol08_Ch0401-0429/"
            + "HRS0425/HRS_0425-0180.htm",
            [
                "PART V. LIMITED LIABILITY PARTNERSHIP ACT--REPEALED",
                "§§425-151 to 425-180 REPEALED. L 2000, c 218, §8.",
                "Note",
                "L 2000, c 219, §§56 to 59 purports to amend §§425-164, "
                + "425-169, 425-171, and 425-172.",
            ],
        ),
    ],
)
def test_hawaii_ambiguous_disposition_is_url_digest_and_shape_bound(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
    paragraphs: list[str],
) -> None:
    html = _official_section_html(url, paragraphs)
    monkeypatch.setattr(
        hawaii_section,
        "_SOURCE_BOUND_NONOPERATIVE_SECTION_DISPOSITIONS",
        {
            url: {
                "content_sha256": hashlib.sha256(html.encode()).hexdigest(),
                "disposition": "repealed",
                "paragraphs": tuple(paragraphs),
            }
        },
    )

    assert nonoperative_hawaii_section_disposition(html, source_url=url) == "repealed"
    assert nonoperative_hawaii_section_disposition(f"{html} ", source_url=url) is None
    assert (
        nonoperative_hawaii_section_disposition(html, source_url=f"{url}?copy=1")
        is None
    )

    shape_drift = [*paragraphs, "Note drift"]
    drift_html = _official_section_html(url, shape_drift)
    monkeypatch.setitem(
        hawaii_section._SOURCE_BOUND_NONOPERATIVE_SECTION_DISPOSITIONS[url],
        "content_sha256",
        hashlib.sha256(drift_html.encode()).hexdigest(),
    )
    assert nonoperative_hawaii_section_disposition(drift_html, source_url=url) is None


def test_hawaii_chapter_tombstone_requires_exact_official_autoindex_and_body() -> None:
    chapter_url = (
        "https://data.capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/"
        "HRS0002/"
    )
    sentinel_url = f"{chapter_url}HRS_0002-.htm"
    directory = _chapter_autoindex(chapter_url)
    sentinel = _chapter_sentinel_html("0002", "Vol01_Ch0001-0042F")

    assert (
        nonoperative_chapter_marker_url(directory, chapter_url=chapter_url)
        == sentinel_url
    )
    assert (
        nonoperative_hawaii_chapter_disposition(
            sentinel,
            sentinel_url=sentinel_url,
        )
        == "repealed"
    )

    assert (
        nonoperative_chapter_marker_url(
            _chapter_autoindex(
                chapter_url,
                extra_link="<a href='HRS_0002-0001.htm'>surviving section</a>",
            ),
            chapter_url=chapter_url,
        )
        is None
    )
    assert (
        nonoperative_chapter_marker_url(
            directory.replace("HRS_0002-.htm", "HRS_0003-.htm"),
            chapter_url=chapter_url,
        )
        is None
    )
    assert (
        nonoperative_hawaii_chapter_disposition(
            _chapter_sentinel_html(
                "0002",
                "Vol01_Ch0001-0042F",
                extra_body="<p>§2-1. This section remains operative.</p>",
            ),
            sentinel_url=sentinel_url,
        )
        is None
    )
    assert (
        nonoperative_hawaii_chapter_disposition(
            _chapter_sentinel_html(
                "0002",
                "Vol01_Ch0001-0042F",
                extra_link="<a href='unexpected.htm'>extra</a>",
            ),
            sentinel_url=sentinel_url,
        )
        is None
    )


def test_hawaii_revision_note_sentinel_is_exact_url_digest_and_shape_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel_url = (
        "https://data.capitol.hawaii.gov/hrscurrent/Vol02_Ch0046-0115/"
        "HRS0070/HRS_0070-.htm"
    )
    html = _chapter_sentinel_html(
        "0070",
        "Vol02_Ch0046-0115",
        extra_body="<p>§70-111 renumbered as §46-74.2.</p>",
    )
    terminal = "REPEALED. L 2024, c 1, §1."
    monkeypatch.setattr(
        hawaii_section,
        "_SOURCE_BOUND_NONOPERATIVE_CHAPTER_SENTINELS",
        {
            sentinel_url: {
                "content_sha256": hashlib.sha256(html.encode()).hexdigest(),
                "terminal_paragraphs": (terminal,),
            }
        },
    )

    assert (
        nonoperative_hawaii_chapter_disposition(
            html,
            sentinel_url=sentinel_url,
        )
        == "repealed"
    )
    assert (
        nonoperative_hawaii_chapter_disposition(
            f"{html} ",
            sentinel_url=sentinel_url,
        )
        is None
    )
    assert (
        nonoperative_hawaii_chapter_disposition(
            html,
            sentinel_url=f"{sentinel_url}?copy=1",
        )
        is None
    )


def test_hawaii_reserved_article_is_exact_url_digest_and_shape_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_url = hawaii_section._SOURCE_BOUND_RESERVED_ARTICLE_URL
    html = _reserved_article_html()
    monkeypatch.setattr(
        hawaii_section,
        "_SOURCE_BOUND_RESERVED_ARTICLE_SHA256",
        hashlib.sha256(html.encode()).hexdigest(),
    )

    assert is_source_bound_nonoperative_hawaii_section_html(
        html,
        source_url=source_url,
    )
    assert not is_source_bound_nonoperative_hawaii_section_html(
        html,
        source_url=f"{source_url}?copy=1",
    )
    assert not is_source_bound_nonoperative_hawaii_section_html(
        f"{html} ",
        source_url=source_url,
    )

    substantive = _reserved_article_html(
        extra_article="<p>§431:18-101. This article is now operative.</p>"
    )
    monkeypatch.setattr(
        hawaii_section,
        "_SOURCE_BOUND_RESERVED_ARTICLE_SHA256",
        hashlib.sha256(substantive.encode()).hexdigest(),
    )
    assert not is_source_bound_nonoperative_hawaii_section_html(
        substantive,
        source_url=source_url,
    )


def test_hawaii_nonoperative_inventory_requires_293_exact_digest_bound_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = HawaiiScraper("HI", "Hawaii")
    observations = [
        {
            "chapter_url": f"https://data.capitol.hawaii.gov/hrscurrent/v/HRS{i:04d}/",
            "directory_sha256": hashlib.sha256(f"directory-{i}".encode()).hexdigest(),
            "disposition": "repealed",
            "sentinel_sha256": hashlib.sha256(f"sentinel-{i}".encode()).hexdigest(),
            "sentinel_url": (
                "https://data.capitol.hawaii.gov/hrscurrent/v/"
                f"HRS{i:04d}/HRS_{i:04d}-.htm"
            ),
        }
        for i in range(1, 294)
    ]
    expected = scraper._nonoperative_chapter_inventory_digest(observations)
    monkeypatch.setattr(
        HawaiiScraper,
        "EXPECTED_NONOPERATIVE_CHAPTER_INVENTORY_SHA256",
        expected,
    )

    assert scraper._nonoperative_chapter_inventory_closed(observations)
    assert not scraper._nonoperative_chapter_inventory_closed(observations[:-1])

    digest_drift = [dict(row) for row in observations]
    digest_drift[17]["sentinel_sha256"] = "0" * 64
    assert not scraper._nonoperative_chapter_inventory_closed(digest_drift)

    url_drift = [dict(row) for row in observations]
    url_drift[17]["sentinel_url"] += "?copy=1"
    assert not scraper._nonoperative_chapter_inventory_closed(url_drift)


def test_hawaii_nonoperative_section_inventory_requires_exact_373_partition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = HawaiiScraper("HI", "Hawaii")
    dispositions = ["repealed"] * 362 + ["reserved"] * 10 + ["renumbered"]
    observations = [
        {
            "content_sha256": hashlib.sha256(f"section-{index}".encode()).hexdigest(),
            "disposition": disposition,
            "source_url": (
                "https://data.capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/"
                f"HRS0001/HRS_0001-{index:04d}.htm"
            ),
        }
        for index, disposition in enumerate(dispositions, start=1)
    ]
    monkeypatch.setattr(
        HawaiiScraper,
        "EXPECTED_NONOPERATIVE_SECTION_INVENTORY_SHA256",
        scraper._nonoperative_section_inventory_digest(observations),
    )

    assert scraper._nonoperative_section_inventory_closed(observations)
    assert not scraper._nonoperative_section_inventory_closed(observations[:-1])

    digest_drift = [dict(row) for row in observations]
    digest_drift[17]["content_sha256"] = "0" * 64
    assert not scraper._nonoperative_section_inventory_closed(digest_drift)

    disposition_drift = [dict(row) for row in observations]
    disposition_drift[-1]["disposition"] = "repealed"
    assert not scraper._nonoperative_section_inventory_closed(disposition_drift)

    url_drift = [dict(row) for row in observations]
    url_drift[17]["source_url"] += "?copy=1"
    assert not scraper._nonoperative_section_inventory_closed(url_drift)


@pytest.mark.anyio
async def test_hawaii_multi_sentinel_batch_is_single_aligned_and_ordered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = HawaiiScraper("HI", "Hawaii")
    volume = "Vol01_Ch0001-0042F"
    chapters = [
        f"{scraper.OFFICIAL_DATA_ENTRY_URL}{volume}/HRS0002/",
        f"{scraper.OFFICIAL_DATA_ENTRY_URL}{volume}/HRS0006/",
    ]
    sentinels = [f"{url}HRS_{url.rstrip('/').rsplit('HRS', 1)[-1]}-.htm" for url in chapters]
    payloads = [
        _chapter_sentinel_html("0002", volume).encode(),
        _chapter_sentinel_html("0006", volume).encode(),
    ]
    scraper._hawaii_nonoperative_chapter_candidates = {
        chapter: {
            "chapter_url": chapter,
            "directory_sha256": hashlib.sha256(chapter.encode()).hexdigest(),
            "sentinel_url": sentinel,
        }
        for chapter, sentinel in zip(chapters, sentinels)
    }
    calls: list[list[str]] = []

    async def _batch(self, urls, **kwargs):
        calls.append(list(urls))
        assert kwargs["prefer_direct"] is True
        return StateLawPageMultiFetchResult(
            urls=list(urls),
            payloads=list(payloads),
            errors=[None, None],
            transport_receipts=[
                {
                    "content_sha256": hashlib.sha256(payload).hexdigest(),
                    "official_url": url,
                    "source_transport": "direct",
                }
                for url, payload in zip(urls, payloads)
            ],
            parser_input_envelopes=[object(), object()],
            stats={"requested_pages": 2},
        )

    monkeypatch.setattr(
        HawaiiScraper,
        "_fetch_page_contents_with_archival_fallback",
        _batch,
    )
    observations, failures = await scraper._resolve_nonoperative_chapters_batch(
        chapters
    )

    assert calls == [sentinels]
    assert failures == []
    assert [row["chapter_url"] for row in observations] == chapters
    assert [row["sentinel_url"] for row in observations] == sentinels

    async def _misaligned(self, urls, **kwargs):
        result = await _batch(self, urls, **kwargs)
        result.urls.reverse()
        return result

    monkeypatch.setattr(
        HawaiiScraper,
        "_fetch_page_contents_with_archival_fallback",
        _misaligned,
    )
    observations, failures = await scraper._resolve_nonoperative_chapters_batch(
        chapters
    )
    assert observations == []
    assert {row["kind"] for row in failures} == {
        "chapter_nonoperative_sentinel_batch_alignment"
    }


@pytest.mark.anyio
async def test_hawaii_293_sentinels_plus_reserved_article_close_exact_frontier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = HawaiiScraper("HI", "Hawaii")
    root = scraper.OFFICIAL_DATA_ENTRY_URL
    volume_name = "Vol09_Ch0431-0435H"
    volume = f"{root}{volume_name}/"
    terminal_chapters = [f"{volume}HRS{i:04d}/" for i in range(1, 294)]
    active_chapter = f"{volume}HRS0431/"
    active_section = f"{active_chapter}HRS_0431-0001-0001.htm"
    reserved_section = hawaii_section._SOURCE_BOUND_RESERVED_ARTICLE_URL
    pages = {
        root: f"<a href='{volume}'>Volume 9</a>",
        volume: "".join(
            f"<a href='{chapter}'>Chapter</a>" for chapter in terminal_chapters
        )
        + f"<a href='{active_chapter}'>Chapter 431</a>",
        active_chapter: (
            f"<a href='{active_section}'>§431:1-1</a>"
            f"<a href='{reserved_section}'>Article 18 reserved</a>"
        ),
        active_section: _section_html("431:1-1"),
        reserved_section: _reserved_article_html(),
    }
    sentinel_payloads: dict[str, bytes] = {}
    observations = []
    for chapter_url in terminal_chapters:
        chapter = chapter_url.rstrip("/").rsplit("HRS", 1)[-1]
        sentinel_url = f"{chapter_url}HRS_{chapter}-.htm"
        directory = _chapter_autoindex(chapter_url)
        payload = _chapter_sentinel_html(chapter, volume_name).encode()
        pages[chapter_url] = directory
        sentinel_payloads[sentinel_url] = payload
        observations.append(
            {
                "chapter_url": chapter_url,
                "directory_sha256": hashlib.sha256(directory.encode()).hexdigest(),
                "disposition": "repealed",
                "sentinel_sha256": hashlib.sha256(payload).hexdigest(),
                "sentinel_url": sentinel_url,
            }
        )

    monkeypatch.setattr(HawaiiScraper, "MIN_EXPECTED_VOLUMES", 1)
    monkeypatch.setattr(HawaiiScraper, "MIN_EXPECTED_CHAPTERS", 294)
    monkeypatch.setattr(HawaiiScraper, "MIN_EXPECTED_SECTION_LOCATORS", 2)
    expected_active = parse_hawaii_section_html(
        pages[active_section],
        source_url=active_section,
    )
    assert expected_active is not None
    monkeypatch.setattr(HawaiiScraper, "EXPECTED_OPERATIVE_SECTIONS", 1)
    monkeypatch.setattr(HawaiiScraper, "EXPECTED_TOTAL_SECTION_LOCATORS", 2)
    monkeypatch.setattr(
        HawaiiScraper,
        "EXPECTED_OPERATIVE_SECTION_INVENTORY_SHA256",
        scraper._operative_section_inventory_digest([expected_active]),
    )
    monkeypatch.setattr(
        HawaiiScraper,
        "EXPECTED_NONOPERATIVE_CHAPTER_INVENTORY_SHA256",
        scraper._nonoperative_chapter_inventory_digest(observations),
    )
    monkeypatch.setattr(
        hawaii_section,
        "_SOURCE_BOUND_RESERVED_ARTICLE_SHA256",
        hashlib.sha256(pages[reserved_section].encode()).hexdigest(),
    )
    section_observations = [
        {
            "content_sha256": hashlib.sha256(
                pages[reserved_section].encode()
            ).hexdigest(),
            "disposition": "reserved",
            "source_url": reserved_section,
        }
    ]
    monkeypatch.setattr(HawaiiScraper, "EXPECTED_NONOPERATIVE_SECTIONS", 1)
    monkeypatch.setattr(
        HawaiiScraper,
        "EXPECTED_NONOPERATIVE_SECTION_DISPOSITION_COUNTS",
        (("renumbered", 0), ("repealed", 0), ("reserved", 1)),
    )
    monkeypatch.setattr(
        HawaiiScraper,
        "EXPECTED_NONOPERATIVE_SECTION_INVENTORY_SHA256",
        scraper._nonoperative_section_inventory_digest(section_observations),
    )
    batch_calls: list[list[str]] = []

    async def _fake_html(self, url: str, timeout_seconds: int = 18) -> str:
        return pages.get(url, "")

    async def _batch(self, urls, **kwargs):
        batch_calls.append(list(urls))
        payloads = [
            (
                sentinel_payloads[url]
                if url in sentinel_payloads
                else str(pages[url]).encode()
            )
            for url in urls
        ]
        return StateLawPageMultiFetchResult(
            urls=list(urls),
            payloads=payloads,
            errors=[None] * len(urls),
            transport_receipts=[
                {
                    "content_sha256": hashlib.sha256(payload).hexdigest(),
                    "official_url": url,
                    "source_transport": "direct",
                }
                for url, payload in zip(urls, payloads)
            ],
            parser_input_envelopes=[object()] * len(urls),
            stats={"requested_pages": len(urls), "batch_calls": 1},
        )

    monkeypatch.setattr(HawaiiScraper, "_fetch_official_hi_html", _fake_html)
    monkeypatch.setattr(
        HawaiiScraper,
        "_fetch_page_contents_with_archival_fallback",
        _batch,
    )
    monkeypatch.setattr(HawaiiScraper, "_write_partial_checkpoint", lambda *a, **k: True)

    rows = await scraper._scrape_official_hrs_tree(
        code_name="Hawaii Revised Statutes",
        code_url=root,
        max_statutes=None,
    )

    assert [row.section_number for row in rows] == ["431:1-1"]
    assert [len(call) for call in batch_calls] == [1, 294, 2, 293]
    assert batch_calls[0] == [volume]
    assert batch_calls[1] == [*terminal_chapters, active_chapter]
    assert batch_calls[2] == [active_section, reserved_section]
    assert batch_calls[3] == list(sentinel_payloads)
    frontier = scraper._hawaii_frontier
    assert frontier["closed"] is True
    assert frontier["statutes_emitted"] == 1
    assert frontier["operative_section_inventory_closed"] is True
    assert frontier["nonoperative_chapters_excluded"] == 293
    assert frontier["nonoperative_chapter_inventory_closed"] is True
    assert frontier["nonoperative_sections_excluded"] == 1
    assert frontier["nonoperative_section_inventory_closed"] is True
    assert frontier["unresolved_count"] == 0


def test_hawaii_operative_inventory_is_exact_count_identity_and_digest_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = HawaiiScraper("HI", "Hawaii")
    urls = [
        (
            "https://data.capitol.hawaii.gov/hrscurrent/Vol14_Ch0701-0853/"
            "HRS0846/HRS_0846-0054.htm"
        ),
        (
            "https://data.capitol.hawaii.gov/hrscurrent/Vol14_Ch0701-0853/"
            "HRS0846E/HRS_0846E-0008.htm"
        ),
    ]
    rows = [
        parse_hawaii_section_html(
            _section_html(number, "Operative provision"),
            source_url=url,
        )
        for number, url in (("846-54", urls[0]), ("846E-8", urls[1]))
    ]
    assert all(row is not None for row in rows)
    operative_rows = [row for row in rows if row is not None]
    monkeypatch.setattr(HawaiiScraper, "EXPECTED_OPERATIVE_SECTIONS", 2)
    monkeypatch.setattr(
        HawaiiScraper,
        "EXPECTED_OPERATIVE_SECTION_INVENTORY_SHA256",
        scraper._operative_section_inventory_digest(operative_rows),
    )

    assert scraper._operative_section_inventory_closed(operative_rows)
    assert not scraper._operative_section_inventory_closed(operative_rows[:1])

    duplicate = [operative_rows[0], operative_rows[0]]
    assert not scraper._operative_section_inventory_closed(duplicate)

    drifted = operative_rows[1].to_dict()
    drifted["source_url"] = urls[1].replace("0008.htm", "0009.htm")
    drifted_row = scraper._coerce_checkpoint_row_to_statute(
        drifted,
        code_name="Hawaii Revised Statutes",
    )
    assert drifted_row is not None
    assert not scraper._operative_section_inventory_closed(
        [operative_rows[0], drifted_row]
    )


@pytest.mark.anyio
async def test_hawaii_post_parser_row_loss_cannot_authorize_shared_closure() -> None:
    scraper = HawaiiScraper("HI", "Hawaii")
    scraper._hawaii_frontier = {
        "closed": True,
        "statutes_emitted": HAWAII_EXPECTED_OPERATIVE_SECTION_COUNT,
        "operative_section_inventory_closed": True,
        "operative_section_inventory_sha256": (
            HAWAII_EXPECTED_OPERATIVE_SECTION_INVENTORY_SHA256
        ),
    }
    scraper._hawaii_operative_canonical_keys = ()

    with pytest.raises(RuntimeError, match="post-parser canonical output lost"):
        await scraper.produce_state_law_frontier_closure(
            canonical_output_projection={
                "canonical_keys": [
                    "urn:state:hi:statute:Hawaii Revised Statutes § 1-1"
                ],
                "canonical_row_count": 1,
            }
        )


@pytest.mark.anyio
async def test_hawaii_canonical_identity_substitution_cannot_authorize_closure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = HawaiiScraper("HI", "Hawaii")
    monkeypatch.setattr(HawaiiScraper, "EXPECTED_OPERATIVE_SECTIONS", 2)
    monkeypatch.setattr(
        HawaiiScraper,
        "EXPECTED_OPERATIVE_SECTION_INVENTORY_SHA256",
        "a" * 64,
    )
    scraper._hawaii_frontier = {
        "closed": True,
        "statutes_emitted": 2,
        "operative_section_inventory_closed": True,
        "operative_section_inventory_sha256": "a" * 64,
    }
    scraper._hawaii_operative_canonical_keys = ("hi:1", "hi:2")

    with pytest.raises(RuntimeError, match="identities differ"):
        await scraper.produce_state_law_frontier_closure(
            canonical_output_projection={
                "canonical_keys": ["hi:1", "hi:3"],
                "canonical_row_count": 2,
            }
        )
