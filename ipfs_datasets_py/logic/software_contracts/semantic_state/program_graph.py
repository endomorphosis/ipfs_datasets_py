"""Closed static program-graph contracts for datasets semantic authority.

This module owns the datasets ``ProgramGraphNode@1``, ``ProgramGraphEdge@1``,
``ProgramGraphSnapshot@1``, and ``ProgramGraphDelta@1`` family, together with
the adjacent callsite, function-symbol, contract-state, proof-obligation,
successor-set, dynamic-frontier, and index-manifest records.

Authority rules (normative):

* Datasets alone defines static program-graph meaning.  This module does not
  introduce a canonical HNSW/cyclic ANN graph, scheduler graph, or operational
  authority.
* Canonical bytes / CIDv1 come only from ``software_contracts.content``.
  Collection-semantics declarations reuse ``ir_core.canonical``.
* Physical IPLD/Merkle block graphs are immutable and acyclic.  Logical
  cycles (mutual recursion, cyclic imports, CFG/data-flow loops) are
  represented by immutable node/edge records that reference independently
  hashed identities; they never require cyclic CID construction.
* Unknown dynamic behavior widens an explicit ``DynamicFrontierRecord@1``.
  It is never treated as absence, and a complete successor set cannot hide it.
* Unchanged subroots are retained by CID in deltas.  Corrupt references,
  unknown fields, unsupported schema versions, ANN kinds, floats, and
  nonfinite numbers fail closed.
* Existing software-contract ``@1`` identity payloads are not modified here.
  Snapshot/delta records may project into the landed identity envelopes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence
import json
import unicodedata

from ipfs_datasets_py.logic.ir_core.canonical import (
    CanonicalizationError,
    CollectionSchema,
    CollectionSemantics,
    canonical_json_bytes as ir_canonical_json_bytes,
)
from ipfs_datasets_py.logic.software_contracts.content import (
    StructuredIdentityError,
    canonical_dag_json_bytes,
    cid_for_structured,
    decode_and_recompute_structured,
    validate_cid,
    validate_structured_value,
)


# ---------------------------------------------------------------------------
# Schema / interface constants (normative)
# ---------------------------------------------------------------------------

PROGRAM_GRAPH_NODE_INTERFACE: Final[str] = "ProgramGraphNode@1"
PROGRAM_GRAPH_EDGE_INTERFACE: Final[str] = "ProgramGraphEdge@1"
PROGRAM_GRAPH_SNAPSHOT_INTERFACE: Final[str] = "ProgramGraphSnapshot@1"
PROGRAM_GRAPH_DELTA_INTERFACE: Final[str] = "ProgramGraphDelta@1"
PROGRAM_GRAPH_INDEX_MANIFEST_INTERFACE: Final[str] = "ProgramGraphIndexManifest@1"
CALLSITE_RECORD_INTERFACE: Final[str] = "CallsiteRecord@1"
FUNCTION_SYMBOL_RECORD_INTERFACE: Final[str] = "FunctionSymbolRecord@1"
CONTRACT_STATE_RECORD_INTERFACE: Final[str] = "ContractStateRecord@1"
PROOF_OBLIGATION_GRAPH_INTERFACE: Final[str] = "ProofObligationGraph@1"
STATIC_SUCCESSOR_SET_INTERFACE: Final[str] = "StaticSuccessorSet@1"
DYNAMIC_FRONTIER_RECORD_INTERFACE: Final[str] = "DynamicFrontierRecord@1"

PROGRAM_GRAPH_NODE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.program-graph-node@1"
)
PROGRAM_GRAPH_EDGE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.program-graph-edge@1"
)
PROGRAM_GRAPH_SNAPSHOT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.program-graph-snapshot@1"
)
PROGRAM_GRAPH_DELTA_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.program-graph-delta@1"
)
PROGRAM_GRAPH_INDEX_MANIFEST_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.program-graph-index-manifest@1"
)
CALLSITE_RECORD_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.callsite-record@1"
)
FUNCTION_SYMBOL_RECORD_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.function-symbol-record@1"
)
CONTRACT_STATE_RECORD_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.contract-state-record@1"
)
PROOF_OBLIGATION_GRAPH_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.program-graph-proof-obligation-graph@1"
)
STATIC_SUCCESSOR_SET_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.static-successor-set@1"
)
DYNAMIC_FRONTIER_RECORD_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.dynamic-frontier-record@1"
)

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_COLLECTION_ITEMS: Final[int] = 100_000
MAX_SAFE_INTEGER: Final[int] = (1 << 53) - 1
MAX_METADATA_BYTES: Final[int] = 16_384

ADMITTED_LANGUAGES: Final[tuple[str, ...]] = ("python",)
UNAVAILABLE_LANGUAGES: Final[tuple[str, ...]] = (
    "javascript",
    "typescript",
    "rust",
    "c",
    "cpp",
    "java",
    "shell",
)

COLLECTION_SEMANTICS_DECLARATION: Final[dict[str, str]] = {
    "/added_edge_cids": CollectionSemantics.SET_LIKE.value,
    "/added_node_cids": CollectionSemantics.SET_LIKE.value,
    "/callsite_cids": CollectionSemantics.SET_LIKE.value,
    "/contract_state_cids": CollectionSemantics.SET_LIKE.value,
    "/edge_cids": CollectionSemantics.SET_LIKE.value,
    "/frontier_cids": CollectionSemantics.SET_LIKE.value,
    "/function_symbol_cids": CollectionSemantics.SET_LIKE.value,
    "/node_cids": CollectionSemantics.SET_LIKE.value,
    "/obligation_edge_cids": CollectionSemantics.SET_LIKE.value,
    "/obligation_node_cids": CollectionSemantics.SET_LIKE.value,
    "/proof_obligation_graph_cids": CollectionSemantics.SET_LIKE.value,
    "/reasons": CollectionSemantics.SET_LIKE.value,
    "/removed_edge_cids": CollectionSemantics.SET_LIKE.value,
    "/removed_node_cids": CollectionSemantics.SET_LIKE.value,
    "/retained_subroot_cids": CollectionSemantics.SET_LIKE.value,
    "/schema_ids": CollectionSemantics.SET_LIKE.value,
    "/successor_edge_cids": CollectionSemantics.SET_LIKE.value,
    "/successor_node_cids": CollectionSemantics.SET_LIKE.value,
    "/successor_set_cids": CollectionSemantics.SET_LIKE.value,
    "/unavailable_dimensions": CollectionSemantics.SET_LIKE.value,
    "/unresolved_edge_cids": CollectionSemantics.SET_LIKE.value,
    "/unresolved_node_cids": CollectionSemantics.SET_LIKE.value,
}

FORBIDDEN_FIELD_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "ann_score",
        "api_key",
        "authorization",
        "cosine",
        "credential",
        "distance",
        "embedding",
        "embedding_score",
        "embeddings",
        "hnsw",
        "knn",
        "model",
        "model_cid",
        "nearest",
        "password",
        "private_key",
        "rank",
        "score",
        "scores",
        "secret",
        "similarity",
        "tokenizer_cid",
        "vector",
        "vector_cid",
        "vectors",
        "wall_clock",
    }
)

FORBIDDEN_GRAPH_KINDS: Final[frozenset[str]] = frozenset(
    {
        "ann",
        "cyclic_ann",
        "embedding",
        "hnsw",
        "knn",
        "nearest",
        "similarity",
        "vector",
    }
)

FORBIDDEN_INDEX_KINDS: Final[frozenset[str]] = frozenset(
    {
        "ann",
        "cyclic_ann",
        "embedding",
        "hnsw",
        "knn",
        "nearest",
        "similarity",
        "vector",
    }
)

GRAPH_REFERENCE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "added_edge_cids",
        "added_node_cids",
        "callsite_cids",
        "contract_state_cids",
        "edge_cids",
        "frontier_cids",
        "function_symbol_cids",
        "node_cids",
        "obligation_edge_cids",
        "obligation_node_cids",
        "previous_snapshot_cid",
        "proof_obligation_graph_cids",
        "record_cid",
        "removed_edge_cids",
        "removed_node_cids",
        "retained_subroot_cids",
        "root_obligation_cid",
        "snapshot_cid",
        "source_node_cid",
        "subject_node_cid",
        "successor_edge_cids",
        "successor_node_cids",
        "successor_set_cids",
        "target_node_cid",
        "unresolved_edge_cids",
        "unresolved_node_cids",
    }
)


class ProgramGraphError(ValueError):
    """Raised when a static program-graph payload or catalog is malformed."""


class ProgramLanguage(str, Enum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    RUST = "rust"
    C = "c"
    CPP = "cpp"
    JAVA = "java"
    SHELL = "shell"


class ProgramGraphKind(str, Enum):
    STATIC_LOGICAL = "static_logical"


class ProgramGraphNodeKind(str, Enum):
    MODULE = "module"
    PACKAGE = "package"
    SOURCE = "source"
    AST = "ast"
    SYMBOL = "symbol"
    FUNCTION = "function"
    CLASS = "class"
    CALLSITE = "callsite"
    IMPORT_BINDING = "import_binding"
    CFG_BLOCK = "cfg_block"
    DATA_FLOW = "data_flow"
    EXCEPTION_HANDLER = "exception_handler"
    TYPE_BINDING = "type_binding"
    EFFECT = "effect"
    CONTRACT_STATE = "contract_state"
    TEST = "test"
    FIXTURE = "fixture"
    PROOF_OBLIGATION = "proof_obligation"
    UNRESOLVED_DYNAMIC = "unresolved_dynamic"


class ProgramGraphEdgeKind(str, Enum):
    CONTAINS = "contains"
    DECLARES = "declares"
    IMPORTS = "imports"
    CYCLIC_IMPORT = "cyclic_import"
    CALLS = "calls"
    MUTUAL_RECURSION = "mutual_recursion"
    CFG_NEXT = "cfg_next"
    CFG_BRANCH = "cfg_branch"
    DATA_FLOW = "data_flow"
    EXCEPTION_EDGE = "exception_edge"
    TYPE_OF = "type_of"
    EFFECT_OF = "effect_of"
    BINDS_CONTRACT = "binds_contract"
    TESTED_BY = "tested_by"
    PROVED_BY = "proved_by"
    SUCCESSOR = "successor"
    UNRESOLVED_DYNAMIC = "unresolved_dynamic"
    INHERITS = "inherits"
    IMPLEMENTS = "implements"
    READS_STATE = "reads_state"
    WRITES_STATE = "writes_state"
    RAISES = "raises"
    CATCHES = "catches"
    USES_FIXTURE = "uses_fixture"


class ResolutionStatus(str, Enum):
    DEFINITE = "definite"
    FINITE_MAY = "finite_may"
    UNRESOLVED = "unresolved"
    UNAVAILABLE = "unavailable"


class ContractKind(str, Enum):
    PRECONDITION = "precondition"
    POSTCONDITION = "postcondition"
    INVARIANT = "invariant"
    FRAME = "frame"
    EXCEPTIONAL = "exceptional"


class ContractDischargeStatus(str, Enum):
    UNKNOWN = "unknown"
    ASSUMED = "assumed"
    DISCHARGED = "discharged"
    VIOLATED = "violated"
    UNAVAILABLE = "unavailable"


class ProgramGraphIndexKind(str, Enum):
    ADJACENCY = "adjacency"
    SUCCESSOR = "successor"
    FRONTIER = "frontier"
    STRUCTURAL = "structural"


class DynamicFrontierReason(str, Enum):
    REFLECTION = "reflection"
    DYNAMIC_DISPATCH = "dynamic_dispatch"
    EVAL = "eval"
    EXEC = "exec"
    PLUGIN = "plugin"
    NATIVE_CALL = "native_call"
    IMPORT_HOOK = "import_hook"
    UNKNOWN_CALLEE = "unknown_callee"
    SOLVER_UNKNOWN = "solver_unknown"
    INCOMPLETE_ANALYSIS = "incomplete_analysis"


REQUIRED_NODE_KINDS: Final[frozenset[str]] = frozenset(
    item.value for item in ProgramGraphNodeKind
)
REQUIRED_EDGE_KINDS: Final[frozenset[str]] = frozenset(
    item.value for item in ProgramGraphEdgeKind
)
LOGICAL_CYCLE_REQUIRED_KINDS: Final[frozenset[str]] = frozenset(
    {
        ProgramGraphEdgeKind.CYCLIC_IMPORT.value,
        ProgramGraphEdgeKind.MUTUAL_RECURSION.value,
    }
)
UNRESOLVED_STATUSES: Final[frozenset[str]] = frozenset(
    {
        ResolutionStatus.UNRESOLVED.value,
        ResolutionStatus.UNAVAILABLE.value,
    }
)
UNRESOLVED_EDGE_KINDS: Final[frozenset[str]] = frozenset(
    {ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value}
)
UNRESOLVED_NODE_KINDS: Final[frozenset[str]] = frozenset(
    {ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value}
)
SPECIALIZED_RECORD_NODE_KINDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        ProgramGraphNodeKind.CALLSITE.value: CALLSITE_RECORD_SCHEMA,
        ProgramGraphNodeKind.FUNCTION.value: FUNCTION_SYMBOL_RECORD_SCHEMA,
        ProgramGraphNodeKind.CONTRACT_STATE.value: CONTRACT_STATE_RECORD_SCHEMA,
    }
)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise ProgramGraphError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise ProgramGraphError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise ProgramGraphError(f"{name} contains invalid text")
    return value


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    if isinstance(value, enum_type):
        return value.value
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise ProgramGraphError(f"{name} has unsupported value {value!r}") from exc


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise ProgramGraphError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ProgramGraphError(f"{name} must be a boolean")
    return value


def _nonneg_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise ProgramGraphError(f"{name} must be a nonnegative integer")
    if value > MAX_SAFE_INTEGER:
        raise ProgramGraphError(f"{name} exceeds the safe JSON integer range")
    return value


def _freeze_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_structured(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_structured(item) for item in value)
    return value


def _thaw_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_structured(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_structured(item) for item in value]
    return value


def _reject_forbidden_keys(mapping: Mapping[str, Any], name: str) -> None:
    forbidden = set(mapping) & FORBIDDEN_FIELD_MARKERS
    if forbidden:
        raise ProgramGraphError(
            f"{name} rejects non-semantic fields {sorted(forbidden)}"
        )


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProgramGraphError(f"{name} must be a mapping")
    result = _thaw_structured(dict(value))
    _reject_forbidden_keys(result, name)
    for key, item in result.items():
        if isinstance(item, Mapping):
            _reject_forbidden_keys(item, f"{name}.{key}")
    try:
        validate_structured_value(result)
    except (StructuredIdentityError, TypeError, ValueError) as exc:
        raise ProgramGraphError(f"{name} must be strict DAG-JSON") from exc
    encoded = canonical_dag_json_bytes(result)
    if len(encoded) > MAX_METADATA_BYTES:
        raise ProgramGraphError(f"{name} exceeds its byte bound")
    return _freeze_structured(result)


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise ProgramGraphError(f"{name} must be a mapping")
    extra = set(data) - fields
    missing = fields - set(data)
    if extra:
        raise ProgramGraphError(f"{name} rejects unknown fields {sorted(extra)}")
    if missing:
        raise ProgramGraphError(f"{name} missing fields {sorted(missing)}")
    _reject_forbidden_keys(data, name)
    return dict(data)


def _unique_sorted_texts(values: Iterable[Any], name: str) -> tuple[str, ...]:
    items = [_text(value, name) for value in values]
    if len(items) > MAX_COLLECTION_ITEMS:
        raise ProgramGraphError(f"{name} exceeds its item bound")
    ordered = tuple(sorted(items))
    if len(ordered) != len(set(ordered)):
        raise ProgramGraphError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_cids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    items = [_cid(value, name) for value in values]
    if len(items) > MAX_COLLECTION_ITEMS:
        raise ProgramGraphError(f"{name} exceeds its item bound")
    ordered = tuple(sorted(items))
    if len(ordered) != len(set(ordered)):
        raise ProgramGraphError(f"{name} must not contain duplicates")
    return ordered


def _ordered_texts(values: Iterable[Any], name: str) -> tuple[str, ...]:
    items = tuple(_text(value, name) for value in values)
    if len(items) > MAX_COLLECTION_ITEMS:
        raise ProgramGraphError(f"{name} exceeds its item bound")
    if len(items) != len(set(items)):
        raise ProgramGraphError(f"{name} must not contain duplicates")
    return items


def _language(value: Any, name: str = "language") -> str:
    language = _enum(value, ProgramLanguage, name)
    if language not in ADMITTED_LANGUAGES:
        raise ProgramGraphError(
            f"{name} {language!r} is typed unavailable in this profile"
        )
    return language


def _marker(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _graph_kind(value: Any, name: str = "graph_kind") -> str:
    if type(value) is str and _marker(value) in FORBIDDEN_GRAPH_KINDS:
        raise ProgramGraphError("canonical graph kind must be logical, not ANN")
    kind = _enum(value, ProgramGraphKind, name)
    if kind != ProgramGraphKind.STATIC_LOGICAL.value:
        raise ProgramGraphError(
            "static program-graph snapshots admit only static_logical"
        )
    return kind


def _index_kind(value: Any, name: str = "index_kind") -> str:
    if type(value) is str and _marker(value) in FORBIDDEN_INDEX_KINDS:
        raise ProgramGraphError(
            "HNSW/ANN indexes are not a canonical program graph"
        )
    return _enum(value, ProgramGraphIndexKind, name)


def _node_kind(value: Any, name: str = "node_kind") -> str:
    if type(value) is str and _marker(value) in FORBIDDEN_GRAPH_KINDS:
        raise ProgramGraphError("node kind must be a static program-graph class")
    return _enum(value, ProgramGraphNodeKind, name)


def _edge_kind(value: Any, name: str = "edge_kind") -> str:
    if type(value) is str and _marker(value) in FORBIDDEN_GRAPH_KINDS:
        raise ProgramGraphError("edge kind must be a static program-graph class")
    return _enum(value, ProgramGraphEdgeKind, name)


def _apply_collection_semantics(
    value: Any, *, path: tuple[str, ...], schema: CollectionSchema
) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _apply_collection_semantics(item, path=path + (key,), schema=schema)
            for key, item in value.items()
        }
    if isinstance(value, list):
        semantics = schema.semantics_for(path) or CollectionSemantics.ORDERED
        child_suffix = "*" if semantics is not CollectionSemantics.ORDERED else None
        prepared = [
            _apply_collection_semantics(
                item,
                path=path + ((child_suffix,) if child_suffix is not None else (str(index),)),
                schema=schema,
            )
            for index, item in enumerate(value)
        ]
        if semantics is CollectionSemantics.ORDERED:
            return prepared
        encoded = [(canonical_dag_json_bytes(item), item) for item in prepared]
        encoded.sort(key=lambda pair: pair[0])
        if semantics is CollectionSemantics.SET_LIKE:
            unique: list[Any] = []
            seen: set[bytes] = set()
            for blob, item in encoded:
                if blob in seen:
                    continue
                seen.add(blob)
                unique.append(item)
            return unique
        return [item for _, item in encoded]
    return value


def canonicalize_program_graph_value(value: Any) -> Any:
    """NFC-normalize, apply declared collection semantics, and reject floats."""

    try:
        validate_structured_value(value)
    except (StructuredIdentityError, TypeError, ValueError) as exc:
        raise ProgramGraphError("program-graph value must be strict DAG-JSON") from exc

    def normalize(item: Any) -> Any:
        if type(item) is str:
            return unicodedata.normalize("NFC", item)
        if isinstance(item, Mapping):
            return {normalize(key): normalize(child) for key, child in item.items()}
        if isinstance(item, list):
            return [normalize(child) for child in item]
        return item

    prepared = normalize(_thaw_structured(value))
    schema = CollectionSchema(COLLECTION_SEMANTICS_DECLARATION, require_declared=False)
    canonical = _apply_collection_semantics(prepared, path=(), schema=schema)
    try:
        validate_structured_value(canonical)
    except (StructuredIdentityError, TypeError, ValueError) as exc:
        raise ProgramGraphError(
            "canonical program-graph value must be strict DAG-JSON"
        ) from exc
    content_bytes = canonical_dag_json_bytes(canonical)
    try:
        ir_bytes = ir_canonical_json_bytes(
            canonical,
            collection_schema=CollectionSchema(None, require_declared=False),
        )
    except CanonicalizationError as exc:
        raise ProgramGraphError(
            "ir_core rejected the canonical program-graph value"
        ) from exc
    if ir_bytes != content_bytes:
        raise ProgramGraphError(
            "ir_core canonical JSON diverged from software-contract DAG-JSON"
        )
    return canonical


def program_graph_cid_for(payload: Mapping[str, Any]) -> str:
    """Return the structured CID of one canonical program-graph payload."""

    return cid_for_structured(canonicalize_program_graph_value(payload))


def canonical_program_graph_bytes(payload: Mapping[str, Any]) -> bytes:
    """Return canonical DAG-JSON bytes of one program-graph payload."""

    return canonical_dag_json_bytes(canonicalize_program_graph_value(payload))


def _verify_claimed(name: str, claimed: Any, payload: Mapping[str, Any]) -> str:
    canonical = canonicalize_program_graph_value(payload)
    try:
        return decode_and_recompute_structured(claimed, canonical)
    except Exception as exc:
        raise ProgramGraphError(f"{name} cid does not verify") from exc


def _reject_nonfinite_constant(token: str) -> None:
    raise ProgramGraphError(f"nonfinite JSON number {token!r} is rejected")


def _parse_int(token: str) -> int:
    try:
        value = int(token, 10)
    except ValueError as exc:
        raise ProgramGraphError(f"JSON number {token!r} is not an integer") from exc
    if value < -MAX_SAFE_INTEGER or value > MAX_SAFE_INTEGER:
        raise ProgramGraphError("integer is outside the safe JSON range")
    return value


def _parse_float(token: str) -> None:
    raise ProgramGraphError(
        f"JSON number {token!r} is not a finite integer; floats are rejected"
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProgramGraphError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def loads_program_graph_json(text: str | bytes) -> Any:
    """Decode JSON text, rejecting duplicate keys, NaN, and floats."""

    if type(text) is bytes:
        try:
            text = text.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProgramGraphError("program-graph JSON must be UTF-8") from exc
    if type(text) is not str:
        raise ProgramGraphError("program-graph JSON must be text or UTF-8 bytes")
    try:
        return json.loads(
            text,
            parse_int=_parse_int,
            parse_float=_parse_float,
            parse_constant=_reject_nonfinite_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except ProgramGraphError:
        raise
    except json.JSONDecodeError as exc:
        raise ProgramGraphError("program-graph JSON is not well-formed") from exc


def _from_closed(cls: type[Any], data: Mapping[str, Any]) -> Any:
    payload = _closed(data, cls._FIELDS, cls.__name__)
    claimed = payload.pop(cls.CID_FIELD)
    if payload.pop("schema") != cls.SCHEMA:
        raise ProgramGraphError(f"unsupported {cls.__name__} schema version")
    result = cls(**payload)
    _verify_claimed(cls.__name__, claimed, result.identity_payload())
    return result


def _payload_graph_refs(
    payload: Mapping[str, Any], catalog: Mapping[str, Any]
) -> tuple[str, ...]:
    refs: list[str] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, Mapping):
            for key, value in obj.items():
                if key in GRAPH_REFERENCE_FIELDS:
                    if type(value) is str and value in catalog:
                        refs.append(value)
                    elif isinstance(value, list):
                        for item in value:
                            if type(item) is str and item in catalog:
                                refs.append(item)
                else:
                    walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(payload)
    return tuple(refs)


def assert_physical_dag_acyclic(
    cid_to_payload: Mapping[str, Mapping[str, Any]],
) -> None:
    """Fail closed if assembled graph blocks form a physical CID cycle."""

    if not isinstance(cid_to_payload, Mapping):
        raise ProgramGraphError("physical DAG catalog must be a mapping")
    catalog = dict(cid_to_payload)
    adjacency = {
        cid: _payload_graph_refs(payload, catalog)
        for cid, payload in catalog.items()
    }
    white, gray, black = 0, 1, 2
    color = {cid: white for cid in catalog}

    def dfs(node: str) -> None:
        color[node] = gray
        for nxt in adjacency[node]:
            state = color.get(nxt, black)
            if state == gray:
                raise ProgramGraphError(
                    "physical IPLD block graph must be acyclic"
                )
            if state == white:
                dfs(nxt)
        color[node] = black

    for cid in catalog:
        if color[cid] == white:
            dfs(cid)


def directed_logical_cycles(
    edges: Sequence["ProgramGraphEdge"],
) -> tuple[tuple[str, ...], ...]:
    """Return immutable edge-CID tuples for each directed logical cycle."""

    adjacency: dict[str, list[ProgramGraphEdge]] = {}
    for edge in edges:
        adjacency.setdefault(str(edge.source_node_cid), []).append(edge)
    cycles: list[tuple[str, ...]] = []
    visiting: list[ProgramGraphEdge] = []
    visiting_nodes: set[str] = set()
    done: set[str] = set()

    def dfs(node: str) -> None:
        visiting_nodes.add(node)
        for edge in adjacency.get(node, ()):
            nxt = str(edge.target_node_cid)
            visiting.append(edge)
            if nxt in visiting_nodes:
                cycle_edges = []
                for item in reversed(visiting):
                    cycle_edges.append(item.program_graph_edge_cid)
                    if item.source_node_cid == nxt:
                        break
                cycles.append(tuple(sorted(cycle_edges)))
            elif nxt not in done:
                dfs(nxt)
            visiting.pop()
        visiting_nodes.remove(node)
        done.add(node)

    for source in list(adjacency):
        if source not in done:
            dfs(source)
    unique = tuple(sorted(set(cycles)))
    return unique


def is_unresolved_dynamic_edge(edge: "ProgramGraphEdge") -> bool:
    return (
        str(edge.edge_kind) in UNRESOLVED_EDGE_KINDS
        or str(edge.resolution_status) in UNRESOLVED_STATUSES
    )


def is_unresolved_dynamic_node(node: "ProgramGraphNode") -> bool:
    return str(node.node_kind) in UNRESOLVED_NODE_KINDS


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProgramGraphNode:
    """Typed static program-graph node; never an ANN vertex."""

    node_kind: ProgramGraphNodeKind | str
    language: ProgramLanguage | str
    logical_name: str
    source_cid: str
    declaration_cid: str | None = None
    environment_binding_cid: str | None = None
    subject_cid: str | None = None
    record_cid: str | None = None
    unavailable_dimensions: Sequence[str] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    SCHEMA: ClassVar[str] = PROGRAM_GRAPH_NODE_SCHEMA
    INTERFACE: ClassVar[str] = PROGRAM_GRAPH_NODE_INTERFACE
    CID_FIELD: ClassVar[str] = "program_graph_node_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "node_kind",
            "language",
            "logical_name",
            "source_cid",
            "declaration_cid",
            "environment_binding_cid",
            "subject_cid",
            "record_cid",
            "unavailable_dimensions",
            "metadata",
            "program_graph_node_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_kind", _node_kind(self.node_kind))
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(self, "logical_name", _text(self.logical_name, "logical_name"))
        object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        object.__setattr__(
            self, "declaration_cid", _optional_cid(self.declaration_cid, "declaration_cid")
        )
        object.__setattr__(
            self,
            "environment_binding_cid",
            _optional_cid(self.environment_binding_cid, "environment_binding_cid"),
        )
        object.__setattr__(
            self, "subject_cid", _optional_cid(self.subject_cid, "subject_cid")
        )
        object.__setattr__(
            self, "record_cid", _optional_cid(self.record_cid, "record_cid")
        )
        object.__setattr__(
            self,
            "unavailable_dimensions",
            _unique_sorted_texts(self.unavailable_dimensions, "unavailable_dimension"),
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "node_kind": self.node_kind,
            "language": self.language,
            "logical_name": self.logical_name,
            "source_cid": self.source_cid,
            "declaration_cid": self.declaration_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "subject_cid": self.subject_cid,
            "record_cid": self.record_cid,
            "unavailable_dimensions": list(self.unavailable_dimensions),
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def program_graph_node_cid(self) -> str:
        return program_graph_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_program_graph_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["program_graph_node_cid"] = self.program_graph_node_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProgramGraphNode":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class ProgramGraphEdge:
    """Typed static program-graph edge; logical cycles stay immutable."""

    edge_kind: ProgramGraphEdgeKind | str
    source_node_cid: str
    target_node_cid: str
    language: ProgramLanguage | str
    environment_binding_cid: str | None = None
    resolution_status: ResolutionStatus | str = ResolutionStatus.DEFINITE
    logical_cycle: bool = False
    unavailable_dimensions: Sequence[str] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    SCHEMA: ClassVar[str] = PROGRAM_GRAPH_EDGE_SCHEMA
    INTERFACE: ClassVar[str] = PROGRAM_GRAPH_EDGE_INTERFACE
    CID_FIELD: ClassVar[str] = "program_graph_edge_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "edge_kind",
            "source_node_cid",
            "target_node_cid",
            "language",
            "environment_binding_cid",
            "resolution_status",
            "logical_cycle",
            "unavailable_dimensions",
            "metadata",
            "program_graph_edge_cid",
        }
    )

    def __post_init__(self) -> None:
        kind = _edge_kind(self.edge_kind)
        status = _enum(self.resolution_status, ResolutionStatus, "resolution_status")
        cycle = _bool(self.logical_cycle, "logical_cycle")
        object.__setattr__(self, "edge_kind", kind)
        object.__setattr__(
            self, "source_node_cid", _cid(self.source_node_cid, "source_node_cid")
        )
        object.__setattr__(
            self, "target_node_cid", _cid(self.target_node_cid, "target_node_cid")
        )
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(
            self,
            "environment_binding_cid",
            _optional_cid(self.environment_binding_cid, "environment_binding_cid"),
        )
        object.__setattr__(self, "resolution_status", status)
        object.__setattr__(self, "logical_cycle", cycle)
        object.__setattr__(
            self,
            "unavailable_dimensions",
            _unique_sorted_texts(self.unavailable_dimensions, "unavailable_dimension"),
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))
        if kind in LOGICAL_CYCLE_REQUIRED_KINDS and not cycle:
            raise ProgramGraphError(
                "cyclic_import/mutual_recursion edges must be immutable logical-cycle records"
            )
        if kind in UNRESOLVED_EDGE_KINDS and status == ResolutionStatus.DEFINITE.value:
            raise ProgramGraphError(
                "unresolved dynamic edges cannot be marked definite"
            )
        if status in UNRESOLVED_STATUSES and not self.unavailable_dimensions:
            raise ProgramGraphError(
                "unresolved edges require unavailable_dimensions"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "edge_kind": self.edge_kind,
            "source_node_cid": self.source_node_cid,
            "target_node_cid": self.target_node_cid,
            "language": self.language,
            "environment_binding_cid": self.environment_binding_cid,
            "resolution_status": self.resolution_status,
            "logical_cycle": self.logical_cycle,
            "unavailable_dimensions": list(self.unavailable_dimensions),
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def program_graph_edge_cid(self) -> str:
        return program_graph_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_program_graph_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["program_graph_edge_cid"] = self.program_graph_edge_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProgramGraphEdge":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class CallsiteRecord:
    """Immutable callsite observation; unresolved callees stay explicit."""

    language: ProgramLanguage | str
    caller_logical_name: str
    callee_logical_name: str
    source_cid: str
    ordinal: int
    resolution_status: ResolutionStatus | str = ResolutionStatus.DEFINITE
    callee_declaration_cid: str | None = None
    unavailable_dimensions: Sequence[str] = ()

    SCHEMA: ClassVar[str] = CALLSITE_RECORD_SCHEMA
    INTERFACE: ClassVar[str] = CALLSITE_RECORD_INTERFACE
    CID_FIELD: ClassVar[str] = "callsite_record_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "language",
            "caller_logical_name",
            "callee_logical_name",
            "source_cid",
            "ordinal",
            "resolution_status",
            "callee_declaration_cid",
            "unavailable_dimensions",
            "callsite_record_cid",
        }
    )

    def __post_init__(self) -> None:
        status = _enum(self.resolution_status, ResolutionStatus, "resolution_status")
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(
            self,
            "caller_logical_name",
            _text(self.caller_logical_name, "caller_logical_name"),
        )
        object.__setattr__(
            self,
            "callee_logical_name",
            _text(self.callee_logical_name, "callee_logical_name"),
        )
        object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        object.__setattr__(self, "ordinal", _nonneg_int(self.ordinal, "ordinal"))
        object.__setattr__(self, "resolution_status", status)
        object.__setattr__(
            self,
            "callee_declaration_cid",
            _optional_cid(self.callee_declaration_cid, "callee_declaration_cid"),
        )
        object.__setattr__(
            self,
            "unavailable_dimensions",
            _unique_sorted_texts(self.unavailable_dimensions, "unavailable_dimension"),
        )
        if status == ResolutionStatus.DEFINITE.value and self.callee_declaration_cid is None:
            raise ProgramGraphError(
                "definite callsites require callee_declaration_cid"
            )
        if status in UNRESOLVED_STATUSES and self.callee_declaration_cid is not None:
            raise ProgramGraphError(
                "unresolved callsites cannot claim a callee declaration"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "language": self.language,
            "caller_logical_name": self.caller_logical_name,
            "callee_logical_name": self.callee_logical_name,
            "source_cid": self.source_cid,
            "ordinal": self.ordinal,
            "resolution_status": self.resolution_status,
            "callee_declaration_cid": self.callee_declaration_cid,
            "unavailable_dimensions": list(self.unavailable_dimensions),
        }

    @property
    def callsite_record_cid(self) -> str:
        return program_graph_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_program_graph_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["callsite_record_cid"] = self.callsite_record_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CallsiteRecord":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class FunctionSymbolRecord:
    """Immutable function-symbol record; callsites are separate CID blocks."""

    language: ProgramLanguage | str
    logical_name: str
    source_cid: str
    declaration_cid: str
    parameter_names: Sequence[str] = ()
    return_annotation: str = ""
    unavailable_dimensions: Sequence[str] = ()

    SCHEMA: ClassVar[str] = FUNCTION_SYMBOL_RECORD_SCHEMA
    INTERFACE: ClassVar[str] = FUNCTION_SYMBOL_RECORD_INTERFACE
    CID_FIELD: ClassVar[str] = "function_symbol_record_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "language",
            "logical_name",
            "source_cid",
            "declaration_cid",
            "parameter_names",
            "return_annotation",
            "unavailable_dimensions",
            "function_symbol_record_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(self, "logical_name", _text(self.logical_name, "logical_name"))
        object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        object.__setattr__(
            self, "declaration_cid", _cid(self.declaration_cid, "declaration_cid")
        )
        object.__setattr__(
            self,
            "parameter_names",
            _ordered_texts(self.parameter_names, "parameter_name"),
        )
        object.__setattr__(
            self,
            "return_annotation",
            _text(self.return_annotation, "return_annotation", empty=True),
        )
        object.__setattr__(
            self,
            "unavailable_dimensions",
            _unique_sorted_texts(self.unavailable_dimensions, "unavailable_dimension"),
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "language": self.language,
            "logical_name": self.logical_name,
            "source_cid": self.source_cid,
            "declaration_cid": self.declaration_cid,
            "parameter_names": list(self.parameter_names),
            "return_annotation": self.return_annotation,
            "unavailable_dimensions": list(self.unavailable_dimensions),
        }

    @property
    def function_symbol_record_cid(self) -> str:
        return program_graph_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_program_graph_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["function_symbol_record_cid"] = self.function_symbol_record_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FunctionSymbolRecord":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class ContractStateRecord:
    """Immutable contract-state projection bound to a program subject."""

    language: ProgramLanguage | str
    subject_logical_name: str
    contract_kind: ContractKind | str
    specification_cid: str
    discharge_status: ContractDischargeStatus | str = ContractDischargeStatus.UNKNOWN
    unavailable_dimensions: Sequence[str] = ()

    SCHEMA: ClassVar[str] = CONTRACT_STATE_RECORD_SCHEMA
    INTERFACE: ClassVar[str] = CONTRACT_STATE_RECORD_INTERFACE
    CID_FIELD: ClassVar[str] = "contract_state_record_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "language",
            "subject_logical_name",
            "contract_kind",
            "specification_cid",
            "discharge_status",
            "unavailable_dimensions",
            "contract_state_record_cid",
        }
    )

    def __post_init__(self) -> None:
        status = _enum(
            self.discharge_status, ContractDischargeStatus, "discharge_status"
        )
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(
            self,
            "subject_logical_name",
            _text(self.subject_logical_name, "subject_logical_name"),
        )
        object.__setattr__(
            self, "contract_kind", _enum(self.contract_kind, ContractKind, "contract_kind")
        )
        object.__setattr__(
            self, "specification_cid", _cid(self.specification_cid, "specification_cid")
        )
        object.__setattr__(self, "discharge_status", status)
        object.__setattr__(
            self,
            "unavailable_dimensions",
            _unique_sorted_texts(self.unavailable_dimensions, "unavailable_dimension"),
        )
        if status == ContractDischargeStatus.UNAVAILABLE.value and not self.unavailable_dimensions:
            raise ProgramGraphError(
                "unavailable contract state requires unavailable_dimensions"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "language": self.language,
            "subject_logical_name": self.subject_logical_name,
            "contract_kind": self.contract_kind,
            "specification_cid": self.specification_cid,
            "discharge_status": self.discharge_status,
            "unavailable_dimensions": list(self.unavailable_dimensions),
        }

    @property
    def contract_state_record_cid(self) -> str:
        return program_graph_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_program_graph_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["contract_state_record_cid"] = self.contract_state_record_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ContractStateRecord":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class ProofObligationGraph:
    """Program-graph projection of proof obligations as CID-addressed blocks.

    Distinct from the tactician ``ProofObligationGraph@1`` AND/OR planner
    graph: this record only cites already-hashed obligation nodes and edges.
    """

    language: ProgramLanguage | str
    root_obligation_cid: str
    obligation_node_cids: Sequence[str]
    obligation_edge_cids: Sequence[str] = ()
    environment_binding_cid: str | None = None
    unavailable_dimensions: Sequence[str] = ()

    SCHEMA: ClassVar[str] = PROOF_OBLIGATION_GRAPH_SCHEMA
    INTERFACE: ClassVar[str] = PROOF_OBLIGATION_GRAPH_INTERFACE
    CID_FIELD: ClassVar[str] = "proof_obligation_graph_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "language",
            "root_obligation_cid",
            "obligation_node_cids",
            "obligation_edge_cids",
            "environment_binding_cid",
            "unavailable_dimensions",
            "proof_obligation_graph_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(
            self,
            "root_obligation_cid",
            _cid(self.root_obligation_cid, "root_obligation_cid"),
        )
        object.__setattr__(
            self,
            "obligation_node_cids",
            _unique_sorted_cids(self.obligation_node_cids, "obligation_node_cid"),
        )
        object.__setattr__(
            self,
            "obligation_edge_cids",
            _unique_sorted_cids(self.obligation_edge_cids, "obligation_edge_cid"),
        )
        object.__setattr__(
            self,
            "environment_binding_cid",
            _optional_cid(self.environment_binding_cid, "environment_binding_cid"),
        )
        object.__setattr__(
            self,
            "unavailable_dimensions",
            _unique_sorted_texts(self.unavailable_dimensions, "unavailable_dimension"),
        )
        if self.root_obligation_cid not in self.obligation_node_cids:
            raise ProgramGraphError(
                "root_obligation_cid must be a member of obligation_node_cids"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "language": self.language,
            "root_obligation_cid": self.root_obligation_cid,
            "obligation_node_cids": list(self.obligation_node_cids),
            "obligation_edge_cids": list(self.obligation_edge_cids),
            "environment_binding_cid": self.environment_binding_cid,
            "unavailable_dimensions": list(self.unavailable_dimensions),
        }

    @property
    def proof_obligation_graph_cid(self) -> str:
        return program_graph_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_program_graph_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["proof_obligation_graph_cid"] = self.proof_obligation_graph_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProofObligationGraph":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class StaticSuccessorSet:
    """Conservative static successor identities; incompleteness stays explicit."""

    language: ProgramLanguage | str
    subject_node_cid: str
    successor_node_cids: Sequence[str] = ()
    successor_edge_cids: Sequence[str] = ()
    complete: bool = False
    unavailable_dimensions: Sequence[str] = ()

    SCHEMA: ClassVar[str] = STATIC_SUCCESSOR_SET_SCHEMA
    INTERFACE: ClassVar[str] = STATIC_SUCCESSOR_SET_INTERFACE
    CID_FIELD: ClassVar[str] = "static_successor_set_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "language",
            "subject_node_cid",
            "successor_node_cids",
            "successor_edge_cids",
            "complete",
            "unavailable_dimensions",
            "static_successor_set_cid",
        }
    )

    def __post_init__(self) -> None:
        complete = _bool(self.complete, "complete")
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(
            self, "subject_node_cid", _cid(self.subject_node_cid, "subject_node_cid")
        )
        object.__setattr__(
            self,
            "successor_node_cids",
            _unique_sorted_cids(self.successor_node_cids, "successor_node_cid"),
        )
        object.__setattr__(
            self,
            "successor_edge_cids",
            _unique_sorted_cids(self.successor_edge_cids, "successor_edge_cid"),
        )
        object.__setattr__(self, "complete", complete)
        object.__setattr__(
            self,
            "unavailable_dimensions",
            _unique_sorted_texts(self.unavailable_dimensions, "unavailable_dimension"),
        )
        if not complete and not self.unavailable_dimensions:
            raise ProgramGraphError(
                "incomplete successor sets require unavailable_dimensions"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "language": self.language,
            "subject_node_cid": self.subject_node_cid,
            "successor_node_cids": list(self.successor_node_cids),
            "successor_edge_cids": list(self.successor_edge_cids),
            "complete": self.complete,
            "unavailable_dimensions": list(self.unavailable_dimensions),
        }

    @property
    def static_successor_set_cid(self) -> str:
        return program_graph_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_program_graph_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["static_successor_set_cid"] = self.static_successor_set_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StaticSuccessorSet":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class DynamicFrontierRecord:
    """Explicit unresolved dynamic behavior; never encoded as absence."""

    language: ProgramLanguage | str
    unresolved_node_cids: Sequence[str] = ()
    unresolved_edge_cids: Sequence[str] = ()
    reasons: Sequence[str] = ()
    unavailable_dimensions: Sequence[str] = ()

    SCHEMA: ClassVar[str] = DYNAMIC_FRONTIER_RECORD_SCHEMA
    INTERFACE: ClassVar[str] = DYNAMIC_FRONTIER_RECORD_INTERFACE
    CID_FIELD: ClassVar[str] = "dynamic_frontier_record_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "language",
            "unresolved_node_cids",
            "unresolved_edge_cids",
            "reasons",
            "unavailable_dimensions",
            "dynamic_frontier_record_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(
            self,
            "unresolved_node_cids",
            _unique_sorted_cids(self.unresolved_node_cids, "unresolved_node_cid"),
        )
        object.__setattr__(
            self,
            "unresolved_edge_cids",
            _unique_sorted_cids(self.unresolved_edge_cids, "unresolved_edge_cid"),
        )
        reasons = tuple(
            _enum(item, DynamicFrontierReason, "reason") for item in self.reasons
        )
        object.__setattr__(self, "reasons", _unique_sorted_texts(reasons, "reason"))
        object.__setattr__(
            self,
            "unavailable_dimensions",
            _unique_sorted_texts(self.unavailable_dimensions, "unavailable_dimension"),
        )
        if (
            not self.unresolved_node_cids
            and not self.unresolved_edge_cids
            and not self.unavailable_dimensions
        ):
            raise ProgramGraphError(
                "dynamic frontier cannot be empty; unknown behavior must stay explicit"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "language": self.language,
            "unresolved_node_cids": list(self.unresolved_node_cids),
            "unresolved_edge_cids": list(self.unresolved_edge_cids),
            "reasons": list(self.reasons),
            "unavailable_dimensions": list(self.unavailable_dimensions),
        }

    @property
    def dynamic_frontier_record_cid(self) -> str:
        return program_graph_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_program_graph_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["dynamic_frontier_record_cid"] = self.dynamic_frontier_record_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DynamicFrontierRecord":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class ProgramGraphIndexManifest:
    """Rebuildable structural index bound to a snapshot; never a canonical ANN graph."""

    snapshot_cid: str
    index_kind: ProgramGraphIndexKind | str
    schema_ids: Sequence[str]
    rebuildable: bool = True
    authoritative: bool = True
    projection_cid: str | None = None

    SCHEMA: ClassVar[str] = PROGRAM_GRAPH_INDEX_MANIFEST_SCHEMA
    INTERFACE: ClassVar[str] = PROGRAM_GRAPH_INDEX_MANIFEST_INTERFACE
    CID_FIELD: ClassVar[str] = "program_graph_index_manifest_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "snapshot_cid",
            "index_kind",
            "schema_ids",
            "rebuildable",
            "authoritative",
            "projection_cid",
            "program_graph_index_manifest_cid",
        }
    )

    def __post_init__(self) -> None:
        kind = _index_kind(self.index_kind)
        rebuildable = _bool(self.rebuildable, "rebuildable")
        authoritative = _bool(self.authoritative, "authoritative")
        object.__setattr__(self, "snapshot_cid", _cid(self.snapshot_cid, "snapshot_cid"))
        object.__setattr__(self, "index_kind", kind)
        object.__setattr__(
            self, "schema_ids", _unique_sorted_texts(self.schema_ids, "schema_id")
        )
        object.__setattr__(self, "rebuildable", rebuildable)
        object.__setattr__(self, "authoritative", authoritative)
        object.__setattr__(
            self, "projection_cid", _optional_cid(self.projection_cid, "projection_cid")
        )
        if not self.schema_ids:
            raise ProgramGraphError("index manifest schema_ids must not be empty")
        if not rebuildable:
            raise ProgramGraphError("program-graph indexes must remain rebuildable")
        if self.projection_cid is not None and authoritative:
            raise ProgramGraphError(
                "projection-bound indexes cannot be canonical graph authority"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "snapshot_cid": self.snapshot_cid,
            "index_kind": self.index_kind,
            "schema_ids": list(self.schema_ids),
            "rebuildable": self.rebuildable,
            "authoritative": self.authoritative,
            "projection_cid": self.projection_cid,
        }

    @property
    def program_graph_index_manifest_cid(self) -> str:
        return program_graph_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_program_graph_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["program_graph_index_manifest_cid"] = (
            self.program_graph_index_manifest_cid
        )
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProgramGraphIndexManifest":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class ProgramGraphSnapshot:
    """Sealed ordered node/edge set at exact environment bindings."""

    language: ProgramLanguage | str
    graph_kind: ProgramGraphKind | str
    canonical_program_graph_cid: str
    node_cids: Sequence[str]
    edge_cids: Sequence[str]
    environment_binding_set_cid: str
    sealed_binding_cid: str
    callsite_cids: Sequence[str] = ()
    function_symbol_cids: Sequence[str] = ()
    contract_state_cids: Sequence[str] = ()
    proof_obligation_graph_cids: Sequence[str] = ()
    successor_set_cids: Sequence[str] = ()
    frontier_cids: Sequence[str] = ()
    retained_subroot_cids: Sequence[str] = ()
    unavailable_dimensions: Sequence[str] = ()

    SCHEMA: ClassVar[str] = PROGRAM_GRAPH_SNAPSHOT_SCHEMA
    INTERFACE: ClassVar[str] = PROGRAM_GRAPH_SNAPSHOT_INTERFACE
    CID_FIELD: ClassVar[str] = "program_graph_snapshot_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "language",
            "graph_kind",
            "canonical_program_graph_cid",
            "node_cids",
            "edge_cids",
            "environment_binding_set_cid",
            "sealed_binding_cid",
            "callsite_cids",
            "function_symbol_cids",
            "contract_state_cids",
            "proof_obligation_graph_cids",
            "successor_set_cids",
            "frontier_cids",
            "retained_subroot_cids",
            "unavailable_dimensions",
            "program_graph_snapshot_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(self, "graph_kind", _graph_kind(self.graph_kind))
        object.__setattr__(
            self,
            "canonical_program_graph_cid",
            _cid(self.canonical_program_graph_cid, "canonical_program_graph_cid"),
        )
        object.__setattr__(self, "node_cids", _unique_sorted_cids(self.node_cids, "node_cid"))
        object.__setattr__(self, "edge_cids", _unique_sorted_cids(self.edge_cids, "edge_cid"))
        object.__setattr__(
            self,
            "environment_binding_set_cid",
            _cid(self.environment_binding_set_cid, "environment_binding_set_cid"),
        )
        object.__setattr__(
            self, "sealed_binding_cid", _cid(self.sealed_binding_cid, "sealed_binding_cid")
        )
        object.__setattr__(
            self, "callsite_cids", _unique_sorted_cids(self.callsite_cids, "callsite_cid")
        )
        object.__setattr__(
            self,
            "function_symbol_cids",
            _unique_sorted_cids(self.function_symbol_cids, "function_symbol_cid"),
        )
        object.__setattr__(
            self,
            "contract_state_cids",
            _unique_sorted_cids(self.contract_state_cids, "contract_state_cid"),
        )
        object.__setattr__(
            self,
            "proof_obligation_graph_cids",
            _unique_sorted_cids(
                self.proof_obligation_graph_cids, "proof_obligation_graph_cid"
            ),
        )
        object.__setattr__(
            self,
            "successor_set_cids",
            _unique_sorted_cids(self.successor_set_cids, "successor_set_cid"),
        )
        object.__setattr__(
            self, "frontier_cids", _unique_sorted_cids(self.frontier_cids, "frontier_cid")
        )
        object.__setattr__(
            self,
            "retained_subroot_cids",
            _unique_sorted_cids(self.retained_subroot_cids, "retained_subroot_cid"),
        )
        object.__setattr__(
            self,
            "unavailable_dimensions",
            _unique_sorted_texts(self.unavailable_dimensions, "unavailable_dimension"),
        )
        extra_subroots = set(self.retained_subroot_cids) - set(self.node_cids)
        if extra_subroots:
            raise ProgramGraphError(
                "retained subroots must be node identities in the snapshot"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "language": self.language,
            "graph_kind": self.graph_kind,
            "canonical_program_graph_cid": self.canonical_program_graph_cid,
            "node_cids": list(self.node_cids),
            "edge_cids": list(self.edge_cids),
            "environment_binding_set_cid": self.environment_binding_set_cid,
            "sealed_binding_cid": self.sealed_binding_cid,
            "callsite_cids": list(self.callsite_cids),
            "function_symbol_cids": list(self.function_symbol_cids),
            "contract_state_cids": list(self.contract_state_cids),
            "proof_obligation_graph_cids": list(self.proof_obligation_graph_cids),
            "successor_set_cids": list(self.successor_set_cids),
            "frontier_cids": list(self.frontier_cids),
            "retained_subroot_cids": list(self.retained_subroot_cids),
            "unavailable_dimensions": list(self.unavailable_dimensions),
        }

    @property
    def program_graph_snapshot_cid(self) -> str:
        return program_graph_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_program_graph_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["program_graph_snapshot_cid"] = self.program_graph_snapshot_cid
        return value

    def to_identity_record(self) -> dict[str, Any]:
        """Project the landed snapshot identity envelope without collapsing CIDs."""

        from ipfs_datasets_py.logic.software_contracts.semantic_state.program_identity import (
            ProgramGraphSnapshotIdentity,
        )

        identity = ProgramGraphSnapshotIdentity(
            canonical_program_graph_cid=self.canonical_program_graph_cid,
            node_cids=self.node_cids,
            edge_cids=self.edge_cids,
            environment_binding_set_cid=self.environment_binding_set_cid,
            sealed_binding_cid=self.sealed_binding_cid,
        )
        return identity.to_dict()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProgramGraphSnapshot":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class ProgramGraphDelta:
    """Pure change record that retains unchanged subroots."""

    previous_snapshot_cid: str
    added_node_cids: Sequence[str] = ()
    removed_node_cids: Sequence[str] = ()
    added_edge_cids: Sequence[str] = ()
    removed_edge_cids: Sequence[str] = ()
    retained_subroot_cids: Sequence[str] = ()

    SCHEMA: ClassVar[str] = PROGRAM_GRAPH_DELTA_SCHEMA
    INTERFACE: ClassVar[str] = PROGRAM_GRAPH_DELTA_INTERFACE
    CID_FIELD: ClassVar[str] = "program_graph_delta_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "previous_snapshot_cid",
            "added_node_cids",
            "removed_node_cids",
            "added_edge_cids",
            "removed_edge_cids",
            "retained_subroot_cids",
            "program_graph_delta_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "previous_snapshot_cid",
            _cid(self.previous_snapshot_cid, "previous_snapshot_cid"),
        )
        object.__setattr__(
            self, "added_node_cids", _unique_sorted_cids(self.added_node_cids, "added_node_cid")
        )
        object.__setattr__(
            self,
            "removed_node_cids",
            _unique_sorted_cids(self.removed_node_cids, "removed_node_cid"),
        )
        object.__setattr__(
            self, "added_edge_cids", _unique_sorted_cids(self.added_edge_cids, "added_edge_cid")
        )
        object.__setattr__(
            self,
            "removed_edge_cids",
            _unique_sorted_cids(self.removed_edge_cids, "removed_edge_cid"),
        )
        object.__setattr__(
            self,
            "retained_subroot_cids",
            _unique_sorted_cids(self.retained_subroot_cids, "retained_subroot_cid"),
        )
        overlap_nodes = set(self.added_node_cids) & set(self.removed_node_cids)
        overlap_edges = set(self.added_edge_cids) & set(self.removed_edge_cids)
        if overlap_nodes or overlap_edges:
            raise ProgramGraphError("delta cannot add and remove the same identity")
        retained_removed = set(self.retained_subroot_cids) & set(self.removed_node_cids)
        if retained_removed:
            raise ProgramGraphError("unchanged subroots cannot be removed")
        retained_added = set(self.retained_subroot_cids) & set(self.added_node_cids)
        if retained_added:
            raise ProgramGraphError("unchanged subroots cannot be added")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "previous_snapshot_cid": self.previous_snapshot_cid,
            "added_node_cids": list(self.added_node_cids),
            "removed_node_cids": list(self.removed_node_cids),
            "added_edge_cids": list(self.added_edge_cids),
            "removed_edge_cids": list(self.removed_edge_cids),
            "retained_subroot_cids": list(self.retained_subroot_cids),
        }

    @property
    def program_graph_delta_cid(self) -> str:
        return program_graph_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_program_graph_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["program_graph_delta_cid"] = self.program_graph_delta_cid
        return value

    def to_identity_record(self) -> dict[str, Any]:
        from ipfs_datasets_py.logic.software_contracts.semantic_state.program_identity import (
            ProgramGraphDeltaIdentity,
        )

        identity = ProgramGraphDeltaIdentity(
            previous_snapshot_cid=self.previous_snapshot_cid,
            added_node_cids=self.added_node_cids,
            removed_node_cids=self.removed_node_cids,
            added_edge_cids=self.added_edge_cids,
            removed_edge_cids=self.removed_edge_cids,
            retained_subroot_cids=self.retained_subroot_cids,
        )
        return identity.to_dict()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProgramGraphDelta":
        return _from_closed(cls, data)


PROGRAM_GRAPH_RECORD_TYPES: Final[tuple[type, ...]] = (
    ProgramGraphNode,
    ProgramGraphEdge,
    CallsiteRecord,
    FunctionSymbolRecord,
    ContractStateRecord,
    ProofObligationGraph,
    StaticSuccessorSet,
    DynamicFrontierRecord,
    ProgramGraphIndexManifest,
    ProgramGraphSnapshot,
    ProgramGraphDelta,
)

_SCHEMA_TO_CLASS: Final[dict[str, type]] = {
    cls.SCHEMA: cls for cls in PROGRAM_GRAPH_RECORD_TYPES
}


def decode_program_graph_record(data: Mapping[str, Any]) -> Any:
    """Dispatch one closed program-graph payload to its versioned record type."""

    if not isinstance(data, Mapping):
        raise ProgramGraphError("program-graph record must be a mapping")
    schema = data.get("schema")
    record_type = _SCHEMA_TO_CLASS.get(schema) if type(schema) is str else None
    if record_type is None:
        raise ProgramGraphError(f"unsupported program-graph schema {schema!r}")
    return record_type.from_dict(data)


def load_payload_schema() -> dict[str, Any]:
    """Load the packaged JSON Schema for program-graph payloads."""

    from pathlib import Path

    path = Path(__file__).resolve().parent / "schemas" / "program-graph.payload.schema.json"
    return loads_program_graph_json(path.read_text(encoding="utf-8"))


def _record_cid(record: Any) -> str:
    return getattr(record, record.CID_FIELD)


def _index_records(records: Sequence[Any], expected_type: type, name: str) -> dict[str, Any]:
    indexed: dict[str, Any] = {}
    for item in records:
        if not isinstance(item, expected_type):
            raise ProgramGraphError(f"{name} must contain {expected_type.__name__} values")
        cid = _record_cid(item)
        if cid in indexed:
            raise ProgramGraphError(f"{name} identities must be unique")
        indexed[cid] = item
    return indexed


def _canonical_graph_cid(
    *,
    language: str,
    node_cids: Sequence[str],
    edge_cids: Sequence[str],
    environment_binding_set_cid: str,
    unavailable_dimensions: Sequence[str],
) -> str:
    from ipfs_datasets_py.logic.software_contracts.semantic_state.program_identity import (
        CanonicalProgramGraphIdentity,
    )

    identity = CanonicalProgramGraphIdentity(
        language=language,
        graph_kind=ProgramGraphKind.STATIC_LOGICAL.value,
        node_cids=node_cids,
        edge_cids=edge_cids,
        environment_binding_set_cid=environment_binding_set_cid,
        unavailable_dimensions=unavailable_dimensions,
    )
    return identity.canonical_program_graph_cid


def verify_program_graph_catalog(
    snapshot: ProgramGraphSnapshot,
    *,
    nodes: Sequence[ProgramGraphNode],
    edges: Sequence[ProgramGraphEdge],
    callsites: Sequence[CallsiteRecord] = (),
    function_symbols: Sequence[FunctionSymbolRecord] = (),
    contract_states: Sequence[ContractStateRecord] = (),
    proof_obligation_graphs: Sequence[ProofObligationGraph] = (),
    successor_sets: Sequence[StaticSuccessorSet] = (),
    frontiers: Sequence[DynamicFrontierRecord] = (),
) -> None:
    """Fail closed unless snapshot references resolve against the supplied records."""

    if not isinstance(snapshot, ProgramGraphSnapshot):
        raise ProgramGraphError("snapshot must be a ProgramGraphSnapshot")
    node_index = _index_records(nodes, ProgramGraphNode, "nodes")
    edge_index = _index_records(edges, ProgramGraphEdge, "edges")
    callsite_index = _index_records(callsites, CallsiteRecord, "callsites")
    function_index = _index_records(
        function_symbols, FunctionSymbolRecord, "function_symbols"
    )
    contract_index = _index_records(
        contract_states, ContractStateRecord, "contract_states"
    )
    pog_index = _index_records(
        proof_obligation_graphs, ProofObligationGraph, "proof_obligation_graphs"
    )
    successor_index = _index_records(
        successor_sets, StaticSuccessorSet, "successor_sets"
    )
    frontier_index = _index_records(frontiers, DynamicFrontierRecord, "frontiers")

    if tuple(sorted(node_index)) != tuple(snapshot.node_cids):
        raise ProgramGraphError("snapshot node_cids do not match supplied nodes")
    if tuple(sorted(edge_index)) != tuple(snapshot.edge_cids):
        raise ProgramGraphError("snapshot edge_cids do not match supplied edges")
    if tuple(sorted(callsite_index)) != tuple(snapshot.callsite_cids):
        raise ProgramGraphError("snapshot callsite_cids do not match supplied callsites")
    if tuple(sorted(function_index)) != tuple(snapshot.function_symbol_cids):
        raise ProgramGraphError(
            "snapshot function_symbol_cids do not match supplied function symbols"
        )
    if tuple(sorted(contract_index)) != tuple(snapshot.contract_state_cids):
        raise ProgramGraphError(
            "snapshot contract_state_cids do not match supplied contract states"
        )
    if tuple(sorted(pog_index)) != tuple(snapshot.proof_obligation_graph_cids):
        raise ProgramGraphError(
            "snapshot proof_obligation_graph_cids do not match supplied graphs"
        )
    if tuple(sorted(successor_index)) != tuple(snapshot.successor_set_cids):
        raise ProgramGraphError(
            "snapshot successor_set_cids do not match supplied successor sets"
        )
    if tuple(sorted(frontier_index)) != tuple(snapshot.frontier_cids):
        raise ProgramGraphError("snapshot frontier_cids do not match supplied frontiers")

    specialized = {**callsite_index, **function_index, **contract_index}
    for node in nodes:
        if node.record_cid is None:
            continue
        record = specialized.get(node.record_cid)
        if record is None:
            raise ProgramGraphError("corrupt node record_cid does not resolve")
        expected_schema = SPECIALIZED_RECORD_NODE_KINDS.get(str(node.node_kind))
        if expected_schema is not None and record.SCHEMA != expected_schema:
            raise ProgramGraphError("node record_cid schema does not match node_kind")

    for edge in edges:
        if edge.source_node_cid not in node_index or edge.target_node_cid not in node_index:
            raise ProgramGraphError("corrupt edge reference does not resolve")

    for successor in successor_sets:
        if successor.subject_node_cid not in node_index:
            raise ProgramGraphError("corrupt successor subject does not resolve")
        missing_nodes = set(successor.successor_node_cids) - set(node_index)
        missing_edges = set(successor.successor_edge_cids) - set(edge_index)
        if missing_nodes or missing_edges:
            raise ProgramGraphError("corrupt successor reference does not resolve")

    for pog in proof_obligation_graphs:
        missing_nodes = set(pog.obligation_node_cids) - set(node_index)
        missing_edges = set(pog.obligation_edge_cids) - set(edge_index)
        if missing_nodes or missing_edges:
            raise ProgramGraphError("corrupt proof-obligation reference does not resolve")

    unresolved_nodes = {
        node.program_graph_node_cid
        for node in nodes
        if is_unresolved_dynamic_node(node)
    }
    unresolved_edges = {
        edge.program_graph_edge_cid
        for edge in edges
        if is_unresolved_dynamic_edge(edge)
    }
    incomplete_successors = [
        item for item in successor_sets if item.complete is False
    ]
    covered_nodes: set[str] = set()
    covered_edges: set[str] = set()
    for frontier in frontiers:
        missing_nodes = set(frontier.unresolved_node_cids) - set(node_index)
        missing_edges = set(frontier.unresolved_edge_cids) - set(edge_index)
        if missing_nodes or missing_edges:
            raise ProgramGraphError("corrupt frontier reference does not resolve")
        covered_nodes.update(frontier.unresolved_node_cids)
        covered_edges.update(frontier.unresolved_edge_cids)

    uncovered_nodes = unresolved_nodes - covered_nodes
    uncovered_edges = unresolved_edges - covered_edges
    if uncovered_nodes or uncovered_edges or (incomplete_successors and not frontiers):
        raise ProgramGraphError(
            "unknown dynamic behavior must stay explicit on the frontier"
        )

    cycles = directed_logical_cycles(edges)
    edge_by_cid = {edge.program_graph_edge_cid: edge for edge in edges}
    for cycle in cycles:
        if not any(edge_by_cid[cid].logical_cycle for cid in cycle):
            raise ProgramGraphError(
                "logical cycles must use immutable logical-cycle records"
            )

    catalog: dict[str, Mapping[str, Any]] = {}
    for record in (
        *nodes,
        *edges,
        *callsites,
        *function_symbols,
        *contract_states,
        *proof_obligation_graphs,
        *successor_sets,
        *frontiers,
        snapshot,
    ):
        catalog[_record_cid(record)] = record.identity_payload()
    assert_physical_dag_acyclic(catalog)


def assemble_program_graph_snapshot(
    *,
    language: ProgramLanguage | str = ProgramLanguage.PYTHON,
    nodes: Sequence[ProgramGraphNode],
    edges: Sequence[ProgramGraphEdge],
    environment_binding_set_cid: str,
    sealed_binding_cid: str,
    callsites: Sequence[CallsiteRecord] = (),
    function_symbols: Sequence[FunctionSymbolRecord] = (),
    contract_states: Sequence[ContractStateRecord] = (),
    proof_obligation_graphs: Sequence[ProofObligationGraph] = (),
    successor_sets: Sequence[StaticSuccessorSet] = (),
    frontiers: Sequence[DynamicFrontierRecord] = (),
    retained_subroot_cids: Sequence[str] = (),
    unavailable_dimensions: Sequence[str] = (),
    canonical_program_graph_cid: str | None = None,
) -> ProgramGraphSnapshot:
    """Assemble a sealed snapshot from immutable records and fail closed on corruption."""

    language_value = _language(language)
    node_cids = tuple(sorted(_record_cid(item) for item in nodes))
    edge_cids = tuple(sorted(_record_cid(item) for item in edges))
    computed_canonical = _canonical_graph_cid(
        language=language_value,
        node_cids=node_cids,
        edge_cids=edge_cids,
        environment_binding_set_cid=environment_binding_set_cid,
        unavailable_dimensions=unavailable_dimensions,
    )
    if canonical_program_graph_cid is None:
        canonical_program_graph_cid = computed_canonical
    elif _cid(canonical_program_graph_cid, "canonical_program_graph_cid") != computed_canonical:
        raise ProgramGraphError("canonical_program_graph_cid does not verify")
    snapshot = ProgramGraphSnapshot(
        language=language_value,
        graph_kind=ProgramGraphKind.STATIC_LOGICAL,
        canonical_program_graph_cid=canonical_program_graph_cid,
        node_cids=node_cids,
        edge_cids=edge_cids,
        environment_binding_set_cid=environment_binding_set_cid,
        sealed_binding_cid=sealed_binding_cid,
        callsite_cids=tuple(_record_cid(item) for item in callsites),
        function_symbol_cids=tuple(_record_cid(item) for item in function_symbols),
        contract_state_cids=tuple(_record_cid(item) for item in contract_states),
        proof_obligation_graph_cids=tuple(
            _record_cid(item) for item in proof_obligation_graphs
        ),
        successor_set_cids=tuple(_record_cid(item) for item in successor_sets),
        frontier_cids=tuple(_record_cid(item) for item in frontiers),
        retained_subroot_cids=retained_subroot_cids,
        unavailable_dimensions=unavailable_dimensions,
    )
    verify_program_graph_catalog(
        snapshot,
        nodes=nodes,
        edges=edges,
        callsites=callsites,
        function_symbols=function_symbols,
        contract_states=contract_states,
        proof_obligation_graphs=proof_obligation_graphs,
        successor_sets=successor_sets,
        frontiers=frontiers,
    )
    return snapshot


def bind_index_manifest(
    manifest: ProgramGraphIndexManifest,
    snapshot: ProgramGraphSnapshot,
) -> ProgramGraphIndexManifest:
    """Fail closed unless the rebuildable index cites this snapshot."""

    if not isinstance(manifest, ProgramGraphIndexManifest):
        raise ProgramGraphError("manifest must be a ProgramGraphIndexManifest")
    if not isinstance(snapshot, ProgramGraphSnapshot):
        raise ProgramGraphError("snapshot must be a ProgramGraphSnapshot")
    if manifest.snapshot_cid != snapshot.program_graph_snapshot_cid:
        raise ProgramGraphError("index manifest is not bound to the supplied snapshot")
    return manifest


def delta_between_snapshots(
    previous: ProgramGraphSnapshot,
    current: ProgramGraphSnapshot,
) -> ProgramGraphDelta:
    """Return the exact node/edge delta, retaining every unchanged subroot CID."""

    if not isinstance(previous, ProgramGraphSnapshot) or not isinstance(
        current, ProgramGraphSnapshot
    ):
        raise ProgramGraphError("delta comparison requires program-graph snapshots")
    prev_nodes = set(previous.node_cids)
    curr_nodes = set(current.node_cids)
    prev_edges = set(previous.edge_cids)
    curr_edges = set(current.edge_cids)
    return ProgramGraphDelta(
        previous_snapshot_cid=previous.program_graph_snapshot_cid,
        added_node_cids=tuple(sorted(curr_nodes - prev_nodes)),
        removed_node_cids=tuple(sorted(prev_nodes - curr_nodes)),
        added_edge_cids=tuple(sorted(curr_edges - prev_edges)),
        removed_edge_cids=tuple(sorted(prev_edges - curr_edges)),
        retained_subroot_cids=tuple(sorted(prev_nodes & curr_nodes)),
    )


def apply_program_graph_delta(
    previous: ProgramGraphSnapshot,
    delta: ProgramGraphDelta,
) -> dict[str, tuple[str, ...]]:
    """Apply a sealed delta to previous CID sets; unchanged subroots are required."""

    if not isinstance(previous, ProgramGraphSnapshot):
        raise ProgramGraphError("previous must be a ProgramGraphSnapshot")
    if not isinstance(delta, ProgramGraphDelta):
        raise ProgramGraphError("delta must be a ProgramGraphDelta")
    if delta.previous_snapshot_cid != previous.program_graph_snapshot_cid:
        raise ProgramGraphError("delta is not bound to the previous snapshot")
    prev_nodes = set(previous.node_cids)
    prev_edges = set(previous.edge_cids)
    if not set(delta.removed_node_cids) <= prev_nodes:
        raise ProgramGraphError("corrupt delta removes an unknown node")
    if not set(delta.removed_edge_cids) <= prev_edges:
        raise ProgramGraphError("corrupt delta removes an unknown edge")
    if set(delta.added_node_cids) & prev_nodes:
        raise ProgramGraphError("corrupt delta adds a node already present")
    if set(delta.added_edge_cids) & prev_edges:
        raise ProgramGraphError("corrupt delta adds an edge already present")
    remaining_nodes = (prev_nodes - set(delta.removed_node_cids)) | set(
        delta.added_node_cids
    )
    remaining_edges = (prev_edges - set(delta.removed_edge_cids)) | set(
        delta.added_edge_cids
    )
    if not set(delta.retained_subroot_cids) <= remaining_nodes:
        raise ProgramGraphError("unchanged subroots must be preserved")
    if not set(delta.retained_subroot_cids) <= prev_nodes:
        raise ProgramGraphError("retained subroots must exist in the previous snapshot")
    return {
        "node_cids": tuple(sorted(remaining_nodes)),
        "edge_cids": tuple(sorted(remaining_edges)),
        "retained_subroot_cids": tuple(delta.retained_subroot_cids),
    }


__all__ = [
    "ADMITTED_LANGUAGES",
    "CALLSITE_RECORD_INTERFACE",
    "CALLSITE_RECORD_SCHEMA",
    "COLLECTION_SEMANTICS_DECLARATION",
    "CONTRACT_STATE_RECORD_INTERFACE",
    "CONTRACT_STATE_RECORD_SCHEMA",
    "DYNAMIC_FRONTIER_RECORD_INTERFACE",
    "DYNAMIC_FRONTIER_RECORD_SCHEMA",
    "FUNCTION_SYMBOL_RECORD_INTERFACE",
    "FUNCTION_SYMBOL_RECORD_SCHEMA",
    "LOGICAL_CYCLE_REQUIRED_KINDS",
    "PROGRAM_GRAPH_DELTA_INTERFACE",
    "PROGRAM_GRAPH_DELTA_SCHEMA",
    "PROGRAM_GRAPH_EDGE_INTERFACE",
    "PROGRAM_GRAPH_EDGE_SCHEMA",
    "PROGRAM_GRAPH_INDEX_MANIFEST_INTERFACE",
    "PROGRAM_GRAPH_INDEX_MANIFEST_SCHEMA",
    "PROGRAM_GRAPH_NODE_INTERFACE",
    "PROGRAM_GRAPH_NODE_SCHEMA",
    "PROGRAM_GRAPH_SNAPSHOT_INTERFACE",
    "PROGRAM_GRAPH_SNAPSHOT_SCHEMA",
    "PROOF_OBLIGATION_GRAPH_INTERFACE",
    "PROOF_OBLIGATION_GRAPH_SCHEMA",
    "REQUIRED_EDGE_KINDS",
    "REQUIRED_NODE_KINDS",
    "STATIC_SUCCESSOR_SET_INTERFACE",
    "STATIC_SUCCESSOR_SET_SCHEMA",
    "UNAVAILABLE_LANGUAGES",
    "CallsiteRecord",
    "ContractDischargeStatus",
    "ContractKind",
    "ContractStateRecord",
    "DynamicFrontierReason",
    "DynamicFrontierRecord",
    "FunctionSymbolRecord",
    "ProgramGraphDelta",
    "ProgramGraphEdge",
    "ProgramGraphEdgeKind",
    "ProgramGraphError",
    "ProgramGraphIndexKind",
    "ProgramGraphIndexManifest",
    "ProgramGraphKind",
    "ProgramGraphNode",
    "ProgramGraphNodeKind",
    "ProgramGraphSnapshot",
    "ProgramLanguage",
    "ProofObligationGraph",
    "ResolutionStatus",
    "StaticSuccessorSet",
    "apply_program_graph_delta",
    "assemble_program_graph_snapshot",
    "assert_physical_dag_acyclic",
    "bind_index_manifest",
    "canonical_program_graph_bytes",
    "canonicalize_program_graph_value",
    "decode_program_graph_record",
    "delta_between_snapshots",
    "directed_logical_cycles",
    "is_unresolved_dynamic_edge",
    "is_unresolved_dynamic_node",
    "load_payload_schema",
    "loads_program_graph_json",
    "program_graph_cid_for",
    "verify_program_graph_catalog",
]
