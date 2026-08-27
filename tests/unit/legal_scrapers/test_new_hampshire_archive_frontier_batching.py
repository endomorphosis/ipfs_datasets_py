"""New Hampshire exact hierarchy and grouped archive-frontier regressions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    NormalizedStatute,
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_hampshire import (
    NewHampshireScraper,
    _NewHampshireCheckpoint,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_hampshire_section import (
    nhtoc_section_units,
    nhtoc_title_units,
    parse_new_hampshire_section_html,
    source_bound_terminal_disposition_from_section_html,
    terminal_disposition_from_label,
)

ROOT = "https://www.gencourt.state.nh.us/rsa/html/NHTOC.htm"
CURRENT_ROOT = "https://gc.nh.gov/rsa/html/NHTOC.htm"
TITLE_I = "https://gc.nh.gov/rsa/html/NHTOC/NHTOC-I.htm"
TITLE_IV = "https://gc.nh.gov/rsa/html/NHTOC/NHTOC-IV.htm"
CHAPTER_1 = "https://gc.nh.gov/rsa/html/NHTOC/NHTOC-I-1.htm"
CHAPTER_2 = "https://gc.nh.gov/rsa/html/NHTOC/NHTOC-I-2.htm"
SECTION_1_1 = "https://gc.nh.gov/rsa/html/I/1/1-1.htm"
SECTION_1_2 = "https://gc.nh.gov/rsa/html/I/1/1-2.htm"
SECTION_2_1 = "https://gc.nh.gov/rsa/html/I/2/2-1.htm"


def _section_page(citation: str, text: str) -> bytes:
    return (
        "<html><head>"
        f'<meta name="sectiontitle" content="Section {citation} Exact title.">'
        "</head><body>"
        f"<h3>Section {citation}</h3><b>{citation} Exact title. –</b>"
        f"<codesect>{text}</codesect>"
        "<sourcenote>Source. History excluded.</sourcenote>"
        "</body></html>"
    ).encode()


def _aligned_result(
    urls: list[str],
    payloads: list[bytes],
    *,
    errors: list[str | None] | None = None,
) -> StateLawPageMultiFetchResult:
    return StateLawPageMultiFetchResult(
        urls=list(urls),
        payloads=list(payloads),
        errors=list(errors or [None] * len(urls)),
        transport_receipts=[
            {
                "official_url": url,
                "content_sha256": hashlib.sha256(payload).hexdigest(),
            }
            if payload
            else None
            for url, payload in zip(urls, payloads, strict=True)
        ],
        parser_input_envelopes=[
            SimpleNamespace(body=payload) if payload else None for payload in payloads
        ],
        stats={"requested_pages": len(urls), "range_fetches_avoided": 3},
    )


@pytest.mark.anyio
async def test_new_hampshire_unbounded_tree_batches_and_closes_exact_frontier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = (
        "<html><body><h1>New Hampshire Statutes</h1><h2>Table of Contents</h2><ul>"
        "<li><a href='NHTOC/NHTOC-I.htm'>TITLE I: THE STATE AND ITS GOVERNMENT</a></li>"
        "<p class='chapter_list'>(Includes Chapters 1 - 2)</p>"
        "<li><a href='NHTOC/NHTOC-IV.htm'>TITLE IV: ELECTIONS</a></li>"
        "<p class='chapter_list'>(Entire Title Was Repealed - Chapters 54 - 70)</p>"
        "</ul></body></html>"
    ).encode()
    title = (
        "<html><body><h1>New Hampshire Statutes</h1><h2>Table of Contents</h2>"
        "<h2>I: THE STATE AND ITS GOVERNMENT</h2>"
        "<a href='NHTOC-I-1.htm'>CHAPTER 1: STATE BOUNDARIES</a>"
        "<a href='NHTOC-I-2.htm'>CHAPTER 2: AERIAL SURVEY</a>"
        "</body></html>"
    ).encode()
    chapter_one = (
        "<html><body><h1>New Hampshire Statutes</h1><h2>Table of Contents</h2>"
        "<h2><a href='../I/1/1-mrg.htm'>CHAPTER 1: STATE BOUNDARIES</a></h2>"
        "<a href='../I/1/1-1.htm'>Section 1:1 Exact title.</a>"
        "<a href='../I/1/1-2.htm'>Section 1:2 Repealed by 2020, 1:1.</a>"
        "</body></html>"
    ).encode()
    chapter_two = (
        "<html><body><h1>New Hampshire Statutes</h1><h2>Table of Contents</h2>"
        "<h2><a href='../I/2/2-mrg.htm'>CHAPTER 2: AERIAL SURVEY</a></h2>"
        "<a href='../I/2/2-1.htm'>Section: 2:1 Exact second title.</a>"
        "</body></html>"
    ).encode()
    pages = {
        ROOT: root,
        TITLE_I: title,
        CHAPTER_1: chapter_one,
        CHAPTER_2: chapter_two,
        SECTION_1_1: _section_page(
            "1:1", "The boundary of New Hampshire shall remain as officially established."
        ),
        SECTION_2_1: _section_page(
            "2:1", "The state may conduct an aerial survey for an official public purpose."
        ),
    }
    plural_calls: list[tuple[list[str], dict[str, Any]]] = []

    async def _plural(self, urls, **kwargs: Any) -> StateLawPageMultiFetchResult:
        del self
        requested = list(urls)
        plural_calls.append((requested, dict(kwargs)))
        return _aligned_result(requested, [pages[url] for url in requested])

    monkeypatch.setattr(
        NewHampshireScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    scraper = NewHampshireScraper("NH", "New Hampshire")
    monkeypatch.setattr(
        scraper,
        "OFFICIAL_TITLES",
        (("I", "The State and Its Government"), ("IV", "Elections")),
    )
    monkeypatch.setattr(scraper, "OFFICIAL_TITLE_COUNT", 2)

    statutes = await scraper._scrape_official_rsa_tree_batched(
        code_name="New Hampshire Revised Statutes",
        checkpoint=_NewHampshireCheckpoint("NH"),
    )

    assert [requested for requested, _kwargs in plural_calls] == [
        [ROOT],
        [TITLE_I],
        [CHAPTER_1, CHAPTER_2],
        [SECTION_1_1, SECTION_2_1],
    ]
    assert all(kwargs["prefer_direct"] is True for _urls, kwargs in plural_calls)
    assert all(
        kwargs["common_crawl_domain_terms"]
        == ("gc.nh.gov", "www.gencourt.state.nh.us")
        for _urls, kwargs in plural_calls
    )
    assert all(kwargs["common_crawl_url_terms"] == ("/rsa/html/",) for _urls, kwargs in plural_calls)
    assert all(
        kwargs["wayback_prefix_inventory"] is True
        for _urls, kwargs in plural_calls
    )
    assert all(
        kwargs["repeat_grouped_archive_inventory_on_residual"] is False
        for _urls, kwargs in plural_calls
    )
    assert all("residual_retry_attempts" in kwargs for _urls, kwargs in plural_calls)
    assert [row.statute_id for row in statutes] == [
        "New Hampshire Revised Statutes § 1:1",
        "New Hampshire Revised Statutes § 2:1",
    ]
    assert all("History excluded" not in row.full_text for row in statutes)
    frontier = scraper._last_new_hampshire_full_frontier
    assert frontier["closed"] is True
    assert frontier["titles_discovered"] == 2
    assert frontier["title_pages_fetched"] == 1
    assert len(frontier["terminal_titles"]) == 1
    assert frontier["chapters_discovered"] == 2
    assert frontier["section_locators_discovered"] == 3
    assert frontier["active_section_pages_fetched"] == 2
    assert len(frontier["terminal_sections"]) == 1
    assert frontier["statutes_emitted"] == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("malformation", "message"),
    (
        ("short-payloads", "unaligned acquisition rows"),
        ("short-errors", "unaligned acquisition rows"),
        ("short-receipts", "unaligned acquisition rows"),
        ("short-envelopes", "unaligned acquisition rows"),
        ("wrong-order", "changed URL order or identity"),
        ("wrong-receipt-url", "receipt changed URL identity"),
        ("wrong-receipt-digest", "receipt changed payload identity"),
        ("wrong-envelope", "envelope changed payload identity"),
        ("unresolved", "unresolved exact URLs"),
    ),
)
async def test_new_hampshire_batch_fails_closed_on_unaligned_or_missing_rows(
    monkeypatch: pytest.MonkeyPatch,
    malformation: str,
    message: str,
) -> None:
    requested = [TITLE_I, TITLE_IV]
    payloads = [b"<html>New Hampshire Statutes Table of Contents CHAPTER 1</html>"] * 2

    async def _plural(self, urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        del self
        result = _aligned_result(list(urls), payloads)
        if malformation == "short-payloads":
            result.payloads = result.payloads[:1]
        elif malformation == "short-errors":
            result.errors = result.errors[:1]
        elif malformation == "short-receipts":
            result.transport_receipts = result.transport_receipts[:1]
        elif malformation == "short-envelopes":
            result.parser_input_envelopes = result.parser_input_envelopes[:1]
        elif malformation == "wrong-order":
            result.urls = list(reversed(result.urls))
        elif malformation == "wrong-receipt-url":
            result.transport_receipts[1]["official_url"] = ROOT
        elif malformation == "wrong-receipt-digest":
            result.transport_receipts[1]["content_sha256"] = "0" * 64
        elif malformation == "wrong-envelope":
            result.parser_input_envelopes[1] = SimpleNamespace(body=b"different")
        elif malformation == "unresolved":
            result.payloads[1] = b""
            result.errors[1] = "archive miss"
        return result

    monkeypatch.setattr(
        NewHampshireScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    scraper = NewHampshireScraper("NH", "New Hampshire")
    with pytest.raises(RuntimeError, match=message):
        await scraper._fetch_new_hampshire_frontier_batch(
            requested,
            frontier_name="test",
            content_validator=lambda payload: bool(payload),
        )


@pytest.mark.anyio
async def test_new_hampshire_batch_requires_receipt_and_envelope_with_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"<html>New Hampshire Statutes Table of Contents CHAPTER 1</html>"

    async def _plural(self, urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        del self
        requested = list(urls)
        return StateLawPageMultiFetchResult(
            urls=requested,
            payloads=[payload],
            errors=[None],
            transport_receipts=[None],
            parser_input_envelopes=[None],
            stats={"requested_pages": 1},
        )

    monkeypatch.setattr(
        NewHampshireScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    scraper = NewHampshireScraper("NH", "New Hampshire")
    scraper._state_law_acquisition_ledger = object()
    with pytest.raises(RuntimeError, match="lacks retained receipt/envelope evidence"):
        await scraper._fetch_new_hampshire_frontier_batch(
            [TITLE_I],
            frontier_name="test",
            content_validator=lambda value: bool(value),
        )


@pytest.mark.parametrize(
    ("receipt", "envelope", "message"),
    (
        (
            {"content_sha256": hashlib.sha256(b"exact").hexdigest()},
            SimpleNamespace(body=b"exact"),
            "receipt lacks exact URL/digest evidence",
        ),
        (
            {"official_url": TITLE_I},
            SimpleNamespace(body=b"exact"),
            "receipt lacks exact URL/digest evidence",
        ),
        (
            {
                "official_url": TITLE_I,
                "content_sha256": hashlib.sha256(b"exact").hexdigest(),
            },
            SimpleNamespace(),
            "envelope lacks exact body evidence",
        ),
    ),
)
def test_new_hampshire_ledger_requires_identity_complete_aligned_evidence(
    receipt: dict[str, str],
    envelope: Any,
    message: str,
) -> None:
    scraper = NewHampshireScraper("NH", "New Hampshire")
    scraper._state_law_acquisition_ledger = object()

    with pytest.raises(RuntimeError, match=message):
        scraper._validate_new_hampshire_aligned_evidence(
            url=TITLE_I,
            payload=b"exact",
            transport_receipt=receipt,
            parser_input_envelope=envelope,
            frontier_name="test",
        )


@pytest.mark.anyio
async def test_new_hampshire_frontier_rejects_duplicate_urls_before_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _forbid(*_args, **_kwargs):
        raise AssertionError("duplicate frontier must fail before transport")

    monkeypatch.setattr(
        NewHampshireScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _forbid,
    )
    scraper = NewHampshireScraper("NH", "New Hampshire")
    with pytest.raises(RuntimeError, match="contains duplicate URLs"):
        await scraper._fetch_new_hampshire_frontier_batch(
            [TITLE_I, TITLE_I],
            frontier_name="duplicate",
            content_validator=lambda value: bool(value),
        )


def test_new_hampshire_catalog_matches_retained_root_shape() -> None:
    titles = [number for number, _name in NewHampshireScraper.OFFICIAL_TITLES]
    assert len(titles) == 67
    assert NewHampshireScraper.OFFICIAL_TITLE_COUNT == 67
    assert NewHampshireScraper.OFFICIAL_ACTIVE_TITLE_COUNT == 66
    assert NewHampshireScraper.OFFICIAL_TERMINAL_TITLE_COUNT == 1
    assert NewHampshireScraper.OFFICIAL_TERMINAL_TITLES == (("IV", "repealed"),)
    assert len(set(titles)) == 67
    assert [number for number in titles if "-" in number] == [
        "XIX-A",
        "XXXIII-A",
        "XXXIV-A",
    ]
    title_names = dict(NewHampshireScraper.OFFICIAL_TITLES)
    assert title_names["IV"] == "Elections"
    assert title_names["XXXII"] == "Chattel Mortgages"
    assert title_names["XXXIII"] == "Conditional Sales"

    html = (
        "<li><a href='NHTOC/NHTOC-XIX-A.htm'>TITLE XIX-A: FORESTRY</a></li>"
        "<p class='chapter_list'>(Includes Chapters 227-G - 227-M)</p>"
        "<li><a href='NHTOC/NHTOC-IV.htm'>TITLE IV: ELECTIONS</a></li>"
        "<p class='chapter_list'>(Entire Title Was Repealed - Chapters 54 - 70)</p>"
    )
    units = nhtoc_title_units(html, base_url=ROOT)
    assert [unit["title_number"] for unit in units] == ["XIX-A", "IV"]
    assert units[0]["terminal_disposition"] == ""
    assert units[1]["terminal_disposition"] == "repealed"


@pytest.mark.anyio
async def test_new_hampshire_root_terminal_projection_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = (
        "<html><body><h1>New Hampshire Statutes</h1><h2>Table of Contents</h2><ul>"
        "<li><a href='NHTOC/NHTOC-I.htm'>TITLE I: THE STATE AND ITS GOVERNMENT</a></li>"
        "<p class='chapter_list'>(Includes Chapters 1 - 2)</p>"
        "<li><a href='NHTOC/NHTOC-IV.htm'>TITLE IV: ELECTIONS</a></li>"
        "<p class='chapter_list'>(Includes Chapters 54 - 70)</p>"
        "</ul></body></html>"
    ).encode()
    calls: list[list[str]] = []

    async def _plural(self, urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        del self
        requested = list(urls)
        calls.append(requested)
        return _aligned_result(requested, [root])

    monkeypatch.setattr(
        NewHampshireScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    scraper = NewHampshireScraper("NH", "New Hampshire")
    monkeypatch.setattr(
        scraper,
        "OFFICIAL_TITLES",
        (("I", "The State and Its Government"), ("IV", "Elections")),
    )
    monkeypatch.setattr(scraper, "OFFICIAL_TITLE_COUNT", 2)

    with pytest.raises(
        RuntimeError, match="changed its exact terminal title projection"
    ):
        await scraper._scrape_official_rsa_tree_batched(
            code_name="New Hampshire Revised Statutes",
            checkpoint=_NewHampshireCheckpoint("NH"),
        )

    assert calls == [[ROOT]]


def test_new_hampshire_section_identity_is_bound_across_toc_url_and_body() -> None:
    chapter_html = (
        "<h2><a href='../XXXIV-A/382-A/382-A-mrg.htm'>"
        "CHAPTER 382-A: UNIFORM COMMERCIAL CODE</a></h2>"
        "<a href='https://web.archive.org/web/20250124114611id_/"
        "https://www.gencourt.state.nh.us/rsa/html/XXXIV-A/382-A/382-A-2-208.htm'>"
        "Section: 382-A:2-208 Repealed by 2006, 169:16, III.</a>"
    )
    units = nhtoc_section_units(
        chapter_html,
        title_number="XXXIV-A",
        chapter_number="382-A",
        base_url="https://www.gencourt.state.nh.us/rsa/html/NHTOC/NHTOC-XXXIV-A-382-A.htm",
    )
    assert units == [
        {
            "title_number": "XXXIV-A",
            "chapter_number": "382-A",
            "section_number": "382-A:2-208",
            "section_name": "Repealed by 2006, 169:16, III.",
            "label": "Section: 382-A:2-208 Repealed by 2006, 169:16, III.",
            "source_url": "https://www.gencourt.state.nh.us/rsa/html/XXXIV-A/382-A/382-A-2-208.htm",
            "terminal_disposition": "repealed",
        }
    ]

    active = _section_page("382-A:2-208", "This replacement text remains operative law.").decode()
    assert (
        parse_new_hampshire_section_html(
            active,
            source_url=units[0]["source_url"],
            code_name="New Hampshire Revised Statutes",
        ).statute_id
        == "New Hampshire Revised Statutes § 382-A:2-208"
    )
    mismatched = _section_page("382-A:2-209", "This is a different official section.").decode()
    assert (
        parse_new_hampshire_section_html(
            mismatched,
            source_url=units[0]["source_url"],
            code_name="New Hampshire Revised Statutes",
        )
        is None
    )


def test_new_hampshire_terminal_body_requires_exact_page_identity() -> None:
    assert terminal_disposition_from_label("[Repealed.]") == "repealed"
    assert terminal_disposition_from_label("Reserved powers remain operative") is None
    html = _section_page("1:2", "Repealed by 2020, 1:1, effective January 1, 2021.").decode()
    disposition = source_bound_terminal_disposition_from_section_html(
        html,
        source_url=SECTION_1_2,
        section_number="1:2",
    )
    assert disposition is not None
    assert disposition["disposition"] == "repealed"
    assert source_bound_terminal_disposition_from_section_html(
        html,
        source_url=SECTION_1_1,
        section_number="1:1",
    ) is None


def test_new_hampshire_complete_checkpoint_replaces_stale_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(tmp_path))
    checkpoint = _NewHampshireCheckpoint("NH")

    def _row(citation: str) -> NormalizedStatute:
        return NormalizedStatute(
            state_code="NH",
            state_name="New Hampshire",
            statute_id=f"New Hampshire Revised Statutes § {citation}",
            code_name="New Hampshire Revised Statutes",
            section_number=citation,
            section_name=f"Section {citation}",
            full_text=f"Exact statutory text for {citation}.",
            source_url=(
                "https://www.gencourt.state.nh.us/rsa/html/I/1/"
                f"1-{citation.split(':', 1)[1]}.htm"
            ),
        )

    checkpoint.write(
        [_row("1:99")],
        code_name="New Hampshire Revised Statutes",
        stage_label="legacy-complete",
    )
    checkpoint.write(
        [_row("1:1")],
        code_name="New Hampshire Revised Statutes",
        stage_label="new-hampshire:complete",
        progress={"codes_completed": 1},
        replace_statutes=True,
    )
    payload = json.loads(checkpoint.path.read_text())
    assert [row["section_number"] for row in payload["statutes"]] == ["1:1"]
