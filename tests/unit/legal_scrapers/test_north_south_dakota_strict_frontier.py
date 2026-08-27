"""Strict source-derived closure tests for the Dakota statute frontiers."""

from __future__ import annotations

import asyncio
import copy
import json
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
    build_canonical_state_law_output_projection,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_dakota import (
    NorthDakotaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_dakota_chapter import (
    parse_north_dakota_chapter_text_with_dispositions,
    source_bound_document_terminal_disposition,
    source_bound_terminal_disposition as north_dakota_terminal_disposition,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.south_dakota import (
    SouthDakotaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.south_dakota_title import (
    parse_south_dakota_title_html_with_dispositions,
    source_bound_terminal_disposition,
    title_chapter_entries,
    title_section_entries,
)


def _south_dakota_catalog_payload(scraper: SouthDakotaScraper) -> bytes:
    return json.dumps(
        [
            {
                "Statute": number,
                "Type": "Title",
                "CatchLine": name,
            }
            for number, name in scraper.OFFICIAL_TITLES
        ],
        separators=(",", ":"),
    ).encode("utf-8")


def _north_dakota_slug(title: str) -> str:
    whole, separator, fraction = title.partition(".")
    slug = f"{int(whole):02d}"
    return f"{slug}-{fraction}" if separator else slug


def _north_dakota_index_payload(scraper: NorthDakotaScraper) -> bytes:
    parts = [
        "<html><head><title>North Dakota Century Code</title></head><body>"
    ]
    for title, name in scraper.OFFICIAL_TITLES:
        chapter = f"{title}-01"
        section = f"{chapter}-01"
        terminal = f"{chapter}-02"
        pdf = f"/cencode/t{_north_dakota_slug(title)}c01.pdf"
        parts.extend(
            [
                "<details class='accordion'>",
                f"<summary class='outer'><h2>Title {title} - {name}</h2></summary>",
                "<details class='accordion'>",
                f"<summary class='inner'><h3>Chapter {chapter} - Test</h3></summary>",
                "<table class='simple-table'><tbody>",
                f"<tr><td><a href='{pdf}#nameddest={section}'>{section}</a></td>"
                "<td>Operative source-derived section</td></tr>",
                f"<tr><td><a href='{pdf}#nameddest={terminal}'>{terminal}</a></td>"
                "<td>Former provision [Repealed]</td></tr>",
                "</tbody></table></details></details>",
            ]
        )
    parts.append("</body></html>")
    return "".join(parts).encode()


def _north_dakota_pdf_payload(title: str) -> bytes:
    chapter = f"{title}-01"
    section = f"{chapter}-01"
    terminal = f"{chapter}-02"
    body = (
        "The agency members shall meet during each legislative session and may "
        "publish media notices under the operative public law. "
    ) * 5
    return (
        "%PDF-1.7\n"
        f"CHAPTER {chapter}\n"
        f"{section}. Operative source-derived section.\n"
        f"{body}\n"
        "Source: S.L. 2025, ch. 1, § 1.\n"
        f"{terminal}. Former provision [Repealed].\n"
    ).encode()


def _bind_north_dakota_plural_fetch(
    monkeypatch: pytest.MonkeyPatch,
    scraper: NorthDakotaScraper,
) -> list[dict[str, Any]]:
    index = _north_dakota_index_payload(scraper)
    calls: list[dict[str, Any]] = []

    async def _fake_fetch(
        urls,
        *,
        frontier_name: str,
        content_validator,
        media_type: str,
    ):
        requested = list(urls)
        calls.append(
            {
                "frontier_name": frontier_name,
                "media_type": media_type,
                "urls": requested,
            }
        )
        if frontier_name == "collapsed-index":
            payloads = [index]
        else:
            by_url = {
                f"https://www.legis.nd.gov/cencode/"
                f"t{_north_dakota_slug(title)}c01.pdf": _north_dakota_pdf_payload(title)
                for title, _name in scraper.OFFICIAL_TITLES
            }
            payloads = [by_url[url] for url in requested]
        assert all(content_validator(payload) for payload in payloads)
        return payloads

    monkeypatch.setattr(scraper, "_fetch_north_dakota_frontier_batch", _fake_fetch)
    monkeypatch.setattr(
        scraper,
        "_north_dakota_pdf_text_lines",
        lambda payload: payload.decode("utf-8"),
    )
    return calls


def _south_dakota_title_payload(
    title: str,
    *,
    residual_section: str = "",
    terminal_chapter: bool = False,
    lifecycle_chapter_variant: bool = False,
    lifecycle_section_variant: bool = False,
    source_collection_parent: bool = False,
    source_collection_parent_toc_only: bool = False,
    source_identity_alias: bool = False,
    toc_only_terminal: bool = False,
) -> bytes:
    section = f"{title}-1-1"
    terminal = f"{title}-1-2"
    residual_toc = (
        f"<p class='schapterB'><a href='/Statutes?Statute={residual_section}'>"
        f"{residual_section}</a> Residual operative section</p>"
        if residual_section
        else ""
    )
    terminal_chapter_html = (
        f"<p class='stitleB'><a href='/Statutes/{title}-2'>02</a> "
        "Historical chapter [Repealed]</p>"
        f"<p class='sdeadB'><a href='/Statutes?Statute={title}-2-1'>"
        f"{title}-2-1</a> Historical descendant</p>"
        f"<p class='sdeadNormal'><span class='sdeadSENU'>{title}-2-1</span>. "
        "Historical descendant.</p>"
        "<p class='sdeadStatute'>This historical body must be excluded beneath "
        "the source-terminal chapter identity.</p>"
        if terminal_chapter
        else ""
    )
    lifecycle_chapter_html = (
        f"<p class='stitleB'><a href='/Statutes/{title}-1'>01</a> "
        "Former chapter variant [Repealed]</p>"
        if lifecycle_chapter_variant
        else ""
    )
    collection_parent = f"{title}-1-3"
    collection_child_a = f"{collection_parent}(a)"
    collection_child_b = f"{collection_parent}(b)"
    collection_toc_html = (
        f"<p class='schapterB'><a href='/Statutes?Statute={collection_parent}'>"
        f"{collection_parent}</a> Discovery pending action</p>"
        f"<p class='schapterB'><a href='/Statutes?Statute={collection_child_a}'>"
        f"{collection_child_a}</a> Depositions before action</p>"
        f"<p class='schapterB'><a href='/Statutes?Statute={collection_child_b}'>"
        f"{collection_child_b}</a> Perpetuation by action</p>"
        if source_collection_parent
        else ""
    )
    collection_parent_heading_html = (
        f"<p class='seaaNormal'><span class='seaaSENU'>{collection_parent}</span>. "
        "Discovery pending action.</p>"
        if source_collection_parent and not source_collection_parent_toc_only
        else ""
    )
    collection_body_html = (
        f"{collection_parent_heading_html}"
        f"<p class='sebbNormal'><span class='sebbSENU'>{collection_child_a}</span>. "
        "Depositions before action.</p>"
        "<p class='sebbStatute'>This child rule contains substantive official "
        "statutory text that must be retained independently.</p>"
        f"<p class='seccNormal'><span class='seccSENU'>{collection_child_b}</span>. "
        "Perpetuation by action.</p>"
        "<p class='seccStatute'>This second child rule also contains substantive "
        "official statutory text that must be retained independently.</p>"
        if source_collection_parent
        else ""
    )
    alias_canonical = f"{title}-1-3A"
    alias_source_identity = f"{title}-1-3(A)"
    alias_toc_html = (
        f"<p class='schapterB'><a href='/Statutes?Statute={alias_source_identity}'>"
        f"{alias_source_identity}</a> Transition source identity alias</p>"
        if source_identity_alias
        else ""
    )
    alias_body_html = (
        f"<p class='seaaNormal'><span class='seaaSENU'>{alias_canonical}</span>. "
        "Canonical transition provision.</p>"
        "<p class='seaaStatute'>This canonical source body contains sufficient "
        "substantive official statutory text for independent admission.</p>"
        if source_identity_alias
        else ""
    )
    current_document_url = (
        "<meta property='og:url' "
        f"content='https://sdlegislature.gov/Statutes/{section}'>"
        if lifecycle_section_variant
        else ""
    )
    title_page_style = "<style>.sourceSENU{}</style>" if toc_only_terminal else ""
    section_toc_label = (
        "Former provision [Repealed]"
        if toc_only_terminal
        else (
            "Repealed."
            if lifecycle_section_variant
            else "Operative source-derived section"
        )
    )
    section_body_html = (
        ""
        if toc_only_terminal
        else (
            f"<p class='sabcNormal'><span class='sabcSENU'>{section}</span>. "
            "<span>Operative source-derived section.</span></p>"
            "<p class='sabcStatute'><span>This is substantive official statutory "
            "text retained without truncation for the normalized corpus.</span></p>"
            f"<p class='sdefNormal'><span class='sdefSENU'>{terminal}</span>. "
            "<span>Former provision [Repealed].</span></p>"
        )
    )
    future_variant_html = (
        "<html><head></head><body>"
        f"<p class='seaaNormal'><span class='seaaSENU'>{section}</span>. "
        "Repealed.</p>"
        "<p class='seaaNormal'>Source: SL 2026, ch 1, § 1, eff. July 1, 2027."
        "</p></body></html>"
        if lifecycle_section_variant
        else ""
    )
    return (
        "<html><head>"
        f"{current_document_url}"
        f"{title_page_style}"
        "<title>SDLRC - Codified Law "
        f"{title}</title></head><body>"
        f"{lifecycle_chapter_html}"
        f"<p class='stitleB'><a href='/Statutes/{title}-1'>01</a> "
        "Active source-derived chapter</p>"
        f"<p class='schapterB'><a href='/Statutes/Codified_Laws/"
        f"DisplayStatute.aspx?Type=Statute&amp;Statute={section}'>{section}</a> "
        f"{section_toc_label}</p>"
        f"<p class='schapterB'><a href='/Statutes/Codified_Laws/"
        f"DisplayStatute.aspx?Type=Statute&amp;Statute={terminal}'>{terminal}</a> "
        "Former provision [Repealed]</p>"
        f"{residual_toc}"
        f"{collection_toc_html}"
        f"{alias_toc_html}"
        f"{terminal_chapter_html}"
        f"{section_body_html}"
        f"{collection_body_html}"
        f"{alias_body_html}"
        "</body></html>"
        f"{future_variant_html}"
    ).encode("utf-8")


def _south_dakota_section_payload(section_number: str) -> bytes:
    return (
        "<html><head><title>SDLRC - Codified Law "
        f"{section_number}</title></head><body>"
        f"<p class='pt-Normal'><span class='pt-SENU'>{section_number}</span>. "
        "Residual operative section.</p>"
        "<p class='pt-Statute'>This is the exact substantive official section "
        "body recovered through the grouped residual fallback.</p>"
        "</body></html>"
    ).encode("utf-8")


def _bind_south_dakota_plural_fetch(
    monkeypatch: pytest.MonkeyPatch,
    scraper: SouthDakotaScraper,
    *,
    residual_section: str = "",
    terminal_chapter_title: str = "",
    lifecycle_chapter_variant_title: str = "",
    lifecycle_section_variant_title: str = "",
    source_collection_parent_title: str = "",
    source_collection_parent_toc_only: bool = False,
    source_identity_alias_title: str = "",
    toc_only_terminal_title: str = "",
) -> list[dict[str, Any]]:
    catalog = _south_dakota_catalog_payload(scraper)
    calls: list[dict[str, Any]] = []

    async def _fake_fetch(
        urls,
        *,
        frontier_name: str,
        content_validator,
        media_type: str,
    ):
        requested = list(urls)
        calls.append(
            {
                "frontier_name": frontier_name,
                "media_type": media_type,
                "urls": requested,
            }
        )
        if frontier_name == "title-catalog":
            payloads = [catalog]
        elif frontier_name == "whole-title-pages":
            payloads = [
                _south_dakota_title_payload(
                    url.split("/api/Statutes/", 1)[1].split(".html", 1)[0],
                    residual_section=(
                        residual_section
                        if url.endswith(
                            f"/{residual_section.split('-', 1)[0]}.html?all=true"
                        )
                        else ""
                    ),
                    terminal_chapter=(
                        bool(terminal_chapter_title)
                        and url.endswith(
                            f"/{terminal_chapter_title}.html?all=true"
                        )
                    ),
                    lifecycle_chapter_variant=(
                        bool(lifecycle_chapter_variant_title)
                        and url.endswith(
                            f"/{lifecycle_chapter_variant_title}.html?all=true"
                        )
                    ),
                    lifecycle_section_variant=(
                        bool(lifecycle_section_variant_title)
                        and url.endswith(
                            f"/{lifecycle_section_variant_title}.html?all=true"
                        )
                    ),
                    source_collection_parent=(
                        bool(source_collection_parent_title)
                        and url.endswith(
                            f"/{source_collection_parent_title}.html?all=true"
                        )
                    ),
                    source_collection_parent_toc_only=(
                        source_collection_parent_toc_only
                        and url.endswith(
                            f"/{source_collection_parent_title}.html?all=true"
                        )
                    ),
                    source_identity_alias=(
                        bool(source_identity_alias_title)
                        and url.endswith(
                            f"/{source_identity_alias_title}.html?all=true"
                        )
                    ),
                    toc_only_terminal=(
                        bool(toc_only_terminal_title)
                        and url.endswith(
                            f"/{toc_only_terminal_title}.html?all=true"
                        )
                    ),
                )
                for url in requested
            ]
        else:
            payloads = [
                _south_dakota_section_payload(
                    url.split("/api/Statutes/", 1)[1].split(".html", 1)[0]
                )
                for url in requested
            ]
        assert all(content_validator(payload) for payload in payloads)
        return payloads

    monkeypatch.setattr(scraper, "_fetch_south_dakota_frontier_batch", _fake_fetch)
    return calls


def test_north_dakota_index_parser_has_exact_74_title_source_oracle() -> None:
    scraper = NorthDakotaScraper("ND", "North Dakota")
    titles, chapters, direct = scraper._parse_north_dakota_index_frontier(
        _north_dakota_index_payload(scraper)
    )

    scraper._validate_north_dakota_live_static_title_catalog(titles)
    assert len(titles) == scraper.OFFICIAL_TITLE_COUNT == 74
    assert len(chapters) == 74
    assert direct == []
    assert sum(len(chapter["sections"]) for chapter in chapters) == 148
    assert {title["title_number"] for title in titles} >= {
        "3",
        "17",
        "60",
        "64",
    }
    assert "32.1" not in {title["title_number"] for title in titles}


def test_north_dakota_pdf_parser_accounts_for_terminal_section_and_document() -> None:
    text = _north_dakota_pdf_payload("12.1").decode()
    rows, terminals, unresolved = parse_north_dakota_chapter_text_with_dispositions(
        text,
        source_url="https://www.legis.nd.gov/cencode/t12-1c01.pdf",
    )

    assert [row.section_number for row in rows] == ["12.1-01-01"]
    assert [(row["section_number"], row["disposition"]) for row in terminals] == [
        ("12.1-01-02", "repealed")
    ]
    assert unresolved == []
    assert source_bound_document_terminal_disposition(
        "TITLE 7 BUILDING AND LOAN ASSOCIATIONS "
        "[Repealed by S.L. 2007, ch. 78, § 6]"
    ) == "repealed"
    assert source_bound_document_terminal_disposition(
        "TITLE 26\nINSURANCE\n[Title 26 was repealed and replaced by S.L. 1983,\n"
        "ch. 332. For present provisions, see Title 26.1]\nPage No. 1"
    ) == "repealed"
    assert north_dakota_terminal_disposition("Former chapter [Repealed]") == (
        "repealed"
    )
    assert north_dakota_terminal_disposition(
        "Chapters 4.1-76 Through 4.1-82 are Reserved"
    ) == "reserved"
    assert north_dakota_terminal_disposition("Reserved name") == ""
    assert north_dakota_terminal_disposition("Property transferred by deed") == ""
    assert north_dakota_terminal_disposition(
        "Task force (Expired effective July 1, 2027)"
    ) == ""


def test_north_dakota_pdf_parser_normalizes_source_proved_padded_title_token() -> None:
    rows, terminals, unresolved = parse_north_dakota_chapter_text_with_dispositions(
        "\n".join(
            [
                "CHAPTER 1-03",
                "01-03-19. State song.",
                "The official state song is designated by this section.",
                "Source: S.L. 2025, ch. 1, § 1.",
            ]
        ),
        source_url="https://www.legis.nd.gov/cencode/t01c03.pdf",
    )

    assert [row.section_number for row in rows] == ["1-03-19"]
    assert [row.chapter_number for row in rows] == ["1-03"]
    assert terminals == []
    assert unresolved == []


def test_north_dakota_pdf_parser_repairs_index_proved_chapter_decimal() -> None:
    label = (
        "Early childhood services providers - Mandated reporter of suspected "
        "child abuse or neglect - Training"
    )
    rows, terminals, unresolved = parse_north_dakota_chapter_text_with_dispositions(
        "\n".join(
            [
                f"50-11-02.4. {label}.",
                "Each provider shall complete the official mandated-reporter training.",
                "50-11.1-03. Operation of early childhood services program - License required.",
                "A license is required under the conditions stated in this section.",
            ]
        ),
        expected_section_numbers=["50-11.1-02.4", "50-11.1-03"],
        expected_section_labels={
            "50-11.1-02.4": label,
            "50-11.1-03": (
                "Operation of early childhood services program - License required"
            ),
        },
    )

    assert [row.section_number for row in rows] == ["50-11.1-02.4", "50-11.1-03"]
    assert rows[0].structured_data["section_number_raw"] == "50-11-02.4"
    assert rows[0].structured_data["section_identity_repair"] == (
        "official_pdf_dropped_chapter_decimal_suffix"
    )
    assert terminals == []
    assert unresolved == []


def test_north_dakota_index_order_distinguishes_body_cite_from_duplicate_heading() -> None:
    source_labels = {
        "4.1-01-05": "Cooperation with federal agencies in destruction of predatory animals",
        "4.1-01-06": "Expenditures authorized (Contingent expiration date - See note)",
    }
    text = "\n".join(
        [
            "4.1-01-05. Cooperation with federal agencies in destruction of predatory animals.",
            "The commissioner may enter agreements with an appropriate federal agency.",
            "4.1-01-06. This citation remains part of the prior section's body.",
            "4.1-01-06. Expenditures authorized. (Contingent expiration date - See note)",
            "The commissioner may authorize expenditures under this section.",
            "4.1-01-05. Hunters employed under section 4.1-01-05 must be residents.",
        ]
    )

    rows, terminals, unresolved = parse_north_dakota_chapter_text_with_dispositions(
        text,
        expected_section_numbers=list(source_labels),
        expected_section_labels=source_labels,
    )

    assert [row.section_number for row in rows] == ["4.1-01-05", "4.1-01-06"]
    assert "This citation remains" in rows[0].full_text
    assert "Hunters employed" in rows[-1].full_text
    assert terminals == []
    assert unresolved == []

    with pytest.raises(ValueError, match="repeated exact section identity"):
        parse_north_dakota_chapter_text_with_dispositions(
            text.replace(
                "4.1-01-05. Hunters employed under section 4.1-01-05 must be residents.",
                "4.1-01-05. Cooperation with federal agencies in destruction of predatory animals.",
            ),
            expected_section_numbers=list(source_labels),
            expected_section_labels=source_labels,
        )


def test_north_dakota_temporal_pair_uses_exact_current_index_heading() -> None:
    source_labels = {
        "15.1-13-35.2": (
            "Teaching license - Mathematics instruction competency "
            "(Effective through June 30, 2027)"
        ),
        "15.1-13-36": "Satisfaction survey",
    }
    text = "\n".join(
        [
            "15.1-13-35.2. Teaching license - Mathematics instruction competency. (Effective",
            "through June 30, 2027)",
            "The current official branch applies to secondary mathematics teachers.",
            "15.1-13-35.2. Teaching license - Mathematics instruction competency. (Effective after",
            "June 30, 2027)",
            "The future official branch also applies to elementary education teachers.",
            "15.1-13-36. Satisfaction survey.",
            "The board shall use the official survey.",
        ]
    )

    rows, terminals, unresolved = parse_north_dakota_chapter_text_with_dispositions(
        text,
        expected_section_numbers=list(source_labels),
        expected_section_labels=source_labels,
    )

    assert [row.section_number for row in rows] == ["15.1-13-35.2", "15.1-13-36"]
    assert "current official branch" in rows[0].full_text
    assert "future official branch" not in rows[0].full_text
    assert "through June 30, 2027" in rows[0].section_name
    disclosure = rows[0].structured_data
    assert disclosure["effective_variant_count"] == 2
    assert disclosure["effective_variant_selection"] == "official_index_current_heading"
    assert disclosure["effective_variant_boundary_date"] == "2027-07-01"
    assert disclosure["effective_variant_selected_index"] == 0
    assert disclosure["effective_variant_excluded_indexes"] == [1]
    variants = disclosure["effective_variants"]
    assert variants[0]["effective_until"] == "2027-07-01"
    assert variants[1]["effective_from"] == "2027-07-01"
    assert all(len(variant["full_text_sha256"]) == 64 for variant in variants)
    assert terminals == []
    assert unresolved == []

    with pytest.raises(ValueError, match="not uniquely selected"):
        parse_north_dakota_chapter_text_with_dispositions(
            text.replace(
                "June 30, 2027)\nThe future",
                "June 30, 2028)\nThe future",
                1,
            ),
            expected_section_numbers=list(source_labels),
            expected_section_labels=source_labels,
        )


def test_north_dakota_strict_frontier_batches_each_unique_pdf_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = NorthDakotaScraper("ND", "North Dakota")
    calls = _bind_north_dakota_plural_fetch(monkeypatch, scraper)

    rows = asyncio.run(
        scraper._scrape_strict_full_corpus_frontier(
            "North Dakota Century Code",
            record_primary=True,
            write_checkpoints=False,
        )
    )

    assert len(calls) == 2
    assert calls[0]["urls"] == [scraper.OFFICIAL_INDEX_URL]
    assert len(calls[1]["urls"]) == 74
    assert len(calls[1]["urls"]) == len(set(calls[1]["urls"]))
    assert {url.split("/", 3)[2] for url in calls[1]["urls"]} == {
        "www.legis.nd.gov"
    }
    assert len(rows) == 74
    frontier = scraper._last_north_dakota_full_frontier["frontier"]
    assert frontier["catalog_parity"] is True
    assert frontier["pdf_section_occurrence_count"] == 148
    assert frontier["selected_multi_variant_identity_count"] == 0
    assert frontier["selected_temporal_variants_excluded"] == 0
    assert frontier["source_identity_repair_count"] == 0
    assert frontier["operative_row_binding_count"] == 74
    assert len(frontier["operative_row_bindings_sha256"]) == 64
    assert frontier["disposition"] == {
        "discovered": 148,
        "fetched": 74,
        "excluded": 74,
        "failed_final": 0,
        "duplicates": 0,
        "quarantined": 0,
    }
    assert frontier["source_record_disposition"] == frontier["disposition"]


def test_north_dakota_source_bound_rows_outrank_generic_navigation_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = NorthDakotaScraper("ND", "North Dakota")
    _bind_north_dakota_plural_fetch(monkeypatch, scraper)
    rows = asyncio.run(
        scraper._scrape_strict_full_corpus_frontier(
            "North Dakota Century Code",
            record_primary=True,
            write_checkpoints=False,
        )
    )

    row = rows[0]
    assert {"agency", "members", "session", "media"}.issubset(
        set(str(row.full_text).lower().split())
    )
    assert scraper._looks_like_navigation_text(str(row.full_text)) is True
    assert scraper._contains_statute_signals(str(row.full_text)) is False
    assert scraper._is_source_bound_operative_statute_record(row) is True
    assert scraper._is_low_quality_statute_record(row) is False

    for field, replacement in (
        ("state_code", "SD"),
        ("state_name", "Dakota"),
        ("code_name", "North Dakota Administrative Code"),
        ("statute_id", "North Dakota Century Code § forged"),
        ("official_cite", "N.D. Cent. Code § forged"),
        ("source_url", "https://www.legis.nd.gov/cencode/forged.pdf"),
        ("section_number", "1-01-999"),
        ("section_name", "Forged source label"),
        ("full_text", f"{row.full_text} forged"),
    ):
        forged = copy.deepcopy(row)
        setattr(forged, field, replacement)
        assert scraper._is_source_bound_operative_statute_record(forged) is False

    for field, replacement in (
        ("source_kind", "official-looking-forgery"),
        ("source_authority_class", "secondary"),
        ("discovery_method", "unbound_pdf"),
        ("skip_hydrate", False),
        ("content_sha256", "0" * 64),
        ("index_source_label", "Forged source label"),
    ):
        forged = copy.deepcopy(row)
        forged.structured_data[field] = replacement
        assert scraper._is_source_bound_operative_statute_record(forged) is False

    forged = copy.deepcopy(row)
    scraper._last_north_dakota_full_frontier["frontier"]["closed"] = False
    assert scraper._is_source_bound_operative_statute_record(forged) is False


def test_north_dakota_closure_replays_exact_rows_and_public_law_rights(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = NorthDakotaScraper("ND", "North Dakota")
    _bind_north_dakota_plural_fetch(monkeypatch, scraper)
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="ND",
        parser_name="NorthDakotaScraper",
    )
    scraper.attach_state_law_acquisition_ledger(ledger)
    rows = asyncio.run(
        scraper._scrape_strict_full_corpus_frontier(
            "North Dakota Century Code",
            record_primary=True,
            write_checkpoints=False,
        )
    )
    projection = build_canonical_state_law_output_projection(
        [scraper._enrich_statute_structure(row).to_dict() for row in rows],
        jurisdiction="ND",
    )

    closure_path = asyncio.run(
        scraper.produce_state_law_frontier_closure(
            canonical_output_projection=projection,
        )
    )
    closure = json.loads(closure_path.read_text(encoding="utf-8"))
    receipt = closure["completion_receipt"]
    assert receipt["disposition"]["fetched"] == 74
    assert receipt["rights"]["basis"] == "public_law_no_state_copyright"
    assert receipt["frontier"] == closure["replayed_frontier"]


def test_south_dakota_live_catalog_is_exact_current_71_title_inventory() -> None:
    scraper = SouthDakotaScraper("SD", "South Dakota")
    units = scraper._parse_live_south_dakota_title_units(
        _south_dakota_catalog_payload(scraper)
    )

    scraper._validate_south_dakota_live_static_title_catalog(units)
    assert len(units) == scraper.OFFICIAL_TITLE_COUNT == 71
    assert {unit["title_number"] for unit in units} >= {
        "23",
        "30",
        "33",
        "48",
        "58",
    }
    assert {unit["title_number"] for unit in units if unit["disposition"]} == {
        "27",
        "29",
        "51",
        "52",
        "57",
    }


def test_south_dakota_whole_title_parser_closes_operative_and_terminal_rows() -> None:
    payload = _south_dakota_title_payload("23A")
    rows, terminals, unresolved = parse_south_dakota_title_html_with_dispositions(
        payload.decode(),
        title_label="23A",
        source_url="https://sdlegislature.gov/api/Statutes/23A.html?all=true",
    )

    assert [row.section_number for row in rows] == ["23A-1-1"]
    assert [row.full_text for row in rows] == [
        "This is substantive official statutory text retained without truncation "
        "for the normalized corpus."
    ]
    assert [(row["section_number"], row["disposition"]) for row in terminals] == [
        ("23A-1-2", "repealed")
    ]
    assert unresolved == []
    assert source_bound_terminal_disposition("Prospective repeal procedure") == ""
    assert (
        source_bound_terminal_disposition(
            "Duties and responsibilities transferred--Successor authority"
        )
        == ""
    )
    assert source_bound_terminal_disposition("Transferred to § 3-8-2.1.") == (
        "transferred"
    )
    assert source_bound_terminal_disposition(
        "Interception Of Wire Or Oral Communications [Transferred And Repealed]"
    ) == "repealed"
    assert source_bound_terminal_disposition(
        "Commission On Children And Youth Repealed"
    ) == "repealed"
    assert source_bound_terminal_disposition(
        "Juvenile Courts Transferred"
    ) == "transferred"
    assert source_bound_terminal_disposition("to 12-8-5 Repealed.") == "repealed"
    assert source_bound_terminal_disposition(
        "Repealed SL 1998, ch 169, § 1"
    ) == "repealed"
    assert source_bound_terminal_disposition(
        "Temporary and executed"
    ) == "executed"
    assert source_bound_terminal_disposition(
        "Invalid enactment. Unconstitutional"
    ) == "unconstitutional"
    assert source_bound_terminal_disposition(
        "42-7B-16.2 to 42-7B-16.4. Not implemented"
    ) == "not_implemented"
    assert source_bound_terminal_disposition("Expired on June 30, 2012.") == (
        "expired"
    )
    assert source_bound_terminal_disposition("Superseded eff. Jan 19, 2018.") == (
        "superseded"
    )
    assert source_bound_terminal_disposition(
        "to 61-5-18.4. Temporary and obsolete."
    ) == "obsolete"


def test_south_dakota_parser_selects_exact_canonical_current_variant() -> None:
    current = (
        "<html><head><meta property='og:url' "
        "content='https://sdlegislature.gov/Statutes/10-1-28.2'></head><body>"
        "<p class='sabcNormal'><span class='sabcSENU'>10-1-28.2</span>. "
        "Current source label.</p>"
        "<p class='sabcStatute'>This is the currently canonical substantive "
        "statutory body selected at the observation date.</p>"
        "<p class='sabcNormal'>Source: SL 2026, ch 53, § 1.</p>"
        "</body></html>"
    )
    future = (
        "<html><head></head><body>"
        "<p class='sdefNormal'><span class='sdefSENU'>10-1-28.2</span>. "
        "Future source label.</p>"
        "<p class='sdefStatute'>This is a different future-effective statutory "
        "body that must not replace the canonical current page.</p>"
        "<p class='sdefNormal'>Source: SL 2026, ch 54, § 1, eff. Jan. 1, 2027.</p>"
        "</body></html>"
    )

    rows, terminals, unresolved = parse_south_dakota_title_html_with_dispositions(
        current + future,
        title_label="10",
        source_url="https://sdlegislature.gov/api/Statutes/10.html?all=true",
    )

    assert [row.section_number for row in rows] == ["10-1-28.2"]
    assert rows[0].full_text.startswith("This is the currently canonical")
    assert unresolved == []
    assert len(terminals) == 1
    assert terminals[0]["frontier_level"] == "section_lifecycle_variant"
    assert terminals[0]["disposition"] == "noncurrent_temporal_variant"
    assert terminals[0]["source_evidence"] == [
        "Source: SL 2026, ch 54, § 1, eff. Jan. 1, 2027."
    ]

    with pytest.raises(ValueError, match="canonical-current selector"):
        parse_south_dakota_title_html_with_dispositions(
            current.replace("<meta property='og:url' content='https://sdlegislature.gov/Statutes/10-1-28.2'>", "")
            + future,
            title_label="10",
        )


def test_south_dakota_parser_preserves_parenthetical_rule_identities() -> None:
    html = (
        "<html><body>"
        "<p class='sabcNormal'><span class='sabcSENU'>15-6-4(a)</span>. "
        "Summons--Form.</p>"
        "<p class='sabcStatute'>Substantive source text for rule subdivision a.</p>"
        "<p class='sdefNormal'><span class='sdefSENU'>15-6-4</span>"
        "<span class='sdefSENU'> (b)</span>. "
        "Summons served without complaint.</p>"
        "<p class='sdefStatute'>Substantive source text for rule subdivision b.</p>"
        "</body></html>"
    )
    rows, terminals, unresolved = parse_south_dakota_title_html_with_dispositions(
        html,
        title_label="15",
    )

    assert [row.section_number for row in rows] == ["15-6-4(a)", "15-6-4(b)"]
    assert terminals == []
    assert unresolved == []

    nested = html.replace(" (b)</span>", " (b)(1)</span>")
    nested_rows, nested_terminals, nested_unresolved = (
        parse_south_dakota_title_html_with_dispositions(
            nested,
            title_label="15",
        )
    )
    assert [row.section_number for row in nested_rows] == [
        "15-6-4(a)",
        "15-6-4(b)(1)",
    ]
    assert nested_terminals == []
    assert nested_unresolved == []


def test_south_dakota_parser_types_bodyless_parent_of_exact_child_rules() -> None:
    html = (
        "<html><body>"
        "<p class='sabcNormal'><span class='sabcSENU'>15-6-26</span>. "
        "Discovery pending action.</p>"
        "<p class='sdefNormal'><span class='sdefSENU'>15-6-26(a)</span>. "
        "Depositions before action.</p>"
        "<p class='sdefStatute'>This child rule has substantive official text "
        "and remains an independently indexed source identity.</p>"
        "<p class='seaaNormal'><span class='seaaSENU'>15-6-26(b)</span>. "
        "Perpetuation by action.</p>"
        "<p class='seaaStatute'>This second child rule also has substantive "
        "official text and remains independently indexed.</p>"
        "</body></html>"
    )

    rows, terminals, unresolved = parse_south_dakota_title_html_with_dispositions(
        html,
        title_label="15",
    )

    assert [row.section_number for row in rows] == ["15-6-26(a)", "15-6-26(b)"]
    assert unresolved == []
    assert terminals == [
        {
            "frontier_level": "section_source_status",
            "title_number": "15",
            "chapter_number": "6",
            "section_number": "15-6-26",
            "source_label": "Discovery pending action.",
            "source_url": "https://sdlegislature.gov/api/Statutes/15.html?all=true",
            "disposition": "source_collection_parent",
            "child_identity_count": 2,
            "child_identities_sha256": (
                "95b87f4a35de3652f8a8ae3a8d55bbb1683d1bbc3bab1efd8ccc1380045036a1"
            ),
        }
    ]


def test_south_dakota_parser_does_not_join_senu_range_word_to_identity() -> None:
    html = (
        "<html><body>"
        "<p class='sabcNormal'><span class='sabcSENU'>1-2-3</span>"
        "<span class='sabcSENU'> to 1-2-5.</span> Repealed.</p>"
        "</body></html>"
    )

    rows, terminals, unresolved = parse_south_dakota_title_html_with_dispositions(
        html,
        title_label="1",
    )

    assert rows == []
    assert [terminal["section_number"] for terminal in terminals] == ["1-2-3"]
    assert terminals[0]["disposition"] == "repealed"
    assert unresolved == []


def test_south_dakota_parser_recovers_source_bound_legacy_and_statute_number_html() -> None:
    legacy = (
        "<html><head><meta name='Description' content='South Dakota Codified Laws "
        "36-20B-36'></head><body><div>36-20B-36. Peer review as condition "
        "of renewal--Confidentiality.The board may require an applicant to "
        "undergo peer review under exact statutory conditions retained here."
        "<p><b>Source:</b> SL 2002, ch 1, § 1.</p></div></body></html>"
    )
    statute_number = (
        "<html><body>"
        "<p class='sabcStatuteNumber1'><span class='sabcSENU'>59-12-35</span>. "
        "Personal and family maintenance.</p>"
        "<p class='sabcStatuteNumber1'>(1) The agent may perform acts necessary "
        "to maintain the principal's customary standard of living.</p>"
        "<p class='sabcStatuteNumber2'>(a) This retained subdivision supplies "
        "additional substantive official statutory text.</p>"
        "</body></html>"
    )

    legacy_rows, legacy_terminals, legacy_unresolved = (
        parse_south_dakota_title_html_with_dispositions(
            legacy,
            title_label="36",
        )
    )
    numbered_rows, numbered_terminals, numbered_unresolved = (
        parse_south_dakota_title_html_with_dispositions(
            statute_number,
            title_label="59",
        )
    )

    assert [row.section_number for row in legacy_rows] == ["36-20B-36"]
    assert legacy_rows[0].section_name == (
        "Peer review as condition of renewal--Confidentiality."
    )
    assert legacy_rows[0].full_text.startswith("The board may require")
    assert legacy_terminals == []
    assert legacy_unresolved == []
    assert [row.section_number for row in numbered_rows] == ["59-12-35"]
    assert numbered_rows[0].full_text.startswith("(1) The agent may perform")
    assert numbered_terminals == []
    assert numbered_unresolved == []


def test_south_dakota_whole_title_tocs_are_independent_source_oracles() -> None:
    html = _south_dakota_title_payload("23A").decode()

    assert title_chapter_entries(html, title_label="23A") == [
        ("1", "Active source-derived chapter")
    ]
    assert title_section_entries(html, title_label="23A") == [
        ("23A-1-1", "Operative source-derived section"),
        ("23A-1-2", "Former provision [Repealed]"),
    ]


def test_south_dakota_section_toc_keeps_single_legacy_repealed_range() -> None:
    html = (
        "<html><body><p><a href='/statutes/DisplayStatute.aspx?Type=Statute&amp;"
        "Statute=12-28-1'>12-28-1</a> to 12-28-37. Repealed.</p></body></html>"
    )

    entries = title_section_entries(html, title_label="12")

    assert entries == [("12-28-1", "to 12-28-37. Repealed.")]
    assert source_bound_terminal_disposition(entries[0][1]) == "repealed"

    malformed_multi = (
        "<html><body><p>"
        "<a href='/statutes/DisplayStatute.aspx?Type=Statute&amp;"
        "Statute=29A-6-113'>29A-6-113</a> Rights at death. <br>"
        "<a href='/statutes/DisplayStatute.aspx?Type=Statute&amp;"
        "Statute=29A-6-114'>29A-6-114</a> Payment of P.O.D. "
        "PART 2. RESERVED. PART 3. UNIFORM TOD SECURITY REGISTRATION ACT."
        "</p></body></html>"
    )
    assert title_section_entries(malformed_multi, title_label="29A") == [
        ("29A-6-113", "Rights at death."),
        ("29A-6-114", "Payment of P.O.D."),
    ]


def test_south_dakota_chapter_toc_accepts_current_query_identity() -> None:
    html = (
        "<html><body>"
        "<p class='sabcB'><a href='https://sdlegislature.gov/Statutes?Statute=2-1'>"
        "01</a> Initiative And Referendum</p>"
        "<p class='sabcB'><a href='https://sdlegislature.gov/Statutes?Statute=2-2'>"
        "02</a> Legislative Districts</p>"
        "<p class='sdefB'><a href='https://sdlegislature.gov/Statutes?Statute=2-1-1'>"
        "2-1-1</a> Operative section</p>"
        "</body></html>"
    )

    assert title_chapter_entries(html, title_label="2") == [
        ("1", "Initiative And Referendum"),
        ("2", "Legislative Districts"),
    ]

    legacy_display_html = (
        "<html><body><p class='sabcB'>"
        "<a href='https://sdlegislature.gov/Statutes/Codified_Laws/"
        "DisplayStatute.aspx?Type=Statute&amp;Statute=3-6C'>"
        "06C</a> State Employment General Provisions</p></body></html>"
        "<html><body><p class='sdefB'>"
        "<a href='https://sdlegislature.gov/Statutes?Statute=3-6C'>"
        "3-6C</a>-1 Definition of terms.</p></body></html>"
    )
    assert title_chapter_entries(legacy_display_html, title_label="3") == [
        ("6C", "State Employment General Provisions")
    ]

    classless_multi_anchor_html = (
        "<html><body><p>Chapter "
        "<a href='/statutes/DisplayStatute.aspx?Type=Statute&amp;Statute=7-1'>"
        "01</a>. County Names And Boundaries "
        "<a href='/statutes/DisplayStatute.aspx?Type=Statute&amp;Statute=7-2'>"
        "02</a>. Consolidation And Change Of County Boundaries"
        "</p></body></html>"
    )
    assert title_chapter_entries(classless_multi_anchor_html, title_label="7") == [
        ("1", "County Names And Boundaries"),
        ("2", "Consolidation And Change Of County Boundaries"),
    ]

    nested_wrapper_html = classless_multi_anchor_html.replace(
        "<body><p>", "<body><p><p>"
    ).replace("</p></body>", "</p></p></body>")
    assert title_chapter_entries(nested_wrapper_html, title_label="7") == [
        ("1", "County Names And Boundaries"),
        ("2", "Consolidation And Change Of County Boundaries"),
    ]


def test_south_dakota_chapter_toc_types_one_terminal_lifecycle_variant() -> None:
    html = (
        "<html><body>"
        "<p class='sabcB'><a href='/Statutes/29A-1'>01</a> "
        "Curative Statutes [Repealed]</p>"
        "<p class='sdefB'><a href='/Statutes/29A-1'>01</a> "
        "General Provisions, Definitions And Probate Jurisdiction Of Court</p>"
        "</body></html>"
    )
    assert title_chapter_entries(html, title_label="29A") == [
        ("1", "Curative Statutes [Repealed]"),
        ("1", "General Provisions, Definitions And Probate Jurisdiction Of Court"),
    ]

    unresolved = html.replace("Curative Statutes [Repealed]", "First active label")
    with pytest.raises(ValueError, match="repeated unresolved chapter identity"):
        title_chapter_entries(unresolved, title_label="29A")


def test_south_dakota_strict_frontier_uses_one_plural_whole_title_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = SouthDakotaScraper("SD", "South Dakota")
    calls = _bind_south_dakota_plural_fetch(monkeypatch, scraper)

    rows = asyncio.run(
        scraper._scrape_strict_full_corpus_frontier(
            "South Dakota Codified Laws",
            record_primary=True,
            write_checkpoints=False,
        )
    )

    assert len(calls) == 2
    assert calls[0]["urls"] == [scraper.OFFICIAL_TITLE_API_URL]
    assert len(calls[1]["urls"]) == 66
    assert len(calls[1]["urls"]) == len(set(calls[1]["urls"]))
    assert {url.split("/", 3)[2] for url in calls[1]["urls"]} == {
        "sdlegislature.gov"
    }
    assert len(rows) == 66
    assert len({row.statute_id for row in rows}) == len(rows)
    frontier = scraper._last_south_dakota_full_frontier["frontier"]
    assert frontier["catalog_parity"] is True
    assert frontier["disposition"] == {
        "discovered": 137,
        "fetched": 66,
        "excluded": 71,
        "failed_final": 0,
        "duplicates": 0,
        "quarantined": 0,
    }


def test_south_dakota_strict_frontier_closes_all_terminal_active_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = SouthDakotaScraper("SD", "South Dakota")
    calls = _bind_south_dakota_plural_fetch(
        monkeypatch,
        scraper,
        toc_only_terminal_title="30",
    )

    rows = asyncio.run(
        scraper._scrape_strict_full_corpus_frontier(
            "South Dakota Codified Laws",
            record_primary=True,
            write_checkpoints=False,
        )
    )

    assert len(calls) == 2
    assert len(rows) == 65
    assert all(not row.section_number.startswith("30-") for row in rows)
    frontier = scraper._last_south_dakota_full_frontier["frontier"]
    assert frontier["terminal_section_count"] == 67
    assert frontier["disposition"] == {
        "discovered": 137,
        "fetched": 65,
        "excluded": 72,
        "failed_final": 0,
        "duplicates": 0,
        "quarantined": 0,
    }


def test_south_dakota_strict_frontier_pluralizes_only_residual_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = SouthDakotaScraper("SD", "South Dakota")
    calls = _bind_south_dakota_plural_fetch(
        monkeypatch,
        scraper,
        residual_section="1-1-3",
        terminal_chapter_title="1",
    )

    rows = asyncio.run(
        scraper._scrape_strict_full_corpus_frontier(
            "South Dakota Codified Laws",
            record_primary=True,
            write_checkpoints=False,
        )
    )

    assert [call["frontier_name"] for call in calls] == [
        "title-catalog",
        "whole-title-pages",
        "residual-section-pages",
    ]
    assert calls[2]["urls"] == [
        "https://sdlegislature.gov/api/Statutes/1-1-3.html?all=true"
    ]
    assert len(rows) == 67
    assert any(row.section_number == "1-1-3" for row in rows)
    assert all(row.section_number != "1-2-1" for row in rows)
    frontier = scraper._last_south_dakota_full_frontier["frontier"]
    assert frontier["request_batch_count"] == 3
    assert frontier["residual_section_fallback_count"] == 1
    assert frontier["terminal_chapter_count"] == 1
    assert frontier["disposition"] == {
        "discovered": 139,
        "fetched": 67,
        "excluded": 72,
        "failed_final": 0,
        "duplicates": 0,
        "quarantined": 0,
    }


def test_south_dakota_strict_frontier_accounts_for_chapter_lifecycle_variant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = SouthDakotaScraper("SD", "South Dakota")
    _bind_south_dakota_plural_fetch(
        monkeypatch,
        scraper,
        lifecycle_chapter_variant_title="1",
    )

    rows = asyncio.run(
        scraper._scrape_strict_full_corpus_frontier(
            "South Dakota Codified Laws",
            record_primary=True,
            write_checkpoints=False,
        )
    )

    assert len(rows) == 66
    frontier = scraper._last_south_dakota_full_frontier["frontier"]
    assert frontier["lifecycle_chapter_variant_count"] == 1
    assert frontier["terminal_chapter_count"] == 1
    assert any(
        unit.get("frontier_level") == "chapter_lifecycle_variant"
        and unit.get("title_number") == "1"
        and unit.get("chapter_number") == "1"
        for unit in frontier["terminal_units"]
    )
    assert frontier["disposition"] == {
        "discovered": 138,
        "fetched": 66,
        "excluded": 72,
        "failed_final": 0,
        "duplicates": 0,
        "quarantined": 0,
    }


def test_south_dakota_frontier_prefers_canonical_current_over_terminal_toc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = SouthDakotaScraper("SD", "South Dakota")
    _bind_south_dakota_plural_fetch(
        monkeypatch,
        scraper,
        lifecycle_section_variant_title="13",
    )

    rows = asyncio.run(
        scraper._scrape_strict_full_corpus_frontier(
            "South Dakota Codified Laws",
            record_primary=True,
            write_checkpoints=False,
        )
    )

    assert len(rows) == 66
    assert any(row.section_number == "13-1-1" for row in rows)
    frontier = scraper._last_south_dakota_full_frontier["frontier"]
    assert frontier["lifecycle_section_variant_count"] == 1
    assert any(
        unit.get("frontier_level") == "section_lifecycle_variant"
        and unit.get("section_number") == "13-1-1"
        and unit.get("disposition") == "noncurrent_temporal_variant"
        for unit in frontier["terminal_units"]
    )
    assert frontier["disposition"] == {
        "discovered": 138,
        "fetched": 66,
        "excluded": 72,
        "failed_final": 0,
        "duplicates": 0,
        "quarantined": 0,
    }


def test_south_dakota_frontier_accounts_for_collection_parent_source_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = SouthDakotaScraper("SD", "South Dakota")
    calls = _bind_south_dakota_plural_fetch(
        monkeypatch,
        scraper,
        source_collection_parent_title="15",
        source_collection_parent_toc_only=True,
    )

    rows = asyncio.run(
        scraper._scrape_strict_full_corpus_frontier(
            "South Dakota Codified Laws",
            record_primary=True,
            write_checkpoints=False,
        )
    )

    assert len(calls) == 2
    assert len(rows) == 68
    assert all(row.section_number != "15-1-3" for row in rows)
    assert {row.section_number for row in rows} >= {"15-1-3(a)", "15-1-3(b)"}
    frontier = scraper._last_south_dakota_full_frontier["frontier"]
    assert frontier["source_status_section_count"] == 1
    assert frontier["terminal_section_count"] == 66
    assert any(
        unit.get("frontier_level") == "section_source_status"
        and unit.get("section_number") == "15-1-3"
        and unit.get("disposition") == "source_collection_parent"
        for unit in frontier["terminal_units"]
    )
    assert frontier["disposition"] == {
        "discovered": 140,
        "fetched": 68,
        "excluded": 72,
        "failed_final": 0,
        "duplicates": 0,
        "quarantined": 0,
    }


def test_south_dakota_frontier_accounts_for_source_identity_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = SouthDakotaScraper("SD", "South Dakota")
    calls = _bind_south_dakota_plural_fetch(
        monkeypatch,
        scraper,
        source_identity_alias_title="57A",
    )

    rows = asyncio.run(
        scraper._scrape_strict_full_corpus_frontier(
            "South Dakota Codified Laws",
            record_primary=True,
            write_checkpoints=False,
        )
    )

    assert len(calls) == 2
    assert len(rows) == 67
    assert any(row.section_number == "57A-1-3A" for row in rows)
    assert all(row.section_number != "57A-1-3(A)" for row in rows)
    frontier = scraper._last_south_dakota_full_frontier["frontier"]
    assert frontier["source_status_section_count"] == 1
    assert any(
        unit.get("frontier_level") == "section_source_status"
        and unit.get("section_number") == "57A-1-3(A)"
        and unit.get("disposition") == "source_identity_alias"
        and unit.get("canonical_section_number") == "57A-1-3A"
        for unit in frontier["terminal_units"]
    )
    assert frontier["disposition"] == {
        "discovered": 139,
        "fetched": 67,
        "excluded": 72,
        "failed_final": 0,
        "duplicates": 0,
        "quarantined": 0,
    }


def test_south_dakota_strict_frontier_rejects_live_static_name_drift() -> None:
    scraper = SouthDakotaScraper("SD", "South Dakota")
    payload = json.loads(_south_dakota_catalog_payload(scraper))
    payload[0]["CatchLine"] = "Silent scope drift"
    units = scraper._parse_live_south_dakota_title_units(json.dumps(payload).encode())

    with pytest.raises(RuntimeError, match="catalog parity failed"):
        scraper._validate_south_dakota_live_static_title_catalog(units)


def test_south_dakota_closure_replays_exact_rows_and_public_law_rights(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = SouthDakotaScraper("SD", "South Dakota")
    _bind_south_dakota_plural_fetch(monkeypatch, scraper)
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="SD",
        parser_name="SouthDakotaScraper",
    )
    scraper.attach_state_law_acquisition_ledger(ledger)
    rows = asyncio.run(
        scraper._scrape_strict_full_corpus_frontier(
            "South Dakota Codified Laws",
            record_primary=True,
            write_checkpoints=False,
        )
    )
    projection = build_canonical_state_law_output_projection(
        [scraper._enrich_statute_structure(row).to_dict() for row in rows],
        jurisdiction="SD",
    )

    closure_path = asyncio.run(
        scraper.produce_state_law_frontier_closure(
            canonical_output_projection=projection,
        )
    )
    closure = json.loads(closure_path.read_text(encoding="utf-8"))
    receipt = closure["completion_receipt"]
    assert receipt["disposition"]["fetched"] == 66
    assert receipt["rights"] == {
        "basis": "public_law_no_state_copyright",
        "decision": "admit",
        "scope": "statutory_text",
    }
    assert receipt["frontier"] == closure["replayed_frontier"]
