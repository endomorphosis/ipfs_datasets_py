"""Pinned thenlper/gte-small embeddings for state-law chunks (LCR-028).

Adapter between admitted LCR-025 chunks / LCR-024 corpus rows and one
pinned legal vector space:

* exactly one 384-d L2-normalized vector per admitted searchable chunk;
* sealed GTE-small revision, mean pooling, L2 normalization, NFKC
  whitespace collapse, and input-text hashes;
* output keys equal the admitted ``chunk_cid`` set exactly;
* zero, duplicate, orphan, NaN, wrong-dimension, stale-model, and
  changed-input vectors fail closed.

Design invariants
-----------------
* Retrieval identity is the chunk CID. Parent ``entry_cid`` is a join key.
* Default offline backend is the sealed local hashed projection so unit
  tests never download sentence-transformers or torch models. Production
  callers may request the sentence-transformers backend; the GTE-small pin
  still binds every receipt and placeholder model refs fail closed.
* Projection embeddings prove the software contract only and cannot
  authorize publication or Hub upload.
* Fixture builds are hermetic. No Hub upload, no tokens, no absolute
  home paths in receipts.

Depends on LCR-025 (chunker), LCR-024 (corpus), and LCR-026 (adapter) as
read-only. Does not cluster, shard, or publish vectors (LCR-029+).
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Optional, Union

from ipfs_datasets_py.processors.legal_data.state_laws_chunker import (
    TASK_ID as CHUNKER_TASK_ID,
    LegalTextChunk,
)
from ipfs_datasets_py.processors.legal_data.state_laws_corpus import (
    TASK_ID as CORPUS_TASK_ID,
    MaterializedCorpus,
    assert_no_secrets_or_home_paths,
)
from ipfs_datasets_py.processors.legal_data.state_laws_graphrag_adapter import (
    TASK_ID as ADAPTER_TASK_ID,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    ADR_PATH,
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_EMBEDDING_DIMENSION as SCHEMA_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL_ID as SCHEMA_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_MODEL_REVISION as SCHEMA_EMBEDDING_MODEL_REVISION,
    RELEASE_PROFILE,
    MutableReferenceError,
    PositionalIdentityError,
    digest_mapping,
    reject_positional_durable_identity,
    require_immutable_model_ref,
    validate_entry_cid,
)
from ipfs_datasets_py.processors.legal_data.state_laws_source_policy import (
    CURRENTNESS_DISCLAIMER,
)
from ipfs_datasets_py.processors.legal_data.uscode_embeddings import (
    DEFAULT_BACKEND as USCODE_DEFAULT_BACKEND,
    DEFAULT_BATCH_SIZE,
    DEFAULT_DEVICE as USCODE_DEFAULT_DEVICE,
    DEFAULT_INPUT_FIELDS,
    DEFAULT_MODEL_ID,
    DEFAULT_MODEL_LICENSE,
    DEFAULT_MODEL_REVISION,
    DEFAULT_NORMALIZATION,
    DEFAULT_POOLING,
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


# ---------------------------------------------------------------------------
# Identity / pin
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "state-laws-embeddings-v1"
REPORT_SCHEMA: Final = "ipfs_datasets_py/legal-corpora-reindex-embeddings@1"
TASK_ID: Final = "LCR-028"
GOAL_ID: Final = "LCR-G040"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "state_laws_embeddings.py"
BOARD_NAMESPACE: Final = "legal-corpora-reindex-v1"
BUNDLE: Final = "dense-embeddings"
CODE_VERSION: Final = "1"

PRIMARY_KEY: Final = "chunk_cid"
PARENT_KEY: Final = "entry_cid"
PREPROCESSING: Final = "nfkc_whitespace_collapse"

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
DEFAULT_DEVICE: Final = "cpu"

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
AUTHORIZES_RELEASE: Final = False
PROVES_SOFTWARE_CONTRACT_ONLY: Final = True
PROJECTION_FALLBACK_AUTHORIZES_RELEASE: Final = False

REPORT_RELATIVE_PATH: Final = Path(
    "docs/reports/legal_corpora_reindex/embedding_receipt.json"
)
_REPO_ROOT = Path(__file__).resolve().parents[3]

EXCLUDED_DISPOSITIONS: Final = frozenset(
    {
        "quarantined",
        "excluded",
        "failed_final",
        "recovery",
        "history",
        "duplicate",
    }
)
PROJECTION_BACKENDS: Final = frozenset(
    {
        PROJECTION_BACKEND,
        "deterministic",
        "hashed",
        "offline",
        "fixture",
        "local",
        "local_deterministic",
        USCODE_DEFAULT_BACKEND,
    }
)
PRODUCTION_BACKENDS: Final = frozenset({PRODUCTION_BACKEND, "huggingface"})

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


if PINNED_MODEL_ID != SCHEMA_EMBEDDING_MODEL_ID:
    raise RuntimeError("state-law model pin drifted from release schema")
if PINNED_MODEL_REVISION != SCHEMA_EMBEDDING_MODEL_REVISION:
    raise RuntimeError("state-law model revision drifted from release schema")
if PINNED_DIMENSION != SCHEMA_EMBEDDING_DIMENSION:
    raise RuntimeError("state-law dimension drifted from release schema")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class StateLawsEmbeddingError(ValueError):
    """Base error for pinned state-law embedding generation."""

    code: str = "state_laws_embedding_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class EmbeddingConfigError(StateLawsEmbeddingError):
    """Raised when the embedding pin is incomplete or not GTE-small."""

    code = "config_invalid"


class VectorCoverageError(StateLawsEmbeddingError):
    """Raised when embedding keys do not equal admitted chunk CIDs."""

    code = "coverage_invalid"


class ZeroVectorError(StateLawsEmbeddingError):
    """Raised when a vector is the zero vector."""

    code = "zero_vector"


class DuplicateVectorError(StateLawsEmbeddingError):
    """Raised when duplicate embedding keys appear."""

    code = "duplicate_vector"


class OrphanVectorError(StateLawsEmbeddingError):
    """Raised when an embedding key is not in the admitted chunk set."""

    code = "orphan_vector"


class StaleModelError(StateLawsEmbeddingError):
    """Raised when a stored vector is bound to a stale model pin."""

    code = "stale_model"


class InputHashDriftError(StateLawsEmbeddingError):
    """Raised when a stored vector's input hash no longer matches the chunk."""

    code = "changed_input"


