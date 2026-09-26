"""Bounded lossless native multiview reports, independently bound to targets.

This separate format does not change target snapshot/bundle v1. Native report
graphs use postorder nodes and backward references, preserving container and
dataclass sharing without allowing cycles or executable object reconstruction.
Repeated long strings use a bounded value table; immutable string identity is
not part of the format. Positional v3 framing retains v1/v2 reader compatibility.
Targets derive from those same report objects; their identities use the exact
unchanged target codec. Integrity is not producer authentication or admission.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
import hashlib
import math
import os
from pathlib import Path
import struct
import time
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence
import uuid
import zlib

from ipfs_datasets_py.logic.bridge.multiview import MultiViewLegalIRReport
from ipfs_datasets_py.logic.bridge.types import (
    BridgeEvaluationReport, LegalIRDocument, LogicIRView, RoundTripMetrics,
    ProofGateResult, GraphProjectionResult,
)
from . import legal_ir_target_bundle as _io
from .legal_ir_target_snapshot import (
    DEFAULT_MAX_BYTES, TargetSnapshotConfig, TargetSnapshotError,
    _digest, _encode as _encode_target, _hash, _json, _parse, _sample_payload,
    _sha, _validate_target,
)

SCHEMA_VERSION = "legal-ir-report-bundle-v1"
DAG_SCHEMA_VERSION = "legal-ir-native-report-dag-v3"
_DAG_V1 = "legal-ir-native-report-dag-v1"
_DAG_V2 = "legal-ir-native-report-dag-v2"
MAGIC = b"LIRRB01\n"
_HEADER = struct.Struct(">8sQ")
DEFAULT_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_SHARD_BYTES = 64 * 1024 * 1024
MAX_NODES = 1_000_000
MAX_DEPTH = 100
MAX_STRINGS = 1_000_000
_MIN_STRING_LENGTH = 64
# Native report methods and the unchanged target codec traverse shared values
# as trees. Bound that amplification before calling either, as well as DAG bytes.
MAX_EXPANDED_GRAPH_BYTES = DEFAULT_MAX_BYTES
_CODEC = "zlib:" + DAG_SCHEMA_VERSION
_CODECS = {"zlib:" + version: version for version in (_DAG_V1, _DAG_V2, DAG_SCHEMA_VERSION)}
_NULL_SHA256 = _digest(None)
_MISSING_STATUSES = frozenset({"timeout", "failed", "unavailable", "unsupported"})
STATUSES = _MISSING_STATUSES | {"ready", "partial"}
_CLASSES = {cls.__name__: cls for cls in (
    MultiViewLegalIRReport, BridgeEvaluationReport, LegalIRDocument, LogicIRView,
    RoundTripMetrics, ProofGateResult, GraphProjectionResult,
)}
_FIELDS = {name: tuple(field.name for field in fields(cls)) for name, cls in _CLASSES.items()}
_NODE_TYPES = ("dict", "list", "tuple", "MultiViewLegalIRReport", "BridgeEvaluationReport",
               "GraphProjectionResult", "LegalIRDocument", "LogicIRView", "ProofGateResult", "RoundTripMetrics")
_NODE_TAGS = {kind: index for index, kind in enumerate(_NODE_TYPES)}
# Declared by code, never supplied by the artifact or used for dynamic imports.
_POSITIONAL_SCHEMA_SHA256 = _digest({"node_types": list(_NODE_TYPES),
                                    "fields": {kind: list(_FIELDS[kind]) for kind in _NODE_TYPES[3:]}})
_NODE_FRAME_SIZES = {
    "dict": len(_json({"type": "mapping", "items": []})),
    "list": len(_json({"type": "list", "items": []})),
    "tuple": len(_json({"type": "tuple", "items": []})),
    **{kind: len(_json({"type": kind, "fields": {"type": "mapping", "items": []}}))
       for kind in _CLASSES},
}
_MAX_SIZE_CACHE_ENTRIES = 4096
_MAX_SIZE_CACHE_BYTES = 1024 * 1024
_MAX_SIZE_CACHE_STRING_CHARS = 4096


class ReportBundleError(TargetSnapshotError):
    """Invalid, changed, unsupported or incompatible complete report data."""


class ReportUnavailableError(ReportBundleError):
    """An explicit producer disposition has no complete report to consume."""


def _number(value):
    if type(value) is int:
        return True
    return type(value) is float and math.isfinite(value)


def _sequence(value):
    return type(value) in (list, tuple)


def _strings(value):
    return _sequence(value) and all(type(item) is str for item in value)


def _mapping(value):
    return type(value) is dict and all(type(key) is str for key in value)


def _native_fields(value):
    """Validate native field shapes without calling arbitrary serializers."""
    kind = type(value).__name__
    if _CLASSES.get(kind) is not type(value) or set(vars(value)) != set(_FIELDS[kind]):
        raise ReportBundleError("only exact native report classes and declared fields are supported")
    valid = True
    if type(value) is MultiViewLegalIRReport:
        valid = (_strings(value.bridge_names) and bool(value.bridge_names)
                 and len(set(value.bridge_names)) == len(value.bridge_names)
                 and all(value.bridge_names) and type(value.document) is LegalIRDocument
                 and _mapping(value.reports) and _mapping(value.failures)
                 and all(type(item) is BridgeEvaluationReport and item.adapter_name == name
                         for name, item in value.reports.items())
                 and all(type(item) is str and item for item in value.failures.values())
                 and not (set(value.reports) & set(value.failures))
                 and set(value.reports) | set(value.failures) <= set(value.bridge_names))
    elif type(value) is BridgeEvaluationReport:
        valid = (all(type(getattr(value, name)) is str for name in
                     ("adapter_name", "target_component", "decoded_text", "status"))
                 and type(value.ir_document) is LegalIRDocument and type(value.round_trip) is RoundTripMetrics
                 and type(value.proof_gate) is ProofGateResult and type(value.graph_projection) is GraphProjectionResult
                 and _mapping(value.metadata))
    elif type(value) is LegalIRDocument:
        valid = (all(type(getattr(value, name)) is str for name in
                     ("document_id", "source_text", "normalized_text", "source", "version"))
                 and (value.citation is None or type(value.citation) is str)
                 and _mapping(value.views) and all(type(item) is LogicIRView for item in value.views.values())
                 and _mapping(value.metadata) and _sequence(value.frame_logic_triples)
                 and all(_mapping(item) for item in value.frame_logic_triples))
    elif type(value) is LogicIRView:
        valid = (all(type(getattr(value, name)) is str for name in ("name", "format", "source_component"))
                 and _mapping(value.payload) and _mapping(value.metadata))
    elif type(value) is RoundTripMetrics:
        valid = (all(_number(getattr(value, name)) for name in _FIELDS[kind] if name != "extra_losses")
                 and _mapping(value.extra_losses) and all(_number(item) for item in value.extra_losses.values()))
    elif type(value) is ProofGateResult:
        valid = (all(type(getattr(value, name)) is int and 0 <= getattr(value, name) <= 2**63 - 1
                     for name in ("attempted_count", "valid_count", "unavailable_count", "error_count", "failed_count"))
                 and _strings(value.verified_by) and _sequence(value.details)
                 and all(_mapping(item) for item in value.details))
    elif type(value) is GraphProjectionResult:
        valid = (type(value.graph_id) is str and type(value.neo4j_compatible) is bool
                 and all(type(getattr(value, name)) is int and 0 <= getattr(value, name) <= 2**63 - 1
                         for name in ("node_count", "relationship_count"))
                 and _strings(value.node_labels) and _strings(value.relationship_types) and _mapping(value.metadata))
    if not valid:
        raise ReportBundleError("invalid native report field types or adapter inventory")


def _scalar(value):
    if value is None or type(value) in (str, bool, int):
        return True
    if type(value) is float:
        if not math.isfinite(value):
            raise ReportBundleError("nonfinite report number")
        return True
    return False


def _exact_json_size(value):
    return len(_json(value))


class _ScalarJsonSizeMemo:
    """Bounded exact string lengths, owned by one encode/decode operation.

    The byte budget counts encoded string bytes, not Python allocation/RSS.
    No source strings are retained globally; misses and overflow use the same
    encoder as before. Other scalar types always retain that exact path.
    """
    __slots__ = ("_sizes", "_retained_bytes")

    def __init__(self):
        self._sizes = {}
        self._retained_bytes = 0

    def __call__(self, value):
        if type(value) is not str or len(value) > _MAX_SIZE_CACHE_STRING_CHARS:
            return len(_json(value))
        cached = self._sizes.get(value)
        if cached is not None:
            return cached
        size = len(_json(value))
        if (len(self._sizes) < _MAX_SIZE_CACHE_ENTRIES
                and self._retained_bytes + size <= _MAX_SIZE_CACHE_BYTES):
            self._sizes[value] = size
            self._retained_bytes += size
        return size


def _node_limits(node, prior, string_sizes=(), *, scalar_size=None):
    """Exact tagged-tree size arithmetic without expanding shared references."""
    kind = node["type"]
    pairs = kind not in {"list", "tuple"}
    items = node["items" if kind in {"dict", "list", "tuple"} else "fields"]
    size = _NODE_FRAME_SIZES.get(kind)
    if size is None:
        if kind == "dict":
            size = len(_json({"type": "mapping", "items": []}))
        elif pairs:
            size = len(_json({"type": kind, "fields": {"type": "mapping", "items": []}}))
        else:
            size = len(_json({"type": kind, "items": []}))
    scalar_size = _exact_json_size if scalar_size is None else scalar_size
    size += max(0, len(items) - 1)
    height = 0
    for entry in items:
        value = entry[1] if pairs else entry
        if type(value) is dict and "str" in value:
            child_height, child_size = 0, string_sizes[value["str"]]
        elif type(value) is dict:
            child_height, child_size = prior[value["ref"]]
        else:
            child_height, child_size = 0, scalar_size(value)
        height = max(height, child_height + 1)
        if pairs:
            key = entry[0]
            key_size = string_sizes[key["str"]] if type(key) is dict else scalar_size(key)
        else:
            key_size = 0
        size += child_size + (key_size + 3 if pairs else 0)
        if size > MAX_EXPANDED_GRAPH_BYTES:
            raise ReportBundleError("expanded report graph exceeds traversal byte bound")
    if height > MAX_DEPTH:
        raise ReportBundleError("report nesting limit exceeded")
    return height, size


def _intern_strings(nodes):
    """Pool repeated long scalar values/keys in deterministic node order."""
    counts = {}

    def count(value):
        if type(value) is str and len(value) >= _MIN_STRING_LENGTH:
            if value not in counts and len(counts) >= MAX_STRINGS:
                raise ReportBundleError("report string count exceeds bound")
            counts[value] = counts.get(value, 0) + 1

    for node in nodes:
        kind = node["type"]
        if kind in {"list", "tuple"}:
            for value in node["items"]:
                count(value)
        else:
            for key, value in node["items" if kind == "dict" else "fields"]:
                if kind == "dict":
                    count(key)
                count(value)
    strings = [value for value, count_ in counts.items() if count_ > 1]
    indices = {value: index for index, value in enumerate(strings)}

    def reference(value):
        if type(value) is str and value in indices:
            return {"str": indices[value]}
        return value

    for node in nodes:
        kind = node["type"]
        if kind in {"list", "tuple"}:
            node["items"] = [reference(value) for value in node["items"]]
        else:
            for pair in node["items" if kind == "dict" else "fields"]:
                if kind == "dict":
                    pair[0] = reference(pair[0])
                pair[1] = reference(pair[1])
    return strings


def _positional_nodes(nodes):
    """Use compact framing only; retain all scalar values and reference kinds."""
    def value(item):
        if type(item) is dict:
            return [0, item["ref"]] if "ref" in item else [1, item["str"]]
        return item
    result = []
    for node in nodes:
        kind = node["type"]
        if kind in {"list", "tuple"}:
            payload = [value(item) for item in node["items"]]
        elif kind == "dict":
            payload = [value(item) for pair in node["items"] for item in pair]
        else:
            payload = [value(pair[1]) for pair in node["fields"]]
        result.append([_NODE_TAGS[kind], payload])
    return result


def _expand_positional(data):
    """Bounded v3 shape normalization, without expanding graph references.

    Preflight every compact shape/reference, then normalize one node at a time.
    The common validator still checks native fields, duplicate names, sharing,
    string usage, traversal bytes and depth. This is not an RSS bound; normalized
    nodes are never reserialized against the original wire-byte cap.
    """
    if (set(data) != {"schema_version", "schema_sha256", "strings", "nodes", "root"}
            or data["schema_sha256"] != _POSITIONAL_SCHEMA_SHA256
            or type(data["nodes"]) is not list or not 1 <= len(data["nodes"]) <= MAX_NODES
            or type(data["strings"]) is not list or len(data["strings"]) > MAX_STRINGS
            or type(data["root"]) is not int or data["root"] != len(data["nodes"]) - 1):
        raise ReportBundleError("invalid positional report DAG envelope or schema")
    for index, row in enumerate(data["nodes"]):
        if (type(row) is not list or len(row) != 2 or type(row[0]) is not int
                or not 0 <= row[0] < len(_NODE_TYPES) or type(row[1]) is not list):
            raise ReportBundleError("invalid positional report node")
        kind, payload = _NODE_TYPES[row[0]], row[1]

        if kind == "dict" and len(payload) % 2:
            raise ReportBundleError("odd positional report dictionary payload")
        if kind not in {"dict", "list", "tuple"} and len(payload) != len(_FIELDS[kind]):
            raise ReportBundleError("invalid positional native field count")
        for item in payload:
            if _scalar(item):
                continue
            if (type(item) is not list or len(item) != 2 or type(item[0]) is not int
                    or item[0] not in {0, 1} or type(item[1]) is not int
                    or not 0 <= item[1] < (index if item[0] == 0 else len(data["strings"]))):
                raise ReportBundleError("invalid positional report reference")

    def value(item):
        return {"ref" if item[0] == 0 else "str": item[1]} if type(item) is list else item

    def nodes():
        for tag, payload in data["nodes"]:
            kind = _NODE_TYPES[tag]
            if kind in {"list", "tuple"}:
                yield {"type": kind, "items": [value(item) for item in payload]}
            elif kind == "dict":
                yield {"type": kind, "items": [[value(payload[i]), value(payload[i + 1])]
                                                 for i in range(0, len(payload), 2)]}
            else:
                yield {"type": kind, "fields": [[name, value(item)] for name, item in zip(_FIELDS[kind], payload)]}
    return {"schema_version": _DAG_V2, "strings": data["strings"], "nodes": nodes(), "root": {"ref": data["root"]}}


def report_to_bytes(report: MultiViewLegalIRReport, *, max_bytes: int = DEFAULT_MAX_SHARD_BYTES) -> bytes:
    """Encode all native fields and shared identities; never use to_dict summaries."""
    if type(max_bytes) is not int or not 1 <= max_bytes <= DEFAULT_MAX_SHARD_BYTES:
        raise ReportBundleError("invalid report byte bound")
    if type(report) is not MultiViewLegalIRReport:
        raise ReportBundleError("full native MultiViewLegalIRReport required")
    nodes, memo, active, limits = [], {}, set(), []
    scalar_size = _ScalarJsonSizeMemo()

    def visit(value, depth=0):
        if depth > MAX_DEPTH:
            raise ReportBundleError("report nesting limit exceeded")
        if _scalar(value):
            return value
        identity = id(value)
        if identity in active:
            raise ReportBundleError("cyclic report graph is not supported")
        if identity in memo:
            return {"ref": memo[identity]}
        if type(value) not in (dict, list, tuple):
            _native_fields(value)
        active.add(identity)
        try:
            if type(value) is dict:
                if not _mapping(value):
                    raise ReportBundleError("report mapping keys must be exact strings")
                node = {"type": "dict", "items": [[key, visit(item, depth + 1)] for key, item in value.items()]}
            elif type(value) in (list, tuple):
                node = {"type": type(value).__name__, "items": [visit(item, depth + 1) for item in value]}
            else:
                kind = type(value).__name__
                node = {"type": kind, "fields": [[name, visit(getattr(value, name), depth + 1)] for name in _FIELDS[kind]]}
            if len(nodes) >= MAX_NODES:
                raise ReportBundleError("report node count exceeds bound")
            limits.append(_node_limits(node, limits, scalar_size=scalar_size))
            index = len(nodes)
            nodes.append(node)
            memo[identity] = index
            return {"ref": index}
        finally:
            active.remove(identity)

    root = visit(report)
    strings = _intern_strings(nodes)
    raw = _json({"schema_version": DAG_SCHEMA_VERSION, "schema_sha256": _POSITIONAL_SCHEMA_SHA256,
                 "strings": strings, "nodes": _positional_nodes(nodes), "root": root["ref"]})
    if len(raw) > max_bytes:
        raise ReportBundleError("encoded report exceeds shard byte bound")
    return raw


def report_from_bytes(raw: bytes, *, max_bytes: int = DEFAULT_MAX_SHARD_BYTES,
                      expected_schema_version: str | None = None) -> MultiViewLegalIRReport:
    """Decode backward-only native DAG nodes with no imports selected by data."""
    if (type(max_bytes) is not int or not 1 <= max_bytes <= DEFAULT_MAX_SHARD_BYTES
            or type(raw) is not bytes or not 1 <= len(raw) <= max_bytes):
        raise ReportBundleError("report bytes exceed bound or have invalid type")
    data = _parse(raw)
    version = data.get("schema_version") if type(data) is dict else None
    if (type(version) is not str or version not in {_DAG_V1, _DAG_V2, DAG_SCHEMA_VERSION}
            or (expected_schema_version is not None and version != expected_schema_version)):
        raise ReportBundleError("invalid report DAG envelope")
    positional = version == DAG_SCHEMA_VERSION
    node_count = len(data["nodes"]) if type(data.get("nodes")) is list else 0
    if positional:
        data = _expand_positional(data)
        version = data["schema_version"]
    if (version not in {_DAG_V1, _DAG_V2}
            or set(data) != ({"schema_version", "nodes", "root"} if version == _DAG_V1
                             else {"schema_version", "nodes", "root", "strings"})
            or (not positional and type(data["nodes"]) is not list)
            or not 1 <= node_count <= MAX_NODES
            or data["root"] != {"ref": node_count - 1}
            or type(data["root"].get("ref")) is not int):
        raise ReportBundleError("invalid report DAG envelope")
    strings = data.get("strings", [])
    if (type(strings) is not list or len(strings) > MAX_STRINGS
            or any(type(value) is not str or len(value) < _MIN_STRING_LENGTH for value in strings)
            or len(set(strings)) != len(strings)):
        raise ReportBundleError("invalid or duplicate report string table")
    string_sizes = [len(_json(value)) for value in strings]
    if sum(string_sizes) > max_bytes:
        raise ReportBundleError("report string table exceeds byte bound")
    string_indices = {value: index for index, value in enumerate(strings)}
    string_uses = [0] * len(strings)
    next_string = 0
    objects, depths, referenced, limits = [], [], set(), []
    scalar_size = _ScalarJsonSizeMemo()

    def resolve_string(value):
        nonlocal next_string
        if (version != _DAG_V2 or type(value) is not dict or set(value) != {"str"}
                or type(value["str"]) is not int or not 0 <= value["str"] < len(strings)):
            raise ReportBundleError("invalid report string reference")
        reference = value["str"]
        if not string_uses[reference]:
            if reference != next_string:
                raise ReportBundleError("report string table first-use order mismatch")
            next_string += 1
        string_uses[reference] += 1
        return strings[reference]

    def inline_string(value):
        if value in string_indices:
            raise ReportBundleError("pooled report string must use a reference")
        return value

    def resolve(value, index):
        if _scalar(value):
            return inline_string(value) if type(value) is str else value, 0
        if type(value) is dict and "str" in value:
            return resolve_string(value), 0
        if (type(value) is not dict or set(value) != {"ref"} or type(value["ref"]) is not int
                or not 0 <= value["ref"] < index):
            raise ReportBundleError("invalid, cyclic or forward report reference")
        reference = value["ref"]
        referenced.add(reference)
        return objects[reference], depths[reference]

    for index, node in enumerate(data["nodes"]):
        if type(node) is not dict or type(node.get("type")) is not str:
            raise ReportBundleError("invalid report node")
        kind = node["type"]
        field = "items" if kind in {"dict", "list", "tuple"} else "fields"
        if set(node) != {"type", field} or type(node[field]) is not list:
            raise ReportBundleError("invalid report node fields")
        children = []
        if kind in {"list", "tuple"}:
            for item in node[field]:
                value, depth = resolve(item, index)
                children.append((value, depth))
            value = [item for item, _ in children]
            if kind == "tuple":
                value = tuple(value)
        else:
            values = {}
            names = []
            for pair in node[field]:
                if type(pair) is not list or len(pair) != 2:
                    raise ReportBundleError("invalid report mapping/field pair")
                name = pair[0]
                if kind == "dict" and type(name) is dict:
                    name = resolve_string(name)
                elif type(name) is str:
                    name = inline_string(name)
                if type(name) is not str or name in values:
                    raise ReportBundleError("invalid or duplicate report mapping/field name")
                item, depth = resolve(pair[1], index)
                values[name] = item
                names.append(name)
                children.append((item, depth))
            if kind == "dict":
                value = values
            else:
                if kind not in _CLASSES or tuple(names) != _FIELDS[kind]:
                    raise ReportBundleError("unknown report class or declared field order")
                try:
                    value = _CLASSES[kind](**values)
                except (TypeError, ValueError) as exc:
                    raise ReportBundleError("invalid native report constructor fields") from exc
                _native_fields(value)
        depth = 1 + max((child_depth for _, child_depth in children), default=-1)
        if depth > MAX_DEPTH:
            raise ReportBundleError("report nesting limit exceeded")
        limits.append(_node_limits(node, limits, string_sizes, scalar_size=scalar_size))
        objects.append(value)
        depths.append(depth)
    if referenced != set(range(len(objects) - 1)) or type(objects[-1]) is not MultiViewLegalIRReport:
        raise ReportBundleError("unreferenced report nodes or non-native report root")
    if any(count < 2 for count in string_uses):
        raise ReportBundleError("unreferenced or unrepeated report string table entry")
    return objects[-1]


def _bound(value, maximum, label):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ReportBundleError("invalid " + label + " bound")


def _bounds(max_bytes, max_manifest_bytes, max_shard_bytes):
    _bound(max_bytes, DEFAULT_MAX_BYTES, "artifact byte")
    _bound(max_manifest_bytes, DEFAULT_MAX_MANIFEST_BYTES, "manifest byte")
    _bound(max_shard_bytes, DEFAULT_MAX_SHARD_BYTES, "report shard byte")


def _report_status(report):
    _native_fields(report)
    # Native adapters may return None without raising: multiview preserves the
    # missing row without inventing a failure entry. Keep that exact observation.
    return "partial" if report.failures or set(report.reports) != set(report.bridge_names) else "ready"


def _validated_target(report, sample, config, status):
    if tuple(report.bridge_names) != config.bridge_names or _report_status(report) != status:
        raise ReportBundleError("report bridge order/configuration or disposition mismatch")
    document = report.document
    if (document.document_id != sample.sample_id or document.source_text != sample.text
            or document.source != sample.source or document.citation != sample.citation):
        raise ReportBundleError("report document differs from exact sample source identity")
    try:
        target = report.training_target()
        _validate_target(target, sample.sample_id, config, "ready")
        target_raw = _json(_encode_target(target))
        if len(target_raw) > DEFAULT_MAX_SHARD_BYTES:
            raise ReportBundleError("derived target exceeds unchanged target shard byte bound")
        digest = _sha(target_raw)
    except (ValueError, TypeError, AttributeError, OverflowError) as exc:
        raise ReportBundleError("native report cannot derive a valid exact target") from exc
    if target.document is not report.document:
        raise ReportBundleError("native derived target did not retain report document")
    return target, digest


def _manifest(raw, *, payload_bytes, max_shard_bytes):
    data = _parse(raw)
    if (type(data) is not dict or set(data) != {"schema_version", "codec", "config", "records", "shards", "snapshot_id"}
            or data["schema_version"] != SCHEMA_VERSION or type(data["codec"]) is not str
            or data["codec"] not in _CODECS):
        raise ReportBundleError("invalid report bundle manifest schema")
    _io._config(data["config"])
    body = {key: value for key, value in data.items() if key != "snapshot_id"}
    if data["snapshot_id"] != "sha256:" + _digest(body):
        raise ReportBundleError("report manifest identity mismatch")
    if type(data["records"]) is not list or not data["records"] or type(data["shards"]) is not list:
        raise ReportBundleError("report bundle requires an ordered record inventory")
    shards, extent = {}, 0
    for shard in data["shards"]:
        if type(shard) is not dict or set(shard) != {"report_sha256", "offset", "compressed_bytes", "uncompressed_bytes", "compressed_sha256"}:
            raise ReportBundleError("invalid report shard descriptor")
        if not _hash(shard["report_sha256"]) or not _hash(shard["compressed_sha256"]) or shard["report_sha256"] in shards:
            raise ReportBundleError("invalid or duplicate report shard identity")
        if (type(shard["offset"]) is not int or shard["offset"] != extent
                or type(shard["compressed_bytes"]) is not int
                or not 1 <= shard["compressed_bytes"] <= _io._compressed_bound(max_shard_bytes)
                or type(shard["uncompressed_bytes"]) is not int
                or not 1 <= shard["uncompressed_bytes"] <= max_shard_bytes):
            raise ReportBundleError("invalid report shard extent or expansion bound")
        extent += shard["compressed_bytes"]
        if extent > payload_bytes:
            raise ReportBundleError("report shard exceeds artifact")
        shards[shard["report_sha256"]] = shard
    if extent != payload_bytes:
        raise ReportBundleError("trailing or unindexed report artifact bytes")
    seen, referenced = set(), set()
    for row in data["records"]:
        if type(row) is not dict or set(row) != {"sample_id", "sample_sha256", "status", "has_report", "report_sha256", "target_sha256"}:
            raise ReportBundleError("invalid report record schema")
        if (type(row["sample_id"]) is not str or not row["sample_id"] or row["sample_id"] in seen
                or not _hash(row["sample_sha256"]) or not _hash(row["report_sha256"]) or not _hash(row["target_sha256"])
                or type(row["status"]) is not str or row["status"] not in STATUSES or type(row["has_report"]) is not bool):
            raise ReportBundleError("invalid report sample identity or status")
        seen.add(row["sample_id"])
        if row["has_report"]:
            if row["status"] not in {"ready", "partial"} or row["report_sha256"] not in shards or row["target_sha256"] == _NULL_SHA256:
                raise ReportBundleError("invalid available report disposition or shard")
            referenced.add(row["report_sha256"])
        elif (row["status"] not in _MISSING_STATUSES or row["report_sha256"] != _NULL_SHA256
              or row["target_sha256"] != _NULL_SHA256):
            raise ReportBundleError("invalid unavailable report disposition")
    if referenced != set(shards):
        raise ReportBundleError("unreferenced report shards")
    return data


def _inventory(manifest, manifest_bytes, artifact_bytes):
    shards = {row["report_sha256"]: row for row in manifest["shards"]}
    references = [row["report_sha256"] for row in manifest["records"] if row["has_report"]]
    return {"artifact_format": "report_bundle", "schema_version": SCHEMA_VERSION, "codec": manifest["codec"],
            "artifact_bytes": artifact_bytes, "manifest_bytes": manifest_bytes,
            "sample_count": len(manifest["records"]), "report_count": len(references),
            "shard_count": len(shards), "compressed_report_bytes": sum(row["compressed_bytes"] for row in shards.values()),
            "unique_uncompressed_report_bytes": sum(row["uncompressed_bytes"] for row in shards.values()),
            "referenced_uncompressed_report_bytes": sum(shards[key]["uncompressed_bytes"] for key in references)}


@dataclass(frozen=True)
class ReportSelection:
    reports: Mapping[str, MultiViewLegalIRReport]
    targets: Mapping[str, Any]
    metadata: Mapping[str, Any]


class ReportBundle:
    """Verified immutable staged file; one request hydrates reports and targets."""

    def __init__(self, descriptor, info, manifest, sha256, path, payload_offset, statistics):
        self._descriptor, self._fingerprint = descriptor, _io._fingerprint(info)
        self._manifest, self._sha256, self._path = manifest, sha256, path
        self._payload_offset, self._statistics = payload_offset, statistics
        self._records = {row["sample_id"]: row for row in manifest["records"]}
        self._shards = {row["report_sha256"]: row for row in manifest["shards"]}
        self._decompressed = set()

    @property
    def snapshot_id(self):
        return self._manifest["snapshot_id"]

    @property
    def sha256(self):
        return self._sha256

    @property
    def config(self):
        return _io._config(_parse(_json(self._manifest["config"])))

    @property
    def statuses(self):
        return {key: row["status"] for key, row in self._records.items()}

    @property
    def sample_count(self):
        return len(self._records)

    @property
    def statistics(self):
        return {**self._statistics, "unique_decompressed_shards": len(self._decompressed), "closed": self._descriptor is None}

    def _check_open(self):
        if self._descriptor is None:
            raise ReportBundleError("report bundle is closed")
        if _io._fingerprint(os.fstat(self._descriptor)) != self._fingerprint:
            raise ReportBundleError("report artifact changed after verification")
        return self._descriptor

    def verify_unchanged(self):
        """Recheck fd/path/bytes at a boundary; no concurrent-writer attestation."""
        self._check_open()
        descriptor, info = _io._open_regular(self._path, DEFAULT_MAX_BYTES)
        try:
            if _io._fingerprint(info) != self._fingerprint:
                raise ReportBundleError("report artifact pathname or file identity changed")
            _io._verify_file(descriptor, info, self._sha256)
            self._check_open()
        finally:
            os.close(descriptor)
        return {"sha256": self.sha256, "bytes": self._fingerprint[2], "snapshot_id": self.snapshot_id}

    def selection_metadata(self, samples, *, config, max_expanded_bytes=DEFAULT_MAX_BYTES):
        self._check_open()
        _bound(max_expanded_bytes, DEFAULT_MAX_BYTES, "selected expanded report byte")
        if _json(config.to_dict()) != _json(self._manifest["config"]):
            raise ReportBundleError("report configuration/provenance mismatch")
        result = {"sample_ids": [], "sample_sha256": {}, "statuses": {}, "report_sha256": {},
                  "target_sha256": {}, "referenced_expanded_bytes": 0}
        for sample in samples:
            sample_id, digest = _sample_payload(sample)
            if sample_id in result["sample_sha256"]:
                raise ReportBundleError("duplicate requested report sample")
            row = self._records.get(sample_id)
            if row is None or row["sample_sha256"] != digest:
                raise ReportBundleError("missing or changed report sample payload")
            if not row["has_report"]:
                raise ReportUnavailableError(f"sample has no full report: {sample_id}: {row['status']}")
            result["sample_ids"].append(sample_id)
            for key in ("sample_sha256", "report_sha256", "target_sha256"):
                result[key][sample_id] = row[key]
            result["statuses"][sample_id] = row["status"]
            result["referenced_expanded_bytes"] += self._shards[row["report_sha256"]]["uncompressed_bytes"]
            if result["referenced_expanded_bytes"] > max_expanded_bytes:
                raise ReportBundleError("selected expanded report bytes exceed bound")
        self._check_open()
        return result

    def selection_for(self, samples, *, config, max_expanded_bytes=DEFAULT_MAX_BYTES):
        samples = tuple(samples)
        metadata = self.selection_metadata(samples, config=config, max_expanded_bytes=max_expanded_bytes)
        descriptor = self._check_open()
        reports, targets = {}, {}
        for sample in samples:
            row = self._records[sample.sample_id]
            shard = self._shards[row["report_sha256"]]
            started = time.perf_counter()
            compressed = _io._read_at(descriptor, shard["compressed_bytes"], self._payload_offset + shard["offset"])
            if _sha(compressed) != shard["compressed_sha256"]:
                raise ReportBundleError("compressed report digest mismatch")
            raw = _io._expand(compressed, shard["uncompressed_bytes"])
            if _sha(raw) != shard["report_sha256"]:
                raise ReportBundleError("expanded report digest mismatch")
            self._statistics["read_decompress_seconds"] += time.perf_counter() - started
            started = time.perf_counter()
            report = report_from_bytes(raw, expected_schema_version=_CODECS[self._manifest["codec"]])
            target, target_sha256 = _validated_target(report, sample, config, row["status"])
            if target_sha256 != row["target_sha256"]:
                raise ReportBundleError("derived target byte identity mismatch")
            reports[sample.sample_id], targets[sample.sample_id] = report, target
            self._statistics["hydrate_validate_seconds"] += time.perf_counter() - started
            self._statistics["decompressed_shards"] += 1
            self._statistics["decompressed_bytes"] += len(raw)
            self._decompressed.add(row["report_sha256"])
        self._check_open()
        return ReportSelection(MappingProxyType(reports), MappingProxyType(targets), MappingProxyType(metadata))

    def close(self):
        descriptor, self._descriptor = self._descriptor, None
        if descriptor is not None:
            os.close(descriptor)

    def __enter__(self):
        self._check_open()
        return self

    def __exit__(self, *_):
        self.close()

    def __del__(self):
        descriptor = getattr(self, "_descriptor", None)
        if descriptor is not None:
            os.close(descriptor)


def write_report_bundle(path, records: Iterable[tuple[Any, Any, str | None]], *, config: TargetSnapshotConfig,
                        max_bytes=DEFAULT_MAX_BYTES, max_manifest_bytes=DEFAULT_MAX_MANIFEST_BYTES,
                        max_shard_bytes=DEFAULT_MAX_SHARD_BYTES):
    """Publish exclusively after all reports and final producer checks succeed."""
    _bounds(max_bytes, max_manifest_bytes, max_shard_bytes)
    config_payload = _parse(_json(config.to_dict()))
    config = _io._config(config_payload)
    parent, name, absolute = _io._open_parent(path)
    spool_name, final_name = ".report-shards-" + uuid.uuid4().hex, ".report-bundle-" + uuid.uuid4().hex
    spool = final = None
    rows, shards, by_hash, seen = [], [], {}, set()
    extent, estimate = 0, len(_json(config_payload)) + 512
    encoding_seconds = compression_seconds = 0.0
    try:
        if estimate > max_manifest_bytes or estimate + _HEADER.size > max_bytes:
            raise ReportBundleError("report configuration exceeds manifest/artifact bound")
        try:
            os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(absolute)
        spool = os.fdopen(os.open(spool_name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                  0o600, dir_fd=parent), "w+b")
        os.unlink(spool_name, dir_fd=parent)
        for sample, report, status in records:
            sample_id, sample_sha256 = _sample_payload(sample)
            if sample_id in seen:
                raise ReportBundleError("duplicate report sample identity")
            seen.add(sample_id)
            report_sha256 = target_sha256 = _NULL_SHA256
            if report is None:
                if type(status) is not str or status not in _MISSING_STATUSES:
                    raise ReportBundleError("missing report requires explicit failure/timeout disposition")
            else:
                started = time.perf_counter()
                raw = report_to_bytes(report, max_bytes=max_shard_bytes)
                actual_status = _report_status(report)
                if status is None:
                    status = actual_status
                if type(status) is not str or status != actual_status:
                    raise ReportBundleError("report disposition does not match returned report inventory")
                target, target_sha256 = _validated_target(report, sample, config, status)
                del target
                report_sha256 = _sha(raw)
                encoding_seconds += time.perf_counter() - started
                if report_sha256 not in by_hash:
                    started = time.perf_counter()
                    compressed = zlib.compress(raw, level=6)
                    compression_seconds += time.perf_counter() - started
                    shard = {"report_sha256": report_sha256, "offset": extent, "compressed_bytes": len(compressed),
                             "uncompressed_bytes": len(raw), "compressed_sha256": _sha(compressed)}
                    extent += len(compressed)
                    if extent + estimate + _HEADER.size > max_bytes:
                        raise ReportBundleError("report bundle exceeds artifact byte bound")
                    spool.write(compressed)
                    shards.append(shard)
                    by_hash[report_sha256] = shard
                    estimate += len(_json(shard)) + 1
                    del compressed
                del raw
            row = {"sample_id": sample_id, "sample_sha256": sample_sha256, "status": status,
                   "has_report": report is not None, "report_sha256": report_sha256, "target_sha256": target_sha256}
            rows.append(row)
            estimate += len(_json(row)) + 1
            if estimate > max_manifest_bytes:
                raise ReportBundleError("report inventory exceeds manifest byte bound")
            sample = report = None
        body = {"schema_version": SCHEMA_VERSION, "codec": _CODEC, "config": config_payload,
                "records": rows, "shards": shards}
        manifest = {**body, "snapshot_id": "sha256:" + _digest(body)}
        manifest_raw = _json(manifest)
        artifact_bytes = _HEADER.size + len(manifest_raw) + extent
        if len(manifest_raw) > max_manifest_bytes or artifact_bytes > max_bytes:
            raise ReportBundleError("report manifest or artifact byte bound exceeded")
        _manifest(manifest_raw, payload_bytes=extent, max_shard_bytes=max_shard_bytes)
        header = _HEADER.pack(MAGIC, len(manifest_raw))
        final = os.fdopen(os.open(final_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                  0o600, dir_fd=parent), "wb")
        digest = hashlib.sha256()
        for part in (header, manifest_raw):
            final.write(part)
            digest.update(part)
        spool.seek(0)
        while part := spool.read(_io._CHUNK):
            final.write(part)
            digest.update(part)
        final.flush()
        os.fsync(final.fileno())
        os.link(final_name, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
        os.fsync(parent)
        statistics = _inventory(manifest, len(manifest_raw), artifact_bytes)
        statistics.update(encoding_validate_seconds=encoding_seconds, compression_seconds=compression_seconds)
        return {"path": absolute, "sha256": digest.hexdigest(), "bytes": artifact_bytes,
                "snapshot_id": manifest["snapshot_id"], "sample_count": len(rows),
                "report_count": sum(row["has_report"] for row in rows),
                "statuses": {row["sample_id"]: row["status"] for row in rows}, "statistics": statistics}
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


def load_report_bundle(path, *, expected_sha256, expected_size_bytes, config=None,
                       max_bytes=DEFAULT_MAX_BYTES, max_manifest_bytes=DEFAULT_MAX_MANIFEST_BYTES,
                       max_shard_bytes=DEFAULT_MAX_SHARD_BYTES):
    _bounds(max_bytes, max_manifest_bytes, max_shard_bytes)
    if not _hash(expected_sha256) or type(expected_size_bytes) is not int or not 1 <= expected_size_bytes <= max_bytes:
        raise ReportBundleError("expected report SHA-256 and bounded byte count required")
    started = time.perf_counter()
    descriptor, info = _io._open_regular(path, max_bytes)
    bundle = None
    try:
        if info.st_size != expected_size_bytes:
            raise ReportBundleError("report artifact byte count mismatch")
        _io._verify_file(descriptor, info, expected_sha256)
        hash_seconds = time.perf_counter() - started
        started = time.perf_counter()
        magic, size = _HEADER.unpack(_io._read_at(descriptor, _HEADER.size, 0))
        if magic != MAGIC or not 1 <= size <= max_manifest_bytes or _HEADER.size + size > info.st_size:
            raise ReportBundleError("invalid report bundle header or manifest bound")
        manifest = _manifest(_io._read_at(descriptor, size, _HEADER.size),
                             payload_bytes=info.st_size - _HEADER.size - size, max_shard_bytes=max_shard_bytes)
        if config is not None and _json(manifest["config"]) != _json(config.to_dict()):
            raise ReportBundleError("report configuration/provenance mismatch")
        statistics = _inventory(manifest, size, info.st_size)
        statistics.update(open_hash_seconds=hash_seconds, manifest_parse_validate_seconds=time.perf_counter() - started,
                          read_decompress_seconds=0.0, hydrate_validate_seconds=0.0,
                          decompressed_shards=0, decompressed_bytes=0)
        bundle = ReportBundle(descriptor, info, manifest, expected_sha256, str(Path(path).absolute()),
                              _HEADER.size + size, statistics)
        bundle._check_open()
        return bundle
    except BaseException:
        if bundle is not None:
            bundle.close()
        else:
            os.close(descriptor)
        raise
