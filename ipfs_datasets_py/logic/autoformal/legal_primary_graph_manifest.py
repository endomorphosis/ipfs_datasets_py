"""Manifest-selected primary KG custody and guarded bounded row transport.

Membership comes from the independently pinned release manifest, never a prefix
glob. Extra retained graph files are inventoried separately, without decoding
or assigning them to this release. Bytes, schemas and populations confer no
legal meaning, review, source currentness or Lean admission. No network or cache
mutation is performed. Optional Arrow imports occur only during file access.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat

SCHEMA = "legal-primary-graph-manifest-selection/v1"
VERIFICATION_SCHEMA = "legal-primary-graph-files-verification/v1"
ROW_SCHEMA = "legal-primary-graph-verified-row/v1"
FIELDS = ("entry_cid", "legal_id", "family", "record_sha256", "record_json")
GRAPH_FAMILIES = {"graph_nodes": ("nodes", "uscode-graph-node/v1"),
                  "graph_edges": ("edges", "uscode-graph-edge/v1")}
RELEASE_FIELDS = ("release_profile", "release_point", "release_root_cid", "source_revision",
                  "manifest_digest", "graph_ontology_version", "producer")
DESCRIPTOR_FIELDS = {"family", "first_key", "last_key", "media_type", "relative_path", "row_count",
                     "schema_id", "sha256", "size_bytes"}
FAMILIES = {*GRAPH_FAMILIES, "receipt", "report", "release_metadata", "manifest", "corpus", "recovery",
            "bm25_documents", "bm25_postings", "vectors", "centroids", "routing_index",
            "graph_adjacency_out", "graph_adjacency_in"}
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_DESCRIPTORS = 8192
DEFAULT_LIMITS = {"max_files": 128, "max_rows": 1_000_000, "max_file_bytes": 32 * 1024 * 1024,
    "max_total_file_bytes": 256 * 1024 * 1024, "max_row_group_bytes": 32 * 1024 * 1024,
    "max_decoded_bytes": 1024 * 1024 * 1024, "batch_size": 512, "max_batch_bytes": 8 * 1024 * 1024,
    "max_row_bytes": 128 * 1024, "max_extra_files": 2048}
FALSE_AUTHORITY = dict.fromkeys(("admitted", "formalized", "source_semantics_verified",
    "source_currentness_verified", "global_consistency_verified", "proof_authority", "training_qualified"), False)
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_REVISION = re.compile(r"[0-9a-f]{40}\Z")
_REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


class PrimaryGraphManifestError(ValueError):
    """Pinned release membership, file custody or an explicit bound disagrees."""


def require(ok, message):
    if not ok:
        raise PrimaryGraphManifestError(message)


def wire(value):
    count = 0
    def visit(item, depth):
        nonlocal count
        count += 1
        require(depth <= 40 and count <= 262144, "primary JSON depth/node bound exceeded")
        if type(item) is dict:
            require(all(type(key) is str for key in item), "plain primary JSON string keys required")
            for child in item.values(): visit(child, depth + 1)
        elif type(item) is list:
            for child in item: visit(child, depth + 1)
        else:
            require(item is None or type(item) in (str, bool, int, float), "plain primary JSON required")
            if type(item) is float: require(math.isfinite(item), "finite primary JSON required")
    visit(value, 0)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise PrimaryGraphManifestError("finite UTF8 primary JSON required") from error
    require(len(raw) <= MAX_JSON_BYTES, "primary JSON byte bound exceeded")
    return raw


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


def _closed(value, fields, label):
    require(type(value) is dict and set(value) == set(fields), "closed " + label + " required")


def _sha(value):
    require(type(value) is str and _SHA.fullmatch(value), "exact primary SHA256 required")


def _text(value, label):
    require(type(value) is str and 0 < len(value) <= 8192 and value.strip() and "\x00" not in value,
            "bounded " + label + " required")


def _integer(value, maximum, label, minimum=0):
    require(type(value) is int and minimum <= value <= maximum, "bounded exact " + label + " required")


def _relative(value):
    _text(value, "repository path")
    path = PurePosixPath(value)
    require(not path.is_absolute() and path.parts and all(part not in (".", "..") for part in path.parts)
            and path.as_posix() == value and "\\" not in value, "canonical safe repository path required")
    return path


def _parse(raw):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_MANIFEST_BYTES, "bounded exact raw manifest bytes required")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate manifest JSON key")
            result[key] = value
        return result
    def nonfinite(_): raise PrimaryGraphManifestError("nonfinite manifest constant")
    try: value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=nonfinite)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise PrimaryGraphManifestError("strict UTF8 manifest JSON required") from error
    require(type(value) is dict, "manifest object required")
    wire(value)
    return value


def select_primary_graph_manifest(raw_bytes, *, expected_manifest_sha256, repository, revision,
                                  expected_release_identity, expected_graph_population):
    """Select exact descriptors under independent raw/release/population pins.

    The supported producer hashes sorted compact UTF8 JSON of the complete
    manifest body before adding ``manifest_digest``. That digest is recomputed;
    the release root CID is only declared and pinned, never recomputed here.
    Unknown top-level metadata is retained, not treated as authority.
    """
    _sha(expected_manifest_sha256)
    require(type(repository) is str and _REPOSITORY.fullmatch(repository)
            and type(revision) is str and _REVISION.fullmatch(revision), "immutable repository/revision required")
    manifest = _parse(raw_bytes)
    require(hashlib.sha256(raw_bytes).hexdigest() == expected_manifest_sha256, "independent raw manifest pin differs")
    require(manifest.get("schema_version") == "uscode-sparse-graphrag-release-schema-v2"
            and manifest.get("hf_release_schema_version") == "uscode-hf-release/v1"
            and manifest.get("release_profile") == "publicus-ir-graphrag/v2", "unsupported primary release schema/profile")
    _closed(expected_release_identity, RELEASE_FIELDS, "expected primary release identity")
    for key, value in expected_release_identity.items():
        _text(value, "release " + key)
        require(manifest.get(key) == value, "independent release identity differs: " + key)
    require(_REVISION.fullmatch(manifest["source_revision"])
            and manifest["producer"] == "uscode_hf_release.py"
            and manifest["graph_ontology_version"] == "uscode-legal-graph-ontology/v1",
            "unsupported primary producer, source revision or ontology version")
    require(manifest.get("dataset_repo_id") == repository, "primary repository binding differs")
    _sha(manifest["manifest_digest"])
    body = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    require(digest(body) == manifest["manifest_digest"], "producer pre-self-field manifest digest differs")
    _closed(expected_graph_population, GRAPH_FAMILIES, "expected graph population")
    for value in expected_graph_population.values():
        _closed(value, {"files", "rows"}, "expected graph family population")
        _integer(value["files"], DEFAULT_LIMITS["max_files"], "expected graph files")
        _integer(value["rows"], DEFAULT_LIMITS["max_rows"], "expected graph rows")
    artifacts = manifest.get("artifacts")
    require(type(artifacts) is list and 0 < len(artifacts) <= MAX_DESCRIPTORS, "bounded complete artifact descriptors required")
    selected, seen = [], set()
    for descriptor in artifacts:
        _closed(descriptor, DESCRIPTOR_FIELDS, "primary artifact descriptor")
        path = descriptor["relative_path"]; _relative(path)
        require(path not in seen, "duplicate manifest descriptor path")
        seen.add(path)
        require(descriptor["family"] in FAMILIES, "unsupported manifest descriptor family")
        _sha(descriptor["sha256"])
        _integer(descriptor["size_bytes"], 1 << 40, "descriptor file bytes", minimum=1)
        _integer(descriptor["row_count"], 1 << 40, "descriptor rows")
        for name in ("media_type", "schema_id"): _text(descriptor[name], "descriptor " + name)
        for name in ("first_key", "last_key"):
            if descriptor[name] is not None: _text(descriptor[name], name)
        family = descriptor["family"]
        if family in GRAPH_FAMILIES:
            directory, schema = GRAPH_FAMILIES[family]
            _integer(descriptor["row_count"], 4096, "supported graph shard rows")
            require(re.fullmatch(r"data/graph/" + directory + r"/part-[0-9]{6}\.parquet", path)
                    and descriptor["schema_id"] == schema
                    and descriptor["media_type"] == "application/vnd.apache.parquet",
                    "unsupported graph descriptor path/schema/media type")
            selected.append(descriptor)
        else:
            require(not path.startswith("data/graph/nodes/") and not path.startswith("data/graph/edges/"),
                    "graph path cannot hide under a different artifact family")
    population = {family: {"files": sum(row["family"] == family for row in selected),
                          "rows": sum(row["row_count"] for row in selected if row["family"] == family)}
                  for family in GRAPH_FAMILIES}
    require(wire(population) == wire(expected_graph_population) and selected,
            "independent graph descriptor population differs")
    result = {"schema": SCHEMA, "repository": repository, "revision": revision,
        "manifest_sha256": expected_manifest_sha256, "raw_manifest_utf8": raw_bytes.decode("utf-8"),
        "manifest": manifest, "expected_release_identity": expected_release_identity,
        "expected_graph_population": expected_graph_population, "descriptors": selected,
        "selected_file_count": len(selected), "selected_row_count": sum(row["row_count"] for row in selected),
        "producer_manifest_digest_verified": True, "release_root_cid_recomputed": False,
        "descriptor_key_ranges_verified": False,
        "membership_policy": "exact_graph_descriptors_only", "authority": dict(FALSE_AUTHORITY)}
    result = json.loads(wire(result))
    return {**result, "selection_sha256": digest(result)}


def _selection(selection, expected_selection_sha256):
    _sha(expected_selection_sha256)
    require(type(selection) is dict and selection.get("selection_sha256") == expected_selection_sha256,
            "independent selection pin differs")
    expected = select_primary_graph_manifest(selection["raw_manifest_utf8"].encode(),
        expected_manifest_sha256=selection["manifest_sha256"], repository=selection["repository"],
        revision=selection["revision"], expected_release_identity=selection["expected_release_identity"],
        expected_graph_population=selection["expected_graph_population"])
    require(wire(selection) == wire(expected), "selection differs from complete pinned manifest regeneration")
    return expected


def _limits(limits):
    if limits is None: return dict(DEFAULT_LIMITS)
    require(type(limits) is dict and set(limits) <= set(DEFAULT_LIMITS), "unknown primary file/row limit")
    value = {**DEFAULT_LIMITS, **limits}
    for key, maximum in DEFAULT_LIMITS.items(): _integer(value[key], maximum, key, minimum=1)
    return value


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def _directory(path):
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and not path.is_symlink() and path.resolve() == path,
            "primary source directory is aliased")
    return _identity(info)


def _roots(selection, snapshot_root, blobs_root):
    root = Path(snapshot_root).absolute(); _directory(root)
    blobs = None
    if blobs_root is not None:
        blobs = Path(blobs_root).absolute(); _directory(blobs)
        owner = root.parent.parent
        require(root.parent.name == "snapshots" and root.name == selection["revision"]
                and owner.name == "datasets--" + selection["repository"].replace("/", "--")
                and blobs == owner / "blobs", "blob root is not this pinned cache repository")
    return root, blobs


def _leaf(root, relative, blobs, expected_sha256=None):
    path = root.joinpath(*_relative(relative).parts)
    directories = []
    parent = path.parent
    while True:
        require(parent.is_relative_to(root), "source directory escaped snapshot")
        directories.append((parent, _directory(parent)))
        if parent == root: break
        parent = parent.parent
    before = path.lstat()
    if stat.S_ISLNK(before.st_mode):
        require(blobs is not None, "source file link requires explicit same-repository blob root")
        target = Path(os.path.abspath(path.parent / os.readlink(path)))
        require(target.parent == blobs and _SHA.fullmatch(target.name)
                and (expected_sha256 is None or target.name == expected_sha256), "source link escaped exact same-repository blob")
        directories.append((blobs, _directory(blobs)))
        kind, blob_sha = "same_repo_blob_link", target.name
    else:
        target, kind, blob_sha = path, "regular_file", None
    target_info = target.lstat()
    require(stat.S_ISREG(target_info.st_mode) and target_info.st_nlink == 1
            and target.resolve() == target, "primary source target is not an unaliased regular file")
    return path, target, before, target_info, directories, kind, blob_sha


def _guard(path, target, before, target_info, directories):
    require(_identity(path.lstat()) == _identity(before)
            and _identity(target.lstat()) == _identity(target_info), "primary source file changed or was replaced")
    for directory, identity in directories:
        require(_directory(directory) == identity, "primary source parent directory changed")
    if stat.S_ISLNK(before.st_mode):
        require(Path(os.path.abspath(path.parent / os.readlink(path))) == target, "primary blob link changed")


def _hash(stream, maximum):
    stream.seek(0); result, total = hashlib.sha256(), 0
    while raw := stream.read(min(1024 * 1024, maximum - total + 1)):
        total += len(raw); require(total <= maximum, "primary file exceeds byte bound")
        result.update(raw)
    return result.hexdigest()


@contextmanager
def _verified_file(root, blobs, descriptor, limits):
    import pyarrow as pa
    import pyarrow.parquet as pq

    path, target, before, target_info, directories, _, _ = _leaf(root, descriptor["relative_path"], blobs, descriptor["sha256"])
    require(target_info.st_size == descriptor["size_bytes"] <= limits["max_file_bytes"], "primary descriptor file size differs or exceeds bound")
    fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        require(_identity(os.fstat(stream.fileno())) == _identity(target_info), "primary descriptor changed before open")
        _guard(path, target, before, target_info, directories)
        require(_hash(stream, limits["max_file_bytes"]) == descriptor["sha256"], "primary body SHA256 differs")
        _guard(path, target, before, target_info, directories)
        require(_identity(os.fstat(stream.fileno())) == _identity(target_info), "primary file changed during initial hash")
        stream.seek(0); parquet = None
        try:
            parquet = pq.ParquetFile(stream, pre_buffer=False, thrift_string_size_limit=1024 * 1024,
                                     thrift_container_size_limit=100_000)
            schema, metadata = parquet.schema_arrow, parquet.metadata
            require(tuple(schema.names) == FIELDS and all(field.type == pa.string() for field in schema),
                    "exact five-string primary graph wrapper schema required")
            require(metadata.num_rows == descriptor["row_count"] and metadata.num_row_groups <= 4096,
                    "primary footer row count differs or group bound exceeded")
            groups, start, expanded = [], 0, 0
            for index in range(metadata.num_row_groups):
                group = metadata.row_group(index)
                size = sum(group.column(i).total_uncompressed_size for i in range(group.num_columns))
                require(size >= 0 and all(group.column(i).total_uncompressed_size >= 0 for i in range(group.num_columns))
                        and size <= limits["max_row_group_bytes"], "primary footer row group decoded bound exceeded")
                groups.append({"row_group": index, "start_ordinal": start, "rows": group.num_rows,
                               "footer_uncompressed_bytes": size})
                start += group.num_rows; expanded += size
            require(start == descriptor["row_count"] and expanded <= limits["max_decoded_bytes"],
                    "primary footer population or decoded bound differs")
            info = {"family": descriptor["family"], "relative_path": descriptor["relative_path"],
                "sha256": descriptor["sha256"], "bytes": descriptor["size_bytes"], "row_count": descriptor["row_count"],
                "schema_sha256": hashlib.sha256(schema.serialize().to_pybytes()).hexdigest(), "row_groups": groups}
            yield parquet, info
        except pa.ArrowException as error:
            raise PrimaryGraphManifestError("primary graph Parquet decoding failed") from error
        finally:
            try:
                require(_identity(os.fstat(stream.fileno())) == _identity(target_info), "primary file changed during traversal")
                _guard(path, target, before, target_info, directories)
                require(_hash(stream, limits["max_file_bytes"]) == descriptor["sha256"], "primary body changed during traversal")
                _guard(path, target, before, target_info, directories)
                require(_identity(os.fstat(stream.fileno())) == _identity(target_info), "primary source changed during final hash")
            finally:
                if parquet is not None: parquet.close()


def _extras(selection, root, blobs, limits):
    selected = {row["relative_path"] for row in selection["descriptors"]}
    rows, observed = [], 0
    for directory in ("data/graph/nodes", "data/graph/edges"):
        parent = root / directory
        _directory(parent)
        entries = []
        for path in parent.iterdir():
            observed += 1
            require(observed <= len(selected) + limits["max_extra_files"], "extra source file inventory bound exceeded")
            entries.append(path)
        for path in sorted(entries):
            relative = path.relative_to(root).as_posix()
            if relative in selected: continue
            require(len(rows) < limits["max_extra_files"], "extra source file inventory bound exceeded")
            require(not path.is_dir(), "unsupported nested extra graph source directory")
            original, target, before, info, parents, kind, blob_sha = _leaf(root, relative, blobs)
            _guard(original, target, before, info, parents)
            rows.append({"relative_path": relative, "kind": kind, "bytes": info.st_size,
                         "blob_sha256_or_null": blob_sha, "body_hash_verified": False})
    return rows


def _prepare(selection, snapshot_root, expected_selection_sha256, blobs_root, limits):
    selection = _selection(selection, expected_selection_sha256); bounds = _limits(limits)
    require(selection["selected_file_count"] <= bounds["max_files"] and selection["selected_row_count"] <= bounds["max_rows"]
            and sum(row["size_bytes"] for row in selection["descriptors"]) <= bounds["max_total_file_bytes"],
            "selected primary file/population total bound exceeded")
    root, blobs = _roots(selection, snapshot_root, blobs_root)
    return selection, root, blobs, bounds


def verify_primary_graph_files(selection, snapshot_root, *, expected_selection_sha256, blobs_root=None, limits=None):
    """Body-hash every selected file and verify schema/footer; inventory extras."""
    selection, root, blobs, bounds = _prepare(selection, snapshot_root, expected_selection_sha256, blobs_root, limits)
    extras = _extras(selection, root, blobs, bounds); files, expanded = [], 0
    for index, descriptor in enumerate(selection["descriptors"]):
        with _verified_file(root, blobs, descriptor, bounds) as (_, info):
            expanded += sum(row["footer_uncompressed_bytes"] for row in info["row_groups"])
            require(expanded <= bounds["max_decoded_bytes"], "cumulative primary footer decoded bound exceeded")
            files.append({"descriptor_index": index, **info})
    require(wire(extras) == wire(_extras(selection, root, blobs, bounds)), "extra source inventory changed during verification")
    report = {"schema": VERIFICATION_SCHEMA, "selection_sha256": selection["selection_sha256"],
        "manifest_sha256": selection["manifest_sha256"], "repository": selection["repository"], "revision": selection["revision"],
        "local_filesystem_paths_retained": False,
        "selected_file_count": len(files), "selected_row_count": sum(row["row_count"] for row in files),
        "files": files, "extra_file_count": len(extras), "extras": extras, "limits": bounds,
        "descriptor_key_ranges_verified": False,
        "status": "complete_selected_file_custody_verified", "authority": dict(FALSE_AUTHORITY)}
    return {**report, "verification_sha256": digest(report)}


def iter_verified_graph_rows(selection, snapshot_root, *, expected_selection_sha256, blobs_root=None, limits=None):
    """Yield exact wrapper rows; exhaust for guarded complete stream traversal.

    ``custody.row_ordinal`` is per-file; ``global_ordinal`` is across the selected
    descriptor order. Individual rows never claim that later files were read.
    The iterator hashes each complete file before yielding and rehashes on exit.
    """
    selection, root, blobs, bounds = _prepare(selection, snapshot_root, expected_selection_sha256, blobs_root, limits)
    global_ordinal, decoded, footer_expanded = 0, 0, 0
    for index, descriptor in enumerate(selection["descriptors"]):
        with _verified_file(root, blobs, descriptor, bounds) as (parquet, info):
            footer_expanded += sum(row["footer_uncompressed_bytes"] for row in info["row_groups"])
            require(footer_expanded <= bounds["max_decoded_bytes"], "cumulative primary footer decoded bound exceeded")
            ordinal = 0
            for group in info["row_groups"]:
                local = 0
                for batch in parquet.iter_batches(batch_size=bounds["batch_size"], row_groups=[group["row_group"]], use_threads=False):
                    require(batch.num_rows <= bounds["batch_size"] and batch.nbytes <= bounds["max_batch_bytes"], "primary Arrow batch bound exceeded")
                    decoded += batch.nbytes; require(decoded <= bounds["max_decoded_bytes"], "primary cumulative Arrow decoded bound exceeded")
                    for raw_row in batch.to_pylist():
                        require(type(raw_row) is dict and tuple(raw_row) == FIELDS and ordinal < descriptor["row_count"], "primary decoded row population/schema differs")
                        raw = wire(raw_row); require(len(raw) <= bounds["max_row_bytes"], "primary canonical row byte bound exceeded")
                        custody = {"repository": selection["repository"], "revision": selection["revision"],
                            "manifest_sha256": selection["manifest_sha256"], "selection_sha256": selection["selection_sha256"],
                            "release_root_cid": selection["expected_release_identity"]["release_root_cid"],
                            "source_revision": selection["expected_release_identity"]["source_revision"], "family": descriptor["family"],
                            "shard_path": descriptor["relative_path"], "file_sha256": descriptor["sha256"], "file_bytes": descriptor["size_bytes"],
                            "file_row_count": descriptor["row_count"], "row_ordinal": ordinal,
                            "row_group": group["row_group"], "row_group_ordinal": local}
                        yield {"global_ordinal": global_ordinal, "descriptor_index": index, "raw_row": raw_row, "custody": custody,
                            "raw_row_sha256": hashlib.sha256(raw).hexdigest(), "custody_sha256": digest(custody),
                            "status": "verified_primary_graph_transport_observation", "authority": dict(FALSE_AUTHORITY)}
                        ordinal += 1; local += 1; global_ordinal += 1
                require(local == group["rows"], "primary decoded row-group population differs")
            require(ordinal == descriptor["row_count"], "primary decoded file population differs")
    require(global_ordinal == selection["selected_row_count"], "primary decoded selected population differs")


__all__ = ["PrimaryGraphManifestError", "select_primary_graph_manifest", "verify_primary_graph_files",
           "iter_verified_graph_rows", "digest", "wire"]
