"""Unified DuckDB proof-cache schema and protocol (DQK-025).

Normalizes proof keys, premises, translator/solver/toolchain/theorem-registry/
policy/resource dimensions, outcomes, trust levels, evidence, access
statistics, and immutable envelope references **behind** the existing
:mod:`~ipfs_datasets_py.logic.backends.cache_protocol` surface
(``VerificationCacheProtocol@1``).

Authority dimensions from the fragmented caches (hammers, formal-verification
supervisor cache, and software-verification backends) are retained as named
fields.  Projection into :class:`VerificationCacheKey` folds the extra
dimensions into protocol digests so no authority input can change without
producing a distinct exact key.

Integrity is fail-closed:

* exact key mismatch is a miss / stale rejection;
* entry rehash drift is a tamper rejection;
* unknown or swapped outcome kinds are rejected;
* trust / evidence authority can never be raised on a hit.

Importing this module is inert with respect to DuckDB: schema SQL is pure
text.  Opening a store is explicit via :class:`DuckDBProofStore`.
"""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final, Protocol, runtime_checkable

from ..backends.cache_protocol import (
    DEFAULT_MAX_ENTRIES,
    DEFAULT_NEGATIVE_TTL_SECONDS,
    DEFAULT_POSITIVE_TTL_SECONDS,
    VERIFICATION_CACHE_PROTOCOL_INTERFACE,
    VERIFICATION_CACHE_PROTOCOL_SCHEMA_VERSION,
    CacheLookupReason,
    CachePolarity,
    ExactVerificationCache,
    VerificationCacheAuthorityError,
    VerificationCacheEntry,
    VerificationCacheError,
    VerificationCacheIntegrityError,
    VerificationCacheKey,
    VerificationCacheLookup,
    VerificationCacheProtocol,
    authority_rank,
    content_digest,
    identity_digest,
    polarity_for_status,
)
from ..backends.results import (
    ResultAuthority,
    ResultStatus,
    TypedBackendResult,
)
from ..families.models import EvidenceAuthority
from ..ir_core.claims import FrozenMap
from ..proof_corpus.backend_store import (
    BackendReceiptKind,
    receipt_kind_for_status,
)

# ---------------------------------------------------------------------------
# Schema identities
# ---------------------------------------------------------------------------

DUCKDB_PROOF_STORE_INTERFACE: Final = "DuckDBProofStore@1"
DUCKDB_PROOF_STORE_SCHEMA_VERSION: Final = "duckdb-proof-store/v1"
PROOF_KEY_SCHEMA_VERSION: Final = "duckdb-proof-key/v1"
PROOF_ENTRY_SCHEMA_VERSION: Final = "duckdb-proof-entry/v1"
PROOF_CATALOG_NAMESPACE: Final = "proofs"

# Every authority dimension retained by the unified key (acceptance: none dropped).
PROOF_AUTHORITY_DIMENSIONS: Final[tuple[str, ...]] = (
    "obligation",
    "premises",
    "translator",
    "solver",
    "kernel",
    "toolchain",
    "theorem_registry",
    "policy",
    "resources",
    "tree",
    "property",
    "backend_binary",
    "backend_version",
    "backend_config",
)

# Principal tables declared for the proofs catalog (control-plane plan).
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

PROOFS_CATALOG_DDL: Final[str] = """
CREATE TABLE IF NOT EXISTS proof_keys (
    key_digest VARCHAR PRIMARY KEY,
    schema_version VARCHAR NOT NULL,
    key_json VARCHAR NOT NULL,
    verification_cache_key_digest VARCHAR NOT NULL,
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
    premise_index INTEGER NOT NULL,
    premise_digest VARCHAR NOT NULL,
    premise_json VARCHAR NOT NULL,
    PRIMARY KEY (key_digest, premise_index)
);
CREATE TABLE IF NOT EXISTS proof_entries (
    entry_digest VARCHAR PRIMARY KEY,
    key_digest VARCHAR NOT NULL,
    outcome VARCHAR NOT NULL,
    trust_level VARCHAR NOT NULL,
    evidence_authority VARCHAR NOT NULL,
    result_authority VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    polarity VARCHAR NOT NULL,
    entry_json VARCHAR NOT NULL,
    envelope_ref_json VARCHAR NOT NULL,
    created_at DOUBLE NOT NULL,
    expires_at DOUBLE
);
CREATE INDEX IF NOT EXISTS proof_entries_key_idx ON proof_entries(key_digest);
CREATE TABLE IF NOT EXISTS solver_runs (
    run_id VARCHAR PRIMARY KEY,
    key_digest VARCHAR NOT NULL,
    entry_digest VARCHAR NOT NULL,
    solver_digest VARCHAR NOT NULL,
    backend_id VARCHAR NOT NULL,
    backend_version VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    run_json VARCHAR NOT NULL,
    created_at DOUBLE NOT NULL
);
CREATE TABLE IF NOT EXISTS proof_evidence (
    evidence_id VARCHAR PRIMARY KEY,
    entry_digest VARCHAR NOT NULL,
    evidence_kind VARCHAR NOT NULL,
    evidence_authority VARCHAR NOT NULL,
    evidence_digest VARCHAR NOT NULL,
    evidence_json VARCHAR NOT NULL,
    created_at DOUBLE NOT NULL
);
CREATE TABLE IF NOT EXISTS attestations (
    attestation_id VARCHAR PRIMARY KEY,
    entry_digest VARCHAR NOT NULL,
    attestation_kind VARCHAR NOT NULL,
    attestation_digest VARCHAR NOT NULL,
    attestation_json VARCHAR NOT NULL,
    created_at DOUBLE NOT NULL
);
CREATE TABLE IF NOT EXISTS invalidations (
    invalidation_id VARCHAR PRIMARY KEY,
    key_digest VARCHAR NOT NULL,
    reason VARCHAR NOT NULL,
    created_at DOUBLE NOT NULL
);
CREATE TABLE IF NOT EXISTS revocations (
    revocation_id VARCHAR PRIMARY KEY,
    entry_digest VARCHAR NOT NULL,
    reason VARCHAR NOT NULL,
    created_at DOUBLE NOT NULL
);
CREATE TABLE IF NOT EXISTS singleflight_claims (
    key_digest VARCHAR PRIMARY KEY,
    owner_id VARCHAR NOT NULL,
    fencing_token BIGINT NOT NULL,
    acquired_at DOUBLE NOT NULL,
    expires_at DOUBLE NOT NULL
);
CREATE TABLE IF NOT EXISTS access_statistics (
    key_digest VARCHAR PRIMARY KEY,
    hits BIGINT NOT NULL DEFAULT 0,
    misses BIGINT NOT NULL DEFAULT 0,
    writes BIGINT NOT NULL DEFAULT 0,
    rejections BIGINT NOT NULL DEFAULT 0,
    last_accessed_at DOUBLE NOT NULL DEFAULT 0
);
""".strip()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DuckDBProofStoreError(ValueError):
    """Raised when a proof-store key, entry, or operation is invalid."""


class DuckDBProofStoreIntegrityError(DuckDBProofStoreError):
    """Raised when a stored entry fails integrity or exact-key checks."""


class DuckDBProofStoreAuthorityError(DuckDBProofStoreError):
    """Raised when a caller attempts to raise or substitute trust/authority."""


# ---------------------------------------------------------------------------
# Outcomes / trust
# ---------------------------------------------------------------------------


class ProofOutcome(StrEnum):
    """Closed, mutually exclusive proof-cache outcomes.

    Acceptance: proof / counterexample / unknown / error remain distinct.
    """

    PROOF = "proof"
    COUNTEREXAMPLE = "counterexample"
    UNKNOWN = "unknown"
    ERROR = "error"


class ProofTrustLevel(StrEnum):
    """Trust classification frozen at write time; hits never raise it."""

    NONE = "none"
    ADVISORY = "advisory"
    BOUNDED = "bounded"
    INDEPENDENTLY_CHECKABLE = "independently_checkable"
    AUTHORITATIVE = "authoritative"


_TRUST_RANK: Final[dict[ProofTrustLevel, int]] = {
    ProofTrustLevel.NONE: 0,
    ProofTrustLevel.ADVISORY: 1,
    ProofTrustLevel.BOUNDED: 2,
    ProofTrustLevel.INDEPENDENTLY_CHECKABLE: 3,
    ProofTrustLevel.AUTHORITATIVE: 4,
}

