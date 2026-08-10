"""Unified proof service for schedulers and formal verification caches (DQK-029).

Composes the unified proof store (DQK-025), fenced single-flight coordinator
(DQK-027), and proof-corpus repository (DQK-028) so proof plans, nodes,
attempts, leases, evidence receipts, draft/attested entries, and policy gates
share one protocol **without** collapsing logic-family semantics.

Program invariants:

* Existing proof scheduler traces are deterministic and replayable.
* Authority upgrades require evidence whose projected trust covers the target.
* Logic-family adapters retain reviewed authority-key dimensions and their
  declared fallback policies (never silently drop reviewed dimensions).
* Draft publications never promote to attested/trusted authority without a
  separate evidence-backed upgrade path.
* Negative and non-trusted outcomes never become positive authority via gates.
* Importing this module is inert: no DuckDB, network, or filesystem I/O.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

from ..backends.cache_protocol import (
    CacheLookupReason,
    CachePolarity,
    VerificationCacheEntry,
    VerificationCacheKey,
    VerificationCacheLookup,
    content_digest,
)
from ..backends.results import ResultAuthority, ResultStatus, TypedBackendResult
from ..families.models import EvidenceAuthority
from ..ir_core.claims import FrozenMap
from ..proof_corpus.duckdb_repository import (
    PROOF_CORPUS_DUCKDB_REPOSITORY_INTERFACE,
    ProofCorpusDuckDBRepository,
    build_proof_corpus_duckdb_repository,
)
from .duckdb_proof_coordination import (
    DEFAULT_LEASE_SECONDS,
    DUCKDB_PROOF_COORDINATION_INTERFACE,
    AttemptStatus,
    ClaimStatus,
    CoordinationResult,
    CoordinationRole,
    DuckDBProofCoordinationError,
    DuckDBProofCoordinator,
    ProofAttemptRecord,
    ProofFenceClaim,
    build_duckdb_proof_coordinator,
)
from .duckdb_proof_migration import ProofCacheFamily
from .duckdb_proof_store import (
    DUCKDB_PROOF_STORE_INTERFACE,
    PROOF_AUTHORITY_DIMENSIONS,
    PROOF_AUTHORITY_DIMENSION_SET,
    DuckDBProofStore,
    DuckDBProofStoreAuthorityError,
    DuckDBProofStoreError,
    ImmutableEnvelopeReference,
    ProofEvidenceRecord,
    ProofOutcomeKind,
    ProofTrustLevel,
    UnifiedProofEntry,
    UnifiedProofKey,
    build_duckdb_proof_store,
    outcome_kind_for_status,
    polarity_for_outcome,
    proof_store_content_digest,
    trust_level_from_evidence,
    trust_rank,
)

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

DUCKDB_PROOF_SERVICE_INTERFACE: Final = "DuckDBProofService@1"
DUCKDB_PROOF_SERVICE_SCHEMA_VERSION: Final = "duckdb-proof-service/v1"
PROOF_PLAN_SCHEMA_VERSION: Final = "proof-service-plan/v1"
PROOF_PLAN_NODE_SCHEMA_VERSION: Final = "proof-service-plan-node/v1"
EVIDENCE_RECEIPT_SCHEMA_VERSION: Final = "proof-service-evidence-receipt/v1"
POLICY_GATE_SCHEMA_VERSION: Final = "proof-service-policy-gate/v1"
SCHEDULER_TRACE_SCHEMA_VERSION: Final = "proof-service-scheduler-trace/v1"
LOGIC_FAMILY_ADAPTER_SCHEMA_VERSION: Final = "proof-service-logic-family-adapter/v1"

DEFAULT_OWNER_ID: Final = "owner:duckdb-proof-service"
DEFAULT_MAX_TRACE_EVENTS: Final = 10_000
DEFAULT_MAX_PLANS: Final = 4_096


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DuckDBProofServiceError(ValueError):
    """Base error for the unified proof service."""


class DuckDBProofServiceAuthorityError(DuckDBProofServiceError):
    """Raised when an authority transition is refused fail-closed."""


class DuckDBProofServicePolicyError(DuckDBProofServiceError):
    """Raised when a policy gate blocks a publication or upgrade."""


class DuckDBProofServiceIntegrityError(DuckDBProofServiceError):
    """Raised when integrity / digest checks fail closed."""


class DuckDBProofServiceReplayError(DuckDBProofServiceError):
    """Raised when a scheduler trace cannot be replayed faithfully."""


class DuckDBProofServiceAdapterError(DuckDBProofServiceError):
    """Raised when a logic-family adapter refuses a key projection."""


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class PlanNodeStatus(StrEnum):
    """Lifecycle of one plan node under the service."""

    PENDING = "pending"
    CLAIMED = "claimed"
    RUNNING = "running"
    DRAFT = "draft"
    ATTESTED = "attested"
    FAILED = "failed"
    SKIPPED = "skipped"
    INVALIDATED = "invalidated"


class EntryPublicationMode(StrEnum):
    """Publication mode for a cache entry under the service."""

    DRAFT = "draft"
    ATTESTED = "attested"


class FallbackPolicy(StrEnum):
    """How adapters handle missing or incomplete unreviewed dimensions.

    Reviewed dimensions are never filled silently — only unreviewed ones may
    receive adapter-declared defaults when the policy allows it.
    """

    FAIL_CLOSED = "fail_closed"
    FILL_UNREVIEWED_DEFAULTS = "fill_unreviewed_defaults"
    QUARANTINE = "quarantine"


class PolicyGateAction(StrEnum):
    """Actions subject to the service policy gate."""

    PUBLISH_DRAFT = "publish_draft"
    PUBLISH_ATTESTED = "publish_attested"
    UPGRADE_AUTHORITY = "upgrade_authority"
    REPLAY_TRACE = "replay_trace"
    INVALIDATE = "invalidate"
    ATTACH_EVIDENCE = "attach_evidence"


class PolicyGateVerdict(StrEnum):
    """Closed set of gate outcomes."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_EVIDENCE = "require_evidence"


class TraceEventKind(StrEnum):
    """Closed vocabulary of scheduler-trace events."""

    PLAN_REGISTERED = "plan_registered"
    NODE_SCHEDULED = "node_scheduled"
    LEASE_CLAIMED = "lease_claimed"
    LEASE_RENEWED = "lease_renewed"
    LEASE_RELEASED = "lease_released"
    DRAFT_PUBLISHED = "draft_published"
    EVIDENCE_ATTACHED = "evidence_attached"
    AUTHORITY_UPGRADED = "authority_upgraded"
    ATTESTED_PUBLISHED = "attested_published"
    POLICY_GATE = "policy_gate"
    NODE_COMPLETED = "node_completed"
    NODE_FAILED = "node_failed"
    INVALIDATED = "invalidated"
    TRACE_MARK = "trace_mark"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(value: object, field_name: str, *, optional: bool = False) -> str:
    if value is None or value == "":
        if optional:
            return ""
        raise DuckDBProofServiceError(f"{field_name} must be a non-empty string")
    if not isinstance(value, str):
        raise DuckDBProofServiceError(f"{field_name} must be a string")
    text = value.strip()
    if not text:
        if optional:
            return ""
        raise DuckDBProofServiceError(f"{field_name} must be a non-empty string")
    if "\x00" in text:
        raise DuckDBProofServiceError(f"{field_name} must not contain NUL bytes")
    return text


def _enum(value: object, enum_type: type[Any], field_name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value))
    except (TypeError, ValueError) as error:
        raise DuckDBProofServiceError(
            f"{field_name} must be a valid {enum_type.__name__}"
        ) from error


