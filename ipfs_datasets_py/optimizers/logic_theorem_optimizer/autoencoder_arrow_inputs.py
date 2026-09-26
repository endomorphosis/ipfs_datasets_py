"""Optional exact float32 Arrow inputs bound to a native producer receipt.

Only numeric views are zero-copy. Receipt/source verification, IPC sealing,
metadata decoding, Python scalar access, and the surrounding training pipeline
are not zero-copy. Files must remain immutable while mapped. Boundary rehashes
detect observed changes, not mutation followed by restoration between checks.
Closing the owner
invalidates its Sequence views; already-exported read-only NumPy arrays retain
the mapping until released, so closing never invalidates a live raw pointer.
"""
from __future__ import annotations

from collections.abc import Iterator, Sequence
import hashlib
import json
import mmap
import operator
import os
from pathlib import Path
import re
import stat
import struct
import sys
import tempfile
import weakref
from typing import Any

from .autoencoder_corpus_manifest import SourceSampleRecord
from .autoencoder_embedding_production import EmbeddingProductionReceipt

SCHEMA_VERSION = "autoencoder-embedding-inputs-arrow-v1"
MAX_RECORDS = 256
MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
DIMENSION = 384
_HASH = re.compile(r"[0-9a-f]{64}")
_VIEW_TOKEN = object()


class ArrowInputError(ValueError):
    """A bounded Arrow input artifact or its exact producer binding is invalid."""


def _digest(value, name):
    if type(value) is not str or not _HASH.fullmatch(value):
        raise ArrowInputError(f"{name} must be a lowercase SHA-256")
    return value


def _stat_identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _verified_records(records, production, resolver):
    if type(production) is not EmbeddingProductionReceipt:
        raise ArrowInputError("production must be an exact EmbeddingProductionReceipt")
    if type(records) not in (list, tuple) or not 1 <= len(records) <= MAX_RECORDS:
        raise ArrowInputError("Arrow inputs require 1 through 256 source records")
    try:
        production = EmbeddingProductionReceipt(production.to_bytes())
        checked = tuple(SourceSampleRecord.from_dict(item.to_dict()) for item in records)
        production.verify_records(checked, resolver=resolver)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ArrowInputError("source records do not match verified native production") from exc
    return checked, production


