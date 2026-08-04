"""Viewer-compatible JusticeDAO patent/legal Hub layout contracts (v2).

:class:`PatentHubLayoutV2` owns **layout and migration metadata only**:

* lowercase organization and repository identities;
* corpus repository plus separate vector, BM25, and knowledge-graph repositories;
* root Parquet ``data_files`` patterns that Dataset Viewer can resolve;
* dataset cards, ``dataset_configs.json``, JSON-LD/manifests, version tags;
* coverage / current-through / official-edition cutoff disclosures;
* forward migration pointers so legacy repositories keep their data; and
* a fail-closed ban on private or mixed visibility configs.

This module never authenticates, uploads, renames, or deletes Hub repositories.
Artifact construction lives in PATLAW-157 (``hf_release_v2``); publication in
PATLAW-159/160.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Final, Literal

from ....huggingface.publication_profile import (
    PATENT_LEGAL_DEFAULT_REPOSITORY_ID,
    PATENT_LEGAL_PROGRAM_ID,
)
from ....huggingface.release import canonical_json_bytes
from ....logic.ir_core.identity import cid_v1_from_digest

# ---------------------------------------------------------------------------
# Schema / identity constants
# ---------------------------------------------------------------------------

HF_LAYOUT_V2_SCHEMA_VERSION: Final = "patent-legal-hf-layout/v2"
HF_LAYOUT_V2_PRODUCER: Final = "producer:patent-legal-hf-layout-v2"
HF_LAYOUT_V2_CONFIG: Final = "config:patent-legal-hf-layout/v2"
JSONLD_CONTEXT: Final = "https://justicedao.org/ns/patent-legal-layout/v2"

ORGANIZATION: Final = "justicedao"
# Historical mixed-case org used by v1 profiles; never written as a new identity.
LEGACY_ORGANIZATION_DISPLAY: Final = "JusticeDAO"

VERSION_TAG_PREFIX: Final = "patent-legal-v2"
DEFAULT_VERSION_TAG: Final = f"{VERSION_TAG_PREFIX}.0.0"

# Repository roles in the JusticeDAO multi-repo / multi-config pattern.
RepositoryRole = Literal["corpus", "vectors", "bm25", "knowledge_graph"]
ConfigVisibility = Literal["public"]

CORPUS_REPOSITORY: Final = "patent-legal-corpus"
VECTORS_REPOSITORY: Final = "patent-legal-vectors"
BM25_REPOSITORY: Final = "patent-legal-bm25"
KNOWLEDGE_GRAPH_REPOSITORY: Final = "patent-legal-knowledge-graph"

CANONICAL_REPOSITORY_NAMES: Final[tuple[str, ...]] = (
    CORPUS_REPOSITORY,
    VECTORS_REPOSITORY,
    BM25_REPOSITORY,
    KNOWLEDGE_GRAPH_REPOSITORY,
)

# Legacy v1 single-repo identity (mixed-case Hub path). Kept only as a migration
# source; new layouts always emit lowercase ``justicedao/...`` identities.
LEGACY_V1_REPOSITORY_ID: Final = PATENT_LEGAL_DEFAULT_REPOSITORY_ID
LEGACY_V1_LOWERCASE_ID: Final = "justicedao/patent-legal-public"

# Support filenames written into a staged layout package.
README_FILENAME: Final = "README.md"
DATASET_CONFIGS_FILENAME: Final = "dataset_configs.json"
DATASET_INFOS_FILENAME: Final = "dataset_infos.json"
JSONLD_MANIFEST_FILENAME: Final = "manifest.jsonld"
LAYOUT_MANIFEST_FILENAME: Final = "layout-manifest.json"
MIGRATION_POINTER_FILENAME: Final = "migration-pointer.json"
COVERAGE_FILENAME: Final = "coverage.json"

# Names / tokens that may never appear as declared Hub configs.
_PRIVATE_CONFIG_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "private",
        "confidential",
        "privileged",
        "restricted",
        "secret",
        "credential",
        "mixed",
        "unknown",
        "internal",
        "matter",
        "work_product",
        "work-product",
        "export_review",
        "export-review",
    }
)

_REPO_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,95})$")
_ORG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,38})$")
_CONFIG_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_RFC3339_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CID_RE = re.compile(r"^b[a-z2-7]{20,}$")
_VERSION_TAG_RE = re.compile(
    r"^patent-legal-v2(?:\.[0-9]+){0,3}(?:[-+][A-Za-z0-9._-]+)?$"
)

# Default responsible-use disclosure (always present on public cards).
DEFAULT_RESPONSIBLE_USE: Final[tuple[str, ...]] = (
    "Public official and public-user records only; private, privileged, mixed, "
    "or unknown classifications are never published.",
    "Official editions and cutoffs are disclosed per source; derived text never "
    "impersonates an official edition.",
    "Not legal advice. Not a substitute for counsel, primary sources, or USPTO "
    "filing systems.",
    "Parser and model outputs are non-authoritative candidates until a natural "
    "person reviews them against the bound source spans.",
    "Do not use these datasets to reconstruct confidential applications, "
    "credentials, or non-public matter state.",
)


class PatentHubLayoutError(ValueError):
    """Raised when layout inputs or generated metadata are invalid."""


class PrivateConfigRejectedError(PatentHubLayoutError):
    """Raised when a private or mixed config is declared."""


class ViewerPatternError(PatentHubLayoutError):
    """Raised when a Dataset Viewer data_files pattern cannot resolve."""


# ---------------------------------------------------------------------------
# Path / privacy helpers (used by frozen specs at import time)
# ---------------------------------------------------------------------------


def PurePosixParts(path: str) -> tuple[str, ...]:
    """Split a POSIX relative path; reject empty and parent segments via caller."""

    return tuple(part for part in path.split("/") if part not in ("", "."))


def _reject_private_config_name(name: str) -> None:
    cleaned = str(name or "").strip().lower()
    if not cleaned:
        raise PatentHubLayoutError("config_name is required")
    # Tokenize on non-alphanumeric boundaries.
    tokens = set(re.split(r"[^a-z0-9]+", cleaned))
    tokens.discard("")
    banned = tokens & _PRIVATE_CONFIG_TOKENS
    if banned:
        raise PrivateConfigRejectedError(
            f"private configs cannot be declared: {name!r} "
            f"(banned tokens: {sorted(banned)})"
        )
    # Also reject substring forms like ``private_claims``.
    for token in _PRIVATE_CONFIG_TOKENS:
        if token in cleaned:
            raise PrivateConfigRejectedError(
                f"private configs cannot be declared: {name!r}"
            )


def _assert_unique_config_names(configs: Sequence[HubConfigSpec]) -> None:
    seen: set[str] = set()
    for cfg in configs:
        if cfg.config_name in seen:
            raise PatentHubLayoutError(
                f"duplicate config_name: {cfg.config_name!r}"
            )
        seen.add(cfg.config_name)


def _safe_relative_path(value: str) -> str:
    path = str(value or "").strip().replace("\\", "/")
    if not path or path.startswith("/") or path.endswith("/"):
        raise PatentHubLayoutError(f"invalid relative path: {value!r}")
    parts = PurePosixParts(path)
    if not parts or any(part in {"..", ""} for part in parts):
        raise PatentHubLayoutError(f"unsafe relative path: {value!r}")
    return "/".join(parts)


def _require_lowercase_dataset_id(value: str) -> str:
    dataset_id = str(value or "").strip()
    if "/" not in dataset_id:
        raise PatentHubLayoutError(f"dataset_id must be org/name: {value!r}")
    org, _, repo = dataset_id.partition("/")
    if org != org.lower() or repo != repo.lower():
        raise PatentHubLayoutError(
            f"dataset_id must be lowercase: {dataset_id!r}"
        )
    if not _ORG_RE.fullmatch(org) or not _REPO_NAME_RE.fullmatch(repo):
        raise PatentHubLayoutError(f"invalid dataset_id: {dataset_id!r}")
    return f"{org}/{repo}"


def _normalize_dataset_id_for_pointer(value: str) -> str:
    """Allow legacy mixed-case IDs only as migration *sources*."""

    dataset_id = str(value or "").strip()
    if "/" not in dataset_id:
        raise PatentHubLayoutError(f"dataset_id must be org/name: {value!r}")
    org, _, repo = dataset_id.partition("/")
    if not org or not repo:
        raise PatentHubLayoutError(f"invalid dataset_id: {value!r}")
    # Preserve original spelling for legacy pointers; validate Hub-safe charset.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", org):
        raise PatentHubLayoutError(f"invalid organization in dataset_id: {org!r}")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", repo):
        raise PatentHubLayoutError(f"invalid repository in dataset_id: {repo!r}")
    return f"{org}/{repo}"


# ---------------------------------------------------------------------------
# Specs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HubRepositoryIdentity:
    """Lowercase Hub organization/repository identity."""

    organization: str
    repository: str
    role: RepositoryRole

    def __post_init__(self) -> None:
        org = str(self.organization or "").strip()
        repo = str(self.repository or "").strip()
        if not _ORG_RE.fullmatch(org):
            raise PatentHubLayoutError(
                "organization must be lowercase Hub-safe (justicedao style)"
            )
        if org != org.lower() or any(ch.isupper() for ch in org):
            raise PatentHubLayoutError(
                "organization identity must be entirely lowercase"
            )
        if not _REPO_NAME_RE.fullmatch(repo):
            raise PatentHubLayoutError(
                "repository name must be lowercase Hub-safe"
            )
        if repo != repo.lower() or any(ch.isupper() for ch in repo):
            raise PatentHubLayoutError(
                "repository identity must be entirely lowercase"
            )
        if self.role not in {
            "corpus",
            "vectors",
            "bm25",
            "knowledge_graph",
        }:
            raise PatentHubLayoutError(f"unknown repository role: {self.role!r}")
        object.__setattr__(self, "organization", org)
        object.__setattr__(self, "repository", repo)

    @property
    def dataset_id(self) -> str:
        return f"{self.organization}/{self.repository}"

    def to_dict(self) -> dict[str, str]:
        return {
            "dataset_id": self.dataset_id,
            "organization": self.organization,
            "repository": self.repository,
            "role": self.role,
        }


@dataclass(frozen=True, slots=True)
class HubConfigSpec:
    """One Dataset Viewer configuration with a resolvable Parquet pattern."""

    config_name: str
    data_files_pattern: str
    role: RepositoryRole
    description: str = ""
    split: str = "train"
    visibility: ConfigVisibility = "public"
    media_type: str = "application/vnd.apache.parquet"
    join_fields: tuple[str, ...] = ("source_cid", "record_id")
    features: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        name = str(self.config_name or "").strip()
        pattern = str(self.data_files_pattern or "").strip().replace("\\", "/")
        split = str(self.split or "").strip() or "train"
        visibility = self.visibility
        if visibility != "public":
            raise PrivateConfigRejectedError(
                f"private configs cannot be declared: visibility={visibility!r}"
            )
        _reject_private_config_name(name)
        if not _CONFIG_NAME_RE.fullmatch(name):
            raise PatentHubLayoutError(
                f"config_name must match {_CONFIG_NAME_RE.pattern}: {name!r}"
            )
        if not pattern or pattern.startswith("/") or ".." in PurePosixParts(pattern):
            raise PatentHubLayoutError(
                f"data_files_pattern must be a safe relative path: {pattern!r}"
            )
        if not (
            pattern.endswith(".parquet")
            or pattern.endswith("/*.parquet")
            or "*.parquet" in pattern
        ):
            raise PatentHubLayoutError(
                "data_files_pattern must target Parquet (*.parquet)"
            )
        if self.role not in {
            "corpus",
            "vectors",
            "bm25",
            "knowledge_graph",
        }:
            raise PatentHubLayoutError(f"unknown config role: {self.role!r}")
        joins = tuple(str(item) for item in self.join_fields if str(item).strip())
        feats = tuple(str(item) for item in self.features if str(item).strip())
        object.__setattr__(self, "config_name", name)
        object.__setattr__(self, "data_files_pattern", pattern)
        object.__setattr__(self, "split", split)
        object.__setattr__(self, "visibility", "public")
        object.__setattr__(self, "join_fields", joins)
        object.__setattr__(self, "features", feats)
        object.__setattr__(
            self,
            "description",
            str(self.description or "").strip(),
        )

    def data_files_entry(self) -> dict[str, Any]:
        return {
            "path": self.data_files_pattern,
            "split": self.split,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_name": self.config_name,
            "data_files": [self.data_files_entry()],
            "description": self.description,
            "features": list(self.features),
            "join_fields": list(self.join_fields),
            "media_type": self.media_type,
            "role": self.role,
            "split": self.split,
            "visibility": self.visibility,
        }


@dataclass(frozen=True, slots=True)
class SourceDisclosure:
    """One bound public source with official-edition and freshness metadata."""

    source_id: str
    license_expression: str
    official_edition_cutoff: str
    current_through: str
    authority_kind: str = "official"
    source_uri: str = ""
    source_revision: str = ""
    freshness_note: str = ""
    gaps: tuple[str, ...] = ()
    source_cid: str = ""

    def __post_init__(self) -> None:
        source_id = str(self.source_id or "").strip()
        license_expression = str(self.license_expression or "").strip()
        cutoff = str(self.official_edition_cutoff or "").strip()
        current = str(self.current_through or "").strip()
        if not source_id:
            raise PatentHubLayoutError("source_id is required")
        if not license_expression:
            raise PatentHubLayoutError("license_expression is required")
        if not (_DATE_RE.fullmatch(cutoff) or _RFC3339_UTC_RE.fullmatch(cutoff)):
            raise PatentHubLayoutError(
                "official_edition_cutoff must be YYYY-MM-DD or RFC3339 UTC"
            )
        if not (
            _DATE_RE.fullmatch(current) or _RFC3339_UTC_RE.fullmatch(current)
        ):
            raise PatentHubLayoutError(
                "current_through must be YYYY-MM-DD or RFC3339 UTC"
            )
        cid = str(self.source_cid or "").strip()
        if cid and not _CID_RE.fullmatch(cid):
            raise PatentHubLayoutError(f"source_cid is not a CIDv1: {cid!r}")
        gaps = tuple(str(item).strip() for item in self.gaps if str(item).strip())
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "license_expression", license_expression)
        object.__setattr__(self, "official_edition_cutoff", cutoff)
        object.__setattr__(self, "current_through", current)
        object.__setattr__(self, "source_cid", cid)
        object.__setattr__(self, "gaps", gaps)
        object.__setattr__(
            self, "authority_kind", str(self.authority_kind or "official").strip()
        )
        object.__setattr__(
            self, "source_uri", str(self.source_uri or "").strip()
        )
        object.__setattr__(
            self, "source_revision", str(self.source_revision or "").strip()
        )
        object.__setattr__(
            self, "freshness_note", str(self.freshness_note or "").strip()
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "authority_kind": self.authority_kind,
            "current_through": self.current_through,
            "gaps": list(self.gaps),
            "license_expression": self.license_expression,
            "official_edition_cutoff": self.official_edition_cutoff,
            "source_id": self.source_id,
        }
        if self.source_uri:
            payload["source_uri"] = self.source_uri
        if self.source_revision:
            payload["source_revision"] = self.source_revision
        if self.freshness_note:
            payload["freshness_note"] = self.freshness_note
        if self.source_cid:
            payload["source_cid"] = self.source_cid
        return payload


@dataclass(frozen=True, slots=True)
class CoverageMetadata:
    """Card-level coverage, freshness, gaps, and tool versions."""

    sources: tuple[SourceDisclosure, ...]
    parser_versions: Mapping[str, str] = field(default_factory=dict)
    model_versions: Mapping[str, str] = field(default_factory=dict)
    gaps: tuple[str, ...] = ()
    responsible_use: tuple[str, ...] = DEFAULT_RESPONSIBLE_USE
    coverage_notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.sources:
            raise PatentHubLayoutError(
                "coverage requires at least one source disclosure"
            )
        sources = tuple(self.sources)
        parsers = {
            str(k).strip(): str(v).strip()
            for k, v in dict(self.parser_versions).items()
            if str(k).strip() and str(v).strip()
        }
        models = {
            str(k).strip(): str(v).strip()
            for k, v in dict(self.model_versions).items()
            if str(k).strip() and str(v).strip()
        }
        gaps = tuple(str(item).strip() for item in self.gaps if str(item).strip())
        # Aggregate source-level gaps into the top-level list for card rendering.
        source_gaps = tuple(
            f"{src.source_id}: {gap}"
            for src in sources
            for gap in src.gaps
        )
        merged_gaps = tuple(dict.fromkeys((*gaps, *source_gaps)))
        use = tuple(
            str(item).strip()
            for item in (self.responsible_use or DEFAULT_RESPONSIBLE_USE)
            if str(item).strip()
        )
        if not use:
            raise PatentHubLayoutError("responsible_use disclosures are required")
        notes = tuple(
            str(item).strip() for item in self.coverage_notes if str(item).strip()
        )
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "parser_versions", MappingProxyType(parsers))
        object.__setattr__(self, "model_versions", MappingProxyType(models))
        object.__setattr__(self, "gaps", merged_gaps)
        object.__setattr__(self, "responsible_use", use)
        object.__setattr__(self, "coverage_notes", notes)

    @property
    def licenses(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(src.license_expression for src in self.sources)
        )

    @property
    def official_edition_cutoffs(self) -> Mapping[str, str]:
        return MappingProxyType(
            {src.source_id: src.official_edition_cutoff for src in self.sources}
        )

    @property
    def current_through(self) -> Mapping[str, str]:
        return MappingProxyType(
            {src.source_id: src.current_through for src in self.sources}
        )

    @property
    def freshness(self) -> Mapping[str, str]:
        """Per-source freshness: current_through plus optional free-text note."""

        result: dict[str, str] = {}
        for src in self.sources:
            if src.freshness_note:
                result[src.source_id] = (
                    f"{src.current_through} ({src.freshness_note})"
                )
            else:
                result[src.source_id] = src.current_through
        return MappingProxyType(result)

    def to_dict(self) -> dict[str, Any]:
        return {
            "coverage_notes": list(self.coverage_notes),
            "current_through": dict(self.current_through),
            "freshness": dict(self.freshness),
            "gaps": list(self.gaps),
            "licenses": list(self.licenses),
            "model_versions": dict(self.model_versions),
            "official_edition_cutoffs": dict(self.official_edition_cutoffs),
            "parser_versions": dict(self.parser_versions),
            "responsible_use": list(self.responsible_use),
            "sources": [src.to_dict() for src in self.sources],
        }


@dataclass(frozen=True, slots=True)
class MigrationPointer:
    """Forward pointer from a legacy repository to a canonical v2 target.

    Legacy repository content is retained. The pointer is additive metadata only;
    callers must never treat it as authorization to delete historical shards.
    """

    legacy_dataset_id: str
    target_dataset_id: str
    target_version_tag: str
    target_revision: str = ""
    target_layout_cid: str = ""
    preserves_legacy_data: bool = True
    deletion_allowed: bool = False
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        legacy = _normalize_dataset_id_for_pointer(self.legacy_dataset_id)
        target = _require_lowercase_dataset_id(self.target_dataset_id)
        tag = str(self.target_version_tag or "").strip()
        if not _VERSION_TAG_RE.fullmatch(tag):
            raise PatentHubLayoutError(
                f"target_version_tag must match patent-legal-v2*: {tag!r}"
            )
        if self.deletion_allowed:
            raise PatentHubLayoutError(
                "migration pointers must not authorize data deletion"
            )
        if not self.preserves_legacy_data:
            raise PatentHubLayoutError(
                "migration pointers must preserve legacy repository data"
            )
        cid = str(self.target_layout_cid or "").strip()
        if cid and not _CID_RE.fullmatch(cid):
            raise PatentHubLayoutError(
                f"target_layout_cid is not a CIDv1: {cid!r}"
            )
        notes = tuple(str(item).strip() for item in self.notes if str(item).strip())
        object.__setattr__(self, "legacy_dataset_id", legacy)
        object.__setattr__(self, "target_dataset_id", target)
        object.__setattr__(self, "target_version_tag", tag)
        object.__setattr__(
            self, "target_revision", str(self.target_revision or "").strip()
        )
        object.__setattr__(self, "target_layout_cid", cid)
        object.__setattr__(self, "preserves_legacy_data", True)
        object.__setattr__(self, "deletion_allowed", False)
        object.__setattr__(self, "notes", notes)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "deletion_allowed": False,
            "legacy_dataset_id": self.legacy_dataset_id,
            "preserves_legacy_data": True,
            "schema_version": HF_LAYOUT_V2_SCHEMA_VERSION,
            "target_dataset_id": self.target_dataset_id,
            "target_version_tag": self.target_version_tag,
        }
        if self.target_revision:
            payload["target_revision"] = self.target_revision
        if self.target_layout_cid:
            payload["target_layout_cid"] = self.target_layout_cid
        if self.notes:
            payload["notes"] = list(self.notes)
        return payload


@dataclass(frozen=True, slots=True)
class LayoutArtifact:
    """One generated text/JSON support file for a repository layout package."""

    relative_path: str
    content: bytes = field(repr=False)
    media_type: str
    sha256: str = ""
    content_cid: str = ""
    size_bytes: int = 0

    def __post_init__(self) -> None:
        path = _safe_relative_path(self.relative_path)
        if not isinstance(self.content, (bytes, bytearray)):
            raise PatentHubLayoutError("artifact content must be bytes")
        content = bytes(self.content)
        digest = hashlib.sha256(content).hexdigest()
        cid = cid_v1_from_digest(bytes.fromhex(digest))
        if self.sha256 and self.sha256 != digest:
            raise PatentHubLayoutError(f"sha256 mismatch for {path}")
        if self.content_cid and self.content_cid != cid:
            raise PatentHubLayoutError(f"content_cid mismatch for {path}")
        object.__setattr__(self, "relative_path", path)
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "sha256", digest)
        object.__setattr__(self, "content_cid", cid)
        object.__setattr__(self, "size_bytes", len(content))

    def descriptor(self) -> dict[str, Any]:
        return {
            "content_cid": self.content_cid,
            "media_type": self.media_type,
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }

    def text(self) -> str:
        return self.content.decode("utf-8")


@dataclass(frozen=True, slots=True)
class RepositoryLayoutPackage:
    """Complete Viewer-compatible layout package for one repository."""

    identity: HubRepositoryIdentity
    configs: tuple[HubConfigSpec, ...]
    coverage: CoverageMetadata
    version_tag: str
    artifacts: tuple[LayoutArtifact, ...]
    migration_pointers: tuple[MigrationPointer, ...] = ()
    layout_cid: str = ""

    def __post_init__(self) -> None:
        if not self.configs:
            raise PatentHubLayoutError("repository layout requires configs")
        for cfg in self.configs:
            if cfg.role != self.identity.role and self.identity.role == "corpus":
                # Corpus repo may only host corpus-role configs.
                if cfg.role != "corpus":
                    raise PatentHubLayoutError(
                        f"config {cfg.config_name!r} role {cfg.role!r} "
                        f"does not match repository role {self.identity.role!r}"
                    )
            elif cfg.role != self.identity.role:
                raise PatentHubLayoutError(
                    f"config {cfg.config_name!r} role {cfg.role!r} "
                    f"does not match repository role {self.identity.role!r}"
                )
        tag = str(self.version_tag or "").strip()
        if not _VERSION_TAG_RE.fullmatch(tag):
            raise PatentHubLayoutError(f"invalid version_tag: {tag!r}")
        arts = tuple(
            sorted(self.artifacts, key=lambda item: item.relative_path)
        )
        pointers = tuple(self.migration_pointers)
        root = _layout_package_cid(
            identity=self.identity,
            configs=self.configs,
            coverage=self.coverage,
            version_tag=tag,
            artifacts=arts,
            migration_pointers=pointers,
        )
        if self.layout_cid and self.layout_cid != root:
            raise PatentHubLayoutError("layout_cid mismatch")
        object.__setattr__(self, "version_tag", tag)
        object.__setattr__(self, "artifacts", arts)
        object.__setattr__(self, "migration_pointers", pointers)
        object.__setattr__(self, "layout_cid", root)

    def artifact(self, relative_path: str) -> LayoutArtifact:
        for item in self.artifacts:
            if item.relative_path == relative_path:
                return item
        raise PatentHubLayoutError(f"artifact not found: {relative_path!r}")

    def dataset_card_text(self) -> str:
        return self.artifact(README_FILENAME).text()

    def dataset_configs(self) -> dict[str, Any]:
        return json.loads(self.artifact(DATASET_CONFIGS_FILENAME).text())

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifacts": [item.descriptor() for item in self.artifacts],
            "configs": [item.to_dict() for item in self.configs],
            "coverage": self.coverage.to_dict(),
            "identity": self.identity.to_dict(),
            "layout_cid": self.layout_cid,
            "migration_pointers": [item.to_dict() for item in self.migration_pointers],
            "schema_version": HF_LAYOUT_V2_SCHEMA_VERSION,
            "version_tag": self.version_tag,
        }


@dataclass(frozen=True, slots=True)
class PatentHubLayoutBundle:
    """All four canonical repository layout packages plus family metadata."""

    packages: tuple[RepositoryLayoutPackage, ...]
    version_tag: str
    program_id: str = PATENT_LEGAL_PROGRAM_ID
    schema_version: str = HF_LAYOUT_V2_SCHEMA_VERSION
    bundle_cid: str = ""

    def __post_init__(self) -> None:
        if len(self.packages) != 4:
            raise PatentHubLayoutError(
                "bundle requires corpus, vectors, bm25, and knowledge_graph packages"
            )
        roles = {pkg.identity.role for pkg in self.packages}
        expected = {"corpus", "vectors", "bm25", "knowledge_graph"}
        if roles != expected:
            raise PatentHubLayoutError(
                f"bundle roles incomplete: {sorted(roles)} != {sorted(expected)}"
            )
        tag = str(self.version_tag or "").strip()
        if not _VERSION_TAG_RE.fullmatch(tag):
            raise PatentHubLayoutError(f"invalid version_tag: {tag!r}")
        for pkg in self.packages:
            if pkg.version_tag != tag:
                raise PatentHubLayoutError(
                    "all packages in a bundle must share the version_tag"
                )
        ordered = tuple(
            sorted(self.packages, key=lambda item: item.identity.dataset_id)
        )
        digest = hashlib.sha256(
            canonical_json_bytes(
                {
                    "packages": [pkg.layout_cid for pkg in ordered],
                    "program_id": self.program_id,
                    "schema_version": self.schema_version,
                    "version_tag": tag,
                }
            )
        ).digest()
        root = cid_v1_from_digest(digest)
        if self.bundle_cid and self.bundle_cid != root:
            raise PatentHubLayoutError("bundle_cid mismatch")
        object.__setattr__(self, "packages", ordered)
        object.__setattr__(self, "version_tag", tag)
        object.__setattr__(self, "bundle_cid", root)

    def package_for_role(self, role: RepositoryRole) -> RepositoryLayoutPackage:
        for pkg in self.packages:
            if pkg.identity.role == role:
                return pkg
        raise PatentHubLayoutError(f"no package for role {role!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_cid": self.bundle_cid,
            "packages": [pkg.to_dict() for pkg in self.packages],
            "program_id": self.program_id,
            "schema_version": self.schema_version,
            "version_tag": self.version_tag,
        }


# ---------------------------------------------------------------------------
# Canonical config catalogs
# ---------------------------------------------------------------------------


def _corpus_configs() -> tuple[HubConfigSpec, ...]:
    """Official law + public patent corpus configs (Viewer root patterns)."""

    families: tuple[tuple[str, str], ...] = (
        ("usc", "United States Code (official edition projection)"),
        ("cfr", "Code of Federal Regulations (official edition projection)"),
        ("public_law", "Public Laws / Statutes at Large projections"),
        ("federal_register", "Federal Register public documents"),
        ("projected_rules", "Projected / proposed rulemakings (nonbinding)"),
        ("applications", "Public patent applications"),
        ("claims", "Public patent claims"),
        ("events", "Public prosecution events"),
        ("office_actions", "Public office actions"),
        ("citations", "Public citation graph edges as rows"),
    )
    return tuple(
        HubConfigSpec(
            config_name=name,
            data_files_pattern=f"data/{name}/*.parquet",
            role="corpus",
            description=description,
            join_fields=("source_cid", "record_id", "content_cid"),
            features=(
                "record_id",
                "artifact_kind",
                "classification",
                "source_cid",
                "content_cid",
                "record_sha256",
                "text",
            ),
        )
        for name, description in families
    )


def _vector_configs() -> tuple[HubConfigSpec, ...]:
    return (
        HubConfigSpec(
            config_name="vectors",
            data_files_pattern="data/vectors/*.parquet",
            role="vectors",
            description="Public embedding shards bound to corpus source CIDs",
            join_fields=("source_cid", "record_id", "corpus_record_id"),
            features=(
                "record_id",
                "corpus_record_id",
                "source_cid",
                "model_id",
                "model_revision",
                "embedding_dim",
                "has_embedding",
            ),
        ),
        HubConfigSpec(
            config_name="vector_chunk_index",
            data_files_pattern="indexes/vector_chunks.parquet",
            role="vectors",
            description="Compact routing index for remote vector probes",
            join_fields=("shard_cid", "relative_path"),
            features=(
                "shard_id",
                "relative_path",
                "sha256",
                "cid",
                "row_count",
                "start_document_index",
                "end_document_index",
            ),
        ),
    )


def _bm25_configs() -> tuple[HubConfigSpec, ...]:
    return (
        HubConfigSpec(
            config_name="bm25_documents",
            data_files_pattern="data/bm25/documents/*.parquet",
            role="bm25",
            description="BM25 document table joined to public corpus CIDs",
            join_fields=("source_cid", "record_id", "corpus_record_id"),
            features=(
                "record_id",
                "corpus_record_id",
                "source_cid",
                "text_preview",
                "token_count",
            ),
        ),
        HubConfigSpec(
            config_name="bm25_postings",
            data_files_pattern="data/bm25/postings/*.parquet",
            role="bm25",
            description="BM25 postings / dictionary shards",
            join_fields=("term", "document_id"),
            features=("term", "document_id", "tf", "df"),
        ),
    )


def _knowledge_graph_configs() -> tuple[HubConfigSpec, ...]:
    return (
        HubConfigSpec(
            config_name="graph_nodes",
            data_files_pattern="data/graph/nodes/*.parquet",
            role="knowledge_graph",
            description="Knowledge-graph nodes joined to public source CIDs",
            join_fields=("source_cid", "node_id", "jsonld_id"),
            features=(
                "node_id",
                "jsonld_id",
                "label",
                "kind",
                "source_cid",
            ),
        ),
        HubConfigSpec(
            config_name="graph_edges",
            data_files_pattern="data/graph/edges/*.parquet",
            role="knowledge_graph",
            description="Knowledge-graph edges with CID-joined endpoints",
            join_fields=("source_cid", "src_node_id", "dst_node_id"),
            features=(
                "edge_id",
                "src_node_id",
                "dst_node_id",
                "relation",
                "source_cid",
            ),
        ),
        HubConfigSpec(
            config_name="graph_node_chunk_index",
            data_files_pattern="indexes/graph_node_chunks.parquet",
            role="knowledge_graph",
            description="Routing index for graph node shards",
            join_fields=("shard_cid", "relative_path"),
            features=(
                "shard_id",
                "relative_path",
                "sha256",
                "cid",
                "row_count",
            ),
        ),
        HubConfigSpec(
            config_name="graph_edge_chunk_index",
            data_files_pattern="indexes/graph_edge_chunks.parquet",
            role="knowledge_graph",
            description="Routing index for graph edge shards",
            join_fields=("shard_cid", "relative_path"),
            features=(
                "shard_id",
                "relative_path",
                "sha256",
                "cid",
                "row_count",
            ),
        ),
    )


CANONICAL_CONFIGS_BY_ROLE: Final[Mapping[RepositoryRole, tuple[HubConfigSpec, ...]]] = (
    MappingProxyType(
        {
            "corpus": _corpus_configs(),
            "vectors": _vector_configs(),
            "bm25": _bm25_configs(),
            "knowledge_graph": _knowledge_graph_configs(),
        }
    )
)


def canonical_repository_identities(
    *,
    organization: str = ORGANIZATION,
) -> tuple[HubRepositoryIdentity, ...]:
    """Return the four canonical lowercase repository identities."""

    mapping: tuple[tuple[str, RepositoryRole], ...] = (
        (CORPUS_REPOSITORY, "corpus"),
        (VECTORS_REPOSITORY, "vectors"),
        (BM25_REPOSITORY, "bm25"),
        (KNOWLEDGE_GRAPH_REPOSITORY, "knowledge_graph"),
    )
    return tuple(
        HubRepositoryIdentity(
            organization=organization,
            repository=name,
            role=role,
        )
        for name, role in mapping
    )


def legacy_repository_inventory() -> tuple[dict[str, Any], ...]:
    """Immutable operator inventory of known legacy / v1 Hub identities.

    Used only to attach forward migration pointers. Data in these repositories
    is retained; pointers never authorize deletion or force-push rewrite.
    """

    return (
        {
            "dataset_id": LEGACY_V1_REPOSITORY_ID,
            "normalized_dataset_id": LEGACY_V1_LOWERCASE_ID,
            "role": "legacy_monorepo_v1",
            "viewer_failures": (
                "mixed multi-kind configs without stable root Parquet patterns",
                "missing official-edition cutoff / current-through card fields",
                "no separate vector/BM25/knowledge-graph repository split",
            ),
            "migration_target_role": "corpus",
            "preserves_data": True,
        },
        {
            "dataset_id": LEGACY_V1_LOWERCASE_ID,
            "normalized_dataset_id": LEGACY_V1_LOWERCASE_ID,
            "role": "legacy_monorepo_v1_lowercase",
            "viewer_failures": (
                "same as mixed-case v1 monorepo when present",
            ),
            "migration_target_role": "corpus",
            "preserves_data": True,
        },
    )


# ---------------------------------------------------------------------------
# PatentHubLayoutV2
# ---------------------------------------------------------------------------


class PatentHubLayoutV2:
    """Build and validate Viewer-compatible JusticeDAO layout packages."""

    def __init__(
        self,
        *,
        organization: str = ORGANIZATION,
        version_tag: str = DEFAULT_VERSION_TAG,
        program_id: str = PATENT_LEGAL_PROGRAM_ID,
    ) -> None:
        org = str(organization or "").strip()
        if org != org.lower() or not _ORG_RE.fullmatch(org):
            raise PatentHubLayoutError(
                "organization must be lowercase (e.g. 'justicedao')"
            )
        tag = str(version_tag or "").strip()
        if not _VERSION_TAG_RE.fullmatch(tag):
            raise PatentHubLayoutError(f"invalid version_tag: {tag!r}")
        self.organization = org
        self.version_tag = tag
        self.program_id = str(program_id or PATENT_LEGAL_PROGRAM_ID).strip()
        self.identities = canonical_repository_identities(organization=org)

    # -- catalogs -----------------------------------------------------------

    def repository_identities(self) -> tuple[HubRepositoryIdentity, ...]:
        return self.identities

    def configs_for_role(self, role: RepositoryRole) -> tuple[HubConfigSpec, ...]:
        if role not in CANONICAL_CONFIGS_BY_ROLE:
            raise PatentHubLayoutError(f"unknown role: {role!r}")
        return CANONICAL_CONFIGS_BY_ROLE[role]

    def all_config_names(self) -> tuple[str, ...]:
        names: list[str] = []
        for role in ("corpus", "vectors", "bm25", "knowledge_graph"):
            for cfg in self.configs_for_role(role):  # type: ignore[arg-type]
                names.append(cfg.config_name)
        return tuple(names)

    # -- generation ---------------------------------------------------------

    def build_repository_package(
        self,
        *,
        role: RepositoryRole,
        coverage: CoverageMetadata,
        migration_pointers: Sequence[MigrationPointer] | None = None,
        extra_configs: Sequence[HubConfigSpec] | None = None,
    ) -> RepositoryLayoutPackage:
        """Generate cards/configs/manifests for one repository role."""

        identity = self._identity_for_role(role)
        configs = list(self.configs_for_role(role))
        if extra_configs:
            for cfg in extra_configs:
                _reject_private_config_name(cfg.config_name)
                if cfg.visibility != "public":
                    raise PrivateConfigRejectedError(
                        "private configs cannot be declared"
                    )
                if cfg.role != role:
                    raise PatentHubLayoutError(
                        f"extra config role {cfg.role!r} != repository role {role!r}"
                    )
                configs.append(cfg)
        # Stable order by config_name.
        ordered_configs = tuple(sorted(configs, key=lambda item: item.config_name))
        _assert_unique_config_names(ordered_configs)
        pointers = tuple(migration_pointers or ())
        for pointer in pointers:
            if pointer.target_dataset_id != identity.dataset_id:
                raise PatentHubLayoutError(
                    "migration pointer target must match package dataset_id"
                )
            if pointer.target_version_tag != self.version_tag:
                raise PatentHubLayoutError(
                    "migration pointer version_tag must match layout version_tag"
                )

        card = render_dataset_card(
            identity=identity,
            configs=ordered_configs,
            coverage=coverage,
            version_tag=self.version_tag,
            migration_pointers=pointers,
        )
        dataset_configs = build_dataset_configs(
            identity=identity,
            configs=ordered_configs,
            version_tag=self.version_tag,
        )
        dataset_infos = build_dataset_infos(
            identity=identity,
            configs=ordered_configs,
        )
        jsonld = build_jsonld_manifest(
            identity=identity,
            configs=ordered_configs,
            coverage=coverage,
            version_tag=self.version_tag,
        )
        coverage_doc = {
            "dataset_id": identity.dataset_id,
            "schema_version": HF_LAYOUT_V2_SCHEMA_VERSION,
            "version_tag": self.version_tag,
            **coverage.to_dict(),
        }
        layout_manifest = {
            "configs": [cfg.to_dict() for cfg in ordered_configs],
            "dataset_id": identity.dataset_id,
            "producer": HF_LAYOUT_V2_PRODUCER,
            "program_id": self.program_id,
            "role": identity.role,
            "schema_version": HF_LAYOUT_V2_SCHEMA_VERSION,
            "version_tag": self.version_tag,
        }

        artifacts = [
            LayoutArtifact(
                relative_path=README_FILENAME,
                content=card.encode("utf-8"),
                media_type="text/markdown; charset=utf-8",
            ),
            LayoutArtifact(
                relative_path=DATASET_CONFIGS_FILENAME,
                content=canonical_json_bytes(dataset_configs) + b"\n",
                media_type="application/json",
            ),
            LayoutArtifact(
                relative_path=DATASET_INFOS_FILENAME,
                content=canonical_json_bytes(dataset_infos) + b"\n",
                media_type="application/json",
            ),
            LayoutArtifact(
                relative_path=JSONLD_MANIFEST_FILENAME,
                content=canonical_json_bytes(jsonld) + b"\n",
                media_type="application/ld+json",
            ),
            LayoutArtifact(
                relative_path=COVERAGE_FILENAME,
                content=canonical_json_bytes(coverage_doc) + b"\n",
                media_type="application/json",
            ),
            LayoutArtifact(
                relative_path=LAYOUT_MANIFEST_FILENAME,
                content=canonical_json_bytes(layout_manifest) + b"\n",
                media_type="application/json",
            ),
        ]
        if pointers:
            pointer_doc = {
                "pointers": [item.to_dict() for item in pointers],
                "preserves_legacy_data": True,
                "schema_version": HF_LAYOUT_V2_SCHEMA_VERSION,
            }
            artifacts.append(
                LayoutArtifact(
                    relative_path=MIGRATION_POINTER_FILENAME,
                    content=canonical_json_bytes(pointer_doc) + b"\n",
                    media_type="application/json",
                )
            )

        return RepositoryLayoutPackage(
            identity=identity,
            configs=ordered_configs,
            coverage=coverage,
            version_tag=self.version_tag,
            artifacts=tuple(artifacts),
            migration_pointers=pointers,
        )

    def build_bundle(
        self,
        *,
        coverage: CoverageMetadata,
        include_legacy_migration: bool = True,
    ) -> PatentHubLayoutBundle:
        """Build the four-repository layout bundle with optional v1 pointers."""

        packages: list[RepositoryLayoutPackage] = []
        for role in ("corpus", "vectors", "bm25", "knowledge_graph"):
            pointers: list[MigrationPointer] = []
            if include_legacy_migration and role == "corpus":
                identity = self._identity_for_role("corpus")
                for legacy in legacy_repository_inventory():
                    pointers.append(
                        MigrationPointer(
                            legacy_dataset_id=str(legacy["dataset_id"]),
                            target_dataset_id=identity.dataset_id,
                            target_version_tag=self.version_tag,
                            notes=(
                                "Forward pointer only; legacy shards are retained.",
                                "Do not delete or force-push the legacy repository.",
                            ),
                        )
                    )
            packages.append(
                self.build_repository_package(
                    role=role,  # type: ignore[arg-type]
                    coverage=coverage,
                    migration_pointers=pointers,
                )
            )
        return PatentHubLayoutBundle(
            packages=tuple(packages),
            version_tag=self.version_tag,
            program_id=self.program_id,
        )

    def build_legacy_forward_pointer(
        self,
        *,
        legacy_dataset_id: str,
        target_role: RepositoryRole = "corpus",
        target_revision: str = "",
        target_layout_cid: str = "",
        notes: Sequence[str] = (),
    ) -> MigrationPointer:
        """Create a non-destructive forward pointer for a legacy repository."""

        target = self._identity_for_role(target_role)
        return MigrationPointer(
            legacy_dataset_id=legacy_dataset_id,
            target_dataset_id=target.dataset_id,
            target_version_tag=self.version_tag,
            target_revision=target_revision,
            target_layout_cid=target_layout_cid,
            notes=tuple(notes)
            or (
                "Forward pointer only; legacy repository data is preserved.",
            ),
        )

    # -- viewer resolution --------------------------------------------------

    def resolve_viewer_patterns(
        self,
        *,
        role: RepositoryRole,
        relative_paths: Sequence[str],
        configs: Sequence[HubConfigSpec] | None = None,
    ) -> dict[str, Any]:
        """Match staged relative paths against config data_files patterns.

        Every declared config must resolve at least one path (unless the path
        list is empty, in which case patterns are only syntax-validated). Paths
        that match no config are reported but do not fail resolution by default.
        """

        specs = tuple(configs) if configs is not None else self.configs_for_role(role)
        _assert_unique_config_names(specs)
        for cfg in specs:
            if cfg.visibility != "public":
                raise PrivateConfigRejectedError(
                    "private configs cannot be declared"
                )
            _reject_private_config_name(cfg.config_name)

        paths = tuple(_safe_relative_path(item) for item in relative_paths)
        matched: dict[str, list[str]] = {cfg.config_name: [] for cfg in specs}
        unmatched: list[str] = []
        for path in paths:
            hits = [
                cfg.config_name
                for cfg in specs
                if pattern_matches_path(cfg.data_files_pattern, path)
            ]
            if not hits:
                unmatched.append(path)
            for name in hits:
                matched[name].append(path)

        unresolved = sorted(
            name for name, files in matched.items() if paths and not files
        )
        if unresolved:
            raise ViewerPatternError(
                "Viewer file patterns did not resolve for configs: "
                + ", ".join(unresolved)
            )
        return {
            "matched": {key: list(value) for key, value in sorted(matched.items())},
            "role": role,
            "total_paths": len(paths),
            "unmatched_paths": unmatched,
            "unresolved_configs": unresolved,
            "viewer_patterns_resolve": not unresolved,
        }

    def validate_package(
        self,
        package: RepositoryLayoutPackage,
        *,
        relative_paths: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Validate card/config disclosures and optional Viewer path resolution."""

        card = package.dataset_card_text()
        configs_doc = package.dataset_configs()
        coverage = package.coverage.to_dict()

        required_card_tokens = (
            "sources",
            "license",
            "official-edition",
            "current-through",
            "freshness",
            "gaps",
            "parser",
            "model",
            "responsible use",
        )
        card_lower = card.lower()
        missing_tokens = [
            token for token in required_card_tokens if token not in card_lower
        ]
        if missing_tokens:
            raise PatentHubLayoutError(
                f"dataset card missing required disclosures: {missing_tokens}"
            )

        if not coverage["sources"]:
            raise PatentHubLayoutError("coverage sources missing")
        if not coverage["licenses"]:
            raise PatentHubLayoutError("coverage licenses missing")
        if not coverage["official_edition_cutoffs"]:
            raise PatentHubLayoutError("official_edition_cutoffs missing")
        if not coverage["freshness"]:
            raise PatentHubLayoutError("freshness missing")
        if "responsible_use" not in coverage or not coverage["responsible_use"]:
            raise PatentHubLayoutError("responsible_use missing")

        # Configs document must enumerate every package config with patterns.
        declared = {
            item["config_name"]: item
            for item in configs_doc.get("configs", [])
        }
        for cfg in package.configs:
            if cfg.config_name not in declared:
                raise PatentHubLayoutError(
                    f"dataset_configs missing config {cfg.config_name!r}"
                )
            entry = declared[cfg.config_name]
            paths = entry.get("data_files") or []
            if not paths:
                raise PatentHubLayoutError(
                    f"config {cfg.config_name!r} has no data_files"
                )

        for cfg in package.configs:
            _reject_private_config_name(cfg.config_name)

        resolution: dict[str, Any] | None = None
        if relative_paths is not None:
            resolution = self.resolve_viewer_patterns(
                role=package.identity.role,
                relative_paths=relative_paths,
                configs=package.configs,
            )

        for pointer in package.migration_pointers:
            if pointer.deletion_allowed or not pointer.preserves_legacy_data:
                raise PatentHubLayoutError(
                    "migration pointer must preserve data and forbid deletion"
                )

        return {
            "dataset_id": package.identity.dataset_id,
            "layout_cid": package.layout_cid,
            "valid": True,
            "viewer_resolution": resolution,
            "version_tag": package.version_tag,
        }

    def _identity_for_role(self, role: RepositoryRole) -> HubRepositoryIdentity:
        for identity in self.identities:
            if identity.role == role:
                return identity
        raise PatentHubLayoutError(f"no identity for role {role!r}")


