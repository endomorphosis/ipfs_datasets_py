"""Canonical Federal Register publication-package controls."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.huggingface.publisher import canonical_json_bytes
from ipfs_datasets_py.processors.legal_data.federal_register_hf_release import (
    build_federal_register_hf_release,
    fixture_family_rows,
    fixture_legacy_files,
)
from ipfs_datasets_py.processors.legal_data.federal_register_publication_package import (
    DEFAULT_STAGING_BRANCH,
    SOURCE_RIGHTS_RELPATH,
    STAGING_CANARY_RELPATH,
    FederalRegisterPublicationPackageError,
    _candidate_digest,
    materialize_federal_register_main_controls,
    materialize_federal_register_staging_controls,
    plan_federal_register_publication_dry_run,
    prepare_federal_register_publication_package,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    PREVIOUS_PUBLIC_PIN,
)
from scripts.ops.legal_data.seal_federal_register_prepublication import (
    check_federal_prepublication_seal,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(scope="module")
def release():
    return build_federal_register_hf_release(
        fixture_family_rows(),
        legacy_files=fixture_legacy_files(),
        dry_run=True,
    )


def _production_candidate(package) -> dict:
    candidate = {
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "candidate": {
            "dataset_id": "justicedao/ipfs_federal_register",
            "kind": "production_descriptor_complete",
            "manifest_digest": package.manifest_digest,
        },
        "fixture_only": False,
        "hub_upload": False,
        "mode": "production",
        "publication_binding": None,
        "schema": "ipfs_datasets_py/legal-corpora-reindex-federal-candidate@1",
        "source_rights": {
            "receipt_digest": package.source_rights_receipt_digest,
        },
    }
    candidate["content_digest"] = _candidate_digest(candidate)
    return candidate


def _canonical_root(root: Path) -> None:
    target = root / SOURCE_RIGHTS_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((REPOSITORY_ROOT / SOURCE_RIGHTS_RELPATH).read_bytes())


def test_package_and_staging_plan_bind_every_exact_artifact(
    release,
    tmp_path: Path,
) -> None:
    package = prepare_federal_register_publication_package(
        release,
        output_root=tmp_path / "release",
    )
    plan = plan_federal_register_publication_dry_run(
        package,
        audited_parent_commit=PREVIOUS_PUBLIC_PIN,
        target_revision=DEFAULT_STAGING_BRANCH,
    )
    assert plan.target_revision == DEFAULT_STAGING_BRANCH
    assert plan.release_sha256 == release.manifest_digest
    assert len(plan.operations) == len(release.artifacts)
    assert {item.relative_path for item in plan.operations} == {
        item.relative_path for item in release.artifacts
    }
    assert all(item["operation"] == "add_only_upload" for item in package.descriptors)


def test_staging_then_main_controls_close_a_b_chain_and_strict_seal(
    release,
    tmp_path: Path,
) -> None:
    package = prepare_federal_register_publication_package(
        release,
        output_root=tmp_path / "release",
    )
    _canonical_root(tmp_path)
    staging_plan = plan_federal_register_publication_dry_run(
        package,
        audited_parent_commit=PREVIOUS_PUBLIC_PIN,
        target_revision=DEFAULT_STAGING_BRANCH,
    )
    staging = materialize_federal_register_staging_controls(
        package,
        staging_plan,
        _production_candidate(package),
        repository_root=tmp_path,
    )
    candidate_path = tmp_path / staging.candidate_path
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    assert candidate["publication_binding"] == {
        "plan_digest": staging.plan_digest,
        "policy_proof_digest": staging.policy_proof_digest,
        "release_manifest_digest": package.manifest_digest,
        "staging_candidate_digest": staging.staging_candidate_digest,
    }
    staging_revision = "6" * 40
    canary = {
        "candidate_manifest_digest": staging.candidate_manifest_digest,
        "dataset_repo_id": "justicedao/ipfs_federal_register",
        "dirty": False,
        "final_manifest_digest": staging.staging_candidate_digest,
        "fixture_only": False,
        "live_staging": True,
        "plan_digest": staging.plan_digest,
        "policy_proof_digest": staging.policy_proof_digest,
        "release_manifest_digest": package.manifest_digest,
        "staging_revision": staging_revision,
        "status": "passed",
    }
    canary_path = tmp_path / STAGING_CANARY_RELPATH
    canary_path.parent.mkdir(parents=True, exist_ok=True)
    canary_path.write_bytes(canonical_json_bytes(canary) + b"\n")
    main_plan = plan_federal_register_publication_dry_run(
        package,
        audited_parent_commit=PREVIOUS_PUBLIC_PIN,
        target_revision="main",
    )
    main = materialize_federal_register_main_controls(
        package,
        main_plan,
        repository_root=tmp_path,
        staging_revision=staging_revision,
        sealed_at="2026-08-29T00:00:00Z",
    )
    promoted = json.loads(candidate_path.read_text(encoding="utf-8"))
    assert main.staging_candidate_digest == staging.staging_candidate_digest
    assert main.candidate_manifest_digest != main.staging_candidate_digest
    assert promoted["publication_binding"]["plan_digest"] == main.plan_digest
    card = (tmp_path / main.dataset_card_path).read_text(encoding="utf-8")
    for identity in (
        main.candidate_manifest_digest,
        main.staging_candidate_digest,
        main.release_manifest_digest,
        main.plan_digest,
        main.policy_proof_digest,
        main.staging_revision,
    ):
        assert identity in card
    checked = check_federal_prepublication_seal(repo_root=tmp_path)
    assert checked["final_manifest_digest"] == main.candidate_manifest_digest
    assert checked["staging_revision"] == staging_revision


def test_main_controls_reject_canary_plan_tamper(release, tmp_path: Path) -> None:
    package = prepare_federal_register_publication_package(
        release,
        output_root=tmp_path / "release",
    )
    _canonical_root(tmp_path)
    staging_plan = plan_federal_register_publication_dry_run(
        package,
        audited_parent_commit=PREVIOUS_PUBLIC_PIN,
        target_revision=DEFAULT_STAGING_BRANCH,
    )
    staging = materialize_federal_register_staging_controls(
        package,
        staging_plan,
        _production_candidate(package),
        repository_root=tmp_path,
    )
    canary = {
        "dataset_repo_id": "justicedao/ipfs_federal_register",
        "dirty": False,
        "final_manifest_digest": staging.staging_candidate_digest,
        "fixture_only": False,
        "live_staging": True,
        "plan_digest": "9" * 64,
        "policy_proof_digest": staging.policy_proof_digest,
        "release_manifest_digest": package.manifest_digest,
        "staging_revision": "6" * 40,
        "status": "passed",
    }
    canary_path = tmp_path / STAGING_CANARY_RELPATH
    canary_path.parent.mkdir(parents=True, exist_ok=True)
    canary_path.write_bytes(canonical_json_bytes(canary) + b"\n")
    main_plan = plan_federal_register_publication_dry_run(
        package,
        audited_parent_commit=PREVIOUS_PUBLIC_PIN,
    )
    with pytest.raises(
        FederalRegisterPublicationPackageError,
        match="staging canary",
    ):
        materialize_federal_register_main_controls(
            package,
            main_plan,
            repository_root=tmp_path,
            staging_revision="6" * 40,
            sealed_at="2026-08-29T00:00:00Z",
        )


def test_staging_controls_reject_candidate_self_digest_tamper(
    release,
    tmp_path: Path,
) -> None:
    package = prepare_federal_register_publication_package(
        release,
        output_root=tmp_path / "release",
    )
    _canonical_root(tmp_path)
    plan = plan_federal_register_publication_dry_run(
        package,
        audited_parent_commit=PREVIOUS_PUBLIC_PIN,
        target_revision=DEFAULT_STAGING_BRANCH,
    )
    candidate = _production_candidate(package)
    candidate["content_digest"] = "f" * 64
    with pytest.raises(
        FederalRegisterPublicationPackageError,
        match="content digest",
    ):
        materialize_federal_register_staging_controls(
            package,
            plan,
            candidate,
            repository_root=tmp_path,
        )
