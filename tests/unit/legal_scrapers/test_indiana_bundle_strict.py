"""Strict prospective provenance and exact-frontier tests for Indiana's ZIP."""

from __future__ import annotations

import asyncio
import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionError,
    StateLawMultiFetchAcquisitionLedger,
    build_canonical_state_law_output_projection,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.indiana import (
    IndianaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.indiana_bulk import (
    IndianaBulkProvenanceError,
    load_indiana_bulk_transport_receipt,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    NormalizedStatute,
)

TITLE_HTML = """
<div class="title" id="1"><span id="shortdescription">General Provisions</span></div>
<div class="section" id="1-1-1-1">
  <span id="shortdescription">Operation of recodified law</span>
  <p>Sec. 1. A law repealed and replaced by this code remains continuous.</p>
</div>
<div class="section" id="1-1-1-2">
  <span id="shortdescription">Concise rule</span>
  <p>It applies.</p>
</div>
<div class="section" id="1-1-1-3">
  <span id="shortdescription">Repealed</span>
  <p>Repealed.</p>
</div>
"""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _write_bundle(tmp_path: Path, *, year: int = 2026) -> Path:
    archive = tmp_path / f"{year}-Indiana-Code-html.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(
            f"{year}-Indiana-Code-html/{year}_Indiana_Code_HTML/1.html",
            TITLE_HTML,
        )
        bundle.writestr("README.txt", "Official Indiana Code HTML bundle")
    return archive


def _write_sidecar(archive: Path, *, year: int = 2026) -> Path:
    sidecar = Path(f"{archive}.receipt.json")
    size = archive.stat().st_size
    sidecar.write_text(
        json.dumps(
            {
                "schema_version": "state-laws-large-file-transport-receipt-v1",
                "official_url": (
                    f"https://iga.in.gov/ic/{year}/"
                    f"{year}-Indiana-Code-html.zip"
                ),
                "source_transport": "direct",
                "content_sha256": _sha256_file(archive),
                "byte_size": size,
                "response_status": 200,
                "media_type": "application/zip",
                "retrieved_at": "2026-08-24T12:34:56Z",
                "response_headers": {
                    "content-length": str(size),
                    "content-type": "application/zip",
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return sidecar


def _strict_scraper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, StateLawMultiFetchAcquisitionLedger, IndianaScraper]:
    archive = _write_bundle(tmp_path)
    sidecar = _write_sidecar(archive)
    monkeypatch.setenv("INDIANA_BULK_ZIP", str(archive))
    monkeypatch.setenv("INDIANA_BULK_ZIP_RECEIPT", str(sidecar))
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="IN",
        parser_name="IndianaScraper",
    )
    scraper = IndianaScraper("IN", "Indiana")
    scraper.attach_state_law_acquisition_ledger(ledger)
    return archive, ledger, scraper


def test_sidecar_binds_official_url_size_status_media_and_time(
    tmp_path: Path,
) -> None:
    archive = _write_bundle(tmp_path)
    sidecar = _write_sidecar(archive)

    receipt = load_indiana_bulk_transport_receipt(
        archive,
        receipt_path=sidecar,
        expected_year=2026,
    )

    assert receipt["official_url"].endswith("/2026-Indiana-Code-html.zip")
    assert receipt["byte_size"] == archive.stat().st_size
    assert receipt["content_sha256"] == _sha256_file(archive)
    assert receipt["response_status"] == 200
    assert receipt["media_type"] == "application/zip"
    assert receipt["retrieved_at"] == "2026-08-24T12:34:56Z"
    assert receipt["code_year"] == "2026"


def test_originless_local_bundle_is_rejected_in_strict_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _write_bundle(tmp_path)
    monkeypatch.setenv("INDIANA_BULK_ZIP", str(archive))
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="IN",
        parser_name="IndianaScraper",
    )
    scraper = IndianaScraper("IN", "Indiana")
    scraper.attach_state_law_acquisition_ledger(ledger)

    with pytest.raises(IndianaBulkProvenanceError, match="receipt is missing"):
        scraper._scrape_official_bulk_zip(
            code_name="Indiana Code",
            max_statutes=None,
        )
    assert ledger.entries == ()


def test_originless_default_cache_is_not_reused_by_strict_download_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    archive = _write_bundle(cache_dir)
    cache_path = cache_dir / "2026-indiana-code-html.zip"
    archive.rename(cache_path)
    monkeypatch.setenv("INDIANA_CODE_ZIP_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("INDIANA_CODE_YEAR", "2026")
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="IN",
        parser_name="IndianaScraper",
    )
    scraper = IndianaScraper("IN", "Indiana")
    scraper.attach_state_law_acquisition_ledger(ledger)
    attempted: list[str] = []

    async def _no_network(url: str, **_kwargs) -> bytes:
        attempted.append(url)
        return b""

    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _no_network)

    assert asyncio.run(scraper._download_indiana_code_bundle()) is None
    assert attempted == [
        "https://iga.in.gov/ic/2026/2026-Indiana-Code-html.zip",
        "https://iga.in.gov/ic/2026/2026-Indiana-Code.zip",
    ]
    assert ledger.entries == ()


