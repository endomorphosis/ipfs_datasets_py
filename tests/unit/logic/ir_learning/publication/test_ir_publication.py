"""Dry-run, retry, and append-only upload tests for IR release packaging."""

from __future__ import annotations

import json
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
    parent_commit = "1" * 40

    def __init__(self, commit_sha: str = "a" * 40, fail_once: bool = False) -> None:
        self.commit_sha = commit_sha
        self.fail_once = fail_once
        self.calls: list[dict] = []

    def repo_info(self, *, repo_id, repo_type, revision):
        assert repo_type == "dataset"
        assert revision == "main"
        return {"sha": self.parent_commit}

    def get_paths_info(self, *, repo_id, repo_type, revision, paths):
        assert revision == self.parent_commit
        return []

    def create_commit(self, **kwargs):
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("simulated transport failure")
        self.calls.append(kwargs)
        assert kwargs["parent_commit"] == self.parent_commit
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
    api = _FakeHfApi(commit_sha="b" * 40)
    plan, _ = plan_ir_dry_run(
        package, policy=policy, audited_parent_commit=api.parent_commit
    )
    approval = PublicationApproval(
        approver="release-operator@example.com",
        plan_digest=plan.plan_digest,
        max_cost_usd=10.0,
        max_upload_bytes=plan.cost_receipt["upload_bytes"],
        credentials_scope="dataset:write:Publicus/proof-grounded-ir-learning",
        approval_id="approval-fixture-002",
    )
    receipt = publish_ir_release(
        package,
        policy=policy,
        dry_run=False,
        approval=approval,
        lease=_lease(policy),
        api=api,
        audited_parent_commit=api.parent_commit,
        receipt_path=tmp_path / "receipt.json",
    )
    assert receipt["remote_revision"] == "b" * 40
    assert receipt["evidence"]["remote_revision_captured"] is True
    assert receipt["post_publication_verification"] is None
    assert receipt["pinned_redownload_validation"] is None
    assert receipt["evidence"]["immutable_remote_readback_verified"] is False
    assert receipt["status"] == "published_pending_promotion"
    assert receipt["append_only"] is True
    assert len(api.calls) == 1
    assert (tmp_path / "receipt.json").is_file()