class EmbeddingReceiptError(StateLawsEmbeddingError):
    """Raised when the sealed embedding receipt is malformed."""

    code = "receipt_invalid"


class EmbeddingReleaseAuthorizationError(StateLawsEmbeddingError):
    """Raised when a receipt would authorize publication or Hub upload."""

    code = "release_authorization_forbidden"


class EmbeddingEvaluationError(StateLawsEmbeddingError):
    """Raised when fixture evaluation cannot complete fail-closed."""

    code = "evaluation_invalid"


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 1024) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EmbeddingConfigError(f"{name} must be a non-empty string")
    text = value.strip()
    if "\x00" in text:
        raise EmbeddingConfigError(f"{name} must not contain NUL")
    if len(text) > maximum:
        raise EmbeddingConfigError(f"{name} exceeds maximum length {maximum}")
    return text


def _require_positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise EmbeddingConfigError(f"{name} must be a positive integer")
    return value


def _durable_key(value: Any, name: str) -> str:
    text = _require_non_empty_str(value, name, maximum=512)
    try:
        reject_positional_durable_identity(text, name=name)
    except PositionalIdentityError as exc:
        raise VectorCoverageError(str(exc), code="positional") from exc
    if text.lower().startswith("row-"):
        raise VectorCoverageError(
            f"{name} must not be a positional identity token: {text!r}",
            code="positional",
        )
    try:
        return validate_entry_cid(text, name=name)
    except (PositionalIdentityError, MutableReferenceError) as exc:
        raise VectorCoverageError(str(exc), code="positional") from exc


def content_cid(value: Any) -> str:
    """Stable ``sha256:<hex>`` content address for roots and receipts."""

    if isinstance(value, (bytes, bytearray)):
        digest = digest_mapping({"bytes": bytes(value).hex()})
        return f"sha256:{digest}"
    if isinstance(value, str):
        return f"sha256:{digest_mapping({'text': value})}"
    return f"sha256:{digest_mapping(dict(value))}"


def write_bytes_atomic(path: PathLike, data: bytes) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".sl-embed-",
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


def is_projection_backend(backend: Any) -> bool:
    return str(backend or "").strip().lower() in PROJECTION_BACKENDS


def is_production_backend(backend: Any) -> bool:
    return str(backend or "").strip().lower() in PRODUCTION_BACKENDS


def projection_cannot_authorize_publication() -> bool:
    return not PROJECTION_FALLBACK_AUTHORIZES_RELEASE


