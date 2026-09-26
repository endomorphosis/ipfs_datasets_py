"""Bounded, lossless target shards in one immutable, content-addressed artifact.

The manifest binds the complete snapshot configuration and exact sample/status
inventory. Each unique target is the *same tagged JSON bytes* as the v1 JSON
snapshot, compressed independently with zlib. No metric summary replaces a
full target. The bundle has its own manifest identity, not the v1 snapshot ID.

Loading checks the external SHA of the entire regular file and the complete
manifest. It does not hydrate unrequested targets: their semantic validation
occurs on first use, after compressed and expanded digest checks. Writers
validate every target before publishing. These artifacts never admit a theorem.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import struct
import time
from typing import Any, Iterable, Mapping, Sequence
import uuid
import zlib

from ipfs_datasets_py.logic.bridge.types import LegalIRDocument
from .legal_ir_target_snapshot import (
    DEFAULT_MAX_BYTES, STATUSES, TargetSnapshot, TargetSnapshotConfig, TargetSnapshotError,
    _decode, _digest, _encode, _hash, _json, _parse, _sample_payload, _sha,
    _target_status, _validate_target,
)

SCHEMA_VERSION = "legal-ir-target-bundle-v1"
MAGIC = b"LIRTB01\n"
_HEADER = struct.Struct(">8sQ")
DEFAULT_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_SHARD_BYTES = 64 * 1024 * 1024
_CODEC = "zlib:legal-ir-target-snapshot-v1-tagged-json"
_CHUNK = 1024 * 1024
_NULL_SHA256 = _digest(None)


def _bounds(max_bytes: int, max_manifest_bytes: int, max_shard_bytes: int) -> None:
    if any(type(v) is not int or v < 1 for v in (max_bytes, max_manifest_bytes, max_shard_bytes)):
        raise TargetSnapshotError("positive artifact, manifest and shard byte bounds required")


def _open_parent(path: str | Path) -> tuple[int, str, str]:
    """Walk directories without following even an ancestor symlink."""
    supplied = Path(path)
    if ".." in supplied.parts:
        raise TargetSnapshotError("parent traversal is not allowed for target artifacts")
    absolute = Path(os.path.abspath(supplied))
    if not absolute.name:
        raise TargetSnapshotError("target artifact filename is required")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open("/", flags)
    try:
        for part in absolute.parent.parts[1:]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor, absolute.name, str(absolute)
    except BaseException:
        os.close(descriptor)
        raise


def _open_regular(path: str | Path, max_bytes: int) -> tuple[int, os.stat_result]:
    parent, name, _ = _open_parent(path)
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
            raise TargetSnapshotError("target artifact must be a bounded regular file")
        return descriptor, info
    except BaseException:
        os.close(descriptor)
        raise


def _fingerprint(info: os.stat_result) -> tuple[int, ...]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _read_at(descriptor: int, count: int, offset: int) -> bytes:
    parts = []
    remaining = count
    while remaining:
        part = os.pread(descriptor, min(_CHUNK, remaining), offset)
        if not part:
            raise TargetSnapshotError("truncated target artifact")
        parts.append(part)
        offset += len(part)
        remaining -= len(part)
    return b"".join(parts)


def _verify_file(descriptor: int, info: os.stat_result, expected_sha256: str) -> None:
    digest = hashlib.sha256()
    offset = 0
    while offset < info.st_size:
        part = os.pread(descriptor, min(_CHUNK, info.st_size - offset), offset)
        if not part:
            raise TargetSnapshotError("truncated target artifact")
        digest.update(part)
        offset += len(part)
    if _fingerprint(os.fstat(descriptor)) != _fingerprint(info) or digest.hexdigest() != expected_sha256:
        raise TargetSnapshotError("target artifact changed or external digest mismatch")


def _config(value: Any) -> TargetSnapshotConfig:
    try:
        return TargetSnapshotConfig.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise TargetSnapshotError("invalid target configuration") from exc


def _manifest(raw: bytes, *, payload_bytes: int, max_shard_bytes: int) -> dict[str, Any]:
    data = _parse(raw)
    if not isinstance(data, dict) or set(data) != {"schema_version", "codec", "config", "records", "shards", "snapshot_id"}:
        raise TargetSnapshotError("invalid bundle manifest schema")
    if data["schema_version"] != SCHEMA_VERSION or data["codec"] != _CODEC:
        raise TargetSnapshotError("unsupported target bundle schema or codec")
    _config(data["config"])
    body = {k: v for k, v in data.items() if k != "snapshot_id"}
    if data["snapshot_id"] != "sha256:" + _digest(body):
        raise TargetSnapshotError("bundle manifest identity mismatch")
    if not isinstance(data["records"], list) or not data["records"] or not isinstance(data["shards"], list):
        raise TargetSnapshotError("target bundle requires a record inventory")
    shards = {}
    extent = 0
    for shard in data["shards"]:
        if not isinstance(shard, dict) or set(shard) != {"target_sha256", "offset", "compressed_bytes", "uncompressed_bytes", "compressed_sha256"}:
            raise TargetSnapshotError("invalid target shard descriptor")
        if not _hash(shard["target_sha256"]) or not _hash(shard["compressed_sha256"]) or shard["target_sha256"] in shards:
            raise TargetSnapshotError("invalid or duplicate content-addressed shard")
        if (type(shard["offset"]) is not int or shard["offset"] != extent
                or type(shard["compressed_bytes"]) is not int or not 1 <= shard["compressed_bytes"] <= _compressed_bound(max_shard_bytes)
                or type(shard["uncompressed_bytes"]) is not int or not 1 <= shard["uncompressed_bytes"] <= max_shard_bytes):
            raise TargetSnapshotError("invalid target shard extent or expanded byte bound")
        extent += shard["compressed_bytes"]
        if extent > payload_bytes:
            raise TargetSnapshotError("target shard extent exceeds artifact")
        shards[shard["target_sha256"]] = shard
    if extent != payload_bytes:
        raise TargetSnapshotError("trailing or unindexed target artifact bytes")
    seen = set()
    referenced = set()
    for row in data["records"]:
        if not isinstance(row, dict) or set(row) != {"sample_id", "sample_sha256", "status", "has_target", "target_sha256"}:
            raise TargetSnapshotError("invalid target record schema")
        if not isinstance(row["sample_id"], str) or not row["sample_id"] or row["sample_id"] in seen or not _hash(row["sample_sha256"]):
            raise TargetSnapshotError("invalid or duplicate sample identity")
        seen.add(row["sample_id"])
        if not isinstance(row["status"], str) or row["status"] not in STATUSES or type(row["has_target"]) is not bool or not _hash(row["target_sha256"]):
            raise TargetSnapshotError("invalid target status or content identity")
        if row["has_target"]:
            if row["target_sha256"] not in shards:
                raise TargetSnapshotError("dangling target shard reference")
            referenced.add(row["target_sha256"])
        elif row["status"] == "ready" or row["target_sha256"] != _NULL_SHA256:
            raise TargetSnapshotError("missing target has invalid status or identity")
    if referenced != set(shards):
        raise TargetSnapshotError("unreferenced target shards are not allowed")
    return data


def _compressed_bound(raw_bound: int) -> int:
    # zlib compressBound, including its worst-case framing overhead.
    return raw_bound + (raw_bound >> 12) + (raw_bound >> 14) + (raw_bound >> 25) + 13


def _expand(compressed: bytes, expected_bytes: int) -> bytes:
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, expected_bytes + 1)
        # No unbounded flush: eof proves the complete zlib stream was consumed.
        if len(raw) != expected_bytes or not decoder.eof or decoder.unconsumed_tail or decoder.unused_data:
            raise TargetSnapshotError("target shard expansion bound, truncation or trailing stream bytes")
        return raw
    except zlib.error as exc:
        raise TargetSnapshotError("invalid compressed target shard") from exc


class TargetBundle:
    """Verified file plus small manifest; targets hydrate only when requested.

    Close explicitly or use as a context manager. Each request creates fresh
    containers, even when multiple rows reference an identical disk shard.
    """
    def __init__(self, descriptor: int, info: os.stat_result, manifest: dict[str, Any],
                 sha256: str, payload_offset: int, statistics: Mapping[str, Any]):
        self._descriptor = descriptor
        self._fingerprint = _fingerprint(info)
        self._manifest = manifest
        self._sha256 = sha256
        self._payload_offset = payload_offset
        self._records = {row["sample_id"]: row for row in manifest["records"]}
        self._shards = {row["target_sha256"]: row for row in manifest["shards"]}
        self._statistics = dict(statistics)
        self._decompressed = set()

    @property
    def snapshot_id(self) -> str:
        return self._manifest["snapshot_id"]

    @property
    def sha256(self) -> str:
        return self._sha256

    @property
    def config(self) -> TargetSnapshotConfig:
        # Detach nested provenance so callers cannot change manifest state.
        return _config(_parse(_json(self._manifest["config"])))

    @property
    def sample_count(self) -> int:
        return len(self._records)

    @property
    def statuses(self) -> dict[str, str]:
        return {key: row["status"] for key, row in self._records.items()}

    @property
    def statistics(self) -> dict[str, Any]:
        return {**self._statistics, "unique_decompressed_shards": len(self._decompressed), "closed": self._descriptor is None}

    def _check_open(self) -> int:
        if self._descriptor is None:
            raise TargetSnapshotError("target bundle is closed")
        if _fingerprint(os.fstat(self._descriptor)) != self._fingerprint:
            raise TargetSnapshotError("target artifact changed after verification")
        return self._descriptor

    def targets_for(self, samples: Sequence[Any], *, config: TargetSnapshotConfig) -> dict[str, Any]:
        descriptor = self._check_open()
        if _json(config.to_dict()) != _json(self._manifest["config"]):
            raise TargetSnapshotError("target configuration/provenance mismatch")
        requested = []
        seen = set()
        for sample in samples:
            sample_id, digest = _sample_payload(sample)
            if sample_id in seen:
                raise TargetSnapshotError("duplicate requested sample")
            seen.add(sample_id)
            row = self._records.get(sample_id)
            if row is None or row["sample_sha256"] != digest:
                raise TargetSnapshotError("missing or changed sample payload")
            if not row["has_target"]:
                raise TargetSnapshotError(f"sample has no injectable target: {row['status']}")
            requested.append((sample, row))
        result = {}
        for sample, row in requested:
            started = time.perf_counter()
            shard = self._shards[row["target_sha256"]]
            compressed = _read_at(descriptor, shard["compressed_bytes"], self._payload_offset + shard["offset"])
            if _sha(compressed) != shard["compressed_sha256"]:
                raise TargetSnapshotError("compressed target shard digest mismatch")
            raw = _expand(compressed, shard["uncompressed_bytes"])
            if _sha(raw) != shard["target_sha256"]:
                raise TargetSnapshotError("expanded target shard digest mismatch")
            self._statistics["read_decompress_seconds"] += time.perf_counter() - started
            self._statistics["decompressed_shards"] += 1
            self._statistics["decompressed_bytes"] += len(raw)
            self._decompressed.add(shard["target_sha256"])
            started = time.perf_counter()
            target = _decode(_parse(raw))
            _validate_target(target, sample.sample_id, config, row["status"])
            document = getattr(target, "document", None)
            if type(document) is LegalIRDocument and document.source_text != sample.text:
                raise TargetSnapshotError("target document/source text mismatch")
            result[sample.sample_id] = target
            self._statistics["hydrate_validate_seconds"] += time.perf_counter() - started
        self._check_open()
        return result

    def close(self) -> None:
        descriptor, self._descriptor = self._descriptor, None
        if descriptor is not None:
            os.close(descriptor)

    def __enter__(self) -> "TargetBundle":
        self._check_open()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def __del__(self):
        descriptor = getattr(self, "_descriptor", None)
        if descriptor is not None:
            os.close(descriptor)


def _inventory_statistics(manifest: Mapping[str, Any], manifest_bytes: int, artifact_bytes: int) -> dict[str, Any]:
    shards = {shard["target_sha256"]: shard for shard in manifest["shards"]}
    references = [row["target_sha256"] for row in manifest["records"] if row["has_target"]]
    return {
        "artifact_format": "bundle", "schema_version": SCHEMA_VERSION, "artifact_bytes": artifact_bytes,
        "manifest_bytes": manifest_bytes, "sample_count": len(manifest["records"]),
        "shard_count": len(shards), "target_reference_count": len(references),
        "deduplicated_target_count": len(references) - len(shards),
        "compressed_target_bytes": sum(row["compressed_bytes"] for row in shards.values()),
        "unique_uncompressed_target_bytes": sum(row["uncompressed_bytes"] for row in shards.values()),
        "referenced_uncompressed_target_bytes": sum(shards[key]["uncompressed_bytes"] for key in references),
    }


def write_target_bundle(path: str | Path, records: Iterable[tuple[Any, Any, str | None]], *,
                        config: TargetSnapshotConfig, max_bytes: int = DEFAULT_MAX_BYTES,
                        max_manifest_bytes: int = DEFAULT_MAX_MANIFEST_BYTES,
                        max_shard_bytes: int = DEFAULT_MAX_SHARD_BYTES) -> dict[str, Any]:
    """Stream validated targets; atomically publish exclusively after exhaustion.

    Records are ``(LegalSample, complete_target_or_None, explicit_status_or_None)``.
    A producer can perform its final provenance check before its iterator ends;
    failures leave no published artifact. One encoded/compressed target is held
    at a time, plus the bounded manifest. Exactly identical targets share bytes.
    """
    _bounds(max_bytes, max_manifest_bytes, max_shard_bytes)
    config_payload = config.to_dict()
    # Freeze caller-owned dependency provenance before consuming the iterator.
    config_payload = _parse(_json(config_payload))
    frozen_config = _config(config_payload)
    parent, name, absolute = _open_parent(path)
    spool_name = ".target-shards-" + uuid.uuid4().hex
    final_name = ".target-bundle-" + uuid.uuid4().hex
    spool = final = None
    manifest_rows, shard_rows, by_hash, seen = [], [], {}, set()
    extent = 0
    estimated_manifest_bytes = len(_json(config_payload)) + 512
    encoding_seconds = compression_seconds = 0.0
    try:
        if estimated_manifest_bytes > max_manifest_bytes or estimated_manifest_bytes + _HEADER.size > max_bytes:
            raise TargetSnapshotError("configuration exceeds manifest or artifact byte bound")
        try:
            os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(absolute)
        spool = os.fdopen(os.open(spool_name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                  0o600, dir_fd=parent), "w+b")
        os.unlink(spool_name, dir_fd=parent)
        for sample, target, status in records:
            sample_id, sample_sha256 = _sample_payload(sample)
            if sample_id in seen:
                raise TargetSnapshotError("duplicate sample identity")
            seen.add(sample_id)
            if status is None:
                if target is None:
                    raise TargetSnapshotError("missing target requires explicit failure status")
                status = _target_status(target)
            if not isinstance(status, str) or status not in STATUSES or (target is None and status == "ready"):
                raise TargetSnapshotError("invalid target status or missing ready target")
            target_sha256 = _NULL_SHA256
            if target is not None:
                started = time.perf_counter()
                _validate_target(target, sample_id, frozen_config, status)
                document = getattr(target, "document", None)
                if type(document) is LegalIRDocument and document.source_text != sample.text:
                    raise TargetSnapshotError("target document/source text mismatch")
                raw = _json(_encode(target))
                if len(raw) > max_shard_bytes:
                    raise TargetSnapshotError("encoded target exceeds shard byte bound")
                target_sha256 = _sha(raw)
                encoding_seconds += time.perf_counter() - started
                if target_sha256 not in by_hash:
                    started = time.perf_counter()
                    compressed = zlib.compress(raw, level=6)
                    compression_seconds += time.perf_counter() - started
                    shard = {"target_sha256": target_sha256, "offset": extent,
                             "compressed_bytes": len(compressed), "uncompressed_bytes": len(raw),
                             "compressed_sha256": _sha(compressed)}
                    extent += len(compressed)
                    if extent + estimated_manifest_bytes + _HEADER.size > max_bytes:
                        raise TargetSnapshotError("target bundle exceeds artifact byte bound")
                    spool.write(compressed)
                    shard_rows.append(shard)
                    by_hash[target_sha256] = shard
                    estimated_manifest_bytes += len(_json(shard)) + 1
                    del compressed
                del raw
            row = {"sample_id": sample_id, "sample_sha256": sample_sha256, "status": status,
                   "has_target": target is not None, "target_sha256": target_sha256}
            manifest_rows.append(row)
            estimated_manifest_bytes += len(_json(row)) + 1
            if estimated_manifest_bytes > max_manifest_bytes:
                raise TargetSnapshotError("target inventory exceeds manifest byte bound")
            # Drop consumer references before the producer computes another target.
            sample = target = document = None
        body = {"schema_version": SCHEMA_VERSION, "codec": _CODEC, "config": config_payload,
                "records": manifest_rows, "shards": shard_rows}
        manifest = {**body, "snapshot_id": "sha256:" + _digest(body)}
        manifest_raw = _json(manifest)
        artifact_bytes = _HEADER.size + len(manifest_raw) + extent
        if len(manifest_raw) > max_manifest_bytes or artifact_bytes > max_bytes:
            raise TargetSnapshotError("target bundle manifest or artifact byte bound exceeded")
        _manifest(manifest_raw, payload_bytes=extent, max_shard_bytes=max_shard_bytes)
        header = _HEADER.pack(MAGIC, len(manifest_raw))
        final = os.fdopen(os.open(final_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                  0o600, dir_fd=parent), "wb")
        digest = hashlib.sha256()
        for part in (header, manifest_raw):
            final.write(part)
            digest.update(part)
        spool.seek(0)
        while part := spool.read(_CHUNK):
            final.write(part)
            digest.update(part)
        final.flush()
        os.fsync(final.fileno())
        os.link(final_name, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
        os.fsync(parent)
        statistics = _inventory_statistics(manifest, len(manifest_raw), artifact_bytes)
        statistics.update(encoding_validate_seconds=encoding_seconds, compression_seconds=compression_seconds)
        return {"path": absolute, "sha256": digest.hexdigest(), "bytes": artifact_bytes,
                "snapshot_id": manifest["snapshot_id"], "statistics": statistics}
    finally:
        if spool is not None:
            spool.close()
        if final is not None:
            final.close()
        for temporary in (spool_name, final_name):
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass
        os.close(parent)


def load_target_bundle(path: str | Path, *, expected_sha256: str, samples: Sequence[Any] | None = None,
                       config: TargetSnapshotConfig | None = None, max_bytes: int = DEFAULT_MAX_BYTES,
                       max_manifest_bytes: int = DEFAULT_MAX_MANIFEST_BYTES,
                       max_shard_bytes: int = DEFAULT_MAX_SHARD_BYTES) -> TargetBundle:
    """Verify all artifact bytes, then retain only a manifest and read-only fd."""
    _bounds(max_bytes, max_manifest_bytes, max_shard_bytes)
    if not _hash(expected_sha256):
        raise TargetSnapshotError("expected target artifact SHA-256 required")
    started = time.perf_counter()
    descriptor, info = _open_regular(path, max_bytes)
    bundle = None
    try:
        _verify_file(descriptor, info, expected_sha256)
        hash_seconds = time.perf_counter() - started
        started = time.perf_counter()
        magic, size = _HEADER.unpack(_read_at(descriptor, _HEADER.size, 0))
        if magic != MAGIC or not 1 <= size <= max_manifest_bytes or _HEADER.size + size > info.st_size:
            raise TargetSnapshotError("invalid target bundle header or manifest byte bound")
        raw = _read_at(descriptor, size, _HEADER.size)
        manifest = _manifest(raw, payload_bytes=info.st_size - _HEADER.size - size, max_shard_bytes=max_shard_bytes)
        if config is not None and _json(manifest["config"]) != _json(config.to_dict()):
            raise TargetSnapshotError("target configuration/provenance mismatch")
        statistics = _inventory_statistics(manifest, size, info.st_size)
        statistics.update(open_hash_seconds=hash_seconds, manifest_parse_validate_seconds=time.perf_counter() - started,
                          read_decompress_seconds=0.0, hydrate_validate_seconds=0.0,
                          decompressed_shards=0, decompressed_bytes=0)
        bundle = TargetBundle(descriptor, info, manifest, expected_sha256, _HEADER.size + size, statistics)
        if samples is not None:
            bundle.targets_for(samples, config=config or bundle.config)
        bundle._check_open()
        return bundle
    except BaseException:
        if bundle is not None:
            bundle.close()
        else:
            os.close(descriptor)
        raise


def load_target_artifact(path: str | Path, *, expected_sha256: str, samples: Sequence[Any] | None = None,
                         config: TargetSnapshotConfig | None = None, max_bytes: int = DEFAULT_MAX_BYTES,
                         max_manifest_bytes: int = DEFAULT_MAX_MANIFEST_BYTES,
                         max_shard_bytes: int = DEFAULT_MAX_SHARD_BYTES):
    """Load the versioned bundle or the unchanged legacy JSON snapshot."""
    _bounds(max_bytes, max_manifest_bytes, max_shard_bytes)
    if not _hash(expected_sha256):
        raise TargetSnapshotError("expected target artifact SHA-256 required")
    descriptor, info = _open_regular(path, max_bytes)
    try:
        magic = os.pread(descriptor, len(MAGIC), 0)
        if magic != MAGIC:
            # Preserve the legacy codec while retaining this securely opened fd.
            raw = _read_at(descriptor, info.st_size, 0)
            if _sha(raw) != expected_sha256 or _fingerprint(os.fstat(descriptor)) != _fingerprint(info):
                raise TargetSnapshotError("snapshot changed or external digest mismatch")
            snapshot = TargetSnapshot(raw)
            if config is not None and _json(snapshot.config.to_dict()) != _json(config.to_dict()):
                raise TargetSnapshotError("target configuration/provenance mismatch")
            if samples is not None:
                snapshot.targets_for(samples, config=config or snapshot.config)
            return snapshot
    finally:
        os.close(descriptor)
    return load_target_bundle(path, expected_sha256=expected_sha256, samples=samples, config=config,
                              max_bytes=max_bytes, max_manifest_bytes=max_manifest_bytes, max_shard_bytes=max_shard_bytes)
