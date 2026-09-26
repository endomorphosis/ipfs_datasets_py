"""Offline metadata fixtures: no Hub, payload download, training or authority."""
from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
import socket
import subprocess
from types import SimpleNamespace

import pytest
import huggingface_hub
from huggingface_hub.hf_api import ModelInfo, RepoFile, RepoFolder

from ipfs_datasets_py.huggingface import autoencoder_remote_metadata as remote
from ipfs_datasets_py.huggingface import publisher
from tests.unit.huggingface.test_autoencoder_release import checkpoint, compact_checkpoint, build


COMMIT = "a" * 40
VARIANT = {"source_languages": ["en"], "target_logic": "typed_deontic"}


def git_blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def inventory(package, *, lfs_checkpoint=True):
    records, folders = [], set()
    for item in package.publication_plan.operations:
        raw = (package.release_root / item.relative_path).read_bytes()
        lfs = None
        if lfs_checkpoint and item.relative_path in {"state.json", "state.compact"}:
            lfs = {"size": len(raw), "oid": hashlib.sha256(raw).hexdigest(), "pointerSize": 132}
        records.append(RepoFile(path=item.remote_path, size=len(raw), oid=git_blob(raw), lfs=lfs))
        parent = Path(item.relative_path).parent
        while parent != Path("."):
            folders.add(package.publication_plan.release_prefix + "/" + parent.as_posix())
            parent = parent.parent
    records.extend(RepoFolder(path=name, oid="b" * 40) for name in sorted(folders))
    return list(reversed(records))


class MetadataApi:
    def __init__(self, package, records=None):
        self.package = package
        self.records = inventory(package) if records is None else records
        self.calls = []
        self.info_records = [ModelInfo(id=package.publication_plan.repository_id, sha=COMMIT, private=True) for _ in range(2)]
        self.on_tree = None
        self.iterated = 0

    def repo_info(self, *args, **kwargs):
        assert not args
        assert kwargs == {"repo_id": self.package.publication_plan.repository_id, "repo_type": "model", "revision": COMMIT,
                          "expand": ["sha", "private"]}
        self.calls.append(("repo_info", dict(kwargs)))
        index = sum(name == "repo_info" for name, _ in self.calls) - 1
        assert index < 2, "unexpected metadata retry"
        return self.info_records[index]

    def list_repo_tree(self, *args, **kwargs):
        assert not args
        assert kwargs == {"repo_id": self.package.publication_plan.repository_id,
            "path_in_repo": self.package.publication_plan.release_prefix, "recursive": True,
            "expand": False, "revision": COMMIT, "repo_type": "model"}
        self.calls.append(("list_repo_tree", dict(kwargs)))
        if self.on_tree is not None:
            self.on_tree()
        for row in self.records:
            self.iterated += 1
            yield row

    def __getattr__(self, name):
        raise AssertionError(f"unapproved API method: {name}")


