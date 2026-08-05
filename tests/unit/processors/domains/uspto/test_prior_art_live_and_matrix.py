"""Tests for live foreign/NPL wiring and distinguishability matrix."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from ipfs_datasets_py.processors.domains.patent.prior_art import (
    assert_no_patentability_conclusions,
)
from ipfs_datasets_py.processors.domains.patent.prior_art_runtime import (
    AdapterSearchResult,
)
from ipfs_datasets_py.processors.domains.patent.search_journal import (
    JournalHit,
    QueryOutcomeKind,
    make_source_link,
)
from ipfs_datasets_py.processors.domains.uspto.prior_art_operator_extensions import (
    build_and_persist_distinguishability_matrix,
    build_coverage_adapter_registry,
)
from ipfs_datasets_py.processors.domains.uspto.prior_art_search_client import (
    search_prior_art,
)
from ipfs_datasets_py.processors.domains.uspto.providers.npl_public_clients import (
    build_npl_public_search_fn,
    npl_rows_to_records,
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
                    "abstract": "encoding claim text for retrieval",
                    "claims": "1. A method comprising encoding claim text.",
                    "cpc": "G06F16/00",
                    "source_cid": "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
                    "publicationDate": "2020-01-15",
                }
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_build_registry_live_flags_without_credentials() -> None:
    registry, status = build_coverage_adapter_registry(
        live_foreign=True,
        live_npl=True,
    )
    assert status["foreign"]["enabled"] is True
    assert status["npl"]["enabled"] is True
    assert status["npl"]["live"] is True
    # foreign live without EPO creds → warning, not live backend
    assert status["foreign"]["live"] is False
    assert "epo_ops_missing" in str(status["foreign"].get("backend") or "")
    assert registry.names()  # at least npl adapter registered


def test_npl_public_search_fn_mocked() -> None:
    rows = [
        {
            "document_id": "npl:openalex:W123",
            "title": "Encoding patents with retrieval",
            "identifier": "10.1/example",
            "rights_status": "public",
            "metadata": {"source": "openalex"},
        }
    ]

    def fake_search(query, **kwargs):
        return rows

    with patch(
        "ipfs_datasets_py.processors.domains.uspto.providers.npl_public_clients.search_npl_public",
        side_effect=fake_search,
    ):
        fn = build_npl_public_search_fn(max_results=5)
        from ipfs_datasets_py.processors.domains.patent.prior_art_runtime import (
            PublicSearchQuery,
        )
        from ipfs_datasets_py.processors.domains.patent.search_journal import (
            SearchDatabase,
        )

        q = PublicSearchQuery(
            query_id="q1",
            query_text="encoding retrieval",
            database=SearchDatabase.NPL,
            rank_cutoff=5,
        )
        result = fn(q, "2024-01-01T00:00:00Z", "2024-01-01")
        assert result.outcome is QueryOutcomeKind.SUCCESS
        assert result.hits


def test_npl_rows_strip_body() -> None:
    recs = npl_rows_to_records(
        [
            {
                "document_id": "npl:x",
                "title": "T",
                "identifier": "10.1/x",
                "rights_status": "public",
                "body_text": "should not pass through rows_to_records intentionally",
            }
        ]
    )
    assert recs[0].body_text is None


def test_distinguishability_matrix_no_conclusions(tmp_path: Path) -> None:
    result = search_prior_art(
        application_number="18654466",
        state_root=tmp_path,
        claims_text=SAMPLE_CLAIM,
        filing_date="2024-05-03",
        priority_date="2024-02-13",
        classifications=["G06F16/00"],
        local_snapshot_path=_us_snap(tmp_path / "us.json"),
        max_queries=4,
    )
    assert Path(result["paths"]["distinguishability_matrix"]).is_file()
    matrix = json.loads(
        Path(result["paths"]["distinguishability_matrix"]).read_text(encoding="utf-8")
    )
    assert matrix["limitation_count"] >= 1
    assert matrix["cells"]
    for cell in matrix["cells"]:
        assert cell["review_label"] == "candidate_overlap_only"
        assert "not" in cell["not_a_determination"].lower()
    assert_no_patentability_conclusions(matrix)

    rebuilt = build_and_persist_distinguishability_matrix(result["run_dir"])
    assert rebuilt["ok"] is True
    assert rebuilt["cell_count"] >= 1


def test_search_with_mocked_live_foreign(tmp_path: Path) -> None:
    hit = JournalHit(
        document_id="EP0999991A1",
        rank=1,
        score=90.0,
        source_links=(
            make_source_link(
                source_cid="bafybeigforeign1",
                artifact_id="artifact:ep",
                end=20,
            ),
        ),
        passage_excerpt="European encoding system",
        metadata={"rights_status": "public", "title": "European encoding system"},
    )

    def fake_epo_fn(query, search_time_utc, corpus_cutoff, pre_ranking_filters=None):
        return AdapterSearchResult(
            outcome=QueryOutcomeKind.SUCCESS,
            hits=(hit,),
            result_count=1,
            status_code=200,
            metadata={"adapter": "epo_ops.v1", "rights_status": "public"},
        )

    with patch(
        "ipfs_datasets_py.processors.domains.uspto.providers.epo_ops_client.has_epo_ops_credentials",
        return_value=True,
    ), patch(
        "ipfs_datasets_py.processors.domains.uspto.providers.epo_ops_client.build_epo_foreign_search_fn",
        return_value=fake_epo_fn,
    ):
        result = search_prior_art(
            application_number="18654466",
            state_root=tmp_path,
            claims_text=SAMPLE_CLAIM,
            filing_date="2024-05-03",
            priority_date="2024-02-13",
            local_snapshot_path=_us_snap(tmp_path / "us.json"),
            live_foreign=True,
            max_queries=8,
        )
    assert result["ok"] is True
    assert result["adapter_status"]["foreign"]["live"] is True
