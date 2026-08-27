"""Strict batching and replay identity tests for New Mexico chapter PDFs."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    NormalizedStatute,
    StateLawPageMultiFetchResult,
    StatuteMetadata,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_mexico import (
    NewMexicoScraper,
)

SEED = "https://nmonesource.com/nmos/nmsa/en/nav_date.do?iframe=true"
PAGE_2 = "https://nmonesource.com/nmos/nmsa/en/nav_date.do?page=2"
PAGE_3 = "https://nmonesource.com/nmos/nmsa/en/nav_date.do?page=3"
DOC_1 = "https://nmonesource.com/nmos/nmsa/en/4351/1/document.do"
DOC_2 = "https://nmonesource.com/nmos/nmsa/en/4359/1/document.do"


def _aligned_result(
    urls: list[str],
    payload_by_url: dict[str, bytes],
    *,
    receipt_url_by_url: dict[str, str] | None = None,
) -> StateLawPageMultiFetchResult:
    payloads = [payload_by_url.get(url, b"") for url in urls]
    return StateLawPageMultiFetchResult(
        urls=list(urls),
        payloads=payloads,
        errors=[None if payload else "missing" for payload in payloads],
        transport_receipts=[
            (
                {
                    "content_sha256": hashlib.sha256(payload).hexdigest(),
                    "official_url": (receipt_url_by_url or {}).get(url, url),
                    "source_transport": "retained_acquisition_replay",
                }
                if payload
                else None
            )
            for url, payload in zip(urls, payloads, strict=True)
        ],
        parser_input_envelopes=[
            SimpleNamespace(body=payload) if payload else None for payload in payloads
        ],
        stats={"requested_pages": len(urls)},
    )


def _nav_pages() -> dict[str, bytes]:
    return {
        SEED: (
            b"<html><body>"
            b"<a href='/nmos/nmsa/en/nav_date.do?page=2'>2</a>"
            b"<a href='/nmos/nmsa/en/nav_date.do?page=3'>3</a>"
            b"<a href='/nmos/nmsa/en/item/4351/index.do'>Chapter 1 - Elections</a>"
            b"<a href='/nmos/nmsa/en/4351/1/document.do'>PDF</a>"
            b"</body></html>"
        ),
        PAGE_3: b"<html><body>Last navigation page.</body></html>",
        PAGE_2: (
            b"<html><body>"
            b"<a href='/nmos/nmsa/en/item/4359/index.do'>"
            b"Chapter 2 - Legislative Branch</a>"
            b"<a href='/nmos/nmsa/en/4359/1/document.do'>PDF</a>"
            b"</body></html>"
        ),
    }


def _chapter_text(section: str, title: str) -> str:
    return f"CHAPTER {section.split('-', 1)[0]}\n{section}. {title}.\n" + (
        "Official enacted New Mexico statutory text. " * 12
    )


@pytest.mark.asyncio
async def test_full_pdf_frontier_uses_two_aligned_plural_waves_without_accept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    scraper = NewMexicoScraper("NM", "New Mexico")
    nav_payloads = _nav_pages()
    pdf_payloads = {DOC_1: b"%PDF-one", DOC_2: b"%PDF-two"}
    plural_calls: list[tuple[list[str], dict[str, Any]]] = []

    async def _seed(url: str, **_kwargs: Any) -> bytes:
        assert url == SEED
        return nav_payloads[SEED]

    async def _plural(urls, **kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        plural_calls.append((requested, dict(kwargs)))
        payloads = nav_payloads if "nav_date.do" in requested[0] else pdf_payloads
        return _aligned_result(requested, payloads)

    def _extract(pdf_bytes: bytes, max_chars=None) -> str:
        del max_chars
        return (
            _chapter_text("1-1-1", "Election Code")
            if pdf_bytes == pdf_payloads[DOC_1]
            else _chapter_text("2-1-1", "Legislative Branch")
        )

    async def _forbid_single_pdf(*_args: Any, **_kwargs: Any) -> bytes:
        raise AssertionError("known New Mexico PDF frontier used a singleton fetch")

    monkeypatch.setattr(scraper, "_fetch_page_content_with_archival_fallback", _seed)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    monkeypatch.setattr(scraper, "_request_bytes", _forbid_single_pdf)
    monkeypatch.setattr(scraper, "_extract_pdf_text_preserve_layout", _extract)

    rows = await scraper._scrape_live_chapter_document_pdfs(
        "New Mexico Statutes",
        None,
    )

    assert [row.section_number for row in rows] == ["1-1-1", "2-1-1"]
    assert [call[0] for call in plural_calls] == [[PAGE_2, PAGE_3], [DOC_1, DOC_2]]
    assert [call[1]["media_type"] for call in plural_calls] == [
        "text/html",
        "application/pdf",
    ]
    assert all(
        call[1]["headers"] == {"User-Agent": "Mozilla/5.0"} for call in plural_calls
    )
    assert all("Accept" not in call[1]["headers"] for call in plural_calls)
    assert all(call[1]["wayback_prefix_inventory"] is True for call in plural_calls)
    assert scraper._new_mexico_pdf_frontier_report["closed"] is True


@pytest.mark.asyncio
async def test_pdf_frontier_preserves_first_seen_dedupe_and_terminal_only_pdf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    scraper = NewMexicoScraper("NM", "New Mexico")
    duplicate_text = (
        _chapter_text("1-1-1", "Election Code")
        + "\n"
        + _chapter_text("1-1-1", "Duplicate Annotation Heading")
    )
    terminal_text = "CHAPTER 22A\nOther Public School Laws\n22A-1-1. Recompiled.\n" + (
        "Recompiled as 22-13-3.3 NMSA 1978. " * 12
    )

    async def _discover(limit=None):
        assert limit is None
        scraper._new_mexico_nav_frontier_urls = [SEED]
        return [("Chapter 1 - Elections", DOC_1), ("Chapter 22A", DOC_2)]

    async def _pdfs(urls, **_kwargs: Any) -> dict[str, bytes]:
        return {url: (b"%PDF-one" if url == DOC_1 else b"%PDF-two") for url in urls}

    def _extract(pdf_bytes: bytes, max_chars=None) -> str:
        del max_chars
        return duplicate_text if pdf_bytes == b"%PDF-one" else terminal_text

    monkeypatch.setattr(scraper, "_discover_live_document_urls", _discover)
    monkeypatch.setattr(scraper, "_fetch_nm_pdf_frontier", _pdfs)
    monkeypatch.setattr(scraper, "_extract_pdf_text_preserve_layout", _extract)

    rows = await scraper._scrape_live_chapter_document_pdfs(
        "New Mexico Statutes",
        None,
    )

    assert [row.section_number for row in rows] == ["1-1-1"]
    assert rows[0].section_name == "Election Code."
    assert scraper._new_mexico_pdf_frontier_report == {
        "closed": True,
        "nav_page_count": 1,
        "nav_urls": [SEED],
        "document_count": 2,
        "document_urls": [DOC_1, DOC_2],
        "fetched_document_count": 2,
        "raw_section_occurrences": 2,
        "duplicate_section_occurrences": 1,
        "normalized_row_count": 1,
        "empty_document_urls": [DOC_2],
        "short_document_urls": [],
    }


@pytest.mark.asyncio
async def test_nm_frontier_rejects_alignment_and_retained_identity_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = NewMexicoScraper("NM", "New Mexico")
    payloads = {DOC_1: b"%PDF-one", DOC_2: b"%PDF-two"}

    async def _misaligned(urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        result = _aligned_result(list(urls), payloads)
        result.urls.reverse()
        return result

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _misaligned,
    )
    with pytest.raises(RuntimeError, match="changed exact URL alignment"):
        await scraper._fetch_nm_pdf_frontier(
            [DOC_1, DOC_2],
            frontier_name="test PDFs",
        )

    async def _incomplete(urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        return _aligned_result(list(urls), {DOC_1: payloads[DOC_1]})

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _incomplete,
    )
    with pytest.raises(RuntimeError, match="frontier is incomplete"):
        await scraper._fetch_nm_pdf_frontier(
            [DOC_1, DOC_2],
            frontier_name="test PDFs",
        )

    scraper._state_law_acquisition_ledger = object()

    async def _wrong_identity(urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        return _aligned_result(
            list(urls),
            payloads,
            receipt_url_by_url={DOC_1: DOC_2},
        )

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _wrong_identity,
    )
    with pytest.raises(RuntimeError, match="changed URL identity"):
        await scraper._fetch_nm_pdf_frontier([DOC_1], frontier_name="test PDFs")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["empty_catalog", "invalid_pdf", "unparsed_pdf"])
async def test_full_pdf_frontier_fails_closed_on_empty_or_incomplete_source(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    scraper = NewMexicoScraper("NM", "New Mexico")

    async def _discover(limit=None):
        assert limit is None
        return [] if failure == "empty_catalog" else [("Chapter 1", DOC_1)]

    async def _pdfs(urls, **_kwargs: Any) -> dict[str, bytes]:
        return {} if failure == "invalid_pdf" else {url: b"%PDF-one" for url in urls}

    monkeypatch.setattr(scraper, "_discover_live_document_urls", _discover)
    monkeypatch.setattr(scraper, "_fetch_nm_pdf_frontier", _pdfs)
    monkeypatch.setattr(
        scraper,
        "_extract_pdf_text_preserve_layout",
        lambda pdf_bytes, max_chars=None: "Malformed but long PDF text. " * 20,
    )

    expected = {
        "empty_catalog": "document frontier is empty",
        "invalid_pdf": "produced no normalized statutes",
        "unparsed_pdf": "failed parser closure",
    }[failure]
    with pytest.raises(RuntimeError, match=expected):
        await scraper._scrape_live_chapter_document_pdfs(
            "New Mexico Statutes",
            None,
        )


@pytest.mark.asyncio
async def test_full_scrape_reaches_pdf_primary_after_empty_html_and_stops_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        new_mexico_chapter,
        new_mexico_constitution,
    )

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        new_mexico_chapter, "configured_chapter_text_path", lambda: None
    )
    monkeypatch.setattr(
        new_mexico_constitution,
        "configured_constitution_text_path",
        lambda: None,
    )
    scraper = NewMexicoScraper("NM", "New Mexico")
    observed: dict[str, Any] = {}

    async def _empty_html(*_args: Any, **_kwargs: Any):
        return []

    async def _pdf_primary(code_name: str, max_statutes=None):
        observed["max_statutes"] = max_statutes
        return [
            NormalizedStatute(
                state_code="NM",
                state_name="New Mexico",
                statute_id=f"{code_name} § 1-1-1",
                code_name=code_name,
                section_number="1-1-1",
                section_name="Election Code",
                full_text="Official enacted New Mexico statutory text. " * 12,
                source_url=DOC_1,
                official_cite="N.M. Stat. Ann. § 1-1-1",
                metadata=StatuteMetadata(),
            )
        ]

    async def _forbid_legacy(*_args: Any, **_kwargs: Any):
        raise AssertionError("successful official PDF primary reached legacy recovery")

    monkeypatch.setattr(scraper, "_scrape_official_nmonesource_tree", _empty_html)
    monkeypatch.setattr(scraper, "_scrape_live_chapter_document_pdfs", _pdf_primary)
    for name in (
        "_scrape_nmonesource_nav_sections",
        "_scrape_nmonesource_index",
        "_scrape_archived_document_pdfs",
        "_generic_scrape",
    ):
        monkeypatch.setattr(scraper, name, _forbid_legacy)

    rows = await scraper.scrape_code(
        "New Mexico Statutes",
        scraper.OFFICIAL_ENTRY_URL,
        None,
    )

    assert [row.section_number for row in rows] == ["1-1-1"]
    assert observed["max_statutes"] is None
