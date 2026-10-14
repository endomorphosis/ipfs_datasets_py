"""Durable, source-bound preparation records before structural publication.

These pure APIs store an existing captured inventory and a contiguous ledger of
source-local preparation artifacts. They do not capture a live repository,
authenticate an analyzer, validate AST semantics, assemble cross-file facts or
publish a catalog head. Receivers verify every referenced body again; a cursor
is a hint about a durable prefix, never a claim of source freshness or proof.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import math
import os
import stat
import sys
from typing import Callable

from .content import (
    canonical_dag_json_bytes, cid_for_bytes, cid_for_structured, validate_cid,
)
from .semantic_index.snapshot import RepositorySnapshot

ROOT_SCHEMA = "codebase-preparation-root@1"
PAGE_SCHEMA = "codebase-preparation-page@1"
CURSOR_SCHEMA = "codebase-preparation-cursor@1"
ARTIFACT_SCHEMA = "codebase-preparation-source-artifact@1"
_MIB = 1024 * 1024
MAX_DECODE_CACHE_BYTES = 8 * _MIB
MAX_DECODE_CACHE_HEAP_BYTES = 64 * _MIB
MAX_DECODE_CACHE_MEMBERS = 1024
MAX_DECODE_CACHE_DEPTH = 128
_AUTHORITY = {name: False for name in (
    "source_currentness_verified", "source_semantics_verified",
    "analysis_execution_verified", "catalog_publication_authority",
    "proof_authority", "execution_authority", "completion_authority",
    "training_executed", "model_inference_executed",
)}
_CONTEXT_FIELDS = {
    "parser_cid", "scanner_cid", "ast_schema_cid", "semantic_schema_cid",
    "options_cid", "implementation_cid",
}
_OUTCOME_FIELDS = {
    "member_index", "source_key", "entry_cid", "source_cid", "parse_status",
    "semantic_disposition", "ast_artifact", "facts_artifact",
    "diagnostic_artifact", "created_at_hex", "reason",
}
_PARSE = {"ok", "partial", "failed", "opaque", "unindexed"}
_SEMANTIC = {"analysed", "failed", "unsupported", "deferred_budget", "opaque"}


class CodebasePreparationError(ValueError):
    """A preparation record, identity, bound or durable prefix differs."""


def _require(condition, message):
    if not condition:
        raise CodebasePreparationError(message)


def _closed(value, fields, label):
    _require(type(value) is dict and all(type(key) is str for key in value)
             and set(value) == set(fields), "closed " + label + " required")


def _integer(value, maximum, minimum=0):
    _require(type(value) is int and minimum <= value <= maximum,
             "bounded exact integer required")


def _text(value, maximum=512):
    _require(type(value) is str and value and value == value.strip()
             and len(value.encode("utf-8")) <= maximum
             and all(ord(char) >= 32 for char in value), "bounded text required")


def _cid(value, codec="dag-json"):
    _require(type(value) is str, "exact CID string required")
    try:
        validate_cid(value, codecs={codec})
    except (ValueError, TypeError) as exc:
        raise CodebasePreparationError("invalid " + codec + " CID") from exc


def _wire(value, maximum=4 * _MIB):
    try:
        raw = canonical_dag_json_bytes(value)
    except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
        raise CodebasePreparationError("finite canonical structured value required") from exc
    _require(len(raw) <= maximum, "preparation record exceeds byte bound")
    return raw


def _authority(value):
    _closed(value, _AUTHORITY, "preparation authority")
    _require(all(flag is False for flag in value.values()), "exact False authority required")


@dataclass(frozen=True, slots=True)
class CodebasePreparationLimits:
    max_entries: int = 1024
    page_entries: int = 16
    max_file_bytes: int = 64 * 1024
    max_record_bytes: int = 4 * _MIB
    max_artifact_bytes: int = _MIB
    max_prefix_read_bytes: int = 128 * _MIB

    def __post_init__(self):
        for name, maximum in zip(self.__dataclass_fields__,
                (1024, 64, 64 * 1024, 4 * _MIB, _MIB, 128 * _MIB)):
            _integer(getattr(self, name), maximum, 1)
        _require(self.max_artifact_bytes <= self.max_record_bytes,
                 "artifact bound exceeds record bound")

    def to_dict(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value):
        _closed(value, cls.__dataclass_fields__, "preparation limits")
        return cls(**value)


def _head(value, repository_id):
    if value is None:
        return
    _closed(value, {"schema", "repository_id", "generation", "manifest_cid",
                    "snapshot_cid", "ast_revision_id", "receipt_cid"}, "expected head")
    _require(value["schema"] == "codebase-head@1"
             and value["repository_id"] == repository_id, "expected head repository differs")
    _integer(value["generation"], 2**63 - 1, 1)
    for name in ("manifest_cid", "snapshot_cid", "receipt_cid"):
        _cid(value[name])
    _require(value["ast_revision_id"] ==
             f"rev:{repository_id}:snapshot:{value['snapshot_cid']}", "expected head revision differs")


def _root_shape(value):
    _closed(value, {"schema", "snapshot", "expected_head", "context", "context_cid",
                    "membership_cid", "limits", "authority"}, "preparation root")
    _require(value["schema"] == ROOT_SCHEMA, "unsupported preparation root")
    limits = CodebasePreparationLimits.from_dict(value["limits"])
    _wire(value, limits.max_record_bytes)
    snapshot = value["snapshot"]
    _closed(snapshot, {"schema", "repository_id", "entries", "mode", "max_file_bytes",
                       "max_entries", "git_tree", "git_commit", "exclusions", "snapshot_cid"},
            "captured snapshot")
    _integer(snapshot["max_entries"], limits.max_entries, 1)
    _integer(snapshot["max_file_bytes"], limits.max_file_bytes, 1)
    _text(snapshot["repository_id"])
    members = snapshot["entries"]
    _require(type(members) is list and len(members) <= limits.max_entries,
             "bounded complete inventory required")
    try:
        restored = RepositorySnapshot.from_dict(snapshot)
        _require(_wire(restored.to_dict()) == _wire(snapshot),
                 "exact ordered snapshot round-trip required")
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise CodebasePreparationError("invalid captured snapshot") from exc
    exclusions = snapshot["exclusions"]
    _require(type(exclusions) is list and len(exclusions) == len(set(exclusions)),
             "duplicate snapshot exclusion")
    for entry in members:
        _require(type(entry["raw_path_hex"]) is str
                 and 0 < len(entry["raw_path_hex"]) <= 8192, "bounded raw source path required")
        if entry["source_cid"] is not None:
            _cid(entry["source_cid"], "raw")
        if entry["opaque_reason"] is None:
            _integer(entry["size_bytes"], snapshot["max_file_bytes"])
        else:
            _text(entry["opaque_reason"])
    _head(value["expected_head"], snapshot["repository_id"])
    _closed(value["context"], _CONTEXT_FIELDS, "analysis context")
    for identity in value["context"].values():
        _cid(identity)
    _cid(value["context_cid"])
    _cid(value["membership_cid"])
    _require(value["context_cid"] == cid_for_structured(value["context"])
             and value["membership_cid"] == cid_for_structured(members),
             "root context or inventory identity differs")
    _authority(value["authority"])


def _descriptor(value):
    if value is None:
        return
    _closed(value, {"cid", "bytes"}, "source artifact descriptor")
    _cid(value["cid"])
    _integer(value["bytes"], _MIB, 1)


def _clock(value):
    _require(type(value) is str and 0 < len(value) <= 64, "exact hexadecimal clock required")
    try:
        clock = float.fromhex(value)
    except (ValueError, OverflowError) as exc:
        raise CodebasePreparationError("invalid hexadecimal clock") from exc
    _require(math.isfinite(clock) and clock.hex() == value, "canonical finite clock required")


def _outcome_shape(value):
    _closed(value, _OUTCOME_FIELDS, "preparation outcome")
    _integer(value["member_index"], 1023)
    _text(value["source_key"], 8196)
    _cid(value["entry_cid"])
    if value["source_cid"] is not None:
        _cid(value["source_cid"], "raw")
    _require(type(value["parse_status"]) is str and value["parse_status"] in _PARSE
             and type(value["semantic_disposition"]) is str
             and value["semantic_disposition"] in _SEMANTIC, "explicit preparation dispositions required")
    for name in ("ast_artifact", "facts_artifact", "diagnostic_artifact"):
        _descriptor(value[name])
    has_ast = value["ast_artifact"] is not None
    _require(has_ast == (value["parse_status"] in {"ok", "partial", "failed"}),
             "AST artifact and parse disposition differ")
    if has_ast:
        _clock(value["created_at_hex"])
    else:
        _require(value["created_at_hex"] is None, "absent AST cannot acquire a clock")
    if value["semantic_disposition"] == "analysed":
        _require(value["facts_artifact"] is not None, "analysed source requires a facts artifact")
    if value["semantic_disposition"] in {"opaque", "unsupported", "deferred_budget"}:
        _require(value["facts_artifact"] is None, "unknown disposition cannot acquire analysed facts")
    opaque = value["parse_status"] == "opaque"
    _require(opaque == (value["semantic_disposition"] == "opaque"), "opaque disposition differs")
    if opaque:
        _require(all(value[name] is None for name in
                     ("ast_artifact", "facts_artifact", "diagnostic_artifact")),
                 "opaque source cannot acquire analysis artifacts")
    if value["reason"] is not None:
        _text(value["reason"])
    _require(value["reason"] is not None or
             (value["parse_status"] == "ok" and value["semantic_disposition"] == "analysed"),
             "incomplete or unknown analysis requires an explicit reason")


def _coverage(entries):
    return {"inventory_entries": len(entries),
            "parse_status": dict(sorted(Counter(row["parse_status"] for row in entries).items())),
            "semantic_dispositions": dict(sorted(Counter(row["semantic_disposition"] for row in entries).items()))}


def _page_shape(value):
    _closed(value, {"schema", "root_cid", "snapshot_cid", "context_cid", "start", "end",
                    "previous_page_cid", "page_membership_cid", "entries", "coverage", "authority"},
            "preparation page")
    _require(value["schema"] == PAGE_SCHEMA, "unsupported preparation page")
    for name in ("root_cid", "snapshot_cid", "context_cid", "page_membership_cid"):
        _cid(value[name])
    _integer(value["start"], 1023)
    _integer(value["end"], 1024, 1)
    _require(value["start"] < value["end"], "empty preparation page refused")
    if value["previous_page_cid"] is not None:
        _cid(value["previous_page_cid"])
    _require((value["start"] == 0) == (value["previous_page_cid"] is None),
             "page predecessor differs from offset")
    entries = value["entries"]
    _require(type(entries) is list and len(entries) == value["end"] - value["start"]
             and len(entries) <= 64, "complete bounded page partition required")
    for index, outcome in enumerate(entries, value["start"]):
        _outcome_shape(outcome)
        _require(outcome["member_index"] == index, "outcome order differs")
    _require(_wire(value["coverage"]) == _wire(_coverage(entries)), "page coverage differs")
    _authority(value["authority"])


def _record(cid, payload, validator):
    _cid(cid)
    _require(type(payload) is bytes and len(payload) <= 4 * _MIB, "bounded canonical record bytes required")
    try:
        value = json.loads(payload)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise CodebasePreparationError("invalid preparation JSON") from exc
    _require(_wire(value) == payload and cid_for_structured(value) == cid,
             "record bytes or CID do not verify")
    validator(value)


@dataclass(frozen=True, slots=True)
class PreparationRoot:
    artifact_cid: str
    _payload: bytes

    def __post_init__(self):
        _record(self.artifact_cid, self._payload, _root_shape)

    def to_dict(self):
        return json.loads(self._payload)

    @classmethod
    def from_dict(cls, cid, value):
        return cls(cid, _wire(value))


@dataclass(frozen=True, slots=True)
class PreparationCursor:
    root_cid: str
    next_offset: int
    previous_page_cid: str | None

    def __post_init__(self):
        _cid(self.root_cid)
        _integer(self.next_offset, 1024)
        if self.previous_page_cid is not None:
            _cid(self.previous_page_cid)
        _require((self.next_offset == 0) == (self.previous_page_cid is None),
                 "cursor predecessor differs from offset")

    def to_dict(self):
        return {"schema": CURSOR_SCHEMA, "root_cid": self.root_cid,
                "next_offset": self.next_offset, "previous_page_cid": self.previous_page_cid}

    @classmethod
    def from_dict(cls, value):
        _closed(value, {"schema", "root_cid", "next_offset", "previous_page_cid"}, "preparation cursor")
        _require(value["schema"] == CURSOR_SCHEMA, "unsupported preparation cursor")
        return cls(value["root_cid"], value["next_offset"], value["previous_page_cid"])


@dataclass(frozen=True, slots=True)
class PreparationPage:
    artifact_cid: str
    _payload: bytes

    def __post_init__(self):
        _record(self.artifact_cid, self._payload, _page_shape)

    def to_dict(self):
        return json.loads(self._payload)

    @classmethod
    def from_dict(cls, cid, value):
        return cls(cid, _wire(value))

    @property
    def next_cursor(self):
        value = self.to_dict()
        return PreparationCursor(value["root_cid"], value["end"], self.artifact_cid)


@dataclass(frozen=True, slots=True)
class PreparationPrefix:
    root: PreparationRoot
    pages: tuple[PreparationPage, ...]
    next_offset: int

    def __post_init__(self):
        _require(type(self.root) is PreparationRoot and type(self.pages) is tuple,
                 "exact root and ordered pages required")
        root = PreparationRoot.from_dict(self.root.artifact_cid, self.root.to_dict()).to_dict()
        limits = CodebasePreparationLimits.from_dict(root["limits"])
        count = len(root["snapshot"]["entries"])
        _require(len(self.pages) <= (count + limits.page_entries - 1) // limits.page_entries
                 and all(type(page) is PreparationPage for page in self.pages),
                 "bounded exact preparation pages required")
        _integer(self.next_offset, count)
        offset, previous = 0, None
        for item in self.pages:
            page = PreparationPage.from_dict(item.artifact_cid, item.to_dict()).to_dict()
            _page_members(page, self.root.artifact_cid, root, limits)
            _require(page["start"] == offset and page["previous_page_cid"] == previous,
                     "prefix pages do not form a contiguous chain")
            offset, previous = page["end"], item.artifact_cid
        _require(offset == self.next_offset, "prefix offset differs from actual pages")

    @property
    def inventory_complete(self):
        return self.next_offset == len(self.root.to_dict()["snapshot"]["entries"])

    @property
    def cursor(self):
        return PreparationCursor(self.root.artifact_cid, self.next_offset,
                                 self.pages[-1].artifact_cid if self.pages else None)


def build_preparation_artifact(entry, context_cid, kind, payload):
    """Bind inert proposed facts to a source; this does not authenticate facts."""
    _cid(context_cid)
    _require(type(kind) is str and kind in {"ast", "semantic", "diagnostic"}, "artifact kind required")
    _require(type(payload) is dict, "structured artifact payload required")
    value = {"schema": ARTIFACT_SCHEMA, "source_key": "raw:" + entry["raw_path_hex"],
             "entry_cid": entry["entry_cid"], "source_cid": entry["source_cid"],
             "context_cid": context_cid, "kind": kind, "payload": payload,
             "authority": dict(_AUTHORITY)}
    return json.loads(_wire(value, _MIB))


class _DecodeCacheFull(Exception):
    """A decoded wrapper cannot fit this operation's optional cache."""


