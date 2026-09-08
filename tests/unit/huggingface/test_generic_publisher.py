"""Generic append-only publisher tests across publication profiles (PATLAW-100)."""

from __future__ import annotations

import copy
import io
import json
import tempfile
from contextlib import ExitStack
from dataclasses import fields, replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.huggingface import publisher as publisher_module
from ipfs_datasets_py.huggingface.protected_repo_guard import (
    ProtectedRepoGuardError,
    guarded_write,
)
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


def test_publisher_uses_the_canonical_protected_write_surface() -> None:
    from ipfs_datasets_py.huggingface.protected_repo_guard import (
        PROTECTED_WRITE_METHODS,
    )

    assert publisher_module._WRITE_API_METHODS is PROTECTED_WRITE_METHODS
    assert "move" not in publisher_module._WRITE_API_METHODS
    assert "move_repo" in publisher_module._WRITE_API_METHODS


@pytest.mark.parametrize(
    ("phase", "repository_id", "revision", "method", "operation"),
    [
        (
            "state_staging",
            "justicedao/ipfs_state_laws",
            "stage/state-laws-sparse-graphrag-v2",
            "create_branch",
            "additive_staging_upload",
        ),
        (
            "state_staging",
            "justicedao/ipfs_state_laws",
            "stage/state-laws-sparse-graphrag-v2",
            "create_commit",
            "additive_staging_upload",
        ),
        (
            "state_main",
            "justicedao/ipfs_state_laws",
            "main",
            "create_commit",
            "additive_main_upload",
        ),
        (
            "federal_staging",
            "justicedao/ipfs_federal_register",
            "stage/federal-register-ir-graphrag-v2",
            "create_branch",
            "additive_staging_upload",
        ),
        (
            "federal_staging",
            "justicedao/ipfs_federal_register",
            "stage/federal-register-ir-graphrag-v2",
            "create_commit",
            "additive_staging_upload",
        ),
        (
            "federal_main",
            "justicedao/ipfs_federal_register",
            "main",
            "create_commit",
            "additive_main_upload",
        ),
    ],
)
def test_canonical_phase_contract_is_exact(
    phase: str,
    repository_id: str,
    revision: str,
    method: str,
    operation: str,
) -> None:
    assert publisher_module._canonical_legal_corpora_phase_contract(
        phase,
        repository_id=repository_id,
        revision=revision,
        method=method,
    ) == (phase, operation)


@pytest.mark.parametrize(
    ("phase", "repository_id", "revision", "method"),
    [
        (
            "state_staging",
            "justicedao/ipfs_federal_register",
            "stage/state-laws-sparse-graphrag-v2",
            "create_commit",
        ),
        (
            "federal_staging",
            "justicedao/ipfs_federal_register",
            "stage/alternate",
            "create_commit",
        ),
        (
            "state_main",
            "justicedao/ipfs_state_laws",
            "main",
            "create_branch",
        ),
        (
            " federal_main",
            "justicedao/ipfs_federal_register",
            "main",
            "create_commit",
        ),
        (
            "federal_main",
            "justicedao/ipfs_federal_register",
            "main",
            "create_commit ",
        ),
    ],
)
def test_canonical_phase_contract_rejects_relabelling(
    phase: str,
    repository_id: str,
    revision: str,
    method: str,
) -> None:
    with pytest.raises(HuggingFacePublicationError):
        publisher_module._canonical_legal_corpora_phase_contract(
            phase,
            repository_id=repository_id,
            revision=revision,
            method=method,
        )


def test_canonical_mutation_receipt_has_only_bound_public_fields() -> None:
    receipt = publisher_module.CanonicalLegalCorporaMutationReceipt(
        phase="federal_staging",
        method="create_branch",
        operation="additive_staging_upload",
        repository_id="justicedao/ipfs_federal_register",
        revision="stage/federal-register-ir-graphrag-v2",
        parent_commit="0" * 40,
        resulting_commit_sha="0" * 40,
        plan_digest="1" * 64,
        release_manifest_digest="2" * 64,
        policy_proof_digest="3" * 64,
        payload_digest="4" * 64,
        approval_id="branch-approval",
    )
    assert set(receipt.to_dict()) == {
        "approval_id",
        "method",
        "operation",
        "parent_commit",
        "payload_digest",
        "phase",
        "plan_digest",
        "policy_proof_digest",
        "release_manifest_digest",
        "repository_id",
        "resulting_commit_sha",
        "revision",
        "runtime_authorized",
    }


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


