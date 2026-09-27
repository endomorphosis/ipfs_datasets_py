"""Complete Git populations backed by fully hashed, bounded blob frames.

Manifests retain references, not blob bytes. Git object storage remains the
content owner. Projection rechecks every blob before returning any verified
snapshot, and exposes analysis limitations for oversized inputs explicitly.
No API here grants semantic acceptance, durable availability or completion.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass
import hashlib
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time
from typing import Any, Iterator

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes, cid_for_byte_chunks, cid_for_bytes, cid_for_structured,
)
from .committed_snapshot import CommittedPopulationEntry, preflight_committed_repository, _fence
from .snapshot import (
    GIT_COMMAND_TIMEOUT_SECONDS, GitCommandTimeout, GitSnapshotError,
    RepositorySnapshot, SnapshotEntry, SnapshotError, _entry, _malformed_raw, _opaque,
)

MAX_FRAME_BYTES = 1024 * 1024
MAX_MATERIALIZED_FILE_BYTES = 4 * 1024 * 1024
MAX_RETAINED_SOURCE_BYTES = 128 * 1024 * 1024
MAX_GIT_DECODER_ADDRESS_BYTES = 128 * 1024 * 1024
GIT_DECODER_CONFIG = (("core.packedGitWindowSize", "8388608"),
                      ("core.packedGitLimit", "33554432"),
                      ("core.deltaBaseCacheLimit", "16777216"))
_GIT_STREAM_LAUNCHER = (
    "import os,resource,sys; "
    "n=int(sys.argv[1]); resource.setrlimit(resource.RLIMIT_AS,(n,n)); "
    "os.execvp('git',['git',*sys.argv[2:]])"
)


class GitBlobDecoderError(GitSnapshotError):
    """The bounded decoder failed; content verification did not complete."""

    def __init__(self):
        super().__init__("bounded Git blob decoder failed or warned")
        self.decoder_address_limit_bytes = MAX_GIT_DECODER_ADDRESS_BYTES


@dataclass(frozen=True)
class ChunkedSnapshotLimits:
    frame_bytes: int = MAX_FRAME_BYTES
    max_entries: int = 20000
    max_stream_bytes: int = 128 * 1024 * 1024
    max_chunks: int = 65536
    max_metadata_bytes: int = 32 * 1024 * 1024

    def __post_init__(self) -> None:
        if any(type(n) is not int or n < 1 for n in asdict(self).values()):
            raise SnapshotError("chunked acquisition limits must be positive integers")
        if self.frame_bytes > MAX_FRAME_BYTES:
            raise SnapshotError("frame_bytes exceeds the fixed frame bound")


@dataclass(frozen=True)
class BlobChunk:
    offset: int
    size_bytes: int
    source_cid: str


@dataclass(frozen=True)
class ChunkedBlob:
    git_object_oid: str
    size_bytes: int
    source_cid: str
    chunks: tuple[BlobChunk, ...]

    def payload(self) -> dict[str, Any]:
        return {"schema": "ipfs-datasets.git-blob-chunks@1",
                "git_object_oid": self.git_object_oid, "size_bytes": self.size_bytes,
                "source_cid": self.source_cid,
                "chunks": [asdict(chunk) for chunk in self.chunks]}


@dataclass(frozen=True)
class ChunkedRepositorySnapshot:
    repository_id: str
    git_commit: str
    git_tree: str
    population_cid: str
    entries: tuple[CommittedPopulationEntry, ...]
    blobs: tuple[ChunkedBlob, ...]
    limits: ChunkedSnapshotLimits

    def manifest_blocks(self) -> tuple[str, dict[str, bytes]]:
        """Return a bounded manifest DAG; every structured block is a frame.

        The root and every referenced block are content addressed. Blob data
        is deliberately absent. A serialized manifest is a reference claim;
        projection must reverify the objects before using their identities.
        """
        blocks: dict[str, bytes] = {}
        retained = 0

        def put(payload):
            nonlocal retained
            raw = canonical_dag_json_bytes(payload)
            if len(raw) > MAX_FRAME_BYTES:
                raise SnapshotError("chunk manifest exceeds the fixed frame bound")
            cid = cid_for_structured(payload)
            if cid not in blocks:
                retained += len(raw)
                if retained > self.limits.max_metadata_bytes:
                    raise SnapshotError("chunk manifests exceed metadata budget")
                blocks[cid] = raw
            return cid

        def pages(records, kind):
            refs, page, size = [], [], 256
            for record in records:
                extent = len(canonical_dag_json_bytes(record)) + 1
                if page and size + extent > MAX_FRAME_BYTES:
                    refs.append(put({"schema": "ipfs-datasets.git-chunk-index-page@1",
                                     "kind": kind, "records": page}))
                    page, size = [], 256
                page.append(record)
                size += extent
            if page:
                refs.append(put({"schema": "ipfs-datasets.git-chunk-index-page@1",
                                 "kind": kind, "records": page}))
            return refs

        blob_pages = pages(({"git_object_oid": blob.git_object_oid,
                             "manifest_cid": put(blob.payload())} for blob in self.blobs), "blobs")
        entry_pages = pages((entry.to_dict() for entry in self.entries), "entries")
        root = put({"schema": "ipfs-datasets.git-chunked-snapshot@1",
                    "repository_id": self.repository_id, "git_commit": self.git_commit,
                    "git_tree": self.git_tree, "population_cid": self.population_cid,
                    "scope": "complete-committed", "entry_pages": entry_pages,
                    "blob_pages": blob_pages, "entry_count": len(self.entries),
                    "unique_blob_count": len(self.blobs), "limits": asdict(self.limits),
                    "git_decoder_address_bytes": MAX_GIT_DECODER_ADDRESS_BYTES,
                    "git_decoder_config": dict(GIT_DECODER_CONFIG)})
        return root, blocks

    @property
    def snapshot_cid(self) -> str:
        return self.manifest_blocks()[0]


def _git_blob_frames(root: Path, oid: str, size: int, frame_bytes: int) -> Iterator[bytes]:
    """Stream a fixed object without a subprocess capture_output accumulator."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    try:
        child = subprocess.Popen(
            [sys.executable, "-I", "-S", "-B", "-c", _GIT_STREAM_LAUNCHER,
             str(MAX_GIT_DECODER_ADDRESS_BYTES),
             "--no-optional-locks", "--no-replace-objects", "-c", "core.fsmonitor=false",
             *(arg for key, value in GIT_DECODER_CONFIG for arg in ("-c", key + "=" + value)),
             "-c", "core.hooksPath=/dev/null", "-C", str(root), "cat-file", "blob", oid],
            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True)
    except OSError as exc:
        raise GitSnapshotError("committed blob stream unavailable") from exc
    pending, errors, received = bytearray(), bytearray(), 0
    deadline = time.monotonic() + GIT_COMMAND_TIMEOUT_SECONDS
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ, "stdout")
            selector.register(child.stderr, selectors.EVENT_READ, "stderr")
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise GitCommandTimeout("committed blob stream timed out")
                for key, _ in selector.select(min(remaining, 0.1)):
                    bound = min(65536, frame_bytes - len(pending)) if key.data == "stdout" else 65536
                    data = os.read(key.fileobj.fileno(), bound)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    if key.data == "stderr":
                        if len(errors) + len(data) > 65536:
                            raise GitSnapshotError("committed blob error output exceeded budget")
                        errors.extend(data)
                        continue
                    received += len(data)
                    if received > size:
                        raise GitSnapshotError("committed blob stream exceeds recorded size")
                    pending.extend(data)
                    if len(pending) == frame_bytes:
                        frame = bytes(pending)
                        pending.clear()
                        yield frame
            if pending:
                yield bytes(pending)
        try:
            child.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            raise GitCommandTimeout("committed blob stream timed out") from exc
        if child.returncode or errors:
            raise GitBlobDecoderError()
        if received != size:
            raise GitSnapshotError("committed blob stream was truncated")
    except BaseException:
        if child.returncode is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=5)
        raise
    finally:
        child.stdout.close()
        child.stderr.close()


