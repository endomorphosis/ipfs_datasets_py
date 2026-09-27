#!/usr/bin/env python3
"""Queue an exact v2 entity/relationship input pair; never a legal admit.

Offline by default. Queue rows and the physical input cursor commit together.
The v2 local snapshot and optional Hub key are separate from every v1 object.
No claims are implicitly released, and remote checkpoints never supply a local
physical cursor. Input files stay open from their initial full hash through the
final operation; per-batch identity guards and final full hashes detect drift.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import stat
import sys

ROOT = Path(__file__).resolve().parents[3]
REPO_ID = "justicedao/uscode-autoformal-entity-cache"
REPO_PREFIX = "autoformal/uscode/v2"
SNAPSHOT_NAME = "entity-resume-checkpoint-v2.parquet"
AGENT_ID = "entity-control-plane-v2"
MAX_INPUT_BYTES = 512 * 1024**2
MAX_RESUME_FILE_BYTES = 128 * 1024**2
MAX_INPUT_ROWS = 2_000_000
MAX_UNCOMPRESSED_BYTES = 1024**3
MAX_BATCH_BYTES = 16 * 1024**2
MAX_BATCH = 512
_HASH = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class EntityIngestError(ValueError):
    """Invalid, changed or unbound ingestion input/progress."""


def _require(value, message):
    if not value:
        raise EntityIngestError(message)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _path(value, *, exists=True):
    value = Path(value)
    _require(".." not in value.parts, "parent path components are forbidden")
    path = Path(os.path.abspath(value))
    _require(path.resolve(strict=exists) == path, "path aliases are forbidden")
    return path


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def _batch(value):
    _require(type(value) is int and 1 <= value <= MAX_BATCH, "batch must be an integer from 1 through 512")
    return value


def _batch_argument(value):
    try:
        return _batch(int(value))
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError("batch must be an integer from 1 through 512") from exc


class _Input:
    def __init__(self, path, *, max_bytes=MAX_INPUT_BYTES):
        self.path = _path(path)
        self.stream = os.fdopen(os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC), "rb")
        try:
            self.signature = _identity(os.fstat(self.stream.fileno()))
            info = os.fstat(self.stream.fileno())
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                     and 0 < info.st_size <= max_bytes, "input must be an exclusive bounded regular file")
            self.verify_current()
            self.sha256 = self._hash()
        except BaseException:
            self.stream.close()
            raise

    def close(self):
        self.stream.close()

    def verify_current(self):
        _require(not self.stream.closed and self.path.resolve(strict=True) == self.path
                 and _identity(os.fstat(self.stream.fileno())) == self.signature
                 and _identity(self.path.lstat()) == self.signature, "input identity changed")

    def _hash(self):
        self.verify_current()
        self.stream.seek(0)
        digest, count = hashlib.sha256(), 0
        while block := self.stream.read(1024**2):
            count += len(block)
            _require(count <= self.signature[3], "input grew while hashing")
            digest.update(block)
        self.verify_current()
        _require(count == self.signature[3], "input truncated while hashing")
        return digest.hexdigest()

    def verify_full(self):
        _require(self._hash() == self.sha256, "input bytes changed")

    def parquet(self, *, role):
        import pyarrow.parquet as pq
        self.verify_current()
        parquet = pq.ParquetFile(self.stream)
        count = parquet.metadata.num_rows
        _require(type(count) is int and 0 <= count <= MAX_INPUT_ROWS, "physical row count exceeds bound")
        _require(sum(parquet.metadata.row_group(i).total_byte_size for i in range(parquet.num_row_groups))
                 <= MAX_UNCOMPRESSED_BYTES, "uncompressed Parquet bytes exceed bound")
        names = parquet.schema_arrow.names
        _require(len(names) == len(set(names)) and 1 <= len(names) <= 128, "ambiguous or oversized Parquet schema")
        if role == "entities":
            _require("label" in names and ("id" in names or "entity_id" in names), "entity columns missing")
        else:
            _require({"type", "source", "target"} <= set(names), "relationship columns missing")
        self.verify_current()
        return parquet, {"sha256": self.sha256, "bytes": self.signature[3], "row_count": count}


class _BoundInputs:
    """One operation's exact source descriptors and still-open readonly files."""
    def __init__(self, entities, relationships):
        self.entity_path, self.relationship_path = entities, relationships
        self._stack = None

    def __enter__(self):
        self._stack = ExitStack()
        try:
            self.entities = _Input(self.entity_path)
            self._stack.callback(self.entities.close)
            self.relationships = _Input(self.relationship_path)
            self._stack.callback(self.relationships.close)
            _require(self.entities.signature[:2] != self.relationships.signature[:2], "entity and relationship inputs alias")
            self.entity_file, entity_ref = self.entities.parquet(role="entities")
            self.relationship_file, relationship_ref = self.relationships.parquet(role="relationships")
            self.manifest = {"schema_version": "entity-cache-inputs/v2", "dataset_id": "justicedao/ipfs_uscode",
                "entity_identity_schema": "uscode-autoformal-entity-cache/v2",
                "entities": entity_ref, "relationships": relationship_ref}
            self.input_id = "sha256:" + hashlib.sha256(_json(self.manifest)).hexdigest()
            self.verify_full()
            return self
        except BaseException:
            self._stack.close()
            self._stack = None
            raise

    def __exit__(self, *args):
        self._stack.close()
        self._stack = None

    def verify_current(self):
        _require(self._stack is not None, "input binding is closed")
        self.entities.verify_current()
        self.relationships.verify_current()

    def verify_full(self):
        self.verify_current()
        self.entities.verify_full()
        self.relationships.verify_full()

    def batches(self, role, size):
        _batch(size)
        self.verify_current()
        parquet = self.entity_file if role == "entities" else self.relationship_file
        columns = ([name for name in ("id", "entity_id", "type", "entity_type", "label", "properties_json")
                    if name in parquet.schema_arrow.names] if role == "entities" else ["type", "source", "target"])
        seen = 0
        for arrow in parquet.iter_batches(batch_size=size, columns=columns, use_threads=False):
            self.verify_current()
            _require(arrow.nbytes <= MAX_BATCH_BYTES, "decoded batch exceeds byte bound")
            rows = arrow.to_pylist()
            _require(0 < len(rows) <= size, "invalid physical batch size")
            seen += len(rows)
            _require(seen <= self.manifest[role]["row_count"], "Parquet returned excess rows")
            yield rows
            self.verify_current()
        _require(seen == self.manifest[role]["row_count"], "Parquet physical row coverage differs")
        self.verify_current()


