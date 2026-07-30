"""Read-only supervisor code / objective / AST / conflict / evidence graph adapter (KGP-027).

Adapts the graph kinds discovered by KGP-002 without coupling this package to the
``ipfs_accelerate_py`` supervisor runtime:

* ``supervisor_objective_graph``
* ``supervisor_semantic_dependency_graph``
* ``supervisor_ast_index``
* ``supervisor_conflict_graph``
* ``supervisor_code_evidence_graph`` (+ companion code impact index)

The adapter:

* preserves typed node/edge kinds, provenance, revision binding, and evidence links
* supports incremental working-copy updates (never mutates on-disk artifacts)
* answers representative dependency, impact, and provenance queries
* is schema-extensible for unknown optional node/edge kinds

On-disk artifacts are strictly read-only.
"""

from __future__ import annotations

from collections import defaultdict, deque
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Sequence


# ---------------------------------------------------------------------------
# Schemas (authoritative producer strings from ipfs_accelerate_py)
# ---------------------------------------------------------------------------

OBJECTIVE_GRAPH_SCHEMA = "ipfs_accelerate_py.agent_supervisor.objective_graph"
OBJECTIVE_THOUGHT_GRAPH_SCHEMA = (
    "ipfs_accelerate_py.agent_supervisor.objective_thought_graph"
)

SEMANTIC_DEPENDENCY_GRAPH_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/semantic-dependency-graph@1"
)
SEMANTIC_DEPENDENCY_NODE_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/semantic-dependency-node@1"
)
SEMANTIC_DEPENDENCY_EDGE_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/semantic-dependency-edge@1"
)
MANDATORY_CLOSURE_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/mandatory-dependency-closure@1"
)

ANALYSIS_AST_INDEX_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/analysis-ast-index@1"
)
ANALYSIS_AST_INDEX_SCHEMA_VERSION = 1
AST_BLOB_RECORD_SCHEMA_VERSION = 1

CONFLICT_GRAPH_SCHEMA = "ipfs_accelerate_py.agent_supervisor.conflict_graph@1"

CODE_EVIDENCE_GRAPH_SCHEMA = (
    "ipfs_accelerate_py.agent_supervisor.code-evidence-graph@1"
)
CODE_EVIDENCE_NODE_SCHEMA = (
    "ipfs_accelerate_py.agent_supervisor.code-evidence-node@1"
)
CODE_EVIDENCE_EDGE_SCHEMA = (
    "ipfs_accelerate_py.agent_supervisor.code-evidence-edge@1"
)
CODE_IMPACT_INDEX_SCHEMA = (
    "ipfs_accelerate_py.agent_supervisor.code-impact-index@1"
)
CODE_IMPACT_RESULT_SCHEMA = (
    "ipfs_accelerate_py.agent_supervisor.code-impact-result@1"
)

BUNDLE_MANIFEST_SCHEMA = "code-evidence-bundle-manifest/v1"
VALIDATION_RECEIPT_SCHEMA = "code-evidence-corpus-validation-receipt/v1"
INCREMENTAL_UPDATE_SCHEMA = "code-evidence-incremental-update/v1"
LOCAL_FIXTURE_REVISION = "0" * 40

# Inventory graph kinds (KGP-002)
GRAPH_KIND_OBJECTIVE = "supervisor_objective_graph"
GRAPH_KIND_SEMANTIC = "supervisor_semantic_dependency_graph"
GRAPH_KIND_AST = "supervisor_ast_index"
GRAPH_KIND_CONFLICT = "supervisor_conflict_graph"
GRAPH_KIND_CODE_EVIDENCE = "supervisor_code_evidence_graph"
GRAPH_KIND_IMPACT = "code_impact_index"

ENV_BUNDLE_ROOT = "CODE_EVIDENCE_BUNDLE_ROOT"
ENV_BUNDLE_ROOT_ALT = "SUPERVISOR_GRAPH_BUNDLE_ROOT"
ENV_OBJECTIVE_ROOT = "SUPERVISOR_OBJECTIVE_GRAPH_ROOT"
ENV_ACCELERATE_ROOT = "IPFS_ACCELERATE_PY_ROOT"

DEFAULT_OBJECTIVE_CANDIDATES = (
    Path(
        "/home/barberb/ipfs_datasets_py/data/agent_supervisor/"
        "knowledge_graphs_production_hardening"
    ),
    Path("data/agent_supervisor/knowledge_graphs_production_hardening"),
)

DEFAULT_MAX_DEPTH = 16
DEFAULT_MAX_NODES = 10_000
DEFAULT_MAX_EDGES = 50_000
DEFAULT_MAX_CLOSURE_NODES = 16_384
DEFAULT_MAX_CLOSURE_EDGES = 65_536
DEFAULT_MAX_CLOSURE_DEPTH = 256

# Known kinds (canonical producer enums). Unknown kinds are optional extensions.
KNOWN_CODE_EVIDENCE_NODE_KINDS = frozenset(
    {
        "task",
        "tree",
        "symbol",
        "ast_scope",
        "obligation",
        "attempt",
        "proof",
        "validation",
        "merge",
        "evidence",
        "enrichment",
    }
)
KNOWN_CODE_EVIDENCE_EDGE_KINDS = frozenset(
    {
        "depends_on",
        "targets_tree",
        "defines_symbol",
        "contains",
        "has_obligation",
        "covers",
        "attempt_for",
        "derived_from",
        "proves",
        "validates",
        "merged",
        "completes",
        "related_to",
        "mentions",
        "suggests",
    }
)
CODE_EVIDENCE_ENRICHMENT_EDGE_KINDS = frozenset(
    {"related_to", "mentions", "suggests"}
)
CODE_EVIDENCE_UNTRUSTED_PROVENANCE = frozenset(
    {"enrichment", "llm", "graphrag"}
)
CODE_EVIDENCE_AUTHORITATIVE_EDGE_PROVENANCE: Mapping[str, frozenset[str]] = {
    "depends_on": frozenset({"task", "proof"}),
    "targets_tree": frozenset({"ast", "task", "proof"}),
    "defines_symbol": frozenset({"ast"}),
    "contains": frozenset({"ast"}),
    "has_obligation": frozenset({"proof"}),
    "covers": frozenset({"proof", "validation"}),
    "attempt_for": frozenset({"proof"}),
    "derived_from": frozenset(
        {"ast", "task", "proof", "validation", "merge"}
    ),
    "proves": frozenset({"proof"}),
    "validates": frozenset({"validation"}),
    "merged": frozenset({"merge"}),
    "completes": frozenset({"validation", "merge"}),
}

KNOWN_SEMANTIC_NODE_KINDS = frozenset(
    {
        "decision",
        "plan",
        "action",
        "effect",
        "tool",
        "resource",
        "intent_goal",
        "intent_declaration",
        "intent_action",
        "intent_control_flow",
        "intent_precondition",
        "intent_guard",
        "intent_invariant",
        "intent_effect",
        "intent_postcondition",
        "intent_assumption",
        "intent_failure",
        "intent_retry",
        "intent_verification",
        "intent_formal_view",
        "intent_claim",
        "intent_obligation",
        "intent_result_authority",
        "legal_obligation",
        "legal_declaration",
        "legal_prohibition",
        "legal_permission",
        "legal_power",
        "legal_exception",
        "legal_formal_view",
        "legal_claim",
        "legal_assumption",
        "legal_proof_obligation",
        "legal_result_authority",
        "security_principal",
        "security_declaration",
        "security_asset",
        "security_resource",
        "security_zone",
        "security_channel",
        "security_policy",
        "security_state_machine",
        "security_threat_assumption",
        "security_formal_view",
        "security_claim",
        "security_obligation",
        "security_result_authority",
        "worktree",
        "repository_tree",
        "file",
        "ast",
        "symbol",
        "interface",
        "call",
        "data_flow",
        "program",
        "environment",
        "toolchain",
        "assumption",
        "premise",
        "obligation",
        "proof",
        "monitor",
        "authorization",
        "validation",
        "merge_evidence",
        "annotation",
    }
)
KNOWN_SEMANTIC_EDGE_KINDS = frozenset(
    {
        "requires",
        "constrained_by",
        "applies_to",
        "exception_to",
        "conflicts_with",
        "authorizes",
        "denies",
        "implements",
        "affects",
        "depends_on",
        "proven_by",
        "monitored_by",
        "invalidates",
        "sourced_from",
    }
)
SEMANTIC_TRUSTED_PROVENANCE = frozenset(
    {
        "source",
        "decision",
        "planner",
        "intent_ir",
        "legal_ir",
        "security_ir",
        "worktree",
        "ast",
        "program",
        "tool",
        "proof",
        "monitor",
        "authorization",
        "validation",
        "merge",
    }
)
SEMANTIC_ACCEPTED_TRUST = frozenset({"trusted", "verified", "reviewed"})
SEMANTIC_AUTHORITY_BEARING = frozenset(
    {
        "authoritative",
        "verified_input",
        "constraint_input",
        "policy_input",
        "descriptive_input",
        "context_only",
    }
)
SEMANTIC_UNSAFE_CYCLE_EDGE_KINDS = frozenset(
    {
        "requires",
        "constrained_by",
        "exception_to",
        "implements",
        "depends_on",
        "proven_by",
        "monitored_by",
        "invalidates",
        "sourced_from",
    }
)

BUNDLE_ARTIFACTS: Mapping[str, str] = {
    "manifest": "manifest.json",
    "objective_graph": "objective_graph.json",
    "semantic_dependency_graph": "semantic_dependency_graph.json",
    "analysis_ast_index": "analysis_ast_index.json",
    "conflict_graph": "conflict_graph.json",
    "code_evidence_graph": "code_evidence_graph.json",
    "code_impact_index": "code_impact_index.json",
}


class CodeEvidenceAdapterError(RuntimeError):
    """Raised when a supervisor graph record, bundle, or query is malformed."""


# ---------------------------------------------------------------------------
# Canonical JSON / identity (mirror producer algorithms; no runtime import)
# ---------------------------------------------------------------------------


