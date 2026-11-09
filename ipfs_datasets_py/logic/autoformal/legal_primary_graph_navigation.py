"""Manifest-bound navigation projections of the existing primary graph transport.

The twelve-field index is paired with the complete reconstruction JSONL. That
companion preserves parsed properties and physical custody; exact original
record_json bytes remain in the independently pinned source shards. No legacy
cache repair, semantic graph, database authority or legal admission is implied.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat

from . import legal_primary_graph_reconstruction as reconstruction
from . import meta_ontology

SCHEMA = "legal-primary-navigation-bundle/v1"
PROFILE = "complete-primary-records-with-twelve-field-navigation/v1"
CANDIDATE = "primary-records.jsonl"
REPORT = "reconstruction.json"
INDEX = "navigation.parquet"
MANIFEST = "manifest.json"
FILES = frozenset((CANDIDATE, REPORT, INDEX, MANIFEST))
FIELDS = ("record_kind", "meta_category", "graph_kind", "label", "legal_id", "node_id",
          "src", "dst", "logic_role", "in_formula", "admitted", "formalized")
BOOLEANS = frozenset(("in_formula", "admitted", "formalized"))
DEFAULT_LIMITS = {"max_candidate_bytes": 1024**3, "max_report_bytes": 8*1024**2,
    "max_index_bytes": 64*1024**2, "max_manifest_bytes": 1024**2,
    "max_line_bytes": 4*1024**2, "max_rows": 1_000_000, "batch_size": 512,
    "max_batch_bytes": 8*1024**2, "max_decoded_bytes": 1024**3,
    "max_row_group_bytes": 128*1024**2, "max_row_groups": 4096}
AUTHORITY = dict.fromkeys(("admitted", "formalized", "source_semantics_verified", "proof_authority",
    "training_qualified", "source_occurrences_bound", "published", "legacy_cache_repair_verified"), False)
_MANIFEST_FIELDS = {"schema", "profile", "selection_sha256", "reconstruction_sha256", "rows",
    "family_row_counts", "files", "limits", "reconstruction_limits", "source_lineage",
    "coverage_scope", "lossless_scope", "source_shards_required", "authority", "producer_pins"}


class PrimaryGraphNavigationError(ValueError):
    """Complete source custody, deterministic projection or a finite bound differs."""


def _need(value, message):
    if not value:
        raise PrimaryGraphNavigationError(message)


def _wire(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def _parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _need(key not in result, "duplicate JSON field")
            result[key] = value
        return result
    try:
        result = json.loads(raw, object_pairs_hook=pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
        _wire(result)  # Reject numeric overflow, including otherwise valid JSON such as 1e999.
        return result
    except (ValueError, UnicodeError, RecursionError) as error:
        raise PrimaryGraphNavigationError("bounded finite UTF8 JSON required") from error


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _limits(value):
    _need(value is None or type(value) is dict and not set(value)-set(DEFAULT_LIMITS), "closed navigation limits required")
    result = dict(DEFAULT_LIMITS, **(value or {}))
    for key, maximum in DEFAULT_LIMITS.items():
        _need(type(result[key]) is int and 0 < result[key] <= maximum, "positive lowered limit required: " + key)
    return result


def _pins():
    modules = (reconstruction, reconstruction.manifests, reconstruction.records, meta_ontology)
    return {str(path.resolve()): _sha(path.read_bytes()) for path in
            (Path(__file__), *(Path(module.__file__) for module in modules))}


def _arrow():
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as error:
        raise PrimaryGraphNavigationError("PyArrow is required; no installation is attempted") from error
    return pa, pq


def _schema(pa):
    return pa.schema([pa.field(name, pa.bool_() if name in BOOLEANS else pa.string(), nullable=False) for name in FIELDS])


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _directory(path):
    path = Path(path).absolute()
    _need(".." not in path.parts and path.resolve(strict=True) == path and path.is_dir(), "real nonaliased directory required")
    return path


def _guard(path, descriptor):
    _directory(path)
    left, right = path.lstat(), os.fstat(descriptor)
    _need((left.st_dev, left.st_ino) == (right.st_dev, right.st_ino), "bundle directory changed")


def _hash_stream(stream, bound):
    stream.seek(0)
    digest, count = hashlib.sha256(), 0
    while raw := stream.read(min(1024**2, bound-count+1)):
        count += len(raw)
        _need(count <= bound, "file exceeds navigation bound")
        digest.update(raw)
    stream.seek(0)
    return {"sha256": digest.hexdigest(), "bytes": count}


@contextmanager
def _read_file(directory, descriptor, name, bound, expected=None):
    _need(name in FILES, "unknown navigation file")
    _guard(directory, descriptor)
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        _need(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= bound, "bounded regular navigation input required")
        commitment = _hash_stream(stream, bound)
        _need(expected is None or commitment == expected, "navigation input commitment differs: " + name)
        try:
            yield stream, commitment
        finally:
            _guard(directory, descriptor)
            current = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            _need(_identity(before) == _identity(os.fstat(stream.fileno())) == _identity(current), "navigation file changed during read")
            _need(_hash_stream(stream, bound) == commitment, "navigation bytes changed during read")


def _new_file(descriptor, name, owned):
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
    info = os.fstat(fd)
    owned[name] = (info.st_dev, info.st_ino)
    return os.fdopen(fd, "wb")


def _write_json(descriptor, name, value, maximum, owned):
    raw = _wire(value) + b"\n"
    _need(0 < len(raw) <= maximum, "JSON output bound exceeded")
    with _new_file(descriptor, name, owned) as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())


def _publish_manifest(directory, descriptor, manifest, maximum, owned):
    temporary = ".manifest-pending.json"
    _write_json(descriptor, temporary, manifest, maximum, owned)
    _guard(directory, descriptor)
    before = os.stat(temporary, dir_fd=descriptor, follow_symlinks=False)
    _need((before.st_dev, before.st_ino) == owned[temporary], "staged manifest replaced")
    # link() is atomic and fails if the destination already exists.
    os.link(temporary, MANIFEST, src_dir_fd=descriptor, dst_dir_fd=descriptor, follow_symlinks=False)
    owned[MANIFEST] = owned[temporary]
    after = os.stat(temporary, dir_fd=descriptor, follow_symlinks=False)
    final = os.stat(MANIFEST, dir_fd=descriptor, follow_symlinks=False)
    _need((after.st_dev, after.st_ino) == (final.st_dev, final.st_ino) == owned[temporary],
          "staged manifest changed during publication")
    os.unlink(temporary, dir_fd=descriptor)
    owned.pop(temporary)
    raw = _wire(manifest) + b"\n"
    with _read_file(directory, descriptor, MANIFEST, maximum, {"sha256": _sha(raw), "bytes": len(raw)}):
        pass


def _payload_bindings(report, commitments):
    _need(commitments[CANDIDATE] == {"sha256": report["candidate_sha256"], "bytes": report["candidate_bytes"]},
          "candidate commitment differs from original reconstruction report")
    raw = _wire(report) + b"\n"
    _need(commitments[REPORT] == {"sha256": _sha(raw), "bytes": len(raw)},
          "report commitment differs from original reconstruction report")


def _candidate_rows(stream, report, limits):
    header = stream.readline(limits["max_line_bytes"]+1)
    _need(0 < len(header) <= limits["max_line_bytes"], "candidate header bound exceeded")
    header = _parse(header)
    _need(type(header) is dict and header.get("schema") == reconstruction.HEADER_SCHEMA
          and header.get("ordered_population_sha256") == report["ordered_population_sha256"], "candidate header differs")
    count = 0
    while raw := stream.readline(limits["max_line_bytes"]+1):
        _need(len(raw) <= limits["max_line_bytes"] and count < limits["max_rows"], "candidate row/population bound exceeded")
        row = _parse(raw)
        _need(type(row) is dict and row.get("schema") == reconstruction.ROW_SCHEMA and row.get("global_ordinal") == count,
              "candidate population order differs")
        _need(row.get("disposition") == "proposed_unreviewed_transport"
              and row.get("identity_resolution", {}).get("status") == "unique_declared_identity", "unresolved candidate cannot enter navigation index")
        _need(row.get("candidate_row_sha256") == _sha(_wire({key: value for key, value in row.items() if key != "candidate_row_sha256"})),
              "candidate row commitment differs")
        yield row
        count += 1
    _need(count == report["rows"], "candidate population is incomplete")


def _projection(row):
    body, identity = row["original_body"], row["declared_identity"]
    node = row["family"] == "graph_nodes"
    _need(node or row["family"] == "graph_edges", "unsupported primary graph family")
    kind = body["node_type" if node else "edge_type"]
    category = (meta_ontology.GRAPH_NODE_CATEGORY if node else meta_ontology.GRAPH_EDGE_CATEGORY).get(kind, "unclassified")
    role = "" if node else meta_ontology.LOGICAL_RELATIONS.get(kind, {}).get("logic_role", "unclassified")
    return {"record_kind": "node" if node else "edge", "meta_category": category,
        "graph_kind": kind, "label": body.get("label") if type(body.get("label")) is str else "",
        "legal_id": row["legal_id"] or "", "node_id": identity["entry_cid"] if node else "",
        "src": "" if node else identity["source_entry_cid"], "dst": "" if node else identity["target_entry_cid"],
        "logic_role": role, "in_formula": False, "admitted": False, "formalized": False}


def _ready(report, limits):
    _need(report.get("schema") == reconstruction.SCHEMA and report.get("population_complete") is True
          and report.get("endpoint_integrity_passed") is True and report.get("blockers") == [], "complete conflict-free primary reconstruction required")
    _need(type(report.get("rows")) is int and 0 < report["rows"] <= limits["max_rows"], "reconstruction row bound exceeded")
    _need(report["candidate_bytes"] <= limits["max_candidate_bytes"], "candidate byte bound exceeded")


def _compare(directory, descriptor, report, commitments, limits):
    pa, pq = _arrow()
    with _read_file(directory, descriptor, CANDIDATE, limits["max_candidate_bytes"], commitments[CANDIDATE]) as (candidate, _), \
         _read_file(directory, descriptor, INDEX, limits["max_index_bytes"], commitments[INDEX]) as (source, _):
        parquet = pq.ParquetFile(source, pre_buffer=False, thrift_string_size_limit=1024**2, thrift_container_size_limit=100_000)
        try:
            _need(parquet.schema_arrow.equals(_schema(pa), check_metadata=True), "exact navigation schema required")
            metadata = parquet.metadata
            _need(metadata.num_rows == report["rows"] and 0 < metadata.num_row_groups <= limits["max_row_groups"], "index population differs")
            decoded = 0
            for number in range(metadata.num_row_groups):
                group = metadata.row_group(number)
                sizes = [group.column(c).total_uncompressed_size for c in range(len(FIELDS))]
                _need(all(size >= 0 for size in sizes) and sum(sizes) <= limits["max_row_group_bytes"],
                      "index row group exceeds decoded bound")
                decoded += sum(sizes)
            _need(0 <= decoded <= limits["max_decoded_bytes"], "index decoded metadata exceeds bound")
            expected = iter(_candidate_rows(candidate, report, limits)); count = 0
            for batch in parquet.iter_batches(batch_size=limits["batch_size"], use_threads=False):
                _need(batch.nbytes <= limits["max_batch_bytes"], "index batch exceeds decoded bound")
                for actual in batch.to_pylist():
                    original = next(expected, None)
                    _need(original is not None and actual == _projection(original), "navigation row differs from complete original record")
                    count += 1
            _need(next(expected, None) is None and count == report["rows"], "index/companion population differs")
        finally:
            parquet.close()


def _manifest(report, selection, commitments, limits, reconstruction_limits, pins):
    return {"schema": SCHEMA, "profile": PROFILE, "selection_sha256": selection["selection_sha256"],
        "reconstruction_sha256": report["reconstruction_sha256"], "rows": report["rows"],
        "family_row_counts": report["family_row_counts"], "files": commitments, "limits": limits,
        "reconstruction_limits": reconstruction_limits,
        "source_lineage": {key: selection[key] for key in ("repository", "revision", "manifest_sha256", "expected_release_identity", "expected_graph_population")},
        "coverage_scope": "exact_manifest_selected_primary_graph_rows_only",
        "lossless_scope": "companion_preserves_complete_parsed_properties_and_custody; exact_original_record_json_bytes_remain_in_required_source_shards",
        "source_shards_required": True, "authority": dict(AUTHORITY), "producer_pins": pins}


def write_navigation_bundle(selection, snapshot_root, new_output_directory, *, expected_selection_sha256,
                            blobs_root=None, limits=None, reconstruction_limits=None):
    """Create a new local bundle. Failed directories have no valid manifest.

    Adapter-created files are removed on failure only if their owned inode is
    still present. A successfully delegated reconstruction may remain as a
    diagnostic; foreign files/directories are never recursively removed.
    """
    bounds, pins = _limits(limits), _pins()
    output = Path(new_output_directory).absolute()
    _directory(output.parent)
    _need(not output.exists() and not output.is_symlink(), "output already exists; overwrite refused")
    for source_root in (snapshot_root, blobs_root):
        if source_root is not None:
            _need(not output.is_relative_to(Path(source_root).resolve(strict=True)), "output cannot mutate source roots")
    parent = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        _guard(output.parent, parent)
        os.mkdir(output.name, mode=0o700, dir_fd=parent)
        created = os.stat(output.name, dir_fd=parent, follow_symlinks=False)
        descriptor = os.open(output.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            opened = os.fstat(descriptor)
            _need((created.st_dev, created.st_ino) == (opened.st_dev, opened.st_ino), "new output directory replaced")
            _guard(output.parent, parent)
        except BaseException:
            os.close(descriptor)
            raise
    finally:
        os.close(parent)
    owned = {}; complete = False
    try:
        _guard(output, descriptor)
        report = reconstruction.reconstruct_to_jsonl(selection, snapshot_root, output/CANDIDATE,
            expected_selection_sha256=expected_selection_sha256, blobs_root=blobs_root, limits=reconstruction_limits)
        _ready(report, bounds)
        _write_json(descriptor, REPORT, report, bounds["max_report_bytes"], owned)
        pa, pq = _arrow()
        expected_candidate = {"sha256": report["candidate_sha256"], "bytes": report["candidate_bytes"]}
        with _read_file(output, descriptor, CANDIDATE, bounds["max_candidate_bytes"], expected_candidate) as (candidate, _), \
             _new_file(descriptor, INDEX, owned) as destination:
            with pq.ParquetWriter(destination, _schema(pa), compression="NONE", use_dictionary=False) as writer:
                batch = []; groups = 0
                for row in _candidate_rows(candidate, report, bounds):
                    batch.append(_projection(row))
                    if len(batch) == bounds["batch_size"]:
                        table = pa.Table.from_pylist(batch, schema=_schema(pa))
                        _need(table.nbytes <= bounds["max_batch_bytes"], "output batch exceeds decoded bound")
                        writer.write_table(table); groups += 1; batch = []
                        _need(groups <= bounds["max_row_groups"] and destination.tell() <= bounds["max_index_bytes"], "index output bound exceeded")
                if batch:
                    table = pa.Table.from_pylist(batch, schema=_schema(pa))
                    _need(table.nbytes <= bounds["max_batch_bytes"], "output batch exceeds decoded bound")
                    writer.write_table(table); groups += 1
                _need(groups <= bounds["max_row_groups"], "output group bound exceeded")
            destination.flush(); os.fsync(destination.fileno())
            _need(destination.tell() <= bounds["max_index_bytes"], "complete index byte bound exceeded")
        commitments = {}
        for name, bound in ((CANDIDATE, bounds["max_candidate_bytes"]), (REPORT, bounds["max_report_bytes"]), (INDEX, bounds["max_index_bytes"])):
            with _read_file(output, descriptor, name, bound) as (_, commitment):
                commitments[name] = commitment
        _payload_bindings(report, commitments)
        _compare(output, descriptor, report, commitments, bounds)
        _need(_pins() == pins, "projection owner changed during export")
        manifest = _manifest(report, selection, commitments, bounds, reconstruction_limits, pins)
        _guard(output, descriptor)
        _need(set(os.listdir(descriptor)) == {CANDIDATE, REPORT, INDEX}, "unexpected bundle files before manifest")
        _publish_manifest(output, descriptor, manifest, bounds["max_manifest_bytes"], owned)
        os.fsync(descriptor); _guard(output, descriptor)
        _need(set(os.listdir(descriptor)) == FILES, "unexpected bundle files after manifest")
        complete = True
        return {"manifest": manifest, "manifest_sha256": _sha(_wire(manifest)+b"\n")}
    finally:
        if not complete:
            for name, identity in reversed(list(owned.items())):
                try:
                    info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                    if (info.st_dev, info.st_ino) == identity:
                        os.unlink(name, dir_fd=descriptor)
                except FileNotFoundError:
                    pass
        os.close(descriptor)


def validate_navigation_bundle(directory, *, expected_manifest_sha256, selection, snapshot_root,
                               expected_selection_sha256, blobs_root=None, limits=None, reconstruction_limits=None):
    """Replay the original selected source before accepting the projection.

    An independently supplied manifest pin is necessary but insufficient: a
    resealed altered companion/report must also equal a fresh source replay.
    """
    bounds = _limits(limits); directory = _directory(directory); pins = _pins()
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        _guard(directory, descriptor)
        _need(set(os.listdir(descriptor)) == FILES, "exact complete navigation bundle required")
        with _read_file(directory, descriptor, MANIFEST, bounds["max_manifest_bytes"]) as (stream, commitment):
            _need(commitment["sha256"] == expected_manifest_sha256, "independent manifest pin differs")
            manifest = _parse(stream.read(bounds["max_manifest_bytes"]+1))
        _need(type(manifest) is dict and set(manifest) == _MANIFEST_FIELDS, "closed navigation manifest required")
        _need(manifest["limits"] == bounds and manifest["reconstruction_limits"] == reconstruction_limits,
              "caller execution limits differ from manifest")
        _need(type(manifest["files"]) is dict and set(manifest["files"]) == {CANDIDATE, REPORT, INDEX}, "complete payload commitments required")
        with _read_file(directory, descriptor, REPORT, bounds["max_report_bytes"], manifest["files"][REPORT]) as (stream, _):
            report = _parse(stream.read(bounds["max_report_bytes"]+1))
        _ready(report, bounds)
        _payload_bindings(report, manifest["files"])
        reconstruction.validate_reconstruction(report, selection, snapshot_root, directory/CANDIDATE,
            expected_selection_sha256=expected_selection_sha256, blobs_root=blobs_root, limits=reconstruction_limits)
        _need(_wire(manifest) == _wire(_manifest(report, selection, manifest["files"], bounds, reconstruction_limits, pins)),
              "manifest differs from original source and current projection contract")
        _compare(directory, descriptor, report, manifest["files"], bounds)
        _need(_pins() == pins, "projection owner changed during validation")
        with _read_file(directory, descriptor, MANIFEST, bounds["max_manifest_bytes"]) as (_, final):
            _need(final == commitment, "manifest changed during validation")
        _need(set(os.listdir(descriptor)) == FILES, "bundle population changed during validation")
        return {"manifest": manifest, "manifest_sha256": expected_manifest_sha256,
                "source_replayed": True, "projection_rows_verified": report["rows"], "authority": dict(AUTHORITY)}
    finally:
        os.close(descriptor)


__all__ = ["PrimaryGraphNavigationError", "write_navigation_bundle", "validate_navigation_bundle"]
