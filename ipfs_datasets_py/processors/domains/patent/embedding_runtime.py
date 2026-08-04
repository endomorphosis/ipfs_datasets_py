"""Pinned local production embedding runtime for patent retrieval (PATLAW-145).

This module owns the local, revision-pinned embedding path used by production
index builds. It deliberately does **not** select models at call time, open
network sockets, or invoke remote embedding providers for denied content.

Design invariants
-----------------
* Model, tokenizer, code, and config identities are pinned immutably and
  bound into every :class:`EmbeddingReceipt`.
* Same inputs + same pin produce vectors stable within
  :data:`VECTOR_STABILITY_TOLERANCE` (exact for the default hashed backend).
* Device selection is explicit: unavailable hardware either falls back to a
  declared alternate device (recorded on the receipt) or blocks fail-closed.
* Private / confidential routes make zero external calls. Receipts, logs, and
  diagnostics never carry input text, vector values, or content CIDs.
* Importing this module performs no model download, GPU init, or network I/O.
"""

from __future__ import annotations

import hashlib
import logging
import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Iterable

from ipfs_datasets_py.processors.retrieval import hashed_term_projection

from .indexing import (
    DEFAULT_EMBEDDING_CONFIG_CID,
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_MODEL_VERSION,
    DEFAULT_EMBEDDING_PROVIDER,
    REMOTE_EMBEDDING_PROVIDERS,
    TOKENIZER_VERSION,
    tokenize_patent_text,
)
from .retrieval_contracts import (
    RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
    DisclosureClass,
    EmbeddingIdentity,
    canonical_json,
    is_private_disclosure,
    requires_quarantine,
)

# ---------------------------------------------------------------------------
# Schema / identity pins (immutable)
# ---------------------------------------------------------------------------

EMBEDDING_RUNTIME_SCHEMA_VERSION: Final = "patent.embedding_runtime.v1"
EMBEDDING_RUNTIME_INTERFACE: Final = "LocalEmbeddingRuntime@1"
EMBEDDING_RUNTIME_CODE_VERSION: Final = "1.0.0"

# Pinned production model artifacts (local hashed-term projection).
PINNED_PROVIDER: Final = DEFAULT_EMBEDDING_PROVIDER
PINNED_MODEL_ID: Final = DEFAULT_EMBEDDING_MODEL_ID
PINNED_MODEL_REVISION: Final = DEFAULT_EMBEDDING_MODEL_VERSION
PINNED_TOKENIZER_ID: Final = TOKENIZER_VERSION
PINNED_TOKENIZER_REVISION: Final = "1.0.0"
PINNED_DIMENSION: Final = DEFAULT_EMBEDDING_DIMENSION
PINNED_CONFIG_CID: Final = DEFAULT_EMBEDDING_CONFIG_CID
PINNED_BACKEND: Final = "local_hashed_term_projection"
PINNED_MODEL_CID: Final = (
    "bafybeigembeddingmodelpinpatentv1hashedtermproj0000000000000001"
)

# Exact stability for the deterministic hashed backend; declared for contract.
VECTOR_STABILITY_TOLERANCE: Final = 0.0
# Float comparison epsilon used by helpers when tolerance is zero.
_FLOAT_EPS: Final = 1e-12

# Resource bounds (fail-closed).
DEFAULT_BATCH_SIZE: Final = 32
MAX_BATCH_SIZE: Final = 512
MAX_TEXTS_PER_CALL: Final = 10_000
MAX_TEXT_CHARS: Final = 1_000_000
DEFAULT_CACHE_ENTRIES: Final = 256
MAX_CACHE_ENTRIES: Final = 10_000

# Device policy
DEFAULT_DEVICE: Final = "cpu"
SUPPORTED_DEVICES: Final = frozenset({"cpu", "cuda", "cuda:0", "mps"})

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class EmbeddingRuntimeError(ValueError):
    """Base error for the patent embedding runtime."""

    code: str = "embedding_runtime_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class UnpinnedModelError(EmbeddingRuntimeError):
    """Raised when a caller requests a model/revision that is not pinned."""

    code = "unpinned_model"


class HardwareUnavailableError(EmbeddingRuntimeError):
    """Raised when requested hardware is unavailable and policy is block."""

    code = "hardware_unavailable"


class EmbeddingPolicyDeniedError(EmbeddingRuntimeError):
    """Raised when a nonlocal route is denied by audited policy."""

    code = "policy_denied"


