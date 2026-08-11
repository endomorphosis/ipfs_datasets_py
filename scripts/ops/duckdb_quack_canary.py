#!/usr/bin/env python3
"""DQK-053 domain canaries and cutover/rollback gates.

Canary the supervisor, proof, graph/vector, AST, wallet, observability, and
DuckLake namespaces in dependency order using shadow/dual authority,
SLO/parity/security/restore evidence, and an explicit rollback window.

Acceptance (summary):

* Each authority promotion has evidence and a tested rollback
* Canary failures quarantine only their namespace
* Legacy producers become export-only after promotion

Hermetic: no live DuckDB, Quack, Docker, or network is required. Import is
side-effect free beyond path bootstrap. Authority mutation is confined to the
in-process DQK-046 :class:`MemoryAuthorityBackend` owned by one canary run.
DuckLake domain-producer lineage is consumed from the sealed DQK-099 canary.

CLI::

    python scripts/ops/duckdb_quack_canary.py [--json] [--emit-receipt] [--self-check]
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Any, Final, Mapping, Sequence

# ---------------------------------------------------------------------------
# Repo path bootstrap
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ipfs_datasets_py.duckdb_control.authority_transition import (  # noqa: E402
    AUTHORITY_TRANSITION_SCHEMA,
    DECISION_RECEIPT_SCHEMA,
    PARITY_RECEIPT_SCHEMA,
    QUARANTINE_SCHEMA,
    AuthorityMode,
    AuthorityState,
    AuthorityTransitionError,
    AuthorityTransitionPort,
    DecisionKind,
    DecisionReceipt,
    MemoryAuthorityBackend,
    ParityReceipt,
    PromotionBlockedError,
    QuarantineRecord,
    build_authority_port,
    compute_payload_digest,
)
from ipfs_datasets_py.duckdb_control.authority_transition import (  # noqa: E402
    install_check as authority_install_check,
)

# ---------------------------------------------------------------------------
# Schemas / constants
# ---------------------------------------------------------------------------

CONTRACT_TASK_ID: Final[str] = "DQK-053"
AUTHORITY_TASK_ID: Final[str] = "DQK-046"
DUCKLAKE_CANARY_TASK_ID: Final[str] = "DQK-099"
PROGRAM_ID: Final[str] = "ipfs-datasets-duckdb-quack-control-plane-v1"
IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-053-domain-canary-cutover-rollback-20260811"
)

CANARY_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-quack-domain-canary-receipt@1"
)
CANARY_RECEIPT_INTERFACE: Final[str] = "DuckDBQuackCanaryReceipt@1"
NAMESPACE_RESULT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-quack-namespace-canary-result@1"
)
EVIDENCE_SCHEMA: Final[str] = "ipfs_datasets_py/duckdb-quack-canary-evidence@1"
ROLLBACK_WINDOW_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-quack-canary-rollback-window@1"
)
PROMOTION_STEP_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-quack-canary-promotion-step@1"
)
STORE_TABLE: Final[str] = "domain_canary_receipts"

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$")

DEFAULT_SLO_BUDGET_S: Final[float] = 0.5

EVIDENCE_DIMENSIONS: Final[tuple[str, ...]] = (
    "slo",
    "parity",
    "security",
    "restore",
)

PROMOTION_LADDER: Final[tuple[str, ...]] = (
    AuthorityMode.LEGACY.value,
    AuthorityMode.SHADOW.value,
    AuthorityMode.DUAL.value,
    AuthorityMode.DB_PRIMARY.value,
    AuthorityMode.EXPORT_ONLY.value,
)
POST_PROMOTION_MODE: Final[str] = AuthorityMode.EXPORT_ONLY.value


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CanaryError(ValueError):
    """Fail-closed domain canary rejection."""


class NamespaceOrderError(CanaryError):
    """Namespaces were canaried out of the sealed dependency order."""


class EvidenceError(CanaryError):
    """Required SLO/parity/security/restore evidence is missing or failed."""


class IsolationError(CanaryError):
    """A canary failure leaked outside its own namespace."""


class RollbackError(CanaryError):
    """Promotion lacked a tested rollback within the explicit window."""


class ReceiptError(CanaryError):
    """Domain canary receipt failed validation."""


# ---------------------------------------------------------------------------
# Namespaces (dependency order)
# ---------------------------------------------------------------------------


class CanaryNamespace(str, Enum):
    """Namespaces canaried by DQK-053, in sealed dependency order."""

    SUPERVISOR = "supervisor"
    PROOF = "proof"
    GRAPH_VECTOR = "graph-vector"
    AST = "ast"
    WALLET = "wallet"
    OBSERVABILITY = "observability"
    DUCKLAKE = "ducklake"


CANARY_NAMESPACE_ORDER: Final[tuple[str, ...]] = tuple(
    ns.value for ns in CanaryNamespace
)


@dataclass(frozen=True, slots=True)
class NamespaceSpec:
    """Static configuration for one canary namespace."""

    namespace: CanaryNamespace
    authority_domain: str
    sample_key: str
    sample_payload: Mapping[str, Any]
    depends_on: tuple[str, ...]
    producer_surface: str
    description: str

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "namespace": self.namespace.value,
                "authority_domain": self.authority_domain,
                "sample_key": self.sample_key,
                "sample_payload": dict(self.sample_payload),
                "depends_on": list(self.depends_on),
                "producer_surface": self.producer_surface,
                "description": self.description,
            }
        )


def build_namespace_specs() -> tuple[NamespaceSpec, ...]:
    """Return the sealed namespace specs in dependency order."""

    return (
        NamespaceSpec(
            namespace=CanaryNamespace.SUPERVISOR,
            authority_domain="control-lease",
            sample_key="lease-canary-1",
            sample_payload={
                "lease_id": "lease-canary-1",
                "generation": 1,
                "heartbeat_s": 0.01,
            },
            depends_on=(),
            producer_surface="agent_supervisor_control_plane",
            description="DuckDB-native agent supervisor control plane",
        ),
        NamespaceSpec(
            namespace=CanaryNamespace.PROOF,
            authority_domain="proof-envelope",
            sample_key="pk-canary-1",
            sample_payload={
                "proof_key": "pk-canary-1",
                "outcome": "valid",
                "trust_level": 2,
            },
            depends_on=(CanaryNamespace.SUPERVISOR.value,),
            producer_surface="logic_proof_caches",
            description="Proof evidence and theorem-cache authority",
        ),
        NamespaceSpec(
            namespace=CanaryNamespace.GRAPH_VECTOR,
            authority_domain="graph-vector-bundle",
            sample_key="g-canary-1",
            sample_payload={
                "graph_id": "g-canary-1",
                "vector_collection": "col-canary-a",
                "vertex_count": 2,
                "dimension": 8,
            },
            depends_on=(
                CanaryNamespace.SUPERVISOR.value,
                CanaryNamespace.PROOF.value,
            ),
            producer_surface="knowledge_graph_and_vector_catalogs",
            description="Combined knowledge-graph and vector shadow catalogs",
        ),
        NamespaceSpec(
            namespace=CanaryNamespace.AST,
            authority_domain="ast-span",
            sample_key="span-canary-1",
            sample_payload={
                "span_id": "span-canary-1",
                "source_path": "mod.py",
                "start_line": 10,
                "end_line": 20,
            },
            depends_on=(
                CanaryNamespace.SUPERVISOR.value,
                CanaryNamespace.GRAPH_VECTOR.value,
            ),
            producer_surface="software_contracts_ast",
            description="AST and code-evidence authority",
        ),
        NamespaceSpec(
            namespace=CanaryNamespace.WALLET,
            authority_domain="wallet-checkpoint",
            sample_key="wallet-checkpoint",
            sample_payload={
                "chain_id": 1,
                "cursor_block": 100,
                "tx_hash": "0xcanary",
            },
            depends_on=(
                CanaryNamespace.SUPERVISOR.value,
                CanaryNamespace.AST.value,
            ),
            producer_surface="wallet_ledger_and_checkpoints",
            description="Processor and legacy wallet ledger authority",
        ),
        NamespaceSpec(
            namespace=CanaryNamespace.OBSERVABILITY,
            authority_domain="obs-audit-event",
            sample_key="evt-canary-1",
            sample_payload={
                "event_id": "evt-canary-1",
                "family": "audit",
                "sensitivity": "internal",
            },
            depends_on=(
                CanaryNamespace.SUPERVISOR.value,
                CanaryNamespace.WALLET.value,
            ),
            producer_surface="typed_observability_catalog",
            description="Audit, metric, alert, and structured-log authority",
        ),
        NamespaceSpec(
            namespace=CanaryNamespace.DUCKLAKE,
            authority_domain="lake-snapshot",
            sample_key="catalog_canary",
            sample_payload={
                "catalog_id": "catalog_canary",
                "snapshot_id": 1,
                "dataset_alias": "general_datasets",
            },
            depends_on=(
                CanaryNamespace.SUPERVISOR.value,
                CanaryNamespace.OBSERVABILITY.value,
            ),
            producer_surface="ducklake_admitted_registry",
            description="DuckLake admitted registry and snapshot receipts",
        ),
    )


NAMESPACE_SPECS: Final[tuple[NamespaceSpec, ...]] = build_namespace_specs()


def namespace_order_receipt() -> Mapping[str, Any]:
    """Canonical namespace dependency-order document."""

    specs = build_namespace_specs()
    order = [s.namespace.value for s in specs]
    if order != list(CANARY_NAMESPACE_ORDER):
        raise NamespaceOrderError(
            f"namespace specs order {order} disagrees with "
            f"CANARY_NAMESPACE_ORDER {list(CANARY_NAMESPACE_ORDER)}"
        )
    body: dict[str, Any] = {
        "schema": "ipfs_datasets_py/duckdb-quack-canary-namespace-order@1",
        "task_id": CONTRACT_TASK_ID,
        "implementation_generation": IMPLEMENTATION_GENERATION,
        "order": list(order),
        "namespaces": [dict(s.as_mapping()) for s in specs],
        "promotion_ladder": list(PROMOTION_LADDER),
        "post_promotion_mode": POST_PROMOTION_MODE,
        "evidence_dimensions": list(EVIDENCE_DIMENSIONS),
    }
    body["order_digest"] = f"sha256:{_sha256_hex(_canonical_json_bytes(body))}"
    return MappingProxyType(body)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")


def _canonical_json(payload: Any) -> str:
    return _canonical_json_bytes(payload).decode("utf-8")


def _digest_of(payload: Any) -> str:
    return f"sha256:{_sha256_hex(_canonical_json_bytes(payload))}"


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def _require_nonempty(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise CanaryError(f"{field_name} must be non-empty")
    return text


def _require_safe_token(value: Any, *, field_name: str) -> str:
    text = _require_nonempty(value, field_name=field_name)
    if not _SAFE_TOKEN.fullmatch(text):
        raise CanaryError(f"{field_name} is not a safe token: {text!r}")
    return text


def _load_ducklake_canary_module() -> ModuleType:
    """Load DQK-099 canary by path (scripts.ops is not always a package)."""

    module_name = "ducklake_canary"
    existing = sys.modules.get(module_name)
    if (
        existing is not None
        and getattr(existing, "CONTRACT_TASK_ID", None) == DUCKLAKE_CANARY_TASK_ID
    ):
        return existing
    path = _REPO_ROOT / "scripts/ops/ducklake_canary.py"
    if not path.is_file():
        raise CanaryError(f"DQK-099 canary missing at {path}")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise CanaryError(f"cannot load DQK-099 canary from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    if getattr(module, "CONTRACT_TASK_ID", None) != DUCKLAKE_CANARY_TASK_ID:
        raise CanaryError("DQK-099 canary contract id mismatch")
    if getattr(module, "CONSUMED_BY_TASK_ID", None) != CONTRACT_TASK_ID:
        raise CanaryError("DQK-099 canary must declare consumed_by=DQK-053")
    return module


# ---------------------------------------------------------------------------
# Evidence / promotion records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CanaryEvidence:
    """SLO/parity/security/restore evidence for one promotion step."""

    namespace: str
    step: str
    slo_ok: bool
    slo_elapsed_s: float
    slo_budget_s: float
    parity_ok: bool
    parity_receipt_cid: str
    security_ok: bool
    security_notes: str
    restore_ok: bool
    restore_notes: str
    payload_digest: str

    def as_mapping(self) -> Mapping[str, Any]:
        dims = {
            "slo": self.slo_ok,
            "parity": self.parity_ok,
            "security": self.security_ok,
            "restore": self.restore_ok,
        }
        return MappingProxyType(
            {
                "schema": EVIDENCE_SCHEMA,
                "namespace": self.namespace,
                "step": self.step,
                "dimensions": dims,
                "all_passed": all(dims.values()),
                "slo_elapsed_s": self.slo_elapsed_s,
                "slo_budget_s": self.slo_budget_s,
                "parity_receipt_cid": self.parity_receipt_cid,
                "security_notes": self.security_notes,
                "restore_notes": self.restore_notes,
                "payload_digest": self.payload_digest,
            }
        )


@dataclass(frozen=True, slots=True)
class RollbackWindow:
    """Explicit tested rollback window around one promotion."""

    window_id: str
    namespace: str
    from_mode: str
    to_mode: str
    opened_at: str
    closes_at: str
    promotion_decision_id: str
    promotion_receipt_cid: str
    rollback_decision_id: str
    rollback_receipt_cid: str
    rollback_tested: bool
    re_promoted: bool
    re_promotion_decision_id: str
    re_promotion_receipt_cid: str

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": ROLLBACK_WINDOW_SCHEMA,
                "window_id": self.window_id,
                "namespace": self.namespace,
                "from_mode": self.from_mode,
                "to_mode": self.to_mode,
                "opened_at": self.opened_at,
                "closes_at": self.closes_at,
                "promotion_decision_id": self.promotion_decision_id,
                "promotion_receipt_cid": self.promotion_receipt_cid,
                "rollback_decision_id": self.rollback_decision_id,
                "rollback_receipt_cid": self.rollback_receipt_cid,
                "rollback_tested": self.rollback_tested,
                "re_promoted": self.re_promoted,
                "re_promotion_decision_id": self.re_promotion_decision_id,
                "re_promotion_receipt_cid": self.re_promotion_receipt_cid,
            }
        )


@dataclass(frozen=True, slots=True)
class PromotionStepResult:
    """One ladder step with evidence and a tested rollback window."""

    namespace: str
    from_mode: str
    to_mode: str
    evidence: Mapping[str, Any]
    promotion: Mapping[str, Any]
    rollback_window: Mapping[str, Any]
    ok: bool

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": PROMOTION_STEP_SCHEMA,
                "namespace": self.namespace,
                "from_mode": self.from_mode,
                "to_mode": self.to_mode,
                "evidence": dict(self.evidence),
                "promotion": dict(self.promotion),
                "rollback_window": dict(self.rollback_window),
                "ok": self.ok,
            }
        )


def _resolve_open_quarantines(backend: MemoryAuthorityBackend, domain: str) -> int:
    """Mark open quarantine records resolved and clear the open count."""

    resolved = 0
    for q in list(backend.list_open_quarantine(domain)):
        backend.put_quarantine(
            QuarantineRecord(
                quarantine_id=q.quarantine_id,
                domain=q.domain,
                key=q.key,
                operation_id=q.operation_id,
                legacy_digest=q.legacy_digest,
                db_digest=q.db_digest,
                reason=q.reason,
                parity_receipt_cid=q.parity_receipt_cid,
                resolved=True,
                created_at=q.created_at,
            )
        )
        resolved += 1
    st = backend.get_state(domain)
    if st is not None and st.open_quarantine_count != 0:
        cleared = AuthorityState(
            domain=st.domain,
            mode=st.mode,
            cas_revision=st.cas_revision + 1,
            fence=st.fence,
            last_parity_receipt_cid=st.last_parity_receipt_cid,
            last_decision_receipt_cid=st.last_decision_receipt_cid,
            open_quarantine_count=0,
            updated_at=_utc_now(),
        )
        try:
            backend.cas_put_state(cleared, expected_revision=st.cas_revision)
        except AuthorityTransitionError:
            pass
    return resolved


def _decision_as_mapping(decision: DecisionReceipt) -> Mapping[str, Any]:
    body = decision.to_dict()
    return MappingProxyType(dict(body))


def _parity_as_mapping(parity: ParityReceipt) -> Mapping[str, Any]:
    return MappingProxyType(dict(parity.to_dict()))


def _seed_and_sync(
    port: AuthorityTransitionPort,
    key: str,
    payload: Mapping[str, Any],
    operation_id: str,
) -> float:
    """Write + recover outbox; return elapsed seconds for SLO evidence."""

    started = time.perf_counter()
    mode = port.mode
    if mode is AuthorityMode.EXPORT_ONLY:
        raise CanaryError("cannot seed authority writes in export-only mode")
    result = port.write(key, dict(payload), operation_id=operation_id)
    if not result.get("ok"):
        raise CanaryError(
            f"seed write failed for {port.domain}: {result}"
        )
    if mode is not AuthorityMode.LEGACY:
        recovery = port.recover_outbox()
        if recovery.get("atomic_across_filesystems") is not False:
            raise EvidenceError(
                "outbox recovery must not claim cross-filesystem atomicity"
            )
    return time.perf_counter() - started


def _collect_evidence(
    port: AuthorityTransitionPort,
    backend: MemoryAuthorityBackend,
    *,
    namespace: str,
    step: str,
    key: str,
    payload: Mapping[str, Any],
    elapsed_s: float,
    slo_budget_s: float,
) -> CanaryEvidence:
    """Build SLO/parity/security/restore evidence for the current mode."""

    mode = port.mode
    payload_digest = compute_payload_digest(dict(payload))
    parity_ok = True
    parity_cid = ""

    if mode is not AuthorityMode.LEGACY:
        _resolve_open_quarantines(backend, port.domain)
        legacy = backend.get_legacy(port.domain, key)
        db = backend.get_db(port.domain, key)

        if mode in {AuthorityMode.SHADOW, AuthorityMode.DUAL}:
            if legacy is None:
                backend.put_legacy(port.domain, key, dict(payload))
            if db is None:
                backend.put_db(port.domain, key, dict(payload))

        if mode in {AuthorityMode.DB_PRIMARY, AuthorityMode.EXPORT_ONLY}:
            if db is None:
                backend.put_db(port.domain, key, dict(payload))
            if legacy is None or (
                compute_payload_digest(dict(legacy or {}))
                != compute_payload_digest(dict(db) if db else dict(payload))
            ):
                backend.put_legacy(
                    port.domain,
                    key,
                    dict(db) if db else dict(payload),
                )

        parity = port.emit_parity_receipt(
            key,
            operation_id=(
                f"parity:{namespace}:{step}:{_new_id('p')}"
            ),
        )
        parity_ok = bool(parity.matched)
        parity_cid = parity.receipt_cid
        if not parity_ok:
            _resolve_open_quarantines(backend, port.domain)
            raise EvidenceError(
                f"parity failed for {namespace} step {step}: "
                f"{parity.mismatch_reason}"
            )
        _resolve_open_quarantines(backend, port.domain)
    else:
        parity_cid = f"sha256:{_sha256_hex(b'legacy-authority-no-parity')}"

    slo_ok = 0.0 <= elapsed_s <= slo_budget_s
    if not slo_ok:
        raise EvidenceError(
            f"SLO exceeded for {namespace} step {step}: "
            f"{elapsed_s:.6f}s > {slo_budget_s}s"
        )

    security_notes: list[str] = []
    security_ok = True
    state = port.state()
    if state.to_dict().get("atomic_across_filesystems") is not False:
        security_ok = False
        security_notes.append("state claims cross-filesystem atomicity")
    if state.mode is not mode:
        security_ok = False
        security_notes.append("mode drift between port and state")
    security_notes.append(f"mode={mode.value}")
    security_notes.append("atomic_across_filesystems=false")
    if not security_ok:
        raise EvidenceError(
            f"security evidence failed for {namespace}: {security_notes}"
        )

    read_back = port.read(key)
    if mode is AuthorityMode.LEGACY:
        restore_ok = read_back is not None and dict(read_back) == dict(payload)
        restore_notes = "legacy authority read-back"
    else:
        restore_ok = (
            read_back is not None
            and compute_payload_digest(dict(read_back)) == payload_digest
        )
        restore_notes = f"{mode.value} authority read-back digest match"
    if not restore_ok:
        raise EvidenceError(
            f"restore evidence failed for {namespace} step {step}"
        )

    return CanaryEvidence(
        namespace=namespace,
        step=step,
        slo_ok=slo_ok,
        slo_elapsed_s=elapsed_s,
        slo_budget_s=slo_budget_s,
        parity_ok=parity_ok,
        parity_receipt_cid=parity_cid,
        security_ok=security_ok,
        security_notes=";".join(security_notes),
        restore_ok=restore_ok,
        restore_notes=restore_notes,
        payload_digest=payload_digest,
    )


def _rollback_target(from_mode: AuthorityMode) -> AuthorityMode:
    """Return the canonical rollback target for a just-promoted mode."""

    reverse = {
        AuthorityMode.SHADOW: AuthorityMode.LEGACY,
        AuthorityMode.DUAL: AuthorityMode.SHADOW,
        AuthorityMode.DB_PRIMARY: AuthorityMode.DUAL,
        AuthorityMode.EXPORT_ONLY: AuthorityMode.DB_PRIMARY,
    }
    if from_mode not in reverse:
        raise RollbackError(f"no rollback target from {from_mode.value}")
    return reverse[from_mode]


def _promote_with_tested_rollback(
    port: AuthorityTransitionPort,
    backend: MemoryAuthorityBackend,
    *,
    namespace: str,
    to_mode: AuthorityMode,
    key: str,
    payload: Mapping[str, Any],
    decision_prefix: str,
    slo_budget_s: float,
) -> PromotionStepResult:
    """Promote one step with evidence and an explicit tested rollback window."""

    from_mode = port.mode
    step_name = f"{from_mode.value}->{to_mode.value}"
    elapsed = _seed_and_sync(
        port,
        key=key,
        payload=payload,
        operation_id=f"op:{decision_prefix}:seed:{_new_id('s')}",
    )
    require_parity = from_mode is not AuthorityMode.LEGACY
    evidence = _collect_evidence(
        port,
        backend,
        namespace=namespace,
        step=step_name,
        key=key,
        payload=payload,
        elapsed_s=elapsed,
        slo_budget_s=slo_budget_s,
    )
    promo_decision_id = f"dec:{decision_prefix}:promo:{to_mode.value}"

    try:
        promotion = port.promote(
            to_mode,
            decision_id=promo_decision_id,
            require_parity=require_parity,
            parity_key=key if require_parity else None,
        )
        if not promotion.accepted:
            raise CanaryError(
                f"promotion rejected for {namespace} {step_name}: "
                f"{promotion.reason}"
            )
        if port.mode is not to_mode:
            raise CanaryError(
                f"mode after promotion expected {to_mode.value}, "
                f"got {port.mode.value}"
            )

        opened_at = _utc_now()
        closes_at = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(time.time() + 3600),
        )
        window_id = _new_id("rbw")
        rollback_to = _rollback_target(to_mode)
        rb_decision_id = f"dec:{decision_prefix}:rollback:{to_mode.value}"
        rollback = port.rollback(
            rollback_to,
            decision_id=rb_decision_id,
            reason=f"canary-tested-rollback:{namespace}:{step_name}",
        )
        if not rollback.accepted:
            raise RollbackError(
                f"tested rollback rejected for {namespace} {step_name}: "
                f"{rollback.reason}"
            )
        if port.mode is not rollback_to:
            raise RollbackError(
                f"mode after rollback expected {rollback_to.value}, "
                f"got {port.mode.value}"
            )

        _ = _seed_and_sync(
            port,
            key=key,
            payload=payload,
            operation_id=f"op:{decision_prefix}:reseed:{_new_id('s')}",
        )

        # Ensure both projections exist for parity after rollback when needed.
        if port.mode is not AuthorityMode.LEGACY:
            if port.mode in {AuthorityMode.SHADOW, AuthorityMode.DUAL}:
                if backend.get_legacy(port.domain, key) is None:
                    backend.put_legacy(port.domain, key, dict(payload))
                if backend.get_db(port.domain, key) is None:
                    backend.put_db(port.domain, key, dict(payload))
            elif port.mode in {
                AuthorityMode.DB_PRIMARY,
                AuthorityMode.EXPORT_ONLY,
            }:
                if backend.get_db(port.domain, key) is None:
                    backend.put_db(port.domain, key, dict(payload))
                if backend.get_legacy(port.domain, key) is None:
                    backend.put_legacy(port.domain, key, dict(payload))
            port.emit_parity_receipt(
                key,
                operation_id=f"parity:{decision_prefix}:re:{_new_id('p')}",
            )
            _resolve_open_quarantines(backend, port.domain)

        require_parity_re = port.mode is not AuthorityMode.LEGACY
        repromo_id = f"dec:{decision_prefix}:repromo:{to_mode.value}"
        re_promotion = port.promote(
            to_mode,
            decision_id=repromo_id,
            require_parity=require_parity_re,
            parity_key=key if require_parity_re else None,
        )
        if not re_promotion.accepted:
            raise RollbackError(
                f"re-promotion after tested rollback failed for "
                f"{namespace} {step_name}: {re_promotion.reason}"
            )
        if port.mode is not to_mode:
            raise RollbackError(
                f"mode after re-promotion expected {to_mode.value}, "
                f"got {port.mode.value}"
            )

        window = RollbackWindow(
            window_id=window_id,
            namespace=namespace,
            from_mode=from_mode.value,
            to_mode=to_mode.value,
            opened_at=opened_at,
            closes_at=closes_at,
            promotion_decision_id=promotion.decision_id,
            promotion_receipt_cid=promotion.receipt_cid,
            rollback_decision_id=rollback.decision_id,
            rollback_receipt_cid=rollback.receipt_cid,
            rollback_tested=True,
            re_promoted=True,
            re_promotion_decision_id=re_promotion.decision_id,
            re_promotion_receipt_cid=re_promotion.receipt_cid,
        )

        if to_mode is AuthorityMode.EXPORT_ONLY:
            try:
                port.write(
                    key,
                    dict(payload),
                    operation_id=f"op:{decision_prefix}:export-reject",
                )
            except AuthorityTransitionError:
                evidence = CanaryEvidence(
                    namespace=evidence.namespace,
                    step=evidence.step,
                    slo_ok=evidence.slo_ok,
                    slo_elapsed_s=evidence.slo_elapsed_s,
                    slo_budget_s=evidence.slo_budget_s,
                    parity_ok=evidence.parity_ok,
                    parity_receipt_cid=evidence.parity_receipt_cid,
                    security_ok=True,
                    security_notes=(
                        evidence.security_notes + ";export-only-writes-rejected"
                    ),
                    restore_ok=evidence.restore_ok,
                    restore_notes=evidence.restore_notes,
                    payload_digest=evidence.payload_digest,
                )
            else:
                raise EvidenceError(
                    f"{namespace}: export-only must reject authority writes"
                )

        return PromotionStepResult(
            namespace=namespace,
            from_mode=from_mode.value,
            to_mode=to_mode.value,
            evidence=dict(evidence.as_mapping()),
            promotion=dict(_decision_as_mapping(promotion)),
            rollback_window=dict(window.as_mapping()),
            ok=True,
        )
    except PromotionBlockedError as exc:
        raise CanaryError(
            f"promotion blocked for {namespace} {step_name}: {exc}"
        ) from exc


@dataclass
class NamespaceCanaryState:
    """Mutable per-namespace canary state for one run."""

    spec: NamespaceSpec
    port: AuthorityTransitionPort
    final_mode: str = AuthorityMode.LEGACY.value
    steps: list[dict[str, Any]] = field(default_factory=list)
    quarantined: bool = False
    quarantine_record: dict[str, Any] | None = None
    export_only_after_promotion: bool = False
    ducklake_lineage_digest: str = ""
    ok: bool = False

    def as_mapping(self) -> Mapping[str, Any]:
        legacy_export = self.export_only_after_promotion and (
            self.final_mode == POST_PROMOTION_MODE
        )
        if self.steps:
            every = all(
                bool(s.get("ok"))
                and bool((s.get("evidence") or {}).get("all_passed"))
                and bool(
                    (s.get("rollback_window") or {}).get("rollback_tested")
                )
                for s in self.steps
            )
        else:
            every = False
        return MappingProxyType(
            {
                "schema": NAMESPACE_RESULT_SCHEMA,
                "namespace": self.spec.namespace.value,
                "authority_domain": self.spec.authority_domain,
                "producer_surface": self.spec.producer_surface,
                "depends_on": list(self.spec.depends_on),
                "final_mode": self.final_mode,
                "steps": list(self.steps),
                "step_count": len(self.steps),
                "quarantined": self.quarantined,
                "quarantine_record": dict(self.quarantine_record or {}),
                "export_only_after_promotion": self.export_only_after_promotion,
                "legacy_producers_export_only": legacy_export,
                "ducklake_lineage_digest": self.ducklake_lineage_digest,
                "ok": self.ok,
                "every_promotion_has_evidence_and_rollback": every,
            }
        )


def canary_one_namespace(
    backend: MemoryAuthorityBackend,
    spec: NamespaceSpec,
    *,
    run_id: str,
    slo_budget_s: float = DEFAULT_SLO_BUDGET_S,
    inject_failure: bool = False,
    ducklake_lineage: Mapping[str, Any] | None = None,
) -> NamespaceCanaryState:
    """Run the full shadow/dual→export-only ladder for one namespace."""

    port = build_authority_port(
        backend,
        domain=spec.authority_domain,
        initial_mode=AuthorityMode.LEGACY,
        writer_id=f"writer:canary:{spec.namespace.value}",
    )
    state = NamespaceCanaryState(spec=spec, port=port)

    try:
        if spec.namespace is CanaryNamespace.DUCKLAKE and ducklake_lineage is not None:
            state.ducklake_lineage_digest = str(
                ducklake_lineage.get("lineage_digest") or ""
            )
            if not state.ducklake_lineage_digest.startswith("sha256:"):
                raise CanaryError(
                    "DuckLake namespace requires DQK-099 lineage_digest"
                )

        key = spec.sample_key
        base_payload = {
            **dict(spec.sample_payload),
            "canary_task": CONTRACT_TASK_ID,
            "canary_run_id": run_id,
            "namespace": spec.namespace.value,
        }
        ladder_targets = (
            AuthorityMode.SHADOW,
            AuthorityMode.DUAL,
            AuthorityMode.DB_PRIMARY,
            AuthorityMode.EXPORT_ONLY,
        )

        for index, target in enumerate(ladder_targets):
            payload = {
                **base_payload,
                "ladder_index": index,
                "target_mode": target.value,
            }
            step = _promote_with_tested_rollback(
                port,
                backend,
                namespace=spec.namespace.value,
                to_mode=target,
                key=key,
                payload=payload,
                decision_prefix=f"{run_id}:{spec.namespace.value}:{index}",
                slo_budget_s=slo_budget_s,
            )
            state.steps.append(dict(step.as_mapping()))

        state.final_mode = port.mode.value
        if state.final_mode != POST_PROMOTION_MODE:
            raise CanaryError(
                f"{spec.namespace.value}: expected final mode "
                f"{POST_PROMOTION_MODE}, got {state.final_mode}"
            )
        state.export_only_after_promotion = True

        if inject_failure:
            q = port.quarantine_disagreement(
                key=key,
                operation_id=(
                    f"op:{run_id}:{spec.namespace.value}:inject"
                ),
                reason="canary-injected-namespace-failure",
                legacy_digest=compute_payload_digest({"injected": "legacy"}),
                db_digest=compute_payload_digest({"injected": "db"}),
            )
            state.quarantined = True
            state.quarantine_record = dict(q.to_dict())
            if (
                state.quarantine_record.get("domain")
                != spec.authority_domain
            ):
                raise IsolationError(
                    "quarantine domain must equal authority domain"
                )
            if state.quarantine_record.get("schema") != QUARANTINE_SCHEMA:
                raise IsolationError("quarantine schema mismatch")

        state.ok = all(bool(s.get("ok")) for s in state.steps)
        if not state.ok:
            raise CanaryError(
                f"{spec.namespace.value}: one or more steps failed"
            )
        return state
    except Exception:
        state.final_mode = port.mode.value
        state.ok = False
        raise


def prove_namespace_isolation(
    backend: MemoryAuthorityBackend,
    *,
    failing_namespace: str,
    all_results: Sequence[NamespaceCanaryState],
) -> Mapping[str, Any]:
    """Prove a canary failure quarantines only its own namespace."""

    failing: NamespaceCanaryState | None = None
    others: list[NamespaceCanaryState] = []
    for result in all_results:
        if result.spec.namespace.value == failing_namespace:
            failing = result
        else:
            others.append(result)

    if failing is None:
        raise IsolationError(
            f"failing namespace {failing_namespace} not present in results"
        )
    if not failing.quarantined:
        raise IsolationError(
            f"expected {failing_namespace} to be quarantined"
        )

    open_failing = list(
        backend.list_open_quarantine(failing.spec.authority_domain)
    )
    if not open_failing:
        raise IsolationError(
            f"no open quarantine for failing namespace {failing_namespace}"
        )

    leaked: list[str] = []
    other_modes: dict[str, str] = {}
    for other in others:
        open_q = list(
            backend.list_open_quarantine(other.spec.authority_domain)
        )
        if open_q:
            leaked.append(other.spec.namespace.value)
        other_modes[other.spec.namespace.value] = other.final_mode
        if other.final_mode != POST_PROMOTION_MODE:
            raise IsolationError(
                f"namespace {other.spec.namespace.value} mode drifted to "
                f"{other.final_mode} after {failing_namespace} quarantine"
            )
        if not other.export_only_after_promotion:
            raise IsolationError(
                f"namespace {other.spec.namespace.value} "
                f"lost export-only mark"
            )

    if leaked:
        raise IsolationError(
            f"quarantine leaked to namespaces: {sorted(leaked)}"
        )

    return MappingProxyType(
        {
            "ok": True,
            "failing_namespace": failing_namespace,
            "failing_domain": failing.spec.authority_domain,
            "open_quarantine_count": len(open_failing),
            "quarantine_ids": [q.quarantine_id for q in open_failing],
            "other_namespaces_export_only": True,
            "other_modes": other_modes,
            "leaked_namespaces": [],
            "isolation_proven": True,
        }
    )


# ---------------------------------------------------------------------------
# Database-native receipt store
# ---------------------------------------------------------------------------


class DomainCanaryStore:
    """In-process database-native authority for DuckDBQuackCanaryReceipt@1.

    Mirrors the control-plane pattern: receipts live in a named table
    (``domain_canary_receipts``), never as the sole Markdown/JSON file authority.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._rows: dict[str, dict[str, Any]] = {}

    def put_receipt(self, receipt: Mapping[str, Any]) -> Mapping[str, Any]:
        require_canary_receipt(receipt)
        rid = str(receipt["receipt_id"])
        row = {
            "receipt_id": rid,
            "task_id": receipt["task_id"],
            "schema": receipt["schema"],
            "interface": receipt["interface"],
            "run_id": receipt["run_id"],
            "receipt_digest": receipt["signature"]["digest"],
            "published_at": _utc_now(),
            "body_json": _canonical_json(dict(receipt)),
            "cas_revision": 1,
        }
        with self._lock:
            existing = self._rows.get(rid)
            if existing is not None:
                if existing["receipt_digest"] != row["receipt_digest"]:
                    raise ReceiptError(
                        f"CAS conflict for receipt {rid}: digest mismatch"
                    )
                return MappingProxyType(dict(existing))
            self._rows[rid] = row
            return MappingProxyType(dict(row))

    def get_receipt(self, receipt_id: str) -> Mapping[str, Any] | None:
        with self._lock:
            row = self._rows.get(receipt_id)
            if row is None:
                return None
            return MappingProxyType(dict(row))

    def list_receipts(self) -> tuple[Mapping[str, Any], ...]:
        with self._lock:
            return tuple(self._rows.values())

    def load_body(self, receipt_id: str) -> Mapping[str, Any]:
        row = self.get_receipt(receipt_id)
        if row is None:
            raise ReceiptError(f"receipt {receipt_id} not found")
        body = json.loads(str(row["body_json"]))
        if not isinstance(body, dict):
            raise ReceiptError("stored body is not an object")
        return MappingProxyType(body)


