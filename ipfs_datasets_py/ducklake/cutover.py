"""DuckLake authority promotion and legacy-manifest cutover controls (DQK-100).

Implements the **fenced command, verifier, dry-run, rollback, and receipt
schema** that *can* make the admitted lake registry and snapshot receipts
authoritative for integrated Parquet producers and disable mutable sidecar
manifests plus implicit directory scans.

Critical non-goals of this implementation task:

* Completing DQK-100 does **not** alter production authority.
* Completing DQK-100 does **not** disable any legacy producer.
* Implementation-task completion grants **no** authority and changes **no**
  runtime authority.
* Production promotion remains held behind an unexpired, independently signed
  DQK-102 decision plus exact process-birth / generation fences and current
  canary / recovery / security evidence at the point of use.

Inventory admission for cutover requires either:

1. a fresh exact-HEAD producer scan, or
2. a signed baseline plus a complete content-addressed delta through HEAD.

Stale baselines, incomplete deltas, or new / changed / unowned producer gaps
cannot authorize promotion; gaps route to governed DQK-081 plan revision and
DQK-083 generation rollover rather than retrying a stale generation.

Importing this module is inert: no DuckDB, network, or filesystem I/O until an
explicit cutover method is called. Process-local promotion state is for
hermetic / synthetic verification only and is reset on import / explicit reset.
"""

from __future__ import annotations

import hashlib
import sys
import json
import hmac
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import (
    Any,
    Final,
    Iterable,
    Mapping,
    Optional,
    Sequence,
)

from ipfs_datasets_py.duckdb_control.contracts import (
    content_identity,
    normalize_timestamp,
)
from ipfs_datasets_py.ducklake.adapters import (
    REGISTERED_PARQUET_PRODUCERS,
    ExactTreeInventoryProof,
    ProducerWaiver,
    UnownedProducerError,
    WaiverValidationError,
    build_exact_tree_inventory_proof,
    build_producer_waiver,
    digest_bytes,
    list_registered_producers,
    prove_zero_unowned_public_parquet_producers,
    verify_producer_waiver,
)
from ipfs_datasets_py.ducklake.security import ProcessBirth

__all__ = [
    "BASELINE_SCHEMA",
    "CUTOVER_COMMAND_SCHEMA",
    "CUTOVER_OWNER_TASK_ID",
    "DELTA_SCHEMA",
    "DOMAIN",
    "EVIDENCE_BUNDLE_SCHEMA",
    "EXECUTION_RECEIPT_SCHEMA",
    "GENERATION_ROLLOVER_TASK_ID",
    "IMPLEMENTATION_GRANTS_NO_AUTHORITY",
    "INVENTORY_SCAN_SCHEMA",
    "OWNER_TASK_ID",
    "PLAN_REVISION_TASK_ID",
    "PROGRAM_ID",
    "PROMOTION_DECISION_SCHEMA",
    "PROMOTION_GATE_TASK_ID",
    "ROLLBACK_RECEIPT_SCHEMA",
    "AuthorityCutoverError",
    "ContentAddressedDelta",
    "CutoverAuthorityMode",
    "CutoverBlockedError",
    "CutoverCommand",
    "CutoverController",
    "CutoverDryRunResult",
    "EvidenceBundle",
    "ExecutionReceipt",
    "ExactHeadProducerScan",
    "GenerationFence",
    "InventoryGap",
    "InventoryGapKind",
    "InventoryGapRouting",
    "LegacyProducerStillEnabledError",
    "PromotionDecision",
    "PromotionDecisionError",
    "RollbackReceipt",
    "SignedInventoryBaseline",
    "StaleBaselineError",
    "IncompleteDeltaError",
    "ProducerInventoryError",
    "apply_content_addressed_delta",
    "assert_query_discovery_authorized",
    "assert_source_content_addressed",
    "authority_mode",
    "build_content_addressed_delta",
    "build_evidence_bundle",
    "build_exact_head_scan",
    "build_generation_fence",
    "build_process_birth",
    "build_promotion_decision",
    "build_signed_baseline",
    "dry_run_cutover",
    "get_active_controller",
    "get_cutover_controller",
    "implicit_directory_scan_enabled",
    "implementation_self_check",
    "invoke_cutover",
    "is_lake_authority_active",
    "legacy_producers_enabled",
    "maybe_enforce_lake_discovery",
    "mutable_sidecar_authority_enabled",
    "production_authority_unchanged",
    "reset_cutover_state",
    "rollback_cutover",
    "route_inventory_gaps",
    "self_check",
    "set_active_controller",
    "verify_evidence_bundle",
    "verify_inventory_through_head",
    "verify_promotion_decision",
    "verify_waivers_current",
]


# ---------------------------------------------------------------------------
# Schema / constants
# ---------------------------------------------------------------------------

OWNER_TASK_ID: Final[str] = "DQK-100"
CUTOVER_OWNER_TASK_ID: Final[str] = OWNER_TASK_ID
PROMOTION_GATE_TASK_ID: Final[str] = "DQK-102"
PLAN_REVISION_TASK_ID: Final[str] = "DQK-081"
GENERATION_ROLLOVER_TASK_ID: Final[str] = "DQK-083"
PROGRAM_ID: Final[str] = "ipfs-datasets-duckdb-quack-control-plane-v1"
DOMAIN: Final[str] = "ducklake-authority-cutover"

# Completing DQK-100 never grants authority; constant is part of the public
# contract so callers and tests can assert it without side effects.
IMPLEMENTATION_GRANTS_NO_AUTHORITY: Final[bool] = True

PROMOTION_DECISION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/authority-cutover-promotion-decision@1"
)
EXECUTION_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/authority-cutover-execution-receipt@1"
)
ROLLBACK_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/authority-cutover-rollback-receipt@1"
)
INVENTORY_SCAN_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/authority-cutover-exact-head-scan@1"
)
BASELINE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/authority-cutover-signed-baseline@1"
)
DELTA_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/authority-cutover-content-addressed-delta@1"
)
EVIDENCE_BUNDLE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/authority-cutover-evidence-bundle@1"
)
CUTOVER_COMMAND_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/authority-cutover-command@1"
)

_SHA256_DIGEST: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_OID: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_SAFE_TOKEN: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$"
)
_MAX_FIELD_BYTES: Final[int] = 8192
_DEFAULT_DECISION_TTL_HOURS: Final[int] = 24
_DEFAULT_EVIDENCE_TTL_HOURS: Final[int] = 12
_DEFAULT_ROLLBACK_WINDOW_HOURS: Final[int] = 72

# Closed transition set for this cutover surface.
_ALLOWED_TRANSITIONS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("legacy", "lake_primary"),
        ("lake_primary", "legacy"),  # rollback only
    }
)

_THREAD_LOCAL = threading.local()
_STATE_LOCK = threading.RLock()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AuthorityCutoverError(ValueError):
    """Fail-closed rejection for cutover inputs, fences, or phases."""


class PromotionDecisionError(AuthorityCutoverError):
    """DQK-102 promotion decision is missing, expired, self-signed, or unbound."""


class CutoverBlockedError(AuthorityCutoverError):
    """Promotion refused without mutating authority."""

    def __init__(
        self,
        message: str,
        *,
        reason: str = "cutover_blocked",
        gap_routing: Mapping[str, Any] | None = None,
    ) -> None:
        self.reason = reason
        self.gap_routing = dict(gap_routing or {})
        super().__init__(message)


class StaleBaselineError(AuthorityCutoverError):
    """Signed inventory baseline is stale relative to HEAD or the delta start."""


class IncompleteDeltaError(AuthorityCutoverError):
    """Content-addressed delta does not complete the chain through HEAD."""


class ProducerInventoryError(AuthorityCutoverError):
    """Producer inventory is incomplete, changed, or has unowned gaps."""


class LegacyProducerStillEnabledError(AuthorityCutoverError):
    """Raised only by synthetic checks that expect lake-primary mode."""


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return normalize_timestamp(
        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )


def _parse_utc(value: Any, *, field: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise AuthorityCutoverError(f"{field} is required")
    # normalize_timestamp accepts datetime or str; re-parse ISO.
    normalized = normalize_timestamp(text)
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise AuthorityCutoverError(f"{field} is not a valid timestamp") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _bounded_text(
    value: Any,
    *,
    field: str,
    allow_empty: bool = False,
    max_bytes: int = _MAX_FIELD_BYTES,
) -> str:
    if not isinstance(value, str):
        raise AuthorityCutoverError(f"{field} must be text")
    text = value.strip()
    if not text and not allow_empty:
        raise AuthorityCutoverError(f"{field} must be nonempty")
    if len(text.encode("utf-8")) > max_bytes:
        raise AuthorityCutoverError(f"{field} exceeds {max_bytes}-byte bound")
    return text


def _require_sha256(value: Any, *, field: str) -> str:
    text = _bounded_text(value, field=field)
    if not _SHA256_DIGEST.fullmatch(text):
        raise AuthorityCutoverError(f"{field} must be sha256:<64-hex>")
    return text


def _require_tree_id(value: Any, *, field: str = "repository_tree_id") -> str:
    text = _bounded_text(value, field=field)
    if not _GIT_OID.fullmatch(text):
        raise AuthorityCutoverError(f"{field} must be a 40-char git tree oid")
    return text


def _require_safe_token(value: Any, *, field: str) -> str:
    text = _bounded_text(value, field=field)
    if not _SAFE_TOKEN.fullmatch(text):
        raise AuthorityCutoverError(f"{field} is not a safe token")
    return text


def _new_id(prefix: str) -> str:
    return f"{prefix}:{uuid.uuid4().hex}"


def _digest_of(payload: Any) -> str:
    return content_identity(payload)


def _hmac_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(str(a), str(b))


# ---------------------------------------------------------------------------
# Authority mode (process-local; default legacy)
# ---------------------------------------------------------------------------


class CutoverAuthorityMode(str, Enum):
    """Process-local discovery/query authority after a *synthetic* cutover.

    Production remains ``legacy`` until a real DQK-102 gate executes this
    command. Importing and completing DQK-100 never leaves legacy.
    """

    LEGACY = "legacy"
    LAKE_PRIMARY = "lake_primary"

    @classmethod
    def parse(cls, value: str | "CutoverAuthorityMode") -> "CutoverAuthorityMode":
        if isinstance(value, cls):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        try:
            return cls(text)
        except ValueError as exc:
            raise AuthorityCutoverError(
                f"unknown cutover authority mode {value!r}"
            ) from exc


@dataclass
class _ProcessLocalAuthorityState:
    """Hermetic process-local cutover state (never production)."""

    mode: CutoverAuthorityMode = CutoverAuthorityMode.LEGACY
    promoted_by_execution_id: str | None = None
    last_execution_receipt: Mapping[str, Any] | None = None
    last_rollback_receipt: Mapping[str, Any] | None = None
    decision_cid: str | None = None
    generation_id: str | None = None
    repository_tree_id: str | None = None
    # Explicit marker: implementation completion never sets this True.
    production_authority_mutated: bool = False


_PROCESS_STATE = _ProcessLocalAuthorityState()


def reset_cutover_state() -> None:
    """Reset process-local cutover authority to legacy (tests / dry harness)."""

    with _STATE_LOCK:
        _PROCESS_STATE.mode = CutoverAuthorityMode.LEGACY
        _PROCESS_STATE.promoted_by_execution_id = None
        _PROCESS_STATE.last_execution_receipt = None
        _PROCESS_STATE.last_rollback_receipt = None
        _PROCESS_STATE.decision_cid = None
        _PROCESS_STATE.generation_id = None
        _PROCESS_STATE.repository_tree_id = None
        _PROCESS_STATE.production_authority_mutated = False
        if hasattr(_THREAD_LOCAL, "controller"):
            delattr(_THREAD_LOCAL, "controller")


def authority_mode() -> CutoverAuthorityMode:
    with _STATE_LOCK:
        return _PROCESS_STATE.mode


def is_lake_authority_active() -> bool:
    return authority_mode() is CutoverAuthorityMode.LAKE_PRIMARY


def legacy_producers_enabled() -> bool:
    """Legacy producers remain enabled unless lake-primary is process-local active."""

    return not is_lake_authority_active()


def mutable_sidecar_authority_enabled() -> bool:
    """Mutable sidecar manifests remain discovery authority under legacy mode."""

    return not is_lake_authority_active()


def implicit_directory_scan_enabled() -> bool:
    """Implicit directory scans remain discovery authority under legacy mode."""

    return not is_lake_authority_active()


def production_authority_unchanged() -> bool:
    """True when no production authority mutation has occurred.

    Completing DQK-100 never sets production_authority_mutated. Synthetic
    hermetic promotions only flip process-local mode and leave this flag False.
    """

    with _STATE_LOCK:
        return (
            not _PROCESS_STATE.production_authority_mutated
            and IMPLEMENTATION_GRANTS_NO_AUTHORITY
        )


# ---------------------------------------------------------------------------
# Process birth + generation fences
# ---------------------------------------------------------------------------


def build_process_birth(
    *,
    process_id: str | None = None,
    boot_id: str | None = None,
    started_at: str | datetime | None = None,
    hostname: str = "",
    pid: int | None = None,
) -> ProcessBirth:
    """Build a process-birth identity for cutover fencing."""

    return ProcessBirth(
        process_id=process_id or _new_id("proc"),
        boot_id=boot_id or _new_id("boot"),
        started_at=normalize_timestamp(started_at or _utc_now()),
        hostname=hostname,
        pid=pid,
    )


@dataclass(frozen=True, slots=True)
class GenerationFence:
    """Exact active plan generation + repository tree fence for cutover."""

    generation_id: str
    repository_tree_id: str
    plan_root_cid: str
    catalog_owner_generation: int = 1
    retired: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "generation_id",
            _require_safe_token(self.generation_id, field="generation_id"),
        )
        object.__setattr__(
            self,
            "repository_tree_id",
            _require_tree_id(self.repository_tree_id),
        )
        object.__setattr__(
            self,
            "plan_root_cid",
            _require_sha256(self.plan_root_cid, field="plan_root_cid"),
        )
        if (
            not isinstance(self.catalog_owner_generation, int)
            or isinstance(self.catalog_owner_generation, bool)
            or self.catalog_owner_generation < 1
        ):
            raise AuthorityCutoverError(
                "catalog_owner_generation must be a positive int"
            )
        if self.retired:
            raise AuthorityCutoverError(
                "retired generation cannot authorize cutover; route through "
                f"{GENERATION_ROLLOVER_TASK_ID} generation rollover"
            )

    def fingerprint(self) -> str:
        return _digest_of(
            {
                "generation_id": self.generation_id,
                "repository_tree_id": self.repository_tree_id,
                "plan_root_cid": self.plan_root_cid,
                "catalog_owner_generation": self.catalog_owner_generation,
            }
        )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "generation_id": self.generation_id,
                "repository_tree_id": self.repository_tree_id,
                "plan_root_cid": self.plan_root_cid,
                "catalog_owner_generation": self.catalog_owner_generation,
                "retired": self.retired,
                "fingerprint": self.fingerprint(),
            }
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "GenerationFence":
        return cls(
            generation_id=str(payload.get("generation_id") or ""),
            repository_tree_id=str(payload.get("repository_tree_id") or ""),
            plan_root_cid=str(payload.get("plan_root_cid") or ""),
            catalog_owner_generation=int(
                payload.get("catalog_owner_generation") or 1
            ),
            retired=bool(payload.get("retired", False)),
        )