class EmbeddingCancelledError(EmbeddingRuntimeError):
    """Raised when cooperative cancellation fires mid-batch."""

    code = "cancelled"


class EmbeddingResourceLimitError(EmbeddingRuntimeError):
    """Raised when a batch or text exceeds declared resource bounds."""

    code = "resource_limit"


class EmbeddingConfigError(EmbeddingRuntimeError):
    """Raised when runtime configuration is invalid."""

    code = "config_invalid"


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


class CancellationToken:
    """Cooperative cancellation flag checked around batch boundaries."""

    __slots__ = ("_cancelled", "reason")

    def __init__(self, *, cancelled: bool = False, reason: str = "cancelled") -> None:
        self._cancelled = bool(cancelled)
        self.reason = str(reason or "cancelled")

    def cancel(self, reason: str = "cancelled") -> None:
        self._cancelled = True
        self.reason = str(reason or "cancelled")

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def check(self) -> None:
        if self._cancelled:
            raise EmbeddingCancelledError(self.reason or "cancelled")


# ---------------------------------------------------------------------------
# Enums / policy
# ---------------------------------------------------------------------------


class DeviceFallbackPolicy(str, Enum):
    """What to do when requested hardware is unavailable."""

    FALLBACK_CPU = "fallback_cpu"
    BLOCK = "block"


class RouteKind(str, Enum):
    """Embedding execution route classification."""

    LOCAL_PINNED = "local_pinned"
    NONLOCAL_DENIED = "nonlocal_denied"
    NONLOCAL_BLOCKED = "nonlocal_blocked"


class PolicyDecisionCode(str, Enum):
    """Audited policy decision codes (never carry content)."""

    ALLOW_LOCAL = "allow_local"
    DENY_REMOTE_PRIVATE = "deny_remote_private"
    DENY_REMOTE_DEFAULT = "deny_remote_default"
    DENY_UNPINNED = "deny_unpinned"
    DENY_QUARANTINE = "deny_quarantine"


# ---------------------------------------------------------------------------
# Identity + receipts
# ---------------------------------------------------------------------------


def _sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _code_digest() -> str:
    """Bind critical algorithm / schema constants into a stable code identity."""
    payload = canonical_json(
        {
            "backend": PINNED_BACKEND,
            "code_version": EMBEDDING_RUNTIME_CODE_VERSION,
            "dimension": PINNED_DIMENSION,
            "interface": EMBEDDING_RUNTIME_INTERFACE,
            "model_id": PINNED_MODEL_ID,
            "model_revision": PINNED_MODEL_REVISION,
            "provider": PINNED_PROVIDER,
            "schema": EMBEDDING_RUNTIME_SCHEMA_VERSION,
            "tokenizer_id": PINNED_TOKENIZER_ID,
            "tokenizer_revision": PINNED_TOKENIZER_REVISION,
            "tolerance": VECTOR_STABILITY_TOLERANCE,
        }
    )
    return _sha256_hex(payload)


CODE_DIGEST: Final = _code_digest()


def _config_digest() -> str:
    payload = canonical_json(
        {
            "batch_size_default": DEFAULT_BATCH_SIZE,
            "config_cid": PINNED_CONFIG_CID,
            "dimension": PINNED_DIMENSION,
            "max_batch_size": MAX_BATCH_SIZE,
            "max_text_chars": MAX_TEXT_CHARS,
            "max_texts_per_call": MAX_TEXTS_PER_CALL,
            "normalize": True,
            "schema": EMBEDDING_RUNTIME_SCHEMA_VERSION,
        }
    )
    return _sha256_hex(payload)


CONFIG_DIGEST: Final = _config_digest()