def test_protected_transport_rejects_create_commit_property_without_resolving_it() -> None:
    observed: list[str] = []

    class MaliciousPropertyApi:
        @property
        def create_commit(self):
            observed.append("property-resolved")
            raise AssertionError("descriptor must not run")

    with pytest.raises(HuggingFacePublicationError, match="rejects fake"):
        publisher_module._require_canonical_state_laws_hf_api(
            MaliciousPropertyApi(),
            runtime_token="fixture-runtime-token",
        )
    assert observed == []


def test_protected_transport_rejects_hf_api_subclass_and_instance_alias() -> None:
    from huggingface_hub import HfApi

    alternate_writes: list[str] = []

    class OverriddenHfApi(HfApi):
        def create_commit(self, **kwargs):
            alternate_writes.append(str(kwargs.get("repo_id")))
            return {"commit_sha": "f" * 40}

    with pytest.raises(HuggingFacePublicationError, match="subclassed"):
        publisher_module._require_canonical_state_laws_hf_api(
            OverriddenHfApi(),
            runtime_token="fixture-runtime-token",
        )

    aliased = HfApi()
    aliased.create_commit = lambda **kwargs: alternate_writes.append(
        "justicedao/ipfs_federal_register"
    )
    with pytest.raises(HuggingFacePublicationError, match="overridden attribute"):
        publisher_module._require_canonical_state_laws_hf_api(
            aliased,
            runtime_token="fixture-runtime-token",
        )
    assert alternate_writes == []


def test_protected_transport_copies_only_safe_exact_hf_api_configuration() -> None:
    from huggingface_hub import HfApi

    injected = HfApi(token="fixture-token")
    fresh = publisher_module._require_canonical_state_laws_hf_api(
        injected,
        runtime_token="fixture-token",
    )
    assert type(fresh) is HfApi
    assert fresh is not injected
    assert fresh.endpoint == "https://huggingface.co"
    assert fresh.token == "fixture-token"


def test_protected_transport_binds_runtime_token_and_rejects_headers() -> None:
    from huggingface_hub import HfApi

    fresh = publisher_module._require_canonical_state_laws_hf_api(
        HfApi(token=None),
        runtime_token="exact-runtime-token",
    )
    assert fresh.token == "exact-runtime-token"
    assert fresh.headers is None

    with pytest.raises(HuggingFacePublicationError, match="token configuration"):
        publisher_module._require_canonical_state_laws_hf_api(
            HfApi(token="different-token"),
            runtime_token="exact-runtime-token",
        )
    with pytest.raises(HuggingFacePublicationError, match="headers are unsafe"):
        publisher_module._require_canonical_state_laws_hf_api(
            HfApi(headers={"authorization": "Bearer alternate"}),
            runtime_token="exact-runtime-token",
        )


def test_protected_transport_rejects_global_get_session_drift_before_contact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import huggingface_hub.hf_api as hf_api_module
    from huggingface_hub import HfApi

    contacts: list[str] = []

    def alternate_get_session():
        contacts.append("contact")
        raise AssertionError("drifted transport must not execute")

    monkeypatch.setattr(hf_api_module, "get_session", alternate_get_session)
    with pytest.raises(HuggingFacePublicationError, match="global dependency drifted"):
        publisher_module._require_canonical_state_laws_hf_api(
            HfApi(),
            runtime_token="exact-runtime-token",
        )
    assert contacts == []


