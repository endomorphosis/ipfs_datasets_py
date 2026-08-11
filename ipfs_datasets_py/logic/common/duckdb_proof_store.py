"""Unified DuckDB proof-cache schema and protocol (DQK-025).

Normalizes proof keys, premises, translator / solver / toolchain /
theorem-registry / policy / resource dimensions, outcomes, trust levels,
evidence, access statistics, and immutable envelope references **behind** the
existing :mod:`ipfs_datasets_py.logic.backends.cache_protocol`
(``VerificationCacheProtocol@1``).

Authority dimensions from both the hammer obligation cache and the
verification-cache key surface are retained as a closed vocabulary.  Dropping
or silently substituting a dimension is a hard error.  Exact key identity and
entry integrity are fail-closed: digest drift, unknown fields, and unknown
schema versions never load as usable hits.

Importing this module is inert: no DuckDB, network, or filesystem I/O.  A live
DuckDB connection may be injected later; the default store is process-local
and implements the verification-cache protocol so shadow and promotion work
can proceed without a server.

Catalog tables (``proofs``):

* ``proof_keys``, ``proof_key_dimensions``, ``premises``
* ``proof_entries``, ``proof_evidence``, ``solver_runs``
* ``attestations``, ``invalidations``, ``revocations``
* ``singleflight_claims``, ``access_statistics``
"""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final, Protocol, runtime_checkable

from ..backends.cache_protocol import (
    DEFAULT_MAX_ENTRIES,
    DEFAULT_NEGATIVE_TTL_SECONDS,
    DEFAULT_POSITIVE_TTL_SECONDS,
    VERIFICATION_CACHE_KEY_SCHEMA_VERSION,
    VERIFICATION_CACHE_PROTOCOL_INTERFACE,
    VERIFICATION_CACHE_PROTOCOL_SCHEMA_VERSION,
    CacheLookupReason,
    CachePolarity,
    VerificationCacheEntry,
    VerificationCacheError,
    VerificationCacheKey,
    VerificationCacheLookup,
    VerificationCacheProtocol,
    content_digest,
    identity_digest,
)
from ..backends.results import ResultAuthority, ResultStatus, TypedBackendResult
from ..families.models import EvidenceAuthority
from ..ir_core.claims import FrozenMap

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

DUCKDB_PROOF_STORE_INTERFACE: Final = "DuckDBProofStore@1"
DUCKDB_PROOF_STORE_SCHEMA_VERSION: Final = "duckdb-proof-store/v1"
UNIFIED_PROOF_KEY_SCHEMA_VERSION: Final = "unified-proof-key/v1"
UNIFIED_PROOF_ENTRY_SCHEMA_VERSION: Final = "unified-proof-entry/v1"
PROOFS_CATALOG_NAME: Final = "proofs"

# Closed authority-dimension vocabulary.  Every producer (hammer obligation
# cache, verification-cache protocol, legal-IR / corpus bridges) must project
# into this set; none of these names may be dropped from a normalized key.
PROOF_AUTHORITY_DIMENSIONS: Final[tuple[str, ...]] = (
    "ir",
    "property",
    "assumptions",
    "premises",
    "translator",
    "solver",
    "toolchain",
    "theorem_registry",
    "policy",
    "resource",
    "tree",
    "backend_id",
    "backend_binary",
    "backend_version",
    "backend_config",
)

PROOF_AUTHORITY_DIMENSION_SET: Final[frozenset[str]] = frozenset(
    PROOF_AUTHORITY_DIMENSIONS
)

# Catalog table family declared by the control-plane plan.
PROOFS_CATALOG_TABLES: Final[tuple[str, ...]] = (
    "proof_keys",
    "proof_entries",
    "proof_key_dimensions",
    "premises",
    "solver_runs",
    "proof_evidence",
    "attestations",
    "invalidations",
    "revocations",
    "singleflight_claims",
    "access_statistics",
)

# SQL DDL for the proofs catalog.  Applied only when an explicit connection is
# provided; unit tests exercise the pure-Python store without DuckDB.
PROOFS_CATALOG_DDL: Final[str] = """
CREATE TABLE IF NOT EXISTS proof_keys (
    key_digest VARCHAR PRIMARY KEY,
    schema_version VARCHAR NOT NULL,
    ir_digest VARCHAR NOT NULL,
    property_digest VARCHAR NOT NULL,
    assumptions_digest VARCHAR NOT NULL,
    premises_digest VARCHAR NOT NULL,
    translator_digest VARCHAR NOT NULL,
    solver_identities_digest VARCHAR NOT NULL,
    toolchain_identity_digest VARCHAR NOT NULL,
    theorem_registry_digest VARCHAR NOT NULL,
    policy_digest VARCHAR NOT NULL,
    resources_digest VARCHAR NOT NULL,
    tree_digest VARCHAR NOT NULL,
    backend_id VARCHAR NOT NULL,
    backend_binary_digest VARCHAR NOT NULL,
    backend_version VARCHAR NOT NULL,
    backend_config_digest VARCHAR NOT NULL,
    key_payload_json VARCHAR NOT NULL,
    key_integrity_digest VARCHAR NOT NULL,
    created_at DOUBLE NOT NULL
);

CREATE TABLE IF NOT EXISTS proof_key_dimensions (
    key_digest VARCHAR NOT NULL,
    dimension_name VARCHAR NOT NULL,
    dimension_digest VARCHAR NOT NULL,
    PRIMARY KEY (key_digest, dimension_name)
);

CREATE TABLE IF NOT EXISTS premises (
    key_digest VARCHAR NOT NULL,
    premise_digest VARCHAR NOT NULL,
    premise_ordinal INTEGER NOT NULL,
    PRIMARY KEY (key_digest, premise_digest)
);

CREATE TABLE IF NOT EXISTS proof_entries (
    entry_digest VARCHAR PRIMARY KEY,
    key_digest VARCHAR NOT NULL,
    outcome VARCHAR NOT NULL,
    trust_level VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    result_authority VARCHAR NOT NULL,
    evidence_authority VARCHAR NOT NULL,
    polarity VARCHAR NOT NULL,
    created_at DOUBLE NOT NULL,
    result_id VARCHAR NOT NULL,
    payload_json VARCHAR NOT NULL,
    envelope_content_id VARCHAR NOT NULL,
    envelope_digest VARCHAR NOT NULL,
    diagnostics_json VARCHAR NOT NULL,
    schema_version VARCHAR NOT NULL,
    verification_entry_digest VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS proof_evidence (
    evidence_id VARCHAR PRIMARY KEY,
    entry_digest VARCHAR NOT NULL,
    evidence_kind VARCHAR NOT NULL,
    evidence_authority VARCHAR NOT NULL,
    content_digest VARCHAR NOT NULL,
    payload_json VARCHAR NOT NULL,
    created_at DOUBLE NOT NULL
);

CREATE TABLE IF NOT EXISTS solver_runs (
    run_id VARCHAR PRIMARY KEY,
    key_digest VARCHAR NOT NULL,
    backend_id VARCHAR NOT NULL,
    backend_version VARCHAR NOT NULL,
    solver_identities_digest VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    started_at DOUBLE NOT NULL,
    finished_at DOUBLE NOT NULL,
    diagnostics_json VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS attestations (
    attestation_id VARCHAR PRIMARY KEY,
    entry_digest VARCHAR NOT NULL,
    attestor_id VARCHAR NOT NULL,
    content_digest VARCHAR NOT NULL,
    created_at DOUBLE NOT NULL,
    payload_json VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS invalidations (
    invalidation_id VARCHAR PRIMARY KEY,
    key_digest VARCHAR NOT NULL,
    reason VARCHAR NOT NULL,
    created_at DOUBLE NOT NULL,
    actor_id VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS revocations (
    revocation_id VARCHAR PRIMARY KEY,
    entry_digest VARCHAR NOT NULL,
    reason VARCHAR NOT NULL,
    created_at DOUBLE NOT NULL,
    actor_id VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS singleflight_claims (
    key_digest VARCHAR PRIMARY KEY,
    claim_id VARCHAR NOT NULL,
    owner_id VARCHAR NOT NULL,
    fence_token VARCHAR NOT NULL,
    claimed_at DOUBLE NOT NULL,
    expires_at DOUBLE NOT NULL,
    status VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS access_statistics (
    key_digest VARCHAR PRIMARY KEY,
    hits BIGINT NOT NULL,
    misses BIGINT NOT NULL,
    writes BIGINT NOT NULL,
    rejections BIGINT NOT NULL,
    last_access_at DOUBLE NOT NULL
);
""".strip()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DuckDBProofStoreError(ValueError):
    """Raised when a proof-store key, entry, or operation is invalid."""


