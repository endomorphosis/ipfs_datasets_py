from __future__ import annotations

import copy
import hashlib
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
    build_canonical_state_law_output_projection,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    NormalizedStatute,
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.nevada import (
    NevadaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.nevada_chapter import (
    parse_nevada_chapter_html,
)


def _chapter_page(chapter: str, paragraphs: str) -> str:
    return (
        "<!doctype html><html><head>"
        f"<title>NRS: CHAPTER {chapter} - Test chapter</title>"
        f"</head><body>{paragraphs}</body></html>"
    )


def _section(
    number: str,
    heading: str,
    body: str,
    *,
    anchor: str = "",
    number_html: str = "",
) -> str:
    anchor_html = f'<a name="{anchor}"></a>' if anchor else ""
    spans = number_html or f'<span class="Section">{number}</span>'
    return (
        '<p class="SectBody">'
        f"{anchor_html}NRS {spans}"
        f'<span class="Leadline">{heading}</span> {body}'
        "</p>"
    )


def _source_bound_navigation_false_positive() -> NormalizedStatute:
    html = _chapter_page(
        "0",
        _section(
            "0.034",
            "Gender identity or expression defined.",
            (
                "Except as otherwise expressly provided, gender identity or "
                "expression includes a gender-related identity or behavior."
            ),
            anchor="NRS000Sec034",
        ),
    )
    row = parse_nevada_chapter_html(
        html,
        source_url="https://www.leg.state.nv.us/NRS/NRS-000.html",
    )[0]
    row.structured_data.update(
        {
            "archive_timestamp": "",
            "chapter_url": "https://www.leg.state.nv.us/NRS/NRS-000.html",
            "content_sha256": "a" * 64,
            "discovery_method": "official_title_chapter_inline_sections",
            "parser_input_receipt_sha256": "b" * 64,
            "source_observed_date": "2026-08-25",
            "source_retrieved_at": "2026-08-25T10:00:04.572000Z",
            "source_transport": "direct",
            "source_transport_chain": ["direct"],
        }
    )
    return row


def test_source_bound_nrs_row_bypasses_generic_navigation_false_positive() -> None:
    scraper = NevadaScraper("NV", "Nevada")
    row = _source_bound_navigation_false_positive()

    assert scraper._looks_like_navigation_text(row.section_name)
    assert scraper._looks_like_navigation_text(row.full_text)
    assert not scraper._contains_statute_signals(row.section_name)
    assert not scraper._contains_statute_signals(row.full_text)
    assert scraper._is_source_bound_operative_statute_record(row)
    assert not scraper._is_low_quality_statute_record(row)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (
            "source_url",
            "https://law.justia.com/codes/nevada/0.034#NRS000Sec034",
        ),
        (
            "source_url",
            "https://www.leg.state.nv.us/NRS/NRS-000.html#NRS000Sec055",
        ),
        ("full_text", "Section Section-1: Navigation scaffold"),
    ],
)
def test_source_bound_nrs_row_rejects_forged_locator_or_scaffold(
    field: str,
    value: str,
) -> None:
    scraper = NevadaScraper("NV", "Nevada")
    row = copy.deepcopy(_source_bound_navigation_false_positive())
    setattr(row, field, value)

    assert not scraper._is_source_bound_operative_statute_record(row)
    if field == "full_text":
        assert scraper._is_low_quality_statute_record(row)
    if "justia.com" in value:
        assert scraper._filter_official_host_statutes([row]) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("chapter_url", "https://www.leg.state.nv.us/NRS/NRS-001.html"),
        ("content_sha256", "not-a-digest"),
        ("parser_input_receipt_sha256", ""),
        ("source_authority_class", "aggregator"),
        ("source_kind", "official-looking-html"),
        ("discovery_method", "generic_link_crawl"),
    ],
)
def test_source_bound_nrs_row_rejects_forged_retained_input_projection(
    field: str,
    value: str,
) -> None:
    scraper = NevadaScraper("NV", "Nevada")
    row = copy.deepcopy(_source_bound_navigation_false_positive())
    row.structured_data[field] = value

    assert not scraper._is_source_bound_operative_statute_record(row)


