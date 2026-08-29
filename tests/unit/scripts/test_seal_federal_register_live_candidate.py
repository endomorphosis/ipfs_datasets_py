"""Hermetic tests for LCR-071 live candidate seal."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import scripts.ops.legal_data.seal_federal_register_live_candidate as seal
from ipfs_datasets_py.processors.legal_data.federal_register_hf_release import (
    FederalRegisterHFReleaseIntegrityError,
    build_federal_production_candidate_evidence,
    build_federal_register_hf_release,
    fixture_family_rows,
    fixture_legacy_files,
    load_source_rights_receipt,
)


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


def _production_bundle_inputs() -> tuple[object, dict, dict, dict, dict, dict]:
    release = build_federal_register_hf_release(
        fixture_family_rows(),
        legacy_files=fixture_legacy_files(),
    )
    total = 3
    inventory = {
        "acceptance": {
            "failed_final": 0,
            "failed_final_zero": True,
            "frontier_closed": True,
            "mode": "live",
            "official_total": total,
        },
        "counts": {"failed_final": 0},
        "frontier_closed": True,
        "identity": {
            "duplicate_free": True,
            "unique_legal_id_count": total,
        },
        "observation_cutoff": "2026-08-10T00:00:00Z",
    }
    fulltext = {
        "authorizing_hub_upload": False,
        "classified": total,
        "compact_recipe": False,
        "excluded": 0,
        "failed_final": 0,
        "full_text_admitted": total,
        "metadata_only": 0,
        "mode": "live",
        "observation_cutoff": "2026-08-10T00:00:00Z",
        "quarantined": 0,
        "sample_identity": False,
    }
    corpus = {
        "authorizing_hub_upload": False,
        "error_count": 0,
        "mismatches": 0,
        "status": "passed",
        "verified": total,
    }
    evaluation = {
        "acceptance": {
            "local_query_canary": True,
            "no_fixture_result_called_live_canary": True,
        },
        "authorizing_hub_upload": False,
        "bm25": {"meets_declared_gates": True},
        "documents": total,
        "fixture_only": False,
        "gold": {"meets_declared_gates": True},
        "graph": {"meets_declared_gates": True},
        "status": "passed",
        "vector": {"meets_declared_gates": True},
    }
    rights = load_source_rights_receipt()
    return release, inventory, fulltext, corpus, evaluation, rights


def test_production_bundle_binds_release_descriptors_and_terminal_fields() -> None:
    release, inventory, fulltext, corpus, evaluation, rights = (
        _production_bundle_inputs()
    )
    bundle = seal.build_canonical_production_evidence_bundle(
        release=release,
        inventory=inventory,
        fulltext=fulltext,
        corpus=corpus,
        evaluation=evaluation,
        source_rights=rights,
    )

    candidate = bundle["candidate"]
    acceptance = bundle["full_live_acceptance"]
    assert candidate["fixture_only"] is False
    assert candidate["manifest_digest"] == release.manifest_digest
    assert candidate["candidate"]["manifest_digest"] == release.manifest_digest
    assert candidate["descriptors"]
    assert candidate["first_package_id"] == "FR-1936-03-14"
    assert acceptance["first_issue"]["package_id"] == "FR-1936-03-14"
    assert acceptance["binds_first_issue"] is True
    assert acceptance["frontier_closed"] is True
    assert acceptance["failed_final_count"] == 0
    assert bundle["admission"]["acceptance"]["one_disposition_per_input"] is True
    assert bundle["fulltext"]["acceptance"]["failed_final_zero"] is True
    assert bundle["evaluation"]["acceptance"]["all_expected_outputs_accounted"] is True


def test_production_bundle_rejects_release_inventory_row_drift() -> None:
    release, inventory, fulltext, corpus, evaluation, rights = (
        _production_bundle_inputs()
    )
    inventory["acceptance"]["official_total"] = 4
    inventory["identity"]["unique_legal_id_count"] = 4
    fulltext["classified"] = 4
    fulltext["full_text_admitted"] = 4
    corpus["verified"] = 4
    evaluation["documents"] = 4
    with pytest.raises(Exception, match="release corpus rows"):
        seal.build_canonical_production_evidence_bundle(
            release=release,
            inventory=inventory,
            fulltext=fulltext,
            corpus=corpus,
            evaluation=evaluation,
            source_rights=rights,
        )


def test_production_bundle_rejects_nonconserving_fulltext_disposition() -> None:
    release, inventory, fulltext, corpus, evaluation, rights = (
        _production_bundle_inputs()
    )
    fulltext["excluded"] = 1
    with pytest.raises(Exception, match="live exhaustion"):
        seal.build_canonical_production_evidence_bundle(
            release=release,
            inventory=inventory,
            fulltext=fulltext,
            corpus=corpus,
            evaluation=evaluation,
            source_rights=rights,
        )


def test_production_bundle_rejects_stale_rights_catalog() -> None:
    release, inventory, fulltext, corpus, evaluation, rights = (
        _production_bundle_inputs()
    )
    rights["catalog_digest_sha256"] = "f" * 64
    with pytest.raises(
        FederalRegisterHFReleaseIntegrityError,
        match="source-rights binding",
    ):
        seal.build_canonical_production_evidence_bundle(
            release=release,
            inventory=inventory,
            fulltext=fulltext,
            corpus=corpus,
            evaluation=evaluation,
            source_rights=rights,
        )


def test_production_candidate_rejects_forged_validation_for_invalid_release() -> None:
    release, _inventory, _fulltext, _corpus, _evaluation, rights = (
        _production_bundle_inputs()
    )
    invalid_release = replace(release, manifest_digest="f" * 64)
    with pytest.raises(FederalRegisterHFReleaseIntegrityError):
        build_federal_production_candidate_evidence(
            invalid_release,
            official_document_count=3,
            first_issue={
                "number": 1,
                "package_id": "FR-1936-03-14",
                "publication_date": "1936-03-14",
                "volume": 1,
            },
            inventory_digest="1" * 64,
            admission_digest="2" * 64,
            fulltext_digest="3" * 64,
            evaluation_digest="4" * 64,
            full_live_acceptance_digest="5" * 64,
            source_rights=rights,
            validation={"valid": True},
        )