def test_live_html_zip_rows_bypass_fallback_citation_shape_filter() -> None:
    scraper = IndianaScraper("IN", "Indiana")
    row = NormalizedStatute(
        state_code="IN",
        state_name="Indiana",
        statute_id="Indiana Code § 1-1-1.1-1",
        code_name="Indiana Code",
        section_number="1-1-1.1-1",
        section_name="Concise official provision",
        full_text="It applies.",
        source_url=(
            "https://iga.in.gov/legislative/laws/2026/ic/titles/1#1-1-1.1-1"
        ),
        structured_data={"source_kind": "official_indiana_code_html_zip"},
    )

    assert scraper._is_substantive_indiana_record(row) is True


def test_changed_bundle_size_fails_sidecar_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _write_bundle(tmp_path)
    sidecar = _write_sidecar(archive)
    with archive.open("ab") as handle:
        handle.write(b"tamper")
    # Preserve the old byte size in the sidecar only long enough to show that
    # structural preflight fails before parser admission.
    monkeypatch.setenv("INDIANA_BULK_ZIP", str(archive))
    monkeypatch.setenv("INDIANA_BULK_ZIP_RECEIPT", str(sidecar))
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="IN",
        parser_name="IndianaScraper",
    )
    scraper = IndianaScraper("IN", "Indiana")
    scraper.attach_state_law_acquisition_ledger(ledger)

    with pytest.raises(IndianaBulkProvenanceError, match="byte_size"):
        scraper._scrape_official_bulk_zip(
            code_name="Indiana Code",
            max_statutes=None,
        )
    assert ledger.entries == ()


def test_same_size_tamper_fails_streaming_ledger_fixity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _write_bundle(tmp_path)
    sidecar = _write_sidecar(archive)
    with archive.open("r+b") as handle:
        handle.seek(80)
        original = handle.read(1)
        handle.seek(80)
        handle.write(bytes([original[0] ^ 1]))
    monkeypatch.setenv("INDIANA_BULK_ZIP", str(archive))
    monkeypatch.setenv("INDIANA_BULK_ZIP_RECEIPT", str(sidecar))
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="IN",
        parser_name="IndianaScraper",
    )
    scraper = IndianaScraper("IN", "Indiana")
    scraper.attach_state_law_acquisition_ledger(ledger)

    with pytest.raises(
        StateLawMultiFetchAcquisitionError,
        match="verified origin receipt",
    ):
        scraper._scrape_official_bulk_zip(
            code_name="Indiana Code",
            max_statutes=None,
        )
    assert ledger.entries == ()


def test_strict_bundle_retention_is_file_backed_and_status_is_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive, ledger, scraper = _strict_scraper(tmp_path, monkeypatch)

    def _read_bytes_must_not_run(_self: Path) -> bytes:
        raise AssertionError("large Indiana ZIP retention must stay streaming")

    monkeypatch.setattr(Path, "read_bytes", _read_bytes_must_not_run)
    rows = scraper._scrape_official_bulk_zip(
        code_name="Indiana Code",
        max_statutes=None,
    )

    assert [row.section_number for row in rows] == ["1-1-1-1", "1-1-1-2"]
    assert "repealed and replaced" in rows[0].full_text
    assert rows[1].full_text == "It applies."
    assert len(ledger.entries) == 1
    retained = ledger.entries[0]
    assert retained.envelope.body is None
    assert retained.body_path != archive
    assert rows[0].structured_data["content_sha256"] == _sha256_file(
        retained.body_path
    )
    inventory = scraper._load_indiana_first_bulk_inventory()
    assert inventory["disposition"] == {
        "discovered": 3,
        "duplicates": 0,
        "excluded": 1,
        "failed_final": 0,
        "fetched": 2,
        "quarantined": 0,
    }
    assert inventory["frontier"]["closed"] is True


