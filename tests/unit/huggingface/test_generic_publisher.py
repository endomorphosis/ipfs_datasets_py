"""Generic append-only publisher tests across publication profiles (PATLAW-100)."""

from __future__ import annotations

import io
import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.huggingface import publisher as publisher_module

from ipfs_datasets_py.huggingface.publication_profile import (
    ABBY_VOICE_GOAL_ID,
    BASE_PROHIBITED_OPERATIONS,
    PATENT_LEGAL_GOAL_ID,
    PATENT_LEGAL_PLAN_SCHEMA,
    PATENT_LEGAL_RECEIPT_SCHEMA,
    abby_voice_publication_profile,
    patent_legal_publication_profile,
)
from ipfs_datasets_py.huggingface.publisher import (
    DEFAULT_DATASET_REPO_ID,
    HUGGINGFACE_PUBLICATION_PLAN_SCHEMA,
    HUGGINGFACE_PUBLICATION_RECEIPT_SCHEMA,
    HuggingFacePublicationError,
    HuggingFaceReleasePublisher,
    PublicationApproval,
    PublicationCommitReceipt,
    RuntimeReleasePointer,
    publish_huggingface_release,
)

AUDITED_PARENT = "0" * 40


class _WriteTrackingApi:
    """Fake Hub API that records every method invocation."""

    def __init__(self, commit_sha: str = "a" * 40, *, parent_sha: str = AUDITED_PARENT) -> None:
        self.commit_sha = commit_sha
        self.head_sha = parent_sha
        self.calls: list[str] = []
        self.remote_files: dict[str, bytes] = {}
        self.operation_handles: list[object] = []

    def repo_info(self, **kwargs):
        self.calls.append("repo_info")
        return {"sha": self.head_sha}

    def get_paths_info(self, **kwargs):
        self.calls.append("get_paths_info")
        return []

    def create_commit(self, **kwargs):
        self.calls.append("create_commit")
        for op in kwargs.get("operations") or ():
            path_in_repo = getattr(op, "path_in_repo", None)
            if path_in_repo is None and isinstance(op, dict):
                path_in_repo = op.get("path_in_repo")
            path_or_fileobj = getattr(op, "path_or_fileobj", None)
            if path_or_fileobj is None and isinstance(op, dict):
                path_or_fileobj = op.get("path_or_fileobj")
            if path_in_repo and path_or_fileobj:
                self.operation_handles.append(path_or_fileobj)
                position = path_or_fileobj.tell()
                path_or_fileobj.seek(0)
                self.remote_files[str(path_in_repo)] = path_or_fileobj.read()
                path_or_fileobj.seek(position)
        return {"commit_sha": self.commit_sha}

    def upload_file(self, **kwargs):
        self.calls.append("upload_file")
        raise AssertionError("upload_file must never be used")

    def delete_file(self, **kwargs):
        self.calls.append("delete_file")
        raise AssertionError("delete_file must never be used")


def _manifest(*, release_id: str = "fixture-release-v1") -> dict:
    payloads = {
        "manifests/release-manifest.json": b'{"schema":"fixture","ok":true}',
        "shards/train-00000.parquet": b"PAR1" + b"\x00" * 40 + b"PAR1",
    }
    files = []
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
        "release_id": release_id,
        "schema_version": "generic-local-release-manifest/v1",
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