@pytest.mark.parametrize(
    "readback",
    [
        "cache_only",
        "offline_payloads",
        "without_inventory",
        "callback_with_inventory",
        "client_transport",
        "client_with_inventory",
        "corrupt_client_payload",
        "corrupt_without_receipt_path",
        "client_interrupted",
        "receipt_checkpoint_error",
        "private_cache_label",
        "invalid_lease_receipt",
        "empty_inventory",
        "unbound_inventory",
    ],
)
def test_ir_readback_requires_independent_immutable_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, readback: str
) -> None:
    package = package_ir_release(output_dir=tmp_path / "pkg", inputs=_inputs())
    policy = IRPublicationPolicy(repository_id=package.repository_id)
    api = _FakeHfApi(commit_sha="d" * 40)
    plan, _ = plan_ir_dry_run(
        package, policy=policy, audited_parent_commit=api.parent_commit
    )
    approval = PublicationApproval(
        approver="release-operator@example.com",
        plan_digest=plan.plan_digest,
        max_cost_usd=10.0,
        max_upload_bytes=plan.cost_receipt["upload_bytes"],
        credentials_scope="dataset:write:Publicus/proof-grounded-ir-learning",
        approval_id="approval-fixture-readback",
    )
    payloads = {
        item.remote_path: (Path(package.output_dir) / item.relative_path).read_bytes()
        for item in plan.operations
    }
    observations = {
        item.remote_path: {
            "commit_sha": api.commit_sha,
            "sha256": item.sha256,
            "size_bytes": item.size_bytes,
        }
        for item in plan.operations
    }
    fetched: list[str] = []
    receipt_path = tmp_path / "receipt.json"
    if readback == "receipt_checkpoint_error":
        receipt_path.mkdir()

    def check_checkpoint():
        saved = json.loads(receipt_path.read_bytes())
        assert saved["status"] == "published_pending_readback"
        assert saved["remote_revision"] == api.commit_sha
        assert saved["commit_receipt"]["plan_digest"] == plan.plan_digest
        assert saved["evidence"]["immutable_remote_readback_verified"] is False

    def fetch(repo_id: str, revision: str, path: str) -> bytes:
        assert repo_id == policy.repository_id
        assert revision == api.commit_sha
        fetched.append(path)
        return payloads[path]

    use_client = readback in {
        "client_transport", "client_with_inventory", "corrupt_client_payload",
        "corrupt_without_receipt_path", "client_interrupted", "receipt_checkpoint_error",
        "private_cache_label",
    }
    if use_client:
        get_parent_paths = api.get_paths_info

        def get_paths_info(*, repo_id, repo_type, revision, paths):
            if revision == api.parent_commit:
                return get_parent_paths(
                    repo_id=repo_id, repo_type=repo_type, revision=revision, paths=paths
                )
            assert revision == api.commit_sha
            assert len(api.calls) == 1
            return [
                {"path": path, "size": len(payloads[path]), "lfs": observations[path]}
                for path in paths
            ]

        def hf_hub_download(
            *, repo_id, repo_type, revision, filename, local_dir, force_download
        ):
            assert repo_type == "dataset"
            assert force_download is True
            target = local_dir / filename
            payload = fetch(repo_id, revision, filename)
            if readback != "corrupt_without_receipt_path":
                check_checkpoint()
            if readback == "client_interrupted":
                raise KeyboardInterrupt
            if readback in {"corrupt_client_payload", "corrupt_without_receipt_path"}:
                payload += b"!"
            target.write_bytes(payload)
            return target

        monkeypatch.setattr(api, "get_paths_info", get_paths_info)
        monkeypatch.setattr(api, "hf_hub_download", hf_hub_download, raising=False)

    use_fetch = readback in {"without_inventory", "callback_with_inventory"}
    has_inventory = readback in {
        "offline_payloads", "callback_with_inventory", "client_transport",
        "client_with_inventory",
    }
    supplied_objects = (
        observations
        if readback in {"offline_payloads", "callback_with_inventory", "client_with_inventory"}
        else None
    )
    if readback == "empty_inventory":
        supplied_objects = {}
    if readback == "unbound_inventory":
        supplied_objects = {
            path: {"sha256": row["sha256"], "size_bytes": row["size_bytes"]}
            for path, row in observations.items()
        }

    cache = tmp_path / ("bearer marker" if readback == "private_cache_label" else "verified-cache")
    publish_args = dict(
        policy=policy,
        dry_run=False,
        approval=approval,
        lease=_lease(policy),
        api=api,
        audited_parent_commit=api.parent_commit,
        remote_objects=supplied_objects,
        remote_payloads=payloads if readback == "offline_payloads" else None,
        verified_cache_root=cache,
        fetch_bytes=fetch if use_fetch else None,
        receipt_path=None if readback == "corrupt_without_receipt_path" else receipt_path,
    )
    if readback == "invalid_lease_receipt":
        publish_args["lease"] = PublicationLease(
            fence=policy.lease_fence,
            lease_id="hf_" + "x" * 32,
            holder="offline fixture",
            repository_id=policy.repository_id,
        )
        with pytest.raises(HuggingFacePublicationError, match="credentials must never appear"):
            publish_ir_release(package, **publish_args)
        assert not api.calls and not receipt_path.exists()
        return

    if readback == "client_interrupted":
        with pytest.raises(KeyboardInterrupt):
            publish_ir_release(package, **publish_args)
        check_checkpoint()
        assert len(api.calls) == 1
        return

    blocked_stage = {
        "empty_inventory": "post_publication_verification",
        "unbound_inventory": "post_publication_verification",
        "corrupt_client_payload": "pinned_redownload_validation",
        "corrupt_without_receipt_path": "pinned_redownload_validation",
        "receipt_checkpoint_error": "receipt_checkpoint",
        "private_cache_label": "pinned_redownload_validation",
    }.get(readback)
    if blocked_stage:
        with pytest.raises(IRPublicationError) as error:
            publish_ir_release(package, **publish_args)
        assert len(api.calls) == 1
        blocked = error.value.receipt
        assert blocked["status"] == "blocked_remote_write_gate"
        assert blocked["blocked_stage"] == blocked_stage
        assert blocked["remote_revision"] == api.commit_sha
        assert blocked["commit_receipt"]["plan_digest"] == plan.plan_digest
        assert blocked["remote_write_performed"] is True
        assert blocked["evidence"]["immutable_remote_readback_verified"] is False
        assert blocked["pinned_redownload_validation"] is None
        assert (blocked["post_publication_verification"] is not None) is (
            blocked_stage == "pinned_redownload_validation"
        )
        if readback == "corrupt_without_receipt_path":
            assert not receipt_path.exists()
        elif readback == "receipt_checkpoint_error":
            assert error.value.__notes__
            assert not fetched and not cache.exists()
        else:
            assert json.loads(receipt_path.read_bytes()) == blocked
        return

    receipt = publish_ir_release(package, **publish_args)
    assert json.loads(receipt_path.read_bytes()) == receipt
    assert receipt["status"] == "published_pending_promotion"
    assert len(api.calls) == 1
    assert (receipt["post_publication_verification"] is not None) is has_inventory
    assert receipt["evidence"]["immutable_remote_readback_verified"] is use_client
    validation = receipt["pinned_redownload_validation"]
    if readback == "cache_only":
        assert validation is None
        assert not cache.exists()
    else:
        assert validation["ok"] is True
        assert validation["network_fetch_performed"] is (use_fetch or use_client)
        assert validation["revalidated_paths"] == list(payloads)
    assert set(fetched) == (set(payloads) if use_fetch or use_client else set())


def test_partial_upload_retry_plans_exact_skips_but_refuses_live_resume(tmp_path: Path) -> None:
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
    assert residual_plan.skipped_exact_matches == (first.remote_path,)
    assert residual_plan.operations == rest
    with pytest.raises(IRPublicationError, match="skipped exact matches"):
        retry_partial_upload(
            package,
            previous_attempt=attempt,
            approval=approval,
            lease=_lease(policy),
            policy=policy,
            api=api,
            remote_digests=attempt["uploaded_digests"],
        )
    assert api.calls == []


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