def _freeze_json(value, maximum):
    """Detach JSON into immutable tuples while bounding retained heap size."""
    used = 0

    def account(size):
        nonlocal used
        used += size
        if used > maximum:
            raise _DecodeCacheFull

    def freeze(item, depth=0):
        if depth > MAX_DECODE_CACHE_DEPTH:
            raise _DecodeCacheFull
        if type(item) is dict:
            pairs = []
            for key, child in item.items():
                account(sys.getsizeof(key))
                pair = (key, freeze(child, depth + 1))
                account(sys.getsizeof(pair))
                pairs.append(pair)
            contents = tuple(pairs)
            result = ("object", contents)
            account(sys.getsizeof(contents) + sys.getsizeof(result))
            return result
        if type(item) is list:
            contents = tuple(freeze(child, depth + 1) for child in item)
            result = ("array", contents)
            account(sys.getsizeof(contents) + sys.getsizeof(result))
            return result
        _require(item is None or type(item) in (str, int, float, bool), "native JSON scalar required")
        account(sys.getsizeof(item))
        return item

    return freeze(value), used


def _thaw_json(value):
    if type(value) is tuple:
        kind, contents = value
        if kind == "object":
            return {key: _thaw_json(child) for key, child in contents}
        return [_thaw_json(child) for child in contents]
    return value


