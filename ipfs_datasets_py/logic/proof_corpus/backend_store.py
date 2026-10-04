"""BackendProofCorpusStore@1 — bridge validated backend receipts into a corpus.

Software-verification backends produce attempt, proof, and counterexample
receipts.  This module content-addresses those receipts under a storage-neutral
surface so exact caches, supervisor artifact stores, or the multi-family
:class:`~ipfs_datasets_py.logic.proof_corpus.store.ProofCorpusStore` can all
persist the same immutable records without forcing one storage implementation.

Integrity is fail-closed:

* every stored record rehashes on load and rejects digest drift;
* cache keys are re-bound to the record identity;
* evidence authority is frozen at write time and never raised on read;
* only validated entries (integrity-verified cache entries or typed results
  with conclusive bindings) are admitted.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Protocol, runtime_checkable

from ..backends.cache_protocol import (
    VERIFICATION_CACHE_PROTOCOL_INTERFACE,
    CachePolarity,
    ExactVerificationCache,
    VerificationCacheAuthorityError,
    VerificationCacheEntry,
    VerificationCacheError,
    VerificationCacheIntegrityError,
    VerificationCacheKey,
    VerificationCacheProtocol,
    authority_rank,
    content_digest,
    identity_digest,
)
from ..backends.results import (
    ResultAuthority,
    ResultStatus,
    TypedBackendResult,
)
from ..families.models import EvidenceAuthority
from ..ir_core.claims import FrozenMap

BACKEND_PROOF_CORPUS_STORE_INTERFACE: Final = "BackendProofCorpusStore@1"
BACKEND_PROOF_CORPUS_STORE_SCHEMA_VERSION: Final = "backend-proof-corpus-store/v1"
BACKEND_PROOF_CORPUS_RECORD_SCHEMA_VERSION: Final = "backend-proof-corpus-record/v1"


class BackendProofCorpusError(ValueError):
    """Raised when a backend corpus record or store operation is invalid."""


class BackendProofCorpusIntegrityError(BackendProofCorpusError):
    """Raised when a stored record fails integrity rehash or key rebinding."""


class BackendProofCorpusAuthorityError(BackendProofCorpusError):
    """Raised when a write would raise or substitute evidence authority."""


class BackendReceiptKind(StrEnum):
    """Closed vocabulary for receipts admitted into the backend corpus."""

    ATTEMPT = "attempt"
    PROOF = "proof"
    COUNTEREXAMPLE = "counterexample"
    NEGATIVE = "negative"


_PROOF_STATUSES: Final = frozenset(
    {
        ResultStatus.PROVED,
        ResultStatus.UNSATISFIABLE,
        ResultStatus.SATISFIED,
        ResultStatus.AUTHORIZED,
        ResultStatus.SECURE,
        ResultStatus.RECONSTRUCTED,
        ResultStatus.ATTESTED,
    }
)
_COUNTEREXAMPLE_STATUSES: Final = frozenset(
    {
        ResultStatus.DISPROVED,
        ResultStatus.SATISFIABLE,
        ResultStatus.VIOLATED,
        ResultStatus.DENIED,
        ResultStatus.ATTACK_FOUND,
    }
)
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
        ResultStatus.CANDIDATE,
    }
)


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
        raise BackendProofCorpusError(
            f"{field_name} must be {qualifier}non-empty trimmed string without NUL"
        )
    return value


def _enum(value: object, enum_type: type[Any], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise BackendProofCorpusError(
            f"{field_name} must be one of {choices}"
        ) from error


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise BackendProofCorpusError("floating-point values must be finite")
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
    raise BackendProofCorpusError(
        f"value of type {type(value).__name__} is not JSON-serializable for the corpus"
    )


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        _json_ready(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def receipt_kind_for_status(status: ResultStatus | str) -> BackendReceiptKind:
    """Map a typed backend result status onto a closed receipt kind."""

    resolved = _enum(status, ResultStatus, "status")
    if resolved in _PROOF_STATUSES:
        return BackendReceiptKind.PROOF
    if resolved in _COUNTEREXAMPLE_STATUSES:
        return BackendReceiptKind.COUNTEREXAMPLE
    if resolved in _NEGATIVE_STATUSES:
        return BackendReceiptKind.NEGATIVE
    # Remaining statuses (e.g. candidate-adjacent) are attempt provenance only.
    return BackendReceiptKind.ATTEMPT


@runtime_checkable
class BackendCorpusStorage(Protocol):
    """Minimal storage surface — any content-addressed backend may implement this."""

    def put_bytes(self, key: str, payload: bytes) -> None: ...

    def get_bytes(self, key: str) -> bytes | None: ...

    def delete(self, key: str) -> bool: ...

    def list_keys(self) -> Sequence[str]: ...


class InMemoryBackendCorpusStorage:
    """Process-local content-addressed storage used by tests and default adapters."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}
        self._lock = threading.RLock()

    def put_bytes(self, key: str, payload: bytes) -> None:
        if not isinstance(key, str) or not key:
            raise BackendProofCorpusError("storage key must be a non-empty string")
        if not isinstance(payload, (bytes, bytearray)):
            raise BackendProofCorpusError("storage payload must be bytes")
        with self._lock:
            self._data[key] = bytes(payload)

    def get_bytes(self, key: str) -> bytes | None:
        with self._lock:
            return self._data.get(key)

    def delete(self, key: str) -> bool:
        with self._lock:
            return self._data.pop(key, None) is not None

    def list_keys(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._data))


