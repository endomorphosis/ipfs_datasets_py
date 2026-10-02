"""Trust-aware, process-safe cache for formal-verification receipts.

This cache is deliberately not a trust root.  Every hit is reconstructed as a
typed :class:`ProofReceipt`, its assurance is derived again from immutable
evidence, and all semantic/execution bindings are checked against the cache
key.  Provider status text and claimed assurance are never used to admit an
entry.

DuckDB supplies the lock-aware transactional boundary needed by parallel
supervisors.  In addition to durable proof receipts, the database contains a
short-lived single-flight lease and outcome channel.  The latter lets threads
and processes share one active expensive computation without treating its
possibly non-authoritative result as a proof-cache hit.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Final, TypeVar

from ..task_sources.duckdb_state import (
    DuckDBConnection,
    DuckDBRow,
    initialize_duckdb_database,
    open_duckdb_connection,
    resolve_duckdb_path,
)
from .formal_verification_contracts import (
    AssuranceLevel,
    CodeProofObligation,
    ContractValidationError,
    EvidenceFreshness,
    EvidenceKind,
    ProofReceipt,
    ProofVerdict,
    ResourceBudget,
    bounded_rejection_reason,
    assurance_satisfies,
    canonical_json,
)
from .proof_attestation import (
    AttestationBackendPolicy,
    AttestationValidationError,
    AttestationVerification,
    PersistedAttestationRecord,
    build_persisted_attestation_record,
    reproduce_attestation_verification,
)


FORMAL_VERIFICATION_CACHE_SCHEMA: Final = (
    "ipfs_accelerate_py/agent-supervisor/formal-verification-cache-entry@1"
)
FORMAL_VERIFICATION_CACHE_KEY_SCHEMA: Final = (
    "ipfs_accelerate_py/agent-supervisor/formal-verification-cache-key@1"
)
FORMAL_VERIFICATION_DRAFT_CACHE_SCHEMA: Final = (
    "ipfs_accelerate_py/agent-supervisor/formal-verification-draft-cache-entry@1"
)
FORMAL_VERIFICATION_DRAFT_CACHE_KEY_SCHEMA: Final = (
    "ipfs_accelerate_py/agent-supervisor/formal-verification-draft-cache-key@1"
)
FORMAL_VERIFICATION_FLIGHT_SCHEMA: Final = (
    "ipfs_accelerate_py/agent-supervisor/formal-verification-flight@1"
)
FORMAL_VERIFICATION_ATTESTATION_SCHEMA: Final = (
    "ipfs_accelerate_py/agent-supervisor/formal-verification-attestation-entry@1"
)
FORMAL_VERIFICATION_ATTESTATION_CACHE_SCHEMA: Final = FORMAL_VERIFICATION_ATTESTATION_SCHEMA
DEFAULT_CACHE_TTL_SECONDS: Final = 24 * 60 * 60
DEFAULT_LEASE_SECONDS: Final = 5 * 60
DEFAULT_WAIT_TIMEOUT_SECONDS: Final = 10 * 60
DEFAULT_MAX_DRAFT_BYTES: Final = 1024 * 1024


class CacheLookupStatus(str, Enum):
    HIT = "hit"
    MISS = "miss"
    REJECTED = "rejected"


class CacheRejectionReason(str, Enum):
    """Stable reason codes suitable for audit records and metrics."""

    CACHE_MISS = "cache_miss"
    MALFORMED_ENTRY = "malformed_cache_entry"
    POISONED_ENTRY = "poisoned_cache_entry"
    STALE_ENTRY = "stale_cache_entry"
    PARTIAL_ENTRY = "partial_cache_entry"
    SOLVER_ONLY_ENTRY = "solver_only_cache_entry"
    SIMULATED_ATTESTATION = "simulated_attestation"
    INSUFFICIENT_ASSURANCE = "required_assurance_not_satisfied"
    FRESHNESS_NOT_SATISFIED = "freshness_requirement_not_satisfied"
    BINDING_MISMATCH = "cache_binding_mismatch"
    ATTESTATION_MISS = "attestation_cache_miss"
    ATTESTATION_MALFORMED = "malformed_attestation_entry"
    ATTESTATION_POISONED = "poisoned_attestation_entry"
    ATTESTATION_EXPIRED = "expired_attestation_entry"
    ATTESTATION_BINDING_MISMATCH = "attestation_binding_mismatch"
    ATTESTATION_REPLAY_REQUIRED = "attestation_reverification_required"
    ATTESTATION_VERIFICATION_FAILED = "attestation_reverification_failed"
    DRAFT_MISS = "draft_cache_miss"
    DRAFT_MALFORMED = "malformed_draft_cache_entry"
    DRAFT_POISONED = "poisoned_draft_cache_entry"
    DRAFT_STALE = "stale_draft_cache_entry"
    DRAFT_BINDING_MISMATCH = "draft_cache_binding_mismatch"
    DRAFT_TRUST_CLAIM = "untrusted_draft_claims_authority"
    DRAFT_TOO_LARGE = "draft_cache_entry_too_large"

    # Short compatibility spellings.
    MALFORMED = "malformed_cache_entry"
    POISONED = "poisoned_cache_entry"
    STALE = "stale_cache_entry"
    PARTIAL = "partial_cache_entry"
    SOLVER_ONLY = "solver_only_cache_entry"


class SingleFlightError(RuntimeError):
    """Base class for single-flight coordination failures."""


class SingleFlightTimeout(SingleFlightError, TimeoutError):
    """Raised when a follower cannot observe an outcome before its deadline."""


class SingleFlightExecutionError(SingleFlightError):
    """A leader failed while producing the shared outcome."""


def _json_value(value: Any, *, field_name: str) -> Any:
    """Round-trip a value through the proof contract's canonical JSON subset."""

    converter = getattr(value, "to_dict", None)
    if callable(converter):
        value = converter()
    try:
        return json.loads(canonical_json(value))
    except (TypeError, ValueError, ContractValidationError, json.JSONDecodeError) as exc:
        raise ValueError(f"{field_name} must contain canonical JSON values") from exc


def _identity_component(value: Any, *, field_name: str) -> Any:
    if value is None:
        raise ValueError(f"{field_name} is required")
    if isinstance(value, str):
        value = value.strip()
        if not value:
            raise ValueError(f"{field_name} must not be empty")
    return _json_value(value, field_name=field_name)


def _premises(value: Any) -> tuple[Any, ...]:
    if value is None:
        raise ValueError("premises is required (use an empty array when there are none)")
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ValueError("premises must be an array")
    normalized = [_json_value(item, field_name="premises") for item in value]

    def sort_key(item: Any) -> bytes:
        return canonical_json(item).encode("utf-8")

    return tuple(sorted(normalized, key=sort_key))


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _rfc3339_from_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _timestamp_ms(value: str) -> int:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return int(parsed.timestamp() * 1000)


@dataclass(frozen=True)
class ProofCacheKey:
    """Content-addressed identity of every input capable of changing a proof."""

    obligation: Any
    premises: tuple[Any, ...]
    translator: Any
    solver: Any
    kernel: Any
    toolchain: Any
    theorem_registry: Any
    policy: Any
    resource_budget: Any
    candidate_tree: Any

    def __post_init__(self) -> None:
        for name in (
            "obligation",
            "translator",
            "solver",
            "kernel",
            "toolchain",
            "theorem_registry",
            "policy",
            "resource_budget",
            "candidate_tree",
        ):
            object.__setattr__(
                self,
                name,
                _identity_component(getattr(self, name), field_name=name),
            )
        object.__setattr__(self, "premises", _premises(self.premises))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": FORMAL_VERIFICATION_CACHE_KEY_SCHEMA,
            "obligation": self.obligation,
            "premises": list(self.premises),
            "translator": self.translator,
            "solver": self.solver,
            "kernel": self.kernel,
            "toolchain": self.toolchain,
            "theorem_registry": self.theorem_registry,
            "policy": self.policy,
            "resource_budget": self.resource_budget,
            "candidate_tree": self.candidate_tree,
        }

    @property
    def key_id(self) -> str:
        return f"proof-cache-key:sha256:{_sha256(self.to_dict())}"

    @property
    def cache_key(self) -> str:
        return self.key_id

    @property
    def digest(self) -> str:
        return self.key_id

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProofCacheKey":
        if not isinstance(value, Mapping):
            raise ValueError("cache key must be an object")
        schema = value.get("schema_version")
        if schema not in (None, FORMAL_VERIFICATION_CACHE_KEY_SCHEMA):
            raise ValueError("unsupported formal-verification cache-key schema")
        return cls(
            obligation=value.get("obligation"),
            premises=tuple(value.get("premises") or ()),
            translator=value.get("translator"),
            solver=value.get("solver"),
            kernel=value.get("kernel"),
            toolchain=value.get("toolchain"),
            theorem_registry=value.get("theorem_registry"),
            policy=value.get("policy"),
            resource_budget=value.get("resource_budget"),
            candidate_tree=value.get("candidate_tree"),
        )


def build_proof_cache_key(
    *,
    obligation: Any,
    premises: Sequence[Any],
    translator: Any,
    solver: Any,
    kernel: Any,
    toolchain: Any,
    theorem_registry: Any,
    policy: Any,
    resource_budget: Any,
    candidate_tree: Any | None = None,
    candidate_tree_id: Any | None = None,
) -> ProofCacheKey:
    """Build a cache key while accepting the common ``*_tree_id`` spelling."""

    if candidate_tree is not None and candidate_tree_id is not None:
        if _json_value(candidate_tree, field_name="candidate_tree") != _json_value(
            candidate_tree_id, field_name="candidate_tree_id"
        ):
            raise ValueError("candidate_tree and candidate_tree_id disagree")
    tree = candidate_tree if candidate_tree is not None else candidate_tree_id
    key = ProofCacheKey(
        obligation=obligation,
        premises=tuple(premises),
        translator=translator,
        solver=solver,
        kernel=kernel,
        toolchain=toolchain,
        theorem_registry=theorem_registry,
        policy=policy,
        resource_budget=resource_budget,
        candidate_tree=tree,
    )
    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        record_ref = str(key.key_id or "proof-cache-key")
        mirror_work_record(
            catalog_kind="proof_cache",
            record_kind="formal_verification_cache_key",
            record_ref=record_ref,
            subject_kind="key_id",
            subject_ref=record_ref,
        )
    except Exception:
        pass
    return key


# Descriptive compatibility spelling.
make_proof_cache_key = build_proof_cache_key
FormalVerificationCacheKey = ProofCacheKey