_OUTCOME_TO_RECEIPT: Final[dict[ProofOutcome, BackendReceiptKind]] = {
    ProofOutcome.PROOF: BackendReceiptKind.PROOF,
    ProofOutcome.COUNTEREXAMPLE: BackendReceiptKind.COUNTEREXAMPLE,
    ProofOutcome.UNKNOWN: BackendReceiptKind.NEGATIVE,
    ProofOutcome.ERROR: BackendReceiptKind.NEGATIVE,
}

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
        ResultStatus.UNSUPPORTED,
        ResultStatus.UNAVAILABLE,
        ResultStatus.RECONSTRUCTION_FAILED,
        ResultStatus.ATTESTATION_INVALID,
        ResultStatus.TIMEOUT,
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
        f"value of type {type(value).__name__} is not JSON-serializable for proof identity"
    )


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        _json_ready(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def proof_content_digest(value: Any) -> str:
    """Return a ``sha256:<hex>`` digest of canonical JSON."""

    return "sha256:" + __import__("hashlib").sha256(_canonical_bytes(value)).hexdigest()


def trust_rank(trust: ProofTrustLevel | str) -> int:
    resolved = _enum(trust, ProofTrustLevel, "trust_level")
    return _TRUST_RANK[resolved]


def trust_level_from_evidence_authority(
    authority: EvidenceAuthority | str,
) -> ProofTrustLevel:
    resolved = (
        authority
        if isinstance(authority, EvidenceAuthority)
        else EvidenceAuthority(str(authority))
    )
    return ProofTrustLevel(resolved.value)


def evidence_authority_from_trust(
    trust: ProofTrustLevel | str,
) -> EvidenceAuthority:
    resolved = _enum(trust, ProofTrustLevel, "trust_level")
    return EvidenceAuthority(resolved.value)


def outcome_for_status(status: ResultStatus | str) -> ProofOutcome:
    """Map a typed backend status onto a closed proof outcome.

    proof / counterexample / unknown / error remain distinct wire values.
    """

    resolved = (
        status if isinstance(status, ResultStatus) else ResultStatus(str(status))
    )
    if resolved in _PROOF_STATUSES:
        return ProofOutcome.PROOF
    if resolved in _COUNTEREXAMPLE_STATUSES:
        return ProofOutcome.COUNTEREXAMPLE
    if resolved in _ERROR_STATUSES:
        return ProofOutcome.ERROR
    return ProofOutcome.UNKNOWN


def outcome_for_receipt_kind(kind: BackendReceiptKind | str) -> ProofOutcome:
    resolved = (
        kind if isinstance(kind, BackendReceiptKind) else BackendReceiptKind(str(kind))
    )
    if resolved is BackendReceiptKind.PROOF:
        return ProofOutcome.PROOF
    if resolved is BackendReceiptKind.COUNTEREXAMPLE:
        return ProofOutcome.COUNTEREXAMPLE
    if resolved is BackendReceiptKind.NEGATIVE:
        # Negative receipts include both unknown and error; default unknown.
        return ProofOutcome.UNKNOWN
    return ProofOutcome.UNKNOWN


def default_status_for_outcome(outcome: ProofOutcome | str) -> ResultStatus:
    resolved = _enum(outcome, ProofOutcome, "outcome")
    if resolved is ProofOutcome.PROOF:
        return ResultStatus.PROVED
    if resolved is ProofOutcome.COUNTEREXAMPLE:
        return ResultStatus.DISPROVED
    if resolved is ProofOutcome.ERROR:
        return ResultStatus.ERROR
    return ResultStatus.UNKNOWN


# ---------------------------------------------------------------------------
# Premises / envelope / evidence
# ---------------------------------------------------------------------------


def normalize_premises(value: Any) -> tuple[Any, ...]:
    """Normalize premises to a sorted, JSON-safe tuple.

    Callers with no premises must pass an empty sequence (not ``None``).
    """

    if value is None:
        raise DuckDBProofStoreError(
            "premises is required (use an empty array when there are none)"
        )
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise DuckDBProofStoreError("premises must be an array")
    normalized = [_json_ready(item) for item in value]

    def sort_key(item: Any) -> bytes:
        return _canonical_bytes(item)

    return tuple(sorted(normalized, key=sort_key))


def premise_digests(premises: Sequence[Any]) -> tuple[str, ...]:
    return tuple(identity_digest(item) for item in normalize_premises(premises))


@dataclass(frozen=True, slots=True)
class ImmutableEnvelopeReference:
    """Storage-neutral, tamper-evident pointer to immutable proof envelope bytes.

    Does not embed filesystem paths as authority.  Identity is the digest;
    optional location hints are non-authoritative.
    """

    content_id: str
    content_digest: str
    byte_size: int = 0
    media_type: str = "application/json"
    location_hint: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "content_id", _text(self.content_id, "content_id")
        )
        digest = _text(self.content_digest, "content_digest")
        if not (
            digest.startswith("sha256:")
            and len(digest) == 71
            and all(c in "0123456789abcdef" for c in digest[7:])
        ):
            # Accept bare hex and normalize; otherwise fail closed.
            if len(digest) == 64 and all(c in "0123456789abcdef" for c in digest):
                digest = f"sha256:{digest}"
            else:
                raise DuckDBProofStoreError(
                    "content_digest must be sha256:<64 lowercase hex>"
                )
        object.__setattr__(self, "content_digest", digest)
        if not isinstance(self.byte_size, int) or isinstance(self.byte_size, bool):
            raise DuckDBProofStoreError("byte_size must be an integer")
        if self.byte_size < 0:
            raise DuckDBProofStoreError("byte_size must be non-negative")
        object.__setattr__(
            self, "media_type", _text(self.media_type, "media_type")
        )
        hint = str(self.location_hint or "").strip()
        if hint and (
            hint.startswith(("/", "\\"))
            or ".." in hint.split("/")
            or (len(hint) >= 2 and hint[1] == ":")
        ):
            raise DuckDBProofStoreError(
                "location_hint must not be a filesystem path authority"
            )
        object.__setattr__(self, "location_hint", hint)

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        *,
        media_type: str = "application/json",
        location_hint: str = "",
    ) -> ImmutableEnvelopeReference:
        if not isinstance(data, (bytes, bytearray)):
            raise DuckDBProofStoreError("envelope bytes must be bytes")
        import hashlib

        hex_digest = "sha256:" + hashlib.sha256(bytes(data)).hexdigest()
        return cls(
            content_id=hex_digest,
            content_digest=hex_digest,
            byte_size=len(data),
            media_type=media_type,
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
    def from_dict(cls, value: Mapping[str, Any] | None) -> ImmutableEnvelopeReference | None:
        if value is None or value == {}:
            return None
        if not isinstance(value, Mapping):
            raise DuckDBProofStoreError("envelope reference must be a mapping")
        return cls(
            content_id=str(value.get("content_id") or ""),
            content_digest=str(value.get("content_digest") or ""),
            byte_size=int(value.get("byte_size") or 0),
            media_type=str(value.get("media_type") or "application/json"),
            location_hint=str(value.get("location_hint") or ""),
        )

    def verify_bytes(self, data: bytes) -> None:
        import hashlib

        observed = "sha256:" + hashlib.sha256(bytes(data)).hexdigest()
        if observed != self.content_digest:
            raise DuckDBProofStoreIntegrityError(
                "envelope reference digest mismatch "
                f"(expected {self.content_digest}, observed {observed})"
            )
        if len(data) != self.byte_size:
            raise DuckDBProofStoreIntegrityError(
                f"envelope reference size mismatch "
                f"(expected {self.byte_size}, observed {len(data)})"
            )


@dataclass(frozen=True, slots=True)
class ProofEvidenceRecord:
    """One integrity-bound evidence item attached to a proof entry."""

    evidence_kind: str
    evidence_authority: EvidenceAuthority
    payload: FrozenMap
    evidence_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence_kind", _text(self.evidence_kind, "evidence_kind")
        )
        authority = (
            self.evidence_authority
            if isinstance(self.evidence_authority, EvidenceAuthority)
            else EvidenceAuthority(str(self.evidence_authority))
        )
        object.__setattr__(self, "evidence_authority", authority)
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
        computed = content_digest(
            {
                "evidence_authority": authority.value,
                "evidence_kind": self.evidence_kind,
                "payload": payload.to_dict(),
            }
        )
        if self.evidence_digest:
            if self.evidence_digest != computed:
                raise DuckDBProofStoreIntegrityError(
                    "proof evidence digest mismatch (tampered or stale payload)"
                )
        else:
            object.__setattr__(self, "evidence_digest", computed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_authority": self.evidence_authority.value,
            "evidence_digest": self.evidence_digest,
            "evidence_kind": self.evidence_kind,
            "payload": self.payload.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProofEvidenceRecord:
        if not isinstance(value, Mapping):
            raise DuckDBProofStoreError("evidence must be a mapping")
        return cls(
            evidence_kind=str(value.get("evidence_kind") or ""),
            evidence_authority=value.get(
                "evidence_authority", EvidenceAuthority.NONE.value
            ),
            payload=FrozenMap(value.get("payload") or {}),
            evidence_digest=str(value.get("evidence_digest") or ""),
        )


# ---------------------------------------------------------------------------
# Unified proof key (all authority dimensions)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NormalizedProofKey:
    """Content-addressed identity of every input capable of changing a proof.

    Dimensions retained (none may be dropped):

    * obligation, premises, property
    * translator, solver, kernel, toolchain, theorem_registry
    * policy, resources, tree
    * backend_binary, backend_version, backend_config

    The key projects onto :class:`VerificationCacheKey` without losing any
    dimension: kernel/toolchain/theorem_registry fold into the protocol's
    backend_config digest while remaining named digests here.
    """

    obligation_digest: str
    premises_digest: str
    translator_digest: str
    solver_digest: str
    kernel_digest: str
    toolchain_digest: str
    theorem_registry_digest: str
    policy_digest: str
    resources_digest: str
    tree_digest: str
    property_digest: str
    backend_id: str
    backend_binary_digest: str
    backend_version: str
    backend_config_digest: str
    premise_digests: tuple[str, ...] = ()
    schema_version: str = PROOF_KEY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "obligation_digest",
            "premises_digest",
            "translator_digest",
            "solver_digest",
            "kernel_digest",
            "toolchain_digest",
            "theorem_registry_digest",
            "policy_digest",
            "resources_digest",
            "tree_digest",
            "property_digest",
            "backend_binary_digest",
            "backend_config_digest",
        ):
            object.__setattr__(
                self, name, identity_digest(getattr(self, name))
            )
        object.__setattr__(self, "backend_id", _text(self.backend_id, "backend_id"))
        object.__setattr__(
            self, "backend_version", _text(self.backend_version, "backend_version")
        )
        premises = tuple(
            identity_digest(item) if not (
                isinstance(item, str)
                and item.startswith("sha256:")
                and len(item) == 71
            )
            else item
            for item in (self.premise_digests or ())
        )
        # Keep caller order for premises list but also expose sorted digest set.
        object.__setattr__(self, "premise_digests", premises)
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != PROOF_KEY_SCHEMA_VERSION:
            raise DuckDBProofStoreError(
                f"unsupported proof key schema: {self.schema_version!r}"
            )

    @classmethod
    def build(
        cls,
        *,
        obligation: Any,
        premises: Sequence[Any] = (),
        translator: Any = None,
        solver: Any = None,
        kernel: Any = None,
        toolchain: Any = None,
        theorem_registry: Any = None,
        policy: Any = None,
        resources: Any = None,
        tree: Any = None,
        property_value: Any = None,
        backend_id: str | None = None,
        backend_binary: Any = "unspecified",
        backend_version: str | None = None,
        backend_config: Any = None,
    ) -> NormalizedProofKey:
        """Build a key from raw values, digesting each authority dimension."""

        premises_norm = normalize_premises(premises)
        solver_payload = {} if solver is None else _json_ready(solver)
        if backend_id is None:
            if isinstance(solver_payload, Mapping) and solver_payload.get("id"):
                backend_id = str(solver_payload["id"])
            elif isinstance(solver_payload, Mapping) and solver_payload.get("backend_id"):
                backend_id = str(solver_payload["backend_id"])
            elif isinstance(solver, str) and solver.strip():
                backend_id = solver.strip()
            else:
                backend_id = "solver.unspecified"
        if backend_version is None:
            if isinstance(solver_payload, Mapping) and solver_payload.get("version"):
                backend_version = str(solver_payload["version"])
            else:
                backend_version = "unspecified"

        return cls(
            obligation_digest=identity_digest(obligation),
            premises_digest=identity_digest(premises_norm),
            premise_digests=tuple(identity_digest(item) for item in premises_norm),
            translator_digest=identity_digest(
                {} if translator is None else translator
            ),
            solver_digest=identity_digest(solver_payload),
            kernel_digest=identity_digest({} if kernel is None else kernel),
            toolchain_digest=identity_digest(
                {} if toolchain is None else toolchain
            ),
            theorem_registry_digest=identity_digest(
                {} if theorem_registry is None else theorem_registry
            ),
            policy_digest=identity_digest({} if policy is None else policy),
            resources_digest=identity_digest(
                {} if resources is None else resources
            ),
            tree_digest=identity_digest({} if tree is None else tree),
            property_digest=identity_digest(
                {} if property_value is None else property_value
            ),
            backend_id=backend_id,
            backend_binary_digest=identity_digest(backend_binary),
            backend_version=backend_version,
            backend_config_digest=identity_digest(
                {} if backend_config is None else backend_config
            ),
        )

    @property
    def digest(self) -> str:
        return content_digest(self.to_dict())

    @property
    def cache_key(self) -> str:
        return self.digest

    def dimension_map(self) -> dict[str, str]:
        """Named digest for every retained authority dimension."""

        return {
            "obligation": self.obligation_digest,
            "premises": self.premises_digest,
            "translator": self.translator_digest,
            "solver": self.solver_digest,
            "kernel": self.kernel_digest,
            "toolchain": self.toolchain_digest,
            "theorem_registry": self.theorem_registry_digest,
            "policy": self.policy_digest,
            "resources": self.resources_digest,
            "tree": self.tree_digest,
            "property": self.property_digest,
            "backend_binary": self.backend_binary_digest,
            "backend_version": content_digest(self.backend_version),
            "backend_config": self.backend_config_digest,
        }

    def to_verification_cache_key(self) -> VerificationCacheKey:
        """Project onto VerificationCacheKey without dropping authority inputs.

        Kernel, toolchain, and theorem-registry are folded into
        ``backend_config_digest`` together with the solver-facing config so
        changing any of them yields a distinct protocol key.  Named digests
        remain on this object for dimension tables and exact rebinding.
        """

        folded_config = {
            "backend_config": self.backend_config_digest,
            "kernel": self.kernel_digest,
            "solver": self.solver_digest,
            "theorem_registry": self.theorem_registry_digest,
            "toolchain": self.toolchain_digest,
        }
        return VerificationCacheKey(
            ir_digest=self.obligation_digest,
            property_digest=self.property_digest,
            assumptions_digest=self.premises_digest,
            translation_digest=self.translator_digest,
            backend_id=self.backend_id,
            backend_binary_digest=self.backend_binary_digest,
            backend_version=self.backend_version,
            backend_config_digest=identity_digest(folded_config),
            resources_digest=self.resources_digest,
            tree_digest=self.tree_digest,
            policy_digest=self.policy_digest,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_binary_digest": self.backend_binary_digest,
            "backend_config_digest": self.backend_config_digest,
            "backend_id": self.backend_id,
            "backend_version": self.backend_version,
            "kernel_digest": self.kernel_digest,
            "obligation_digest": self.obligation_digest,
            "policy_digest": self.policy_digest,
            "premise_digests": list(self.premise_digests),
            "premises_digest": self.premises_digest,
            "property_digest": self.property_digest,
            "resources_digest": self.resources_digest,
            "schema_version": self.schema_version,
            "solver_digest": self.solver_digest,
            "theorem_registry_digest": self.theorem_registry_digest,
            "toolchain_digest": self.toolchain_digest,
            "translator_digest": self.translator_digest,
            "tree_digest": self.tree_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> NormalizedProofKey:
        if not isinstance(value, Mapping):
            raise DuckDBProofStoreError("proof key must be a mapping")
        payload = dict(value)
        unknown = sorted(set(payload) - set(_PROOF_KEY_FIELDS))
        if unknown:
            raise DuckDBProofStoreError(
                f"unknown proof key field(s): {', '.join(unknown)}"
            )
        return cls(
            obligation_digest=payload.get("obligation_digest", ""),
            premises_digest=payload.get("premises_digest", ""),
            premise_digests=tuple(payload.get("premise_digests") or ()),
            translator_digest=payload.get("translator_digest", ""),
            solver_digest=payload.get("solver_digest", ""),
            kernel_digest=payload.get("kernel_digest", ""),
            toolchain_digest=payload.get("toolchain_digest", ""),
            theorem_registry_digest=payload.get("theorem_registry_digest", ""),
            policy_digest=payload.get("policy_digest", ""),
            resources_digest=payload.get("resources_digest", ""),
            tree_digest=payload.get("tree_digest", ""),
            property_digest=payload.get("property_digest", ""),
            backend_id=payload.get("backend_id", ""),
            backend_binary_digest=payload.get("backend_binary_digest", ""),
            backend_version=payload.get("backend_version", ""),
            backend_config_digest=payload.get("backend_config_digest", ""),
            schema_version=payload.get(
                "schema_version", PROOF_KEY_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_verification_cache_key(
        cls,
        key: VerificationCacheKey,
        *,
        kernel: Any = None,
        toolchain: Any = None,
        theorem_registry: Any = None,
        solver: Any = None,
        premise_digests_value: Sequence[str] = (),
    ) -> NormalizedProofKey:
        """Lift a protocol key into the richer proof key.

        Dimensions not present on the protocol key are filled from explicit
        kwargs or empty bindings so the full dimension set is always present.
        """

        if not isinstance(key, VerificationCacheKey):
            raise DuckDBProofStoreError(
                "from_verification_cache_key requires a VerificationCacheKey"
            )
        return cls(
            obligation_digest=key.ir_digest,
            premises_digest=key.assumptions_digest,
            premise_digests=tuple(premise_digests_value),
            translator_digest=key.translation_digest,
            solver_digest=identity_digest(
                {} if solver is None else solver
            )
            if solver is not None
            else identity_digest(
                {
                    "backend_id": key.backend_id,
                    "backend_version": key.backend_version,
                    "backend_binary_digest": key.backend_binary_digest,
                    "backend_config_digest": key.backend_config_digest,
                }
            ),
            kernel_digest=identity_digest({} if kernel is None else kernel),
            toolchain_digest=identity_digest(
                {} if toolchain is None else toolchain
            ),
            theorem_registry_digest=identity_digest(
                {} if theorem_registry is None else theorem_registry
            ),
            policy_digest=key.policy_digest,
            resources_digest=key.resources_digest,
            tree_digest=key.tree_digest,
            property_digest=key.property_digest,
            backend_id=key.backend_id,
            backend_binary_digest=key.backend_binary_digest,
            backend_version=key.backend_version,
            backend_config_digest=key.backend_config_digest,
        )


_PROOF_KEY_FIELDS: Final = frozenset(
    {
        "backend_binary_digest",
        "backend_config_digest",
        "backend_id",
        "backend_version",
        "kernel_digest",
        "obligation_digest",
        "policy_digest",
        "premise_digests",
        "premises_digest",
        "property_digest",
        "resources_digest",
        "schema_version",
        "solver_digest",
        "theorem_registry_digest",
        "toolchain_digest",
        "translator_digest",
        "tree_digest",
    }
)


# ---------------------------------------------------------------------------
# Proof entry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NormalizedProofEntry:
    """Integrity-bound cached outcome for one :class:`NormalizedProofKey`."""

    key: NormalizedProofKey
    outcome: ProofOutcome
    trust_level: ProofTrustLevel
    evidence_authority: EvidenceAuthority
    result_authority: ResultAuthority
    status: ResultStatus
    result_payload: FrozenMap
    polarity: CachePolarity
    created_at: float
    entry_digest: str = ""
    result_id: str = ""
    diagnostics: tuple[str, ...] = ()
    evidence: tuple[ProofEvidenceRecord, ...] = ()
    envelope_ref: ImmutableEnvelopeReference | None = None
    schema_version: str = PROOF_ENTRY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.key, NormalizedProofKey):
            raise DuckDBProofStoreError("entry.key must be a NormalizedProofKey")
        object.__setattr__(
            self, "outcome", _enum(self.outcome, ProofOutcome, "outcome")
        )
        object.__setattr__(
            self,
            "trust_level",
            _enum(self.trust_level, ProofTrustLevel, "trust_level"),
        )
        object.__setattr__(
            self,
            "evidence_authority",
            (
                self.evidence_authority
                if isinstance(self.evidence_authority, EvidenceAuthority)
                else EvidenceAuthority(str(self.evidence_authority))
            ),
        )
        object.__setattr__(
            self,
            "result_authority",
            (
                self.result_authority
                if isinstance(self.result_authority, ResultAuthority)
                else ResultAuthority(str(self.result_authority))
            ),
        )
        object.__setattr__(
            self,
            "status",
            (
                self.status
                if isinstance(self.status, ResultStatus)
                else ResultStatus(str(self.status))
            ),
        )
        expected_outcome = outcome_for_status(self.status)
        # Allow explicit ERROR vs UNKNOWN when status is error-class; otherwise
        # require outcome to match the status mapping.
        if self.outcome is ProofOutcome.ERROR:
            if self.status not in _ERROR_STATUSES and self.status is not ResultStatus.UNKNOWN:
                # Still allow explicit error outcome only with error-class statuses.
                if expected_outcome is not ProofOutcome.ERROR:
                    raise DuckDBProofStoreError(
                        f"outcome {self.outcome.value!r} does not match status "
                        f"{self.status.value!r}"
                    )
        elif self.outcome is not expected_outcome and not (
            self.outcome is ProofOutcome.UNKNOWN
            and expected_outcome is ProofOutcome.ERROR
        ):
            # UNKNOWN is allowed for non-error negative statuses only.
            if expected_outcome in {ProofOutcome.PROOF, ProofOutcome.COUNTEREXAMPLE}:
                raise DuckDBProofStoreError(
                    f"outcome {self.outcome.value!r} does not match status "
                    f"{self.status.value!r} (expected {expected_outcome.value})"
                )
            if (
                self.outcome is ProofOutcome.UNKNOWN
                and expected_outcome is ProofOutcome.ERROR
            ):
                # Distinct: caller chose unknown over error — reject silent swap
                # only when status is clearly an error class? Acceptance says
                # they remain distinct, so if status is ERROR we require ERROR.
                if self.status in _ERROR_STATUSES:
                    raise DuckDBProofStoreError(
                        f"outcome {self.outcome.value!r} does not match status "
                        f"{self.status.value!r} (expected {expected_outcome.value})"
                    )
        expected_polarity = polarity_for_status(self.status)
        polarity = (
            self.polarity
            if isinstance(self.polarity, CachePolarity)
            else CachePolarity(str(self.polarity))
        )
        if polarity is not expected_polarity:
            raise DuckDBProofStoreError(
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
        evidence = tuple(
            item
            if isinstance(item, ProofEvidenceRecord)
            else ProofEvidenceRecord.from_dict(item)
            for item in (self.evidence or ())
        )
        object.__setattr__(self, "evidence", evidence)
        if self.envelope_ref is not None and not isinstance(
            self.envelope_ref, ImmutableEnvelopeReference
        ):
            object.__setattr__(
                self,
                "envelope_ref",
                ImmutableEnvelopeReference.from_dict(self.envelope_ref),  # type: ignore[arg-type]
            )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != PROOF_ENTRY_SCHEMA_VERSION:
            raise DuckDBProofStoreError(
                f"unsupported proof entry schema: {self.schema_version!r}"
            )
        # Trust cannot exceed evidence authority rank.
        if trust_rank(self.trust_level) > authority_rank(self.evidence_authority):
            raise DuckDBProofStoreAuthorityError(
                f"trust_level {self.trust_level.value!r} exceeds evidence_authority "
                f"{self.evidence_authority.value!r}"
            )
        computed = self.compute_entry_digest()
        if self.entry_digest:
            if self.entry_digest != computed:
                raise DuckDBProofStoreIntegrityError(
                    "proof entry digest mismatch (tampered or stale payload)"
                )
        else:
            object.__setattr__(self, "entry_digest", computed)

    def compute_entry_digest(self) -> str:
        return content_digest(
            {
                "created_at": self.created_at,
                "diagnostics": list(self.diagnostics),
                "envelope_ref": (
                    None if self.envelope_ref is None else self.envelope_ref.to_dict()
                ),
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
        )

    def verify_integrity(self) -> NormalizedProofEntry:
        computed = self.compute_entry_digest()
        if computed != self.entry_digest:
            raise DuckDBProofStoreIntegrityError(
                "proof entry failed integrity rehash"
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

    def require_trust_at_most(
        self, ceiling: ProofTrustLevel | str
    ) -> NormalizedProofEntry:
        limit = _enum(ceiling, ProofTrustLevel, "trust_level ceiling")
        if trust_rank(self.trust_level) > trust_rank(limit):
            raise DuckDBProofStoreAuthorityError(
                f"entry trust {self.trust_level.value!r} exceeds ceiling "
                f"{limit.value!r}; cache cannot raise trust"
            )
        return self

    def to_verification_cache_entry(self) -> VerificationCacheEntry:
        """Project onto the verification-cache entry surface."""

        return VerificationCacheEntry(
            key=self.key.to_verification_cache_key(),
            result_authority=self.result_authority,
            status=self.status,
            evidence_authority=self.evidence_authority,
            result_payload=self.result_payload,
            polarity=self.polarity,
            created_at=self.created_at,
            result_id=self.result_id,
            diagnostics=self.diagnostics,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "diagnostics": list(self.diagnostics),
            "entry_digest": self.entry_digest,
            "envelope_ref": (
                None if self.envelope_ref is None else self.envelope_ref.to_dict()
            ),
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

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> NormalizedProofEntry:
        if not isinstance(value, Mapping):
            raise DuckDBProofStoreError("proof entry must be a mapping")
        payload = dict(value)
        unknown = sorted(set(payload) - set(_PROOF_ENTRY_FIELDS))
        if unknown:
            raise DuckDBProofStoreError(
                f"unknown proof entry field(s): {', '.join(unknown)}"
            )
        key_payload = payload.get("key")
        if not isinstance(key_payload, Mapping):
            raise DuckDBProofStoreError("entry.key must be a mapping")
        evidence_raw = payload.get("evidence") or ()
        return cls(
            key=NormalizedProofKey.from_dict(key_payload),
            outcome=payload.get("outcome", ProofOutcome.UNKNOWN.value),
            trust_level=payload.get("trust_level", ProofTrustLevel.NONE.value),
            evidence_authority=payload.get(
                "evidence_authority", EvidenceAuthority.NONE.value
            ),
            result_authority=payload.get(
                "result_authority", ResultAuthority.THEOREM.value
            ),
            status=payload.get("status", ResultStatus.UNKNOWN.value),
            result_payload=FrozenMap(payload.get("result_payload") or {}),
            polarity=payload.get("polarity", CachePolarity.NEGATIVE.value),
            created_at=float(payload.get("created_at", 0.0)),
            entry_digest=str(payload.get("entry_digest") or ""),
            result_id=str(payload.get("result_id") or ""),
            diagnostics=tuple(payload.get("diagnostics") or ()),
            evidence=tuple(
                ProofEvidenceRecord.from_dict(item) for item in evidence_raw
            ),
            envelope_ref=ImmutableEnvelopeReference.from_dict(
                payload.get("envelope_ref")
            ),
            schema_version=payload.get(
                "schema_version", PROOF_ENTRY_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_verification_cache_entry(
        cls,
        entry: VerificationCacheEntry,
        *,
        key: NormalizedProofKey | None = None,
        outcome: ProofOutcome | str | None = None,
        trust_level: ProofTrustLevel | str | None = None,
        evidence: Sequence[ProofEvidenceRecord | Mapping[str, Any]] = (),
        envelope_ref: ImmutableEnvelopeReference | Mapping[str, Any] | None = None,
    ) -> NormalizedProofEntry:
        if not isinstance(entry, VerificationCacheEntry):
            raise DuckDBProofStoreError(
                "from_verification_cache_entry requires a VerificationCacheEntry"
            )
        entry = entry.verify_integrity()
        proof_key = key or NormalizedProofKey.from_verification_cache_key(entry.key)
        # Ensure projection rebinds exactly when a richer key is supplied.
        if proof_key.to_verification_cache_key().digest != entry.key.digest:
            raise DuckDBProofStoreIntegrityError(
                "proof key projection does not rebind verification cache key"
            )
        resolved_outcome = (
            outcome_for_status(entry.status)
            if outcome is None
            else _enum(outcome, ProofOutcome, "outcome")
        )
        resolved_trust = (
            trust_level_from_evidence_authority(entry.evidence_authority)
            if trust_level is None
            else _enum(trust_level, ProofTrustLevel, "trust_level")
        )
        env = (
            envelope_ref
            if isinstance(envelope_ref, ImmutableEnvelopeReference) or envelope_ref is None
            else ImmutableEnvelopeReference.from_dict(envelope_ref)
        )
        return cls(
            key=proof_key,
            outcome=resolved_outcome,
            trust_level=resolved_trust,
            evidence_authority=entry.evidence_authority,
            result_authority=entry.result_authority,
            status=entry.status,
            result_payload=entry.result_payload,
            polarity=entry.polarity,
            created_at=entry.created_at,
            result_id=entry.result_id,
            diagnostics=entry.diagnostics,
            evidence=tuple(
                item
                if isinstance(item, ProofEvidenceRecord)
                else ProofEvidenceRecord.from_dict(item)
                for item in evidence
            ),
            envelope_ref=env,
        )

    @classmethod
    def from_typed_result(
        cls,
        key: NormalizedProofKey,
        result: TypedBackendResult,
        *,
        created_at: float | None = None,
        evidence_authority: EvidenceAuthority | str | None = None,
        trust_level: ProofTrustLevel | str | None = None,
        evidence: Sequence[ProofEvidenceRecord | Mapping[str, Any]] = (),
        envelope_ref: ImmutableEnvelopeReference | Mapping[str, Any] | None = None,
        outcome: ProofOutcome | str | None = None,
    ) -> NormalizedProofEntry:
        if not isinstance(result, TypedBackendResult):
            raise DuckDBProofStoreError(
                "from_typed_result requires a TypedBackendResult"
            )
        ceiling = result.translation_ceiling
        if evidence_authority is None:
            resolved_evidence = ceiling
        else:
            resolved_evidence = (
                evidence_authority
                if isinstance(evidence_authority, EvidenceAuthority)
                else EvidenceAuthority(str(evidence_authority))
            )
            if authority_rank(resolved_evidence) > authority_rank(ceiling):
                raise DuckDBProofStoreAuthorityError(
                    "store cannot raise evidence authority above the result "
                    f"translation ceiling ({ceiling.value})"
                )
        resolved_trust = (
            trust_level_from_evidence_authority(resolved_evidence)
            if trust_level is None
            else _enum(trust_level, ProofTrustLevel, "trust_level")
        )
        if trust_rank(resolved_trust) > authority_rank(resolved_evidence):
            raise DuckDBProofStoreAuthorityError(
                "trust_level cannot exceed evidence_authority"
            )
        resolved_outcome = (
            outcome_for_status(result.status)
            if outcome is None
            else _enum(outcome, ProofOutcome, "outcome")
        )
        env = (
            envelope_ref
            if isinstance(envelope_ref, ImmutableEnvelopeReference) or envelope_ref is None
            else ImmutableEnvelopeReference.from_dict(envelope_ref)
        )
        return cls(
            key=key,
            outcome=resolved_outcome,
            trust_level=resolved_trust,
            evidence_authority=resolved_evidence,
            result_authority=result.authority,
            status=result.status,
            result_payload=FrozenMap(result.to_dict()),
            polarity=polarity_for_status(result.status),
            created_at=time.time() if created_at is None else float(created_at),
            result_id=result.result_id,
            diagnostics=result.diagnostics,
            evidence=tuple(
                item
                if isinstance(item, ProofEvidenceRecord)
                else ProofEvidenceRecord.from_dict(item)
                for item in evidence
            ),
            envelope_ref=env,
        )


_PROOF_ENTRY_FIELDS: Final = frozenset(
    {
        "created_at",
        "diagnostics",
        "entry_digest",
        "envelope_ref",
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


@dataclass(frozen=True, slots=True)
class ProofStoreLookup:
    """Result of a proof-store lookup with provenance and reason code."""

    entry: NormalizedProofEntry | None
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

    def to_verification_lookup(self) -> VerificationCacheLookup:
        return VerificationCacheLookup(
            entry=(
                None
                if self.entry is None
                else self.entry.to_verification_cache_entry()
            ),
            hit=self.hit,
            usable=self.usable,
            reason=self.reason,
            key_digest=self.key_digest,
            single_flight_shared=self.single_flight_shared,
            age_seconds=self.age_seconds,
        )


@dataclass(frozen=True, slots=True)
class AccessStatistics:
    """Per-key and global access counters for the proofs catalog."""

    hits: int = 0
    misses: int = 0
    writes: int = 0
    rejections: int = 0
    expirations: int = 0
    tamper_rejections: int = 0
    evictions: int = 0
    size: int = 0
    last_accessed_at: float = 0.0

    def to_dict(self) -> dict[str, int | float]:
        return {
            "evictions": self.evictions,
            "expirations": self.expirations,
            "hits": self.hits,
            "last_accessed_at": self.last_accessed_at,
            "misses": self.misses,
            "rejections": self.rejections,
            "size": self.size,
            "tamper_rejections": self.tamper_rejections,
            "writes": self.writes,
        }


# ---------------------------------------------------------------------------
# Storage backends
# ---------------------------------------------------------------------------


@runtime_checkable
class ProofStoreBackend(Protocol):
    """Minimal persistence surface for the proofs catalog."""

    def ensure_schema(self) -> None: ...

    def put_entry(self, entry: NormalizedProofEntry) -> None: ...

    def get_entry(self, key_digest: str) -> NormalizedProofEntry | None: ...

    def delete_entry(self, key_digest: str) -> bool: ...

    def record_access(
        self,
        key_digest: str,
        *,
        hit: bool = False,
        miss: bool = False,
        write: bool = False,
        rejection: bool = False,
        now: float,
    ) -> None: ...

    def access_stats(self, key_digest: str | None = None) -> AccessStatistics: ...

    def list_key_digests(self) -> Sequence[str]: ...

    def clear(self) -> None: ...


class InMemoryProofStoreBackend:
    """Process-local backend used by unit tests and default adapters."""

    def __init__(self) -> None:
        self._entries: OrderedDict[str, NormalizedProofEntry] = OrderedDict()
        self._access: dict[str, dict[str, int | float]] = {}
        self._global = {
            "hits": 0,
            "misses": 0,
            "writes": 0,
            "rejections": 0,
            "expirations": 0,
            "tamper_rejections": 0,
            "evictions": 0,
        }
        self._lock = threading.RLock()

    def ensure_schema(self) -> None:
        return None

    def put_entry(self, entry: NormalizedProofEntry) -> None:
        entry = entry.verify_integrity()
        with self._lock:
            self._entries[entry.key.digest] = entry
            self._entries.move_to_end(entry.key.digest)

    def get_entry(self, key_digest: str) -> NormalizedProofEntry | None:
        with self._lock:
            entry = self._entries.get(key_digest)
            return None if entry is None else entry.verify_integrity()

    def delete_entry(self, key_digest: str) -> bool:
        with self._lock:
            return self._entries.pop(key_digest, None) is not None

    def record_access(
        self,
        key_digest: str,
        *,
        hit: bool = False,
        miss: bool = False,
        write: bool = False,
        rejection: bool = False,
        now: float,
    ) -> None:
        with self._lock:
            row = self._access.setdefault(
                key_digest,
                {
                    "hits": 0,
                    "misses": 0,
                    "writes": 0,
                    "rejections": 0,
                    "last_accessed_at": 0.0,
                },
            )
            if hit:
                row["hits"] = int(row["hits"]) + 1
                self._global["hits"] += 1
            if miss:
                row["misses"] = int(row["misses"]) + 1
                self._global["misses"] += 1
            if write:
                row["writes"] = int(row["writes"]) + 1
                self._global["writes"] += 1
            if rejection:
                row["rejections"] = int(row["rejections"]) + 1
                self._global["rejections"] += 1
            row["last_accessed_at"] = float(now)

    def access_stats(self, key_digest: str | None = None) -> AccessStatistics:
        with self._lock:
            if key_digest is None:
                return AccessStatistics(
                    hits=self._global["hits"],
                    misses=self._global["misses"],
                    writes=self._global["writes"],
                    rejections=self._global["rejections"],
                    expirations=self._global["expirations"],
                    tamper_rejections=self._global["tamper_rejections"],
                    evictions=self._global["evictions"],
                    size=len(self._entries),
                )
            row = self._access.get(key_digest) or {}
            return AccessStatistics(
                hits=int(row.get("hits", 0)),
                misses=int(row.get("misses", 0)),
                writes=int(row.get("writes", 0)),
                rejections=int(row.get("rejections", 0)),
                size=1 if key_digest in self._entries else 0,
                last_accessed_at=float(row.get("last_accessed_at", 0.0)),
            )

    def list_key_digests(self) -> Sequence[str]:
        with self._lock:
            return list(self._entries.keys())

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._access.clear()
            for key in self._global:
                self._global[key] = 0

    def note_expiration(self) -> None:
        with self._lock:
            self._global["expirations"] += 1

    def note_tamper(self) -> None:
        with self._lock:
            self._global["tamper_rejections"] += 1

    def note_eviction(self) -> None:
        with self._lock:
            self._global["evictions"] += 1

    def trim(self, max_entries: int, *, now: float, positive_ttl: float, negative_ttl: float) -> None:
        with self._lock:
            expired: list[str] = []
            for digest, entry in self._entries.items():
                if entry.is_expired(
                    positive_ttl_seconds=positive_ttl,
                    negative_ttl_seconds=negative_ttl,
                    now=now,
                ):
                    expired.append(digest)
            for digest in expired:
                del self._entries[digest]
                self._global["expirations"] += 1
            while len(self._entries) > max_entries:
                self._entries.popitem(last=False)
                self._global["evictions"] += 1


class DuckDBProofStoreBackend:
    """DuckDB-backed proofs catalog (lazy import of ``duckdb``)."""

    def __init__(self, path: str = ":memory:") -> None:
        try:
            import duckdb
        except ImportError as error:  # pragma: no cover - environment dependent
            raise DuckDBProofStoreError(
                "duckdb is required for DuckDBProofStoreBackend"
            ) from error
        self._duckdb = duckdb
        self.path = path
        self._lock = threading.RLock()
        self._conn = duckdb.connect(path)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with self._lock:
            self._conn.execute(PROOFS_CATALOG_DDL)

    def put_entry(self, entry: NormalizedProofEntry) -> None:
        entry = entry.verify_integrity()
        key = entry.key
        key_json = json.dumps(key.to_dict(), sort_keys=True, separators=(",", ":"))
        entry_json = json.dumps(entry.to_dict(), sort_keys=True, separators=(",", ":"))
        envelope_json = json.dumps(
            None if entry.envelope_ref is None else entry.envelope_ref.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )
        vck = key.to_verification_cache_key().digest
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.execute(
                    "DELETE FROM proof_keys WHERE key_digest = ?",
                    [key.digest],
                )
                self._conn.execute(
                    """
                    INSERT INTO proof_keys(
                        key_digest, schema_version, key_json,
                        verification_cache_key_digest, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        key.digest,
                        key.schema_version,
                        key_json,
                        vck,
                        entry.created_at,
                    ],
                )
                self._conn.execute(
                    "DELETE FROM proof_key_dimensions WHERE key_digest = ?",
                    [key.digest],
                )
                for name, digest in key.dimension_map().items():
                    self._conn.execute(
                        """
                        INSERT INTO proof_key_dimensions(
                            key_digest, dimension_name, dimension_digest
                        ) VALUES (?, ?, ?)
                        """,
                        [key.digest, name, digest],
                    )
                self._conn.execute(
                    "DELETE FROM premises WHERE key_digest = ?", [key.digest]
                )
                for index, premise_digest in enumerate(key.premise_digests):
                    self._conn.execute(
                        """
                        INSERT INTO premises(
                            key_digest, premise_index, premise_digest, premise_json
                        ) VALUES (?, ?, ?, ?)
                        """,
                        [
                            key.digest,
                            index,
                            premise_digest,
                            json.dumps(premise_digest),
                        ],
                    )
                self._conn.execute(
                    "DELETE FROM proof_entries WHERE key_digest = ?", [key.digest]
                )
                self._conn.execute(
                    """
                    INSERT INTO proof_entries(
                        entry_digest, key_digest, outcome, trust_level,
                        evidence_authority, result_authority, status, polarity,
                        entry_json, envelope_ref_json, created_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        entry.entry_digest,
                        key.digest,
                        entry.outcome.value,
                        entry.trust_level.value,
                        entry.evidence_authority.value,
                        entry.result_authority.value,
                        entry.status.value,
                        entry.polarity.value,
                        entry_json,
                        envelope_json,
                        entry.created_at,
                        None,
                    ],
                )
                self._conn.execute(
                    "DELETE FROM proof_evidence WHERE entry_digest = ?",
                    [entry.entry_digest],
                )
                for evidence in entry.evidence:
                    self._conn.execute(
                        """
                        INSERT INTO proof_evidence(
                            evidence_id, entry_digest, evidence_kind,
                            evidence_authority, evidence_digest, evidence_json,
                            created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            evidence.evidence_digest,
                            entry.entry_digest,
                            evidence.evidence_kind,
                            evidence.evidence_authority.value,
                            evidence.evidence_digest,
                            json.dumps(
                                evidence.to_dict(),
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                            entry.created_at,
                        ],
                    )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def get_entry(self, key_digest: str) -> NormalizedProofEntry | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT entry_json FROM proof_entries
                WHERE key_digest = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                [key_digest],
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row[0])
        return NormalizedProofEntry.from_dict(payload).verify_integrity()

    def delete_entry(self, key_digest: str) -> bool:
        with self._lock:
            existing = self._conn.execute(
                "SELECT 1 FROM proof_entries WHERE key_digest = ? LIMIT 1",
                [key_digest],
            ).fetchone()
            if existing is None:
                return False
            self._conn.execute(
                "DELETE FROM proof_entries WHERE key_digest = ?", [key_digest]
            )
            self._conn.execute(
                "DELETE FROM proof_keys WHERE key_digest = ?", [key_digest]
            )
            self._conn.execute(
                "DELETE FROM proof_key_dimensions WHERE key_digest = ?",
                [key_digest],
            )
            self._conn.execute(
                "DELETE FROM premises WHERE key_digest = ?", [key_digest]
            )
            return True

    def record_access(
        self,
        key_digest: str,
        *,
        hit: bool = False,
        miss: bool = False,
        write: bool = False,
        rejection: bool = False,
        now: float,
    ) -> None:
        with self._lock:
            row = self._conn.execute(
                "SELECT hits, misses, writes, rejections FROM access_statistics WHERE key_digest = ?",
                [key_digest],
            ).fetchone()
            if row is None:
                hits = 1 if hit else 0
                misses = 1 if miss else 0
                writes = 1 if write else 0
                rejections = 1 if rejection else 0
                self._conn.execute(
                    """
                    INSERT INTO access_statistics(
                        key_digest, hits, misses, writes, rejections, last_accessed_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [key_digest, hits, misses, writes, rejections, now],
                )
            else:
                hits, misses, writes, rejections = row
                self._conn.execute(
                    """
                    UPDATE access_statistics SET
                        hits = ?, misses = ?, writes = ?, rejections = ?,
                        last_accessed_at = ?
                    WHERE key_digest = ?
                    """,
                    [
                        hits + (1 if hit else 0),
                        misses + (1 if miss else 0),
                        writes + (1 if write else 0),
                        rejections + (1 if rejection else 0),
                        now,
                        key_digest,
                    ],
                )

    def access_stats(self, key_digest: str | None = None) -> AccessStatistics:
        with self._lock:
            if key_digest is None:
                row = self._conn.execute(
                    """
                    SELECT
                        COALESCE(SUM(hits), 0),
                        COALESCE(SUM(misses), 0),
                        COALESCE(SUM(writes), 0),
                        COALESCE(SUM(rejections), 0),
                        COUNT(*)
                    FROM access_statistics
                    """
                ).fetchone()
                size_row = self._conn.execute(
                    "SELECT COUNT(*) FROM proof_entries"
                ).fetchone()
                return AccessStatistics(
                    hits=int(row[0]),
                    misses=int(row[1]),
                    writes=int(row[2]),
                    rejections=int(row[3]),
                    size=int(size_row[0]),
                )
            row = self._conn.execute(
                """
                SELECT hits, misses, writes, rejections, last_accessed_at
                FROM access_statistics WHERE key_digest = ?
                """,
                [key_digest],
            ).fetchone()
            if row is None:
                return AccessStatistics()
            return AccessStatistics(
                hits=int(row[0]),
                misses=int(row[1]),
                writes=int(row[2]),
                rejections=int(row[3]),
                last_accessed_at=float(row[4]),
            )

    def list_key_digests(self) -> Sequence[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT key_digest FROM proof_entries"
            ).fetchall()
        return [row[0] for row in rows]

    def clear(self) -> None:
        with self._lock:
            for table in PROOFS_CATALOG_TABLES:
                self._conn.execute(f"DELETE FROM {table}")

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ---------------------------------------------------------------------------
# Store (VerificationCacheProtocol adapter)
# ---------------------------------------------------------------------------


class DuckDBProofStore:
    """Unified proof store implementing VerificationCacheProtocol@1 semantics.

    Accepts both :class:`NormalizedProofKey` and :class:`VerificationCacheKey`
    surfaces.  Exact key and integrity checks fail closed.  Access statistics
    and dimension rows are maintained for the proofs catalog.
    """

    def __init__(
        self,
        *,
        backend: ProofStoreBackend | None = None,
        path: str | None = None,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        positive_ttl_seconds: float = DEFAULT_POSITIVE_TTL_SECONDS,
        negative_ttl_seconds: float = DEFAULT_NEGATIVE_TTL_SECONDS,
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
        self._lock = threading.RLock()
        if backend is not None:
            self._backend = backend
        elif path is not None:
            self._backend = DuckDBProofStoreBackend(path)
        else:
            self._backend = InMemoryProofStoreBackend()
        self._backend.ensure_schema()
        # Protocol mirror for get/put via VerificationCacheKey.
        self._protocol_cache = ExactVerificationCache(
            max_entries=max_entries,
            positive_ttl_seconds=positive_ttl_seconds,
            negative_ttl_seconds=negative_ttl_seconds,
        )
        self._key_index: dict[str, str] = {}  # vck_digest -> proof_key_digest
        self._flights: dict[str, threading.Event] = {}
        self._flight_results: dict[str, ProofStoreLookup | BaseException] = {}

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

    @property
    def catalog_tables(self) -> tuple[str, ...]:
        return PROOFS_CATALOG_TABLES

    @property
    def authority_dimensions(self) -> tuple[str, ...]:
        return PROOF_AUTHORITY_DIMENSIONS

    @property
    def catalog_ddl(self) -> str:
        return PROOFS_CATALOG_DDL

    def stats(self) -> Mapping[str, int | float]:
        with self._lock:
            access = self._backend.access_stats()
            return {
                **access.to_dict(),
                "in_flight": len(self._flights),
            }

    def access_statistics(
        self, key: NormalizedProofKey | VerificationCacheKey | str | None = None
    ) -> AccessStatistics:
        if key is None:
            return self._backend.access_stats()
        if isinstance(key, str):
            digest = key
        elif isinstance(key, NormalizedProofKey):
            digest = key.digest
        elif isinstance(key, VerificationCacheKey):
            digest = self._key_index.get(key.digest, key.digest)
        else:
            raise TypeError("key must be NormalizedProofKey, VerificationCacheKey, or digest")
        return self._backend.access_stats(digest)

    def _coerce_key(
        self, key: NormalizedProofKey | VerificationCacheKey
    ) -> NormalizedProofKey:
        if isinstance(key, NormalizedProofKey):
            return key
        if isinstance(key, VerificationCacheKey):
            return NormalizedProofKey.from_verification_cache_key(key)
        raise TypeError("key must be NormalizedProofKey or VerificationCacheKey")

    def _evaluate_entry(
        self,
        entry: NormalizedProofEntry,
        key: NormalizedProofKey,
        *,
        require_result_authority: ResultAuthority | None,
        max_trust: ProofTrustLevel | None,
        max_evidence_authority: EvidenceAuthority | None,
        now: float,
        single_flight_shared: bool = False,
    ) -> ProofStoreLookup:
        if entry.key.digest != key.digest:
            self._backend.record_access(
                key.digest, rejection=True, now=now
            )
            return ProofStoreLookup(
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
            if isinstance(self._backend, InMemoryProofStoreBackend):
                self._backend.note_tamper()
            self._backend.record_access(key.digest, rejection=True, now=now)
            return ProofStoreLookup(
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
            if isinstance(self._backend, InMemoryProofStoreBackend):
                self._backend.note_expiration()
            return ProofStoreLookup(
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
            self._backend.record_access(key.digest, rejection=True, now=now)
            return ProofStoreLookup(
                entry=entry,
                hit=True,
                usable=False,
                reason=CacheLookupReason.AUTHORITY_MISMATCH,
                key_digest=key.digest,
                age_seconds=entry.age_seconds(now=now),
                single_flight_shared=single_flight_shared,
            )
        if max_trust is not None:
            try:
                entry.require_trust_at_most(max_trust)
            except DuckDBProofStoreAuthorityError:
                self._backend.record_access(key.digest, rejection=True, now=now)
                return ProofStoreLookup(
                    entry=entry,
                    hit=True,
                    usable=False,
                    reason=CacheLookupReason.INSUFFICIENT_AUTHORITY,
                    key_digest=key.digest,
                    age_seconds=entry.age_seconds(now=now),
                    single_flight_shared=single_flight_shared,
                )
        if max_evidence_authority is not None:
            try:
                if authority_rank(entry.evidence_authority) > authority_rank(
                    max_evidence_authority
                ):
                    raise DuckDBProofStoreAuthorityError("evidence ceiling exceeded")
            except DuckDBProofStoreAuthorityError:
                self._backend.record_access(key.digest, rejection=True, now=now)
                return ProofStoreLookup(
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
        self._backend.record_access(key.digest, hit=True, now=now)
        return ProofStoreLookup(
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
        key: NormalizedProofKey | VerificationCacheKey,
        *,
        require_result_authority: ResultAuthority | str | None = None,
        max_trust: ProofTrustLevel | str | None = None,
        max_evidence_authority: EvidenceAuthority | str | None = None,
        now: float | None = None,
    ) -> ProofStoreLookup:
        proof_key = self._coerce_key(key)
        required = (
            None
            if require_result_authority is None
            else (
                require_result_authority
                if isinstance(require_result_authority, ResultAuthority)
                else ResultAuthority(str(require_result_authority))
            )
        )
        trust_ceiling = (
            None
            if max_trust is None
            else _enum(max_trust, ProofTrustLevel, "max_trust")
        )
        evidence_ceiling = (
            None
            if max_evidence_authority is None
            else (
                max_evidence_authority
                if isinstance(max_evidence_authority, EvidenceAuthority)
                else EvidenceAuthority(str(max_evidence_authority))
            )
        )
        current = time.time() if now is None else float(now)
        with self._lock:
            if isinstance(self._backend, InMemoryProofStoreBackend):
                self._backend.trim(
                    self.max_entries,
                    now=current,
                    positive_ttl=self.positive_ttl_seconds,
                    negative_ttl=self.negative_ttl_seconds,
                )
            entry = self._backend.get_entry(proof_key.digest)
            if entry is None:
                self._backend.record_access(proof_key.digest, miss=True, now=current)
                return ProofStoreLookup(
                    entry=None,
                    hit=False,
                    usable=False,
                    reason=CacheLookupReason.MISS,
                    key_digest=proof_key.digest,
                )
            result = self._evaluate_entry(
                entry,
                proof_key,
                require_result_authority=required,
                max_trust=trust_ceiling,
                max_evidence_authority=evidence_ceiling,
                now=current,
            )
            if result.reason in {
                CacheLookupReason.EXPIRED,
                CacheLookupReason.TAMPERED,
                CacheLookupReason.STALE,
            }:
                self._backend.delete_entry(proof_key.digest)
            return result

    def get(
        self,
        key: NormalizedProofKey | VerificationCacheKey,
        *,
        require_result_authority: ResultAuthority | str | None = None,
        max_trust: ProofTrustLevel | str | None = None,
        max_evidence_authority: EvidenceAuthority | str | None = None,
        now: float | None = None,
    ) -> NormalizedProofEntry | None:
        result = self.lookup(
            key,
            require_result_authority=require_result_authority,
            max_trust=max_trust,
            max_evidence_authority=max_evidence_authority,
            now=now,
        )
        return result.entry if result.usable else None

    def put(
        self,
        entry: NormalizedProofEntry,
        *,
        now: float | None = None,
    ) -> ProofStoreLookup:
        if not isinstance(entry, NormalizedProofEntry):
            raise TypeError("entry must be a NormalizedProofEntry")
        entry = NormalizedProofEntry.from_dict(entry.to_dict()).verify_integrity()
        current = time.time() if now is None else float(now)
        with self._lock:
            self._backend.put_entry(entry)
            self._key_index[entry.key.to_verification_cache_key().digest] = (
                entry.key.digest
            )
            # Keep protocol mirror in sync for VerificationCacheProtocol callers.
            try:
                self._protocol_cache.put(
                    entry.to_verification_cache_entry(), now=current
                )
            except (
                VerificationCacheError,
                VerificationCacheIntegrityError,
                VerificationCacheAuthorityError,
            ):
                # Protocol mirror is best-effort; store remains authoritative.
                pass
            self._backend.record_access(entry.key.digest, write=True, now=current)
            if isinstance(self._backend, InMemoryProofStoreBackend):
                self._backend.trim(
                    self.max_entries,
                    now=current,
                    positive_ttl=self.positive_ttl_seconds,
                    negative_ttl=self.negative_ttl_seconds,
                )
            return ProofStoreLookup(
                entry=entry,
                hit=False,
                usable=True,
                reason=CacheLookupReason.STORED,
                key_digest=entry.key.digest,
                age_seconds=entry.age_seconds(now=current),
            )

    def put_result(
        self,
        key: NormalizedProofKey | VerificationCacheKey,
        result: TypedBackendResult,
        *,
        evidence_authority: EvidenceAuthority | str | None = None,
        trust_level: ProofTrustLevel | str | None = None,
        evidence: Sequence[ProofEvidenceRecord | Mapping[str, Any]] = (),
        envelope_ref: ImmutableEnvelopeReference | Mapping[str, Any] | None = None,
        outcome: ProofOutcome | str | None = None,
        now: float | None = None,
    ) -> ProofStoreLookup:
        proof_key = self._coerce_key(key)
        entry = NormalizedProofEntry.from_typed_result(
            proof_key,
            result,
            created_at=time.time() if now is None else float(now),
            evidence_authority=evidence_authority,
            trust_level=trust_level,
            evidence=evidence,
            envelope_ref=envelope_ref,
            outcome=outcome,
        )
        return self.put(entry, now=now)

    def put_verification_entry(
        self,
        entry: VerificationCacheEntry,
        *,
        key: NormalizedProofKey | None = None,
        outcome: ProofOutcome | str | None = None,
        trust_level: ProofTrustLevel | str | None = None,
        evidence: Sequence[ProofEvidenceRecord | Mapping[str, Any]] = (),
        envelope_ref: ImmutableEnvelopeReference | Mapping[str, Any] | None = None,
        now: float | None = None,
    ) -> ProofStoreLookup:
        """Admit a validated verification-cache entry into the proof store."""

        normalized = NormalizedProofEntry.from_verification_cache_entry(
            entry,
            key=key,
            outcome=outcome,
            trust_level=trust_level,
            evidence=evidence,
            envelope_ref=envelope_ref,
        )
        return self.put(normalized, now=now)

    def get_or_compute(
        self,
        key: NormalizedProofKey | VerificationCacheKey,
        producer: Callable[[], NormalizedProofEntry | TypedBackendResult],
        *,
        require_result_authority: ResultAuthority | str | None = None,
        max_trust: ProofTrustLevel | str | None = None,
        max_evidence_authority: EvidenceAuthority | str | None = None,
        now: float | None = None,
    ) -> ProofStoreLookup:
        proof_key = self._coerce_key(key)
        current = time.time() if now is None else float(now)
        existing = self.lookup(
            proof_key,
            require_result_authority=require_result_authority,
            max_trust=max_trust,
            max_evidence_authority=max_evidence_authority,
            now=current,
        )
        if existing.usable:
            return existing

        leader = False
        event: threading.Event
        with self._lock:
            event = self._flights.get(proof_key.digest)  # type: ignore[assignment]
            if event is None:
                event = threading.Event()
                self._flights[proof_key.digest] = event
                leader = True

        if not leader:
            event.wait(timeout=max(1.0, self.negative_ttl_seconds or 1.0))
            shared = self.lookup(
                proof_key,
                require_result_authority=require_result_authority,
                max_trust=max_trust,
                max_evidence_authority=max_evidence_authority,
                now=time.time() if now is None else float(now),
            )
            if shared.usable:
                return ProofStoreLookup(
                    entry=shared.entry,
                    hit=shared.hit,
                    usable=shared.usable,
                    reason=CacheLookupReason.SINGLE_FLIGHT_SHARED,
                    key_digest=shared.key_digest,
                    single_flight_shared=True,
                    age_seconds=shared.age_seconds,
                )
            return shared

        try:
            produced = producer()
            if isinstance(produced, TypedBackendResult):
                stored = self.put_result(proof_key, produced, now=now)
            elif isinstance(produced, NormalizedProofEntry):
                if produced.key.digest != proof_key.digest:
                    raise DuckDBProofStoreIntegrityError(
                        "producer entry key does not match request key"
                    )
                stored = self.put(produced, now=now)
            else:
                raise DuckDBProofStoreError(
                    "producer must return NormalizedProofEntry or TypedBackendResult"
                )
            return stored
        finally:
            with self._lock:
                self._flights.pop(proof_key.digest, None)
                event.set()

    def invalidate(
        self, key: NormalizedProofKey | VerificationCacheKey
    ) -> bool:
        proof_key = self._coerce_key(key)
        with self._lock:
            removed = self._backend.delete_entry(proof_key.digest)
            vck = proof_key.to_verification_cache_key()
            self._key_index.pop(vck.digest, None)
            self._protocol_cache.invalidate(vck)
            if isinstance(self._backend, InMemoryProofStoreBackend) and removed:
                self._backend.note_eviction()
            return removed

    def clear(self) -> None:
        with self._lock:
            self._backend.clear()
            self._key_index.clear()
            self._protocol_cache.clear()

    # --- VerificationCacheProtocol surface (exact key via projection) ---

    def protocol_lookup(
        self,
        key: VerificationCacheKey,
        *,
        require_result_authority: ResultAuthority | str | None = None,
        max_evidence_authority: EvidenceAuthority | str | None = None,
        now: float | None = None,
    ) -> VerificationCacheLookup:
        """Lookup through the VerificationCacheProtocol key surface.

        Exact key checks fail closed: a stored proof key must rebind to the
        same verification-cache digest or the hit is rejected as stale.
        """

        if not isinstance(key, VerificationCacheKey):
            raise TypeError("protocol_lookup requires VerificationCacheKey")
        current = time.time() if now is None else float(now)
        with self._lock:
            proof_digest = self._key_index.get(key.digest)
            if proof_digest is None:
                # Fall back to scanning for a matching projection.
                for candidate in self._backend.list_key_digests():
                    entry = self._backend.get_entry(candidate)
                    if entry is None:
                        continue
                    if entry.key.to_verification_cache_key().digest == key.digest:
                        proof_digest = entry.key.digest
                        self._key_index[key.digest] = proof_digest
                        break
            if proof_digest is None:
                self._backend.record_access(key.digest, miss=True, now=current)
                return VerificationCacheLookup(
                    entry=None,
                    hit=False,
                    usable=False,
                    reason=CacheLookupReason.MISS,
                    key_digest=key.digest,
                )
            entry = self._backend.get_entry(proof_digest)
            if entry is None:
                self._backend.record_access(key.digest, miss=True, now=current)
                return VerificationCacheLookup(
                    entry=None,
                    hit=False,
                    usable=False,
                    reason=CacheLookupReason.MISS,
                    key_digest=key.digest,
                )
            # Exact rebinding check.
            projected = entry.key.to_verification_cache_key()
            if projected.digest != key.digest:
                self._backend.record_access(key.digest, rejection=True, now=current)
                return VerificationCacheLookup(
                    entry=None,
                    hit=False,
                    usable=False,
                    reason=CacheLookupReason.STALE,
                    key_digest=key.digest,
                )
            result = self._evaluate_entry(
                entry,
                entry.key,
                require_result_authority=(
                    None
                    if require_result_authority is None
                    else (
                        require_result_authority
                        if isinstance(require_result_authority, ResultAuthority)
                        else ResultAuthority(str(require_result_authority))
                    )
                ),
                max_trust=None,
                max_evidence_authority=(
                    None
                    if max_evidence_authority is None
                    else (
                        max_evidence_authority
                        if isinstance(max_evidence_authority, EvidenceAuthority)
                        else EvidenceAuthority(str(max_evidence_authority))
                    )
                ),
                now=current,
            )
            return result.to_verification_lookup()


def build_normalized_proof_key(
    *,
    obligation: Any,
    premises: Sequence[Any] = (),
    translator: Any = None,
    solver: Any = None,
    kernel: Any = None,
    toolchain: Any = None,
    theorem_registry: Any = None,
    policy: Any = None,
    resources: Any = None,
    tree: Any = None,
    property_value: Any = None,
    backend_id: str | None = None,
    backend_binary: Any = "unspecified",
    backend_version: str | None = None,
    backend_config: Any = None,
) -> NormalizedProofKey:
    """Public builder for :class:`NormalizedProofKey`."""

    return NormalizedProofKey.build(
        obligation=obligation,
        premises=premises,
        translator=translator,
        solver=solver,
        kernel=kernel,
        toolchain=toolchain,
        theorem_registry=theorem_registry,
        policy=policy,
        resources=resources,
        tree=tree,
        property_value=property_value,
        backend_id=backend_id,
        backend_binary=backend_binary,
        backend_version=backend_version,
        backend_config=backend_config,
    )


def build_duckdb_proof_store(
    *,
    path: str | None = None,
    backend: ProofStoreBackend | None = None,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    positive_ttl_seconds: float = DEFAULT_POSITIVE_TTL_SECONDS,
    negative_ttl_seconds: float = DEFAULT_NEGATIVE_TTL_SECONDS,
) -> DuckDBProofStore:
    """Construct a :class:`DuckDBProofStore` with defaults suitable for tests."""

    return DuckDBProofStore(
        path=path,
        backend=backend,
        max_entries=max_entries,
        positive_ttl_seconds=positive_ttl_seconds,
        negative_ttl_seconds=negative_ttl_seconds,
    )


__all__ = [
    "AccessStatistics",
    "DUCKDB_PROOF_STORE_INTERFACE",
    "DUCKDB_PROOF_STORE_SCHEMA_VERSION",
    "DuckDBProofStore",
    "DuckDBProofStoreAuthorityError",
    "DuckDBProofStoreBackend",
    "DuckDBProofStoreError",
    "DuckDBProofStoreIntegrityError",
    "ImmutableEnvelopeReference",
    "InMemoryProofStoreBackend",
    "NormalizedProofEntry",
    "NormalizedProofKey",
    "PROOFS_CATALOG_DDL",
    "PROOFS_CATALOG_TABLES",
    "PROOF_AUTHORITY_DIMENSIONS",
    "PROOF_ENTRY_SCHEMA_VERSION",
    "PROOF_KEY_SCHEMA_VERSION",
    "ProofEvidenceRecord",
    "ProofOutcome",
    "ProofStoreLookup",
    "ProofTrustLevel",
    "build_duckdb_proof_store",
    "build_normalized_proof_key",
    "default_status_for_outcome",
    "evidence_authority_from_trust",
    "normalize_premises",
    "outcome_for_receipt_kind",
    "outcome_for_status",
    "premise_digests",
    "proof_content_digest",
    "trust_level_from_evidence_authority",
    "trust_rank",
]
