"""Persistent, trust-aware single-flight cache for proof obligations.

The ordinary logic proof caches predate the hammer trust boundary and key
results only by a formula/prover pair.  That is insufficient for reconstructed
proofs: changing a selected premise, translator, solver, Lean kernel, theorem
registry, policy, or resource limit can change the meaning of a cached result.

This module therefore keeps the cache contract deliberately small and strict:

* :class:`ProofCacheKey` content-addresses every input that can affect a run;
* :class:`ProofCacheOutcome` distinguishes trusted outcomes from explicitly
  non-trusted ATP/SMT candidates and refuses unsupported trust promotions;
* :class:`PersistentProofCache` persists JSON-safe entries atomically and
  coalesces concurrent identical work in one process ("single flight"); and
* every lookup returns :class:`ProofCacheProvenance`, suitable for embedding
  directly in a reconstruction receipt.

An ATP saying ``proved`` is not a trusted authority.  A trusted outcome must
record either native-kernel acceptance or a deterministic trusted decision.
That invariant is validated both when writing and when loading the cache.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
import unicodedata
from collections import OrderedDict
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence


PROOF_CACHE_SCHEMA_VERSION = "hammer-proof-obligation-cache-v1"
PROOF_CACHE_KEY_SCHEMA_VERSION = "hammer-proof-obligation-key-v1"
PROOF_CACHE_OUTCOME_SCHEMA_VERSION = "hammer-proof-outcome-v1"


class ProofCacheError(ValueError):
    """Base class for malformed cache keys, outcomes, or persistence data."""


class ProofCacheTrustError(ProofCacheError):
    """Raised when an unverified result is presented as a trusted proof."""


class ProofTrust(str, Enum):
    """Trust classification of a cached proof outcome."""

    TRUSTED = "trusted"
    NON_TRUSTED = "non_trusted"


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return _json_ready(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return _json_ready(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_ready(item) for item in sorted(value, key=str)]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    return str(value)


def canonical_json(value: Any) -> str:
    """Return the stable JSON representation used by every cache digest."""

    return json.dumps(
        _json_ready(value),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def content_digest(value: Any) -> str:
    """Return a lowercase SHA-256 digest of canonical JSON data."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def canonicalize_obligation(value: Any) -> Any:
    """Canonicalize an obligation without claiming semantic equivalence.

    Structured obligations are canonicalized as JSON.  Text obligations get
    Unicode NFC normalization, normalized newlines, trimmed lines, and
    collapsed horizontal whitespace.  This matches the hammer corpus's safe,
    syntax-independent normalization without parsing prover source.
    """

    if not isinstance(value, str):
        return _json_ready(value)
    text = (
        unicodedata.normalize("NFC", value)
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    lines = [" ".join(line.strip().split()) for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def _identity_digest(value: Any) -> str:
    if isinstance(value, str) and value.startswith("sha256:") and len(value) == 71:
        return value[7:]
    return content_digest(value)


@dataclass(frozen=True)
class ProofCacheKey:
    """Complete identity of one proof-obligation execution."""

    obligation_digest: str
    selected_premise_digests: tuple[str, ...]
    translation_version_digest: str
    solver_identities_digest: str
    lean_toolchain_identity_digest: str
    theorem_registry_digest: str
    policy_digest: str
    resource_budget_digest: str
    schema_version: str = PROOF_CACHE_KEY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PROOF_CACHE_KEY_SCHEMA_VERSION:
            raise ProofCacheError(
                f"unsupported proof cache key schema: {self.schema_version!r}"
            )
        for name in (
            "obligation_digest",
            "translation_version_digest",
            "solver_identities_digest",
            "lean_toolchain_identity_digest",
            "theorem_registry_digest",
            "policy_digest",
            "resource_budget_digest",
        ):
            if not str(getattr(self, name) or "").strip():
                raise ProofCacheError(f"ProofCacheKey.{name} must be non-empty")

    @classmethod
    def build(
        cls,
        obligation: Any,
        *,
        selected_premise_digests: Sequence[Any] = (),
        selected_premises: Sequence[Any] = (),
        translation_version: Any = "unspecified",
        solver_identities: Any = (),
        lean_toolchain_identity: Any = "not-applicable",
        theorem_registry: Any = "unspecified",
        policy: Any = None,
        resource_budget: Any = None,
    ) -> "ProofCacheKey":
        """Build a key, digesting raw premises when explicit digests are absent."""

        if selected_premise_digests:
            # Callers that already selected content digests should see those
            # exact identities in receipts and diagnostics, not digests of
            # digests. Non-string structured values are still canonicalized.
            premise_digests = tuple(
                sorted(
                    {
                        str(item) if isinstance(item, str) else _identity_digest(item)
                        for item in selected_premise_digests
                    }
                )
            )
        else:
            premise_digests = tuple(
                sorted({_identity_digest(item) for item in selected_premises})
            )
        return cls(
            obligation_digest=content_digest(canonicalize_obligation(obligation)),
            selected_premise_digests=premise_digests,
            translation_version_digest=_identity_digest(translation_version),
            solver_identities_digest=_identity_digest(solver_identities),
            lean_toolchain_identity_digest=_identity_digest(lean_toolchain_identity),
            theorem_registry_digest=_identity_digest(theorem_registry),
            policy_digest=_identity_digest({} if policy is None else policy),
            resource_budget_digest=_identity_digest(
                {} if resource_budget is None else resource_budget
            ),
        )

    @property
    def digest(self) -> str:
        return content_digest(self.to_dict())

    @property
    def cache_key(self) -> str:
        return self.digest

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lean_toolchain_identity_digest": self.lean_toolchain_identity_digest,
            "obligation_digest": self.obligation_digest,
            "policy_digest": self.policy_digest,
            "resource_budget_digest": self.resource_budget_digest,
            "schema_version": self.schema_version,
            "selected_premise_digests": list(self.selected_premise_digests),
            "solver_identities_digest": self.solver_identities_digest,
            "theorem_registry_digest": self.theorem_registry_digest,
            "translation_version_digest": self.translation_version_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProofCacheKey":
        data = dict(value)
        data["selected_premise_digests"] = tuple(data.get("selected_premise_digests") or ())
        return cls(**data)


ProofObligationCacheKey = ProofCacheKey


@dataclass(frozen=True)
class ProofCacheOutcome:
    """JSON-safe result stored under a :class:`ProofCacheKey`.

    ``kernel_accepted`` and ``deterministic_trusted`` are verifier-owned
    attestations.  ``atp_claimed_proof`` is provenance only and can never
    authorize :attr:`trust` ``TRUSTED``.
    """

    status: str
    trust: ProofTrust
    payload: Mapping[str, Any] = field(default_factory=dict)
    kernel_accepted: bool = False
    deterministic_trusted: bool = False
    atp_claimed_proof: bool = False
    authority: str = ""
    schema_version: str = PROOF_CACHE_OUTCOME_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PROOF_CACHE_OUTCOME_SCHEMA_VERSION:
            raise ProofCacheError(
                f"unsupported proof cache outcome schema: {self.schema_version!r}"
            )
        if not str(self.status or "").strip():
            raise ProofCacheError("ProofCacheOutcome.status must be non-empty")
        if not isinstance(self.trust, ProofTrust):
            object.__setattr__(self, "trust", ProofTrust(str(self.trust)))
        if not isinstance(self.payload, Mapping):
            raise ProofCacheError("ProofCacheOutcome.payload must be a mapping")
        if self.trust == ProofTrust.TRUSTED and not (
            self.kernel_accepted or self.deterministic_trusted
        ):
            raise ProofCacheTrustError(
                "trusted cached outcomes require kernel_accepted=True or "
                "deterministic_trusted=True; ATP output alone is non-trusted"
            )

    @property
    def trusted(self) -> bool:
        return self.trust == ProofTrust.TRUSTED

    @classmethod
    def trusted_kernel(
        cls, status: str, payload: Mapping[str, Any], *, authority: str = "lean"
    ) -> "ProofCacheOutcome":
        return cls(
            status,
            ProofTrust.TRUSTED,
            dict(payload),
            kernel_accepted=True,
            authority=authority,
        )

    @classmethod
    def trusted_deterministic(
        cls, status: str, payload: Mapping[str, Any], *, authority: str
    ) -> "ProofCacheOutcome":
        return cls(
            status,
            ProofTrust.TRUSTED,
            dict(payload),
            deterministic_trusted=True,
            authority=authority,
        )

    @classmethod
    def non_trusted(
        cls,
        status: str,
        payload: Mapping[str, Any],
        *,
        atp_claimed_proof: bool = False,
        authority: str = "",
    ) -> "ProofCacheOutcome":
        return cls(
            status,
            ProofTrust.NON_TRUSTED,
            dict(payload),
            atp_claimed_proof=atp_claimed_proof,
            authority=authority,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "atp_claimed_proof": self.atp_claimed_proof,
            "authority": self.authority,
            "deterministic_trusted": self.deterministic_trusted,
            "kernel_accepted": self.kernel_accepted,
            "payload": _json_ready(self.payload),
            "schema_version": self.schema_version,
            "status": self.status,
            "trust": self.trust.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProofCacheOutcome":
        data = dict(value)
        data["trust"] = ProofTrust(str(data.get("trust")))
        data["payload"] = dict(data.get("payload") or {})
        return cls(**data)


CachedProofOutcome = ProofCacheOutcome


@dataclass(frozen=True)
class ProofCacheProvenance:
    """Auditable cache provenance returned with every lookup/execution."""

    key_digest: str
    hit: bool
    usable: bool
    persistent: bool
    trust: str = ""
    entry_digest: str = ""
    created_at: float = 0.0
    age_seconds: float = 0.0
    single_flight_shared: bool = False
    reason: str = ""
    schema_version: str = PROOF_CACHE_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class ProofCacheLookup:
    outcome: Optional[ProofCacheOutcome]
    provenance: ProofCacheProvenance

    @property
    def hit(self) -> bool:
        return self.provenance.hit

    @property
    def usable(self) -> bool:
        return self.provenance.usable


ProofCacheExecution = ProofCacheLookup
CacheLookupResult = ProofCacheLookup


@dataclass
class _Entry:
    key: ProofCacheKey
    outcome: ProofCacheOutcome
    created_at: float
    accessed_at: float

    @property
    def digest(self) -> str:
        return content_digest(
            {
                "created_at": self.created_at,
                "key": self.key.to_dict(),
                "outcome": self.outcome.to_dict(),
            }
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accessed_at": self.accessed_at,
            "created_at": self.created_at,
            "key": self.key.to_dict(),
            "outcome": self.outcome.to_dict(),
        }


@dataclass
class _Flight:
    event: threading.Event = field(default_factory=threading.Event)
    outcome: Optional[ProofCacheOutcome] = None
    error: Optional[BaseException] = None


class PersistentProofCache:
    """Bounded TTL cache with atomic persistence and thread single-flight."""

    def __init__(
        self,
        path: Optional[str | os.PathLike[str]] = None,
        *,
        max_entries: int = 4096,
        ttl_seconds: float = 2_592_000,
        persistence_path: Optional[str | os.PathLike[str]] = None,
        cache_path: Optional[str | os.PathLike[str]] = None,
        maxsize: Optional[int] = None,
        max_size: Optional[int] = None,
        ttl: Optional[float] = None,
    ) -> None:
        if persistence_path is not None:
            path = persistence_path
        if cache_path is not None:
            path = cache_path
        if maxsize is not None:
            max_entries = maxsize
        if max_size is not None:
            max_entries = max_size
        if ttl is not None:
            ttl_seconds = ttl
        if max_entries <= 0:
            raise ProofCacheError("max_entries must be positive")
        if ttl_seconds <= 0:
            raise ProofCacheError("ttl_seconds must be positive")
        self.path = Path(path).expanduser() if path else None
        self.max_entries = int(max_entries)
        self.ttl_seconds = float(ttl_seconds)
        self._lock = threading.RLock()
        self._entries: "OrderedDict[str, _Entry]" = OrderedDict()
        self._flights: Dict[str, _Flight] = {}
        self._stats = {
            "hits": 0,
            "misses": 0,
            "writes": 0,
            "evictions": 0,
            "invalidations": 0,
            "single_flight_waits": 0,
            "load_errors": 0,
        }
        self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.get("schema_version") != PROOF_CACHE_SCHEMA_VERSION:
                return
            now = time.time()
            for value in raw.get("entries", []):
                entry = _Entry(
                    key=ProofCacheKey.from_dict(value["key"]),
                    outcome=ProofCacheOutcome.from_dict(value["outcome"]),
                    created_at=float(value["created_at"]),
                    accessed_at=float(value.get("accessed_at", value["created_at"])),
                )
                if now - entry.created_at <= self.ttl_seconds:
                    self._entries[entry.key.digest] = entry
            self._trim_locked()
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, ProofCacheError):
            self._stats["load_errors"] += 1

    def _persist_locked(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = canonical_json(
            {
                "entries": [entry.to_dict() for entry in self._entries.values()],
                "schema_version": PROOF_CACHE_SCHEMA_VERSION,
            }
        )
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=str(self.path.parent),
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def _trim_locked(self) -> None:
        now = time.time()
        expired = [
            digest
            for digest, entry in self._entries.items()
            if now - entry.created_at > self.ttl_seconds
        ]
        for digest in expired:
            del self._entries[digest]
            self._stats["invalidations"] += 1
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
            self._stats["evictions"] += 1

    def lookup(
        self,
        key: ProofCacheKey,
        *,
        require_trusted: bool = False,
    ) -> ProofCacheLookup:
        if not isinstance(key, ProofCacheKey):
            raise TypeError("key must be a ProofCacheKey")
        with self._lock:
            self._trim_locked()
            entry = self._entries.get(key.digest)
            if entry is None:
                self._stats["misses"] += 1
                return ProofCacheLookup(
                    None,
                    ProofCacheProvenance(
                        key.digest,
                        False,
                        False,
                        self.path is not None,
                        reason="not_found",
                    ),
                )
            entry.accessed_at = time.time()
            self._entries.move_to_end(key.digest)
            usable = not require_trusted or entry.outcome.trusted
            self._stats["hits"] += 1
            return ProofCacheLookup(
                entry.outcome,
                ProofCacheProvenance(
                    key.digest,
                    True,
                    usable,
                    self.path is not None,
                    trust=entry.outcome.trust.value,
                    entry_digest=entry.digest,
                    created_at=entry.created_at,
                    age_seconds=max(0.0, time.time() - entry.created_at),
                    reason="hit" if usable else "insufficient_trust",
                ),
            )

    def get(
        self,
        key: ProofCacheKey,
        *,
        require_trusted: bool = False,
    ) -> Optional[ProofCacheOutcome]:
        result = self.lookup(key, require_trusted=require_trusted)
        return result.outcome if result.usable else None

    def put(self, key: ProofCacheKey, outcome: ProofCacheOutcome) -> ProofCacheProvenance:
        if not isinstance(key, ProofCacheKey) or not isinstance(outcome, ProofCacheOutcome):
            raise TypeError("put requires ProofCacheKey and ProofCacheOutcome")
        # Round-trip validation also guarantees JSON safety and rechecks trust.
        outcome = ProofCacheOutcome.from_dict(outcome.to_dict())
        with self._lock:
            now = time.time()
            entry = _Entry(key, outcome, now, now)
            self._entries[key.digest] = entry
            self._entries.move_to_end(key.digest)
            self._trim_locked()
            self._persist_locked()
            self._stats["writes"] += 1
            return ProofCacheProvenance(
                key.digest,
                False,
                True,
                self.path is not None,
                trust=outcome.trust.value,
                entry_digest=entry.digest,
                created_at=now,
                reason="stored",
            )

    set = put
    store = put

    def get_or_compute(
        self,
        key: ProofCacheKey,
        producer: Callable[[], ProofCacheOutcome],
        *,
        require_trusted: bool = False,
    ) -> ProofCacheExecution:
        """Return cached work or run one producer for all concurrent callers."""

        initial = self.lookup(key, require_trusted=require_trusted)
        if initial.usable:
            return initial
        with self._lock:
            # Close the gap between the optimistic lookup above and joining a
            # flight: a fast producer may have completed in that interval.
            current = self.lookup(key, require_trusted=require_trusted)
            if current.usable:
                return current
            # A non-trusted hit cannot satisfy a trusted lookup; replace it with
            # one new flight rather than returning it as proof.
            flight = self._flights.get(key.digest)
            owner = flight is None
            if owner:
                flight = _Flight()
                self._flights[key.digest] = flight
            else:
                self._stats["single_flight_waits"] += 1
        assert flight is not None
        if not owner:
            flight.event.wait()
            if flight.error is not None:
                raise flight.error
            result = self.lookup(key, require_trusted=require_trusted)
            # A deliberately non-trusted result remains visible but unusable.
            provenance = ProofCacheProvenance(
                **{**result.provenance.to_dict(), "single_flight_shared": True}
            )
            return ProofCacheExecution(result.outcome or flight.outcome, provenance)
        try:
            outcome = producer()
            if not isinstance(outcome, ProofCacheOutcome):
                raise TypeError("proof cache producer must return ProofCacheOutcome")
            stored = self.put(key, outcome)
            flight.outcome = outcome
            return ProofCacheExecution(outcome, stored)
        except BaseException as exc:
            flight.error = exc
            raise
        finally:
            with self._lock:
                self._flights.pop(key.digest, None)
                flight.event.set()

    single_flight = get_or_compute
    execute = get_or_compute

    def invalidate_stale_toolchains(
        self,
        *,
        solver_identities: Any,
        lean_toolchain_identity: Any,
    ) -> int:
        """Delete entries not matching the currently resolved toolchains."""

        solver_digest = _identity_digest(solver_identities)
        lean_digest = _identity_digest(lean_toolchain_identity)
        with self._lock:
            stale = [
                digest for digest, entry in self._entries.items()
                if entry.key.solver_identities_digest != solver_digest
                or entry.key.lean_toolchain_identity_digest != lean_digest
            ]
            for digest in stale:
                del self._entries[digest]
            if stale:
                self._stats["invalidations"] += len(stale)
                self._persist_locked()
            return len(stale)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._persist_locked()

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                **self._stats,
                "entries": len(self._entries),
                "in_flight": len(self._flights),
            }

    def __len__(self) -> int:
        with self._lock:
            self._trim_locked()
            return len(self._entries)


ProofObligationCache = PersistentProofCache
PersistentProofObligationCache = PersistentProofCache
ProofCache = PersistentProofCache
ProofOutcome = ProofCacheOutcome


def cache_provenance_metadata(
    value: ProofCacheLookup | ProofCacheProvenance,
) -> Dict[str, Any]:
    """Return the stable receipt fragment for a cache result/provenance."""

    provenance = value.provenance if isinstance(value, ProofCacheLookup) else value
    return {"proof_cache": provenance.to_dict()}


__all__ = [
    "PROOF_CACHE_KEY_SCHEMA_VERSION",
    "PROOF_CACHE_OUTCOME_SCHEMA_VERSION",
    "PROOF_CACHE_SCHEMA_VERSION",
    "CacheLookupResult",
    "CachedProofOutcome",
    "PersistentProofCache",
    "PersistentProofObligationCache",
    "ProofCache",
    "ProofCacheError",
    "ProofCacheExecution",
    "ProofCacheKey",
    "ProofCacheLookup",
    "ProofCacheOutcome",
    "ProofCacheProvenance",
    "ProofCacheTrustError",
    "ProofObligationCache",
    "ProofObligationCacheKey",
    "ProofOutcome",
    "ProofTrust",
    "cache_provenance_metadata",
    "canonical_json",
    "canonicalize_obligation",
    "content_digest",
]