def build_generation_fence(
    *,
    generation_id: str,
    repository_tree_id: str,
    plan_root_cid: str,
    catalog_owner_generation: int = 1,
    retired: bool = False,
) -> GenerationFence:
    return GenerationFence(
        generation_id=generation_id,
        repository_tree_id=repository_tree_id,
        plan_root_cid=plan_root_cid,
        catalog_owner_generation=catalog_owner_generation,
        retired=retired,
    )


# ---------------------------------------------------------------------------
# Evidence bundle (canary / recovery / security)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    """Point-of-use canary, recovery, and security evidence binding."""

    schema: str
    evidence_set_cid: str
    canary_receipt_cid: str
    recovery_receipt_cid: str
    security_receipt_cid: str
    repository_tree_id: str
    generation_id: str
    issued_at: str
    expires_at: str
    signature: str
    program_id: str = PROGRAM_ID
    owner_task_id: str = OWNER_TASK_ID

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "canary_receipt_cid": self.canary_receipt_cid,
                "recovery_receipt_cid": self.recovery_receipt_cid,
                "security_receipt_cid": self.security_receipt_cid,
                "repository_tree_id": self.repository_tree_id,
                "generation_id": self.generation_id,
                "issued_at": self.issued_at,
                "expires_at": self.expires_at,
                "program_id": self.program_id,
                "owner_task_id": self.owner_task_id,
                "signature": self.signature,
                "evidence_set_cid": self.evidence_set_cid,
            }
        )


def _evidence_unsigned_body(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"signature", "evidence_set_cid"}
    }


def build_evidence_bundle(
    *,
    canary_receipt_cid: str,
    recovery_receipt_cid: str,
    security_receipt_cid: str,
    repository_tree_id: str,
    generation_id: str,
    issued_at: datetime | str | None = None,
    expires_at: datetime | str | None = None,
) -> EvidenceBundle:
    issued = normalize_timestamp(issued_at or _utc_now())
    if expires_at is None:
        exp_dt = _parse_utc(issued, field="issued_at") + timedelta(
            hours=_DEFAULT_EVIDENCE_TTL_HOURS
        )
        expires = normalize_timestamp(exp_dt)
    else:
        expires = normalize_timestamp(expires_at)
    if _parse_utc(expires, field="expires_at") <= _parse_utc(
        issued, field="issued_at"
    ):
        raise AuthorityCutoverError("evidence expires_at must be after issued_at")
    body = {
        "schema": EVIDENCE_BUNDLE_SCHEMA,
        "canary_receipt_cid": _require_sha256(
            canary_receipt_cid, field="canary_receipt_cid"
        ),
        "recovery_receipt_cid": _require_sha256(
            recovery_receipt_cid, field="recovery_receipt_cid"
        ),
        "security_receipt_cid": _require_sha256(
            security_receipt_cid, field="security_receipt_cid"
        ),
        "repository_tree_id": _require_tree_id(repository_tree_id),
        "generation_id": _require_safe_token(generation_id, field="generation_id"),
        "issued_at": issued,
        "expires_at": expires,
        "program_id": PROGRAM_ID,
        "owner_task_id": OWNER_TASK_ID,
    }
    signature = _digest_of(body)
    evidence_set_cid = _digest_of({**body, "signature": signature})
    return EvidenceBundle(
        schema=EVIDENCE_BUNDLE_SCHEMA,
        evidence_set_cid=evidence_set_cid,
        canary_receipt_cid=body["canary_receipt_cid"],
        recovery_receipt_cid=body["recovery_receipt_cid"],
        security_receipt_cid=body["security_receipt_cid"],
        repository_tree_id=body["repository_tree_id"],
        generation_id=body["generation_id"],
        issued_at=issued,
        expires_at=expires,
        signature=signature,
        program_id=PROGRAM_ID,
        owner_task_id=OWNER_TASK_ID,
    )


def verify_evidence_bundle(
    bundle: EvidenceBundle | Mapping[str, Any],
    *,
    now: datetime | None = None,
    expected_tree_id: str | None = None,
    expected_generation_id: str | None = None,
) -> EvidenceBundle:
    if isinstance(bundle, EvidenceBundle):
        mapping = dict(bundle.as_mapping())
    elif isinstance(bundle, Mapping):
        mapping = dict(bundle)
    else:
        raise AuthorityCutoverError("evidence bundle must be an object")
    if mapping.get("schema") != EVIDENCE_BUNDLE_SCHEMA:
        raise AuthorityCutoverError(
            f"evidence schema must be {EVIDENCE_BUNDLE_SCHEMA}"
        )
    for key in (
        "canary_receipt_cid",
        "recovery_receipt_cid",
        "security_receipt_cid",
        "repository_tree_id",
        "generation_id",
        "issued_at",
        "expires_at",
        "signature",
        "evidence_set_cid",
    ):
        if not str(mapping.get(key) or "").strip():
            raise AuthorityCutoverError(f"evidence missing field {key}")
    expected_sig = _digest_of(_evidence_unsigned_body(mapping))
    actual_sig = _require_sha256(mapping.get("signature"), field="evidence.signature")
    if not _hmac_eq(expected_sig, actual_sig):
        raise AuthorityCutoverError("evidence signature does not match body")
    expected_cid = _digest_of(
        {**_evidence_unsigned_body(mapping), "signature": actual_sig}
    )
    actual_cid = _require_sha256(
        mapping.get("evidence_set_cid"), field="evidence_set_cid"
    )
    if not _hmac_eq(expected_cid, actual_cid):
        raise AuthorityCutoverError("evidence_set_cid does not match signed body")
    clock = now or datetime.now(timezone.utc)
    expires = _parse_utc(mapping["expires_at"], field="expires_at")
    if clock >= expires:
        raise AuthorityCutoverError("evidence bundle is expired at point of use")
    tree = _require_tree_id(mapping["repository_tree_id"])
    if expected_tree_id is not None and tree != _require_tree_id(expected_tree_id):
        raise AuthorityCutoverError("evidence repository tree does not match fence")
    gen = _require_safe_token(mapping["generation_id"], field="generation_id")
    if expected_generation_id is not None and gen != _require_safe_token(
        expected_generation_id, field="expected_generation_id"
    ):
        raise AuthorityCutoverError("evidence generation does not match fence")
    return EvidenceBundle(
        schema=EVIDENCE_BUNDLE_SCHEMA,
        evidence_set_cid=actual_cid,
        canary_receipt_cid=_require_sha256(
            mapping["canary_receipt_cid"], field="canary_receipt_cid"
        ),
        recovery_receipt_cid=_require_sha256(
            mapping["recovery_receipt_cid"], field="recovery_receipt_cid"
        ),
        security_receipt_cid=_require_sha256(
            mapping["security_receipt_cid"], field="security_receipt_cid"
        ),
        repository_tree_id=tree,
        generation_id=gen,
        issued_at=normalize_timestamp(mapping["issued_at"]),
        expires_at=normalize_timestamp(mapping["expires_at"]),
        signature=actual_sig,
        program_id=str(mapping.get("program_id") or PROGRAM_ID),
        owner_task_id=str(mapping.get("owner_task_id") or OWNER_TASK_ID),
    )