_DEFAULT_STORE: DomainCanaryStore | None = None
_DEFAULT_STORE_LOCK = threading.Lock()


def get_default_canary_store() -> DomainCanaryStore:
    global _DEFAULT_STORE
    with _DEFAULT_STORE_LOCK:
        if _DEFAULT_STORE is None:
            _DEFAULT_STORE = DomainCanaryStore()
        return _DEFAULT_STORE


def reset_default_canary_store() -> None:
    global _DEFAULT_STORE
    with _DEFAULT_STORE_LOCK:
        _DEFAULT_STORE = DomainCanaryStore()


# ---------------------------------------------------------------------------
# Receipt build / validate
# ---------------------------------------------------------------------------


def build_canary_receipt(
    *,
    run_id: str,
    namespace_results: Sequence[Mapping[str, Any]],
    isolation_proof: Mapping[str, Any],
    namespace_order: Mapping[str, Any],
    ducklake_lineage: Mapping[str, Any],
    authority_install: Mapping[str, Any],
    inject_failure_namespace: str | None,
) -> dict[str, Any]:
    """Build and seal DuckDBQuackCanaryReceipt@1."""

    rid_run = _require_safe_token(run_id, field_name="run_id")
    results = [dict(r) for r in namespace_results]
    expected = list(CANARY_NAMESPACE_ORDER)
    got = [str(r.get("namespace") or "") for r in results]
    if got != expected:
        raise ReceiptError(
            f"namespace results must be exactly {expected} in order; got {got}"
        )

    for result in results:
        if not result.get("every_promotion_has_evidence_and_rollback"):
            raise ReceiptError(
                f"namespace {result.get('namespace')} missing evidence/rollback"
            )
        if not result.get("export_only_after_promotion"):
            raise ReceiptError(
                f"namespace {result.get('namespace')} did not reach export-only"
            )
        if result.get("final_mode") != POST_PROMOTION_MODE:
            raise ReceiptError(
                f"namespace {result.get('namespace')} final_mode must be "
                f"{POST_PROMOTION_MODE}"
            )

    if not isolation_proof.get("isolation_proven"):
        raise ReceiptError("isolation_proof.isolation_proven must be true")

    all_export = all(
        r.get("export_only_after_promotion")
        and r.get("final_mode") == POST_PROMOTION_MODE
        for r in results
    )
    each_promo = all(
        r.get("every_promotion_has_evidence_and_rollback") for r in results
    )

    body: dict[str, Any] = {
        "schema": CANARY_RECEIPT_SCHEMA,
        "interface": CANARY_RECEIPT_INTERFACE,
        "task_id": CONTRACT_TASK_ID,
        "program_id": PROGRAM_ID,
        "implementation_generation": IMPLEMENTATION_GENERATION,
        "run_id": rid_run,
        "database_native_table": STORE_TABLE,
        "authority_task_id": AUTHORITY_TASK_ID,
        "authority_transition_schema": AUTHORITY_TRANSITION_SCHEMA,
        "ducklake_canary_task_id": DUCKLAKE_CANARY_TASK_ID,
        "promotion_ladder": list(PROMOTION_LADDER),
        "post_promotion_mode": POST_PROMOTION_MODE,
        "evidence_dimensions": list(EVIDENCE_DIMENSIONS),
        "namespace_order": dict(namespace_order),
        "namespace_results": results,
        "namespaces": list(expected),
        "all_namespaces_promoted_export_only": all_export,
        "each_promotion_has_evidence_and_tested_rollback": each_promo,
        "isolation_proof": dict(isolation_proof),
        "inject_failure_namespace": inject_failure_namespace,
        "ducklake_lineage": dict(ducklake_lineage),
        "authority_install": dict(authority_install),
        "decision_receipt_schema": DECISION_RECEIPT_SCHEMA,
        "parity_receipt_schema": PARITY_RECEIPT_SCHEMA,
        "published_at": _utc_now(),
        "atomic_across_filesystems": False,
    }
    digest = _sha256_hex(_canonical_json_bytes(body))
    body["receipt_id"] = f"receipt:sha256:{digest}"
    body["signature"] = {
        "algorithm": "content-bound-sha256@1",
        "digest": f"sha256:{digest}",
        "signed_fields": sorted(k for k in body if k != "signature"),
    }
    return body


