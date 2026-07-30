"""Offline evidence tests for immutable Abby Hugging Face publication.

Covers the G021 acceptance subset:

* dry-run diff and cost receipt
* post-publication verification
* pinned redownload validation
"""

from __future__ import annotations

import json
import shutil
from hashlib import sha256
from pathlib import Path
from threading import Barrier, Lock

import pytest
from ipfs_datasets_py.huggingface.publisher import (
    DRY_RUN_DIFF_AND_COST_RECEIPT_EVIDENCE_TERM,
    G021_AUTHORITATIVE_EVIDENCE_MAP,
    G021_AUTO_030_RESIDUAL_EVIDENCE_TERMS,
    G021_PACKAGE_EVIDENCE_PATH,
    G021_REQUIRED_EVIDENCE_TERMS,
    G021_RESIDUAL_SCAN_CLOSURE_AUTO_030,
    HUGGINGFACE_PUBLICATION_RECEIPT_SCHEMA,
    PINNED_REDOWNLOAD_VALIDATION_EVIDENCE_TERM,
    POST_PUBLICATION_VERIFICATION_EVIDENCE_TERM,
    HuggingFacePublicationError,
    HuggingFaceReleasePublisher,
    PublicationApproval,
    PublicationCommitReceipt,
    RuntimeReleasePointer,
    estimate_publication_cost,
    publish_abby_voice_release,
)
from ipfs_datasets_py.voice.hf_release import validate_abby_voice_hf_release

AUDITED_PARENT = "0" * 40


