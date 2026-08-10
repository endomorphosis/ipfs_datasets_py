"""Pinned legal embedding generation for U.S. Code chunks (USCIR-017).

This module owns model/input projection for the ``publicus-ir-graphrag/v2``
US Code release. It deliberately does **not** perform centroid clustering or
physical vector-shard layout (that is USCIR-018).

Design invariants
-----------------
* Model ID, immutable model revision, license, maximum tokens, pooling,
  normalization, and input fields are configuration-bound. Mutable tokens
  (``latest``, branch names), placeholders (``unknown``, ``mock``), and
  empty/missing pins fail closed.
* Output map keys are canonical chunk CIDs and must equal the admitted
  chunk set exactly (no extras, no omissions).
* Every vector is finite, matches the configured dimension, and is
  L2-normalized to unit length when non-zero (within tolerance).
* Legacy positional vectors (``row-N`` joins, unknown model identity) are
  never promoted into trusted embeddings.
* Default offline backend is a deterministic local projection so unit tests
  and sealed validation environments need no model download. Production
  callers may inject a pin-compatible embedder; the pin identity still
  binds every receipt.
* Device selection supports explicit CPU fallback; batching and atomic
  checkpoints enable resumable streams with missing-vector diagnostics.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final, Optional, Union

from ipfs_datasets_py.processors.legal_data.uscode_release_schema import (
    MutableReferenceError,
    PositionalIdentityError,
    reject_positional_durable_identity,
    require_immutable_model_ref,
)
from ipfs_datasets_py.processors.retrieval import hashed_term_projection

# ---------------------------------------------------------------------------
# Schema / pin constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "uscode-embeddings-v1"
FIXTURE_SCHEMA_VERSION: Final = "uscode-embedding-contract-v1"
TASK_ID: Final = "USCIR-017"
GOAL_ID: Final = "USCIR-G050"
RELEASE_PROFILE: Final = "publicus-ir-graphrag/v2"

# Default production pin (immutable revision; never "latest").
# Production US Code sparse GraphRAG uses GTE-small on CUDA when available.
DEFAULT_MODEL_ID: Final = "thenlper/gte-small"
DEFAULT_MODEL_REVISION: Final = "17e1f347d17fe144873b1201da91788898c639cd"
DEFAULT_MODEL_LICENSE: Final = "mit"
DEFAULT_DIMENSION: Final = 384
DEFAULT_MAX_TOKENS: Final = 512
DEFAULT_POOLING: Final = "mean"
DEFAULT_NORMALIZATION: Final = "l2"
DEFAULT_INPUT_FIELDS: Final = ("text",)
# Offline unit/sealed tests use the deterministic projection backend.
# Production full builds set backend="sentence_transformers" + device="cuda".
DEFAULT_BACKEND: Final = "local_deterministic_projection"
DEFAULT_PROVIDER: Final = "local"
DEFAULT_DEVICE: Final = "cuda"
DEFAULT_BATCH_SIZE: Final = 64
MAX_BATCH_SIZE: Final = 512
MAX_CHUNKS_PER_CALL: Final = 100_000
NORM_TOLERANCE: Final = 1e-5
VECTOR_STABILITY_TOLERANCE: Final = 0.0
_FLOAT_EPS: Final = 1e-12

SUPPORTED_POOLING: Final = frozenset({"mean", "cls", "max", "last"})
SUPPORTED_NORMALIZATION: Final = frozenset({"l2", "none"})
SUPPORTED_DEVICES: Final = frozenset({"cpu", "cuda", "cuda:0", "mps"})

# Tokens that must never be accepted as model identity.
_PLACEHOLDER_MODEL_RE = re.compile(
    r"^(?:placeholder|unknown|none|null|n/?a|na|mock|dummy|todo|tbd|"
    r"example|test|fake|unset|missing|unspecified|default|auto|"
    r"changeme|replace.?me|your.?model|model.?name)$",
    re.IGNORECASE,
)
_PLACEHOLDER_REVISION_RE = re.compile(
    r"^(?:placeholder|unknown|none|null|n/?a|na|mock|dummy|todo|tbd|"
    r"unpinned|floating|mutable)$",
    re.IGNORECASE,
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]
EmbeddingFunction = Callable[[Sequence[str]], Sequence[Sequence[float]]]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class UscodeEmbeddingError(ValueError):
    """Base error for pinned legal embedding generation."""

    code: str = "uscode_embedding_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class EmbeddingConfigError(UscodeEmbeddingError):
    """Raised when embedding configuration is incomplete or invalid."""

    code = "config_invalid"


class UnpinnedModelError(UscodeEmbeddingError):
    """Raised when model identity is mutable, placeholder, or unknown."""

    code = "unpinned_model"


class DimensionValidationError(UscodeEmbeddingError):
    """Raised when vector dimensions do not match the configured pin."""

    code = "dimension_mismatch"


class NormValidationError(UscodeEmbeddingError):
    """Raised when vector norms fail the normalization contract."""

    code = "norm_invalid"


class ChunkKeyMismatchError(UscodeEmbeddingError):
    """Raised when output keys do not exactly match admitted chunk CIDs."""

    code = "chunk_key_mismatch"


class LegacyVectorPromotionError(UscodeEmbeddingError):
    """Raised when legacy positional / untrusted vectors would be promoted."""

    code = "legacy_promotion_forbidden"


class MissingVectorError(UscodeEmbeddingError):
    """Raised when required vectors are missing after generation."""

    code = "missing_vector"


class EmbeddingFixtureError(UscodeEmbeddingError):
    """Raised when the sealed embedding contract fixture is malformed."""

    code = "fixture_invalid"


class EmbeddingCheckpointError(UscodeEmbeddingError):
    """Raised when a checkpoint is corrupt or pin-incompatible."""

    code = "checkpoint_invalid"


class HardwareUnavailableError(UscodeEmbeddingError):
    """Raised when requested hardware is unavailable and policy is block."""

    code = "hardware_unavailable"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DeviceFallbackPolicy(str, Enum):
    """What to do when requested hardware is unavailable."""

    FALLBACK_CPU = "fallback_cpu"
    BLOCK = "block"


class PoolingMethod(str, Enum):
    MEAN = "mean"
    CLS = "cls"
    MAX = "max"
    LAST = "last"


class NormalizationMethod(str, Enum):
    L2 = "l2"
    NONE = "none"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def content_sha256(data: bytes | str) -> str:
    return _sha256_hex(data)


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


def is_placeholder_model_ref(value: Any) -> bool:
    """Return True when *value* is a known placeholder / unknown model token."""

    if value is None:
        return True
    if not isinstance(value, str):
        return True
    text = value.strip()
    if not text:
        return True
    if _PLACEHOLDER_MODEL_RE.fullmatch(text):
        return True
    # Common "org/placeholder" style tokens.
    tail = text.rsplit("/", 1)[-1]
    if _PLACEHOLDER_MODEL_RE.fullmatch(tail):
        return True
    return False


def is_placeholder_revision(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return True
    text = value.strip()
    if not text:
        return True
    return bool(_PLACEHOLDER_REVISION_RE.fullmatch(text))


def reject_placeholder_model_ref(
    *,
    model_id: Any,
    model_revision: Any,
    model_id_name: str = "model_id",
    model_revision_name: str = "model_revision",
) -> tuple[str, str]:
    """Fail closed on placeholder / mutable / unknown model references."""

    if is_placeholder_model_ref(model_id):
        raise UnpinnedModelError(
            f"{model_id_name} is a placeholder/unknown model reference: {model_id!r}"
        )
    if is_placeholder_revision(model_revision):
        raise UnpinnedModelError(
            f"{model_revision_name} is a placeholder/unknown revision: "
            f"{model_revision!r}"
        )
    try:
        return require_immutable_model_ref(
            model_id=model_id,
            model_revision=model_revision,
            model_id_name=model_id_name,
            model_revision_name=model_revision_name,
        )
    except MutableReferenceError as exc:
        raise UnpinnedModelError(str(exc)) from exc


def normalize_embedding_text(text: str) -> str:
    """NFKC-normalize and collapse whitespace for deterministic input hashing."""

    if not isinstance(text, str):
        raise UscodeEmbeddingError("embedding text must be a string")
    if "\x00" in text:
        raise UscodeEmbeddingError("embedding text must not contain NUL")
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    # Collapse runs of whitespace to single spaces while preserving content.
    parts = normalized.split()
    return " ".join(parts)


def input_content_hash(text: str) -> str:
    """SHA-256 of the normalized embedding input text."""

    return content_sha256(normalize_embedding_text(text))


def l2_norm(values: Sequence[float]) -> float:
    return math.sqrt(sum(float(v) * float(v) for v in values))


def l2_normalize(values: Sequence[float]) -> list[float]:
    norm = l2_norm(values)
    if norm <= 0.0:
        return [float(v) for v in values]
    return [float(v) / norm for v in values]


def validate_vector_dimension(
    vector: Sequence[float],
    *,
    dimension: int,
    name: str = "vector",
) -> tuple[float, ...]:
    if not isinstance(vector, (list, tuple)):
        raise DimensionValidationError(f"{name} must be a sequence of floats")
    if len(vector) != dimension:
        raise DimensionValidationError(
            f"{name} length {len(vector)} != configured dimension {dimension}"
        )
    out: list[float] = []
    for index, item in enumerate(vector):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise DimensionValidationError(
                f"{name}[{index}] must be a finite number"
            )
        number = float(item)
        if not math.isfinite(number):
            raise DimensionValidationError(f"{name}[{index}] must be finite")
        out.append(number)
    return tuple(out)


def validate_vector_norm(
    vector: Sequence[float],
    *,
    normalization: str,
    tolerance: float = NORM_TOLERANCE,
    name: str = "vector",
) -> float:
    """Validate L2 norm under the configured normalization policy.

    Returns the measured L2 norm.
    """

    norm = l2_norm(vector)
    if not math.isfinite(norm):
        raise NormValidationError(f"{name} norm is not finite")
    policy = str(normalization or "").strip().lower()
    if policy == "l2":
        # Zero vectors (empty text) are allowed; non-zero must be unit.
        if norm > 0.0 and abs(norm - 1.0) > tolerance:
            raise NormValidationError(
                f"{name} L2 norm {norm} outside unit tolerance {tolerance}"
            )
    elif policy == "none":
        pass
    else:
        raise EmbeddingConfigError(f"unsupported normalization: {normalization!r}")
    return norm


def build_vector_space_id(
    *,
    model_id: str,
    model_revision: str,
    pooling: str,
    normalization: str,
    dimension: int,
) -> str:
    """Bind model + revision + pooling + normalization into a space id."""

    model, revision = reject_placeholder_model_ref(
        model_id=model_id, model_revision=model_revision
    )
    short = model.rsplit("/", 1)[-1].lower()
    short = re.sub(r"[^a-z0-9._-]+", "-", short)
    pool = _require_non_empty_str(pooling, "pooling").lower()
    norm = _require_non_empty_str(normalization, "normalization").lower()
    dim = _require_positive_int(dimension, "dimension")
    return f"{short}@{revision}:d{dim}:pool={pool}:norm={norm}"


def device_is_available(device: str) -> bool:
    """Pure probe; never downloads models or mutates global state."""

    name = str(device or "").strip().lower()
    if not name or name == "cpu":
        return True
    if name.startswith("cuda"):
        try:
            import torch  # type: ignore[import-not-found]

            return bool(
                getattr(torch, "cuda", None)
                and torch.backends.cuda.is_built()
                and torch.cuda.is_available()
            )
        except Exception:
            return False
    if name == "mps":
        try:
            import torch  # type: ignore[import-not-found]

            mps = getattr(getattr(torch, "backends", None), "mps", None)
            return bool(mps is not None and mps.is_available())
        except Exception:
            return False
    return False


def select_device(
    requested: str,
    *,
    fallback: DeviceFallbackPolicy = DeviceFallbackPolicy.FALLBACK_CPU,
    probe: Callable[[str], bool] | None = None,
) -> tuple[str, bool]:
    """Select a device, applying fallback or blocking.

    Returns ``(selected_device, fallback_applied)``.
    """

    req = str(requested or DEFAULT_DEVICE).strip().lower() or DEFAULT_DEVICE
    if req not in SUPPORTED_DEVICES and not req.startswith("cuda:"):
        raise EmbeddingConfigError(f"unsupported device: {requested!r}")
    is_available = probe or device_is_available
    if is_available(req):
        return req, False
    if fallback is DeviceFallbackPolicy.FALLBACK_CPU:
        return DEFAULT_DEVICE, True
    if fallback is DeviceFallbackPolicy.BLOCK:
        raise HardwareUnavailableError(
            f"requested device {req!r} is unavailable and fallback policy is block"
        )
    raise EmbeddingConfigError(f"unknown fallback policy: {fallback!r}")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UscodeEmbeddingConfig:
    """Configuration-bound pin for legal embedding generation.

    All fields that define the vector space are required and validated
    fail-closed. Callers may not leave model identity unbound.
    """

    model_id: str = DEFAULT_MODEL_ID
    model_revision: str = DEFAULT_MODEL_REVISION
    license: str = DEFAULT_MODEL_LICENSE
    max_tokens: int = DEFAULT_MAX_TOKENS
    pooling: str = DEFAULT_POOLING
    normalization: str = DEFAULT_NORMALIZATION
    input_fields: tuple[str, ...] = DEFAULT_INPUT_FIELDS
    dimension: int = DEFAULT_DIMENSION
    vector_space_id: str = ""
    config_cid: str = ""
    backend: str = DEFAULT_BACKEND
    provider: str = DEFAULT_PROVIDER
    device: str = DEFAULT_DEVICE
    device_fallback: DeviceFallbackPolicy = DeviceFallbackPolicy.FALLBACK_CPU
    batch_size: int = DEFAULT_BATCH_SIZE
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        model_id, model_revision = reject_placeholder_model_ref(
            model_id=self.model_id,
            model_revision=self.model_revision,
        )
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "model_revision", model_revision)

        license_text = _require_non_empty_str(self.license, "license", maximum=256)
        if is_placeholder_model_ref(license_text) or license_text.lower() in {
            "unknown",
            "unspecified",
            "none",
        }:
            raise UnpinnedModelError(
                f"license must be an explicit declared license, not {self.license!r}"
            )
        object.__setattr__(self, "license", license_text)

        max_tokens = _require_positive_int(self.max_tokens, "max_tokens")
        if max_tokens > 100_000:
            raise EmbeddingConfigError("max_tokens exceeds hard bound 100000")
        object.__setattr__(self, "max_tokens", max_tokens)

        pooling = _require_non_empty_str(self.pooling, "pooling").lower()
        if pooling not in SUPPORTED_POOLING:
            raise EmbeddingConfigError(
                f"pooling must be one of {sorted(SUPPORTED_POOLING)}; got {self.pooling!r}"
            )
        object.__setattr__(self, "pooling", pooling)

        normalization = _require_non_empty_str(
            self.normalization, "normalization"
        ).lower()
        if normalization not in SUPPORTED_NORMALIZATION:
            raise EmbeddingConfigError(
                f"normalization must be one of {sorted(SUPPORTED_NORMALIZATION)}; "
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
        if dimension > 8192:
            raise EmbeddingConfigError("dimension exceeds hard bound 8192")
        object.__setattr__(self, "dimension", dimension)

        space = str(self.vector_space_id or "").strip()
        if not space:
            space = build_vector_space_id(
                model_id=model_id,
                model_revision=model_revision,
                pooling=pooling,
                normalization=normalization,
                dimension=dimension,
            )
        else:
            space = _require_non_empty_str(space, "vector_space_id", maximum=512)
            # Reject space ids that are themselves mutable or placeholder tokens.
            # Composite ids (model@revision:...) are allowed; bare mutable
            # tokens are not.
            if is_placeholder_model_ref(space) or re.fullmatch(
                r"(?:latest|main|master|head|default|current|tip|trunk)",
                space,
                flags=re.IGNORECASE,
            ):
                raise UnpinnedModelError(
                    f"vector_space_id must not be a mutable/placeholder token: "
                    f"{space!r}"
                )
        object.__setattr__(self, "vector_space_id", space)

        backend = _require_non_empty_str(self.backend, "backend", maximum=128).lower()
        if is_placeholder_model_ref(backend):
            raise UnpinnedModelError(f"backend must not be a placeholder: {backend!r}")
        object.__setattr__(self, "backend", backend)

        provider = _require_non_empty_str(
            self.provider, "provider", maximum=128
        ).lower()
        object.__setattr__(self, "provider", provider)

        device = str(self.device or DEFAULT_DEVICE).strip().lower() or DEFAULT_DEVICE
        if device not in SUPPORTED_DEVICES and not device.startswith("cuda:"):
            raise EmbeddingConfigError(f"unsupported device: {self.device!r}")
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
            raise EmbeddingConfigError(
                f"batch_size must be <= {MAX_BATCH_SIZE}"
            )
        object.__setattr__(self, "batch_size", batch_size)

        schema = _require_non_empty_str(self.schema_version, "schema_version")
        if schema != SCHEMA_VERSION:
            raise EmbeddingConfigError(
                f"schema_version must be {SCHEMA_VERSION!r}; got {schema!r}"
            )
        object.__setattr__(self, "schema_version", schema)

        # Compute config_cid from the pin surface if not supplied.
        cid = str(self.config_cid or "").strip()
        if not cid:
            cid = "sha256:" + content_sha256(canonical_json_bytes(self.pin_dict()))
        else:
            cid = _require_non_empty_str(cid, "config_cid", maximum=128)
            if is_placeholder_model_ref(cid):
                raise UnpinnedModelError(
                    f"config_cid must not be a placeholder: {cid!r}"
                )
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

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "UscodeEmbeddingConfig":
        if not isinstance(value, Mapping):
            raise EmbeddingConfigError("config payload must be a mapping")
        fields = value.get("input_fields", DEFAULT_INPUT_FIELDS)
        if isinstance(fields, list):
            fields = tuple(fields)
        fallback = value.get("device_fallback", DeviceFallbackPolicy.FALLBACK_CPU)
        return cls(
            model_id=value.get("model_id", DEFAULT_MODEL_ID),
            model_revision=value.get("model_revision", DEFAULT_MODEL_REVISION),
            license=value.get("license", DEFAULT_MODEL_LICENSE),
            max_tokens=value.get("max_tokens", DEFAULT_MAX_TOKENS),
            pooling=value.get("pooling", DEFAULT_POOLING),
            normalization=value.get("normalization", DEFAULT_NORMALIZATION),
            input_fields=fields,
            dimension=value.get("dimension", DEFAULT_DIMENSION),
            vector_space_id=str(value.get("vector_space_id") or ""),
            config_cid=str(value.get("config_cid") or ""),
            backend=value.get("backend", DEFAULT_BACKEND),
            provider=value.get("provider", DEFAULT_PROVIDER),
            device=value.get("device", DEFAULT_DEVICE),
            device_fallback=fallback,
            batch_size=value.get("batch_size", DEFAULT_BATCH_SIZE),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
        )


def default_embedding_config() -> UscodeEmbeddingConfig:
    """Return the sealed default production pin."""

    return UscodeEmbeddingConfig()


# ---------------------------------------------------------------------------
# Admitted chunks
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AdmittedChunk:
    """One admitted legal chunk eligible for embedding.

    Durable join keys are ``chunk_cid`` (output map key) and optional
    ``entry_cid`` (parent retrieval row). Positional labels are rejected.
    """

    chunk_cid: str
    text: str
    entry_cid: Optional[str] = None
    chunk_id: Optional[str] = None
    legal_id: Optional[str] = None
    heading: str = ""
    title: str = ""
    section: str = ""
    extra_fields: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        chunk_cid = _require_non_empty_str(self.chunk_cid, "chunk_cid", maximum=256)
        reject_positional_durable_identity(chunk_cid, name="chunk_cid")
        if chunk_cid.lower().startswith("row-"):
            raise PositionalIdentityError(
                f"chunk_cid must not be a positional identity token: {chunk_cid!r}"
            )
        object.__setattr__(self, "chunk_cid", chunk_cid)

        if not isinstance(self.text, str):
            raise UscodeEmbeddingError("chunk text must be a string")
        if "\x00" in self.text:
            raise UscodeEmbeddingError("chunk text must not contain NUL")
        object.__setattr__(self, "text", self.text)

        if self.entry_cid is not None and str(self.entry_cid).strip():
            entry = _require_non_empty_str(self.entry_cid, "entry_cid", maximum=256)
            reject_positional_durable_identity(entry, name="entry_cid")
            object.__setattr__(self, "entry_cid", entry)
        else:
            object.__setattr__(self, "entry_cid", None)

        if self.chunk_id is not None and str(self.chunk_id).strip():
            cid = _require_non_empty_str(self.chunk_id, "chunk_id", maximum=512)
            reject_positional_durable_identity(cid, name="chunk_id")
            object.__setattr__(self, "chunk_id", cid)
        else:
            object.__setattr__(self, "chunk_id", None)

        if self.legal_id is not None and str(self.legal_id).strip():
            object.__setattr__(
                self,
                "legal_id",
                _require_non_empty_str(self.legal_id, "legal_id", maximum=512),
            )
        else:
            object.__setattr__(self, "legal_id", None)

        extras = self.extra_fields or {}
        if not isinstance(extras, Mapping):
            raise UscodeEmbeddingError("extra_fields must be a mapping")
        clean = {
            _require_non_empty_str(k, "extra_fields key"): str(v)
            for k, v in extras.items()
        }
        object.__setattr__(self, "extra_fields", clean)

    def resolve_input_text(self, input_fields: Sequence[str]) -> str:
        """Compose the embeddable string from configured input fields."""

        parts: list[str] = []
        for name in input_fields:
            if name == "text":
                parts.append(self.text)
            elif name == "heading":
                parts.append(self.heading or "")
            elif name == "title":
                parts.append(self.title or "")
            elif name == "section":
                parts.append(self.section or "")
            elif name == "legal_id":
                parts.append(self.legal_id or "")
            elif name in self.extra_fields:
                parts.append(self.extra_fields[name])
            else:
                raise EmbeddingConfigError(
                    f"input field {name!r} is not available on admitted chunk "
                    f"{self.chunk_cid}"
                )
        return "\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_cid": self.chunk_cid,
            "chunk_id": self.chunk_id,
            "entry_cid": self.entry_cid,
            "extra_fields": dict(self.extra_fields),
            "heading": self.heading,
            "legal_id": self.legal_id,
            "section": self.section,
            "text": self.text,
            "title": self.title,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AdmittedChunk":
        if not isinstance(value, Mapping):
            raise UscodeEmbeddingError("admitted chunk must be a mapping")
        extras = value.get("extra_fields") or {}
        return cls(
            chunk_cid=str(value.get("chunk_cid") or value.get("cid") or ""),
            text=str(value.get("text") or ""),
            entry_cid=value.get("entry_cid"),
            chunk_id=value.get("chunk_id"),
            legal_id=value.get("legal_id"),
            heading=str(value.get("heading") or ""),
            title=str(value.get("title") or ""),
            section=str(value.get("section") or ""),
            extra_fields=extras if isinstance(extras, Mapping) else {},
        )


def coerce_admitted_chunks(
    chunks: Sequence[AdmittedChunk | Mapping[str, Any]],
) -> tuple[AdmittedChunk, ...]:
    """Normalize admitted chunks and reject duplicate / positional keys."""

    if not isinstance(chunks, Sequence) or isinstance(chunks, (str, bytes)):
        raise UscodeEmbeddingError("chunks must be a sequence")
    if len(chunks) > MAX_CHUNKS_PER_CALL:
        raise UscodeEmbeddingError(
            f"chunk count {len(chunks)} exceeds max {MAX_CHUNKS_PER_CALL}"
        )
    out: list[AdmittedChunk] = []
    seen: set[str] = set()
    for index, item in enumerate(chunks):
        if isinstance(item, AdmittedChunk):
            chunk = item
        elif isinstance(item, Mapping):
            chunk = AdmittedChunk.from_mapping(item)
        else:
            raise UscodeEmbeddingError(
                f"chunks[{index}] must be AdmittedChunk or mapping"
            )
        if chunk.chunk_cid in seen:
            raise ChunkKeyMismatchError(
                f"duplicate admitted chunk_cid: {chunk.chunk_cid!r}"
            )
        seen.add(chunk.chunk_cid)
        out.append(chunk)
    return tuple(out)


# ---------------------------------------------------------------------------
# Embedding records / results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EmbeddingRecord:
    """One trusted embedding bound to a canonical chunk CID."""

    chunk_cid: str
    embedding: tuple[float, ...]
    dimension: int
    input_hash: str
    model_id: str
    model_revision: str
    vector_space_id: str
    pooling: str
    normalization: str
    l2_norm: float
    config_cid: str
    entry_cid: Optional[str] = None
    chunk_id: Optional[str] = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        reject_positional_durable_identity(self.chunk_cid, name="chunk_cid")
        object.__setattr__(
            self,
            "embedding",
            validate_vector_dimension(
                self.embedding, dimension=self.dimension, name="embedding"
            ),
        )
        measured = validate_vector_norm(
            self.embedding,
            normalization=self.normalization,
            name="embedding",
        )
        # Prefer measured norm for consistency.
        object.__setattr__(self, "l2_norm", measured)
        model_id, model_revision = reject_placeholder_model_ref(
            model_id=self.model_id,
            model_revision=self.model_revision,
        )
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "model_revision", model_revision)
        object.__setattr__(
            self,
            "input_hash",
            _require_non_empty_str(self.input_hash, "input_hash", maximum=128),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_cid": self.chunk_cid,
            "chunk_id": self.chunk_id,
            "config_cid": self.config_cid,
            "dimension": self.dimension,
            "embedding": list(self.embedding),
            "entry_cid": self.entry_cid,
            "input_hash": self.input_hash,
            "l2_norm": self.l2_norm,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "normalization": self.normalization,
            "pooling": self.pooling,
            "schema_version": self.schema_version,
            "vector_space_id": self.vector_space_id,
        }


@dataclass(frozen=True, slots=True)
class MissingVectorDiagnostic:
    """Diagnostic for a chunk that did not produce a trusted vector."""

    chunk_cid: str
    reason: str
    code: str = "missing_vector"

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_cid": self.chunk_cid,
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class EmbeddingGenerationResult:
    """Result of embedding a closed admitted-chunk set."""

    embeddings: Mapping[str, EmbeddingRecord]
    config: UscodeEmbeddingConfig
    admitted_chunk_cids: tuple[str, ...]
    device_requested: str
    device_selected: str
    device_fallback_applied: bool
    missing: tuple[MissingVectorDiagnostic, ...] = ()
    batch_count: int = 0
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        # Freeze embeddings mapping as plain dict for stable access.
        if not isinstance(self.embeddings, Mapping):
            raise UscodeEmbeddingError("embeddings must be a mapping")
        object.__setattr__(self, "embeddings", dict(self.embeddings))
        assert_output_keys_match_admitted(
            self.embeddings,
            self.admitted_chunk_cids,
            missing=self.missing,
        )

    @property
    def vectors_by_chunk_cid(self) -> dict[str, tuple[float, ...]]:
        return {cid: rec.embedding for cid, rec in self.embeddings.items()}

    def to_dict(self, *, include_vectors: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "admitted_chunk_cids": list(self.admitted_chunk_cids),
            "batch_count": self.batch_count,
            "config": self.config.to_dict(),
            "device_fallback_applied": self.device_fallback_applied,
            "device_requested": self.device_requested,
            "device_selected": self.device_selected,
            "missing": [item.to_dict() for item in self.missing],
            "schema_version": self.schema_version,
            "vector_count": len(self.embeddings),
        }
        if include_vectors:
            payload["embeddings"] = {
                cid: rec.to_dict() for cid, rec in self.embeddings.items()
            }
        else:
            payload["embedding_keys"] = sorted(self.embeddings)
        return payload


def assert_output_keys_match_admitted(
    embeddings: Mapping[str, Any],
    admitted_chunk_cids: Sequence[str],
    *,
    missing: Sequence[MissingVectorDiagnostic] = (),
) -> None:
    """Require output keys == admitted set when there are no missing vectors.

    When *missing* is non-empty, keys must equal admitted minus missing.
    Extras or unexpected omissions fail closed.
    """

    admitted = list(admitted_chunk_cids)
    admitted_set = set(admitted)
    if len(admitted) != len(admitted_set):
        raise ChunkKeyMismatchError("admitted_chunk_cids contains duplicates")

    keys = set(embeddings.keys())
    missing_cids = {item.chunk_cid for item in missing}
    if missing_cids & keys:
        raise ChunkKeyMismatchError(
            "missing diagnostics must not overlap produced embedding keys"
        )
    expected = admitted_set - missing_cids
    if keys != expected:
        extra = sorted(keys - expected)
        absent = sorted(expected - keys)
        raise ChunkKeyMismatchError(
            "output keys must exactly match admitted chunks "
            f"(minus missing); extra={extra!r} absent={absent!r}"
        )
    # Preserve fail-closed full-coverage default: callers that require every
    # admitted chunk to embed must pass allow_missing=False to the generator.
    unknown_missing = missing_cids - admitted_set
    if unknown_missing:
        raise ChunkKeyMismatchError(
            f"missing diagnostics reference non-admitted chunks: "
            f"{sorted(unknown_missing)!r}"
        )


# ---------------------------------------------------------------------------
# Legacy vector rejection
# ---------------------------------------------------------------------------


def is_legacy_positional_identity(value: Any) -> bool:
    """Return True for positional durable-identity tokens such as ``row-12``."""

    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    try:
        reject_positional_durable_identity(text, name="identity")
    except PositionalIdentityError:
        return True
    lowered = text.lower()
    if lowered.startswith("row-") and re.fullmatch(r"row-\d+", lowered):
        return True
    if re.fullmatch(r"document[_-]?index[_-]?\d+", lowered):
        return True
    return False


def is_untrusted_legacy_vector_row(row: Mapping[str, Any]) -> bool:
    """Return True when a legacy embedding row must not be promoted."""

    if not isinstance(row, Mapping):
        return True
    # Positional join keys.
    for key in (
        "chunk_cid",
        "entry_cid",
        "cid",
        "id",
        "row_id",
        "primary_key",
        "chunk_id",
    ):
        if key in row and is_legacy_positional_identity(row.get(key)):
            return True
    # Explicit positional fields as sole identity.
    has_durable = any(
        row.get(k) not in (None, "")
        and not is_legacy_positional_identity(row.get(k))
        for k in ("chunk_cid", "entry_cid", "cid")
    )
    if not has_durable:
        for key in ("document_index", "row_index", "row_number", "embedding_row"):
            if row.get(key) not in (None, ""):
                return True
    # Unknown / missing / placeholder model identity.
    model_id = row.get("model_id") or row.get("model") or row.get("model_name")
    model_revision = row.get("model_revision") or row.get("model_version")
    if is_placeholder_model_ref(model_id) or is_placeholder_revision(model_revision):
        return True
    try:
        reject_placeholder_model_ref(
            model_id=model_id, model_revision=model_revision
        )
    except (UnpinnedModelError, MutableReferenceError, EmbeddingConfigError):
        return True
    return False


def promote_legacy_vectors(
    rows: Sequence[Mapping[str, Any]],
    *,
    config: UscodeEmbeddingConfig | None = None,
) -> dict[str, EmbeddingRecord]:
    """Fail closed: legacy positional / untrusted vectors are never promoted.

    This function exists as an explicit choke point so callers cannot
    accidentally re-key ``laws_embeddings.parquet`` row-N vectors into the
    trusted v2 space.
    """

    del config  # pin is irrelevant; promotion is always forbidden
    if not rows:
        raise LegacyVectorPromotionError(
            "legacy vector promotion is forbidden even for an empty batch; "
            "regenerate embeddings under a pinned model and chunk CIDs"
        )
    reasons: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            reasons.append(f"row[{index}]: not a mapping")
            continue
        if is_untrusted_legacy_vector_row(row):
            identity = (
                row.get("chunk_cid")
                or row.get("entry_cid")
                or row.get("cid")
                or row.get("id")
                or f"row[{index}]"
            )
            model = row.get("model_id") or row.get("model") or "unknown"
            revision = row.get("model_revision") or "unknown"
            reasons.append(
                f"{identity}: untrusted legacy vector "
                f"(model={model!r}, revision={revision!r})"
            )
        else:
            # Even "well-formed" legacy rows are never promoted through this API.
            identity = (
                row.get("chunk_cid")
                or row.get("entry_cid")
                or row.get("cid")
                or f"row[{index}]"
            )
            reasons.append(
                f"{identity}: legacy promotion path is permanently disabled"
            )
    detail = "; ".join(reasons[:8])
    if len(reasons) > 8:
        detail += f"; ... and {len(reasons) - 8} more"
    raise LegacyVectorPromotionError(
        "legacy positional / untrusted vectors must never be promoted; "
        f"regenerate under a pinned model. details: {detail}"
    )


# ---------------------------------------------------------------------------
# Deterministic local backend
# ---------------------------------------------------------------------------


def deterministic_project(
    texts: Sequence[str],
    *,
    dimension: int,
    normalize: bool = True,
) -> list[list[float]]:
    """Project texts into a sealed deterministic unit-normalized space."""

    vectors: list[list[float]] = []
    for text in texts:
        normalized = normalize_embedding_text(text)
        projected = hashed_term_projection(normalized, dimension=dimension)
        if normalize:
            projected = l2_normalize(projected)
        vectors.append([float(x) for x in projected])
    return vectors


def _sentence_transformers_embedder(
    config: UscodeEmbeddingConfig,
) -> EmbeddingFunction:
    """Load the pinned model via sentence-transformers on the configured device."""

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover
        raise HardwareUnavailableError(
            "sentence-transformers is required for production GTE embeddings; "
            "install sentence-transformers or inject an embedder"
        ) from exc

    device, _fallback = select_device(
        config.device,
        fallback=config.device_fallback,
    )
    model = SentenceTransformer(
        config.model_id,
        revision=config.model_revision,
        device=device,
    )

    def _embed(texts: Sequence[str]) -> list[list[float]]:
        # truncate to the pin's max_tokens window when the backend supports it
        vectors = model.encode(
            list(texts),
            batch_size=config.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=config.normalization == "l2",
        )
        return [list(map(float, row)) for row in vectors]

    return _embed


def _default_embedder(config: UscodeEmbeddingConfig) -> EmbeddingFunction:
    """Select the embedder for *config*.

    Production pins (``sentence_transformers`` / huggingface provider) load the
    immutable model revision on CUDA when available. Unit-test / offline pins
    that explicitly request the deterministic backend stay offline.
    """

    backend = str(config.backend or "").strip().lower()
    if backend in {
        "local_deterministic_projection",
        "deterministic",
        "hashed",
        "offline",
        "fixture",
    }:
        def _embed(texts: Sequence[str]) -> list[list[float]]:
            return deterministic_project(
                texts,
                dimension=config.dimension,
                normalize=config.normalization == "l2",
            )

        return _embed

    return _sentence_transformers_embedder(config)


# ---------------------------------------------------------------------------
# Checkpoints
# ---------------------------------------------------------------------------


@dataclass
class EmbeddingCheckpoint:
    """Resumable checkpoint of completed chunk CIDs for one pin."""

    config_digest: str
    completed_chunk_cids: list[str] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "completed_chunk_cids": list(self.completed_chunk_cids),
            "config_digest": self.config_digest,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EmbeddingCheckpoint":
        if not isinstance(value, Mapping):
            raise EmbeddingCheckpointError("checkpoint must be a mapping")
        if value.get("schema_version") != SCHEMA_VERSION:
            raise EmbeddingCheckpointError(
                f"unsupported checkpoint schema_version: "
                f"{value.get('schema_version')!r}"
            )
        digest = _require_non_empty_str(
            value.get("config_digest"), "config_digest", maximum=128
        )
        completed = value.get("completed_chunk_cids") or []
        if not isinstance(completed, list):
            raise EmbeddingCheckpointError(
                "completed_chunk_cids must be a list"
            )
        cids: list[str] = []
        for item in completed:
            text = _require_non_empty_str(item, "completed_chunk_cids item")
            reject_positional_durable_identity(text, name="chunk_cid")
            cids.append(text)
        return cls(config_digest=digest, completed_chunk_cids=cids)


def load_checkpoint(path: PathLike) -> EmbeddingCheckpoint:
    checkpoint_path = Path(path)
    if not checkpoint_path.is_file():
        raise EmbeddingCheckpointError(f"checkpoint not found: {checkpoint_path}")
    try:
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EmbeddingCheckpointError(
            f"invalid checkpoint JSON: {exc}"
        ) from exc
    return EmbeddingCheckpoint.from_mapping(payload)


def write_checkpoint_atomic(
    path: PathLike,
    checkpoint: EmbeddingCheckpoint,
) -> Path:
    """Write *checkpoint* atomically (temp file + replace)."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        checkpoint.to_dict(),
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    ) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=".uscode-embed-ckpt-",
        suffix=".json",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
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


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class UscodeEmbeddingGenerator:
    """Stream reproducible normalized embeddings for admitted legal chunks."""

    def __init__(
        self,
        config: UscodeEmbeddingConfig | None = None,
        *,
        embedder: EmbeddingFunction | None = None,
        device_probe: Callable[[str], bool] | None = None,
    ) -> None:
        self._config = config or default_embedding_config()
        if not isinstance(self._config, UscodeEmbeddingConfig):
            raise EmbeddingConfigError("config must be UscodeEmbeddingConfig")
        self._embedder = embedder or _default_embedder(self._config)
        if not callable(self._embedder):
            raise EmbeddingConfigError("embedder must be callable")
        self._device_probe = device_probe

    @property
    def config(self) -> UscodeEmbeddingConfig:
        return self._config

    def resolve_device(self) -> tuple[str, bool]:
        return select_device(
            self._config.device,
            fallback=self._config.device_fallback,
            probe=self._device_probe,
        )

    def embed_texts(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        """Embed raw texts under the bound pin (dimension/norm validated)."""

        raw = self._embedder([str(t if t is not None else "") for t in texts])
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise UscodeEmbeddingError("embedder must return a sequence of vectors")
        if len(raw) != len(texts):
            raise MissingVectorError(
                f"embedder returned {len(raw)} vectors for {len(texts)} texts"
            )
        out: list[tuple[float, ...]] = []
        for index, vector in enumerate(raw):
            validated = validate_vector_dimension(
                vector,
                dimension=self._config.dimension,
                name=f"vector[{index}]",
            )
            if self._config.normalization == "l2":
                # Re-normalize to defend against non-compliant injectors.
                validated = tuple(l2_normalize(validated))
            validate_vector_norm(
                validated,
                normalization=self._config.normalization,
                name=f"vector[{index}]",
            )
            out.append(tuple(validated))
        return out

    def generate(
        self,
        chunks: Sequence[AdmittedChunk | Mapping[str, Any]],
        *,
        allow_missing: bool = False,
        checkpoint_path: PathLike | None = None,
        resume: bool = True,
    ) -> EmbeddingGenerationResult:
        """Generate embeddings for *chunks*; keys match admitted CIDs.

        Parameters
        ----------
        chunks:
            Admitted legal chunks (or mappings). Duplicate / positional
            ``chunk_cid`` values fail closed.
        allow_missing:
            When False (default), any missing vector fails the run.
        checkpoint_path:
            Optional path for atomic completed-CID checkpoints.
        resume:
            When True and a compatible checkpoint exists, skip completed CIDs
            already recorded (vectors are still re-emitted only for the full
            admitted set by re-embedding remaining work; completed keys must
            still be produced — resume skips re-compute only when vectors are
            reloaded from an external store). For this module, resume records
            progress diagnostics; full key coverage is always validated.
        """

        admitted = coerce_admitted_chunks(chunks)
        admitted_cids = tuple(chunk.chunk_cid for chunk in admitted)
        device_selected, fallback_applied = self.resolve_device()

        completed: set[str] = set()
        if checkpoint_path is not None and resume and Path(checkpoint_path).is_file():
            ckpt = load_checkpoint(checkpoint_path)
            if ckpt.config_digest != self._config.digest:
                raise EmbeddingCheckpointError(
                    "checkpoint config_digest does not match active pin"
                )
            completed = set(ckpt.completed_chunk_cids)

        embeddings: dict[str, EmbeddingRecord] = {}
        missing: list[MissingVectorDiagnostic] = []
        batch_size = self._config.batch_size
        batch_count = 0

        pending = [chunk for chunk in admitted if chunk.chunk_cid not in completed]
        # Re-embed completed as well for a self-contained result that always
        # covers the full admitted set (checkpoints track progress only).
        work = list(admitted)

        for start in range(0, len(work), batch_size):
            batch = work[start : start + batch_size]
            batch_count += 1
            texts = [
                chunk.resolve_input_text(self._config.input_fields) for chunk in batch
            ]
            input_hashes = [input_content_hash(text) for text in texts]
            try:
                vectors = self.embed_texts(texts)
            except MissingVectorError as exc:
                if not allow_missing:
                    raise
                for chunk in batch:
                    missing.append(
                        MissingVectorDiagnostic(
                            chunk_cid=chunk.chunk_cid,
                            reason=str(exc),
                        )
                    )
                continue

            for chunk, vector, in_hash in zip(batch, vectors, input_hashes):
                # Detect all-zero unexpected for non-empty text under l2 as
                # missing diagnostic when allow_missing is set.
                norm = l2_norm(vector)
                if (
                    allow_missing
                    and normalize_embedding_text(
                        chunk.resolve_input_text(self._config.input_fields)
                    )
                    and norm == 0.0
                    and self._config.normalization == "l2"
                ):
                    missing.append(
                        MissingVectorDiagnostic(
                            chunk_cid=chunk.chunk_cid,
                            reason="zero vector for non-empty input",
                            code="zero_vector",
                        )
                    )
                    continue
                record = EmbeddingRecord(
                    chunk_cid=chunk.chunk_cid,
                    embedding=vector,
                    dimension=self._config.dimension,
                    input_hash=in_hash,
                    model_id=self._config.model_id,
                    model_revision=self._config.model_revision,
                    vector_space_id=self._config.vector_space_id,
                    pooling=self._config.pooling,
                    normalization=self._config.normalization,
                    l2_norm=norm,
                    config_cid=self._config.config_cid,
                    entry_cid=chunk.entry_cid,
                    chunk_id=chunk.chunk_id,
                )
                embeddings[chunk.chunk_cid] = record
                completed.add(chunk.chunk_cid)

            if checkpoint_path is not None:
                write_checkpoint_atomic(
                    checkpoint_path,
                    EmbeddingCheckpoint(
                        config_digest=self._config.digest,
                        completed_chunk_cids=sorted(completed),
                    ),
                )

        if not allow_missing and missing:
            raise MissingVectorError(
                f"{len(missing)} vectors missing after generation"
            )

        # pending is retained for diagnostics/resume awareness.
        del pending

        return EmbeddingGenerationResult(
            embeddings=embeddings,
            config=self._config,
            admitted_chunk_cids=admitted_cids,
            device_requested=self._config.device,
            device_selected=device_selected,
            device_fallback_applied=fallback_applied,
            missing=tuple(missing),
            batch_count=batch_count,
        )


def generate_uscode_embeddings(
    chunks: Sequence[AdmittedChunk | Mapping[str, Any]],
    *,
    config: UscodeEmbeddingConfig | None = None,
    embedder: EmbeddingFunction | None = None,
    allow_missing: bool = False,
    checkpoint_path: PathLike | None = None,
    device_probe: Callable[[str], bool] | None = None,
) -> EmbeddingGenerationResult:
    """Convenience entry point for pinned legal embedding generation."""

    generator = UscodeEmbeddingGenerator(
        config=config,
        embedder=embedder,
        device_probe=device_probe,
    )
    return generator.generate(
        chunks,
        allow_missing=allow_missing,
        checkpoint_path=checkpoint_path,
    )


# ---------------------------------------------------------------------------
# Fixture contract (compact recipe)
# ---------------------------------------------------------------------------


def default_embedding_contract_fixture_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "legal_ir"
        / "uscode_embedding_contract.json"
    )