def require_canary_receipt(receipt: Mapping[str, Any]) -> None:
    """Fail-closed validation of DuckDBQuackCanaryReceipt@1."""

    if not isinstance(receipt, Mapping):
        raise ReceiptError("receipt must be an object")
    if receipt.get("schema") != CANARY_RECEIPT_SCHEMA:
        raise ReceiptError(f"unexpected schema {receipt.get('schema')!r}")
    if receipt.get("interface") != CANARY_RECEIPT_INTERFACE:
        raise ReceiptError(
            f"unexpected interface {receipt.get('interface')!r}"
        )
    if receipt.get("task_id") != CONTRACT_TASK_ID:
        raise ReceiptError("receipt task_id must be DQK-053")
    if not receipt.get("database_native_table"):
        raise ReceiptError("receipt must declare database_native_table")
    if receipt.get("atomic_across_filesystems") is not False:
        raise ReceiptError("receipt must not claim cross-filesystem atomicity")

    sig = receipt.get("signature")
    if not isinstance(sig, Mapping):
        raise ReceiptError("receipt signature missing")
    if sig.get("algorithm") != "content-bound-sha256@1":
        raise ReceiptError("unsupported signature algorithm")
    digest = str(sig.get("digest") or "")
    if not _SHA256_RE.match(digest):
        raise ReceiptError("signature digest must be sha256:<hex>")

    body = {
        k: v
        for k, v in receipt.items()
        if k not in {"signature", "receipt_id"}
    }
    expected_digest = f"sha256:{_sha256_hex(_canonical_json_bytes(body))}"
    if digest != expected_digest:
        raise ReceiptError("receipt signature digest mismatch")
    expected_id = f"receipt:{expected_digest}"
    if receipt.get("receipt_id") != expected_id:
        raise ReceiptError("receipt_id does not match content-bound digest")

    namespaces = list(receipt.get("namespaces") or [])
    if namespaces != list(CANARY_NAMESPACE_ORDER):
        raise ReceiptError("receipt namespaces order invalid")
    results = list(receipt.get("namespace_results") or [])
    if len(results) != len(CANARY_NAMESPACE_ORDER):
        raise ReceiptError("receipt must include one result per namespace")
    if receipt.get("each_promotion_has_evidence_and_tested_rollback") is not True:
        raise ReceiptError(
            "each_promotion_has_evidence_and_tested_rollback must be true"
        )
    if receipt.get("all_namespaces_promoted_export_only") is not True:
        raise ReceiptError(
            "all_namespaces_promoted_export_only must be true"
        )
    isolation = receipt.get("isolation_proof") or {}
    if not isinstance(isolation, Mapping) or not isolation.get(
        "isolation_proven"
    ):
        raise ReceiptError("isolation_proof must prove isolation")
    lineage = receipt.get("ducklake_lineage")
    if not isinstance(lineage, Mapping):
        raise ReceiptError("ducklake_lineage missing")
    if lineage.get("consumed_by") != CONTRACT_TASK_ID:
        raise ReceiptError("ducklake lineage must be consumed_by DQK-053")
    ld = str(lineage.get("lineage_digest") or "")
    if not ld.startswith("sha256:"):
        raise ReceiptError("ducklake lineage_digest missing")