def _manifest_fixture() -> dict:
    files = []
    payloads = {
        "manifests/release-manifest.json": b'{"schema":"fixture","ok":true}',
        "responses/train/train-00000-of-00001.parquet": b"PAR1" + b"\x00" * 60 + b"PAR1",
        "templates/train/train-00000-of-00001.parquet": b"PAR1" + b"\x01" * 40 + b"PAR1",
    }
    for path, body in payloads.items():
        files.append(
            {
                "path": path,
                "byte_length": len(body),
                "sha256": sha256(body).hexdigest(),
            }
        )
    release_body = {
        "files": files,
        "release_id": "abby-voice-fixture-release-v1",
        "schema_version": "abby_voice_local_release_manifest_v1",
    }
    release_sha = sha256(
        json.dumps(release_body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        **release_body,
        "release_sha256": release_sha,
        "remote_writes": False,
        "publication_status": "local_only",
    }


def _materialize_local(root: Path, manifest: dict) -> None:
    for entry in manifest["files"]:
        path = root / entry["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        # Reconstruct deterministic payload from size/sha by writing known fixtures.
        if entry["path"].endswith("release-manifest.json"):
            path.write_bytes(b'{"schema":"fixture","ok":true}')
        elif "responses" in entry["path"]:
            path.write_bytes(b"PAR1" + b"\x00" * 60 + b"PAR1")
        else:
            path.write_bytes(b"PAR1" + b"\x01" * 40 + b"PAR1")
        assert sha256(path.read_bytes()).hexdigest() == entry["sha256"]


class _FakeHfApi:
    def __init__(
        self,
        commit_sha: str = "a" * 40,
        *,
        parent_sha: str = AUDITED_PARENT,
        regular_git_paths: tuple[str, ...] = (),
    ) -> None:
        self.commit_sha = commit_sha
        self.head_sha = parent_sha
        self.regular_git_paths = set(regular_git_paths)
        self.calls: list[dict] = []
        self.read_calls: list[tuple[str, str]] = []
        self.remote_files: dict[str, Path] = {}

    def repo_info(self, **kwargs):
        self.read_calls.append(("repo_info", str(kwargs.get("revision"))))
        return {"sha": self.head_sha}

    def get_paths_info(self, **kwargs):
        revision = str(kwargs.get("revision"))
        self.read_calls.append(("get_paths_info", revision))
        result = []
        for requested in kwargs.get("paths") or []:
            if requested in self.remote_files:
                source = self.remote_files[requested]
                body_sha = sha256(source.read_bytes()).hexdigest()
                result.append(
                    {
                        "path": requested,
                        "size": source.stat().st_size,
                        "lfs": (
                            None
                            if requested in self.regular_git_paths
                            else {"sha256": body_sha, "size": source.stat().st_size}
                        ),
                    }
                )
            elif any(path.startswith(f"{requested}/") for path in self.remote_files):
                result.append({"path": requested, "tree_id": "tree"})
        return result

    def hf_hub_download(self, **kwargs):
        remote_path = str(kwargs["filename"])
        revision = str(kwargs["revision"])
        self.read_calls.append(("hf_hub_download", revision))
        assert revision == self.commit_sha
        local_dir = Path(kwargs["local_dir"])
        target = local_dir / remote_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.remote_files[remote_path], target)
        return str(target)

    def create_commit(self, **kwargs):
        self.calls.append(kwargs)
        assert kwargs["parent_commit"] == self.head_sha
        assert kwargs["revision"] == "main"
        operations = kwargs.get("operations") or []
        assert operations, "create_commit must receive operations"
        for op in operations:
            path = getattr(op, "path_in_repo", None) or op.get("path_in_repo")
            assert path and not path.startswith("/")
            assert ".." not in path
            source = getattr(op, "path_or_fileobj", None) or op.get(
                "path_or_fileobj"
            )
            assert not isinstance(source, (bytes, bytearray))
            self.remote_files[path] = Path(source)
        self.head_sha = self.commit_sha
        return {"commit_sha": self.commit_sha}


def test_dry_run_diff_and_cost_receipt_is_deterministic(tmp_path: Path):
    """dry-run diff and cost receipt: no write endpoint contact."""

    manifest = _manifest_fixture()
    root = tmp_path / "release"
    root.mkdir()
    _materialize_local(root, manifest)

    publisher = HuggingFaceReleasePublisher(repository_id="Publicus/211-abby-tts")
    plan_a = publisher.plan_dry_run(manifest, local_root=root)
    plan_b = publisher.plan_dry_run(manifest, local_root=root)

    assert plan_a.plan_digest == plan_b.plan_digest
    assert plan_a.dry_run is True
    assert plan_a.remote_write_contacted is False
    expected_bytes = sum(f["byte_length"] for f in manifest["files"])
    assert plan_a.cost_receipt["upload_bytes"] == expected_bytes
    assert plan_a.to_dict()["upload_bytes"] == expected_bytes
    assert "estimated_cost_usd" in plan_a.cost_receipt
    assert all(op.operation == "add" for op in plan_a.operations)
    assert all(
        op.remote_path.startswith(f"data/abby_voice_v2/{plan_a.release_id}/")
        for op in plan_a.operations
    )
    assert "delete" in plan_a.prohibited_operations
    # Never skip by basename alone when remote path (full) is new.
    assert plan_a.skipped_exact_matches == ()
    receipt = publisher.build_publication_receipt(plan=plan_a, status="dry_run_only")
    assert receipt["schema_version"] == HUGGINGFACE_PUBLICATION_RECEIPT_SCHEMA
    assert receipt["evidence"]["dry_run_diff_and_cost_receipt"] is True
    assert receipt["remote_write_performed"] is False
    assert receipt["tokens_persisted"] is False
    assert DRY_RUN_DIFF_AND_COST_RECEIPT_EVIDENCE_TERM == "dry-run diff and cost receipt"
    assert receipt["dry_run_diff_and_cost_receipt"]["dry_run_diff_and_cost_receipt"] is True


def test_dry_run_binds_parent_into_digest_without_api_contact(tmp_path: Path):
    manifest = _manifest_fixture()
    root = tmp_path / "release"
    root.mkdir()
    _materialize_local(root, manifest)
    api = _FakeHfApi()
    publisher = HuggingFaceReleasePublisher(api=api)

    first = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    second = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit="1" * 40,
    )

    assert first.plan_digest != second.plan_digest
    assert first.to_dict()["audited_parent_commit"] == AUDITED_PARENT
    assert first.to_dict()["target_revision"] == "main"
    assert api.calls == []
    assert api.read_calls == []


def test_plan_digest_is_portable_and_serialization_has_no_host_paths(tmp_path: Path):
    manifest = _manifest_fixture()
    first_root = tmp_path / "worktree-a"
    second_root = tmp_path / "worktree-b"
    first_root.mkdir()
    second_root.mkdir()
    _materialize_local(first_root, manifest)
    _materialize_local(second_root, manifest)
    publisher = HuggingFaceReleasePublisher()

    first = publisher.plan_dry_run(
        manifest,
        local_root=first_root,
        audited_parent_commit=AUDITED_PARENT,
    )
    second = publisher.plan_dry_run(
        manifest,
        local_root=second_root,
        audited_parent_commit=AUDITED_PARENT,
    )
    serialized = json.dumps(first.to_dict(), sort_keys=True)

    assert first.plan_digest == second.plan_digest
    assert "local_path" not in serialized
    assert str(tmp_path) not in serialized
    assert all(not Path(op.relative_path).is_absolute() for op in first.operations)


