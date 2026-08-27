"""No-per-page regressions for repaired strict state hierarchy waves."""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    NormalizedStatute,
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.delaware import (
    DelawareScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.district_of_columbia import (
    DistrictOfColumbiaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.hawaii import (
    HawaiiScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_mexico import (
    NewMexicoScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.ohio import OhioScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oklahoma import (
    OklahomaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.pennsylvania import (
    PennsylvaniaScraper,
)


def _aligned_result(
    urls: list[str],
    payload_by_url: dict[str, bytes],
    *,
    receipts: bool = False,
) -> StateLawPageMultiFetchResult:
    payloads = [payload_by_url[url] for url in urls]
    return StateLawPageMultiFetchResult(
        urls=list(urls),
        payloads=payloads,
        errors=[None] * len(urls),
        transport_receipts=(
            [
                {
                    "content_sha256": hashlib.sha256(payload).hexdigest(),
                    "official_url": url,
                    "source_transport": "direct",
                }
                for url, payload in zip(urls, payloads, strict=True)
            ]
            if receipts
            else [None] * len(urls)
        ),
        parser_input_envelopes=[None] * len(urls),
        stats={"requested_pages": len(urls)},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scraper", "helper_name"),
    [
        (DelawareScraper("DE", "Delaware"), "_fetch_de_html_frontier"),
        (
            DistrictOfColumbiaScraper("DC", "District of Columbia"),
            "_fetch_dc_html_frontier",
        ),
        (HawaiiScraper("HI", "Hawaii"), "_fetch_hi_html_frontier"),
        (NewMexicoScraper("NM", "New Mexico"), "_fetch_nm_html_frontier"),
        (OhioScraper("OH", "Ohio"), "_fetch_oh_html_frontier"),
    ],
)
async def test_repaired_html_helpers_use_one_plural_residual_seam_and_no_singleton(
    monkeypatch: pytest.MonkeyPatch,
    scraper: Any,
    helper_name: str,
) -> None:
    urls = [
        f"https://{scraper.OFFICIAL_DOMAIN}/test/a.html",
        f"https://{scraper.OFFICIAL_DOMAIN}/test/b.html",
    ]
    html = (
        b"<html><body>Official statutory catalog content with enough text "
        b"to satisfy the Hawaii page validator.</body></html>"
    )
    payloads = {url: html for url in urls}
    calls: list[tuple[list[str], dict[str, Any]]] = []

    async def _plural(requested_urls, **kwargs):
        requested = list(requested_urls)
        calls.append((requested, dict(kwargs)))
        return _aligned_result(requested, payloads, receipts=True)

    async def _singleton(*_args, **_kwargs):
        raise AssertionError("known plural frontier must not use singleton archival fetch")

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    monkeypatch.setattr(
        scraper,
        "_fetch_page_content_with_archival_fallback",
        _singleton,
    )

    result = await getattr(scraper, helper_name)(urls, frontier_name="test wave")

    assert list(result) == urls
    assert [call[0] for call in calls] == [urls]
    assert calls[0][1]["residual_retry_attempts"] == 1
    assert calls[0][1]["wayback_prefix_inventory"] is True


@pytest.mark.asyncio
async def test_dc_full_hierarchy_batches_each_known_wave(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = DistrictOfColumbiaScraper("DC", "District of Columbia")
    titles = [
        "https://code.dccouncil.gov/us/dc/council/code/titles/1",
        "https://code.dccouncil.gov/us/dc/council/code/titles/2",
    ]
    chapters = [f"{url}/chapters/1" for url in titles]
    sections = [
        "https://code.dccouncil.gov/us/dc/council/code/sections/1-101",
        "https://code.dccouncil.gov/us/dc/council/code/sections/2-101",
    ]
    payloads = {
        **{
            title: f'<html><a href="{chapter}">Chapter 1</a></html>'.encode()
            for title, chapter in zip(titles, chapters, strict=True)
        },
        **{
            chapter: f'<html><a href="{section}">Section</a></html>'.encode()
            for chapter, section in zip(chapters, sections, strict=True)
        },
        **{
            section: (
                f"<html><h1>Section {index}-101</h1><main>"
                + ("Official enacted District of Columbia statutory text. " * 8)
                + "</main></html>"
            ).encode()
            for index, section in enumerate(sections, start=1)
        },
    }
    calls: list[list[str]] = []

    async def _titles():
        return [(url, f"Title {index}") for index, url in enumerate(titles, start=1)]

    async def _plural(requested_urls, **_kwargs):
        requested = list(requested_urls)
        calls.append(requested)
        return _aligned_result(requested, payloads)

    async def _singleton(*_args, **_kwargs):
        raise AssertionError("D.C. child hierarchy used a singleton fetch")

    monkeypatch.setattr(scraper, "_discover_title_links", _titles)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    monkeypatch.setattr(scraper, "_fetch_page_content_with_archival_fallback", _singleton)

    rows = await scraper._scrape_official_index("District of Columbia Code")

    assert calls == [titles, chapters, sections]
    assert [row.section_number for row in rows] == ["1-101", "2-101"]


@pytest.mark.asyncio
async def test_new_mexico_full_hierarchy_allows_one_root_then_plural_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = NewMexicoScraper("NM", "New Mexico")
    root = scraper.OFFICIAL_ENTRY_URL
    chapters = [f"{root}?chapter={number}" for number in (1, 2)]
    sections = [
        f"https://nmonesource.com/nmos/nmsa/en/document.do?section={number}-1"
        for number in (1, 2)
    ]
    root_html = "".join(
        f'<a href="{url}">Chapter {index}</a>'
        for index, url in enumerate(chapters, start=1)
    ).encode()
    payloads = {
        **{
            chapter: f'<html><a href="{section}">{index}-1</a></html>'.encode()
            for index, (chapter, section) in enumerate(
                zip(chapters, sections, strict=True), start=1
            )
        },
        **{
            section: (
                f"<html><h1>Section {index}-1</h1><body>"
                + ("Official New Mexico statutory body text. " * 8)
                + "</body></html>"
            ).encode()
            for index, section in enumerate(sections, start=1)
        },
    }
    singleton_calls: list[str] = []
    plural_calls: list[list[str]] = []

    async def _singleton(url: str, **_kwargs):
        singleton_calls.append(url)
        if url != root:
            raise AssertionError("New Mexico child hierarchy used a singleton fetch")
        return root_html

    async def _plural(requested_urls, **_kwargs):
        requested = list(requested_urls)
        plural_calls.append(requested)
        return _aligned_result(requested, payloads)

    monkeypatch.setattr(scraper, "_fetch_page_content_with_archival_fallback", _singleton)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )

    rows = await scraper._scrape_official_nmonesource_tree("New Mexico Statutes")

    assert singleton_calls == [root]
    assert plural_calls == [chapters, sections]
    assert [row.section_number for row in rows] == ["1-1", "2-1"]


@pytest.mark.asyncio
async def test_ohio_full_hierarchy_allows_one_root_then_plural_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = OhioScraper("OH", "Ohio")
    root = f"{scraper.get_base_url()}/ohio-revised-code"
    titles = [f"{root}/title-{number}" for number in (1, 3)]
    chapters = [f"{root}/chapter-{number}01" for number in (1, 3)]
    sections = [f"{root}/section-{number}01.01" for number in (1, 3)]
    root_html = "".join(f'<a href="{url}">Title</a>' for url in titles).encode()
    payloads = {
        **{
            title: f'<html><a href="{chapter}">Chapter</a></html>'.encode()
            for title, chapter in zip(titles, chapters, strict=True)
        },
        **{
            chapter: f'<html><a href="{section}">Section</a></html>'.encode()
            for chapter, section in zip(chapters, sections, strict=True)
        },
        **{
            section: (
                f"<html><h1>Section {index}01.01</h1><main>"
                + ("Official Ohio statutory body text. " * 8)
                + "</main></html>"
            ).encode()
            for index, section in zip((1, 3), sections, strict=True)
        },
    }
    singleton_calls: list[str] = []
    plural_calls: list[list[str]] = []

    async def _singleton(url: str, **_kwargs):
        singleton_calls.append(url)
        if url != root:
            raise AssertionError("Ohio child hierarchy used a singleton fetch")
        return root_html

    async def _plural(requested_urls, **_kwargs):
        requested = list(requested_urls)
        plural_calls.append(requested)
        return _aligned_result(requested, payloads, receipts=True)

    monkeypatch.setattr(scraper, "_fetch_page_content_with_archival_fallback", _singleton)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    monkeypatch.setattr(scraper, "_parse_official_chapter_inline", lambda *_a, **_k: [])

    rows = await scraper._scrape_official_title_chapter_section_tree("Ohio Revised Code")

    assert singleton_calls == [root]
    assert plural_calls == [titles, chapters, sections]
    assert [row.section_number for row in rows] == ["101.01", "301.01"]


@pytest.mark.asyncio
async def test_oklahoma_exact_pdf_frontier_is_one_plural_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = OklahomaScraper("OK", "Oklahoma")
    monkeypatch.setattr(scraper, "OFFICIAL_TITLE_COUNT", 2)
    monkeypatch.setattr(scraper, "OFFICIAL_TITLES", (("1", "One"), ("2", "Two")))
    urls = [f"https://www.oklegislature.gov/ok_statutes/title-{number}.pdf" for number in (1, 2)]
    frontier = {"member_urls": {"1": urls[0], "2": urls[1]}}
    payloads = {url: b"%PDF-1.7\n" + (url.encode() * 8) for url in urls}
    calls: list[tuple[list[str], dict[str, object]]] = []

    async def _plural(requested_urls, **kwargs):
        requested = list(requested_urls)
        calls.append((requested, kwargs))
        return _aligned_result(requested, payloads, receipts=True)

    def _canonical(*, source_url: str, payload: bytes, raw_receipt):
        assert raw_receipt["official_url"] == source_url
        return dict(raw_receipt)

    async def _singleton(*_args, **_kwargs):
        raise AssertionError("Oklahoma exact PDF frontier used a singleton fetch")

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    monkeypatch.setattr(scraper, "_canonical_transport_receipt", _canonical)
    monkeypatch.setattr(scraper, "_fetch_official_bytes_with_receipt", _singleton)

    resolved = await scraper._ensure_complete_title_payloads(frontier)

    assert len(calls) == 1
    assert calls[0][0] == urls
    assert calls[0][1]["headers"] == {
        "User-Agent": "ipfs-datasets-oklahoma-code-scraper/2.0",
    }
    assert calls[0][1]["media_type"] == "application/pdf"
    assert list(resolved) == urls


@pytest.mark.asyncio
async def test_pennsylvania_full_pdf_frontier_is_one_plural_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = PennsylvaniaScraper("PA", "Pennsylvania")
    discovered = [
        ("1", "General Provisions", "https://www.palegis.us/statutes/title-1.pdf"),
        ("2", "Administrative Law", "https://www.palegis.us/statutes/title-2.pdf"),
    ]
    urls = [url for _number, _name, url in discovered]
    payloads = {url: b"%PDF-1.7 retained" for url in urls}
    calls: list[list[str]] = []

    async def _discover(*, limit=None):
        assert limit is None
        return discovered

    async def _plural(requested_urls, **_kwargs):
        requested = list(requested_urls)
        calls.append(requested)
        return _aligned_result(requested, payloads)

    async def _singleton(*_args, **_kwargs):
        raise AssertionError("Pennsylvania exact PDF frontier used a singleton fetch")

    def _split(code_name, title_number, title_name, title_text, source_url):
        return [
            NormalizedStatute(
                state_code="PA",
                state_name="Pennsylvania",
                statute_id=f"PA-{title_number}-1",
                code_name=code_name,
                title_number=title_number,
                section_number="1",
                section_name=title_name,
                full_text=title_text,
                source_url=source_url,
            )
        ]

    monkeypatch.setattr(scraper, "_discover_consolidated_title_pdfs", _discover)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    monkeypatch.setattr(scraper, "_request_pdf_bytes", _singleton)
    monkeypatch.setattr(
        scraper,
        "_extract_pdf_text_preserve_layout",
        lambda **_kwargs: "Official Pennsylvania consolidated statute text. " * 20,
    )
    monkeypatch.setattr(scraper, "_split_title_pdf_into_sections", _split)

    rows = await scraper._scrape_consolidated_title_pdfs("Pennsylvania Code")

    assert calls == [urls]
    assert [row.title_number for row in rows] == ["1", "2"]


@pytest.mark.asyncio
async def test_pennsylvania_full_pdf_catalog_fails_closed_when_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = PennsylvaniaScraper("PA", "Pennsylvania")

    async def _discover(*, limit=None):
        assert limit is None
        return []

    monkeypatch.setattr(scraper, "_discover_consolidated_title_pdfs", _discover)

    with pytest.raises(RuntimeError, match="PDF catalog did not close"):
        await scraper._scrape_consolidated_title_pdfs("Pennsylvania Code")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scraper", "official_method", "error_match"),
    [
        (
            OhioScraper("OH", "Ohio"),
            "_scrape_official_title_chapter_section_tree",
            "official title/chapter hierarchy did not close",
        ),
    ],
)
async def test_repaired_full_hierarchy_wrappers_fail_before_legacy_recovery(
    monkeypatch: pytest.MonkeyPatch,
    scraper: Any,
    official_method: str,
    error_match: str,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        new_mexico_chapter,
        new_mexico_constitution,
        ohio_constitution,
    )

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        new_mexico_constitution,
        "configured_constitution_text_path",
        lambda: None,
    )
    monkeypatch.setattr(
        new_mexico_chapter,
        "configured_chapter_text_path",
        lambda: None,
    )
    monkeypatch.setattr(
        ohio_constitution,
        "configured_constitution_html_path",
        lambda: None,
    )

    async def _empty_official(*_args, **_kwargs):
        return []

    async def _forbid_legacy(*_args, **_kwargs):
        raise AssertionError("strict empty hierarchy reached legacy recovery")

    monkeypatch.setattr(scraper, official_method, _empty_official)
    for method_name in (
        "_generic_scrape",
        "_scrape_direct_sections",
        "_scrape_live_chapter_document_pdfs",
        "_scrape_nmonesource_nav_sections",
        "_scrape_nmonesource_index",
        "_scrape_archived_document_pdfs",
        "_scrape_direct_document_pdfs",
    ):
        if hasattr(scraper, method_name):
            monkeypatch.setattr(scraper, method_name, _forbid_legacy)

    with pytest.raises(RuntimeError, match=error_match):
        await scraper.scrape_code("Code", scraper.get_base_url(), None)