# ---------------------------------------------------------------------------
# Card / config / JSON-LD builders
# ---------------------------------------------------------------------------


# Hugging Face dataset-card ``license`` front-matter must use a Hub-known tag.
# Internal SPDX-ish expressions (e.g. public-domain-US-government) map here.
_HF_CARD_LICENSE_ALIASES: Final[Mapping[str, str]] = {
    "public-domain-us-government": "cc0-1.0",
    "public-domain": "cc0-1.0",
    "public domain": "cc0-1.0",
    "us-government-work": "cc0-1.0",
    "pd": "cc0-1.0",
    "cc0": "cc0-1.0",
    "pddl": "pddl",
    "other": "other",
    "unknown": "unknown",
}


def hub_dataset_card_license(license_expression: str) -> str:
    """Map an internal license expression to a Hub-valid dataset-card tag."""
    text = str(license_expression or "").strip()
    if not text:
        return "other"
    alias = _HF_CARD_LICENSE_ALIASES.get(text.casefold())
    if alias:
        return alias
    # Already a Hub-style tag (mit, apache-2.0, cc-by-4.0, …).
    if re.fullmatch(r"[a-z0-9.+-]+", text.casefold()):
        return text.casefold()
    return "other"


def render_dataset_card(
    *,
    identity: HubRepositoryIdentity,
    configs: Sequence[HubConfigSpec],
    coverage: CoverageMetadata,
    version_tag: str,
    migration_pointers: Sequence[MigrationPointer] = (),
) -> str:
    """Render a Hugging Face dataset card with YAML front matter and disclosures."""

    for cfg in configs:
        _reject_private_config_name(cfg.config_name)
        if cfg.visibility != "public":
            raise PrivateConfigRejectedError(
                "private configs cannot be declared on a dataset card"
            )

    licenses = list(coverage.licenses)
    if len(licenses) == 1:
        primary_license = hub_dataset_card_license(licenses[0])
    else:
        primary_license = "other"

    lines: list[str] = [
        "---",
        f"license: {json.dumps(primary_license)}",
        f"pretty_name: {json.dumps(identity.dataset_id)}",
        "tags:",
        "  - patent",
        "  - legal",
        "  - justicedao",
        "  - public-official",
        f"  - {identity.role.replace('_', '-')}",
        "configs:",
    ]
    for cfg in sorted(configs, key=lambda item: item.config_name):
        lines.extend(
            [
                f"- config_name: {json.dumps(cfg.config_name)}",
                "  data_files:",
                "  - split: train",
                f"    path: {json.dumps(cfg.data_files_pattern)}",
            ]
        )
    lines.extend(
        [
            f"version_tag: {json.dumps(version_tag)}",
            "---",
            "",
            f"# {identity.dataset_id}",
            "",
            f"JusticeDAO patent/legal **{identity.role}** repository layout "
            f"(schema `{HF_LAYOUT_V2_SCHEMA_VERSION}`, tag `{version_tag}`).",
            "",
            "Generated by `PatentHubLayoutV2`. Publication is a separate "
            "operator-approved action; this card is layout metadata only.",
            "",
            "## Sources",
            "",
        ]
    )
    for src in coverage.sources:
        lines.append(f"- `{src.source_id}`")
        lines.append(f"  - license: `{src.license_expression}`")
        lines.append(
            f"  - official-edition cutoff: `{src.official_edition_cutoff}`"
        )
        lines.append(f"  - current-through: `{src.current_through}`")
        if src.freshness_note:
            lines.append(f"  - freshness: {src.freshness_note}")
        if src.source_revision:
            lines.append(f"  - source revision: `{src.source_revision}`")
        if src.source_uri:
            lines.append(f"  - uri: {src.source_uri}")
        if src.source_cid:
            lines.append(f"  - source CID: `{src.source_cid}`")
        if src.gaps:
            lines.append(f"  - gaps: {'; '.join(src.gaps)}")
    lines.extend(
        [
            "",
            "## Licenses",
            "",
        ]
    )
    for lic in licenses:
        lines.append(f"- `{lic}`")

    lines.extend(
        [
            "",
            "## Official-edition cutoffs",
            "",
        ]
    )
    for source_id, cutoff in coverage.official_edition_cutoffs.items():
        lines.append(f"- `{source_id}`: `{cutoff}`")

    lines.extend(
        [
            "",
            "## Freshness / current-through",
            "",
        ]
    )
    for source_id, value in coverage.freshness.items():
        lines.append(f"- `{source_id}`: `{value}`")

    lines.extend(["", "## Gaps", ""])
    if coverage.gaps:
        for gap in coverage.gaps:
            lines.append(f"- {gap}")
    else:
        lines.append("- No additional gaps disclosed beyond per-source notes.")

    lines.extend(["", "## Parser versions", ""])
    if coverage.parser_versions:
        for name, version in sorted(coverage.parser_versions.items()):
            lines.append(f"- `{name}`: `{version}`")
    else:
        lines.append("- (none declared for this layout package)")

    lines.extend(["", "## Model versions", ""])
    if coverage.model_versions:
        for name, version in sorted(coverage.model_versions.items()):
            lines.append(f"- `{name}`: `{version}`")
    else:
        lines.append("- (none declared for this layout package)")

    lines.extend(
        [
            "",
            "## Dataset configurations",
            "",
        ]
    )
    for cfg in sorted(configs, key=lambda item: item.config_name):
        lines.append(
            f"- `{cfg.config_name}` → `{cfg.data_files_pattern}` "
            f"(join: {', '.join(cfg.join_fields)})"
        )
        if cfg.description:
            lines.append(f"  - {cfg.description}")

    lines.extend(
        [
            "",
            "## CID joins",
            "",
            "Every data row that projects public text or index structure must "
            "join to a public source CID (`source_cid`) and a stable `record_id`. "
            "Index and graph configs additionally bind shard CIDs in their routing "
            "tables. See `manifest.jsonld` for machine-readable joins.",
            "",
            "## Responsible use",
            "",
        ]
    )
    for item in coverage.responsible_use:
        lines.append(f"- {item}")

    if migration_pointers:
        lines.extend(
            [
                "",
                "## Migration",
                "",
                "Legacy repositories may include a forward pointer to this "
                "dataset. Historical shards are retained; pointers never authorize "
                "deletion.",
                "",
            ]
        )
        for pointer in migration_pointers:
            lines.append(
                f"- from `{pointer.legacy_dataset_id}` → "
                f"`{pointer.target_dataset_id}` (`{pointer.target_version_tag}`)"
            )

    lines.extend(
        [
            "",
            "## Integrity files",
            "",
            f"- `{DATASET_CONFIGS_FILENAME}` — Viewer config + data_files patterns",
            f"- `{DATASET_INFOS_FILENAME}` — split/feature summary",
            f"- `{JSONLD_MANIFEST_FILENAME}` — JSON-LD identity and CID joins",
            f"- `{COVERAGE_FILENAME}` — machine-readable coverage disclosures",
            f"- `{LAYOUT_MANIFEST_FILENAME}` — layout contract binding",
            "",
        ]
    )
    return "\n".join(lines)