# ---------------------------------------------------------------------------
# Embedding configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StateLawsEmbeddingConfig:
    """GTE-small pin for state-law embeddings.

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
            cid = _durable_key(cid, "config_cid")
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
        return digest_mapping(self.pin_dict())

    @property
    def is_projection_backend(self) -> bool:
        return is_projection_backend(self.backend)

    @property
    def may_authorize_publication(self) -> bool:
        return False

    def to_uscode_config(self) -> UscodeEmbeddingConfig:
        """Project this pin onto the sealed US Code embedder config."""

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


def default_embedding_config() -> StateLawsEmbeddingConfig:
    """Hermetic default: GTE-small pin + local hashed projection."""

    return StateLawsEmbeddingConfig()


def fixture_embedding_config() -> StateLawsEmbeddingConfig:
    """Alias of :func:`default_embedding_config` for sealed unit tests."""

    return default_embedding_config()


def production_embedding_config() -> StateLawsEmbeddingConfig:
    """Production pin: GTE-small + sentence-transformers (not used in tests)."""

    return StateLawsEmbeddingConfig(
        backend=PRODUCTION_BACKEND,
        provider=PRODUCTION_PROVIDER,
        device=USCODE_DEFAULT_DEVICE,
    )


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InputReceipt:
    """Per-chunk input hash bound to the GTE-small pin."""

    chunk_cid: str
    entry_cid: Optional[str]
    input_hash: str
    model_id: str = PINNED_MODEL_ID
    model_revision: str = PINNED_MODEL_REVISION
    pooling: str = PINNED_POOLING
    normalization: str = PINNED_NORMALIZATION
    dimension: int = PINNED_DIMENSION
    preprocessing: str = PREPROCESSING
    vector_space_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "chunk_cid", _durable_key(self.chunk_cid, "chunk_cid"))
        if self.entry_cid:
            object.__setattr__(
                self, "entry_cid", _durable_key(self.entry_cid, "entry_cid")
            )
        require_pinned_gte_small(
            model_id=self.model_id, model_revision=self.model_revision
        )
        space = str(self.vector_space_id or "").strip() or default_vector_space_id()
        object.__setattr__(self, "vector_space_id", space)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_cid": self.chunk_cid,
            "dimension": self.dimension,
            "entry_cid": self.entry_cid,
            "input_hash": self.input_hash,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "normalization": self.normalization,
            "pooling": self.pooling,
            "preprocessing": self.preprocessing,
            "vector_space_id": self.vector_space_id,
        }


@dataclass(frozen=True, slots=True)
class StateLawsEmbeddingBinding:
    """Closed embedding set for admitted state-law chunks."""

    embeddings: Mapping[str, EmbeddingRecord]
    config: StateLawsEmbeddingConfig
    admitted_chunk_cids: tuple[str, ...]
    corpus_root_cid: str
    input_receipts: tuple[InputReceipt, ...] = ()
    generation: Optional[EmbeddingGenerationResult] = None
    schema_version: str = SCHEMA_VERSION
    task_id: str = TASK_ID
    goal_id: str = GOAL_ID

    def __post_init__(self) -> None:
        object.__setattr__(self, "embeddings", dict(self.embeddings))
        object.__setattr__(self, "admitted_chunk_cids", tuple(self.admitted_chunk_cids))
        object.__setattr__(self, "input_receipts", tuple(self.input_receipts))

    @property
    def vector_count(self) -> int:
        return len(self.embeddings)

    @property
    def vector_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self.embeddings))

    @property
    def config_cid(self) -> str:
        return self.config.config_cid

    @property
    def vector_space_id(self) -> str:
        return self.config.vector_space_id

    @property
    def model_id(self) -> str:
        return self.config.model_id

    @property
    def model_revision(self) -> str:
        return self.config.model_revision

    def receipt(self) -> dict[str, Any]:
        return {
            "config_cid": self.config_cid,
            "corpus_root_cid": self.corpus_root_cid,
            "dimension": PINNED_DIMENSION,
            "goal_id": self.goal_id,
            "input_receipt_count": len(self.input_receipts),
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "normalization": PINNED_NORMALIZATION,
            "pooling": PINNED_POOLING,
            "primary_key": PRIMARY_KEY,
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "vector_count": self.vector_count,
            "vector_space_id": self.vector_space_id,
        }


# ---------------------------------------------------------------------------
# Corpus / chunk coercion
# ---------------------------------------------------------------------------


def _cid(nibble: str) -> str:
    text = nibble.lower()
    if len(text) == 1 and all(ch in "0123456789abcdef" for ch in text):
        return f"sha256:{text * 64}"
    from ipfs_datasets_py.processors.legal_data.uscode_embeddings import content_sha256

    return f"sha256:{content_sha256(text)}"


def _normalize_chunk_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(value)
    if not payload.get("text"):
        payload["text"] = (
            payload.get("exclusive_text")
            or payload.get("body")
            or payload.get("embed_text")
            or ""
        )
    if not payload.get("chunk_cid"):
        payload["chunk_cid"] = payload.get("cid") or ""
    if not payload.get("legal_id"):
        payload["legal_id"] = payload.get("parent_legal_id")
    parent = payload.get("parent_entry_cid")
    if parent and not payload.get("entry_cid"):
        payload["entry_cid"] = parent
    return payload


def _admitted_from_legal_text_chunk(chunk: LegalTextChunk) -> AdmittedChunk:
    extras: dict[str, str] = {}
    if chunk.jurisdiction:
        extras["jurisdiction"] = chunk.jurisdiction
    if chunk.parent_legal_id:
        extras["parent_legal_id"] = chunk.parent_legal_id
    return AdmittedChunk(
        chunk_cid=chunk.chunk_cid,
        text=chunk.text or chunk.exclusive_text,
        entry_cid=None,
        chunk_id=chunk.chunk_id,
        legal_id=chunk.legal_id,
        heading=chunk.heading or "",
        title=chunk.title or "",
        section=chunk.section or "",
        extra_fields=extras,
    )


def chunks_from_legal_text_chunks(
    chunks: Sequence[LegalTextChunk],
) -> list[dict[str, Any]]:
    """Project LCR-025 semantic chunks into embedding input rows."""

    rows: list[dict[str, Any]] = []
    for chunk in chunks:
        if not isinstance(chunk, LegalTextChunk):
            raise VectorCoverageError("chunks must be LegalTextChunk rows")
        rows.append(
            {
                "chunk_cid": chunk.chunk_cid,
                "chunk_id": chunk.chunk_id,
                "heading": chunk.heading,
                "jurisdiction": chunk.jurisdiction,
                "legal_id": chunk.legal_id,
                "parent_legal_id": chunk.parent_legal_id,
                "section": chunk.section,
                "text": chunk.text or chunk.exclusive_text,
                "title": chunk.title,
            }
        )
    if not rows:
        raise VectorCoverageError("LegalTextChunk sequence is empty")
    return rows


def coerce_state_law_chunks(
    source: Sequence[AdmittedChunk | LegalTextChunk | Mapping[str, Any]]
    | MaterializedCorpus
    | Iterable[AdmittedChunk | LegalTextChunk | Mapping[str, Any]],
) -> tuple[AdmittedChunk, ...]:
    """Normalize admitted searchable chunks for the sealed embedder."""

    if isinstance(source, MaterializedCorpus):
        raise VectorCoverageError(
            "MaterializedCorpus rows are documents, not searchable chunks; "
            "pass LCR-025 LegalTextChunk rows or chunk mappings"
        )
    if isinstance(source, (str, bytes, bytearray)):
        raise VectorCoverageError("chunks must be an iterable of mappings")
    admitted: list[AdmittedChunk | Mapping[str, Any]] = []
    for position, item in enumerate(source):
        if isinstance(item, AdmittedChunk):
            admitted.append(item)
            continue
        if isinstance(item, LegalTextChunk):
            admitted.append(_admitted_from_legal_text_chunk(item))
            continue
        if isinstance(item, Mapping):
            payload = _normalize_chunk_mapping(item)
            disposition = str(payload.get("disposition") or "admitted").lower()
            if disposition in EXCLUDED_DISPOSITIONS:
                continue
            if payload.get("is_recovery") is True:
                continue
            if not payload.get("chunk_cid"):
                continue
            admitted.append(payload)
            continue
        raise VectorCoverageError(
            f"chunks[{position}] must be AdmittedChunk, LegalTextChunk, or mapping"
        )
    if not admitted:
        raise VectorCoverageError("no admitted searchable chunks to embed")
    return coerce_admitted_chunks(admitted)


def build_corpus_root_cid(
    rows: Iterable[Mapping[str, Any] | AdmittedChunk | LegalTextChunk],
) -> str:
    """Content-address admitted chunk identities (no full text payload)."""

    identities: list[dict[str, Any]] = []
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
        if isinstance(row, LegalTextChunk):
            identities.append(
                {
                    "chunk_cid": row.chunk_cid,
                    "chunk_id": row.chunk_id,
                    "legal_id": row.legal_id,
                }
            )
            continue
        if not isinstance(row, Mapping):
            raise VectorCoverageError(f"corpus row {position} must be a mapping")
        payload = _normalize_chunk_mapping(row)
        disposition = str(payload.get("disposition") or "admitted").lower()
        if disposition != "admitted" or payload.get("is_recovery") is True:
            continue
        if not payload.get("chunk_cid"):
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
            "schema_version": "state-laws-embedding-corpus-root/v1",
        }
    )


# ---------------------------------------------------------------------------
# Embedding generation / conservation
# ---------------------------------------------------------------------------


def _projection_embedder(config: StateLawsEmbeddingConfig) -> EmbeddingFunction:
    def _embed(texts: Sequence[str]) -> list[list[float]]:
        return deterministic_project(
            texts,
            dimension=config.dimension,
            normalize=config.normalization == "l2",
        )

    return _embed


def _chunk_input_text(
    chunk: AdmittedChunk, *, input_fields: Sequence[str]
) -> str:
    return chunk.resolve_input_text(input_fields)


def generate_state_laws_embeddings(
    chunks: Sequence[AdmittedChunk | LegalTextChunk | Mapping[str, Any]]
    | Iterable[AdmittedChunk | LegalTextChunk | Mapping[str, Any]],
    *,
    config: StateLawsEmbeddingConfig | None = None,
    embedder: EmbeddingFunction | None = None,
    checkpoint_path: PathLike | None = None,
) -> EmbeddingGenerationResult:
    """Embed admitted searchable chunks under the sealed GTE-small pin.

    Tests pass a projection backend (the default) so no model is downloaded.
    Production callers may set ``backend='sentence_transformers'``; the pin
    identity still binds every record.
    """

    pin = config or default_embedding_config()
    if not isinstance(pin, StateLawsEmbeddingConfig):
        raise EmbeddingConfigError("config must be a StateLawsEmbeddingConfig")
    require_pinned_gte_small(model_id=pin.model_id, model_revision=pin.model_revision)
    admitted = coerce_state_law_chunks(chunks)
    uscode_pin = pin.to_uscode_config()
    if embedder is not None:
        chosen = embedder
    elif pin.is_projection_backend:
        chosen = _projection_embedder(pin)
    else:
        chosen = None
    result = generate_uscode_embeddings(
        admitted,
        config=uscode_pin,
        embedder=chosen,
        checkpoint_path=checkpoint_path,
    )
    assert_embedding_conservation(result, expected_chunks=admitted, config=pin)
    return result


def assert_records_match_pin(
    records: Mapping[str, EmbeddingRecord] | Sequence[EmbeddingRecord],
    *,
    config: StateLawsEmbeddingConfig | None = None,
) -> None:
    """Fail closed on stale-model vectors."""

    pin = config or default_embedding_config()
    items = (
        records.values() if isinstance(records, Mapping) else records
    )
    for record in items:
        if not isinstance(record, EmbeddingRecord):
            raise StaleModelError("embedding record is not an EmbeddingRecord")
        if record.model_id != pin.model_id or record.model_revision != pin.model_revision:
            raise StaleModelError(
                f"{record.chunk_cid!r} is bound to stale model "
                f"{record.model_id}@{record.model_revision}"
            )
        if record.pooling != PINNED_POOLING:
            raise StaleModelError(f"{record.chunk_cid!r} pooling is not mean")
        if record.normalization != PINNED_NORMALIZATION:
            raise StaleModelError(f"{record.chunk_cid!r} normalization is not l2")
        if record.dimension != PINNED_DIMENSION:
            raise StaleModelError(f"{record.chunk_cid!r} dimension is not 384")
        if record.vector_space_id != pin.vector_space_id:
            raise StaleModelError(
                f"{record.chunk_cid!r} vector_space_id drifted from the pin"
            )


def assert_input_hashes_match(
    result: EmbeddingGenerationResult | Mapping[str, EmbeddingRecord],
    chunks: Sequence[AdmittedChunk | Mapping[str, Any] | LegalTextChunk],
    *,
    config: StateLawsEmbeddingConfig | None = None,
) -> None:
    """Fail closed when stored input hashes no longer match current text."""

    pin = config or default_embedding_config()
    embeddings = (
        result.embeddings if isinstance(result, EmbeddingGenerationResult) else result
    )
    admitted = coerce_state_law_chunks(chunks)
    by_cid = {chunk.chunk_cid: chunk for chunk in admitted}
    for cid, record in embeddings.items():
        chunk = by_cid.get(cid)
        if chunk is None:
            raise OrphanVectorError(f"orphan embedding key {cid!r} is not admitted")
        expected = input_content_hash(_chunk_input_text(chunk, input_fields=pin.input_fields))
        if record.input_hash != expected:
            raise InputHashDriftError(
                f"input hash changed for chunk {cid!r}: "
                f"stored={record.input_hash} current={expected}"
            )


def assert_embedding_conservation(
    result: EmbeddingGenerationResult,
    *,
    expected_chunks: Sequence[AdmittedChunk] | None = None,
    expected_chunk_cids: Sequence[str] | None = None,
    config: StateLawsEmbeddingConfig | None = None,
) -> None:
    """Prove one finite non-zero 384-d L2-normalized vector per expected chunk."""

    pin = config or default_embedding_config()
    if expected_chunks is not None:
        expected = [chunk.chunk_cid for chunk in expected_chunks]
        chunk_by_cid = {chunk.chunk_cid: chunk for chunk in expected_chunks}
    elif expected_chunk_cids is not None:
        expected = list(expected_chunk_cids)
        chunk_by_cid = {}
    else:
        expected = list(result.admitted_chunk_cids)
        chunk_by_cid = {}
    if len(expected) != len(set(expected)):
        raise DuplicateVectorError("expected chunk_cids are not unique")
    keys = list(result.embeddings)
    if len(keys) != len(set(keys)):
        raise DuplicateVectorError("embedding keys are not unique")
    extra = sorted(set(keys) - set(expected))
    missing = sorted(set(expected) - set(keys))
    if extra:
        raise OrphanVectorError(
            f"orphan embedding keys not in admitted set: {extra!r}"
        )
    if missing:
        raise VectorCoverageError(f"missing vectors for admitted chunks: {missing!r}")
    if sorted(keys) != sorted(expected):
        raise VectorCoverageError(
            f"embedding keys differ; extra={extra!r} missing={missing!r}"
        )
    if result.missing:
        raise VectorCoverageError(
            f"missing vectors: {[item.chunk_cid for item in result.missing]!r}"
        )
    assert_records_match_pin(result.embeddings, config=pin)
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
        measured = l2_norm(record.embedding)
        if measured <= 0.0:
            raise ZeroVectorError(f"{cid!r} embedding is the zero vector")
        validate_vector_norm(
            record.embedding,
            normalization=PINNED_NORMALIZATION,
            name=f"embedding[{cid}]",
        )
        require_pinned_gte_small(
            model_id=record.model_id, model_revision=record.model_revision
        )
        chunk = chunk_by_cid.get(cid)
        if chunk is not None:
            expected_hash = input_content_hash(
                _chunk_input_text(chunk, input_fields=pin.input_fields)
            )
            if record.input_hash != expected_hash:
                raise InputHashDriftError(
                    f"input hash changed for chunk {cid!r}"
                )


def bind_state_laws_embeddings(
    chunks: Sequence[AdmittedChunk | LegalTextChunk | Mapping[str, Any]]
    | Iterable[AdmittedChunk | LegalTextChunk | Mapping[str, Any]],
    *,
    config: StateLawsEmbeddingConfig | None = None,
    embedder: EmbeddingFunction | None = None,
) -> StateLawsEmbeddingBinding:
    """Generate embeddings and bind input receipts for admitted chunks."""

    pin = config or default_embedding_config()
    source = list(chunks)
    result = generate_state_laws_embeddings(source, config=pin, embedder=embedder)
    receipts = tuple(
        InputReceipt(
            chunk_cid=record.chunk_cid,
            entry_cid=record.entry_cid,
            input_hash=record.input_hash,
            model_id=record.model_id,
            model_revision=record.model_revision,
            pooling=record.pooling,
            normalization=record.normalization,
            dimension=record.dimension,
            vector_space_id=record.vector_space_id,
        )
        for record in result.embeddings.values()
    )
    return StateLawsEmbeddingBinding(
        embeddings=result.embeddings,
        config=pin,
        admitted_chunk_cids=result.admitted_chunk_cids,
        corpus_root_cid=build_corpus_root_cid(source),
        input_receipts=receipts,
        generation=result,
    )


def bind_fixture_embeddings(
    chunks: Sequence[Mapping[str, Any]] | None = None,
) -> StateLawsEmbeddingBinding:
    """Bind the compact fixture recipe with the sealed projection backend."""

    rows = list(chunks) if chunks is not None else fixture_embedding_chunks()
    return bind_state_laws_embeddings(rows, config=fixture_embedding_config())


# ---------------------------------------------------------------------------
# Compact fixture recipe
# ---------------------------------------------------------------------------


def fixture_embedding_chunks() -> list[dict[str, Any]]:
    """Compact admitted state-law chunk sample for sealed unit fixtures."""

    return [
        {
            "chunk_cid": _cid("a"),
            "parent_entry_cid": _cid("b"),
            "entry_cid": _cid("b"),
            "chunk_id": "or:174:010#chunk=0000",
            "legal_id": "sl:or:174:010",
            "jurisdiction_code": "OR",
            "heading": "General rule for construction of statutes",
            "title": "174",
            "section": "010",
            "text": (
                "In the construction of a statute, the office of the judge is "
                "simply to ascertain and declare what is contained therein. "
                "Unique token oregonconstruction. The statute is a public "
                "records construction rule."
            ),
            "disposition": "admitted",
        },
        {
            "chunk_cid": _cid("c"),
            "parent_entry_cid": _cid("d"),
            "entry_cid": _cid("d"),
            "chunk_id": "ca:1:1#chunk=0000",
            "legal_id": "sl:ca:1:1",
            "jurisdiction_code": "CA",
            "heading": "Title of act",
            "title": "1",
            "section": "1",
            "text": (
                "This act shall be known as the Civil Code of the State of "
                "California. Unique token californiaevidence. The statute "
                "governs civil obligations and public records construction."
            ),
            "disposition": "admitted",
        },
        {
            "chunk_cid": _cid("e"),
            "parent_entry_cid": _cid("0"),
            "entry_cid": _cid("0"),
            "chunk_id": "dc:2:531#chunk=0000",
            "legal_id": "sl:dc:2:531",
            "jurisdiction_code": "DC",
            "heading": "Open meetings",
            "title": "2",
            "section": "531",
            "text": (
                "All meetings of public bodies shall be open to the public. "
                "Unique token dcopenmeetings. The statute requires notice "
                "and is a public records open-meetings law."
            ),
            "disposition": "admitted",
        },
        {
            "chunk_cid": _cid("1"),
            "parent_entry_cid": _cid("2"),
            "entry_cid": _cid("2"),
            "chunk_id": "ny:5:86#chunk=0000",
            "legal_id": "sl:ny:5:86",
            "jurisdiction_code": "NY",
            "heading": "Definitions",
            "title": "5",
            "section": "86",
            "text": (
                "As used in this article, agency means any state or municipal "
                "department, board, bureau, or public body. Unique token "
                "newyorkfoil. The statute defines public records."
            ),
            "disposition": "admitted",
        },
        {
            "chunk_cid": _cid("3"),
            "parent_entry_cid": _cid("4"),
            "entry_cid": _cid("4"),
            "chunk_id": "tx:552:001#chunk=0000",
            "legal_id": "sl:tx:552:001",
            "jurisdiction_code": "TX",
            "heading": "Policy; construction",
            "title": "552",
            "section": "001",
            "text": (
                "Under the fundamental philosophy of representative government, "
                "each person is entitled to complete information about the "
                "affairs of government. Unique token texaspublicinfo. The "
                "statute declares a public information policy."
            ),
            "disposition": "admitted",
        },
        {
            "chunk_cid": _cid("5"),
            "parent_entry_cid": _cid("6"),
            "entry_cid": _cid("6"),
            "chunk_id": "il:5:140:1#chunk=0000",
            "legal_id": "sl:il:5:140:1",
            "jurisdiction_code": "IL",
            "heading": "Public policy",
            "title": "5",
            "section": "1",
            "text": (
                "It is declared to be the public policy of the State of "
                "Illinois that all persons are entitled to full and complete "
                "information. Unique token illinoisfia. The statute is a "
                "public records law."
            ),
            "disposition": "admitted",
        },
        {
            "chunk_cid": _cid("7"),
            "parent_entry_cid": _cid("8"),
            "entry_cid": _cid("8"),
            "chunk_id": "fl:119:01#chunk=0000",
            "legal_id": "sl:fl:119:01",
            "jurisdiction_code": "FL",
            "heading": "General state policy on public records",
            "title": "119",
            "section": "01",
            "text": (
                "It is the policy of this state that all state, county, and "
                "municipal records are open for personal inspection. Unique "
                "token floridasunshine. The statute is a public records act."
            ),
            "disposition": "admitted",
        },
        {
            "chunk_cid": _cid("9"),
            "parent_entry_cid": _cid("aa"),
            "entry_cid": _cid("aa"),
            "chunk_id": "wa:42:56:030#chunk=0000",
            "legal_id": "sl:wa:42:56:030",
            "jurisdiction_code": "WA",
            "heading": "Findings",
            "title": "42",
            "section": "030",
            "text": (
                "The people of this state do not yield their sovereignty to "
                "the agencies that serve them. Unique token washingtonpra. "
                "The statute favors disclosure of public records."
            ),
            "disposition": "admitted",
        },
        {
            "entry_cid": "",
            "chunk_cid": "",
            "row_id": "recovery-src-01",
            "disposition": "quarantined",
            "is_recovery": True,
            "text": "workflow recovery payload must not enter embeddings",
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
        for row in fixture_embedding_chunks()
        if str(row.get("disposition") or "admitted").lower() == "admitted"
        and not row.get("is_recovery")
        and row.get("chunk_cid")
    ]


# ---------------------------------------------------------------------------
# Receipt
# ---------------------------------------------------------------------------


def default_embedding_receipt_path(repo_root: PathLike | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else _REPO_ROOT
    return (root / REPORT_RELATIVE_PATH).resolve()


def _acceptance_block() -> dict[str, Any]:
    return {
        "criteria": (
            "Embedding key set equals admitted searchable chunk key set "
            "exactly with no zero, duplicate, orphan, NaN, wrong-dimension, "
            "stale-model, or changed-input vector."
        ),
        "hub_upload": False,
        "keys_equal_admitted_searchable_chunks": True,
        "l2_normalized": True,
        "mean_pooling": True,
        "no_stale_model_or_changed_input": True,
        "no_zero_duplicate_orphan_nan": True,
        "pinned_thenlper_gte_small": True,
        "projection_cannot_authorize_publication": True,
        "secrets_absent": True,
        "vector_dimension_384": True,
    }


def build_embedding_receipt(
    *,
    binding: StateLawsEmbeddingBinding | None = None,
    rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the sealed, secret-free LCR-028 embedding receipt."""

    source_rows = list(rows) if rows is not None else fixture_embedding_chunks()
    demo = binding if binding is not None else bind_fixture_embeddings(source_rows)
    admitted = admitted_fixture_chunks() if rows is None else [
        row
        for row in source_rows
        if str(row.get("disposition") or "admitted").lower() == "admitted"
        and not row.get("is_recovery")
        and row.get("chunk_cid")
    ]
    pin = demo.config
    production = production_embedding_config()
    input_hashes = {
        cid: rec.input_hash for cid, rec in sorted(demo.embeddings.items())
    }
    payload: dict[str, Any] = {
        "acceptance": _acceptance_block(),
        "adr_path": ADR_PATH,
        "admitted": {
            "chunk_count": len(admitted),
            "corpus_root_cid": demo.corpus_root_cid,
            "vector_count": demo.vector_count,
        },
        "authorizing_for_publication": False,
        "authorizing_for_release": False,
        "authorizing_hub_upload": False,
        "backend": {
            "default": DEFAULT_BACKEND,
            "production": PRODUCTION_BACKEND,
            "projection": PROJECTION_BACKEND,
            "projection_authorizes_publication": False,
            "provider": DEFAULT_PROVIDER,
        },
        "board_namespace": BOARD_NAMESPACE,
        "bundle": BUNDLE,
        "checks": {
            "admitted_chunk_count": len(admitted),
            "default_backend_is_projection": DEFAULT_BACKEND == PROJECTION_BACKEND,
            "demo_backend": demo.config.backend,
            "demo_vector_count": demo.vector_count,
            "every_admitted_chunk_embedded": demo.vector_count == len(admitted),
            "input_hashes_present": all(input_hashes.values()),
            "keys_match_admitted": sorted(demo.vector_keys)
            == sorted(row["chunk_cid"] for row in admitted),
            "no_hub_upload": True,
            "no_nan_or_zero": True,
            "no_stale_model": True,
            "pinned_dimension": PINNED_DIMENSION,
            "pinned_max_tokens": PINNED_MAX_TOKENS,
            "pinned_model_id": PINNED_MODEL_ID,
            "pinned_model_revision": PINNED_MODEL_REVISION,
            "pinned_normalization": PINNED_NORMALIZATION,
            "pinned_pooling": PINNED_POOLING,
            "production_backend": production.backend,
            "production_still_binds_gte_small": production.model_id == PINNED_MODEL_ID
            and production.model_revision == PINNED_MODEL_REVISION,
            "projection_cannot_authorize_publication": True,
            "recovery_excluded_from_embeddings": True,
            "secrets_absent": True,
            "unit_norms": all(
                abs(rec.l2_norm - 1.0) <= NORM_TOLERANCE
                for rec in demo.embeddings.values()
            ),
        },
        "code_version": CODE_VERSION,
        "config": pin.to_dict(),
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "demo": {
            "admitted_chunk_cids": list(demo.admitted_chunk_cids),
            "authorizing_for_publication": False,
            "backend": demo.config.backend,
            "chunk_cids": list(demo.vector_keys),
            "config_digest": pin.digest,
            "corpus_root_cid": demo.corpus_root_cid,
            "input_hashes": input_hashes,
            "vector_count": demo.vector_count,
            "vector_space_id": pin.vector_space_id,
        },
        "depends_on": [CORPUS_TASK_ID, CHUNKER_TASK_ID, ADAPTER_TASK_ID],
        "description": (
            "LCR-028 state-law embeddings in one pinned legal vector space. "
            "Every admitted searchable chunk is embedded with thenlper/gte-small "
            f"at revision {PINNED_MODEL_REVISION}, 384 dimensions, mean pooling, "
            "and L2 normalization. Default offline backend is the sealed local "
            "hashed projection so tests never download sentence-transformers or "
            "torch. Projection output cannot authorize publication. Hermetic "
            "fixture evaluation only. Does not authorize Hub upload."
        ),
        "embedding_contract": {
            "dimension": PINNED_DIMENSION,
            "license": PINNED_MODEL_LICENSE,
            "max_tokens": PINNED_MAX_TOKENS,
            "model_id": PINNED_MODEL_ID,
            "model_revision": PINNED_MODEL_REVISION,
            "normalization": PINNED_NORMALIZATION,
            "pooling": PINNED_POOLING,
            "preprocessing": PREPROCESSING,
            "primary_key": PRIMARY_KEY,
            "vector_space_id": default_vector_space_id(),
        },
        "family_counts": {
            "chunks": len(admitted),
            "embeddings": demo.vector_count,
        },
        "goal_id": GOAL_ID,
        "hub_upload": False,
        "model_pin": {
            "dimension": PINNED_DIMENSION,
            "license": PINNED_MODEL_LICENSE,
            "max_tokens": PINNED_MAX_TOKENS,
            "model_id": PINNED_MODEL_ID,
            "model_revision": PINNED_MODEL_REVISION,
            "normalization": PINNED_NORMALIZATION,
            "pooling": PINNED_POOLING,
            "vector_space_id": default_vector_space_id(),
        },
        "network_required": False,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "projection_fallback_authorizes_release": False,
        "proves_software_contract_only": True,
        "release_profile": RELEASE_PROFILE,
        "report_kind": "fixture_embeddings",
        "schema": REPORT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "secrets_absent": True,
        "task_id": TASK_ID,
    }
    compact = dict(payload)
    assert_no_secrets_or_home_paths(compact)
    blob = json.dumps(compact, sort_keys=True)
    if "/home/" in blob or "/Users/" in blob:
        raise EmbeddingReceiptError("embedding receipt contains an absolute home path")
    compact["report_digest_sha256"] = digest_mapping(
        {key: value for key, value in compact.items() if key != "report_digest_sha256"}
    )
    return compact


