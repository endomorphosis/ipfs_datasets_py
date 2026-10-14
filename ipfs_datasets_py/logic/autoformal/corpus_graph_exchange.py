"""Lossless local candidate-graph Parquet bundles with external manifest pins.

The readable columns are projections of sealed canonical JSON records. All
three payload files are hash-checked before parsing; their records reconstruct
the exact sealed snapshot. References outside the snapshot are declarations,
not authenticated evidence. No dataset upload or legal admission occurs here.

V1 admits only flat, uncompressed, nondictionary Parquet with a fixed schema.
Metadata, row counts, decoded buffers and canonical records have separate bounds.
PyArrow is imported only when a bundle is actually written or read.
"""
from __future__ import annotations

import hashlib
import os
import stat
import struct
from pathlib import Path

from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

from . import corpus_graph as graph
from .corpus_contracts import (
    MAX_RECORD_BYTES,
    CorpusContractError,
    load_record_bytes,
    require_cid,
    require_int,
    require_keys,
    require_sha256,
    seal_record,
    validate_record,
)

SCHEMA = "legal-corpus-graph-bundle/v1"
FORMAT_PROFILE = "candidate-graph-parquet-with-canonical-records/v1"
MANIFEST_FILE = "manifest.json"
SNAPSHOT_FILE = "snapshot.json"
NODES_FILE = "nodes.parquet"
EDGES_FILE = "edges.parquet"
PAYLOAD_FILES = (NODES_FILE, EDGES_FILE, SNAPSHOT_FILE)
BUNDLE_FILES = frozenset((*PAYLOAD_FILES, MANIFEST_FILE))
MAX_MANIFEST_BYTES = 32 * 1024
MAX_PARQUET_BYTES = 8 * 1024 * 1024
MAX_FOOTER_BYTES = 512 * 1024
MAX_DECODED_BYTES = 4 * 1024 * 1024
MAX_ROW_GROUPS = 128
MAX_THRIFT_CONTAINERS = 32_768
_FLAGS = ("admitted", "formalized", "source_semantics_verified", "external_references_verified")
_MANIFEST_FIELDS = {"format_profile", "snapshot_cid", "node_count", "edge_count", "files", "view", *_FLAGS}
_NODE_COLUMNS = ("record_cid", "node_type", "stable_id", "content_cid", "scope_cid", "record_json")
_EDGE_COLUMNS = ("record_cid", "src_cid", "dst_cid", "relation", "ordinal", "record_json")


def _require(condition, message):
    if not condition:
        raise CorpusContractError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _arrow():
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as error:
        raise CorpusContractError("PyArrow is required for local graph bundle exchange") from error
    return pa, pq


def _schemas(pa):
    def text(name, nullable=False):
        return pa.field(name, pa.string(), nullable=nullable)
    return {
        NODES_FILE: pa.schema([text(name, nullable=name == "scope_cid") for name in _NODE_COLUMNS]),
        EDGES_FILE: pa.schema([pa.field(name, pa.int64(), nullable=True) if name == "ordinal" else text(name)
                              for name in _EDGE_COLUMNS]),
    }


def _path(value):
    try:
        path = Path(value).absolute()
    except (TypeError, ValueError) as error:
        raise CorpusContractError("ordinary bundle directory path required") from error
    _require(".." not in path.parts and "\x00" not in str(path), "bundle path traversal is refused")
    return path


def _directory_components(path):
    for component in (*reversed(path.parents), path):
        info = component.lstat()
        _require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode),
                 "bundle path must use regular directories without symlinks")


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _open_directory(path):
    _directory_components(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        _verify_directory(path, descriptor)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _verify_directory(path, descriptor):
    _directory_components(path)
    current, opened = path.lstat(), os.fstat(descriptor)
    _require((current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino),
             "bundle directory changed during operation")


def _read_file(descriptor, name, maximum, *, expected_sha256=None, expected_size=None):
    _require(name in BUNDLE_FILES, "unknown bundle filename")
    handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
    try:
        before = os.fstat(handle)
        _require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= maximum,
                 "bounded regular bundle file required: " + name)
        _require(expected_size is None or before.st_size == expected_size, "bundle file size differs: " + name)
        chunks, length = [], 0
        while length <= maximum:
            part = os.read(handle, min(65536, maximum + 1 - length))
            if not part:
                break
            chunks.append(part)
            length += len(part)
        raw = b"".join(chunks)
        after = os.fstat(handle)
        current = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        _require(_identity(before) == _identity(after) == _identity(current)
                 and stat.S_ISREG(current.st_mode) and len(raw) == before.st_size <= maximum,
                 "bundle file changed while reading: " + name)
        if expected_sha256 is not None:
            _require(_sha(raw) == expected_sha256, "bundle file SHA256 differs: " + name)
        return raw
    finally:
        os.close(handle)


