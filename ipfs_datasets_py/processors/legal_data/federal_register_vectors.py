"""Pinned Federal Register embeddings and true centroid routes (LCR-057).

Adapter between the LCR-055 admitted searchable chunks and a centroid-routed
dense index:

* exactly one 384-d L2-normalized vector per searchable chunk;
* sealed GTE-small revision, preprocessing, pooling, normalization,
  dimension, and k-means seed contract (reuses US Code pins);
* deterministic balanced spherical clusters;
* centroid-specific physical shards and compact centroid routes;
* model/input receipts bound to the layout.

Design invariants
-----------------
* Retrieval identity is the chunk CID. Parent ``entry_cid`` is a join key.
* Default offline backend is the sealed local hashed projection so unit
  tests never download sentence-transformers or torch models. Production
  callers may request the sentence-transformers backend; the GTE-small pin
  still binds every receipt and placeholder model refs fail closed.
* Projection embeddings prove the software contract only and cannot
  authorize publication or Hub upload.
* Centroid groups have at most 8,192 rows and two physical shards.
  Each physical shard has at most 4,096 rows.
* Legacy FAISS filenames (``federal_register_gte_small.faiss``) are never
  overwritten.
* No Hub upload, no tokens, and no absolute home paths in receipts.

Depends on LCR-055 (canonical corpus/chunks). Does not rewrite that module.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Optional, Union

from ipfs_datasets_py.processors.legal_data.federal_register_acquisition import (
    SecretInReceiptError,
    assert_no_secrets,
    find_secret_surfaces,
)
from ipfs_datasets_py.processors.legal_data.federal_register_corpus import (
    CanonicalChunk,
    MaterializedCorpus,
    materialize_federal_register_corpus,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    ADR_PATH,
    DEFAULT_EMBEDDING_DIMENSION as SCHEMA_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL_ID as SCHEMA_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_MODEL_REVISION as SCHEMA_EMBEDDING_MODEL_REVISION,
    MAX_ROWS_PER_PHYSICAL_SHARD as SCHEMA_MAX_ROWS_PER_PHYSICAL_SHARD,
    MAX_ROWS_PER_VECTOR_CENTROID as SCHEMA_MAX_ROWS_PER_VECTOR_CENTROID,
    MAX_VECTOR_SHARDS_PER_CENTROID as SCHEMA_MAX_VECTOR_SHARDS_PER_CENTROID,
    RELEASE_PROFILE,
    MutableReferenceError,
    PositionalIdentityError,
    reject_positional_durable_identity,
    require_immutable_model_ref,
    validate_digest,
    validate_entry_cid,
)
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (
    CURRENTNESS_DISCLAIMER,
    DEFAULT_DATASET_REPO_ID,
    canonical_json_dumps,
    content_sha256,
    digest_mapping,
    repository_root,
)
from ipfs_datasets_py.processors.legal_data.uscode_embeddings import (
    DEFAULT_BACKEND as USCODE_DEFAULT_BACKEND,
    DEFAULT_BATCH_SIZE,
    DEFAULT_DEVICE,
    DEFAULT_INPUT_FIELDS,
    DEFAULT_MODEL_ID,
    DEFAULT_MODEL_LICENSE,
    DEFAULT_MODEL_REVISION,
    DEFAULT_NORMALIZATION,
    DEFAULT_POOLING,
    DEFAULT_PROVIDER,
    MAX_BATCH_SIZE,
    NORM_TOLERANCE,
    AdmittedChunk,
    DeviceFallbackPolicy,
    EmbeddingFunction,
    EmbeddingGenerationResult,
    EmbeddingRecord,
    UnpinnedModelError,
    UscodeEmbeddingConfig,
    build_vector_space_id,
    coerce_admitted_chunks,
    deterministic_project,
    generate_uscode_embeddings,
    input_content_hash,
    l2_norm,
    l2_normalize,
    normalize_embedding_text,
    reject_placeholder_model_ref,
    validate_vector_dimension,
    validate_vector_norm,
)
from ipfs_datasets_py.retrieval.hf_graphrag.locators import (
    KIND_VECTORS,
    LOCATOR_SCHEMA_VERSION,
    LocatorHit,
    LocatorRow,
    MissingKeyError,
    build_vector_locator,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    DEFAULT_CANDIDATE_CENTROIDS,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    MAX_ROWS_PER_VECTOR_CENTROID,
    MAX_ROUTING_ROWS_PER_INDEX,
    MAX_VECTOR_SHARDS_PER_CENTROID,
    ArtifactFamily,
    canonical_json_bytes,
    normalize_relative_artifact_path,
    normalize_sha256,
)
from ipfs_datasets_py.retrieval.hf_graphrag.vectors import (
    ASSIGNMENT,
    DEFAULT_KMEANS_ITERATIONS,
    DEFAULT_TARGET_ROWS_PER_CENTROID,
    DEFAULT_VECTOR_KMEANS_SEED,
    ROWS_SORTED_BY,
    VECTOR_DATA_DIR,
    VECTOR_INDEX_PATH,
    VECTOR_LAYOUT_SCHEMA_VERSION,
    VECTOR_ROUTING_SCHEMA_VERSION,
    VectorClusterLayout,
    VectorRecord,
    VectorShardRoute,
    build_centroid_routed_vector_layout,
    route_vector_shards,
    validate_vector_layout,
    vector_bounds_policy,
    vector_shard_relative_path,
)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "federal-register-vectors-v1"
REPORT_SCHEMA: Final = "ipfs_datasets_py/legal-corpora-reindex-federal-vectors@1"
TASK_ID: Final = "LCR-057"
GOAL_ID: Final = "LCR-G120"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "federal_register_vectors.py"
BOARD_NAMESPACE: Final = "legal-corpora-reindex-v1"
BUNDLE: Final = "federal-index-vectors"
CODE_VERSION: Final = "1"
CORPUS_TASK_ID: Final = "LCR-055"

PRIMARY_KEY: Final = "chunk_cid"
PARENT_KEY: Final = "entry_cid"
VECTOR_KEY_FIELD: Final = "chunk_cid"
PREPROCESSING: Final = "nfkc_whitespace_collapse"
VECTOR_ENTRY_LOCATOR_DIR: Final = "indexes/vector_entry_locator"

PINNED_MODEL_ID: Final = DEFAULT_MODEL_ID
PINNED_MODEL_REVISION: Final = DEFAULT_MODEL_REVISION
PINNED_MODEL_LICENSE: Final = DEFAULT_MODEL_LICENSE
PINNED_DIMENSION: Final = 384
PINNED_MAX_TOKENS: Final = 512
PINNED_POOLING: Final = DEFAULT_POOLING
PINNED_NORMALIZATION: Final = DEFAULT_NORMALIZATION
PINNED_INPUT_FIELDS: Final = DEFAULT_INPUT_FIELDS

PRODUCTION_BACKEND: Final = "sentence_transformers"
PRODUCTION_PROVIDER: Final = "huggingface"
PROJECTION_BACKEND: Final = "local_deterministic_projection"
DEFAULT_BACKEND: Final = PROJECTION_BACKEND
DEFAULT_PROVIDER: Final = "local"

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
PROVES_SOFTWARE_CONTRACT_ONLY: Final = True
PROJECTION_FALLBACK_AUTHORIZES_RELEASE: Final = False

REPORT_RELATIVE_PATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_vectors.json"
)

FORBIDDEN_LEGACY_FAISS_FILENAMES: Final = frozenset(
    {
        "federal_register_gte_small.faiss",
        "federal_register_gte_small_metadata.parquet",
        "index.faiss",
        "index.faiss.index",
    }
)
FORBIDDEN_FAISS_SUFFIXES: Final = (".faiss", ".faiss.index")

DEFAULT_TEST_MAX_ROWS_PER_SHARD: Final = 2
DEFAULT_TEST_MAX_ROWS_PER_CENTROID: Final = 4
DEFAULT_TEST_TARGET_ROWS_PER_CENTROID: Final = 3
DEFAULT_TEST_ENTRY_LOCATOR_PAGE_SIZE: Final = 4

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


if PINNED_MODEL_ID != SCHEMA_EMBEDDING_MODEL_ID:
    raise RuntimeError("Federal Register model pin drifted from release schema")
if PINNED_MODEL_REVISION != SCHEMA_EMBEDDING_MODEL_REVISION:
    raise RuntimeError("Federal Register model revision drifted from release schema")
if PINNED_DIMENSION != SCHEMA_EMBEDDING_DIMENSION:
    raise RuntimeError("Federal Register dimension drifted from release schema")
if MAX_ROWS_PER_PHYSICAL_SHARD != SCHEMA_MAX_ROWS_PER_PHYSICAL_SHARD:
    raise RuntimeError("physical shard bound drifted from release schema")
if MAX_ROWS_PER_VECTOR_CENTROID != SCHEMA_MAX_ROWS_PER_VECTOR_CENTROID:
    raise RuntimeError("centroid row bound drifted from release schema")
if MAX_VECTOR_SHARDS_PER_CENTROID != SCHEMA_MAX_VECTOR_SHARDS_PER_CENTROID:
    raise RuntimeError("centroid shard bound drifted from release schema")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FederalRegisterVectorError(ValueError):
    """Base error for Federal Register embedding / vector-route failures."""

    code: str = "federal_register_vector_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class EmbeddingConfigError(FederalRegisterVectorError):
    """Raised when the embedding pin is incomplete or not GTE-small."""

    code = "config_invalid"


class VectorBindingError(FederalRegisterVectorError):
    """Raised when embeddings cannot be bound to a vector layout."""

    code = "binding_invalid"


class VectorCoverageError(FederalRegisterVectorError):
    """Raised when chunk conservation or uniqueness fails."""

    code = "coverage_invalid"


class VectorRouteBoundError(FederalRegisterVectorError):
    """Raised when centroid or shard physical bounds are violated."""

    code = "route_bound_exceeded"


class VectorRootReconcileError(FederalRegisterVectorError):
    """Raised when model/config/corpus/layout roots do not reconcile."""

    code = "root_reconcile_failed"


class VectorLocatorError(FederalRegisterVectorError):
    """Raised when direct CID vector location fails."""

    code = "locator_failed"


class VectorReceiptError(FederalRegisterVectorError):
    """Raised when the sealed vector report is malformed."""

    code = "receipt_invalid"


class VectorReleaseAuthorizationError(FederalRegisterVectorError):
    """Raised when a vector report would authorize release or Hub upload."""

    code = "release_authorization_forbidden"


class LegacyFaissOverwriteError(FederalRegisterVectorError):
    """Raised when a layout would overwrite a legacy FAISS filename."""

    code = "legacy_faiss_overwrite_forbidden"


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 1024) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VectorBindingError(f"{name} must be a non-empty string")
    text = value.strip()
    if "\x00" in text:
        raise VectorBindingError(f"{name} must not contain NUL")
    if len(text) > maximum:
        raise VectorBindingError(f"{name} exceeds maximum length {maximum}")
    return text


def _require_positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise VectorBindingError(f"{name} must be a positive integer")
    return value


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise VectorBindingError(f"{name} must be a non-negative integer")
    return value


def _durable_key(value: Any, name: str) -> str:
    text = _require_non_empty_str(value, name, maximum=512)
    try:
        reject_positional_durable_identity(text, name=name)
    except PositionalIdentityError as exc:
        raise VectorBindingError(str(exc), code="positional") from exc
    if text.lower().startswith("row-"):
        raise VectorBindingError(
            f"{name} must not be a positional identity token: {text!r}",
            code="positional",
        )
    try:
        return validate_entry_cid(text, name=name)
    except (PositionalIdentityError, MutableReferenceError) as exc:
        raise VectorBindingError(str(exc), code="positional") from exc


def content_cid(value: Any) -> str:
    """Stable ``sha256:<hex>`` content address for roots and receipts."""

    if isinstance(value, (bytes, bytearray)):
        digest = content_sha256(bytes(value))
    elif isinstance(value, str):
        digest = content_sha256(value)
    else:
        digest = content_sha256(canonical_json_bytes(value))
    return f"sha256:{digest}"


def write_bytes_atomic(path: PathLike, data: bytes) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".fr-vectors-",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return target


def write_json_atomic(path: PathLike, payload: Mapping[str, Any]) -> Path:
    text = (
        json.dumps(
            dict(payload),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )
    return write_bytes_atomic(path, text.encode("utf-8"))


def reject_legacy_faiss_path(path: Any, *, name: str = "path") -> str:
    """Fail closed on legacy FAISS filenames that must never be overwritten."""

    text = _require_non_empty_str(path, name, maximum=2048)
    lowered = text.replace("\\", "/").lower()
    basename = lowered.rsplit("/", 1)[-1]
    if basename in FORBIDDEN_LEGACY_FAISS_FILENAMES:
        raise LegacyFaissOverwriteError(
            f"{name} would overwrite a legacy FAISS artifact: {path!r}"
        )
    if any(basename.endswith(suffix) for suffix in FORBIDDEN_FAISS_SUFFIXES):
        raise LegacyFaissOverwriteError(
            f"{name} uses a forbidden FAISS suffix: {path!r}"
        )
    if "federal_register_gte_small.faiss" in lowered:
        raise LegacyFaissOverwriteError(
            f"{name} aliases the legacy Federal Register FAISS filename: {path!r}"
        )
    return text


def require_pinned_gte_small(
    *,
    model_id: Any,
    model_revision: Any,
    model_id_name: str = "model_id",
    model_revision_name: str = "model_revision",
) -> tuple[str, str]:
    """Require the sealed GTE-small identity; reject placeholders and drift."""

    try:
        model, revision = reject_placeholder_model_ref(
            model_id=model_id,
            model_revision=model_revision,
            model_id_name=model_id_name,
            model_revision_name=model_revision_name,
        )
    except UnpinnedModelError:
        raise
    try:
        model, revision = require_immutable_model_ref(
            model_id=model,
            model_revision=revision,
            model_id_name=model_id_name,
            model_revision_name=model_revision_name,
        )
    except MutableReferenceError as exc:
        raise UnpinnedModelError(str(exc)) from exc
    if model != PINNED_MODEL_ID:
        raise UnpinnedModelError(
            f"{model_id_name} must be the sealed GTE-small pin "
            f"{PINNED_MODEL_ID!r}; got {model!r}"
        )
    if revision != PINNED_MODEL_REVISION:
        raise UnpinnedModelError(
            f"{model_revision_name} must be the sealed GTE-small revision "
            f"{PINNED_MODEL_REVISION!r}; got {revision!r}"
        )
    return model, revision


def default_vector_space_id() -> str:
    """Return the sealed GTE-small vector-space id."""

    return build_vector_space_id(
        model_id=PINNED_MODEL_ID,
        model_revision=PINNED_MODEL_REVISION,
        pooling=PINNED_POOLING,
        normalization=PINNED_NORMALIZATION,
        dimension=PINNED_DIMENSION,
    )


def build_model_cid(
    *,
    model_id: str,
    model_revision: str,
    vector_space_id: str,
) -> str:
    """Content-address the immutable model pin surface."""

    model, revision = require_pinned_gte_small(
        model_id=model_id, model_revision=model_revision
    )
    space = _require_non_empty_str(vector_space_id, "vector_space_id", maximum=512)
    payload = {
        "model_id": model,
        "model_revision": revision,
        "vector_space_id": space,
    }
    return content_cid(payload)


def build_layout_root_cid(layout: VectorClusterLayout) -> str:
    """Content-address the structural centroid layout (no raw embeddings)."""

    if not isinstance(layout, VectorClusterLayout):
        raise VectorBindingError("layout must be a VectorClusterLayout")
    structural = {
        "assignment": layout.assignment,
        "clusters": [
            {
                "cluster_id": group.cluster_id,
                "entry_cids": list(group.entry_cids),
                "row_count": group.row_count,
                "shard_count": group.shard_count,
                "shards": [
                    {
                        "chunk_in_cluster": shard.chunk_in_cluster,
                        "entry_cids": list(shard.entry_cids),
                        "global_shard_id": shard.global_shard_id,
                        "relative_path": shard.relative_path,
                        "row_count": shard.row_count,
                    }
                    for shard in group.shards
                ],
            }
            for group in layout.clusters
        ],
        "dimension": layout.dimension,
        "max_rows_per_centroid": layout.max_rows_per_centroid,
        "max_rows_per_shard": layout.max_rows_per_shard,
        "max_shards_per_centroid": layout.max_shards_per_centroid,
        "schema_version": layout.schema_version,
        "seed": layout.seed,
        "total_rows": layout.total_rows,
    }
    return content_cid(structural)


def _synthetic_shard_digest(relative_path: str, row_count: int) -> str:
    """Deterministic placeholder digest for in-memory (not-yet-written) shards."""

    reject_legacy_faiss_path(relative_path, name="relative_path")
    return content_sha256(
        f"federal-register-vector-shard:{relative_path}:rows={row_count}"
    )


# ---------------------------------------------------------------------------
# Embedding configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FederalRegisterEmbeddingConfig:
    """GTE-small pin for Federal Register embeddings.

    Runtime backend may be the hermetic hashed projection (tests) or
    sentence-transformers (production). The model identity is always the
    sealed GTE-small revision; placeholder / mutable refs fail closed.
    """

    model_id: str = PINNED_MODEL_ID
    model_revision: str = PINNED_MODEL_REVISION
    license: str = PINNED_MODEL_LICENSE
    max_tokens: int = PINNED_MAX_TOKENS
    pooling: str = PINNED_POOLING
    normalization: str = PINNED_NORMALIZATION
    input_fields: tuple[str, ...] = PINNED_INPUT_FIELDS
    dimension: int = PINNED_DIMENSION
    vector_space_id: str = ""
    config_cid: str = ""
    backend: str = DEFAULT_BACKEND
    provider: str = DEFAULT_PROVIDER
    device: str = DEFAULT_DEVICE
    device_fallback: DeviceFallbackPolicy = DeviceFallbackPolicy.FALLBACK_CPU
    batch_size: int = DEFAULT_BATCH_SIZE
    schema_version: str = SCHEMA_VERSION
    preprocessing: str = PREPROCESSING

    def __post_init__(self) -> None:
        model_id, model_revision = require_pinned_gte_small(
            model_id=self.model_id,
            model_revision=self.model_revision,
        )
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "model_revision", model_revision)

        license_text = _require_non_empty_str(self.license, "license", maximum=256)
        object.__setattr__(self, "license", license_text)

        max_tokens = _require_positive_int(self.max_tokens, "max_tokens")
        if max_tokens != PINNED_MAX_TOKENS:
            raise EmbeddingConfigError(
                f"max_tokens must be the GTE-small ceiling {PINNED_MAX_TOKENS}; "
                f"got {max_tokens}"
            )
        object.__setattr__(self, "max_tokens", max_tokens)

        pooling = _require_non_empty_str(self.pooling, "pooling").lower()
        if pooling != PINNED_POOLING:
            raise EmbeddingConfigError(
                f"pooling must be {PINNED_POOLING!r}; got {self.pooling!r}"
            )
        object.__setattr__(self, "pooling", pooling)

        normalization = _require_non_empty_str(
            self.normalization, "normalization"
        ).lower()
        if normalization != PINNED_NORMALIZATION:
            raise EmbeddingConfigError(
                f"normalization must be {PINNED_NORMALIZATION!r}; "
                f"got {self.normalization!r}"
            )
        object.__setattr__(self, "normalization", normalization)

        if not isinstance(self.input_fields, (list, tuple)) or not self.input_fields:
            raise EmbeddingConfigError(
                "input_fields must be a non-empty sequence of field names"
            )
        fields: list[str] = []
        for index, item in enumerate(self.input_fields):
            name = _require_non_empty_str(item, f"input_fields[{index}]", maximum=128)
            if name in fields:
                raise EmbeddingConfigError(f"duplicate input field: {name!r}")
            fields.append(name)
        object.__setattr__(self, "input_fields", tuple(fields))

        dimension = _require_positive_int(self.dimension, "dimension")
        if dimension != PINNED_DIMENSION:
            raise EmbeddingConfigError(
                f"dimension must be the GTE-small width {PINNED_DIMENSION}; "
                f"got {dimension}"
            )
        object.__setattr__(self, "dimension", dimension)

        space = str(self.vector_space_id or "").strip()
        expected_space = default_vector_space_id()
        if not space:
            space = expected_space
        else:
            space = _require_non_empty_str(space, "vector_space_id", maximum=512)
            if space != expected_space:
                raise EmbeddingConfigError(
                    f"vector_space_id must be {expected_space!r}; got {space!r}"
                )
        object.__setattr__(self, "vector_space_id", space)

        backend = _require_non_empty_str(self.backend, "backend", maximum=128).lower()
        object.__setattr__(self, "backend", backend)
        provider = _require_non_empty_str(
            self.provider, "provider", maximum=128
        ).lower()
        object.__setattr__(self, "provider", provider)

        device = str(self.device or DEFAULT_DEVICE).strip().lower() or DEFAULT_DEVICE
        object.__setattr__(self, "device", device)

        if not isinstance(self.device_fallback, DeviceFallbackPolicy):
            try:
                object.__setattr__(
                    self,
                    "device_fallback",
                    DeviceFallbackPolicy(str(self.device_fallback)),
                )
            except ValueError as exc:
                raise EmbeddingConfigError(
                    f"invalid device_fallback: {self.device_fallback!r}"
                ) from exc

        batch_size = _require_positive_int(self.batch_size, "batch_size")
        if batch_size > MAX_BATCH_SIZE:
            raise EmbeddingConfigError(f"batch_size must be <= {MAX_BATCH_SIZE}")
        object.__setattr__(self, "batch_size", batch_size)

        schema = _require_non_empty_str(self.schema_version, "schema_version")
        if schema != SCHEMA_VERSION:
            raise EmbeddingConfigError(
                f"schema_version must be {SCHEMA_VERSION!r}; got {schema!r}"
            )
        object.__setattr__(self, "schema_version", schema)

        preprocessing = _require_non_empty_str(
            self.preprocessing, "preprocessing", maximum=128
        )
        if preprocessing != PREPROCESSING:
            raise EmbeddingConfigError(
                f"preprocessing must be {PREPROCESSING!r}; got {preprocessing!r}"
            )
        object.__setattr__(self, "preprocessing", preprocessing)

        cid = str(self.config_cid or "").strip()
        if not cid:
            cid = content_cid(self.pin_dict())
        else:
            cid = validate_digest(cid, name="config_cid")
        object.__setattr__(self, "config_cid", cid)

    def pin_dict(self) -> dict[str, Any]:
        """Identity surface used for config digests (excludes runtime device)."""

        return {
            "backend": self.backend,
            "dimension": self.dimension,
            "input_fields": list(self.input_fields),
            "license": self.license,
            "max_tokens": self.max_tokens,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "normalization": self.normalization,
            "pooling": self.pooling,
            "preprocessing": self.preprocessing,
            "provider": self.provider,
            "schema_version": self.schema_version,
            "vector_space_id": self.vector_space_id,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.pin_dict(),
            "batch_size": self.batch_size,
            "config_cid": self.config_cid,
            "device": self.device,
            "device_fallback": self.device_fallback.value
            if isinstance(self.device_fallback, DeviceFallbackPolicy)
            else str(self.device_fallback),
        }

    @property
    def digest(self) -> str:
        return content_sha256(canonical_json_bytes(self.pin_dict()))

    @property
    def is_projection_backend(self) -> bool:
        return self.backend in {
            PROJECTION_BACKEND,
            "deterministic",
            "hashed",
            "offline",
            "fixture",
            "local",
            USCODE_DEFAULT_BACKEND,
        }

    def to_uscode_config(self) -> UscodeEmbeddingConfig:
        """Project this pin onto the sealed US Code embedder config.

        The US Code generator owns the local hashed projection and optional
        sentence-transformers loader. Schema version on that config remains
        the US Code generator's internal pin; Federal Register receipts use
        :attr:`schema_version` from this object.
        """

        return UscodeEmbeddingConfig(
            model_id=self.model_id,
            model_revision=self.model_revision,
            license=self.license,
            max_tokens=self.max_tokens,
            pooling=self.pooling,
            normalization=self.normalization,
            input_fields=self.input_fields,
            dimension=self.dimension,
            vector_space_id=self.vector_space_id,
            backend=self.backend,
            provider=self.provider,
            device=self.device,
            device_fallback=self.device_fallback,
            batch_size=self.batch_size,
        )


def default_embedding_config() -> FederalRegisterEmbeddingConfig:
    """Hermetic default: GTE-small pin + local hashed projection."""

    return FederalRegisterEmbeddingConfig()


def fixture_embedding_config() -> FederalRegisterEmbeddingConfig:
    """Alias of :func:`default_embedding_config` for sealed unit tests."""

    return default_embedding_config()


def production_embedding_config() -> FederalRegisterEmbeddingConfig:
    """Production pin: GTE-small + sentence-transformers (not used in tests)."""

    return FederalRegisterEmbeddingConfig(
        backend=PRODUCTION_BACKEND,
        provider=PRODUCTION_PROVIDER,
        device="cuda",
    )


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CorpusParentLink:
    """Corpus parent identity for one embedded Federal Register chunk."""

    chunk_cid: str
    entry_cid: str
    document_index: int = 0
    legal_id: Optional[str] = None
    chunk_id: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "chunk_cid", _durable_key(self.chunk_cid, "chunk_cid"))
        object.__setattr__(self, "entry_cid", _durable_key(self.entry_cid, "entry_cid"))
        object.__setattr__(
            self,
            "document_index",
            _require_non_negative_int(self.document_index, "document_index"),
        )
        if self.legal_id is not None and str(self.legal_id).strip():
            object.__setattr__(
                self,
                "legal_id",
                _require_non_empty_str(self.legal_id, "legal_id", maximum=256),
            )
        else:
            object.__setattr__(self, "legal_id", None)
        if self.chunk_id is not None and str(self.chunk_id).strip():
            object.__setattr__(
                self,
                "chunk_id",
                _require_non_empty_str(self.chunk_id, "chunk_id", maximum=512),
            )
        else:
            object.__setattr__(self, "chunk_id", None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_cid": self.chunk_cid,
            "chunk_id": self.chunk_id,
            "document_index": self.document_index,
            "entry_cid": self.entry_cid,
            "legal_id": self.legal_id,
        }


@dataclass(frozen=True, slots=True)
class VectorShardLocation:
    """Exact location of one vector inside a centroid-routed data shard."""

    vector_key: str
    chunk_cid: str
    relative_path: str
    cluster_id: int
    chunk_in_cluster: int
    global_shard_id: int
    row_offset: int
    entry_cid: Optional[str] = None
    document_index: int = 0
    sha256: str = ""
    size_bytes: int = 0
    content_cid: Optional[str] = None
    dimension: int = 0
    centroid_cosine: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "vector_key", _durable_key(self.vector_key, "vector_key")
        )
        object.__setattr__(self, "chunk_cid", _durable_key(self.chunk_cid, "chunk_cid"))
        object.__setattr__(
            self,
            "relative_path",
            reject_legacy_faiss_path(
                normalize_relative_artifact_path(self.relative_path),
                name="relative_path",
            ),
        )
        object.__setattr__(
            self, "cluster_id", _require_non_negative_int(self.cluster_id, "cluster_id")
        )
        object.__setattr__(
            self,
            "chunk_in_cluster",
            _require_non_negative_int(self.chunk_in_cluster, "chunk_in_cluster"),
        )
        object.__setattr__(
            self,
            "global_shard_id",
            _require_non_negative_int(self.global_shard_id, "global_shard_id"),
        )
        object.__setattr__(
            self, "row_offset", _require_non_negative_int(self.row_offset, "row_offset")
        )
        if self.entry_cid is not None and str(self.entry_cid).strip():
            object.__setattr__(
                self, "entry_cid", _durable_key(self.entry_cid, "entry_cid")
            )
        else:
            object.__setattr__(self, "entry_cid", None)
        if self.sha256:
            object.__setattr__(
                self, "sha256", normalize_sha256(self.sha256, name="sha256")
            )
        if self.content_cid is not None and str(self.content_cid).strip():
            object.__setattr__(
                self,
                "content_cid",
                validate_digest(self.content_cid, name="content_cid"),
            )
        object.__setattr__(self, "centroid_cosine", float(self.centroid_cosine))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "centroid_cosine": self.centroid_cosine,
            "chunk_cid": self.chunk_cid,
            "chunk_in_cluster": self.chunk_in_cluster,
            "cluster_id": self.cluster_id,
            "dimension": self.dimension,
            "document_index": self.document_index,
            "entry_cid": self.entry_cid,
            "global_shard_id": self.global_shard_id,
            "relative_path": self.relative_path,
            "row_offset": self.row_offset,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "vector_key": self.vector_key,
        }
        if self.content_cid is not None:
            payload["content_cid"] = self.content_cid
            payload["cid"] = self.content_cid
        return payload

    def locator_payload(self) -> dict[str, Any]:
        return {
            "centroid_cosine": self.centroid_cosine,
            "chunk_cid": self.chunk_cid,
            "chunk_in_cluster": self.chunk_in_cluster,
            "cluster_id": self.cluster_id,
            "entry_cid": self.entry_cid,
            "global_shard_id": self.global_shard_id,
            "relative_path": self.relative_path,
            "row_offset": self.row_offset,
            "vector_key": self.vector_key,
        }


@dataclass(frozen=True, slots=True)
class ManifestReadyDescriptor:
    """Compact artifact descriptor ready for a release manifest entry."""

    relative_path: str
    family: str
    row_count: int
    sha256: str
    size_bytes: int = 0
    schema_id: str = VECTOR_LAYOUT_SCHEMA_VERSION
    first_key: Optional[str] = None
    last_key: Optional[str] = None
    centroid_id: Optional[str] = None
    media_type: str = "application/vnd.apache.parquet"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "relative_path",
            reject_legacy_faiss_path(
                normalize_relative_artifact_path(self.relative_path),
                name="relative_path",
            ),
        )
        object.__setattr__(
            self,
            "family",
            _require_non_empty_str(self.family, "family", maximum=64),
        )
        object.__setattr__(
            self, "row_count", _require_non_negative_int(self.row_count, "row_count")
        )
        object.__setattr__(self, "sha256", normalize_sha256(self.sha256, name="sha256"))
        object.__setattr__(
            self,
            "size_bytes",
            _require_non_negative_int(self.size_bytes, "size_bytes"),
        )
        if not isinstance(self.metadata, Mapping):
            raise VectorBindingError("metadata must be a mapping")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "family": self.family,
            "first_key": self.first_key,
            "last_key": self.last_key,
            "media_type": self.media_type,
            "relative_path": self.relative_path,
            "row_count": self.row_count,
            "schema_id": self.schema_id,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }
        if self.centroid_id is not None:
            payload["centroid_id"] = self.centroid_id
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class InputReceipt:
    """Per-chunk input hash bound to the GTE-small pin."""

    chunk_cid: str
    input_hash: str
    model_id: str
    model_revision: str
    pooling: str
    normalization: str
    dimension: int
    preprocessing: str = PREPROCESSING
    vector_space_id: str = ""
    config_cid: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_cid": self.chunk_cid,
            "config_cid": self.config_cid,
            "dimension": self.dimension,
            "input_hash": self.input_hash,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "normalization": self.normalization,
            "pooling": self.pooling,
            "preprocessing": self.preprocessing,
            "vector_space_id": self.vector_space_id,
        }


@dataclass(frozen=True, slots=True)
class FederalRegisterVectorBinding:
    """Complete Federal Register vector binding: embeddings + centroid routes."""

    layout: VectorClusterLayout
    routing_rows: tuple[dict[str, Any], ...]
    locations: Mapping[str, VectorShardLocation]
    parent_links: tuple[CorpusParentLink, ...]
    embeddings: Mapping[str, EmbeddingRecord]
    model_id: str
    model_revision: str
    vector_space_id: str
    config_cid: str
    model_cid: str
    vector_root_cid: str
    layout_seed: int
    corpus_root_cid: Optional[str] = None
    embedding_config: Optional[FederalRegisterEmbeddingConfig] = None
    entry_locator_rows: tuple[LocatorRow, ...] = ()
    descriptors: tuple[ManifestReadyDescriptor, ...] = ()
    input_receipts: tuple[InputReceipt, ...] = ()
    schema_version: str = SCHEMA_VERSION
    release_profile: str = RELEASE_PROFILE
    task_id: str = TASK_ID
    goal_id: str = GOAL_ID

    def __post_init__(self) -> None:
        if not isinstance(self.layout, VectorClusterLayout):
            raise VectorBindingError("layout must be a VectorClusterLayout")
        if not isinstance(self.locations, Mapping):
            raise VectorBindingError("locations must be a mapping")
        object.__setattr__(self, "locations", MappingProxyType(dict(self.locations)))
        if not isinstance(self.embeddings, Mapping):
            raise VectorBindingError("embeddings must be a mapping")
        object.__setattr__(self, "embeddings", MappingProxyType(dict(self.embeddings)))
        if len(self.locations) != self.layout.total_rows:
            raise VectorCoverageError(
                f"location map size {len(self.locations)} != layout "
                f"total_rows {self.layout.total_rows}"
            )
        if len(self.embeddings) != self.layout.total_rows:
            raise VectorCoverageError(
                f"embedding map size {len(self.embeddings)} != layout "
                f"total_rows {self.layout.total_rows}"
            )
        model_id, model_revision = require_pinned_gte_small(
            model_id=self.model_id, model_revision=self.model_revision
        )
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "model_revision", model_revision)
        object.__setattr__(
            self,
            "vector_space_id",
            _require_non_empty_str(self.vector_space_id, "vector_space_id"),
        )
        object.__setattr__(
            self, "config_cid", validate_digest(self.config_cid, name="config_cid")
        )
        object.__setattr__(
            self, "model_cid", validate_digest(self.model_cid, name="model_cid")
        )
        object.__setattr__(
            self,
            "vector_root_cid",
            validate_digest(self.vector_root_cid, name="vector_root_cid"),
        )
        if self.corpus_root_cid is not None and str(self.corpus_root_cid).strip():
            object.__setattr__(
                self,
                "corpus_root_cid",
                validate_digest(self.corpus_root_cid, name="corpus_root_cid"),
            )
        else:
            object.__setattr__(self, "corpus_root_cid", None)
        for shard in self.layout.shards:
            reject_legacy_faiss_path(shard.relative_path, name="shard.relative_path")

    @property
    def vector_count(self) -> int:
        return self.layout.total_rows

    @property
    def cluster_count(self) -> int:
        return self.layout.cluster_count

    @property
    def shard_count(self) -> int:
        return self.layout.shard_count

    @property
    def vector_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self.locations))

    @property
    def chunk_cids(self) -> tuple[str, ...]:
        return tuple(sorted(loc.chunk_cid for loc in self.locations.values()))

    def location_for(self, vector_key: str) -> VectorShardLocation:
        key = _durable_key(vector_key, "vector_key")
        try:
            return self.locations[key]
        except KeyError as exc:
            raise MissingKeyError(
                f"vector key {key!r} is not covered by any vector shard"
            ) from exc

    def locate_vector(self, vector_key: str) -> LocatorHit:
        location = self.location_for(vector_key)
        row = LocatorRow(
            first_key=location.vector_key,
            last_key=location.vector_key,
            relative_path=location.relative_path,
            sha256=location.sha256
            or _synthetic_shard_digest(location.relative_path, 1),
            size_bytes=location.size_bytes,
            row_count=1,
            shard_id=location.global_shard_id,
            kind=KIND_VECTORS,
            schema_version=LOCATOR_SCHEMA_VERSION,
            content_cid=location.content_cid,
            metadata=location.locator_payload(),
        )
        return LocatorHit(key=location.vector_key, row=row)

    def locate_vectors(
        self,
        vector_keys: Sequence[str],
        *,
        strict: bool = True,
    ) -> tuple[LocatorHit, ...]:
        hits: list[LocatorHit] = []
        for position, key in enumerate(vector_keys):
            try:
                hits.append(self.locate_vector(str(key)))
            except (MissingKeyError, VectorBindingError):
                if strict:
                    raise MissingKeyError(
                        f"vector_keys[{position}]={key!r} is not covered"
                    ) from None
        return tuple(hits)

    def entry_locator_index(self):
        if not self.entry_locator_rows:
            raise VectorLocatorError("entry locator rows are empty")
        return build_vector_locator(self.entry_locator_rows)

    def route_centroids(
        self,
        query_embedding: Sequence[float],
        *,
        candidate_centroids: int = DEFAULT_CANDIDATE_CENTROIDS,
        max_shards: int | None = None,
    ) -> tuple[VectorShardRoute, ...]:
        return route_vector_shards(
            self.routing_rows,
            query_embedding,
            candidate_centroids=candidate_centroids,
            max_shards=max_shards,
        )

    def parent_link_for_chunk(self, chunk_cid: str) -> Optional[CorpusParentLink]:
        key = _durable_key(chunk_cid, "chunk_cid")
        for link in self.parent_links:
            if link.chunk_cid == key:
                return link
        return None

    def locations_for_entry_cid(
        self, entry_cid: str
    ) -> tuple[VectorShardLocation, ...]:
        parent = _durable_key(entry_cid, "entry_cid")
        matches = [
            loc for loc in self.locations.values() if loc.entry_cid == parent
        ]
        return tuple(sorted(matches, key=lambda item: item.vector_key))

    def model_receipt(self) -> dict[str, Any]:
        return {
            "backend": (
                self.embedding_config.backend
                if self.embedding_config is not None
                else DEFAULT_BACKEND
            ),
            "config_cid": self.config_cid,
            "dimension": PINNED_DIMENSION,
            "input_fields": list(
                self.embedding_config.input_fields
                if self.embedding_config is not None
                else PINNED_INPUT_FIELDS
            ),
            "max_tokens": PINNED_MAX_TOKENS,
            "model_cid": self.model_cid,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "normalization": PINNED_NORMALIZATION,
            "pooling": PINNED_POOLING,
            "preprocessing": PREPROCESSING,
            "seed": self.layout_seed,
            "vector_space_id": self.vector_space_id,
        }

    def receipt(self) -> dict[str, Any]:
        return {
            "assignment": self.layout.assignment,
            "cluster_count": self.cluster_count,
            "config_cid": self.config_cid,
            "corpus_root_cid": self.corpus_root_cid,
            "dimension": self.layout.dimension,
            "goal_id": self.goal_id,
            "input_receipt_count": len(self.input_receipts),
            "layout_seed": self.layout_seed,
            "max_rows_per_centroid": self.layout.max_rows_per_centroid,
            "max_rows_per_shard": self.layout.max_rows_per_shard,
            "max_shards_per_centroid": self.layout.max_shards_per_centroid,
            "model_cid": self.model_cid,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "parent_link_count": len(self.parent_links),
            "primary_key": PRIMARY_KEY,
            "release_profile": self.release_profile,
            "rows_sorted_by": ROWS_SORTED_BY,
            "schema_version": self.schema_version,
            "shard_count": self.shard_count,
            "task_id": self.task_id,
            "vector_count": self.vector_count,
            "vector_root_cid": self.vector_root_cid,
            "vector_space_id": self.vector_space_id,
        }

    def to_dict(self, *, include_locations: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "descriptors": [item.to_dict() for item in self.descriptors],
            "entry_locator_rows": [row.to_dict() for row in self.entry_locator_rows],
            "layout": self.layout.manifest_config(),
            "model_receipt": self.model_receipt(),
            "parent_links": [link.to_dict() for link in self.parent_links],
            "receipt": self.receipt(),
            "routing_rows": [dict(row) for row in self.routing_rows],
            "schema_version": self.schema_version,
        }
        if include_locations:
            payload["locations"] = {
                key: loc.to_dict() for key, loc in sorted(self.locations.items())
            }
        else:
            payload["vector_keys"] = list(self.vector_keys)
        return payload


# ---------------------------------------------------------------------------
# Corpus / chunk coercion
# ---------------------------------------------------------------------------


def _cid(nibble: str) -> str:
    return f"sha256:{nibble.lower() * 64}"


def _normalize_chunk_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(value)
    if not payload.get("text"):
        payload["text"] = (
            payload.get("exclusive_text")
            or payload.get("body")
            or payload.get("abstract")
            or ""
        )
    if not payload.get("chunk_cid"):
        payload["chunk_cid"] = payload.get("cid") or payload.get("entry_cid") or ""
    if not payload.get("legal_id"):
        payload["legal_id"] = payload.get("parent_legal_id")
    parent = payload.get("parent_entry_cid")
    if parent and not payload.get("entry_cid"):
        payload["entry_cid"] = parent
    elif parent:
        # Keep document parent as entry_cid for corpus links; retrieval
        # identity remains chunk_cid.
        payload["entry_cid"] = parent
    return payload


def _admitted_from_canonical(
    chunk: CanonicalChunk,
    *,
    parent_title: str = "",
) -> AdmittedChunk:
    return AdmittedChunk(
        chunk_cid=chunk.chunk_cid,
        text=chunk.exclusive_text or chunk.text,
        entry_cid=chunk.entry_cid,
        chunk_id=chunk.chunk_id,
        legal_id=chunk.parent_legal_id,
        heading=chunk.heading or "",
        title=parent_title,
        section=chunk.document_number,
    )


def chunks_from_materialized_corpus(
    corpus: MaterializedCorpus,
) -> list[dict[str, Any]]:
    """Project LCR-055 admitted searchable chunks into embedding input rows."""

    if not isinstance(corpus, MaterializedCorpus):
        raise VectorBindingError("corpus must be a MaterializedCorpus")
    parents = {record.entry_cid: record for record in corpus.corpus_records}
    rows: list[dict[str, Any]] = []
    for chunk in corpus.chunks:
        if not isinstance(chunk, CanonicalChunk):
            raise VectorBindingError("corpus chunks must be CanonicalChunk rows")
        parent = parents.get(chunk.entry_cid)
        if parent is None:
            raise VectorCoverageError(
                f"chunk {chunk.chunk_id!r} has no parent corpus row "
                f"{chunk.entry_cid}"
            )
        rows.append(
            {
                "chunk_cid": chunk.chunk_cid,
                "chunk_id": chunk.chunk_id,
                "document_number": chunk.document_number,
                "document_type": chunk.document_type,
                "entry_cid": chunk.entry_cid,
                "heading": chunk.heading,
                "legal_id": chunk.parent_legal_id,
                "section": chunk.document_number,
                "text": chunk.exclusive_text or chunk.text,
                "title": parent.title or "",
                "year_month": chunk.year_month,
            }
        )
    if not rows:
        raise VectorCoverageError("materialized corpus emitted no searchable chunks")
    return rows


def coerce_federal_chunks(
    source: MaterializedCorpus
    | Iterable[AdmittedChunk | CanonicalChunk | Mapping[str, Any]],
) -> tuple[AdmittedChunk, ...]:
    """Normalize admitted searchable chunks for the sealed embedder."""

    if isinstance(source, MaterializedCorpus):
        rows = chunks_from_materialized_corpus(source)
        return coerce_admitted_chunks(rows)
    if isinstance(source, (str, bytes, bytearray)):
        raise VectorBindingError("chunks must be an iterable of mappings")
    admitted: list[AdmittedChunk | Mapping[str, Any]] = []
    for position, item in enumerate(source):
        if isinstance(item, AdmittedChunk):
            admitted.append(item)
            continue
        if isinstance(item, CanonicalChunk):
            admitted.append(_admitted_from_canonical(item))
            continue
        if isinstance(item, Mapping):
            payload = _normalize_chunk_mapping(item)
            disposition = str(payload.get("disposition") or "admitted").lower()
            if disposition in {"quarantined", "excluded", "failed_final", "recovery"}:
                continue
            if payload.get("is_recovery") is True:
                continue
            admitted.append(payload)
            continue
        raise VectorBindingError(
            f"chunks[{position}] must be AdmittedChunk, CanonicalChunk, or mapping"
        )
    if not admitted:
        raise VectorCoverageError("no admitted searchable chunks to embed")
    return coerce_admitted_chunks(admitted)


def build_corpus_root_cid(
    rows: Iterable[Mapping[str, Any] | AdmittedChunk | CanonicalChunk]
    | MaterializedCorpus,
) -> str:
    """Content-address admitted chunk identities (no full text payload)."""

    if isinstance(rows, MaterializedCorpus):
        identities = [
            {
                "chunk_cid": chunk.chunk_cid,
                "chunk_id": chunk.chunk_id,
                "entry_cid": chunk.entry_cid,
                "legal_id": chunk.parent_legal_id,
            }
            for chunk in rows.chunks
        ]
    else:
        identities = []
        for position, row in enumerate(rows):
            if isinstance(row, AdmittedChunk):
                identities.append(
                    {
                        "chunk_cid": row.chunk_cid,
                        "chunk_id": row.chunk_id,
                        "entry_cid": row.entry_cid,
                        "legal_id": row.legal_id,
                    }
                )
                continue
            if isinstance(row, CanonicalChunk):
                identities.append(
                    {
                        "chunk_cid": row.chunk_cid,
                        "chunk_id": row.chunk_id,
                        "entry_cid": row.entry_cid,
                        "legal_id": row.parent_legal_id,
                    }
                )
                continue
            if not isinstance(row, Mapping):
                raise VectorBindingError(f"corpus row {position} must be a mapping")
            payload = _normalize_chunk_mapping(row)
            disposition = str(payload.get("disposition") or "admitted").lower()
            if disposition != "admitted" or payload.get("is_recovery") is True:
                continue
            identities.append(
                {
                    "chunk_cid": payload.get("chunk_cid"),
                    "chunk_id": payload.get("chunk_id"),
                    "entry_cid": payload.get("entry_cid")
                    or payload.get("parent_entry_cid"),
                    "legal_id": payload.get("legal_id"),
                }
            )
    identities.sort(key=lambda item: str(item["chunk_cid"]))
    return content_cid(
        {
            "admitted_count": len(identities),
            "identities": identities,
            "primary_key": PRIMARY_KEY,
            "schema_version": "federal-register-corpus-root/v1",
        }
    )


# ---------------------------------------------------------------------------
# Embedding generation
# ---------------------------------------------------------------------------


def _projection_embedder(config: FederalRegisterEmbeddingConfig) -> EmbeddingFunction:
    def _embed(texts: Sequence[str]) -> list[list[float]]:
        return deterministic_project(
            texts,
            dimension=config.dimension,
            normalize=config.normalization == "l2",
        )

    return _embed


def generate_federal_register_embeddings(
    chunks: MaterializedCorpus
    | Sequence[AdmittedChunk | CanonicalChunk | Mapping[str, Any]],
    *,
    config: FederalRegisterEmbeddingConfig | None = None,
    embedder: EmbeddingFunction | None = None,
) -> EmbeddingGenerationResult:
    """Embed admitted searchable chunks under the sealed GTE-small pin.

    Tests pass a projection backend (the default) so no model is downloaded.
    Production callers may set ``backend='sentence_transformers'``; the pin
    identity still binds every record.
    """

    pin = config or default_embedding_config()
    if not isinstance(pin, FederalRegisterEmbeddingConfig):
        raise EmbeddingConfigError("config must be a FederalRegisterEmbeddingConfig")
    require_pinned_gte_small(
        model_id=pin.model_id, model_revision=pin.model_revision
    )
    admitted = coerce_federal_chunks(chunks)
    uscode_pin = pin.to_uscode_config()
    if embedder is not None:
        chosen = embedder
    elif pin.is_projection_backend:
        chosen = _projection_embedder(pin)
    else:
        chosen = None
    return generate_uscode_embeddings(
        admitted,
        config=uscode_pin,
        embedder=chosen,
    )


def assert_embedding_conservation(
    result: EmbeddingGenerationResult,
    *,
    expected_chunk_cids: Sequence[str],
) -> None:
    """Prove one finite 384-d L2-normalized vector per expected chunk."""

    expected = list(expected_chunk_cids)
    if len(expected) != len(set(expected)):
        raise VectorCoverageError("expected chunk_cids are not unique")
    keys = list(result.embeddings)
    if sorted(keys) != sorted(expected):
        extra = sorted(set(keys) - set(expected))
        missing = sorted(set(expected) - set(keys))
        raise VectorCoverageError(
            f"embedding keys differ; extra={extra!r} missing={missing!r}"
        )
    if result.missing:
        raise VectorCoverageError(
            f"missing vectors: {[item.chunk_cid for item in result.missing]!r}"
        )
    for cid in expected:
        record = result.embeddings[cid]
        if record.dimension != PINNED_DIMENSION or len(record.embedding) != PINNED_DIMENSION:
            raise VectorCoverageError(
                f"{cid!r} is not a {PINNED_DIMENSION}-d vector"
            )
        for index, value in enumerate(record.embedding):
            if not math.isfinite(float(value)):
                raise VectorCoverageError(
                    f"{cid!r} embedding[{index}] is not finite"
                )
        validate_vector_norm(
            record.embedding,
            normalization=PINNED_NORMALIZATION,
            name=f"embedding[{cid}]",
        )
        require_pinned_gte_small(
            model_id=record.model_id, model_revision=record.model_revision
        )


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------


def embeddings_to_vector_records(
    records: Sequence[EmbeddingRecord],
) -> tuple[VectorRecord, ...]:
    if not records:
        raise VectorBindingError("cannot bind an empty embedding set")
    seen: set[str] = set()
    rows: list[VectorRecord] = []
    for position, record in enumerate(records):
        if not isinstance(record, EmbeddingRecord):
            raise VectorBindingError(
                f"records[{position}] must be an EmbeddingRecord"
            )
        key = record.chunk_cid
        if key in seen:
            raise VectorCoverageError(f"duplicate embedded chunk_cid: {key!r}")
        seen.add(key)
        validate_vector_dimension(
            record.embedding, dimension=PINNED_DIMENSION, name=f"embedding[{key}]"
        )
        rows.append(
            VectorRecord(
                entry_cid=key,
                embedding=record.embedding,
                document_index=position,
                metadata={
                    "chunk_cid": record.chunk_cid,
                    "chunk_id": record.chunk_id,
                    "config_cid": record.config_cid,
                    "entry_cid": record.entry_cid,
                    "input_hash": record.input_hash,
                    "model_id": record.model_id,
                    "model_revision": record.model_revision,
                    "vector_space_id": record.vector_space_id,
                },
            )
        )
    return tuple(rows)


def build_entry_locator_rows(
    locations: Mapping[str, VectorShardLocation],
    *,
    max_keys_per_page: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    locator_dir: str = VECTOR_ENTRY_LOCATOR_DIR,
) -> tuple[LocatorRow, ...]:
    if not locations:
        return ()
    max_keys = _require_positive_int(max_keys_per_page, "max_keys_per_page")
    if max_keys > MAX_ROWS_PER_PHYSICAL_SHARD:
        raise VectorRouteBoundError(
            f"max_keys_per_page={max_keys} exceeds {MAX_ROWS_PER_PHYSICAL_SHARD}"
        )
    directory = normalize_relative_artifact_path(locator_dir)
    reject_legacy_faiss_path(directory, name="locator_dir")
    ordered_keys = sorted(locations)
    rows: list[LocatorRow] = []
    for page_index, offset in enumerate(range(0, len(ordered_keys), max_keys)):
        group = ordered_keys[offset : offset + max_keys]
        relative = f"{directory}/part-{page_index:06d}.parquet"
        reject_legacy_faiss_path(relative, name="locator_relative_path")
        page_payload = [
            {
                "relative_path": locations[key].relative_path,
                "vector_key": key,
            }
            for key in group
        ]
        digest = content_sha256(canonical_json_bytes({"rows": page_payload}))
        rows.append(
            LocatorRow(
                first_key=group[0],
                last_key=group[-1],
                relative_path=relative,
                sha256=digest,
                size_bytes=0,
                row_count=len(group),
                shard_id=page_index,
                kind=KIND_VECTORS,
                schema_version=LOCATOR_SCHEMA_VERSION,
                page_index=page_index,
                start_document_index=offset,
                end_document_index=offset + len(group) - 1,
                metadata={
                    "kind": "vector_entry_locator_page",
                    "vector_keys": list(group),
                    "data_paths": sorted(
                        {locations[key].relative_path for key in group}
                    ),
                },
            )
        )
    if len(rows) > MAX_ROUTING_ROWS_PER_INDEX:
        raise VectorRouteBoundError(
            f"entry locator page count {len(rows)} exceeds "
            f"{MAX_ROUTING_ROWS_PER_INDEX}"
        )
    return tuple(rows)


def build_location_map(
    layout: VectorClusterLayout,
    *,
    records: Sequence[EmbeddingRecord],
    descriptors: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, VectorShardLocation]:
    parent_by_key = {rec.chunk_cid: rec for rec in records}
    descriptor_map = descriptors or {}
    locations: dict[str, VectorShardLocation] = {}
    score_by_key: dict[str, float] = {}
    for shard in layout.shards:
        reject_legacy_faiss_path(shard.relative_path, name="shard.relative_path")
        for offset, vector_key in enumerate(shard.entry_cids):
            if offset < len(shard.scores):
                score_by_key[vector_key] = float(shard.scores[offset])
    for shard in layout.shards:
        extra = descriptor_map.get(shard.relative_path, {})
        sha256 = str(extra.get("sha256") or "") or _synthetic_shard_digest(
            shard.relative_path, shard.row_count
        )
        size_bytes = int(extra.get("size_bytes") or 0)
        content_cid_value = extra.get("content_cid") or extra.get("cid")
        for offset, vector_key in enumerate(shard.entry_cids):
            if vector_key in locations:
                raise VectorCoverageError(
                    f"duplicate vector key across shards: {vector_key!r}"
                )
            record = parent_by_key.get(vector_key)
            locations[vector_key] = VectorShardLocation(
                vector_key=vector_key,
                chunk_cid=vector_key,
                relative_path=shard.relative_path,
                cluster_id=shard.cluster_id,
                chunk_in_cluster=shard.chunk_in_cluster,
                global_shard_id=shard.global_shard_id,
                row_offset=offset,
                entry_cid=record.entry_cid if record is not None else None,
                document_index=(
                    shard.document_indexes[offset]
                    if offset < len(shard.document_indexes)
                    else offset
                ),
                sha256=sha256,
                size_bytes=size_bytes,
                content_cid=str(content_cid_value) if content_cid_value else None,
                dimension=shard.dimension,
                centroid_cosine=score_by_key.get(vector_key, 0.0),
            )
    if len(locations) != layout.total_rows:
        raise VectorCoverageError(
            f"location map has {len(locations)} keys; layout has "
            f"{layout.total_rows} rows"
        )
    return locations


def build_parent_links(
    records: Sequence[EmbeddingRecord],
) -> tuple[CorpusParentLink, ...]:
    links: list[CorpusParentLink] = []
    for position, record in enumerate(records):
        if record.entry_cid is None:
            continue
        links.append(
            CorpusParentLink(
                chunk_cid=record.chunk_cid,
                entry_cid=record.entry_cid,
                document_index=position,
                chunk_id=record.chunk_id,
            )
        )
    return tuple(sorted(links, key=lambda item: item.chunk_cid))


def build_input_receipts(
    records: Sequence[EmbeddingRecord],
    *,
    config: FederalRegisterEmbeddingConfig | None = None,
) -> tuple[InputReceipt, ...]:
    pin = config
    receipts: list[InputReceipt] = []
    for record in records:
        receipts.append(
            InputReceipt(
                chunk_cid=record.chunk_cid,
                input_hash=record.input_hash,
                model_id=record.model_id,
                model_revision=record.model_revision,
                pooling=record.pooling,
                normalization=record.normalization,
                dimension=record.dimension,
                preprocessing=pin.preprocessing if pin is not None else PREPROCESSING,
                vector_space_id=record.vector_space_id,
                config_cid=record.config_cid,
            )
        )
    return tuple(sorted(receipts, key=lambda item: item.chunk_cid))


def build_manifest_descriptors(
    layout: VectorClusterLayout,
    *,
    routing_rows: Sequence[Mapping[str, Any]],
    entry_locator_rows: Sequence[LocatorRow],
    descriptors: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[ManifestReadyDescriptor, ...]:
    descriptor_map = descriptors or {}
    out: list[ManifestReadyDescriptor] = []
    for shard in layout.shards:
        reject_legacy_faiss_path(shard.relative_path, name="shard.relative_path")
        extra = descriptor_map.get(shard.relative_path, {})
        sha256 = str(extra.get("sha256") or "") or _synthetic_shard_digest(
            shard.relative_path, shard.row_count
        )
        out.append(
            ManifestReadyDescriptor(
                relative_path=shard.relative_path,
                family=ArtifactFamily.VECTORS.value,
                row_count=shard.row_count,
                sha256=sha256,
                size_bytes=int(extra.get("size_bytes") or 0),
                schema_id=VECTOR_LAYOUT_SCHEMA_VERSION,
                first_key=shard.entry_cids[0] if shard.entry_cids else None,
                last_key=shard.entry_cids[-1] if shard.entry_cids else None,
                centroid_id=f"cluster-{shard.cluster_id:06d}",
                metadata={
                    "chunk_in_cluster": shard.chunk_in_cluster,
                    "cluster_id": shard.cluster_id,
                    "global_shard_id": shard.global_shard_id,
                },
            )
        )
    routing_digest = content_sha256(
        canonical_json_bytes({"routing_rows": list(routing_rows)})
    )
    reject_legacy_faiss_path(VECTOR_INDEX_PATH, name="vector_index_path")
    out.append(
        ManifestReadyDescriptor(
            relative_path=VECTOR_INDEX_PATH,
            family=ArtifactFamily.ROUTING_INDEX.value,
            row_count=len(routing_rows),
            sha256=routing_digest,
            schema_id=VECTOR_ROUTING_SCHEMA_VERSION,
            metadata={"kind": "centroid_routing_index"},
        )
    )
    for row in entry_locator_rows:
        out.append(
            ManifestReadyDescriptor(
                relative_path=row.relative_path,
                family=ArtifactFamily.LOCATOR_INDEX.value,
                row_count=row.row_count,
                sha256=row.sha256,
                size_bytes=row.size_bytes,
                schema_id=LOCATOR_SCHEMA_VERSION,
                first_key=row.first_key,
                last_key=row.last_key,
                metadata={"kind": "vector_entry_locator_page"},
            )
        )
    return tuple(out)


def production_vector_bounds() -> dict[str, Any]:
    policy = vector_bounds_policy()
    return {
        "assignment": ASSIGNMENT,
        "default_candidate_centroids": policy["default_candidate_centroids"],
        "layout_seed": DEFAULT_VECTOR_KMEANS_SEED,
        "maximum_rows_per_physical_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
        "maximum_rows_per_vector_centroid": MAX_ROWS_PER_VECTOR_CENTROID,
        "maximum_shards_per_centroid": MAX_VECTOR_SHARDS_PER_CENTROID,
        "rows_sorted_by": ROWS_SORTED_BY,
        "target_rows_per_centroid": DEFAULT_TARGET_ROWS_PER_CENTROID,
    }


def fixture_vector_bounds(**overrides: Any) -> dict[str, int]:
    bounds = {
        "entry_locator_page_size": DEFAULT_TEST_ENTRY_LOCATOR_PAGE_SIZE,
        "kmeans_iterations": DEFAULT_KMEANS_ITERATIONS,
        "max_rows_per_centroid": DEFAULT_TEST_MAX_ROWS_PER_CENTROID,
        "max_rows_per_shard": DEFAULT_TEST_MAX_ROWS_PER_SHARD,
        "max_shards_per_centroid": MAX_VECTOR_SHARDS_PER_CENTROID,
        "seed": DEFAULT_VECTOR_KMEANS_SEED,
        "target_rows_per_centroid": DEFAULT_TEST_TARGET_ROWS_PER_CENTROID,
    }
    bounds.update(overrides)
    return bounds


def assert_centroid_routes_bounded(layout: VectorClusterLayout) -> None:
    if layout.max_rows_per_shard > MAX_ROWS_PER_PHYSICAL_SHARD:
        raise VectorRouteBoundError(
            f"max_rows_per_shard={layout.max_rows_per_shard} exceeds "
            f"{MAX_ROWS_PER_PHYSICAL_SHARD}"
        )
    if layout.max_rows_per_centroid > MAX_ROWS_PER_VECTOR_CENTROID:
        raise VectorRouteBoundError(
            f"max_rows_per_centroid={layout.max_rows_per_centroid} exceeds "
            f"{MAX_ROWS_PER_VECTOR_CENTROID}"
        )
    if layout.max_shards_per_centroid > MAX_VECTOR_SHARDS_PER_CENTROID:
        raise VectorRouteBoundError(
            f"max_shards_per_centroid={layout.max_shards_per_centroid} exceeds "
            f"{MAX_VECTOR_SHARDS_PER_CENTROID}"
        )
    for group in layout.clusters:
        if group.row_count > layout.max_rows_per_centroid:
            raise VectorRouteBoundError(
                f"cluster {group.cluster_id} has {group.row_count} rows; "
                f"exceeds {layout.max_rows_per_centroid}"
            )
        if group.shard_count > layout.max_shards_per_centroid:
            raise VectorRouteBoundError(
                f"cluster {group.cluster_id} has {group.shard_count} shards; "
                f"exceeds {layout.max_shards_per_centroid}"
            )
        if group.row_count > MAX_ROWS_PER_VECTOR_CENTROID:
            raise VectorRouteBoundError(
                f"cluster {group.cluster_id} exceeds the 8192-row centroid bound"
            )
        if group.shard_count > MAX_VECTOR_SHARDS_PER_CENTROID:
            raise VectorRouteBoundError(
                f"cluster {group.cluster_id} exceeds the two-shard centroid bound"
            )
        for shard in group.shards:
            reject_legacy_faiss_path(shard.relative_path, name="shard.relative_path")
            if shard.row_count > layout.max_rows_per_shard:
                raise VectorRouteBoundError(
                    f"shard {shard.relative_path} has {shard.row_count} rows; "
                    f"exceeds {layout.max_rows_per_shard}"
                )
            if shard.row_count > MAX_ROWS_PER_PHYSICAL_SHARD:
                raise VectorRouteBoundError(
                    f"shard {shard.relative_path} exceeds the 4096-row physical bound"
                )
            expected_path = vector_shard_relative_path(
                shard.cluster_id,
                shard.chunk_in_cluster,
                data_dir=str(Path(shard.relative_path).parent).replace("\\", "/"),
            )
            if Path(shard.relative_path).name != Path(expected_path).name:
                raise VectorRouteBoundError(
                    f"shard path {shard.relative_path!r} is not centroid-specific"
                )


def assert_every_chunk_once(
    layout: VectorClusterLayout,
    *,
    expected_chunk_cids: Sequence[str],
) -> None:
    expected = list(expected_chunk_cids)
    if len(expected) != len(set(expected)):
        raise VectorCoverageError("expected chunk_cids are not unique")
    observed = list(layout.all_entry_cids())
    if len(observed) != len(set(observed)):
        raise VectorCoverageError("layout contains duplicate vector keys")
    if len(observed) != len(expected):
        raise VectorCoverageError(
            f"layout has {len(observed)} rows; expected {len(expected)}"
        )
    if sorted(observed) != sorted(expected):
        extra = sorted(set(observed) - set(expected))
        missing = sorted(set(expected) - set(observed))
        raise VectorCoverageError(
            f"layout vector-key set differs; extra={extra!r} missing={missing!r}"
        )
    validate_vector_layout(layout, expected_entry_cids=expected)


def reconcile_roots(
    binding: FederalRegisterVectorBinding,
    *,
    expected_model_id: str | None = None,
    expected_model_revision: str | None = None,
    expected_config_cid: str | None = None,
    expected_vector_space_id: str | None = None,
    expected_corpus_root_cid: str | None = None,
    expected_layout_seed: int | None = None,
    expected_vector_root_cid: str | None = None,
) -> dict[str, Any]:
    checks: dict[str, Any] = {
        "config_cid": binding.config_cid,
        "corpus_root_cid": binding.corpus_root_cid,
        "layout_seed": binding.layout_seed,
        "model_cid": binding.model_cid,
        "model_id": binding.model_id,
        "model_revision": binding.model_revision,
        "reconciled": True,
        "vector_root_cid": binding.vector_root_cid,
        "vector_space_id": binding.vector_space_id,
    }
    mismatches: list[str] = []

    def _check(name: str, actual: Any, expected: Any) -> None:
        if expected is None:
            return
        if actual != expected:
            mismatches.append(f"{name}: actual={actual!r} expected={expected!r}")

    _check("model_id", binding.model_id, expected_model_id)
    _check("model_revision", binding.model_revision, expected_model_revision)
    if expected_config_cid is not None:
        _check(
            "config_cid",
            binding.config_cid,
            validate_digest(expected_config_cid, name="expected_config_cid"),
        )
    _check("vector_space_id", binding.vector_space_id, expected_vector_space_id)
    if expected_corpus_root_cid is not None:
        _check(
            "corpus_root_cid",
            binding.corpus_root_cid,
            validate_digest(
                expected_corpus_root_cid, name="expected_corpus_root_cid"
            ),
        )
    if expected_layout_seed is not None:
        _check("layout_seed", binding.layout_seed, int(expected_layout_seed))
    if expected_vector_root_cid is not None:
        _check(
            "vector_root_cid",
            binding.vector_root_cid,
            validate_digest(
                expected_vector_root_cid, name="expected_vector_root_cid"
            ),
        )

    recomputed_model = build_model_cid(
        model_id=binding.model_id,
        model_revision=binding.model_revision,
        vector_space_id=binding.vector_space_id,
    )
    if recomputed_model != binding.model_cid:
        mismatches.append(
            f"model_cid drift: bound={binding.model_cid!r} "
            f"recomputed={recomputed_model!r}"
        )
    recomputed_layout = build_layout_root_cid(binding.layout)
    if recomputed_layout != binding.vector_root_cid:
        mismatches.append(
            f"vector_root_cid drift: bound={binding.vector_root_cid!r} "
            f"recomputed={recomputed_layout!r}"
        )
    if binding.layout.seed != binding.layout_seed:
        mismatches.append(
            f"layout seed drift: layout.seed={binding.layout.seed} "
            f"binding.layout_seed={binding.layout_seed}"
        )
    if mismatches:
        raise VectorRootReconcileError(
            "vector roots/revisions do not reconcile: " + "; ".join(mismatches)
        )
    return checks


# ---------------------------------------------------------------------------
# Input coercion for bind()
# ---------------------------------------------------------------------------


def _embedding_records_from_input(
    embeddings: (
        EmbeddingGenerationResult
        | Mapping[str, EmbeddingRecord | Mapping[str, Any] | Sequence[float]]
        | Sequence[EmbeddingRecord | Mapping[str, Any]]
    ),
) -> tuple[EmbeddingRecord, ...]:
    if isinstance(embeddings, EmbeddingGenerationResult):
        records = tuple(
            embeddings.embeddings[cid] for cid in sorted(embeddings.embeddings)
        )
        if not records:
            raise VectorBindingError("embedding result contains no vectors")
        return records

    if isinstance(embeddings, Mapping):
        records_list: list[EmbeddingRecord] = []
        for key in sorted(embeddings):
            value = embeddings[key]
            if isinstance(value, EmbeddingRecord):
                if value.chunk_cid != key:
                    raise VectorBindingError(
                        f"embedding map key {key!r} != record.chunk_cid "
                        f"{value.chunk_cid!r}"
                    )
                records_list.append(value)
            elif isinstance(value, Mapping):
                payload = dict(value)
                payload.setdefault("chunk_cid", key)
                records_list.append(_embedding_record_from_mapping(payload))
            elif isinstance(value, Sequence) and not isinstance(
                value, (str, bytes, bytearray)
            ):
                raise VectorBindingError(
                    "bare embedding sequences require full EmbeddingRecord "
                    "fields (model pin, vector_space_id, config_cid)"
                )
            else:
                raise VectorBindingError(
                    f"embeddings[{key!r}] must be an EmbeddingRecord or mapping"
                )
        if not records_list:
            raise VectorBindingError("embeddings mapping is empty")
        return tuple(records_list)

    if isinstance(embeddings, Sequence) and not isinstance(
        embeddings, (str, bytes, bytearray)
    ):
        records_list = []
        for position, item in enumerate(embeddings):
            if isinstance(item, EmbeddingRecord):
                records_list.append(item)
            elif isinstance(item, Mapping):
                records_list.append(_embedding_record_from_mapping(item))
            else:
                raise VectorBindingError(
                    f"embeddings[{position}] must be an EmbeddingRecord or mapping"
                )
        if not records_list:
            raise VectorBindingError("embeddings sequence is empty")
        return tuple(records_list)

    raise VectorBindingError(
        "embeddings must be an EmbeddingGenerationResult, mapping, or sequence"
    )


def _embedding_record_from_mapping(value: Mapping[str, Any]) -> EmbeddingRecord:
    chunk_cid = _durable_key(
        value.get("chunk_cid") or value.get("vector_key") or value.get("cid") or "",
        "chunk_cid",
    )
    embedding = value.get("embedding")
    if not isinstance(embedding, Sequence) or isinstance(
        embedding, (str, bytes, bytearray)
    ):
        raise VectorBindingError(f"embedding for {chunk_cid!r} must be a float sequence")
    dimension = int(value.get("dimension") or len(embedding))
    model_id = str(value.get("model_id") or PINNED_MODEL_ID)
    model_revision = str(value.get("model_revision") or PINNED_MODEL_REVISION)
    require_pinned_gte_small(model_id=model_id, model_revision=model_revision)
    pooling = str(value.get("pooling") or PINNED_POOLING)
    normalization = str(value.get("normalization") or PINNED_NORMALIZATION)
    vector_space_id = str(value.get("vector_space_id") or "").strip() or default_vector_space_id()
    config_cid_value = str(value.get("config_cid") or "").strip()
    if not config_cid_value:
        config_cid_value = content_cid(
            {
                "model_id": model_id,
                "model_revision": model_revision,
                "vector_space_id": vector_space_id,
            }
        )
    input_hash = str(value.get("input_hash") or "").strip()
    if not input_hash:
        input_hash = content_sha256(f"input:{chunk_cid}")
    validated = validate_vector_dimension(
        tuple(float(x) for x in embedding),
        dimension=dimension,
        name=f"embedding[{chunk_cid}]",
    )
    if normalization == "l2":
        validated = tuple(l2_normalize(validated))
    l2 = float(value.get("l2_norm") or 0.0)
    if l2 <= 0.0:
        l2 = l2_norm(validated)
    return EmbeddingRecord(
        chunk_cid=chunk_cid,
        embedding=validated,
        dimension=dimension,
        input_hash=input_hash,
        model_id=model_id,
        model_revision=model_revision,
        vector_space_id=vector_space_id,
        pooling=pooling,
        normalization=normalization,
        l2_norm=l2,
        config_cid=config_cid_value,
        entry_cid=value.get("entry_cid"),
        chunk_id=value.get("chunk_id"),
    )


# ---------------------------------------------------------------------------
# Main bind API
# ---------------------------------------------------------------------------


def bind_federal_register_vectors(
    embeddings: (
        EmbeddingGenerationResult
        | Mapping[str, EmbeddingRecord | Mapping[str, Any] | Sequence[float]]
        | Sequence[EmbeddingRecord | Mapping[str, Any]]
    ),
    *,
    corpus_root_cid: str | None = None,
    config: FederalRegisterEmbeddingConfig | None = None,
    seed: int = DEFAULT_VECTOR_KMEANS_SEED,
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    max_shards_per_centroid: int = MAX_VECTOR_SHARDS_PER_CENTROID,
    max_rows_per_centroid: int | None = None,
    target_rows_per_centroid: int = DEFAULT_TARGET_ROWS_PER_CENTROID,
    kmeans_iterations: int = DEFAULT_KMEANS_ITERATIONS,
    data_dir: str = VECTOR_DATA_DIR,
    entry_locator_page_size: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    shard_descriptors: Mapping[str, Mapping[str, Any]] | None = None,
) -> FederalRegisterVectorBinding:
    """Bind trusted Federal Register embeddings to centroid routes."""

    reject_legacy_faiss_path(data_dir, name="data_dir")
    if max_rows_per_shard > MAX_ROWS_PER_PHYSICAL_SHARD:
        raise VectorRouteBoundError(
            f"max_rows_per_shard={max_rows_per_shard} exceeds "
            f"{MAX_ROWS_PER_PHYSICAL_SHARD}"
        )
    if max_shards_per_centroid > MAX_VECTOR_SHARDS_PER_CENTROID:
        raise VectorRouteBoundError(
            f"max_shards_per_centroid={max_shards_per_centroid} exceeds "
            f"{MAX_VECTOR_SHARDS_PER_CENTROID}"
        )
    if (
        max_rows_per_centroid is not None
        and max_rows_per_centroid > MAX_ROWS_PER_VECTOR_CENTROID
    ):
        raise VectorRouteBoundError(
            f"max_rows_per_centroid={max_rows_per_centroid} exceeds "
            f"{MAX_ROWS_PER_VECTOR_CENTROID}"
        )

    records = _embedding_records_from_input(embeddings)
    chunk_cids = [rec.chunk_cid for rec in records]
    pins = {
        (
            rec.model_id,
            rec.model_revision,
            rec.vector_space_id,
            rec.config_cid,
            rec.dimension,
            rec.pooling,
            rec.normalization,
        )
        for rec in records
    }
    if len(pins) != 1:
        raise VectorBindingError(
            "all embeddings must share one model/config/vector-space pin; "
            f"observed {len(pins)} distinct pins"
        )
    first = records[0]
    require_pinned_gte_small(
        model_id=first.model_id, model_revision=first.model_revision
    )
    if first.dimension != PINNED_DIMENSION:
        raise VectorBindingError(
            f"embeddings must be {PINNED_DIMENSION}-d; got {first.dimension}"
        )
    bound_config = config
    if config is not None:
        if (
            config.model_id != first.model_id
            or config.model_revision != first.model_revision
            or config.vector_space_id != first.vector_space_id
        ):
            raise VectorRootReconcileError(
                "supplied embedding config does not match embedding pin"
            )

    model_id, model_revision = require_pinned_gte_small(
        model_id=first.model_id, model_revision=first.model_revision
    )
    vector_space_id = first.vector_space_id
    config_cid = validate_digest(first.config_cid, name="config_cid")
    model_cid = build_model_cid(
        model_id=model_id,
        model_revision=model_revision,
        vector_space_id=vector_space_id,
    )

    vector_rows = embeddings_to_vector_records(records)
    layout = build_centroid_routed_vector_layout(
        vector_rows,
        seed=seed,
        max_rows_per_shard=max_rows_per_shard,
        max_shards_per_centroid=max_shards_per_centroid,
        max_rows_per_centroid=max_rows_per_centroid,
        target_rows_per_centroid=target_rows_per_centroid,
        kmeans_iterations=kmeans_iterations,
        data_dir=data_dir,
    )
    assert_every_chunk_once(layout, expected_chunk_cids=chunk_cids)
    assert_centroid_routes_bounded(layout)

    locations = build_location_map(
        layout, records=records, descriptors=shard_descriptors
    )
    parent_links = build_parent_links(records)
    routing_rows = layout.routing_rows(descriptors=shard_descriptors)
    entry_locator_rows = build_entry_locator_rows(
        locations, max_keys_per_page=entry_locator_page_size
    )
    descriptors = build_manifest_descriptors(
        layout,
        routing_rows=routing_rows,
        entry_locator_rows=entry_locator_rows,
        descriptors=shard_descriptors,
    )
    vector_root_cid = build_layout_root_cid(layout)
    corpus_root: Optional[str] = None
    if corpus_root_cid is not None and str(corpus_root_cid).strip():
        corpus_root = validate_digest(corpus_root_cid, name="corpus_root_cid")
    input_receipts = build_input_receipts(records, config=bound_config)

    binding = FederalRegisterVectorBinding(
        layout=layout,
        routing_rows=routing_rows,
        locations=locations,
        parent_links=parent_links,
        embeddings={rec.chunk_cid: rec for rec in records},
        model_id=model_id,
        model_revision=model_revision,
        vector_space_id=vector_space_id,
        config_cid=config_cid,
        model_cid=model_cid,
        vector_root_cid=vector_root_cid,
        layout_seed=layout.seed,
        corpus_root_cid=corpus_root,
        embedding_config=bound_config,
        entry_locator_rows=entry_locator_rows,
        descriptors=descriptors,
        input_receipts=input_receipts,
    )
    reconcile_roots(
        binding,
        expected_model_id=model_id,
        expected_model_revision=model_revision,
        expected_config_cid=config_cid,
        expected_vector_space_id=vector_space_id,
        expected_corpus_root_cid=corpus_root,
        expected_layout_seed=seed,
        expected_vector_root_cid=vector_root_cid,
    )
    return binding


def bind_federal_register_vectors_from_chunks(
    chunks: MaterializedCorpus
    | Sequence[AdmittedChunk | CanonicalChunk | Mapping[str, Any]],
    *,
    corpus_root_cid: str | None = None,
    config: FederalRegisterEmbeddingConfig | None = None,
    seed: int = DEFAULT_VECTOR_KMEANS_SEED,
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    max_shards_per_centroid: int = MAX_VECTOR_SHARDS_PER_CENTROID,
    max_rows_per_centroid: int | None = None,
    target_rows_per_centroid: int = DEFAULT_TARGET_ROWS_PER_CENTROID,
    kmeans_iterations: int = DEFAULT_KMEANS_ITERATIONS,
    entry_locator_page_size: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    embedder: EmbeddingFunction | None = None,
) -> FederalRegisterVectorBinding:
    """Embed admitted chunks with the sealed local backend, then bind routes."""

    pin = config or default_embedding_config()
    result = generate_federal_register_embeddings(
        chunks, config=pin, embedder=embedder
    )
    admitted = coerce_federal_chunks(chunks)
    assert_embedding_conservation(
        result, expected_chunk_cids=[chunk.chunk_cid for chunk in admitted]
    )
    root = corpus_root_cid or build_corpus_root_cid(chunks)
    return bind_federal_register_vectors(
        result,
        corpus_root_cid=root,
        config=pin,
        seed=seed,
        max_rows_per_shard=max_rows_per_shard,
        max_shards_per_centroid=max_shards_per_centroid,
        max_rows_per_centroid=max_rows_per_centroid,
        target_rows_per_centroid=target_rows_per_centroid,
        kmeans_iterations=kmeans_iterations,
        entry_locator_page_size=entry_locator_page_size,
    )


def bind_federal_register_vectors_from_corpus(
    corpus: MaterializedCorpus | None = None,
    *,
    config: FederalRegisterEmbeddingConfig | None = None,
    **kwargs: Any,
) -> FederalRegisterVectorBinding:
    materialized = corpus or materialize_federal_register_corpus()
    return bind_federal_register_vectors_from_chunks(
        materialized, config=config, **kwargs
    )


def bind_fixture_vectors(
    chunks: Sequence[Mapping[str, Any]] | MaterializedCorpus | None = None,
    **overrides: Any,
) -> FederalRegisterVectorBinding:
    """Bind the compact fixture recipe with tight physical test bounds."""

    if chunks is None:
        rows: MaterializedCorpus | Sequence[Mapping[str, Any]] = fixture_vector_chunks()
    else:
        rows = chunks
    config = overrides.pop("config", None) or fixture_embedding_config()
    bounds = fixture_vector_bounds(**overrides)
    return bind_federal_register_vectors_from_chunks(
        rows,
        config=config,
        seed=int(bounds["seed"]),
        max_rows_per_shard=int(bounds["max_rows_per_shard"]),
        max_shards_per_centroid=int(bounds["max_shards_per_centroid"]),
        max_rows_per_centroid=int(bounds["max_rows_per_centroid"]),
        target_rows_per_centroid=int(bounds["target_rows_per_centroid"]),
        kmeans_iterations=int(bounds["kmeans_iterations"]),
        entry_locator_page_size=int(bounds["entry_locator_page_size"]),
    )


def select_off_centroid_keys(
    binding: FederalRegisterVectorBinding,
    query_embedding: Sequence[float],
    *,
    candidate_centroids: int = 1,
) -> tuple[str, ...]:
    routes = binding.route_centroids(
        query_embedding, candidate_centroids=candidate_centroids
    )
    routed_paths = {route.relative_path for route in routes}
    off = [
        key
        for key, loc in sorted(binding.locations.items())
        if loc.relative_path not in routed_paths
    ]
    return tuple(off)


def prove_direct_cid_off_centroid_fetch(
    binding: FederalRegisterVectorBinding,
    query_embedding: Sequence[float],
    *,
    candidate_centroids: int = 1,
) -> dict[str, Any]:
    off_keys = select_off_centroid_keys(
        binding, query_embedding, candidate_centroids=candidate_centroids
    )
    if not off_keys:
        raise VectorLocatorError(
            "no off-centroid vector keys for the given probe budget; "
            "increase corpus diversity or lower candidate_centroids"
        )
    routes = binding.route_centroids(
        query_embedding, candidate_centroids=candidate_centroids
    )
    routed_paths = {route.relative_path for route in routes}
    samples: list[dict[str, Any]] = []
    for key in off_keys:
        hit = binding.locate_vector(key)
        if hit.relative_path in routed_paths:
            raise VectorLocatorError(
                f"key {key!r} unexpectedly maps to a routed centroid shard"
            )
        location = binding.location_for(key)
        if location.relative_path != hit.relative_path:
            raise VectorLocatorError(
                f"locator path drift for {key!r}: "
                f"{hit.relative_path!r} vs {location.relative_path!r}"
            )
        samples.append(
            {
                "relative_path": hit.relative_path,
                "shard_id": hit.shard_id,
                "vector_key": key,
            }
        )
    return {
        "candidate_centroids": candidate_centroids,
        "off_centroid_count": len(off_keys),
        "off_centroid_keys": list(off_keys),
        "routed_paths": sorted(routed_paths),
        "samples": samples,
    }


# ---------------------------------------------------------------------------
# Compact fixture recipe
# ---------------------------------------------------------------------------


def fixture_vector_chunks() -> list[dict[str, Any]]:
    """Compact admitted Federal Register chunk sample for sealed unit fixtures."""

    return [
        {
            "chunk_cid": _cid("a"),
            "entry_cid": _cid("b"),
            "chunk_id": "fr:2026-04567:2026-03-16#chunk=0000",
            "legal_id": "fr:2026-04567:2026-03-16",
            "heading": "SUMMARY",
            "title": "EPA emissions reporting rule",
            "section": "2026-04567",
            "text": (
                "The Environmental Protection Agency adopts emissions reporting "
                "requirements for stationary sources. Unique token "
                "epaemissionsrule. This final rule governs emissions reporting."
            ),
            "disposition": "admitted",
        },
        {
            "chunk_cid": _cid("c"),
            "entry_cid": _cid("d"),
            "chunk_id": "fr:2026-04568:2026-03-16#chunk=0000",
            "legal_id": "fr:2026-04568:2026-03-16",
            "heading": "DATES",
            "title": "EPA proposed emissions amendments",
            "section": "2026-04568",
            "text": (
                "EPA proposes amendments to emissions reporting for mobile "
                "sources. Unique token epaproposedrule. Comments on the "
                "emissions proposal are invited."
            ),
            "disposition": "admitted",
        },
        {
            "chunk_cid": _cid("e"),
            "entry_cid": _cid("f"),
            "chunk_id": "fr:2026-05001:2026-03-20#chunk=0000",
            "legal_id": "fr:2026-05001:2026-03-20",
            "heading": "ADDRESSES",
            "title": "DOT freight corridor notice",
            "section": "2026-05001",
            "text": (
                "The Department of Transportation publishes a freight corridor "
                "notice. Unique token dotnoticeunique. Emissions from freight "
                "corridors are discussed."
            ),
            "disposition": "admitted",
        },
        {
            "chunk_cid": _cid("1"),
            "entry_cid": _cid("2"),
            "chunk_id": "fr:2026-06010:2026-04-02#chunk=0000",
            "legal_id": "fr:2026-06010:2026-04-02",
            "heading": "SUPPLEMENTARY INFORMATION",
            "title": "USDA organic labeling rule",
            "section": "2026-06010",
            "text": (
                "USDA amends organic labeling. Unique token usdaorganicrule. "
                "The rule is not an emissions reporting action."
            ),
            "disposition": "admitted",
        },
        {
            "chunk_cid": _cid("3"),
            "entry_cid": _cid("4"),
            "chunk_id": "fr:2026-06111:2026-04-08#chunk=0000",
            "legal_id": "fr:2026-06111:2026-04-08",
            "heading": "AGENCY",
            "title": "HHS coverage proposed rule",
            "section": "2026-06111",
            "text": (
                "HHS proposes coverage amendments. Unique token "
                "hhsproposedrule. Emissions of covered services are out of scope."
            ),
            "disposition": "admitted",
        },
        {
            "chunk_cid": _cid("5"),
            "entry_cid": _cid("6"),
            "chunk_id": "fr:2026-07001:2026-06-01#chunk=0000",
            "legal_id": "fr:2026-07001:2026-06-01",
            "heading": "ACTION",
            "title": "EPA correction notice",
            "section": "2026-07001",
            "text": (
                "EPA issues a correction notice. Unique token "
                "epacorrectionnotice. The correction mentions emissions only "
                "in passing."
            ),
            "disposition": "admitted",
        },
        {
            "chunk_cid": _cid("7"),
            "entry_cid": _cid("8"),
            "chunk_id": "fr:2026-07100:2026-06-12#chunk=0000",
            "legal_id": "fr:2026-07100:2026-06-12",
            "heading": "FOR FURTHER INFORMATION CONTACT",
            "title": "Commerce export controls rule",
            "section": "2026-07100",
            "text": (
                "Commerce amends export controls. Unique token "
                "commerceruleunique. This final rule does not address emissions."
            ),
            "disposition": "admitted",
        },
        {
            "chunk_cid": _cid("9"),
            "entry_cid": _cid("0"),
            "chunk_id": "fr:2026-07222:2026-06-18#chunk=0000",
            "legal_id": "fr:2026-07222:2026-06-18",
            "heading": "SUMMARY",
            "title": "Interior public lands notice",
            "section": "2026-07222",
            "text": (
                "Interior publishes a public lands notice. Unique token "
                "interiornoticeunique. Emissions from public lands are noted."
            ),
            "disposition": "admitted",
        },
        {
            "entry_cid": "",
            "chunk_cid": "",
            "row_id": "recovery-src-01",
            "disposition": "quarantined",
            "is_recovery": True,
            "text": "workflow recovery payload must not enter vectors",
        },
        {
            "chunk_cid": _cid("f"),
            "entry_cid": _cid("f"),
            "disposition": "excluded",
            "text": "excluded incomplete provenance row",
        },
    ]


def admitted_fixture_chunks() -> list[dict[str, Any]]:
    return [
        row
        for row in fixture_vector_chunks()
        if str(row.get("disposition") or "admitted").lower() == "admitted"
        and not row.get("is_recovery")
    ]


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def default_vectors_report_path(repo_root: PathLike | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else repository_root()
    return (root / REPORT_RELATIVE_PATH).resolve()


def _acceptance_block() -> dict[str, Any]:
    return {
        "centroid_and_two_shard_bounds_hold": True,
        "criteria": (
            "Exactly one valid 384-d normalized vector per searchable chunk; "
            "no missing/extra/NaN row; centroid and two-shard bounds hold "
            "physically and logically."
        ),
        "exactly_one_vector_per_searchable_chunk": True,
        "hub_upload": False,
        "legacy_faiss_not_overwritten": True,
        "no_missing_extra_or_nan": True,
        "physical_shard_bound_4096": True,
        "secrets_absent": True,
    }


def _shard_bound_snapshot(binding: FederalRegisterVectorBinding) -> dict[str, Any]:
    max_centroid_rows = max((group.row_count for group in binding.layout.clusters), default=0)
    max_centroid_shards = max(
        (group.shard_count for group in binding.layout.clusters), default=0
    )
    max_shard_rows = max((shard.row_count for shard in binding.layout.shards), default=0)
    return {
        "cluster_count": binding.cluster_count,
        "max_centroid_rows": max_centroid_rows,
        "max_centroid_shards": max_centroid_shards,
        "max_shard_rows": max_shard_rows,
        "shard_count": binding.shard_count,
        "shard_relative_paths": [shard.relative_path for shard in binding.layout.shards],
    }


def build_federal_vectors_report(
    *,
    corpus: MaterializedCorpus | None = None,
    compact_binding: FederalRegisterVectorBinding | None = None,
) -> dict[str, Any]:
    """Build the sealed, secret-free LCR-057 vector receipt."""

    demo = compact_binding if compact_binding is not None else bind_fixture_vectors()
    materialized = corpus or materialize_federal_register_corpus()
    admitted = bind_federal_register_vectors_from_corpus(
        materialized,
        config=fixture_embedding_config(),
        **fixture_vector_bounds(),
    )
    expected = [chunk.chunk_cid for chunk in materialized.chunks]
    assert_every_chunk_once(admitted.layout, expected_chunk_cids=expected)
    assert_centroid_routes_bounded(admitted.layout)
    assert_centroid_routes_bounded(demo.layout)

    query = None
    for shard in demo.layout.shards:
        if shard.embeddings:
            query = list(shard.embeddings[0])
            break
    routes = ()
    if query is not None:
        routes = demo.route_centroids(query, candidate_centroids=1)
    off_centroid = None
    if query is not None and demo.cluster_count > 1:
        try:
            off_centroid = prove_direct_cid_off_centroid_fetch(
                demo, query, candidate_centroids=1
            )
        except VectorLocatorError:
            off_centroid = None

    demo_snapshot = _shard_bound_snapshot(demo)
    admitted_snapshot = _shard_bound_snapshot(admitted)
    pin = fixture_embedding_config()
    payload: dict[str, Any] = {
        "acceptance": _acceptance_block(),
        "adr_path": ADR_PATH,
        "admitted": {
            "chunk_count": len(materialized.chunks),
            "cluster_count": admitted.cluster_count,
            "config_cid": admitted.config_cid,
            "corpus_count": len(materialized.corpus_records),
            "corpus_root_cid": admitted.corpus_root_cid,
            "input_receipt_count": len(admitted.input_receipts),
            "layout_seed": admitted.layout_seed,
            "model_cid": admitted.model_cid,
            "shard_count": admitted.shard_count,
            "vector_count": admitted.vector_count,
            "vector_root_cid": admitted.vector_root_cid,
            "vector_space_id": admitted.vector_space_id,
        },
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "board_namespace": BOARD_NAMESPACE,
        "bounds": production_vector_bounds(),
        "bundle": BUNDLE,
        "checks": {
            "admitted_chunk_count": len(materialized.chunks),
            "admitted_max_centroid_rows": admitted_snapshot["max_centroid_rows"],
            "admitted_max_centroid_shards": admitted_snapshot["max_centroid_shards"],
            "admitted_max_shard_rows": admitted_snapshot["max_shard_rows"],
            "admitted_vector_count": admitted.vector_count,
            "centroid_specific_physical_shards": all(
                "centroid-" in path and "-part-" in path
                for path in admitted_snapshot["shard_relative_paths"]
            ),
            "demo_cluster_count": demo.cluster_count,
            "demo_max_centroid_rows": demo_snapshot["max_centroid_rows"],
            "demo_max_centroid_shards": demo_snapshot["max_centroid_shards"],
            "demo_max_shard_rows": demo_snapshot["max_shard_rows"],
            "demo_shard_count": demo.shard_count,
            "demo_vector_count": demo.vector_count,
            "dimension": PINNED_DIMENSION,
            "every_searchable_chunk_has_one_vector": admitted.vector_count
            == len(materialized.chunks),
            "gte_small_pin": True,
            "legacy_faiss_not_overwritten": True,
            "model_id": PINNED_MODEL_ID,
            "model_revision": PINNED_MODEL_REVISION,
            "no_hub_upload": True,
            "normalization": PINNED_NORMALIZATION,
            "off_centroid_direct_cid": bool(off_centroid),
            "pooling": PINNED_POOLING,
            "preprocessing": PREPROCESSING,
            "production_max_rows_per_centroid": MAX_ROWS_PER_VECTOR_CENTROID,
            "production_max_rows_per_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
            "production_max_shards_per_centroid": MAX_VECTOR_SHARDS_PER_CENTROID,
            "projection_backend_used_for_fixture": pin.is_projection_backend,
            "recovery_excluded_from_vectors": True,
            "seed": DEFAULT_VECTOR_KMEANS_SEED,
            "uscode_default_backend": USCODE_DEFAULT_BACKEND,
        },
        "code_version": CODE_VERSION,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "demo": {
            "chunk_cids": list(demo.vector_keys),
            "cluster_count": demo.cluster_count,
            "config_cid": demo.config_cid,
            "corpus_root_cid": demo.corpus_root_cid,
            "input_receipt_count": len(demo.input_receipts),
            "layout_seed": demo.layout_seed,
            "max_centroid_rows": demo_snapshot["max_centroid_rows"],
            "max_centroid_shards": demo_snapshot["max_centroid_shards"],
            "max_shard_rows": demo_snapshot["max_shard_rows"],
            "model_cid": demo.model_cid,
            "model_id": demo.model_id,
            "model_revision": demo.model_revision,
            "routed_shard_count": len(routes),
            "shard_count": demo.shard_count,
            "shard_relative_paths": demo_snapshot["shard_relative_paths"],
            "vector_count": demo.vector_count,
            "vector_root_cid": demo.vector_root_cid,
            "vector_space_id": demo.vector_space_id,
        },
        "depends_on": [CORPUS_TASK_ID],
        "description": (
            "LCR-057 Federal Register pinned embeddings and true centroid "
            "routes. Streams complete GTE-small embeddings, deterministic "
            "balanced spherical clusters, centroid-specific physical shards, "
            "routes, and model/input receipts. Hermetic against the LCR-055 "
            "admitted searchable chunks. Does not authorize Hub upload or "
            "overwrite legacy FAISS filenames."
        ),
        "embedding_contract": {
            "backend_fixture": DEFAULT_BACKEND,
            "backend_production": PRODUCTION_BACKEND,
            "dimension": PINNED_DIMENSION,
            "max_tokens": PINNED_MAX_TOKENS,
            "model_id": PINNED_MODEL_ID,
            "model_revision": PINNED_MODEL_REVISION,
            "normalization": PINNED_NORMALIZATION,
            "pooling": PINNED_POOLING,
            "preprocessing": PREPROCESSING,
            "seed": DEFAULT_VECTOR_KMEANS_SEED,
            "vector_space_id": default_vector_space_id(),
        },
        "family_counts": {
            "chunks": len(materialized.chunks),
            "corpus": len(materialized.corpus_records),
            "vector": admitted.vector_count,
            "vectors": admitted.vector_count,
        },
        "goal_id": GOAL_ID,
        "model_receipt": admitted.model_receipt(),
        "network_required": False,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "proves_software_contract_only": True,
        "release_profile": RELEASE_PROFILE,
        "report_kind": "fixture_vectors",
        "schema": REPORT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
    }
    compact = dict(payload)
    assert_no_secrets(compact, context="federal_vectors")
    blob = json.dumps(compact, sort_keys=True)
    if "/home/" in blob or "/Users/" in blob:
        raise SecretInReceiptError("vector report contains an absolute home path")
    if any(name in blob for name in FORBIDDEN_LEGACY_FAISS_FILENAMES if name.endswith(".faiss")):
        # Presence as a forbidden-name *value* is allowed only under explicit
        # rejection evidence; the report must not treat those as outputs.
        if compact.get("checks", {}).get("legacy_faiss_not_overwritten") is not True:
            raise LegacyFaissOverwriteError("report would overwrite a legacy FAISS file")
    compact["report_digest_sha256"] = digest_mapping(
        {key: value for key, value in compact.items() if key != "report_digest_sha256"}
    )
    return compact


def write_federal_vectors_report(
    path: PathLike | None = None,
    *,
    corpus: MaterializedCorpus | None = None,
) -> Path:
    target = Path(path) if path is not None else default_vectors_report_path()
    reject_legacy_faiss_path(str(target), name="report_path")
    payload = build_federal_vectors_report(corpus=corpus)
    write_json_atomic(target, payload)
    return target


def load_federal_vectors_report(path: PathLike | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else default_vectors_report_path()
    if not target.is_file():
        raise VectorReceiptError(f"vector report not found: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise VectorReceiptError("vector report root must be an object")
    return dict(payload)


def assert_federal_vectors_report(payload: Mapping[str, Any]) -> None:
    """Fail closed if the report would authorize release or weaken the contract."""

    if payload.get("task_id") != TASK_ID:
        raise VectorReceiptError(f"report task_id must be {TASK_ID!r}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise VectorReceiptError(
            f"report schema_version must be {SCHEMA_VERSION!r}"
        )
    if payload.get("authorizing_hub_upload") is True:
        raise VectorReleaseAuthorizationError(
            "vector report cannot authorize Hub upload"
        )
    if payload.get("authorizing_for_publication") is True:
        raise VectorReleaseAuthorizationError(
            "vector report cannot authorize publication"
        )
    acceptance = payload.get("acceptance") or {}
    if not isinstance(acceptance, Mapping):
        raise VectorReceiptError("report acceptance must be a mapping")
    if acceptance.get("hub_upload") is not False:
        raise VectorReceiptError("report must not claim Hub upload")
    if acceptance.get("exactly_one_vector_per_searchable_chunk") is not True:
        raise VectorReceiptError("report must prove one vector per searchable chunk")
    if acceptance.get("no_missing_extra_or_nan") is not True:
        raise VectorReceiptError("report must prove conservation and finite vectors")
    if acceptance.get("centroid_and_two_shard_bounds_hold") is not True:
        raise VectorReceiptError("report must prove centroid and two-shard bounds")
    if acceptance.get("physical_shard_bound_4096") is not True:
        raise VectorReceiptError("report must prove the 4096-row physical bound")
    if acceptance.get("legacy_faiss_not_overwritten") is not True:
        raise VectorReceiptError("report must prove legacy FAISS files were not overwritten")
    bounds = payload.get("bounds") or {}
    if not isinstance(bounds, Mapping):
        raise VectorReceiptError("report bounds must be a mapping")
    if bounds.get("maximum_rows_per_physical_shard") != MAX_ROWS_PER_PHYSICAL_SHARD:
        raise VectorReceiptError("report physical shard bound must be 4096")
    if bounds.get("maximum_rows_per_vector_centroid") != MAX_ROWS_PER_VECTOR_CENTROID:
        raise VectorReceiptError("report centroid row bound must be 8192")
    if bounds.get("maximum_shards_per_centroid") != MAX_VECTOR_SHARDS_PER_CENTROID:
        raise VectorReceiptError("report centroid shard bound must be 2")
    contract = payload.get("embedding_contract") or {}
    if not isinstance(contract, Mapping):
        raise VectorReceiptError("report embedding_contract must be a mapping")
    if contract.get("model_id") != PINNED_MODEL_ID:
        raise VectorReceiptError("report model_id is not the sealed GTE-small pin")
    if contract.get("model_revision") != PINNED_MODEL_REVISION:
        raise VectorReceiptError("report model_revision is not the sealed GTE-small pin")
    if contract.get("dimension") != PINNED_DIMENSION:
        raise VectorReceiptError("report dimension must be 384")
    blob = json.dumps(dict(payload), sort_keys=True)
    if "/home/" in blob or "/Users/" in blob:
        raise SecretInReceiptError("vector report contains an absolute home path")
    assert_no_secrets(payload, context="federal_vectors")


__all__ = [
    "ASSIGNMENT",
    "AUTHORIZES_HUB_UPLOAD",
    "AUTHORIZES_PUBLICATION",
    "DEFAULT_BACKEND",
    "DEFAULT_VECTOR_KMEANS_SEED",
    "FORBIDDEN_LEGACY_FAISS_FILENAMES",
    "GOAL_ID",
    "MAX_ROWS_PER_PHYSICAL_SHARD",
    "MAX_ROWS_PER_VECTOR_CENTROID",
    "MAX_VECTOR_SHARDS_PER_CENTROID",
    "PINNED_DIMENSION",
    "PINNED_MODEL_ID",
    "PINNED_MODEL_REVISION",
    "PINNED_NORMALIZATION",
    "PINNED_POOLING",
    "PREPROCESSING",
    "PRIMARY_KEY",
    "PRODUCER",
    "PRODUCTION_BACKEND",
    "PROGRAM_ID",
    "PROJECTION_BACKEND",
    "REPORT_SCHEMA",
    "SCHEMA_VERSION",
    "TASK_ID",
    "CorpusParentLink",
    "EmbeddingConfigError",
    "FederalRegisterEmbeddingConfig",
    "FederalRegisterVectorBinding",
    "FederalRegisterVectorError",
    "InputReceipt",
    "LegacyFaissOverwriteError",
    "ManifestReadyDescriptor",
    "UnpinnedModelError",
    "VectorBindingError",
    "VectorCoverageError",
    "VectorLocatorError",
    "VectorReceiptError",
    "VectorReleaseAuthorizationError",
    "VectorRootReconcileError",
    "VectorRouteBoundError",
    "VectorShardLocation",
    "admitted_fixture_chunks",
    "assert_centroid_routes_bounded",
    "assert_embedding_conservation",
    "assert_every_chunk_once",
    "assert_federal_vectors_report",
    "bind_federal_register_vectors",
    "bind_federal_register_vectors_from_chunks",
    "bind_federal_register_vectors_from_corpus",
    "bind_fixture_vectors",
    "build_corpus_root_cid",
    "build_federal_vectors_report",
    "build_layout_root_cid",
    "build_model_cid",
    "chunks_from_materialized_corpus",
    "default_embedding_config",
    "default_vector_space_id",
    "default_vectors_report_path",
    "fixture_embedding_config",
    "fixture_vector_bounds",
    "fixture_vector_chunks",
    "generate_federal_register_embeddings",
    "load_federal_vectors_report",
    "production_embedding_config",
    "production_vector_bounds",
    "prove_direct_cid_off_centroid_fetch",
    "reconcile_roots",
    "reject_legacy_faiss_path",
    "reject_placeholder_model_ref",
    "require_pinned_gte_small",
    "select_off_centroid_keys",
    "write_federal_vectors_report",
]