def test_protected_transport_discards_cached_session_hooks_and_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in publisher_module._PROTECTED_TRANSPORT_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    publisher_module._CANONICAL_HF_RESET_SESSIONS()
    cached = publisher_module._CANONICAL_HF_GET_SESSION()
    observed: list[str] = []
    cached.hooks["response"].append(lambda response, **kwargs: observed.append("hook"))
    cached.send = lambda *args, **kwargs: observed.append("send")  # type: ignore[method-assign]
    cached.proxies["https"] = "https://alternate.invalid"
    cached.auth = ("alternate", "credential")
    cached.headers["authorization"] = "Bearer alternate"
    cached.cookies.set("session", "alternate")
    cached.adapters["https://"] = object()

    fresh = publisher_module._fresh_canonical_hf_session()

    assert fresh is not cached
    assert type(fresh) is publisher_module._CANONICAL_REQUESTS_SESSION_TYPE
    assert fresh.trust_env is False
    assert fresh.hooks == {"response": []}
    assert fresh.auth is None
    assert fresh.proxies == {}
    assert "authorization" not in fresh.headers
    assert len(fresh.cookies) == 0
    assert tuple(fresh.adapters) == ("https://", "http://")
    assert all(
        type(adapter) is publisher_module._CANONICAL_HF_ADAPTER_TYPE
        for adapter in fresh.adapters.values()
    )
    assert observed == []


def test_protected_transport_rejects_session_factory_and_cache_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contacts: list[str] = []

    def alternate_factory():
        contacts.append("factory")
        return publisher_module._CANONICAL_REQUESTS_SESSION_TYPE()

    monkeypatch.setattr(
        publisher_module._CANONICAL_HF_HTTP_MODULE,
        "_GLOBAL_BACKEND_FACTORY",
        alternate_factory,
    )
    with pytest.raises(HuggingFacePublicationError, match="factory/cache identity"):
        publisher_module._fresh_canonical_hf_session()
    assert contacts == []
    monkeypatch.setattr(
        publisher_module._CANONICAL_HF_HTTP_MODULE,
        "_GLOBAL_BACKEND_FACTORY",
        publisher_module._CANONICAL_HF_BACKEND_FACTORY,
    )
    monkeypatch.setattr(
        publisher_module._CANONICAL_HF_HTTP_MODULE,
        "_get_session_from_cache",
        lambda **kwargs: alternate_factory(),
    )
    with pytest.raises(HuggingFacePublicationError, match="factory/cache identity"):
        publisher_module._fresh_canonical_hf_session()
    assert contacts == []


def test_protected_transport_rejects_proxy_environment_before_contact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in publisher_module._PROTECTED_TRANSPORT_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "https://alternate.invalid")

    with pytest.raises(HuggingFacePublicationError, match="environment configuration"):
        publisher_module._canonical_hf_api_create_commit(
            "exact-runtime-token",
            repo_id="justicedao/ipfs_state_laws",
            repo_type="dataset",
            operations=(),
            commit_message="must not contact",
            revision="main",
            parent_commit="0" * 40,
        )


@pytest.mark.parametrize("token_role", ["read", "fineGrained"])
def test_state_laws_whoami_rejects_non_write_tokens(token_role: str) -> None:
    identity = {
        "auth": {"accessToken": {"role": token_role}},
        "name": "fixture-bot",
        "orgs": [{"name": "JusticeDAO", "roleInOrg": "admin"}],
    }
    with pytest.raises(HuggingFacePublicationError, match="not explicitly write-capable"):
        publisher_module._state_laws_write_authority_from_whoami(
            identity,
            repository_id="justicedao/ipfs_state_laws",
        )


def test_state_laws_whoami_requires_owner_write_role() -> None:
    identity = {
        "auth": {"accessToken": {"role": "write"}},
        "name": "fixture-bot",
        "orgs": [{"name": "JusticeDAO", "roleInOrg": "read"}],
    }
    with pytest.raises(HuggingFacePublicationError, match="JusticeDAO role"):
        publisher_module._state_laws_write_authority_from_whoami(
            identity,
            repository_id="justicedao/ipfs_state_laws",
        )


