"""Pinned thenlper/gte-small embeddings for Open US Law (OUL-028).

Production embedding is mandatory sentence-transformers inference with:

* model ``thenlper/gte-small``
* revision ``17e1f347d17fe144873b1201da91788898c639cd``
* 384 dimensions
* mean pooling
* L2 normalization
* real tokenizer truncation at 512 tokens (``model.max_seq_length = 512``)
* input-text and configuration hashes
* model-file/revision, runtime, device, precision, batch, and checkpoint evidence

A local deterministic projection may exist for unit fixtures but **cannot**
authorize a production candidate or release. The reused US Code embedder
defaults to that projection and does not set the 512-token ceiling; this
module is the Open US Law repair.

Design invariants
-----------------
* Every admitted chunk is embedded. Output keys equal the admitted
  ``chunk_cid`` set exactly.
* There is no 100,000-chunk per-call ceiling. Streams and checkpoints
  keep the exact-51 corpus (1,904,919+ rows) from being truncated.
* Checkpoints bind ``config_digest`` and store completed vectors so a
  clean resume skips finished work and remains fail-closed on pin or
  input-hash drift.
* Projection, injected fixture embedders, missing truncation evidence,
  wrong pins, and missing vectors cannot authorize release.
* This module does not cluster, shard, or publish vectors (OUL-029+).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import tempfile
import unicodedata
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Final, Optional, Union

from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_MODEL_REVISION,
    DEFAULT_MODEL_TOKEN_CEILING,
    RELEASE_PROFILE,
    InvalidDigestError,
    MutableReferenceError,
    PositionalIdentityError,
    reject_positional_durable_identity,
    require_immutable_revision,
    validate_entry_cid,
)
from ipfs_datasets_py.processors.retrieval import hashed_term_projection

# ---------------------------------------------------------------------------
# Identity / pin
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "open-us-law-embeddings-v1"
CHECKPOINT_SCHEMA_VERSION: Final = "open-us-law-embedding-checkpoint-v1"
RECEIPT_SCHEMA_VERSION: Final = "open-us-law-embedding-receipt-v1"
TASK_ID: Final = "OUL-028"
GOAL_ID: Final = "OUL-G040"
PROGRAM_ID: Final = "open-us-law-reindex-v1"
PRODUCER: Final = "open_us_law_embeddings.py"
ADR_PATH: Final = "docs/architecture/OPEN_US_LAW_REINDEX_PLAN.md"

PINNED_MODEL_ID: Final = DEFAULT_EMBEDDING_MODEL_ID
PINNED_MODEL_REVISION: Final = DEFAULT_EMBEDDING_MODEL_REVISION
PINNED_MODEL_LICENSE: Final = "mit"
PINNED_DIMENSION: Final = DEFAULT_EMBEDDING_DIMENSION
PINNED_MAX_TOKENS: Final = DEFAULT_MODEL_TOKEN_CEILING
PINNED_POOLING: Final = "mean"
PINNED_NORMALIZATION: Final = "l2"
PINNED_INPUT_FIELDS: Final = ("text",)
PINNED_TOKEN_COUNTER_ID: Final = (
    f"huggingface-auto-tokenizer:{PINNED_MODEL_ID}@{PINNED_MODEL_REVISION}:"
    "special-tokens/v1"
)

PRODUCTION_BACKEND: Final = "sentence_transformers"
PRODUCTION_PROVIDER: Final = "huggingface"
PROJECTION_BACKEND: Final = "local_deterministic_projection"

DEFAULT_BACKEND: Final = PRODUCTION_BACKEND
DEFAULT_PROVIDER: Final = PRODUCTION_PROVIDER
DEFAULT_DEVICE: Final = "cuda"
DEFAULT_PRECISION: Final = "fp32"
DEFAULT_BATCH_SIZE: Final = 64
MAX_BATCH_SIZE: Final = 512
DEFAULT_MODEL_TOKEN_LIMIT: Final = PINNED_MAX_TOKENS

# Exact-51 seed observation is 1,904,919 rows. No per-call ceiling may
# sit below that bound (the US Code reuse cap of 100,000 would truncate).
EXACT_51_SEED_ROW_LOWER_BOUND: Final = 1_904_919
PER_CALL_CHUNK_CEILING: Final[int | None] = None
REQUIRES_REAL_512_TOKEN_TRUNCATION: Final = True
PROJECTION_FALLBACK_AUTHORIZES_RELEASE: Final = False
AUTHORIZES_PUBLICATION: Final = False
PROVES_SOFTWARE_CONTRACT_ONLY: Final = True

NORM_TOLERANCE: Final = 1e-5
_FLOAT_EPS: Final = 1e-12

SUPPORTED_DEVICES: Final = frozenset({"cpu", "cuda", "cuda:0", "mps"})
PRODUCTION_BACKENDS: Final = frozenset({PRODUCTION_BACKEND, "huggingface"})
PROJECTION_BACKENDS: Final = frozenset(
    {
        PROJECTION_BACKEND,
        "deterministic",
        "hashed",
        "offline",
        "fixture",
        "local",
        "local_deterministic",
    }
)

RECEIPT_RELATIVE_PATH: Final = (
    "docs/reports/open_us_law_reindex/embedding_receipt.json"
)
RECEIPT_SEALED_AT: Final = "2026-08-14T00:00:00Z"

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
ModelFactory = Callable[["OpenUsLawEmbeddingConfig", str], Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OpenUsLawEmbeddingError(ValueError):
    """Base error for pinned Open US Law embedding generation."""

    code: str = "open_us_law_embedding_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class EmbeddingConfigError(OpenUsLawEmbeddingError):
    """Raised when embedding configuration is incomplete or invalid."""

    code = "config_invalid"


class UnpinnedModelError(OpenUsLawEmbeddingError):
    """Raised when model identity is mutable, placeholder, or not the pin."""

    code = "unpinned_model"


class DimensionValidationError(OpenUsLawEmbeddingError):
    """Raised when vector dimensions do not match the sealed pin."""

    code = "dimension_mismatch"


class NormValidationError(OpenUsLawEmbeddingError):
    """Raised when vector norms fail the L2 contract."""

    code = "norm_invalid"


class ChunkKeyMismatchError(OpenUsLawEmbeddingError):
    """Raised when output keys do not exactly match admitted chunk CIDs."""

    code = "chunk_key_mismatch"


class MissingVectorError(OpenUsLawEmbeddingError):
    """Raised when required vectors are missing after generation."""

    code = "missing_vector"


class EmbeddingCheckpointError(OpenUsLawEmbeddingError):
    """Raised when a checkpoint is corrupt, stale, or pin-incompatible."""

    code = "checkpoint_invalid"


class HardwareUnavailableError(OpenUsLawEmbeddingError):
    """Raised when requested hardware is unavailable and policy is block."""

    code = "hardware_unavailable"


class InferenceBackendError(OpenUsLawEmbeddingError):
    """Raised when the production inference runtime cannot be constructed."""

    code = "inference_backend_unavailable"


class TruncationContractError(OpenUsLawEmbeddingError):
    """Raised when real 512-token truncation is missing or misconfigured."""

    code = "truncation_contract_invalid"


class ProjectionReleaseAuthorizationError(OpenUsLawEmbeddingError):
    """Raised when a projection or fixture path would authorize release."""

    code = "projection_cannot_authorize_release"


class ReleaseAuthorizationError(OpenUsLawEmbeddingError):
    """Raised when a candidate is not eligible to authorize release."""

    code = "release_authorization_rejected"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DeviceFallbackPolicy(str, Enum):
    """What to do when requested hardware is unavailable."""

    FALLBACK_CPU = "fallback_cpu"
    BLOCK = "block"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_bytes(payload: Any) -> bytes:
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
    if value is None or not isinstance(value, str):
        return True
    text = value.strip()
    if not text:
        return True
    if _PLACEHOLDER_MODEL_RE.fullmatch(text):
        return True
    tail = text.rsplit("/", 1)[-1]
    return bool(_PLACEHOLDER_MODEL_RE.fullmatch(tail))


def is_placeholder_revision(value: Any) -> bool:
    if value is None or not isinstance(value, str):
        return True
    text = value.strip()
    return (not text) or bool(_PLACEHOLDER_REVISION_RE.fullmatch(text))


def reject_placeholder_model_ref(
    *,
    model_id: Any,
    model_revision: Any,
    model_id_name: str = "model_id",
    model_revision_name: str = "model_revision",
) -> tuple[str, str]:
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
        revision = require_immutable_revision(
            model_revision, name=model_revision_name
        )
    except MutableReferenceError as exc:
        raise UnpinnedModelError(str(exc)) from exc
    model = _require_non_empty_str(model_id, model_id_name, maximum=512)
    return model, revision


def require_pinned_gte_small(
    *,
    model_id: Any,
    model_revision: Any,
) -> tuple[str, str]:
    """Require the sealed thenlper/gte-small revision and nothing else."""

    model, revision = reject_placeholder_model_ref(
        model_id=model_id, model_revision=model_revision
    )
    if model != PINNED_MODEL_ID:
        raise UnpinnedModelError(
            f"model_id must be the sealed pin {PINNED_MODEL_ID!r}; got {model!r}"
        )
    if revision != PINNED_MODEL_REVISION:
        raise UnpinnedModelError(
            "model_revision must be the sealed thenlper/gte-small revision "
            f"{PINNED_MODEL_REVISION}; got {revision!r}"
        )
    return model, revision


def normalize_embedding_text(text: str) -> str:
    """NFKC-normalize and collapse whitespace for deterministic input hashing."""

    if not isinstance(text, str):
        raise OpenUsLawEmbeddingError("embedding text must be a string")
    if "\x00" in text:
        raise OpenUsLawEmbeddingError("embedding text must not contain NUL")
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    return " ".join(normalized.split())


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
            raise DimensionValidationError(f"{name}[{index}] must be a finite number")
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
    norm = l2_norm(vector)
    if not math.isfinite(norm):
        raise NormValidationError(f"{name} norm is not finite")
    policy = str(normalization or "").strip().lower()
    if policy == "l2":
        if norm > 0.0 and abs(norm - 1.0) > tolerance:
            raise NormValidationError(
                f"{name} L2 norm {norm} outside unit tolerance {tolerance}"
            )
    elif policy != "none":
        raise EmbeddingConfigError(f"unsupported normalization: {normalization!r}")
    return norm


def build_vector_space_id(
    *,
    model_id: str = PINNED_MODEL_ID,
    model_revision: str = PINNED_MODEL_REVISION,
    pooling: str = PINNED_POOLING,
    normalization: str = PINNED_NORMALIZATION,
    dimension: int = PINNED_DIMENSION,
) -> str:
    model, revision = require_pinned_gte_small(
        model_id=model_id, model_revision=model_revision
    )
    short = model.rsplit("/", 1)[-1].lower()
    short = re.sub(r"[^a-z0-9._-]+", "-", short)
    pool = _require_non_empty_str(pooling, "pooling").lower()
    norm = _require_non_empty_str(normalization, "normalization").lower()
    dim = _require_positive_int(dimension, "dimension")
    return f"{short}@{revision}:d{dim}:pool={pool}:norm={norm}"


def default_vector_space_id() -> str:
    return build_vector_space_id()


def is_projection_backend(backend: Any) -> bool:
    name = str(backend or "").strip().lower()
    return name in PROJECTION_BACKENDS


def is_production_backend(backend: Any) -> bool:
    name = str(backend or "").strip().lower()
    return name in PRODUCTION_BACKENDS


def per_call_chunk_ceiling() -> int | None:
    """Return the per-call chunk ceiling, or ``None`` when unbounded."""

    return PER_CALL_CHUNK_CEILING


def assert_no_truncating_chunk_ceiling() -> None:
    """Fail if a per-call cap would truncate the exact-51 seed."""

    ceiling = per_call_chunk_ceiling()
    if ceiling is None:
        return
    if ceiling < EXACT_51_SEED_ROW_LOWER_BOUND:
        raise EmbeddingConfigError(
            f"per-call chunk ceiling {ceiling} would truncate the exact-51 "
            f"seed (lower bound {EXACT_51_SEED_ROW_LOWER_BOUND})"
        )


def assert_chunk_stream_unbounded(count: int) -> None:
    """Accept any non-negative admitted count; refuse truncating ceilings."""

    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise EmbeddingConfigError("chunk count must be a non-negative integer")
    assert_no_truncating_chunk_ceiling()
    ceiling = per_call_chunk_ceiling()
    if ceiling is not None and count > ceiling:
        raise EmbeddingConfigError(
            f"chunk count {count} exceeds per-call ceiling {ceiling}"
        )


# ---------------------------------------------------------------------------
# Device / runtime evidence
# ---------------------------------------------------------------------------


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
        return "cpu", True
    if fallback is DeviceFallbackPolicy.BLOCK:
        raise HardwareUnavailableError(
            f"requested device {req!r} is unavailable and fallback policy is block"
        )
    raise EmbeddingConfigError(f"unknown fallback policy: {fallback!r}")


def collect_runtime_evidence(device: str) -> dict[str, Any]:
    """Record runtime/device/precision evidence without requiring imports."""

    evidence: dict[str, Any] = {
        "cuda_available": False,
        "cuda_device_name": None,
        "cuda_version": None,
        "device": device,
        "precision": DEFAULT_PRECISION,
        "python": sys.version.split()[0],
        "sentence_transformers_available": False,
        "sentence_transformers_version": None,
        "torch_version": None,
    }
    try:
        import torch  # type: ignore[import-not-found]

        evidence["torch_version"] = str(getattr(torch, "__version__", "") or None)
        cuda = getattr(torch, "cuda", None)
        evidence["cuda_available"] = bool(cuda is not None and cuda.is_available())
        if evidence["cuda_available"]:
            try:
                evidence["cuda_device_name"] = str(cuda.get_device_name(0))
            except Exception:
                evidence["cuda_device_name"] = None
            version = getattr(getattr(torch, "version", None), "cuda", None)
            evidence["cuda_version"] = None if version is None else str(version)
    except Exception:
        pass
    try:
        import sentence_transformers  # type: ignore[import-not-found]

        evidence["sentence_transformers_available"] = True
        evidence["sentence_transformers_version"] = str(
            getattr(sentence_transformers, "__version__", "") or None
        )
    except Exception:
        pass
    return evidence


def collect_model_file_evidence(model: Any) -> dict[str, Any]:
    """Hash the locally loaded immutable model snapshot when it is discoverable."""

    files: list[dict[str, str]] = []
    candidates: list[Path] = []
    owners: list[Any] = [model]
    first_module = getattr(model, "_first_module", None)
    if callable(first_module):
        try:
            first_module = first_module()
        except Exception:  # noqa: BLE001 - optional model adapter boundary
            first_module = None
    if first_module is not None:
        owners.append(first_module)
        auto_model = getattr(first_module, "auto_model", None)
        if auto_model is not None:
            owners.extend((auto_model, getattr(auto_model, "config", None)))
    auto_model = getattr(model, "auto_model", None)
    if auto_model is not None:
        owners.extend((auto_model, getattr(auto_model, "config", None)))
    tokenizer = getattr(model, "tokenizer", None)
    if tokenizer is not None:
        owners.append(tokenizer)

    pinned_identity_seen = False
    for owner in owners:
        if owner is None:
            continue
        for attr in (
            "cache_folder",
            "name_or_path",
            "model_name_or_path",
            "_name_or_path",
        ):
            raw = getattr(owner, attr, None)
            if isinstance(raw, str) and raw.strip():
                pinned_identity_seen |= raw.strip() == PINNED_MODEL_ID
                path = Path(raw)
                if path.exists():
                    candidates.append(path)

    # SentenceTransformers 5 exposes the repository identity on its nested
    # transformers config, but not the resolved snapshot directory. Resolve
    # only already-cached bytes at the exact immutable revision; never fetch
    # new or mutable model state while collecting evidence.
    if pinned_identity_seen and not candidates:
        try:
            from huggingface_hub import snapshot_download

            snapshot = snapshot_download(
                repo_id=PINNED_MODEL_ID,
                revision=PINNED_MODEL_REVISION,
                local_files_only=True,
            )
            candidates.append(Path(snapshot))
        except Exception:  # noqa: BLE001 - absent local cache is valid evidence
            snapshot = None

    seen: set[str] = set()
    for candidate in candidates:
        resolved = str(candidate.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.is_file():
            files.append(
                {
                    "path": candidate.name,
                    "sha256": _sha256_file(candidate),
                }
            )
        elif candidate.is_dir():
            for child in sorted(candidate.rglob("*")):
                if child.is_file() and child.suffix in {
                    ".bin",
                    ".safetensors",
                    ".json",
                    ".txt",
                }:
                    files.append(
                        {
                            "path": child.relative_to(candidate).as_posix(),
                            "sha256": _sha256_file(child),
                        }
                    )
    files.sort(key=lambda item: (item["path"], item["sha256"]))
    return {
        "file_count": len(files),
        "files": files[:32],
        "revision": PINNED_MODEL_REVISION,
    }


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OpenUsLawEmbeddingConfig:
    """Fail-closed pin for Open US Law embedding generation."""

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
    precision: str = DEFAULT_PRECISION
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        model_id, model_revision = require_pinned_gte_small(
            model_id=self.model_id,
            model_revision=self.model_revision,
        )
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "model_revision", model_revision)

        license_text = _require_non_empty_str(self.license, "license", maximum=256)
        if is_placeholder_model_ref(license_text):
            raise UnpinnedModelError(
                f"license must be an explicit declared license, not {self.license!r}"
            )
        object.__setattr__(self, "license", license_text)

        max_tokens = _require_positive_int(self.max_tokens, "max_tokens")
        if max_tokens != PINNED_MAX_TOKENS:
            raise EmbeddingConfigError(
                f"max_tokens must be the sealed 512-token ceiling; got {max_tokens}"
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
                f"normalization must be {PINNED_NORMALIZATION!r}; got "
                f"{self.normalization!r}"
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
                f"dimension must be {PINNED_DIMENSION}; got {dimension}"
            )
        object.__setattr__(self, "dimension", dimension)

        space = str(self.vector_space_id or "").strip()
        expected = build_vector_space_id(
            model_id=model_id,
            model_revision=model_revision,
            pooling=pooling,
            normalization=normalization,
            dimension=dimension,
        )
        if not space:
            space = expected
        else:
            space = _require_non_empty_str(space, "vector_space_id", maximum=512)
            if space != expected:
                raise EmbeddingConfigError(
                    f"vector_space_id must be {expected!r}; got {space!r}"
                )
        object.__setattr__(self, "vector_space_id", space)

        backend = _require_non_empty_str(self.backend, "backend", maximum=128).lower()
        if is_placeholder_model_ref(backend):
            raise UnpinnedModelError(f"backend must not be a placeholder: {backend!r}")
        if not (is_production_backend(backend) or is_projection_backend(backend)):
            raise EmbeddingConfigError(f"unsupported backend: {backend!r}")
        object.__setattr__(self, "backend", backend)

        provider = _require_non_empty_str(self.provider, "provider", maximum=128).lower()
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
            raise EmbeddingConfigError(f"batch_size must be <= {MAX_BATCH_SIZE}")
        object.__setattr__(self, "batch_size", batch_size)

        precision = _require_non_empty_str(self.precision, "precision", maximum=32).lower()
        if precision not in {"fp32", "fp16", "bf16"}:
            raise EmbeddingConfigError(f"unsupported precision: {self.precision!r}")
        object.__setattr__(self, "precision", precision)

        schema = _require_non_empty_str(self.schema_version, "schema_version")
        if schema != SCHEMA_VERSION:
            raise EmbeddingConfigError(
                f"schema_version must be {SCHEMA_VERSION!r}; got {schema!r}"
            )
        object.__setattr__(self, "schema_version", schema)

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
            "precision": self.precision,
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
    def may_authorize_release(self) -> bool:
        return (
            is_production_backend(self.backend)
            and not is_projection_backend(self.backend)
            and self.model_id == PINNED_MODEL_ID
            and self.model_revision == PINNED_MODEL_REVISION
            and self.pooling == PINNED_POOLING
            and self.normalization == PINNED_NORMALIZATION
            and self.dimension == PINNED_DIMENSION
            and self.max_tokens == PINNED_MAX_TOKENS
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "OpenUsLawEmbeddingConfig":
        if not isinstance(value, Mapping):
            raise EmbeddingConfigError("config payload must be a mapping")
        fields = value.get("input_fields", PINNED_INPUT_FIELDS)
        if isinstance(fields, list):
            fields = tuple(fields)
        fallback = value.get("device_fallback", DeviceFallbackPolicy.FALLBACK_CPU)
        return cls(
            model_id=value.get("model_id", PINNED_MODEL_ID),
            model_revision=value.get("model_revision", PINNED_MODEL_REVISION),
            license=value.get("license", PINNED_MODEL_LICENSE),
            max_tokens=value.get("max_tokens", PINNED_MAX_TOKENS),
            pooling=value.get("pooling", PINNED_POOLING),
            normalization=value.get("normalization", PINNED_NORMALIZATION),
            input_fields=fields,
            dimension=value.get("dimension", PINNED_DIMENSION),
            vector_space_id=str(value.get("vector_space_id") or ""),
            config_cid=str(value.get("config_cid") or ""),
            backend=value.get("backend", DEFAULT_BACKEND),
            provider=value.get("provider", DEFAULT_PROVIDER),
            device=value.get("device", DEFAULT_DEVICE),
            device_fallback=fallback,
            batch_size=value.get("batch_size", DEFAULT_BATCH_SIZE),
            precision=value.get("precision", DEFAULT_PRECISION),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
        )


def default_embedding_config() -> OpenUsLawEmbeddingConfig:
    """Return the sealed production pin (sentence-transformers, not projection)."""

    return OpenUsLawEmbeddingConfig()


def fixture_embedding_config(**overrides: Any) -> OpenUsLawEmbeddingConfig:
    """Offline projection pin for unit fixtures. Cannot authorize release."""

    payload = {
        "backend": PROJECTION_BACKEND,
        "provider": "local",
        "device": "cpu",
        "device_fallback": DeviceFallbackPolicy.FALLBACK_CPU,
    }
    payload.update(overrides)
    return OpenUsLawEmbeddingConfig.from_mapping(payload)


# ---------------------------------------------------------------------------
# Admitted chunks
# ---------------------------------------------------------------------------


def _validate_durable_cid(value: Any, name: str) -> str:
    text = _require_non_empty_str(value, name, maximum=256)
    reject_positional_durable_identity(text, name=name)
    if text.lower().startswith("row-"):
        raise PositionalIdentityError(
            f"{name} must not be a positional identity token: {text!r}"
        )
    try:
        return validate_entry_cid(text, name=name)
    except (InvalidDigestError, MutableReferenceError, PositionalIdentityError):
        raise
    except Exception as exc:  # pragma: no cover - schema raises typed errors
        raise OpenUsLawEmbeddingError(f"{name} is not a durable CID: {text!r}") from exc


@dataclass(frozen=True, slots=True)
class AdmittedChunk:
    """One admitted legal chunk eligible for embedding."""

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
        object.__setattr__(self, "chunk_cid", _validate_durable_cid(self.chunk_cid, "chunk_cid"))
        if not isinstance(self.text, str):
            raise OpenUsLawEmbeddingError("chunk text must be a string")
        if "\x00" in self.text:
            raise OpenUsLawEmbeddingError("chunk text must not contain NUL")
        object.__setattr__(self, "text", self.text)

        if self.entry_cid is not None and str(self.entry_cid).strip():
            object.__setattr__(
                self, "entry_cid", _validate_durable_cid(self.entry_cid, "entry_cid")
            )
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
            raise OpenUsLawEmbeddingError("extra_fields must be a mapping")
        clean = {
            _require_non_empty_str(k, "extra_fields key"): str(v)
            for k, v in extras.items()
        }
        object.__setattr__(self, "extra_fields", clean)

    def resolve_input_text(self, input_fields: Sequence[str]) -> str:
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
            raise OpenUsLawEmbeddingError("admitted chunk must be a mapping")
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


def iter_admitted_chunks(
    chunks: Iterable[AdmittedChunk | Mapping[str, Any]],
) -> Iterator[AdmittedChunk]:
    """Yield admitted chunks with no per-call ceiling.

    Duplicate or positional ``chunk_cid`` values fail closed. Sequences
    larger than the exact-51 seed are accepted.
    """

    if isinstance(chunks, (str, bytes)):
        raise OpenUsLawEmbeddingError("chunks must be a sequence or iterable of mappings")
    assert_no_truncating_chunk_ceiling()
    seen: set[str] = set()
    count = 0
    for index, item in enumerate(chunks):
        if isinstance(item, AdmittedChunk):
            chunk = item
        elif isinstance(item, Mapping):
            chunk = AdmittedChunk.from_mapping(item)
        else:
            raise OpenUsLawEmbeddingError(
                f"chunks[{index}] must be AdmittedChunk or mapping"
            )
        if chunk.chunk_cid in seen:
            raise ChunkKeyMismatchError(
                f"duplicate admitted chunk_cid: {chunk.chunk_cid!r}"
            )
        seen.add(chunk.chunk_cid)
        count += 1
        yield chunk
    assert_chunk_stream_unbounded(count)


def coerce_admitted_chunks(
    chunks: Iterable[AdmittedChunk | Mapping[str, Any]],
) -> tuple[AdmittedChunk, ...]:
    """Materialize admitted chunks. There is no 100,000-item cap."""

    return tuple(iter_admitted_chunks(chunks))


# ---------------------------------------------------------------------------
# Records / results
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
        object.__setattr__(
            self, "chunk_cid", _validate_durable_cid(self.chunk_cid, "chunk_cid")
        )
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
        object.__setattr__(self, "l2_norm", measured)
        model_id, model_revision = require_pinned_gte_small(
            model_id=self.model_id, model_revision=self.model_revision
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

    def checkpoint_dict(self) -> dict[str, Any]:
        return {
            "chunk_cid": self.chunk_cid,
            "chunk_id": self.chunk_id,
            "dimension": self.dimension,
            "embedding": list(self.embedding),
            "entry_cid": self.entry_cid,
            "input_hash": self.input_hash,
            "l2_norm": self.l2_norm,
        }


@dataclass(frozen=True, slots=True)
class MissingVectorDiagnostic:
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
class DeviceEvidence:
    requested: str
    selected: str
    fallback_applied: bool
    precision: str
    runtime: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fallback_applied": self.fallback_applied,
            "precision": self.precision,
            "requested": self.requested,
            "runtime": dict(self.runtime),
            "selected": self.selected,
        }


@dataclass(frozen=True, slots=True)
class TruncationEvidence:
    applied: bool
    max_seq_length: int | None
    tokenizer_model_max_length: int | None
    max_tokens: int = PINNED_MAX_TOKENS

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied": self.applied,
            "max_seq_length": self.max_seq_length,
            "max_tokens": self.max_tokens,
            "tokenizer_model_max_length": self.tokenizer_model_max_length,
        }

    @property
    def satisfies_contract(self) -> bool:
        return (
            self.applied
            and self.max_tokens == PINNED_MAX_TOKENS
            and self.max_seq_length == PINNED_MAX_TOKENS
        )


@dataclass(frozen=True, slots=True)
class EmbeddingGenerationResult:
    """Result of embedding a closed admitted-chunk set."""

    embeddings: Mapping[str, EmbeddingRecord]
    config: OpenUsLawEmbeddingConfig
    admitted_chunk_cids: tuple[str, ...]
    device: DeviceEvidence
    truncation: TruncationEvidence
    missing: tuple[MissingVectorDiagnostic, ...] = ()
    batch_count: int = 0
    resumed_chunk_cids: tuple[str, ...] = ()
    executed_chunk_cids: tuple[str, ...] = ()
    embedder_kind: str = PRODUCTION_BACKEND
    real_inference: bool = False
    model_file_evidence: Mapping[str, Any] = field(default_factory=dict)
    checkpoint_path: str = ""
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.embeddings, Mapping):
            raise OpenUsLawEmbeddingError("embeddings must be a mapping")
        object.__setattr__(self, "embeddings", dict(self.embeddings))
        object.__setattr__(self, "model_file_evidence", dict(self.model_file_evidence))
        assert_output_keys_match_admitted(
            self.embeddings,
            self.admitted_chunk_cids,
            missing=self.missing,
        )

    @property
    def vectors_by_chunk_cid(self) -> dict[str, tuple[float, ...]]:
        return {cid: rec.embedding for cid, rec in self.embeddings.items()}

    @property
    def authorizing_for_release(self) -> bool:
        return release_authorization_reasons(self) == ()

    def to_dict(self, *, include_vectors: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "admitted_chunk_cids": list(self.admitted_chunk_cids),
            "authorizing_for_release": self.authorizing_for_release,
            "batch_count": self.batch_count,
            "checkpoint_path": self.checkpoint_path,
            "config": self.config.to_dict(),
            "device": self.device.to_dict(),
            "embedder_kind": self.embedder_kind,
            "executed_chunk_cids": list(self.executed_chunk_cids),
            "missing": [item.to_dict() for item in self.missing],
            "model_file_evidence": dict(self.model_file_evidence),
            "real_inference": self.real_inference,
            "resumed_chunk_cids": list(self.resumed_chunk_cids),
            "schema_version": self.schema_version,
            "truncation": self.truncation.to_dict(),
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
    unknown_missing = missing_cids - admitted_set
    if unknown_missing:
        raise ChunkKeyMismatchError(
            f"missing diagnostics reference non-admitted chunks: "
            f"{sorted(unknown_missing)!r}"
        )


# ---------------------------------------------------------------------------
# Release authorization (projection cannot authorize)
# ---------------------------------------------------------------------------


def release_authorization_reasons(
    result: EmbeddingGenerationResult,
) -> tuple[str, ...]:
    """Return the reasons *result* cannot authorize a production release."""

    reasons: list[str] = []
    if is_projection_backend(result.config.backend) or is_projection_backend(
        result.embedder_kind
    ):
        reasons.append("projection_backend")
    if not is_production_backend(result.config.backend):
        reasons.append("backend_not_sentence_transformers")
    if not result.real_inference:
        reasons.append("real_inference_required")
    if result.embedder_kind in {"injected", "fixture"} or (
        result.embedder_kind in PROJECTION_BACKENDS
    ):
        reasons.append("non_production_embedder")
    if not result.config.may_authorize_release:
        reasons.append("pin_does_not_authorize")
    if not result.truncation.satisfies_contract:
        reasons.append("real_512_token_truncation_missing")
    if result.missing:
        reasons.append("missing_vectors")
    if set(result.embeddings) != set(result.admitted_chunk_cids):
        reasons.append("admitted_key_mismatch")
    if PROJECTION_FALLBACK_AUTHORIZES_RELEASE:
        reasons.append("projection_fallback_flag_must_be_false")
    return tuple(reasons)


def production_inference_evidence_reasons(
    evidence: Mapping[str, Any] | Any,
) -> tuple[str, ...]:
    """Validate durable evidence for pinned real GTE-small inference.

    This predicate is intentionally independent of a dataset adapter.  A
    checkpoint boolean is not evidence by itself: production consumers must
    also see the exact immutable model revision, hashed local model files,
    live runtime provenance, and the concrete 512-token truncation settings.
    """

    if not isinstance(evidence, Mapping):
        return ("inference_evidence_missing",)
    reasons: list[str] = []
    if evidence.get("real_inference") is not True:
        reasons.append("real_inference_required")
    if evidence.get("embedder_kind") != PRODUCTION_BACKEND:
        reasons.append("backend_not_sentence_transformers")

    truncation = evidence.get("truncation")
    if not isinstance(truncation, Mapping) or (
        truncation.get("applied") is not True
        or truncation.get("max_tokens") != PINNED_MAX_TOKENS
        or truncation.get("max_seq_length") != PINNED_MAX_TOKENS
        or evidence.get("truncation_satisfies_contract") is not True
    ):
        reasons.append("real_512_token_truncation_missing")

    model_files = evidence.get("model_file_evidence")
    if not isinstance(model_files, Mapping):
        reasons.append("model_file_evidence_missing")
    else:
        files = model_files.get("files")
        file_count = model_files.get("file_count")
        if model_files.get("revision") != PINNED_MODEL_REVISION:
            reasons.append("model_revision_evidence_mismatch")
        if (
            isinstance(file_count, bool)
            or not isinstance(file_count, int)
            or file_count < 1
            or not isinstance(files, Sequence)
            or isinstance(files, (str, bytes, bytearray))
            or not files
            or len(files) > file_count
        ):
            reasons.append("model_file_hashes_missing")
        else:
            observed_paths: set[str] = set()
            malformed = False
            for item in files:
                if not isinstance(item, Mapping):
                    malformed = True
                    break
                path = str(item.get("path") or "")
                digest = str(item.get("sha256") or "")
                pure_path = PurePosixPath(path)
                if (
                    not path
                    or pure_path.is_absolute()
                    or ".." in pure_path.parts
                    or path in observed_paths
                    or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                ):
                    malformed = True
                    break
                observed_paths.add(path)
            if malformed:
                reasons.append("model_file_hashes_malformed")

    device = evidence.get("device")
    runtime = device.get("runtime") if isinstance(device, Mapping) else None
    if not isinstance(runtime, Mapping) or (
        runtime.get("sentence_transformers_available") is not True
        or not str(runtime.get("sentence_transformers_version") or "").strip()
        or not str(runtime.get("torch_version") or "").strip()
    ):
        reasons.append("runtime_evidence_missing")
    return tuple(reasons)


def production_inference_evidence_satisfies_contract(
    evidence: Mapping[str, Any] | Any,
) -> bool:
    """Return whether *evidence* proves the shared pinned inference contract."""

    return not production_inference_evidence_reasons(evidence)


def authorize_embedding_release(result: EmbeddingGenerationResult) -> None:
    """Fail closed unless *result* is real pinned sentence-transformers output."""

    reasons = release_authorization_reasons(result)
    if not reasons:
        return
    if "projection_backend" in reasons or is_projection_backend(result.config.backend):
        raise ProjectionReleaseAuthorizationError(
            "local deterministic projection cannot authorize an Open US Law "
            f"release; reasons={list(reasons)}"
        )
    raise ReleaseAuthorizationError(
        "embedding result cannot authorize release; "
        f"reasons={list(reasons)}"
    )


def projection_cannot_authorize_release() -> bool:
    return not PROJECTION_FALLBACK_AUTHORIZES_RELEASE


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


def deterministic_project(
    texts: Sequence[str],
    *,
    dimension: int = PINNED_DIMENSION,
    normalize: bool = True,
) -> list[list[float]]:
    """Fixture-only hashed projection. Cannot authorize release."""

    vectors: list[list[float]] = []
    for text in texts:
        normalized = normalize_embedding_text(text)
        projected = hashed_term_projection(normalized, dimension=dimension)
        if normalize:
            projected = l2_normalize(projected)
        vectors.append([float(x) for x in projected])
    return vectors


def apply_real_512_token_truncation(
    model: Any,
    *,
    max_tokens: int = PINNED_MAX_TOKENS,
) -> TruncationEvidence:
    """Assign the real tokenizer truncation window to 512 tokens.

    The reused US Code helper encodes without setting ``max_seq_length``.
    Production Open US Law inference must set it on the model and, when
    present, the tokenizer.
    """

    if max_tokens != PINNED_MAX_TOKENS:
        raise TruncationContractError(
            f"truncation window must be {PINNED_MAX_TOKENS}; got {max_tokens}"
        )
    try:
        model.max_seq_length = PINNED_MAX_TOKENS
    except Exception as exc:
        raise TruncationContractError(
            "failed to assign model.max_seq_length=512"
        ) from exc
    tokenizer = getattr(model, "tokenizer", None)
    tokenizer_max: int | None = None
    if tokenizer is not None:
        try:
            tokenizer.model_max_length = PINNED_MAX_TOKENS
            tokenizer_max = int(tokenizer.model_max_length)
        except Exception as exc:
            raise TruncationContractError(
                "failed to assign tokenizer.model_max_length=512"
            ) from exc
    assigned = getattr(model, "max_seq_length", None)
    try:
        assigned_int = int(assigned) if assigned is not None else None
    except (TypeError, ValueError) as exc:
        raise TruncationContractError(
            f"model.max_seq_length is not an int: {assigned!r}"
        ) from exc
    if assigned_int != PINNED_MAX_TOKENS:
        raise TruncationContractError(
            f"model.max_seq_length must be {PINNED_MAX_TOKENS}; got {assigned_int!r}"
        )
    return TruncationEvidence(
        applied=True,
        max_seq_length=assigned_int,
        tokenizer_model_max_length=tokenizer_max,
        max_tokens=PINNED_MAX_TOKENS,
    )


def load_sentence_transformer_model(
    config: OpenUsLawEmbeddingConfig,
    device: str,
) -> Any:
    """Load the pinned revision via sentence-transformers."""

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise InferenceBackendError(
            "sentence-transformers is required for production GTE embeddings; "
            "install sentence-transformers or inject a pin-compatible embedder"
        ) from exc
    return SentenceTransformer(
        config.model_id,
        revision=config.model_revision,
        device=device,
    )


def build_pinned_model_token_counter(
    config: OpenUsLawEmbeddingConfig | None = None,
    *,
    tokenizer: Any | None = None,
    local_files_only: bool = False,
) -> tuple[Callable[[str], int], str]:
    """Build the exact GTE-small token counter used before chunk persistence.

    Chunkers may use structure-aware or whitespace planning internally, but a
    production chunk store must validate the final embedding text against the
    model's real WordPiece tokenizer.  Counting includes model special tokens
    and explicitly disables truncation, so a value above 512 cannot be hidden
    by the sentence-transformers inference ceiling.
    """

    selected = config or default_embedding_config()
    if not isinstance(selected, OpenUsLawEmbeddingConfig):
        raise EmbeddingConfigError("config must be an OpenUsLawEmbeddingConfig")
    require_pinned_gte_small(
        model_id=selected.model_id,
        model_revision=selected.model_revision,
    )
    resolved = tokenizer
    if resolved is None:
        try:
            from transformers import AutoTokenizer
        except ImportError as exc:
            raise InferenceBackendError(
                "transformers is required for exact GTE-small token counting"
            ) from exc
        try:
            resolved = AutoTokenizer.from_pretrained(
                selected.model_id,
                revision=selected.model_revision,
                local_files_only=bool(local_files_only),
            )
        except Exception as exc:
            raise InferenceBackendError(
                "failed to load the pinned GTE-small tokenizer at its exact revision"
            ) from exc
    if not callable(resolved):
        raise InferenceBackendError("pinned model tokenizer must be callable")

    def count_model_tokens(text: str) -> int:
        try:
            encoded = resolved(
                str(text if text is not None else ""),
                add_special_tokens=True,
                truncation=False,
                return_attention_mask=False,
                return_token_type_ids=False,
            )
            token_ids = encoded["input_ids"]
            count = len(token_ids)
        except Exception as exc:
            raise TruncationContractError(
                "failed to count untruncated pinned-model input tokens"
            ) from exc
        if count < 0:
            raise TruncationContractError("pinned-model token count is negative")
        return count

    # Exercise the contract immediately instead of deferring a broken
    # tokenizer surface until a multi-hour corpus build.
    if count_model_tokens("") < 1:
        raise TruncationContractError(
            "pinned tokenizer did not account for required special tokens"
        )
    return count_model_tokens, PINNED_TOKEN_COUNTER_ID


def build_sentence_transformers_embedder(
    config: OpenUsLawEmbeddingConfig,
    *,
    device: str | None = None,
    model_factory: ModelFactory | None = None,
) -> tuple[EmbeddingFunction, TruncationEvidence, dict[str, Any], bool]:
    """Construct the production embedder and record truncation evidence.

    Returns ``(embed_fn, truncation, model_file_evidence, real_inference)``.
    """

    selected = device or config.device
    factory = model_factory or load_sentence_transformer_model
    try:
        model = factory(config, selected)
    except InferenceBackendError:
        raise
    except Exception as exc:
        raise InferenceBackendError(
            "failed to load pinned thenlper/gte-small via sentence-transformers: "
            f"{exc}"
        ) from exc
    truncation = apply_real_512_token_truncation(model, max_tokens=config.max_tokens)
    model_files = collect_model_file_evidence(model)
    real_inference = model_factory is None

    def _embed(texts: Sequence[str]) -> list[list[float]]:
        vectors = model.encode(
            list(texts),
            batch_size=config.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=config.normalization == "l2",
        )
        return [list(map(float, row)) for row in vectors]

    return _embed, truncation, model_files, real_inference


def build_projection_embedder(config: OpenUsLawEmbeddingConfig) -> EmbeddingFunction:
    def _embed(texts: Sequence[str]) -> list[list[float]]:
        return deterministic_project(
            texts,
            dimension=config.dimension,
            normalize=config.normalization == "l2",
        )

    return _embed


def resolve_embedder(
    config: OpenUsLawEmbeddingConfig,
    *,
    embedder: EmbeddingFunction | None = None,
    device: str | None = None,
    model_factory: ModelFactory | None = None,
) -> tuple[EmbeddingFunction, TruncationEvidence, dict[str, Any], str, bool]:
    """Resolve the embedder, truncation evidence, and inference kind."""

    if embedder is not None:
        kind = "injected"
        if is_projection_backend(config.backend):
            kind = PROJECTION_BACKEND
        return (
            embedder,
            TruncationEvidence(
                applied=False,
                max_seq_length=None,
                tokenizer_model_max_length=None,
                max_tokens=config.max_tokens,
            ),
            {"file_count": 0, "files": [], "revision": config.model_revision},
            kind,
            False,
        )
    if is_projection_backend(config.backend):
        return (
            build_projection_embedder(config),
            TruncationEvidence(
                applied=False,
                max_seq_length=None,
                tokenizer_model_max_length=None,
                max_tokens=config.max_tokens,
            ),
            {"file_count": 0, "files": [], "revision": config.model_revision},
            PROJECTION_BACKEND,
            False,
        )
    fn, truncation, files, real = build_sentence_transformers_embedder(
        config, device=device, model_factory=model_factory
    )
    kind = PRODUCTION_BACKEND
    if model_factory is not None:
        kind = "injected_sentence_transformers"
        real = False
    return fn, truncation, files, kind, real


# ---------------------------------------------------------------------------
# Checkpoints
# ---------------------------------------------------------------------------


def write_bytes_atomic(path: PathLike, data: bytes) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".oul-embed-",
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


@dataclass
class EmbeddingCheckpoint:
    """Resumable checkpoint of completed vectors for one pin."""

    config_digest: str
    completed: dict[str, dict[str, Any]] = field(default_factory=dict)
    schema_version: str = CHECKPOINT_SCHEMA_VERSION
    task_id: str = TASK_ID
    batch_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_count": self.batch_count,
            "completed": dict(sorted(self.completed.items())),
            "completed_chunk_cids": sorted(self.completed),
            "config_digest": self.config_digest,
            "schema_version": self.schema_version,
            "task_id": self.task_id,
        }

    @property
    def completed_chunk_cids(self) -> list[str]:
        return sorted(self.completed)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EmbeddingCheckpoint":
        if not isinstance(value, Mapping):
            raise EmbeddingCheckpointError("checkpoint must be a mapping")
        schema = value.get("schema_version")
        if schema != CHECKPOINT_SCHEMA_VERSION:
            raise EmbeddingCheckpointError(
                f"unsupported checkpoint schema_version: {schema!r}"
            )
        if value.get("task_id") not in {None, TASK_ID} and value.get("task_id") != TASK_ID:
            raise EmbeddingCheckpointError(
                f"checkpoint task_id {value.get('task_id')!r} != {TASK_ID!r}"
            )
        digest = _require_non_empty_str(
            value.get("config_digest"), "config_digest", maximum=128
        )
        raw_completed = value.get("completed") or {}
        if not isinstance(raw_completed, Mapping):
            raise EmbeddingCheckpointError("completed must be a mapping")
        completed: dict[str, dict[str, Any]] = {}
        for key, record in raw_completed.items():
            cid = _validate_durable_cid(key, "completed chunk_cid")
            if not isinstance(record, Mapping):
                raise EmbeddingCheckpointError(
                    f"completed[{cid!r}] must be a mapping"
                )
            completed[cid] = dict(record)
        if not completed:
            legacy = value.get("completed_chunk_cids") or []
            if isinstance(legacy, list) and legacy:
                raise EmbeddingCheckpointError(
                    "checkpoint lists completed_chunk_cids without stored vectors; "
                    "cannot resume without re-embedding"
                )
        batch_count = value.get("batch_count", 0)
        if isinstance(batch_count, bool) or not isinstance(batch_count, int) or batch_count < 0:
            raise EmbeddingCheckpointError("batch_count must be a non-negative integer")
        return cls(
            config_digest=digest,
            completed=completed,
            batch_count=batch_count,
        )


def load_checkpoint(path: PathLike) -> EmbeddingCheckpoint:
    checkpoint_path = Path(path)
    if not checkpoint_path.is_file():
        raise EmbeddingCheckpointError(f"checkpoint not found: {checkpoint_path}")
    try:
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EmbeddingCheckpointError(f"invalid checkpoint JSON: {exc}") from exc
    return EmbeddingCheckpoint.from_mapping(payload)


def write_checkpoint_atomic(
    path: PathLike,
    checkpoint: EmbeddingCheckpoint,
) -> Path:
    return write_json_atomic(path, checkpoint.to_dict())


def assert_checkpoint_compatible(
    checkpoint: EmbeddingCheckpoint,
    config: OpenUsLawEmbeddingConfig,
) -> None:
    if checkpoint.schema_version != CHECKPOINT_SCHEMA_VERSION:
        raise EmbeddingCheckpointError(
            f"checkpoint schema_version {checkpoint.schema_version!r} "
            f"!= {CHECKPOINT_SCHEMA_VERSION!r}"
        )
    if checkpoint.config_digest != config.digest:
        raise EmbeddingCheckpointError(
            "checkpoint config_digest does not match active pin"
        )
    if checkpoint.task_id != TASK_ID:
        raise EmbeddingCheckpointError(
            f"checkpoint task_id {checkpoint.task_id!r} != {TASK_ID!r}"
        )


def record_from_checkpoint(
    cid: str,
    payload: Mapping[str, Any],
    config: OpenUsLawEmbeddingConfig,
) -> EmbeddingRecord:
    embedding = payload.get("embedding")
    if not isinstance(embedding, (list, tuple)):
        raise EmbeddingCheckpointError(f"checkpoint vector missing for {cid}")
    return EmbeddingRecord(
        chunk_cid=cid,
        embedding=tuple(float(x) for x in embedding),
        dimension=int(payload.get("dimension") or config.dimension),
        input_hash=str(payload.get("input_hash") or ""),
        model_id=config.model_id,
        model_revision=config.model_revision,
        vector_space_id=config.vector_space_id,
        pooling=config.pooling,
        normalization=config.normalization,
        l2_norm=float(payload.get("l2_norm") or 0.0),
        config_cid=config.config_cid,
        entry_cid=payload.get("entry_cid"),
        chunk_id=payload.get("chunk_id"),
    )


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class OpenUsLawEmbeddingGenerator:
    """Stream real pinned gte-small embeddings for admitted legal chunks."""

    def __init__(
        self,
        config: OpenUsLawEmbeddingConfig | None = None,
        *,
        embedder: EmbeddingFunction | None = None,
        device_probe: Callable[[str], bool] | None = None,
        model_factory: ModelFactory | None = None,
    ) -> None:
        self._config = config or default_embedding_config()
        if not isinstance(self._config, OpenUsLawEmbeddingConfig):
            raise EmbeddingConfigError("config must be OpenUsLawEmbeddingConfig")
        self._injected_embedder = embedder
        self._device_probe = device_probe
        self._model_factory = model_factory
        if embedder is not None and not callable(embedder):
            raise EmbeddingConfigError("embedder must be callable")

    @property
    def config(self) -> OpenUsLawEmbeddingConfig:
        return self._config

    def resolve_device(self) -> tuple[str, bool]:
        return select_device(
            self._config.device,
            fallback=self._config.device_fallback,
            probe=self._device_probe,
        )

    def embed_texts(
        self,
        texts: Sequence[str],
        *,
        embedder: EmbeddingFunction,
    ) -> list[tuple[float, ...]]:
        raw = embedder([str(t if t is not None else "") for t in texts])
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise OpenUsLawEmbeddingError("embedder must return a sequence of vectors")
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
        chunks: Iterable[AdmittedChunk | Mapping[str, Any]],
        *,
        allow_missing: bool = False,
        checkpoint_path: PathLike | None = None,
        resume: bool = True,
    ) -> EmbeddingGenerationResult:
        """Generate embeddings; keys match admitted CIDs; resume skips work."""

        admitted = coerce_admitted_chunks(chunks)
        admitted_cids = tuple(chunk.chunk_cid for chunk in admitted)
        device_selected, fallback_applied = self.resolve_device()
        runtime = collect_runtime_evidence(device_selected)
        device = DeviceEvidence(
            requested=self._config.device,
            selected=device_selected,
            fallback_applied=fallback_applied,
            precision=self._config.precision,
            runtime=runtime,
        )

        embedder, truncation, model_files, embedder_kind, real_inference = (
            resolve_embedder(
                self._config,
                embedder=self._injected_embedder,
                device=device_selected,
                model_factory=self._model_factory,
            )
        )

        completed_records: dict[str, EmbeddingRecord] = {}
        checkpoint = EmbeddingCheckpoint(config_digest=self._config.digest)
        if checkpoint_path is not None and resume and Path(checkpoint_path).is_file():
            checkpoint = load_checkpoint(checkpoint_path)
            assert_checkpoint_compatible(checkpoint, self._config)
            for cid, payload in checkpoint.completed.items():
                completed_records[cid] = record_from_checkpoint(
                    cid, payload, self._config
                )

        embeddings: dict[str, EmbeddingRecord] = {}
        missing: list[MissingVectorDiagnostic] = []
        resumed: list[str] = []
        executed: list[str] = []
        batch_size = self._config.batch_size
        batch_count = checkpoint.batch_count

        pending: list[AdmittedChunk] = []
        for chunk in admitted:
            existing = completed_records.get(chunk.chunk_cid)
            if existing is not None:
                expected_hash = input_content_hash(
                    chunk.resolve_input_text(self._config.input_fields)
                )
                if existing.input_hash != expected_hash:
                    raise EmbeddingCheckpointError(
                        f"input hash changed for completed chunk {chunk.chunk_cid}"
                    )
                embeddings[chunk.chunk_cid] = existing
                resumed.append(chunk.chunk_cid)
                continue
            pending.append(chunk)

        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            batch_count += 1
            texts = [
                chunk.resolve_input_text(self._config.input_fields) for chunk in batch
            ]
            input_hashes = [input_content_hash(text) for text in texts]
            try:
                vectors = self.embed_texts(texts, embedder=embedder)
            except MissingVectorError as exc:
                if not allow_missing:
                    raise
                for chunk in batch:
                    missing.append(
                        MissingVectorDiagnostic(
                            chunk_cid=chunk.chunk_cid, reason=str(exc)
                        )
                    )
                continue

            for chunk, vector, in_hash in zip(batch, vectors, input_hashes):
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
                executed.append(chunk.chunk_cid)
                checkpoint.completed[chunk.chunk_cid] = record.checkpoint_dict()

            checkpoint.batch_count = batch_count
            if checkpoint_path is not None:
                write_checkpoint_atomic(checkpoint_path, checkpoint)

        if not allow_missing and missing:
            raise MissingVectorError(f"{len(missing)} vectors missing after generation")

        return EmbeddingGenerationResult(
            embeddings=embeddings,
            config=self._config,
            admitted_chunk_cids=admitted_cids,
            device=device,
            truncation=truncation,
            missing=tuple(missing),
            batch_count=batch_count,
            resumed_chunk_cids=tuple(resumed),
            executed_chunk_cids=tuple(executed),
            embedder_kind=embedder_kind,
            real_inference=real_inference,
            model_file_evidence=model_files,
            checkpoint_path="" if checkpoint_path is None else str(checkpoint_path),
        )


def generate_open_us_law_embeddings(
    chunks: Iterable[AdmittedChunk | Mapping[str, Any]],
    *,
    config: OpenUsLawEmbeddingConfig | None = None,
    embedder: EmbeddingFunction | None = None,
    allow_missing: bool = False,
    checkpoint_path: PathLike | None = None,
    resume: bool = True,
    device_probe: Callable[[str], bool] | None = None,
    model_factory: ModelFactory | None = None,
) -> EmbeddingGenerationResult:
    """Convenience entry point for pinned Open US Law embedding generation."""

    generator = OpenUsLawEmbeddingGenerator(
        config=config,
        embedder=embedder,
        device_probe=device_probe,
        model_factory=model_factory,
    )
    return generator.generate(
        chunks,
        allow_missing=allow_missing,
        checkpoint_path=checkpoint_path,
        resume=resume,
    )


# ---------------------------------------------------------------------------
# Receipt
# ---------------------------------------------------------------------------


def default_embedding_receipt_path() -> Path:
    return Path(__file__).resolve().parents[3] / RECEIPT_RELATIVE_PATH


def software_contract_flags() -> dict[str, Any]:
    return {
        "authorizing_for_publication": AUTHORIZES_PUBLICATION,
        "authorizing_for_release": False,
        "projection_fallback_authorizes_release": PROJECTION_FALLBACK_AUTHORIZES_RELEASE,
        "proves_software_contract_only": PROVES_SOFTWARE_CONTRACT_ONLY,
        "real_sentence_transformers_required": True,
    }


def fixture_sample_chunks() -> list[dict[str, str]]:
    return [
        {
            "chunk_cid": (
                "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            ),
            "entry_cid": (
                "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            ),
            "text": "Every admitted statute chunk is embedded with pinned gte-small.",
            "heading": "Embedding contract",
            "title": "1",
            "section": "1",
            "legal_id": "oul:or:statutes:1:1:1",
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
            "text": "Projection fallback cannot authorize an Open US Law release.",
            "heading": "Release gate",
            "title": "1",
            "section": "2",
            "legal_id": "oul:or:statutes:1:1:2",
        },
    ]


def _acceptance_block() -> dict[str, bool]:
    return {
        "device_evidence_recorded": True,
        "every_admitted_chunk_embedded": True,
        "input_hashes_recorded": True,
        "l2_normalization": True,
        "mean_pooling": True,
        "no_per_call_chunk_ceiling": PER_CALL_CHUNK_CEILING is None,
        "pinned_thenlper_gte_small": True,
        "projection_fallback_cannot_authorize_release": True,
        "real_512_token_truncation": True,
        "resumable_checkpoints": True,
        "sentence_transformers_required_for_release": True,
        "vector_dimension_384": True,
    }


def _sealed_runtime_evidence(device: str = "cpu") -> dict[str, Any]:
    """Host-independent runtime block for the software-contract receipt."""

    return {
        "cuda_available": False,
        "cuda_device_name": None,
        "cuda_version": None,
        "device": device,
        "note": (
            "Sealed software-contract receipt does not record host runtime "
            "probes; production runs attach live device evidence separately."
        ),
        "precision": DEFAULT_PRECISION,
        "python": None,
        "sentence_transformers_available": None,
        "sentence_transformers_version": None,
        "torch_version": None,
    }


def build_embedding_receipt(
    *,
    result: EmbeddingGenerationResult | None = None,
) -> dict[str, Any]:
    """Build the sealed software-contract embedding receipt."""

    config = default_embedding_config()
    fixture_config = fixture_embedding_config()
    demo = result
    if demo is None:
        demo = generate_open_us_law_embeddings(
            fixture_sample_chunks(),
            config=fixture_config,
            device_probe=lambda device: str(device).startswith("cpu"),
        )
    try:
        authorize_embedding_release(demo)
        projection_blocked = False
        projection_error = None
    except (ProjectionReleaseAuthorizationError, ReleaseAuthorizationError) as exc:
        projection_blocked = True
        projection_error = exc.code

    payload: dict[str, Any] = {
        "acceptance": _acceptance_block(),
        "adr_path": ADR_PATH,
        "authorizing_for_publication": False,
        "authorizing_for_release": False,
        "backend": {
            "default": DEFAULT_BACKEND,
            "production": PRODUCTION_BACKEND,
            "projection": PROJECTION_BACKEND,
            "projection_authorizes_release": PROJECTION_FALLBACK_AUTHORIZES_RELEASE,
            "provider": DEFAULT_PROVIDER,
        },
        "checks": {
            "default_backend_is_sentence_transformers": DEFAULT_BACKEND
            == PRODUCTION_BACKEND,
            "demo_projection_blocked_from_release": projection_blocked,
            "demo_projection_error": projection_error,
            "input_hashes_present": all(
                rec.input_hash for rec in demo.embeddings.values()
            ),
            "keys_match_admitted": set(demo.embeddings) == set(demo.admitted_chunk_cids),
            "no_per_call_chunk_ceiling": PER_CALL_CHUNK_CEILING is None,
            "per_call_ceiling_below_exact_51_seed": False,
            "pinned_dimension": PINNED_DIMENSION,
            "pinned_max_tokens": PINNED_MAX_TOKENS,
            "pinned_model_id": PINNED_MODEL_ID,
            "pinned_model_revision": PINNED_MODEL_REVISION,
            "pinned_normalization": PINNED_NORMALIZATION,
            "pinned_pooling": PINNED_POOLING,
            "requires_real_512_token_truncation": REQUIRES_REAL_512_TOKEN_TRUNCATION,
            "unit_norms": all(
                rec.l2_norm == 0.0 or abs(rec.l2_norm - 1.0) <= NORM_TOLERANCE
                for rec in demo.embeddings.values()
            ),
        },
        "config": config.to_dict(),
        "demo": {
            "admitted_chunk_cids": list(demo.admitted_chunk_cids),
            "authorizing_for_release": demo.authorizing_for_release,
            "backend": demo.config.backend,
            "device": {
                **demo.device.to_dict(),
                "runtime": _sealed_runtime_evidence(demo.device.selected),
            },
            "embedder_kind": demo.embedder_kind,
            "input_hashes": {
                cid: rec.input_hash for cid, rec in sorted(demo.embeddings.items())
            },
            "real_inference": demo.real_inference,
            "release_authorization_reasons": list(release_authorization_reasons(demo)),
            "truncation": demo.truncation.to_dict(),
            "vector_count": len(demo.embeddings),
        },
        "description": (
            "Software-contract receipt for OUL-028. Production embedding requires "
            "sentence-transformers inference of thenlper/gte-small at the sealed "
            "revision, 384 dimensions, mean pooling, L2 normalization, real "
            "512-token truncation, input hashes, device evidence, and resumable "
            "checkpoints. Projection output cannot authorize release. This receipt "
            "does not claim the live exact-51 corpus has been embedded."
        ),
        "device": {
            "default": DEFAULT_DEVICE,
            "fallback": DeviceFallbackPolicy.FALLBACK_CPU.value,
            "precision": DEFAULT_PRECISION,
            "supported": sorted(SUPPORTED_DEVICES),
        },
        "exact_51_seed_row_lower_bound": EXACT_51_SEED_ROW_LOWER_BOUND,
        "goal_id": GOAL_ID,
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
        "per_call_chunk_ceiling": PER_CALL_CHUNK_CEILING,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "projection_fallback_authorizes_release": False,
        "proves_software_contract_only": True,
        "real_sentence_transformers_required": True,
        "release_profile": RELEASE_PROFILE,
        "repairs": {
            "area_id": "real_gte_inference",
            "owner_task": TASK_ID,
            "required": [
                (
                    "Require sentence-transformers inference of thenlper/gte-small "
                    f"at revision {PINNED_MODEL_REVISION} for every admitted "
                    "production chunk."
                ),
                (
                    "Set the real tokenizer truncation window to 512 tokens and "
                    "record input, model-file, device, precision, batch, and "
                    "checkpoint evidence."
                ),
                (
                    "Refuse release authorization when the backend is "
                    f"{PROJECTION_BACKEND} or any other fixture projection."
                ),
                (
                    "Stream and checkpoint embeddings so the 100,000-chunk "
                    "per-call cap cannot truncate the exact-51 corpus."
                ),
            ],
        },
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "sealed_at": RECEIPT_SEALED_AT,
        "task_id": TASK_ID,
        "truncation": {
            "method": "sentence_transformers.max_seq_length",
            "required": True,
            "tokens": PINNED_MAX_TOKENS,
        },
    }
    payload.update(software_contract_flags())
    payload["receipt_sha256"] = content_sha256(canonical_json_bytes(
        {key: value for key, value in payload.items() if key != "receipt_sha256"}
    ))
    return payload


def write_embedding_receipt(path: PathLike | None = None) -> Path:
    target = Path(path) if path is not None else default_embedding_receipt_path()
    payload = build_embedding_receipt()
    write_json_atomic(target, payload)
    return target


def load_embedding_receipt(path: PathLike | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else default_embedding_receipt_path()
    if not target.is_file():
        raise OpenUsLawEmbeddingError(f"embedding receipt not found: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise OpenUsLawEmbeddingError("embedding receipt root must be an object")
    return dict(payload)


def assert_embedding_receipt(payload: Mapping[str, Any]) -> None:
    """Fail closed if the receipt would authorize projection or a wrong pin."""

    if payload.get("task_id") != TASK_ID:
        raise OpenUsLawEmbeddingError(f"receipt task_id must be {TASK_ID!r}")
    if payload.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise OpenUsLawEmbeddingError(
            f"receipt schema_version must be {RECEIPT_SCHEMA_VERSION!r}"
        )
    pin = payload.get("model_pin") or {}
    if not isinstance(pin, Mapping):
        raise OpenUsLawEmbeddingError("receipt model_pin must be a mapping")
    if pin.get("model_id") != PINNED_MODEL_ID:
        raise UnpinnedModelError("receipt model_id is not the sealed pin")
    if pin.get("model_revision") != PINNED_MODEL_REVISION:
        raise UnpinnedModelError("receipt model_revision is not the sealed pin")
    if pin.get("dimension") != PINNED_DIMENSION:
        raise DimensionValidationError("receipt dimension is not 384")
    if pin.get("pooling") != PINNED_POOLING:
        raise EmbeddingConfigError("receipt pooling is not mean")
    if pin.get("normalization") != PINNED_NORMALIZATION:
        raise EmbeddingConfigError("receipt normalization is not l2")
    if pin.get("max_tokens") != PINNED_MAX_TOKENS:
        raise TruncationContractError("receipt max_tokens is not 512")
    if payload.get("authorizing_for_release"):
        raise ProjectionReleaseAuthorizationError(
            "software-contract receipt must not authorize release"
        )
    if payload.get("projection_fallback_authorizes_release"):
        raise ProjectionReleaseAuthorizationError(
            "projection fallback cannot authorize release"
        )
    backend = payload.get("backend") or {}
    if isinstance(backend, Mapping) and backend.get("default") != PRODUCTION_BACKEND:
        raise EmbeddingConfigError(
            "receipt default backend must be sentence_transformers"
        )
    if payload.get("per_call_chunk_ceiling") is not None:
        raise EmbeddingConfigError(
            "receipt must not declare a truncating per-call chunk ceiling"
        )


__all__ = [
    "AUTHORIZES_PUBLICATION",
    "CHECKPOINT_SCHEMA_VERSION",
    "DEFAULT_BACKEND",
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_DEVICE",
    "DEFAULT_PRECISION",
    "DEFAULT_PROVIDER",
    "EXACT_51_SEED_ROW_LOWER_BOUND",
    "GOAL_ID",
    "PER_CALL_CHUNK_CEILING",
    "PINNED_DIMENSION",
    "PINNED_MAX_TOKENS",
    "PINNED_MODEL_ID",
    "PINNED_MODEL_REVISION",
    "PINNED_NORMALIZATION",
    "PINNED_POOLING",
    "PINNED_TOKEN_COUNTER_ID",
    "PRODUCTION_BACKEND",
    "PROGRAM_ID",
    "PROJECTION_BACKEND",
    "PROJECTION_FALLBACK_AUTHORIZES_RELEASE",
    "PROVES_SOFTWARE_CONTRACT_ONLY",
    "RECEIPT_SCHEMA_VERSION",
    "REQUIRES_REAL_512_TOKEN_TRUNCATION",
    "SCHEMA_VERSION",
    "TASK_ID",
    "AdmittedChunk",
    "ChunkKeyMismatchError",
    "DeviceEvidence",
    "DeviceFallbackPolicy",
    "DimensionValidationError",
    "EmbeddingCheckpoint",
    "EmbeddingCheckpointError",
    "EmbeddingConfigError",
    "EmbeddingGenerationResult",
    "EmbeddingRecord",
    "HardwareUnavailableError",
    "InferenceBackendError",
    "MissingVectorError",
    "NormValidationError",
    "OpenUsLawEmbeddingConfig",
    "OpenUsLawEmbeddingError",
    "OpenUsLawEmbeddingGenerator",
    "ProjectionReleaseAuthorizationError",
    "ReleaseAuthorizationError",
    "TruncationContractError",
    "TruncationEvidence",
    "UnpinnedModelError",
    "apply_real_512_token_truncation",
    "assert_chunk_stream_unbounded",
    "assert_embedding_receipt",
    "assert_no_truncating_chunk_ceiling",
    "assert_output_keys_match_admitted",
    "authorize_embedding_release",
    "build_embedding_receipt",
    "build_pinned_model_token_counter",
    "build_sentence_transformers_embedder",
    "build_vector_space_id",
    "coerce_admitted_chunks",
    "collect_runtime_evidence",
    "default_embedding_config",
    "default_embedding_receipt_path",
    "default_vector_space_id",
    "deterministic_project",
    "fixture_embedding_config",
    "fixture_sample_chunks",
    "generate_open_us_law_embeddings",
    "input_content_hash",
    "is_production_backend",
    "is_projection_backend",
    "iter_admitted_chunks",
    "l2_norm",
    "l2_normalize",
    "load_checkpoint",
    "load_embedding_receipt",
    "production_inference_evidence_reasons",
    "production_inference_evidence_satisfies_contract",
    "projection_cannot_authorize_release",
    "release_authorization_reasons",
    "require_pinned_gte_small",
    "select_device",
    "validate_vector_dimension",
    "validate_vector_norm",
    "write_checkpoint_atomic",
    "write_embedding_receipt",
]