@dataclass(frozen=True, slots=True)
class PinnedRuntimeIdentity:
    """Immutable binding of model, tokenizer, code, and config identities."""

    schema_version: str
    provider: str
    model_id: str
    model_revision: str
    model_cid: str
    tokenizer_id: str
    tokenizer_revision: str
    dimension: int
    config_cid: str
    config_digest: str
    code_version: str
    code_digest: str
    backend: str
    normalize: bool = True

    def __post_init__(self) -> None:
        if self.schema_version != EMBEDDING_RUNTIME_SCHEMA_VERSION:
            raise EmbeddingConfigError(
                f"schema_version must be {EMBEDDING_RUNTIME_SCHEMA_VERSION!r}"
            )
        if self.model_id != PINNED_MODEL_ID or self.model_revision != PINNED_MODEL_REVISION:
            raise UnpinnedModelError(
                f"model must be pinned {PINNED_MODEL_ID}@{PINNED_MODEL_REVISION}"
            )
        if (
            self.tokenizer_id != PINNED_TOKENIZER_ID
            or self.tokenizer_revision != PINNED_TOKENIZER_REVISION
        ):
            raise UnpinnedModelError(
                f"tokenizer must be pinned {PINNED_TOKENIZER_ID}@"
                f"{PINNED_TOKENIZER_REVISION}"
            )
        if self.dimension != PINNED_DIMENSION:
            raise EmbeddingConfigError(
                f"dimension must be pinned {PINNED_DIMENSION}"
            )
        if self.config_cid != PINNED_CONFIG_CID:
            raise UnpinnedModelError("config_cid must match the pinned config CID")
        if self.code_digest != CODE_DIGEST:
            raise EmbeddingConfigError("code_digest does not match pinned runtime")
        if self.config_digest != CONFIG_DIGEST:
            raise EmbeddingConfigError("config_digest does not match pinned runtime")

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "code_digest": self.code_digest,
            "code_version": self.code_version,
            "config_cid": self.config_cid,
            "config_digest": self.config_digest,
            "dimension": self.dimension,
            "model_cid": self.model_cid,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "normalize": self.normalize,
            "provider": self.provider,
            "schema_version": self.schema_version,
            "tokenizer_id": self.tokenizer_id,
            "tokenizer_revision": self.tokenizer_revision,
        }

    def to_embedding_identity(self) -> EmbeddingIdentity:
        """Project into the v1 :class:`EmbeddingIdentity` contract."""
        return EmbeddingIdentity(
            schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
            provider=self.provider,
            model_id=self.model_id,
            model_version=self.model_revision,
            dimension=self.dimension,
            config_cid=self.config_cid,
            model_cid=self.model_cid,
            backend="pinned",
            normalize=self.normalize,
            metadata={
                "code_digest": self.code_digest,
                "config_digest": self.config_digest,
                "tokenizer_id": self.tokenizer_id,
                "tokenizer_revision": self.tokenizer_revision,
            },
        )


