"""Dry-run, retry, and append-only upload tests for IR release packaging."""

from __future__ import annotations

import hashlib
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

AUDITED_PARENT = "9" * 40


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
    """Inert remote-byte transport; it makes no actual Hub/network claim."""

    def __init__(self, commit_sha: str = "a" * 40, fail_once: bool = False,
                 *, parent_commit: str = AUDITED_PARENT, existing_payloads=None) -> None:
        self.commit_sha = commit_sha
        self.parent_commit = parent_commit
        self.fail_once = fail_once
        self.calls: list[dict] = []
        self.read_calls: list[dict] = []
        self.existing_payloads = dict(existing_payloads or {})
        self.payloads: dict[str, bytes] = {}

    def repo_info(self, **kwargs):
        self.read_calls.append({"method": "repo_info", **kwargs})
        return {"sha": self.parent_commit}

    def get_paths_info(self, **kwargs):
        self.read_calls.append({"method": "get_paths_info", **kwargs})
        revision = kwargs["revision"]
        assert revision in (self.parent_commit, self.commit_sha)
        stored = self.payloads if revision == self.commit_sha else self.existing_payloads
        return [
            {"path": path, "size": len(payload),
             "lfs": {"sha256": hashlib.sha256(payload).hexdigest()}}
            for path, payload in stored.items()
            if any(path == requested or path.startswith(requested + "/")
                   for requested in kwargs["paths"])
        ]

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
            source = getattr(op, "path_or_fileobj", None)
            if source is None:
                source = op["path_or_fileobj"]
            if hasattr(source, "read"):
                position = source.tell()
                source.seek(0)
                self.payloads[path] = source.read()
                source.seek(position)
            else:
                self.payloads[path] = Path(source).read_bytes()
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
    plan, _ = plan_ir_dry_run(package, policy=policy, audited_parent_commit=AUDITED_PARENT)
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
    plan, _ = plan_ir_dry_run(package, policy=policy, audited_parent_commit=AUDITED_PARENT)
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
        audited_parent_commit=AUDITED_PARENT,
    )
    assert receipt["remote_revision"] == "b" * 40
    assert receipt["evidence"]["remote_revision_captured"] is True
    assert receipt["status"] == "published_pending_promotion"
    assert receipt["append_only"] is True
    assert len(api.calls) == 1
    assert (tmp_path / "receipt.json").is_file()


def test_partial_upload_retry_skips_exact_matches_only(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.huggingface.publisher import HuggingFaceReleasePublisher

    # Caller-supplied digest observations exercise residual planning. This is
    # not a live resume of a claimed prefix; the strict prefix case is below.
    package = package_ir_release(output_dir=tmp_path / "pkg", inputs=_inputs())
    policy = IRPublicationPolicy(repository_id=package.repository_id)
    full_plan, _ = plan_ir_dry_run(package, policy=policy, audited_parent_commit=AUDITED_PARENT)
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
        audited_parent_commit=AUDITED_PARENT,
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
    pointer_calls = []
    def no_pointer(*args, **kwargs):
        pointer_calls.append((args, kwargs))
        pytest.fail("a refused residual plan must never advance a selected pointer")
    monkeypatch.setattr(HuggingFaceReleasePublisher, "canary_promote_pointer", no_pointer)
    # Residual planning remains useful, but the genuine live owner requires a
    # fresh immutable prefix and refuses skipped-match plans before any API.
    with pytest.raises(IRPublicationError, match="fresh release prefix") as raised:
        retry_partial_upload(
            package,
            previous_attempt=attempt,
            approval=approval,
            lease=_lease(policy),
            policy=policy,
            api=api,
            remote_digests=attempt["uploaded_digests"],
            audited_parent_commit=AUDITED_PARENT,
        )
    assert api.calls == api.read_calls == []
    assert api.payloads == {} and raised.value.receipt is None
    assert pointer_calls == []


def test_retry_refuses_digest_mismatch_overwrite(tmp_path: Path) -> None:
    package = package_ir_release(output_dir=tmp_path / "pkg", inputs=_inputs())
    policy = IRPublicationPolicy(repository_id=package.repository_id)
    plan, _ = plan_ir_dry_run(package, policy=policy, audited_parent_commit=AUDITED_PARENT)
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
            audited_parent_commit=AUDITED_PARENT,
        )


