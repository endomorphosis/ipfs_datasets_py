"""Exact obligation slicing and unchanged-stage replay for LGCVF-071.

This module is a composition adapter.  Stage receipts remain owned by
:mod:`ipfs_datasets_py.logic.formalization.translation_receipts`; theorem-shaped
targets remain owned by :class:`ProofObligation`; and cache identity remains
owned by :class:`CanonicalProofCacheKey`.  No second proof cache, compiler, or
authority lattice is introduced.

A local mutation yields the smallest affected frontier over:

* translation stages (receipt identity, compiler, and source-map change cones);
* theorem dependencies (direct hits, reverse dependents, and SCC closure);
* proof obligations that cite those stages or theorems.

Reusable evidence is never trusted by pathname or prior disposition.  Unchanged
stages are independently replayed through :func:`replay_stage_receipt`.
Unaffected theorem and obligation evidence is independently re-admitted through
:func:`admit_cache_hit`.  Downstream authority never exceeds the weakest
upstream preservation ceiling already bound into the stage receipts.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar, Final, cast

from ipfs_datasets_py.logic.common.canonical_cache_key import (
    CanonicalCacheKeyError,
    CanonicalProofCacheKey,
    CrossEnvironmentHitError,
    InvalidCidError,
    admit_cache_hit,
    admit_canonical_cache_key,
    require_valid_cid,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.formalization.translation_receipts import (
    STAGE_ORDER,
    CompilationPipelineReceipt,
    CompilationStage,
    StageReceiptExpectation,
    StageTranslationReceipt,
    effective_downstream_authority,
    replay_stage_receipt,
    stage_index,
    stage_successor,
)
from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
)


OBLIGATION_SLICING_INTERFACE: Final = "ObligationSlice@1"
OBLIGATION_SLICE_RECEIPT_SCHEMA: Final = (
    "ipfs-datasets.software-verification.obligation-slice-receipt@1"
)
THEOREM_RECORD_SCHEMA: Final = "ipfs-datasets.software-verification.theorem-record@1"
THEOREM_DEPENDENCY_GRAPH_SCHEMA: Final = (
    "ipfs-datasets.software-verification.theorem-dependency-graph@1"
)
OBLIGATION_SLICE_BINDING_SCHEMA: Final = (
    "ipfs-datasets.software-verification.obligation-slice-binding@1"
)
LOCAL_MUTATION_SCHEMA: Final = "ipfs-datasets.software-verification.local-mutation@1"
OBLIGATION_EVIDENCE_REQUEST_SCHEMA: Final = (
    "ipfs-datasets.software-verification.obligation-evidence-request@1"
)
STAGE_SLICE_DECISION_SCHEMA: Final = (
    "ipfs-datasets.software-verification.stage-slice-decision@1"
)
THEOREM_SLICE_DECISION_SCHEMA: Final = (
    "ipfs-datasets.software-verification.theorem-slice-decision@1"
)
OBLIGATION_SLICE_DECISION_SCHEMA: Final = (
    "ipfs-datasets.software-verification.obligation-slice-decision@1"
)
EVIDENCE_REVALIDATION_DECISION_SCHEMA: Final = (
    "ipfs-datasets.software-verification.evidence-revalidation-decision@1"
)
SOURCE_NODE_CONE_SCHEMA: Final = "ipfs-datasets.software-verification.source-node-cone@1"


class ObligationSlicingError(ValueError):
    """Raised when an obligation-slicing request is malformed."""


class ObligationSlicingStaleError(ObligationSlicingError):
    """Raised when a supplied pipeline, graph, or binding is stale."""


class UnchangedStageReplayError(ObligationSlicingError):
    """Raised when an authority-bearing replay of an unchanged stage fails."""


class SliceSubjectKind(StrEnum):
    """Closed categories of slice subjects that can carry reusable evidence."""

    TRANSLATION_STAGE = "translation_stage"
    THEOREM = "theorem"
    OBLIGATION = "obligation"
    EVIDENCE = "evidence"


class SliceDisposition(StrEnum):
    """Whether one stage, theorem, obligation, or binding remains current."""

    INVALIDATED = "invalidated"
    REPLAYED = "replayed"
    REUSED = "reused"


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or "\x00" in value:
        raise ObligationSlicingError(f"{label} must be a trimmed non-empty string")
    return value


def _optional_text(value: object, label: str) -> str:
    if value in (None, ""):
        return ""
    return _text(value, label)


def _cid(value: object, label: str) -> str:
    try:
        return require_valid_cid(value, label)
    except (TypeError, ValueError, InvalidCidError) as error:
        raise ObligationSlicingError(f"{label} must be a valid CID") from error


def _unique_texts(
    values: Sequence[str] | object,
    label: str,
    *,
    nonempty: bool = False,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise ObligationSlicingError(f"{label} must be a sequence")
    result = tuple(sorted(_text(item, f"{label} item") for item in values))
    if len(result) != len(set(result)):
        raise ObligationSlicingError(f"{label} must not contain duplicates")
    if nonempty and not result:
        raise ObligationSlicingError(f"{label} must not be empty")
    return result


def _closed(value: Mapping[str, Any], fields: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ObligationSlicingError(f"{label} must be a mapping")
    actual = set(value)
    if actual != fields:
        raise ObligationSlicingError(
            f"{label} fields are closed (missing={sorted(fields - actual)}, "
            f"extra={sorted(actual - fields)})"
        )
    return dict(value)


def _enum(value: object, enum_type: type[Any], label: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(member.value) for member in enum_type)
        raise ObligationSlicingError(f"{label} must be one of {choices}") from error


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ObligationSlicingError(f"{label} must be a bool")
    return value


def _stage(value: object, label: str) -> CompilationStage:
    return cast(CompilationStage, _enum(value, CompilationStage, label))


def _stages(values: Sequence[str] | object, label: str) -> tuple[CompilationStage, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise ObligationSlicingError(f"{label} must be a sequence")
    result = tuple(_stage(item, f"{label} item") for item in values)
    identities = tuple(item.value for item in result)
    if len(identities) != len(set(identities)):
        raise ObligationSlicingError(f"{label} must not contain duplicates")
    return tuple(sorted(result, key=stage_index))


def _record(value: object, record_type: type[Any], label: str) -> Any:
    if isinstance(value, record_type):
        return value
    if isinstance(value, Mapping):
        return record_type.from_dict(value)
    raise ObligationSlicingError(f"{label} must be a {record_type.__name__}")


def _records(
    values: Sequence[Any] | object,
    record_type: type[Any],
    label: str,
) -> tuple[Any, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise ObligationSlicingError(f"{label} must be a sequence")
    return tuple(_record(item, record_type, f"{label} item") for item in values)


def _cache_key(value: object, label: str) -> CanonicalProofCacheKey:
    try:
        return admit_canonical_cache_key(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, CanonicalCacheKeyError) as error:
        raise ObligationSlicingError(f"{label} must be a CanonicalProofCacheKey") from error


def _pipeline(value: object, label: str) -> CompilationPipelineReceipt:
    if isinstance(value, CompilationPipelineReceipt):
        return value
    if isinstance(value, Mapping):
        try:
            return CompilationPipelineReceipt.from_dict(value)
        except (TypeError, ValueError) as error:
            raise ObligationSlicingError(f"{label} must be a CompilationPipelineReceipt") from error
    raise ObligationSlicingError(f"{label} must be a CompilationPipelineReceipt")


def _stage_by_output(
    pipeline: CompilationPipelineReceipt,
) -> dict[CompilationStage, StageTranslationReceipt]:
    indexed: dict[CompilationStage, StageTranslationReceipt] = {}
    for receipt in pipeline.stages:
        output = receipt.output.stage
        if output in indexed:
            raise ObligationSlicingError(
                f"pipeline {pipeline.pipeline_id} repeats output stage {output.value}"
            )
        indexed[output] = receipt
    return indexed


def _tarjan_sccs(
    nodes: set[str],
    adjacency: Mapping[str, set[str]],
) -> tuple[tuple[str, ...], ...]:
    """Return cyclic SCCs of a directed theorem-dependency graph."""

    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indexes: dict[str, int] = {}
    lows: dict[str, int] = {}
    result: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal index
        indexes[node] = index
        lows[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in sorted(adjacency.get(node, set())):
            if target not in indexes:
                visit(target)
                lows[node] = min(lows[node], lows[target])
            elif target in on_stack:
                lows[node] = min(lows[node], indexes[target])
        if lows[node] != indexes[node]:
            return
        members: list[str] = []
        while True:
            item = stack.pop()
            on_stack.remove(item)
            members.append(item)
            if item == node:
                break
        has_self_edge = node in adjacency.get(node, set())
        if len(members) > 1 or has_self_edge:
            result.append(tuple(sorted(members)))

    for node in sorted(nodes):
        if node not in indexes:
            visit(node)
    return tuple(sorted(result))


@dataclass(frozen=True, slots=True)
class TheoremRecord:
    """One theorem-shaped node in the dependency graph.

    ``premise_ids`` are other theorem identities this node cites.  Source nodes
    and the producing compilation stage locate the theorem in the translation
    pipeline without introducing a parallel obligation store.
    """

    theorem_id: str
    statement_identity: str
    premise_ids: tuple[str, ...] = ()
    producing_stage: CompilationStage | str = CompilationStage.VC
    obligation_ids: tuple[str, ...] = ()
    source_node_ids: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = ()
    content_identity: str = ""
    schema: str = THEOREM_RECORD_SCHEMA

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "assumption_ids",
            "content_identity",
            "obligation_ids",
            "premise_ids",
            "producing_stage",
            "schema",
            "source_node_ids",
            "statement_identity",
            "theorem_id",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "theorem_id", _text(self.theorem_id, "theorem_id"))
        object.__setattr__(
            self, "statement_identity", _text(self.statement_identity, "statement_identity")
        )
        object.__setattr__(self, "premise_ids", _unique_texts(self.premise_ids, "premise_ids"))
        object.__setattr__(self, "producing_stage", _stage(self.producing_stage, "producing_stage"))
        object.__setattr__(
            self, "obligation_ids", _unique_texts(self.obligation_ids, "obligation_ids")
        )
        object.__setattr__(
            self, "source_node_ids", _unique_texts(self.source_node_ids, "source_node_ids")
        )
        object.__setattr__(
            self, "assumption_ids", _unique_texts(self.assumption_ids, "assumption_ids")
        )
        object.__setattr__(
            self,
            "content_identity",
            _optional_text(self.content_identity, "content_identity") or self.statement_identity,
        )
        if self.schema != THEOREM_RECORD_SCHEMA:
            raise ObligationSlicingError("unsupported theorem record schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "content_identity": self.content_identity,
            "obligation_ids": list(self.obligation_ids),
            "premise_ids": list(self.premise_ids),
            "producing_stage": cast(CompilationStage, self.producing_stage).value,
            "schema": self.schema,
            "source_node_ids": list(self.source_node_ids),
            "statement_identity": self.statement_identity,
            "theorem_id": self.theorem_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TheoremRecord:
        payload = _closed(value, cls._FIELDS, cls.__name__)
        payload["premise_ids"] = tuple(payload["premise_ids"])
        payload["obligation_ids"] = tuple(payload["obligation_ids"])
        payload["source_node_ids"] = tuple(payload["source_node_ids"])
        payload["assumption_ids"] = tuple(payload["assumption_ids"])
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class TheoremDependencyGraph:
    """Directed theorem-to-theorem dependency graph with explicit SCCs.

    An edge ``premise → dependent`` means the dependent cites the premise.
    Invalidation walks that edge and then closes every touched cyclic SCC.
    """

    theorems: tuple[TheoremRecord, ...]
    graph_id: str = "theorem-graph:default"
    schema: str = THEOREM_DEPENDENCY_GRAPH_SCHEMA

    _FIELDS: ClassVar[frozenset[str]] = frozenset({"graph_id", "schema", "theorems"})

    def __post_init__(self) -> None:
        object.__setattr__(self, "graph_id", _text(self.graph_id, "graph_id"))
        theorems = _records(self.theorems, TheoremRecord, "theorems")
        identities = [item.theorem_id for item in theorems]
        if len(identities) != len(set(identities)):
            raise ObligationSlicingError("theorem IDs must be unique")
        known = set(identities)
        for theorem in theorems:
            missing = sorted(set(theorem.premise_ids) - known)
            if missing:
                raise ObligationSlicingError(
                    f"theorem {theorem.theorem_id} cites unknown premises {missing}"
                )
        object.__setattr__(
            self, "theorems", tuple(sorted(theorems, key=lambda item: item.theorem_id))
        )
        if self.schema != THEOREM_DEPENDENCY_GRAPH_SCHEMA:
            raise ObligationSlicingError("unsupported theorem dependency graph schema")

    @property
    def theorem_ids(self) -> tuple[str, ...]:
        return tuple(item.theorem_id for item in self.theorems)

    @property
    def by_id(self) -> dict[str, TheoremRecord]:
        return {item.theorem_id: item for item in self.theorems}

    @property
    def dependents(self) -> dict[str, tuple[str, ...]]:
        edges: dict[str, set[str]] = {item.theorem_id: set() for item in self.theorems}
        for theorem in self.theorems:
            for premise in theorem.premise_ids:
                edges[premise].add(theorem.theorem_id)
        return {key: tuple(sorted(value)) for key, value in edges.items()}

    @property
    def adjacency(self) -> dict[str, set[str]]:
        return {key: set(value) for key, value in self.dependents.items()}

    @property
    def sccs(self) -> tuple[tuple[str, ...], ...]:
        return _tarjan_sccs(set(self.theorem_ids), self.adjacency)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "schema": self.schema,
            "theorems": [item.to_dict() for item in self.theorems],
        }

    @property
    def graph_cid(self) -> str:
        return canonical_identity(
            self.identity_payload(),
            domain="logic.software-verification.theorem-dependency-graph",
            schema_version=self.schema,
        ).cid

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["graph_cid"] = self.graph_cid
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TheoremDependencyGraph:
        if not isinstance(value, Mapping):
            raise ObligationSlicingError("theorem graph must be a mapping")
        payload = dict(value)
        payload.pop("graph_cid", None)
        closed = _closed(payload, cls._FIELDS, cls.__name__)
        closed["theorems"] = tuple(closed["theorems"])
        return cls(**closed)


@dataclass(frozen=True, slots=True)
class ObligationSliceBinding:
    """Dependency surface of one proof obligation relative to the slice."""

    obligation_id: str
    statement_identity: str
    theorem_ids: tuple[str, ...] = ()
    producing_stage: CompilationStage | str = CompilationStage.VC
    source_node_ids: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = ()
    stage_receipt_id: str = ""
    schema: str = OBLIGATION_SLICE_BINDING_SCHEMA

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "assumption_ids",
            "obligation_id",
            "producing_stage",
            "schema",
            "source_node_ids",
            "stage_receipt_id",
            "statement_identity",
            "theorem_ids",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "obligation_id", _text(self.obligation_id, "obligation_id"))
        object.__setattr__(
            self, "statement_identity", _text(self.statement_identity, "statement_identity")
        )
        object.__setattr__(self, "theorem_ids", _unique_texts(self.theorem_ids, "theorem_ids"))
        object.__setattr__(self, "producing_stage", _stage(self.producing_stage, "producing_stage"))
        object.__setattr__(
            self, "source_node_ids", _unique_texts(self.source_node_ids, "source_node_ids")
        )
        object.__setattr__(
            self, "assumption_ids", _unique_texts(self.assumption_ids, "assumption_ids")
        )
        object.__setattr__(
            self, "stage_receipt_id", _optional_text(self.stage_receipt_id, "stage_receipt_id")
        )
        if self.schema != OBLIGATION_SLICE_BINDING_SCHEMA:
            raise ObligationSlicingError("unsupported obligation slice binding schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "obligation_id": self.obligation_id,
            "producing_stage": cast(CompilationStage, self.producing_stage).value,
            "schema": self.schema,
            "source_node_ids": list(self.source_node_ids),
            "stage_receipt_id": self.stage_receipt_id,
            "statement_identity": self.statement_identity,
            "theorem_ids": list(self.theorem_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ObligationSliceBinding:
        payload = _closed(value, cls._FIELDS, cls.__name__)
        payload["theorem_ids"] = tuple(payload["theorem_ids"])
        payload["source_node_ids"] = tuple(payload["source_node_ids"])
        payload["assumption_ids"] = tuple(payload["assumption_ids"])
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class LocalMutation:
    """Exact local change selectors that seed the invalidation frontier."""

    mutation_id: str
    changed_source_node_ids: tuple[str, ...] = ()
    changed_stage_ids: tuple[str, ...] = ()
    changed_theorem_ids: tuple[str, ...] = ()
    changed_obligation_ids: tuple[str, ...] = ()
    changed_content_identities: tuple[str, ...] = ()
    changed_compiler_ids: tuple[str, ...] = ()
    schema: str = LOCAL_MUTATION_SCHEMA

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "changed_compiler_ids",
            "changed_content_identities",
            "changed_obligation_ids",
            "changed_source_node_ids",
            "changed_stage_ids",
            "changed_theorem_ids",
            "mutation_id",
            "schema",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "mutation_id", _text(self.mutation_id, "mutation_id"))
        object.__setattr__(
            self,
            "changed_source_node_ids",
            _unique_texts(self.changed_source_node_ids, "changed_source_node_ids"),
        )
        stages = _stages(self.changed_stage_ids, "changed_stage_ids")
        object.__setattr__(self, "changed_stage_ids", tuple(item.value for item in stages))
        object.__setattr__(
            self,
            "changed_theorem_ids",
            _unique_texts(self.changed_theorem_ids, "changed_theorem_ids"),
        )
        object.__setattr__(
            self,
            "changed_obligation_ids",
            _unique_texts(self.changed_obligation_ids, "changed_obligation_ids"),
        )
        object.__setattr__(
            self,
            "changed_content_identities",
            _unique_texts(self.changed_content_identities, "changed_content_identities"),
        )
        object.__setattr__(
            self,
            "changed_compiler_ids",
            _unique_texts(self.changed_compiler_ids, "changed_compiler_ids"),
        )
        if self.schema != LOCAL_MUTATION_SCHEMA:
            raise ObligationSlicingError("unsupported local mutation schema")

    @property
    def changed_stages(self) -> tuple[CompilationStage, ...]:
        return tuple(CompilationStage(item) for item in self.changed_stage_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed_compiler_ids": list(self.changed_compiler_ids),
            "changed_content_identities": list(self.changed_content_identities),
            "changed_obligation_ids": list(self.changed_obligation_ids),
            "changed_source_node_ids": list(self.changed_source_node_ids),
            "changed_stage_ids": list(self.changed_stage_ids),
            "changed_theorem_ids": list(self.changed_theorem_ids),
            "mutation_id": self.mutation_id,
            "schema": self.schema,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> LocalMutation:
        payload = _closed(value, cls._FIELDS, cls.__name__)
        for name in (
            "changed_compiler_ids",
            "changed_content_identities",
            "changed_obligation_ids",
            "changed_source_node_ids",
            "changed_stage_ids",
            "changed_theorem_ids",
        ):
            payload[name] = tuple(payload[name])
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class ObligationEvidenceRequest:
    """Prior evidence paired with a freshly derived complete cache key."""

    binding_id: str
    kind: SliceSubjectKind | str
    subject_ids: tuple[str, ...]
    artifact_cid: str
    cache_key: CanonicalProofCacheKey
    current_cache_key: CanonicalProofCacheKey
    dependency_ids: tuple[str, ...] = ()
    producing_stage: CompilationStage | str | None = None
    confidence: AnalysisConfidence | str = AnalysisConfidence.EXACT
    dynamic_frontier: bool = False
    schema: str = OBLIGATION_EVIDENCE_REQUEST_SCHEMA

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "artifact_cid",
            "binding_id",
            "cache_key",
            "confidence",
            "current_cache_key",
            "dependency_ids",
            "dynamic_frontier",
            "kind",
            "producing_stage",
            "schema",
            "subject_ids",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_id", _text(self.binding_id, "binding_id"))
        object.__setattr__(self, "kind", _enum(self.kind, SliceSubjectKind, "kind"))
        object.__setattr__(
            self, "subject_ids", _unique_texts(self.subject_ids, "subject_ids", nonempty=True)
        )
        object.__setattr__(self, "artifact_cid", _cid(self.artifact_cid, "artifact_cid"))
        object.__setattr__(self, "cache_key", _cache_key(self.cache_key, "cache_key"))
        object.__setattr__(
            self, "current_cache_key", _cache_key(self.current_cache_key, "current_cache_key")
        )
        object.__setattr__(
            self, "dependency_ids", _unique_texts(self.dependency_ids, "dependency_ids")
        )
        if self.producing_stage in (None, ""):
            object.__setattr__(self, "producing_stage", None)
        else:
            object.__setattr__(
                self, "producing_stage", _stage(self.producing_stage, "producing_stage")
            )
        object.__setattr__(
            self, "confidence", _enum(self.confidence, AnalysisConfidence, "confidence")
        )
        object.__setattr__(self, "dynamic_frontier", _bool(self.dynamic_frontier, "dynamic_frontier"))
        if self.schema != OBLIGATION_EVIDENCE_REQUEST_SCHEMA:
            raise ObligationSlicingError("unsupported obligation evidence request schema")

    def to_dict(self) -> dict[str, Any]:
        stage = self.producing_stage
        return {
            "artifact_cid": self.artifact_cid,
            "binding_id": self.binding_id,
            "cache_key": self.cache_key.to_dict(),
            "confidence": cast(AnalysisConfidence, self.confidence).value,
            "current_cache_key": self.current_cache_key.to_dict(),
            "dependency_ids": list(self.dependency_ids),
            "dynamic_frontier": self.dynamic_frontier,
            "kind": cast(SliceSubjectKind, self.kind).value,
            "producing_stage": None if stage is None else cast(CompilationStage, stage).value,
            "schema": self.schema,
            "subject_ids": list(self.subject_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ObligationEvidenceRequest:
        payload = _closed(value, cls._FIELDS, cls.__name__)
        payload["subject_ids"] = tuple(payload["subject_ids"])
        payload["dependency_ids"] = tuple(payload["dependency_ids"])
        payload["cache_key"] = CanonicalProofCacheKey.from_dict(payload["cache_key"])
        payload["current_cache_key"] = CanonicalProofCacheKey.from_dict(
            payload["current_cache_key"]
        )
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class SourceNodeCone:
    """Source-map projection of a local node mutation through the pipeline."""

    seeds: tuple[str, ...]
    stage_hits: tuple[tuple[str, tuple[str, ...]], ...]
    node_ids: tuple[str, ...]
    schema: str = SOURCE_NODE_CONE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "seeds", _unique_texts(self.seeds, "seeds"))
        if not isinstance(self.stage_hits, tuple):
            raise ObligationSlicingError("stage_hits must be a tuple")
        normalized: list[tuple[str, tuple[str, ...]]] = []
        seen_stages: set[str] = set()
        for item in self.stage_hits:
            if not isinstance(item, tuple) or len(item) != 2:
                raise ObligationSlicingError("stage_hits items must be (stage, nodes) pairs")
            stage = _stage(item[0], "stage_hits stage").value
            if stage in seen_stages:
                raise ObligationSlicingError("stage_hits must not repeat a stage")
            seen_stages.add(stage)
            nodes = _unique_texts(item[1], "stage_hits nodes")
            normalized.append((stage, nodes))
        object.__setattr__(
            self, "stage_hits", tuple(sorted(normalized, key=lambda item: stage_index(item[0])))
        )
        object.__setattr__(self, "node_ids", _unique_texts(self.node_ids, "node_ids"))
        if self.schema != SOURCE_NODE_CONE_SCHEMA:
            raise ObligationSlicingError("unsupported source-node cone schema")

    @property
    def stages(self) -> tuple[CompilationStage, ...]:
        return tuple(CompilationStage(item[0]) for item in self.stage_hits)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_ids": list(self.node_ids),
            "schema": self.schema,
            "seeds": list(self.seeds),
            "stage_hits": [[stage, list(nodes)] for stage, nodes in self.stage_hits],
        }


@dataclass(frozen=True, slots=True)
class StageSliceDecision:
    """Replay or invalidation decision for one compilation stage."""

    stage: CompilationStage | str
    receipt_id: str
    disposition: SliceDisposition | str
    reason_codes: tuple[str, ...]
    reproduced: bool
    authority_ceiling: str
    change_cone_node_ids: tuple[str, ...] = ()
    schema: str = STAGE_SLICE_DECISION_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage", _stage(self.stage, "stage"))
        object.__setattr__(self, "receipt_id", _text(self.receipt_id, "receipt_id"))
        object.__setattr__(
            self, "disposition", _enum(self.disposition, SliceDisposition, "disposition")
        )
        object.__setattr__(
            self, "reason_codes", _unique_texts(self.reason_codes, "reason_codes", nonempty=True)
        )
        object.__setattr__(self, "reproduced", _bool(self.reproduced, "reproduced"))
        object.__setattr__(
            self, "authority_ceiling", _text(self.authority_ceiling, "authority_ceiling")
        )
        object.__setattr__(
            self,
            "change_cone_node_ids",
            _unique_texts(self.change_cone_node_ids, "change_cone_node_ids"),
        )
        if self.schema != STAGE_SLICE_DECISION_SCHEMA:
            raise ObligationSlicingError("unsupported stage slice decision schema")
        if self.disposition is SliceDisposition.REPLAYED and not self.reproduced:
            raise ObligationSlicingError("replayed stages must have reproduced=true")
        if self.disposition is SliceDisposition.INVALIDATED and self.reproduced:
            raise ObligationSlicingError("invalidated stages cannot claim reproduction")

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling,
            "change_cone_node_ids": list(self.change_cone_node_ids),
            "disposition": cast(SliceDisposition, self.disposition).value,
            "reason_codes": list(self.reason_codes),
            "receipt_id": self.receipt_id,
            "reproduced": self.reproduced,
            "schema": self.schema,
            "stage": cast(CompilationStage, self.stage).value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> StageSliceDecision:
        payload = _closed(
            value,
            frozenset(
                {
                    "authority_ceiling",
                    "change_cone_node_ids",
                    "disposition",
                    "reason_codes",
                    "receipt_id",
                    "reproduced",
                    "schema",
                    "stage",
                }
            ),
            cls.__name__,
        )
        payload["reason_codes"] = tuple(payload["reason_codes"])
        payload["change_cone_node_ids"] = tuple(payload["change_cone_node_ids"])
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class TheoremSliceDecision:
    """Theorem-granularity reuse or invalidation decision."""

    theorem_id: str
    disposition: SliceDisposition | str
    reason_codes: tuple[str, ...]
    producing_stage: CompilationStage | str
    dependent_ids: tuple[str, ...] = ()
    schema: str = THEOREM_SLICE_DECISION_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "theorem_id", _text(self.theorem_id, "theorem_id"))
        object.__setattr__(
            self, "disposition", _enum(self.disposition, SliceDisposition, "disposition")
        )
        object.__setattr__(
            self, "reason_codes", _unique_texts(self.reason_codes, "reason_codes", nonempty=True)
        )
        object.__setattr__(self, "producing_stage", _stage(self.producing_stage, "producing_stage"))
        object.__setattr__(self, "dependent_ids", _unique_texts(self.dependent_ids, "dependent_ids"))
        if self.disposition is SliceDisposition.REPLAYED:
            raise ObligationSlicingError("theorems are reused or invalidated, not replayed")
        if self.schema != THEOREM_SLICE_DECISION_SCHEMA:
            raise ObligationSlicingError("unsupported theorem slice decision schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "dependent_ids": list(self.dependent_ids),
            "disposition": cast(SliceDisposition, self.disposition).value,
            "producing_stage": cast(CompilationStage, self.producing_stage).value,
            "reason_codes": list(self.reason_codes),
            "schema": self.schema,
            "theorem_id": self.theorem_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TheoremSliceDecision:
        payload = _closed(
            value,
            frozenset(
                {
                    "dependent_ids",
                    "disposition",
                    "producing_stage",
                    "reason_codes",
                    "schema",
                    "theorem_id",
                }
            ),
            cls.__name__,
        )
        payload["reason_codes"] = tuple(payload["reason_codes"])
        payload["dependent_ids"] = tuple(payload["dependent_ids"])
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class ObligationSliceDecision:
    """Obligation-granularity reuse or invalidation decision."""

    obligation_id: str
    disposition: SliceDisposition | str
    reason_codes: tuple[str, ...]
    producing_stage: CompilationStage | str
    theorem_ids: tuple[str, ...] = ()
    schema: str = OBLIGATION_SLICE_DECISION_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "obligation_id", _text(self.obligation_id, "obligation_id"))
        object.__setattr__(
            self, "disposition", _enum(self.disposition, SliceDisposition, "disposition")
        )
        object.__setattr__(
            self, "reason_codes", _unique_texts(self.reason_codes, "reason_codes", nonempty=True)
        )
        object.__setattr__(self, "producing_stage", _stage(self.producing_stage, "producing_stage"))
        object.__setattr__(self, "theorem_ids", _unique_texts(self.theorem_ids, "theorem_ids"))
        if self.disposition is SliceDisposition.REPLAYED:
            raise ObligationSlicingError("obligations are reused or invalidated, not replayed")
        if self.schema != OBLIGATION_SLICE_DECISION_SCHEMA:
            raise ObligationSlicingError("unsupported obligation slice decision schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "disposition": cast(SliceDisposition, self.disposition).value,
            "obligation_id": self.obligation_id,
            "producing_stage": cast(CompilationStage, self.producing_stage).value,
            "reason_codes": list(self.reason_codes),
            "schema": self.schema,
            "theorem_ids": list(self.theorem_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ObligationSliceDecision:
        payload = _closed(
            value,
            frozenset(
                {
                    "disposition",
                    "obligation_id",
                    "producing_stage",
                    "reason_codes",
                    "schema",
                    "theorem_ids",
                }
            ),
            cls.__name__,
        )
        payload["reason_codes"] = tuple(payload["reason_codes"])
        payload["theorem_ids"] = tuple(payload["theorem_ids"])
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class EvidenceRevalidationDecision:
    """Independent cache-key revalidation of one reusable evidence binding."""

    binding_id: str
    kind: SliceSubjectKind | str
    artifact_cid: str
    disposition: SliceDisposition | str
    reason_codes: tuple[str, ...]
    admitted_cache_key_id: str
    evidence_kind: str
    authority_ceiling: str
    schema: str = EVIDENCE_REVALIDATION_DECISION_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_id", _text(self.binding_id, "binding_id"))
        object.__setattr__(self, "kind", _enum(self.kind, SliceSubjectKind, "kind"))
        object.__setattr__(self, "artifact_cid", _cid(self.artifact_cid, "artifact_cid"))
        object.__setattr__(
            self, "disposition", _enum(self.disposition, SliceDisposition, "disposition")
        )
        object.__setattr__(
            self, "reason_codes", _unique_texts(self.reason_codes, "reason_codes", nonempty=True)
        )
        object.__setattr__(
            self, "admitted_cache_key_id", _text(self.admitted_cache_key_id, "admitted_cache_key_id")
        )
        object.__setattr__(self, "evidence_kind", _text(self.evidence_kind, "evidence_kind"))
        object.__setattr__(
            self, "authority_ceiling", _text(self.authority_ceiling, "authority_ceiling")
        )
        if self.disposition is SliceDisposition.REPLAYED:
            raise ObligationSlicingError("evidence is reused or invalidated, not replayed")
        if self.schema != EVIDENCE_REVALIDATION_DECISION_SCHEMA:
            raise ObligationSlicingError("unsupported evidence revalidation schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted_cache_key_id": self.admitted_cache_key_id,
            "artifact_cid": self.artifact_cid,
            "authority_ceiling": self.authority_ceiling,
            "binding_id": self.binding_id,
            "disposition": cast(SliceDisposition, self.disposition).value,
            "evidence_kind": self.evidence_kind,
            "kind": cast(SliceSubjectKind, self.kind).value,
            "reason_codes": list(self.reason_codes),
            "schema": self.schema,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> EvidenceRevalidationDecision:
        payload = _closed(
            value,
            frozenset(
                {
                    "admitted_cache_key_id",
                    "artifact_cid",
                    "authority_ceiling",
                    "binding_id",
                    "disposition",
                    "evidence_kind",
                    "kind",
                    "reason_codes",
                    "schema",
                }
            ),
            cls.__name__,
        )
        payload["reason_codes"] = tuple(payload["reason_codes"])
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class ObligationSliceReceipt:
    """Content-addressed result of one exact obligation-slicing operation."""

    mutation_id: str
    previous_pipeline_id: str
    current_pipeline_id: str
    previous_pipeline_receipt_id: str
    current_pipeline_receipt_id: str
    theorem_graph_cid: str
    invalidated_stage_ids: tuple[str, ...]
    replayed_stage_ids: tuple[str, ...]
    invalidated_theorem_ids: tuple[str, ...]
    reused_theorem_ids: tuple[str, ...]
    invalidated_obligation_ids: tuple[str, ...]
    reused_obligation_ids: tuple[str, ...]
    affected_sccs: tuple[tuple[str, ...], ...]
    source_node_cone: SourceNodeCone
    stage_decisions: tuple[StageSliceDecision, ...]
    theorem_decisions: tuple[TheoremSliceDecision, ...]
    obligation_decisions: tuple[ObligationSliceDecision, ...]
    evidence_decisions: tuple[EvidenceRevalidationDecision, ...]
    authority_ceiling: str
    limitations: tuple[str, ...]
    schema: str = OBLIGATION_SLICE_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "mutation_id", _text(self.mutation_id, "mutation_id"))
        object.__setattr__(
            self, "previous_pipeline_id", _text(self.previous_pipeline_id, "previous_pipeline_id")
        )
        object.__setattr__(
            self,
            "current_pipeline_id",
            _optional_text(self.current_pipeline_id, "current_pipeline_id"),
        )
        object.__setattr__(
            self,
            "previous_pipeline_receipt_id",
            _text(self.previous_pipeline_receipt_id, "previous_pipeline_receipt_id"),
        )
        object.__setattr__(
            self,
            "current_pipeline_receipt_id",
            _optional_text(self.current_pipeline_receipt_id, "current_pipeline_receipt_id"),
        )
        object.__setattr__(
            self, "theorem_graph_cid", _text(self.theorem_graph_cid, "theorem_graph_cid")
        )
        object.__setattr__(
            self,
            "invalidated_stage_ids",
            tuple(item.value for item in _stages(self.invalidated_stage_ids, "invalidated_stage_ids")),
        )
        object.__setattr__(
            self,
            "replayed_stage_ids",
            tuple(item.value for item in _stages(self.replayed_stage_ids, "replayed_stage_ids")),
        )
        for name in (
            "invalidated_theorem_ids",
            "reused_theorem_ids",
            "invalidated_obligation_ids",
            "reused_obligation_ids",
            "limitations",
        ):
            object.__setattr__(self, name, _unique_texts(getattr(self, name), name))
        overlap = set(self.invalidated_stage_ids) & set(self.replayed_stage_ids)
        if overlap:
            raise ObligationSlicingError(
                f"stages cannot be both invalidated and replayed: {sorted(overlap)}"
            )
        theorem_overlap = set(self.invalidated_theorem_ids) & set(self.reused_theorem_ids)
        if theorem_overlap:
            raise ObligationSlicingError(
                f"theorems cannot be both invalidated and reused: {sorted(theorem_overlap)}"
            )
        obligation_overlap = set(self.invalidated_obligation_ids) & set(self.reused_obligation_ids)
        if obligation_overlap:
            raise ObligationSlicingError(
                f"obligations cannot be both invalidated and reused: {sorted(obligation_overlap)}"
            )
        sccs = tuple(sorted(tuple(sorted(item)) for item in self.affected_sccs))
        if any(not item for item in sccs) or len(sccs) != len(set(sccs)):
            raise ObligationSlicingError("affected_sccs must be unique and non-empty")
        object.__setattr__(self, "affected_sccs", sccs)
        if not isinstance(self.source_node_cone, SourceNodeCone):
            raise ObligationSlicingError("source_node_cone must be a SourceNodeCone")
        stages = tuple(sorted(self.stage_decisions, key=lambda item: stage_index(item.stage)))
        theorems = tuple(sorted(self.theorem_decisions, key=lambda item: item.theorem_id))
        obligations = tuple(sorted(self.obligation_decisions, key=lambda item: item.obligation_id))
        evidence = tuple(sorted(self.evidence_decisions, key=lambda item: item.binding_id))
        if any(not isinstance(item, StageSliceDecision) for item in stages):
            raise ObligationSlicingError("stage_decisions must contain StageSliceDecision values")
        if any(not isinstance(item, TheoremSliceDecision) for item in theorems):
            raise ObligationSlicingError("theorem_decisions must contain TheoremSliceDecision values")
        if any(not isinstance(item, ObligationSliceDecision) for item in obligations):
            raise ObligationSlicingError(
                "obligation_decisions must contain ObligationSliceDecision values"
            )
        if any(not isinstance(item, EvidenceRevalidationDecision) for item in evidence):
            raise ObligationSlicingError(
                "evidence_decisions must contain EvidenceRevalidationDecision values"
            )
        if len({item.binding_id for item in evidence}) != len(evidence):
            raise ObligationSlicingError("evidence decision binding IDs must be unique")
        object.__setattr__(self, "stage_decisions", stages)
        object.__setattr__(self, "theorem_decisions", theorems)
        object.__setattr__(self, "obligation_decisions", obligations)
        object.__setattr__(self, "evidence_decisions", evidence)
        object.__setattr__(
            self, "authority_ceiling", _text(self.authority_ceiling, "authority_ceiling")
        )
        if self.schema != OBLIGATION_SLICE_RECEIPT_SCHEMA:
            raise ObligationSlicingError("unsupported obligation slice receipt schema")

    @property
    def reused_evidence_binding_ids(self) -> tuple[str, ...]:
        return tuple(
            item.binding_id
            for item in self.evidence_decisions
            if item.disposition is SliceDisposition.REUSED
        )

    @property
    def invalidated_evidence_binding_ids(self) -> tuple[str, ...]:
        return tuple(
            item.binding_id
            for item in self.evidence_decisions
            if item.disposition is SliceDisposition.INVALIDATED
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "affected_sccs": [list(item) for item in self.affected_sccs],
            "authority_ceiling": self.authority_ceiling,
            "current_pipeline_id": self.current_pipeline_id,
            "current_pipeline_receipt_id": self.current_pipeline_receipt_id,
            "evidence_decisions": [item.to_dict() for item in self.evidence_decisions],
            "interface": OBLIGATION_SLICING_INTERFACE,
            "invalidated_obligation_ids": list(self.invalidated_obligation_ids),
            "invalidated_stage_ids": list(self.invalidated_stage_ids),
            "invalidated_theorem_ids": list(self.invalidated_theorem_ids),
            "limitations": list(self.limitations),
            "mutation_id": self.mutation_id,
            "obligation_decisions": [item.to_dict() for item in self.obligation_decisions],
            "previous_pipeline_id": self.previous_pipeline_id,
            "previous_pipeline_receipt_id": self.previous_pipeline_receipt_id,
            "replayed_stage_ids": list(self.replayed_stage_ids),
            "reused_obligation_ids": list(self.reused_obligation_ids),
            "reused_theorem_ids": list(self.reused_theorem_ids),
            "schema": self.schema,
            "source_node_cone": self.source_node_cone.to_dict(),
            "stage_decisions": [item.to_dict() for item in self.stage_decisions],
            "theorem_decisions": [item.to_dict() for item in self.theorem_decisions],
            "theorem_graph_cid": self.theorem_graph_cid,
        }

    @property
    def receipt_cid(self) -> str:
        return canonical_identity(
            self.identity_payload(),
            domain="logic.software-verification.obligation-slice-receipt",
            schema_version=self.schema,
        ).cid

    def to_dict(self) -> dict[str, Any]:
        result = self.identity_payload()
        result["receipt_cid"] = self.receipt_cid
        result["invalidated_evidence_binding_ids"] = list(self.invalidated_evidence_binding_ids)
        result["reused_evidence_binding_ids"] = list(self.reused_evidence_binding_ids)
        return result


def propagate_changed_source_nodes(
    stages: Sequence[StageTranslationReceipt],
    seeds: Sequence[str],
) -> SourceNodeCone:
    """Project mutated source nodes through adjacent stage source maps.

    A stage is in the cone only when one of its mapped source nodes is a seed
    or a previously produced target.  Unmapped seeds persist so a later stage
    can still observe them; they do not silently mark the current stage.
    """

    if isinstance(stages, (str, bytes, bytearray)) or not isinstance(stages, Sequence):
        raise ObligationSlicingError("stages must be a sequence of StageTranslationReceipt values")
    receipts = tuple(stages)
    if any(not isinstance(item, StageTranslationReceipt) for item in receipts):
        raise ObligationSlicingError("stages must contain StageTranslationReceipt values")
    seed_ids = _unique_texts(seeds, "seeds")
    remaining = set(seed_ids)
    hits: list[tuple[str, tuple[str, ...]]] = []
    observed = set(remaining)
    for receipt in receipts:
        mapped = set(receipt.source_map.source_node_ids)
        hit = tuple(sorted(remaining & mapped))
        produced: set[str] = set()
        for entry in receipt.source_map.entries:
            if entry.source_node_id in remaining:
                produced.update(entry.target_node_ids)
        if hit:
            hits.append((receipt.output.stage.value, hit))
        remaining = produced | (remaining - mapped)
        observed.update(produced)
        observed.update(hit)
    return SourceNodeCone(
        seeds=seed_ids,
        stage_hits=tuple(hits),
        node_ids=tuple(sorted(observed)),
    )


def close_theorem_dependents(
    graph: TheoremDependencyGraph,
    seeds: Sequence[str],
) -> tuple[str, ...]:
    """Close *seeds* over reverse theorem dependents and touched cyclic SCCs."""

    if not isinstance(graph, TheoremDependencyGraph):
        raise ObligationSlicingError("graph must be a TheoremDependencyGraph")
    seed_ids = _unique_texts(seeds, "seeds")
    dependents = graph.dependents
    affected: set[str] = set(seed_ids)
    queue: deque[str] = deque(sorted(affected))
    seen = set(affected)
    while queue:
        node = queue.popleft()
        for dependent in dependents.get(node, ()):
            if dependent not in seen:
                seen.add(dependent)
                affected.add(dependent)
                queue.append(dependent)
    changed = True
    while changed:
        changed = False
        for scc in graph.sccs:
            if affected.intersection(scc) and not set(scc) <= affected:
                affected.update(scc)
                changed = True
    return tuple(sorted(affected))


def _downstream_stages(start: CompilationStage) -> tuple[CompilationStage, ...]:
    result: list[CompilationStage] = []
    current: CompilationStage | None = start
    while current is not None:
        nxt = stage_successor(current)
        if nxt is None:
            break
        result.append(nxt)
        current = nxt
    return tuple(result)


def _wholesale_stage_reasons(
    receipt: StageTranslationReceipt,
    mutation: LocalMutation,
    changed_identities: set[str],
) -> set[str]:
    reasons: set[str] = set()
    output_stage = receipt.output.stage
    if output_stage.value in mutation.changed_stage_ids:
        reasons.add("mutated_stage")
    if receipt.compiler.compiler_id in mutation.changed_compiler_ids:
        reasons.add("mutated_compiler")
    if receipt.compiler.binding_id in mutation.changed_compiler_ids:
        reasons.add("mutated_compiler")
    identities = {
        receipt.input.content_identity,
        receipt.output.content_identity,
        receipt.compiler.binding_id,
        receipt.compiler.implementation_identity,
        receipt.source_map.identity.cid,
        receipt.receipt_id,
    }
    if identities & changed_identities:
        reasons.add("mutated_content_identity")
    return reasons


def classify_translation_stages(
    previous_pipeline: CompilationPipelineReceipt,
    mutation: LocalMutation,
    *,
    current_pipeline: CompilationPipelineReceipt | None = None,
    cone: SourceNodeCone | None = None,
    stage_expectations: Mapping[str, StageReceiptExpectation] | None = None,
) -> tuple[StageSliceDecision, ...]:
    """Classify each previous stage as independently replayed or invalidated.

    When a current pipeline is supplied, receipt identity is authoritative:
    identical receipts are replayed even if a source-map cone touches the
    stage.  Without a current pipeline, a node-cone hit or a wholesale
    compiler/stage mutation invalidates the stage, and wholesale mutations
    also invalidate every downstream stage.
    """

    previous = _pipeline(previous_pipeline, "previous_pipeline")
    if not isinstance(mutation, LocalMutation):
        raise ObligationSlicingError("mutation must be a LocalMutation")
    current = None if current_pipeline is None else _pipeline(current_pipeline, "current_pipeline")
    if current is not None and current.source_identity != previous.source_identity:
        if current.source_identity not in mutation.changed_content_identities and (
            not mutation.changed_source_node_ids and not mutation.changed_stage_ids
        ):
            raise ObligationSlicingStaleError(
                "current pipeline source_identity differs without a matching mutation"
            )
    previous_by_output = _stage_by_output(previous)
    current_by_output = {} if current is None else _stage_by_output(current)
    if cone is None:
        cone = propagate_changed_source_nodes(previous.stages, mutation.changed_source_node_ids)
    cone_stages = set(cone.stages)
    cone_nodes_by_stage = {stage: nodes for stage, nodes in cone.stage_hits}
    changed_identities = set(mutation.changed_content_identities)
    expectations = {} if stage_expectations is None else dict(stage_expectations)

    wholesale: set[CompilationStage] = set()
    for receipt in previous.stages:
        if _wholesale_stage_reasons(receipt, mutation, changed_identities):
            wholesale.add(receipt.output.stage)
            wholesale.update(_downstream_stages(receipt.output.stage))
    if current is not None:
        for stage, previous_receipt in previous_by_output.items():
            current_receipt = current_by_output.get(stage)
            if current_receipt is None or current_receipt.receipt_id != previous_receipt.receipt_id:
                wholesale.add(stage)
        for stage in current_by_output:
            if stage not in previous_by_output:
                wholesale.add(stage)

    decisions: list[StageSliceDecision] = []
    seen_outputs = set(previous_by_output) | set(current_by_output)
    for stage in STAGE_ORDER:
        if stage is CompilationStage.SOURCE:
            continue
        if stage not in seen_outputs and stage.value not in mutation.changed_stage_ids:
            continue
        previous_receipt = previous_by_output.get(stage)
        current_receipt = current_by_output.get(stage)
        receipt = current_receipt or previous_receipt
        reasons: set[str] = set()
        if receipt is None:
            decisions.append(
                StageSliceDecision(
                    stage=stage,
                    receipt_id=f"missing:{stage.value}",
                    disposition=SliceDisposition.INVALIDATED,
                    reason_codes=("added_or_removed", "mutated_stage"),
                    reproduced=False,
                    authority_ceiling=EvidenceAuthority.NONE.value,
                )
            )
            continue
        cone_nodes = cone_nodes_by_stage.get(stage.value, ())
        if previous_receipt is None or current is not None and current_receipt is None:
            reasons.add("added_or_removed")
        if current is not None and previous_receipt is not None and current_receipt is not None:
            if previous_receipt.receipt_id != current_receipt.receipt_id:
                reasons.add("stage_receipt_changed")
            if (
                previous_receipt.input.content_identity != current_receipt.input.content_identity
                or previous_receipt.output.content_identity != current_receipt.output.content_identity
            ):
                reasons.add("stage_identity_changed")
        if previous_receipt is not None:
            reasons.update(_wholesale_stage_reasons(previous_receipt, mutation, changed_identities))
        if current is None and stage in cone_stages:
            reasons.add("source_map_change_cone")
        if current is None and stage in wholesale and "mutated_stage" not in reasons:
            if any(
                _wholesale_stage_reasons(item, mutation, changed_identities)
                for item in previous.stages
                if stage_index(item.output.stage) < stage_index(stage)
            ):
                reasons.add("downstream_stage_invalidated")
        if stage.value in mutation.changed_stage_ids:
            reasons.add("mutated_stage")

        expectation: StageReceiptExpectation | None = None
        if stage.value in expectations:
            expectation = expectations[stage.value]
        elif current_receipt is not None:
            expectation = StageReceiptExpectation.from_receipt(current_receipt)
        elif previous_receipt is not None:
            expectation = StageReceiptExpectation.from_receipt(previous_receipt)

        replayed = False
        reproduced = False
        if not reasons and previous_receipt is not None and expectation is not None:
            replay = replay_stage_receipt(previous_receipt, expectation)
            if replay.reproduced:
                replayed = True
                reproduced = True
                reasons.add("independent_stage_replay")
            else:
                reasons.add("replay_failed")

        if replayed:
            decisions.append(
                StageSliceDecision(
                    stage=stage,
                    receipt_id=previous_receipt.receipt_id,
                    disposition=SliceDisposition.REPLAYED,
                    reason_codes=tuple(sorted(reasons)),
                    reproduced=True,
                    authority_ceiling=previous_receipt.authority_ceiling.value,
                    change_cone_node_ids=cone_nodes,
                )
            )
            continue
        if not reasons:
            reasons.add("stage_not_reproducible")
        decisions.append(
            StageSliceDecision(
                stage=stage,
                receipt_id=receipt.receipt_id,
                disposition=SliceDisposition.INVALIDATED,
                reason_codes=tuple(sorted(reasons)),
                reproduced=False,
                authority_ceiling=EvidenceAuthority.NONE.value,
                change_cone_node_ids=cone_nodes,
            )
        )
    return tuple(sorted(decisions, key=lambda item: stage_index(item.stage)))


def _direct_theorem_reasons(
    theorem: TheoremRecord,
    mutation: LocalMutation,
    cone_nodes: set[str],
    fully_invalidated_stages: set[CompilationStage],
) -> set[str]:
    reasons: set[str] = set()
    if theorem.theorem_id in mutation.changed_theorem_ids:
        reasons.add("mutated_theorem")
    if theorem.statement_identity in mutation.changed_content_identities:
        reasons.add("mutated_content_identity")
    if theorem.content_identity in mutation.changed_content_identities:
        reasons.add("mutated_content_identity")
    if set(theorem.source_node_ids) & (set(mutation.changed_source_node_ids) | cone_nodes):
        reasons.add("mutated_source_node")
    producing = cast(CompilationStage, theorem.producing_stage)
    if producing in fully_invalidated_stages:
        reasons.add("producing_stage_invalidated")
    return reasons


def _direct_obligation_reasons(
    obligation: ObligationSliceBinding,
    mutation: LocalMutation,
    cone_nodes: set[str],
    fully_invalidated_stages: set[CompilationStage],
    invalidated_theorems: set[str],
) -> set[str]:
    reasons: set[str] = set()
    if obligation.obligation_id in mutation.changed_obligation_ids:
        reasons.add("mutated_obligation")
    if obligation.statement_identity in mutation.changed_content_identities:
        reasons.add("mutated_content_identity")
    if set(obligation.source_node_ids) & (set(mutation.changed_source_node_ids) | cone_nodes):
        reasons.add("mutated_source_node")
    cited = set(obligation.theorem_ids) & invalidated_theorems
    if cited:
        reasons.add("theorem_dependency_invalidated")
    producing = cast(CompilationStage, obligation.producing_stage)
    if producing in fully_invalidated_stages:
        reasons.add("producing_stage_invalidated")
    if (
        not obligation.theorem_ids
        and not obligation.source_node_ids
        and producing in fully_invalidated_stages
    ):
        reasons.add("underspecified_obligation_follows_stage")
    return reasons


def _revalidate_evidence(
    requests: Sequence[ObligationEvidenceRequest],
    *,
    invalidated_theorems: set[str],
    invalidated_obligations: set[str],
    invalidated_stages: set[CompilationStage],
    fully_invalidated_stages: set[CompilationStage],
    cone_nodes: set[str],
    mutation: LocalMutation,
) -> tuple[EvidenceRevalidationDecision, ...]:
    decisions: list[EvidenceRevalidationDecision] = []
    seen: set[str] = set()
    for request in requests:
        if not isinstance(request, ObligationEvidenceRequest):
            raise ObligationSlicingError(
                "evidence_requests must contain ObligationEvidenceRequest values"
            )
        if request.binding_id in seen:
            raise ObligationSlicingError("evidence binding IDs must be unique")
        seen.add(request.binding_id)
        reasons: set[str] = set()
        subjects = set(request.subject_ids)
        dependencies = set(request.dependency_ids)
        if subjects & invalidated_theorems or dependencies & invalidated_theorems:
            reasons.add("theorem_dependency_invalidated")
        if subjects & invalidated_obligations or dependencies & invalidated_obligations:
            reasons.add("obligation_invalidated")
        changed_theorems = set(mutation.changed_theorem_ids)
        changed_obligations = set(mutation.changed_obligation_ids)
        if subjects & changed_theorems or dependencies & changed_theorems:
            reasons.add("mutated_theorem")
        if subjects & changed_obligations or dependencies & changed_obligations:
            reasons.add("mutated_obligation")
        if subjects & (set(mutation.changed_source_node_ids) | cone_nodes):
            reasons.add("mutated_source_node")
        if dependencies & (set(mutation.changed_source_node_ids) | cone_nodes):
            reasons.add("changed_dependency")
        stage = request.producing_stage
        if isinstance(stage, CompilationStage) and stage in fully_invalidated_stages:
            reasons.add("producing_stage_invalidated")
        for subject in subjects:
            try:
                subject_stage = CompilationStage(subject)
            except ValueError:
                continue
            if subject_stage in invalidated_stages:
                reasons.add("producing_stage_invalidated")
        if request.dynamic_frontier:
            reasons.add("dynamic_frontier")
        if request.confidence is not AnalysisConfidence.EXACT:
            reasons.add("non_exact_evidence")

        admitted_key_id = request.current_cache_key.key_id
        if not reasons:
            try:
                admitted = admit_cache_hit(request.cache_key, request.current_cache_key)
            except CrossEnvironmentHitError:
                reasons.add("cross_environment_hit")
            except CanonicalCacheKeyError:
                reasons.add("cache_key_mismatch")
            else:
                admitted_key_id = admitted.key_id

        disposition = (
            SliceDisposition.INVALIDATED if reasons else SliceDisposition.REUSED
        )
        if not reasons:
            reasons.add("exact_cache_key_revalidated")
        decisions.append(
            EvidenceRevalidationDecision(
                binding_id=request.binding_id,
                kind=request.kind,
                artifact_cid=request.artifact_cid,
                disposition=disposition,
                reason_codes=tuple(sorted(reasons)),
                admitted_cache_key_id=admitted_key_id,
                evidence_kind=request.current_cache_key.evidence_kind.value,
                authority_ceiling=request.current_cache_key.authority_ceiling.value,
            )
        )
    return tuple(sorted(decisions, key=lambda item: item.binding_id))


def slice_and_replay_obligations(
    previous_pipeline: CompilationPipelineReceipt,
    *,
    mutation: LocalMutation,
    theorem_graph: TheoremDependencyGraph,
    obligations: Sequence[ObligationSliceBinding] = (),
    current_pipeline: CompilationPipelineReceipt | None = None,
    evidence_requests: Sequence[ObligationEvidenceRequest] = (),
    stage_expectations: Mapping[str, StageReceiptExpectation] | None = None,
) -> ObligationSliceReceipt:
    """Slice the affected frontier and independently revalidate reusable evidence.

    Local mutations invalidate exactly the touched translation stages, the
    reverse-closed theorem dependents (including cyclic SCCs), and the
    obligations that cite those subjects.  Unchanged stages are replayed
    against current expectations.  Prior evidence is reused only after
    :func:`admit_cache_hit` succeeds on a freshly derived cache key.
    """

    previous = _pipeline(previous_pipeline, "previous_pipeline")
    if not isinstance(mutation, LocalMutation):
        raise ObligationSlicingError("mutation must be a LocalMutation")
    if not isinstance(theorem_graph, TheoremDependencyGraph):
        raise ObligationSlicingError("theorem_graph must be a TheoremDependencyGraph")
    current = None if current_pipeline is None else _pipeline(current_pipeline, "current_pipeline")
    obligation_records = _records(obligations, ObligationSliceBinding, "obligations")
    known_theorems = set(theorem_graph.theorem_ids)
    obligation_ids = [item.obligation_id for item in obligation_records]
    if len(obligation_ids) != len(set(obligation_ids)):
        raise ObligationSlicingError("obligation IDs must be unique")
    for obligation in obligation_records:
        missing = sorted(set(obligation.theorem_ids) - known_theorems)
        if missing:
            raise ObligationSlicingError(
                f"obligation {obligation.obligation_id} cites unknown theorems {missing}"
            )
        cited_by_theorems = {
            theorem.theorem_id
            for theorem in theorem_graph.theorems
            if obligation.obligation_id in theorem.obligation_ids
        }
        if cited_by_theorems and not set(obligation.theorem_ids) >= cited_by_theorems:
            raise ObligationSlicingStaleError(
                f"obligation {obligation.obligation_id} is missing theorem citations "
                f"{sorted(cited_by_theorems - set(obligation.theorem_ids))}"
            )

    cone = propagate_changed_source_nodes(previous.stages, mutation.changed_source_node_ids)
    stage_decisions = classify_translation_stages(
        previous,
        mutation,
        current_pipeline=current,
        cone=cone,
        stage_expectations=stage_expectations,
    )
    invalidated_stages = {
        cast(CompilationStage, item.stage)
        for item in stage_decisions
        if item.disposition is SliceDisposition.INVALIDATED
    }
    replayed_stages = {
        cast(CompilationStage, item.stage)
        for item in stage_decisions
        if item.disposition is SliceDisposition.REPLAYED
    }
    fully_invalidated_stages = {
        cast(CompilationStage, item.stage)
        for item in stage_decisions
        if item.disposition is SliceDisposition.INVALIDATED
        and (
            "stage_receipt_changed" in item.reason_codes
            or "mutated_stage" in item.reason_codes
            or "mutated_compiler" in item.reason_codes
            or "stage_identity_changed" in item.reason_codes
            or "added_or_removed" in item.reason_codes
            or "downstream_stage_invalidated" in item.reason_codes
            or "replay_failed" in item.reason_codes
        )
    }
    cone_nodes = set(cone.node_ids)
    direct_reasons: dict[str, set[str]] = {}
    for theorem in theorem_graph.theorems:
        reasons = _direct_theorem_reasons(
            theorem, mutation, cone_nodes, fully_invalidated_stages
        )
        if reasons:
            direct_reasons[theorem.theorem_id] = reasons
    for theorem_id in mutation.changed_theorem_ids:
        if theorem_id not in known_theorems:
            direct_reasons.setdefault(theorem_id, set()).add("mutated_theorem")

    closed = set(close_theorem_dependents(theorem_graph, tuple(direct_reasons)))
    closed.update(theorem_id for theorem_id in direct_reasons if theorem_id not in known_theorems)
    dependents = theorem_graph.dependents
    theorem_decisions: list[TheoremSliceDecision] = []
    for theorem in theorem_graph.theorems:
        reasons = set(direct_reasons.get(theorem.theorem_id, ()))
        if theorem.theorem_id in closed and theorem.theorem_id not in direct_reasons:
            reasons.add("theorem_dependency_invalidated")
            for scc in theorem_graph.sccs:
                if theorem.theorem_id in scc and set(scc) & set(direct_reasons):
                    reasons.add("scc_closure")
        if theorem.theorem_id in closed:
            theorem_decisions.append(
                TheoremSliceDecision(
                    theorem_id=theorem.theorem_id,
                    disposition=SliceDisposition.INVALIDATED,
                    reason_codes=tuple(sorted(reasons or {"theorem_dependency_invalidated"})),
                    producing_stage=theorem.producing_stage,
                    dependent_ids=dependents.get(theorem.theorem_id, ()),
                )
            )
        else:
            theorem_decisions.append(
                TheoremSliceDecision(
                    theorem_id=theorem.theorem_id,
                    disposition=SliceDisposition.REUSED,
                    reason_codes=("unaffected_theorem",),
                    producing_stage=theorem.producing_stage,
                    dependent_ids=dependents.get(theorem.theorem_id, ()),
                )
            )
    for theorem_id, reasons in sorted(direct_reasons.items()):
        if theorem_id in known_theorems:
            continue
        theorem_decisions.append(
            TheoremSliceDecision(
                theorem_id=theorem_id,
                disposition=SliceDisposition.INVALIDATED,
                reason_codes=tuple(sorted(reasons)),
                producing_stage=CompilationStage.SOURCE,
                dependent_ids=(),
            )
        )

    invalidated_theorems = {
        item.theorem_id
        for item in theorem_decisions
        if item.disposition is SliceDisposition.INVALIDATED
    }
    obligation_decisions: list[ObligationSliceDecision] = []
    for obligation in obligation_records:
        reasons = _direct_obligation_reasons(
            obligation,
            mutation,
            cone_nodes,
            fully_invalidated_stages,
            invalidated_theorems,
        )
        if reasons:
            obligation_decisions.append(
                ObligationSliceDecision(
                    obligation_id=obligation.obligation_id,
                    disposition=SliceDisposition.INVALIDATED,
                    reason_codes=tuple(sorted(reasons)),
                    producing_stage=obligation.producing_stage,
                    theorem_ids=obligation.theorem_ids,
                )
            )
        else:
            obligation_decisions.append(
                ObligationSliceDecision(
                    obligation_id=obligation.obligation_id,
                    disposition=SliceDisposition.REUSED,
                    reason_codes=("unaffected_obligation",),
                    producing_stage=obligation.producing_stage,
                    theorem_ids=obligation.theorem_ids,
                )
            )
    for obligation_id in mutation.changed_obligation_ids:
        if obligation_id in {item.obligation_id for item in obligation_records}:
            continue
        obligation_decisions.append(
            ObligationSliceDecision(
                obligation_id=obligation_id,
                disposition=SliceDisposition.INVALIDATED,
                reason_codes=("mutated_obligation",),
                producing_stage=CompilationStage.SOURCE,
                theorem_ids=(),
            )
        )

    invalidated_obligations = {
        item.obligation_id
        for item in obligation_decisions
        if item.disposition is SliceDisposition.INVALIDATED
    }
    evidence_decisions = _revalidate_evidence(
        evidence_requests,
        invalidated_theorems=invalidated_theorems,
        invalidated_obligations=invalidated_obligations,
        invalidated_stages=invalidated_stages,
        fully_invalidated_stages=fully_invalidated_stages,
        cone_nodes=cone_nodes,
        mutation=mutation,
    )

    limitations: set[str] = set()
    if current is None:
        limitations.add("current_pipeline_unavailable")
    if any("replay_failed" in item.reason_codes for item in stage_decisions):
        limitations.add("unchanged_stage_replay_failed")
    if any("scc_closure" in item.reason_codes for item in theorem_decisions):
        limitations.add("cyclic_theorem_scc_closed")
    if any(item.dynamic_frontier for item in evidence_requests):
        limitations.add("dynamic_frontier_requires_full_revalidation")

    replayed_receipts = [
        receipt
        for receipt in previous.stages
        if receipt.output.stage in replayed_stages
    ]
    if replayed_receipts:
        authority = effective_downstream_authority(replayed_receipts).value
    elif previous.stages:
        authority = EvidenceAuthority.NONE.value
    else:
        authority = EvidenceAuthority.NONE.value

    affected_sccs = tuple(
        scc for scc in theorem_graph.sccs if set(scc) & invalidated_theorems
    )
    return ObligationSliceReceipt(
        mutation_id=mutation.mutation_id,
        previous_pipeline_id=previous.pipeline_id,
        current_pipeline_id="" if current is None else current.pipeline_id,
        previous_pipeline_receipt_id=previous.receipt_id,
        current_pipeline_receipt_id="" if current is None else current.receipt_id,
        theorem_graph_cid=theorem_graph.graph_cid,
        invalidated_stage_ids=tuple(
            sorted((item.value for item in invalidated_stages), key=lambda value: stage_index(value))
        ),
        replayed_stage_ids=tuple(
            sorted((item.value for item in replayed_stages), key=lambda value: stage_index(value))
        ),
        invalidated_theorem_ids=tuple(sorted(invalidated_theorems)),
        reused_theorem_ids=tuple(
            item.theorem_id
            for item in sorted(theorem_decisions, key=lambda item: item.theorem_id)
            if item.disposition is SliceDisposition.REUSED
        ),
        invalidated_obligation_ids=tuple(sorted(invalidated_obligations)),
        reused_obligation_ids=tuple(
            item.obligation_id
            for item in sorted(obligation_decisions, key=lambda item: item.obligation_id)
            if item.disposition is SliceDisposition.REUSED
        ),
        affected_sccs=affected_sccs,
        source_node_cone=cone,
        stage_decisions=tuple(stage_decisions),
        theorem_decisions=tuple(theorem_decisions),
        obligation_decisions=tuple(obligation_decisions),
        evidence_decisions=evidence_decisions,
        authority_ceiling=authority,
        limitations=tuple(sorted(limitations)),
    )


def require_replayed_stages(receipt: ObligationSliceReceipt) -> tuple[StageSliceDecision, ...]:
    """Return replayed stage decisions, raising if any expected replay failed."""

    if not isinstance(receipt, ObligationSliceReceipt):
        raise ObligationSlicingError("receipt must be an ObligationSliceReceipt")
    failed = tuple(
        item
        for item in receipt.stage_decisions
        if "replay_failed" in item.reason_codes
    )
    if failed:
        stages = ", ".join(cast(CompilationStage, item.stage).value for item in failed)
        raise UnchangedStageReplayError(f"unchanged stage replay failed: {stages}")
    return tuple(
        item for item in receipt.stage_decisions if item.disposition is SliceDisposition.REPLAYED
    )


__all__ = [
    "EVIDENCE_REVALIDATION_DECISION_SCHEMA",
    "LOCAL_MUTATION_SCHEMA",
    "OBLIGATION_EVIDENCE_REQUEST_SCHEMA",
    "OBLIGATION_SLICE_BINDING_SCHEMA",
    "OBLIGATION_SLICE_DECISION_SCHEMA",
    "OBLIGATION_SLICE_RECEIPT_SCHEMA",
    "OBLIGATION_SLICING_INTERFACE",
    "SOURCE_NODE_CONE_SCHEMA",
    "STAGE_SLICE_DECISION_SCHEMA",
    "THEOREM_DEPENDENCY_GRAPH_SCHEMA",
    "THEOREM_RECORD_SCHEMA",
    "THEOREM_SLICE_DECISION_SCHEMA",
    "EvidenceRevalidationDecision",
    "LocalMutation",
    "ObligationEvidenceRequest",
    "ObligationSliceBinding",
    "ObligationSliceDecision",
    "ObligationSliceReceipt",
    "ObligationSlicingError",
    "ObligationSlicingStaleError",
    "SliceDisposition",
    "SliceSubjectKind",
    "SourceNodeCone",
    "StageSliceDecision",
    "TheoremDependencyGraph",
    "TheoremRecord",
    "TheoremSliceDecision",
    "UnchangedStageReplayError",
    "classify_translation_stages",
    "close_theorem_dependents",
    "propagate_changed_source_nodes",
    "require_replayed_stages",
    "slice_and_replay_obligations",
]
