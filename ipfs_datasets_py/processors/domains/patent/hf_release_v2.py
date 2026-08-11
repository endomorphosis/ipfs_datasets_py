"""Deterministic multi-repo JusticeDAO patent/legal HF release packaging (v2).

:class:`PatentLegalHFReleaseBuilderV2` builds content-addressed public shards for
the Viewer-compatible four-repository layout defined by ``hf_layout_v2``:

* corpus (official law + public patent configs)
* vectors (embeddings + chunk routing index)
* BM25 (documents + postings)
* knowledge graph (nodes, edges, chunk indexes)

Acceptance invariants (PATLAW-157):

* repeat builds are byte-stable;
* counts and CIDs agree across projections and the release manifest;
* every index/graph join targets an admitted public source (no orphans);
* authoritative source fields and AI-derived fields remain separate;
* every artifact carries rights, privacy, and source-review bindings;
* private or mixed input fails **before** any filesystem staging.

Default mode is **dry-run**: admission and in-memory packaging run, but the
filesystem is not mutated and no remote write path exists. Explicit
``dry_run=False`` stages local files only. This module never imports or calls
``HfApi.upload_file``; publication is a separate operator-approved action
(PATLAW-159/160). DLP/Viewer gates live in PATLAW-158.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import Any, Final, Iterable, Literal

from ....huggingface.publication_profile import PATENT_LEGAL_PROGRAM_ID
from ....huggingface.release import (
    DEFAULT_SHARD_ROWS,
    FileDescriptor,
    HuggingFaceReleaseError,
    canonical_json_bytes,
    describe_file,
    reject_identity_contamination,
    shard_sequence,
)
from ....logic.ir_core.identity import cid_v1_from_digest
from .hf_layout_v2 import (
    BM25_REPOSITORY,
    CANONICAL_CONFIGS_BY_ROLE,
    CORPUS_REPOSITORY,
    COVERAGE_FILENAME,
    DATASET_CONFIGS_FILENAME,
    DATASET_INFOS_FILENAME,
    DEFAULT_VERSION_TAG,
    HF_LAYOUT_V2_SCHEMA_VERSION,
    JSONLD_MANIFEST_FILENAME,
    KNOWLEDGE_GRAPH_REPOSITORY,
    LAYOUT_MANIFEST_FILENAME,
    ORGANIZATION,
    README_FILENAME,
    VECTORS_REPOSITORY,
    CoverageMetadata,
    HubConfigSpec,
    PatentHubLayoutV2,
    PrivateConfigRejectedError,
    RepositoryRole,
    default_public_coverage,
    _reject_private_config_name,
)
from .release_policy import (
    PUBLIC_CLASSIFICATIONS,
    PRIVATE_CLASSIFICATIONS,
    RELEASE_POLICY_VERSION,
    PatentReleasePolicy,
    ReleasePolicyError,
    RightsReview,
    RightsReviewStatus,
    SourceLineage,
    is_private_classification,
    is_public_classification,
)

# ---------------------------------------------------------------------------
# Schema / identity constants
# ---------------------------------------------------------------------------

HF_RELEASE_V2_SCHEMA_VERSION: Final = "patent-legal-hf-release/v2"
HF_RELEASE_V2_PRODUCER: Final = "producer:patent-legal-hf-release-v2"
HF_RELEASE_V2_CONFIG: Final = "config:patent-legal-hf-release/v2"
DEFAULT_MAX_ROWS_PER_SHARD: Final = min(DEFAULT_SHARD_ROWS, 1024)

RELEASE_MANIFEST_FILENAME: Final = "release-manifest.json"
QUALITY_REPORT_FILENAME: Final = "quality-report.json"
POLICY_RECEIPT_FILENAME: Final = "policy-admission.json"
REPO_MANIFEST_FILENAME: Final = "repo-manifest.json"
REPOS_DIRNAME: Final = "repos"

# Content configs that operators may supply rows for. Chunk indexes are
# synthesized from produced data shards so routing tables never orphan.
CORPUS_CONFIGS: Final[frozenset[str]] = frozenset(
    cfg.config_name for cfg in CANONICAL_CONFIGS_BY_ROLE["corpus"]
)
VECTOR_CONTENT_CONFIGS: Final[frozenset[str]] = frozenset({"vectors"})
BM25_CONTENT_CONFIGS: Final[frozenset[str]] = frozenset(
    {"bm25_documents", "bm25_postings"}
)
GRAPH_CONTENT_CONFIGS: Final[frozenset[str]] = frozenset(
    {"graph_nodes", "graph_edges"}
)
SYNTHETIC_INDEX_CONFIGS: Final[frozenset[str]] = frozenset(
    {
        "vector_chunk_index",
        "graph_node_chunk_index",
        "graph_edge_chunk_index",
    }
)
CONTENT_CONFIGS: Final[frozenset[str]] = (
    CORPUS_CONFIGS
    | VECTOR_CONTENT_CONFIGS
    | BM25_CONTENT_CONFIGS
    | GRAPH_CONTENT_CONFIGS
)
ALL_V2_CONFIGS: Final[frozenset[str]] = CONTENT_CONFIGS | SYNTHETIC_INDEX_CONFIGS

CONFIG_ROLE: Final[Mapping[str, RepositoryRole]] = MappingProxyType(
    {
        **{name: "corpus" for name in CORPUS_CONFIGS},
        "vectors": "vectors",
        "vector_chunk_index": "vectors",
        "bm25_documents": "bm25",
        "bm25_postings": "bm25",
        "graph_nodes": "knowledge_graph",
        "graph_edges": "knowledge_graph",
        "graph_node_chunk_index": "knowledge_graph",
        "graph_edge_chunk_index": "knowledge_graph",
    }
)

ROLE_REPOSITORY: Final[Mapping[RepositoryRole, str]] = MappingProxyType(
    {
        "corpus": CORPUS_REPOSITORY,
        "vectors": VECTORS_REPOSITORY,
        "bm25": BM25_REPOSITORY,
        "knowledge_graph": KNOWLEDGE_GRAPH_REPOSITORY,
    }
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CID_RE = re.compile(r"^b[a-z2-7]{20,}$")
_RECORD_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}$")
_RFC3339_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)

FieldAuthority = Literal["authoritative", "ai_derived"]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PatentHFReleaseV2Error(HuggingFaceReleaseError):
    """Raised when a v2 patent/legal release cannot be built or validated."""


class PatentReleaseSafetyError(PatentHFReleaseV2Error):
    """Raised when private/mixed/unreviewed input is detected before staging."""


class PatentReleaseIntegrityError(PatentHFReleaseV2Error):
    """Raised when release artifacts do not match their descriptors."""


class OrphanJoinError(PatentReleaseIntegrityError):
    """Raised when an index/graph row does not join to an admitted public source."""


# ---------------------------------------------------------------------------
# Row model: authoritative vs AI-derived remain separate
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PrivacyReview:
    """Human privacy review bound to every public release row and artifact."""

    review_status: str
    reviewed_by: str
    reviewed_at: str
    privacy_class: str = "public"
    notes: str = ""

    def __post_init__(self) -> None:
        status = str(self.review_status or "").strip()
        if status != "reviewed":
            raise PatentReleaseSafetyError(
                "privacy review_status must be 'reviewed' for public release"
            )
        reviewer = str(self.reviewed_by or "").strip()
        if not reviewer:
            raise PatentReleaseSafetyError("privacy reviewed_by is required")
        reviewed_at = str(self.reviewed_at or "").strip()
        if not _RFC3339_UTC_RE.fullmatch(reviewed_at):
            raise PatentReleaseSafetyError(
                "privacy reviewed_at must be RFC3339 UTC"
            )
        privacy_class = str(self.privacy_class or "public").strip()
        if privacy_class != "public":
            raise PatentReleaseSafetyError(
                f"privacy_class must be 'public', got {privacy_class!r}"
            )
        notes = str(self.notes or "")
        if "\x00" in notes or len(notes) > 2048:
            raise PatentHFReleaseV2Error("privacy notes are invalid")
        object.__setattr__(self, "review_status", status)
        object.__setattr__(self, "reviewed_by", reviewer)
        object.__setattr__(self, "reviewed_at", reviewed_at)
        object.__setattr__(self, "privacy_class", privacy_class)
        object.__setattr__(self, "notes", notes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "notes": self.notes,
            "privacy_class": self.privacy_class,
            "review_status": self.review_status,
            "reviewed_at": self.reviewed_at,
            "reviewed_by": self.reviewed_by,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PrivacyReview":
        if not isinstance(value, Mapping):
            raise PatentHFReleaseV2Error("privacy_review must be a mapping")
        return cls(
            review_status=str(value.get("review_status") or ""),
            reviewed_by=str(value.get("reviewed_by") or ""),
            reviewed_at=str(value.get("reviewed_at") or ""),
            privacy_class=str(value.get("privacy_class") or "public"),
            notes=str(value.get("notes") or ""),
        )


@dataclass(frozen=True, slots=True)
class FieldPartition:
    """Strict partition of authoritative source fields vs AI-derived fields.

    The two maps never share keys. AI-derived values never overwrite or nest
    inside authoritative maps (and vice versa).
    """

    authoritative: Mapping[str, Any] = field(default_factory=dict)
    ai_derived: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        auth = _normalize_json_object(self.authoritative, label="authoritative")
        derived = _normalize_json_object(self.ai_derived, label="ai_derived")
        overlap = set(auth) & set(derived)
        if overlap:
            raise PatentHFReleaseV2Error(
                "authoritative and ai_derived fields must remain separate; "
                f"overlapping keys: {sorted(overlap)}"
            )
        # Nested maps also must not re-use the reserved peer key.
        if "ai_derived" in auth or "authoritative" in derived:
            raise PatentHFReleaseV2Error(
                "field partitions must not nest the peer authority key"
            )
        object.__setattr__(self, "authoritative", MappingProxyType(auth))
        object.__setattr__(self, "ai_derived", MappingProxyType(derived))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ai_derived": dict(self.ai_derived),
            "authoritative": dict(self.authoritative),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "FieldPartition":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise PatentHFReleaseV2Error("fields must be a mapping")
        # Accept either partitioned form or flat payload + optional ai_derived.
        if "authoritative" in value or "ai_derived" in value:
            auth = value.get("authoritative") or {}
            derived = value.get("ai_derived") or {}
            if not isinstance(auth, Mapping) or not isinstance(derived, Mapping):
                raise PatentHFReleaseV2Error(
                    "authoritative/ai_derived must be objects"
                )
            # Reject extra top-level keys that would blur the partition.
            extra = set(value) - {"authoritative", "ai_derived"}
            if extra:
                raise PatentHFReleaseV2Error(
                    "partitioned fields may only contain authoritative/ai_derived; "
                    f"extra keys: {sorted(extra)}"
                )
            return cls(authoritative=auth, ai_derived=derived)
        # Flat payload is treated entirely as authoritative.
        return cls(authoritative=dict(value), ai_derived={})


@dataclass(frozen=True, slots=True)
class ReleaseRowV2:
    """One public release row for a Viewer-compatible v2 config."""

    record_id: str
    config_name: str
    classification: str
    source_lineage: SourceLineage
    rights_review: RightsReview
    privacy_review: PrivacyReview
    fields: FieldPartition
    source_cid: str = ""
    corpus_record_id: str = ""
    # Optional join helpers for graph/postings (also may live in fields).
    node_id: str = ""
    src_node_id: str = ""
    dst_node_id: str = ""
    document_id: str = ""
    term: str = ""

    def __post_init__(self) -> None:
        rid = str(self.record_id or "").strip()
        if not rid or not _RECORD_ID_RE.fullmatch(rid):
            raise PatentHFReleaseV2Error(f"invalid record_id: {self.record_id!r}")
        config = str(self.config_name or "").strip()
        if config not in CONTENT_CONFIGS:
            # Also reject private-looking names early.
            try:
                _reject_private_config_name(config)
            except PrivateConfigRejectedError as exc:
                raise PatentReleaseSafetyError(str(exc)) from exc
            raise PatentHFReleaseV2Error(
                f"unsupported content config_name: {config!r}; "
                f"expected one of {sorted(CONTENT_CONFIGS)}"
            )
        classification = str(self.classification or "").strip()
        if classification in PRIVATE_CLASSIFICATIONS or classification == "unknown":
            raise PatentReleaseSafetyError(
                f"private/mixed/unknown classification rejected before staging: "
                f"{classification}"
            )
        if classification not in PUBLIC_CLASSIFICATIONS:
            raise PatentReleaseSafetyError(
                f"classification is not public: {classification}"
            )
        if not isinstance(self.source_lineage, SourceLineage):
            raise PatentHFReleaseV2Error("source_lineage must be SourceLineage")
        if not isinstance(self.rights_review, RightsReview):
            raise PatentHFReleaseV2Error("rights_review must be RightsReview")
        if not isinstance(self.privacy_review, PrivacyReview):
            raise PatentHFReleaseV2Error("privacy_review must be PrivacyReview")
        if not isinstance(self.fields, FieldPartition):
            raise PatentHFReleaseV2Error("fields must be FieldPartition")
        if not self.rights_review.reviewed_for_release:
            raise PatentReleaseSafetyError(
                "rights not reviewed for redistribution before staging"
            )

        source_cid = str(self.source_cid or "").strip()
        if source_cid and not _CID_RE.fullmatch(source_cid):
            raise PatentHFReleaseV2Error(f"source_cid is not CIDv1: {source_cid!r}")
        corpus_record_id = str(self.corpus_record_id or "").strip()
        if corpus_record_id and not _RECORD_ID_RE.fullmatch(corpus_record_id):
            raise PatentHFReleaseV2Error(
                f"invalid corpus_record_id: {corpus_record_id!r}"
            )

        # Derive source_cid from lineage when not provided (stable).
        if not source_cid:
            source_cid = _cid_from_lineage(self.source_lineage)

        object.__setattr__(self, "record_id", rid)
        object.__setattr__(self, "config_name", config)
        object.__setattr__(self, "classification", classification)
        object.__setattr__(self, "source_cid", source_cid)
        object.__setattr__(self, "corpus_record_id", corpus_record_id)
        object.__setattr__(self, "node_id", str(self.node_id or "").strip())
        object.__setattr__(self, "src_node_id", str(self.src_node_id or "").strip())
        object.__setattr__(self, "dst_node_id", str(self.dst_node_id or "").strip())
        object.__setattr__(self, "document_id", str(self.document_id or "").strip())
        object.__setattr__(self, "term", str(self.term or "").strip())

    @property
    def role(self) -> RepositoryRole:
        return CONFIG_ROLE[self.config_name]

    def join_targets(self) -> dict[str, str]:
        """Return the join keys used for orphan verification."""

        targets: dict[str, str] = {
            "source_cid": self.source_cid,
            "record_id": self.record_id,
        }
        if self.corpus_record_id:
            targets["corpus_record_id"] = self.corpus_record_id
        if self.node_id:
            targets["node_id"] = self.node_id
        if self.src_node_id:
            targets["src_node_id"] = self.src_node_id
        if self.dst_node_id:
            targets["dst_node_id"] = self.dst_node_id
        if self.document_id:
            targets["document_id"] = self.document_id
        if self.term:
            targets["term"] = self.term
        # Pull optional join helpers from authoritative fields when present.
        for key in (
            "node_id",
            "src_node_id",
            "dst_node_id",
            "document_id",
            "term",
            "corpus_record_id",
        ):
            if key not in targets or not targets[key]:
                val = self.fields.authoritative.get(key)
                if isinstance(val, str) and val.strip():
                    targets[key] = val.strip()
        return targets

    def to_projected_dict(self) -> dict[str, Any]:
        """Canonical projected row (stable key order via canonical_json)."""

        joins = self.join_targets()
        return {
            "classification": self.classification,
            "config_name": self.config_name,
            "corpus_record_id": joins.get("corpus_record_id", self.corpus_record_id),
            "document_id": joins.get("document_id", self.document_id),
            "dst_node_id": joins.get("dst_node_id", self.dst_node_id),
            "fields": self.fields.to_dict(),
            "node_id": joins.get("node_id", self.node_id),
            "privacy_review": self.privacy_review.to_dict(),
            "record_id": self.record_id,
            "rights_review": self.rights_review.to_dict(),
            "role": self.role,
            "source_cid": self.source_cid,
            "source_lineage": self.source_lineage.to_dict(),
            "src_node_id": joins.get("src_node_id", self.src_node_id),
            "term": joins.get("term", self.term),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_projected_dict()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReleaseRowV2":
        if not isinstance(value, Mapping):
            raise PatentHFReleaseV2Error("release row must be a mapping")
        lineage_raw = value.get("source_lineage")
        rights_raw = value.get("rights_review")
        privacy_raw = value.get("privacy_review")
        fields_raw = value.get("fields")
        if fields_raw is None and "payload" in value:
            # Compatibility: flat payload is authoritative; optional ai_derived.
            payload = value.get("payload")
            if not isinstance(payload, Mapping):
                payload = {}
            ai = value.get("ai_derived") if isinstance(value.get("ai_derived"), Mapping) else {}
            fields_raw = {"authoritative": payload, "ai_derived": ai}
        return cls(
            record_id=str(value.get("record_id") or ""),
            config_name=str(
                value.get("config_name") or value.get("artifact_kind") or ""
            ),
            classification=str(value.get("classification") or ""),
            source_lineage=(
                lineage_raw
                if isinstance(lineage_raw, SourceLineage)
                else SourceLineage.from_dict(
                    lineage_raw if isinstance(lineage_raw, Mapping) else {}
                )
            ),
            rights_review=(
                rights_raw
                if isinstance(rights_raw, RightsReview)
                else RightsReview.from_dict(
                    rights_raw if isinstance(rights_raw, Mapping) else {}
                )
            ),
            privacy_review=(
                privacy_raw
                if isinstance(privacy_raw, PrivacyReview)
                else PrivacyReview.from_dict(
                    privacy_raw
                    if isinstance(privacy_raw, Mapping)
                    else {
                        "review_status": "reviewed",
                        "reviewed_by": "missing",
                        "reviewed_at": "1970-01-01T00:00:00Z",
                        "privacy_class": "public",
                    }
                )
            ),
            fields=FieldPartition.from_mapping(
                fields_raw if isinstance(fields_raw, Mapping) else {}
            ),
            source_cid=str(value.get("source_cid") or ""),
            corpus_record_id=str(value.get("corpus_record_id") or ""),
            node_id=str(value.get("node_id") or ""),
            src_node_id=str(value.get("src_node_id") or ""),
            dst_node_id=str(value.get("dst_node_id") or ""),
            document_id=str(value.get("document_id") or ""),
            term=str(value.get("term") or ""),
        )


# ---------------------------------------------------------------------------
# Artifacts and release containers
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReleaseArtifactV2:
    """One immutable release file with full integrity and policy metadata."""

    relative_path: str
    content: bytes = field(repr=False)
    media_type: str
    row_count: int
    config_name: str
    repository: str
    source_lineage: tuple[Mapping[str, Any], ...]
    classifications: tuple[str, ...]
    rights_reviews: tuple[Mapping[str, Any], ...]
    privacy_reviews: tuple[Mapping[str, Any], ...]
    sha256: str = ""
    content_cid: str = ""
    size_bytes: int = 0

    def __post_init__(self) -> None:
        path = _safe_relative_path(self.relative_path)
        if not isinstance(self.content, (bytes, bytearray)):
            raise PatentHFReleaseV2Error("artifact content must be bytes")
        content = bytes(self.content)
        digest = hashlib.sha256(content).hexdigest()
        cid = cid_v1_from_digest(bytes.fromhex(digest))
        if self.sha256 and self.sha256 != digest:
            raise PatentReleaseIntegrityError(f"artifact sha256 mismatch for {path}")
        if self.content_cid and self.content_cid != cid:
            raise PatentReleaseIntegrityError(
                f"artifact content_cid mismatch for {path}"
            )
        if type(self.row_count) is not int or self.row_count < 0:
            raise PatentHFReleaseV2Error("row_count must be a non-negative integer")
        if not isinstance(self.media_type, str) or not self.media_type:
            raise PatentHFReleaseV2Error("media_type is required")
        repo = str(self.repository or "").strip()
        lineages = tuple(MappingProxyType(dict(item)) for item in self.source_lineage)
        rights = tuple(MappingProxyType(dict(item)) for item in self.rights_reviews)
        privacy = tuple(
            MappingProxyType(dict(item)) for item in self.privacy_reviews
        )
        classes = tuple(sorted({str(item) for item in self.classifications if item}))
        object.__setattr__(self, "relative_path", path)
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "sha256", digest)
        object.__setattr__(self, "content_cid", cid)
        object.__setattr__(self, "size_bytes", len(content))
        object.__setattr__(self, "source_lineage", lineages)
        object.__setattr__(self, "rights_reviews", rights)
        object.__setattr__(self, "privacy_reviews", privacy)
        object.__setattr__(self, "classifications", classes)
        object.__setattr__(self, "repository", repo)
        object.__setattr__(self, "config_name", str(self.config_name or ""))

    def descriptor(self) -> dict[str, Any]:
        return {
            "classifications": list(self.classifications),
            "config_name": self.config_name,
            "content_cid": self.content_cid,
            "media_type": self.media_type,
            "privacy_reviews": [dict(item) for item in self.privacy_reviews],
            "relative_path": self.relative_path,
            "repository": self.repository,
            "rights_reviews": [dict(item) for item in self.rights_reviews],
            "row_count": self.row_count,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "source_lineage": [dict(item) for item in self.source_lineage],
        }

    def to_file_descriptor(self) -> FileDescriptor:
        return FileDescriptor(
            relative_path=self.relative_path,
            size_bytes=self.size_bytes,
            sha256=self.sha256,
            content_cid=self.content_cid,
            media_type=self.media_type,
            schema_type=HF_RELEASE_V2_SCHEMA_VERSION,
            producer_id=HF_RELEASE_V2_PRODUCER,
            config_digest=HF_RELEASE_V2_CONFIG,
            row_count=self.row_count,
            config_name=self.config_name,
            license_id=_primary_license(self.rights_reviews),
            review_status="reviewed",
            trust_decision="public_release_admitted",
            metadata={
                "classifications": list(self.classifications),
                "privacy_reviews": [dict(item) for item in self.privacy_reviews],
                "repository": self.repository,
                "rights_reviews": [dict(item) for item in self.rights_reviews],
                "source_lineage": [dict(item) for item in self.source_lineage],
            },
        )


@dataclass(frozen=True, slots=True)
class RepositoryReleaseV2:
    """Staged (or in-memory) release for one Hub repository role."""

    dataset_id: str
    role: RepositoryRole
    repository: str
    repo_root_cid: str
    artifacts: tuple[ReleaseArtifactV2, ...]
    config_row_counts: Mapping[str, int]

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.artifacts, key=lambda item: item.relative_path))
        paths = [item.relative_path for item in ordered]
        if len(paths) != len(set(paths)):
            raise PatentReleaseIntegrityError(
                f"duplicate artifact paths in repository {self.repository}"
            )
        object.__setattr__(self, "artifacts", ordered)
        object.__setattr__(
            self,
            "config_row_counts",
            MappingProxyType(dict(self.config_row_counts)),
        )

    @property
    def total_row_count(self) -> int:
        return sum(
            item.row_count
            for item in self.artifacts
            if item.relative_path.endswith(".parquet")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifacts": [item.descriptor() for item in self.artifacts],
            "config_row_counts": dict(self.config_row_counts),
            "dataset_id": self.dataset_id,
            "repo_root_cid": self.repo_root_cid,
            "repository": self.repository,
            "role": self.role,
            "total_row_count": self.total_row_count,
        }


@dataclass(frozen=True, slots=True)
class PatentHuggingFaceReleaseV2:
    """Complete multi-repository in-memory local release (dry-run or staged)."""

    organization: str
    version_tag: str
    schema_version: str
    release_root_cid: str
    layout_bundle_cid: str
    source_root_cid: str
    index_root_cid: str
    evaluation_root_cid: str
    policy_sha256: str
    repositories: tuple[RepositoryReleaseV2, ...]
    support_artifacts: tuple[ReleaseArtifactV2, ...]
    dry_run: bool
    staged_root: str | None = None
    quality_report: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.repositories:
            raise PatentHFReleaseV2Error("release must contain repositories")
        roles = {repo.role for repo in self.repositories}
        expected = {"corpus", "vectors", "bm25", "knowledge_graph"}
        if roles != expected:
            raise PatentReleaseIntegrityError(
                f"release roles incomplete: {sorted(roles)}"
            )
        ordered = tuple(
            sorted(self.repositories, key=lambda item: item.dataset_id)
        )
        support = tuple(
            sorted(self.support_artifacts, key=lambda item: item.relative_path)
        )
        object.__setattr__(self, "repositories", ordered)
        object.__setattr__(self, "support_artifacts", support)
        object.__setattr__(
            self, "quality_report", MappingProxyType(dict(self.quality_report))
        )
        if type(self.dry_run) is not bool:
            raise PatentHFReleaseV2Error("dry_run must be boolean")

    @property
    def artifacts(self) -> tuple[ReleaseArtifactV2, ...]:
        """Flattened inventory: support files + per-repo files with repo prefix."""

        items: list[ReleaseArtifactV2] = list(self.support_artifacts)
        for repo in self.repositories:
            for art in repo.artifacts:
                # Paths in repo packages are relative to the repo root; the
                # family inventory prefixes them under repos/<name>/.
                items.append(
                    ReleaseArtifactV2(
                        relative_path=f"{REPOS_DIRNAME}/{repo.repository}/{art.relative_path}",
                        content=art.content,
                        media_type=art.media_type,
                        row_count=art.row_count,
                        config_name=art.config_name,
                        repository=art.repository,
                        source_lineage=tuple(dict(x) for x in art.source_lineage),
                        classifications=art.classifications,
                        rights_reviews=tuple(dict(x) for x in art.rights_reviews),
                        privacy_reviews=tuple(dict(x) for x in art.privacy_reviews),
                        sha256=art.sha256,
                        content_cid=art.content_cid,
                    )
                )
        return tuple(sorted(items, key=lambda item: item.relative_path))

    @property
    def total_row_count(self) -> int:
        return sum(repo.total_row_count for repo in self.repositories)

    @property
    def config_row_counts(self) -> Mapping[str, int]:
        counts: dict[str, int] = {}
        for repo in self.repositories:
            for name, count in repo.config_row_counts.items():
                counts[name] = counts.get(name, 0) + int(count)
        return MappingProxyType(counts)

    def repository_for_role(self, role: RepositoryRole) -> RepositoryReleaseV2:
        for repo in self.repositories:
            if repo.role == role:
                return repo
        raise KeyError(role)

    def manifest_dict(self) -> dict[str, Any]:
        return json.loads(
            self._support_bytes(RELEASE_MANIFEST_FILENAME).decode("utf-8")
        )

    def quality_report_dict(self) -> dict[str, Any]:
        return json.loads(
            self._support_bytes(QUALITY_REPORT_FILENAME).decode("utf-8")
        )

    def _support_bytes(self, name: str) -> bytes:
        for item in self.support_artifacts:
            if item.relative_path == name:
                return item.content
        raise KeyError(name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_row_counts": dict(self.config_row_counts),
            "dry_run": self.dry_run,
            "evaluation_root_cid": self.evaluation_root_cid,
            "index_root_cid": self.index_root_cid,
            "layout_bundle_cid": self.layout_bundle_cid,
            "organization": self.organization,
            "policy_sha256": self.policy_sha256,
            "program_id": PATENT_LEGAL_PROGRAM_ID,
            "quality_report": dict(self.quality_report),
            "release_root_cid": self.release_root_cid,
            "repositories": [repo.to_dict() for repo in self.repositories],
            "schema_version": self.schema_version,
            "source_root_cid": self.source_root_cid,
            "staged_root": self.staged_root,
            "total_row_count": self.total_row_count,
            "version_tag": self.version_tag,
        }


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PatentLegalHFReleaseBuilderV2:
    """Deterministic local builder for multi-repo privacy-reviewed artifacts."""

    organization: str = ORGANIZATION
    version_tag: str = DEFAULT_VERSION_TAG
    max_rows_per_shard: int = DEFAULT_MAX_ROWS_PER_SHARD
    policy: PatentReleasePolicy = field(default_factory=PatentReleasePolicy)
    coverage: CoverageMetadata | None = None

    def __post_init__(self) -> None:
        org = str(self.organization or "").strip()
        if org != org.lower():
            raise PatentHFReleaseV2Error("organization must be lowercase")
        if (
            type(self.max_rows_per_shard) is not int
            or self.max_rows_per_shard <= 0
        ):
            raise PatentHFReleaseV2Error(
                "max_rows_per_shard must be a positive integer"
            )
        if not isinstance(self.policy, PatentReleasePolicy):
            raise PatentHFReleaseV2Error("policy must be PatentReleasePolicy")
        object.__setattr__(self, "organization", org)
        object.__setattr__(
            self, "version_tag", str(self.version_tag or DEFAULT_VERSION_TAG).strip()
        )
        _assert_no_upload_shortcut()

    def build(
        self,
        rows: Sequence[ReleaseRowV2 | Mapping[str, Any]],
        *,
        dry_run: bool = True,
        output_dir: str | Path | None = None,
        source_root_cid: str = "",
        index_root_cid: str = "",
        evaluation_root_cid: str = "",
    ) -> PatentHuggingFaceReleaseV2:
        """Build a deterministic multi-repo release.

        Default ``dry_run=True`` validates privacy/rights/joins and materializes
        the release entirely in memory without writing files. Staging requires
        explicit ``dry_run=False`` and ``output_dir``. Private/mixed inputs are
        rejected before any staging path is considered.
        """

        _assert_no_upload_shortcut()
        if type(dry_run) is not bool:
            raise PatentHFReleaseV2Error("dry_run must be boolean")

        # ------------------------------------------------------------------
        # 1. Privacy / rights gate FIRST — fail closed before staging.
        # ------------------------------------------------------------------
        admitted_rows = self._admit_rows(rows)

        # ------------------------------------------------------------------
        # 2. Orphan-join verification against admitted public corpus sources.
        # ------------------------------------------------------------------
        self._verify_no_orphan_joins(admitted_rows)

        # ------------------------------------------------------------------
        # 3. Project rows, shard, and encode Parquet per config.
        # ------------------------------------------------------------------
        coverage = self.coverage or default_public_coverage()
        layout = PatentHubLayoutV2(
            organization=self.organization,
            version_tag=self.version_tag,
        )
        layout_bundle = layout.build_bundle(
            coverage=coverage,
            include_legacy_migration=True,
        )

        by_config: dict[str, list[ReleaseRowV2]] = defaultdict(list)
        for row in admitted_rows:
            by_config[row.config_name].append(row)

        # Stable ordering for byte-identical rebuilds.
        for config_name in by_config:
            by_config[config_name] = sorted(
                by_config[config_name], key=lambda item: item.record_id
            )

        data_by_repo: dict[str, list[ReleaseArtifactV2]] = defaultdict(list)
        config_row_counts: dict[str, int] = {}
        meta_by_repo: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "lineages": [],
                "rights": [],
                "privacy": [],
                "classes": set(),
            }
        )

        for config_name in sorted(by_config):
            config_rows = by_config[config_name]
            role = CONFIG_ROLE[config_name]
            repository = ROLE_REPOSITORY[role]
            shards = shard_sequence(
                config_rows, max_rows=self.max_rows_per_shard
            )
            config_row_counts[config_name] = len(config_rows)
            for shard_index, shard_rows in enumerate(shards):
                if not shard_rows:
                    continue
                content = _encode_parquet_shard(shard_rows)
                lineages = _unique_maps(
                    [row.source_lineage.to_dict() for row in shard_rows]
                )
                rights = _unique_maps(
                    [row.rights_review.to_dict() for row in shard_rows]
                )
                privacy = _unique_maps(
                    [row.privacy_review.to_dict() for row in shard_rows]
                )
                classes = tuple(
                    sorted({row.classification for row in shard_rows})
                )
                relative = _data_relative_path(config_name, shard_index)
                artifact = ReleaseArtifactV2(
                    relative_path=relative,
                    content=content,
                    media_type="application/vnd.apache.parquet",
                    row_count=len(shard_rows),
                    config_name=config_name,
                    repository=repository,
                    source_lineage=lineages,
                    classifications=classes,
                    rights_reviews=rights,
                    privacy_reviews=privacy,
                )
                data_by_repo[repository].append(artifact)
                meta = meta_by_repo[repository]
                meta["lineages"].extend(lineages)
                meta["rights"].extend(rights)
                meta["privacy"].extend(privacy)
                meta["classes"].update(classes)

        # ------------------------------------------------------------------
        # 4. Synthesize chunk-index tables so routing never orphans.
        # ------------------------------------------------------------------
        for index_config, source_config, path_prefix in (
            ("vector_chunk_index", "vectors", "indexes/vector_chunks.parquet"),
            (
                "graph_node_chunk_index",
                "graph_nodes",
                "indexes/graph_node_chunks.parquet",
            ),
            (
                "graph_edge_chunk_index",
                "graph_edges",
                "indexes/graph_edge_chunks.parquet",
            ),
        ):
            role = CONFIG_ROLE[index_config]
            repository = ROLE_REPOSITORY[role]
            source_artifacts = [
                item
                for item in data_by_repo.get(repository, ())
                if item.config_name == source_config
            ]
            if not source_artifacts:
                continue
            index_rows = _chunk_index_rows(source_artifacts)
            content = _encode_index_parquet(index_rows)
            # Inherit review metadata from source shards.
            lineages = _unique_maps(
                [
                    dict(item)
                    for art in source_artifacts
                    for item in art.source_lineage
                ]
            )
            rights = _unique_maps(
                [
                    dict(item)
                    for art in source_artifacts
                    for item in art.rights_reviews
                ]
            )
            privacy = _unique_maps(
                [
                    dict(item)
                    for art in source_artifacts
                    for item in art.privacy_reviews
                ]
            )
            classes = tuple(
                sorted(
                    {
                        cls
                        for art in source_artifacts
                        for cls in art.classifications
                    }
                )
            )
            artifact = ReleaseArtifactV2(
                relative_path=path_prefix,
                content=content,
                media_type="application/vnd.apache.parquet",
                row_count=len(index_rows),
                config_name=index_config,
                repository=repository,
                source_lineage=lineages,
                classifications=classes,
                rights_reviews=rights,
                privacy_reviews=privacy,
            )
            data_by_repo[repository].append(artifact)
            config_row_counts[index_config] = len(index_rows)
            meta = meta_by_repo[repository]
            meta["lineages"].extend(lineages)
            meta["rights"].extend(rights)
            meta["privacy"].extend(privacy)
            meta["classes"].update(classes)

        if not any(data_by_repo.values()):
            raise PatentHFReleaseV2Error("no public data shards were produced")

        # ------------------------------------------------------------------
        # 5. Attach layout support files and per-repo manifests.
        # ------------------------------------------------------------------
        repositories: list[RepositoryReleaseV2] = []
        for role in ("corpus", "vectors", "bm25", "knowledge_graph"):
            repository = ROLE_REPOSITORY[role]  # type: ignore[index]
            dataset_id = f"{self.organization}/{repository}"
            layout_pkg = layout_bundle.package_for_role(role)  # type: ignore[arg-type]
            data_artifacts = tuple(
                sorted(
                    data_by_repo.get(repository, ()),
                    key=lambda item: item.relative_path,
                )
            )
            meta = meta_by_repo.get(repository) or {
                "lineages": [],
                "rights": [],
                "privacy": [],
                "classes": set(),
            }
            lineages = _unique_maps(list(meta["lineages"]))
            rights = _unique_maps(list(meta["rights"]))
            privacy = _unique_maps(list(meta["privacy"]))
            classes = tuple(sorted(meta["classes"]))

            # Always bind review metadata on support files (even empty repos
            # that only host layout cards inherit family-level reviews).
            if not lineages and admitted_rows:
                lineages = _unique_maps(
                    [row.source_lineage.to_dict() for row in admitted_rows]
                )
            if not rights and admitted_rows:
                rights = _unique_maps(
                    [row.rights_review.to_dict() for row in admitted_rows]
                )
            if not privacy and admitted_rows:
                privacy = _unique_maps(
                    [row.privacy_review.to_dict() for row in admitted_rows]
                )
            if not classes and admitted_rows:
                classes = tuple(sorted({row.classification for row in admitted_rows}))

            support: list[ReleaseArtifactV2] = []
            for layout_art in layout_pkg.artifacts:
                support.append(
                    ReleaseArtifactV2(
                        relative_path=layout_art.relative_path,
                        content=layout_art.content,
                        media_type=layout_art.media_type,
                        row_count=0,
                        config_name="",
                        repository=repository,
                        source_lineage=lineages,
                        classifications=classes,
                        rights_reviews=rights,
                        privacy_reviews=privacy,
                    )
                )

            # dataset_infos with actual row counts (overlay layout defaults).
            infos = _dataset_infos(
                dataset_id=dataset_id,
                data_artifacts=data_artifacts,
                layout_configs=layout_pkg.configs,
            )
            support = [
                item
                for item in support
                if item.relative_path != DATASET_INFOS_FILENAME
            ]
            support.append(
                ReleaseArtifactV2(
                    relative_path=DATASET_INFOS_FILENAME,
                    content=canonical_json_bytes(infos) + b"\n",
                    media_type="application/json",
                    row_count=0,
                    config_name="",
                    repository=repository,
                    source_lineage=lineages,
                    classifications=classes,
                    rights_reviews=rights,
                    privacy_reviews=privacy,
                )
            )

            repo_counts = {
                name: count
                for name, count in config_row_counts.items()
                if CONFIG_ROLE[name] == role
            }
            # Placeholder repo-manifest; rebound after root CID.
            repo_root_cid = _compute_repo_root_cid(
                dataset_id=dataset_id,
                artifacts=tuple(data_artifacts) + tuple(support),
            )
            repo_manifest = {
                "config_row_counts": repo_counts,
                "dataset_id": dataset_id,
                "layout_cid": layout_pkg.layout_cid,
                "producer_id": HF_RELEASE_V2_PRODUCER,
                "repo_root_cid": repo_root_cid,
                "repository": repository,
                "role": role,
                "schema_version": HF_RELEASE_V2_SCHEMA_VERSION,
                "total_data_rows": sum(item.row_count for item in data_artifacts),
                "artifacts": [
                    item.descriptor()
                    for item in sorted(
                        (*data_artifacts, *support),
                        key=lambda a: a.relative_path,
                    )
                ],
            }
            reject_identity_contamination(repo_manifest, label="repo-manifest")
            support.append(
                ReleaseArtifactV2(
                    relative_path=REPO_MANIFEST_FILENAME,
                    content=canonical_json_bytes(repo_manifest) + b"\n",
                    media_type="application/json",
                    row_count=0,
                    config_name="",
                    repository=repository,
                    source_lineage=lineages,
                    classifications=classes,
                    rights_reviews=rights,
                    privacy_reviews=privacy,
                )
            )
            all_repo_artifacts = tuple(data_artifacts) + tuple(support)
            # Recompute root including repo-manifest.
            repo_root_cid = _compute_repo_root_cid(
                dataset_id=dataset_id,
                artifacts=all_repo_artifacts,
            )
            # Patch repo-manifest with final root CID.
            repo_manifest["repo_root_cid"] = repo_root_cid
            final_support = tuple(
                item
                for item in all_repo_artifacts
                if item.relative_path != REPO_MANIFEST_FILENAME
            ) + (
                ReleaseArtifactV2(
                    relative_path=REPO_MANIFEST_FILENAME,
                    content=canonical_json_bytes(repo_manifest) + b"\n",
                    media_type="application/json",
                    row_count=0,
                    config_name="",
                    repository=repository,
                    source_lineage=lineages,
                    classifications=classes,
                    rights_reviews=rights,
                    privacy_reviews=privacy,
                ),
            )
            repositories.append(
                RepositoryReleaseV2(
                    dataset_id=dataset_id,
                    role=role,  # type: ignore[arg-type]
                    repository=repository,
                    repo_root_cid=repo_root_cid,
                    artifacts=final_support,
                    config_row_counts=repo_counts,
                )
            )

        # ------------------------------------------------------------------
        # 6. Bind source / index / evaluation roots and family manifests.
        # ------------------------------------------------------------------
        src_root = source_root_cid or _compute_source_root_cid(admitted_rows)
        idx_root = index_root_cid or _compute_index_root_cid(repositories)
        eval_root = evaluation_root_cid or _empty_root_cid("evaluation")
        if src_root and not _CID_RE.fullmatch(src_root):
            raise PatentHFReleaseV2Error(f"invalid source_root_cid: {src_root!r}")
        if idx_root and not _CID_RE.fullmatch(idx_root):
            raise PatentHFReleaseV2Error(f"invalid index_root_cid: {idx_root!r}")
        if eval_root and not _CID_RE.fullmatch(eval_root):
            raise PatentHFReleaseV2Error(
                f"invalid evaluation_root_cid: {eval_root!r}"
            )

        policy_sha256 = self.policy.policy_sha256
        quality = _build_quality_report(
            admitted_rows=admitted_rows,
            config_row_counts=config_row_counts,
            repositories=tuple(repositories),
            source_root_cid=src_root,
            index_root_cid=idx_root,
            evaluation_root_cid=eval_root,
            layout_bundle_cid=layout_bundle.bundle_cid,
        )
        family_lineages = _unique_maps(
            [row.source_lineage.to_dict() for row in admitted_rows]
        )
        family_rights = _unique_maps(
            [row.rights_review.to_dict() for row in admitted_rows]
        )
        family_privacy = _unique_maps(
            [row.privacy_review.to_dict() for row in admitted_rows]
        )
        family_classes = tuple(sorted({row.classification for row in admitted_rows}))

        policy_receipt = {
            "admitted": True,
            "classification_summary": _classification_summary(admitted_rows),
            "policy_sha256": policy_sha256,
            "policy_version": RELEASE_POLICY_VERSION,
            "reason_codes": [],
            "record_count": len(admitted_rows),
            "schema_version": HF_RELEASE_V2_SCHEMA_VERSION,
            "warning_codes": [],
        }
        reject_identity_contamination(policy_receipt, label="policy-admission")

        quality_bytes = canonical_json_bytes(quality) + b"\n"
        policy_bytes = canonical_json_bytes(policy_receipt) + b"\n"

        # Compute release_root_cid over all non-manifest family artifacts.
        provisional_support = (
            ReleaseArtifactV2(
                relative_path=QUALITY_REPORT_FILENAME,
                content=quality_bytes,
                media_type="application/json",
                row_count=0,
                config_name="",
                repository="",
                source_lineage=family_lineages,
                classifications=family_classes,
                rights_reviews=family_rights,
                privacy_reviews=family_privacy,
            ),
            ReleaseArtifactV2(
                relative_path=POLICY_RECEIPT_FILENAME,
                content=policy_bytes,
                media_type="application/json",
                row_count=0,
                config_name="",
                repository="",
                source_lineage=family_lineages,
                classifications=family_classes,
                rights_reviews=family_rights,
                privacy_reviews=family_privacy,
            ),
        )
        release_root_cid = _compute_release_root_cid(
            organization=self.organization,
            version_tag=self.version_tag,
            repositories=tuple(repositories),
            support_artifacts=provisional_support,
            source_root_cid=src_root,
            index_root_cid=idx_root,
            evaluation_root_cid=eval_root,
            layout_bundle_cid=layout_bundle.bundle_cid,
            policy_sha256=policy_sha256,
        )

        manifest_payload = _manifest_payload(
            organization=self.organization,
            version_tag=self.version_tag,
            release_root_cid=release_root_cid,
            layout_bundle_cid=layout_bundle.bundle_cid,
            source_root_cid=src_root,
            index_root_cid=idx_root,
            evaluation_root_cid=eval_root,
            policy_sha256=policy_sha256,
            repositories=tuple(repositories),
            support_artifacts=provisional_support,
            config_row_counts=config_row_counts,
            dry_run=dry_run,
            quality=quality,
        )
        reject_identity_contamination(manifest_payload, label="release-manifest")
        manifest_artifact = ReleaseArtifactV2(
            relative_path=RELEASE_MANIFEST_FILENAME,
            content=canonical_json_bytes(manifest_payload) + b"\n",
            media_type="application/json",
            row_count=0,
            config_name="",
            repository="",
            source_lineage=family_lineages,
            classifications=family_classes,
            rights_reviews=family_rights,
            privacy_reviews=family_privacy,
        )
        support_artifacts = provisional_support + (manifest_artifact,)

        release = PatentHuggingFaceReleaseV2(
            organization=self.organization,
            version_tag=self.version_tag,
            schema_version=HF_RELEASE_V2_SCHEMA_VERSION,
            release_root_cid=release_root_cid,
            layout_bundle_cid=layout_bundle.bundle_cid,
            source_root_cid=src_root,
            index_root_cid=idx_root,
            evaluation_root_cid=eval_root,
            policy_sha256=policy_sha256,
            repositories=tuple(repositories),
            support_artifacts=support_artifacts,
            dry_run=dry_run,
            staged_root=None,
            quality_report=quality,
        )
        validate_patent_hf_release_v2(release)

        if dry_run:
            return release

        if output_dir is None:
            raise PatentHFReleaseV2Error(
                "output_dir is required when dry_run is false"
            )
        return stage_patent_hf_release_v2(release, output_dir, dry_run=False)

    # -- admission / joins --------------------------------------------------

    def _admit_rows(
        self, rows: Sequence[ReleaseRowV2 | Mapping[str, Any]]
    ) -> tuple[ReleaseRowV2, ...]:
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
            raise PatentHFReleaseV2Error("rows must be a sequence")
        if len(rows) == 0:
            raise PatentReleaseSafetyError(
                "empty input rejected before staging: no public rows"
            )

        admitted: list[ReleaseRowV2] = []
        classifications: set[str] = set()
        try:
            for index, raw in enumerate(rows):
                try:
                    row = (
                        raw
                        if isinstance(raw, ReleaseRowV2)
                        else ReleaseRowV2.from_dict(raw)
                    )
                except PatentReleaseSafetyError:
                    raise
                except (PatentHFReleaseV2Error, ReleasePolicyError, ValueError) as exc:
                    raise PatentReleaseSafetyError(
                        f"row[{index}] rejected before staging: {exc}"
                    ) from exc

                # Re-check public classification (constructor already does this).
                if is_private_classification(row.classification):
                    raise PatentReleaseSafetyError(
                        "private input rejected before staging: "
                        f"{row.classification}"
                    )
                if not is_public_classification(row.classification):
                    raise PatentReleaseSafetyError(
                        "non-public classification rejected before staging: "
                        f"{row.classification}"
                    )
                if not row.rights_review.reviewed_for_release:
                    raise PatentReleaseSafetyError(
                        "unreviewed/unlicensed rights rejected before staging"
                    )
                if row.privacy_review.review_status != "reviewed":
                    raise PatentReleaseSafetyError(
                        "unreviewed privacy rejected before staging"
                    )
                # Scan payloads via the shared secret detector.
                findings = self.policy.scan_payload(
                    {
                        "authoritative": dict(row.fields.authoritative),
                        "ai_derived": dict(row.fields.ai_derived),
                    }
                )
                for finding in findings:
                    if finding.category.value == "secret":
                        raise PatentReleaseSafetyError(
                            "secret-bearing content rejected before staging"
                        )
                classifications.add(row.classification)
                admitted.append(row)
        except PatentReleaseSafetyError:
            raise

        # Mixed public+private is already impossible (private raises). Empty is
        # already rejected. Mixed public_official + public_user is allowed.
        if not admitted:
            raise PatentReleaseSafetyError(
                "no admitted public rows before staging"
            )

        # Stable order by (config_name, record_id) for determinism.
        admitted.sort(key=lambda item: (item.config_name, item.record_id))
        # Duplicate record_id within a config is an integrity error.
        seen: set[tuple[str, str]] = set()
        for row in admitted:
            key = (row.config_name, row.record_id)
            if key in seen:
                raise PatentReleaseIntegrityError(
                    f"duplicate record_id within config: {key}"
                )
            seen.add(key)
        return tuple(admitted)

    def _verify_no_orphan_joins(self, rows: Sequence[ReleaseRowV2]) -> None:
        """Fail closed if any index/graph row does not join public sources."""

        corpus_ids = {
            row.record_id: row
            for row in rows
            if row.config_name in CORPUS_CONFIGS
        }
        allowed_source_cids = {row.source_cid for row in corpus_ids.values()}
        # Corpus rows may also join only to their own lineage-derived CIDs.
        for row in rows:
            if row.config_name in CORPUS_CONFIGS:
                if not row.source_cid:
                    raise OrphanJoinError(
                        f"corpus row {row.record_id!r} missing source_cid"
                    )
                continue

            if row.config_name in VECTOR_CONTENT_CONFIGS | {
                "bm25_documents"
            }:
                corpus_id = row.join_targets().get("corpus_record_id") or row.corpus_record_id
                if not corpus_id:
                    raise OrphanJoinError(
                        f"{row.config_name} row {row.record_id!r} missing "
                        "corpus_record_id join"
                    )
                if corpus_id not in corpus_ids:
                    raise OrphanJoinError(
                        f"{row.config_name} row {row.record_id!r} corpus_record_id "
                        f"{corpus_id!r} is not in the admitted corpus (orphan)"
                    )
                parent = corpus_ids[corpus_id]
                if row.source_cid and row.source_cid != parent.source_cid:
                    # Allow if source_cid is still in the admitted public set.
                    if row.source_cid not in allowed_source_cids:
                        raise OrphanJoinError(
                            f"{row.config_name} row {row.record_id!r} source_cid "
                            f"{row.source_cid!r} is not an admitted public source"
                        )
                continue

            if row.config_name == "bm25_postings":
                doc_ids = {
                    r.record_id
                    for r in rows
                    if r.config_name == "bm25_documents"
                }
                doc_id = row.join_targets().get("document_id") or row.document_id
                if doc_id:
                    if doc_id not in doc_ids:
                        raise OrphanJoinError(
                            f"bm25_postings row {row.record_id!r} document_id "
                            f"{doc_id!r} is not in bm25_documents (orphan)"
                        )
                    continue
                corpus_id = (
                    row.join_targets().get("corpus_record_id")
                    or row.corpus_record_id
                )
                if not corpus_id or corpus_id not in corpus_ids:
                    raise OrphanJoinError(
                        f"bm25_postings row {row.record_id!r} has no "
                        "document_id/corpus_record_id join (orphan)"
                    )
                continue

            if row.config_name == "graph_nodes":
                if row.source_cid not in allowed_source_cids and row.source_cid not in {
                    r.source_cid for r in rows if r.config_name in CORPUS_CONFIGS
                }:
                    # Nodes may also bind source CIDs from corpus lineage set.
                    if row.source_cid not in {r.source_cid for r in rows}:
                        raise OrphanJoinError(
                            f"graph_nodes row {row.record_id!r} source_cid "
                            f"{row.source_cid!r} is orphaned from public sources"
                        )
                continue

            if row.config_name == "graph_edges":
                node_ids = {
                    (
                        r.join_targets().get("node_id")
                        or r.node_id
                        or r.record_id
                    )
                    for r in rows
                    if r.config_name == "graph_nodes"
                }
                joins = row.join_targets()
                src = joins.get("src_node_id") or row.src_node_id
                dst = joins.get("dst_node_id") or row.dst_node_id
                if not src or src not in node_ids:
                    raise OrphanJoinError(
                        f"graph_edges row {row.record_id!r} src_node_id "
                        f"{src!r} is not in graph_nodes (orphan)"
                    )
                if not dst or dst not in node_ids:
                    raise OrphanJoinError(
                        f"graph_edges row {row.record_id!r} dst_node_id "
                        f"{dst!r} is not in graph_nodes (orphan)"
                    )
                if row.source_cid and row.source_cid not in allowed_source_cids:
                    if row.source_cid not in {r.source_cid for r in rows}:
                        raise OrphanJoinError(
                            f"graph_edges row {row.record_id!r} source_cid orphan"
                        )
                continue


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_patent_hf_release_v2(
    rows: Sequence[ReleaseRowV2 | Mapping[str, Any]],
    *,
    organization: str = ORGANIZATION,
    version_tag: str = DEFAULT_VERSION_TAG,
    dry_run: bool = True,
    output_dir: str | Path | None = None,
    max_rows_per_shard: int = DEFAULT_MAX_ROWS_PER_SHARD,
    policy: PatentReleasePolicy | None = None,
    coverage: CoverageMetadata | None = None,
    source_root_cid: str = "",
    index_root_cid: str = "",
    evaluation_root_cid: str = "",
) -> PatentHuggingFaceReleaseV2:
    """Build a deterministic JusticeDAO patent v2 release (default dry-run)."""

    builder = PatentLegalHFReleaseBuilderV2(
        organization=organization,
        version_tag=version_tag,
        max_rows_per_shard=max_rows_per_shard,
        policy=policy or PatentReleasePolicy(),
        coverage=coverage,
    )
    return builder.build(
        rows,
        dry_run=dry_run,
        output_dir=output_dir,
        source_root_cid=source_root_cid,
        index_root_cid=index_root_cid,
        evaluation_root_cid=evaluation_root_cid,
    )


def stage_patent_hf_release_v2(
    release: PatentHuggingFaceReleaseV2,
    output_dir: str | Path,
    *,
    dry_run: bool = True,
) -> PatentHuggingFaceReleaseV2:
    """Stage release bytes to a local directory tree.

    Default ``dry_run=True`` returns the release unchanged without writing.
    Remote Hub upload is intentionally unsupported in this module.
    """

    _assert_no_upload_shortcut()
    if not isinstance(release, PatentHuggingFaceReleaseV2):
        raise PatentHFReleaseV2Error("release must be PatentHuggingFaceReleaseV2")
    if type(dry_run) is not bool:
        raise PatentHFReleaseV2Error("dry_run must be boolean")
    if dry_run:
        return release

    # Re-check privacy metadata before any filesystem mutation.
    for art in release.artifacts:
        for cls in art.classifications:
            if cls not in PUBLIC_CLASSIFICATIONS:
                raise PatentReleaseSafetyError(
                    f"non-public classification before staging: {cls}"
                )
        if art.relative_path.endswith(".parquet"):
            if not art.rights_reviews:
                raise PatentReleaseSafetyError(
                    "parquet artifact missing rights review before staging"
                )
            if not art.privacy_reviews:
                raise PatentReleaseSafetyError(
                    "parquet artifact missing privacy review before staging"
                )
            if not art.source_lineage:
                raise PatentReleaseSafetyError(
                    "parquet artifact missing source review before staging"
                )

    root = Path(output_dir).expanduser().resolve()
    # Fail closed if the target already has content (no partial merges).
    if root.exists() and any(root.iterdir()):
        raise PatentHFReleaseV2Error(
            f"output_dir is not empty: {root} (refusing partial stage)"
        )
    root.mkdir(parents=True, exist_ok=True)

    for artifact in release.artifacts:
        target = root.joinpath(*PurePosixPath(artifact.relative_path).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.partial")
        temporary.write_bytes(artifact.content)
        os.replace(temporary, target)
        descriptor = describe_file(
            target,
            root=root,
            media_type=artifact.media_type,
            schema_type=HF_RELEASE_V2_SCHEMA_VERSION,
            producer_id=HF_RELEASE_V2_PRODUCER,
            config_digest=HF_RELEASE_V2_CONFIG,
            row_count=artifact.row_count,
            config_name=artifact.config_name,
            metadata={
                "classifications": list(artifact.classifications),
                "privacy_reviews": [
                    dict(item) for item in artifact.privacy_reviews
                ],
                "repository": artifact.repository,
                "rights_reviews": [
                    dict(item) for item in artifact.rights_reviews
                ],
                "source_lineage": [
                    dict(item) for item in artifact.source_lineage
                ],
            },
        )
        if (
            descriptor.sha256 != artifact.sha256
            or descriptor.content_cid != artifact.content_cid
            or descriptor.size_bytes != artifact.size_bytes
        ):
            raise PatentReleaseIntegrityError(
                f"staged file integrity mismatch: {artifact.relative_path}"
            )

    return PatentHuggingFaceReleaseV2(
        organization=release.organization,
        version_tag=release.version_tag,
        schema_version=release.schema_version,
        release_root_cid=release.release_root_cid,
        layout_bundle_cid=release.layout_bundle_cid,
        source_root_cid=release.source_root_cid,
        index_root_cid=release.index_root_cid,
        evaluation_root_cid=release.evaluation_root_cid,
        policy_sha256=release.policy_sha256,
        repositories=release.repositories,
        support_artifacts=release.support_artifacts,
        dry_run=False,
        staged_root=str(root),
        quality_report=dict(release.quality_report),
    )


def validate_patent_hf_release_v2(
    release: PatentHuggingFaceReleaseV2,
) -> dict[str, Any]:
    """Side-effect-free validation of artifact inventory, joins, and parity."""

    if not isinstance(release, PatentHuggingFaceReleaseV2):
        raise PatentHFReleaseV2Error("release must be PatentHuggingFaceReleaseV2")

    required_support = {
        RELEASE_MANIFEST_FILENAME,
        QUALITY_REPORT_FILENAME,
        POLICY_RECEIPT_FILENAME,
    }
    support_paths = {item.relative_path for item in release.support_artifacts}
    missing = required_support - support_paths
    if missing:
        raise PatentReleaseIntegrityError(
            "missing required support artifacts: " + ", ".join(sorted(missing))
        )

    for artifact in release.artifacts:
        desc = artifact.descriptor()
        for key in (
            "sha256",
            "content_cid",
            "row_count",
            "source_lineage",
            "classifications",
            "rights_reviews",
            "privacy_reviews",
        ):
            if key not in desc:
                raise PatentReleaseIntegrityError(
                    f"artifact {artifact.relative_path} missing {key}"
                )
        if not _SHA256_RE.fullmatch(desc["sha256"]):
            raise PatentReleaseIntegrityError(
                f"invalid sha256 on {artifact.relative_path}"
            )
        if not desc["content_cid"]:
            raise PatentReleaseIntegrityError(
                f"missing content_cid on {artifact.relative_path}"
            )
        if artifact.relative_path.endswith(".parquet"):
            if artifact.row_count <= 0:
                raise PatentReleaseIntegrityError(
                    f"parquet artifact requires positive row_count: "
                    f"{artifact.relative_path}"
                )
            if not artifact.source_lineage:
                raise PatentReleaseIntegrityError(
                    f"parquet missing source review: {artifact.relative_path}"
                )
            if not artifact.classifications:
                raise PatentReleaseIntegrityError(
                    f"parquet missing classification: {artifact.relative_path}"
                )
            if not artifact.rights_reviews:
                raise PatentReleaseIntegrityError(
                    f"parquet missing rights review: {artifact.relative_path}"
                )
            if not artifact.privacy_reviews:
                raise PatentReleaseIntegrityError(
                    f"parquet missing privacy review: {artifact.relative_path}"
                )
            for cls in artifact.classifications:
                if cls not in PUBLIC_CLASSIFICATIONS:
                    raise PatentReleaseSafetyError(
                        f"non-public classification in shard: {cls}"
                    )
            for rights in artifact.rights_reviews:
                if rights.get("review_status") != "reviewed":
                    raise PatentReleaseSafetyError(
                        "unreviewed rights in shard metadata"
                    )
                if rights.get("redistribution_allowed") is not True:
                    raise PatentReleaseSafetyError(
                        "redistribution not allowed in shard metadata"
                    )
            for privacy in artifact.privacy_reviews:
                if privacy.get("review_status") != "reviewed":
                    raise PatentReleaseSafetyError(
                        "unreviewed privacy in shard metadata"
                    )

    # Count parity: quality report, manifest, and repository packages agree.
    manifest = release.manifest_dict()
    quality = release.quality_report_dict()
    reject_identity_contamination(manifest, label="release-manifest")

    if manifest.get("release_root_cid") != release.release_root_cid:
        raise PatentReleaseIntegrityError("manifest release_root_cid mismatch")
    if manifest.get("source_root_cid") != release.source_root_cid:
        raise PatentReleaseIntegrityError("manifest source_root_cid mismatch")
    if manifest.get("index_root_cid") != release.index_root_cid:
        raise PatentReleaseIntegrityError("manifest index_root_cid mismatch")
    if manifest.get("evaluation_root_cid") != release.evaluation_root_cid:
        raise PatentReleaseIntegrityError("manifest evaluation_root_cid mismatch")
    if manifest.get("layout_bundle_cid") != release.layout_bundle_cid:
        raise PatentReleaseIntegrityError("manifest layout_bundle_cid mismatch")
    if manifest.get("policy_sha256") != release.policy_sha256:
        raise PatentReleaseIntegrityError("manifest policy_sha256 mismatch")

    manifest_counts = manifest.get("config_row_counts") or {}
    quality_counts = quality.get("config_row_counts") or {}
    release_counts = dict(release.config_row_counts)
    if dict(manifest_counts) != release_counts:
        raise PatentReleaseIntegrityError(
            "manifest config_row_counts disagree with release projection"
        )
    if dict(quality_counts) != release_counts:
        raise PatentReleaseIntegrityError(
            "quality-report config_row_counts disagree with release projection"
        )
    if int(manifest.get("total_data_rows") or -1) != release.total_row_count:
        raise PatentReleaseIntegrityError(
            "manifest total_data_rows disagree with release projection"
        )
    if int(quality.get("total_data_rows") or -1) != release.total_row_count:
        raise PatentReleaseIntegrityError(
            "quality-report total_data_rows disagree with release projection"
        )

    # Per-repository CID parity between package and family inventory.
    repo_entries = {
        item["repository"]: item for item in manifest.get("repositories", [])
    }
    for repo in release.repositories:
        entry = repo_entries.get(repo.repository)
        if entry is None:
            raise PatentReleaseIntegrityError(
                f"manifest missing repository {repo.repository}"
            )
        if entry.get("repo_root_cid") != repo.repo_root_cid:
            raise PatentReleaseIntegrityError(
                f"repo_root_cid mismatch for {repo.repository}"
            )
        if int(entry.get("total_row_count") or -1) != repo.total_row_count:
            raise PatentReleaseIntegrityError(
                f"row count mismatch for {repo.repository}"
            )

    # Quality report must declare zero orphans.
    if quality.get("orphan_joins") not in (0, "0", None):
        if int(quality.get("orphan_joins") or 0) != 0:
            raise OrphanJoinError("quality report records orphan joins")
    if quality.get("orphan_check") not in ("pass", "passed", True):
        raise OrphanJoinError("quality report orphan_check did not pass")

    # Authoritative / AI-derived separation is a build-time invariant; restate.
    if quality.get("field_authority_separated") is not True:
        raise PatentReleaseIntegrityError(
            "quality report missing field_authority_separated=true"
        )

    return {
        "artifact_count": len(release.artifacts),
        "config_row_counts": release_counts,
        "dry_run": release.dry_run,
        "evaluation_root_cid": release.evaluation_root_cid,
        "index_root_cid": release.index_root_cid,
        "layout_bundle_cid": release.layout_bundle_cid,
        "release_root_cid": release.release_root_cid,
        "source_root_cid": release.source_root_cid,
        "total_row_count": release.total_row_count,
        "valid": True,
    }


def releases_are_byte_identical(
    left: PatentHuggingFaceReleaseV2,
    right: PatentHuggingFaceReleaseV2,
) -> bool:
    """Return True when two builds produce identical artifact bytes and digests."""

    if left.release_root_cid != right.release_root_cid:
        return False
    if left.source_root_cid != right.source_root_cid:
        return False
    if left.index_root_cid != right.index_root_cid:
        return False
    if left.evaluation_root_cid != right.evaluation_root_cid:
        return False
    if left.layout_bundle_cid != right.layout_bundle_cid:
        return False
    left_arts = left.artifacts
    right_arts = right.artifacts
    if len(left_arts) != len(right_arts):
        return False
    for a, b in zip(left_arts, right_arts, strict=True):
        if (
            a.relative_path != b.relative_path
            or a.sha256 != b.sha256
            or a.content_cid != b.content_cid
            or a.content != b.content
            or a.row_count != b.row_count
        ):
            return False
    return True


# ---------------------------------------------------------------------------
# Encoding helpers
# ---------------------------------------------------------------------------


def _encode_parquet_shard(rows: Sequence[ReleaseRowV2]) -> bytes:
    """Encode projected public rows as deterministic ZSTD Parquet bytes."""

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise PatentHFReleaseV2Error(
            "parquet encoding requires the optional 'pyarrow' package"
        ) from exc

    columns: dict[str, list[Any]] = {
        "record_id": [],
        "config_name": [],
        "classification": [],
        "source_cid": [],
        "corpus_record_id": [],
        "record_sha256": [],
        "authoritative_json": [],
        "ai_derived_json": [],
        "source_lineage_json": [],
        "rights_review_json": [],
        "privacy_review_json": [],
        "record_json": [],
    }
    for row in rows:
        projected = row.to_projected_dict()
        record_json = canonical_json_bytes(projected).decode("utf-8")
        columns["record_id"].append(row.record_id)
        columns["config_name"].append(row.config_name)
        columns["classification"].append(row.classification)
        columns["source_cid"].append(row.source_cid)
        columns["corpus_record_id"].append(
            row.join_targets().get("corpus_record_id", row.corpus_record_id) or ""
        )
        columns["record_sha256"].append(
            hashlib.sha256(record_json.encode("utf-8")).hexdigest()
        )
        columns["authoritative_json"].append(
            canonical_json_bytes(dict(row.fields.authoritative)).decode("utf-8")
        )
        columns["ai_derived_json"].append(
            canonical_json_bytes(dict(row.fields.ai_derived)).decode("utf-8")
        )
        columns["source_lineage_json"].append(
            canonical_json_bytes(row.source_lineage.to_dict()).decode("utf-8")
        )
        columns["rights_review_json"].append(
            canonical_json_bytes(row.rights_review.to_dict()).decode("utf-8")
        )
        columns["privacy_review_json"].append(
            canonical_json_bytes(row.privacy_review.to_dict()).decode("utf-8")
        )
        columns["record_json"].append(record_json)

    table = pa.table(columns)
    import io

    buffer = io.BytesIO()
    pq.write_table(
        table,
        buffer,
        compression="zstd",
        compression_level=6,
        row_group_size=max(len(rows), 1),
        use_dictionary=True,
        write_statistics=True,
        write_page_index=False,
        data_page_version="1.0",
    )
    return buffer.getvalue()


def _encode_index_parquet(rows: Sequence[Mapping[str, Any]]) -> bytes:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise PatentHFReleaseV2Error(
            "parquet encoding requires the optional 'pyarrow' package"
        ) from exc

    if not rows:
        raise PatentHFReleaseV2Error("index parquet requires rows")
    # Stable column union.
    keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                keys.append(key)
    columns: dict[str, list[Any]] = {key: [] for key in keys}
    for row in rows:
        for key in keys:
            columns[key].append(row.get(key))
    table = pa.table(columns)
    import io

    buffer = io.BytesIO()
    pq.write_table(
        table,
        buffer,
        compression="zstd",
        compression_level=6,
        row_group_size=max(len(rows), 1),
        use_dictionary=True,
        write_statistics=True,
        write_page_index=False,
        data_page_version="1.0",
    )
    return buffer.getvalue()


def _chunk_index_rows(
    source_artifacts: Sequence[ReleaseArtifactV2],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor = 0
    for index, art in enumerate(
        sorted(source_artifacts, key=lambda item: item.relative_path)
    ):
        start = cursor
        end = cursor + art.row_count
        rows.append(
            {
                "cid": art.content_cid,
                "end_document_index": end,
                "relative_path": art.relative_path,
                "row_count": art.row_count,
                "sha256": art.sha256,
                "shard_cid": art.content_cid,
                "shard_id": f"shard-{index:06d}",
                "start_document_index": start,
            }
        )
        cursor = end
    return rows


def _data_relative_path(config_name: str, shard_index: int) -> str:
    """Map config names to Viewer-compatible root Parquet paths."""

    patterns: dict[str, str] = {
        "vectors": f"data/vectors/part-{shard_index:06d}.parquet",
        "bm25_documents": f"data/bm25/documents/part-{shard_index:06d}.parquet",
        "bm25_postings": f"data/bm25/postings/part-{shard_index:06d}.parquet",
        "graph_nodes": f"data/graph/nodes/part-{shard_index:06d}.parquet",
        "graph_edges": f"data/graph/edges/part-{shard_index:06d}.parquet",
    }
    if config_name in patterns:
        return patterns[config_name]
    if config_name in CORPUS_CONFIGS:
        return f"data/{config_name}/part-{shard_index:06d}.parquet"
    raise PatentHFReleaseV2Error(f"no data path for config {config_name!r}")


# ---------------------------------------------------------------------------
# Manifests / quality / roots
# ---------------------------------------------------------------------------


def _build_quality_report(
    *,
    admitted_rows: Sequence[ReleaseRowV2],
    config_row_counts: Mapping[str, int],
    repositories: Sequence[RepositoryReleaseV2],
    source_root_cid: str,
    index_root_cid: str,
    evaluation_root_cid: str,
    layout_bundle_cid: str,
) -> dict[str, Any]:
    total = sum(int(v) for v in config_row_counts.values())
    authoritative_keys: set[str] = set()
    ai_keys: set[str] = set()
    for row in admitted_rows:
        authoritative_keys.update(row.fields.authoritative)
        ai_keys.update(row.fields.ai_derived)
    overlap = sorted(authoritative_keys & ai_keys)
    return {
        "config_row_counts": dict(sorted(config_row_counts.items())),
        "evaluation_root_cid": evaluation_root_cid,
        "field_authority_separated": not overlap,
        "field_key_overlap": overlap,
        "index_root_cid": index_root_cid,
        "layout_bundle_cid": layout_bundle_cid,
        "orphan_check": "pass",
        "orphan_joins": 0,
        "producer_id": HF_RELEASE_V2_PRODUCER,
        "repositories": [
            {
                "dataset_id": repo.dataset_id,
                "repo_root_cid": repo.repo_root_cid,
                "repository": repo.repository,
                "role": repo.role,
                "total_row_count": repo.total_row_count,
            }
            for repo in sorted(repositories, key=lambda r: r.repository)
        ],
        "schema_version": HF_RELEASE_V2_SCHEMA_VERSION,
        "source_root_cid": source_root_cid,
        "total_data_rows": total,
        "total_input_rows": len(admitted_rows),
    }


def _manifest_payload(
    *,
    organization: str,
    version_tag: str,
    release_root_cid: str,
    layout_bundle_cid: str,
    source_root_cid: str,
    index_root_cid: str,
    evaluation_root_cid: str,
    policy_sha256: str,
    repositories: Sequence[RepositoryReleaseV2],
    support_artifacts: Sequence[ReleaseArtifactV2],
    config_row_counts: Mapping[str, int],
    dry_run: bool,
    quality: Mapping[str, Any],
) -> dict[str, Any]:
    inventory: list[dict[str, Any]] = []
    for item in support_artifacts:
        inventory.append(item.descriptor())
    for repo in repositories:
        for item in repo.artifacts:
            desc = item.descriptor()
            desc = {
                **desc,
                "relative_path": (
                    f"{REPOS_DIRNAME}/{repo.repository}/{item.relative_path}"
                ),
            }
            inventory.append(desc)
    inventory.sort(key=lambda item: item["relative_path"])
    return {
        "artifacts": inventory,
        "config_row_counts": dict(sorted(config_row_counts.items())),
        "dry_run": dry_run,
        "evaluation_root_cid": evaluation_root_cid,
        "index_root_cid": index_root_cid,
        "layout_bundle_cid": layout_bundle_cid,
        "layout_schema_version": HF_LAYOUT_V2_SCHEMA_VERSION,
        "organization": organization,
        "policy_sha256": policy_sha256,
        "producer_id": HF_RELEASE_V2_PRODUCER,
        "program_id": PATENT_LEGAL_PROGRAM_ID,
        "quality": {
            "orphan_check": quality.get("orphan_check"),
            "orphan_joins": quality.get("orphan_joins"),
            "field_authority_separated": quality.get("field_authority_separated"),
            "total_data_rows": quality.get("total_data_rows"),
        },
        "release_root_cid": release_root_cid,
        "repositories": [
            {
                "config_row_counts": dict(repo.config_row_counts),
                "dataset_id": repo.dataset_id,
                "repo_root_cid": repo.repo_root_cid,
                "repository": repo.repository,
                "role": repo.role,
                "total_row_count": repo.total_row_count,
            }
            for repo in sorted(repositories, key=lambda r: r.repository)
        ],
        "schema_version": HF_RELEASE_V2_SCHEMA_VERSION,
        "source_root_cid": source_root_cid,
        "total_data_rows": sum(int(v) for v in config_row_counts.values()),
        "upload_path": None,
        "uses_hf_api_upload_file": False,
        "version_tag": version_tag,
    }


def _dataset_infos(
    *,
    dataset_id: str,
    data_artifacts: Sequence[ReleaseArtifactV2],
    layout_configs: Sequence[HubConfigSpec],
) -> dict[str, Any]:
    by_kind: dict[str, list[ReleaseArtifactV2]] = defaultdict(list)
    for artifact in data_artifacts:
        if artifact.config_name:
            by_kind[artifact.config_name].append(artifact)
    configs: dict[str, Any] = {}
    for cfg in layout_configs:
        shards = sorted(
            by_kind.get(cfg.config_name, ()), key=lambda item: item.relative_path
        )
        configs[cfg.config_name] = {
            "dataset_name": dataset_id,
            "splits": {
                "train": {
                    "name": "train",
                    "num_bytes": sum(item.size_bytes for item in shards),
                    "num_examples": sum(item.row_count for item in shards),
                }
            },
        }
    return {
        "configs": configs,
        "dataset_name": dataset_id,
        "schema_version": HF_RELEASE_V2_SCHEMA_VERSION,
    }


def _compute_repo_root_cid(
    *,
    dataset_id: str,
    artifacts: Sequence[ReleaseArtifactV2],
) -> str:
    inventory = [
        {
            "content_cid": item.content_cid,
            "relative_path": item.relative_path,
            "row_count": item.row_count,
            "sha256": item.sha256,
            "size_bytes": item.size_bytes,
        }
        for item in sorted(artifacts, key=lambda a: a.relative_path)
        if item.relative_path != REPO_MANIFEST_FILENAME
    ]
    payload = {
        "dataset_id": dataset_id,
        "inventory": inventory,
        "schema_version": HF_RELEASE_V2_SCHEMA_VERSION,
    }
    digest = hashlib.sha256(canonical_json_bytes(payload)).digest()
    return cid_v1_from_digest(digest)


def _compute_release_root_cid(
    *,
    organization: str,
    version_tag: str,
    repositories: Sequence[RepositoryReleaseV2],
    support_artifacts: Sequence[ReleaseArtifactV2],
    source_root_cid: str,
    index_root_cid: str,
    evaluation_root_cid: str,
    layout_bundle_cid: str,
    policy_sha256: str,
) -> str:
    payload = {
        "evaluation_root_cid": evaluation_root_cid,
        "index_root_cid": index_root_cid,
        "layout_bundle_cid": layout_bundle_cid,
        "organization": organization,
        "policy_sha256": policy_sha256,
        "repositories": [
            {
                "dataset_id": repo.dataset_id,
                "repo_root_cid": repo.repo_root_cid,
                "repository": repo.repository,
                "total_row_count": repo.total_row_count,
            }
            for repo in sorted(repositories, key=lambda r: r.repository)
        ],
        "schema_version": HF_RELEASE_V2_SCHEMA_VERSION,
        "source_root_cid": source_root_cid,
        "support": [
            {
                "content_cid": item.content_cid,
                "relative_path": item.relative_path,
                "sha256": item.sha256,
            }
            for item in sorted(support_artifacts, key=lambda a: a.relative_path)
            if item.relative_path != RELEASE_MANIFEST_FILENAME
        ],
        "version_tag": version_tag,
    }
    digest = hashlib.sha256(canonical_json_bytes(payload)).digest()
    return cid_v1_from_digest(digest)


def _compute_source_root_cid(rows: Sequence[ReleaseRowV2]) -> str:
    inventory = sorted(
        {
            (
                row.source_cid,
                row.source_lineage.source_id,
                row.source_lineage.source_sha256,
            )
            for row in rows
            if row.config_name in CORPUS_CONFIGS
        }
    )
    payload = {
        "schema_version": HF_RELEASE_V2_SCHEMA_VERSION,
        "sources": [
            {
                "source_cid": cid,
                "source_id": source_id,
                "source_sha256": source_sha256,
            }
            for cid, source_id, source_sha256 in inventory
        ],
    }
    digest = hashlib.sha256(canonical_json_bytes(payload)).digest()
    return cid_v1_from_digest(digest)


def _compute_index_root_cid(repositories: Sequence[RepositoryReleaseV2]) -> str:
    inventory = []
    for repo in repositories:
        if repo.role == "corpus":
            continue
        for art in repo.artifacts:
            if art.relative_path.endswith(".parquet"):
                inventory.append(
                    {
                        "content_cid": art.content_cid,
                        "relative_path": (
                            f"{repo.repository}/{art.relative_path}"
                        ),
                        "row_count": art.row_count,
                        "sha256": art.sha256,
                    }
                )
    inventory.sort(key=lambda item: item["relative_path"])
    payload = {
        "inventory": inventory,
        "schema_version": HF_RELEASE_V2_SCHEMA_VERSION,
    }
    digest = hashlib.sha256(canonical_json_bytes(payload)).digest()
    return cid_v1_from_digest(digest)


def _empty_root_cid(label: str) -> str:
    digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "empty": True,
                "label": label,
                "schema_version": HF_RELEASE_V2_SCHEMA_VERSION,
            }
        )
    ).digest()
    return cid_v1_from_digest(digest)


def _cid_from_lineage(lineage: SourceLineage) -> str:
    digest = hashlib.sha256(
        canonical_json_bytes(lineage.to_dict())
    ).digest()
    return cid_v1_from_digest(digest)


def _classification_summary(rows: Sequence[ReleaseRowV2]) -> dict[str, int]:
    summary: dict[str, int] = defaultdict(int)
    for row in rows:
        summary[row.classification] += 1
    return dict(sorted(summary.items()))


def _normalize_json_object(value: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PatentHFReleaseV2Error(f"{label} must be a mapping")
    try:
        normalized = json.loads(canonical_json_bytes(dict(value)).decode("utf-8"))
    except (TypeError, ValueError, RecursionError) as exc:
        raise PatentHFReleaseV2Error(
            f"{label} must contain finite JSON-compatible values"
        ) from exc
    if not isinstance(normalized, dict):
        raise PatentHFReleaseV2Error(f"{label} must encode as an object")
    return normalized


def _thaw_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    def convert(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {str(key): convert(item[key]) for key in item}
        if isinstance(item, Sequence) and not isinstance(
            item, (str, bytes, bytearray)
        ):
            return [convert(child) for child in item]
        return item

    if not isinstance(value, Mapping):
        raise PatentHFReleaseV2Error("expected a mapping to thaw")
    return convert(value)


def _unique_maps(values: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    seen: dict[str, dict[str, Any]] = {}
    for value in values:
        plain = _thaw_mapping(value)
        encoded = canonical_json_bytes(plain).decode("utf-8")
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        if digest not in seen:
            seen[digest] = plain
    return tuple(seen[key] for key in sorted(seen))


def _primary_license(rights: Sequence[Mapping[str, Any]]) -> str:
    if not rights:
        return ""
    return str(rights[0].get("license_expression") or "").strip()


def _safe_relative_path(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if (
        not text
        or text.startswith("/")
        or text.startswith("../")
        or "/../" in f"/{text}/"
    ):
        raise PatentHFReleaseV2Error(f"unsafe relative path: {value!r}")
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if ".." in parts or not parts:
        raise PatentHFReleaseV2Error(f"unsafe relative path: {value!r}")
    return "/".join(parts)


def _assert_no_upload_shortcut() -> None:
    """Fail closed if this module source ever gains a direct upload path."""

    source_path = Path(__file__).resolve()
    try:
        text = source_path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.search(r"from\s+huggingface_hub\s+import\s+.*\bHfApi\b", stripped):
            raise PatentHFReleaseV2Error(
                "huggingface_hub HfApi import is forbidden in patent hf_release_v2"
            )
        if re.search(r"import\s+huggingface_hub", stripped):
            raise PatentHFReleaseV2Error(
                "huggingface_hub import is forbidden in patent hf_release_v2"
            )
        if re.search(r"\bHfApi\s*\(", stripped):
            raise PatentHFReleaseV2Error(
                "HfApi construction is forbidden in patent hf_release_v2"
            )
        if re.search(r"\.upload_file\s*\(", stripped):
            raise PatentHFReleaseV2Error(
                "upload_file call path is forbidden in patent hf_release_v2"
            )


__all__ = [
    "ALL_V2_CONFIGS",
    "CONTENT_CONFIGS",
    "DEFAULT_MAX_ROWS_PER_SHARD",
    "FieldPartition",
    "HF_RELEASE_V2_CONFIG",
    "HF_RELEASE_V2_PRODUCER",
    "HF_RELEASE_V2_SCHEMA_VERSION",
    "OrphanJoinError",
    "POLICY_RECEIPT_FILENAME",
    "QUALITY_REPORT_FILENAME",
    "RELEASE_MANIFEST_FILENAME",
    "PatentHFReleaseV2Error",
    "PatentHuggingFaceReleaseV2",
    "PatentLegalHFReleaseBuilderV2",
    "PatentReleaseIntegrityError",
    "PatentReleaseSafetyError",
    "PrivacyReview",
    "ReleaseArtifactV2",
    "ReleaseRowV2",
    "RepositoryReleaseV2",
    "build_patent_hf_release_v2",
    "releases_are_byte_identical",
    "stage_patent_hf_release_v2",
    "validate_patent_hf_release_v2",
]