def test_prepared_executor_retains_no_proof_plan_profile_or_api_hooks() -> None:
    prepared_type = publisher_module._PreparedStateLawsCanonicalCommitExecutor
    assert {field.name for field in fields(prepared_type)} == {
        "canonical_candidate_digest",
        "canonical_message",
        "mutation_binding",
        "operations_payload",
        "runtime_token",
    }
    unsafe_names = {
        "api",
        "live_policy_proof",
        "local_root",
        "plan",
        "profile",
        "publisher",
        "_canonical_state_laws_parent_and_prefix_empty",
        "_verify_state_laws_live_policy",
    }
    assert unsafe_names.isdisjoint(prepared_type.__call__.__code__.co_names)
    closure = {
        name: cell.cell_contents
        for name, cell in zip(
            prepared_type.__call__.__code__.co_freevars,
            prepared_type.__call__.__closure__ or (),
            strict=True,
        )
    }
    assert closure == {
        "create_branch": publisher_module._canonical_hf_api_create_branch,
        "create_commit": publisher_module._canonical_hf_api_create_commit,
        "protected_write": publisher_module.guarded_write,
        "rehash_files": publisher_module._rehash_prepared_snapshot_files,
        "require_guard": publisher_module.require_unprotected_or_runtime,
        "revalidate_remote": (
            publisher_module
            ._canonical_revalidate_compound_parent_prefix_and_readme
        ),
    }
    assert {
        "create_branch_local",
        "create_commit_local",
        "protected_write_local",
        "rehash_files_local",
        "require_guard_local",
        "revalidate_remote_local",
    }.issubset(
        set(prepared_type.__call__.__code__.co_varnames)
        | set(prepared_type.__call__.__code__.co_cellvars)
    )


@pytest.mark.parametrize(
    "helper_name",
    [
        "require_unprotected_or_runtime",
        "_rehash_prepared_snapshot_files",
        "_canonical_revalidate_compound_parent_prefix_and_readme",
        "guarded_write",
        "_canonical_hf_api_create_branch",
        "_canonical_hf_api_create_commit",
    ],
)
def test_prepared_executor_never_resolves_rebound_write_helper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    helper_name: str,
) -> None:
    manifest = _manifest(release_id=f"prepared-helper-{helper_name}-v1")
    root = tmp_path / "release"
    root.mkdir()
    _materialize(root, manifest)
    plan = HuggingFaceReleasePublisher(
        profile=patent_legal_publication_profile()
    ).plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )

    with ExitStack() as stack:
        operations = []
        for item in plan.operations:
            handle = stack.enter_context(tempfile.TemporaryFile(mode="w+b"))
            handle.write((root / item.relative_path).read_bytes())
            handle.flush()
            handle.seek(0)
            operations.append(
                publisher_module._CANONICAL_COMMIT_ADD_TYPE(
                    path_in_repo=item.remote_path,
                    path_or_fileobj=handle,
                )
            )
        files = publisher_module._rehash_anonymous_snapshot_files(
            operations,
            plan,
        )
        binding = publisher_module.CanonicalMutationBinding(
            method="create_commit",
            repository_id="justicedao/ipfs_state_laws",
            repository_type="dataset",
            revision="main",
            parent_commit=AUDITED_PARENT,
            files=files,
            plan_digest="1" * 64,
            release_manifest_digest="2" * 64,
            policy_proof_digest="3" * 64,
            commit_message_digest=sha256(b"message").hexdigest(),
        )
        prepared = publisher_module._PreparedStateLawsCanonicalCommitExecutor(
            canonical_candidate_digest="4" * 64,
            canonical_message="message",
            mutation_binding=binding,
            operations_payload=tuple(operations),
            runtime_token="runtime-token",
        )
        contacts: list[str] = []

        def rebound_helper(*_args, **_kwargs):
            contacts.append(helper_name)
            raise AssertionError("rebound helper must not be reached")

        monkeypatch.setattr(publisher_module, helper_name, rebound_helper)
        with pytest.raises(ProtectedRepoGuardError, match="must enter"):
            prepared()
        assert contacts == []


def _seal_state_control_receipt(runtime_module, payload: dict) -> dict:
    body = dict(payload)
    body["schema"] = runtime_module.RECEIPT_SCHEMA_V1
    body["canonical_digest"] = runtime_module.canonical_no_self_field_digest(
        body
    )
    return body


