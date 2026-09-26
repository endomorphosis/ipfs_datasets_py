"""Read-only, commit-pinned metadata checks for sealed private resume releases.

This is deliberately separate from the publisher's stronger byte-readback
verification. It never downloads artifacts, creates commits, resolves an
uncertain upload, changes approval flags, or acknowledges an owner event.
The caller must supply a known commit and an independently selected package.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any, Mapping

from .autoencoder_release import (
    AutoencoderReleaseError,
    _bounded_package_paths,
    load_private_resume_release,
    verify_release_package,
)
from .publisher import _open_absolute_path_nofollow_components

SCHEMA = "autoencoder-private-remote-metadata-v1"
_GIT_SHA1 = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
MAX_TREE_ENTRIES = 256


class AutoencoderRemoteMetadataError(ValueError):
    """Remote observations or local package bytes cannot support this check."""


def _digest(value: Any, *, pattern: re.Pattern, label: str, missing: bool = False):
    if missing and (value is None or type(value) is str and value == ""):
        return None
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise AutoencoderRemoteMetadataError(f"invalid {label}")
    return value


def _path(value: Any) -> str:
    if (type(value) is not str or not value or len(value) > 1024 or len(value.encode("utf-8")) > 1024
            or "\\" in value or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or len(value.split("/")) > 8
            or any(piece in {"", ".", ".."} for piece in value.split("/"))):
        raise AutoencoderRemoteMetadataError("unsafe remote tree path")
    return value


def _repository_observation(api, repository_id, commit_sha):
    from huggingface_hub.hf_api import ModelInfo

    info = api.repo_info(repo_id=repository_id, repo_type="model", revision=commit_sha, expand=["sha", "private"])
    if (type(info) is not ModelInfo or type(info.id) is not str or info.id != repository_id
            or type(info.sha) is not str or info.sha != commit_sha or info.private is not True):
        raise AutoencoderRemoteMetadataError("repository identity, commit or private visibility differs")
    return {"repository_id": info.id, "commit_sha": info.sha, "private": True}


def _local_identities(root, operation):
    """Read one bounded regular file; SHA-1 uses Git's blob header, not raw bytes."""
    path = root / operation.relative_path
    _, parent_fd = _open_absolute_path_nofollow_components(
        path.parent, label="release artifact parent", require_directory=True,
    )
    try:
        # O_NONBLOCK prevents a file replaced by a FIFO after package reopening
        # from hanging verification. fstat rejects all non-regular descriptors.
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
    finally:
        os.close(parent_fd)
    sha256 = hashlib.sha256()
    git_sha1 = hashlib.sha1(b"blob " + str(operation.size_bytes).encode("ascii") + b"\0")
    size = 0
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size != operation.size_bytes:
            raise AutoencoderRemoteMetadataError("local release artifact size or type differs")
        while block := stream.read(min(1024 * 1024, operation.size_bytes - size + 1)):
            size += len(block)
            if size > operation.size_bytes:
                raise AutoencoderRemoteMetadataError("local release artifact exceeds sealed size")
            sha256.update(block)
            git_sha1.update(block)
        after = os.fstat(stream.fileno())
    if (size != operation.size_bytes or sha256.hexdigest() != operation.sha256
            or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
        raise AutoencoderRemoteMetadataError("local release artifact differs from sealed operation")
    return {"sha256": sha256.hexdigest(), "git_blob_sha1": git_sha1.hexdigest()}


def _file_observation(entry, operation, local):
    from huggingface_hub.hf_api import BlobLfsInfo

    if type(entry.size) is not int or entry.size != operation.size_bytes:
        raise AutoencoderRemoteMetadataError("remote file size differs from sealed operation")
    # A non-LFS blob OID describes the file; an LFS blob OID describes a pointer.
    # Never treat either as a file SHA-256 or use a pointer as payload evidence.
    blob = _digest(entry.blob_id, pattern=_GIT_SHA1, label="remote Git blob SHA-1", missing=True)
    lfs_sha256 = None
    if entry.lfs is None:
        method = "git_blob_sha1"
        observed, expected = blob, local["git_blob_sha1"]
        pending = "missing_git_blob_sha1"
    else:
        if type(entry.lfs) is not BlobLfsInfo:
            raise AutoencoderRemoteMetadataError("unsupported LFS metadata record")
        if type(entry.lfs.size) is not int or entry.lfs.size != operation.size_bytes:
            raise AutoencoderRemoteMetadataError("remote LFS size differs from sealed operation")
        pointer_size = entry.lfs.pointer_size
        if pointer_size is not None and (type(pointer_size) is not int or pointer_size < 1):
            raise AutoencoderRemoteMetadataError("invalid LFS pointer byte count")
        lfs_sha256 = _digest(entry.lfs.sha256, pattern=_SHA256, label="remote LFS SHA-256", missing=True)
        method = "lfs_sha256"
        observed, expected = lfs_sha256, local["sha256"]
        pending = "missing_lfs_sha256"
    if observed is not None and observed != expected:
        raise AutoencoderRemoteMetadataError("remote file identity differs from sealed operation")
    return {
        "remote_path": operation.remote_path, "size_bytes": entry.size,
        "expected_sha256": local["sha256"], "expected_git_blob_sha1": local["git_blob_sha1"],
        "remote_lfs_sha256": lfs_sha256, "remote_git_blob_sha1": blob,
        "identity_method": method, "identity_verified": observed is not None,
        "pending_reason": None if observed is not None else pending,
    }


def verify_private_resume_release_metadata(
    root: str | Path, *, expected_manifest_sha256: str,
    expected_version_record: Mapping[str, Any], expected_variant_manifest: Mapping[str, Any],
    expected_repository_id: str, commit_sha: str, api,
) -> dict[str, Any]:
    """Compare a sealed package with actual metadata at one known Hub commit.

    Accepts the installed Hub SDK's ModelInfo, RepoFile and RepoFolder records
    through an injected metadata client. No default client or credentials are
    constructed. Tree consumption is bounded; transport timeouts must be set
    by the caller (SDK list_repo_tree has no per-call timeout parameter).

    Missing file digests yield ``verification_pending``. Conflicting identity,
    inventory, visibility or local bytes raise. A successful result is metadata
    evidence only, with Git SHA-1 and LFS SHA-256 explicitly distinguished. It
    proves neither remote-byte readback nor which operation created the commit.
    Repository privacy is observed now, not historically attested by that commit.
    """
    _digest(commit_sha, pattern=_GIT_SHA1, label="full lowercase commit SHA-1")
    if type(expected_repository_id) is not str or not expected_repository_id:
        raise AutoencoderRemoteMetadataError("explicit repository identity is required")
    if not callable(getattr(api, "repo_info", None)) or not callable(getattr(api, "list_repo_tree", None)):
        raise AutoencoderRemoteMetadataError("injected metadata API is required")
    try:
        release = load_private_resume_release(
            root, expected_manifest_sha256=expected_manifest_sha256,
            expected_version_record=expected_version_record, expected_variant_manifest=expected_variant_manifest,
        )
        plan = release.publication_plan
        if plan.repository_id != expected_repository_id or plan.repository_type != "model":
            raise AutoencoderRemoteMetadataError("sealed plan differs from expected repository")
        operations = {row.remote_path: row for row in plan.operations}
        folders = set()
        for name in operations:
            _path(name)
            parent = PurePosixPath(name).parent
            while str(parent) != plan.release_prefix:
                if not str(parent).startswith(plan.release_prefix + "/"):
                    raise AutoencoderRemoteMetadataError("operation escapes sealed release prefix")
                folders.add(str(parent))
                parent = parent.parent
        limit = len(operations) + len(folders)
        if not 1 <= limit <= MAX_TREE_ENTRIES:
            raise AutoencoderRemoteMetadataError("sealed remote namespace exceeds entry bound")

        before = _repository_observation(api, expected_repository_id, commit_sha)
        # Hash after the first observation and independently of any client data.
        local = {name: _local_identities(release.release_root, row) for name, row in operations.items()}
        from huggingface_hub.hf_api import RepoFile, RepoFolder

        iterator = iter(api.list_repo_tree(
            repo_id=expected_repository_id, path_in_repo=plan.release_prefix,
            recursive=True, expand=False, revision=commit_sha, repo_type="model",
        ))
        seen, files, directories = set(), {}, {}
        primary = None
        try:
            for index, entry in enumerate(iterator):
                if index >= limit:
                    raise AutoencoderRemoteMetadataError("remote tree exceeds sealed entry bound")
                if type(entry) not in {RepoFile, RepoFolder}:
                    raise AutoencoderRemoteMetadataError("unsupported remote tree record")
                name = _path(entry.path)
                if name in seen:
                    raise AutoencoderRemoteMetadataError("duplicate remote tree entry")
                seen.add(name)
                if type(entry) is RepoFolder:
                    if name not in folders:
                        raise AutoencoderRemoteMetadataError("unexpected remote directory")
                    directories[name] = _digest(entry.tree_id, pattern=_GIT_SHA1, label="remote tree SHA-1")
                else:
                    if name not in operations:
                        raise AutoencoderRemoteMetadataError("unexpected remote file")
                    files[name] = _file_observation(entry, operations[name], local[name])
        except BaseException as exc:
            primary = exc
            raise
        finally:
            close = getattr(iterator, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    if primary is None:
                        raise
                    primary.add_note("remote metadata iterator cleanup also failed")
        if set(files) != set(operations) or set(directories) != folders:
            raise AutoencoderRemoteMetadataError("remote tree differs from exact sealed inventory")
        after = _repository_observation(api, expected_repository_id, commit_sha)
        # The initial strong loader already checked checkpoint semantics. Exact
        # final closure checks detect subsequent changes without rehydrating it.
        verify_release_package(
            release.package_root, expected_manifest_sha256=expected_manifest_sha256,
            _namespace_paths=_bounded_package_paths(release.package_root),
        )
        verified = all(row["identity_verified"] for row in files.values())
        return {
            "schema": SCHEMA, "status": "metadata_verified" if verified else "verification_pending",
            "observation_source": "injected_huggingface_hub_metadata_api",
            "repository_id": expected_repository_id, "repository_type": "model", "commit_sha": commit_sha,
            "release_id": plan.release_id, "release_prefix": plan.release_prefix,
            "package_manifest_sha256": release.package_manifest_sha256, "publication_plan_digest": plan.plan_digest,
            "repository_observations": [before, after], "private_visibility_observed": True,
            "historical_private_visibility_verified": False,
            "file_count": len(files), "release_size_bytes": sum(row.size_bytes for row in operations.values()),
            "files": [files[name] for name in sorted(files)],
            "directories": [{"path": name, "tree_sha1": directories[name]} for name in sorted(directories)],
            "metadata_identity_verified": verified,
            "all_remote_file_sha256_available": all(row["remote_lfs_sha256"] is not None for row in files.values()),
            "remote_modes_verified": False, "bytes_verified": False, "remote_bytes_downloaded": 0,
            "remote_write_operations": 0, "publication_outcome_established": False,
            "publication_acknowledged": False, "pointer_promoted": False, "admitted": False,
        }
    except AutoencoderRemoteMetadataError:
        raise
    except AutoencoderReleaseError as exc:
        raise AutoencoderRemoteMetadataError("local private resume package verification failed") from exc
    except Exception as exc:
        # Do not insert arbitrary transport messages (which may contain tokens)
        # into an evidence receipt or substitute local values after a failure.
        raise AutoencoderRemoteMetadataError("private release metadata verification failed") from exc
