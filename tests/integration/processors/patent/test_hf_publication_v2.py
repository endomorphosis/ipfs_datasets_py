"""Integration tests: patent HF v2 staged Hub PR with exact operator approval.

PATLAW-159 acceptance:

* Missing/wrong approval, changed base, changed artifact, conflict, partial
  upload, auth error or race cannot publish main/pointers.
* Fake service proves credentials stay out of receipts.
* The implementation agent / publisher cannot generate the operator approval
  it consumes.
* No direct-main upload, embedded token, unattended approval, supervisor
  self-approval, repository deletion, or pointer promotion.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import re
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.patent.hf_layout_v2 import (
    CANONICAL_REPOSITORY_NAMES,
    ORGANIZATION,
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
    materialize_minimal_release_tree,
    new_ephemeral_operator_key,
    plan_stage_from_local_root,
    publisher_can_generate_operator_approval,
    reject_credentials_in_payload,
    verify_operator_approval,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
PUBLISHER_PATH = (
    REPO_ROOT
    / "ipfs_datasets_py/processors/domains/patent/hf_publisher_v2.py"
)
STAGE_SCRIPT = REPO_ROOT / "scripts/ops/legal_data/stage_patent_hf_release.py"
BASE_SHA = "0" * 40


def _load_stage_module():
    spec = importlib.util.spec_from_file_location(
        "stage_patent_hf_release", STAGE_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


stage_mod = _load_stage_module()


@pytest.fixture
def release_tree(tmp_path: Path) -> tuple[Path, dict]:
    root = tmp_path / "release"
    manifest = materialize_minimal_release_tree(root)
    return root, manifest


@pytest.fixture
def bases() -> dict[str, str]:
    return default_test_base_revisions(sha=BASE_SHA)


@pytest.fixture
def operator_key() -> bytes:
    """Ephemeral key injected by the test — never from the publisher module."""

    return new_ephemeral_operator_key()


def _json_blob(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _assert_no_credentials(payload: object) -> None:
    reject_credentials_in_payload(payload, label="test_receipt")
    text = _json_blob(payload)
    lowered = text.casefold()
    # Schema names may contain "hf_" (e.g. patent-legal-hf-publication-plan);
    # flag only token-shaped values.
    assert "bearer " not in lowered
    assert "password=" not in lowered
    assert "fake-operator-token" not in text
    # hf_<long> token pattern (not schema ids like patent-legal-hf-publication).
    assert not re.search(r"(?<![a-z0-9_-])hf_[A-Za-z0-9]{12,}", text)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_dry_run_plan_default_no_hub_contact(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
) -> None:
    root, _manifest = release_tree
    api = FakeHubService(base_revisions=bases)
    publisher = PatentHFPublisherV2(api=api, token=api.auth_token)
    plan = publisher.plan(local_root=root, base_revisions=bases)
    assert plan.dry_run is True
    assert plan.plan_digest
    assert plan.staged_diff_digest
    assert plan.upload_bytes > 0
    assert len(plan.artifacts) >= len(CANONICAL_REPOSITORY_NAMES)
    assert plan.branch_name.casefold() not in {"main", "master"}
    assert api.calls == []
    receipt = plan.to_dict()
    assert receipt["remote_write_contacted"] is False
    _assert_no_credentials(receipt)


def test_stage_and_promote_with_exact_operator_approval(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
    operator_key: bytes,
) -> None:
    root, _ = release_tree
    api = FakeHubService(base_revisions=bases)
    publisher = PatentHFPublisherV2(api=api, token=api.auth_token)
    plan = publisher.plan(local_root=root, base_revisions=bases)

    staged = publisher.stage_pull_request(plan, local_root=root)
    assert staged.main_published is False
    assert staged.pointers_moved is False
    assert staged.status == "staged_pending_approval"
    assert len(staged.repositories) == len(CANONICAL_REPOSITORY_NAMES)
    for repo in staged.repositories:
        assert repo.pull_request_number is not None
        assert repo.staged_commit_sha
        # Main must still be at audited base.
        assert api.main_sha(repo.dataset_id) == BASE_SHA
    _assert_no_credentials(staged.to_dict())

    # Operator (external key) signs; publisher did not generate this.
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
        local_root=root,
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
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
    operator_key: bytes,
) -> None:
    root, _ = release_tree
    api = FakeHubService(base_revisions=bases)
    publisher = PatentHFPublisherV2(api=api, token=api.auth_token)
    plan = publisher.plan(local_root=root, base_revisions=bases)
    staged = publisher.stage_pull_request(plan, local_root=root)

    with pytest.raises((ApprovalError, TypeError, KeyError)):
        publisher.promote_approved(
            plan,
            staged=staged,
            approval={},  # type: ignore[arg-type]
            operator_key=operator_key,
            local_root=root,
        )
    for dataset_id in plan.dataset_ids():
        assert api.main_sha(dataset_id) == BASE_SHA


def test_wrong_approval_signature_cannot_promote(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
    operator_key: bytes,
) -> None:
    root, _ = release_tree
    api = FakeHubService(base_revisions=bases)
    publisher = PatentHFPublisherV2(api=api, token=api.auth_token)
    plan = publisher.plan(local_root=root, base_revisions=bases)
    staged = publisher.stage_pull_request(plan, local_root=root)
    approval = create_operator_approval(
        plan=plan,
        operator_key=operator_key,
        approver="patent-legal-operator",
        approval_id="ops-1",
    )
    # Tamper signature.
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
            local_root=root,
        )
    for dataset_id in plan.dataset_ids():
        assert api.main_sha(dataset_id) == BASE_SHA


def test_wrong_plan_digest_approval_rejected(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
    operator_key: bytes,
) -> None:
    root, _ = release_tree
    api = FakeHubService(base_revisions=bases)
    publisher = PatentHFPublisherV2(api=api, token=api.auth_token)
    plan = publisher.plan(local_root=root, base_revisions=bases)
    staged = publisher.stage_pull_request(plan, local_root=root)
    other_key = new_ephemeral_operator_key()
    # Sign with a different key → verify with operator_key fails.
    foreign = create_operator_approval(
        plan=plan,
        operator_key=other_key,
        approver="other-operator",
        approval_id="foreign",
    )
    with pytest.raises(ApprovalError):
        publisher.promote_approved(
            plan,
            staged=staged,
            approval=foreign,
            operator_key=operator_key,
            local_root=root,
        )


def test_publisher_cannot_generate_operator_approval(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
) -> None:
    root, _ = release_tree
    api = FakeHubService(base_revisions=bases)
    publisher = PatentHFPublisherV2(api=api, token=api.auth_token)
    plan = publisher.plan(local_root=root, base_revisions=bases)

    assert publisher_can_generate_operator_approval() is False
    assert PatentHFPublisherV2.OPERATOR_APPROVAL_KEY is None

    with pytest.raises(ApprovalError, match="cannot generate"):
        publisher.generate_operator_approval(plan)
    with pytest.raises(ApprovalError, match="self-approval"):
        publisher.self_approve(plan)

    # Source must not embed a default operator key constant usable for signing.
    source = PUBLISHER_PATH.read_text(encoding="utf-8")
    assert "OPERATOR_APPROVAL_KEY: None" in source or "OPERATOR_APPROVAL_KEY = None" in source
    assert "DEFAULT_OPERATOR_KEY" not in source
    # Agent/supervisor markers are rejected as approver identities.
    with pytest.raises(ApprovalError, match="self-approve|cannot"):
        create_operator_approval(
            plan=plan,
            operator_key=new_ephemeral_operator_key(),
            approver="implementation-agent",
            approval_id="bad",
        )


# ---------------------------------------------------------------------------
# Base / artifact / conflict / race / partial / auth
# ---------------------------------------------------------------------------


def test_changed_base_blocks_stage(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
) -> None:
    root, _ = release_tree
    # Service heads differ from declared bases.
    wrong_heads = {k: "1" * 40 for k in bases}
    api = FakeHubService(base_revisions=wrong_heads)
    publisher = PatentHFPublisherV2(api=api, token=api.auth_token)
    plan = publisher.plan(local_root=root, base_revisions=bases)
    with pytest.raises(BaseRevisionError, match="advanced after audit|approved parent"):
        publisher.stage_pull_request(plan, local_root=root)
    for dataset_id in plan.dataset_ids():
        assert api.main_sha(dataset_id) == "1" * 40  # unchanged by failed stage


def test_changed_artifact_blocks_stage(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
) -> None:
    root, _ = release_tree
    api = FakeHubService(base_revisions=bases)
    publisher = PatentHFPublisherV2(api=api, token=api.auth_token)
    plan = publisher.plan(local_root=root, base_revisions=bases)
    # Mutate a local file after planning.
    target = root.joinpath(*Path(plan.artifacts[0].relative_path).parts)
    target.write_bytes(target.read_bytes() + b"MUTATED")
    with pytest.raises(ArtifactChangedError):
        publisher.stage_pull_request(plan, local_root=root)
    for dataset_id in plan.dataset_ids():
        assert api.main_sha(dataset_id) == BASE_SHA


def test_conflict_on_branch_blocks_stage(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
) -> None:
    root, _ = release_tree
    api = FakeHubService(base_revisions=bases, conflict_on_branch=True)
    publisher = PatentHFPublisherV2(api=api, token=api.auth_token)
    plan = publisher.plan(local_root=root, base_revisions=bases)
    with pytest.raises(ConflictError):
        publisher.stage_pull_request(plan, local_root=root)
    for dataset_id in plan.dataset_ids():
        assert api.main_sha(dataset_id) == BASE_SHA


def test_partial_upload_does_not_publish_main(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
) -> None:
    root, _ = release_tree
    # Fail after first create_commit succeeds.
    api = FakeHubService(base_revisions=bases, fail_create_commit_after=1)
    publisher = PatentHFPublisherV2(api=api, token=api.auth_token)
    plan = publisher.plan(local_root=root, base_revisions=bases)
    with pytest.raises(PartialUploadError):
        publisher.stage_pull_request(plan, local_root=root)
    # No main advanced.
    for dataset_id in plan.dataset_ids():
        assert api.main_sha(dataset_id) == BASE_SHA


def test_auth_error_blocks_stage_and_promote(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
    operator_key: bytes,
) -> None:
    root, _ = release_tree
    api = FakeHubService(base_revisions=bases, fail_auth=True)
    publisher = PatentHFPublisherV2(api=api, token="wrong-token")
    plan = publisher.plan(local_root=root, base_revisions=bases)
    with pytest.raises(AuthError):
        publisher.stage_pull_request(plan, local_root=root)

    # Good stage then bad auth on promote.
    api2 = FakeHubService(base_revisions=bases)
    pub2 = PatentHFPublisherV2(api=api2, token=api2.auth_token)
    staged = pub2.stage_pull_request(plan, local_root=root)
    approval = create_operator_approval(
        plan=plan,
        operator_key=operator_key,
        approver="ops",
        approval_id="a1",
    )
    api2.fail_auth = True
    with pytest.raises(AuthError):
        pub2.promote_approved(
            plan,
            staged=staged,
            approval=approval,
            operator_key=operator_key,
            local_root=root,
        )
    for dataset_id in plan.dataset_ids():
        assert api2.main_sha(dataset_id) == BASE_SHA


def test_race_on_promote_blocks_main(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
    operator_key: bytes,
) -> None:
    root, _ = release_tree
    api = FakeHubService(base_revisions=bases)
    publisher = PatentHFPublisherV2(api=api, token=api.auth_token)
    plan = publisher.plan(local_root=root, base_revisions=bases)
    staged = publisher.stage_pull_request(plan, local_root=root)
    approval = create_operator_approval(
        plan=plan,
        operator_key=operator_key,
        approver="ops",
        approval_id="race-1",
    )
    # Advance main after stage (race).
    first = plan.dataset_ids()[0]
    api._heads[first]["main"] = "9" * 40  # noqa: SLF001 — intentional race inject
    api._files[first]["9" * 40] = {}  # noqa: SLF001
    with pytest.raises(BaseRevisionError):
        publisher.promote_approved(
            plan,
            staged=staged,
            approval=approval,
            operator_key=operator_key,
            local_root=root,
        )


def test_direct_main_upload_prohibited(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
) -> None:
    root, _ = release_tree
    with pytest.raises(DirectMainUploadError):
        plan_stage_from_local_root(
            local_root=root,
            base_revisions=bases,
            branch_name="main",
        )
    api = FakeHubService(base_revisions=bases)
    with pytest.raises((DirectMainUploadError, PatentHFPublisherV2Error)):
        api.upload_file(path="x", repo_id="justicedao/patent-legal-corpus")


def test_pointer_promotion_refused(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
) -> None:
    publisher = PatentHFPublisherV2(
        api=FakeHubService(base_revisions=bases),
        token="t",
    )
    with pytest.raises(PatentHFPublisherV2Error, match="pointer"):
        publisher.canary_promote_pointer()


# ---------------------------------------------------------------------------
# Credentials / fake service receipts
# ---------------------------------------------------------------------------


def test_fake_service_credentials_stay_out_of_receipts(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
    operator_key: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = release_tree
    secret = "hf_thisIsAFakeTokenValueForLeakTest99"
    monkeypatch.setenv("HF_TOKEN", secret)
    api = FakeHubService(base_revisions=bases, auth_token=secret)
    publisher = PatentHFPublisherV2(api=api, token=secret)
    plan = publisher.plan(local_root=root, base_revisions=bases)
    staged = publisher.stage_pull_request(plan, local_root=root)
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
        local_root=root,
    )
    for payload in (plan.to_dict(), staged.to_dict(), approval.to_dict(), promoted.to_dict()):
        blob = _json_blob(payload)
        assert secret not in blob
        _assert_no_credentials(payload)
    # Token was used for auth but never persisted into receipts.
    assert secret in api.tokens_seen


def test_source_has_no_live_hfapi_import() -> None:
    source = PUBLISHER_PATH.read_text(encoding="utf-8")
    assert "HfApi(" not in source
    assert "from huggingface_hub" not in source
    assert "import huggingface_hub" not in source
    stage_source = STAGE_SCRIPT.read_text(encoding="utf-8")
    assert "HfApi(" not in stage_source
    assert "from huggingface_hub" not in stage_source


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_default_is_dry_run(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
    tmp_path: Path,
) -> None:
    root, _ = release_tree
    bases_path = tmp_path / "bases.json"
    bases_path.write_text(json.dumps(bases), encoding="utf-8")
    receipt_path = tmp_path / "receipt.json"
    code = stage_mod.main(
        [
            "--mode",
            "dry-run",
            "--local-root",
            str(root),
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
    _assert_no_credentials(payload)


def test_cli_fake_stage_sign_promote(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
    operator_key: bytes,
    tmp_path: Path,
) -> None:
    root, _ = release_tree
    bases_path = tmp_path / "bases.json"
    bases_path.write_text(json.dumps(bases), encoding="utf-8")
    key_path = tmp_path / "operator.key"
    key_path.write_bytes(operator_key)

    stage_receipt = tmp_path / "staged.json"
    code = stage_mod.main(
        [
            "--mode",
            "stage",
            "--fake-service",
            "--local-root",
            str(root),
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
    _assert_no_credentials(staged)

    approval_path = tmp_path / "approval.json"
    code = stage_mod.main(
        [
            "--mode",
            "sign",
            "--local-root",
            str(root),
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
            "--local-root",
            str(root),
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


def test_cli_sign_rejects_agent_approver(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
    operator_key: bytes,
    tmp_path: Path,
) -> None:
    root, _ = release_tree
    bases_path = tmp_path / "bases.json"
    bases_path.write_text(json.dumps(bases), encoding="utf-8")
    key_path = tmp_path / "operator.key"
    key_path.write_bytes(operator_key)
    code = stage_mod.main(
        [
            "--mode",
            "sign",
            "--local-root",
            str(root),
            "--base-revisions-file",
            str(bases_path),
            "--operator-key-file",
            str(key_path),
            "--approver",
            "agent-supervisor",
            "--approval-out",
            str(tmp_path / "bad.json"),
        ]
    )
    assert code == 1


def test_plan_only_manifest_enumerated_files(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
) -> None:
    root, manifest = release_tree
    # Extra file on disk not in manifest must not be planned.
    extra = root / "repos" / CANONICAL_REPOSITORY_NAMES[0] / "EXTRA.bin"
    extra.write_bytes(b"not-in-manifest")
    plan = plan_stage_from_local_root(local_root=root, base_revisions=bases)
    planned_paths = {a.relative_path for a in plan.artifacts}
    assert "repos/patent-legal-corpus/EXTRA.bin" not in planned_paths
    # Every planned path is in the manifest.
    manifest_paths = {
        str(e.get("relative_path") or e.get("path"))
        for e in manifest["artifacts"]
    }
    assert planned_paths <= manifest_paths


def test_stage_script_signature_defaults() -> None:
    sig = inspect.signature(stage_mod.main)
    # main accepts optional argv; parser default mode is dry-run.
    parser = stage_mod._parser()
    assert parser.get_default("mode") == "dry-run"
