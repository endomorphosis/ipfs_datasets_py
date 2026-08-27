from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
)
from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import (
    _write_state_jsonld_files,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.alaska import (
    AlaskaScraper,
)


def _section(number: str) -> str:
    return (
        f'<b><a name="{number}"> </a>Sec. {number}. Test provision.</b>'
        + (f"Exact official Alaska text for {number}. " * 6)
        + "<br><br>"
    )


def test_alaska_jsonld_retains_ajax_input_digest_for_strict_closure(
    tmp_path: Path,
) -> None:
    scraper = AlaskaScraper("AK", "Alaska")
    endpoint = (
        "https://www.akleg.gov/basis/statutes.asp"
        "?media=print&type=fetch&secStart=1"
    )
    parser_input = _section("01.05.006").encode("cp1252")
    digest = hashlib.sha256(parser_input).hexdigest()
    receipt = {
        "content_sha256": digest,
        "official_url": endpoint,
        "source_transport": "direct",
    }
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="AK",
        parser_name="AlaskaScraper",
    )
    ledger.retain_parser_input(
        official_url=endpoint,
        body=parser_input,
        transport_receipt=receipt,
        media_type="text/html",
    )
    scraper._state_law_acquisition_ledger = ledger
    scraper._last_page_fetch_transport_evidence = receipt

    rows = scraper._bind_statute_chunk_provenance(
        scraper._parse_statute_chunk(
            code_name="Alaska Statutes",
            html=parser_input.decode("cp1252"),
        )
    )
    assert len(rows) == 1
    enriched = scraper._enrich_statute_structure(rows[0])

    jsonld_dir = tmp_path / "jsonld"
    jsonld_dir.mkdir()
    written = _write_state_jsonld_files(
        [
            {
                "state_code": "AK",
                "state_name": "Alaska",
                "statutes": [enriched.to_dict()],
            }
        ],
        jsonld_dir,
    )

    assert len(written) == 1
    canonical_path = Path(written[0])
    payload = json.loads(canonical_path.read_text(encoding="utf-8"))
    assert payload["sourceUrl"] == f"{scraper.OFFICIAL_ENTRY_URL}#01.05.006"
    assert payload["provenance"] == {
        "content_sha256": digest,
        "transport_receipt": receipt,
    }

    coverage = ledger.audit_canonical_jsonld_coverage(canonical_path)
    assert coverage["complete"] is True
    assert coverage["covered_by_content_digest"] == 1
    assert coverage["covered_by_official_url"] == 0
    assert coverage["uncovered_unit_count"] == 0


def test_alaska_jsonld_provenance_mismatch_fails_closed() -> None:
    scraper = AlaskaScraper("AK", "Alaska")
    scraper._state_law_acquisition_ledger = object()
    [statute] = scraper._parse_statute_chunk(
        code_name="Alaska Statutes",
        html=_section("01.05.006"),
    )
    statute.structured_data.update(
        {
            "content_sha256": "a" * 64,
            "transport_receipt": {
                "content_sha256": "b" * 64,
                "official_url": scraper.OFFICIAL_ENTRY_URL,
                "source_transport": "direct",
            },
        }
    )

    with pytest.raises(RuntimeError, match="canonical retained parser-input provenance"):
        scraper._enrich_statute_structure(statute)


@pytest.mark.anyio
async def test_alaska_ajax_rows_bind_the_exact_chunk_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    digest = "a" * 64
    receipt = {
        "content_sha256": digest,
        "official_url": (
            "https://www.akleg.gov/basis/statutes.asp"
            "?media=print&type=fetch&secStart=1"
        ),
        "source_transport": "direct",
    }

    async def _fetch(self, sec_start: str, timeout_seconds: int = 8):
        assert sec_start == "1"
        return _section("01.05.006"), "01.05.006"

    monkeypatch.setattr(AlaskaScraper, "_fetch_statute_chunk", _fetch)
    monkeypatch.setattr(
        AlaskaScraper,
        "_last_parser_input_row_provenance",
        lambda self: {
            "content_sha256": digest,
            "transport_receipt": receipt,
        },
    )
    scraper = AlaskaScraper("AK", "Alaska")
    scraper._state_law_acquisition_ledger = object()

    rows = await scraper.scrape_code(
        "Alaska Statutes",
        scraper.OFFICIAL_ENTRY_URL,
        max_statutes=1,
    )

    assert len(rows) == 1
    assert rows[0].structured_data["content_sha256"] == digest
    assert rows[0].structured_data["transport_receipt"] == receipt


@pytest.mark.anyio
async def test_alaska_ajax_rows_fail_closed_without_attached_input_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fetch(self, sec_start: str, timeout_seconds: int = 8):
        return _section("01.05.006"), "01.05.006"

    monkeypatch.setattr(AlaskaScraper, "_fetch_statute_chunk", _fetch)
    monkeypatch.setattr(
        AlaskaScraper,
        "_last_parser_input_row_provenance",
        lambda self: {},
    )
    scraper = AlaskaScraper("AK", "Alaska")
    scraper._state_law_acquisition_ledger = object()

    with pytest.raises(RuntimeError, match="exact retained parser-input provenance"):
        await scraper.scrape_code(
            "Alaska Statutes",
            scraper.OFFICIAL_ENTRY_URL,
            max_statutes=1,
        )


