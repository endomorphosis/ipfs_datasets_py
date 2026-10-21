"""Bounded saved-parent metadata custody and unresolved grouping preparation.

This reader never opens the declared parent or decodes its source text. Hashes
of source rows, pages and text remain pinned scanner observations. They are not
independent source or semantic verification. This is a distinct immutable type,
not the release USCodeSourceInventory or a training/partition capability.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

from . import legal_parent_parquet_pages as pages

SCHEMA = "legal-parent-source-metadata-inventory/v1"
GROUPING_SCHEMA = "legal-parent-source-grouping-preparation/v1"
SCOPE = "exact_pinned_saved_metadata_package_only"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_REV = re.compile(r"[0-9a-f]{40}\Z")
_IDENTITIES = ("ipfs_cid", "title_number", "section_number")
_AUTHORITY = dict.fromkeys(("source_semantics_verified", "source_authority_authenticated",
    "official_edition_correspondence_verified", "original_producer_occurrence_attested",
    "source_equivalence_proven", "context_permission_verified", "context_closure_verified",
    "source_encoder_authenticated", "global_holdout_verified", "training_qualified",
    "evaluation_gold_qualified", "model_executed", "training_executed", "database_executed",
    "prover_executed", "Lean_admitted", "convergence_proved", "admitted"), False)
_PARENT_FIELDS = {"repository", "revision", "path_in_repo", "local_path", "sha256", "bytes", "row_count", "profile"}
_MANIFEST_FIELDS = {"schema", "profile", "scope", "parent", "parent_descriptor_sha256",
    "preflight_report_sha256", "source_schema", "source_schema_sha256", "content_normalization",
    "limits", "row_count", "shards", "coverage", "all_source_columns_hashed", "raw_rows_stored",
    "source_text_stored", "grouping_metadata_complete", "page_count", "decoded_page_bytes",
    "decoded_page_witnesses", "raw_row_canonical_bytes", "total_metadata_bytes", "disposition_counts",
    "group_id", "split", "inference_view", "authority", "training_mask", "evaluation_gold_mask", "manifest_sha256"}
_ROW_FIELDS = {"physical_section_id", "physical_key", "full_raw_row_sha256", "text",
    "normalized_content_sha256", "observed_identity", "observed_identity_status",
    "observed_identity_evidence", "disposition", "raw_row_canonical_bytes", "group_id", "split",
    "inference_view", "authority", "training_mask", "evaluation_gold_mask"}
_DISPOSITIONS = {"stored_text_available", "empty_text", "missing_text", "unsupported_text_type"}
_EMPTY_SHA = hashlib.sha256(b"").hexdigest()


class ParentSourceMetadataInventoryError(ValueError):
    """Pinned saved metadata, finite bounds or source-only state differs."""


def _need(ok, message):
    if not ok:
        raise ParentSourceMetadataInventoryError(message)


def _integer(value, maximum, minimum=0):
    _need(type(value) is int and minimum <= value <= maximum, "bounded plain integer required")
    return value


def _sha(value):
    _need(type(value) is str and _SHA.fullmatch(value), "literal lowercase SHA256 required")
    return value


def _keys(value, fields, label):
    _need(type(value) is dict and set(value) == set(fields), "closed " + label + " required")


def _wire(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ParentSourceMetadataInventoryError("finite canonical UTF-8 metadata required") from exc


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _plain_snapshot(value, maximum, *, max_nodes=262144):
    """Bound caller objects before serialization, including aliases/cycles."""
    nodes = size = 0
    active = set()
    def visit(item, depth):
        nonlocal nodes, size
        nodes += 1
        _need(nodes <= max_nodes and depth <= 16, "JSON node/depth bound exceeded")
        kind = type(item)
        if kind is str:
            _need(len(item) <= maximum, "string character bound exceeded")
            size += len(item.encode("utf-8"))
            _need(size <= maximum, "aggregate string byte bound exceeded")
            return item
        if kind is int:
            _integer(item, 2**63 - 1, -(2**63))
            return item
        if item is None or kind is bool:
            return item
        _need(kind in (dict, list) and len(item) <= 65536, "plain bounded JSON required")
        identity = id(item)
        _need(identity not in active, "cyclic JSON refused")
        active.add(identity)
        try:
            if kind is list:
                return [visit(child, depth + 1) for child in item]
            result = {}
            for key, child in item.items():
                _need(type(key) is str and len(key) <= 4096, "bounded string JSON key required")
                result[visit(key, depth + 1)] = visit(child, depth + 1)
            return result
        finally:
            active.remove(identity)
    try:
        result = visit(value, 0)
        raw = _wire(result)
    except (UnicodeError, RuntimeError, RecursionError) as exc:
        raise ParentSourceMetadataInventoryError("invalid bounded metadata") from exc
    _need(len(raw) <= maximum, "canonical metadata byte bound exceeded")
    return result, raw


def _parse(raw, maximum):
    _need(type(raw) is bytes and 0 < len(raw) <= maximum, "bounded metadata bytes required")
    def pairs(entries):
        result = {}
        for key, value in entries:
            _need(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    def integer(text):
        _need(len(text) <= 20, "JSON integer width exceeded")
        return _integer(int(text), 2**63 - 1, -(2**63))
    def refused(_):
        raise ParentSourceMetadataInventoryError("noninteger JSON number refused")
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=pairs,
            parse_int=integer, parse_float=refused, parse_constant=refused)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ParentSourceMetadataInventoryError("invalid finite UTF-8 JSON") from exc
    return _plain_snapshot(value, maximum)[0]


@dataclass(frozen=True)
class ParentSourceMetadataInventoryLimits:
    """Lower-only representation ceilings; these are not RSS measurements."""
    max_rows: int = 65536
    max_manifest_bytes: int = 2 * 1024**2
    max_metadata_row_bytes: int = 4096
    max_metadata_shard_bytes: int = 4 * 1024**2
    max_metadata_shards: int = 128
    max_total_package_bytes: int = 384 * 1024**2
    max_retained_summary_bytes: int = 128 * 1024**2
    max_preparation_bytes: int = 64 * 1024**2

    def __post_init__(self):
        for name, maximum in (("max_rows", 65536), ("max_manifest_bytes", 2 * 1024**2),
                ("max_metadata_row_bytes", 4096), ("max_metadata_shard_bytes", 4 * 1024**2),
                ("max_metadata_shards", 128), ("max_total_package_bytes", 384 * 1024**2),
                ("max_retained_summary_bytes", 128 * 1024**2), ("max_preparation_bytes", 64 * 1024**2)):
            _integer(getattr(self, name), maximum, 1)


def _limits_snapshot(value):
    _need(type(value) is ParentSourceMetadataInventoryLimits, "genuine inventory limits required")
    fields = {name: getattr(value, name) for name in ParentSourceMetadataInventoryLimits.__dataclass_fields__}
    checked = ParentSourceMetadataInventoryLimits(**fields)
    return checked, _wire(fields)


def _flags(value):
    _keys(value["authority"], _AUTHORITY, "source authority")
    _need(all(type(item) is bool and item is False for item in value["authority"].values()),
        "source authority promotion refused")
    _need(all(value[key] is None for key in ("group_id", "split", "inference_view")),
        "group/split/inference promotion refused")
    for key in ("training_mask", "evaluation_gold_mask"):
        _integer(value[key], 0)


def _source_only():
    return {"group_id": None, "split": None, "inference_view": None,
        "authority": dict(_AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0}


def _literal(value, maximum, label, *, nonempty=True):
    _need(type(value) is str and len(value) <= maximum, "bounded " + label + " required")
    _need((not nonempty or bool(value.strip())) and len(value.encode("utf-8")) <= maximum,
        "literal " + label + " byte bound exceeded")
    return value


def _relative(value):
    _literal(value, 2048, "relative path")
    _need("\\" not in value and not PurePosixPath(value).is_absolute()
        and all(part not in ("", ".", "..") for part in value.split("/")), "safe literal relative path required")


def _descriptor(value, pin, max_rows):
    _keys(value, _PARENT_FIELDS, "parent descriptor")
    _literal(value["repository"], 256, "repository")
    _need(type(value["revision"]) is str and _REV.fullmatch(value["revision"]), "full source revision required")
    _relative(value["path_in_repo"])
    _literal(value["local_path"], 4096, "declared parent locator")
    _need(Path(value["local_path"]).is_absolute(), "absolute declared parent locator required")
    _sha(value["sha256"])
    _integer(value["bytes"], 512 * 1024**2, 12)
    _integer(value["row_count"], max_rows, 1)
    _need(value["profile"] == "legacy_laws_parquet/v1" and _digest(value) == pin,
        "parent descriptor/profile differs from independent pin")


def _schema(value, expected):
    _need(type(value) is list and 0 < len(value) <= 64, "bounded complete source schema required")
    names = set()
    for index, field in enumerate(value):
        _keys(field, {"index", "name", "path", "kind", "physical_type", "max_definition_level", "max_repetition_level"}, "source field")
        _integer(field["index"], 63)
        name = _literal(field["name"], 4096, "source field name")
        _need(field["index"] == index and name not in names, "source field order or uniqueness differs")
        names.add(name)
        kind = field["kind"]
        _need(kind in ("utf8", "int64", "null", "list_utf8", "list_null"), "unsupported source field kind")
        repeated = kind.startswith("list_")
        physical = 6 if kind in ("utf8", "list_utf8") else 2 if kind == "int64" else 1
        _integer(field["physical_type"], 6)
        _integer(field["max_definition_level"], 3)
        _integer(field["max_repetition_level"], 1)
        path = field["path"]
        _need(type(path) is list and len(path) == (3 if repeated else 1) and path[0] == name,
            "source field path differs")
        for part in path:
            _literal(part, 4096, "source field path segment")
        _need(field["physical_type"] == physical and field["max_definition_level"] == (3 if repeated else 1)
            and field["max_repetition_level"] == int(repeated), "source field physical profile differs")
    _need(_digest(value) == expected, "source schema SHA differs")
    return {field["name"]: field["kind"] for field in value}


def _manifest(value, pins, limits):
    _keys(value, _MANIFEST_FIELDS, "complete metadata manifest")
    _need(value["schema"] == pages.METADATA_SCHEMA and value["profile"] == pages.METADATA_PROFILE
        and value["scope"] == pages.METADATA_SCOPE and value["content_normalization"] == pages.METADATA_NORMALIZATION,
        "unsupported metadata manifest profile")
    _flags(value)
    for name in ("all_source_columns_hashed",):
        _need(value[name] is True, "complete source-column hash observation required")
    for name in ("raw_rows_stored", "source_text_stored", "grouping_metadata_complete"):
        _need(value[name] is False, "unsupported metadata storage or grouping claim")
    _sha(value["manifest_sha256"])
    _need(_digest({key: item for key, item in value.items() if key != "manifest_sha256"}) == value["manifest_sha256"],
        "manifest internal seal differs")
    _sha(value["parent_descriptor_sha256"]); _sha(value["preflight_report_sha256"])
    _need((value["parent_descriptor_sha256"], value["preflight_report_sha256"]) == pins,
        "descriptor/preflight bindings differ from independent pins")
    _descriptor(value["parent"], pins[0], limits.max_rows)
    count = _integer(value["row_count"], limits.max_rows, 1)
    _need(count == value["parent"]["row_count"], "parent/manifest row denominator differs")
    _keys(value["coverage"], {"declared_parent_rows", "replayed_parent_rows", "whole_parent_inventoried"}, "coverage")
    for name in ("declared_parent_rows", "replayed_parent_rows"):
        _need(_integer(value["coverage"][name], limits.max_rows, 1) == count, "complete declared coverage differs")
    _need(value["coverage"]["whole_parent_inventoried"] is True, "whole-parent metadata coverage required")
    _sha(value["source_schema_sha256"])
    kinds = _schema(value["source_schema"], value["source_schema_sha256"])
    scan = value["limits"]
    _keys(scan, pages.ParentMetadataScanLimits.__dataclass_fields__, "scanner limits")
    try:
        scan_limits = pages.ParentMetadataScanLimits(**scan)
    except pages.ParentParquetPagesError as exc:
        raise ParentSourceMetadataInventoryError("scanner limits exceed their profile") from exc
    _need(count <= scan_limits.max_rows, "rows exceed scanner bound")
    witnesses = value["decoded_page_witnesses"]
    page_count = _integer(value["page_count"], 8192, 1)
    _need(type(witnesses) is list and len(witnesses) == page_count, "complete bounded page witnesses required")
    ids, locations, columns, decoded = set(), set(), set(), 0
    for witness in witnesses:
        _keys(witness, {"page_id", "column_index", "offset", "header_sha256", "compressed_body_sha256", "decoded_body_sha256", "uncompressed_bytes"}, "page witness")
        for name in ("page_id", "header_sha256", "compressed_body_sha256", "decoded_body_sha256"):
            _sha(witness[name])
        column = _integer(witness["column_index"], len(kinds) - 1)
        offset = _integer(witness["offset"], value["parent"]["bytes"] - 9, 4)
        _need(witness["page_id"] not in ids and offset not in locations, "duplicate page witness identity/location")
        ids.add(witness["page_id"]); locations.add(offset); columns.add(column)
        decoded += _integer(witness["uncompressed_bytes"], 32 * 1024**2)
    _need(columns == set(range(len(kinds))) and decoded == _integer(value["decoded_page_bytes"], scan_limits.max_total_decoded_page_bytes),
        "page-column coverage or decoded accounting differs")
    _integer(value["raw_row_canonical_bytes"], scan_limits.max_total_canonical_hashed_bytes, 2)
    _integer(value["total_metadata_bytes"], min(limits.max_total_package_bytes, scan_limits.max_total_metadata_package_bytes), 1)
    dispositions = value["disposition_counts"]
    _need(type(dispositions) is dict and set(dispositions) <= _DISPOSITIONS and dispositions, "closed disposition counts required")
    _need(sum(_integer(number, count, 1) for number in dispositions.values()) == count, "disposition denominator differs")
    shards = value["shards"]
    _need(type(shards) is list and 0 < len(shards) <= min(limits.max_metadata_shards, scan_limits.max_metadata_shards), "bounded shard roster required")
    ordinal = total = 0
    for index, shard in enumerate(shards):
        _keys(shard, {"relative_path", "bytes", "sha256", "row_count", "start_ordinal", "end_ordinal"}, "metadata shard")
        _need(shard["relative_path"] == "metadata/part-%06d.jsonl" % index, "exact ordered shard path required")
        _sha(shard["sha256"])
        total += _integer(shard["bytes"], min(limits.max_metadata_shard_bytes, scan_limits.max_metadata_shard_bytes), 1)
        rows = _integer(shard["row_count"], scan_limits.max_rows_per_metadata_shard, 1)
        _need(_integer(shard["start_ordinal"], count) == ordinal and _integer(shard["end_ordinal"], count, 1) == ordinal + rows,
            "shard ordinal gap/overlap")
        ordinal += rows
    _need(ordinal == count and total == value["total_metadata_bytes"], "shard population/byte totals differ")
    return kinds, scan_limits


def _row(value, ordinal, manifest, kinds, scan_limits):
    _keys(value, _ROW_FIELDS, "source metadata row")
    _flags(value)
    parent = manifest["parent"]
    key = value["physical_key"]
    expected = {"repository_id": parent["repository"], "revision": parent["revision"],
        "path_in_repo": parent["path_in_repo"], "artifact_sha256": parent["sha256"],
        "artifact_bytes": parent["bytes"], "parquet_row_index": ordinal}
    _keys(key, expected, "physical source key")
    _integer(key["parquet_row_index"], manifest["row_count"] - 1)
    _integer(key["artifact_bytes"], 512 * 1024**2, 12)
    _need(key == expected and value["physical_section_id"] == "sha256:" + _digest(key),
        "physical identity/order differs")
    _sha(value["full_raw_row_sha256"])
    minimum = 2 + max(0, len(kinds) - 1) + sum(len(_wire(name)) + 1 + (1 if kind == "int64" else 4 if kind == "null" else 2) for name, kind in kinds.items())
    _integer(value["raw_row_canonical_bytes"], 8 * 1024**2, minimum)
    disposition, text, normalized = value["disposition"], value["text"], value["normalized_content_sha256"]
    _need(type(disposition) is str and disposition in _DISPOSITIONS, "unknown source text disposition")
    text_kind = kinds.get("text")
    if disposition in ("stored_text_available", "empty_text"):
        _need(text_kind == "utf8", "text observation conflicts with source field kind")
        _keys(text, {"sha256", "utf8_bytes", "unicode_characters"}, "text metadata")
        _sha(text["sha256"]); _sha(normalized)
        size = _integer(text["utf8_bytes"], 8 * 1024**2)
        chars = _integer(text["unicode_characters"], 8 * 1024**2)
        _need(chars <= size <= 4 * chars and size <= value["raw_row_canonical_bytes"],
            "UTF-8 byte/character/raw-row bounds differ")
        if disposition == "empty_text":
            _need(size == chars == 0 and text["sha256"] == normalized == _EMPTY_SHA,
                "empty text projection differs")
        else:
            _need(size > 0 and chars > 0, "stored text must be nonempty")
    else:
        _need(text is None and normalized is None, "unavailable source text has invented hashes")
        _need(disposition != "unsupported_text_type" or text_kind not in (None, "utf8", "null"),
            "unsupported text disposition conflicts with source kind")
    for name in ("observed_identity", "observed_identity_status", "observed_identity_evidence"):
        _keys(value[name], _IDENTITIES, name)
    for name in _IDENTITIES:
        literal = value["observed_identity"][name]
        status = value["observed_identity_status"][name]
        evidence = value["observed_identity_evidence"][name]
        kind = kinds.get(name)
        _need(status in ("observed_string", "missing", "unsupported_type", "unsupported_size"), "unknown identity status")
        if status == "observed_string":
            _literal(literal, scan_limits.max_identity_literal_bytes, "identity observation", nonempty=False)
            _need(kind == "utf8" and evidence is None, "literal identity/source kind or evidence differs")
        elif status == "unsupported_size":
            _need(literal is None and kind == "utf8", "overlong identity/source kind differs")
            _keys(evidence, {"sha256", "utf8_bytes"}, "overlong identity evidence")
            _sha(evidence["sha256"])
            _integer(evidence["utf8_bytes"], value["raw_row_canonical_bytes"], scan_limits.max_identity_literal_bytes + 1)
        else:
            _need(literal is None and evidence is None, "unavailable identity contains invented value/evidence")
            _need(status != "unsupported_type" or kind not in (None, "utf8", "null"),
                "unsupported identity/source kind differs")
    compact = {name: value[name] for name in ("physical_section_id", "full_raw_row_sha256", "text",
        "normalized_content_sha256", "observed_identity", "observed_identity_status",
        "observed_identity_evidence", "disposition", "raw_row_canonical_bytes")}
    compact["parquet_row_index"] = ordinal
    return _wire(compact)


def _stat_identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _roster(fd, maximum):
    """Refuse surplus directory entries before an unbounded list allocation."""
    names = set()
    with os.scandir(fd) as entries:
        for entry in entries:
            _need(len(names) < maximum and len(entry.name) <= 128,
                "package directory entry count/name bound exceeded")
            names.add(entry.name)
    return names


@contextmanager
def _directory(path):
    fd = None
    try:
        _need(path.resolve(strict=True) == path, "aliased package directory refused")
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        before = _stat_identity(os.fstat(fd))
        _need(stat.S_ISDIR(before[2]) and _stat_identity(path.lstat()) == before, "directory path/FD differs")
        yield fd, before
        _need(_stat_identity(os.fstat(fd)) == before == _stat_identity(path.lstat())
            and path.resolve(strict=True) == path, "package directory changed while reading")
    except (OSError, RuntimeError) as exc:
        raise ParentSourceMetadataInventoryError("saved package directory unavailable or changed") from exc
    finally:
        if fd is not None:
            os.close(fd)


@contextmanager
def _file(directory_fd, directory_path, name, maximum, expected_bytes=None):
    fd = None
    try:
        # The absolute pathname is also visible to the execution owner's input
        # audit. Compare its FD to the held physical directory before any read.
        fd = os.open(directory_path / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        info = os.fstat(fd)
        _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= maximum
            and (expected_bytes is None or info.st_size == expected_bytes), "bounded single-link regular metadata file required")
        before = _stat_identity(info)
        _need(_stat_identity(os.stat(name, dir_fd=directory_fd, follow_symlinks=False)) == before,
            "metadata path/FD differs")
        with os.fdopen(fd, "rb") as stream:
            fd = None
            yield stream, before
            _need(_stat_identity(os.fstat(stream.fileno())) == before
                == _stat_identity(os.stat(name, dir_fd=directory_fd, follow_symlinks=False)),
                "metadata file changed while reading")
    except OSError as exc:
        raise ParentSourceMetadataInventoryError("saved metadata file unavailable or changed") from exc
    finally:
        if fd is not None:
            os.close(fd)


@dataclass(frozen=True, slots=True, init=False, repr=False)
class HistoricalParentSourceInventory:
    """Immutable verified saved metadata; iter_rows returns detached observations."""
    _manifest_raw: bytes
    _rows: tuple
    _summary_raw: bytes
    _limits_raw: bytes
    _ordered_rows_sha256: str

    def __init__(self, *args, **kwargs):
        raise ParentSourceMetadataInventoryError("use the bounded public package loader")

    def __repr__(self):
        return ("HistoricalParentSourceInventory(row_count=" + str(self.row_count)
            + ", manifest_file_sha256=" + repr(self.sha256) + ")")

    @property
    def row_count(self):
        return len(self._rows)

    @property
    def sha256(self):
        return hashlib.sha256(self._manifest_raw).hexdigest()

    @property
    def manifest_file_sha256(self):
        return self.sha256

    @property
    def manifest_canonical_sha256(self):
        return hashlib.sha256(self._manifest_raw[:-1]).hexdigest()

    @property
    def internal_manifest_sha256(self):
        return self.manifest["manifest_sha256"]

    @property
    def manifest(self):
        return _parse(self._manifest_raw, 2 * 1024**2)

    def to_dict(self):
        """A detached bounded summary, not a resident full row roster."""
        return _parse(self._summary_raw, 2 * 1024**2)

    def iter_rows(self):
        parent = self.manifest["parent"]
        for raw in self._rows:
            row = _parse(raw, 4096)
            ordinal = row.pop("parquet_row_index")
            row["physical_key"] = {"repository_id": parent["repository"], "revision": parent["revision"],
                "path_in_repo": parent["path_in_repo"], "artifact_sha256": parent["sha256"],
                "artifact_bytes": parent["bytes"], "parquet_row_index": ordinal}
            row.update(_source_only())
            yield row


def load_parent_source_metadata_inventory_v1(manifest_path, *, expected_manifest_sha256,
        expected_parent_descriptor_sha256, expected_preflight_report_sha256,
        limits=ParentSourceMetadataInventoryLimits()):
    """Verify a sealed saved package; no declared parent/preflight body is opened.

    expected_manifest_sha256 hashes exact canonical UTF-8 file bytes INCLUDING
    one LF. Descriptor and preflight pins bind recorded observations, not live
    source verification. Retained immutable compact summaries have their own
    representation bound; Python allocator/RSS limits belong to the runtime.
    """
    original_limits = limits
    limits, limits_raw = _limits_snapshot(limits)
    pins = (_sha(expected_parent_descriptor_sha256), _sha(expected_preflight_report_sha256))
    _sha(expected_manifest_sha256)
    _need(type(manifest_path) in (str, Path) or isinstance(manifest_path, Path), "literal manifest path required")
    literal_path = _literal(str(manifest_path), 4096, "manifest path")
    path = Path(literal_path)
    _need(path.is_absolute() and path.name == pages.METADATA_MANIFEST_NAME
        and str(path) == str(manifest_path) and ".." not in path.parts,
        "absolute canonical scanner manifest path required")
    root = path.parent
    compact_rows, retained, canonical_total, counts = [], 0, 0, Counter()
    ordered = hashlib.sha256(b"legal-parent-compact-metadata-rows/v1\0")
    snapshots = []
    with _directory(root) as (root_fd, _):
        _need(_roster(root_fd, 2) == {pages.METADATA_MANIFEST_NAME, "metadata"}, "unexpected package root entries")
        with _file(root_fd, root, path.name, limits.max_manifest_bytes) as (stream, manifest_stat):
            raw = stream.read(limits.max_manifest_bytes + 1)
            _need(len(raw) == manifest_stat[4] and hashlib.sha256(raw).hexdigest() == expected_manifest_sha256,
                "external raw manifest pin differs")
            manifest = _parse(raw, limits.max_manifest_bytes)
            _need(_wire(manifest) + b"\n" == raw, "exact canonical manifest plus one LF required")
            kinds, scan_limits = _manifest(manifest, pins, limits)
            _need(len(raw) <= scan_limits.max_manifest_bytes, "manifest exceeds recorded producer bound")
            _need(pages.parent_source_metadata_manifest_sha256(manifest) == hashlib.sha256(raw[:-1]).hexdigest(),
                "public full canonical manifest identity differs")
        snapshots.append((root_fd, path.name, manifest_stat))
        _need(manifest["total_metadata_bytes"] + len(raw) <= min(limits.max_total_package_bytes, scan_limits.max_total_metadata_package_bytes),
            "complete package byte bound exceeded")
        with _directory(root / "metadata") as (data_fd, _):
            expected_names = {shard["relative_path"].split("/")[1] for shard in manifest["shards"]}
            _need(_roster(data_fd, limits.max_metadata_shards) == expected_names, "unexpected/missing metadata shard entries")
            ordinal = 0
            for shard in manifest["shards"]:
                name = shard["relative_path"].split("/")[1]
                maximum = min(limits.max_metadata_shard_bytes, scan_limits.max_metadata_shard_bytes)
                row_maximum = min(limits.max_metadata_row_bytes, scan_limits.max_metadata_row_bytes)
                count = size = 0
                hashed = hashlib.sha256()
                with _file(data_fd, root / "metadata", name, maximum, shard["bytes"]) as (stream, file_stat):
                    while True:
                        line = stream.readline(row_maximum + 1)
                        if not line:
                            break
                        _need(len(line) <= row_maximum and line.endswith(b"\n"), "bounded complete JSONL row required")
                        size += len(line); count += 1
                        _need(size <= shard["bytes"] and count <= shard["row_count"] and ordinal < manifest["row_count"],
                            "shard row/byte denominator exceeded")
                        hashed.update(line)
                        value = _parse(line, row_maximum)
                        _need(_wire(value) + b"\n" == line, "noncanonical metadata row")
                        compact = _row(value, ordinal, manifest, kinds, scan_limits)
                        _need(retained + len(compact) <= limits.max_retained_summary_bytes,
                            "compact immutable metadata bound exceeded")
                        retained += len(compact); compact_rows.append(compact)
                        ordered.update(len(compact).to_bytes(8, "big")); ordered.update(compact)
                        canonical_total += value["raw_row_canonical_bytes"]
                        counts[value["disposition"]] += 1
                        ordinal += 1
                    _need(size == shard["bytes"] and count == shard["row_count"]
                        and ordinal == shard["end_ordinal"] and hashed.hexdigest() == shard["sha256"],
                        "shard hash/population/byte accounting differs")
                snapshots.append((data_fd, name, file_stat))
            _need(ordinal == manifest["row_count"] and canonical_total == manifest["raw_row_canonical_bytes"]
                and dict(counts) == manifest["disposition_counts"], "whole package row/canonical/disposition accounting differs")
            for fd, name, before in snapshots:
                _need(_stat_identity(os.stat(name, dir_fd=fd, follow_symlinks=False)) == before,
                    "previously read package member changed")
            _need(_roster(data_fd, limits.max_metadata_shards) == expected_names, "metadata roster changed while reading")
        _need(_roster(root_fd, 2) == {path.name, "metadata"}, "package roster changed while reading")
        _need(_limits_snapshot(original_limits)[1] == limits_raw, "caller limits changed during package load")
    summary = {"schema": SCHEMA, "scope": SCOPE,
        "manifest": {"path": str(path), "bytes": len(raw), "sha256": expected_manifest_sha256,
            "canonical_sha256": hashlib.sha256(raw[:-1]).hexdigest(), "internal_sha256": manifest["manifest_sha256"]},
        "parent": manifest["parent"], "parent_descriptor_sha256": pins[0], "preflight_report_sha256": pins[1],
        "source_schema": manifest["source_schema"], "source_schema_sha256": manifest["source_schema_sha256"],
        "content_normalization": manifest["content_normalization"], "row_count": len(compact_rows),
        "shard_count": len(manifest["shards"]), "metadata_bytes": manifest["total_metadata_bytes"],
        "retained_summary_bytes": retained, "ordered_compact_rows_sha256": ordered.hexdigest(),
        "disposition_counts": dict(counts), "package_custody_verified": True,
        "current_source_bytes_verified": False, "scanner_row_hashes_independently_recomputed": False,
        "source_text_stored": False, "raw_rows_stored": False, "grouping_metadata_complete": False,
        **_source_only()}
    inventory = object.__new__(HistoricalParentSourceInventory)
    for name, value in (("_manifest_raw", raw), ("_rows", tuple(compact_rows)),
            ("_summary_raw", _plain_snapshot(summary, 2 * 1024**2)[1]), ("_limits_raw", limits_raw),
            ("_ordered_rows_sha256", ordered.hexdigest())):
        object.__setattr__(inventory, name, value)
    _need(_limits_snapshot(original_limits)[1] == limits_raw, "caller limits changed during final inventory assembly")
    return inventory


def prepare_parent_source_grouping_v1(inventory):
    """Retain every physical row's known keys and unresolved obligations.

    No canonical document identity is inferred from literals. There is no
    identity-binding or split-assignment API in this profile. Even a known empty
    source text key cannot establish document lineage or scientific eligibility.
    """
    _need(type(inventory) is HistoricalParentSourceInventory, "distinct verified saved inventory required")
    limits_data = _parse(inventory._limits_raw, 4096)
    limits, limits_raw = _limits_snapshot(ParentSourceMetadataInventoryLimits(**limits_data))
    _need(type(inventory._rows) is tuple and 0 < len(inventory._rows) <= limits.max_rows,
        "bounded immutable inventory population required")
    summary = inventory.to_dict()
    _need(summary["row_count"] == inventory.row_count and summary["manifest"]["sha256"] == inventory.sha256,
        "inventory summary identity differs")
    rows, blockers, available = [], Counter(), Counter(document=0, exact_text_sha256=0, normalized_content_sha256=0)
    ordered = hashlib.sha256(b"legal-parent-compact-metadata-rows/v1\0")
    retained = 0
    # Charge each complete row wire before appending; final top-level framing is
    # also bounded. This bounds representation bytes, not Python resident memory.
    row_bytes = 0
    for ordinal, raw in enumerate(inventory._rows):
        _need(type(raw) is bytes and 0 < len(raw) <= limits.max_metadata_row_bytes,
            "bounded immutable row summary required")
        retained += len(raw)
        _need(retained <= limits.max_retained_summary_bytes, "immutable summary bound exceeded")
        ordered.update(len(raw).to_bytes(8, "big")); ordered.update(raw)
        source = _parse(raw, limits.max_metadata_row_bytes)
        _need(source["parquet_row_index"] == ordinal, "immutable row order differs")
        text_sha = None if source["text"] is None else source["text"]["sha256"]
        normalized = source["normalized_content_sha256"]
        unresolved = ["document_identity_unresolved"]
        if text_sha is None:
            unresolved.append("exact_text_unavailable")
        else:
            available["exact_text_sha256"] += 1
        if normalized is None:
            unresolved.append("normalized_content_unavailable")
        else:
            available["normalized_content_sha256"] += 1
        blockers.update(unresolved)
        row = {"physical_section_id": source["physical_section_id"], "parquet_row_index": ordinal,
            "full_raw_row_sha256": source["full_raw_row_sha256"], "disposition": source["disposition"],
            "keys": {"document": None, "exact_text_sha256": text_sha, "normalized_content_sha256": normalized},
            "opaque_cid_observation": source["observed_identity"]["ipfs_cid"], "blockers": unresolved,
            "group_id": None, "split": None, "inference_view": None, "training_mask": 0, "evaluation_gold_mask": 0}
        row_bytes += len(_wire(row)) + 1
        _need(row_bytes <= limits.max_preparation_bytes, "complete preparation row roster exceeds byte bound")
        rows.append(row)
    _need(ordered.hexdigest() == inventory._ordered_rows_sha256 == summary["ordered_compact_rows_sha256"]
        and retained == summary["retained_summary_bytes"], "immutable row summaries changed")
    report = {"schema": GROUPING_SCHEMA, "scope": SCOPE, "inventory_sha256": inventory.sha256,
        "manifest_canonical_sha256": inventory.manifest_canonical_sha256,
        "parent_descriptor_sha256": summary["parent_descriptor_sha256"],
        "preflight_report_sha256": summary["preflight_report_sha256"], "row_count": len(rows), "rows": rows,
        "key_availability_counts": dict(available), "blocker_counts": dict(blockers),
        "all_required_keys_available": False, "complete_source_partitions_constructed": False,
        "canonical_document_identity_inferred": False, "alias_referents_verified": False,
        "current_source_bytes_verified": False, "scientific_training_eligibility_established": False,
        **_source_only()}
    body = _plain_snapshot(report, limits.max_preparation_bytes, max_nodes=4_000_000)[1]
    report["preparation_sha256"] = hashlib.sha256(body).hexdigest()
    _need(len(_wire(report)) <= limits.max_preparation_bytes and inventory._limits_raw == limits_raw,
        "final preparation byte/limit identity differs")
    return report


def parent_source_grouping_sha256(report):
    """Whole canonical report digest INCLUDING its internal preparation seal."""
    return hashlib.sha256(_plain_snapshot(report, 64 * 1024**2, max_nodes=4_000_000)[1]).hexdigest()


__all__ = ["SCHEMA", "GROUPING_SCHEMA", "SCOPE", "ParentSourceMetadataInventoryError",
    "ParentSourceMetadataInventoryLimits", "HistoricalParentSourceInventory",
    "load_parent_source_metadata_inventory_v1", "prepare_parent_source_grouping_v1",
    "parent_source_grouping_sha256"]
