"""Dry-run, retry, and append-only upload tests for IR release packaging."""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.huggingface.ir_publisher import (
    IRPublicationError,
    PublicationLease,
    build_upload_attempt,
    package_and_publish,
    plan_ir_dry_run,
    publish_ir_release,
    record_revocation_or_supersession,
    retry_partial_upload,
)
from ipfs_datasets_py.huggingface.ir_release import (
    IRPublicationPolicy,
    package_ir_release,
)
from ipfs_datasets_py.huggingface.publisher import (
    HuggingFacePublicationError,
    PublicationApproval,
)


def _inputs() -> dict:
    return {
        "checkpoint_authority": True,
        "checkpoint_digest": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        "checkpoint_id": "irck:publish-admitted",
        "checkpoint_lifecycle_state": "promoted",
        "compiler_identity": "COMPILER-CURRENT-1",
        "corpus_root": "bafkreiha35x7mcukzzb5x67hmykwsny5wipf5jb4do5gpsl24mxvix55n4",
        "decompiler_identity": "DECOMPILER-CURRENT-1",
        "derived_count": 9,
        "evaluation_root": "baguqeeraf3mevd4zrpkcy6hmsamfyszkq5zeisq2ipu6bvupquprtfqi53ta",
        "loss_configuration_identity": "IRLossConfiguration@1",
        "promotion_decision": "promote",
        "promotion_receipt": "RESULT(PGIR-072)",
        "proof_root": "bafkreiedk7zooeftd4qnhysbuazs6ulntis3ixn5vye6q7bgtxgrdlrfna",
        "source_count": 3,
        "split_root": "sha256:047b263b85067aa3dad6760f623c2855fbaf776d565ec9c273c49425fcc14eb4",
    }


class _FakeHfApi:
    def __init__(self, commit_sha: str = "a" * 40, fail_once: bool = False) -> None:
        self.commit_sha = commit_sha
        self.fail_once = fail_once
        self.calls: list[dict] = []

    def create_commit(self, **kwargs):
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("simulated transport failure")
        self.calls.append(kwargs)
        operations = kwargs.get("operations") or []
        assert operations, "create_commit must receive operations"
        for op in operations:
            path = getattr(op, "path_in_repo", None) or op.get("path_in_repo")
            assert path and not path.startswith("/")
            assert ".." not in path
            assert not path.startswith("data/abby_voice")
        return {"commit_sha": self.commit_sha}


def _lease(policy: IRPublicationPolicy) -> PublicationLease:
    return PublicationLease(
        fence=policy.lease_fence,
        lease_id="lease-fixture-001",
        holder="release-packager",
        repository_id=policy.repository_id,
    )


def test_dry_run_is_deterministic_and_contacts_no_write_endpoint(tmp_path: Path) -> None:
    package = package_ir_release(output_dir=tmp_path / "pkg", inputs=_inputs())
    policy = IRPublicationPolicy(repository_id=package.repository_id)
    plan_a, wrapped_a = plan_ir_dry_run(package, policy=policy)
    plan_b, wrapped_b = plan_ir_dry_run(package, policy=policy)
    assert plan_a.plan_digest == plan_b.plan_digest
    assert plan_a.remote_write_contacted is False
    assert wrapped_a["remote_write_contacted"] is False
    assert wrapped_a["schema"] == "ir-hf-publication-plan/v1"
    assert all(op.operation == "add" for op in plan_a.operations)
    assert all(
        op.remote_path.startswith(f"data/ir_learning/{plan_a.release_id}/")
        for op in plan_a.operations
    )
    receipt = publish_ir_release(package, policy=policy, dry_run=True)
    assert receipt["status"] == "dry_run_only"
    assert receipt["remote_write_performed"] is False
    assert receipt["tokens_persisted"] is False
    assert receipt["remote_revision"] == ""
    assert receipt["source_count"] == 3
    assert receipt["derived_count"] == 9


