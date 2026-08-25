"""Descriptor-complete additive Federal Register Hugging Face release (LCR-062).

Assembles verified LCR-061 family outputs into an immutable candidate root
with:

* compact ``manifest.json`` / ``release_metadata.json`` (control plane);
* a Viewer-safe default v2 configuration plus explicit non-default
  legacy, recovery, and quarantine configs;
* descriptor-bound inventory for every artifact (relative path, media type,
  row count, byte size, SHA-256, schema id, family, route keys);
* family bindings for corpus, BM25, vectors, centroids, the vector entry
  locator, the legal graph, two-way adjacency, recovery, and source
  receipts;
* model revision, route bounds, compact admission/quality reports, and an
  old-pin rollback map;
* a dataset card whose source-scope rights summary binds the LCR-078/LCR-079
  compliance-receipt digest;
* **verbose lineage** isolated under ``reports/lineage.json`` (never mixed
  into control-plane manifests or the default Viewer config).

This module does **not** publish to the Hub. Remote mutation is owned by
LCR-064+ publication gates. Default mode is dry-run (in-memory). Fixture
receipts set ``authorizing_for_publication=false``.

Acceptance invariants
---------------------
1. The default Viewer config is ``federal-register-ir-graphrag/v2`` and
   excludes recovery, quarantine, and legacy rows.
2. Every advertised config is schema-coherent (paths + families + keys).
3. Every artifact is descriptor-bound (relative path, media type, rows,
   bytes, SHA-256, schema id, family).
4. The manifest binds corpus, BM25, vectors, centroids, vector locator,
   graph, two-way adjacency, recovery, configs, source receipts, model
   revision, row counts, sizes, SHA-256 digests, route bounds, rollback
   metadata, and the source-rights receipt digest.
5. Unknown or prohibited rights cannot enter the default release.
6. Verbose lineage is separate from the control plane.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import Any, Final, Optional, Union

from ipfs_datasets_py.huggingface.release import (
    FileDescriptor,
    HuggingFaceReleaseError,
    canonical_json_bytes,
    describe_file,
    reject_identity_contamination,
    shard_sequence,
)
from ipfs_datasets_py.logic.ir_core.identity import cid_v1_from_digest
from ipfs_datasets_py.processors.legal_data.federal_register_acquisition import (
    assert_no_secrets,
)
from ipfs_datasets_py.processors.legal_data.federal_register_bm25 import (
    TOKENIZER_ID,
    TOKENIZER_SHARED_BY,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release import (
    consume_family_builders,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    DEFAULT_CANDIDATE_CENTROIDS,
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_MODEL_REVISION,
    DEFAULT_OBSERVATION_CUTOFF,
    MAX_ADJACENCY_POINTERS_PER_ROW,
    MAX_POSTING_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    MAX_ROWS_PER_VECTOR_CENTROID,
    MAX_VECTOR_SHARDS_PER_CENTROID,
    PREVIOUS_PUBLIC_PIN,
    RELEASE_PROFILE,
    SOURCE_RIGHTS_RECEIPT_RELPATH,
    ArtifactDescriptor,
    ArtifactFamily,
    SemanticFamilyClosureError,
    SourceRightsBindingError,
    content_sha256,
    digest_mapping,
    example_corpus_payload,
    example_correction_corpus_payload,
    example_source_receipt_payload,
    normalize_relative_artifact_path,
    normalize_sha256,
    physical_bounds_policy as identity_physical_bounds,
    required_semantic_families,
    require_immutable_revision,
    require_source_rights_binding,
    validate_entry_cid,
    validate_semantic_family_closure,
)
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (
    CURRENTNESS_DISCLAIMER,
    LEGACY_BASELINE_END_INCLUSIVE,
)
from ipfs_datasets_py.processors.legal_data.federal_register_vectors import (
    PINNED_DIMENSION,
    PINNED_MAX_TOKENS,
    PINNED_MODEL_ID,
    PINNED_MODEL_REVISION,
    PINNED_NORMALIZATION,
    PINNED_POOLING,
    default_vector_space_id,
)


# ---------------------------------------------------------------------------
# Identity / schema constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "federal-register-hf-release/v1"
TASK_ID: Final = "LCR-062"
GOAL_ID: Final = "LCR-G130"
PRODUCER: Final = "federal_register_hf_release.py"
HF_RELEASE_PRODUCER: Final = "producer:federal-register-hf-release"
HF_RELEASE_CONFIG: Final = "config:federal-register-hf-release/v1"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
BOARD_NAMESPACE: Final = "legal-corpora-reindex-v1"
BUNDLE: Final = "federal-release-package"
CODE_VERSION: Final = "1"
AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
PROVES_SOFTWARE_CONTRACT_ONLY: Final = True

MANIFEST_FILENAME: Final = "manifest.json"
RELEASE_METADATA_FILENAME: Final = "release_metadata.json"
README_FILENAME: Final = "README.md"
DATASET_INFOS_FILENAME: Final = "dataset_infos.json"
DATASET_CONFIGS_FILENAME: Final = "dataset_configs.json"

ADMISSION_REPORT_PATH: Final = "reports/admission.json"
QUALITY_REPORT_PATH: Final = "reports/quality.json"
REPRODUCIBILITY_REPORT_PATH: Final = "reports/reproducibility.json"
LINEAGE_REPORT_PATH: Final = "reports/lineage.json"
CANDIDATE_EVIDENCE_RELPATH: Final = (
    "docs/reports/legal_corpora_reindex/federal_candidate.json"
)
DATASET_CARD_TEMPLATE_RELPATH: Final = (
    "docs/templates/FEDERAL_REGISTER_DATASET_CARD.md"
)

DEFAULT_CONFIG_NAME: Final = RELEASE_PROFILE
RECOVERY_CONFIG_NAME: Final = "recovery"
QUARANTINE_CONFIG_NAME: Final = "quarantine"
LEGACY_CONFIG_NAME: Final = "legacy-federal-register-parquet/v1"

PRIMARY_KEY_V2: Final = "entry_cid"
DEFAULT_LICENSE: Final = "other"
DEFAULT_PACKAGE_VERSION: Final = "2"
DEFAULT_DETERMINISM_SEED: Final = 20260810
DEFAULT_GRAPH_ONTOLOGY_VERSION: Final = "federal-register-graph-ontology/v1"
DEFAULT_SOURCE_REVISION: Final = PREVIOUS_PUBLIC_PIN
DEFAULT_RELEASE_POINT: Final = f"federal-register/v2/{DEFAULT_OBSERVATION_CUTOFF[:10]}"
DEFAULT_MODEL_TOKEN_CEILING: Final = PINNED_MAX_TOKENS
DEFAULT_BM25_K1: Final = 1.2
DEFAULT_BM25_B: Final = 0.75
ADMITTED_FEDERAL_SOURCE_ID: Final = (
    "fr-hf-baseline-720668ae016cc400916dda884c9005e03618edfa-federal_government_text"
)
DENIED_FEDERAL_SOURCE_ID: Final = (
    "fr-hf-baseline-720668ae016cc400916dda884c9005e03618edfa-editorial_enhancements"
)

PARQUET_MEDIA_TYPE: Final = "application/vnd.apache.parquet"
JSON_MEDIA_TYPE: Final = "application/json"
MARKDOWN_MEDIA_TYPE: Final = "text/markdown; charset=utf-8"
JSONLD_MEDIA_TYPE: Final = "application/ld+json"

DEFAULT_CONFIG_FAMILIES: Final = frozenset(
    {
        "corpus",
        "bm25_documents",
        "bm25_postings",
        "vectors",
        "centroids",
        "vector_locator",
        "graph_nodes",
        "graph_edges",
        "graph_adjacency_out",
        "graph_adjacency_in",
    }
)
RECOVERY_FAMILIES: Final = frozenset({"recovery", "quarantine"})
JSON_FAMILIES: Final = frozenset({"recovery", "quarantine", "source_receipts"})
PROHIBITED_RIGHTS_DISPOSITIONS: Final = frozenset(
    {"unknown", "prohibited", "denied", "rejected"}
)

DEFAULT_CONFIG_PATH_PREFIXES: Final = (
    "data/corpus/",
    "data/bm25/",
    "data/vectors/",
    "data/graph/",
    "indexes/",
)
RECOVERY_CONFIG_PATH_PREFIXES: Final = ("recovery/",)
QUARANTINE_CONFIG_PATH_PREFIXES: Final = ("quarantine/",)
LEGACY_CONFIG_PATH_PREFIXES: Final = (
    "federal_register.parquet",
    "federal_register.jsonld",
    "federal_register_raw/",
    "federal_register_gte_small.faiss",
    "federal_register_gte_small_metadata.parquet",
)

CONTROL_PLANE_PATHS: Final = frozenset(
    {
        MANIFEST_FILENAME,
        RELEASE_METADATA_FILENAME,
        README_FILENAME,
        DATASET_INFOS_FILENAME,
        DATASET_CONFIGS_FILENAME,
        ADMISSION_REPORT_PATH,
        QUALITY_REPORT_PATH,
        REPRODUCIBILITY_REPORT_PATH,
    }
)

REQUIRED_MANIFEST_BINDINGS: Final = (
    "corpus",
    "bm25",
    "vectors",
    "centroids",
    "vector_locator",
    "graph",
    "two_way_adjacency",
    "recovery",
    "configs",
    "source_receipts",
    "model_revision",
    "row_counts",
    "sizes",
    "sha256_digests",
    "route_bounds",
    "viewer_safe_default_v2",
    "source_rights_receipt_digest",
    "source_rights_receipt_path",
    "rollback",
    "semantic_family_closure",
)

_DATASET_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CID_RE = re.compile(r"^b[a-z2-7]{20,}$")
_SECRET_RE = re.compile(
    r"(hf_[A-Za-z0-9]{16,}|HUGGINGFACE_TOKEN|HF_TOKEN=|Bearer\s+[A-Za-z0-9._\-]+)",
    re.IGNORECASE,
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]

_FAMILY_ALIASES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "bm25": "bm25_documents",
        "bm25_docs": "bm25_documents",
        "postings": "bm25_postings",
        "locator": "vector_locator",
        "locator_index": "vector_locator",
        "entry_locator": "vector_locator",
        "nodes": "graph_nodes",
        "edges": "graph_edges",
        "adjacency_out": "graph_adjacency_out",
        "adjacency_in": "graph_adjacency_in",
        "graph_adjacency": "graph_adjacency_out",
        "two_way_adjacency": "graph_adjacency_out",
        "receipts": "source_receipts",
        "source_receipt": "source_receipts",
        "legacy": LEGACY_CONFIG_NAME,
    }
)

_FAMILY_PATH_TEMPLATES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "corpus": "data/corpus/part-{shard:06d}.parquet",
        "bm25_documents": "data/bm25/documents/part-{shard:06d}.parquet",
        "bm25_postings": "data/bm25/postings/part-{shard:06d}.parquet",
        "vectors": "data/vectors/centroid-000-part-{shard:06d}.parquet",
        "centroids": "data/vectors/centroids/part-{shard:06d}.parquet",
        "vector_locator": "data/vectors/locator/part-{shard:06d}.parquet",
        "graph_nodes": "data/graph/nodes/part-{shard:06d}.parquet",
        "graph_edges": "data/graph/edges/part-{shard:06d}.parquet",
        "graph_adjacency_out": "data/graph/adjacency/out/part-{shard:06d}.parquet",
        "graph_adjacency_in": "data/graph/adjacency/in/part-{shard:06d}.parquet",
        "source_receipts": "receipts/source/part-{shard:06d}.json",
        "recovery": "recovery/part-{shard:06d}.json",
        "quarantine": "quarantine/part-{shard:06d}.json",
    }
)

_FAMILY_SCHEMA_IDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "corpus": "federal-register-corpus-row/v1",
        "bm25_documents": "federal-register-bm25-document/v1",
        "bm25_postings": "federal-register-bm25-posting/v1",
        "vectors": "federal-register-vector-row/v1",
        "centroids": "federal-register-centroid-row/v1",
        "vector_locator": "federal-register-vector-locator/v1",
        "graph_nodes": "federal-register-graph-node/v1",
        "graph_edges": "federal-register-graph-edge/v1",
        "graph_adjacency_out": "federal-register-graph-adjacency-out/v1",
        "graph_adjacency_in": "federal-register-graph-adjacency-in/v1",
        "source_receipts": "federal-register-source-receipt/v1",
        "recovery": "federal-register-recovery/v1",
        "quarantine": "federal-register-quarantine/v1",
        "routing_index": "federal-register-routing-index/v1",
        LEGACY_CONFIG_NAME: "federal-register-legacy-parquet/v1",
    }
)

_FAMILY_TO_ARTIFACT_FAMILY: Final[Mapping[str, ArtifactFamily]] = MappingProxyType(
    {
        "corpus": ArtifactFamily.CORPUS,
        "bm25_documents": ArtifactFamily.BM25_DOCUMENTS,
        "bm25_postings": ArtifactFamily.BM25_POSTINGS,
        "vectors": ArtifactFamily.VECTORS,
        "centroids": ArtifactFamily.CENTROIDS,
        "vector_locator": ArtifactFamily.LOCATOR_INDEX,
        "graph_nodes": ArtifactFamily.GRAPH_NODES,
        "graph_edges": ArtifactFamily.GRAPH_EDGES,
        "graph_adjacency_out": ArtifactFamily.GRAPH_ADJACENCY_OUT,
        "graph_adjacency_in": ArtifactFamily.GRAPH_ADJACENCY_IN,
        "routing_index": ArtifactFamily.ROUTING_INDEX,
        "manifest": ArtifactFamily.MANIFEST,
        "receipt": ArtifactFamily.RECEIPT,
        "source_receipts": ArtifactFamily.SOURCE_RECEIPT,
        "recovery": ArtifactFamily.RECOVERY,
        "quarantine": ArtifactFamily.RECOVERY,
        "report": ArtifactFamily.REPORT,
        "release_metadata": ArtifactFamily.RELEASE_METADATA,
        "rollback": ArtifactFamily.ROLLBACK,
        LEGACY_CONFIG_NAME: ArtifactFamily.RECEIPT,
    }
)

_DEFAULT_FEATURES: Final = (
    "entry_cid",
    "legal_id",
    "document_number",
    "publication_date",
    "document_type",
    "year_month",
    "family",
    "record_json",
    "record_sha256",
)
_RECOVERY_FEATURES: Final = (
    "recovery_id",
    "admission_status",
    "record_json",
    "record_sha256",
)
_LEGACY_FEATURES: Final = (
    "document_number",
    "publication_date",
    "title",
    "abstract",
    "text",
)
_CONFIG_FEATURES: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        DEFAULT_CONFIG_NAME: _DEFAULT_FEATURES,
        LEGACY_CONFIG_NAME: _LEGACY_FEATURES,
        RECOVERY_CONFIG_NAME: _RECOVERY_FEATURES,
        QUARANTINE_CONFIG_NAME: _RECOVERY_FEATURES,
    }
)

_HIDDEN_VIEWER_CONFIGS: Final = frozenset(
    {RECOVERY_CONFIG_NAME, QUARANTINE_CONFIG_NAME}
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FederalRegisterHFReleaseError(HuggingFaceReleaseError):
    """Base error for Federal Register Hugging Face release packaging failures."""

    code: str = "federal_register_hf_release_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class FederalRegisterHFReleaseIntegrityError(FederalRegisterHFReleaseError):
    """Raised when descriptors, digests, or family bindings disagree."""

    code = "federal_register_hf_release_integrity"


class FederalRegisterHFReleaseConfigError(FederalRegisterHFReleaseError):
    """Raised when viewer/config schema coherence fails."""

    code = "federal_register_hf_release_config"


class FederalRegisterHFReleaseSafetyError(FederalRegisterHFReleaseError):
    """Raised when recovery, rights, or non-default rows contaminate v2."""

    code = "federal_register_hf_release_safety"


class HubUploadForbiddenError(FederalRegisterHFReleaseSafetyError):
    """Raised when a Hub upload surface is requested."""

    code = "hub_upload_forbidden"


# ---------------------------------------------------------------------------
# Source-rights receipt binding
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    return _REPO_ROOT


def load_source_rights_receipt(
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Load the sealed LCR-078/LCR-079 source-rights compliance receipt."""

    candidates: list[Path] = []
    if path is not None:
        candidates.append(Path(path))
    candidates.extend(
        [
            _repo_root() / SOURCE_RIGHTS_RECEIPT_RELPATH,
            Path(SOURCE_RIGHTS_RECEIPT_RELPATH),
            Path.cwd() / SOURCE_RIGHTS_RECEIPT_RELPATH,
        ]
    )
    target: Path | None = None
    for candidate in candidates:
        if candidate.is_file():
            target = candidate
            break
    if target is None:
        raise FederalRegisterHFReleaseSafetyError(
            f"source-rights receipt missing: {SOURCE_RIGHTS_RECEIPT_RELPATH}"
        )
    raw = target.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise FederalRegisterHFReleaseSafetyError(
            "source-rights receipt must be a JSON object"
        )
    digest = str(
        payload.get("report_digest_sha256")
        or payload.get("content_digest")
        or payload.get("digest")
        or ""
    ).strip()
    if not digest:
        digest = hashlib.sha256(raw).hexdigest()
    digest = normalize_sha256(digest, name="source_rights_receipt_digest")
    catalog = str(payload.get("catalog_digest_sha256") or "").strip()
    if catalog:
        catalog = normalize_sha256(catalog, name="source_rights_catalog_digest")
    admitted = tuple(
        str(item)
        for item in (payload.get("admitted_record_ids") or ())
        if str(item).strip()
    )
    denied = {
        str(item)
        for item in (payload.get("denied_record_ids") or ())
        if str(item).strip()
    }
    prohibited: set[str] = set(denied)
    unknown: set[str] = set()
    for decision in payload.get("decisions") or ():
        if not isinstance(decision, Mapping):
            continue
        disposition = str(decision.get("rights_disposition") or "").strip().lower()
        identifiers = {
            str(decision.get("record_id") or "").strip(),
            str(decision.get("source_id") or "").strip(),
        }
        identifiers.discard("")
        if disposition in {"prohibited", "denied", "rejected"}:
            prohibited.update(identifiers)
        elif disposition in {"unknown"}:
            unknown.update(identifiers)
    return {
        "admitted_record_ids": admitted,
        "admitted_source_ids": admitted,
        "authorizing_for_publication": False,
        "catalog_digest_sha256": catalog,
        "denied_record_ids": tuple(sorted(denied)),
        "path": SOURCE_RIGHTS_RECEIPT_RELPATH,
        "prohibited_ids": tuple(sorted(prohibited)),
        "receipt_digest": digest,
        "status": str(payload.get("status") or "").strip().lower(),
        "unknown_ids": tuple(sorted(unknown)),
    }