# ---------------------------------------------------------------------------
# DQK-102 independently signed promotion decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    """Unexpired independently signed DQK-102 promotion decision.

    Bound to the exact actor / process birth, generation, repository tree,
    evidence set, and requested transition. The signer identity must be
    independent of the DQK-100 implementer and of the runtime actor.
    """

    schema: str
    decision_id: str
    decision_cid: str
    gate_task_id: str
    from_authority: str
    to_authority: str
    actor_identity: str
    implementer_identity: str
    signer_identity: str
    process_birth_fingerprint: str
    generation_fingerprint: str
    repository_tree_id: str
    evidence_set_cid: str
    inventory_proof_cid: str
    requested_transition: str
    issued_at: str
    expires_at: str
    rollback_window_hours: int
    signature: str
    signature_algorithm: str = "content-bound-sha256@1"
    accepted: bool = True
    program_id: str = PROGRAM_ID
    owner_task_id: str = OWNER_TASK_ID

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "decision_id": self.decision_id,
                "gate_task_id": self.gate_task_id,
                "from_authority": self.from_authority,
                "to_authority": self.to_authority,
                "actor_identity": self.actor_identity,
                "implementer_identity": self.implementer_identity,
                "signer_identity": self.signer_identity,
                "process_birth_fingerprint": self.process_birth_fingerprint,
                "generation_fingerprint": self.generation_fingerprint,
                "repository_tree_id": self.repository_tree_id,
                "evidence_set_cid": self.evidence_set_cid,
                "inventory_proof_cid": self.inventory_proof_cid,
                "requested_transition": self.requested_transition,
                "issued_at": self.issued_at,
                "expires_at": self.expires_at,
                "rollback_window_hours": self.rollback_window_hours,
                "accepted": self.accepted,
                "program_id": self.program_id,
                "owner_task_id": self.owner_task_id,
                "signature_algorithm": self.signature_algorithm,
                "signature": self.signature,
                "decision_cid": self.decision_cid,
            }
        )


def _decision_unsigned_body(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"signature", "decision_cid"}
    }


def build_promotion_decision(
    *,
    actor_identity: str,
    implementer_identity: str,
    signer_identity: str,
    process_birth: ProcessBirth | Mapping[str, Any],
    generation: GenerationFence | Mapping[str, Any],
    evidence: EvidenceBundle | Mapping[str, Any],
    inventory_proof_cid: str,
    from_authority: str = CutoverAuthorityMode.LEGACY.value,
    to_authority: str = CutoverAuthorityMode.LAKE_PRIMARY.value,
    decision_id: str | None = None,
    issued_at: datetime | str | None = None,
    expires_at: datetime | str | None = None,
    rollback_window_hours: int = _DEFAULT_ROLLBACK_WINDOW_HOURS,
    accepted: bool = True,
) -> PromotionDecision:
    """Build a sealed independently signed DQK-102 promotion decision.

    The *signer_identity* must differ from both *actor_identity* and
    *implementer_identity* (DQK-100 owner). Self-signed decisions are rejected
    at verify time.
    """

    birth = (
        process_birth
        if isinstance(process_birth, ProcessBirth)
        else ProcessBirth.from_mapping(process_birth)
    )
    fence = (
        generation
        if isinstance(generation, GenerationFence)
        else GenerationFence.from_mapping(generation)
    )
    evidence_obj = verify_evidence_bundle(
        evidence,
        expected_tree_id=fence.repository_tree_id,
        expected_generation_id=fence.generation_id,
    )
    from_mode = CutoverAuthorityMode.parse(from_authority).value
    to_mode = CutoverAuthorityMode.parse(to_authority).value
    # Promotion decisions are forward-only; rollback uses rollback_cutover.
    if (
        from_mode != CutoverAuthorityMode.LEGACY.value
        or to_mode != CutoverAuthorityMode.LAKE_PRIMARY.value
    ):
        raise PromotionDecisionError(
            f"promotion decision must request legacy->lake_primary, "
            f"got {from_mode!r} -> {to_mode!r}"
        )
    issued = normalize_timestamp(issued_at or _utc_now())
    if expires_at is None:
        exp_dt = _parse_utc(issued, field="issued_at") + timedelta(
            hours=_DEFAULT_DECISION_TTL_HOURS
        )
        expires = normalize_timestamp(exp_dt)
    else:
        expires = normalize_timestamp(expires_at)
    if _parse_utc(expires, field="expires_at") <= _parse_utc(
        issued, field="issued_at"
    ):
        raise PromotionDecisionError("decision expires_at must be after issued_at")
    if (
        not isinstance(rollback_window_hours, int)
        or isinstance(rollback_window_hours, bool)
        or rollback_window_hours < 1
    ):
        raise PromotionDecisionError("rollback_window_hours must be a positive int")

    actor = _require_safe_token(actor_identity, field="actor_identity")
    implementer = _require_safe_token(
        implementer_identity, field="implementer_identity"
    )
    signer = _require_safe_token(signer_identity, field="signer_identity")
    if signer == actor or signer == implementer:
        raise PromotionDecisionError(
            "DQK-102 decision must be signed by an identity independent of the "
            "DQK-100 implementer and the runtime actor"
        )
    requested = f"{from_mode}->{to_mode}"
    did = _require_safe_token(decision_id or _new_id("dec"), field="decision_id")
    body = {
        "schema": PROMOTION_DECISION_SCHEMA,
        "decision_id": did,
        "gate_task_id": PROMOTION_GATE_TASK_ID,
        "from_authority": from_mode,
        "to_authority": to_mode,
        "actor_identity": actor,
        "implementer_identity": implementer,
        "signer_identity": signer,
        "process_birth_fingerprint": birth.fingerprint(),
        "generation_fingerprint": fence.fingerprint(),
        "repository_tree_id": fence.repository_tree_id,
        "evidence_set_cid": evidence_obj.evidence_set_cid,
        "inventory_proof_cid": _require_sha256(
            inventory_proof_cid, field="inventory_proof_cid"
        ),
        "requested_transition": requested,
        "issued_at": issued,
        "expires_at": expires,
        "rollback_window_hours": int(rollback_window_hours),
        "accepted": bool(accepted),
        "program_id": PROGRAM_ID,
        "owner_task_id": OWNER_TASK_ID,
        "signature_algorithm": "content-bound-sha256@1",
    }
    # Independent signature material binds signer identity into the digest.
    signature = _digest_of({**body, "signer_binding": signer})
    decision_cid = _digest_of({**body, "signature": signature})
    return PromotionDecision(
        schema=PROMOTION_DECISION_SCHEMA,
        decision_id=did,
        decision_cid=decision_cid,
        gate_task_id=PROMOTION_GATE_TASK_ID,
        from_authority=from_mode,
        to_authority=to_mode,
        actor_identity=actor,
        implementer_identity=implementer,
        signer_identity=signer,
        process_birth_fingerprint=body["process_birth_fingerprint"],
        generation_fingerprint=body["generation_fingerprint"],
        repository_tree_id=body["repository_tree_id"],
        evidence_set_cid=body["evidence_set_cid"],
        inventory_proof_cid=body["inventory_proof_cid"],
        requested_transition=requested,
        issued_at=issued,
        expires_at=expires,
        rollback_window_hours=int(rollback_window_hours),
        signature=signature,
        signature_algorithm="content-bound-sha256@1",
        accepted=bool(accepted),
        program_id=PROGRAM_ID,
        owner_task_id=OWNER_TASK_ID,
    )


def verify_promotion_decision(
    decision: PromotionDecision | Mapping[str, Any],
    *,
    process_birth: ProcessBirth | Mapping[str, Any],
    generation: GenerationFence | Mapping[str, Any],
    evidence: EvidenceBundle | Mapping[str, Any],
    inventory_proof_cid: str,
    actor_identity: str,
    now: datetime | None = None,
    expected_transition: tuple[str, str] | None = None,
) -> PromotionDecision:
    """Fail-closed verification of an unexpired independently signed decision."""

    if isinstance(decision, PromotionDecision):
        mapping = dict(decision.as_mapping())
    elif isinstance(decision, Mapping):
        mapping = dict(decision)
    else:
        raise PromotionDecisionError("promotion decision must be an object")

    if mapping.get("schema") != PROMOTION_DECISION_SCHEMA:
        raise PromotionDecisionError(
            f"decision schema must be {PROMOTION_DECISION_SCHEMA}"
        )
    if mapping.get("gate_task_id") != PROMOTION_GATE_TASK_ID:
        raise PromotionDecisionError(
            f"decision gate_task_id must be {PROMOTION_GATE_TASK_ID}"
        )
    required = (
        "decision_id",
        "decision_cid",
        "from_authority",
        "to_authority",
        "actor_identity",
        "implementer_identity",
        "signer_identity",
        "process_birth_fingerprint",
        "generation_fingerprint",
        "repository_tree_id",
        "evidence_set_cid",
        "inventory_proof_cid",
        "requested_transition",
        "issued_at",
        "expires_at",
        "signature",
    )
    missing = [k for k in required if not str(mapping.get(k) or "").strip()]
    if missing:
        raise PromotionDecisionError(
            "incomplete promotion decision; missing: " + ",".join(missing)
        )
    if not bool(mapping.get("accepted", False)):
        raise PromotionDecisionError("promotion decision is not accepted")

    signer = _require_safe_token(mapping["signer_identity"], field="signer_identity")
    actor = _require_safe_token(mapping["actor_identity"], field="actor_identity")
    implementer = _require_safe_token(
        mapping["implementer_identity"], field="implementer_identity"
    )
    if signer == actor or signer == implementer:
        raise PromotionDecisionError(
            "DQK-102 decision must be signed by an identity independent of the "
            "DQK-100 implementer and the runtime actor"
        )
    expected_actor = _require_safe_token(actor_identity, field="actor_identity")
    if actor != expected_actor:
        raise PromotionDecisionError(
            "promotion decision actor_identity does not match runtime actor"
        )

    # Reconstruct the exact sealed unsigned body (stable key set / order).
    sealed_body = {
        "schema": mapping.get("schema") or PROMOTION_DECISION_SCHEMA,
        "decision_id": mapping["decision_id"],
        "gate_task_id": mapping.get("gate_task_id") or PROMOTION_GATE_TASK_ID,
        "from_authority": mapping["from_authority"],
        "to_authority": mapping["to_authority"],
        "actor_identity": actor,
        "implementer_identity": implementer,
        "signer_identity": signer,
        "process_birth_fingerprint": mapping["process_birth_fingerprint"],
        "generation_fingerprint": mapping["generation_fingerprint"],
        "repository_tree_id": mapping["repository_tree_id"],
        "evidence_set_cid": mapping["evidence_set_cid"],
        "inventory_proof_cid": mapping["inventory_proof_cid"],
        "requested_transition": mapping["requested_transition"],
        "issued_at": mapping["issued_at"],
        "expires_at": mapping["expires_at"],
        "rollback_window_hours": int(mapping.get("rollback_window_hours") or 1),
        "accepted": bool(mapping.get("accepted", False)),
        "program_id": mapping.get("program_id") or PROGRAM_ID,
        "owner_task_id": mapping.get("owner_task_id") or OWNER_TASK_ID,
        "signature_algorithm": str(
            mapping.get("signature_algorithm") or "content-bound-sha256@1"
        ),
    }
    expected_sig = _digest_of({**sealed_body, "signer_binding": signer})
    actual_sig = _require_sha256(mapping.get("signature"), field="decision.signature")
    if not _hmac_eq(expected_sig, actual_sig):
        raise PromotionDecisionError("promotion decision signature mismatch")
    expected_cid = _digest_of({**sealed_body, "signature": actual_sig})
    actual_cid = _require_sha256(mapping.get("decision_cid"), field="decision_cid")
    if not _hmac_eq(expected_cid, actual_cid):
        raise PromotionDecisionError("decision_cid does not match signed body")

    clock = now or datetime.now(timezone.utc)
    expires = _parse_utc(mapping["expires_at"], field="expires_at")
    if clock >= expires:
        raise PromotionDecisionError(
            "promotion decision is expired; unexpired DQK-102 decision required"
        )

    birth = (
        process_birth
        if isinstance(process_birth, ProcessBirth)
        else ProcessBirth.from_mapping(process_birth)
    )
    fence = (
        generation
        if isinstance(generation, GenerationFence)
        else GenerationFence.from_mapping(generation)
    )
    if mapping["process_birth_fingerprint"] != birth.fingerprint():
        raise PromotionDecisionError(
            "promotion decision is not bound to the exact process birth"
        )
    if mapping["generation_fingerprint"] != fence.fingerprint():
        raise PromotionDecisionError(
            "promotion decision is not bound to the exact generation fence"
        )
    tree = _require_tree_id(mapping["repository_tree_id"])
    if tree != fence.repository_tree_id:
        raise PromotionDecisionError(
            "promotion decision repository tree does not match generation fence"
        )

    evidence_obj = verify_evidence_bundle(
        evidence,
        now=clock,
        expected_tree_id=tree,
        expected_generation_id=fence.generation_id,
    )
    if mapping["evidence_set_cid"] != evidence_obj.evidence_set_cid:
        raise PromotionDecisionError(
            "promotion decision is not bound to the exact evidence set"
        )

    inv = _require_sha256(inventory_proof_cid, field="inventory_proof_cid")
    if mapping["inventory_proof_cid"] != inv:
        raise PromotionDecisionError(
            "promotion decision is not bound to the exact inventory proof"
        )

    from_mode = CutoverAuthorityMode.parse(mapping["from_authority"]).value
    to_mode = CutoverAuthorityMode.parse(mapping["to_authority"]).value
    requested = str(mapping["requested_transition"])
    if requested != f"{from_mode}->{to_mode}":
        raise PromotionDecisionError("requested_transition does not match authorities")
    if expected_transition is not None:
        exp_from, exp_to = expected_transition
        if from_mode != exp_from or to_mode != exp_to:
            raise PromotionDecisionError(
                "promotion decision requested transition does not match "
                f"expected {exp_from}->{exp_to}"
            )
    if (from_mode, to_mode) not in _ALLOWED_TRANSITIONS:
        raise PromotionDecisionError("transition is not allowed")

    return PromotionDecision(
        schema=PROMOTION_DECISION_SCHEMA,
        decision_id=_require_safe_token(mapping["decision_id"], field="decision_id"),
        decision_cid=actual_cid,
        gate_task_id=PROMOTION_GATE_TASK_ID,
        from_authority=from_mode,
        to_authority=to_mode,
        actor_identity=actor,
        implementer_identity=implementer,
        signer_identity=signer,
        process_birth_fingerprint=str(mapping["process_birth_fingerprint"]),
        generation_fingerprint=str(mapping["generation_fingerprint"]),
        repository_tree_id=tree,
        evidence_set_cid=str(mapping["evidence_set_cid"]),
        inventory_proof_cid=inv,
        requested_transition=requested,
        issued_at=normalize_timestamp(mapping["issued_at"]),
        expires_at=normalize_timestamp(mapping["expires_at"]),
        rollback_window_hours=int(mapping.get("rollback_window_hours") or 1),
        signature=actual_sig,
        signature_algorithm=str(
            mapping.get("signature_algorithm") or "content-bound-sha256@1"
        ),
        accepted=True,
        program_id=str(mapping.get("program_id") or PROGRAM_ID),
        owner_task_id=str(mapping.get("owner_task_id") or OWNER_TASK_ID),
    )


# ---------------------------------------------------------------------------
# Producer inventory: exact-HEAD scan OR signed baseline + complete delta
# ---------------------------------------------------------------------------


class InventoryGapKind(str, Enum):
    NEW_PRODUCER = "new_producer"
    CHANGED_PRODUCER = "changed_producer"
    UNOWNED_PRODUCER = "unowned_producer"
    STALE_BASELINE = "stale_baseline"
    INCOMPLETE_DELTA = "incomplete_delta"
    EXPIRED_WAIVER = "expired_waiver"


@dataclass(frozen=True, slots=True)
class InventoryGap:
    kind: InventoryGapKind
    path: str
    detail: str
    producer_id: str = ""

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "kind": self.kind.value,
                "path": self.path,
                "detail": self.detail,
                "producer_id": self.producer_id,
            }
        )


@dataclass(frozen=True, slots=True)
class InventoryGapRouting:
    """Governed routing for inventory gaps (never retry stale generation)."""

    plan_revision_task_id: str
    generation_rollover_task_id: str
    gaps: tuple[InventoryGap, ...]
    stale_generation_id: str
    repository_tree_id: str
    requires_new_generation: bool = True
    retry_against_stale_generation_allowed: bool = False

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "plan_revision_task_id": self.plan_revision_task_id,
                "generation_rollover_task_id": self.generation_rollover_task_id,
                "gaps": [dict(g.as_mapping()) for g in self.gaps],
                "stale_generation_id": self.stale_generation_id,
                "repository_tree_id": self.repository_tree_id,
                "requires_new_generation": self.requires_new_generation,
                "retry_against_stale_generation_allowed": (
                    self.retry_against_stale_generation_allowed
                ),
            }
        )


def route_inventory_gaps(
    gaps: Sequence[InventoryGap | Mapping[str, Any]],
    *,
    generation: GenerationFence | Mapping[str, Any],
) -> InventoryGapRouting:
    """Route inventory gaps to DQK-081 plan revision + DQK-083 rollover."""

    fence = (
        generation
        if isinstance(generation, GenerationFence)
        else GenerationFence.from_mapping(generation)
    )
    normalized: list[InventoryGap] = []
    for raw in gaps:
        if isinstance(raw, InventoryGap):
            normalized.append(raw)
        else:
            normalized.append(
                InventoryGap(
                    kind=InventoryGapKind(str(raw.get("kind") or "unowned_producer")),
                    path=str(raw.get("path") or ""),
                    detail=str(raw.get("detail") or ""),
                    producer_id=str(raw.get("producer_id") or ""),
                )
            )
    if not normalized:
        raise AuthorityCutoverError("route_inventory_gaps requires at least one gap")
    return InventoryGapRouting(
        plan_revision_task_id=PLAN_REVISION_TASK_ID,
        generation_rollover_task_id=GENERATION_ROLLOVER_TASK_ID,
        gaps=tuple(normalized),
        stale_generation_id=fence.generation_id,
        repository_tree_id=fence.repository_tree_id,
        requires_new_generation=True,
        retry_against_stale_generation_allowed=False,
    )


@dataclass(frozen=True, slots=True)
class ExactHeadProducerScan:
    """Fresh exact-HEAD producer inventory scan."""

    schema: str
    scan_cid: str
    repository_tree_id: str
    head_tree_id: str
    producer_digests: Mapping[str, str]
    public_paths: tuple[str, ...]
    owned_paths: tuple[str, ...]
    waiver_cids: tuple[str, ...]
    inventory_proof_cid: str
    scanned_at: str
    signature: str
    is_fresh_exact_head: bool = True

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "scan_cid": self.scan_cid,
                "repository_tree_id": self.repository_tree_id,
                "head_tree_id": self.head_tree_id,
                "producer_digests": dict(self.producer_digests),
                "public_paths": list(self.public_paths),
                "owned_paths": list(self.owned_paths),
                "waiver_cids": list(self.waiver_cids),
                "inventory_proof_cid": self.inventory_proof_cid,
                "scanned_at": self.scanned_at,
                "signature": self.signature,
                "is_fresh_exact_head": self.is_fresh_exact_head,
            }
        )


def verify_waivers_current(
    waivers: Sequence[Mapping[str, Any] | ProducerWaiver],
    *,
    repository_tree_id: str,
    now: datetime | None = None,
) -> tuple[ProducerWaiver, ...]:
    """Every waiver must be current, reviewer-signed, path-scoped, justified, expiring."""

    tree = _require_tree_id(repository_tree_id)
    verified: list[ProducerWaiver] = []
    for raw in waivers:
        mapping = raw.to_dict() if isinstance(raw, ProducerWaiver) else dict(raw)
        verified.append(
            verify_producer_waiver(mapping, now=now, repository_tree_id=tree)
        )
    return tuple(verified)


def build_exact_head_scan(
    *,
    head_tree_id: str,
    producer_digests: Mapping[str, str] | None = None,
    owned_paths: Sequence[str] | None = None,
    public_paths: Sequence[str] | None = None,
    waivers: Sequence[Mapping[str, Any]] = (),
    inventory_snapshot_cid: str | None = None,
    now: datetime | None = None,
) -> ExactHeadProducerScan:
    """Build a fresh exact-HEAD producer inventory (hermetic / explicit digests).

    When *producer_digests* is omitted, digests are derived from the closed
    registered producer module paths (content-addressed identity of the
    registration record — no filesystem I/O).
    """

    head = _require_tree_id(head_tree_id, field="head_tree_id")
    digests: dict[str, str] = {}
    if producer_digests is None:
        for pid, producer in REGISTERED_PARQUET_PRODUCERS.items():
            digests[pid] = _digest_of(producer.to_dict())
    else:
        for pid, digest in producer_digests.items():
            key = _require_safe_token(pid, field="producer_id")
            digests[key] = _require_sha256(digest, field=f"producer_digests[{key}]")
        # Closed-set completeness: every registered producer must appear.
        missing = sorted(set(REGISTERED_PARQUET_PRODUCERS) - set(digests))
        if missing:
            raise ProducerInventoryError(
                "exact-HEAD scan missing registered producers: " + ",".join(missing)
            )
        extra = sorted(set(digests) - set(REGISTERED_PARQUET_PRODUCERS))
        if extra:
            raise ProducerInventoryError(
                "exact-HEAD scan has unregistered producers (new gap): "
                + ",".join(extra)
            )

    public = tuple(
        public_paths
        if public_paths is not None
        else tuple(
            p.module_path
            for p in REGISTERED_PARQUET_PRODUCERS.values()
            if p.public
        )
    )
    owned = tuple(owned_paths if owned_paths is not None else public)
    verified_waivers = verify_waivers_current(
        waivers, repository_tree_id=head, now=now
    )
    snapshot = inventory_snapshot_cid or _digest_of(
        {
            "head_tree_id": head,
            "producer_digests": dict(sorted(digests.items())),
            "kind": "exact-head-scan",
        }
    )
    proof = prove_zero_unowned_public_parquet_producers(
        repository_tree_id=head,
        inventory_snapshot_cid=snapshot
        if _SHA256_DIGEST.fullmatch(str(snapshot))
        else _digest_of({"snapshot": snapshot}),
        public_producer_paths=public,
        owned_paths=owned,
        waivers=[w.to_dict() for w in verified_waivers],
        now=now,
    )
    scanned_at = _utc_now()
    body = {
        "schema": INVENTORY_SCAN_SCHEMA,
        "repository_tree_id": head,
        "head_tree_id": head,
        "producer_digests": dict(sorted(digests.items())),
        "public_paths": list(public),
        "owned_paths": list(owned),
        "waiver_cids": list(proof.waiver_cids),
        "inventory_proof_cid": proof.proof_cid,
        "scanned_at": scanned_at,
        "is_fresh_exact_head": True,
        "program_id": PROGRAM_ID,
        "owner_task_id": OWNER_TASK_ID,
    }
    signature = _digest_of(body)
    scan_cid = _digest_of({**body, "signature": signature})
    return ExactHeadProducerScan(
        schema=INVENTORY_SCAN_SCHEMA,
        scan_cid=scan_cid,
        repository_tree_id=head,
        head_tree_id=head,
        producer_digests=MappingProxyType(dict(sorted(digests.items()))),
        public_paths=tuple(public),
        owned_paths=tuple(owned),
        waiver_cids=tuple(proof.waiver_cids),
        inventory_proof_cid=proof.proof_cid,
        scanned_at=scanned_at,
        signature=signature,
        is_fresh_exact_head=True,
    )


@dataclass(frozen=True, slots=True)
class SignedInventoryBaseline:
    """Signed producer inventory baseline at a specific tree."""

    schema: str
    baseline_cid: str
    baseline_tree_id: str
    producer_digests: Mapping[str, str]
    inventory_proof_cid: str
    issued_at: str
    signer_identity: str
    signature: str
    program_id: str = PROGRAM_ID
    owner_task_id: str = OWNER_TASK_ID

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "baseline_tree_id": self.baseline_tree_id,
                "producer_digests": dict(self.producer_digests),
                "inventory_proof_cid": self.inventory_proof_cid,
                "issued_at": self.issued_at,
                "signer_identity": self.signer_identity,
                "program_id": self.program_id,
                "owner_task_id": self.owner_task_id,
                "signature": self.signature,
                "baseline_cid": self.baseline_cid,
            }
        )


def build_signed_baseline(
    *,
    baseline_tree_id: str,
    producer_digests: Mapping[str, str],
    signer_identity: str,
    inventory_proof_cid: str | None = None,
    issued_at: datetime | str | None = None,
) -> SignedInventoryBaseline:
    tree = _require_tree_id(baseline_tree_id, field="baseline_tree_id")
    digests = {
        _require_safe_token(k, field="producer_id"): _require_sha256(
            v, field=f"producer_digests[{k}]"
        )
        for k, v in producer_digests.items()
    }
    missing = sorted(set(REGISTERED_PARQUET_PRODUCERS) - set(digests))
    if missing:
        raise ProducerInventoryError(
            "baseline missing registered producers: " + ",".join(missing)
        )
    proof_cid = (
        _require_sha256(inventory_proof_cid, field="inventory_proof_cid")
        if inventory_proof_cid
        else _digest_of({"baseline_tree_id": tree, "producer_digests": digests})
    )
    issued = normalize_timestamp(issued_at or _utc_now())
    signer = _require_safe_token(signer_identity, field="signer_identity")
    body = {
        "schema": BASELINE_SCHEMA,
        "baseline_tree_id": tree,
        "producer_digests": dict(sorted(digests.items())),
        "inventory_proof_cid": proof_cid,
        "issued_at": issued,
        "signer_identity": signer,
        "program_id": PROGRAM_ID,
        "owner_task_id": OWNER_TASK_ID,
    }
    signature = _digest_of({**body, "signer_binding": signer})
    baseline_cid = _digest_of({**body, "signature": signature})
    return SignedInventoryBaseline(
        schema=BASELINE_SCHEMA,
        baseline_cid=baseline_cid,
        baseline_tree_id=tree,
        producer_digests=MappingProxyType(dict(sorted(digests.items()))),
        inventory_proof_cid=proof_cid,
        issued_at=issued,
        signer_identity=signer,
        signature=signature,
        program_id=PROGRAM_ID,
        owner_task_id=OWNER_TASK_ID,
    )


@dataclass(frozen=True, slots=True)
class ContentAddressedDelta:
    """Complete content-addressed delta chain from baseline tree through HEAD."""

    schema: str
    delta_cid: str
    from_tree_id: str
    to_tree_id: str  # must equal HEAD
    steps: tuple[Mapping[str, Any], ...]
    resulting_producer_digests: Mapping[str, str]
    complete_through_head: bool
    signature: str

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "delta_cid": self.delta_cid,
                "from_tree_id": self.from_tree_id,
                "to_tree_id": self.to_tree_id,
                "steps": [dict(s) for s in self.steps],
                "resulting_producer_digests": dict(self.resulting_producer_digests),
                "complete_through_head": self.complete_through_head,
                "signature": self.signature,
            }
        )


def build_content_addressed_delta(
    *,
    from_tree_id: str,
    to_tree_id: str,
    steps: Sequence[Mapping[str, Any]],
    resulting_producer_digests: Mapping[str, str],
) -> ContentAddressedDelta:
    """Build a content-addressed delta. Each step binds prev/next tree digests."""

    start = _require_tree_id(from_tree_id, field="from_tree_id")
    end = _require_tree_id(to_tree_id, field="to_tree_id")
    if not steps:
        raise IncompleteDeltaError(
            "content-addressed delta must include at least one step through HEAD"
        )
    normalized_steps: list[dict[str, Any]] = []
    cursor = start
    for index, raw in enumerate(steps):
        if not isinstance(raw, Mapping):
            raise IncompleteDeltaError(f"delta step {index} must be an object")
        prev = _require_tree_id(raw.get("from_tree_id"), field=f"steps[{index}].from")
        nxt = _require_tree_id(raw.get("to_tree_id"), field=f"steps[{index}].to")
        if prev != cursor:
            raise IncompleteDeltaError(
                f"delta step {index} breaks chain: expected from_tree_id={cursor}"
            )
        change_set = raw.get("producer_changes") or {}
        if not isinstance(change_set, Mapping):
            raise IncompleteDeltaError(
                f"delta step {index} producer_changes must be an object"
            )
        changes = {
            _require_safe_token(k, field="producer_id"): _require_sha256(
                v, field=f"producer_changes[{k}]"
            )
            for k, v in change_set.items()
        }
        step_body = {
            "from_tree_id": prev,
            "to_tree_id": nxt,
            "producer_changes": dict(sorted(changes.items())),
            "step_index": index,
        }
        step_body["step_cid"] = _digest_of(step_body)
        normalized_steps.append(step_body)
        cursor = nxt
    if cursor != end:
        raise IncompleteDeltaError(
            f"delta chain ends at {cursor} but HEAD/to_tree_id is {end}"
        )
    result = {
        _require_safe_token(k, field="producer_id"): _require_sha256(
            v, field=f"resulting_producer_digests[{k}]"
        )
        for k, v in resulting_producer_digests.items()
    }
    missing = sorted(set(REGISTERED_PARQUET_PRODUCERS) - set(result))
    if missing:
        raise IncompleteDeltaError(
            "delta resulting digests missing producers: " + ",".join(missing)
        )
    body = {
        "schema": DELTA_SCHEMA,
        "from_tree_id": start,
        "to_tree_id": end,
        "steps": normalized_steps,
        "resulting_producer_digests": dict(sorted(result.items())),
        "complete_through_head": True,
        "program_id": PROGRAM_ID,
        "owner_task_id": OWNER_TASK_ID,
    }
    signature = _digest_of(body)
    delta_cid = _digest_of({**body, "signature": signature})
    return ContentAddressedDelta(
        schema=DELTA_SCHEMA,
        delta_cid=delta_cid,
        from_tree_id=start,
        to_tree_id=end,
        steps=tuple(MappingProxyType(s) for s in normalized_steps),
        resulting_producer_digests=MappingProxyType(dict(sorted(result.items()))),
        complete_through_head=True,
        signature=signature,
    )


def apply_content_addressed_delta(
    baseline: SignedInventoryBaseline | Mapping[str, Any],
    delta: ContentAddressedDelta | Mapping[str, Any],
    *,
    head_tree_id: str,
) -> dict[str, str]:
    """Apply a complete delta onto a signed baseline; return HEAD producer digests."""

    if isinstance(baseline, SignedInventoryBaseline):
        base_map = dict(baseline.as_mapping())
    else:
        base_map = dict(baseline)
    if isinstance(delta, ContentAddressedDelta):
        delta_map = dict(delta.as_mapping())
    else:
        delta_map = dict(delta)

    head = _require_tree_id(head_tree_id, field="head_tree_id")
    base_tree = _require_tree_id(
        base_map.get("baseline_tree_id"), field="baseline_tree_id"
    )
    # Verify baseline signature against the exact sealed body fields.
    signer = _require_safe_token(
        base_map.get("signer_identity"), field="signer_identity"
    )
    base_body = {
        "schema": base_map.get("schema") or BASELINE_SCHEMA,
        "baseline_tree_id": base_map.get("baseline_tree_id"),
        "producer_digests": dict(
            sorted(dict(base_map.get("producer_digests") or {}).items())
        ),
        "inventory_proof_cid": base_map.get("inventory_proof_cid"),
        "issued_at": base_map.get("issued_at"),
        "signer_identity": signer,
        "program_id": base_map.get("program_id") or PROGRAM_ID,
        "owner_task_id": base_map.get("owner_task_id") or OWNER_TASK_ID,
    }
    expected_base_sig = _digest_of({**base_body, "signer_binding": signer})
    actual_base_sig = _require_sha256(
        base_map.get("signature"), field="baseline.signature"
    )
    if not _hmac_eq(expected_base_sig, actual_base_sig):
        raise StaleBaselineError("baseline signature mismatch")

    from_tree = _require_tree_id(delta_map.get("from_tree_id"), field="from_tree_id")
    to_tree = _require_tree_id(delta_map.get("to_tree_id"), field="to_tree_id")
    if from_tree != base_tree:
        raise StaleBaselineError(
            f"stale baseline: baseline_tree_id={base_tree} does not match "
            f"delta from_tree_id={from_tree}"
        )
    if to_tree != head:
        raise IncompleteDeltaError(
            f"incomplete delta: delta to_tree_id={to_tree} does not equal HEAD={head}"
        )
    if not bool(delta_map.get("complete_through_head")):
        raise IncompleteDeltaError("delta is not marked complete_through_head")

    steps = list(delta_map.get("steps") or [])
    if not steps:
        raise IncompleteDeltaError("delta has no steps")
    cursor = from_tree
    digests = {
        _require_safe_token(k, field="producer_id"): _require_sha256(
            v, field=f"baseline.producer_digests[{k}]"
        )
        for k, v in dict(base_map.get("producer_digests") or {}).items()
    }
    for index, step in enumerate(steps):
        if not isinstance(step, Mapping):
            raise IncompleteDeltaError(f"delta step {index} is invalid")
        prev = _require_tree_id(step.get("from_tree_id"), field=f"step[{index}].from")
        nxt = _require_tree_id(step.get("to_tree_id"), field=f"step[{index}].to")
        if prev != cursor:
            raise IncompleteDeltaError(
                f"incomplete delta chain at step {index}: expected {cursor}, got {prev}"
            )
        for pid, new_digest in dict(step.get("producer_changes") or {}).items():
            digests[_require_safe_token(pid, field="producer_id")] = _require_sha256(
                new_digest, field=f"step[{index}].{pid}"
            )
        cursor = nxt
    if cursor != head:
        raise IncompleteDeltaError(
            f"incomplete delta: chain ends at {cursor}, HEAD is {head}"
        )

    expected_result = {
        _require_safe_token(k, field="producer_id"): _require_sha256(
            v, field=f"resulting[{k}]"
        )
        for k, v in dict(delta_map.get("resulting_producer_digests") or {}).items()
    }
    if digests != expected_result:
        # Changed producer gap: applied chain disagrees with claimed result.
        raise ProducerInventoryError(
            "delta resulting producer digests disagree with applied chain "
            "(changed or incomplete producer gap)"
        )
    missing = sorted(set(REGISTERED_PARQUET_PRODUCERS) - set(digests))
    if missing:
        raise ProducerInventoryError(
            "applied delta leaves unregistered gaps for: " + ",".join(missing)
        )
    extra = sorted(set(digests) - set(REGISTERED_PARQUET_PRODUCERS))
    if extra:
        raise ProducerInventoryError(
            "applied delta introduces unowned/new producers: " + ",".join(extra)
        )
    return dict(sorted(digests.items()))


def verify_inventory_through_head(
    *,
    head_tree_id: str,
    generation: GenerationFence | Mapping[str, Any],
    exact_head_scan: ExactHeadProducerScan | Mapping[str, Any] | None = None,
    baseline: SignedInventoryBaseline | Mapping[str, Any] | None = None,
    delta: ContentAddressedDelta | Mapping[str, Any] | None = None,
    waivers: Sequence[Mapping[str, Any]] = (),
    expected_producer_digests: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> tuple[str, dict[str, str], ExactTreeInventoryProof | None]:
    """Verify inventory path for cutover; return (proof_cid, digests, proof).

    Accepts either a fresh exact-HEAD scan **or** a signed baseline plus a
    complete content-addressed delta through HEAD. On gap, raises with routing
    metadata available via :func:`route_inventory_gaps`.
    """

    fence = (
        generation
        if isinstance(generation, GenerationFence)
        else GenerationFence.from_mapping(generation)
    )
    head = _require_tree_id(head_tree_id, field="head_tree_id")
    if head != fence.repository_tree_id:
        gaps = [
            InventoryGap(
                kind=InventoryGapKind.STALE_BASELINE,
                path="",
                detail=(
                    f"HEAD tree {head} does not match generation fence tree "
                    f"{fence.repository_tree_id}"
                ),
            )
        ]
        routing = route_inventory_gaps(gaps, generation=fence)
        raise CutoverBlockedError(
            "inventory HEAD does not match generation fence repository tree; "
            f"route to {PLAN_REVISION_TASK_ID} and {GENERATION_ROLLOVER_TASK_ID}",
            reason="inventory_tree_mismatch",
            gap_routing=dict(routing.as_mapping()),
        )

    digests: dict[str, str]
    proof_cid: str
    proof: ExactTreeInventoryProof | None = None

    if exact_head_scan is not None:
        if baseline is not None or delta is not None:
            raise AuthorityCutoverError(
                "provide either exact-HEAD scan or baseline+delta, not both"
            )
        if isinstance(exact_head_scan, ExactHeadProducerScan):
            scan_map = dict(exact_head_scan.as_mapping())
        else:
            scan_map = dict(exact_head_scan)
        if not bool(scan_map.get("is_fresh_exact_head")):
            raise ProducerInventoryError("exact-HEAD scan is not marked fresh")
        scan_head = _require_tree_id(
            scan_map.get("head_tree_id"), field="scan.head_tree_id"
        )
        if scan_head != head:
            raise ProducerInventoryError(
                f"exact-HEAD scan head_tree_id={scan_head} != HEAD={head}"
            )
        digests = {
            _require_safe_token(k, field="producer_id"): _require_sha256(
                v, field=f"scan.digest[{k}]"
            )
            for k, v in dict(scan_map.get("producer_digests") or {}).items()
        }
        proof_cid = _require_sha256(
            scan_map.get("inventory_proof_cid"), field="inventory_proof_cid"
        )
        # Re-verify waivers embedded / supplied.
        verify_waivers_current(waivers, repository_tree_id=head, now=now)
    else:
        if baseline is None or delta is None:
            raise AuthorityCutoverError(
                "cutover requires a fresh exact-HEAD producer scan or a signed "
                "baseline plus complete content-addressed delta through HEAD"
            )
        try:
            digests = apply_content_addressed_delta(
                baseline, delta, head_tree_id=head
            )
        except (StaleBaselineError, IncompleteDeltaError, ProducerInventoryError) as exc:
            kind = InventoryGapKind.STALE_BASELINE
            if isinstance(exc, IncompleteDeltaError):
                kind = InventoryGapKind.INCOMPLETE_DELTA
            elif isinstance(exc, ProducerInventoryError):
                kind = InventoryGapKind.CHANGED_PRODUCER
            routing = route_inventory_gaps(
                [
                    InventoryGap(
                        kind=kind,
                        path="",
                        detail=str(exc),
                    )
                ],
                generation=fence,
            )
            raise CutoverBlockedError(
                f"{exc}; route to {PLAN_REVISION_TASK_ID} and "
                f"{GENERATION_ROLLOVER_TASK_ID} rather than retrying stale generation",
                reason=kind.value,
                gap_routing=dict(routing.as_mapping()),
            ) from exc
        # Build / verify zero-unowned proof at HEAD.
        public = tuple(
            p.module_path
            for p in REGISTERED_PARQUET_PRODUCERS.values()
            if p.public
        )
        try:
            proof = prove_zero_unowned_public_parquet_producers(
                repository_tree_id=head,
                inventory_snapshot_cid=_digest_of(
                    {"head": head, "digests": digests, "via": "baseline+delta"}
                ),
                public_producer_paths=public,
                owned_paths=public,
                waivers=list(waivers),
                now=now,
            )
            proof_cid = proof.proof_cid
        except (UnownedProducerError, WaiverValidationError) as exc:
            routing = route_inventory_gaps(
                [
                    InventoryGap(
                        kind=InventoryGapKind.UNOWNED_PRODUCER,
                        path="",
                        detail=str(exc),
                    )
                ],
                generation=fence,
            )
            raise CutoverBlockedError(
                f"{exc}; route to {PLAN_REVISION_TASK_ID} and "
                f"{GENERATION_ROLLOVER_TASK_ID}",
                reason="unowned_producer",
                gap_routing=dict(routing.as_mapping()),
            ) from exc

    if expected_producer_digests is not None:
        expected = {
            _require_safe_token(k, field="producer_id"): _require_sha256(
                v, field=f"expected[{k}]"
            )
            for k, v in expected_producer_digests.items()
        }
        changed = sorted(
            pid
            for pid, digest in digests.items()
            if expected.get(pid) is not None and expected[pid] != digest
        )
        new_ids = sorted(set(digests) - set(expected))
        missing_ids = sorted(set(expected) - set(digests))
        gaps: list[InventoryGap] = []
        for pid in changed:
            gaps.append(
                InventoryGap(
                    kind=InventoryGapKind.CHANGED_PRODUCER,
                    path=REGISTERED_PARQUET_PRODUCERS[pid].module_path
                    if pid in REGISTERED_PARQUET_PRODUCERS
                    else pid,
                    detail=f"producer digest changed for {pid}",
                    producer_id=pid,
                )
            )
        for pid in new_ids:
            gaps.append(
                InventoryGap(
                    kind=InventoryGapKind.NEW_PRODUCER,
                    path=pid,
                    detail=f"new producer {pid} not in expected set",
                    producer_id=pid,
                )
            )
        for pid in missing_ids:
            gaps.append(
                InventoryGap(
                    kind=InventoryGapKind.UNOWNED_PRODUCER,
                    path=pid,
                    detail=f"expected producer {pid} missing from inventory",
                    producer_id=pid,
                )
            )
        if gaps:
            routing = route_inventory_gaps(gaps, generation=fence)
            raise CutoverBlockedError(
                "producer inventory has new/changed/unowned gaps; route to "
                f"{PLAN_REVISION_TASK_ID} and {GENERATION_ROLLOVER_TASK_ID} "
                "rather than retrying against a stale generation",
                reason="producer_inventory_gap",
                gap_routing=dict(routing.as_mapping()),
            )

    return proof_cid, digests, proof


# ---------------------------------------------------------------------------
# Execution + rollback receipts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    """Generation-fenced execution receipt binding before/after authorities."""

    schema: str
    execution_id: str
    receipt_cid: str
    decision_cid: str
    actor_identity: str
    process_birth_fingerprint: str
    generation_fingerprint: str
    repository_tree_id: str
    before_authority: str
    after_authority: str
    inventory_proof_cid: str
    evidence_set_cid: str
    changed_producers: tuple[str, ...]
    rollback_fence_id: str
    rollback_window_hours: int
    dry_run: bool
    executed_at: str
    post_transition_verification: str
    signature: str
    production_authority_mutated: bool = False

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "execution_id": self.execution_id,
                "receipt_cid": self.receipt_cid,
                "decision_cid": self.decision_cid,
                "actor_identity": self.actor_identity,
                "process_birth_fingerprint": self.process_birth_fingerprint,
                "generation_fingerprint": self.generation_fingerprint,
                "repository_tree_id": self.repository_tree_id,
                "before_authority": self.before_authority,
                "after_authority": self.after_authority,
                "inventory_proof_cid": self.inventory_proof_cid,
                "evidence_set_cid": self.evidence_set_cid,
                "changed_producers": list(self.changed_producers),
                "rollback_fence_id": self.rollback_fence_id,
                "rollback_window_hours": self.rollback_window_hours,
                "dry_run": self.dry_run,
                "executed_at": self.executed_at,
                "post_transition_verification": self.post_transition_verification,
                "signature": self.signature,
                "production_authority_mutated": self.production_authority_mutated,
            }
        )


@dataclass(frozen=True, slots=True)
class RollbackReceipt:
    """Bounded receipted rollback to the pre-cutover authority."""

    schema: str
    rollback_id: str
    receipt_cid: str
    execution_id: str
    decision_cid: str
    from_authority: str
    to_authority: str
    generation_fingerprint: str
    repository_tree_id: str
    actor_identity: str
    process_birth_fingerprint: str
    bounded_by_execution: bool
    rolled_back_at: str
    signature: str

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "rollback_id": self.rollback_id,
                "receipt_cid": self.receipt_cid,
                "execution_id": self.execution_id,
                "decision_cid": self.decision_cid,
                "from_authority": self.from_authority,
                "to_authority": self.to_authority,
                "generation_fingerprint": self.generation_fingerprint,
                "repository_tree_id": self.repository_tree_id,
                "actor_identity": self.actor_identity,
                "process_birth_fingerprint": self.process_birth_fingerprint,
                "bounded_by_execution": self.bounded_by_execution,
                "rolled_back_at": self.rolled_back_at,
                "signature": self.signature,
            }
        )


@dataclass(frozen=True, slots=True)
class CutoverDryRunResult:
    """Outcome of a dry-run cutover verification (no authority mutation)."""

    ok: bool
    would_transition: str
    decision_cid: str
    inventory_proof_cid: str
    evidence_set_cid: str
    generation_fingerprint: str
    before_authority: str
    after_authority: str
    blockers: tuple[str, ...]
    production_authority_unchanged: bool = True
    dry_run: bool = True

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "ok": self.ok,
                "would_transition": self.would_transition,
                "decision_cid": self.decision_cid,
                "inventory_proof_cid": self.inventory_proof_cid,
                "evidence_set_cid": self.evidence_set_cid,
                "generation_fingerprint": self.generation_fingerprint,
                "before_authority": self.before_authority,
                "after_authority": self.after_authority,
                "blockers": list(self.blockers),
                "production_authority_unchanged": self.production_authority_unchanged,
                "dry_run": self.dry_run,
            }
        )


# ---------------------------------------------------------------------------
# Discovery enforcement for producers (no-op under legacy)
# ---------------------------------------------------------------------------


def assert_source_content_addressed(
    *,
    source_digest: str,
    source_bytes: bytes | None = None,
    source_uri: str = "",
    media_type: str = "parquet",
) -> str:
    """Immutable source Parquet data remains content addressed.

    When *source_bytes* are provided, the digest must match. Always returns the
    validated ``sha256:…`` digest.
    """

    digest = _require_sha256(source_digest, field="source_digest")
    if source_bytes is not None:
        actual = digest_bytes(source_bytes)
        if not _hmac_eq(digest, actual):
            raise AuthorityCutoverError(
                f"source content address mismatch for {source_uri or media_type}: "
                f"claimed {digest}, actual {actual}"
            )
    return digest


def assert_query_discovery_authorized(
    *,
    path: str,
    registered_paths: Sequence[str] | None = None,
    allow_directory_scan: bool | None = None,
    is_mutable_sidecar_manifest: bool = False,
) -> None:
    """When lake authority is active, reject unregistered / sidecar discovery.

    Under legacy mode this is a no-op so DQK-100 completion never disables
    legacy producers or directory scans.
    """

    if not is_lake_authority_active():
        return
    if is_mutable_sidecar_manifest:
        raise CutoverBlockedError(
            f"mutable sidecar manifest is not authoritative under lake_primary "
            f"(path={path!r})",
            reason="mutable_sidecar_rejected",
        )
    if allow_directory_scan is None:
        allow_directory_scan = False
    if allow_directory_scan:
        raise CutoverBlockedError(
            f"implicit directory scan is disabled under lake_primary "
            f"(path={path!r})",
            reason="implicit_directory_scan_rejected",
        )
    allowed = tuple(
        registered_paths
        if registered_paths is not None
        else tuple(
            p.module_path for p in REGISTERED_PARQUET_PRODUCERS.values() if p.public
        )
    )
    normalized = path.strip().lstrip("./")
    owned = False
    for root in allowed:
        r = root.strip().lstrip("./")
        if not r:
            continue
        if normalized == r or normalized.startswith(r.rstrip("/") + "/"):
            owned = True
            break
        # Also allow registered producer ids as logical dataset roots.
        if normalized == root or normalized.startswith(str(root) + "/"):
            owned = True
            break
    if not owned:
        raise CutoverBlockedError(
            f"unregistered directory contents cannot enter a query under "
            f"lake_primary (path={path!r})",
            reason="unregistered_path_rejected",
        )


def maybe_enforce_lake_discovery(
    *,
    producer_id: str,
    source_uri: str = "",
    path: str = "",
    uses_mutable_sidecar: bool = False,
    uses_implicit_directory_scan: bool = False,
    source_digest: str | None = None,
    source_bytes: bytes | None = None,
) -> dict[str, Any] | None:
    """Producer entrypoint hook: enforce lake discovery only when promoted.

    Returns ``None`` under legacy (default) so production authority and legacy
    producers are unchanged by DQK-100 implementation. When lake-primary is
    process-local active, rejects mutable sidecars, implicit directory scans,
    and unregistered paths; validates content addressing when a digest is given.
    """

    if not is_lake_authority_active():
        return None
    target = path or source_uri or producer_id
    if uses_mutable_sidecar:
        assert_query_discovery_authorized(
            path=target, is_mutable_sidecar_manifest=True
        )
    if uses_implicit_directory_scan:
        assert_query_discovery_authorized(
            path=target, allow_directory_scan=True
        )
    # Registered producers remain authorized by producer_id module path.
    producer = REGISTERED_PARQUET_PRODUCERS.get(str(producer_id).strip())
    if producer is not None:
        # Producer itself is in the closed set; only extra paths need checks.
        if path and path not in {producer.module_path, source_uri, ""}:
            assert_query_discovery_authorized(path=path)
    elif path:
        assert_query_discovery_authorized(path=path)
    if source_digest is not None:
        assert_source_content_addressed(
            source_digest=source_digest,
            source_bytes=source_bytes,
            source_uri=source_uri,
        )
    return {
        "enforced": True,
        "authority": CutoverAuthorityMode.LAKE_PRIMARY.value,
        "producer_id": producer_id,
        "path": target,
    }


# ---------------------------------------------------------------------------
# Fenced cutover command / controller
# ---------------------------------------------------------------------------


@dataclass
class CutoverCommand:
    """Inputs for one fenced cutover invocation."""

    actor_identity: str
    process_birth: ProcessBirth
    generation: GenerationFence
    decision: PromotionDecision | Mapping[str, Any]
    evidence: EvidenceBundle | Mapping[str, Any]
    head_tree_id: str
    exact_head_scan: ExactHeadProducerScan | Mapping[str, Any] | None = None
    baseline: SignedInventoryBaseline | Mapping[str, Any] | None = None
    delta: ContentAddressedDelta | Mapping[str, Any] | None = None
    waivers: tuple[Mapping[str, Any], ...] = ()
    expected_producer_digests: Mapping[str, str] | None = None
    dry_run: bool = True
    # Explicit synthetic execute flag. Even when False is overridden to True,
    # production_authority_mutated remains False — hermetic only.
    execute_process_local: bool = False


class CutoverController:
    """Fenced cutover command surface: verify, dry-run, execute, rollback.

    Execution only mutates **process-local** authority for hermetic verification.
    It never claims production authority mutation.
    """

    SCHEMA: Final[str] = CUTOVER_COMMAND_SCHEMA

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._last_execution: ExecutionReceipt | None = None
        self._last_rollback: RollbackReceipt | None = None
        self._executions: dict[str, ExecutionReceipt] = {}

    @property
    def last_execution(self) -> ExecutionReceipt | None:
        return self._last_execution

    @property
    def last_rollback(self) -> RollbackReceipt | None:
        return self._last_rollback

    def verify(
        self,
        command: CutoverCommand,
        *,
        now: datetime | None = None,
    ) -> tuple[PromotionDecision, str, dict[str, str]]:
        """Verify all cutover gates without mutating authority."""

        fence = command.generation
        birth = command.process_birth
        if not isinstance(birth, ProcessBirth):
            birth = ProcessBirth.from_mapping(birth)  # type: ignore[arg-type]
        if not isinstance(fence, GenerationFence):
            fence = GenerationFence.from_mapping(fence)  # type: ignore[arg-type]

        proof_cid, digests, _proof = verify_inventory_through_head(
            head_tree_id=command.head_tree_id,
            generation=fence,
            exact_head_scan=command.exact_head_scan,
            baseline=command.baseline,
            delta=command.delta,
            waivers=list(command.waivers),
            expected_producer_digests=command.expected_producer_digests,
            now=now,
        )
        verified_decision = verify_promotion_decision(
            command.decision,
            process_birth=birth,
            generation=fence,
            evidence=command.evidence,
            inventory_proof_cid=proof_cid,
            actor_identity=command.actor_identity,
            now=now,
            expected_transition=(
                CutoverAuthorityMode.LEGACY.value,
                CutoverAuthorityMode.LAKE_PRIMARY.value,
            ),
        )
        return verified_decision, proof_cid, digests

    def dry_run(
        self,
        command: CutoverCommand,
        *,
        now: datetime | None = None,
    ) -> CutoverDryRunResult:
        """Dry-run: verify gates; never mutate process-local or production authority."""

        before = authority_mode().value
        try:
            decision, proof_cid, _digests = self.verify(command, now=now)
            evidence = verify_evidence_bundle(
                command.evidence,
                now=now,
                expected_tree_id=command.generation.repository_tree_id
                if isinstance(command.generation, GenerationFence)
                else str(
                    dict(command.generation).get("repository_tree_id")  # type: ignore[arg-type]
                ),
            )
            return CutoverDryRunResult(
                ok=True,
                would_transition=decision.requested_transition,
                decision_cid=decision.decision_cid,
                inventory_proof_cid=proof_cid,
                evidence_set_cid=evidence.evidence_set_cid,
                generation_fingerprint=(
                    command.generation.fingerprint()
                    if isinstance(command.generation, GenerationFence)
                    else GenerationFence.from_mapping(command.generation).fingerprint()  # type: ignore[arg-type]
                ),
                before_authority=before,
                after_authority=decision.to_authority,
                blockers=(),
                production_authority_unchanged=production_authority_unchanged(),
                dry_run=True,
            )
        except AuthorityCutoverError as exc:
            return CutoverDryRunResult(
                ok=False,
                would_transition="",
                decision_cid="",
                inventory_proof_cid="",
                evidence_set_cid="",
                generation_fingerprint="",
                before_authority=before,
                after_authority=before,
                blockers=(str(exc),),
                production_authority_unchanged=production_authority_unchanged(),
                dry_run=True,
            )

    def invoke(
        self,
        command: CutoverCommand,
        *,
        now: datetime | None = None,
    ) -> ExecutionReceipt | CutoverDryRunResult:
        """Invoke the fenced cutover command.

        * ``dry_run=True`` (default): verify only; no authority change.
        * ``execute_process_local=True`` and ``dry_run=False``: flip process-local
          authority for hermetic tests after full verification. Production
          authority is never mutated (``production_authority_mutated`` stays
          False; ``IMPLEMENTATION_GRANTS_NO_AUTHORITY`` remains True).
        """

        with self._lock:
            if command.dry_run or not command.execute_process_local:
                return self.dry_run(command, now=now)

            decision, proof_cid, digests = self.verify(command, now=now)
            birth = command.process_birth
            fence = command.generation
            if not isinstance(birth, ProcessBirth):
                birth = ProcessBirth.from_mapping(birth)  # type: ignore[arg-type]
            if not isinstance(fence, GenerationFence):
                fence = GenerationFence.from_mapping(fence)  # type: ignore[arg-type]
            evidence = verify_evidence_bundle(
                command.evidence,
                now=now,
                expected_tree_id=fence.repository_tree_id,
                expected_generation_id=fence.generation_id,
            )

            before = authority_mode()
            if before is not CutoverAuthorityMode.LEGACY:
                raise CutoverBlockedError(
                    f"cutover requires before_authority=legacy, got {before.value}",
                    reason="unexpected_before_authority",
                )
            after = CutoverAuthorityMode.parse(decision.to_authority)
            if after is not CutoverAuthorityMode.LAKE_PRIMARY:
                raise CutoverBlockedError(
                    "cutover execution only supports transition to lake_primary",
                    reason="unexpected_after_authority",
                )

            execution_id = _new_id("exec")
            rollback_fence_id = _new_id("rollback-fence")
            executed_at = _utc_now()
            changed = tuple(sorted(digests.keys()))
            body = {
                "schema": EXECUTION_RECEIPT_SCHEMA,
                "execution_id": execution_id,
                "decision_cid": decision.decision_cid,
                "actor_identity": decision.actor_identity,
                "process_birth_fingerprint": birth.fingerprint(),
                "generation_fingerprint": fence.fingerprint(),
                "repository_tree_id": fence.repository_tree_id,
                "before_authority": before.value,
                "after_authority": after.value,
                "inventory_proof_cid": proof_cid,
                "evidence_set_cid": evidence.evidence_set_cid,
                "changed_producers": list(changed),
                "rollback_fence_id": rollback_fence_id,
                "rollback_window_hours": decision.rollback_window_hours,
                "dry_run": False,
                "executed_at": executed_at,
                "post_transition_verification": "pending",
                "production_authority_mutated": False,
                "program_id": PROGRAM_ID,
                "owner_task_id": OWNER_TASK_ID,
            }

            # Process-local authority flip (hermetic only).
            with _STATE_LOCK:
                _PROCESS_STATE.mode = after
                _PROCESS_STATE.promoted_by_execution_id = execution_id
                _PROCESS_STATE.decision_cid = decision.decision_cid
                _PROCESS_STATE.generation_id = fence.generation_id
                _PROCESS_STATE.repository_tree_id = fence.repository_tree_id
                # Explicitly never claim production mutation.
                _PROCESS_STATE.production_authority_mutated = False

            # Post-transition verification (process-local).
            post = "ok"
            if authority_mode() is not after:
                post = "authority_mode_mismatch"
            if legacy_producers_enabled():
                post = "legacy_still_enabled_unexpected"
            if mutable_sidecar_authority_enabled():
                post = "sidecar_still_enabled_unexpected"
            if implicit_directory_scan_enabled():
                post = "directory_scan_still_enabled_unexpected"
            body["post_transition_verification"] = post
            if post != "ok":
                # Roll back process-local state on failed post-check.
                with _STATE_LOCK:
                    _PROCESS_STATE.mode = CutoverAuthorityMode.LEGACY
                    _PROCESS_STATE.promoted_by_execution_id = None
                raise CutoverBlockedError(
                    f"post-transition verification failed: {post}",
                    reason="post_transition_verification_failed",
                )

            signature = _digest_of(body)
            receipt_cid = _digest_of({**body, "signature": signature})
            receipt = ExecutionReceipt(
                schema=EXECUTION_RECEIPT_SCHEMA,
                execution_id=execution_id,
                receipt_cid=receipt_cid,
                decision_cid=decision.decision_cid,
                actor_identity=decision.actor_identity,
                process_birth_fingerprint=birth.fingerprint(),
                generation_fingerprint=fence.fingerprint(),
                repository_tree_id=fence.repository_tree_id,
                before_authority=before.value,
                after_authority=after.value,
                inventory_proof_cid=proof_cid,
                evidence_set_cid=evidence.evidence_set_cid,
                changed_producers=changed,
                rollback_fence_id=rollback_fence_id,
                rollback_window_hours=decision.rollback_window_hours,
                dry_run=False,
                executed_at=executed_at,
                post_transition_verification=post,
                signature=signature,
                production_authority_mutated=False,
            )
            self._last_execution = receipt
            self._executions[execution_id] = receipt
            with _STATE_LOCK:
                _PROCESS_STATE.last_execution_receipt = dict(receipt.as_mapping())
            return receipt

    def rollback(
        self,
        *,
        execution: ExecutionReceipt | Mapping[str, Any] | None = None,
        actor_identity: str,
        process_birth: ProcessBirth | Mapping[str, Any],
        generation: GenerationFence | Mapping[str, Any],
    ) -> RollbackReceipt:
        """Bounded receipted rollback to legacy authority (process-local)."""

        with self._lock:
            if execution is None:
                if self._last_execution is None:
                    raise CutoverBlockedError(
                        "no execution receipt available for rollback",
                        reason="missing_execution_receipt",
                    )
                exec_map = dict(self._last_execution.as_mapping())
            elif isinstance(execution, ExecutionReceipt):
                exec_map = dict(execution.as_mapping())
            else:
                exec_map = dict(execution)

            birth = (
                process_birth
                if isinstance(process_birth, ProcessBirth)
                else ProcessBirth.from_mapping(process_birth)
            )
            fence = (
                generation
                if isinstance(generation, GenerationFence)
                else GenerationFence.from_mapping(generation)
            )
            if exec_map.get("generation_fingerprint") != fence.fingerprint():
                raise CutoverBlockedError(
                    "rollback generation fence does not match execution receipt",
                    reason="rollback_generation_mismatch",
                )
            if exec_map.get("process_birth_fingerprint") != birth.fingerprint():
                raise CutoverBlockedError(
                    "rollback process birth does not match execution receipt",
                    reason="rollback_process_birth_mismatch",
                )
            actor = _require_safe_token(actor_identity, field="actor_identity")
            if str(exec_map.get("actor_identity") or "") != actor:
                raise CutoverBlockedError(
                    "rollback actor does not match execution actor",
                    reason="rollback_actor_mismatch",
                )
            if bool(exec_map.get("dry_run")):
                raise CutoverBlockedError(
                    "cannot rollback a dry-run execution",
                    reason="rollback_of_dry_run",
                )

            before = authority_mode()
            if before is not CutoverAuthorityMode.LAKE_PRIMARY:
                raise CutoverBlockedError(
                    "rollback requires current authority lake_primary",
                    reason="rollback_not_lake_primary",
                )

            with _STATE_LOCK:
                _PROCESS_STATE.mode = CutoverAuthorityMode.LEGACY
                _PROCESS_STATE.promoted_by_execution_id = None
                _PROCESS_STATE.decision_cid = None
                # production_authority_mutated stays False
                _PROCESS_STATE.production_authority_mutated = False

            rollback_id = _new_id("rollback")
            rolled_back_at = _utc_now()
            body = {
                "schema": ROLLBACK_RECEIPT_SCHEMA,
                "rollback_id": rollback_id,
                "execution_id": exec_map["execution_id"],
                "decision_cid": exec_map["decision_cid"],
                "from_authority": CutoverAuthorityMode.LAKE_PRIMARY.value,
                "to_authority": CutoverAuthorityMode.LEGACY.value,
                "generation_fingerprint": fence.fingerprint(),
                "repository_tree_id": fence.repository_tree_id,
                "actor_identity": actor,
                "process_birth_fingerprint": birth.fingerprint(),
                "bounded_by_execution": True,
                "bounded_by_rollback_fence": exec_map.get("rollback_fence_id"),
                "rolled_back_at": rolled_back_at,
                "program_id": PROGRAM_ID,
                "owner_task_id": OWNER_TASK_ID,
            }
            signature = _digest_of(body)
            receipt_cid = _digest_of({**body, "signature": signature})
            receipt = RollbackReceipt(
                schema=ROLLBACK_RECEIPT_SCHEMA,
                rollback_id=rollback_id,
                receipt_cid=receipt_cid,
                execution_id=str(exec_map["execution_id"]),
                decision_cid=str(exec_map["decision_cid"]),
                from_authority=CutoverAuthorityMode.LAKE_PRIMARY.value,
                to_authority=CutoverAuthorityMode.LEGACY.value,
                generation_fingerprint=fence.fingerprint(),
                repository_tree_id=fence.repository_tree_id,
                actor_identity=actor,
                process_birth_fingerprint=birth.fingerprint(),
                bounded_by_execution=True,
                rolled_back_at=rolled_back_at,
                signature=signature,
            )
            self._last_rollback = receipt
            with _STATE_LOCK:
                _PROCESS_STATE.last_rollback_receipt = dict(receipt.as_mapping())
            return receipt


def get_cutover_controller() -> CutoverController:
    """Return the process-local cutover controller (create on first use)."""

    controller = getattr(_THREAD_LOCAL, "controller", None)
    if controller is None:
        controller = CutoverController()
        _THREAD_LOCAL.controller = controller
    return controller


def set_active_controller(controller: CutoverController | None) -> None:
    _THREAD_LOCAL.controller = controller


def get_active_controller() -> CutoverController | None:
    return getattr(_THREAD_LOCAL, "controller", None)


def dry_run_cutover(command: CutoverCommand, **kwargs: Any) -> CutoverDryRunResult:
    return get_cutover_controller().dry_run(command, **kwargs)


def invoke_cutover(
    command: CutoverCommand, **kwargs: Any
) -> ExecutionReceipt | CutoverDryRunResult:
    return get_cutover_controller().invoke(command, **kwargs)


def rollback_cutover(**kwargs: Any) -> RollbackReceipt:
    return get_cutover_controller().rollback(**kwargs)


# ---------------------------------------------------------------------------
# Self-check / install report
# ---------------------------------------------------------------------------


def self_check() -> dict[str, Any]:
    """Inert install / self-check report (no I/O, no authority mutation)."""

    return {
        "ok": True,
        "schema": CUTOVER_COMMAND_SCHEMA,
        "owner_task_id": OWNER_TASK_ID,
        "promotion_gate_task_id": PROMOTION_GATE_TASK_ID,
        "plan_revision_task_id": PLAN_REVISION_TASK_ID,
        "generation_rollover_task_id": GENERATION_ROLLOVER_TASK_ID,
        "program_id": PROGRAM_ID,
        "domain": DOMAIN,
        "implementation_grants_no_authority": IMPLEMENTATION_GRANTS_NO_AUTHORITY,
        "production_authority_unchanged": production_authority_unchanged(),
        "authority_mode": authority_mode().value,
        "legacy_producers_enabled": legacy_producers_enabled(),
        "mutable_sidecar_authority_enabled": mutable_sidecar_authority_enabled(),
        "implicit_directory_scan_enabled": implicit_directory_scan_enabled(),
        "registered_producers": list_registered_producers(),
        "receipt_schemas": {
            "promotion_decision": PROMOTION_DECISION_SCHEMA,
            "execution": EXECUTION_RECEIPT_SCHEMA,
            "rollback": ROLLBACK_RECEIPT_SCHEMA,
            "inventory_scan": INVENTORY_SCAN_SCHEMA,
            "baseline": BASELINE_SCHEMA,
            "delta": DELTA_SCHEMA,
            "evidence": EVIDENCE_BUNDLE_SCHEMA,
        },
        "inventory_paths": (
            "fresh_exact_head_scan",
            "signed_baseline_plus_complete_content_addressed_delta",
        ),
        "gap_routing": {
            "plan_revision": PLAN_REVISION_TASK_ID,
            "generation_rollover": GENERATION_ROLLOVER_TASK_ID,
            "retry_stale_generation": False,
        },
    }


def implementation_self_check() -> dict[str, Any]:
    """Alias emphasizing that implementation completion is non-authoritative."""

    report = self_check()
    report["completing_dqk_100_alters_production_authority"] = False
    report["completing_dqk_100_disables_legacy_producer"] = False
    return report


# Reset on import so reloads cannot leave a promoted process-local mode.
reset_cutover_state()


# ---------------------------------------------------------------------------
# Manual-gate CLI (DQK-102 execute-promotion / verify-promotion)
# ---------------------------------------------------------------------------


PROMOTION_EXECUTION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-promotion-execution@1"
)
PROMOTION_OPERATOR_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-promotion-operator-receipt@1"
)


def _control_plan_to_fence_plan(plan_root_cid: str) -> str:
    """Map a control-plane plan root (baguqeera/CID) to a sha256 fence token."""

    text = _bounded_text(plan_root_cid, field="plan_root_cid")
    if _SHA256_DIGEST.fullmatch(text):
        return text
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_control_repository_tree_id(value: str) -> tuple[str, str]:
    """Return (commit_oid, tree_oid) from a control-plane repository_tree_id."""

    text = _bounded_text(value, field="repository_tree_id")
    # Forms:
    #   repository:git-commit:<40>:tree:<40>
    #   <40 tree oid>
    if _GIT_OID.fullmatch(text):
        return ("", text)
    parts = text.split(":")
    if (
        len(parts) == 5
        and parts[0] == "repository"
        and parts[1] == "git-commit"
        and _GIT_OID.fullmatch(parts[2])
        and parts[3] == "tree"
        and _GIT_OID.fullmatch(parts[4])
    ):
        return (parts[2], parts[4])
    raise AuthorityCutoverError(
        "repository_tree_id must be repository:git-commit:<oid>:tree:<oid> "
        "or a 40-char tree oid"
    )


def load_operator_promotion_receipt(path: str | Path) -> dict[str, Any]:
    raw = Path(path).read_text(encoding="utf-8")
    if len(raw.encode("utf-8")) > 2 * 1024 * 1024:
        raise AuthorityCutoverError("promotion operator receipt exceeds size bound")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AuthorityCutoverError("promotion operator receipt is not JSON") from exc
    if not isinstance(payload, dict):
        raise AuthorityCutoverError("promotion operator receipt must be an object")
    if payload.get("schema") != PROMOTION_OPERATOR_RECEIPT_SCHEMA:
        raise AuthorityCutoverError(
            f"promotion operator receipt schema must be {PROMOTION_OPERATOR_RECEIPT_SCHEMA}"
        )
    if payload.get("accepted") is not True:
        raise AuthorityCutoverError("promotion operator receipt is not accepted")
    return payload


def execute_promotion_from_operator_receipt(
    receipt: Mapping[str, Any],
    *,
    expected_plan_root_cid: str,
    expected_repository_tree_id: str,
    now: datetime | None = None,
    execute: bool = True,
) -> dict[str, Any]:
    """Verify (and optionally execute process-local) promotion for DQK-102.

    Returns the sealed manual-gate typed output
    (``ipfs_datasets_py/ducklake-promotion-execution@1``).
    """

    control_plan = _bounded_text(
        expected_plan_root_cid, field="expected_plan_root_cid"
    )
    control_tree = _bounded_text(
        expected_repository_tree_id, field="expected_repository_tree_id"
    )
    if str(receipt.get("control_plan_root_cid") or "") != control_plan:
        raise AuthorityCutoverError("operator receipt plan root does not match gate")
    if str(receipt.get("control_repository_tree_id") or "") != control_tree:
        raise AuthorityCutoverError(
            "operator receipt repository tree does not match gate"
        )

    _commit_oid, tree_oid = _parse_control_repository_tree_id(control_tree)
    fence_plan = _control_plan_to_fence_plan(control_plan)

    decision_raw = receipt.get("decision")
    evidence_raw = receipt.get("evidence")
    birth_raw = receipt.get("process_birth")
    generation_raw = receipt.get("generation")
    scan_raw = receipt.get("exact_head_scan")
    if not all(
        isinstance(item, Mapping)
        for item in (decision_raw, evidence_raw, birth_raw, generation_raw, scan_raw)
    ):
        raise AuthorityCutoverError(
            "operator receipt missing decision/evidence/process_birth/"
            "generation/exact_head_scan objects"
        )

    # Rebind generation fence to the live control plan/tree mapping.
    gen_map = dict(generation_raw)
    gen_map["repository_tree_id"] = tree_oid
    gen_map["plan_root_cid"] = fence_plan
    fence = GenerationFence.from_mapping(gen_map)
    birth = ProcessBirth.from_mapping(dict(birth_raw))
    evidence = verify_evidence_bundle(
        dict(evidence_raw),
        now=now,
        expected_tree_id=tree_oid,
        expected_generation_id=fence.generation_id,
    )
    scan_map = dict(scan_raw)
    if scan_map.get("schema") != INVENTORY_SCAN_SCHEMA:
        raise AuthorityCutoverError("exact_head_scan schema is foreign")
    digests = scan_map.get("producer_digests")
    if not isinstance(digests, Mapping):
        raise AuthorityCutoverError("exact_head_scan producer_digests missing")
    sealed_proof = str(scan_map.get("inventory_proof_cid") or "")
    decision_proof = str(dict(decision_raw).get("inventory_proof_cid") or "")
    if not sealed_proof or sealed_proof != decision_proof:
        raise AuthorityCutoverError(
            "exact_head_scan inventory proof does not match decision"
        )
    scan_head = str(scan_map.get("head_tree_id") or "")
    if scan_head != tree_oid:
        raise AuthorityCutoverError(
            f"exact_head_scan head_tree_id {scan_head} != gate tree {tree_oid}"
        )
    # Pass the sealed scan mapping through; verify_inventory trusts its
    # inventory_proof_cid after basic head/digest binding checks.
    scan = scan_map

    actor = _require_safe_token(
        receipt.get("actor_identity") or dict(decision_raw).get("actor_identity"),
        field="actor_identity",
    )
    command = CutoverCommand(
        actor_identity=actor,
        process_birth=birth,
        generation=fence,
        decision=dict(decision_raw),
        evidence=evidence,
        head_tree_id=tree_oid,
        exact_head_scan=scan,
        dry_run=not execute,
        execute_process_local=bool(execute),
    )
    result = invoke_cutover(command, now=now)
    if isinstance(result, CutoverDryRunResult):
        if not result.ok:
            raise CutoverBlockedError(
                "promotion dry-run blocked: " + ";".join(result.blockers),
                reason="dry_run_blocked",
            )
        execution_receipt_cid = "sha256:" + ("0" * 64)
        authority_fence_id = result.generation_fingerprint
        decision_cid = result.decision_cid
        expires_at = evidence.expires_at
    else:
        execution_receipt_cid = result.receipt_cid
        authority_fence_id = result.rollback_fence_id
        decision_cid = result.decision_cid
        # Execution receipts do not carry expiry; bind evidence expiry.
        expires_at = evidence.expires_at

    risk = receipt.get("risk_acceptance")
    if not isinstance(risk, Mapping) or risk.get("quack_beta_not_production_ready") is not True:
        raise AuthorityCutoverError(
            "operator receipt must explicitly accept Quack beta/not-production-ready risk"
        )

    output = {
        "schema": PROMOTION_EXECUTION_SCHEMA,
        "accepted": True,
        "decision_cid": decision_cid,
        "execution_receipt_cid": execution_receipt_cid,
        "authority_fence_id": authority_fence_id,
        "plan_root_cid": control_plan,
        "repository_tree_id": control_tree,
        "expires_at": expires_at,
        "requested_transition": "legacy->lake_primary",
        "production_authority_mutated": False,
        "process_local_promoted": bool(execute),
        "owner_task_id": OWNER_TASK_ID,
        "gate_task_id": PROMOTION_GATE_TASK_ID,
        "program_id": PROGRAM_ID,
        "risk_acceptance": dict(risk),
    }
    return output


def verify_promotion_operator_receipt(
    receipt: Mapping[str, Any],
    *,
    expected_plan_root_cid: str,
    expected_repository_tree_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Independent verify path used by the DQK-102 authority adapter."""

    return execute_promotion_from_operator_receipt(
        receipt,
        expected_plan_root_cid=expected_plan_root_cid,
        expected_repository_tree_id=expected_repository_tree_id,
        now=now,
        execute=False,
    )


