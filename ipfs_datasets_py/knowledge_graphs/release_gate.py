"""Production release evidence gate for knowledge graphs (KGP-035 / KGP-G100).

This module answers a single fail-closed question: *"is
``ipfs_datasets_py.knowledge_graphs`` production ready for release?"*

**Normative rules**

1. Exact fresh **passing** receipts are required for child goals
   ``KGP-G010`` through ``KGP-G090`` (inclusive, decade steps).
2. Every root **definition-of-done** clause from the production-hardening
   plan must have a matching fresh passing receipt, including
   **corpus-specific sign-off**.
3. The following are **never** substitutes for receipts and always fail the
   gate when offered as evidence kinds or as sole proof:

   * task status / backlog completion claims
   * coverage percentages
   * prose assertions / narrative claims
   * optional-dependency skips
   * sample-only corpus runs
   * absent soak or chaos profiles
   * missing UCAN negative (deny) proof
   * unknown / unlabelled environment

4. Missing, stale, foreign-tree, skipped, partial, or contradicted evidence
   **fails closed**.
5. The gate always emits a **signed, content-addressed**
   :class:`ReleaseDecision`. Until the decision is ``pass`` with
   ``production_ready=True``, the platform is **not** production ready.

This module has no optional backend imports so it is safe for package-root
and CI load paths.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from types import MappingProxyType
from typing import (
    Any,
    Dict,
    Final,
    FrozenSet,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

# ---------------------------------------------------------------------------
# Schema stamps
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "kg-release-gate/v1"
DECISION_SCHEMA_VERSION: Final = "kg-release-decision/v1"
RECEIPT_SCHEMA_VERSION: Final = "kg-goal-receipt/v1"
BUNDLE_SCHEMA_VERSION: Final = "kg-release-evidence-bundle/v1"
CANONICAL_JSON_PROFILE: Final = "kg-canonical-json-v1"
CONTENT_DOMAIN: Final = "kg.release.gate"
SIGNATURE_DOMAIN: Final = "kg.release.decision"
TASK_ID: Final = "KGP-035"
GOAL_ID: Final = "KGP-G100"
POLICY_ID: Final = "kg-release-evidence/v1"

# Default maximum age for a receipt to count as "fresh" (7 days).
DEFAULT_MAX_RECEIPT_AGE: Final = timedelta(days=7)

# ---------------------------------------------------------------------------
# Required child goals (KGP-G010 … KGP-G090)
# ---------------------------------------------------------------------------

REQUIRED_CHILD_GOALS: Final[Tuple[str, ...]] = tuple(
    f"KGP-G{n:03d}" for n in range(10, 100, 10)
)
# Explicit enumeration for documentation and static analysis.
assert REQUIRED_CHILD_GOALS == (
    "KGP-G010",
    "KGP-G020",
    "KGP-G030",
    "KGP-G040",
    "KGP-G050",
    "KGP-G060",
    "KGP-G070",
    "KGP-G080",
    "KGP-G090",
)

# ---------------------------------------------------------------------------
# Root definition-of-done clauses (plan § Definition of done)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RootDodClause:
    """One root definition-of-done acceptance clause."""

    clause_id: str
    description: str
    requires_corpus_signoff: bool = False
    requires_ucan_negative: bool = False
    requires_soak_chaos: bool = False
    requires_labelled_environment: bool = False


ROOT_DOD_CLAUSES: Final[Tuple[RootDodClause, ...]] = (
    RootDodClause(
        clause_id="concurrent_identity_durability",
        description=(
            "At least 16 graph IDs can be read and written concurrently without "
            "identity confusion, lost updates, or cross-tenant leakage."
        ),
    ),
    RootDodClause(
        clause_id="storage_profiles_contract",
        description=(
            "Parquet, direct IPFS/IPLD, and ipfs_kit_py profiles pass the same "
            "contract suite, including restart and crash recovery."
        ),
    ),
    RootDodClause(
        clause_id="four_surface_parity",
        description=(
            "Python, CLI, MCP, and MCP++ pass the same operation/query/error "
            "vectors."
        ),
    ),
    RootDodClause(
        clause_id="ucan_fail_closed",
        description=(
            "UCAN allow, attenuation, expiry, revocation, replay, and denial "
            "tests pass with fail-closed audit evidence."
        ),
        requires_ucan_negative=True,
    ),
    RootDodClause(
        clause_id="sharded_integrity",
        description=(
            "v1 and v2 sharded graphs pass integrity and cross-shard traversal "
            "tests."
        ),
    ),
    RootDodClause(
        clause_id="corpora_differential",
        description=(
            "CVEfixes, SkillCenter, 211-AI, and code/evidence graph fixtures "
            "pass differential and representative workload tests."
        ),
        requires_corpus_signoff=True,
    ),
    RootDodClause(
        clause_id="load_soak_chaos_ops",
        description=(
            "Load, soak, chaos, backup/restore, observability, and resource "
            "bounds pass on a labelled environment."
        ),
        requires_soak_chaos=True,
        requires_labelled_environment=True,
    ),
    RootDodClause(
        clause_id="migration_reversible",
        description=(
            "Migration runbooks, rollback, compatibility policy, and "
            "deprecation warnings are published, with no legacy codepath moved "
            "before its gate."
        ),
    ),
)

ROOT_DOD_CLAUSE_IDS: Final[Tuple[str, ...]] = tuple(
    c.clause_id for c in ROOT_DOD_CLAUSES
)

REQUIRED_CORPORA: Final[Tuple[str, ...]] = (
    "cvefixes",
    "skillcenter",
    "two_eleven",
    "code_evidence",
)

# ---------------------------------------------------------------------------
# Rejected evidence substitutes
# ---------------------------------------------------------------------------

REJECTED_SUBSTITUTES: Final[FrozenSet[str]] = frozenset(
    {
        "task_status",
        "coverage",
        "prose",
        "optional_dependency_skip",
        "sample_only_corpus",
        "absent_soak",
        "absent_chaos",
        "absent_soak_chaos",
        "missing_ucan_negative_proof",
        "unknown_environment",
        # Common aliases operators may still attempt.
        "status",
        "backlog_status",
        "todo_status",
        "line_coverage",
        "test_coverage",
        "narrative",
        "documentation_only",
        "skip",
        "skipped",
        "xfail",
        "sample",
        "sample_only",
        "fixture_sample",
        "unknown",
        "unlabelled_environment",
        "unlabeled_environment",
    }
)

# Evidence kinds that are accepted when properly structured.
ACCEPTED_EVIDENCE_KINDS: Final[FrozenSet[str]] = frozenset(
    {
        "validation_receipt",
        "integration_receipt",
        "contract_probe",
        "load_receipt",
        "soak_receipt",
        "chaos_receipt",
        "ucan_negative_proof",
        "ucan_audit_receipt",
        "corpus_differential",
        "corpus_signoff",
        "backup_restore_proof",
        "migration_receipt",
        "shadow_metrics",
        "canary_rollback_drill",
        "surface_conformance",
        "storage_contract",
        "concurrency_receipt",
        "sharding_integrity",
    }
)

PASSING_STATUSES: Final[FrozenSet[str]] = frozenset(
    {"pass", "passed", "ok", "success", "accepted"}
)

FAILING_STATUSES: Final[FrozenSet[str]] = frozenset(
    {
        "fail",
        "failed",
        "error",
        "skipped",
        "skip",
        "partial",
        "stale",
        "unknown",
        "pending",
        "blocked",
        "xfail",
    }
)

UNKNOWN_ENVIRONMENT_TOKENS: Final[FrozenSet[str]] = frozenset(
    {
        "",
        "unknown",
        "unlabelled",
        "unlabeled",
        "none",
        "null",
        "n/a",
        "na",
        "local-unknown",
        "ci-unknown",
    }
)

# ---------------------------------------------------------------------------
# Errors / decisions
# ---------------------------------------------------------------------------


class ReleaseGateError(Exception):
    """Base error for the release evidence gate."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "release_gate_error",
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details: Dict[str, Any] = dict(details or {})