def _state_publication_binding_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from ipfs_datasets_py.processors.legal_data import (
        legal_corpora_publication_runtime as runtime_module,
    )
    from ipfs_datasets_py.processors.legal_data import (
        state_laws_publication_package as package_module,
    )

    canonical_root = tmp_path / "canonical"
    release_root = tmp_path / "release"
    canonical_root.mkdir()
    release_root.mkdir()
    release_digest = "a" * 64
    plan_digest = "b" * 64
    proof_digest = "c" * 64
    staging_revision = "d" * 40
    admitted_ids = [f"state-source-{index:02d}" for index in range(51)]

    rights_body = {
        "admitted_record_ids": admitted_ids,
        "authorizing_for_publication": True,
        "catalog_digest_sha256": "e" * 64,
        "evidence_mode": "live",
        "fixture_only_non_authorizing": False,
        "mode": "live",
        "report_schema": (
            "ipfs_datasets_py/legal-source-rights-compliance@2"
        ),
        "status": "passed",
    }
    rights_body["report_digest_sha256"] = sha256(
        package_module.canonical_json_bytes(rights_body)
    ).hexdigest()
    rights_bytes = package_module.canonical_json_bytes(rights_body) + b"\n"
    for root in (release_root, canonical_root):
        rights_path = root / package_module.SOURCE_RIGHTS_RECEIPT_RELPATH
        rights_path.parent.mkdir(parents=True, exist_ok=True)
        rights_path.write_bytes(rights_bytes)

    manifest = {
        "fixture_only": False,
        "jurisdictions": list(package_module.CANONICAL_JURISDICTION_ORDER),
        "mode": "production",
        "release_point": "production-release",
        "source_rights_receipt": {"admitted_record_ids": admitted_ids},
    }
    manifest_path = release_root / "manifest.json"
    manifest_path.write_bytes(
        package_module.canonical_json_bytes(manifest) + b"\n"
    )
    package = SimpleNamespace(
        manifest_path=manifest_path,
        output_root=release_root,
    )
    plan = SimpleNamespace(
        audited_parent_commit="78cba0ed86c3971a7b90620c6df167af8a1a6fb2",
        plan_digest=plan_digest,
        release_prefix=f"data/state_laws/sha256-{release_digest}",
        release_sha256=release_digest,
        repository_id="justicedao/ipfs_state_laws",
    )
    sealed_proof = SimpleNamespace(
        authorized=True,
        proof_digest=proof_digest,
        request={
            "authorize_mutation": True,
            "staging_canary_passed": True,
            "staging_redownload_verified": True,
            "staging_revision": staging_revision,
        },
    )
    monkeypatch.setattr(
        package_module,
        "verify_state_laws_publication_package_identity",
        lambda _package: None,
    )
    monkeypatch.setattr(
        package_module,
        "_verify_state_laws_plan_binding",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        package_module,
        "verify_state_laws_live_policy_proof",
        lambda *_args, **_kwargs: sealed_proof,
    )
    monkeypatch.setattr(
        package_module,
        "state_laws_publication_profile",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(
        package_module,
        "require_live_source_rights_receipt",
        lambda _receipt: None,
    )
    monkeypatch.setattr(
        package_module,
        "validate_exact_51_coverage",
        lambda _jurisdictions: None,
    )

    checked_bindings: list[object] = []

    def _strict_candidate_check(
        candidate_bytes: bytes,
        *,
        repository_root: Path,
        phase: str,
    ) -> dict:
        assert repository_root == canonical_root
        payload = json.loads(candidate_bytes.decode("utf-8"))
        for flag in (
            "authorizing_for_publication",
            "authorizing_for_release",
            "hub_upload",
            "hub_mutation_performed",
        ):
            if payload.get(flag) is not False:
                raise package_module.StateLawsPublicationPackageError(
                    f"unsafe candidate flag: {flag}"
                )
        if payload.get("schema") != runtime_module.PRODUCTION_MANIFEST_SCHEMA_V2:
            raise package_module.StateLawsPublicationPackageError(
                "candidate is not @2"
            )
        report_digest = package_module._lcr084_candidate_report_digest(payload)
        staging_digest = package_module._lcr084_staging_candidate_digest(payload)
        if payload.get("report_digest_sha256") != report_digest:
            raise package_module.StateLawsPublicationPackageError(
                "candidate report digest mismatch"
            )
        binding = payload.get("publication_binding")
        checked_bindings.append(copy.deepcopy(binding))
        if phase == "state_staging":
            if binding is not None:
                raise package_module.StateLawsPublicationPackageError(
                    "staging publication_binding must be null"
                )
        elif phase == "state_main":
            expected_keys = {
                "plan_digest",
                "policy_proof_digest",
                "release_manifest_digest",
                "staging_candidate_digest",
            }
            if type(binding) is not dict or set(binding) != expected_keys:
                raise package_module.StateLawsPublicationPackageError(
                    "main publication_binding is malformed"
                )
            if any(
                type(binding[key]) is not str
                or len(binding[key]) != 64
                or any(character not in "0123456789abcdef" for character in binding[key])
                for key in expected_keys
            ):
                raise package_module.StateLawsPublicationPackageError(
                    "main publication_binding digest is malformed"
                )
            if (
                binding["release_manifest_digest"]
                != payload.get("manifest_digest")
                or binding["staging_candidate_digest"] != staging_digest
            ):
                raise package_module.StateLawsPublicationPackageError(
                    "main publication_binding chain mismatch"
                )
        else:
            raise package_module.StateLawsPublicationPackageError(
                f"unsupported phase: {phase}"
            )
        return {
            "checked": {
                "jurisdiction_count": 51,
                "ok": True,
                "task_id": "LCR-084",
                "valid": True,
            },
            "phase": phase,
            "report_digest_sha256": report_digest,
            "staging_candidate_digest": staging_digest,
        }

    monkeypatch.setattr(
        package_module,
        "_check_lcr084_candidate_in_subprocess",
        _strict_candidate_check,
    )
    candidate = {
        "authorizing_for_publication": False,
        "authorizing_for_release": False,
        "dataset_repo_id": plan.repository_id,
        "hub_mutation_performed": False,
        "hub_upload": False,
        "manifest_digest": release_digest,
        "publication_binding": None,
        "report_digest_sha256": "0" * 64,
        "schema": runtime_module.PRODUCTION_MANIFEST_SCHEMA_V2,
        "source_rights_catalog_digest": rights_body[
            "catalog_digest_sha256"
        ],
        "source_rights_receipt_digest": rights_body[
            "report_digest_sha256"
        ],
    }
    candidate["report_digest_sha256"] = (
        package_module._lcr084_candidate_report_digest(candidate)
    )
    candidate_path = canonical_root / runtime_module.STATE_CANDIDATE_MANIFEST_RELPATH
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_bytes(
        package_module.canonical_json_bytes(candidate) + b"\n"
    )
    staging_digest = package_module._lcr084_staging_candidate_digest(candidate)
    receipt_paths = {}
    for relative_path, include_revision in (
        (package_module.STATE_LAWS_STAGING_UPLOAD_RELPATH, False),
        (package_module.STATE_LAWS_STAGING_CANARY_RELPATH, True),
    ):
        receipt = {
            "dataset_repo_id": plan.repository_id,
            "dirty": False,
            "final_manifest_digest": staging_digest,
            "fixture_only": False,
            "release_manifest_digest": release_digest,
            "status": "passed",
        }
        if include_revision:
            receipt["staging_revision"] = staging_revision
        receipt = _seal_state_control_receipt(runtime_module, receipt)
        receipt_path = canonical_root / relative_path
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(
            json.dumps(receipt, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        receipt_paths[relative_path] = receipt_path
    return SimpleNamespace(
        candidate=candidate,
        candidate_path=candidate_path,
        canonical_root=canonical_root,
        checked_bindings=checked_bindings,
        package=package,
        package_module=package_module,
        plan=plan,
        proof=sealed_proof,
        receipt_paths=receipt_paths,
        release_digest=release_digest,
        runtime=runtime_module,
        staging_digest=staging_digest,
        staging_revision=staging_revision,
    )


def test_state_main_controls_promote_only_publication_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _state_publication_binding_fixture(tmp_path, monkeypatch)
    viewer_card = b"viewer control\n"
    monkeypatch.setattr(
        fixture.package_module,
        "state_laws_viewer_control_card_bytes",
        lambda *_args, **_kwargs: viewer_card,
    )
    monkeypatch.setattr(
        fixture.package_module,
        "verify_state_laws_viewer_control_plan",
        lambda *_args, **_kwargs: SimpleNamespace(
            sha256=sha256(viewer_card).hexdigest()
        ),
    )
    before = copy.deepcopy(fixture.candidate)
    bundle = fixture.package_module.materialize_state_laws_canonical_controls(
        fixture.package,
        fixture.plan,
        fixture.proof,
        repository_root=fixture.canonical_root,
        sealed_at="2020-01-01T00:00:00Z",
    )
    main = json.loads(fixture.candidate_path.read_text(encoding="utf-8"))
    assert fixture.checked_bindings == [None, main["publication_binding"]]
    assert main["publication_binding"] == {
        "plan_digest": fixture.plan.plan_digest,
        "policy_proof_digest": fixture.proof.proof_digest,
        "release_manifest_digest": fixture.release_digest,
        "staging_candidate_digest": fixture.staging_digest,
    }
    assert {
        key for key in main if main[key] != before[key]
    } == {"publication_binding", "report_digest_sha256"}
    assert main["report_digest_sha256"] == bundle.candidate_manifest_digest
    assert bundle.staging_candidate_digest == fixture.staging_digest
    assert bundle.candidate_manifest_digest != fixture.staging_digest
    for flag in (
        "authorizing_for_publication",
        "authorizing_for_release",
        "hub_upload",
        "hub_mutation_performed",
    ):
        assert main[flag] is False
    seal = json.loads(
        (fixture.canonical_root / bundle.seal_path).read_text(encoding="utf-8")
    )
    assert seal["final_manifest_digest"] == bundle.candidate_manifest_digest
    assert seal["release_manifest_digest"] == fixture.release_digest


def test_state_main_controls_reject_at1_candidate_bypass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _state_publication_binding_fixture(tmp_path, monkeypatch)
    candidate = dict(fixture.candidate)
    candidate["schema"] = fixture.runtime.MANIFEST_SCHEMA_V1
    fixture.candidate_path.write_text(
        json.dumps(candidate, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        fixture.package_module.StateLawsPublicationPackageError,
        match="@2 candidate|@1 manifest",
    ):
        fixture.package_module.materialize_state_laws_canonical_controls(
            fixture.package,
            fixture.plan,
            fixture.proof,
            repository_root=fixture.canonical_root,
            sealed_at="2020-01-01T00:00:00Z",
        )


@pytest.mark.parametrize(
    ("receipt_name", "field", "value", "message"),
    [
        ("upload", "final_manifest_digest", "1" * 64, "candidate A"),
        ("canary", "release_manifest_digest", "2" * 64, "release manifest"),
        ("canary", "staging_revision", "3" * 40, "staging revision"),
    ],
)
def test_state_main_controls_reject_staging_chain_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    receipt_name: str,
    field: str,
    value: str,
    message: str,
) -> None:
    fixture = _state_publication_binding_fixture(tmp_path, monkeypatch)
    relative_path = (
        fixture.package_module.STATE_LAWS_STAGING_UPLOAD_RELPATH
        if receipt_name == "upload"
        else fixture.package_module.STATE_LAWS_STAGING_CANARY_RELPATH
    )
    path = fixture.receipt_paths[relative_path]
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt[field] = value
    receipt.pop("canonical_digest", None)
    receipt = _seal_state_control_receipt(fixture.runtime, receipt)
    path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(
        fixture.package_module.StateLawsPublicationPackageError,
        match=message,
    ):
        fixture.package_module.materialize_state_laws_canonical_controls(
            fixture.package,
            fixture.plan,
            fixture.proof,
            repository_root=fixture.canonical_root,
            sealed_at="2020-01-01T00:00:00Z",
        )


def test_untrusted_policy_hook_runs_before_authority_and_cannot_steal_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.unit.processors.legal_data.test_state_laws_publication_package import (
        _materialize_local_release,
        _sealed_live_policy_fixture,
        _stub_authoritative_live_rights,
    )

    _stub_authoritative_live_rights.__wrapped__(monkeypatch)
    root = tmp_path / "state-release"
    _materialize_local_release(root, fixture_only=False)
    dry_run, proof, approval = _sealed_live_policy_fixture(root)
    api = _WriteTrackingApi()
    attempts: list[str] = []
    writes: list[str] = []

    def stealing_verifier(**_kwargs) -> None:
        attempts.append("proof-hook")
        with pytest.raises(ProtectedRepoGuardError, match="must enter"):
            guarded_write(
                "justicedao/ipfs_state_laws",
                "create_commit",
                lambda: writes.append("stolen"),
                expected_phase="state_main",
                expected_operation="additive_main_upload",
                expected_manifest_digest="1" * 64,
                expected_payload_digest="2" * 64,
            )

    monkeypatch.setattr(
        publisher_module,
        "_verify_state_laws_live_policy",
        stealing_verifier,
    )
    publisher = HuggingFaceReleasePublisher(profile=dry_run.profile, api=api)
    with pytest.raises(
        HuggingFacePublicationError,
        match="unobserved root README state cannot authorize a State-main mutation",
    ):
        publisher.publish_append_only(
            dry_run.plan,
            approval=approval,
            local_root=root,
            live_policy_proof=proof,
        )
    assert attempts == ["proof-hook"]
    assert writes == []
    assert api.calls == []


def test_anonymous_snapshot_rehash_detects_post_plan_byte_mutation(
    tmp_path: Path,
) -> None:
    manifest = _manifest(release_id="snapshot-rehash-v1")
    root = tmp_path / "release"
    root.mkdir()
    _materialize(root, manifest)
    profile = patent_legal_publication_profile()
    plan = HuggingFaceReleasePublisher(profile=profile).plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )

    with ExitStack() as stack:
        operations = []
        handles = []
        for item in plan.operations:
            handle = stack.enter_context(tempfile.TemporaryFile(mode="w+b"))
            handle.write((root / item.relative_path).read_bytes())
            handle.flush()
            handle.seek(0)
            handles.append(handle)
            operations.append(
                publisher_module._CANONICAL_COMMIT_ADD_TYPE(
                    path_in_repo=item.remote_path,
                    path_or_fileobj=handle,
                )
            )
        verified = publisher_module._rehash_anonymous_snapshot_files(
            operations,
            plan,
        )
        assert tuple(item.local_sha256 for item in verified) == tuple(
            item.sha256 for item in plan.operations
        )

        mutation_binding = publisher_module.CanonicalMutationBinding(
            method="create_commit",
            repository_id="justicedao/ipfs_state_laws",
            repository_type="dataset",
            revision="main",
            parent_commit=AUDITED_PARENT,
            files=verified,
            plan_digest="1" * 64,
            release_manifest_digest="2" * 64,
            policy_proof_digest="3" * 64,
            commit_message_digest=sha256(b"message").hexdigest(),
        )

        class TokenText(str):
            pass

        with pytest.raises(HuggingFacePublicationError, match="exact and inert"):
            publisher_module._PreparedStateLawsCanonicalCommitExecutor(
                canonical_candidate_digest="4" * 64,
                canonical_message="message",
                mutation_binding=mutation_binding,
                operations_payload=tuple(operations),
                runtime_token=TokenText("runtime-token"),
            )
        with pytest.raises(HuggingFacePublicationError, match="exact and inert"):
            publisher_module._PreparedStateLawsCanonicalCommitExecutor(
                canonical_candidate_digest="4" * 64,
                canonical_message="message",
                mutation_binding=mutation_binding,
                operations_payload=operations,
                runtime_token="runtime-token",
            )

        upload_info = vars(operations[0])["upload_info"]
        original_sample = vars(upload_info)["sample"]
        vars(upload_info)["sample"] = b"tampered"
        with pytest.raises(HuggingFacePublicationError, match="differ"):
            publisher_module._rehash_anonymous_snapshot_files(operations, plan)
        vars(upload_info)["sample"] = original_sample

        handles[0].seek(0)
        handles[0].write(b"X" * plan.operations[0].size_bytes)
        handles[0].flush()
        handles[0].seek(0)
        with pytest.raises(HuggingFacePublicationError, match="differ"):
            publisher_module._rehash_anonymous_snapshot_files(operations, plan)


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
