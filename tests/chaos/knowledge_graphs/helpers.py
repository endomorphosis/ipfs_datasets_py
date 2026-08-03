"""Isolated fault-injection helpers for knowledge-graph chaos tests (KGP-031).

All helpers use temporary stores and disposable namespaces so fault scenarios
never touch shared production data or live IPFS daemons.
"""

from __future__ import annotations

import errno
import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from ipfs_datasets_py.knowledge_graphs.exceptions import DeserializationError
from ipfs_datasets_py.knowledge_graphs.storage.ipld_store import InMemoryBlockBackend
from ipfs_datasets_py.knowledge_graphs.storage.sharding.models import GraphFragment
from ipfs_datasets_py.knowledge_graphs.storage.sharding.publish import (
    publish_sharded_graph_v2,
)
from ipfs_datasets_py.knowledge_graphs.transactions import (
    DurableMVCC,
    InMemoryBranchStore,
    WriteAheadLog,
)

from tests.integration.knowledge_graphs.concurrency.helpers import (
    make_file_mvcc,
    make_mvcc,
)

# Re-export for chaos modules.
__all__ = [
    "DiskFullJsonStorage",
    "OutageBlockBackend",
    "LimitedCapacityBlockBackend",
    "make_sample_published",
    "make_disk_full_mvcc",
    "make_file_mvcc",
    "make_mvcc",
    "simulate_enospc",
    "make_readonly_root",
    "corrupt_file_bytes",
    "count_leases",
    "wal_entry_count",
]


class DiskFullJsonStorage:
    """Content-addressed JSON store that raises ENOSPC after a byte budget."""

    def __init__(self, max_bytes: int = 256) -> None:
        self.max_bytes = int(max_bytes)
        self._store: Dict[str, bytes] = {}
        self.bytes_written = 0
        self.enospc_hits = 0

    def store_json(self, data: dict) -> str:
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        if self.bytes_written + len(payload) > self.max_bytes:
            self.enospc_hits += 1
            raise OSError(errno.ENOSPC, "No space left on device (chaos inject)")
        cid = "bafy" + __import__("hashlib").sha256(payload).hexdigest()[:32]
        if cid not in self._store:
            self._store[cid] = payload
            self.bytes_written += len(payload)
        return cid

    def retrieve_json(self, cid: str) -> dict:
        payload = self._store.get(cid)
        if payload is None:
            raise DeserializationError(f"CID not found: {cid}", details={"cid": cid})
        return json.loads(payload.decode("utf-8"))


class LimitedCapacityBlockBackend(InMemoryBlockBackend):
    """Block backend that fails puts with ENOSPC after capacity is reached."""

    def __init__(self, max_puts: int = 2, root_dir: Optional[Path] = None) -> None:
        super().__init__(root_dir=root_dir)
        self.max_puts = int(max_puts)
        self.put_count = 0
        self.enospc_hits = 0

    def put_block(self, data: bytes, *, codec: str) -> str:
        if self.put_count >= self.max_puts:
            self.enospc_hits += 1
            raise OSError(errno.ENOSPC, "No space left on device (chaos inject)")
        cid = super().put_block(data, codec=codec)
        self.put_count += 1
        return cid


class OutageBlockBackend(InMemoryBlockBackend):
    """Toggleable IPFS outage double: raises ConnectionError while offline."""

    def __init__(self, root_dir: Optional[Path] = None) -> None:
        super().__init__(root_dir=root_dir)
        self.online = True
        self.outage_hits = 0
        self._lock = threading.RLock()

    def set_online(self, online: bool) -> None:
        with self._lock:
            self.online = bool(online)

    def _require_online(self, op: str) -> None:
        with self._lock:
            if not self.online:
                self.outage_hits += 1
                raise ConnectionError(f"IPFS daemon unavailable during {op} (chaos outage)")

    def put_block(self, data: bytes, *, codec: str) -> str:
        self._require_online("put")
        return super().put_block(data, codec=codec)

    def get_block(self, cid: str) -> bytes:
        self._require_online("get")
        return super().get_block(cid)

    def pin(self, cid: str) -> None:
        self._require_online("pin")
        return super().pin(cid)

    def unpin(self, cid: str) -> None:
        self._require_online("unpin")
        return super().unpin(cid)


def simulate_enospc() -> OSError:
    return OSError(errno.ENOSPC, "No space left on device")


def make_disk_full_mvcc(*, max_bytes: int = 400, holder_id: str = "diskfull") -> DurableMVCC:
    storage = DiskFullJsonStorage(max_bytes=max_bytes)
    store = InMemoryBranchStore()
    wal = WriteAheadLog(storage)
    return DurableMVCC(wal, branch_store=store, holder_id=holder_id)


def make_readonly_root(writable: Path) -> Path:
    """
    Mark *writable* and its contents read-only (best-effort).

    Returns the same path. Callers should restore permissions in finally
    blocks if they need further cleanup on some filesystems.
    """
    root = Path(writable)
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        for name in filenames:
            p = Path(dirpath) / name
            try:
                os.chmod(p, 0o444)
            except OSError:
                pass
        try:
            os.chmod(dirpath, 0o555)
        except OSError:
            pass
    try:
        os.chmod(root, 0o555)
    except OSError:
        pass
    return root


def restore_writable(root: Path) -> None:
    """Best-effort restore write permissions after a read-only experiment."""
    root = Path(root)
    try:
        os.chmod(root, 0o755)
    except OSError:
        pass
    for dirpath, dirnames, filenames in os.walk(root):
        try:
            os.chmod(dirpath, 0o755)
        except OSError:
            pass
        for name in filenames:
            try:
                os.chmod(Path(dirpath) / name, 0o644)
            except OSError:
                pass


def corrupt_file_bytes(path: Path) -> None:
    """Flip bytes in an on-disk object without renaming the file."""
    path = Path(path)
    original = path.read_bytes()
    if not original:
        path.write_bytes(b"\xffCORRUPT")
        return
    flipped = bytes((b ^ 0xFF) for b in original[: min(32, len(original))]) + original[32:]
    path.write_bytes(flipped)


def make_sample_published(n_entities: int = 24, shards: int = 4, seed: str = "kgp-031"):
    """Publish a small ring graph for missing/slow/corrupt shard scenarios."""
    g = GraphFragment(name="chaos-sample")
    for i in range(n_entities):
        g.add_entity(
            entity_id=f"e{i:04d}",
            entity_type="Person" if i % 2 == 0 else "Org",
            name=f"Entity-{i}",
            properties={"idx": i},
        )
    for i in range(n_entities):
        j = (i + 1) % n_entities
        g.add_relationship(
            relationship_id=f"r{i:04d}",
            relationship_type="KNOWS",
            source_id=f"e{i:04d}",
            target_id=f"e{j:04d}",
            properties={"hop": i},
        )
    return publish_sharded_graph_v2(
        g,
        num_physical_shards=shards,
        virtual_shard_count=max(16, shards * 8),
        seed=seed,
        index_bucket_target_size=8,
        force_bucket_prefix_len=1,
    )


def count_leases(store: Any) -> int:
    """Count live leases on an in-memory or file branch store."""
    if hasattr(store, "_leases"):
        return len(getattr(store, "_leases") or {})
    if hasattr(store, "path"):
        state = json.loads(Path(store.path).read_text(encoding="utf-8"))
        return len(state.get("leases") or {})
    return 0


def wal_entry_count(mvcc: DurableMVCC) -> int:
    return int(getattr(mvcc.wal, "_entry_count", 0) or 0)