class _Reader:
    def __init__(self, artifacts, limits, checkpoint, *, optimized_decode=False,
                 max_cache_bytes=MAX_DECODE_CACHE_BYTES,
                 max_cache_heap_bytes=MAX_DECODE_CACHE_HEAP_BYTES):
        from .cache import ImmutableCAS
        _require(type(artifacts) is ImmutableCAS, "exact filesystem ImmutableCAS required")
        bound = getattr(artifacts, "max_object_bytes", None)
        _integer(bound, limits.max_record_bytes, 1)
        _require(checkpoint is None or callable(checkpoint), "checkpoint must be callable")
        _require(type(optimized_decode) is bool, "optimized_decode must be an exact boolean")
        _integer(max_cache_bytes, MAX_DECODE_CACHE_BYTES)
        _integer(max_cache_heap_bytes, MAX_DECODE_CACHE_HEAP_BYTES)
        self.artifacts, self.limits, self.checkpoint = artifacts, limits, checkpoint
        self.read_bytes = 0
        self.optimized_decode = optimized_decode
        self.max_cache_bytes, self.max_cache_heap_bytes = max_cache_bytes, max_cache_heap_bytes
        self._decoded = {}
        self.read_calls = self.structured_decodes = self.decode_cache_hits = 0
        self.decode_cache_bytes = self.decode_cache_heap_bytes = 0

    def check(self):
        if self.checkpoint is not None:
            self.checkpoint()

    def read(self, cid, *, source=False, maximum=None):
        _require(type(self.optimized_decode) is bool, "optimized_decode must be an exact boolean")
        self.check()
        _cid(cid, "raw" if source else "dag-json")
        # CAS's ordinary get() uses its owner-wide cap. Bound this read before
        # parsing by the source/artifact profile and remaining operation budget.
        maximum = self.limits.max_record_bytes if maximum is None else maximum
        bound = min(maximum, self.artifacts.max_object_bytes,
                    self.limits.max_prefix_read_bytes - self.read_bytes)
        _require(bound >= 0, "aggregate preparation reads exceed profile bound")
        path = self.artifacts.path_for(cid, source=source)
        key = (str(path.absolute()), cid)
        cached = self._decoded.get(key) if self.optimized_decode and not source else None
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = os.fstat(descriptor)
            fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns",
                      "st_mode", "st_uid", "st_nlink")
            stamp = lambda info: tuple(getattr(info, name) for name in fields)
            _require(stat.S_ISREG(before.st_mode) and before.st_size <= bound,
                     "referenced artifact exceeds profile bound or is not regular")
            parts, size = [], 0
            while True:
                part = os.read(descriptor, min(64 * 1024, bound + 1 - size))
                if not part:
                    break
                parts.append(part)
                size += len(part)
                _require(size <= bound, "referenced artifact exceeds profile bound")
            raw = b"".join(parts)
            _require(len(raw) == before.st_size and stamp(before) == stamp(os.fstat(descriptor))
                     == stamp(os.stat(path, follow_symlinks=False)), "CAS object changed during read")
        finally:
            os.close(descriptor)
        if cached is not None:
            # Reopen and read the whole leaf even on a hit. A previously verified
            # body cannot authorize different bytes or changed file custody.
            _require(raw == cached[0] and stamp(before) == cached[1]
                     and path.absolute().resolve(strict=True) == path.absolute(),
                     "cached wrapper bytes or custody changed")
            value, actual = _thaw_json(cached[2]), cid
            self.decode_cache_hits += 1
        elif source:
            value, actual = raw, cid_for_bytes(raw)
        else:
            self.structured_decodes += 1
            try:
                value = json.loads(raw)
            except (ValueError, UnicodeError, RecursionError) as exc:
                raise CodebasePreparationError("invalid artifact JSON") from exc
            _require(_wire(value, maximum) == raw, "noncanonical artifact bytes")
            actual = cid_for_structured(value)
        _require(actual == cid, "referenced artifact CID differs")
        if (cached is None and self.optimized_decode and not source
                and type(value) is dict and value.get("schema") == ARTIFACT_SCHEMA
                and value.get("kind") == "ast" and before.st_uid == os.getuid()
                and before.st_nlink == 1
                and path.absolute().resolve(strict=True) == path.absolute()
                and len(self._decoded) < MAX_DECODE_CACHE_MEMBERS
                and self.decode_cache_bytes + len(raw) <= self.max_cache_bytes):
            # Count actual retained key/raw/custody objects, including long
            # paths. The extra reserve covers cache-container allocation.
            custody = stamp(before)
            overhead = (sys.getsizeof(key) + sum(sys.getsizeof(part) for part in key)
                        + sys.getsizeof(raw) + sys.getsizeof(custody)
                        + sum(sys.getsizeof(part) for part in custody)
                        + sys.getsizeof((None, None, None)) + 1024)
            remaining = self.max_cache_heap_bytes - self.decode_cache_heap_bytes - overhead
            try:
                frozen, heap_bytes = _freeze_json(value, remaining)
            except (_DecodeCacheFull, RecursionError):
                pass  # Oversized/deep values retain the ordinary verified path.
            else:
                self._decoded[key] = (raw, custody, frozen)
                self.decode_cache_bytes += len(raw)
                self.decode_cache_heap_bytes += heap_bytes + overhead
        self.read_bytes += len(raw)
        self.read_calls += 1
        _require(self.read_bytes <= self.limits.max_prefix_read_bytes,
                 "aggregate preparation reads exceed profile bound")
        self.check()
        return value, len(raw)