def build_dataset_configs(
    *,
    identity: HubRepositoryIdentity,
    configs: Sequence[HubConfigSpec],
    version_tag: str,
) -> dict[str, Any]:
    """Build the machine-readable dataset_configs document."""

    for cfg in configs:
        _reject_private_config_name(cfg.config_name)
        if cfg.visibility != "public":
            raise PrivateConfigRejectedError(
                "private configs cannot be declared"
            )
    return {
        "configs": [
            {
                "config_name": cfg.config_name,
                "data_files": [cfg.data_files_entry()],
                "description": cfg.description,
                "join_fields": list(cfg.join_fields),
                "role": cfg.role,
                "visibility": "public",
            }
            for cfg in sorted(configs, key=lambda item: item.config_name)
        ],
        "dataset_repo_id": identity.dataset_id,
        "format": "huggingface_dataset_card_frontmatter",
        "organization": identity.organization,
        "role": identity.role,
        "schema_version": HF_LAYOUT_V2_SCHEMA_VERSION,
        "version_tag": version_tag,
    }


def build_dataset_infos(
    *,
    identity: HubRepositoryIdentity,
    configs: Sequence[HubConfigSpec],
) -> dict[str, Any]:
    """Build a dataset_infos-style summary for Viewer/feature discovery."""

    config_map: dict[str, Any] = {}
    for cfg in sorted(configs, key=lambda item: item.config_name):
        features = {
            name: {"dtype": "string"}
            for name in (cfg.features or ("record_id", "source_cid"))
        }
        config_map[cfg.config_name] = {
            "data_files": cfg.data_files_pattern,
            "features": features,
            "splits": {
                cfg.split: {
                    "name": cfg.split,
                    "num_bytes": 0,
                    "num_examples": 0,
                }
            },
            "visibility": "public",
        }
    return {
        "configs": config_map,
        "dataset_name": identity.dataset_id,
        "schema_version": HF_LAYOUT_V2_SCHEMA_VERSION,
    }


