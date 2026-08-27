from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import minnesota, montana
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    NormalizedStatute,
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.minnesota import (
    MinnesotaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.montana import (
    MontanaScraper,
)


MN_CHAPTER_URLS = [
    "https://www.revisor.mn.gov/statutes/cite/1",
    "https://www.revisor.mn.gov/statutes/cite/2",
]
MN_SECTION_URLS = [
    "https://www.revisor.mn.gov/statutes/cite/1.01",
    "https://www.revisor.mn.gov/statutes/cite/1.02",
    "https://www.revisor.mn.gov/statutes/cite/2.01",
]
MN_TERMINAL_CATALOG_URL = "https://www.revisor.mn.gov/statutes/cite/73"
MN_TERMINAL_URL = "https://www.revisor.mn.gov/statutes/cite/73.55"
MN_TERMINAL_TARGET_URL = "https://www.revisor.mn.gov/statutes/cite/299F.40"

MT_ROOT_URL = "https://leg.mt.gov/bills/mca/index.html"
MT_TITLE_URLS = [
    "https://leg.mt.gov/bills/mca/title_0010/chapters_index.html",
    "https://leg.mt.gov/bills/mca/title_0020/chapters_index.html",
]
MT_CHAPTER_URLS = [
    "https://leg.mt.gov/bills/mca/title_0010/chapter_0010/parts_index.html",
    "https://leg.mt.gov/bills/mca/title_0020/chapter_0010/parts_index.html",
]
MT_PART_URLS = [
    "https://leg.mt.gov/bills/mca/title_0010/chapter_0010/part_0010/sections_index.html",
    "https://leg.mt.gov/bills/mca/title_0020/chapter_0010/part_0010/sections_index.html",
]
MT_SECTION_URLS = [
    "https://leg.mt.gov/bills/mca/title_0010/chapter_0010/part_0010/section_0010/0010-0010-0010-0010.html",
    "https://leg.mt.gov/bills/mca/title_0010/chapter_0010/part_0010/section_0020/0010-0010-0010-0020.html",
    "https://leg.mt.gov/bills/mca/title_0020/chapter_0010/part_0010/section_0010/0020-0010-0010-0010.html",
]


def _aligned_result(
    urls: list[str],
    payloads: list[bytes],
    *,
    errors: list[str | None] | None = None,
    returned_urls: list[str] | None = None,
) -> StateLawPageMultiFetchResult:
    return StateLawPageMultiFetchResult(
        urls=list(urls if returned_urls is None else returned_urls),
        payloads=list(payloads),
        errors=list(errors if errors is not None else [None] * len(urls)),
        transport_receipts=[None] * len(urls),
        parser_input_envelopes=[None] * len(urls),
        stats={"requested_pages": len(urls)},
    )


def _mn_current_page(body: str) -> bytes:
    return (
        "<html><body><div id='header'><h1>2025 Minnesota Statutes</h1></div>"
        f"{body}</body></html>"
    ).encode()


def _mn_chapter_payload(*section_numbers: str) -> bytes:
    rows = "".join(
        f"<tr><td>{number} Official heading {number}</td></tr>"
        for number in section_numbers
    )
    return _mn_current_page(f"<table>{rows}</table>")


def _mn_section_payload(section_number: str) -> bytes:
    body = (
        f"Official Minnesota statutory text for section {section_number}. "
        "This public-law provision supplies substantive normalized text. "
    ) * 4
    return _mn_current_page(
        f"<div class='section' id='stat.{section_number}'>"
        f"<h2 class='shn'>{section_number}. Official heading.</h2>"
        f"<p>{body}</p>"
        "</div>"
    )


def _mn_terminal_catalog_payload(*, include_active: bool = False) -> bytes:
    active = (
        "<tr><td><a href='/statutes/cite/73.63'>73.63</a></td>"
        "<td>Active official heading</td></tr>"
        if include_active
        else ""
    )
    return _mn_current_page(
        "<div id='chapter_analysis'><table>"
        "<tr><td><a href='/statutes/cite/73.55'>73.55</a></td>"
        "<td class='inactive'> [Renumbered "
        "<a href='/statutes/cite/299F.40'>299F.40, subd 5</a>]"
        "</td></tr>"
        f"{active}</table></div>"
    )


def _mn_fixture_terminal_contract(payload: bytes) -> dict[str, Any]:
    records = [
        {
            "source_href": "/statutes/cite/73.55",
            "section_number": "73.55",
            "catalog_text": "[Renumbered 299F.40, subd 5]",
            "target_href": "/statutes/cite/299F.40",
            "target_text": "299F.40, subd 5",
        }
    ]
    return {
        "content_sha256": hashlib.sha256(payload).hexdigest(),
        "content_cid": "fixture-content-cid",
        "content_byte_size": len(payload),
        "receipt_sha256": "fixture-receipt-sha256",
        "receipt_cid": "fixture-receipt-cid",
        "terminal_record_count": 1,
        "terminal_records_sha256": (
            minnesota._terminal_catalog_records_sha256(records)
        ),
        "disposition": "renumbered",
    }


def _mt_section_payload(section_number: str) -> bytes:
    body = (
        f"Official Montana statutory text for section {section_number}. "
        "This public-law provision supplies substantive normalized text. "
    ) * 4
    return (
        "<html><body><main>"
        f"<h1>{section_number}. Official heading.</h1>"
        f"<p>{body}</p>"
        "</main></body></html>"
    ).encode()


def _mt_terminal_part_payload(*, heading: str = "Repealed") -> bytes:
    return (
        "<html><body><ul>"
        "<li class='line'><a href='./section_0120/"
        "0390-0710-0230-0120.html'><span class='citation'>"
        "39-71-2312</span>&nbsp;Definitions</a></li>"
        "<li class='line'><a href='./section_0260/"
        "0390-0710-0230-0260.html'><span class='citation'>"
        f"39-71-2326</span>&nbsp;{heading}</a></li>"
        "<li class='line'><a href='./section_0270/"
        "0390-0710-0230-0270.html'><span class='citation'>"
        "39-71-2327</span>&nbsp;Earnings of state fund</a></li>"
        "</ul></body></html>"
    ).encode()


def _mt_title_scope_fixture() -> tuple[bytes, bytes, dict[str, Any]]:
    root_payload = (
        "<html><body><a data-titlenumber='0' "
        "href='./title_0000/chapters_index.html'>"
        "THE CONSTITUTION OF THE STATE OF MONTANA</a>"
        "<a href='./title_0010/chapters_index.html'>Title 1</a>"
        "</body></html>"
    ).encode()
    title_payload = (
        "<html><body><h1 class='chapter-title-title'>"
        "THE CONSTITUTION OF THE STATE OF MONTANA</h1>"
        "<div class='chapter-toc-content'><ul><li class='line'>"
        "<a href='./article_0010/parts_index.html'>"
        "ARTICLE I. COMPACT WITH THE UNITED STATES</a>"
        "</li></ul></div></body></html>"
    ).encode()
    contract = {
        "disposition": "separate_constitution_scope",
        "non_default_configuration": "constitutions",
        "root_url": MT_ROOT_URL,
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
        "title_content_sha256": hashlib.sha256(title_payload).hexdigest(),
        "title_content_cid": "fixture-title-content-cid",
        "title_content_byte_size": len(title_payload),
        "title_receipt_sha256": "fixture-title-receipt-sha256",
        "title_receipt_cid": "fixture-title-receipt-cid",
        "article_links": (
            (
                "./article_0010/parts_index.html",
                "ARTICLE I. COMPACT WITH THE UNITED STATES",
            ),
        ),
    }
    return root_payload, title_payload, contract


def test_montana_title_zero_scope_is_exact_and_adversarially_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    title_url = (
        "https://leg.mt.gov/bills/mca/title_0000/chapters_index.html"
    )
    root_payload, title_payload, contract = _mt_title_scope_fixture()
    monkeypatch.setattr(
        montana,
        "_EXACT_TITLE_SCOPE_EXCLUSIONS",
        {title_url: contract},
    )

    root_scope = montana._source_bound_title_scope_exclusions_from_root_html(
        root_payload,
        source_url=MT_ROOT_URL,
    )
    assert list(root_scope) == [title_url]
    assert root_scope[title_url]["disposition"] == (
        "separate_constitution_scope"
    )
    assert root_scope[title_url]["non_default_configuration"] == "constitutions"
    report = montana._source_bound_title_scope_report_from_title_html(
        title_payload,
        source_label=contract["source_label"],
        source_url=title_url,
        root_scope_record=root_scope[title_url],
    )
    assert report is not None
    assert report["chapter_count"] == 0
    assert report["article_catalog_count"] == 1
    assert report["disposition"] == "separate_constitution_scope"

    assert (
        montana._source_bound_title_scope_exclusions_from_root_html(
            root_payload,
            source_url=f"{MT_ROOT_URL}?copy=1",
        )
        == {}
    )
    assert montana._source_bound_title_scope_report_from_title_html(
        title_payload,
        source_label="Title 0",
        source_url=title_url,
        root_scope_record=root_scope[title_url],
    ) is None
    assert montana._source_bound_title_scope_report_from_title_html(
        title_payload,
        source_label=contract["source_label"],
        source_url=f"{title_url}?copy=1",
        root_scope_record=root_scope[title_url],
    ) is None
    assert montana._source_bound_title_scope_report_from_title_html(
        title_payload,
        source_label=contract["source_label"],
        source_url=title_url,
        root_scope_record={
            **root_scope[title_url],
            "disposition": "statutory_hierarchy",
        },
    ) is None

    drifted_root = root_payload.replace(
        b"<a data-titlenumber='0' ",
        b"<a class='forged' data-titlenumber='0' ",
    )
    monkeypatch.setattr(
        montana,
        "_EXACT_TITLE_SCOPE_EXCLUSIONS",
        {
            title_url: {
                **contract,
                "root_content_sha256": hashlib.sha256(drifted_root).hexdigest(),
                "root_content_byte_size": len(drifted_root),
            }
        },
    )
    assert (
        montana._source_bound_title_scope_exclusions_from_root_html(
            drifted_root,
            source_url=MT_ROOT_URL,
        )
        == {}
    )

    drifted_title = title_payload.replace(
        b"</li></ul>",
        b"</li><li class='line'><a href='./article_0020/parts_index.html'>"
        b"ARTICLE II. FORGED</a></li></ul>",
    )
    monkeypatch.setattr(
        montana,
        "_EXACT_TITLE_SCOPE_EXCLUSIONS",
        {
            title_url: {
                **contract,
                "title_content_sha256": hashlib.sha256(drifted_title).hexdigest(),
                "title_content_byte_size": len(drifted_title),
            }
        },
    )
    assert montana._source_bound_title_scope_report_from_title_html(
        drifted_title,
        source_label=contract["source_label"],
        source_url=title_url,
        root_scope_record=root_scope[title_url],
    ) is None


def test_minnesota_source_bound_terminal_catalog_rejects_identity_and_dom_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _mn_terminal_catalog_payload()
    contract = _mn_fixture_terminal_contract(payload)
    monkeypatch.setattr(
        minnesota,
        "_EXACT_TERMINAL_CHAPTER_CATALOGS",
        {MN_TERMINAL_CATALOG_URL: contract},
    )

    typed = (
        minnesota._source_bound_terminal_sections_from_chapter_catalog_html(
            payload.decode(),
            source_url=MN_TERMINAL_CATALOG_URL,
        )
    )
    assert typed == {
        MN_TERMINAL_URL: {
            "section_number": "73.55",
            "catalog_text": "[Renumbered 299F.40, subd 5]",
            "disposition": "renumbered",
            "renumbered_to": MN_TERMINAL_TARGET_URL,
            "catalog_url": MN_TERMINAL_CATALOG_URL,
            "catalog_content_sha256": hashlib.sha256(payload).hexdigest(),
        }
    }
    assert (
        minnesota._source_bound_terminal_sections_from_chapter_catalog_html(
            payload.decode(),
            source_url=f"{MN_TERMINAL_CATALOG_URL}?copy=1",
        )
        == {}
    )
    assert (
        minnesota._source_bound_terminal_sections_from_chapter_catalog_html(
            payload.decode().replace("subd 5", "subd 6"),
            source_url=MN_TERMINAL_CATALOG_URL,
        )
        == {}
    )

    drifted_dom = payload.replace(b"<tr>", b"<tr class='changed'>", 1)
    drifted_contract = {
        **contract,
        "content_sha256": hashlib.sha256(drifted_dom).hexdigest(),
        "content_byte_size": len(drifted_dom),
    }
    monkeypatch.setattr(
        minnesota,
        "_EXACT_TERMINAL_CHAPTER_CATALOGS",
        {MN_TERMINAL_CATALOG_URL: drifted_contract},
    )
    assert (
        minnesota._source_bound_terminal_sections_from_chapter_catalog_html(
            drifted_dom.decode(),
            source_url=MN_TERMINAL_CATALOG_URL,
        )
        == {}
    )


def test_minnesota_source_bound_terminal_catalog_replays_retained_contract() -> None:
    evidence_root = os.getenv("STATE_LAWS_TEST_MN_EVIDENCE_ROOT", "").strip()
    if not evidence_root:
        pytest.skip("requires retained Minnesota acquisition evidence")

    expected = minnesota._EXACT_TERMINAL_CHAPTER_CATALOGS[
        MN_TERMINAL_CATALOG_URL
    ]
    jurisdiction_root = Path(evidence_root) / "MN"
    payload_path = (
        jurisdiction_root
        / "objects"
        / f'{expected["content_sha256"]}.bin'
    )
    payload = payload_path.read_bytes()
    assert len(payload) == expected["content_byte_size"]
    assert hashlib.sha256(payload).hexdigest() == expected["content_sha256"]

    fetch_path = (
        jurisdiction_root
        / "fetches"
        / f'{expected["receipt_sha256"]}.json'
    )
    fetch = json.loads(fetch_path.read_text(encoding="utf-8"))
    receipt = fetch["parser_input_envelope"]["acquisition"]["receipt"]
    assert fetch["authorizes_parser_admission"] is True
    assert receipt["endpoint"] == MN_TERMINAL_CATALOG_URL
    assert receipt["response_status"] == 200
    assert receipt["receipt_sha256"] == expected["receipt_sha256"]
    assert receipt["receipt_cid"] == expected["receipt_cid"]
    assert receipt["content"]["sha256"] == expected["content_sha256"]
    assert receipt["content"]["cid"] == expected["content_cid"]
    assert receipt["metadata"]["transport_receipt"]["source_transport"] == (
        "direct"
    )

    typed = (
        minnesota._source_bound_terminal_sections_from_chapter_catalog_html(
            payload.decode("utf-8"),
            source_url=MN_TERMINAL_CATALOG_URL,
        )
    )
    assert len(typed) == 52
    assert MN_TERMINAL_URL in typed
    assert "https://www.revisor.mn.gov/statutes/cite/73.18" not in typed
    assert typed[MN_TERMINAL_URL]["catalog_text"] == (
        "[Renumbered 299F.40, subd 5]"
    )
    assert typed[MN_TERMINAL_URL]["renumbered_to"] == MN_TERMINAL_TARGET_URL
    assert {record["disposition"] for record in typed.values()} == {
        "renumbered"
    }


@pytest.mark.anyio
async def test_minnesota_unbounded_tree_excludes_exact_catalog_terminals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MinnesotaScraper("MN", "Minnesota")
    catalog_payload = _mn_terminal_catalog_payload(include_active=True)
    active_url = "https://www.revisor.mn.gov/statutes/cite/73.63"
    pages = {
        MN_TERMINAL_CATALOG_URL: catalog_payload,
        active_url: _mn_section_payload("73.63"),
    }
    plural_calls: list[list[str]] = []
    checkpoints: list[dict[str, Any]] = []
    monkeypatch.setattr(
        minnesota,
        "_EXACT_TERMINAL_CHAPTER_CATALOGS",
        {
            MN_TERMINAL_CATALOG_URL: _mn_fixture_terminal_contract(
                catalog_payload
            )
        },
    )

    async def _discover(*, max_chapters: int | None) -> list[str]:
        assert max_chapters is None
        return [MN_TERMINAL_CATALOG_URL]

    async def _plural(urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        plural_calls.append(requested)
        return _aligned_result(requested, [pages[url] for url in requested])

    def _checkpoint(_rows, **kwargs: Any) -> bool:
        checkpoints.append(dict(kwargs))
        return True

    monkeypatch.setattr(scraper, "_discover_chapter_urls", _discover)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", _checkpoint)

    rows = await scraper._scrape_chapter_sections(
        "Minnesota Statutes",
        max_statutes=None,
    )

    assert [row.source_url for row in rows] == [active_url]
    assert plural_calls == [[MN_TERMINAL_CATALOG_URL], [active_url]]
    assert all(MN_TERMINAL_URL not in call for call in plural_calls)
    assert [checkpoint["stage_label"] for checkpoint in checkpoints] == [
        "minnesota:section-progress",
        "minnesota:complete",
    ]
    for checkpoint in checkpoints:
        assert checkpoint["extra"]["terminal_sections_excluded"] == 1
        assert checkpoint["extra"]["terminal_section_urls"] == [
            MN_TERMINAL_URL
        ]
        assert checkpoint["extra"]["terminal_disposition_counts"] == {
            "renumbered": 1
        }


@pytest.mark.anyio
async def test_minnesota_unbounded_tree_uses_one_cross_chapter_section_wave(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MinnesotaScraper("MN", "Minnesota")
    calls: list[tuple[list[str], dict[str, Any]]] = []
    checkpoints: list[dict[str, Any]] = []
    pages = {
        MN_CHAPTER_URLS[0]: _mn_chapter_payload("1.01", "1.02"),
        MN_CHAPTER_URLS[1]: _mn_chapter_payload("2.01"),
        **{
            url: _mn_section_payload(url.rsplit("/", 1)[-1])
            for url in MN_SECTION_URLS
        },
    }

    async def _discover(*, max_chapters: int | None) -> list[str]:
        assert max_chapters is None
        return list(MN_CHAPTER_URLS)

    async def _forbid_singleton(*_args: Any, **_kwargs: Any) -> bytes:
        raise AssertionError("uncapped Minnesota must not fetch known-page singletons")

    async def _forbid_singleton_builder(*_args: Any, **_kwargs: Any):
        raise AssertionError("uncapped Minnesota must parse retained plural payloads")

    async def _plural(urls, **kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        calls.append((requested, dict(kwargs)))
        return _aligned_result(requested, [pages[url] for url in requested])

    def _checkpoint(*_args: Any, **kwargs: Any) -> bool:
        checkpoints.append(dict(kwargs))
        return True

    monkeypatch.setenv("STATE_SCRAPER_MN_FRONTIER_BATCH_SIZE", "2")
    monkeypatch.setenv("STATE_SCRAPER_MN_FRONTIER_CONCURRENCY", "3")
    monkeypatch.setattr(scraper, "_discover_chapter_urls", _discover)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_content_with_archival_fallback",
        _forbid_singleton,
    )
    monkeypatch.setattr(
        scraper,
        "_build_statute_from_section_page",
        _forbid_singleton_builder,
    )
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", _checkpoint)

    statutes = await scraper._scrape_chapter_sections(
        "Minnesota Statutes",
        max_statutes=None,
    )

    assert [requested for requested, _kwargs in calls] == [
        MN_CHAPTER_URLS,
        MN_SECTION_URLS,
    ]
    assert all(
        kwargs
        == {
            "timeout_seconds": 35,
            "media_type": "text/html",
            "max_concurrency": 3,
            "prefer_direct": True,
            "common_crawl_domain_terms": ("www.revisor.mn.gov",),
            "common_crawl_url_terms": ("/statutes/",),
            "common_crawl_mime_terms": ("html",),
            "wayback_prefix_inventory": True,
        }
        for _requested, kwargs in calls
    )
    assert [row.source_url for row in statutes] == MN_SECTION_URLS
    assert [row.section_number for row in statutes] == ["1.01", "1.02", "2.01"]
    assert checkpoints[-1]["stage_label"] == "minnesota:complete"
    assert checkpoints[-1]["extra"]["sections_scanned"] == 3
    assert checkpoints[-1]["extra"]["discovered_sections"] == 3


@pytest.mark.anyio
async def test_minnesota_full_scrape_skips_the_duplicate_direct_seed_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MinnesotaScraper("MN", "Minnesota")
    rows = [
        NormalizedStatute(
            state_code="MN",
            state_name="Minnesota",
            statute_id=f"Minnesota Statutes § 1.{index:02d}",
            code_name="Minnesota Statutes",
            section_number=f"1.{index:02d}",
            full_text="Official Minnesota statutory text. " * 8,
            source_url=f"https://www.revisor.mn.gov/statutes/cite/1.{index:02d}",
            official_cite=f"Minn. Stat. § 1.{index:02d}",
        )
        for index in range(1, 81)
    ]

    async def _tree(_code_name: str, max_statutes: int | None):
        assert max_statutes is None
        return rows

    async def _forbid_seed(*_args: Any, **_kwargs: Any):
        raise AssertionError("full Minnesota crawl must not refetch its seed section")

    monkeypatch.setattr(scraper, "_full_corpus_enabled", lambda: True)
    monkeypatch.setattr(scraper, "_scrape_chapter_sections", _tree)
    monkeypatch.setattr(scraper, "_build_statute_from_section_page", _forbid_seed)

    statutes = await scraper.scrape_code(
        "Minnesota Statutes",
        "https://www.revisor.mn.gov/statutes/cite/609.02",
        max_statutes=None,
    )

    assert statutes == rows


@pytest.mark.anyio
async def test_minnesota_unbounded_named_toc_batches_part_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MinnesotaScraper("MN", "Minnesota")
    root_url = "https://www.revisor.mn.gov/statutes/"
    part_urls = [
        "https://www.revisor.mn.gov/statutes/part-1",
        "https://www.revisor.mn.gov/statutes/part-2",
    ]
    chapter_urls = [
        "https://www.revisor.mn.gov/statutes/cite/1",
        "https://www.revisor.mn.gov/statutes/cite/2",
    ]
    root = _mn_current_page(
        "<table id='toc_table'>"
        "<tr><td><a href='/statutes/part-1'>1 - 1</a></td><td>Part 1</td></tr>"
        "<tr><td><a href='/statutes/part-2'>2 - 2</a></td><td>Part 2</td></tr>"
        "</table>"
    )
    parts = {
        part_urls[0]: _mn_current_page(
            "<table id='chapters_table'><tr><td>"
            "<a href='/statutes/cite/1'>1</a></td><td>Chapter 1</td></tr></table>"
        ),
        part_urls[1]: _mn_current_page(
            "<table id='chapters_table'><tr><td>"
            "<a href='/statutes/cite/2'>2</a></td><td>Chapter 2</td></tr></table>"
        ),
    }
    singleton_calls: list[str] = []
    plural_calls: list[list[str]] = []

    async def _single(url: str, **_kwargs: Any) -> bytes:
        singleton_calls.append(url)
        assert url == root_url
        return root

    async def _plural(urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        plural_calls.append(requested)
        return _aligned_result(requested, [parts[url] for url in requested])

    monkeypatch.setattr(
        scraper,
        "_fetch_page_content_with_archival_fallback",
        _single,
    )
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )
    # Parsing/checkpoint size must not split a known same-domain acquisition
    # frontier into repeated archive inventory waves.
    monkeypatch.setenv("STATE_SCRAPER_MN_FRONTIER_BATCH_SIZE", "1")

    discovered = await scraper._discover_chapter_urls(max_chapters=None)

    assert singleton_calls == [root_url]
    assert plural_calls == [part_urls]
    assert discovered == chapter_urls


def _mt_pages() -> dict[str, bytes]:
    return {
        MT_ROOT_URL: (
            "<html><body>"
            "<a href='title_0010/chapters_index.html'>Title 1</a>"
            "<a href='title_0020/chapters_index.html'>Title 2</a>"
            "</body></html>"
        ).encode(),
        MT_TITLE_URLS[0]: (
            "<a href='chapter_0010/parts_index.html'>Chapter 1</a>"
        ).encode(),
        MT_TITLE_URLS[1]: (
            "<a href='chapter_0010/parts_index.html'>Chapter 1</a>"
        ).encode(),
        MT_CHAPTER_URLS[0]: (
            "<a href='part_0010/sections_index.html'>Part 1</a>"
        ).encode(),
        MT_CHAPTER_URLS[1]: (
            "<a href='part_0010/sections_index.html'>Part 1</a>"
        ).encode(),
        MT_PART_URLS[0]: (
            "<a href='section_0010/0010-0010-0010-0010.html'>"
            "1-1-101 First provision</a>"
            "<a href='section_0020/0010-0010-0010-0020.html'>"
            "1-1-102 Second provision</a>"
        ).encode(),
        MT_PART_URLS[1]: (
            "<a href='section_0010/0020-0010-0010-0010.html'>"
            "2-1-101 Third provision</a>"
        ).encode(),
        MT_SECTION_URLS[0]: _mt_section_payload("1-1-101"),
        MT_SECTION_URLS[1]: _mt_section_payload("1-1-102"),
        MT_SECTION_URLS[2]: _mt_section_payload("2-1-101"),
    }


def test_montana_source_bound_terminal_part_rejects_identity_content_and_dom_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    part_url = (
        "https://leg.mt.gov/bills/mca/title_0390/chapter_0710/"
        "part_0230/sections_index.html"
    )
    terminal_url = (
        "https://leg.mt.gov/bills/mca/title_0390/chapter_0710/part_0230/"
        "section_0260/0390-0710-0230-0260.html"
    )
    payload = _mt_terminal_part_payload()
    contract = {
        "content_sha256": hashlib.sha256(payload).hexdigest(),
        "content_cid": "fixture-content-cid",
        "content_byte_size": len(payload),
        "receipt_sha256": "fixture-receipt-sha256",
        "receipt_cid": "fixture-receipt-cid",
        "terminal_sections": {
            "39-71-2326": {
                "href": "./section_0260/0390-0710-0230-0260.html",
                "catalog_text": "39-71-2326 Repealed",
                "disposition": "repealed",
            }
        },
    }
    monkeypatch.setattr(
        montana,
        "_EXACT_TERMINAL_PART_CATALOGS",
        {part_url: contract},
    )

    assert montana._source_bound_terminal_sections_from_part_catalog_html(
        payload.decode(),
        source_url=part_url,
    ) == {
        terminal_url: {
            "section_number": "39-71-2326",
            "catalog_text": "39-71-2326 Repealed",
            "disposition": "repealed",
            "catalog_url": part_url,
            "catalog_content_sha256": contract["content_sha256"],
            "catalog_content_cid": "fixture-content-cid",
            "catalog_receipt_sha256": "fixture-receipt-sha256",
            "catalog_receipt_cid": "fixture-receipt-cid",
        }
    }
    assert (
        montana._source_bound_terminal_sections_from_part_catalog_html(
            payload.decode(),
            source_url=f"{part_url}?copy=1",
        )
        == {}
    )
    assert (
        montana._source_bound_terminal_sections_from_part_catalog_html(
            _mt_terminal_part_payload(heading="Reserved").decode(),
            source_url=part_url,
        )
        == {}
    )

    drifted_dom = payload.replace(
        b"<li class='line'><a href='./section_0260/",
        b"<li><a href='./section_0260/",
        1,
    )
    monkeypatch.setattr(
        montana,
        "_EXACT_TERMINAL_PART_CATALOGS",
        {
            part_url: {
                **contract,
                "content_sha256": hashlib.sha256(drifted_dom).hexdigest(),
                "content_byte_size": len(drifted_dom),
            }
        },
    )
    assert (
        montana._source_bound_terminal_sections_from_part_catalog_html(
            drifted_dom.decode(),
            source_url=part_url,
        )
        == {}
    )


def test_montana_source_bound_terminal_part_replays_retained_contract() -> None:
    evidence_root = os.getenv("STATE_LAWS_TEST_MT_EVIDENCE_ROOT", "").strip()
    if not evidence_root:
        pytest.skip("requires retained Montana acquisition evidence")

    part_url, expected = next(iter(montana._EXACT_TERMINAL_PART_CATALOGS.items()))
    jurisdiction_root = Path(evidence_root) / "MT"
    payload_path = (
        jurisdiction_root / "objects" / f'{expected["content_sha256"]}.bin'
    )
    payload = payload_path.read_bytes()
    assert len(payload) == expected["content_byte_size"]
    assert hashlib.sha256(payload).hexdigest() == expected["content_sha256"]

    fetch_path = (
        jurisdiction_root / "fetches" / f'{expected["receipt_sha256"]}.json'
    )
    fetch = json.loads(fetch_path.read_text(encoding="utf-8"))
    receipt = fetch["parser_input_envelope"]["acquisition"]["receipt"]
    assert fetch["authorizes_parser_admission"] is True
    assert receipt["endpoint"] == part_url
    assert receipt["response_status"] == 200
    assert receipt["content"]["sha256"] == expected["content_sha256"]
    assert receipt["content"]["cid"] == expected["content_cid"]
    assert receipt["receipt_sha256"] == expected["receipt_sha256"]
    assert receipt["receipt_cid"] == expected["receipt_cid"]

    typed = montana._source_bound_terminal_sections_from_part_catalog_html(
        payload.decode("utf-8"),
        source_url=part_url,
    )
    assert list(typed) == [
        "https://leg.mt.gov/bills/mca/title_0390/chapter_0710/part_0230/"
        "section_0260/0390-0710-0230-0260.html"
    ]
    assert typed[next(iter(typed))]["disposition"] == "repealed"


@pytest.mark.parametrize(
    ("url", "label", "expected"),
    [
        (
            "https://leg.mt.gov/bills/mca/title_0200/chapter_0070/part_0030/"
            "section_0021/0200-0070-0030-0021.html",
            "20-7-302.1 Renumbered 20-7-308",
            "20-7-302.1",
        ),
        (
            "https://leg.mt.gov/bills/mca/title_0230/chapter_0020/part_0060/"
            "section_0151/0230-0020-0060-0151.html",
            "23-2-615.1 Renumbered 23-2-626",
            "23-2-615.1",
        ),
        (
            "https://leg.mt.gov/bills/mca/title_0250/chapter_0200/part_0020/"
            "section_0041/0250-0200-0020-0041.html",
            "Rule 4.1 Limited Representation Permitted",
            "25-20-204.1",
        ),
        (
            "https://leg.mt.gov/bills/mca/title_0250/chapter_0200/part_0080/"
            "section_0651/0250-0200-0080-0651.html",
            "***No Montana Rule 65.1.***",
            "25-20-865.1",
        ),
        (
            "https://leg.mt.gov/bills/mca/title_0250/chapter_0200/part_0120/"
            "section_0181/0250-0200-0120-0181.html",
            "Form 18-A NOTICE OF A LAWSUIT",
            "25-20-1218-A",
        ),
        (
            "https://leg.mt.gov/bills/mca/title_0250/chapter_0200/part_0120/"
            "section_0182/0250-0200-0120-0182.html",
            "Form 18-B Acknowledgment and Waiver",
            "25-20-1218-B",
        ),
        (
            "https://leg.mt.gov/bills/mca/title_0250/chapter_0210/part_0020/"
            "section_0011/0250-0210-0020-0011.html",
            "Form 1A",
            "25-21-201A",
        ),
    ],
)
def test_montana_section_identity_preserves_source_ordinal_qualifiers(
    url: str,
    label: str,
    expected: str,
) -> None:
    scraper = MontanaScraper("MT", "Montana")
    assert (
        scraper._section_number_from_mca_url(url, section_label=label)
        == expected
    )
    statute = scraper._build_official_html_section_statute_from_html(
        "Montana Code Annotated",
        label,
        url,
        _mt_section_payload(expected).decode(),
    )
    assert statute is not None
    assert statute.section_number == expected
    assert statute.statute_id == f"Montana Code Annotated § {expected}"
    assert statute.official_cite == f"Mont. Code Ann. § {expected}"


def test_montana_nonzero_source_ordinal_without_identity_label_fails_closed() -> None:
    scraper = MontanaScraper("MT", "Montana")
    url = (
        "https://leg.mt.gov/bills/mca/title_0250/chapter_0200/part_0020/"
        "section_0041/0250-0200-0020-0041.html"
    )
    with pytest.raises(ValueError, match="nonzero source ordinal"):
        scraper._section_number_from_mca_url(
            url,
            section_label="Unbound duplicate identity",
        )


@pytest.mark.anyio
async def test_montana_unbounded_tree_unions_every_known_hierarchy_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MontanaScraper("MT", "Montana")
    pages = _mt_pages()
    single_calls: list[str] = []
    plural_calls: list[tuple[list[str], dict[str, Any]]] = []
    checkpoints: list[dict[str, Any]] = []

    async def _single(url: str, timeout_seconds: int = 25) -> bytes:
        single_calls.append(url)
        assert url == MT_ROOT_URL
        return pages[url]

    async def _plural(urls, **kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        plural_calls.append((requested, dict(kwargs)))
        return _aligned_result(requested, [pages[url] for url in requested])

    def _checkpoint(*_args: Any, **kwargs: Any) -> bool:
        checkpoints.append(dict(kwargs))
        return True

    monkeypatch.setenv("STATE_SCRAPER_MT_FRONTIER_BATCH_SIZE", "2")
    monkeypatch.setenv("STATE_SCRAPER_MT_FRONTIER_CONCURRENCY", "4")
    monkeypatch.setattr(
        scraper,
        "_fetch_page_content_with_archival_fallback",
        _single,
    )
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", _checkpoint)

    statutes = await scraper._scrape_official_mca_html_tree(
        "Montana Code Annotated",
        max_statutes=None,
    )

    assert single_calls == [MT_ROOT_URL]
    assert [requested for requested, _kwargs in plural_calls] == [
        MT_TITLE_URLS,
        MT_CHAPTER_URLS,
        MT_PART_URLS,
        MT_SECTION_URLS,
    ]
    assert all(
        kwargs
        == {
            "timeout_seconds": 25,
            "media_type": "text/html",
            "max_concurrency": 4,
            "prefer_direct": True,
            "common_crawl_domain_terms": ("leg.mt.gov",),
            "common_crawl_url_terms": ("/bills/mca/",),
            "common_crawl_mime_terms": ("html",),
            "wayback_prefix_inventory": True,
        }
        for _requested, kwargs in plural_calls
    )
    assert [row.source_url for row in statutes] == MT_SECTION_URLS
    assert [row.section_number for row in statutes] == [
        "1-1-101",
        "1-1-102",
        "2-1-101",
    ]
    assert checkpoints[-1]["stage_label"] == "montana:complete"
    assert checkpoints[-1]["extra"]["sections_scanned"] == 3
    assert checkpoints[-1]["extra"]["discovered_sections"] == 3


@pytest.mark.anyio
async def test_montana_exact_terminal_link_is_excluded_before_section_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MontanaScraper("MT", "Montana")
    title_url = (
        "https://leg.mt.gov/bills/mca/title_0390/chapters_index.html"
    )
    chapter_url = (
        "https://leg.mt.gov/bills/mca/title_0390/chapter_0710/parts_index.html"
    )
    part_url = (
        "https://leg.mt.gov/bills/mca/title_0390/chapter_0710/"
        "part_0230/sections_index.html"
    )
    operative_urls = [
        (
            "https://leg.mt.gov/bills/mca/title_0390/chapter_0710/part_0230/"
            "section_0120/0390-0710-0230-0120.html"
        ),
        (
            "https://leg.mt.gov/bills/mca/title_0390/chapter_0710/part_0230/"
            "section_0270/0390-0710-0230-0270.html"
        ),
    ]
    terminal_url = (
        "https://leg.mt.gov/bills/mca/title_0390/chapter_0710/part_0230/"
        "section_0260/0390-0710-0230-0260.html"
    )
    part_payload = _mt_terminal_part_payload()
    contract = {
        "content_sha256": hashlib.sha256(part_payload).hexdigest(),
        "content_cid": "fixture-content-cid",
        "content_byte_size": len(part_payload),
        "receipt_sha256": "fixture-receipt-sha256",
        "receipt_cid": "fixture-receipt-cid",
        "terminal_sections": {
            "39-71-2326": {
                "href": "./section_0260/0390-0710-0230-0260.html",
                "catalog_text": "39-71-2326 Repealed",
                "disposition": "repealed",
            }
        },
    }
    monkeypatch.setattr(
        montana,
        "_EXACT_TERMINAL_PART_CATALOGS",
        {part_url: contract},
    )
    pages = {
        title_url: (
            "<a href='chapter_0710/parts_index.html'>Chapter 71</a>"
        ).encode(),
        chapter_url: (
            "<a href='part_0230/sections_index.html'>Part 23</a>"
        ).encode(),
        part_url: part_payload,
        operative_urls[0]: _mt_section_payload("39-71-2312"),
        operative_urls[1]: _mt_section_payload("39-71-2327"),
    }
    calls: list[list[str]] = []
    checkpoints: list[dict[str, Any]] = []

    async def _plural(urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        calls.append(requested)
        assert terminal_url not in requested
        return _aligned_result(requested, [pages[url] for url in requested])

    monkeypatch.setenv("STATE_SCRAPER_FRONTIER_RESIDUAL_RETRY_ATTEMPTS", "0")
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )
    monkeypatch.setattr(
        scraper,
        "_write_partial_checkpoint",
        lambda *_args, **kwargs: checkpoints.append(dict(kwargs)) or True,
    )

    statutes = await scraper._scrape_official_mca_html_frontier(
        "Montana Code Annotated",
        [("Title 39", title_url)],
    )

    assert calls == [[title_url], [chapter_url], [part_url], operative_urls]
    assert [row.section_number for row in statutes] == [
        "39-71-2312",
        "39-71-2327",
    ]
    assert scraper._last_montana_catalog_terminal_sections[terminal_url][
        "catalog_receipt_sha256"
    ] == "fixture-receipt-sha256"
    assert checkpoints[-1]["extra"]["terminal_sections_excluded"] == 1
    assert checkpoints[-1]["extra"]["terminal_section_urls"] == [terminal_url]
    assert checkpoints[-1]["extra"]["terminal_disposition_counts"] == {
        "repealed": 1
    }


@pytest.mark.anyio
async def test_montana_section_frontier_retries_only_exact_residual_misses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MontanaScraper("MT", "Montana")
    urls = [
        "https://leg.mt.gov/bills/mca/one.html",
        "https://leg.mt.gov/bills/mca/two.html",
        "https://leg.mt.gov/bills/mca/three.html",
    ]
    calls: list[list[str]] = []

    async def _plural(requested_urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(requested_urls)
        calls.append(requested)
        if len(calls) == 1:
            assert requested == urls
            return _aligned_result(
                requested,
                [b"one", b"", b""],
                errors=[None, "transient miss", "transient miss"],
            )
        assert requested == urls[1:]
        return _aligned_result(requested, [b"two", b"three"])

    monkeypatch.setenv("STATE_SCRAPER_FRONTIER_RESIDUAL_RETRY_ATTEMPTS", "1")
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )

    payloads = await scraper._fetch_montana_frontier_batch(
        urls,
        frontier_name="section",
    )

    assert calls == [urls, urls[1:]]
    assert payloads == [b"one", b"two", b"three"]
    assert scraper._last_page_multifetch_stats[
        "residual_retry_recovered_pages"
    ] == 2


@pytest.mark.anyio
async def test_montana_unbounded_reader_fallback_batches_known_levels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MontanaScraper("MT", "Montana")
    title_url = "https://mca.legmt.gov/bills/mca/title_0010/chapters_index.html"
    chapter_url = (
        "https://mca.legmt.gov/bills/mca/title_0010/"
        "chapter_0010/parts_index.html"
    )
    part_url = (
        "https://mca.legmt.gov/bills/mca/title_0010/chapter_0010/"
        "part_0010/sections_index.html"
    )
    source_urls = [url.replace("https://leg.mt.gov", "https://mca.legmt.gov") for url in MT_SECTION_URLS[:2]]

    def _reader_url(url: str) -> str:
        return f"https://r.jina.ai/http://{url}"

    markdown_by_reader_url = {
        _reader_url(title_url): (
            f"[Chapter 1]({chapter_url})"
        ).encode(),
        _reader_url(chapter_url): (
            f"[Part 1]({part_url})"
        ).encode(),
        _reader_url(part_url): (
            f"[1-1-101 First provision]({source_urls[0]})"
            f"[1-1-102 Second provision]({source_urls[1]})"
        ).encode(),
        _reader_url(source_urls[0]): (
            "# 1-1-101. First provision.\n"
            + ("Official Montana reader statutory text. " * 12)
        ).encode(),
        _reader_url(source_urls[1]): (
            "# 1-1-102. Second provision.\n"
            + ("Official Montana reader statutory text. " * 12)
        ).encode(),
    }
    calls: list[tuple[list[str], dict[str, Any]]] = []

    async def _plural(urls, **kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        calls.append((requested, dict(kwargs)))
        return _aligned_result(
            requested,
            [markdown_by_reader_url[url] for url in requested],
        )

    monkeypatch.setenv("STATE_SCRAPER_MT_FRONTIER_BATCH_SIZE", "2")
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )
    monkeypatch.setattr(
        scraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    statutes = await scraper._scrape_official_mca_reader_frontier(
        "Montana Code Annotated",
        [("Title 1", title_url)],
    )

    assert [requested for requested, _kwargs in calls] == [
        [_reader_url(title_url)],
        [_reader_url(chapter_url)],
        [_reader_url(part_url)],
        [_reader_url(source_urls[0]), _reader_url(source_urls[1])],
    ]
    assert all(
        kwargs
        == {
            "timeout_seconds": 25,
            "media_type": "text/plain",
            "max_concurrency": 8,
            "prefer_direct": True,
            "common_crawl_domain_terms": ("r.jina.ai",),
            "common_crawl_url_terms": ("/http://https://",),
            "common_crawl_mime_terms": ("text", "html"),
            "wayback_prefix_inventory": True,
        }
        for _requested, kwargs in calls
    )
    assert [row.source_url for row in statutes] == source_urls
    assert [row.section_number for row in statutes] == ["1-1-101", "1-1-102"]


@pytest.mark.anyio
@pytest.mark.parametrize("state", ["MN", "MT"])
@pytest.mark.parametrize("malformation", ["reordered", "short-vector"])
async def test_uncapped_state_frontier_rejects_alignment_drift(
    monkeypatch: pytest.MonkeyPatch,
    state: str,
    malformation: str,
) -> None:
    scraper: MinnesotaScraper | MontanaScraper
    if state == "MN":
        scraper = MinnesotaScraper("MN", "Minnesota")
        urls = [
            "https://www.revisor.mn.gov/statutes/cite/1.01",
            "https://www.revisor.mn.gov/statutes/cite/1.02",
        ]
    else:
        scraper = MontanaScraper("MT", "Montana")
        urls = ["https://example.test/one", "https://example.test/two"]

    async def _malformed(requested_urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(requested_urls)
        if malformation == "reordered":
            return _aligned_result(
                requested,
                [b"one", b"two"],
                returned_urls=list(reversed(requested)),
            )
        result = _aligned_result(requested, [b"one", b"two"])
        result.errors = [None]
        return result

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _malformed,
    )

    expected = (
        "changed URL order or identity"
        if malformation == "reordered"
        else "unaligned acquisition rows"
    )
    with pytest.raises(RuntimeError, match=expected):
        if state == "MN":
            await scraper._fetch_minnesota_frontier_batch(  # type: ignore[union-attr]
                urls,
                frontier_name="section",
            )
        else:
            await scraper._fetch_montana_frontier_batch(  # type: ignore[union-attr]
                urls,
                frontier_name="section",
            )


@pytest.mark.anyio
@pytest.mark.parametrize("state", ["MN", "MT"])
async def test_uncapped_state_frontier_fails_promptly_on_typed_miss(
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    scraper: MinnesotaScraper | MontanaScraper
    monkeypatch.setenv(
        "STATE_SCRAPER_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
        "0",
    )
    if state == "MN":
        scraper = MinnesotaScraper("MN", "Minnesota")
        urls = [
            "https://www.revisor.mn.gov/statutes/cite/1.01",
            "https://www.revisor.mn.gov/statutes/cite/1.02",
        ]
    else:
        scraper = MontanaScraper("MT", "Montana")
        urls = ["https://example.test/one", "https://example.test/two"]

    async def _typed_miss(requested_urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(requested_urls)
        return _aligned_result(
            requested,
            [b"retained", b""],
            errors=[
                None,
                "TimeoutError: residual archival fallback exceeded its deadline",
            ],
        )

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _typed_miss,
    )

    with pytest.raises(RuntimeError, match="frontier is incomplete"):
        if state == "MN":
            await scraper._fetch_minnesota_frontier_batch(  # type: ignore[union-attr]
                urls,
                frontier_name="section",
            )
        else:
            await scraper._fetch_montana_frontier_batch(  # type: ignore[union-attr]
                urls,
                frontier_name="section",
            )