def _hash_blob(root: Path, oid: str, size: int, frame_bytes: int,
               *, capture: bool = False, capture_chunk: int | None = None) -> tuple[ChunkedBlob, bytes | None]:
    digest = hashlib.sha1() if len(oid) == 40 else hashlib.sha256()
    digest.update(b"blob " + str(size).encode("ascii") + b"\0")
    chunks, retained, offset = [], bytearray() if capture or capture_chunk is not None else None, 0

    def observed(frames):
        nonlocal offset
        for frame in frames:
            if type(frame) is not bytes or not frame or len(frame) > frame_bytes:
                raise GitSnapshotError("invalid committed blob frame")
            digest.update(frame)
            chunks.append(BlobChunk(offset, len(frame), cid_for_bytes(frame)))
            offset += len(frame)
            if offset > size:
                raise GitSnapshotError("committed blob exceeds recorded size")
            if retained is not None and (capture or len(chunks) - 1 == capture_chunk):
                retained.extend(frame)
            yield frame

    with closing(_git_blob_frames(root, oid, size, frame_bytes)) as frames:
        source_cid = cid_for_byte_chunks(observed(frames), max_chunk_bytes=frame_bytes)
    if offset != size or digest.hexdigest() != oid:
        raise GitSnapshotError("streamed bytes differ from committed object identity")
    return ChunkedBlob(oid, size, source_cid, tuple(chunks)), bytes(retained) if retained is not None else None