def build_parser() -> Any:
    import argparse

    parser = argparse.ArgumentParser(
        prog="ipfs_datasets_py.ducklake.cutover",
        description=(
            "Fenced DuckLake authority cutover controls (DQK-100/DQK-102). "
            "Implementation grants no production authority."
        ),
    )
    sub = parser.add_subparsers(dest="command")

    check = sub.add_parser("verify-promotion", help="hermetic or receipt-bound verify")
    check.add_argument("--check", action="store_true", help="self-check only")
    check.add_argument("--receipt", type=str, default="", help="operator receipt JSON")
    check.add_argument("--plan-root", type=str, default="")
    check.add_argument("--repository-tree", type=str, default="")
    check.add_argument("--json", action="store_true")

    execute = sub.add_parser(
        "execute-promotion",
        help="verify + process-local execute for DQK-102 manual gate",
    )
    execute.add_argument("--receipt", type=str, required=True)
    execute.add_argument("--plan-root", type=str, required=True)
    execute.add_argument("--repository-tree", type=str, required=True)
    execute.add_argument("--json", action="store_true")
    execute.add_argument(
        "--dry-run",
        action="store_true",
        help="verify only (no process-local authority flip)",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not args.command:
        parser.print_help()
        return 2

    def _emit(payload: Mapping[str, Any]) -> None:
        sys.stdout.write(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            + "\n"
        )

    try:
        if args.command == "verify-promotion":
            if args.check and not args.receipt:
                _emit(self_check())
                return 0
            if not args.receipt:
                raise AuthorityCutoverError("--receipt is required unless --check is set")
            receipt = load_operator_promotion_receipt(args.receipt)
            payload = verify_promotion_operator_receipt(
                receipt,
                expected_plan_root_cid=str(args.plan_root or receipt.get("control_plan_root_cid") or ""),
                expected_repository_tree_id=str(
                    args.repository_tree or receipt.get("control_repository_tree_id") or ""
                ),
            )
            _emit(payload)
            return 0 if payload.get("accepted") is True else 1

        if args.command == "execute-promotion":
            receipt = load_operator_promotion_receipt(args.receipt)
            payload = execute_promotion_from_operator_receipt(
                receipt,
                expected_plan_root_cid=str(args.plan_root),
                expected_repository_tree_id=str(args.repository_tree),
                execute=not bool(args.dry_run),
            )
            _emit(payload)
            return 0 if payload.get("accepted") is True else 1
    except AuthorityCutoverError as exc:
        _emit({"ok": False, "error": str(exc), "schema": PROMOTION_EXECUTION_SCHEMA})
        return 1
    except OSError as exc:
        _emit({"ok": False, "error": str(exc), "schema": PROMOTION_EXECUTION_SCHEMA})
        return 1

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