class DuckDBProofStoreIntegrityError(DuckDBProofStoreError):
    """Raised when a stored key or entry fails integrity rehash."""


class DuckDBProofStoreAuthorityError(DuckDBProofStoreError):
    """Raised when a write would drop or raise authority dimensions/trust."""


# ---------------------------------------------------------------------------
# Outcomes and trust (closed vocabularies)
# ---------------------------------------------------------------------------


class ProofOutcomeKind(StrEnum):
    """Closed outcome kinds retained as distinct authority conclusions.

    ``proof`` and ``counterexample`` are conclusive positive/negative evidence.
    ``unknown`` is a non-conclusive negative cache record.  ``error`` is an
    operational failure and must never be collapsed into ``unknown``.
    """

    PROOF = "proof"
    COUNTEREXAMPLE = "counterexample"
    UNKNOWN = "unknown"
    ERROR = "error"


class ProofTrustLevel(StrEnum):
    """Trust classification for a cached proof outcome.

    Aligns with :class:`EvidenceAuthority` ranks plus an explicit
    non-trusted band for ATP/SMT candidates that must never promote.
    """

    AUTHORITATIVE = "authoritative"
    INDEPENDENTLY_CHECKABLE = "independently_checkable"
    BOUNDED = "bounded"
    ADVISORY = "advisory"
    NON_TRUSTED = "non_trusted"
    NONE = "none"


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
_ERROR_STATUSES: Final = frozenset(
    {
        ResultStatus.ERROR,
        ResultStatus.MALFORMED,
        ResultStatus.UNAVAILABLE,
        ResultStatus.UNSUPPORTED,
        ResultStatus.RECONSTRUCTION_FAILED,
        ResultStatus.ATTESTATION_INVALID,
        ResultStatus.TIMEOUT,
    }
)
_UNKNOWN_STATUSES: Final = frozenset(
    {
        ResultStatus.UNKNOWN,
        ResultStatus.CANDIDATE,
    }
)

_TRUST_FROM_EVIDENCE: Final[dict[EvidenceAuthority, ProofTrustLevel]] = {
    EvidenceAuthority.AUTHORITATIVE: ProofTrustLevel.AUTHORITATIVE,
    EvidenceAuthority.INDEPENDENTLY_CHECKABLE: ProofTrustLevel.INDEPENDENTLY_CHECKABLE,
    EvidenceAuthority.BOUNDED: ProofTrustLevel.BOUNDED,
    EvidenceAuthority.ADVISORY: ProofTrustLevel.ADVISORY,
    EvidenceAuthority.NONE: ProofTrustLevel.NONE,
}