def _captured_sources(reader, root):
    for entry in root["snapshot"]["entries"]:
        if entry["opaque_reason"] is None:
            _, size = reader.read(entry["source_cid"], source=True,
                                  maximum=reader.limits.max_file_bytes)
            _require(size == entry["size_bytes"], "captured source size differs")


def _page_members(page, root_cid, root, limits):
    _require(page["root_cid"] == root_cid and page["context_cid"] == root["context_cid"]
             and page["snapshot_cid"] == root["snapshot"]["snapshot_cid"],
             "foreign page root, source or context")
    start, end = page["start"], page["end"]
    members = root["snapshot"]["entries"]
    _require(start % limits.page_entries == 0
             and end == min(start + limits.page_entries, len(members))
             and start < len(members), "page is not the exact root inventory slice")
    _wire(page, limits.max_record_bytes)
    _require(page["page_membership_cid"] == cid_for_structured(members[start:end]),
             "page membership differs")
    for entry, outcome in zip(members[start:end], page["entries"]):
        _require(outcome["source_key"] == "raw:" + entry["raw_path_hex"]
                 and outcome["entry_cid"] == entry["entry_cid"]
                 and outcome["source_cid"] == entry["source_cid"]
                 and (outcome["parse_status"] == "opaque") == (entry["opaque_reason"] is not None),
                 "outcome does not bind exact captured member")
        for name in ("ast_artifact", "facts_artifact", "diagnostic_artifact"):
            if outcome[name] is not None:
                _integer(outcome[name]["bytes"], limits.max_artifact_bytes, 1)
    return members[start:end]


