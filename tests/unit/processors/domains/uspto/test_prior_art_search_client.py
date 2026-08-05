"""Unit tests for portfolio prior-art search client (offline, no live ODP/HF)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.patent.prior_art import (
    PRIOR_ART_DISCLAIMER,
    assert_no_patentability_conclusions,
)
from ipfs_datasets_py.processors.domains.uspto.prior_art_search_client import (
    PRIOR_ART_CLIENT_SCHEMA,
    PriorArtSearchClientError,
    list_prior_art_runs,
    load_claims,
    load_local_snapshot_documents,
    parse_claims_text,
    plan_prior_art,
    search_prior_art,
    show_prior_art_run,
)


SAMPLE_CLAIM = (
    "1. A method comprising encoding claim text for retrieval using CPC codes."
)


def _snapshot(path: Path) -> Path:
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
                },
                {
                    "document_id": "doc:network-prior",
                    "title": "Network packet classification",
                    "abstract": "Systems for classifying network packets",
                    "claims": "1. A system comprising network packet classification.",
                    "cpc": "H04L45/00",
                    "source_cid": "bafybeic3g5s5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x",
                    "publicationDate": "2019-06-01",
                },
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_parse_claims_text_numbered() -> None:
    claims = parse_claims_text(
        "1. A method comprising encoding.\n2. The method of claim 1 wherein hybrid."
    )
    assert len(claims) == 2
    assert claims[0]["claim_number"] == 1
    assert "encoding" in claims[0]["claim_text"]


def test_load_claims_from_json_file(tmp_path: Path) -> None:
    p = tmp_path / "claims.json"
    p.write_text(
        json.dumps(
            {
                "claims": [
                    {"claim_number": 1, "claim_text": "A system comprising a sensor."}
                ]
            }
        ),
        encoding="utf-8",
    )
    claims = load_claims(claims_file=p)
    assert claims[0]["claim_number"] == 1


def test_plan_prior_art_persists_with_gaps(tmp_path: Path) -> None:
    result = plan_prior_art(
        application_number="18654466",
        state_root=tmp_path,
        claims_text=SAMPLE_CLAIM,
        filing_date="2024-05-03",
        priority_date="2024-02-13",
        classifications=["G06F16/00"],
    )
    assert result["ok"] is True
    assert result["schema"] == PRIOR_ART_CLIENT_SCHEMA
    assert result["query_count"] >= 1
    assert result["limitation_count"] >= 1
    gap_blob = json.dumps(result["coverage_gaps"]).lower()
    assert "foreign" in gap_blob
    assert "npl" in gap_blob
    assert Path(result["paths"]["plan"]).is_file()
    assert_no_patentability_conclusions(result)


def test_search_prior_art_local_snapshot(tmp_path: Path) -> None:
    snap = _snapshot(tmp_path / "snap.json")
    result = search_prior_art(
        application_number="18654466",
        state_root=tmp_path,
        claims_text=SAMPLE_CLAIM,
        filing_date="2024-05-03",
        priority_date="2024-02-13",
        classifications=["G06F16/00"],
        local_snapshot_path=snap,
        max_queries=4,
    )
    assert result["ok"] is True
    assert result["journal_id"]
    assert result["chart_id"]
    assert result["coverage_id"]
    paths = result["paths"]
    for key in (
        "plan",
        "journal",
        "coverage",
        "claim_chart",
        "summary",
        "manifest",
    ):
        assert Path(paths[key]).is_file(), key

    summary = result["summary"]
    assert "candidate_hits" in summary
    assert summary["candidate_hits"], "expected at least one local hit"
    gap_blob = json.dumps(summary["coverage_gaps"]).lower()
    assert "foreign" in gap_blob or "npl" in gap_blob
    assert "review_tips" in summary
    assert "not" in summary["disclaimer"].lower()
    # Refuse patentability conclusion keys
    assert_no_patentability_conclusions(summary)
    assert_no_patentability_conclusions(result)

    listed = list_prior_art_runs(
        application_number="18654466", state_root=tmp_path
    )
    assert listed["count"] >= 1
    shown = show_prior_art_run(
        run_id=result["run_id"],
        application_number="18654466",
        state_root=tmp_path,
    )
    assert shown["ok"] is True
    assert shown["manifest"]["action"] == "search"


def test_search_requires_backend(tmp_path: Path) -> None:
    with pytest.raises(PriorArtSearchClientError) as exc:
        search_prior_art(
            application_number="18654466",
            state_root=tmp_path,
            claims_text=SAMPLE_CLAIM,
            filing_date="2024-05-03",
            use_odp=False,
            local_snapshot_path=None,
        )
    assert exc.value.code == "no_search_backend"


def test_load_local_snapshot_documents(tmp_path: Path) -> None:
    snap = _snapshot(tmp_path / "docs.json")
    docs = load_local_snapshot_documents(snap)
    assert len(docs) == 2
    assert docs[0].document_id == "doc:encode-prior"


def test_disclaimer_present_on_plan_artifact() -> None:
    # Module-level disclaimer used by domain layer remains non-empty
    assert "not" in PRIOR_ART_DISCLAIMER.lower()
    assert "novelty" in PRIOR_ART_DISCLAIMER.lower()