def _finite_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DuckDBProofServiceError(f"{field_name} must be a finite number")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise DuckDBProofServiceError(f"{field_name} must be a finite number")
    return number


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, float) and (
            value != value or value in (float("inf"), float("-inf"))
        ):
            raise DuckDBProofServiceError("non-finite float is not JSON-safe")
        return value
    if isinstance(value, Mapping):
        return {str(k): _json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_ready(value.to_dict())
    if hasattr(value, "value"):
        return _json_ready(value.value)
    raise DuckDBProofServiceError(
        f"value of type {type(value).__name__} is not JSON-safe"
    )


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        _json_ready(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def service_content_digest(value: Any) -> str:
    """Stable ``sha256:…`` digest over a JSON-ready payload."""

    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _new_id(prefix: str) -> str:
    return f"{prefix}:{uuid.uuid4().hex}"


def _key_digest(key: UnifiedProofKey | VerificationCacheKey | str) -> str:
    if isinstance(key, UnifiedProofKey):
        return key.digest
    if isinstance(key, VerificationCacheKey):
        return key.digest
    return _text(key, "key_digest")


# ---------------------------------------------------------------------------
# Logic-family adapters (preserve reviewed keys + fallback policies)
# ---------------------------------------------------------------------------


# Per-family reviewed dimensions.  Adapters must never drop these from a
# projected key; missing reviewed material fails closed or quarantines.
_COMMON_REVIEWED: Final[tuple[str, ...]] = (
    "ir",
    "property",
    "backend_id",
    "backend_version",
    "solver",
    "policy",
)
_HAMMER_REVIEWED: Final[tuple[str, ...]] = PROOF_AUTHORITY_DIMENSIONS
_LEGAL_REVIEWED: Final[tuple[str, ...]] = (
    "ir",
    "property",
    "premises",
    "translator",
    "solver",
    "toolchain",
    "theorem_registry",
    "policy",
    "resource",
    "backend_id",
    "backend_version",
    "backend_config",
)
_INTEGRATION_REVIEWED: Final[tuple[str, ...]] = (
    "ir",
    "property",
    "assumptions",
    "translator",
    "solver",
    "policy",
    "backend_id",
    "backend_version",
    "backend_config",
)
_TDFOL_REVIEWED: Final[tuple[str, ...]] = (
    "ir",
    "property",
    "assumptions",
    "premises",
    "solver",
    "toolchain",
    "policy",
    "backend_id",
    "backend_version",
)
_CEC_REVIEWED: Final[tuple[str, ...]] = (
    "ir",
    "property",
    "solver",
    "policy",
    "resource",
    "backend_id",
    "backend_version",
    "backend_config",
)
_EXTERNAL_REVIEWED: Final[tuple[str, ...]] = (
    "ir",
    "property",
    "solver",
    "toolchain",
    "theorem_registry",
    "policy",
    "backend_id",
    "backend_binary",
    "backend_version",
    "backend_config",
)


@dataclass(frozen=True, slots=True)
class LogicFamilyAdapter:
    """Logic-family projection policy onto the unified proof key surface.

    Reviewed dimensions must be supplied by the caller (or lifted from a
    family-native key).  Unreviewed dimensions follow ``fallback_policy`` and
    never silently overwrite reviewed material.
    """

    family: ProofCacheFamily
    reviewed_key_dimensions: tuple[str, ...]
    fallback_policy: FallbackPolicy
    default_dimension_values: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LOGIC_FAMILY_ADAPTER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        family = (
            self.family
            if isinstance(self.family, ProofCacheFamily)
            else ProofCacheFamily.parse(str(self.family))
        )
        object.__setattr__(self, "family", family)
        reviewed = tuple(
            _text(item, "reviewed_key_dimensions item")
            for item in (self.reviewed_key_dimensions or ())
        )
        unknown = sorted(set(reviewed) - set(PROOF_AUTHORITY_DIMENSION_SET))
        if unknown:
            raise DuckDBProofServiceAdapterError(
                f"adapter for {family.value} declares unknown dimensions: "
                f"{unknown}"
            )
        if not reviewed:
            raise DuckDBProofServiceAdapterError(
                f"adapter for {family.value} must review at least one dimension"
            )
        # Preserve declaration order; drop duplicates.
        seen: set[str] = set()
        ordered: list[str] = []
        for name in reviewed:
            if name not in seen:
                seen.add(name)
                ordered.append(name)
        object.__setattr__(self, "reviewed_key_dimensions", tuple(ordered))
        object.__setattr__(
            self,
            "fallback_policy",
            _enum(self.fallback_policy, FallbackPolicy, "fallback_policy"),
        )
        defaults = dict(self.default_dimension_values or {})
        # Defaults may only target unreviewed dimensions.
        reviewed_set = set(self.reviewed_key_dimensions)
        illegal = sorted(set(defaults) & reviewed_set)
        if illegal:
            raise DuckDBProofServiceAdapterError(
                f"adapter for {family.value} cannot default reviewed "
                f"dimensions: {illegal}"
            )
        unknown_defaults = sorted(
            set(defaults) - set(PROOF_AUTHORITY_DIMENSION_SET)
        )
        if unknown_defaults:
            raise DuckDBProofServiceAdapterError(
                f"adapter for {family.value} has unknown default dimensions: "
                f"{unknown_defaults}"
            )
        object.__setattr__(
            self,
            "default_dimension_values",
            MappingProxyType(_json_ready(defaults)),
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != LOGIC_FAMILY_ADAPTER_SCHEMA_VERSION:
            raise DuckDBProofServiceAdapterError(
                f"unsupported adapter schema: {self.schema_version!r}"
            )

    @property
    def reviewed_set(self) -> frozenset[str]:
        return frozenset(self.reviewed_key_dimensions)

    def preserves_reviewed_keys(self, key: UnifiedProofKey) -> bool:
        """Return True when every reviewed dimension is present and non-empty."""

        if not isinstance(key, UnifiedProofKey):
            return False
        try:
            key.require_all_dimensions()
            dims = key.dimension_map()
        except DuckDBProofStoreError:
            return False
        for name in self.reviewed_key_dimensions:
            value = dims.get(name)
            if not value:
                return False
        return True

    def project_key(
        self,
        *,
        dimensions: Mapping[str, Any] | None = None,
        unified_key: UnifiedProofKey | None = None,
        hammer_key: Mapping[str, Any] | None = None,
        verification_key: VerificationCacheKey | None = None,
    ) -> UnifiedProofKey:
        """Project family-native material into a :class:`UnifiedProofKey`.

        Precedence: explicit ``unified_key`` > ``hammer_key`` >
        ``verification_key`` + dimensions > dimensions alone.  Reviewed
        dimensions missing after projection raise or quarantine per policy.
        """

        if unified_key is not None:
            if not isinstance(unified_key, UnifiedProofKey):
                raise DuckDBProofServiceAdapterError(
                    "unified_key must be a UnifiedProofKey"
                )
            key = unified_key
        elif hammer_key is not None:
            if self.family is not ProofCacheFamily.HAMMERS:
                raise DuckDBProofServiceAdapterError(
                    "hammer_key is only valid for the hammers adapter"
                )
            try:
                key = UnifiedProofKey.from_hammer_key_dict(hammer_key)
            except DuckDBProofStoreError as error:
                raise DuckDBProofServiceAdapterError(
                    f"hammer key cannot be projected: {error}"
                ) from error
        elif verification_key is not None:
            dims = dict(dimensions or {})
            try:
                key = UnifiedProofKey.from_verification_cache_key(
                    verification_key,
                    selected_premise_digests=dims.get(
                        "selected_premise_digests", ()
                    ),
                    solver_identities=dims.get(
                        "solver", dims.get("solver_identities", ())
                    ),
                    toolchain=dims.get("toolchain", "not-applicable"),
                    theorem_registry=dims.get(
                        "theorem_registry", f"family:{self.family.value}"
                    ),
                )
            except (DuckDBProofStoreError, TypeError, ValueError) as error:
                raise DuckDBProofServiceAdapterError(
                    f"verification key cannot be projected: {error}"
                ) from error
        else:
            dims = dict(dimensions or {})
            # Apply unreviewed defaults under FILL policy before build.
            if self.fallback_policy is FallbackPolicy.FILL_UNREVIEWED_DEFAULTS:
                for name, default in self.default_dimension_values.items():
                    dims.setdefault(name, default)
            # Family identity always rides in property / backend_config so
            # logic-specific semantics remain distinct under the unified key.
            property_value = dims.get("property", dims.get("property_value"))
            if property_value is None:
                property_value = {}
            if isinstance(property_value, Mapping):
                property_value = {
                    **dict(property_value),
                    "logic_family": self.family.value,
                }
            backend_config = dims.get("backend_config")
            if backend_config is None:
                backend_config = {"source_family": self.family.value}
            elif isinstance(backend_config, Mapping):
                backend_config = {
                    **dict(backend_config),
                    "source_family": self.family.value,
                }
            try:
                key = UnifiedProofKey.build(
                    ir=dims.get("ir", dims.get("obligation")),
                    property_value=property_value,
                    assumptions=dims.get("assumptions", ()),
                    selected_premises=dims.get("premises", dims.get("selected_premises", ())),
                    selected_premise_digests=dims.get(
                        "selected_premise_digests", ()
                    ),
                    translator=dims.get("translator", dims.get("translation")),
                    solver_identities=dims.get(
                        "solver", dims.get("solver_identities", ())
                    ),
                    toolchain=dims.get("toolchain", "not-applicable"),
                    theorem_registry=dims.get(
                        "theorem_registry", f"family:{self.family.value}"
                    ),
                    policy=dims.get("policy"),
                    resources=dims.get("resource", dims.get("resources")),
                    tree=dims.get("tree"),
                    backend_id=str(
                        dims.get("backend_id")
                        or f"family.{self.family.value}"
                    ),
                    backend_binary=dims.get("backend_binary", "unspecified"),
                    backend_version=str(
                        dims.get("backend_version") or "unspecified"
                    ),
                    backend_config=backend_config,
                )
            except DuckDBProofStoreError as error:
                raise DuckDBProofServiceAdapterError(
                    f"family key cannot be projected: {error}"
                ) from error

        if not self.preserves_reviewed_keys(key):
            if self.fallback_policy is FallbackPolicy.QUARANTINE:
                raise DuckDBProofServiceAdapterError(
                    f"family {self.family.value} quarantined key: reviewed "
                    f"dimensions incomplete"
                )
            raise DuckDBProofServiceAdapterError(
                f"family {self.family.value} refuses key: reviewed dimensions "
                f"{list(self.reviewed_key_dimensions)} must remain present "
                f"(fallback_policy={self.fallback_policy.value})"
            )
        return key

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_dimension_values": dict(self.default_dimension_values),
            "fallback_policy": self.fallback_policy.value,
            "family": self.family.value,
            "reviewed_key_dimensions": list(self.reviewed_key_dimensions),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> LogicFamilyAdapter:
        if not isinstance(value, Mapping):
            raise DuckDBProofServiceAdapterError("adapter must be a mapping")
        return cls(
            family=value.get("family", ProofCacheFamily.COMMON.value),
            reviewed_key_dimensions=tuple(
                value.get("reviewed_key_dimensions") or ()
            ),
            fallback_policy=value.get(
                "fallback_policy", FallbackPolicy.FAIL_CLOSED.value
            ),
            default_dimension_values=dict(
                value.get("default_dimension_values") or {}
            ),
            schema_version=str(
                value.get("schema_version")
                or LOGIC_FAMILY_ADAPTER_SCHEMA_VERSION
            ),
        )


def _default_adapters() -> dict[ProofCacheFamily, LogicFamilyAdapter]:
    """Closed default adapter table for every migrated proof-cache family."""

    specs: list[tuple[ProofCacheFamily, tuple[str, ...], FallbackPolicy, dict]] = [
        (
            ProofCacheFamily.COMMON,
            _COMMON_REVIEWED,
            FallbackPolicy.FILL_UNREVIEWED_DEFAULTS,
            {
                "assumptions": (),
                "premises": (),
                "translator": {"migration": "common-default"},
                "toolchain": "not-applicable",
                "theorem_registry": "family:common",
                "resource": {},
                "tree": {},
                "backend_binary": "unspecified",
                "backend_config": {"source_family": "common"},
            },
        ),
        (
            ProofCacheFamily.TDFOL,
            _TDFOL_REVIEWED,
            FallbackPolicy.FILL_UNREVIEWED_DEFAULTS,
            {
                "translator": {"family": "tdfol"},
                "theorem_registry": "family:tdfol",
                "tree": {},
                "backend_binary": "unspecified",
                "backend_config": {"source_family": "tdfol"},
            },
        ),
        (
            ProofCacheFamily.CEC,
            _CEC_REVIEWED,
            FallbackPolicy.FILL_UNREVIEWED_DEFAULTS,
            {
                "assumptions": (),
                "premises": (),
                "translator": {"family": "cec"},
                "toolchain": "not-applicable",
                "theorem_registry": "family:cec",
                "tree": {},
                "backend_binary": "unspecified",
            },
        ),
        (
            ProofCacheFamily.INTEGRATION,
            _INTEGRATION_REVIEWED,
            FallbackPolicy.FILL_UNREVIEWED_DEFAULTS,
            {
                "premises": (),
                "toolchain": "not-applicable",
                "theorem_registry": "family:integration",
                "resource": {},
                "tree": {},
                "backend_binary": "unspecified",
            },
        ),
        (
            ProofCacheFamily.HAMMERS,
            _HAMMER_REVIEWED,
            FallbackPolicy.FAIL_CLOSED,
            {},
        ),
        (
            ProofCacheFamily.LEGAL_IR,
            _LEGAL_REVIEWED,
            FallbackPolicy.QUARANTINE,
            {
                "assumptions": (),
                "tree": {},
                "backend_binary": "unspecified",
            },
        ),
        (
            ProofCacheFamily.EXTERNAL_PROVERS,
            _EXTERNAL_REVIEWED,
            FallbackPolicy.FAIL_CLOSED,
            {
                "assumptions": (),
                "premises": (),
                "translator": {"family": "external_provers"},
                "resource": {},
                "tree": {},
            },
        ),
    ]
    return {
        family: LogicFamilyAdapter(
            family=family,
            reviewed_key_dimensions=reviewed,
            fallback_policy=policy,
            default_dimension_values=defaults,
        )
        for family, reviewed, policy, defaults in specs
    }


DEFAULT_LOGIC_FAMILY_ADAPTERS: Final[
    Mapping[ProofCacheFamily, LogicFamilyAdapter]
] = MappingProxyType(_default_adapters())


# ---------------------------------------------------------------------------
# Evidence receipts, policy gates, plans, nodes, traces
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvidenceReceipt:
    """Auditable evidence binding required for authority upgrades.

    A receipt is not itself authority; it names the evidence that *justifies*
    a trust transition.  The service refuses upgrades without receipts whose
    projected trust covers the requested target.
    """

    receipt_id: str
    key_digest: str
    evidence: ProofEvidenceRecord
    issued_at: float
    issuer_id: str = DEFAULT_OWNER_ID
    entry_digest: str = ""
    notes: str = ""
    schema_version: str = EVIDENCE_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", _text(self.receipt_id, "receipt_id")
        )
        object.__setattr__(
            self, "key_digest", _text(self.key_digest, "key_digest")
        )
        if not isinstance(self.evidence, ProofEvidenceRecord):
            raise DuckDBProofServiceError(
                "evidence must be a ProofEvidenceRecord"
            )
        object.__setattr__(
            self, "issued_at", _finite_number(self.issued_at, "issued_at")
        )
        object.__setattr__(
            self, "issuer_id", _text(self.issuer_id, "issuer_id")
        )
        object.__setattr__(
            self,
            "entry_digest",
            _text(self.entry_digest, "entry_digest", optional=True),
        )
        object.__setattr__(
            self, "notes", _text(self.notes, "notes", optional=True)
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != EVIDENCE_RECEIPT_SCHEMA_VERSION:
            raise DuckDBProofServiceError(
                f"unsupported evidence receipt schema: {self.schema_version!r}"
            )

    @property
    def evidence_authority(self) -> EvidenceAuthority:
        return self.evidence.evidence_authority

    @property
    def projected_trust(self) -> ProofTrustLevel:
        return trust_level_from_evidence(self.evidence.evidence_authority)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_digest": self.entry_digest,
            "evidence": self.evidence.to_dict(),
            "issued_at": self.issued_at,
            "issuer_id": self.issuer_id,
            "key_digest": self.key_digest,
            "notes": self.notes,
            "receipt_id": self.receipt_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> EvidenceReceipt:
        if not isinstance(value, Mapping):
            raise DuckDBProofServiceError("evidence receipt must be a mapping")
        evidence_payload = value.get("evidence")
        if not isinstance(evidence_payload, Mapping):
            raise DuckDBProofServiceError(
                "evidence receipt requires an evidence mapping"
            )
        return cls(
            receipt_id=str(value.get("receipt_id") or ""),
            key_digest=str(value.get("key_digest") or ""),
            evidence=ProofEvidenceRecord.from_dict(evidence_payload),
            issued_at=float(value.get("issued_at") or 0.0),
            issuer_id=str(value.get("issuer_id") or DEFAULT_OWNER_ID),
            entry_digest=str(value.get("entry_digest") or ""),
            notes=str(value.get("notes") or ""),
            schema_version=str(
                value.get("schema_version") or EVIDENCE_RECEIPT_SCHEMA_VERSION
            ),
        )

    @classmethod
    def build(
        cls,
        *,
        key: UnifiedProofKey | str,
        evidence_kind: str,
        evidence_authority: EvidenceAuthority | str,
        payload: Mapping[str, Any] | None = None,
        content: Any = None,
        evidence_id: str | None = None,
        entry_digest: str = "",
        issuer_id: str = DEFAULT_OWNER_ID,
        notes: str = "",
        issued_at: float | None = None,
    ) -> EvidenceReceipt:
        """Construct a receipt with a content-addressed evidence record."""

        key_digest = _key_digest(key)
        auth = (
            evidence_authority
            if isinstance(evidence_authority, EvidenceAuthority)
            else EvidenceAuthority(str(evidence_authority))
        )
        body = dict(payload or {})
        if content is not None:
            body.setdefault("content", _json_ready(content))
        digest = service_content_digest(
            {
                "evidence_authority": auth.value,
                "evidence_kind": evidence_kind,
                "key_digest": key_digest,
                "payload": body,
            }
        )
        record = ProofEvidenceRecord(
            evidence_id=evidence_id or _new_id("ev"),
            evidence_kind=_text(evidence_kind, "evidence_kind"),
            evidence_authority=auth,
            content_digest=digest,
            payload=FrozenMap(body),
            created_at=float(issued_at if issued_at is not None else time.time()),
        )
        return cls(
            receipt_id=_new_id("receipt"),
            key_digest=key_digest,
            evidence=record,
            issued_at=record.created_at,
            issuer_id=issuer_id,
            entry_digest=entry_digest,
            notes=notes,
        )


@dataclass(frozen=True, slots=True)
class PolicyGateDecision:
    """Result of evaluating a policy gate against an action."""

    action: PolicyGateAction
    verdict: PolicyGateVerdict
    reason: str
    key_digest: str = ""
    plan_id: str = ""
    node_id: str = ""
    required_trust: ProofTrustLevel | None = None
    schema_version: str = POLICY_GATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "action", _enum(self.action, PolicyGateAction, "action")
        )
        object.__setattr__(
            self, "verdict", _enum(self.verdict, PolicyGateVerdict, "verdict")
        )
        object.__setattr__(self, "reason", _text(self.reason, "reason"))
        object.__setattr__(
            self,
            "key_digest",
            _text(self.key_digest, "key_digest", optional=True),
        )
        object.__setattr__(
            self, "plan_id", _text(self.plan_id, "plan_id", optional=True)
        )
        object.__setattr__(
            self, "node_id", _text(self.node_id, "node_id", optional=True)
        )
        if self.required_trust is not None:
            object.__setattr__(
                self,
                "required_trust",
                _enum(self.required_trust, ProofTrustLevel, "required_trust"),
            )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )

    @property
    def allowed(self) -> bool:
        return self.verdict is PolicyGateVerdict.ALLOW

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "key_digest": self.key_digest,
            "node_id": self.node_id,
            "plan_id": self.plan_id,
            "reason": self.reason,
            "required_trust": None
            if self.required_trust is None
            else self.required_trust.value,
            "schema_version": self.schema_version,
            "verdict": self.verdict.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PolicyGateDecision:
        if not isinstance(value, Mapping):
            raise DuckDBProofServiceError("policy gate decision must be a mapping")
        required = value.get("required_trust")
        return cls(
            action=value.get("action", PolicyGateAction.PUBLISH_DRAFT.value),
            verdict=value.get("verdict", PolicyGateVerdict.DENY.value),
            reason=str(value.get("reason") or "unspecified"),
            key_digest=str(value.get("key_digest") or ""),
            plan_id=str(value.get("plan_id") or ""),
            node_id=str(value.get("node_id") or ""),
            required_trust=None if required in (None, "") else required,
            schema_version=str(
                value.get("schema_version") or POLICY_GATE_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class ProofPlanNode:
    """One schedulable unit of proof work under a plan."""

    node_id: str
    key: UnifiedProofKey
    family: ProofCacheFamily
    depends_on: tuple[str, ...] = ()
    status: PlanNodeStatus = PlanNodeStatus.PENDING
    entry_digest: str = ""
    claim_id: str = ""
    attempt_id: str = ""
    publication_mode: EntryPublicationMode | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = PROOF_PLAN_NODE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _text(self.node_id, "node_id"))
        if not isinstance(self.key, UnifiedProofKey):
            raise DuckDBProofServiceError("node.key must be a UnifiedProofKey")
        self.key.require_all_dimensions()
        family = (
            self.family
            if isinstance(self.family, ProofCacheFamily)
            else ProofCacheFamily.parse(str(self.family))
        )
        object.__setattr__(self, "family", family)
        deps = tuple(
            _text(item, "depends_on item") for item in (self.depends_on or ())
        )
        if self.node_id in deps:
            raise DuckDBProofServiceError("node cannot depend on itself")
        if len(deps) != len(set(deps)):
            raise DuckDBProofServiceError("depends_on must not contain duplicates")
        object.__setattr__(self, "depends_on", deps)
        object.__setattr__(
            self, "status", _enum(self.status, PlanNodeStatus, "status")
        )
        object.__setattr__(
            self,
            "entry_digest",
            _text(self.entry_digest, "entry_digest", optional=True),
        )
        object.__setattr__(
            self, "claim_id", _text(self.claim_id, "claim_id", optional=True)
        )
        object.__setattr__(
            self,
            "attempt_id",
            _text(self.attempt_id, "attempt_id", optional=True),
        )
        if self.publication_mode is not None:
            object.__setattr__(
                self,
                "publication_mode",
                _enum(
                    self.publication_mode,
                    EntryPublicationMode,
                    "publication_mode",
                ),
            )
        try:
            meta = FrozenMap(self.metadata or {})
        except (TypeError, ValueError) as error:
            raise DuckDBProofServiceError(
                "node metadata must be an immutable JSON mapping"
            ) from error
        object.__setattr__(self, "metadata", meta)
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PROOF_PLAN_NODE_SCHEMA_VERSION:
            raise DuckDBProofServiceError(
                f"unsupported plan node schema: {self.schema_version!r}"
            )

    @property
    def key_digest(self) -> str:
        return self.key.digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "claim_id": self.claim_id,
            "depends_on": list(self.depends_on),
            "entry_digest": self.entry_digest,
            "family": self.family.value,
            "key": self.key.to_dict(),
            "metadata": self.metadata.to_dict()
            if hasattr(self.metadata, "to_dict")
            else dict(self.metadata),
            "node_id": self.node_id,
            "publication_mode": None
            if self.publication_mode is None
            else self.publication_mode.value,
            "schema_version": self.schema_version,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProofPlanNode:
        if not isinstance(value, Mapping):
            raise DuckDBProofServiceError("plan node must be a mapping")
        key_payload = value.get("key")
        if not isinstance(key_payload, Mapping):
            raise DuckDBProofServiceError("plan node requires a key mapping")
        mode = value.get("publication_mode")
        return cls(
            node_id=str(value.get("node_id") or ""),
            key=UnifiedProofKey.from_dict(key_payload),
            family=value.get("family", ProofCacheFamily.COMMON.value),
            depends_on=tuple(value.get("depends_on") or ()),
            status=value.get("status", PlanNodeStatus.PENDING.value),
            entry_digest=str(value.get("entry_digest") or ""),
            claim_id=str(value.get("claim_id") or ""),
            attempt_id=str(value.get("attempt_id") or ""),
            publication_mode=None if mode in (None, "") else mode,
            metadata=dict(value.get("metadata") or {}),
            schema_version=str(
                value.get("schema_version") or PROOF_PLAN_NODE_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class ProofPlan:
    """Ordered (DAG) set of proof nodes scheduled under one plan identity."""

    plan_id: str
    nodes: tuple[ProofPlanNode, ...]
    family: ProofCacheFamily = ProofCacheFamily.COMMON
    created_at: float = 0.0
    policy: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = PROOF_PLAN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "plan_id", _text(self.plan_id, "plan_id"))
        nodes = tuple(self.nodes or ())
        if not nodes:
            raise DuckDBProofServiceError("plan must contain at least one node")
        for node in nodes:
            if not isinstance(node, ProofPlanNode):
                raise DuckDBProofServiceError(
                    "plan.nodes items must be ProofPlanNode instances"
                )
        ids = [node.node_id for node in nodes]
        if len(ids) != len(set(ids)):
            raise DuckDBProofServiceError("plan node_ids must be unique")
        id_set = set(ids)
        for node in nodes:
            missing = [dep for dep in node.depends_on if dep not in id_set]
            if missing:
                raise DuckDBProofServiceError(
                    f"node {node.node_id!r} depends on unknown nodes: {missing}"
                )
        if _plan_has_cycle(nodes):
            raise DuckDBProofServiceError("plan dependency graph contains a cycle")
        object.__setattr__(self, "nodes", nodes)
        family = (
            self.family
            if isinstance(self.family, ProofCacheFamily)
            else ProofCacheFamily.parse(str(self.family))
        )
        object.__setattr__(self, "family", family)
        object.__setattr__(
            self, "created_at", _finite_number(self.created_at, "created_at")
        )
        try:
            policy = FrozenMap(self.policy or {})
            meta = FrozenMap(self.metadata or {})
        except (TypeError, ValueError) as error:
            raise DuckDBProofServiceError(
                "plan policy/metadata must be immutable JSON mappings"
            ) from error
        object.__setattr__(self, "policy", policy)
        object.__setattr__(self, "metadata", meta)
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PROOF_PLAN_SCHEMA_VERSION:
            raise DuckDBProofServiceError(
                f"unsupported plan schema: {self.schema_version!r}"
            )

    def node_map(self) -> Mapping[str, ProofPlanNode]:
        return {node.node_id: node for node in self.nodes}

    def ready_nodes(
        self, completed: Iterable[str] = ()
    ) -> tuple[ProofPlanNode, ...]:
        done = set(completed)
        ready: list[ProofPlanNode] = []
        for node in self.nodes:
            if node.status not in {
                PlanNodeStatus.PENDING,
                PlanNodeStatus.SKIPPED,
            } and node.node_id not in done:
                # Already progressed nodes are not "ready" for scheduling.
                if node.status is not PlanNodeStatus.PENDING:
                    continue
            if node.status is PlanNodeStatus.PENDING and all(
                dep in done for dep in node.depends_on
            ):
                ready.append(node)
        return tuple(ready)

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "family": self.family.value,
            "metadata": self.metadata.to_dict()
            if hasattr(self.metadata, "to_dict")
            else dict(self.metadata),
            "nodes": [node.to_dict() for node in self.nodes],
            "plan_id": self.plan_id,
            "policy": self.policy.to_dict()
            if hasattr(self.policy, "to_dict")
            else dict(self.policy),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProofPlan:
        if not isinstance(value, Mapping):
            raise DuckDBProofServiceError("plan must be a mapping")
        nodes_raw = value.get("nodes") or ()
        return cls(
            plan_id=str(value.get("plan_id") or ""),
            nodes=tuple(
                ProofPlanNode.from_dict(item) for item in nodes_raw
            ),
            family=value.get("family", ProofCacheFamily.COMMON.value),
            created_at=float(value.get("created_at") or 0.0),
            policy=dict(value.get("policy") or {}),
            metadata=dict(value.get("metadata") or {}),
            schema_version=str(
                value.get("schema_version") or PROOF_PLAN_SCHEMA_VERSION
            ),
        )


def _plan_has_cycle(nodes: Sequence[ProofPlanNode]) -> bool:
    depends = {node.node_id: set(node.depends_on) for node in nodes}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> bool:
        if node_id in visited:
            return False
        if node_id in visiting:
            return True
        visiting.add(node_id)
        for dep in depends.get(node_id, ()):
            if visit(dep):
                return True
        visiting.remove(node_id)
        visited.add(node_id)
        return False

    return any(visit(node_id) for node_id in depends)


@dataclass(frozen=True, slots=True)
class SchedulerTraceEvent:
    """One immutable event in a proof scheduler trace."""

    event_id: str
    kind: TraceEventKind
    timestamp: float
    plan_id: str = ""
    node_id: str = ""
    key_digest: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    sequence: int = 0
    schema_version: str = SCHEDULER_TRACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _text(self.event_id, "event_id"))
        object.__setattr__(
            self, "kind", _enum(self.kind, TraceEventKind, "kind")
        )
        object.__setattr__(
            self, "timestamp", _finite_number(self.timestamp, "timestamp")
        )
        object.__setattr__(
            self, "plan_id", _text(self.plan_id, "plan_id", optional=True)
        )
        object.__setattr__(
            self, "node_id", _text(self.node_id, "node_id", optional=True)
        )
        object.__setattr__(
            self,
            "key_digest",
            _text(self.key_digest, "key_digest", optional=True),
        )
        try:
            payload = FrozenMap(self.payload or {})
        except (TypeError, ValueError) as error:
            raise DuckDBProofServiceError(
                "trace event payload must be an immutable JSON mapping"
            ) from error
        object.__setattr__(self, "payload", payload)
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 0
        ):
            raise DuckDBProofServiceError("sequence must be a non-negative int")
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "key_digest": self.key_digest,
            "kind": self.kind.value,
            "node_id": self.node_id,
            "payload": self.payload.to_dict()
            if hasattr(self.payload, "to_dict")
            else dict(self.payload),
            "plan_id": self.plan_id,
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SchedulerTraceEvent:
        if not isinstance(value, Mapping):
            raise DuckDBProofServiceError("trace event must be a mapping")
        return cls(
            event_id=str(value.get("event_id") or ""),
            kind=value.get("kind", TraceEventKind.TRACE_MARK.value),
            timestamp=float(value.get("timestamp") or 0.0),
            plan_id=str(value.get("plan_id") or ""),
            node_id=str(value.get("node_id") or ""),
            key_digest=str(value.get("key_digest") or ""),
            payload=dict(value.get("payload") or {}),
            sequence=int(value.get("sequence") or 0),
            schema_version=str(
                value.get("schema_version") or SCHEDULER_TRACE_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class SchedulerTrace:
    """Ordered proof scheduler trace suitable for deterministic replay."""

    trace_id: str
    events: tuple[SchedulerTraceEvent, ...]
    plan_id: str = ""
    created_at: float = 0.0
    schema_version: str = SCHEDULER_TRACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace_id", _text(self.trace_id, "trace_id"))
        events = tuple(self.events or ())
        for event in events:
            if not isinstance(event, SchedulerTraceEvent):
                raise DuckDBProofServiceError(
                    "trace.events items must be SchedulerTraceEvent instances"
                )
        # Sequence must be strictly increasing for stable replay order.
        last = -1
        for event in events:
            if event.sequence <= last:
                raise DuckDBProofServiceError(
                    "trace event sequence must be strictly increasing"
                )
            last = event.sequence
        object.__setattr__(self, "events", events)
        object.__setattr__(
            self, "plan_id", _text(self.plan_id, "plan_id", optional=True)
        )
        object.__setattr__(
            self, "created_at", _finite_number(self.created_at, "created_at")
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != SCHEDULER_TRACE_SCHEMA_VERSION:
            raise DuckDBProofServiceError(
                f"unsupported scheduler trace schema: {self.schema_version!r}"
            )

    @property
    def digest(self) -> str:
        return service_content_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "events": [event.to_dict() for event in self.events],
            "plan_id": self.plan_id,
            "schema_version": self.schema_version,
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SchedulerTrace:
        if not isinstance(value, Mapping):
            raise DuckDBProofServiceError("scheduler trace must be a mapping")
        return cls(
            trace_id=str(value.get("trace_id") or ""),
            events=tuple(
                SchedulerTraceEvent.from_dict(item)
                for item in (value.get("events") or ())
            ),
            plan_id=str(value.get("plan_id") or ""),
            created_at=float(value.get("created_at") or 0.0),
            schema_version=str(
                value.get("schema_version") or SCHEDULER_TRACE_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class SchedulerTraceReplayResult:
    """Outcome of replaying a proof scheduler trace."""

    source_trace_id: str
    source_digest: str
    replay_trace_id: str
    replay_digest: str
    matched: bool
    events_replayed: int
    divergences: tuple[str, ...] = ()
    final_node_statuses: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "divergences": list(self.divergences),
            "events_replayed": self.events_replayed,
            "final_node_statuses": dict(self.final_node_statuses),
            "matched": self.matched,
            "replay_digest": self.replay_digest,
            "replay_trace_id": self.replay_trace_id,
            "source_digest": self.source_digest,
            "source_trace_id": self.source_trace_id,
        }


@dataclass(frozen=True, slots=True)
class ServiceOperationResult:
    """Projection of one service mutation/lookup outcome."""

    ok: bool
    action: str
    key_digest: str = ""
    plan_id: str = ""
    node_id: str = ""
    entry: UnifiedProofEntry | None = None
    claim: ProofFenceClaim | None = None
    attempt: ProofAttemptRecord | None = None
    gate: PolicyGateDecision | None = None
    receipt: EvidenceReceipt | None = None
    reason: str = ""
    coordination: CoordinationResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "attempt": None if self.attempt is None else self.attempt.to_dict(),
            "claim": None if self.claim is None else self.claim.to_dict(),
            "entry_digest": None
            if self.entry is None
            else self.entry.entry_digest,
            "gate": None if self.gate is None else self.gate.to_dict(),
            "key_digest": self.key_digest,
            "node_id": self.node_id,
            "ok": self.ok,
            "plan_id": self.plan_id,
            "reason": self.reason,
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
        }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class DuckDBProofService:
    """Integrate proof plans, coordination, evidence, and corpus authority.

    The service is the single façade that schedulers and formal-verification
    caches use so plans/nodes/attempts/leases/evidence/drafts/attestations and
    policy gates share the unified protocol while each logic family keeps its
    reviewed key dimensions and fallback policy.
    """

    def __init__(
        self,
        *,
        coordinator: DuckDBProofCoordinator | None = None,
        store: DuckDBProofStore | None = None,
        corpus: ProofCorpusDuckDBRepository | None = None,
        adapters: Mapping[ProofCacheFamily | str, LogicFamilyAdapter]
        | None = None,
        owner_id: str = DEFAULT_OWNER_ID,
        max_trace_events: int = DEFAULT_MAX_TRACE_EVENTS,
        max_plans: int = DEFAULT_MAX_PLANS,
        require_policy_mode: str | None = None,
        connection: Any | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._owner_id = _text(owner_id, "owner_id")
        self._max_trace_events = max(1, int(max_trace_events))
        self._max_plans = max(1, int(max_plans))
        self._require_policy_mode = (
            None
            if require_policy_mode in (None, "")
            else _text(require_policy_mode, "require_policy_mode")
        )
        self._coordinator = coordinator or build_duckdb_proof_coordinator(
            store=store,
            connection=connection,
            clock=self._clock,
        )
        self._store = self._coordinator.store
        self._corpus = corpus  # optional; attestation envelope indexing
        self._adapters: dict[ProofCacheFamily, LogicFamilyAdapter] = dict(
            DEFAULT_LOGIC_FAMILY_ADAPTERS
        )
        if adapters:
            for raw_family, adapter in adapters.items():
                family = (
                    raw_family
                    if isinstance(raw_family, ProofCacheFamily)
                    else ProofCacheFamily.parse(str(raw_family))
                )
                if not isinstance(adapter, LogicFamilyAdapter):
                    raise DuckDBProofServiceError(
                        "adapters values must be LogicFamilyAdapter instances"
                    )
                if adapter.family is not family:
                    raise DuckDBProofServiceError(
                        f"adapter family {adapter.family.value} does not match "
                        f"registry key {family.value}"
                    )
                self._adapters[family] = adapter
        self._plans: dict[str, ProofPlan] = {}
        self._node_index: dict[str, tuple[str, str]] = {}  # key_digest -> (plan, node)
        self._receipts: dict[str, list[EvidenceReceipt]] = {}
        self._trace_events: list[SchedulerTraceEvent] = []
        self._trace_seq = 0
        self._active_trace_id = _new_id("trace")
        self._stats = {
            "plans_registered": 0,
            "nodes_scheduled": 0,
            "leases_claimed": 0,
            "drafts_published": 0,
            "attested_published": 0,
            "authority_upgrades": 0,
            "authority_upgrade_rejections": 0,
            "policy_denials": 0,
            "evidence_receipts": 0,
            "traces_exported": 0,
            "traces_replayed": 0,
            "replay_matches": 0,
            "replay_divergences": 0,
            "adapter_projections": 0,
            "adapter_rejections": 0,
        }
        if connection is not None:
            self.install_schema(connection)

    # -- identity ------------------------------------------------------------

    @property
    def interface(self) -> str:
        return DUCKDB_PROOF_SERVICE_INTERFACE

    @property
    def schema_version(self) -> str:
        return DUCKDB_PROOF_SERVICE_SCHEMA_VERSION

    @property
    def coordinator(self) -> DuckDBProofCoordinator:
        return self._coordinator

    @property
    def store(self) -> DuckDBProofStore:
        return self._store

    @property
    def corpus(self) -> ProofCorpusDuckDBRepository | None:
        return self._corpus

    @property
    def owner_id(self) -> str:
        return self._owner_id

    @property
    def store_interface(self) -> str:
        return DUCKDB_PROOF_STORE_INTERFACE

    @property
    def coordination_interface(self) -> str:
        return DUCKDB_PROOF_COORDINATION_INTERFACE

    @property
    def corpus_interface(self) -> str:
        return PROOF_CORPUS_DUCKDB_REPOSITORY_INTERFACE

    def now(self) -> float:
        return float(self._clock())

    def stats(self) -> Mapping[str, Any]:
        with self._lock:
            return MappingProxyType(
                {
                    **dict(self._stats),
                    "coordinator": dict(self._coordinator.stats()),
                    "store": dict(self._store.stats()),
                }
            )

    def install_schema(self, connection: Any) -> None:
        """Install store + coordination (+ optional corpus) catalog DDL."""

        self._coordinator.install_schema(connection)
        if self._corpus is not None:
            self._corpus.install_schema(connection)

    # -- adapters ------------------------------------------------------------

    def adapters(self) -> Mapping[ProofCacheFamily, LogicFamilyAdapter]:
        with self._lock:
            return MappingProxyType(dict(self._adapters))

    def adapter_for(
        self, family: ProofCacheFamily | str
    ) -> LogicFamilyAdapter:
        parsed = (
            family
            if isinstance(family, ProofCacheFamily)
            else ProofCacheFamily.parse(str(family))
        )
        with self._lock:
            adapter = self._adapters.get(parsed)
            if adapter is None:
                raise DuckDBProofServiceAdapterError(
                    f"no logic-family adapter registered for {parsed.value}"
                )
            return adapter

    def project_family_key(
        self,
        family: ProofCacheFamily | str,
        *,
        dimensions: Mapping[str, Any] | None = None,
        unified_key: UnifiedProofKey | None = None,
        hammer_key: Mapping[str, Any] | None = None,
        verification_key: VerificationCacheKey | None = None,
    ) -> UnifiedProofKey:
        """Project a family-native key via its adapter (preserves reviewed keys)."""

        adapter = self.adapter_for(family)
        try:
            key = adapter.project_key(
                dimensions=dimensions,
                unified_key=unified_key,
                hammer_key=hammer_key,
                verification_key=verification_key,
            )
        except DuckDBProofServiceAdapterError:
            with self._lock:
                self._stats["adapter_rejections"] += 1
            raise
        with self._lock:
            self._stats["adapter_projections"] += 1
        return key

    # -- policy gate ---------------------------------------------------------

    def evaluate_policy_gate(
        self,
        action: PolicyGateAction | str,
        *,
        key: UnifiedProofKey | str | None = None,
        plan_id: str = "",
        node_id: str = "",
        entry: UnifiedProofEntry | None = None,
        evidence_receipts: Sequence[EvidenceReceipt] = (),
        target_trust: ProofTrustLevel | str | None = None,
        plan_policy: Mapping[str, Any] | None = None,
    ) -> PolicyGateDecision:
        """Evaluate whether *action* is permitted under current policy."""

        act = _enum(action, PolicyGateAction, "action")
        key_digest = "" if key is None else _key_digest(key)
        policy = dict(plan_policy or {})
        if self._require_policy_mode is not None:
            mode = str(policy.get("mode") or "")
            if mode != self._require_policy_mode:
                decision = PolicyGateDecision(
                    action=act,
                    verdict=PolicyGateVerdict.DENY,
                    reason=(
                        f"policy mode {mode!r} does not match required "
                        f"{self._require_policy_mode!r}"
                    ),
                    key_digest=key_digest,
                    plan_id=plan_id,
                    node_id=node_id,
                )
                self._record_gate(decision)
                return decision

        if act is PolicyGateAction.PUBLISH_DRAFT:
            if entry is not None and trust_rank(entry.trust_level) > trust_rank(
                ProofTrustLevel.ADVISORY
            ):
                decision = PolicyGateDecision(
                    action=act,
                    verdict=PolicyGateVerdict.DENY,
                    reason="draft publication cannot carry above-advisory trust",
                    key_digest=key_digest,
                    plan_id=plan_id,
                    node_id=node_id,
                )
                self._record_gate(decision)
                return decision
            decision = PolicyGateDecision(
                action=act,
                verdict=PolicyGateVerdict.ALLOW,
                reason="draft publication permitted",
                key_digest=key_digest,
                plan_id=plan_id,
                node_id=node_id,
            )
            self._record_gate(decision)
            return decision

        if act in {
            PolicyGateAction.PUBLISH_ATTESTED,
            PolicyGateAction.UPGRADE_AUTHORITY,
            PolicyGateAction.ATTACH_EVIDENCE,
        }:
            if not evidence_receipts:
                decision = PolicyGateDecision(
                    action=act,
                    verdict=PolicyGateVerdict.REQUIRE_EVIDENCE,
                    reason="authority-sensitive action requires evidence receipts",
                    key_digest=key_digest,
                    plan_id=plan_id,
                    node_id=node_id,
                    required_trust=(
                        None
                        if target_trust is None
                        else _enum(
                            target_trust, ProofTrustLevel, "target_trust"
                        )
                    ),
                )
                self._record_gate(decision)
                return decision
            if target_trust is not None:
                target = _enum(target_trust, ProofTrustLevel, "target_trust")
                ceiling = _max_projected_trust(evidence_receipts)
                if trust_rank(ceiling) < trust_rank(target):
                    decision = PolicyGateDecision(
                        action=act,
                        verdict=PolicyGateVerdict.DENY,
                        reason=(
                            f"evidence projects to {ceiling.value} which does "
                            f"not cover target trust {target.value}"
                        ),
                        key_digest=key_digest,
                        plan_id=plan_id,
                        node_id=node_id,
                        required_trust=target,
                    )
                    self._record_gate(decision)
                    return decision
            # Bind receipts to the key when provided.
            for receipt in evidence_receipts:
                if key_digest and receipt.key_digest != key_digest:
                    decision = PolicyGateDecision(
                        action=act,
                        verdict=PolicyGateVerdict.DENY,
                        reason=(
                            f"evidence receipt {receipt.receipt_id} key_digest "
                            f"mismatch"
                        ),
                        key_digest=key_digest,
                        plan_id=plan_id,
                        node_id=node_id,
                    )
                    self._record_gate(decision)
                    return decision
            decision = PolicyGateDecision(
                action=act,
                verdict=PolicyGateVerdict.ALLOW,
                reason="evidence receipts satisfy policy",
                key_digest=key_digest,
                plan_id=plan_id,
                node_id=node_id,
                required_trust=(
                    None
                    if target_trust is None
                    else _enum(target_trust, ProofTrustLevel, "target_trust")
                ),
            )
            self._record_gate(decision)
            return decision

        # Default allow for invalidate / replay / other non-authority actions.
        decision = PolicyGateDecision(
            action=act,
            verdict=PolicyGateVerdict.ALLOW,
            reason="action permitted",
            key_digest=key_digest,
            plan_id=plan_id,
            node_id=node_id,
        )
        self._record_gate(decision)
        return decision

    def _record_gate(self, decision: PolicyGateDecision) -> None:
        if decision.verdict is PolicyGateVerdict.DENY:
            with self._lock:
                self._stats["policy_denials"] += 1
        self._append_event(
            TraceEventKind.POLICY_GATE,
            plan_id=decision.plan_id,
            node_id=decision.node_id,
            key_digest=decision.key_digest,
            payload=decision.to_dict(),
        )

    # -- plans / nodes -------------------------------------------------------

    def register_plan(self, plan: ProofPlan | Mapping[str, Any]) -> ProofPlan:
        """Register a proof plan; nodes share the unified key protocol."""

        if isinstance(plan, Mapping):
            plan = ProofPlan.from_dict(plan)
        if not isinstance(plan, ProofPlan):
            raise DuckDBProofServiceError("plan must be a ProofPlan")
        # Validate every node key through its family adapter.
        for node in plan.nodes:
            adapter = self.adapter_for(node.family)
            if not adapter.preserves_reviewed_keys(node.key):
                raise DuckDBProofServiceAdapterError(
                    f"node {node.node_id!r} key fails reviewed dimensions for "
                    f"family {node.family.value}"
                )
        with self._lock:
            if len(self._plans) >= self._max_plans and plan.plan_id not in self._plans:
                # Drop oldest by created_at.
                oldest = min(self._plans.values(), key=lambda p: p.created_at)
                self._drop_plan_locked(oldest.plan_id)
            created = plan
            if created.created_at <= 0:
                created = ProofPlan(
                    plan_id=plan.plan_id,
                    nodes=plan.nodes,
                    family=plan.family,
                    created_at=self.now(),
                    policy=dict(plan.policy)
                    if hasattr(plan.policy, "items")
                    else {},
                    metadata=dict(plan.metadata)
                    if hasattr(plan.metadata, "items")
                    else {},
                )
            self._plans[created.plan_id] = created
            for node in created.nodes:
                self._node_index[node.key_digest] = (
                    created.plan_id,
                    node.node_id,
                )
            self._stats["plans_registered"] += 1
            self._stats["nodes_scheduled"] += len(created.nodes)
        self._append_event(
            TraceEventKind.PLAN_REGISTERED,
            plan_id=created.plan_id,
            payload={
                "family": created.family.value,
                "node_ids": [node.node_id for node in created.nodes],
            },
        )
        for node in created.nodes:
            self._append_event(
                TraceEventKind.NODE_SCHEDULED,
                plan_id=created.plan_id,
                node_id=node.node_id,
                key_digest=node.key_digest,
                payload={
                    "depends_on": list(node.depends_on),
                    "family": node.family.value,
                    "key": node.key.to_dict(),
                    "status": node.status.value,
                },
            )
        return created

    def get_plan(self, plan_id: str) -> ProofPlan | None:
        with self._lock:
            return self._plans.get(_text(plan_id, "plan_id"))

    def list_plans(self) -> tuple[ProofPlan, ...]:
        with self._lock:
            return tuple(self._plans.values())

    def _drop_plan_locked(self, plan_id: str) -> None:
        plan = self._plans.pop(plan_id, None)
        if plan is None:
            return
        for node in plan.nodes:
            existing = self._node_index.get(node.key_digest)
            if existing and existing[0] == plan_id:
                self._node_index.pop(node.key_digest, None)

    def _update_node_locked(
        self,
        plan_id: str,
        node_id: str,
        **changes: Any,
    ) -> ProofPlanNode:
        plan = self._plans.get(plan_id)
        if plan is None:
            raise DuckDBProofServiceError(f"unknown plan_id {plan_id!r}")
        nodes: list[ProofPlanNode] = []
        updated: ProofPlanNode | None = None
        for node in plan.nodes:
            if node.node_id != node_id:
                nodes.append(node)
                continue
            payload = node.to_dict()
            payload.update(changes)
            if "key" in changes and isinstance(changes["key"], UnifiedProofKey):
                payload["key"] = changes["key"].to_dict()
            updated = ProofPlanNode.from_dict(payload)
            nodes.append(updated)
        if updated is None:
            raise DuckDBProofServiceError(
                f"unknown node_id {node_id!r} in plan {plan_id!r}"
            )
        new_plan = ProofPlan(
            plan_id=plan.plan_id,
            nodes=tuple(nodes),
            family=plan.family,
            created_at=plan.created_at,
            policy=dict(plan.policy)
            if hasattr(plan.policy, "items")
            else {},
            metadata=dict(plan.metadata)
            if hasattr(plan.metadata, "items")
            else {},
        )
        self._plans[plan_id] = new_plan
        self._node_index[updated.key_digest] = (plan_id, node_id)
        return updated

    # -- leases / attempts (coordinator façade) ------------------------------

    def claim_node(
        self,
        plan_id: str,
        node_id: str,
        *,
        owner_id: str | None = None,
        now: float | None = None,
    ) -> ServiceOperationResult:
        """Acquire a fenced lease for a plan node via the coordinator."""

        plan = self.get_plan(plan_id)
        if plan is None:
            raise DuckDBProofServiceError(f"unknown plan_id {plan_id!r}")
        node = plan.node_map().get(node_id)
        if node is None:
            raise DuckDBProofServiceError(
                f"unknown node_id {node_id!r} in plan {plan_id!r}"
            )
        current = self.now() if now is None else float(now)
        claim = self._coordinator.claim(
            node.key,
            owner_id=owner_id or self._owner_id,
            now=current,
        )
        attempt = None
        with self._lock:
            self._stats["leases_claimed"] += 1
            if claim.acquired:
                # Coordinator already opened an attempt; surface latest.
                records = self._coordinator.attempt_records(node.key)
                attempt = records[-1] if records else None
                self._update_node_locked(
                    plan_id,
                    node_id,
                    status=PlanNodeStatus.CLAIMED.value,
                    claim_id=claim.claim_id,
                    attempt_id="" if attempt is None else attempt.attempt_id,
                )
        self._append_event(
            TraceEventKind.LEASE_CLAIMED,
            plan_id=plan_id,
            node_id=node_id,
            key_digest=node.key.digest,
            payload=claim.to_dict(),
            timestamp=current,
        )
        return ServiceOperationResult(
            ok=claim.acquired,
            action="claim_node",
            key_digest=node.key.digest,
            plan_id=plan_id,
            node_id=node_id,
            claim=claim,
            attempt=attempt if claim.acquired else None,
            reason="acquired" if claim.acquired else "followed",
        )

    def renew_lease(
        self,
        claim: ProofFenceClaim,
        *,
        now: float | None = None,
    ) -> ProofFenceClaim:
        renewed = self._coordinator.renew(claim, now=now)
        self._append_event(
            TraceEventKind.LEASE_RENEWED,
            key_digest=renewed.key_digest,
            payload=renewed.to_dict(),
            timestamp=self.now() if now is None else float(now),
        )
        return renewed

    def release_lease(
        self,
        claim: ProofFenceClaim,
        *,
        now: float | None = None,
    ) -> None:
        self._coordinator.release(claim, now=now)
        self._append_event(
            TraceEventKind.LEASE_RELEASED,
            key_digest=claim.key_digest,
            payload={"claim_id": claim.claim_id},
            timestamp=self.now() if now is None else float(now),
        )

    # -- draft / attested publication ----------------------------------------

    def publish_draft(
        self,
        claim: ProofFenceClaim,
        entry: UnifiedProofEntry | VerificationCacheEntry | TypedBackendResult,
        *,
        key: UnifiedProofKey | None = None,
        plan_id: str = "",
        node_id: str = "",
        now: float | None = None,
    ) -> ServiceOperationResult:
        """Publish a draft (non-attested) entry under a live fence.

        Draft trust is capped at ADVISORY.  Without attached evidence the trust
        band is forced to NON_TRUSTED.  Promotion to attested/trusted authority
        requires :meth:`upgrade_authority` or :meth:`publish_attested` with
        evidence receipts.
        """

        unified_key, unified_entry = self._coerce_entry(
            claim, entry, key=key, now=now
        )
        if trust_rank(unified_entry.trust_level) > trust_rank(
            ProofTrustLevel.ADVISORY
        ):
            raise DuckDBProofServiceAuthorityError(
                "draft publication refuses above-advisory trust; use "
                "publish_attested or upgrade_authority"
            )
        if not unified_entry.evidence:
            # Provisional cache records never carry trusted authority.
            if (
                unified_entry.trust_level is not ProofTrustLevel.NON_TRUSTED
                or unified_entry.evidence_authority is not EvidenceAuthority.NONE
            ):
                unified_entry = self._rebuild_entry(
                    unified_entry,
                    trust_level=ProofTrustLevel.NON_TRUSTED,
                    evidence_authority=EvidenceAuthority.NONE,
                )
        else:
            # Evidence on a draft is allowed only through the advisory ceiling.
            ceiling = trust_level_from_evidence(
                unified_entry.evidence_authority
            )
            allowed = min_trust(ProofTrustLevel.ADVISORY, ceiling)
            if trust_rank(unified_entry.trust_level) > trust_rank(allowed):
                unified_entry = self._rebuild_entry(
                    unified_entry,
                    trust_level=allowed,
                    evidence_authority=unified_entry.evidence_authority,
                    evidence=unified_entry.evidence,
                )

        plan_policy = {}
        plan = self.get_plan(plan_id) if plan_id else None
        if plan is not None:
            plan_policy = (
                dict(plan.policy)
                if hasattr(plan.policy, "items")
                else {}
            )
        gate = self.evaluate_policy_gate(
            PolicyGateAction.PUBLISH_DRAFT,
            key=unified_key,
            plan_id=plan_id,
            node_id=node_id,
            entry=unified_entry,
            plan_policy=plan_policy,
        )
        if not gate.allowed:
            raise DuckDBProofServicePolicyError(gate.reason)

        coord = self._coordinator.publish(
            claim, unified_entry, key=unified_key, now=now
        )
        with self._lock:
            self._stats["drafts_published"] += 1
            if plan_id and node_id:
                self._update_node_locked(
                    plan_id,
                    node_id,
                    status=PlanNodeStatus.DRAFT.value,
                    entry_digest=unified_entry.entry_digest,
                    publication_mode=EntryPublicationMode.DRAFT.value,
                    claim_id=claim.claim_id,
                )
        self._append_event(
            TraceEventKind.DRAFT_PUBLISHED,
            plan_id=plan_id,
            node_id=node_id,
            key_digest=unified_key.digest,
            payload={
                "entry_digest": unified_entry.entry_digest,
                "trust_level": unified_entry.trust_level.value,
                "outcome": unified_entry.outcome.value,
            },
            timestamp=self.now() if now is None else float(now),
        )
        return ServiceOperationResult(
            ok=True,
            action="publish_draft",
            key_digest=unified_key.digest,
            plan_id=plan_id,
            node_id=node_id,
            entry=unified_entry,
            claim=coord.claim,
            attempt=coord.attempt,
            gate=gate,
            coordination=coord,
            reason="draft_published",
        )

    def publish_attested(
        self,
        claim: ProofFenceClaim,
        entry: UnifiedProofEntry | VerificationCacheEntry | TypedBackendResult,
        evidence_receipts: Sequence[EvidenceReceipt],
        *,
        key: UnifiedProofKey | None = None,
        plan_id: str = "",
        node_id: str = "",
        envelope: ImmutableEnvelopeReference | None = None,
        now: float | None = None,
    ) -> ServiceOperationResult:
        """Publish an attested entry; evidence receipts are mandatory."""

        unified_key, unified_entry = self._coerce_entry(
            claim, entry, key=key, now=now
        )
        receipts = tuple(evidence_receipts or ())
        if not receipts:
            raise DuckDBProofServiceAuthorityError(
                "publish_attested requires evidence receipts"
            )
        for receipt in receipts:
            if not isinstance(receipt, EvidenceReceipt):
                raise DuckDBProofServiceError(
                    "evidence_receipts items must be EvidenceReceipt instances"
                )
            if receipt.key_digest != unified_key.digest:
                raise DuckDBProofServiceAuthorityError(
                    f"evidence receipt {receipt.receipt_id} is not bound to "
                    f"key {unified_key.digest}"
                )

        projected_trust = _max_projected_trust(receipts)
        # Trust cannot exceed evidence; also refuse non-trusted attested path.
        if projected_trust in {
            ProofTrustLevel.NONE,
            ProofTrustLevel.NON_TRUSTED,
        }:
            raise DuckDBProofServiceAuthorityError(
                "attested publication requires evidence that projects above "
                "non-trusted trust"
            )
        # Caller's requested trust is the entry's trust, clamped to evidence.
        requested = unified_entry.trust_level
        if requested in {ProofTrustLevel.NONE, ProofTrustLevel.NON_TRUSTED}:
            target_trust = projected_trust
        else:
            target_trust = min_trust(requested, projected_trust)

        plan_policy = {}
        plan = self.get_plan(plan_id) if plan_id else None
        if plan is not None:
            plan_policy = (
                dict(plan.policy) if hasattr(plan.policy, "items") else {}
            )
        gate = self.evaluate_policy_gate(
            PolicyGateAction.PUBLISH_ATTESTED,
            key=unified_key,
            plan_id=plan_id,
            node_id=node_id,
            entry=unified_entry,
            evidence_receipts=receipts,
            target_trust=target_trust,
            plan_policy=plan_policy,
        )
        if gate.verdict is PolicyGateVerdict.REQUIRE_EVIDENCE:
            raise DuckDBProofServiceAuthorityError(gate.reason)
        if not gate.allowed:
            raise DuckDBProofServicePolicyError(gate.reason)

        evidence_records = tuple(receipt.evidence for receipt in receipts)
        max_evidence = _max_evidence_authority(receipts)
        attested = self._rebuild_entry(
            unified_entry,
            trust_level=target_trust,
            evidence_authority=max_evidence,
            evidence=evidence_records,
            envelope=envelope if envelope is not None else unified_entry.envelope,
        )

        coord = self._coordinator.publish(
            claim, attested, key=unified_key, now=now
        )
        with self._lock:
            self._stats["attested_published"] += 1
            self._store_receipts_locked(unified_key.digest, receipts)
            if plan_id and node_id:
                self._update_node_locked(
                    plan_id,
                    node_id,
                    status=PlanNodeStatus.ATTESTED.value,
                    entry_digest=attested.entry_digest,
                    publication_mode=EntryPublicationMode.ATTESTED.value,
                    claim_id=claim.claim_id,
                )
        self._append_event(
            TraceEventKind.ATTESTED_PUBLISHED,
            plan_id=plan_id,
            node_id=node_id,
            key_digest=unified_key.digest,
            payload={
                "entry_digest": attested.entry_digest,
                "trust_level": attested.trust_level.value,
                "receipt_ids": [r.receipt_id for r in receipts],
            },
            timestamp=self.now() if now is None else float(now),
        )
        for receipt in receipts:
            self._append_event(
                TraceEventKind.EVIDENCE_ATTACHED,
                plan_id=plan_id,
                node_id=node_id,
                key_digest=unified_key.digest,
                payload=receipt.to_dict(),
                timestamp=self.now() if now is None else float(now),
            )
        return ServiceOperationResult(
            ok=True,
            action="publish_attested",
            key_digest=unified_key.digest,
            plan_id=plan_id,
            node_id=node_id,
            entry=attested,
            claim=coord.claim,
            attempt=coord.attempt,
            gate=gate,
            receipt=receipts[0],
            coordination=coord,
            reason="attested_published",
        )

    def upgrade_authority(
        self,
        key: UnifiedProofKey | str,
        *,
        target_trust: ProofTrustLevel | str,
        evidence_receipts: Sequence[EvidenceReceipt],
        claim: ProofFenceClaim | None = None,
        plan_id: str = "",
        node_id: str = "",
        owner_id: str | None = None,
        now: float | None = None,
    ) -> ServiceOperationResult:
        """Raise cached trust only when evidence receipts justify the target.

        Authority upgrades without evidence are a hard error.  The target trust
        must not exceed the maximum trust projected from the receipts.
        """

        target = _enum(target_trust, ProofTrustLevel, "target_trust")
        receipts = tuple(evidence_receipts or ())
        if not receipts:
            with self._lock:
                self._stats["authority_upgrade_rejections"] += 1
            raise DuckDBProofServiceAuthorityError(
                "authority upgrades require evidence receipts"
            )

        unified = self._resolve_key(key)
        current = self.now() if now is None else float(now)
        existing = self._store.get(unified, now=current)
        if existing is None:
            with self._lock:
                self._stats["authority_upgrade_rejections"] += 1
            raise DuckDBProofServiceAuthorityError(
                f"no cached entry for key {unified.digest}; publish before upgrade"
            )

        if trust_rank(target) <= trust_rank(existing.trust_level):
            with self._lock:
                self._stats["authority_upgrade_rejections"] += 1
            raise DuckDBProofServiceAuthorityError(
                f"target trust {target.value} does not exceed current "
                f"{existing.trust_level.value}"
            )

        for receipt in receipts:
            if not isinstance(receipt, EvidenceReceipt):
                raise DuckDBProofServiceError(
                    "evidence_receipts items must be EvidenceReceipt instances"
                )
            if receipt.key_digest != unified.digest:
                with self._lock:
                    self._stats["authority_upgrade_rejections"] += 1
                raise DuckDBProofServiceAuthorityError(
                    f"evidence receipt {receipt.receipt_id} is not bound to "
                    f"key {unified.digest}"
                )

        projected = _max_projected_trust(receipts)
        if trust_rank(projected) < trust_rank(target):
            with self._lock:
                self._stats["authority_upgrade_rejections"] += 1
            raise DuckDBProofServiceAuthorityError(
                f"evidence projects to {projected.value} which does not cover "
                f"target trust {target.value}"
            )

        plan_policy = {}
        plan = self.get_plan(plan_id) if plan_id else None
        if plan is not None:
            plan_policy = (
                dict(plan.policy) if hasattr(plan.policy, "items") else {}
            )
        gate = self.evaluate_policy_gate(
            PolicyGateAction.UPGRADE_AUTHORITY,
            key=unified,
            plan_id=plan_id,
            node_id=node_id,
            entry=existing,
            evidence_receipts=receipts,
            target_trust=target,
            plan_policy=plan_policy,
        )
        if gate.verdict is PolicyGateVerdict.REQUIRE_EVIDENCE:
            with self._lock:
                self._stats["authority_upgrade_rejections"] += 1
            raise DuckDBProofServiceAuthorityError(gate.reason)
        if not gate.allowed:
            with self._lock:
                self._stats["authority_upgrade_rejections"] += 1
            raise DuckDBProofServicePolicyError(gate.reason)

        evidence_records = existing.evidence + tuple(
            receipt.evidence for receipt in receipts
        )
        # De-duplicate by evidence_id preserving order.
        seen_ids: set[str] = set()
        merged: list[ProofEvidenceRecord] = []
        for record in evidence_records:
            if record.evidence_id in seen_ids:
                continue
            seen_ids.add(record.evidence_id)
            merged.append(record)

        max_evidence = _max_evidence_authority(receipts)
        # Keep the stronger of existing vs receipt evidence authority.
        if trust_rank(
            trust_level_from_evidence(existing.evidence_authority)
        ) > trust_rank(trust_level_from_evidence(max_evidence)):
            max_evidence = existing.evidence_authority

        upgraded = self._rebuild_entry(
            existing,
            trust_level=target,
            evidence_authority=max_evidence,
            evidence=tuple(merged),
        )

        # Authority upgrades mutate existing cache authority under policy +
        # evidence.  They are not a fresh single-flight production: writing
        # through the store avoids handoff/fence contention with the draft
        # publisher.  An optional live claim is accepted for audit linkage only.
        active_claim = claim
        if active_claim is not None:
            if (
                not active_claim.acquired
                or active_claim.key_digest != unified.digest
            ):
                with self._lock:
                    self._stats["authority_upgrade_rejections"] += 1
                raise DuckDBProofServiceError(
                    "upgrade claim must be a live owner fence for the key"
                )
        lookup = self._store.put(upgraded, now=current)

        with self._lock:
            self._stats["authority_upgrades"] += 1
            self._store_receipts_locked(unified.digest, receipts)
            if plan_id and node_id:
                self._update_node_locked(
                    plan_id,
                    node_id,
                    status=PlanNodeStatus.ATTESTED.value,
                    entry_digest=upgraded.entry_digest,
                    publication_mode=EntryPublicationMode.ATTESTED.value,
                )
        self._append_event(
            TraceEventKind.AUTHORITY_UPGRADED,
            plan_id=plan_id,
            node_id=node_id,
            key_digest=unified.digest,
            payload={
                "from_trust": existing.trust_level.value,
                "to_trust": upgraded.trust_level.value,
                "entry_digest": upgraded.entry_digest,
                "receipt_ids": [r.receipt_id for r in receipts],
                "owner_id": owner_id or self._owner_id,
            },
            timestamp=current,
        )
        for receipt in receipts:
            self._append_event(
                TraceEventKind.EVIDENCE_ATTACHED,
                plan_id=plan_id,
                node_id=node_id,
                key_digest=unified.digest,
                payload=receipt.to_dict(),
                timestamp=current,
            )
        return ServiceOperationResult(
            ok=bool(lookup.usable or lookup.hit or True),
            action="upgrade_authority",
            key_digest=unified.digest,
            plan_id=plan_id,
            node_id=node_id,
            entry=upgraded,
            claim=active_claim,
            gate=gate,
            receipt=receipts[0],
            reason="authority_upgraded",
        )

    def attach_evidence_receipt(
        self,
        receipt: EvidenceReceipt | Mapping[str, Any],
    ) -> EvidenceReceipt:
        """Record an evidence receipt without changing entry authority."""

        if isinstance(receipt, Mapping):
            receipt = EvidenceReceipt.from_dict(receipt)
        if not isinstance(receipt, EvidenceReceipt):
            raise DuckDBProofServiceError("receipt must be an EvidenceReceipt")
        with self._lock:
            self._store_receipts_locked(receipt.key_digest, (receipt,))
            self._stats["evidence_receipts"] += 1
        self._append_event(
            TraceEventKind.EVIDENCE_ATTACHED,
            key_digest=receipt.key_digest,
            payload=receipt.to_dict(),
        )
        return receipt

    def evidence_receipts_for(
        self, key: UnifiedProofKey | str
    ) -> tuple[EvidenceReceipt, ...]:
        digest = _key_digest(key)
        with self._lock:
            return tuple(self._receipts.get(digest, ()))

    # -- lookup / invalidate -------------------------------------------------

    def lookup(
        self,
        key: UnifiedProofKey | VerificationCacheKey | str,
        **kwargs: Any,
    ) -> VerificationCacheLookup:
        if isinstance(key, str):
            # Digest-only lookup is not supported by the store; miss closed.
            return VerificationCacheLookup(
                entry=None,
                hit=False,
                usable=False,
                reason=CacheLookupReason.MISS,
                key_digest=key,
            )
        return self._coordinator.lookup(key, **kwargs)

    def get(
        self,
        key: UnifiedProofKey | VerificationCacheKey,
        **kwargs: Any,
    ) -> UnifiedProofEntry | None:
        return self._coordinator.get(key, **kwargs)

    def invalidate(
        self,
        key: UnifiedProofKey | VerificationCacheKey | str,
        *,
        reason: str = "explicit",
        plan_id: str = "",
        node_id: str = "",
        now: float | None = None,
    ) -> bool:
        from .duckdb_proof_coordination import InvalidationReason

        if isinstance(key, str):
            # Prefer digest-native invalidation when the coordinator supports it.
            resolved: UnifiedProofKey | VerificationCacheKey | str = key
        else:
            resolved = key
        try:
            invalidation_reason = InvalidationReason(reason)
        except ValueError:
            invalidation_reason = InvalidationReason.EXPLICIT
        result = self._coordinator.invalidate(
            resolved, reason=invalidation_reason, now=now
        )
        if result:
            digest = _key_digest(resolved) if not isinstance(resolved, str) else resolved
            with self._lock:
                if plan_id and node_id:
                    try:
                        self._update_node_locked(
                            plan_id,
                            node_id,
                            status=PlanNodeStatus.INVALIDATED.value,
                        )
                    except DuckDBProofServiceError:
                        pass
            self._append_event(
                TraceEventKind.INVALIDATED,
                plan_id=plan_id,
                node_id=node_id,
                key_digest=digest,
                payload={"reason": invalidation_reason.value},
                timestamp=self.now() if now is None else float(now),
            )
        return result

    # -- scheduler traces / replay -------------------------------------------

    def export_trace(
        self,
        *,
        plan_id: str | None = None,
        trace_id: str | None = None,
    ) -> SchedulerTrace:
        """Export the in-memory scheduler trace (optionally filtered by plan)."""

        with self._lock:
            events = list(self._trace_events)
            active_id = self._active_trace_id
            self._stats["traces_exported"] += 1
        if plan_id is not None:
            events = [e for e in events if e.plan_id == plan_id]
        # Re-sequence for a self-contained export.
        renumbered = tuple(
            SchedulerTraceEvent(
                event_id=event.event_id,
                kind=event.kind,
                timestamp=event.timestamp,
                plan_id=event.plan_id,
                node_id=event.node_id,
                key_digest=event.key_digest,
                payload=dict(event.payload)
                if hasattr(event.payload, "items")
                else {},
                sequence=index,
            )
            for index, event in enumerate(events)
        )
        return SchedulerTrace(
            trace_id=trace_id or active_id,
            events=renumbered,
            plan_id=plan_id or "",
            created_at=self.now(),
        )

    def replay_trace(
        self,
        trace: SchedulerTrace | Mapping[str, Any],
        *,
        reset: bool = True,
    ) -> SchedulerTraceReplayResult:
        """Replay a proof scheduler trace and verify deterministic outcomes.

        Replay re-applies plan registration, draft/attested publications, and
        authority upgrades recorded in the trace against a fresh (or current)
        service state.  Lease claim fence tokens from the original run are not
        reused; equivalent coordination effects are re-derived.
        """

        if isinstance(trace, Mapping):
            trace = SchedulerTrace.from_dict(trace)
        if not isinstance(trace, SchedulerTrace):
            raise DuckDBProofServiceReplayError("trace must be a SchedulerTrace")

        gate = self.evaluate_policy_gate(PolicyGateAction.REPLAY_TRACE)
        if not gate.allowed:
            raise DuckDBProofServicePolicyError(gate.reason)

        if reset:
            self.clear_runtime_state(clear_store=True)

        source_digest = trace.digest
        divergences: list[str] = []
        # Materialize plan from PLAN_REGISTERED / NODE_SCHEDULED events.
        plan_nodes: dict[str, dict[str, Any]] = {}
        plan_meta: dict[str, Any] = {"plan_id": trace.plan_id, "family": "common"}
        # Pending publications keyed by node for later claim/publish.
        node_keys: dict[str, UnifiedProofKey] = {}
        final_statuses: dict[str, str] = {}
        events_replayed = 0

        for event in trace.events:
            events_replayed += 1
            kind = event.kind
            payload = (
                dict(event.payload)
                if hasattr(event.payload, "items")
                else dict(event.payload or {})
            )
            try:
                if kind is TraceEventKind.PLAN_REGISTERED:
                    plan_meta["plan_id"] = event.plan_id or payload.get(
                        "plan_id", plan_meta.get("plan_id", "")
                    )
                    plan_meta["family"] = payload.get(
                        "family", plan_meta.get("family", "common")
                    )
                    for node_id in payload.get("node_ids") or ():
                        plan_nodes.setdefault(str(node_id), {"node_id": str(node_id)})
                elif kind is TraceEventKind.NODE_SCHEDULED:
                    node_id = event.node_id or str(payload.get("node_id") or "")
                    if not node_id:
                        divergences.append(
                            f"seq={event.sequence}: NODE_SCHEDULED missing node_id"
                        )
                        continue
                    node_payload = plan_nodes.setdefault(
                        node_id, {"node_id": node_id}
                    )
                    if event.key_digest:
                        node_payload["key_digest"] = event.key_digest
                    if "family" in payload:
                        node_payload["family"] = payload["family"]
                    if "key" in payload and isinstance(payload["key"], Mapping):
                        key = UnifiedProofKey.from_dict(payload["key"])
                        node_payload["key"] = key
                        node_keys[node_id] = key
                elif kind is TraceEventKind.DRAFT_PUBLISHED:
                    self._replay_publish(
                        event,
                        payload,
                        plan_meta,
                        plan_nodes,
                        node_keys,
                        mode=EntryPublicationMode.DRAFT,
                        final_statuses=final_statuses,
                        divergences=divergences,
                    )
                elif kind is TraceEventKind.ATTESTED_PUBLISHED:
                    self._replay_publish(
                        event,
                        payload,
                        plan_meta,
                        plan_nodes,
                        node_keys,
                        mode=EntryPublicationMode.ATTESTED,
                        final_statuses=final_statuses,
                        divergences=divergences,
                    )
                elif kind is TraceEventKind.AUTHORITY_UPGRADED:
                    self._replay_upgrade(
                        event,
                        payload,
                        node_keys,
                        final_statuses=final_statuses,
                        divergences=divergences,
                    )
                elif kind is TraceEventKind.EVIDENCE_ATTACHED:
                    if "receipt_id" in payload or "evidence" in payload:
                        try:
                            receipt = EvidenceReceipt.from_dict(payload)
                            self.attach_evidence_receipt(receipt)
                        except DuckDBProofServiceError as error:
                            divergences.append(
                                f"seq={event.sequence}: evidence attach failed: "
                                f"{error}"
                            )
                elif kind is TraceEventKind.INVALIDATED:
                    key_digest = event.key_digest or str(
                        payload.get("key_digest") or ""
                    )
                    if key_digest:
                        self.invalidate(
                            key_digest,
                            reason=str(payload.get("reason") or "replay"),
                            plan_id=event.plan_id,
                            node_id=event.node_id,
                        )
                        if event.node_id:
                            final_statuses[event.node_id] = (
                                PlanNodeStatus.INVALIDATED.value
                            )
                elif kind in {
                    TraceEventKind.LEASE_CLAIMED,
                    TraceEventKind.LEASE_RENEWED,
                    TraceEventKind.LEASE_RELEASED,
                    TraceEventKind.POLICY_GATE,
                    TraceEventKind.NODE_COMPLETED,
                    TraceEventKind.NODE_FAILED,
                    TraceEventKind.TRACE_MARK,
                }:
                    # Informational for replay fidelity; coordination is
                    # re-derived on publish/upgrade events.
                    if kind is TraceEventKind.NODE_COMPLETED and event.node_id:
                        final_statuses.setdefault(
                            event.node_id, PlanNodeStatus.ATTESTED.value
                        )
                    if kind is TraceEventKind.NODE_FAILED and event.node_id:
                        final_statuses[event.node_id] = PlanNodeStatus.FAILED.value
                else:
                    divergences.append(
                        f"seq={event.sequence}: unhandled kind {kind.value}"
                    )
            except (
                DuckDBProofServiceError,
                DuckDBProofStoreError,
                DuckDBProofCoordinationError,
            ) as error:
                divergences.append(f"seq={event.sequence}: {error}")

        # Ensure plan exists when we only saw NODE_SCHEDULED events with keys.
        if plan_nodes and (
            plan_meta.get("plan_id")
            and self.get_plan(str(plan_meta["plan_id"])) is None
        ):
            try:
                self._materialize_plan_from_nodes(plan_meta, plan_nodes, node_keys)
            except DuckDBProofServiceError as error:
                divergences.append(f"plan materialization failed: {error}")

        replay_export = self.export_trace(
            plan_id=trace.plan_id or None,
            trace_id=_new_id("replay"),
        )
        # Compare semantic fingerprints (kinds + key digests + payloads of
        # authority-bearing events), not fence tokens.
        matched = not divergences and _traces_semantically_match(trace, replay_export)
        if not matched and not divergences:
            divergences.append("semantic fingerprint mismatch after replay")

        with self._lock:
            self._stats["traces_replayed"] += 1
            if matched:
                self._stats["replay_matches"] += 1
            else:
                self._stats["replay_divergences"] += 1

        return SchedulerTraceReplayResult(
            source_trace_id=trace.trace_id,
            source_digest=source_digest,
            replay_trace_id=replay_export.trace_id,
            replay_digest=replay_export.digest,
            matched=matched,
            events_replayed=events_replayed,
            divergences=tuple(divergences),
            final_node_statuses=MappingProxyType(dict(final_statuses)),
        )

    def _materialize_plan_from_nodes(
        self,
        plan_meta: Mapping[str, Any],
        plan_nodes: Mapping[str, Mapping[str, Any]],
        node_keys: Mapping[str, UnifiedProofKey],
    ) -> ProofPlan:
        nodes: list[ProofPlanNode] = []
        for node_id, meta in plan_nodes.items():
            key = node_keys.get(node_id) or meta.get("key")
            if isinstance(key, Mapping):
                key = UnifiedProofKey.from_dict(key)
            if not isinstance(key, UnifiedProofKey):
                raise DuckDBProofServiceReplayError(
                    f"cannot materialize node {node_id!r} without a key"
                )
            family = meta.get("family") or plan_meta.get("family") or "common"
            nodes.append(
                ProofPlanNode(
                    node_id=node_id,
                    key=key,
                    family=family,
                    depends_on=tuple(meta.get("depends_on") or ()),
                )
            )
        plan = ProofPlan(
            plan_id=str(plan_meta.get("plan_id") or _new_id("plan")),
            nodes=tuple(nodes),
            family=str(plan_meta.get("family") or "common"),
            created_at=self.now(),
            policy=dict(plan_meta.get("policy") or {}),
        )
        return self.register_plan(plan)

    def _replay_publish(
        self,
        event: SchedulerTraceEvent,
        payload: Mapping[str, Any],
        plan_meta: dict[str, Any],
        plan_nodes: dict[str, dict[str, Any]],
        node_keys: dict[str, UnifiedProofKey],
        *,
        mode: EntryPublicationMode,
        final_statuses: dict[str, str],
        divergences: list[str],
    ) -> None:
        node_id = event.node_id
        plan_id = event.plan_id or str(plan_meta.get("plan_id") or "")
        key = node_keys.get(node_id) if node_id else None
        if key is None and event.key_digest:
            # Try to recover key from prior node schedule payload.
            for nid, meta in plan_nodes.items():
                stored = meta.get("key")
                if isinstance(stored, UnifiedProofKey) and stored.digest == event.key_digest:
                    key = stored
                    node_id = node_id or nid
                    break
                if isinstance(stored, Mapping):
                    try:
                        candidate = UnifiedProofKey.from_dict(stored)
                    except DuckDBProofStoreError:
                        continue
                    if candidate.digest == event.key_digest:
                        key = candidate
                        node_id = node_id or nid
                        break
        if key is None:
            divergences.append(
                f"seq={event.sequence}: {mode.value} publish missing key"
            )
            return
        if plan_id and node_id and self.get_plan(plan_id) is None:
            plan_nodes.setdefault(node_id, {"node_id": node_id, "key": key})
            node_keys[node_id] = key
            try:
                self._materialize_plan_from_nodes(plan_meta, plan_nodes, node_keys)
            except DuckDBProofServiceError as error:
                divergences.append(f"seq={event.sequence}: {error}")
                return

        # Use wall-clock for entry created_at so dual-TTL does not treat
        # historical event timestamps as already expired.
        created_at = self.now()
        if mode is EntryPublicationMode.DRAFT:
            # Drafts preserve conclusive outcomes but stay non-trusted.
            entry = UnifiedProofEntry(
                key=key,
                outcome=ProofOutcomeKind.PROOF,
                trust_level=ProofTrustLevel.NON_TRUSTED,
                status=ResultStatus.PROVED,
                result_authority=ResultAuthority.THEOREM,
                evidence_authority=EvidenceAuthority.NONE,
                result_payload=FrozenMap(
                    {"replay": True, "source_event": event.event_id}
                ),
                polarity=CachePolarity.POSITIVE,
                created_at=created_at,
            )
        else:
            trust_level = payload.get(
                "trust_level",
                ProofTrustLevel.INDEPENDENTLY_CHECKABLE.value,
            )
            entry = UnifiedProofEntry(
                key=key,
                outcome=ProofOutcomeKind.PROOF,
                trust_level=trust_level,
                status=ResultStatus.PROVED,
                result_authority=ResultAuthority.THEOREM,
                evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
                result_payload=FrozenMap(
                    {"replay": True, "source_event": event.event_id}
                ),
                polarity=CachePolarity.POSITIVE,
                created_at=created_at,
            )

        now = self.now()
        claim = self._coordinator.claim(key, owner_id=self._owner_id, now=now)
        if not claim.acquired:
            # Recover when a prior replay step left a published handoff.
            active = self._coordinator.active_claim(key, now=now)
            if active is not None:
                try:
                    self._coordinator.abandon(active, now=now)
                except DuckDBProofCoordinationError:
                    pass
                # Invalidate handoff window by advancing past it.
                self._coordinator.invalidate(key, now=now)
            claim = self._coordinator.claim(
                key, owner_id=self._owner_id, now=now + 0.001
            )
        if not claim.acquired:
            divergences.append(
                f"seq={event.sequence}: could not acquire claim for replay publish"
            )
            return

        try:
            if mode is EntryPublicationMode.DRAFT:
                self.publish_draft(
                    claim,
                    entry,
                    key=key,
                    plan_id=plan_id,
                    node_id=node_id or "",
                    now=now,
                )
                if node_id:
                    final_statuses[node_id] = PlanNodeStatus.DRAFT.value
            else:
                # Build synthetic receipts from payload when present.
                receipt_ids = list(payload.get("receipt_ids") or ())
                receipts: list[EvidenceReceipt] = []
                for receipt_id in receipt_ids:
                    existing = [
                        r
                        for r in self.evidence_receipts_for(key)
                        if r.receipt_id == receipt_id
                    ]
                    if existing:
                        receipts.extend(existing)
                if not receipts:
                    trust = payload.get(
                        "trust_level",
                        ProofTrustLevel.INDEPENDENTLY_CHECKABLE.value,
                    )
                    auth = _evidence_for_trust(
                        _enum(trust, ProofTrustLevel, "trust_level")
                    )
                    receipts.append(
                        EvidenceReceipt.build(
                            key=key,
                            evidence_kind="replay_attestation",
                            evidence_authority=auth,
                            payload={"replay": True, "event_id": event.event_id},
                            issued_at=now,
                        )
                    )
                projected = _max_projected_trust(receipts)
                attested_entry = UnifiedProofEntry(
                    key=key,
                    outcome=ProofOutcomeKind.PROOF,
                    trust_level=min_trust(
                        payload.get(
                            "trust_level",
                            ProofTrustLevel.INDEPENDENTLY_CHECKABLE.value,
                        ),
                        projected,
                    ),
                    status=ResultStatus.PROVED,
                    result_authority=ResultAuthority.THEOREM,
                    evidence_authority=_max_evidence_authority(receipts),
                    result_payload=FrozenMap(
                        {"replay": True, "source_event": event.event_id}
                    ),
                    polarity=CachePolarity.POSITIVE,
                    created_at=created_at,
                    evidence=tuple(r.evidence for r in receipts),
                )
                self.publish_attested(
                    claim,
                    attested_entry,
                    receipts,
                    key=key,
                    plan_id=plan_id,
                    node_id=node_id or "",
                    now=now,
                )
                if node_id:
                    final_statuses[node_id] = PlanNodeStatus.ATTESTED.value
        except (
            DuckDBProofServiceError,
            DuckDBProofStoreError,
            DuckDBProofCoordinationError,
        ) as error:
            divergences.append(f"seq={event.sequence}: publish failed: {error}")

    def _replay_upgrade(
        self,
        event: SchedulerTraceEvent,
        payload: Mapping[str, Any],
        node_keys: Mapping[str, UnifiedProofKey],
        *,
        final_statuses: dict[str, str],
        divergences: list[str],
    ) -> None:
        key = None
        if event.node_id and event.node_id in node_keys:
            key = node_keys[event.node_id]
        if key is None and event.key_digest:
            for candidate in node_keys.values():
                if candidate.digest == event.key_digest:
                    key = candidate
                    break
        if key is None:
            divergences.append(
                f"seq={event.sequence}: authority upgrade missing key"
            )
            return
        to_trust = payload.get(
            "to_trust", ProofTrustLevel.INDEPENDENTLY_CHECKABLE.value
        )
        target = _enum(to_trust, ProofTrustLevel, "to_trust")
        receipts = list(self.evidence_receipts_for(key))
        if not receipts:
            receipts.append(
                EvidenceReceipt.build(
                    key=key,
                    evidence_kind="replay_upgrade",
                    evidence_authority=_evidence_for_trust(target),
                    payload={"replay": True, "event_id": event.event_id},
                    issued_at=event.timestamp,
                )
            )
        try:
            self.upgrade_authority(
                key,
                target_trust=target,
                evidence_receipts=receipts,
                plan_id=event.plan_id,
                node_id=event.node_id,
                now=self.now(),
            )
            if event.node_id:
                final_statuses[event.node_id] = PlanNodeStatus.ATTESTED.value
        except (
            DuckDBProofServiceError,
            DuckDBProofStoreError,
            DuckDBProofCoordinationError,
        ) as error:
            divergences.append(f"seq={event.sequence}: upgrade failed: {error}")

    # -- internals -----------------------------------------------------------

    def _append_event(
        self,
        kind: TraceEventKind,
        *,
        plan_id: str = "",
        node_id: str = "",
        key_digest: str = "",
        payload: Mapping[str, Any] | None = None,
        timestamp: float | None = None,
    ) -> SchedulerTraceEvent:
        with self._lock:
            self._trace_seq += 1
            event = SchedulerTraceEvent(
                event_id=_new_id("evt"),
                kind=kind,
                timestamp=self.now() if timestamp is None else float(timestamp),
                plan_id=plan_id,
                node_id=node_id,
                key_digest=key_digest,
                payload=dict(payload or {}),
                sequence=self._trace_seq,
            )
            self._trace_events.append(event)
            if len(self._trace_events) > self._max_trace_events:
                overflow = len(self._trace_events) - self._max_trace_events
                del self._trace_events[:overflow]
            return event

    def _store_receipts_locked(
        self, key_digest: str, receipts: Sequence[EvidenceReceipt]
    ) -> None:
        bucket = self._receipts.setdefault(key_digest, [])
        known = {item.receipt_id for item in bucket}
        for receipt in receipts:
            if receipt.receipt_id not in known:
                bucket.append(receipt)
                known.add(receipt.receipt_id)
                self._stats["evidence_receipts"] += 1

    def _resolve_key(
        self, key: UnifiedProofKey | VerificationCacheKey | str
    ) -> UnifiedProofKey:
        if isinstance(key, UnifiedProofKey):
            return key
        if isinstance(key, VerificationCacheKey):
            return UnifiedProofKey.from_verification_cache_key(key)
        # Digest string: recover from node index.
        with self._lock:
            location = self._node_index.get(key)
            if location is not None:
                plan = self._plans.get(location[0])
                if plan is not None:
                    node = plan.node_map().get(location[1])
                    if node is not None:
                        return node.key
        raise DuckDBProofServiceError(
            f"cannot resolve key digest {key!r} to a UnifiedProofKey"
        )

    def _coerce_entry(
        self,
        claim: ProofFenceClaim,
        entry: UnifiedProofEntry | VerificationCacheEntry | TypedBackendResult,
        *,
        key: UnifiedProofKey | None,
        now: float | None,
    ) -> tuple[UnifiedProofKey, UnifiedProofEntry]:
        current = self.now() if now is None else float(now)
        if isinstance(entry, UnifiedProofEntry):
            unified_entry = entry
            unified_key = key or entry.key
        elif isinstance(entry, VerificationCacheEntry):
            unified_entry = UnifiedProofEntry.from_verification_cache_entry(entry)
            unified_key = key or unified_entry.key
        elif isinstance(entry, TypedBackendResult):
            if key is None:
                raise DuckDBProofServiceError(
                    "key is required when publishing a TypedBackendResult"
                )
            unified_key = key
            unified_entry = UnifiedProofEntry.from_typed_result(
                key, entry, created_at=current
            )
        else:
            raise TypeError(
                "entry must be UnifiedProofEntry, VerificationCacheEntry, "
                "or TypedBackendResult"
            )
        if unified_key.digest != claim.key_digest:
            raise DuckDBProofServiceError(
                "entry key digest does not match claim key_digest"
            )
        return unified_key, unified_entry

    def _rebuild_entry(
        self,
        entry: UnifiedProofEntry,
        *,
        trust_level: ProofTrustLevel | str | None = None,
        evidence_authority: EvidenceAuthority | str | None = None,
        evidence: Sequence[ProofEvidenceRecord] | None = None,
        envelope: ImmutableEnvelopeReference | None = None,
        result_authority: ResultAuthority | str | None = None,
        status: ResultStatus | str | None = None,
    ) -> UnifiedProofEntry:
        """Rebuild an entry with authority/evidence changes (rehashed)."""

        new_status = (
            entry.status
            if status is None
            else _enum(status, ResultStatus, "status")
        )
        new_outcome = outcome_kind_for_status(new_status)
        new_trust = (
            entry.trust_level
            if trust_level is None
            else _enum(trust_level, ProofTrustLevel, "trust_level")
        )
        new_evidence_auth = (
            entry.evidence_authority
            if evidence_authority is None
            else (
                evidence_authority
                if isinstance(evidence_authority, EvidenceAuthority)
                else EvidenceAuthority(str(evidence_authority))
            )
        )
        new_result_auth = (
            entry.result_authority
            if result_authority is None
            else (
                result_authority
                if isinstance(result_authority, ResultAuthority)
                else ResultAuthority(str(result_authority))
            )
        )
        new_evidence = (
            entry.evidence if evidence is None else tuple(evidence)
        )
        new_envelope = entry.envelope if envelope is None else envelope
        return UnifiedProofEntry(
            key=entry.key,
            outcome=new_outcome,
            trust_level=new_trust,
            status=new_status,
            result_authority=new_result_auth,
            evidence_authority=new_evidence_auth,
            result_payload=entry.result_payload,
            polarity=polarity_for_outcome(new_outcome),
            created_at=entry.created_at,
            result_id=entry.result_id,
            diagnostics=entry.diagnostics,
            evidence=new_evidence,
            envelope=new_envelope,
        )

    def clear_runtime_state(self, *, clear_store: bool = False) -> None:
        """Clear plans, traces, and receipts; optionally clear store/coordinator."""

        with self._lock:
            self._plans.clear()
            self._node_index.clear()
            self._receipts.clear()
            self._trace_events.clear()
            self._trace_seq = 0
            self._active_trace_id = _new_id("trace")
        if clear_store:
            self._coordinator.clear()

    def clear(self) -> None:
        self.clear_runtime_state(clear_store=True)


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def min_trust(
    left: ProofTrustLevel | str, right: ProofTrustLevel | str
) -> ProofTrustLevel:
    """Return the lower of two trust levels."""

    a = left if isinstance(left, ProofTrustLevel) else ProofTrustLevel(str(left))
    b = right if isinstance(right, ProofTrustLevel) else ProofTrustLevel(str(right))
    return a if trust_rank(a) <= trust_rank(b) else b


def max_trust(
    left: ProofTrustLevel | str, right: ProofTrustLevel | str
) -> ProofTrustLevel:
    """Return the higher of two trust levels."""

    a = left if isinstance(left, ProofTrustLevel) else ProofTrustLevel(str(left))
    b = right if isinstance(right, ProofTrustLevel) else ProofTrustLevel(str(right))
    return a if trust_rank(a) >= trust_rank(b) else b


def _max_projected_trust(
    receipts: Sequence[EvidenceReceipt],
) -> ProofTrustLevel:
    best = ProofTrustLevel.NONE
    for receipt in receipts:
        best = max_trust(best, receipt.projected_trust)
    return best


def _max_evidence_authority(
    receipts: Sequence[EvidenceReceipt],
) -> EvidenceAuthority:
    ranking = {
        EvidenceAuthority.NONE: 0,
        EvidenceAuthority.ADVISORY: 1,
        EvidenceAuthority.BOUNDED: 2,
        EvidenceAuthority.INDEPENDENTLY_CHECKABLE: 3,
        EvidenceAuthority.AUTHORITATIVE: 4,
    }
    best = EvidenceAuthority.NONE
    for receipt in receipts:
        if ranking[receipt.evidence_authority] > ranking[best]:
            best = receipt.evidence_authority
    return best


def _evidence_for_trust(trust: ProofTrustLevel) -> EvidenceAuthority:
    mapping = {
        ProofTrustLevel.AUTHORITATIVE: EvidenceAuthority.AUTHORITATIVE,
        ProofTrustLevel.INDEPENDENTLY_CHECKABLE: (
            EvidenceAuthority.INDEPENDENTLY_CHECKABLE
        ),
        ProofTrustLevel.BOUNDED: EvidenceAuthority.BOUNDED,
        ProofTrustLevel.ADVISORY: EvidenceAuthority.ADVISORY,
        ProofTrustLevel.NON_TRUSTED: EvidenceAuthority.NONE,
        ProofTrustLevel.NONE: EvidenceAuthority.NONE,
    }
    return mapping[trust]


def _traces_semantically_match(
    source: SchedulerTrace, replay: SchedulerTrace
) -> bool:
    """Compare authority-bearing event kinds and key digests for replay fidelity.

    Fence tokens, claim ids, and absolute timestamps are intentionally ignored.
    """

    def fingerprint(trace: SchedulerTrace) -> list[tuple[str, str, str]]:
        rows: list[tuple[str, str, str]] = []
        for event in trace.events:
            if event.kind in {
                TraceEventKind.PLAN_REGISTERED,
                TraceEventKind.NODE_SCHEDULED,
                TraceEventKind.DRAFT_PUBLISHED,
                TraceEventKind.ATTESTED_PUBLISHED,
                TraceEventKind.AUTHORITY_UPGRADED,
                TraceEventKind.INVALIDATED,
            }:
                trust = ""
                payload = (
                    dict(event.payload)
                    if hasattr(event.payload, "items")
                    else {}
                )
                if "trust_level" in payload:
                    trust = str(payload["trust_level"])
                elif "to_trust" in payload:
                    trust = str(payload["to_trust"])
                rows.append((event.kind.value, event.key_digest, trust))
        return rows

    return fingerprint(source) == fingerprint(replay)


def build_duckdb_proof_service(
    *,
    coordinator: DuckDBProofCoordinator | None = None,
    store: DuckDBProofStore | None = None,
    corpus: ProofCorpusDuckDBRepository | None = None,
    include_corpus: bool = False,
    **kwargs: Any,
) -> DuckDBProofService:
    """Construct a :class:`DuckDBProofService` with standard defaults."""

    if corpus is None and include_corpus:
        corpus = build_proof_corpus_duckdb_repository()
    if coordinator is None and store is not None:
        coordinator = build_duckdb_proof_coordinator(store=store)
    return DuckDBProofService(
        coordinator=coordinator,
        store=store,
        corpus=corpus,
        **kwargs,
    )


__all__ = [
    "DEFAULT_LOGIC_FAMILY_ADAPTERS",
    "DEFAULT_OWNER_ID",
    "DUCKDB_PROOF_SERVICE_INTERFACE",
    "DUCKDB_PROOF_SERVICE_SCHEMA_VERSION",
    "DuckDBProofService",
    "DuckDBProofServiceAdapterError",
    "DuckDBProofServiceAuthorityError",
    "DuckDBProofServiceError",
    "DuckDBProofServiceIntegrityError",
    "DuckDBProofServicePolicyError",
    "DuckDBProofServiceReplayError",
    "EVIDENCE_RECEIPT_SCHEMA_VERSION",
    "EntryPublicationMode",
    "EvidenceReceipt",
    "FallbackPolicy",
    "LOGIC_FAMILY_ADAPTER_SCHEMA_VERSION",
    "LogicFamilyAdapter",
    "POLICY_GATE_SCHEMA_VERSION",
    "PROOF_PLAN_NODE_SCHEMA_VERSION",
    "PROOF_PLAN_SCHEMA_VERSION",
    "PlanNodeStatus",
    "PolicyGateAction",
    "PolicyGateDecision",
    "PolicyGateVerdict",
    "ProofPlan",
    "ProofPlanNode",
    "SCHEDULER_TRACE_SCHEMA_VERSION",
    "SchedulerTrace",
    "SchedulerTraceEvent",
    "SchedulerTraceReplayResult",
    "ServiceOperationResult",
    "TraceEventKind",
    "build_duckdb_proof_service",
    "max_trust",
    "min_trust",
    "service_content_digest",
]