def _write_file(descriptor, name, raw):
    handle = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
    try:
        remaining = memoryview(raw)
        while remaining:
            amount = os.write(handle, remaining)
            _require(amount > 0, "bundle write made no progress")
            remaining = remaining[amount:]
        os.fsync(handle)
        return os.fstat(handle)
    finally:
        os.close(handle)


def _validate_manifest(value):
    result = validate_record(value, schema=SCHEMA, fields=_MANIFEST_FIELDS)
    _require(result["format_profile"] == FORMAT_PROFILE and result["view"] == "candidate",
             "unsupported graph bundle format or view")
    _require(all(result[key] is False for key in _FLAGS), "graph bundle cannot claim authority")
    require_cid(result["snapshot_cid"], "snapshot_cid", codecs=("dag-json",))
    require_int(result["node_count"], "node_count", minimum=1, maximum=graph.MAX_NODES)
    require_int(result["edge_count"], "edge_count", maximum=graph.MAX_EDGES)
    require_keys(result["files"], PAYLOAD_FILES, "bundle files")
    for name in PAYLOAD_FILES:
        record = result["files"][name]
        require_keys(record, {"sha256", "size_bytes", "row_count"}, "bundle file binding")
        require_sha256(record["sha256"], name + " SHA256")
        require_int(record["size_bytes"], name + " size", minimum=1,
                    maximum=MAX_RECORD_BYTES if name == SNAPSHOT_FILE else MAX_PARQUET_BYTES)
        expected_rows = result["node_count"] if name == NODES_FILE else result["edge_count"] if name == EDGES_FILE else 1
        require_int(record["row_count"], name + " row_count", maximum=graph.MAX_EDGES)
        _require(record["row_count"] == expected_rows, "bundle row count disagrees: " + name)
    return result


def _projection(record, name):
    fields = _NODE_COLUMNS if name == NODES_FILE else _EDGE_COLUMNS
    return {key: canonical_dag_json_bytes(record).decode("utf-8") if key == "record_json" else record[key]
            for key in fields}


def _parquet_bytes(records, name):
    pa, pq = _arrow()
    table = pa.Table.from_pylist([_projection(record, name) for record in records], schema=_schemas(pa)[name])
    _require(table.nbytes <= MAX_DECODED_BYTES, "graph projection exceeds decoded-data budget")
    output = pa.BufferOutputStream()
    pq.write_table(table, output, compression="NONE", use_dictionary=False, write_statistics=False,
                   row_group_size=128, data_page_size=65536, store_schema=False)
    raw = output.getvalue().to_pybytes()
    _require(0 < len(raw) <= MAX_PARQUET_BYTES, "graph Parquet exceeds byte bound")
    return raw


