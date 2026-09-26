"""Private, lossless Arrow materialization of legacy feature embedding rows.

Only ``feature_embedding_weights`` is covered. Original keys are retained, so
this codec is not the typed-key model format or a public-export qualification.
Uncompressed IPC numeric buffers are mapped read-only; touched rows use the
existing tracked Python list implementation. Source JSON parsing, key decoding,
identity hashing and checkpoint serialization are not zero-copy operations.
"""

from __future__ import annotations

import copy
import hashlib
import math
import mmap
import os
import re
import stat
import struct
import tempfile
from collections.abc import Iterable, Iterator, Mapping, MutableMapping, MutableSequence
from pathlib import Path
from typing import Any, Callable


ARROW_FEATURE_WEIGHTS_SCHEMA_VERSION = "modal-autoencoder-legacy-feature-weights-arrow-v1"
COMPONENT = "feature_embedding_weights"
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class ArrowWeightError(ValueError):
    """An artifact, source binding or mapped view failed qualification."""


def _stat_identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


class _FlatBuffer:
    """Bounded Arrow File/Message metadata access before batch decoding.

    Field slots follow Arrow format/File.fbs and format/Message.fbs. Only the
    existing string + list<float64> file layout is accepted below.
    """

    def __init__(self, raw):
        self.raw = raw

    def number(self, fmt, offset):
        size = struct.calcsize(fmt)
        if not 0 <= offset <= len(self.raw) - size:
            raise ArrowWeightError("Arrow metadata offset exceeds its byte bounds")
        return struct.unpack_from(fmt, self.raw, offset)[0]

    def field(self, table, slot):
        vtable = table - self.number("<i", table)
        length, size = self.number("<H", vtable), self.number("<H", vtable + 2)
        if length < 4 or vtable + length > len(self.raw) or size < 4 or table + size > len(self.raw):
            raise ArrowWeightError("invalid Arrow metadata table")
        if 4 + slot * 2 >= length:
            return None
        relative = self.number("<H", vtable + 4 + slot * 2)
        if relative == 0:
            return None
        if not 4 <= relative < size:
            raise ArrowWeightError("invalid Arrow metadata field")
        return table + relative

    def indirect(self, position):
        if position is None:
            raise ArrowWeightError("required Arrow metadata field is absent")
        target = position + self.number("<I", position)
        if not 0 <= target < len(self.raw):
            raise ArrowWeightError("invalid Arrow metadata indirection")
        return target

    def vector(self, table, slot, stride):
        position = self.field(table, slot)
        if position is None:
            return 0, 0
        vector = self.indirect(position)
        count = self.number("<I", vector)
        if count > (len(self.raw) - vector - 4) // stride:
            raise ArrowWeightError("Arrow metadata vector exceeds byte bounds")
        return vector + 4, count

    @property
    def root(self):
        return self.number("<I", 0)


