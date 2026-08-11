"""DuckDB-backed code-evidence consumer adapter (DQK-034).

Adapts datasets code-evidence consumers to the DQP-039 revision-bound AST,
dependency, conflict, and evidence interfaces **without reimplementing** the
supervisor stores:

* AST catalog rows via :mod:`ipfs_datasets_py.logic.software_contracts.duckdb_ast_store`
* Impact / dependency closures via :mod:`ipfs_datasets_py.logic.software_contracts.duckdb_impact`
* Supervisor schema identifiers shared with
  :mod:`ipfs_datasets_py.knowledge_graphs.adapters.code_evidence`

The adapter:

* verifies the exact DQP release / tree / schema identity before serving queries
* answers AST, dependency, conflict, and evidence queries from typed row
  projections (no whole-artifact JSON graph load is required)
* keeps datasets and supervisor projections schema-compatible by pinning the
  same producer schema strings

Importing this module is inert: no DuckDB, network, or filesystem I/O.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from ipfs_datasets_py.knowledge_graphs.adapters import code_evidence as _ce
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
    ASTS_CATALOG_NAME,
    ASTS_CATALOG_TABLES,
    DUCKDB_AST_STORE_INTERFACE,
    DUCKDB_AST_STORE_SCHEMA_VERSION,
    SUPERVISOR_BLOB_SUMMARY_SCHEMA,
    ASTCatalogProjection,
    DuckDBASTStore,
    DuckDBASTStoreError,
    build_duckdb_ast_store,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_impact import (
    DUCKDB_IMPACT_SCHEMA,
    BudgetExceeded,
    ImpactBudget,
    ImpactEdge,
    ImpactGraph,
    ImpactQueryError,
    ImpactResult,
    closure as impact_closure,
)
from ipfs_datasets_py.logic.software_contracts.schema_versions import (
    AST_IR_SCHEMA_VERSION,
)

# ---------------------------------------------------------------------------
# Interface / schema pins
# ---------------------------------------------------------------------------

DUCKDB_CODE_EVIDENCE_INTERFACE: Final = "DuckDBCodeEvidenceAdapter@1"
DUCKDB_CODE_EVIDENCE_SCHEMA: Final = (
    "ipfs_datasets_py/knowledge-graphs-duckdb-code-evidence@1"
)

# DQP-039 release plane identity (mirrored from the external release verifier).
DQP_PROGRAM_ID: Final = "agent-supervisor-duckdb-quack-control-plane-v1"
DQP_RELEASE_TASK_ID: Final = "DQP-039"
DQP_RELEASE_RECEIPT_INTERFACE: Final = "DuckDBControlPlaneReleaseReceipt@1"
DQP_RELEASE_RECEIPT_SCHEMA: Final = (
    "ipfs_accelerate_py/agent-supervisor/duckdb-control-plane-release-receipt@1"
)
DQP_VERIFICATION_SCHEMA: Final = (
    "ipfs_accelerate_py/agent-supervisor/duckdb-quack-release-verification@1"
)

# Supervisor / datasets shared graph schemas (must stay identical).
ANALYSIS_AST_INDEX_SCHEMA: Final = _ce.ANALYSIS_AST_INDEX_SCHEMA
CODE_EVIDENCE_GRAPH_SCHEMA: Final = _ce.CODE_EVIDENCE_GRAPH_SCHEMA
CODE_EVIDENCE_NODE_SCHEMA: Final = _ce.CODE_EVIDENCE_NODE_SCHEMA
CODE_EVIDENCE_EDGE_SCHEMA: Final = _ce.CODE_EVIDENCE_EDGE_SCHEMA
CODE_IMPACT_INDEX_SCHEMA: Final = _ce.CODE_IMPACT_INDEX_SCHEMA
CONFLICT_GRAPH_SCHEMA: Final = _ce.CONFLICT_GRAPH_SCHEMA
SEMANTIC_DEPENDENCY_GRAPH_SCHEMA: Final = _ce.SEMANTIC_DEPENDENCY_GRAPH_SCHEMA

# Query result schemas (compatible with the JSON corpus adapter surface).
AST_QUERY_SCHEMA: Final = "code-evidence-ast-query/v1"
DEPENDENCY_QUERY_SCHEMA: Final = "code-evidence-dependency-query/v1"
CONFLICT_QUERY_SCHEMA: Final = "code-evidence-conflict-query/v1"
EVIDENCE_QUERY_SCHEMA: Final = "code-evidence-evidence-query/v1"
IMPACT_QUERY_SCHEMA: Final = "code-evidence-impact-query/v1"

_GIT_OID: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_SHA256_DIGEST: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")

# Closed identity fields that must match exactly between expected and observed.
_DQP_IDENTITY_FIELDS: Final[tuple[str, ...]] = (
    "program_id",
    "release_task_id",
    "accelerator_commit",
    "accelerator_tree",
    "store_generation",
    "schema_checksum",
    "quack_profile",
)

# Supervisor schema identifiers that datasets projections must remain aligned with.
_COMPATIBLE_SCHEMA_PAIRS: Final[tuple[tuple[str, str], ...]] = (
    ("analysis_ast_index", ANALYSIS_AST_INDEX_SCHEMA),
    ("code_evidence_graph", CODE_EVIDENCE_GRAPH_SCHEMA),
    ("code_evidence_node", CODE_EVIDENCE_NODE_SCHEMA),
    ("code_evidence_edge", CODE_EVIDENCE_EDGE_SCHEMA),
    ("code_impact_index", CODE_IMPACT_INDEX_SCHEMA),
    ("conflict_graph", CONFLICT_GRAPH_SCHEMA),
    ("semantic_dependency_graph", SEMANTIC_DEPENDENCY_GRAPH_SCHEMA),
    ("ast_blob_summary", SUPERVISOR_BLOB_SUMMARY_SCHEMA),
    ("duckdb_ast_store", DUCKDB_AST_STORE_SCHEMA_VERSION),
    ("duckdb_impact", DUCKDB_IMPACT_SCHEMA),
)


class DuckDBCodeEvidenceError(RuntimeError):
    """Raised when the DuckDB code-evidence adapter fails closed."""


class DQPReleaseIdentityError(DuckDBCodeEvidenceError):
    """Raised when the DQP release/tree/schema identity does not match."""


class SchemaCompatibilityError(DuckDBCodeEvidenceError):
    """Raised when datasets and supervisor projections disagree on schema."""


# ---------------------------------------------------------------------------
# DQP release identity
# ---------------------------------------------------------------------------


def _text(value: object, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise DuckDBCodeEvidenceError(f"{field_name} must be a string")
    if value != value.strip() and value:
        raise DuckDBCodeEvidenceError(
            f"{field_name} must not contain surrounding whitespace"
        )
    if not allow_empty and not value:
        raise DuckDBCodeEvidenceError(f"{field_name} must not be empty")
    if "\x00" in value or "\n" in value or "\r" in value:
        raise DuckDBCodeEvidenceError(
            f"{field_name} must not contain control characters"
        )
    return value


def _git_oid(value: object, field_name: str) -> str:
    text = _text(value, field_name).lower()
    if not _GIT_OID.fullmatch(text):
        raise DuckDBCodeEvidenceError(
            f"{field_name} must be a 40-character lowercase git OID"
        )
    return text


def _sha256_digest(value: object, field_name: str) -> str:
    text = _text(value, field_name).lower()
    if not _SHA256_DIGEST.fullmatch(text):
        raise DuckDBCodeEvidenceError(
            f"{field_name} must be a sha256:<64-hex> digest"
        )
    return text


def _constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


@dataclass(frozen=True, slots=True)
class DQPReleaseIdentity:
    """Exact DQP-039 release / tree / schema identity binding.

    Fields mirror the gate verification object emitted by
    ``validate_accelerate_duckdb_quack_release`` so consumers pin the same
    machine-readable identity the release plane admits.
    """

    accelerator_commit: str
    accelerator_tree: str
    store_generation: str
    schema_checksum: str
    quack_profile: str
    program_id: str = DQP_PROGRAM_ID
    release_task_id: str = DQP_RELEASE_TASK_ID
    release_receipt_interface: str = DQP_RELEASE_RECEIPT_INTERFACE
    release_receipt_schema: str = DQP_RELEASE_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "accelerator_commit",
            _git_oid(self.accelerator_commit, "accelerator_commit"),
        )
        object.__setattr__(
            self,
            "accelerator_tree",
            _git_oid(self.accelerator_tree, "accelerator_tree"),
        )
        object.__setattr__(
            self,
            "store_generation",
            _text(self.store_generation, "store_generation"),
        )
        object.__setattr__(
            self,
            "schema_checksum",
            _sha256_digest(self.schema_checksum, "schema_checksum"),
        )
        object.__setattr__(
            self, "quack_profile", _text(self.quack_profile, "quack_profile")
        )
        object.__setattr__(
            self, "program_id", _text(self.program_id, "program_id")
        )
        object.__setattr__(
            self,
            "release_task_id",
            _text(self.release_task_id, "release_task_id"),
        )
        if self.release_task_id != DQP_RELEASE_TASK_ID:
            raise DQPReleaseIdentityError(
                f"release_task_id must be {DQP_RELEASE_TASK_ID}, "
                f"got {self.release_task_id!r}"
            )
        if self.program_id != DQP_PROGRAM_ID:
            raise DQPReleaseIdentityError(
                f"program_id must be {DQP_PROGRAM_ID}, got {self.program_id!r}"
            )
        object.__setattr__(
            self,
            "release_receipt_interface",
            _text(self.release_receipt_interface, "release_receipt_interface"),
        )
        object.__setattr__(
            self,
            "release_receipt_schema",
            _text(self.release_receipt_schema, "release_receipt_schema"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "program_id": self.program_id,
            "release_task_id": self.release_task_id,
            "release_receipt_interface": self.release_receipt_interface,
            "release_receipt_schema": self.release_receipt_schema,
            "accelerator_commit": self.accelerator_commit,
            "accelerator_tree": self.accelerator_tree,
            "store_generation": self.store_generation,
            "schema_checksum": self.schema_checksum,
            "quack_profile": self.quack_profile,
        }

    def identity_digest(self) -> str:
        """Return a content-bound digest over the closed identity fields."""

        body = "|".join(
            f"{name}={getattr(self, name)}" for name in _DQP_IDENTITY_FIELDS
        )
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "DQPReleaseIdentity":
        if not isinstance(payload, Mapping):
            raise DuckDBCodeEvidenceError("release identity must be a mapping")
        return cls(
            accelerator_commit=str(payload.get("accelerator_commit") or ""),
            accelerator_tree=str(payload.get("accelerator_tree") or ""),
            store_generation=str(payload.get("store_generation") or ""),
            schema_checksum=str(payload.get("schema_checksum") or ""),
            quack_profile=str(payload.get("quack_profile") or ""),
            program_id=str(payload.get("program_id") or DQP_PROGRAM_ID),
            release_task_id=str(
                payload.get("release_task_id")
                or payload.get("task_id")
                or DQP_RELEASE_TASK_ID
            ),
            release_receipt_interface=str(
                payload.get("release_receipt_interface")
                or payload.get("interface")
                or DQP_RELEASE_RECEIPT_INTERFACE
            ),
            release_receipt_schema=str(
                payload.get("release_receipt_schema")
                or payload.get("schema")
                or DQP_RELEASE_RECEIPT_SCHEMA
            ),
        )


def verify_dqp_release_identity(
    observed: DQPReleaseIdentity | Mapping[str, Any],
    expected: DQPReleaseIdentity | Mapping[str, Any],
) -> DQPReleaseIdentity:
    """Fail closed unless observed and expected DQP identities match exactly.

    Compares program, release task, accelerator commit/tree, store generation,
    schema checksum, and Quack profile. Digest fields use constant-time
    comparison.
    """

    actual = (
        observed
        if isinstance(observed, DQPReleaseIdentity)
        else DQPReleaseIdentity.from_mapping(observed)
    )
    want = (
        expected
        if isinstance(expected, DQPReleaseIdentity)
        else DQPReleaseIdentity.from_mapping(expected)
    )
    mismatches: list[str] = []
    for name in _DQP_IDENTITY_FIELDS:
        left = getattr(actual, name)
        right = getattr(want, name)
        if name in {"accelerator_commit", "accelerator_tree", "schema_checksum"}:
            if not _constant_time_equal(left, right):
                mismatches.append(name)
        elif left != right:
            mismatches.append(name)
    if mismatches:
        raise DQPReleaseIdentityError(
            "DQP release/tree/schema identity mismatch: "
            + ", ".join(mismatches)
        )
    return actual


# ---------------------------------------------------------------------------
# Schema compatibility
# ---------------------------------------------------------------------------


def schema_compatibility_report() -> dict[str, Any]:
    """Return the closed set of schema pins shared with the supervisor plane."""

    datasets_pins = {
        "analysis_ast_index": _ce.ANALYSIS_AST_INDEX_SCHEMA,
        "code_evidence_graph": _ce.CODE_EVIDENCE_GRAPH_SCHEMA,
        "code_evidence_node": _ce.CODE_EVIDENCE_NODE_SCHEMA,
        "code_evidence_edge": _ce.CODE_EVIDENCE_EDGE_SCHEMA,
        "code_impact_index": _ce.CODE_IMPACT_INDEX_SCHEMA,
        "conflict_graph": _ce.CONFLICT_GRAPH_SCHEMA,
        "semantic_dependency_graph": _ce.SEMANTIC_DEPENDENCY_GRAPH_SCHEMA,
    }
    adapter_pins = {
        "analysis_ast_index": ANALYSIS_AST_INDEX_SCHEMA,
        "code_evidence_graph": CODE_EVIDENCE_GRAPH_SCHEMA,
        "code_evidence_node": CODE_EVIDENCE_NODE_SCHEMA,
        "code_evidence_edge": CODE_EVIDENCE_EDGE_SCHEMA,
        "code_impact_index": CODE_IMPACT_INDEX_SCHEMA,
        "conflict_graph": CONFLICT_GRAPH_SCHEMA,
        "semantic_dependency_graph": SEMANTIC_DEPENDENCY_GRAPH_SCHEMA,
    }
    pairs: dict[str, dict[str, Any]] = {}
    compatible = True
    for name, expected in datasets_pins.items():
        observed = adapter_pins[name]
        ok = observed == expected
        if not ok:
            compatible = False
        pairs[name] = {
            "datasets": expected,
            "adapter": observed,
            "compatible": ok,
        }
    # DuckDB AST store must project the shared supervisor blob summary schema.
    blob_ok = SUPERVISOR_BLOB_SUMMARY_SCHEMA == (
        "ipfs_accelerate_py/agent-supervisor/ast-blob-record@1"
    )
    if not blob_ok:
        compatible = False
    pairs["ast_blob_summary"] = {
        "datasets": SUPERVISOR_BLOB_SUMMARY_SCHEMA,
        "supervisor": "ipfs_accelerate_py/agent-supervisor/ast-blob-record@1",
        "compatible": blob_ok,
    }
    return {
        "schema": f"{DUCKDB_CODE_EVIDENCE_SCHEMA}/compatibility",
        "interface": DUCKDB_CODE_EVIDENCE_INTERFACE,
        "compatible": compatible,
        "pairs": pairs,
        "ast_store_interface": DUCKDB_AST_STORE_INTERFACE,
        "ast_store_schema_version": DUCKDB_AST_STORE_SCHEMA_VERSION,
        "ast_ir_schema": AST_IR_SCHEMA_VERSION.identifier,
        "impact_schema": DUCKDB_IMPACT_SCHEMA,
        "asts_catalog": ASTS_CATALOG_NAME,
        "asts_tables": list(ASTS_CATALOG_TABLES),
    }


def assert_schema_compatibility() -> dict[str, Any]:
    """Fail closed when datasets and supervisor projections diverge."""

    report = schema_compatibility_report()
    if not report["compatible"]:
        bad = sorted(
            name
            for name, entry in report["pairs"].items()
            if not entry["compatible"]
        )
        raise SchemaCompatibilityError(
            "datasets/supervisor schema incompatibility: " + ", ".join(bad)
        )
    return report


def adapter_schema_descriptor() -> dict[str, Any]:
    """Return a deterministic machine-readable adapter/schema statement."""

    return {
        "interface": DUCKDB_CODE_EVIDENCE_INTERFACE,
        "schema": DUCKDB_CODE_EVIDENCE_SCHEMA,
        "dqp_program_id": DQP_PROGRAM_ID,
        "dqp_release_task_id": DQP_RELEASE_TASK_ID,
        "dqp_release_receipt_interface": DQP_RELEASE_RECEIPT_INTERFACE,
        "requires_whole_artifact_json_load": False,
        "reimplements_supervisor_stores": False,
        "consumes": {
            "ast_store": DUCKDB_AST_STORE_INTERFACE,
            "impact": DUCKDB_IMPACT_SCHEMA,
            "code_evidence_graph": CODE_EVIDENCE_GRAPH_SCHEMA,
            "conflict_graph": CONFLICT_GRAPH_SCHEMA,
            "analysis_ast_index": ANALYSIS_AST_INDEX_SCHEMA,
        },
        "compatible_schemas": dict(_COMPATIBLE_SCHEMA_PAIRS),
        "guarantees": {
            "verifies_dqp_release_tree_schema_identity": True,
            "no_whole_artifact_json_load": True,
            "schema_compatible_with_supervisor": True,
            "import_inert": True,
        },
    }


# ---------------------------------------------------------------------------
# Revision-bound typed plane (no whole-artifact JSON)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvidenceNodeRow:
    """One revision-bound code-evidence node (typed row, not a JSON blob)."""

    node_id: str
    kind: str
    record_key: str
    provenance: str
    authoritative: bool
    revision: str
    task_id: str = ""
    tree_id: str = ""
    symbol: str = ""
    obligation_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CODE_EVIDENCE_NODE_SCHEMA,
            "node_id": self.node_id,
            "kind": self.kind,
            "record_key": self.record_key,
            "provenance": self.provenance,
            "authoritative": self.authoritative,
            "revision": self.revision,
            "task_id": self.task_id,
            "tree_id": self.tree_id,
            "symbol": self.symbol,
            "obligation_id": self.obligation_id,
        }


@dataclass(frozen=True, slots=True)
class EvidenceEdgeRow:
    """One revision-bound code-evidence edge."""

    edge_id: str
    kind: str
    source: str
    target: str
    provenance: str
    authoritative: bool
    revision: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CODE_EVIDENCE_EDGE_SCHEMA,
            "edge_id": self.edge_id,
            "kind": self.kind,
            "source": self.source,
            "target": self.target,
            "provenance": self.provenance,
            "authoritative": self.authoritative,
            "revision": self.revision,
        }


@dataclass(frozen=True, slots=True)
class ConflictEdgeRow:
    """One revision-bound conflict edge."""

    left_task_cid: str
    right_task_cid: str
    weight: float
    blocks_concurrency: bool
    explicitly_allowed: bool
    revision: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "left_task_cid": self.left_task_cid,
            "right_task_cid": self.right_task_cid,
            "weight": self.weight,
            "blocks_concurrency": self.blocks_concurrency,
            "explicitly_allowed": self.explicitly_allowed,
            "revision": self.revision,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ConflictSurfaceRow:
    """One revision-bound conflict surface."""

    task_id: str
    task_cid: str
    revision: str
    predicted_paths: tuple[str, ...] = ()
    predicted_symbols: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_cid": self.task_cid,
            "revision": self.revision,
            "predicted_paths": list(self.predicted_paths),
            "predicted_symbols": list(self.predicted_symbols),
            "dependencies": list(self.dependencies),
        }


@dataclass
class CodeEvidencePlane:
    """In-process, revision-bound AST / dependency / conflict / evidence plane.

    Holds typed rows and store handles only. Never materializes whole
    supervisor JSON artifacts (analysis_ast_index.json, code_evidence_graph.json,
    etc.). Suitable for hermetic unit tests and process-local consumers.
    """

    source_revision: str
    release_identity: DQPReleaseIdentity
    ast_store: DuckDBASTStore = field(default_factory=build_duckdb_ast_store)
    impact_graph: ImpactGraph | None = None
    evidence_nodes: list[EvidenceNodeRow] = field(default_factory=list)
    evidence_edges: list[EvidenceEdgeRow] = field(default_factory=list)
    conflict_surfaces: dict[str, ConflictSurfaceRow] = field(default_factory=dict)
    conflict_edges: list[ConflictEdgeRow] = field(default_factory=list)
    # Path index for O(1) AST lookups without scanning whole artifacts.
    _path_index: dict[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not self.source_revision or not str(self.source_revision).strip():
            raise DuckDBCodeEvidenceError("source_revision is required")
        self.source_revision = str(self.source_revision).strip()
        if self.impact_graph is None:
            self.impact_graph = ImpactGraph(source_revision=self.source_revision)
        elif self.impact_graph.source_revision != self.source_revision:
            raise DuckDBCodeEvidenceError(
                "impact graph source_revision must match the plane revision"
            )

    def put_ast_projection(self, projection: ASTCatalogProjection) -> None:
        """Index one AST catalog projection without loading JSON artifacts."""

        if type(projection) is not ASTCatalogProjection:
            raise DuckDBCodeEvidenceError(
                "put_ast_projection requires an exact ASTCatalogProjection"
            )
        if projection.source_revision.revision != self.source_revision and (
            projection.source_revision.revision_id != self.source_revision
        ):
            # Accept either bare revision or revision_id binding.
            raise DuckDBCodeEvidenceError(
                "AST projection is not bound to this plane's source_revision"
            )
        self.ast_store.put_projection(projection)
        self._path_index[projection.source_file.path] = projection.blob_id

    def put_evidence_node(self, node: EvidenceNodeRow) -> None:
        if node.revision != self.source_revision:
            raise DuckDBCodeEvidenceError(
                "evidence node revision must match the plane source_revision"
            )
        self.evidence_nodes.append(node)

    def put_evidence_edge(self, edge: EvidenceEdgeRow) -> None:
        if edge.revision != self.source_revision:
            raise DuckDBCodeEvidenceError(
                "evidence edge revision must match the plane source_revision"
            )
        self.evidence_edges.append(edge)

    def put_conflict_surface(self, surface: ConflictSurfaceRow) -> None:
        if surface.revision != self.source_revision:
            raise DuckDBCodeEvidenceError(
                "conflict surface revision must match the plane source_revision"
            )
        self.conflict_surfaces[surface.task_cid] = surface

    def put_conflict_edge(self, edge: ConflictEdgeRow) -> None:
        if edge.revision != self.source_revision:
            raise DuckDBCodeEvidenceError(
                "conflict edge revision must match the plane source_revision"
            )
        self.conflict_edges.append(edge)

    def add_dependency(
        self, source: str, target: str, kind: str = "dependency"
    ) -> None:
        assert self.impact_graph is not None
        self.impact_graph.add(source, target, kind)


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class DuckDBCodeEvidenceAdapter:
    """Revision-bound consumer over DQP AST / dependency / conflict / evidence.

    Does **not** reimplement supervisor stores. Does **not** require loading
    whole-artifact JSON graphs. Verifies the exact DQP release/tree/schema
    identity at construction time.
    """

    def __init__(
        self,
        plane: CodeEvidencePlane,
        *,
        expected_release: DQPReleaseIdentity | Mapping[str, Any] | None = None,
        verify_schemas: bool = True,
    ) -> None:
        if type(plane) is not CodeEvidencePlane:
            raise DuckDBCodeEvidenceError(
                "plane must be an exact CodeEvidencePlane"
            )
        expected = expected_release if expected_release is not None else plane.release_identity
        self._release = verify_dqp_release_identity(
            plane.release_identity, expected
        )
        if verify_schemas:
            assert_schema_compatibility()
        self._plane = plane
        self._source_revision = plane.source_revision
        # Explicit marker used by tests/acceptance: this adapter never loads
        # whole-artifact JSON graph files.
        self._whole_artifact_json_loads = 0

    # -- Identity / metadata -------------------------------------------------

    @property
    def interface(self) -> str:
        return DUCKDB_CODE_EVIDENCE_INTERFACE

    @property
    def schema(self) -> str:
        return DUCKDB_CODE_EVIDENCE_SCHEMA

    @property
    def source_revision(self) -> str:
        return self._source_revision

    @property
    def release_identity(self) -> DQPReleaseIdentity:
        return self._release

    @property
    def requires_whole_artifact_json_load(self) -> bool:
        """Acceptance: whole-artifact JSON load is never required."""

        return False

    @property
    def whole_artifact_json_load_count(self) -> int:
        return self._whole_artifact_json_loads

    def identity(self) -> dict[str, Any]:
        return {
            "schema": DUCKDB_CODE_EVIDENCE_SCHEMA,
            "interface": DUCKDB_CODE_EVIDENCE_INTERFACE,
            "source_revision": self._source_revision,
            "release": self._release.to_dict(),
            "release_identity_digest": self._release.identity_digest(),
            "requires_whole_artifact_json_load": False,
            "reimplements_supervisor_stores": False,
        }

    def schema_descriptor(self) -> dict[str, Any]:
        report = schema_compatibility_report()
        descriptor = adapter_schema_descriptor()
        descriptor["compatibility"] = report
        descriptor["source_revision"] = self._source_revision
        descriptor["release_identity_digest"] = self._release.identity_digest()
        return descriptor

    # -- AST (DuckDB AST store; no whole-artifact JSON) ----------------------

    def ast_lookup(
        self,
        *,
        path: str | None = None,
        symbol: str | None = None,
        blob_id: str | None = None,
        ast_cid: str | None = None,
    ) -> dict[str, Any]:
        """Look up AST projections from the DuckDB AST store by path/symbol/id."""

        results: list[dict[str, Any]] = []
        candidates: list[ASTCatalogProjection] = []

        if blob_id is not None:
            found = self._plane.ast_store.get(blob_id)
            if found is not None:
                candidates.append(found)
        elif ast_cid is not None:
            found = self._plane.ast_store.get_by_ast_cid(ast_cid)
            if found is not None:
                candidates.append(found)
        elif path is not None:
            blob = self._plane._path_index.get(path)
            if blob is not None:
                found = self._plane.ast_store.get(blob)
                if found is not None:
                    candidates.append(found)
            else:
                # Fall back to scanning indexed paths only (still not whole JSON).
                for indexed_path, indexed_blob in self._plane._path_index.items():
                    if indexed_path == path:
                        found = self._plane.ast_store.get(indexed_blob)
                        if found is not None:
                            candidates.append(found)
        else:
            for indexed_blob in self._plane._path_index.values():
                found = self._plane.ast_store.get(indexed_blob)
                if found is not None:
                    candidates.append(found)

        for projection in candidates:
            summary = projection.to_supervisor_blob_summary()
            symbols = list(summary.get("qualified_symbols") or [])
            if symbol is not None:
                simple = {item.rsplit(".", 1)[-1] for item in symbols}
                if symbol not in symbols and symbol not in simple:
                    continue
            if path is not None and projection.source_file.path != path:
                continue
            results.append(
                {
                    "path": projection.source_file.path,
                    "blob_id": projection.blob_id,
                    "blob_identity": summary.get("blob_identity"),
                    "source_sha256": summary.get("source_sha256"),
                    "ast_cid": projection.ast_cid,
                    "qualified_symbols": symbols,
                    "imports": list(summary.get("imports") or []),
                    "calls": list(summary.get("calls") or []),
                    "parse_status": projection.ast_blob.parse_status,
                    "schema": SUPERVISOR_BLOB_SUMMARY_SCHEMA,
                    "revision": projection.source_revision.revision,
                }
            )
        return {
            "schema": AST_QUERY_SCHEMA,
            "revision": self._source_revision,
            "release_identity_digest": self._release.identity_digest(),
            "result_count": len(results),
            "results": results,
            "source": "duckdb_ast_store",
            "whole_artifact_json_loaded": False,
        }

    # -- Dependency / impact (DQK-033 closures) ------------------------------

    def dependency_query(
        self,
        *,
        seed_ids: Sequence[str],
        direction: str = "forward",
        kinds: Iterable[str] | None = None,
        budget: ImpactBudget | None = None,
    ) -> dict[str, Any]:
        """Bounded dependency closure bound to the plane's source revision."""

        assert self._plane.impact_graph is not None
        try:
            result = impact_closure(
                self._plane.impact_graph,
                list(seed_ids),
                direction=direction,
                kinds=kinds,
                budget=budget,
            )
        except (ImpactQueryError, BudgetExceeded) as exc:
            raise DuckDBCodeEvidenceError(str(exc)) from exc
        if result.source_revision != self._source_revision:
            raise DuckDBCodeEvidenceError(
                "dependency closure is not bound to the adapter source_revision"
            )
        payload = result.to_dict()
        payload.update(
            {
                "schema": DEPENDENCY_QUERY_SCHEMA,
                "impact_schema": DUCKDB_IMPACT_SCHEMA,
                "family": "dependency",
                "revision": self._source_revision,
                "release_identity_digest": self._release.identity_digest(),
                "whole_artifact_json_loaded": False,
            }
        )
        return payload

    def impact_query(
        self,
        *,
        roots: Sequence[str],
        direction: str = "forward",
        kinds: Iterable[str] | None = None,
        budget: ImpactBudget | None = None,
    ) -> dict[str, Any]:
        """Bounded impact query (alias of dependency with impact schema stamp)."""

        dep = self.dependency_query(
            seed_ids=roots,
            direction=direction,
            kinds=kinds,
            budget=budget,
        )
        dep["schema"] = IMPACT_QUERY_SCHEMA
        dep["family"] = "impact"
        return dep

    # -- Conflict ------------------------------------------------------------

    def conflict_query(
        self,
        *,
        task_cid: str | None = None,
        blocking_only: bool = True,
    ) -> dict[str, Any]:
        """Query revision-bound conflict edges/surfaces without JSON artifacts."""

        edges = [
            edge
            for edge in self._plane.conflict_edges
            if edge.revision == self._source_revision
        ]
        if blocking_only:
            edges = [edge for edge in edges if edge.blocks_concurrency]
        if task_cid is not None:
            cid = _text(task_cid, "task_cid")
            edges = [
                edge
                for edge in edges
                if cid in {edge.left_task_cid, edge.right_task_cid}
            ]
            surface = self._plane.conflict_surfaces.get(cid)
        else:
            surface = None
        return {
            "schema": CONFLICT_QUERY_SCHEMA,
            "conflict_graph_schema": CONFLICT_GRAPH_SCHEMA,
            "revision": self._source_revision,
            "release_identity_digest": self._release.identity_digest(),
            "task_cid": task_cid,
            "edge_count": len(edges),
            "edges": [edge.to_dict() for edge in edges],
            "surface": surface.to_dict() if surface is not None else None,
            "surface_count": len(self._plane.conflict_surfaces),
            "whole_artifact_json_loaded": False,
        }

    # -- Evidence ------------------------------------------------------------

    def evidence_query(
        self,
        *,
        node_ids: Sequence[str] | None = None,
        kinds: Iterable[str] | None = None,
        authoritative_only: bool = False,
        symbol: str | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Query revision-bound evidence nodes/edges without JSON artifacts."""

        kind_set = frozenset(kinds) if kinds is not None else None
        id_set = frozenset(node_ids) if node_ids is not None else None
        nodes: list[dict[str, Any]] = []
        for node in self._plane.evidence_nodes:
            if node.revision != self._source_revision:
                continue
            if id_set is not None and node.node_id not in id_set:
                continue
            if kind_set is not None and node.kind not in kind_set:
                continue
            if authoritative_only and not node.authoritative:
                continue
            if symbol is not None and node.symbol != symbol:
                continue
            if task_id is not None and node.task_id != task_id:
                continue
            nodes.append(node.to_dict())
        node_id_set = {item["node_id"] for item in nodes}
        edges: list[dict[str, Any]] = []
        for edge in self._plane.evidence_edges:
            if edge.revision != self._source_revision:
                continue
            if authoritative_only and not edge.authoritative:
                continue
            if id_set is not None and (
                edge.source not in id_set and edge.target not in id_set
            ):
                # When filtering by node ids, keep edges incident to those nodes.
                continue
            if node_ids is not None and (
                edge.source not in node_id_set and edge.target not in node_id_set
            ):
                continue
            edges.append(edge.to_dict())
        return {
            "schema": EVIDENCE_QUERY_SCHEMA,
            "code_evidence_graph_schema": CODE_EVIDENCE_GRAPH_SCHEMA,
            "revision": self._source_revision,
            "release_identity_digest": self._release.identity_digest(),
            "node_count": len(nodes),
            "edge_count": len(edges),
            "nodes": nodes,
            "edges": edges,
            "whole_artifact_json_loaded": False,
        }


def build_duckdb_code_evidence_adapter(
    plane: CodeEvidencePlane,
    *,
    expected_release: DQPReleaseIdentity | Mapping[str, Any] | None = None,
    verify_schemas: bool = True,
) -> DuckDBCodeEvidenceAdapter:
    """Construct a :class:`DuckDBCodeEvidenceAdapter` with standard defaults."""

    return DuckDBCodeEvidenceAdapter(
        plane,
        expected_release=expected_release,
        verify_schemas=verify_schemas,
    )


def make_fixture_release_identity(
    *,
    commit: str = "a" * 40,
    tree: str = "b" * 40,
    store_generation: str = "generation:test-1",
    schema_checksum: str | None = None,
    quack_profile: str = "quack-profile:test@1",
) -> DQPReleaseIdentity:
    """Build a hermetic DQP release identity for unit tests."""

    if schema_checksum is None:
        schema_checksum = "sha256:" + ("c" * 64)
    return DQPReleaseIdentity(
        accelerator_commit=commit,
        accelerator_tree=tree,
        store_generation=store_generation,
        schema_checksum=schema_checksum,
        quack_profile=quack_profile,
    )


def make_fixture_ast_projection(
    *,
    source_revision: str,
    path: str = "src/example.py",
    qualified_symbol: str = "example.fetch",
    source_cid: str | None = None,
    ast_cid: str | None = None,
    repository_id: str = "repository:example",
) -> ASTCatalogProjection:
    """Build a hermetic AST catalog projection without multiformats / Git I/O.

    Used by unit tests and lightweight consumers that need a revision-bound
    AST row set without loading whole-artifact JSON or invoking CID codecs.
    """

    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
        ASTBlobRow,
        ASTCatalogProjection as _Projection,
        ASTNodeRow,
        CallRow,
        ImportRow,
        ParseStatus,
        ScopeRow,
        SourceFileRow,
        SourceRevisionRow,
        SpanColumns,
        SymbolRow,
    )

    rev = _text(source_revision, "source_revision")
    path_text = _text(path, "path")
    digest_seed = f"{rev}:{path_text}:{qualified_symbol}".encode("utf-8")
    digest = hashlib.sha256(digest_seed).hexdigest()
    src_cid = source_cid or f"bafyfixture{digest[:46]}"
    a_cid = ast_cid or f"bafyfixture{digest[16:62]}"
    revision_id = f"revision:{repository_id}:{rev}"
    file_id = f"file:{revision_id}:{path_text}"
    blob_id = f"blob:{a_cid}"
    span = SpanColumns(
        start_byte=0,
        end_byte=32,
        start_line=1,
        start_column=0,
        end_line=2,
        end_column=0,
    )
    simple_name = qualified_symbol.rsplit(".", 1)[-1]
    return _Projection(
        source_revision=SourceRevisionRow(
            revision_id=revision_id,
            repository_id=repository_id,
            revision=rev,
            repository_tree_cid=None,
            schema_version=DUCKDB_AST_STORE_SCHEMA_VERSION,
            created_at=0.0,
        ),
        source_file=SourceFileRow(
            file_id=file_id,
            revision_id=revision_id,
            path=path_text,
            source_cid=src_cid,
            language="python",
            created_at=0.0,
        ),
        ast_blob=ASTBlobRow(
            blob_id=blob_id,
            file_id=file_id,
            revision_id=revision_id,
            source_cid=src_cid,
            ast_cid=a_cid,
            language="python",
            frontend_name="fixture",
            frontend_version="1",
            frontend_toolchain_cid=f"bafyfixture{digest[8:54]}",
            ast_schema_identifier=AST_IR_SCHEMA_VERSION.identifier,
            store_schema_version=DUCKDB_AST_STORE_SCHEMA_VERSION,
            parse_status=ParseStatus.OK.value,
            parse_error="",
            payload_json="{}",
            created_at=0.0,
        ),
        nodes=(
            ASTNodeRow(
                node_id=f"{blob_id}:module",
                blob_id=blob_id,
                file_id=file_id,
                revision_id=revision_id,
                node_kind="module",
                record_id="module:example",
                parent_node_id=None,
                span=span,
                label="example",
                payload_json="{}",
            ),
        ),
        scopes=(
            ScopeRow(
                scope_row_id=f"{blob_id}:scope:module",
                blob_id=blob_id,
                scope_id="scope:module",
                kind="module",
                parent_scope_id=None,
                owner_symbol_id=None,
                span=span,
            ),
        ),
        symbols=(
            SymbolRow(
                symbol_row_id=f"{blob_id}:symbol:{simple_name}",
                blob_id=blob_id,
                symbol_id=f"symbol:{simple_name}:0",
                name=simple_name,
                qualified_name=qualified_symbol,
                kind="function",
                scope_id="scope:module",
                definition_ordinal=0,
                visibility="public",
                signature_json=None,
                decorator_names_json="[]",
                flags_json="[]",
                span=span,
            ),
        ),
        imports=(
            ImportRow(
                import_row_id=f"{blob_id}:import:os",
                blob_id=blob_id,
                import_id="import:os:0",
                scope_id="scope:module",
                module="os",
                kind="module",
                imported_name=None,
                local_name=None,
                is_type_only=False,
                span=span,
            ),
        ),
        references=(),
        calls=(
            CallRow(
                call_row_id=f"{blob_id}:call:client",
                blob_id=blob_id,
                call_id="call:client:0",
                scope_id="scope:module",
                callee_name="client",
                kind="direct",
                argument_count=0,
                callee_reference_id=None,
                named_argument_names_json="[]",
                is_awaited=False,
                span=span,
            ),
        ),
        effects=(),
        interfaces=(),
        diagnostics=(),
        invalidations=(),
    )


__all__ = [
    "ANALYSIS_AST_INDEX_SCHEMA",
    "AST_QUERY_SCHEMA",
    "CODE_EVIDENCE_EDGE_SCHEMA",
    "CODE_EVIDENCE_GRAPH_SCHEMA",
    "CODE_EVIDENCE_NODE_SCHEMA",
    "CODE_IMPACT_INDEX_SCHEMA",
    "CONFLICT_GRAPH_SCHEMA",
    "CONFLICT_QUERY_SCHEMA",
    "CodeEvidencePlane",
    "ConflictEdgeRow",
    "ConflictSurfaceRow",
    "DEPENDENCY_QUERY_SCHEMA",
    "DQPReleaseIdentity",
    "DQPReleaseIdentityError",
    "DQP_PROGRAM_ID",
    "DQP_RELEASE_RECEIPT_INTERFACE",
    "DQP_RELEASE_RECEIPT_SCHEMA",
    "DQP_RELEASE_TASK_ID",
    "DQP_VERIFICATION_SCHEMA",
    "DUCKDB_CODE_EVIDENCE_INTERFACE",
    "DUCKDB_CODE_EVIDENCE_SCHEMA",
    "DuckDBCodeEvidenceAdapter",
    "DuckDBCodeEvidenceError",
    "EVIDENCE_QUERY_SCHEMA",
    "EvidenceEdgeRow",
    "EvidenceNodeRow",
    "IMPACT_QUERY_SCHEMA",
    "SEMANTIC_DEPENDENCY_GRAPH_SCHEMA",
    "SchemaCompatibilityError",
    "adapter_schema_descriptor",
    "assert_schema_compatibility",
    "build_duckdb_code_evidence_adapter",
    "make_fixture_ast_projection",
    "make_fixture_release_identity",
    "schema_compatibility_report",
    "verify_dqp_release_identity",
    # Re-exported store surfaces so consumers need not reimport supervisor stores.
    "BudgetExceeded",
    "DuckDBASTStore",
    "DuckDBASTStoreError",
    "ImpactBudget",
    "ImpactEdge",
    "ImpactGraph",
    "ImpactResult",
    "SUPERVISOR_BLOB_SUMMARY_SCHEMA",
    "build_duckdb_ast_store",
]