def _read_parquet(raw, name, row_count):
    pa, pq = _arrow()
    _require(len(raw) >= 12 and raw[:4] == raw[-4:] == b"PAR1", "ordinary Parquet framing required")
    footer_size = struct.unpack("<I", raw[-8:-4])[0]
    _require(0 < footer_size <= MAX_FOOTER_BYTES and footer_size <= len(raw) - 12,
             "Parquet footer exceeds metadata budget")
    parquet = None
    try:
        parquet = pq.ParquetFile(pa.BufferReader(raw), pre_buffer=False, arrow_extensions_enabled=False,
            thrift_string_size_limit=MAX_FOOTER_BYTES, thrift_container_size_limit=MAX_THRIFT_CONTAINERS)
        expected_schema = _schemas(pa)[name]
        _require(parquet.schema_arrow.equals(expected_schema, check_metadata=True),
                 "unknown or incompatible Parquet columns/types/metadata")
        metadata = parquet.metadata
        _require(metadata.num_rows == row_count and metadata.num_columns == len(expected_schema)
                 and metadata.num_row_groups <= MAX_ROW_GROUPS, "Parquet row/group count differs or exceeds bounds")
        total = 0
        for index in range(metadata.num_row_groups):
            group = metadata.row_group(index)
            _require(group.num_rows <= graph.MAX_EDGES and group.num_columns == len(expected_schema),
                     "invalid flat Parquet row group")
            for position in range(group.num_columns):
                column = group.column(position)
                _require(column.compression == "UNCOMPRESSED" and not column.has_dictionary_page
                         and set(column.encodings) <= {"PLAIN", "RLE"},
                         "compressed/dictionary/nonplain Parquet profile refused")
                _require(column.path_in_schema == expected_schema.names[position] and column.num_values == group.num_rows,
                         "nested or inconsistent Parquet value count")
                _require(0 <= column.total_uncompressed_size <= MAX_DECODED_BYTES
                         and 0 <= column.total_compressed_size <= MAX_PARQUET_BYTES,
                         "Parquet column exceeds decoded budget")
                _require(0 <= column.data_page_offset < len(raw), "Parquet data offset is out of bounds")
                total += column.total_uncompressed_size
        _require(total <= MAX_DECODED_BYTES, "Parquet decoded metadata exceeds budget")
        table = parquet.read(use_threads=False)
        _require(table.num_rows == row_count and table.nbytes <= MAX_DECODED_BYTES,
                 "decoded Parquet exceeds row/data budget")
        records = []
        validator = graph.validate_node if name == NODES_FILE else graph.validate_edge
        for row in table.to_pylist():
            text = row["record_json"]
            _require(type(text) is str and len(text.encode("utf-8")) <= MAX_RECORD_BYTES,
                     "bounded canonical record_json required")
            encoded = text.encode("utf-8")
            record = validator(load_record_bytes(encoded, expected_sha256=_sha(encoded)))
            _require(row == _projection(record, name), "Parquet projection disagrees with canonical record")
            records.append(record)
        return records
    except pa.ArrowException as error:
        raise CorpusContractError("Parquet operation refused within the bounded profile") from error
    finally:
        if parquet is not None:
            parquet.close()


def _read_content(descriptor, manifest):
    # Authenticate every payload before invoking either the JSON or Parquet parser.
    payloads = {name: _read_file(descriptor, name,
        MAX_RECORD_BYTES if name == SNAPSHOT_FILE else MAX_PARQUET_BYTES,
        expected_sha256=manifest["files"][name]["sha256"], expected_size=manifest["files"][name]["size_bytes"])
        for name in PAYLOAD_FILES}
    snapshot = graph.validate_graph_snapshot(load_record_bytes(payloads[SNAPSHOT_FILE],
        expected_sha256=manifest["files"][SNAPSHOT_FILE]["sha256"]))
    _require(canonical_dag_json_bytes(snapshot) == payloads[SNAPSHOT_FILE], "snapshot JSON is not exact canonical bytes")
    _require(snapshot["record_cid"] == manifest["snapshot_cid"]
             and len(snapshot["nodes"]) == manifest["node_count"] and len(snapshot["edges"]) == manifest["edge_count"],
             "snapshot identity/counts disagree with manifest")
    nodes = _read_parquet(payloads[NODES_FILE], NODES_FILE, manifest["node_count"])
    edges = _read_parquet(payloads[EDGES_FILE], EDGES_FILE, manifest["edge_count"])
    rebuilt = graph.build_graph_snapshot(nodes, edges)
    _require(rebuilt["nodes"] == nodes and rebuilt["edges"] == edges,
             "Parquet record order differs from canonical snapshot order")
    _require(canonical_dag_json_bytes(rebuilt) == payloads[SNAPSHOT_FILE],
             "Parquet records do not reconstruct the exact sealed snapshot")
    return snapshot


