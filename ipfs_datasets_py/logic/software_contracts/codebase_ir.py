"""Snapshot-bound structural codebase IR and bounded repository preparation.

This first profile composes the existing snapshot, semantic index, AST catalog
and immutable CAS. It has structural authority only: neither parsing nor a
stored manifest establishes a behavioral property or a proof. Preparation uses
shared resource admission by default and never imports the repository it scans.
"""

from __future__ import annotations

import json
import hashlib
import math
import sys
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from pathlib import Path
from types import (BuiltinFunctionType, FunctionType, MappingProxyType, ModuleType,
                   MethodDescriptorType, WrapperDescriptorType)
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ipfs_datasets_py.duckdb_control.codebase_catalog import (
        CodebaseCatalog, CodebaseHead, CodebasePublicationReceipt,
    )

from .cache import ImmutableCAS
from .ast_ir import ASTRecord
from .content import cid_for_structured, validate_cid
from .duckdb_ast_store import ASTCatalogProjection, DuckDBASTBatchReadLimitError
from .duckdb_ingest import DuckDBASTIngestor
from .semantic_index.models import RepositoryState
from .semantic_index.scanner import RepositoryScanner
from .semantic_index.snapshot import RepositorySnapshot, snapshot_repository

CODEBASE_IR_SCHEMA = "codebase-ir-structural-manifest@1"
CODEBASE_UNIT_SCHEMA = "codebase-ir-structural-unit@1"
_UNIT_FIELDS = frozenset({
    "schema", "source_key", "entry_cid", "ast_cid", "parse_status",
})
_MANIFEST_FIELDS = frozenset({
    "schema", "authority", "snapshot", "semantic_state", "ast_revision_id",
    "units", "coverage",
})


class CodebaseIRError(ValueError):
    """A codebase artifact has invalid or unavailable source/index bindings."""


class StaleCodebaseError(CodebaseIRError):
    """A recorded structural head no longer matches the catalog or source."""