def _bind_page(page, root_cid, root, reader):
    members = _page_members(page, root_cid, root, reader.limits)
    for entry, outcome in zip(members, page["entries"]):
        reader.check()
        for name, kind in (("ast_artifact", "ast"), ("facts_artifact", "semantic"),
                           ("diagnostic_artifact", "diagnostic")):
            descriptor = outcome[name]
            if descriptor is None:
                continue
            value, size = reader.read(descriptor["cid"], maximum=reader.limits.max_artifact_bytes)
            _require(size == descriptor["bytes"], "artifact descriptor byte count differs")
            _closed(value, {"schema", "source_key", "entry_cid", "source_cid", "context_cid",
                            "kind", "payload", "authority"}, "source-bound artifact")
            _require(value["schema"] == ARTIFACT_SCHEMA and value["kind"] == kind
                     and value["context_cid"] == root["context_cid"]
                     and all(value[key] == outcome[key] for key in ("source_key", "entry_cid", "source_cid"))
                     and type(value["payload"]) is dict, "source artifact binding differs")
            _authority(value["authority"])


def load_preparation_root(artifacts, root_cid):
    reader = _Reader(artifacts, CodebasePreparationLimits(), None)
    value, _ = reader.read(root_cid)
    return PreparationRoot.from_dict(root_cid, value)


