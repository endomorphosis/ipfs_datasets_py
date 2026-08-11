"""Multi-artifact corpus + BM25 + vector + graph Hub index package (PATLAW-174).

Assembles a multi-repo-compatible release package that binds:

* the public legal corpus root (PATLAW-170);
* the production BM25 snapshot (PATLAW-171);
* the production vector snapshot (PATLAW-172); and
* the production knowledge-graph snapshot (PATLAW-173),

together with Viewer layout cards, counts, repository identities, and
rights/privacy metadata required on every artifact.

Design invariants
-----------------
* Package digests are **byte-stable** for identical pinned inputs (corpus +
  three index family roots, layout version tag, organization).
* **Missing any of the three index families** (bm25 / vectors /
  knowledge_graph) fails closed before packaging or staging.
* Every package artifact carries **rights_review** and **privacy_review**.
* Default mode is dry-run (in-memory); ``stage=True`` writes local files only.
* No network I/O, no Hub authentication, and no remote upload.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Final, Optional, Union

from ....logic.ir_core.identity import cid_v1_from_digest
from .hf_layout_v2 import (
    BM25_REPOSITORY,
    CORPUS_REPOSITORY,
    DEFAULT_VERSION_TAG,
    HF_LAYOUT_V2_SCHEMA_VERSION,
    KNOWLEDGE_GRAPH_REPOSITORY,
    ORGANIZATION,
    VECTORS_REPOSITORY,
    CoverageMetadata,
    PatentHubLayoutBundle,
    PatentHubLayoutV2,
    SourceDisclosure,
    default_public_coverage,
)
from .hf_release_v2 import PrivacyReview
from .public_legal_bm25_builder import (
    MANIFEST_FILENAME as BM25_MANIFEST_FILENAME,
    PublicLegalBm25Snapshot,
    build_public_legal_bm25_index,
    release_packaging_bindings as bm25_release_packaging_bindings,
    validate_snapshot as validate_bm25_snapshot,
)
from .public_legal_corpus_materializer import (
    MANIFEST_FILENAME as CORPUS_MANIFEST_FILENAME,
    PublicLegalCorpusMaterialization,
    PublicLegalCorpusMaterializer,
    assert_public_only_documents,
    build_default_public_legal_recipe,
)
from .public_legal_graph_builder import (
    SNAPSHOT_FILENAME as GRAPH_SNAPSHOT_FILENAME,
    PublicLegalGraphBuild,
    build_public_legal_knowledge_graph,
    validate_graph_build,
)
from .public_legal_vector_builder import (
    MANIFEST_FILENAME as VECTOR_MANIFEST_FILENAME,
    PublicLegalVectorBuildResult,
    build_public_legal_vector_index,
    validate_build as validate_vector_build,
)
from .release_policy import (
    RightsReview,
    RightsReviewStatus,
)

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "patent.hub_index_package.v1"
INTERFACE: Final = "HubIndexPackageBuilder@1"
PRODUCER: Final = "producer:hub-index-package"
CONFIG_ID: Final = "config:hub-index-package/v1"
TASK_ID: Final = "PATLAW-174"
GOAL_ID: Final = "PATLAW-G212"
CODE_VERSION: Final = "1.0.0"

MANIFEST_FILENAME: Final = "hub-index-package.manifest.json"
PACKAGE_ROOT_FILENAME: Final = "package-root.json"
LAYOUT_BUNDLE_FILENAME: Final = "layout-bundle.json"
RECEIPT_FILENAME: Final = "hub-index-package-receipt.json"
ARTIFACTS_INVENTORY_FILENAME: Final = "artifacts-inventory.json"

DEFAULT_PRIVACY_REVIEWER: Final = "patent-legal-governance"
DEFAULT_REVIEWED_AT: Final = "2026-08-01T00:00:00Z"
DEFAULT_LICENSE: Final = "public-domain-US-government"

# The three index families required by acceptance (corpus is foundation).
INDEX_FAMILIES: Final[tuple[str, ...]] = ("bm25", "vectors", "knowledge_graph")
INDEX_FAMILY_SET: Final[frozenset[str]] = frozenset(INDEX_FAMILIES)
REQUIRED_ROLES: Final[tuple[str, ...]] = (
    "corpus",
    "bm25",
    "vectors",
    "knowledge_graph",
)

ROLE_TO_REPOSITORY: Final[Mapping[str, str]] = MappingProxyType(
    {
        "corpus": CORPUS_REPOSITORY,
        "bm25": BM25_REPOSITORY,
        "vectors": VECTORS_REPOSITORY,
        "knowledge_graph": KNOWLEDGE_GRAPH_REPOSITORY,
    }
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CID_RE = re.compile(r"^b[a-z2-7]{20,}$")
_RFC3339_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
_FILE_MODE: Final = 0o600
_DIR_MODE: Final = 0o700

# Fields stripped from content digests so staging presentation cannot drift CIDs.
_NON_CONTENT_MANIFEST_KEYS: Final[frozenset[str]] = frozenset(
    {
        "staged_at_utc",
        "notes",
        "mode",
        "output_dir",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class HubIndexPackageError(ValueError):
    """Base error for hub index packaging."""

    code: str = "hub_index_package_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class MissingIndexFamilyError(HubIndexPackageError):
    """Raised when BM25, vectors, or knowledge_graph is absent."""

    code = "missing_index_family"


class MissingRightsPrivacyError(HubIndexPackageError):
    """Raised when an artifact lacks rights or privacy metadata."""

    code = "missing_rights_privacy"


class CorpusPinMismatchError(HubIndexPackageError):
    """Raised when index families do not share the same corpus root pin."""

    code = "corpus_pin_mismatch"


class PackageIntegrityError(HubIndexPackageError):
    """Raised when counts, digests, or CIDs fail integrity checks."""

    code = "package_integrity"


class SchemaValidationError(HubIndexPackageError):
    """Raised when a package artifact or manifest fails structural validation."""

    code = "schema_validation"


class PrivateOrMixedPackageError(HubIndexPackageError):
    """Raised when private / mixed material is present in the package inputs."""

    code = "private_or_mixed_input"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PackageMode(str, Enum):
    """How the package is produced."""

    DRY_RUN = "dry_run"
    STAGE = "stage"


class IndexFamily(str, Enum):
    """Closed set of Hub index package roles (corpus + three index families)."""

    CORPUS = "corpus"
    BM25 = "bm25"
    VECTORS = "vectors"
    KNOWLEDGE_GRAPH = "knowledge_graph"

    @classmethod
    def coerce(cls, value: Any) -> "IndexFamily":
        if isinstance(value, cls):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "vector": "vectors",
            "embedding": "vectors",
            "embeddings": "vectors",
            "graph": "knowledge_graph",
            "kg": "knowledge_graph",
            "knowledgegraph": "knowledge_graph",
        }
        text = aliases.get(text, text)
        try:
            return cls(text)
        except ValueError as exc:
            raise SchemaValidationError(
                f"unknown index family / role: {value!r}"
            ) from exc


# ---------------------------------------------------------------------------
# Canonical JSON / content addressing
# ---------------------------------------------------------------------------


def canonical_json(value: Any) -> str:
    """RFC 8785-style deterministic JSON (sorted keys, compact separators)."""
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def content_digest_of(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def content_cid_of(value: Any) -> str:
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).digest()
    return cid_v1_from_digest(digest)


def content_cid_of_bytes(payload: bytes) -> str:
    return cid_v1_from_digest(hashlib.sha256(payload).digest())


def _require_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    text = str(value if value is not None else "").strip()
    if not text:
        raise SchemaValidationError(f"{name} is required")
    if len(text) > maximum:
        raise SchemaValidationError(f"{name} exceeds max length {maximum}")
    if "\x00" in text:
        raise SchemaValidationError(f"{name} contains NUL")
    return text


def _require_sha256(value: Any, name: str = "sha256") -> str:
    text = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(text):
        raise SchemaValidationError(f"{name} must be a 64-char hex sha256")
    return text


def _require_cid(value: Any, name: str = "cid") -> str:
    text = str(value or "").strip()
    if not _CID_RE.fullmatch(text):
        raise SchemaValidationError(f"{name} must be a CIDv1 base32 string")
    return text


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, _DIR_MODE)
    except OSError:
        pass
    return path


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    _ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(payload)
    try:
        os.chmod(tmp, _FILE_MODE)
    except OSError:
        pass
    tmp.replace(path)


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"))


# ---------------------------------------------------------------------------
# Rights / privacy helpers
# ---------------------------------------------------------------------------


def default_privacy_review(
    *,
    reviewed_by: str = DEFAULT_PRIVACY_REVIEWER,
    reviewed_at: str = DEFAULT_REVIEWED_AT,
    notes: str = "Public official / public-user Hub index package artifact",
) -> PrivacyReview:
    """Stable public privacy review bound to package artifacts."""
    return PrivacyReview(
        review_status="reviewed",
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        privacy_class="public",
        notes=notes,
    )


def default_rights_review(
    *,
    license_expression: str = DEFAULT_LICENSE,
    reviewed_by: str = DEFAULT_PRIVACY_REVIEWER,
    reviewed_at: str = DEFAULT_REVIEWED_AT,
    notes: str = "Public US government works admitted for redistribution",
) -> RightsReview:
    """Stable public rights review bound to package artifacts."""
    return RightsReview(
        license_expression=license_expression,
        review_status=RightsReviewStatus.REVIEWED,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        redistribution_allowed=True,
        notes=notes,
    )


def rights_privacy_from_corpus(
    corpus: PublicLegalCorpusMaterialization,
) -> tuple[RightsReview, PrivacyReview]:
    """Derive package-level rights/privacy from the pinned corpus documents."""
    assert_public_only_documents(corpus.documents)
    docs = corpus.documents
    if not docs:
        raise SchemaValidationError("corpus has no documents for rights derivation")
    licenses = {doc.rights_review.license_expression for doc in docs}
    reviewers = {doc.rights_review.reviewed_by for doc in docs}
    reviewed_ats = {doc.rights_review.reviewed_at for doc in docs}
    if not all(doc.rights_review.redistribution_allowed for doc in docs):
        raise MissingRightsPrivacyError(
            "corpus contains documents that disallow redistribution"
        )
    if not all(
        doc.rights_review.review_status is RightsReviewStatus.REVIEWED for doc in docs
    ):
        raise MissingRightsPrivacyError(
            "corpus contains unreviewed rights on one or more documents"
        )
    # Prefer a single shared pin when uniform; otherwise use deterministic defaults.
    license_expression = (
        next(iter(licenses)) if len(licenses) == 1 else DEFAULT_LICENSE
    )
    reviewed_by = (
        next(iter(reviewers)) if len(reviewers) == 1 else DEFAULT_PRIVACY_REVIEWER
    )
    reviewed_at = (
        next(iter(reviewed_ats)) if len(reviewed_ats) == 1 else DEFAULT_REVIEWED_AT
    )
    rights = RightsReview(
        license_expression=license_expression,
        review_status=RightsReviewStatus.REVIEWED,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        redistribution_allowed=True,
        notes="Derived from public legal corpus document rights reviews",
    )
    privacy = PrivacyReview(
        review_status="reviewed",
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        privacy_class="public",
        notes="Public partition only; private/mixed inputs fail closed upstream",
    )
    return rights, privacy


def assert_rights_privacy_present(
    *,
    rights_review: RightsReview | Mapping[str, Any] | None,
    privacy_review: PrivacyReview | Mapping[str, Any] | None,
    label: str,
) -> tuple[RightsReview, PrivacyReview]:
    """Fail closed when rights or privacy metadata is missing or incomplete."""
    if rights_review is None:
        raise MissingRightsPrivacyError(f"{label}: rights_review is required")
    if privacy_review is None:
        raise MissingRightsPrivacyError(f"{label}: privacy_review is required")
    rights = (
        rights_review
        if isinstance(rights_review, RightsReview)
        else RightsReview.from_dict(rights_review)
    )
    privacy = (
        privacy_review
        if isinstance(privacy_review, PrivacyReview)
        else PrivacyReview.from_dict(privacy_review)
    )
    if rights.review_status is not RightsReviewStatus.REVIEWED:
        raise MissingRightsPrivacyError(
            f"{label}: rights_review.review_status must be 'reviewed'"
        )
    if not rights.redistribution_allowed:
        raise MissingRightsPrivacyError(
            f"{label}: rights_review.redistribution_allowed must be true"
        )
    if not rights.reviewed_by:
        raise MissingRightsPrivacyError(f"{label}: rights_review.reviewed_by required")
    if privacy.review_status != "reviewed":
        raise MissingRightsPrivacyError(
            f"{label}: privacy_review.review_status must be 'reviewed'"
        )
    if privacy.privacy_class != "public":
        raise MissingRightsPrivacyError(
            f"{label}: privacy_review.privacy_class must be 'public'"
        )
    if not privacy.reviewed_by:
        raise MissingRightsPrivacyError(
            f"{label}: privacy_review.reviewed_by required"
        )
    return rights, privacy


# ---------------------------------------------------------------------------
# Artifact + family binding models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HubIndexPackageArtifact:
    """One package file with mandatory rights and privacy metadata."""

    relative_path: str
    content: bytes = field(repr=False)
    media_type: str
    role: str
    family: str
    rights_review: RightsReview
    privacy_review: PrivacyReview
    classification: str = "public_official"
    row_count: int = 0
    config_name: str = ""
    sha256: str = ""
    content_cid: str = ""
    size_bytes: int = 0

    def __post_init__(self) -> None:
        path = str(self.relative_path or "").strip().replace("\\", "/")
        if not path or path.startswith("/") or ".." in path.split("/"):
            raise SchemaValidationError(
                f"invalid artifact relative_path: {self.relative_path!r}"
            )
        if not isinstance(self.content, (bytes, bytearray)):
            raise SchemaValidationError("artifact content must be bytes")
        content = bytes(self.content)
        digest = hashlib.sha256(content).hexdigest()
        cid = cid_v1_from_digest(bytes.fromhex(digest))
        if self.sha256 and self.sha256 != digest:
            raise PackageIntegrityError(f"artifact sha256 mismatch for {path}")
        if self.content_cid and self.content_cid != cid:
            raise PackageIntegrityError(f"artifact content_cid mismatch for {path}")
        rights, privacy = assert_rights_privacy_present(
            rights_review=self.rights_review,
            privacy_review=self.privacy_review,
            label=f"artifact {path}",
        )
        family = IndexFamily.coerce(self.family).value
        role = IndexFamily.coerce(self.role).value
        classification = str(self.classification or "public_official").strip()
        if classification not in {"public_official", "public_user"}:
            raise PrivateOrMixedPackageError(
                f"artifact {path}: non-public classification {classification!r}"
            )
        if type(self.row_count) is not int or self.row_count < 0:
            raise SchemaValidationError("row_count must be a non-negative int")
        media_type = _require_str(self.media_type, "media_type", maximum=128)
        object.__setattr__(self, "relative_path", path)
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "sha256", digest)
        object.__setattr__(self, "content_cid", cid)
        object.__setattr__(self, "size_bytes", len(content))
        object.__setattr__(self, "rights_review", rights)
        object.__setattr__(self, "privacy_review", privacy)
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "classification", classification)
        object.__setattr__(self, "media_type", media_type)
        object.__setattr__(self, "config_name", str(self.config_name or ""))

    def descriptor(self) -> dict[str, Any]:
        """Content-stable descriptor (no raw bytes)."""
        return {
            "classification": self.classification,
            "config_name": self.config_name,
            "content_cid": self.content_cid,
            "family": self.family,
            "media_type": self.media_type,
            "privacy_review": self.privacy_review.to_dict(),
            "relative_path": self.relative_path,
            "rights_review": self.rights_review.to_dict(),
            "role": self.role,
            "row_count": self.row_count,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.descriptor()


@dataclass(frozen=True, slots=True)
class HubIndexFamilyBinding:
    """Binding for one repository role (corpus or index family)."""

    role: str
    family: str
    repository: str
    dataset_id: str
    root_cid: str
    root_digest_sha256: str
    layout_cid: str
    counts: Mapping[str, Any]
    configs: tuple[str, ...]
    corpus_root_cid: str
    schema_version: str
    join_fields: tuple[str, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        role = IndexFamily.coerce(self.role).value
        family = IndexFamily.coerce(self.family).value
        if role != family:
            raise SchemaValidationError(
                f"family binding role {role!r} must equal family {family!r}"
            )
        repository = _require_str(self.repository, "repository", maximum=128)
        expected_repo = ROLE_TO_REPOSITORY.get(role)
        if expected_repo and repository != expected_repo:
            # Allow organization-prefixed names only if exact short name matches.
            if not repository.endswith(expected_repo):
                raise SchemaValidationError(
                    f"repository for role {role!r} must be {expected_repo!r}, "
                    f"got {repository!r}"
                )
        dataset_id = _require_str(self.dataset_id, "dataset_id", maximum=256)
        if dataset_id != dataset_id.lower():
            raise SchemaValidationError("dataset_id must be lowercase")
        root_cid = _require_cid(self.root_cid, f"{role}.root_cid")
        root_digest = _require_sha256(
            self.root_digest_sha256, f"{role}.root_digest_sha256"
        )
        layout_cid = _require_cid(self.layout_cid, f"{role}.layout_cid")
        corpus_root_cid = _require_cid(self.corpus_root_cid, "corpus_root_cid")
        schema_version = _require_str(self.schema_version, "schema_version", maximum=128)
        configs = tuple(str(c).strip() for c in (self.configs or ()) if str(c).strip())
        join_fields = tuple(
            str(f).strip() for f in (self.join_fields or ()) if str(f).strip()
        )
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "repository", repository)
        object.__setattr__(self, "dataset_id", dataset_id)
        object.__setattr__(self, "root_cid", root_cid)
        object.__setattr__(self, "root_digest_sha256", root_digest)
        object.__setattr__(self, "layout_cid", layout_cid)
        object.__setattr__(self, "corpus_root_cid", corpus_root_cid)
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "configs", configs)
        object.__setattr__(self, "join_fields", join_fields)
        object.__setattr__(self, "counts", MappingProxyType(dict(self.counts or {})))
        object.__setattr__(self, "extra", MappingProxyType(dict(self.extra or {})))

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "configs": list(self.configs),
            "corpus_root_cid": self.corpus_root_cid,
            "counts": dict(self.counts),
            "dataset_id": self.dataset_id,
            "extra": dict(self.extra),
            "family": self.family,
            "join_fields": list(self.join_fields),
            "layout_cid": self.layout_cid,
            "repository": self.repository,
            "role": self.role,
            "root_cid": self.root_cid,
            "root_digest_sha256": self.root_digest_sha256,
            "schema_version": self.schema_version,
        }
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HubIndexFamilyBinding":
        if not isinstance(value, Mapping):
            raise SchemaValidationError("family binding must be a mapping")
        return cls(
            role=str(value.get("role") or ""),
            family=str(value.get("family") or value.get("role") or ""),
            repository=str(value.get("repository") or ""),
            dataset_id=str(value.get("dataset_id") or ""),
            root_cid=str(value.get("root_cid") or ""),
            root_digest_sha256=str(value.get("root_digest_sha256") or ""),
            layout_cid=str(value.get("layout_cid") or ""),
            counts=dict(value.get("counts") or {}),
            configs=tuple(value.get("configs") or ()),
            corpus_root_cid=str(value.get("corpus_root_cid") or ""),
            schema_version=str(value.get("schema_version") or ""),
            join_fields=tuple(value.get("join_fields") or ()),
            extra=dict(value.get("extra") or {}),
        )


@dataclass(frozen=True, slots=True)
class HubIndexPackageCounts:
    """Aggregate counts across corpus and the three index families."""

    corpus_documents: int
    bm25_documents: int
    bm25_terms: int
    bm25_postings: int
    vector_documents: int
    vector_dimension: int
    graph_nodes: int
    graph_edges: int
    artifact_count: int

    def __post_init__(self) -> None:
        for name in (
            "corpus_documents",
            "bm25_documents",
            "bm25_terms",
            "bm25_postings",
            "vector_documents",
            "vector_dimension",
            "graph_nodes",
            "graph_edges",
            "artifact_count",
        ):
            value = int(getattr(self, name))
            if value < 0:
                raise SchemaValidationError(f"{name} must be >= 0")
            object.__setattr__(self, name, value)
        if self.corpus_documents < 1:
            raise PackageIntegrityError("corpus_documents must be >= 1")
        if self.bm25_documents < 1:
            raise MissingIndexFamilyError("bm25_documents must be >= 1")
        if self.vector_documents < 1:
            raise MissingIndexFamilyError("vector_documents must be >= 1")
        if self.graph_nodes < 1:
            raise MissingIndexFamilyError("graph_nodes must be >= 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_count": self.artifact_count,
            "bm25_documents": self.bm25_documents,
            "bm25_postings": self.bm25_postings,
            "bm25_terms": self.bm25_terms,
            "corpus_documents": self.corpus_documents,
            "graph_edges": self.graph_edges,
            "graph_nodes": self.graph_nodes,
            "vector_dimension": self.vector_dimension,
            "vector_documents": self.vector_documents,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HubIndexPackageCounts":
        if not isinstance(value, Mapping):
            raise SchemaValidationError("counts must be a mapping")
        return cls(
            corpus_documents=int(value.get("corpus_documents") or 0),
            bm25_documents=int(value.get("bm25_documents") or 0),
            bm25_terms=int(value.get("bm25_terms") or 0),
            bm25_postings=int(value.get("bm25_postings") or 0),
            vector_documents=int(value.get("vector_documents") or 0),
            vector_dimension=int(value.get("vector_dimension") or 0),
            graph_nodes=int(value.get("graph_nodes") or 0),
            graph_edges=int(value.get("graph_edges") or 0),
            artifact_count=int(value.get("artifact_count") or 0),
        )


@dataclass(frozen=True, slots=True)
class HubIndexPackageManifest:
    """Content-addressed multi-artifact Hub index package manifest.

    Binds corpus + BM25 + vector + graph roots, Viewer layout CIDs, counts,
    and package-level rights/privacy summaries.
    """

    schema_version: str
    interface: str
    task_id: str
    goal_id: str
    producer: str
    config_id: str
    code_version: str
    partition: str
    organization: str
    version_tag: str
    package_root_cid: str
    package_digest_sha256: str
    corpus_root_cid: str
    corpus_digest_sha256: str
    bm25_root_cid: str
    bm25_digest_sha256: str
    vector_root_cid: str
    vector_digest_sha256: str
    graph_root_cid: str
    graph_digest_sha256: str
    layout_bundle_cid: str
    layout_schema_version: str
    counts: HubIndexPackageCounts
    families: tuple[HubIndexFamilyBinding, ...]
    index_families_present: tuple[str, ...]
    rights_summary: Mapping[str, Any]
    privacy_summary: Mapping[str, Any]
    viewer_layouts: Mapping[str, Any]
    artifact_descriptors: tuple[Mapping[str, Any], ...]
    mode: str = PackageMode.DRY_RUN.value
    staged_at_utc: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise SchemaValidationError(
                f"schema_version must be {SCHEMA_VERSION!r}, got {self.schema_version!r}"
            )
        if self.interface != INTERFACE:
            raise SchemaValidationError(f"interface must be {INTERFACE!r}")
        if self.task_id != TASK_ID:
            raise SchemaValidationError(f"task_id must be {TASK_ID}")
        if self.goal_id != GOAL_ID:
            raise SchemaValidationError(f"goal_id must be {GOAL_ID}")
        if self.partition != "public":
            raise PrivateOrMixedPackageError(
                f"partition must be 'public', got {self.partition!r}"
            )
        org = _require_str(self.organization, "organization", maximum=64).lower()
        if org != org.lower():
            raise SchemaValidationError("organization must be lowercase")
        tag = _require_str(self.version_tag, "version_tag", maximum=128)
        present = tuple(
            str(x).strip() for x in (self.index_families_present or ()) if str(x).strip()
        )
        missing = [name for name in INDEX_FAMILIES if name not in present]
        if missing:
            raise MissingIndexFamilyError(
                "missing required index families: " + ", ".join(missing)
            )
        if set(present) != set(INDEX_FAMILIES):
            # Allow only the exact three; no extras that could confuse consumers.
            extra = sorted(set(present) - set(INDEX_FAMILIES))
            if extra:
                raise SchemaValidationError(
                    "unexpected index families: " + ", ".join(extra)
                )
        if not isinstance(self.counts, HubIndexPackageCounts):
            raise SchemaValidationError("counts must be HubIndexPackageCounts")
        families = tuple(self.families or ())
        roles = {f.role for f in families}
        expected_roles = set(REQUIRED_ROLES)
        if roles != expected_roles:
            raise MissingIndexFamilyError(
                f"family bindings incomplete: {sorted(roles)} != {sorted(expected_roles)}"
            )
        corpus_root = _require_cid(self.corpus_root_cid, "corpus_root_cid")
        for binding in families:
            if binding.corpus_root_cid != corpus_root:
                raise CorpusPinMismatchError(
                    f"family {binding.role!r} corpus_root_cid "
                    f"{binding.corpus_root_cid!r} != package {corpus_root!r}"
                )
        rights = dict(self.rights_summary or {})
        privacy = dict(self.privacy_summary or {})
        if not rights:
            raise MissingRightsPrivacyError("manifest.rights_summary is required")
        if not privacy:
            raise MissingRightsPrivacyError("manifest.privacy_summary is required")
        if not rights.get("all_reviewed"):
            raise MissingRightsPrivacyError("rights_summary.all_reviewed must be true")
        if privacy.get("privacy_class") != "public":
            raise MissingRightsPrivacyError(
                "privacy_summary.privacy_class must be 'public'"
            )
        artifacts = tuple(
            MappingProxyType(dict(item))
            for item in (self.artifact_descriptors or ())
        )
        if not artifacts:
            raise PackageIntegrityError("package requires at least one artifact")
        for item in artifacts:
            if "rights_review" not in item or "privacy_review" not in item:
                raise MissingRightsPrivacyError(
                    f"artifact {item.get('relative_path')!r} missing rights/privacy"
                )
            assert_rights_privacy_present(
                rights_review=item.get("rights_review"),
                privacy_review=item.get("privacy_review"),
                label=f"artifact {item.get('relative_path')}",
            )
        object.__setattr__(self, "organization", org)
        object.__setattr__(self, "version_tag", tag)
        object.__setattr__(self, "index_families_present", tuple(INDEX_FAMILIES))
        object.__setattr__(
            self,
            "families",
            tuple(sorted(families, key=lambda f: f.role)),
        )
        object.__setattr__(self, "rights_summary", MappingProxyType(rights))
        object.__setattr__(self, "privacy_summary", MappingProxyType(privacy))
        object.__setattr__(
            self,
            "viewer_layouts",
            MappingProxyType(dict(self.viewer_layouts or {})),
        )
        object.__setattr__(self, "artifact_descriptors", artifacts)
        # Seal content address.
        body = self._content_body()
        digest = content_digest_of(body)
        cid = content_cid_of(body)
        if self.package_digest_sha256 and self.package_digest_sha256 != digest:
            raise PackageIntegrityError("package_digest_sha256 mismatch")
        if self.package_root_cid and self.package_root_cid != cid:
            raise PackageIntegrityError("package_root_cid mismatch")
        object.__setattr__(self, "package_digest_sha256", digest)
        object.__setattr__(self, "package_root_cid", cid)
        object.__setattr__(
            self, "corpus_root_cid", _require_cid(self.corpus_root_cid, "corpus_root_cid")
        )
        object.__setattr__(
            self,
            "corpus_digest_sha256",
            _require_sha256(self.corpus_digest_sha256, "corpus_digest_sha256"),
        )
        object.__setattr__(
            self, "bm25_root_cid", _require_cid(self.bm25_root_cid, "bm25_root_cid")
        )
        object.__setattr__(
            self,
            "bm25_digest_sha256",
            _require_sha256(self.bm25_digest_sha256, "bm25_digest_sha256"),
        )
        object.__setattr__(
            self, "vector_root_cid", _require_cid(self.vector_root_cid, "vector_root_cid")
        )
        object.__setattr__(
            self,
            "vector_digest_sha256",
            _require_sha256(self.vector_digest_sha256, "vector_digest_sha256"),
        )
        object.__setattr__(
            self, "graph_root_cid", _require_cid(self.graph_root_cid, "graph_root_cid")
        )
        object.__setattr__(
            self,
            "graph_digest_sha256",
            _require_sha256(self.graph_digest_sha256, "graph_digest_sha256"),
        )
        object.__setattr__(
            self,
            "layout_bundle_cid",
            _require_cid(self.layout_bundle_cid, "layout_bundle_cid"),
        )
        object.__setattr__(
            self,
            "layout_schema_version",
            _require_str(self.layout_schema_version, "layout_schema_version", maximum=128),
        )

    def _content_body(self) -> dict[str, Any]:
        """Body used for content addressing (excludes mode/staging noise)."""
        return {
            "artifact_descriptors": [dict(item) for item in self.artifact_descriptors],
            "bm25_digest_sha256": self.bm25_digest_sha256,
            "bm25_root_cid": self.bm25_root_cid,
            "code_version": self.code_version,
            "config_id": self.config_id,
            "corpus_digest_sha256": self.corpus_digest_sha256,
            "corpus_root_cid": self.corpus_root_cid,
            "counts": self.counts.to_dict(),
            "families": [f.to_dict() for f in self.families],
            "goal_id": self.goal_id,
            "graph_digest_sha256": self.graph_digest_sha256,
            "graph_root_cid": self.graph_root_cid,
            "index_families_present": list(INDEX_FAMILIES),
            "interface": self.interface,
            "layout_bundle_cid": self.layout_bundle_cid,
            "layout_schema_version": self.layout_schema_version,
            "organization": self.organization,
            "partition": self.partition,
            "privacy_summary": dict(self.privacy_summary),
            "producer": self.producer,
            "rights_summary": dict(self.rights_summary),
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "vector_digest_sha256": self.vector_digest_sha256,
            "vector_root_cid": self.vector_root_cid,
            "version_tag": self.version_tag,
            "viewer_layouts": dict(self.viewer_layouts),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._content_body()
        payload["mode"] = self.mode
        payload["package_digest_sha256"] = self.package_digest_sha256
        payload["package_root_cid"] = self.package_root_cid
        if self.staged_at_utc:
            payload["staged_at_utc"] = self.staged_at_utc
        if self.notes:
            payload["notes"] = self.notes
        return payload

    def to_canonical_bytes(self) -> bytes:
        return canonical_json(self._content_body()).encode("utf-8")

    def to_receipt(self) -> dict[str, Any]:
        """Compact receipt for downstream admission / staging (PATLAW-175+)."""
        return {
            "bm25_root_cid": self.bm25_root_cid,
            "corpus_root_cid": self.corpus_root_cid,
            "counts": self.counts.to_dict(),
            "graph_root_cid": self.graph_root_cid,
            "index_families_present": list(self.index_families_present),
            "layout_bundle_cid": self.layout_bundle_cid,
            "organization": self.organization,
            "package_digest_sha256": self.package_digest_sha256,
            "package_root_cid": self.package_root_cid,
            "partition": self.partition,
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "vector_root_cid": self.vector_root_cid,
            "version_tag": self.version_tag,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HubIndexPackageManifest":
        if not isinstance(value, Mapping):
            raise SchemaValidationError("manifest must be a mapping")
        families = tuple(
            HubIndexFamilyBinding.from_dict(item)
            for item in (value.get("families") or [])
        )
        counts_raw = value.get("counts") or {}
        counts = (
            counts_raw
            if isinstance(counts_raw, HubIndexPackageCounts)
            else HubIndexPackageCounts.from_dict(counts_raw)
        )
        return cls(
            schema_version=str(value.get("schema_version") or SCHEMA_VERSION),
            interface=str(value.get("interface") or INTERFACE),
            task_id=str(value.get("task_id") or TASK_ID),
            goal_id=str(value.get("goal_id") or GOAL_ID),
            producer=str(value.get("producer") or PRODUCER),
            config_id=str(value.get("config_id") or CONFIG_ID),
            code_version=str(value.get("code_version") or CODE_VERSION),
            partition=str(value.get("partition") or "public"),
            organization=str(value.get("organization") or ORGANIZATION),
            version_tag=str(value.get("version_tag") or DEFAULT_VERSION_TAG),
            package_root_cid=str(value.get("package_root_cid") or ""),
            package_digest_sha256=str(value.get("package_digest_sha256") or ""),
            corpus_root_cid=str(value.get("corpus_root_cid") or ""),
            corpus_digest_sha256=str(value.get("corpus_digest_sha256") or ""),
            bm25_root_cid=str(value.get("bm25_root_cid") or ""),
            bm25_digest_sha256=str(value.get("bm25_digest_sha256") or ""),
            vector_root_cid=str(value.get("vector_root_cid") or ""),
            vector_digest_sha256=str(value.get("vector_digest_sha256") or ""),
            graph_root_cid=str(value.get("graph_root_cid") or ""),
            graph_digest_sha256=str(value.get("graph_digest_sha256") or ""),
            layout_bundle_cid=str(value.get("layout_bundle_cid") or ""),
            layout_schema_version=str(
                value.get("layout_schema_version") or HF_LAYOUT_V2_SCHEMA_VERSION
            ),
            counts=counts,
            families=families,
            index_families_present=tuple(value.get("index_families_present") or ()),
            rights_summary=dict(value.get("rights_summary") or {}),
            privacy_summary=dict(value.get("privacy_summary") or {}),
            viewer_layouts=dict(value.get("viewer_layouts") or {}),
            artifact_descriptors=tuple(value.get("artifact_descriptors") or ()),
            mode=str(value.get("mode") or PackageMode.DRY_RUN.value),
            staged_at_utc=str(value.get("staged_at_utc") or ""),
            notes=str(value.get("notes") or ""),
        )


@dataclass(frozen=True, slots=True)
class HubIndexPackage:
    """Complete multi-artifact Hub index package (dry-run or staged)."""

    manifest: HubIndexPackageManifest
    artifacts: tuple[HubIndexPackageArtifact, ...]
    layout_bundle: PatentHubLayoutBundle
    mode: PackageMode = PackageMode.DRY_RUN
    output_dir: Optional[str] = None
    corpus_root_cid: str = ""
    bm25_root_cid: str = ""
    vector_root_cid: str = ""
    graph_root_cid: str = ""

    def __post_init__(self) -> None:
        if not self.artifacts:
            raise PackageIntegrityError("package requires artifacts")
        for art in self.artifacts:
            if not isinstance(art, HubIndexPackageArtifact):
                raise SchemaValidationError("artifacts must be HubIndexPackageArtifact")
        ordered = tuple(sorted(self.artifacts, key=lambda a: a.relative_path))
        paths = [a.relative_path for a in ordered]
        if len(paths) != len(set(paths)):
            raise PackageIntegrityError("duplicate artifact relative_path in package")
        object.__setattr__(self, "artifacts", ordered)
        if not self.corpus_root_cid:
            object.__setattr__(self, "corpus_root_cid", self.manifest.corpus_root_cid)
        if not self.bm25_root_cid:
            object.__setattr__(self, "bm25_root_cid", self.manifest.bm25_root_cid)
        if not self.vector_root_cid:
            object.__setattr__(self, "vector_root_cid", self.manifest.vector_root_cid)
        if not self.graph_root_cid:
            object.__setattr__(self, "graph_root_cid", self.manifest.graph_root_cid)
        if self.manifest.counts.artifact_count != len(ordered):
            raise PackageIntegrityError(
                f"artifact_count {self.manifest.counts.artifact_count} "
                f"!= len(artifacts) {len(ordered)}"
            )

    @property
    def package_root_cid(self) -> str:
        return self.manifest.package_root_cid

    @property
    def package_digest_sha256(self) -> str:
        return self.manifest.package_digest_sha256

    def family_binding(self, role: str | IndexFamily) -> HubIndexFamilyBinding:
        role_value = IndexFamily.coerce(role).value
        for binding in self.manifest.families:
            if binding.role == role_value:
                return binding
        raise MissingIndexFamilyError(f"no family binding for role {role_value!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifacts": [a.descriptor() for a in self.artifacts],
            "bm25_root_cid": self.bm25_root_cid,
            "corpus_root_cid": self.corpus_root_cid,
            "graph_root_cid": self.graph_root_cid,
            "layout_bundle": self.layout_bundle.to_dict(),
            "manifest": self.manifest.to_dict(),
            "mode": self.mode.value if isinstance(self.mode, PackageMode) else str(self.mode),
            "output_dir": self.output_dir,
            "package_digest_sha256": self.package_digest_sha256,
            "package_root_cid": self.package_root_cid,
            "vector_root_cid": self.vector_root_cid,
        }

    def to_canonical_bytes(self) -> bytes:
        """Content-stable package payload excluding staging presentation."""
        payload = {
            "artifacts": [a.descriptor() for a in self.artifacts],
            "layout_bundle_cid": self.layout_bundle.bundle_cid,
            "manifest": self.manifest._content_body(),
            "package_pins": {
                "bm25_root_cid": self.bm25_root_cid,
                "corpus_root_cid": self.corpus_root_cid,
                "graph_root_cid": self.graph_root_cid,
                "package_digest_sha256": self.package_digest_sha256,
                "package_root_cid": self.package_root_cid,
                "vector_root_cid": self.vector_root_cid,
            },
        }
        return canonical_json(payload).encode("utf-8")


# ---------------------------------------------------------------------------
# Coverage from corpus
# ---------------------------------------------------------------------------


def coverage_from_corpus(
    corpus: PublicLegalCorpusMaterialization,
    *,
    model_pin: str = "",
) -> CoverageMetadata:
    """Build Viewer coverage metadata from public legal corpus source roots."""
    sources: list[SourceDisclosure] = []
    for root in corpus.manifest.source_roots:
        current = str(root.current_through or "").strip() or DEFAULT_REVIEWED_AT[:10]
        cutoff = (
            str(root.official_edition_cutoff or "").strip() or current
        )
        family = (
            root.family.value
            if hasattr(root.family, "value")
            else str(root.family)
        )
        sources.append(
            SourceDisclosure(
                source_id=root.source_id,
                license_expression=root.license_expression or DEFAULT_LICENSE,
                official_edition_cutoff=cutoff,
                current_through=current,
                authority_kind=family or "official",
                source_uri=str(root.source_uri or ""),
                source_revision=str(root.source_revision or ""),
                source_cid=str(root.root_cid or ""),
                freshness_note="public legal corpus materialization",
                gaps=tuple(root.gaps or ()),
            )
        )
    if not sources:
        return default_public_coverage()
    models: dict[str, str] = {}
    if model_pin:
        models["embedding"] = model_pin
    return CoverageMetadata(
        sources=tuple(sources),
        parser_versions={
            "public-legal-corpus-materializer": "patent.public_legal_corpus.v1",
            "hub-index-package": SCHEMA_VERSION,
        },
        model_versions=models,
        gaps=(
            "Private matter exports and mixed-rights batches are rejected before packaging.",
        ),
        coverage_notes=(
            "Coverage is public-official / public-user only.",
            f"Corpus root {corpus.corpus_root_cid}",
        ),
    )


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def _dataset_id(organization: str, repository: str) -> str:
    return f"{organization}/{repository}"


def _make_artifact(
    *,
    relative_path: str,
    content: bytes,
    media_type: str,
    role: str,
    family: str,
    rights: RightsReview,
    privacy: PrivacyReview,
    row_count: int = 0,
    config_name: str = "",
    classification: str = "public_official",
) -> HubIndexPackageArtifact:
    return HubIndexPackageArtifact(
        relative_path=relative_path,
        content=content,
        media_type=media_type,
        role=role,
        family=family,
        rights_review=rights,
        privacy_review=privacy,
        classification=classification,
        row_count=row_count,
        config_name=config_name,
    )


def _assert_shared_corpus_root(
    *,
    corpus_root_cid: str,
    bm25: PublicLegalBm25Snapshot,
    vector: PublicLegalVectorBuildResult,
    graph: PublicLegalGraphBuild,
) -> None:
    if bm25.corpus_root_cid != corpus_root_cid:
        raise CorpusPinMismatchError(
            f"BM25 corpus_root_cid {bm25.corpus_root_cid!r} "
            f"!= corpus {corpus_root_cid!r}"
        )
    if vector.corpus_root_cid != corpus_root_cid:
        raise CorpusPinMismatchError(
            f"vector corpus_root_cid {vector.corpus_root_cid!r} "
            f"!= corpus {corpus_root_cid!r}"
        )
    if graph.corpus_root_cid != corpus_root_cid:
        raise CorpusPinMismatchError(
            f"graph corpus_root_cid {graph.corpus_root_cid!r} "
            f"!= corpus {corpus_root_cid!r}"
        )


def _require_index_inputs(
    bm25: PublicLegalBm25Snapshot | None,
    vector: PublicLegalVectorBuildResult | None,
    graph: PublicLegalGraphBuild | None,
) -> tuple[PublicLegalBm25Snapshot, PublicLegalVectorBuildResult, PublicLegalGraphBuild]:
    missing: list[str] = []
    if bm25 is None:
        missing.append("bm25")
    if vector is None:
        missing.append("vectors")
    if graph is None:
        missing.append("knowledge_graph")
    if missing:
        raise MissingIndexFamilyError(
            "missing required index families: " + ", ".join(missing)
        )
    assert bm25 is not None and vector is not None and graph is not None
    return bm25, vector, graph


class HubIndexPackageBuilder:
    """Assemble multi-repo corpus + BM25 + vector + graph Hub packages."""

    def __init__(
        self,
        *,
        organization: str = ORGANIZATION,
        version_tag: str = DEFAULT_VERSION_TAG,
    ) -> None:
        org = str(organization or ORGANIZATION).strip().lower()
        if not org:
            raise SchemaValidationError("organization is required")
        tag = str(version_tag or DEFAULT_VERSION_TAG).strip()
        if not tag:
            raise SchemaValidationError("version_tag is required")
        self.organization = org
        self.version_tag = tag
        self.layout = PatentHubLayoutV2(
            organization=org,
            version_tag=tag,
        )

    def package_from_default_fixture(
        self,
        *,
        stage: bool = False,
        output_dir: PathLike | None = None,
        notes: str = "",
    ) -> HubIndexPackage:
        """Build corpus + three indexes from the CI fixture and package them."""
        recipe = build_default_public_legal_recipe()
        corpus = PublicLegalCorpusMaterializer(
            require_all_families=True
        ).materialize_from_recipe(recipe)
        bm25 = build_public_legal_bm25_index(corpus)
        vector = build_public_legal_vector_index(corpus=corpus)
        graph = build_public_legal_knowledge_graph(materialization=corpus)
        return self.package(
            corpus=corpus,
            bm25=bm25,
            vector=vector,
            graph=graph,
            stage=stage,
            output_dir=output_dir,
            notes=notes,
        )

    def package_from_recipe(
        self,
        recipe: Mapping[str, Any],
        *,
        stage: bool = False,
        output_dir: PathLike | None = None,
        notes: str = "",
        require_all_families: bool = True,
    ) -> HubIndexPackage:
        corpus = PublicLegalCorpusMaterializer(
            require_all_families=require_all_families
        ).materialize_from_recipe(recipe)
        bm25 = build_public_legal_bm25_index(
            corpus, require_all_families=require_all_families
        )
        vector = build_public_legal_vector_index(
            corpus=corpus, require_all_families=require_all_families
        )
        graph = build_public_legal_knowledge_graph(
            materialization=corpus, require_all_families=require_all_families
        )
        return self.package(
            corpus=corpus,
            bm25=bm25,
            vector=vector,
            graph=graph,
            stage=stage,
            output_dir=output_dir,
            notes=notes,
        )

    def package(
        self,
        *,
        corpus: PublicLegalCorpusMaterialization,
        bm25: PublicLegalBm25Snapshot | None = None,
        vector: PublicLegalVectorBuildResult | None = None,
        graph: PublicLegalGraphBuild | None = None,
        stage: bool = False,
        output_dir: PathLike | None = None,
        notes: str = "",
        layout_bundle: PatentHubLayoutBundle | None = None,
        coverage: CoverageMetadata | None = None,
    ) -> HubIndexPackage:
        """Package corpus + three index family snapshots into a Hub release package."""
        if corpus is None:
            raise SchemaValidationError("corpus materialization is required")
        assert_public_only_documents(corpus.documents)
        bm25, vector, graph = _require_index_inputs(bm25, vector, graph)

        # Upstream integrity gates.
        validate_bm25_snapshot(bm25)
        validate_vector_build(vector)
        validate_graph_build(graph)

        corpus_root_cid = str(corpus.corpus_root_cid or "").strip()
        if not corpus_root_cid:
            raise SchemaValidationError("corpus missing corpus_root_cid")
        _assert_shared_corpus_root(
            corpus_root_cid=corpus_root_cid,
            bm25=bm25,
            vector=vector,
            graph=graph,
        )

        rights, privacy = rights_privacy_from_corpus(corpus)
        cov = coverage or coverage_from_corpus(
            corpus, model_pin=str(vector.model_pin or "")
        )
        bundle = layout_bundle or self.layout.build_bundle(
            coverage=cov,
            include_legacy_migration=True,
        )
        if bundle.bundle_cid != (
            layout_bundle.bundle_cid if layout_bundle is not None else bundle.bundle_cid
        ):
            pass  # sealed by PatentHubLayoutBundle

        families = self._build_family_bindings(
            corpus=corpus,
            bm25=bm25,
            vector=vector,
            graph=graph,
            layout_bundle=bundle,
        )
        artifacts = self._build_artifacts(
            corpus=corpus,
            bm25=bm25,
            vector=vector,
            graph=graph,
            layout_bundle=bundle,
            rights=rights,
            privacy=privacy,
        )
        counts = HubIndexPackageCounts(
            corpus_documents=len(corpus.documents),
            bm25_documents=int(bm25.manifest.counts.document_count),
            bm25_terms=int(bm25.manifest.counts.term_count),
            bm25_postings=int(bm25.manifest.counts.posting_count),
            vector_documents=int(vector.manifest.document_count),
            vector_dimension=int(vector.manifest.dimension),
            graph_nodes=int(graph.snapshot.counts.nodes),
            graph_edges=int(graph.snapshot.counts.edges),
            artifact_count=len(artifacts),
        )
        viewer_layouts = {
            "bundle_cid": bundle.bundle_cid,
            "layout_schema_version": HF_LAYOUT_V2_SCHEMA_VERSION,
            "repositories": {
                pkg.identity.role: {
                    "dataset_id": pkg.identity.dataset_id,
                    "layout_cid": pkg.layout_cid,
                    "configs": [cfg.config_name for cfg in pkg.configs],
                }
                for pkg in bundle.packages
            },
            "version_tag": self.version_tag,
        }
        rights_summary = {
            "all_redistribution_allowed": True,
            "all_reviewed": True,
            "license_expressions": sorted(
                {
                    rights.license_expression,
                    *list(corpus.manifest.rights_summary.get("license_expressions") or []),
                }
            ),
            "partition": "public",
            "reviewed_by": sorted(
                {
                    rights.reviewed_by,
                    *list(corpus.manifest.rights_summary.get("reviewed_by") or []),
                }
            ),
            "source_root_licenses": list(
                corpus.manifest.rights_summary.get("source_root_licenses") or []
            ),
        }
        privacy_summary = {
            "all_reviewed": True,
            "partition": "public",
            "privacy_class": "public",
            "reviewed_by": privacy.reviewed_by,
            "reviewed_at": privacy.reviewed_at,
        }
        artifact_descriptors = tuple(a.descriptor() for a in artifacts)

        # First construct without self-pins so __post_init__ seals digests.
        manifest = HubIndexPackageManifest(
            schema_version=SCHEMA_VERSION,
            interface=INTERFACE,
            task_id=TASK_ID,
            goal_id=GOAL_ID,
            producer=PRODUCER,
            config_id=CONFIG_ID,
            code_version=CODE_VERSION,
            partition="public",
            organization=self.organization,
            version_tag=self.version_tag,
            package_root_cid="",
            package_digest_sha256="",
            corpus_root_cid=corpus_root_cid,
            corpus_digest_sha256=str(corpus.manifest.corpus_digest_sha256),
            bm25_root_cid=bm25.index_cid,
            bm25_digest_sha256=bm25.index_digest_sha256,
            vector_root_cid=vector.index_root_cid,
            vector_digest_sha256=vector.index_digest_sha256,
            graph_root_cid=graph.graph_root_cid,
            graph_digest_sha256=graph.graph_digest_sha256,
            layout_bundle_cid=bundle.bundle_cid,
            layout_schema_version=HF_LAYOUT_V2_SCHEMA_VERSION,
            counts=counts,
            families=families,
            index_families_present=INDEX_FAMILIES,
            rights_summary=rights_summary,
            privacy_summary=privacy_summary,
            viewer_layouts=viewer_layouts,
            artifact_descriptors=artifact_descriptors,
            mode=PackageMode.STAGE.value if stage else PackageMode.DRY_RUN.value,
            staged_at_utc=DEFAULT_REVIEWED_AT if stage else "",
            notes=str(notes or ""),
        )

        result = HubIndexPackage(
            manifest=manifest,
            artifacts=artifacts,
            layout_bundle=bundle,
            mode=PackageMode.STAGE if stage else PackageMode.DRY_RUN,
            output_dir=None,
            corpus_root_cid=corpus_root_cid,
            bm25_root_cid=bm25.index_cid,
            vector_root_cid=vector.index_root_cid,
            graph_root_cid=graph.graph_root_cid,
        )

        if stage:
            if output_dir is None:
                raise HubIndexPackageError(
                    "--output-dir / output_dir is required when stage=True"
                )
            return self._stage(result, Path(output_dir))
        return result

    def _build_family_bindings(
        self,
        *,
        corpus: PublicLegalCorpusMaterialization,
        bm25: PublicLegalBm25Snapshot,
        vector: PublicLegalVectorBuildResult,
        graph: PublicLegalGraphBuild,
        layout_bundle: PatentHubLayoutBundle,
    ) -> tuple[HubIndexFamilyBinding, ...]:
        corpus_root = corpus.corpus_root_cid
        bindings: list[HubIndexFamilyBinding] = []

        corpus_pkg = layout_bundle.package_for_role("corpus")
        bindings.append(
            HubIndexFamilyBinding(
                role="corpus",
                family="corpus",
                repository=CORPUS_REPOSITORY,
                dataset_id=_dataset_id(self.organization, CORPUS_REPOSITORY),
                root_cid=corpus.corpus_root_cid,
                root_digest_sha256=corpus.manifest.corpus_digest_sha256,
                layout_cid=corpus_pkg.layout_cid,
                counts=corpus.manifest.counts.to_dict(),
                configs=tuple(cfg.config_name for cfg in corpus_pkg.configs),
                corpus_root_cid=corpus_root,
                schema_version=corpus.manifest.schema_version,
                join_fields=("document_cid", "source_cid", "record_id"),
                extra={
                    "source_root_count": corpus.manifest.counts.source_root_count,
                    "task_id": corpus.manifest.task_id,
                },
            )
        )

        bm25_pkg = layout_bundle.package_for_role("bm25")
        bm25_packaging = bm25_release_packaging_bindings()
        bindings.append(
            HubIndexFamilyBinding(
                role="bm25",
                family="bm25",
                repository=BM25_REPOSITORY,
                dataset_id=_dataset_id(self.organization, BM25_REPOSITORY),
                root_cid=bm25.index_cid,
                root_digest_sha256=bm25.index_digest_sha256,
                layout_cid=bm25_pkg.layout_cid,
                counts=bm25.manifest.counts.to_dict(),
                configs=tuple(cfg.config_name for cfg in bm25_pkg.configs),
                corpus_root_cid=corpus_root,
                schema_version=bm25.manifest.schema_version,
                join_fields=("source_cid", "record_id", "corpus_record_id"),
                extra={
                    "release_packaging": bm25_packaging,
                    "tokenizer_version": bm25.manifest.tokenizer_version,
                    "task_id": bm25.manifest.task_id,
                },
            )
        )

        vec_pkg = layout_bundle.package_for_role("vectors")
        bindings.append(
            HubIndexFamilyBinding(
                role="vectors",
                family="vectors",
                repository=VECTORS_REPOSITORY,
                dataset_id=_dataset_id(self.organization, VECTORS_REPOSITORY),
                root_cid=vector.index_root_cid,
                root_digest_sha256=vector.index_digest_sha256,
                layout_cid=vec_pkg.layout_cid,
                counts={
                    "document_count": vector.manifest.document_count,
                    "vector_count": vector.manifest.vector_count,
                    "dimension": vector.manifest.dimension,
                },
                configs=tuple(cfg.config_name for cfg in vec_pkg.configs),
                corpus_root_cid=corpus_root,
                schema_version=vector.manifest.schema_version,
                join_fields=("source_cid", "record_id", "corpus_record_id"),
                extra={
                    "model_pin": vector.model_pin,
                    "task_id": vector.manifest.task_id,
                },
            )
        )

        graph_pkg = layout_bundle.package_for_role("knowledge_graph")
        bindings.append(
            HubIndexFamilyBinding(
                role="knowledge_graph",
                family="knowledge_graph",
                repository=KNOWLEDGE_GRAPH_REPOSITORY,
                dataset_id=_dataset_id(self.organization, KNOWLEDGE_GRAPH_REPOSITORY),
                root_cid=graph.graph_root_cid,
                root_digest_sha256=graph.graph_digest_sha256,
                layout_cid=graph_pkg.layout_cid,
                counts=graph.snapshot.counts.to_dict(),
                configs=tuple(cfg.config_name for cfg in graph_pkg.configs),
                corpus_root_cid=corpus_root,
                schema_version=graph.snapshot.schema_version,
                join_fields=("source_cid", "node_id", "jsonld_id"),
                extra={
                    "graph_schema_version": graph.snapshot.graph_schema_version,
                    "orphan_check": graph.snapshot.orphan_check,
                    "authority_span_check": graph.snapshot.authority_span_check,
                    "task_id": graph.snapshot.task_id,
                },
            )
        )
        return tuple(bindings)

    def _build_artifacts(
        self,
        *,
        corpus: PublicLegalCorpusMaterialization,
        bm25: PublicLegalBm25Snapshot,
        vector: PublicLegalVectorBuildResult,
        graph: PublicLegalGraphBuild,
        layout_bundle: PatentHubLayoutBundle,
        rights: RightsReview,
        privacy: PrivacyReview,
    ) -> tuple[HubIndexPackageArtifact, ...]:
        artifacts: list[HubIndexPackageArtifact] = []

        # Per-repository Viewer layout cards / configs.
        for pkg in layout_bundle.packages:
            role = pkg.identity.role
            prefix = f"repos/{pkg.identity.repository}"
            for layout_art in pkg.artifacts:
                artifacts.append(
                    _make_artifact(
                        relative_path=f"{prefix}/{layout_art.relative_path}",
                        content=layout_art.content,
                        media_type=layout_art.media_type,
                        role=role,
                        family=role if role in REQUIRED_ROLES else "corpus",
                        rights=rights,
                        privacy=privacy,
                    )
                )

        # Snapshot pin files (compact roots consumed by admission / staging).
        corpus_pin = {
            "corpus_digest_sha256": corpus.manifest.corpus_digest_sha256,
            "corpus_root_cid": corpus.corpus_root_cid,
            "counts": corpus.manifest.counts.to_dict(),
            "schema_version": corpus.manifest.schema_version,
            "task_id": corpus.manifest.task_id,
        }
        artifacts.append(
            _make_artifact(
                relative_path=f"indexes/corpus/{CORPUS_MANIFEST_FILENAME}",
                content=(canonical_json(corpus.manifest.to_dict()) + "\n").encode(
                    "utf-8"
                ),
                media_type="application/json",
                role="corpus",
                family="corpus",
                rights=rights,
                privacy=privacy,
                row_count=len(corpus.documents),
            )
        )
        artifacts.append(
            _make_artifact(
                relative_path="indexes/corpus/corpus-root.json",
                content=(canonical_json(corpus_pin) + "\n").encode("utf-8"),
                media_type="application/json",
                role="corpus",
                family="corpus",
                rights=rights,
                privacy=privacy,
            )
        )

        artifacts.append(
            _make_artifact(
                relative_path=f"indexes/bm25/{BM25_MANIFEST_FILENAME}",
                content=(canonical_json(bm25.manifest.to_dict()) + "\n").encode(
                    "utf-8"
                ),
                media_type="application/json",
                role="bm25",
                family="bm25",
                rights=rights,
                privacy=privacy,
                row_count=bm25.manifest.counts.document_count,
                config_name="bm25_documents",
            )
        )
        bm25_root = {
            "corpus_root_cid": bm25.corpus_root_cid,
            "counts": bm25.manifest.counts.to_dict(),
            "index_cid": bm25.index_cid,
            "index_digest_sha256": bm25.index_digest_sha256,
            "schema_version": bm25.manifest.schema_version,
            "task_id": bm25.manifest.task_id,
        }
        artifacts.append(
            _make_artifact(
                relative_path="indexes/bm25/index-root.json",
                content=(canonical_json(bm25_root) + "\n").encode("utf-8"),
                media_type="application/json",
                role="bm25",
                family="bm25",
                rights=rights,
                privacy=privacy,
            )
        )

        # Bulk BM25 payload (documents / terms / postings) for Hub consumers.
        def _jsonl_bytes(rows: Sequence[Any]) -> bytes:
            lines: list[str] = []
            for row in rows:
                if hasattr(row, "to_dict"):
                    payload = row.to_dict()
                elif isinstance(row, Mapping):
                    payload = dict(row)
                else:
                    payload = {"value": row}
                lines.append(canonical_json(payload))
            return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")

        artifacts.append(
            _make_artifact(
                relative_path="indexes/bm25/bm25-documents.jsonl",
                content=_jsonl_bytes(bm25.documents),
                media_type="application/x-ndjson",
                role="bm25",
                family="bm25",
                rights=rights,
                privacy=privacy,
                row_count=len(bm25.documents),
                config_name="bm25_documents",
            )
        )
        artifacts.append(
            _make_artifact(
                relative_path="indexes/bm25/bm25-terms.jsonl",
                content=_jsonl_bytes(bm25.terms),
                media_type="application/x-ndjson",
                role="bm25",
                family="bm25",
                rights=rights,
                privacy=privacy,
                row_count=len(bm25.terms),
            )
        )
        artifacts.append(
            _make_artifact(
                relative_path="indexes/bm25/bm25-postings.jsonl",
                content=_jsonl_bytes(bm25.postings),
                media_type="application/x-ndjson",
                role="bm25",
                family="bm25",
                rights=rights,
                privacy=privacy,
                row_count=len(bm25.postings),
                config_name="bm25_postings",
            )
        )
        # Viewer-aligned release paths (jsonl; parquet optional elsewhere).
        release_docs = (
            bm25.release_document_rows()
            if callable(getattr(bm25, "release_document_rows", None))
            else bm25.documents
        )
        release_posts = (
            bm25.release_posting_rows()
            if callable(getattr(bm25, "release_posting_rows", None))
            else bm25.postings
        )
        artifacts.append(
            _make_artifact(
                relative_path="data/bm25/documents/train.jsonl",
                content=_jsonl_bytes(release_docs),
                media_type="application/x-ndjson",
                role="bm25",
                family="bm25",
                rights=rights,
                privacy=privacy,
                row_count=len(bm25.documents),
                config_name="bm25_documents",
            )
        )
        artifacts.append(
            _make_artifact(
                relative_path="data/bm25/postings/train.jsonl",
                content=_jsonl_bytes(release_posts),
                media_type="application/x-ndjson",
                role="bm25",
                family="bm25",
                rights=rights,
                privacy=privacy,
                row_count=len(bm25.postings),
                config_name="bm25_postings",
            )
        )

        # Corpus document payloads (full public legal texts).
        artifacts.append(
            _make_artifact(
                relative_path="indexes/corpus/documents.jsonl",
                content=_jsonl_bytes(corpus.documents),
                media_type="application/x-ndjson",
                role="corpus",
                family="corpus",
                rights=rights,
                privacy=privacy,
                row_count=len(corpus.documents),
            )
        )
        artifacts.append(
            _make_artifact(
                relative_path="data/corpus/documents/train.jsonl",
                content=_jsonl_bytes(corpus.documents),
                media_type="application/x-ndjson",
                role="corpus",
                family="corpus",
                rights=rights,
                privacy=privacy,
                row_count=len(corpus.documents),
            )
        )

        artifacts.append(
            _make_artifact(
                relative_path=f"indexes/vectors/{VECTOR_MANIFEST_FILENAME}",
                content=(canonical_json(vector.manifest.to_dict()) + "\n").encode(
                    "utf-8"
                ),
                media_type="application/json",
                role="vectors",
                family="vectors",
                rights=rights,
                privacy=privacy,
                row_count=vector.manifest.document_count,
                config_name="vectors",
            )
        )
        vector_root = {
            "corpus_root_cid": vector.corpus_root_cid,
            "dimension": vector.dimension,
            "document_count": vector.manifest.document_count,
            "index_digest_sha256": vector.index_digest_sha256,
            "index_root_cid": vector.index_root_cid,
            "model_pin": vector.model_pin,
            "schema_version": vector.manifest.schema_version,
            "task_id": vector.manifest.task_id,
        }
        artifacts.append(
            _make_artifact(
                relative_path="indexes/vectors/vector-root.json",
                content=(canonical_json(vector_root) + "\n").encode("utf-8"),
                media_type="application/json",
                role="vectors",
                family="vectors",
                rights=rights,
                privacy=privacy,
            )
        )

        artifacts.append(
            _make_artifact(
                relative_path=f"indexes/knowledge_graph/{GRAPH_SNAPSHOT_FILENAME}",
                content=(canonical_json(graph.snapshot.to_dict()) + "\n").encode(
                    "utf-8"
                ),
                media_type="application/json",
                role="knowledge_graph",
                family="knowledge_graph",
                rights=rights,
                privacy=privacy,
                row_count=graph.snapshot.counts.nodes,
                config_name="graph_nodes",
            )
        )
        graph_root = {
            "corpus_root_cid": graph.corpus_root_cid,
            "counts": graph.snapshot.counts.to_dict(),
            "graph_digest_sha256": graph.graph_digest_sha256,
            "graph_root_cid": graph.graph_root_cid,
            "schema_version": graph.snapshot.schema_version,
            "task_id": graph.snapshot.task_id,
        }
        artifacts.append(
            _make_artifact(
                relative_path="indexes/knowledge_graph/graph-root.json",
                content=(canonical_json(graph_root) + "\n").encode("utf-8"),
                media_type="application/json",
                role="knowledge_graph",
                family="knowledge_graph",
                rights=rights,
                privacy=privacy,
            )
        )

        # Vector payload rows + dense vectors.
        artifacts.append(
            _make_artifact(
                relative_path="indexes/vectors/vector-rows.jsonl",
                content=_jsonl_bytes(vector.rows),
                media_type="application/x-ndjson",
                role="vectors",
                family="vectors",
                rights=rights,
                privacy=privacy,
                row_count=len(vector.rows),
                config_name="vectors",
            )
        )
        artifacts.append(
            _make_artifact(
                relative_path="indexes/vectors/vectors.jsonl",
                content=_jsonl_bytes(vector.vectors),
                media_type="application/x-ndjson",
                role="vectors",
                family="vectors",
                rights=rights,
                privacy=privacy,
                row_count=len(vector.vectors),
                config_name="vectors",
            )
        )
        artifacts.append(
            _make_artifact(
                relative_path="data/vectors/mapping/train.jsonl",
                content=_jsonl_bytes(vector.rows),
                media_type="application/x-ndjson",
                role="vectors",
                family="vectors",
                rights=rights,
                privacy=privacy,
                row_count=len(vector.rows),
                config_name="vectors",
            )
        )

        # Knowledge-graph nodes / edges / json-ld.
        artifacts.append(
            _make_artifact(
                relative_path="indexes/knowledge_graph/nodes.jsonl",
                content=_jsonl_bytes(graph.nodes),
                media_type="application/x-ndjson",
                role="knowledge_graph",
                family="knowledge_graph",
                rights=rights,
                privacy=privacy,
                row_count=len(graph.nodes),
                config_name="graph_nodes",
            )
        )
        artifacts.append(
            _make_artifact(
                relative_path="indexes/knowledge_graph/edges.jsonl",
                content=_jsonl_bytes(graph.edges),
                media_type="application/x-ndjson",
                role="knowledge_graph",
                family="knowledge_graph",
                rights=rights,
                privacy=privacy,
                row_count=len(graph.edges),
                config_name="graph_edges",
            )
        )
        artifacts.append(
            _make_artifact(
                relative_path="indexes/knowledge_graph/graph.jsonld",
                content=(canonical_json(dict(graph.jsonld)) + "\n").encode("utf-8"),
                media_type="application/ld+json",
                role="knowledge_graph",
                family="knowledge_graph",
                rights=rights,
                privacy=privacy,
            )
        )
        artifacts.append(
            _make_artifact(
                relative_path="data/knowledge_graph/nodes/train.jsonl",
                content=_jsonl_bytes(graph.nodes),
                media_type="application/x-ndjson",
                role="knowledge_graph",
                family="knowledge_graph",
                rights=rights,
                privacy=privacy,
                row_count=len(graph.nodes),
                config_name="graph_nodes",
            )
        )
        artifacts.append(
            _make_artifact(
                relative_path="data/knowledge_graph/edges/train.jsonl",
                content=_jsonl_bytes(graph.edges),
                media_type="application/x-ndjson",
                role="knowledge_graph",
                family="knowledge_graph",
                rights=rights,
                privacy=privacy,
                row_count=len(graph.edges),
                config_name="graph_edges",
            )
        )

        # Layout bundle summary (support artifact at package root).
        artifacts.append(
            _make_artifact(
                relative_path=LAYOUT_BUNDLE_FILENAME,
                content=(canonical_json(layout_bundle.to_dict()) + "\n").encode(
                    "utf-8"
                ),
                media_type="application/json",
                role="corpus",
                family="corpus",
                rights=rights,
                privacy=privacy,
            )
        )

        # Fail closed: every artifact must carry rights + privacy (constructor
        # already enforces; re-check inventory for empty descriptors).
        if not artifacts:
            raise PackageIntegrityError("no artifacts produced")
        for art in artifacts:
            assert_rights_privacy_present(
                rights_review=art.rights_review,
                privacy_review=art.privacy_review,
                label=art.relative_path,
            )
        return tuple(sorted(artifacts, key=lambda a: a.relative_path))

    def _stage(self, package: HubIndexPackage, output_dir: Path) -> HubIndexPackage:
        root = Path(output_dir).expanduser().resolve()
        if root.exists() and any(root.iterdir()):
            raise HubIndexPackageError(
                f"output_dir is not empty: {root} (refusing partial stage)"
            )
        _ensure_dir(root)

        # Write each artifact under its relative path.
        for art in package.artifacts:
            target = root / art.relative_path
            _atomic_write_bytes(target, art.content)

        # Package-level support files (also mirrored as inventory entries).
        _atomic_write_text(
            root / MANIFEST_FILENAME,
            canonical_json(package.manifest.to_dict()) + "\n",
        )
        package_root = {
            "bm25_root_cid": package.bm25_root_cid,
            "corpus_root_cid": package.corpus_root_cid,
            "graph_root_cid": package.graph_root_cid,
            "layout_bundle_cid": package.layout_bundle.bundle_cid,
            "package_digest_sha256": package.package_digest_sha256,
            "package_root_cid": package.package_root_cid,
            "schema_version": SCHEMA_VERSION,
            "task_id": TASK_ID,
            "vector_root_cid": package.vector_root_cid,
            "version_tag": package.manifest.version_tag,
        }
        _atomic_write_text(
            root / PACKAGE_ROOT_FILENAME, canonical_json(package_root) + "\n"
        )
        _atomic_write_text(
            root / RECEIPT_FILENAME,
            canonical_json(package.manifest.to_receipt()) + "\n",
        )
        inventory = {
            "artifacts": [a.descriptor() for a in package.artifacts],
            "package_root_cid": package.package_root_cid,
            "schema_version": SCHEMA_VERSION,
            "task_id": TASK_ID,
        }
        _atomic_write_text(
            root / ARTIFACTS_INVENTORY_FILENAME,
            canonical_json(inventory) + "\n",
        )

        # Re-seal manifest in STAGE mode with output path presentation only.
        staged_manifest = HubIndexPackageManifest.from_dict(
            {
                **package.manifest.to_dict(),
                "mode": PackageMode.STAGE.value,
                "staged_at_utc": DEFAULT_REVIEWED_AT,
            }
        )
        # Content pins must remain identical.
        if staged_manifest.package_root_cid != package.package_root_cid:
            raise PackageIntegrityError(
                "staging changed package_root_cid (content address drift)"
            )
        _atomic_write_text(
            root / MANIFEST_FILENAME,
            canonical_json(staged_manifest.to_dict()) + "\n",
        )

        return HubIndexPackage(
            manifest=staged_manifest,
            artifacts=package.artifacts,
            layout_bundle=package.layout_bundle,
            mode=PackageMode.STAGE,
            output_dir=str(root),
            corpus_root_cid=package.corpus_root_cid,
            bm25_root_cid=package.bm25_root_cid,
            vector_root_cid=package.vector_root_cid,
            graph_root_cid=package.graph_root_cid,
        )


# ---------------------------------------------------------------------------
# Validation / public API
# ---------------------------------------------------------------------------


def validate_package(package: HubIndexPackage) -> dict[str, Any]:
    """Return a structured validation receipt for a hub index package."""
    manifest = package.manifest
    if manifest.partition != "public":
        raise PrivateOrMixedPackageError("package partition is not public")
    present = set(manifest.index_families_present)
    missing = [name for name in INDEX_FAMILIES if name not in present]
    if missing:
        raise MissingIndexFamilyError(
            "missing required index families: " + ", ".join(missing)
        )
    roles = {f.role for f in manifest.families}
    for role in REQUIRED_ROLES:
        if role not in roles:
            raise MissingIndexFamilyError(f"missing family binding for {role!r}")
    for art in package.artifacts:
        assert_rights_privacy_present(
            rights_review=art.rights_review,
            privacy_review=art.privacy_review,
            label=art.relative_path,
        )
    recomputed = content_digest_of(manifest._content_body())
    if recomputed != manifest.package_digest_sha256:
        raise PackageIntegrityError("package digest does not match content body")
    if content_cid_of(manifest._content_body()) != manifest.package_root_cid:
        raise PackageIntegrityError("package_root_cid does not match content body")
    return {
        "artifact_count": len(package.artifacts),
        "bm25_root_cid": package.bm25_root_cid,
        "corpus_root_cid": package.corpus_root_cid,
        "graph_root_cid": package.graph_root_cid,
        "index_families_present": list(INDEX_FAMILIES),
        "layout_bundle_cid": package.layout_bundle.bundle_cid,
        "ok": True,
        "package_digest_sha256": package.package_digest_sha256,
        "package_root_cid": package.package_root_cid,
        "partition": "public",
        "rights_privacy_ok": True,
        "task_id": TASK_ID,
        "vector_root_cid": package.vector_root_cid,
    }


def packages_are_byte_identical(
    left: HubIndexPackage, right: HubIndexPackage
) -> bool:
    """Return True when two packages share identical content-stable bytes."""
    return left.to_canonical_bytes() == right.to_canonical_bytes()


def package_patent_legal_hub_indexes(
    *,
    corpus: PublicLegalCorpusMaterialization | None = None,
    bm25: PublicLegalBm25Snapshot | None = None,
    vector: PublicLegalVectorBuildResult | None = None,
    graph: PublicLegalGraphBuild | None = None,
    recipe: Mapping[str, Any] | None = None,
    default_fixture: bool = False,
    organization: str = ORGANIZATION,
    version_tag: str = DEFAULT_VERSION_TAG,
    stage: bool = False,
    output_dir: PathLike | None = None,
    notes: str = "",
) -> HubIndexPackage:
    """Module-level convenience entrypoint for PATLAW-174 packaging."""
    builder = HubIndexPackageBuilder(
        organization=organization,
        version_tag=version_tag,
    )
    if default_fixture or (
        corpus is None and recipe is None and bm25 is None and vector is None and graph is None
    ):
        return builder.package_from_default_fixture(
            stage=stage, output_dir=output_dir, notes=notes
        )
    if recipe is not None and corpus is None:
        return builder.package_from_recipe(
            recipe, stage=stage, output_dir=output_dir, notes=notes
        )
    if corpus is None:
        raise SchemaValidationError(
            "corpus, recipe, or default_fixture is required"
        )
    return builder.package(
        corpus=corpus,
        bm25=bm25,
        vector=vector,
        graph=graph,
        stage=stage,
        output_dir=output_dir,
        notes=notes,
    )


def load_package_manifest(path: PathLike) -> HubIndexPackageManifest:
    """Load and validate a staged hub index package manifest."""
    target = Path(path)
    if not target.is_file():
        raise HubIndexPackageError(f"manifest not found: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HubIndexPackageError(f"invalid manifest JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise HubIndexPackageError("manifest must be a JSON object")
    return HubIndexPackageManifest.from_dict(payload)


def assert_three_index_families_present(
    families: Sequence[str] | Mapping[str, Any] | None,
) -> tuple[str, ...]:
    """Fail closed unless bm25, vectors, and knowledge_graph are all present."""
    if families is None:
        raise MissingIndexFamilyError("index families mapping/list is required")
    if isinstance(families, Mapping):
        present = {
            IndexFamily.coerce(k).value
            for k, v in families.items()
            if v is not None and str(k).strip()
        }
    else:
        present = {IndexFamily.coerce(item).value for item in families}
    # Corpus is not an index family for this gate.
    present_indexes = present & INDEX_FAMILY_SET
    missing = [name for name in INDEX_FAMILIES if name not in present_indexes]
    if missing:
        raise MissingIndexFamilyError(
            "missing required index families: " + ", ".join(missing)
        )
    return INDEX_FAMILIES


__all__ = [
    "ARTIFACTS_INVENTORY_FILENAME",
    "CODE_VERSION",
    "CONFIG_ID",
    "DEFAULT_LICENSE",
    "DEFAULT_PRIVACY_REVIEWER",
    "DEFAULT_REVIEWED_AT",
    "GOAL_ID",
    "INDEX_FAMILIES",
    "INTERFACE",
    "LAYOUT_BUNDLE_FILENAME",
    "MANIFEST_FILENAME",
    "PACKAGE_ROOT_FILENAME",
    "PRODUCER",
    "RECEIPT_FILENAME",
    "REQUIRED_ROLES",
    "SCHEMA_VERSION",
    "TASK_ID",
    "CorpusPinMismatchError",
    "HubIndexFamilyBinding",
    "HubIndexPackage",
    "HubIndexPackageArtifact",
    "HubIndexPackageBuilder",
    "HubIndexPackageCounts",
    "HubIndexPackageError",
    "HubIndexPackageManifest",
    "IndexFamily",
    "MissingIndexFamilyError",
    "MissingRightsPrivacyError",
    "PackageIntegrityError",
    "PackageMode",
    "PrivateOrMixedPackageError",
    "SchemaValidationError",
    "assert_rights_privacy_present",
    "assert_three_index_families_present",
    "canonical_json",
    "content_cid_of",
    "content_digest_of",
    "coverage_from_corpus",
    "default_privacy_review",
    "default_rights_review",
    "load_package_manifest",
    "package_patent_legal_hub_indexes",
    "packages_are_byte_identical",
    "rights_privacy_from_corpus",
    "validate_package",
]