def _checkpoint(cache, inputs):
    checkpoint = cache.checkpoint()
    _require(type(checkpoint) is dict and checkpoint.get("input_id") == inputs.input_id
             and _json(checkpoint.get("input_manifest")) == _json(inputs.manifest), "checkpoint input binding differs")
    cursor = checkpoint.get("next_ordinal")
    _require(type(cursor) is int and 0 <= cursor <= inputs.manifest["entities"]["row_count"], "corrupt physical cursor")
    return cursor


def enqueue_entities(cache, inputs, *, batch):
    """Skip only a verified physical prefix; commit rows and cursor atomically."""
    _batch(batch)
    inputs.verify_full()
    skip = _checkpoint(cache, inputs)
    seen, added = 0, 0
    for rows in inputs.batches("entities", batch):
        start, seen = seen, seen + len(rows)
        if seen <= skip:
            continue
        if start < skip:
            rows, start = rows[skip - start:], skip
        added += cache.enqueue_source_batch(rows, start, seen, verify_inputs=inputs.verify_current)
    _require(seen == inputs.manifest["entities"]["row_count"] and _checkpoint(cache, inputs) == seen,
             "entity cursor does not cover the exact physical input")
    inputs.verify_full()
    return {"admitted": False, "formalized": False, "entities": seen,
            "new": added, "resumed_from": skip, "input_id": inputs.input_id}


def prepare_pending(cache, inputs, *, batch):
    inputs.verify_full()
    _require(_checkpoint(cache, inputs) == inputs.manifest["entities"]["row_count"], "cannot prepare an incomplete input")
    # One core operation consumes all batches; it must not reset maps per batch.
    result = cache.prepare_containment_batches(inputs.batches("relationships", _batch(batch)),
                                               verify_inputs=inputs.verify_current)
    inputs.verify_full()
    return result


def _remote_key(cache):
    identifier = cache.checkpoint().get("input_id", "")
    _require(type(identifier) is str and identifier.startswith("sha256:")
             and _HASH.fullmatch(identifier[7:]), "remote checkpoint requires exact v2 input binding")
    return REPO_PREFIX + "/" + identifier[7:] + "/" + SNAPSHOT_NAME


def _poll(cache, inputs):
    """Explicit remote observation; defaults never enter this function."""
    inputs.verify_full()
    key = _remote_key(cache)
    from huggingface_hub import HfApi, hf_hub_download
    try:
        api = HfApi()
        revision = str(api.repo_info(REPO_ID, repo_type="dataset").sha)
        _require(_COMMIT.fullmatch(revision), "remote revision is not immutable")
        info = api.get_paths_info(REPO_ID, [key], repo_type="dataset", revision=revision)
        if not info:
            return {"changed": False, "admitted": False, "formalized": False}
        _require(len(info) == 1 and type(info[0].size) is int and 0 < info[0].size <= MAX_RESUME_FILE_BYTES,
                 "remote checkpoint exceeds byte bound")
        downloaded = Path(hf_hub_download(REPO_ID, key, repo_type="dataset", revision=revision)).resolve(strict=True)
        inputs.verify_full()
        _require(downloaded.stat().st_size == info[0].size, "remote checkpoint size differs")
        result = cache.upsert_remote_resume(downloaded, agent_id=AGENT_ID)
        inputs.verify_full()
        return {**result, "changed": True, "revision": revision, "admitted": False, "formalized": False}
    except (OSError, ValueError) as exc:
        inputs.verify_full()
        return {"changed": False, "error": type(exc).__name__, "admitted": False, "formalized": False}


