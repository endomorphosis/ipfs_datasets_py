"""Hermetic tests for LCR-071 live candidate seal."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.ops.legal_data.seal_federal_register_live_candidate as seal


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _live_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    official = seal.EXPECTED_LIVE_DOCUMENTS
    _write(
        root / seal.INVENTORY_RELPATH,
        {"acceptance": {"mode": "live", "official_total": official}},
    )
    _write(
        root / seal.LIVE_FULLTEXT_RELPATH,
        {
            "classified": official,
            "full_text_admitted": official,
            "failed_final": 0,
            "sample_identity": False,
            "compact_recipe": False,
            "checkpoint_sha256": "aa" * 32,
            "authorizing_hub_upload": False,
        },
    )
    _write(
        root / seal.LIVE_CORPUS_RELPATH,
        {"verified": official, "status": "passed", "authorizing_hub_upload": False},
    )
    _write(
        root / seal.LIVE_BM25_RELPATH,
        {
            "documents": official,
            "vocabulary_size": 10,
            "status": "passed",
            "authorizing_hub_upload": False,
        },
    )
    _write(
        root / seal.LIVE_GRAPH_RELPATH,
        {
            "fixture_only": False,
            "status": "passed",
            "node_count": 9,
            "edge_count": 12,
            "content_digest": "bb" * 32,
            "authorizing_hub_upload": False,
        },
    )
    _write(
        root / seal.LIVE_ADJACENCY_RELPATH,
        {
            "fixture_only": False,
            "status": "passed",
            "content_digest": "cc" * 32,
            "authorizing_hub_upload": False,
        },
    )
    _write(
        root / seal.LIVE_EVAL_RELPATH,
        {
            "fixture_only": False,
            "status": "passed",
            "content_digest": "dd" * 32,
            "authorizing_hub_upload": False,
        },
    )
    _write(
        root / seal.LIVE_VECTORS_RELPATH,
        {
            "fixture_only": False,
            "status": "passed",
            "backend": "sentence_transformers",
            "centroid_bounds_hold": True,
            "vector_count": official,
            "cluster_count": 6,
            "vector_root_cid": "sha256:" + ("11" * 32),
            "content_digest": "aa" * 32,
            "authorizing_hub_upload": False,
        },
    )
    _write(
        root / seal.LIVE_GOLD_RELPATH,
        {
            "fixture_only": False,
            "status": "passed",
            "content_digest": "22" * 32,
            "authorizing_hub_upload": False,
        },
    )
    _write(
        root / seal.RIGHTS_RELPATH,
        {
            "catalog_digest_sha256": "ee" * 32,
            "receipt_digest": "ff" * 32,
        },
    )
    return root


def test_missing_evaluation_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(seal.LiveCandidateError, match="required receipt missing"):
        seal.seal_live_candidate(repository_root=tmp_path, write_receipt=False)


def test_seal_writes_non_fixture_kind_without_hub_upload(tmp_path: Path) -> None:
    root = _live_workspace(tmp_path)
    payload = seal.seal_live_candidate(repository_root=root, write_receipt=True)
    assert payload["candidate"]["kind"] == "live_official_complete"
    assert payload["candidate"]["kind"] not in seal.FORBIDDEN_KINDS
    assert payload["fixture_only"] is False
    assert payload["authorizing_for_publication"] is False
    assert payload["authorizing_hub_upload"] is False
    assert payload["semantic_family_closure"]["closed"] is True
    assert payload["semantic_family_closure"]["missing"] == []
    assert "vectors" in payload["semantic_family_closure"]["present"]
    assert payload["vectors_deferred"] is False
    assert (root / seal.LIVE_CANDIDATE_RELPATH).is_file()
    assert (root / "docs/reports/legal_corpora_reindex/federal_candidate.json").exists() is False