def _materialize(root: Path, manifest: dict) -> None:
    for entry in manifest["files"]:
        path = root / entry["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        if entry["path"].endswith("release-manifest.json"):
            path.write_bytes(b'{"schema":"fixture","ok":true}')
        else:
            path.write_bytes(b"PAR1" + b"\x00" * 40 + b"PAR1")
        assert sha256(path.read_bytes()).hexdigest() == entry["sha256"]


def _approval(plan, *, repository_id: str) -> PublicationApproval:
    return PublicationApproval(
        approver="ops",
        plan_digest=plan.plan_digest,
        max_cost_usd=10.0,
        max_upload_bytes=int(plan.cost_receipt["upload_bytes"]),
        credentials_scope=f"dataset:write:{repository_id}",
        approval_id="approval-generic-1",
    )


def test_legacy_default_publisher_matches_abby_wire_identity(tmp_path: Path) -> None:
    """Omitting profile preserves historical Abby schemas and repository defaults."""

    manifest = _manifest(release_id="abby-legacy-compat-v1")
    root = tmp_path / "release"
    root.mkdir()
    _materialize(root, manifest)

    publisher = HuggingFaceReleasePublisher()
    assert publisher.repository_id == DEFAULT_DATASET_REPO_ID
    assert publisher.profile.goal_id == ABBY_VOICE_GOAL_ID
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    assert plan.schema_version == HUGGINGFACE_PUBLICATION_PLAN_SCHEMA
    assert plan.metadata["goal_id"] == ABBY_VOICE_GOAL_ID
    assert "profile_id" not in plan.metadata  # digest-stable legacy metadata
    assert plan.release_prefix.startswith("data/abby_voice_v2/")
    receipt = publisher.build_publication_receipt(plan=plan, status="dry_run_only")
    assert receipt["schema_version"] == HUGGINGFACE_PUBLICATION_RECEIPT_SCHEMA
    assert receipt["goal_id"] == ABBY_VOICE_GOAL_ID
    assert "profile_id" not in receipt


def test_patent_legal_plan_uses_program_schemas_without_abby_strings(
    tmp_path: Path,
) -> None:
    manifest = _manifest(release_id="patent-public-v1")
    root = tmp_path / "release"
    root.mkdir()
    _materialize(root, manifest)

    profile = patent_legal_publication_profile(
        repository_id="JusticeDAO/patent-legal-public"
    )
    publisher = HuggingFaceReleasePublisher(profile=profile)
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    assert plan.schema_version == PATENT_LEGAL_PLAN_SCHEMA
    assert plan.schema_version != HUGGINGFACE_PUBLICATION_PLAN_SCHEMA
    assert plan.metadata["goal_id"] == PATENT_LEGAL_GOAL_ID
    assert plan.metadata["profile_id"] == "patent-legal"
    assert plan.repository_id == "JusticeDAO/patent-legal-public"
    assert plan.release_prefix == "data/patent_legal/patent-public-v1"
    assert publisher.pointer_path == "runtime/patent_legal_release_pointer.json"

    serialized = json.dumps(plan.to_dict(), sort_keys=True)
    for marker in ("abby-voice", "abby_voice", "ABBY-VOICE", "abby-tts"):
        assert marker not in serialized

    receipt = publisher.build_publication_receipt(plan=plan, status="dry_run_only")
    assert receipt["schema_version"] == PATENT_LEGAL_RECEIPT_SCHEMA
    assert receipt["goal_id"] == PATENT_LEGAL_GOAL_ID
    assert receipt["profile_id"] == "patent-legal"
    receipt_text = json.dumps(receipt, sort_keys=True)
    for marker in ("abby-voice", "abby_voice", "ABBY-VOICE", "abby-tts"):
        assert marker not in receipt_text


def test_dry_run_never_invokes_write_api(tmp_path: Path) -> None:
    manifest = _manifest()
    root = tmp_path / "release"
    root.mkdir()
    _materialize(root, manifest)
    api = _WriteTrackingApi()
    publisher = HuggingFaceReleasePublisher(
        profile=patent_legal_publication_profile(),
        api=api,
    )
    plan = publisher.plan_dry_run(manifest, local_root=root)
    assert plan.dry_run is True
    assert plan.remote_write_contacted is False
    assert api.calls == []

    receipt = publish_huggingface_release(
        profile=patent_legal_publication_profile(),
        manifest=manifest,
        dry_run=True,
        local_root=root,
        api=api,
    )
    assert receipt["status"] == "dry_run_only"
    assert receipt["remote_write_performed"] is False
    assert api.calls == []


def test_no_profile_weakens_prohibited_operations(tmp_path: Path) -> None:
    manifest = _manifest()
    root = tmp_path / "release"
    root.mkdir()
    _materialize(root, manifest)

    for profile in (
        abby_voice_publication_profile(),
        patent_legal_publication_profile(),
    ):
        publisher = HuggingFaceReleasePublisher(profile=profile)
        plan = publisher.plan_dry_run(manifest, local_root=root)
        prohibited = set(plan.prohibited_operations)
        assert BASE_PROHIBITED_OPERATIONS.issubset(prohibited)
        assert "delete" in prohibited
        assert "force_push" in prohibited
        assert "overwrite_legacy" in prohibited


def test_pointer_promotion_waits_for_pinned_verification(tmp_path: Path) -> None:
    manifest = _manifest(release_id="promote-gate-v1")
    root = tmp_path / "release"
    root.mkdir()
    _materialize(root, manifest)

    api = _WriteTrackingApi(commit_sha="b" * 40)
    profile = patent_legal_publication_profile()
    publisher = HuggingFaceReleasePublisher(profile=profile, api=api)
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    approval = _approval(plan, repository_id=profile.repository_id)
    commit = publisher.publish_append_only(
        plan, approval=approval, local_root=root
    )
    previous = RuntimeReleasePointer(
        repository_id=commit.repository_id,
        release_id="previous-v0",
        commit_sha="c" * 40,
        release_prefix=publisher.release_prefix_for("previous-v0"),
    )

    with pytest.raises(HuggingFacePublicationError, match="pinned redownload"):
        publisher.canary_promote_pointer(
            commit_receipt=commit,
            previous=previous,
            canary_percent=10,
            approval=approval,
        )

    payloads = {
        item.remote_path: (root / item.relative_path).read_bytes()
        for item in plan.operations
    }
    cache = tmp_path / "verified-empty"
    cache.mkdir()
    pinned = publisher.redownload_and_validate_pinned(
        commit_sha=commit.commit_sha,
        plan=plan,
        cache_root=cache,
        remote_payloads=payloads,
    )
    assert pinned.ok is True

    pointer = publisher.canary_promote_pointer(
        commit_receipt=commit,
        previous=previous,
        canary_percent=10,
        approval=approval,
        pinned_redownload=pinned,
    )
    assert pointer.canary_percent == 10
    assert pointer.commit_sha == commit.commit_sha
    assert pointer.pointer_path == profile.pointer_path


def test_pointer_promotion_accepts_prior_pinned_verification_on_same_publisher(
    tmp_path: Path,
) -> None:
    """Instance-local pinned verification also unlocks canary promotion."""

    manifest = _manifest(release_id="promote-instance-v1")
    root = tmp_path / "release"
    root.mkdir()
    _materialize(root, manifest)

    api = _WriteTrackingApi(commit_sha="d" * 40)
    publisher = HuggingFaceReleasePublisher(
        profile=abby_voice_publication_profile(),
        api=api,
    )
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    approval = _approval(plan, repository_id=publisher.repository_id)
    commit = publisher.publish_append_only(
        plan, approval=approval, local_root=root
    )
    payloads = {
        item.remote_path: (root / item.relative_path).read_bytes()
        for item in plan.operations
    }
    cache = tmp_path / "cache"
    cache.mkdir()
    publisher.redownload_and_validate_pinned(
        commit_sha=commit.commit_sha,
        plan=plan,
        cache_root=cache,
        remote_payloads=payloads,
    )
    pointer = publisher.canary_promote_pointer(
        commit_receipt=commit,
        previous=None,
        canary_percent=5,
        approval=approval,
    )
    assert pointer.commit_sha == commit.commit_sha


def test_mismatched_pinned_commit_blocks_promotion(tmp_path: Path) -> None:
    manifest = _manifest(release_id="promote-mismatch-v1")
    root = tmp_path / "release"
    root.mkdir()
    _materialize(root, manifest)

    api = _WriteTrackingApi(commit_sha="e" * 40)
    publisher = HuggingFaceReleasePublisher(
        profile=patent_legal_publication_profile(),
        api=api,
    )
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    approval = _approval(plan, repository_id=publisher.repository_id)
    commit = publisher.publish_append_only(
        plan, approval=approval, local_root=root
    )
    payloads = {
        item.remote_path: (root / item.relative_path).read_bytes()
        for item in plan.operations
    }
    cache = tmp_path / "cache"
    cache.mkdir()
    # Validate a different commit SHA than the publish receipt.
    other = PublicationCommitReceipt(
        repository_id=commit.repository_id,
        commit_sha="f" * 40,
        release_id=commit.release_id,
        release_prefix=commit.release_prefix,
        plan_digest=commit.plan_digest,
        parent_commit=commit.parent_commit,
        target_revision=commit.target_revision,
        uploaded_paths=commit.uploaded_paths,
        upload_bytes=commit.upload_bytes,
        approval_id=commit.approval_id,
    )
    # Force a validation receipt for the published commit, then try to promote
    # while claiming a mismatched commit via a forged pinned object.
    good = publisher.redownload_and_validate_pinned(
        commit_sha=commit.commit_sha,
        plan=plan,
        cache_root=cache,
        remote_payloads=payloads,
    )
    forged = type(good)(
        commit_sha="f" * 40,
        repository_id=good.repository_id,
        cache_root=good.cache_root,
        revalidated_paths=good.revalidated_paths,
        revalidated_file_count=good.revalidated_file_count,
        revalidated_bytes=good.revalidated_bytes,
        empty_cache_before_fetch=good.empty_cache_before_fetch,
        network_fetch_performed=good.network_fetch_performed,
        ok=True,
    )
    with pytest.raises(HuggingFacePublicationError, match="commit_sha"):
        publisher.canary_promote_pointer(
            commit_receipt=commit,
            previous=None,
            canary_percent=5,
            approval=approval,
            pinned_redownload=forged,
        )
    # Using the matching commit still works via the instance cache even if
    # someone supplies a bad forged receipt when the commit is already verified.
    # Explicit forged receipt is checked first and must fail (above).
    del other  # silence unused when gate raises as expected


def test_live_publish_generic_profile_stops_before_promotion(tmp_path: Path) -> None:
    manifest = _manifest(release_id="live-generic-v1")
    root = tmp_path / "release"
    root.mkdir()
    _materialize(root, manifest)
    api = _WriteTrackingApi(commit_sha="1" * 40)
    profile = patent_legal_publication_profile()
    publisher = HuggingFaceReleasePublisher(profile=profile, api=api)
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    approval = _approval(plan, repository_id=profile.repository_id)

    payloads = {
        item.remote_path: (root / item.relative_path).read_bytes()
        for item in plan.operations
    }
    remote_objects = {
        item.remote_path: {
            "sha256": item.sha256,
            "size_bytes": item.size_bytes,
            "commit_sha": "1" * 40,
        }
        for item in plan.operations
    }
    receipt = publish_huggingface_release(
        profile=profile,
        manifest=manifest,
        dry_run=False,
        local_root=root,
        approval=approval,
        api=api,
        audited_parent_commit=AUDITED_PARENT,
        remote_objects=remote_objects,
        remote_payloads=payloads,
        verified_cache_root=tmp_path / "verified",
    )
    assert receipt["status"] == "published_pending_promotion"
    assert receipt["evidence"]["pinned_redownload_validation"] is True
    assert receipt["schema_version"] == PATENT_LEGAL_RECEIPT_SCHEMA
    assert "create_commit" in api.calls
    assert "upload_file" not in api.calls


def test_plan_digest_is_deterministic_for_patent_profile(tmp_path: Path) -> None:
    manifest = _manifest(release_id="digest-stable-v1")
    root = tmp_path / "release"
    root.mkdir()
    _materialize(root, manifest)
    profile = patent_legal_publication_profile()
    first = HuggingFaceReleasePublisher(profile=profile).plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    second = HuggingFaceReleasePublisher(profile=profile).plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    assert first.plan_digest == second.plan_digest
    assert len(first.plan_digest) == 64


@pytest.mark.parametrize("mutation", ["rewrite", "delete", "replace"])
def test_publish_uses_anonymous_snapshots_after_source_path_mutation(
    tmp_path: Path,
    mutation: str,
) -> None:
    manifest = _manifest(release_id=f"snapshot-{mutation}-v1")
    root = tmp_path / "release"
    root.mkdir()
    _materialize(root, manifest)
    expected = {
        entry["path"]: (root / entry["path"]).read_bytes()
        for entry in manifest["files"]
    }

    class _MutatingApi(_WriteTrackingApi):
        def create_commit(self, **kwargs):
            for entry in manifest["files"]:
                source = root / entry["path"]
                if mutation == "rewrite":
                    source.write_bytes(b"mutated-in-place")
                elif mutation == "delete":
                    source.unlink()
                else:
                    source.unlink()
                    source.write_bytes(b"replacement-inode")
            return super().create_commit(**kwargs)

    api = _MutatingApi()
    profile = patent_legal_publication_profile()
    publisher = HuggingFaceReleasePublisher(profile=profile, api=api)
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    publisher.publish_append_only(
        plan,
        approval=_approval(plan, repository_id=profile.repository_id),
        local_root=root,
    )
    assert api.remote_files == {
        f"{plan.release_prefix}/{path}": body
        for path, body in expected.items()
    }
    assert api.operation_handles
    assert all(handle.closed for handle in api.operation_handles)


def test_publish_closes_snapshot_handles_when_create_commit_raises(
    tmp_path: Path,
) -> None:
    manifest = _manifest(release_id="snapshot-error-v1")
    root = tmp_path / "release"
    root.mkdir()
    _materialize(root, manifest)

    class _FailingApi(_WriteTrackingApi):
        def create_commit(self, **kwargs):
            self.calls.append("create_commit")
            self.operation_handles = [
                getattr(op, "path_or_fileobj", None)
                for op in kwargs["operations"]
            ]
            assert all(not handle.closed for handle in self.operation_handles)
            raise OSError("simulated transport failure")

    api = _FailingApi()
    profile = patent_legal_publication_profile()
    publisher = HuggingFaceReleasePublisher(profile=profile, api=api)
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    with pytest.raises(HuggingFacePublicationError, match="create_commit failed"):
        publisher.publish_append_only(
            plan,
            approval=_approval(plan, repository_id=profile.repository_id),
            local_root=root,
        )
    assert api.operation_handles
    assert all(handle.closed for handle in api.operation_handles)


def test_short_anonymous_snapshot_write_never_calls_create_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest(release_id="snapshot-short-write-v1")
    root = tmp_path / "release"
    root.mkdir()
    _materialize(root, manifest)

    class _ShortWriteBuffer(io.BytesIO):
        def write(self, body: bytes) -> int:
            if not body:
                return 0
            super().write(body[:-1])
            return len(body) - 1

    monkeypatch.setattr(
        publisher_module.tempfile,
        "TemporaryFile",
        lambda **kwargs: _ShortWriteBuffer(),
    )
    api = _WriteTrackingApi()
    profile = patent_legal_publication_profile()
    publisher = HuggingFaceReleasePublisher(profile=profile, api=api)
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    with pytest.raises(HuggingFacePublicationError, match="short anonymous"):
        publisher.publish_append_only(
            plan,
            approval=_approval(plan, repository_id=profile.repository_id),
            local_root=root,
        )
    assert "create_commit" not in api.calls


def test_commit_operation_upload_info_mismatch_never_calls_create_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest(release_id="snapshot-upload-info-v1")
    root = tmp_path / "release"
    root.mkdir()
    _materialize(root, manifest)

    def forged_operation(**kwargs):
        return {
            "operation": "add",
            "path_in_repo": kwargs["path_in_repo"],
            "path_or_fileobj": kwargs["fileobj"],
            "upload_info": {"size": 0, "sha256": b"\x00" * 32},
        }

    monkeypatch.setattr(
        publisher_module,
        "_build_commit_add_operation",
        forged_operation,
    )
    api = _WriteTrackingApi()
    profile = patent_legal_publication_profile()
    publisher = HuggingFaceReleasePublisher(profile=profile, api=api)
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    with pytest.raises(HuggingFacePublicationError, match="upload_info"):
        publisher.publish_append_only(
            plan,
            approval=_approval(plan, repository_id=profile.repository_id),
            local_root=root,
        )
    assert "create_commit" not in api.calls


def test_publish_refuses_symlink_even_when_target_bytes_match_plan(
    tmp_path: Path,
) -> None:
    manifest = _manifest(release_id="snapshot-nofollow-v1")
    root = tmp_path / "release"
    root.mkdir()
    _materialize(root, manifest)
    entry = manifest["files"][0]
    local = root / entry["path"]
    same_bytes = tmp_path / "same-bytes"
    same_bytes.write_bytes(local.read_bytes())
    local.unlink()
    local.symlink_to(same_bytes)

    api = _WriteTrackingApi()
    profile = patent_legal_publication_profile()
    publisher = HuggingFaceReleasePublisher(profile=profile, api=api)
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    with pytest.raises(HuggingFacePublicationError, match="without following symlinks"):
        publisher.publish_append_only(
            plan,
            approval=_approval(plan, repository_id=profile.repository_id),
            local_root=root,
        )
    assert "create_commit" not in api.calls


def test_publish_refuses_intermediate_parent_symlink_before_any_api(
    tmp_path: Path,
) -> None:
    manifest = _manifest(release_id="snapshot-parent-nofollow-v1")
    root = tmp_path / "release"
    root.mkdir()
    _materialize(root, manifest)
    profile = patent_legal_publication_profile()
    publisher = HuggingFaceReleasePublisher(profile=profile)
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )

    outside = tmp_path / "outside-manifests"
    (root / "manifests").rename(outside)
    (root / "manifests").symlink_to(outside, target_is_directory=True)
    api = _WriteTrackingApi()
    publisher.api = api
    with pytest.raises(HuggingFacePublicationError, match="parent directory"):
        publisher.publish_append_only(
            plan,
            approval=_approval(plan, repository_id=profile.repository_id),
            local_root=root,
        )
    assert api.calls == []