def load_preparation_page(artifacts, page_cid):
    reader = _Reader(artifacts, CodebasePreparationLimits(), None)
    value, _ = reader.read(page_cid)
    return PreparationPage.from_dict(page_cid, value)


def _persist_record(reader, record):
    """Reuse CAS atomic no-replace publication with bounded verification.

    The current CAS put() rereads under its owner-wide cap. Keep its fsync/link
    publisher but perform that verification through this operation's reader.
    This adapter is intentionally restricted to the exact filesystem CAS.
    """
    raw = record._payload
    _require(len(raw) <= reader.limits.max_record_bytes
             and reader.read_bytes + len(raw) <= reader.limits.max_prefix_read_bytes,
             "record publication exceeds operation budget")
    reader.check()
    target = reader.artifacts.path_for(record.artifact_cid)
    reader.artifacts._publish(target, raw)
    value, _ = reader.read(record.artifact_cid, maximum=len(raw))
    _require(_wire(value) == raw, "persisted record differs")
    reader.check()


def create_preparation_root(artifacts, snapshot, context, *, expected_head=None,
                            limits=None, checkpoint: Callable | None = None):
    """Seal an already captured inventory after checking its ordinary sources."""
    limits = CodebasePreparationLimits() if limits is None else limits
    _require(type(limits) is CodebasePreparationLimits, "exact preparation limits required")
    value = {"schema": ROOT_SCHEMA, "snapshot": snapshot, "expected_head": expected_head,
             "context": context, "context_cid": cid_for_structured(context),
             "membership_cid": cid_for_structured(snapshot["entries"]),
             "limits": limits.to_dict(), "authority": dict(_AUTHORITY)}
    root = PreparationRoot.from_dict(cid_for_structured(value), value)
    reader = _Reader(artifacts, limits, checkpoint)
    _require(len(root._payload) <= limits.max_prefix_read_bytes, "root exceeds aggregate read bound")
    _captured_sources(reader, root.to_dict())
    _persist_record(reader, root)
    return root


