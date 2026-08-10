"""DQP-039 release-plane adapter for datasets code-evidence consumers (DQK-034).

Adapts knowledge-graph / code-evidence consumers onto the revision-bound AST,
dependency, conflict, and evidence interfaces delivered by the supervisor
DuckDB/Quack control plane without reimplementing supervisor stores.

Design guarantees
-----------------
* **Exact DQP identity** — every adapter instance is pinned to a verified
  ``DuckDBControlPlaneReleaseReceipt@1`` release/tree/schema triple (plus store
  generation and Quack profile). Mismatched pins fail closed.
* **No whole-artifact JSON load** — consumers ingest and query row/record
  surfaces (AST catalog projections, impact edges, evidence nodes/edges,
  conflict surfaces). Loading a multi-graph bundle JSON artifact is refused.
* **Schema compatibility** — datasets pins for supervisor AST/evidence/conflict
  schemas and the DuckDB AST store catalog are asserted equal; incompatible
  second schemas are rejected.

This module reuses:

* :mod:`ipfs_datasets_py.logic.software_contracts.duckdb_ast_store` (DQK-031)
* :mod:`ipfs_datasets_py.logic.software_contracts.duckdb_impact` (DQK-033)
* Supervisor schema constants from
  :mod:`ipfs_datasets_py.knowledge_graphs.adapters.code_evidence`

Importing this module performs no filesystem, network, or DuckDB I/O.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final

from ipfs_datasets_py.knowledge_graphs.adapters import code_evidence as _ce
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
    ASTS_CATALOG_TABLES,
    DUCKDB_AST_STORE_INTERFACE,
    DUCKDB_AST_STORE_SCHEMA_VERSION,
    SUPERVISOR_BLOB_SUMMARY_SCHEMA,
    ASTCatalogProjection,
    DuckDBASTStore,
    DuckDBASTStoreError,
    ast_store_schema_descriptor,
    build_duckdb_ast_store,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_impact import (
    DUCKDB_IMPACT_SCHEMA,
    ImpactBudget,
    ImpactGraph,
    ImpactQueryError,
    ImpactResult,
    closure as impact_closure,
)
from ipfs_datasets_py.logic.software_contracts.schema_versions import (
    AST_IR_SCHEMA_VERSION,
)

# ---------------------------------------------------------------------------
# Interface / schema pins (datasets consumer surface)
# ---------------------------------------------------------------------------

DUCKDB_CODE_EVIDENCE_INTERFACE: Final[str] = "DuckDBCodeEvidenceAdapter@1"
DUCKDB_CODE_EVIDENCE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/knowledge-graphs-adapters-duckdb-code-evidence@1"
)
ADAPTER_SCHEMA_VERSION: Final[int] = 1

# DQP-039 terminal release plane (matches DQK-057 verifier constants).
DQP_PROGRAM_ID: Final[str] = "agent-supervisor-duckdb-quack-control-plane-v1"
DQP_RELEASE_TASK_ID: Final[str] = "DQP-039"
DQP_RELEASE_RECEIPT_INTERFACE: Final[str] = "DuckDBControlPlaneReleaseReceipt@1"
DQP_RELEASE_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_accelerate_py/agent-supervisor/duckdb-control-plane-release-receipt@1"
)
DQP_VERIFICATION_SCHEMA: Final[str] = (
    "ipfs_accelerate_py/agent-supervisor/duckdb-quack-release-verification@1"
)

# Closed supervisor schemas that datasets must remain compatible with.
SUPERVISOR_ANALYSIS_AST_INDEX_SCHEMA: Final[str] = _ce.ANALYSIS_AST_INDEX_SCHEMA
SUPERVISOR_CONFLICT_GRAPH_SCHEMA: Final[str] = _ce.CONFLICT_GRAPH_SCHEMA
SUPERVISOR_CODE_EVIDENCE_GRAPH_SCHEMA: Final[str] = _ce.CODE_EVIDENCE_GRAPH_SCHEMA
SUPERVISOR_CODE_EVIDENCE_NODE_SCHEMA: Final[str] = _ce.CODE_EVIDENCE_NODE_SCHEMA
SUPERVISOR_CODE_EVIDENCE_EDGE_SCHEMA: Final[str] = _ce.CODE_EVIDENCE_EDGE_SCHEMA
SUPERVISOR_CODE_IMPACT_INDEX_SCHEMA: Final[str] = _ce.CODE_IMPACT_INDEX_SCHEMA
SUPERVISOR_CODE_IMPACT_RESULT_SCHEMA: Final[str] = _ce.CODE_IMPACT_RESULT_SCHEMA
SUPERVISOR_SEMANTIC_DEPENDENCY_GRAPH_SCHEMA: Final[str] = (
    _ce.SEMANTIC_DEPENDENCY_GRAPH_SCHEMA
)

_GIT_OID: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_SHA256_DIGEST: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
_STORE_GENERATION: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$"
)

# Identity fields that form the exact DQP release/tree/schema triple.
_IDENTITY_FIELDS: Final[tuple[str, ...]] = (
    "accelerator_commit",
    "accelerator_tree",
    "schema_checksum",
    "store_generation",
    "quack_profile",
)

__all__ = [
    "ADAPTER_SCHEMA_VERSION",
    "DUCKDB_CODE_EVIDENCE_INTERFACE",
    "DUCKDB_CODE_EVIDENCE_SCHEMA",
    "DQPReleaseIdentity",
    "DQP_PROGRAM_ID",
    "DQP_RELEASE_RECEIPT_INTERFACE",
    "DQP_RELEASE_RECEIPT_SCHEMA",
    "DQP_RELEASE_TASK_ID",
    "DQP_VERIFICATION_SCHEMA",
    "DuckDBCodeEvidenceAdapter",
    "DuckDBCodeEvidenceError",
    "IdentityMismatchError",
    "SchemaCompatibilityError",
    "WholeArtifactLoadError",
    "assert_schema_compatible",
    "build_duckdb_code_evidence_adapter",
    "open_duckdb_code_evidence_adapter",
    "schema_compatibility_report",
    "verify_dqp_release_identity",
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DuckDBCodeEvidenceError(ValueError):
    """Raised when the DuckDB code-evidence adapter fails closed."""


class IdentityMismatchError(DuckDBCodeEvidenceError):
    """Raised when the DQP release/tree/schema identity does not match."""


class SchemaCompatibilityError(DuckDBCodeEvidenceError):
    """Raised when datasets and supervisor projection schemas diverge."""


class WholeArtifactLoadError(DuckDBCodeEvidenceError):
    """Raised when a consumer attempts a whole-artifact JSON load."""


# ---------------------------------------------------------------------------
# DQP release identity
# ---------------------------------------------------------------------------


def _require_text(value: Any, field: str) -> str:
    if type(value) is not str or not value:
        raise DuckDBCodeEvidenceError(f"{field} must be a non-empty string")
    if value != value.strip():
        raise DuckDBCodeEvidenceError(
            f"{field} must not contain surrounding whitespace"
        )
    if "\0" in value or "\n" in value or "\r" in value:
        raise DuckDBCodeEvidenceError(f"{field} contains control characters")
    return value


def _require_git_oid(value: Any, field: str) -> str:
    text = _require_text(value, field).lower()
    if not _GIT_OID.fullmatch(text):
        raise DuckDBCodeEvidenceError(
            f"{field} must be a 40-character lowercase hex Git OID"
        )
    return text


def _require_schema_checksum(value: Any, field: str = "schema_checksum") -> str:
    text = _require_text(value, field).lower()
    if not _SHA256_DIGEST.fullmatch(text):
        raise DuckDBCodeEvidenceError(
            f"{field} must be a sha256:<64-hex> digest"
        )
    return text


@dataclass(frozen=True, slots=True)
class DQPReleaseIdentity:
    """Exact DQP-039 release / tree / schema identity pin.

    The triple ``(accelerator_commit, accelerator_tree, schema_checksum)`` is
    the primary identity. ``store_generation`` and ``quack_profile`` are also
    required so consumers cannot silently accept a mismatched Quack plane.
    """

    accelerator_commit: str
    accelerator_tree: str
    schema_checksum: str
    store_generation: str
    quack_profile: str
    program_id: str = DQP_PROGRAM_ID
    task_id: str = DQP_RELEASE_TASK_ID
    interface: str = DQP_RELEASE_RECEIPT_INTERFACE
    release_receipt_cid: str = ""
    decision_cid: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "accelerator_commit",
            _require_git_oid(self.accelerator_commit, "accelerator_commit"),
        )
        object.__setattr__(
            self,
            "accelerator_tree",
            _require_git_oid(self.accelerator_tree, "accelerator_tree"),
        )
        object.__setattr__(
            self,
            "schema_checksum",
            _require_schema_checksum(self.schema_checksum),
        )
        generation = _require_text(self.store_generation, "store_generation")
        if not _STORE_GENERATION.fullmatch(generation):
            raise DuckDBCodeEvidenceError("store_generation has invalid form")
        object.__setattr__(self, "store_generation", generation)
        object.__setattr__(
            self, "quack_profile", _require_text(self.quack_profile, "quack_profile")
        )
        object.__setattr__(
            self, "program_id", _require_text(self.program_id, "program_id")
        )
        object.__setattr__(self, "task_id", _require_text(self.task_id, "task_id"))
        object.__setattr__(
            self, "interface", _require_text(self.interface, "interface")
        )
        if self.program_id != DQP_PROGRAM_ID:
            raise DuckDBCodeEvidenceError(
                f"program_id must be {DQP_PROGRAM_ID!r}"
            )
        if self.task_id != DQP_RELEASE_TASK_ID:
            raise DuckDBCodeEvidenceError(
                f"task_id must be {DQP_RELEASE_TASK_ID!r}"
            )
        if self.interface != DQP_RELEASE_RECEIPT_INTERFACE:
            raise DuckDBCodeEvidenceError(
                f"interface must be {DQP_RELEASE_RECEIPT_INTERFACE!r}"
            )
        if self.release_receipt_cid:
            object.__setattr__(
                self,
                "release_receipt_cid",
                _require_text(self.release_receipt_cid, "release_receipt_cid"),
            )
        if self.decision_cid:
            object.__setattr__(
                self,
                "decision_cid",
                _require_text(self.decision_cid, "decision_cid"),
            )

    @property
    def triple(self) -> tuple[str, str, str]:
        """Primary release/tree/schema identity triple."""

        return (
            self.accelerator_commit,
            self.accelerator_tree,
            self.schema_checksum,
        )

    def matches(self, other: "DQPReleaseIdentity" | Mapping[str, Any]) -> bool:
        """Return True when the primary release/tree/schema triple agrees."""

        peer = (
            other
            if isinstance(other, DQPReleaseIdentity)
            else verify_dqp_release_identity(other)
        )
        return self.triple == peer.triple

    def matches_full(self, other: "DQPReleaseIdentity" | Mapping[str, Any]) -> bool:
        """Return True when the full identity pin (including store/profile) agrees."""

        peer = (
            other
            if isinstance(other, DQPReleaseIdentity)
            else verify_dqp_release_identity(other)
        )
        return (
            self.matches(peer)
            and self.store_generation == peer.store_generation
            and self.quack_profile == peer.quack_profile
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "program_id": self.program_id,
            "task_id": self.task_id,
            "interface": self.interface,
            "accelerator_commit": self.accelerator_commit,
            "accelerator_tree": self.accelerator_tree,
            "schema_checksum": self.schema_checksum,
            "store_generation": self.store_generation,
            "quack_profile": self.quack_profile,
        }
        if self.release_receipt_cid:
            payload["release_receipt_cid"] = self.release_receipt_cid
        if self.decision_cid:
            payload["decision_cid"] = self.decision_cid
        return payload


def verify_dqp_release_identity(
    payload: Mapping[str, Any],
    *,
    require_accepted: bool = True,
) -> DQPReleaseIdentity:
    """Verify and extract the exact DQP release/tree/schema identity.

    Accepts either a terminal ``DuckDBControlPlaneReleaseReceipt@1`` body or a
    DQK-057 verification object. Markdown boards and process-status blobs are
    rejected. When *require_accepted* is true, ``accepted`` must be the
    boolean literal ``True``.
    """

    if not isinstance(payload, Mapping):
        raise DuckDBCodeEvidenceError(
            "DQP release identity payload must be a mapping"
        )
    # Reject process-status / markdown smuggling shapes.
    for marker in (
        "master_alive",
        "master_pid",
        "release_status",
        "lane_status",
        "board_path",
    ):
        if marker in payload:
            raise DuckDBCodeEvidenceError(
                "process status / markdown board cannot satisfy DQP identity"
            )

    schema = payload.get("schema")
    if schema not in (
        None,
        "",
        DQP_RELEASE_RECEIPT_SCHEMA,
        DQP_VERIFICATION_SCHEMA,
    ):
        raise DuckDBCodeEvidenceError(
            f"unsupported DQP identity schema {schema!r}"
        )

    if require_accepted and "accepted" in payload:
        if payload.get("accepted") is not True:
            raise DuckDBCodeEvidenceError(
                "DQP release identity is not accepted (accepted must be true)"
            )

    interface = payload.get("interface") or DQP_RELEASE_RECEIPT_INTERFACE
    task_id = payload.get("task_id") or DQP_RELEASE_TASK_ID
    program_id = payload.get("program_id") or DQP_PROGRAM_ID

    # Nested cutover (joined receipt) must agree on the identity triple when present.
    cutover = payload.get("cutover")
    if isinstance(cutover, Mapping):
        for field_name in (
            "accelerator_commit",
            "accelerator_tree",
            "schema_checksum",
            "store_generation",
            "quack_profile",
        ):
            claimed = cutover.get(field_name)
            outer = payload.get(field_name)
            if claimed is not None and outer is not None and claimed != outer:
                raise IdentityMismatchError(
                    f"cutover {field_name} does not match release identity"
                )

    return DQPReleaseIdentity(
        accelerator_commit=_require_git_oid(
            payload.get("accelerator_commit"), "accelerator_commit"
        ),
        accelerator_tree=_require_git_oid(
            payload.get("accelerator_tree"), "accelerator_tree"
        ),
        schema_checksum=_require_schema_checksum(payload.get("schema_checksum")),
        store_generation=_require_text(
            payload.get("store_generation"), "store_generation"
        ),
        quack_profile=_require_text(payload.get("quack_profile"), "quack_profile"),
        program_id=_require_text(program_id, "program_id"),
        task_id=_require_text(task_id, "task_id"),
        interface=_require_text(interface, "interface"),
        release_receipt_cid=str(
            payload.get("release_receipt_cid")
            or payload.get("receipt_cid")
            or ""
        ),
        decision_cid=str(payload.get("decision_cid") or ""),
    )


# ---------------------------------------------------------------------------
# Schema compatibility
# ---------------------------------------------------------------------------


def schema_compatibility_report() -> dict[str, Any]:
    """Report datasets ↔ supervisor schema pins used by this adapter.

    Compatibility is structural: the consumer re-exports supervisor schema
    strings from the datasets code-evidence adapter and binds the DuckDB AST
    store catalog declared by DQK-031. A second incompatible AST schema is
    never invented here.
    """

    descriptor = ast_store_schema_descriptor()
    supervisor_pins = {
        "analysis_ast_index": SUPERVISOR_ANALYSIS_AST_INDEX_SCHEMA,
        "conflict_graph": SUPERVISOR_CONFLICT_GRAPH_SCHEMA,
        "code_evidence_graph": SUPERVISOR_CODE_EVIDENCE_GRAPH_SCHEMA,
        "code_evidence_node": SUPERVISOR_CODE_EVIDENCE_NODE_SCHEMA,
        "code_evidence_edge": SUPERVISOR_CODE_EVIDENCE_EDGE_SCHEMA,
        "code_impact_index": SUPERVISOR_CODE_IMPACT_INDEX_SCHEMA,
        "code_impact_result": SUPERVISOR_CODE_IMPACT_RESULT_SCHEMA,
        "semantic_dependency_graph": SUPERVISOR_SEMANTIC_DEPENDENCY_GRAPH_SCHEMA,
        "supervisor_blob_summary": SUPERVISOR_BLOB_SUMMARY_SCHEMA,
    }
    datasets_pins = {
        "duckdb_ast_store_interface": DUCKDB_AST_STORE_INTERFACE,
        "duckdb_ast_store_schema": DUCKDB_AST_STORE_SCHEMA_VERSION,
        "duckdb_impact_schema": DUCKDB_IMPACT_SCHEMA,
        "duckdb_code_evidence_interface": DUCKDB_CODE_EVIDENCE_INTERFACE,
        "duckdb_code_evidence_schema": DUCKDB_CODE_EVIDENCE_SCHEMA,
        "ast_ir_schema": AST_IR_SCHEMA_VERSION.identifier,
        "asts_catalog_tables": list(ASTS_CATALOG_TABLES),
    }
    # Re-check that adapter-local aliases still equal the code_evidence module.
    alias_checks = {
        "analysis_ast_index": (
            SUPERVISOR_ANALYSIS_AST_INDEX_SCHEMA,
            _ce.ANALYSIS_AST_INDEX_SCHEMA,
        ),
        "conflict_graph": (
            SUPERVISOR_CONFLICT_GRAPH_SCHEMA,
            _ce.CONFLICT_GRAPH_SCHEMA,
        ),
        "code_evidence_graph": (
            SUPERVISOR_CODE_EVIDENCE_GRAPH_SCHEMA,
            _ce.CODE_EVIDENCE_GRAPH_SCHEMA,
        ),
        "code_evidence_node": (
            SUPERVISOR_CODE_EVIDENCE_NODE_SCHEMA,
            _ce.CODE_EVIDENCE_NODE_SCHEMA,
        ),
        "code_evidence_edge": (
            SUPERVISOR_CODE_EVIDENCE_EDGE_SCHEMA,
            _ce.CODE_EVIDENCE_EDGE_SCHEMA,
        ),
        "code_impact_index": (
            SUPERVISOR_CODE_IMPACT_INDEX_SCHEMA,
            _ce.CODE_IMPACT_INDEX_SCHEMA,
        ),
        "code_impact_result": (
            SUPERVISOR_CODE_IMPACT_RESULT_SCHEMA,
            _ce.CODE_IMPACT_RESULT_SCHEMA,
        ),
        "semantic_dependency_graph": (
            SUPERVISOR_SEMANTIC_DEPENDENCY_GRAPH_SCHEMA,
            _ce.SEMANTIC_DEPENDENCY_GRAPH_SCHEMA,
        ),
        "supervisor_blob_summary": (
            SUPERVISOR_BLOB_SUMMARY_SCHEMA,
            "ipfs_accelerate_py/agent-supervisor/ast-blob-record@1",
        ),
    }
    mismatches = {
        name: {"adapter": left, "authority": right}
        for name, (left, right) in alias_checks.items()
        if left != right
    }
    compatible = not mismatches and descriptor["interface"] == DUCKDB_AST_STORE_INTERFACE
    return {
        "schema": f"{DUCKDB_CODE_EVIDENCE_SCHEMA}/compatibility@1",
        "compatible": compatible,
        "mismatches": mismatches,
        "supervisor_pins": supervisor_pins,
        "datasets_pins": datasets_pins,
        "ast_store_descriptor": descriptor,
        "guarantees": {
            "no_second_ast_schema": True,
            "supervisor_schemas_reexported": True,
            "duckdb_ast_store_bound": True,
            "duckdb_impact_bound": True,
        },
    }


def assert_schema_compatible() -> dict[str, Any]:
    """Fail closed when datasets and supervisor schema pins diverge."""

    report = schema_compatibility_report()
    if not report["compatible"]:
        raise SchemaCompatibilityError(
            "datasets and supervisor projections are not schema compatible: "
            + ", ".join(sorted(report["mismatches"]))
        )
    return report


# ---------------------------------------------------------------------------
# Row stores (no whole-artifact JSON)
# ---------------------------------------------------------------------------


@dataclass
class _EvidenceRowStore:
    """Indexed evidence node/edge rows for one source revision."""

    source_revision: str
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: dict[str, dict[str, Any]] = field(default_factory=dict)

    def put_node(self, node: Mapping[str, Any]) -> dict[str, Any]:
        normalized = _ce.normalize_code_evidence_node(node)
        self.nodes[normalized["node_id"]] = normalized
        return normalized

    def put_edge(self, edge: Mapping[str, Any]) -> dict[str, Any]:
        normalized = _ce.normalize_code_evidence_edge(edge)
        self.edges[normalized["edge_id"]] = normalized
        return normalized

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        return self.nodes.get(node_id)

    def get_edge(self, edge_id: str) -> dict[str, Any] | None:
        return self.edges.get(edge_id)


@dataclass
class _ConflictRowStore:
    """Indexed conflict surfaces and edges for one source revision."""

    source_revision: str
    surfaces: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: list[dict[str, Any]] = field(default_factory=list)

    def put_surface(self, surface: Mapping[str, Any]) -> dict[str, Any]:
        task_id = _require_text(
            surface.get("task_id") or surface.get("task_cid"), "task_id"
        )
        task_cid = str(surface.get("task_cid") or task_id)
        row = {
            **dict(surface),
            "task_id": task_id,
            "task_cid": task_cid,
            "revision": str(
                surface.get("revision") or self.source_revision
            ),
            "schema": SUPERVISOR_CONFLICT_GRAPH_SCHEMA,
        }
        self.surfaces[task_cid] = row
        return row

    def put_edge(self, edge: Mapping[str, Any]) -> dict[str, Any]:
        left = _require_text(
            edge.get("left_task_cid") or edge.get("left"), "left_task_cid"
        )
        right = _require_text(
            edge.get("right_task_cid") or edge.get("right"), "right_task_cid"
        )
        weight = float(edge.get("weight") or 0.0)
        explicitly_allowed = bool(edge.get("explicitly_allowed", False))
        row = {
            **dict(edge),
            "left_task_cid": left,
            "right_task_cid": right,
            "weight": weight,
            "explicitly_allowed": explicitly_allowed,
            "blocks_concurrency": weight > 0 and not explicitly_allowed,
            "reasons": list(edge.get("reasons") or []),
            "schema": SUPERVISOR_CONFLICT_GRAPH_SCHEMA,
        }
        self.edges.append(row)
        return row


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class DuckDBCodeEvidenceAdapter:
    """Revision-bound consumer of the DQP-039 AST / evidence release plane.

    The adapter:

    1. Verifies and pins the exact DQP release/tree/schema identity.
    2. Serves AST lookups through :class:`DuckDBASTStore` (DQK-031).
    3. Serves dependency/impact closures through :mod:`duckdb_impact` (DQK-033).
    4. Accepts evidence and conflict *rows* only — never whole JSON artifacts.
    5. Asserts datasets/supervisor schema compatibility at construction.
    """

    def __init__(
        self,
        identity: DQPReleaseIdentity | Mapping[str, Any],
        *,
        source_revision: str,
        ast_store: DuckDBASTStore | None = None,
        impact_graph: ImpactGraph | None = None,
        verify_schema_compatibility: bool = True,
    ) -> None:
        if isinstance(identity, DQPReleaseIdentity):
            self._identity = identity
        else:
            self._identity = verify_dqp_release_identity(identity)
        revision = _require_text(source_revision, "source_revision")
        self._source_revision = revision
        if verify_schema_compatibility:
            assert_schema_compatible()
        self._ast_store = ast_store or build_duckdb_ast_store()
        if impact_graph is not None:
            if impact_graph.source_revision != revision:
                raise DuckDBCodeEvidenceError(
                    "impact graph source_revision must match adapter revision"
                )
            self._impact = impact_graph
        else:
            self._impact = ImpactGraph(source_revision=revision)
        self._evidence = _EvidenceRowStore(source_revision=revision)
        self._conflicts = _ConflictRowStore(source_revision=revision)
        # Track blob ids published through this adapter so lookups never
        # require walking private DuckDBASTStore internals.
        self._ast_blob_ids: list[str] = []
        self._lock = threading.RLock()
        self._stats = {
            "ast_puts": 0,
            "ast_lookups": 0,
            "evidence_nodes": 0,
            "evidence_edges": 0,
            "conflict_surfaces": 0,
            "conflict_edges": 0,
            "impact_edges": 0,
            "closures": 0,
            "identity_checks": 0,
            "refused_whole_artifact_loads": 0,
        }

    # -- identity ------------------------------------------------------------

    @property
    def interface(self) -> str:
        return DUCKDB_CODE_EVIDENCE_INTERFACE

    @property
    def schema(self) -> str:
        return DUCKDB_CODE_EVIDENCE_SCHEMA

    @property
    def identity(self) -> DQPReleaseIdentity:
        return self._identity

    @property
    def source_revision(self) -> str:
        return self._source_revision

    @property
    def ast_store(self) -> DuckDBASTStore:
        return self._ast_store

    def verify_identity(
        self, expected: DQPReleaseIdentity | Mapping[str, Any]
    ) -> DQPReleaseIdentity:
        """Verify that *expected* matches this adapter's exact DQP identity."""

        with self._lock:
            self._stats["identity_checks"] += 1
        peer = (
            expected
            if isinstance(expected, DQPReleaseIdentity)
            else verify_dqp_release_identity(expected)
        )
        if not self._identity.matches(peer):
            raise IdentityMismatchError(
                "DQP release/tree/schema identity mismatch: "
                f"pinned={self._identity.triple!r} claimed={peer.triple!r}"
            )
        if self._identity.store_generation != peer.store_generation:
            raise IdentityMismatchError("store_generation mismatch")
        if self._identity.quack_profile != peer.quack_profile:
            raise IdentityMismatchError("quack_profile mismatch")
        return self._identity

    # -- refusal of whole-artifact JSON --------------------------------------

    def load_whole_artifact_json(self, *_args: Any, **_kwargs: Any) -> None:
        """Explicitly refuse whole-artifact JSON loads (acceptance criterion)."""

        with self._lock:
            self._stats["refused_whole_artifact_loads"] += 1
        raise WholeArtifactLoadError(
            "DuckDBCodeEvidenceAdapter refuses whole-artifact JSON load; "
            "ingest AST projections, evidence rows, conflict rows, and impact "
            "edges instead"
        )

    # alias common consumer mistakes onto the refusal path
    load_bundle = load_whole_artifact_json
    load_code_evidence_graph_artifact = load_whole_artifact_json
    load_analysis_ast_index_artifact = load_whole_artifact_json
    load_conflict_graph_artifact = load_whole_artifact_json

    # -- AST (DQK-031 store; not reimplemented) ------------------------------

    def put_ast_projection(
        self, projection: ASTCatalogProjection
    ) -> ASTCatalogProjection:
        """Publish one AST catalog projection through the shared store."""

        if type(projection) is not ASTCatalogProjection:
            raise DuckDBCodeEvidenceError(
                "put_ast_projection requires an exact ASTCatalogProjection"
            )
        if projection.source_revision.revision != self._source_revision:
            # source_revision.revision is the Git/content revision string
            # while revision_id is the composite key — bind the content rev.
            if projection.source_revision.revision_id != self._source_revision:
                # Allow either form so callers may pass revision_id or revision.
                rev = projection.source_revision
                if (
                    rev.revision != self._source_revision
                    and rev.revision_id != self._source_revision
                ):
                    raise DuckDBCodeEvidenceError(
                        "AST projection revision does not match adapter "
                        f"source_revision {self._source_revision!r}"
                    )
        try:
            stored = self._ast_store.put_projection(projection)
        except DuckDBASTStoreError as exc:
            raise DuckDBCodeEvidenceError(str(exc)) from exc
        with self._lock:
            self._stats["ast_puts"] += 1
            if stored.blob_id not in self._ast_blob_ids:
                self._ast_blob_ids.append(stored.blob_id)
        return stored

    def get_ast_blob(self, blob_id: str) -> ASTCatalogProjection | None:
        with self._lock:
            self._stats["ast_lookups"] += 1
        return self._ast_store.get(blob_id)

    def get_ast_by_cid(self, ast_cid: str) -> ASTCatalogProjection | None:
        with self._lock:
            self._stats["ast_lookups"] += 1
        return self._ast_store.get_by_ast_cid(ast_cid)

    def query_ast_parse_failures(
        self, *, path: str | None = None
    ) -> tuple[Any, ...]:
        return self._ast_store.query_parse_failures(
            revision_id=None, path=path
        )

    def ast_lookup(
        self,
        *,
        path: str | None = None,
        symbol: str | None = None,
        blob_id: str | None = None,
    ) -> dict[str, Any]:
        """Bounded AST lookup over the catalog store (row-wise, not JSON)."""

        with self._lock:
            self._stats["ast_lookups"] += 1
            blob_ids = list(self._ast_blob_ids)
        results: list[dict[str, Any]] = []
        for candidate_id in blob_ids:
            if blob_id is not None and candidate_id != blob_id:
                continue
            projection = self._ast_store.get(candidate_id)
            if projection is None:
                continue
            file_path = projection.source_file.path
            if path is not None and file_path != path:
                continue
            symbols = [row.qualified_name for row in projection.symbols]
            if symbol is not None:
                simple = {item.rsplit(".", 1)[-1] for item in symbols}
                if symbol not in symbols and symbol not in simple:
                    continue
            results.append(
                {
                    "blob_id": projection.blob_id,
                    "ast_cid": projection.ast_cid,
                    "path": file_path,
                    "source_cid": projection.source_file.source_cid,
                    "revision_id": projection.source_revision.revision_id,
                    "qualified_symbols": symbols,
                    "imports": [row.module for row in projection.imports],
                    "calls": [row.callee_name for row in projection.calls],
                    "parse_status": projection.ast_blob.parse_status,
                    "schema": SUPERVISOR_BLOB_SUMMARY_SCHEMA,
                }
            )
        return {
            "schema": "duckdb-code-evidence-ast-query/v1",
            "source_revision": self._source_revision,
            "dqp_identity": {
                "accelerator_commit": self._identity.accelerator_commit,
                "accelerator_tree": self._identity.accelerator_tree,
                "schema_checksum": self._identity.schema_checksum,
            },
            "result_count": len(results),
            "results": results,
        }

    # -- dependency / impact (DQK-033; not reimplemented) --------------------

    def put_impact_edge(
        self, source: str, target: str, kind: str = "dependency"
    ) -> None:
        source_id = _require_text(source, "source")
        target_id = _require_text(target, "target")
        kind_text = _require_text(kind, "kind")
        with self._lock:
            self._impact.add(source_id, target_id, kind_text)
            self._stats["impact_edges"] += 1

    def put_impact_edges(
        self, edges: Iterable[Mapping[str, Any] | tuple[str, str, str]]
    ) -> int:
        count = 0
        for item in edges:
            if isinstance(item, Mapping):
                self.put_impact_edge(
                    str(item.get("source") or item.get("from")),
                    str(item.get("target") or item.get("to")),
                    str(item.get("kind") or "dependency"),
                )
            else:
                source, target, *rest = item
                kind = rest[0] if rest else "dependency"
                self.put_impact_edge(source, target, kind)
            count += 1
        return count

    def dependency_closure(
        self,
        roots: Sequence[str],
        *,
        direction: str = "forward",
        kinds: Iterable[str] | None = None,
        budget: ImpactBudget | None = None,
    ) -> ImpactResult:
        """Bounded dependency/impact closure bound to ``source_revision``."""

        try:
            result = impact_closure(
                self._impact,
                roots,
                direction=direction,
                kinds=kinds,
                budget=budget,
            )
        except ImpactQueryError as exc:
            raise DuckDBCodeEvidenceError(str(exc)) from exc
        if result.source_revision != self._source_revision:
            raise DuckDBCodeEvidenceError(
                "impact closure returned a foreign source_revision"
            )
        with self._lock:
            self._stats["closures"] += 1
        return result

    # -- evidence rows -------------------------------------------------------

    def put_evidence_node(self, node: Mapping[str, Any]) -> dict[str, Any]:
        """Ingest one evidence node row (not a whole graph artifact)."""

        with self._lock:
            stored = self._evidence.put_node(node)
            self._stats["evidence_nodes"] = len(self._evidence.nodes)
            return stored

    def put_evidence_edge(self, edge: Mapping[str, Any]) -> dict[str, Any]:
        """Ingest one evidence edge row (not a whole graph artifact)."""

        with self._lock:
            stored = self._evidence.put_edge(edge)
            self._stats["evidence_edges"] = len(self._evidence.edges)
            return stored

    def put_evidence_rows(
        self,
        *,
        nodes: Sequence[Mapping[str, Any]] = (),
        edges: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, int]:
        node_count = 0
        edge_count = 0
        for node in nodes:
            self.put_evidence_node(node)
            node_count += 1
        for edge in edges:
            self.put_evidence_edge(edge)
            edge_count += 1
        return {"nodes": node_count, "edges": edge_count}

    def get_evidence_node(self, node_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._evidence.get_node(node_id)

    def evidence_query(
        self,
        *,
        node_ids: Sequence[str] | None = None,
        kinds: Sequence[str] | None = None,
        authoritative_only: bool = False,
    ) -> dict[str, Any]:
        """Row-filtered evidence query (never materializes a whole JSON graph)."""

        kind_set = frozenset(kinds) if kinds is not None else None
        id_set = frozenset(node_ids) if node_ids is not None else None
        with self._lock:
            nodes = list(self._evidence.nodes.values())
            edges = list(self._evidence.edges.values())
        if id_set is not None:
            nodes = [n for n in nodes if n["node_id"] in id_set]
            edges = [
                e
                for e in edges
                if e.get("source") in id_set or e.get("target") in id_set
            ]
        if kind_set is not None:
            nodes = [n for n in nodes if n.get("kind") in kind_set]
        if authoritative_only:
            nodes = [n for n in nodes if n.get("authoritative")]
            edges = [e for e in edges if e.get("authoritative")]
        return {
            "schema": "duckdb-code-evidence-evidence-query/v1",
            "source_revision": self._source_revision,
            "supervisor_schema": SUPERVISOR_CODE_EVIDENCE_GRAPH_SCHEMA,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "nodes": nodes,
            "edges": edges,
            "dqp_identity": {
                "accelerator_commit": self._identity.accelerator_commit,
                "accelerator_tree": self._identity.accelerator_tree,
                "schema_checksum": self._identity.schema_checksum,
            },
        }

    # -- conflict rows -------------------------------------------------------

    def put_conflict_surface(self, surface: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            stored = self._conflicts.put_surface(surface)
            self._stats["conflict_surfaces"] = len(self._conflicts.surfaces)
            return stored

    def put_conflict_edge(self, edge: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            stored = self._conflicts.put_edge(edge)
            self._stats["conflict_edges"] = len(self._conflicts.edges)
            return stored

    def conflict_query(
        self,
        *,
        task_cid: str | None = None,
        blocking_only: bool = True,
    ) -> dict[str, Any]:
        with self._lock:
            edges = list(self._conflicts.edges)
            surfaces = dict(self._conflicts.surfaces)
        if blocking_only:
            edges = [e for e in edges if e.get("blocks_concurrency")]
        surface: dict[str, Any] | None = None
        if task_cid:
            cid = _require_text(task_cid, "task_cid")
            edges = [
                e
                for e in edges
                if cid
                in {e.get("left_task_cid"), e.get("right_task_cid")}
            ]
            surface = surfaces.get(cid)
        return {
            "schema": "duckdb-code-evidence-conflict-query/v1",
            "source_revision": self._source_revision,
            "supervisor_schema": SUPERVISOR_CONFLICT_GRAPH_SCHEMA,
            "task_cid": task_cid,
            "edge_count": len(edges),
            "edges": edges,
            "surface": surface,
            "surface_count": len(surfaces),
            "dqp_identity": {
                "accelerator_commit": self._identity.accelerator_commit,
                "accelerator_tree": self._identity.accelerator_tree,
                "schema_checksum": self._identity.schema_checksum,
            },
        }

    # -- stats / descriptor --------------------------------------------------

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                **self._stats,
                "evidence_nodes": len(self._evidence.nodes),
                "evidence_edges": len(self._evidence.edges),
                "conflict_surfaces": len(self._conflicts.surfaces),
                "conflict_edges": len(self._conflicts.edges),
            }

    def descriptor(self) -> Mapping[str, Any]:
        """Machine-readable surface statement for gates and inventories."""

        return MappingProxyType(
            {
                "interface": DUCKDB_CODE_EVIDENCE_INTERFACE,
                "schema": DUCKDB_CODE_EVIDENCE_SCHEMA,
                "schema_version": ADAPTER_SCHEMA_VERSION,
                "source_revision": self._source_revision,
                "dqp_identity": self._identity.to_dict(),
                "reuses": {
                    "duckdb_ast_store": DUCKDB_AST_STORE_INTERFACE,
                    "duckdb_impact": DUCKDB_IMPACT_SCHEMA,
                    "supervisor_code_evidence": SUPERVISOR_CODE_EVIDENCE_GRAPH_SCHEMA,
                    "supervisor_conflict": SUPERVISOR_CONFLICT_GRAPH_SCHEMA,
                    "supervisor_ast_blob": SUPERVISOR_BLOB_SUMMARY_SCHEMA,
                },
                "guarantees": {
                    "verifies_exact_dqp_release_tree_schema_identity": True,
                    "no_whole_artifact_json_load": True,
                    "datasets_supervisor_schema_compatible": True,
                    "does_not_reimplement_supervisor_stores": True,
                },
            }
        )


def build_duckdb_code_evidence_adapter(
    identity: DQPReleaseIdentity | Mapping[str, Any],
    *,
    source_revision: str,
    ast_store: DuckDBASTStore | None = None,
    impact_graph: ImpactGraph | None = None,
    verify_schema_compatibility: bool = True,
) -> DuckDBCodeEvidenceAdapter:
    """Construct a :class:`DuckDBCodeEvidenceAdapter` with standard defaults."""

    return DuckDBCodeEvidenceAdapter(
        identity,
        source_revision=source_revision,
        ast_store=ast_store,
        impact_graph=impact_graph,
        verify_schema_compatibility=verify_schema_compatibility,
    )


# Back-compat alias used by some consumer wiring patterns.
open_duckdb_code_evidence_adapter = build_duckdb_code_evidence_adapter
