"""Database-native residual analysis and self-improvement loop (DQK-054).

Runs bounded datasets inventory, schema, parity, performance, blocker, and
coverage analyzers against identified snapshots, then submits deduplicated
findings through the DQP-039 database-native planning interface
(:class:`~ipfs_datasets_py.duckdb_control.inventory_refinement.CanonicalPlanRevisionAPI`).

Acceptance (DQK-054):

* Findings cannot bypass DQP planning/acceptance policy
* Duplicate or stale findings do not create task storms
* The loop uses DuckDB authority rather than Markdown objective refill
* Cross-repository proposals bind separate immutable Git trees and receipt
  identities

Authority rules (fail-closed):

* The only mutation surface is the DQP plan-revision API; raw task status
  mutation, Markdown objective refill, and analyzer self-approval are refused.
* Proposals remain ``non_active`` until generation rollover (DQK-083).
* A content-bound finding ledger suppresses duplicate and stale re-submissions.
* Each repository proposal binds its own ``repository_tree_id`` and
  ``snapshot_receipt_cid``; trees and receipts never cross repositories.

Importing this module is inert: no filesystem, network, or database I/O until
an explicit entry point is called.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    Final,
    Iterable,
    Mapping,
    Protocol,
    Sequence,
)

from ipfs_datasets_py.duckdb_control.contracts import (
    SnapshotId,
    content_identity,
    normalize_timestamp,
    parse_snapshot_id,
)
from ipfs_datasets_py.duckdb_control.inventory_refinement import (
    APPROVAL_GATE_TASK_ID as _DQP_APPROVAL_GATE,
    CanonicalPlanRevisionAPI,
    GapFinding,
    GapProposal,
    InventoryRefinementError,
    MemoryPlanRevisionAPI,
    PlanRevisionAdapter,
    PlanRevisionRequest,
    ProposalStatus,
    RefinementBudget,
    ROLLOVER_GATE_TASK_ID as _DQP_ROLLOVER_GATE,
    build_gap_proposals,
    deduplicate_findings as _dedupe_gap_findings,
)

__all__ = [
    "ANALYZER_KINDS",
    "AUTHORITY_SURFACE",
    "DEFAULT_ANALYZER_IDS",
    "FINDING_SCHEMA",
    "LOOP_SCHEMA",
    "OWNER_TASK_ID",
    "PROGRAM_ID",
    "RECEIPT_SCHEMA",
    "SNAPSHOT_BINDING_SCHEMA",
    "AnalysisBudget",
    "AnalyzerKind",
    "FindingLedger",
    "FindingSeverity",
    "IdentifiedSnapshot",
    "LoopReceipt",
    "MarkdownRefillError",
    "MemoryFindingLedger",
    "ResidualAnalyzer",
    "ResidualFinding",
    "SelfImprovementError",
    "SelfImprovementLoop",
    "SnapshotObservation",
    "analyze_blockers",
    "analyze_coverage",
    "analyze_inventory",
    "analyze_parity",
    "analyze_performance",
    "analyze_schema",
    "build_gap_proposals_from_residuals",
    "deduplicate_residual_findings",
    "filter_stale_and_duplicate_findings",
    "main",
    "run_analyzers",
    "self_check",
    "submit_residual_findings",
]


# ---------------------------------------------------------------------------
# Schemas / constants
# ---------------------------------------------------------------------------

OWNER_TASK_ID: Final[str] = "DQK-054"
PROGRAM_ID: Final[str] = "ipfs-datasets-duckdb-quack-control-plane-v1"
APPROVAL_GATE_TASK_ID: Final[str] = _DQP_APPROVAL_GATE  # DQK-081
ROLLOVER_GATE_TASK_ID: Final[str] = _DQP_ROLLOVER_GATE  # DQK-083

LOOP_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control/self-improvement-loop@1"
)
FINDING_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control/residual-finding@1"
)
SNAPSHOT_BINDING_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control/identified-snapshot@1"
)
RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control/self-improvement-loop-receipt@1"
)

AUTHORITY_SURFACE: Final[str] = "duckdb_plan_revision_api"
MARKDOWN_REFILL_SURFACE: Final[str] = "markdown_objective_refill"

# Default budgets keep residual analysis deterministic and storm-resistant.
DEFAULT_MAX_FINDINGS_PER_ANALYZER: Final[int] = 32
DEFAULT_MAX_TOTAL_FINDINGS: Final[int] = 128
DEFAULT_MAX_PROPOSALS: Final[int] = 32
DEFAULT_MAX_MODEL_CALLS: Final[int] = 0  # pure deterministic path
DEFAULT_STALENESS_SECONDS: Final[int] = 86_400  # 24h

_MAX_FIELD_BYTES: Final[int] = 4096
_SHA256_DIGEST: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_OID: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_CONTROL_CHARS: Final[frozenset[str]] = frozenset(("\0", "\n", "\r"))

DEFAULT_ANALYZER_IDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "inventory": "analyzer:datasets-inventory",
        "schema": "analyzer:datasets-schema",
        "parity": "analyzer:datasets-parity",
        "performance": "analyzer:datasets-performance",
        "blocker": "analyzer:datasets-blocker",
        "coverage": "analyzer:datasets-coverage",
    }
)


class SelfImprovementError(ValueError):
    """Raised when residual analysis inputs, budgets, or policy fail closed."""


class MarkdownRefillError(SelfImprovementError):
    """Raised when a caller attempts Markdown objective refill authority."""


class AnalyzerKind(str, Enum):
    """Closed set of residual analyzers admitted by DQK-054."""

    INVENTORY = "inventory"
    SCHEMA = "schema"
    PARITY = "parity"
    PERFORMANCE = "performance"
    BLOCKER = "blocker"
    COVERAGE = "coverage"

    @classmethod
    def parse(cls, value: str | AnalyzerKind) -> AnalyzerKind:
        if isinstance(value, AnalyzerKind):
            return value
        text = str(value).strip().lower().replace("-", "_")
        try:
            return cls(text)
        except ValueError as exc:
            raise SelfImprovementError(
                f"unsupported analyzer kind {value!r}; "
                f"admitted: {', '.join(item.value for item in cls)}"
            ) from exc


ANALYZER_KINDS: Final[tuple[AnalyzerKind, ...]] = tuple(AnalyzerKind)


class FindingSeverity(str, Enum):
    """Closed severity vocabulary for residual findings."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @classmethod
    def parse(cls, value: str | FindingSeverity) -> FindingSeverity:
        if isinstance(value, FindingSeverity):
            return value
        text = str(value).strip().lower()
        try:
            return cls(text)
        except ValueError as exc:
            raise SelfImprovementError(
                f"unsupported finding severity {value!r}"
            ) from exc


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AnalysisBudget:
    """Hard caps on residual analysis and proposal emission.

    Zero for model calls means the pure deterministic path (no LLM). Zero for
    finding or proposal caps blocks generation entirely.
    """

    max_findings_per_analyzer: int = DEFAULT_MAX_FINDINGS_PER_ANALYZER
    max_total_findings: int = DEFAULT_MAX_TOTAL_FINDINGS
    max_proposals: int = DEFAULT_MAX_PROPOSALS
    max_model_calls: int = DEFAULT_MAX_MODEL_CALLS
    staleness_seconds: int = DEFAULT_STALENESS_SECONDS
    max_goals: int = 32
    max_tasks: int = 128
    max_depth: int = 4
    max_retries: int = 2

    def __post_init__(self) -> None:
        for name in (
            "max_findings_per_analyzer",
            "max_total_findings",
            "max_proposals",
            "max_model_calls",
            "staleness_seconds",
            "max_goals",
            "max_tasks",
            "max_depth",
            "max_retries",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise SelfImprovementError(
                    f"{name} must be a non-negative integer, got {value!r}"
                )

    @property
    def allows_model_calls(self) -> bool:
        return self.max_model_calls > 0

    def to_refinement_budget(self) -> RefinementBudget:
        return RefinementBudget(
            max_goals=self.max_goals,
            max_tasks=min(self.max_tasks, self.max_total_findings or self.max_tasks),
            max_depth=self.max_depth,
            max_retries=self.max_retries,
            max_model_calls=self.max_model_calls,
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "max_findings_per_analyzer": self.max_findings_per_analyzer,
            "max_total_findings": self.max_total_findings,
            "max_proposals": self.max_proposals,
            "max_model_calls": self.max_model_calls,
            "staleness_seconds": self.staleness_seconds,
            "max_goals": self.max_goals,
            "max_tasks": self.max_tasks,
            "max_depth": self.max_depth,
            "max_retries": self.max_retries,
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> AnalysisBudget:
        if payload is None:
            return cls()
        if not isinstance(payload, Mapping):
            raise SelfImprovementError("analysis budget must be an object")
        return cls(
            max_findings_per_analyzer=int(
                payload.get(
                    "max_findings_per_analyzer", DEFAULT_MAX_FINDINGS_PER_ANALYZER
                )
            ),
            max_total_findings=int(
                payload.get("max_total_findings", DEFAULT_MAX_TOTAL_FINDINGS)
            ),
            max_proposals=int(payload.get("max_proposals", DEFAULT_MAX_PROPOSALS)),
            max_model_calls=int(
                payload.get("max_model_calls", DEFAULT_MAX_MODEL_CALLS)
            ),
            staleness_seconds=int(
                payload.get("staleness_seconds", DEFAULT_STALENESS_SECONDS)
            ),
            max_goals=int(payload.get("max_goals", 32)),
            max_tasks=int(payload.get("max_tasks", 128)),
            max_depth=int(payload.get("max_depth", 4)),
            max_retries=int(payload.get("max_retries", 2)),
        )


# ---------------------------------------------------------------------------
# Snapshot identity binding
# ---------------------------------------------------------------------------


def _reject_control_chars(value: str, field_name: str) -> None:
    if any(character in value for character in _CONTROL_CHARS):
        raise SelfImprovementError(
            f"{field_name} must not contain control characters"
        )
    if len(value.encode("utf-8")) > _MAX_FIELD_BYTES:
        raise SelfImprovementError(
            f"{field_name} exceeds {_MAX_FIELD_BYTES}-byte bound"
        )


def _require_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SelfImprovementError(f"{field} must be nonempty text")
    text = value.strip()
    _reject_control_chars(text, field)
    return text


def _require_git_oid(value: Any, *, field: str) -> str:
    text = _require_text(value, field=field).lower()
    if not _GIT_OID.fullmatch(text):
        raise SelfImprovementError(f"{field} must be a 40-char git object id")
    return text


def _require_sha256(value: Any, *, field: str) -> str:
    text = _require_text(value, field=field).lower()
    if not text.startswith("sha256:"):
        if re.fullmatch(r"[0-9a-f]{64}", text):
            text = f"sha256:{text}"
        else:
            raise SelfImprovementError(f"{field} must be sha256:<64 hex>")
    if not _SHA256_DIGEST.fullmatch(text):
        raise SelfImprovementError(f"{field} must be sha256:<64 hex>")
    return text


def _parse_utc(value: Any, *, field: str) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise SelfImprovementError(f"{field} must be timezone-aware UTC")
        return value.astimezone(timezone.utc)
    text = _require_text(value, field=field)
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SelfImprovementError(f"{field} is not ISO-8601") from exc
    if moment.tzinfo is None:
        raise SelfImprovementError(f"{field} must be timezone-aware UTC")
    return moment.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class IdentifiedSnapshot:
    """Snapshot identity bound to one repository tree and receipt.

    Cross-repository loops must use distinct :attr:`repository_tree_id` and
    :attr:`snapshot_receipt_cid` values per repository — never shared trees.
    """

    repository_id: str
    repository_tree_id: str
    snapshot_id: str
    snapshot_receipt_cid: str
    store_generation: int = 0
    schema_checksum: str = ""
    base_plan_root_cid: str = ""
    schema: str = SNAPSHOT_BINDING_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != SNAPSHOT_BINDING_SCHEMA:
            raise SelfImprovementError(
                f"identified snapshot schema must be {SNAPSHOT_BINDING_SCHEMA}"
            )
        object.__setattr__(
            self, "repository_id", _require_text(self.repository_id, field="repository_id")
        )
        object.__setattr__(
            self,
            "repository_tree_id",
            _require_git_oid(self.repository_tree_id, field="repository_tree_id"),
        )
        object.__setattr__(
            self, "snapshot_id", parse_snapshot_id(str(self.snapshot_id).strip())
        )
        object.__setattr__(
            self,
            "snapshot_receipt_cid",
            _require_sha256(
                self.snapshot_receipt_cid, field="snapshot_receipt_cid"
            ),
        )
        if isinstance(self.store_generation, bool) or not isinstance(
            self.store_generation, int
        ):
            raise SelfImprovementError("store_generation must be an integer")
        if self.store_generation < 0:
            raise SelfImprovementError("store_generation must be non-negative")
        if self.schema_checksum:
            object.__setattr__(
                self,
                "schema_checksum",
                _require_sha256(self.schema_checksum, field="schema_checksum"),
            )
        if self.base_plan_root_cid:
            object.__setattr__(
                self,
                "base_plan_root_cid",
                _require_sha256(self.base_plan_root_cid, field="base_plan_root_cid"),
            )

    @property
    def binding_cid(self) -> str:
        """Content identity of the repository+tree+snapshot+receipt binding."""

        return content_identity(self.to_dict())

    @property
    def as_snapshot_id(self) -> SnapshotId:
        return SnapshotId(
            value=self.snapshot_id,
            store_generation=self.store_generation,
            schema_checksum=self.schema_checksum,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "repository_id": self.repository_id,
            "repository_tree_id": self.repository_tree_id,
            "snapshot_id": self.snapshot_id,
            "snapshot_receipt_cid": self.snapshot_receipt_cid,
            "store_generation": self.store_generation,
            "schema_checksum": self.schema_checksum,
            "base_plan_root_cid": self.base_plan_root_cid,
            "binding_cid": content_identity(
                {
                    "repository_id": self.repository_id,
                    "repository_tree_id": self.repository_tree_id,
                    "snapshot_id": self.snapshot_id,
                    "snapshot_receipt_cid": self.snapshot_receipt_cid,
                    "store_generation": self.store_generation,
                    "schema_checksum": self.schema_checksum,
                }
            ),
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> IdentifiedSnapshot:
        if not isinstance(payload, Mapping):
            raise SelfImprovementError("identified snapshot must be an object")
        return cls(
            repository_id=str(payload.get("repository_id") or ""),
            repository_tree_id=str(payload.get("repository_tree_id") or ""),
            snapshot_id=str(payload.get("snapshot_id") or ""),
            snapshot_receipt_cid=str(payload.get("snapshot_receipt_cid") or ""),
            store_generation=int(payload.get("store_generation", 0)),
            schema_checksum=str(payload.get("schema_checksum") or ""),
            base_plan_root_cid=str(payload.get("base_plan_root_cid") or ""),
            schema=str(payload.get("schema") or SNAPSHOT_BINDING_SCHEMA),
        )


# ---------------------------------------------------------------------------
# Residual findings
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResidualFinding:
    """One residual gap discovered against an identified snapshot.

    Finding keys are content-bound over analyzer, subject, reason, snapshot
    receipt, and repository tree so duplicate/stale resubmissions collapse.
    """

    analyzer: AnalyzerKind
    subject: str
    reason: str
    severity: FindingSeverity = FindingSeverity.MEDIUM
    evidence_digest: str = ""
    repository_id: str = ""
    repository_tree_id: str = ""
    snapshot_id: str = ""
    snapshot_receipt_cid: str = ""
    observed_at: str = ""
    finding_key: str = ""
    path: str = ""
    schema: str = FINDING_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != FINDING_SCHEMA:
            raise SelfImprovementError(
                f"finding schema must be {FINDING_SCHEMA}"
            )
        analyzer = AnalyzerKind.parse(self.analyzer)
        object.__setattr__(self, "analyzer", analyzer)
        object.__setattr__(
            self, "subject", _require_text(self.subject, field="subject")
        )
        object.__setattr__(
            self, "reason", _require_text(self.reason, field="reason")
        )
        object.__setattr__(
            self, "severity", FindingSeverity.parse(self.severity)
        )
        if self.evidence_digest:
            object.__setattr__(
                self,
                "evidence_digest",
                _require_sha256(self.evidence_digest, field="evidence_digest"),
            )
        if self.repository_id:
            object.__setattr__(
                self,
                "repository_id",
                _require_text(self.repository_id, field="repository_id"),
            )
        if self.repository_tree_id:
            object.__setattr__(
                self,
                "repository_tree_id",
                _require_git_oid(
                    self.repository_tree_id, field="repository_tree_id"
                ),
            )
        if self.snapshot_id:
            object.__setattr__(
                self, "snapshot_id", parse_snapshot_id(str(self.snapshot_id).strip())
            )
        if self.snapshot_receipt_cid:
            object.__setattr__(
                self,
                "snapshot_receipt_cid",
                _require_sha256(
                    self.snapshot_receipt_cid, field="snapshot_receipt_cid"
                ),
            )
        if self.observed_at:
            moment = _parse_utc(self.observed_at, field="observed_at")
            object.__setattr__(self, "observed_at", normalize_timestamp(moment))
        if self.path:
            object.__setattr__(
                self, "path", _require_text(self.path, field="path")
            )
        if not self.finding_key:
            material = {
                "analyzer": analyzer.value,
                "subject": self.subject,
                "reason": self.reason,
                "repository_id": self.repository_id,
                "repository_tree_id": self.repository_tree_id,
                "snapshot_receipt_cid": self.snapshot_receipt_cid,
                "evidence_digest": self.evidence_digest,
            }
            object.__setattr__(self, "finding_key", content_identity(material))
        else:
            object.__setattr__(
                self,
                "finding_key",
                _require_sha256(self.finding_key, field="finding_key"),
            )

    def bind_snapshot(self, snapshot: IdentifiedSnapshot) -> ResidualFinding:
        """Return a copy of this finding bound to *snapshot* identity."""

        return ResidualFinding(
            analyzer=self.analyzer,
            subject=self.subject,
            reason=self.reason,
            severity=self.severity,
            evidence_digest=self.evidence_digest,
            repository_id=snapshot.repository_id,
            repository_tree_id=snapshot.repository_tree_id,
            snapshot_id=snapshot.snapshot_id,
            snapshot_receipt_cid=snapshot.snapshot_receipt_cid,
            observed_at=self.observed_at,
            path=self.path or self.subject,
            finding_key="",  # recompute under new binding
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "analyzer": self.analyzer.value,
            "subject": self.subject,
            "reason": self.reason,
            "severity": self.severity.value,
            "evidence_digest": self.evidence_digest,
            "repository_id": self.repository_id,
            "repository_tree_id": self.repository_tree_id,
            "snapshot_id": self.snapshot_id,
            "snapshot_receipt_cid": self.snapshot_receipt_cid,
            "observed_at": self.observed_at,
            "finding_key": self.finding_key,
            "path": self.path or self.subject,
        }

    def to_gap_finding(self) -> GapFinding:
        """Project into a DQP inventory gap finding for plan-revision submit."""

        digest = self.evidence_digest
        if digest.startswith("sha256:"):
            digest = digest[len("sha256:") :]
        if not digest:
            digest = hashlib.sha256(
                self.finding_key.encode("utf-8")
            ).hexdigest()
        path = self.path or self.subject
        # GapFinding requires a relative path-like subject; normalize.
        if path.startswith("/"):
            path = path.lstrip("/")
        if not path:
            path = f"residual/{self.analyzer.value}/{self.finding_key[-12:]}"
        return GapFinding(
            path=path,
            kind=f"residual_{self.analyzer.value}",
            digest=digest,
            producer=f"analyzer:{self.analyzer.value}",
            consumer="self-improvement-loop",
            proposed_authority="control_duckdb",
            reason=self.reason,
            gap_key=self.finding_key,
        )


def deduplicate_residual_findings(
    findings: Sequence[ResidualFinding],
) -> tuple[ResidualFinding, ...]:
    """Collapse findings by finding_key, preserving first-seen severity order."""

    seen: dict[str, ResidualFinding] = {}
    for finding in findings:
        if finding.finding_key not in seen:
            seen[finding.finding_key] = finding
    ordered = sorted(
        seen.values(),
        key=lambda item: (
            item.analyzer.value,
            item.subject.encode("utf-8"),
            item.finding_key,
        ),
    )
    return tuple(ordered)


def filter_stale_and_duplicate_findings(
    findings: Sequence[ResidualFinding],
    ledger: "FindingLedger",
    *,
    budget: AnalysisBudget | None = None,
    now: datetime | None = None,
) -> tuple[ResidualFinding, ...]:
    """Drop findings already admitted or older than the staleness window.

    This is the storm-prevention gate: identical finding keys already in the
    ledger, and findings whose ``observed_at`` is outside the budget window,
    never create new proposals.
    """

    limits = budget if budget is not None else AnalysisBudget()
    moment = now if now is not None else datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise SelfImprovementError("now must be timezone-aware UTC")
    moment = moment.astimezone(timezone.utc)

    unique = deduplicate_residual_findings(findings)
    admitted: list[ResidualFinding] = []
    for finding in unique:
        if ledger.has_finding(finding.finding_key):
            continue
        if finding.observed_at and limits.staleness_seconds > 0:
            observed = _parse_utc(finding.observed_at, field="observed_at")
            age = (moment - observed).total_seconds()
            if age > limits.staleness_seconds:
                continue
            if age < -60:
                # Far-future observations are treated as clock-skew failures.
                raise SelfImprovementError(
                    f"finding {finding.finding_key} observed_at is in the future"
                )
        admitted.append(finding)
    return tuple(admitted)


# ---------------------------------------------------------------------------
# Snapshot observations and analyzers
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SnapshotObservation:
    """Structured residual signals drawn from an identified DuckDB snapshot.

    Analyzers are pure functions over this observation; they never mutate
    plans, Markdown, or task status.
    """

    snapshot: IdentifiedSnapshot
    inventory_gaps: tuple[Mapping[str, Any], ...] = ()
    schema_rows: tuple[Mapping[str, Any], ...] = ()
    parity_receipts: tuple[Mapping[str, Any], ...] = ()
    performance_samples: tuple[Mapping[str, Any], ...] = ()
    blockers: tuple[Mapping[str, Any], ...] = ()
    coverage_rows: tuple[Mapping[str, Any], ...] = ()
    observed_at: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, IdentifiedSnapshot):
            raise SelfImprovementError("snapshot must be an IdentifiedSnapshot")
        if self.observed_at:
            moment = _parse_utc(self.observed_at, field="observed_at")
            object.__setattr__(self, "observed_at", normalize_timestamp(moment))
        else:
            object.__setattr__(
                self,
                "observed_at",
                normalize_timestamp(datetime.now(timezone.utc)),
            )
        object.__setattr__(self, "inventory_gaps", tuple(self.inventory_gaps or ()))
        object.__setattr__(self, "schema_rows", tuple(self.schema_rows or ()))
        object.__setattr__(
            self, "parity_receipts", tuple(self.parity_receipts or ())
        )
        object.__setattr__(
            self, "performance_samples", tuple(self.performance_samples or ())
        )
        object.__setattr__(self, "blockers", tuple(self.blockers or ()))
        object.__setattr__(self, "coverage_rows", tuple(self.coverage_rows or ()))


class ResidualAnalyzer(Protocol):
    """Pure analyzer callable bound to one :class:`AnalyzerKind`."""

    kind: AnalyzerKind

    def analyze(
        self, observation: SnapshotObservation, *, budget: AnalysisBudget
    ) -> tuple[ResidualFinding, ...]:
        """Return residual findings for *observation*, capped by *budget*."""


def _finding_from_row(
    *,
    analyzer: AnalyzerKind,
    subject: str,
    reason: str,
    severity: FindingSeverity,
    snapshot: IdentifiedSnapshot,
    observed_at: str,
    evidence: Mapping[str, Any] | None = None,
    path: str = "",
) -> ResidualFinding:
    evidence_digest = ""
    if evidence is not None:
        evidence_digest = content_identity(dict(evidence))
    return ResidualFinding(
        analyzer=analyzer,
        subject=subject,
        reason=reason,
        severity=severity,
        evidence_digest=evidence_digest,
        repository_id=snapshot.repository_id,
        repository_tree_id=snapshot.repository_tree_id,
        snapshot_id=snapshot.snapshot_id,
        snapshot_receipt_cid=snapshot.snapshot_receipt_cid,
        observed_at=observed_at,
        path=path or subject,
    )


def analyze_inventory(
    observation: SnapshotObservation, *, budget: AnalysisBudget
) -> tuple[ResidualFinding, ...]:
    """Inventory residual analyzer: unowned / undeclared producer paths."""

    findings: list[ResidualFinding] = []
    for row in observation.inventory_gaps:
        if not isinstance(row, Mapping):
            continue
        path = str(row.get("path") or row.get("subject") or "").strip()
        if not path:
            continue
        owned = row.get("owned")
        if owned is True:
            continue
        reason = str(row.get("reason") or "unowned_mutable_producer").strip()
        findings.append(
            _finding_from_row(
                analyzer=AnalyzerKind.INVENTORY,
                subject=path,
                reason=reason,
                severity=FindingSeverity.parse(
                    str(row.get("severity") or "high")
                ),
                snapshot=observation.snapshot,
                observed_at=observation.observed_at,
                evidence=row,
                path=path,
            )
        )
        if len(findings) >= budget.max_findings_per_analyzer:
            break
    return tuple(findings)


def analyze_schema(
    observation: SnapshotObservation, *, budget: AnalysisBudget
) -> tuple[ResidualFinding, ...]:
    """Schema residual analyzer: missing or mismatched schema checksums."""

    findings: list[ResidualFinding] = []
    expected = observation.snapshot.schema_checksum
    for row in observation.schema_rows:
        if not isinstance(row, Mapping):
            continue
        table = str(row.get("table") or row.get("subject") or "").strip()
        if not table:
            continue
        status = str(row.get("status") or "").strip().lower()
        actual = str(row.get("schema_checksum") or row.get("checksum") or "").strip()
        mismatch = status in {"mismatch", "missing", "drift"} or (
            expected and actual and actual != expected and status != "ok"
        )
        if status == "ok" and not mismatch:
            continue
        if not mismatch and status not in {"mismatch", "missing", "drift", ""}:
            # Unknown status without explicit failure — skip unless flagged.
            if row.get("ok") is True:
                continue
        if row.get("ok") is True and not mismatch:
            continue
        if not mismatch and row.get("ok") is not False and status not in {
            "mismatch",
            "missing",
            "drift",
        }:
            # Only emit when explicitly bad or checksum drifts from binding.
            if not (expected and actual and actual != expected):
                continue
        reason = str(row.get("reason") or "schema_checksum_mismatch").strip()
        findings.append(
            _finding_from_row(
                analyzer=AnalyzerKind.SCHEMA,
                subject=table,
                reason=reason,
                severity=FindingSeverity.parse(
                    str(row.get("severity") or "high")
                ),
                snapshot=observation.snapshot,
                observed_at=observation.observed_at,
                evidence=row,
                path=f"schema/{table}",
            )
        )
        if len(findings) >= budget.max_findings_per_analyzer:
            break
    return tuple(findings)


def analyze_parity(
    observation: SnapshotObservation, *, budget: AnalysisBudget
) -> tuple[ResidualFinding, ...]:
    """Parity residual analyzer: dual-authority disagreement receipts."""

    findings: list[ResidualFinding] = []
    for row in observation.parity_receipts:
        if not isinstance(row, Mapping):
            continue
        if row.get("agrees") is True or str(row.get("status") or "").lower() in {
            "ok",
            "agree",
            "matched",
            "parity",
        }:
            continue
        subject = str(
            row.get("domain")
            or row.get("subject")
            or row.get("table")
            or "parity"
        ).strip()
        reason = str(row.get("reason") or "parity_disagreement").strip()
        findings.append(
            _finding_from_row(
                analyzer=AnalyzerKind.PARITY,
                subject=subject,
                reason=reason,
                severity=FindingSeverity.parse(
                    str(row.get("severity") or "critical")
                ),
                snapshot=observation.snapshot,
                observed_at=observation.observed_at,
                evidence=row,
                path=f"parity/{subject}",
            )
        )
        if len(findings) >= budget.max_findings_per_analyzer:
            break
    return tuple(findings)


def analyze_performance(
    observation: SnapshotObservation, *, budget: AnalysisBudget
) -> tuple[ResidualFinding, ...]:
    """Performance residual analyzer: budget / SLO breaches."""

    findings: list[ResidualFinding] = []
    for row in observation.performance_samples:
        if not isinstance(row, Mapping):
            continue
        metric = str(row.get("metric") or row.get("subject") or "").strip()
        if not metric:
            continue
        breached = row.get("breached")
        if breached is False:
            continue
        value = row.get("value")
        limit = row.get("limit")
        if breached is None and value is not None and limit is not None:
            try:
                breached = float(value) > float(limit)
            except (TypeError, ValueError):
                breached = False
        if not breached:
            continue
        reason = str(row.get("reason") or "performance_budget_breach").strip()
        findings.append(
            _finding_from_row(
                analyzer=AnalyzerKind.PERFORMANCE,
                subject=metric,
                reason=reason,
                severity=FindingSeverity.parse(
                    str(row.get("severity") or "medium")
                ),
                snapshot=observation.snapshot,
                observed_at=observation.observed_at,
                evidence=row,
                path=f"performance/{metric}",
            )
        )
        if len(findings) >= budget.max_findings_per_analyzer:
            break
    return tuple(findings)


def analyze_blockers(
    observation: SnapshotObservation, *, budget: AnalysisBudget
) -> tuple[ResidualFinding, ...]:
    """Blocker residual analyzer: open blockers without resolved ownership."""

    findings: list[ResidualFinding] = []
    for row in observation.blockers:
        if not isinstance(row, Mapping):
            continue
        status = str(row.get("status") or "open").strip().lower()
        if status in {"resolved", "closed", "cleared", "waived"}:
            continue
        blocker_id = str(
            row.get("blocker_id") or row.get("subject") or row.get("id") or ""
        ).strip()
        if not blocker_id:
            continue
        linked = row.get("linked_task_id") or row.get("task_id")
        if linked and status == "tracked":
            continue
        reason = str(row.get("reason") or "open_blocker").strip()
        findings.append(
            _finding_from_row(
                analyzer=AnalyzerKind.BLOCKER,
                subject=blocker_id,
                reason=reason,
                severity=FindingSeverity.parse(
                    str(row.get("severity") or "high")
                ),
                snapshot=observation.snapshot,
                observed_at=observation.observed_at,
                evidence=row,
                path=f"blockers/{blocker_id}",
            )
        )
        if len(findings) >= budget.max_findings_per_analyzer:
            break
    return tuple(findings)


def analyze_coverage(
    observation: SnapshotObservation, *, budget: AnalysisBudget
) -> tuple[ResidualFinding, ...]:
    """Coverage residual analyzer: uncovered domains or acceptance criteria."""

    findings: list[ResidualFinding] = []
    for row in observation.coverage_rows:
        if not isinstance(row, Mapping):
            continue
        if row.get("covered") is True:
            continue
        subject = str(
            row.get("domain")
            or row.get("criterion")
            or row.get("subject")
            or ""
        ).strip()
        if not subject:
            continue
        ratio = row.get("coverage_ratio")
        if ratio is not None:
            try:
                if float(ratio) >= 1.0:
                    continue
            except (TypeError, ValueError):
                pass
        reason = str(row.get("reason") or "coverage_gap").strip()
        findings.append(
            _finding_from_row(
                analyzer=AnalyzerKind.COVERAGE,
                subject=subject,
                reason=reason,
                severity=FindingSeverity.parse(
                    str(row.get("severity") or "medium")
                ),
                snapshot=observation.snapshot,
                observed_at=observation.observed_at,
                evidence=row,
                path=f"coverage/{subject}",
            )
        )
        if len(findings) >= budget.max_findings_per_analyzer:
            break
    return tuple(findings)


_ANALYZER_DISPATCH: Final[
    Mapping[AnalyzerKind, Callable[[SnapshotObservation], Any]]
] = MappingProxyType(
    {
        AnalyzerKind.INVENTORY: analyze_inventory,
        AnalyzerKind.SCHEMA: analyze_schema,
        AnalyzerKind.PARITY: analyze_parity,
        AnalyzerKind.PERFORMANCE: analyze_performance,
        AnalyzerKind.BLOCKER: analyze_blockers,
        AnalyzerKind.COVERAGE: analyze_coverage,
    }
)


def run_analyzers(
    observation: SnapshotObservation,
    *,
    budget: AnalysisBudget | None = None,
    kinds: Sequence[AnalyzerKind | str] | None = None,
) -> tuple[ResidualFinding, ...]:
    """Run the selected residual analyzers against *observation*.

    Results are per-analyzer capped, then globally capped by
    :attr:`AnalysisBudget.max_total_findings`, then deduplicated.
    """

    limits = budget if budget is not None else AnalysisBudget()
    if limits.max_total_findings == 0 or limits.max_findings_per_analyzer == 0:
        return ()
    selected: tuple[AnalyzerKind, ...]
    if kinds is None:
        selected = ANALYZER_KINDS
    else:
        selected = tuple(AnalyzerKind.parse(item) for item in kinds)

    collected: list[ResidualFinding] = []
    for kind in selected:
        fn = _ANALYZER_DISPATCH[kind]
        batch = fn(observation, budget=limits)
        collected.extend(batch)
        if len(collected) >= limits.max_total_findings:
            break
    unique = deduplicate_residual_findings(collected)
    if limits.max_total_findings and len(unique) > limits.max_total_findings:
        unique = unique[: limits.max_total_findings]
    return unique


# ---------------------------------------------------------------------------
# Finding ledger (DuckDB-authority projection; hermetic memory backend)
# ---------------------------------------------------------------------------


class FindingLedger(Protocol):
    """Durable ledger of admitted finding keys (DuckDB authority surface)."""

    def has_finding(self, finding_key: str) -> bool:
        """Return True when *finding_key* was previously admitted."""

    def record_findings(
        self, findings: Sequence[ResidualFinding]
    ) -> Mapping[str, Any]:
        """Persist admitted finding keys; return a ledger receipt."""

    def recorded_keys(self) -> frozenset[str]:
        """Return the set of known finding keys."""


@dataclass
class MemoryFindingLedger:
    """Hermetic in-memory finding ledger used by tests and self-check.

    Models the DuckDB-authoritative finding admission table without I/O.
    """

    repository_id: str
    _keys: dict[str, Mapping[str, Any]] = field(default_factory=dict)
    records: list[Mapping[str, Any]] = field(default_factory=list)

    def has_finding(self, finding_key: str) -> bool:
        return finding_key in self._keys

    def record_findings(
        self, findings: Sequence[ResidualFinding]
    ) -> Mapping[str, Any]:
        admitted: list[str] = []
        for finding in findings:
            if finding.repository_id and finding.repository_id != self.repository_id:
                raise SelfImprovementError(
                    "ledger refuses cross-repository finding admission"
                )
            if finding.finding_key in self._keys:
                continue
            entry = MappingProxyType(
                {
                    "finding_key": finding.finding_key,
                    "analyzer": finding.analyzer.value,
                    "repository_id": finding.repository_id or self.repository_id,
                    "repository_tree_id": finding.repository_tree_id,
                    "snapshot_receipt_cid": finding.snapshot_receipt_cid,
                    "observed_at": finding.observed_at,
                }
            )
            self._keys[finding.finding_key] = entry
            self.records.append(entry)
            admitted.append(finding.finding_key)
        receipt = {
            "schema": "ipfs_datasets_py/duckdb-control/finding-ledger-receipt@1",
            "repository_id": self.repository_id,
            "admitted_count": len(admitted),
            "admitted_keys": admitted,
            "total_keys": len(self._keys),
            "authority_surface": AUTHORITY_SURFACE,
        }
        return MappingProxyType(dict(receipt))

    def recorded_keys(self) -> frozenset[str]:
        return frozenset(self._keys)


# ---------------------------------------------------------------------------
# Proposal construction and DQP-039 submission
# ---------------------------------------------------------------------------


def build_gap_proposals_from_residuals(
    findings: Sequence[ResidualFinding],
    *,
    snapshot: IdentifiedSnapshot,
    budget: AnalysisBudget | None = None,
    analyzer_id: str = "analyzer:self-improvement",
) -> tuple[GapProposal, ...]:
    """Convert residual findings into non-active DQP gap proposals.

    Each proposal binds *snapshot*'s repository tree and receipt identity.
    Findings from a different repository or tree are refused.
    """

    limits = budget if budget is not None else AnalysisBudget()
    if limits.max_proposals == 0 or limits.max_total_findings == 0:
        return ()

    for finding in findings:
        if finding.repository_id and finding.repository_id != snapshot.repository_id:
            raise SelfImprovementError(
                "cross-repository findings cannot share a proposal binding"
            )
        if (
            finding.repository_tree_id
            and finding.repository_tree_id != snapshot.repository_tree_id
        ):
            raise SelfImprovementError(
                "findings must bind the same repository tree as the snapshot"
            )
        if (
            finding.snapshot_receipt_cid
            and finding.snapshot_receipt_cid != snapshot.snapshot_receipt_cid
        ):
            raise SelfImprovementError(
                "findings must bind the same snapshot receipt identity"
            )

    unique = deduplicate_residual_findings(findings)
    if not unique:
        return ()

    # Cap before projection so proposal budgets stay consistent.
    capped = unique[: limits.max_total_findings]
    gaps = tuple(item.to_gap_finding() for item in capped)
    gaps = _dedupe_gap_findings(gaps)

    plan_root = snapshot.base_plan_root_cid or content_identity(
        {
            "repository_id": snapshot.repository_id,
            "repository_tree_id": snapshot.repository_tree_id,
            "snapshot_id": snapshot.snapshot_id,
        }
    )
    # inventory_snapshot_cid must be sha256:<64 hex> for GapProposal.
    inventory_snapshot_cid = content_identity(
        {
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_receipt_cid": snapshot.snapshot_receipt_cid,
            "repository_tree_id": snapshot.repository_tree_id,
            "binding_cid": snapshot.binding_cid,
        }
    )

    proposals = build_gap_proposals(
        gaps,
        repository_id=snapshot.repository_id,
        repository_tree_id=snapshot.repository_tree_id,
        inventory_snapshot_cid=inventory_snapshot_cid,
        base_plan_root_cid=plan_root,
        budget=limits.to_refinement_budget(),
        analyzer_id=analyzer_id,
        goal_prefix="DQK-G-SI",
        task_prefix="DQK-SI",
    )
    if limits.max_proposals and len(proposals) > limits.max_proposals:
        proposals = proposals[: limits.max_proposals]
    return proposals


def submit_residual_findings(
    api: CanonicalPlanRevisionAPI,
    findings: Sequence[ResidualFinding],
    *,
    snapshot: IdentifiedSnapshot,
    budget: AnalysisBudget | None = None,
    analyzer_id: str = "analyzer:self-improvement",
    ledger: FindingLedger | None = None,
    now: datetime | None = None,
) -> Mapping[str, Any]:
    """Submit deduplicated residual findings via DQP-039 plan-revision only.

    Never mutates task status, never refills Markdown objectives, and never
    activates proposals. Duplicate/stale findings are filtered before submit;
    admitted keys are recorded on *ledger* after a successful admission.
    """

    limits = budget if budget is not None else AnalysisBudget()
    active_ledger = ledger or MemoryFindingLedger(
        repository_id=snapshot.repository_id
    )
    admitted = filter_stale_and_duplicate_findings(
        findings, active_ledger, budget=limits, now=now
    )
    proposals = build_gap_proposals_from_residuals(
        admitted,
        snapshot=snapshot,
        budget=limits,
        analyzer_id=analyzer_id,
    )
    adapter = PlanRevisionAdapter(
        api=api,
        repository_id=snapshot.repository_id,
        analyzer_id=analyzer_id,
        budget=limits.to_refinement_budget(),
    )
    plan_root = snapshot.base_plan_root_cid or content_identity(
        {
            "repository_id": snapshot.repository_id,
            "repository_tree_id": snapshot.repository_tree_id,
            "snapshot_id": snapshot.snapshot_id,
        }
    )
    try:
        admission = adapter.submit(proposals, base_plan_root_cid=plan_root)
    except InventoryRefinementError as exc:
        raise SelfImprovementError(str(exc)) from exc

    # Record only after plan-revision admits the batch (no storm on failure).
    ledger_receipt = active_ledger.record_findings(admitted)
    return MappingProxyType(
        {
            **dict(admission),
            "loop_schema": LOOP_SCHEMA,
            "owner_task_id": OWNER_TASK_ID,
            "authority_surface": AUTHORITY_SURFACE,
            "markdown_refill": False,
            "status_mutation": False,
            "mutation_surface": "plan_revision_api",
            "finding_count_input": len(findings),
            "finding_count_admitted": len(admitted),
            "finding_count_suppressed": len(findings)
            - len(deduplicate_residual_findings(findings))
            + (
                len(deduplicate_residual_findings(findings)) - len(admitted)
            ),
            "repository_tree_id": snapshot.repository_tree_id,
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_receipt_cid": snapshot.snapshot_receipt_cid,
            "snapshot_binding_cid": snapshot.binding_cid,
            "ledger": dict(ledger_receipt),
            "admitted_finding_keys": [item.finding_key for item in admitted],
        }
    )


# ---------------------------------------------------------------------------
# Self-improvement loop
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LoopReceipt:
    """Deterministic receipt for one residual-analysis loop iteration."""

    schema: str
    owner_task_id: str
    repository_id: str
    repository_tree_id: str
    snapshot_id: str
    snapshot_receipt_cid: str
    snapshot_binding_cid: str
    analyzer_kinds: tuple[str, ...]
    finding_count_raw: int
    finding_count_admitted: int
    proposal_count: int
    proposal_ids: tuple[str, ...]
    admission_cid: str
    authority_surface: str
    markdown_refill: bool
    status_mutation: bool
    receipt_cid: str = ""

    def __post_init__(self) -> None:
        if self.schema != RECEIPT_SCHEMA:
            raise SelfImprovementError(
                f"loop receipt schema must be {RECEIPT_SCHEMA}"
            )
        if self.markdown_refill:
            raise SelfImprovementError(
                "loop receipt cannot claim markdown_refill authority"
            )
        if self.status_mutation:
            raise SelfImprovementError(
                "loop receipt cannot claim status_mutation"
            )
        if self.authority_surface != AUTHORITY_SURFACE:
            raise SelfImprovementError(
                f"authority_surface must be {AUTHORITY_SURFACE}"
            )
        if not self.receipt_cid:
            material = {
                key: value
                for key, value in self.to_dict().items()
                if key != "receipt_cid"
            }
            object.__setattr__(self, "receipt_cid", content_identity(material))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "owner_task_id": self.owner_task_id,
            "repository_id": self.repository_id,
            "repository_tree_id": self.repository_tree_id,
            "snapshot_id": self.snapshot_id,
            "snapshot_receipt_cid": self.snapshot_receipt_cid,
            "snapshot_binding_cid": self.snapshot_binding_cid,
            "analyzer_kinds": list(self.analyzer_kinds),
            "finding_count_raw": self.finding_count_raw,
            "finding_count_admitted": self.finding_count_admitted,
            "proposal_count": self.proposal_count,
            "proposal_ids": list(self.proposal_ids),
            "admission_cid": self.admission_cid,
            "authority_surface": self.authority_surface,
            "markdown_refill": self.markdown_refill,
            "status_mutation": self.status_mutation,
            "receipt_cid": self.receipt_cid
            or content_identity(
                {
                    "schema": self.schema,
                    "owner_task_id": self.owner_task_id,
                    "repository_id": self.repository_id,
                    "repository_tree_id": self.repository_tree_id,
                    "snapshot_receipt_cid": self.snapshot_receipt_cid,
                    "proposal_ids": list(self.proposal_ids),
                    "finding_count_admitted": self.finding_count_admitted,
                }
            ),
        }


@dataclass
class SelfImprovementLoop:
    """Orchestrates residual analysis and DQP-039 submission for one repository.

    The loop refuses Markdown objective refill and raw status mutation. Cross-
    repository work requires a separate loop instance with its own tree and
    receipt identity.
    """

    api: CanonicalPlanRevisionAPI
    repository_id: str
    ledger: FindingLedger | None = None
    budget: AnalysisBudget = field(default_factory=AnalysisBudget)
    analyzer_id: str = "analyzer:self-improvement"
    kinds: tuple[AnalyzerKind, ...] = ANALYZER_KINDS

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "repository_id",
            _require_text(self.repository_id, field="repository_id"),
        )
        if self.ledger is None:
            self.ledger = MemoryFindingLedger(repository_id=self.repository_id)
        elif getattr(self.ledger, "repository_id", self.repository_id) not in (
            self.repository_id,
            None,
        ):
            # MemoryFindingLedger binds repository_id; enforce match.
            ledger_repo = getattr(self.ledger, "repository_id", None)
            if ledger_repo and ledger_repo != self.repository_id:
                raise SelfImprovementError(
                    "ledger repository_id does not match loop repository_id"
                )
        parsed = tuple(AnalyzerKind.parse(item) for item in self.kinds)
        object.__setattr__(self, "kinds", parsed)

    def run(
        self,
        observation: SnapshotObservation,
        *,
        now: datetime | None = None,
    ) -> Mapping[str, Any]:
        """Analyze *observation* and submit non-active DQP proposals."""

        if observation.snapshot.repository_id != self.repository_id:
            raise SelfImprovementError(
                "observation repository_id does not match loop repository_id"
            )
        raw = run_analyzers(
            observation, budget=self.budget, kinds=self.kinds
        )
        submission = submit_residual_findings(
            self.api,
            raw,
            snapshot=observation.snapshot,
            budget=self.budget,
            analyzer_id=self.analyzer_id,
            ledger=self.ledger,
            now=now,
        )
        receipt = LoopReceipt(
            schema=RECEIPT_SCHEMA,
            owner_task_id=OWNER_TASK_ID,
            repository_id=self.repository_id,
            repository_tree_id=observation.snapshot.repository_tree_id,
            snapshot_id=observation.snapshot.snapshot_id,
            snapshot_receipt_cid=observation.snapshot.snapshot_receipt_cid,
            snapshot_binding_cid=observation.snapshot.binding_cid,
            analyzer_kinds=tuple(item.value for item in self.kinds),
            finding_count_raw=len(raw),
            finding_count_admitted=int(submission.get("finding_count_admitted") or 0),
            proposal_count=int(submission.get("proposal_count") or 0),
            proposal_ids=tuple(submission.get("proposal_ids") or ()),
            admission_cid=str(submission.get("admission_cid") or ""),
            authority_surface=AUTHORITY_SURFACE,
            markdown_refill=False,
            status_mutation=False,
        )
        return MappingProxyType(
            {
                **dict(submission),
                "loop_receipt": receipt.to_dict(),
                "findings_raw": [item.to_dict() for item in raw],
            }
        )

    def run_multi_repository(
        self,
        observations: Sequence[SnapshotObservation],
        *,
        apis: Mapping[str, CanonicalPlanRevisionAPI],
        now: datetime | None = None,
    ) -> Mapping[str, Any]:
        """Run residual analysis across repositories with separate bindings.

        Each observation must have a distinct ``(repository_id, tree_id,
        snapshot_receipt_cid)`` triple. Trees and receipts must not be shared
        across repositories.
        """

        if not observations:
            return MappingProxyType(
                {
                    "schema": LOOP_SCHEMA,
                    "repository_count": 0,
                    "results": [],
                    "authority_surface": AUTHORITY_SURFACE,
                    "markdown_refill": False,
                }
            )

        trees_by_repo: dict[str, set[str]] = {}
        receipts_by_repo: dict[str, set[str]] = {}
        tree_owners: dict[str, str] = {}
        receipt_owners: dict[str, str] = {}

        results: list[Mapping[str, Any]] = []
        for observation in observations:
            snap = observation.snapshot
            repo = snap.repository_id
            tree = snap.repository_tree_id
            receipt = snap.snapshot_receipt_cid

            if tree in tree_owners and tree_owners[tree] != repo:
                raise SelfImprovementError(
                    "cross-repository proposals cannot share an immutable Git tree"
                )
            if receipt in receipt_owners and receipt_owners[receipt] != repo:
                raise SelfImprovementError(
                    "cross-repository proposals cannot share a snapshot receipt identity"
                )
            tree_owners[tree] = repo
            receipt_owners[receipt] = repo
            trees_by_repo.setdefault(repo, set()).add(tree)
            receipts_by_repo.setdefault(repo, set()).add(receipt)

            api = apis.get(repo)
            if api is None:
                raise SelfImprovementError(
                    f"no plan-revision API registered for repository {repo!r}"
                )
            loop = SelfImprovementLoop(
                api=api,
                repository_id=repo,
                ledger=MemoryFindingLedger(repository_id=repo)
                if self.ledger is None
                or getattr(self.ledger, "repository_id", None) != repo
                else self.ledger,
                budget=self.budget,
                analyzer_id=self.analyzer_id,
                kinds=self.kinds,
            )
            results.append(loop.run(observation, now=now))

        return MappingProxyType(
            {
                "schema": LOOP_SCHEMA,
                "repository_count": len({item.snapshot.repository_id for item in observations}),
                "results": list(results),
                "authority_surface": AUTHORITY_SURFACE,
                "markdown_refill": False,
                "status_mutation": False,
                "trees_by_repository": {
                    repo: sorted(trees) for repo, trees in trees_by_repo.items()
                },
                "receipts_by_repository": {
                    repo: sorted(receipts)
                    for repo, receipts in receipts_by_repo.items()
                },
            }
        )

    def refill_markdown_objectives(self, *_args: Any, **_kwargs: Any) -> None:
        """Markdown objective refill is not an authority surface."""

        raise MarkdownRefillError(
            "self-improvement loop refuses Markdown objective refill; "
            f"authority is {AUTHORITY_SURFACE}"
        )

    def mutate_status(self, *_args: Any, **_kwargs: Any) -> None:
        raise SelfImprovementError(
            "self-improvement loop refuses raw status mutation; "
            "use the DQP plan-revision API"
        )

    def approve(self, *_args: Any, **_kwargs: Any) -> None:
        raise SelfImprovementError(
            "analyzer cannot self-approve residual findings; "
            f"approval is reserved for {APPROVAL_GATE_TASK_ID}"
        )

    def activate_proposals(self, *_args: Any, **_kwargs: Any) -> None:
        raise SelfImprovementError(
            f"activation is reserved for {ROLLOVER_GATE_TASK_ID} rollover"
        )