def load_graph_bundle(directory, *, expected_manifest_sha256):
    """Load fixed files under an externally supplied manifest SHA256.

    A seal binds declared contents; it does not authenticate external semantic
    payloads, source occurrences or evidence merely named by those contents.
    """
    require_sha256(expected_manifest_sha256, "expected_manifest_sha256")
    path, descriptor = _path(directory), None
    try:
        descriptor = _open_directory(path)
        _require(set(os.listdir(descriptor)) == BUNDLE_FILES, "incomplete bundle or unknown filenames")
        raw = _read_file(descriptor, MANIFEST_FILE, MAX_MANIFEST_BYTES,
                         expected_sha256=expected_manifest_sha256)
        manifest = _validate_manifest(load_record_bytes(raw, expected_sha256=expected_manifest_sha256))
        _require(canonical_dag_json_bytes(manifest) == raw, "manifest JSON is not exact canonical bytes")
        snapshot = _read_content(descriptor, manifest)
        _verify_directory(path, descriptor)
        _require(set(os.listdir(descriptor)) == BUNDLE_FILES, "bundle filenames changed while loading")
        return {"manifest": manifest, "snapshot": snapshot}
    except (OSError, ValueError, TypeError, OverflowError) as error:
        if isinstance(error, CorpusContractError):
            raise
        raise CorpusContractError("invalid local graph bundle: " + str(error)) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def write_graph_bundle(snapshot, output_directory):
    """Write exclusively, read back, then atomically publish manifest.json.

    Failed attempts retain their payloads for inspection, without a committed
    manifest. Existing directories/files are never overwritten or reused.
    """
    snapshot = graph.validate_graph_snapshot(snapshot)
    path, descriptor, committed = _path(output_directory), None, None
    try:
        _directory_components(path.parent)
        path.mkdir(mode=0o700, exist_ok=False)
        descriptor = _open_directory(path)
        payloads = {NODES_FILE: _parquet_bytes(snapshot["nodes"], NODES_FILE),
                    EDGES_FILE: _parquet_bytes(snapshot["edges"], EDGES_FILE),
                    SNAPSHOT_FILE: canonical_dag_json_bytes(snapshot)}
        files = {}
        for name, raw in payloads.items():
            _write_file(descriptor, name, raw)
            files[name] = {"sha256": _sha(raw), "size_bytes": len(raw),
                           "row_count": len(snapshot["nodes"]) if name == NODES_FILE
                           else len(snapshot["edges"]) if name == EDGES_FILE else 1}
        manifest = _validate_manifest(seal_record({"schema": SCHEMA, "format_profile": FORMAT_PROFILE,
            "snapshot_cid": snapshot["record_cid"], "node_count": len(snapshot["nodes"]),
            "edge_count": len(snapshot["edges"]), "files": files, "view": "candidate",
            **dict.fromkeys(_FLAGS, False)}))
        _require(_read_content(descriptor, manifest) == snapshot, "writer readback differs from input snapshot")
        raw_manifest = canonical_dag_json_bytes(manifest)
        _require(len(raw_manifest) <= MAX_MANIFEST_BYTES, "manifest exceeds byte bound")
        staged = _write_file(descriptor, ".manifest.pending", raw_manifest)
        _verify_directory(path, descriptor)
        os.link(".manifest.pending", MANIFEST_FILE, src_dir_fd=descriptor, dst_dir_fd=descriptor, follow_symlinks=False)
        committed = (staged.st_dev, staged.st_ino)
        os.unlink(".manifest.pending", dir_fd=descriptor)
        os.fsync(descriptor)
        loaded = load_graph_bundle(path, expected_manifest_sha256=_sha(raw_manifest))
        _require(loaded == {"manifest": manifest, "snapshot": snapshot}, "writer final bundle readback differs")
        return manifest
    except (OSError, ValueError, TypeError, OverflowError) as error:
        if committed is not None and descriptor is not None:
            try:
                current = os.stat(MANIFEST_FILE, dir_fd=descriptor, follow_symlinks=False)
                if (current.st_dev, current.st_ino) == committed:
                    os.unlink(MANIFEST_FILE, dir_fd=descriptor)
            except OSError:
                pass
        if isinstance(error, CorpusContractError):
            raise
        raise CorpusContractError("could not write local graph bundle: " + str(error)) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