@pytest.mark.anyio
async def test_alaska_terminal_200_empty_skips_archive_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = AlaskaScraper("AK", "Alaska")
    calls: list[bool] = []

    async def _fetch(url: str, **kwargs):
        calls.append(bool(kwargs["allow_archival_fallback"]))
        return b""

    async def _probe(url: str, **kwargs):
        return {
            "body": b"",
            "content_sha256": hashlib.sha256(b"").hexdigest(),
            "final_url": url,
            "observed_at": "2026-08-24T17:25:58+00:00",
            "requested_url": url,
            "status_code": 200,
        }

    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _fetch)
    monkeypatch.setattr(scraper, "_fetch_fresh_official_response_receipt", _probe)

    html, cursor = await scraper._fetch_statute_chunk("47.90.070")

    assert (html, cursor) == ("", "")
    assert calls == [False]
    assert scraper._last_alaska_terminal_probe == {
        "closed": True,
        "content_sha256": hashlib.sha256(b"").hexdigest(),
        "empty": True,
        "final_url": (
            "https://www.akleg.gov/basis/statutes.asp"
            "?media=print&type=fetch&secStart=47.90.070"
        ),
        "observed_at": "2026-08-24T17:25:58+00:00",
        "requested_url": (
            "https://www.akleg.gov/basis/statutes.asp"
            "?media=print&type=fetch&secStart=47.90.070"
        ),
        "sec_start": "47.90.070",
        "status_code": 200,
    }


@pytest.mark.anyio
async def test_alaska_terminal_transport_failure_keeps_archive_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = AlaskaScraper("AK", "Alaska")
    calls: list[bool] = []
    archived = _section("47.90.080").encode("cp1252")

    async def _fetch(url: str, **kwargs):
        archival = bool(kwargs["allow_archival_fallback"])
        calls.append(archival)
        return archived if archival else b""

    async def _probe(url: str, **kwargs):
        return {
            "body": b"",
            "content_sha256": hashlib.sha256(b"").hexdigest(),
            "final_url": url,
            "observed_at": "2026-08-24T17:25:58+00:00",
            "requested_url": url,
            "status_code": 503,
        }

    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _fetch)
    monkeypatch.setattr(scraper, "_fetch_fresh_official_response_receipt", _probe)

    html, cursor = await scraper._fetch_statute_chunk("47.90.070")

    assert cursor == "47.90.080"
    assert "47.90.080" in html
    assert calls == [False, True]
    assert scraper._last_alaska_terminal_probe == {}


@pytest.mark.anyio
async def test_alaska_strict_full_traversal_accepts_only_exact_terminal_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = AlaskaScraper("AK", "Alaska")
    scraper._state_law_acquisition_ledger = object()
    page = "".join(
        _section(f"{int(title):02d}.01.001")
        for title, _name in scraper.OFFICIAL_TITLES
    )
    terminal_url = (
        "https://www.akleg.gov/basis/statutes.asp"
        "?media=print&type=fetch&secStart=47.01.001"
    )

    async def _fetch(self, sec_start: str, timeout_seconds: int = 8):
        if sec_start == "1":
            self._last_alaska_terminal_probe = {}
            return page, "47.01.001"
        assert sec_start == "47.01.001"
        self._last_alaska_terminal_probe = {
            "closed": True,
            "content_sha256": hashlib.sha256(b"").hexdigest(),
            "empty": True,
            "final_url": terminal_url,
            "observed_at": "2026-08-24T17:25:58+00:00",
            "requested_url": terminal_url,
            "sec_start": sec_start,
            "status_code": 200,
        }
        return "", ""

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(AlaskaScraper, "_fetch_statute_chunk", _fetch)
    monkeypatch.setattr(
        AlaskaScraper,
        "_last_parser_input_row_provenance",
        lambda self: {
            "content_sha256": "a" * 64,
            "transport_receipt": {
                "content_sha256": "a" * 64,
                "official_url": scraper.OFFICIAL_ENTRY_URL,
                "source_transport": "direct",
            },
        },
    )

    rows = await scraper.scrape_code(
        "Alaska Statutes",
        scraper.OFFICIAL_ENTRY_URL,
    )

    assert len(rows) == len(scraper.OFFICIAL_TITLES)


@pytest.mark.anyio
async def test_alaska_strict_full_traversal_rejects_unproven_empty_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = AlaskaScraper("AK", "Alaska")
    scraper._state_law_acquisition_ledger = object()
    page = "".join(
        _section(f"{int(title):02d}.01.001")
        for title, _name in scraper.OFFICIAL_TITLES
    )

    async def _fetch(self, sec_start: str, timeout_seconds: int = 8):
        if sec_start == "1":
            return page, "47.01.001"
        self._last_alaska_terminal_probe = {}
        return "", ""

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(AlaskaScraper, "_fetch_statute_chunk", _fetch)
    monkeypatch.setattr(
        AlaskaScraper,
        "_last_parser_input_row_provenance",
        lambda self: {
            "content_sha256": "a" * 64,
            "transport_receipt": {
                "content_sha256": "a" * 64,
                "official_url": scraper.OFFICIAL_ENTRY_URL,
                "source_transport": "direct",
            },
        },
    )

    with pytest.raises(RuntimeError, match="exact terminal HTTP 200 empty response"):
        await scraper.scrape_code(
            "Alaska Statutes",
            scraper.OFFICIAL_ENTRY_URL,
        )