def source_scope_rights_summary(
    receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compact rights summary bound into the dataset card and manifest."""

    bound = dict(receipt or load_source_rights_receipt())
    return {
        "admitted_count": len(bound.get("admitted_record_ids") or ()),
        "authorizing_for_publication": False,
        "catalog_digest_sha256": bound.get("catalog_digest_sha256") or "",
        "prohibited_and_unknown_excluded_from_default": True,
        "source_rights_receipt_digest": bound["receipt_digest"],
        "source_rights_receipt_path": SOURCE_RIGHTS_RECEIPT_RELPATH,
        "task_ids": ["LCR-078", "LCR-079", "LCR-081", "LCR-082", "LCR-083"],
    }


def _assert_row_rights_admissible(
    row: Mapping[str, Any],
    *,
    family: str,
    receipt: Mapping[str, Any],
) -> None:
    """Fail closed when unknown/prohibited rights would enter the default set."""

    if family in RECOVERY_FAMILIES or family == LEGACY_CONFIG_NAME:
        return
    disposition = str(
        row.get("rights_disposition") or row.get("source_rights_disposition") or ""
    ).strip().lower()
    if disposition in PROHIBITED_RIGHTS_DISPOSITIONS:
        raise FederalRegisterHFReleaseSafetyError(
            f"family {family!r} row has {disposition} rights and cannot enter "
            "the default Federal Register v2 release"
        )
    identifiers = {
        str(row.get("source_id") or "").strip(),
        str(row.get("record_id") or "").strip(),
        str(row.get("acquisition_receipt_id") or "").strip(),
    }
    identifiers.discard("")
    prohibited = set(receipt.get("prohibited_ids") or ())
    unknown = set(receipt.get("unknown_ids") or ())
    blocked = identifiers & (prohibited | unknown)
    if blocked:
        raise FederalRegisterHFReleaseSafetyError(
            f"family {family!r} row binds prohibited/unknown source-rights "
            f"identifiers {sorted(blocked)!r}"
        )


def _assert_no_secrets_or_absolute_paths(payload: Any, *, label: str) -> None:
    if isinstance(payload, Mapping):
        try:
            assert_no_secrets(payload, context=label)
        except Exception as exc:
            raise FederalRegisterHFReleaseSafetyError(
                f"{label} contains secrets or absolute home paths: {exc}"
            ) from exc
        dumped = json.dumps(payload, default=str)
    else:
        dumped = str(payload)
    if "/home/" in dumped or "/Users/" in dumped or "C:\\" in dumped:
        raise FederalRegisterHFReleaseSafetyError(
            f"{label} must not contain absolute paths"
        )
    if _SECRET_RE.search(dumped):
        raise FederalRegisterHFReleaseSafetyError(f"{label} must not contain secrets")


def reject_hub_upload(requested: bool) -> None:
    if requested:
        raise HubUploadForbiddenError("Hub upload is forbidden in LCR-062")


def software_contract_flags() -> dict[str, Any]:
    return {
        "authorizing_for_publication": AUTHORIZES_PUBLICATION,
        "authorizing_hub_upload": AUTHORIZES_HUB_UPLOAD,
        "fixture_only": True,
        "hub_upload": False,
        "proves_software_contract_only": PROVES_SOFTWARE_CONTRACT_ONLY,
    }


# ---------------------------------------------------------------------------
# Viewer configuration contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ViewerConfig:
    """One advertised Hugging Face Dataset Viewer configuration."""

    config_name: str
    data_files: tuple[dict[str, str], ...]
    primary_key: str
    is_default: bool = False
    is_recovery: bool = False
    is_quarantine: bool = False
    is_legacy: bool = False
    viewer_visible: bool = True
    viewer_safe_default: bool = False
    features: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    path_prefixes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        name = str(self.config_name or "").strip()
        if not name:
            raise FederalRegisterHFReleaseConfigError("config_name is required")
        if self.is_default and (self.is_recovery or self.is_quarantine or self.is_legacy):
            raise FederalRegisterHFReleaseConfigError(
                "default config cannot also be recovery, quarantine, or legacy"
            )
        if self.is_default and not self.viewer_safe_default:
            raise FederalRegisterHFReleaseConfigError(
                "default config must be Viewer-safe v2"
            )
        if (self.is_recovery or self.is_quarantine or self.is_legacy) and (
            self.viewer_safe_default
        ):
            raise FederalRegisterHFReleaseConfigError(
                "recovery/quarantine/legacy configs cannot be the Viewer-safe default"
            )
        object.__setattr__(self, "config_name", name)
        object.__setattr__(
            self,
            "primary_key",
            str(self.primary_key or "").strip() or PRIMARY_KEY_V2,
        )
        files = tuple(dict(item) for item in self.data_files)
        if not files:
            raise FederalRegisterHFReleaseConfigError(
                f"config {name!r} requires at least one data_files entry"
            )
        for item in files:
            if "split" not in item or "path" not in item:
                raise FederalRegisterHFReleaseConfigError(
                    f"config {name!r} data_files entries need split + path"
                )
            path = str(item["path"])
            if path.startswith("/") or ".." in PurePosixPath(path).parts:
                raise FederalRegisterHFReleaseConfigError(
                    f"config {name!r} data path is unsafe: {path!r}"
                )
        object.__setattr__(self, "data_files", files)
        object.__setattr__(self, "features", tuple(self.features))
        object.__setattr__(self, "notes", tuple(str(n) for n in self.notes))
        object.__setattr__(
            self, "path_prefixes", tuple(str(p) for p in self.path_prefixes)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_name": self.config_name,
            "data_files": [dict(item) for item in self.data_files],
            "features": list(self.features),
            "is_default": self.is_default,
            "is_legacy": self.is_legacy,
            "is_quarantine": self.is_quarantine,
            "is_recovery": self.is_recovery,
            "notes": list(self.notes),
            "path_prefixes": list(self.path_prefixes),
            "primary_key": self.primary_key,
            "viewer_safe_default": self.viewer_safe_default,
            "viewer_visible": self.viewer_visible,
        }

    def yaml_block(self) -> list[str]:
        """Return YAML lines for Dataset card ``configs:`` frontmatter."""

        lines = [
            f"- config_name: {json.dumps(self.config_name)}",
            "  data_files:",
        ]
        for item in self.data_files:
            lines.append(f"  - split: {json.dumps(item['split'])}")
            lines.append(f"    path: {json.dumps(item['path'])}")
        return lines


def advertised_viewer_configs(
    *,
    include_legacy: bool = True,
    include_recovery: bool = True,
    include_quarantine: bool = True,
    default_data_glob: str = "data/**/*.parquet",
    recovery_data_glob: str = "recovery/**/*.json",
    quarantine_data_glob: str = "quarantine/**/*.json",
    legacy_data_glob: str = "federal_register.parquet",
) -> tuple[ViewerConfig, ...]:
    """Return the sealed set of advertised Dataset Viewer configurations."""

    configs: list[ViewerConfig] = [
        ViewerConfig(
            config_name=DEFAULT_CONFIG_NAME,
            data_files=({"split": "train", "path": default_data_glob},),
            primary_key=PRIMARY_KEY_V2,
            is_default=True,
            is_recovery=False,
            is_quarantine=False,
            is_legacy=False,
            viewer_visible=True,
            viewer_safe_default=True,
            features=_CONFIG_FEATURES[DEFAULT_CONFIG_NAME],
            path_prefixes=DEFAULT_CONFIG_PATH_PREFIXES,
            notes=(
                "Viewer-safe default v2 Federal Register configuration.",
                "Cutoff-relative official Federal Register documents with full-text dispositions.",
                "Excludes recovery, quarantine, and legacy root-level Parquet/JSON-LD/FAISS rows.",
            ),
        )
    ]
    if include_legacy:
        configs.append(
            ViewerConfig(
                config_name=LEGACY_CONFIG_NAME,
                data_files=({"split": "train", "path": legacy_data_glob},),
                primary_key="document_number",
                is_default=False,
                is_legacy=True,
                viewer_visible=True,
                viewer_safe_default=False,
                features=_CONFIG_FEATURES[LEGACY_CONFIG_NAME],
                path_prefixes=LEGACY_CONFIG_PATH_PREFIXES,
                notes=(
                    "Explicit deprecation-cycle compatibility path for federal_register.parquet.",
                    "Must not be the default Dataset Viewer config.",
                    "Legacy files are retained; packaging never deletes them.",
                ),
            )
        )
    if include_recovery:
        configs.append(
            ViewerConfig(
                config_name=RECOVERY_CONFIG_NAME,
                data_files=({"split": "train", "path": recovery_data_glob},),
                primary_key="recovery_id",
                is_default=False,
                is_recovery=True,
                viewer_visible=False,
                viewer_safe_default=False,
                features=_CONFIG_FEATURES[RECOVERY_CONFIG_NAME],
                path_prefixes=RECOVERY_CONFIG_PATH_PREFIXES,
                notes=(
                    "Recovery records that cannot enter canonical default counts.",
                    "Never included in the default config or Viewer-safe v2 gate.",
                ),
            )
        )
    if include_quarantine:
        configs.append(
            ViewerConfig(
                config_name=QUARANTINE_CONFIG_NAME,
                data_files=({"split": "train", "path": quarantine_data_glob},),
                primary_key="recovery_id",
                is_default=False,
                is_quarantine=True,
                viewer_visible=False,
                viewer_safe_default=False,
                features=_CONFIG_FEATURES[QUARANTINE_CONFIG_NAME],
                path_prefixes=QUARANTINE_CONFIG_PATH_PREFIXES,
                notes=(
                    "Quarantined or rejected rows excluded from the Viewer default split.",
                    "Unknown or prohibited rights stay out of the default v2 config.",
                ),
            )
        )
    return tuple(configs)


def assert_configs_schema_coherent(
    configs: Sequence[ViewerConfig | Mapping[str, Any]],
) -> dict[str, Any]:
    """Fail closed when advertised configs violate schema coherence rules."""

    resolved: list[ViewerConfig] = []
    for item in configs:
        if isinstance(item, ViewerConfig):
            resolved.append(item)
        elif isinstance(item, Mapping):
            resolved.append(
                ViewerConfig(
                    config_name=str(item.get("config_name") or item.get("name") or ""),
                    data_files=tuple(item.get("data_files") or ()),
                    primary_key=str(item.get("primary_key") or PRIMARY_KEY_V2),
                    is_default=bool(item.get("is_default", False)),
                    is_recovery=bool(item.get("is_recovery", False)),
                    is_quarantine=bool(item.get("is_quarantine", False)),
                    is_legacy=bool(item.get("is_legacy", False)),
                    viewer_visible=bool(item.get("viewer_visible", True)),
                    viewer_safe_default=bool(
                        item.get("viewer_safe_default", False)
                    ),
                    features=tuple(item.get("features") or ()),
                    notes=tuple(item.get("notes") or ()),
                    path_prefixes=tuple(item.get("path_prefixes") or ()),
                )
            )
        else:
            raise FederalRegisterHFReleaseConfigError(
                "config entries must be ViewerConfig or mapping"
            )

    if not resolved:
        raise FederalRegisterHFReleaseConfigError(
            "at least one viewer config is required"
        )

    defaults = [c for c in resolved if c.is_default]
    if len(defaults) != 1:
        raise FederalRegisterHFReleaseConfigError(
            f"exactly one default config required, found {len(defaults)}"
        )
    default = defaults[0]
    if default.config_name != DEFAULT_CONFIG_NAME:
        raise FederalRegisterHFReleaseConfigError(
            f"default config must be {DEFAULT_CONFIG_NAME!r}, "
            f"got {default.config_name!r}"
        )
    if default.is_recovery or default.is_quarantine or default.is_legacy:
        raise FederalRegisterHFReleaseConfigError(
            "default config must not be recovery, quarantine, or legacy"
        )
    if not default.viewer_safe_default:
        raise FederalRegisterHFReleaseConfigError(
            "default config must be Viewer-safe v2"
        )

    for entry in default.data_files:
        path = str(entry["path"])
        lowered = path.lower()
        if (
            path.startswith("recovery/")
            or path.startswith("quarantine/")
            or path.startswith("federal_register.")
            or path.startswith("federal_register_")
            or "/recovery/" in f"/{path}/"
            or "/quarantine/" in f"/{path}/"
            or ("recovery" in lowered and lowered.endswith(".json"))
        ):
            raise FederalRegisterHFReleaseSafetyError(
                "default config excludes recovery, quarantine, and legacy; "
                f"found path {path!r}"
            )

    names = [c.config_name for c in resolved]
    if len(names) != len(set(names)):
        raise FederalRegisterHFReleaseConfigError("viewer config names must be unique")

    for cfg in resolved:
        features = set(cfg.features)
        if cfg.primary_key and cfg.features and cfg.primary_key not in features:
            raise FederalRegisterHFReleaseConfigError(
                f"config {cfg.config_name!r} primary_key "
                f"{cfg.primary_key!r} missing from features"
            )
        if cfg.is_recovery and cfg.config_name != RECOVERY_CONFIG_NAME:
            raise FederalRegisterHFReleaseConfigError(
                f"recovery config must be named {RECOVERY_CONFIG_NAME!r}"
            )
        if cfg.is_quarantine and cfg.config_name != QUARANTINE_CONFIG_NAME:
            raise FederalRegisterHFReleaseConfigError(
                f"quarantine config must be named {QUARANTINE_CONFIG_NAME!r}"
            )
        if cfg.is_legacy and cfg.config_name != LEGACY_CONFIG_NAME:
            raise FederalRegisterHFReleaseConfigError(
                f"legacy config must be named {LEGACY_CONFIG_NAME!r}"
            )
        if cfg.viewer_safe_default and cfg.config_name != DEFAULT_CONFIG_NAME:
            raise FederalRegisterHFReleaseConfigError(
                "only the default config may be Viewer-safe v2"
            )

    return {
        "config_count": len(resolved),
        "default_config": default.config_name,
        "default_excludes_recovery": True,
        "schema_coherent": True,
        "viewer_safe_default_v2": True,
    }


# ---------------------------------------------------------------------------
# Release artifacts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReleaseArtifact:
    """One immutable release file with full integrity metadata."""

    relative_path: str
    content: bytes = field(repr=False)
    media_type: str
    family: str
    row_count: int = 0
    config_name: str = ""
    schema_id: str = ""
    first_key: Optional[str] = None
    last_key: Optional[str] = None
    year_month: Optional[str] = None
    document_type: Optional[str] = None
    sha256: str = ""
    content_cid: str = ""
    size_bytes: int = 0

    def __post_init__(self) -> None:
        path = normalize_relative_artifact_path(self.relative_path)
        if not isinstance(self.content, (bytes, bytearray)):
            raise FederalRegisterHFReleaseError("artifact content must be bytes")
        content = bytes(self.content)
        digest = hashlib.sha256(content).hexdigest()
        cid = cid_v1_from_digest(bytes.fromhex(digest))
        if self.sha256 and normalize_sha256(self.sha256) != digest:
            raise FederalRegisterHFReleaseIntegrityError(
                f"artifact sha256 mismatch for {path}"
            )
        if self.content_cid and self.content_cid != cid:
            raise FederalRegisterHFReleaseIntegrityError(
                f"artifact content_cid mismatch for {path}"
            )
        if type(self.row_count) is not int or isinstance(self.row_count, bool):
            raise FederalRegisterHFReleaseError("row_count must be a non-negative integer")
        if self.row_count < 0:
            raise FederalRegisterHFReleaseError("row_count must be a non-negative integer")
        bounded = DEFAULT_CONFIG_FAMILIES | RECOVERY_FAMILIES | {
            "source_receipts",
            "routing_index",
        }
        if self.row_count > MAX_ROWS_PER_PHYSICAL_SHARD and self.family in bounded:
            raise FederalRegisterHFReleaseIntegrityError(
                f"artifact {path} row_count={self.row_count} exceeds "
                f"physical bound {MAX_ROWS_PER_PHYSICAL_SHARD}"
            )
        media = str(self.media_type or "").strip()
        if not media:
            raise FederalRegisterHFReleaseError("media_type is required")
        family = _normalize_family(self.family)
        if not family:
            raise FederalRegisterHFReleaseError("family is required")
        schema_id = str(self.schema_id or _FAMILY_SCHEMA_IDS.get(family) or "")
        if not schema_id:
            schema_id = SCHEMA_VERSION
        object.__setattr__(self, "relative_path", path)
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "sha256", digest)
        object.__setattr__(self, "content_cid", cid)
        object.__setattr__(self, "size_bytes", len(content))
        object.__setattr__(self, "media_type", media)
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "schema_id", schema_id)
        object.__setattr__(self, "config_name", str(self.config_name or ""))
        if self.first_key is not None:
            object.__setattr__(self, "first_key", str(self.first_key))
        if self.last_key is not None:
            object.__setattr__(self, "last_key", str(self.last_key))
        if self.year_month is not None:
            object.__setattr__(self, "year_month", str(self.year_month))
        if self.document_type is not None:
            object.__setattr__(self, "document_type", str(self.document_type))

    def to_artifact_descriptor(self) -> ArtifactDescriptor:
        family = _FAMILY_TO_ARTIFACT_FAMILY.get(self.family)
        if family is None:
            if self.relative_path == MANIFEST_FILENAME:
                family = ArtifactFamily.MANIFEST
            elif self.relative_path == RELEASE_METADATA_FILENAME:
                family = ArtifactFamily.RELEASE_METADATA
            elif self.relative_path.startswith("reports/"):
                family = ArtifactFamily.REPORT
            elif self.relative_path.startswith("indexes/"):
                family = ArtifactFamily.ROUTING_INDEX
            elif self.family == "vector_locator":
                family = ArtifactFamily.LOCATOR_INDEX
            else:
                family = ArtifactFamily.RECEIPT
        return ArtifactDescriptor(
            relative_path=self.relative_path,
            media_type=self.media_type,
            sha256=self.sha256,
            size_bytes=self.size_bytes,
            schema_id=self.schema_id,
            family=family,
            row_count=self.row_count,
            first_key=self.first_key,
            last_key=self.last_key,
            year_month=self.year_month,
            document_type=self.document_type,
        )

    def to_file_descriptor(self) -> FileDescriptor:
        return FileDescriptor(
            relative_path=self.relative_path,
            size_bytes=self.size_bytes,
            sha256=self.sha256,
            content_cid=self.content_cid,
            media_type=self.media_type,
            schema_type=self.schema_id,
            producer_id=HF_RELEASE_PRODUCER,
            config_digest=HF_RELEASE_CONFIG,
            row_count=self.row_count,
            config_name=self.config_name,
            license_id=DEFAULT_LICENSE,
            review_status="reviewed",
            trust_decision="public_release_admitted",
            metadata={
                "document_type": self.document_type,
                "family": self.family,
                "first_key": self.first_key,
                "last_key": self.last_key,
                "year_month": self.year_month,
            },
        )

    def descriptor_dict(self) -> dict[str, Any]:
        payload = self.to_artifact_descriptor().to_dict()
        payload["content_cid"] = self.content_cid
        payload["config_name"] = self.config_name
        payload["release_family"] = self.family
        return payload


@dataclass(frozen=True, slots=True)
class FederalRegisterHuggingFaceRelease:
    """Complete in-memory (or staged) Federal Register Hugging Face release."""

    dataset_id: str
    release_root_cid: str
    manifest_digest: str
    schema_version: str
    release_profile: str
    source_revision: str
    build_config_cid: str
    vector_space_id: str
    model_id: str
    model_revision: str
    configs: tuple[ViewerConfig, ...]
    artifacts: tuple[ReleaseArtifact, ...]
    dry_run: bool
    staged_root: Optional[str] = None
    package_version: str = DEFAULT_PACKAGE_VERSION
    source_rights_receipt_digest: str = ""
    observation_cutoff: str = DEFAULT_OBSERVATION_CUTOFF
    lcr061_consumption_digest: str = ""

    def __post_init__(self) -> None:
        if not _DATASET_ID_RE.fullmatch(self.dataset_id):
            raise FederalRegisterHFReleaseError("dataset_id must be owner/name")
        if self.dataset_id != DEFAULT_DATASET_REPO_ID:
            raise FederalRegisterHFReleaseSafetyError(
                f"dataset_id must be {DEFAULT_DATASET_REPO_ID!r}"
            )
        if not self.artifacts:
            raise FederalRegisterHFReleaseError("release must contain artifacts")
        paths = [item.relative_path for item in self.artifacts]
        if len(paths) != len(set(paths)):
            raise FederalRegisterHFReleaseIntegrityError("artifact paths must be unique")
        ordered = tuple(sorted(self.artifacts, key=lambda item: item.relative_path))
        object.__setattr__(self, "artifacts", ordered)
        if type(self.dry_run) is not bool:
            raise FederalRegisterHFReleaseError("dry_run must be boolean")
        require_immutable_revision(self.source_revision, name="source_revision")
        require_immutable_revision(self.model_revision, name="model_revision")
        if self.model_id != DEFAULT_EMBEDDING_MODEL_ID:
            raise FederalRegisterHFReleaseSafetyError(
                f"model_id must be {DEFAULT_EMBEDDING_MODEL_ID!r}"
            )
        if self.model_revision != DEFAULT_EMBEDDING_MODEL_REVISION:
            raise FederalRegisterHFReleaseSafetyError(
                "model_revision must be the pinned thenlper/gte-small revision"
            )
        cid = str(self.release_root_cid)
        if not _CID_RE.fullmatch(cid) and not _SHA256_RE.fullmatch(cid):
            if not cid.startswith("b") and len(cid) != 64:
                raise FederalRegisterHFReleaseIntegrityError(
                    f"invalid release_root_cid: {self.release_root_cid!r}"
                )

    def artifact(self, relative_path: str) -> ReleaseArtifact:
        for item in self.artifacts:
            if item.relative_path == relative_path:
                return item
        raise KeyError(relative_path)

    @property
    def data_artifacts(self) -> tuple[ReleaseArtifact, ...]:
        return tuple(
            item
            for item in self.artifacts
            if item.relative_path.startswith("data/")
            or item.relative_path.startswith("recovery/")
            or item.relative_path.startswith("quarantine/")
            or item.relative_path.startswith("indexes/")
            or item.relative_path.startswith("receipts/")
            or item.relative_path.startswith("federal_register")
        )

    @property
    def control_plane_artifacts(self) -> tuple[ReleaseArtifact, ...]:
        return tuple(
            item
            for item in self.artifacts
            if item.relative_path in CONTROL_PLANE_PATHS
            or (
                item.relative_path.startswith("reports/")
                and item.relative_path != LINEAGE_REPORT_PATH
            )
        )

    @property
    def lineage_artifact(self) -> Optional[ReleaseArtifact]:
        for item in self.artifacts:
            if item.relative_path == LINEAGE_REPORT_PATH:
                return item
        return None

    def manifest_dict(self) -> dict[str, Any]:
        return json.loads(self.artifact(MANIFEST_FILENAME).content.decode("utf-8"))

    def release_metadata_dict(self) -> dict[str, Any]:
        return json.loads(
            self.artifact(RELEASE_METADATA_FILENAME).content.decode("utf-8")
        )

    def dataset_card_text(self) -> str:
        return self.artifact(README_FILENAME).content.decode("utf-8")

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifacts": [item.descriptor_dict() for item in self.artifacts],
            "build_config_cid": self.build_config_cid,
            "configs": [cfg.to_dict() for cfg in self.configs],
            "dataset_id": self.dataset_id,
            "dry_run": self.dry_run,
            "lcr061_consumption_digest": self.lcr061_consumption_digest,
            "manifest_digest": self.manifest_digest,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "observation_cutoff": self.observation_cutoff,
            "package_version": self.package_version,
            "release_profile": self.release_profile,
            "release_root_cid": self.release_root_cid,
            "schema_version": self.schema_version,
            "source_revision": self.source_revision,
            "source_rights_receipt_digest": self.source_rights_receipt_digest,
            "staged_root": self.staged_root,
            "vector_space_id": self.vector_space_id,
        }


# ---------------------------------------------------------------------------
# Family / encoding helpers
# ---------------------------------------------------------------------------


def _normalize_family(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return _FAMILY_ALIASES.get(text, text)


def _config_for_family(family: str) -> str:
    if family == "recovery":
        return RECOVERY_CONFIG_NAME
    if family == "quarantine":
        return QUARANTINE_CONFIG_NAME
    if family == LEGACY_CONFIG_NAME:
        return LEGACY_CONFIG_NAME
    return DEFAULT_CONFIG_NAME


def _partition_key(row: Mapping[str, Any]) -> tuple[str, str]:
    year_month = str(row.get("year_month") or "").strip()
    document_type = str(row.get("document_type") or "").strip()
    return year_month, document_type


def _family_relative_path(
    family: str,
    *,
    shard: int,
    year_month: str = "",
    document_type: str = "",
) -> str:
    if family in {"corpus", "bm25_documents"} and year_month and document_type:
        root = "data/corpus" if family == "corpus" else "data/bm25/documents"
        return (
            f"{root}/year_month={year_month}/document_type={document_type}/"
            f"part-{shard:06d}.parquet"
        )
    return _FAMILY_PATH_TEMPLATES[family].format(shard=shard)


def _encode_parquet_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    family: str,
) -> bytes:
    """Encode rows as deterministic ZSTD Parquet bytes (optional pyarrow)."""

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise FederalRegisterHFReleaseError(
            "parquet encoding requires the optional 'pyarrow' package"
        ) from exc

    entry_cids: list[str] = []
    legal_ids: list[str] = []
    document_numbers: list[str] = []
    publication_dates: list[str] = []
    document_types: list[str] = []
    year_months: list[str] = []
    families: list[str] = []
    record_json: list[str] = []
    record_sha256: list[str] = []
    for row in rows:
        payload = dict(row)
        payload.setdefault("family", family)
        encoded = canonical_json_bytes(payload).decode("utf-8")
        record_json.append(encoded)
        record_sha256.append(hashlib.sha256(encoded.encode("utf-8")).hexdigest())
        entry_cids.append(
            str(
                payload.get("entry_cid")
                or payload.get("recovery_id")
                or payload.get("centroid_id")
                or payload.get("node_cid")
                or payload.get("record_id")
                or payload.get("receipt_id")
                or payload.get("receipt_cid")
                or ""
            )
        )
        legal_ids.append(
            str(payload.get("legal_id") or payload.get("term") or payload.get("node_key") or "")
        )
        document_numbers.append(str(payload.get("document_number") or ""))
        publication_dates.append(str(payload.get("publication_date") or ""))
        document_types.append(str(payload.get("document_type") or ""))
        year_months.append(str(payload.get("year_month") or ""))
        families.append(family)

    table = pa.table(
        {
            "entry_cid": entry_cids,
            "legal_id": legal_ids,
            "document_number": document_numbers,
            "publication_date": publication_dates,
            "document_type": document_types,
            "year_month": year_months,
            "family": families,
            "record_sha256": record_sha256,
            "record_json": record_json,
        }
    )
    buffer = io.BytesIO()
    pq.write_table(
        table,
        buffer,
        compression="zstd",
        compression_level=6,
        use_dictionary=True,
        write_statistics=True,
        write_page_index=False,
        data_page_version="1.0",
    )
    return buffer.getvalue()


def _encode_json_family(rows: Sequence[Mapping[str, Any]], *, family: str) -> bytes:
    payload = {
        "authorizing_for_publication": False,
        "family": family,
        "quarantined": family in RECOVERY_FAMILIES,
        "rows": [dict(row) for row in rows],
        "schema_version": _FAMILY_SCHEMA_IDS.get(family, SCHEMA_VERSION),
    }
    reject_identity_contamination(payload, label=f"{family}-json")
    return canonical_json_bytes(payload) + b"\n"


def _row_sort_key(row: Mapping[str, Any], family: str) -> tuple[str, ...]:
    if family in RECOVERY_FAMILIES:
        return (
            str(row.get("recovery_id") or row.get("entry_cid") or row.get("legal_id") or ""),
            str(row.get("record_sha256") or row.get("raw_digest") or ""),
        )
    if family == "bm25_postings":
        return (str(row.get("term") or ""), str(row.get("entry_cid") or row.get("chunk_cid") or ""))
    if family == "centroids":
        return (str(row.get("centroid_id") or row.get("cluster_id") or ""),)
    if family == "vector_locator":
        return (
            str(row.get("entry_cid") or row.get("first_key") or ""),
            str(row.get("chunk_cid") or ""),
            f"{int(row.get('row_offset') or row.get('page_index') or 0):08d}",
        )
    if family == "graph_nodes":
        return (str(row.get("node_cid") or row.get("entry_cid") or ""),)
    if family == "graph_edges":
        return (
            str(row.get("edge_cid") or ""),
            str(row.get("source_node_cid") or ""),
            str(row.get("target_node_cid") or ""),
        )
    if family in {"graph_adjacency_out", "graph_adjacency_in"}:
        return (
            str(row.get("node_cid") or ""),
            f"{int(row.get('page_index') or 0):08d}",
        )
    if family == "source_receipts":
        return (
            str(row.get("year_month") or ""),
            str(row.get("receipt_id") or row.get("receipt_cid") or ""),
        )
    return (
        str(row.get("year_month") or ""),
        str(row.get("document_number") or ""),
        str(row.get("entry_cid") or row.get("record_id") or ""),
        str(row.get("legal_id") or ""),
    )


def _first_last_keys(
    rows: Sequence[Mapping[str, Any]], family: str
) -> tuple[Optional[str], Optional[str]]:
    if not rows:
        return None, None
    keys = [":".join(_row_sort_key(row, family)) for row in rows]
    return keys[0] or None, keys[-1] or None


def route_bounds_policy() -> dict[str, int]:
    """Sealed physical and routing bounds bound into the release manifest."""

    bounds = dict(identity_physical_bounds())
    bounds["default_candidate_centroids"] = DEFAULT_CANDIDATE_CENTROIDS
    bounds["embedding_dimension"] = DEFAULT_EMBEDDING_DIMENSION
    bounds["max_adjacency_pointers_per_row"] = MAX_ADJACENCY_POINTERS_PER_ROW
    bounds["max_posting_pointers_per_row"] = MAX_POSTING_POINTERS_PER_ROW
    bounds["max_rows_per_physical_shard"] = MAX_ROWS_PER_PHYSICAL_SHARD
    bounds["max_rows_per_vector_centroid"] = MAX_ROWS_PER_VECTOR_CENTROID
    bounds["max_vector_shards_per_centroid"] = MAX_VECTOR_SHARDS_PER_CENTROID
    bounds["model_token_ceiling"] = DEFAULT_MODEL_TOKEN_CEILING
    return bounds


def rollback_map() -> dict[str, Any]:
    """Old-pin rollback metadata for the previous public Federal Register pin."""

    return {
        "additive_only": True,
        "authorizing_for_publication": False,
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "legacy_files_deleted": False,
        "previous_public_pin": PREVIOUS_PUBLIC_PIN,
        "reason": "restore previous public pin if the additive v2 candidate is rolled back",
        "to_revision": PREVIOUS_PUBLIC_PIN,
    }


def _family_binding(
    artifacts: Sequence[ReleaseArtifact],
    families: Sequence[str],
) -> dict[str, Any]:
    wanted = {_normalize_family(name) for name in families}
    matching = [item for item in artifacts if item.family in wanted]
    matching = sorted(matching, key=lambda item: item.relative_path)
    return {
        "artifact_count": len(matching),
        "artifacts": [item.descriptor_dict() for item in matching],
        "families": sorted(wanted),
        "first_keys": [item.first_key for item in matching],
        "last_keys": [item.last_key for item in matching],
        "relative_paths": [item.relative_path for item in matching],
        "row_count": sum(item.row_count for item in matching),
        "sha256": [item.sha256 for item in matching],
        "size_bytes": sum(item.size_bytes for item in matching),
    }


# ---------------------------------------------------------------------------
# Dataset card
# ---------------------------------------------------------------------------


def render_dataset_card(
    *,
    dataset_id: str = DEFAULT_DATASET_REPO_ID,
    release_profile: str = RELEASE_PROFILE,
    source_revision: str = DEFAULT_SOURCE_REVISION,
    configs: Sequence[ViewerConfig] | None = None,
    vector_space_id: str = "",
    model_id: str = PINNED_MODEL_ID,
    model_revision: str = PINNED_MODEL_REVISION,
    limitations: Sequence[str] | None = None,
    currentness_disclaimer: str = CURRENTNESS_DISCLAIMER,
    source_rights: Mapping[str, Any] | None = None,
) -> str:
    """Render the sealed Dataset card (README.md) with YAML frontmatter."""

    viewer_configs = tuple(configs or advertised_viewer_configs())
    assert_configs_schema_coherent(viewer_configs)
    space = vector_space_id or default_vector_space_id()
    rights = source_scope_rights_summary(source_rights)
    digest = str(rights["source_rights_receipt_digest"])
    catalog = str(rights.get("catalog_digest_sha256") or "")
    safe_limitations = tuple(
        limitations
        or (
            "Retrieval output is a research aid and is not a substitute for "
            "the official Federal Register or GovInfo publications.",
            "Acquisition and publication timestamps are not legal-currentness claims.",
            "Recovery and quarantine rows are excluded from the default v2 "
            "config and from corpus/BM25/vector/graph counts until admitted.",
            "Unknown or prohibited source-rights dispositions cannot enter the "
            "default Viewer config.",
            "Legacy federal_register.parquet / JSON-LD / FAISS remains available "
            "only through the explicit compatibility configuration for one "
            "deprecation cycle.",
        )
    )

    lines: list[str] = [
        "---",
        f"license: {DEFAULT_LICENSE}",
        'pretty_name: "Federal Register Sparse GraphRAG"',
        "tags:",
        "  - legal",
        "  - federal-register",
        "  - graphrag",
        "  - justicedao",
        "  - public-domain-us-government",
        "configs:",
    ]
    for cfg in viewer_configs:
        lines.extend(cfg.yaml_block())
    lines.extend(
        [
            "---",
            "",
            "# Federal Register Sparse GraphRAG",
            "",
            f"Dataset repository: `{dataset_id}`",
            "",
            "## Release profile",
            "",
            f"- Profile: `{release_profile}`",
            f"- Pinned source revision: `{source_revision}`",
            f"- Observation cutoff: `{DEFAULT_OBSERVATION_CUTOFF}`",
            f"- Embedding model: `{model_id}` @ `{model_revision}`",
            f"- Vector space: `{space}`",
            f"- Primary key (default config): `{PRIMARY_KEY_V2}`",
            f"- Default configuration: `{DEFAULT_CONFIG_NAME}` (Viewer-safe v2)",
            f"- Previous public pin (rollback): `{PREVIOUS_PUBLIC_PIN}`",
            "",
            "## Dataset configurations",
            "",
            "The **default** configuration is Viewer-safe v2 Federal Register "
            "documents only. Recovery JSON, quarantine JSON, and legacy "
            "federal_register.parquet / JSON-LD / FAISS files are advertised as "
            "separate named configs and never contaminate the default Dataset "
            "Viewer schema.",
            "",
        ]
    )
    for cfg in viewer_configs:
        if cfg.is_default:
            role = "default v2"
        elif cfg.is_legacy:
            role = "legacy compatibility"
        elif cfg.is_recovery:
            role = "recovery"
        elif cfg.is_quarantine:
            role = "quarantine"
        else:
            role = "named non-default"
        lines.append(
            f"- `{cfg.config_name}` ({role}) — primary key `{cfg.primary_key}`"
        )
        for note in cfg.notes:
            lines.append(f"  - {note}")
    lines.extend(
        [
            "",
            "## Artifact layout",
            "",
            "```text",
            "README.md",
            "manifest.json",
            "release_metadata.json",
            "dataset_configs.json",
            "dataset_infos.json",
            "data/corpus/year_month=*/document_type=*/part-*.parquet",
            "data/bm25/documents/year_month=*/document_type=*/part-*.parquet",
            "data/bm25/postings/part-*.parquet",
            "data/vectors/centroid-*-part-*.parquet",
            "data/vectors/centroids/part-*.parquet",
            "data/vectors/locator/part-*.parquet",
            "data/graph/nodes/part-*.parquet",
            "data/graph/edges/part-*.parquet",
            "data/graph/adjacency/out/part-*.parquet",
            "data/graph/adjacency/in/part-*.parquet",
            "indexes/*",
            "receipts/source/*",
            "reports/admission.json",
            "reports/quality.json",
            "reports/reproducibility.json",
            "reports/lineage.json   # verbose lineage (not control plane)",
            "recovery/...          # recovery config only",
            "quarantine/...        # quarantine config only",
            "federal_register.parquet  # legacy compatibility config only",
            "```",
            "",
            "## Control plane vs verbose lineage",
            "",
            "The control plane consists of `manifest.json`, `release_metadata.json`, "
            "routing indexes, source-receipt descriptors, and compact "
            "admission/quality/reproducibility reports. Verbose per-row source "
            "lineage lives only in `reports/lineage.json` and is **not** mixed "
            "into Dataset Viewer configs or the release control plane.",
            "",
            "## Source-scope rights summary",
            "",
            "This additive fixture assembly binds the LCR-078/LCR-079/LCR-083 "
            "source-rights compliance receipt and cannot authorize publication.",
            "",
            f"- Receipt path: `{SOURCE_RIGHTS_RECEIPT_RELPATH}`",
            f"- Source-rights receipt digest: `{digest}`",
            f"- Source-rights catalog digest: `{catalog}`",
            f"- Admitted source-scope records: {rights['admitted_count']}",
            "- Unknown or prohibited rights cannot enter the default v2 release.",
            "- Fixture receipts set `authorizing_for_publication=false`.",
            "",
            "## Route bounds",
            "",
            f"- At most {MAX_ROWS_PER_PHYSICAL_SHARD} rows per physical shard.",
            f"- At most {MAX_POSTING_POINTERS_PER_ROW} BM25 posting pointers per cell.",
            f"- At most {MAX_ADJACENCY_POINTERS_PER_ROW} adjacency pointers per page.",
            f"- At most {MAX_ROWS_PER_VECTOR_CENTROID} vectors and "
            f"{MAX_VECTOR_SHARDS_PER_CENTROID} shards per centroid.",
            f"- Model token ceiling is {DEFAULT_MODEL_TOKEN_CEILING}; it is not a "
            "shard bound.",
            "",
            "## Currentness disclaimer",
            "",
            currentness_disclaimer,
            "",
            "## Limitations",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in safe_limitations)
    lines.extend(
        [
            "",
            "## Integrity",
            "",
            "Every artifact is descriptor-bound in `manifest.json` with relative "
            "path, media type, row count, byte count, SHA-256, schema identifier, "
            "and optional key range. The manifest also binds corpus, BM25, "
            "vectors, centroids, the vector locator, the legal graph, two-way "
            "adjacency, recovery, source receipts, the pinned model revision, "
            "route bounds, old-pin rollback metadata, and the source-rights "
            "receipt digest.",
            "",
            f"Producer: `{PRODUCER}` (`{TASK_ID}` / `{GOAL_ID}`).",
            "",
        ]
    )
    return "\n".join(lines)


def load_fixture_dataset_card(path: str | Path | None = None) -> str:
    """Load the sealed ``FEDERAL_REGISTER_DATASET_CARD.md`` template."""

    candidates: list[Path] = []
    if path is not None:
        candidates.append(Path(path))
    candidates.extend(
        [
            Path(DATASET_CARD_TEMPLATE_RELPATH),
            Path.cwd() / DATASET_CARD_TEMPLATE_RELPATH,
            _repo_root() / DATASET_CARD_TEMPLATE_RELPATH,
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    raise FederalRegisterHFReleaseError(
        "FEDERAL_REGISTER_DATASET_CARD.md template not found"
    )


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FederalRegisterHFReleaseBuilder:
    """Deterministic local builder for Federal Register HF release candidates."""

    dataset_id: str = DEFAULT_DATASET_REPO_ID
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD
    source_revision: str = DEFAULT_SOURCE_REVISION
    model_id: str = PINNED_MODEL_ID
    model_revision: str = PINNED_MODEL_REVISION
    tokenizer_id: str = TOKENIZER_ID
    graph_ontology_version: str = DEFAULT_GRAPH_ONTOLOGY_VERSION
    determinism_seed: int = DEFAULT_DETERMINISM_SEED
    observation_cutoff: str = DEFAULT_OBSERVATION_CUTOFF
    include_legacy_config: bool = True
    include_recovery_config: bool = True
    include_quarantine_config: bool = True

    def __post_init__(self) -> None:
        if not _DATASET_ID_RE.fullmatch(self.dataset_id):
            raise FederalRegisterHFReleaseError("dataset_id must be owner/name")
        if self.dataset_id != DEFAULT_DATASET_REPO_ID:
            raise FederalRegisterHFReleaseSafetyError(
                f"dataset_id must be {DEFAULT_DATASET_REPO_ID!r}"
            )
        if (
            type(self.max_rows_per_shard) is not int
            or isinstance(self.max_rows_per_shard, bool)
            or self.max_rows_per_shard <= 0
            or self.max_rows_per_shard > MAX_ROWS_PER_PHYSICAL_SHARD
        ):
            raise FederalRegisterHFReleaseError(
                f"max_rows_per_shard must be in 1..{MAX_ROWS_PER_PHYSICAL_SHARD}"
            )
        require_immutable_revision(self.source_revision, name="source_revision")
        object.__setattr__(
            self,
            "model_revision",
            require_immutable_revision(self.model_revision, name="model_revision"),
        )
        if self.model_id != DEFAULT_EMBEDDING_MODEL_ID:
            raise FederalRegisterHFReleaseSafetyError(
                f"model_id must be {DEFAULT_EMBEDDING_MODEL_ID!r}"
            )
        if self.model_revision != DEFAULT_EMBEDDING_MODEL_REVISION:
            raise FederalRegisterHFReleaseSafetyError(
                "model_revision must be the pinned thenlper/gte-small revision"
            )
        _assert_no_upload_shortcut()

    def build(
        self,
        family_rows: Mapping[str, Sequence[Mapping[str, Any]]],
        *,
        dry_run: bool = True,
        output_dir: str | Path | None = None,
        admission_summary: Mapping[str, Any] | None = None,
        preserve_existing: Sequence[str] | None = None,
        legacy_files: Mapping[str, bytes] | None = None,
        source_rights: Mapping[str, Any] | None = None,
        lcr061_consumption: Mapping[str, Any] | None = None,
    ) -> FederalRegisterHuggingFaceRelease:
        """Build a descriptor-complete release from family rows."""

        _assert_no_upload_shortcut()
        reject_hub_upload(False)
        if type(dry_run) is not bool:
            raise FederalRegisterHFReleaseError("dry_run must be boolean")

        rights = dict(source_rights or load_source_rights_receipt())
        consumption = dict(lcr061_consumption or consume_lcr061_family_outputs())
        vector_space = default_vector_space_id()
        build_config_cid = digest_mapping(
            {
                "dataset_id": self.dataset_id,
                "determinism_seed": self.determinism_seed,
                "graph_ontology_version": self.graph_ontology_version,
                "lcr061_consumption_digest": consumption.get("consumption_digest") or "",
                "max_rows_per_shard": self.max_rows_per_shard,
                "model_id": self.model_id,
                "model_revision": self.model_revision,
                "observation_cutoff": self.observation_cutoff,
                "schema_version": SCHEMA_VERSION,
                "source_revision": self.source_revision,
                "source_rights_receipt_digest": rights["receipt_digest"],
                "tokenizer_id": self.tokenizer_id,
                "vector_space_id": vector_space,
            }
        )

        data_artifacts = self._build_data_artifacts(family_rows, rights=rights)
        legacy_artifacts = self._build_legacy_artifacts(legacy_files or {})

        configs = advertised_viewer_configs(
            include_legacy=self.include_legacy_config,
            include_recovery=self.include_recovery_config,
            include_quarantine=self.include_quarantine_config,
        )
        assert_configs_schema_coherent(configs)

        reports = self._build_reports(
            data_artifacts=data_artifacts,
            family_rows=family_rows,
            admission_summary=admission_summary or {},
            build_config_cid=build_config_cid,
            vector_space_id=vector_space,
            rights=rights,
            consumption=consumption,
        )
        card_text = render_dataset_card(
            dataset_id=self.dataset_id,
            release_profile=RELEASE_PROFILE,
            source_revision=self.source_revision,
            configs=configs,
            vector_space_id=vector_space,
            model_id=self.model_id,
            model_revision=self.model_revision,
            source_rights=rights,
        )
        _assert_no_secrets_or_absolute_paths(card_text, label="dataset-card")
        card_artifact = ReleaseArtifact(
            relative_path=README_FILENAME,
            content=card_text.encode("utf-8"),
            media_type=MARKDOWN_MEDIA_TYPE,
            family="receipt",
            row_count=0,
            schema_id=SCHEMA_VERSION,
        )
        configs_payload = {
            "authorizing_for_publication": False,
            "configs": [cfg.to_dict() for cfg in configs],
            "default_config": DEFAULT_CONFIG_NAME,
            "default_excludes_recovery": True,
            "schema_version": SCHEMA_VERSION,
            "task_id": TASK_ID,
            "viewer_safe_default_v2": True,
        }
        reject_identity_contamination(configs_payload, label="dataset-configs")
        configs_artifact = ReleaseArtifact(
            relative_path=DATASET_CONFIGS_FILENAME,
            content=canonical_json_bytes(configs_payload) + b"\n",
            media_type=JSON_MEDIA_TYPE,
            family="receipt",
            row_count=0,
            schema_id=SCHEMA_VERSION,
        )
        infos_payload = _dataset_infos(
            dataset_id=self.dataset_id,
            data_artifacts=(*data_artifacts, *legacy_artifacts),
            configs=configs,
        )
        reject_identity_contamination(infos_payload, label="dataset-infos")
        infos_artifact = ReleaseArtifact(
            relative_path=DATASET_INFOS_FILENAME,
            content=canonical_json_bytes(infos_payload) + b"\n",
            media_type=JSON_MEDIA_TYPE,
            family="receipt",
            row_count=0,
            schema_id=SCHEMA_VERSION,
        )

        support_pre_manifest = (
            card_artifact,
            configs_artifact,
            infos_artifact,
            *reports,
        )
        all_pre = tuple(data_artifacts) + tuple(legacy_artifacts) + support_pre_manifest
        release_root_cid = _compute_release_root_cid(
            dataset_id=self.dataset_id,
            artifacts=all_pre,
            build_config_cid=build_config_cid,
        )
        metadata_payload = _release_metadata_payload(
            dataset_id=self.dataset_id,
            release_root_cid=release_root_cid,
            build_config_cid=build_config_cid,
            source_revision=self.source_revision,
            vector_space_id=vector_space,
            model_id=self.model_id,
            model_revision=self.model_revision,
            tokenizer_id=self.tokenizer_id,
            graph_ontology_version=self.graph_ontology_version,
            determinism_seed=self.determinism_seed,
            configs=configs,
            dry_run=dry_run,
            rights=rights,
            observation_cutoff=self.observation_cutoff,
            consumption=consumption,
        )
        reject_identity_contamination(metadata_payload, label="release-metadata")
        metadata_artifact = ReleaseArtifact(
            relative_path=RELEASE_METADATA_FILENAME,
            content=canonical_json_bytes(metadata_payload) + b"\n",
            media_type=JSON_MEDIA_TYPE,
            family="release_metadata",
            row_count=0,
            schema_id=SCHEMA_VERSION,
        )

        manifest_body = self._build_manifest_body(
            data_artifacts=(*data_artifacts, *legacy_artifacts),
            support_artifacts=(*support_pre_manifest, metadata_artifact),
            configs=configs,
            build_config_cid=build_config_cid,
            release_root_cid=release_root_cid,
            vector_space_id=vector_space,
            rights=rights,
            card_text=card_text,
            consumption=consumption,
        )
        reject_identity_contamination(manifest_body, label="manifest")
        _assert_no_secrets_or_absolute_paths(manifest_body, label="manifest")
        manifest_digest = digest_mapping(
            {key: value for key, value in manifest_body.items() if key != "manifest_digest"}
        )
        manifest_body["manifest_digest"] = manifest_digest
        manifest_artifact = ReleaseArtifact(
            relative_path=MANIFEST_FILENAME,
            content=canonical_json_bytes(manifest_body) + b"\n",
            media_type=JSON_MEDIA_TYPE,
            family="manifest",
            row_count=0,
            schema_id=SCHEMA_VERSION,
        )

        release = FederalRegisterHuggingFaceRelease(
            dataset_id=self.dataset_id,
            release_root_cid=release_root_cid,
            manifest_digest=manifest_digest,
            schema_version=SCHEMA_VERSION,
            release_profile=RELEASE_PROFILE,
            source_revision=self.source_revision,
            build_config_cid=build_config_cid,
            vector_space_id=vector_space,
            model_id=self.model_id,
            model_revision=self.model_revision,
            configs=configs,
            artifacts=(
                *data_artifacts,
                *legacy_artifacts,
                *support_pre_manifest,
                metadata_artifact,
                manifest_artifact,
            ),
            dry_run=dry_run,
            staged_root=None,
            source_rights_receipt_digest=str(rights["receipt_digest"]),
            observation_cutoff=self.observation_cutoff,
            lcr061_consumption_digest=str(consumption.get("consumption_digest") or ""),
        )
        validate_federal_register_hf_release(release)
        if dry_run:
            return release
        if output_dir is None:
            raise FederalRegisterHFReleaseError(
                "output_dir is required when dry_run is false"
            )
        return stage_federal_register_hf_release(
            release,
            output_dir,
            dry_run=False,
            preserve_existing=preserve_existing,
        )

    def _build_data_artifacts(
        self,
        family_rows: Mapping[str, Sequence[Mapping[str, Any]]],
        *,
        rights: Mapping[str, Any],
    ) -> tuple[ReleaseArtifact, ...]:
        artifacts: list[ReleaseArtifact] = []
        if not isinstance(family_rows, Mapping):
            raise FederalRegisterHFReleaseError("family_rows must be a mapping")

        for family in sorted(family_rows):
            fam = _normalize_family(family)
            if fam not in _FAMILY_PATH_TEMPLATES:
                raise FederalRegisterHFReleaseError(f"unknown artifact family: {family!r}")
            rows = list(family_rows[family] or ())
            if not rows:
                continue
            for row in rows:
                if not isinstance(row, Mapping):
                    raise FederalRegisterHFReleaseError(
                        f"family {fam!r} rows must be mappings"
                    )
                _assert_row_rights_admissible(row, family=fam, receipt=rights)
            ordered = sorted(rows, key=lambda r: _row_sort_key(r, fam))
            groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
            if fam in {"corpus", "bm25_documents"}:
                for row in ordered:
                    groups[_partition_key(row)].append(row)
            else:
                groups[("", "")] = ordered
            config_name = _config_for_family(fam)
            for (year_month, document_type), group_rows in sorted(groups.items()):
                shards = shard_sequence(group_rows, max_rows=self.max_rows_per_shard)
                for shard_index, shard_rows in enumerate(shards):
                    if not shard_rows:
                        continue
                    if fam in JSON_FAMILIES:
                        content = _encode_json_family(shard_rows, family=fam)
                        media = JSON_MEDIA_TYPE
                    else:
                        content = _encode_parquet_rows(shard_rows, family=fam)
                        media = PARQUET_MEDIA_TYPE
                    first_key, last_key = _first_last_keys(shard_rows, fam)
                    artifacts.append(
                        ReleaseArtifact(
                            relative_path=_family_relative_path(
                                fam,
                                shard=shard_index,
                                year_month=year_month,
                                document_type=document_type,
                            ),
                            content=content,
                            media_type=media,
                            family=fam,
                            row_count=len(shard_rows),
                            config_name=config_name,
                            schema_id=_FAMILY_SCHEMA_IDS[fam],
                            first_key=first_key,
                            last_key=last_key,
                            year_month=year_month or None,
                            document_type=document_type or None,
                        )
                    )

        by_family: dict[str, list[ReleaseArtifact]] = defaultdict(list)
        for art in artifacts:
            if art.family not in RECOVERY_FAMILIES and art.family != "source_receipts":
                if art.config_name == DEFAULT_CONFIG_NAME:
                    by_family[art.family].append(art)
        for fam in sorted(by_family):
            shards = sorted(by_family[fam], key=lambda a: a.relative_path)
            index_rows = [
                {
                    "family": fam,
                    "relative_path": art.relative_path,
                    "sha256": art.sha256,
                    "content_cid": art.content_cid,
                    "row_count": art.row_count,
                    "size_bytes": art.size_bytes,
                    "first_key": art.first_key,
                    "last_key": art.last_key,
                    "schema_id": art.schema_id,
                    "year_month": art.year_month,
                    "document_type": art.document_type,
                }
                for art in shards
            ]
            content = _encode_parquet_rows(index_rows, family="routing_index")
            artifacts.append(
                ReleaseArtifact(
                    relative_path=f"indexes/{fam}_chunks-000000.parquet",
                    content=content,
                    media_type=PARQUET_MEDIA_TYPE,
                    family="routing_index",
                    row_count=len(index_rows),
                    config_name=DEFAULT_CONFIG_NAME,
                    schema_id=_FAMILY_SCHEMA_IDS["routing_index"],
                    first_key=index_rows[0]["relative_path"],
                    last_key=index_rows[-1]["relative_path"],
                )
            )
        return tuple(sorted(artifacts, key=lambda a: a.relative_path))

    def _build_legacy_artifacts(
        self,
        legacy_files: Mapping[str, bytes],
    ) -> tuple[ReleaseArtifact, ...]:
        artifacts: list[ReleaseArtifact] = []
        allowed_prefixes = (
            "federal_register.parquet",
            "federal_register.jsonld",
            "federal_register_raw/",
            "federal_register_gte_small.faiss",
            "federal_register_gte_small_metadata.parquet",
        )
        for relative_path, content in sorted(legacy_files.items()):
            path = normalize_relative_artifact_path(relative_path)
            if not any(path == prefix or path.startswith(prefix) for prefix in allowed_prefixes):
                raise FederalRegisterHFReleaseSafetyError(
                    f"legacy path must be a Federal Register baseline artifact, got {path!r}"
                )
            if not isinstance(content, (bytes, bytearray)):
                raise FederalRegisterHFReleaseError("legacy file content must be bytes")
            if path.endswith(".jsonld"):
                media = JSONLD_MEDIA_TYPE
            elif path.endswith(".faiss"):
                media = "application/octet-stream"
            else:
                media = PARQUET_MEDIA_TYPE
            artifacts.append(
                ReleaseArtifact(
                    relative_path=path,
                    content=bytes(content),
                    media_type=media,
                    family=LEGACY_CONFIG_NAME,
                    row_count=0,
                    config_name=LEGACY_CONFIG_NAME,
                    schema_id=_FAMILY_SCHEMA_IDS[LEGACY_CONFIG_NAME],
                )
            )
        return tuple(sorted(artifacts, key=lambda a: a.relative_path))

    def _build_reports(
        self,
        *,
        data_artifacts: Sequence[ReleaseArtifact],
        family_rows: Mapping[str, Sequence[Mapping[str, Any]]],
        admission_summary: Mapping[str, Any],
        build_config_cid: str,
        vector_space_id: str,
        rights: Mapping[str, Any],
        consumption: Mapping[str, Any],
    ) -> tuple[ReleaseArtifact, ...]:
        family_counts = {
            _normalize_family(fam): sum(1 for _ in (family_rows.get(fam) or ()))
            for fam in sorted(family_rows)
        }
        admitted = int(
            admission_summary.get("admitted_count", family_counts.get("corpus", 0))
        )
        recovery_count = int(
            admission_summary.get(
                "recovery_quarantine_count",
                family_counts.get("recovery", 0) + family_counts.get("quarantine", 0),
            )
        )
        admission = {
            "admitted_count": admitted,
            "authorizing_for_publication": False,
            "build_config_cid": build_config_cid,
            "default_config_excludes_recovery": True,
            "family_counts": family_counts,
            "goal_id": GOAL_ID,
            "lcr061_consumption_digest": consumption.get("consumption_digest") or "",
            "observation_cutoff": self.observation_cutoff,
            "producer": PRODUCER,
            "recovery_excluded_from_families": sorted(DEFAULT_CONFIG_FAMILIES),
            "recovery_quarantine_count": recovery_count,
            "release_profile": RELEASE_PROFILE,
            "schema_version": SCHEMA_VERSION,
            "source_revision": self.source_revision,
            "source_rights_receipt_digest": rights["receipt_digest"],
            "task_id": TASK_ID,
            "viewer_safe_default_v2": True,
        }
        for key in ("disposition_counts", "notes"):
            if key in admission_summary:
                admission[key] = admission_summary[key]
        reject_identity_contamination(admission, label="admission-report")

        quality = {
            "artifact_count": len(data_artifacts),
            "authorizing_for_publication": False,
            "build_config_cid": build_config_cid,
            "configs_schema_coherent": True,
            "default_config": DEFAULT_CONFIG_NAME,
            "default_excludes_recovery": True,
            "descriptor_bound_artifacts": True,
            "every_artifact_descriptor_bound": True,
            "goal_id": GOAL_ID,
            "max_rows_per_physical_shard": self.max_rows_per_shard,
            "producer": PRODUCER,
            "route_bounds": route_bounds_policy(),
            "schema_version": SCHEMA_VERSION,
            "source_rights_receipt_digest": rights["receipt_digest"],
            "task_id": TASK_ID,
            "vector_space_id": vector_space_id,
            "viewer_safe_default_v2": True,
        }
        reject_identity_contamination(quality, label="quality-report")

        reproducibility = {
            "authorizing_for_publication": False,
            "build_config_cid": build_config_cid,
            "determinism_seed": self.determinism_seed,
            "goal_id": GOAL_ID,
            "lcr061_consumption_digest": consumption.get("consumption_digest") or "",
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "observation_cutoff": self.observation_cutoff,
            "producer": PRODUCER,
            "schema_version": SCHEMA_VERSION,
            "source_revision": self.source_revision,
            "task_id": TASK_ID,
            "tokenizer_id": self.tokenizer_id,
            "tokenizer_shared_by": TOKENIZER_SHARED_BY,
            "vector_space_id": vector_space_id,
        }
        reject_identity_contamination(reproducibility, label="reproducibility-report")

        lineage_rows: list[dict[str, Any]] = []
        for fam, rows in sorted(family_rows.items()):
            for row in rows:
                lineage_rows.append(
                    {
                        "document_number": row.get("document_number"),
                        "document_type": row.get("document_type"),
                        "entry_cid": row.get("entry_cid") or row.get("recovery_id"),
                        "family": _normalize_family(fam),
                        "legal_id": row.get("legal_id"),
                        "publication_date": row.get("publication_date"),
                        "receipt_id": row.get("receipt_id")
                        or row.get("acquisition_receipt_id"),
                        "source_cid": row.get("source_cid"),
                        "source_checksum": row.get("source_checksum")
                        or row.get("body_hash"),
                        "verification_result": row.get("verification_result"),
                        "year_month": row.get("year_month"),
                    }
                )
        lineage = {
            "authorizing_for_publication": False,
            "control_plane": False,
            "goal_id": GOAL_ID,
            "producer": PRODUCER,
            "row_count": len(lineage_rows),
            "rows": lineage_rows,
            "schema_version": "federal-register-verbose-lineage/v1",
            "separate_from_control_plane": True,
            "task_id": TASK_ID,
        }
        scrubbed_rows = []
        for row in lineage["rows"]:
            clean = {
                key: value
                for key, value in row.items()
                if not (
                    isinstance(value, str)
                    and (
                        value.startswith("/home/")
                        or value.startswith("/tmp/")
                        or value.startswith("file://")
                    )
                )
            }
            scrubbed_rows.append(clean)
        lineage["rows"] = scrubbed_rows
        reject_identity_contamination(lineage, label="lineage-report")

        return (
            ReleaseArtifact(
                relative_path=ADMISSION_REPORT_PATH,
                content=canonical_json_bytes(admission) + b"\n",
                media_type=JSON_MEDIA_TYPE,
                family="report",
                schema_id=SCHEMA_VERSION,
            ),
            ReleaseArtifact(
                relative_path=QUALITY_REPORT_PATH,
                content=canonical_json_bytes(quality) + b"\n",
                media_type=JSON_MEDIA_TYPE,
                family="report",
                schema_id=SCHEMA_VERSION,
            ),
            ReleaseArtifact(
                relative_path=REPRODUCIBILITY_REPORT_PATH,
                content=canonical_json_bytes(reproducibility) + b"\n",
                media_type=JSON_MEDIA_TYPE,
                family="report",
                schema_id=SCHEMA_VERSION,
            ),
            ReleaseArtifact(
                relative_path=LINEAGE_REPORT_PATH,
                content=canonical_json_bytes(lineage) + b"\n",
                media_type=JSON_MEDIA_TYPE,
                family="report",
                schema_id="federal-register-verbose-lineage/v1",
            ),
        )

    def _build_manifest_body(
        self,
        *,
        data_artifacts: Sequence[ReleaseArtifact],
        support_artifacts: Sequence[ReleaseArtifact],
        configs: Sequence[ViewerConfig],
        build_config_cid: str,
        release_root_cid: str,
        vector_space_id: str,
        rights: Mapping[str, Any],
        card_text: str,
        consumption: Mapping[str, Any],
    ) -> dict[str, Any]:
        inventory = [
            item.descriptor_dict()
            for item in sorted(
                (*data_artifacts, *support_artifacts),
                key=lambda art: art.relative_path,
            )
        ]
        row_counts = {
            item.relative_path: item.row_count
            for item in (*data_artifacts, *support_artifacts)
        }
        sizes = {
            item.relative_path: item.size_bytes
            for item in (*data_artifacts, *support_artifacts)
        }
        sha256_digests = {
            item.relative_path: item.sha256
            for item in (*data_artifacts, *support_artifacts)
        }
        present_families = [
            item.to_artifact_descriptor().family.value
            for item in (*data_artifacts, *support_artifacts)
        ]
        present_families.append(ArtifactFamily.MANIFEST.value)
        closure = validate_semantic_family_closure(present_families)
        rights_summary = source_scope_rights_summary(rights)
        body: dict[str, Any] = {
            "acceptance": {
                "all_advertised_configs_schema_coherent": True,
                "default_config_excludes_recovery": True,
                "every_artifact_descriptor_bound": True,
                "legacy_files_not_deleted": True,
                "semantic_family_closure": True,
                "source_rights_bound": True,
                "verbose_lineage_separate_from_control_plane": True,
                "viewer_safe_default_v2": True,
            },
            "additive_packaging": True,
            "admitted_source_ids": list(rights.get("admitted_record_ids") or ()),
            "artifacts": inventory,
            "authorizing_for_publication": False,
            "bm25": _family_binding(data_artifacts, ("bm25_documents", "bm25_postings")),
            "bm25_b": DEFAULT_BM25_B,
            "bm25_k1": DEFAULT_BM25_K1,
            "build_config_cid": build_config_cid,
            "centroids": _family_binding(data_artifacts, ("centroids",)),
            "configs": [cfg.to_dict() for cfg in configs],
            "corpus": _family_binding(data_artifacts, ("corpus",)),
            "dataset_repo_id": self.dataset_id,
            "default_config": DEFAULT_CONFIG_NAME,
            "default_excludes_recovery": True,
            "embedding_dimension": DEFAULT_EMBEDDING_DIMENSION,
            "enforce_semantic_family_closure": True,
            "extras_in_default_allowed": False,
            "goal_id": GOAL_ID,
            "graph": _family_binding(data_artifacts, ("graph_nodes", "graph_edges")),
            "graph_ontology_version": self.graph_ontology_version,
            "hf_release_schema_version": SCHEMA_VERSION,
            "lcr061_consumption_digest": consumption.get("consumption_digest") or "",
            "lcr061_family_roots": {
                "adjacency_root": consumption.get("adjacency_root") or "",
                "bm25_root": consumption.get("bm25_root") or "",
                "graph_root": consumption.get("graph_root") or "",
                "vector_root": consumption.get("vector_root") or "",
            },
            "legacy_files_deleted": False,
            "lineage_is_control_plane": False,
            "lineage_report": LINEAGE_REPORT_PATH,
            "max_rows_per_physical_shard": self.max_rows_per_shard,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "observation_cutoff": self.observation_cutoff,
            "package_version": DEFAULT_PACKAGE_VERSION,
            "producer": PRODUCER,
            "program_id": PROGRAM_ID,
            "recovery": _family_binding(data_artifacts, ("recovery", "quarantine")),
            "release_point": DEFAULT_RELEASE_POINT,
            "release_profile": RELEASE_PROFILE,
            "release_root_cid": release_root_cid,
            "rollback": rollback_map(),
            "route_bounds": route_bounds_policy(),
            "row_counts": row_counts,
            "schema_version": SCHEMA_VERSION,
            "semantic_family_closure": closure,
            "sha256_digests": sha256_digests,
            "sizes": sizes,
            "source_receipts": _family_binding(data_artifacts, ("source_receipts",)),
            "source_revision": self.source_revision,
            "source_rights_catalog_digest": rights.get("catalog_digest_sha256") or "",
            "source_rights_receipt_digest": rights["receipt_digest"],
            "source_rights_receipt_path": SOURCE_RIGHTS_RECEIPT_RELPATH,
            "source_scope_rights_summary": rights_summary,
            "task_id": TASK_ID,
            "tokenizer_id": self.tokenizer_id,
            "two_way_adjacency": _family_binding(
                data_artifacts, ("graph_adjacency_out", "graph_adjacency_in")
            ),
            "vector_locator": _family_binding(data_artifacts, ("vector_locator",)),
            "vector_space_id": vector_space_id,
            "vectors": _family_binding(data_artifacts, ("vectors",)),
            "viewer": {
                "default_split": DEFAULT_CONFIG_NAME,
                "excluded_from_default": [
                    LEGACY_CONFIG_NAME,
                    RECOVERY_CONFIG_NAME,
                    QUARANTINE_CONFIG_NAME,
                ],
                "hidden_configurations": sorted(_HIDDEN_VIEWER_CONFIGS),
            },
            "viewer_safe_default_v2": True,
        }
        try:
            require_source_rights_binding(
                body,
                receipt_digest=str(rights["receipt_digest"]),
                catalog_digest=str(rights.get("catalog_digest_sha256") or ""),
                dataset_card_text=card_text,
            )
        except SourceRightsBindingError as exc:
            raise FederalRegisterHFReleaseSafetyError(str(exc)) from exc
        return body


# ---------------------------------------------------------------------------
# Family extractors / assembly
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def consume_lcr061_family_outputs() -> dict[str, Any]:
    """Consume LCR-061 family builders as immutable fixture inputs."""

    payload = dict(consume_family_builders())
    payload["authorizing_for_publication"] = False
    payload["consumed_as_immutable_input"] = True
    payload["consumer_task_id"] = TASK_ID
    payload["producer_task_id"] = "LCR-061"
    return dict(payload)


def rows_from_bm25_index(index: Any) -> dict[str, list[dict[str, Any]]]:
    """Project a bound BM25 index into document and posting family rows."""

    if getattr(index, "document_records", None):
        documents = [dict(row) for row in index.document_records]
    else:
        documents = [
            dict(row) for shard in index.document_shards for row in shard.documents
        ]
    postings: list[dict[str, Any]] = []
    for shard in index.term_shards:
        for term in shard.terms:
            payload = term.to_dict() if hasattr(term, "to_dict") else dict(term)
            payload["entry_cid"] = payload.get("entry_cid") or getattr(term, "term", "")
            payload["legal_id"] = payload.get("legal_id") or getattr(term, "term", "")
            postings.append(payload)
    return {"bm25_documents": documents, "bm25_postings": postings}


def rows_from_vector_binding(
    binding: Any,
) -> dict[str, list[dict[str, Any]]]:
    """Project a vector binding into vector, centroid, and locator rows."""

    vectors: list[dict[str, Any]] = []
    locations = getattr(binding, "locations", {}) or {}
    if hasattr(locations, "values"):
        for location in locations.values():
            vectors.append(location.to_dict() if hasattr(location, "to_dict") else dict(location))
    centroids: list[dict[str, Any]] = []
    for row in getattr(binding, "routing_rows", ()) or ():
        payload = dict(row)
        payload.setdefault("centroid_id", payload.get("cluster_id"))
        centroids.append(payload)
    locator: list[dict[str, Any]] = []
    if getattr(binding, "entry_locator_rows", None):
        for row in binding.entry_locator_rows:
            locator.append(row.to_dict() if hasattr(row, "to_dict") else dict(row))
    else:
        if hasattr(locations, "values"):
            for location in locations.values():
                if hasattr(location, "locator_payload"):
                    locator.append(location.locator_payload())
    return {
        "centroids": centroids,
        "vector_locator": locator,
        "vectors": vectors,
    }


def rows_from_graph_projection(
    projection: Any,
) -> dict[str, list[dict[str, Any]]]:
    """Project a legal graph into node and edge family rows."""

    return {
        "graph_edges": [
            edge.to_dict() if hasattr(edge, "to_dict") else dict(edge)
            for edge in projection.edges
        ],
        "graph_nodes": [
            node.to_dict() if hasattr(node, "to_dict") else dict(node)
            for node in projection.nodes
        ],
    }


def rows_from_two_way_adjacency(
    adjacency: Any,
) -> dict[str, list[dict[str, Any]]]:
    """Project two-way adjacency pages into out/in family rows."""

    incoming = getattr(adjacency, "incoming_pages", ()) or ()
    outgoing = getattr(adjacency, "outgoing_pages", ()) or ()
    return {
        "graph_adjacency_in": [
            page.to_dict() if hasattr(page, "to_dict") else dict(page)
            for page in incoming
        ],
        "graph_adjacency_out": [
            page.to_dict() if hasattr(page, "to_dict") else dict(page)
            for page in outgoing
        ],
    }


def merge_family_rows(
    *parts: Mapping[str, Sequence[Mapping[str, Any]]] | None,
) -> dict[str, list[dict[str, Any]]]:
    """Merge family-row mappings; later parts override earlier families."""

    merged: dict[str, list[dict[str, Any]]] = {}
    for part in parts:
        if not part:
            continue
        for family, rows in part.items():
            merged[_normalize_family(family)] = [dict(row) for row in rows]
    return merged


def assemble_federal_register_hf_release(
    family_rows: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    *,
    corpus_rows: Sequence[Mapping[str, Any]] | None = None,
    bm25_index: Any | None = None,
    vector_binding: Any | None = None,
    graph_projection: Any | None = None,
    adjacency: Any | None = None,
    source_receipts: Sequence[Mapping[str, Any]] | None = None,
    recovery_rows: Sequence[Mapping[str, Any]] | None = None,
    quarantine_rows: Sequence[Mapping[str, Any]] | None = None,
    legacy_files: Mapping[str, bytes] | None = None,
    dry_run: bool = True,
    output_dir: str | Path | None = None,
    **builder_kwargs: Any,
) -> FederalRegisterHuggingFaceRelease:
    """Assemble a descriptor-complete release from family rows and/or bindings."""

    parts: list[Mapping[str, Sequence[Mapping[str, Any]]]] = []
    if family_rows:
        parts.append(family_rows)
    extras: dict[str, Sequence[Mapping[str, Any]]] = {}
    if corpus_rows is not None:
        extras["corpus"] = corpus_rows
    if source_receipts is not None:
        extras["source_receipts"] = source_receipts
    if recovery_rows is not None:
        extras["recovery"] = recovery_rows
    if quarantine_rows is not None:
        extras["quarantine"] = quarantine_rows
    if extras:
        parts.append(extras)
    if bm25_index is not None:
        parts.append(rows_from_bm25_index(bm25_index))
    if vector_binding is not None:
        parts.append(rows_from_vector_binding(vector_binding))
    if graph_projection is not None:
        parts.append(rows_from_graph_projection(graph_projection))
    if adjacency is not None:
        parts.append(rows_from_two_way_adjacency(adjacency))
    assembled = merge_family_rows(*parts) if parts else fixture_family_rows()
    return build_federal_register_hf_release(
        assembled,
        dry_run=dry_run,
        output_dir=output_dir,
        legacy_files=legacy_files,
        **builder_kwargs,
    )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def build_federal_register_hf_release(
    family_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    dataset_id: str = DEFAULT_DATASET_REPO_ID,
    dry_run: bool = True,
    output_dir: str | Path | None = None,
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    source_revision: str = DEFAULT_SOURCE_REVISION,
    model_id: str = PINNED_MODEL_ID,
    model_revision: str = PINNED_MODEL_REVISION,
    admission_summary: Mapping[str, Any] | None = None,
    preserve_existing: Sequence[str] | None = None,
    include_legacy_config: bool = True,
    include_recovery_config: bool = True,
    include_quarantine_config: bool = True,
    legacy_files: Mapping[str, bytes] | None = None,
    source_rights: Mapping[str, Any] | None = None,
    lcr061_consumption: Mapping[str, Any] | None = None,
) -> FederalRegisterHuggingFaceRelease:
    """Build a deterministic Federal Register HF release (default dry-run)."""

    builder = FederalRegisterHFReleaseBuilder(
        dataset_id=dataset_id,
        max_rows_per_shard=max_rows_per_shard,
        source_revision=source_revision,
        model_id=model_id,
        model_revision=model_revision,
        include_legacy_config=include_legacy_config,
        include_recovery_config=include_recovery_config,
        include_quarantine_config=include_quarantine_config,
    )
    return builder.build(
        family_rows,
        dry_run=dry_run,
        output_dir=output_dir,
        admission_summary=admission_summary,
        preserve_existing=preserve_existing,
        legacy_files=legacy_files,
        source_rights=source_rights,
        lcr061_consumption=lcr061_consumption,
    )


def stage_federal_register_hf_release(
    release: FederalRegisterHuggingFaceRelease,
    output_dir: str | Path,
    *,
    dry_run: bool = True,
    preserve_existing: Sequence[str] | None = None,
) -> FederalRegisterHuggingFaceRelease:
    """Stage release bytes to a local directory (additive; never deletes)."""

    _assert_no_upload_shortcut()
    if not isinstance(release, FederalRegisterHuggingFaceRelease):
        raise FederalRegisterHFReleaseError(
            "release must be FederalRegisterHuggingFaceRelease"
        )
    if type(dry_run) is not bool:
        raise FederalRegisterHFReleaseError("dry_run must be boolean")
    if dry_run:
        return release

    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    preserve = tuple(preserve_existing or ())
    pre_existing = {
        path: (root / path).read_bytes()
        for path in preserve
        if (root / path).is_file()
    }

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
            schema_type=artifact.schema_id,
            producer_id=HF_RELEASE_PRODUCER,
            config_digest=HF_RELEASE_CONFIG,
            row_count=artifact.row_count,
            config_name=artifact.config_name,
        )
        if (
            descriptor.sha256 != artifact.sha256
            or descriptor.content_cid != artifact.content_cid
            or descriptor.size_bytes != artifact.size_bytes
        ):
            raise FederalRegisterHFReleaseIntegrityError(
                f"staged file integrity mismatch: {artifact.relative_path}"
            )

    for path, original in pre_existing.items():
        current = root / path
        if not current.is_file():
            raise FederalRegisterHFReleaseSafetyError(
                f"preserved file was deleted during staging: {path}"
            )
        if current.read_bytes() != original:
            released = {item.relative_path: item.content for item in release.artifacts}
            if path not in released or released[path] != current.read_bytes():
                raise FederalRegisterHFReleaseSafetyError(
                    f"preserved file was mutated during staging: {path}"
                )
    return FederalRegisterHuggingFaceRelease(
        dataset_id=release.dataset_id,
        release_root_cid=release.release_root_cid,
        manifest_digest=release.manifest_digest,
        schema_version=release.schema_version,
        release_profile=release.release_profile,
        source_revision=release.source_revision,
        build_config_cid=release.build_config_cid,
        vector_space_id=release.vector_space_id,
        model_id=release.model_id,
        model_revision=release.model_revision,
        configs=release.configs,
        artifacts=release.artifacts,
        dry_run=False,
        staged_root=str(root),
        package_version=release.package_version,
        source_rights_receipt_digest=release.source_rights_receipt_digest,
        observation_cutoff=release.observation_cutoff,
        lcr061_consumption_digest=release.lcr061_consumption_digest,
    )


def validate_federal_register_hf_release(
    release: FederalRegisterHuggingFaceRelease,
) -> dict[str, Any]:
    """Side-effect-free validation of the full acceptance contract."""

    if not isinstance(release, FederalRegisterHuggingFaceRelease):
        raise FederalRegisterHFReleaseError(
            "release must be FederalRegisterHuggingFaceRelease"
        )

    required = {
        MANIFEST_FILENAME,
        RELEASE_METADATA_FILENAME,
        README_FILENAME,
        DATASET_CONFIGS_FILENAME,
        DATASET_INFOS_FILENAME,
        ADMISSION_REPORT_PATH,
        QUALITY_REPORT_PATH,
        REPRODUCIBILITY_REPORT_PATH,
        LINEAGE_REPORT_PATH,
    }
    paths = {item.relative_path for item in release.artifacts}
    missing = required - paths
    if missing:
        raise FederalRegisterHFReleaseIntegrityError(
            "missing required artifacts: " + ", ".join(sorted(missing))
        )

    descriptors = []
    for artifact in release.artifacts:
        desc = artifact.to_artifact_descriptor()
        payload = desc.to_dict()
        for key in (
            "relative_path",
            "media_type",
            "sha256",
            "size_bytes",
            "schema_id",
            "family",
            "row_count",
        ):
            if key not in payload:
                raise FederalRegisterHFReleaseIntegrityError(
                    f"artifact {artifact.relative_path} missing descriptor field {key}"
                )
        if not _SHA256_RE.fullmatch(artifact.sha256):
            raise FederalRegisterHFReleaseIntegrityError(
                f"invalid sha256 on {artifact.relative_path}"
            )
        if not artifact.content_cid:
            raise FederalRegisterHFReleaseIntegrityError(
                f"missing content_cid on {artifact.relative_path}"
            )
        if artifact.relative_path.startswith("/") or ".." in artifact.relative_path:
            raise FederalRegisterHFReleaseSafetyError(
                f"artifact path is unsafe: {artifact.relative_path}"
            )
        descriptors.append(desc)

    config_receipt = assert_configs_schema_coherent(release.configs)
    default_cfg = next(c for c in release.configs if c.is_default)
    for entry in default_cfg.data_files:
        path = str(entry["path"])
        if (
            "recovery" in path
            or "quarantine" in path
            or path.startswith("federal_register.")
            or path.startswith("federal_register_")
        ):
            raise FederalRegisterHFReleaseSafetyError(
                f"default config includes recovery/quarantine/legacy path: {path!r}"
            )

    for artifact in release.artifacts:
        if artifact.config_name == DEFAULT_CONFIG_NAME and artifact.family in RECOVERY_FAMILIES:
            raise FederalRegisterHFReleaseSafetyError(
                f"recovery artifact bound to default config: {artifact.relative_path}"
            )
        if artifact.relative_path.startswith("recovery/") and artifact.config_name not in {
            "",
            RECOVERY_CONFIG_NAME,
        }:
            raise FederalRegisterHFReleaseSafetyError(
                f"recovery path not bound to recovery config: {artifact.relative_path}"
            )
        if artifact.relative_path.startswith("quarantine/") and artifact.config_name not in {
            "",
            QUARANTINE_CONFIG_NAME,
        }:
            raise FederalRegisterHFReleaseSafetyError(
                f"quarantine path not bound to quarantine config: {artifact.relative_path}"
            )

    lineage = release.lineage_artifact
    if lineage is None:
        raise FederalRegisterHFReleaseIntegrityError("missing verbose lineage report")
    lineage_body = json.loads(lineage.content.decode("utf-8"))
    if lineage_body.get("control_plane") is not False:
        raise FederalRegisterHFReleaseIntegrityError(
            "lineage report must declare control_plane=false"
        )
    if not lineage_body.get("separate_from_control_plane"):
        raise FederalRegisterHFReleaseIntegrityError(
            "lineage report must declare separate_from_control_plane=true"
        )
    if LINEAGE_REPORT_PATH in CONTROL_PLANE_PATHS:
        raise FederalRegisterHFReleaseIntegrityError(
            "lineage path must not be a control-plane path"
        )

    manifest = release.manifest_dict()
    if manifest.get("lineage_is_control_plane") is not False:
        raise FederalRegisterHFReleaseIntegrityError(
            "manifest must declare lineage_is_control_plane=false"
        )
    if LINEAGE_REPORT_PATH not in str(manifest.get("lineage_report", "")):
        raise FederalRegisterHFReleaseIntegrityError(
            "manifest must point lineage_report at reports/lineage.json"
        )
    for plane_path in (
        ADMISSION_REPORT_PATH,
        QUALITY_REPORT_PATH,
        REPRODUCIBILITY_REPORT_PATH,
        MANIFEST_FILENAME,
        RELEASE_METADATA_FILENAME,
    ):
        body = json.loads(release.artifact(plane_path).content.decode("utf-8"))
        if isinstance(body, Mapping) and "rows" in body and plane_path != LINEAGE_REPORT_PATH:
            if (
                isinstance(body.get("rows"), list)
                and body["rows"]
                and any(isinstance(r, Mapping) and "source_cid" in r for r in body["rows"])
            ):
                raise FederalRegisterHFReleaseIntegrityError(
                    f"control-plane artifact {plane_path} embeds verbose lineage rows"
                )
        if isinstance(body, Mapping) and body.get("authorizing_for_publication") is True:
            raise FederalRegisterHFReleaseSafetyError(
                f"{plane_path} must not authorize publication"
            )
        _assert_no_secrets_or_absolute_paths(body, label=plane_path)

    if manifest.get("additive_packaging") is not True:
        raise FederalRegisterHFReleaseSafetyError(
            "manifest must declare additive_packaging=true"
        )
    if manifest.get("default_excludes_recovery") is not True:
        raise FederalRegisterHFReleaseSafetyError(
            "manifest must declare default_excludes_recovery=true"
        )
    if manifest.get("viewer_safe_default_v2") is not True:
        raise FederalRegisterHFReleaseSafetyError(
            "manifest must declare viewer_safe_default_v2=true"
        )
    if manifest.get("authorizing_for_publication") is not False:
        raise FederalRegisterHFReleaseSafetyError(
            "manifest must declare authorizing_for_publication=false"
        )
    if manifest.get("manifest_digest") != release.manifest_digest:
        raise FederalRegisterHFReleaseIntegrityError("manifest_digest mismatch")
    if manifest.get("release_root_cid") != release.release_root_cid:
        raise FederalRegisterHFReleaseIntegrityError("release_root_cid mismatch")
    if manifest.get("model_revision") != DEFAULT_EMBEDDING_MODEL_REVISION:
        raise FederalRegisterHFReleaseIntegrityError("manifest model_revision is not pinned")
    if manifest.get("model_id") != DEFAULT_EMBEDDING_MODEL_ID:
        raise FederalRegisterHFReleaseIntegrityError("manifest model_id is not pinned")
    if manifest.get("default_config") != DEFAULT_CONFIG_NAME:
        raise FederalRegisterHFReleaseConfigError("manifest default_config is not v2")

    missing_bindings = [
        name for name in REQUIRED_MANIFEST_BINDINGS if name not in manifest
    ]
    if missing_bindings:
        raise FederalRegisterHFReleaseIntegrityError(
            "manifest missing required bindings: " + ", ".join(missing_bindings)
        )
    for name in (
        "corpus",
        "bm25",
        "vectors",
        "centroids",
        "vector_locator",
        "graph",
        "two_way_adjacency",
        "recovery",
        "source_receipts",
    ):
        binding = manifest[name]
        if not isinstance(binding, Mapping):
            raise FederalRegisterHFReleaseIntegrityError(
                f"manifest binding {name!r} must be a mapping"
            )
        if int(binding.get("row_count") or 0) <= 0 or int(binding.get("artifact_count") or 0) <= 0:
            raise FederalRegisterHFReleaseIntegrityError(
                f"manifest binding {name!r} must include at least one artifact"
            )
        if not binding.get("sha256") or not binding.get("size_bytes"):
            raise FederalRegisterHFReleaseIntegrityError(
                f"manifest binding {name!r} must include sha256 and size_bytes"
            )

    if not isinstance(manifest.get("configs"), list) or not manifest["configs"]:
        raise FederalRegisterHFReleaseIntegrityError("manifest must bind advertised configs")
    if not isinstance(manifest.get("row_counts"), Mapping) or not manifest["row_counts"]:
        raise FederalRegisterHFReleaseIntegrityError("manifest must bind row_counts")
    if not isinstance(manifest.get("sizes"), Mapping) or not manifest["sizes"]:
        raise FederalRegisterHFReleaseIntegrityError("manifest must bind sizes")
    if not isinstance(manifest.get("sha256_digests"), Mapping) or not manifest["sha256_digests"]:
        raise FederalRegisterHFReleaseIntegrityError("manifest must bind sha256_digests")
    bounds = manifest.get("route_bounds")
    if not isinstance(bounds, Mapping):
        raise FederalRegisterHFReleaseIntegrityError("manifest must bind route_bounds")
    for key, expected in (
        ("max_rows_per_physical_shard", MAX_ROWS_PER_PHYSICAL_SHARD),
        ("max_posting_pointers_per_row", MAX_POSTING_POINTERS_PER_ROW),
        ("max_adjacency_pointers_per_row", MAX_ADJACENCY_POINTERS_PER_ROW),
        ("max_rows_per_vector_centroid", MAX_ROWS_PER_VECTOR_CENTROID),
        ("max_vector_shards_per_centroid", MAX_VECTOR_SHARDS_PER_CENTROID),
    ):
        if int(bounds.get(key) or 0) != expected:
            raise FederalRegisterHFReleaseIntegrityError(
                f"route bound {key} must be {expected}"
            )

    rollback = manifest.get("rollback")
    if not isinstance(rollback, Mapping):
        raise FederalRegisterHFReleaseIntegrityError("manifest must bind rollback")
    if rollback.get("previous_public_pin") != PREVIOUS_PUBLIC_PIN:
        raise FederalRegisterHFReleaseIntegrityError(
            "rollback previous_public_pin must be the sealed old pin"
        )
    if rollback.get("to_revision") != PREVIOUS_PUBLIC_PIN:
        raise FederalRegisterHFReleaseIntegrityError(
            "rollback to_revision must be the sealed old pin"
        )

    closure = manifest.get("semantic_family_closure")
    if not isinstance(closure, Mapping) or closure.get("closed") is not True:
        raise FederalRegisterHFReleaseIntegrityError(
            "manifest must bind a closed semantic-family set"
        )
    try:
        validate_semantic_family_closure(closure.get("present") or ())
    except SemanticFamilyClosureError as exc:
        raise FederalRegisterHFReleaseIntegrityError(str(exc)) from exc

    rights = load_source_rights_receipt()
    card = release.dataset_card_text()
    try:
        require_source_rights_binding(
            manifest,
            receipt_digest=str(rights["receipt_digest"]),
            catalog_digest=str(rights.get("catalog_digest_sha256") or ""),
            dataset_card_text=card,
        )
    except SourceRightsBindingError as exc:
        raise FederalRegisterHFReleaseSafetyError(str(exc)) from exc
    if "configs:" not in card:
        raise FederalRegisterHFReleaseConfigError("dataset card missing YAML configs")
    if DEFAULT_CONFIG_NAME not in card:
        raise FederalRegisterHFReleaseConfigError(
            "dataset card must advertise the default v2 config"
        )
    if "recovery" not in card.lower():
        raise FederalRegisterHFReleaseConfigError(
            "dataset card must document recovery separation"
        )
    if "source-scope rights" not in card.lower():
        raise FederalRegisterHFReleaseConfigError(
            "dataset card must include a source-scope rights summary"
        )
    if rights["receipt_digest"] not in card:
        raise FederalRegisterHFReleaseSafetyError(
            "dataset card must bind the source-rights receipt digest"
        )
    _assert_no_secrets_or_absolute_paths(card, label="dataset-card")

    reject_identity_contamination(manifest, label="manifest-validate")
    reject_identity_contamination(
        release.release_metadata_dict(), label="release-metadata-validate"
    )

    return {
        "acceptance": {
            "all_advertised_configs_schema_coherent": config_receipt["schema_coherent"],
            "default_config_excludes_recovery": True,
            "every_artifact_descriptor_bound": True,
            "legacy_files_not_deleted": True,
            "semantic_family_closure": True,
            "source_rights_bound": True,
            "verbose_lineage_separate_from_control_plane": True,
            "viewer_safe_default_v2": True,
        },
        "artifact_count": len(release.artifacts),
        "config_count": len(release.configs),
        "default_config": DEFAULT_CONFIG_NAME,
        "descriptor_count": len(descriptors),
        "manifest_digest": release.manifest_digest,
        "model_revision": release.model_revision,
        "release_root_cid": release.release_root_cid,
        "required_semantic_families": list(required_semantic_families()),
        "schema_version": release.schema_version,
        "source_rights_receipt_digest": rights["receipt_digest"],
        "valid": True,
    }


def releases_are_byte_identical(
    left: FederalRegisterHuggingFaceRelease,
    right: FederalRegisterHuggingFaceRelease,
) -> bool:
    """Return True when two releases have identical artifact bytes + digests."""

    if left.manifest_digest != right.manifest_digest:
        return False
    if left.release_root_cid != right.release_root_cid:
        return False
    left_map = {a.relative_path: a for a in left.artifacts}
    right_map = {a.relative_path: a for a in right.artifacts}
    if set(left_map) != set(right_map):
        return False
    for path, art in left_map.items():
        other = right_map[path]
        if art.sha256 != other.sha256 or art.content != other.content:
            return False
    return True


# ---------------------------------------------------------------------------
# Compact fixtures
# ---------------------------------------------------------------------------


def _receipt_digest(label: str) -> str:
    return hashlib.sha256(
        f"federal-register-source-receipt:{label}".encode("utf-8")
    ).hexdigest()


def fixture_source_receipts(
    rows: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Compact official-source receipts bound into the release manifest."""

    corpus = list(rows) if rows is not None else [
        example_corpus_payload(),
        example_correction_corpus_payload(),
        example_corpus_payload(
            document_number="2026-14890",
            publication_date="2026-08-10",
            document_type="notice",
        ),
    ]
    receipts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in corpus:
        year_month = str(row.get("year_month") or "").strip()
        if not year_month or year_month in seen:
            continue
        seen.add(year_month)
        payload = example_source_receipt_payload(year_month=year_month)
        payload["authorizing_for_publication"] = False
        payload["body_hash"] = _receipt_digest(f"body:{year_month}")
        payload["receipt_cid"] = _receipt_digest(f"receipt:{year_month}")
        payload["source_cid"] = str(row.get("source_cid") or payload["source_checksum"])
        receipts.append(payload)
    if not receipts:
        raise FederalRegisterHFReleaseError(
            "source receipts require at least one year_month partition"
        )
    return receipts


def fixture_legacy_files() -> dict[str, bytes]:
    """Compact legacy Federal Register baseline bytes retained additively."""

    return {
        "federal_register.parquet": b"PAR1LEGACY-FR-MUST-REMAIN\nPAR1",
        "federal_register.jsonld": b'{"@id":"legacy-federal-register"}\n',
    }


def fixture_family_rows() -> dict[str, list[dict[str, Any]]]:
    """Compact deterministic fixture rows for unit tests and sealed recipes."""

    rule = example_corpus_payload()
    correction = example_correction_corpus_payload()
    notice = example_corpus_payload(
        document_number="2026-14890",
        publication_date="2026-08-10",
        document_type="notice",
    )
    corpus = [rule, correction, notice]
    for row in corpus:
        row["admission_status"] = "admitted"
        row["verification_result"] = "verified"
        row["rights_disposition"] = "allowed"
        row["source_id"] = ADMITTED_FEDERAL_SOURCE_ID
        validate_entry_cid(row["entry_cid"])

    bm25_docs = [
        {
            "chunk_cid": row["entry_cid"],
            "document_index": index,
            "document_number": row["document_number"],
            "document_type": row["document_type"],
            "entry_cid": row["entry_cid"],
            "field_lengths": {"body": len(str(row.get("text") or "").split())},
            "legal_id": row["legal_id"],
            "publication_date": row["publication_date"],
            "year_month": row["year_month"],
        }
        for index, row in enumerate(corpus)
    ]
    bm25_postings = [
        {"chunk_cid": rule["entry_cid"], "entry_cid": rule["entry_cid"], "term": "reporting", "tf": 1},
        {"chunk_cid": correction["entry_cid"], "entry_cid": correction["entry_cid"], "term": "corrects", "tf": 1},
        {"chunk_cid": notice["entry_cid"], "entry_cid": notice["entry_cid"], "term": "notice", "tf": 1},
    ]
    vectors = [
        {
            "chunk_cid": row["entry_cid"],
            "cluster_id": 0,
            "dimension": DEFAULT_EMBEDDING_DIMENSION,
            "document_number": row["document_number"],
            "entry_cid": row["entry_cid"],
            "legal_id": row["legal_id"],
            "model_id": DEFAULT_EMBEDDING_MODEL_ID,
            "model_revision": DEFAULT_EMBEDDING_MODEL_REVISION,
            "relative_path": "data/vectors/centroid-000-part-000000.parquet",
            "row_offset": index,
        }
        for index, row in enumerate(corpus)
    ]
    centroids = [
        {
            "centroid_id": "cluster-000000",
            "cluster_id": 0,
            "dimension": DEFAULT_EMBEDDING_DIMENSION,
            "entry_cid": rule["entry_cid"],
            "relative_path": "data/vectors/centroid-000-part-000000.parquet",
            "row_count": len(vectors),
        }
    ]
    locator = [
        {
            "chunk_cid": row["entry_cid"],
            "cluster_id": 0,
            "entry_cid": row["entry_cid"],
            "global_shard_id": 0,
            "relative_path": "data/vectors/centroid-000-part-000000.parquet",
            "row_offset": index,
            "vector_key": row["entry_cid"],
        }
        for index, row in enumerate(corpus)
    ]
    graph_nodes = [
        {
            "document_number": row["document_number"],
            "entry_cid": row["entry_cid"],
            "legal_id": row["legal_id"],
            "node_cid": row["entry_cid"],
            "node_key": row["legal_id"],
            "node_type": "document",
        }
        for row in corpus
    ]
    graph_edges = [
        {
            "edge_cid": _receipt_digest("edge:corrects"),
            "edge_type": "CORRECTS",
            "source_node_cid": correction["entry_cid"],
            "target_node_cid": rule["entry_cid"],
        }
    ]
    adjacency_out = [
        {
            "direction": "out",
            "node_cid": correction["entry_cid"],
            "page_index": 0,
            "pointer_count": 1,
            "pointers": [
                {
                    "edge_cid": graph_edges[0]["edge_cid"],
                    "neighbor_node_cid": rule["entry_cid"],
                }
            ],
        }
    ]
    adjacency_in = [
        {
            "direction": "in",
            "node_cid": rule["entry_cid"],
            "page_index": 0,
            "pointer_count": 1,
            "pointers": [
                {
                    "edge_cid": graph_edges[0]["edge_cid"],
                    "neighbor_node_cid": correction["entry_cid"],
                }
            ],
        }
    ]
    recovery = [
        {
            "admission_status": "recovery",
            "authorizing_for_publication": False,
            "document_number": "2026-00000",
            "reason": "recovery-seed-excluded-from-default-v2",
            "recovery_id": _receipt_digest("recovery:fr"),
            "raw_digest": _receipt_digest("recovery-raw:fr"),
        }
    ]
    quarantine = [
        {
            "admission_status": "quarantined",
            "authorizing_for_publication": False,
            "document_number": "2026-99999",
            "reason": "unknown-or-prohibited-rights-excluded-from-default",
            "recovery_id": _receipt_digest("quarantine:fr"),
            "rights_disposition": "prohibited",
            "raw_digest": _receipt_digest("quarantine-raw:fr"),
            "source_id": DENIED_FEDERAL_SOURCE_ID,
        }
    ]
    return {
        "bm25_documents": bm25_docs,
        "bm25_postings": bm25_postings,
        "centroids": centroids,
        "corpus": corpus,
        "graph_adjacency_in": adjacency_in,
        "graph_adjacency_out": adjacency_out,
        "graph_edges": graph_edges,
        "graph_nodes": graph_nodes,
        "quarantine": quarantine,
        "recovery": recovery,
        "source_receipts": fixture_source_receipts(corpus),
        "vector_locator": locator,
        "vectors": vectors,
    }


# ---------------------------------------------------------------------------
# Candidate evidence
# ---------------------------------------------------------------------------


def build_federal_candidate_evidence(
    release: FederalRegisterHuggingFaceRelease,
    *,
    consumption: Mapping[str, Any] | None = None,
    validation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compact candidate evidence root bound to the fixture release."""

    receipt = validation or validate_federal_register_hf_release(release)
    rights = load_source_rights_receipt()
    family = dict(consumption or consume_lcr061_family_outputs())
    manifest = release.manifest_dict()
    payload = {
        "acceptance": dict(receipt["acceptance"]),
        "artifact_count": receipt["artifact_count"],
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "board_namespace": BOARD_NAMESPACE,
        "bundle": BUNDLE,
        "candidate": {
            "build_config_cid": release.build_config_cid,
            "dataset_id": release.dataset_id,
            "default_config": DEFAULT_CONFIG_NAME,
            "kind": "fixture_descriptor_complete",
            "manifest_digest": release.manifest_digest,
            "observation_cutoff": release.observation_cutoff,
            "package_version": release.package_version,
            "release_point": DEFAULT_RELEASE_POINT,
            "release_profile": release.release_profile,
            "release_root_cid": release.release_root_cid,
            "source_revision": release.source_revision,
            "vector_space_id": release.vector_space_id,
        },
        "code_version": CODE_VERSION,
        "configs": [cfg.config_name for cfg in release.configs],
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "depends_on": ["LCR-050", "LCR-061", "LCR-079"],
        "evidence_root": CANDIDATE_EVIDENCE_RELPATH,
        "fixture_only": True,
        "goal_id": GOAL_ID,
        "hub_upload": False,
        "lcr061_family_outputs": {
            "adjacency_root": family.get("adjacency_root") or "",
            "bm25_root": family.get("bm25_root") or "",
            "consumed_as_immutable_input": True,
            "consumption_digest": family.get("consumption_digest") or "",
            "graph_root": family.get("graph_root") or "",
            "producer_task_id": "LCR-061",
            "vector_root": family.get("vector_root") or "",
        },
        "legacy_baseline_end_inclusive": LEGACY_BASELINE_END_INCLUSIVE,
        "mode": "fixture",
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "proves_software_contract_only": True,
        "rollback": rollback_map(),
        "route_bounds": route_bounds_policy(),
        "schema": "ipfs_datasets_py/legal-corpora-reindex-federal-candidate@1",
        "schema_version": SCHEMA_VERSION,
        "semantic_family_closure": manifest.get("semantic_family_closure"),
        "source_rights": {
            "catalog_digest_sha256": rights.get("catalog_digest_sha256") or "",
            "receipt_digest": rights["receipt_digest"],
            "receipt_path": SOURCE_RIGHTS_RECEIPT_RELPATH,
            "unknown_or_prohibited_excluded_from_default": True,
        },
        "task_id": TASK_ID,
        "viewer_safe_default_v2": True,
    }
    payload["acceptance"]["publication_not_authorized"] = True
    payload["acceptance"]["secrets_absent"] = True
    payload["acceptance"]["old_pin_rollback_named"] = True
    payload["content_digest"] = digest_mapping(
        {key: value for key, value in payload.items() if key != "content_digest"}
    )
    reject_identity_contamination(payload, label="federal-candidate")
    _assert_no_secrets_or_absolute_paths(payload, label="federal-candidate")
    return payload


def write_federal_candidate_evidence(
    payload: Mapping[str, Any],
    *,
    path: str | Path | None = None,
) -> Path:
    """Write the sealed candidate evidence JSON (repo-relative)."""

    target = Path(path) if path is not None else _repo_root() / CANDIDATE_EVIDENCE_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        dict(payload),
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(encoded, encoding="utf-8")
    os.replace(tmp, target)
    return target


def load_federal_candidate_evidence(
    path: str | Path | None = None,
) -> dict[str, Any]:
    candidates: list[Path] = []
    if path is not None:
        candidates.append(Path(path))
    candidates.extend(
        [
            _repo_root() / CANDIDATE_EVIDENCE_RELPATH,
            Path(CANDIDATE_EVIDENCE_RELPATH),
            Path.cwd() / CANDIDATE_EVIDENCE_RELPATH,
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                raise FederalRegisterHFReleaseError(
                    "federal_candidate.json must be a JSON object"
                )
            return dict(payload)
    raise FederalRegisterHFReleaseError("federal_candidate.json is missing")


def run_hermetic_check(
    *,
    write_candidate: bool = False,
) -> dict[str, Any]:
    """Offline self-check: fixture assembly, rights, rollback, LCR-061 bind."""

    reject_hub_upload(False)
    proofs: list[str] = []
    consumption = consume_lcr061_family_outputs()
    if consumption.get("authorizing_hub_upload"):
        raise HubUploadForbiddenError("LCR-061 family consumption authorized Hub")
    proofs.append("lcr061_family_outputs_consumed")

    first = build_federal_register_hf_release(
        fixture_family_rows(),
        legacy_files=fixture_legacy_files(),
        dry_run=True,
        lcr061_consumption=consumption,
    )
    second = build_federal_register_hf_release(
        fixture_family_rows(),
        legacy_files=fixture_legacy_files(),
        dry_run=True,
        lcr061_consumption=consumption,
    )
    if not releases_are_byte_identical(first, second):
        raise FederalRegisterHFReleaseIntegrityError(
            "two-build fixture releases diverged"
        )
    proofs.append("two_build_logical_determinism")

    receipt = validate_federal_register_hf_release(first)
    if receipt["acceptance"]["source_rights_bound"] is not True:
        raise FederalRegisterHFReleaseSafetyError("source-rights not bound")
    proofs.append("source_rights_bound")
    if receipt["acceptance"]["semantic_family_closure"] is not True:
        raise FederalRegisterHFReleaseIntegrityError("semantic families not closed")
    proofs.append("semantic_family_closure")
    if first.manifest_dict()["rollback"]["previous_public_pin"] != PREVIOUS_PUBLIC_PIN:
        raise FederalRegisterHFReleaseIntegrityError("old-pin rollback missing")
    proofs.append("old_pin_rollback_named")

    evidence = build_federal_candidate_evidence(
        first,
        consumption=consumption,
        validation=receipt,
    )
    sealed = load_federal_candidate_evidence()
    comparable_keys = (
        "task_id",
        "goal_id",
        "program_id",
        "authorizing_for_publication",
        "authorizing_hub_upload",
        "fixture_only",
        "schema_version",
        "evidence_root",
    )
    for key in comparable_keys:
        if sealed.get(key) != evidence.get(key):
            raise FederalRegisterHFReleaseIntegrityError(
                f"federal_candidate.json field {key!r} drifted"
            )
    if sealed["candidate"]["manifest_digest"] != first.manifest_digest:
        raise FederalRegisterHFReleaseIntegrityError(
            "federal_candidate.json manifest_digest does not match fixture release"
        )
    if sealed["source_rights"]["receipt_digest"] != first.source_rights_receipt_digest:
        raise FederalRegisterHFReleaseIntegrityError(
            "federal_candidate.json source-rights digest drifted"
        )
    proofs.append("candidate_evidence_root_bound")
    if write_candidate:
        write_federal_candidate_evidence(evidence)
        proofs.append("candidate_evidence_written")

    payload = {
        "candidate_root": first.release_root_cid,
        "content_digest": evidence["content_digest"],
        "fixture_only": True,
        "goal_id": GOAL_ID,
        "manifest_digest": first.manifest_digest,
        "ok": True,
        "program_id": PROGRAM_ID,
        "proofs": proofs,
        "release_root_cid": first.release_root_cid,
        "schema_version": SCHEMA_VERSION,
        "source_rights_receipt_digest": first.source_rights_receipt_digest,
        "task_id": TASK_ID,
        **software_contract_flags(),
        "lcr061_family_outputs": evidence["lcr061_family_outputs"],
        "acceptance": receipt["acceptance"],
    }
    payload["check_digest"] = digest_mapping(
        {
            "proofs": proofs,
            "schema_version": SCHEMA_VERSION,
            "task_id": TASK_ID,
        }
    )
    return payload


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _dataset_infos(
    *,
    dataset_id: str,
    data_artifacts: Sequence[ReleaseArtifact],
    configs: Sequence[ViewerConfig],
) -> dict[str, Any]:
    by_config: dict[str, list[ReleaseArtifact]] = defaultdict(list)
    for art in data_artifacts:
        if art.config_name:
            by_config[art.config_name].append(art)
    for cfg in configs:
        by_config.setdefault(cfg.config_name, [])
    out_configs: dict[str, Any] = {}
    for name in sorted(by_config):
        shards = by_config[name]
        out_configs[name] = {
            "dataset_name": dataset_id,
            "features": list(_CONFIG_FEATURES.get(name, ())),
            "splits": {
                "train": {
                    "name": "train",
                    "num_bytes": sum(item.size_bytes for item in shards),
                    "num_examples": sum(item.row_count for item in shards),
                }
            },
        }
    return {
        "authorizing_for_publication": False,
        "configs": out_configs,
        "dataset_name": dataset_id,
        "schema_version": SCHEMA_VERSION,
    }


def _release_metadata_payload(
    *,
    dataset_id: str,
    release_root_cid: str,
    build_config_cid: str,
    source_revision: str,
    vector_space_id: str,
    model_id: str,
    model_revision: str,
    tokenizer_id: str,
    graph_ontology_version: str,
    determinism_seed: int,
    configs: Sequence[ViewerConfig],
    dry_run: bool,
    rights: Mapping[str, Any],
    observation_cutoff: str,
    consumption: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "additive_packaging": True,
        "authorizing_for_publication": False,
        "build_config_cid": build_config_cid,
        "configs": [cfg.config_name for cfg in configs],
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "dataset_id": dataset_id,
        "default_config": DEFAULT_CONFIG_NAME,
        "default_excludes_recovery": True,
        "determinism_seed": determinism_seed,
        "dry_run": dry_run,
        "goal_id": GOAL_ID,
        "graph_ontology_version": graph_ontology_version,
        "lcr061_consumption_digest": consumption.get("consumption_digest") or "",
        "lineage_is_control_plane": False,
        "lineage_report": LINEAGE_REPORT_PATH,
        "model_id": model_id,
        "model_revision": model_revision,
        "observation_cutoff": observation_cutoff,
        "package_version": DEFAULT_PACKAGE_VERSION,
        "producer": PRODUCER,
        "release_profile": RELEASE_PROFILE,
        "release_root_cid": release_root_cid,
        "rollback": rollback_map(),
        "route_bounds": route_bounds_policy(),
        "schema_version": SCHEMA_VERSION,
        "source_revision": source_revision,
        "source_rights_receipt_digest": rights["receipt_digest"],
        "source_rights_receipt_path": SOURCE_RIGHTS_RECEIPT_RELPATH,
        "task_id": TASK_ID,
        "tokenizer_id": tokenizer_id,
        "upload_path": None,
        "uses_hf_api_upload_file": False,
        "vector_space_id": vector_space_id,
        "viewer_safe_default_v2": True,
    }


def _compute_release_root_cid(
    *,
    dataset_id: str,
    artifacts: Sequence[ReleaseArtifact],
    build_config_cid: str,
) -> str:
    inventory = [
        {
            "content_cid": item.content_cid,
            "relative_path": item.relative_path,
            "sha256": item.sha256,
            "size_bytes": item.size_bytes,
        }
        for item in sorted(artifacts, key=lambda a: a.relative_path)
    ]
    payload = {
        "artifacts": inventory,
        "build_config_cid": build_config_cid,
        "dataset_id": dataset_id,
        "schema_version": SCHEMA_VERSION,
    }
    digest = hashlib.sha256(canonical_json_bytes(payload)).digest()
    return cid_v1_from_digest(digest)


def _assert_no_upload_shortcut() -> None:
    """Static guard: this module must never grow a Hub upload path.

    Token strings are assembled at runtime so the source does not contain
    banned import/call forms (tests scan the source text fail-closed).
    """

    source_path = Path(__file__).resolve()
    text = source_path.read_text(encoding="utf-8")
    prefix = text.split("def _assert_no_upload_shortcut", 1)[0]
    hub = "hugging" + "face_hub"
    from_hub = "from " + hub
    import_hub = "import " + hub
    hf_api_call = "Hf" + "Api("
    upload_file_call = "upload_" + "file("
    upload_folder_call = "upload_" + "folder("
    for token in (
        from_hub,
        import_hub,
        hf_api_call,
        upload_file_call,
        upload_folder_call,
    ):
        if token in prefix:
            raise FederalRegisterHFReleaseSafetyError(
                f"Hub upload surface is forbidden in federal_register_hf_release: {token!r}"
            )


__all__ = [
    "ADMISSION_REPORT_PATH",
    "AUTHORIZES_HUB_UPLOAD",
    "AUTHORIZES_PUBLICATION",
    "CANDIDATE_EVIDENCE_RELPATH",
    "CONTROL_PLANE_PATHS",
    "DATASET_CARD_TEMPLATE_RELPATH",
    "DATASET_CONFIGS_FILENAME",
    "DATASET_INFOS_FILENAME",
    "DEFAULT_CONFIG_NAME",
    "DEFAULT_DATASET_REPO_ID",
    "DEFAULT_SOURCE_REVISION",
    "GOAL_ID",
    "LEGACY_CONFIG_NAME",
    "LINEAGE_REPORT_PATH",
    "MANIFEST_FILENAME",
    "PRODUCER",
    "PROGRAM_ID",
    "QUALITY_REPORT_PATH",
    "QUARANTINE_CONFIG_NAME",
    "README_FILENAME",
    "RECOVERY_CONFIG_NAME",
    "RELEASE_METADATA_FILENAME",
    "REPRODUCIBILITY_REPORT_PATH",
    "REQUIRED_MANIFEST_BINDINGS",
    "SCHEMA_VERSION",
    "SOURCE_RIGHTS_RECEIPT_RELPATH",
    "TASK_ID",
    "FederalRegisterHFReleaseBuilder",
    "FederalRegisterHFReleaseConfigError",
    "FederalRegisterHFReleaseError",
    "FederalRegisterHFReleaseIntegrityError",
    "FederalRegisterHFReleaseSafetyError",
    "FederalRegisterHuggingFaceRelease",
    "HubUploadForbiddenError",
    "ReleaseArtifact",
    "ViewerConfig",
    "advertised_viewer_configs",
    "assemble_federal_register_hf_release",
    "assert_configs_schema_coherent",
    "build_federal_candidate_evidence",
    "build_federal_register_hf_release",
    "consume_lcr061_family_outputs",
    "fixture_family_rows",
    "fixture_legacy_files",
    "load_federal_candidate_evidence",
    "load_fixture_dataset_card",
    "load_source_rights_receipt",
    "reject_hub_upload",
    "releases_are_byte_identical",
    "render_dataset_card",
    "rollback_map",
    "route_bounds_policy",
    "run_hermetic_check",
    "stage_federal_register_hf_release",
    "validate_federal_register_hf_release",
    "write_federal_candidate_evidence",
]