_TRUST_RANK: Final[dict[ProofTrustLevel, int]] = {
    ProofTrustLevel.NONE: 0,
    ProofTrustLevel.NON_TRUSTED: 1,
    ProofTrustLevel.ADVISORY: 2,
    ProofTrustLevel.BOUNDED: 3,
    ProofTrustLevel.INDEPENDENTLY_CHECKABLE: 4,
    ProofTrustLevel.AUTHORITATIVE: 5,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
        raise DuckDBProofStoreError(
            f"{field_name} must be {qualifier}non-empty trimmed string without NUL"
        )
    return value


def _enum(value: object, enum_type: type[Any], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise DuckDBProofStoreError(
            f"{field_name} must be one of {choices}"
        ) from error


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise DuckDBProofStoreError("floating-point values must be finite")
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
    raise DuckDBProofStoreError(
        f"value of type {type(value).__name__} is not JSON-serializable "
        "for the proof store"
    )


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        _json_ready(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def proof_store_content_digest(value: Any) -> str:
    """Return a ``sha256:<hex>`` digest of canonical JSON for proof-store identity."""

    return "sha256:" + __import__("hashlib").sha256(_canonical_bytes(value)).hexdigest()


def _digest_field(value: Any, field_name: str) -> str:
    """Normalize a digest or digestable value to ``sha256:<hex>``."""

    if isinstance(value, str) and value.startswith("sha256:") and len(value) == 71:
        hex_part = value[7:]
        if all(character in "0123456789abcdef" for character in hex_part):
            return value
    if value is None:
        return proof_store_content_digest({})
    # Prefer protocol digests already in sha256: form via identity_digest.
    try:
        return identity_digest(value)
    except VerificationCacheError as error:
        raise DuckDBProofStoreError(
            f"{field_name} is not a valid digest identity"
        ) from error


def outcome_kind_for_status(status: ResultStatus | str) -> ProofOutcomeKind:
    """Map a typed backend status onto a closed proof-store outcome.

    Outcomes remain distinct: proof and counterexample never collapse into
    each other, and operational ``error`` never collapses into ``unknown``.
    """

    resolved = _enum(status, ResultStatus, "status")
    if resolved in _PROOF_STATUSES:
        return ProofOutcomeKind.PROOF
    if resolved in _COUNTEREXAMPLE_STATUSES:
        return ProofOutcomeKind.COUNTEREXAMPLE
    if resolved in _ERROR_STATUSES:
        return ProofOutcomeKind.ERROR
    if resolved in _UNKNOWN_STATUSES:
        return ProofOutcomeKind.UNKNOWN
    # Fail closed on unexpected statuses rather than guessing.
    raise DuckDBProofStoreError(
        f"status {resolved.value!r} cannot be mapped to a closed proof outcome"
    )


def trust_level_from_evidence(
    authority: EvidenceAuthority | str,
    *,
    non_trusted: bool = False,
) -> ProofTrustLevel:
    """Project evidence authority into a proof-store trust level."""

    if non_trusted:
        return ProofTrustLevel.NON_TRUSTED
    resolved = _enum(authority, EvidenceAuthority, "evidence_authority")
    return _TRUST_FROM_EVIDENCE[resolved]


def trust_rank(level: ProofTrustLevel | str) -> int:
    """Closed rank used only for non-increase checks."""

    resolved = _enum(level, ProofTrustLevel, "trust_level")
    return _TRUST_RANK[resolved]


def polarity_for_outcome(outcome: ProofOutcomeKind | str) -> CachePolarity:
    """Classify outcome polarity for dual-TTL negative caching.

    ``proof`` and ``counterexample`` are conclusive results and use the
    positive TTL.  ``unknown`` and ``error`` are non-conclusive and use the
    negative TTL — matching :func:`polarity_for_status` on the verification
    cache protocol.
    """

    resolved = _enum(outcome, ProofOutcomeKind, "outcome")
    if resolved in (ProofOutcomeKind.UNKNOWN, ProofOutcomeKind.ERROR):
        return CachePolarity.NEGATIVE
    return CachePolarity.POSITIVE


# ---------------------------------------------------------------------------
# Unified proof key (all authority dimensions retained)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UnifiedProofKey:
    """Content-addressed identity of one exact proof-cache attempt.

    Every authority dimension from the hammer obligation cache and the
    verification-cache protocol is a first-class field.  Changing any field
    produces a distinct key and forces a miss.
    """

    ir_digest: str
    property_digest: str
    assumptions_digest: str
    selected_premise_digests: tuple[str, ...]
    translator_digest: str
    solver_identities_digest: str
    toolchain_identity_digest: str
    theorem_registry_digest: str
    policy_digest: str
    resources_digest: str
    tree_digest: str
    backend_id: str
    backend_binary_digest: str
    backend_version: str
    backend_config_digest: str
    schema_version: str = UNIFIED_PROOF_KEY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "ir_digest", _digest_field(self.ir_digest, "ir_digest"))
        object.__setattr__(
            self, "property_digest", _digest_field(self.property_digest, "property_digest")
        )
        object.__setattr__(
            self,
            "assumptions_digest",
            _digest_field(self.assumptions_digest, "assumptions_digest"),
        )
        normalized_premises: list[str] = []
        for item in self.selected_premise_digests or ():
            if isinstance(item, str):
                text = item.strip().lower()
                if text.startswith("sha256:") and len(text) == 71:
                    hex_part = text[7:]
                    if all(c in "0123456789abcdef" for c in hex_part):
                        normalized_premises.append(text)
                        continue
                if len(text) == 64 and all(c in "0123456789abcdef" for c in text):
                    normalized_premises.append(f"sha256:{text}")
                    continue
            normalized_premises.append(
                _digest_field(item, "selected_premise_digests item")
            )
        premises = tuple(sorted(set(normalized_premises)))
        object.__setattr__(self, "selected_premise_digests", premises)
        object.__setattr__(
            self,
            "translator_digest",
            _digest_field(self.translator_digest, "translator_digest"),
        )
        object.__setattr__(
            self,
            "solver_identities_digest",
            _digest_field(self.solver_identities_digest, "solver_identities_digest"),
        )
        object.__setattr__(
            self,
            "toolchain_identity_digest",
            _digest_field(self.toolchain_identity_digest, "toolchain_identity_digest"),
        )
        object.__setattr__(
            self,
            "theorem_registry_digest",
            _digest_field(self.theorem_registry_digest, "theorem_registry_digest"),
        )
        object.__setattr__(
            self, "policy_digest", _digest_field(self.policy_digest, "policy_digest")
        )
        object.__setattr__(
            self,
            "resources_digest",
            _digest_field(self.resources_digest, "resources_digest"),
        )
        object.__setattr__(
            self, "tree_digest", _digest_field(self.tree_digest, "tree_digest")
        )
        object.__setattr__(self, "backend_id", _text(self.backend_id, "backend_id"))
        object.__setattr__(
            self,
            "backend_binary_digest",
            _digest_field(self.backend_binary_digest, "backend_binary_digest"),
        )
        object.__setattr__(
            self, "backend_version", _text(self.backend_version, "backend_version")
        )
        object.__setattr__(
            self,
            "backend_config_digest",
            _digest_field(self.backend_config_digest, "backend_config_digest"),
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != UNIFIED_PROOF_KEY_SCHEMA_VERSION:
            raise DuckDBProofStoreError(
                f"unsupported unified proof key schema: {self.schema_version!r}"
            )

    # -- builders ------------------------------------------------------------

    @classmethod
    def build(
        cls,
        *,
        ir: Any = None,
        property_value: Any = None,
        assumptions: Any = (),
        selected_premises: Sequence[Any] = (),
        selected_premise_digests: Sequence[Any] = (),
        translator: Any = None,
        translation: Any = None,
        solver_identities: Any = (),
        toolchain: Any = "not-applicable",
        lean_toolchain_identity: Any = None,
        theorem_registry: Any = "unspecified",
        policy: Any = None,
        resources: Any = None,
        resource_budget: Any = None,
        tree: Any = None,
        backend_id: str = "unspecified",
        backend_binary: Any = "unspecified",
        backend_version: str = "unspecified",
        backend_config: Any = None,
        obligation: Any = None,
    ) -> UnifiedProofKey:
        """Build a key from raw values, digesting each authority dimension."""

        ir_value = ir if ir is not None else obligation
        if ir_value is None:
            ir_value = {}
        translator_value = (
            translator if translator is not None else translation
        )
        if translator_value is None:
            translator_value = {}
        toolchain_value = (
            lean_toolchain_identity
            if lean_toolchain_identity is not None
            else toolchain
        )
        resource_value = resources if resources is not None else resource_budget
        if selected_premise_digests:
            premise_digests = tuple(selected_premise_digests)
        else:
            premise_digests = tuple(
                identity_digest(item) for item in selected_premises
            )
        return cls(
            ir_digest=identity_digest(ir_value),
            property_digest=identity_digest(
                {} if property_value is None else property_value
            ),
            assumptions_digest=identity_digest(assumptions),
            selected_premise_digests=premise_digests,
            translator_digest=identity_digest(translator_value),
            solver_identities_digest=identity_digest(solver_identities),
            toolchain_identity_digest=identity_digest(toolchain_value),
            theorem_registry_digest=identity_digest(theorem_registry),
            policy_digest=identity_digest({} if policy is None else policy),
            resources_digest=identity_digest(
                {} if resource_value is None else resource_value
            ),
            tree_digest=identity_digest({} if tree is None else tree),
            backend_id=backend_id,
            backend_binary_digest=identity_digest(backend_binary),
            backend_version=backend_version,
            backend_config_digest=identity_digest(
                {} if backend_config is None else backend_config
            ),
        )

    @classmethod
    def from_verification_cache_key(
        cls,
        key: VerificationCacheKey,
        *,
        selected_premise_digests: Sequence[Any] = (),
        solver_identities: Any = None,
        toolchain: Any = "not-applicable",
        theorem_registry: Any = "unspecified",
    ) -> UnifiedProofKey:
        """Lift a verification-cache key into the unified key surface.

        Extra hammer dimensions that are not first-class on the verification
        key must still be supplied (or defaulted) so no authority dimension is
        dropped from the normalized form.
        """

        if not isinstance(key, VerificationCacheKey):
            raise DuckDBProofStoreError(
                "from_verification_cache_key requires a VerificationCacheKey"
            )
        # Re-validate verification key schema fail-closed.
        if key.schema_version != VERIFICATION_CACHE_KEY_SCHEMA_VERSION:
            raise DuckDBProofStoreError(
                f"unsupported verification cache key schema: {key.schema_version!r}"
            )
        solver = (
            solver_identities
            if solver_identities is not None
            else {
                "backend_id": key.backend_id,
                "backend_binary_digest": key.backend_binary_digest,
                "backend_version": key.backend_version,
                "backend_config_digest": key.backend_config_digest,
            }
        )
        return cls(
            ir_digest=key.ir_digest,
            property_digest=key.property_digest,
            assumptions_digest=key.assumptions_digest,
            selected_premise_digests=tuple(selected_premise_digests),
            translator_digest=key.translation_digest,
            solver_identities_digest=identity_digest(solver),
            toolchain_identity_digest=identity_digest(toolchain),
            theorem_registry_digest=identity_digest(theorem_registry),
            policy_digest=key.policy_digest,
            resources_digest=key.resources_digest,
            tree_digest=key.tree_digest,
            backend_id=key.backend_id,
            backend_binary_digest=key.backend_binary_digest,
            backend_version=key.backend_version,
            backend_config_digest=key.backend_config_digest,
        )

    @classmethod
    def from_hammer_key_dict(cls, value: Mapping[str, Any]) -> UnifiedProofKey:
        """Lift a hammer :class:`ProofCacheKey` dict into the unified key."""

        if not isinstance(value, Mapping):
            raise DuckDBProofStoreError("hammer key must be a mapping")
        payload = dict(value)
        return cls(
            ir_digest=_digest_field(
                payload.get("obligation_digest", ""), "obligation_digest"
            ),
            property_digest=identity_digest(
                {"obligation": payload.get("obligation_digest", "")}
            ),
            assumptions_digest=identity_digest(
                list(payload.get("selected_premise_digests") or ())
            ),
            selected_premise_digests=tuple(
                payload.get("selected_premise_digests") or ()
            ),
            translator_digest=_digest_field(
                payload.get("translation_version_digest", ""),
                "translation_version_digest",
            ),
            solver_identities_digest=_digest_field(
                payload.get("solver_identities_digest", ""),
                "solver_identities_digest",
            ),
            toolchain_identity_digest=_digest_field(
                payload.get("lean_toolchain_identity_digest", "not-applicable"),
                "lean_toolchain_identity_digest",
            ),
            theorem_registry_digest=_digest_field(
                payload.get("theorem_registry_digest", "unspecified"),
                "theorem_registry_digest",
            ),
            policy_digest=_digest_field(
                payload.get("policy_digest", ""), "policy_digest"
            ),
            resources_digest=_digest_field(
                payload.get("resource_budget_digest", ""),
                "resource_budget_digest",
            ),
            tree_digest=identity_digest({}),
            backend_id=str(payload.get("backend_id") or "hammer"),
            backend_binary_digest=identity_digest(
                payload.get("backend_binary", "unspecified")
            ),
            backend_version=str(payload.get("backend_version") or "unspecified"),
            backend_config_digest=identity_digest(
                payload.get("backend_config") or {}
            ),
        )

    # -- identity ------------------------------------------------------------

    @property
    def premises_digest(self) -> str:
        return proof_store_content_digest(list(self.selected_premise_digests))

    @property
    def digest(self) -> str:
        return proof_store_content_digest(self.to_dict())

    @property
    def cache_key(self) -> str:
        return self.digest

    def dimension_map(self) -> Mapping[str, str]:
        """Return every authority dimension name → digest/identity.

        The closed vocabulary is exhaustively present; callers can assert that
        no dimension is missing after normalization.
        """

        mapping = {
            "ir": self.ir_digest,
            "property": self.property_digest,
            "assumptions": self.assumptions_digest,
            "premises": self.premises_digest,
            "translator": self.translator_digest,
            "solver": self.solver_identities_digest,
            "toolchain": self.toolchain_identity_digest,
            "theorem_registry": self.theorem_registry_digest,
            "policy": self.policy_digest,
            "resource": self.resources_digest,
            "tree": self.tree_digest,
            "backend_id": identity_digest(self.backend_id),
            "backend_binary": self.backend_binary_digest,
            "backend_version": identity_digest(self.backend_version),
            "backend_config": self.backend_config_digest,
        }
        missing = PROOF_AUTHORITY_DIMENSION_SET - set(mapping)
        if missing:
            raise DuckDBProofStoreAuthorityError(
                f"authority dimension(s) dropped: {', '.join(sorted(missing))}"
            )
        extra = set(mapping) - PROOF_AUTHORITY_DIMENSION_SET
        if extra:
            raise DuckDBProofStoreAuthorityError(
                f"unknown authority dimension(s): {', '.join(sorted(extra))}"
            )
        for name, value in mapping.items():
            if not value:
                raise DuckDBProofStoreAuthorityError(
                    f"authority dimension {name!r} is empty"
                )
        return MappingProxyType(mapping)

    def require_all_dimensions(self) -> UnifiedProofKey:
        """Fail closed when any authority dimension is absent or empty."""

        self.dimension_map()
        return self

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
            "selected_premise_digests": list(self.selected_premise_digests),
            "solver_identities_digest": self.solver_identities_digest,
            "theorem_registry_digest": self.theorem_registry_digest,
            "toolchain_identity_digest": self.toolchain_identity_digest,
            "translator_digest": self.translator_digest,
            "tree_digest": self.tree_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> UnifiedProofKey:
        if not isinstance(value, Mapping):
            raise DuckDBProofStoreError("unified proof key must be a mapping")
        payload = dict(value)
        unknown = sorted(set(payload) - set(_UNIFIED_KEY_FIELDS))
        if unknown:
            raise DuckDBProofStoreError(
                f"unknown unified proof key field(s): {', '.join(unknown)}"
            )
        return cls(
            ir_digest=payload.get("ir_digest", ""),
            property_digest=payload.get("property_digest", ""),
            assumptions_digest=payload.get("assumptions_digest", ""),
            selected_premise_digests=tuple(
                payload.get("selected_premise_digests") or ()
            ),
            translator_digest=payload.get("translator_digest", ""),
            solver_identities_digest=payload.get("solver_identities_digest", ""),
            toolchain_identity_digest=payload.get(
                "toolchain_identity_digest", ""
            ),
            theorem_registry_digest=payload.get("theorem_registry_digest", ""),
            policy_digest=payload.get("policy_digest", ""),
            resources_digest=payload.get("resources_digest", ""),
            tree_digest=payload.get("tree_digest", ""),
            backend_id=payload.get("backend_id", ""),
            backend_binary_digest=payload.get("backend_binary_digest", ""),
            backend_version=payload.get("backend_version", ""),
            backend_config_digest=payload.get("backend_config_digest", ""),
            schema_version=payload.get(
                "schema_version", UNIFIED_PROOF_KEY_SCHEMA_VERSION
            ),
        )

    def to_verification_cache_key(self) -> VerificationCacheKey:
        """Project into :class:`VerificationCacheKey` without dropping authority.

        Extended hammer dimensions (premises, solver identities, toolchain,
        theorem registry) are bound into verification-key fields so the
        projected digest still changes when any of them change.  When those
        extensions are at their protocol defaults, fields pass through so a
        pure verification-cache key round-trips without rebinding.  The full
        unified key remains authoritative in the store tables.
        """

        self.require_all_dimensions()
        # Bind premises into assumptions so premise swaps miss the cache.
        if self.selected_premise_digests:
            assumptions_binding = content_digest(
                {
                    "assumptions_digest": self.assumptions_digest,
                    "premises": list(self.selected_premise_digests),
                }
            )
        else:
            assumptions_binding = self.assumptions_digest

        default_solver = identity_digest(
            {
                "backend_id": self.backend_id,
                "backend_binary_digest": self.backend_binary_digest,
                "backend_version": self.backend_version,
                "backend_config_digest": self.backend_config_digest,
            }
        )
        default_toolchain = identity_digest("not-applicable")
        default_registry = identity_digest("unspecified")
        has_extended = (
            self.solver_identities_digest != default_solver
            or self.toolchain_identity_digest != default_toolchain
            or self.theorem_registry_digest != default_registry
        )
        if has_extended:
            # Bind solver + toolchain + theorem registry into tree so they
            # affect exact identity without inventing verification-key fields.
            tree_binding = content_digest(
                {
                    "solver_identities_digest": self.solver_identities_digest,
                    "theorem_registry_digest": self.theorem_registry_digest,
                    "toolchain_identity_digest": self.toolchain_identity_digest,
                    "tree_digest": self.tree_digest,
                }
            )
            if self.solver_identities_digest != default_solver:
                backend_config_binding = content_digest(
                    {
                        "backend_config_digest": self.backend_config_digest,
                        "solver_identities_digest": self.solver_identities_digest,
                    }
                )
            else:
                backend_config_binding = self.backend_config_digest
        else:
            tree_binding = self.tree_digest
            backend_config_binding = self.backend_config_digest

        return VerificationCacheKey(
            ir_digest=self.ir_digest,
            property_digest=self.property_digest,
            assumptions_digest=assumptions_binding,
            translation_digest=self.translator_digest,
            backend_id=self.backend_id,
            backend_binary_digest=self.backend_binary_digest,
            backend_version=self.backend_version,
            backend_config_digest=backend_config_binding,
            resources_digest=self.resources_digest,
            tree_digest=tree_binding,
            policy_digest=self.policy_digest,
        )


_UNIFIED_KEY_FIELDS: Final = frozenset(
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
        "selected_premise_digests",
        "solver_identities_digest",
        "theorem_registry_digest",
        "toolchain_identity_digest",
        "translator_digest",
        "tree_digest",
    }
)


# ---------------------------------------------------------------------------
# Immutable envelope reference
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ImmutableEnvelopeReference:
    """Storage-neutral pointer to immutable envelope bytes.

    Identity is the content digest / CID; location hints are never authority.
    """

    content_id: str
    content_digest: str
    media_type: str = "ipld-dag-cbor"
    byte_size: int = 0
    location_hint: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "content_id", _text(self.content_id, "content_id")
        )
        object.__setattr__(
            self,
            "content_digest",
            _digest_field(self.content_digest, "content_digest"),
        )
        object.__setattr__(
            self, "media_type", _text(self.media_type, "media_type")
        )
        if not isinstance(self.byte_size, int) or isinstance(self.byte_size, bool):
            raise DuckDBProofStoreError("byte_size must be an integer")
        if self.byte_size < 0:
            raise DuckDBProofStoreError("byte_size must be non-negative")
        hint = str(self.location_hint or "").strip()
        if hint.startswith(("/", "\\")) or ".." in hint.split("/"):
            raise DuckDBProofStoreError(
                "location_hint must not be a filesystem path authority"
            )
        object.__setattr__(self, "location_hint", hint)

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        *,
        media_type: str = "bytes",
        content_id: str | None = None,
        location_hint: str = "",
    ) -> ImmutableEnvelopeReference:
        if not isinstance(data, (bytes, bytearray)):
            raise DuckDBProofStoreError("envelope bytes must be bytes")
        digest = "sha256:" + __import__("hashlib").sha256(bytes(data)).hexdigest()
        return cls(
            content_id=content_id or digest,
            content_digest=digest,
            media_type=media_type,
            byte_size=len(data),
            location_hint=location_hint,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "byte_size": self.byte_size,
            "content_digest": self.content_digest,
            "content_id": self.content_id,
            "location_hint": self.location_hint,
            "media_type": self.media_type,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ImmutableEnvelopeReference:
        if not isinstance(value, Mapping):
            raise DuckDBProofStoreError("envelope reference must be a mapping")
        return cls(
            content_id=str(value.get("content_id") or ""),
            content_digest=str(value.get("content_digest") or ""),
            media_type=str(value.get("media_type") or "ipld-dag-cbor"),
            byte_size=int(value.get("byte_size") or 0),
            location_hint=str(value.get("location_hint") or ""),
        )


# ---------------------------------------------------------------------------
# Evidence and access statistics
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProofEvidenceRecord:
    """One evidence attachment bound to a proof entry."""

    evidence_id: str
    evidence_kind: str
    evidence_authority: EvidenceAuthority
    content_digest: str
    payload: FrozenMap = field(default_factory=lambda: FrozenMap({}))
    created_at: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence_id", _text(self.evidence_id, "evidence_id")
        )
        object.__setattr__(
            self, "evidence_kind", _text(self.evidence_kind, "evidence_kind")
        )
        object.__setattr__(
            self,
            "evidence_authority",
            _enum(self.evidence_authority, EvidenceAuthority, "evidence_authority"),
        )
        object.__setattr__(
            self,
            "content_digest",
            _digest_field(self.content_digest, "content_digest"),
        )
        try:
            payload = (
                self.payload
                if isinstance(self.payload, FrozenMap)
                else FrozenMap(self.payload)
            )
        except (TypeError, ValueError) as error:
            raise DuckDBProofStoreError(
                "evidence payload must be an immutable JSON mapping"
            ) from error
        object.__setattr__(self, "payload", payload)
        if not isinstance(self.created_at, (int, float)) or self.created_at != self.created_at:
            raise DuckDBProofStoreError("created_at must be a finite number")
        object.__setattr__(self, "created_at", float(self.created_at))

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_digest": self.content_digest,
            "created_at": self.created_at,
            "evidence_authority": self.evidence_authority.value,
            "evidence_id": self.evidence_id,
            "evidence_kind": self.evidence_kind,
            "payload": self.payload.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProofEvidenceRecord:
        if not isinstance(value, Mapping):
            raise DuckDBProofStoreError("evidence record must be a mapping")
        return cls(
            evidence_id=str(value.get("evidence_id") or ""),
            evidence_kind=str(value.get("evidence_kind") or ""),
            evidence_authority=value.get(
                "evidence_authority", EvidenceAuthority.NONE.value
            ),
            content_digest=str(value.get("content_digest") or ""),
            payload=FrozenMap(value.get("payload") or {}),
            created_at=float(value.get("created_at") or 0.0),
        )


