"""Tests for the fail-closed existing-receipt reuse bridge."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data import (
    open_us_law_acquisition_coordinator,
    state_laws_legacy_v2_adapter,
    state_laws_source_receipt_reuse,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_completeness import (
    closed_jurisdiction_receipt,
)
from ipfs_datasets_py.processors.legal_data.state_laws_source_receipt_reuse import (
    StateLawsSourceReceiptReuseError,
    qualify_existing_source_receipt,
)

RELEASE_POINT = hashlib.sha256(b"verified-state-receipt-reuse").hexdigest()
OFFICIAL_URL = "https://docs.legis.wisconsin.gov/statutes/statutes/1"


def _canonical_body(rows: int = 1) -> bytes:
    return b"".join(
        (
            json.dumps(
                {
                    "@id": f"urn:state:wi:statute:1.{index:02d}",
                    "@type": "Legislation",
                    "sectionNumber": f"1.{index:02d}",
                    "sourceUrl": (
                        "https://docs.legis.wisconsin.gov/document/statutes/"
                        f"1.{index:02d}"
                    ),
                    "stateCode": "WI",
                    "text": f"A licensee shall comply with provision {index}.",
                },
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        for index in range(1, rows + 1)
    )


def _receipt(
    body: bytes,
    request: bytes,
    response: bytes,
    *,
    rows: int = 1,
) -> dict[str, object]:
    receipt = closed_jurisdiction_receipt(
        "WI",
        discovered=rows,
        fetched=rows,
        excluded=0,
        quarantined=0,
        failed_final=0,
        source_domain="docs.legis.wisconsin.gov",
        canonical_keys=[f"wi:1.{index:02d}" for index in range(1, rows + 1)],
        derived_keys=[f"wi:1.{index:02d}" for index in range(1, rows + 1)],
    )
    request_digest = hashlib.sha256(request).hexdigest()
    response_digest = hashlib.sha256(response).hexdigest()
    body_digest = hashlib.sha256(body).hexdigest()
    receipt["hashes"] = {
        "admitted_body_sha256": body_digest,
        "request_sha256": request_digest,
        "response_sha256": response_digest,
    }
    receipt["replay"].update(
        {
            "admitted_body_sha256": body_digest,
            "first_frontier_digest": receipt["frontier"][
                "frontier_digest_sha256"
            ],
            "request_sha256": request_digest,
            "response_sha256": response_digest,
            "second_frontier_digest": receipt["frontier"][
                "frontier_digest_sha256"
            ],
        }
    )
    receipt.update(
        {
            "acquisition_path_ids": ["wi-docs-statutes"],
            "adapter_input_sha256": body_digest,
            "canonical_row_count": rows,
            "content_hashes": [body_digest],
            "observation_time": "2026-08-24T00:00:00Z",
            "official_source_url": OFFICIAL_URL,
            "receipt_id": "scrape-wi-retained-live",
            "release_point": RELEASE_POINT,
            "row_count": rows,
            "source_checksum": body_digest,
            "source_software_version": "state-scraper/verified",
            "start_urls": [OFFICIAL_URL],
            "verification_result": "verified",
        }
    )
    return receipt


def test_reuses_shared_acquisition_and_canonical_normalization_gates(
    tmp_path: Path,
) -> None:
    body = _canonical_body()
    request = b"GET /statutes/statutes/1 HTTP/1.1\nhost: docs.legis.wisconsin.gov\n"
    response = b"HTTP/1.1 200 OK\ncontent-type: application/json\n\n" + body
    source = tmp_path / "STATE-WI.jsonld"
    source.write_bytes(body)

    normalized = qualify_existing_source_receipt(
        _receipt(body, request, response),
        input_path=source,
        jurisdiction="WI",
        release_point=RELEASE_POINT,
        request_bytes=request,
        response_bytes=response,
        body_bytes=body,
        source_kind="retained_live_evidence",
        source_label="evidence/WI/receipt.json",
    )

    assert normalized.admission_eligible is True
    gate = normalized.record.payload["shared_acquisition_reuse_gate"]
    assert gate["accepted"] is True
    assert gate["canonical_artifact_sha256"] == hashlib.sha256(body).hexdigest()
    assert gate["canonical_row_count"] == 1
    assert gate["raw_artifacts_checked"] == ["request", "response", "body"]
    assert gate["byte_verification"]["ok"] is True
    assert gate["frontier_verification"]["ok"] is True

    # Architecture guard: the bridge imports existing implementations instead
    # of copying either receipt gate.
    assert (
        state_laws_source_receipt_reuse.evaluate_prior_receipt
        is open_us_law_acquisition_coordinator.evaluate_prior_receipt
    )
    assert (
        state_laws_source_receipt_reuse.normalize_source_receipt
        is state_laws_legacy_v2_adapter.normalize_source_receipt
    )


def test_inventory_receipt_cannot_cover_different_canonical_body(
    tmp_path: Path,
) -> None:
    inventory_body = b'{"titles":["1","2"]}\n'
    canonical_body = _canonical_body()
    request = b"GET /titles HTTP/1.1\nhost: docs.legis.wisconsin.gov\n"
    response = b"HTTP/1.1 200 OK\n\n" + inventory_body
    source = tmp_path / "STATE-WI.jsonld"
    source.write_bytes(canonical_body)

    with pytest.raises(
        StateLawsSourceReceiptReuseError,
        match="retained admitted body does not match",
    ):
        qualify_existing_source_receipt(
            _receipt(inventory_body, request, response),
            input_path=source,
            jurisdiction="WI",
            release_point=RELEASE_POINT,
            request_bytes=request,
            response_bytes=response,
            body_bytes=inventory_body,
        )


def test_receipt_row_count_must_equal_canonical_artifact(tmp_path: Path) -> None:
    body = _canonical_body(rows=2)
    request = b"GET /statutes HTTP/1.1\n"
    response = b"HTTP/1.1 200 OK\n\n" + body
    source = tmp_path / "STATE-WI.jsonld"
    source.write_bytes(body)
    receipt = _receipt(body, request, response, rows=1)

    with pytest.raises(StateLawsSourceReceiptReuseError, match="row count does not match"):
        qualify_existing_source_receipt(
            receipt,
            input_path=source,
            jurisdiction="WI",
            release_point=RELEASE_POINT,
            request_bytes=request,
            response_bytes=response,
            body_bytes=body,
        )


def test_checkpoint_or_materialization_claim_is_not_upgraded(
    tmp_path: Path,
) -> None:
    body = _canonical_body()
    source = tmp_path / "STATE-WI.jsonld"
    source.write_bytes(body)
    nonauthorizing = {
        "authorizing_coordinator_reuse": False,
        "authorizing_for_publication": False,
        "jurisdiction": "WI",
        "operation": "offline_checkpoint_rematerialization",
        "output_artifact": {
            "row_count": 1,
            "sha256": hashlib.sha256(body).hexdigest(),
        },
        "status": "materialized",
    }

    with pytest.raises(
        StateLawsSourceReceiptReuseError,
        match="shared acquisition gate rejected receipt",
    ):
        qualify_existing_source_receipt(
            nonauthorizing,
            input_path=source,
            jurisdiction="WI",
            release_point=RELEASE_POINT,
            request_bytes=b"retained request ledger",
            response_bytes=b"retained response ledger",
            body_bytes=body,
        )

    assert state_laws_source_receipt_reuse.AUTHORIZES_RECEIPT_FROM_CHECKPOINT is False
    assert (
        state_laws_source_receipt_reuse.REQUIRES_RETAINED_REQUEST_RESPONSE_BODY is True
    )


def test_canonical_artifact_symlink_is_rejected(tmp_path: Path) -> None:
    body = _canonical_body()
    real = tmp_path / "real.jsonld"
    real.write_bytes(body)
    linked = tmp_path / "STATE-WI.jsonld"
    linked.symlink_to(real)
    request = b"GET /statutes HTTP/1.1\n"
    response = b"HTTP/1.1 200 OK\n\n" + body

    with pytest.raises(StateLawsSourceReceiptReuseError, match="non-symlink"):
        qualify_existing_source_receipt(
            _receipt(body, request, response),
            input_path=linked,
            jurisdiction="WI",
            release_point=RELEASE_POINT,
            request_bytes=request,
            response_bytes=response,
            body_bytes=body,
        )
