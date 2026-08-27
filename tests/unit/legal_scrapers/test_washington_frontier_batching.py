from __future__ import annotations

import hashlib
import inspect
import json
import os
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.washington import (
    WashingtonScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.washington_section import (
    chapter_page_identity,
    dual_effective_section_contract,
    parse_washington_chapter_material_html,
    parse_washington_section_html,
    section_cite_belongs_to_chapter,
    section_page_identity,
    source_bound_terminal_disposition_from_chapter_html,
    source_bound_terminal_disposition_from_section_html,
)


def _root_html(titles: list[str]) -> bytes:
    anchors = "".join(
        f"<a href='default.aspx?Cite={title}'>Title {title}</a>" for title in titles
    )
    return f"<html><body>{anchors}</body></html>".encode()


def _title_html(title: str, chapters: list[str]) -> bytes:
    anchors = "".join(
        f"<a href='default.aspx?cite={chapter}'>{chapter}</a>"
        for chapter in chapters
    )
    return (
        f"<html><head><title>Title {title} RCW:</title></head><body>"
        "<div id='ContentPlaceHolder1_pnlTitleBlock'>"
        f"<h1>Title {title} RCW</h1></div>"
        f"<div id='contentWrapper' class='title-page'>{anchors}</div>"
        "</body></html>"
    ).encode()


def _chapter_html(chapter: str, sections: list[str]) -> bytes:
    rows = "".join(
        "<tr><td><a href='print'>HTML</a></td>"
        f"<td><a href='default.aspx?cite={section}'>{section}</a></td>"
        f"<td>Caption for {section}</td></tr>"
        for section in sections
    )
    return (
        f"<html><head><title>Chapter {chapter} RCW:</title></head><body>"
        "<div id='ContentPlaceHolder1_pnlTitleBlock'>"
        f"<h1>Chapter {chapter} RCW</h1></div>"
        f"<div id='contentWrapper' class='chapter-page'><table>{rows}</table></div>"
        "</body></html>"
    ).encode()


def _ucc_article_html(chapter: str, article: str, sections: list[str]) -> bytes:
    rows = "".join(
        "<tr><td><a href='print'>HTML</a></td>"
        f"<td><a href='default.aspx?cite={section}'>{section}</a></td>"
        f"<td>Caption for {section}</td></tr>"
        for section in sections
    )
    return (
        f"<html><head><title>Chapter {chapter} RCW:</title></head><body>"
        "<div id='ContentPlaceHolder1_pnlTitleBlock'>"
        f"<h1>Article {article}</h1><h2>GENERAL PROVISIONS</h2></div>"
        "<div id='contentWrapper' class='chapter-page'>"
        f"<h3 class='list-heading'>Sections</h3><table>{rows}</table></div>"
        "</body></html>"
    ).encode()


def _zero_row_chapter_html(chapter: str, wrapper_body: str = "") -> bytes:
    return (
        f"<html><head><title>Chapter {chapter} RCW:</title></head><body>"
        "<div id='ContentPlaceHolder1_pnlTitleBlock'>"
        f"<h1>Chapter {chapter} RCW</h1></div>"
        f"<div id='contentWrapper' class='chapter-page'>{wrapper_body}</div>"
        "</body></html>"
    ).encode()


def _section_html(
    section: str,
    *,
    caption: str = "Current official section.",
    body: str | None = None,
) -> bytes:
    section_body = (
        "Current Washington statutory text. " * 8 if body is None else body
    )
    return (
        f"<html><head><title>RCW {section}:</title></head><body>"
        "<div id='ContentPlaceHolder1_pnlTitleBlock'>"
        f"<h1>RCW {section}</h1><h2>{caption}</h2></div>"
        "<div id='contentWrapper' class='section-page'>"
        f"<div></div><div></div><div>{section_body}</div></div>"
        "</body></html>"
    ).encode()


_RETAINED_SHORT_OPERATIVE_EVIDENCE = {
    "2.78.900": {
        "content_sha256": (
            "7e605e1f20d1e88abb016618b6c598d4b5a5add9230c3a07996363f901dc248f"
        ),
        "receipt_sha256": (
            "9cbc69652d3088971b732d4d09fa3950c6d73bbbc95e6b4c4c6191b9b23fde64"
        ),
        "content_cid": (
            "bafkreid6mbpb6igr5cflwalgdc3mlgguwws23wjdbq5apgldmp4qdxber4"
        ),
        "receipt_cid": (
            "bafkreie4xruwkljqrclrw4znjue7uokqy3ltxo6jlzvuytdbsg43ep66mq"
        ),
        "body": "This chapter expires December 31, 2029.",
    },
    "6.23.011": {
        "content_sha256": (
            "b2948dac6c95d0f21a1b7eb8da2a82b095333af0c40177409ccb68b2fe16105a"
        ),
        "receipt_sha256": (
            "622f046d040aa209ae9f851ff1ba5c9764cad9d455fbecf77c14c8bd42e128ef"
        ),
        "content_cid": (
            "bafkreifsssg2y3ev2dzbug36xdncvavqsuztv4geaf3ubhglnczp4fqqli"
        ),
        "receipt_cid": (
            "bafkreidcf4cg2bakuie25h4fd7y3uxexmtfntvcv7pwpo7auzc6ufyji54"
        ),
        "body": "See RCW 61.12.093 through 61.12.095 .",
    },
    "7.04A.900": {
        "content_sha256": (
            "3c0b24f452b34c5bea5a6f1b121df2e7b9a092fee5dbf855d53f747d3d8aded6"
        ),
        "receipt_sha256": (
            "7ce319c6e556582d04581a152ec694aa1c653249b9afaa9ebd28d01acda97bad"
        ),
        "content_cid": (
            "bafkreib4bmspiuvtjrn6uwtpdmjb34xhxgqjf7xf3p4flvj7or6t3cw62y"
        ),
        "receipt_cid": (
            "bafkreid44mm4nzkwlawqiwa2cuxmnffkdrstesnzv6vj5pji2anm3kl3vu"
        ),
        "body": "This act takes effect January 1, 2006.",
    },
}


def _dual_effective_section_html(
    section: str = "2.10.155",
    *,
    boundary: str = "June 30, 2029",
) -> bytes:
    base_caption = (
        "Suspension of retirement allowance upon employment"
        "<span>—</span>Exceptions<span>—</span>Reinstatement"
        "<span>—</span>Pro tempore service."
    )
    title_caption = (
        "Suspension of retirement allowance upon employment—Exceptions—"
        "Reinstatement—Pro tempore service."
    )
    current_body = "Current-until Washington statutory text. " * 8
    future_body = "Future-effective Washington statutory text. " * 8
    return (
        "<html><head>"
        f"<title>RCW {section}: {title_caption} "
        f"(<i>Effective {boundary}.</i>)</title>"
        "</head><body>"
        "<div id='ContentPlaceHolder1_pnlTitleBlock'>"
        f"<h1>RCW {section}</h1>"
        f"<h2>{base_caption} (Effective until {boundary}.)</h2>"
        "</div>"
        "<div id='contentWrapper' class='section-page'>"
        "<div></div><div></div>"
        f"<div>{current_body}</div>"
        "<div style='margin-top:15pt;margin-bottom:0pt;'>"
        "[ 1990 c 274 s 14 ; 1988 c 109 s 10 .]</div>"
        "<div><h3>Notes:</h3></div><div>Current-version note.</div>"
        "<div><div><div>"
        f"<h3 class='h1'>RCW {section}</h3>"
        "</div></div></div>"
        "<div><div><div>"
        f"<h4 class='h2'>{base_caption} (Effective {boundary}.)</h4>"
        "</div></div></div>"
        f"<div>{future_body}</div>"
        "<div style='margin-top:15pt;margin-bottom:0pt;'>"
        "[ 2026 c 261 s 401 ; 1990 c 274 s 14 ; 1988 c 109 s 10 .]"
        "</div>"
        "<div><h3>Notes:</h3></div><div>Future-version note.</div>"
        "</div></body></html>"
    ).encode()


def _frontier_result(
    urls: list[str],
    pages: dict[str, bytes],
    *,
    retrieved_at: str = "2026-08-25T11:06:45.054000Z",
) -> StateLawPageMultiFetchResult:
    payloads = [pages[url] for url in urls]
    transport_receipts: list[dict[str, str]] = []
    envelopes: list[dict[str, Any]] = []
    for url, payload in zip(urls, payloads, strict=True):
        digest = hashlib.sha256(payload).hexdigest()
        transport = {
            "content_sha256": digest,
            "official_url": url,
            "source_transport": "direct",
        }
        transport_receipts.append(transport)
        envelopes.append(
            {
                "acquisition": {
                    "body_sha256": digest,
                    "receipt": {
                        "content": {"sha256": digest},
                        "endpoint": url,
                        "metadata": {"transport_receipt": transport},
                        "receipt_sha256": f"receipt-{digest}",
                        "retrieved_at": retrieved_at,
                    },
                }
            }
        )
    return StateLawPageMultiFetchResult(
        urls=urls,
        payloads=payloads,
        errors=[None] * len(urls),
        transport_receipts=transport_receipts,
        parser_input_envelopes=envelopes,
        stats={"requested_pages": len(urls)},
    )


def test_washington_frontier_identity_binds_parser_and_plural_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = WashingtonScraper("WA", "Washington")

    dependencies = scraper.state_law_frontier_source_dependencies()

    assert [dependency.__name__.rsplit(".", 1)[-1] for dependency in dependencies] == [
        "base_scraper",
        "state_archival_fetch",
        "strict_frontier_closure",
        "washington_section",
        "wayback_machine_engine",
    ]
    baseline = scraper._state_law_frontier_source_software_version()
    assert baseline.startswith(
        "ipfs_datasets_py.processors.legal_scrapers.state_scrapers.washington."
        "WashingtonScraper@sha256:"
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


def test_washington_frontier_validator_keeps_statutory_access_denied_text() -> None:
    valid_chapter = _chapter_html("90.64", ["90.64.200"]).replace(
        b"Caption for 90.64.200",
        b"Inspecting and investigating dairy nutrient management operations -- Access denied",
    )
    valid_section = _section_html(
        "90.64.200",
        caption="Inspecting and investigating -- Access denied -- Search warrant.",
    )

    assert WashingtonScraper._is_valid_washington_frontier_payload(valid_chapter)
    assert WashingtonScraper._is_valid_washington_frontier_payload(valid_section)
    assert not WashingtonScraper._is_valid_washington_frontier_payload(
        b"<html><body><div id='contentWrapper'>Access denied</div></body></html>"
    )


@pytest.mark.parametrize(
    "cite",
    [
        "6.40A.010",
        "28A.600.010",
        "35A.02.010",
        "9A.32.030",
        "62A.1-101",
        "62A.2A-101",
    ],
)
def test_washington_section_cite_accepts_alpha_suffix_on_each_segment(
    cite: str,
) -> None:
    assert WashingtonScraper._SECTION_CITE_RE.fullmatch(cite)


@pytest.mark.parametrize(
    "cite",
    ["6.40-A.010", "6..010", "6.40A.", "chapter-6.40A.010"],
)
def test_washington_section_cite_rejects_malformed_or_decorated_values(
    cite: str,
) -> None:
    assert WashingtonScraper._SECTION_CITE_RE.fullmatch(cite) is None


@pytest.mark.parametrize(
    ("chapter", "article", "section"),
    [
        ("62A.1", "1", "62A.1-101"),
        ("62A.2A", "2A", "62A.2A-101"),
    ],
)
def test_washington_ucc_article_chapter_identity_is_source_shaped(
    chapter: str,
    article: str,
    section: str,
) -> None:
    html = _ucc_article_html(chapter, article, [section]).decode()

    assert chapter_page_identity(html) == chapter
    assert WashingtonScraper._washington_index_page_identity(
        html,
        kind="chapter",
    ) == chapter
    assert WashingtonScraper._SECTION_CITE_RE.fullmatch(section)
    assert section_cite_belongs_to_chapter(section, chapter)


@pytest.mark.parametrize(
    ("chapter", "article", "section"),
    [
        ("62A.1", "2", "62A.1-101"),
        ("62A.1", "1", "62A.2-101"),
        ("62A.1", "1", "1.01.010"),
    ],
)
def test_washington_ucc_article_identity_rejects_drift(
    chapter: str,
    article: str,
    section: str,
) -> None:
    html = _ucc_article_html(chapter, article, [section]).decode()

    assert chapter_page_identity(html) is None
    assert (
        WashingtonScraper._washington_index_page_identity(html, kind="chapter")
        == ""
    )


def test_washington_ucc_section_page_normalizes_with_exact_identity() -> None:
    section = "62A.1-101"
    html = _section_html(section).decode()

    assert section_page_identity(html) == section
    row = parse_washington_section_html(
        html,
        source_url=f"https://app.leg.wa.gov/RCW/default.aspx?cite={section}",
        section_number=section,
    )

    assert row is not None
    assert row.section_number == section
    assert row.title_number == "62A"


def test_washington_dual_effective_page_selects_by_source_observation_date() -> None:
    section = "2.10.155"
    html = _dual_effective_section_html(section).decode()
    url = f"https://app.leg.wa.gov/RCW/default.aspx?cite={section}"

    contract = dual_effective_section_contract(html)
    current = parse_washington_section_html(
        html,
        source_url=url,
        section_number=section,
        as_of_date=date(2026, 8, 25),
    )
    future = parse_washington_section_html(
        html,
        source_url=url,
        section_number=section,
        as_of_date=date(2029, 6, 30),
    )

    assert section_page_identity(html) == section
    assert contract is not None
    assert contract["boundary_date"] == date(2029, 6, 30)
    assert current is not None
    assert current.full_text.startswith("Current-until")
    assert current.metadata.effective_date is None
    assert current.structured_data["effective_variant_count"] == 2
    assert current.structured_data["effective_variant_selected_index"] == 0
    assert current.structured_data["effective_variant_excluded_indexes"] == [1]
    assert (
        current.structured_data["effective_variant_selection"]
        == "source_observation_date"
    )
    assert (
        current.structured_data["effective_variant_as_of_date"]
        == "2026-08-25"
    )
    assert len(current.structured_data["effective_variants"]) == 2
    assert current.metadata.history == [
        "[ 1990 c 274 s 14 ; 1988 c 109 s 10 .]"
    ]
    assert future is not None
    assert future.full_text.startswith("Future-effective")
    assert future.metadata.effective_date == "2029-06-30"
    assert future.structured_data["effective_variant_selected_index"] == 1
    assert future.structured_data["effective_variant_excluded_indexes"] == [0]


def test_washington_dual_effective_page_requires_explicit_as_of_and_source() -> None:
    section = "2.10.155"
    html = _dual_effective_section_html(section).decode()
    url = f"https://app.leg.wa.gov/RCW/default.aspx?cite={section}"

    assert (
        parse_washington_section_html(
            html,
            source_url=url,
            section_number=section,
        )
        is None
    )
    assert (
        parse_washington_section_html(
            html,
            source_url=f"{url}.drift",
            section_number=section,
            as_of_date=date(2026, 8, 25),
        )
        is None
    )


@pytest.mark.parametrize(
    ("old", "new", "count"),
    [
        (
            "<h3 class='h1'>RCW 2.10.155</h3>",
            "<h3 class='h1'>RCW 2.10.156</h3>",
            1,
        ),
        ("class='section-page'", "class='section-page-drift'", 1),
        (
            "(Effective until June 30, 2029.)</h2>",
            "(Effective until July 1, 2029.)</h2>",
            1,
        ),
        (
            "(Effective June 30, 2029.)</h4>",
            "(Effective July 1, 2029.)</h4>",
            1,
        ),
        (
            "<i>Effective June 30, 2029.</i>",
            "<i>Effective July 1, 2029.</i>",
            1,
        ),
        ("margin-top:15pt", "margin-top:14pt", 1),
        ("<div><h3>Notes:</h3></div>", "<div>Notes drift.</div>", 1),
    ],
)
def test_washington_dual_effective_identity_rejects_structural_drift(
    old: str,
    new: str,
    count: int,
) -> None:
    html = _dual_effective_section_html().decode().replace(old, new, count)

    assert dual_effective_section_contract(html) is None
    assert section_page_identity(html) is None
    assert (
        parse_washington_section_html(
            html,
            source_url="https://app.leg.wa.gov/RCW/default.aspx?cite=2.10.155",
            section_number="2.10.155",
            as_of_date=date(2026, 8, 25),
        )
        is None
    )


@pytest.mark.parametrize(
    ("section", "caption", "body", "history"),
    [
        (
            "1.70.903",
            "Effective date — 2017 c 106.",
            "This act takes effect January 1, 2018.",
            "<div style='margin-top:15pt'>[ 2017 c 106 s 13 .]</div>",
        ),
        (
            "2.06.045",
            "When open for transaction of business.",
            "See RCW 2.04.030 .",
            "",
        ),
        (
            "2.76.900",
            "Expiration date.",
            "This chapter expires January 1, 2031.",
            "<div style='margin-top:15pt'>[ 2025 c 398 s 4 ; 2022 c 284 s 5 .]</div>",
        ),
        (
            "2.78.900",
            "Expiration date.",
            "This chapter expires December 31, 2029.",
            "<div style='margin-top:15pt'>[ 2026 c 199 s 6 .]</div>",
        ),
        (
            "4.84.320",
            (
                "Attorneys' fees in actions for injuries resulting from the "
                "rendering of medical and other health care."
            ),
            "See RCW 7.70.070 .",
            "",
        ),
        (
            "6.23.011",
            (
                "Voluntary relinquishment of ownership rights by mortgagor may "
                "result in loss of redemption rights."
            ),
            "See RCW 61.12.093 through 61.12.095 .",
            "",
        ),
        (
            "7.04A.900",
            "Effective date — 2005 c 433.",
            "This act takes effect January 1, 2006.",
            "<div style='margin-top:15pt'>[ 2005 c 433 s 51 .]</div>",
        ),
    ],
)
def test_washington_exact_short_operative_sections_are_retained(
    section: str,
    caption: str,
    body: str,
    history: str,
) -> None:
    payload = _section_html(section, caption=caption, body=body).replace(
        b"</div></body></html>",
        f"{history}</div></body></html>".encode(),
    )
    url = f"https://app.leg.wa.gov/RCW/default.aspx?cite={section}"

    row = parse_washington_section_html(
        payload.decode(),
        source_url=url,
        section_number=section,
    )

    assert row is not None
    assert row.section_number == section
    assert row.full_text == body
    assert row.structured_data["source_bound_short_operative"] is True
    assert (
        parse_washington_section_html(
            payload.decode(),
            source_url=f"{url}.drift",
            section_number=section,
        )
        is None
    )
    assert (
        parse_washington_section_html(
            payload.decode().replace(body, f"{body} drift"),
            source_url=url,
            section_number=section,
        )
        is None
    )
    assert (
        parse_washington_section_html(
            payload.decode().replace(caption, f"{caption} drift"),
            source_url=url,
            section_number=section,
        )
        is None
    )
    history_drift = payload.replace(
        b"</div></body></html>",
        (
            b"<div style='margin-top:15pt'>[ 1900 c 1 s 1 .]</div>"
            b"</div></body></html>"
        ),
    )
    assert (
        parse_washington_section_html(
            history_drift.decode(),
            source_url=url,
            section_number=section,
        )
        is None
    )


@pytest.mark.parametrize(
    ("section", "evidence"),
    sorted(_RETAINED_SHORT_OPERATIVE_EVIDENCE.items()),
)
def test_washington_short_operative_replays_retained_contract(
    section: str,
    evidence: dict[str, str],
) -> None:
    evidence_root = os.getenv("STATE_LAWS_TEST_WA_EVIDENCE_ROOT", "").strip()
    if not evidence_root:
        pytest.skip("requires retained Washington acquisition evidence")

    jurisdiction_root = Path(evidence_root) / "WA"
    fetch_path = (
        jurisdiction_root
        / "fetches"
        / f'{evidence["receipt_sha256"]}.json'
    )
    fetch = json.loads(fetch_path.read_text(encoding="utf-8"))
    payload = (jurisdiction_root / fetch["body_relative_path"]).read_bytes()
    assert hashlib.sha256(payload).hexdigest() == evidence["content_sha256"]

    url = f"https://app.leg.wa.gov/RCW/default.aspx?cite={section}"
    receipt = fetch["parser_input_envelope"]["acquisition"]["receipt"]
    assert fetch["authorizes_parser_admission"] is True
    assert receipt["endpoint"] == url
    assert receipt["response_status"] == 200
    assert receipt["content"]["sha256"] == evidence["content_sha256"]
    assert receipt["content"]["cid"] == evidence["content_cid"]
    assert receipt["receipt_sha256"] == evidence["receipt_sha256"]
    assert receipt["receipt_cid"] == evidence["receipt_cid"]

    row = parse_washington_section_html(
        payload.decode("utf-8", errors="replace"),
        source_url=url,
        section_number=section,
    )
    assert row is not None
    assert row.section_number == section
    assert row.full_text == evidence["body"]
    assert row.structured_data["source_bound_short_operative"] is True


@pytest.mark.parametrize(
    ("chapter", "wrapper_body", "expected"),
    [
        (
            "14.30",
            "<a class='btn'>PDF</a><h3>See chapter 81.96 RCW</h3>",
            {"disposition": "cross_reference", "target_chapter": "81.96"},
        ),
        (
            "18.09",
            "<div>Notes: See chapter 2.44 RCW, attorneys-at-law.</div>",
            {
                "disposition": "notes_only_cross_reference",
                "target_chapter": "2.44",
            },
        ),
        (
            "76.10",
            (
                "<div>Notes: Reviser's note: The act has been codified as "
                "chapter 78.44 RCW.</div>"
            ),
            {"disposition": "recodified", "target_chapter": "78.44"},
        ),
        ("48.26", "", {"disposition": "reserved"}),
    ],
)
def test_washington_zero_row_chapters_are_source_bound(
    chapter: str,
    wrapper_body: str,
    expected: dict[str, str],
) -> None:
    html = _zero_row_chapter_html(chapter, wrapper_body).decode()
    source_url = f"https://app.leg.wa.gov/RCW/default.aspx?cite={chapter}"

    assert chapter_page_identity(html) == chapter
    assert source_bound_terminal_disposition_from_chapter_html(
        html,
        source_url=source_url,
        chapter_number=chapter,
    ) == expected
    assert (
        source_bound_terminal_disposition_from_chapter_html(
            html,
            source_url=f"{source_url}.drift",
            chapter_number=chapter,
        )
        is None
    )


def test_washington_unknown_empty_chapter_fails_closed() -> None:
    chapter = "14.31"
    html = _zero_row_chapter_html(chapter).decode()

    assert (
        source_bound_terminal_disposition_from_chapter_html(
            html,
            source_url=f"https://app.leg.wa.gov/RCW/default.aspx?cite={chapter}",
            chapter_number=chapter,
        )
        is None
    )


@pytest.mark.parametrize(
    ("chapter", "plan_kind", "district_marker"),
    [
        ("29A.76C", "congressional_redistricting_plan", "District 10:"),
        ("44.07F", "legislative_redistricting_plan", "District 49:"),
    ],
)
def test_washington_source_bound_redistricting_chapters_are_normalized(
    chapter: str,
    plan_kind: str,
    district_marker: str,
) -> None:
    html = _zero_row_chapter_html(
        chapter,
        (
            "<a class='btn hidden-print'>PDF</a>"
            "<p>Washington State Redistricting Commission final plan.</p>"
            "<h2>Congressional Districts</h2>"
            "<h2>Legislative Districts</h2>"
            f"<p>{district_marker} Exact official district description.</p>"
        ),
    ).decode()
    source_url = f"https://app.leg.wa.gov/RCW/default.aspx?cite={chapter}"

    row = parse_washington_chapter_material_html(
        html,
        source_url=source_url,
        chapter_number=chapter,
    )

    assert row is not None
    assert row.section_number == chapter
    assert row.source_url == source_url
    assert row.structured_data["record_level"] == "chapter_material"
    assert row.structured_data["record_type"] == plan_kind
    assert "PDF" not in row.full_text
    assert (
        parse_washington_chapter_material_html(
            html,
            source_url=f"{source_url}.drift",
            chapter_number=chapter,
        )
        is None
    )


@pytest.mark.asyncio
async def test_washington_frontier_batch_uses_shared_grouped_warc_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls = [
        "https://app.leg.wa.gov/RCW/default.aspx?cite=1.01.010",
        "https://app.leg.wa.gov/RCW/default.aspx?cite=1.01.020",
    ]
    observed: list[tuple[list[str], dict[str, Any]]] = []

    async def _plural(self, requested, **kwargs):
        requested = list(requested)
        observed.append((requested, dict(kwargs)))
        return StateLawPageMultiFetchResult(
            urls=requested,
            payloads=[b"one", b"two"],
            errors=[None, None],
            transport_receipts=[{}, {}],
            parser_input_envelopes=[None, None],
            stats={"requested_pages": 2},
        )

    monkeypatch.setattr(
        WashingtonScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    scraper = WashingtonScraper("WA", "Washington")

    batch = await scraper._fetch_washington_frontier_batch(
        urls,
        frontier_name="sections",
    )

    assert batch.urls == urls
    assert batch.payloads == [b"one", b"two"]
    validator = observed[0][1].pop("content_validator")
    assert validator(b"<div id='contentWrapper'>official RCW</div>") is True
    assert validator(b"<html>Access Denied</html>") is False
    assert observed == [
        (
            urls,
            {
                "residual_retry_attempts": 1,
                "timeout_seconds": 25,
                "media_type": "text/html",
                "max_concurrency": 16,
                "prefer_direct": True,
                "common_crawl_domain_terms": ("app.leg.wa.gov",),
                "common_crawl_url_terms": ("/RCW/",),
                "common_crawl_mime_terms": ("html",),
                "repeat_grouped_archive_inventory_on_residual": False,
                "wayback_prefix_inventory": True,
            },
        )
    ]


def test_washington_archived_section_context_uses_capture_date_and_exact_bytes() -> None:
    url = "https://app.leg.wa.gov/RCW/default.aspx?cite=2.10.155"
    pages = {url: _dual_effective_section_html()}
    batch = _frontier_result(
        [url],
        pages,
        retrieved_at="2031-01-02T03:04:05Z",
    )
    batch.transport_receipts[0]["source_transport"] = "wayback"
    batch.transport_receipts[0]["archive_timestamp"] = "20300101000000"
    retained_transport = batch.parser_input_envelopes[0]["acquisition"][
        "receipt"
    ]["metadata"]["transport_receipt"]
    retained_transport["source_transport"] = "wayback"
    retained_transport["archive_timestamp"] = "20300101000000"

    context = WashingtonScraper._washington_section_evidence_context(
        source_url=url,
        payload=pages[url],
        transport_receipt=batch.transport_receipts[0],
        parser_input_envelope=batch.parser_input_envelopes[0],
    )
    row = parse_washington_section_html(
        pages[url].decode(),
        source_url=url,
        section_number="2.10.155",
        as_of_date=context["as_of_date"],
    )

    assert context["as_of_date"] == date(2030, 1, 1)
    assert context["source_transport"] == "wayback"
    assert row is not None
    assert row.full_text.startswith("Future-effective")
    with pytest.raises(RuntimeError, match="changed parser bytes"):
        WashingtonScraper._washington_section_evidence_context(
            source_url=url,
            payload=pages[url] + b"drift",
            transport_receipt=batch.transport_receipts[0],
            parser_input_envelope=batch.parser_input_envelopes[0],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_kind", ["reordered", "missing", "short"])
async def test_washington_frontier_batch_fails_closed_on_alignment_or_gap(
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    urls = [
        "https://app.leg.wa.gov/RCW/default.aspx?cite=1.01.010",
        "https://app.leg.wa.gov/RCW/default.aspx?cite=1.01.020",
    ]

    async def _plural(self, requested, **_kwargs):
        requested = list(requested)
        returned = list(reversed(requested)) if failure_kind == "reordered" else requested
        errors = [None, "unavailable" if failure_kind == "missing" else None]
        if failure_kind == "short":
            errors = errors[:1]
        return StateLawPageMultiFetchResult(
            urls=returned,
            payloads=[b"one", b"" if failure_kind == "missing" else b"two"],
            errors=errors,
            transport_receipts=[{}, {}],
            parser_input_envelopes=[None, None],
            stats={},
        )

    monkeypatch.setattr(
        WashingtonScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    scraper = WashingtonScraper("WA", "Washington")

    with pytest.raises(
        RuntimeError,
        match="changed URL order|unresolved exact URLs|unaligned acquisition rows",
    ):
        await scraper._fetch_washington_frontier_batch(
            urls,
            frontier_name="sections",
        )


@pytest.mark.asyncio
async def test_washington_unbounded_uses_one_global_section_wave(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_url = "https://app.leg.wa.gov/RCW/default.aspx"
    title_urls = [
        f"{root_url}?cite=1",
        f"{root_url}?cite=2",
        f"{root_url}?cite=29A",
        f"{root_url}?cite=62A",
    ]
    chapter_urls = [
        f"{root_url}?cite=1.01",
        f"{root_url}?cite=2.01",
        f"{root_url}?cite=2.02",
        f"{root_url}?cite=2.10",
        f"{root_url}?cite=29A.76C",
        f"{root_url}?cite=62A.1",
    ]
    section_urls = [
        f"{root_url}?cite=1.01.010",
        f"{root_url}?cite=2.01.010",
        f"{root_url}?cite=2.10.155",
        f"{root_url}?cite=62A.1-101",
    ]
    pages = {
        root_url: _root_html(["1", "2", "29A", "62A"]),
        title_urls[0]: _title_html("1", ["1.01"]),
        title_urls[1]: _title_html("2", ["2.01", "2.02", "2.10"]),
        title_urls[2]: _title_html("29A", ["29A.76C"]),
        title_urls[3]: _title_html("62A", ["62A.1"]),
        chapter_urls[0]: _chapter_html("1.01", ["1.01.010"]),
        chapter_urls[1]: _chapter_html("2.01", ["2.01.010"]),
        chapter_urls[2]: _zero_row_chapter_html(
            "2.02",
            "<a class='btn'>PDF</a><h3>See chapter 3.46 RCW</h3>",
        ),
        chapter_urls[3]: _chapter_html("2.10", ["2.10.155"]),
        chapter_urls[4]: _zero_row_chapter_html(
            "29A.76C",
            (
                "<p>Washington State Redistricting Commission final plan.</p>"
                "<h2>Congressional Districts</h2>"
                "<p>District 10: Exact official district description.</p>"
            ),
        ),
        chapter_urls[5]: _ucc_article_html("62A.1", "1", ["62A.1-101"]),
        section_urls[0]: _section_html("1.01.010"),
        section_urls[1]: _section_html(
            "2.01.010",
            caption="Reserved.",
            body="",
        ),
        section_urls[2]: _dual_effective_section_html(),
        section_urls[3]: _section_html("62A.1-101"),
    }
    batch_calls: list[tuple[str, list[str]]] = []
    checkpoints: list[tuple[str, bool, dict[str, Any]]] = []

    async def _batch(self, urls, *, frontier_name: str):
        requested = list(urls)
        batch_calls.append((frontier_name, requested))
        return _frontier_result(requested, pages)

    async def _single_must_not_run(*_args, **_kwargs):
        raise AssertionError("unbounded Washington must use the plural frontier path")

    def _checkpoint(
        self,
        statutes,
        *,
        stage_label: str,
        replace_existing_rows: bool = False,
        extra=None,
        **_kwargs,
    ):
        checkpoints.append(
            (stage_label, replace_existing_rows, dict(extra or {}))
        )
        return True

    def _stale_checkpoint_must_not_load(*_args, **_kwargs):
        raise AssertionError("unbounded Washington must rebuild its retained frontier")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv("STATE_SCRAPER_WA_SECTION_BATCH_SIZE", "2")
    monkeypatch.setattr(
        WashingtonScraper,
        "OFFICIAL_TITLES",
        (
            ("1", "One"),
            ("2", "Two"),
            ("29A", "Elections"),
            ("62A", "Uniform Commercial Code"),
        ),
    )
    monkeypatch.setattr(WashingtonScraper, "_fetch_washington_frontier_batch", _batch)
    monkeypatch.setattr(
        WashingtonScraper,
        "_fetch_page_content_with_archival_fallback",
        _single_must_not_run,
    )
    monkeypatch.setattr(WashingtonScraper, "_write_partial_checkpoint", _checkpoint)
    monkeypatch.setattr(
        WashingtonScraper,
        "_load_partial_checkpoint_statutes",
        _stale_checkpoint_must_not_load,
    )
    monkeypatch.setattr(
        WashingtonScraper,
        "_load_partial_checkpoint_progress",
        _stale_checkpoint_must_not_load,
    )
    scraper = WashingtonScraper("WA", "Washington")

    rows = await scraper._scrape_official_index(
        "Revised Code of Washington",
        max_statutes=None,
    )

    assert [row.section_number for row in rows] == [
        "1.01.010",
        "2.10.155",
        "29A.76C",
        "62A.1-101",
    ]
    assert [row.source_url for row in rows] == [
        section_urls[0],
        section_urls[2],
        chapter_urls[4],
        section_urls[3],
    ]
    dual_row = rows[1]
    assert dual_row.full_text.startswith("Current-until")
    assert dual_row.structured_data["effective_variant_selected_index"] == 0
    assert dual_row.structured_data["source_observed_date"] == "2026-08-25"
    assert dual_row.structured_data["source_transport"] == "direct"
    assert dual_row.structured_data["content_sha256"] == hashlib.sha256(
        pages[section_urls[2]],
    ).hexdigest()
    assert batch_calls == [
        ("root-index", [root_url]),
        ("title-index", title_urls),
        ("chapter-index", chapter_urls),
        ("section-frontier", section_urls),
    ]
    assert all(replace for _stage, replace, _extra in checkpoints)
    assert checkpoints[-1][0] == "washington:complete"
    assert checkpoints[-1][2]["terminal_chapters_classified"] == 1
    assert checkpoints[-1][2]["terminal_chapter_dispositions"] == [
        {
            "chapter_number": "2.02",
            "source_url": chapter_urls[2],
            "disposition": "cross_reference",
            "target_chapter": "3.46",
        }
    ]
    assert checkpoints[-1][2]["chapter_materials_admitted"] == 1
    assert checkpoints[-1][2]["chapter_material_records"] == [
        {
            "chapter_number": "29A.76C",
            "record_type": "congressional_redistricting_plan",
            "source_url": chapter_urls[4],
        }
    ]
    assert checkpoints[-1][2]["terminal_sections_classified"] == 1
    assert checkpoints[-1][2]["terminal_section_dispositions"] == [
        {
            "chapter_number": "2.01",
            "section_number": "2.01.010",
            "disposition": "reserved",
            "source_url": section_urls[1],
            "source_observed_date": "2026-08-25",
            "source_transport": "direct",
            "parser_input_receipt_sha256": (
                "receipt-"
                + hashlib.sha256(pages[section_urls[1]]).hexdigest()
            ),
        }
    ]


@pytest.mark.asyncio
async def test_washington_bounded_section_probe_keeps_singleton_compatibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://app.leg.wa.gov/RCW/default.aspx?cite=1.01.010"
    calls: list[str] = []

    async def _single(self, requested_url: str, **_kwargs):
        calls.append(requested_url)
        return _section_html("1.01.010")

    async def _plural_must_not_run(*_args, **_kwargs):
        raise AssertionError("bounded probe should retain the legacy singleton path")

    monkeypatch.setattr(
        WashingtonScraper,
        "_fetch_page_content_with_archival_fallback",
        _single,
    )
    monkeypatch.setattr(
        WashingtonScraper,
        "_fetch_washington_frontier_batch",
        _plural_must_not_run,
    )
    scraper = WashingtonScraper("WA", "Washington")

    rows = await scraper._scrape_section_urls(
        "Revised Code of Washington",
        [(url, "1.01.010")],
        max_statutes=1,
    )

    assert calls == [url]
    assert [row.section_number for row in rows] == ["1.01.010"]


def test_washington_terminal_classifier_is_exact_and_source_bound() -> None:
    section = "1.01.010"
    url = f"https://app.leg.wa.gov/RCW/default.aspx?cite={section}"
    terminal_html = _section_html(section, caption="Reserved.", body="").decode()

    assert section_page_identity(terminal_html) == section
    assert source_bound_terminal_disposition_from_section_html(
        terminal_html,
        source_url=url,
        section_number=section,
    ) == "reserved"
    assert source_bound_terminal_disposition_from_section_html(
        terminal_html,
        source_url=url,
        section_number="1.01.020",
    ) is None


def test_washington_parser_keeps_substantive_repealer_text() -> None:
    section = "9A.98.010"
    html = _section_html(
        section,
        caption="Acts or parts of acts repealed.",
        body=("The following acts or parts of acts are repealed by this law. " * 4),
    ).decode()

    row = parse_washington_section_html(
        html,
        source_url=f"https://app.leg.wa.gov/RCW/default.aspx?cite={section}",
        section_number=section,
    )

    assert row is not None
    assert row.section_number == section
    assert "acts or parts of acts are repealed" in row.full_text