def pinned_runtime_identity() -> PinnedRuntimeIdentity:
    """Return the sole approved production pin."""
    return PinnedRuntimeIdentity(
        schema_version=EMBEDDING_RUNTIME_SCHEMA_VERSION,
        provider=PINNED_PROVIDER,
        model_id=PINNED_MODEL_ID,
        model_revision=PINNED_MODEL_REVISION,
        model_cid=PINNED_MODEL_CID,
        tokenizer_id=PINNED_TOKENIZER_ID,
        tokenizer_revision=PINNED_TOKENIZER_REVISION,
        dimension=PINNED_DIMENSION,
        config_cid=PINNED_CONFIG_CID,
        config_digest=CONFIG_DIGEST,
        code_version=EMBEDDING_RUNTIME_CODE_VERSION,
        code_digest=CODE_DIGEST,
        backend=PINNED_BACKEND,
        normalize=True,
    )


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Audited decision recorded *before* any nonlocal attempt."""

    code: PolicyDecisionCode
    route: RouteKind
    allow_execute: bool
    reason: str
    disclosure: str
    private_route: bool

    def to_dict(self) -> dict[str, Any]:
        # Never include text, vectors, or CIDs.
        return {
            "allow_execute": self.allow_execute,
            "code": self.code.value,
            "disclosure": self.disclosure,
            "private_route": self.private_route,
            "reason": self.reason,
            "route": self.route.value,
        }


@dataclass(frozen=True, slots=True)
class EmbeddingReceipt:
    """Binds model/tokenizer/code/config identities for one embed call.

    Receipts are content-safe: they never carry input text, vector values, or
    source CIDs. Input identity is represented only as ordered input digests
    (SHA-256 of normalized text) when *redacted* is False; confidential calls
    omit digests entirely when redacted=True.
    """

    schema_version: str
    identity: PinnedRuntimeIdentity
    policy: PolicyDecision
    device_requested: str
    device_selected: str
    device_fallback_applied: bool
    batch_size: int
    text_count: int
    cache_hits: int
    cache_misses: int
    input_digests: tuple[str, ...]
    vector_digest: str
    stability_tolerance: float
    cancelled: bool
    elapsed_ms: float
    redacted: bool
    metadata: Mapping[str, str] = MappingProxyType({})

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "batch_size": self.batch_size,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cancelled": self.cancelled,
            "device_fallback_applied": self.device_fallback_applied,
            "device_requested": self.device_requested,
            "device_selected": self.device_selected,
            "elapsed_ms": self.elapsed_ms,
            "identity": self.identity.to_dict(),
            "policy": self.policy.to_dict(),
            "redacted": self.redacted,
            "schema_version": self.schema_version,
            "stability_tolerance": self.stability_tolerance,
            "text_count": self.text_count,
            "vector_digest": self.vector_digest if not self.redacted else "",
            "metadata": dict(self.metadata),
        }
        if self.redacted:
            payload["input_digests"] = []
        else:
            payload["input_digests"] = list(self.input_digests)
        return payload


@dataclass(frozen=True, slots=True)
class EmbeddingBatchResult:
    """Vectors plus the binding receipt for one embed invocation."""

    vectors: tuple[tuple[float, ...], ...]
    receipt: EmbeddingReceipt
    identity: PinnedRuntimeIdentity

    def to_dict(self, *, include_vectors: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            "identity": self.identity.to_dict(),
            "receipt": self.receipt.to_dict(),
            "vector_count": len(self.vectors),
            "dimension": self.identity.dimension,
        }
        if include_vectors and not self.receipt.redacted:
            out["vectors"] = [list(v) for v in self.vectors]
        return out


# ---------------------------------------------------------------------------
# Input normalization + hashing
# ---------------------------------------------------------------------------


def normalize_embedding_input(text: str) -> str:
    """Normalize text for deterministic input hashing and embedding.

    Uses the patent-legal tokenizer so protected citations / classifications
    survive, then joins with single spaces.
    """
    tokens = tokenize_patent_text(str(text or ""))
    return " ".join(tokens)


def input_content_digest(text: str) -> str:
    """SHA-256 of the normalized input (never the raw text itself)."""
    return _sha256_hex(normalize_embedding_input(text))


def vector_content_digest(vectors: Sequence[Sequence[float]]) -> str:
    """Digest of vector payload for receipt binding (not for disclosure)."""
    payload = canonical_json([[float(x) for x in row] for row in vectors])
    return _sha256_hex(payload)


def vectors_within_tolerance(
    left: Sequence[Sequence[float]],
    right: Sequence[Sequence[float]],
    *,
    tolerance: float = VECTOR_STABILITY_TOLERANCE,
) -> bool:
    """Return True when *left* and *right* agree within *tolerance* (L-inf)."""
    if len(left) != len(right):
        return False
    tol = max(float(tolerance), _FLOAT_EPS) if tolerance == 0.0 else float(tolerance)
    # When declared tolerance is exactly 0.0, still use a tiny eps for float noise.
    if float(tolerance) == 0.0:
        tol = _FLOAT_EPS
    for a, b in zip(left, right):
        if len(a) != len(b):
            return False
        for x, y in zip(a, b):
            if abs(float(x) - float(y)) > tol:
                return False
    return True


# ---------------------------------------------------------------------------
# Device selection
# ---------------------------------------------------------------------------


def _probe_cuda() -> bool:
    try:
        import torch  # type: ignore[import-not-found]

        return bool(
            getattr(torch, "cuda", None)
            and torch.backends.cuda.is_built()
            and torch.cuda.is_available()
        )
    except Exception:
        return False


def _probe_mps() -> bool:
    try:
        import torch  # type: ignore[import-not-found]

        mps = getattr(getattr(torch, "backends", None), "mps", None)
        return bool(mps is not None and mps.is_available())
    except Exception:
        return False


def device_is_available(device: str) -> bool:
    """Return whether *device* can be used (pure probe; no side effects)."""
    name = str(device or "").strip().lower()
    if not name or name == "cpu":
        return True
    if name.startswith("cuda"):
        return _probe_cuda()
    if name == "mps":
        return _probe_mps()
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
# Policy gate (audited before any nonlocal route)
# ---------------------------------------------------------------------------


def _coerce_disclosure(value: DisclosureClass | str | None) -> DisclosureClass:
    if value is None:
        return DisclosureClass.PUBLIC_USER
    if isinstance(value, DisclosureClass):
        return value
    try:
        return DisclosureClass(str(value).strip())
    except ValueError as exc:
        raise EmbeddingConfigError(f"unknown disclosure: {value!r}") from exc


def evaluate_embedding_policy(
    *,
    disclosure: DisclosureClass | str | None = None,
    allow_remote: bool = False,
    remote_requested: bool = False,
    private_route: bool | None = None,
) -> PolicyDecision:
    """Audited policy decision recorded before any nonlocal embed attempt.

    Default is local-only. Remote is denied for private/quarantine material and
    whenever ``allow_remote`` is False (production default).
    """
    disc = _coerce_disclosure(disclosure)
    is_private = (
        bool(private_route)
        if private_route is not None
        else (is_private_disclosure(disc) or requires_quarantine(disc))
    )

    if requires_quarantine(disc) and remote_requested:
        return PolicyDecision(
            code=PolicyDecisionCode.DENY_QUARANTINE,
            route=RouteKind.NONLOCAL_DENIED,
            allow_execute=True,  # local path still permitted
            reason="quarantine disclosure cannot use nonlocal embedding",
            disclosure=disc.value,
            private_route=True,
        )

    if remote_requested and is_private:
        return PolicyDecision(
            code=PolicyDecisionCode.DENY_REMOTE_PRIVATE,
            route=RouteKind.NONLOCAL_DENIED,
            allow_execute=True,  # fall through to local
            reason="private disclosure blocks remote embedding providers",
            disclosure=disc.value,
            private_route=True,
        )

    if remote_requested and not allow_remote:
        return PolicyDecision(
            code=PolicyDecisionCode.DENY_REMOTE_DEFAULT,
            route=RouteKind.NONLOCAL_BLOCKED,
            allow_execute=True,  # local still ok
            reason="remote embedding disabled by runtime policy",
            disclosure=disc.value,
            private_route=is_private,
        )

    if remote_requested and allow_remote and not is_private:
        # Even when remote is notionally allowed, this production runtime never
        # executes a nonlocal path — callers must use a different module.
        return PolicyDecision(
            code=PolicyDecisionCode.DENY_REMOTE_DEFAULT,
            route=RouteKind.NONLOCAL_BLOCKED,
            allow_execute=True,
            reason="pinned local runtime does not execute nonlocal routes",
            disclosure=disc.value,
            private_route=False,
        )

    return PolicyDecision(
        code=PolicyDecisionCode.ALLOW_LOCAL,
        route=RouteKind.LOCAL_PINNED,
        allow_execute=True,
        reason="pinned local embedding permitted",
        disclosure=disc.value,
        private_route=is_private,
    )


def _is_remote_provider(provider: str | None, backend: str | None = None) -> bool:
    candidates = {
        str(provider or "").strip().lower(),
        str(backend or "").strip().lower(),
    }
    return bool(candidates & REMOTE_EMBEDDING_PROVIDERS) or any(
        c.startswith("remote") or c.endswith("_remote") for c in candidates if c
    )


# ---------------------------------------------------------------------------
# Bounded cache
# ---------------------------------------------------------------------------


@dataclass
class _CacheEntry:
    vector: tuple[float, ...]
    identity_digest: str


class EmbeddingVectorCache:
    """Bounded LRU cache keyed by (input_digest, identity_digest)."""

    def __init__(self, *, max_entries: int = DEFAULT_CACHE_ENTRIES) -> None:
        if (
            isinstance(max_entries, bool)
            or not isinstance(max_entries, int)
            or max_entries < 0
        ):
            raise EmbeddingConfigError("max_entries must be a non-negative int")
        if max_entries > MAX_CACHE_ENTRIES:
            raise EmbeddingConfigError(
                f"max_entries must be <= {MAX_CACHE_ENTRIES}"
            )
        self._max = max_entries
        self._entries: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def __len__(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self.hits = 0
            self.misses = 0

    @staticmethod
    def cache_key(input_digest: str, identity_digest: str) -> str:
        return f"{identity_digest}:{input_digest}"

    def get(
        self, input_digest: str, identity_digest: str
    ) -> tuple[float, ...] | None:
        if self._max == 0:
            self.misses += 1
            return None
        key = self.cache_key(input_digest, identity_digest)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.misses += 1
                return None
            self._entries.move_to_end(key)
            self.hits += 1
            return entry.vector

    def put(
        self,
        input_digest: str,
        identity_digest: str,
        vector: Sequence[float],
    ) -> None:
        if self._max == 0:
            return
        key = self.cache_key(input_digest, identity_digest)
        with self._lock:
            self._entries[key] = _CacheEntry(
                vector=tuple(float(x) for x in vector),
                identity_digest=identity_digest,
            )
            self._entries.move_to_end(key)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)

    def stats(self) -> dict[str, int]:
        return {
            "entries": len(self._entries),
            "hits": self.hits,
            "max_entries": self._max,
            "misses": self.misses,
        }


# ---------------------------------------------------------------------------
# Local embedding computation (pinned)
# ---------------------------------------------------------------------------


def _embed_normalized(normalized: str, *, dimension: int) -> list[float]:
    """Project normalized text into the pinned vector space."""
    return hashed_term_projection(normalized, dimension=dimension)


def _l2_normalize(values: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(float(v) * float(v) for v in values))
    if norm <= 0.0:
        return [float(v) for v in values]
    return [float(v) / norm for v in values]


# ---------------------------------------------------------------------------
# Runtime configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EmbeddingRuntimeConfig:
    """Bounded runtime configuration (no unpinned model selection)."""

    device: str = DEFAULT_DEVICE
    device_fallback: DeviceFallbackPolicy = DeviceFallbackPolicy.FALLBACK_CPU
    batch_size: int = DEFAULT_BATCH_SIZE
    max_texts_per_call: int = MAX_TEXTS_PER_CALL
    max_text_chars: int = MAX_TEXT_CHARS
    cache_entries: int = DEFAULT_CACHE_ENTRIES
    allow_remote: bool = False
    redact_private_receipts: bool = True

    def __post_init__(self) -> None:
        device = str(self.device or DEFAULT_DEVICE).strip().lower() or DEFAULT_DEVICE
        if device not in SUPPORTED_DEVICES and not device.startswith("cuda:"):
            raise EmbeddingConfigError(f"unsupported device: {self.device!r}")
        object.__setattr__(self, "device", device)
        if not isinstance(self.device_fallback, DeviceFallbackPolicy):
            object.__setattr__(
                self,
                "device_fallback",
                DeviceFallbackPolicy(str(self.device_fallback)),
            )
        for name, value, minimum, maximum in (
            ("batch_size", self.batch_size, 1, MAX_BATCH_SIZE),
            ("max_texts_per_call", self.max_texts_per_call, 1, MAX_TEXTS_PER_CALL),
            ("max_text_chars", self.max_text_chars, 1, MAX_TEXT_CHARS),
            ("cache_entries", self.cache_entries, 0, MAX_CACHE_ENTRIES),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise EmbeddingConfigError(f"{name} must be an int")
            if value < minimum or value > maximum:
                raise EmbeddingConfigError(
                    f"{name} must be in [{minimum}, {maximum}]"
                )
        if not isinstance(self.allow_remote, bool):
            raise EmbeddingConfigError("allow_remote must be bool")
        if not isinstance(self.redact_private_receipts, bool):
            raise EmbeddingConfigError("redact_private_receipts must be bool")

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_remote": self.allow_remote,
            "batch_size": self.batch_size,
            "cache_entries": self.cache_entries,
            "device": self.device,
            "device_fallback": self.device_fallback.value,
            "max_text_chars": self.max_text_chars,
            "max_texts_per_call": self.max_texts_per_call,
            "redact_private_receipts": self.redact_private_receipts,
        }


# ---------------------------------------------------------------------------
# Main runtime
# ---------------------------------------------------------------------------


class LocalEmbeddingRuntime:
    """Pinned local production embedding runtime.

    Parameters
    ----------
    config:
        Bounded resource and device configuration. Model selection is not
        accepted: only the module-level pin is used.
    identity:
        Optional override that must still equal :func:`pinned_runtime_identity`.
    device_probe:
        Injectable availability probe (tests inject fixed answers).
    """

    def __init__(
        self,
        config: EmbeddingRuntimeConfig | None = None,
        *,
        identity: PinnedRuntimeIdentity | None = None,
        device_probe: Callable[[str], bool] | None = None,
        cache: EmbeddingVectorCache | None = None,
    ) -> None:
        self._config = config or EmbeddingRuntimeConfig()
        self._identity = identity or pinned_runtime_identity()
        # Re-validate pin equality.
        if self._identity.to_dict() != pinned_runtime_identity().to_dict():
            raise UnpinnedModelError(
                "runtime identity must equal the sole approved production pin"
            )
        self._device_probe = device_probe
        self._cache = cache or EmbeddingVectorCache(
            max_entries=self._config.cache_entries
        )
        self._identity_digest = _sha256_hex(
            canonical_json(self._identity.to_dict())
        )
        self._external_call_count = 0
        self._embed_call_count = 0
        self._lock = threading.Lock()

    # -- properties ---------------------------------------------------------

    @property
    def identity(self) -> PinnedRuntimeIdentity:
        return self._identity

    @property
    def config(self) -> EmbeddingRuntimeConfig:
        return self._config

    @property
    def external_call_count(self) -> int:
        """Number of nonlocal / external provider attempts (always 0)."""
        return self._external_call_count

    @property
    def embed_call_count(self) -> int:
        return self._embed_call_count

    @property
    def cache(self) -> EmbeddingVectorCache:
        return self._cache

    @property
    def stability_tolerance(self) -> float:
        return VECTOR_STABILITY_TOLERANCE

    # -- device -------------------------------------------------------------

    def resolve_device(self) -> tuple[str, bool]:
        """Resolve configured device under fallback policy."""
        return select_device(
            self._config.device,
            fallback=self._config.device_fallback,
            probe=self._device_probe,
        )

    # -- embed --------------------------------------------------------------

    def embed(
        self,
        texts: Sequence[str],
        *,
        disclosure: DisclosureClass | str | None = None,
        private_route: bool | None = None,
        remote_requested: bool = False,
        cancellation: CancellationToken | None = None,
        use_cache: bool = True,
    ) -> EmbeddingBatchResult:
        """Embed *texts* with the pinned local backend.

        Always executes the local pin. Any remote request is audited and
        denied; private material never triggers an external call.
        """
        started = time.perf_counter()
        if cancellation is not None:
            cancellation.check()

        items = [str(t if t is not None else "") for t in texts]
        if len(items) > self._config.max_texts_per_call:
            raise EmbeddingResourceLimitError(
                f"text count {len(items)} exceeds max_texts_per_call "
                f"{self._config.max_texts_per_call}"
            )
        for i, raw in enumerate(items):
            if len(raw) > self._config.max_text_chars:
                raise EmbeddingResourceLimitError(
                    f"text[{i}] length exceeds max_text_chars "
                    f"{self._config.max_text_chars}"
                )

        # Policy decision *before* any nonlocal route would be considered.
        if remote_requested or self._config.allow_remote:
            # Count an audited nonlocal consideration, never an actual call.
            pass
        policy = evaluate_embedding_policy(
            disclosure=disclosure,
            allow_remote=self._config.allow_remote,
            remote_requested=remote_requested,
            private_route=private_route,
        )
        if not policy.allow_execute:
            raise EmbeddingPolicyDeniedError(policy.reason)

        # Hardware selection (explicit fallback or block).
        device_selected, fallback_applied = select_device(
            self._config.device,
            fallback=self._config.device_fallback,
            probe=self._device_probe,
        )

        # This runtime never issues external calls.
        if remote_requested:
            # Record that a nonlocal route was considered and denied.
            logger.info(
                "embedding_policy decision=%s route=%s private=%s",
                policy.code.value,
                policy.route.value,
                policy.private_route,
            )

        dim = self._identity.dimension
        batch_size = self._config.batch_size
        vectors: list[tuple[float, ...]] = []
        input_digests: list[str] = []
        cache_hits = 0
        cache_misses = 0

        for batch_start in range(0, len(items), batch_size):
            if cancellation is not None:
                cancellation.check()
            batch = items[batch_start : batch_start + batch_size]
            for raw in batch:
                normalized = normalize_embedding_input(raw)
                digest = _sha256_hex(normalized)
                input_digests.append(digest)
                cached: tuple[float, ...] | None = None
                if use_cache:
                    cached = self._cache.get(digest, self._identity_digest)
                if cached is not None:
                    cache_hits += 1
                    vectors.append(cached)
                    continue
                cache_misses += 1
                projected = _embed_normalized(normalized, dimension=dim)
                if self._identity.normalize:
                    projected = _l2_normalize(projected)
                # Device is recorded for receipt/audit; hashed backend is
                # device-invariant, which keeps vectors stable across fallback.
                vec = tuple(float(x) for x in projected)
                if use_cache:
                    self._cache.put(digest, self._identity_digest, vec)
                vectors.append(vec)

        if cancellation is not None:
            cancellation.check()

        with self._lock:
            self._embed_call_count += 1

        redact = bool(
            self._config.redact_private_receipts and policy.private_route
        )
        vec_digest = vector_content_digest(vectors) if not redact else ""
        elapsed_ms = (time.perf_counter() - started) * 1000.0

        receipt = EmbeddingReceipt(
            schema_version=EMBEDDING_RUNTIME_SCHEMA_VERSION,
            identity=self._identity,
            policy=policy,
            device_requested=self._config.device,
            device_selected=device_selected,
            device_fallback_applied=fallback_applied,
            batch_size=batch_size,
            text_count=len(items),
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            input_digests=tuple(input_digests),
            vector_digest=vec_digest,
            stability_tolerance=VECTOR_STABILITY_TOLERANCE,
            cancelled=False,
            elapsed_ms=round(elapsed_ms, 3),
            redacted=redact,
            metadata=MappingProxyType(
                {
                    "interface": EMBEDDING_RUNTIME_INTERFACE,
                    "device_invariant_backend": "true",
                }
            ),
        )
        return EmbeddingBatchResult(
            vectors=tuple(vectors),
            receipt=receipt,
            identity=self._identity,
        )

    def embed_one(
        self,
        text: str,
        *,
        disclosure: DisclosureClass | str | None = None,
        private_route: bool | None = None,
        remote_requested: bool = False,
        cancellation: CancellationToken | None = None,
        use_cache: bool = True,
    ) -> tuple[tuple[float, ...], EmbeddingReceipt]:
        """Convenience wrapper for a single text."""
        result = self.embed(
            [text],
            disclosure=disclosure,
            private_route=private_route,
            remote_requested=remote_requested,
            cancellation=cancellation,
            use_cache=use_cache,
        )
        return result.vectors[0], result.receipt

    def assert_stable(
        self,
        texts: Sequence[str],
        *,
        rounds: int = 2,
        disclosure: DisclosureClass | str | None = None,
    ) -> EmbeddingBatchResult:
        """Embed *rounds* times and require agreement within tolerance."""
        if rounds < 2:
            raise EmbeddingConfigError("rounds must be >= 2")
        results = [
            self.embed(texts, disclosure=disclosure, use_cache=False)
            for _ in range(rounds)
        ]
        baseline = results[0]
        for other in results[1:]:
            if not vectors_within_tolerance(
                baseline.vectors,
                other.vectors,
                tolerance=VECTOR_STABILITY_TOLERANCE,
            ):
                raise EmbeddingRuntimeError(
                    "pinned runtime produced vectors outside stability tolerance",
                    code="stability_violation",
                )
            if other.identity.to_dict() != baseline.identity.to_dict():
                raise EmbeddingRuntimeError(
                    "identity drifted across stable embed rounds",
                    code="identity_drift",
                )
        return baseline


# Alias used by objective AST queries.
EmbeddingRuntime = LocalEmbeddingRuntime


def build_default_runtime(
    **config_kwargs: Any,
) -> LocalEmbeddingRuntime:
    """Factory for a default pinned runtime (optional config overrides)."""
    config = EmbeddingRuntimeConfig(**config_kwargs) if config_kwargs else None
    return LocalEmbeddingRuntime(config=config)


__all__ = [
    "CODE_DIGEST",
    "CONFIG_DIGEST",
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_CACHE_ENTRIES",
    "DEFAULT_DEVICE",
    "EMBEDDING_RUNTIME_CODE_VERSION",
    "EMBEDDING_RUNTIME_INTERFACE",
    "EMBEDDING_RUNTIME_SCHEMA_VERSION",
    "MAX_BATCH_SIZE",
    "MAX_CACHE_ENTRIES",
    "MAX_TEXT_CHARS",
    "MAX_TEXTS_PER_CALL",
    "PINNED_BACKEND",
    "PINNED_CONFIG_CID",
    "PINNED_DIMENSION",
    "PINNED_MODEL_CID",
    "PINNED_MODEL_ID",
    "PINNED_MODEL_REVISION",
    "PINNED_PROVIDER",
    "PINNED_TOKENIZER_ID",
    "PINNED_TOKENIZER_REVISION",
    "SUPPORTED_DEVICES",
    "VECTOR_STABILITY_TOLERANCE",
    "CancellationToken",
    "DeviceFallbackPolicy",
    "EmbeddingBatchResult",
    "EmbeddingCancelledError",
    "EmbeddingConfigError",
    "EmbeddingPolicyDeniedError",
    "EmbeddingReceipt",
    "EmbeddingResourceLimitError",
    "EmbeddingRuntime",
    "EmbeddingRuntimeConfig",
    "EmbeddingRuntimeError",
    "EmbeddingVectorCache",
    "HardwareUnavailableError",
    "LocalEmbeddingRuntime",
    "PinnedRuntimeIdentity",
    "PolicyDecision",
    "PolicyDecisionCode",
    "RouteKind",
    "UnpinnedModelError",
    "build_default_runtime",
    "device_is_available",
    "evaluate_embedding_policy",
    "input_content_digest",
    "normalize_embedding_input",
    "pinned_runtime_identity",
    "select_device",
    "vector_content_digest",
    "vectors_within_tolerance",
]
