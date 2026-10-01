"""Verify immutable Hub evidence before evicting one campaign's local copies.

The controller owns the DuckDB connection and the campaign directory. This
module never uploads, scans unrelated files, deletes weights, or changes work
status. A durable database journal precedes deletion so interrupted cleanup is
repeatable without retaining another growing directory of receipt files.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any

REPOSITORY = "justicedao/uscode-autoformal-span-cache"
MAX_BYTES = 64 * 1024 * 1024
SCHEMA = "legacy-span-publication-eviction/v1"


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _field(value, key, default=None):
    return value.get(key, default) if isinstance(value, Mapping) else getattr(value, key, default)


def _root(runtime):
    root = Path(runtime).absolute()
    if not root.is_dir() or root.resolve(strict=True) != root:
        raise ValueError("campaign directory must be a real unaliased directory")
    return root


def _path(root, relative):
    path = PurePosixPath(relative)
    if (path.is_absolute() or len(path.parts) != 2 or path.parts[0] not in {"receipts", "outbox"}
            or ".." in path.parts or str(path) != relative or "\\" in relative):
        raise ValueError("cleanup path is outside the campaign artifact directories")
    result = root / relative
    if result.parent.resolve(strict=True) != result.parent or not result.parent.is_dir():
        raise ValueError("campaign artifact directory is aliased")
    return result


def _snapshot(path):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags), "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 <= before.st_size <= MAX_BYTES:
            raise ValueError("cleanup requires a bounded privately owned regular file")
        raw = handle.read(MAX_BYTES + 1)
        after = os.fstat(handle.fileno())
    identity = lambda info: [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]
    if (len(raw) != before.st_size or identity(before) != identity(after)
            or identity(before) != identity(path.stat(follow_symlinks=False))):
        raise ValueError("campaign artifact changed during observation")
    return raw, {"bytes": len(raw), "sha256": _sha(raw), "identity": identity(before),
        "git_blob_sha1": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def _load_bundle(path):
    from ipfs_datasets_py.logic.autoformal.span_cache_exchange import load_exchange_bundle
    return load_exchange_bundle(path)


def _coverage(receipt, census):
    """Prove that deleting the local batch JSON loses no recorded observation."""
    rows = receipt.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("batch receipt requires complete observations")
    expected = {row["source_span_id"]: row for row in rows}
    if len(expected) != len(rows) or len(census) != len(rows):
        raise ValueError("census does not cover the complete batch")
    shared = {key: value for key, value in receipt.items() if key not in {"rows", "raw_evaluation"}}
    seen, observations = set(), []
    for census_row in census:
        observed = json.loads(census_row["input_json"])
        span_id = observed.get("source_span_id")
        if (span_id not in expected or span_id in seen
                or observed.get("autoencoder_observation") != expected[span_id]
                or observed.get("batch_observation") != shared):
            raise ValueError("census omits or changes a complete batch observation")
        seen.add(span_id)
        observations.append(observed)
    raw = receipt.get("raw_evaluation")
    if not isinstance(raw, dict):
        raise ValueError("batch requires a recorded raw evaluation")
    if all(item.get("raw_batch_evaluation") == raw for item in observations):
        return
    summaries = [item["raw_batch_summary"] for item in observations if "raw_batch_summary" in item]
    if len(summaries) != 1 or not isinstance(summaries[0], dict):
        raise ValueError("census requires exactly one complete raw batch summary")
    reconstructed = dict(summaries[0])
    sample_maps = {}
    for observed in observations:
        sample_id = observed["autoencoder_observation"].get("sample_id")
        values = observed.get("raw_sample_evaluation")
        if not isinstance(values, dict) or (values and not isinstance(sample_id, str)):
            raise ValueError("census raw sample evaluation is invalid")
        for key, value in values.items():
            if key in reconstructed or sample_id in sample_maps.get(key, {}):
                raise ValueError("census raw evaluation is ambiguous")
            sample_maps.setdefault(key, {})[sample_id] = value
    reconstructed.update(sample_maps)
    if reconstructed != raw:
        raise ValueError("census does not preserve the complete raw evaluation")


def _published(db, batch_id):
    row = db.execute("SELECT status,manifest,publication,receipt_sha256 FROM batches WHERE id=?", [batch_id]).fetchone()
    if row is None or row[0] != "published":
        raise ValueError("only an explicitly published batch may be evicted")
    publication = json.loads(row[2])
    if (publication.get("repository_id") != REPOSITORY or publication.get("uploaded") is not True
            or publication.get("dry_run") is not False
            or not re.fullmatch(r"[0-9a-f]{40}", str(publication.get("commit_sha", "")))
            or any(publication.get(key) is not False for key in ("admitted", "formalized", "wrote_compiler", "enqueued"))):
        raise ValueError("publication is not a non-authoritative immutable Hub receipt")
    if db.execute("SELECT count(*) FROM batches WHERE id<>? AND manifest=?", [batch_id, row[1]]).fetchone()[0]:
        raise ValueError("exchange artifact is referenced by another batch")
    return row[1], publication, row[3]


def _prepare(root, batch_id, manifest_path, publication, receipt_sha):
    manifest_raw, _ = _snapshot(Path(manifest_path))
    if json.loads(manifest_raw).get("schema") in {"uscode-paired-span-bundle/v1", "uscode-paired-span-bundle/v2"}:
        from .paired_span_publication import prepare_cleanup
        return prepare_cleanup(root, batch_id, manifest_path, publication, receipt_sha)
    fingerprint = publication.get("fingerprint", "")
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise ValueError("invalid exchange fingerprint")
    filenames = {
        "receipt": f"receipts/{batch_id}.json",
        "manifest": f"outbox/exchange-{fingerprint}.manifest.json",
        "census": f"outbox/census-{fingerprint}.parquet",
        "goals": f"outbox/goals-{fingerprint}.parquet",
        "publication": f"outbox/exchange-{fingerprint}.manifest.json.publication.json",
    }
    if str(_path(root, filenames["manifest"])) != manifest_path:
        raise ValueError("batch manifest does not belong to this campaign")
    snapshots, local = {}, []
    for kind, relative in filenames.items():
        raw, desc = _snapshot(_path(root, relative))
        snapshots[kind] = raw
        local.append({"kind": kind, "relative_path": relative, **desc})
    if _sha(snapshots["receipt"]) != receipt_sha:
        raise ValueError("retained batch receipt differs from its durable database digest")
    receipt = json.loads(snapshots["receipt"])
    if receipt.get("campaign", {}).get("batch_id") != batch_id:
        raise ValueError("batch receipt belongs to another batch")
    manifest = json.loads(snapshots["manifest"])
    if (manifest.get("repository_id") != REPOSITORY or manifest.get("fingerprint") != fingerprint
            or publication.get("manifest_sha256") != _sha(snapshots["manifest"])
            or publication.get("manifest", {}).get("path_in_repo") != manifest.get("path_in_repo")):
        raise ValueError("publication does not bind the exact manifest")
    stored = json.loads(snapshots["publication"])
    strip_resume = lambda value: {key: item for key, item in value.items() if key != "skipped"}
    if strip_resume(stored) != strip_resume(publication):
        raise ValueError("local and database publication receipts differ")
    bundle = _load_bundle(Path(manifest_path))
    if bundle["manifest_sha256"] != publication["manifest_sha256"]:
        raise ValueError("manifest changed during closure validation")
    for kind in ("census", "goals"):
        if (Path(bundle[kind + "_path"]) != _path(root, filenames[kind])
                or manifest[kind].get("filename") != Path(filenames[kind]).name):
            raise ValueError("manifest closure references another local batch artifact")
    _coverage(receipt, bundle["census_rows"])
    remote = []
    for kind in ("manifest", "census", "goals"):
        desc = next(item for item in local if item["kind"] == kind)
        path = manifest["path_in_repo"] if kind == "manifest" else manifest[kind]["path_in_repo"]
        remote.append({"kind": kind, "path_in_repo": path,
                       **{key: desc[key] for key in ("bytes", "sha256", "git_blob_sha1")}})
    return {"schema_version": SCHEMA, "batch_id": batch_id, "campaign_root": str(root),
            "publication": publication, "manifest": manifest, "remote_files": remote,
            "local_files": local, "receipt_sha256": receipt_sha,
            "admitted": False, "formalized": False}


def _verify_remote(plan, api):
    publication = plan["publication"]
    revision = publication["commit_sha"]
    info = api.repo_info(repo_id=REPOSITORY, repo_type="dataset", revision=revision)
    if _field(info, "sha") != revision:
        raise ValueError("Hub did not resolve the exact immutable publication commit")
    expected = {item["path_in_repo"]: item for item in plan["remote_files"]}
    kinds = [item.get("kind") for item in plan["remote_files"]]
    required = {"manifest", "paired_spans", "goals", "artifacts"} if "paired_spans" in kinds else {"manifest", "census", "goals"}
    if len(expected) != len(required) or len(kinds) != len(required) or set(kinds) != required:
        raise ValueError("publication closure must contain exactly its declared artifacts")
    observed = api.get_paths_info(repo_id=REPOSITORY, repo_type="dataset", revision=revision,
                                  paths=list(expected))
    verified = []
    for item in observed:
        path = _field(item, "path", _field(item, "rfilename"))
        if path not in expected or any(value["path_in_repo"] == path for value in verified):
            raise ValueError("unexpected or duplicate remote publication artifact")
        wanted = expected[path]
        lfs = _field(item, "lfs")
        lfs_sha = _field(lfs, "sha256") if lfs else None
        actual = lfs_sha or _field(item, "blob_id")
        target = wanted["sha256"] if lfs_sha else wanted["git_blob_sha1"]
        if actual != target or _field(item, "size") != wanted["bytes"]:
            raise ValueError("remote publication blob digest or size differs")
        verified.append({**wanted, "verified_digest": actual,
                         "digest_kind": "lfs_sha256" if lfs_sha else "git_blob_sha1"})
    if len(verified) != len(expected):
        raise ValueError("immutable commit is missing publication closure artifacts")
    return {"repository_id": REPOSITORY, "commit_sha": revision, "files": verified}


def verify_and_evict_published_batch(db, runtime, batch_id: str, *, api=None) -> dict[str, Any]:
    """Verify remote closure, journal it durably, then unlink exactly five files.

    Call outside any transaction, with one controller owning this connection
    and campaign directory. A timeout/error leaves local evidence in place.
    Repeating after a partial cleanup uses the durable journal and rechecks
    immutable remote references before deleting any remaining files.
    """
    if not isinstance(batch_id, str) or not re.fullmatch(r"[0-9a-f]{32}", batch_id):
        raise ValueError("invalid campaign batch identity")
    root = _root(runtime)
    manifest_path, publication, receipt_sha = _published(db, batch_id)
    db.execute("""CREATE TABLE IF NOT EXISTS legacy_span_evictions (
        batch_id VARCHAR PRIMARY KEY, status VARCHAR NOT NULL,
        plan VARCHAR NOT NULL, plan_sha256 VARCHAR NOT NULL, remote_verification VARCHAR NOT NULL)""")
    retained = db.execute("SELECT status,plan,plan_sha256,remote_verification FROM legacy_span_evictions WHERE batch_id=?", [batch_id]).fetchone()
    if retained:
        if _sha(retained[1].encode()) != retained[2]:
            raise ValueError("durable cleanup plan changed")
        plan = json.loads(retained[1])
        if (plan["campaign_root"] != str(root) or plan["batch_id"] != batch_id
                or plan["publication"] != publication or plan["receipt_sha256"] != receipt_sha):
            raise ValueError("cleanup plan differs from durable batch identity")
        if retained[0] == "evicted":
            return {"batch_id": batch_id, "status": "already_evicted", "deleted_bytes": 0,
                    "remote": json.loads(retained[3]), "admitted": False, "formalized": False}
    else:
        plan = _prepare(root, batch_id, manifest_path, publication, receipt_sha)
    if api is None:
        from huggingface_hub import HfApi
        api = HfApi()
    verification = _verify_remote(plan, api)
    # Preflight every remaining local file before changing any of them.
    pending = []
    for descriptor in plan["local_files"]:
        path = _path(root, descriptor["relative_path"])
        if not path.exists() and not path.is_symlink():
            if retained:
                continue
            raise ValueError("unjournaled campaign artifact disappeared")
        _, current = _snapshot(path)
        if any(current[key] != descriptor[key] for key in current):
            raise ValueError("campaign artifact changed after publication")
        pending.append((path, descriptor))
    if not retained:
        encoded = _json(plan)
        db.execute("BEGIN")
        try:
            db.execute("INSERT INTO legacy_span_evictions VALUES (?, 'verified', ?, ?, ?)",
                       [batch_id, encoded, _sha(encoded.encode()), _json(verification)])
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    deleted = 0
    for path, descriptor in pending:
        # Repeat byte+inode checks immediately before unlinking. The controller
        # exclusively owns these immutable artifacts and their directories.
        _, current = _snapshot(path)
        if any(current[key] != descriptor[key] for key in current):
            raise ValueError("campaign artifact changed immediately before eviction")
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.unlink(path.name, dir_fd=directory)
            os.fsync(directory)
        finally:
            os.close(directory)
        deleted += descriptor["bytes"]
    db.execute("UPDATE legacy_span_evictions SET status='evicted',remote_verification=? WHERE batch_id=?",
               [_json(verification), batch_id])
    return {"batch_id": batch_id, "status": "evicted", "deleted_bytes": deleted,
            "remote": verification, "admitted": False, "formalized": False}


def cleanup_published_batches(db, runtime, *, limit: int = 2, api=None) -> list[dict[str, Any]]:
    """Bounded restart/status cleanup; existing database publication is retained."""
    if type(limit) is not int or not 1 <= limit <= 128:
        raise ValueError("cleanup limit must be between one and 128")
    # Avoid creating a second growing filesystem queue; published batches are
    # the authoritative restart work list, excluding completed journal rows.
    db.execute("""CREATE TABLE IF NOT EXISTS legacy_span_evictions (
        batch_id VARCHAR PRIMARY KEY, status VARCHAR NOT NULL,
        plan VARCHAR NOT NULL, plan_sha256 VARCHAR NOT NULL, remote_verification VARCHAR NOT NULL)""")
    pending = db.execute("""SELECT b.id FROM batches b LEFT JOIN legacy_span_evictions e ON b.id=e.batch_id
        WHERE b.status='published' AND (e.batch_id IS NULL OR e.status<>'evicted') ORDER BY b.id LIMIT ?""", [limit]).fetchall()
    return [verify_and_evict_published_batch(db, runtime, row[0], api=api) for row in pending]
