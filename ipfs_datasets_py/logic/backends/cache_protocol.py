"""VerificationCacheProtocol@1 — exact cache for software-verification backends.

Exact cache hits inherit, but never raise, the authority of a validated current
receipt.  Cache keys content-address every input that can change a run:

* IR / property / assumption digests
* translation receipt identity
* backend id, binary digest, version, and config
* resource-budget digests
* candidate / repository tree identity
* proof / verification policy

Implementations coalesce concurrent identical work (single-flight), apply a
distinct negative TTL for non-conclusive outcomes, reject stale and tampered
entries fail-closed, and never promote a stored result's authority.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final, Protocol, runtime_checkable

from ..families.models import EvidenceAuthority
from ..ir_core.claims import FrozenMap
from .results import (
    ResultAuthority,
    ResultStatus,
    TypedBackendResult,
)

VERIFICATION_CACHE_PROTOCOL_INTERFACE: Final = "VerificationCacheProtocol@1"
VERIFICATION_CACHE_PROTOCOL_SCHEMA_VERSION: Final = "verification-cache-protocol/v1"
VERIFICATION_CACHE_KEY_SCHEMA_VERSION: Final = "verification-cache-key/v1"
VERIFICATION_CACHE_ENTRY_SCHEMA_VERSION: Final = "verification-cache-entry/v1"

DEFAULT_POSITIVE_TTL_SECONDS: Final = 2_592_000  # 30 days
DEFAULT_NEGATIVE_TTL_SECONDS: Final = 300  # 5 minutes
DEFAULT_MAX_ENTRIES: Final = 4096

_NEGATIVE_STATUSES: Final = frozenset(
    {
        ResultStatus.UNKNOWN,
        ResultStatus.TIMEOUT,
        ResultStatus.UNAVAILABLE,
        ResultStatus.UNSUPPORTED,
        ResultStatus.MALFORMED,
        ResultStatus.ERROR,
        ResultStatus.RECONSTRUCTION_FAILED,
        ResultStatus.ATTESTATION_INVALID,
    }
)

_AUTHORITY_RANK: Final[dict[EvidenceAuthority, int]] = {
    EvidenceAuthority.NONE: 0,
    EvidenceAuthority.ADVISORY: 1,
    EvidenceAuthority.BOUNDED: 2,
    EvidenceAuthority.INDEPENDENTLY_CHECKABLE: 3,
    EvidenceAuthority.AUTHORITATIVE: 4,
}


class VerificationCacheError(ValueError):
    """Raised when a verification-cache key, entry, or operation is invalid."""


class VerificationCacheIntegrityError(VerificationCacheError):
    """Raised when a stored entry fails integrity or authority checks."""


class VerificationCacheAuthorityError(VerificationCacheError):
    """Raised when a caller attempts to raise or substitute authority."""


class CachePolarity(StrEnum):
    """Whether a cached outcome is positive evidence or a negative record."""

    POSITIVE = "positive"
    NEGATIVE = "negative"


class CacheLookupReason(StrEnum):
    """Stable reason codes returned with every lookup."""

    HIT = "hit"
    MISS = "miss"
    EXPIRED = "expired"
    STALE = "stale"
    TAMPERED = "tampered"
    AUTHORITY_MISMATCH = "authority_mismatch"
    NEGATIVE_HIT = "negative_hit"
    INSUFFICIENT_AUTHORITY = "insufficient_authority"
    STORED = "stored"
    SINGLE_FLIGHT_SHARED = "single_flight_shared"
    REJECTED = "rejected"


def _text(value: object, field_name: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        qualifier = "an empty or " if optional else "a "
        raise VerificationCacheError(
            f"{field_name} must be {qualifier}non-empty trimmed string without NUL"
        )
    return value


def _enum(value: object, enum_type: type[Any], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise VerificationCacheError(
            f"{field_name} must be one of {choices}"
        ) from error


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        # Digests and identities stay finite JSON; reject NaN/inf.
        if value != value or value in (float("inf"), float("-inf")):
            raise VerificationCacheError("floating-point values must be finite")
        return value
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_ready(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    raise VerificationCacheError(
        f"value of type {type(value).__name__} is not JSON-serializable for cache identity"
    )


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        _json_ready(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def content_digest(value: Any) -> str:
    """Return a ``sha256:<hex>`` digest of canonical JSON."""

    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def identity_digest(value: Any) -> str:
    """Digest a raw value, preserving already-canonical ``sha256:`` digests."""

    if isinstance(value, str) and value.startswith("sha256:") and len(value) == 71:
        hex_part = value[7:]
        if all(character in "0123456789abcdef" for character in hex_part):
            return value
    if value is None:
        return content_digest({})
    return content_digest(value)


def _evidence_authority(value: object) -> EvidenceAuthority:
    return _enum(value, EvidenceAuthority, "evidence_authority")


def _result_authority(value: object) -> ResultAuthority:
    return _enum(value, ResultAuthority, "result_authority")


def authority_rank(authority: EvidenceAuthority | str) -> int:
    """Return a closed rank used only for non-increase checks."""

    resolved = _evidence_authority(authority)
    return _AUTHORITY_RANK[resolved]


def polarity_for_status(status: ResultStatus | str) -> CachePolarity:
    """Classify a result status as positive evidence or a negative record."""

    resolved = _enum(status, ResultStatus, "status")
    if resolved in _NEGATIVE_STATUSES:
        return CachePolarity.NEGATIVE
    return CachePolarity.POSITIVE


@dataclass(frozen=True, slots=True)
class VerificationCacheKey:
    """Content-addressed identity of one exact verification attempt.

    All bound dimensions are digests or stable identifiers.  Changing any
    dimension produces a distinct key and forces a miss.
    """

    ir_digest: str
    property_digest: str
    assumptions_digest: str
    translation_digest: str
    backend_id: str
    backend_binary_digest: str
    backend_version: str
    backend_config_digest: str
    resources_digest: str
    tree_digest: str
    policy_digest: str
    schema_version: str = VERIFICATION_CACHE_KEY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "ir_digest", identity_digest(self.ir_digest))
        object.__setattr__(
            self, "property_digest", identity_digest(self.property_digest)
        )
        object.__setattr__(
            self, "assumptions_digest", identity_digest(self.assumptions_digest)
        )
        object.__setattr__(
            self, "translation_digest", identity_digest(self.translation_digest)
        )
        object.__setattr__(self, "backend_id", _text(self.backend_id, "backend_id"))
        object.__setattr__(
            self,
            "backend_binary_digest",
            identity_digest(self.backend_binary_digest),
        )
        object.__setattr__(
            self, "backend_version", _text(self.backend_version, "backend_version")
        )
        object.__setattr__(
            self,
            "backend_config_digest",
            identity_digest(self.backend_config_digest),
        )
        object.__setattr__(
            self, "resources_digest", identity_digest(self.resources_digest)
        )
        object.__setattr__(self, "tree_digest", identity_digest(self.tree_digest))
        object.__setattr__(self, "policy_digest", identity_digest(self.policy_digest))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != VERIFICATION_CACHE_KEY_SCHEMA_VERSION:
            raise VerificationCacheError(
                f"unsupported verification cache key schema: {self.schema_version!r}"
            )

    @classmethod
    def build(
        cls,
        *,
        ir: Any,
        property_: Any = None,
        property_value: Any = None,
        assumptions: Any = (),
        translation: Any = None,
        backend_id: str,
        backend_binary: Any = "unspecified",
        backend_version: str,
        backend_config: Any = None,
        resources: Any = None,
        tree: Any = None,
        policy: Any = None,
    ) -> VerificationCacheKey:
        """Build a key from raw values, digesting each bound dimension."""

        prop = property_ if property_ is not None else property_value
        if prop is None:
            prop = {}
        return cls(
            ir_digest=identity_digest(ir),
            property_digest=identity_digest(prop),
            assumptions_digest=identity_digest(assumptions),
            translation_digest=identity_digest(
                {} if translation is None else translation
            ),
            backend_id=backend_id,
            backend_binary_digest=identity_digest(backend_binary),
            backend_version=backend_version,
            backend_config_digest=identity_digest(
                {} if backend_config is None else backend_config
            ),
            resources_digest=identity_digest({} if resources is None else resources),
            tree_digest=identity_digest({} if tree is None else tree),
            policy_digest=identity_digest({} if policy is None else policy),
        )

    @property
    def digest(self) -> str:
        return content_digest(self.to_dict())

    @property
    def cache_key(self) -> str:
        return self.digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumptions_digest": self.assumptions_digest,
            "backend_binary_digest": self.backend_binary_digest,
            "backend_config_digest": self.backend_config_digest,
            "backend_id": self.backend_id,
            "backend_version": self.backend_version,
            "ir_digest": self.ir_digest,
            "policy_digest": self.policy_digest,
            "property_digest": self.property_digest,
            "resources_digest": self.resources_digest,
            "schema_version": self.schema_version,
            "translation_digest": self.translation_digest,
            "tree_digest": self.tree_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> VerificationCacheKey:
        if not isinstance(value, Mapping):
            raise VerificationCacheError("verification cache key must be a mapping")
        payload = dict(value)
        unknown = sorted(set(payload) - set(_KEY_FIELDS))
        if unknown:
            raise VerificationCacheError(
                f"unknown verification cache key field(s): {', '.join(unknown)}"
            )
        return cls(
            ir_digest=payload.get("ir_digest", ""),
            property_digest=payload.get("property_digest", ""),
            assumptions_digest=payload.get("assumptions_digest", ""),
            translation_digest=payload.get("translation_digest", ""),
            backend_id=payload.get("backend_id", ""),
            backend_binary_digest=payload.get("backend_binary_digest", ""),
            backend_version=payload.get("backend_version", ""),
            backend_config_digest=payload.get("backend_config_digest", ""),
            resources_digest=payload.get("resources_digest", ""),
            tree_digest=payload.get("tree_digest", ""),
            policy_digest=payload.get("policy_digest", ""),
            schema_version=payload.get(
                "schema_version", VERIFICATION_CACHE_KEY_SCHEMA_VERSION
            ),
        )


_KEY_FIELDS: Final = frozenset(
    {
        "assumptions_digest",
        "backend_binary_digest",
        "backend_config_digest",
        "backend_id",
        "backend_version",
        "ir_digest",
        "policy_digest",
        "property_digest",
        "resources_digest",
        "schema_version",
        "translation_digest",
        "tree_digest",
    }
)


@dataclass(frozen=True, slots=True)
class VerificationCacheEntry:
    """Integrity-bound cached outcome for one :class:`VerificationCacheKey`.

    Authority fields are frozen at write time.  Hits revalidate integrity and
    return the stored authority unchanged; no path may raise it.
    """

    key: VerificationCacheKey
    result_authority: ResultAuthority
    status: ResultStatus
    evidence_authority: EvidenceAuthority
    result_payload: FrozenMap
    polarity: CachePolarity
    created_at: float
    entry_digest: str = ""
    result_id: str = ""
    diagnostics: tuple[str, ...] = ()
    schema_version: str = VERIFICATION_CACHE_ENTRY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.key, VerificationCacheKey):
            raise VerificationCacheError("entry.key must be a VerificationCacheKey")
        object.__setattr__(
            self,
            "result_authority",
            _result_authority(self.result_authority),
        )
        object.__setattr__(self, "status", _enum(self.status, ResultStatus, "status"))
        object.__setattr__(
            self,
            "evidence_authority",
            _evidence_authority(self.evidence_authority),
        )
        expected_polarity = polarity_for_status(self.status)
        polarity = _enum(self.polarity, CachePolarity, "polarity")
        if polarity is not expected_polarity:
            raise VerificationCacheError(
                f"polarity {polarity.value!r} does not match status "
                f"{self.status.value!r} (expected {expected_polarity.value})"
            )
        object.__setattr__(self, "polarity", polarity)
        try:
            payload = (
                self.result_payload
                if isinstance(self.result_payload, FrozenMap)
                else FrozenMap(self.result_payload)
            )
        except (TypeError, ValueError) as error:
            raise VerificationCacheError(
                "result_payload must be an immutable JSON mapping"
            ) from error
        object.__setattr__(self, "result_payload", payload)
        if not isinstance(self.created_at, (int, float)) or self.created_at != self.created_at:
            raise VerificationCacheError("created_at must be a finite number")
        object.__setattr__(self, "created_at", float(self.created_at))
        object.__setattr__(
            self, "result_id", _text(self.result_id, "result_id", optional=True)
        )
        diagnostics = tuple(
            _text(item, "diagnostics item") for item in (self.diagnostics or ())
        )
        if len(diagnostics) != len(set(diagnostics)):
            raise VerificationCacheError("diagnostics must not contain duplicates")
        object.__setattr__(self, "diagnostics", diagnostics)
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != VERIFICATION_CACHE_ENTRY_SCHEMA_VERSION:
            raise VerificationCacheError(
                f"unsupported verification cache entry schema: {self.schema_version!r}"
            )
        computed = self.compute_entry_digest()
        if self.entry_digest:
            if self.entry_digest != computed:
                raise VerificationCacheIntegrityError(
                    "verification cache entry digest mismatch (tampered or stale payload)"
                )
        else:
            object.__setattr__(self, "entry_digest", computed)

    def compute_entry_digest(self) -> str:
        return content_digest(
            {
                "created_at": self.created_at,
                "diagnostics": list(self.diagnostics),
                "evidence_authority": self.evidence_authority.value,
                "key": self.key.to_dict(),
                "polarity": self.polarity.value,
                "result_authority": self.result_authority.value,
                "result_id": self.result_id,
                "result_payload": self.result_payload.to_dict(),
                "schema_version": self.schema_version,
                "status": self.status.value,
            }
        )

    def verify_integrity(self) -> VerificationCacheEntry:
        """Rehash the entry and fail closed on digest drift."""

        computed = self.compute_entry_digest()
        if computed != self.entry_digest:
            raise VerificationCacheIntegrityError(
                "verification cache entry failed integrity rehash"
            )
        return self

    def age_seconds(self, *, now: float | None = None) -> float:
        current = time.time() if now is None else float(now)
        return max(0.0, current - self.created_at)

    def is_expired(
        self,
        *,
        positive_ttl_seconds: float,
        negative_ttl_seconds: float,
        now: float | None = None,
    ) -> bool:
        ttl = (
            negative_ttl_seconds
            if self.polarity is CachePolarity.NEGATIVE
            else positive_ttl_seconds
        )
        if ttl <= 0:
            return False
        return self.age_seconds(now=now) > ttl

    def require_authority_at_most(
        self, ceiling: EvidenceAuthority | str
    ) -> VerificationCacheEntry:
        """Reject when the stored evidence authority exceeds a caller ceiling.

        Hits may only inherit authority; they never raise it.  Callers that
        re-bind a receipt under a lower translation ceiling use this check.
        """

        limit = _evidence_authority(ceiling)
        if authority_rank(self.evidence_authority) > authority_rank(limit):
            raise VerificationCacheAuthorityError(
                f"cache entry authority {self.evidence_authority.value!r} exceeds "
                f"ceiling {limit.value!r}; cache cannot raise authority"
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "diagnostics": list(self.diagnostics),
            "entry_digest": self.entry_digest,
            "evidence_authority": self.evidence_authority.value,
            "key": self.key.to_dict(),
            "polarity": self.polarity.value,
            "result_authority": self.result_authority.value,
            "result_id": self.result_id,
            "result_payload": self.result_payload.to_dict(),
            "schema_version": self.schema_version,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> VerificationCacheEntry:
        if not isinstance(value, Mapping):
            raise VerificationCacheError("verification cache entry must be a mapping")
        payload = dict(value)
        unknown = sorted(set(payload) - set(_ENTRY_FIELDS))
        if unknown:
            raise VerificationCacheError(
                f"unknown verification cache entry field(s): {', '.join(unknown)}"
            )
        key_payload = payload.get("key")
        if not isinstance(key_payload, Mapping):
            raise VerificationCacheError("entry.key must be a mapping")
        return cls(
            key=VerificationCacheKey.from_dict(key_payload),
            result_authority=payload.get("result_authority", ""),
            status=payload.get("status", ""),
            evidence_authority=payload.get(
                "evidence_authority", EvidenceAuthority.NONE.value
            ),
            result_payload=FrozenMap(payload.get("result_payload") or {}),
            polarity=payload.get("polarity", CachePolarity.POSITIVE.value),
            created_at=float(payload.get("created_at", 0.0)),
            entry_digest=str(payload.get("entry_digest") or ""),
            result_id=str(payload.get("result_id") or ""),
            diagnostics=tuple(payload.get("diagnostics") or ()),
            schema_version=payload.get(
                "schema_version", VERIFICATION_CACHE_ENTRY_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_typed_result(
        cls,
        key: VerificationCacheKey,
        result: TypedBackendResult,
        *,
        created_at: float | None = None,
        evidence_authority: EvidenceAuthority | str | None = None,
    ) -> VerificationCacheEntry:
        """Build an entry from a normalized typed backend result.

        ``evidence_authority`` defaults to the result's translation ceiling and
        is clamped so it never exceeds that ceiling.
        """

        if not isinstance(result, TypedBackendResult):
            raise VerificationCacheError(
                "from_typed_result requires a TypedBackendResult"
            )
        ceiling = result.translation_ceiling
        if evidence_authority is None:
            resolved_evidence = ceiling
        else:
            resolved_evidence = _evidence_authority(evidence_authority)
            if authority_rank(resolved_evidence) > authority_rank(ceiling):
                raise VerificationCacheAuthorityError(
                    "cache cannot raise evidence authority above the result "
                    f"translation ceiling ({ceiling.value})"
                )
        return cls(
            key=key,
            result_authority=result.authority,
            status=result.status,
            evidence_authority=resolved_evidence,
            result_payload=FrozenMap(result.to_dict()),
            polarity=polarity_for_status(result.status),
            created_at=time.time() if created_at is None else float(created_at),
            result_id=result.result_id,
            diagnostics=result.diagnostics,
        )


_ENTRY_FIELDS: Final = frozenset(
    {
        "created_at",
        "diagnostics",
        "entry_digest",
        "evidence_authority",
        "key",
        "polarity",
        "result_authority",
        "result_id",
        "result_payload",
        "schema_version",
        "status",
    }
)


@dataclass(frozen=True, slots=True)
class VerificationCacheLookup:
    """Result of a cache lookup with provenance and reason code."""

    entry: VerificationCacheEntry | None
    hit: bool
    usable: bool
    reason: CacheLookupReason
    key_digest: str
    single_flight_shared: bool = False
    age_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "age_seconds": self.age_seconds,
            "entry": None if self.entry is None else self.entry.to_dict(),
            "hit": self.hit,
            "key_digest": self.key_digest,
            "reason": self.reason.value,
            "single_flight_shared": self.single_flight_shared,
            "usable": self.usable,
        }


@dataclass
class _Flight:
    event: threading.Event = field(default_factory=threading.Event)
    entry: VerificationCacheEntry | None = None
    error: BaseException | None = None


@runtime_checkable
class VerificationCacheProtocol(Protocol):
    """Protocol surface for exact verification caches (VerificationCacheProtocol@1)."""

    @property
    def interface(self) -> str: ...

    @property
    def schema_version(self) -> str: ...

    def lookup(
        self,
        key: VerificationCacheKey,
        *,
        require_result_authority: ResultAuthority | str | None = None,
        max_evidence_authority: EvidenceAuthority | str | None = None,
        now: float | None = None,
    ) -> VerificationCacheLookup: ...

    def get(
        self,
        key: VerificationCacheKey,
        *,
        require_result_authority: ResultAuthority | str | None = None,
        max_evidence_authority: EvidenceAuthority | str | None = None,
        now: float | None = None,
    ) -> VerificationCacheEntry | None: ...

    def put(
        self,
        entry: VerificationCacheEntry,
        *,
        now: float | None = None,
    ) -> VerificationCacheLookup: ...

    def get_or_compute(
        self,
        key: VerificationCacheKey,
        producer: Callable[[], VerificationCacheEntry | TypedBackendResult],
        *,
        require_result_authority: ResultAuthority | str | None = None,
        max_evidence_authority: EvidenceAuthority | str | None = None,
        now: float | None = None,
    ) -> VerificationCacheLookup: ...

    def invalidate(self, key: VerificationCacheKey) -> bool: ...

    def stats(self) -> Mapping[str, int]: ...


class ExactVerificationCache:
    """In-process exact verification cache with single-flight and dual TTL.

    This is the default adapter implementing :class:`VerificationCacheProtocol`.
    Legacy Hammer / supervisor caches can wrap this surface without rewriting
    their storage backends.
    """

    def __init__(
        self,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        positive_ttl_seconds: float = DEFAULT_POSITIVE_TTL_SECONDS,
        negative_ttl_seconds: float = DEFAULT_NEGATIVE_TTL_SECONDS,
    ) -> None:
        if max_entries <= 0:
            raise VerificationCacheError("max_entries must be positive")
        if positive_ttl_seconds < 0 or negative_ttl_seconds < 0:
            raise VerificationCacheError("TTL values must be non-negative")
        if negative_ttl_seconds > positive_ttl_seconds and positive_ttl_seconds > 0:
            raise VerificationCacheError(
                "negative_ttl_seconds cannot exceed positive_ttl_seconds"
            )
        self.max_entries = int(max_entries)
        self.positive_ttl_seconds = float(positive_ttl_seconds)
        self.negative_ttl_seconds = float(negative_ttl_seconds)
        self._lock = threading.RLock()
        self._entries: OrderedDict[str, VerificationCacheEntry] = OrderedDict()
        self._flights: dict[str, _Flight] = {}
        self._stats = {
            "hits": 0,
            "misses": 0,
            "writes": 0,
            "evictions": 0,
            "expirations": 0,
            "rejections": 0,
            "single_flight_waits": 0,
            "tamper_rejections": 0,
        }

    @property
    def interface(self) -> str:
        return VERIFICATION_CACHE_PROTOCOL_INTERFACE

    @property
    def schema_version(self) -> str:
        return VERIFICATION_CACHE_PROTOCOL_SCHEMA_VERSION

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                **self._stats,
                "size": len(self._entries),
                "in_flight": len(self._flights),
            }

    def _trim_locked(self, *, now: float) -> None:
        expired: list[str] = []
        for digest, entry in self._entries.items():
            if entry.is_expired(
                positive_ttl_seconds=self.positive_ttl_seconds,
                negative_ttl_seconds=self.negative_ttl_seconds,
                now=now,
            ):
                expired.append(digest)
        for digest in expired:
            del self._entries[digest]
            self._stats["expirations"] += 1
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
            self._stats["evictions"] += 1

    def _evaluate_entry(
        self,
        entry: VerificationCacheEntry,
        key: VerificationCacheKey,
        *,
        require_result_authority: ResultAuthority | None,
        max_evidence_authority: EvidenceAuthority | None,
        now: float,
        single_flight_shared: bool = False,
    ) -> VerificationCacheLookup:
        if entry.key.digest != key.digest:
            self._stats["rejections"] += 1
            return VerificationCacheLookup(
                entry=None,
                hit=False,
                usable=False,
                reason=CacheLookupReason.STALE,
                key_digest=key.digest,
                single_flight_shared=single_flight_shared,
            )
        try:
            entry = entry.verify_integrity()
        except VerificationCacheIntegrityError:
            self._stats["tamper_rejections"] += 1
            self._stats["rejections"] += 1
            return VerificationCacheLookup(
                entry=None,
                hit=False,
                usable=False,
                reason=CacheLookupReason.TAMPERED,
                key_digest=key.digest,
                single_flight_shared=single_flight_shared,
            )
        if entry.is_expired(
            positive_ttl_seconds=self.positive_ttl_seconds,
            negative_ttl_seconds=self.negative_ttl_seconds,
            now=now,
        ):
            self._stats["expirations"] += 1
            return VerificationCacheLookup(
                entry=None,
                hit=False,
                usable=False,
                reason=CacheLookupReason.EXPIRED,
                key_digest=key.digest,
                age_seconds=entry.age_seconds(now=now),
                single_flight_shared=single_flight_shared,
            )
        if (
            require_result_authority is not None
            and entry.result_authority is not require_result_authority
        ):
            self._stats["rejections"] += 1
            return VerificationCacheLookup(
                entry=entry,
                hit=True,
                usable=False,
                reason=CacheLookupReason.AUTHORITY_MISMATCH,
                key_digest=key.digest,
                age_seconds=entry.age_seconds(now=now),
                single_flight_shared=single_flight_shared,
            )
        if max_evidence_authority is not None:
            try:
                entry.require_authority_at_most(max_evidence_authority)
            except VerificationCacheAuthorityError:
                self._stats["rejections"] += 1
                return VerificationCacheLookup(
                    entry=entry,
                    hit=True,
                    usable=False,
                    reason=CacheLookupReason.INSUFFICIENT_AUTHORITY,
                    key_digest=key.digest,
                    age_seconds=entry.age_seconds(now=now),
                    single_flight_shared=single_flight_shared,
                )
        reason = (
            CacheLookupReason.NEGATIVE_HIT
            if entry.polarity is CachePolarity.NEGATIVE
            else CacheLookupReason.HIT
        )
        if single_flight_shared:
            reason = CacheLookupReason.SINGLE_FLIGHT_SHARED
        self._stats["hits"] += 1
        return VerificationCacheLookup(
            entry=entry,
            hit=True,
            usable=True,
            reason=reason,
            key_digest=key.digest,
            age_seconds=entry.age_seconds(now=now),
            single_flight_shared=single_flight_shared,
        )

    def lookup(
        self,
        key: VerificationCacheKey,
        *,
        require_result_authority: ResultAuthority | str | None = None,
        max_evidence_authority: EvidenceAuthority | str | None = None,
        now: float | None = None,
    ) -> VerificationCacheLookup:
        if not isinstance(key, VerificationCacheKey):
            raise TypeError("key must be a VerificationCacheKey")
        required = (
            None
            if require_result_authority is None
            else _result_authority(require_result_authority)
        )
        ceiling = (
            None
            if max_evidence_authority is None
            else _evidence_authority(max_evidence_authority)
        )
        current = time.time() if now is None else float(now)
        with self._lock:
            entry = self._entries.get(key.digest)
            if entry is None:
                self._trim_locked(now=current)
                self._stats["misses"] += 1
                return VerificationCacheLookup(
                    entry=None,
                    hit=False,
                    usable=False,
                    reason=CacheLookupReason.MISS,
                    key_digest=key.digest,
                )
            result = self._evaluate_entry(
                entry,
                key,
                require_result_authority=required,
                max_evidence_authority=ceiling,
                now=current,
            )
            if result.reason in {
                CacheLookupReason.EXPIRED,
                CacheLookupReason.TAMPERED,
                CacheLookupReason.STALE,
            }:
                self._entries.pop(key.digest, None)
            elif result.usable:
                # Move usable hits to end for LRU after a successful evaluation.
                self._entries.move_to_end(key.digest)
            self._trim_locked(now=current)
            return result

    def get(
        self,
        key: VerificationCacheKey,
        *,
        require_result_authority: ResultAuthority | str | None = None,
        max_evidence_authority: EvidenceAuthority | str | None = None,
        now: float | None = None,
    ) -> VerificationCacheEntry | None:
        result = self.lookup(
            key,
            require_result_authority=require_result_authority,
            max_evidence_authority=max_evidence_authority,
            now=now,
        )
        return result.entry if result.usable else None

    def put(
        self,
        entry: VerificationCacheEntry,
        *,
        now: float | None = None,
    ) -> VerificationCacheLookup:
        if not isinstance(entry, VerificationCacheEntry):
            raise TypeError("entry must be a VerificationCacheEntry")
        # Round-trip revalidates integrity and JSON safety.
        entry = VerificationCacheEntry.from_dict(entry.to_dict()).verify_integrity()
        current = time.time() if now is None else float(now)
        with self._lock:
            self._entries[entry.key.digest] = entry
            self._entries.move_to_end(entry.key.digest)
            self._trim_locked(now=current)
            self._stats["writes"] += 1
            return VerificationCacheLookup(
                entry=entry,
                hit=False,
                usable=True,
                reason=CacheLookupReason.STORED,
                key_digest=entry.key.digest,
                age_seconds=entry.age_seconds(now=current),
            )

    def put_result(
        self,
        key: VerificationCacheKey,
        result: TypedBackendResult,
        *,
        evidence_authority: EvidenceAuthority | str | None = None,
        now: float | None = None,
    ) -> VerificationCacheLookup:
        """Store a typed backend result under ``key`` without raising authority."""

        entry = VerificationCacheEntry.from_typed_result(
            key,
            result,
            created_at=time.time() if now is None else float(now),
            evidence_authority=evidence_authority,
        )
        return self.put(entry, now=now)

    def get_or_compute(
        self,
        key: VerificationCacheKey,
        producer: Callable[[], VerificationCacheEntry | TypedBackendResult],
        *,
        require_result_authority: ResultAuthority | str | None = None,
        max_evidence_authority: EvidenceAuthority | str | None = None,
        now: float | None = None,
    ) -> VerificationCacheLookup:
        """Lookup, or single-flight compute and store on miss.

        Concurrent callers with the same key wait on one producer invocation.
        """

        if not isinstance(key, VerificationCacheKey):
            raise TypeError("key must be a VerificationCacheKey")
        if not callable(producer):
            raise TypeError("producer must be callable")

        existing = self.lookup(
            key,
            require_result_authority=require_result_authority,
            max_evidence_authority=max_evidence_authority,
            now=now,
        )
        if existing.usable:
            return existing

        leader = False
        flight: _Flight
        with self._lock:
            # Re-check under lock after the initial unlocked lookup.
            recheck = self.lookup(
                key,
                require_result_authority=require_result_authority,
                max_evidence_authority=max_evidence_authority,
                now=now,
            )
            if recheck.usable:
                return recheck
            existing_flight = self._flights.get(key.digest)
            if existing_flight is None:
                flight = _Flight()
                self._flights[key.digest] = flight
                leader = True
            else:
                flight = existing_flight

        if not leader:
            self._stats["single_flight_waits"] += 1
            flight.event.wait()
            if flight.error is not None:
                raise flight.error
            if flight.entry is None:
                return VerificationCacheLookup(
                    entry=None,
                    hit=False,
                    usable=False,
                    reason=CacheLookupReason.MISS,
                    key_digest=key.digest,
                    single_flight_shared=True,
                )
            current = time.time() if now is None else float(now)
            required = (
                None
                if require_result_authority is None
                else _result_authority(require_result_authority)
            )
            ceiling = (
                None
                if max_evidence_authority is None
                else _evidence_authority(max_evidence_authority)
            )
            return self._evaluate_entry(
                flight.entry,
                key,
                require_result_authority=required,
                max_evidence_authority=ceiling,
                now=current,
                single_flight_shared=True,
            )

        try:
            produced = producer()
            if isinstance(produced, TypedBackendResult):
                entry = VerificationCacheEntry.from_typed_result(
                    key,
                    produced,
                    created_at=time.time() if now is None else float(now),
                )
            elif isinstance(produced, VerificationCacheEntry):
                if produced.key.digest != key.digest:
                    raise VerificationCacheError(
                        "producer entry key does not match requested key"
                    )
                entry = produced.verify_integrity()
            else:
                raise VerificationCacheError(
                    "producer must return VerificationCacheEntry or TypedBackendResult"
                )
            stored = self.put(entry, now=now)
            flight.entry = stored.entry
            return VerificationCacheLookup(
                entry=stored.entry,
                hit=False,
                usable=True,
                reason=CacheLookupReason.STORED,
                key_digest=key.digest,
                single_flight_shared=False,
            )
        except BaseException as error:
            flight.error = error
            raise
        finally:
            flight.event.set()
            with self._lock:
                if self._flights.get(key.digest) is flight:
                    del self._flights[key.digest]

    def invalidate(self, key: VerificationCacheKey) -> bool:
        if not isinstance(key, VerificationCacheKey):
            raise TypeError("key must be a VerificationCacheKey")
        with self._lock:
            removed = self._entries.pop(key.digest, None) is not None
            if removed:
                self._stats["evictions"] += 1
            return removed

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            for flight in self._flights.values():
                flight.event.set()
            self._flights.clear()


def build_verification_cache_key(
    *,
    ir: Any,
    property_: Any = None,
    property_value: Any = None,
    assumptions: Any = (),
    translation: Any = None,
    backend_id: str,
    backend_binary: Any = "unspecified",
    backend_version: str,
    backend_config: Any = None,
    resources: Any = None,
    tree: Any = None,
    policy: Any = None,
) -> VerificationCacheKey:
    """Public builder matching the common keyword surface for adapters."""

    return VerificationCacheKey.build(
        ir=ir,
        property_=property_,
        property_value=property_value,
        assumptions=assumptions,
        translation=translation,
        backend_id=backend_id,
        backend_binary=backend_binary,
        backend_version=backend_version,
        backend_config=backend_config,
        resources=resources,
        tree=tree,
        policy=policy,
    )


# Compatibility alias used by objective interface inventory.
VerificationCache = ExactVerificationCache


__all__ = [
    "CacheLookupReason",
    "CachePolarity",
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_NEGATIVE_TTL_SECONDS",
    "DEFAULT_POSITIVE_TTL_SECONDS",
    "ExactVerificationCache",
    "VERIFICATION_CACHE_ENTRY_SCHEMA_VERSION",
    "VERIFICATION_CACHE_KEY_SCHEMA_VERSION",
    "VERIFICATION_CACHE_PROTOCOL_INTERFACE",
    "VERIFICATION_CACHE_PROTOCOL_SCHEMA_VERSION",
    "VerificationCache",
    "VerificationCacheAuthorityError",
    "VerificationCacheEntry",
    "VerificationCacheError",
    "VerificationCacheIntegrityError",
    "VerificationCacheKey",
    "VerificationCacheLookup",
    "VerificationCacheProtocol",
    "authority_rank",
    "build_verification_cache_key",
    "content_digest",
    "identity_digest",
    "polarity_for_status",
]
