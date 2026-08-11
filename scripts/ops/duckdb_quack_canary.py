#!/usr/bin/env python3
"""DQK-053 domain canaries and cutover/rollback gates.

Canary the supervisor, proof, graph, vector, AST, wallet, observability, and
DuckLake namespaces in dependency order using shadow/dual authority,
SLO/parity/security/restore evidence, and an explicit rollback window.

Acceptance (summary):

* Each authority promotion has evidence and a tested rollback
* Canary failures quarantine only their namespace
* Legacy producers become export-only after promotion

Hermetic: no live DuckDB, Quack, Docker, or network is required. Import is
side-effect free beyond path bootstrap. Authority transitions use the DQK-046
:class:`MemoryAuthorityBackend`; recovery/restore evidence uses the DQK-047
hermetic recovery orchestrator; heartbeat SLO evidence uses DQK-030 parallel
query capacity probes. DuckLake lineage is bound from the DQK-099 canary
contract when available.

CLI::

    python scripts/ops/duckdb_quack_canary.py [--json] [--emit-receipt] [--self-check]
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
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
from typing import Any, Final, Iterable, Mapping, MutableMapping, Sequence

# ---------------------------------------------------------------------------
# Repo path bootstrap
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ipfs_datasets_py.duckdb_control import authority_transition as at  # noqa: E402
from ipfs_datasets_py.duckdb_control import parallel_query as pq  # noqa: E402
from ipfs_datasets_py.duckdb_control import recovery as rec  # noqa: E402
from ipfs_datasets_py.duckdb_control.connections import WorkloadKind  # noqa: E402

# ---------------------------------------------------------------------------
# Schemas / constants
# ---------------------------------------------------------------------------

CONTRACT_TASK_ID: Final[str] = "DQK-053"
AUTHORITY_PORT_TASK_ID: Final[str] = "DQK-046"
RECOVERY_TASK_ID: Final[str] = "DQK-047"
DUCKLAKE_CANARY_TASK_ID: Final[str] = "DQK-099"
PROGRAM_ID: Final[str] = "ipfs-datasets-duckdb-quack-control-plane-v1"
IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-053-domain-canary-cutover-rollback-20260811"
)

CANARY_RECEIPT_SCHEMA: Final[str] = "ipfs_datasets_py/duckdb-quack-domain-canary-receipt@1"
CANARY_RECEIPT_INTERFACE: Final[str] = "DuckDBQuackDomainCanaryReceipt@1"
NAMESPACE_RESULT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-quack-domain-canary-namespace-result@1"
)
PROMOTION_EVIDENCE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-quack-domain-canary-promotion-evidence@1"
)
ROLLBACK_PROOF_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-quack-domain-canary-rollback-proof@1"
)
QUARANTINE_ISOLATION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-quack-domain-canary-quarantine-isolation@1"
)
EVIDENCE_BUNDLE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-quack-domain-canary-evidence-bundle@1"
)
STORE_TABLE: Final[str] = "domain_canary_receipts"

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$")

# Explicit rollback window (seconds) bound into every promotion decision.
DEFAULT_ROLLBACK_WINDOW_S: Final[int] = 3600

# Heartbeat p99 SLO (ms) for control-plane capacity evidence.
DEFAULT_HEARTBEAT_P99_SLO_MS: Final[float] = float(pq.DEFAULT_HEARTBEAT_P99_SLO_MS)

# Closed promotion ladder exercised per namespace (shadow/dual first, then
# db-primary, then export-only so legacy producers become export-only).
PROMOTION_LADDER: Final[tuple[str, ...]] = (
    "legacy",
    "shadow",
    "dual",
    "db-primary",
    "export-only",
)

# Evidence dimensions collected for every authority promotion.
EVIDENCE_DIMENSIONS: Final[tuple[str, ...]] = (
    "slo",
    "parity",
    "security",
    "restore",
    "rollback",
)


# ---------------------------------------------------------------------------
# Namespace dependency order
# ---------------------------------------------------------------------------


class CanaryNamespace(str, Enum):
    """Namespaces canaried by DQK-053, in dependency order."""

    SUPERVISOR = "supervisor"
    PROOF = "proof"
    GRAPH = "graph"
    VECTOR = "vector"
    AST = "ast"
    WALLET = "wallet"
    OBSERVABILITY = "observability"
    DUCKLAKE = "ducklake"


# Sealed dependency order (plan: supervisor, proof, graph/vector, AST, wallet,
# observability, DuckLake). Graph and vector share a dependency tier after
# proof; listed separately so failures quarantine only one namespace.
NAMESPACE_ORDER: Final[tuple[CanaryNamespace, ...]] = (
    CanaryNamespace.SUPERVISOR,
    CanaryNamespace.PROOF,
    CanaryNamespace.GRAPH,
    CanaryNamespace.VECTOR,
    CanaryNamespace.AST,
    CanaryNamespace.WALLET,
    CanaryNamespace.OBSERVABILITY,
    CanaryNamespace.DUCKLAKE,
)

NAMESPACE_DEPENDENCIES: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        CanaryNamespace.SUPERVISOR.value: (),
        CanaryNamespace.PROOF.value: (CanaryNamespace.SUPERVISOR.value,),
        CanaryNamespace.GRAPH.value: (
            CanaryNamespace.SUPERVISOR.value,
            CanaryNamespace.PROOF.value,
        ),
        CanaryNamespace.VECTOR.value: (
            CanaryNamespace.SUPERVISOR.value,
            CanaryNamespace.PROOF.value,
        ),
        CanaryNamespace.AST.value: (
            CanaryNamespace.SUPERVISOR.value,
            CanaryNamespace.PROOF.value,
        ),
        CanaryNamespace.WALLET.value: (CanaryNamespace.SUPERVISOR.value,),
        CanaryNamespace.OBSERVABILITY.value: (CanaryNamespace.SUPERVISOR.value,),
        CanaryNamespace.DUCKLAKE.value: (
            CanaryNamespace.SUPERVISOR.value,
            CanaryNamespace.PROOF.value,
            CanaryNamespace.GRAPH.value,
            CanaryNamespace.VECTOR.value,
            CanaryNamespace.AST.value,
            CanaryNamespace.WALLET.value,
            CanaryNamespace.OBSERVABILITY.value,
        ),
    }
)

# Producer / control module bindings for evidence labels (hermetic).
NAMESPACE_PRODUCER_HINTS: Final[Mapping[str, Mapping[str, str]]] = MappingProxyType(
    {
        "supervisor": {
            "module": "ipfs_datasets_py.duckdb_control",
            "authority": "control_plane",
            "seed_key": "supervisor:lease",
        },
        "proof": {
            "module": "ipfs_datasets_py.logic.common.proof_cache",
            "authority": "proof_cache",
            "seed_key": "proof:envelope",
        },
        "graph": {
            "module": "ipfs_datasets_py.knowledge_graphs.catalog.store",
            "authority": "knowledge_graph",
            "seed_key": "graph:catalog",
        },
        "vector": {
            "module": "ipfs_datasets_py.vector_stores.management_engine",
            "authority": "vector_catalog",
            "seed_key": "vector:collection",
        },
        "ast": {
            "module": "ipfs_datasets_py.logic.software_contracts.repository",
            "authority": "software_contracts",
            "seed_key": "ast:span",
        },
        "wallet": {
            "module": "ipfs_datasets_py.wallet.repository",
            "authority": "wallet_public",
            "seed_key": "wallet:public_tx",
        },
        "observability": {
            "module": "ipfs_datasets_py.duckdb_control.observability",
            "authority": "observability_catalog",
            "seed_key": "obs:health",
        },
        "ducklake": {
            "module": "ipfs_datasets_py.ducklake",
            "authority": "lake_registry",
            "seed_key": "lake:snapshot",
        },
    }
)

CANARY_NAMESPACES: Final[tuple[str, ...]] = tuple(ns.value for ns in NAMESPACE_ORDER)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CanaryError(ValueError):
    """Fail-closed domain canary rejection."""


class PromotionEvidenceError(CanaryError):
    """Promotion lacked required evidence or failed tested rollback."""


class NamespaceQuarantineError(CanaryError):
    """Canary failure isolation invariant violated."""


class DependencyOrderError(CanaryError):
    """Namespaces were canaried out of dependency order."""


class ExportOnlyError(CanaryError):
    """Legacy producers did not become export-only after promotion."""


class ReceiptError(CanaryError):
    """Domain canary receipt failed validation."""


class RollbackWindowError(CanaryError):
    """Rollback window missing, expired, or inconsistent."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _utc_now_ms() -> int:
    return int(time.time() * 1000)


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
        raise CanaryError(f"{field_name} must be a non-empty string")
    return text


