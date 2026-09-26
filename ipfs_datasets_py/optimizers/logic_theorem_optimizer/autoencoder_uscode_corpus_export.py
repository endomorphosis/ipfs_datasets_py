"""Portable, bounded Parquet catalog of every declared physical U.S. Code row.

Source files and provenance retain their exact bytes. Generated rows are a
queryable projection, not a replacement for raw sources or a legal admit.
Output is exclusive and manifest-last; failed partial directories are retained.
Verification rebuilds the complete expected row stream from package-local
artifacts. There is no network, model, registry mutation or publication here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from functools import wraps
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

from ...huggingface.autoencoder_campaign_release import (
    _current_file, _directory, _directory_at, _identity, _new_root,
    _regular, _root_current,
)
from .autoencoder_uscode_corpus_rows import (
    USCodeCorpusRows, ROW_FIELDS, ROW_TYPES, NULLABLE_FIELDS,
)

SCHEMA_VERSION = "autoencoder-uscode-source-export-v1"
REPORT_SCHEMA_VERSION = "autoencoder-uscode-source-export-report-v1"
MANIFEST_NAME = "source-export.json"
SCOPE = "declared_corpus_family_only"
_CHUNK = 1024 * 1024
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_MANIFEST_FIELDS = frozenset({"schema_version", "scope", "metadata", "coverage",
    "limits", "files", "row_schema", "writer", "qualification"})
_FILE_FIELDS = frozenset({"relative_path", "sha256", "bytes", "kind", "row_count"})
_QUALIFICATION = {
    "admitted": False, "formalized": False, "source_authority_authenticated": False,
    "original_official_source_bytes_verified": False, "full_federal_corpus_complete": False,
    "global_holdout_verified": False, "training_eligible": False,
    "training_dispatched": False, "publication_performed": False,
}
_README = b'''---
configs:
- config_name: corpus
  data_files:
  - split: corpus
    path: data/source_rows/*.parquet
---
# U.S. Code physical source-row catalog

This offline package contains every physical row of the declared corpus family
in its pinned release. It is not a complete federal-law or Constitution dataset.
The `corpus` configuration exposes queryable text and the full verified record
JSON, including exclusions and aliases. Original source Parquet files under
`source/corpus/` retain raw bytes, including invalid wrappers that cannot supply
verified text. Provenance files retain the exact inventory, release manifest,
optional split and embedding-receipt roots, leaf receipts and producer inputs.

The `split` column preserves frozen source membership; null means unavailable.
The physical Hugging Face split `corpus` is cataloguing, not training permission.
`source_eligible` and embedding dispositions describe existing input contracts,
not legal success. Any published admission status inside `record_json` is only
a historical retrieval claim. No row is certified formalized or admitted here.
Only the existing Lake proof gate can establish a Lean admit. The Constitution
is not formalized. This package does not upload or publish anything.

Verify `source-export.json` against an independently supplied SHA-256 using
`verify_uscode_source_export`. It verifies original bytes and regenerates every
queryable row, without opening historical paths or loading model weights.
'''


class CorpusExportError(ValueError):
    """Incomplete, changed, unsafe or over-budget source export."""


@dataclass(frozen=True)
class CorpusExportLimits:
    """Only tighter limits than these format ceilings are accepted."""
    max_rows: int = 65536
    max_files: int = 4096
    max_file_bytes: int = 256 * 1024**2
    max_total_bytes: int = 512 * 1024**2
    max_manifest_bytes: int = 4 * 1024**2
    max_batch_bytes: int = 16 * 1024**2
    max_rows_per_file: int = 4096
    max_row_group_bytes: int = 32 * 1024**2
    max_parquet_uncompressed_bytes: int = 256 * 1024**2
    max_directories: int = 1024
    max_namespace_entries: int = 8192
    max_path_bytes: int = 512
    max_path_depth: int = 8

    def __post_init__(self):
        for item in fields(self):
            value = getattr(self, item.name)
            if type(value) is not int or not 1 <= value <= item.default:
                raise CorpusExportError("invalid export limit: " + item.name)


def _require(condition, message):
    if not condition:
        raise CorpusExportError(message)


def _errors(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except CorpusExportError:
            raise
        except (ValueError, TypeError, KeyError, AttributeError, OSError,
                OverflowError, RecursionError) as exc:
            raise CorpusExportError("source export validation failed: " + str(exc)) from exc
    return guarded


def _limits(value):
    _require(type(value) is CorpusExportLimits, "actual export limits required")
    return CorpusExportLimits(**asdict(value))


def _canonical(value, maximum=4 * 1024**2):
    chunks, size = [], 0
    for chunk in json.JSONEncoder(sort_keys=True, separators=(",", ":"),
                                  ensure_ascii=False, allow_nan=False).iterencode(value):
        raw = chunk.encode("utf-8")
        size += len(raw)
        _require(size <= maximum, "canonical JSON exceeds byte bound")
        chunks.append(raw)
    return b"".join(chunks)


def _parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate JSON field")
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(CorpusExportError("nonfinite JSON")))
    _require(_canonical(value, len(raw)) == raw, "noncanonical manifest")
    return value


def _digest(value):
    _require(type(value) is str and _HASH.fullmatch(value), "invalid digest")
    return value


def _path(value):
    path = Path(value)
    _require(path.is_absolute() and str(path) == os.path.abspath(path)
             and ".." not in path.parts, "absolute normalized local path required")
    return path


def _relative(value, limits):
    _require(type(value) is str and value and "\\" not in value
             and len(value.encode("utf-8")) <= limits.max_path_bytes,
             "invalid package relative path")
    path = PurePosixPath(value)
    _require(not path.is_absolute() and path.as_posix() == value
             and all(part not in {"", ".", ".."} for part in value.split("/"))
             and len(path.parts) <= limits.max_path_depth,
             "unsafe or over-bound package path")
    return value


def _ref(value, limits):
    _require(type(value) is dict and set(value) == {"sha256", "bytes"}, "invalid artifact reference")
    _digest(value["sha256"])
    _require(type(value["bytes"]) is int and 0 < value["bytes"] <= limits.max_file_bytes,
             "artifact byte bound exceeded")
    return value


def _read(path, maximum):
    with os.fdopen(_regular(path), "rb") as stream:
        before = os.fstat(stream.fileno())
        _require(0 < before.st_size <= maximum, "file byte bound exceeded")
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
        _require(len(raw) == before.st_size and _identity(before) == _identity(after), "file changed while reading")
    _current_file(path, after)
    return raw


def _hash(path, expected=None, *, maximum):
    with os.fdopen(_regular(path), "rb") as stream:
        before = os.fstat(stream.fileno())
        _require(0 < before.st_size <= maximum, "file byte bound exceeded")
        if expected is not None:
            _require(before.st_size == expected["bytes"], "artifact size mismatch")
        digest, size = hashlib.sha256(), 0
        while chunk := stream.read(min(_CHUNK, maximum - size + 1)):
            size += len(chunk)
            _require(size <= maximum, "file grew beyond byte bound")
            digest.update(chunk)
        after = os.fstat(stream.fileno())
        _require(size == before.st_size and _identity(before) == _identity(after), "artifact changed while hashing")
    _current_file(path, after)
    result = {"sha256": digest.hexdigest(), "bytes": size}
    _require(expected is None or result == expected, "artifact digest mismatch")
    return result


def _row_schema():
    return [{"name": name, "type": ROW_TYPES[name], "nullable": name in NULLABLE_FIELDS}
            for name in ROW_FIELDS]


def _arrow_schema():
    import pyarrow as pa
    types = {"string": pa.string(), "int64": pa.int64(), "bool": pa.bool_()}
    return pa.schema([pa.field(name, types[ROW_TYPES[name]], nullable=name in NULLABLE_FIELDS)
                      for name in ROW_FIELDS])


def _row_size(row, limits):
    _require(type(row) is dict and set(row) == set(ROW_FIELDS), "incorrect row fields")
    for name in ROW_FIELDS:
        value = row[name]
        if value is None:
            _require(name in NULLABLE_FIELDS, "null in required row field")
        else:
            kind = ROW_TYPES[name]
            expected = {"string": str, "int64": int, "bool": bool}[kind]
            _require(type(value) is expected, "incorrect row field type")
            if kind == "int64":
                _require(0 <= value < 2**63, "invalid row integer")
    return len(_canonical(row, limits.max_batch_bytes))


class _Budget:
    def __init__(self, limits):
        self.limits, self.total, self.paths = limits, 0, set()

    def add_file(self, relative):
        _relative(relative, self.limits)
        _require(relative not in self.paths, "duplicate output path")
        _require(len(self.paths) < self.limits.max_files, "file count exceeds bound")
        paths = self.paths | {relative}
        directories = {str(parent) for name in paths for parent in PurePosixPath(name).parents
                       if str(parent) != "."}
        _require(len(directories) <= self.limits.max_directories
                 and len(directories) + len(paths) <= self.limits.max_namespace_entries,
                 "output namespace exceeds bound")
        self.paths.add(relative)

    def charge(self, count, file_bytes):
        _require(file_bytes + count <= self.limits.max_file_bytes, "output file exceeds byte bound")
        _require(self.total + count <= self.limits.max_total_bytes, "output package exceeds aggregate byte bound")
        self.total += count


class _Output(io.RawIOBase):
    """Forward-only writer charging real output bytes before every write."""
    def __init__(self, root_fd, relative, budget):
        super().__init__()
        self._stream, self._parent_fd = None, None
        budget.add_file(relative)
        parent = _directory_at(root_fd, PurePosixPath(relative).parts[:-1])
        try:
            fd = os.open(PurePosixPath(relative).name,
                         os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=parent)
            try:
                self._stream = os.fdopen(fd, "wb", buffering=0)
            except BaseException:
                os.close(fd)
                raise
        except BaseException:
            os.close(parent)
            raise
        self._parent_fd = parent
        self._budget, self._size, self._digest = budget, 0, hashlib.sha256()

    def writable(self):
        return True

    def tell(self):
        return self._size

    def write(self, value):
        _require(not self.closed, "closed output stream")
        view = memoryview(value)
        count = view.nbytes
        self._budget.charge(count, self._size)
        offset = 0
        while offset < count:
            written = self._stream.write(view[offset:])
            _require(type(written) is int and written > 0, "short output write")
            offset += written
        self._digest.update(view)
        self._size += count
        return count

    def flush(self):
        if self._stream is not None and not self._stream.closed:
            self._stream.flush()

    def close(self):
        if not self.closed:
            try:
                if self._stream is not None:
                    self.flush()
                    os.fsync(self._stream.fileno())
                # File data and its entry in a nested directory are separate
                # durability boundaries. Keep this descriptor until both sync.
                if self._parent_fd is not None:
                    os.fsync(self._parent_fd)
            finally:
                try:
                    if self._stream is not None:
                        self._stream.close()
                finally:
                    try:
                        if self._parent_fd is not None:
                            os.close(self._parent_fd)
                            self._parent_fd = None
                    finally:
                        super().close()

    def reference(self):
        _require(self.closed and self._size > 0, "output is not finalized")
        return {"sha256": self._digest.hexdigest(), "bytes": self._size}


def _write(root_fd, relative, raw, budget, kind):
    with _Output(root_fd, relative, budget) as output:
        for offset in range(0, len(raw), _CHUNK):
            output.write(raw[offset:offset + _CHUNK])
    return {"relative_path": relative, **output.reference(), "kind": kind, "row_count": None}


def _copy(root, root_fd, artifact, relative, budget, kind):
    path = _path(artifact["path"])
    _require(not path.is_relative_to(root), "source/output alias is forbidden")
    reference = _ref({"sha256": artifact["sha256"], "bytes": artifact["bytes"]}, budget.limits)
    with os.fdopen(_regular(path), "rb") as source:
        before = os.fstat(source.fileno())
        _require(before.st_size == reference["bytes"], "source size differs before copy")
        with _Output(root_fd, relative, budget) as output:
            size = 0
            while chunk := source.read(min(_CHUNK, reference["bytes"] - size + 1)):
                size += len(chunk)
                _require(size <= reference["bytes"], "source grew during copy")
                output.write(chunk)
        after = os.fstat(source.fileno())
        _require(_identity(before) == _identity(after), "source changed during copy")
    _current_file(path, after)
    _require(output.reference() == reference, "copied source differs from reference")
    _root_current(root, root_fd)
    return {"relative_path": relative, **reference, "kind": kind, "row_count": None}


def _parquet_footer(parquet, row_count, limits, schema):
    _require(parquet.schema_arrow.equals(schema, check_metadata=True), "Parquet schema differs")
    metadata = parquet.metadata
    _require(metadata.num_rows == row_count and 0 < row_count <= limits.max_rows_per_file,
             "Parquet row count differs or exceeds bound")
    _require(0 < metadata.num_row_groups <= row_count, "invalid row-group count")
    uncompressed = 0
    for index in range(metadata.num_row_groups):
        group = metadata.row_group(index)
        _require(0 < group.num_rows <= 256 and 0 < group.total_byte_size <= limits.max_row_group_bytes,
                 "Parquet row group exceeds decode bound")
        uncompressed += group.total_byte_size
    _require(uncompressed <= limits.max_parquet_uncompressed_bytes,
             "Parquet uncompressed file exceeds bound")


def _namespace(root, limits, expected):
    seen, directories, identities, total = set(), set(), set(), 0
    def visit(fd, prefix):
        nonlocal total
        with os.scandir(fd) as iterator:
            for entry in iterator:
                name = prefix + entry.name
                _relative(name, limits)
                info = entry.stat(follow_symlinks=False)
                _require(len(seen) + len(directories) < limits.max_namespace_entries,
                         "namespace entry count exceeds bound")
                if stat.S_ISDIR(info.st_mode):
                    directories.add(name)
                    _require(len(directories) <= limits.max_directories, "directory count exceeds bound")
                    child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                    dir_fd=fd)
                    try:
                        visit(child, name + "/")
                    finally:
                        os.close(child)
                else:
                    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                             "package contains a symlink, hardlink or special file")
                    identity = (info.st_dev, info.st_ino)
                    _require(identity not in identities, "duplicate physical file alias")
                    identities.add(identity)
                    seen.add(name)
                    _require(len(seen) <= limits.max_files and 0 < info.st_size <= limits.max_file_bytes,
                             "package file count or size exceeds bound")
                    total += info.st_size
                    _require(total <= limits.max_total_bytes, "package aggregate bytes exceed bound")
    fd = _directory(root)
    try:
        visit(fd, "")
    finally:
        os.close(fd)
    expected_dirs = {str(parent) for name in expected for parent in PurePosixPath(name).parents
                     if str(parent) != "."}
    _require(seen == set(expected) and directories == expected_dirs, "package namespace is not exact")
    return total


def _manifest(value, caller_limits):
    _require(type(value) is dict and set(value) == _MANIFEST_FIELDS, "invalid manifest fields")
    _require(value["schema_version"] == SCHEMA_VERSION and value["scope"] == SCOPE,
             "unsupported export schema or scope")
    _require(type(value["limits"]) is dict and set(value["limits"]) == set(asdict(caller_limits)),
             "invalid manifest limits")
    recorded = CorpusExportLimits(**value["limits"])
    limits = CorpusExportLimits(**{name: min(amount, getattr(caller_limits, name))
                                  for name, amount in asdict(recorded).items()})
    _require(_canonical(value["qualification"]) == _canonical(_QUALIFICATION), "false authority flags required")
    _require(_canonical(value["row_schema"]) == _canonical(_row_schema()), "row schema declaration differs")
    writer = value["writer"]
    _require(type(writer) is dict and set(writer) == {"format", "compression", "parquet_version", "pyarrow_version", "batch_size"}
             and writer["format"] == "parquet" and writer["compression"] == "zstd"
             and writer["parquet_version"] == "2.6" and type(writer["pyarrow_version"]) is str
             and 0 < len(writer["pyarrow_version"]) <= 128
             and type(writer["batch_size"]) is int and 1 <= writer["batch_size"] <= 256,
             "invalid writer declaration")
    items = value["files"]
    _require(type(items) is list and 1 <= len(items) < limits.max_files, "manifest file count exceeds bound")
    names, total, rows, shards = [], 0, 0, []
    for item in items:
        _require(type(item) is dict and set(item) == _FILE_FIELDS, "invalid file descriptor")
        name = _relative(item["relative_path"], limits)
        _ref({key: item[key] for key in ("sha256", "bytes")}, limits)
        _require(name != MANIFEST_NAME, "manifest cannot describe itself")
        names.append(name)
        total += item["bytes"]
        if item["kind"] == "source_rows":
            _require(name == f"data/source_rows/part-{len(shards):06d}.parquet", "row shard order or path differs")
            _require(type(item["row_count"]) is int and 0 < item["row_count"] <= limits.max_rows_per_file,
                     "invalid row shard count")
            rows += item["row_count"]
            shards.append(item)
        else:
            _require(item["kind"] in {"source_corpus", "provenance", "embedding_evidence", "readme"}
                     and item["row_count"] is None, "invalid non-row file descriptor")
    _require(names == sorted(set(names)) and 0 < rows <= limits.max_rows
             and total <= limits.max_total_bytes, "manifest count, ordering or aggregate bound differs")
    return limits, shards


def _packaged_provider(root, manifest, limits):
    from .autoencoder_uscode_import import load_uscode_release, USCodeImportLimits
    from .autoencoder_uscode_inventory import USCodeSourceInventory
    from .autoencoder_source_partitions import SourcePartitions
    from .autoencoder_embedding_receipt_set import EmbeddingReceiptSet
    by_path = {item["relative_path"]: item for item in manifest["files"]}
    by_hash = {}
    for item in manifest["files"]:
        if item["kind"] not in {"provenance", "source_corpus", "embedding_evidence"}:
            continue
        prior = by_hash.setdefault(item["sha256"], item)
        _require(prior["bytes"] == item["bytes"], "digest has conflicting byte counts")
    def resolver(ref):
        _ref(ref, limits)
        item = by_hash.get(ref["sha256"])
        _require(item is not None and item["bytes"] == ref["bytes"], "required packaged artifact is missing")
        return root / item["relative_path"]
    def raw(name):
        item = by_path[name]
        _require(item["kind"] == "provenance", "incorrect provenance role")
        return _read(root / name, min(item["bytes"], limits.max_file_bytes, 64 * 1024**2))
    metadata = manifest["metadata"]
    release_data = metadata["release"]
    release_ref = release_data["manifest"]
    _require({key: by_path["provenance/release-manifest.json"][key] for key in ("sha256", "bytes")} == release_ref,
             "release root descriptor differs")
    release = load_uscode_release(release_ref, repo_id=release_data["repo_id"],
        revision=release_data["revision"], resolver=resolver,
        limits=USCodeImportLimits(**release_data["import_limits"]))
    inventory = USCodeSourceInventory(raw("provenance/source-inventory.json"))
    partitions = (SourcePartitions(raw("provenance/source-partitions.json"), inventory)
                  if metadata["source_partitions"] is not None else None)
    receipts = (EmbeddingReceiptSet(raw("provenance/embedding-receipt-set.json"), partitions)
                if metadata["embedding_receipt_set"] is not None else None)
    provider = USCodeCorpusRows(inventory, release=release, resolver=resolver, partitions=partitions,
        receipt_set=receipts, receipt_resolver=resolver, source_resolver=resolver,
        batch_size=manifest["writer"]["batch_size"])
    _require(_canonical(provider.metadata, limits.max_manifest_bytes) == _canonical(metadata, limits.max_manifest_bytes),
             "source metadata differs from reconstructed provenance")
    expected = {}
    for item in provider.source_artifacts:
        expected["source/corpus/" + item["relative_path"]] = (item, "source_corpus")
    for item in provider.evidence_artifacts:
        expected[item["relative_path"]] = (item, "embedding_evidence")
    for item in provider.provenance_artifacts:
        expected[item["relative_path"]] = ({"sha256": hashlib.sha256(item["raw"]).hexdigest(),
                                            "bytes": len(item["raw"])}, "provenance")
    expected["README.md"] = ({"sha256": hashlib.sha256(_README).hexdigest(), "bytes": len(_README)}, "readme")
    actual = {item["relative_path"]: item for item in manifest["files"] if item["kind"] != "source_rows"}
    _require(set(actual) == set(expected), "typed source/provenance closure differs")
    for name, (ref, kind) in expected.items():
        _require(actual[name]["kind"] == kind and all(actual[name][key] == ref[key] for key in ("sha256", "bytes")),
                 "typed artifact role or descriptor differs")
    return provider


def _verify_rows(root, manifest, limits, shards):
    import pyarrow.parquet as pq
    provider = _packaged_provider(root, manifest, limits)
    expected = provider.iter_rows()
    schema, total = _arrow_schema(), 0
    try:
        for item in shards:
            path = root / item["relative_path"]
            with os.fdopen(_regular(path), "rb") as stream:
                before = os.fstat(stream.fileno())
                parquet = pq.ParquetFile(stream)
                _parquet_footer(parquet, item["row_count"], limits, schema)
                count = 0
                for batch in parquet.iter_batches(batch_size=min(64, manifest["writer"]["batch_size"]), use_threads=False):
                    _require(batch.nbytes <= limits.max_row_group_bytes, "decoded Arrow batch exceeds bound")
                    logical = 0
                    for row in batch.to_pylist():
                        logical += _row_size(row, limits)
                        _require(logical <= limits.max_row_group_bytes, "decoded row batch exceeds bound")
                        try:
                            original = next(expected)
                        except StopIteration as exc:
                            raise CorpusExportError("unexpected extra exported row") from exc
                        _require(row == original, "Parquet row differs from original source/provenance")
                        count += 1
                    del batch
                _require(count == item["row_count"], "decoded Parquet count differs")
                after = os.fstat(stream.fileno())
                _require(_identity(before) == _identity(after), "Parquet changed during verification")
            _current_file(path, after)
            total += count
        try:
            next(expected)
        except StopIteration:
            pass
        else:
            raise CorpusExportError("missing exported physical source rows")
        _require(_canonical(provider.summary(), limits.max_manifest_bytes) == _canonical(manifest["coverage"], limits.max_manifest_bytes),
                 "coverage differs from regenerated physical rows")
        provider.verify_final()
        _require(total == manifest["metadata"]["declared_row_count"], "declared physical row coverage differs")
    finally:
        expected.close()
    return total


def _report(root, ref, manifest, shards):
    return {"schema_version": REPORT_SCHEMA_VERSION, "output_directory": str(root),
        "manifest_artifact": {"path": str(root / MANIFEST_NAME), **ref},
        "row_count": sum(item["row_count"] for item in shards),
        "row_shards": [{key: item[key] for key in ("relative_path", "sha256", "bytes", "row_count")} for item in shards],
        "coverage": manifest["coverage"], "qualification": dict(_QUALIFICATION)}


@_errors
def export_uscode_source_rows(inventory, destination, *, release, resolver,
        partitions=None, receipt_set=None, receipt_resolver=None, source_resolver=None,
        limits=CorpusExportLimits(), batch_size=64):
    """Write a new package, retaining partial bytes on failure without a manifest."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    limits = _limits(limits)
    _require(type(batch_size) is int and 1 <= batch_size <= 256, "invalid row batch size")
    root = _path(destination)
    # Validate/capture all source metadata and selected receipt evidence before
    # creating output. The provider never opens untrusted historical locators.
    provider = USCodeCorpusRows(inventory, release=release, resolver=resolver, partitions=partitions,
        receipt_set=receipt_set, receipt_resolver=receipt_resolver, source_resolver=source_resolver,
        batch_size=batch_size)
    metadata = provider.metadata
    _require(0 < metadata["declared_row_count"] <= limits.max_rows, "physical row count exceeds export bound")
    # Preflight the complete declared copy closure before output creation. The
    # streaming budget below additionally charges every generated byte.
    planned = _Budget(limits)
    for item in provider.provenance_artifacts:
        planned.add_file(item["relative_path"])
        _require(0 < len(item["raw"]) <= limits.max_file_bytes, "provenance file exceeds bound")
        planned.charge(len(item["raw"]), 0)
    for kind, artifacts in (("source", provider.source_artifacts), ("evidence", provider.evidence_artifacts)):
        for item in artifacts:
            ref = _ref({key: item[key] for key in ("sha256", "bytes")}, limits)
            original = _path(item["path"])
            _require(not original.is_relative_to(root), "source/output alias is forbidden")
            planned.add_file(("source/corpus/" if kind == "source" else "") + item["relative_path"])
            planned.charge(ref["bytes"], 0)
    planned.add_file("README.md")
    planned.charge(len(_README), 0)
    planned.add_file(MANIFEST_NAME)
    planned.add_file("data/source_rows/part-000000.parquet")
    planned.charge(2, 0)  # Strictly positive manifest and first row-file lower bounds.
    _canonical(metadata, limits.max_manifest_bytes)
    budget = _Budget(limits)
    files, row_shards, writer, output = [], [], None, None
    root_fd = _new_root(root)
    iterator, manifest_identity, committed = None, None, False
    try:
        for item in provider.provenance_artifacts:
            files.append(_write(root_fd, item["relative_path"], item["raw"], budget, "provenance"))
        for item in provider.source_artifacts:
            files.append(_copy(root, root_fd, item, "source/corpus/" + item["relative_path"], budget, "source_corpus"))
        for item in provider.evidence_artifacts:
            files.append(_copy(root, root_fd, item, item["relative_path"], budget, "embedding_evidence"))
        files.append(_write(root_fd, "README.md", _README, budget, "readme"))
        schema, buffer, buffered_bytes, rows_in_file, logical_in_file, total = _arrow_schema(), [], 0, 0, 0, 0
        relative = None
        def finish():
            nonlocal writer, output
            if writer is not None:
                writer.close()
                writer = None
                output.close()
                descriptor = {"relative_path": relative, **output.reference(),
                              "kind": "source_rows", "row_count": rows_in_file}
                with os.fdopen(_regular(root / relative), "rb") as stream:
                    _parquet_footer(pq.ParquetFile(stream), rows_in_file, limits, schema)
                files.append(descriptor)
                row_shards.append(descriptor)
                output = None
        def flush():
            nonlocal writer, output, rows_in_file, logical_in_file, relative, buffer, buffered_bytes
            if not buffer:
                return
            # Canonical row bytes are a conservative planning bound, while
            # actual compressed bytes are charged by _Output before writes.
            if writer is not None and (rows_in_file + len(buffer) > limits.max_rows_per_file
                    or logical_in_file + buffered_bytes > limits.max_parquet_uncompressed_bytes // 2):
                finish()
            if writer is None:
                relative = f"data/source_rows/part-{len(row_shards):06d}.parquet"
                output = _Output(root_fd, relative, budget)
                writer = pq.ParquetWriter(output, schema, compression="zstd", version="2.6",
                                          use_dictionary=False, write_statistics=True)
                rows_in_file = logical_in_file = 0
            table = pa.Table.from_pylist(buffer, schema=schema)
            writer.write_table(table, row_group_size=len(buffer))
            rows_in_file += len(buffer)
            logical_in_file += buffered_bytes
            buffer, buffered_bytes = [], 0
            del table
        iterator = provider.iter_rows()
        for row in iterator:
            size = _row_size(row, limits)
            if buffer and (len(buffer) >= min(batch_size, limits.max_rows_per_file)
                           or buffered_bytes + size > limits.max_batch_bytes):
                flush()
            buffer.append(row)
            buffered_bytes += size
            total += 1
            _require(total <= limits.max_rows, "physical row count grew beyond bound")
        flush()
        finish()
        _require(total == metadata["declared_row_count"], "incomplete physical row export")
        provider.verify_final()
        manifest = {"schema_version": SCHEMA_VERSION, "scope": SCOPE, "metadata": metadata,
            "coverage": provider.summary(), "limits": asdict(limits),
            "files": sorted(files, key=lambda item: item["relative_path"]), "row_schema": _row_schema(),
            "writer": {"format": "parquet", "compression": "zstd", "parquet_version": "2.6",
                       "pyarrow_version": pa.__version__, "batch_size": batch_size},
            "qualification": dict(_QUALIFICATION)}
        _, shards = _manifest(manifest, limits)
        raw = _canonical(manifest, limits.max_manifest_bytes)
        # Rehash generated/copied files before the sole completion marker.
        _namespace(root, limits, budget.paths)
        for item in files:
            _hash(root / item["relative_path"], {key: item[key] for key in ("sha256", "bytes")}, maximum=limits.max_file_bytes)
        provider.verify_final()
        _root_current(root, root_fd)
        # Reserve the entire completion marker before creating its pathname.
        _require(len(raw) <= limits.max_file_bytes and budget.total + len(raw) <= limits.max_total_bytes,
                 "completion manifest exceeds package byte bound")
        with _Output(root_fd, MANIFEST_NAME, budget) as completion:
            info = os.fstat(completion._stream.fileno())
            manifest_identity = (info.st_dev, info.st_ino)
            completion.write(raw)
        os.fsync(root_fd)
        _namespace(root, limits, budget.paths)
        _root_current(root, root_fd)
        report = _report(root, completion.reference(), manifest, shards)
        committed = True
        return report
    finally:
        # A local failure after opening the completion marker must not leave a
        # valid-looking manifest. Never remove an externally replaced inode.
        if not committed and manifest_identity is not None:
            try:
                info = os.stat(MANIFEST_NAME, dir_fd=root_fd, follow_symlinks=False)
                if (info.st_dev, info.st_ino) == manifest_identity:
                    os.unlink(MANIFEST_NAME, dir_fd=root_fd)
                    os.fsync(root_fd)
            except OSError:
                pass
        if iterator is not None:
            iterator.close()
        try:
            if writer is not None:
                writer.close()
        finally:
            if output is not None:
                output.close()
            os.close(root_fd)


@_errors
def verify_uscode_source_export(path, *, expected_manifest_sha256, limits=CorpusExportLimits()):
    """Independently regenerate all rows using only the bounded local package."""
    limits, root = _limits(limits), _path(path)
    _digest(expected_manifest_sha256)
    root_fd = _directory(root)
    try:
        raw = _read(root / MANIFEST_NAME, min(limits.max_manifest_bytes, limits.max_file_bytes))
        _require(hashlib.sha256(raw).hexdigest() == expected_manifest_sha256, "manifest digest mismatch")
        manifest = _parse(raw)
        limits, shards = _manifest(manifest, limits)
        _require(len(raw) <= limits.max_manifest_bytes, "manifest exceeds recorded byte bound")
        expected = {MANIFEST_NAME, *(item["relative_path"] for item in manifest["files"])}
        _namespace(root, limits, expected)
        for item in manifest["files"]:
            _hash(root / item["relative_path"], {key: item[key] for key in ("sha256", "bytes")}, maximum=limits.max_file_bytes)
        _verify_rows(root, manifest, limits, shards)
        # Fresh guards after all semantic reads, including the manifest itself.
        for item in manifest["files"]:
            _hash(root / item["relative_path"], {key: item[key] for key in ("sha256", "bytes")}, maximum=limits.max_file_bytes)
        ref = {"sha256": expected_manifest_sha256, "bytes": len(raw)}
        _hash(root / MANIFEST_NAME, ref, maximum=limits.max_manifest_bytes)
        _namespace(root, limits, expected)
        _root_current(root, root_fd)
        return _report(root, ref, manifest, shards)
    finally:
        os.close(root_fd)