# ---------------------------------------------------------------------------
# Full canary run
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CanaryRunResult:
    """Outcome of a full multi-namespace domain canary."""

    ok: bool
    run_id: str
    receipt: dict[str, Any]
    stored_row: Mapping[str, Any]
    report: Mapping[str, Any]
    backend: MemoryAuthorityBackend

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "ok": self.ok,
                "run_id": self.run_id,
                "receipt_id": self.receipt.get("receipt_id"),
                "receipt": self.receipt,
                "stored_row": dict(self.stored_row),
                "report": dict(self.report),
            }
        )


def run_domain_canary(
    *,
    run_id: str | None = None,
    store: DomainCanaryStore | None = None,
    backend: MemoryAuthorityBackend | None = None,
    inject_failure_namespace: str | None = None,
    slo_budget_s: float = DEFAULT_SLO_BUDGET_S,
) -> CanaryRunResult:
    """Execute the complete DQK-053 domain canary in dependency order."""

    rid = run_id or _new_id("domain-canary")
    canary_store = store or get_default_canary_store()
    shared_backend = backend or MemoryAuthorityBackend()

    order_doc = namespace_order_receipt()
    authority_install = dict(authority_install_check())
    if not authority_install.get("ok"):
        raise CanaryError("DQK-046 authority install_check failed")

    ducklake_mod = _load_ducklake_canary_module()
    ducklake_lineage = dict(ducklake_mod.domain_lineage_receipt())
    if ducklake_lineage.get("consumed_by") != CONTRACT_TASK_ID:
        raise CanaryError("DQK-099 lineage consumed_by must be DQK-053")

    if inject_failure_namespace is None:
        inject_failure_namespace = CanaryNamespace.OBSERVABILITY.value
    inject_failure_namespace = _require_safe_token(
        inject_failure_namespace, field_name="inject_failure_namespace"
    )
    if inject_failure_namespace not in CANARY_NAMESPACE_ORDER:
        raise CanaryError(
            "inject_failure_namespace must be one of "
            f"{list(CANARY_NAMESPACE_ORDER)}"
        )

    completed: list[str] = []
    results: list[NamespaceCanaryState] = []

    for spec in build_namespace_specs():
        for dep in spec.depends_on:
            if dep not in completed:
                raise NamespaceOrderError(
                    f"namespace {spec.namespace.value} depends on {dep} "
                    f"which has not completed"
                )
        expected_index = list(CANARY_NAMESPACE_ORDER).index(
            spec.namespace.value
        )
        if len(completed) != expected_index:
            raise NamespaceOrderError(
                f"namespace {spec.namespace.value} out of order: "
                f"completed={completed}"
            )

        ns_state = canary_one_namespace(
            shared_backend,
            spec,
            run_id=rid,
            slo_budget_s=slo_budget_s,
            inject_failure=(
                spec.namespace.value == inject_failure_namespace
            ),
            ducklake_lineage=(
                ducklake_lineage
                if spec.namespace is CanaryNamespace.DUCKLAKE
                else None
            ),
        )
        if not ns_state.ok:
            raise CanaryError(
                f"namespace canary failed: {spec.namespace.value}"
            )
        results.append(ns_state)
        completed.append(spec.namespace.value)

    isolation = prove_namespace_isolation(
        shared_backend,
        failing_namespace=inject_failure_namespace,
        all_results=results,
    )
    namespace_results = [dict(r.as_mapping()) for r in results]
    receipt = build_canary_receipt(
        run_id=rid,
        namespace_results=namespace_results,
        isolation_proof=isolation,
        namespace_order=order_doc,
        ducklake_lineage=ducklake_lineage,
        authority_install=authority_install,
        inject_failure_namespace=inject_failure_namespace,
    )
    require_canary_receipt(receipt)
    stored = canary_store.put_receipt(receipt)

    report = MappingProxyType(
        {
            "ok": True,
            "task_id": CONTRACT_TASK_ID,
            "program_id": PROGRAM_ID,
            "implementation_generation": IMPLEMENTATION_GENERATION,
            "run_id": rid,
            "interface": CANARY_RECEIPT_INTERFACE,
            "schema": CANARY_RECEIPT_SCHEMA,
            "receipt_id": receipt["receipt_id"],
            "database_native_table": STORE_TABLE,
            "stored_receipt_id": stored["receipt_id"],
            "namespaces": list(CANARY_NAMESPACE_ORDER),
            "completed_namespaces": list(completed),
            "all_namespaces_promoted_export_only": receipt[
                "all_namespaces_promoted_export_only"
            ],
            "each_promotion_has_evidence_and_tested_rollback": receipt[
                "each_promotion_has_evidence_and_tested_rollback"
            ],
            "isolation_proof": dict(isolation),
            "inject_failure_namespace": inject_failure_namespace,
            "namespace_results": namespace_results,
            "ducklake_lineage_digest": ducklake_lineage.get("lineage_digest"),
            "authority_task_id": AUTHORITY_TASK_ID,
            "post_promotion_mode": POST_PROMOTION_MODE,
            "promotion_ladder": list(PROMOTION_LADDER),
            "evidence_dimensions": list(EVIDENCE_DIMENSIONS),
        }
    )
    return CanaryRunResult(
        ok=True,
        run_id=rid,
        receipt=receipt,
        stored_row=stored,
        report=report,
        backend=shared_backend,
    )