@dataclass(frozen=True)
class DraftCacheKey:
    """Route-aware identity for an untrusted model draft.

    Draft reuse is safe only when every prompt-, compiler-, and policy-facing
    input is unchanged.  The model route and the concrete model version are
    intentionally independent fields: changing an alias to another route, or
    changing the model served by the same route, invalidates reuse.

    The fields are named ``*_digest`` because callers should pass compact
    content identities rather than source material.  They accept any
    canonical JSON identity so existing CID-based contracts remain usable.
    """

    goal_digest: Any
    repository_tree_digest: Any
    vocabulary_digest: Any
    compiler_digest: Any
    model_route_digest: Any
    model_version: Any
    assumptions_digest: Any
    bounds_digest: Any
    policy_digest: Any

    def __post_init__(self) -> None:
        for name in (
            "goal_digest",
            "repository_tree_digest",
            "vocabulary_digest",
            "compiler_digest",
            "model_route_digest",
            "model_version",
            "assumptions_digest",
            "bounds_digest",
            "policy_digest",
        ):
            object.__setattr__(
                self,
                name,
                _identity_component(getattr(self, name), field_name=name),
            )

    @property
    def tree_digest(self) -> Any:
        return self.repository_tree_digest

    @property
    def model_route(self) -> Any:
        return self.model_route_digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": FORMAL_VERIFICATION_DRAFT_CACHE_KEY_SCHEMA,
            "goal_digest": self.goal_digest,
            "repository_tree_digest": self.repository_tree_digest,
            "vocabulary_digest": self.vocabulary_digest,
            "compiler_digest": self.compiler_digest,
            "model_route_digest": self.model_route_digest,
            "model_version": self.model_version,
            "assumptions_digest": self.assumptions_digest,
            "bounds_digest": self.bounds_digest,
            "policy_digest": self.policy_digest,
        }

    @property
    def key_id(self) -> str:
        return f"proof-draft-cache-key:sha256:{_sha256(self.to_dict())}"

    @property
    def cache_key(self) -> str:
        return self.key_id

    @property
    def digest(self) -> str:
        return self.key_id

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DraftCacheKey":
        if not isinstance(value, Mapping):
            raise ValueError("draft cache key must be an object")
        schema = value.get("schema_version", value.get("schema"))
        if schema not in (None, FORMAL_VERIFICATION_DRAFT_CACHE_KEY_SCHEMA):
            raise ValueError("unsupported formal-verification draft cache-key schema")
        return cls(
            goal_digest=value.get("goal_digest", value.get("goal")),
            repository_tree_digest=value.get(
                "repository_tree_digest",
                value.get(
                    "tree_digest",
                    value.get("repository_tree_id", value.get("tree")),
                ),
            ),
            vocabulary_digest=value.get("vocabulary_digest", value.get("vocabulary")),
            compiler_digest=value.get("compiler_digest", value.get("compiler")),
            model_route_digest=value.get(
                "model_route_digest",
                value.get("route_digest", value.get("model_route")),
            ),
            model_version=value.get("model_version", value.get("model_route_version")),
            assumptions_digest=value.get("assumptions_digest", value.get("assumptions")),
            bounds_digest=value.get("bounds_digest", value.get("bounds")),
            policy_digest=value.get("policy_digest", value.get("policy")),
        )


def _one_identity(
    canonical_name: str,
    *values: Any,
) -> Any:
    supplied = [value for value in values if value is not None]
    if not supplied:
        return None
    canonical = canonical_json(_identity_component(supplied[0], field_name=canonical_name))
    for value in supplied[1:]:
        if canonical_json(_identity_component(value, field_name=canonical_name)) != canonical:
            raise ValueError(f"{canonical_name} aliases disagree")
    return supplied[0]


def build_draft_cache_key(
    *,
    goal_digest: Any = None,
    goal: Any = None,
    repository_tree_digest: Any = None,
    tree_digest: Any = None,
    repository_tree_id: Any = None,
    tree: Any = None,
    vocabulary_digest: Any = None,
    vocabulary: Any = None,
    compiler_digest: Any = None,
    compiler: Any = None,
    model_route_digest: Any = None,
    route_digest: Any = None,
    model_route: Any = None,
    model_version: Any = None,
    model_route_version: Any = None,
    assumptions_digest: Any = None,
    assumptions: Any = None,
    bounds_digest: Any = None,
    bounds: Any = None,
    policy_digest: Any = None,
    policy: Any = None,
) -> DraftCacheKey:
    """Build a complete route-aware draft key with common identity aliases."""

    key = DraftCacheKey(
        goal_digest=_one_identity("goal_digest", goal_digest, goal),
        repository_tree_digest=_one_identity(
            "repository_tree_digest",
            repository_tree_digest,
            tree_digest,
            repository_tree_id,
            tree,
        ),
        vocabulary_digest=_one_identity("vocabulary_digest", vocabulary_digest, vocabulary),
        compiler_digest=_one_identity("compiler_digest", compiler_digest, compiler),
        model_route_digest=_one_identity(
            "model_route_digest",
            model_route_digest,
            route_digest,
            model_route,
        ),
        model_version=_one_identity("model_version", model_version, model_route_version),
        assumptions_digest=_one_identity("assumptions_digest", assumptions_digest, assumptions),
        bounds_digest=_one_identity("bounds_digest", bounds_digest, bounds),
        policy_digest=_one_identity("policy_digest", policy_digest, policy),
    )
    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        record_ref = str(key.key_id or "draft-cache-key")
        mirror_work_record(
            catalog_kind="proof_cache",
            record_kind="formal_verification_draft_cache_key",
            record_ref=record_ref,
            subject_kind="key_id",
            subject_ref=record_ref,
        )
    except Exception:
        pass
    return key


make_draft_cache_key = build_draft_cache_key
FormalVerificationDraftCacheKey = DraftCacheKey
ProofDraftCacheKey = DraftCacheKey


@dataclass(frozen=True)
class CacheRequirements:
    required_assurance: AssuranceLevel = AssuranceLevel.KERNEL_VERIFIED
    required_freshness: EvidenceFreshness = EvidenceFreshness.CURRENT
    max_age_seconds: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "required_assurance", AssuranceLevel(self.required_assurance))
        object.__setattr__(self, "required_freshness", EvidenceFreshness(self.required_freshness))
        if self.max_age_seconds is not None and (
            isinstance(self.max_age_seconds, bool)
            or not isinstance(self.max_age_seconds, int)
            or self.max_age_seconds < 0
        ):
            raise ValueError("max_age_seconds must be a nonnegative integer or None")


@dataclass(frozen=True)
class ProofCacheEntry:
    key: ProofCacheKey
    receipt: ProofReceipt
    created_at_ms: int
    expires_at_ms: int
    complete: bool = True
    entry_digest: str = ""

    def _unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema_version": FORMAL_VERIFICATION_CACHE_SCHEMA,
            "key_id": self.key.key_id,
            "key": self.key.to_dict(),
            "receipt_id": self.receipt.receipt_id,
            "receipt": self.receipt.to_dict(),
            "created_at_ms": self.created_at_ms,
            "expires_at_ms": self.expires_at_ms,
            "complete": self.complete,
        }

    @property
    def computed_digest(self) -> str:
        return f"sha256:{_sha256(self._unsigned_dict())}"

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._unsigned_dict(),
            "entry_digest": self.entry_digest or self.computed_digest,
        }

    @classmethod
    def create(
        cls,
        key: ProofCacheKey,
        receipt: ProofReceipt,
        *,
        created_at_ms: int,
        expires_at_ms: int,
        complete: bool = True,
    ) -> "ProofCacheEntry":
        entry = cls(
            key=key,
            receipt=receipt,
            created_at_ms=created_at_ms,
            expires_at_ms=expires_at_ms,
            complete=complete,
        )
        return cls(**{**entry.__dict__, "entry_digest": entry.computed_digest})


_DRAFT_BOOLEAN_TRUST_CLAIMS: Final = frozenset(
    {
        "admission_claimed",
        "admitted",
        "authoritative",
        "can_mark_complete",
        "can_satisfy_completion",
        "complete",
        "completion_evidence",
        "implementation_conformant",
        "kernel_checked",
        "proof_success",
        "trusted",
        "verified",
    }
)
_DRAFT_ASSURANCE_CLAIMS: Final = frozenset(
    {
        "assurance",
        "assurance_level",
        "authority",
        "trust",
        "trust_level",
        "verdict",
    }
)
_UNTRUSTED_CLAIM_VALUES: Final = frozenset(
    {
        "",
        "candidate",
        "draft",
        "inconclusive",
        "none",
        "not_proved",
        "proposed",
        "unknown",
        "untrusted",
        "unverified",
    }
)


def _draft_claims_authority(value: Any) -> bool:
    """Fail closed when any nested draft data claims proof authority."""

    if isinstance(value, Mapping):
        for raw_name, item in value.items():
            name = str(raw_name).strip().casefold().replace("-", "_")
            if name in _DRAFT_BOOLEAN_TRUST_CLAIMS and item not in (
                False,
                None,
                0,
                "",
            ):
                return True
            if name in _DRAFT_ASSURANCE_CLAIMS:
                normalized = (
                    str(getattr(item, "value", item) or "").strip().casefold().replace("-", "_")
                )
                if normalized not in _UNTRUSTED_CLAIM_VALUES:
                    return True
            if _draft_claims_authority(item):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_draft_claims_authority(item) for item in value)
    return False


def _coerce_untrusted_draft(value: Any) -> dict[str, Any]:
    """Create an immutable JSON projection without accepting trust claims."""

    if isinstance(value, ProofReceipt):
        raise ValueError("proof receipts cannot be stored in the draft cache")
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        value = converter()
    if not isinstance(value, Mapping):
        raise ValueError("untrusted draft must be an object")
    normalized = _json_value(value, field_name="untrusted draft")
    if not isinstance(normalized, dict):
        raise ValueError("untrusted draft must be an object")
    if _draft_claims_authority(normalized):
        raise PermissionError("untrusted draft claims proof authority")
    return normalized


def _nested_identity_values(value: Any, names: frozenset[str]) -> tuple[Any, ...]:
    result: list[Any] = []
    if isinstance(value, Mapping):
        for raw_name, item in value.items():
            name = str(raw_name).strip().casefold().replace("-", "_")
            if name in names:
                result.append(item)
            result.extend(_nested_identity_values(item, names))
    elif isinstance(value, (list, tuple)):
        for item in value:
            result.extend(_nested_identity_values(item, names))
    return tuple(result)


def _identity_matches(expected: Any, candidate: Any) -> bool:
    try:
        if canonical_json(expected) == canonical_json(candidate):
            return True
        candidate_digest = _sha256(candidate)
        if isinstance(expected, str):
            normalized = expected.strip().casefold()
            return normalized in {
                candidate_digest,
                f"sha256:{candidate_digest}",
            }
    except (TypeError, ValueError, ContractValidationError):
        return False
    return False


_DRAFT_BINDING_FIELDS: Final = (
    ("goal_digest", frozenset({"goal_digest", "root_goal_content_id"})),
    (
        "repository_tree_digest",
        frozenset(
            {
                "repository_tree_digest",
                "repository_tree_id",
                "candidate_tree_id",
            }
        ),
    ),
    ("vocabulary_digest", frozenset({"vocabulary_digest"})),
    (
        "compiler_digest",
        frozenset({"compiler_digest", "compiler_identity"}),
    ),
    (
        "model_route_digest",
        frozenset({"model_route_digest", "route_digest"}),
    ),
    ("model_version", frozenset({"model_version", "model"})),
    ("assumptions_digest", frozenset({"assumptions_digest"})),
    ("bounds_digest", frozenset({"bounds_digest", "validation_bounds_digest"})),
    ("policy_digest", frozenset({"policy_digest"})),
)


def _draft_binding_mismatch(key: DraftCacheKey, draft: Mapping[str, Any]) -> bool:
    """Check every explicit context identity carried by a draft."""

    for key_field, draft_fields in _DRAFT_BINDING_FIELDS:
        expected = getattr(key, key_field)
        candidates = _nested_identity_values(draft, draft_fields)
        if any(not _identity_matches(expected, candidate) for candidate in candidates):
            return True
    return False