def build_jsonld_manifest(
    *,
    identity: HubRepositoryIdentity,
    configs: Sequence[HubConfigSpec],
    coverage: CoverageMetadata,
    version_tag: str,
) -> dict[str, Any]:
    """JSON-LD manifest binding dataset identity, configs, sources, and CID joins."""

    return {
        "@context": JSONLD_CONTEXT,
        "@type": "PatentLegalHubLayout",
        "configs": [
            {
                "@type": "HubConfig",
                "config_name": cfg.config_name,
                "data_files_pattern": cfg.data_files_pattern,
                "join_fields": list(cfg.join_fields),
                "role": cfg.role,
                "visibility": "public",
            }
            for cfg in sorted(configs, key=lambda item: item.config_name)
        ],
        "dataset_id": identity.dataset_id,
        "organization": identity.organization,
        "program_id": PATENT_LEGAL_PROGRAM_ID,
        "role": identity.role,
        "schema_version": HF_LAYOUT_V2_SCHEMA_VERSION,
        "sources": [src.to_dict() for src in coverage.sources],
        "version_tag": version_tag,
    }


def pattern_matches_path(pattern: str, relative_path: str) -> bool:
    """Return True when a Viewer data_files pattern matches a relative path.

    Glob matching is path-segment aware: ``*`` matches within a single segment
    only (not recursive ``**``). Exact file patterns match with no wildcards.
    """

    normalized_pattern = pattern.strip().replace("\\", "/")
    path = relative_path.strip().replace("\\", "/")
    if not normalized_pattern or not path:
        return False
    path_parts = PurePosixParts(path)
    if not path_parts or ".." in path_parts or path.startswith("/"):
        return False
    pattern_parts = PurePosixParts(normalized_pattern)
    if not pattern_parts or ".." in pattern_parts:
        return False
    if len(pattern_parts) != len(path_parts):
        return False
    return all(
        fnmatchcase(path_part, pattern_part)
        for path_part, pattern_part in zip(path_parts, pattern_parts, strict=True)
    )