@pytest.fixture(autouse=True)
def no_network_or_publication(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("network/download/credential/approval/publication boundary was used")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    for name in ("hf_hub_download", "snapshot_download", "get_token"):
        monkeypatch.setattr(huggingface_hub, name, forbidden)
    monkeypatch.setattr(publisher, "PublicationApproval", forbidden)
    for name in ("publish_append_only", "redownload_and_validate_pinned", "inventory_remote_objects_at_commit"):
        monkeypatch.setattr(publisher.HuggingFaceReleasePublisher, name, forbidden)


@pytest.fixture(params=["legacy", "compact"])
def package_case(request, checkpoint, compact_checkpoint, tmp_path):
    selected = checkpoint if request.param == "legacy" else compact_checkpoint
    evaluations = []
    for index in range(2):
        path = tmp_path / f"evaluation-{index}.json"
        path.write_bytes((f'{{"fixture":{index},"evaluation_matches_final":false,"admitted":false}}\n').encode())
        evaluations.append(path)
    return build(selected, tmp_path / "package", evaluation_receipts=evaluations, audited_parent_commit="c" * 40), selected[1]


@pytest.fixture
def legacy_case(checkpoint, tmp_path):
    return build(checkpoint, tmp_path / "package"), checkpoint[1]


def verify(case, api, **changes):
    package, version = case
    kwargs = {"expected_manifest_sha256": package.package_manifest_sha256,
        "expected_version_record": version, "expected_variant_manifest": VARIANT,
        "expected_repository_id": package.publication_plan.repository_id, "commit_sha": COMMIT, "api": api}
    kwargs.update(changes)
    return remote.verify_private_resume_release_metadata(package.package_root, **kwargs)


def package_files(root):
    return {path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


def assert_binding(result, package, *, verified):
    plan = package.publication_plan
    for field, expected in {"repository_id": plan.repository_id, "repository_type": "model", "commit_sha": COMMIT,
        "package_manifest_sha256": package.package_manifest_sha256, "publication_plan_digest": plan.plan_digest,
        "release_id": plan.release_id, "release_prefix": plan.release_prefix}.items():
        assert result[field] == expected
    assert result["status"] == ("metadata_verified" if verified else "verification_pending")
    assert result["metadata_identity_verified"] is verified
    assert result["remote_bytes_downloaded"] == 0
    for field in ("bytes_verified", "publication_outcome_established", "publication_acknowledged", "pointer_promoted", "admitted"):
        assert result[field] is False


def test_exact_mixed_metadata_uses_only_pinned_reads_and_preserves_package(package_case):
    package, _ = package_case
    api = MetadataApi(package)
    before, plan = package_files(package.package_root), copy.deepcopy(package.publication_plan.to_dict())
    result = verify(package_case, api)
    assert_binding(result, package, verified=True)
    assert [name for name, _ in api.calls] == ["repo_info", "list_repo_tree", "repo_info"]
    assert api.iterated == len(api.records)
    assert package_files(package.package_root) == before
    assert package.publication_plan.to_dict() == plan
    assert plan["metadata"]["remote_privacy_verified"] is False
    assert plan["metadata"]["upload_ready"] is False
    assert plan["metadata"]["approval_status"] == "exact_plan_human_approval_required"
    assert result["all_remote_file_sha256_available"] is False
    rows = {row["remote_path"]: row for row in result["files"]}
    assert set(rows) == {item.remote_path for item in package.publication_plan.operations}
    for item in package.publication_plan.operations:
        row = rows[item.remote_path]
        raw = (package.release_root / item.relative_path).read_bytes()
        assert row["expected_sha256"] == item.sha256
        assert row["expected_git_blob_sha1"] == git_blob(raw)
        assert row["identity_verified"] is True and row["pending_reason"] is None
        if item.relative_path in {"state.json", "state.compact"}:
            assert row["identity_method"] == "lfs_sha256"
            assert row["remote_lfs_sha256"] == item.sha256
        else:
            assert row["identity_method"] == "git_blob_sha1"
            assert row["remote_git_blob_sha1"] == git_blob(raw)
            assert row["remote_lfs_sha256"] is None
    assert not {"README.md", "publication-plan.json", "package-manifest.json"} & set(rows)


def test_regular_git_metadata_matches_actual_git_hash_object_oracle(legacy_case):
    package, _ = legacy_case
    known = subprocess.run(["git", "hash-object", "--stdin"], input=b"hello\n", capture_output=True, check=True)
    assert known.stdout.strip() == b"ce013625030ba8dba906f756967f9e9ca394464a"
    rows = inventory(package, lfs_checkpoint=False)
    for row in rows:
        if type(row) is RepoFile:
            relative = row.path.removeprefix(package.publication_plan.release_prefix + "/")
            raw = (package.release_root / relative).read_bytes()
            row.blob_id = subprocess.run(["git", "hash-object", "--stdin"], input=raw, capture_output=True, check=True).stdout.decode().strip()
    result = verify(legacy_case, MetadataApi(package, rows))
    assert_binding(result, package, verified=True)
    assert all(row["identity_method"] == "git_blob_sha1" for row in result["files"])


@pytest.mark.parametrize("kind,missing", [(kind, missing) for kind in ("git", "lfs") for missing in (None, "")])
def test_missing_identity_is_pending_without_fallback_or_write(legacy_case, kind, missing):
    package, _ = legacy_case
    api = MetadataApi(package, inventory(package, lfs_checkpoint=kind == "lfs"))
    target = next(row for row in api.records if type(row) is RepoFile and row.path.endswith("state.json"))
    if kind == "git":
        target.blob_id = missing
    else:
        target.lfs.sha256 = target.lfs["sha256"] = missing
        assert target.blob_id  # Must not rescue an incomplete LFS descriptor.
    before = package_files(package.package_root)
    result = verify(legacy_case, api)
    assert_binding(result, package, verified=False)
    pending, = [row for row in result["files"] if row["identity_verified"] is False]
    assert pending["remote_path"] == target.path
    assert pending["pending_reason"] == ("missing_git_blob_sha1" if kind == "git" else "missing_lfs_sha256")
    assert pending["remote_git_blob_sha1" if kind == "git" else "remote_lfs_sha256"] is None
    assert package_files(package.package_root) == before


@pytest.mark.parametrize("pointer", [None, "", "d" * 40])
def test_valid_lfs_digest_does_not_claim_pointer_oid_hashes_payload(legacy_case, pointer):
    package, _ = legacy_case
    api = MetadataApi(package)
    target = next(row for row in api.records if type(row) is RepoFile and row.lfs is not None)
    target.blob_id = pointer
    assert_binding(verify(legacy_case, api), package, verified=True)


def test_all_lfs_metadata_availability_does_not_upgrade_to_byte_verification(legacy_case):
    package, _ = legacy_case
    records = []
    for item in package.publication_plan.operations:
        records.append(RepoFile(path=item.remote_path, size=item.size_bytes, oid="d" * 40,
            lfs={"size": item.size_bytes, "oid": item.sha256, "pointerSize": 132}))
    result = verify(legacy_case, MetadataApi(package, records))
    assert_binding(result, package, verified=True)
    assert result["all_remote_file_sha256_available"] is True
    assert all(row["identity_method"] == "lfs_sha256" for row in result["files"])
    assert all(row["remote_lfs_sha256"] == row["expected_sha256"] for row in result["files"])


@pytest.mark.parametrize("field,value", [("sha", "b" * 40), ("id", "different/private-repo"),
    ("private", False), ("private", None), ("private", 1), ("private", "true")])
@pytest.mark.parametrize("phase", [0, 1])
def test_repo_private_and_commit_checks_at_both_boundaries(legacy_case, field, value, phase):
    api = MetadataApi(legacy_case[0])
    setattr(api.info_records[phase], field, value)
    with pytest.raises(remote.AutoencoderRemoteMetadataError):
        verify(legacy_case, api)


@pytest.mark.parametrize("commit", ["main", "v1", "a" * 39, "a" * 41, "a" * 64, "A" * 40, " " + "a" * 40, None, True])
def test_revision_aliases_and_unsupported_commit_lengths_rejected(legacy_case, commit):
    api = MetadataApi(legacy_case[0])
    with pytest.raises(remote.AutoencoderRemoteMetadataError):
        verify(legacy_case, api, commit_sha=commit)
    assert not api.calls


def test_expected_destination_equals_sealed_plan(legacy_case):
    api = MetadataApi(legacy_case[0])
    with pytest.raises(remote.AutoencoderRemoteMetadataError):
        verify(legacy_case, api, expected_repository_id="other/private-model")
    assert not api.calls


@pytest.mark.parametrize("change", ["missing", "extra", "duplicate", "folder_collision", "spoof_file", "subclass_file", "spoof_info", "prefix_root"])
def test_exact_inventory_and_native_types_cannot_be_spoofed(legacy_case, change):
    package, _ = legacy_case
    api = MetadataApi(package)
    first = api.records[0]
    if change == "missing":
        api.records.pop()
    elif change == "extra":
        api.records.append(RepoFile(path=package.publication_plan.release_prefix + "/unexpected", size=0, oid=git_blob(b"")))
    elif change == "duplicate":
        api.records.append(copy.deepcopy(first))
    elif change == "folder_collision":
        api.records.append(RepoFolder(path=first.path, oid="b" * 40))
    elif change == "prefix_root":
        api.records.append(RepoFolder(path=package.publication_plan.release_prefix, oid="b" * 40))
    elif change == "spoof_info":
        api.info_records[0] = SimpleNamespace(**vars(api.info_records[0]))
    elif change == "spoof_file":
        api.records[0] = SimpleNamespace(**vars(first))
    else:
        class CustomFile(RepoFile):
            pass
        api.records[0] = CustomFile(path=first.path, size=first.size, oid=first.blob_id)
    with pytest.raises(remote.AutoencoderRemoteMetadataError):
        verify(legacy_case, api)


@pytest.mark.parametrize("path", ["../escape", "/absolute", "releases/sibling/file", "a\\b", "x/./y", "x//y", "nul\0x", "x/../y", "x" * 1025, "é" * 513])
def test_paths_never_normalize_into_expected_file(legacy_case, path):
    api = MetadataApi(legacy_case[0])
    api.records[0].path = path
    with pytest.raises(remote.AutoencoderRemoteMetadataError):
        verify(legacy_case, api)


@pytest.mark.parametrize("value", [None, True, -1, "12", 1.5, 0])
def test_size_is_exact_integer_and_matches_local(legacy_case, value):
    api = MetadataApi(legacy_case[0])
    api.records[0].size = value
    with pytest.raises(remote.AutoencoderRemoteMetadataError):
        verify(legacy_case, api)


@pytest.mark.parametrize("change", ["digest_wrong", "digest_malformed", "digest_upper", "size_wrong", "size_bool", "pointer_malformed", "pointer_size_bool", "pointer_size_zero", "dict_not_native"])
def test_malformed_or_conflicting_lfs_never_falls_back(legacy_case, change):
    api = MetadataApi(legacy_case[0])
    target = next(row for row in api.records if type(row) is RepoFile and row.lfs is not None)
    if change.startswith("digest"):
        value = {"digest_wrong": "0" * 64, "digest_malformed": "not-a-digest", "digest_upper": "A" * 64}[change]
        target.lfs.sha256 = target.lfs["sha256"] = value
    elif change.startswith("size"):
        target.lfs.size = target.lfs["size"] = True if change == "size_bool" else target.size + 1
    elif change == "pointer_malformed":
        target.blob_id = "g" * 40
    elif change.startswith("pointer_size"):
        target.lfs.pointer_size = target.lfs["pointer_size"] = True if change == "pointer_size_bool" else 0
    else:
        target.lfs = dict(target.lfs)
    with pytest.raises(remote.AutoencoderRemoteMetadataError):
        verify(legacy_case, api)


@pytest.mark.parametrize("digest", ["0" * 40, "a" * 64, "A" * 40, "not-a-hash", "raw_sha1"])
def test_git_blob_requires_object_hash_not_raw_digest(legacy_case, digest):
    package, _ = legacy_case
    api = MetadataApi(package, inventory(package, lfs_checkpoint=False))
    first = api.records[0]
    if digest == "raw_sha1":
        relative = first.path.removeprefix(package.publication_plan.release_prefix + "/")
        digest = hashlib.sha1((package.release_root / relative).read_bytes()).hexdigest()
    first.blob_id = digest
    with pytest.raises(remote.AutoencoderRemoteMetadataError):
        verify(legacy_case, api)


@pytest.mark.parametrize("change", ["missing_folder", "duplicate_folder", "unlisted_folder"])
def test_ancestor_folder_inventory_is_exact(package_case, change):
    package, _ = package_case
    api = MetadataApi(package)
    folder = next(row for row in api.records if type(row) is RepoFolder)
    if change == "missing_folder":
        api.records.remove(folder)
    elif change == "duplicate_folder":
        api.records.append(copy.deepcopy(folder))
    else:
        api.records.append(RepoFolder(path=package.publication_plan.release_prefix + "/empty-extra", oid="b" * 40))
    with pytest.raises(remote.AutoencoderRemoteMetadataError):
        verify(package_case, api)


def test_lazy_pagination_failure_never_returns_partial_success(legacy_case):
    class InterruptedApi(MetadataApi):
        def list_repo_tree(self, *args, **kwargs):
            yield from super().list_repo_tree(*args, **kwargs)
            raise OSError("synthetic later page failure")
    with pytest.raises(remote.AutoencoderRemoteMetadataError):
        verify(legacy_case, InterruptedApi(legacy_case[0]))


def test_iterator_is_bounded_without_materializing_remote_namespace(legacy_case):
    package, _ = legacy_case
    class UnboundedApi(MetadataApi):
        def list_repo_tree(self, *args, **kwargs):
            yield from super().list_repo_tree(*args, **kwargs)
            for index in range(1000):
                self.iterated += 1
                assert self.iterated <= len(self.records) + 1, "unbounded remote iterator consumption"
                yield RepoFolder(path=package.publication_plan.release_prefix + f"/extra-{index}", oid="b" * 40)
    api = UnboundedApi(package)
    with pytest.raises(remote.AutoencoderRemoteMetadataError):
        verify(legacy_case, api)
    assert api.iterated <= len(api.records) + 1


@pytest.mark.parametrize("mutation", ["content", "symlink", "extra_local_file"])
def test_package_change_after_reopen_blocks_receipt(legacy_case, tmp_path, mutation):
    package, _ = legacy_case
    api = MetadataApi(package)
    target = package.release_root / "README.md"
    def mutate():
        if mutation == "content":
            target.write_bytes(target.read_bytes() + b"changed")
        elif mutation == "symlink":
            other = tmp_path / "alias-target"
            other.write_bytes(target.read_bytes())
            target.unlink()
            target.symlink_to(other)
        else:
            (package.package_root / "unlisted-local").write_bytes(b"unexpected")
    api.on_tree = mutate
    with pytest.raises(remote.AutoencoderRemoteMetadataError):
        verify(legacy_case, api)


def test_wrong_manifest_fails_before_api(legacy_case):
    api = MetadataApi(legacy_case[0])
    with pytest.raises(remote.AutoencoderRemoteMetadataError):
        verify(legacy_case, api, expected_manifest_sha256="0" * 64)
    assert not api.calls


@pytest.mark.parametrize("mutation", ["fifo", "same_size_content"])
def test_first_info_mutation_rejected_by_local_hash_without_blocking_stream(legacy_case, mutation):
    package, _ = legacy_case
    api = MetadataApi(package)
    original = api.repo_info
    target = package.release_root / "README.md"
    def replace_after_observation(*args, **kwargs):
        info = original(*args, **kwargs)
        if mutation == "fifo":
            target.unlink()
            os.mkfifo(target)
        else:
            raw = target.read_bytes()
            target.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        return info
    api.repo_info = replace_after_observation
    with pytest.raises(remote.AutoencoderRemoteMetadataError):
        verify(legacy_case, api)


@pytest.mark.parametrize("primary_failure", [False, True])
def test_iterator_close_error_never_hides_verification_error(legacy_case, primary_failure):
    api = MetadataApi(legacy_case[0])
    rows = list(api.records)
    if primary_failure:
        rows[0].size += 1
    class FailingClose:
        def __init__(self):
            self.iterator = iter(rows)
            self.closed = False
        def __iter__(self):
            return self
        def __next__(self):
            return next(self.iterator)
        def close(self):
            self.closed = True
            raise OSError("synthetic-private-close-detail")
    iterator = FailingClose()
    original = api.list_repo_tree
    def tree(*args, **kwargs):
        # Evaluate the original fake's argument assertions without remote I/O.
        checked = original(*args, **kwargs)
        next(checked)
        checked.close()
        return iterator
    api.list_repo_tree = tree
    with pytest.raises(remote.AutoencoderRemoteMetadataError) as caught:
        verify(legacy_case, api)
    assert iterator.closed
    assert "synthetic-private-close-detail" not in str(caught.value)
    if primary_failure:
        assert "size" in str(caught.value).lower()
        assert getattr(caught.value, "__notes__", [])