def _flush(cache, destination, *, upload, inputs):
    inputs.verify_full()
    key = _remote_key(cache)
    root = _path(destination, exists=False) / inputs.input_id[7:]
    root.mkdir(parents=True, exist_ok=True)
    _require(root.resolve(strict=True) == root, "checkpoint directory aliases another path")
    path = root / SNAPSHOT_NAME
    if os.path.lexists(path):
        _require(not path.is_symlink(), "checkpoint destination is not an exclusive regular file")
        _require(path.resolve(strict=True) == path and stat.S_ISREG(path.lstat().st_mode)
                 and path.lstat().st_nlink == 1, "checkpoint destination is not an exclusive regular file")
    _require(path not in (inputs.entities.path, inputs.relationships.path), "checkpoint output overlaps an input")
    cache_path = _path(cache.path, exists=True)
    protected = (cache_path, Path(str(cache_path) + ".wal"))
    _require(path not in protected, "checkpoint output overlaps the cache or its WAL")
    if path.exists():
        for value in protected:
            if value.exists():
                _require(not os.path.samefile(path, value), "checkpoint output aliases the cache or its WAL")
    cache.register_agent(AGENT_ID)
    written = cache.write_resume_parquet(path)
    inputs.verify_full()
    receipt = {"admitted": False, "formalized": False, "jsonl_written": False,
        "input_id": inputs.input_id, "local_path": str(path), "task_count": written.get("task_count"),
        "uploaded": False, "remote_verified": False}
    if not upload:
        return receipt
    from huggingface_hub import HfApi
    with ExitStack() as stack:
        snapshot = _Input(path, max_bytes=MAX_RESUME_FILE_BYTES)
        stack.callback(snapshot.close)
        api = HfApi()
        inputs.verify_full()
        snapshot.verify_full()
        api.create_repo(REPO_ID, repo_type="dataset", exist_ok=True)
        parent = str(api.repo_info(REPO_ID, repo_type="dataset").sha)
        _require(_COMMIT.fullmatch(parent), "remote parent is not immutable")
        # Last complete input check immediately before the explicit remote write.
        inputs.verify_full()
        snapshot.verify_full()
        snapshot.stream.seek(0)
        result = api.upload_file(path_or_fileobj=snapshot.stream, path_in_repo=key,
            repo_id=REPO_ID, repo_type="dataset", parent_commit=parent,
            commit_message="autoformal entity v2 source-bound resume checkpoint")
        snapshot.verify_current()
        inputs.verify_full()
        receipt.update(uploaded=True, repo_id=REPO_ID, repo_path=key,
                       revision=str(getattr(result, "oid", "") or ""))
    return receipt


def _cache_type():
    # Existing imported HACC modules must fail; changing sys.path cannot repair a
    # process that already selected a different compiler/parser tree.
    if str(ROOT) in sys.path:
        sys.path.remove(str(ROOT))
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")
    pin = importlib.import_module("ipfs_datasets_py.logic.autoformal.tree_pin")
    module = importlib.import_module("ipfs_datasets_py.logic.autoformal.entity_cache")
    for value, filename in ((pin, "tree_pin.py"), (module, "entity_cache.py")):
        _require(Path(value.__file__).resolve() == ROOT / "ipfs_datasets_py/logic/autoformal" / filename,
                 "entity ingestion requires the canonical workspace tree")
    pin.require_workspace_logic_tree()
    _require(module.SCHEMA == "uscode-autoformal-entity-cache/v2", "entity ingestion requires the v2 cache")
    _require(module.MAX_RESUME_FILE_BYTES == MAX_RESUME_FILE_BYTES, "entity resume size policies differ")
    return module.EntityCache


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet", type=Path, required=True)
    parser.add_argument("--relationships", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--upload-dir", type=Path)
    parser.add_argument("--batch", type=_batch_argument, default=512)
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--poll", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--upload", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--prepare", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args(argv)
    cache_path = _path(args.cache, exists=False)
    upload_dir = args.upload_dir or cache_path.parent / "entity-hf-checkpoint-v2"
    with _BoundInputs(args.parquet, args.relationships) as inputs:
        cache_files = (cache_path, Path(str(cache_path) + ".wal"))
        _require(not set(cache_files).intersection((inputs.entities.path, inputs.relationships.path)),
                 "cache or its WAL overlaps an input")
        cache = _cache_type()(cache_path)
        try:
            inputs.verify_full()
            cache.bind_inputs(inputs.manifest, resume=args.resume)
            inputs.verify_full()
            polled = _poll(cache, inputs) if args.poll else {"changed": False, "poll_performed": False}
            enqueued = enqueue_entities(cache, inputs, batch=args.batch)
            prepared = prepare_pending(cache, inputs, batch=args.batch) if args.prepare else {
                "prepared": 0, "admitted": False, "formalized": False}
            flushed = _flush(cache, upload_dir, upload=args.upload, inputs=inputs)
            inputs.verify_full()
            print(json.dumps({"admitted": False, "formalized": False,
                "stage": "entities_prepared" if args.prepare else "entities_queued", "enqueued": enqueued,
                "prepared": prepared, "poll": polled, "hf": flushed, "stats": cache.stats()}, sort_keys=True), flush=True)
        finally:
            cache.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