def test_dated_variants_emit_one_row_with_full_exclusion_disclosure() -> None:
    html = _chapter_page(
        "1",
        _section(
            "1.010",
            "Old rule. [Effective through June 30, 2026.]",
            "The old operative text applies.",
            anchor="NRS001Sec010",
        )
        + '<p class="SourceNote">(Added to NRS by 2020, 1)</p>'
        + _section(
            "1.010",
            "New rule. [Effective July 1, 2026.]",
            "The new operative text applies.",
        )
        + '<p class="SourceNote">(Added to NRS by 2026, 2)</p>',
    )

    before = parse_nevada_chapter_html(
        html,
        source_url="https://www.leg.state.nv.us/NRS/NRS-001.html",
        as_of_date=date(2026, 6, 1),
    )
    after = parse_nevada_chapter_html(
        html,
        source_url="https://www.leg.state.nv.us/NRS/NRS-001.html",
        as_of_date=date(2026, 8, 25),
    )

    assert len(before) == len(after) == 1
    assert "old operative" in before[0].full_text
    assert "new operative" in after[0].full_text
    assert after[0].source_url.endswith("#NRS001Sec010")
    disclosure = after[0].structured_data
    assert disclosure["effective_variant_count"] == 2
    assert disclosure["effective_variant_selected_index"] == 1
    assert disclosure["effective_variant_excluded_indexes"] == [0]
    assert disclosure["effective_variant_as_of_date"] == "2026-08-25"
    assert disclosure["effective_variant_selection"] == "source_observation_date"
    variants = disclosure["effective_variants"]
    assert variants[0]["effective_until"] == "2026-07-01"
    assert variants[1]["effective_from"] == "2026-07-01"
    assert all(len(item["full_text_sha256"]) == 64 for item in variants)
    assert all(len(item["history_sha256"]) == 64 for item in variants)
    assert "Added to NRS by 2026" in after[0].metadata.history[0]
    assert "Added to NRS" not in after[0].full_text


def test_generic_event_variants_select_pre_contingency_compiler_branch() -> None:
    html = _chapter_page(
        "116A",
        _section(
            "116A.620",
            "Rule. [Effective until the effective date of the regulations adopted by the Commission.]",
            "The pre-regulation text applies.",
            anchor="NRS116ASec620",
        )
        + _section(
            "116A.620",
            "Rule. [Effective on the effective date of the regulations adopted by the Commission.]",
            "The post-regulation text applies.",
        ),
    )

    rows = parse_nevada_chapter_html(
        html,
        source_url="https://www.leg.state.nv.us/NRS/NRS-116A.html",
        as_of_date=date(2026, 8, 25),
    )

    assert len(rows) == 1
    assert "pre-regulation" in rows[0].full_text
    data = rows[0].structured_data
    assert data["effective_variant_selection"] == (
        "source_observation_date_pre_contingency_compiler_branch"
    )
    assert [
        item["contingency_polarity"] for item in data["effective_variants"]
    ] == ["before", "after"]


def test_disjoint_calendar_windows_select_the_observation_date_branch() -> None:
    html = _chapter_page(
        "280",
        _section(
            "280.201",
            "Rule. [Effective through June 30, 2027, and after June 30, 2057.]",
            "The outside-window text applies.",
            anchor="NRS280Sec201",
        )
        + _section(
            "280.201",
            "Rule. [Effective July 1, 2027, through June 30, 2057.]",
            "The middle-window text applies.",
        ),
    )

    early = parse_nevada_chapter_html(html, as_of_date=date(2026, 8, 25))
    middle = parse_nevada_chapter_html(html, as_of_date=date(2030, 1, 1))

    assert len(early) == len(middle) == 1
    assert "outside-window" in early[0].full_text
    assert "middle-window" in middle[0].full_text
    assert [
        item["contingency_polarity"]
        for item in early[0].structured_data["effective_variants"]
    ] == ["none", "none"]


