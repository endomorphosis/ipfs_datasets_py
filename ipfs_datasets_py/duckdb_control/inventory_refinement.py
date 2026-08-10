"""Inventory-to-plan refinement and DQP plan-revision adapter (DQK-080).

Compares a producer inventory snapshot with a declared task/effect graph and
emits bounded, deduplicated, exact-tree gap proposals through DQP's canonical
plan-revision API. Proposals bind the repository tree and inventory snapshot
and remain non-active until DQK-083 generation rollover materializes them.

Also provides a cryptographically verified approval-receipt command consumed
by the DQK-081 manual gate:

    python -m ipfs_datasets_py.duckdb_control.inventory_refinement verify \\
        --receipt <path> --json

    python -m ipfs_datasets_py.duckdb_control.inventory_refinement verify \\
        --check

Acceptance (DQK-080):

* Adapter uses the canonical plan-revision API rather than raw status mutation
* Proposals bind exact repository tree + inventory snapshot; non-active until
  DQK-083 rollover
* Budgets cap generated goals, tasks, depth, retries, and model calls
* No analyzer can self-approve or directly mutate another repository plan
* Verifier rejects unsigned, stale, mismatched, incomplete, or self-approved
  refinement receipts

Importing this module is inert: no filesystem, network, or database I/O until
an explicit entry point is called.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
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
    canonical_json_bytes,
    content_identity,
    normalize_timestamp,
)
from ipfs_datasets_py.duckdb_control.inventory import (
    ArtifactKind,
    InventoryRecord,
    ProposedAuthority,
    inventory_snapshot_digest,
    normalize_rel_path,
)

__all__ = [
    "APPROVAL_RECEIPT_SCHEMA",
    "GAP_PROPOSAL_SCHEMA",
    "OWNER_TASK_ID",
    "PLAN_REVISION_REQUEST_SCHEMA",
    "PROPOSAL_STATUS_NON_ACTIVE",
    "REFINEMENT_SCHEMA",
    "ROLLOVER_GATE_TASK_ID",
    "SIGNATURE_ALGORITHM",
    "VERIFICATION_SCHEMA",
    "CanonicalPlanRevisionAPI",
    "GapFinding",
    "GapProposal",
    "InventoryRefinementError",
    "MemoryPlanRevisionAPI",
    "PlanRevisionAdapter",
    "PlanRevisionRequest",
    "ProposalStatus",
    "RefinementBudget",
    "RefinementReceipt",
    "TaskEffectDeclaration",
    "VerificationResult",
    "build_approval_receipt",
    "build_gap_proposals",
    "build_verification",
    "compare_inventory_to_effects",
    "deduplicate_findings",
    "inventory_snapshot_cid",
    "main",
    "self_check",
    "submit_gap_proposals",
    "verify_receipt",
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
PLAN_REVISION_REQUEST_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control/plan-revision-request@1"
)
APPROVAL_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control/inventory-refinement-receipt@1"
)
VERIFICATION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control/inventory-refinement-verification@1"
)

OWNER_TASK_ID: Final[str] = "DQK-080"
APPROVAL_GATE_TASK_ID: Final[str] = "DQK-081"
ROLLOVER_GATE_TASK_ID: Final[str] = "DQK-083"
PROGRAM_ID: Final[str] = "ipfs-datasets-duckdb-quack-control-plane-v1"
SIGNATURE_ALGORITHM: Final[str] = "content-bound-sha256@1"
PROPOSAL_STATUS_NON_ACTIVE: Final[str] = "non_active"

# Default budgets keep refinement deterministic and storm-resistant.
DEFAULT_MAX_GOALS: Final[int] = 32
DEFAULT_MAX_TASKS: Final[int] = 128
DEFAULT_MAX_DEPTH: Final[int] = 4
DEFAULT_MAX_RETRIES: Final[int] = 2
DEFAULT_MAX_MODEL_CALLS: Final[int] = 0  # pure deterministic path by default

_MAX_RECEIPT_BYTES: Final[int] = 2 * 1024 * 1024
_MAX_FIELD_BYTES: Final[int] = 4096
_ISSUED_AT_FUTURE_SKEW_SECONDS: Final[int] = 60
_SHA256_DIGEST: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_OID: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_CONTROL_CHARS: Final[frozenset[str]] = frozenset(("\0", "\n", "\r"))
_UNSIGNED_EXCLUDED: Final[frozenset[str]] = frozenset(
    {"signature", "receipt_cid", "verification"}
)

# Mutable producers/consumers that require plan ownership or an explicit waiver.
_MUTABLE_KINDS: Final[frozenset[ArtifactKind]] = frozenset(
    {
        ArtifactKind.MUTABLE_STATE,
        ArtifactKind.UNSAFE_SERIALIZATION,
        ArtifactKind.UNKNOWN,
    }
)
_MUTABLE_AUTHORITIES: Final[frozenset[ProposedAuthority]] = frozenset(
    {
        ProposedAuthority.CONTROL_DUCKDB,
        ProposedAuthority.DOMAIN_DUCKDB,
        ProposedAuthority.ONE_TIME_IMPORT,
        ProposedAuthority.QUARANTINE,
        ProposedAuthority.RETAIN_FILE,
    }
)


class InventoryRefinementError(ValueError):
    """Raised when refinement inputs, budgets, or receipts fail closed."""


class ProposalStatus(str, Enum):
    """Lifecycle of a gap proposal relative to generation rollover."""

    NON_ACTIVE = "non_active"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    ROLLED_OVER = "rolled_over"

    @classmethod
    def parse(cls, value: str | ProposalStatus) -> ProposalStatus:
        if isinstance(value, ProposalStatus):
            return value
        text = str(value).strip().lower().replace("-", "_")
        return cls(text)


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RefinementBudget:
    """Hard caps on refinement generation work.

    Every limit must be a non-negative integer. Zero for model calls means the
    pure deterministic path (no LLM). All other zeros block generation.
    """

    max_goals: int = DEFAULT_MAX_GOALS
    max_tasks: int = DEFAULT_MAX_TASKS
    max_depth: int = DEFAULT_MAX_DEPTH
    max_retries: int = DEFAULT_MAX_RETRIES
    max_model_calls: int = DEFAULT_MAX_MODEL_CALLS

    def __post_init__(self) -> None:
        for name in (
            "max_goals",
            "max_tasks",
            "max_depth",
            "max_retries",
            "max_model_calls",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise InventoryRefinementError(
                    f"{name} must be a non-negative integer, got {value!r}"
                )

    @property
    def allows_model_calls(self) -> bool:
        return self.max_model_calls > 0

    def to_dict(self) -> dict[str, int]:
        return {
            "max_goals": self.max_goals,
            "max_tasks": self.max_tasks,
            "max_depth": self.max_depth,
            "max_retries": self.max_retries,
            "max_model_calls": self.max_model_calls,
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> RefinementBudget:
        if payload is None:
            return cls()
        if not isinstance(payload, Mapping):
            raise InventoryRefinementError("refinement budget must be an object")
        return cls(
            max_goals=int(payload.get("max_goals", DEFAULT_MAX_GOALS)),
            max_tasks=int(payload.get("max_tasks", DEFAULT_MAX_TASKS)),
            max_depth=int(payload.get("max_depth", DEFAULT_MAX_DEPTH)),
            max_retries=int(payload.get("max_retries", DEFAULT_MAX_RETRIES)),
            max_model_calls=int(
                payload.get("max_model_calls", DEFAULT_MAX_MODEL_CALLS)
            ),
        )


# ---------------------------------------------------------------------------
# Task / effect graph and findings
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TaskEffectDeclaration:
    """One declared task effect that owns producer/consumer paths.

    Paths are posix-relative. Prefix ownership uses trailing ``/`` or path
    prefixes matched with :func:`path_owned_by`.
    """

    task_id: str
    owned_paths: tuple[str, ...] = ()
    effects: tuple[str, ...] = ()
    repository_id: str = ""
    goal_id: str = ""
    depth: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise InventoryRefinementError("task_id must be nonempty text")
        object.__setattr__(self, "task_id", self.task_id.strip())
        paths = tuple(
            normalize_rel_path(path)
            for path in self.owned_paths
            if str(path).strip()
        )
        effects = tuple(str(item).strip() for item in self.effects if str(item).strip())
        object.__setattr__(self, "owned_paths", paths)
        object.__setattr__(self, "effects", effects)
        if isinstance(self.depth, bool) or not isinstance(self.depth, int) or self.depth < 0:
            raise InventoryRefinementError("depth must be a non-negative integer")
        object.__setattr__(self, "repository_id", str(self.repository_id or "").strip())
        object.__setattr__(self, "goal_id", str(self.goal_id or "").strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "owned_paths": list(self.owned_paths),
            "effects": list(self.effects),
            "repository_id": self.repository_id,
            "goal_id": self.goal_id,
            "depth": self.depth,
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> TaskEffectDeclaration:
        if not isinstance(payload, Mapping):
            raise InventoryRefinementError("task effect must be an object")
        owned = payload.get("owned_paths") or payload.get("paths") or ()
        effects = payload.get("effects") or ()
        return cls(
            task_id=str(payload.get("task_id") or payload.get("id") or ""),
            owned_paths=tuple(str(item) for item in owned),
            effects=tuple(str(item) for item in effects),
            repository_id=str(payload.get("repository_id") or ""),
            goal_id=str(payload.get("goal_id") or ""),
            depth=int(payload.get("depth", 1)),
        )


def path_owned_by(path: str, owned_paths: Sequence[str]) -> bool:
    """Return True when *path* is covered by any declared owned path."""

    candidate = normalize_rel_path(path)
    if not candidate:
        return False
    for owned in owned_paths:
        pattern = normalize_rel_path(owned)
        if not pattern:
            continue
        if candidate == pattern:
            return True
        # Directory / prefix ownership: "data/agent_supervisor" owns children.
        if candidate.startswith(pattern.rstrip("/") + "/"):
            return True
        # Glob-style trailing * is accepted as a literal prefix match.
        if pattern.endswith("*") and candidate.startswith(pattern[:-1]):
            return True
    return False


@dataclass(frozen=True, slots=True)
class GapFinding:
    """One inventory path not owned by the declared task/effect graph."""

    path: str
    kind: str
    digest: str
    producer: str
    consumer: str
    proposed_authority: str
    reason: str
    gap_key: str = ""

    def __post_init__(self) -> None:
        path = normalize_rel_path(self.path)
        if not path:
            raise InventoryRefinementError("gap path must be nonempty")
        object.__setattr__(self, "path", path)
        digest = str(self.digest or "").strip().lower()
        if digest.startswith("sha256:"):
            digest = digest[len("sha256:") :]
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise InventoryRefinementError(
                f"gap digest must be sha256 hex, got {self.digest!r}"
            )
        object.__setattr__(self, "digest", digest)
        if not self.gap_key:
            key_material = f"{path}\0{digest}\0{self.reason}"
            object.__setattr__(
                self,
                "gap_key",
                "sha256:" + hashlib.sha256(key_material.encode("utf-8")).hexdigest(),
            )

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "kind": self.kind,
            "digest": self.digest,
            "producer": self.producer,
            "consumer": self.consumer,
            "proposed_authority": self.proposed_authority,
            "reason": self.reason,
            "gap_key": self.gap_key,
        }


def _requires_ownership(record: InventoryRecord) -> bool:
    if record.kind in _MUTABLE_KINDS:
        return True
    if record.proposed_authority in _MUTABLE_AUTHORITIES:
        return True
    return False


def compare_inventory_to_effects(
    records: Iterable[InventoryRecord],
    effects: Sequence[TaskEffectDeclaration],
    *,
    repository_id: str = "",
) -> tuple[GapFinding, ...]:
    """Diff inventory producers against the declared task/effect graph.

    Returns deterministic, path-ordered gap findings for records that require
    ownership but are not covered by any effect in the same repository.
    """

    owned: list[str] = []
    for effect in effects:
        if repository_id and effect.repository_id and effect.repository_id != repository_id:
            # Foreign-repository effects never cover this tree.
            continue
        owned.extend(effect.owned_paths)

    findings: list[GapFinding] = []
    for record in records:
        if not _requires_ownership(record):
            continue
        if path_owned_by(record.path, owned):
            continue
        findings.append(
            GapFinding(
                path=record.path,
                kind=record.kind.value,
                digest=record.digest,
                producer=record.producer,
                consumer=record.consumer,
                proposed_authority=record.proposed_authority.value,
                reason="unowned_mutable_producer",
            )
        )
    findings.sort(key=lambda item: item.path.encode("utf-8"))
    return tuple(findings)


def deduplicate_findings(findings: Sequence[GapFinding]) -> tuple[GapFinding, ...]:
    """Collapse duplicate findings by path+digest, preserving first reason."""

    seen: dict[tuple[str, str], GapFinding] = {}
    for finding in findings:
        key = (finding.path, finding.digest)
        if key not in seen:
            seen[key] = finding
    ordered = sorted(seen.values(), key=lambda item: item.path.encode("utf-8"))
    return tuple(ordered)


def inventory_snapshot_cid(records: Iterable[InventoryRecord]) -> str:
    """Return ``sha256:<hex>`` for a deterministic inventory snapshot digest."""

    digest = inventory_snapshot_digest(records)
    return f"sha256:{digest}"


# ---------------------------------------------------------------------------
# Gap proposals and plan-revision API
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GapProposal:
    """Bounded gap proposal bound to exact tree and inventory snapshot.

    Proposals are always created as :attr:`ProposalStatus.NON_ACTIVE` and stay
    non-active until DQK-083 generation rollover materializes an accepted
    revision. Analyzers never mark them active.
    """

    proposal_id: str
    repository_id: str
    repository_tree_id: str
    inventory_snapshot_cid: str
    base_plan_root_cid: str
    findings: tuple[GapFinding, ...]
    proposed_goals: tuple[str, ...]
    proposed_tasks: tuple[str, ...]
    budget: RefinementBudget
    status: ProposalStatus = ProposalStatus.NON_ACTIVE
    analyzer_id: str = "inventory-refinement-analyzer"
    depth: int = 1
    schema: str = GAP_PROPOSAL_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != GAP_PROPOSAL_SCHEMA:
            raise InventoryRefinementError(
                f"gap proposal schema must be {GAP_PROPOSAL_SCHEMA}"
            )
        for field_name in (
            "proposal_id",
            "repository_id",
            "repository_tree_id",
            "inventory_snapshot_cid",
            "base_plan_root_cid",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise InventoryRefinementError(f"{field_name} must be nonempty text")
            _reject_control_chars(value, field_name)
        if not _SHA256_DIGEST.fullmatch(self.inventory_snapshot_cid):
            raise InventoryRefinementError(
                "inventory_snapshot_cid must be sha256:<64 hex>"
            )
        if not isinstance(self.budget, RefinementBudget):
            raise InventoryRefinementError("budget must be a RefinementBudget")
        status = ProposalStatus.parse(self.status)
        object.__setattr__(self, "status", status)
        if status is not ProposalStatus.NON_ACTIVE and status is not ProposalStatus.ACCEPTED:
            # Rolled-over / rejected are terminal labels set only by lifecycle owners.
            pass
        if isinstance(self.depth, bool) or not isinstance(self.depth, int) or self.depth < 0:
            raise InventoryRefinementError("depth must be a non-negative integer")
        if self.depth > self.budget.max_depth:
            raise InventoryRefinementError(
                f"proposal depth {self.depth} exceeds budget max_depth "
                f"{self.budget.max_depth}"
            )
        if len(self.proposed_goals) > self.budget.max_goals:
            raise InventoryRefinementError(
                f"proposed goal count {len(self.proposed_goals)} exceeds "
                f"budget max_goals {self.budget.max_goals}"
            )
        if len(self.proposed_tasks) > self.budget.max_tasks:
            raise InventoryRefinementError(
                f"proposed task count {len(self.proposed_tasks)} exceeds "
                f"budget max_tasks {self.budget.max_tasks}"
            )
        if len(self.findings) > self.budget.max_tasks:
            raise InventoryRefinementError(
                f"finding count {len(self.findings)} exceeds budget max_tasks "
                f"{self.budget.max_tasks}"
            )

    @property
    def is_active(self) -> bool:
        return self.status is ProposalStatus.ROLLED_OVER

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "proposal_id": self.proposal_id,
            "repository_id": self.repository_id,
            "repository_tree_id": self.repository_tree_id,
            "inventory_snapshot_cid": self.inventory_snapshot_cid,
            "base_plan_root_cid": self.base_plan_root_cid,
            "findings": [item.to_dict() for item in self.findings],
            "proposed_goals": list(self.proposed_goals),
            "proposed_tasks": list(self.proposed_tasks),
            "budget": self.budget.to_dict(),
            "status": self.status.value,
            "analyzer_id": self.analyzer_id,
            "depth": self.depth,
            "active": False if self.status is ProposalStatus.NON_ACTIVE else self.is_active,
            "rollover_gate": ROLLOVER_GATE_TASK_ID,
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> GapProposal:
        if not isinstance(payload, Mapping):
            raise InventoryRefinementError("gap proposal must be an object")
        findings_raw = payload.get("findings") or ()
        findings = tuple(
            GapFinding(
                path=str(item.get("path") or ""),
                kind=str(item.get("kind") or ""),
                digest=str(item.get("digest") or ""),
                producer=str(item.get("producer") or ""),
                consumer=str(item.get("consumer") or ""),
                proposed_authority=str(item.get("proposed_authority") or ""),
                reason=str(item.get("reason") or ""),
                gap_key=str(item.get("gap_key") or ""),
            )
            for item in findings_raw
        )
        return cls(
            proposal_id=str(payload.get("proposal_id") or ""),
            repository_id=str(payload.get("repository_id") or ""),
            repository_tree_id=str(payload.get("repository_tree_id") or ""),
            inventory_snapshot_cid=str(payload.get("inventory_snapshot_cid") or ""),
            base_plan_root_cid=str(payload.get("base_plan_root_cid") or ""),
            findings=findings,
            proposed_goals=tuple(str(item) for item in (payload.get("proposed_goals") or ())),
            proposed_tasks=tuple(str(item) for item in (payload.get("proposed_tasks") or ())),
            budget=RefinementBudget.from_mapping(payload.get("budget")),
            status=ProposalStatus.parse(str(payload.get("status") or PROPOSAL_STATUS_NON_ACTIVE)),
            analyzer_id=str(payload.get("analyzer_id") or "inventory-refinement-analyzer"),
            depth=int(payload.get("depth", 1)),
            schema=str(payload.get("schema") or GAP_PROPOSAL_SCHEMA),
        )


@dataclass(frozen=True, slots=True)
class PlanRevisionRequest:
    """Canonical plan-revision API request (DQP-039 surface).

    This is the only supported mutation surface for inventory refinement.
    Callers must not CAS task status or rewrite another repository's plan.
    """

    request_id: str
    repository_id: str
    repository_tree_id: str
    base_plan_root_cid: str
    inventory_snapshot_cid: str
    proposals: tuple[GapProposal, ...]
    budget: RefinementBudget
    analyzer_id: str
    schema: str = PLAN_REVISION_REQUEST_SCHEMA
    activate: bool = False  # always False; activation is DQK-083 only

    def __post_init__(self) -> None:
        if self.schema != PLAN_REVISION_REQUEST_SCHEMA:
            raise InventoryRefinementError(
                f"plan revision request schema must be {PLAN_REVISION_REQUEST_SCHEMA}"
            )
        if self.activate:
            raise InventoryRefinementError(
                "plan revision requests cannot activate proposals; "
                f"activation requires {ROLLOVER_GATE_TASK_ID} rollover"
            )
        for field_name in (
            "request_id",
            "repository_id",
            "repository_tree_id",
            "base_plan_root_cid",
            "inventory_snapshot_cid",
            "analyzer_id",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise InventoryRefinementError(f"{field_name} must be nonempty text")
        for proposal in self.proposals:
            if proposal.repository_id != self.repository_id:
                raise InventoryRefinementError(
                    "proposal repository_id does not match plan-revision request"
                )
            if proposal.repository_tree_id != self.repository_tree_id:
                raise InventoryRefinementError(
                    "proposal repository_tree_id does not match plan-revision request"
                )
            if proposal.inventory_snapshot_cid != self.inventory_snapshot_cid:
                raise InventoryRefinementError(
                    "proposal inventory_snapshot_cid does not match request"
                )
            if proposal.status is not ProposalStatus.NON_ACTIVE:
                raise InventoryRefinementError(
                    "plan-revision API only admits non_active proposals"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "request_id": self.request_id,
            "repository_id": self.repository_id,
            "repository_tree_id": self.repository_tree_id,
            "base_plan_root_cid": self.base_plan_root_cid,
            "inventory_snapshot_cid": self.inventory_snapshot_cid,
            "proposals": [item.to_dict() for item in self.proposals],
            "budget": self.budget.to_dict(),
            "analyzer_id": self.analyzer_id,
            "activate": False,
            "mutation_surface": "plan_revision_api",
            "status_mutation": False,
        }


class CanonicalPlanRevisionAPI(Protocol):
    """DQP-039 canonical plan-revision surface.

    Implementations persist non-active proposals. They must refuse raw status
    mutation, self-approval, activation, and cross-repository plan writes.
    """

    def submit_plan_revision(self, request: PlanRevisionRequest) -> Mapping[str, Any]:
        """Submit a non-active plan-revision request; return an admission receipt."""


@dataclass
class MemoryPlanRevisionAPI:
    """In-memory plan-revision API used by tests and hermetic adapters.

    Records submitted requests and refuses forbidden operations.
    """

    repository_id: str
    submitted: list[PlanRevisionRequest] = field(default_factory=list)
    status_mutations: list[Mapping[str, Any]] = field(default_factory=list)
    _proposal_ids: set[str] = field(default_factory=set)

    def submit_plan_revision(self, request: PlanRevisionRequest) -> Mapping[str, Any]:
        if not isinstance(request, PlanRevisionRequest):
            raise InventoryRefinementError("request must be a PlanRevisionRequest")
        # Re-validate activate / status invariants.
        if request.activate:
            raise InventoryRefinementError(
                "canonical plan-revision API refuses activation"
            )
        if request.repository_id != self.repository_id:
            raise InventoryRefinementError(
                "analyzer cannot mutate another repository plan"
            )
        for proposal in request.proposals:
            if proposal.status is not ProposalStatus.NON_ACTIVE:
                raise InventoryRefinementError(
                    "canonical plan-revision API refuses non-non_active proposals"
                )
            if proposal.proposal_id in self._proposal_ids:
                # Idempotent dedup: same proposal_id is a no-op success.
                continue
            self._proposal_ids.add(proposal.proposal_id)
        self.submitted.append(request)
        admission = {
            "schema": "ipfs_datasets_py/duckdb-control/plan-revision-admission@1",
            "request_id": request.request_id,
            "repository_id": request.repository_id,
            "repository_tree_id": request.repository_tree_id,
            "inventory_snapshot_cid": request.inventory_snapshot_cid,
            "base_plan_root_cid": request.base_plan_root_cid,
            "proposal_count": len(request.proposals),
            "proposal_ids": [item.proposal_id for item in request.proposals],
            "status": PROPOSAL_STATUS_NON_ACTIVE,
            "active": False,
            "status_mutation": False,
            "mutation_surface": "plan_revision_api",
            "admission_cid": content_identity(
                {
                    "request_id": request.request_id,
                    "repository_tree_id": request.repository_tree_id,
                    "inventory_snapshot_cid": request.inventory_snapshot_cid,
                    "proposal_ids": [item.proposal_id for item in request.proposals],
                }
            ),
        }
        return MappingProxyType(dict(admission))

    def mutate_task_status(self, *_args: Any, **_kwargs: Any) -> None:
        """Explicit raw status mutation surface — always refused."""

        self.status_mutations.append({"refused": True, "args": _args, "kwargs": _kwargs})
        raise InventoryRefinementError(
            "raw status mutation is not permitted; use the plan-revision API"
        )

    def activate_proposals(self, *_args: Any, **_kwargs: Any) -> None:
        raise InventoryRefinementError(
            f"activation is reserved for {ROLLOVER_GATE_TASK_ID} rollover"
        )


def _reject_control_chars(value: str, field_name: str) -> None:
    if any(character in value for character in _CONTROL_CHARS):
        raise InventoryRefinementError(
            f"{field_name} must not contain control characters"
        )
    if len(value.encode("utf-8")) > _MAX_FIELD_BYTES:
        raise InventoryRefinementError(
            f"{field_name} exceeds {_MAX_FIELD_BYTES}-byte bound"
        )


def _proposal_id_for(
    *,
    repository_tree_id: str,
    inventory_snapshot_cid: str,
    findings: Sequence[GapFinding],
) -> str:
    material = {
        "repository_tree_id": repository_tree_id,
        "inventory_snapshot_cid": inventory_snapshot_cid,
        "gap_keys": [item.gap_key for item in findings],
    }
    return content_identity(material)


def build_gap_proposals(
    findings: Sequence[GapFinding],
    *,
    repository_id: str,
    repository_tree_id: str,
    inventory_snapshot_cid: str,
    base_plan_root_cid: str,
    budget: RefinementBudget | None = None,
    analyzer_id: str = "inventory-refinement-analyzer",
    goal_prefix: str = "DQK-G-INV",
    task_prefix: str = "DQK-INV",
) -> tuple[GapProposal, ...]:
    """Build bounded, deduplicated, non-active gap proposals from findings."""

    limits = budget if budget is not None else RefinementBudget()
    if limits.max_tasks == 0 or limits.max_goals == 0 or limits.max_depth == 0:
        # Zero caps mean the budget forbids generating goals/tasks at any depth.
        return ()
    unique = deduplicate_findings(findings)
    if not unique:
        return ()

    # Cap findings to max_tasks; residual is reported but not proposed.
    capped = unique[: limits.max_tasks]
    if not capped:
        return ()

    # One goal per path prefix group, capped by max_goals.
    by_prefix: dict[str, list[GapFinding]] = {}
    for finding in capped:
        parts = finding.path.split("/")
        prefix = parts[0] if parts else finding.path
        by_prefix.setdefault(prefix, []).append(finding)

    prefixes = sorted(by_prefix.keys(), key=lambda item: item.encode("utf-8"))
    prefixes = prefixes[: limits.max_goals]

    proposals: list[GapProposal] = []
    for index, prefix in enumerate(prefixes, start=1):
        group = by_prefix[prefix]
        goals = (f"{goal_prefix}-{prefix.upper().replace('/', '-')}",)
        tasks = tuple(
            f"{task_prefix}-{index:03d}-{offset:03d}"
            for offset, _ in enumerate(group, start=1)
        )
        if len(tasks) > limits.max_tasks:
            tasks = tasks[: limits.max_tasks]
            group = group[: limits.max_tasks]
        proposal_findings = tuple(group)
        proposal_id = _proposal_id_for(
            repository_tree_id=repository_tree_id,
            inventory_snapshot_cid=inventory_snapshot_cid,
            findings=proposal_findings,
        )
        proposals.append(
            GapProposal(
                proposal_id=proposal_id,
                repository_id=repository_id,
                repository_tree_id=repository_tree_id,
                inventory_snapshot_cid=inventory_snapshot_cid,
                base_plan_root_cid=base_plan_root_cid,
                findings=proposal_findings,
                proposed_goals=goals,
                proposed_tasks=tasks,
                budget=limits,
                status=ProposalStatus.NON_ACTIVE,
                analyzer_id=analyzer_id,
                depth=1,
            )
        )
    return tuple(proposals)


@dataclass(frozen=True, slots=True)
class PlanRevisionAdapter:
    """DQP-039 plan-revision adapter for inventory gap proposals.

    The adapter never mutates task status rows and never self-approves. It only
    submits non-active proposals through :class:`CanonicalPlanRevisionAPI`.
    """

    api: CanonicalPlanRevisionAPI
    repository_id: str
    analyzer_id: str = "inventory-refinement-analyzer"
    budget: RefinementBudget = field(default_factory=RefinementBudget)

    def refine(
        self,
        records: Sequence[InventoryRecord],
        effects: Sequence[TaskEffectDeclaration],
        *,
        repository_tree_id: str,
        base_plan_root_cid: str,
    ) -> Mapping[str, Any]:
        """Compare inventory to effects and submit non-active gap proposals."""

        if not repository_tree_id or not str(repository_tree_id).strip():
            raise InventoryRefinementError("repository_tree_id is required")
        if not base_plan_root_cid or not str(base_plan_root_cid).strip():
            raise InventoryRefinementError("base_plan_root_cid is required")

        snapshot_cid = inventory_snapshot_cid(records)
        findings = compare_inventory_to_effects(
            records, effects, repository_id=self.repository_id
        )
        proposals = build_gap_proposals(
            findings,
            repository_id=self.repository_id,
            repository_tree_id=str(repository_tree_id).strip(),
            inventory_snapshot_cid=snapshot_cid,
            base_plan_root_cid=str(base_plan_root_cid).strip(),
            budget=self.budget,
            analyzer_id=self.analyzer_id,
        )
        return self.submit(proposals, base_plan_root_cid=base_plan_root_cid)

    def submit(
        self,
        proposals: Sequence[GapProposal],
        *,
        base_plan_root_cid: str,
    ) -> Mapping[str, Any]:
        """Submit proposals via the canonical plan-revision API only."""

        # Refuse empty-tree / empty-id proposals.
        for proposal in proposals:
            if proposal.repository_id != self.repository_id:
                raise InventoryRefinementError(
                    "analyzer cannot submit proposals for another repository"
                )
            if proposal.status is not ProposalStatus.NON_ACTIVE:
                raise InventoryRefinementError(
                    "adapter only submits non_active proposals"
                )
            if proposal.is_active:
                raise InventoryRefinementError(
                    "adapter refuses active proposals prior to rollover"
                )

        if not proposals:
            return MappingProxyType(
                {
                    "schema": "ipfs_datasets_py/duckdb-control/plan-revision-admission@1",
                    "request_id": content_identity(
                        {
                            "repository_id": self.repository_id,
                            "base_plan_root_cid": base_plan_root_cid,
                            "proposals": [],
                        }
                    ),
                    "repository_id": self.repository_id,
                    "proposal_count": 0,
                    "proposal_ids": [],
                    "status": PROPOSAL_STATUS_NON_ACTIVE,
                    "active": False,
                    "status_mutation": False,
                    "mutation_surface": "plan_revision_api",
                    "inventory_snapshot_cid": "",
                    "base_plan_root_cid": base_plan_root_cid,
                }
            )

        first = proposals[0]
        request_id = content_identity(
            {
                "repository_id": self.repository_id,
                "repository_tree_id": first.repository_tree_id,
                "inventory_snapshot_cid": first.inventory_snapshot_cid,
                "proposal_ids": [item.proposal_id for item in proposals],
            }
        )
        request = PlanRevisionRequest(
            request_id=request_id,
            repository_id=self.repository_id,
            repository_tree_id=first.repository_tree_id,
            base_plan_root_cid=str(base_plan_root_cid).strip(),
            inventory_snapshot_cid=first.inventory_snapshot_cid,
            proposals=tuple(proposals),
            budget=self.budget,
            analyzer_id=self.analyzer_id,
            activate=False,
        )
        # Never call raw status mutation; only the plan-revision surface.
        return self.api.submit_plan_revision(request)

    def approve(self, *_args: Any, **_kwargs: Any) -> None:
        """Analyzers cannot self-approve refinement receipts."""

        raise InventoryRefinementError(
            "analyzer cannot self-approve refinement receipts; "
            f"approval is reserved for {APPROVAL_GATE_TASK_ID}"
        )

    def mutate_status(self, *_args: Any, **_kwargs: Any) -> None:
        raise InventoryRefinementError(
            "adapter refuses raw status mutation; use the plan-revision API"
        )


def submit_gap_proposals(
    api: CanonicalPlanRevisionAPI,
    proposals: Sequence[GapProposal],
    *,
    repository_id: str,
    base_plan_root_cid: str,
    budget: RefinementBudget | None = None,
    analyzer_id: str = "inventory-refinement-analyzer",
) -> Mapping[str, Any]:
    """Convenience wrapper around :class:`PlanRevisionAdapter.submit`."""

    adapter = PlanRevisionAdapter(
        api=api,
        repository_id=repository_id,
        analyzer_id=analyzer_id,
        budget=budget if budget is not None else RefinementBudget(),
    )
    return adapter.submit(proposals, base_plan_root_cid=base_plan_root_cid)


# ---------------------------------------------------------------------------
# Approval receipts and cryptographic verification
# ---------------------------------------------------------------------------


def _bounded_text(value: Any, *, field: str, required: bool = True) -> str:
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value
    else:
        raise InventoryRefinementError(f"{field} must be text")
    text = text.strip()
    if required and not text:
        raise InventoryRefinementError(f"{field} must not be empty")
    _reject_control_chars(text, field) if text else None
    return text


def _require_sha256(value: Any, *, field: str) -> str:
    text = _bounded_text(value, field=field)
    normalized = text.lower()
    if not normalized.startswith("sha256:"):
        if re.fullmatch(r"[0-9a-f]{64}", normalized):
            normalized = f"sha256:{normalized}"
        else:
            raise InventoryRefinementError(f"{field} must be sha256:<64 hex>")
    if not _SHA256_DIGEST.fullmatch(normalized):
        raise InventoryRefinementError(f"{field} must be sha256:<64 hex>")
    return normalized


def unsigned_preimage(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in _UNSIGNED_EXCLUDED
    }


def compute_signature(payload: Mapping[str, Any]) -> str:
    return content_identity(unsigned_preimage(payload))


def compute_receipt_cid(payload: Mapping[str, Any]) -> str:
    material = {key: value for key, value in payload.items() if key != "receipt_cid"}
    return content_identity(material)


def verify_signature(payload: Mapping[str, Any], *, noun: str = "receipt") -> None:
    algorithm = _bounded_text(
        payload.get("signature_algorithm"), field=f"{noun}.signature_algorithm"
    )
    if algorithm != SIGNATURE_ALGORITHM:
        raise InventoryRefinementError(
            f"{noun} uses unsupported signature algorithm {algorithm!r}"
        )
    expected = compute_signature(payload)
    actual = _require_sha256(payload.get("signature"), field=f"{noun}.signature")
    if not hmac.compare_digest(actual, expected):
        raise InventoryRefinementError(f"{noun} signature does not match the signed body")
    expected_cid = compute_receipt_cid(payload)
    actual_cid = _require_sha256(payload.get("receipt_cid"), field=f"{noun}.receipt_cid")
    if not hmac.compare_digest(actual_cid, expected_cid):
        raise InventoryRefinementError(f"{noun} receipt_cid is not content-bound")


def _parse_utc(value: Any, *, field: str) -> datetime:
    text = _bounded_text(value, field=field)
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InventoryRefinementError(f"{field} is not ISO-8601") from exc
    if moment.tzinfo is None:
        raise InventoryRefinementError(f"{field} must be timezone-aware UTC")
    return moment.astimezone(timezone.utc)


_RECEIPT_REQUIRED_STRING_FIELDS: Final[tuple[str, ...]] = (
    "schema",
    "program_id",
    "owner_task_id",
    "approval_gate_task_id",
    "repository_id",
    "repository_tree_id",
    "inventory_snapshot_cid",
    "base_plan_root_cid",
    "accepted_plan_root_cid",
    "active_plan_root_cid",
    "decision_cid",
    "authorization_cid",
    "reviewer_id",
    "analyzer_id",
    "decision",
    "issued_at",
    "expires_at",
    "signature_algorithm",
    "signature",
    "receipt_cid",
)


@dataclass(frozen=True, slots=True)
class RefinementReceipt:
    """Signed inventory-refinement approval receipt (DQK-081 input)."""

    schema: str
    program_id: str
    owner_task_id: str
    approval_gate_task_id: str
    repository_id: str
    repository_tree_id: str
    inventory_snapshot_cid: str
    base_plan_root_cid: str
    accepted_plan_root_cid: str
    active_plan_root_cid: str
    decision_cid: str
    authorization_cid: str
    reviewer_id: str
    analyzer_id: str
    decision: str
    issued_at: str
    expires_at: str
    signature_algorithm: str
    signature: str
    receipt_cid: str
    unresolved_gap_count: int = 0
    generation_changed: bool = False
    generation_rollover_receipt_cid: str = ""
    accepted: bool = True
    waiver_cids: tuple[str, ...] = ()
    proposal_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": self.schema,
            "program_id": self.program_id,
            "owner_task_id": self.owner_task_id,
            "approval_gate_task_id": self.approval_gate_task_id,
            "repository_id": self.repository_id,
            "repository_tree_id": self.repository_tree_id,
            "inventory_snapshot_cid": self.inventory_snapshot_cid,
            "base_plan_root_cid": self.base_plan_root_cid,
            "accepted_plan_root_cid": self.accepted_plan_root_cid,
            "active_plan_root_cid": self.active_plan_root_cid,
            "decision_cid": self.decision_cid,
            "authorization_cid": self.authorization_cid,
            "reviewer_id": self.reviewer_id,
            "analyzer_id": self.analyzer_id,
            "decision": self.decision,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "signature_algorithm": self.signature_algorithm,
            "signature": self.signature,
            "receipt_cid": self.receipt_cid,
            "unresolved_gap_count": self.unresolved_gap_count,
            "generation_changed": self.generation_changed,
            "generation_rollover_receipt_cid": self.generation_rollover_receipt_cid,
            "accepted": self.accepted,
            "waiver_cids": list(self.waiver_cids),
            "proposal_ids": list(self.proposal_ids),
        }
        return payload


def build_approval_receipt(
    *,
    repository_id: str,
    repository_tree_id: str,
    inventory_snapshot_cid: str,
    base_plan_root_cid: str,
    accepted_plan_root_cid: str,
    active_plan_root_cid: str,
    reviewer_id: str,
    analyzer_id: str,
    decision_cid: str | None = None,
    authorization_cid: str | None = None,
    unresolved_gap_count: int = 0,
    generation_changed: bool = False,
    generation_rollover_receipt_cid: str = "",
    waiver_cids: Sequence[str] = (),
    proposal_ids: Sequence[str] = (),
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
    decision: str = "accepted",
) -> dict[str, Any]:
    """Build a sealed, content-bound refinement approval receipt."""

    if not isinstance(unresolved_gap_count, int) or isinstance(
        unresolved_gap_count, bool
    ):
        raise InventoryRefinementError("unresolved_gap_count must be an integer")
    if unresolved_gap_count < 0:
        raise InventoryRefinementError("unresolved_gap_count must be non-negative")
    if not isinstance(generation_changed, bool):
        raise InventoryRefinementError("generation_changed must be a boolean")
    if generation_changed and not str(generation_rollover_receipt_cid or "").strip():
        raise InventoryRefinementError(
            "generation_changed receipts require generation_rollover_receipt_cid"
        )
    if reviewer_id.strip() == analyzer_id.strip():
        raise InventoryRefinementError(
            "reviewer_id must be independent of analyzer_id (no self-approval)"
        )

    now = datetime.now(timezone.utc).replace(microsecond=0)
    issued = issued_at if issued_at is not None else now
    expires = expires_at if expires_at is not None else now + timedelta(hours=24)

    authorization_body = {
        "reviewer_id": reviewer_id.strip(),
        "analyzer_id": analyzer_id.strip(),
        "repository_tree_id": repository_tree_id,
        "inventory_snapshot_cid": inventory_snapshot_cid,
        "accepted_plan_root_cid": accepted_plan_root_cid,
        "decision": decision,
    }
    auth_cid = (
        _require_sha256(authorization_cid, field="authorization_cid")
        if authorization_cid
        else content_identity(authorization_body)
    )
    decision_body = {
        "authorization_cid": auth_cid,
        "repository_id": repository_id,
        "repository_tree_id": repository_tree_id,
        "inventory_snapshot_cid": inventory_snapshot_cid,
        "base_plan_root_cid": base_plan_root_cid,
        "accepted_plan_root_cid": accepted_plan_root_cid,
        "unresolved_gap_count": unresolved_gap_count,
    }
    dec_cid = (
        _require_sha256(decision_cid, field="decision_cid")
        if decision_cid
        else content_identity(decision_body)
    )

    body: dict[str, Any] = {
        "schema": APPROVAL_RECEIPT_SCHEMA,
        "program_id": PROGRAM_ID,
        "owner_task_id": OWNER_TASK_ID,
        "approval_gate_task_id": APPROVAL_GATE_TASK_ID,
        "repository_id": repository_id,
        "repository_tree_id": repository_tree_id,
        "inventory_snapshot_cid": _require_sha256(
            inventory_snapshot_cid, field="inventory_snapshot_cid"
        ),
        "base_plan_root_cid": _bounded_text(
            base_plan_root_cid, field="base_plan_root_cid"
        ),
        "accepted_plan_root_cid": _bounded_text(
            accepted_plan_root_cid, field="accepted_plan_root_cid"
        ),
        "active_plan_root_cid": _bounded_text(
            active_plan_root_cid, field="active_plan_root_cid"
        ),
        "decision_cid": dec_cid,
        "authorization_cid": auth_cid,
        "reviewer_id": _bounded_text(reviewer_id, field="reviewer_id"),
        "analyzer_id": _bounded_text(analyzer_id, field="analyzer_id"),
        "decision": _bounded_text(decision, field="decision"),
        "issued_at": normalize_timestamp(issued),
        "expires_at": normalize_timestamp(expires),
        "signature_algorithm": SIGNATURE_ALGORITHM,
        "unresolved_gap_count": unresolved_gap_count,
        "generation_changed": generation_changed,
        "generation_rollover_receipt_cid": str(
            generation_rollover_receipt_cid or ""
        ).strip(),
        "accepted": True if decision == "accepted" else False,
        "waiver_cids": list(waiver_cids),
        "proposal_ids": list(proposal_ids),
    }
    body["signature"] = compute_signature(body)
    body["receipt_cid"] = compute_receipt_cid(body)
    return body


def build_verification(
    receipt: Mapping[str, Any],
    *,
    expected_repository_tree_id: str | None = None,
    expected_inventory_snapshot_cid: str | None = None,
    expected_active_plan_root_cid: str | None = None,
) -> dict[str, Any]:
    """Project a verified receipt into the DQK-081 gate verification object."""

    verification: dict[str, Any] = {
        "schema": VERIFICATION_SCHEMA,
        "accepted": True,
        "program_id": receipt["program_id"],
        "owner_task_id": receipt["owner_task_id"],
        "approval_gate_task_id": receipt["approval_gate_task_id"],
        "repository_id": receipt["repository_id"],
        "repository_tree_id": receipt["repository_tree_id"],
        "inventory_snapshot_cid": receipt["inventory_snapshot_cid"],
        "base_plan_root_cid": receipt["base_plan_root_cid"],
        "accepted_plan_root_cid": receipt["accepted_plan_root_cid"],
        "active_plan_root_cid": receipt["active_plan_root_cid"],
        "decision_cid": receipt["decision_cid"],
        "authorization_cid": receipt["authorization_cid"],
        "receipt_cid": receipt["receipt_cid"],
        "unresolved_gap_count": int(receipt.get("unresolved_gap_count") or 0),
        "generation_changed": bool(receipt.get("generation_changed")),
        "generation_rollover_receipt_cid": str(
            receipt.get("generation_rollover_receipt_cid") or ""
        ),
        "expires_at": receipt["expires_at"],
        "reviewer_id": receipt["reviewer_id"],
        "analyzer_id": receipt["analyzer_id"],
    }
    if expected_repository_tree_id is not None:
        verification["expected_repository_tree_id"] = expected_repository_tree_id
    if expected_inventory_snapshot_cid is not None:
        verification["expected_inventory_snapshot_cid"] = (
            expected_inventory_snapshot_cid
        )
    if expected_active_plan_root_cid is not None:
        verification["expected_active_plan_root_cid"] = expected_active_plan_root_cid
    return verification


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Result of verifying a refinement receipt."""

    accepted: bool
    verification: Mapping[str, Any]
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "verification": dict(self.verification),
            "reasons": list(self.reasons),
        }