@dataclass(frozen=True, slots=True)
class BackendCorpusRecord:
    """Immutable, integrity-bound backend receipt stored in the corpus.

    Records bind a verification cache key, typed result authority, evidence
    ceiling, and receipt kind.  Digests are recomputed on load.
    """

    key: VerificationCacheKey
    kind: BackendReceiptKind
    result_authority: ResultAuthority
    status: ResultStatus
    evidence_authority: EvidenceAuthority
    result_payload: FrozenMap
    content_digest: str = ""
    content_cid: str = ""
    source_entry_digest: str = ""
    created_at: float = 0.0
    result_id: str = ""
    diagnostics: tuple[str, ...] = ()
    schema_version: str = BACKEND_PROOF_CORPUS_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.key, VerificationCacheKey):
            raise BackendProofCorpusError("record.key must be a VerificationCacheKey")
        object.__setattr__(self, "kind", _enum(self.kind, BackendReceiptKind, "kind"))
        object.__setattr__(
            self,
            "result_authority",
            _enum(self.result_authority, ResultAuthority, "result_authority"),
        )
        object.__setattr__(self, "status", _enum(self.status, ResultStatus, "status"))
        object.__setattr__(
            self,
            "evidence_authority",
            _enum(self.evidence_authority, EvidenceAuthority, "evidence_authority"),
        )
        try:
            payload = (
                self.result_payload
                if isinstance(self.result_payload, FrozenMap)
                else FrozenMap(self.result_payload)
            )
        except (TypeError, ValueError) as error:
            raise BackendProofCorpusError(
                "result_payload must be an immutable JSON mapping"
            ) from error
        object.__setattr__(self, "result_payload", payload)
        if not isinstance(self.created_at, (int, float)) or self.created_at != self.created_at:
            raise BackendProofCorpusError("created_at must be a finite number")
        object.__setattr__(self, "created_at", float(self.created_at))
        object.__setattr__(
            self,
            "source_entry_digest",
            _text(self.source_entry_digest, "source_entry_digest", optional=True),
        )
        object.__setattr__(
            self, "result_id", _text(self.result_id, "result_id", optional=True)
        )
        diagnostics = tuple(
            _text(item, "diagnostics item") for item in (self.diagnostics or ())
        )
        if len(diagnostics) != len(set(diagnostics)):
            raise BackendProofCorpusError("diagnostics must not contain duplicates")
        object.__setattr__(self, "diagnostics", diagnostics)
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != BACKEND_PROOF_CORPUS_RECORD_SCHEMA_VERSION:
            raise BackendProofCorpusError(
                f"unsupported backend corpus record schema: {self.schema_version!r}"
            )
        computed = self.compute_content_digest()
        if self.content_digest:
            if self.content_digest != computed:
                raise BackendProofCorpusIntegrityError(
                    "backend corpus record content digest mismatch"
                )
        else:
            object.__setattr__(self, "content_digest", computed)
        if not self.content_cid:
            object.__setattr__(
                self,
                "content_cid",
                f"backend-receipt:{self.content_digest}",
            )
        else:
            object.__setattr__(
                self, "content_cid", _text(self.content_cid, "content_cid")
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "diagnostics": list(self.diagnostics),
            "evidence_authority": self.evidence_authority.value,
            "key": self.key.to_dict(),
            "kind": self.kind.value,
            "result_authority": self.result_authority.value,
            "result_id": self.result_id,
            "result_payload": self.result_payload.to_dict(),
            "schema_version": self.schema_version,
            "source_entry_digest": self.source_entry_digest,
            "status": self.status.value,
        }

    def compute_content_digest(self) -> str:
        return content_digest(self.identity_payload())

    def verify_integrity(self) -> BackendCorpusRecord:
        computed = self.compute_content_digest()
        if computed != self.content_digest:
            raise BackendProofCorpusIntegrityError(
                "backend corpus record failed integrity rehash"
            )
        return self

    def require_authority_at_most(
        self, ceiling: EvidenceAuthority | str
    ) -> BackendCorpusRecord:
        limit = _enum(ceiling, EvidenceAuthority, "evidence_authority ceiling")
        if authority_rank(self.evidence_authority) > authority_rank(limit):
            raise BackendProofCorpusAuthorityError(
                f"record authority {self.evidence_authority.value!r} exceeds "
                f"ceiling {limit.value!r}; corpus cannot raise authority"
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["content_cid"] = self.content_cid
        payload["content_digest"] = self.content_digest
        return payload

    def to_canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> BackendCorpusRecord:
        if not isinstance(value, Mapping):
            raise BackendProofCorpusError("backend corpus record must be a mapping")
        payload = dict(value)
        unknown = sorted(set(payload) - set(_RECORD_FIELDS))
        if unknown:
            raise BackendProofCorpusError(
                f"unknown backend corpus record field(s): {', '.join(unknown)}"
            )
        key_payload = payload.get("key")
        if not isinstance(key_payload, Mapping):
            raise BackendProofCorpusError("record.key must be a mapping")
        return cls(
            key=VerificationCacheKey.from_dict(key_payload),
            kind=payload.get("kind", BackendReceiptKind.ATTEMPT.value),
            result_authority=payload.get("result_authority", ""),
            status=payload.get("status", ""),
            evidence_authority=payload.get(
                "evidence_authority", EvidenceAuthority.NONE.value
            ),
            result_payload=FrozenMap(payload.get("result_payload") or {}),
            content_digest=str(payload.get("content_digest") or ""),
            content_cid=str(payload.get("content_cid") or ""),
            source_entry_digest=str(payload.get("source_entry_digest") or ""),
            created_at=float(payload.get("created_at", 0.0)),
            result_id=str(payload.get("result_id") or ""),
            diagnostics=tuple(payload.get("diagnostics") or ()),
            schema_version=payload.get(
                "schema_version", BACKEND_PROOF_CORPUS_RECORD_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_cache_entry(
        cls,
        entry: VerificationCacheEntry,
        *,
        kind: BackendReceiptKind | str | None = None,
    ) -> BackendCorpusRecord:
        """Admit a validated cache entry into an immutable corpus record."""

        if not isinstance(entry, VerificationCacheEntry):
            raise BackendProofCorpusError(
                "from_cache_entry requires a VerificationCacheEntry"
            )
        entry = entry.verify_integrity()
        if kind is None:
            if entry.polarity is CachePolarity.NEGATIVE:
                resolved_kind = BackendReceiptKind.NEGATIVE
            else:
                resolved_kind = receipt_kind_for_status(entry.status)
        else:
            resolved_kind = _enum(kind, BackendReceiptKind, "kind")
        return cls(
            key=entry.key,
            kind=resolved_kind,
            result_authority=entry.result_authority,
            status=entry.status,
            evidence_authority=entry.evidence_authority,
            result_payload=entry.result_payload,
            source_entry_digest=entry.entry_digest,
            created_at=entry.created_at,
            result_id=entry.result_id,
            diagnostics=entry.diagnostics,
        )

    @classmethod
    def from_typed_result(
        cls,
        key: VerificationCacheKey,
        result: TypedBackendResult,
        *,
        kind: BackendReceiptKind | str | None = None,
        evidence_authority: EvidenceAuthority | str | None = None,
        created_at: float | None = None,
    ) -> BackendCorpusRecord:
        """Admit a typed backend result under an exact cache key."""

        if not isinstance(result, TypedBackendResult):
            raise BackendProofCorpusError(
                "from_typed_result requires a TypedBackendResult"
            )
        entry = VerificationCacheEntry.from_typed_result(
            key,
            result,
            created_at=time.time() if created_at is None else float(created_at),
            evidence_authority=evidence_authority,
        )
        return cls.from_cache_entry(entry, kind=kind)


_RECORD_FIELDS: Final = frozenset(
    {
        "content_cid",
        "content_digest",
        "created_at",
        "diagnostics",
        "evidence_authority",
        "key",
        "kind",
        "result_authority",
        "result_id",
        "result_payload",
        "schema_version",
        "source_entry_digest",
        "status",
    }
)


@runtime_checkable
class BackendProofCorpusStoreProtocol(Protocol):
    """Protocol surface for BackendProofCorpusStore@1."""

    @property
    def interface(self) -> str: ...

    @property
    def schema_version(self) -> str: ...

    def put(self, record: BackendCorpusRecord) -> BackendCorpusRecord: ...

    def get(self, content_digest: str) -> BackendCorpusRecord: ...

    def get_by_key(self, key: VerificationCacheKey) -> BackendCorpusRecord | None: ...

    def put_from_cache_entry(
        self, entry: VerificationCacheEntry
    ) -> BackendCorpusRecord: ...

    def put_from_result(
        self,
        key: VerificationCacheKey,
        result: TypedBackendResult,
        *,
        kind: BackendReceiptKind | str | None = None,
        evidence_authority: EvidenceAuthority | str | None = None,
    ) -> BackendCorpusRecord: ...

    def bridge_cache_hit(
        self,
        cache: VerificationCacheProtocol,
        key: VerificationCacheKey,
    ) -> BackendCorpusRecord | None: ...


class BackendProofCorpusStore:
    """Content-addressed store for validated backend attempt/proof/counterexample receipts.

    Storage is injected via :class:`BackendCorpusStorage` so filesystem, memory,
    IPFS, or supervisor artifact backends can all host the same record shape.
    An optional verification cache can be bridged so exact hits become durable
    corpus records without re-running solvers.
    """

    def __init__(
        self,
        storage: BackendCorpusStorage | None = None,
        *,
        cache: VerificationCacheProtocol | None = None,
    ) -> None:
        self._storage: BackendCorpusStorage = (
            storage if storage is not None else InMemoryBackendCorpusStorage()
        )
        self._cache = cache
        self._lock = threading.RLock()
        # Secondary index: verification-cache key digest -> content digest
        self._key_index: dict[str, str] = {}
        self._hits = 0
        self._misses = 0
        self._writes = 0
        self._rejections = 0

    @property
    def interface(self) -> str:
        return BACKEND_PROOF_CORPUS_STORE_INTERFACE

    @property
    def schema_version(self) -> str:
        return BACKEND_PROOF_CORPUS_STORE_SCHEMA_VERSION

    @property
    def cache_interface(self) -> str:
        return VERIFICATION_CACHE_PROTOCOL_INTERFACE

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "writes": self._writes,
                "rejections": self._rejections,
                "size": len(self._key_index),
            }

    def _storage_key(self, content_digest_value: str) -> str:
        digest = identity_digest(content_digest_value)
        return f"backend-proof-corpus/{digest}"

    def put(self, record: BackendCorpusRecord) -> BackendCorpusRecord:
        """Persist a validated record and return the integrity-verified copy."""

        if not isinstance(record, BackendCorpusRecord):
            raise TypeError("record must be a BackendCorpusRecord")
        verified = BackendCorpusRecord.from_dict(record.to_dict()).verify_integrity()
        payload = verified.to_canonical_bytes()
        with self._lock:
            self._storage.put_bytes(self._storage_key(verified.content_digest), payload)
            self._key_index[verified.key.digest] = verified.content_digest
            self._writes += 1
            return verified

    def get(self, content_digest_value: str) -> BackendCorpusRecord:
        """Load one record by content digest (fail closed on missing/tamper)."""

        digest = identity_digest(content_digest_value)
        with self._lock:
            raw = self._storage.get_bytes(self._storage_key(digest))
            if raw is None:
                self._misses += 1
                raise BackendProofCorpusError(
                    f"backend corpus record not found for content_digest={digest!r}"
                )
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as error:
                self._rejections += 1
                raise BackendProofCorpusIntegrityError(
                    "backend corpus record is unreadable or not JSON"
                ) from error
            try:
                record = BackendCorpusRecord.from_dict(payload).verify_integrity()
            except (
                BackendProofCorpusError,
                VerificationCacheError,
                VerificationCacheIntegrityError,
            ) as error:
                self._rejections += 1
                raise BackendProofCorpusIntegrityError(
                    f"backend corpus record failed integrity: {error}"
                ) from error
            if record.content_digest != digest:
                self._rejections += 1
                raise BackendProofCorpusIntegrityError(
                    "stored content digest does not match requested digest"
                )
            self._key_index[record.key.digest] = record.content_digest
            self._hits += 1
            return record

    def get_by_key(self, key: VerificationCacheKey) -> BackendCorpusRecord | None:
        """Return the corpus record currently indexed under a verification key."""

        if not isinstance(key, VerificationCacheKey):
            raise TypeError("key must be a VerificationCacheKey")
        with self._lock:
            content = self._key_index.get(key.digest)
            if content is None:
                # Rebuild index from storage if needed.
                for storage_key in self._storage.list_keys():
                    raw = self._storage.get_bytes(storage_key)
                    if raw is None:
                        continue
                    try:
                        payload = json.loads(raw.decode("utf-8"))
                        record = BackendCorpusRecord.from_dict(payload).verify_integrity()
                    except Exception:
                        continue
                    self._key_index[record.key.digest] = record.content_digest
                content = self._key_index.get(key.digest)
            if content is None:
                self._misses += 1
                return None
        try:
            record = self.get(content)
        except BackendProofCorpusError:
            return None
        if record.key.digest != key.digest:
            self._rejections += 1
            raise BackendProofCorpusIntegrityError(
                "indexed record key digest does not match requested key"
            )
        return record

    def put_from_cache_entry(
        self, entry: VerificationCacheEntry
    ) -> BackendCorpusRecord:
        """Bridge a validated exact-cache entry into the immutable corpus."""

        try:
            record = BackendCorpusRecord.from_cache_entry(entry)
        except (
            BackendProofCorpusError,
            VerificationCacheError,
            VerificationCacheIntegrityError,
            VerificationCacheAuthorityError,
        ) as error:
            self._rejections += 1
            raise BackendProofCorpusError(
                f"cannot admit cache entry into corpus: {error}"
            ) from error
        return self.put(record)

    def put_from_result(
        self,
        key: VerificationCacheKey,
        result: TypedBackendResult,
        *,
        kind: BackendReceiptKind | str | None = None,
        evidence_authority: EvidenceAuthority | str | None = None,
    ) -> BackendCorpusRecord:
        """Validate and store a typed backend result under an exact key."""

        try:
            record = BackendCorpusRecord.from_typed_result(
                key,
                result,
                kind=kind,
                evidence_authority=evidence_authority,
            )
        except (
            BackendProofCorpusError,
            VerificationCacheError,
            VerificationCacheAuthorityError,
        ) as error:
            self._rejections += 1
            raise BackendProofCorpusError(
                f"cannot admit typed result into corpus: {error}"
            ) from error
        return self.put(record)

    def bridge_cache_hit(
        self,
        cache: VerificationCacheProtocol | None,
        key: VerificationCacheKey,
        *,
        require_result_authority: ResultAuthority | str | None = None,
        max_evidence_authority: EvidenceAuthority | str | None = None,
    ) -> BackendCorpusRecord | None:
        """If ``cache`` has a usable hit for ``key``, persist it into the corpus.

        Returns the durable record, or ``None`` when the cache misses or the
        hit is unusable.  Already-stored records are returned without rewrite
        when content digests match.
        """

        active_cache = cache if cache is not None else self._cache
        if active_cache is None:
            raise BackendProofCorpusError(
                "bridge_cache_hit requires a VerificationCacheProtocol"
            )
        lookup = active_cache.lookup(
            key,
            require_result_authority=require_result_authority,
            max_evidence_authority=max_evidence_authority,
        )
        if not lookup.usable or lookup.entry is None:
            return None
        existing = self.get_by_key(key)
        if existing is not None:
            candidate = BackendCorpusRecord.from_cache_entry(lookup.entry)
            if existing.content_digest == candidate.content_digest:
                return existing
        return self.put_from_cache_entry(lookup.entry)

    def put_attempt(
        self,
        key: VerificationCacheKey,
        result: TypedBackendResult,
        *,
        evidence_authority: EvidenceAuthority | str | None = None,
    ) -> BackendCorpusRecord:
        """Store an attempt receipt (explicit kind)."""

        return self.put_from_result(
            key,
            result,
            kind=BackendReceiptKind.ATTEMPT,
            evidence_authority=evidence_authority,
        )

    def put_proof(
        self,
        key: VerificationCacheKey,
        result: TypedBackendResult,
        *,
        evidence_authority: EvidenceAuthority | str | None = None,
    ) -> BackendCorpusRecord:
        """Store a proof receipt after status validation."""

        kind = receipt_kind_for_status(result.status)
        if kind is not BackendReceiptKind.PROOF:
            raise BackendProofCorpusError(
                f"status {result.status.value!r} is not a proof receipt"
            )
        return self.put_from_result(
            key,
            result,
            kind=BackendReceiptKind.PROOF,
            evidence_authority=evidence_authority,
        )

    def put_counterexample(
        self,
        key: VerificationCacheKey,
        result: TypedBackendResult,
        *,
        evidence_authority: EvidenceAuthority | str | None = None,
    ) -> BackendCorpusRecord:
        """Store a counterexample / disproof receipt after status validation."""

        kind = receipt_kind_for_status(result.status)
        if kind is not BackendReceiptKind.COUNTEREXAMPLE:
            raise BackendProofCorpusError(
                f"status {result.status.value!r} is not a counterexample receipt"
            )
        return self.put_from_result(
            key,
            result,
            kind=BackendReceiptKind.COUNTEREXAMPLE,
            evidence_authority=evidence_authority,
        )

    def list_by_kind(self, kind: BackendReceiptKind | str) -> tuple[BackendCorpusRecord, ...]:
        """Return all integrity-verified records of a given kind."""

        resolved = _enum(kind, BackendReceiptKind, "kind")
        records: list[BackendCorpusRecord] = []
        with self._lock:
            storage_keys = list(self._storage.list_keys())
        for storage_key in storage_keys:
            raw = self._storage.get_bytes(storage_key)
            if raw is None:
                continue
            try:
                payload = json.loads(raw.decode("utf-8"))
                record = BackendCorpusRecord.from_dict(payload).verify_integrity()
            except Exception:
                continue
            if record.kind is resolved:
                records.append(record)
        records.sort(key=lambda item: item.content_digest)
        return tuple(records)


def build_backend_proof_corpus_store(
    *,
    storage: BackendCorpusStorage | None = None,
    cache: VerificationCacheProtocol | None = None,
    with_default_cache: bool = False,
) -> BackendProofCorpusStore:
    """Factory for BackendProofCorpusStore@1 with optional exact-cache wiring."""

    active_cache: VerificationCacheProtocol | None = cache
    if active_cache is None and with_default_cache:
        active_cache = ExactVerificationCache()
    return BackendProofCorpusStore(storage=storage, cache=active_cache)


__all__ = [
    "BACKEND_PROOF_CORPUS_RECORD_SCHEMA_VERSION",
    "BACKEND_PROOF_CORPUS_STORE_INTERFACE",
    "BACKEND_PROOF_CORPUS_STORE_SCHEMA_VERSION",
    "BackendCorpusRecord",
    "BackendCorpusStorage",
    "BackendProofCorpusAuthorityError",
    "BackendProofCorpusError",
    "BackendProofCorpusIntegrityError",
    "BackendProofCorpusStore",
    "BackendProofCorpusStoreProtocol",
    "BackendReceiptKind",
    "InMemoryBackendCorpusStorage",
    "build_backend_proof_corpus_store",
    "receipt_kind_for_status",
]
