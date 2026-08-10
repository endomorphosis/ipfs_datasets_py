"""Inventory-to-plan refinement and DQP-039 plan-revision adapter (DQK-080).

Compares a producer inventory snapshot with a declared task/effect graph,
emits bounded/deduplicated exact-tree gap proposals through DQP's canonical
plan-revision API (never via raw status mutation), and provides a
cryptographically verified approval-receipt command used by the DQK-081 gate.

Design invariants (acceptance):

* Proposals bind the exact repository tree and inventory snapshot and remain
  **non-active** until a later DQK-083 generation rollover activates them.
* Budgets cap generated goals, tasks, depth, retries, and model calls.
* No analyzer can self-approve or directly mutate another repository's plan.
* The verifier rejects unsigned, stale, mismatched, incomplete, or
  self-approved refinement receipts.

Importing this module is inert: no filesystem, network, or database I/O until
an explicit compare / submit / verify / CLI entry point is invoked.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import (
    Any,
    Final,
    Iterable,
    Iterator,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    TextIO,
)

from ipfs_datasets_py.duckdb_control.contracts import (
    ContractError,
    canonical_json_bytes,
    content_identity,
    normalize_timestamp,
    parse_source_digest,
)
from ipfs_datasets_py.duckdb_control.inventory import (
    ArtifactKind,
    InventoryRecord,
    ProposedAuthority,
    inventory_snapshot_digest,
    normalize_rel_path,
)

__all__ = [
    "APPROVAL_COMMAND",
    "DEFAULT_BUDGET",
    "DQK_083_ROLLOVER_GATE",
    "GAP_PROPOSAL_SCHEMA",
    "PLAN_REVISION_API_SCHEMA",
    "PROGRAM_ID",
    "PROPOSAL_STATUS_PROPOSED",
    "RECEIPT_SCHEMA",
    "REFINEMENT_SCHEMA",
    "SIGNATURE_ALGORITHM",
    "TASK_ID",
    "VERIFICATION_SCHEMA",
    "BudgetExceededError",
    "DqpPlanRevisionAPI",
    "GapFinding",
    "GapProposal",
    "GapProposalStatus",
    "InventoryRefinementError",
    "MemoryPlanRevisionAPI",
    "PlanRevisionAdapter",
    "PlanRevisionSubmission",
    "RefinementBudget",
    "RefinementReceipt",
    "SelfApprovalError",
    "TaskEffect",
    "TaskEffectGraph",
    "VerificationError",
    "build_parser",
    "build_refinement_receipt",
    "compare_inventory_to_effect_graph",
    "compute_receipt_cid",
    "compute_signature",
    "deduplicate_findings",
    "emit_gap_proposals",
    "inventory_snapshot_cid",
    "main",
    "proposal_content_id",
    "require_non_active_until_rollover",
    "sign_receipt_payload",
    "unsigned_preimage",
    "verify_refinement_receipt",
    "verify_signature",
]


# ---------------------------------------------------------------------------
# Schemas / constants
# ---------------------------------------------------------------------------

REFINEMENT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control/inventory-refinement@1"
)
GAP_PROPOSAL_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control/inventory-gap-proposal@1"
)
RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control/inventory-refinement-receipt@1"
)
VERIFICATION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control/inventory-refinement-verification@1"
)
PLAN_REVISION_API_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control/dqp-plan-revision-api@1"
)

PROGRAM_ID: Final[str] = "ipfs-datasets-duckdb-quack-v1"
TASK_ID: Final[str] = "DQK-080"
APPROVAL_COMMAND: Final[str] = "verify-refinement-receipt"
DQK_083_ROLLOVER_GATE: Final[str] = "DQK-083"
PROPOSAL_STATUS_PROPOSED: Final[str] = "proposed"
SIGNATURE_ALGORITHM: Final[str] = "content-bound-sha256@1"

# Kinds that must be dependency-ordered task effects or explicit waivers
# before authority promotion (mutable / residual producers).
_GAP_KINDS: Final[frozenset[ArtifactKind]] = frozenset(
    {
        ArtifactKind.MUTABLE_STATE,
        ArtifactKind.UNSAFE_SERIALIZATION,
        ArtifactKind.UNKNOWN,
    }
)
_GAP_AUTHORITIES: Final[frozenset[ProposedAuthority]] = frozenset(
    {
        ProposedAuthority.CONTROL_DUCKDB,
        ProposedAuthority.DOMAIN_DUCKDB,
        ProposedAuthority.ONE_TIME_IMPORT,
        ProposedAuthority.QUARANTINE,
        ProposedAuthority.RETAIN_FILE,
    }
)

_UNSIGNED_EXCLUDED: Final[frozenset[str]] = frozenset(
    {"signature", "receipt_cid"}
)
_MAX_RECEIPT_BYTES: Final[int] = 2 * 1024 * 1024
_MAX_FIELD_BYTES: Final[int] = 4096
_MAX_FINDINGS: Final[int] = 10_000
_ISSUED_AT_FUTURE_SKEW_SECONDS: Final[int] = 60
_SHA256_DIGEST_RE = __import__("re").compile(r"^sha256:[0-9a-f]{64}$")
_CONTROL_CHARS: Final[frozenset[str]] = frozenset(("\0", "\n", "\r"))

_RECEIPT_REQUIRED_STRING_FIELDS: Final[tuple[str, ...]] = (
    "schema",
    "program_id",
    "task_id",
    "repository_id",
    "repository_tree_id",
    "inventory_snapshot_cid",
    "base_plan_root_cid",
    "accepted_plan_root_cid",
    "analyzer_id",
    "reviewer_id",
    "authorization_cid",
    "decision_cid",
    "decision",
    "issued_at",
    "expires_at",
    "signature_algorithm",
    "signature",
    "receipt_cid",
)

_RECEIPT_KEYS: Final[frozenset[str]] = frozenset(
    {
        *_RECEIPT_REQUIRED_STRING_FIELDS,
        "accepted",
        "proposal_ids",
        "unresolved_gap_count",
        "generation_changed",
        "generation_rollover_receipt_cid",
        "active_plan_root_cid",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class InventoryRefinementError(ValueError):
    """Raised when refinement inputs, budgets, or authority rules fail closed."""


class BudgetExceededError(InventoryRefinementError):
    """Raised when a refinement budget would be exceeded."""


class SelfApprovalError(InventoryRefinementError):
    """Raised when an analyzer attempts to approve its own proposals."""


class VerificationError(RuntimeError):
    """Raised when a refinement receipt fails closed verification."""


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RefinementBudget:
    """Hard caps on refinement generation cost.

    Every dimension is independently enforced. Zero is allowed only for
    ``max_model_calls`` (pure symbolic refinement); other dimensions must be
    strictly positive so the adapter can emit at least one bounded unit of work.
    """

    max_goals: int = 32
    max_tasks: int = 256
    max_depth: int = 8
    max_retries: int = 3
    max_model_calls: int = 0

    def __post_init__(self) -> None:
        for name in ("max_goals", "max_tasks", "max_depth", "max_retries"):
            value = int(getattr(self, name))
            if value < 1:
                raise InventoryRefinementError(
                    f"{name} must be a positive integer, got {value}"
                )
            if value > 100_000:
                raise InventoryRefinementError(
                    f"{name} exceeds the hard safety bound of 100000"
                )
            object.__setattr__(self, name, value)
        model_calls = int(self.max_model_calls)
        if model_calls < 0:
            raise InventoryRefinementError(
                f"max_model_calls must be non-negative, got {model_calls}"
            )
        if model_calls > 10_000:
            raise InventoryRefinementError(
                "max_model_calls exceeds the hard safety bound of 10000"
            )
        object.__setattr__(self, "max_model_calls", model_calls)

    def to_dict(self) -> dict[str, int]:
        return {
            "max_depth": self.max_depth,
            "max_goals": self.max_goals,
            "max_model_calls": self.max_model_calls,
            "max_retries": self.max_retries,
            "max_tasks": self.max_tasks,
        }


DEFAULT_BUDGET: Final[RefinementBudget] = RefinementBudget()


# ---------------------------------------------------------------------------
# Effect graph
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TaskEffect:
    """One declared path/producer effect owned by a task in the plan graph."""

    task_id: str
    path: str
    effect_kind: str = "owns_producer"
    producer: str = ""
    goal_id: str = ""
    depth: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise InventoryRefinementError("task_id must be nonempty text")
        path = normalize_rel_path(self.path)
        if not path:
            raise InventoryRefinementError("effect path must be nonempty")
        object.__setattr__(self, "task_id", self.task_id.strip())
        object.__setattr__(self, "path", path)
        object.__setattr__(
            self, "effect_kind", str(self.effect_kind or "owns_producer").strip()
        )
        object.__setattr__(self, "producer", str(self.producer or "").strip())
        object.__setattr__(self, "goal_id", str(self.goal_id or "").strip())
        depth = int(self.depth)
        if depth < 0:
            raise InventoryRefinementError("effect depth must be non-negative")
        object.__setattr__(self, "depth", depth)

    def covers(self, inventory_path: str) -> bool:
        """Return True when this effect owns *inventory_path* exactly or as prefix."""
        target = normalize_rel_path(inventory_path)
        if not target:
            return False
        if self.path == target:
            return True
        prefix = self.path.rstrip("/") + "/"
        return target.startswith(prefix)

    def to_dict(self) -> dict[str, Any]:
        return {
            "depth": self.depth,
            "effect_kind": self.effect_kind,
            "goal_id": self.goal_id,
            "path": self.path,
            "producer": self.producer,
            "task_id": self.task_id,
        }


@dataclass(frozen=True, slots=True)
class TaskEffectGraph:
    """Declared task/effect population bound to one repository plan.

    The graph is repository-scoped: adapters refuse to apply it against a
    different ``repository_id``.
    """

    repository_id: str
    repository_tree_id: str
    plan_root_cid: str
    effects: tuple[TaskEffect, ...] = ()
    goal_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.repository_id, str) or not self.repository_id.strip():
            raise InventoryRefinementError("repository_id must be nonempty")
        if (
            not isinstance(self.repository_tree_id, str)
            or not self.repository_tree_id.strip()
        ):
            raise InventoryRefinementError("repository_tree_id must be nonempty")
        if not isinstance(self.plan_root_cid, str) or not self.plan_root_cid.strip():
            raise InventoryRefinementError("plan_root_cid must be nonempty")
        object.__setattr__(self, "repository_id", self.repository_id.strip())
        object.__setattr__(
            self, "repository_tree_id", self.repository_tree_id.strip()
        )
        object.__setattr__(self, "plan_root_cid", self.plan_root_cid.strip())
        effects = tuple(self.effects)
        object.__setattr__(self, "effects", effects)
        if self.goal_ids:
            goals = tuple(sorted({str(g).strip() for g in self.goal_ids if str(g).strip()}))
        else:
            goals = tuple(
                sorted({e.goal_id for e in effects if e.goal_id})
            )
        object.__setattr__(self, "goal_ids", goals)

    def covering_effects(self, path: str) -> tuple[TaskEffect, ...]:
        return tuple(effect for effect in self.effects if effect.covers(path))

    def to_dict(self) -> dict[str, Any]:
        return {
            "effects": [effect.to_dict() for effect in self.effects],
            "goal_ids": list(self.goal_ids),
            "plan_root_cid": self.plan_root_cid,
            "repository_id": self.repository_id,
            "repository_tree_id": self.repository_tree_id,
        }

    @property
    def content_id(self) -> str:
        return content_identity(self.to_dict())


# ---------------------------------------------------------------------------
# Findings and proposals
# ---------------------------------------------------------------------------


class GapProposalStatus(str, Enum):
    """Lifecycle of a gap proposal.

    Emitted proposals are always :attr:`PROPOSED` (non-active). Activation is
    exclusively owned by DQK-083 generation rollover after independent approval.
    """

    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    # Active is intentionally NOT assignable by this module.
    ACTIVE = "active"


@dataclass(frozen=True, slots=True)
class GapFinding:
    """One inventory path not covered by the declared task/effect graph."""

    path: str
    kind: ArtifactKind
    producer: str
    consumer: str
    proposed_authority: ProposedAuthority
    digest: str
    reason: str = "unowned_mutable_producer"

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", normalize_rel_path(self.path))
        if not self.path:
            raise InventoryRefinementError("finding path must be nonempty")
        if not self.producer:
            raise InventoryRefinementError("finding producer must be nonempty")
        object.__setattr__(self, "kind", ArtifactKind.parse(self.kind))
        object.__setattr__(
            self,
            "proposed_authority",
            ProposedAuthority.parse(self.proposed_authority),
        )
        digest = str(self.digest).strip().lower()
        if digest.startswith("sha256:"):
            digest = digest[7:]
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise InventoryRefinementError(
                f"finding digest must be sha256 hex, got {self.digest!r}"
            )
        object.__setattr__(self, "digest", digest)

    @property
    def dedupe_key(self) -> str:
        """Stable identity for deduplication (path + content digest)."""
        return f"{self.path}\0{self.digest}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "consumer": self.consumer,
            "digest": self.digest,
            "kind": self.kind.value,
            "path": self.path,
            "producer": self.producer,
            "proposed_authority": self.proposed_authority.value,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class GapProposal:
    """Exact-tree, non-active plan-revision proposal for one or more gaps.

    Proposals never become active from this module. ``active`` is always False
    and ``status`` is always ``proposed`` on emission; DQK-083 rollover is the
    only path that may activate an accepted revision.
    """

    proposal_id: str
    repository_id: str
    repository_tree_id: str
    inventory_snapshot_cid: str
    base_plan_root_cid: str
    analyzer_id: str
    findings: tuple[GapFinding, ...]
    proposed_goal_ids: tuple[str, ...]
    proposed_task_ids: tuple[str, ...]
    budget: RefinementBudget
    depth: int = 1
    status: GapProposalStatus = GapProposalStatus.PROPOSED
    active: bool = False
    activation_gate: str = DQK_083_ROLLOVER_GATE
    schema: str = GAP_PROPOSAL_SCHEMA

    def __post_init__(self) -> None:
        if self.active is not False:
            raise InventoryRefinementError(
                "gap proposals must remain non-active until DQK-083 rollover"
            )
        if self.status is GapProposalStatus.ACTIVE:
            raise InventoryRefinementError(
                "proposals cannot be emitted with active status; "
                "DQK-083 rollover owns activation"
            )
        if self.activation_gate != DQK_083_ROLLOVER_GATE:
            raise InventoryRefinementError(
                f"activation_gate must be {DQK_083_ROLLOVER_GATE}, "
                f"got {self.activation_gate!r}"
            )
        if not self.proposal_id or not self.repository_id:
            raise InventoryRefinementError(
                "proposal_id and repository_id are required"
            )
        if not self.repository_tree_id or not self.inventory_snapshot_cid:
            raise InventoryRefinementError(
                "proposals must bind repository_tree_id and inventory_snapshot_cid"
            )
        if not self.base_plan_root_cid:
            raise InventoryRefinementError("proposals must bind base_plan_root_cid")
        if not self.analyzer_id:
            raise InventoryRefinementError("analyzer_id is required")
        if not self.findings:
            raise InventoryRefinementError("proposal must include at least one finding")
        depth = int(self.depth)
        if depth < 1:
            raise InventoryRefinementError("proposal depth must be >= 1")
        object.__setattr__(self, "depth", depth)
        object.__setattr__(self, "findings", tuple(self.findings))
        object.__setattr__(
            self, "proposed_goal_ids", tuple(self.proposed_goal_ids)
        )
        object.__setattr__(
            self, "proposed_task_ids", tuple(self.proposed_task_ids)
        )
        object.__setattr__(self, "status", GapProposalStatus(self.status))
        object.__setattr__(self, "active", False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "activation_gate": self.activation_gate,
            "active": False,
            "analyzer_id": self.analyzer_id,
            "base_plan_root_cid": self.base_plan_root_cid,
            "budget": self.budget.to_dict(),
            "depth": self.depth,
            "findings": [finding.to_dict() for finding in self.findings],
            "inventory_snapshot_cid": self.inventory_snapshot_cid,
            "proposal_id": self.proposal_id,
            "proposed_goal_ids": list(self.proposed_goal_ids),
            "proposed_task_ids": list(self.proposed_task_ids),
            "repository_id": self.repository_id,
            "repository_tree_id": self.repository_tree_id,
            "schema": self.schema,
            "status": self.status.value,
        }

    @property
    def content_id(self) -> str:
        return proposal_content_id(self)


def proposal_content_id(proposal: GapProposal | Mapping[str, Any]) -> str:
    """Return content identity of a proposal excluding mutable status fields."""
    if isinstance(proposal, GapProposal):
        payload = proposal.to_dict()
    else:
        payload = dict(proposal)
    # Identity excludes status so re-serialisation after approval does not
    # rewrite the proposal content binding used in receipts.
    payload = {key: value for key, value in payload.items() if key != "status"}
    return content_identity(payload)


def require_non_active_until_rollover(proposal: GapProposal | Mapping[str, Any]) -> None:
    """Fail closed if a proposal claims activity before DQK-083 rollover."""
    if isinstance(proposal, GapProposal):
        active = proposal.active
        status = proposal.status.value
        gate = proposal.activation_gate
    else:
        active = proposal.get("active")
        status = str(proposal.get("status") or "")
        gate = str(proposal.get("activation_gate") or "")
    if active is True or status == GapProposalStatus.ACTIVE.value:
        raise InventoryRefinementError(
            "proposals remain non-active until DQK-083 rollover"
        )
    if gate != DQK_083_ROLLOVER_GATE:
        raise InventoryRefinementError(
            f"activation is owned exclusively by {DQK_083_ROLLOVER_GATE}"
        )


# ---------------------------------------------------------------------------
# Comparison + emission
# ---------------------------------------------------------------------------


def inventory_snapshot_cid(
    records: Iterable[InventoryRecord],
    *,
    repository_tree_id: str,
) -> str:
    """Bind an inventory stream to a repository tree as a content CID."""
    digest = inventory_snapshot_digest(records)
    material = {
        "inventory_digest": f"sha256:{digest}",
        "repository_tree_id": str(repository_tree_id).strip(),
        "schema": REFINEMENT_SCHEMA,
    }
    return content_identity(material)


def _requires_coverage(record: InventoryRecord) -> bool:
    """Return True when a record must be an effect or an explicit waiver."""
    if record.kind in _GAP_KINDS:
        return True
    if record.proposed_authority in _GAP_AUTHORITIES and record.kind not in (
        ArtifactKind.AUTHORED_DOCUMENTATION,
        ArtifactKind.DERIVED_EXPORT,
        ArtifactKind.IMMUTABLE_EVIDENCE,
    ):
        return True
    return False


def compare_inventory_to_effect_graph(
    records: Iterable[InventoryRecord],
    graph: TaskEffectGraph,
    *,
    budget: RefinementBudget = DEFAULT_BUDGET,
) -> tuple[GapFinding, ...]:
    """Diff inventory producers against the declared task/effect graph.

    Returns deduplicated, path-sorted findings for uncovered mutable/residual
    producers. Honours ``budget.max_tasks`` as the hard ceiling on findings
    retained for proposal emission (additional findings raise
    :class:`BudgetExceededError` rather than silently truncating).
    """
    findings: list[GapFinding] = []
    seen: set[str] = set()
    for record in records:
        if not _requires_coverage(record):
            continue
        covered = graph.covering_effects(record.path)
        if covered:
            continue
        finding = GapFinding(
            path=record.path,
            kind=record.kind,
            producer=record.producer,
            consumer=record.consumer,
            proposed_authority=record.proposed_authority,
            digest=record.digest,
            reason="unowned_mutable_producer",
        )
        key = finding.dedupe_key
        if key in seen:
            continue
        seen.add(key)
        if len(findings) >= budget.max_tasks:
            raise BudgetExceededError(
                f"gap findings exceed max_tasks budget of {budget.max_tasks}"
            )
        if len(findings) >= _MAX_FINDINGS:
            raise BudgetExceededError(
                f"gap findings exceed hard safety bound of {_MAX_FINDINGS}"
            )
        findings.append(finding)
    findings.sort(key=lambda item: item.path.encode("utf-8"))
    return tuple(findings)


def deduplicate_findings(
    findings: Iterable[GapFinding],
) -> tuple[GapFinding, ...]:
    """Return path+digest-unique findings in deterministic path order."""
    seen: set[str] = set()
    unique: list[GapFinding] = []
    for finding in findings:
        key = finding.dedupe_key
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    unique.sort(key=lambda item: item.path.encode("utf-8"))
    return tuple(unique)


def emit_gap_proposals(
    findings: Sequence[GapFinding],
    *,
    repository_id: str,
    repository_tree_id: str,
    inventory_snapshot_cid: str,
    base_plan_root_cid: str,
    analyzer_id: str,
    budget: RefinementBudget = DEFAULT_BUDGET,
    depth: int = 1,
) -> tuple[GapProposal, ...]:
    """Emit bounded, deduplicated, exact-tree, non-active gap proposals.

    Findings are packed into proposals without exceeding budget caps for
    goals, tasks, or depth. Model-call budget is recorded but not consumed
    (symbolic emission never issues model calls).
    """
    if depth < 1 or depth > budget.max_depth:
        raise BudgetExceededError(
            f"proposal depth {depth} is outside budget max_depth={budget.max_depth}"
        )
    unique = deduplicate_findings(findings)
    if not unique:
        return ()

    if len(unique) > budget.max_tasks:
        raise BudgetExceededError(
            f"cannot emit {len(unique)} findings under max_tasks={budget.max_tasks}"
        )

    # One goal per proposal batch; tasks map 1:1 with findings.
    # Cap the number of goals by packing all findings into at most max_goals
    # proposals (round-robin chunks).
    chunk_size = max(1, (len(unique) + budget.max_goals - 1) // budget.max_goals)
    proposals: list[GapProposal] = []
    for index in range(0, len(unique), chunk_size):
        if len(proposals) >= budget.max_goals:
            raise BudgetExceededError(
                f"generated goals would exceed max_goals={budget.max_goals}"
            )
        chunk = unique[index : index + chunk_size]
        goal_id = f"goal:inventory-gap:{index // chunk_size:04d}"
        task_ids = tuple(
            f"task:inventory-gap:{finding.path.replace('/', ':')}"
            for finding in chunk
        )
        body = {
            "analyzer_id": analyzer_id,
            "base_plan_root_cid": base_plan_root_cid,
            "findings": [f.to_dict() for f in chunk],
            "inventory_snapshot_cid": inventory_snapshot_cid,
            "repository_id": repository_id,
            "repository_tree_id": repository_tree_id,
        }
        proposal_id = content_identity(body)
        proposal = GapProposal(
            proposal_id=proposal_id,
            repository_id=repository_id,
            repository_tree_id=repository_tree_id,
            inventory_snapshot_cid=inventory_snapshot_cid,
            base_plan_root_cid=base_plan_root_cid,
            analyzer_id=analyzer_id,
            findings=chunk,
            proposed_goal_ids=(goal_id,),
            proposed_task_ids=task_ids,
            budget=budget,
            depth=depth,
            status=GapProposalStatus.PROPOSED,
            active=False,
            activation_gate=DQK_083_ROLLOVER_GATE,
        )
        require_non_active_until_rollover(proposal)
        proposals.append(proposal)
    return tuple(proposals)


# ---------------------------------------------------------------------------
# Canonical DQP plan-revision API (never raw status mutation)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlanRevisionSubmission:
    """Receipt that a proposal was accepted into the non-active revision store."""

    submission_id: str
    proposal_id: str
    repository_id: str
    repository_tree_id: str
    inventory_snapshot_cid: str
    status: str = PROPOSAL_STATUS_PROPOSED
    active: bool = False
    api_schema: str = PLAN_REVISION_API_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": False,
            "api_schema": self.api_schema,
            "inventory_snapshot_cid": self.inventory_snapshot_cid,
            "proposal_id": self.proposal_id,
            "repository_id": self.repository_id,
            "repository_tree_id": self.repository_tree_id,
            "status": self.status,
            "submission_id": self.submission_id,
        }


class DqpPlanRevisionAPI(Protocol):
    """Canonical DQP-039 plan-revision surface.

    Implementations store signed/CID-bound proposal rows. They must not expose
    raw task status mutation and must refuse cross-repository writes and
    analyzer self-approval.
    """

    @property
    def repository_id(self) -> str:
        """Repository this API instance is bound to."""

    @property
    def api_schema(self) -> str:
        """Wire schema of this plan-revision API."""

    def submit_proposal(self, proposal: GapProposal) -> PlanRevisionSubmission:
        """Admit a non-active gap proposal for later independent review."""

    def get_proposal(self, proposal_id: str) -> Optional[GapProposal]:
        """Return a previously submitted proposal, or None."""

    def list_proposals(self) -> tuple[GapProposal, ...]:
        """Return all non-active proposals in deterministic order."""

    def approve_proposal(
        self,
        proposal_id: str,
        *,
        reviewer_id: str,
        authorization_cid: str,
        decision_cid: str,
        expires_at: datetime | str,
        issued_at: datetime | str | None = None,
        generation_changed: bool = False,
        generation_rollover_receipt_cid: str = "",
    ) -> "RefinementReceipt":
        """Independent reviewer approval; must reject self-approval."""

    def mutate_task_status(self, *args: Any, **kwargs: Any) -> None:
        """Explicitly unavailable — raw status mutation is forbidden."""


class MemoryPlanRevisionAPI:
    """Hermetic in-memory DQP plan-revision API for tests and dry-runs.

    Enforces the same authority rules as a production adapter: repository
    binding, non-active proposals, no raw status mutation, and no self-approval.
    """

    def __init__(self, *, repository_id: str) -> None:
        if not repository_id or not str(repository_id).strip():
            raise InventoryRefinementError("repository_id is required")
        self._repository_id = str(repository_id).strip()
        self._proposals: dict[str, GapProposal] = {}
        self._submissions: dict[str, PlanRevisionSubmission] = {}
        self._receipts: dict[str, RefinementReceipt] = {}

    @property
    def repository_id(self) -> str:
        return self._repository_id

    @property
    def api_schema(self) -> str:
        return PLAN_REVISION_API_SCHEMA

    def submit_proposal(self, proposal: GapProposal) -> PlanRevisionSubmission:
        if not isinstance(proposal, GapProposal):
            raise InventoryRefinementError("proposal must be a GapProposal")
        require_non_active_until_rollover(proposal)
        if proposal.repository_id != self._repository_id:
            raise InventoryRefinementError(
                "refusing to mutate another repository plan: "
                f"api={self._repository_id!r} proposal={proposal.repository_id!r}"
            )
        existing = self._proposals.get(proposal.proposal_id)
        if existing is not None:
            # Idempotent resubmit of identical content.
            if existing.content_id != proposal.content_id:
                raise InventoryRefinementError(
                    f"proposal_id {proposal.proposal_id} already bound to different content"
                )
            return self._submissions[proposal.proposal_id]
        submission_id = content_identity(
            {
                "api_schema": PLAN_REVISION_API_SCHEMA,
                "proposal_id": proposal.proposal_id,
                "repository_id": proposal.repository_id,
                "repository_tree_id": proposal.repository_tree_id,
            }
        )
        submission = PlanRevisionSubmission(
            submission_id=submission_id,
            proposal_id=proposal.proposal_id,
            repository_id=proposal.repository_id,
            repository_tree_id=proposal.repository_tree_id,
            inventory_snapshot_cid=proposal.inventory_snapshot_cid,
            status=PROPOSAL_STATUS_PROPOSED,
            active=False,
        )
        self._proposals[proposal.proposal_id] = proposal
        self._submissions[proposal.proposal_id] = submission
        return submission

    def get_proposal(self, proposal_id: str) -> Optional[GapProposal]:
        return self._proposals.get(str(proposal_id))

    def list_proposals(self) -> tuple[GapProposal, ...]:
        return tuple(
            self._proposals[key]
            for key in sorted(self._proposals.keys())
        )

    def approve_proposal(
        self,
        proposal_id: str,
        *,
        reviewer_id: str,
        authorization_cid: str,
        decision_cid: str,
        expires_at: datetime | str,
        issued_at: datetime | str | None = None,
        generation_changed: bool = False,
        generation_rollover_receipt_cid: str = "",
    ) -> "RefinementReceipt":
        proposal = self._proposals.get(str(proposal_id))
        if proposal is None:
            raise InventoryRefinementError(f"unknown proposal_id {proposal_id!r}")
        if proposal.repository_id != self._repository_id:
            raise InventoryRefinementError(
                "refusing to approve a proposal for another repository plan"
            )
        reviewer = str(reviewer_id or "").strip()
        if not reviewer:
            raise InventoryRefinementError("reviewer_id is required")
        if reviewer == proposal.analyzer_id:
            raise SelfApprovalError(
                "analyzer cannot self-approve refinement proposals"
            )
        receipt = build_refinement_receipt(
            proposal=proposal,
            reviewer_id=reviewer,
            authorization_cid=authorization_cid,
            decision_cid=decision_cid,
            expires_at=expires_at,
            issued_at=issued_at,
            generation_changed=generation_changed,
            generation_rollover_receipt_cid=generation_rollover_receipt_cid,
            unresolved_gap_count=0,
        )
        self._receipts[receipt.receipt_cid] = receipt
        # Mark approved but still non-active (DQK-083 owns activation).
        approved = GapProposal(
            proposal_id=proposal.proposal_id,
            repository_id=proposal.repository_id,
            repository_tree_id=proposal.repository_tree_id,
            inventory_snapshot_cid=proposal.inventory_snapshot_cid,
            base_plan_root_cid=proposal.base_plan_root_cid,
            analyzer_id=proposal.analyzer_id,
            findings=proposal.findings,
            proposed_goal_ids=proposal.proposed_goal_ids,
            proposed_task_ids=proposal.proposed_task_ids,
            budget=proposal.budget,
            depth=proposal.depth,
            status=GapProposalStatus.APPROVED,
            active=False,
            activation_gate=DQK_083_ROLLOVER_GATE,
        )
        self._proposals[proposal.proposal_id] = approved
        return receipt

    def mutate_task_status(self, *args: Any, **kwargs: Any) -> None:
        raise InventoryRefinementError(
            "raw status mutation is forbidden; use the canonical plan-revision API"
        )


class PlanRevisionAdapter:
    """DQP-039 plan-revision adapter for inventory gap proposals.

    Always routes through :class:`DqpPlanRevisionAPI`. Never mutates task
    status rows directly.
    """

    def __init__(
        self,
        api: DqpPlanRevisionAPI,
        *,
        analyzer_id: str,
        budget: RefinementBudget = DEFAULT_BUDGET,
    ) -> None:
        if api is None:
            raise InventoryRefinementError("plan-revision API is required")
        analyzer = str(analyzer_id or "").strip()
        if not analyzer:
            raise InventoryRefinementError("analyzer_id is required")
        self._api = api
        self._analyzer_id = analyzer
        self._budget = budget
        self._model_calls = 0

    @property
    def analyzer_id(self) -> str:
        return self._analyzer_id

    @property
    def budget(self) -> RefinementBudget:
        return self._budget

    @property
    def api(self) -> DqpPlanRevisionAPI:
        return self._api

    @property
    def model_calls_used(self) -> int:
        return self._model_calls

    def compare_and_propose(
        self,
        records: Iterable[InventoryRecord],
        graph: TaskEffectGraph,
        *,
        depth: int = 1,
    ) -> tuple[tuple[GapProposal, ...], tuple[PlanRevisionSubmission, ...]]:
        """Compare inventory to graph and submit non-active gap proposals."""
        if graph.repository_id != self._api.repository_id:
            raise InventoryRefinementError(
                "analyzer cannot mutate another repository plan: "
                f"api={self._api.repository_id!r} graph={graph.repository_id!r}"
            )
        materialised = tuple(records)
        snapshot_cid = inventory_snapshot_cid(
            materialised, repository_tree_id=graph.repository_tree_id
        )
        findings = compare_inventory_to_effect_graph(
            materialised, graph, budget=self._budget
        )
        proposals = emit_gap_proposals(
            findings,
            repository_id=graph.repository_id,
            repository_tree_id=graph.repository_tree_id,
            inventory_snapshot_cid=snapshot_cid,
            base_plan_root_cid=graph.plan_root_cid,
            analyzer_id=self._analyzer_id,
            budget=self._budget,
            depth=depth,
        )
        submissions: list[PlanRevisionSubmission] = []
        for proposal in proposals:
            # Guard: adapter never activates proposals.
            require_non_active_until_rollover(proposal)
            if proposal.analyzer_id != self._analyzer_id:
                raise InventoryRefinementError(
                    "adapter cannot submit proposals under a foreign analyzer_id"
                )
            submissions.append(self._api.submit_proposal(proposal))
        return proposals, tuple(submissions)

    def approve(
        self,
        proposal_id: str,
        *,
        reviewer_id: str,
        authorization_cid: str,
        decision_cid: str,
        expires_at: datetime | str,
        issued_at: datetime | str | None = None,
        generation_changed: bool = False,
        generation_rollover_receipt_cid: str = "",
    ) -> "RefinementReceipt":
        """Delegate approval; enforces non-self-approval at the API boundary."""
        if str(reviewer_id or "").strip() == self._analyzer_id:
            raise SelfApprovalError(
                "analyzer cannot self-approve refinement proposals"
            )
        return self._api.approve_proposal(
            proposal_id,
            reviewer_id=reviewer_id,
            authorization_cid=authorization_cid,
            decision_cid=decision_cid,
            expires_at=expires_at,
            issued_at=issued_at,
            generation_changed=generation_changed,
            generation_rollover_receipt_cid=generation_rollover_receipt_cid,
        )

    def mutate_task_status(self, *args: Any, **kwargs: Any) -> None:
        """Explicitly unavailable on the adapter."""
        raise InventoryRefinementError(
            "raw status mutation is forbidden; use the canonical plan-revision API"
        )


# ---------------------------------------------------------------------------
# Cryptographic refinement receipt
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RefinementReceipt:
    """Signed inventory-refinement approval receipt (DQK-081 authority input)."""

    schema: str
    program_id: str
    task_id: str
    repository_id: str
    repository_tree_id: str
    inventory_snapshot_cid: str
    base_plan_root_cid: str
    accepted_plan_root_cid: str
    active_plan_root_cid: str
    analyzer_id: str
    reviewer_id: str
    authorization_cid: str
    decision_cid: str
    decision: str
    proposal_ids: tuple[str, ...]
    unresolved_gap_count: int
    generation_changed: bool
    generation_rollover_receipt_cid: str
    issued_at: str
    expires_at: str
    signature_algorithm: str
    signature: str
    receipt_cid: str
    accepted: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted is True,
            "active_plan_root_cid": self.active_plan_root_cid,
            "analyzer_id": self.analyzer_id,
            "accepted_plan_root_cid": self.accepted_plan_root_cid,
            "authorization_cid": self.authorization_cid,
            "base_plan_root_cid": self.base_plan_root_cid,
            "decision": self.decision,
            "decision_cid": self.decision_cid,
            "expires_at": self.expires_at,
            "generation_changed": self.generation_changed is True,
            "generation_rollover_receipt_cid": self.generation_rollover_receipt_cid,
            "inventory_snapshot_cid": self.inventory_snapshot_cid,
            "issued_at": self.issued_at,
            "program_id": self.program_id,
            "proposal_ids": list(self.proposal_ids),
            "receipt_cid": self.receipt_cid,
            "repository_id": self.repository_id,
            "repository_tree_id": self.repository_tree_id,
            "reviewer_id": self.reviewer_id,
            "schema": self.schema,
            "signature": self.signature,
            "signature_algorithm": self.signature_algorithm,
            "task_id": self.task_id,
            "unresolved_gap_count": int(self.unresolved_gap_count),
        }


def unsigned_preimage(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the signed-body preimage without digest/signature fields."""
    return {
        key: value
        for key, value in payload.items()
        if key not in _UNSIGNED_EXCLUDED
    }