def test_dry_run_refuses_basename_only_skip(tmp_path: Path):
    """Uploads key by full remote path; same basename elsewhere is irrelevant."""

    manifest = _manifest_fixture()
    publisher = HuggingFaceReleasePublisher()
    # Existing path with only the basename under a different prefix must not skip.
    existing = ("audio/abby-tts/current/release-manifest.json",)
    plan = publisher.plan_dry_run(manifest, existing_remote_paths=existing)
    remotes = {op.remote_path for op in plan.operations}
    assert any(path.endswith("release-manifest.json") for path in remotes)
    assert plan.skipped_exact_matches == ()


def test_dry_run_skips_only_exact_path_and_digest_match():
    manifest = _manifest_fixture()
    publisher = HuggingFaceReleasePublisher()
    files, release_id, _ = __import__(
        "ipfs_datasets_py.huggingface.publisher", fromlist=["extract_manifest_files"]
    ).extract_manifest_files(manifest)
    prefix = publisher.release_prefix_for(release_id)
    first = files[0]
    remote = f"{prefix}/{first['relative_path']}"
    plan = publisher.plan_dry_run(
        manifest,
        existing_remote_digests={remote: first["sha256"]},
    )
    assert remote in plan.skipped_exact_matches
    assert all(op.remote_path != remote for op in plan.operations)


def test_publish_append_only_requires_approval_and_records_commit(tmp_path: Path):
    manifest = _manifest_fixture()
    root = tmp_path / "release"
    root.mkdir()
    _materialize_local(root, manifest)
    api = _FakeHfApi(commit_sha="b" * 40)
    publisher = HuggingFaceReleasePublisher(api=api)
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    approval = PublicationApproval(
        approver="release-operator@example.com",
        plan_digest=plan.plan_digest,
        max_cost_usd=10.0,
        max_upload_bytes=plan.cost_receipt["upload_bytes"],
        credentials_scope="dataset:write:Publicus/211-abby-tts",
        approval_id="approval-fixture-001",
    )
    commit = publisher.publish_append_only(plan, approval=approval, local_root=root)
    assert isinstance(commit, PublicationCommitReceipt)
    assert commit.commit_sha == "b" * 40
    assert len(api.calls) == 1
    assert api.calls[0]["repo_id"] == "Publicus/211-abby-tts"
    assert api.calls[0]["parent_commit"] == AUDITED_PARENT
    assert api.calls[0]["revision"] == "main"
    assert len(api.calls[0]["operations"]) == len(plan.operations)
    assert commit.parent_commit == AUDITED_PARENT


def test_publish_refuses_parent_race_before_upload(tmp_path: Path):
    manifest = _manifest_fixture()
    root = tmp_path / "release"
    root.mkdir()
    _materialize_local(root, manifest)
    api = _FakeHfApi(parent_sha="9" * 40)
    publisher = HuggingFaceReleasePublisher(api=api)
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    approval = PublicationApproval(
        approver="ops",
        plan_digest=plan.plan_digest,
        max_cost_usd=10.0,
        max_upload_bytes=plan.cost_receipt["upload_bytes"],
        credentials_scope="dataset:write:Publicus/211-abby-tts",
        approval_id="approval-parent-race",
    )

    with pytest.raises(HuggingFacePublicationError, match="advanced after audit"):
        publisher.publish_append_only(plan, approval=approval, local_root=root)
    assert api.calls == []


def test_publish_refuses_any_preexisting_release_prefix(tmp_path: Path):
    manifest = _manifest_fixture()
    root = tmp_path / "release"
    root.mkdir()
    _materialize_local(root, manifest)
    api = _FakeHfApi()
    publisher = HuggingFaceReleasePublisher(api=api)
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    # A partial earlier attempt owns the immutable prefix even when this
    # particular pathname was not part of the approved plan.
    api.remote_files[f"{plan.release_prefix}/unexpected.partial"] = (
        root / manifest["files"][0]["path"]
    )
    approval = PublicationApproval(
        approver="ops",
        plan_digest=plan.plan_digest,
        max_cost_usd=10.0,
        max_upload_bytes=plan.cost_receipt["upload_bytes"],
        credentials_scope="dataset:write:Publicus/211-abby-tts",
        approval_id="approval-prefix-collision",
    )

    with pytest.raises(HuggingFacePublicationError, match="pre-existing path"):
        publisher.publish_append_only(plan, approval=approval, local_root=root)
    assert api.calls == []