def test_publish_refuses_symlinked_local_root_before_any_api(
    tmp_path: Path,
) -> None:
    manifest = _manifest(release_id="snapshot-root-nofollow-v1")
    real_root = tmp_path / "real-release"
    real_root.mkdir()
    _materialize(real_root, manifest)
    alias_root = tmp_path / "release-alias"
    alias_root.symlink_to(real_root, target_is_directory=True)
    profile = patent_legal_publication_profile()
    api = _WriteTrackingApi()
    publisher = HuggingFaceReleasePublisher(profile=profile, api=api)
    plan = publisher.plan_dry_run(
        manifest,
        local_root=real_root,
        audited_parent_commit=AUDITED_PARENT,
    )
    with pytest.raises(HuggingFacePublicationError, match="local_root.*symlink"):
        publisher.publish_append_only(
            plan,
            approval=_approval(plan, repository_id=profile.repository_id),
            local_root=alias_root,
        )
    assert api.calls == []


def test_publish_recomputes_cost_receipt_from_operation_sizes(
    tmp_path: Path,
) -> None:
    manifest = _manifest(release_id="forged-cost-v1")
    root = tmp_path / "release"
    root.mkdir()
    _materialize(root, manifest)
    profile = patent_legal_publication_profile()
    api = _WriteTrackingApi()
    publisher = HuggingFaceReleasePublisher(profile=profile, api=api)
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    forged = replace(
        plan,
        cost_receipt={
            **plan.cost_receipt,
            "estimated_cost_usd": 0.0,
            "retained_release_bytes": 0,
            "storage_component_usd": 0.0,
            "transfer_component_usd": 0.0,
            "upload_bytes": 0,
        },
    )
    with pytest.raises(HuggingFacePublicationError, match="cost receipt"):
        publisher.publish_append_only(
            forged,
            approval=_approval(forged, repository_id=profile.repository_id),
            local_root=root,
        )
    assert api.calls == []