def default_public_coverage(
    *,
    as_of: str = "2026-08-01",
    include_models: bool = True,
) -> CoverageMetadata:
    """Deterministic sample public coverage for tests and dry layout builds."""

    sources = (
        SourceDisclosure(
            source_id="govinfo/uscode",
            license_expression="public-domain-US-government",
            official_edition_cutoff=as_of,
            current_through=as_of,
            authority_kind="codified_statute",
            source_uri="https://www.govinfo.gov/app/collection/uscode",
            source_revision=f"USCODE-{as_of[:4]}-title35",
            freshness_note="official edition projection",
            gaps=("Titles outside the patent-relevant set are out of scope.",),
        ),
        SourceDisclosure(
            source_id="govinfo/cfr",
            license_expression="public-domain-US-government",
            official_edition_cutoff=as_of,
            current_through=as_of,
            authority_kind="promulgated_regulation",
            source_uri="https://www.govinfo.gov/app/collection/cfr",
            source_revision=f"CFR-{as_of[:4]}-title37",
            freshness_note="annual CFR base; eCFR is unofficial",
            gaps=("eCFR currency is not treated as official edition.",),
        ),
        SourceDisclosure(
            source_id="uspto/public-pair",
            license_expression="public-domain-US-government",
            official_edition_cutoff=as_of,
            current_through=as_of,
            authority_kind="public_agency_record",
            source_uri="https://data.uspto.gov/",
            source_revision=f"public-export-{as_of}",
            freshness_note="public bulk / API export only",
            gaps=("Unpublished applications are excluded by policy.",),
        ),
    )
    parsers = {
        "patent-legal-xml-parser": "patent-legal-xml/v2",
        "patent-legal-pdf-extractor": "patent-legal-pdf/v2",
    }
    models = (
        {
            "embedding": "patent-legal-minilm/v2@rev-2026-08-01",
            "tokenizer": "patent-legal-tokens/v1",
        }
        if include_models
        else {}
    )
    return CoverageMetadata(
        sources=sources,
        parser_versions=parsers,
        model_versions=models,
        gaps=(
            "Private matter exports and mixed-rights batches are rejected before staging.",
        ),
        coverage_notes=(
            "Coverage is public-official / public-user only.",
        ),
    )