def _observe(repository, commit, tree, identity, limits):
    # Retained-snapshot byte budgets remain unchanged. Streaming work has its
    # own explicit bound, checked on unique objects before content is read.
    plan = preflight_committed_repository(
        repository, expected_commit=commit, expected_tree=tree, repository_id=identity,
        max_entries=limits.max_entries, max_metadata_bytes=limits.max_metadata_bytes)
    if len(plan.entries) > limits.max_entries:
        raise SnapshotError("chunked population exceeds entry budget")
    sizes = {}
    for entry in plan.entries:
        if entry.object_type == "blob":
            if entry.git_object_oid in sizes and sizes[entry.git_object_oid] != entry.size_bytes:
                raise GitSnapshotError("committed blob has contradictory sizes")
            sizes[entry.git_object_oid] = entry.size_bytes
    if sum(sizes.values()) > limits.max_stream_bytes:
        raise SnapshotError("unique committed blobs exceed streaming work budget")
    count = sum((size + limits.frame_bytes - 1) // limits.frame_bytes for size in sizes.values())
    if count > limits.max_chunks:
        raise SnapshotError("committed blobs exceed chunk reference budget")
    estimated_metadata = (2 * len(canonical_dag_json_bytes(plan.population_payload()))
                          + len(sizes) * 768 + count * 200 + 4096)
    if estimated_metadata > limits.max_metadata_bytes:
        raise SnapshotError("committed manifest estimate exceeds metadata budget")
    # Bound each future blob manifest before reading any content. The exact
    # manifest/DAG byte limit is checked again before publication.
    if any(512 + ((size + limits.frame_bytes - 1) // limits.frame_bytes) * 160 > MAX_FRAME_BYTES
           for size in sizes.values()):
        raise SnapshotError("committed blob manifest would exceed the fixed frame bound")
    return plan, sizes


def snapshot_chunked_repository(
    repository: str | os.PathLike[str], *, expected_commit: str, expected_tree: str,
    repository_id: str, limits: ChunkedSnapshotLimits = ChunkedSnapshotLimits(),
) -> ChunkedRepositorySnapshot:
    """Hash the complete population, retaining bounded references only."""
    if not isinstance(limits, ChunkedSnapshotLimits):
        raise SnapshotError("chunked acquisition requires typed limits")
    root = Path(repository).resolve(strict=True)
    plan, sizes = _observe(root, expected_commit, expected_tree, repository_id, limits)
    before = _fence(root, plan.commit, plan.tree, limits.max_metadata_bytes)
    blobs = tuple(_hash_blob(root, oid, size, limits.frame_bytes)[0] for oid, size in sorted(sizes.items()))
    if _fence(root, plan.commit, plan.tree, limits.max_metadata_bytes) != before:
        raise GitSnapshotError("source index changed during chunked acquisition")
    result = ChunkedRepositorySnapshot(repository_id, plan.commit, plan.tree,
                                       plan.population_cid, plan.entries, blobs, limits)
    result.manifest_blocks()  # No result escapes before all manifest bounds pass.
    return result


@dataclass(frozen=True)
class ChunkedProjection:
    snapshot: RepositorySnapshot
    chunked_snapshot_cid: str
    unique_blob_bytes_verified: int
    retained_source_bytes: int


def read_chunked_blob_frame(
    repository: str | os.PathLike[str], chunked: ChunkedRepositorySnapshot,
    *, git_object_oid: str, chunk_index: int,
) -> bytes:
    """Return one bounded frame after rehashing its complete immutable blob.

    No partial iterator is called whole-object verification. Git compressed
    objects currently require a full stream per read; this is not an indexed
    random-access cache. Other blobs are not claimed verified by this read.
    """
    if not isinstance(chunked, ChunkedRepositorySnapshot):
        raise SnapshotError("frame read requires a chunked snapshot")
    root = Path(repository).resolve(strict=True)
    plan, sizes = _observe(root, chunked.git_commit, chunked.git_tree,
                           chunked.repository_id, chunked.limits)
    if plan.population_cid != chunked.population_cid or plan.entries != chunked.entries:
        raise GitSnapshotError("chunked manifest differs from complete committed population")
    claims = {blob.git_object_oid: blob for blob in chunked.blobs}
    if len(claims) != len(chunked.blobs) or set(claims) != set(sizes):
        raise GitSnapshotError("chunked manifest omits or duplicates committed blobs")
    if git_object_oid not in claims:
        raise GitSnapshotError("frame object is outside the committed population")
    claim = claims[git_object_oid]
    if type(chunk_index) is not int or not 0 <= chunk_index < len(claim.chunks):
        raise SnapshotError("chunk_index is outside the blob manifest")
    chunked.manifest_blocks()
    before = _fence(root, plan.commit, plan.tree, chunked.limits.max_metadata_bytes)
    observed, data = _hash_blob(root, git_object_oid, sizes[git_object_oid],
                                chunked.limits.frame_bytes, capture_chunk=chunk_index)
    if observed != claim:
        raise GitSnapshotError("streamed blob does not verify chunked manifest")
    if _fence(root, plan.commit, plan.tree, chunked.limits.max_metadata_bytes) != before:
        raise GitSnapshotError("source index changed during committed frame read")
    return data


def project_chunked_repository(
    repository: str | os.PathLike[str], chunked: ChunkedRepositorySnapshot,
    *, max_file_bytes: int = MAX_MATERIALIZED_FILE_BYTES,
    max_total_bytes: int = MAX_RETAINED_SOURCE_BYTES,
) -> ChunkedProjection:
    """Reverify every blob, retaining only bounded inputs for legacy scanners.

    Oversized blobs have verified source identities but remain analysis-opaque;
    they are never called analyzed or omitted from the exact population. The
    caller must bind chunked_snapshot_cid alongside the scanner snapshot.
    """
    if not isinstance(chunked, ChunkedRepositorySnapshot):
        raise SnapshotError("projection requires a chunked snapshot")
    if any(type(n) is not int or n < 1 for n in (max_file_bytes, max_total_bytes)):
        raise SnapshotError("projection limits must be positive integers")
    if max_file_bytes > MAX_MATERIALIZED_FILE_BYTES or max_total_bytes > MAX_RETAINED_SOURCE_BYTES:
        raise SnapshotError("projection exceeds fixed retained-content bounds")
    root = Path(repository).resolve(strict=True)
    plan, sizes = _observe(root, chunked.git_commit, chunked.git_tree,
                           chunked.repository_id, chunked.limits)
    if plan.population_cid != chunked.population_cid or plan.entries != chunked.entries:
        raise GitSnapshotError("chunked manifest differs from complete committed population")
    claims = {blob.git_object_oid: blob for blob in chunked.blobs}
    if len(claims) != len(chunked.blobs) or set(claims) != set(sizes):
        raise GitSnapshotError("chunked manifest omits or duplicates committed blobs")
    eligible = [entry for entry in plan.entries
                if entry.git_mode in {"100644", "100755"}
                and not _malformed_raw(bytes.fromhex(entry.raw_path_hex))
                and entry.size_bytes <= max_file_bytes]
    if sum(entry.size_bytes for entry in eligible) > max_total_bytes:
        raise SnapshotError("projection exceeds retained source byte budget")
    capture = {entry.git_object_oid for entry in eligible}
    snapshot_cid = chunked.snapshot_cid
    before = _fence(root, plan.commit, plan.tree, chunked.limits.max_metadata_bytes)
    captured = {}
    for oid, size in sorted(sizes.items()):
        observed, data = _hash_blob(root, oid, size, chunked.limits.frame_bytes, capture=oid in capture)
        if observed != claims[oid]:
            raise GitSnapshotError("streamed blob does not verify chunked manifest")
        if data is not None:
            captured[oid] = data
    if _fence(root, plan.commit, plan.tree, chunked.limits.max_metadata_bytes) != before:
        raise GitSnapshotError("source index changed during chunked projection")
    entries = []
    for item in plan.entries:
        raw, oid = bytes.fromhex(item.raw_path_hex), item.git_object_oid
        if item.object_type != "blob":
            entries.append(_opaque(item.path, "symlink_or_nonregular", None, raw=raw,
                                   oid=oid, disposition="clean", head_oid=oid))
            continue
        reason = ("malformed_path" if _malformed_raw(raw) else
                  "symlink_or_nonregular" if item.git_mode == "120000" else
                  "analysis_budget_exceeded" if item.size_bytes > max_file_bytes else None)
        if reason:
            entries.append(SnapshotEntry(item.path, "opaque", item.size_bytes,
                                         source_cid=claims[oid].source_cid, opaque_reason=reason,
                                         raw_path_hex=item.raw_path_hex, git_blob_oid=oid,
                                         acquisition="git-object", disposition="clean", head_blob_oid=oid))
        else:
            entries.append(_entry(item.path, raw, captured[oid], max_file_bytes, oid,
                                  disposition="clean", head_oid=oid, acquisition="git-object"))
    snapshot = RepositorySnapshot(plan.repository_id, tuple(entries), "git-clean", max_file_bytes,
                                  chunked.limits.max_entries, plan.tree, plan.commit, ())
    return ChunkedProjection(snapshot, snapshot_cid, sum(sizes.values()), sum(map(len, captured.values())))


__all__ = ["BlobChunk", "ChunkedBlob", "ChunkedSnapshotLimits", "ChunkedRepositorySnapshot",
           "ChunkedProjection", "snapshot_chunked_repository", "project_chunked_repository",
           "read_chunked_blob_frame", "GitBlobDecoderError"]