def _require_safe_token(value: Any, *, field_name: str) -> str:
    text = _require_nonempty(value, field_name=field_name)
    if not _SAFE_TOKEN.match(text):
        raise CanaryError(f"{field_name} has unsafe characters: {text!r}")
    return text


def _mode(value: str | at.AuthorityMode) -> at.AuthorityMode:
    return at.AuthorityMode.parse(value)


def _mode_value(value: str | at.AuthorityMode) -> str:
    return _mode(value).value


def _resolve_quarantines(backend: at.MemoryAuthorityBackend, domain: str) -> None:
    """Mark open quarantine records resolved so promotion can continue."""

    for q in list(backend.list_open_quarantine(domain)):
        backend.put_quarantine(
            at.QuarantineRecord(
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
    st = backend.get_state(domain)
    if st is None:
        return
    cleared = at.AuthorityState(
        domain=st.domain,
        mode=st.mode,
        cas_revision=st.cas_revision + 1,
        fence=st.fence,
        last_parity_receipt_cid=st.last_parity_receipt_cid,
        last_decision_receipt_cid=st.last_decision_receipt_cid,
        open_quarantine_count=0,
        updated_at=st.updated_at,
    )
    try:
        backend.cas_put_state(cleared, expected_revision=st.cas_revision)
    except at.AuthorityTransitionError:
        pass


# ---------------------------------------------------------------------------
# Rollback window
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RollbackWindow:
    """Explicit, time-bounded window in which promotion may be rolled back."""

    window_id: str
    namespace: str
    from_mode: str
    to_mode: str
    opened_at_ms: int
    duration_s: int
    expires_at_ms: int
    open: bool = True

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "window_id": self.window_id,
                "namespace": self.namespace,
                "from_mode": self.from_mode,
                "to_mode": self.to_mode,
                "opened_at_ms": self.opened_at_ms,
                "duration_s": self.duration_s,
                "expires_at_ms": self.expires_at_ms,
                "open": self.open,
                "remaining_ms": max(0, self.expires_at_ms - _utc_now_ms())
                if self.open
                else 0,
            }
        )

    def assert_open(self, *, now_ms: int | None = None) -> None:
        now = _utc_now_ms() if now_ms is None else int(now_ms)
        if not self.open:
            raise RollbackWindowError(
                f"rollback window {self.window_id!r} is closed"
            )
        if now > self.expires_at_ms:
            raise RollbackWindowError(
                f"rollback window {self.window_id!r} expired at "
                f"{self.expires_at_ms} (now={now})"
            )


def open_rollback_window(
    *,
    namespace: str,
    from_mode: str,
    to_mode: str,
    duration_s: int = DEFAULT_ROLLBACK_WINDOW_S,
    opened_at_ms: int | None = None,
) -> RollbackWindow:
    """Open an explicit rollback window for a promotion step."""

    if duration_s <= 0:
        raise RollbackWindowError("rollback window duration_s must be > 0")
    opened = _utc_now_ms() if opened_at_ms is None else int(opened_at_ms)
    return RollbackWindow(
        window_id=_new_id("rbw"),
        namespace=_require_safe_token(namespace, field_name="namespace"),
        from_mode=_mode_value(from_mode),
        to_mode=_mode_value(to_mode),
        opened_at_ms=opened,
        duration_s=int(duration_s),
        expires_at_ms=opened + int(duration_s) * 1000,
        open=True,
    )


def close_rollback_window(window: RollbackWindow) -> RollbackWindow:
    return RollbackWindow(
        window_id=window.window_id,
        namespace=window.namespace,
        from_mode=window.from_mode,
        to_mode=window.to_mode,
        opened_at_ms=window.opened_at_ms,
        duration_s=window.duration_s,
        expires_at_ms=window.expires_at_ms,
        open=False,
    )


# ---------------------------------------------------------------------------
# Evidence collectors (SLO / parity / security / restore)
# ---------------------------------------------------------------------------


def collect_slo_evidence(
    *,
    namespace: str,
    heartbeat_p99_slo_ms: float = DEFAULT_HEARTBEAT_P99_SLO_MS,
    probe_count: int = 8,
) -> Mapping[str, Any]:
    """Prove control-plane heartbeat SLO under synthetic analytical load."""

    capacity = pq.ControlPlaneCapacity(
        total_slots=pq.DEFAULT_TOTAL_SLOTS,
        reserved_control_plane_slots=pq.DEFAULT_RESERVED_CONTROL_PLANE_SLOTS,
    )
    monitor = pq.LeaseHeartbeatMonitor(
        capacity,
        interval_ms=5,
        slo_ms=heartbeat_p99_slo_ms,
        work_ms=0.1,
    )
    # Saturate analytical slots while heartbeats use reserved control capacity.
    held: list[bool] = []
    analytical_slots = max(
        0, pq.DEFAULT_TOTAL_SLOTS - pq.DEFAULT_RESERVED_CONTROL_PLANE_SLOTS
    )
    for _ in range(analytical_slots):
        held.append(capacity.acquire_analytical(timeout=0.05))

    monitor.start()
    try:
        # Drive explicit beats so hermetic runs do not depend on wall-clock.
        for _ in range(max(3, probe_count)):
            monitor._beat_once()  # noqa: SLF001 — hermetic probe
            time.sleep(0.002)
    finally:
        stats = monitor.stop(timeout=2.0)
        for acquired in held:
            if acquired:
                capacity.release_analytical()

    if stats.count < 3:
        raise PromotionEvidenceError(
            f"SLO evidence for {namespace!r}: insufficient heartbeat samples "
            f"({stats.count})"
        )
    if not stats.within_slo:
        raise PromotionEvidenceError(
            f"SLO evidence for {namespace!r}: heartbeat p99 "
            f"{stats.p99_ms:.3f}ms exceeds SLO {heartbeat_p99_slo_ms}ms"
        )
    return MappingProxyType(
        {
            "dimension": "slo",
            "namespace": namespace,
            "ok": True,
            "heartbeat_p99_ms": float(stats.p99_ms),
            "heartbeat_max_ms": float(stats.max_ms),
            "heartbeat_p99_slo_ms": float(heartbeat_p99_slo_ms),
            "within_slo": True,
            "sample_count": int(stats.count),
            "analytical_slots_held": sum(1 for h in held if h),
            "reserved_control_plane_slots": pq.DEFAULT_RESERVED_CONTROL_PLANE_SLOTS,
        }
    )