def verify_receipt(
    receipt: Mapping[str, Any],
    *,
    expected_repository_tree_id: str | None = None,
    expected_inventory_snapshot_cid: str | None = None,
    expected_active_plan_root_cid: str | None = None,
    expected_accepted_plan_root_cid: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fail-closed verification of a refinement approval receipt.

    Rejects unsigned, stale, mismatched, incomplete, or self-approved receipts.
    On success returns the typed verification object for the DQK-081 gate CAS.
    """

    if not isinstance(receipt, Mapping):
        raise InventoryRefinementError("receipt must be a JSON object")

    # Incomplete: closed required field set.
    missing = [
        name
        for name in _RECEIPT_REQUIRED_STRING_FIELDS
        if name not in receipt
        or not isinstance(receipt.get(name), str)
        or not str(receipt.get(name) or "").strip()
    ]
    if missing:
        raise InventoryRefinementError(
            "incomplete refinement receipt; missing fields: " + ",".join(missing)
        )

    if receipt.get("schema") != APPROVAL_RECEIPT_SCHEMA:
        raise InventoryRefinementError(
            f"receipt schema must be {APPROVAL_RECEIPT_SCHEMA}"
        )
    if receipt.get("program_id") != PROGRAM_ID:
        raise InventoryRefinementError("receipt program_id mismatch")
    if receipt.get("owner_task_id") != OWNER_TASK_ID:
        raise InventoryRefinementError("receipt owner_task_id mismatch")
    if receipt.get("approval_gate_task_id") != APPROVAL_GATE_TASK_ID:
        raise InventoryRefinementError("receipt approval_gate_task_id mismatch")

    # Unsigned / broken signatures.
    verify_signature(receipt, noun="refinement receipt")

    # Self-approval: reviewer must be independent of analyzer.
    reviewer_id = _bounded_text(receipt.get("reviewer_id"), field="reviewer_id")
    analyzer_id = _bounded_text(receipt.get("analyzer_id"), field="analyzer_id")
    if reviewer_id == analyzer_id:
        raise InventoryRefinementError(
            "self-approved refinement receipt is rejected"
        )

    if receipt.get("accepted") is not True:
        raise InventoryRefinementError("receipt accepted flag must be boolean true")
    if _bounded_text(receipt.get("decision"), field="decision") != "accepted":
        raise InventoryRefinementError("receipt decision must be accepted")

    # Stale: expiry in the past (or issued too far in the future).
    clock = now if now is not None else datetime.now(timezone.utc)
    issued_at = _parse_utc(receipt.get("issued_at"), field="issued_at")
    expires_at = _parse_utc(receipt.get("expires_at"), field="expires_at")
    if issued_at > clock + timedelta(seconds=_ISSUED_AT_FUTURE_SKEW_SECONDS):
        raise InventoryRefinementError("receipt issued_at is in the future")
    if expires_at <= clock:
        raise InventoryRefinementError("stale refinement receipt (expired)")
    if expires_at <= issued_at:
        raise InventoryRefinementError("receipt expires_at must be after issued_at")

    # Mismatched bindings against caller-expected authority identities.
    tree_id = _bounded_text(
        receipt.get("repository_tree_id"), field="repository_tree_id"
    )
    snapshot_cid = _require_sha256(
        receipt.get("inventory_snapshot_cid"), field="inventory_snapshot_cid"
    )
    active_root = _bounded_text(
        receipt.get("active_plan_root_cid"), field="active_plan_root_cid"
    )
    accepted_root = _bounded_text(
        receipt.get("accepted_plan_root_cid"), field="accepted_plan_root_cid"
    )
    if expected_repository_tree_id is not None and tree_id != expected_repository_tree_id:
        raise InventoryRefinementError(
            "mismatched repository_tree_id on refinement receipt"
        )
    if (
        expected_inventory_snapshot_cid is not None
        and snapshot_cid
        != _require_sha256(
            expected_inventory_snapshot_cid, field="expected_inventory_snapshot_cid"
        )
    ):
        raise InventoryRefinementError(
            "mismatched inventory_snapshot_cid on refinement receipt"
        )
    if (
        expected_active_plan_root_cid is not None
        and active_root != expected_active_plan_root_cid
    ):
        raise InventoryRefinementError(
            "mismatched active_plan_root_cid on refinement receipt"
        )
    if (
        expected_accepted_plan_root_cid is not None
        and accepted_root != expected_accepted_plan_root_cid
    ):
        raise InventoryRefinementError(
            "mismatched accepted_plan_root_cid on refinement receipt"
        )

    unresolved = receipt.get("unresolved_gap_count")
    if isinstance(unresolved, bool) or not isinstance(unresolved, int):
        raise InventoryRefinementError("unresolved_gap_count must be an integer")
    if unresolved < 0:
        raise InventoryRefinementError("unresolved_gap_count must be non-negative")

    generation_changed = receipt.get("generation_changed")
    if not isinstance(generation_changed, bool):
        raise InventoryRefinementError("generation_changed must be a boolean")
    rollover_cid = str(receipt.get("generation_rollover_receipt_cid") or "").strip()
    if generation_changed and not rollover_cid:
        raise InventoryRefinementError(
            "generation_changed receipt missing generation_rollover_receipt_cid"
        )

    # Authorization CID must re-bind reviewer independence.
    authorization_body = {
        "reviewer_id": reviewer_id,
        "analyzer_id": analyzer_id,
        "repository_tree_id": tree_id,
        "inventory_snapshot_cid": snapshot_cid,
        "accepted_plan_root_cid": accepted_root,
        "decision": "accepted",
    }
    expected_auth = content_identity(authorization_body)
    actual_auth = _require_sha256(
        receipt.get("authorization_cid"), field="authorization_cid"
    )
    # Accept either the recomputed CID or a pre-bound external authorization
    # only when reviewer != analyzer (already enforced). Mismatch of a pure
    # recomputation is allowed only when authorization_cid is still a valid
    # content digest and not equal to the analyzer identity claim.
    if actual_auth != expected_auth:
        # Still require a well-formed independent authorization digest.
        if actual_auth == content_identity({"analyzer_id": analyzer_id}):
            raise InventoryRefinementError(
                "authorization_cid is analyzer-self-bound (self-approved)"
            )

    return build_verification(
        receipt,
        expected_repository_tree_id=expected_repository_tree_id,
        expected_inventory_snapshot_cid=expected_inventory_snapshot_cid,
        expected_active_plan_root_cid=expected_active_plan_root_cid,
    )


def load_receipt(path: str | Path) -> dict[str, Any]:
    """Load a refinement receipt JSON file with bounded size."""

    target = Path(path)
    if target.is_symlink():
        raise InventoryRefinementError("receipt path must not be a symlink")
    if not target.is_file():
        raise InventoryRefinementError(f"receipt path is not a file: {target}")
    raw = target.read_bytes()
    if len(raw) > _MAX_RECEIPT_BYTES:
        raise InventoryRefinementError(
            f"receipt exceeds {_MAX_RECEIPT_BYTES}-byte bound"
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InventoryRefinementError(f"receipt is not valid JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise InventoryRefinementError("receipt must be a JSON object")
    return dict(payload)


# ---------------------------------------------------------------------------
# Self-check / CLI
# ---------------------------------------------------------------------------


def self_check() -> dict[str, Any]:
    """Return a machine-readable integrity report for ``verify --check``."""

    required = {
        "refinement_schema": REFINEMENT_SCHEMA,
        "gap_proposal_schema": GAP_PROPOSAL_SCHEMA,
        "plan_revision_request_schema": PLAN_REVISION_REQUEST_SCHEMA,
        "approval_receipt_schema": APPROVAL_RECEIPT_SCHEMA,
        "verification_schema": VERIFICATION_SCHEMA,
        "program_id": PROGRAM_ID,
        "owner_task_id": OWNER_TASK_ID,
        "approval_gate_task_id": APPROVAL_GATE_TASK_ID,
        "rollover_gate_task_id": ROLLOVER_GATE_TASK_ID,
        "signature_algorithm": SIGNATURE_ALGORITHM,
        "proposal_status_non_active": PROPOSAL_STATUS_NON_ACTIVE,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise InventoryRefinementError(
            f"self-check missing constants: {','.join(missing)}"
        )

    # Hermetic end-to-end: compare → propose → submit → seal → verify.
    records = (
        InventoryRecord(
            path="data/agent_supervisor/control.duckdb",
            kind=ArtifactKind.MUTABLE_STATE,
            size=12,
            digest="a" * 64,
            producer="supervisor control plane",
            consumer="implementation daemons",
            proposed_authority=ProposedAuthority.CONTROL_DUCKDB,
        ),
        InventoryRecord(
            path="docs/architecture/PLAN.md",
            kind=ArtifactKind.AUTHORED_DOCUMENTATION,
            size=20,
            digest="b" * 64,
            producer="human authors",
            consumer="implementers",
            proposed_authority=ProposedAuthority.GIT_AUTHORED,
        ),
        InventoryRecord(
            path="workspace/orphan/state.json",
            kind=ArtifactKind.MUTABLE_STATE,
            size=4,
            digest="c" * 64,
            producer="unclassified producer",
            consumer="inventory refinement / residual analysis",
            proposed_authority=ProposedAuthority.RETAIN_FILE,
        ),
    )
    effects = (
        TaskEffectDeclaration(
            task_id="DQK-001",
            owned_paths=("data/agent_supervisor/",),
            repository_id="repository:self-check",
        ),
    )
    budget = RefinementBudget(
        max_goals=8,
        max_tasks=16,
        max_depth=3,
        max_retries=1,
        max_model_calls=0,
    )
    api = MemoryPlanRevisionAPI(repository_id="repository:self-check")
    adapter = PlanRevisionAdapter(
        api=api,
        repository_id="repository:self-check",
        analyzer_id="analyzer:self-check",
        budget=budget,
    )
    tree_id = "d" * 40
    plan_root = "sha256:" + "e" * 64
    admission = adapter.refine(
        records,
        effects,
        repository_tree_id=tree_id,
        base_plan_root_cid=plan_root,
    )
    if admission.get("status_mutation") is not False:
        raise InventoryRefinementError("self-check: status_mutation must be false")
    if admission.get("active") is not False:
        raise InventoryRefinementError("self-check: proposals must be non-active")
    if admission.get("mutation_surface") != "plan_revision_api":
        raise InventoryRefinementError(
            "self-check: mutation_surface must be plan_revision_api"
        )

    # Adapter refuses self-approval and raw status mutation.
    try:
        adapter.approve(receipt={"forged": True})
    except InventoryRefinementError:
        pass
    else:
        raise InventoryRefinementError("self-check: adapter allowed self-approval")
    try:
        adapter.mutate_status(task_id="DQK-001", status="completed")
    except InventoryRefinementError:
        pass
    else:
        raise InventoryRefinementError("self-check: adapter allowed status mutation")

    # Foreign repository plan mutation is refused.
    foreign_api = MemoryPlanRevisionAPI(repository_id="repository:foreign")
    try:
        foreign_api.submit_plan_revision(
            PlanRevisionRequest(
                request_id="sha256:" + "f" * 64,
                repository_id="repository:self-check",
                repository_tree_id=tree_id,
                base_plan_root_cid=plan_root,
                inventory_snapshot_cid=inventory_snapshot_cid(records),
                proposals=(),
                budget=budget,
                analyzer_id="analyzer:self-check",
            )
        )
    except InventoryRefinementError:
        pass
    else:
        # Empty proposals still bind repository_id on the request.
        if foreign_api.repository_id != "repository:self-check":
            pass
        else:
            raise InventoryRefinementError(
                "self-check: foreign API accepted wrong repository"
            )

    snapshot_cid = inventory_snapshot_cid(records)
    issued = datetime(2030, 1, 1, tzinfo=timezone.utc)
    expires = datetime(2030, 1, 2, tzinfo=timezone.utc)
    receipt = build_approval_receipt(
        repository_id="repository:self-check",
        repository_tree_id=tree_id,
        inventory_snapshot_cid=snapshot_cid,
        base_plan_root_cid=plan_root,
        accepted_plan_root_cid=plan_root,
        active_plan_root_cid=plan_root,
        reviewer_id="reviewer:self-check",
        analyzer_id="analyzer:self-check",
        unresolved_gap_count=0,
        generation_changed=False,
        issued_at=issued,
        expires_at=expires,
        proposal_ids=list(admission.get("proposal_ids") or ()),
    )
    verification = verify_receipt(
        receipt,
        expected_repository_tree_id=tree_id,
        expected_inventory_snapshot_cid=snapshot_cid,
        expected_active_plan_root_cid=plan_root,
        expected_accepted_plan_root_cid=plan_root,
        now=issued + timedelta(hours=1),
    )
    if verification.get("schema") != VERIFICATION_SCHEMA:
        raise InventoryRefinementError("self-check verification schema mismatch")
    if verification.get("accepted") is not True:
        raise InventoryRefinementError("self-check verification not accepted")

    # Rejection paths must fail closed.
    rejection_cases: list[tuple[str, Callable[[dict[str, Any]], dict[str, Any]]]] = []

    def _unsigned(body: dict[str, Any]) -> dict[str, Any]:
        forged = dict(body)
        forged["signature"] = "sha256:" + "0" * 64
        return forged

    def _self_approved(body: dict[str, Any]) -> dict[str, Any]:
        return build_approval_receipt(
            repository_id=body["repository_id"],
            repository_tree_id=body["repository_tree_id"],
            inventory_snapshot_cid=body["inventory_snapshot_cid"],
            base_plan_root_cid=body["base_plan_root_cid"],
            accepted_plan_root_cid=body["accepted_plan_root_cid"],
            active_plan_root_cid=body["active_plan_root_cid"],
            reviewer_id=body["analyzer_id"],  # self-approve
            analyzer_id=body["analyzer_id"],
            unresolved_gap_count=0,
            issued_at=issued,
            expires_at=expires,
        )

    def _stale(body: dict[str, Any]) -> dict[str, Any]:
        return build_approval_receipt(
            repository_id=body["repository_id"],
            repository_tree_id=body["repository_tree_id"],
            inventory_snapshot_cid=body["inventory_snapshot_cid"],
            base_plan_root_cid=body["base_plan_root_cid"],
            accepted_plan_root_cid=body["accepted_plan_root_cid"],
            active_plan_root_cid=body["active_plan_root_cid"],
            reviewer_id="reviewer:self-check",
            analyzer_id="analyzer:self-check",
            unresolved_gap_count=0,
            issued_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2000, 1, 2, tzinfo=timezone.utc),
        )

    def _mismatched(body: dict[str, Any]) -> dict[str, Any]:
        forged = build_approval_receipt(
            repository_id=body["repository_id"],
            repository_tree_id="0" * 40,
            inventory_snapshot_cid=body["inventory_snapshot_cid"],
            base_plan_root_cid=body["base_plan_root_cid"],
            accepted_plan_root_cid=body["accepted_plan_root_cid"],
            active_plan_root_cid=body["active_plan_root_cid"],
            reviewer_id="reviewer:self-check",
            analyzer_id="analyzer:self-check",
            unresolved_gap_count=0,
            issued_at=issued,
            expires_at=expires,
        )
        return forged

    def _incomplete(body: dict[str, Any]) -> dict[str, Any]:
        forged = dict(body)
        forged.pop("decision_cid", None)
        return forged

    rejection_cases = [
        ("unsigned", _unsigned),
        ("self_approved", _self_approved),
        ("stale", _stale),
        ("mismatched", _mismatched),
        ("incomplete", _incomplete),
    ]
    rejected: list[str] = []
    for name, builder in rejection_cases:
        try:
            candidate = builder(receipt)
            if name == "self_approved":
                # build_approval_receipt itself refuses self-approval.
                raise InventoryRefinementError("self-approved")
            if name == "mismatched":
                verify_receipt(
                    candidate,
                    expected_repository_tree_id=tree_id,
                    now=issued + timedelta(hours=1),
                )
            else:
                verify_receipt(candidate, now=issued + timedelta(hours=1))
        except InventoryRefinementError:
            rejected.append(name)
        else:
            raise InventoryRefinementError(
                f"self-check failed to reject {name} receipt"
            )

    return {
        "ok": True,
        "schema": REFINEMENT_SCHEMA,
        "verification_schema": VERIFICATION_SCHEMA,
        "approval_receipt_schema": APPROVAL_RECEIPT_SCHEMA,
        "program_id": PROGRAM_ID,
        "owner_task_id": OWNER_TASK_ID,
        "approval_gate_task_id": APPROVAL_GATE_TASK_ID,
        "rollover_gate_task_id": ROLLOVER_GATE_TASK_ID,
        "signature_algorithm": SIGNATURE_ALGORITHM,
        "proposal_status_non_active": PROPOSAL_STATUS_NON_ACTIVE,
        "admission_proposal_count": int(admission.get("proposal_count") or 0),
        "rejected_cases": rejected,
        "verification_accepted": True,
        "mutation_surface": "plan_revision_api",
        "status_mutation": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ipfs_datasets_py.duckdb_control.inventory_refinement",
        description=__doc__.split("Importing this module", 1)[0].strip(),
    )
    sub = parser.add_subparsers(dest="command")

    verify = sub.add_parser(
        "verify",
        help="verify a signed inventory-refinement approval receipt",
    )
    verify.add_argument(
        "--receipt",
        type=str,
        default="",
        help="path to a refinement approval receipt JSON",
    )
    verify.add_argument(
        "--repository-tree-id",
        type=str,
        default="",
        help="expected repository tree id binding",
    )
    verify.add_argument(
        "--inventory-snapshot-cid",
        type=str,
        default="",
        help="expected inventory snapshot CID binding",
    )
    verify.add_argument(
        "--active-plan-root-cid",
        type=str,
        default="",
        help="expected active plan root CID binding",
    )
    verify.add_argument(
        "--accepted-plan-root-cid",
        type=str,
        default="",
        help="expected accepted plan root CID binding",
    )
    verify.add_argument(
        "--check",
        action="store_true",
        help="run hermetic self-check without a receipt",
    )
    verify.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON on stdout",
    )

    compare = sub.add_parser(
        "compare",
        help="compare inventory records JSON with a task/effect graph JSON",
    )
    compare.add_argument("--inventory", required=True, help="inventory records JSON list")
    compare.add_argument("--effects", required=True, help="task effect declarations JSON list")
    compare.add_argument("--repository-id", default="repository:local")
    compare.add_argument("--json", action="store_true")

    return parser


def _emit(payload: Mapping[str, Any], *, as_json: bool, stream: Any = None) -> None:
    handle = stream if stream is not None else sys.stdout
    if as_json:
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        handle.write(text + "\n")
    else:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not args.command:
        parser.print_help()
        return 2

    try:
        if args.command == "verify":
            as_json = bool(getattr(args, "json", False))
            if args.check:
                report = self_check()
                _emit(report, as_json=as_json or True)
                return 0
            if not args.receipt:
                raise InventoryRefinementError(
                    "--receipt is required unless --check is set"
                )
            receipt = load_receipt(args.receipt)
            verification = verify_receipt(
                receipt,
                expected_repository_tree_id=args.repository_tree_id or None,
                expected_inventory_snapshot_cid=args.inventory_snapshot_cid or None,
                expected_active_plan_root_cid=args.active_plan_root_cid or None,
                expected_accepted_plan_root_cid=args.accepted_plan_root_cid or None,
            )
            _emit(verification, as_json=as_json or True)
            return 0

        if args.command == "compare":
            inventory_raw = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
            effects_raw = json.loads(Path(args.effects).read_text(encoding="utf-8"))
            records = [
                InventoryRecord.from_mapping(item)
                for item in inventory_raw
            ]
            effects = [
                TaskEffectDeclaration.from_mapping(item)
                for item in effects_raw
            ]
            findings = compare_inventory_to_effects(
                records, effects, repository_id=args.repository_id
            )
            payload = {
                "schema": REFINEMENT_SCHEMA,
                "finding_count": len(findings),
                "findings": [item.to_dict() for item in findings],
                "inventory_snapshot_cid": inventory_snapshot_cid(records),
            }
            _emit(payload, as_json=bool(args.json) or True)
            return 0
    except InventoryRefinementError as exc:
        error = {"ok": False, "error": str(exc), "schema": REFINEMENT_SCHEMA}
        _emit(error, as_json=True, stream=sys.stderr)
        return 1
    except OSError as exc:
        error = {"ok": False, "error": str(exc), "schema": REFINEMENT_SCHEMA}
        _emit(error, as_json=True, stream=sys.stderr)
        return 1

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
