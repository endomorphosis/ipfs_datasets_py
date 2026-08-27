from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    build_canonical_state_law_output_projection,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import montana
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.minnesota import (
    MinnesotaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.minnesota_section import (
    classify_minnesota_terminal_section_html,
    parse_minnesota_section_html,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.montana import (
    MontanaScraper,
    _classify_montana_catalog_terminal_label,
)


class _RetainedLedger:
    def __init__(self, pages: dict[str, bytes]) -> None:
        self.pages = dict(pages)
        self.replayed: list[str] = []
        self.retained: dict[str, Any] | None = None

    def refresh_existing_entries(self) -> None:
        return None

    def replay_retained_parser_input(self, *, official_url: str, **_kwargs: Any):
        self.replayed.append(official_url)
        payload = self.pages.get(official_url)
        if payload is None:
            return None
        return SimpleNamespace(
            envelope=SimpleNamespace(body=payload),
            transport_receipt={
                "content_sha256": hashlib.sha256(payload).hexdigest(),
                "official_url": official_url,
            },
        )

    def retain_frontier_closure_projection(
        self,
        completion_receipt: dict[str, Any],
        **kwargs: Any,
    ) -> Path:
        self.retained = {
            "completion_receipt": completion_receipt,
            **kwargs,
        }
        return Path("/tmp/strict-frontier.json")


def _projection(scraper: Any, rows: list[Any], jurisdiction: str) -> dict[str, Any]:
    return build_canonical_state_law_output_projection(
        [scraper._enrich_statute_structure(row).to_dict() for row in rows],
        jurisdiction=jurisdiction,
    )


def _mn_current_page(body: str) -> bytes:
    return (
        "<html><body><div id='header'><h1>2025 Minnesota Statutes</h1></div>"
        f"{body}</body></html>"
    ).encode()


def test_minnesota_dom_bound_terminal_classifier_preserves_short_operative_text() -> None:
    source_url = "https://www.revisor.mn.gov/statutes/cite/1.01"
    operative = (
        "<html><body><div class='section' id='stat.1.01'>"
        "<h1 class='shn'>1.01 SHORT LAW.</h1><p>It applies.</p>"
        "</div></body></html>"
    )
    terminal = (
        "<html><body><div class='sr' id='stat.1.01'>"
        "<b>1.01</b> MS 2024 Supp [Repealed, 2025 c 1 s 1]"
        "</div></body></html>"
    )
    unknown = terminal.replace("Repealed, 2025 c 1 s 1", "Editorial note")

    parsed = parse_minnesota_section_html(operative, source_url=source_url)
    assert parsed is not None
    assert parsed.full_text == "It applies."
    assert classify_minnesota_terminal_section_html(
        operative.replace("It applies.", "A repealed law is referenced."),
        source_url=source_url,
    ) is None
    assert classify_minnesota_terminal_section_html(
        terminal,
        source_url=source_url,
    )["disposition"] == "repealed"
    assert classify_minnesota_terminal_section_html(
        unknown,
        source_url=source_url,
    ) is None

    uniform_code = operative.replace("1.01", "336.1-101")
    parsed_uniform_code = parse_minnesota_section_html(
        uniform_code,
        source_url="https://www.revisor.mn.gov/statutes/cite/336.1-101",
    )
    assert parsed_uniform_code is not None
    assert parsed_uniform_code.section_number == "336.1-101"
    uniform_match = MinnesotaScraper(
        "MN",
        "Minnesota",
    )._MN_SECTION_NUMBER_RE.search(parsed_uniform_code.source_url)
    assert uniform_match is not None
    assert uniform_match.group(1) == "336.1-101"


@pytest.mark.anyio
async def test_minnesota_full_root_fails_closed_without_exact_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MinnesotaScraper("MN", "Minnesota")

    async def _root_only(*_args: Any, **_kwargs: Any) -> bytes:
        return b"<html><body><a href='/statutes/cite/1'>Chapter 1</a></body></html>"

    monkeypatch.setattr(
        scraper,
        "_fetch_page_content_with_archival_fallback",
        _root_only,
    )

    with pytest.raises(RuntimeError, match="neither an exact chapter table"):
        await scraper._discover_chapter_urls(max_chapters=None)


def test_exact_frontier_algebra_rejects_unclosed_membership_and_disposition() -> None:
    digest = hashlib.sha256(b"retained parser input").hexdigest()
    mn = MinnesotaScraper("MN", "Minnesota")
    with pytest.raises(RuntimeError, match="terminal dispositions"):
        mn._minnesota_exact_frontier(
            catalog_report={
                "catalog_mode": "direct_chapter_table",
                "chapter_count": 1,
                "content_sha256": digest,
                "edition": MinnesotaScraper.OFFICIAL_EDITION,
                "source_url": "https://www.revisor.mn.gov/statutes/",
            },
            toc_part_reports=[],
            chapter_reports=[
                {
                    "content_sha256": digest,
                    "edition": MinnesotaScraper.OFFICIAL_EDITION,
                    "source_section_count": 1,
                    "source_url": "https://www.revisor.mn.gov/statutes/cite/1",
                }
            ],
            section_reports=[
                {
                    "canonical_identity": "",
                    "content_sha256": digest,
                    "disposition": "repealed",
                    "edition": MinnesotaScraper.OFFICIAL_EDITION,
                    "source_url": "https://www.revisor.mn.gov/statutes/cite/1.01",
                }
            ],
            terminal_dispositions={},
        )


def test_montana_catalog_terminals_are_exact_and_lettered_chapters_survive() -> None:
    digest = hashlib.sha256(b"official part index").hexdigest()
    source_url = (
        "https://leg.mt.gov/bills/mca/title_0010/chapter_0010/part_0010/"
        "section_0010/0010-0010-0010-0010.html"
    )
    catalog_url = (
        "https://leg.mt.gov/bills/mca/title_0010/chapter_0010/part_0010/"
        "sections_index.html"
    )
    cases = {
        "1-1-101 Repealed": "repealed",
        "1-1-101 through 1-1-109 reserved": "reserved",
        "1-1-101 Renumbered 30-9A-101": "renumbered",
        "1-1-101 Superseded": "superseded",
        "1-1-101 Expired": "expired",
        "1-1-101 Terminated": "terminated",
        "1-1-101 Void": "void",
        "1-1-101 Not codified": "not_codified",
        "***No Montana Rules 73-76.*** ***No Montana Rules 73-76.***": (
            "no_rule_reserved"
        ),
        (
            "1-1-101 Combined with 1-1-102, renumbered 1-1-201"
        ): "combined_and_renumbered",
    }
    for label, expected in cases.items():
        record = _classify_montana_catalog_terminal_label(
            label,
            section_url=source_url,
            catalog_url=catalog_url,
            catalog_content_sha256=digest,
        )
        assert record is not None
        assert record["disposition"] == expected
    for active_label in (
        "1-1-101 All statutes subject to repeal",
        "1-1-101 Reserved name",
        "1-1-101 Emergency or temporary rules",
        "1-1-101 Provisions of law not codified because redundant",
    ):
        assert _classify_montana_catalog_terminal_label(
            active_label,
            section_url=source_url,
            catalog_url=catalog_url,
            catalog_content_sha256=digest,
        ) is None

    scraper = MontanaScraper("MT", "Montana")
    part_html = (
        "<a href='./section_0010/0010-0010-0010-0010.html'>"
        "1-1-101 Repealed</a>"
        "<a href='./section_0020/0010-0010-0010-0020.html'>"
        "1-1-102 Reserved name</a>"
    )
    discovered = scraper._extract_html_mca_links(
        part_html,
        catalog_url,
        scraper._MT_SECTION_URL_RE,
    )
    catalog_terminals = scraper._montana_catalog_terminal_records(
        part_html,
        part_url=catalog_url,
        discovered=discovered,
        content_sha256=hashlib.sha256(part_html.encode()).hexdigest(),
    )
    assert list(catalog_terminals) == [source_url]

    lettered_chapter = (
        "https://leg.mt.gov/bills/mca/title_0300/chapter_009A/parts_index.html"
    )
    extracted = scraper._extract_html_mca_links(
        "<a href='./chapter_009A/parts_index.html'>Chapter 9A</a>",
        "https://leg.mt.gov/bills/mca/title_0300/chapters_index.html",
        scraper._MT_CHAPTER_INDEX_HREF_RE,
    )
    assert extracted == [("Chapter 9A", lettered_chapter)]
    lettered_section = (
        "https://leg.mt.gov/bills/mca/title_0300/chapter_009A/part_0010/"
        "section_0010/0300-009A-0010-0010.html"
    )
    assert scraper._section_number_from_mca_url(
        lettered_section,
        section_label="30-9A-101 Secured transactions.",
    ) == "30-9A-101"


def test_montana_exact_frontier_rejects_unclosed_membership() -> None:
    digest = hashlib.sha256(b"retained parser input").hexdigest()
    mt = MontanaScraper("MT", "Montana")
    with pytest.raises(RuntimeError, match="membership did not reconcile"):
        mt._montana_exact_frontier(
            root_report={
                "content_sha256": digest,
                "source_url": "https://leg.mt.gov/bills/mca/index.html",
                "title_count": 1,
            },
            title_reports=[
                {
                    "chapter_count": 1,
                    "content_sha256": digest,
                    "source_url": "https://leg.mt.gov/bills/mca/title.html",
                }
            ],
            chapter_reports=[
                {
                    "content_sha256": digest,
                    "part_count": 1,
                    "source_url": "https://leg.mt.gov/bills/mca/chapter.html",
                }
            ],
            part_reports=[
                {
                    "content_sha256": digest,
                    "section_count": 2,
                    "source_url": "https://leg.mt.gov/bills/mca/part.html",
                }
            ],
            section_reports=[
                {
                    "canonical_identity": "1-1-101",
                    "content_sha256": digest,
                    "disposition": "operative",
                    "source_url": "https://leg.mt.gov/bills/mca/section.html",
                }
            ],
            terminal_dispositions={},
        )


def test_montana_exact_frontier_rejects_forged_constitution_scope() -> None:
    digest = hashlib.sha256(b"retained parser input").hexdigest()
    constitution = (
        "https://leg.mt.gov/bills/mca/title_0000/chapters_index.html"
    )
    mt = MontanaScraper("MT", "Montana")
    with pytest.raises(
        RuntimeError,
        match="separate constitutional scope is not source-bound",
    ):
        mt._montana_exact_frontier(
            root_report={
                "content_sha256": digest,
                "source_url": "https://leg.mt.gov/bills/mca/index.html",
                "title_count": 2,
                "title_scope_exclusion_count": 1,
                "title_scope_exclusions": [
                    {
                        "disposition": "separate_constitution_scope",
                        "source_url": constitution,
                    }
                ],
            },
            title_reports=[
                {
                    "chapter_count": 0,
                    "content_sha256": digest,
                    "disposition": "separate_constitution_scope",
                    "evidence_kind": "source_bound_separate_configuration",
                    "non_default_configuration": "default",
                    "root_catalog_content_sha256": digest,
                    "source_url": constitution,
                },
                {
                    "chapter_count": 1,
                    "content_sha256": digest,
                    "disposition": "statutory_hierarchy",
                    "source_url": "https://leg.mt.gov/bills/mca/title.html",
                },
            ],
            chapter_reports=[
                {
                    "content_sha256": digest,
                    "part_count": 1,
                    "source_url": "https://leg.mt.gov/bills/mca/chapter.html",
                }
            ],
            part_reports=[
                {
                    "content_sha256": digest,
                    "section_count": 1,
                    "source_url": "https://leg.mt.gov/bills/mca/part.html",
                }
            ],
            section_reports=[
                {
                    "canonical_identity": "1-1-101",
                    "content_sha256": digest,
                    "disposition": "operative",
                    "source_url": "https://leg.mt.gov/bills/mca/section.html",
                }
            ],
            terminal_dispositions={},
        )


@pytest.mark.anyio
async def test_minnesota_closure_replays_root_hierarchy_and_leaves_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MinnesotaScraper("MN", "Minnesota")
    root = "https://www.revisor.mn.gov/statutes/"
    part = "https://www.revisor.mn.gov/statutes/part/ONE"
    chapter = "https://www.revisor.mn.gov/statutes/cite/1"
    active = "https://www.revisor.mn.gov/statutes/cite/1.01"
    terminal = "https://www.revisor.mn.gov/statutes/cite/1.02"
    pages = {
        root: _mn_current_page(
            "<table id='toc_table'><tr><td><a href='/statutes/part/ONE'>"
            "1-1</a></td><td>Part one</td></tr></table>"
        ),
        part: _mn_current_page(
            "<table id='chapters_table'><tr><td><a href='/statutes/cite/1'>"
            "1</a></td><td>Chapter one</td></tr></table>"
        ),
        chapter: _mn_current_page(
            "<div id='chapter_analysis'><table>"
            "<tr><td><a href='/statutes/cite/1.01'>1.01</a></td>"
            "<td>Active</td></tr>"
            "<tr><td><a href='/statutes/cite/1.02'>1.02</a></td>"
            "<td>Repealed</td></tr></table></div>"
        ),
        active: _mn_current_page(
            "<div class='section' id='stat.1.01'><h1 class='shn'>"
            "1.01 ACTIVE LAW.</h1><p>This operative public law remains in force."
            "</p></div>"
        ),
        terminal: _mn_current_page(
            "<div class='sr' id='stat.1.02'><b>1.02</b> "
            "[Repealed, 2025 c 1 s 1]</div>"
        ),
    }
    acquisition_calls: list[list[str]] = []

    async def _single(url: str, **_kwargs: Any) -> bytes:
        acquisition_calls.append([url])
        return pages[url]

    async def _batch(urls: list[str], **_kwargs: Any) -> list[bytes]:
        requested = list(urls)
        acquisition_calls.append(requested)
        return [pages[url] for url in requested]

    monkeypatch.setattr(scraper, "_fetch_page_content_with_archival_fallback", _single)
    monkeypatch.setattr(scraper, "_fetch_minnesota_frontier_batch", _batch)
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", lambda *_a, **_k: True)
    ledger = _RetainedLedger(pages)
    scraper._state_law_acquisition_ledger = ledger

    rows = await scraper._scrape_chapter_sections(
        "Minnesota Statutes",
        max_statutes=None,
    )
    calls_before_replay = list(acquisition_calls)
    path = await scraper.produce_state_law_frontier_closure(
        canonical_output_projection=_projection(scraper, rows, "MN"),
    )

    assert path == Path("/tmp/strict-frontier.json")
    assert [row.section_number for row in rows] == ["1.01"]
    assert acquisition_calls == calls_before_replay
    assert set(ledger.replayed) == set(pages)
    assert ledger.retained is not None
    completion = ledger.retained["completion_receipt"]
    assert completion["disposition"] == {
        "discovered": 2,
        "duplicates": 0,
        "excluded": 1,
        "failed_final": 0,
        "fetched": 1,
        "quarantined": 0,
    }
    assert completion["rights"]["basis"] == "public_law_no_state_copyright"
    assert completion["edition"] == MinnesotaScraper.OFFICIAL_EDITION
    assert completion["replay"]["network_requests"] == 0
    assert completion["transport"]["grouped_warc_recovery"] is True
    assert completion["transport"]["per_page_archive_loop"] is False
    assert completion["transport"][
        "repeat_grouped_archive_inventory_on_residual"
    ] is False
    assert completion["transport"]["residual_only_retries"] is True
    assert completion["transport"]["source_ordered_cross_parent_union"] is True
    assert completion["transport"]["statutes_edition_guard"] is True
    assert completion["transport"]["wayback_prefix_inventory"] is True


@pytest.mark.anyio
async def test_montana_closure_replays_root_hierarchy_and_leaves_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MontanaScraper("MT", "Montana")
    root = "https://leg.mt.gov/bills/mca/index.html"
    constitution = (
        "https://leg.mt.gov/bills/mca/title_0000/chapters_index.html"
    )
    title = "https://leg.mt.gov/bills/mca/title_0010/chapters_index.html"
    chapter = (
        "https://leg.mt.gov/bills/mca/title_0010/chapter_0010/parts_index.html"
    )
    part = (
        "https://leg.mt.gov/bills/mca/title_0010/chapter_0010/"
        "part_0010/sections_index.html"
    )
    active = (
        "https://leg.mt.gov/bills/mca/title_0010/chapter_0010/part_0010/"
        "section_0010/0010-0010-0010-0010.html"
    )
    terminal = (
        "https://leg.mt.gov/bills/mca/title_0010/chapter_0010/part_0010/"
        "section_0020/0010-0010-0010-0020.html"
    )
    terminal_href = "./section_0020/0010-0010-0010-0020.html"
    part_payload = (
        "<ul><li class='line'><a href='./section_0010/"
        "0010-0010-0010-0010.html'><span class='citation'>1-1-101</span> "
        "Active</a></li><li class='line'><a href='"
        f"{terminal_href}'><span class='citation'>1-1-102</span> "
        "Repealed</a></li></ul>"
    ).encode()
    root_payload = (
        "<a data-titlenumber='0' href='./title_0000/chapters_index.html'>"
        "THE CONSTITUTION OF THE STATE OF MONTANA</a>"
        "<a href='title_0010/chapters_index.html'>Title 1</a>"
    ).encode()
    constitution_payload = (
        "<h1 class='chapter-title-title'>"
        "THE CONSTITUTION OF THE STATE OF MONTANA</h1>"
        "<div class='chapter-toc-content'><ul><li class='line'>"
        "<a href='./article_0010/parts_index.html'>"
        "ARTICLE I. COMPACT WITH THE UNITED STATES</a>"
        "</li></ul></div>"
    ).encode()
    pages = {
        root: root_payload,
        constitution: constitution_payload,
        title: (
            "<a href='chapter_0010/parts_index.html'>Chapter 1</a>"
        ).encode(),
        chapter: (
            "<a href='part_0010/sections_index.html'>Part 1</a>"
        ).encode(),
        part: part_payload,
        active: (
            "<main><h1>1-1-101 Active law.</h1><p>"
            + "This operative Montana public law supplies exact text. " * 4
            + "</p></main>"
        ).encode(),
    }
    monkeypatch.setattr(
        montana,
        "_EXACT_TITLE_SCOPE_EXCLUSIONS",
        {
            constitution: {
                "disposition": "separate_constitution_scope",
                "non_default_configuration": "constitutions",
                "root_url": root,
                "root_href": "./title_0000/chapters_index.html",
                "root_anchor_attrs": {
                    "data-titlenumber": "0",
                    "href": "./title_0000/chapters_index.html",
                },
                "source_label": "THE CONSTITUTION OF THE STATE OF MONTANA",
                "root_content_sha256": hashlib.sha256(root_payload).hexdigest(),
                "root_content_cid": "fixture-root-content-cid",
                "root_content_byte_size": len(root_payload),
                "root_receipt_sha256": "fixture-root-receipt-sha256",
                "root_receipt_cid": "fixture-root-receipt-cid",
                "title_content_sha256": hashlib.sha256(
                    constitution_payload
                ).hexdigest(),
                "title_content_cid": "fixture-title-content-cid",
                "title_content_byte_size": len(constitution_payload),
                "title_receipt_sha256": "fixture-title-receipt-sha256",
                "title_receipt_cid": "fixture-title-receipt-cid",
                "article_links": (
                    (
                        "./article_0010/parts_index.html",
                        "ARTICLE I. COMPACT WITH THE UNITED STATES",
                    ),
                ),
            }
        },
    )
    monkeypatch.setattr(
        montana,
        "_EXACT_TERMINAL_PART_CATALOGS",
        {
            part: {
                "content_sha256": hashlib.sha256(part_payload).hexdigest(),
                "content_cid": "fixture-content-cid",
                "content_byte_size": len(part_payload),
                "receipt_sha256": "fixture-receipt-sha256",
                "receipt_cid": "fixture-receipt-cid",
                "terminal_sections": {
                    "1-1-102": {
                        "href": terminal_href,
                        "catalog_text": "1-1-102 Repealed",
                        "disposition": "repealed",
                    }
                },
            }
        },
    )
    acquisition_calls: list[list[str]] = []

    async def _single(url: str, **_kwargs: Any) -> bytes:
        acquisition_calls.append([url])
        return pages[url]

    async def _batch(
        urls: list[str],
        **_kwargs: Any,
    ) -> list[bytes]:
        requested = list(urls)
        acquisition_calls.append(requested)
        return [pages[url] for url in requested]

    monkeypatch.setattr(
        scraper,
        "_fetch_page_content_with_archival_fallback",
        _single,
    )
    monkeypatch.setattr(scraper, "_fetch_montana_frontier_batch", _batch)
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", lambda *_a, **_k: True)
    ledger = _RetainedLedger(pages)
    scraper._state_law_acquisition_ledger = ledger

    rows = await scraper._scrape_official_mca_html_tree(
        "Montana Code Annotated",
        max_statutes=None,
    )
    calls_before_replay = list(acquisition_calls)
    path = await scraper.produce_state_law_frontier_closure(
        canonical_output_projection=_projection(scraper, rows, "MT"),
    )

    assert path == Path("/tmp/strict-frontier.json")
    assert [row.section_number for row in rows] == ["1-1-101"]
    assert acquisition_calls == [
        [root],
        [constitution, title],
        [chapter],
        [part],
        [active],
    ]
    assert acquisition_calls == calls_before_replay
    assert set(ledger.replayed) == set(pages)
    assert terminal not in ledger.replayed
    assert ledger.retained is not None
    completion = ledger.retained["completion_receipt"]
    assert completion["disposition"]["discovered"] == 2
    assert completion["disposition"]["fetched"] == 1
    assert completion["disposition"]["excluded"] == 1
    assert completion["frontier"]["title_document_count"] == 2
    assert completion["frontier"]["statutory_title_document_count"] == 1
    assert completion["frontier"]["title_scope_exclusion_count"] == 1
    assert completion["frontier"]["title_scope_dispositions"] == {
        "separate_constitution_scope": 1,
        "statutory_hierarchy": 1,
    }
    assert completion["rights"]["basis"] == "public_law_no_state_copyright"
    assert completion["replay"]["network_requests"] == 0
    assert completion["transport"]["grouped_warc_recovery"] is True
    assert completion["transport"]["per_page_archive_loop"] is False
    assert completion["transport"][
        "repeat_grouped_archive_inventory_on_residual"
    ] is False
    assert completion["transport"]["residual_only_retries"] is True
    assert completion["transport"]["source_ordered_cross_parent_union"] is True
    assert completion["transport"]["wayback_prefix_inventory"] is True