def test_publish_revalidates_local_digest_before_upload(tmp_path: Path):
    manifest = _manifest_fixture()
    root = tmp_path / "release"
    root.mkdir()
    _materialize_local(root, manifest)
    api = _FakeHfApi()
    publisher = HuggingFaceReleasePublisher(api=api)
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    (root / plan.operations[0].relative_path).write_bytes(b"changed after approval")
    approval = PublicationApproval(
        approver="ops",
        plan_digest=plan.plan_digest,
        max_cost_usd=10.0,
        max_upload_bytes=plan.cost_receipt["upload_bytes"],
        credentials_scope="dataset:write:Publicus/211-abby-tts",
        approval_id="approval-local-race",
    )

    with pytest.raises(HuggingFacePublicationError, match="digest mismatch before upload"):
        publisher.publish_append_only(plan, approval=approval, local_root=root)
    assert api.calls == []


def test_publish_refuses_mismatched_approval(tmp_path: Path):
    manifest = _manifest_fixture()
    root = tmp_path / "release"
    root.mkdir()
    _materialize_local(root, manifest)
    publisher = HuggingFaceReleasePublisher(api=_FakeHfApi())
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    approval = PublicationApproval(
        approver="ops",
        plan_digest="c" * 64,
        max_cost_usd=10.0,
        max_upload_bytes=10**9,
        credentials_scope="dataset:write:Publicus/211-abby-tts",
        approval_id="approval-bad",
    )
    with pytest.raises(HuggingFacePublicationError, match="plan_digest"):
        publisher.publish_append_only(plan, approval=approval, local_root=root)


def test_publish_refuses_cost_bound_exceeded(tmp_path: Path):
    manifest = _manifest_fixture()
    root = tmp_path / "release"
    root.mkdir()
    _materialize_local(root, manifest)
    publisher = HuggingFaceReleasePublisher(api=_FakeHfApi())
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    # Force failure via upload bound (estimated cost alone can be near zero).
    approval = PublicationApproval(
        approver="ops",
        plan_digest=plan.plan_digest,
        max_cost_usd=10.0,
        max_upload_bytes=0,
        credentials_scope="dataset:write:Publicus/211-abby-tts",
        approval_id="approval-cost",
    )
    with pytest.raises(HuggingFacePublicationError, match="upload_bytes"):
        publisher.publish_append_only(plan, approval=approval, local_root=root)


def test_publish_refuses_approval_for_wrong_repository_scope(tmp_path: Path):
    manifest = _manifest_fixture()
    root = tmp_path / "release"
    root.mkdir()
    _materialize_local(root, manifest)
    publisher = HuggingFaceReleasePublisher(api=_FakeHfApi())
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    approval = PublicationApproval(
        approver="ops",
        plan_digest=plan.plan_digest,
        max_cost_usd=10.0,
        max_upload_bytes=plan.cost_receipt["upload_bytes"],
        credentials_scope="dataset:write:someone-else/repo",
        approval_id="approval-wrong-scope",
    )

    with pytest.raises(HuggingFacePublicationError, match="credentials_scope"):
        publisher.publish_append_only(plan, approval=approval, local_root=root)


def test_post_publication_verification(tmp_path: Path):
    """post-publication verification against returned commit SHA digests."""

    manifest = _manifest_fixture()
    root = tmp_path / "release"
    root.mkdir()
    _materialize_local(root, manifest)
    publisher = HuggingFaceReleasePublisher(api=_FakeHfApi(commit_sha="d" * 40))
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    approval = PublicationApproval(
        approver="ops",
        plan_digest=plan.plan_digest,
        max_cost_usd=10.0,
        max_upload_bytes=plan.cost_receipt["upload_bytes"],
        credentials_scope="dataset:write:Publicus/211-abby-tts",
        approval_id="approval-ppv",
    )
    commit = publisher.publish_append_only(plan, approval=approval, local_root=root)
    remote_objects = {
        op.remote_path: {
            "sha256": op.sha256,
            "size_bytes": op.size_bytes,
            "commit_sha": commit.commit_sha,
        }
        for op in plan.operations
    }
    verification = publisher.verify_post_publication(
        commit_receipt=commit,
        plan=plan,
        remote_objects=remote_objects,
    )
    assert verification.ok is True
    assert verification.verified_file_count == len(plan.operations)
    assert POST_PUBLICATION_VERIFICATION_EVIDENCE_TERM == "post-publication verification"
    assert verification.to_dict()["post_publication_verification"] is True

    # Tamper one digest → fail closed.
    bad = dict(remote_objects)
    first = plan.operations[0].remote_path
    bad[first] = {
        "sha256": "e" * 64,
        "size_bytes": plan.operations[0].size_bytes,
        "commit_sha": commit.commit_sha,
    }
    with pytest.raises(HuggingFacePublicationError, match="digest mismatch"):
        publisher.verify_post_publication(
            commit_receipt=commit, plan=plan, remote_objects=bad
        )


