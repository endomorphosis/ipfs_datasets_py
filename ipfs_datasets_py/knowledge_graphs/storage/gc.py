"""Reachability, pin policy, and garbage collection (KGP-012).

Conflict policy (from the production-hardening board):

* GC only immutable objects proven **unreachable** from catalog roots and
  active leases.
* Default mode is **dry-run** (plan only; no deletes).
* Only **abandoned staged** objects are selected for collection — never live
  branch / tag / snapshot / lease pin roots.
* Interrupted GC is recoverable via a durable journal: restart re-loads the
  plan, re-validates reachability, and finishes or aborts safely.

Catalog roots collected when a :class:`~ipfs_datasets_py.knowledge_graphs.catalog.store.GraphCatalog`
is available:

* active branch heads (``pin_root`` / ``manifest_cid`` / revision pin roots)
* explicit ``pin_roots`` rows (any ``pin_kind``, including tag/snapshot)
* active (non-expired) writer leases — protect staged objects bound to the lease
* extra roots registered on a :class:`HybridGraphStore` (tags/snapshots/leases)
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Set,
    Tuple,
    Union,
    runtime_checkable,
)

from ipfs_datasets_py.knowledge_graphs.storage.hybrid import (
    AuthoritativeCopy,
    CacheEntryMeta,
    HybridGraphStore,
    ObjectLifecycle,
    VerifiedHybridCache,
    atomic_write_json,
)
from ipfs_datasets_py.knowledge_graphs.storage.ipld_store import GraphStoreError

logger = logging.getLogger(__name__)

GC_JOURNAL_SCHEMA: str = "1"
DEFAULT_ROOT_KINDS = frozenset(
    {"branch", "tag", "snapshot", "lease", "manifest", "pin", "revision"}
)
COLLECTIBLE_LIFECYCLES = frozenset(
    {ObjectLifecycle.ABANDONED.value, ObjectLifecycle.STAGED.value}
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class RootKind(str, Enum):
    BRANCH = "branch"
    TAG = "tag"
    SNAPSHOT = "snapshot"
    LEASE = "lease"
    MANIFEST = "manifest"
    PIN = "pin"
    REVISION = "revision"
    STAGED = "staged"
    EXTRA = "extra"


@dataclass(frozen=True, slots=True)
class ReachableRoot:
    """A durable pin root that must remain reachable."""

    cid: str
    kind: str
    tenant: Optional[str] = None
    graph_id: Optional[str] = None
    revision_id: Optional[str] = None
    name: Optional[str] = None  # branch / tag / snapshot name
    lease_id: Optional[str] = None
    source: str = "explicit"
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cid": self.cid,
            "kind": self.kind,
            "tenant": self.tenant,
            "graph_id": self.graph_id,
            "revision_id": self.revision_id,
            "name": self.name,
            "lease_id": self.lease_id,
            "source": self.source,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReachableRoot":
        return cls(
            cid=str(data["cid"]),
            kind=str(data.get("kind") or RootKind.PIN.value),
            tenant=data.get("tenant"),
            graph_id=data.get("graph_id"),
            revision_id=data.get("revision_id"),
            name=data.get("name"),
            lease_id=data.get("lease_id"),
            source=str(data.get("source") or "explicit"),
            details=dict(data.get("details") or {}),
        )


@dataclass(frozen=True, slots=True)
class GCCandidate:
    """Object selected for collection (must be abandoned staged)."""

    cid: str
    reason: str
    size: int = 0
    lifecycle: str = ObjectLifecycle.ABANDONED.value
    lease_id: Optional[str] = None
    tenant: Optional[str] = None
    graph_id: Optional[str] = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cid": self.cid,
            "reason": self.reason,
            "size": self.size,
            "lifecycle": self.lifecycle,
            "lease_id": self.lease_id,
            "tenant": self.tenant,
            "graph_id": self.graph_id,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GCCandidate":
        return cls(
            cid=str(data["cid"]),
            reason=str(data.get("reason") or "abandoned_staged"),
            size=int(data.get("size") or 0),
            lifecycle=str(data.get("lifecycle") or ObjectLifecycle.ABANDONED.value),
            lease_id=data.get("lease_id"),
            tenant=data.get("tenant"),
            graph_id=data.get("graph_id"),
            details=dict(data.get("details") or {}),
        )


class GCPhase(str, Enum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    ABORTED = "aborted"
    INTERRUPTED = "interrupted"


@dataclass
class GCPlan:
    """Immutable GC plan produced by dry-run or execute preparation."""

    plan_id: str
    created_at: float
    dry_run: bool
    roots: List[ReachableRoot]
    reachable_cids: List[str]
    candidates: List[GCCandidate]
    protected_cids: List[str]
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "created_at": self.created_at,
            "dry_run": self.dry_run,
            "roots": [r.to_dict() for r in self.roots],
            "reachable_cids": list(self.reachable_cids),
            "candidates": [c.to_dict() for c in self.candidates],
            "protected_cids": list(self.protected_cids),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GCPlan":
        return cls(
            plan_id=str(data["plan_id"]),
            created_at=float(data.get("created_at") or 0.0),
            dry_run=bool(data.get("dry_run", True)),
            roots=[ReachableRoot.from_dict(r) for r in data.get("roots") or []],
            reachable_cids=[str(c) for c in data.get("reachable_cids") or []],
            candidates=[GCCandidate.from_dict(c) for c in data.get("candidates") or []],
            protected_cids=[str(c) for c in data.get("protected_cids") or []],
            notes=[str(n) for n in data.get("notes") or []],
        )


@dataclass
class GCResult:
    """Outcome of a GC run (dry-run or execute)."""

    plan_id: str
    dry_run: bool
    phase: str
    deleted: List[str]
    skipped: List[str]
    protected: List[str]
    candidates: List[GCCandidate]
    roots: List[ReachableRoot]
    bytes_freed: int = 0
    error: Optional[str] = None
    recovered_from_journal: bool = False
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "dry_run": self.dry_run,
            "phase": self.phase,
            "deleted": list(self.deleted),
            "skipped": list(self.skipped),
            "protected": list(self.protected),
            "candidates": [c.to_dict() for c in self.candidates],
            "roots": [r.to_dict() for r in self.roots],
            "bytes_freed": self.bytes_freed,
            "error": self.error,
            "recovered_from_journal": self.recovered_from_journal,
            "notes": list(self.notes),
        }


@dataclass
class GCJournalState:
    """Durable journal for interrupted-GC recovery."""

    schema_version: str
    plan_id: str
    phase: str
    dry_run: bool
    plan: Dict[str, Any]
    deleted: List[str]
    pending: List[str]
    updated_at: float
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "phase": self.phase,
            "dry_run": self.dry_run,
            "plan": dict(self.plan),
            "deleted": list(self.deleted),
            "pending": list(self.pending),
            "updated_at": self.updated_at,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GCJournalState":
        return cls(
            schema_version=str(data.get("schema_version") or GC_JOURNAL_SCHEMA),
            plan_id=str(data["plan_id"]),
            phase=str(data.get("phase") or GCPhase.PLANNED.value),
            dry_run=bool(data.get("dry_run", True)),
            plan=dict(data.get("plan") or {}),
            deleted=[str(c) for c in data.get("deleted") or []],
            pending=[str(c) for c in data.get("pending") or []],
            updated_at=float(data.get("updated_at") or 0.0),
            error=data.get("error"),
        )


# ---------------------------------------------------------------------------
# Inventory / pin protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class GCInventory(Protocol):
    """Object inventory consumed by the garbage collector."""

    def list_objects(self) -> Sequence[CacheEntryMeta]: ...

    def delete_object(self, cid: str, *, force: bool = False) -> bool: ...

    def is_pinned(self, cid: str) -> bool: ...

    def pin(self, cid: str, *, root_kind: Optional[str] = None) -> None: ...

    def list_registered_roots(self) -> Sequence[Mapping[str, Any]]: ...


# ---------------------------------------------------------------------------
# Reachability
# ---------------------------------------------------------------------------


def _is_expired_iso(expires_at: str, *, now: Optional[float] = None) -> bool:
    """Best-effort ISO-8601 expiry check; fail closed (treat as active) on parse errors."""
    try:
        from ipfs_datasets_py.knowledge_graphs.catalog.identity import is_expired

        return bool(is_expired(expires_at))
    except Exception:
        # Fallback: if we cannot parse, treat as still active (fail closed for GC).
        return False


def collect_catalog_roots(
    catalog: Any,
    *,
    tenant: Optional[str] = None,
    graph_id: Optional[str] = None,
    include_tombstoned_graphs: bool = False,
) -> List[ReachableRoot]:
    """Collect branch / pin / lease roots from a GraphCatalog instance.

    ``catalog`` is typed as ``Any`` so tests can inject light doubles without
    importing the catalog module at package import time.
    """
    roots: List[ReachableRoot] = []
    if catalog is None:
        return roots

    # Resolve tenants.
    tenants: List[str]
    if tenant is not None:
        tenants = [tenant]
    elif hasattr(catalog, "list_tenants"):
        tenants = list(catalog.list_tenants())
    else:
        # Scan via private connection when available.
        tenants = _discover_tenants(catalog)

    for t in tenants:
        try:
            graphs = catalog.list_graphs(t, include_tombstoned=include_tombstoned_graphs)
        except Exception as exc:
            logger.warning("list_graphs failed for tenant %s: %s", t, exc)
            continue
        for g in graphs:
            gid = getattr(g, "graph_id", None) or g.get("graph_id")  # type: ignore[union-attr]
            if graph_id is not None and gid != graph_id:
                continue
            roots.extend(_roots_for_graph(catalog, t, gid))
    return roots


def _discover_tenants(catalog: Any) -> List[str]:
    path = getattr(catalog, "path", None)
    if path is None and hasattr(catalog, "_path"):
        path = catalog._path
    if path is None:
        return []
    try:
        import sqlite3

        conn = sqlite3.connect(str(path))
        try:
            rows = conn.execute("SELECT DISTINCT tenant FROM graphs").fetchall()
            return [str(r[0]) for r in rows]
        finally:
            conn.close()
    except Exception:
        return []


def _roots_for_graph(catalog: Any, tenant: str, graph_id: str) -> List[ReachableRoot]:
    roots: List[ReachableRoot] = []

    # Branch heads.
    try:
        branches = catalog.list_branches(tenant, graph_id, include_tombstoned=False)
    except TypeError:
        try:
            branches = catalog.list_branches(tenant, graph_id)
        except Exception:
            branches = []
    except Exception:
        branches = []

    for br in branches:
        branch_name = getattr(br, "branch", None) or br.get("branch")  # type: ignore[union-attr]
        head = getattr(br, "head_revision", None) or br.get("head_revision")  # type: ignore[union-attr]
        if not head:
            continue
        # Resolve pin_root / manifest_cid from revision record.
        rev = None
        try:
            rev = catalog.get_revision(tenant, graph_id, head)
        except Exception:
            rev = None
        pin_cid = None
        if rev is not None:
            pin_cid = (
                getattr(rev, "pin_root", None)
                or getattr(rev, "manifest_cid", None)
                or (rev.get("pin_root") if isinstance(rev, Mapping) else None)
                or (rev.get("manifest_cid") if isinstance(rev, Mapping) else None)
            )
        if pin_cid:
            roots.append(
                ReachableRoot(
                    cid=str(pin_cid),
                    kind=RootKind.BRANCH.value,
                    tenant=tenant,
                    graph_id=graph_id,
                    revision_id=str(head),
                    name=str(branch_name) if branch_name else None,
                    source="catalog.branch",
                )
            )
        # Also protect the revision id itself when it looks like a CID.
        if head and str(head).startswith(("b", "Qm")):
            roots.append(
                ReachableRoot(
                    cid=str(head),
                    kind=RootKind.REVISION.value,
                    tenant=tenant,
                    graph_id=graph_id,
                    revision_id=str(head),
                    name=str(branch_name) if branch_name else None,
                    source="catalog.branch_revision",
                )
            )

    # Explicit pin roots (tags/snapshots/manifest/...).
    try:
        pins = catalog.list_pin_roots(tenant, graph_id)
    except Exception:
        pins = []
    for pin in pins:
        root_cid = getattr(pin, "root_cid", None) or pin.get("root_cid")  # type: ignore[union-attr]
        pin_kind = getattr(pin, "pin_kind", None) or pin.get("pin_kind") or "pin"  # type: ignore[union-attr]
        revision_id = getattr(pin, "revision_id", None) or pin.get("revision_id")  # type: ignore[union-attr]
        if not root_cid:
            continue
        kind = str(pin_kind)
        # Normalize common pin kinds into RootKind values.
        if kind not in {k.value for k in RootKind}:
            if kind in {"tag", "snapshot", "lease", "manifest", "branch"}:
                pass
            else:
                kind = RootKind.PIN.value
        roots.append(
            ReachableRoot(
                cid=str(root_cid),
                kind=kind,
                tenant=tenant,
                graph_id=graph_id,
                revision_id=str(revision_id) if revision_id else None,
                source="catalog.pin_root",
                details={"pin_kind": str(pin_kind)},
            )
        )

    # Active leases protect staged objects bound to the lease.
    try:
        branches = catalog.list_branches(tenant, graph_id)
    except Exception:
        branches = []
    for br in branches:
        branch_name = getattr(br, "branch", None) or br.get("branch")  # type: ignore[union-attr]
        if not branch_name:
            continue
        try:
            lease = catalog.get_lease(tenant, graph_id, branch_name)
        except Exception:
            lease = None
        if lease is None:
            continue
        expires_at = getattr(lease, "expires_at", None) or (
            lease.get("expires_at") if isinstance(lease, Mapping) else None
        )
        if expires_at and _is_expired_iso(str(expires_at)):
            continue
        lease_id = getattr(lease, "lease_id", None) or (
            lease.get("lease_id") if isinstance(lease, Mapping) else None
        )
        # Lease itself does not always hold a CID; mark via details for staged matching.
        roots.append(
            ReachableRoot(
                cid=f"lease:{lease_id}" if lease_id else f"lease:{tenant}/{graph_id}/{branch_name}",
                kind=RootKind.LEASE.value,
                tenant=tenant,
                graph_id=graph_id,
                name=str(branch_name),
                lease_id=str(lease_id) if lease_id else None,
                source="catalog.lease",
                details={"expires_at": expires_at},
            )
        )
    return roots


def collect_hybrid_roots(store: HybridGraphStore) -> List[ReachableRoot]:
    """Collect explicitly registered roots from a HybridGraphStore."""
    roots: List[ReachableRoot] = []
    for raw in store.list_registered_roots():
        cid = str(raw.get("cid") or "")
        if not cid:
            continue
        roots.append(
            ReachableRoot(
                cid=cid,
                kind=str(raw.get("kind") or RootKind.EXTRA.value),
                tenant=raw.get("tenant"),
                graph_id=raw.get("graph_id"),
                name=raw.get("name"),
                source="hybrid.registered",
                details=dict(raw),
            )
        )
    # Pinned cache entries with root_kind in the durable set are also roots.
    for meta in store.list_objects():
        if meta.pin_count <= 0:
            continue
        kind = meta.root_kind or RootKind.PIN.value
        if kind == RootKind.STAGED.value:
            continue
        roots.append(
            ReachableRoot(
                cid=meta.cid,
                kind=kind,
                tenant=meta.tenant,
                graph_id=meta.graph_id,
                revision_id=meta.revision_id,
                lease_id=meta.lease_id,
                source="hybrid.pinned",
            )
        )
    return roots


def compute_reachable_set(
    roots: Sequence[ReachableRoot],
    *,
    inventory: Optional[Sequence[CacheEntryMeta]] = None,
    expand: Optional[Callable[[str], Iterable[str]]] = None,
) -> Set[str]:
    """Compute the set of CIDs reachable from durable roots.

    Non-CID lease markers (``lease:...``) are not content CIDs; they only
    protect staged objects via lease_id matching during candidate selection.
    """
    reachable: Set[str] = set()
    queue: List[str] = []
    for root in roots:
        cid = root.cid
        if cid.startswith("lease:"):
            continue
        if cid not in reachable:
            reachable.add(cid)
            queue.append(cid)

    # Expand via optional walker (e.g. DAG-CBOR link following).
    if expand is not None:
        seen_expand: Set[str] = set(queue)
        while queue:
            current = queue.pop()
            try:
                children = list(expand(current))
            except Exception:
                children = []
            for child in children:
                if child in seen_expand:
                    continue
                seen_expand.add(child)
                reachable.add(child)
                queue.append(child)

    return reachable


def active_lease_ids(roots: Sequence[ReachableRoot]) -> Set[str]:
    return {r.lease_id for r in roots if r.kind == RootKind.LEASE.value and r.lease_id}


# ---------------------------------------------------------------------------
# Pin policy
# ---------------------------------------------------------------------------


class PinPolicy:
    """Ensure every branch/tag/snapshot/lease root remains pinned."""

    def __init__(self, store: HybridGraphStore) -> None:
        self.store = store

    def ensure_roots_pinned(
        self,
        roots: Sequence[ReachableRoot],
    ) -> List[str]:
        """Pin every content CID root; return list of CIDs pinned/confirmed."""
        pinned: List[str] = []
        for root in roots:
            if root.cid.startswith("lease:"):
                continue
            if root.kind == RootKind.STAGED.value:
                continue
            try:
                self.store.pin(root.cid, root_kind=root.kind)
                pinned.append(root.cid)
            except GraphStoreError as err:
                # Root may be a logical revision id not present as a block.
                logger.debug("pin skipped for %s: %s", root.cid, err)
        return pinned

    def assert_roots_reachable(
        self,
        roots: Sequence[ReachableRoot],
        reachable: Set[str],
    ) -> List[str]:
        """Return root CIDs that failed reachability (should be empty)."""
        missing: List[str] = []
        for root in roots:
            if root.cid.startswith("lease:"):
                continue
            if root.cid not in reachable:
                missing.append(root.cid)
        return missing


# ---------------------------------------------------------------------------
# GC journal
# ---------------------------------------------------------------------------


class GCJournal:
    """Durable journal for plan + progress (interrupted-GC recovery)."""

    def __init__(self, path: Union[str, Path]) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def write(self, state: GCJournalState) -> None:
        with self._lock:
            atomic_write_json(self.path, state.to_dict())

    def read(self) -> Optional[GCJournalState]:
        with self._lock:
            if not self.path.is_file():
                return None
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                return None
            if not isinstance(data, Mapping):
                return None
            try:
                return GCJournalState.from_dict(data)
            except Exception:
                return None

    def clear(self) -> None:
        with self._lock:
            if self.path.exists():
                try:
                    self.path.unlink()
                except OSError:
                    pass

    def mark_interrupted(self) -> Optional[GCJournalState]:
        state = self.read()
        if state is None:
            return None
        if state.phase in {GCPhase.COMPLETED.value, GCPhase.ABORTED.value}:
            return state
        state.phase = GCPhase.INTERRUPTED.value
        state.updated_at = time.time()
        self.write(state)
        return state


# ---------------------------------------------------------------------------
# Garbage collector
# ---------------------------------------------------------------------------


class GarbageCollector:
    """Plan and execute GC over a hybrid store (+ optional catalog).

    Default ``dry_run=True``: builds a plan identifying only abandoned staged
    objects and never deletes. Execute mode writes a journal so an interrupted
    run can be recovered via :meth:`recover`.
    """

    def __init__(
        self,
        store: HybridGraphStore,
        *,
        catalog: Any = None,
        journal_path: Optional[Union[str, Path]] = None,
        expand_links: Optional[Callable[[str], Iterable[str]]] = None,
    ) -> None:
        self.store = store
        self.catalog = catalog
        self.pin_policy = PinPolicy(store)
        self.expand_links = expand_links
        if journal_path is None:
            journal_path = Path(store.cache.root) / "gc-journal.json"
        self.journal = GCJournal(journal_path)
        self._lock = threading.RLock()
        self._interrupt_requested = False
        # Test hook: call after each delete (may raise to simulate crash).
        self._after_delete_hook: Optional[Callable[[str, GCJournalState], None]] = None

    # -- planning ----------------------------------------------------------

    def collect_roots(
        self,
        *,
        tenant: Optional[str] = None,
        graph_id: Optional[str] = None,
        extra_roots: Optional[Sequence[ReachableRoot]] = None,
    ) -> List[ReachableRoot]:
        roots: List[ReachableRoot] = []
        roots.extend(collect_hybrid_roots(self.store))
        if self.catalog is not None:
            roots.extend(
                collect_catalog_roots(
                    self.catalog,
                    tenant=tenant,
                    graph_id=graph_id,
                )
            )
        if extra_roots:
            roots.extend(list(extra_roots))
        # Deduplicate by (cid, kind, lease_id).
        seen: Set[Tuple[str, str, Optional[str]]] = set()
        unique: List[ReachableRoot] = []
        for r in roots:
            key = (r.cid, r.kind, r.lease_id)
            if key in seen:
                continue
            seen.add(key)
            unique.append(r)
        return unique

    def plan(
        self,
        *,
        dry_run: bool = True,
        tenant: Optional[str] = None,
        graph_id: Optional[str] = None,
        extra_roots: Optional[Sequence[ReachableRoot]] = None,
        mark_unleased_staged_abandoned: bool = True,
    ) -> GCPlan:
        """Build a GC plan. Never deletes."""
        with self._lock:
            roots = self.collect_roots(
                tenant=tenant,
                graph_id=graph_id,
                extra_roots=extra_roots,
            )
            # Ensure durable roots stay pinned.
            pinned = self.pin_policy.ensure_roots_pinned(roots)
            reachable = compute_reachable_set(
                roots,
                inventory=self.store.list_objects(),
                expand=self.expand_links,
            )
            lease_ids = active_lease_ids(roots)

            notes: List[str] = []
            if pinned:
                notes.append(f"ensured_pins={len(pinned)}")

            objects = list(self.store.list_objects())
            candidates: List[GCCandidate] = []
            protected: List[str] = sorted(reachable)

            for meta in objects:
                # Live pin roots are never candidates.
                if meta.cid in reachable:
                    continue
                if meta.pin_count > 0 and meta.root_kind in DEFAULT_ROOT_KINDS:
                    protected.append(meta.cid)
                    continue
                if meta.pin_count > 0 and meta.lifecycle == ObjectLifecycle.COMMITTED.value:
                    protected.append(meta.cid)
                    continue

                # Active lease protects staged objects for that lease.
                if (
                    meta.lifecycle == ObjectLifecycle.STAGED.value
                    and meta.lease_id
                    and meta.lease_id in lease_ids
                ):
                    protected.append(meta.cid)
                    notes.append(f"lease_protected:{meta.cid}")
                    continue

                # Auto-mark unleased staged as abandoned for collection.
                lifecycle = meta.lifecycle
                if (
                    mark_unleased_staged_abandoned
                    and lifecycle == ObjectLifecycle.STAGED.value
                    and (not meta.lease_id or meta.lease_id not in lease_ids)
                ):
                    try:
                        self.store.abandon_staged(meta.cid)
                        lifecycle = ObjectLifecycle.ABANDONED.value
                        notes.append(f"auto_abandoned:{meta.cid}")
                    except GraphStoreError as err:
                        notes.append(f"auto_abandon_failed:{meta.cid}:{err.code}")

                if lifecycle not in COLLECTIBLE_LIFECYCLES:
                    continue
                # Only abandoned staged objects (or staged with no lease) are
                # collectible. Committed unreachable objects are intentionally
                # left alone (may be shared or pending pin registration).
                if lifecycle == ObjectLifecycle.STAGED.value:
                    # Still staged after auto-mark attempt → treat as abandoned
                    # only when no active lease.
                    if meta.lease_id and meta.lease_id in lease_ids:
                        continue
                    reason = "abandoned_staged"
                elif lifecycle == ObjectLifecycle.ABANDONED.value:
                    reason = "abandoned_staged"
                else:
                    continue

                candidates.append(
                    GCCandidate(
                        cid=meta.cid,
                        reason=reason,
                        size=meta.size,
                        lifecycle=lifecycle,
                        lease_id=meta.lease_id,
                        tenant=meta.tenant,
                        graph_id=meta.graph_id,
                        details={"root_kind": meta.root_kind},
                    )
                )

            # Dedup protected list.
            protected = sorted(set(protected))
            plan = GCPlan(
                plan_id=uuid.uuid4().hex,
                created_at=time.time(),
                dry_run=bool(dry_run),
                roots=list(roots),
                reachable_cids=sorted(reachable),
                candidates=candidates,
                protected_cids=protected,
                notes=notes,
            )
            return plan

    # -- execute / recover -------------------------------------------------

    def run(
        self,
        *,
        dry_run: bool = True,
        tenant: Optional[str] = None,
        graph_id: Optional[str] = None,
        extra_roots: Optional[Sequence[ReachableRoot]] = None,
        plan: Optional[GCPlan] = None,
    ) -> GCResult:
        """Run GC. Defaults to dry-run (plan only)."""
        with self._lock:
            self._interrupt_requested = False
            if plan is None:
                plan = self.plan(
                    dry_run=dry_run,
                    tenant=tenant,
                    graph_id=graph_id,
                    extra_roots=extra_roots,
                )
            else:
                # Honour caller's dry_run flag over plan.dry_run when executing.
                plan = GCPlan(
                    plan_id=plan.plan_id,
                    created_at=plan.created_at,
                    dry_run=bool(dry_run),
                    roots=plan.roots,
                    reachable_cids=plan.reachable_cids,
                    candidates=plan.candidates,
                    protected_cids=plan.protected_cids,
                    notes=list(plan.notes),
                )

            if plan.dry_run:
                return GCResult(
                    plan_id=plan.plan_id,
                    dry_run=True,
                    phase=GCPhase.COMPLETED.value,
                    deleted=[],
                    skipped=[c.cid for c in plan.candidates],
                    protected=list(plan.protected_cids),
                    candidates=list(plan.candidates),
                    roots=list(plan.roots),
                    bytes_freed=0,
                    notes=list(plan.notes) + ["dry_run: no objects deleted"],
                )

            return self._execute_plan(plan)

    def _execute_plan(self, plan: GCPlan) -> GCResult:
        # Fresh execute/recover paths clear cooperative interrupt unless the
        # caller re-requests it during this run.
        self._interrupt_requested = False
        pending = [c.cid for c in plan.candidates]
        state = GCJournalState(
            schema_version=GC_JOURNAL_SCHEMA,
            plan_id=plan.plan_id,
            phase=GCPhase.RUNNING.value,
            dry_run=False,
            plan=plan.to_dict(),
            deleted=[],
            pending=list(pending),
            updated_at=time.time(),
        )
        self.journal.write(state)

        deleted: List[str] = []
        skipped: List[str] = []
        bytes_freed = 0
        # Re-validate reachability before each delete.
        live_roots = self.collect_roots()
        reachable = compute_reachable_set(
            live_roots,
            inventory=self.store.list_objects(),
            expand=self.expand_links,
        )
        lease_ids = active_lease_ids(live_roots)

        error: Optional[str] = None
        try:
            for cand in plan.candidates:
                if self._interrupt_requested:
                    state.phase = GCPhase.INTERRUPTED.value
                    state.deleted = list(deleted)
                    state.pending = [c for c in pending if c not in deleted]
                    state.updated_at = time.time()
                    self.journal.write(state)
                    return GCResult(
                        plan_id=plan.plan_id,
                        dry_run=False,
                        phase=GCPhase.INTERRUPTED.value,
                        deleted=deleted,
                        skipped=skipped + state.pending,
                        protected=list(plan.protected_cids),
                        candidates=list(plan.candidates),
                        roots=list(plan.roots),
                        bytes_freed=bytes_freed,
                        notes=list(plan.notes) + ["interrupted by request"],
                    )

                cid = cand.cid
                # Safety re-check: never delete a now-reachable or lease-protected object.
                if cid in reachable:
                    skipped.append(cid)
                    continue
                meta = self.store.cache.get_meta(cid)
                if meta is not None:
                    if meta.pin_count > 0 and meta.lifecycle == ObjectLifecycle.COMMITTED.value:
                        skipped.append(cid)
                        continue
                    if meta.lease_id and meta.lease_id in lease_ids:
                        skipped.append(cid)
                        continue
                    if (
                        meta.lifecycle not in COLLECTIBLE_LIFECYCLES
                        and meta.lifecycle != ObjectLifecycle.ABANDONED.value
                    ):
                        skipped.append(cid)
                        continue

                try:
                    size = meta.size if meta is not None else cand.size
                    ok = self.store.delete_object(cid, force=True)
                    if ok or meta is None:
                        deleted.append(cid)
                        bytes_freed += int(size or 0)
                        state.deleted = list(deleted)
                        state.pending = [c for c in pending if c not in deleted and c not in skipped]
                        state.updated_at = time.time()
                        self.journal.write(state)
                        if self._after_delete_hook is not None:
                            self._after_delete_hook(cid, state)
                    else:
                        skipped.append(cid)
                except GraphStoreError as err:
                    skipped.append(cid)
                    notes_err = f"delete_failed:{cid}:{err.code}"
                    plan.notes.append(notes_err)
        except Exception as exc:
            # Crash / unexpected — journal remains RUNNING or we mark interrupted.
            error = f"{type(exc).__name__}: {exc}"
            state.phase = GCPhase.INTERRUPTED.value
            state.deleted = list(deleted)
            state.pending = [c for c in pending if c not in deleted and c not in skipped]
            state.error = error
            state.updated_at = time.time()
            self.journal.write(state)
            return GCResult(
                plan_id=plan.plan_id,
                dry_run=False,
                phase=GCPhase.INTERRUPTED.value,
                deleted=deleted,
                skipped=skipped + state.pending,
                protected=list(plan.protected_cids),
                candidates=list(plan.candidates),
                roots=list(plan.roots),
                bytes_freed=bytes_freed,
                error=error,
                notes=list(plan.notes) + ["interrupted by exception"],
            )

        state.phase = GCPhase.COMPLETED.value
        state.deleted = list(deleted)
        state.pending = []
        state.updated_at = time.time()
        self.journal.write(state)

        return GCResult(
            plan_id=plan.plan_id,
            dry_run=False,
            phase=GCPhase.COMPLETED.value,
            deleted=deleted,
            skipped=skipped,
            protected=list(plan.protected_cids),
            candidates=list(plan.candidates),
            roots=list(plan.roots),
            bytes_freed=bytes_freed,
            notes=list(plan.notes),
        )

    def request_interrupt(self) -> None:
        """Cooperative interrupt for long-running execute."""
        self._interrupt_requested = True

    def recover(self, *, resume: bool = True) -> GCResult:
        """Recover from an interrupted GC journal.

        When ``resume`` is True and the journal is ``running``/``interrupted``,
        re-validates candidates against current reachability and finishes
        remaining deletes. When the journal is already completed, returns that
        outcome without further mutation.
        """
        with self._lock:
            self._interrupt_requested = False
            state = self.journal.read()
            if state is None:
                return GCResult(
                    plan_id="",
                    dry_run=True,
                    phase=GCPhase.ABORTED.value,
                    deleted=[],
                    skipped=[],
                    protected=[],
                    candidates=[],
                    roots=[],
                    notes=["no journal to recover"],
                )

            plan = GCPlan.from_dict(state.plan) if state.plan else None
            if plan is None:
                self.journal.clear()
                return GCResult(
                    plan_id=state.plan_id,
                    dry_run=state.dry_run,
                    phase=GCPhase.ABORTED.value,
                    deleted=list(state.deleted),
                    skipped=list(state.pending),
                    protected=[],
                    candidates=[],
                    roots=[],
                    recovered_from_journal=True,
                    notes=["corrupt journal plan; aborted"],
                )

            if state.phase == GCPhase.COMPLETED.value:
                return GCResult(
                    plan_id=state.plan_id,
                    dry_run=state.dry_run,
                    phase=GCPhase.COMPLETED.value,
                    deleted=list(state.deleted),
                    skipped=[],
                    protected=list(plan.protected_cids),
                    candidates=list(plan.candidates),
                    roots=list(plan.roots),
                    recovered_from_journal=True,
                    notes=["journal already completed"],
                )

            if state.dry_run or plan.dry_run:
                self.journal.clear()
                return GCResult(
                    plan_id=state.plan_id,
                    dry_run=True,
                    phase=GCPhase.COMPLETED.value,
                    deleted=[],
                    skipped=[c.cid for c in plan.candidates],
                    protected=list(plan.protected_cids),
                    candidates=list(plan.candidates),
                    roots=list(plan.roots),
                    recovered_from_journal=True,
                    notes=["dry-run journal cleared"],
                )

            if not resume:
                state.phase = GCPhase.ABORTED.value
                state.updated_at = time.time()
                self.journal.write(state)
                return GCResult(
                    plan_id=state.plan_id,
                    dry_run=False,
                    phase=GCPhase.ABORTED.value,
                    deleted=list(state.deleted),
                    skipped=list(state.pending),
                    protected=list(plan.protected_cids),
                    candidates=list(plan.candidates),
                    roots=list(plan.roots),
                    recovered_from_journal=True,
                    notes=["recovery aborted by caller"],
                )

            # Rebuild a residual plan for remaining pending CIDs, re-checking safety.
            already = set(state.deleted)
            remaining_candidates = [
                c for c in plan.candidates if c.cid not in already and c.cid in set(state.pending)
            ]
            # If pending empty but phase interrupted mid-write, use candidates not deleted.
            if not remaining_candidates and state.pending:
                remaining_candidates = [
                    GCCandidate(cid=c, reason="abandoned_staged") for c in state.pending
                ]
            residual = GCPlan(
                plan_id=plan.plan_id,
                created_at=plan.created_at,
                dry_run=False,
                roots=plan.roots,
                reachable_cids=plan.reachable_cids,
                candidates=remaining_candidates,
                protected_cids=plan.protected_cids,
                notes=list(plan.notes) + ["resumed_from_journal"],
            )
            result = self._execute_plan(residual)
            # Merge previously deleted.
            merged_deleted = list(dict.fromkeys(list(state.deleted) + list(result.deleted)))
            return GCResult(
                plan_id=result.plan_id,
                dry_run=False,
                phase=result.phase,
                deleted=merged_deleted,
                skipped=result.skipped,
                protected=result.protected,
                candidates=list(plan.candidates),
                roots=list(plan.roots),
                bytes_freed=result.bytes_freed,
                error=result.error,
                recovered_from_journal=True,
                notes=list(result.notes) + [f"prior_deleted={len(state.deleted)}"],
            )


def create_garbage_collector(
    store: HybridGraphStore,
    *,
    catalog: Any = None,
    journal_path: Optional[Union[str, Path]] = None,
) -> GarbageCollector:
    return GarbageCollector(store, catalog=catalog, journal_path=journal_path)


__all__ = [
    "RootKind",
    "ReachableRoot",
    "GCCandidate",
    "GCPhase",
    "GCPlan",
    "GCResult",
    "GCJournalState",
    "GCJournal",
    "PinPolicy",
    "GarbageCollector",
    "collect_catalog_roots",
    "collect_hybrid_roots",
    "compute_reachable_set",
    "active_lease_ids",
    "create_garbage_collector",
    "DEFAULT_ROOT_KINDS",
]
