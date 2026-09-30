"""Publish and verify the canonical paired census without executing its goals."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import legacy_span_publication as verified

TABLES = ("paired_spans", "goals", "artifacts")
REPOSITORY = verified.REPOSITORY


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _load(path):
    from ipfs_datasets_py.logic.autoformal.paired_span_census import load_paired_census_bundle
    return load_paired_census_bundle(path)


def _files(path, manifest):
    path = Path(path)
    files = [("manifest", path, manifest["path_in_repo"])]
    for kind in TABLES:
        desc = manifest["tables"][kind]
        name = desc["filename"]
        if Path(name).name != name or not name.endswith(".parquet"):
            raise ValueError("invalid paired table filename")
        files.append((kind, path.parent / name, desc["path_in_repo"]))
    return files


def _descriptors(path, manifest):
    values = []
    for kind, local, remote in _files(path, manifest):
        raw, snapshot = verified._snapshot(local)
        if kind != "manifest" and (snapshot["sha256"] != manifest["tables"][kind]["sha256"]
                                   or len(raw) != manifest["tables"][kind]["bytes"]):
            raise ValueError("paired table differs from manifest")
        values.append(({"kind": kind, "path_in_repo": remote,
                        **{key: snapshot[key] for key in ("sha256", "git_blob_sha1", "bytes")}}, raw))
    return values


def _remote(api, descriptors, commit, *, complete):
    if complete:
        return verified._verify_remote({"publication": {"commit_sha": commit},
                                        "remote_files": descriptors}, api)
    expected = {row["path_in_repo"]: row for row in descriptors}
    seen = set()
    for item in api.get_paths_info(repo_id=REPOSITORY, repo_type="dataset", revision=commit,
                                  paths=list(expected)):
        path = verified._field(item, "path")
        if path not in expected or path in seen:
            raise ValueError("unexpected paired output at remote path")
        wanted = expected[path]
        lfs = verified._field(item, "lfs")
        digest = verified._field(lfs, "sha256") if lfs else None
        if ((digest or verified._field(item, "blob_id")) !=
                (wanted["sha256"] if digest else wanted["git_blob_sha1"])
                or verified._field(item, "size") != wanted["bytes"]):
            raise ValueError("immutable paired output path conflicts")
        seen.add(path)
    return seen


def publish_paired_manifest(path, *, upload=False, api=None):
    from ipfs_datasets_py.logic.autoformal.span_cache_exchange import _immutable_write
    from huggingface_hub import HfApi, CommitOperationAdd

    path = Path(path)
    bundle = _load(path)
    manifest = bundle["manifest"]
    if manifest["repository_id"] != REPOSITORY:
        raise ValueError("paired publication repository differs")
    artifacts = _descriptors(path, manifest)
    manifest_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if manifest_sha != bundle["manifest_sha256"]:
        raise ValueError("paired manifest changed after validation")
    result = {"schema": "paired-span-publication/v1", "repository_id": REPOSITORY,
              "fingerprint": manifest["fingerprint"], "manifest_sha256": manifest_sha,
              "manifest": {"path_in_repo": manifest["path_in_repo"]},
              "uploaded": False, "dry_run": not upload, "admitted": False,
              "formalized": False, "enqueued": False, "wrote_compiler": False}
    if not upload:
        return result
    api = api or HfApi()
    receipt_path = path.with_name(path.name + ".publication.json")
    if receipt_path.exists():
        saved = json.loads(verified._snapshot(receipt_path)[0])
        if saved.get("manifest_sha256") != manifest_sha or saved.get("uploaded") is not True:
            raise ValueError("retained paired publication differs")
        _remote(api, [row for row, _ in artifacts], saved["commit_sha"], complete=True)
        return saved
    parent = verified._field(api.repo_info(repo_id=REPOSITORY, repo_type="dataset"), "sha")
    present = _remote(api, [row for row, _ in artifacts], parent, complete=False)
    operations = [CommitOperationAdd(path_in_repo=row["path_in_repo"], path_or_fileobj=raw)
                  for row, raw in artifacts if row["path_in_repo"] not in present]
    commit = parent
    if operations:
        commit = verified._field(api.create_commit(repo_id=REPOSITORY, repo_type="dataset",
            parent_commit=parent, operations=operations,
            commit_message="Append paired span conversions, diagnostic census and deferred goals"), "oid")
    _remote(api, [row for row, _ in artifacts], commit, complete=True)
    result.update(uploaded=True, commit_sha=commit, parent_commit=parent)
    _immutable_write(receipt_path, _json(result).encode())
    return result


def prepare_cleanup(root, batch_id, manifest_path, publication, receipt_sha):
    """Prove the complete producer receipt survives in the remote bundle."""
    path = Path(manifest_path)
    root = Path(root)
    bundle = _load(path)
    manifest = bundle["manifest"]
    receipt_path = root / "receipts" / (batch_id + ".json")
    raw, snapshot = verified._snapshot(receipt_path)
    receipt = json.loads(raw)
    if snapshot["sha256"] != receipt_sha or receipt["campaign"]["batch_id"] != batch_id:
        raise ValueError("paired cleanup source receipt differs")
    if bundle.get("original_receipt") != receipt:
        raise ValueError("paired artifacts do not preserve the full producer receipt")
    if (hashlib.sha256(path.read_bytes()).hexdigest() != bundle["manifest_sha256"]
            or bundle["manifest_sha256"] != publication["manifest_sha256"]
            or manifest["fingerprint"] != publication["fingerprint"]
            or publication.get("manifest", {}).get("path_in_repo") != manifest["path_in_repo"]):
        raise ValueError("paired cleanup publication does not bind manifest")
    publication_path = path.with_name(path.name + ".publication.json")
    if json.loads(verified._snapshot(publication_path)[0]) != publication:
        raise ValueError("paired publication receipt changed")
    remote_files, local_files = [], []
    files = _files(path, manifest) + [("receipt", receipt_path, None),
                                     ("publication", publication_path, None)]
    for kind, local, remote in files:
        relative = str(local.relative_to(root))
        verified._path(root, relative)
        _, desc = verified._snapshot(local)
        local_files.append({"kind": kind, "relative_path": relative, **desc})
        if remote is not None:
            remote_files.append({"kind": kind, "path_in_repo": remote,
                **{key: desc[key] for key in ("bytes", "sha256", "git_blob_sha1")}})
    return {"schema_version": "paired-span-cleanup/v1", "batch_id": batch_id,
            "campaign_root": str(root), "publication": publication, "manifest": manifest,
            "remote_files": remote_files, "local_files": local_files,
            "receipt_sha256": receipt_sha, "admitted": False, "formalized": False}