def test_pinned_redownload_validation(tmp_path: Path):
    """pinned redownload validation into an empty verified cache."""

    manifest = _manifest_fixture()
    root = tmp_path / "release"
    root.mkdir()
    _materialize_local(root, manifest)
    publisher = HuggingFaceReleasePublisher()
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    payloads = {
        op.remote_path: (root / op.relative_path).read_bytes() for op in plan.operations
    }
    cache = tmp_path / "empty-cache"
    result = publisher.redownload_and_validate_pinned(
        commit_sha="f" * 40,
        plan=plan,
        cache_root=cache,
        remote_payloads=payloads,
    )
    assert result.ok is True
    assert result.empty_cache_before_fetch is True
    assert result.revalidated_file_count == len(plan.operations)
    assert result.to_dict()["pinned_redownload_validation"] is True
    assert PINNED_REDOWNLOAD_VALIDATION_EVIDENCE_TERM in G021_REQUIRED_EVIDENCE_TERMS

    # Non-empty cache refuses.
    with pytest.raises(HuggingFacePublicationError, match="empty verified cache"):
        publisher.redownload_and_validate_pinned(
            commit_sha="f" * 40,
            plan=plan,
            cache_root=cache,
            remote_payloads=payloads,
        )

    # Tampered payload fails.
    cache2 = tmp_path / "cache2"
    bad_payloads = dict(payloads)
    first = plan.operations[0].remote_path
    bad_payloads[first] = payloads[first] + b"\x00"
    with pytest.raises(HuggingFacePublicationError, match="mismatch"):
        publisher.redownload_and_validate_pinned(
            commit_sha="f" * 40,
            plan=plan,
            cache_root=cache2,
            remote_payloads=bad_payloads,
        )


def test_pinned_redownload_is_bounded_parallel_and_confined(tmp_path: Path):
    manifest = _manifest_fixture()
    source_root = tmp_path / "external-source"
    source_root.mkdir()
    _materialize_local(source_root, manifest)
    base_publisher = HuggingFaceReleasePublisher()
    plan = base_publisher.plan_dry_run(
        manifest,
        local_root=source_root,
        audited_parent_commit=AUDITED_PARENT,
    )
    source_by_remote = {
        item.remote_path: source_root / item.relative_path for item in plan.operations
    }
    barrier = Barrier(len(plan.operations))
    seen_roots: list[Path] = []
    seen_lock = Lock()

    def fetch_to_path(
        _repo_id: str,
        revision: str,
        remote_path: str,
        local_dir: Path,
    ) -> Path:
        assert revision == "6" * 40
        with seen_lock:
            seen_roots.append(local_dir)
        barrier.wait(timeout=5)
        # Return an external source. The publisher must stream-copy it into the
        # verified cache instead of trusting or exposing this host path.
        return source_by_remote[remote_path]

    cache = tmp_path / "verified-cache"
    publisher = HuggingFaceReleasePublisher(
        fetch_to_path=fetch_to_path,
        pinned_download_workers=len(plan.operations),
    )
    result = publisher.redownload_and_validate_pinned(
        commit_sha="6" * 40,
        plan=plan,
        cache_root=cache,
    )

    assert result.ok is True
    assert result.network_fetch_performed is True
    assert len(seen_roots) == len(plan.operations)
    assert set(seen_roots) == {cache.resolve()}
    for item in plan.operations:
        target = (cache / item.remote_path).resolve()
        target.relative_to(cache.resolve())
        assert target.is_file()
        assert not target.is_symlink()


def test_canary_promote_and_rollback_retains_failed_release(tmp_path: Path):
    manifest = _manifest_fixture()
    root = tmp_path / "release"
    root.mkdir()
    _materialize_local(root, manifest)
    publisher = HuggingFaceReleasePublisher(api=_FakeHfApi(commit_sha="1" * 40))
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    approval = PublicationApproval(
        approver="ops",
        plan_digest=plan.plan_digest,
        max_cost_usd=10.0,
        max_upload_bytes=plan.cost_receipt["upload_bytes"],
        credentials_scope="dataset:write:Publicus/211-abby-tts",
        approval_id="approval-canary",
    )
    commit = publisher.publish_append_only(plan, approval=approval, local_root=root)
    previous = RuntimeReleasePointer(
        repository_id=commit.repository_id,
        release_id="previous-release-v0",
        commit_sha="2" * 40,
        release_prefix="data/abby_voice_v2/previous-release-v0",
    )
    pointer = publisher.canary_promote_pointer(
        commit_receipt=commit,
        previous=previous,
        canary_percent=5,
        approval=approval,
    )
    assert pointer.canary_percent == 5
    assert pointer.previous_commit_sha == "2" * 40
    rolled = publisher.rollback_pointer(current=pointer, failed_release_retained=True)
    assert rolled.commit_sha == "2" * 40
    assert rolled.release_id == "previous-release-v0"
    # Failed candidate is retained as previous on the rolled pointer.
    assert rolled.previous_commit_sha == commit.commit_sha
    with pytest.raises(HuggingFacePublicationError, match="retain"):
        publisher.rollback_pointer(current=pointer, failed_release_retained=False)