def test_publish_requires_lease_and_approval(tmp_path: Path) -> None:
    package = package_ir_release(output_dir=tmp_path / "pkg", inputs=_inputs())
    policy = IRPublicationPolicy(repository_id=package.repository_id)
    with pytest.raises(IRPublicationError, match="PublicationApproval"):
        publish_ir_release(package, policy=policy, dry_run=False, api=_FakeHfApi())
    plan, _ = plan_ir_dry_run(package, policy=policy)
    approval = PublicationApproval(
        approver="release-operator@example.com",
        plan_digest=plan.plan_digest,
        max_cost_usd=10.0,
        max_upload_bytes=plan.cost_receipt["upload_bytes"],
        credentials_scope="dataset:write:Publicus/proof-grounded-ir-learning",
        approval_id="approval-fixture-001",
    )
    with pytest.raises(IRPublicationError, match="lease"):
        publish_ir_release(
            package, policy=policy, dry_run=False, approval=approval, api=_FakeHfApi()
        )


def test_approved_append_only_upload_captures_remote_revision(tmp_path: Path) -> None:
    package = package_ir_release(output_dir=tmp_path / "pkg", inputs=_inputs())
    policy = IRPublicationPolicy(repository_id=package.repository_id)
    plan, _ = plan_ir_dry_run(package, policy=policy)
    approval = PublicationApproval(
        approver="release-operator@example.com",
        plan_digest=plan.plan_digest,
        max_cost_usd=10.0,
        max_upload_bytes=plan.cost_receipt["upload_bytes"],
        credentials_scope="dataset:write:Publicus/proof-grounded-ir-learning",
        approval_id="approval-fixture-002",
    )
    api = _FakeHfApi(commit_sha="b" * 40)
    receipt = publish_ir_release(
        package,
        policy=policy,
        dry_run=False,
        approval=approval,
        lease=_lease(policy),
        api=api,
        receipt_path=tmp_path / "receipt.json",
    )
    assert receipt["remote_revision"] == "b" * 40
    assert receipt["evidence"]["remote_revision_captured"] is True
    assert receipt["status"] == "published_pending_promotion"
    assert receipt["append_only"] is True
    assert len(api.calls) == 1
    assert (tmp_path / "receipt.json").is_file()


def test_partial_upload_retry_skips_exact_matches_only(tmp_path: Path) -> None:
    package = package_ir_release(output_dir=tmp_path / "pkg", inputs=_inputs())
    policy = IRPublicationPolicy(repository_id=package.repository_id)
    full_plan, _ = plan_ir_dry_run(package, policy=policy)
    first = full_plan.operations[0]
    rest = full_plan.operations[1:]
    attempt = build_upload_attempt(
        plan=full_plan,
        uploaded_paths=[first.remote_path],
        attempt_index=1,
    )
    assert first.remote_path in attempt["uploaded_digests"]
    assert len(attempt["remaining_paths"]) == len(rest)

    residual_plan, _ = plan_ir_dry_run(
        package,
        policy=policy,
        existing_remote_digests=attempt["uploaded_digests"],
    )
    approval = PublicationApproval(
        approver="release-operator@example.com",
        plan_digest=residual_plan.plan_digest,
        max_cost_usd=10.0,
        max_upload_bytes=residual_plan.cost_receipt["upload_bytes"],
        credentials_scope="dataset:write:Publicus/proof-grounded-ir-learning",
        approval_id="approval-fixture-003",
    )
    api = _FakeHfApi(commit_sha="c" * 40)
    receipt = retry_partial_upload(
        package,
        previous_attempt=attempt,
        approval=approval,
        lease=_lease(policy),
        policy=policy,
        api=api,
        remote_digests=attempt["uploaded_digests"],
    )
    uploaded = receipt["commit_receipt"]["uploaded_paths"]
    assert first.remote_path not in uploaded
    assert all(path in {item.remote_path for item in rest} for path in uploaded)
    assert receipt["remote_revision"] == "c" * 40


