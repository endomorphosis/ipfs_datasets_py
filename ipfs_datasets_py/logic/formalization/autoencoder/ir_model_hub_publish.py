"""Explicit, append-only publication of byte-pinned IR assets.

This module authenticates metadata and payload bytes, never model meaning or
quality. It does not import checkpoints, execute repository Python, change
existing visibility, or promise an atomic transaction across repositories.
Files must be regular local files; copy retained assets into an owned release
stage before calling. Per-file witnesses do not fence arbitrary ancestor races.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import stat
from pathlib import Path

PLAN_SCHEMA = "ir-model-hub-release-plan/v1"
MAX_FILES = 256
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024


class HubPublicationError(ValueError):
    """Publication refused; ``receipt`` describes observed partial operations."""

    def __init__(self, message, *, receipt=None):
        super().__init__(message)
        self.receipt = copy.deepcopy(receipt or {})


def _require(condition, message):
    if not condition:
        raise HubPublicationError(message)


def _closed(value, keys, label):
    _require(type(value) is dict and set(value) == set(keys), label + " fields differ")


def _pin(value):
    _closed(value, ("path", "bytes", "sha256"), "file pin")
    _require(type(value["path"]) is str and Path(value["path"]).is_absolute(),
             "file pin requires an absolute path")
    _require(type(value["bytes"]) is int and 0 <= value["bytes"] <= MAX_FILE_BYTES,
             "file byte count is invalid")
    _require(type(value["sha256"]) is str and
             re.fullmatch(r"[0-9a-f]{64}", value["sha256"]), "file SHA256 is invalid")


def _destination(value):
    _require(type(value) is str and 1 <= len(value) <= 512 and
             re.fullmatch(r"[A-Za-z0-9_.\-/]+", value), "repository file path is invalid")
    parts = value.split("/")
    _require(all(part not in ("", ".", "..") and len(part) <= 255 for part in parts),
             "repository file path is not canonical")


def _capture_plan(plan):
    # JSON detaches caller objects and refuses NaN or nonmetadata objects.
    try:
        value = json.loads(json.dumps(plan, allow_nan=False))
    except Exception as exc:
        raise HubPublicationError("release plan is not JSON metadata") from exc
    _closed(value, ("schema", "manifest_pin", "repository_id", "private_new", "operations"),
            "release plan")
    _require(value["schema"] == PLAN_SCHEMA, "release plan schema is unsupported")
    repo = value["repository_id"]
    _require(type(repo) is str and re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}/[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", repo)
        and ".." not in repo, "repository ID is invalid")
    _require(type(value["private_new"]) is bool, "new repository visibility must be explicit")
    _pin(value["manifest_pin"])
    _require(value["manifest_pin"]["bytes"] <= MAX_MANIFEST_BYTES, "manifest is too large")
    operations = value["operations"]
    _require(type(operations) is list and 1 <= len(operations) <= MAX_FILES,
             "release file count is invalid")
    destinations = set()
    manifest_count = 0
    for operation in operations:
        _closed(operation, ("file_pin", "path_in_repo"), "file operation")
        _pin(operation["file_pin"])
        _destination(operation["path_in_repo"])
        _require(operation["path_in_repo"] not in destinations, "duplicate repository file path")
        destinations.add(operation["path_in_repo"])
        manifest_count += operation["file_pin"] == value["manifest_pin"]
    _require(manifest_count == 1, "manifest pin must appear exactly once among operations")
    _require(sum(x["file_pin"]["bytes"] for x in operations) <= MAX_TOTAL_BYTES,
             "release total bytes exceed the bound")
    return value


def _witness(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


def _read_pin(pin):
    path = pin["path"]
    try:
        before = os.lstat(path)
        _require(stat.S_ISREG(before.st_mode), "release source must be a regular file")
        _require(before.st_size == pin["bytes"], "release source byte count differs")
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            opened = os.fstat(fd)
            _require(_witness(before) == _witness(opened), "release source changed before opening")
            chunks, count = [], 0
            while True:
                chunk = os.read(fd, min(1024 * 1024, pin["bytes"] - count + 1))
                if not chunk:
                    break
                count += len(chunk)
                _require(count <= pin["bytes"], "release source grew while reading")
                chunks.append(chunk)
            after_fd = os.fstat(fd)
        finally:
            os.close(fd)
        after_path = os.lstat(path)
        _require(_witness(before) == _witness(after_fd) == _witness(after_path),
                 "release source changed while reading")
        data = b"".join(chunks)
        _require(len(data) == pin["bytes"] and hashlib.sha256(data).hexdigest() == pin["sha256"],
                 "release source SHA256 differs")
        return data
    except HubPublicationError:
        raise
    except Exception as exc:
        raise HubPublicationError("release source could not be authenticated") from exc


def _json_object(data):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "manifest contains duplicate JSON keys")
            result[key] = value
        return result

    def finite(value):
        result = float(value)
        _require(math.isfinite(result), "manifest contains nonfinite JSON numbers")
        return result

    try:
        result = json.loads(data, object_pairs_hook=pairs, parse_float=finite,
                            parse_constant=lambda _: (_require(False, "manifest contains nonfinite JSON")))
    except HubPublicationError:
        raise
    except Exception as exc:
        raise HubPublicationError("manifest is not valid JSON metadata") from exc
    _require(type(result) is dict, "manifest must be a JSON object")


def _freeze_files(plan, previous=None):
    result = {}
    for operation in plan["operations"]:
        path = operation["path_in_repo"]
        result[path] = _read_pin(operation["file_pin"])
        if previous is not None:
            _require(result[path] == previous[path], "release source differs from captured bytes")
        if operation["file_pin"] == plan["manifest_pin"]:
            _json_object(result[path])
    return result


def _field(value, name, alias=None):
    if isinstance(value, dict):
        if alias and name in value and alias in value:
            _require(value[name] == value[alias], "remote metadata aliases disagree")
        return value.get(name, value.get(alias) if alias else None)
    return getattr(value, name, None)


def _info(api, repository_id, revision=None):
    kwargs = {"files_metadata": True}
    if revision is not None:
        kwargs["revision"] = revision
    value = api.model_info(repository_id, **kwargs)
    sha, private = _field(value, "sha"), _field(value, "private")
    _require(type(sha) is str and re.fullmatch(r"[0-9a-f]{40}", sha),
             "remote repository revision is invalid")
    _require(type(private) is bool, "remote repository visibility is unknown")
    rows = _field(value, "siblings")
    _require(type(rows) is list, "remote file metadata is unavailable")
    files = {}
    for row in rows:
        path = _field(row, "rfilename")
        _require(type(path) is str and path and path not in files,
                 "remote file metadata contains ambiguous paths")
        files[path] = row
    return sha, private, files


def _verify_file(row, operation, data):
    pin = operation["file_pin"]
    size = _field(row, "size")
    _require(type(size) is int and size == pin["bytes"], "remote file byte count differs")
    lfs = _field(row, "lfs")
    if lfs is not None:
        sha, lfs_size = _field(lfs, "sha256"), _field(lfs, "size")
        _require(type(lfs_size) is int and lfs_size == pin["bytes"] and
                 type(sha) is str and sha == pin["sha256"],
                 "remote LFS payload SHA256 or byte count differs")
        identity = {"scheme": "lfs-payload-sha256", "sha256": sha, "bytes": size}
    else:
        blob = _field(row, "blob_id", "blobId")
        expected = hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
        _require(type(blob) is str and blob == expected, "remote Git file blob identity differs")
        identity = {"scheme": "git-blob-sha1", "blob_id": blob, "bytes": size}
    return {"path_in_repo": operation["path_in_repo"], "file_pin": copy.deepcopy(pin),
            "bytes": pin["bytes"], "sha256": pin["sha256"],
            "remote_identity": identity, "verified": True}


def publish_ir_model_hub_release(plan, *, api=None, operation_factory=None):
    """Publish explicit files or reuse exact remote bytes; never overwrite a path.

    ``api`` follows HfApi's model_info/create_repo/create_commit contract.
    ``operation_factory`` follows CommitOperationAdd and enables inert tests.
    The defaults import genuine huggingface_hub lazily after local validation.
    The manifest is authenticated JSON metadata, not runtime/model qualification.
    Root README.md is create-only like every other explicit destination.
    """
    captured = _capture_plan(plan)
    payloads = _freeze_files(captured)
    receipt = {
        "schema": "ir-model-hub-publication-receipt/v1",
        "repository_id": captured["repository_id"],
        "manifest_pin": copy.deepcopy(captured["manifest_pin"]),
        "requested_private_new": captured["private_new"],
        "repository_create_started": False, "repository_create_returned": False,
        "repository_creation_indeterminate": False, "repository_created": False,
        "commit_started": False, "commit_returned": False,
        "files_verified": False, "created_paths": [], "reused_paths": [],
        "repository_supplied_python_executed": False, "trust_remote_code": False,
        "model_loaded": False, "numerical_quality_qualified": False, "teacher_qualified": False,
        "proof_qualified": False, "cross_repository_transaction_atomic": False,
    }
    try:
        if api is None:
            from huggingface_hub import HfApi
            api = HfApi()
        try:
            revision, private, existing = _info(api, captured["repository_id"])
        except Exception as exc:
            # Only a genuine not-found response admits repository creation.
            if getattr(getattr(exc, "response", None), "status_code", None) != 404:
                raise
            receipt["repository_create_started"] = True
            receipt["repository_creation_indeterminate"] = True
            api.create_repo(captured["repository_id"], repo_type="model",
                            private=captured["private_new"], exist_ok=False)
            receipt["repository_create_returned"] = True
            receipt["repository_creation_indeterminate"] = False
            receipt["repository_created"] = True
            revision, private, existing = _info(api, captured["repository_id"])
            _require(private == captured["private_new"], "new repository visibility differs")
        receipt.update(initial_revision=revision, revision=revision, repository_private=private,
                       existing_visibility_preserved=not receipt["repository_created"])
        missing = []
        for operation in captured["operations"]:
            path = operation["path_in_repo"]
            if path in existing:
                _verify_file(existing[path], operation, payloads[path])
                receipt["reused_paths"].append(path)
            else:
                missing.append(operation)
        _freeze_files(captured, payloads)
        if missing:
            if operation_factory is None:
                from huggingface_hub import CommitOperationAdd
                operation_factory = CommitOperationAdd
            additions = [operation_factory(path_in_repo=x["path_in_repo"],
                                            path_or_fileobj=payloads[x["path_in_repo"]]) for x in missing]
            receipt["commit_started"] = True
            commit = api.create_commit(captured["repository_id"], repo_type="model",
                parent_commit=revision, operations=additions,
                commit_message="Publish pinned IR assets " + captured["manifest_pin"]["sha256"][:12])
            receipt["commit_returned"] = True
            new_revision = _field(commit, "oid")
            _require(type(new_revision) is str and re.fullmatch(r"[0-9a-f]{40}", new_revision),
                     "returned commit identity is invalid")
            receipt["revision"] = revision = new_revision
            receipt["created_paths"] = [x["path_in_repo"] for x in missing]
        _freeze_files(captured, payloads)
        verified_revision, verified_private, files = _info(api, captured["repository_id"], revision)
        _require(verified_revision == revision and verified_private == private,
                 "returned revision or repository visibility differs")
        verified = []
        for operation in captured["operations"]:
            path = operation["path_in_repo"]
            _require(path in files, "published file is missing from returned commit")
            verified.append(_verify_file(files[path], operation, payloads[path]))
        _freeze_files(captured, payloads)
        receipt.update(files=verified, files_verified=True, idempotent_reuse=not missing)
        return copy.deepcopy(receipt)
    except Exception as exc:
        # Stable messages do not print provider exception strings or secrets.
        message = str(exc) if isinstance(exc, HubPublicationError) else "Hub publication operation failed"
        raise HubPublicationError(message, receipt=receipt) from exc


__all__ = ["HubPublicationError", "publish_ir_model_hub_release"]