def test_idempotent_rerun_skips_identical_remote_objects(tmp_path: Path) -> None:
    package = package_ir_release(output_dir=tmp_path / "pkg", inputs=_inputs())
    policy = IRPublicationPolicy(repository_id=package.repository_id)
    plan, _ = plan_ir_dry_run(package, policy=policy, audited_parent_commit=AUDITED_PARENT)
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
        audited_parent_commit=AUDITED_PARENT,
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


def _approved_case(tmp_path: Path, *, target_revision: str = "main"):
    package = package_ir_release(output_dir=tmp_path / "pkg", inputs=_inputs())
    policy = IRPublicationPolicy(repository_id=package.repository_id)
    plan, _ = plan_ir_dry_run(package, policy=policy,
        audited_parent_commit=AUDITED_PARENT, target_revision=target_revision)
    approval = PublicationApproval(approver="fixture-release-reviewer",
        plan_digest=plan.plan_digest, max_cost_usd=10.0,
        max_upload_bytes=plan.cost_receipt["upload_bytes"],
        credentials_scope="dataset:write:Publicus/proof-grounded-ir-learning",
        approval_id="explicit-readback-fixture-approval")
    return package, policy, plan, approval


class _DownloadingFakeHfApi(_FakeHfApi):
    def __init__(self, *, fault=None, **kwargs):
        super().__init__(**kwargs)
        self.fault = fault
        self.download_calls = []

    def hf_hub_download(self, **kwargs):
        self.download_calls.append(kwargs)
        assert kwargs["revision"] == self.commit_sha
        assert kwargs["force_download"] is True
        if self.fault == "raises":
            raise RuntimeError("sensitive provider detail must not enter a receipt")
        payload = b"wrong remote body" if self.fault == "wrong-bytes" else self.payloads[kwargs["filename"]]
        path = Path(kwargs["local_dir"]) / kwargs["filename"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return str(path)


def test_live_publish_missing_audited_parent_refuses_before_remote_contact(tmp_path):
    package = package_ir_release(output_dir=tmp_path / "pkg", inputs=_inputs())
    policy = IRPublicationPolicy(repository_id=package.repository_id)
    plan, _ = plan_ir_dry_run(package, policy=policy)
    approval = PublicationApproval(approver="fixture-reviewer", plan_digest=plan.plan_digest,
        max_cost_usd=10.0, max_upload_bytes=plan.cost_receipt["upload_bytes"],
        credentials_scope="dataset:write:Publicus/proof-grounded-ir-learning", approval_id="missing-parent-fixture")
    api = _FakeHfApi()
    with pytest.raises(IRPublicationError, match="audited_parent_commit"):
        publish_ir_release(package, policy=policy, dry_run=False,
            approval=approval, lease=_lease(policy), api=api)
    assert api.calls == api.read_calls == []


def test_default_inventory_uses_exact_repository_and_returned_commit_without_promotion(tmp_path, monkeypatch):
    from ipfs_datasets_py.huggingface.publisher import HuggingFaceReleasePublisher

    def no_pointer(*args, **kwargs):
        pytest.fail("publication/readback must not advance a selected pointer")
    monkeypatch.setattr(HuggingFaceReleasePublisher, "canary_promote_pointer", no_pointer)
    package, policy, plan, approval = _approved_case(tmp_path, target_revision="main")
    api = _FakeHfApi(commit_sha="b" * 40)
    receipt = publish_ir_release(package, policy=policy, dry_run=False, approval=approval,
        lease=_lease(policy), api=api, audited_parent_commit=AUDITED_PARENT,
        target_revision="main")
    assert api.calls[0]["parent_commit"] == AUDITED_PARENT
    assert api.calls[0]["revision"] == "main"
    parent_reads = [call for call in api.read_calls if call["method"] == "repo_info"]
    assert parent_reads == [{"method": "repo_info", "repo_id": policy.repository_id,
        "repo_type": "dataset", "revision": "main"}]
    inventory = [call for call in api.read_calls
                 if call["method"] == "get_paths_info" and call["revision"] == api.commit_sha]
    assert inventory and all(call["repo_id"] == policy.repository_id and call["repo_type"] == "dataset"
                             for call in inventory)
    assert {path for call in inventory for path in call["paths"]} == {item.remote_path for item in plan.operations}
    assert receipt["post_publication_verification"]["ok"] is True
    assert receipt["readback_sources"] == {"inventory": "publisher_adapter", "pinned_payloads": "not_requested"}
    assert receipt["pinned_redownload_validation"] is None
    assert receipt["status"] == "published_pending_promotion"


def test_parent_race_and_real_existing_prefix_remain_fail_closed(tmp_path):
    package, policy, plan, approval = _approved_case(tmp_path)
    first = plan.operations[0]
    for api in [_FakeHfApi(parent_commit="8" * 40),
                _FakeHfApi(existing_payloads={first.remote_path: b"retained existing release body"})]:
        with pytest.raises(IRPublicationError, match="write outcome unverified"):
            publish_ir_release(package, policy=policy, dry_run=False, approval=approval,
                lease=_lease(policy), api=api, audited_parent_commit=AUDITED_PARENT)
        assert api.calls == []


def test_explicit_empty_inventory_never_falls_back_to_local_plan(tmp_path):
    package, policy, _, approval = _approved_case(tmp_path)
    api = _FakeHfApi(commit_sha="c" * 40)
    path = tmp_path / "blocked-readback.json"
    with pytest.raises(IRPublicationError) as raised:
        publish_ir_release(package, policy=policy, dry_run=False, approval=approval,
            lease=_lease(policy), api=api, audited_parent_commit=AUDITED_PARENT,
            remote_objects={}, receipt_path=path)
    receipt = json.loads(path.read_bytes())
    assert receipt == raised.value.receipt
    assert len(api.calls) == 1 and receipt["remote_revision"] == api.commit_sha
    assert receipt["status"] == "blocked_remote_write_gate"
    assert receipt["readback_sources"]["inventory"] == "supplied_observations"
    assert receipt["readback_failure"]["stage"] == "post_publication_verification"
    assert receipt["readback_failure"]["automatic_retry_authorized"] is False
    assert receipt["readback_failure"]["pointer_advanced"] is False


@pytest.mark.parametrize("fault", ["raises", "missing", "wrong-digest"])
def test_inventory_failure_preserves_returned_commit_and_blocks_readback(tmp_path, fault):
    package, policy, _, approval = _approved_case(tmp_path)
    class BrokenInventory(_FakeHfApi):
        def get_paths_info(self, **kwargs):
            if kwargs["revision"] == self.commit_sha:
                if fault == "raises":
                    raise RuntimeError("sensitive provider detail must not enter a receipt")
                if fault == "missing":
                    return []
                records = super().get_paths_info(**kwargs)
                records[0]["lfs"]["sha256"] = "0" * 64
                return records
            return super().get_paths_info(**kwargs)
    api = BrokenInventory(commit_sha="d" * 40)
    target = tmp_path / "failed-readback.json"
    with pytest.raises(IRPublicationError) as raised:
        publish_ir_release(package, policy=policy, dry_run=False, approval=approval,
            lease=_lease(policy), api=api, audited_parent_commit=AUDITED_PARENT, receipt_path=target)
    receipt = raised.value.receipt
    assert json.loads(target.read_bytes()) == receipt
    assert len(api.calls) == 1 and receipt["remote_revision"] == api.commit_sha
    assert receipt["remote_write_performed"] is True
    assert receipt["commit_receipt"]["parent_commit"] == AUDITED_PARENT
    assert receipt["status"] == "blocked_remote_write_gate"
    assert receipt["pinned_redownload_validation"] is None
    assert "sensitive provider detail" not in str(raised.value) + json.dumps(receipt)
    assert raised.value.__suppress_context__ is True


@pytest.mark.parametrize("fault", ["wrong-bytes", "raises"])
def test_requested_pinned_cache_uses_remote_downloader_never_local_package_fallback(tmp_path, fault):
    package, policy, _, approval = _approved_case(tmp_path)
    api = _DownloadingFakeHfApi(commit_sha="e" * 40, fault=fault)
    cache = tmp_path / "verified-cache"
    with pytest.raises(IRPublicationError) as raised:
        publish_ir_release(package, policy=policy, dry_run=False, approval=approval,
            lease=_lease(policy), api=api, audited_parent_commit=AUDITED_PARENT,
            verified_cache_root=cache, receipt_path=tmp_path / "failed-fetch.json")
    receipt = raised.value.receipt
    assert len(api.calls) == 1 and api.download_calls
    assert receipt["remote_revision"] == api.commit_sha
    assert receipt["post_publication_verification"]["ok"] is True
    assert receipt["pinned_redownload_validation"] is None
    assert receipt["readback_failure"]["stage"] == "pinned_redownload"
    assert receipt["status"] == "blocked_remote_write_gate"
    assert receipt["readback_sources"]["pinned_payloads"] == "publisher_adapter"
    assert "sensitive provider detail" not in str(raised.value) + json.dumps(receipt)


def test_pinned_adapter_success_remains_pending_promotion(tmp_path):
    package, policy, plan, approval = _approved_case(tmp_path)
    api = _DownloadingFakeHfApi(commit_sha="f" * 40)
    cache = tmp_path / "verified-cache"
    receipt = publish_ir_release(package, policy=policy, dry_run=False, approval=approval,
        lease=_lease(policy), api=api, audited_parent_commit=AUDITED_PARENT, verified_cache_root=cache)
    assert len(api.calls) == 1
    assert len(api.download_calls) == len(plan.operations)
    assert receipt["pinned_redownload_validation"]["ok"] is True
    assert receipt["pinned_redownload_validation"]["commit_sha"] == api.commit_sha
    assert receipt["status"] == "published_pending_promotion"
    assert all((cache / path).read_bytes() == payload for path, payload in api.payloads.items())


def test_explicit_fixture_observations_are_preserved_and_identified(tmp_path):
    package, policy, plan, approval = _approved_case(tmp_path)
    api = _FakeHfApi(commit_sha="1" * 40)
    objects = {item.remote_path: {"sha256": item.sha256, "size_bytes": item.size_bytes,
               "commit_sha": api.commit_sha} for item in plan.operations}
    payloads = {item.remote_path: (Path(package.output_dir) / item.relative_path).read_bytes()
                for item in plan.operations}
    receipt = publish_ir_release(package, policy=policy, dry_run=False, approval=approval,
        lease=_lease(policy), api=api, audited_parent_commit=AUDITED_PARENT,
        remote_objects=objects, remote_payloads=payloads, verified_cache_root=tmp_path / "fixture-cache")
    assert not [call for call in api.read_calls if call["revision"] == api.commit_sha]
    assert receipt["readback_sources"] == {"inventory": "supplied_observations", "pinned_payloads": "supplied_observations"}
    assert receipt["pinned_redownload_validation"]["network_fetch_performed"] is False
    assert receipt["status"] == "published_pending_promotion"


def test_explicit_empty_payloads_remain_a_failed_fixture_observation(tmp_path):
    package, policy, _, approval = _approved_case(tmp_path)
    api = _FakeHfApi()
    with pytest.raises(IRPublicationError) as raised:
        publish_ir_release(package, policy=policy, dry_run=False, approval=approval,
            lease=_lease(policy), api=api, audited_parent_commit=AUDITED_PARENT,
            remote_payloads={}, verified_cache_root=tmp_path / "empty-payload-cache")
    assert raised.value.receipt["status"] == "blocked_remote_write_gate"
    assert raised.value.receipt["readback_failure"]["stage"] == "pinned_redownload"
    assert raised.value.receipt["readback_sources"]["pinned_payloads"] == "supplied_observations"
    assert len(api.calls) == 1


@pytest.mark.parametrize("entrypoint", ["retry", "package"])
def test_existing_wrappers_forward_exact_parent_revision_cache_and_fetch(tmp_path, entrypoint):
    package, policy, plan, approval = _approved_case(tmp_path, target_revision="main")
    api = _FakeHfApi(commit_sha="2" * 40)
    fetches = []
    def fetch(repo, commit, path):
        fetches.append((repo, commit, path))
        return api.payloads[path]
    options = dict(policy=policy, api=api, approval=approval, lease=_lease(policy),
        audited_parent_commit=AUDITED_PARENT, target_revision="main",
        verified_cache_root=tmp_path / "wrapper-cache", fetch_bytes=fetch,
        receipt_path=tmp_path / "wrapper-receipt.json")
    if entrypoint == "retry":
        receipt = retry_partial_upload(package,
            previous_attempt=build_upload_attempt(plan=plan), **options)
    else:
        receipt = package_and_publish(output_dir=tmp_path / "actual-package",
            inputs=_inputs(), dry_run=False, **options)
    assert len(api.calls) == 1
    assert api.calls[0]["parent_commit"] == AUDITED_PARENT and api.calls[0]["revision"] == "main"
    assert {path for _, _, path in fetches} == set(api.payloads)
    assert all((repo, commit) == (policy.repository_id, api.commit_sha) for repo, commit, _ in fetches)
    assert receipt["pinned_redownload_validation"]["ok"] is True
    assert receipt["status"] == "published_pending_promotion"
    assert json.loads((tmp_path / "wrapper-receipt.json").read_bytes()) == receipt


def test_failed_readback_keeps_commit_even_if_receipt_storage_fails(tmp_path, monkeypatch):
    from ipfs_datasets_py.huggingface import ir_publisher as module

    package, policy, _, approval = _approved_case(tmp_path)
    api = _FakeHfApi(commit_sha="3" * 40)
    def unavailable(*args, **kwargs):
        raise OSError("receipt storage unavailable")
    monkeypatch.setattr(module, "_write_receipt", unavailable)
    with pytest.raises(IRPublicationError) as raised:
        publish_ir_release(package, policy=policy, dry_run=False, approval=approval,
            lease=_lease(policy), api=api, audited_parent_commit=AUDITED_PARENT,
            remote_objects={}, receipt_path=tmp_path / "not-written.json")
    assert raised.value.receipt["remote_revision"] == api.commit_sha
    assert raised.value.receipt["readback_failure"]["receipt_write_error_type"] == "storage_error"
    assert raised.value.receipt["status"] == "blocked_remote_write_gate" and len(api.calls) == 1


@pytest.mark.parametrize("fault", ["receipt-construction", "receipt-storage"])
def test_successful_readback_finalization_failure_retains_commit_and_previous_receipt(tmp_path, monkeypatch, fault):
    from ipfs_datasets_py.huggingface import ir_publisher as module

    package, policy, plan, approval = _approved_case(tmp_path)
    api = _DownloadingFakeHfApi(commit_sha="4" * 40)
    target = tmp_path / "retained-receipt.json"
    previous = b'{"previous_receipt":"retained"}\n'
    target.write_bytes(previous)
    writes = []
    if fault == "receipt-construction":
        original = module._build_ir_receipt
        def fail_success_only(**kwargs):
            if kwargs["status"] == "published_pending_promotion":
                raise ValueError("sensitive finalization detail")
            return original(**kwargs)
        monkeypatch.setattr(module, "_build_ir_receipt", fail_success_only)
    def unavailable(path, receipt):
        writes.append((path, receipt["status"]))
        raise OSError("sensitive storage detail")
    monkeypatch.setattr(module, "_write_receipt", unavailable)
    with pytest.raises(IRPublicationError) as raised:
        publish_ir_release(package, policy=policy, dry_run=False, approval=approval,
            lease=_lease(policy), api=api, audited_parent_commit=AUDITED_PARENT,
            verified_cache_root=tmp_path / "finalization-cache", receipt_path=target)
    receipt = raised.value.receipt
    assert receipt["remote_revision"] == api.commit_sha
    assert receipt["commit_receipt"]["commit_sha"] == api.commit_sha
    assert receipt["post_publication_verification"]["ok"] is True
    assert receipt["pinned_redownload_validation"]["ok"] is True
    assert receipt["status"] == "blocked_remote_write_gate"
    assert receipt["readback_failure"]["stage"] == fault.replace("-", "_")
    assert receipt["readback_failure"]["receipt_write_error_type"] == "storage_error"
    assert receipt["readback_failure"]["automatic_retry_authorized"] is False
    assert receipt["readback_failure"]["pointer_advanced"] is False
    assert target.read_bytes() == previous and len(writes) == 1
    assert len(api.calls) == 1 and len(api.download_calls) == len(plan.operations)
    assert "sensitive" not in str(raised.value) + json.dumps(receipt)
    assert raised.value.__cause__ is None and raised.value.__suppress_context__ is True


def test_publish_transport_exception_suppresses_provider_text_and_keeps_outcome_unknown(tmp_path):
    import traceback

    package, policy, _, approval = _approved_case(tmp_path)
    detail = "Bearer fixture-only-not-a-credential"
    class UncertainCommit(_FakeHfApi):
        def create_commit(self, **kwargs):
            super().create_commit(**kwargs)
            raise RuntimeError(detail)
    api = UncertainCommit()
    target = tmp_path / "unknown-write.json"
    with pytest.raises(IRPublicationError, match="write outcome unverified") as raised:
        publish_ir_release(package, policy=policy, dry_run=False, approval=approval,
            lease=_lease(policy), api=api, audited_parent_commit=AUDITED_PARENT,
            receipt_path=target)
    assert len(api.calls) == 1 and api.payloads
    assert raised.value.receipt is None and not target.exists()
    assert raised.value.__cause__ is None and raised.value.__suppress_context__ is True
    assert detail not in "".join(traceback.format_exception(raised.value))
    assert "automatic retry not authorized" in str(raised.value)


@pytest.mark.parametrize("fault", ["inventory", "blocked-receipt-storage"])
def test_provider_exception_class_names_cannot_escape_failure_category_validation(tmp_path, monkeypatch, fault):
    from ipfs_datasets_py.huggingface import ir_publisher as module

    package, policy, _, approval = _approved_case(tmp_path)
    untrusted_name = "hf_" + "fixture_class_name_" * 4096
    UntrustedError = type(untrusted_name, (RuntimeError,), {})
    class BrokenInventory(_FakeHfApi):
        def get_paths_info(self, **kwargs):
            if kwargs["revision"] == self.commit_sha:
                raise UntrustedError("untrusted external detail")
            return super().get_paths_info(**kwargs)
    api = BrokenInventory()
    checked = []
    original = module._reject_secrets
    def checked_failure_metadata(value, **kwargs):
        if isinstance(value, dict) and "readback_failure" in value:
            checked.append(dict(value["readback_failure"]))
        return original(value, **kwargs)
    monkeypatch.setattr(module, "_reject_secrets", checked_failure_metadata)
    if fault == "blocked-receipt-storage":
        def unavailable(*args, **kwargs):
            raise UntrustedError("untrusted storage detail")
        monkeypatch.setattr(module, "_write_receipt", unavailable)
    with pytest.raises(IRPublicationError) as raised:
        publish_ir_release(package, policy=policy, dry_run=False, approval=approval,
            lease=_lease(policy), api=api, audited_parent_commit=AUDITED_PARENT,
            receipt_path=tmp_path / "bounded-failure.json")
    receipt = raised.value.receipt
    failure = receipt["readback_failure"]
    allowed_categories = {"timeout_error", "storage_error", "publication_validation_error",
                          "validation_error", "external_error"}
    assert failure["error_type"] in allowed_categories
    if fault == "blocked-receipt-storage":
        assert failure["receipt_write_error_type"] in allowed_categories
    assert checked[-1] == failure and len(json.dumps(failure)) < 256
    assert untrusted_name not in str(raised.value) + json.dumps(receipt)
    assert receipt["remote_revision"] == api.commit_sha and len(api.calls) == 1


def test_non_main_target_revision_remains_refused_without_remote_contact(tmp_path):
    package, policy, _, approval = _approved_case(tmp_path)
    api = _FakeHfApi()
    with pytest.raises(HuggingFacePublicationError, match="target_revision=main only"):
        publish_ir_release(package, policy=policy, dry_run=False, approval=approval,
            lease=_lease(policy), api=api, audited_parent_commit=AUDITED_PARENT,
            target_revision="review-branch")
    assert api.calls == api.read_calls == [] and api.payloads == {}


@pytest.mark.parametrize("fault", ["skipped-observations", "occupied-prefix"])
def test_genuine_generic_owner_refuses_skipped_plans_and_occupied_prefixes(tmp_path, fault):
    from ipfs_datasets_py.huggingface.ir_publisher import ir_publisher

    package, policy, full_plan, _ = _approved_case(tmp_path)
    first = full_plan.operations[0]
    observations = {first.remote_path: first.sha256} if fault == "skipped-observations" else {}
    body = (Path(package.output_dir) / first.relative_path).read_bytes()
    actual_store = {first.remote_path: body} if fault == "occupied-prefix" else {}
    api = _FakeHfApi(existing_payloads=actual_store)
    publisher = ir_publisher(policy, api=api)
    plan, _ = plan_ir_dry_run(package, policy=policy, publisher=publisher,
        existing_remote_digests=observations, audited_parent_commit=AUDITED_PARENT)
    approval = PublicationApproval(approver="release-operator@example.com",
        plan_digest=plan.plan_digest, max_cost_usd=10.0,
        max_upload_bytes=plan.cost_receipt["upload_bytes"],
        credentials_scope="dataset:write:Publicus/proof-grounded-ir-learning",
        approval_id="approval-fixture-direct-generic-refusal")
    expected = "skipped exact matches" if fault == "skipped-observations" else "pre-existing path"
    with pytest.raises(HuggingFacePublicationError, match=expected):
        publisher.publish_append_only(plan, approval=approval, local_root=package.output_dir)
    assert api.calls == [] and api.payloads == {}
    assert api.existing_payloads == actual_store
    if fault == "skipped-observations":
        assert plan.skipped_exact_matches and api.read_calls == []
    else:
        assert not plan.skipped_exact_matches
        assert any(call["method"] == "get_paths_info" and call["revision"] == AUDITED_PARENT
                   for call in api.read_calls)