def test_lettered_and_split_section_identity_is_reconstructed_not_truncated() -> None:
    html = _chapter_page(
        "388C",
        _section(
            "388C.140",
            "Power reserved to the State after an expired license is repealed.",
            "A short but operative law.",
            anchor="NRS388CSec140",
            number_html=(
                '<span class="Section">388C</span>'
                '<span class="Section">.140</span>'
            ),
        ),
    )

    rows = parse_nevada_chapter_html(html)

    assert len(rows) == 1
    assert rows[0].section_number == "388C.140"
    assert rows[0].full_text == "A short but operative law."
    assert rows[0].structured_data["source_section_identity_reconstructed"] is True
    assert rows[0].structured_data["source_section_number_fragments"] == [
        "388C",
        ".140",
    ]


def test_compiler_prefix_split_uses_matching_page_and_anchor_evidence() -> None:
    html = _chapter_page(
        "532",
        _section(
            "32.005",
            "Tribal government defined.",
            "The definition is operative.",
            anchor="NRS532Sec005",
        ),
    )

    rows = parse_nevada_chapter_html(html)

    assert len(rows) == 1
    assert rows[0].section_number == "532.005"
    data = rows[0].structured_data
    assert data["source_section_number_raw"] == "32.005"
    assert data["source_section_identity_reconstructed"] is True
    assert data["source_section_identity_repair"] == (
        "official_chapter_anchor_prefix_repair"
    )


def test_empty_section_span_is_disclosed_as_decoration_not_reconstruction() -> None:
    html = _chapter_page(
        "638",
        _section(
            "638.1408",
            "Operative section.",
            "The operative text remains intact.",
            anchor="NRS638Sec1408",
            number_html=(
                '<span class="Section">638.1408</span>'
                '<span class="Section"></span>'
            ),
        ),
    )

    rows = parse_nevada_chapter_html(html)

    assert len(rows) == 1
    data = rows[0].structured_data
    assert data["source_section_identity_reconstructed"] is False
    assert data["source_section_number_empty_span_count"] == 1


def test_repeated_identity_without_effective_qualifiers_fails_closed() -> None:
    html = _chapter_page(
        "1",
        _section("1.020", "First heading.", "First body.", anchor="NRS001Sec020")
        + _section("1.020", "Second heading.", "Second body."),
    )

    with pytest.raises(ValueError, match="effective-version qualifier"):
        parse_nevada_chapter_html(html, as_of_date=date(2026, 8, 25))


def test_future_singleton_is_digested_but_not_emitted_as_current_law() -> None:
    html = _chapter_page(
        "585",
        _section(
            "585.600",
            "Future rule. [Effective July 1, 2027.]",
            "Future operative text.",
            anchor="NRS585Sec600",
        ),
    )
    exclusions: list[dict[str, Any]] = []

    rows = parse_nevada_chapter_html(
        html,
        source_url="https://www.leg.state.nv.us/NRS/NRS-585.html",
        as_of_date=date(2026, 8, 25),
        temporal_exclusions=exclusions,
    )

    assert rows == []
    assert len(exclusions) == 1
    excluded = exclusions[0]
    assert excluded["section_number"] == "585.600"
    assert excluded["exclusion_reason"] == "future_effective_official_variant"
    assert excluded["source_url"].endswith("#NRS585Sec600")
    assert excluded["variants"][0]["effective_from"] == "2027-07-01"
    assert len(excluded["variants"][0]["full_text_sha256"]) == 64