def test_retry_refuses_digest_mismatch_overwrite(tmp_path: Path) -> None:
    package = package_ir_release(output_dir=tmp_path / "pkg", inputs=_inputs())
    policy = IRPublicationPolicy(repository_id=package.repository_id)
    plan, _ = plan_ir_dry_run(package, policy=policy)
    first = plan.operations[0]
    approval = PublicationApproval(
        approver="release-operator@example.com",
        plan_digest=plan.plan_digest,
        max_cost_usd=10.0,
        max_upload_bytes=plan.cost_receipt["upload_bytes"],
        credentials_scope="dataset:write:Publicus/proof-grounded-ir-learning",
        approval_id="approval-fixture-004",
    )
    with pytest.raises((IRPublicationError, HuggingFacePublicationError), match="overwrite"):
        publish_ir_release(
            package,
            policy=policy,
            dry_run=False,
            approval=approval,
            lease=_lease(policy),
            api=_FakeHfApi(),
            existing_remote_paths=(first.remote_path,),
            existing_remote_digests={first.remote_path: "d" * 64},
        )


def test_idempotent_rerun_skips_identical_remote_objects(tmp_path: Path) -> None:
    package = package_ir_release(output_dir=tmp_path / "pkg", inputs=_inputs())
    policy = IRPublicationPolicy(repository_id=package.repository_id)
    plan, _ = plan_ir_dry_run(package, policy=policy)
    exact = {item.remote_path: item.sha256 for item in plan.operations}
    approval = PublicationApproval(
        approver="release-operator@example.com",
        plan_digest=plan.plan_digest,
        max_cost_usd=10.0,
        max_upload_bytes=plan.cost_receipt["upload_bytes"],
        credentials_scope="dataset:write:Publicus/proof-grounded-ir-learning",
        approval_id="approval-fixture-005",
    )
    api = _FakeHfApi(commit_sha="e" * 40)
    receipt = publish_ir_release(
        package,
        policy=policy,
        dry_run=False,
        approval=approval,
        lease=_lease(policy),
        api=api,
        existing_remote_digests=exact,
    )
    assert receipt["status"] == "idempotent_already_published"
    assert api.calls == []
    assert receipt["remote_write_performed"] is False


def test_basename_collision_does_not_skip_upload(tmp_path: Path) -> None:
    package = package_ir_release(output_dir=tmp_path / "pkg", inputs=_inputs())
    policy = IRPublicationPolicy(repository_id=package.repository_id)
    plan, _ = plan_ir_dry_run(
        package,
        policy=policy,
        existing_remote_paths=("legacy/README.md",),
    )
    remotes = {item.remote_path for item in plan.operations}
    assert any(path.endswith("README.md") for path in remotes)
    assert plan.skipped_exact_matches == ()


def test_revocation_retains_previous_release(tmp_path: Path) -> None:
    record = record_revocation_or_supersession(
        previous_release_id="sha256-old",
        previous_commit_sha="f" * 40,
        reason="superseded by qualified successor",
        output_path=tmp_path / "revocation.json",
        successor_release_id="sha256-new",
        successor_commit_sha="1" * 40,
    )
    assert record["previous_release_retained"] is True
    assert record["kind"] == "supersession"
    assert (tmp_path / "revocation.json").is_file()


def test_lease_fence_must_match_repository() -> None:
    with pytest.raises(IRPublicationError, match="fence"):
        PublicationLease(
            fence="hf-publication:other/repo",
            lease_id="x",
            holder="y",
            repository_id="Publicus/proof-grounded-ir-learning",
        )


def test_package_and_publish_dry_run_entrypoint(tmp_path: Path) -> None:
    receipt = package_and_publish(
        output_dir=tmp_path / "pkg",
        inputs=_inputs(),
        dry_run=True,
    )
    assert receipt["status"] == "dry_run_only"
    assert receipt["schema"] == "ir-hf-publication-receipt/v1"
    assert receipt["tokens_persisted"] is False