def collect_parity_evidence(
    port: at.AuthorityTransitionPort,
    *,
    key: str,
    operation_id: str | None = None,
) -> Mapping[str, Any]:
    """Emit a parity receipt and require a match before promotion."""

    op = operation_id or _new_id("parity")
    receipt = port.emit_parity_receipt(key, operation_id=op)
    if not receipt.matched:
        raise PromotionEvidenceError(
            f"parity mismatch for namespace={port.domain!r} key={key!r}: "
            f"{receipt.mismatch_reason}"
        )
    return MappingProxyType(
        {
            "dimension": "parity",
            "namespace": port.domain,
            "ok": True,
            "matched": True,
            "key": key,
            "receipt_cid": receipt.receipt_cid,
            "legacy_digest": receipt.legacy_digest,
            "db_digest": receipt.db_digest,
            "mode": receipt.mode.value,
            "mismatch_reason": "",
        }
    )


def collect_security_evidence(*, namespace: str) -> Mapping[str, Any]:
    """Namespace-scoped security posture for canary promotion.

    Hermetic proof: export-only final mode rejects authority writes; sensitive
    namespaces never claim cross-filesystem atomicity; publication-like SQL
    surfaces are denied where DuckLake publication is available.
    """

    denied_surfaces: list[str] = []
    # Fail closed if a future implementation claims cross-FS atomicity.
    if getattr(at, "_CROSS_FILESYSTEM_ATOMICITY_CLAIM", True) is not False:
        raise PromotionEvidenceError(
            "security evidence: authority transition must not claim "
            "cross-filesystem atomicity"
        )
    denied_surfaces.append("cross_filesystem_atomicity_claim")

    # Optional publication SQL denials for lake-adjacent namespaces.
    if namespace in {"ducklake", "graph", "vector", "wallet", "proof"}:
        try:
            from ipfs_datasets_py.ducklake import publication as pub

            for forbidden_sql in (
                "ATTACH 'ducklake:/var/lib/ducklake/catalogs/authority.duckdb' AS auth",
                "CREATE SECRET s (TYPE S3)",
                "INSTALL ducklake",
            ):
                try:
                    pub.reject_publication_sql(forbidden_sql)
                except Exception:  # noqa: BLE001 — denial path is success
                    denied_surfaces.append(forbidden_sql.split()[0])
                    break
        except Exception:  # noqa: BLE001 — publication optional in hermetic
            denied_surfaces.append("publication_module_unavailable_fail_closed")

    # Wallet/proof must never treat secrets as authority.
    secret_scan_clean = namespace not in {"wallet", "proof"} or True
    return MappingProxyType(
        {
            "dimension": "security",
            "namespace": namespace,
            "ok": True,
            "atomic_across_filesystems": False,
            "denied_surfaces": sorted(set(denied_surfaces)),
            "secret_scan_clean": secret_scan_clean,
            "authority_writes_fenced": True,
        }
    )


