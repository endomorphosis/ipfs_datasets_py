"""
Shared fixtures for multi-thread / multi-process MVCC concurrency (KGP-008).

Provides:
- Content-addressed JSON storage (in-memory and filesystem)
- A file-backed branch store with exclusive locks for process-safe CAS/leases
- Subprocess helpers that do not share process caches
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ipfs_datasets_py.knowledge_graphs.exceptions import DeserializationError
from ipfs_datasets_py.knowledge_graphs.transactions import (
    DurableMVCC,
    HeadCASResult,
    IdempotencyConflictError,
    InMemoryBranchStore,
    LeaseFence,
    LeaseFencedError,
    SnapshotRevision,
    WriteAheadLog,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
HELPERS_DIR = Path(__file__).resolve().parent

NUM_GRAPHS = 16
TENANTS = ("tenant-alpha", "tenant-beta")
BRANCH = "main"
GENESIS = "rev-genesis"


class InMemoryJsonStorage:
    """Minimal store_json / retrieve_json backend for single-process tests."""

    def __init__(self) -> None:
        self._store: Dict[str, bytes] = {}

    def store_json(self, data: dict) -> str:
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        cid = "bafy" + hashlib.sha256(payload).hexdigest()[:32]
        self._store[cid] = payload
        return cid

    def retrieve_json(self, cid: str) -> dict:
        payload = self._store.get(cid)
        if payload is None:
            raise DeserializationError(f"CID not found: {cid}", details={"cid": cid})
        return json.loads(payload.decode("utf-8"))


class FileJsonStorage:
    """
    Process-safe content-addressed JSON storage under a directory.

    Each object is written atomically (temp + fsync + rename). Concurrent
    writers of the same content produce the same CID and may race harmlessly.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._head_path = self.root / "wal_head.txt"

    def store_json(self, data: dict) -> str:
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        cid = "bafy" + hashlib.sha256(payload).hexdigest()[:32]
        target = self.root / f"{cid}.json"
        if target.exists():
            return cid
        tmp = self.root / f"{cid}.{uuid.uuid4().hex}.tmp"
        try:
            with open(tmp, "wb") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            tmp.replace(target)
        except OSError:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
            if not target.exists():
                raise
        return cid

    def retrieve_json(self, cid: str) -> dict:
        target = self.root / f"{cid}.json"
        if not target.exists():
            raise DeserializationError(f"CID not found: {cid}", details={"cid": cid})
        with open(target, "rb") as fh:
            return json.loads(fh.read().decode("utf-8"))

    def write_wal_head(self, cid: str) -> None:
        tmp = self.root / f".wal_head.{uuid.uuid4().hex}.tmp"
        data = (cid or "").encode("utf-8")
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(self._head_path)

    def read_wal_head(self) -> Optional[str]:
        if not self._head_path.exists():
            return None
        raw = self._head_path.read_text(encoding="utf-8").strip()
        return raw or None