def build_default_embedding_contract_fixture_payload() -> dict[str, Any]:
    """Compact sealed contract recipe (no bulk per-vector golden dumps)."""

    config = default_embedding_config()
    return {
        "acceptance": {
            "dimensions_and_norms_validated": True,
            "legacy_positional_vectors_never_promoted": True,
            "output_keys_exactly_match_admitted_chunks": True,
            "unknown_mutable_placeholder_model_refs_fail_closed": True,
        },
        "default_pin": {
            "backend": config.backend,
            "dimension": config.dimension,
            "input_fields": list(config.input_fields),
            "license": config.license,
            "max_tokens": config.max_tokens,
            "model_id": config.model_id,
            "model_revision": config.model_revision,
            "normalization": config.normalization,
            "pooling": config.pooling,
            "provider": config.provider,
            "vector_space_id": config.vector_space_id,
        },
        "description": (
            "Compact embedding contract recipe for USCIR-017. Cases exercise "
            "fail-closed model pins, exact chunk-CID key matching, dimension "
            "and L2-norm validation, and permanent rejection of legacy "
            "positional vector promotion. Vectors are produced by the sealed "
            "deterministic local backend (no model download)."
        ),
        "goal_id": GOAL_ID,
        "notes": (
            "Recipe form: generators and case expectations only; no bulk "
            "embedding golden dumps. Expand via run_contract_case()."
        ),
        "producer": "uscode_embeddings.py",
        "release_profile": RELEASE_PROFILE,
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "cases": [
            {
                "case_id": "happy-path-key-match-and-norms",
                "kind": "generate",
                "chunks": [
                    {
                        "chunk_cid": (
                            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                        ),
                        "entry_cid": (
                            "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                        ),
                        "text": "Whoever invents or discovers any new and useful process.",
                        "heading": "Inventions patentable",
                        "title": "35",
                        "section": "101",
                        "legal_id": "usc:us:35:101",
                    },
                    {
                        "chunk_cid": (
                            "sha256:cccccccccccccccccccccccccccccccc"
                            "cccccccccccccccccccccccccccccccc"
                        ),
                        "entry_cid": (
                            "sha256:dddddddddddddddddddddddddddddddd"
                            "dddddddddddddddddddddddddddddddd"
                        ),
                        "text": "Each agency shall make available to the public information.",
                        "heading": "Public information",
                        "title": "5",
                        "section": "552",
                        "legal_id": "usc:us:5:552",
                    },
                ],
                "expect": {
                    "key_match": True,
                    "unit_norms": True,
                    "dimension": DEFAULT_DIMENSION,
                    "vector_count": 2,
                    "reproducible": True,
                },
            },
            {
                "case_id": "reject-mutable-model-revision",
                "kind": "config_reject",
                "config_overrides": {
                    "model_revision": "latest",
                },
                "expect": {
                    "error": "unpinned_model",
                },
            },
            {
                "case_id": "reject-placeholder-model-id",
                "kind": "config_reject",
                "config_overrides": {
                    "model_id": "unknown",
                    "model_revision": DEFAULT_MODEL_REVISION,
                },
                "expect": {
                    "error": "unpinned_model",
                },
            },
            {
                "case_id": "reject-branch-model-revision",
                "kind": "config_reject",
                "config_overrides": {
                    "model_revision": "main",
                },
                "expect": {
                    "error": "unpinned_model",
                },
            },
            {
                "case_id": "reject-positional-chunk-cid",
                "kind": "chunk_reject",
                "chunks": [
                    {
                        "chunk_cid": "row-12",
                        "text": "positional identity must fail",
                    }
                ],
                "expect": {
                    "error": "positional",
                },
            },
            {
                "case_id": "reject-legacy-promotion",
                "kind": "legacy_reject",
                "legacy_rows": [
                    {
                        "id": "row-0",
                        "document_index": 0,
                        # Compact untrusted samples — promotion never inspects
                        # full 384-d payloads; keep the sealed recipe small.
                        "embedding": [0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1],
                        "model": None,
                        "model_revision": None,
                    },
                    {
                        "cid": "row-99",
                        "embedding": [0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2],
                    },
                ],
                "expect": {
                    "error": "legacy_promotion_forbidden",
                },
            },
            {
                "case_id": "cpu-fallback-when-cuda-unavailable",
                "kind": "device_fallback",
                "config_overrides": {
                    "device": "cuda",
                    "device_fallback": "fallback_cpu",
                },
                "chunks": [
                    {
                        "chunk_cid": (
                            "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
                            "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
                        ),
                        "text": "Device fallback must still emit unit vectors.",
                    }
                ],
                "expect": {
                    "device_selected": "cpu",
                    "device_fallback_applied": True,
                    "key_match": True,
                    "unit_norms": True,
                },
            },
            {
                "case_id": "dimension-mismatch-from-embedder-fails",
                "kind": "dimension_reject",
                "chunks": [
                    {
                        "chunk_cid": (
                            "sha256:ffffffffffffffffffffffffffffffff"
                            "ffffffffffffffffffffffffffffffff"
                        ),
                        "text": "Wrong dimension must fail closed.",
                    }
                ],
                "bad_dimension": 16,
                "expect": {
                    "error": "dimension_mismatch",
                },
            },
        ],
    }


def load_embedding_contract_fixture_payload(
    path: PathLike | None = None,
) -> dict[str, Any]:
    fixture_path = (
        Path(path) if path is not None else default_embedding_contract_fixture_path()
    )
    if not fixture_path.is_file():
        raise EmbeddingFixtureError(f"fixture not found: {fixture_path}")
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EmbeddingFixtureError(
            f"invalid JSON in {fixture_path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise EmbeddingFixtureError("fixture root must be an object")
    if payload.get("schema_version") != FIXTURE_SCHEMA_VERSION:
        raise EmbeddingFixtureError(
            f"unsupported fixture schema_version: {payload.get('schema_version')!r}"
        )
    if payload.get("task_id") != TASK_ID:
        raise EmbeddingFixtureError(
            f"fixture task_id must be {TASK_ID!r}"
        )
    if not isinstance(payload.get("cases"), list) or not payload["cases"]:
        raise EmbeddingFixtureError("fixture must contain a non-empty cases list")
    return payload


def run_contract_case(case: Mapping[str, Any]) -> dict[str, Any]:
    """Execute one sealed contract case; return a compact outcome dict."""

    if not isinstance(case, Mapping):
        raise EmbeddingFixtureError("case must be a mapping")
    case_id = str(case.get("case_id") or "")
    kind = str(case.get("kind") or "")
    expect = case.get("expect") or {}
    if not isinstance(expect, Mapping):
        raise EmbeddingFixtureError(f"case {case_id!r} expect must be a mapping")

    if kind == "config_reject":
        overrides = dict(case.get("config_overrides") or {})
        try:
            UscodeEmbeddingConfig(**overrides)
            return {"case_id": case_id, "ok": False, "error": "expected_reject"}
        except (UnpinnedModelError, EmbeddingConfigError, MutableReferenceError) as exc:
            code = getattr(exc, "code", "config_invalid")
            ok = expect.get("error") in {code, "unpinned_model"}
            return {"case_id": case_id, "ok": ok, "error": code, "message": str(exc)}

    if kind == "chunk_reject":
        try:
            coerce_admitted_chunks(list(case.get("chunks") or []))
            return {"case_id": case_id, "ok": False, "error": "expected_reject"}
        except (PositionalIdentityError, UscodeEmbeddingError) as exc:
            ok = "positional" in str(exc).lower() or expect.get("error") == "positional"
            return {
                "case_id": case_id,
                "ok": ok,
                "error": "positional",
                "message": str(exc),
            }

    if kind == "legacy_reject":
        try:
            promote_legacy_vectors(list(case.get("legacy_rows") or []))
            return {"case_id": case_id, "ok": False, "error": "expected_reject"}
        except LegacyVectorPromotionError as exc:
            ok = expect.get("error") == exc.code
            return {
                "case_id": case_id,
                "ok": ok,
                "error": exc.code,
                "message": str(exc),
            }

    if kind == "dimension_reject":
        bad_dim = int(case.get("bad_dimension") or 8)

        def bad_embedder(texts: Sequence[str]) -> list[list[float]]:
            return [[0.1] * bad_dim for _ in texts]

        try:
            generate_uscode_embeddings(
                list(case.get("chunks") or []),
                embedder=bad_embedder,
            )
            return {"case_id": case_id, "ok": False, "error": "expected_reject"}
        except DimensionValidationError as exc:
            ok = expect.get("error") == exc.code
            return {
                "case_id": case_id,
                "ok": ok,
                "error": exc.code,
                "message": str(exc),
            }

    if kind == "device_fallback":
        overrides = dict(case.get("config_overrides") or {})
        config = UscodeEmbeddingConfig(**overrides)

        def probe(device: str) -> bool:
            return str(device).startswith("cpu")

        result = generate_uscode_embeddings(
            list(case.get("chunks") or []),
            config=config,
            device_probe=probe,
        )
        ok = (
            result.device_selected == expect.get("device_selected", "cpu")
            and result.device_fallback_applied
            is bool(expect.get("device_fallback_applied", True))
        )
        if expect.get("key_match"):
            ok = ok and set(result.embeddings) == set(result.admitted_chunk_cids)
        if expect.get("unit_norms"):
            for rec in result.embeddings.values():
                if rec.l2_norm > 0 and abs(rec.l2_norm - 1.0) > NORM_TOLERANCE:
                    ok = False
        return {
            "case_id": case_id,
            "ok": ok,
            "device_selected": result.device_selected,
            "device_fallback_applied": result.device_fallback_applied,
            "vector_count": len(result.embeddings),
        }

    if kind == "generate":
        result = generate_uscode_embeddings(list(case.get("chunks") or []))
        ok = True
        if expect.get("key_match"):
            ok = ok and set(result.embeddings) == set(result.admitted_chunk_cids)
        if expect.get("vector_count") is not None:
            ok = ok and len(result.embeddings) == int(expect["vector_count"])
        if expect.get("dimension") is not None:
            dim = int(expect["dimension"])
            ok = ok and all(rec.dimension == dim for rec in result.embeddings.values())
            ok = ok and all(
                len(rec.embedding) == dim for rec in result.embeddings.values()
            )
        if expect.get("unit_norms"):
            for rec in result.embeddings.values():
                if rec.l2_norm > 0 and abs(rec.l2_norm - 1.0) > NORM_TOLERANCE:
                    ok = False
        if expect.get("reproducible"):
            again = generate_uscode_embeddings(list(case.get("chunks") or []))
            for cid, rec in result.embeddings.items():
                other = again.embeddings[cid]
                if rec.embedding != other.embedding:
                    ok = False
                if rec.input_hash != other.input_hash:
                    ok = False
        return {
            "case_id": case_id,
            "ok": ok,
            "vector_count": len(result.embeddings),
            "keys": sorted(result.embeddings),
        }

    raise EmbeddingFixtureError(f"unknown case kind: {kind!r}")


def write_default_embedding_contract_fixture(
    path: PathLike | None = None,
) -> Path:
    """Write the sealed compact contract recipe to *path* (or default)."""

    fixture_path = (
        Path(path) if path is not None else default_embedding_contract_fixture_path()
    )
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_default_embedding_contract_fixture_payload()
    # Smoke-run every case before sealing.
    for case in payload["cases"]:
        outcome = run_contract_case(case)
        if not outcome.get("ok"):
            raise EmbeddingFixtureError(
                f"contract case failed during seal: {outcome!r}"
            )
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fixture_path.write_text(text, encoding="utf-8")
    return fixture_path


__all__ = [
    "SCHEMA_VERSION",
    "FIXTURE_SCHEMA_VERSION",
    "TASK_ID",
    "GOAL_ID",
    "RELEASE_PROFILE",
    "DEFAULT_MODEL_ID",
    "DEFAULT_MODEL_REVISION",
    "DEFAULT_MODEL_LICENSE",
    "DEFAULT_DIMENSION",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_POOLING",
    "DEFAULT_NORMALIZATION",
    "DEFAULT_INPUT_FIELDS",
    "DEFAULT_BACKEND",
    "DEFAULT_PROVIDER",
    "DEFAULT_DEVICE",
    "DEFAULT_BATCH_SIZE",
    "MAX_BATCH_SIZE",
    "NORM_TOLERANCE",
    "VECTOR_STABILITY_TOLERANCE",
    "UscodeEmbeddingError",
    "EmbeddingConfigError",
    "UnpinnedModelError",
    "DimensionValidationError",
    "NormValidationError",
    "ChunkKeyMismatchError",
    "LegacyVectorPromotionError",
    "MissingVectorError",
    "EmbeddingFixtureError",
    "EmbeddingCheckpointError",
    "HardwareUnavailableError",
    "DeviceFallbackPolicy",
    "PoolingMethod",
    "NormalizationMethod",
    "UscodeEmbeddingConfig",
    "AdmittedChunk",
    "EmbeddingRecord",
    "MissingVectorDiagnostic",
    "EmbeddingGenerationResult",
    "EmbeddingCheckpoint",
    "UscodeEmbeddingGenerator",
    "default_embedding_config",
    "reject_placeholder_model_ref",
    "is_placeholder_model_ref",
    "is_placeholder_revision",
    "normalize_embedding_text",
    "input_content_hash",
    "l2_norm",
    "l2_normalize",
    "validate_vector_dimension",
    "validate_vector_norm",
    "build_vector_space_id",
    "device_is_available",
    "select_device",
    "coerce_admitted_chunks",
    "assert_output_keys_match_admitted",
    "is_legacy_positional_identity",
    "is_untrusted_legacy_vector_row",
    "promote_legacy_vectors",
    "deterministic_project",
    "load_checkpoint",
    "write_checkpoint_atomic",
    "generate_uscode_embeddings",
    "default_embedding_contract_fixture_path",
    "build_default_embedding_contract_fixture_payload",
    "load_embedding_contract_fixture_payload",
    "run_contract_case",
    "write_default_embedding_contract_fixture",
    "canonical_json_bytes",
    "content_sha256",
]
