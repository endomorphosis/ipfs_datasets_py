"""Versioned source, derived-artifact, lineage, and corpus-manifest contracts.

These records extend the existing identity, provenance, and schema-registry
kernel.  They do not introduce a second provenance system, canonicalizer, or
logic family.  Identity is always a CIDv1 over the existing
``ir-canonical-identity-v1`` profile.  Floats are rejected as durable fields.
Unknown payload keys fail closed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final

from .canonical import CanonicalizationError, canonical_json_bytes
from .identity import canonical_identity
from .provenance import SourceRef, SourceReviewStatus
from .schema_registry import (
    CompatibilityDeclaration,
    IRSchemaRegistry,
    MigrationSpec,
    SchemaSpec,
)


SOURCE_RELEASE_SCHEMA: Final = "ir-source-release/v1"
SOURCE_RECORD_SCHEMA: Final = "ir-source-record/v1"
SOURCE_RECORD_SCHEMA_V1_1: Final = "ir-source-record/v1.1"
DERIVED_ARTIFACT_SCHEMA: Final = "ir-derived-artifact/v1"
LINEAGE_GRAPH_SCHEMA: Final = "ir-lineage-graph/v1"
CORPUS_MANIFEST_SCHEMA: Final = "ir-corpus-manifest/v1"
SOURCE_LINEAGE_DOMAIN: Final = "ir.source-lineage"

_ID_RE_MAX = 256


class SourceLineageError(ValueError):
    """Raised when a source/lineage record is malformed or fails closed."""


class RecordKind(str, Enum):
    """Closed vocabulary distinguishing source rows from derivatives."""

    SOURCE_RELEASE = "source_release"
    SOURCE_RECORD = "source_record"
    DERIVED_ARTIFACT = "derived_artifact"
    LINEAGE_GRAPH = "lineage_graph"
    CORPUS_MANIFEST = "corpus_manifest"


class RightsDisposition(str, Enum):
    """Training-admission decision for one rights scope."""

    ADMITTED = "admitted"
    QUARANTINED = "quarantined"
    DENIED = "denied"
    UNRESOLVED = "unresolved"


class LineageRelation(str, Enum):
    """How one record was produced from another."""

    RELEASE_CONTAINS = "release_contains"
    DERIVED_FROM = "derived_from"
    SAME_LINEAGE_GROUP = "same_lineage_group"
    TRANSLATION_OF = "translation_of"
    PROOF_OF = "proof_of"


def _require_id(label: str, value: object) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise SourceLineageError(f"{label} must be a non-empty exact string")
    if len(value) > _ID_RE_MAX:
        raise SourceLineageError(f"{label} must not exceed {_ID_RE_MAX} characters")
    if any(ch.isspace() for ch in value):
        raise SourceLineageError(f"{label} must not contain whitespace")
    return value


def _require_text(label: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise SourceLineageError(f"{label} must be a non-empty string")
    return value


def _require_int(label: str, value: object, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SourceLineageError(f"{label} must be an integer")
    if value < minimum:
        raise SourceLineageError(f"{label} must be >= {minimum}")
    return value


def _require_sha256(label: str, value: object) -> str:
    if not isinstance(value, str) or len(value) != 64 or value != value.lower():
        raise SourceLineageError(f"{label} must be a lowercase 64-hex SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise SourceLineageError(f"{label} must be a lowercase 64-hex SHA-256 digest") from exc
    return value


def _enum(cls: type[Enum], value: object, label: str) -> Any:
    if isinstance(value, cls):
        return value
    if isinstance(value, str):
        try:
            return cls(value)
        except ValueError as exc:
            raise SourceLineageError(f"{label} is not an allowed {cls.__name__}") from exc
    raise SourceLineageError(f"{label} is not an allowed {cls.__name__}")


def _reject_unknown(payload: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    extra = set(payload) - allowed
    if extra:
        raise SourceLineageError(f"{label} unknown field: {sorted(extra)[0]}")


def _identity_for(schema_version: str, payload: Mapping[str, Any]) -> str:
    identity = canonical_identity(
        dict(payload),
        domain=SOURCE_LINEAGE_DOMAIN,
        schema_version=schema_version,
    )
    return identity.cid


@dataclass(frozen=True, slots=True)
class RightsRecord:
    """Declared rights and training-admission disposition."""

    disposition: RightsDisposition
    license_expression: str
    source_rights_status: str
    transformation_rights_status: str
    scope: str

    def validate(self) -> None:
        _enum(RightsDisposition, self.disposition, "RightsRecord.disposition")
        _require_text("RightsRecord.license_expression", self.license_expression)
        _require_text("RightsRecord.source_rights_status", self.source_rights_status)
        _require_text(
            "RightsRecord.transformation_rights_status",
            self.transformation_rights_status,
        )
        _require_text("RightsRecord.scope", self.scope)
        if (
            self.disposition is RightsDisposition.ADMITTED
            and self.source_rights_status in {"unresolved", "unverified", "denied"}
        ):
            raise SourceLineageError("admitted rights require a resolved source-rights status")

    def to_dict(self) -> dict[str, str]:
        return {
            "disposition": self.disposition.value,
            "license_expression": self.license_expression,
            "scope": self.scope,
            "source_rights_status": self.source_rights_status,
            "transformation_rights_status": self.transformation_rights_status,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RightsRecord":
        return _rights_from_dict(data)


_RIGHTS_FIELDS = frozenset(
    {
        "disposition",
        "license_expression",
        "scope",
        "source_rights_status",
        "transformation_rights_status",
    }
)


def _rights_from_dict(data: Mapping[str, Any]) -> RightsRecord:
    if not isinstance(data, Mapping):
        raise SourceLineageError("RightsRecord must be an object")
    _reject_unknown(data, _RIGHTS_FIELDS, "RightsRecord")
    record = RightsRecord(
        disposition=_enum(RightsDisposition, data.get("disposition"), "RightsRecord.disposition"),
        license_expression=str(data.get("license_expression") or ""),
        source_rights_status=str(data.get("source_rights_status") or ""),
        transformation_rights_status=str(data.get("transformation_rights_status") or ""),
        scope=str(data.get("scope") or ""),
    )
    record.validate()
    return record


@dataclass(frozen=True, slots=True)
class TemporalCoverage:
    """Known-or-unknown cutoff and observation time.  Never a float."""

    cutoff_status: str
    cutoff_value: str | None = None
    observed_at_ms: int | None = None

    def validate(self) -> None:
        _require_text("TemporalCoverage.cutoff_status", self.cutoff_status)
        if self.cutoff_status == "known":
            if not self.cutoff_value:
                raise SourceLineageError("known temporal cutoff requires cutoff_value")
        elif self.cutoff_status == "unknown":
            if self.cutoff_value is not None:
                raise SourceLineageError("unknown temporal cutoff must not carry a value")
        else:
            raise SourceLineageError("TemporalCoverage.cutoff_status must be known or unknown")
        if self.observed_at_ms is not None:
            _require_int("TemporalCoverage.observed_at_ms", self.observed_at_ms)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cutoff_status": self.cutoff_status,
            "cutoff_value": self.cutoff_value,
            "observed_at_ms": self.observed_at_ms,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TemporalCoverage":
        if not isinstance(data, Mapping):
            raise SourceLineageError("TemporalCoverage must be an object")
        _reject_unknown(
            data, frozenset({"cutoff_status", "cutoff_value", "observed_at_ms"}), "TemporalCoverage"
        )
        raw_ms = data.get("observed_at_ms")
        record = cls(
            cutoff_status=str(data.get("cutoff_status") or ""),
            cutoff_value=None if data.get("cutoff_value") is None else str(data.get("cutoff_value")),
            observed_at_ms=None if raw_ms is None else raw_ms,  # type: ignore[arg-type]
        )
        record.validate()
        return record


@dataclass(frozen=True, slots=True)
class SourceRelease:
    """Pinned Hub/source release.  No row payloads live here."""

    release_id: str
    repository_id: str
    revision: str
    pinset_id: str
    rights: RightsRecord
    temporal: TemporalCoverage
    configuration_ids: tuple[str, ...] = ()
    schema_version: str = SOURCE_RELEASE_SCHEMA

    def validate(self) -> None:
        if self.schema_version != SOURCE_RELEASE_SCHEMA:
            raise SourceLineageError("SourceRelease.schema_version is not the v1 schema")
        _require_id("SourceRelease.release_id", self.release_id)
        _require_text("SourceRelease.repository_id", self.repository_id)
        _require_text("SourceRelease.revision", self.revision)
        _require_text("SourceRelease.pinset_id", self.pinset_id)
        self.rights.validate()
        self.temporal.validate()
        for index, item in enumerate(self.configuration_ids):
            _require_id(f"SourceRelease.configuration_ids[{index}]", item)
        if len(set(self.configuration_ids)) != len(self.configuration_ids):
            raise SourceLineageError("SourceRelease.configuration_ids must be unique")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "configuration_ids": list(self.configuration_ids),
            "pinset_id": self.pinset_id,
            "release_id": self.release_id,
            "repository_id": self.repository_id,
            "revision": self.revision,
            "rights": self.rights.to_dict(),
            "schema_version": self.schema_version,
            "temporal": self.temporal.to_dict(),
        }

    @property
    def record_cid(self) -> str:
        return _identity_for(self.schema_version, self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["kind"] = RecordKind.SOURCE_RELEASE.value
        payload["record_cid"] = self.record_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceRelease":
        _reject_unknown(
            data,
            frozenset(
                {
                    "configuration_ids",
                    "kind",
                    "pinset_id",
                    "record_cid",
                    "release_id",
                    "repository_id",
                    "revision",
                    "rights",
                    "schema_version",
                    "temporal",
                }
            ),
            "SourceRelease",
        )
        if data.get("kind") not in (None, RecordKind.SOURCE_RELEASE.value):
            raise SourceLineageError("SourceRelease.kind must be source_release")
        configs = data.get("configuration_ids") or ()
        if not isinstance(configs, Sequence) or isinstance(configs, (str, bytes)):
            raise SourceLineageError("SourceRelease.configuration_ids must be an array")
        record = cls(
            release_id=str(data.get("release_id") or ""),
            repository_id=str(data.get("repository_id") or ""),
            revision=str(data.get("revision") or ""),
            pinset_id=str(data.get("pinset_id") or ""),
            rights=_rights_from_dict(data.get("rights") or {}),
            temporal=TemporalCoverage.from_dict(data.get("temporal") or {}),
            configuration_ids=tuple(str(item) for item in configs),
            schema_version=str(data.get("schema_version") or SOURCE_RELEASE_SCHEMA),
        )
        record.validate()
        declared = data.get("record_cid")
        if declared and declared != record.record_cid:
            raise SourceLineageError("SourceRelease.record_cid does not match payload identity")
        return record


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """One source row/group bound to an existing SourceRef."""

    record_id: str
    release_id: str
    lineage_group_id: str
    source_ref: SourceRef
    rights: RightsRecord
    temporal: TemporalCoverage
    jurisdiction: str = ""
    schema_version: str = SOURCE_RECORD_SCHEMA

    def validate(self) -> None:
        if self.schema_version != SOURCE_RECORD_SCHEMA:
            raise SourceLineageError("SourceRecord.schema_version is not the v1 schema")
        _require_id("SourceRecord.record_id", self.record_id)
        _require_id("SourceRecord.release_id", self.release_id)
        _require_id("SourceRecord.lineage_group_id", self.lineage_group_id)
        self.source_ref.validate()
        self.rights.validate()
        self.temporal.validate()
        if self.jurisdiction:
            _require_text("SourceRecord.jurisdiction", self.jurisdiction)
        if self.rights.disposition is RightsDisposition.ADMITTED:
            if self.source_ref.review_status is SourceReviewStatus.QUARANTINED:
                raise SourceLineageError("quarantined SourceRef cannot be admitted")
            if self.source_ref.review_status is SourceReviewStatus.REJECTED:
                raise SourceLineageError("rejected SourceRef cannot be admitted")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "jurisdiction": self.jurisdiction,
            "lineage_group_id": self.lineage_group_id,
            "record_id": self.record_id,
            "release_id": self.release_id,
            "rights": self.rights.to_dict(),
            "schema_version": self.schema_version,
            "source_ref": self.source_ref.to_dict(),
            "temporal": self.temporal.to_dict(),
        }

    @property
    def record_cid(self) -> str:
        return _identity_for(self.schema_version, self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["kind"] = RecordKind.SOURCE_RECORD.value
        payload["record_cid"] = self.record_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceRecord":
        _reject_unknown(
            data,
            frozenset(
                {
                    "jurisdiction",
                    "kind",
                    "lineage_group_id",
                    "record_cid",
                    "record_id",
                    "release_id",
                    "rights",
                    "schema_version",
                    "source_ref",
                    "temporal",
                }
            ),
            "SourceRecord",
        )
        if data.get("kind") not in (None, RecordKind.SOURCE_RECORD.value):
            raise SourceLineageError("SourceRecord.kind must be source_record")
        record = cls(
            record_id=str(data.get("record_id") or ""),
            release_id=str(data.get("release_id") or ""),
            lineage_group_id=str(data.get("lineage_group_id") or ""),
            source_ref=SourceRef.from_dict(data.get("source_ref") or {}),
            rights=_rights_from_dict(data.get("rights") or {}),
            temporal=TemporalCoverage.from_dict(data.get("temporal") or {}),
            jurisdiction=str(data.get("jurisdiction") or ""),
            schema_version=str(data.get("schema_version") or SOURCE_RECORD_SCHEMA),
        )
        record.validate()
        declared = data.get("record_cid")
        if declared and declared != record.record_cid:
            raise SourceLineageError("SourceRecord.record_cid does not match payload identity")
        return record


@dataclass(frozen=True, slots=True)
class DerivedArtifactRecord:
    """Derivative of one or more source records.  Never counted as a source."""

    artifact_id: str
    parent_record_ids: tuple[str, ...]
    derivation_kind: str
    content_sha256: str
    rights: RightsRecord
    content_cid: str = ""
    schema_version: str = DERIVED_ARTIFACT_SCHEMA

    def validate(self) -> None:
        if self.schema_version != DERIVED_ARTIFACT_SCHEMA:
            raise SourceLineageError("DerivedArtifactRecord.schema_version is not the v1 schema")
        _require_id("DerivedArtifactRecord.artifact_id", self.artifact_id)
        if not self.parent_record_ids:
            raise SourceLineageError("DerivedArtifactRecord requires at least one parent_record_id")
        for index, item in enumerate(self.parent_record_ids):
            _require_id(f"DerivedArtifactRecord.parent_record_ids[{index}]", item)
        if len(set(self.parent_record_ids)) != len(self.parent_record_ids):
            raise SourceLineageError("DerivedArtifactRecord.parent_record_ids must be unique")
        _require_text("DerivedArtifactRecord.derivation_kind", self.derivation_kind)
        _require_sha256("DerivedArtifactRecord.content_sha256", self.content_sha256)
        self.rights.validate()
        if self.rights.disposition is RightsDisposition.ADMITTED:
            raise SourceLineageError("derived artifacts cannot be admitted as training sources")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "content_cid": self.content_cid,
            "content_sha256": self.content_sha256,
            "derivation_kind": self.derivation_kind,
            "parent_record_ids": list(self.parent_record_ids),
            "rights": self.rights.to_dict(),
            "schema_version": self.schema_version,
        }

    @property
    def record_cid(self) -> str:
        return _identity_for(self.schema_version, self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["kind"] = RecordKind.DERIVED_ARTIFACT.value
        payload["record_cid"] = self.record_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DerivedArtifactRecord":
        _reject_unknown(
            data,
            frozenset(
                {
                    "artifact_id",
                    "content_cid",
                    "content_sha256",
                    "derivation_kind",
                    "kind",
                    "parent_record_ids",
                    "record_cid",
                    "rights",
                    "schema_version",
                }
            ),
            "DerivedArtifactRecord",
        )
        if data.get("kind") not in (None, RecordKind.DERIVED_ARTIFACT.value):
            raise SourceLineageError("DerivedArtifactRecord.kind must be derived_artifact")
        parents = data.get("parent_record_ids") or ()
        if not isinstance(parents, Sequence) or isinstance(parents, (str, bytes)):
            raise SourceLineageError("DerivedArtifactRecord.parent_record_ids must be an array")
        record = cls(
            artifact_id=str(data.get("artifact_id") or ""),
            parent_record_ids=tuple(str(item) for item in parents),
            derivation_kind=str(data.get("derivation_kind") or ""),
            content_sha256=str(data.get("content_sha256") or ""),
            rights=_rights_from_dict(data.get("rights") or {}),
            content_cid=str(data.get("content_cid") or ""),
            schema_version=str(data.get("schema_version") or DERIVED_ARTIFACT_SCHEMA),
        )
        record.validate()
        declared = data.get("record_cid")
        if declared and declared != record.record_cid:
            raise SourceLineageError(
                "DerivedArtifactRecord.record_cid does not match payload identity"
            )
        return record


@dataclass(frozen=True, slots=True)
class LineageEdge:
    """Directed, content-addressed relationship between two record IDs."""

    parent_id: str
    child_id: str
    relation: LineageRelation

    def validate(self) -> None:
        _require_id("LineageEdge.parent_id", self.parent_id)
        _require_id("LineageEdge.child_id", self.child_id)
        if self.parent_id == self.child_id:
            raise SourceLineageError("LineageEdge cannot be reflexive")
        _enum(LineageRelation, self.relation, "LineageEdge.relation")

    def to_dict(self) -> dict[str, str]:
        return {
            "child_id": self.child_id,
            "parent_id": self.parent_id,
            "relation": self.relation.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LineageEdge":
        _reject_unknown(data, frozenset({"child_id", "parent_id", "relation"}), "LineageEdge")
        edge = cls(
            parent_id=str(data.get("parent_id") or ""),
            child_id=str(data.get("child_id") or ""),
            relation=_enum(LineageRelation, data.get("relation"), "LineageEdge.relation"),
        )
        edge.validate()
        return edge


@dataclass(frozen=True, slots=True)
class LineageGraph:
    """Acyclic lineage graph over source and derived records."""

    graph_id: str
    node_ids: tuple[str, ...]
    edges: tuple[LineageEdge, ...]
    schema_version: str = LINEAGE_GRAPH_SCHEMA

    def validate(self) -> None:
        if self.schema_version != LINEAGE_GRAPH_SCHEMA:
            raise SourceLineageError("LineageGraph.schema_version is not the v1 schema")
        _require_id("LineageGraph.graph_id", self.graph_id)
        if not self.node_ids:
            raise SourceLineageError("LineageGraph requires at least one node")
        for index, item in enumerate(self.node_ids):
            _require_id(f"LineageGraph.node_ids[{index}]", item)
        if len(set(self.node_ids)) != len(self.node_ids):
            raise SourceLineageError("LineageGraph.node_ids must be unique")
        nodes = set(self.node_ids)
        adjacency: dict[str, list[str]] = {node: [] for node in self.node_ids}
        for edge in self.edges:
            edge.validate()
            if edge.parent_id not in nodes or edge.child_id not in nodes:
                raise SourceLineageError("LineageGraph edge references an unknown node")
            adjacency[edge.parent_id].append(edge.child_id)
        visiting: set[str] = set()
        visited: set[str] = set()

        def walk(node: str) -> None:
            if node in visited:
                return
            if node in visiting:
                raise SourceLineageError("LineageGraph contains a cycle")
            visiting.add(node)
            for child in adjacency[node]:
                walk(child)
            visiting.remove(node)
            visited.add(node)

        for node in self.node_ids:
            walk(node)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "edges": [edge.to_dict() for edge in self.edges],
            "graph_id": self.graph_id,
            "node_ids": list(self.node_ids),
            "schema_version": self.schema_version,
        }

    @property
    def record_cid(self) -> str:
        return _identity_for(self.schema_version, self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["kind"] = RecordKind.LINEAGE_GRAPH.value
        payload["record_cid"] = self.record_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LineageGraph":
        _reject_unknown(
            data,
            frozenset({"edges", "graph_id", "kind", "node_ids", "record_cid", "schema_version"}),
            "LineageGraph",
        )
        if data.get("kind") not in (None, RecordKind.LINEAGE_GRAPH.value):
            raise SourceLineageError("LineageGraph.kind must be lineage_graph")
        nodes = data.get("node_ids") or ()
        edges = data.get("edges") or ()
        if not isinstance(nodes, Sequence) or isinstance(nodes, (str, bytes)):
            raise SourceLineageError("LineageGraph.node_ids must be an array")
        if not isinstance(edges, Sequence) or isinstance(edges, (str, bytes)):
            raise SourceLineageError("LineageGraph.edges must be an array")
        record = cls(
            graph_id=str(data.get("graph_id") or ""),
            node_ids=tuple(str(item) for item in nodes),
            edges=tuple(LineageEdge.from_dict(item) for item in edges),
            schema_version=str(data.get("schema_version") or LINEAGE_GRAPH_SCHEMA),
        )
        record.validate()
        declared = data.get("record_cid")
        if declared and declared != record.record_cid:
            raise SourceLineageError("LineageGraph.record_cid does not match payload identity")
        return record


@dataclass(frozen=True, slots=True)
class CorpusManifest:
    """Sealed corpus identity: source counts never include derivatives."""

    manifest_id: str
    source_record_ids: tuple[str, ...]
    derived_artifact_ids: tuple[str, ...]
    lineage_graph_id: str
    rights: RightsRecord
    schema_version: str = CORPUS_MANIFEST_SCHEMA

    def validate(self) -> None:
        if self.schema_version != CORPUS_MANIFEST_SCHEMA:
            raise SourceLineageError("CorpusManifest.schema_version is not the v1 schema")
        _require_id("CorpusManifest.manifest_id", self.manifest_id)
        _require_id("CorpusManifest.lineage_graph_id", self.lineage_graph_id)
        if not self.source_record_ids:
            raise SourceLineageError("CorpusManifest requires at least one source_record_id")
        for index, item in enumerate(self.source_record_ids):
            _require_id(f"CorpusManifest.source_record_ids[{index}]", item)
        if len(set(self.source_record_ids)) != len(self.source_record_ids):
            raise SourceLineageError("CorpusManifest.source_record_ids must be unique")
        for index, item in enumerate(self.derived_artifact_ids):
            _require_id(f"CorpusManifest.derived_artifact_ids[{index}]", item)
        if len(set(self.derived_artifact_ids)) != len(self.derived_artifact_ids):
            raise SourceLineageError("CorpusManifest.derived_artifact_ids must be unique")
        overlap = set(self.source_record_ids) & set(self.derived_artifact_ids)
        if overlap:
            raise SourceLineageError("derived artifacts cannot be counted as source records")
        self.rights.validate()

    def identity_payload(self) -> dict[str, Any]:
        return {
            "derived_artifact_ids": list(self.derived_artifact_ids),
            "lineage_graph_id": self.lineage_graph_id,
            "manifest_id": self.manifest_id,
            "rights": self.rights.to_dict(),
            "schema_version": self.schema_version,
            "source_record_ids": list(self.source_record_ids),
        }

    @property
    def record_cid(self) -> str:
        return _identity_for(self.schema_version, self.identity_payload())

    @property
    def source_count(self) -> int:
        return len(self.source_record_ids)

    @property
    def derived_count(self) -> int:
        return len(self.derived_artifact_ids)

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["derived_count"] = self.derived_count
        payload["kind"] = RecordKind.CORPUS_MANIFEST.value
        payload["record_cid"] = self.record_cid
        payload["source_count"] = self.source_count
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CorpusManifest":
        _reject_unknown(
            data,
            frozenset(
                {
                    "derived_artifact_ids",
                    "derived_count",
                    "kind",
                    "lineage_graph_id",
                    "manifest_id",
                    "record_cid",
                    "rights",
                    "schema_version",
                    "source_count",
                    "source_record_ids",
                }
            ),
            "CorpusManifest",
        )
        if data.get("kind") not in (None, RecordKind.CORPUS_MANIFEST.value):
            raise SourceLineageError("CorpusManifest.kind must be corpus_manifest")
        sources = data.get("source_record_ids") or ()
        derived = data.get("derived_artifact_ids") or ()
        if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes)):
            raise SourceLineageError("CorpusManifest.source_record_ids must be an array")
        if not isinstance(derived, Sequence) or isinstance(derived, (str, bytes)):
            raise SourceLineageError("CorpusManifest.derived_artifact_ids must be an array")
        record = cls(
            manifest_id=str(data.get("manifest_id") or ""),
            source_record_ids=tuple(str(item) for item in sources),
            derived_artifact_ids=tuple(str(item) for item in derived),
            lineage_graph_id=str(data.get("lineage_graph_id") or ""),
            rights=_rights_from_dict(data.get("rights") or {}),
            schema_version=str(data.get("schema_version") or CORPUS_MANIFEST_SCHEMA),
        )
        record.validate()
        if data.get("source_count") not in (None, record.source_count):
            raise SourceLineageError("CorpusManifest.source_count does not match source_record_ids")
        if data.get("derived_count") not in (None, record.derived_count):
            raise SourceLineageError(
                "CorpusManifest.derived_count does not match derived_artifact_ids"
            )
        declared = data.get("record_cid")
        if declared and declared != record.record_cid:
            raise SourceLineageError("CorpusManifest.record_cid does not match payload identity")
        return record


def _source_record_v1_to_v1_1(payload: Mapping[str, Any]) -> dict[str, Any]:
    migrated = dict(payload)
    migrated.setdefault("annotation", "")
    migrated["schema_version"] = SOURCE_RECORD_SCHEMA_V1_1
    return migrated


def source_lineage_schema_registry() -> IRSchemaRegistry:
    """Return the closed v1 registry for source/lineage records."""

    return IRSchemaRegistry(
        schemas=(
            SchemaSpec(SOURCE_RELEASE_SCHEMA, "Pinned source release identity"),
            SchemaSpec(SOURCE_RECORD_SCHEMA, "Source row/group bound to SourceRef"),
            SchemaSpec(SOURCE_RECORD_SCHEMA_V1_1, "Source record plus optional annotation"),
            SchemaSpec(DERIVED_ARTIFACT_SCHEMA, "Non-source derivative artifact"),
            SchemaSpec(LINEAGE_GRAPH_SCHEMA, "Acyclic source/derived lineage graph"),
            SchemaSpec(CORPUS_MANIFEST_SCHEMA, "Sealed corpus source/derived counts"),
        ),
        compatibility=(
            CompatibilityDeclaration(
                source_schema_id=SOURCE_RECORD_SCHEMA,
                reader_schema_id=SOURCE_RECORD_SCHEMA_V1_1,
                compatible=True,
                rationale="v1.1 readers default the optional annotation field",
            ),
        ),
        migrations=(
            MigrationSpec(
                "ir-source-record-v1-v1.1",
                SOURCE_RECORD_SCHEMA,
                SOURCE_RECORD_SCHEMA_V1_1,
                _source_record_v1_to_v1_1,
            ),
        ),
    )


def source_lineage_schema_ids() -> tuple[str, ...]:
    return (
        SOURCE_RELEASE_SCHEMA,
        SOURCE_RECORD_SCHEMA,
        SOURCE_RECORD_SCHEMA_V1_1,
        DERIVED_ARTIFACT_SCHEMA,
        LINEAGE_GRAPH_SCHEMA,
        CORPUS_MANIFEST_SCHEMA,
    )


__all__ = [
    "CORPUS_MANIFEST_SCHEMA",
    "DERIVED_ARTIFACT_SCHEMA",
    "LINEAGE_GRAPH_SCHEMA",
    "SOURCE_RECORD_SCHEMA",
    "SOURCE_RECORD_SCHEMA_V1_1",
    "SOURCE_RELEASE_SCHEMA",
    "CorpusManifest",
    "DerivedArtifactRecord",
    "LineageEdge",
    "LineageGraph",
    "LineageRelation",
    "RecordKind",
    "RightsDisposition",
    "RightsRecord",
    "SourceLineageError",
    "SourceRecord",
    "SourceRelease",
    "TemporalCoverage",
    "source_lineage_schema_ids",
    "source_lineage_schema_registry",
]