def _checksum(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class FileBranchStore:
    """
    Process-safe branch head / lease / revision store backed by a single JSON
    document under exclusive flock for mutations.

    Implements the same contracts as :class:`InMemoryBranchStore` so
    :class:`DurableMVCC` can be shared across processes via a directory path.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._atomic_write(
                {
                    "heads": {},
                    "revisions": {},
                    "leases": {},
                    "idempotency": {},
                    "staged_roots": {},
                }
            )

    def _atomic_write(self, state: dict) -> None:
        tmp = self.path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        payload = json.dumps(state, sort_keys=True).encode("utf-8")
        with open(tmp, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(self.path)

    def _load(self) -> dict:
        with open(self.path, "rb") as fh:
            return json.loads(fh.read().decode("utf-8"))

    def _with_lock(self, mutator):
        lock_path = self.path.with_suffix(".lock")
        lock_path.touch(exist_ok=True)
        with open(lock_path, "a+") as lock_fh:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
            try:
                state = self._load()
                result = mutator(state)
                self._atomic_write(state)
                return result
            finally:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _hk(tenant: str, graph_id: str, branch: str) -> str:
        return f"{tenant}/{graph_id}/{branch}"

    @staticmethod
    def _rk(tenant: str, graph_id: str, revision_id: str) -> str:
        return f"{tenant}/{graph_id}/{revision_id}"

    def ensure_branch(
        self,
        tenant: str,
        graph_id: str,
        branch: str,
        *,
        initial_revision: str = GENESIS,
    ) -> SnapshotRevision:
        def _mut(state: dict):
            key = self._hk(tenant, graph_id, branch)
            if key not in state["heads"]:
                snap = SnapshotRevision(
                    tenant=tenant,
                    graph_id=graph_id,
                    revision_id=initial_revision,
                    parent_revision=None,
                    root_cid=None,
                    checksum=_checksum(b"{}"),
                    created_at=time.time(),
                )
                state["heads"][key] = initial_revision
                state["revisions"][self._rk(tenant, graph_id, initial_revision)] = (
                    snap.to_dict()
                )
                return snap
            rev_id = state["heads"][key]
            return SnapshotRevision.from_dict(
                state["revisions"][self._rk(tenant, graph_id, rev_id)]
            )

        return self._with_lock(_mut)

    def get_head(self, tenant: str, graph_id: str, branch: str) -> str:
        state = self._load()
        key = self._hk(tenant, graph_id, branch)
        if key not in state["heads"]:
            raise KeyError(f"unknown branch {tenant}/{graph_id}/{branch}")
        return state["heads"][key]

    def get_revision(
        self, tenant: str, graph_id: str, revision_id: str
    ) -> SnapshotRevision:
        state = self._load()
        rk = self._rk(tenant, graph_id, revision_id)
        if rk not in state["revisions"]:
            raise KeyError(f"unknown revision {tenant}/{graph_id}/{revision_id}")
        return SnapshotRevision.from_dict(state["revisions"][rk])

    def put_revision(self, snap: SnapshotRevision) -> None:
        def _mut(state: dict):
            state["revisions"][
                self._rk(snap.tenant, snap.graph_id, snap.revision_id)
            ] = snap.to_dict()

        self._with_lock(_mut)

    def put_staged_root(self, root_cid: str, payload: Dict[str, Any]) -> None:
        def _mut(state: dict):
            state["staged_roots"][root_cid] = payload

        self._with_lock(_mut)

    def discard_staged_root(self, root_cid: Optional[str]) -> bool:
        if not root_cid:
            return False

        def _mut(state: dict):
            return state["staged_roots"].pop(root_cid, None) is not None

        return bool(self._with_lock(_mut))

    def has_staged_root(self, root_cid: str) -> bool:
        state = self._load()
        return root_cid in state["staged_roots"]

    def cas_set_head(
        self,
        tenant: str,
        graph_id: str,
        branch: str,
        *,
        expected_revision: str,
        new_revision: str,
        lease_id: Optional[str] = None,
        lease_epoch: Optional[int] = None,
        now: Optional[float] = None,
    ) -> HeadCASResult:
        now_ts = time.time() if now is None else now

        def _mut(state: dict):
            if lease_id is not None or lease_epoch is not None:
                self._check_lease_state(
                    state,
                    tenant,
                    graph_id,
                    branch,
                    lease_id=lease_id,
                    lease_epoch=lease_epoch,
                    now=now_ts,
                )
            key = self._hk(tenant, graph_id, branch)
            current = state["heads"].get(key)
            if current is None:
                raise KeyError(f"unknown branch {tenant}/{graph_id}/{branch}")
            if current != expected_revision:
                return HeadCASResult(
                    success=False,
                    tenant=tenant,
                    graph_id=graph_id,
                    branch=branch,
                    expected_revision=expected_revision,
                    new_revision=new_revision,
                    current_revision=current,
                    conflict=True,
                )
            state["heads"][key] = new_revision
            return HeadCASResult(
                success=True,
                tenant=tenant,
                graph_id=graph_id,
                branch=branch,
                expected_revision=expected_revision,
                new_revision=new_revision,
                current_revision=new_revision,
                conflict=False,
            )

        return self._with_lock(_mut)

    def acquire_lease(
        self,
        tenant: str,
        graph_id: str,
        branch: str,
        *,
        holder: str,
        ttl_seconds: float = 300.0,
        now: Optional[float] = None,
    ) -> LeaseFence:
        now_ts = time.time() if now is None else now

        def _mut(state: dict):
            key = self._hk(tenant, graph_id, branch)
            existing_raw = state["leases"].get(key)
            existing = (
                LeaseFence.from_dict(existing_raw) if existing_raw is not None else None
            )
            if existing is not None and not existing.is_expired(now_ts):
                if existing.holder == holder:
                    renewed = LeaseFence(
                        tenant=tenant,
                        graph_id=graph_id,
                        branch=branch,
                        lease_id=existing.lease_id,
                        holder=holder,
                        epoch=existing.epoch,
                        expires_at=now_ts + float(ttl_seconds),
                        created_at=existing.created_at,
                    )
                    state["leases"][key] = renewed.to_dict()
                    return renewed
                raise LeaseFencedError(
                    "writer lease held by another holder",
                    details={
                        "tenant": tenant,
                        "graph_id": graph_id,
                        "branch": branch,
                        "holder": holder,
                        "current_holder": existing.holder,
                        "epoch": existing.epoch,
                    },
                )
            epoch = (existing.epoch + 1) if existing is not None else 1
            lease = LeaseFence(
                tenant=tenant,
                graph_id=graph_id,
                branch=branch,
                lease_id=f"lease-{uuid.uuid4().hex[:12]}",
                holder=holder,
                epoch=epoch,
                expires_at=now_ts + float(ttl_seconds),
                created_at=now_ts,
            )
            state["leases"][key] = lease.to_dict()
            return lease

        return self._with_lock(_mut)

    @staticmethod
    def _check_lease_state(
        state: dict,
        tenant: str,
        graph_id: str,
        branch: str,
        *,
        lease_id: Optional[str],
        lease_epoch: Optional[int],
        now: float,
    ) -> None:
        if lease_id is None and lease_epoch is None:
            return
        if lease_id is None or lease_epoch is None:
            raise LeaseFencedError(
                "lease_id and lease_epoch must be provided together",
                details={"lease_id": lease_id, "lease_epoch": lease_epoch},
            )
        key = FileBranchStore._hk(tenant, graph_id, branch)
        raw = state["leases"].get(key)
        if raw is None:
            raise LeaseFencedError(
                "no active writer lease for branch",
                details={
                    "tenant": tenant,
                    "graph_id": graph_id,
                    "branch": branch,
                    "lease_id": lease_id,
                    "lease_epoch": lease_epoch,
                },
            )
        current = LeaseFence.from_dict(raw)
        if current.is_expired(now):
            raise LeaseFencedError(
                "writer lease expired",
                details={
                    "tenant": tenant,
                    "graph_id": graph_id,
                    "branch": branch,
                    "lease_id": lease_id,
                    "lease_epoch": lease_epoch,
                    "expires_at": current.expires_at,
                },
            )
        if current.lease_id != lease_id or int(current.epoch) != int(lease_epoch):
            raise LeaseFencedError(
                "writer lease epoch is stale",
                details={
                    "tenant": tenant,
                    "graph_id": graph_id,
                    "branch": branch,
                    "lease_id": lease_id,
                    "lease_epoch": lease_epoch,
                    "current_lease_id": current.lease_id,
                    "current_epoch": current.epoch,
                },
            )

    def check_idempotency(
        self, key: str, request_hash: str
    ) -> Optional[Dict[str, Any]]:
        def _mut(state: dict):
            prior = state["idempotency"].get(key)
            if prior is None:
                return None
            prior_hash, response = prior
            if prior_hash != request_hash:
                raise IdempotencyConflictError(
                    "idempotency key reused with different request",
                    details={"key": key},
                )
            return dict(response)

        return self._with_lock(_mut)

    def record_idempotency(
        self, key: str, request_hash: str, response: Dict[str, Any]
    ) -> None:
        def _mut(state: dict):
            state["idempotency"][key] = (request_hash, dict(response))

        self._with_lock(_mut)


def make_mvcc(
    *,
    holder_id: Optional[str] = None,
    branch_store: Optional[InMemoryBranchStore] = None,
    storage=None,
    wal_head_cid: Optional[str] = None,
) -> DurableMVCC:
    """Single-process DurableMVCC with in-memory storage and branch store."""
    store = branch_store if branch_store is not None else InMemoryBranchStore()
    if storage is None:
        storage = InMemoryJsonStorage()
    wal = WriteAheadLog(storage, wal_head_cid=wal_head_cid)
    return DurableMVCC(wal, branch_store=store, holder_id=holder_id)


def make_file_mvcc(root: Path | str, *, holder_id: Optional[str] = None) -> DurableMVCC:
    """Process-safe DurableMVCC sharing branch store + WAL objects under root."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    storage = FileJsonStorage(root / "wal_objects")
    head = storage.read_wal_head()
    wal = WriteAheadLog(storage, wal_head_cid=head)

    # Rebuild idempotency map and entry count from durable chain.
    if head:
        try:
            cursor = head
            visited: set = set()
            while cursor and cursor not in visited:
                visited.add(cursor)
                entry_dict = storage.retrieve_json(cursor)
                from ipfs_datasets_py.knowledge_graphs.transactions import WALEntry

                entry = WALEntry.from_dict(entry_dict)
                key = wal._replay_key(entry)
                if key is not None and key not in wal._applied_keys:
                    wal._applied_keys[key] = cursor
                cursor = entry.prev_wal_cid
            wal._entry_count = len(visited)
        except Exception:
            pass

    wal_lock_path = root / "wal_objects" / "wal_append.lock"
    wal_lock_path.parent.mkdir(parents=True, exist_ok=True)
    wal_lock_path.touch(exist_ok=True)
    _orig_append = wal.append

    def _append_and_persist(entry):
        with open(wal_lock_path, "a+") as lock_fh:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
            try:
                # Sync in-memory head + idempotency from disk before append.
                disk_head = storage.read_wal_head()
                wal.wal_head_cid = disk_head
                if disk_head:
                    try:
                        from ipfs_datasets_py.knowledge_graphs.transactions import (
                            WALEntry,
                        )

                        cursor = disk_head
                        seen: set = set()
                        while cursor and cursor not in seen:
                            seen.add(cursor)
                            ed = storage.retrieve_json(cursor)
                            ent = WALEntry.from_dict(ed)
                            rk = wal._replay_key(ent)
                            if rk is not None and rk not in wal._applied_keys:
                                wal._applied_keys[rk] = cursor
                            cursor = ent.prev_wal_cid
                    except Exception:
                        pass
                cid = _orig_append(entry)
                storage.write_wal_head(wal.wal_head_cid)
                return cid
            finally:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)

    wal.append = _append_and_persist  # type: ignore[method-assign]
    branch_store = FileBranchStore(root / "branch_store.json")
    return DurableMVCC(wal, branch_store=branch_store, holder_id=holder_id)