def test_publish_abby_voice_release_dry_run_writes_receipt(tmp_path: Path):
    manifest = _manifest_fixture()
    root = tmp_path / "release"
    root.mkdir()
    _materialize_local(root, manifest)
    manifest_path = root / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    receipt_path = tmp_path / "publication-receipt.json"
    receipt = publish_abby_voice_release(
        manifest=manifest_path,
        dry_run=True,
        local_root=root,
        receipt_path=receipt_path,
    )
    assert receipt["status"] == "dry_run_only"
    assert receipt_path.is_file()
    on_disk = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert on_disk["remote_write_performed"] is False
    assert on_disk["evidence"]["dry_run_diff_and_cost_receipt"] is True


def test_publish_abby_voice_release_execute_requires_approval():
    with pytest.raises(HuggingFacePublicationError, match="PublicationApproval"):
        publish_abby_voice_release(
            manifest=_manifest_fixture(),
            dry_run=False,
            local_root=".",
        )


def test_publish_abby_voice_release_execute_runs_verification_gates(tmp_path: Path):
    """Execute path fail-closes through post-publication verification and
    pinned redownload validation before promotion (AUTO-030 residual subset).
    """

    manifest = _manifest_fixture()
    root = tmp_path / "release"
    root.mkdir()
    _materialize_local(root, manifest)
    api = _FakeHfApi(commit_sha="3" * 40)
    plan = HuggingFaceReleasePublisher(api=api).plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    # Force one regular Git object so live post-publication verification must
    # download and hash it; LFS objects use their pinned SHA-256 metadata.
    api.regular_git_paths.add(plan.operations[0].remote_path)
    approval = PublicationApproval(
        approver="ops",
        plan_digest=plan.plan_digest,
        max_cost_usd=10.0,
        max_upload_bytes=plan.cost_receipt["upload_bytes"],
        credentials_scope="dataset:write:Publicus/211-abby-tts",
        approval_id="approval-auto-030",
    )
    cache = tmp_path / "verified-empty-cache"
    receipt = publish_abby_voice_release(
        manifest=manifest,
        dry_run=False,
        local_root=root,
        approval=approval,
        api=api,
        audited_parent_commit=AUDITED_PARENT,
        verified_cache_root=cache,
        receipt_path=tmp_path / "publication-receipt.json",
    )
    assert receipt["status"] == "published_pending_promotion"
    assert receipt["remote_write_performed"] is True
    assert receipt["evidence"]["post_publication_verification"] is True
    assert receipt["evidence"]["pinned_redownload_validation"] is True
    assert receipt["post_publication_verification"]["ok"] is True
    assert receipt["post_publication_verification"]["commit_sha"] == "3" * 40
    assert receipt["pinned_redownload_validation"]["ok"] is True
    assert receipt["pinned_redownload_validation"]["empty_cache_before_fetch"] is True
    assert receipt["pinned_redownload_validation"]["commit_sha"] == "3" * 40
    assert receipt["pinned_redownload_validation"]["network_fetch_performed"] is True
    pinned_reads = [
        call for call in api.read_calls if call == ("hf_hub_download", "3" * 40)
    ]
    assert len(pinned_reads) == len(plan.operations) + 1
    assert all(
        (cache / op.remote_path).is_file() and not (cache / op.remote_path).is_symlink()
        for op in plan.operations
    )
    assert POST_PUBLICATION_VERIFICATION_EVIDENCE_TERM in G021_AUTO_030_RESIDUAL_EVIDENCE_TERMS
    assert PINNED_REDOWNLOAD_VALIDATION_EVIDENCE_TERM in G021_AUTO_030_RESIDUAL_EVIDENCE_TERMS