def _validate_prefix_with_reader(artifacts, root_cid, cursor, checkpoint, *, root=None, reader=None):
    # Internal live owners can continue the same bounded operation after its
    # root read. Public callers still reopen and verify the root here.
    if root is None:
        _require(reader is None, "an initial reader requires its just-read root")
        opening = _Reader(artifacts, CodebasePreparationLimits(), checkpoint)
        body, size = opening.read(root_cid)
        root = PreparationRoot.from_dict(root_cid, body)
        reader = _Reader(artifacts, CodebasePreparationLimits.from_dict(body["limits"]), checkpoint)
        reader.read_bytes = size
    else:
        _require(type(root) is PreparationRoot and root.artifact_cid == root_cid
                 and type(reader) is _Reader and reader.artifacts is artifacts,
                 "exact current-operation root and reader required")
        root = PreparationRoot.from_dict(root_cid, root.to_dict())
        body, size = root.to_dict(), len(root._payload)
        _require(reader.limits == CodebasePreparationLimits.from_dict(body["limits"]),
                 "initial reader differs from root limits")
    _require(size <= reader.limits.max_record_bytes and reader.read_bytes <= reader.limits.max_prefix_read_bytes,
             "root exceeds declared read bounds")
    if cursor is None:
        cursor = PreparationCursor(root_cid, 0, None)
    _require(type(cursor) is PreparationCursor, "exact preparation cursor required")
    cursor = PreparationCursor.from_dict(cursor.to_dict())
    _require(cursor.root_cid == root_cid and cursor.next_offset <= len(body["snapshot"]["entries"]),
             "foreign or overflowing cursor")
    _captured_sources(reader, body)
    pages, seen = [], set()
    previous, expected_end = cursor.previous_page_cid, cursor.next_offset
    max_pages = (reader.limits.max_entries + reader.limits.page_entries - 1) // reader.limits.page_entries
    while previous is not None:
        _require(previous not in seen and len(pages) < max_pages, "cyclic or excessive page chain")
        seen.add(previous)
        value, _ = reader.read(previous)
        page = PreparationPage.from_dict(previous, value)
        _require(value["end"] == expected_end, "gapped or forged preparation cursor")
        _bind_page(value, root_cid, body, reader)
        pages.append(page)
        previous, expected_end = value["previous_page_cid"], value["start"]
    _require(expected_end == 0, "prefix does not start at zero")
    reader.check()
    return PreparationPrefix(root, tuple(reversed(pages)), cursor.next_offset), reader