@dataclass(frozen=True)
class UntrustedDraftCacheEntry:
    """Integrity-protected draft data which can never be proof evidence."""

    key: DraftCacheKey
    draft: Mapping[str, Any]
    created_at_ms: int
    expires_at_ms: int
    trust: str = "untrusted"
    entry_digest: str = ""

    def __post_init__(self) -> None:
        if self.trust != "untrusted":
            raise ValueError("draft cache entries must be explicitly untrusted")
        object.__setattr__(self, "draft", _coerce_untrusted_draft(self.draft))

    def _unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema_version": FORMAL_VERIFICATION_DRAFT_CACHE_SCHEMA,
            "key_id": self.key.key_id,
            "key": self.key.to_dict(),
            "draft": dict(self.draft),
            "created_at_ms": self.created_at_ms,
            "expires_at_ms": self.expires_at_ms,
            "trust": "untrusted",
            "authoritative": False,
            "completion_evidence": False,
        }

    @property
    def computed_digest(self) -> str:
        return f"sha256:{_sha256(self._unsigned_dict())}"

    @property
    def draft_id(self) -> str:
        candidate = self.draft.get("draft_id", self.draft.get("artifact_id"))
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
        return f"untrusted-draft:sha256:{_sha256(self.draft)}"

    @property
    def authoritative(self) -> bool:
        return False

    @property
    def completion_evidence(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._unsigned_dict(),
            "entry_digest": self.entry_digest or self.computed_digest,
        }

    @classmethod
    def create(
        cls,
        key: DraftCacheKey,
        draft: Mapping[str, Any],
        *,
        created_at_ms: int,
        expires_at_ms: int,
    ) -> "UntrustedDraftCacheEntry":
        entry = cls(
            key=key,
            draft=draft,
            created_at_ms=created_at_ms,
            expires_at_ms=expires_at_ms,
        )
        return cls(**{**entry.__dict__, "entry_digest": entry.computed_digest})


# Short spelling used by callers whose cache namespace is already explicit.
DraftCacheEntry = UntrustedDraftCacheEntry


@dataclass(frozen=True)
class DraftCacheLookupResult:
    status: CacheLookupStatus
    key: DraftCacheKey
    entry: UntrustedDraftCacheEntry | None = None
    reason_codes: tuple[str, ...] = ()

    @property
    def hit(self) -> bool:
        return self.status is CacheLookupStatus.HIT

    @property
    def draft(self) -> Mapping[str, Any] | None:
        return self.entry.draft if self.entry is not None and self.hit else None

    @property
    def authoritative(self) -> bool:
        return False

    @property
    def completion_evidence(self) -> bool:
        return False

    @property
    def reason_code(self) -> str:
        return self.reason_codes[0] if self.reason_codes else ""


@dataclass(frozen=True)
class DraftCacheStoreResult:
    stored: bool
    key: DraftCacheKey
    entry: UntrustedDraftCacheEntry | None = None
    reason_codes: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.stored

    @property
    def reason_code(self) -> str:
        return self.reason_codes[0] if self.reason_codes else ""


@dataclass(frozen=True)
class AttestationCacheEntry:
    """Integrity-checked sidecar stored independently from a proof receipt."""

    key: ProofCacheKey
    record: PersistedAttestationRecord
    stored_at_ms: int
    expires_at_ms: int
    ipfs_cid: str = ""
    entry_digest: str = ""

    def _unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema_version": FORMAL_VERIFICATION_ATTESTATION_SCHEMA,
            "key_id": self.key.key_id,
            "proof_receipt_id": self.record.proof_receipt_id,
            "record_id": self.record.record_id,
            "record": self.record.to_public_artifact(),
            "stored_at_ms": self.stored_at_ms,
            "expires_at_ms": self.expires_at_ms,
            "ipfs_cid": self.ipfs_cid,
        }

    @property
    def computed_digest(self) -> str:
        return f"sha256:{_sha256(self._unsigned_dict())}"

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._unsigned_dict(),
            "entry_digest": self.entry_digest or self.computed_digest,
        }

    @classmethod
    def create(
        cls,
        key: ProofCacheKey,
        record: PersistedAttestationRecord,
        *,
        stored_at_ms: int,
        expires_at_ms: int,
        ipfs_cid: str = "",
    ) -> "AttestationCacheEntry":
        entry = cls(
            key=key,
            record=record,
            stored_at_ms=stored_at_ms,
            expires_at_ms=expires_at_ms,
            ipfs_cid=ipfs_cid.strip(),
        )
        return cls(**{**entry.__dict__, "entry_digest": entry.computed_digest})


@dataclass(frozen=True)
class CacheLookupResult:
    status: CacheLookupStatus
    key: ProofCacheKey
    entry: ProofCacheEntry | None = None
    reason_codes: tuple[str, ...] = ()
    attestation_entry: AttestationCacheEntry | None = None
    attestation_reproduced: bool = False

    @property
    def hit(self) -> bool:
        return self.status is CacheLookupStatus.HIT

    @property
    def receipt(self) -> ProofReceipt | None:
        return self.entry.receipt if self.entry is not None and self.hit else None

    @property
    def kernel_receipt(self) -> ProofReceipt | None:
        """Return the immutable base receipt even when ATTESTED was requested."""

        return self.entry.receipt if self.entry is not None else None

    @property
    def attestation(self) -> PersistedAttestationRecord | None:
        return self.attestation_entry.record if self.attestation_entry is not None else None

    @property
    def verification(self) -> AttestationVerification | None:
        return self.attestation.verification if self.attestation is not None else None

    @property
    def kernel_assurance(self) -> AssuranceLevel:
        if self.kernel_receipt is None:
            return AssuranceLevel.UNVERIFIED
        return self.kernel_receipt.authoritative_assurance

    @property
    def authoritative_assurance(self) -> AssuranceLevel:
        if self.attestation_entry is not None and self.attestation_reproduced:
            return AssuranceLevel.ATTESTED
        return self.kernel_assurance

    effective_assurance = authoritative_assurance

    @property
    def reason_code(self) -> str:
        return self.reason_codes[0] if self.reason_codes else ""

    @property
    def actionable_reason(self) -> str:
        return bounded_rejection_reason(self.reason_code) if self.reason_code else ""


@dataclass(frozen=True)
class CacheStoreResult:
    stored: bool
    key: ProofCacheKey
    entry: ProofCacheEntry | None = None
    reason_codes: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.stored

    @property
    def reason_code(self) -> str:
        return self.reason_codes[0] if self.reason_codes else ""

    @property
    def actionable_reason(self) -> str:
        return bounded_rejection_reason(self.reason_code) if self.reason_code else ""


@dataclass(frozen=True)
class AttestationCacheLookupResult:
    status: CacheLookupStatus
    key: ProofCacheKey
    receipt: ProofReceipt | None = None
    entry: AttestationCacheEntry | None = None
    reason_codes: tuple[str, ...] = ()
    reproduced: bool = False

    @property
    def hit(self) -> bool:
        return self.status is CacheLookupStatus.HIT

    @property
    def record(self) -> PersistedAttestationRecord | None:
        return self.entry.record if self.entry is not None and self.hit else None

    @property
    def verification(self) -> AttestationVerification | None:
        return self.record.verification if self.record is not None else None

    @property
    def kernel_assurance(self) -> AssuranceLevel:
        if self.receipt is None:
            return AssuranceLevel.UNVERIFIED
        return self.receipt.authoritative_assurance

    @property
    def authoritative_assurance(self) -> AssuranceLevel:
        return AssuranceLevel.ATTESTED if self.hit and self.reproduced else self.kernel_assurance

    effective_assurance = authoritative_assurance

    @property
    def reason_code(self) -> str:
        return self.reason_codes[0] if self.reason_codes else ""

    @property
    def actionable_reason(self) -> str:
        return bounded_rejection_reason(self.reason_code) if self.reason_code else ""


@dataclass(frozen=True)
class AttestationCacheStoreResult:
    stored: bool
    key: ProofCacheKey
    entry: AttestationCacheEntry | None = None
    reason_codes: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.stored

    @property
    def reason_code(self) -> str:
        return self.reason_codes[0] if self.reason_codes else ""

    @property
    def actionable_reason(self) -> str:
        return bounded_rejection_reason(self.reason_code) if self.reason_code else ""


@dataclass(frozen=True)
class SingleFlightLease:
    """A fenced lease returned for both leaders and followers."""

    cache: "FormalVerificationCache" = field(repr=False, compare=False)
    key: ProofCacheKey | DraftCacheKey
    owner_id: str
    token: str
    fencing_token: int
    acquired_at_ms: int
    expires_at_ms: int
    acquired: bool

    @property
    def is_leader(self) -> bool:
        return self.acquired

    def renew(self, *, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> "SingleFlightLease":
        return self.cache.renew_lease(self, lease_seconds=lease_seconds)

    def release(self) -> bool:
        return self.cache.release_lease(self)

    def __enter__(self) -> "SingleFlightLease":
        if not self.acquired:
            raise SingleFlightError("cannot enter a single-flight lease not owned by caller")
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.release()


def _strict_json_loads(value: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in items:
            if key in result:
                raise ValueError(f"duplicate JSON field {key!r}")
            result[key] = item
        return result

    return json.loads(value, object_pairs_hook=pairs)


_PRIVATE_FLIGHT_FIELDS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "credential",
        "hidden_witness",
        "password",
        "private_key",
        "private_witness",
        "refresh_token",
        "secret",
        "session_token",
        "witness",
    }
)


def _contains_private_flight_material(value: Any) -> bool:
    """Inspect field names only; never inspect or reflect secret values."""

    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key).strip().lower().replace("-", "_")
            if any(
                key == marker or key.endswith("_" + marker) or marker in key
                for marker in _PRIVATE_FLIGHT_FIELDS
            ):
                return True
            if _contains_private_flight_material(item):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_contains_private_flight_material(item) for item in value)
    return False


def _single_flight_public_value(value: Any) -> Any:
    normalized = _json_value(value, field_name="single-flight outcome")
    if _contains_private_flight_material(normalized):
        raise ValueError(bounded_rejection_reason("private_material"))
    return normalized