@dataclass(frozen=True, slots=True)
class CodebaseScanLimits:
    """Small-repository profile; bounds are cooperative, not an RSS guarantee."""

    max_entries: int = 256
    max_file_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        for name in ("max_entries", "max_file_bytes"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise CodebaseIRError(f"{name} must be a positive exact integer")

    def validate_reservation(self, memory_mb: int) -> None:
        if type(memory_mb) is not int or memory_mb <= 0:
            raise CodebaseIRError("memory_mb must be a positive exact integer")
        # Account for simultaneous captured bytes, parser/semantic structures,
        # serialization and database work. This is an admission estimate only.
        if self.max_entries * self.max_file_bytes > memory_mb * 1024 * 1024 // 16:
            raise CodebaseIRError("source bounds exceed the preparation memory envelope")


@dataclass(frozen=True, slots=True)
class CodebaseUnit:
    source_key: str
    entry_cid: str
    ast_cid: str | None
    parse_status: str

    def __post_init__(self) -> None:
        if type(self.source_key) is not str or not self.source_key.startswith("raw:"):
            raise CodebaseIRError("source_key must identify a captured raw path")
        validate_cid(self.entry_cid, codecs={"dag-json"})
        if self.ast_cid is not None:
            validate_cid(self.ast_cid, codecs={"dag-json"})
        if self.parse_status not in {"ok", "partial", "failed", "opaque", "unindexed"}:
            raise CodebaseIRError("unsupported structural parse status")
        if (self.ast_cid is None) != (self.parse_status in {"opaque", "unindexed"}):
            raise CodebaseIRError("AST identity and parse status disagree")

    def to_dict(self) -> dict[str, Any]:
        return {"schema": CODEBASE_UNIT_SCHEMA, "source_key": self.source_key,
                "entry_cid": self.entry_cid, "ast_cid": self.ast_cid,
                "parse_status": self.parse_status}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CodebaseUnit:
        if not isinstance(value, Mapping) or set(value) != _UNIT_FIELDS:
            raise CodebaseIRError("invalid codebase unit fields")
        if value["schema"] != CODEBASE_UNIT_SCHEMA:
            raise CodebaseIRError("unsupported codebase unit schema")
        return cls(**{key: value[key] for key in _UNIT_FIELDS - {"schema"}})


@dataclass(frozen=True, slots=True)
class CodebaseIRManifest:
    """Complete admitted inventory with source-bound structural projections."""

    snapshot: RepositorySnapshot
    semantic_state: RepositoryState
    ast_revision_id: str
    units: Sequence[CodebaseUnit]

    def __post_init__(self) -> None:
        if type(self.snapshot) is not RepositorySnapshot or type(self.semantic_state) is not RepositoryState:
            raise CodebaseIRError("manifest requires canonical snapshot and semantic state")
        if self.semantic_state.repository_id != self.snapshot.repository_id:
            raise CodebaseIRError("semantic state belongs to another repository")
        evidence = [item for item in self.semantic_state.artifacts
                    if item.artifact_id == "artifact:snapshot-evidence"]
        if len(evidence) != 1 or evidence[0].source_cid != self.snapshot.snapshot_cid:
            raise CodebaseIRError("semantic state is not bound to this snapshot")
        if evidence[0].to_dict()["metadata"].get("snapshot") != self.snapshot.to_dict():
            raise CodebaseIRError("semantic snapshot evidence does not match")
        by_path = {entry.path: entry for entry in self.snapshot.entries}
        by_raw = {entry.raw_path_hex: entry for entry in self.snapshot.entries}
        for symbol in self.semantic_state.symbols:
            entry = by_path.get(symbol.module_path)
            if entry is None or entry.is_opaque or symbol.source_cid != entry.source_cid:
                raise CodebaseIRError("semantic symbol is not bound to captured source")
        for artifact in self.semantic_state.artifacts:
            if artifact.artifact_id == "artifact:snapshot-evidence" or artifact.source_cid is None:
                continue
            entry = by_path.get(artifact.path)
            if entry is None and artifact.kind == "opaque":
                entry = by_raw.get(artifact.metadata.get("raw_path_hex"))
            if entry is None or artifact.source_cid != entry.source_cid:
                raise CodebaseIRError("semantic artifact is not bound to captured source")
        expected_revision = f"rev:{self.snapshot.repository_id}:snapshot:{self.snapshot.snapshot_cid}"
        if self.ast_revision_id != expected_revision:
            raise CodebaseIRError("AST revision does not bind the captured snapshot")
        units = tuple(self.units)
        if any(type(unit) is not CodebaseUnit for unit in units):
            raise CodebaseIRError("units must be canonical CodebaseUnit records")
        by_key = {unit.source_key: unit for unit in units}
        entries = {entry.source_key: entry for entry in self.snapshot.entries}
        if len(by_key) != len(units) or set(by_key) != set(entries):
            raise CodebaseIRError("units must account for the entire snapshot exactly once")
        for key, entry in entries.items():
            unit = by_key[key]
            if unit.entry_cid != entry.entry_cid:
                raise CodebaseIRError("unit does not bind its exact snapshot entry")
            if (unit.parse_status == "opaque") != entry.is_opaque:
                raise CodebaseIRError("opaque entry cannot acquire an AST projection")
        object.__setattr__(self, "units", tuple(sorted(units, key=lambda unit: unit.source_key)))

    @property
    def coverage(self) -> dict[str, int]:
        return {
            "inventory_entries": len(self.units),
            "captured_entries": sum(not entry.is_opaque for entry in self.snapshot.entries),
            "ast_ok": sum(unit.parse_status == "ok" for unit in self.units),
            "ast_partial": sum(unit.parse_status == "partial" for unit in self.units),
            "ast_failed": sum(unit.parse_status == "failed" for unit in self.units),
            "opaque_entries": sum(unit.parse_status == "opaque" for unit in self.units),
            "unindexed_entries": sum(unit.parse_status == "unindexed" for unit in self.units),
            "semantic_symbols": len(self.semantic_state.symbols),
            "formalized_properties": 0,
            "checked_properties": 0,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"schema": CODEBASE_IR_SCHEMA, "authority": "structural_only",
                "snapshot": self.snapshot.to_dict(),
                "semantic_state": self.semantic_state.to_dict(),
                "ast_revision_id": self.ast_revision_id,
                "units": [unit.to_dict() for unit in self.units],
                "coverage": self.coverage}

    @property
    def cid(self) -> str:
        return cid_for_structured(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CodebaseIRManifest:
        if not isinstance(value, Mapping) or set(value) != _MANIFEST_FIELDS:
            raise CodebaseIRError("invalid codebase manifest fields")
        if value["schema"] != CODEBASE_IR_SCHEMA or value["authority"] != "structural_only":
            raise CodebaseIRError("unsupported codebase manifest schema or authority")
        result = cls(RepositorySnapshot.from_dict(value["snapshot"]),
                     RepositoryState.from_dict(value["semantic_state"]),
                     value["ast_revision_id"],
                     tuple(CodebaseUnit.from_dict(unit) for unit in value["units"]))
        if value["coverage"] != result.coverage:
            raise CodebaseIRError("coverage does not recompute from the complete inventory")
        return result


# Only the pure, detached reconstruction is retained. CAS reads, current heads,
# source observations and active SQL facts are deliberately outside this memo.
_MANIFEST_MEMO_ENTRIES = 4
_MANIFEST_MEMO_BYTES = 128 * 1024 * 1024
_MANIFEST_MEMO_LOCK = threading.RLock()
_MANIFEST_MEMO: OrderedDict = OrderedDict()
_MANIFEST_MEMO_SIZE = 0
_MANIFEST_MEMO_STATS = dict(hits=0, misses=0, evictions=0, bypasses=0)


def _manifest_modules():
    from . import cache, content
    from .semantic_index import identity, models, snapshot
    return (sys.modules[__name__], content, models, snapshot, identity, cache)


def _manifest_record_types():
    from .semantic_index import models, snapshot
    return (CodebaseIRManifest, CodebaseUnit, snapshot.RepositorySnapshot,
            snapshot.SnapshotEntry, models.RepositoryState, models.SymbolRecord,
            models.ArtifactRecord, models.DependencyEdge, models.SourceSpan)


def _manifest_binding_value(value):
    import dataclasses
    if value is dataclasses.MISSING or value is dataclasses._HAS_DEFAULT_FACTORY:
        return value
    if isinstance(value, Enum):
        return (type(value), value.value)
    if value is None or type(value) in (str, int, float, bool, bytes):
        return value
    if type(value) in (tuple, list):
        return tuple(_manifest_binding_value(item) for item in value)
    if type(value) in (dict, MappingProxyType):
        return tuple(sorted((key, _manifest_binding_value(item)) for key, item in value.items()))
    if type(value) in (set, frozenset):
        return frozenset(_manifest_binding_value(item) for item in value)
    # Native class/function defaults are identity-bearing, never evaluated.
    if isinstance(value, (type, BuiltinFunctionType, MethodDescriptorType, WrapperDescriptorType)) or type(value) is FunctionType:
        return value
    raise TypeError("non-native manifest producer default")


def _manifest_function_binding(function):
    return (function, function.__code__,
            _manifest_binding_value(function.__defaults__),
            _manifest_binding_value(function.__kwdefaults__))


def _manifest_live_bindings():
    result = []
    modules = _manifest_modules()
    native_modules = {module.__name__ for module in modules}
    for module in modules:
        for name, value in sorted(vars(module).items()):
            if name.startswith("_MANIFEST_MEMO") or name == "_MANIFEST_NATIVE_BINDINGS":
                continue
            if type(value) is ModuleType:
                result.append((module.__name__, name, type(value), id(value)))
            elif type(value) is FunctionType:
                result.append((module.__name__, name, _manifest_function_binding(value)))
            elif isinstance(value, type) and value.__module__ in native_modules:
                # from_dict also consults imported aliases in its own module.
                result.append((module.__name__, name, value))
            elif name.isupper() and type(value) in (str, int, float, bool, tuple, frozenset):
                result.append((module.__name__, name, _manifest_binding_value(value)))
    for cls in _manifest_record_types():
        result.append((cls, tuple(field.name for field in fields(cls))))
        for name, value in sorted(vars(cls).items()):
            if isinstance(value, (classmethod, staticmethod)):
                value = value.__func__
            if isinstance(value, property):
                result.append((cls, name, tuple(None if fn is None else _manifest_function_binding(fn)
                                               for fn in (value.fget, value.fset, value.fdel))))
            elif type(value) is FunctionType:
                result.append((cls, name, _manifest_function_binding(value)))
            elif name.isupper() and type(value) in (str, int, tuple, frozenset):
                result.append((cls, name, _manifest_binding_value(value)))
    result.append(("native_cas_readers", _manifest_cas_bindings()))
    return tuple(result)


def _manifest_producer_key():
    from . import cache
    try:
        if not cache._structured_reader_is_native():
            return None
        if _manifest_live_bindings() != _MANIFEST_NATIVE_BINDINGS:
            return None
        return tuple((module.__name__, hashlib.sha256(Path(module.__file__).read_bytes()).digest())
                     for module in _manifest_modules())
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _manifest_clone(value):
    """Clone exact native immutable records without rerunning their validation.

    The privately retained graph is never returned, including on the miss path.
    This also prevents object.__setattr__ on a caller's frozen record from
    poisoning a later lookup. Public to_dict still returns detached lists/maps.
    """
    if value is None or type(value) in (str, int, float, bool, bytes):
        return value
    if type(value) is tuple:
        return tuple(_manifest_clone(item) for item in value)
    if type(value) is MappingProxyType:
        return MappingProxyType({key: _manifest_clone(item) for key, item in value.items()})
    if type(value) in _MANIFEST_NATIVE_RECORD_TYPES:
        result = object.__new__(type(value))
        for field in fields(value):
            item = getattr(value, field.name)
            shared_json = field.name in dict(_MANIFEST_NATIVE_JSON_FIELDS).get(type(value), ())
            object.__setattr__(result, field.name, item if shared_json else _manifest_clone(item))
        return result
    raise TypeError("manifest memo requires exact immutable native records")


def _manifest_compact_value(value, scalars, containers):
    """Intern exact immutable values using call-local, type-sensitive keys.

    Tokens keep composite keys small: no hash of source text, custom equality,
    recursive key expansion, or process-global string interning is used. Native
    records are rebuilt individually and never enter either intern table.
    """
    kind = type(value)
    if value is None or kind in (str, int, bool, bytes, float):
        # Float values are not admitted by canonical DAG-JSON, but retaining
        # exact signed-zero identity here also makes this helper type-safe.
        if kind is float and not math.isfinite(value):
            raise TypeError("non-finite manifest compact scalar")
        key = (kind, value.hex() if kind is float else value)
        prior = scalars.get(key)
        if prior is not None:
            return prior
        result = (value, len(scalars) + len(containers))
        scalars[key] = result
        return result
    if kind is tuple:
        items = tuple(_manifest_compact_value(item, scalars, containers) for item in value)
        compact = tuple(item for item, _ in items)
        if any(token is None for _, token in items):
            return compact, None
        key = (tuple, tuple(token for _, token in items))
    elif kind is MappingProxyType:
        if any(type(key) is not str for key in value):
            raise TypeError("manifest compact maps require exact string keys")
        items = tuple((_manifest_compact_value(key, scalars, containers),
                       _manifest_compact_value(item, scalars, containers))
                      for key, item in value.items())
        if any(token is None for _, (_, token) in items):
            raise TypeError("manifest compact metadata cannot contain records")
        compact = MappingProxyType({key: item for (key, _), (item, _) in items})
        # Preserve mapping iteration order as well as all durable values.
        key = (MappingProxyType, tuple((kt, vt) for (_, kt), (_, vt) in items))
    elif kind in _MANIFEST_NATIVE_RECORD_TYPES:
        result = object.__new__(kind)
        for field in fields(value):
            item = getattr(value, field.name)
            if field.name in dict(_MANIFEST_NATIVE_JSON_FIELDS).get(kind, ()):
                _manifest_require_frozen_json(item)
            object.__setattr__(result, field.name,
                               _manifest_compact_value(item, scalars, containers)[0])
        return result, None
    else:
        raise TypeError("manifest compaction requires exact immutable native records")
    prior = containers.get(key)
    if prior is not None:
        return prior
    result = (compact, len(scalars) + len(containers))
    containers[key] = result
    return result


def _manifest_compact(manifest):
    """Compact only a newly validated private graph; keep no working tables.

    Record objects remain detached, including records whose fields are equal.
    The existing return-time clone still isolates every caller from this graph.
    """
    if type(manifest) is not CodebaseIRManifest:
        raise TypeError("manifest compaction requires an exact native manifest")
    return _manifest_compact_value(manifest, {}, {})[0]


def _manifest_retained_bytes(key, manifest):
    # Account for the owned graph and serialized key, including proxy backing
    # maps. This bounds retained representation, not allocator/peak process RSS.
    raw, producer, registration = key
    pending = [raw, producer, manifest]; seen = set()
    # Registry registrations are existing library-owned immutable objects;
    # account for the newly retained registration tuple, not their shared graph.
    total = sys.getsizeof(key) + sys.getsizeof(registration) + sys.getsizeof((manifest, "", 0)) + 256
    while pending:
        value = pending.pop()
        if id(value) in seen:
            continue
        seen.add(id(value)); total += sys.getsizeof(value)
        if type(value) is tuple:
            pending.extend(value)
        elif type(value) is MappingProxyType:
            total += 2 * sys.getsizeof(dict(value))
            pending.extend(value.keys()); pending.extend(value.values())
        elif type(value) in _MANIFEST_NATIVE_RECORD_TYPES:
            for name in dict(_MANIFEST_NATIVE_JSON_FIELDS).get(type(value), ()):
                _manifest_require_frozen_json(getattr(value, name))
            pending.extend(getattr(value, field.name) for field in fields(value))
        elif value is not None and type(value) not in (str, int, float, bool, bytes):
            raise TypeError("non-native manifest retention")
    return total


def _manifest_require_frozen_json(value):
    """Shared metadata contains no record objects or mutable containers."""
    if value is None or type(value) in (str, int, float, bool):
        return
    if type(value) is tuple:
        for item in value:
            _manifest_require_frozen_json(item)
        return
    if type(value) is MappingProxyType and all(type(key) is str for key in value):
        for item in value.values():
            _manifest_require_frozen_json(item)
        return
    raise TypeError("manifest memo metadata must be recursively immutable JSON")


def _manifest_native_equal(left, right):
    """Fast affirmative equality only; other cases retain serialized comparison.

    Both graphs are checked at the caller's existing post-read boundary. Exact
    typed comparison omits only snapshot acquisition bytes/witnesses, which
    their durable serialization also omits. No caller candidate is cached.
    """
    from . import content
    producer = _manifest_producer_key()
    registration = content._memo_registration_key()
    if (producer is None or registration is None
            or type(left) is not CodebaseIRManifest or type(right) is not CodebaseIRManifest):
        return False
    pending = [(left, right)]; seen = set()
    while pending:
        a, b = pending.pop()
        if type(a) is not type(b):
            return False
        pair = (id(a), id(b))
        if pair in seen:
            continue
        seen.add(pair)
        if a is None or type(a) in (str, int, bool, bytes):
            if a != b:
                return False
            continue
        if type(a) is tuple:
            if len(a) != len(b):
                return False
            pending.extend(zip(a, b))
        elif type(a) is MappingProxyType:
            if (not all(type(key) is str for key in (*a, *b))
                    or a.keys() != b.keys()):
                return False
            pending.extend((a[key], b[key]) for key in a)
        elif any(type(a) is cls for cls in _MANIFEST_NATIVE_RECORD_TYPES):
            pending.extend((getattr(a, field.name), getattr(b, field.name)) for field in fields(a)
                           if not (type(a) is _MANIFEST_NATIVE_RECORD_TYPES[3]
                                   and field.name in {"captured_bytes", "witness"}))
        else:
            return False
    if (producer != _manifest_producer_key()
            or registration != content._memo_registration_key()):
        raise CodebaseIRError("manifest comparison producer or registry changed")
    return True


def _manifest_cas_bindings():
    """Include the concrete read owner and its JSON decoder/encoder hooks."""
    result = []
    for cls in (ImmutableCAS, json.JSONDecoder, json.JSONEncoder):
        result.append(cls)
        for name, value in sorted(vars(cls).items()):
            if isinstance(value, (classmethod, staticmethod)):
                value = value.__func__
            if type(value) is FunctionType:
                result.append((cls, name, _manifest_function_binding(value)))
            elif isinstance(value, property):
                result.append((cls, name, tuple(None if fn is None else _manifest_function_binding(fn)
                                               for fn in (value.fget, value.fset, value.fdel))))
            else:
                result.append((cls, name, type(value), id(value)))
    for module in (json, json.decoder, json.encoder, json.scanner):
        for name, value in sorted(vars(module).items()):
            if type(value) is FunctionType:
                result.append((module.__name__, name, _manifest_function_binding(value)))
            elif name in {"c_make_encoder", "c_make_scanner", "scanstring",
                          "encode_basestring", "encode_basestring_ascii"}:
                result.append((module.__name__, name, type(value), id(value)))
    for name in ("_default_decoder", "_default_encoder"):
        value = getattr(json, name)
        result.append((name, type(value), id(value),
                       tuple((key, type(item), id(item)) for key, item in sorted(vars(value).items()))))
    return tuple(result)


def _manifest_native_cas_state(cas):
    """Only ordinary native instances can use a private verified-byte replay."""
    if type(cas) is not ImmutableCAS:
        return None
    values = vars(cas)
    if set(values) != {"root", "structured_root", "source_root", "max_object_bytes"}:
        return None
    maximum = values["max_object_bytes"]
    path_type = type(Path())
    if type(maximum) is not int or maximum <= 0 or any(
            type(values[name]) is not path_type for name in ("root", "structured_root", "source_root")):
        return None
    return (maximum, *(str(values[name]) for name in ("root", "structured_root", "source_root")))


def _ast_observation_value(value):
    if not isinstance(value, type) and is_dataclass(value):
        return (type(value), tuple((field.name, _ast_observation_value(getattr(value, field.name)))
                                  for field in fields(value)))
    if type(value) is tuple:
        return tuple(_ast_observation_value(item) for item in value)
    if type(value) is dict:
        return tuple(sorted((key, _ast_observation_value(item)) for key, item in value.items()))
    return _manifest_binding_value(value)


def _ast_observation_function(function):
    wrapped = getattr(function, "__wrapped__", None)
    return (function, function.__code__, _ast_observation_value(function.__defaults__),
            _ast_observation_value(function.__kwdefaults__),
            None if wrapped is None else _ast_observation_function(wrapped))


def _ast_observation_bindings():
    """Capture live reconstruction semantics, never ASTs or read results."""
    import re
    from . import ast_ir, duckdb_ast_store, schema_versions
    modules = (ast_ir, duckdb_ast_store, schema_versions)
    names = {module.__name__ for module in modules}
    result = []
    classes = set()
    for module in modules:
        result.append(module)
        for name, value in sorted(vars(module).items()):
            if type(value) is FunctionType:
                result.append((module.__name__, name, _ast_observation_function(value)))
            elif type(value) is ModuleType:
                result.append((module.__name__, name, value))
            elif isinstance(value, re.Pattern):
                result.append((module.__name__, name, value.pattern, value.flags))
            elif isinstance(value, type) and value.__module__ in names:
                result.append((module.__name__, name, value))
                classes.add(value)
            elif name.isupper() and (type(value) in (str, int, float, bool, tuple, frozenset)
                                     or (not isinstance(value, type) and is_dataclass(value))):
                result.append((module.__name__, name, _ast_observation_value(value)))
    for cls in sorted(classes, key=lambda value: (value.__module__, value.__name__)):
        for name, value in sorted(vars(cls).items()):
            if isinstance(value, (classmethod, staticmethod)):
                value = value.__func__
            if type(value) is FunctionType:
                result.append((cls, name, _ast_observation_function(value)))
            elif isinstance(value, property):
                result.append((cls, name, tuple(None if fn is None else _ast_observation_function(fn)
                                               for fn in (value.fget, value.fset, value.fdel))))
            elif name.isupper() and type(value) in (str, int, tuple, frozenset):
                result.append((cls, name, _ast_observation_value(value)))
    result.append(_ast_observation_function(RepositoryCodebaseIndex.load_ast_artifact))
    return tuple(result)


def _ast_observation_provenance():
    """Pre-import schema/store wrappers retain the ordinary historical path."""
    from . import ast_ir, duckdb_ast_store
    if ASTRecord is not ast_ir.ASTRecord:
        return False
    functions = [(ast_ir, ast_ir.ASTRecord.from_dict.__func__),
                 (ast_ir, ast_ir.ASTRecord.from_json.__func__),
                 (duckdb_ast_store, duckdb_ast_store.project_ast_record)]
    functions.extend((duckdb_ast_store, getattr(duckdb_ast_store.DuckDBASTStore, name))
                     for name in ("_rebuild", "_verify_loaded_rows", "get_many_by_ast_cid"))
    return all(type(function) is FunctionType
               and function.__module__ == module.__name__
               and function.__code__.co_filename == module.__file__
               and not hasattr(function, "__wrapped__")
               for module, function in functions)


def _ast_observation_context(index, store):
    """Only unmodified native durable reads may discharge duplicate construction."""
    from . import cache, duckdb_ast_store
    try:
        duckdb = sys.modules.get("duckdb")
        if (type(index) is not RepositoryCodebaseIndex or "load_ast_artifact" in vars(index)
                or type(store) is not duckdb_ast_store.DuckDBASTStore
                or duckdb is None or type(store._connection) is not duckdb.DuckDBPyConnection
                or set(vars(store)) != {"_connection", "_lock", "_by_blob", "_by_ast_cid",
                                       "_by_file", "_invalidations", "_stats"}
                or not cache._structured_reader_is_native()
                or not _ast_observation_provenance()
                or _ast_observation_bindings() != _ast_observation_native_bindings):
            return None
        state = _manifest_native_cas_state(index.artifacts)
        return None if state is None else (id(store), id(store._connection), id(index.artifacts), state)
    except (AttributeError, TypeError, ValueError):
        return None


def _verify_observed_ast(artifacts, manifest, entry, unit, projection):
    """Join a fresh, fully verified SQL reconstruction to fresh exact CAS bytes.

    The CAS still performs its original bounded decode, canonical and CID
    checks. Exact payload equality transfers only the AST schema validation
    already performed in this batch; no previous observation is reused.
    """
    payload = artifacts._read_structured_payload(unit.ast_cid)
    artifacts._decode_structured_payload(unit.ast_cid, payload)
    if payload != projection.ast_blob.payload_json.encode("utf-8"):
        raise CodebaseIRError("AST artifact differs from verified active payload")
    source, revision = projection.source_file, projection.source_revision
    if (source.source_cid != entry.source_cid or source.path != entry.path
            or revision.repository_id != manifest.snapshot.repository_id
            or revision.revision != "snapshot:" + manifest.snapshot.snapshot_cid
            or revision.repository_tree_cid != manifest.snapshot.snapshot_cid):
        raise CodebaseIRError("AST artifact does not match the manifest")


def _load_manifest_from_cas(cas, manifest_cid):
    """Fresh exact body identity may reuse only a privately validated manifest.

    Unknown owners take their original get path. A miss still decodes,
    canonicalizes, hashes and schema-checks through the ordinary CAS owner.
    A hit avoids JSON materialization, not the bounded read or body digest.
    """
    from . import content
    from .cache import CacheIntegrityError
    producer = _manifest_producer_key()
    registration = content._memo_registration_key()
    state = _manifest_native_cas_state(cas) if producer is not None else None
    if producer is None or registration is None or state is None:
        return _reconstruct_manifest(cas.get(manifest_cid, expected_schema=CODEBASE_IR_SCHEMA), manifest_cid)

    def unchanged():
        if (producer != _manifest_producer_key()
                or registration != content._memo_registration_key()
                or state != _manifest_native_cas_state(cas)):
            raise CodebaseIRError("manifest read producer, registry or owner changed")

    raw = cas._read_structured_payload(manifest_cid)
    unchanged()
    key = (raw, producer, registration)
    with _MANIFEST_MEMO_LOCK:
        cached = _MANIFEST_MEMO.get(key)
        if cached is not None:
            # Exact bytes were previously canonical/schema-validated, but the
            # current body digest and registration are still checked afresh.
            identity = content._cid_from_digest_bytes(raw, codec=content.STRUCTURED_CODEC)
            if identity != manifest_cid:
                raise CacheIntegrityError("stored structured object CID mismatch")
            unchanged()
            manifest, identity, _ = cached
            if identity != manifest_cid:
                raise CodebaseIRError("manifest identity does not verify")
            result = _manifest_clone(manifest)
            unchanged()
            _MANIFEST_MEMO.move_to_end(key)
            _MANIFEST_MEMO_STATS["hits"] += 1
            return result
    value = cas._decode_structured_payload(manifest_cid, raw, expected_schema=CODEBASE_IR_SCHEMA)
    unchanged()
    result = _reconstruct_manifest(value, manifest_cid)
    unchanged()
    return result


def _reconstruct_manifest(value, expected_cid):
    """Reconstruct exact bytes; callers must freshly read/verify their CAS.

    Unknown/custom producers and registry layouts keep the original uncached
    behavior. A supported producer/registry changing during a call is refused.
    """
    from . import content
    global _MANIFEST_MEMO_SIZE
    producer = _manifest_producer_key()
    registration = content._memo_registration_key()
    if producer is None or registration is None:
        _MANIFEST_MEMO_STATS["bypasses"] += 1
        result = CodebaseIRManifest.from_dict(value)
        if result.cid != expected_cid:
            raise CodebaseIRError("manifest identity does not verify")
        return result
    raw = content.canonical_dag_json_bytes(value)
    key = (raw, producer, registration)

    def unchanged():
        if _manifest_producer_key() != producer or content._memo_registration_key() != registration:
            raise CodebaseIRError("manifest reconstruction producer or registry changed")

    with _MANIFEST_MEMO_LOCK:
        cached = _MANIFEST_MEMO.get(key)
        if cached is not None:
            manifest, identity, size = cached
            if identity != expected_cid:
                raise CodebaseIRError("manifest identity does not verify")
            result = _manifest_clone(manifest)
            unchanged()
            _MANIFEST_MEMO.move_to_end(key)
            _MANIFEST_MEMO_STATS["hits"] += 1
            return result
    # Decode detached canonical bytes, never a caller-owned mutable structure.
    manifest = CodebaseIRManifest.from_dict(json.loads(raw))
    identity = manifest.cid
    if identity != expected_cid:
        raise CodebaseIRError("manifest identity does not verify")
    unchanged()
    manifest = _manifest_compact(manifest)
    size = _manifest_retained_bytes(key, manifest)
    result = _manifest_clone(manifest)
    with _MANIFEST_MEMO_LOCK:
        unchanged()
        _MANIFEST_MEMO_STATS["misses"] += 1
        if size <= _MANIFEST_MEMO_BYTES:
            previous = _MANIFEST_MEMO.pop(key, None)
            if previous is not None:
                _MANIFEST_MEMO_SIZE -= previous[2]
            while _MANIFEST_MEMO and (len(_MANIFEST_MEMO) >= _MANIFEST_MEMO_ENTRIES
                                     or _MANIFEST_MEMO_SIZE + size > _MANIFEST_MEMO_BYTES):
                _, previous = _MANIFEST_MEMO.popitem(last=False)
                _MANIFEST_MEMO_SIZE -= previous[2]
                _MANIFEST_MEMO_STATS["evictions"] += 1
            _MANIFEST_MEMO[key] = (manifest, identity, size)
            _MANIFEST_MEMO_SIZE += size
        return result


@dataclass(frozen=True, slots=True)
class CodebaseObservation:
    """Point-in-time structural observation, without behavioral authority.

    This record does not lock a checkout against later edits. Consumers must
    reobserve it at their completion/admission boundary.
    """

    head: CodebaseHead
    manifest: CodebaseIRManifest


class RepositoryCodebaseIndex:
    """Explicit preparation API; reads never train, infer or scan a live tree.

    Inject an owner-managed DuckDBASTIngestor and ImmutableCAS for durable use.
    Without a catalog, preparation returns historical manifests. Inject the
    native codebase catalog to publish an expected-head transition; that path
    owns both the structural head and AST projection in one SQL transaction.
    """

    def __init__(self, *, ingestor: DuckDBASTIngestor | None = None,
                 artifacts: ImmutableCAS | None = None,
                 catalog: CodebaseCatalog | None = None) -> None:
        self.ingestor = ingestor if ingestor is not None else DuckDBASTIngestor()
        self.artifacts = artifacts
        if catalog is not None:
            from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
            if (type(catalog) is not CodebaseCatalog or catalog.store is not self.ingestor.store
                    or catalog.artifacts is not artifacts):
                raise CodebaseIRError("catalog must share the exact AST store and artifact owner")
        self.catalog = catalog

    def prepare(
        self, repository: str | Path, *, repository_id: str | None = None,
        previous: CodebaseIRManifest | None = None,
        limits: CodebaseScanLimits | None = None,
        exclusions: Sequence[str] | None = None,
        scheduler: Any = None, parent_lease: Any = None, cancel_event: Any = None,
        admission_timeout_seconds: float | None = None, timeout_seconds: float = 120.0,
        memory_mb: int = 512,
    ) -> CodebaseIRManifest:
        """Prepare a historical structural manifest without changing a catalog head."""
        if self.catalog is not None:
            raise CodebaseIRError("catalog-owned indexes require prepare_current with an expected head")
        return self._prepare(
            repository, repository_id=repository_id, previous=previous,
            limits=limits, exclusions=exclusions, scheduler=scheduler,
            parent_lease=parent_lease, cancel_event=cancel_event,
            admission_timeout_seconds=admission_timeout_seconds,
            timeout_seconds=timeout_seconds, memory_mb=memory_mb,
        )

    def prepare_current(
        self, repository: str | Path, *, repository_id: str,
        operation_id: str, expected_head: CodebaseHead | None,
        limits: CodebaseScanLimits | None = None,
        exclusions: Sequence[str] | None = None,
        scheduler: Any = None, parent_lease: Any = None, cancel_event: Any = None,
        admission_timeout_seconds: float | None = None, timeout_seconds: float = 120.0,
        memory_mb: int = 512,
    ) -> CodebasePublicationReceipt:
        """Atomically publish a structural head and its complete AST projection.

        ``repository_id`` explicitly names one repository view. Use distinct IDs
        for independent worktrees. Exact operation retries return the original
        receipt, which can be historical if a successor was already published.
        Use ``observe_current`` before treating a receipt as current evidence.
        """
        from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
        if self.catalog is None or self.artifacts is None:
            raise CodebaseIRError("current publication requires a durable catalog and artifacts")
        if type(repository_id) is not str or not repository_id or repository_id != repository_id.strip():
            raise CodebaseIRError("repository_id must explicitly identify a repository view")
        if expected_head is not None and (
            type(expected_head) is not CodebaseHead or expected_head.repository_id != repository_id
        ):
            raise CodebaseIRError("expected head belongs to another repository view")
        receipts = []

        def publish(manifest: CodebaseIRManifest, publication: Any, checkpoint: Any) -> None:
            # Reobserve after extraction/artifact work. This is a source fence,
            # not a filesystem lock: consumers must also check when using it.
            checkpoint()
            captured = manifest.snapshot
            observed = snapshot_repository(
                repository, repository_id=repository_id,
                max_file_bytes=captured.max_file_bytes, max_entries=captured.max_entries,
                exclusions=captured.exclusions,
            )
            checkpoint()
            if observed.snapshot_cid != captured.snapshot_cid:
                raise StaleCodebaseError("repository changed before head publication")
            # Only the durable owner may derive prior-generation invalidation.
            # The ingestor's optional process-local history is not authoritative.
            receipts.append(self.catalog.publish(
                operation_id=operation_id, manifest=manifest, expected_head=expected_head,
                projections=publication.projections, checkpoint=checkpoint,
            ))

        self._prepare(
            repository, repository_id=repository_id, limits=limits, exclusions=exclusions,
            scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            admission_timeout_seconds=admission_timeout_seconds,
            timeout_seconds=timeout_seconds, memory_mb=memory_mb, publisher=publish,
        )
        if len(receipts) != 1:
            raise CodebaseIRError("catalog did not return exactly one publication receipt")
        return receipts[0]

    def _prepare(
        self, repository: str | Path, *, repository_id: str | None = None,
        previous: CodebaseIRManifest | None = None,
        limits: CodebaseScanLimits | None = None,
        exclusions: Sequence[str] | None = None,
        scheduler: Any = None, parent_lease: Any = None, cancel_event: Any = None,
        admission_timeout_seconds: float | None = None, timeout_seconds: float = 120.0,
        memory_mb: int = 512, publisher: Any = None,
    ) -> CodebaseIRManifest:
        """Capture, extract, persist and return an exact structural manifest.

        Deadlines/cancellation are checked between stages and ingestion files;
        active Python extraction and Git commands are not forcibly preempted.
        Database threads/memory/temp-space remain the injected owner's policy.
        Prior manifests check repository lineage. Their semantic facts are
        re-extracted: content identity alone does not authenticate a producer.
        Parser-context-bound AST shards retain their own incremental reuse.
        """
        from .codebase_resources import acquire_codebase_resources, codebase_admission_timeout
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
            LeaseCancelledError, LeaseTimeoutError,
        )

        bounds = limits if limits is not None else CodebaseScanLimits()
        if type(bounds) is not CodebaseScanLimits:
            raise CodebaseIRError("limits must be CodebaseScanLimits")
        bounds.validate_reservation(memory_mb)
        if type(timeout_seconds) not in {int, float} or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise CodebaseIRError("timeout_seconds must be finite and positive")
        if admission_timeout_seconds is not None and (type(admission_timeout_seconds) not in {int, float}
                or not math.isfinite(admission_timeout_seconds) or admission_timeout_seconds < 0):
            raise CodebaseIRError("admission_timeout_seconds must be finite and nonnegative")
        if previous is not None and type(previous) is not CodebaseIRManifest:
            raise CodebaseIRError("previous must be a CodebaseIRManifest")
        deadline = time.monotonic() + timeout_seconds
        with acquire_codebase_resources(
            scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            timeout_seconds=codebase_admission_timeout(admission_timeout_seconds,
                remaining_seconds=max(0.0, deadline - time.monotonic())), memory_mb=memory_mb,
        ) as lease:
            cancelled = lease.combined_cancellation_signal(cancel_event)

            def checkpoint() -> None:
                if cancelled.is_set():
                    raise LeaseCancelledError("codebase preparation cancelled")
                if time.monotonic() >= deadline:
                    raise LeaseTimeoutError("codebase preparation deadline exceeded")

            checkpoint()
            snapshot = snapshot_repository(
                repository, repository_id=repository_id,
                max_file_bytes=bounds.max_file_bytes, max_entries=bounds.max_entries,
                exclusions=exclusions,
            )
            checkpoint()
            if previous is not None and previous.snapshot.repository_id != snapshot.repository_id:
                raise CodebaseIRError("previous manifest belongs to another repository")
            sources = {entry.source_key: entry.captured_bytes for entry in snapshot.entries
                       if not entry.is_opaque and entry.captured_bytes is not None}
            state = RepositoryScanner(repository_id=snapshot.repository_id).scan_snapshot(
                snapshot, sources,
            )
            checkpoint()
            # Seal input bytes first. Failed preparation can leave immutable,
            # unreferenced CAS objects, but never returns a partial manifest.
            if self.artifacts is not None:
                for raw in sources.values():
                    checkpoint()
                    self.artifacts.put_bytes(raw)
            prepared: list[CodebaseIRManifest] = []

            def seal_manifest(publication: Any) -> None:
                checkpoint()
                projections = {item.source_file.path: item for item in publication.projections}
                units = []
                for entry in snapshot.entries:
                    projection = projections.get(entry.path)
                    units.append(CodebaseUnit(
                        entry.source_key, entry.entry_cid,
                        None if projection is None else projection.ast_cid,
                        "opaque" if entry.is_opaque else "unindexed" if projection is None
                        else projection.ast_blob.parse_status,
                    ))
                manifest = CodebaseIRManifest(snapshot, state, publication.revision_id, tuple(units))
                if self.artifacts is not None:
                    for projection in publication.projections:
                        checkpoint()
                        body_cid = self.artifacts.put(json.loads(projection.ast_blob.payload_json))
                        if body_cid != projection.ast_cid:
                            raise CodebaseIRError("AST artifact identity does not verify")
                    self.artifacts.put(manifest.to_dict())
                checkpoint()
                prepared.append(manifest)

            # Seal the immutable manifest before the AST transaction. A failed
            # CAS write cannot invalidate the previous active AST generation.
            # A later SQL failure may leave an orphan manifest; loading a
            # manifest alone never asserts that its SQL projections are active.
            self.ingestor.ingest_snapshot(
                snapshot, checkpoint=checkpoint, before_publish=seal_manifest,
                publish_batch=(None if publisher is None else
                               lambda publication: publisher(prepared[0], publication, checkpoint)),
            )
            checkpoint()
            if len(prepared) != 1:
                raise CodebaseIRError("ingestor did not prepare exactly one manifest")
            manifest = prepared[0]
            return manifest

    def current(self, repository_id: str) -> CodebaseHead | None:
        """Read the durable head; this does not inspect current source bytes."""
        if self.catalog is None:
            raise CodebaseIRError("current lookup requires a durable catalog")
        return self.catalog.current(repository_id)

    def observe_current(
        self, repository: str | Path, *, expected_head: CodebaseHead,
        scheduler: Any = None, parent_lease: Any = None, cancel_event: Any = None,
        admission_timeout_seconds: float | None = None, timeout_seconds: float = 120.0,
        memory_mb: int = 512,
    ) -> CodebaseObservation:
        """Verify head, immutable evidence, active ASTs and current admitted bytes.

        Uses the manifest's exact capture profile under default shared admission.
        No parsing, inference, training or SQL mutation occurs. Opaque entries
        remain unknown; excluded source remains outside the observation scope.
        """
        from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
        from .codebase_resources import acquire_codebase_resources, codebase_admission_timeout
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
            LeaseCancelledError, LeaseTimeoutError,
        )
        if type(expected_head) is not CodebaseHead or self.catalog is None or self.artifacts is None:
            raise CodebaseIRError("observation requires a catalog head and artifact owner")
        if type(timeout_seconds) not in {int, float} or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise CodebaseIRError("timeout_seconds must be finite and positive")
        if admission_timeout_seconds is not None and (type(admission_timeout_seconds) not in {int, float}
                or not math.isfinite(admission_timeout_seconds) or admission_timeout_seconds < 0):
            raise CodebaseIRError("admission_timeout_seconds must be finite and nonnegative")
        deadline = time.monotonic() + timeout_seconds
        with acquire_codebase_resources(
            scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            timeout_seconds=codebase_admission_timeout(admission_timeout_seconds,
                remaining_seconds=max(0.0, deadline - time.monotonic())), memory_mb=memory_mb,
        ) as lease:
            cancelled = lease.combined_cancellation_signal(cancel_event)

            def checkpoint() -> None:
                if cancelled.is_set():
                    raise LeaseCancelledError("codebase observation cancelled")
                if time.monotonic() >= deadline:
                    raise LeaseTimeoutError("codebase observation deadline exceeded")

            def require_head() -> None:
                if self.current(expected_head.repository_id) != expected_head:
                    raise StaleCodebaseError("catalog head changed")

            checkpoint()
            require_head()
            manifest = self.load(expected_head.manifest_cid)
            if (manifest.snapshot.repository_id != expected_head.repository_id
                    or manifest.snapshot.snapshot_cid != expected_head.snapshot_cid
                    or manifest.ast_revision_id != expected_head.ast_revision_id):
                raise CodebaseIRError("catalog head does not bind its manifest")
            captured = manifest.snapshot
            CodebaseScanLimits(captured.max_entries, captured.max_file_bytes).validate_reservation(memory_mb)
            units = {unit.source_key: unit for unit in manifest.units}
            # Each batch reads current SQL rows and fully revalidates their
            # canonical projections. Keep only a bounded chunk resident while
            # independently checking CAS bodies/provenance. The fresh identity
            # fence afterwards catches invalidation or replacement during CAS
            # reads; no projection is retained across observations.
            store = self.ingestor.store
            def observe_entries(entries) -> None:
                ast_entries = [entry for entry in entries if units[entry.source_key].ast_cid is not None]
                native_context = _ast_observation_context(self, store)
                oversized = False
                try:
                    projections = store.get_many_by_ast_cid(
                        [units[entry.source_key].ast_cid for entry in ast_entries], checkpoint=checkpoint)
                except DuckDBASTBatchReadLimitError:
                    if len(ast_entries) <= 1:
                        raise
                    oversized = True
                # Leave the exception handler before retrying so its traceback
                # and partially loaded SQL rows cannot retain the failed batch.
                if oversized:
                    middle = len(entries) // 2
                    observe_entries(entries[:middle])
                    observe_entries(entries[middle:])
                    return
                if native_context is not None and _ast_observation_context(self, store) != native_context:
                    raise CodebaseIRError("AST observation owner or reconstruction semantics changed")
                by_path = dict(zip((entry.path for entry in ast_entries), projections))
                for entry in entries:
                    checkpoint()
                    if not entry.is_opaque:
                        self.artifacts.get_bytes(entry.source_cid)
                    unit = units[entry.source_key]
                    if unit.ast_cid is not None:
                        self._require_ast_projection(manifest, entry, unit, by_path[entry.path])
                    if native_context is not None and unit.parse_status in {"ok", "partial"}:
                        _verify_observed_ast(self.artifacts, manifest, entry, unit, by_path[entry.path])
                    else:
                        self.load_ast_artifact(manifest, entry.path)
                store.require_active_identities(projections, checkpoint=checkpoint)
                if native_context is not None and _ast_observation_context(self, store) != native_context:
                    raise CodebaseIRError("AST observation owner or reconstruction semantics changed")
            for offset in range(0, len(captured.entries), 32):
                observe_entries(captured.entries[offset:offset + 32])
            checkpoint()
            observed = snapshot_repository(
                repository, repository_id=expected_head.repository_id,
                max_file_bytes=captured.max_file_bytes, max_entries=captured.max_entries,
                exclusions=captured.exclusions,
            )
            checkpoint()
            if observed.snapshot_cid != captured.snapshot_cid:
                raise StaleCodebaseError("current repository differs from the published snapshot")
            require_head()
            checkpoint()
            return CodebaseObservation(expected_head, manifest)

    def load(self, manifest_cid: str) -> CodebaseIRManifest:
        if self.artifacts is None:
            raise CodebaseIRError("loading a manifest requires an immutable artifact store")
        return _load_manifest_from_cas(self.artifacts, manifest_cid)

    def lookup(self, manifest: CodebaseIRManifest, path: str) -> ASTCatalogProjection | None:
        """Return an exact active AST projection; missing expected evidence fails."""
        entry = next((item for item in manifest.snapshot.entries if item.path == path), None)
        if entry is None:
            raise CodebaseIRError("path is outside the captured inventory")
        unit = next(item for item in manifest.units if item.source_key == entry.source_key)
        if unit.ast_cid is None:
            return None
        found = self.ingestor.store.get_by_ast_cid(unit.ast_cid)
        self._require_ast_projection(manifest, entry, unit, found)
        return found

    @staticmethod
    def _require_ast_projection(manifest, entry, unit, found) -> None:
        if found is None:
            raise CodebaseIRError("AST projection is missing or invalidated")
        if (found.ast_cid != unit.ast_cid or found.source_cid != entry.source_cid
                or found.source_file.path != entry.path
                or found.source_revision.revision_id != manifest.ast_revision_id
                or found.ast_blob.parse_status != unit.parse_status):
            raise CodebaseIRError("AST projection does not match the manifest")

    def load_ast_artifact(self, manifest: CodebaseIRManifest, path: str) -> ASTRecord | None:
        """Read immutable AST history without asserting active index eligibility."""
        if self.artifacts is None:
            raise CodebaseIRError("reading an AST artifact requires an immutable artifact store")
        entry = next((item for item in manifest.snapshot.entries if item.path == path), None)
        if entry is None:
            raise CodebaseIRError("path is outside the captured inventory")
        unit = next(item for item in manifest.units if item.source_key == entry.source_key)
        if unit.ast_cid is None:
            return None
        record = ASTRecord.from_dict(self.artifacts.get(unit.ast_cid))
        provenance = record.provenance
        if (provenance.source_cid != entry.source_cid or provenance.path != path
                or provenance.repository_id != manifest.snapshot.repository_id
                or provenance.revision != "snapshot:" + manifest.snapshot.snapshot_cid
                or provenance.repository_tree_cid != manifest.snapshot.snapshot_cid):
            raise CodebaseIRError("AST artifact does not match the manifest")
        return record


# Capture native callable/default/schema identities before the first memo call;
# import stays free of filesystem reads. Live producer bytes are read on use.
_ast_observation_native_bindings = _ast_observation_bindings()
_MANIFEST_NATIVE_RECORD_TYPES = _manifest_record_types()
_MANIFEST_NATIVE_JSON_FIELDS = (
    (_MANIFEST_NATIVE_RECORD_TYPES[5], ("metadata", "signature", "annotations", "normalized_ast")),
    (_MANIFEST_NATIVE_RECORD_TYPES[6], ("metadata",)),
    (_MANIFEST_NATIVE_RECORD_TYPES[7], ("metadata",)),
)
_MANIFEST_NATIVE_BINDINGS = _manifest_live_bindings()


__all__ = ["CODEBASE_IR_SCHEMA", "CodebaseIRError", "StaleCodebaseError", "CodebaseScanLimits",
           "CodebaseUnit", "CodebaseIRManifest", "CodebaseObservation", "RepositoryCodebaseIndex"]