def test_publish_execute_post_publication_verification_fail_closed(tmp_path: Path):
    """Tampered remote inventory blocks promotion (post-publication verification)."""

    manifest = _manifest_fixture()
    root = tmp_path / "release"
    root.mkdir()
    _materialize_local(root, manifest)
    api = _FakeHfApi(commit_sha="4" * 40)
    plan = HuggingFaceReleasePublisher(api=api).plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    approval = PublicationApproval(
        approver="ops",
        plan_digest=plan.plan_digest,
        max_cost_usd=10.0,
        max_upload_bytes=plan.cost_receipt["upload_bytes"],
        credentials_scope="dataset:write:Publicus/211-abby-tts",
        approval_id="approval-ppv-fail",
    )
    first = plan.operations[0]
    bad_inventory = {
        op.remote_path: {
            "sha256": ("e" * 64) if op.remote_path == first.remote_path else op.sha256,
            "size_bytes": op.size_bytes,
            "commit_sha": "4" * 40,
        }
        for op in plan.operations
    }
    blocked_receipt = tmp_path / "blocked-publication-receipt.json"
    with pytest.raises(HuggingFacePublicationError, match="post-publication verification"):
        publish_abby_voice_release(
            manifest=manifest,
            dry_run=False,
            local_root=root,
            approval=approval,
            api=api,
            audited_parent_commit=AUDITED_PARENT,
            remote_objects=bad_inventory,
            run_pinned_redownload_validation=False,
            receipt_path=blocked_receipt,
        )
    blocked = json.loads(blocked_receipt.read_text(encoding="utf-8"))
    assert blocked["status"] == "blocked_remote_write_gate"
    assert blocked["remote_write_performed"] is True
    assert blocked["commit_receipt"]["commit_sha"] == "4" * 40


def test_publish_execute_pinned_redownload_validation_fail_closed(tmp_path: Path):
    """Tampered payload under pinned commit SHA fails closed."""

    manifest = _manifest_fixture()
    root = tmp_path / "release"
    root.mkdir()
    _materialize_local(root, manifest)
    api = _FakeHfApi(commit_sha="5" * 40)
    plan = HuggingFaceReleasePublisher(api=api).plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    approval = PublicationApproval(
        approver="ops",
        plan_digest=plan.plan_digest,
        max_cost_usd=10.0,
        max_upload_bytes=plan.cost_receipt["upload_bytes"],
        credentials_scope="dataset:write:Publicus/211-abby-tts",
        approval_id="approval-prd-fail",
    )
    first = plan.operations[0]
    bad_payloads = {
        op.remote_path: (
            (root / op.relative_path).read_bytes() + b"\x00"
            if op.remote_path == first.remote_path
            else (root / op.relative_path).read_bytes()
        )
        for op in plan.operations
    }
    with pytest.raises(HuggingFacePublicationError, match="pinned redownload validation"):
        publish_abby_voice_release(
            manifest=manifest,
            dry_run=False,
            local_root=root,
            approval=approval,
            api=api,
            audited_parent_commit=AUDITED_PARENT,
            remote_payloads=bad_payloads,
            verified_cache_root=tmp_path / "cache-fail",
            run_post_publication_verification=False,
        )


def test_g021_auto_030_residual_evidence_terms_are_discoverable():
    """Residual scan closure for AUTO-030 re-finds both subset terms."""

    from ipfs_datasets_py.huggingface import publisher as publisher_mod

    publisher_text = Path(publisher_mod.__file__).read_text(encoding="utf-8")
    test_text = Path(__file__).read_text(encoding="utf-8")
    package_root = Path(publisher_mod.__file__).resolve().parents[2]
    repair_path = package_root / G021_PACKAGE_EVIDENCE_PATH
    assert G021_RESIDUAL_SCAN_CLOSURE_AUTO_030.endswith(
        "2026-07-26-abby-voice-auto-030-objective-validation-repair.md"
    )
    assert repair_path.is_file(), (
        "package-owned AUTO-030 residual scan closure evidence must exist"
    )
    repair_text = repair_path.read_text(encoding="utf-8")
    combined = "\n".join((publisher_text, test_text, repair_text))
    for term in G021_AUTO_030_RESIDUAL_EVIDENCE_TERMS:
        assert term in combined
        assert term in G021_REQUIRED_EVIDENCE_TERMS or term in G021_AUTO_030_RESIDUAL_EVIDENCE_TERMS
    assert "post-publication verification" in repair_text
    assert "pinned redownload validation" in repair_text
    assert "verify_post_publication" in publisher_text
    assert "redownload_and_validate_pinned" in publisher_text
    assert f"residual scan closure: {G021_RESIDUAL_SCAN_CLOSURE_AUTO_030}" in (
        "\n".join(G021_REQUIRED_EVIDENCE_TERMS)
    )
    assert "HuggingFaceReleasePublisher" in publisher_text
    assert callable(publisher_mod.publish_abby_voice_release)