def validate_preparation_prefix(artifacts, root_cid, cursor=None, *, checkpoint=None):
    """Verify a complete contiguous prefix and its source/artifact closure.

    This reopens immutable historical source bytes, not the live repository.
    ``inventory_complete`` reports ledger coverage, including unknown outcomes.
    It never asserts analysis completeness, a catalog commit or accepted proof.
    """
    prefix, _ = _validate_prefix_with_reader(artifacts, root_cid, cursor, checkpoint)
    return prefix


def create_preparation_page(artifacts, root_cid, cursor, outcomes, *, checkpoint=None):
    """Seal one complete page after validating the existing durable prefix.

    An interruption can leave an unreferenced immutable page. The caller's
    cursor never changes, and no catalog or AST-store transaction is performed.
    """
    _require(type(outcomes) is list, "exact ordered outcomes required")
    _require(len(outcomes) <= 64, "bounded page outcomes required")
    for outcome in outcomes:
        _outcome_shape(outcome)
    prefix, reader = _validate_prefix_with_reader(artifacts, root_cid, cursor, checkpoint)
    return _append_page_to_prefix(prefix, reader, outcomes)


def _append_page_to_prefix(prefix, reader, outcomes):
    """Append to a prefix verified in this operation using its same reader.

    Internal live extraction uses this after additional context/projection
    checks. Public receivers must validate the prefix rather than constructing
    metadata and calling this internal owner integration directly.
    """
    _require(type(prefix) is PreparationPrefix and type(reader) is _Reader,
             "exact internal preparation prefix and reader required")
    _require(type(outcomes) is list and len(outcomes) <= 64, "bounded exact outcomes required")
    for outcome in outcomes:
        _outcome_shape(outcome)
    root_cid = prefix.root.artifact_cid
    _require(not prefix.inventory_complete, "preparation inventory already complete")
    root = prefix.root.to_dict()
    limits = CodebasePreparationLimits.from_dict(root["limits"])
    _require(reader.limits == limits, "operation reader differs from root limits")
    start = prefix.next_offset
    end = min(start + limits.page_entries, len(root["snapshot"]["entries"]))
    _require(len(outcomes) == end - start, "outcomes must cover the exact next inventory slice")
    value = {"schema": PAGE_SCHEMA, "root_cid": root_cid,
             "snapshot_cid": root["snapshot"]["snapshot_cid"], "context_cid": root["context_cid"],
             "start": start, "end": end, "previous_page_cid": prefix.cursor.previous_page_cid,
             "page_membership_cid": cid_for_structured(root["snapshot"]["entries"][start:end]),
             "entries": outcomes, "coverage": _coverage(outcomes), "authority": dict(_AUTHORITY)}
    page = PreparationPage.from_dict(cid_for_structured(value), value)
    _require(len(page._payload) <= limits.max_record_bytes, "page exceeds root record bound")
    # One public append shares a payload budget across prefix replay, its new
    # artifact closure and the page verification performed by CAS publication.
    _require(reader.read_bytes + len(page._payload) <= limits.max_prefix_read_bytes,
             "aggregate preparation reads exceed profile bound")
    _bind_page(page.to_dict(), root_cid, root, reader)
    _persist_record(reader, page)
    return page


__all__ = [
    "CodebasePreparationError", "CodebasePreparationLimits", "PreparationRoot",
    "PreparationPage", "PreparationCursor", "PreparationPrefix",
    "build_preparation_artifact", "create_preparation_root", "create_preparation_page",
    "load_preparation_root", "load_preparation_page", "validate_preparation_prefix",
]