def build_default_layout_bundle(
    *,
    version_tag: str = DEFAULT_VERSION_TAG,
    organization: str = ORGANIZATION,
    include_legacy_migration: bool = True,
    coverage: CoverageMetadata | None = None,
) -> PatentHubLayoutBundle:
    """Convenience entry point for the canonical four-repo layout bundle."""

    layout = PatentHubLayoutV2(
        organization=organization,
        version_tag=version_tag,
    )
    return layout.build_bundle(
        coverage=coverage or default_public_coverage(),
        include_legacy_migration=include_legacy_migration,
    )


def validate_no_private_configs(
    configs: Iterable[HubConfigSpec | Mapping[str, Any] | str],
) -> None:
    """Fail closed if any config name or visibility is private/mixed."""

    for item in configs:
        if isinstance(item, HubConfigSpec):
            _reject_private_config_name(item.config_name)
            if item.visibility != "public":
                raise PrivateConfigRejectedError(
                    "private configs cannot be declared"
                )
            continue
        if isinstance(item, Mapping):
            name = str(item.get("config_name") or item.get("name") or "")
            visibility = str(item.get("visibility") or "public").lower()
            _reject_private_config_name(name)
            if visibility != "public":
                raise PrivateConfigRejectedError(
                    f"private configs cannot be declared: visibility={visibility!r}"
                )
            continue
        _reject_private_config_name(str(item))


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _layout_package_cid(
    *,
    identity: HubRepositoryIdentity,
    configs: Sequence[HubConfigSpec],
    coverage: CoverageMetadata,
    version_tag: str,
    artifacts: Sequence[LayoutArtifact],
    migration_pointers: Sequence[MigrationPointer],
) -> str:
    payload = {
        "artifacts": [item.descriptor() for item in artifacts],
        "configs": [item.to_dict() for item in configs],
        "coverage": coverage.to_dict(),
        "identity": identity.to_dict(),
        "migration_pointers": [item.to_dict() for item in migration_pointers],
        "schema_version": HF_LAYOUT_V2_SCHEMA_VERSION,
        "version_tag": version_tag,
    }
    digest = hashlib.sha256(canonical_json_bytes(payload)).digest()
    return cid_v1_from_digest(digest)