def compute_signature(payload: Mapping[str, Any]) -> str:
    """Compute the content-bound signature for an unsigned body."""
    return content_identity(unsigned_preimage(payload))


def compute_receipt_cid(payload: Mapping[str, Any]) -> str:
    """Compute the content-bound receipt identity including the signature."""
    material = {
        key: value for key, value in payload.items() if key != "receipt_cid"
    }
    return content_identity(material)


def sign_receipt_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Attach signature and receipt_cid to a refinement receipt body."""
    body = dict(payload)
    body["signature_algorithm"] = SIGNATURE_ALGORITHM
    body.pop("signature", None)
    body.pop("receipt_cid", None)
    body["signature"] = compute_signature(body)
    body["receipt_cid"] = compute_receipt_cid(body)
    return body


def build_refinement_receipt(
    *,
    proposal: GapProposal,
    reviewer_id: str,
    authorization_cid: str,
    decision_cid: str,
    expires_at: datetime | str,
    issued_at: datetime | str | None = None,
    generation_changed: bool = False,
    generation_rollover_receipt_cid: str = "",
    unresolved_gap_count: int = 0,
    accepted_plan_root_cid: str | None = None,
    decision: str = "accepted",
) -> RefinementReceipt:
    """Build a cryptographically bound refinement approval receipt."""
    reviewer = str(reviewer_id or "").strip()
    if not reviewer:
        raise InventoryRefinementError("reviewer_id is required")
    if reviewer == proposal.analyzer_id:
        raise SelfApprovalError(
            "analyzer cannot self-approve refinement proposals"
        )
    auth = str(authorization_cid or "").strip()
    dec = str(decision_cid or "").strip()
    if not auth or not dec:
        raise InventoryRefinementError(
            "authorization_cid and decision_cid are required"
        )
    if generation_changed and not str(generation_rollover_receipt_cid or "").strip():
        raise InventoryRefinementError(
            "generation_changed requires generation_rollover_receipt_cid"
        )
    if unresolved_gap_count < 0:
        raise InventoryRefinementError("unresolved_gap_count must be non-negative")

    try:
        issued = normalize_timestamp(issued_at or datetime.now(timezone.utc))
        expires = normalize_timestamp(expires_at)
    except ContractError as exc:
        raise InventoryRefinementError(str(exc)) from exc

    accepted_root = (
        str(accepted_plan_root_cid).strip()
        if accepted_plan_root_cid
        else proposal.base_plan_root_cid
    )
    body = {
        "accepted": True,
        "active_plan_root_cid": accepted_root,
        "analyzer_id": proposal.analyzer_id,
        "accepted_plan_root_cid": accepted_root,
        "authorization_cid": auth,
        "base_plan_root_cid": proposal.base_plan_root_cid,
        "decision": str(decision).strip().lower(),
        "decision_cid": dec,
        "expires_at": expires,
        "generation_changed": generation_changed is True,
        "generation_rollover_receipt_cid": str(
            generation_rollover_receipt_cid or ""
        ).strip(),
        "inventory_snapshot_cid": proposal.inventory_snapshot_cid,
        "issued_at": issued,
        "program_id": PROGRAM_ID,
        "proposal_ids": [proposal.proposal_id],
        "repository_id": proposal.repository_id,
        "repository_tree_id": proposal.repository_tree_id,
        "reviewer_id": reviewer,
        "schema": RECEIPT_SCHEMA,
        "task_id": TASK_ID,
        "unresolved_gap_count": int(unresolved_gap_count),
    }
    signed = sign_receipt_payload(body)
    return RefinementReceipt(
        schema=RECEIPT_SCHEMA,
        program_id=PROGRAM_ID,
        task_id=TASK_ID,
        repository_id=proposal.repository_id,
        repository_tree_id=proposal.repository_tree_id,
        inventory_snapshot_cid=proposal.inventory_snapshot_cid,
        base_plan_root_cid=proposal.base_plan_root_cid,
        accepted_plan_root_cid=accepted_root,
        active_plan_root_cid=accepted_root,
        analyzer_id=proposal.analyzer_id,
        reviewer_id=reviewer,
        authorization_cid=auth,
        decision_cid=dec,
        decision=str(decision).strip().lower(),
        proposal_ids=(proposal.proposal_id,),
        unresolved_gap_count=int(unresolved_gap_count),
        generation_changed=generation_changed is True,
        generation_rollover_receipt_cid=str(
            generation_rollover_receipt_cid or ""
        ).strip(),
        issued_at=issued,
        expires_at=expires,
        signature_algorithm=SIGNATURE_ALGORITHM,
        signature=str(signed["signature"]),
        receipt_cid=str(signed["receipt_cid"]),
        accepted=True,
    )


def _bounded_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise VerificationError(f"{field} must be a string")
    if not value.strip():
        raise VerificationError(f"{field} must be non-empty")
    encoded = value.encode("utf-8")
    if len(encoded) > _MAX_FIELD_BYTES:
        raise VerificationError(f"{field} exceeds the {_MAX_FIELD_BYTES} byte bound")
    if any(character in value for character in _CONTROL_CHARS):
        raise VerificationError(f"{field} contains forbidden control characters")
    return value


def _require_sha256(value: Any, *, field: str) -> str:
    text = _bounded_text(value, field=field)
    if not _SHA256_DIGEST_RE.fullmatch(text):
        raise VerificationError(f"{field} must be sha256:<64 lowercase hex>")
    return text


def _parse_aware_datetime(value: Any, *, field: str) -> datetime:
    text = _bounded_text(value, field=field)
    if len(text.encode("utf-8")) > 128:
        raise VerificationError(f"{field} timestamp is unbounded")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VerificationError(f"{field} is not a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise VerificationError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _require_exact_keys(
    payload: Mapping[str, Any],
    *,
    allowed: frozenset[str],
    noun: str,
) -> None:
    keys = frozenset(payload)
    missing = sorted(allowed - keys)
    extra = sorted(keys - allowed)
    if missing:
        raise VerificationError(
            f"{noun} is incomplete; missing keys: {','.join(missing)}"
        )
    if extra:
        raise VerificationError(
            f"{noun} contains unsupported keys: {','.join(extra)}"
        )


def verify_signature(payload: Mapping[str, Any], *, noun: str = "receipt") -> None:
    """Fail closed when signature algorithm or digest does not match the body."""
    if "signature" not in payload or not payload.get("signature"):
        raise VerificationError(f"{noun} is unsigned")
    algorithm = _bounded_text(
        payload.get("signature_algorithm"), field=f"{noun}.signature_algorithm"
    )
    if algorithm != SIGNATURE_ALGORITHM:
        raise VerificationError(f"{noun} uses unsupported signature algorithm")
    expected = compute_signature(payload)
    actual = _require_sha256(payload.get("signature"), field=f"{noun}.signature")
    if not hmac.compare_digest(actual, expected):
        raise VerificationError(
            f"{noun} signature does not match the signed body (unsigned or tampered)"
        )
    expected_cid = compute_receipt_cid(payload)
    actual_cid = _require_sha256(
        payload.get("receipt_cid"), field=f"{noun}.receipt_cid"
    )
    if not hmac.compare_digest(actual_cid, expected_cid):
        raise VerificationError(f"{noun} receipt_cid does not match the signed body")


def verify_refinement_receipt(
    receipt: Mapping[str, Any] | RefinementReceipt,
    *,
    expected_repository_tree_id: str | None = None,
    expected_inventory_snapshot_cid: str | None = None,
    expected_plan_root_cid: str | None = None,
    expected_repository_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Verify a refinement receipt and emit the gate-typed verification object.

    Rejects unsigned, stale, mismatched, incomplete, and self-approved receipts.
    On success returns:

        schema = VERIFICATION_SCHEMA
        accepted = True
        ...identity fields consumed by DQK-081 manual-gate CAS...
    """
    if isinstance(receipt, RefinementReceipt):
        payload = receipt.to_dict()
    else:
        if not isinstance(receipt, Mapping):
            raise VerificationError("receipt must be a JSON object")
        payload = dict(receipt)

    _require_exact_keys(payload, allowed=_RECEIPT_KEYS, noun="refinement receipt")

    if payload.get("schema") != RECEIPT_SCHEMA:
        raise VerificationError(
            f"refinement receipt schema mismatch; expected {RECEIPT_SCHEMA}"
        )
    if payload.get("program_id") != PROGRAM_ID:
        raise VerificationError("refinement receipt program_id mismatch")
    if payload.get("task_id") != TASK_ID:
        raise VerificationError("refinement receipt task_id mismatch")
    if payload.get("accepted") is not True:
        raise VerificationError("refinement receipt is unaccepted")
    decision = _bounded_text(payload.get("decision"), field="decision").lower()
    if decision != "accepted":
        raise VerificationError("refinement receipt decision is not accepted")

    # Signature / completeness of identity fields.
    verify_signature(payload, noun="refinement receipt")

    repository_id = _bounded_text(
        payload.get("repository_id"), field="repository_id"
    )
    repository_tree_id = _bounded_text(
        payload.get("repository_tree_id"), field="repository_tree_id"
    )
    inventory_snapshot = _bounded_text(
        payload.get("inventory_snapshot_cid"), field="inventory_snapshot_cid"
    )
    base_plan = _bounded_text(
        payload.get("base_plan_root_cid"), field="base_plan_root_cid"
    )
    accepted_plan = _bounded_text(
        payload.get("accepted_plan_root_cid"), field="accepted_plan_root_cid"
    )
    active_plan = _bounded_text(
        payload.get("active_plan_root_cid"), field="active_plan_root_cid"
    )
    analyzer_id = _bounded_text(payload.get("analyzer_id"), field="analyzer_id")
    reviewer_id = _bounded_text(payload.get("reviewer_id"), field="reviewer_id")
    authorization_cid = _bounded_text(
        payload.get("authorization_cid"), field="authorization_cid"
    )
    decision_cid = _bounded_text(payload.get("decision_cid"), field="decision_cid")

    # Self-approval is never valid authority.
    if analyzer_id == reviewer_id:
        raise VerificationError(
            "refinement receipt is self-approved; independent reviewer required"
        )

    proposal_ids = payload.get("proposal_ids")
    if not isinstance(proposal_ids, list) or not proposal_ids:
        raise VerificationError("refinement receipt is incomplete; proposal_ids required")
    if any(not isinstance(item, str) or not item.strip() for item in proposal_ids):
        raise VerificationError("refinement receipt proposal_ids are malformed")

    unresolved = payload.get("unresolved_gap_count")
    if isinstance(unresolved, bool) or not isinstance(unresolved, int) or unresolved < 0:
        raise VerificationError("unresolved_gap_count must be a non-negative integer")

    generation_changed = payload.get("generation_changed")
    if not isinstance(generation_changed, bool):
        raise VerificationError("generation_changed must be a boolean")
    rollover_cid = payload.get("generation_rollover_receipt_cid")
    if not isinstance(rollover_cid, str):
        raise VerificationError("generation_rollover_receipt_cid must be a string")
    if generation_changed and not rollover_cid.strip():
        raise VerificationError(
            "generation_changed receipts must bind generation_rollover_receipt_cid"
        )

    # Staleness / expiry.
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise VerificationError("now must be timezone-aware")
    moment = moment.astimezone(timezone.utc)
    issued_at = _parse_aware_datetime(payload.get("issued_at"), field="issued_at")
    expires_at = _parse_aware_datetime(payload.get("expires_at"), field="expires_at")
    skew = timedelta(seconds=_ISSUED_AT_FUTURE_SKEW_SECONDS)
    if issued_at > moment + skew:
        raise VerificationError("issued_at is in the future beyond allowed clock skew")
    if expires_at <= moment:
        raise VerificationError("refinement receipt is stale (expired)")
    if expires_at <= issued_at:
        raise VerificationError("expires_at must be after issued_at")

    # Mismatch checks against expected authority bindings.
    if (
        expected_repository_id is not None
        and repository_id != str(expected_repository_id).strip()
    ):
        raise VerificationError("refinement receipt repository_id is mismatched")
    if (
        expected_repository_tree_id is not None
        and repository_tree_id != str(expected_repository_tree_id).strip()
    ):
        raise VerificationError(
            "refinement receipt repository_tree_id is mismatched or stale"
        )
    if (
        expected_inventory_snapshot_cid is not None
        and inventory_snapshot != str(expected_inventory_snapshot_cid).strip()
    ):
        raise VerificationError(
            "refinement receipt inventory_snapshot_cid is mismatched"
        )
    if expected_plan_root_cid is not None:
        expected_root = str(expected_plan_root_cid).strip()
        if accepted_plan != expected_root or active_plan != expected_root:
            raise VerificationError(
                "refinement receipt plan root is mismatched or stale"
            )

    return {
        "schema": VERIFICATION_SCHEMA,
        "accepted": True,
        "inventory_snapshot_cid": inventory_snapshot,
        "accepted_plan_root_cid": accepted_plan,
        "active_plan_root_cid": active_plan,
        "base_plan_root_cid": base_plan,
        "decision_cid": decision_cid,
        "authorization_cid": authorization_cid,
        "repository_tree_id": repository_tree_id,
        "repository_id": repository_id,
        "unresolved_gap_count": unresolved,
        "generation_changed": generation_changed,
        "generation_rollover_receipt_cid": rollover_cid,
        "receipt_cid": _require_sha256(
            payload.get("receipt_cid"), field="receipt_cid"
        ),
        "expires_at": normalize_timestamp(expires_at),
        "analyzer_id": analyzer_id,
        "reviewer_id": reviewer_id,
        "proposal_ids": list(proposal_ids),
    }