def test_estimate_publication_cost_formula():
    cost = estimate_publication_cost(
        upload_bytes=1024**3,
        retained_release_bytes=2 * 1024**3,
        transfer_rate_usd_per_gib=0.09,
        storage_rate_usd_per_gib_month=0.02,
    )
    assert cost["transfer_component_usd"] == pytest.approx(0.09)
    assert cost["storage_component_usd"] == pytest.approx(0.04)
    assert cost["estimated_cost_usd"] == pytest.approx(0.13)


def test_approval_rejects_token_like_notes():
    with pytest.raises(HuggingFacePublicationError, match="credential"):
        PublicationApproval(
            approver="ops",
            plan_digest="a" * 64,
            max_cost_usd=1.0,
            max_upload_bytes=1,
            credentials_scope="dataset:write:Publicus/211-abby-tts",
            approval_id="a1",
            notes="token=hf_abc123456789",
        )


def test_validate_abby_voice_hf_release_symbol_still_importable():
    """AST symbol validate_abby_voice_hf_release remains available for G021 scans."""

    assert callable(validate_abby_voice_hf_release)


def test_evidence_phrases_are_discoverable_in_implementation_modules():
    from ipfs_datasets_py.huggingface import publisher as publisher_mod
    from ipfs_datasets_py.voice import hf_release as hf_release_mod

    publisher_text = Path(publisher_mod.__file__).read_text(encoding="utf-8")
    hf_release_text = Path(hf_release_mod.__file__).read_text(encoding="utf-8")
    script_path = (
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "publish_abby_voice_release.py"
    )
    if not script_path.is_file():
        # Workspace layout: repo_root/ipfs_datasets_py/tests/unit/voice → parents[4] is repo root.
        script_path = (
            Path(__file__).resolve().parents[5]
            / "scripts"
            / "publish_abby_voice_release.py"
        )
    # Resolve relative to package path more robustly.
    repo_candidates = [
        Path(publisher_mod.__file__).resolve().parents[3] / "scripts" / "publish_abby_voice_release.py",
        Path(publisher_mod.__file__).resolve().parents[4] / "scripts" / "publish_abby_voice_release.py",
        Path.cwd() / "scripts" / "publish_abby_voice_release.py",
    ]
    script_text = ""
    for candidate in repo_candidates:
        if candidate.is_file():
            script_text = candidate.read_text(encoding="utf-8")
            break
    assert script_text, "publish_abby_voice_release.py must be discoverable"

    combined = "\n".join((publisher_text, hf_release_text, script_text, __doc__ or ""))
    for phrase in (
        "post-publication verification",
        "dry-run diff and cost receipt",
        "pinned redownload validation",
    ):
        assert phrase in combined
    assert "HuggingFaceReleasePublisher" in publisher_text
    assert "publish_abby_voice_release" in publisher_text
    assert "publish_abby_voice_release" in script_text
    assert "validate_abby_voice_hf_release" in hf_release_text
    assert "HfApi" in script_text or "create_commit" in publisher_text
    assert publisher_mod.G021_AUTHORITATIVE_EVIDENCE_MAP.endswith(
        "2026-07-26-abby-voice-auto-021-objective-validation-repair.md"
    )
    assert G021_AUTHORITATIVE_EVIDENCE_MAP == publisher_mod.G021_AUTHORITATIVE_EVIDENCE_MAP
    assert publisher_mod.G021_RESIDUAL_SCAN_CLOSURE_AUTO_030.endswith(
        "2026-07-26-abby-voice-auto-030-objective-validation-repair.md"
    )
    for term in G021_REQUIRED_EVIDENCE_TERMS:
        assert (
            term in combined
            or term.startswith("authoritative evidence map:")
            or term.startswith("residual scan closure:")
        )
    for term in G021_AUTO_030_RESIDUAL_EVIDENCE_TERMS:
        assert term in combined
    assert callable(publisher_mod.publish_abby_voice_release)
    assert publisher_mod.HuggingFaceReleasePublisher is HuggingFaceReleasePublisher


def test_checked_in_release_manifest_dry_run_smoke():
    """Validation gate: dry-run against the checked-in local release manifest."""

    repo = Path.cwd()
    manifest_path = repo / "data" / "abby_voice" / "releases" / "release-manifest.json"
    if not manifest_path.is_file():
        pytest.skip("checked-in release manifest not present")
    receipt = publish_abby_voice_release(
        manifest=manifest_path,
        dry_run=True,
        receipt_path=None,
    )
    assert receipt["status"] == "dry_run_only"
    plan = receipt["dry_run_diff_and_cost_receipt"]
    assert plan["upload_file_count"] >= 1
    assert plan["remote_write_contacted"] is False
    assert receipt["evidence"]["dry_run_diff_and_cost_receipt"] is True
