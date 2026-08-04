"""Integration tests: stage authenticated Hub PR for hub index packages.

PATLAW-176 acceptance:

* Fake-service tests prove missing/wrong approval cannot publish main.
* Credentials never appear in receipts.
* Default path does not contact live Hub unless operator-invoked.
* Stage plan enumerates corpus / BM25 / vector / graph artifacts.
* No direct-main upload, embedded token, unattended approval, or
  supervisor self-approval.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.domains.patent.hf_layout_v2 import (
    BM25_REPOSITORY,
    CANONICAL_REPOSITORY_NAMES,
    CORPUS_REPOSITORY,
    KNOWLEDGE_GRAPH_REPOSITORY,
    ORGANIZATION,
    VECTORS_REPOSITORY,
)
from ipfs_datasets_py.processors.domains.patent.hf_publisher_v2 import (
    ApprovalError,
    ArtifactChangedError,
    AuthError,
    BaseRevisionError,
    ConflictError,
    DirectMainUploadError,
    FakeHubService,
    PartialUploadError,
    PatentHFPublisherV2,
    PatentHFPublisherV2Error,
    PublicationApprovalReceipt,
    create_operator_approval,
    default_test_base_revisions,
    new_ephemeral_operator_key,
    plan_stage_from_local_root,
    publisher_can_generate_operator_approval,
    reject_credentials_in_payload,
    verify_operator_approval,
)
from ipfs_datasets_py.processors.domains.patent.hub_index_package import (
    INDEX_FAMILIES,
    MANIFEST_FILENAME,
    package_patent_legal_hub_indexes,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
STAGE_SCRIPT = REPO_ROOT / "scripts/ops/legal_data/stage_patent_legal_hub_indexes.py"
PUBLISHER_PATH = (
    REPO_ROOT / "ipfs_datasets_py/processors/domains/patent/hf_publisher_v2.py"
)
BASE_SHA = "0" * 40


def _load_stage_module():
    spec = importlib.util.spec_from_file_location(
        "stage_patent_legal_hub_indexes", STAGE_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


stage_mod = _load_stage_module()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def staged_package(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("hub-index-package")
    package_patent_legal_hub_indexes(
        default_fixture=True,
        stage=True,
        output_dir=root,
    )
    return root


@pytest.fixture
def package_copy(staged_package: Path, tmp_path: Path) -> Path:
    dest = tmp_path / "package"
    shutil.copytree(staged_package, dest)
    return dest


@pytest.fixture
def bases() -> dict[str, str]:
    return default_test_base_revisions(sha=BASE_SHA)


@pytest.fixture
def operator_key() -> bytes:
    """Ephemeral key injected by the test — never from the publisher module."""
    return new_ephemeral_operator_key()


@pytest.fixture
def release_manifest(package_copy: Path) -> dict[str, Any]:
    return stage_mod.build_release_manifest_from_package(package_copy)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json_blob(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _assert_no_credentials(payload: object) -> None:
    reject_credentials_in_payload(payload, label="test_receipt")
    text = _json_blob(payload)
    lowered = text.casefold()
    assert "bearer " not in lowered
    assert "password=" not in lowered
    assert "fake-operator-token" not in text
    assert not re.search(r"(?<![a-z0-9_-])hf_[A-Za-z0-9]{12,}", text)


def _write_bases(path: Path, bases: dict[str, str]) -> Path:
    path.write_text(json.dumps(bases, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Schema / surface pins
# ---------------------------------------------------------------------------


def test_task_and_schema_pins() -> None:
    assert stage_mod.TASK_ID == "PATLAW-176"
    assert stage_mod.GOAL_ID == "PATLAW-G212"
    assert stage_mod.STAGE_RECEIPT_SCHEMA == "patent-legal-hub-index-stage-receipt/v1"
    assert (
        stage_mod.DRY_RUN_RECEIPT_SCHEMA
        == "patent-legal-hub-index-dry-run-staging-receipt/v1"
    )
    assert set(INDEX_FAMILIES) == {"bm25", "vectors", "knowledge_graph"}
    assert STAGE_SCRIPT.is_file()


def test_release_manifest_enumerates_all_projections(
    package_copy: Path, release_manifest: dict[str, Any]
) -> None:
    assert release_manifest["release_root_cid"]
    assert release_manifest["package_root_cid"] == release_manifest["release_root_cid"]
    assert set(release_manifest["index_families_present"]) == set(INDEX_FAMILIES)
    counts = release_manifest["projection_artifact_counts"]
    for family in ("corpus", *INDEX_FAMILIES):
        assert counts.get(family, 0) >= 1, family

    repos_seen = {item["repository"] for item in release_manifest["artifacts"]}
    for repo in CANONICAL_REPOSITORY_NAMES:
        assert repo in repos_seen, repo

    # Index pins and Viewer cards both present.
    rels = {item["relative_path"] for item in release_manifest["artifacts"]}
    assert any(r.startswith("indexes/bm25/") for r in rels)
    assert any(r.startswith("indexes/vectors/") for r in rels)
    assert any(r.startswith("indexes/knowledge_graph/") for r in rels)
    assert any(r.startswith("indexes/corpus/") for r in rels)
    assert any(r.startswith(f"repos/{CORPUS_REPOSITORY}/") for r in rels)
    assert any(r.startswith(f"repos/{BM25_REPOSITORY}/") for r in rels)
    assert any(r.startswith(f"repos/{VECTORS_REPOSITORY}/") for r in rels)
    assert any(r.startswith(f"repos/{KNOWLEDGE_GRAPH_REPOSITORY}/") for r in rels)
    _assert_no_credentials(release_manifest)


# ---------------------------------------------------------------------------
# Happy path — dry-run (default, no Hub contact)
# ---------------------------------------------------------------------------


def test_dry_run_plan_default_no_hub_contact(
    package_copy: Path,
    bases: dict[str, str],
    release_manifest: dict[str, Any],
) -> None:
    api = FakeHubService(base_revisions=bases)
    publisher = PatentHFPublisherV2(api=api, token=api.auth_token)
    plan = publisher.plan(
        local_root=package_copy,
        base_revisions=bases,
        manifest=release_manifest,
    )
    assert plan.dry_run is True
    assert plan.plan_digest
    assert plan.staged_diff_digest
    assert plan.upload_bytes > 0
    assert plan.release_root_cid == release_manifest["package_root_cid"]
    assert set(plan.dataset_ids()) == {
        f"{ORGANIZATION}/{name}" for name in CANONICAL_REPOSITORY_NAMES
    }
    assert plan.branch_name.casefold() not in {"main", "master"}
    assert api.calls == []
    receipt = plan.to_dict()
    assert receipt["remote_write_contacted"] is False
    _assert_no_credentials(receipt)


def test_stage_and_promote_with_exact_operator_approval(
    package_copy: Path,
    bases: dict[str, str],
    operator_key: bytes,
    release_manifest: dict[str, Any],
) -> None:
    api = FakeHubService(base_revisions=bases)
    publisher = PatentHFPublisherV2(api=api, token=api.auth_token)
    plan = publisher.plan(
        local_root=package_copy,
        base_revisions=bases,
        manifest=release_manifest,
    )

    staged = publisher.stage_pull_request(plan, local_root=package_copy)
    assert staged.main_published is False
    assert staged.pointers_moved is False
    assert staged.status == "staged_pending_approval"
    assert len(staged.repositories) == len(CANONICAL_REPOSITORY_NAMES)
    for repo in staged.repositories:
        assert repo.pull_request_number is not None
        assert repo.staged_commit_sha
        assert api.main_sha(repo.dataset_id) == BASE_SHA
    _assert_no_credentials(staged.to_dict())

    approval = create_operator_approval(
        plan=plan,
        operator_key=operator_key,
        approver="patent-legal-operator",
        approval_id="ops-approval-1",
    )
    verify_operator_approval(approval, plan=plan, operator_key=operator_key)

    promoted = publisher.promote_approved(
        plan,
        staged=staged,
        approval=approval,
        operator_key=operator_key,
        local_root=package_copy,
    )
    assert promoted.main_published is True
    assert promoted.pointers_moved is False
    assert promoted.approval_id == "ops-approval-1"
    for repo in promoted.repositories:
        assert api.main_sha(repo.dataset_id) == repo.promoted_commit_sha
        assert repo.promoted_commit_sha != BASE_SHA
    _assert_no_credentials(promoted.to_dict())
    assert "upload_file" not in api.calls
    assert "delete_repo" not in api.calls


# ---------------------------------------------------------------------------
# Approval fail-closed
# ---------------------------------------------------------------------------


def test_missing_approval_cannot_promote(
    package_copy: Path,
    bases: dict[str, str],
    operator_key: bytes,
    release_manifest: dict[str, Any],
) -> None:
    api = FakeHubService(base_revisions=bases)
    publisher = PatentHFPublisherV2(api=api, token=api.auth_token)
    plan = publisher.plan(
        local_root=package_copy,
        base_revisions=bases,
        manifest=release_manifest,
    )
    staged = publisher.stage_pull_request(plan, local_root=package_copy)

    with pytest.raises((ApprovalError, TypeError, KeyError)):
        publisher.promote_approved(
            plan,
            staged=staged,
            approval={},  # type: ignore[arg-type]
            operator_key=operator_key,
            local_root=package_copy,
        )
    for dataset_id in plan.dataset_ids():
        assert api.main_sha(dataset_id) == BASE_SHA


def test_wrong_approval_signature_cannot_promote(
    package_copy: Path,
    bases: dict[str, str],
    operator_key: bytes,
    release_manifest: dict[str, Any],
) -> None:
    api = FakeHubService(base_revisions=bases)
    publisher = PatentHFPublisherV2(api=api, token=api.auth_token)
    plan = publisher.plan(
        local_root=package_copy,
        base_revisions=bases,
        manifest=release_manifest,
    )
    staged = publisher.stage_pull_request(plan, local_root=package_copy)
    approval = create_operator_approval(
        plan=plan,
        operator_key=operator_key,
        approver="patent-legal-operator",
        approval_id="ops-1",
    )
    bad = PublicationApprovalReceipt(
        schema_version=approval.schema_version,
        approval_id=approval.approval_id,
        approver=approval.approver,
        plan_digest=approval.plan_digest,
        staged_diff_digest=approval.staged_diff_digest,
        release_root_cid=approval.release_root_cid,
        signature="f" * 64,
        credentials_scope=approval.credentials_scope,
        max_upload_bytes=approval.max_upload_bytes,
    )
    with pytest.raises(ApprovalError, match="signature"):
        publisher.promote_approved(
            plan,
            staged=staged,
            approval=bad,
            operator_key=operator_key,
            local_root=package_copy,
        )
    for dataset_id in plan.dataset_ids():
        assert api.main_sha(dataset_id) == BASE_SHA


def test_wrong_operator_key_cannot_promote(
    package_copy: Path,
    bases: dict[str, str],
    operator_key: bytes,
    release_manifest: dict[str, Any],
) -> None:
    api = FakeHubService(base_revisions=bases)
    publisher = PatentHFPublisherV2(api=api, token=api.auth_token)
    plan = publisher.plan(
        local_root=package_copy,
        base_revisions=bases,
        manifest=release_manifest,
    )
    staged = publisher.stage_pull_request(plan, local_root=package_copy)
    foreign = create_operator_approval(
        plan=plan,
        operator_key=new_ephemeral_operator_key(),
        approver="other-operator",
        approval_id="foreign",
    )
    with pytest.raises(ApprovalError):
        publisher.promote_approved(
            plan,
            staged=staged,
            approval=foreign,
            operator_key=operator_key,
            local_root=package_copy,
        )
    for dataset_id in plan.dataset_ids():
        assert api.main_sha(dataset_id) == BASE_SHA


def test_publisher_cannot_generate_operator_approval(
    package_copy: Path,
    bases: dict[str, str],
    release_manifest: dict[str, Any],
) -> None:
    api = FakeHubService(base_revisions=bases)
    publisher = PatentHFPublisherV2(api=api, token=api.auth_token)
    plan = publisher.plan(
        local_root=package_copy,
        base_revisions=bases,
        manifest=release_manifest,
    )

    assert publisher_can_generate_operator_approval() is False
    assert PatentHFPublisherV2.OPERATOR_APPROVAL_KEY is None

    with pytest.raises(ApprovalError, match="cannot generate"):
        publisher.generate_operator_approval(plan)
    with pytest.raises(ApprovalError, match="self-approval"):
        publisher.self_approve(plan)

    with pytest.raises(ApprovalError, match="self-approve|cannot"):
        create_operator_approval(
            plan=plan,
            operator_key=new_ephemeral_operator_key(),
            approver="implementation-agent",
            approval_id="bad",
        )


# ---------------------------------------------------------------------------
# Base / artifact / conflict / partial / auth / direct-main
# ---------------------------------------------------------------------------


def test_changed_base_blocks_stage(
    package_copy: Path,
    bases: dict[str, str],
    release_manifest: dict[str, Any],
) -> None:
    wrong_heads = {k: "1" * 40 for k in bases}
    api = FakeHubService(base_revisions=wrong_heads)
    publisher = PatentHFPublisherV2(api=api, token=api.auth_token)
    plan = publisher.plan(
        local_root=package_copy,
        base_revisions=bases,
        manifest=release_manifest,
    )
    with pytest.raises(BaseRevisionError, match="advanced after audit|approved parent"):
        publisher.stage_pull_request(plan, local_root=package_copy)
    for dataset_id in plan.dataset_ids():
        assert api.main_sha(dataset_id) == "1" * 40


def test_changed_artifact_blocks_stage(
    package_copy: Path,
    bases: dict[str, str],
    release_manifest: dict[str, Any],
) -> None:
    api = FakeHubService(base_revisions=bases)
    publisher = PatentHFPublisherV2(api=api, token=api.auth_token)
    plan = publisher.plan(
        local_root=package_copy,
        base_revisions=bases,
        manifest=release_manifest,
    )
    target = package_copy.joinpath(*Path(plan.artifacts[0].relative_path).parts)
    target.write_bytes(target.read_bytes() + b"MUTATED")
    with pytest.raises(ArtifactChangedError):
        publisher.stage_pull_request(plan, local_root=package_copy)
    for dataset_id in plan.dataset_ids():
        assert api.main_sha(dataset_id) == BASE_SHA


def test_conflict_on_branch_blocks_stage(
    package_copy: Path,
    bases: dict[str, str],
    release_manifest: dict[str, Any],
) -> None:
    api = FakeHubService(base_revisions=bases, conflict_on_branch=True)
    publisher = PatentHFPublisherV2(api=api, token=api.auth_token)
    plan = publisher.plan(
        local_root=package_copy,
        base_revisions=bases,
        manifest=release_manifest,
    )
    with pytest.raises(ConflictError):
        publisher.stage_pull_request(plan, local_root=package_copy)
    for dataset_id in plan.dataset_ids():
        assert api.main_sha(dataset_id) == BASE_SHA


def test_partial_upload_does_not_publish_main(
    package_copy: Path,
    bases: dict[str, str],
    release_manifest: dict[str, Any],
) -> None:
    api = FakeHubService(base_revisions=bases, fail_create_commit_after=1)
    publisher = PatentHFPublisherV2(api=api, token=api.auth_token)
    plan = publisher.plan(
        local_root=package_copy,
        base_revisions=bases,
        manifest=release_manifest,
    )
    with pytest.raises(PartialUploadError):
        publisher.stage_pull_request(plan, local_root=package_copy)
    for dataset_id in plan.dataset_ids():
        assert api.main_sha(dataset_id) == BASE_SHA


def test_auth_error_blocks_stage(
    package_copy: Path,
    bases: dict[str, str],
    release_manifest: dict[str, Any],
) -> None:
    api = FakeHubService(base_revisions=bases, fail_auth=True)
    publisher = PatentHFPublisherV2(api=api, token="wrong-token")
    plan = publisher.plan(
        local_root=package_copy,
        base_revisions=bases,
        manifest=release_manifest,
    )
    with pytest.raises(AuthError):
        publisher.stage_pull_request(plan, local_root=package_copy)
    for dataset_id in plan.dataset_ids():
        assert api.main_sha(dataset_id) == BASE_SHA


def test_direct_main_upload_prohibited(
    package_copy: Path,
    bases: dict[str, str],
    release_manifest: dict[str, Any],
) -> None:
    with pytest.raises(DirectMainUploadError):
        plan_stage_from_local_root(
            local_root=package_copy,
            manifest=release_manifest,
            base_revisions=bases,
            branch_name="main",
        )


def test_pointer_promotion_refused(bases: dict[str, str]) -> None:
    publisher = PatentHFPublisherV2(
        api=FakeHubService(base_revisions=bases),
        token="t",
    )
    with pytest.raises(PatentHFPublisherV2Error, match="pointer"):
        publisher.canary_promote_pointer()


# ---------------------------------------------------------------------------
# Credentials stay out of receipts
# ---------------------------------------------------------------------------


def test_fake_service_credentials_stay_out_of_receipts(
    package_copy: Path,
    bases: dict[str, str],
    operator_key: bytes,
    release_manifest: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "hf_thisIsAFakeTokenValueForLeakTest99"
    monkeypatch.setenv("HF_TOKEN", secret)
    api = FakeHubService(base_revisions=bases, auth_token=secret)
    publisher = PatentHFPublisherV2(api=api, token=secret)
    plan = publisher.plan(
        local_root=package_copy,
        base_revisions=bases,
        manifest=release_manifest,
    )
    staged = publisher.stage_pull_request(plan, local_root=package_copy)
    approval = create_operator_approval(
        plan=plan,
        operator_key=operator_key,
        approver="ops",
        approval_id="cred-1",
    )
    promoted = publisher.promote_approved(
        plan,
        staged=staged,
        approval=approval,
        operator_key=operator_key,
        local_root=package_copy,
    )
    for payload in (
        plan.to_dict(),
        staged.to_dict(),
        approval.to_dict(),
        promoted.to_dict(),
    ):
        blob = _json_blob(payload)
        assert secret not in blob
        _assert_no_credentials(payload)
    assert secret in api.tokens_seen


def test_source_has_no_live_hfapi_import() -> None:
    stage_source = STAGE_SCRIPT.read_text(encoding="utf-8")
    assert "HfApi(" not in stage_source
    assert "from huggingface_hub" not in stage_source
    assert "import huggingface_hub" not in stage_source
    publisher_source = PUBLISHER_PATH.read_text(encoding="utf-8")
    assert "HfApi(" not in publisher_source
    assert "from huggingface_hub" not in publisher_source


# ---------------------------------------------------------------------------
# Admission binding
# ---------------------------------------------------------------------------


def test_require_admission_blocks_without_receipt(
    package_copy: Path,
    bases: dict[str, str],
) -> None:
    with pytest.raises(stage_mod.AdmissionRequiredError):
        stage_mod.run_dry_run(
            package_dir=package_copy,
            organization=ORGANIZATION,
            base_revisions=bases,
            branch_name=None,
            target_revision="main",
            version_tag=None,
            release_id=None,
            admission_receipt=None,
            require_admission=True,
        )


def test_admission_receipt_must_bind_package_root(
    package_copy: Path,
    bases: dict[str, str],
    tmp_path: Path,
) -> None:
    ctx = stage_mod.load_package_context(package_copy)
    package_root_cid = ctx["manifest"].package_root_cid
    bad = {
        "admitted": True,
        "package_root_cid": "bafyreithisiswrongcid0000000000000000000001",
        "schema_version": stage_mod.ADMISSION_RECEIPT_SCHEMA,
        "task_id": "PATLAW-175",
    }
    path = tmp_path / "bad-admission.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(stage_mod.AdmissionMismatchError):
        stage_mod.verify_admission_receipt(
            path, package_root_cid=package_root_cid, require=True
        )

    good = {
        "admitted": True,
        "package_root_cid": package_root_cid,
        "schema_version": stage_mod.ADMISSION_RECEIPT_SCHEMA,
        "task_id": "PATLAW-175",
    }
    receipt = stage_mod.verify_admission_receipt(
        good, package_root_cid=package_root_cid, require=True
    )
    assert receipt is not None
    assert receipt["admitted"] is True


def test_rejected_admission_cannot_stage(
    package_copy: Path,
    bases: dict[str, str],
) -> None:
    ctx = stage_mod.load_package_context(package_copy)
    package_root_cid = ctx["manifest"].package_root_cid
    rejected = {
        "admitted": False,
        "package_root_cid": package_root_cid,
        "schema_version": stage_mod.ADMISSION_RECEIPT_SCHEMA,
        "reason_codes": ["rights.unreviewed"],
    }
    with pytest.raises(stage_mod.AdmissionRequiredError):
        stage_mod.run_stage(
            package_dir=package_copy,
            organization=ORGANIZATION,
            base_revisions=bases,
            branch_name=None,
            target_revision="main",
            version_tag=None,
            release_id=None,
            fake_service=True,
            token_env="HF_TOKEN",
            create_pr=True,
            admission_receipt=rejected,
            require_admission=True,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_default_is_dry_run(
    package_copy: Path,
    bases: dict[str, str],
    tmp_path: Path,
) -> None:
    bases_path = _write_bases(tmp_path / "bases.json", bases)
    receipt_path = tmp_path / "receipt.json"
    code = stage_mod.main(
        [
            "--mode",
            "dry-run",
            "--package-dir",
            str(package_copy),
            "--base-revisions-file",
            str(bases_path),
            "--receipt-out",
            str(receipt_path),
        ]
    )
    assert code == 0
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert payload["status"] == "dry_run_only"
    assert payload["tokens_used"] is False
    assert payload["main_published"] is False
    assert payload["live_network"] is False
    assert payload["remote_write_contacted"] is False
    assert payload["task_id"] == "PATLAW-176"
    assert payload["package_root_cid"]
    assert set(payload["index_families_present"]) == set(INDEX_FAMILIES)
    assert payload["human_approval_required"] is True
    _assert_no_credentials(payload)


def test_cli_fake_stage_sign_promote(
    package_copy: Path,
    bases: dict[str, str],
    operator_key: bytes,
    tmp_path: Path,
) -> None:
    bases_path = _write_bases(tmp_path / "bases.json", bases)
    key_path = tmp_path / "operator.key"
    key_path.write_bytes(operator_key)

    stage_receipt = tmp_path / "staged.json"
    code = stage_mod.main(
        [
            "--mode",
            "stage",
            "--fake-service",
            "--package-dir",
            str(package_copy),
            "--base-revisions-file",
            str(bases_path),
            "--receipt-out",
            str(stage_receipt),
        ]
    )
    assert code == 0
    staged = json.loads(stage_receipt.read_text(encoding="utf-8"))
    assert staged["status"] == "staged_pending_approval"
    assert staged["main_published"] is False
    assert staged["fake_service"] is True
    assert staged["package_root_cid"]
    assert set(staged["index_families_present"]) == set(INDEX_FAMILIES)
    _assert_no_credentials(staged)

    approval_path = tmp_path / "approval.json"
    code = stage_mod.main(
        [
            "--mode",
            "sign",
            "--package-dir",
            str(package_copy),
            "--base-revisions-file",
            str(bases_path),
            "--operator-key-file",
            str(key_path),
            "--approval-out",
            str(approval_path),
            "--approver",
            "cli-operator",
            "--approval-id",
            "cli-1",
        ]
    )
    assert code == 0
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    assert approval["approver"] == "cli-operator"
    _assert_no_credentials(approval)

    promote_receipt = tmp_path / "promoted.json"
    code = stage_mod.main(
        [
            "--mode",
            "promote",
            "--fake-service",
            "--package-dir",
            str(package_copy),
            "--base-revisions-file",
            str(bases_path),
            "--operator-key-file",
            str(key_path),
            "--approval-file",
            str(approval_path),
            "--staged-receipt-file",
            str(stage_receipt),
            "--receipt-out",
            str(promote_receipt),
        ]
    )
    assert code == 0
    promoted = json.loads(promote_receipt.read_text(encoding="utf-8"))
    assert promoted["status"] == "promoted"
    assert promoted["main_published"] is True
    assert promoted["pointers_moved"] is False
    _assert_no_credentials(promoted)


def test_cli_stage_without_fake_service_fails_closed(
    package_copy: Path,
    bases: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bases_path = _write_bases(tmp_path / "bases.json", bases)
    monkeypatch.setenv("HF_TOKEN", "hf_" + "x" * 24)
    code = stage_mod.main(
        [
            "--mode",
            "stage",
            "--package-dir",
            str(package_copy),
            "--base-revisions-file",
            str(bases_path),
            "--receipt-out",
            str(tmp_path / "should-not-exist.json"),
        ]
    )
    assert code == 1
    assert not (tmp_path / "should-not-exist.json").exists()


def test_cli_sign_rejects_agent_approver(
    package_copy: Path,
    bases: dict[str, str],
    operator_key: bytes,
    tmp_path: Path,
) -> None:
    bases_path = _write_bases(tmp_path / "bases.json", bases)
    key_path = tmp_path / "operator.key"
    key_path.write_bytes(operator_key)
    code = stage_mod.main(
        [
            "--mode",
            "sign",
            "--package-dir",
            str(package_copy),
            "--base-revisions-file",
            str(bases_path),
            "--operator-key-file",
            str(key_path),
            "--approver",
            "implementation-agent",
            "--approval-out",
            str(tmp_path / "approval.json"),
        ]
    )
    assert code == 1


def test_cli_require_admission_exit_code(
    package_copy: Path,
    bases: dict[str, str],
    tmp_path: Path,
) -> None:
    bases_path = _write_bases(tmp_path / "bases.json", bases)
    code = stage_mod.main(
        [
            "--mode",
            "dry-run",
            "--package-dir",
            str(package_copy),
            "--base-revisions-file",
            str(bases_path),
            "--require-admission",
            "--receipt-out",
            str(tmp_path / "receipt.json"),
        ]
    )
    assert code == 1


def test_cli_with_valid_admission_receipt(
    package_copy: Path,
    bases: dict[str, str],
    tmp_path: Path,
) -> None:
    bases_path = _write_bases(tmp_path / "bases.json", bases)
    ctx = stage_mod.load_package_context(package_copy)
    admission = {
        "admitted": True,
        "package_root_cid": ctx["manifest"].package_root_cid,
        "schema_version": stage_mod.ADMISSION_RECEIPT_SCHEMA,
        "task_id": "PATLAW-175",
    }
    admission_path = tmp_path / "admission.json"
    admission_path.write_text(json.dumps(admission), encoding="utf-8")
    receipt_path = tmp_path / "receipt.json"
    code = stage_mod.main(
        [
            "--mode",
            "dry-run",
            "--package-dir",
            str(package_copy),
            "--base-revisions-file",
            str(bases_path),
            "--admission-receipt",
            str(admission_path),
            "--require-admission",
            "--receipt-out",
            str(receipt_path),
        ]
    )
    assert code == 0
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert payload["admission_bound"] is True
    assert payload["admission"]["admitted"] is True
    _assert_no_credentials(payload)


def test_missing_index_family_blocks_stage_plan(
    package_copy: Path,
) -> None:
    # Remove BM25 index tree after packaging.
    shutil.rmtree(package_copy / "indexes" / "bm25")
    with pytest.raises(stage_mod.StageHubIndexError, match="missing index tree|bm25"):
        stage_mod.load_package_context(package_copy)


def test_module_run_stage_fake_service_receipt(
    package_copy: Path,
    bases: dict[str, str],
) -> None:
    payload = stage_mod.run_stage(
        package_dir=package_copy,
        organization=ORGANIZATION,
        base_revisions=bases,
        branch_name=None,
        target_revision="main",
        version_tag=None,
        release_id=None,
        fake_service=True,
        token_env="HF_TOKEN",
        create_pr=True,
        require_admission=False,
    )
    assert payload["status"] == "staged_pending_approval"
    assert payload["main_published"] is False
    assert payload["fake_service"] is True
    assert payload["tokens_used"] is False
    assert (package_copy / "release-manifest.json").is_file()
    assert (package_copy / MANIFEST_FILENAME).is_file()
    _assert_no_credentials(payload)