def _component_identifier(value: Any, *names: str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        for name in names:
            candidate = value.get(name)
            if isinstance(candidate, str) and candidate:
                return candidate
    return ""


def _obligation_identifier(value: Any) -> str:
    direct = _component_identifier(value, "obligation_id", "content_id", "id")
    if direct:
        return direct
    if isinstance(value, Mapping):
        try:
            return CodeProofObligation.from_dict(value).obligation_id
        except (TypeError, ValueError, ContractValidationError):
            return ""
    return ""


def _premise_identifiers(values: Sequence[Any]) -> tuple[str, ...]:
    identifiers = []
    for value in values:
        identifier = _component_identifier(value, "premise_id", "content_id", "id")
        if not identifier and isinstance(value, str):
            identifier = value
        if identifier:
            identifiers.append(identifier)
    return tuple(sorted(set(identifiers)))


def _binding_reasons(key: ProofCacheKey, receipt: ProofReceipt) -> set[str]:
    reasons: set[str] = set()

    expected_obligation = _obligation_identifier(key.obligation)
    if not expected_obligation or expected_obligation != receipt.obligation_id:
        reasons.add(CacheRejectionReason.BINDING_MISMATCH.value)

    expected_premises = _premise_identifiers(key.premises)
    if len(expected_premises) != len(key.premises) or expected_premises != tuple(
        sorted(receipt.premise_ids)
    ):
        reasons.add(CacheRejectionReason.BINDING_MISMATCH.value)

    bindings = (
        (key.translator, receipt.translator_id, ("translator_id", "id")),
        (key.kernel, receipt.kernel_id, ("kernel_id", "id")),
        (key.toolchain, receipt.toolchain_id, ("toolchain_id", "id")),
        (
            key.theorem_registry,
            receipt.theorem_registry_id,
            ("theorem_registry_id", "registry_id", "id"),
        ),
        (key.policy, receipt.policy_id, ("policy_id", "id")),
        (
            key.candidate_tree,
            receipt.repository_tree_id,
            ("candidate_tree_id", "repository_tree_id", "tree_id", "id"),
        ),
    )
    for component, actual, names in bindings:
        expected = _component_identifier(component, *names)
        if not expected or expected != actual:
            reasons.add(CacheRejectionReason.BINDING_MISMATCH.value)

    solver_ids: tuple[str, ...] = ()
    if isinstance(key.solver, Mapping):
        raw_ids = key.solver.get("solver_ids") or key.solver.get("allowed_solvers")
        if isinstance(raw_ids, Sequence) and not isinstance(raw_ids, str):
            solver_ids = tuple(str(item) for item in raw_ids)
    expected_solver = _component_identifier(key.solver, "solver_id", "id")
    if expected_solver and expected_solver != receipt.solver_id:
        reasons.add(CacheRejectionReason.BINDING_MISMATCH.value)
    elif solver_ids and receipt.solver_id not in solver_ids:
        reasons.add(CacheRejectionReason.BINDING_MISMATCH.value)
    elif not expected_solver and not solver_ids:
        reasons.add(CacheRejectionReason.BINDING_MISMATCH.value)

    try:
        expected_budget = ResourceBudget.from_dict(key.resource_budget).to_dict()
    except (TypeError, ValueError, ContractValidationError):
        expected_budget = key.resource_budget
    if expected_budget != receipt.resource_budget.to_dict():
        reasons.add(CacheRejectionReason.BINDING_MISMATCH.value)
    return reasons


def _trust_reasons(
    key: ProofCacheKey,
    receipt: ProofReceipt,
    *,
    complete: bool,
    requirements: CacheRequirements,
) -> set[str]:
    reasons = _binding_reasons(key, receipt)
    if not complete or receipt.verdict is not ProofVerdict.PROVED:
        reasons.add(CacheRejectionReason.PARTIAL_ENTRY.value)
    if receipt.metadata.get("partial") is True:
        reasons.add(CacheRejectionReason.PARTIAL_ENTRY.value)

    simulated_attestation = any(
        evidence.kind is EvidenceKind.CRYPTOGRAPHIC_ATTESTATION and evidence.simulated
        for evidence in receipt.evidence
    )
    if simulated_attestation:
        reasons.add(CacheRejectionReason.SIMULATED_ATTESTATION.value)

    actual = receipt.authoritative_assurance
    if actual.rank <= AssuranceLevel.SOLVER_CHECKED.rank:
        reasons.add(CacheRejectionReason.SOLVER_ONLY_ENTRY.value)
    if not assurance_satisfies(actual, requirements.required_assurance):
        reasons.add(CacheRejectionReason.INSUFFICIENT_ASSURANCE.value)
    if (
        requirements.required_freshness is EvidenceFreshness.CURRENT
        and receipt.freshness is not EvidenceFreshness.CURRENT
    ):
        reasons.add(CacheRejectionReason.FRESHNESS_NOT_SATISFIED.value)
    return reasons


T = TypeVar("T")


class FormalVerificationCache:
    """Durable receipt cache and cross-process single-flight coordinator.

    ``exact_path`` selects an explicit native file without account relocation or
    legacy migration. It is intended for independently bound owner locations and
    isolated runs whose storage must stay within their admitted disk roots.
    Selecting a path confers no proof or execution authority.
    """

    def __init__(
        self,
        path: str | os.PathLike[str] | None = None,
        *,
        default_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
        default_draft_ttl_seconds: int | None = None,
        max_draft_bytes: int = DEFAULT_MAX_DRAFT_BYTES,
        clock: Callable[[], float] = time.time,
        duckdb_timeout_seconds: int = 30,
        sqlite_timeout_seconds: int | None = None,
        attestation_verifier: Callable[[Any], bool] | None = None,
        exact_path: bool = False,
    ) -> None:
        if isinstance(default_ttl_seconds, bool) or default_ttl_seconds <= 0:
            raise ValueError("default_ttl_seconds must be a positive integer")
        if default_draft_ttl_seconds is not None and (
            isinstance(default_draft_ttl_seconds, bool)
            or not isinstance(default_draft_ttl_seconds, int)
            or default_draft_ttl_seconds <= 0
        ):
            raise ValueError("default_draft_ttl_seconds must be a positive integer or None")
        if (
            isinstance(max_draft_bytes, bool)
            or not isinstance(max_draft_bytes, int)
            or max_draft_bytes <= 0
        ):
            raise ValueError("max_draft_bytes must be a positive integer")
        timeout_seconds = (
            sqlite_timeout_seconds if sqlite_timeout_seconds is not None else duckdb_timeout_seconds
        )
        if timeout_seconds <= 0:
            raise ValueError("duckdb_timeout_seconds must be positive")
        if type(exact_path) is not bool:
            raise ValueError("exact_path must be a boolean")
        if exact_path:
            if path is None:
                raise ValueError("exact_path requires a canonical absolute .duckdb file")
            supplied = Path(path)
            if (not supplied.is_absolute() or supplied.suffix != ".duckdb"
                    or str(supplied) != os.fspath(path)
                    or supplied.resolve(strict=False) != supplied
                    or any(part.is_symlink() for part in (supplied, *supplied.parents))
                    or (supplied.exists() and not supplied.is_file())):
                raise ValueError("exact_path requires a canonical absolute .duckdb file")
            self.path, self._legacy_path = supplied, None
        else:
            self.path, self._legacy_path = resolve_duckdb_path(
                path,
                default_filename="formal_verification_cache.duckdb",
                temporary_prefix="formal-verification-cache-",
            )
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.default_ttl_seconds = int(default_ttl_seconds)
        self.default_draft_ttl_seconds = int(
            default_ttl_seconds if default_draft_ttl_seconds is None else default_draft_ttl_seconds
        )
        self.max_draft_bytes = int(max_draft_bytes)
        self._clock = clock
        self._attestation_verifier = attestation_verifier
        self._duckdb_timeout_seconds = int(timeout_seconds)
        self._schema_lock = threading.Lock()
        self._initialize()

    @property
    def db_path(self) -> Path:
        return self.path

    def _now_ms(self) -> int:
        return int(self._clock() * 1000)

    def _connect(self) -> DuckDBConnection:
        return open_duckdb_connection(
            self.path,
            timeout_seconds=self._duckdb_timeout_seconds,
        )

    def _initialize(self) -> None:
        with self._schema_lock:
            initialize_duckdb_database(
                self.path,
                legacy_sqlite_path=self._legacy_path,
                timeout_seconds=self._duckdb_timeout_seconds,
                table_names=(
                    "proof_cache_entries",
                    "proof_draft_cache_entries",
                    "proof_attestation_entries",
                    "proof_single_flights",
                    "proof_flight_outcomes",
                ),
                schema_sql="""
                    CREATE TABLE IF NOT EXISTS proof_cache_entries (
                        key_id TEXT PRIMARY KEY,
                        key_json TEXT NOT NULL,
                        entry_json TEXT NOT NULL,
                        created_at_ms BIGINT NOT NULL,
                        expires_at_ms BIGINT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS proof_cache_expiry_idx
                        ON proof_cache_entries(expires_at_ms);
                    CREATE TABLE IF NOT EXISTS proof_draft_cache_entries (
                        key_id TEXT PRIMARY KEY,
                        key_json TEXT NOT NULL,
                        entry_json TEXT NOT NULL,
                        created_at_ms BIGINT NOT NULL,
                        expires_at_ms BIGINT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS proof_draft_cache_expiry_idx
                        ON proof_draft_cache_entries(expires_at_ms);
                    CREATE TABLE IF NOT EXISTS proof_attestation_entries (
                        key_id TEXT PRIMARY KEY,
                        proof_receipt_id TEXT NOT NULL,
                        record_id TEXT NOT NULL UNIQUE,
                        envelope_id TEXT NOT NULL,
                        public_input_digest TEXT NOT NULL,
                        backend_policy_id TEXT NOT NULL,
                        backend_id TEXT NOT NULL,
                        circuit_id TEXT NOT NULL,
                        verification_key_id TEXT NOT NULL,
                        formal_policy_id TEXT NOT NULL,
                        entry_json TEXT NOT NULL,
                        stored_at_ms BIGINT NOT NULL,
                        expires_at_ms BIGINT NOT NULL,
                        ipfs_cid TEXT NOT NULL DEFAULT ''
                    );
                    CREATE INDEX IF NOT EXISTS proof_attestation_receipt_idx
                        ON proof_attestation_entries(proof_receipt_id);
                    CREATE INDEX IF NOT EXISTS proof_attestation_expiry_idx
                        ON proof_attestation_entries(expires_at_ms);
                    CREATE TABLE IF NOT EXISTS proof_single_flights (
                        key_id TEXT PRIMARY KEY,
                        owner_id TEXT NOT NULL,
                        token TEXT NOT NULL,
                        fencing_token BIGINT NOT NULL,
                        acquired_at_ms BIGINT NOT NULL,
                        expires_at_ms BIGINT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS proof_flight_expiry_idx
                        ON proof_single_flights(expires_at_ms);
                    CREATE TABLE IF NOT EXISTS proof_flight_outcomes (
                        key_id TEXT PRIMARY KEY,
                        fencing_token BIGINT NOT NULL,
                        status TEXT NOT NULL,
                        outcome_json TEXT NOT NULL,
                        outcome_digest TEXT NOT NULL,
                        created_at_ms BIGINT NOT NULL,
                        expires_at_ms BIGINT NOT NULL
                    );
                    """,
            )

    def _coerce_key(self, key: ProofCacheKey | Mapping[str, Any]) -> ProofCacheKey:
        return key if isinstance(key, ProofCacheKey) else ProofCacheKey.from_dict(key)

    def _coerce_draft_key(self, key: DraftCacheKey | Mapping[str, Any]) -> DraftCacheKey:
        return key if isinstance(key, DraftCacheKey) else DraftCacheKey.from_dict(key)

    def _coerce_coordination_key(
        self,
        key: ProofCacheKey | DraftCacheKey | Mapping[str, Any],
    ) -> ProofCacheKey | DraftCacheKey:
        if isinstance(key, (ProofCacheKey, DraftCacheKey)):
            return key
        if not isinstance(key, Mapping):
            raise ValueError("single-flight key must be a cache key or object")
        schema = key.get("schema_version", key.get("schema"))
        if (
            schema == FORMAL_VERIFICATION_DRAFT_CACHE_KEY_SCHEMA
            or "goal_digest" in key
            or "model_route_digest" in key
        ):
            return DraftCacheKey.from_dict(key)
        return ProofCacheKey.from_dict(key)

    def put_draft(
        self,
        key: DraftCacheKey | Mapping[str, Any],
        draft: Any,
        *,
        ttl_seconds: int | None = None,
    ) -> DraftCacheStoreResult:
        """Atomically persist a bounded, explicitly untrusted model draft.

        Drafts use their own table, schema, key prefix, and API.  Supplying a
        :class:`ProofReceipt` or any nested proof/authority/completion claim
        fails closed; this method can never populate ``proof_cache_entries``.
        """

        cache_key = self._coerce_draft_key(key)
        try:
            normalized = _coerce_untrusted_draft(draft)
        except PermissionError:
            return DraftCacheStoreResult(
                False,
                cache_key,
                reason_codes=(CacheRejectionReason.DRAFT_TRUST_CLAIM.value,),
            )
        except (TypeError, ValueError, ContractValidationError):
            return DraftCacheStoreResult(
                False,
                cache_key,
                reason_codes=(CacheRejectionReason.DRAFT_MALFORMED.value,),
            )
        if _draft_binding_mismatch(cache_key, normalized):
            return DraftCacheStoreResult(
                False,
                cache_key,
                reason_codes=(CacheRejectionReason.DRAFT_BINDING_MISMATCH.value,),
            )
        encoded_draft = canonical_json(normalized).encode("utf-8")
        if len(encoded_draft) > self.max_draft_bytes:
            return DraftCacheStoreResult(
                False,
                cache_key,
                reason_codes=(CacheRejectionReason.DRAFT_TOO_LARGE.value,),
            )
        ttl = self.default_draft_ttl_seconds if ttl_seconds is None else ttl_seconds
        if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl <= 0:
            raise ValueError("ttl_seconds must be a positive integer")
        now = self._now_ms()
        entry = UntrustedDraftCacheEntry.create(
            cache_key,
            normalized,
            created_at_ms=now,
            expires_at_ms=now + ttl * 1000,
        )
        key_json = canonical_json(cache_key.to_dict())
        entry_json = canonical_json(entry.to_dict())
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO proof_draft_cache_entries(
                    key_id, key_json, entry_json, created_at_ms, expires_at_ms
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key_id) DO UPDATE SET
                    key_json=excluded.key_json,
                    entry_json=excluded.entry_json,
                    created_at_ms=excluded.created_at_ms,
                    expires_at_ms=excluded.expires_at_ms
                """,
                (
                    cache_key.key_id,
                    key_json,
                    entry_json,
                    entry.created_at_ms,
                    entry.expires_at_ms,
                ),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        return DraftCacheStoreResult(True, cache_key, entry=entry)

    store_draft = put_draft

    def _decode_draft_entry(
        self,
        key: DraftCacheKey,
        row: DuckDBRow,
    ) -> tuple[UntrustedDraftCacheEntry | None, tuple[str, ...]]:
        try:
            stored_key_payload = _strict_json_loads(str(row["key_json"]))
            stored_payload = _strict_json_loads(str(row["entry_json"]))
            if not isinstance(stored_key_payload, Mapping) or not isinstance(
                stored_payload, Mapping
            ):
                raise ValueError("draft entry envelope must contain objects")
            stored_key = DraftCacheKey.from_dict(stored_key_payload)
            draft_payload = stored_payload.get("draft")
            if not isinstance(draft_payload, Mapping):
                raise ValueError("draft entry must contain an object")
            if stored_payload.get("trust") != "untrusted":
                raise PermissionError("draft entry changed trust")
            if stored_payload.get("authoritative") is not False:
                raise PermissionError("draft entry claims authority")
            if stored_payload.get("completion_evidence") is not False:
                raise PermissionError("draft entry claims completion evidence")
            entry = UntrustedDraftCacheEntry(
                key=stored_key,
                draft=draft_payload,
                created_at_ms=int(stored_payload["created_at_ms"]),
                expires_at_ms=int(stored_payload["expires_at_ms"]),
                trust=str(stored_payload["trust"]),
                entry_digest=str(stored_payload["entry_digest"]),
            )
        except PermissionError:
            return None, (CacheRejectionReason.DRAFT_TRUST_CLAIM.value,)
        except (
            KeyError,
            TypeError,
            ValueError,
            ContractValidationError,
            json.JSONDecodeError,
        ):
            return None, (CacheRejectionReason.DRAFT_MALFORMED.value,)
        poisoned = (
            stored_key.key_id != key.key_id
            or canonical_json(stored_key.to_dict()) != canonical_json(key.to_dict())
            or str(stored_payload.get("key_id")) != key.key_id
            or entry.entry_digest != entry.computed_digest
            or str(row["key_id"]) != key.key_id
            or int(row["created_at_ms"]) != entry.created_at_ms
            or int(row["expires_at_ms"]) != entry.expires_at_ms
        )
        if _draft_binding_mismatch(key, entry.draft):
            return None, (CacheRejectionReason.DRAFT_BINDING_MISMATCH.value,)
        if poisoned:
            return None, (CacheRejectionReason.DRAFT_POISONED.value,)
        return entry, ()

    def lookup_draft(
        self,
        key: DraftCacheKey | Mapping[str, Any],
        *,
        max_age_seconds: int | None = None,
    ) -> DraftCacheLookupResult:
        """Return only a current, integrity-checked untrusted draft."""

        if max_age_seconds is not None and (
            isinstance(max_age_seconds, bool)
            or not isinstance(max_age_seconds, int)
            or max_age_seconds < 0
        ):
            raise ValueError("max_age_seconds must be a nonnegative integer or None")
        cache_key = self._coerce_draft_key(key)
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM proof_draft_cache_entries WHERE key_id=?",
                (cache_key.key_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return DraftCacheLookupResult(
                CacheLookupStatus.MISS,
                cache_key,
                reason_codes=(CacheRejectionReason.DRAFT_MISS.value,),
            )
        entry, reasons = self._decode_draft_entry(cache_key, row)
        if entry is None:
            return DraftCacheLookupResult(
                CacheLookupStatus.REJECTED,
                cache_key,
                reason_codes=reasons,
            )
        now = self._now_ms()
        if now >= entry.expires_at_ms or (
            max_age_seconds is not None and now - entry.created_at_ms > max_age_seconds * 1000
        ):
            return DraftCacheLookupResult(
                CacheLookupStatus.REJECTED,
                cache_key,
                entry=entry,
                reason_codes=(CacheRejectionReason.DRAFT_STALE.value,),
            )
        return DraftCacheLookupResult(CacheLookupStatus.HIT, cache_key, entry=entry)

    def get_draft(
        self,
        key: DraftCacheKey | Mapping[str, Any],
        **requirements: Any,
    ) -> Mapping[str, Any] | None:
        return self.lookup_draft(key, **requirements).draft

    def delete_draft(self, key: DraftCacheKey | Mapping[str, Any]) -> bool:
        cache_key = self._coerce_draft_key(key)
        connection = self._connect()
        try:
            cursor = connection.execute(
                "DELETE FROM proof_draft_cache_entries WHERE key_id=?",
                (cache_key.key_id,),
            )
            return cursor.rowcount > 0
        finally:
            connection.close()

    def put(
        self,
        key: ProofCacheKey | Mapping[str, Any],
        receipt: ProofReceipt | Mapping[str, Any],
        *,
        ttl_seconds: int | None = None,
        complete: bool = True,
    ) -> CacheStoreResult:
        """Validate and atomically store an authoritative proof receipt."""

        cache_key = self._coerce_key(key)
        try:
            typed_receipt = (
                receipt if isinstance(receipt, ProofReceipt) else ProofReceipt.from_dict(receipt)
            )
        except (TypeError, ValueError, ContractValidationError):
            return CacheStoreResult(
                False,
                cache_key,
                reason_codes=(CacheRejectionReason.MALFORMED_ENTRY.value,),
            )
        reasons = _trust_reasons(
            cache_key,
            typed_receipt,
            complete=complete,
            requirements=CacheRequirements(required_assurance=AssuranceLevel.KERNEL_VERIFIED),
        )
        if reasons:
            return CacheStoreResult(False, cache_key, reason_codes=tuple(sorted(reasons)))
        ttl = self.default_ttl_seconds if ttl_seconds is None else ttl_seconds
        if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl <= 0:
            raise ValueError("ttl_seconds must be a positive integer")
        now = self._now_ms()
        entry = ProofCacheEntry.create(
            cache_key,
            typed_receipt,
            created_at_ms=now,
            expires_at_ms=now + ttl * 1000,
            complete=complete,
        )
        key_json = canonical_json(cache_key.to_dict())
        entry_json = canonical_json(entry.to_dict())
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                "SELECT * FROM proof_cache_entries WHERE key_id=?",
                (cache_key.key_id,),
            ).fetchone()
            if previous is not None:
                previous_entry, _ = self._decode_entry(cache_key, previous)
                if (
                    previous_entry is None
                    or previous_entry.receipt.receipt_id != typed_receipt.receipt_id
                ):
                    # A sidecar is bound to one immutable receipt identity.
                    # Replacing that receipt must atomically remove the old
                    # optional assurance while preserving the new kernel row.
                    connection.execute(
                        "DELETE FROM proof_attestation_entries WHERE key_id=?",
                        (cache_key.key_id,),
                    )
            connection.execute(
                """
                INSERT INTO proof_cache_entries(
                    key_id, key_json, entry_json, created_at_ms, expires_at_ms
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key_id) DO UPDATE SET
                    key_json=excluded.key_json,
                    entry_json=excluded.entry_json,
                    created_at_ms=excluded.created_at_ms,
                    expires_at_ms=excluded.expires_at_ms
                """,
                (
                    cache_key.key_id,
                    key_json,
                    entry_json,
                    entry.created_at_ms,
                    entry.expires_at_ms,
                ),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        try:
            from .proof_certificate_database import mirror_proof_cache_entry

            mirror_proof_cache_entry(
                key_id=cache_key.key_id,
                receipt_id=typed_receipt.receipt_id,
                verdict=str(getattr(typed_receipt.verdict, "value", typed_receipt.verdict) or ""),
                assurance=str(
                    getattr(
                        getattr(typed_receipt, "assurance", None),
                        "value",
                        getattr(typed_receipt, "assurance", ""),
                    )
                    or ""
                ),
                complete=complete,
            )
        except Exception:
            pass
        return CacheStoreResult(True, cache_key, entry=entry)

    store = put
    put_receipt = put
    store_receipt = put

    def put_attestation(
        self,
        key: ProofCacheKey | Mapping[str, Any],
        attestation: (AttestationVerification | PersistedAttestationRecord | Mapping[str, Any]),
        *,
        receipt: ProofReceipt | Mapping[str, Any] | None = None,
        ttl_seconds: int | None = None,
        created_at: str | None = None,
        expires_at: str | None = None,
        ipfs_cid: str = "",
    ) -> AttestationCacheStoreResult:
        """Persist a verified ZKP as an expiring sidecar to a cached receipt.

        Failure to store this optional record never rewrites or removes the
        underlying kernel receipt.  A caller can therefore retry IPFS or
        attestation persistence without changing the proof verdict.
        """

        cache_key = self._coerce_key(key)
        base = self.lookup(
            cache_key,
            required_assurance=AssuranceLevel.KERNEL_VERIFIED,
        )
        base_receipt = base.kernel_receipt
        if not base.hit or base_receipt is None:
            return AttestationCacheStoreResult(
                False,
                cache_key,
                reason_codes=(CacheRejectionReason.ATTESTATION_BINDING_MISMATCH.value,),
            )
        if receipt is not None:
            try:
                supplied_receipt = (
                    receipt
                    if isinstance(receipt, ProofReceipt)
                    else ProofReceipt.from_dict(receipt)
                )
            except (TypeError, ValueError, ContractValidationError):
                return AttestationCacheStoreResult(
                    False,
                    cache_key,
                    reason_codes=(CacheRejectionReason.ATTESTATION_MALFORMED.value,),
                )
            if supplied_receipt.receipt_id != base_receipt.receipt_id:
                return AttestationCacheStoreResult(
                    False,
                    cache_key,
                    reason_codes=(CacheRejectionReason.ATTESTATION_BINDING_MISMATCH.value,),
                )

        now = self._now_ms()
        try:
            if isinstance(attestation, PersistedAttestationRecord):
                record = attestation
            elif isinstance(attestation, AttestationVerification):
                ttl = self.default_ttl_seconds if ttl_seconds is None else ttl_seconds
                if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl <= 0:
                    raise ValueError("ttl_seconds must be a positive integer")
                created = created_at or _rfc3339_from_ms(now)
                expires = expires_at or _rfc3339_from_ms(now + ttl * 1000)
                record = build_persisted_attestation_record(
                    base_receipt,
                    attestation,
                    created_at=created,
                    expires_at=expires,
                )
            elif isinstance(attestation, Mapping):
                schema = attestation.get("schema")
                if schema == PersistedAttestationRecord.SCHEMA:
                    record = PersistedAttestationRecord.from_dict(attestation)
                else:
                    verification = AttestationVerification.from_dict(attestation)
                    ttl = self.default_ttl_seconds if ttl_seconds is None else ttl_seconds
                    if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl <= 0:
                        raise ValueError("ttl_seconds must be a positive integer")
                    record = build_persisted_attestation_record(
                        base_receipt,
                        verification,
                        created_at=created_at or _rfc3339_from_ms(now),
                        expires_at=expires_at or _rfc3339_from_ms(now + ttl * 1000),
                    )
            else:
                raise AttestationValidationError("invalid attestation value")
        except (
            TypeError,
            ValueError,
            ContractValidationError,
            AttestationValidationError,
        ):
            return AttestationCacheStoreResult(
                False,
                cache_key,
                reason_codes=(CacheRejectionReason.ATTESTATION_MALFORMED.value,),
            )

        if record.proof_receipt_id != base_receipt.receipt_id:
            return AttestationCacheStoreResult(
                False,
                cache_key,
                reason_codes=(CacheRejectionReason.ATTESTATION_BINDING_MISMATCH.value,),
            )
        try:
            record_expires_ms = _timestamp_ms(record.expires_at)
        except (TypeError, ValueError):
            return AttestationCacheStoreResult(
                False,
                cache_key,
                reason_codes=(CacheRejectionReason.ATTESTATION_MALFORMED.value,),
            )
        if now >= record_expires_ms:
            return AttestationCacheStoreResult(
                False,
                cache_key,
                reason_codes=(CacheRejectionReason.ATTESTATION_EXPIRED.value,),
            )
        entry = AttestationCacheEntry.create(
            cache_key,
            record,
            stored_at_ms=now,
            expires_at_ms=record_expires_ms,
            ipfs_cid=str(ipfs_cid or ""),
        )
        statement = record.envelope.statement
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            parent_row = connection.execute(
                "SELECT * FROM proof_cache_entries WHERE key_id=?",
                (cache_key.key_id,),
            ).fetchone()
            current_parent = None
            if parent_row is not None:
                current_parent, _ = self._decode_entry(cache_key, parent_row)
            commit_now = self._now_ms()
            parent_reasons = (
                _trust_reasons(
                    cache_key,
                    current_parent.receipt,
                    complete=current_parent.complete,
                    requirements=CacheRequirements(
                        required_assurance=AssuranceLevel.KERNEL_VERIFIED
                    ),
                )
                if current_parent is not None
                else set()
            )
            if (
                current_parent is None
                or current_parent.receipt.receipt_id != record.proof_receipt_id
                or parent_reasons
                or commit_now >= current_parent.expires_at_ms
                or commit_now >= record_expires_ms
            ):
                connection.rollback()
                return AttestationCacheStoreResult(
                    False,
                    cache_key,
                    reason_codes=(CacheRejectionReason.ATTESTATION_BINDING_MISMATCH.value,),
                )
            connection.execute(
                """
                INSERT INTO proof_attestation_entries(
                    key_id, proof_receipt_id, record_id, envelope_id,
                    public_input_digest, backend_policy_id, backend_id,
                    circuit_id, verification_key_id, formal_policy_id,
                    entry_json, stored_at_ms, expires_at_ms, ipfs_cid
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key_id) DO UPDATE SET
                    proof_receipt_id=excluded.proof_receipt_id,
                    record_id=excluded.record_id,
                    envelope_id=excluded.envelope_id,
                    public_input_digest=excluded.public_input_digest,
                    backend_policy_id=excluded.backend_policy_id,
                    backend_id=excluded.backend_id,
                    circuit_id=excluded.circuit_id,
                    verification_key_id=excluded.verification_key_id,
                    formal_policy_id=excluded.formal_policy_id,
                    entry_json=excluded.entry_json,
                    stored_at_ms=excluded.stored_at_ms,
                    expires_at_ms=excluded.expires_at_ms,
                    ipfs_cid=excluded.ipfs_cid
                """,
                (
                    cache_key.key_id,
                    record.proof_receipt_id,
                    record.record_id,
                    record.envelope_id,
                    record.public_input_digest,
                    statement.backend_policy_id,
                    statement.backend_id,
                    statement.circuit_id,
                    statement.verification_key_id,
                    statement.policy_id,
                    canonical_json(entry.to_dict()),
                    entry.stored_at_ms,
                    entry.expires_at_ms,
                    entry.ipfs_cid,
                ),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        try:
            from .proof_certificate_database import mirror_zkp_certificate

            mirror_zkp_certificate(
                key_id=cache_key.key_id,
                receipt_id=record.proof_receipt_id,
                envelope_id=str(record.envelope_id or ""),
                circuit_id=str(statement.circuit_id or ""),
                backend_id=str(statement.backend_id or ""),
                public_input_digest=str(record.public_input_digest or ""),
                ipfs_cid=str(entry.ipfs_cid or ""),
                simulated="simulated" in str(getattr(record.envelope.backend_mode, "value", record.envelope.backend_mode) or "").lower(),
            )
        except Exception:
            pass
        return AttestationCacheStoreResult(True, cache_key, entry=entry)

    store_attestation = put_attestation

    def _decode_attestation_entry(
        self,
        key: ProofCacheKey,
        receipt: ProofReceipt,
        row: DuckDBRow,
    ) -> tuple[AttestationCacheEntry | None, tuple[str, ...]]:
        try:
            payload = _strict_json_loads(str(row["entry_json"]))
            if not isinstance(payload, Mapping):
                raise ValueError("attestation entry must be an object")
            stored_key_id = str(payload["key_id"])
            record_payload = payload.get("record")
            if not isinstance(record_payload, Mapping):
                raise ValueError("attestation record must be an object")
            record = PersistedAttestationRecord.from_dict(record_payload)
            entry = AttestationCacheEntry(
                key=key,
                record=record,
                stored_at_ms=int(payload["stored_at_ms"]),
                expires_at_ms=int(payload["expires_at_ms"]),
                ipfs_cid=str(payload.get("ipfs_cid") or ""),
                entry_digest=str(payload["entry_digest"]),
            )
        except (
            KeyError,
            TypeError,
            ValueError,
            ContractValidationError,
            AttestationValidationError,
            json.JSONDecodeError,
        ):
            return None, (CacheRejectionReason.ATTESTATION_MALFORMED.value,)

        statement = record.envelope.statement
        poisoned = (
            stored_key_id != key.key_id
            or record.proof_receipt_id != receipt.receipt_id
            or str(payload.get("proof_receipt_id")) != receipt.receipt_id
            or str(payload.get("record_id")) != record.record_id
            or entry.entry_digest != entry.computed_digest
            or str(row["key_id"]) != key.key_id
            or str(row["proof_receipt_id"]) != record.proof_receipt_id
            or str(row["record_id"]) != record.record_id
            or str(row["envelope_id"]) != record.envelope_id
            or str(row["public_input_digest"]) != record.public_input_digest
            or str(row["backend_policy_id"]) != statement.backend_policy_id
            or str(row["backend_id"]) != statement.backend_id
            or str(row["circuit_id"]) != statement.circuit_id
            or str(row["verification_key_id"]) != statement.verification_key_id
            or str(row["formal_policy_id"]) != statement.policy_id
            or int(row["stored_at_ms"]) != entry.stored_at_ms
            or int(row["expires_at_ms"]) != entry.expires_at_ms
            or str(row["ipfs_cid"] or "") != entry.ipfs_cid
            or _timestamp_ms(record.expires_at) != entry.expires_at_ms
        )
        if poisoned:
            return None, (CacheRejectionReason.ATTESTATION_POISONED.value,)
        return entry, ()

    def _attestation_for_receipt(
        self,
        key: ProofCacheKey,
        receipt: ProofReceipt,
        *,
        now_ms: int | None = None,
        expected_backend_policy: AttestationBackendPolicy | None = None,
    ) -> tuple[AttestationCacheEntry | None, tuple[str, ...]]:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM proof_attestation_entries WHERE key_id=?",
                (key.key_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None, (CacheRejectionReason.ATTESTATION_MISS.value,)
        entry, reasons = self._decode_attestation_entry(key, receipt, row)
        if entry is None:
            return None, reasons
        checked_now = self._now_ms() if now_ms is None else now_ms
        if checked_now >= entry.expires_at_ms or not entry.record.is_current_at(
            _rfc3339_from_ms(checked_now)
        ):
            return entry, (CacheRejectionReason.ATTESTATION_EXPIRED.value,)
        if (
            expected_backend_policy is not None
            and entry.record.backend_policy.policy_id != expected_backend_policy.policy_id
        ):
            return entry, (CacheRejectionReason.ATTESTATION_BINDING_MISMATCH.value,)
        return entry, ()

    def lookup_attestation(
        self,
        key: ProofCacheKey | Mapping[str, Any] | str,
        *,
        expected_backend_policy: AttestationBackendPolicy | None = None,
        verifier: Callable[[Any], bool] | None = None,
        checked_at: str | None = None,
    ) -> AttestationCacheLookupResult:
        """Return a current sidecar while preserving the base receipt on miss."""

        if isinstance(key, str):
            receipt_id = key.strip()
            if not receipt_id:
                raise ValueError("proof receipt identity must not be empty")
            connection = self._connect()
            try:
                row = connection.execute(
                    """
                    SELECT cache.key_json
                    FROM proof_attestation_entries AS attestation
                    JOIN proof_cache_entries AS cache
                      ON cache.key_id = attestation.key_id
                    WHERE attestation.proof_receipt_id=?
                    ORDER BY attestation.stored_at_ms DESC
                    LIMIT 1
                    """,
                    (receipt_id,),
                ).fetchone()
            finally:
                connection.close()
            if row is None:
                # There is no key object to return for a receipt-only miss.
                # A deterministic lookup key cannot be invented safely.
                raise KeyError("no cached proof attestation for receipt %s" % receipt_id)
            payload = _strict_json_loads(str(row["key_json"]))
            if not isinstance(payload, Mapping):
                raise ValueError("cached proof key is malformed")
            cache_key = ProofCacheKey.from_dict(payload)
        else:
            cache_key = self._coerce_key(key)
        base = self.lookup(
            cache_key,
            required_assurance=AssuranceLevel.KERNEL_VERIFIED,
            _include_attestation=False,
        )
        receipt = base.kernel_receipt
        if receipt is None:
            return AttestationCacheLookupResult(
                CacheLookupStatus.MISS,
                cache_key,
                reason_codes=(CacheRejectionReason.CACHE_MISS.value,),
            )
        if not base.hit:
            return AttestationCacheLookupResult(
                CacheLookupStatus.REJECTED,
                cache_key,
                receipt=receipt,
                reason_codes=base.reason_codes,
            )
        try:
            checked_at_ms = self._now_ms() if checked_at is None else _timestamp_ms(checked_at)
        except (TypeError, ValueError):
            raise ValueError("checked_at must be an RFC3339 timestamp") from None
        entry, reasons = self._attestation_for_receipt(
            cache_key,
            receipt,
            now_ms=checked_at_ms,
            expected_backend_policy=expected_backend_policy,
        )
        if entry is None and reasons == (CacheRejectionReason.ATTESTATION_MISS.value,):
            return AttestationCacheLookupResult(
                CacheLookupStatus.MISS,
                cache_key,
                receipt=receipt,
                reason_codes=reasons,
            )
        if reasons:
            return AttestationCacheLookupResult(
                CacheLookupStatus.REJECTED,
                cache_key,
                receipt=receipt,
                entry=entry,
                reason_codes=reasons,
            )
        replay_verifier = verifier or self._attestation_verifier
        reproduced_ok = False
        if replay_verifier is not None and entry is not None:
            reproduced = reproduce_attestation_verification(
                entry.record,
                verifier=replay_verifier,
                checked_at=checked_at or _rfc3339_from_ms(checked_at_ms),
                receipt=receipt,
                backend_policy=expected_backend_policy,
            )
            if not reproduced.authoritative:
                return AttestationCacheLookupResult(
                    CacheLookupStatus.REJECTED,
                    cache_key,
                    receipt=receipt,
                    entry=entry,
                    reason_codes=(CacheRejectionReason.ATTESTATION_VERIFICATION_FAILED.value,),
                )
            reproduced_ok = True
        return AttestationCacheLookupResult(
            CacheLookupStatus.HIT,
            cache_key,
            receipt=receipt,
            entry=entry,
            reproduced=reproduced_ok,
        )

    def get_attestation(
        self,
        key: ProofCacheKey | Mapping[str, Any] | str,
        **requirements: Any,
    ) -> PersistedAttestationRecord | None:
        """Compatibility helper returning only a current public record."""

        return self.lookup_attestation(key, **requirements).record

    def _decode_entry(
        self, key: ProofCacheKey, row: DuckDBRow
    ) -> tuple[ProofCacheEntry | None, tuple[str, ...]]:
        try:
            stored_key_payload = _strict_json_loads(str(row["key_json"]))
            stored_payload = _strict_json_loads(str(row["entry_json"]))
            if not isinstance(stored_key_payload, Mapping) or not isinstance(
                stored_payload, Mapping
            ):
                raise ValueError("entry envelope must contain objects")
            stored_key = ProofCacheKey.from_dict(stored_key_payload)
            receipt_payload = stored_payload.get("receipt")
            if not isinstance(receipt_payload, Mapping):
                raise ValueError("entry receipt must be an object")
            receipt = ProofReceipt.from_dict(receipt_payload)
            created_at_ms = int(stored_payload["created_at_ms"])
            expires_at_ms = int(stored_payload["expires_at_ms"])
            complete = stored_payload["complete"]
            if not isinstance(complete, bool):
                raise ValueError("entry complete must be a boolean")
            digest = str(stored_payload["entry_digest"])
            entry = ProofCacheEntry(
                key=stored_key,
                receipt=receipt,
                created_at_ms=created_at_ms,
                expires_at_ms=expires_at_ms,
                complete=complete,
                entry_digest=digest,
            )
        except (KeyError, TypeError, ValueError, ContractValidationError, json.JSONDecodeError):
            return None, (CacheRejectionReason.MALFORMED_ENTRY.value,)

        poisoned = (
            stored_key.key_id != key.key_id
            or canonical_json(stored_key.to_dict()) != canonical_json(key.to_dict())
            or str(stored_payload.get("key_id")) != key.key_id
            or str(stored_payload.get("receipt_id")) != receipt.receipt_id
            or entry.entry_digest != entry.computed_digest
            or int(row["created_at_ms"]) != entry.created_at_ms
            or int(row["expires_at_ms"]) != entry.expires_at_ms
        )
        if poisoned:
            return None, (CacheRejectionReason.POISONED_ENTRY.value,)
        return entry, ()

    def lookup(
        self,
        key: ProofCacheKey | Mapping[str, Any],
        *,
        required_assurance: AssuranceLevel = AssuranceLevel.KERNEL_VERIFIED,
        required_freshness: EvidenceFreshness = EvidenceFreshness.CURRENT,
        max_age_seconds: int | None = None,
        requirements: CacheRequirements | None = None,
        attestation_verifier: Callable[[Any], bool] | None = None,
        _include_attestation: bool = True,
    ) -> CacheLookupResult:
        cache_key = self._coerce_key(key)
        requested = requirements or CacheRequirements(
            required_assurance=required_assurance,
            required_freshness=required_freshness,
            max_age_seconds=max_age_seconds,
        )
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM proof_cache_entries WHERE key_id=?",
                (cache_key.key_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return CacheLookupResult(
                CacheLookupStatus.MISS,
                cache_key,
                reason_codes=(CacheRejectionReason.CACHE_MISS.value,),
            )
        entry, decoding_reasons = self._decode_entry(cache_key, row)
        if entry is None:
            return CacheLookupResult(
                CacheLookupStatus.REJECTED,
                cache_key,
                reason_codes=decoding_reasons,
            )

        now = self._now_ms()
        reasons = _trust_reasons(
            cache_key,
            entry.receipt,
            complete=entry.complete,
            requirements=requested,
        )
        if now >= entry.expires_at_ms:
            reasons.add(CacheRejectionReason.STALE_ENTRY.value)
            reasons.add(CacheRejectionReason.FRESHNESS_NOT_SATISFIED.value)
        if (
            requested.max_age_seconds is not None
            and now - entry.created_at_ms > requested.max_age_seconds * 1000
        ):
            reasons.add(CacheRejectionReason.STALE_ENTRY.value)
            reasons.add(CacheRejectionReason.FRESHNESS_NOT_SATISFIED.value)
        attestation_entry: AttestationCacheEntry | None = None
        attestation_reasons: tuple[str, ...] = ()
        base_blockers = reasons - {CacheRejectionReason.INSUFFICIENT_ASSURANCE.value}
        if _include_attestation and not base_blockers:
            attestation_entry, attestation_reasons = self._attestation_for_receipt(
                cache_key,
                entry.receipt,
                now_ms=now,
            )
            if attestation_entry is not None and not attestation_reasons:
                replay_verifier = attestation_verifier or self._attestation_verifier
                attestation_reproduced = False
                if replay_verifier is not None:
                    reproduced = reproduce_attestation_verification(
                        attestation_entry.record,
                        verifier=replay_verifier,
                        checked_at=_rfc3339_from_ms(now),
                        receipt=entry.receipt,
                    )
                    attestation_reproduced = reproduced.authoritative
                    if not attestation_reproduced:
                        attestation_reasons = (
                            CacheRejectionReason.ATTESTATION_VERIFICATION_FAILED.value,
                        )
                elif requested.required_assurance is AssuranceLevel.ATTESTED:
                    attestation_reasons = (CacheRejectionReason.ATTESTATION_REPLAY_REQUIRED.value,)
                if attestation_reproduced and assurance_satisfies(
                    AssuranceLevel.ATTESTED, requested.required_assurance
                ):
                    reasons.discard(CacheRejectionReason.INSUFFICIENT_ASSURANCE.value)
            if attestation_reasons and requested.required_assurance is AssuranceLevel.ATTESTED:
                reasons.update(attestation_reasons)
        if reasons:
            return CacheLookupResult(
                CacheLookupStatus.REJECTED,
                cache_key,
                entry=entry,
                reason_codes=tuple(sorted(reasons)),
                attestation_entry=(attestation_entry if not attestation_reasons else None),
                attestation_reproduced=False,
            )
        return CacheLookupResult(
            CacheLookupStatus.HIT,
            cache_key,
            entry=entry,
            attestation_entry=(attestation_entry if not attestation_reasons else None),
            attestation_reproduced=bool(
                attestation_entry
                and not attestation_reasons
                and (attestation_verifier is not None or self._attestation_verifier is not None)
            ),
        )

    def get(
        self,
        key: ProofCacheKey | Mapping[str, Any],
        **requirements: Any,
    ) -> ProofReceipt | None:
        """Compatibility helper returning only the accepted receipt."""

        return self.lookup(key, **requirements).receipt

    lookup_receipt = lookup
    get_receipt = get

    def delete(self, key: ProofCacheKey | Mapping[str, Any]) -> bool:
        cache_key = self._coerce_key(key)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM proof_attestation_entries WHERE key_id=?",
                (cache_key.key_id,),
            )
            cursor = connection.execute(
                "DELETE FROM proof_cache_entries WHERE key_id=?",
                (cache_key.key_id,),
            )
            connection.commit()
            return cursor.rowcount > 0
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    delete_receipt = delete

    def delete_attestation(self, key: ProofCacheKey | Mapping[str, Any] | str) -> bool:
        """Delete only the optional sidecar, never the trusted proof receipt."""

        connection = self._connect()
        try:
            if isinstance(key, str):
                receipt_id = key.strip()
                if not receipt_id:
                    raise ValueError("proof receipt identity must not be empty")
                cursor = connection.execute(
                    "DELETE FROM proof_attestation_entries WHERE proof_receipt_id=?",
                    (receipt_id,),
                )
            else:
                cache_key = self._coerce_key(key)
                cursor = connection.execute(
                    "DELETE FROM proof_attestation_entries WHERE key_id=?",
                    (cache_key.key_id,),
                )
            return cursor.rowcount > 0
        finally:
            connection.close()

    def purge_expired(self) -> int:
        now = self._now_ms()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                DELETE FROM proof_attestation_entries
                WHERE key_id IN (
                    SELECT key_id FROM proof_cache_entries
                    WHERE expires_at_ms<=?
                )
                """,
                (now,),
            )
            connection.execute(
                "DELETE FROM proof_attestation_entries WHERE expires_at_ms<=?",
                (now,),
            )
            first = connection.execute(
                "DELETE FROM proof_cache_entries WHERE expires_at_ms<=?", (now,)
            ).rowcount
            drafts = connection.execute(
                "DELETE FROM proof_draft_cache_entries WHERE expires_at_ms<=?",
                (now,),
            ).rowcount
            connection.execute("DELETE FROM proof_flight_outcomes WHERE expires_at_ms<=?", (now,))
            connection.execute("DELETE FROM proof_single_flights WHERE expires_at_ms<=?", (now,))
            connection.commit()
            return first + drafts
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def acquire_lease(
        self,
        key: ProofCacheKey | DraftCacheKey | Mapping[str, Any],
        *,
        owner_id: str | None = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> SingleFlightLease:
        if isinstance(lease_seconds, bool) or lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        cache_key = self._coerce_coordination_key(key)
        owner = (owner_id or f"{os.getpid()}:{threading.get_ident()}").strip()
        if not owner:
            raise ValueError("owner_id must not be empty")
        now = self._now_ms()
        token = uuid.uuid4().hex
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM proof_single_flights WHERE key_id=?",
                (cache_key.key_id,),
            ).fetchone()
            if row is not None and int(row["expires_at_ms"]) > now:
                connection.commit()
                return SingleFlightLease(
                    cache=self,
                    key=cache_key,
                    owner_id=str(row["owner_id"]),
                    token=str(row["token"]),
                    fencing_token=int(row["fencing_token"]),
                    acquired_at_ms=int(row["acquired_at_ms"]),
                    expires_at_ms=int(row["expires_at_ms"]),
                    acquired=False,
                )
            # A completed leader releases its lease immediately, but its
            # bounded outcome remains the rendezvous point for callers which
            # were concurrent yet reached DuckDB just after that release.
            # Treating it as a follower generation closes the late-arrival
            # duplicate-execution race without turning the outcome into a
            # trusted proof-cache entry.
            completed = connection.execute(
                """
                SELECT fencing_token, created_at_ms, expires_at_ms
                FROM proof_flight_outcomes
                WHERE key_id=? AND expires_at_ms>?
                """,
                (cache_key.key_id, now),
            ).fetchone()
            if completed is not None:
                connection.commit()
                return SingleFlightLease(
                    cache=self,
                    key=cache_key,
                    owner_id="completed-outcome",
                    token="",
                    fencing_token=int(completed["fencing_token"]),
                    acquired_at_ms=int(completed["created_at_ms"]),
                    expires_at_ms=int(completed["expires_at_ms"]),
                    acquired=False,
                )
            fencing = int(row["fencing_token"]) + 1 if row is not None else 1
            expires = now + lease_seconds * 1000
            connection.execute(
                """
                INSERT INTO proof_single_flights(
                    key_id, owner_id, token, fencing_token,
                    acquired_at_ms, expires_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(key_id) DO UPDATE SET
                    owner_id=excluded.owner_id,
                    token=excluded.token,
                    fencing_token=excluded.fencing_token,
                    acquired_at_ms=excluded.acquired_at_ms,
                    expires_at_ms=excluded.expires_at_ms
                """,
                (cache_key.key_id, owner, token, fencing, now, expires),
            )
            # An outcome from an older fencing generation must never satisfy a
            # follower of the new computation.
            connection.execute(
                "DELETE FROM proof_flight_outcomes WHERE key_id=?",
                (cache_key.key_id,),
            )
            connection.commit()
            return SingleFlightLease(
                cache=self,
                key=cache_key,
                owner_id=owner,
                token=token,
                fencing_token=fencing,
                acquired_at_ms=now,
                expires_at_ms=expires,
                acquired=True,
            )
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    acquire_single_flight = acquire_lease
    acquire_draft_lease = acquire_lease

    def renew_lease(
        self,
        lease: SingleFlightLease,
        *,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> SingleFlightLease:
        if not lease.acquired:
            raise SingleFlightError("only the lease owner can renew a lease")
        if isinstance(lease_seconds, bool) or lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        now = self._now_ms()
        expires = now + lease_seconds * 1000
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE proof_single_flights SET expires_at_ms=?
                WHERE key_id=? AND owner_id=? AND token=? AND fencing_token=?
                  AND expires_at_ms>?
                """,
                (
                    expires,
                    lease.key.key_id,
                    lease.owner_id,
                    lease.token,
                    lease.fencing_token,
                    now,
                ),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise SingleFlightError("single-flight lease is expired or fenced")
            connection.commit()
        finally:
            connection.close()
        return SingleFlightLease(
            cache=self,
            key=lease.key,
            owner_id=lease.owner_id,
            token=lease.token,
            fencing_token=lease.fencing_token,
            acquired_at_ms=lease.acquired_at_ms,
            expires_at_ms=expires,
            acquired=True,
        )

    def release_lease(self, lease: SingleFlightLease) -> bool:
        if not lease.acquired:
            return False
        connection = self._connect()
        try:
            cursor = connection.execute(
                """
                DELETE FROM proof_single_flights
                WHERE key_id=? AND owner_id=? AND token=? AND fencing_token=?
                """,
                (
                    lease.key.key_id,
                    lease.owner_id,
                    lease.token,
                    lease.fencing_token,
                ),
            )
            return cursor.rowcount == 1
        finally:
            connection.close()

    def _publish_outcome(
        self,
        lease: SingleFlightLease,
        *,
        status: str,
        value: Any,
        ttl_seconds: int,
    ) -> None:
        if not lease.acquired:
            raise SingleFlightError("only the lease owner can publish an outcome")
        envelope = {
            "schema_version": FORMAL_VERIFICATION_FLIGHT_SCHEMA,
            "status": status,
            "value": (
                _single_flight_public_value(value)
                if status == "ok"
                else _json_value(value, field_name="single-flight error")
            ),
        }
        encoded = canonical_json(envelope)
        digest = f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"
        now = self._now_ms()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            active = connection.execute(
                """
                SELECT 1 FROM proof_single_flights
                WHERE key_id=? AND owner_id=? AND token=? AND fencing_token=?
                  AND expires_at_ms>?
                """,
                (
                    lease.key.key_id,
                    lease.owner_id,
                    lease.token,
                    lease.fencing_token,
                    now,
                ),
            ).fetchone()
            if active is None:
                connection.rollback()
                raise SingleFlightError("cannot publish from an expired or fenced lease")
            connection.execute(
                """
                INSERT INTO proof_flight_outcomes(
                    key_id, fencing_token, status, outcome_json,
                    outcome_digest, created_at_ms, expires_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key_id) DO UPDATE SET
                    fencing_token=excluded.fencing_token,
                    status=excluded.status,
                    outcome_json=excluded.outcome_json,
                    outcome_digest=excluded.outcome_digest,
                    created_at_ms=excluded.created_at_ms,
                    expires_at_ms=excluded.expires_at_ms
                """,
                (
                    lease.key.key_id,
                    lease.fencing_token,
                    status,
                    encoded,
                    digest,
                    now,
                    now + ttl_seconds * 1000,
                ),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _read_outcome(self, key_id: str, fencing_token: int) -> tuple[bool, Any]:
        now = self._now_ms()
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT * FROM proof_flight_outcomes
                WHERE key_id=? AND fencing_token=? AND expires_at_ms>?
                """,
                (key_id, fencing_token, now),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return False, None
        try:
            payload = _strict_json_loads(str(row["outcome_json"]))
            encoded = canonical_json(payload)
            digest = f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"
            if digest != str(row["outcome_digest"]):
                raise ValueError("single-flight outcome digest mismatch")
            if (
                not isinstance(payload, Mapping)
                or payload.get("schema_version") != FORMAL_VERIFICATION_FLIGHT_SCHEMA
                or payload.get("status") != row["status"]
            ):
                raise ValueError("single-flight outcome envelope mismatch")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SingleFlightExecutionError(
                bounded_rejection_reason("single_flight_execution_failed")
            ) from exc
        if row["status"] == "error":
            error = payload.get("value")
            reason_code = (
                str(error.get("reason_code"))
                if isinstance(error, Mapping)
                else "single_flight_execution_failed"
            )
            raise SingleFlightExecutionError(bounded_rejection_reason(reason_code))
        return True, payload.get("value")

    def single_flight(
        self,
        key: ProofCacheKey | DraftCacheKey | Mapping[str, Any],
        execute: Callable[[], T],
        *,
        owner_id: str | None = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        wait_timeout_seconds: int = DEFAULT_WAIT_TIMEOUT_SECONDS,
        poll_interval_seconds: float = 0.02,
        outcome_ttl_seconds: int = 60,
    ) -> T:
        """Execute once across threads/processes and share the exact outcome.

        Shared outcomes are a coordination channel, not proof-cache entries;
        callers must still use :meth:`lookup` for an authoritative cached
        receipt.
        """

        if not callable(execute):
            raise ValueError("execute must be callable")
        if wait_timeout_seconds <= 0 or poll_interval_seconds <= 0 or outcome_ttl_seconds <= 0:
            raise ValueError("wait timeout, poll interval, and outcome TTL must be positive")
        cache_key = self._coerce_coordination_key(key)
        deadline = time.monotonic() + wait_timeout_seconds
        while True:
            lease = self.acquire_lease(cache_key, owner_id=owner_id, lease_seconds=lease_seconds)
            if lease.acquired:
                heartbeat_stop = threading.Event()
                heartbeat_failures: list[BaseException] = []

                def heartbeat() -> None:
                    interval = max(0.1, lease_seconds / 3)
                    while not heartbeat_stop.wait(interval):
                        try:
                            self.renew_lease(lease, lease_seconds=lease_seconds)
                        except BaseException as exc:
                            heartbeat_failures.append(exc)
                            return

                heartbeat_thread = threading.Thread(
                    target=heartbeat,
                    name=f"proof-flight-heartbeat-{lease.fencing_token}",
                    daemon=True,
                )
                heartbeat_thread.start()
                try:
                    value = execute()
                    heartbeat_stop.set()
                    heartbeat_thread.join()
                    if heartbeat_failures:
                        raise SingleFlightError(
                            "single-flight lease heartbeat was fenced"
                        ) from heartbeat_failures[0]
                    self._publish_outcome(
                        lease,
                        status="ok",
                        value=value,
                        ttl_seconds=outcome_ttl_seconds,
                    )
                    return value
                except BaseException as exc:
                    heartbeat_stop.set()
                    heartbeat_thread.join()
                    try:
                        cancelled = type(exc).__name__ in {
                            "CancelledError",
                            "GeneratorExit",
                            "KeyboardInterrupt",
                        }
                        self._publish_outcome(
                            lease,
                            status="error",
                            value={
                                "reason_code": (
                                    "single_flight_cancelled"
                                    if cancelled
                                    else "single_flight_execution_failed"
                                ),
                            },
                            ttl_seconds=outcome_ttl_seconds,
                        )
                    except BaseException:
                        # Preserve the leader's original failure.  Followers
                        # will take over after the fenced/expired lease when
                        # an error outcome cannot be published.
                        pass
                    raise
                finally:
                    heartbeat_stop.set()
                    heartbeat_thread.join()
                    lease.release()

            observed_fence = lease.fencing_token
            while time.monotonic() < deadline:
                found, value = self._read_outcome(cache_key.key_id, observed_fence)
                if found:
                    return value
                connection = self._connect()
                try:
                    active = connection.execute(
                        """
                        SELECT fencing_token, expires_at_ms
                        FROM proof_single_flights WHERE key_id=?
                        """,
                        (cache_key.key_id,),
                    ).fetchone()
                finally:
                    connection.close()
                if (
                    active is None
                    or int(active["expires_at_ms"]) <= self._now_ms()
                    or int(active["fencing_token"]) != observed_fence
                ):
                    break
                time.sleep(poll_interval_seconds)
            if time.monotonic() >= deadline:
                raise SingleFlightTimeout(bounded_rejection_reason("single_flight_timeout"))

    execute_single_flight = single_flight
    run_single_flight = single_flight

    def single_flight_draft(
        self,
        key: DraftCacheKey | Mapping[str, Any],
        execute: Callable[[], Any],
        **coordination: Any,
    ) -> Mapping[str, Any]:
        """Share one model draft while enforcing the untrusted-draft contract.

        Validation happens inside the leader execution, before its outcome is
        published.  Consequently, an authority-claiming payload becomes a
        shared execution failure and can never be returned to either leader
        or followers as a reusable draft.
        """

        if not callable(execute):
            raise ValueError("execute must be callable")

        def execute_checked() -> dict[str, Any]:
            return _coerce_untrusted_draft(execute())

        value = self.single_flight(key, execute_checked, **coordination)
        # Revalidate the decoded outcome as defense in depth against database
        # tampering or callers reaching this method after a process restart.
        return _coerce_untrusted_draft(value)

    execute_draft_single_flight = single_flight_draft


# Concise compatibility name for callers that already operate in the formal
# verification package.
ProofCache = FormalVerificationCache
TrustAwareProofCache = FormalVerificationCache


__all__ = [
    "FORMAL_VERIFICATION_CACHE_SCHEMA",
    "FORMAL_VERIFICATION_CACHE_KEY_SCHEMA",
    "FORMAL_VERIFICATION_DRAFT_CACHE_SCHEMA",
    "FORMAL_VERIFICATION_DRAFT_CACHE_KEY_SCHEMA",
    "FORMAL_VERIFICATION_FLIGHT_SCHEMA",
    "FORMAL_VERIFICATION_ATTESTATION_SCHEMA",
    "FORMAL_VERIFICATION_ATTESTATION_CACHE_SCHEMA",
    "DEFAULT_CACHE_TTL_SECONDS",
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_WAIT_TIMEOUT_SECONDS",
    "DEFAULT_MAX_DRAFT_BYTES",
    "CacheLookupStatus",
    "CacheRejectionReason",
    "CacheRequirements",
    "ProofCacheKey",
    "FormalVerificationCacheKey",
    "DraftCacheKey",
    "FormalVerificationDraftCacheKey",
    "ProofDraftCacheKey",
    "ProofCacheEntry",
    "UntrustedDraftCacheEntry",
    "DraftCacheEntry",
    "DraftCacheLookupResult",
    "DraftCacheStoreResult",
    "AttestationCacheEntry",
    "CacheLookupResult",
    "CacheStoreResult",
    "AttestationCacheLookupResult",
    "AttestationCacheStoreResult",
    "SingleFlightLease",
    "SingleFlightError",
    "SingleFlightTimeout",
    "SingleFlightExecutionError",
    "FormalVerificationCache",
    "ProofCache",
    "TrustAwareProofCache",
    "build_proof_cache_key",
    "make_proof_cache_key",
    "build_draft_cache_key",
    "make_draft_cache_key",
]