# ---------------------------------------------------------------------------
# JSON helpers / CLI
# ---------------------------------------------------------------------------


def strict_json_object(raw: str | bytes, *, noun: str) -> dict[str, Any]:
    """Decode one bounded authority object without duplicate keys or NaN."""
    if isinstance(raw, bytes):
        if len(raw) > _MAX_RECEIPT_BYTES:
            raise VerificationError(
                f"{noun} exceeds the {_MAX_RECEIPT_BYTES} byte bound"
            )
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise VerificationError(f"{noun} is not UTF-8") from exc
    else:
        if not isinstance(raw, str) or not raw:
            raise VerificationError(f"{noun} must be a non-empty UTF-8 JSON object")
        if len(raw.encode("utf-8")) > _MAX_RECEIPT_BYTES:
            raise VerificationError(
                f"{noun} exceeds the {_MAX_RECEIPT_BYTES} byte bound"
            )
        text = raw

    def object_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise VerificationError(f"{noun} contains duplicate key {key!r}")
            result[key] = item
        return result

    def reject_constant(constant: str) -> Any:
        raise VerificationError(f"{noun} contains non-finite value {constant}")

    try:
        decoded = json.loads(
            text,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise VerificationError(f"{noun} is not strict JSON") from exc
    if not isinstance(decoded, dict):
        raise VerificationError(f"{noun} must be a JSON object")
    return decoded


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ipfs_datasets_py.duckdb_control.inventory_refinement",
        description=(
            "Inventory-to-plan refinement adapter and cryptographically "
            "verified approval-receipt command (DQK-080)."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    verify = sub.add_parser(
        "verify",
        help="cryptographically verify a refinement approval receipt",
    )
    verify.add_argument(
        "--check",
        action="store_true",
        help="self-check module readiness without verifying a receipt",
    )
    verify.add_argument(
        "--receipt",
        type=str,
        default="",
        help="path to a refinement receipt JSON document",
    )
    verify.add_argument(
        "--repository-tree-id",
        type=str,
        default="",
        help="expected repository tree binding",
    )
    verify.add_argument(
        "--inventory-snapshot-cid",
        type=str,
        default="",
        help="expected inventory snapshot CID",
    )
    verify.add_argument(
        "--plan-root-cid",
        type=str,
        default="",
        help="expected accepted/active plan root CID",
    )
    verify.add_argument(
        "--repository-id",
        type=str,
        default="",
        help="expected repository id",
    )
    verify.add_argument(
        "--json",
        action="store_true",
        help="emit structured JSON on success",
    )
    return parser


def _emit_json(payload: Mapping[str, Any], stream: TextIO) -> None:
    stream.write(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )
    stream.write("\n")


def run_verify(args: argparse.Namespace) -> int:
    if args.check and not args.receipt:
        payload = {
            "ok": True,
            "command": APPROVAL_COMMAND,
            "program_id": PROGRAM_ID,
            "task_id": TASK_ID,
            "verification_schema": VERIFICATION_SCHEMA,
            "receipt_schema": RECEIPT_SCHEMA,
            "plan_revision_api_schema": PLAN_REVISION_API_SCHEMA,
            "proposal_schema": GAP_PROPOSAL_SCHEMA,
            "activation_gate": DQK_083_ROLLOVER_GATE,
            "signature_algorithm": SIGNATURE_ALGORITHM,
            "default_budget": DEFAULT_BUDGET.to_dict(),
        }
        if args.json:
            _emit_json(payload, sys.stdout)
        else:
            sys.stdout.write(
                f"ok inventory_refinement ready "
                f"schema={VERIFICATION_SCHEMA} api={PLAN_REVISION_API_SCHEMA}\n"
            )
        return 0

    if not args.receipt:
        sys.stderr.write(
            "error: verify requires --receipt PATH or --check\n"
        )
        return 2

    path = Path(args.receipt)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        sys.stderr.write(f"error: cannot read receipt: {exc}\n")
        return 2

    try:
        receipt = strict_json_object(raw, noun="refinement receipt")
        verification = verify_refinement_receipt(
            receipt,
            expected_repository_tree_id=args.repository_tree_id or None,
            expected_inventory_snapshot_cid=args.inventory_snapshot_cid or None,
            expected_plan_root_cid=args.plan_root_cid or None,
            expected_repository_id=args.repository_id or None,
        )
    except VerificationError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1

    if args.json:
        _emit_json(verification, sys.stdout)
    else:
        sys.stdout.write(
            f"accepted decision_cid={verification['decision_cid']} "
            f"receipt_cid={verification['receipt_cid']}\n"
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "verify":
        return run_verify(args)
    parser.error(f"unsupported command {args.command!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