__all__ = [
    "BM25_REPOSITORY",
    "CANONICAL_CONFIGS_BY_ROLE",
    "CANONICAL_REPOSITORY_NAMES",
    "CORPUS_REPOSITORY",
    "COVERAGE_FILENAME",
    "DATASET_CONFIGS_FILENAME",
    "DATASET_INFOS_FILENAME",
    "DEFAULT_RESPONSIBLE_USE",
    "DEFAULT_VERSION_TAG",
    "HF_LAYOUT_V2_CONFIG",
    "HF_LAYOUT_V2_PRODUCER",
    "HF_LAYOUT_V2_SCHEMA_VERSION",
    "JSONLD_MANIFEST_FILENAME",
    "KNOWLEDGE_GRAPH_REPOSITORY",
    "LAYOUT_MANIFEST_FILENAME",
    "LEGACY_V1_LOWERCASE_ID",
    "LEGACY_V1_REPOSITORY_ID",
    "MIGRATION_POINTER_FILENAME",
    "ORGANIZATION",
    "README_FILENAME",
    "VECTORS_REPOSITORY",
    "VERSION_TAG_PREFIX",
    "CoverageMetadata",
    "HubConfigSpec",
    "HubRepositoryIdentity",
    "LayoutArtifact",
    "MigrationPointer",
    "PatentHubLayoutBundle",
    "PatentHubLayoutError",
    "PatentHubLayoutV2",
    "PrivateConfigRejectedError",
    "RepositoryLayoutPackage",
    "SourceDisclosure",
    "ViewerPatternError",
    "build_dataset_configs",
    "build_dataset_infos",
    "build_default_layout_bundle",
    "build_jsonld_manifest",
    "canonical_repository_identities",
    "default_public_coverage",
    "legacy_repository_inventory",
    "pattern_matches_path",
    "render_dataset_card",
    "validate_no_private_configs",
]