def write_embedding_receipt(
    path: PathLike | None = None,
    *,
    binding: StateLawsEmbeddingBinding | None = None,
) -> Path:
    target = Path(path) if path is not None else default_embedding_receipt_path()
    payload = build_embedding_receipt(binding=binding)
    write_json_atomic(target, payload)
    return target


def load_embedding_receipt(path: PathLike | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else default_embedding_receipt_path()
    if not target.is_file():
        raise EmbeddingReceiptError(f"embedding receipt not found: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise EmbeddingReceiptError("embedding receipt root must be an object")
    return dict(payload)


def assert_embedding_receipt(payload: Mapping[str, Any]) -> None:
    """Fail closed if the receipt would authorize release or weaken the contract."""

    if payload.get("task_id") != TASK_ID:
        raise EmbeddingReceiptError(f"receipt task_id must be {TASK_ID!r}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise EmbeddingReceiptError(
            f"receipt schema_version must be {SCHEMA_VERSION!r}"
        )
    if payload.get("schema") != REPORT_SCHEMA:
        raise EmbeddingReceiptError(f"receipt schema must be {REPORT_SCHEMA!r}")
    if payload.get("authorizing_hub_upload") is True:
        raise EmbeddingReleaseAuthorizationError(
            "embedding receipt cannot authorize Hub upload"
        )
    if payload.get("authorizing_for_publication") is True:
        raise EmbeddingReleaseAuthorizationError(
            "embedding receipt cannot authorize publication"
        )
    if payload.get("hub_upload") is True:
        raise EmbeddingReleaseAuthorizationError(
            "embedding receipt cannot claim Hub upload"
        )
    if payload.get("projection_fallback_authorizes_release") is True:
        raise EmbeddingReleaseAuthorizationError(
            "projection fallback cannot authorize release"
        )
    acceptance = payload.get("acceptance") or {}
    if not isinstance(acceptance, Mapping):
        raise EmbeddingReceiptError("receipt acceptance must be a mapping")
    if acceptance.get("hub_upload") is not False:
        raise EmbeddingReceiptError("receipt must not claim Hub upload")
    if acceptance.get("keys_equal_admitted_searchable_chunks") is not True:
        raise EmbeddingReceiptError("receipt must prove keys equal admitted chunks")
    if acceptance.get("vector_dimension_384") is not True:
        raise EmbeddingReceiptError("receipt must prove 384-d vectors")
    if acceptance.get("l2_normalized") is not True:
        raise EmbeddingReceiptError("receipt must prove L2 normalization")
    if acceptance.get("mean_pooling") is not True:
        raise EmbeddingReceiptError("receipt must prove mean pooling")
    if acceptance.get("pinned_thenlper_gte_small") is not True:
        raise EmbeddingReceiptError("receipt must prove the GTE-small pin")
    if acceptance.get("no_zero_duplicate_orphan_nan") is not True:
        raise EmbeddingReceiptError(
            "receipt must prove no zero/duplicate/orphan/NaN vectors"
        )
    if acceptance.get("no_stale_model_or_changed_input") is not True:
        raise EmbeddingReceiptError(
            "receipt must prove no stale-model or changed-input vectors"
        )
    if acceptance.get("secrets_absent") is not True:
        raise EmbeddingReceiptError("receipt must prove secrets are absent")
    if acceptance.get("projection_cannot_authorize_publication") is not True:
        raise EmbeddingReceiptError(
            "receipt must prove projection cannot authorize publication"
        )
    if payload.get("secrets_absent") is not True:
        raise EmbeddingReceiptError("receipt secrets_absent must be true")
    pin = payload.get("model_pin") or payload.get("embedding_contract") or {}
    if not isinstance(pin, Mapping):
        raise EmbeddingReceiptError("receipt model_pin must be a mapping")
    if pin.get("model_id") != PINNED_MODEL_ID:
        raise EmbeddingReceiptError("receipt model_id is not the sealed GTE-small pin")
    if pin.get("model_revision") != PINNED_MODEL_REVISION:
        raise EmbeddingReceiptError(
            "receipt model_revision is not the sealed GTE-small pin"
        )
    if pin.get("dimension") != PINNED_DIMENSION:
        raise EmbeddingReceiptError("receipt dimension must be 384")
    if pin.get("pooling") != PINNED_POOLING:
        raise EmbeddingReceiptError("receipt pooling is not mean")
    if pin.get("normalization") != PINNED_NORMALIZATION:
        raise EmbeddingReceiptError("receipt normalization is not l2")
    backend = payload.get("backend") or {}
    if isinstance(backend, Mapping):
        if backend.get("default") != PROJECTION_BACKEND:
            raise EmbeddingReceiptError(
                "receipt default backend must be the sealed hashed projection"
            )
        if backend.get("projection_authorizes_publication") is True:
            raise EmbeddingReleaseAuthorizationError(
                "projection backend cannot authorize publication"
            )
    blob = json.dumps(dict(payload), sort_keys=True)
    if "/home/" in blob or "/Users/" in blob:
        raise EmbeddingReceiptError("embedding receipt contains an absolute home path")
    assert_no_secrets_or_home_paths(payload)


def check_embedding_receipt(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a receipt object against sealed LCR-028 acceptance."""

    assert_embedding_receipt(payload)
    admitted = payload.get("admitted") or {}
    return {
        "ok": True,
        "task_id": TASK_ID,
        "vector_count": admitted.get("vector_count"),
        "chunk_count": admitted.get("chunk_count"),
        "hub_upload": False,
        "authorizing_for_publication": False,
        "secrets_absent": True,
    }


def check_receipt_matches_fixture(
    on_disk: Mapping[str, Any],
    fixture_report: Mapping[str, Any],
) -> None:
    """Ensure frozen receipt acceptance matches the live fixture evaluation."""

    for key in ("task_id", "schema_version", "schema", "goal_id"):
        if on_disk.get(key) != fixture_report.get(key):
            raise EmbeddingEvaluationError(
                f"on-disk {key} diverges from fixture: "
                f"disk={on_disk.get(key)!r} fixture={fixture_report.get(key)!r}"
            )
    disk_acc = on_disk.get("acceptance") or {}
    fix_acc = fixture_report.get("acceptance") or {}
    for key in (
        "keys_equal_admitted_searchable_chunks",
        "vector_dimension_384",
        "l2_normalized",
        "mean_pooling",
        "pinned_thenlper_gte_small",
        "no_zero_duplicate_orphan_nan",
        "no_stale_model_or_changed_input",
        "secrets_absent",
        "hub_upload",
        "projection_cannot_authorize_publication",
    ):
        if disk_acc.get(key) != fix_acc.get(key):
            raise EmbeddingEvaluationError(
                f"on-disk acceptance[{key!r}] diverges from fixture: "
                f"disk={disk_acc.get(key)!r} fixture={fix_acc.get(key)!r}"
            )
    disk_admitted = on_disk.get("admitted") or {}
    fix_admitted = fixture_report.get("admitted") or {}
    for key in ("chunk_count", "vector_count"):
        if disk_admitted.get(key) != fix_admitted.get(key):
            raise EmbeddingEvaluationError(
                f"on-disk admitted[{key!r}] diverges from fixture: "
                f"disk={disk_admitted.get(key)!r} fixture={fix_admitted.get(key)!r}"
            )


__all__ = [
    "ADAPTER_TASK_ID",
    "AUTHORIZES_HUB_UPLOAD",
    "AUTHORIZES_PUBLICATION",
    "CHUNKER_TASK_ID",
    "CORPUS_TASK_ID",
    "DEFAULT_BACKEND",
    "GOAL_ID",
    "NORM_TOLERANCE",
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
    "DuplicateVectorError",
    "EmbeddingConfigError",
    "EmbeddingEvaluationError",
    "EmbeddingReceiptError",
    "EmbeddingReleaseAuthorizationError",
    "InputHashDriftError",
    "InputReceipt",
    "OrphanVectorError",
    "StaleModelError",
    "StateLawsEmbeddingBinding",
    "StateLawsEmbeddingConfig",
    "StateLawsEmbeddingError",
    "UnpinnedModelError",
    "VectorCoverageError",
    "ZeroVectorError",
    "admitted_fixture_chunks",
    "assert_embedding_conservation",
    "assert_embedding_receipt",
    "assert_input_hashes_match",
    "assert_records_match_pin",
    "bind_fixture_embeddings",
    "bind_state_laws_embeddings",
    "build_corpus_root_cid",
    "build_embedding_receipt",
    "check_embedding_receipt",
    "check_receipt_matches_fixture",
    "chunks_from_legal_text_chunks",
    "coerce_state_law_chunks",
    "default_embedding_config",
    "default_embedding_receipt_path",
    "default_vector_space_id",
    "deterministic_project",
    "fixture_embedding_chunks",
    "fixture_embedding_config",
    "generate_state_laws_embeddings",
    "input_content_hash",
    "is_production_backend",
    "is_projection_backend",
    "l2_norm",
    "l2_normalize",
    "load_embedding_receipt",
    "normalize_embedding_text",
    "production_embedding_config",
    "projection_cannot_authorize_publication",
    "require_pinned_gte_small",
    "validate_vector_dimension",
    "validate_vector_norm",
    "write_embedding_receipt",
]


if __name__ == "__main__":
    written = write_embedding_receipt()
    payload = load_embedding_receipt(written)
    print(
        f"wrote {REPORT_RELATIVE_PATH.as_posix()} "
        f"admitted_vectors={payload['admitted']['vector_count']}"
    )
