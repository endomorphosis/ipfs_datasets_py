"""Bounded, additive transport of independently selected primary graph rows.

Original custody and global dispositions come from the existing manifest,
record and reconstruction owners. Parquet uses the original release writer.
Every physical occurrence survives in lineage, including quarantined rows.
Canonical JSON encoding is declared separately from original wrapper bytes.
This module does not repair historical flat-cache occurrences or admit meaning.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import secrets
import stat


SCHEMA = "legal-primary-graph-export/v1"
PROFILE = "manifest-selected-primary-entry-cid-canonical-parquet/v1"
LINEAGE_HEADER_SCHEMA = "legal-primary-graph-export-lineage-header/v1"
LINEAGE_ROW_SCHEMA = "legal-primary-graph-export-lineage-row/v1"
DEFAULT_LIMITS = {
    "max_rows": 400_000, "max_shards": 1024, "rows_per_shard": 512,
    "max_shard_input_bytes": 8 * 1024 * 1024, "max_parquet_bytes": 64 * 1024 * 1024,
    "max_output_bytes": 1024 * 1024 * 1024, "max_lineage_line_bytes": 8 * 1024 * 1024,
    "max_manifest_bytes": 1024 * 1024, "batch_size": 512,
    "max_decoded_batch_bytes": 16 * 1024 * 1024,
}
FALSE_AUTHORITY = dict.fromkeys((
    "admitted", "formalized", "source_semantics_verified", "semantic_review_verified",
    "training_qualified", "proof_authority", "accepted_graph_view_enabled", "published",
    "historical_flat_occurrences_repaired", "source_population_equivalence_verified",
), False)
_FAMILIES = ("graph_nodes", "graph_edges")
_WRAPPER_FIELDS = ("entry_cid", "legal_id", "family", "record_sha256", "record_json")
_DESCRIPTOR_FIELDS = {"path", "kind", "family", "rows", "bytes", "sha256"}
_MANIFEST_FIELDS = {
    "schema", "profile", "identity_namespace", "source_selection_sha256", "source_manifest_sha256",
    "repository", "revision", "source_rows", "exported_rows", "lineage_only_rows", "quarantined_rows",
    "family_row_counts", "exported_family_row_counts", "disposition_counts",
    "structural_endpoint_integrity_passed", "encoding_transformation_counts", "limits",
    "reconstruction_sha256", "files", "view", "authority",
}


class PrimaryGraphExportError(ValueError):
    """Original population, exact transport or a finite export bound differs."""


def _need(condition, message):
    if not condition:
        raise PrimaryGraphExportError(message)


def _wire(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise PrimaryGraphExportError("finite UTF8 transport JSON required") from error


def _parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _need(key not in result, "duplicate transport JSON key")
            result[key] = value
        return result

    def nonfinite(_value):
        raise PrimaryGraphExportError("nonfinite transport JSON refused")

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise PrimaryGraphExportError("valid bounded transport JSON required") from error
    _need(type(value) is dict and _wire(value) + b"\n" == raw, "canonical transport JSON object required")
    return value


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    return _sha(_wire(value))


def _same(left, right):
    """JSON types, including booleans versus integers, are transport data."""
    return _wire(left) == _wire(right)


def _limits(value):
    _need(value is None or type(value) is dict, "export limits object required")
    supplied = {} if value is None else value
    _need(not set(supplied) - set(DEFAULT_LIMITS), "unknown export limit")
    result = {key: supplied.get(key, ceiling) for key, ceiling in DEFAULT_LIMITS.items()}
    _need(all(type(number) is int and 1 <= number <= DEFAULT_LIMITS[key]
              for key, number in result.items()), "positive lower-only export limits required")
    return result


def _owners():
    from . import legal_primary_graph_manifest as manifests
    from . import legal_primary_graph_records as records
    from . import legal_primary_graph_reconstruction as reconstruction
    from ...processors.legal_data import uscode_hf_release as release
    return manifests, records, reconstruction, release


def _path(value):
    path = Path(value).absolute()
    _need(".." not in path.parts and path.parent.resolve(strict=True) == path.parent,
          "unaliased existing export parent required")
    for parent in (path.parent, *path.parent.parents):
        _need(stat.S_ISDIR(parent.lstat().st_mode), "export parent aliases refused")
    return path


def _outside_sources(path, snapshot_root, blobs_root):
    for source in (snapshot_root, blobs_root):
        if source is not None:
            root = Path(source).absolute()
            _need(root.resolve(strict=True) == root, "immutable source aliases refused")
            _need(not path.is_relative_to(root), "export cannot mutate immutable source roots")


def _inode(info):
    return info.st_dev, info.st_ino


def _file_identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


class _Directory:
    """One guarded directory; cleanup removes only our unchanged-inode files."""
    def __init__(self, path, *, create=False):
        self.path, self.files, self.created = _path(path), {}, create
        self.parent_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.fd = None
        created_inode = None
        try:
            self.parent_inode = _inode(os.fstat(self.parent_fd))
            if create:
                os.mkdir(self.path.name, mode=0o700, dir_fd=self.parent_fd)
                info = os.stat(self.path.name, dir_fd=self.parent_fd, follow_symlinks=False)
                _need(stat.S_ISDIR(info.st_mode), "created export directory became aliased")
                created_inode = _inode(info)
            self.fd = os.open(self.path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                              dir_fd=self.parent_fd)
            self.inode = _inode(os.fstat(self.fd))
            _need(created_inode is None or self.inode == created_inode, "created export directory changed")
            self.guard()
        except BaseException:
            if created_inode is not None:
                cleanup_fd = None
                try:
                    cleanup_fd = os.open(self.path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                         dir_fd=self.parent_fd)
                    with os.scandir(cleanup_fd) as entries:
                        empty = next(entries, None) is None
                    current = os.stat(self.path.name, dir_fd=self.parent_fd, follow_symlinks=False)
                    if (empty and stat.S_ISDIR(current.st_mode)
                            and created_inode == _inode(current) == _inode(os.fstat(cleanup_fd))):
                        os.rmdir(self.path.name, dir_fd=self.parent_fd)
                except OSError:
                    pass
                finally:
                    if cleanup_fd is not None:
                        os.close(cleanup_fd)
            self.close()
            raise

    def guard(self):
        _need(_inode(self.path.parent.lstat()) == self.parent_inode == _inode(os.fstat(self.parent_fd))
              and self.path.parent.resolve(strict=True) == self.path.parent,
              "export parent changed or became aliased")
        info = self.path.lstat()
        _need(stat.S_ISDIR(info.st_mode) and _inode(info) == self.inode == _inode(os.fstat(self.fd))
              and self.path.resolve(strict=True) == self.path, "export directory changed or became aliased")

    def _name(self, name):
        _need(type(name) is str and name not in ("", ".", "..") and Path(name).name == name
              and "\\" not in name and "\x00" not in name, "single export filename required")
        self.guard()

    def new(self, name):
        self._name(name)
        descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=self.fd)
        self.files[name] = _inode(os.fstat(descriptor))
        return os.fdopen(descriptor, "wb")

    @contextmanager
    def read(self, name, maximum):
        self._name(name)
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
        except OSError as error:
            raise PrimaryGraphExportError("export file is not accessible as a regular input") from error
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                  and 0 < before.st_size <= maximum, "bounded single-link regular export file required")
            try:
                yield stream, before.st_size
            finally:
                self.guard()
                _need(_file_identity(before) == _file_identity(os.fstat(stream.fileno()))
                      == _file_identity(os.stat(name, dir_fd=self.fd, follow_symlinks=False)),
                      "export file changed while reading")

    def remember(self, name):
        self._name(name)
        info = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "owned regular staging file required")
        self.files[name] = _inode(info)

    def names(self, maximum=DEFAULT_LIMITS["max_shards"] + 3):
        self.guard()
        names = set()
        with os.scandir(self.fd) as entries:
            for entry in entries:
                _need(len(names) < maximum, "export directory entry bound exceeded")
                names.add(entry.name)
        return names

    def cleanup(self):
        if not self.created or self.fd is None:
            return
        for name, expected in reversed(tuple(self.files.items())):
            try:
                info = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
                if _inode(info) == expected:
                    os.unlink(name, dir_fd=self.fd)
            except FileNotFoundError:
                pass
        try:
            with os.scandir(self.fd) as entries:
                empty = next(entries, None) is None
            if (_inode(os.stat(self.path.name, dir_fd=self.parent_fd, follow_symlinks=False)) == self.inode
                    and empty):
                os.rmdir(self.path.name, dir_fd=self.parent_fd)
        except FileNotFoundError:
            pass

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        if getattr(self, "parent_fd", None) is not None:
            os.close(self.parent_fd)
            self.parent_fd = None


def _write(directory, name, raw):
    with directory.new(name) as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    directory.guard()
    return {"path": name, "bytes": len(raw), "sha256": _sha(raw)}


def _file_pin(directory, name, maximum):
    digest, count = hashlib.sha256(), 0
    with directory.read(name, maximum) as (stream, size):
        while chunk := stream.read(1024 * 1024):
            count += len(chunk)
            _need(count <= maximum, "export file exceeds byte bound")
            digest.update(chunk)
        _need(count == size, "export file byte count differs")
    return {"path": name, "bytes": count, "sha256": digest.hexdigest()}


def _record(directory, name, maximum):
    with directory.read(name, maximum) as (stream, _size):
        raw = stream.read(maximum + 1)
    _need(len(raw) <= maximum, "transport record exceeds byte bound")
    return _parse(raw), raw


def _lines(directory, name, maximum, line_maximum, expected_pin):
    digest, count = hashlib.sha256(), 0
    with directory.read(name, maximum) as (stream, size):
        while raw := stream.readline(line_maximum + 1):
            _need(len(raw) <= line_maximum, "transport lineage line exceeds byte bound")
            digest.update(raw)
            count += len(raw)
            yield _parse(raw)
        _need(count == size == expected_pin["bytes"] and digest.hexdigest() == expected_pin["sha256"],
              "complete transport stream differs from its independent pin")


def _source_pairs(selection, snapshot_root, expected_selection_sha256, blobs_root, source_limits,
                  directory, reconstruction_report, owners):
    manifests, records, reconstruction, _release = owners
    manifest_limits, _local = reconstruction._limits(source_limits)
    source_rows = manifests.iter_verified_graph_rows(selection, snapshot_root,
        expected_selection_sha256=expected_selection_sha256, blobs_root=blobs_root, limits=manifest_limits)
    candidate_rows = _lines(directory, "reconstructed.jsonl", reconstruction.MAX_OUTPUT_BYTES,
        reconstruction.MAX_LINE_BYTES, {"bytes": reconstruction_report["candidate_bytes"],
                                        "sha256": reconstruction_report["candidate_sha256"]})
    header = next(candidate_rows, None)
    _need(type(header) is dict and header.get("schema") == reconstruction.HEADER_SCHEMA
          and _same(header.get("selection"), selection), "reconstructed source header differs")
    missing, count = object(), 0
    try:
        for observation, row in itertools.zip_longest(source_rows, candidate_rows, fillvalue=missing):
            _need(observation is not missing and row is not missing, "source/candidate population differs")
            envelope = records.decode_primary_graph_record(observation["raw_row"],
                custody=observation["custody"], expected_raw_row_sha256=observation["raw_row_sha256"],
                expected_custody_sha256=observation["custody_sha256"])
            expected = {"global_ordinal": count, "schema": reconstruction.ROW_SCHEMA,
                "family": envelope["family"], "legal_id": envelope["legal_id"],
                "custody": envelope["custody"], "custody_sha256": envelope["custody_sha256"],
                "raw_row_sha256": envelope["raw_row_sha256"], "record_sha256": envelope["record_sha256"],
                "decoder_envelope_sha256": envelope["envelope_sha256"], "original_body": envelope["original_body"],
                "declared_identity": envelope["declared_identity"], "decoder_disposition": envelope["disposition"],
                "decoder_issues": envelope["issues"], "authority": dict(reconstruction.FALSE_AUTHORITY)}
            _need(observation["global_ordinal"] == count and all(_same(row.get(key), value) for key, value in expected.items())
                  and row.get("candidate_row_sha256") == reconstruction._digest(
                      {key: value for key, value in row.items() if key != "candidate_row_sha256"}),
                  "reconstruction row differs from independently verified original")
            yield observation, row, envelope
            count += 1
        _need(count == reconstruction_report["rows"], "complete original population was not retained")
    finally:
        source_rows.close()
        candidate_rows.close()


def _canonical_wrapper(observation, envelope, records, release):
    body = envelope["original_body"]
    encoded = release.canonical_json_bytes(body).decode("utf-8")
    original = observation["raw_row"]
    wrapper = {"entry_cid": original["entry_cid"], "legal_id": original["legal_id"],
               "family": envelope["family"], "record_sha256": _sha(encoded.encode("utf-8")), "record_json": encoded}
    checked = records.decode_primary_graph_payload(wrapper, family=envelope["family"],
        expected_raw_row_sha256=records.raw_row_sha256(wrapper))
    _need(not checked["issues"] and _same(checked["original_body"], body)
          and _same(checked["declared_identity"], envelope["declared_identity"]),
          "canonical encoding changed the original graph body or identities")
    return wrapper


class _Plan:
    def __init__(self, limits):
        self.limits = limits
        self.states = {family: {"index": 0, "rows": 0, "bytes": 0} for family in _FAMILIES}
        self.counts = {family: 0 for family in _FAMILIES}
        self.locations = {}

    def place(self, family, wrapper):
        state, size = self.states[family], len(_wire(wrapper))
        _need(size <= self.limits["max_shard_input_bytes"], "one wrapper exceeds shard input byte bound")
        if state["rows"] and (state["rows"] >= self.limits["rows_per_shard"]
                              or state["bytes"] + size > self.limits["max_shard_input_bytes"]):
            state.update(index=state["index"] + 1, rows=0, bytes=0)
        name = family + "-" + format(state["index"], "06d") + ".parquet"
        if name not in self.locations:
            _need(len(self.locations) < self.limits["max_shards"], "export shard bound exceeded")
            self.locations[name] = {"family": family, "rows": 0}
        location = {"file": name, "row_ordinal": state["rows"]}
        state["rows"] += 1
        state["bytes"] += size
        self.counts[family] += 1
        self.locations[name]["rows"] += 1
        return location


def _lineage_header(selection, report):
    return {"schema": LINEAGE_HEADER_SCHEMA, "source_selection_sha256": selection["selection_sha256"],
            "reconstruction_sha256": report["reconstruction_sha256"], "source_rows": report["rows"],
            "identity_namespace": "primary_entry_cid", "authority": dict(FALSE_AUTHORITY)}


def _lineage_row(observation, candidate, envelope, plan, owners):
    _manifests, records, _reconstruction, release = owners
    wrapper, location, transformation = None, None, None
    if envelope["disposition"] != "unresolved":
        wrapper = _canonical_wrapper(observation, envelope, records, release)
        location = plan.place(envelope["family"], wrapper)
        original = observation["raw_row"]
        transformation = {
            "profile": "canonical-json-encoding-only/v1",
            "record_json_changed": original["record_json"] != wrapper["record_json"],
            "record_sha256_changed": original["record_sha256"] != wrapper["record_sha256"],
            "original_record_sha256": original["record_sha256"],
            "exported_record_sha256": wrapper["record_sha256"],
            "original_raw_row_sha256": observation["raw_row_sha256"],
            "exported_raw_row_sha256": records.raw_row_sha256(wrapper),
        }
    return {"schema": LINEAGE_ROW_SCHEMA, "global_ordinal": observation["global_ordinal"],
            "original_raw_wrapper": observation["raw_row"], "reconstruction_row": candidate,
            "exported_wrapper": wrapper, "export_location": location, "encoding_transformation": transformation,
            "disposition": candidate["disposition"],
            "quarantined": candidate["disposition"] != "proposed_unreviewed_transport"}


def _parquet_rows(directory, descriptor, limits):
    import pyarrow as pa
    import pyarrow.parquet as pq
    with directory.read(descriptor["path"], limits["max_parquet_bytes"]) as (stream, _size):
        parquet = pq.ParquetFile(stream, pre_buffer=False, arrow_extensions_enabled=False,
            thrift_string_size_limit=1024 * 1024, thrift_container_size_limit=100_000)
        _need(tuple(parquet.schema_arrow.names) == _WRAPPER_FIELDS
              and all(field.type == pa.string() for field in parquet.schema_arrow),
              "exact current five-string-field export schema required")
        _need(parquet.metadata.num_rows == descriptor["rows"] <= limits["rows_per_shard"]
              and 0 <= parquet.num_row_groups <= limits["rows_per_shard"], "export shard footer population differs")
        footer_rows = footer_decoded = 0
        for index in range(parquet.num_row_groups):
            group = parquet.metadata.row_group(index)
            _need(group.num_columns == len(_WRAPPER_FIELDS), "export footer column population differs")
            sizes = [group.column(column).total_uncompressed_size for column in range(group.num_columns)]
            _need(all(type(size) is int and size >= 0 for size in sizes), "invalid export footer decoded sizes")
            footer_rows += group.num_rows
            footer_decoded += sum(sizes)
            _need(footer_decoded <= limits["max_shard_input_bytes"], "export footer decoded bytes exceed bound")
        _need(footer_rows == descriptor["rows"], "export footer row groups omit source occurrences")
        decoded = count = 0
        for batch in parquet.iter_batches(batch_size=limits["batch_size"], use_threads=False):
            _need(batch.num_rows <= limits["batch_size"] and batch.nbytes <= limits["max_decoded_batch_bytes"],
                  "export Arrow batch exceeds bound")
            decoded += batch.nbytes
            _need(decoded <= limits["max_shard_input_bytes"], "export shard decoded bytes exceed input envelope bound")
            for row in batch.to_pylist():
                count += 1
                _need(count <= descriptor["rows"], "export shard contains extra rows")
                yield row
        _need(count == descriptor["rows"], "export shard omits rows")


def _strict_wrapper(actual, expected, original_body, family, records):
    _need(_same(actual, expected), "export wrapper differs from independently derived canonical original")
    checked = records.decode_primary_graph_payload(actual, family=family,
        expected_raw_row_sha256=records.raw_row_sha256(actual))
    _need(not checked["issues"] and _same(checked["original_body"], original_body),
          "strict export decode changed original body, roles, ordering or source properties")


def _encoded_originals(rows, family, limits, release):
    _need(0 < len(rows) <= limits["rows_per_shard"]
          and sum(len(_wire(row["wrapper"])) for row in rows) <= limits["max_shard_input_bytes"],
          "complete writer input exceeds row or byte bound")
    bodies = json.loads(_wire([row["body"] for row in rows]))
    before = _wire(bodies)
    encoded = release._encode_parquet_rows(bodies, family=family)
    _need(_wire(bodies) == before, "release writer mutated source bodies")
    _need(type(encoded) is bytes and 0 < len(encoded) <= limits["max_parquet_bytes"],
          "encoded Parquet exceeds byte bound")
    return encoded


def _check_original_shard(directory, descriptor, rows, limits, records, release, encoded=None):
    # A fresh actual writer result is derived from the independently replayed
    # originals, not from the export's own manifest or saved lineage. Refuse
    # altered compressed bytes before asking Arrow to allocate decoded arrays.
    encoded = _encoded_originals(rows, descriptor["family"], limits, release) if encoded is None else encoded
    _need(_file_pin(directory, descriptor["path"], limits["max_parquet_bytes"])
          == {"path": descriptor["path"], "bytes": len(encoded), "sha256": _sha(encoded)},
          "Parquet differs from actual writer replay of independently verified originals")
    actual, missing = _parquet_rows(directory, descriptor, limits), object()
    try:
        for saved, expected in itertools.zip_longest(actual, rows, fillvalue=missing):
            _need(saved is not missing and expected is not missing, "writer/readback row population differs")
            _strict_wrapper(saved, expected["wrapper"], expected["body"], descriptor["family"], records)
    finally:
        actual.close()


def _descriptor(pin, kind, family, rows):
    return {**pin, "kind": kind, "family": family, "rows": rows}


def _manifest(selection, report, plan, descriptors, quarantined, transformations, limits):
    exported = sum(plan.counts.values())
    return {
        "schema": SCHEMA, "profile": PROFILE, "identity_namespace": "primary_entry_cid",
        "source_selection_sha256": selection["selection_sha256"],
        "source_manifest_sha256": selection["manifest_sha256"],
        "repository": selection["repository"], "revision": selection["revision"],
        "source_rows": report["rows"], "exported_rows": exported,
        "lineage_only_rows": report["rows"] - exported, "quarantined_rows": quarantined,
        "family_row_counts": {family: report["family_row_counts"].get(family, 0) for family in _FAMILIES},
        "exported_family_row_counts": plan.counts, "disposition_counts": report["disposition_counts"],
        "structural_endpoint_integrity_passed": report["endpoint_integrity_passed"],
        "encoding_transformation_counts": transformations, "limits": limits,
        "reconstruction_sha256": report["reconstruction_sha256"],
        "files": sorted(descriptors, key=lambda row: row["path"]),
        "view": "candidate_transport_only", "authority": dict(FALSE_AUTHORITY),
    }


def _reconstruct(selection, snapshot_root, expected_selection_sha256, blobs_root, source_limits, directory, reconstruction):
    report = reconstruction.reconstruct_to_jsonl(selection, snapshot_root, directory.path / "reconstructed.jsonl",
        expected_selection_sha256=expected_selection_sha256, blobs_root=blobs_root, limits=source_limits)
    directory.remember("reconstructed.jsonl")
    return report


def _stage_export(selection, snapshot_root, expected_selection_sha256, blobs_root, source_limits, directory, limits, owners):
    _manifests, records, reconstruction, release = owners
    report = _reconstruct(selection, snapshot_root, expected_selection_sha256, blobs_root, source_limits, directory, reconstruction)
    _need(report["rows"] <= limits["max_rows"], "complete source population exceeds export row bound")
    report_raw = _wire(report) + b"\n"
    _need(len(report_raw) <= min(limits["max_manifest_bytes"], limits["max_output_bytes"]),
          "reconstruction companion exceeds byte bound")
    descriptors = [_descriptor(_write(directory, "reconstruction.json", report_raw),
                               "reconstruction", None, report["rows"])]
    plan, buffers = _Plan(limits), {family: [] for family in _FAMILIES}
    active, quarantined = {}, 0
    transformations = {"unchanged": 0, "canonicalized": 0}
    written, companion_bytes = 0, len(report_raw)

    def flush(family):
        nonlocal companion_bytes
        rows = buffers[family]
        if not rows:
            return
        name = active[family]
        encoded = _encoded_originals(rows, family, limits, release)
        _need(companion_bytes + written + len(encoded) <= limits["max_output_bytes"],
              "complete staged export exceeds aggregate byte bound")
        descriptor = _descriptor(_write(directory, name, encoded), "parquet", family, len(rows))
        companion_bytes += len(encoded)
        _check_original_shard(directory, descriptor, rows, limits, records, release, encoded)
        descriptors.append(descriptor)
        buffers[family] = []

    with directory.new("lineage.jsonl") as stream:
        def write_line(value):
            nonlocal written
            raw = _wire(value) + b"\n"
            _need(len(raw) <= limits["max_lineage_line_bytes"]
                  and companion_bytes + written + len(raw) <= limits["max_output_bytes"], "lineage byte bound exceeded")
            stream.write(raw)
            written += len(raw)

        write_line(_lineage_header(selection, report))
        pairs = _source_pairs(selection, snapshot_root, expected_selection_sha256, blobs_root,
                              source_limits, directory, report, owners)
        try:
            for observation, candidate, envelope in pairs:
                row = _lineage_row(observation, candidate, envelope, plan, owners)
                quarantined += int(row["quarantined"])
                if row["exported_wrapper"] is not None:
                    family, name = envelope["family"], row["export_location"]["file"]
                    if family in active and active[family] != name:
                        flush(family)
                    active[family] = name
                    buffers[family].append({"wrapper": row["exported_wrapper"], "body": envelope["original_body"]})
                    changed = row["encoding_transformation"]["record_json_changed"]
                    transformations["canonicalized" if changed else "unchanged"] += 1
                write_line(row)
            for family in _FAMILIES:
                flush(family)
        finally:
            pairs.close()
        stream.flush()
        os.fsync(stream.fileno())
    descriptors.append(_descriptor(_file_pin(directory, "lineage.jsonl", limits["max_output_bytes"]),
                                   "lineage", None, report["rows"]))
    manifest = _manifest(selection, report, plan, descriptors, quarantined, transformations, limits)
    raw = _wire(manifest) + b"\n"
    _need(len(raw) <= limits["max_manifest_bytes"]
          and len(raw) + sum(row["bytes"] for row in descriptors) <= limits["max_output_bytes"],
          "complete export byte bound exceeded")
    return manifest, report


def _check_files(directory, manifest, limits, *, manifest_present):
    _need(set(manifest) == _MANIFEST_FIELDS and manifest["schema"] == SCHEMA and manifest["profile"] == PROFILE
          and _same(manifest["limits"], limits) and _same(manifest["authority"], FALSE_AUTHORITY),
          "closed export manifest/profile/limits/authority differs")
    files = manifest["files"]
    _need(type(files) is list and len(files) <= limits["max_shards"] + 2, "bounded export file population required")
    names, total = set(), 0
    for descriptor in files:
        _need(type(descriptor) is dict and set(descriptor) == _DESCRIPTOR_FIELDS, "closed export file descriptor required")
        name, kind = descriptor["path"], descriptor["kind"]
        _need(type(name) is str and name not in names, "unique export file path required")
        if kind == "parquet":
            _need(descriptor["family"] in _FAMILIES and re.fullmatch(
                descriptor["family"] + r"-[0-9]{6}\.parquet", name), "supported family shard path required")
            maximum = limits["max_parquet_bytes"]
        else:
            _need((kind, name) in (("lineage", "lineage.jsonl"), ("reconstruction", "reconstruction.json"))
                  and descriptor["family"] is None, "unsupported export companion")
            maximum = limits["max_output_bytes"] if kind == "lineage" else limits["max_manifest_bytes"]
        _need(type(descriptor["bytes"]) is int and 0 < descriptor["bytes"] <= maximum
              and type(descriptor["rows"]) is int and 0 <= descriptor["rows"] <= limits["max_rows"]
              and type(descriptor["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", descriptor["sha256"]),
              "bounded export descriptor sizes/count/hash required")
        total += descriptor["bytes"]
        _need(total + len(_wire(manifest)) + 1 <= limits["max_output_bytes"],
              "export descriptor aggregate exceeds byte bound")
        _need(_file_pin(directory, name, maximum) == {key: descriptor[key] for key in ("path", "bytes", "sha256")},
              "export file differs from exact manifest commitment")
        names.add(name)
    _need({"lineage.jsonl", "reconstruction.json"} <= names and files == sorted(files, key=lambda row: row["path"]),
          "complete canonical companion inventory required")
    expected_names = names | ({"manifest.json"} if manifest_present else set())
    _need(directory.names(len(expected_names)) == expected_names and total + len(_wire(manifest)) + 1 <= limits["max_output_bytes"],
          "export has missing/extra files or exceeds aggregate bytes")


def _compare_originals(directory, manifest, selection, snapshot_root, expected_selection_sha256,
                       blobs_root, source_limits, replay_directory, report, limits, owners):
    _manifests, records, _reconstruction, release = owners
    stored_report, _raw = _record(directory, "reconstruction.json", limits["max_manifest_bytes"])
    _need(_same(stored_report, report), "stored reconstruction differs from fresh original replay")
    descriptors = {row["path"]: row for row in manifest["files"]}
    lineage = _lines(directory, "lineage.jsonl", limits["max_output_bytes"],
                     limits["max_lineage_line_bytes"], descriptors["lineage.jsonl"])
    _need(_same(next(lineage, None), _lineage_header(selection, report)), "lineage header differs from fresh original replay")
    plan, active = _Plan(limits), {}
    buffers = {family: [] for family in _FAMILIES}
    transformations, quarantined = {"unchanged": 0, "canonicalized": 0}, 0
    pairs = _source_pairs(selection, snapshot_root, expected_selection_sha256, blobs_root,
                          source_limits, replay_directory, report, owners)
    missing = object()

    def check_shard(family):
        rows = buffers[family]
        if rows:
            name = active[family]
            _need(name in descriptors and descriptors[name]["kind"] == "parquet", "expected export shard missing")
            _check_original_shard(directory, descriptors[name], rows, limits, records, release)
            buffers[family] = []

    try:
        for source, saved in itertools.zip_longest(pairs, lineage, fillvalue=missing):
            _need(source is not missing and saved is not missing, "complete lineage population differs")
            observation, candidate, envelope = source
            expected = _lineage_row(observation, candidate, envelope, plan, owners)
            _need(_same(saved, expected), "lineage differs from independently verified original occurrence")
            quarantined += int(expected["quarantined"])
            if expected["exported_wrapper"] is None:
                continue
            family, name = envelope["family"], expected["export_location"]["file"]
            if active.get(family) != name:
                if family in active:
                    check_shard(family)
                active[family] = name
            buffers[family].append({"wrapper": expected["exported_wrapper"], "body": envelope["original_body"]})
            changed = expected["encoding_transformation"]["record_json_changed"]
            transformations["canonicalized" if changed else "unchanged"] += 1
        for family in _FAMILIES:
            check_shard(family)
        expected_manifest = _manifest(selection, report, plan, manifest["files"], quarantined, transformations, limits)
        _need(_same(manifest, expected_manifest), "export population, encoding or structural claims differ from original replay")
        parquet_descriptors = {name: {"family": row["family"], "rows": row["rows"]}
                               for name, row in descriptors.items() if row["kind"] == "parquet"}
        _need(parquet_descriptors == plan.locations, "export shard population differs from original replay")
        _need(descriptors["lineage.jsonl"]["rows"] == descriptors["reconstruction.json"]["rows"] == report["rows"],
              "companion row counts differ from exact source population")
    finally:
        pairs.close()
        lineage.close()


def _copy(source, destination, descriptor):
    name = descriptor["path"]
    with source.read(name, descriptor["bytes"]) as (reader, size), destination.new(name) as writer:
        copied = 0
        while chunk := reader.read(1024 * 1024):
            copied += len(chunk)
            _need(copied <= descriptor["bytes"], "staged export grew during exclusive publication")
            writer.write(chunk)
        _need(copied == size == descriptor["bytes"], "staged export changed during exclusive publication")
        writer.flush()
        os.fsync(writer.fileno())


def export_primary_graph(selection, snapshot_root, output_directory, *, expected_selection_sha256,
                         blobs_root=None, source_limits=None, limits=None):
    """Export every original occurrence to a NEW candidate generation.

    Source limits delegate unchanged to reconstruction. Export limits only lower
    DEFAULT_LIMITS. Quarantine remains explicit; no structural blocker is waived.
    A finalized manifest appears only after complete original-bound readback.
    max_output_bytes bounds this generation, not reconstruction scratch or
    staging/publication overlap; the native parent reserves that aggregate.
    """
    bounds, owners = _limits(limits), _owners()
    output = _path(output_directory)
    _outside_sources(output, snapshot_root, blobs_root)
    _need(not output.exists() and not output.is_symlink(), "export target exists; overwrite refused")
    selected = json.loads(_wire(selection))
    _need(type(selected.get("selected_row_count")) is int
          and 0 <= selected["selected_row_count"] <= bounds["max_rows"], "complete source rows exceed export bound")
    stage = _Directory(output.parent / (".legal-primary-export-" + secrets.token_hex(16)), create=True)
    destination, success = None, False
    try:
        manifest, report = _stage_export(selected, snapshot_root, expected_selection_sha256,
            blobs_root, source_limits, stage, bounds, owners)
        # Reconstruction is a staging-only source for the independent comparisons.
        companion_names = {row["path"] for row in manifest["files"]}
        _need(stage.names() == companion_names | {"reconstructed.jsonl"}, "unexpected staging files")
        _compare_originals(stage, manifest, selected, snapshot_root, expected_selection_sha256,
                           blobs_root, source_limits, stage, report, bounds, owners)
        destination = _Directory(output, create=True)
        for descriptor in manifest["files"]:
            _copy(stage, destination, descriptor)
        _check_files(destination, manifest, bounds, manifest_present=False)
        _compare_originals(destination, manifest, selected, snapshot_root, expected_selection_sha256,
                           blobs_root, source_limits, stage, report, bounds, owners)
        # Cleanup errors occur before finalization, never after a returned or
        # apparently committed generation. Only unchanged owned inodes unlink.
        stage.cleanup()
        stage.close()
        stage = None
        raw = _wire(manifest) + b"\n"
        _need(len(raw) <= bounds["max_manifest_bytes"], "export manifest exceeds byte bound")
        pin = _write(destination, "manifest.json", raw)
        _check_files(destination, manifest, bounds, manifest_present=True)
        os.fsync(destination.fd)
        os.fsync(destination.parent_fd)
        success = True
        return {"manifest": manifest, "manifest_sha256": pin["sha256"],
                "manifest_bytes": pin["bytes"], "status": "candidate_export_complete"}
    finally:
        if destination is not None:
            if not success:
                destination.cleanup()
            destination.close()
        if stage is not None:
            stage.cleanup()
            stage.close()


def validate_primary_graph_export(output_directory, *, expected_manifest_sha256, selection,
                                  snapshot_root, expected_selection_sha256, blobs_root=None,
                                  source_limits=None, limits=None):
    """Rebuild existing-owner dispositions and compare all original-bound rows.

    The independently expected manifest hash is necessary but insufficient:
    source custody, full lineage and strict exported bodies are freshly replayed.
    Temporary replay writes never mutate the input sources or exported files.
    Exact Parquet byte replay requires the unchanged writer/encoding environment.
    """
    bounds, owners = _limits(limits), _owners()
    _need(type(expected_manifest_sha256) is str and re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha256),
          "independently expected export manifest SHA256 required")
    output = _path(output_directory)
    _outside_sources(output, snapshot_root, blobs_root)
    selected = json.loads(_wire(selection))
    _need(type(selected.get("selected_row_count")) is int
          and 0 <= selected["selected_row_count"] <= bounds["max_rows"], "complete source rows exceed export bound")
    directory = _Directory(output)
    replay = None
    try:
        manifest, raw = _record(directory, "manifest.json", bounds["max_manifest_bytes"])
        _need(_sha(raw) == expected_manifest_sha256, "export manifest differs from independent SHA256")
        _check_files(directory, manifest, bounds, manifest_present=True)
        replay = _Directory(output.parent / (".legal-primary-replay-" + secrets.token_hex(16)), create=True)
        report = _reconstruct(selected, snapshot_root, expected_selection_sha256,
                              blobs_root, source_limits, replay, owners[2])
        _compare_originals(directory, manifest, selected, snapshot_root, expected_selection_sha256,
                           blobs_root, source_limits, replay, report, bounds, owners)
        _check_files(directory, manifest, bounds, manifest_present=True)
        return {"manifest": manifest, "manifest_sha256": expected_manifest_sha256,
                "manifest_bytes": len(raw), "status": "candidate_export_verified",
                "fresh_original_replay_performed": True,
                "structural_endpoint_integrity_passed": report["endpoint_integrity_passed"],
                "authority": dict(FALSE_AUTHORITY)}
    finally:
        if replay is not None:
            replay.cleanup()
            replay.close()
        directory.close()


__all__ = ["PrimaryGraphExportError", "export_primary_graph", "validate_primary_graph_export"]