def _evidence(
    url: str,
    payload: bytes,
    *,
    source_transport: str,
    archive_timestamp: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    content_sha256 = hashlib.sha256(payload).hexdigest()
    transport = {
        "content_sha256": content_sha256,
        "official_url": url,
        "source_transport": source_transport,
    }
    if archive_timestamp:
        transport["archive_timestamp"] = archive_timestamp
        transport["archive_url"] = (
            "https://data.commoncrawl.org/crawl-data/CC-MAIN-2024-22/"
            "segments/example/warc/example.warc.gz"
        )
    receipt_sha256 = hashlib.sha256(
        f"{url}:{source_transport}:{archive_timestamp}".encode()
    ).hexdigest()
    envelope = {
        "acquisition": {
            "body_sha256": content_sha256,
            "receipt": {
                "content": {"sha256": content_sha256},
                "endpoint": url,
                "metadata": {"transport_receipt": transport},
                "receipt_sha256": receipt_sha256,
                "retrieved_at": "2026-08-25T10:03:02.096000Z",
            },
        }
    }
    return transport, envelope


@pytest.mark.asyncio
async def test_unbounded_chapters_use_one_plural_batch_and_archive_capture_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls = [
        "https://www.leg.state.nv.us/NRS/NRS-001.html",
        "https://www.leg.state.nv.us/NRS/NRS-002.html",
    ]
    first = _chapter_page(
        "1",
        '<p class="COLeadline"><a href="#NRS001Sec010">NRS 1.010</a> '
        "Direct section.</p>"
        + _section(
            "1.010",
            "Direct section.",
            "Direct official body.",
            anchor="NRS001Sec010",
        ),
    ).encode("windows-1252")
    second = _chapter_page(
        "2",
        '<p class="COLeadline"><a href="#NRS002Sec010">NRS 2.010</a> '
        "Temporal section.</p>"
        '<p class="COLeadline"><a href="#NRS002Sec010">NRS 2.010</a> '
        "Temporal section.</p>"
        + _section(
            "2.010",
            "Old section. [Effective through December 31, 2024.]",
            "Archive-date old body.",
            anchor="NRS002Sec010",
        )
        + _section(
            "2.010",
            "New section. [Effective January 1, 2025.]",
            "Later body.",
        ),
    ).encode("windows-1252")
    direct_receipt, direct_envelope = _evidence(
        urls[0],
        first,
        source_transport="direct",
    )
    archive_receipt, archive_envelope = _evidence(
        urls[1],
        second,
        source_transport="common_crawl",
        archive_timestamp="20240615112233",
    )
    calls: list[tuple[list[str], dict[str, Any]]] = []

    async def _plural(requested: list[str], **kwargs: Any) -> StateLawPageMultiFetchResult:
        calls.append((list(requested), dict(kwargs)))
        return StateLawPageMultiFetchResult(
            urls=list(requested),
            payloads=[first, second],
            errors=[None, None],
            transport_receipts=[direct_receipt, archive_receipt],
            parser_input_envelopes=[direct_envelope, archive_envelope],
            stats={
                "network_requested_pages": 0,
                "retained_replay_pages": 2,
                "requested_pages": 2,
            },
        )

    scraper = NevadaScraper("NV", "Nevada")
    monkeypatch.setenv("STATE_SCRAPER_NV_CHAPTER_BATCH_SIZE", "512")
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", lambda *args, **kwargs: None)

    rows = await scraper._scrape_unbounded_nevada_chapters(
        "Nevada Revised Statutes",
        urls,
        discovery_method="official_title_chapter_inline_sections",
    )

    assert len(calls) == 1
    assert calls[0][0] == urls
    assert calls[0][1]["prefer_direct"] is True
    assert calls[0][1]["common_crawl_domain_terms"] == (
        "www.leg.state.nv.us",
    )
    assert calls[0][1]["common_crawl_url_terms"] == ("/NRS/NRS-",)
    assert [row.section_number for row in rows] == ["1.010", "2.010"]
    assert "Archive-date old body" in rows[1].full_text
    assert rows[1].structured_data["source_observed_date"] == "2024-06-15"
    assert rows[1].structured_data["source_transport"] == "common_crawl"
    assert rows[1].structured_data["source_transport_chain"] == ["common_crawl"]
    assert len(rows[1].structured_data["parser_input_receipt_sha256"]) == 64
    assert scraper._last_nevada_temporal_closure["canonical_statutes"] == 2
    assert scraper._last_nevada_temporal_closure["duplicate_canonical_identities"] == 0


def test_official_catalog_acquisition_fails_closed_without_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = NevadaScraper("NV", "Nevada")
    monkeypatch.setattr(scraper, "_official_http_get", lambda *_args, **_kwargs: b"")

    with pytest.raises(RuntimeError, match="no retained parser bytes"):
        scraper.fetch_official("NV")


@pytest.mark.asyncio
async def test_exact_retained_temporal_frontier_replays_and_seals_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = NevadaScraper("NV", "Nevada")
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="NV",
        parser_name=type(scraper).__name__,
    )
    scraper.attach_state_law_acquisition_ledger(ledger)
    monkeypatch.setattr(NevadaScraper, "OFFICIAL_CHAPTER_FLOOR", 2)
    monkeypatch.setattr(
        scraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: None,
    )

    urls = [
        "https://www.leg.state.nv.us/NRS/NRS-001.html",
        "https://www.leg.state.nv.us/NRS/NRS-002.html",
    ]
    root = (
        "<html><body>"
        '<a href="NRS-001.html">Chapter 1</a>'
        '<a href="NRS-002.html">Chapter 2</a>'
        "</body></html>"
    ).encode("windows-1252")
    first = _chapter_page(
        "1",
        '<p class="COLeadline"><a href="#NRS001Sec010">NRS 1.010</a> '
        "Direct section.</p>"
        + _section(
            "1.010",
            "Direct section.",
            "Direct official body.",
            anchor="NRS001Sec010",
        ),
    ).encode("windows-1252")
    second = _chapter_page(
        "2",
        '<p class="COLeadline"><a href="#NRS002Sec010">NRS 2.010</a> '
        "Old section.</p>"
        '<p class="COLeadline"><a href="#NRS002Sec010">NRS 2.010</a> '
        "New section.</p>"
        + _section(
            "2.010",
            "Old section. [Effective through December 31, 2024.]",
            "Old official body.",
            anchor="NRS002Sec010",
        )
        + _section(
            "2.010",
            "New section. [Effective January 1, 2025.]",
            "Current official body.",
        ),
    ).encode("windows-1252")

    def _retain(url: str, body: bytes, retrieved_at: str) -> None:
        ledger.retain_parser_input(
            official_url=url,
            body=body,
            transport_receipt={
                "content_sha256": hashlib.sha256(body).hexdigest(),
                "official_url": url,
                "source_transport": "direct",
            },
            retrieved_at=retrieved_at,
            media_type="text/html",
            sanitized_request={"method": "GET", "url": url},
        )

    _retain(scraper.OFFICIAL_ENTRY_URL, root, "2026-08-25T20:00:00Z")
    _retain(urls[0], first, "2026-08-25T20:01:00Z")
    _retain(urls[1], second, "2026-08-25T20:02:00Z")

    discovered = await scraper._discover_chapter_pages()
    rows = await scraper._scrape_unbounded_nevada_chapters(
        "Nevada Revised Statutes",
        discovered,
        discovery_method="official_title_chapter_inline_sections",
    )
    first_frontier = scraper._last_nevada_full_frontier["frontier"]

    assert discovered == urls
    assert [row.section_number for row in rows] == ["1.010", "2.010"]
    assert "Current official body" in rows[1].full_text
    assert first_frontier["disposition"] == {
        "discovered": 2,
        "duplicates": 0,
        "excluded": 0,
        "failed_final": 0,
        "fetched": 2,
        "quarantined": 0,
    }
    assert first_frontier["toc_variant_record_count"] == 3
    assert first_frontier["selected_temporal_variants_excluded"] == 1

    projection = build_canonical_state_law_output_projection(
        [scraper._enrich_statute_structure(row).to_dict() for row in rows],
        jurisdiction="NV",
    )
    closure_path = await scraper.produce_state_law_frontier_closure(
        canonical_output_projection=projection,
    )

    assert closure_path is not None and closure_path.is_file()
    assert len(ledger.entries) == 3
    replay = scraper._last_nevada_replayed_frontier
    assert replay["frontier"] == first_frontier
    assert [row.section_number for row in replay["rows"]] == ["1.010", "2.010"]