def _preflight(file_buffer):
    """Bound every batch before Arrow can allocate/decompress its contents."""
    raw = memoryview(file_buffer).cast("B")
    if len(raw) < 18 or raw[:8] != b"ARROW1\x00\x00" or raw[-6:] != b"ARROW1":
        raise ArrowWeightError("not a qualified Arrow IPC file")
    footer_size = struct.unpack_from("<I", raw, len(raw) - 10)[0]
    footer_start = len(raw) - 10 - footer_size
    if not 8 <= footer_start < len(raw) - 10:
        raise ArrowWeightError("invalid Arrow footer length")
    footer = _FlatBuffer(raw[footer_start:len(raw) - 10])
    _, dictionaries = footer.vector(footer.root, 2, 24)
    blocks, count = footer.vector(footer.root, 3, 24)
    if dictionaries:
        raise ArrowWeightError("dictionary batches are outside the feature-weight schema")
    total_rows = total_scalars = 0
    previous_end = 8
    for index in range(count):
        block = blocks + index * 24
        offset = footer.number("<q", block)
        metadata_size = footer.number("<i", block + 8)
        body_size = footer.number("<q", block + 16)
        if (offset < previous_end or offset % 8 or metadata_size < 8 or metadata_size % 8
                or body_size < 0 or offset + metadata_size + body_size > footer_start):
            raise ArrowWeightError("Arrow record batch extents exceed file bounds")
        previous_end = offset + metadata_size + body_size
        if (raw[offset:offset + 4] != b"\xff\xff\xff\xff"
                or struct.unpack_from("<I", raw, offset + 4)[0] != metadata_size - 8):
            raise ArrowWeightError("unsupported Arrow record batch framing")
        message = _FlatBuffer(raw[offset + 8:offset + metadata_size])
        header = message.field(message.root, 1)
        if header is None or message.number("<B", header) != 3:
            raise ArrowWeightError("Arrow block is not a record batch")
        batch = message.indirect(message.field(message.root, 2))
        if message.field(batch, 3) is not None:
            raise ArrowWeightError("compressed IPC is not a mapped file buffer")
        if message.field(batch, 4) is not None:
            raise ArrowWeightError("variadic buffers are outside the feature-weight schema")
        length = message.field(batch, 0)
        body = message.field(message.root, 3)
        rows = 0 if length is None else message.number("<q", length)
        actual_body = 0 if body is None else message.number("<q", body)
        if rows < 0 or rows > body_size // 8 or actual_body != body_size:
            raise ArrowWeightError("Arrow batch length exceeds its physical byte bounds")
        nodes, node_count = message.vector(batch, 1, 16)
        buffers, buffer_count = message.vector(batch, 2, 16)
        if node_count != 3 or buffer_count != 7:
            raise ArrowWeightError("Arrow batch has unexpected array nodes or buffers")
        scalars = message.number("<q", nodes + 32)
        if not 0 <= scalars <= body_size // 8:
            raise ArrowWeightError("Arrow scalar count exceeds its physical byte bounds")
        for position, expected in enumerate((rows, rows, scalars)):
            if (message.number("<q", nodes + 16 * position) != expected
                    or message.number("<q", nodes + 16 * position + 8) != 0):
                raise ArrowWeightError("Arrow array lengths or null counts differ from schema")
        previous_buffer_end = 0
        for position in range(buffer_count):
            start = message.number("<q", buffers + 16 * position)
            size = message.number("<q", buffers + 16 * position + 8)
            if not 0 <= size <= body_size or not previous_buffer_end <= start <= body_size - size:
                raise ArrowWeightError("Arrow array buffers overlap or exceed batch bytes")
            previous_buffer_end = start + size
            expected = {1: (rows + 1) * 4, 4: (rows + 1) * 4, 6: scalars * 8}.get(position)
            if expected is not None and size != expected:
                raise ArrowWeightError("Arrow array buffer size differs from its declared length")
        total_rows += rows
        total_scalars += scalars
    if total_rows > len(raw) // 8 or total_scalars > len(raw) // 8:
        raise ArrowWeightError("Arrow total counts exceed physical file bounds")
    return count, total_rows, total_scalars