def _binding(records, production):
    record_ids = [item.record_id for item in records]
    order = json.dumps(record_ids, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    return {"schema_version": SCHEMA_VERSION, "production_sha256": production.sha256,
            "production_bytes": len(production.to_bytes()),
            "ordered_record_ids_sha256": hashlib.sha256(order).hexdigest(),
            "row_count": len(records), "dimension": DIMENSION}


def _schema(pa, binding):
    return pa.schema([
        pa.field("record_id", pa.binary(32), nullable=False),
        pa.field("embedding", pa.list_(pa.field("value", pa.float32(), nullable=False), DIMENSION), nullable=False),
    ], metadata={key.encode("ascii"): str(value).encode("ascii") for key, value in binding.items()})


def _record_bits(record):
    # Producer validation already establishes exact float32 representability.
    return struct.pack(f"<{DIMENSION}f", *record.sample.embedding_vector)


def write_embedding_inputs_ipc(records, destination, *, production, resolver):
    """Seal one uncompressed batch exclusively, after exact source verification."""
    import pyarrow as pa

    checked, production = _verified_records(records, production, resolver)
    binding = _binding(checked, production)
    schema = _schema(pa, binding)
    path = Path(destination)
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    numeric = b"".join(_record_bits(item) for item in checked)
    scalars = pa.Array.from_buffers(pa.float32(), len(checked) * DIMENSION, [None, pa.py_buffer(numeric)])
    vectors = pa.FixedSizeListArray.from_arrays(scalars, type=schema.field("embedding").type)
    identifiers = pa.array([bytes.fromhex(item.record_id.removeprefix("sha256:")) for item in checked], type=pa.binary(32))
    batch = pa.record_batch([identifiers, vectors], schema=schema)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w+b", prefix=f".{path.name}.", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            options = pa.ipc.IpcWriteOptions(compression=None, use_threads=False)
            with pa.ipc.new_file(handle, schema, options=options) as writer:
                writer.write_batch(batch)
            handle.flush()
            os.fsync(handle.fileno())
        size = temporary.stat().st_size
        if not 1 <= size <= MAX_ARTIFACT_BYTES:
            raise ArrowInputError("sealed Arrow artifact exceeds byte bound")
        digest = hashlib.sha256()
        with temporary.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        os.link(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return {"path": str(path.absolute()), "sha256": digest.hexdigest(), "bytes": size, **binding}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class _FlatBuffer:
    """Bounded IPC metadata inspection before Arrow can allocate/decompress.

    Field positions follow Apache Arrow format/File.fbs and format/Message.fbs:
    https://github.com/apache/arrow/tree/main/format
    This reads only the closed single-batch layout, not arbitrary Arrow types.
    """

    def __init__(self, raw):
        self.raw = raw

    def number(self, fmt, offset):
        size = struct.calcsize(fmt)
        if not 0 <= offset <= len(self.raw) - size:
            raise ArrowInputError("Arrow metadata offset is outside its byte bounds")
        return struct.unpack_from(fmt, self.raw, offset)[0]

    def field(self, table, slot):
        vtable = table - self.number("<i", table)
        length = self.number("<H", vtable)
        object_size = self.number("<H", vtable + 2)
        if length < 4 or vtable + length > len(self.raw) or object_size < 4 or table + object_size > len(self.raw):
            raise ArrowInputError("invalid Arrow metadata table")
        if 4 + slot * 2 >= length:
            return None
        relative = self.number("<H", vtable + 4 + slot * 2)
        if relative == 0:
            return None
        if not 4 <= relative < object_size:
            raise ArrowInputError("invalid Arrow metadata field")
        return table + relative

    def indirect(self, position):
        if position is None:
            raise ArrowInputError("required Arrow metadata field is absent")
        target = position + self.number("<I", position)
        if not 0 <= target < len(self.raw):
            raise ArrowInputError("invalid Arrow metadata indirection")
        return target

    def vector(self, table, slot, stride):
        position = self.field(table, slot)
        if position is None:
            return 0, 0
        vector = self.indirect(position)
        count = self.number("<I", vector)
        if count > (len(self.raw) - vector - 4) // stride:
            raise ArrowInputError("Arrow metadata vector exceeds bounds")
        return vector + 4, count

    @property
    def root(self):
        return self.number("<I", 0)


def _preflight(file_buffer, row_count):
    """Reject compression and oversized allocations before get_batch()."""
    raw = memoryview(file_buffer).cast("B")
    if len(raw) < 18 or raw[:8] != b"ARROW1\x00\x00" or raw[-6:] != b"ARROW1":
        raise ArrowInputError("not a qualified Arrow IPC file")
    footer_size = struct.unpack_from("<I", raw, len(raw) - 10)[0]
    footer_start = len(raw) - 10 - footer_size
    if not 8 <= footer_start < len(raw) - 10:
        raise ArrowInputError("invalid Arrow footer length")
    footer = _FlatBuffer(raw[footer_start:len(raw) - 10])
    _, dictionaries = footer.vector(footer.root, 2, 24)
    blocks, count = footer.vector(footer.root, 3, 24)
    if dictionaries or count != 1 or footer.field(footer.root, 4) is not None:
        raise ArrowInputError("Arrow inputs require one record batch without dictionaries or footer metadata")
    offset = footer.number("<q", blocks)
    metadata_size = footer.number("<i", blocks + 8)
    body_size = footer.number("<q", blocks + 16)
    if (offset < 8 or offset % 8 or not 8 <= metadata_size <= 65536 or metadata_size % 8
            or not 0 <= body_size <= MAX_ARTIFACT_BYTES or offset + metadata_size + body_size + 8 != footer_start):
        raise ArrowInputError("Arrow record batch byte extents exceed qualified bounds")
    if raw[offset:offset + 4] != b"\xff\xff\xff\xff" or struct.unpack_from("<I", raw, offset + 4)[0] != metadata_size - 8:
        raise ArrowInputError("unsupported Arrow record batch framing")
    if raw[footer_start - 8:footer_start] != b"\xff\xff\xff\xff\x00\x00\x00\x00":
        raise ArrowInputError("unsupported Arrow end-of-stream framing")
    message = _FlatBuffer(raw[offset + 8:offset + metadata_size])
    header_kind = message.field(message.root, 1)
    if header_kind is None or message.number("<B", header_kind) != 3:
        raise ArrowInputError("Arrow block is not a record batch")
    batch = message.indirect(message.field(message.root, 2))
    if message.field(batch, 3) is not None:
        raise ArrowInputError("compressed IPC cannot supply qualified zero-copy numeric inputs")
    if message.field(batch, 4) is not None or message.field(message.root, 4) is not None:
        raise ArrowInputError("unsupported variable or custom batch metadata")
    length = message.field(batch, 0)
    body_length = message.field(message.root, 3)
    if (length is None or message.number("<q", length) != row_count or body_length is None
            or message.number("<q", body_length) != body_size or body_size != row_count * (32 + DIMENSION * 4)):
        raise ArrowInputError("Arrow batch row or numeric byte count differs from verified records")
    nodes, node_count = message.vector(batch, 1, 16)
    buffers, buffer_count = message.vector(batch, 2, 16)
    if node_count != 3 or buffer_count != 5:
        raise ArrowInputError("Arrow batch has unexpected array nodes or buffers")
    for index, length in enumerate((row_count, row_count, row_count * DIMENSION)):
        if message.number("<q", nodes + 16 * index) != length or message.number("<q", nodes + 16 * index + 8) != 0:
            raise ArrowInputError("Arrow array length or null count differs from the closed schema")
    for index, length in enumerate((0, row_count * 32, 0, 0, row_count * DIMENSION * 4)):
        start = message.number("<q", buffers + 16 * index)
        size = message.number("<q", buffers + 16 * index + 8)
        if size != length or not 0 <= start <= body_size - size:
            raise ArrowInputError("Arrow array buffer exceeds expected numeric shape")
        if (index == 1 and start != 0) or (index == 4 and start != row_count * 32):
            raise ArrowInputError("Arrow input buffers have unexpected padding or overlap")


class MappedEmbeddingVector(Sequence[float]):
    """Read-only scalar access over a verified mapped float32 row, without tuples."""

    __slots__ = ("_owner", "_array", "record_id", "__weakref__")

    def __init__(self, owner, array, record_id, *, _token=None):
        if _token is not _VIEW_TOKEN or type(owner) is not MappedEmbeddingInputs:
            raise TypeError("obtain mapped embedding vectors through MappedEmbeddingInputs.row")
        self._owner, self._array, self.record_id = owner, array, record_id
        owner._views.add(self)

    def __len__(self):
        self._owner._require_open()
        return len(self._array)

    def __getitem__(self, index):
        self._owner._require_open()
        if isinstance(index, slice):
            return MappedEmbeddingVector(self._owner, self._array[index], self.record_id, _token=_VIEW_TOKEN)
        value = self._array[operator.index(index)]
        self._owner._counters["scalar_accesses"] += 1
        return float(value)

    def __iter__(self) -> Iterator[float]:
        for index in range(len(self)):
            yield self[index]

    def __deepcopy__(self, memo: dict[int, Any]) -> list[float]:
        """Detach snapshot samples while their mapped owner is still open.

        Scalar access already produces immutable Python floats. Materialize
        before memoizing so a failed copy cannot leave a partial row in the
        caller's memo. The caller must serialize copying with owner closure;
        the returned list has no mapped lifetime dependency.
        """
        copied = list(self)
        self._owner._require_open()
        memo[id(self)] = copied
        return copied

    def readonly_array(self):
        self._owner._require_open()
        self._owner._counters["array_exports"] += 1
        return self._array.view()


class MappedEmbeddingInputs:
    """Owner of exact rows and their read-only mapped numeric buffer."""

    def __init__(self, mapping, file_buffer, reader, values, records, summary, path, fd, identity, *, _token=None):
        if _token is not _VIEW_TOKEN:
            raise TypeError("use load_embedding_inputs_ipc to construct verified mapped inputs")
        self._mapping, self._file_buffer, self._reader, self._values = mapping, file_buffer, reader, values
        self._path, self._fd, self._identity = path, fd, identity
        self.record_ids = tuple(record.record_id for record in records)
        self._index = {record_id: index for index, record_id in enumerate(self.record_ids)}
        self._summary = dict(summary)
        self._counters = {"row_accesses": 0, "scalar_accesses": 0, "array_exports": 0}
        self._views = weakref.WeakSet()
        self.closed = False

    def _require_open(self):
        if self.closed:
            raise ArrowInputError("mapped embedding inputs are closed")

    def row(self, record_id):
        self._require_open()
        index = self._index[record_id]
        self._counters["row_accesses"] += 1
        return MappedEmbeddingVector(self, self._values[index * DIMENSION:(index + 1) * DIMENSION],
                                     record_id, _token=_VIEW_TOKEN)

    def verification_summary(self):
        return dict(self._summary)

    def verify_unchanged(self):
        """Check the staged inode and bytes at a consumption boundary.

        This does not authenticate concurrent writers or promise detection of
        every transient change. The artifact must remain immutable during use.
        """
        self._require_open()
        try:
            before = os.fstat(self._fd)
            named = os.stat(self._path, follow_symlinks=False)
            if _stat_identity(before) != self._identity or _stat_identity(named) != self._identity:
                raise ArrowInputError("mapped Arrow artifact identity changed during use")
            digest = hashlib.sha256(memoryview(self._file_buffer)).hexdigest()
            if digest != self._summary["artifact_sha256"] or _stat_identity(os.fstat(self._fd)) != self._identity:
                raise ArrowInputError("mapped Arrow artifact bytes changed during use")
        except OSError as exc:
            raise ArrowInputError("mapped Arrow artifact is no longer available at its binding") from exc
        return {"artifact_sha256": digest, "artifact_bytes": self._summary["artifact_bytes"],
                "artifact_unchanged": True}

    @property
    def statistics(self):
        return {**self._summary, **self._counters, "closed": self.closed}

    def close(self):
        if not self.closed:
            self.closed = True
            os.close(self._fd)
            self._fd = None
            mapping = self._mapping
            for view in self._views:
                view._array = None
            self._views.clear()
            self._values = self._reader = self._file_buffer = self._mapping = None
            try:
                mapping.close()
            except BufferError:
                # Exported NumPy/Arrow views own the remaining mapping lifetime.
                pass

    def __enter__(self):
        self._require_open()
        return self

    def __exit__(self, *_):
        self.close()


def load_embedding_inputs_ipc(path, *, expected_sha256, expected_size_bytes, production, records, resolver):
    """Verify exact source/receipt bindings before exposing real mapped views."""
    import numpy as np
    import pyarrow as pa

    if sys.byteorder != "little":
        raise ArrowInputError("zero-copy float32 IPC inputs require a little-endian host")
    digest = _digest(expected_sha256, "expected_sha256")
    if type(expected_size_bytes) is not int or not 1 <= expected_size_bytes <= MAX_ARTIFACT_BYTES:
        raise ArrowInputError("Arrow artifact size exceeds its byte bound")
    checked, production = _verified_records(records, production, resolver)
    binding = _binding(checked, production)
    path = Path(path)
    if not path.is_absolute():
        raise ArrowInputError("Arrow artifact path must be absolute")
    mapping = file_buffer = reader = batch = values = None
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size != expected_size_bytes:
            raise ArrowInputError("Arrow artifact is not a regular file of its declared size")
        identity = _stat_identity(info)
        mapping = mmap.mmap(fd, expected_size_bytes, access=mmap.ACCESS_READ)
        file_buffer = pa.py_buffer(mapping)
        if hashlib.sha256(memoryview(file_buffer)).hexdigest() != digest:
            raise ArrowInputError("Arrow artifact SHA-256 mismatch")
        _preflight(file_buffer, len(checked))
        reader = pa.ipc.open_file(pa.BufferReader(file_buffer))
        if reader.num_record_batches != 1 or not reader.schema.equals(_schema(pa, binding), check_metadata=True):
            raise ArrowInputError("Arrow schema or ordered producer binding mismatch")
        batch = reader.get_batch(0)
        batch.validate(full=True)
        if batch.num_rows != len(checked) or batch.num_columns != 2:
            raise ArrowInputError("Arrow record count differs from exact source membership")
        identifiers, vectors = batch.column(0), batch.column(1)
        if identifiers.null_count or vectors.null_count or vectors.values.null_count:
            raise ArrowInputError("null record identities, vectors or scalars are forbidden")
        if identifiers.to_pylist() != [bytes.fromhex(item.record_id.removeprefix("sha256:")) for item in checked]:
            raise ArrowInputError("Arrow record membership or order differs from verified records")
        values = vectors.values.to_numpy(zero_copy_only=True)
        address = values.__array_interface__["data"][0]
        if (values.dtype != np.dtype("float32") or values.shape != (len(checked) * DIMENSION,)
                or not values.flags.c_contiguous or values.flags.writeable
                or not file_buffer.address <= address <= file_buffer.address + file_buffer.size - values.nbytes):
            raise ArrowInputError("Arrow numeric data is not a read-only zero-copy mapped buffer")
        for index, item in enumerate(checked):
            actual = memoryview(values[index * DIMENSION:(index + 1) * DIMENSION]).cast("B")
            if actual != _record_bits(item):
                raise ArrowInputError("Arrow float32 bits differ from the exact producer record")
        if hashlib.sha256(memoryview(file_buffer)).hexdigest() != digest:
            raise ArrowInputError("Arrow artifact changed during verification")
        summary = {**binding, "artifact_sha256": digest, "artifact_bytes": expected_size_bytes,
                   "mapped_numeric_bytes": values.nbytes, "zero_copy_numeric_buffers_verified": True,
                   "read_only": True, "whole_training_zero_copy": False}
        owner = MappedEmbeddingInputs(mapping, file_buffer, reader, values, checked, summary,
                                      path, fd, identity, _token=_VIEW_TOKEN)
        owner.verify_unchanged()
        return owner
    except BaseException as exc:
        if fd is not None:
            os.close(fd)
        values = batch = reader = file_buffer = None
        if mapping is not None:
            try:
                mapping.close()
            except BufferError:
                pass
        if isinstance(exc, (OSError, pa.ArrowException)):
            raise ArrowInputError("Arrow input artifact could not be mapped or decoded") from exc
        raise