def _canonical_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise CodeEvidenceAdapterError("non-finite numbers are not canonical")
        return value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise CodeEvidenceAdapterError("record keys must be strings")
        return {key: _canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [_canonical_value(item) for item in value]
        return sorted(items, key=canonical_json)
    raise CodeEvidenceAdapterError(
        f"unsupported record value type: {type(value).__name__}"
    )


def canonical_json(value: Any) -> str:
    """Return deterministic UTF-8 JSON without insignificant whitespace."""

    return json.dumps(
        _canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def content_identity(value: Any, *, prefix: str = "") -> str:
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return f"{prefix}{digest}" if prefix else digest


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    return Path(raw).expanduser()


def _load_json(path: Path) -> Any:
    if not path.is_file() or path.is_symlink():
        raise CodeEvidenceAdapterError(f"missing JSON artifact: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CodeEvidenceAdapterError(
            f"corrupt or unreadable JSON artifact: {path.name}"
        ) from exc


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CodeEvidenceAdapterError(f"{label} must be a JSON object")
    return dict(value)


def _require_sequence(value: Any, label: str) -> list[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise CodeEvidenceAdapterError(f"{label} must be a sequence")
    return list(value)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_path(value: Any) -> str:
    text = _text(value).replace("\\", "/")
    if not text or text.startswith("/") or ".." in text.split("/"):
        raise CodeEvidenceAdapterError(f"unsafe repository path: {value!r}")
    return text


# ---------------------------------------------------------------------------
# Kind classification (known vs optional unknown)
# ---------------------------------------------------------------------------


def classify_kind(
    kind: str,
    known: frozenset[str],
    *,
    allow_unknown: bool = True,
) -> dict[str, Any]:
    """Return kind classification metadata for schema extensibility proofs."""

    text = _text(kind)
    if not text:
        raise CodeEvidenceAdapterError("node/edge kind is required")
    if text in known:
        return {
            "kind": text,
            "known": True,
            "optional_unknown": False,
            "status": "canonical",
        }
    if not allow_unknown:
        raise CodeEvidenceAdapterError(f"unknown kind not allowed: {text!r}")
    return {
        "kind": text,
        "known": False,
        "optional_unknown": True,
        "status": "optional_extension",
    }


def _is_code_evidence_authoritative(
    edge_kind: str, provenance: str, *, known: bool
) -> bool:
    if not known:
        # Unknown optional edge kinds are never authority-bearing.
        return False
    if provenance in CODE_EVIDENCE_UNTRUSTED_PROVENANCE:
        return False
    allowed = CODE_EVIDENCE_AUTHORITATIVE_EDGE_PROVENANCE.get(edge_kind)
    if allowed is None:
        return False
    return provenance in allowed


def _is_semantic_authoritative(
    *,
    provenance: str,
    trust: str,
    authority: str,
    known: bool,
) -> bool:
    if not known:
        return False
    return (
        provenance in SEMANTIC_TRUSTED_PROVENANCE
        and trust in SEMANTIC_ACCEPTED_TRUST
        and authority in SEMANTIC_AUTHORITY_BEARING
    )


# ---------------------------------------------------------------------------
# Record normalizers
# ---------------------------------------------------------------------------


def normalize_code_evidence_node(
    payload: Mapping[str, Any],
    *,
    allow_unknown_kinds: bool = True,
) -> dict[str, Any]:
    schema = _text(payload.get("schema") or CODE_EVIDENCE_NODE_SCHEMA)
    if schema != CODE_EVIDENCE_NODE_SCHEMA:
        raise CodeEvidenceAdapterError(f"unsupported node schema: {schema}")
    kind_meta = classify_kind(
        _text(payload.get("kind")),
        KNOWN_CODE_EVIDENCE_NODE_KINDS,
        allow_unknown=allow_unknown_kinds,
    )
    kind = kind_meta["kind"]
    record_key = _text(payload.get("record_key"))
    if not record_key:
        raise CodeEvidenceAdapterError("code evidence node record_key is required")
    provenance = _text(payload.get("provenance"))
    if not provenance:
        raise CodeEvidenceAdapterError("code evidence node provenance is required")
    if (
        provenance in CODE_EVIDENCE_UNTRUSTED_PROVENANCE
        and kind != "enrichment"
        and kind_meta["known"]
    ):
        raise CodeEvidenceAdapterError(
            "enrichment provenance may only create enrichment nodes"
        )
    record = payload.get("record") or {}
    if not isinstance(record, Mapping):
        raise CodeEvidenceAdapterError("code evidence node record must be a mapping")
    node_id = "node-" + content_identity(
        {
            "schema": CODE_EVIDENCE_NODE_SCHEMA,
            "kind": kind,
            "record_key": record_key,
        }
    )
    claimed = _text(payload.get("node_id"))
    if claimed and claimed != node_id:
        raise CodeEvidenceAdapterError("node identity does not match payload")
    authoritative = (
        provenance not in CODE_EVIDENCE_UNTRUSTED_PROVENANCE
        and kind_meta["known"]
    )
    if "authoritative" in payload and bool(payload["authoritative"]) != authoritative:
        raise CodeEvidenceAdapterError("node authority does not match provenance")
    return {
        "schema": CODE_EVIDENCE_NODE_SCHEMA,
        "node_id": node_id,
        "kind": kind,
        "kind_meta": kind_meta,
        "record_key": record_key,
        "provenance": provenance,
        "authoritative": authoritative,
        "task_id": _text(payload.get("task_id")),
        "tree_id": _text(payload.get("tree_id")),
        "symbol": _text(payload.get("symbol")),
        "obligation_id": _text(payload.get("obligation_id")),
        "assurance": _text(payload.get("assurance")),
        "freshness": _text(payload.get("freshness")),
        "record": _canonical_value(record),
        "revision": _text(payload.get("revision")),
    }


def normalize_code_evidence_edge(
    payload: Mapping[str, Any],
    *,
    allow_unknown_kinds: bool = True,
) -> dict[str, Any]:
    schema = _text(payload.get("schema") or CODE_EVIDENCE_EDGE_SCHEMA)
    if schema != CODE_EVIDENCE_EDGE_SCHEMA:
        raise CodeEvidenceAdapterError(f"unsupported edge schema: {schema}")
    source = _text(payload.get("source") or payload.get("source_node_id"))
    target = _text(payload.get("target") or payload.get("target_node_id"))
    if not source or not target:
        raise CodeEvidenceAdapterError("edge source and target are required")
    kind_meta = classify_kind(
        _text(payload.get("kind") or payload.get("edge_kind")),
        KNOWN_CODE_EVIDENCE_EDGE_KINDS,
        allow_unknown=allow_unknown_kinds,
    )
    kind = kind_meta["kind"]
    provenance = _text(payload.get("provenance"))
    provenance_record_id = _text(payload.get("provenance_record_id"))
    if not provenance or not provenance_record_id:
        raise CodeEvidenceAdapterError(
            "edge provenance and provenance_record_id are required"
        )
    metadata = payload.get("metadata") or {}
    if not isinstance(metadata, Mapping):
        raise CodeEvidenceAdapterError("edge metadata must be a mapping")
    metadata = _canonical_value(metadata)
    if provenance in CODE_EVIDENCE_UNTRUSTED_PROVENANCE:
        if kind_meta["known"] and kind not in CODE_EVIDENCE_ENRICHMENT_EDGE_KINDS:
            raise CodeEvidenceAdapterError(
                f"enrichment cannot create {kind!r} edges"
            )
    elif kind_meta["known"]:
        allowed = CODE_EVIDENCE_AUTHORITATIVE_EDGE_PROVENANCE.get(kind)
        if allowed is not None and provenance not in allowed:
            raise CodeEvidenceAdapterError(
                f"{provenance} records cannot create {kind!r} edges"
            )
    edge_id = "edge-" + content_identity(
        {
            "schema": CODE_EVIDENCE_EDGE_SCHEMA,
            "source": source,
            "target": target,
            "kind": kind,
            "provenance": provenance,
            "provenance_record_id": provenance_record_id,
            "metadata": metadata,
        }
    )
    claimed = _text(payload.get("edge_id"))
    if claimed and claimed != edge_id:
        raise CodeEvidenceAdapterError("edge identity does not match payload")
    authoritative = _is_code_evidence_authoritative(
        kind, provenance, known=kind_meta["known"]
    )
    if "authoritative" in payload and bool(payload["authoritative"]) != authoritative:
        raise CodeEvidenceAdapterError("edge authority does not match provenance")
    return {
        "schema": CODE_EVIDENCE_EDGE_SCHEMA,
        "edge_id": edge_id,
        "source": source,
        "target": target,
        "kind": kind,
        "kind_meta": kind_meta,
        "provenance": provenance,
        "provenance_record_id": provenance_record_id,
        "authoritative": authoritative,
        "metadata": metadata,
        "revision": _text(payload.get("revision")),
    }


def normalize_code_evidence_graph(
    payload: Mapping[str, Any],
    *,
    allow_unknown_kinds: bool = True,
    revision: str = "",
) -> dict[str, Any]:
    schema = _text(payload.get("schema") or CODE_EVIDENCE_GRAPH_SCHEMA)
    if schema != CODE_EVIDENCE_GRAPH_SCHEMA:
        raise CodeEvidenceAdapterError(f"unsupported graph schema: {schema}")
    raw_nodes = _require_sequence(payload.get("nodes") or (), "graph nodes")
    raw_edges = _require_sequence(payload.get("edges") or (), "graph edges")
    nodes = [
        normalize_code_evidence_node(
            _require_mapping(item, "node"),
            allow_unknown_kinds=allow_unknown_kinds,
        )
        for item in raw_nodes
    ]
    edges = [
        normalize_code_evidence_edge(
            _require_mapping(item, "edge"),
            allow_unknown_kinds=allow_unknown_kinds,
        )
        for item in raw_edges
    ]
    node_map = {node["node_id"]: node for node in nodes}
    if len(node_map) != len(nodes):
        # Identical re-declarations are ok if equal; conflicts already checked
        # during identity rebuild — collapse by node_id.
        collapsed: dict[str, dict[str, Any]] = {}
        for node in nodes:
            previous = collapsed.get(node["node_id"])
            if previous is not None and previous != node:
                raise CodeEvidenceAdapterError(
                    f"conflicting records for node {node['node_id']}"
                )
            collapsed[node["node_id"]] = node
        node_map = collapsed
    for edge in edges:
        if edge["source"] not in node_map or edge["target"] not in node_map:
            raise CodeEvidenceAdapterError(
                f"edge {edge['edge_id']} references an unknown node"
            )
    nodes_sorted = [node_map[key] for key in sorted(node_map)]
    edge_map = {edge["edge_id"]: edge for edge in edges}
    edges_sorted = [edge_map[key] for key in sorted(edge_map)]
    graph_id = "graph-" + content_identity(
        {
            "nodes": [
                {k: v for k, v in node.items() if k != "kind_meta"}
                for node in nodes_sorted
            ],
            "edges": [
                {k: v for k, v in edge.items() if k != "kind_meta"}
                for edge in edges_sorted
            ],
        }
    )
    # Producer graph_id is over canonical_records which exclude kind_meta and
    # use to_dict() fields only. Recompute with public fields.
    public_nodes = [
        {
            "schema": n["schema"],
            "node_id": n["node_id"],
            "kind": n["kind"],
            "record_key": n["record_key"],
            "provenance": n["provenance"],
            "authoritative": n["authoritative"],
            "task_id": n["task_id"],
            "tree_id": n["tree_id"],
            "symbol": n["symbol"],
            "obligation_id": n["obligation_id"],
            "assurance": n["assurance"],
            "freshness": n["freshness"],
            "record": n["record"],
        }
        for n in nodes_sorted
    ]
    public_edges = [
        {
            "schema": e["schema"],
            "edge_id": e["edge_id"],
            "source": e["source"],
            "target": e["target"],
            "kind": e["kind"],
            "provenance": e["provenance"],
            "provenance_record_id": e["provenance_record_id"],
            "authoritative": e["authoritative"],
            "metadata": e["metadata"],
        }
        for e in edges_sorted
    ]
    graph_id = "graph-" + content_identity(
        {"nodes": public_nodes, "edges": public_edges}
    )
    claimed = _text(payload.get("graph_id"))
    if claimed and claimed != graph_id:
        raise CodeEvidenceAdapterError("graph identity does not match payload")
    if "node_count" in payload and int(payload["node_count"]) != len(public_nodes):
        raise CodeEvidenceAdapterError("graph node_count does not match records")
    if "edge_count" in payload and int(payload["edge_count"]) != len(public_edges):
        raise CodeEvidenceAdapterError("graph edge_count does not match records")
    unknown_node_kinds = sorted(
        {
            n["kind"]
            for n in nodes_sorted
            if n["kind_meta"]["optional_unknown"]
        }
    )
    unknown_edge_kinds = sorted(
        {
            e["kind"]
            for e in edges_sorted
            if e["kind_meta"]["optional_unknown"]
        }
    )
    return {
        "schema": CODE_EVIDENCE_GRAPH_SCHEMA,
        "graph_id": graph_id,
        "node_count": len(public_nodes),
        "edge_count": len(public_edges),
        "nodes": nodes_sorted,
        "edges": edges_sorted,
        "public_nodes": public_nodes,
        "public_edges": public_edges,
        "revision": _text(payload.get("revision") or revision),
        "unknown_optional_node_kinds": unknown_node_kinds,
        "unknown_optional_edge_kinds": unknown_edge_kinds,
        "graph_kind": GRAPH_KIND_CODE_EVIDENCE,
    }


def normalize_semantic_node(
    payload: Mapping[str, Any],
    *,
    allow_unknown_kinds: bool = True,
) -> dict[str, Any]:
    schema = _text(payload.get("schema") or SEMANTIC_DEPENDENCY_NODE_SCHEMA)
    if schema != SEMANTIC_DEPENDENCY_NODE_SCHEMA:
        raise CodeEvidenceAdapterError(f"unsupported semantic node schema: {schema}")
    node_id = _text(payload.get("node_id"))
    root_id = _text(payload.get("root_id"))
    version = _text(payload.get("version"))
    if not node_id or not root_id or not version:
        raise CodeEvidenceAdapterError(
            "semantic node requires node_id, root_id, and version"
        )
    kind_meta = classify_kind(
        _text(payload.get("kind")),
        KNOWN_SEMANTIC_NODE_KINDS,
        allow_unknown=allow_unknown_kinds,
    )
    provenance = _text(payload.get("provenance"))
    trust = _text(payload.get("trust"))
    authority = _text(payload.get("authority"))
    if not provenance or not trust or not authority:
        raise CodeEvidenceAdapterError(
            "semantic node requires provenance, trust, and authority"
        )
    source_root_id = _text(payload.get("source_root_id") or root_id)
    provenance_id = _text(payload.get("provenance_id") or node_id)
    record = payload.get("record") or {}
    if not isinstance(record, Mapping):
        raise CodeEvidenceAdapterError("semantic node record must be a mapping")
    record = _canonical_value(record)
    trusted_channel = provenance in SEMANTIC_TRUSTED_PROVENANCE
    accepted = trust in SEMANTIC_ACCEPTED_TRUST
    authority_bearing = authority in SEMANTIC_AUTHORITY_BEARING
    if (
        kind_meta["known"]
        and (not trusted_channel or not accepted)
        and authority_bearing
    ):
        raise CodeEvidenceAdapterError(
            "untrusted or model provenance cannot create authoritative nodes"
        )
    authoritative = _is_semantic_authoritative(
        provenance=provenance,
        trust=trust,
        authority=authority,
        known=kind_meta["known"],
    )
    content_id = _prefixed_identity(
        "semantic-node",
        {
            "schema": SEMANTIC_DEPENDENCY_NODE_SCHEMA,
            "node_id": node_id,
            "kind": kind_meta["kind"],
            "root_id": root_id,
            "source_root_id": source_root_id,
            "provenance": provenance,
            "provenance_id": provenance_id,
            "trust": trust,
            "authority": authority,
            "version": version,
            "record": record,
        },
    )
    claimed = _text(payload.get("content_id"))
    if claimed and claimed != content_id:
        raise CodeEvidenceAdapterError("semantic node content identity mismatch")
    if "authoritative" in payload and bool(payload["authoritative"]) != authoritative:
        raise CodeEvidenceAdapterError("semantic node authority claim is forged")
    return {
        "schema": SEMANTIC_DEPENDENCY_NODE_SCHEMA,
        "node_id": node_id,
        "kind": kind_meta["kind"],
        "kind_meta": kind_meta,
        "root_id": root_id,
        "source_root_id": source_root_id,
        "provenance": provenance,
        "provenance_id": provenance_id,
        "trust": trust,
        "authority": authority,
        "version": version,
        "record": record,
        "content_id": content_id,
        "authoritative": authoritative,
        "revision": _text(payload.get("revision") or version),
    }


def _prefixed_identity(prefix: str, value: Any) -> str:
    """Match accelerate ``_identity(prefix, value)`` which hashes prefix+json.

    Producers use: sha256(canonical_json({"_prefix": prefix, ...})) or
    ``prefix + ":" + sha256``? Inspect: ``_identity(namespace, value)``.
    """

    # From semantic_dependency_graph.py:
    # def _identity(namespace: str, value: Any) -> str:
    #     return hashlib.sha256(
    #         f"{namespace}:{canonical_semantic_json(value)}".encode("utf-8")
    #     ).hexdigest()
    material = f"{prefix}:{canonical_json(value)}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def normalize_semantic_edge(
    payload: Mapping[str, Any],
    *,
    allow_unknown_kinds: bool = True,
) -> dict[str, Any]:
    schema = _text(payload.get("schema") or SEMANTIC_DEPENDENCY_EDGE_SCHEMA)
    if schema != SEMANTIC_DEPENDENCY_EDGE_SCHEMA:
        raise CodeEvidenceAdapterError(f"unsupported semantic edge schema: {schema}")
    source = _text(payload.get("source") or payload.get("source_node_id"))
    target = _text(payload.get("target") or payload.get("target_node_id"))
    root_id = _text(payload.get("root_id"))
    version = _text(payload.get("version"))
    provenance_id = _text(payload.get("provenance_id"))
    if not source or not target:
        raise CodeEvidenceAdapterError("semantic edge requires source and target")
    if source == target:
        raise CodeEvidenceAdapterError("self-referential semantic edge")
    if not root_id or not version or not provenance_id:
        raise CodeEvidenceAdapterError(
            "semantic edge requires root_id, version, and provenance_id"
        )
    kind_meta = classify_kind(
        _text(payload.get("kind") or payload.get("edge_kind")),
        KNOWN_SEMANTIC_EDGE_KINDS,
        allow_unknown=allow_unknown_kinds,
    )
    provenance = _text(payload.get("provenance"))
    trust = _text(payload.get("trust"))
    authority = _text(payload.get("authority"))
    if not provenance or not trust or not authority:
        raise CodeEvidenceAdapterError(
            "semantic edge requires provenance, trust, and authority"
        )
    source_root_id = _text(payload.get("source_root_id") or root_id)
    mandatory = bool(payload.get("mandatory", True))
    record = payload.get("record") or {}
    if not isinstance(record, Mapping):
        raise CodeEvidenceAdapterError("semantic edge record must be a mapping")
    record = _canonical_value(record)
    trusted_channel = provenance in SEMANTIC_TRUSTED_PROVENANCE
    accepted = trust in SEMANTIC_ACCEPTED_TRUST
    if not trusted_channel or not accepted:
        if authority in SEMANTIC_AUTHORITY_BEARING and kind_meta["known"]:
            raise CodeEvidenceAdapterError(
                "untrusted or model provenance cannot create authoritative edges"
            )
        mandatory = False
    if authority in {"proposal_only", "untrusted", "none"}:
        mandatory = False
    kind = kind_meta["kind"]
    if kind_meta["known"]:
        if kind in {"authorizes", "denies"} and provenance not in {
            "security_ir",
            "authorization",
        }:
            raise CodeEvidenceAdapterError(
                f"{kind} edges require SecurityIR or authorization provenance"
            )
        if kind == "proven_by" and provenance != "proof":
            raise CodeEvidenceAdapterError("proven_by edges require proof provenance")
        if kind == "monitored_by" and provenance != "monitor":
            raise CodeEvidenceAdapterError(
                "monitored_by edges require monitor provenance"
            )
    authoritative = _is_semantic_authoritative(
        provenance=provenance,
        trust=trust,
        authority=authority,
        known=kind_meta["known"],
    )
    identity_payload = {
        "schema": SEMANTIC_DEPENDENCY_EDGE_SCHEMA,
        "source": source,
        "target": target,
        "kind": kind,
        "root_id": root_id,
        "source_root_id": source_root_id,
        "provenance": provenance,
        "provenance_id": provenance_id,
        "trust": trust,
        "authority": authority,
        "version": version,
        "mandatory": mandatory,
        "record": record,
    }
    edge_id = _prefixed_identity("semantic-edge", identity_payload)
    claimed = _text(payload.get("edge_id"))
    if claimed and claimed != edge_id:
        raise CodeEvidenceAdapterError("semantic edge identity mismatch")
    if "authoritative" in payload and bool(payload["authoritative"]) != authoritative:
        raise CodeEvidenceAdapterError("semantic edge authority claim is forged")
    return {
        **identity_payload,
        "edge_id": edge_id,
        "authoritative": authoritative,
        "kind_meta": kind_meta,
        "revision": _text(payload.get("revision") or version),
    }


def normalize_semantic_dependency_graph(
    payload: Mapping[str, Any],
    *,
    allow_unknown_kinds: bool = True,
    revision: str = "",
) -> dict[str, Any]:
    schema = _text(payload.get("schema") or SEMANTIC_DEPENDENCY_GRAPH_SCHEMA)
    if schema != SEMANTIC_DEPENDENCY_GRAPH_SCHEMA:
        raise CodeEvidenceAdapterError(f"unsupported semantic graph schema: {schema}")
    root_id = _text(payload.get("root_id"))
    if not root_id:
        raise CodeEvidenceAdapterError("semantic graph root_id is required")
    nodes = [
        normalize_semantic_node(
            _require_mapping(item, "semantic node"),
            allow_unknown_kinds=allow_unknown_kinds,
        )
        for item in _require_sequence(payload.get("nodes") or (), "semantic nodes")
    ]
    edges = [
        normalize_semantic_edge(
            _require_mapping(item, "semantic edge"),
            allow_unknown_kinds=allow_unknown_kinds,
        )
        for item in _require_sequence(payload.get("edges") or (), "semantic edges")
    ]
    node_map: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if node["root_id"] != root_id:
            raise CodeEvidenceAdapterError(
                f"node {node['node_id']!r} is bound to a foreign root"
            )
        previous = node_map.get(node["node_id"])
        if previous is not None and previous != node:
            raise CodeEvidenceAdapterError(
                f"conflicting semantic node: {node['node_id']}"
            )
        node_map[node["node_id"]] = node
    edge_map: dict[str, dict[str, Any]] = {}
    for edge in edges:
        if edge["source"] not in node_map or edge["target"] not in node_map:
            raise CodeEvidenceAdapterError(
                f"edge {edge['edge_id']} references an unknown node"
            )
        source = node_map[edge["source"]]
        target = node_map[edge["target"]]
        if (
            edge["root_id"] != root_id
            or source["root_id"] != edge["root_id"]
            or target["root_id"] != edge["root_id"]
        ):
            raise CodeEvidenceAdapterError(
                f"edge {edge['edge_id']} crosses semantic roots"
            )
        if edge["authoritative"] and (
            not source["authoritative"] or not target["authoritative"]
        ):
            raise CodeEvidenceAdapterError(
                "authoritative edge cannot promote a non-authoritative endpoint"
            )
        edge_map[edge["edge_id"]] = edge
    nodes_sorted = [node_map[key] for key in sorted(node_map)]
    edges_sorted = [edge_map[key] for key in sorted(edge_map)]
    _reject_semantic_cycles(edges_sorted)
    public_nodes = [
        {k: v for k, v in node.items() if k not in {"kind_meta", "revision"}}
        for node in nodes_sorted
    ]
    public_edges = [
        {k: v for k, v in edge.items() if k not in {"kind_meta", "revision"}}
        for edge in edges_sorted
    ]
    graph_id = _prefixed_identity(
        "semantic-graph",
        {
            "schema": SEMANTIC_DEPENDENCY_GRAPH_SCHEMA,
            "root_id": root_id,
            "nodes": public_nodes,
            "edges": public_edges,
        },
    )
    claimed = _text(payload.get("graph_id"))
    if claimed and claimed != graph_id:
        raise CodeEvidenceAdapterError("semantic graph identity mismatch")
    if "node_count" in payload and int(payload["node_count"]) != len(nodes_sorted):
        raise CodeEvidenceAdapterError("semantic node_count does not match records")
    if "edge_count" in payload and int(payload["edge_count"]) != len(edges_sorted):
        raise CodeEvidenceAdapterError("semantic edge_count does not match records")
    return {
        "schema": SEMANTIC_DEPENDENCY_GRAPH_SCHEMA,
        "graph_id": graph_id,
        "root_id": root_id,
        "node_count": len(nodes_sorted),
        "edge_count": len(edges_sorted),
        "nodes": nodes_sorted,
        "edges": edges_sorted,
        "revision": _text(payload.get("revision") or revision),
        "unknown_optional_node_kinds": sorted(
            {
                n["kind"]
                for n in nodes_sorted
                if n["kind_meta"]["optional_unknown"]
            }
        ),
        "unknown_optional_edge_kinds": sorted(
            {
                e["kind"]
                for e in edges_sorted
                if e["kind_meta"]["optional_unknown"]
            }
        ),
        "graph_kind": GRAPH_KIND_SEMANTIC,
    }


def _reject_semantic_cycles(edges: Sequence[Mapping[str, Any]]) -> None:
    adjacency: dict[str, set[str]] = {}
    indegree: dict[str, int] = {}
    for edge in edges:
        if (
            edge.get("authoritative")
            and edge.get("mandatory")
            and edge.get("kind") in SEMANTIC_UNSAFE_CYCLE_EDGE_KINDS
        ):
            adjacency.setdefault(edge["source"], set()).add(edge["target"])
            adjacency.setdefault(edge["target"], set())
    for source, targets in adjacency.items():
        indegree.setdefault(source, 0)
        for target in targets:
            indegree[target] = indegree.get(target, 0) + 1
    ready = deque(sorted(key for key, degree in indegree.items() if degree == 0))
    visited = 0
    while ready:
        current = ready.popleft()
        visited += 1
        for target in sorted(adjacency.get(current, ())):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    if visited != len(indegree):
        raise CodeEvidenceAdapterError("unsafe mandatory dependency cycle")


def normalize_ast_blob_record(payload: Mapping[str, Any]) -> dict[str, Any]:
    version = int(payload.get("record_schema_version", AST_BLOB_RECORD_SCHEMA_VERSION))
    if version != AST_BLOB_RECORD_SCHEMA_VERSION:
        raise CodeEvidenceAdapterError(
            f"unsupported AST blob record schema version: {version}"
        )
    source_hash = _text(payload.get("source_sha256"))
    if source_hash and ":" not in source_hash:
        source_hash = f"sha256:{source_hash}"
    blob = _text(payload.get("blob_identity") or source_hash)
    if not blob:
        raise CodeEvidenceAdapterError("AST blob_identity is required")

    def _str_tuple(name: str) -> list[str]:
        raw = payload.get(name) or ()
        if isinstance(raw, str):
            raw = (raw,)
        return sorted({_text(item) for item in raw if _text(item)})

    symbol_hashes = {
        _text(k): _text(v)
        for k, v in sorted(dict(payload.get("symbol_hashes") or {}).items())
        if _text(k) and _text(v)
    }
    symbol_lines: dict[str, list[int]] = {}
    for key, value in sorted(dict(payload.get("symbol_lines") or {}).items()):
        try:
            start, end = value
            symbol_lines[_text(key)] = [max(0, int(start)), max(0, int(end))]
        except (TypeError, ValueError):
            continue
    body = {
        "record_schema_version": version,
        "blob_identity": blob,
        "blob_hash": blob,
        "source_sha256": source_hash,
        "language": _text(payload.get("language") or "python") or "python",
        "qualified_symbols": _str_tuple("qualified_symbols"),
        "imports": _str_tuple("imports"),
        "calls": _str_tuple("calls"),
        "state_transitions": _str_tuple("state_transitions"),
        "interfaces": _str_tuple("interfaces"),
        "symbol_hashes": symbol_hashes,
        "symbol_lines": symbol_lines,
        "parse_error": _text(payload.get("parse_error")),
    }
    record_id = "ast-sha256:" + hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        .encode("utf-8")
    ).hexdigest()
    claimed = _text(payload.get("record_id"))
    if claimed and claimed != record_id:
        raise CodeEvidenceAdapterError(
            "AST blob record identity does not match payload"
        )
    return {"record_id": record_id, **body}


def normalize_ast_index(
    payload: Mapping[str, Any],
    *,
    revision: str = "",
) -> dict[str, Any]:
    schema = payload.get("schema")
    if schema not in (None, "", ANALYSIS_AST_INDEX_SCHEMA):
        raise CodeEvidenceAdapterError(
            f"unsupported analysis AST index schema {schema!r}"
        )
    schema_version = int(
        payload.get("schema_version", ANALYSIS_AST_INDEX_SCHEMA_VERSION)
    )
    if schema_version != ANALYSIS_AST_INDEX_SCHEMA_VERSION:
        raise CodeEvidenceAdapterError(
            f"unsupported analysis AST index schema version {schema_version}"
        )
    path_records: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for item in _require_sequence(
        payload.get("path_records") or (), "path_records"
    ):
        row = _require_mapping(item, "path record")
        path = _repo_path(row.get("path"))
        if path in seen_paths:
            raise CodeEvidenceAdapterError("AST index paths must be unique")
        seen_paths.add(path)
        ast_record = normalize_ast_blob_record(
            _require_mapping(row.get("ast_record"), "ast_record")
        )
        path_records.append({"path": path, "ast_record": ast_record})
    path_records.sort(key=lambda item: item["path"])
    invalidations: list[dict[str, Any]] = []
    for item in _require_sequence(
        payload.get("invalidations") or (), "invalidations"
    ):
        row = _require_mapping(item, "invalidation")
        reason = _text(row.get("reason"))
        if reason not in {"blob_changed", "path_deleted"}:
            raise CodeEvidenceAdapterError(
                f"unsupported AST invalidation reason {reason!r}"
            )
        content = {
            "path": _repo_path(row.get("path")),
            "blob_identity": _text(row.get("blob_identity")),
            "source_sha256": _text(row.get("source_sha256")),
            "record_id": _text(row.get("record_id")),
            "reason": reason,
            "replacement_blob_identity": _text(
                row.get("replacement_blob_identity")
            ),
            "replacement_record_id": _text(row.get("replacement_record_id")),
        }
        if not content["record_id"]:
            raise CodeEvidenceAdapterError(
                "AST invalidations require a record identity"
            )
        invalidation_id = _prefixed_identity("ast-invalidation", content)
        claimed = _text(row.get("invalidation_id"))
        if claimed and claimed != invalidation_id:
            raise CodeEvidenceAdapterError("AST invalidation identity mismatch")
        invalidations.append(
            {"invalidation_id": invalidation_id, **content}
        )
    invalidations.sort(key=lambda item: item["invalidation_id"])
    stats = dict(payload.get("stats") or {})
    index_id = _prefixed_identity(
        "analysis-ast-index",
        {
            "schema": ANALYSIS_AST_INDEX_SCHEMA,
            "schema_version": schema_version,
            "path_records": path_records,
        },
    )
    claimed = _text(payload.get("index_id"))
    if claimed and claimed != index_id:
        raise CodeEvidenceAdapterError(
            "analysis AST index identity does not match payload"
        )
    return {
        "schema": ANALYSIS_AST_INDEX_SCHEMA,
        "schema_version": schema_version,
        "index_id": index_id,
        "path_records": path_records,
        "invalidations": invalidations,
        "stats": stats,
        "revision": _text(payload.get("revision") or revision),
        "graph_kind": GRAPH_KIND_AST,
        "path_count": len(path_records),
        "invalidation_count": len(invalidations),
    }


def normalize_conflict_graph(
    payload: Mapping[str, Any],
    *,
    revision: str = "",
) -> dict[str, Any]:
    schema = _text(payload.get("schema") or CONFLICT_GRAPH_SCHEMA)
    if schema != CONFLICT_GRAPH_SCHEMA:
        raise CodeEvidenceAdapterError(f"unsupported conflict graph schema: {schema}")
    surfaces_raw = payload.get("surfaces") or {}
    if not isinstance(surfaces_raw, Mapping):
        raise CodeEvidenceAdapterError("conflict surfaces must be a mapping")
    surfaces: dict[str, dict[str, Any]] = {}
    for key, value in surfaces_raw.items():
        surface = _require_mapping(value, "conflict surface")
        task_id = _text(surface.get("task_id") or key)
        task_cid = _text(surface.get("task_cid") or task_id)
        if not task_id:
            raise CodeEvidenceAdapterError("conflict surface requires task_id")
        surfaces[str(key)] = {
            **surface,
            "task_id": task_id,
            "task_cid": task_cid,
            "predicted_paths": list(surface.get("predicted_paths") or []),
            "predicted_symbols": list(surface.get("predicted_symbols") or []),
            "files": list(surface.get("files") or []),
            "changed_paths": list(surface.get("changed_paths") or []),
            "ast_symbols": list(surface.get("ast_symbols") or []),
            "dependencies": list(surface.get("dependencies") or []),
            "conflicts": list(surface.get("conflicts") or []),
            "evidence_subset": list(surface.get("evidence_subset") or []),
            "revision": _text(surface.get("revision") or revision),
        }
    edges: list[dict[str, Any]] = []
    for item in _require_sequence(payload.get("edges") or (), "conflict edges"):
        edge = _require_mapping(item, "conflict edge")
        left = _text(edge.get("left_task_cid") or edge.get("left"))
        right = _text(edge.get("right_task_cid") or edge.get("right"))
        if not left or not right:
            raise CodeEvidenceAdapterError("conflict edge requires both endpoints")
        weight = float(edge.get("weight") or 0.0)
        explicitly_allowed = bool(edge.get("explicitly_allowed", False))
        blocks = weight > 0 and not explicitly_allowed
        edges.append(
            {
                **edge,
                "left_task_cid": left,
                "right_task_cid": right,
                "weight": weight,
                "explicitly_allowed": explicitly_allowed,
                "blocks_concurrency": blocks,
                "reasons": list(edge.get("reasons") or []),
                "overlaps": dict(edge.get("overlaps") or {}),
            }
        )
    assignments = [
        _require_mapping(item, "lane assignment")
        for item in _require_sequence(
            payload.get("assignments") or (), "assignments"
        )
    ]
    decisions = [
        _require_mapping(item, "lane decision")
        for item in _require_sequence(payload.get("decisions") or (), "decisions")
    ]
    lanes_raw = payload.get("lanes") or {}
    if not isinstance(lanes_raw, Mapping):
        raise CodeEvidenceAdapterError("conflict lanes must be a mapping")
    lanes = {str(k): list(v) for k, v in sorted(lanes_raw.items())}
    history = dict(payload.get("history") or {})
    return {
        "schema": CONFLICT_GRAPH_SCHEMA,
        "surfaces": dict(sorted(surfaces.items())),
        "edges": edges,
        "assignments": assignments,
        "decisions": decisions,
        "lanes": lanes,
        "history": history,
        "revision": _text(payload.get("revision") or revision),
        "graph_kind": GRAPH_KIND_CONFLICT,
        "surface_count": len(surfaces),
        "edge_count": len(edges),
        "blocking_edge_count": sum(
            1 for edge in edges if edge["blocks_concurrency"]
        ),
    }


def normalize_objective_graph(
    payload: Mapping[str, Any],
    *,
    revision: str = "",
) -> dict[str, Any]:
    schema = _text(payload.get("schema") or OBJECTIVE_GRAPH_SCHEMA)
    if schema != OBJECTIVE_GRAPH_SCHEMA:
        raise CodeEvidenceAdapterError(f"unsupported objective graph schema: {schema}")
    goals = [
        _require_mapping(item, "goal")
        for item in _require_sequence(payload.get("goals") or (), "goals")
    ]
    graph = _require_mapping(payload.get("graph") or {}, "objective graph body")
    nodes = list(graph.get("nodes") or [])
    edges = [
        _require_mapping(item, "objective edge")
        for item in _require_sequence(graph.get("edges") or (), "objective edges")
    ]
    evidence_nodes = [
        _require_mapping(item, "evidence node")
        for item in _require_sequence(
            graph.get("evidence_nodes") or (), "evidence nodes"
        )
    ]
    evidence_edges = [
        _require_mapping(item, "evidence edge")
        for item in _require_sequence(
            graph.get("evidence_edges") or (), "evidence edges"
        )
    ]
    node_details = dict(graph.get("node_details") or {})
    thought_graph = dict(payload.get("thought_graph") or {})
    if thought_graph:
        tg_schema = _text(thought_graph.get("schema"))
        if tg_schema and tg_schema != OBJECTIVE_THOUGHT_GRAPH_SCHEMA:
            raise CodeEvidenceAdapterError(
                f"unsupported thought graph schema: {tg_schema}"
            )
    return {
        "schema": OBJECTIVE_GRAPH_SCHEMA,
        "generated_at": _text(payload.get("generated_at")),
        "objective_path": _text(payload.get("objective_path")),
        "goal_count": int(payload.get("goal_count") or len(goals)),
        "active_goal_count": int(payload.get("active_goal_count") or 0),
        "completed_goal_count": int(payload.get("completed_goal_count") or 0),
        "goals": goals,
        "graph": {
            "nodes": nodes,
            "edges": edges,
            "evidence_nodes": evidence_nodes,
            "evidence_edges": evidence_edges,
            "node_details": node_details,
            "children": dict(graph.get("children") or {}),
            "depths": dict(graph.get("depths") or {}),
            "roots": list(graph.get("roots") or []),
            "lifecycle": dict(graph.get("lifecycle") or {}),
            "schedulable_goal_ids": list(
                graph.get("schedulable_goal_ids") or []
            ),
            "terminal_goal_ids": list(graph.get("terminal_goal_ids") or []),
            "state_counts": dict(graph.get("state_counts") or {}),
        },
        "thought_graph": thought_graph,
        "heap_schedule": list(payload.get("heap_schedule") or []),
        "revision": _text(payload.get("revision") or revision),
        "graph_kind": GRAPH_KIND_OBJECTIVE,
        "counts": {
            "goals": len(goals),
            "graph_nodes": len(nodes),
            "graph_edges": len(edges),
            "evidence_nodes": len(evidence_nodes),
            "evidence_edges": len(evidence_edges),
        },
    }


def normalize_impact_index(
    payload: Mapping[str, Any],
    *,
    revision: str = "",
) -> dict[str, Any]:
    schema = _text(payload.get("schema") or CODE_IMPACT_INDEX_SCHEMA)
    if schema != CODE_IMPACT_INDEX_SCHEMA:
        raise CodeEvidenceAdapterError(
            f"unsupported code impact index schema: {schema}"
        )
    repository_tree_id = _text(payload.get("repository_tree_id"))
    if not repository_tree_id:
        raise CodeEvidenceAdapterError(
            "code impact index requires repository_tree_id"
        )
    symbol_paths = {
        _text(k): _repo_path(v)
        for k, v in sorted(dict(payload.get("symbol_paths") or {}).items())
        if _text(k)
    }
    symbol_dependencies: dict[str, list[str]] = {}
    known_symbols = set(symbol_paths)
    for dependent, deps in dict(payload.get("symbol_dependencies") or {}).items():
        dep = _text(dependent)
        values = sorted({_text(item) for item in (deps or []) if _text(item)})
        unknown = {dep, *values} - known_symbols
        if unknown:
            raise CodeEvidenceAdapterError(
                "symbol dependency references unknown symbols: "
                + ", ".join(sorted(unknown))
            )
        if dep in values:
            raise CodeEvidenceAdapterError(
                "symbol dependency cannot reference itself"
            )
        symbol_dependencies[dep] = values
    path_dependencies: dict[str, list[str]] = {}
    for dependent, deps in dict(payload.get("path_dependencies") or {}).items():
        dep = _repo_path(dependent)
        values = sorted(
            {
                _repo_path(item)
                for item in (
                    (deps,) if isinstance(deps, str) else (deps or [])
                )
            }
        )
        if dep in values:
            raise CodeEvidenceAdapterError(
                "path dependency cannot reference itself"
            )
        path_dependencies[dep] = values
    validation_targets: dict[str, list[str]] = {}
    known_paths = set(symbol_paths.values())
    known_paths.update(path_dependencies)
    for deps in path_dependencies.values():
        known_paths.update(deps)
    known_targets = known_symbols | known_paths
    for validation_id, targets in dict(
        payload.get("validation_targets") or {}
    ).items():
        vid = _text(validation_id)
        values = sorted({_text(item) for item in (targets or []) if _text(item)})
        if not vid or not values:
            raise CodeEvidenceAdapterError(
                "validation target requires identity and targets"
            )
        unknown = set(values) - known_targets
        if unknown:
            raise CodeEvidenceAdapterError(
                "validation references unknown impact targets: "
                + ", ".join(sorted(unknown))
            )
        validation_targets[vid] = values
    index_version = _text(payload.get("index_version") or "code-impact-index-v1")
    identity_payload = {
        "schema": CODE_IMPACT_INDEX_SCHEMA,
        "repository_tree_id": repository_tree_id,
        "index_version": index_version,
        "symbol_paths": dict(sorted(symbol_paths.items())),
        "symbol_dependencies": {
            k: symbol_dependencies[k] for k in sorted(symbol_dependencies)
        },
        "path_dependencies": {
            k: path_dependencies[k] for k in sorted(path_dependencies)
        },
        "validation_targets": {
            k: validation_targets[k] for k in sorted(validation_targets)
        },
    }
    index_id = content_identity(identity_payload)
    claimed = _text(payload.get("index_id"))
    if claimed and claimed != index_id:
        raise CodeEvidenceAdapterError(
            "code impact index identity does not match payload"
        )
    return {
        **identity_payload,
        "index_id": index_id,
        "revision": _text(payload.get("revision") or revision),
        "graph_kind": GRAPH_KIND_IMPACT,
    }


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def _adjacency(
    edges: Sequence[Mapping[str, Any]],
    *,
    source_key: str = "source",
    target_key: str = "target",
    authoritative_only: bool = False,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        if authoritative_only and not edge.get("authoritative"):
            continue
        outgoing[edge[source_key]].append(dict(edge))
        incoming[edge[target_key]].append(dict(edge))
    return outgoing, incoming


def dependency_closure(
    *,
    seed_ids: Iterable[str],
    edges: Sequence[Mapping[str, Any]],
    direction: str = "forward",
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_nodes: int = DEFAULT_MAX_NODES,
    max_edges: int = DEFAULT_MAX_EDGES,
    authoritative_only: bool = False,
    edge_kinds: frozenset[str] | None = None,
    source_key: str = "source",
    target_key: str = "target",
) -> dict[str, Any]:
    """Bounded dependency closure over a typed edge set.

    *forward*: seed → dependencies (follow source→target)
    *reverse*: seed ← dependents (follow target→source) — impact-style
    *both*: undirected union of both
    """

    if direction not in {"forward", "reverse", "both"}:
        raise CodeEvidenceAdapterError(f"invalid dependency direction: {direction}")
    if max_depth < 0 or max_nodes < 1 or max_edges < 0:
        raise CodeEvidenceAdapterError("invalid dependency bounds")
    outgoing, incoming = _adjacency(
        edges,
        source_key=source_key,
        target_key=target_key,
        authoritative_only=authoritative_only,
    )
    seeds = tuple(sorted({_text(item) for item in seed_ids if _text(item)}))
    if not seeds:
        raise CodeEvidenceAdapterError("dependency query requires at least one seed")

    visited: set[str] = set(seeds)
    paths: dict[str, tuple[str, ...]] = {seed: (seed,) for seed in seeds}
    depths: dict[str, int] = {seed: 0 for seed in seeds}
    included_edges: list[dict[str, Any]] = []
    seen_edge_ids: set[str] = set()
    queue: deque[str] = deque(seeds)

    def _neighbors(node_id: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if direction in {"forward", "both"}:
            rows.extend(outgoing.get(node_id, ()))
        if direction in {"reverse", "both"}:
            for edge in incoming.get(node_id, ()):
                flipped = dict(edge)
                flipped["_walk_source"] = edge[target_key]
                flipped["_walk_target"] = edge[source_key]
                rows.append(flipped)
        return rows

    while queue:
        current = queue.popleft()
        if depths[current] >= max_depth:
            continue
        for edge in _neighbors(current):
            kind = _text(edge.get("kind") or edge.get("edge_kind"))
            if edge_kinds is not None and kind not in edge_kinds:
                continue
            nxt = edge.get("_walk_target") or edge[target_key]
            if direction == "reverse" and "_walk_target" not in edge:
                nxt = edge[source_key]
            if direction == "forward":
                nxt = edge[target_key]
            edge_id = _text(edge.get("edge_id")) or content_identity(edge)
            if edge_id not in seen_edge_ids:
                if len(seen_edge_ids) >= max_edges:
                    raise CodeEvidenceAdapterError(
                        "dependency query exceeds max_edges"
                    )
                seen_edge_ids.add(edge_id)
                included_edges.append(
                    {k: v for k, v in edge.items() if not str(k).startswith("_")}
                )
            candidate = (*paths[current], nxt)
            previous = paths.get(nxt)
            depth = depths[current] + 1
            if previous is None:
                if len(visited) >= max_nodes:
                    raise CodeEvidenceAdapterError(
                        "dependency query exceeds max_nodes"
                    )
                visited.add(nxt)
                paths[nxt] = candidate
                depths[nxt] = depth
                queue.append(nxt)
            elif (len(candidate), candidate) < (len(previous), previous):
                paths[nxt] = candidate
                depths[nxt] = depth

    return {
        "schema": "code-evidence-dependency-query/v1",
        "direction": direction,
        "seeds": list(seeds),
        "node_ids": sorted(visited),
        "node_count": len(visited),
        "edges": included_edges,
        "edge_count": len(included_edges),
        "paths": {key: list(value) for key, value in sorted(paths.items())},
        "depths": dict(sorted(depths.items())),
        "authoritative_only": authoritative_only,
        "truncated": False,
    }


def impact_from_index(
    index: Mapping[str, Any],
    *,
    changed_symbols: Iterable[str] = (),
    changed_paths: Iterable[str] = (),
) -> dict[str, Any]:
    """Deterministic reverse dependency impact over a code impact index."""

    symbol_paths = dict(index.get("symbol_paths") or {})
    symbol_dependencies = {
        k: list(v) for k, v in dict(index.get("symbol_dependencies") or {}).items()
    }
    path_dependencies = {
        k: list(v) for k, v in dict(index.get("path_dependencies") or {}).items()
    }
    validation_targets = {
        k: list(v) for k, v in dict(index.get("validation_targets") or {}).items()
    }

    explicit_symbols = {_text(s) for s in changed_symbols if _text(s)}
    explicit_paths = {_repo_path(p) for p in changed_paths if _text(p)}
    inferred_symbols = {
        symbol
        for symbol, path in symbol_paths.items()
        if path in explicit_paths
    }
    known_changed_symbols = (explicit_symbols | inferred_symbols) & set(
        symbol_paths
    )
    uncovered_symbols = tuple(sorted(explicit_symbols - set(symbol_paths)))

    # Reverse maps: provider -> dependents
    rev_symbols: dict[str, list[str]] = defaultdict(list)
    for dependent, providers in symbol_dependencies.items():
        for provider in providers:
            rev_symbols[provider].append(dependent)
    rev_paths: dict[str, list[str]] = defaultdict(list)
    for dependent, providers in path_dependencies.items():
        for provider in providers:
            rev_paths[provider].append(dependent)

    def _closure(
        roots: Iterable[str], reverse: Mapping[str, Sequence[str]]
    ) -> tuple[list[str], dict[str, list[str]]]:
        normalized = tuple(sorted(set(roots)))
        chains: dict[str, list[str]] = {root: [root] for root in normalized}
        queue = deque(normalized)
        while queue:
            current = queue.popleft()
            for dependent in reverse.get(current, ()):
                candidate = [*chains[current], dependent]
                existing = chains.get(dependent)
                if existing is None or (len(candidate), candidate) < (
                    len(existing),
                    existing,
                ):
                    chains[dependent] = candidate
                    queue.append(dependent)
        return sorted(chains), chains

    affected_symbols, symbol_chains = _closure(known_changed_symbols, rev_symbols)
    symbol_affected_paths = {
        symbol_paths[symbol] for symbol in affected_symbols if symbol in symbol_paths
    }
    path_roots = explicit_paths | symbol_affected_paths
    known_paths = set(symbol_paths.values())
    known_paths.update(path_dependencies)
    for deps in path_dependencies.values():
        known_paths.update(deps)
    uncovered_paths = tuple(sorted(explicit_paths - known_paths))
    affected_paths, path_chains = _closure(path_roots, rev_paths)

    impacted_targets = set(affected_symbols) | set(affected_paths)
    validation_reasons = {
        validation_id: sorted(impacted_targets.intersection(targets))
        for validation_id, targets in validation_targets.items()
        if impacted_targets.intersection(targets)
    }
    chains = {k: list(v) for k, v in symbol_chains.items()}
    for target, chain in path_chains.items():
        chains.setdefault(target, list(chain))

    return {
        "schema": CODE_IMPACT_RESULT_SCHEMA,
        "repository_tree_id": index.get("repository_tree_id"),
        "index_id": index.get("index_id"),
        "changed_symbols": sorted(explicit_symbols | inferred_symbols),
        "affected_symbols": list(affected_symbols),
        "changed_paths": sorted(explicit_paths),
        "affected_paths": list(affected_paths),
        "dependency_chains": {
            key: value for key, value in sorted(chains.items())
        },
        "required_validation_ids": sorted(validation_reasons),
        "validation_reasons": {
            key: value for key, value in sorted(validation_reasons.items())
        },
        "uncovered_symbols": list(uncovered_symbols),
        "uncovered_paths": list(uncovered_paths),
        "uncovered_impact": bool(uncovered_symbols or uncovered_paths),
    }


def provenance_trace(
    *,
    seed_ids: Iterable[str],
    nodes: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> dict[str, Any]:
    """Collect provenance records reachable from seeds via typed edges."""

    node_map = {
        _text(node.get("node_id") or node.get("id")): dict(node)
        for node in nodes
        if _text(node.get("node_id") or node.get("id"))
    }
    closure = dependency_closure(
        seed_ids=seed_ids,
        edges=edges,
        direction="both",
        max_depth=max_depth,
        authoritative_only=False,
    )
    records: list[dict[str, Any]] = []
    for node_id in closure["node_ids"]:
        node = node_map.get(node_id)
        if node is None:
            continue
        records.append(
            {
                "node_id": node_id,
                "kind": node.get("kind"),
                "provenance": node.get("provenance"),
                "provenance_id": node.get("provenance_id")
                or node.get("record_key"),
                "authoritative": bool(node.get("authoritative")),
                "revision": node.get("revision") or node.get("version") or "",
                "record": node.get("record") or {},
            }
        )
    edge_provenance = [
        {
            "edge_id": edge.get("edge_id"),
            "kind": edge.get("kind"),
            "provenance": edge.get("provenance"),
            "provenance_record_id": edge.get("provenance_record_id")
            or edge.get("provenance_id"),
            "authoritative": bool(edge.get("authoritative")),
            "source": edge.get("source"),
            "target": edge.get("target"),
        }
        for edge in closure["edges"]
    ]
    return {
        "schema": "code-evidence-provenance-query/v1",
        "seeds": list(closure["seeds"]),
        "node_records": records,
        "edge_records": edge_provenance,
        "node_count": len(records),
        "edge_count": len(edge_provenance),
        "paths": closure["paths"],
    }


def mandatory_semantic_closure(
    graph: Mapping[str, Any],
    decision_id: str,
    *,
    max_nodes: int = DEFAULT_MAX_CLOSURE_NODES,
    max_edges: int = DEFAULT_MAX_CLOSURE_EDGES,
    max_depth: int = DEFAULT_MAX_CLOSURE_DEPTH,
) -> dict[str, Any]:
    """Forward mandatory authority closure for a semantic decision seed."""

    node_map = {node["node_id"]: node for node in graph["nodes"]}
    try:
        seed = node_map[decision_id]
    except KeyError as exc:
        raise CodeEvidenceAdapterError(
            f"unknown decision seed: {decision_id}"
        ) from exc
    if seed["kind"] != "decision":
        raise CodeEvidenceAdapterError("mandatory closure seed must be a decision")
    if not seed["authoritative"]:
        raise CodeEvidenceAdapterError(
            "mandatory closure seed must be authority-bearing"
        )
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in graph["edges"]:
        outgoing[edge["source"]].append(edge)
    for values in outgoing.values():
        values.sort(key=lambda item: (item["kind"], item["target"], item["edge_id"]))

    paths: dict[str, tuple[str, ...]] = {decision_id: (decision_id,)}
    depths = {decision_id: 0}
    included_edges: set[str] = set()
    queue: deque[str] = deque((decision_id,))
    while queue:
        current = queue.popleft()
        for edge in outgoing.get(current, ()):
            if not edge.get("authoritative") or not edge.get("mandatory"):
                continue
            target = node_map[edge["target"]]
            if not target.get("authoritative"):
                raise CodeEvidenceAdapterError(
                    "mandatory authority edge reached a non-authoritative node"
                )
            depth = depths[current] + 1
            if depth > max_depth:
                raise CodeEvidenceAdapterError(
                    "mandatory closure exceeds max_depth"
                )
            included_edges.add(edge["edge_id"])
            if len(included_edges) > max_edges:
                raise CodeEvidenceAdapterError(
                    "mandatory closure exceeds max_edges"
                )
            candidate = (*paths[current], edge["target"])
            previous = paths.get(edge["target"])
            if previous is None:
                paths[edge["target"]] = candidate
                depths[edge["target"]] = depth
                if len(paths) > max_nodes:
                    raise CodeEvidenceAdapterError(
                        "mandatory closure exceeds max_nodes"
                    )
                queue.append(edge["target"])
            elif (len(candidate), candidate) < (len(previous), previous):
                paths[edge["target"]] = candidate
                depths[edge["target"]] = depth
    return {
        "schema": MANDATORY_CLOSURE_SCHEMA,
        "root_id": graph["root_id"],
        "decision_id": decision_id,
        "node_ids": sorted(paths),
        "edge_ids": sorted(included_edges),
        "paths": {key: list(value) for key, value in sorted(paths.items())},
        "complete": True,
        "bounds": {
            "max_nodes": max_nodes,
            "max_edges": max_edges,
            "max_depth": max_depth,
        },
    }


# ---------------------------------------------------------------------------
# Incremental updates (working copy only)
# ---------------------------------------------------------------------------


def apply_incremental_update(
    graph: Mapping[str, Any],
    *,
    graph_family: str,
    upsert_nodes: Sequence[Mapping[str, Any]] = (),
    upsert_edges: Sequence[Mapping[str, Any]] = (),
    remove_node_ids: Sequence[str] = (),
    remove_edge_ids: Sequence[str] = (),
    revision: str = "",
    allow_unknown_kinds: bool = True,
) -> dict[str, Any]:
    """Apply a deterministic incremental patch to a working graph copy.

    On-disk artifacts are never modified. The result is a freshly normalized
    graph bound to ``revision`` when supplied.
    """

    family = _text(graph_family)
    remove_nodes = {_text(item) for item in remove_node_ids if _text(item)}
    remove_edges = {_text(item) for item in remove_edge_ids if _text(item)}
    working = copy.deepcopy(dict(graph))

    if family in {"code_evidence", GRAPH_KIND_CODE_EVIDENCE}:
        nodes = [
            node
            for node in working.get("nodes") or []
            if node.get("node_id") not in remove_nodes
        ]
        edges = [
            edge
            for edge in working.get("edges") or []
            if edge.get("edge_id") not in remove_edges
            and edge.get("source") not in remove_nodes
            and edge.get("target") not in remove_nodes
        ]
        # Strip internal meta before re-normalization.
        def _public_node(node: Mapping[str, Any]) -> dict[str, Any]:
            return {
                k: v
                for k, v in node.items()
                if k not in {"kind_meta"}
            }

        def _public_edge(edge: Mapping[str, Any]) -> dict[str, Any]:
            return {
                k: v
                for k, v in edge.items()
                if k not in {"kind_meta"}
            }

        node_map = {_public_node(n)["node_id"]: _public_node(n) for n in nodes}
        for raw in upsert_nodes:
            normalized = normalize_code_evidence_node(
                raw, allow_unknown_kinds=allow_unknown_kinds
            )
            node_map[normalized["node_id"]] = _public_node(normalized)
        edge_map = {_public_edge(e)["edge_id"]: _public_edge(e) for e in edges}
        for raw in upsert_edges:
            normalized = normalize_code_evidence_edge(
                raw, allow_unknown_kinds=allow_unknown_kinds
            )
            edge_map[normalized["edge_id"]] = _public_edge(normalized)
        result = normalize_code_evidence_graph(
            {
                "schema": CODE_EVIDENCE_GRAPH_SCHEMA,
                "nodes": list(node_map.values()),
                "edges": list(edge_map.values()),
                "revision": revision or working.get("revision") or "",
            },
            allow_unknown_kinds=allow_unknown_kinds,
            revision=revision or _text(working.get("revision")),
        )
    elif family in {"semantic", "semantic_dependency", GRAPH_KIND_SEMANTIC}:
        nodes = [
            node
            for node in working.get("nodes") or []
            if node.get("node_id") not in remove_nodes
        ]
        edges = [
            edge
            for edge in working.get("edges") or []
            if edge.get("edge_id") not in remove_edges
            and edge.get("source") not in remove_nodes
            and edge.get("target") not in remove_nodes
        ]

        def _pub(item: Mapping[str, Any]) -> dict[str, Any]:
            return {k: v for k, v in item.items() if k not in {"kind_meta"}}

        node_map = {_pub(n)["node_id"]: _pub(n) for n in nodes}
        for raw in upsert_nodes:
            normalized = normalize_semantic_node(
                raw, allow_unknown_kinds=allow_unknown_kinds
            )
            node_map[normalized["node_id"]] = _pub(normalized)
        edge_map = {_pub(e)["edge_id"]: _pub(e) for e in edges}
        for raw in upsert_edges:
            normalized = normalize_semantic_edge(
                raw, allow_unknown_kinds=allow_unknown_kinds
            )
            edge_map[normalized["edge_id"]] = _pub(normalized)
        result = normalize_semantic_dependency_graph(
            {
                "schema": SEMANTIC_DEPENDENCY_GRAPH_SCHEMA,
                "root_id": working["root_id"],
                "nodes": list(node_map.values()),
                "edges": list(edge_map.values()),
                "revision": revision or working.get("revision") or "",
            },
            allow_unknown_kinds=allow_unknown_kinds,
            revision=revision or _text(working.get("revision")),
        )
    else:
        raise CodeEvidenceAdapterError(
            f"incremental updates unsupported for family {family!r}"
        )

    return {
        "schema": INCREMENTAL_UPDATE_SCHEMA,
        "graph_family": family,
        "revision": result.get("revision") or revision,
        "removed_nodes": sorted(remove_nodes),
        "removed_edges": sorted(remove_edges),
        "upserted_nodes": len(list(upsert_nodes)),
        "upserted_edges": len(list(upsert_edges)),
        "graph": result,
        "graph_id": result.get("graph_id"),
        "node_count": result.get("node_count"),
        "edge_count": result.get("edge_count"),
    }


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_bundle_root() -> Path | None:
    for name in (ENV_BUNDLE_ROOT, ENV_BUNDLE_ROOT_ALT):
        path = _env_path(name)
        if path is not None and path.is_dir():
            return path
    return None


def discover_objective_graph_path() -> Path | None:
    env = _env_path(ENV_OBJECTIVE_ROOT)
    if env is not None:
        if env.is_file():
            return env
        candidate = env / "objective_graph.json"
        if candidate.is_file():
            return candidate
    for root in DEFAULT_OBJECTIVE_CANDIDATES:
        candidate = root / "objective_graph.json"
        if candidate.is_file():
            return candidate
    return None


def validate_bundle_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    schema = _text(manifest.get("schema") or BUNDLE_MANIFEST_SCHEMA)
    if schema != BUNDLE_MANIFEST_SCHEMA:
        raise CodeEvidenceAdapterError(f"unsupported bundle manifest schema: {schema}")
    revision = _text(manifest.get("revision"))
    if not revision:
        raise CodeEvidenceAdapterError("bundle manifest requires revision binding")
    artifacts = manifest.get("artifacts") or {}
    if not isinstance(artifacts, Mapping) or not artifacts:
        raise CodeEvidenceAdapterError("bundle manifest requires artifacts map")
    graph_kinds = list(manifest.get("graph_kinds") or [])
    required = {
        "objective_graph",
        "semantic_dependency_graph",
        "analysis_ast_index",
        "conflict_graph",
        "code_evidence_graph",
        "code_impact_index",
    }
    missing = sorted(required - set(artifacts))
    if missing:
        raise CodeEvidenceAdapterError(
            f"bundle manifest missing artifacts: {', '.join(missing)}"
        )
    return {
        "schema": schema,
        "revision": revision,
        "program": _text(manifest.get("program")),
        "graph_kinds": graph_kinds,
        "artifacts": dict(artifacts),
        "artifact_checksums": dict(manifest.get("artifact_checksums") or {}),
        "provenance": dict(manifest.get("provenance") or {}),
        "counts": dict(manifest.get("counts") or {}),
    }


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class CodeEvidenceCorpusAdapter:
    """Fail-closed reader over a supervisor multi-graph bundle.

    The adapter loads objective, semantic dependency, AST index, conflict, and
    code-evidence (+ impact index) JSON records. Working-copy incremental
    updates never write back to the bundle directory.
    """

    def __init__(
        self,
        bundle_root: Path | str,
        *,
        revision: str | None = None,
        allow_unknown_kinds: bool = True,
        objective_path: Path | str | None = None,
    ) -> None:
        self.bundle_root = Path(bundle_root)
        if not self.bundle_root.is_dir():
            raise CodeEvidenceAdapterError(
                f"bundle root does not exist: {self.bundle_root}"
            )
        self.allow_unknown_kinds = allow_unknown_kinds
        self._objective_override = (
            Path(objective_path) if objective_path is not None else None
        )
        self._manifest = self._load_manifest()
        self.revision = _text(revision or self._manifest.get("revision"))
        if not self.revision:
            raise CodeEvidenceAdapterError("adapter requires a revision binding")
        self._cache: dict[str, dict[str, Any]] = {}
        self._working: dict[str, dict[str, Any]] = {}

    def _load_manifest(self) -> dict[str, Any]:
        path = self.bundle_root / BUNDLE_ARTIFACTS["manifest"]
        return validate_bundle_manifest(_load_json(path))

    def _artifact_path(self, name: str) -> Path:
        relative = self._manifest["artifacts"].get(name) or BUNDLE_ARTIFACTS.get(
            name
        )
        if not relative:
            raise CodeEvidenceAdapterError(f"unknown artifact: {name}")
        path = self.bundle_root / relative
        if not path.is_file() or path.is_symlink():
            raise CodeEvidenceAdapterError(f"missing artifact: {name}")
        return path

    def _load_artifact(self, name: str) -> dict[str, Any]:
        return _require_mapping(_load_json(self._artifact_path(name)), name)

    def load_objective_graph(self, *, use_cache: bool = True) -> dict[str, Any]:
        if use_cache and "objective" in self._cache:
            return self._cache["objective"]
        if self._objective_override is not None:
            payload = _require_mapping(
                _load_json(self._objective_override), "objective_graph"
            )
        else:
            payload = self._load_artifact("objective_graph")
        graph = normalize_objective_graph(payload, revision=self.revision)
        self._cache["objective"] = graph
        return graph

    def load_semantic_dependency_graph(
        self, *, use_cache: bool = True
    ) -> dict[str, Any]:
        if use_cache and "semantic" in self._cache:
            return self._cache["semantic"]
        payload = self._load_artifact("semantic_dependency_graph")
        graph = normalize_semantic_dependency_graph(
            payload,
            allow_unknown_kinds=self.allow_unknown_kinds,
            revision=self.revision,
        )
        self._cache["semantic"] = graph
        return graph

    def load_ast_index(self, *, use_cache: bool = True) -> dict[str, Any]:
        if use_cache and "ast" in self._cache:
            return self._cache["ast"]
        payload = self._load_artifact("analysis_ast_index")
        graph = normalize_ast_index(payload, revision=self.revision)
        self._cache["ast"] = graph
        return graph

    def load_conflict_graph(self, *, use_cache: bool = True) -> dict[str, Any]:
        if use_cache and "conflict" in self._cache:
            return self._cache["conflict"]
        payload = self._load_artifact("conflict_graph")
        graph = normalize_conflict_graph(payload, revision=self.revision)
        self._cache["conflict"] = graph
        return graph

    def load_code_evidence_graph(
        self, *, use_cache: bool = True
    ) -> dict[str, Any]:
        if use_cache and "code_evidence" in self._cache:
            return self._cache["code_evidence"]
        payload = self._load_artifact("code_evidence_graph")
        graph = normalize_code_evidence_graph(
            payload,
            allow_unknown_kinds=self.allow_unknown_kinds,
            revision=self.revision,
        )
        self._cache["code_evidence"] = graph
        return graph

    def load_impact_index(self, *, use_cache: bool = True) -> dict[str, Any]:
        if use_cache and "impact" in self._cache:
            return self._cache["impact"]
        payload = self._load_artifact("code_impact_index")
        graph = normalize_impact_index(payload, revision=self.revision)
        self._cache["impact"] = graph
        return graph

    def working_code_evidence_graph(self) -> dict[str, Any]:
        if "code_evidence" not in self._working:
            self._working["code_evidence"] = copy.deepcopy(
                self.load_code_evidence_graph()
            )
        return self._working["code_evidence"]

    def working_semantic_graph(self) -> dict[str, Any]:
        if "semantic" not in self._working:
            self._working["semantic"] = copy.deepcopy(
                self.load_semantic_dependency_graph()
            )
        return self._working["semantic"]

    def validate(self, *, verify_checksums: bool = True) -> dict[str, Any]:
        """Validate all bundle graphs and revision binding."""

        kinds: dict[str, Any] = {}
        checksums_verified = 0
        for name in (
            "objective_graph",
            "semantic_dependency_graph",
            "analysis_ast_index",
            "conflict_graph",
            "code_evidence_graph",
            "code_impact_index",
        ):
            path = self._artifact_path(name)
            entry: dict[str, Any] = {
                "path": path.name,
                "size_bytes": path.stat().st_size,
                "present": True,
            }
            if verify_checksums:
                digest = _sha256_file(path)
                entry["sha256"] = digest
                expected = (
                    (self._manifest.get("artifacts") or {})
                    .get(name)
                )
                # artifacts may be path strings or descriptor maps
                desc = self._manifest.get("artifact_checksums") or {}
                if name in desc:
                    if desc[name] != digest:
                        raise CodeEvidenceAdapterError(
                            f"artifact digest differs: {name}"
                        )
                    entry["checksum_verified"] = True
                    checksums_verified += 1
                else:
                    entry["checksum_verified"] = False
            kinds[name] = entry

        objective = self.load_objective_graph()
        semantic = self.load_semantic_dependency_graph()
        ast_index = self.load_ast_index()
        conflict = self.load_conflict_graph()
        evidence = self.load_code_evidence_graph()
        impact = self.load_impact_index()

        # Revision binding: every loaded graph reports the bundle revision.
        for label, graph in (
            ("objective", objective),
            ("semantic", semantic),
            ("ast", ast_index),
            ("conflict", conflict),
            ("code_evidence", evidence),
            ("impact", impact),
        ):
            bound = _text(graph.get("revision"))
            if bound and bound != self.revision:
                raise CodeEvidenceAdapterError(
                    f"{label} revision {bound!r} does not match bundle "
                    f"revision {self.revision!r}"
                )

        return {
            "schema": VALIDATION_RECEIPT_SCHEMA,
            "revision": self.revision,
            "bundle_root": str(self.bundle_root),
            "manifest": {
                "schema": self._manifest["schema"],
                "revision": self._manifest["revision"],
                "program": self._manifest.get("program"),
                "graph_kinds": self._manifest.get("graph_kinds"),
                "provenance": self._manifest.get("provenance"),
            },
            "artifacts": kinds,
            "checksums_verified": checksums_verified,
            "graphs": {
                "objective": {
                    "schema": objective["schema"],
                    "counts": objective["counts"],
                    "revision": objective.get("revision"),
                },
                "semantic_dependency": {
                    "schema": semantic["schema"],
                    "graph_id": semantic["graph_id"],
                    "root_id": semantic["root_id"],
                    "node_count": semantic["node_count"],
                    "edge_count": semantic["edge_count"],
                    "unknown_optional_node_kinds": semantic[
                        "unknown_optional_node_kinds"
                    ],
                    "unknown_optional_edge_kinds": semantic[
                        "unknown_optional_edge_kinds"
                    ],
                    "revision": semantic.get("revision"),
                },
                "ast_index": {
                    "schema": ast_index["schema"],
                    "index_id": ast_index["index_id"],
                    "path_count": ast_index["path_count"],
                    "invalidation_count": ast_index["invalidation_count"],
                    "revision": ast_index.get("revision"),
                },
                "conflict": {
                    "schema": conflict["schema"],
                    "surface_count": conflict["surface_count"],
                    "edge_count": conflict["edge_count"],
                    "blocking_edge_count": conflict["blocking_edge_count"],
                    "revision": conflict.get("revision"),
                },
                "code_evidence": {
                    "schema": evidence["schema"],
                    "graph_id": evidence["graph_id"],
                    "node_count": evidence["node_count"],
                    "edge_count": evidence["edge_count"],
                    "unknown_optional_node_kinds": evidence[
                        "unknown_optional_node_kinds"
                    ],
                    "unknown_optional_edge_kinds": evidence[
                        "unknown_optional_edge_kinds"
                    ],
                    "revision": evidence.get("revision"),
                },
                "impact_index": {
                    "schema": impact["schema"],
                    "index_id": impact["index_id"],
                    "repository_tree_id": impact["repository_tree_id"],
                    "symbol_count": len(impact["symbol_paths"]),
                    "revision": impact.get("revision"),
                },
            },
            "provenance": self._manifest.get("provenance") or {},
        }

    # -- Queries -------------------------------------------------------------

    def dependency_query(
        self,
        *,
        family: str = "code_evidence",
        seed_ids: Sequence[str],
        direction: str = "forward",
        max_depth: int = DEFAULT_MAX_DEPTH,
        authoritative_only: bool = False,
        edge_kinds: Sequence[str] | None = None,
        use_working: bool = False,
    ) -> dict[str, Any]:
        fam = _text(family)
        kinds = frozenset(edge_kinds) if edge_kinds is not None else None
        if fam in {"code_evidence", GRAPH_KIND_CODE_EVIDENCE}:
            graph = (
                self.working_code_evidence_graph()
                if use_working
                else self.load_code_evidence_graph()
            )
            result = dependency_closure(
                seed_ids=seed_ids,
                edges=graph["edges"],
                direction=direction,
                max_depth=max_depth,
                authoritative_only=authoritative_only,
                edge_kinds=kinds,
            )
            result["family"] = "code_evidence"
            result["graph_id"] = graph["graph_id"]
            result["revision"] = graph.get("revision") or self.revision
            return result
        if fam in {"semantic", "semantic_dependency", GRAPH_KIND_SEMANTIC}:
            graph = (
                self.working_semantic_graph()
                if use_working
                else self.load_semantic_dependency_graph()
            )
            result = dependency_closure(
                seed_ids=seed_ids,
                edges=graph["edges"],
                direction=direction,
                max_depth=max_depth,
                authoritative_only=authoritative_only,
                edge_kinds=kinds,
            )
            result["family"] = "semantic_dependency"
            result["graph_id"] = graph["graph_id"]
            result["root_id"] = graph["root_id"]
            result["revision"] = graph.get("revision") or self.revision
            return result
        if fam in {"objective", GRAPH_KIND_OBJECTIVE}:
            graph = self.load_objective_graph()
            body = graph["graph"]
            # Objective edges use from/to rather than source/target.
            edges = [
                {
                    "edge_id": f"obj-{item.get('from')}-{item.get('kind')}-{item.get('to')}",
                    "source": item.get("from"),
                    "target": item.get("to"),
                    "kind": item.get("kind"),
                    "authoritative": True,
                    "provenance": "objective",
                }
                for item in body["edges"]
            ]
            evidence_edges = [
                {
                    "edge_id": f"ev-{item.get('from')}-{item.get('kind')}-{item.get('to')}",
                    "source": item.get("from"),
                    "target": item.get("to"),
                    "kind": item.get("kind"),
                    "authoritative": True,
                    "provenance": "evidence",
                }
                for item in body["evidence_edges"]
            ]
            result = dependency_closure(
                seed_ids=seed_ids,
                edges=[*edges, *evidence_edges],
                direction=direction,
                max_depth=max_depth,
                authoritative_only=authoritative_only,
                edge_kinds=kinds,
            )
            result["family"] = "objective"
            result["revision"] = graph.get("revision") or self.revision
            return result
        raise CodeEvidenceAdapterError(f"unknown dependency family: {fam}")

    def impact_query(
        self,
        *,
        changed_symbols: Sequence[str] = (),
        changed_paths: Sequence[str] = (),
        include_evidence_reverse: bool = True,
    ) -> dict[str, Any]:
        index = self.load_impact_index()
        impact = impact_from_index(
            index,
            changed_symbols=changed_symbols,
            changed_paths=changed_paths,
        )
        impact["revision"] = index.get("revision") or self.revision
        if include_evidence_reverse and (
            impact["affected_symbols"] or impact["changed_symbols"]
        ):
            evidence = self.load_code_evidence_graph()
            symbol_nodes = [
                node["node_id"]
                for node in evidence["nodes"]
                if node.get("symbol")
                in set(impact["affected_symbols"]) | set(impact["changed_symbols"])
            ]
            if symbol_nodes:
                reverse = dependency_closure(
                    seed_ids=symbol_nodes,
                    edges=evidence["edges"],
                    direction="reverse",
                    max_depth=8,
                    authoritative_only=True,
                )
                impact["evidence_reverse_closure"] = {
                    "node_ids": reverse["node_ids"],
                    "edge_count": reverse["edge_count"],
                }
        return impact

    def provenance_query(
        self,
        *,
        family: str = "code_evidence",
        seed_ids: Sequence[str],
        max_depth: int = DEFAULT_MAX_DEPTH,
        use_working: bool = False,
    ) -> dict[str, Any]:
        fam = _text(family)
        if fam in {"code_evidence", GRAPH_KIND_CODE_EVIDENCE}:
            graph = (
                self.working_code_evidence_graph()
                if use_working
                else self.load_code_evidence_graph()
            )
            result = provenance_trace(
                seed_ids=seed_ids,
                nodes=graph["nodes"],
                edges=graph["edges"],
                max_depth=max_depth,
            )
            result["family"] = "code_evidence"
            result["graph_id"] = graph["graph_id"]
            result["revision"] = graph.get("revision") or self.revision
            return result
        if fam in {"semantic", "semantic_dependency", GRAPH_KIND_SEMANTIC}:
            graph = (
                self.working_semantic_graph()
                if use_working
                else self.load_semantic_dependency_graph()
            )
            result = provenance_trace(
                seed_ids=seed_ids,
                nodes=graph["nodes"],
                edges=graph["edges"],
                max_depth=max_depth,
            )
            result["family"] = "semantic_dependency"
            result["graph_id"] = graph["graph_id"]
            result["revision"] = graph.get("revision") or self.revision
            return result
        raise CodeEvidenceAdapterError(f"unknown provenance family: {fam}")

    def semantic_mandatory_closure(
        self, decision_id: str, **bounds: Any
    ) -> dict[str, Any]:
        graph = self.load_semantic_dependency_graph()
        result = mandatory_semantic_closure(graph, decision_id, **bounds)
        result["revision"] = graph.get("revision") or self.revision
        return result

    def conflict_query(
        self,
        *,
        task_cid: str | None = None,
        blocking_only: bool = True,
    ) -> dict[str, Any]:
        graph = self.load_conflict_graph()
        edges = list(graph["edges"])
        if blocking_only:
            edges = [edge for edge in edges if edge.get("blocks_concurrency")]
        if task_cid:
            cid = _text(task_cid)
            edges = [
                edge
                for edge in edges
                if cid
                in {edge.get("left_task_cid"), edge.get("right_task_cid")}
            ]
            surface = graph["surfaces"].get(cid) or next(
                (
                    value
                    for value in graph["surfaces"].values()
                    if value.get("task_cid") == cid
                    or value.get("task_id") == cid
                ),
                None,
            )
        else:
            surface = None
        return {
            "schema": "code-evidence-conflict-query/v1",
            "revision": graph.get("revision") or self.revision,
            "task_cid": task_cid,
            "edge_count": len(edges),
            "edges": edges,
            "surface": surface,
            "lanes": graph["lanes"],
            "assignments": graph["assignments"],
        }

    def ast_lookup(
        self,
        *,
        path: str | None = None,
        symbol: str | None = None,
    ) -> dict[str, Any]:
        index = self.load_ast_index()
        results: list[dict[str, Any]] = []
        for record in index["path_records"]:
            if path and record["path"] != _repo_path(path):
                continue
            symbols = record["ast_record"].get("qualified_symbols") or []
            if symbol and symbol not in symbols:
                # also allow simple name match
                simple = {item.rsplit(".", 1)[-1] for item in symbols}
                if symbol not in simple and symbol not in symbols:
                    continue
            results.append(
                {
                    "path": record["path"],
                    "blob_identity": record["ast_record"]["blob_identity"],
                    "source_sha256": record["ast_record"]["source_sha256"],
                    "record_id": record["ast_record"]["record_id"],
                    "qualified_symbols": symbols,
                    "imports": record["ast_record"].get("imports") or [],
                    "calls": record["ast_record"].get("calls") or [],
                }
            )
        return {
            "schema": "code-evidence-ast-query/v1",
            "revision": index.get("revision") or self.revision,
            "index_id": index["index_id"],
            "result_count": len(results),
            "results": results,
        }

    def objective_evidence_links(
        self, goal_id: str | None = None
    ) -> dict[str, Any]:
        graph = self.load_objective_graph()
        body = graph["graph"]
        nodes = body["evidence_nodes"]
        edges = body["evidence_edges"]
        if goal_id:
            gid = _text(goal_id)
            edges = [edge for edge in edges if edge.get("from") == gid]
            linked = {edge.get("to") for edge in edges}
            nodes = [
                node
                for node in nodes
                if node.get("id") in linked or node.get("goal_id") == gid
            ]
        return {
            "schema": "code-evidence-objective-evidence-query/v1",
            "revision": graph.get("revision") or self.revision,
            "goal_id": goal_id,
            "evidence_nodes": nodes,
            "evidence_edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
        }

    def apply_incremental(
        self,
        *,
        family: str = "code_evidence",
        upsert_nodes: Sequence[Mapping[str, Any]] = (),
        upsert_edges: Sequence[Mapping[str, Any]] = (),
        remove_node_ids: Sequence[str] = (),
        remove_edge_ids: Sequence[str] = (),
        revision: str | None = None,
    ) -> dict[str, Any]:
        fam = _text(family)
        if fam in {"code_evidence", GRAPH_KIND_CODE_EVIDENCE}:
            base = self.working_code_evidence_graph()
            update = apply_incremental_update(
                base,
                graph_family="code_evidence",
                upsert_nodes=upsert_nodes,
                upsert_edges=upsert_edges,
                remove_node_ids=remove_node_ids,
                remove_edge_ids=remove_edge_ids,
                revision=revision or self.revision,
                allow_unknown_kinds=self.allow_unknown_kinds,
            )
            self._working["code_evidence"] = update["graph"]
            return update
        if fam in {"semantic", "semantic_dependency", GRAPH_KIND_SEMANTIC}:
            base = self.working_semantic_graph()
            update = apply_incremental_update(
                base,
                graph_family="semantic",
                upsert_nodes=upsert_nodes,
                upsert_edges=upsert_edges,
                remove_node_ids=remove_node_ids,
                remove_edge_ids=remove_edge_ids,
                revision=revision or self.revision,
                allow_unknown_kinds=self.allow_unknown_kinds,
            )
            self._working["semantic"] = update["graph"]
            return update
        raise CodeEvidenceAdapterError(
            f"incremental updates unsupported for family {fam!r}"
        )

    def unknown_optional_kinds(self) -> dict[str, Any]:
        evidence = self.load_code_evidence_graph()
        semantic = self.load_semantic_dependency_graph()
        return {
            "schema": "code-evidence-unknown-kinds-report/v1",
            "revision": self.revision,
            "code_evidence": {
                "node_kinds": evidence["unknown_optional_node_kinds"],
                "edge_kinds": evidence["unknown_optional_edge_kinds"],
            },
            "semantic_dependency": {
                "node_kinds": semantic["unknown_optional_node_kinds"],
                "edge_kinds": semantic["unknown_optional_edge_kinds"],
            },
        }


# ---------------------------------------------------------------------------
# Tiny fixture builder
# ---------------------------------------------------------------------------


def _write_json(path: Path, payload: Mapping[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_tiny_fixture_bundle(root: Path) -> Path:
    """Materialize a tiny multi-graph supervisor-shaped fixture bundle.

    Includes known kinds plus one unknown optional node/edge kind per graph
    family so schema-extensibility is exercised by the integration suite.
    """

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    revision = LOCAL_FIXTURE_REVISION
    tree_id = "tree-" + "a" * 40
    program = "knowledge_graphs_production_hardening"

    # --- Code evidence graph ------------------------------------------------
    def ce_node(
        kind: str,
        record_key: str,
        provenance: str,
        **fields: Any,
    ) -> dict[str, Any]:
        payload = {
            "schema": CODE_EVIDENCE_NODE_SCHEMA,
            "kind": kind,
            "record_key": record_key,
            "provenance": provenance,
            "task_id": fields.get("task_id", ""),
            "tree_id": fields.get("tree_id", ""),
            "symbol": fields.get("symbol", ""),
            "obligation_id": fields.get("obligation_id", ""),
            "assurance": fields.get("assurance", ""),
            "freshness": fields.get("freshness", "current"),
            "record": fields.get("record") or {"key": record_key},
            "revision": revision,
        }
        return normalize_code_evidence_node(
            payload, allow_unknown_kinds=True
        )

    nodes_raw = [
        ce_node("task", "task:KGP-027", "task", task_id="KGP-027", tree_id=tree_id),
        ce_node("tree", f"tree:{tree_id}", "ast", tree_id=tree_id),
        ce_node(
            "symbol",
            "symbol:pkg.mod.helper",
            "ast",
            task_id="KGP-027",
            tree_id=tree_id,
            symbol="pkg.mod.helper",
        ),
        ce_node(
            "symbol",
            "symbol:pkg.mod.caller",
            "ast",
            task_id="KGP-027",
            tree_id=tree_id,
            symbol="pkg.mod.caller",
        ),
        ce_node(
            "ast_scope",
            "ast:pkg/mod.py:helper",
            "ast",
            symbol="pkg.mod.helper",
            tree_id=tree_id,
        ),
        ce_node(
            "obligation",
            "obl:KGP-027-proof",
            "proof",
            task_id="KGP-027",
            obligation_id="obl-kgp-027",
        ),
        ce_node(
            "proof",
            "proof:KGP-027",
            "proof",
            task_id="KGP-027",
            obligation_id="obl-kgp-027",
            assurance="proved",
        ),
        ce_node(
            "validation",
            "val:test_code_evidence",
            "validation",
            task_id="KGP-027",
            assurance="passed",
        ),
        ce_node(
            "merge",
            "merge:KGP-027",
            "merge",
            task_id="KGP-027",
            tree_id=tree_id,
        ),
        ce_node(
            "evidence",
            "evidence:pytest-receipt",
            "validation",
            task_id="KGP-027",
        ),
        ce_node(
            "enrichment",
            "enr:related-note",
            "graphrag",
            record={"note": "non-authoritative annotation"},
        ),
        # Unknown optional extension kind
        ce_node(
            "coverage_span",
            "cov:pkg.mod.helper",
            "validation",
            task_id="KGP-027",
            symbol="pkg.mod.helper",
            record={"lines": [10, 40]},
        ),
    ]
    by_key = {n["record_key"]: n for n in nodes_raw}

    def ce_edge(
        source_key: str,
        target_key: str,
        kind: str,
        provenance: str,
        *,
        meta: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "schema": CODE_EVIDENCE_EDGE_SCHEMA,
            "source": by_key[source_key]["node_id"],
            "target": by_key[target_key]["node_id"],
            "kind": kind,
            "provenance": provenance,
            "provenance_record_id": f"prov:{kind}:{source_key}:{target_key}",
            "metadata": dict(meta or {}),
            "revision": revision,
        }
        return normalize_code_evidence_edge(payload, allow_unknown_kinds=True)

    edges_raw = [
        ce_edge("task:KGP-027", f"tree:{tree_id}", "targets_tree", "task"),
        ce_edge(
            "ast:pkg/mod.py:helper",
            "symbol:pkg.mod.helper",
            "defines_symbol",
            "ast",
        ),
        ce_edge(
            "task:KGP-027",
            "obl:KGP-027-proof",
            "has_obligation",
            "proof",
        ),
        ce_edge("proof:KGP-027", "obl:KGP-027-proof", "proves", "proof"),
        ce_edge(
            "proof:KGP-027",
            "symbol:pkg.mod.helper",
            "covers",
            "proof",
        ),
        ce_edge(
            "val:test_code_evidence",
            "task:KGP-027",
            "validates",
            "validation",
        ),
        ce_edge("merge:KGP-027", "task:KGP-027", "merged", "merge"),
        ce_edge(
            "val:test_code_evidence",
            "task:KGP-027",
            "completes",
            "validation",
        ),
        ce_edge(
            "enr:related-note",
            "symbol:pkg.mod.helper",
            "related_to",
            "graphrag",
        ),
        # Unknown optional extension edge kind (non-authoritative)
        ce_edge(
            "cov:pkg.mod.helper",
            "symbol:pkg.mod.helper",
            "covers_lines",
            "validation",
            meta={"start": 10, "end": 40},
        ),
    ]
    public_nodes = [
        {k: v for k, v in n.items() if k not in {"kind_meta"}}
        for n in nodes_raw
    ]
    public_edges = [
        {k: v for k, v in e.items() if k not in {"kind_meta"}}
        for e in edges_raw
    ]
    code_evidence = normalize_code_evidence_graph(
        {
            "schema": CODE_EVIDENCE_GRAPH_SCHEMA,
            "nodes": public_nodes,
            "edges": public_edges,
            "revision": revision,
        },
        allow_unknown_kinds=True,
        revision=revision,
    )
    code_evidence_payload = {
        "schema": CODE_EVIDENCE_GRAPH_SCHEMA,
        "graph_id": code_evidence["graph_id"],
        "node_count": code_evidence["node_count"],
        "edge_count": code_evidence["edge_count"],
        "revision": revision,
        "nodes": code_evidence["public_nodes"],
        "edges": code_evidence["public_edges"],
    }

    # --- Impact index -------------------------------------------------------
    impact_payload = {
        "schema": CODE_IMPACT_INDEX_SCHEMA,
        "repository_tree_id": tree_id,
        "index_version": "code-impact-index-v1",
        "symbol_paths": {
            "pkg.mod.helper": "pkg/mod.py",
            "pkg.mod.caller": "pkg/mod.py",
            "pkg.other.use": "pkg/other.py",
        },
        "symbol_dependencies": {
            "pkg.mod.caller": ["pkg.mod.helper"],
            "pkg.other.use": ["pkg.mod.helper"],
        },
        "path_dependencies": {
            "pkg/other.py": ["pkg/mod.py"],
            "tests/test_mod.py": ["pkg/mod.py"],
        },
        "validation_targets": {
            "test_code_evidence": ["pkg.mod.helper", "pkg/mod.py"],
            "test_other": ["pkg.other.use", "pkg/other.py"],
        },
        "revision": revision,
    }
    impact = normalize_impact_index(impact_payload, revision=revision)
    impact_payload["index_id"] = impact["index_id"]

    # --- Semantic dependency graph ------------------------------------------
    def sem_node(
        node_id: str,
        kind: str,
        *,
        provenance: str = "decision",
        trust: str = "trusted",
        authority: str = "authoritative",
        version: str = "v1",
        record: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "schema": SEMANTIC_DEPENDENCY_NODE_SCHEMA,
            "node_id": node_id,
            "kind": kind,
            "root_id": "decision:KGP-027",
            "source_root_id": "decision:KGP-027",
            "provenance": provenance,
            "provenance_id": f"prov:{node_id}",
            "trust": trust,
            "authority": authority,
            "version": version,
            "record": dict(record or {"id": node_id}),
            "revision": revision,
        }
        return normalize_semantic_node(payload, allow_unknown_kinds=True)

    s_nodes = [
        sem_node("decision:KGP-027", "decision", provenance="decision"),
        sem_node(
            "obligation:impl",
            "obligation",
            provenance="proof",
            authority="verified_input",
        ),
        sem_node(
            "proof:receipt-1",
            "proof",
            provenance="proof",
            authority="verified_input",
        ),
        sem_node(
            "file:pkg/mod.py",
            "file",
            provenance="ast",
            authority="descriptive_input",
        ),
        sem_node(
            "symbol:pkg.mod.helper",
            "symbol",
            provenance="ast",
            authority="descriptive_input",
        ),
        sem_node(
            "validation:pytest",
            "validation",
            provenance="validation",
            authority="verified_input",
        ),
        # Unknown optional extension kind
        sem_node(
            "policy_hint:lane",
            "scheduling_hint",
            provenance="planner",
            trust="reviewed",
            authority="context_only",
            record={"lane": "code-evidence-corpus"},
        ),
    ]
    s_by = {n["node_id"]: n for n in s_nodes}

    def sem_edge(
        source: str,
        target: str,
        kind: str,
        *,
        provenance: str,
        trust: str = "trusted",
        authority: str = "authoritative",
        mandatory: bool = True,
        version: str = "v1",
    ) -> dict[str, Any]:
        payload = {
            "schema": SEMANTIC_DEPENDENCY_EDGE_SCHEMA,
            "source": source,
            "target": target,
            "kind": kind,
            "root_id": "decision:KGP-027",
            "source_root_id": "decision:KGP-027",
            "provenance": provenance,
            "provenance_id": f"prov-edge:{source}:{kind}:{target}",
            "trust": trust,
            "authority": authority,
            "version": version,
            "mandatory": mandatory,
            "record": {},
            "revision": revision,
        }
        return normalize_semantic_edge(payload, allow_unknown_kinds=True)

    s_edges = [
        sem_edge(
            "decision:KGP-027",
            "obligation:impl",
            "requires",
            provenance="decision",
        ),
        sem_edge(
            "obligation:impl",
            "proof:receipt-1",
            "proven_by",
            provenance="proof",
            authority="verified_input",
        ),
        sem_edge(
            "decision:KGP-027",
            "file:pkg/mod.py",
            "depends_on",
            provenance="ast",
            authority="descriptive_input",
        ),
        sem_edge(
            "file:pkg/mod.py",
            "symbol:pkg.mod.helper",
            "depends_on",
            provenance="ast",
            authority="descriptive_input",
        ),
        sem_edge(
            "decision:KGP-027",
            "validation:pytest",
            "requires",
            provenance="validation",
            authority="verified_input",
        ),
        # Unknown optional extension edge (non-mandatory by authority rules
        # when untrusted; here trusted but unknown → non-authoritative)
        sem_edge(
            "decision:KGP-027",
            "policy_hint:lane",
            "hints_schedule",
            provenance="planner",
            trust="reviewed",
            authority="context_only",
            mandatory=False,
        ),
    ]
    semantic = normalize_semantic_dependency_graph(
        {
            "schema": SEMANTIC_DEPENDENCY_GRAPH_SCHEMA,
            "root_id": "decision:KGP-027",
            "nodes": [
                {k: v for k, v in n.items() if k not in {"kind_meta"}}
                for n in s_nodes
            ],
            "edges": [
                {k: v for k, v in e.items() if k not in {"kind_meta"}}
                for e in s_edges
            ],
            "revision": revision,
        },
        allow_unknown_kinds=True,
        revision=revision,
    )
    semantic_payload = {
        "schema": SEMANTIC_DEPENDENCY_GRAPH_SCHEMA,
        "graph_id": semantic["graph_id"],
        "root_id": semantic["root_id"],
        "node_count": semantic["node_count"],
        "edge_count": semantic["edge_count"],
        "revision": revision,
        "nodes": [
            {k: v for k, v in n.items() if k not in {"kind_meta", "revision"}}
            for n in semantic["nodes"]
        ],
        "edges": [
            {k: v for k, v in e.items() if k not in {"kind_meta", "revision"}}
            for e in semantic["edges"]
        ],
    }

    # --- AST index ----------------------------------------------------------
    helper_blob = normalize_ast_blob_record(
        {
            "blob_identity": "sha256:" + "b" * 64,
            "source_sha256": "sha256:" + "b" * 64,
            "qualified_symbols": ["pkg.mod.helper", "pkg.mod.caller"],
            "imports": ["json", "hashlib"],
            "calls": ["normalize_code_evidence_graph"],
            "interfaces": [],
            "symbol_hashes": {
                "pkg.mod.helper": "sha256:" + "c" * 64,
                "pkg.mod.caller": "sha256:" + "d" * 64,
            },
            "symbol_lines": {
                "pkg.mod.helper": [10, 40],
                "pkg.mod.caller": [42, 60],
            },
            "language": "python",
            "record_schema_version": 1,
        }
    )
    other_blob = normalize_ast_blob_record(
        {
            "blob_identity": "sha256:" + "e" * 64,
            "source_sha256": "sha256:" + "e" * 64,
            "qualified_symbols": ["pkg.other.use"],
            "imports": ["pkg.mod"],
            "calls": ["helper"],
            "language": "python",
            "record_schema_version": 1,
        }
    )
    ast_payload = {
        "schema": ANALYSIS_AST_INDEX_SCHEMA,
        "schema_version": 1,
        "path_records": [
            {"path": "pkg/mod.py", "ast_record": helper_blob},
            {"path": "pkg/other.py", "ast_record": other_blob},
        ],
        "invalidations": [],
        "stats": {
            "cache_hits": 1,
            "cache_misses": 1,
            "reused_records": 0,
            "invalidated_records": 0,
        },
        "revision": revision,
    }
    ast_index = normalize_ast_index(ast_payload, revision=revision)
    ast_payload["index_id"] = ast_index["index_id"]

    # --- Conflict graph -----------------------------------------------------
    conflict_payload = {
        "schema": CONFLICT_GRAPH_SCHEMA,
        "revision": revision,
        "surfaces": {
            "task-cid-027": {
                "task_id": "KGP-027",
                "task_cid": "task-cid-027",
                "goal_id": "KGP-G080",
                "predicted_paths": [
                    "ipfs_datasets_py/knowledge_graphs/adapters/code_evidence.py",
                    "tests/integration/knowledge_graphs/corpora/test_code_evidence.py",
                ],
                "predicted_symbols": [
                    "CodeEvidenceCorpusAdapter",
                    "build_tiny_fixture_bundle",
                ],
                "files": [
                    "ipfs_datasets_py/knowledge_graphs/adapters/code_evidence.py"
                ],
                "changed_paths": [
                    "ipfs_datasets_py/knowledge_graphs/adapters/code_evidence.py",
                    "tests/integration/knowledge_graphs/corpora/test_code_evidence.py",
                ],
                "ast_symbols": ["CodeEvidenceCorpusAdapter"],
                "dependencies": ["KGP-002", "KGP-015"],
                "conflicts": ["KGP-028"],
                "evidence_subset": ["pytest:test_code_evidence"],
                "validation_commands": [
                    "python -m pytest -q tests/integration/knowledge_graphs/corpora/test_code_evidence.py"
                ],
            },
            "task-cid-028": {
                "task_id": "KGP-028",
                "task_cid": "task-cid-028",
                "goal_id": "KGP-G080",
                "predicted_paths": [
                    "ipfs_datasets_py/knowledge_graphs/migration/verifier.py"
                ],
                "predicted_symbols": ["DifferentialVerifier"],
                "files": [
                    "ipfs_datasets_py/knowledge_graphs/migration/verifier.py"
                ],
                "changed_paths": [
                    "ipfs_datasets_py/knowledge_graphs/migration/verifier.py"
                ],
                "ast_symbols": ["DifferentialVerifier"],
                "dependencies": ["KGP-027"],
                "conflicts": ["KGP-027"],
                "evidence_subset": [],
            },
            "task-cid-024": {
                "task_id": "KGP-024",
                "task_cid": "task-cid-024",
                "goal_id": "KGP-G080",
                "predicted_paths": [
                    "ipfs_datasets_py/knowledge_graphs/adapters/cvefixes.py"
                ],
                "files": [
                    "ipfs_datasets_py/knowledge_graphs/adapters/cvefixes.py"
                ],
                "changed_paths": [
                    "ipfs_datasets_py/knowledge_graphs/adapters/cvefixes.py"
                ],
                "dependencies": [],
                "conflicts": [],
            },
        },
        "edges": [
            {
                "left_task_cid": "task-cid-027",
                "right_task_cid": "task-cid-028",
                "weight": 1.0,
                "reasons": ["shared goal track", "dependency order"],
                "overlaps": {
                    "goals": ["KGP-G080"],
                },
                "predicted_weight": 0.8,
                "observed_weight": 0.0,
                "explicitly_allowed": False,
            },
            {
                "left_task_cid": "task-cid-027",
                "right_task_cid": "task-cid-024",
                "weight": 0.0,
                "reasons": ["disjoint adapters"],
                "overlaps": {},
                "explicitly_allowed": True,
            },
        ],
        "assignments": [
            {
                "task_cid": "task-cid-027",
                "task_id": "KGP-027",
                "lane": 0,
                "color": 0,
                "explanation": "independent of KGP-024",
            },
            {
                "task_cid": "task-cid-024",
                "task_id": "KGP-024",
                "lane": 0,
                "color": 0,
                "explanation": "same lane as non-conflicting peer",
            },
            {
                "task_cid": "task-cid-028",
                "task_id": "KGP-028",
                "lane": 1,
                "color": 1,
                "explanation": "blocked by KGP-027",
            },
        ],
        "decisions": [
            {
                "left_task_cid": "task-cid-027",
                "right_task_cid": "task-cid-028",
                "action": "serialize",
                "explanation": "dependency edge",
                "weight": 1.0,
                "reasons": ["depends_on"],
            }
        ],
        "lanes": {
            "0": ["task-cid-024", "task-cid-027"],
            "1": ["task-cid-028"],
        },
        "history": {"observed_evidence_ids": []},
    }

    # --- Objective graph ----------------------------------------------------
    objective_payload = {
        "schema": OBJECTIVE_GRAPH_SCHEMA,
        "generated_at": "2026-07-30T00:00:00+00:00",
        "objective_path": "docs/architecture/knowledge_graphs_production_hardening.objectives.md",
        "goal_count": 3,
        "active_goal_count": 2,
        "completed_goal_count": 0,
        "revision": revision,
        "goals": [
            {
                "goal_id": "KGP-G000",
                "title": "Production-grade multi-graph knowledge graph platform",
                "status": "active",
                "track": "knowledge-graphs",
                "parents": [],
                "evidence": [
                    "docs/architecture/KNOWLEDGE_GRAPHS_PRODUCTION_HARDENING_PLAN_2026_07_29.md"
                ],
                "bundle": "knowledge-graphs/root",
                "fib_priority": 1,
            },
            {
                "goal_id": "KGP-G080",
                "title": "Corpus adapters and differential verification",
                "status": "active",
                "track": "compatibility",
                "parents": ["KGP-G000"],
                "evidence": [],
                "bundle": "knowledge-graphs/corpora",
                "fib_priority": 5,
            },
            {
                "goal_id": "KGP-G081",
                "title": "Code evidence adapter complete",
                "status": "active",
                "track": "compatibility",
                "parents": ["KGP-G080"],
                "evidence": [
                    "tests/integration/knowledge_graphs/corpora/test_code_evidence.py"
                ],
                "bundle": "knowledge-graphs/corpora/code-evidence",
                "fib_priority": 8,
            },
        ],
        "graph": {
            "nodes": ["KGP-G000", "KGP-G080", "KGP-G081"],
            "edges": [
                {"from": "KGP-G000", "to": "KGP-G080", "kind": "refines"},
                {"from": "KGP-G080", "to": "KGP-G081", "kind": "refines"},
            ],
            "evidence_nodes": [
                {
                    "id": "evidence:plan",
                    "goal_id": "KGP-G000",
                    "acceptance_criterion": (
                        "docs/architecture/"
                        "KNOWLEDGE_GRAPHS_PRODUCTION_HARDENING_PLAN_2026_07_29.md"
                    ),
                },
                {
                    "id": "evidence:pytest-code-evidence",
                    "goal_id": "KGP-G081",
                    "acceptance_criterion": (
                        "tests/integration/knowledge_graphs/corpora/"
                        "test_code_evidence.py"
                    ),
                },
            ],
            "evidence_edges": [
                {
                    "from": "KGP-G000",
                    "to": "evidence:plan",
                    "kind": "requires_evidence",
                },
                {
                    "from": "KGP-G081",
                    "to": "evidence:pytest-code-evidence",
                    "kind": "requires_evidence",
                },
            ],
            "node_details": {
                "KGP-G000": {
                    "goal_id": "KGP-G000",
                    "status": "active",
                    "schedulable": True,
                    "terminal": False,
                    "parents": [],
                    "required_evidence": [
                        "docs/architecture/"
                        "KNOWLEDGE_GRAPHS_PRODUCTION_HARDENING_PLAN_2026_07_29.md"
                    ],
                },
                "KGP-G080": {
                    "goal_id": "KGP-G080",
                    "status": "active",
                    "schedulable": True,
                    "terminal": False,
                    "parents": ["KGP-G000"],
                    "required_evidence": [],
                },
                "KGP-G081": {
                    "goal_id": "KGP-G081",
                    "status": "active",
                    "schedulable": True,
                    "terminal": False,
                    "parents": ["KGP-G080"],
                    "required_evidence": [
                        "tests/integration/knowledge_graphs/corpora/"
                        "test_code_evidence.py"
                    ],
                },
            },
            "children": {
                "KGP-G000": ["KGP-G080"],
                "KGP-G080": ["KGP-G081"],
            },
            "depths": {"KGP-G000": 0, "KGP-G080": 1, "KGP-G081": 2},
            "roots": ["KGP-G000"],
            "lifecycle": {},
            "schedulable_goal_ids": ["KGP-G000", "KGP-G080", "KGP-G081"],
            "terminal_goal_ids": [],
            "state_counts": {"active": 3},
        },
        "thought_graph": {
            "schema": OBJECTIVE_THOUGHT_GRAPH_SCHEMA,
            "node_count": 1,
            "edge_count": 1,
            "nodes": [
                {
                    "id": "code_surface:adapters",
                    "goal_id": "KGP-G081",
                    "kind": "code_surface",
                    "path": "ipfs_datasets_py/knowledge_graphs/adapters",
                    "thought": "Implement code_evidence adapter",
                }
            ],
            "edges": [
                {
                    "from": "KGP-G081",
                    "to": "code_surface:adapters",
                    "kind": "thinks_about",
                }
            ],
        },
        "heap_schedule": [
            {
                "goal_id": "KGP-G081",
                "title": "Code evidence adapter complete",
                "priority": 8,
                "status": "active",
            }
        ],
    }

    # --- Write artifacts ----------------------------------------------------
    checksums: dict[str, str] = {}
    files = {
        "objective_graph": objective_payload,
        "semantic_dependency_graph": semantic_payload,
        "analysis_ast_index": ast_payload,
        "conflict_graph": conflict_payload,
        "code_evidence_graph": code_evidence_payload,
        "code_impact_index": impact_payload,
    }
    for name, payload in files.items():
        rel = BUNDLE_ARTIFACTS[name]
        checksums[name] = _write_json(root / rel, payload)

    manifest = {
        "schema": BUNDLE_MANIFEST_SCHEMA,
        "revision": revision,
        "program": program,
        "graph_kinds": [
            GRAPH_KIND_OBJECTIVE,
            GRAPH_KIND_SEMANTIC,
            GRAPH_KIND_AST,
            GRAPH_KIND_CONFLICT,
            GRAPH_KIND_CODE_EVIDENCE,
            GRAPH_KIND_IMPACT,
        ],
        "artifacts": {name: BUNDLE_ARTIFACTS[name] for name in files},
        "artifact_checksums": checksums,
        "provenance": {
            "authoritative_owner": "ipfs_accelerate_py",
            "producer_boundary": "projection-only",
            "source": "kgp-027-tiny-fixture",
            "tree_id": tree_id,
            "inventory_task": "KGP-002",
            "adapter_task": "KGP-027",
        },
        "counts": {
            "code_evidence_nodes": code_evidence["node_count"],
            "code_evidence_edges": code_evidence["edge_count"],
            "semantic_nodes": semantic["node_count"],
            "semantic_edges": semantic["edge_count"],
            "ast_paths": ast_index["path_count"],
            "conflict_surfaces": 3,
            "objective_goals": 3,
            "impact_symbols": 3,
        },
    }
    _write_json(root / BUNDLE_ARTIFACTS["manifest"], manifest)
    return root


def open_bundle_reader(
    bundle_root: Path | str | None = None,
    **kwargs: Any,
) -> CodeEvidenceCorpusAdapter:
    root = Path(bundle_root) if bundle_root is not None else discover_bundle_root()
    if root is None:
        raise CodeEvidenceAdapterError(
            "no bundle root provided; set CODE_EVIDENCE_BUNDLE_ROOT "
            "or pass bundle_root="
        )
    return CodeEvidenceCorpusAdapter(root, **kwargs)


__all__ = [
    "ANALYSIS_AST_INDEX_SCHEMA",
    "BUNDLE_ARTIFACTS",
    "BUNDLE_MANIFEST_SCHEMA",
    "CODE_EVIDENCE_EDGE_SCHEMA",
    "CODE_EVIDENCE_GRAPH_SCHEMA",
    "CODE_EVIDENCE_NODE_SCHEMA",
    "CODE_IMPACT_INDEX_SCHEMA",
    "CODE_IMPACT_RESULT_SCHEMA",
    "CONFLICT_GRAPH_SCHEMA",
    "CodeEvidenceAdapterError",
    "CodeEvidenceCorpusAdapter",
    "ENV_BUNDLE_ROOT",
    "GRAPH_KIND_AST",
    "GRAPH_KIND_CODE_EVIDENCE",
    "GRAPH_KIND_CONFLICT",
    "GRAPH_KIND_IMPACT",
    "GRAPH_KIND_OBJECTIVE",
    "GRAPH_KIND_SEMANTIC",
    "LOCAL_FIXTURE_REVISION",
    "OBJECTIVE_GRAPH_SCHEMA",
    "SEMANTIC_DEPENDENCY_GRAPH_SCHEMA",
    "VALIDATION_RECEIPT_SCHEMA",
    "apply_incremental_update",
    "build_tiny_fixture_bundle",
    "canonical_json",
    "classify_kind",
    "content_identity",
    "dependency_closure",
    "discover_bundle_root",
    "discover_objective_graph_path",
    "impact_from_index",
    "mandatory_semantic_closure",
    "normalize_ast_index",
    "normalize_code_evidence_graph",
    "normalize_conflict_graph",
    "normalize_impact_index",
    "normalize_objective_graph",
    "normalize_semantic_dependency_graph",
    "open_bundle_reader",
    "provenance_trace",
    "validate_bundle_manifest",
]
