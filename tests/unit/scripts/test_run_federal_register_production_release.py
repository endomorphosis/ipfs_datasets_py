"""Injection-only Federal staging/main operator bridge tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.huggingface.publisher import PublicationApproval
from ipfs_datasets_py.processors.legal_data.federal_register_hf_release import (
    build_federal_register_hf_release,
    fixture_family_rows,
    fixture_legacy_files,
    load_source_rights_receipt,
)
import scripts.ops.legal_data.run_federal_register_production_release as operator
import scripts.ops.legal_data.seal_federal_register_live_candidate as live


def _bundle() -> tuple[object, dict, dict, dict]:
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
    evidence = live.build_canonical_production_evidence_bundle(
        release=release,
        inventory=inventory,
        fulltext=fulltext,
        corpus=corpus,
        evaluation=evaluation,
        source_rights=load_source_rights_receipt(),
    )
    return release, evidence["candidate"], inventory, evidence["fulltext"]


def _approval(plan_digest: str, approval_id: str) -> PublicationApproval:
    return PublicationApproval(
        approver="operator@example.test",
        plan_digest=plan_digest,
        max_cost_usd=1.0,
        max_upload_bytes=10_000_000,
        credentials_scope="dataset:write:justicedao/ipfs_federal_register",
        approval_id=approval_id,
    )


def test_cli_is_check_only() -> None:
    assert operator.main([]) == 2
    assert operator.main(["--check"]) == 0


@pytest.mark.parametrize("field", ["sha256", "content_cid"])
def test_candidate_must_match_exact_release_descriptors(field: str) -> None:
    release, candidate, _inventory, _fulltext = _bundle()
    operator.require_production_release_candidate(
        release=release,
        candidate=candidate,
    )
    tampered = json.loads(json.dumps(candidate))
    tampered["descriptors"][0][field] = (
        "f" * 64 if field == "sha256" else "bafkrei" + "a" * 52
    )
    tampered["content_digest"] = operator._candidate_digest(tampered)
    with pytest.raises(
        operator.FederalRegisterProductionOperatorError,
        match="descriptors differ",
    ):
        operator.require_production_release_candidate(
            release=release,
            candidate=tampered,
        )


@pytest.mark.parametrize("field", ["official_document_count", "configs"])
def test_candidate_rejects_recomputed_release_metadata_drift(field: str) -> None:
    release, candidate, _inventory, _fulltext = _bundle()
    tampered = json.loads(json.dumps(candidate))
    if field == "official_document_count":
        tampered["candidate"][field] += 1
    else:
        tampered[field] = list(reversed(tampered[field]))
    tampered["content_digest"] = operator._candidate_digest(tampered)
    with pytest.raises(
        operator.FederalRegisterProductionOperatorError,
        match="metadata differs",
    ):
        operator.require_production_release_candidate(
            release=release,
            candidate=tampered,
        )


def test_candidate_rejects_recomputed_semantic_closure_drift() -> None:
    release, candidate, _inventory, _fulltext = _bundle()
    tampered = json.loads(json.dumps(candidate))
    tampered["semantic_family_closure"]["present"].pop()
    tampered["content_digest"] = operator._candidate_digest(tampered)
    with pytest.raises(
        operator.FederalRegisterProductionOperatorError,
        match="candidate validation failed",
    ):
        operator.require_production_release_candidate(
            release=release,
            candidate=tampered,
        )


@pytest.mark.parametrize("field", ["first_issue", "binds_first_issue"])
def test_candidate_rejects_recomputed_first_issue_drift(field: str) -> None:
    release, candidate, _inventory, _fulltext = _bundle()
    tampered = json.loads(json.dumps(candidate))
    if field == "first_issue":
        tampered["first_issue"]["publication_date"] = "1936-03-15"
    else:
        tampered["acceptance"]["binds_first_issue"] = False
    tampered["content_digest"] = operator._candidate_digest(tampered)
    with pytest.raises(
        operator.FederalRegisterProductionOperatorError,
        match="candidate validation failed",
    ):
        operator.require_production_release_candidate(
            release=release,
            candidate=tampered,
        )


def test_staging_wrapper_requires_two_approvals_and_delegates(monkeypatch) -> None:
    release, candidate, _inventory, _fulltext = _bundle()
    captured = {}

    def execute(**kwargs):
        captured.update(kwargs)
        return {"status": "passed"}

    monkeypatch.setattr(operator, "execute_canonical_staging_release", execute)
    branch = _approval("1" * 64, "branch-approval")
    commit = _approval("1" * 64, "commit-approval")
    result = operator.execute_federal_staging_operator_path(
        release=release,
        candidate=candidate,
        output_root="release",
        branch_approval=branch,
        commit_approval=commit,
    )
    assert result == {"status": "passed"}
    assert captured["release"] is release
    assert captured["branch_approval"] is branch
    assert captured["commit_approval"] is commit


def test_canary_wrapper_wires_exact_release_and_fetcher(monkeypatch) -> None:
    release, candidate, inventory, fulltext = _bundle()
    captured = {}

    def canary(**kwargs):
        captured.update(kwargs)
        return {"status": "passed"}

    monkeypatch.setattr(operator, "run_remote_canary", canary)
    fetch = lambda *_args: b""
    receipt = {
        "staging_revision": "b" * 40,
        "target_repo": "justicedao/ipfs_federal_register",
    }
    remote = [item.descriptor_dict() for item in release.artifacts]
    operator.execute_federal_staging_canary_operator_path(
        release=release,
        candidate=candidate,
        staging_receipt=receipt,
        remote_descriptors=remote,
        fetch_file=fetch,
        inventory=inventory,
        fulltext=fulltext,
    )
    assert captured["fetch_file"] is fetch
    assert captured["artifact_descriptors"] == remote
    assert captured["remote_descriptors"] is remote


def test_main_wrapper_requires_canonical_candidate_then_delegates(
    tmp_path: Path, monkeypatch
) -> None:
    release, candidate, _inventory, _fulltext = _bundle()
    target = tmp_path / operator.CANONICAL_CANDIDATE_RELPATH
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(candidate), encoding="utf-8")
    captured = {}

    def execute(**kwargs):
        captured.update(kwargs)
        return {"status": "published"}

    monkeypatch.setattr(operator, "execute_canonical_main_release", execute)
    approval = _approval("2" * 64, "main-approval")
    result = operator.execute_federal_main_operator_path(
        release=release,
        candidate=candidate,
        output_root=tmp_path / "release",
        main_approval=approval,
        staging_revision="b" * 40,
        sealed_at="2026-08-29T12:00:00Z",
        repository_root=tmp_path,
    )
    assert result == {"status": "published"}
    assert captured["release"] is release
    assert captured["approval"] is approval