def test_exact_inventory_replay_and_output_parity_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _archive, ledger, scraper = _strict_scraper(tmp_path, monkeypatch)
    rows = scraper._scrape_official_bulk_zip(
        code_name="Indiana Code",
        max_statutes=None,
    )
    rows = [scraper._enrich_statute_structure(row) for row in rows]
    projection = build_canonical_state_law_output_projection(
        rows,
        jurisdiction="IN",
    )

    original_read_bytes = Path.read_bytes

    def _read_bytes_must_not_run(_self: Path) -> bytes:
        raise AssertionError("large Indiana ZIP replay must stay streaming")

    monkeypatch.setattr(Path, "read_bytes", _read_bytes_must_not_run)
    closure_path = asyncio.run(
        scraper.produce_state_law_frontier_closure(
            canonical_output_projection=projection,
        )
    )
    closure = json.loads(closure_path.read_text(encoding="utf-8"))
    assert closure["official_source_url"] == (
        "https://iga.in.gov/ic/2026/2026-Indiana-Code-html.zip"
    )
    assert closure["acquisition_path_ids"] == ["in-iga-code"]
    assert closure["completion_receipt"]["disposition"] == {
        "discovered": 3,
        "duplicates": 0,
        "excluded": 1,
        "failed_final": 0,
        "fetched": 2,
        "quarantined": 0,
    }
    assert closure["completion_receipt"]["frontier"]["closed"] is True
    assert closure["replayed_frontier"] == closure["completion_receipt"][
        "frontier"
    ]
    assert ledger.verify_retained_frontier_closure_projection(
        projection,
        closure_input_path=closure_path,
    )[
        "canonical_row_count"
    ] == 2
    monkeypatch.setattr(Path, "read_bytes", original_read_bytes)
    jsonld_path = tmp_path / "STATE-IN.jsonld"
    jsonld_path.write_text(
        "".join(
            json.dumps(row.structured_data["jsonld"], sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    closed = ledger.close_from_projection_file(
        closure_path,
        canonical_jsonld_path=jsonld_path,
    )
    assert closed.byte_verification.ok is True
    assert closed.frontier_verification.ok is True
    assert closed.normalized_source_receipt.admission_eligible is True


def test_missing_final_section_identity_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _archive, ledger, scraper = _strict_scraper(tmp_path, monkeypatch)
    rows = scraper._scrape_official_bulk_zip(
        code_name="Indiana Code",
        max_statutes=None,
    )
    rows = [scraper._enrich_statute_structure(row) for row in rows]
    incomplete = build_canonical_state_law_output_projection(
        rows[:1],
        jurisdiction="IN",
    )

    with pytest.raises(RuntimeError, match="do not exactly match admitted"):
        asyncio.run(
            scraper.produce_state_law_frontier_closure(
                canonical_output_projection=incomplete,
            )
        )
    assert not ledger.closure_input_path.exists()


def test_mutated_retained_bundle_fails_before_reinventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _archive, ledger, scraper = _strict_scraper(tmp_path, monkeypatch)
    rows = scraper._scrape_official_bulk_zip(
        code_name="Indiana Code",
        max_statutes=None,
    )
    rows = [scraper._enrich_statute_structure(row) for row in rows]
    projection = build_canonical_state_law_output_projection(
        rows,
        jurisdiction="IN",
    )
    with ledger.entries[0].body_path.open("ab") as handle:
        handle.write(b"tamper")

    with pytest.raises(
        StateLawMultiFetchAcquisitionError,
        match="fixity replay",
    ):
        asyncio.run(
            scraper.produce_state_law_frontier_closure(
                canonical_output_projection=projection,
            )
        )