# ---------------------------------------------------------------------------
# Self-check and CLI
# ---------------------------------------------------------------------------


def _demo_snapshot(
    *,
    repository_id: str = "repository:self-check",
    tree_id: str = "a" * 40,
    receipt_suffix: str = "b",
) -> IdentifiedSnapshot:
    return IdentifiedSnapshot(
        repository_id=repository_id,
        repository_tree_id=tree_id,
        snapshot_id="sha256:" + "c" * 64,
        snapshot_receipt_cid="sha256:" + receipt_suffix * 64,
        store_generation=1,
        schema_checksum="sha256:" + "d" * 64,
        base_plan_root_cid="sha256:" + "e" * 64,
    )


def self_check() -> dict[str, Any]:
    """Hermetic acceptance self-check for DQK-054."""

    now = datetime(2030, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    snapshot = _demo_snapshot()
    observation = SnapshotObservation(
        snapshot=snapshot,
        observed_at=normalize_timestamp(now),
        inventory_gaps=(
            {"path": "workspace/orphan/state.json", "owned": False},
            {"path": "workspace/orphan/state.json", "owned": False},  # duplicate
        ),
        schema_rows=(
            {
                "table": "tasks",
                "status": "mismatch",
                "schema_checksum": "sha256:" + "f" * 64,
            },
        ),
        parity_receipts=(
            {"domain": "graph", "agrees": False, "reason": "row_count_mismatch"},
            {"domain": "vector", "agrees": True},
        ),
        performance_samples=(
            {"metric": "query_p99_ms", "value": 900, "limit": 250, "breached": True},
        ),
        blockers=(
            {"blocker_id": "BLK-1", "status": "open"},
            {"blocker_id": "BLK-2", "status": "resolved"},
        ),
        coverage_rows=(
            {"domain": "wallet", "covered": False, "coverage_ratio": 0.4},
            {"domain": "control", "covered": True, "coverage_ratio": 1.0},
        ),
    )

    api = MemoryPlanRevisionAPI(repository_id=snapshot.repository_id)
    ledger = MemoryFindingLedger(repository_id=snapshot.repository_id)
    loop = SelfImprovementLoop(
        api=api,
        repository_id=snapshot.repository_id,
        ledger=ledger,
        budget=AnalysisBudget(
            max_findings_per_analyzer=16,
            max_total_findings=64,
            max_proposals=16,
            max_model_calls=0,
            staleness_seconds=86_400,
        ),
    )

    # First pass admits findings through plan-revision only.
    first = loop.run(observation, now=now)
    if first.get("mutation_surface") != "plan_revision_api":
        raise SelfImprovementError("self-check: mutation_surface must be plan_revision_api")
    if first.get("status_mutation") is not False:
        raise SelfImprovementError("self-check: status_mutation must be false")
    if first.get("markdown_refill") is not False:
        raise SelfImprovementError("self-check: markdown_refill must be false")
    if first.get("authority_surface") != AUTHORITY_SURFACE:
        raise SelfImprovementError("self-check: authority_surface mismatch")
    if int(first.get("finding_count_admitted") or 0) < 1:
        raise SelfImprovementError("self-check: expected admitted findings")
    if int(first.get("proposal_count") or 0) < 1:
        raise SelfImprovementError("self-check: expected non-active proposals")
    if not api.submitted:
        raise SelfImprovementError("self-check: plan-revision API not invoked")
    for request in api.submitted:
        if not isinstance(request, PlanRevisionRequest):
            raise SelfImprovementError("self-check: unexpected request type")
        if request.activate:
            raise SelfImprovementError("self-check: activate must be false")
        for proposal in request.proposals:
            if proposal.status is not ProposalStatus.NON_ACTIVE:
                raise SelfImprovementError("self-check: proposals must be non_active")
            if proposal.repository_tree_id != snapshot.repository_tree_id:
                raise SelfImprovementError("self-check: tree binding mismatch")

    # Second pass with identical observation must not storm.
    prior_count = len(api.submitted)
    prior_keys = len(ledger.recorded_keys())
    second = loop.run(observation, now=now)
    if int(second.get("finding_count_admitted") or 0) != 0:
        raise SelfImprovementError(
            "self-check: duplicate findings created a task storm"
        )
    if len(ledger.recorded_keys()) != prior_keys:
        raise SelfImprovementError(
            "self-check: ledger grew on duplicate residual pass"
        )
    # Empty proposal batch may still submit a zero-count admission; proposals
    # themselves must not grow.
    new_proposals = sum(
        len(req.proposals) for req in api.submitted[prior_count:]
    )
    if new_proposals != 0:
        raise SelfImprovementError(
            "self-check: duplicate pass submitted new proposals"
        )

    # Stale findings are suppressed.
    stale_obs = SnapshotObservation(
        snapshot=snapshot,
        observed_at=normalize_timestamp(now - timedelta(days=3)),
        inventory_gaps=(
            {"path": "workspace/stale/only.json", "owned": False},
        ),
    )
    # Fresh ledger so only staleness is under test.
    stale_ledger = MemoryFindingLedger(repository_id=snapshot.repository_id)
    stale_loop = SelfImprovementLoop(
        api=MemoryPlanRevisionAPI(repository_id=snapshot.repository_id),
        repository_id=snapshot.repository_id,
        ledger=stale_ledger,
        budget=AnalysisBudget(staleness_seconds=3_600),
    )
    stale_result = stale_loop.run(stale_obs, now=now)
    if int(stale_result.get("finding_count_admitted") or 0) != 0:
        raise SelfImprovementError("self-check: stale findings were admitted")

    # Markdown refill / status mutation / self-approval / activation refused.
    refused: list[str] = []
    for name, action in (
        ("markdown_refill", lambda: loop.refill_markdown_objectives()),
        ("status_mutation", lambda: loop.mutate_status(task_id="X", status="done")),
        ("self_approval", lambda: loop.approve()),
        ("activation", lambda: loop.activate_proposals()),
    ):
        try:
            action()
        except (SelfImprovementError, MarkdownRefillError, InventoryRefinementError):
            refused.append(name)
        else:
            raise SelfImprovementError(f"self-check failed to refuse {name}")

    # Cross-repository bindings: separate trees and receipts required.
    foreign_snap = _demo_snapshot(
        repository_id="repository:foreign",
        tree_id="1" * 40,
        receipt_suffix="2",
    )
    foreign_obs = SnapshotObservation(
        snapshot=foreign_snap,
        observed_at=normalize_timestamp(now),
        inventory_gaps=({"path": "foreign/gap.json", "owned": False},),
    )
    multi = loop.run_multi_repository(
        (observation, foreign_obs),
        apis={
            snapshot.repository_id: api,
            foreign_snap.repository_id: MemoryPlanRevisionAPI(
                repository_id=foreign_snap.repository_id
            ),
        },
        now=now,
    )
    if int(multi.get("repository_count") or 0) != 2:
        raise SelfImprovementError("self-check: expected two repositories")
    trees = multi.get("trees_by_repository") or {}
    if snapshot.repository_tree_id in (trees.get(foreign_snap.repository_id) or []):
        raise SelfImprovementError("self-check: trees must not cross repositories")

    # Shared tree across repositories must fail closed.
    shared_tree_foreign = IdentifiedSnapshot(
        repository_id="repository:foreign-shared",
        repository_tree_id=snapshot.repository_tree_id,  # shared — forbidden
        snapshot_id="sha256:" + "9" * 64,
        snapshot_receipt_cid="sha256:" + "8" * 64,
        base_plan_root_cid="sha256:" + "7" * 64,
    )
    try:
        loop.run_multi_repository(
            (
                observation,
                SnapshotObservation(
                    snapshot=shared_tree_foreign,
                    observed_at=normalize_timestamp(now),
                    inventory_gaps=({"path": "x.json", "owned": False},),
                ),
            ),
            apis={
                snapshot.repository_id: api,
                shared_tree_foreign.repository_id: MemoryPlanRevisionAPI(
                    repository_id=shared_tree_foreign.repository_id
                ),
            },
            now=now,
        )
    except SelfImprovementError:
        refused.append("shared_tree")
    else:
        raise SelfImprovementError(
            "self-check failed to refuse shared Git tree across repositories"
        )

    # All six analyzer kinds must be registered.
    if set(item.value for item in ANALYZER_KINDS) != set(DEFAULT_ANALYZER_IDS):
        raise SelfImprovementError("self-check: analyzer kind set mismatch")

    return {
        "ok": True,
        "schema": LOOP_SCHEMA,
        "receipt_schema": RECEIPT_SCHEMA,
        "finding_schema": FINDING_SCHEMA,
        "program_id": PROGRAM_ID,
        "owner_task_id": OWNER_TASK_ID,
        "approval_gate_task_id": APPROVAL_GATE_TASK_ID,
        "rollover_gate_task_id": ROLLOVER_GATE_TASK_ID,
        "authority_surface": AUTHORITY_SURFACE,
        "markdown_refill": False,
        "status_mutation": False,
        "mutation_surface": "plan_revision_api",
        "analyzer_kinds": [item.value for item in ANALYZER_KINDS],
        "first_admitted": int(first.get("finding_count_admitted") or 0),
        "second_admitted": int(second.get("finding_count_admitted") or 0),
        "stale_admitted": int(stale_result.get("finding_count_admitted") or 0),
        "proposal_count": int(first.get("proposal_count") or 0),
        "refused_cases": refused,
        "cross_repository_count": int(multi.get("repository_count") or 0),
        "loop_receipt_cid": (first.get("loop_receipt") or {}).get("receipt_cid"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ipfs_datasets_py.duckdb_control.self_improvement",
        description=(
            "Database-native residual analysis and self-improvement loop (DQK-054)."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser(
        "check", help="Run hermetic acceptance self-check and print JSON."
    )
    check.add_argument(
        "--json",
        action="store_true",
        default=True,
        help="Emit JSON (default).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "check":
        try:
            report = self_check()
        except Exception as exc:  # noqa: BLE001 — CLI boundary
            payload = {"ok": False, "error": str(exc)}
            print(json.dumps(payload, sort_keys=True, indent=2))
            return 1
        print(json.dumps(report, sort_keys=True, indent=2))
        return 0 if report.get("ok") else 1
    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