def _sha256(value: str, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ArrowWeightError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _source_rows(source: Any) -> dict[str, Any]:
    mapping = getattr(source, COMPONENT, source)
    if not isinstance(mapping, Mapping):
        raise ArrowWeightError("feature embedding rows must be a mapping")
    # Match the legacy loader's str(key) normalization, collision behavior and
    # insertion order without retaining a second graph of numeric values.
    return {str(key): value for key, value in mapping.items()}


def _numbers(value: Iterable[Any]) -> list[float]:
    result = [float(number) for number in value]
    if not all(math.isfinite(number) for number in result):
        raise ArrowWeightError("feature embedding rows must contain finite numbers")
    return result


def _schema(pa: Any, *, base_sha256: str, row_count: int, scalar_count: int) -> Any:
    return pa.schema([
        pa.field("key", pa.string(), nullable=False),
        pa.field("values", pa.list_(pa.float64()), nullable=False),
    ], metadata={
        b"schema_version": ARROW_FEATURE_WEIGHTS_SCHEMA_VERSION.encode(),
        b"component": COMPONENT.encode(),
        b"base_checkpoint_sha256": base_sha256.encode(),
        b"row_count": str(row_count).encode(),
        b"scalar_count": str(scalar_count).encode(),
        b"normalization": b"legacy-str-key-float64-v1",
    })


def build_feature_embedding_weights_ipc(
    source: Any,
    destination: str | os.PathLike[str],
    *,
    base_checkpoint_sha256: str,
    batch_rows: int = 4096,
) -> dict[str, Any]:
    """Seal deterministic IPC bytes without replacing an existing artifact.

    The caller supplies an independently verified base checkpoint identity.
    Loading also verifies that identity; ``verify_source_rows`` reconciles the
    mapped component to the actual parsed checkpoint before state construction.
    """

    import pyarrow as pa

    base_sha = _sha256(base_checkpoint_sha256, "base_checkpoint_sha256")
    if isinstance(batch_rows, bool) or not isinstance(batch_rows, int) or batch_rows < 1:
        raise ArrowWeightError("batch_rows must be a positive integer")
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    rows = _source_rows(source)
    scalar_count = sum(len(row) for row in rows.values())
    schema = _schema(pa, base_sha256=base_sha, row_count=len(rows), scalar_count=scalar_count)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b", prefix=f".{destination.name}.", dir=destination.parent, delete=False,
        ) as handle:
            temporary = handle.name
            with pa.ipc.new_file(handle, schema, options=pa.ipc.IpcWriteOptions(compression=None)) as writer:
                keys: list[str] = []
                values: list[list[float]] = []
                for key, row in rows.items():
                    keys.append(key)
                    values.append(_numbers(row))
                    if len(keys) == batch_rows:
                        writer.write_batch(pa.record_batch([
                            pa.array(keys, type=pa.string()),
                            pa.array(values, type=pa.list_(pa.float64())),
                        ], schema=schema))
                        keys, values = [], []
                if keys:
                    writer.write_batch(pa.record_batch([
                        pa.array(keys, type=pa.string()),
                        pa.array(values, type=pa.list_(pa.float64())),
                    ], schema=schema))
            handle.flush()
            os.fsync(handle.fileno())
        digest = hashlib.sha256()
        with open(temporary, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        size_bytes = os.stat(temporary).st_size
        os.link(temporary, destination)  # exclusive publication, no source hardlink
        directory_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return {
            "schema_version": ARROW_FEATURE_WEIGHTS_SCHEMA_VERSION,
            "component": COMPONENT,
            "sha256": digest.hexdigest(),
            "size_bytes": size_bytes,
            "base_checkpoint_sha256": base_sha,
            "row_count": len(rows),
            "scalar_count": scalar_count,
        }
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


class _MappedBase:
    def __init__(self, mapped: Any, file_buffer: Any, reader: Any, descriptor: dict[str, Any],
                 *, path: Path, fd: int, identity: tuple[int, ...]) -> None:
        import numpy as np

        self.mapped, self.file_buffer, self.reader = mapped, file_buffer, reader
        self.path, self.fd, self.identity = path, fd, identity
        self.descriptor = descriptor
        self.closed = False
        self.keys: list[str] = []
        self.index: dict[str, tuple[int, int]] = {}
        self.values: list[Any] = []
        self.offsets: list[Any] = []
        scalar_count = 0
        for batch_index in range(reader.num_record_batches):
            batch = reader.get_batch(batch_index)
            batch.validate(full=True)
            keys, rows = batch.column(0), batch.column(1)
            if keys.null_count or rows.null_count or rows.values.null_count:
                raise ArrowWeightError("null keys, rows or scalar values are unsupported")
            values = rows.values.to_numpy(zero_copy_only=True)
            offsets = rows.offsets.to_numpy(zero_copy_only=True)
            for array in (values, offsets):
                if array.size:
                    address = array.__array_interface__["data"][0]
                    if not (file_buffer.address <= address and address + array.nbytes <= file_buffer.address + file_buffer.size):
                        raise ArrowWeightError("IPC numeric data is not a mapped file buffer")
                array.setflags(write=False)
            if not np.isfinite(values).all():
                raise ArrowWeightError("feature embedding rows contain non-finite numbers")
            if offsets[0] != 0 or offsets[-1] != len(values) or np.any(offsets[1:] < offsets[:-1]):
                raise ArrowWeightError("invalid ragged row offsets")
            self.values.append(values)
            self.offsets.append(offsets)
            scalar_count += len(values)
            for row_index, key in enumerate(keys.to_pylist()):
                if key in self.index:
                    raise ArrowWeightError("duplicate feature key in Arrow artifact")
                self.keys.append(key)
                self.index[key] = batch_index, row_index
        if len(self.keys) != descriptor["row_count"] or scalar_count != descriptor["scalar_count"]:
            raise ArrowWeightError("Arrow row/scalar count does not match metadata")
        self.numeric_bytes = sum(array.nbytes for array in self.values)
        self.offset_bytes = sum(array.nbytes for array in self.offsets)

    def require_open(self) -> None:
        if self.closed:
            raise ArrowWeightError("mapped feature weights are closed")

    def row(self, key: str) -> Any:
        self.require_open()
        batch, row = self.index[key]
        start, end = self.offsets[batch][row:row + 2]
        return self.values[batch][int(start):int(end)]

    def verify_unchanged(self) -> dict[str, Any]:
        self.require_open()
        try:
            if (self.path.resolve() != self.path
                    or _stat_identity(os.fstat(self.fd)) != self.identity
                    or _stat_identity(self.path.stat(follow_symlinks=False)) != self.identity):
                raise ArrowWeightError("mapped feature artifact identity changed during use")
            digest = hashlib.sha256(memoryview(self.file_buffer)).hexdigest()
            if (digest != self.descriptor["sha256"]
                    or _stat_identity(os.fstat(self.fd)) != self.identity
                    or _stat_identity(self.path.stat(follow_symlinks=False)) != self.identity
                    or self.path.resolve() != self.path):
                raise ArrowWeightError("mapped feature artifact bytes or pathname changed during use")
        except OSError as exc:
            raise ArrowWeightError("mapped feature artifact is no longer available at its binding") from exc
        return {"artifact_sha256": digest, "artifact_bytes": self.descriptor["size_bytes"],
                "artifact_unchanged": True}

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            mapped, fd = self.mapped, self.fd
            self.fd = None
            self.values.clear()
            self.offsets.clear()
            self.reader = self.file_buffer = self.mapped = None
            try:
                os.close(fd)
            finally:
                try:
                    mapped.close()
                except BufferError:
                    # Exported read-only arrays retain their own buffer owner.
                    pass


class _MappedVector(MutableSequence[float]):
    """Read mapped scalars; delegate mutations to the established tracked list."""

    def __init__(self, owner: "MappedFeatureEmbeddingWeights", key: str, overlay: Any = None) -> None:
        self.owner, self.key, self.overlay = owner, key, overlay

    def _values(self) -> Any:
        self.owner._base.require_open()
        return self.overlay if self.overlay is not None else self.owner._base.row(self.key)

    def _mutable(self) -> Any:
        from .modal_autoencoder_state_version import _TrackedList

        self.owner._base.require_open()
        if self.overlay is None:
            values = list(self)
            self.owner._counters["row_materializations"] += 1
            self.overlay = _TrackedList(
                values, self.owner._callback, self.owner._before, (*self.owner._path, self.key),
            )
        return self.overlay

    def __len__(self) -> int:
        return len(self._values())

    def __getitem__(self, index: Any) -> Any:
        values = self._values()
        if self.overlay is not None:
            return values[index]
        if isinstance(index, slice):
            self.owner._counters["row_materializations"] += 1
            return [float(value) for value in values[index]]
        return float(values[index])

    def __iter__(self) -> Iterator[float]:
        values = self._values()
        return iter(values) if self.overlay is not None else (float(value) for value in values)

    def __setitem__(self, index: Any, value: Any) -> None:
        self._mutable()[index] = value

    def __delitem__(self, index: Any) -> None:
        del self._mutable()[index]

    def insert(self, index: int, value: float) -> None:
        self._mutable().insert(index, value)

    def append(self, value: float) -> None:
        self._mutable().append(value)

    def extend(self, values: Iterable[float]) -> None:
        self._mutable().extend(values)

    def pop(self, index: int = -1) -> Any:
        return self._mutable().pop(index)

    def remove(self, value: float) -> None:
        self._mutable().remove(value)

    def clear(self) -> None:
        self._mutable().clear()

    def reverse(self) -> None:
        self._mutable().reverse()

    def sort(self, *args: Any, **kwargs: Any) -> None:
        self._mutable().sort(*args, **kwargs)

    def __iadd__(self, values: Iterable[float]) -> "_MappedVector":
        self._mutable().__iadd__(values)
        return self

    def __imul__(self, count: int) -> "_MappedVector":
        self._mutable().__imul__(count)
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> list[float]:
        self.owner._counters["row_materializations"] += 1
        return [copy.deepcopy(value, memo) for value in self]

    def __eq__(self, other: object) -> bool:
        try:
            return list(self) == list(other)  # type: ignore[arg-type]
        except TypeError:
            return False

    def __repr__(self) -> str:
        return repr(list(self))


class MappedFeatureEmbeddingWeights(MutableMapping[str, Any]):
    """An ordered legacy map with a shared immutable base and private rows.

    Install through normal state construction/tracking. Binding creates an
    independent overlay; ``close`` closes the common source mapping and must
    therefore run only after all associated state objects finish using it.
    """

    def __init__(self, base: _MappedBase) -> None:
        if type(base) is not _MappedBase:
            raise TypeError("use load_feature_embedding_weights_ipc to verify a base")
        self._base = base
        self._rows: dict[str, _MappedVector] = {}
        self._hidden_base: set[str] = set()
        self._appended: dict[str, None] = {}
        self._callback: Callable[[], None] = lambda: None
        self._before: Callable[[tuple[Any, ...], str], None] = lambda _path, _operation: None
        self._path: tuple[Any, ...] = ()
        self._counters = {"mapped_row_reads": 0, "row_materializations": 0}

    def _bind_tracking(self, callback: Any, before: Any, path: tuple[Any, ...]) -> "MappedFeatureEmbeddingWeights":
        self._base.require_open()
        bound = type(self)(self._base)
        bound._callback, bound._before, bound._path = callback, before, path
        bound._hidden_base = set(self._hidden_base)
        bound._appended = dict(self._appended)
        for key, row in self._rows.items():
            if row.overlay is not None:
                bound._assign(key, list(row))
        return bound

    def __getitem__(self, key: str) -> _MappedVector:
        if key not in self:
            raise KeyError(key)
        row = self._rows.get(key)
        if row is None:
            row = self._rows[key] = _MappedVector(self, key)
        if row.overlay is None:
            self._counters["mapped_row_reads"] += 1
        return row

    def __contains__(self, key: object) -> bool:
        self._base.require_open()
        return isinstance(key, str) and (
            key in self._appended or (key in self._base.index and key not in self._hidden_base)
        )

    def __iter__(self) -> Iterator[str]:
        self._base.require_open()
        return iter([key for key in self._base.keys if key not in self._hidden_base] + list(self._appended))

    def __len__(self) -> int:
        self._base.require_open()
        return len(self._base.keys) - len(self._hidden_base) + len(self._appended)

    def _assign(self, key: str, value: Any) -> None:
        from .modal_autoencoder_state_version import _TrackedList
        import numpy as np

        if not isinstance(key, str):
            raise TypeError("legacy feature keys must be strings")
        values = _TrackedList(value, self._callback, self._before, (*self._path, key))
        if key not in self:
            self._appended[key] = None
        # Rollback writes ordinary before-images. Reuse unchanged mapped bytes
        # when every Python scalar type and bit matches the original float row;
        # integer/bool writes must retain their legacy tracked-list semantics.
        if key in self._base.index and all(type(number) is float for number in values):
            original = self._base.row(key)
            if len(values) == len(original) and np.asarray(values, dtype=np.float64).tobytes() == original.tobytes():
                self._rows[key] = _MappedVector(self, key)
                return
        self._rows[key] = _MappedVector(self, key, values)

    def __setitem__(self, key: str, value: Any) -> None:
        self._before((*self._path, key), "set")
        self._assign(key, value)
        self._callback()

    def _delete(self, key: str) -> None:
        if key not in self:
            raise KeyError(key)
        if key in self._base.index:
            self._hidden_base.add(key)
        self._appended.pop(key, None)
        self._rows.pop(key, None)

    def __delitem__(self, key: str) -> None:
        self._before((*self._path, key), "delete")
        self._delete(key)
        self._callback()

    def setdefault(self, key: str, default: Any = None) -> Any:
        if key in self:
            return self[key]
        self._before((*self._path, key), "insert")
        self._assign(key, default)
        self._callback()
        return self[key]

    def update(self, *args: Any, **kwargs: Any) -> None:
        incoming = dict(*args, **kwargs)
        if not incoming:
            return
        for key, value in incoming.items():
            self._before((*self._path, key), "set")
            self._assign(key, value)
        self._callback()

    def clear(self) -> None:
        if self:
            for key in tuple(self):
                self._before((*self._path, key), "delete")
                self._delete(key)
            self._callback()

    def popitem(self) -> tuple[str, Any]:
        if not self:
            raise KeyError("popitem(): dictionary is empty")
        key = next(reversed(list(self)))
        value = self[key]
        del self[key]
        return key, value

    def __ior__(self, other: Mapping[str, Any]) -> "MappedFeatureEmbeddingWeights":
        self.update(other)
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> dict[str, Any]:
        return {copy.deepcopy(key, memo): copy.deepcopy(self[key], memo) for key in self}

    def readonly_row_array(self, key: str, *, zero_copy_only: bool = True) -> Any:
        """Return a read-only numeric view; private Python rows require a copy."""

        import numpy as np

        if key not in self:
            raise KeyError(key)
        row = self._rows.get(key)
        if row is None or row.overlay is None:
            return self._base.row(key)
        if zero_copy_only:
            raise ArrowWeightError("a private Python overlay row requires materialization")
        self._counters["row_materializations"] += 1
        result = np.asarray(row.overlay, dtype=np.float64)
        result.setflags(write=False)
        return result

    def verify_source_rows(self, original_mapping: Mapping[Any, Any]) -> None:
        """Check exact normalized key order and float64 bits against the base."""

        import numpy as np

        rows = _source_rows(original_mapping)
        if list(rows) != list(self):
            raise ArrowWeightError("source feature key membership/order mismatch")
        for key, row in rows.items():
            current = self._rows.get(key)
            if current is not None and current.overlay is not None and any(
                type(value) is not float for value in current.overlay
            ):
                # from_dict normalizes every source scalar to a Python float.
                # Equal numeric bits alone cannot justify preserving an int or
                # bool written into an unbound overlay before construction.
                raise ArrowWeightError("source feature overlay is not float-normalized")
            expected = np.asarray(_numbers(row), dtype=np.float64)
            actual = self.readonly_row_array(key, zero_copy_only=False)
            if actual.shape != expected.shape or actual.tobytes() != expected.tobytes():
                raise ArrowWeightError("source feature row values mismatch")

    @property
    def statistics(self) -> dict[str, Any]:
        overlay_rows = [row for row in self._rows.values() if row.overlay is not None]
        return {
            "component": COMPONENT,
            "base_rows": len(self._base.keys),
            "scalar_count": self._base.descriptor["scalar_count"],
            "mapped_numeric_bytes": self._base.numeric_bytes,
            "mapped_offset_bytes": self._base.offset_bytes,
            "overlay_rows": len(overlay_rows),
            "private_numeric_payload_bytes": sum(len(row.overlay) * 8 for row in overlay_rows),
            "private_bytes_excludes_python_overhead": True,
            "closed": self._base.closed,
            **self._counters,
        }

    def close(self) -> None:
        self._base.close()

    def verify_unchanged(self) -> dict[str, Any]:
        """Recheck the immutable staged file without inspecting private overlays.

        Detects persistent byte changes and pathname replacement. The caller
        must keep the file immutable and serialize use with close; this is not
        synchronization against concurrent writers or transient mutate/revert.
        """
        return self._base.verify_unchanged()


def load_feature_embedding_weights_ipc(
    path: str | os.PathLike[str],
    *,
    expected_sha256: str,
    expected_size_bytes: int,
    expected_base_checkpoint_sha256: str,
) -> MappedFeatureEmbeddingWeights:
    """Verify bounded immutable bytes, path identity and actual mapped buffers.

    Relative paths are captured as absolute paths; symlink aliases are rejected.
    The 512 MiB artifact limit bounds bytes, not total Python/Arrow memory use.
    """

    import pyarrow as pa

    digest = _sha256(expected_sha256, "expected_sha256")
    base_sha = _sha256(expected_base_checkpoint_sha256, "expected_base_checkpoint_sha256")
    if type(expected_size_bytes) is not int or not 1 <= expected_size_bytes <= MAX_ARTIFACT_BYTES:
        raise ArrowWeightError("expected_size_bytes exceeds the Arrow artifact byte bound")
    path = Path(path).absolute()
    mapped = file_buffer = reader = owner = None
    fd = None
    try:
        if path.resolve() != path:
            raise ArrowWeightError("Arrow artifact path must not contain symlink aliases")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size != expected_size_bytes:
            raise ArrowWeightError("Arrow artifact must be a regular file of its declared size")
        identity = _stat_identity(info)
        mapped = mmap.mmap(fd, expected_size_bytes, access=mmap.ACCESS_READ)
        file_buffer = pa.py_buffer(mapped)
        if hashlib.sha256(memoryview(file_buffer)).hexdigest() != digest:
            raise ArrowWeightError("Arrow artifact SHA-256 mismatch")
        batch_count, physical_rows, physical_scalars = _preflight(file_buffer)
        reader = pa.ipc.open_file(pa.BufferReader(file_buffer))
        metadata = reader.schema.metadata or {}
        expected_metadata = {
            b"schema_version": ARROW_FEATURE_WEIGHTS_SCHEMA_VERSION.encode(),
            b"component": COMPONENT.encode(),
            b"base_checkpoint_sha256": base_sha.encode(),
            b"normalization": b"legacy-str-key-float64-v1",
        }
        if any(metadata.get(key) != value for key, value in expected_metadata.items()):
            raise ArrowWeightError("Arrow schema or base checkpoint binding mismatch")
        try:
            row_count = int(metadata[b"row_count"])
            scalar_count = int(metadata[b"scalar_count"])
        except (KeyError, ValueError) as exc:
            raise ArrowWeightError("Arrow artifact is missing valid counts") from exc
        if (row_count != physical_rows or scalar_count != physical_scalars
                or reader.num_record_batches != batch_count):
            raise ArrowWeightError("Arrow counts differ from bounded batch metadata")
        expected_schema = _schema(pa, base_sha256=base_sha, row_count=row_count, scalar_count=scalar_count)
        if not reader.schema.equals(expected_schema, check_metadata=True):
            raise ArrowWeightError("Arrow feature-weight schema mismatch")
        descriptor = {
            "sha256": digest, "size_bytes": expected_size_bytes,
            "base_checkpoint_sha256": base_sha, "row_count": row_count, "scalar_count": scalar_count,
        }
        owner = _MappedBase(mapped, file_buffer, reader, descriptor,
                            path=path, fd=fd, identity=identity)
        owner.verify_unchanged()
        return MappedFeatureEmbeddingWeights(owner)
    except BaseException as exc:
        if owner is not None:
            try:
                owner.close()
            except BaseException as cleanup:
                exc.add_note(f"mapped feature cleanup also failed: {type(cleanup).__name__}")
        else:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError as cleanup:
                    exc.add_note(f"mapped feature fd cleanup also failed: {type(cleanup).__name__}")
            reader = file_buffer = None
            if mapped is not None:
                try:
                    mapped.close()
                except BufferError:
                    pass
        if isinstance(exc, (OSError, pa.ArrowException)):
            raise ArrowWeightError("Arrow feature artifact could not be mapped or decoded") from exc
        raise