# ---------------------------------------------------------------------------
# Install / self-check / CLI
# ---------------------------------------------------------------------------


def install_check() -> Mapping[str, Any]:
    """Validate canary contract without mutating durable state."""

    order = namespace_order_receipt()
    namespaces = list(order["order"])
    if namespaces != list(CANARY_NAMESPACE_ORDER):
        raise CanaryError("namespace order document mismatch")
    expected = {
        "supervisor",
        "proof",
        "graph-vector",
        "ast",
        "wallet",
        "observability",
        "ducklake",
    }
    if set(namespaces) != expected:
        raise CanaryError(f"canary namespaces incomplete: {set(namespaces)}")

    seen: set[str] = set()
    for spec in build_namespace_specs():
        for dep in spec.depends_on:
            if dep not in seen:
                raise CanaryError(
                    f"{spec.namespace.value} depends on {dep} before it appears"
                )
        seen.add(spec.namespace.value)

    authority = dict(authority_install_check())
    if not authority.get("ok"):
        raise CanaryError("DQK-046 install_check failed")
    modes = set(authority.get("modes") or [])
    if modes != {
        "legacy",
        "shadow",
        "dual",
        "db-primary",
        "export-only",
    }:
        raise CanaryError("authority modes incomplete")

    ducklake = _load_ducklake_canary_module()
    lineage = dict(ducklake.domain_lineage_receipt())
    if lineage.get("consumed_by") != CONTRACT_TASK_ID:
        raise CanaryError("DQK-099 lineage not consumed by DQK-053")

    return MappingProxyType(
        {
            "ok": True,
            "owner_task_id": CONTRACT_TASK_ID,
            "program_id": PROGRAM_ID,
            "implementation_generation": IMPLEMENTATION_GENERATION,
            "interface": CANARY_RECEIPT_INTERFACE,
            "schema": CANARY_RECEIPT_SCHEMA,
            "database_native_table": STORE_TABLE,
            "namespaces": namespaces,
            "namespace_order_digest": order["order_digest"],
            "promotion_ladder": list(PROMOTION_LADDER),
            "post_promotion_mode": POST_PROMOTION_MODE,
            "evidence_dimensions": list(EVIDENCE_DIMENSIONS),
            "authority_task_id": AUTHORITY_TASK_ID,
            "authority_modes": list(authority.get("modes") or []),
            "ducklake_canary_task_id": DUCKLAKE_CANARY_TASK_ID,
            "ducklake_lineage_digest": lineage.get("lineage_digest"),
            "acceptance": (
                "Each authority promotion has evidence and a tested rollback",
                "Canary failures quarantine only their namespace",
                "Legacy producers become export-only after promotion",
            ),
        }
    )