class ReleaseGateFailClosed(ReleaseGateError):
    """Raised when evaluation must fail closed (missing/stale/foreign/etc.)."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "fail_closed",
        details: Optional[Mapping[str, Any]] = None,
        decision: Optional["ReleaseDecision"] = None,
    ) -> None:
        super().__init__(message, code=code, details=details)
        self.decision = decision


class DecisionOutcome(str, Enum):
    """Outcome of a release evaluation."""

    PASS = "pass"
    FAIL = "fail"
    NOT_PRODUCTION_READY = "not_production_ready"


class BlockerCode(str, Enum):
    """Machine-readable blocker codes."""

    MISSING_GOAL_RECEIPT = "missing_goal_receipt"
    INVALID_GOAL_RECEIPT = "invalid_goal_receipt"
    STALE_RECEIPT = "stale_receipt"
    FOREIGN_TREE = "foreign_tree"
    SKIPPED_RECEIPT = "skipped_receipt"
    PARTIAL_EVIDENCE = "partial_evidence"
    CONTRADICTED_EVIDENCE = "contradicted_evidence"
    REJECTED_SUBSTITUTE = "rejected_substitute"
    MISSING_DOD_CLAUSE = "missing_dod_clause"
    INVALID_DOD_CLAUSE = "invalid_dod_clause"
    MISSING_CORPUS_SIGNOFF = "missing_corpus_signoff"
    SAMPLE_ONLY_CORPUS = "sample_only_corpus"
    MISSING_UCAN_NEGATIVE = "missing_ucan_negative_proof"
    ABSENT_SOAK = "absent_soak"
    ABSENT_CHAOS = "absent_chaos"
    UNKNOWN_ENVIRONMENT = "unknown_environment"
    MISSING_ENVIRONMENT = "missing_environment"
    SCHEMA_MISMATCH = "schema_mismatch"
    MISSING_BUNDLE = "missing_bundle"
    SIGNATURE_INVALID = "signature_invalid"
    NOT_PASSING = "not_passing"


# ---------------------------------------------------------------------------
# Canonical serialization / content addressing
# ---------------------------------------------------------------------------


def _is_json_primitive(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def canonicalize(value: Any) -> Any:
    """Return a JSON-safe, deterministically ordered structure."""

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return str(value)
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(k): canonicalize(v)
            for k, v in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [canonicalize(item) for item in value]
    if isinstance(value, set):
        items = [canonicalize(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, datetime):
        return _format_ts(value)
    return str(value)


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize *value* as canonical UTF-8 JSON."""

    return json.dumps(
        canonicalize(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def content_address(value: Any, *, domain: str = CONTENT_DOMAIN) -> str:
    """SHA-256 hex digest of the domain-bound canonical JSON of *value*."""

    digest = hashlib.sha256(
        f"{domain}|".encode("utf-8") + canonical_json_bytes(value)
    ).hexdigest()
    return f"sha256:{digest}"


def content_cid(value: Any, *, domain: str = CONTENT_DOMAIN) -> str:
    """Content-addressed id suitable for release decisions and receipts.

    Uses a stable ``kg-rel1-`` prefix plus the first 48 hex chars of the
    domain-bound SHA-256 so the id is short, unique, and deterministic.
    """

    digest = content_address(value, domain=domain).removeprefix("sha256:")
    return f"kg-rel1-{digest[:48]}"


def _format_ts(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc).replace(microsecond=0)
    return value.isoformat().replace("+00:00", "Z")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def parse_timestamp(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp into an aware UTC datetime."""

    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_status(status: Any) -> str:
    if status is None:
        return ""
    return str(status).strip().lower()


def _normalize_kind(kind: Any) -> str:
    if kind is None:
        return ""
    return str(kind).strip().lower().replace("-", "_").replace(" ", "_")


def _normalize_env(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def is_rejected_substitute(kind: Any) -> bool:
    """Return True if *kind* is a forbidden evidence substitute."""

    return _normalize_kind(kind) in REJECTED_SUBSTITUTES


def is_unknown_environment(environment_id: Any) -> bool:
    """Return True if *environment_id* is missing or explicitly unknown."""

    return _normalize_env(environment_id) in UNKNOWN_ENVIRONMENT_TOKENS


def is_passing_status(status: Any) -> bool:
    return _normalize_status(status) in PASSING_STATUSES


# ---------------------------------------------------------------------------
# Evidence structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GoalReceipt:
    """Fresh passing validation receipt for one child goal."""

    goal_id: str
    tree_id: str
    status: str
    collected_at: str
    evidence_kind: str
    validation_command: str = ""
    receipt_digest: str = ""
    notes: str = ""
    schema_version: str = RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.receipt_digest:
            object.__setattr__(self, "receipt_digest", self.compute_digest())

    def compute_digest(self) -> str:
        payload = {
            "collected_at": self.collected_at,
            "evidence_kind": self.evidence_kind,
            "goal_id": self.goal_id,
            "notes": self.notes,
            "schema_version": self.schema_version,
            "status": self.status,
            "tree_id": self.tree_id,
            "validation_command": self.validation_command,
        }
        return content_address(payload, domain="kg.release.goal_receipt")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "collected_at": self.collected_at,
            "evidence_kind": self.evidence_kind,
            "goal_id": self.goal_id,
            "notes": self.notes,
            "receipt_digest": self.receipt_digest,
            "schema_version": self.schema_version,
            "status": self.status,
            "tree_id": self.tree_id,
            "validation_command": self.validation_command,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "GoalReceipt":
        return cls(
            goal_id=str(data.get("goal_id") or ""),
            tree_id=str(data.get("tree_id") or ""),
            status=str(data.get("status") or ""),
            collected_at=str(data.get("collected_at") or ""),
            evidence_kind=str(data.get("evidence_kind") or ""),
            validation_command=str(data.get("validation_command") or ""),
            receipt_digest=str(data.get("receipt_digest") or ""),
            notes=str(data.get("notes") or ""),
            schema_version=str(
                data.get("schema_version") or RECEIPT_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class DodClauseReceipt:
    """Fresh passing receipt for one root definition-of-done clause."""

    clause_id: str
    tree_id: str
    status: str
    collected_at: str
    evidence_kind: str
    validation_command: str = ""
    receipt_digest: str = ""
    notes: str = ""
    schema_version: str = RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.receipt_digest:
            object.__setattr__(self, "receipt_digest", self.compute_digest())

    def compute_digest(self) -> str:
        payload = {
            "clause_id": self.clause_id,
            "collected_at": self.collected_at,
            "evidence_kind": self.evidence_kind,
            "notes": self.notes,
            "schema_version": self.schema_version,
            "status": self.status,
            "tree_id": self.tree_id,
            "validation_command": self.validation_command,
        }
        return content_address(payload, domain="kg.release.dod_receipt")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "clause_id": self.clause_id,
            "collected_at": self.collected_at,
            "evidence_kind": self.evidence_kind,
            "notes": self.notes,
            "receipt_digest": self.receipt_digest,
            "schema_version": self.schema_version,
            "status": self.status,
            "tree_id": self.tree_id,
            "validation_command": self.validation_command,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "DodClauseReceipt":
        return cls(
            clause_id=str(data.get("clause_id") or ""),
            tree_id=str(data.get("tree_id") or ""),
            status=str(data.get("status") or ""),
            collected_at=str(data.get("collected_at") or ""),
            evidence_kind=str(data.get("evidence_kind") or ""),
            validation_command=str(data.get("validation_command") or ""),
            receipt_digest=str(data.get("receipt_digest") or ""),
            notes=str(data.get("notes") or ""),
            schema_version=str(
                data.get("schema_version") or RECEIPT_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class CorpusSignOff:
    """Producer / owner corpus-specific release sign-off."""

    corpus_id: str
    producer_id: str
    signer: str
    signed_at: str
    tree_id: str
    mode: str  # must be "full" (not sample)
    receipt_digest: str = ""
    statement: str = ""
    schema_version: str = "kg-corpus-signoff/v1"

    def __post_init__(self) -> None:
        if not self.receipt_digest:
            object.__setattr__(self, "receipt_digest", self.compute_digest())

    def compute_digest(self) -> str:
        payload = {
            "corpus_id": self.corpus_id,
            "mode": self.mode,
            "producer_id": self.producer_id,
            "schema_version": self.schema_version,
            "signed_at": self.signed_at,
            "signer": self.signer,
            "statement": self.statement,
            "tree_id": self.tree_id,
        }
        return content_address(payload, domain="kg.release.corpus_signoff")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "corpus_id": self.corpus_id,
            "mode": self.mode,
            "producer_id": self.producer_id,
            "receipt_digest": self.receipt_digest,
            "schema_version": self.schema_version,
            "signed_at": self.signed_at,
            "signer": self.signer,
            "statement": self.statement,
            "tree_id": self.tree_id,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CorpusSignOff":
        return cls(
            corpus_id=str(data.get("corpus_id") or ""),
            producer_id=str(data.get("producer_id") or ""),
            signer=str(data.get("signer") or ""),
            signed_at=str(data.get("signed_at") or ""),
            tree_id=str(data.get("tree_id") or ""),
            mode=str(data.get("mode") or ""),
            receipt_digest=str(data.get("receipt_digest") or ""),
            statement=str(data.get("statement") or ""),
            schema_version=str(
                data.get("schema_version") or "kg-corpus-signoff/v1"
            ),
        )


@dataclass(frozen=True, slots=True)
class UCANNegativeProof:
    """UCAN deny / negative authorization proof bound to a tree."""

    tree_id: str
    deny_receipt_cids: Tuple[str, ...]
    collected_at: str
    evidence_kind: str = "ucan_negative_proof"
    receipt_digest: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "deny_receipt_cids",
            tuple(str(c) for c in self.deny_receipt_cids if str(c).strip()),
        )
        if not self.receipt_digest:
            object.__setattr__(self, "receipt_digest", self.compute_digest())

    def compute_digest(self) -> str:
        payload = {
            "collected_at": self.collected_at,
            "deny_receipt_cids": list(self.deny_receipt_cids),
            "evidence_kind": self.evidence_kind,
            "notes": self.notes,
            "tree_id": self.tree_id,
        }
        return content_address(payload, domain="kg.release.ucan_negative")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "collected_at": self.collected_at,
            "deny_receipt_cids": list(self.deny_receipt_cids),
            "evidence_kind": self.evidence_kind,
            "notes": self.notes,
            "receipt_digest": self.receipt_digest,
            "tree_id": self.tree_id,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "UCANNegativeProof":
        cids = data.get("deny_receipt_cids") or data.get("receipt_cids") or []
        if isinstance(cids, str):
            cids = [cids]
        return cls(
            tree_id=str(data.get("tree_id") or ""),
            deny_receipt_cids=tuple(str(c) for c in cids),
            collected_at=str(data.get("collected_at") or ""),
            evidence_kind=str(
                data.get("evidence_kind") or "ucan_negative_proof"
            ),
            receipt_digest=str(data.get("receipt_digest") or ""),
            notes=str(data.get("notes") or ""),
        )


@dataclass(frozen=True, slots=True)
class SoakChaosEvidence:
    """Load soak + chaos profile receipts on a labelled environment."""

    tree_id: str
    environment_id: str
    soak_receipt_digest: str
    chaos_receipt_digest: str
    collected_at: str
    load_receipt_digest: str = ""
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chaos_receipt_digest": self.chaos_receipt_digest,
            "collected_at": self.collected_at,
            "environment_id": self.environment_id,
            "load_receipt_digest": self.load_receipt_digest,
            "notes": self.notes,
            "soak_receipt_digest": self.soak_receipt_digest,
            "tree_id": self.tree_id,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "SoakChaosEvidence":
        return cls(
            tree_id=str(data.get("tree_id") or ""),
            environment_id=str(data.get("environment_id") or ""),
            soak_receipt_digest=str(data.get("soak_receipt_digest") or ""),
            chaos_receipt_digest=str(data.get("chaos_receipt_digest") or ""),
            collected_at=str(data.get("collected_at") or ""),
            load_receipt_digest=str(data.get("load_receipt_digest") or ""),
            notes=str(data.get("notes") or ""),
        )


@dataclass(frozen=True, slots=True)
class EnvironmentBinding:
    """Labelled environment the release evidence was collected against."""

    environment_id: str
    label: str
    tree_id: str
    collected_at: str = ""
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "collected_at": self.collected_at,
            "environment_id": self.environment_id,
            "label": self.label,
            "notes": self.notes,
            "tree_id": self.tree_id,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "EnvironmentBinding":
        return cls(
            environment_id=str(data.get("environment_id") or ""),
            label=str(data.get("label") or data.get("environment_id") or ""),
            tree_id=str(data.get("tree_id") or ""),
            collected_at=str(data.get("collected_at") or ""),
            notes=str(data.get("notes") or ""),
        )


@dataclass
class ReleaseEvidenceBundle:
    """Operator-supplied evidence package for a single tree evaluation."""

    tree_id: str
    goal_receipts: List[GoalReceipt] = field(default_factory=list)
    dod_receipts: List[DodClauseReceipt] = field(default_factory=list)
    corpus_signoffs: List[CorpusSignOff] = field(default_factory=list)
    ucan_negative: Optional[UCANNegativeProof] = None
    soak_chaos: Optional[SoakChaosEvidence] = None
    environment: Optional[EnvironmentBinding] = None
    schema_version: str = BUNDLE_SCHEMA_VERSION
    package_version: str = ""
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "corpus_signoffs": [s.to_dict() for s in self.corpus_signoffs],
            "dod_receipts": [r.to_dict() for r in self.dod_receipts],
            "environment": (
                self.environment.to_dict() if self.environment else None
            ),
            "goal_receipts": [r.to_dict() for r in self.goal_receipts],
            "notes": self.notes,
            "package_version": self.package_version,
            "schema_version": self.schema_version,
            "soak_chaos": self.soak_chaos.to_dict() if self.soak_chaos else None,
            "tree_id": self.tree_id,
            "ucan_negative": (
                self.ucan_negative.to_dict() if self.ucan_negative else None
            ),
        }

    def content_digest(self) -> str:
        return content_address(self.to_dict(), domain="kg.release.bundle")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ReleaseEvidenceBundle":
        goals = [
            GoalReceipt.from_mapping(item)
            for item in (data.get("goal_receipts") or [])
            if isinstance(item, Mapping)
        ]
        dods = [
            DodClauseReceipt.from_mapping(item)
            for item in (data.get("dod_receipts") or [])
            if isinstance(item, Mapping)
        ]
        signoffs = [
            CorpusSignOff.from_mapping(item)
            for item in (data.get("corpus_signoffs") or [])
            if isinstance(item, Mapping)
        ]
        ucan_raw = data.get("ucan_negative")
        soak_raw = data.get("soak_chaos")
        env_raw = data.get("environment")
        return cls(
            tree_id=str(data.get("tree_id") or ""),
            goal_receipts=goals,
            dod_receipts=dods,
            corpus_signoffs=signoffs,
            ucan_negative=(
                UCANNegativeProof.from_mapping(ucan_raw)
                if isinstance(ucan_raw, Mapping)
                else None
            ),
            soak_chaos=(
                SoakChaosEvidence.from_mapping(soak_raw)
                if isinstance(soak_raw, Mapping)
                else None
            ),
            environment=(
                EnvironmentBinding.from_mapping(env_raw)
                if isinstance(env_raw, Mapping)
                else None
            ),
            schema_version=str(
                data.get("schema_version") or BUNDLE_SCHEMA_VERSION
            ),
            package_version=str(data.get("package_version") or ""),
            notes=str(data.get("notes") or ""),
        )


# ---------------------------------------------------------------------------
# Blockers and decisions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReleaseBlocker:
    """One fail-closed reason that prevents production readiness."""

    code: str
    message: str
    subject: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "details": dict(self.details),
            "message": self.message,
            "subject": self.subject,
        }


@dataclass(frozen=True, slots=True)
class ReleaseDecision:
    """Signed, content-addressed release evaluation result.

    ``production_ready`` is True **only** when ``outcome`` is
    :attr:`DecisionOutcome.PASS` and there are zero blockers. Until then the
    platform remains not production ready.
    """

    outcome: str
    production_ready: bool
    tree_id: str
    evaluated_at: str
    blockers: Tuple[ReleaseBlocker, ...]
    required_child_goals: Tuple[str, ...]
    required_dod_clauses: Tuple[str, ...]
    satisfied_child_goals: Tuple[str, ...]
    satisfied_dod_clauses: Tuple[str, ...]
    bundle_digest: str
    decision_cid: str = ""
    signature: str = ""
    schema_version: str = DECISION_SCHEMA_VERSION
    policy_id: str = POLICY_ID
    task_id: str = TASK_ID
    goal_id: str = GOAL_ID
    package_version: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.decision_cid:
            object.__setattr__(self, "decision_cid", self.compute_cid())

    def _body_for_addressing(self) -> Dict[str, Any]:
        return {
            "blockers": [b.to_dict() for b in self.blockers],
            "bundle_digest": self.bundle_digest,
            "evaluated_at": self.evaluated_at,
            "goal_id": self.goal_id,
            "notes": self.notes,
            "outcome": self.outcome,
            "package_version": self.package_version,
            "policy_id": self.policy_id,
            "production_ready": self.production_ready,
            "required_child_goals": list(self.required_child_goals),
            "required_dod_clauses": list(self.required_dod_clauses),
            "satisfied_child_goals": list(self.satisfied_child_goals),
            "satisfied_dod_clauses": list(self.satisfied_dod_clauses),
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "tree_id": self.tree_id,
        }

    def compute_cid(self) -> str:
        return content_cid(self._body_for_addressing(), domain=SIGNATURE_DOMAIN)

    def signing_payload(self) -> bytes:
        body = self._body_for_addressing()
        body["decision_cid"] = self.decision_cid or self.compute_cid()
        return canonical_json_bytes(body)

    def to_dict(self) -> Dict[str, Any]:
        body = self._body_for_addressing()
        body["decision_cid"] = self.decision_cid
        body["signature"] = self.signature
        return body

    def is_pass(self) -> bool:
        return (
            self.outcome == DecisionOutcome.PASS.value
            and self.production_ready
            and not self.blockers
        )


def sign_decision(
    decision: ReleaseDecision,
    *,
    signing_key: bytes | str,
) -> ReleaseDecision:
    """Return a copy of *decision* with an HMAC-SHA256 signature.

    The signature binds ``decision_cid`` and the full decision body. Empty
    keys are rejected so unsigned decisions cannot be mistaken for signed
    ones.
    """

    if isinstance(signing_key, str):
        key_bytes = signing_key.encode("utf-8")
    else:
        key_bytes = signing_key
    if not key_bytes:
        raise ReleaseGateError(
            "signing_key must be non-empty",
            code="empty_signing_key",
        )
    cid = decision.decision_cid or decision.compute_cid()
    # Rebuild with cid fixed so signing_payload is stable.
    fixed = ReleaseDecision(
        outcome=decision.outcome,
        production_ready=decision.production_ready,
        tree_id=decision.tree_id,
        evaluated_at=decision.evaluated_at,
        blockers=decision.blockers,
        required_child_goals=decision.required_child_goals,
        required_dod_clauses=decision.required_dod_clauses,
        satisfied_child_goals=decision.satisfied_child_goals,
        satisfied_dod_clauses=decision.satisfied_dod_clauses,
        bundle_digest=decision.bundle_digest,
        decision_cid=cid,
        signature="",
        schema_version=decision.schema_version,
        policy_id=decision.policy_id,
        task_id=decision.task_id,
        goal_id=decision.goal_id,
        package_version=decision.package_version,
        notes=decision.notes,
    )
    mac = hmac.new(
        key_bytes,
        fixed.signing_payload(),
        hashlib.sha256,
    ).hexdigest()
    signature = f"hmac-sha256:{mac}"
    return ReleaseDecision(
        outcome=fixed.outcome,
        production_ready=fixed.production_ready,
        tree_id=fixed.tree_id,
        evaluated_at=fixed.evaluated_at,
        blockers=fixed.blockers,
        required_child_goals=fixed.required_child_goals,
        required_dod_clauses=fixed.required_dod_clauses,
        satisfied_child_goals=fixed.satisfied_child_goals,
        satisfied_dod_clauses=fixed.satisfied_dod_clauses,
        bundle_digest=fixed.bundle_digest,
        decision_cid=fixed.decision_cid,
        signature=signature,
        schema_version=fixed.schema_version,
        policy_id=fixed.policy_id,
        task_id=fixed.task_id,
        goal_id=fixed.goal_id,
        package_version=fixed.package_version,
        notes=fixed.notes,
    )


def verify_decision_signature(
    decision: ReleaseDecision,
    *,
    signing_key: bytes | str,
) -> bool:
    """Verify an HMAC-SHA256 signature on *decision*."""

    if not decision.signature:
        return False
    if isinstance(signing_key, str):
        key_bytes = signing_key.encode("utf-8")
    else:
        key_bytes = signing_key
    if not key_bytes:
        return False
    expected = sign_decision(
        ReleaseDecision(
            outcome=decision.outcome,
            production_ready=decision.production_ready,
            tree_id=decision.tree_id,
            evaluated_at=decision.evaluated_at,
            blockers=decision.blockers,
            required_child_goals=decision.required_child_goals,
            required_dod_clauses=decision.required_dod_clauses,
            satisfied_child_goals=decision.satisfied_child_goals,
            satisfied_dod_clauses=decision.satisfied_dod_clauses,
            bundle_digest=decision.bundle_digest,
            decision_cid=decision.decision_cid,
            signature="",
            schema_version=decision.schema_version,
            policy_id=decision.policy_id,
            task_id=decision.task_id,
            goal_id=decision.goal_id,
            package_version=decision.package_version,
            notes=decision.notes,
        ),
        signing_key=key_bytes,
    )
    return hmac.compare_digest(decision.signature, expected.signature)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def _blocker(
    code: BlockerCode | str,
    message: str,
    *,
    subject: str = "",
    **details: Any,
) -> ReleaseBlocker:
    code_value = code.value if isinstance(code, BlockerCode) else str(code)
    return ReleaseBlocker(
        code=code_value,
        message=message,
        subject=subject,
        details=MappingProxyType(dict(details)),
    )


def _check_freshness(
    collected_at: str,
    *,
    now: datetime,
    max_age: timedelta,
    subject: str,
) -> Optional[ReleaseBlocker]:
    ts = parse_timestamp(collected_at)
    if ts is None:
        return _blocker(
            BlockerCode.INVALID_GOAL_RECEIPT,
            f"unparseable collected_at for {subject}",
            subject=subject,
            collected_at=collected_at,
        )
    age = now - ts
    if age > max_age:
        return _blocker(
            BlockerCode.STALE_RECEIPT,
            f"stale evidence for {subject}: age {age} exceeds max {max_age}",
            subject=subject,
            collected_at=collected_at,
            age_seconds=age.total_seconds(),
            max_age_seconds=max_age.total_seconds(),
        )
    if ts > now + timedelta(minutes=5):
        return _blocker(
            BlockerCode.INVALID_GOAL_RECEIPT,
            f"evidence timestamp is in the future for {subject}",
            subject=subject,
            collected_at=collected_at,
        )
    return None


def _check_tree(
    evidence_tree: str,
    expected_tree: str,
    *,
    subject: str,
) -> Optional[ReleaseBlocker]:
    if not expected_tree:
        return _blocker(
            BlockerCode.FOREIGN_TREE,
            "evaluation requires an explicit expected tree_id",
            subject=subject,
        )
    if not evidence_tree or evidence_tree != expected_tree:
        return _blocker(
            BlockerCode.FOREIGN_TREE,
            f"foreign-tree evidence for {subject}",
            subject=subject,
            evidence_tree_id=evidence_tree,
            expected_tree_id=expected_tree,
        )
    return None


def _check_evidence_kind(
    kind: str,
    *,
    subject: str,
) -> Optional[ReleaseBlocker]:
    if is_rejected_substitute(kind):
        return _blocker(
            BlockerCode.REJECTED_SUBSTITUTE,
            f"rejected evidence substitute {kind!r} for {subject}",
            subject=subject,
            evidence_kind=kind,
        )
    if not kind or _normalize_kind(kind) not in ACCEPTED_EVIDENCE_KINDS:
        # Unknown kinds are fail-closed unless they are accepted.
        return _blocker(
            BlockerCode.REJECTED_SUBSTITUTE
            if is_rejected_substitute(kind)
            else BlockerCode.INVALID_GOAL_RECEIPT,
            f"unaccepted evidence kind {kind!r} for {subject}",
            subject=subject,
            evidence_kind=kind,
        )
    return None


def evaluate_goal_receipts(
    receipts: Sequence[GoalReceipt],
    *,
    expected_tree_id: str,
    now: datetime,
    max_age: timedelta,
) -> Tuple[List[str], List[ReleaseBlocker]]:
    """Validate child-goal receipts; return (satisfied_ids, blockers)."""

    blockers: List[ReleaseBlocker] = []
    by_goal: Dict[str, List[GoalReceipt]] = {}
    for receipt in receipts:
        by_goal.setdefault(receipt.goal_id, []).append(receipt)

    satisfied: List[str] = []
    for goal_id in REQUIRED_CHILD_GOALS:
        items = by_goal.get(goal_id) or []
        if not items:
            blockers.append(
                _blocker(
                    BlockerCode.MISSING_GOAL_RECEIPT,
                    f"missing exact fresh passing receipt for {goal_id}",
                    subject=goal_id,
                )
            )
            continue

        # Prefer the newest collectable passing receipt for this goal.
        goal_blockers: List[ReleaseBlocker] = []
        accepted: Optional[GoalReceipt] = None
        for receipt in items:
            subject = f"{goal_id}"
            if not receipt.goal_id:
                goal_blockers.append(
                    _blocker(
                        BlockerCode.INVALID_GOAL_RECEIPT,
                        "goal receipt missing goal_id",
                        subject=subject,
                    )
                )
                continue

            tree_block = _check_tree(
                receipt.tree_id, expected_tree_id, subject=subject
            )
            if tree_block:
                goal_blockers.append(tree_block)
                continue

            kind_block = _check_evidence_kind(
                receipt.evidence_kind, subject=subject
            )
            if kind_block:
                goal_blockers.append(kind_block)
                continue

            status = _normalize_status(receipt.status)
            if status in {"skip", "skipped", "xfail"}:
                goal_blockers.append(
                    _blocker(
                        BlockerCode.SKIPPED_RECEIPT,
                        f"skipped receipt is not acceptable for {goal_id}",
                        subject=subject,
                        status=receipt.status,
                    )
                )
                continue

            if not is_passing_status(status):
                goal_blockers.append(
                    _blocker(
                        BlockerCode.NOT_PASSING,
                        f"non-passing status {receipt.status!r} for {goal_id}",
                        subject=subject,
                        status=receipt.status,
                    )
                )
                continue

            # Digests must match content (tamper detection).
            expected_digest = receipt.compute_digest()
            if receipt.receipt_digest and receipt.receipt_digest != expected_digest:
                goal_blockers.append(
                    _blocker(
                        BlockerCode.CONTRADICTED_EVIDENCE,
                        f"receipt digest mismatch for {goal_id}",
                        subject=subject,
                        expected=expected_digest,
                        actual=receipt.receipt_digest,
                    )
                )
                continue

            fresh_block = _check_freshness(
                receipt.collected_at,
                now=now,
                max_age=max_age,
                subject=subject,
            )
            if fresh_block:
                # Stale uses STALE_RECEIPT; remap invalid timestamps.
                if fresh_block.code == BlockerCode.INVALID_GOAL_RECEIPT.value:
                    goal_blockers.append(fresh_block)
                else:
                    goal_blockers.append(fresh_block)
                continue

            accepted = receipt
            break

        if accepted is not None:
            satisfied.append(goal_id)
        else:
            if goal_blockers:
                blockers.extend(goal_blockers)
            else:
                blockers.append(
                    _blocker(
                        BlockerCode.INVALID_GOAL_RECEIPT,
                        f"no valid passing receipt for {goal_id}",
                        subject=goal_id,
                    )
                )

    # Extra unknown goals do not satisfy missing required ones; ignore.
    return satisfied, blockers


def evaluate_dod_receipts(
    receipts: Sequence[DodClauseReceipt],
    *,
    expected_tree_id: str,
    now: datetime,
    max_age: timedelta,
) -> Tuple[List[str], List[ReleaseBlocker]]:
    """Validate root DoD clause receipts; return (satisfied_ids, blockers)."""

    blockers: List[ReleaseBlocker] = []
    by_clause: Dict[str, List[DodClauseReceipt]] = {}
    for receipt in receipts:
        by_clause.setdefault(receipt.clause_id, []).append(receipt)

    satisfied: List[str] = []
    for clause in ROOT_DOD_CLAUSES:
        clause_id = clause.clause_id
        items = by_clause.get(clause_id) or []
        if not items:
            blockers.append(
                _blocker(
                    BlockerCode.MISSING_DOD_CLAUSE,
                    f"missing root definition-of-done receipt for {clause_id}",
                    subject=clause_id,
                    description=clause.description,
                )
            )
            continue

        clause_blockers: List[ReleaseBlocker] = []
        accepted: Optional[DodClauseReceipt] = None
        for receipt in items:
            subject = clause_id
            tree_block = _check_tree(
                receipt.tree_id, expected_tree_id, subject=subject
            )
            if tree_block:
                clause_blockers.append(tree_block)
                continue

            kind_block = _check_evidence_kind(
                receipt.evidence_kind, subject=subject
            )
            if kind_block:
                clause_blockers.append(kind_block)
                continue

            status = _normalize_status(receipt.status)
            if status in {"skip", "skipped", "xfail"}:
                clause_blockers.append(
                    _blocker(
                        BlockerCode.SKIPPED_RECEIPT,
                        f"skipped DoD receipt for {clause_id}",
                        subject=subject,
                        status=receipt.status,
                    )
                )
                continue

            if not is_passing_status(status):
                clause_blockers.append(
                    _blocker(
                        BlockerCode.NOT_PASSING,
                        f"non-passing DoD status {receipt.status!r} for {clause_id}",
                        subject=subject,
                        status=receipt.status,
                    )
                )
                continue

            expected_digest = receipt.compute_digest()
            if receipt.receipt_digest and receipt.receipt_digest != expected_digest:
                clause_blockers.append(
                    _blocker(
                        BlockerCode.CONTRADICTED_EVIDENCE,
                        f"DoD receipt digest mismatch for {clause_id}",
                        subject=subject,
                        expected=expected_digest,
                        actual=receipt.receipt_digest,
                    )
                )
                continue

            fresh_block = _check_freshness(
                receipt.collected_at,
                now=now,
                max_age=max_age,
                subject=subject,
            )
            if fresh_block:
                # Remap generic invalid to DoD code when appropriate.
                if fresh_block.code == BlockerCode.INVALID_GOAL_RECEIPT.value:
                    clause_blockers.append(
                        _blocker(
                            BlockerCode.INVALID_DOD_CLAUSE,
                            fresh_block.message,
                            subject=subject,
                            **dict(fresh_block.details),
                        )
                    )
                else:
                    clause_blockers.append(fresh_block)
                continue

            accepted = receipt
            break

        if accepted is not None:
            satisfied.append(clause_id)
        else:
            if clause_blockers:
                blockers.extend(clause_blockers)
            else:
                blockers.append(
                    _blocker(
                        BlockerCode.INVALID_DOD_CLAUSE,
                        f"no valid passing DoD receipt for {clause_id}",
                        subject=clause_id,
                    )
                )

    return satisfied, blockers


def evaluate_corpus_signoffs(
    signoffs: Sequence[CorpusSignOff],
    *,
    expected_tree_id: str,
    now: datetime,
    max_age: timedelta,
) -> List[ReleaseBlocker]:
    """Require full-mode sign-off for every required corpus."""

    blockers: List[ReleaseBlocker] = []
    by_corpus: Dict[str, List[CorpusSignOff]] = {}
    for item in signoffs:
        by_corpus.setdefault(item.corpus_id, []).append(item)

    for corpus_id in REQUIRED_CORPORA:
        items = by_corpus.get(corpus_id) or []
        if not items:
            blockers.append(
                _blocker(
                    BlockerCode.MISSING_CORPUS_SIGNOFF,
                    f"missing corpus-specific sign-off for {corpus_id}",
                    subject=corpus_id,
                )
            )
            continue

        accepted = False
        local_blockers: List[ReleaseBlocker] = []
        for item in items:
            subject = f"corpus:{corpus_id}"
            mode = _normalize_kind(item.mode)
            if mode in {"sample", "sample_only", "fixture_sample"}:
                local_blockers.append(
                    _blocker(
                        BlockerCode.SAMPLE_ONLY_CORPUS,
                        f"sample-only corpus run rejected for {corpus_id}",
                        subject=subject,
                        mode=item.mode,
                    )
                )
                continue
            if mode != "full":
                local_blockers.append(
                    _blocker(
                        BlockerCode.SAMPLE_ONLY_CORPUS
                        if "sample" in mode
                        else BlockerCode.MISSING_CORPUS_SIGNOFF,
                        f"corpus sign-off mode must be 'full' for {corpus_id}",
                        subject=subject,
                        mode=item.mode,
                    )
                )
                continue

            if not item.signer or not item.producer_id:
                local_blockers.append(
                    _blocker(
                        BlockerCode.MISSING_CORPUS_SIGNOFF,
                        f"corpus sign-off requires signer and producer_id for {corpus_id}",
                        subject=subject,
                    )
                )
                continue

            tree_block = _check_tree(
                item.tree_id, expected_tree_id, subject=subject
            )
            if tree_block:
                local_blockers.append(tree_block)
                continue

            fresh_block = _check_freshness(
                item.signed_at,
                now=now,
                max_age=max_age,
                subject=subject,
            )
            if fresh_block:
                local_blockers.append(fresh_block)
                continue

            expected_digest = item.compute_digest()
            if item.receipt_digest and item.receipt_digest != expected_digest:
                local_blockers.append(
                    _blocker(
                        BlockerCode.CONTRADICTED_EVIDENCE,
                        f"corpus sign-off digest mismatch for {corpus_id}",
                        subject=subject,
                    )
                )
                continue

            accepted = True
            break

        if not accepted:
            blockers.extend(local_blockers)
            if not local_blockers:
                blockers.append(
                    _blocker(
                        BlockerCode.MISSING_CORPUS_SIGNOFF,
                        f"no valid full-mode sign-off for {corpus_id}",
                        subject=corpus_id,
                    )
                )

    return blockers


def evaluate_ucan_negative(
    proof: Optional[UCANNegativeProof],
    *,
    expected_tree_id: str,
    now: datetime,
    max_age: timedelta,
) -> List[ReleaseBlocker]:
    """Require at least one deny receipt CID bound to the current tree."""

    if proof is None:
        return [
            _blocker(
                BlockerCode.MISSING_UCAN_NEGATIVE,
                "missing UCAN negative proof (deny audit receipts required)",
                subject="ucan_negative",
            )
        ]

    blockers: List[ReleaseBlocker] = []
    subject = "ucan_negative"

    if is_rejected_substitute(proof.evidence_kind):
        blockers.append(
            _blocker(
                BlockerCode.REJECTED_SUBSTITUTE,
                f"rejected UCAN evidence kind {proof.evidence_kind!r}",
                subject=subject,
                evidence_kind=proof.evidence_kind,
            )
        )

    tree_block = _check_tree(proof.tree_id, expected_tree_id, subject=subject)
    if tree_block:
        blockers.append(tree_block)

    fresh_block = _check_freshness(
        proof.collected_at, now=now, max_age=max_age, subject=subject
    )
    if fresh_block:
        blockers.append(fresh_block)

    if not proof.deny_receipt_cids:
        blockers.append(
            _blocker(
                BlockerCode.MISSING_UCAN_NEGATIVE,
                "UCAN negative proof has no deny_receipt_cids",
                subject=subject,
            )
        )

    expected_digest = proof.compute_digest()
    if proof.receipt_digest and proof.receipt_digest != expected_digest:
        blockers.append(
            _blocker(
                BlockerCode.CONTRADICTED_EVIDENCE,
                "UCAN negative proof digest mismatch",
                subject=subject,
            )
        )

    return blockers


def evaluate_soak_chaos(
    evidence: Optional[SoakChaosEvidence],
    *,
    expected_tree_id: str,
    now: datetime,
    max_age: timedelta,
) -> List[ReleaseBlocker]:
    """Require both soak and chaos receipts on a labelled environment."""

    if evidence is None:
        return [
            _blocker(
                BlockerCode.ABSENT_SOAK,
                "absent soak evidence",
                subject="soak_chaos",
            ),
            _blocker(
                BlockerCode.ABSENT_CHAOS,
                "absent chaos evidence",
                subject="soak_chaos",
            ),
        ]

    blockers: List[ReleaseBlocker] = []
    subject = "soak_chaos"

    tree_block = _check_tree(
        evidence.tree_id, expected_tree_id, subject=subject
    )
    if tree_block:
        blockers.append(tree_block)

    if is_unknown_environment(evidence.environment_id):
        blockers.append(
            _blocker(
                BlockerCode.UNKNOWN_ENVIRONMENT,
                "soak/chaos evidence bound to unknown environment",
                subject=subject,
                environment_id=evidence.environment_id,
            )
        )

    if not str(evidence.soak_receipt_digest or "").strip():
        blockers.append(
            _blocker(
                BlockerCode.ABSENT_SOAK,
                "absent soak receipt digest",
                subject=subject,
            )
        )

    if not str(evidence.chaos_receipt_digest or "").strip():
        blockers.append(
            _blocker(
                BlockerCode.ABSENT_CHAOS,
                "absent chaos receipt digest",
                subject=subject,
            )
        )

    fresh_block = _check_freshness(
        evidence.collected_at, now=now, max_age=max_age, subject=subject
    )
    if fresh_block:
        blockers.append(fresh_block)

    return blockers


def evaluate_environment(
    environment: Optional[EnvironmentBinding],
    *,
    expected_tree_id: str,
) -> List[ReleaseBlocker]:
    """Require a labelled, non-unknown environment bound to the tree."""

    if environment is None:
        return [
            _blocker(
                BlockerCode.MISSING_ENVIRONMENT,
                "missing labelled environment binding",
                subject="environment",
            )
        ]

    blockers: List[ReleaseBlocker] = []
    subject = "environment"
    if is_unknown_environment(environment.environment_id):
        blockers.append(
            _blocker(
                BlockerCode.UNKNOWN_ENVIRONMENT,
                "unknown environment is not an acceptable release target",
                subject=subject,
                environment_id=environment.environment_id,
            )
        )
    if not str(environment.label or "").strip():
        blockers.append(
            _blocker(
                BlockerCode.UNKNOWN_ENVIRONMENT,
                "environment label is required",
                subject=subject,
            )
        )
    tree_block = _check_tree(
        environment.tree_id, expected_tree_id, subject=subject
    )
    if tree_block:
        blockers.append(tree_block)
    return blockers


def evaluate_release_evidence(
    bundle: Optional[ReleaseEvidenceBundle],
    *,
    expected_tree_id: str,
    now: Optional[datetime] = None,
    max_receipt_age: timedelta = DEFAULT_MAX_RECEIPT_AGE,
    signing_key: Optional[bytes | str] = None,
    package_version: str = "",
    notes: str = "",
) -> ReleaseDecision:
    """Evaluate a release evidence bundle and emit a signed decision.

    The platform is **not** production ready unless the returned decision has
    ``production_ready is True`` and ``outcome == "pass"``.
    """

    evaluated_at_dt = (now or _now_utc()).astimezone(timezone.utc).replace(
        microsecond=0
    )
    evaluated_at = _format_ts(evaluated_at_dt)
    blockers: List[ReleaseBlocker] = []
    satisfied_goals: List[str] = []
    satisfied_dod: List[str] = []
    bundle_digest = ""

    if bundle is None:
        blockers.append(
            _blocker(
                BlockerCode.MISSING_BUNDLE,
                "no release evidence bundle provided",
                subject="bundle",
            )
        )
    else:
        if bundle.schema_version and bundle.schema_version != BUNDLE_SCHEMA_VERSION:
            blockers.append(
                _blocker(
                    BlockerCode.SCHEMA_MISMATCH,
                    "evidence bundle schema_version mismatch",
                    subject="bundle",
                    expected=BUNDLE_SCHEMA_VERSION,
                    actual=bundle.schema_version,
                )
            )

        if not expected_tree_id:
            blockers.append(
                _blocker(
                    BlockerCode.FOREIGN_TREE,
                    "expected_tree_id is required for evaluation",
                    subject="tree",
                )
            )
        elif bundle.tree_id != expected_tree_id:
            blockers.append(
                _blocker(
                    BlockerCode.FOREIGN_TREE,
                    "bundle tree_id does not match expected tree",
                    subject="bundle",
                    evidence_tree_id=bundle.tree_id,
                    expected_tree_id=expected_tree_id,
                )
            )

        bundle_digest = bundle.content_digest()

        goals_ok, goal_blockers = evaluate_goal_receipts(
            bundle.goal_receipts,
            expected_tree_id=expected_tree_id,
            now=evaluated_at_dt,
            max_age=max_receipt_age,
        )
        satisfied_goals = goals_ok
        blockers.extend(goal_blockers)

        dod_ok, dod_blockers = evaluate_dod_receipts(
            bundle.dod_receipts,
            expected_tree_id=expected_tree_id,
            now=evaluated_at_dt,
            max_age=max_receipt_age,
        )
        satisfied_dod = dod_ok
        blockers.extend(dod_blockers)

        blockers.extend(
            evaluate_corpus_signoffs(
                bundle.corpus_signoffs,
                expected_tree_id=expected_tree_id,
                now=evaluated_at_dt,
                max_age=max_receipt_age,
            )
        )
        blockers.extend(
            evaluate_ucan_negative(
                bundle.ucan_negative,
                expected_tree_id=expected_tree_id,
                now=evaluated_at_dt,
                max_age=max_receipt_age,
            )
        )
        blockers.extend(
            evaluate_soak_chaos(
                bundle.soak_chaos,
                expected_tree_id=expected_tree_id,
                now=evaluated_at_dt,
                max_age=max_receipt_age,
            )
        )
        blockers.extend(
            evaluate_environment(
                bundle.environment,
                expected_tree_id=expected_tree_id,
            )
        )

        # Partial: some goals/clauses present but not all.
        if (
            (satisfied_goals or satisfied_dod)
            and (
                set(satisfied_goals) != set(REQUIRED_CHILD_GOALS)
                or set(satisfied_dod) != set(ROOT_DOD_CLAUSE_IDS)
            )
            and not any(
                b.code
                in {
                    BlockerCode.MISSING_GOAL_RECEIPT.value,
                    BlockerCode.MISSING_DOD_CLAUSE.value,
                }
                for b in blockers
            )
        ):
            # Always surface partial when not fully satisfied.
            pass
        if set(satisfied_goals) != set(REQUIRED_CHILD_GOALS) or set(
            satisfied_dod
        ) != set(ROOT_DOD_CLAUSE_IDS):
            if not any(
                b.code
                in {
                    BlockerCode.MISSING_GOAL_RECEIPT.value,
                    BlockerCode.MISSING_DOD_CLAUSE.value,
                    BlockerCode.PARTIAL_EVIDENCE.value,
                }
                for b in blockers
            ):
                blockers.append(
                    _blocker(
                        BlockerCode.PARTIAL_EVIDENCE,
                        "evidence set is partial relative to required goals/DoD",
                        subject="bundle",
                        satisfied_goals=list(satisfied_goals),
                        satisfied_dod=list(satisfied_dod),
                    )
                )

    production_ready = len(blockers) == 0
    if production_ready:
        outcome = DecisionOutcome.PASS.value
    else:
        # Distinguish empty/missing from other failures for operators.
        if bundle is None:
            outcome = DecisionOutcome.NOT_PRODUCTION_READY.value
        else:
            outcome = DecisionOutcome.FAIL.value

    decision = ReleaseDecision(
        outcome=outcome,
        production_ready=production_ready,
        tree_id=expected_tree_id or (bundle.tree_id if bundle else ""),
        evaluated_at=evaluated_at,
        blockers=tuple(blockers),
        required_child_goals=REQUIRED_CHILD_GOALS,
        required_dod_clauses=ROOT_DOD_CLAUSE_IDS,
        satisfied_child_goals=tuple(satisfied_goals),
        satisfied_dod_clauses=tuple(satisfied_dod),
        bundle_digest=bundle_digest,
        package_version=package_version
        or (bundle.package_version if bundle else ""),
        notes=notes or (bundle.notes if bundle else ""),
    )

    if signing_key is not None:
        decision = sign_decision(decision, signing_key=signing_key)
    else:
        # Still produce a content-addressed "signature" from the decision body
        # so every decision is content-addressed even without an operator key.
        body_sig = content_address(
            decision.signing_payload().decode("utf-8"),
            domain=SIGNATURE_DOMAIN,
        )
        decision = ReleaseDecision(
            outcome=decision.outcome,
            production_ready=decision.production_ready,
            tree_id=decision.tree_id,
            evaluated_at=decision.evaluated_at,
            blockers=decision.blockers,
            required_child_goals=decision.required_child_goals,
            required_dod_clauses=decision.required_dod_clauses,
            satisfied_child_goals=decision.satisfied_child_goals,
            satisfied_dod_clauses=decision.satisfied_dod_clauses,
            bundle_digest=decision.bundle_digest,
            decision_cid=decision.decision_cid,
            signature=f"content-addressed:{body_sig}",
            schema_version=decision.schema_version,
            policy_id=decision.policy_id,
            task_id=decision.task_id,
            goal_id=decision.goal_id,
            package_version=decision.package_version,
            notes=decision.notes,
        )

    return decision


def is_production_ready(decision: Optional[ReleaseDecision] = None) -> bool:
    """Return whether the platform may be treated as production ready.

    Without a passing decision, the answer is always ``False``.
    """

    if decision is None:
        return False
    return bool(decision.production_ready and decision.is_pass())


def default_not_production_ready_decision(
    *,
    tree_id: str = "",
    reason: str = "no release evidence gate evaluation has passed",
    signing_key: Optional[bytes | str] = None,
) -> ReleaseDecision:
    """Emit the standing not-production-ready decision."""

    bundle = None
    return evaluate_release_evidence(
        bundle,
        expected_tree_id=tree_id,
        signing_key=signing_key,
        notes=reason,
    )


# ---------------------------------------------------------------------------
# GraphReleaseGate facade
# ---------------------------------------------------------------------------


class GraphReleaseGate:
    """Fail-closed production release evidence gate.

    Example::

        gate = GraphReleaseGate(expected_tree_id=tree_id, signing_key=key)
        decision = gate.evaluate(bundle)
        assert gate.is_production_ready(decision)  # False until all evidence lands
    """

    def __init__(
        self,
        *,
        expected_tree_id: str,
        signing_key: Optional[bytes | str] = None,
        max_receipt_age: timedelta = DEFAULT_MAX_RECEIPT_AGE,
        package_version: str = "",
    ) -> None:
        if not expected_tree_id:
            raise ReleaseGateError(
                "expected_tree_id is required",
                code="missing_tree_id",
            )
        self.expected_tree_id = expected_tree_id
        self.signing_key = signing_key
        self.max_receipt_age = max_receipt_age
        self.package_version = package_version
        self._last_decision: Optional[ReleaseDecision] = None

    @property
    def last_decision(self) -> Optional[ReleaseDecision]:
        return self._last_decision

    def evaluate(
        self,
        bundle: Optional[ReleaseEvidenceBundle],
        *,
        now: Optional[datetime] = None,
        notes: str = "",
    ) -> ReleaseDecision:
        """Evaluate *bundle* and retain the resulting decision."""

        decision = evaluate_release_evidence(
            bundle,
            expected_tree_id=self.expected_tree_id,
            now=now,
            max_receipt_age=self.max_receipt_age,
            signing_key=self.signing_key,
            package_version=self.package_version,
            notes=notes,
        )
        self._last_decision = decision
        return decision

    def evaluate_or_raise(
        self,
        bundle: Optional[ReleaseEvidenceBundle],
        *,
        now: Optional[datetime] = None,
        notes: str = "",
    ) -> ReleaseDecision:
        """Evaluate and raise :class:`ReleaseGateFailClosed` on failure."""

        decision = self.evaluate(bundle, now=now, notes=notes)
        if not decision.is_pass():
            raise ReleaseGateFailClosed(
                "release evidence gate failed closed",
                code="not_production_ready",
                details={
                    "outcome": decision.outcome,
                    "blocker_count": len(decision.blockers),
                    "decision_cid": decision.decision_cid,
                },
                decision=decision,
            )
        return decision

    def is_production_ready(
        self, decision: Optional[ReleaseDecision] = None
    ) -> bool:
        """Return production readiness for *decision* or the last evaluation."""

        target = decision if decision is not None else self._last_decision
        return is_production_ready(target)

    def standing_decision(self) -> ReleaseDecision:
        """Return the default not-production-ready decision for this tree."""

        decision = default_not_production_ready_decision(
            tree_id=self.expected_tree_id,
            signing_key=self.signing_key,
        )
        self._last_decision = decision
        return decision


# ---------------------------------------------------------------------------
# Helpers for building valid fixtures / operator bundles
# ---------------------------------------------------------------------------


def make_goal_receipt(
    goal_id: str,
    *,
    tree_id: str,
    collected_at: Optional[str] = None,
    evidence_kind: str = "validation_receipt",
    status: str = "pass",
    validation_command: str = "",
    notes: str = "",
) -> GoalReceipt:
    """Build a :class:`GoalReceipt` with a correct content digest."""

    return GoalReceipt(
        goal_id=goal_id,
        tree_id=tree_id,
        status=status,
        collected_at=collected_at or _format_ts(_now_utc()),
        evidence_kind=evidence_kind,
        validation_command=validation_command,
        notes=notes,
    )


def make_dod_receipt(
    clause_id: str,
    *,
    tree_id: str,
    collected_at: Optional[str] = None,
    evidence_kind: str = "validation_receipt",
    status: str = "pass",
    validation_command: str = "",
    notes: str = "",
) -> DodClauseReceipt:
    """Build a :class:`DodClauseReceipt` with a correct content digest."""

    return DodClauseReceipt(
        clause_id=clause_id,
        tree_id=tree_id,
        status=status,
        collected_at=collected_at or _format_ts(_now_utc()),
        evidence_kind=evidence_kind,
        validation_command=validation_command,
        notes=notes,
    )


def make_corpus_signoff(
    corpus_id: str,
    *,
    tree_id: str,
    producer_id: str,
    signer: str,
    mode: str = "full",
    signed_at: Optional[str] = None,
    statement: str = "",
) -> CorpusSignOff:
    """Build a full-mode corpus sign-off."""

    return CorpusSignOff(
        corpus_id=corpus_id,
        producer_id=producer_id,
        signer=signer,
        signed_at=signed_at or _format_ts(_now_utc()),
        tree_id=tree_id,
        mode=mode,
        statement=statement
        or f"Producer {producer_id} signs off corpus {corpus_id} for release.",
    )


def build_passing_bundle(
    *,
    tree_id: str,
    environment_id: str = "lab-kg-release-1",
    environment_label: str = "labelled lab environment",
    now: Optional[datetime] = None,
    package_version: str = "0.0.0-test",
) -> ReleaseEvidenceBundle:
    """Construct a complete, fresh, passing evidence bundle for *tree_id*.

    Intended for tests and operator dry-runs. Production use still requires
    real validation receipts generated by the child-goal harnesses.
    """

    ts = _format_ts((now or _now_utc()))
    goals = [
        make_goal_receipt(
            goal_id,
            tree_id=tree_id,
            collected_at=ts,
            validation_command=f"pytest -q for {goal_id}",
        )
        for goal_id in REQUIRED_CHILD_GOALS
    ]
    # Map DoD clauses to appropriate evidence kinds.
    kind_for_clause = {
        "concurrent_identity_durability": "concurrency_receipt",
        "storage_profiles_contract": "storage_contract",
        "four_surface_parity": "surface_conformance",
        "ucan_fail_closed": "ucan_audit_receipt",
        "sharded_integrity": "sharding_integrity",
        "corpora_differential": "corpus_differential",
        "load_soak_chaos_ops": "load_receipt",
        "migration_reversible": "migration_receipt",
    }
    dods = [
        make_dod_receipt(
            clause.clause_id,
            tree_id=tree_id,
            collected_at=ts,
            evidence_kind=kind_for_clause.get(
                clause.clause_id, "validation_receipt"
            ),
        )
        for clause in ROOT_DOD_CLAUSES
    ]
    signoffs = [
        make_corpus_signoff(
            corpus_id,
            tree_id=tree_id,
            producer_id=f"producer-{corpus_id}",
            signer=f"owner-{corpus_id}",
            signed_at=ts,
        )
        for corpus_id in REQUIRED_CORPORA
    ]
    ucan = UCANNegativeProof(
        tree_id=tree_id,
        deny_receipt_cids=(
            "sha256:" + "a" * 64,
            "sha256:" + "b" * 64,
        ),
        collected_at=ts,
    )
    soak = SoakChaosEvidence(
        tree_id=tree_id,
        environment_id=environment_id,
        soak_receipt_digest="sha256:" + "c" * 64,
        chaos_receipt_digest="sha256:" + "d" * 64,
        collected_at=ts,
        load_receipt_digest="sha256:" + "e" * 64,
    )
    env = EnvironmentBinding(
        environment_id=environment_id,
        label=environment_label,
        tree_id=tree_id,
        collected_at=ts,
    )
    return ReleaseEvidenceBundle(
        tree_id=tree_id,
        goal_receipts=goals,
        dod_receipts=dods,
        corpus_signoffs=signoffs,
        ucan_negative=ucan,
        soak_chaos=soak,
        environment=env,
        package_version=package_version,
    )


def policy_dict() -> Dict[str, Any]:
    """Return a JSON-serializable summary of the release gate policy."""

    return {
        "accepted_evidence_kinds": sorted(ACCEPTED_EVIDENCE_KINDS),
        "bundle_schema_version": BUNDLE_SCHEMA_VERSION,
        "decision_schema_version": DECISION_SCHEMA_VERSION,
        "default_max_receipt_age_days": DEFAULT_MAX_RECEIPT_AGE.days,
        "goal_id": GOAL_ID,
        "policy_id": POLICY_ID,
        "rejected_substitutes": sorted(REJECTED_SUBSTITUTES),
        "required_child_goals": list(REQUIRED_CHILD_GOALS),
        "required_corpora": list(REQUIRED_CORPORA),
        "required_dod_clauses": [
            {"clause_id": c.clause_id, "description": c.description}
            for c in ROOT_DOD_CLAUSES
        ],
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
    }


__all__ = [
    "ACCEPTED_EVIDENCE_KINDS",
    "BUNDLE_SCHEMA_VERSION",
    "BlockerCode",
    "CorpusSignOff",
    "DECISION_SCHEMA_VERSION",
    "DEFAULT_MAX_RECEIPT_AGE",
    "DecisionOutcome",
    "DodClauseReceipt",
    "EnvironmentBinding",
    "GOAL_ID",
    "GoalReceipt",
    "GraphReleaseGate",
    "POLICY_ID",
    "RECEIPT_SCHEMA_VERSION",
    "REJECTED_SUBSTITUTES",
    "REQUIRED_CHILD_GOALS",
    "REQUIRED_CORPORA",
    "ROOT_DOD_CLAUSE_IDS",
    "ROOT_DOD_CLAUSES",
    "ReleaseBlocker",
    "ReleaseDecision",
    "ReleaseEvidenceBundle",
    "ReleaseGateError",
    "ReleaseGateFailClosed",
    "SCHEMA_VERSION",
    "SoakChaosEvidence",
    "TASK_ID",
    "UCANNegativeProof",
    "build_passing_bundle",
    "canonical_json_bytes",
    "canonicalize",
    "content_address",
    "content_cid",
    "default_not_production_ready_decision",
    "evaluate_release_evidence",
    "is_production_ready",
    "is_rejected_substitute",
    "is_unknown_environment",
    "make_corpus_signoff",
    "make_dod_receipt",
    "make_goal_receipt",
    "parse_timestamp",
    "policy_dict",
    "sign_decision",
    "verify_decision_signature",
]
