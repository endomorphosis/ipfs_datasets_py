"""Unit tests for extended prior-art operator features (foreign/NPL/PPS/ack)."""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.processors.domains.patent.prior_art import (
    assert_no_patentability_conclusions,
)
from ipfs_datasets_py.processors.domains.uspto.prior_art_operator_extensions import (
    PPS_PUBLIC_URL,
    acknowledge_prior_art_run,
    load_foreign_hits,
    load_npl_records,
    record_pps_verification,
)
from ipfs_datasets_py.processors.domains.uspto.prior_art_search_client import (
    search_prior_art,
)


SAMPLE_CLAIM = (
    "1. A method comprising encoding claim text for retrieval using CPC codes."
)


def _us_snap(path: Path) -> Path:
    path.write_text(
        json.dumps(
            [
                {
                    "document_id": "doc:encode-prior",
                    "title": "Encoding retrieval system for patent claims",
                    "abstract": "A method comprising encoding claim text for retrieval",
                    "claims": "1. A method comprising encoding claim text for retrieval.",
                    "cpc": "G06F16/00",
                    "source_cid": "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
                    "publicationDate": "2020-01-15",
                }
            ]
        ),
        encoding="utf-8",
    )
    return path


def _foreign(path: Path) -> Path:
    path.write_text(
        json.dumps(
            [
                {
                    "document_id": "EP0999991A1",
                    "title": "European encoding system",
                    "country": "EP",
                    "source_cid": "bafybeigforeign1",
                }
            ]
        ),
        encoding="utf-8",
    )
    return path


def _npl(path: Path) -> Path:
    path.write_text(
        json.dumps(
            [
                {
                    "document_id": "npl:open-1",
                    "title": "Open encoding preprint",
                    "identifier": "10.1234/example",
                    "rights_status": "public",
                },
                {
                    "document_id": "npl:secret",
                    "title": "Paywalled",
                    "rights_status": "unlicensed",
                    "body_text": "this body must never be redistributed",
                },
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_load_foreign_and_npl(tmp_path: Path) -> None:
    hits = load_foreign_hits(_foreign(tmp_path / "f.json"))
    assert len(hits) == 1
    assert "EP" in hits[0].document_id or "0999991" in hits[0].document_id
    recs = load_npl_records(_npl(tmp_path / "n.json"))
    assert len(recs) == 2
    secret = next(r for r in recs if r.document_id == "npl:secret")
    assert secret.body_text is None  # unlicensed body stripped at load


def test_extended_search_foreign_npl_pps_report(tmp_path: Path) -> None:
    result = search_prior_art(
        application_number="18654466",
        state_root=tmp_path,
        claims_text=SAMPLE_CLAIM,
        filing_date="2024-05-03",
        priority_date="2024-02-13",
        classifications=["G06F16/00"],
        local_snapshot_path=_us_snap(tmp_path / "us.json"),
        enable_foreign=True,
        foreign_hits_path=_foreign(tmp_path / "foreign.json"),
        enable_npl=True,
        npl_catalog_path=_npl(tmp_path / "npl.json"),
        npl_licensed=True,
        max_queries=16,
    )
    assert result["ok"] is True
    status = result["adapter_status"]
    assert status["foreign"]["enabled"] is True
    assert status["npl"]["enabled"] is True
    assert Path(result["paths"]["report"]).is_file()
    assert Path(result["paths"]["pps_checklist"]).is_file()
    assert Path(result["paths"]["coverage"]).is_file()

    searched = set(result["summary"].get("searched_corpora") or [])
    assert "foreign_patents" in searched or "npl" in searched or "us_patents" in searched

    pps = json.loads(Path(result["paths"]["pps_checklist"]).read_text(encoding="utf-8"))
    assert pps["pps_url"] == PPS_PUBLIC_URL
    assert pps["item_count"] >= 1
    assert "not" in pps["disclaimer"].lower()

    assert_no_patentability_conclusions(result["summary"])
    assert_no_patentability_conclusions(
        json.loads(Path(result["paths"]["report"]).read_text(encoding="utf-8"))
    )


def test_pps_record_and_acknowledge(tmp_path: Path) -> None:
    result = search_prior_art(
        application_number="18654466",
        state_root=tmp_path,
        claims_text=SAMPLE_CLAIM,
        filing_date="2024-05-03",
        priority_date="2024-02-13",
        local_snapshot_path=_us_snap(tmp_path / "us.json"),
        max_queries=4,
    )
    run_dir = Path(result["run_dir"])
    pps = json.loads((run_dir / "pps_verification_checklist.json").read_text())
    qid = pps["items"][0]["query_id"]

    rec = record_pps_verification(
        run_dir,
        results=[
            {
                "query_id": qid,
                "human_result_count": 3,
                "human_notes": "spot check",
            }
        ],
        verified_by="operator:test",
    )
    assert rec["ok"] is True
    assert rec["record"]["updated_items"] == 1

    ack = acknowledge_prior_art_run(
        run_dir,
        acknowledger_name="operator:test",
        claim_search_complete=False,
    )
    assert ack["ok"] is True
    assert Path(ack["acknowledgment_path"]).is_file()
    assert Path(ack["checklist_path"]).is_file()
    assert "prior_art_search_complete" in ack
    assert_no_patentability_conclusions(ack)


def test_foreign_unlicensed_remains_gap(tmp_path: Path) -> None:
    result = search_prior_art(
        application_number="18654466",
        state_root=tmp_path,
        claims_text=SAMPLE_CLAIM,
        filing_date="2024-05-03",
        priority_date="2024-02-13",
        local_snapshot_path=_us_snap(tmp_path / "us.json"),
        enable_foreign=True,
        foreign_hits_path=_foreign(tmp_path / "foreign.json"),
        foreign_licensed=False,
        max_queries=8,
    )
    cov = json.loads(Path(result["paths"]["coverage"]).read_text(encoding="utf-8"))
    gap_blob = json.dumps(cov).lower()
    assert "foreign" in gap_blob