def graph_ids(n: int = NUM_GRAPHS) -> List[str]:
    return [f"graph-{i:02d}" for i in range(n)]


def tenant_graph_pairs(
    n_graphs: int = NUM_GRAPHS,
    tenants: Tuple[str, ...] = TENANTS,
) -> List[Tuple[str, str]]:
    """Round-robin (tenant, graph_id) pairs covering all graphs and tenants."""
    gids = graph_ids(n_graphs)
    pairs: List[Tuple[str, str]] = []
    for i, gid in enumerate(gids):
        pairs.append((tenants[i % len(tenants)], gid))
    return pairs


def child_env() -> Dict[str, str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    prefix = f"{HELPERS_DIR}{os.pathsep}{REPO_ROOT}"
    env["PYTHONPATH"] = prefix if not existing else f"{prefix}{os.pathsep}{existing}"
    return env


def run_child(script: str, *args: str, timeout: float = 90.0):
    """Run a child Python process (true process boundary; no shared caches)."""
    return subprocess.run(
        [sys.executable, "-c", script, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=child_env(),
        cwd=str(REPO_ROOT),
    )


CHILD_COMMIT = """
import json, sys
from pathlib import Path
from helpers import make_file_mvcc
from ipfs_datasets_py.knowledge_graphs.transactions import ConflictError, LeaseFencedError

root = Path(sys.argv[1])
tenant, graph_id, entity_id, holder = sys.argv[2:6]
idem = sys.argv[6] if len(sys.argv) > 6 and sys.argv[6] != "-" else None

mvcc = make_file_mvcc(root, holder_id=holder)
try:
    txn = mvcc.begin(tenant, graph_id, acquire_lease=True, idempotency_key=idem)
    mvcc.stage_mutations(txn, entities=[{"id": entity_id, "type": "Node", "holder": holder}])
    result = mvcc.commit(txn)
    print(json.dumps({"ok": True, "revision": result["revision"], "txn_id": txn.txn_id,
                      "tenant": tenant, "graph_id": graph_id}))
except (ConflictError, LeaseFencedError) as exc:
    print(json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc),
                      "tenant": tenant, "graph_id": graph_id}))
"""

CHILD_READ_HEAD = """
import json, sys
from pathlib import Path
from helpers import make_file_mvcc

root = Path(sys.argv[1])
tenant, graph_id = sys.argv[2], sys.argv[3]
mvcc = make_file_mvcc(root, holder_id="reader-child")
snap = mvcc.open_snapshot(tenant, graph_id)
print(json.dumps({
    "revision": snap.revision_id,
    "tenant": snap.tenant,
    "graph_id": snap.graph_id,
}))
"""

CHILD_STOP_AT_PHASE = """
import json, sys
from pathlib import Path
from helpers import make_file_mvcc

root = Path(sys.argv[1])
tenant, graph_id, entity_id, holder, stop = sys.argv[2:7]
idem = sys.argv[7] if len(sys.argv) > 7 and sys.argv[7] != "-" else None

mvcc = make_file_mvcc(root, holder_id=holder)
txn = mvcc.begin(tenant, graph_id, acquire_lease=True, idempotency_key=idem)
base = txn.base_revision
if stop == "INTENT":
    print(json.dumps({
        "ok": True, "stopped": "INTENT", "txn_id": txn.txn_id,
        "base_revision": base, "head": mvcc.store.get_head(tenant, graph_id, "main"),
        "staged_root": txn.staged_root_cid,
    }))
    raise SystemExit(0)
mvcc.stage_mutations(txn, entities=[{"id": entity_id, "type": "Node"}])
if stop == "PREPARE":
    delta = mvcc.prepare(txn)
    print(json.dumps({
        "ok": True, "stopped": "PREPARE", "txn_id": txn.txn_id,
        "base_revision": base, "head": mvcc.store.get_head(tenant, graph_id, "main"),
        "staged_root": delta.staged_root_cid, "staged_revision": delta.staged_revision_id,
    }))
    raise SystemExit(0)
mvcc.prepare(txn)
if stop == "PUBLISH":
    cas = mvcc.publish(txn)
    print(json.dumps({
        "ok": True, "stopped": "PUBLISH", "txn_id": txn.txn_id,
        "base_revision": base, "head": mvcc.store.get_head(tenant, graph_id, "main"),
        "staged_root": txn.staged_root_cid, "staged_revision": txn.staged_revision_id,
        "cas_success": cas.success,
    }))
    raise SystemExit(0)
mvcc.publish(txn)
result = mvcc.complete(txn)
print(json.dumps({
    "ok": True, "stopped": "COMPLETE", "txn_id": txn.txn_id,
    "base_revision": base, "head": mvcc.store.get_head(tenant, graph_id, "main"),
    "revision": result["revision"], "staged_root": txn.staged_root_cid,
}))
"""

CHILD_RECOVER = """
import json, sys
from pathlib import Path
from helpers import make_file_mvcc

root = Path(sys.argv[1])
# optional: tenant graph_id pairs as JSON list
pairs = json.loads(sys.argv[2]) if len(sys.argv) > 2 else []
mvcc = make_file_mvcc(root, holder_id="recovery-child")
decisions = mvcc.recover()
heads = {}
for tenant, graph_id in pairs:
    try:
        heads[f"{tenant}/{graph_id}"] = mvcc.store.get_head(tenant, graph_id, "main")
    except KeyError:
        heads[f"{tenant}/{graph_id}"] = None
print(json.dumps({
    "decisions": [d.to_dict() for d in decisions],
    "heads": heads,
    "wal_head": mvcc.wal.wal_head_cid,
}))
"""