@dataclass(frozen=True, slots=True)
class AccessStatistics:
    """Per-key access counters projected into ``access_statistics``."""

    key_digest: str
    hits: int = 0
    misses: int = 0
    writes: int = 0
    rejections: int = 0
    last_access_at: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "key_digest", _text(self.key_digest, "key_digest")
        )
        for name in ("hits", "misses", "writes", "rejections"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise DuckDBProofStoreError(f"{name} must be a non-negative integer")
        if not isinstance(self.last_access_at, (int, float)) or (
            self.last_access_at != self.last_access_at
        ):
            raise DuckDBProofStoreError("last_access_at must be a finite number")
        object.__setattr__(self, "last_access_at", float(self.last_access_at))

    def to_dict(self) -> dict[str, Any]:
        return {
            "hits": self.hits,
            "key_digest": self.key_digest,
            "last_access_at": self.last_access_at,
            "misses": self.misses,
            "rejections": self.rejections,
            "writes": self.writes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AccessStatistics:
        if not isinstance(value, Mapping):
            raise DuckDBProofStoreError("access statistics must be a mapping")
        return cls(
            key_digest=str(value.get("key_digest") or ""),
            hits=int(value.get("hits") or 0),
            misses=int(value.get("misses") or 0),
            writes=int(value.get("writes") or 0),
            rejections=int(value.get("rejections") or 0),
            last_access_at=float(value.get("last_access_at") or 0.0),
        )


# ---------------------------------------------------------------------------
# Unified proof entry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UnifiedProofEntry:
    """Integrity-bound cached outcome for one :class:`UnifiedProofKey`.

    Outcomes (proof / counterexample / unknown / error) and trust levels are
    frozen at write time.  Hits revalidate integrity and never raise trust.
    """

    key: UnifiedProofKey
    outcome: ProofOutcomeKind
    trust_level: ProofTrustLevel
    status: ResultStatus
    result_authority: ResultAuthority
    evidence_authority: EvidenceAuthority
    result_payload: FrozenMap
    polarity: CachePolarity
    created_at: float
    entry_digest: str = ""
    result_id: str = ""
    diagnostics: tuple[str, ...] = ()
    evidence: tuple[ProofEvidenceRecord, ...] = ()
    envelope: ImmutableEnvelopeReference | None = None
    schema_version: str = UNIFIED_PROOF_ENTRY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.key, UnifiedProofKey):
            raise DuckDBProofStoreError("entry.key must be a UnifiedProofKey")
        self.key.require_all_dimensions()
        object.__setattr__(
            self, "outcome", _enum(self.outcome, ProofOutcomeKind, "outcome")
        )
        object.__setattr__(
            self,
            "trust_level",
            _enum(self.trust_level, ProofTrustLevel, "trust_level"),
        )
        object.__setattr__(
            self, "status", _enum(self.status, ResultStatus, "status")
        )
        object.__setattr__(
            self,
            "result_authority",
            _enum(self.result_authority, ResultAuthority, "result_authority"),
        )
        object.__setattr__(
            self,
            "evidence_authority",
            _enum(self.evidence_authority, EvidenceAuthority, "evidence_authority"),
        )
        expected_outcome = outcome_kind_for_status(self.status)
        if self.outcome is not expected_outcome:
            raise DuckDBProofStoreError(
                f"outcome {self.outcome.value!r} does not match status "
                f"{self.status.value!r} (expected {expected_outcome.value})"
            )
        expected_polarity = polarity_for_outcome(self.outcome)
        polarity = _enum(self.polarity, CachePolarity, "polarity")
        if polarity is not expected_polarity:
            raise DuckDBProofStoreError(
                f"polarity {polarity.value!r} does not match outcome "
                f"{self.outcome.value!r} (expected {expected_polarity.value})"
            )
        object.__setattr__(self, "polarity", polarity)
        # Trust must not exceed evidence authority rank (except NON_TRUSTED).
        if self.trust_level is not ProofTrustLevel.NON_TRUSTED:
            projected = trust_level_from_evidence(self.evidence_authority)
            if trust_rank(self.trust_level) > trust_rank(projected):
                raise DuckDBProofStoreAuthorityError(
                    f"trust_level {self.trust_level.value!r} exceeds evidence "
                    f"authority {self.evidence_authority.value!r}"
                )
        try:
            payload = (
                self.result_payload
                if isinstance(self.result_payload, FrozenMap)
                else FrozenMap(self.result_payload)
            )
        except (TypeError, ValueError) as error:
            raise DuckDBProofStoreError(
                "result_payload must be an immutable JSON mapping"
            ) from error
        object.__setattr__(self, "result_payload", payload)
        if not isinstance(self.created_at, (int, float)) or self.created_at != self.created_at:
            raise DuckDBProofStoreError("created_at must be a finite number")
        object.__setattr__(self, "created_at", float(self.created_at))
        object.__setattr__(
            self, "result_id", _text(self.result_id, "result_id", optional=True)
        )
        diagnostics = tuple(
            _text(item, "diagnostics item") for item in (self.diagnostics or ())
        )
        if len(diagnostics) != len(set(diagnostics)):
            raise DuckDBProofStoreError("diagnostics must not contain duplicates")
        object.__setattr__(self, "diagnostics", diagnostics)
        evidence = tuple(self.evidence or ())
        for item in evidence:
            if not isinstance(item, ProofEvidenceRecord):
                raise DuckDBProofStoreError(
                    "evidence items must be ProofEvidenceRecord instances"
                )
        object.__setattr__(self, "evidence", evidence)
        if self.envelope is not None and not isinstance(
            self.envelope, ImmutableEnvelopeReference
        ):
            raise DuckDBProofStoreError(
                "envelope must be an ImmutableEnvelopeReference or None"
            )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != UNIFIED_PROOF_ENTRY_SCHEMA_VERSION:
            raise DuckDBProofStoreError(
                f"unsupported unified proof entry schema: {self.schema_version!r}"
            )
        computed = self.compute_entry_digest()
        if self.entry_digest:
            if self.entry_digest != computed:
                raise DuckDBProofStoreIntegrityError(
                    "unified proof entry digest mismatch (tampered or stale payload)"
                )
        else:
            object.__setattr__(self, "entry_digest", computed)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "diagnostics": list(self.diagnostics),
            "envelope": None if self.envelope is None else self.envelope.to_dict(),
            "evidence": [item.to_dict() for item in self.evidence],
            "evidence_authority": self.evidence_authority.value,
            "key": self.key.to_dict(),
            "outcome": self.outcome.value,
            "polarity": self.polarity.value,
            "result_authority": self.result_authority.value,
            "result_id": self.result_id,
            "result_payload": self.result_payload.to_dict(),
            "schema_version": self.schema_version,
            "status": self.status.value,
            "trust_level": self.trust_level.value,
        }

    def compute_entry_digest(self) -> str:
        return proof_store_content_digest(self.identity_payload())

    def verify_integrity(self) -> UnifiedProofEntry:
        """Rehash the entry and fail closed on digest drift."""

        computed = self.compute_entry_digest()
        if computed != self.entry_digest:
            raise DuckDBProofStoreIntegrityError(
                "unified proof entry failed integrity rehash"
            )
        # Re-check key dimensions fail closed.
        self.key.require_all_dimensions()
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

    def require_trust_at_most(
        self, ceiling: ProofTrustLevel | str
    ) -> UnifiedProofEntry:
        limit = _enum(ceiling, ProofTrustLevel, "trust ceiling")
        if trust_rank(self.trust_level) > trust_rank(limit):
            raise DuckDBProofStoreAuthorityError(
                f"entry trust {self.trust_level.value!r} exceeds ceiling "
                f"{limit.value!r}; store cannot raise trust"
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["entry_digest"] = self.entry_digest
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> UnifiedProofEntry:
        if not isinstance(value, Mapping):
            raise DuckDBProofStoreError("unified proof entry must be a mapping")
        payload = dict(value)
        unknown = sorted(set(payload) - set(_UNIFIED_ENTRY_FIELDS))
        if unknown:
            raise DuckDBProofStoreError(
                f"unknown unified proof entry field(s): {', '.join(unknown)}"
            )
        key_payload = payload.get("key")
        if not isinstance(key_payload, Mapping):
            raise DuckDBProofStoreError("entry.key must be a mapping")
        envelope_payload = payload.get("envelope")
        envelope = (
            None
            if envelope_payload is None
            else ImmutableEnvelopeReference.from_dict(envelope_payload)
        )
        evidence_items = tuple(
            ProofEvidenceRecord.from_dict(item)
            for item in (payload.get("evidence") or ())
        )
        return cls(
            key=UnifiedProofKey.from_dict(key_payload),
            outcome=payload.get("outcome", ""),
            trust_level=payload.get("trust_level", ProofTrustLevel.NONE.value),
            status=payload.get("status", ""),
            result_authority=payload.get("result_authority", ""),
            evidence_authority=payload.get(
                "evidence_authority", EvidenceAuthority.NONE.value
            ),
            result_payload=FrozenMap(payload.get("result_payload") or {}),
            polarity=payload.get("polarity", CachePolarity.POSITIVE.value),
            created_at=float(payload.get("created_at", 0.0)),
            entry_digest=str(payload.get("entry_digest") or ""),
            result_id=str(payload.get("result_id") or ""),
            diagnostics=tuple(payload.get("diagnostics") or ()),
            evidence=evidence_items,
            envelope=envelope,
            schema_version=payload.get(
                "schema_version", UNIFIED_PROOF_ENTRY_SCHEMA_VERSION
            ),
        )

    def to_verification_cache_entry(self) -> VerificationCacheEntry:
        """Project into a verification-cache entry for protocol interop."""

        verified = self.verify_integrity()
        return VerificationCacheEntry(
            key=verified.key.to_verification_cache_key(),
            result_authority=verified.result_authority,
            status=verified.status,
            evidence_authority=verified.evidence_authority,
            result_payload=verified.result_payload,
            polarity=verified.polarity,
            created_at=verified.created_at,
            result_id=verified.result_id,
            diagnostics=verified.diagnostics,
        )

    @classmethod
    def from_verification_cache_entry(
        cls,
        entry: VerificationCacheEntry,
        *,
        key: UnifiedProofKey | None = None,
        trust_level: ProofTrustLevel | str | None = None,
        envelope: ImmutableEnvelopeReference | None = None,
        evidence: Sequence[ProofEvidenceRecord] = (),
        non_trusted: bool = False,
    ) -> UnifiedProofEntry:
        """Lift a validated verification-cache entry into the unified store."""

        if not isinstance(entry, VerificationCacheEntry):
            raise DuckDBProofStoreError(
                "from_verification_cache_entry requires a VerificationCacheEntry"
            )
        entry = entry.verify_integrity()
        unified_key = (
            key
            if key is not None
            else UnifiedProofKey.from_verification_cache_key(entry.key)
        )
        if unified_key.to_verification_cache_key().digest != entry.key.digest:
            # When an explicit unified key is supplied it must project to the
            # same verification-cache identity (exact key check, fail closed).
            if key is not None:
                raise DuckDBProofStoreIntegrityError(
                    "unified key does not project to the verification cache key"
                )
        outcome = outcome_kind_for_status(entry.status)
        if trust_level is None:
            resolved_trust = trust_level_from_evidence(
                entry.evidence_authority, non_trusted=non_trusted
            )
        else:
            resolved_trust = _enum(trust_level, ProofTrustLevel, "trust_level")
        return cls(
            key=unified_key,
            outcome=outcome,
            trust_level=resolved_trust,
            status=entry.status,
            result_authority=entry.result_authority,
            evidence_authority=entry.evidence_authority,
            result_payload=entry.result_payload,
            polarity=entry.polarity,
            created_at=entry.created_at,
            result_id=entry.result_id,
            diagnostics=entry.diagnostics,
            evidence=tuple(evidence),
            envelope=envelope,
        )

    @classmethod
    def from_typed_result(
        cls,
        key: UnifiedProofKey,
        result: TypedBackendResult,
        *,
        created_at: float | None = None,
        evidence_authority: EvidenceAuthority | str | None = None,
        trust_level: ProofTrustLevel | str | None = None,
        envelope: ImmutableEnvelopeReference | None = None,
        evidence: Sequence[ProofEvidenceRecord] = (),
        non_trusted: bool = False,
    ) -> UnifiedProofEntry:
        if not isinstance(result, TypedBackendResult):
            raise DuckDBProofStoreError(
                "from_typed_result requires a TypedBackendResult"
            )
        vkey = key.to_verification_cache_key()
        ventry = VerificationCacheEntry.from_typed_result(
            vkey,
            result,
            created_at=time.time() if created_at is None else float(created_at),
            evidence_authority=evidence_authority,
        )
        return cls.from_verification_cache_entry(
            ventry,
            key=key,
            trust_level=trust_level,
            envelope=envelope,
            evidence=evidence,
            non_trusted=non_trusted,
        )


_UNIFIED_ENTRY_FIELDS: Final = frozenset(
    {
        "created_at",
        "diagnostics",
        "entry_digest",
        "envelope",
        "evidence",
        "evidence_authority",
        "key",
        "outcome",
        "polarity",
        "result_authority",
        "result_id",
        "result_payload",
        "schema_version",
        "status",
        "trust_level",
    }
)


# ---------------------------------------------------------------------------
# Store protocol and implementation
# ---------------------------------------------------------------------------


@dataclass
class _Flight:
    event: threading.Event = field(default_factory=threading.Event)
    entry: UnifiedProofEntry | None = None
    error: BaseException | None = None


@runtime_checkable
class DuckDBProofStoreProtocol(Protocol):
    """Protocol surface for DuckDBProofStore@1."""

    @property
    def interface(self) -> str: ...

    @property
    def schema_version(self) -> str: ...

    @property
    def cache_interface(self) -> str: ...

    def lookup(
        self,
        key: UnifiedProofKey | VerificationCacheKey,
        *,
        max_trust_level: ProofTrustLevel | str | None = None,
        now: float | None = None,
    ) -> VerificationCacheLookup: ...

    def put(
        self,
        entry: UnifiedProofEntry | VerificationCacheEntry,
        *,
        now: float | None = None,
    ) -> VerificationCacheLookup: ...

    def get(
        self,
        key: UnifiedProofKey | VerificationCacheKey,
        *,
        max_trust_level: ProofTrustLevel | str | None = None,
        now: float | None = None,
    ) -> UnifiedProofEntry | None: ...

    def invalidate(self, key: UnifiedProofKey | VerificationCacheKey) -> bool: ...

    def stats(self) -> Mapping[str, int]: ...

    def access_statistics_for(
        self, key: UnifiedProofKey | VerificationCacheKey
    ) -> AccessStatistics: ...


class DuckDBProofStore:
    """In-process unified proof store implementing VerificationCacheProtocol@1.

    Entries are keyed by the unified proof-key digest.  Lookups accept either
    a :class:`UnifiedProofKey` or a :class:`VerificationCacheKey` (projected
    comparison).  Exact key and integrity checks fail closed.
    """

    def __init__(
        self,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        positive_ttl_seconds: float = DEFAULT_POSITIVE_TTL_SECONDS,
        negative_ttl_seconds: float = DEFAULT_NEGATIVE_TTL_SECONDS,
        connection: Any | None = None,
    ) -> None:
        if max_entries <= 0:
            raise DuckDBProofStoreError("max_entries must be positive")
        if positive_ttl_seconds < 0 or negative_ttl_seconds < 0:
            raise DuckDBProofStoreError("TTL values must be non-negative")
        if negative_ttl_seconds > positive_ttl_seconds and positive_ttl_seconds > 0:
            raise DuckDBProofStoreError(
                "negative_ttl_seconds cannot exceed positive_ttl_seconds"
            )
        self.max_entries = int(max_entries)
        self.positive_ttl_seconds = float(positive_ttl_seconds)
        self.negative_ttl_seconds = float(negative_ttl_seconds)
        self._connection = connection
        self._lock = threading.RLock()
        # Unified key digest -> entry
        self._entries: OrderedDict[str, UnifiedProofEntry] = OrderedDict()
        # Verification-cache key digest -> unified key digest (secondary index)
        self._verification_index: dict[str, str] = {}
        self._flights: dict[str, _Flight] = {}
        self._access: dict[str, dict[str, float | int]] = {}
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
        if connection is not None:
            self.install_schema(connection)

    @property
    def interface(self) -> str:
        return DUCKDB_PROOF_STORE_INTERFACE

    @property
    def schema_version(self) -> str:
        return DUCKDB_PROOF_STORE_SCHEMA_VERSION

    @property
    def cache_interface(self) -> str:
        return VERIFICATION_CACHE_PROTOCOL_INTERFACE

    @property
    def cache_schema_version(self) -> str:
        return VERIFICATION_CACHE_PROTOCOL_SCHEMA_VERSION

    @staticmethod
    def install_schema(connection: Any) -> None:
        """Apply proofs-catalog DDL on a DuckDB-like connection."""

        if connection is None:
            raise DuckDBProofStoreError("connection is required to install schema")
        # Split on statement boundaries; DuckDB execute accepts one statement.
        for statement in PROOFS_CATALOG_DDL.split(";"):
            body = statement.strip()
            if body:
                connection.execute(body)

    def catalog_tables(self) -> tuple[str, ...]:
        return PROOFS_CATALOG_TABLES

    def authority_dimensions(self) -> tuple[str, ...]:
        return PROOF_AUTHORITY_DIMENSIONS

    # -- key resolution ------------------------------------------------------

    def _resolve_unified_key(
        self, key: UnifiedProofKey | VerificationCacheKey
    ) -> UnifiedProofKey:
        if isinstance(key, UnifiedProofKey):
            return key.require_all_dimensions()
        if isinstance(key, VerificationCacheKey):
            # Prefer a previously stored unified key with the same projected digest.
            with self._lock:
                unified_digest = self._verification_index.get(key.digest)
                if unified_digest is not None:
                    stored = self._entries.get(unified_digest)
                    if stored is not None:
                        projected = stored.key.to_verification_cache_key()
                        if projected.digest == key.digest:
                            return stored.key
            return UnifiedProofKey.from_verification_cache_key(key)
        raise TypeError(
            "key must be a UnifiedProofKey or VerificationCacheKey"
        )

    def _access_touch(
        self,
        key_digest: str,
        *,
        hit: bool = False,
        miss: bool = False,
        write: bool = False,
        rejection: bool = False,
        now: float,
    ) -> None:
        bucket = self._access.setdefault(
            key_digest,
            {
                "hits": 0,
                "misses": 0,
                "writes": 0,
                "rejections": 0,
                "last_access_at": 0.0,
            },
        )
        if hit:
            bucket["hits"] = int(bucket["hits"]) + 1
        if miss:
            bucket["misses"] = int(bucket["misses"]) + 1
        if write:
            bucket["writes"] = int(bucket["writes"]) + 1
        if rejection:
            bucket["rejections"] = int(bucket["rejections"]) + 1
        bucket["last_access_at"] = float(now)

    def access_statistics_for(
        self, key: UnifiedProofKey | VerificationCacheKey
    ) -> AccessStatistics:
        unified = self._resolve_unified_key(key)
        with self._lock:
            bucket = self._access.get(unified.digest, {})
            return AccessStatistics(
                key_digest=unified.digest,
                hits=int(bucket.get("hits") or 0),
                misses=int(bucket.get("misses") or 0),
                writes=int(bucket.get("writes") or 0),
                rejections=int(bucket.get("rejections") or 0),
                last_access_at=float(bucket.get("last_access_at") or 0.0),
            )

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
            entry = self._entries.pop(digest, None)
            if entry is not None:
                vdigest = entry.key.to_verification_cache_key().digest
                self._verification_index.pop(vdigest, None)
            self._stats["expirations"] += 1
        while len(self._entries) > self.max_entries:
            _old_digest, old_entry = self._entries.popitem(last=False)
            vdigest = old_entry.key.to_verification_cache_key().digest
            self._verification_index.pop(vdigest, None)
            self._stats["evictions"] += 1

    def _evaluate_entry(
        self,
        entry: UnifiedProofEntry,
        key: UnifiedProofKey,
        *,
        max_trust_level: ProofTrustLevel | None,
        now: float,
        single_flight_shared: bool = False,
    ) -> VerificationCacheLookup:
        # Exact key check — fail closed on digest mismatch.
        if entry.key.digest != key.digest:
            # Also accept when the caller supplied a verification key that
            # projects to the stored key's verification digest.
            try:
                stored_v = entry.key.to_verification_cache_key()
                caller_v = key.to_verification_cache_key()
                if stored_v.digest != caller_v.digest:
                    self._stats["rejections"] += 1
                    self._access_touch(
                        key.digest, rejection=True, now=now
                    )
                    return VerificationCacheLookup(
                        entry=None,
                        hit=False,
                        usable=False,
                        reason=CacheLookupReason.STALE,
                        key_digest=key.digest,
                        single_flight_shared=single_flight_shared,
                    )
            except (DuckDBProofStoreError, VerificationCacheError):
                self._stats["rejections"] += 1
                self._access_touch(key.digest, rejection=True, now=now)
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
        except DuckDBProofStoreIntegrityError:
            self._stats["tamper_rejections"] += 1
            self._stats["rejections"] += 1
            self._access_touch(key.digest, rejection=True, now=now)
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
        if max_trust_level is not None:
            try:
                entry.require_trust_at_most(max_trust_level)
            except DuckDBProofStoreAuthorityError:
                self._stats["rejections"] += 1
                self._access_touch(key.digest, rejection=True, now=now)
                ventry = entry.to_verification_cache_entry()
                return VerificationCacheLookup(
                    entry=ventry,
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
        self._access_touch(entry.key.digest, hit=True, now=now)
        ventry = entry.to_verification_cache_entry()
        return VerificationCacheLookup(
            entry=ventry,
            hit=True,
            usable=True,
            reason=reason,
            key_digest=key.digest,
            age_seconds=entry.age_seconds(now=now),
            single_flight_shared=single_flight_shared,
        )

    def lookup(
        self,
        key: UnifiedProofKey | VerificationCacheKey,
        *,
        require_result_authority: ResultAuthority | str | None = None,
        max_evidence_authority: EvidenceAuthority | str | None = None,
        max_trust_level: ProofTrustLevel | str | None = None,
        now: float | None = None,
    ) -> VerificationCacheLookup:
        unified = self._resolve_unified_key(key)
        ceiling = (
            None
            if max_trust_level is None
            else _enum(max_trust_level, ProofTrustLevel, "max_trust_level")
        )
        # Map evidence ceiling onto trust when trust ceiling omitted.
        if ceiling is None and max_evidence_authority is not None:
            ceiling = trust_level_from_evidence(
                _enum(
                    max_evidence_authority,
                    EvidenceAuthority,
                    "max_evidence_authority",
                )
            )
        current = time.time() if now is None else float(now)
        with self._lock:
            entry = self._entries.get(unified.digest)
            if entry is None and isinstance(key, VerificationCacheKey):
                # Secondary index by verification-cache digest.
                udigest = self._verification_index.get(key.digest)
                if udigest is not None:
                    entry = self._entries.get(udigest)
                    if entry is not None:
                        unified = entry.key
            if entry is None:
                self._trim_locked(now=current)
                self._stats["misses"] += 1
                self._access_touch(unified.digest, miss=True, now=current)
                return VerificationCacheLookup(
                    entry=None,
                    hit=False,
                    usable=False,
                    reason=CacheLookupReason.MISS,
                    key_digest=unified.digest,
                )
            result = self._evaluate_entry(
                entry,
                unified,
                max_trust_level=ceiling,
                now=current,
            )
            # Optional result-authority filter (protocol parity).
            if (
                result.usable
                and result.entry is not None
                and require_result_authority is not None
            ):
                required = (
                    require_result_authority
                    if isinstance(require_result_authority, ResultAuthority)
                    else ResultAuthority(require_result_authority)
                )
                if result.entry.result_authority is not required:
                    self._stats["rejections"] += 1
                    self._access_touch(
                        unified.digest, rejection=True, now=current
                    )
                    return VerificationCacheLookup(
                        entry=result.entry,
                        hit=True,
                        usable=False,
                        reason=CacheLookupReason.AUTHORITY_MISMATCH,
                        key_digest=unified.digest,
                        age_seconds=result.age_seconds,
                    )
            if result.reason in {
                CacheLookupReason.EXPIRED,
                CacheLookupReason.TAMPERED,
                CacheLookupReason.STALE,
            }:
                self._entries.pop(unified.digest, None)
                self._verification_index.pop(
                    entry.key.to_verification_cache_key().digest, None
                )
            elif result.usable:
                self._entries.move_to_end(unified.digest)
            self._trim_locked(now=current)
            return result

    def get(
        self,
        key: UnifiedProofKey | VerificationCacheKey,
        *,
        require_result_authority: ResultAuthority | str | None = None,
        max_evidence_authority: EvidenceAuthority | str | None = None,
        max_trust_level: ProofTrustLevel | str | None = None,
        now: float | None = None,
    ) -> UnifiedProofEntry | None:
        unified = self._resolve_unified_key(key)
        result = self.lookup(
            unified,
            require_result_authority=require_result_authority,
            max_evidence_authority=max_evidence_authority,
            max_trust_level=max_trust_level,
            now=now,
        )
        if not result.usable:
            return None
        with self._lock:
            return self._entries.get(unified.digest)

    def put(
        self,
        entry: UnifiedProofEntry | VerificationCacheEntry,
        *,
        now: float | None = None,
    ) -> VerificationCacheLookup:
        if isinstance(entry, VerificationCacheEntry):
            unified_entry = UnifiedProofEntry.from_verification_cache_entry(entry)
        elif isinstance(entry, UnifiedProofEntry):
            unified_entry = entry
        else:
            raise TypeError(
                "entry must be a UnifiedProofEntry or VerificationCacheEntry"
            )
        # Round-trip revalidates integrity and JSON safety (fail closed).
        unified_entry = UnifiedProofEntry.from_dict(
            unified_entry.to_dict()
        ).verify_integrity()
        current = time.time() if now is None else float(now)
        with self._lock:
            self._entries[unified_entry.key.digest] = unified_entry
            self._entries.move_to_end(unified_entry.key.digest)
            vdigest = unified_entry.key.to_verification_cache_key().digest
            self._verification_index[vdigest] = unified_entry.key.digest
            self._trim_locked(now=current)
            self._stats["writes"] += 1
            self._access_touch(unified_entry.key.digest, write=True, now=current)
            ventry = unified_entry.to_verification_cache_entry()
            return VerificationCacheLookup(
                entry=ventry,
                hit=False,
                usable=True,
                reason=CacheLookupReason.STORED,
                key_digest=unified_entry.key.digest,
                age_seconds=unified_entry.age_seconds(now=current),
            )

    def put_result(
        self,
        key: UnifiedProofKey | VerificationCacheKey,
        result: TypedBackendResult,
        *,
        evidence_authority: EvidenceAuthority | str | None = None,
        trust_level: ProofTrustLevel | str | None = None,
        envelope: ImmutableEnvelopeReference | None = None,
        evidence: Sequence[ProofEvidenceRecord] = (),
        non_trusted: bool = False,
        now: float | None = None,
    ) -> VerificationCacheLookup:
        unified = self._resolve_unified_key(key)
        entry = UnifiedProofEntry.from_typed_result(
            unified,
            result,
            created_at=time.time() if now is None else float(now),
            evidence_authority=evidence_authority,
            trust_level=trust_level,
            envelope=envelope,
            evidence=evidence,
            non_trusted=non_trusted,
        )
        return self.put(entry, now=now)

    def get_or_compute(
        self,
        key: UnifiedProofKey | VerificationCacheKey,
        producer: Callable[
            [], UnifiedProofEntry | VerificationCacheEntry | TypedBackendResult
        ],
        *,
        require_result_authority: ResultAuthority | str | None = None,
        max_evidence_authority: EvidenceAuthority | str | None = None,
        max_trust_level: ProofTrustLevel | str | None = None,
        now: float | None = None,
    ) -> VerificationCacheLookup:
        unified = self._resolve_unified_key(key)
        if not callable(producer):
            raise TypeError("producer must be callable")

        existing = self.lookup(
            unified,
            require_result_authority=require_result_authority,
            max_evidence_authority=max_evidence_authority,
            max_trust_level=max_trust_level,
            now=now,
        )
        if existing.usable:
            return existing

        leader = False
        flight: _Flight
        with self._lock:
            recheck = self.lookup(
                unified,
                require_result_authority=require_result_authority,
                max_evidence_authority=max_evidence_authority,
                max_trust_level=max_trust_level,
                now=now,
            )
            if recheck.usable:
                return recheck
            existing_flight = self._flights.get(unified.digest)
            if existing_flight is None:
                flight = _Flight()
                self._flights[unified.digest] = flight
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
                    key_digest=unified.digest,
                    single_flight_shared=True,
                )
            current = time.time() if now is None else float(now)
            ceiling = (
                None
                if max_trust_level is None
                else _enum(max_trust_level, ProofTrustLevel, "max_trust_level")
            )
            return self._evaluate_entry(
                flight.entry,
                unified,
                max_trust_level=ceiling,
                now=current,
                single_flight_shared=True,
            )

        try:
            produced = producer()
            if isinstance(produced, TypedBackendResult):
                entry = UnifiedProofEntry.from_typed_result(
                    unified,
                    produced,
                    created_at=time.time() if now is None else float(now),
                )
            elif isinstance(produced, VerificationCacheEntry):
                entry = UnifiedProofEntry.from_verification_cache_entry(
                    produced, key=unified
                )
            elif isinstance(produced, UnifiedProofEntry):
                if produced.key.digest != unified.digest:
                    raise DuckDBProofStoreError(
                        "producer entry key does not match requested key"
                    )
                entry = produced.verify_integrity()
            else:
                raise DuckDBProofStoreError(
                    "producer must return UnifiedProofEntry, "
                    "VerificationCacheEntry, or TypedBackendResult"
                )
            stored = self.put(entry, now=now)
            flight.entry = self._entries.get(unified.digest)
            return VerificationCacheLookup(
                entry=stored.entry,
                hit=False,
                usable=True,
                reason=CacheLookupReason.STORED,
                key_digest=unified.digest,
                age_seconds=stored.age_seconds,
            )
        except BaseException as error:
            flight.error = error
            raise
        finally:
            flight.event.set()
            with self._lock:
                self._flights.pop(unified.digest, None)

    def invalidate(self, key: UnifiedProofKey | VerificationCacheKey) -> bool:
        unified = self._resolve_unified_key(key)
        with self._lock:
            removed_entry = self._entries.pop(unified.digest, None)
            if removed_entry is not None:
                vdigest = removed_entry.key.to_verification_cache_key().digest
                self._verification_index.pop(vdigest, None)
                self._stats["evictions"] += 1
                return True
            # Also try verification-index path.
            if isinstance(key, VerificationCacheKey):
                udigest = self._verification_index.pop(key.digest, None)
                if udigest is not None:
                    removed = self._entries.pop(udigest, None) is not None
                    if removed:
                        self._stats["evictions"] += 1
                    return removed
            return False

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._verification_index.clear()
            for flight in self._flights.values():
                flight.event.set()
            self._flights.clear()

    def as_verification_cache(self) -> VerificationCacheProtocol:
        """Return ``self`` typed as the verification-cache protocol surface."""

        return self  # type: ignore[return-value]


def build_unified_proof_key(**kwargs: Any) -> UnifiedProofKey:
    """Public builder matching the common keyword surface for adapters."""

    return UnifiedProofKey.build(**kwargs)


def build_duckdb_proof_store(
    *,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    positive_ttl_seconds: float = DEFAULT_POSITIVE_TTL_SECONDS,
    negative_ttl_seconds: float = DEFAULT_NEGATIVE_TTL_SECONDS,
    connection: Any | None = None,
) -> DuckDBProofStore:
    """Construct a :class:`DuckDBProofStore` with standard defaults."""

    return DuckDBProofStore(
        max_entries=max_entries,
        positive_ttl_seconds=positive_ttl_seconds,
        negative_ttl_seconds=negative_ttl_seconds,
        connection=connection,
    )


__all__ = [
    "AccessStatistics",
    "DUCKDB_PROOF_STORE_INTERFACE",
    "DUCKDB_PROOF_STORE_SCHEMA_VERSION",
    "DuckDBProofStore",
    "DuckDBProofStoreAuthorityError",
    "DuckDBProofStoreError",
    "DuckDBProofStoreIntegrityError",
    "DuckDBProofStoreProtocol",
    "ImmutableEnvelopeReference",
    "PROOFS_CATALOG_DDL",
    "PROOFS_CATALOG_NAME",
    "PROOFS_CATALOG_TABLES",
    "PROOF_AUTHORITY_DIMENSIONS",
    "PROOF_AUTHORITY_DIMENSION_SET",
    "ProofEvidenceRecord",
    "ProofOutcomeKind",
    "ProofTrustLevel",
    "UNIFIED_PROOF_ENTRY_SCHEMA_VERSION",
    "UNIFIED_PROOF_KEY_SCHEMA_VERSION",
    "UnifiedProofEntry",
    "UnifiedProofKey",
    "build_duckdb_proof_store",
    "build_unified_proof_key",
    "outcome_kind_for_status",
    "polarity_for_outcome",
    "proof_store_content_digest",
    "trust_level_from_evidence",
    "trust_rank",
]