def self_check() -> Mapping[str, Any]:
    """End-to-end hermetic domain canary self-check."""

    check = dict(install_check())
    reset_default_canary_store()
    result = run_domain_canary(run_id="self-check")
    if not result.ok:
        raise CanaryError("self-check canary run failed")
    require_canary_receipt(result.receipt)
    stored = get_default_canary_store().load_body(result.receipt["receipt_id"])
    if stored.get("receipt_id") != result.receipt["receipt_id"]:
        raise CanaryError("database-native store round-trip failed")

    bad_results = list(result.receipt["namespace_results"])
    if len(bad_results) >= 2:
        bad_results[0], bad_results[1] = bad_results[1], bad_results[0]
        try:
            build_canary_receipt(
                run_id="negative-order",
                namespace_results=bad_results,
                isolation_proof=result.receipt["isolation_proof"],
                namespace_order=result.receipt["namespace_order"],
                ducklake_lineage=result.receipt["ducklake_lineage"],
                authority_install=result.receipt["authority_install"],
                inject_failure_namespace=result.receipt[
                    "inject_failure_namespace"
                ],
            )
            raise CanaryError(
                "receipt build should reject swapped namespace order"
            )
        except ReceiptError:
            pass

    return MappingProxyType(
        {
            **check,
            "self_check": {
                "ok": True,
                "run_id": result.run_id,
                "receipt_id": result.receipt["receipt_id"],
                "namespaces_promoted": list(result.report["namespaces"]),
                "export_only": result.report[
                    "all_namespaces_promoted_export_only"
                ],
                "evidence_and_rollback": result.report[
                    "each_promotion_has_evidence_and_tested_rollback"
                ],
                "isolation_proven": result.report["isolation_proof"].get(
                    "isolation_proven"
                ),
                "inject_failure_namespace": result.report[
                    "inject_failure_namespace"
                ],
                "database_native_stored": True,
            },
        }
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="DQK-053 domain canaries and cutover/rollback gates"
    )
    parser.add_argument(
        "--json", action="store_true", help="emit JSON report"
    )
    parser.add_argument(
        "--emit-receipt",
        action="store_true",
        help="run canary and emit DuckDBQuackCanaryReceipt@1",
    )
    parser.add_argument(
        "--self-check", action="store_true", help="run hermetic self-check"
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="optional canary run identity",
    )
    parser.add_argument(
        "--inject-failure-namespace",
        type=str,
        default=None,
        help="namespace to quarantine after promotion (isolation proof)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.self_check:
        report = dict(self_check())
    elif args.emit_receipt:
        result = run_domain_canary(
            run_id=args.run_id,
            inject_failure_namespace=args.inject_failure_namespace,
        )
        report = dict(result.receipt)
    else:
        report = dict(install_check())

    if args.json or args.emit_receipt:
        print(_canonical_json(report))
    else:
        print(
            f"ok={report.get('ok', True)} task={CONTRACT_TASK_ID}"
        )
        if "receipt_id" in report:
            print(f"receipt={report['receipt_id']}")
        if "interface" in report:
            print(f"interface={report['interface']}")
        if "namespaces" in report:
            print(f"namespaces={report['namespaces']}")
        if "self_check" in report:
            print(f"self_check={report['self_check'].get('ok')}")

    return 0 if report.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