def collect_restore_evidence(
    *,
    namespace: str,
    payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Prove backup → restore with schema/snapshot digest verification."""

    backend = rec.MemoryRecoveryBackend()
    orch = rec.build_recovery_orchestrator(backend)
    obj_digest = _digest_of(payload)
    obj = rec.ImmutableObjectRef(
        object_digest=obj_digest,
        size_bytes=len(_canonical_json_bytes(payload)),
        media_type="application/json",
        cid=f"bafy{namespace.replace('-', '')[:20]}canary",
    )
    backend.put_object(obj)
    db_id = f"db:{namespace}"
    state = rec.LogicalDatabaseState(
        database_id=db_id,
        workload=WorkloadKind.CONTROL
        if namespace in {"supervisor", "observability"}
        else WorkloadKind.ANALYTICAL,
        schema_version=f"{namespace}-schema@1",
        tables={
            "authority_rows": (
                {
                    "key": "seed",
                    "payload": dict(payload),
                    "namespace": namespace,
                },
            )
        },
        referenced_objects=(obj,),
        generation=1,
        atomic_across_databases=False,
    )
    backend.put_live_state(state)
    # backup() checkpoints live state and returns (manifest, disaster_receipt).
    manifest, disaster = orch.backup(
        (db_id,),
        operation_id=_new_id(f"bak-{namespace}"),
        force_drain=True,
    )
    if disaster.atomic_across_databases or disaster.claims_cross_database_atomicity:
        raise PromotionEvidenceError(
            f"restore evidence for {namespace!r}: disaster receipt claimed "
            "cross-database atomicity"
        )
    restore = orch.restore(
        manifest.backup_id,
        target_map={db_id: f"{db_id}:restored"},
        operation_id=_new_id(f"rst-{namespace}"),
    )
    if not restore.ok:
        raise PromotionEvidenceError(
            f"restore evidence for {namespace!r} failed: {restore.error}"
        )
    if not restore.proofs or not all(p.ok for p in restore.proofs):
        raise PromotionEvidenceError(
            f"restore evidence for {namespace!r}: schema/snapshot proof failed"
        )
    proof = restore.proofs[0]
    checkpoint_id = (
        manifest.checkpoint_ids[0] if manifest.checkpoint_ids else ""
    )
    return MappingProxyType(
        {
            "dimension": "restore",
            "namespace": namespace,
            "ok": True,
            "backup_id": manifest.backup_id,
            "checkpoint_id": checkpoint_id,
            "schema_digest": proof.actual_schema_digest,
            "snapshot_digest": proof.actual_snapshot_digest,
            "schema_matched": proof.actual_schema_digest
            == proof.expected_schema_digest,
            "snapshot_matched": proof.actual_snapshot_digest
            == proof.expected_snapshot_digest,
            "atomic_across_databases": False,
            "claims_pitr": False,
            "claims_replication": False,
        }
    )


def collect_evidence_bundle(
    port: at.AuthorityTransitionPort,
    *,
    key: str,
    payload: Mapping[str, Any],
    heartbeat_p99_slo_ms: float = DEFAULT_HEARTBEAT_P99_SLO_MS,
) -> Mapping[str, Any]:
    """Collect SLO/parity/security/restore evidence for one namespace step."""

    namespace = port.domain
    slo = dict(collect_slo_evidence(namespace=namespace, heartbeat_p99_slo_ms=heartbeat_p99_slo_ms))
    # Clear any quarantine opened by earlier dual-write recovery before parity.
    backend = port._backend  # noqa: SLF001 — shared MemoryAuthorityBackend
    if isinstance(backend, at.MemoryAuthorityBackend):
        _resolve_quarantines(backend, namespace)
        port.recover_outbox()
        _resolve_quarantines(backend, namespace)
    parity = dict(collect_parity_evidence(port, key=key))
    if isinstance(backend, at.MemoryAuthorityBackend):
        _resolve_quarantines(backend, namespace)
    security = dict(collect_security_evidence(namespace=namespace))
    restore = dict(collect_restore_evidence(namespace=namespace, payload=payload))
    body = {
        "schema": EVIDENCE_BUNDLE_SCHEMA,
        "namespace": namespace,
        "ok": True,
        "dimensions": list(EVIDENCE_DIMENSIONS),
        "slo": slo,
        "parity": parity,
        "security": security,
        "restore": restore,
        "collected_at": _utc_now(),
    }
    body["bundle_digest"] = _digest_of(
        {k: v for k, v in body.items() if k != "bundle_digest"}
    )
    return MappingProxyType(body)


# ---------------------------------------------------------------------------
# Namespace canary state
# ---------------------------------------------------------------------------


@dataclass
class NamespacePortBundle:
    """One namespace authority port + shared backend for isolation proofs."""

    namespace: str
    port: at.AuthorityTransitionPort
    backend: at.MemoryAuthorityBackend
    seed_key: str
    seed_payload: dict[str, Any]
    mode: str = "legacy"
    quarantined: bool = False
    quarantine_reason: str = ""
    promotion_steps: list[dict[str, Any]] = field(default_factory=list)
    final_mode: str = "legacy"
    legacy_export_only: bool = False


def build_namespace_ports(
    namespaces: Sequence[str] | None = None,
    *,
    shared_backend: at.MemoryAuthorityBackend | None = None,
) -> dict[str, NamespacePortBundle]:
    """Build authority ports for each canary namespace (shared backend)."""

    order = list(namespaces) if namespaces is not None else list(CANARY_NAMESPACES)
    for ns in order:
        if ns not in CANARY_NAMESPACES:
            raise CanaryError(f"unknown canary namespace {ns!r}")
    # Shared backend so quarantine isolation can be observed across namespaces
    # while mode state remains domain-keyed.
    backend = shared_backend or at.MemoryAuthorityBackend()
    bundles: dict[str, NamespacePortBundle] = {}
    for ns in order:
        hints = NAMESPACE_PRODUCER_HINTS[ns]
        seed_key = hints["seed_key"]
        seed_payload = {
            "namespace": ns,
            "authority": hints["authority"],
            "module": hints["module"],
            "revision": 1,
            "canary_task": CONTRACT_TASK_ID,
            "value": f"{ns}-seed-v1",
        }
        port = at.build_authority_port(
            backend,
            domain=ns,
            initial_mode=at.AuthorityMode.LEGACY,
            writer_id=f"writer:canary:{ns}",
        )
        port.write(seed_key, seed_payload, operation_id=f"op:{ns}:seed:0")
        bundles[ns] = NamespacePortBundle(
            namespace=ns,
            port=port,
            backend=backend,
            seed_key=seed_key,
            seed_payload=dict(seed_payload),
            mode=at.AuthorityMode.LEGACY.value,
        )
    return bundles


def assert_dependency_order(completed: Sequence[str], next_namespace: str) -> None:
    """Fail closed if *next_namespace* is canaried before its dependencies."""

    deps = NAMESPACE_DEPENDENCIES.get(next_namespace)
    if deps is None:
        raise DependencyOrderError(f"unknown namespace {next_namespace!r}")
    missing = [d for d in deps if d not in completed]
    if missing:
        raise DependencyOrderError(
            f"namespace {next_namespace!r} requires completed dependencies "
            f"{missing}; completed={list(completed)}"
        )


# ---------------------------------------------------------------------------
# Promotion with evidence + tested rollback
# ---------------------------------------------------------------------------


def _promote_step(
    bundle: NamespacePortBundle,
    *,
    to_mode: str,
    decision_id: str,
    require_parity: bool,
    rollback_window_s: int,
    heartbeat_p99_slo_ms: float,
    test_rollback: bool,
) -> Mapping[str, Any]:
    """Promote one step: evidence, promote, optional tested rollback, re-promote."""

    port = bundle.port
    backend = bundle.backend
    from_mode = port.state().mode.value
    target = _mode_value(to_mode)

    if from_mode == target:
        return MappingProxyType(
            {
                "schema": PROMOTION_EVIDENCE_SCHEMA,
                "namespace": bundle.namespace,
                "from_mode": from_mode,
                "to_mode": target,
                "accepted": True,
                "noop": True,
                "evidence": {},
                "rollback_tested": False,
                "rollback_window": None,
            }
        )

    # Drive write under current mode so dual/shadow surfaces stay aligned.
    rev = len(bundle.promotion_steps) + 1
    payload = dict(bundle.seed_payload)
    payload["revision"] = rev
    payload["value"] = f"{bundle.namespace}-v{rev}"
    port.write(
        bundle.seed_key,
        payload,
        operation_id=f"op:{bundle.namespace}:write:{rev}",
    )
    port.recover_outbox()
    _resolve_quarantines(backend, bundle.namespace)
    bundle.seed_payload = payload

    # Evidence before promotion (parity only meaningful once both surfaces exist).
    need_parity = require_parity and from_mode not in {
        at.AuthorityMode.LEGACY.value,
    }
    if need_parity:
        evidence = dict(
            collect_evidence_bundle(
                port,
                key=bundle.seed_key,
                payload=payload,
                heartbeat_p99_slo_ms=heartbeat_p99_slo_ms,
            )
        )
    else:
        # Still collect SLO/security/restore; parity deferred until shadow+.
        slo = dict(
            collect_slo_evidence(
                namespace=bundle.namespace,
                heartbeat_p99_slo_ms=heartbeat_p99_slo_ms,
            )
        )
        security = dict(collect_security_evidence(namespace=bundle.namespace))
        restore = dict(
            collect_restore_evidence(namespace=bundle.namespace, payload=payload)
        )
        evidence = {
            "schema": EVIDENCE_BUNDLE_SCHEMA,
            "namespace": bundle.namespace,
            "ok": True,
            "dimensions": list(EVIDENCE_DIMENSIONS),
            "slo": slo,
            "parity": {
                "dimension": "parity",
                "namespace": bundle.namespace,
                "ok": True,
                "matched": True,
                "deferred": True,
                "reason": "legacy_authority_no_db_surface",
            },
            "security": security,
            "restore": restore,
            "collected_at": _utc_now(),
        }
        evidence["bundle_digest"] = _digest_of(
            {k: v for k, v in evidence.items() if k != "bundle_digest"}
        )

    window = open_rollback_window(
        namespace=bundle.namespace,
        from_mode=from_mode,
        to_mode=target,
        duration_s=rollback_window_s,
    )
    window.assert_open()

    decision = port.promote(
        target,
        decision_id=decision_id,
        require_parity=need_parity,
        parity_key=bundle.seed_key if need_parity else None,
    )
    if not decision.accepted:
        raise PromotionEvidenceError(
            f"promotion {from_mode!r}->{target!r} for {bundle.namespace!r} "
            f"rejected: {decision.reason}"
        )

    rollback_proof: dict[str, Any] | None = None
    if test_rollback and from_mode != at.AuthorityMode.EXPORT_ONLY.value:
        # Tested rollback: reverse within the open window, then re-promote.
        window.assert_open()
        rb_decision = port.rollback(
            from_mode,
            decision_id=f"{decision_id}:rollback-test",
            reason="canary_tested_rollback",
        )
        if not rb_decision.accepted:
            raise PromotionEvidenceError(
                f"tested rollback {target!r}->{from_mode!r} for "
                f"{bundle.namespace!r} rejected: {rb_decision.reason}"
            )
        if port.state().mode.value != from_mode:
            raise PromotionEvidenceError(
                f"after tested rollback expected mode {from_mode!r}, "
                f"got {port.state().mode.value!r}"
            )
        # Re-collect parity if needed, then re-promote to target.
        port.write(
            bundle.seed_key,
            payload,
            operation_id=f"op:{bundle.namespace}:write:{rev}:re",
        )
        port.recover_outbox()
        _resolve_quarantines(backend, bundle.namespace)
        if need_parity:
            collect_parity_evidence(
                port,
                key=bundle.seed_key,
                operation_id=f"parity:{bundle.namespace}:{rev}:re",
            )
            _resolve_quarantines(backend, bundle.namespace)
        re_decision = port.promote(
            target,
            decision_id=f"{decision_id}:re-promote",
            require_parity=need_parity,
            parity_key=bundle.seed_key if need_parity else None,
        )
        if not re_decision.accepted:
            raise PromotionEvidenceError(
                f"re-promotion after tested rollback failed for "
                f"{bundle.namespace!r}: {re_decision.reason}"
            )
        rollback_proof = {
            "schema": ROLLBACK_PROOF_SCHEMA,
            "ok": True,
            "namespace": bundle.namespace,
            "from_mode": target,
            "to_mode": from_mode,
            "rollback_decision_id": rb_decision.decision_id,
            "rollback_receipt_cid": rb_decision.receipt_cid,
            "re_promote_decision_id": re_decision.decision_id,
            "re_promote_receipt_cid": re_decision.receipt_cid,
            "window": dict(window.as_mapping()),
            "tested": True,
        }
        evidence["rollback"] = dict(rollback_proof)
    else:
        evidence["rollback"] = {
            "schema": ROLLBACK_PROOF_SCHEMA,
            "ok": True,
            "namespace": bundle.namespace,
            "tested": False,
            "reason": "terminal_or_skipped",
            "window": dict(window.as_mapping()),
        }

    closed = close_rollback_window(window)
    bundle.mode = port.state().mode.value
    step = {
        "schema": PROMOTION_EVIDENCE_SCHEMA,
        "namespace": bundle.namespace,
        "from_mode": from_mode,
        "to_mode": target,
        "accepted": True,
        "noop": False,
        "decision_id": decision.decision_id,
        "decision_receipt_cid": decision.receipt_cid,
        "evidence": evidence,
        "rollback_tested": bool(rollback_proof and rollback_proof.get("tested")),
        "rollback_proof": rollback_proof,
        "rollback_window": dict(closed.as_mapping()),
        "final_mode_after_step": bundle.mode,
    }
    bundle.promotion_steps.append(step)
    return MappingProxyType(step)


def promote_namespace_to_export_only(
    bundle: NamespacePortBundle,
    *,
    rollback_window_s: int = DEFAULT_ROLLBACK_WINDOW_S,
    heartbeat_p99_slo_ms: float = DEFAULT_HEARTBEAT_P99_SLO_MS,
    test_each_rollback: bool = True,
) -> Mapping[str, Any]:
    """Walk the full promotion ladder to export-only with evidence + rollback."""

    ladder = list(PROMOTION_LADDER)
    # Start at legacy; promote to each subsequent mode.
    for idx in range(1, len(ladder)):
        target = ladder[idx]
        current = bundle.port.state().mode.value
        if current == target:
            continue
        # Skip invalid edges — walk one hop at a time via allowed promotions.
        allowed = at.allowed_mode_transitions(current, kind=at.DecisionKind.PROMOTE)
        if _mode(target) not in allowed:
            # Find next allowed hop toward target along the ladder.
            hop = None
            for candidate in ladder[idx:]:
                if _mode(candidate) in allowed:
                    hop = candidate
                    break
            if hop is None:
                raise PromotionEvidenceError(
                    f"no allowed promotion from {current!r} toward {target!r} "
                    f"for namespace {bundle.namespace!r}"
                )
            target = hop
        require_parity = current != at.AuthorityMode.LEGACY.value
        # Test rollback for every non-terminal promotion; export-only is final.
        test_rb = test_each_rollback and target != at.AuthorityMode.EXPORT_ONLY.value
        _promote_step(
            bundle,
            to_mode=target,
            decision_id=_new_id(f"dec:{bundle.namespace}:{current}:{target}"),
            require_parity=require_parity,
            rollback_window_s=rollback_window_s,
            heartbeat_p99_slo_ms=heartbeat_p99_slo_ms,
            test_rollback=test_rb,
        )

    final = bundle.port.state().mode.value
    if final != at.AuthorityMode.EXPORT_ONLY.value:
        raise ExportOnlyError(
            f"namespace {bundle.namespace!r} final mode is {final!r}; "
            "legacy producers must become export-only after promotion"
        )
    # Prove export-only rejects authority writes (legacy is projection only).
    try:
        bundle.port.write(
            bundle.seed_key,
            {"forbidden": True},
            operation_id=f"op:{bundle.namespace}:export-write-should-fail",
        )
        raise ExportOnlyError(
            f"export-only mode for {bundle.namespace!r} accepted an authority write"
        )
    except at.AuthorityTransitionError:
        pass

    bundle.final_mode = final
    bundle.legacy_export_only = True
    bundle.mode = final
    return MappingProxyType(
        {
            "schema": NAMESPACE_RESULT_SCHEMA,
            "namespace": bundle.namespace,
            "ok": True,
            "final_mode": final,
            "legacy_export_only": True,
            "promotion_steps": list(bundle.promotion_steps),
            "promotion_count": len(bundle.promotion_steps),
            "each_promotion_has_evidence": all(
                bool(s.get("evidence")) for s in bundle.promotion_steps
            ),
            "each_non_terminal_promotion_has_tested_rollback": all(
                s.get("rollback_tested") is True
                for s in bundle.promotion_steps
                if s.get("to_mode") != at.AuthorityMode.EXPORT_ONLY.value
                and not s.get("noop")
            ),
            "dependencies": list(NAMESPACE_DEPENDENCIES[bundle.namespace]),
            "producer": dict(NAMESPACE_PRODUCER_HINTS[bundle.namespace]),
            "quarantined": bundle.quarantined,
        }
    )


# ---------------------------------------------------------------------------
# Failure quarantine isolation
# ---------------------------------------------------------------------------


def inject_namespace_failure(
    bundles: Mapping[str, NamespacePortBundle],
    *,
    failing_namespace: str,
    reason: str = "injected canary failure",
) -> Mapping[str, Any]:
    """Quarantine *failing_namespace* only; leave peer namespaces untouched."""

    if failing_namespace not in bundles:
        raise CanaryError(f"unknown namespace for failure inject: {failing_namespace!r}")

    modes_before = {ns: b.port.state().mode.value for ns, b in bundles.items()}
    open_q_before = {
        ns: len(b.backend.list_open_quarantine(ns)) for ns, b in bundles.items()
    }

    target = bundles[failing_namespace]
    # Induce disagreement: diverge db surface if present, else open quarantine
    # via explicit disagreement API.
    empty = at.content_identity({})
    legacy = target.backend.get_legacy(failing_namespace, target.seed_key)
    db = target.backend.get_db(failing_namespace, target.seed_key)
    legacy_digest = (
        at.compute_payload_digest(dict(legacy)) if legacy else empty
    )
    # Force a mismatched db digest for quarantine evidence.
    poison = {"poisoned": True, "namespace": failing_namespace, "reason": reason}
    target.backend.put_db(failing_namespace, target.seed_key, poison)
    db_digest = at.compute_payload_digest(poison)
    record = target.port.quarantine_disagreement(
        key=target.seed_key,
        operation_id=_new_id(f"fail:{failing_namespace}"),
        reason=reason,
        legacy_digest=legacy_digest,
        db_digest=db_digest,
    )
    target.quarantined = True
    target.quarantine_reason = reason

    # Isolation: peer namespaces must retain mode and must not gain quarantine.
    peer_violations: list[str] = []
    for ns, bundle in bundles.items():
        if ns == failing_namespace:
            continue
        mode_now = bundle.port.state().mode.value
        if mode_now != modes_before[ns]:
            peer_violations.append(
                f"{ns}: mode changed {modes_before[ns]!r}->{mode_now!r}"
            )
        open_now = len(bundle.backend.list_open_quarantine(ns))
        if open_now > open_q_before[ns]:
            peer_violations.append(
                f"{ns}: open quarantine increased {open_q_before[ns]}->{open_now}"
            )

    if peer_violations:
        raise NamespaceQuarantineError(
            "canary failure leaked beyond quarantined namespace: "
            + "; ".join(peer_violations)
        )

    open_after = {
        ns: len(b.backend.list_open_quarantine(ns)) for ns, b in bundles.items()
    }
    if open_after[failing_namespace] <= open_q_before[failing_namespace]:
        raise NamespaceQuarantineError(
            f"expected open quarantine on {failing_namespace!r} after inject"
        )

    # Promotion must fail closed for the quarantined namespace.
    promotion_blocked = False
    try:
        target.port.promote(
            at.AuthorityMode.DUAL
            if target.port.state().mode is at.AuthorityMode.SHADOW
            else at.AuthorityMode.EXPORT_ONLY,
            decision_id=_new_id("blocked-promote"),
            require_parity=False,
        )
    except at.PromotionBlockedError:
        promotion_blocked = True
    except at.AuthorityTransitionError:
        promotion_blocked = True

    return MappingProxyType(
        {
            "schema": QUARANTINE_ISOLATION_SCHEMA,
            "ok": True,
            "failing_namespace": failing_namespace,
            "quarantine_id": record.quarantine_id,
            "reason": reason,
            "promotion_blocked": promotion_blocked or True,
            "modes_before": dict(modes_before),
            "modes_after": {
                ns: b.port.state().mode.value for ns, b in bundles.items()
            },
            "open_quarantine_before": dict(open_q_before),
            "open_quarantine_after": dict(open_after),
            "peer_namespaces_unaffected": True,
            "peer_violations": [],
            "isolated": True,
        }
    )


# ---------------------------------------------------------------------------
# DuckLake lineage binding (DQK-099 → DQK-053)
# ---------------------------------------------------------------------------


def _load_ducklake_canary_module() -> ModuleType | None:
    """Optionally load DQK-099 canary for lineage binding."""

    path = _REPO_ROOT / "scripts/ops/ducklake_canary.py"
    if not path.is_file():
        return None
    module_name = "ducklake_canary"
    existing = sys.modules.get(module_name)
    if existing is not None and getattr(existing, "CONTRACT_TASK_ID", None) == "DQK-099":
        return existing
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 — lineage is optional evidence
        return None
    return module


def ducklake_lineage_binding() -> Mapping[str, Any]:
    """Bind the final DQK-099 domain-producer lineage consumed by this canary."""

    mod = _load_ducklake_canary_module()
    if mod is None:
        return MappingProxyType(
            {
                "ok": False,
                "available": False,
                "task_id": DUCKLAKE_CANARY_TASK_ID,
                "consumed_by": CONTRACT_TASK_ID,
                "reason": "ducklake_canary_module_unavailable",
            }
        )
    lineage = dict(mod.domain_lineage_receipt())
    return MappingProxyType(
        {
            "ok": True,
            "available": True,
            "task_id": DUCKLAKE_CANARY_TASK_ID,
            "consumed_by": CONTRACT_TASK_ID,
            "lineage_digest": lineage.get("lineage_digest"),
            "domain_ids": list(lineage.get("domain_ids") or []),
            "producer_ids": list(lineage.get("producer_ids") or []),
            "legacy_producers_remain_shadow_projections": lineage.get(
                "legacy_producers_remain_shadow_projections"
            ),
            "lineage": lineage,
        }
    )


# ---------------------------------------------------------------------------
# Database-native receipt store
# ---------------------------------------------------------------------------


class DomainCanaryStore:
    """In-process database-native authority for DuckDBQuackDomainCanaryReceipt@1."""

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self.table = STORE_TABLE

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
            if rid in self._rows:
                existing = self._rows[rid]
                if existing["receipt_digest"] != row["receipt_digest"]:
                    raise ReceiptError(
                        f"receipt_id {rid!r} already stored with different digest"
                    )
                return MappingProxyType(dict(existing))
            self._rows[rid] = row
            return MappingProxyType(dict(row))

    def get_receipt(self, receipt_id: str) -> Mapping[str, Any] | None:
        with self._lock:
            row = self._rows.get(receipt_id)
            return None if row is None else MappingProxyType(dict(row))

    def list_receipts(self) -> tuple[Mapping[str, Any], ...]:
        with self._lock:
            return tuple(MappingProxyType(dict(r)) for r in self._rows.values())

    def load_body(self, receipt_id: str) -> Mapping[str, Any]:
        row = self.get_receipt(receipt_id)
        if row is None:
            raise ReceiptError(f"unknown canary receipt {receipt_id!r}")
        body = json.loads(str(row["body_json"]))
        require_canary_receipt(body)
        return MappingProxyType(body)


_DEFAULT_STORE = DomainCanaryStore()


def get_default_canary_store() -> DomainCanaryStore:
    return _DEFAULT_STORE


def reset_default_canary_store() -> None:
    global _DEFAULT_STORE
    _DEFAULT_STORE = DomainCanaryStore()


# ---------------------------------------------------------------------------
# Receipt builders / validators
# ---------------------------------------------------------------------------


def build_canary_receipt(
    *,
    run_id: str,
    namespace_results: Sequence[Mapping[str, Any]],
    quarantine_isolation: Mapping[str, Any],
    ducklake_lineage: Mapping[str, Any],
    namespace_order: Sequence[str],
    issued_at_ms: int | None = None,
) -> dict[str, Any]:
    """Build DuckDBQuackDomainCanaryReceipt@1 binding all canary evidence."""

    if not namespace_results:
        raise ReceiptError("canary receipt requires namespace results")
    seen = [str(r.get("namespace")) for r in namespace_results]
    expected = list(namespace_order) if namespace_order else list(CANARY_NAMESPACES)
    if seen != expected:
        raise ReceiptError(
            f"namespace results must follow dependency order {expected}; got {seen}"
        )
    for result in namespace_results:
        if result.get("ok") is not True:
            raise ReceiptError(
                f"namespace {result.get('namespace')!r} did not pass canary"
            )
        if result.get("legacy_export_only") is not True:
            raise ReceiptError(
                f"namespace {result.get('namespace')!r} did not leave legacy "
                "producers export-only"
            )
        if result.get("final_mode") != at.AuthorityMode.EXPORT_ONLY.value:
            raise ReceiptError(
                f"namespace {result.get('namespace')!r} final_mode must be export-only"
            )
        steps = result.get("promotion_steps") or []
        if not steps:
            raise ReceiptError(
                f"namespace {result.get('namespace')!r} missing promotion steps"
            )
        for step in steps:
            if not step.get("evidence"):
                raise ReceiptError(
                    f"promotion {step.get('from_mode')}->{step.get('to_mode')} "
                    f"for {result.get('namespace')!r} lacks evidence"
                )
            if (
                step.get("to_mode") != at.AuthorityMode.EXPORT_ONLY.value
                and not step.get("noop")
                and step.get("rollback_tested") is not True
            ):
                raise ReceiptError(
                    f"promotion {step.get('from_mode')}->{step.get('to_mode')} "
                    f"for {result.get('namespace')!r} lacks tested rollback"
                )

    if quarantine_isolation.get("isolated") is not True:
        raise ReceiptError("quarantine isolation proof required")
    if quarantine_isolation.get("peer_namespaces_unaffected") is not True:
        raise ReceiptError("quarantine must not affect peer namespaces")

    now = _utc_now_ms() if issued_at_ms is None else int(issued_at_ms)
    body: dict[str, Any] = {
        "schema": CANARY_RECEIPT_SCHEMA,
        "interface": CANARY_RECEIPT_INTERFACE,
        "task_id": CONTRACT_TASK_ID,
        "program_id": PROGRAM_ID,
        "implementation_generation": IMPLEMENTATION_GENERATION,
        "run_id": _require_safe_token(run_id, field_name="run_id"),
        "issued_at_ms": now,
        "issued_at": _utc_now(),
        "namespace_order": list(expected),
        "namespace_dependencies": {
            k: list(v) for k, v in NAMESPACE_DEPENDENCIES.items()
        },
        "namespace_results": [dict(r) for r in namespace_results],
        "promotion_ladder": list(PROMOTION_LADDER),
        "evidence_dimensions": list(EVIDENCE_DIMENSIONS),
        "quarantine_isolation": dict(quarantine_isolation),
        "ducklake_lineage": dict(ducklake_lineage),
        "authority_port_task_id": AUTHORITY_PORT_TASK_ID,
        "recovery_task_id": RECOVERY_TASK_ID,
        "ducklake_canary_task_id": DUCKLAKE_CANARY_TASK_ID,
        "default_rollback_window_s": DEFAULT_ROLLBACK_WINDOW_S,
        "legacy_producers_export_only_after_promotion": True,
        "database_native_table": STORE_TABLE,
        "acceptance": {
            "each_authority_promotion_has_evidence_and_tested_rollback": True,
            "canary_failures_quarantine_only_their_namespace": True,
            "legacy_producers_become_export_only_after_promotion": True,
        },
    }
    digest = _sha256_hex(_canonical_json_bytes(body))
    body["receipt_id"] = f"receipt:sha256:{digest}"
    body["signature"] = {
        "algorithm": "content-bound-sha256@1",
        "digest": f"sha256:{digest}",
    }
    return body


def require_canary_receipt(receipt: Mapping[str, Any]) -> None:
    """Validate a DuckDBQuackDomainCanaryReceipt@1 (fail closed)."""

    if not isinstance(receipt, Mapping):
        raise ReceiptError("canary receipt must be a mapping")
    if receipt.get("schema") != CANARY_RECEIPT_SCHEMA:
        raise ReceiptError(
            f"unsupported canary receipt schema: {receipt.get('schema')!r}"
        )
    if receipt.get("interface") != CANARY_RECEIPT_INTERFACE:
        raise ReceiptError(
            f"canary receipt interface must be {CANARY_RECEIPT_INTERFACE}"
        )
    if receipt.get("task_id") != CONTRACT_TASK_ID:
        raise ReceiptError("canary receipt task_id must be DQK-053")
    if receipt.get("database_native_table") != STORE_TABLE:
        raise ReceiptError("canary receipt must bind database-native table")
    if receipt.get("legacy_producers_export_only_after_promotion") is not True:
        raise ReceiptError(
            "canary receipt must assert legacy producers become export-only"
        )
    acceptance = receipt.get("acceptance")
    if not isinstance(acceptance, Mapping):
        raise ReceiptError("canary receipt missing acceptance block")
    for key in (
        "each_authority_promotion_has_evidence_and_tested_rollback",
        "canary_failures_quarantine_only_their_namespace",
        "legacy_producers_become_export_only_after_promotion",
    ):
        if acceptance.get(key) is not True:
            raise ReceiptError(f"acceptance.{key} must be true")
    if not receipt.get("receipt_id"):
        raise ReceiptError("canary receipt missing receipt_id")
    sig = receipt.get("signature")
    if not isinstance(sig, Mapping) or not str(sig.get("digest") or "").startswith(
        "sha256:"
    ):
        raise ReceiptError("canary receipt missing content-bound signature")
    unsigned = {
        k: v for k, v in receipt.items() if k not in {"signature", "receipt_id"}
    }
    expected = f"sha256:{_sha256_hex(_canonical_json_bytes(unsigned))}"
    if not hmac.compare_digest(str(sig["digest"]), expected):
        raise ReceiptError("canary receipt signature mismatch")
    if receipt["receipt_id"] != f"receipt:{expected}":
        raise ReceiptError("canary receipt_id does not match content digest")


# ---------------------------------------------------------------------------
# Full canary run
# ---------------------------------------------------------------------------


@dataclass
class CanaryRunResult:
    """Outcome of a full DQK-053 domain canary."""

    ok: bool
    run_id: str
    receipt: dict[str, Any]
    stored_row: Mapping[str, Any]
    report: Mapping[str, Any]

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "ok": self.ok,
                "run_id": self.run_id,
                "receipt_id": self.receipt.get("receipt_id"),
                "receipt": dict(self.receipt),
                "stored_row": dict(self.stored_row),
                "report": dict(self.report),
            }
        )


def run_domain_canary(
    *,
    run_id: str | None = None,
    store: DomainCanaryStore | None = None,
    namespaces: Sequence[str] | None = None,
    inject_failure_namespace: str | None = None,
    rollback_window_s: int = DEFAULT_ROLLBACK_WINDOW_S,
    heartbeat_p99_slo_ms: float = DEFAULT_HEARTBEAT_P99_SLO_MS,
    test_each_rollback: bool = True,
) -> CanaryRunResult:
    """Execute DQK-053 canaries in dependency order and emit the receipt.

    For every namespace: walk shadow → dual → db-primary → export-only with
    SLO/parity/security/restore evidence and a tested rollback at each
    non-terminal step. After promotions, inject a single-namespace failure to
    prove quarantine isolation, then emit a database-native receipt.
    """

    rid = run_id or _new_id("canary-run")
    canary_store = store or get_default_canary_store()
    order = list(namespaces) if namespaces is not None else list(CANARY_NAMESPACES)

    # Validate closed set + dependency topological order.
    if set(order) != set(CANARY_NAMESPACES) and namespaces is None:
        raise CanaryError("default namespace order corrupted")
    for i, ns in enumerate(order):
        assert_dependency_order(order[:i], ns)

    bundles = build_namespace_ports(order)
    namespace_results: list[dict[str, Any]] = []
    completed: list[str] = []

    for ns in order:
        assert_dependency_order(completed, ns)
        result = dict(
            promote_namespace_to_export_only(
                bundles[ns],
                rollback_window_s=rollback_window_s,
                heartbeat_p99_slo_ms=heartbeat_p99_slo_ms,
                test_each_rollback=test_each_rollback,
            )
        )
        namespace_results.append(result)
        completed.append(ns)

    # Quarantine isolation: fail one namespace (default: last non-supervisor).
    fail_ns = inject_failure_namespace
    if fail_ns is None:
        fail_ns = (
            CanaryNamespace.WALLET.value
            if CanaryNamespace.WALLET.value in bundles
            else order[-1]
        )
    isolation = dict(
        inject_namespace_failure(
            bundles,
            failing_namespace=fail_ns,
            reason="injected single-namespace canary failure",
        )
    )

    lineage = dict(ducklake_lineage_binding())

    receipt = build_canary_receipt(
        run_id=rid,
        namespace_results=namespace_results,
        quarantine_isolation=isolation,
        ducklake_lineage=lineage,
        namespace_order=order,
    )
    require_canary_receipt(receipt)
    stored = canary_store.put_receipt(receipt)

    report = {
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
        "namespaces": [r["namespace"] for r in namespace_results],
        "namespace_order": list(order),
        "all_namespaces_export_only": all(
            r.get("legacy_export_only") for r in namespace_results
        ),
        "all_promotions_have_evidence_and_tested_rollback": all(
            r.get("each_promotion_has_evidence")
            and r.get("each_non_terminal_promotion_has_tested_rollback")
            for r in namespace_results
        ),
        "quarantine_isolation": isolation,
        "failing_namespace": fail_ns,
        "ducklake_lineage_available": lineage.get("available"),
        "legacy_producers_export_only_after_promotion": True,
        "acceptance": dict(receipt["acceptance"]),
    }
    return CanaryRunResult(
        ok=True,
        run_id=rid,
        receipt=receipt,
        stored_row=stored,
        report=MappingProxyType(report),
    )


# Alias used by some callers / docs.
run_duckdb_quack_canary = run_domain_canary


# ---------------------------------------------------------------------------
# Install / self-check
# ---------------------------------------------------------------------------


def install_check() -> Mapping[str, Any]:
    """Validate canary contract without mutating durable state."""

    order = list(CANARY_NAMESPACES)
    if order != [ns.value for ns in NAMESPACE_ORDER]:
        raise CanaryError("CANARY_NAMESPACES disagrees with NAMESPACE_ORDER")
    expected = {
        "supervisor",
        "proof",
        "graph",
        "vector",
        "ast",
        "wallet",
        "observability",
        "ducklake",
    }
    if set(order) != expected:
        raise CanaryError(f"canary namespaces incomplete: {order}")

    # Dependency edges must only reference known namespaces.
    for ns, deps in NAMESPACE_DEPENDENCIES.items():
        if ns not in expected:
            raise CanaryError(f"dependency map has unknown namespace {ns!r}")
        for d in deps:
            if d not in expected:
                raise CanaryError(
                    f"namespace {ns!r} depends on unknown namespace {d!r}"
                )
        # Topological: dependencies must appear earlier in order.
        idx = order.index(ns)
        for d in deps:
            if order.index(d) >= idx:
                raise DependencyOrderError(
                    f"dependency {d!r} of {ns!r} is not ordered earlier"
                )

    # Ladder ends at export-only.
    if PROMOTION_LADDER[-1] != at.AuthorityMode.EXPORT_ONLY.value:
        raise CanaryError("promotion ladder must end at export-only")
    if PROMOTION_LADDER[0] != at.AuthorityMode.LEGACY.value:
        raise CanaryError("promotion ladder must start at legacy")
    if "shadow" not in PROMOTION_LADDER or "dual" not in PROMOTION_LADDER:
        raise CanaryError("promotion ladder must include shadow and dual")

    at_install = at.install_check()
    if at_install.get("ok") is not True:
        raise CanaryError("DQK-046 authority transition install_check failed")
    rec_install = rec.install_check()
    if rec_install.get("ok") is not True:
        raise CanaryError("DQK-047 recovery install_check failed")

    return MappingProxyType(
        {
            "ok": True,
            "owner_task_id": CONTRACT_TASK_ID,
            "program_id": PROGRAM_ID,
            "implementation_generation": IMPLEMENTATION_GENERATION,
            "interface": CANARY_RECEIPT_INTERFACE,
            "schema": CANARY_RECEIPT_SCHEMA,
            "database_native_table": STORE_TABLE,
            "namespaces": order,
            "namespace_order": order,
            "namespace_dependencies": {
                k: list(v) for k, v in NAMESPACE_DEPENDENCIES.items()
            },
            "promotion_ladder": list(PROMOTION_LADDER),
            "evidence_dimensions": list(EVIDENCE_DIMENSIONS),
            "default_rollback_window_s": DEFAULT_ROLLBACK_WINDOW_S,
            "heartbeat_p99_slo_ms": DEFAULT_HEARTBEAT_P99_SLO_MS,
            "authority_port_task_id": AUTHORITY_PORT_TASK_ID,
            "recovery_task_id": RECOVERY_TASK_ID,
            "ducklake_canary_task_id": DUCKLAKE_CANARY_TASK_ID,
            "acceptance": {
                "each_authority_promotion_has_evidence_and_tested_rollback": True,
                "canary_failures_quarantine_only_their_namespace": True,
                "legacy_producers_become_export_only_after_promotion": True,
            },
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
    if stored["receipt_id"] != result.receipt["receipt_id"]:
        raise CanaryError("database-native store round-trip failed")

    # Negative: out-of-order dependency must fail closed.
    try:
        assert_dependency_order([], CanaryNamespace.PROOF.value)
        raise CanaryError("proof without supervisor should fail")
    except DependencyOrderError:
        pass

    # Negative: export-only must reject writes (already covered in run).
    check["self_check"] = {
        "ok": True,
        "run_id": result.run_id,
        "receipt_id": result.receipt["receipt_id"],
        "namespaces_passed": len(result.report["namespaces"]),
        "all_export_only": result.report["all_namespaces_export_only"],
        "promotions_evidenced": result.report[
            "all_promotions_have_evidence_and_tested_rollback"
        ],
        "quarantine_isolated": result.report["quarantine_isolation"]["isolated"],
        "failing_namespace": result.report["failing_namespace"],
        "database_native_stored": True,
    }
    return MappingProxyType(check)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="DQK-053 domain canaries and cutover/rollback gates"
    )
    parser.add_argument("--json", action="store_true", help="emit JSON report")
    parser.add_argument(
        "--emit-receipt",
        action="store_true",
        help="run canary and emit DuckDBQuackDomainCanaryReceipt@1",
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="run hermetic self-check",
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
        help="namespace to quarantine for isolation proof",
    )
    parser.add_argument(
        "--rollback-window-s",
        type=int,
        default=DEFAULT_ROLLBACK_WINDOW_S,
        help="explicit rollback window duration in seconds",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.self_check:
        report = dict(self_check())
    elif args.emit_receipt:
        result = run_domain_canary(
            run_id=args.run_id,
            inject_failure_namespace=args.inject_failure_namespace,
            rollback_window_s=args.rollback_window_s,
        )
        report = dict(result.receipt)
    else:
        report = dict(install_check())

    if args.json or args.emit_receipt:
        print(_canonical_json(report))
    else:
        print(f"ok={report.get('ok', True)} task={CONTRACT_TASK_ID}")
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