def test_publish_fails_closed_when_snapshot_filesystem_is_too_small(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest(release_id="snapshot-capacity-v1")
    root = tmp_path / "release"
    root.mkdir()
    _materialize(root, manifest)
    profile = patent_legal_publication_profile()
    api = _WriteTrackingApi()
    publisher = HuggingFaceReleasePublisher(profile=profile, api=api)
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    monkeypatch.setattr(
        publisher_module.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(total=1, used=1, free=0),
    )
    with pytest.raises(HuggingFacePublicationError, match="insufficient free"):
        publisher.publish_append_only(
            plan,
            approval=_approval(plan, repository_id=profile.repository_id),
            local_root=root,
        )
    assert api.calls == []


def test_case_alias_of_state_laws_repo_requires_official_proof(
    tmp_path: Path,
) -> None:
    manifest = _manifest(release_id="state-repo-case-alias-v1")
    root = tmp_path / "release"
    root.mkdir()
    _materialize(root, manifest)
    profile = patent_legal_publication_profile(
        repository_id="JusticeDAO/ipfs_state_laws"
    )
    api = _WriteTrackingApi()
    publisher = HuggingFaceReleasePublisher(profile=profile, api=api)
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    with pytest.raises(HuggingFacePublicationError, match="sealed policy proof"):
        publisher.publish_append_only(
            plan,
            approval=_approval(plan, repository_id=profile.repository_id),
            local_root=root,
        )
    assert api.calls == []


def test_top_level_state_repo_relabel_cannot_bypass_policy(
    tmp_path: Path,
) -> None:
    manifest = _manifest(release_id="state-repo-top-level-relabel-v1")
    root = tmp_path / "release"
    root.mkdir()
    _materialize(root, manifest)
    profile = patent_legal_publication_profile(
        repository_id="justicedao/ipfs_state_laws"
    )
    plan = HuggingFaceReleasePublisher(profile=profile).plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    api = _WriteTrackingApi()
    with pytest.raises(HuggingFacePublicationError, match="sealed policy proof"):
        publish_huggingface_release(
            profile=profile,
            manifest=manifest,
            dry_run=False,
            local_root=root,
            approval=_approval(plan, repository_id=profile.repository_id),
            api=api,
            audited_parent_commit=AUDITED_PARENT,
        )
    assert api.calls == []
