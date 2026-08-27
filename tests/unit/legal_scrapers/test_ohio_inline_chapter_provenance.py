"""Exact retained-byte provenance for Ohio's inline chapter fan-out."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.ohio import OhioScraper

ROOT_URL = "https://codes.ohio.gov/ohio-revised-code"
TITLE_URL = "https://codes.ohio.gov/ohio-revised-code/title-29"
CHAPTER_URL = "https://codes.ohio.gov/ohio-revised-code/chapter-2903"
CHAPTER_HTML = b"""<html><body>
<div>Chapter 2903 | Homicide and assault</div>
<div>Section 2903.01 | Aggravated murder.</div>
<div>No person shall purposely cause the death of another person under this section.</div>
<div>Section 2903.04 | Involuntary manslaughter.</div>
<div>No person shall cause another person's death as the proximate result of a felony.</div>
</body></html>"""


def _receipt(*, url: str = CHAPTER_URL, digest: str | None = None) -> dict[str, str]:
    return {
        "content_sha256": digest or hashlib.sha256(CHAPTER_HTML).hexdigest(),
        "official_url": url,
        "source_transport": "direct",
    }


def _install_tree_fetch(
    monkeypatch: pytest.MonkeyPatch,
    scraper: OhioScraper,
    *,
    chapter_receipt: Mapping[str, Any],
) -> None:
    async def _fetch(url: str, timeout_seconds: int = 20) -> bytes:
        del timeout_seconds
        if url == ROOT_URL:
            return f'<a href="{TITLE_URL}">Title 29</a>'.encode()
        if url == TITLE_URL:
            return f'<a href="{CHAPTER_URL}">Chapter 2903</a>'.encode()
        if url == CHAPTER_URL:
            scraper._last_page_fetch_transport_evidence = dict(chapter_receipt)
            return CHAPTER_HTML
        return b""

    monkeypatch.setattr(
        scraper,
        "_fetch_page_content_with_archival_fallback",
        _fetch,
    )


@pytest.mark.anyio
async def test_inline_rows_share_exact_retained_chapter_provenance_and_coverage(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = OhioScraper("OH", "Ohio")
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="OH",
        parser_name="OhioScraper",
    )
    scraper.attach_state_law_acquisition_ledger(ledger)
    receipt = _receipt()
    digest = receipt["content_sha256"]
    ledger.retain_parser_input(
        official_url=CHAPTER_URL,
        body=CHAPTER_HTML,
        transport_receipt=receipt,
        media_type="text/html",
    )
    _install_tree_fetch(monkeypatch, scraper, chapter_receipt=receipt)

    rows = await scraper._scrape_official_title_chapter_section_tree(
        "Ohio Revised Code",
        max_statutes=8,
    )

    assert [row.section_number for row in rows] == ["2903.01", "2903.04"]
    assert all(row.source_url != CHAPTER_URL for row in rows)
    assert all(row.structured_data["content_sha256"] == digest for row in rows)
    assert all(row.structured_data["transport_receipt"] == receipt for row in rows)
    coverage = ledger.audit_parser_output_coverage(
        [scraper._enrich_statute_structure(row).to_dict() for row in rows]
    )
    assert coverage["complete"] is True
    assert coverage["covered_by_content_digest"] == 2
    assert coverage["covered_by_official_url"] == 0
    assert coverage["uncovered_unit_count"] == 0


@pytest.mark.anyio
async def test_inline_rows_fail_closed_without_retained_chapter_provenance(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = OhioScraper("OH", "Ohio")
    scraper.attach_state_law_acquisition_ledger(
        StateLawMultiFetchAcquisitionLedger(
            tmp_path / "evidence",
            jurisdiction="OH",
            parser_name="OhioScraper",
        )
    )
    _install_tree_fetch(monkeypatch, scraper, chapter_receipt={})

    with pytest.raises(RuntimeError, match="exact retained parser-input provenance"):
        await scraper._scrape_official_title_chapter_section_tree(
            "Ohio Revised Code",
            max_statutes=8,
        )


@pytest.mark.anyio
async def test_inline_rows_fail_closed_on_chapter_receipt_url_drift(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = OhioScraper("OH", "Ohio")
    scraper.attach_state_law_acquisition_ledger(
        StateLawMultiFetchAcquisitionLedger(
            tmp_path / "evidence",
            jurisdiction="OH",
            parser_name="OhioScraper",
        )
    )
    _install_tree_fetch(
        monkeypatch,
        scraper,
        chapter_receipt=_receipt(url=TITLE_URL),
    )

    with pytest.raises(RuntimeError, match="exact retained parser-input provenance"):
        await scraper._scrape_official_title_chapter_section_tree(
            "Ohio Revised Code",
            max_statutes=8,
        )


@pytest.mark.anyio
@pytest.mark.parametrize("conflict_field", ["content_sha256", "transport_receipt"])
async def test_inline_rows_fail_closed_on_conflicting_row_provenance(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    conflict_field: str,
) -> None:
    scraper = OhioScraper("OH", "Ohio")
    scraper.attach_state_law_acquisition_ledger(
        StateLawMultiFetchAcquisitionLedger(
            tmp_path / "evidence",
            jurisdiction="OH",
            parser_name="OhioScraper",
        )
    )
    receipt = _receipt()
    _install_tree_fetch(monkeypatch, scraper, chapter_receipt=receipt)
    original_parse = scraper._parse_official_chapter_inline

    def _parse(*args: Any, **kwargs: Any):
        rows = original_parse(*args, **kwargs)
        rows[0].structured_data[conflict_field] = (
            "0" * 64
            if conflict_field == "content_sha256"
            else _receipt(url=TITLE_URL)
        )
        return rows

    monkeypatch.setattr(scraper, "_parse_official_chapter_inline", _parse)

    with pytest.raises(RuntimeError, match="conflicting retained parser-input provenance"):
        await scraper._scrape_official_title_chapter_section_tree(
            "Ohio Revised Code",
            max_statutes=8,
        )


@pytest.mark.anyio
async def test_nonledger_mocked_tree_remains_compatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = OhioScraper("OH", "Ohio")
    _install_tree_fetch(monkeypatch, scraper, chapter_receipt={})

    rows = await scraper._scrape_official_title_chapter_section_tree(
        "Ohio Revised Code",
        max_statutes=8,
    )

    assert [row.section_number for row in rows] == ["2903.01", "2903.04"]
    assert all("content_sha256" not in row.structured_data for row in rows)
