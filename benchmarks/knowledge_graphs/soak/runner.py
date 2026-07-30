"""Mixed soak runner with resource sampling and growth gates (KGP-031).

Runs a multi-graph write/read/compaction loop for a configured duration,
samples RSS/FD/cache/WAL/lease metrics, and emits a versioned soak receipt.
Destructive chaos is left to ``tests/chaos``; this runner proves longevity
and resource bounds on isolated temporary stores.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from benchmarks.knowledge_graphs.metrics import (
    LatencyHistogram,
    OperationCounters,
    sample_resources,
)
from benchmarks.knowledge_graphs.soak.growth import GrowthReport, analyze_growth
from benchmarks.knowledge_graphs.soak.profiles import (
    SoakProfile,
    get_soak_profile,
    resolve_duration_override,
    short_profiles_required,
)
from ipfs_datasets_py.knowledge_graphs.transactions import (
    DurableMVCC,
    InMemoryBranchStore,
    WriteAheadLog,
)

# Lightweight content-addressed JSON storage (mirrors concurrency helpers).
import hashlib as _hashlib


class _InMemoryJsonStorage:
    def __init__(self) -> None:
        self._store: Dict[str, bytes] = {}

    def store_json(self, data: dict) -> str:
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        cid = "bafy" + _hashlib.sha256(payload).hexdigest()[:32]
        self._store[cid] = payload
        return cid

    def retrieve_json(self, cid: str) -> dict:
        payload = self._store.get(cid)
        if payload is None:
            raise KeyError(cid)
        return json.loads(payload.decode("utf-8"))

JSONDict = Dict[str, Any]

SOAK_RECEIPT_SCHEMA = "ipfs-datasets.knowledge-graphs.soak-receipt.v1"
SOAK_RECEIPT_SCHEMA_VERSION = 1


@dataclass
class SoakTickResult:
    tick: int
    writes: int
    reads: int
    compactions: int
    errors: int
    data_errors: int
    security_errors: int


@dataclass
class SoakRunResult:
    profile: SoakProfile
    elapsed_s: float
    ticks: int
    operations: int
    samples: List[JSONDict]
    growth: GrowthReport
    latency: LatencyHistogram
    counters: OperationCounters
    receipt: JSONDict
    status: str
    work_dir: Optional[str] = None

    def to_json_dict(self) -> JSONDict:
        return {
            "profile": self.profile.to_json_dict(),
            "elapsed_s": self.elapsed_s,
            "ticks": self.ticks,
            "operations": self.operations,
            "samples": list(self.samples),
            "growth": self.growth.to_json_dict(),
            "latency": self.latency.to_json_dict(),
            "counters": self.counters.to_json_dict(),
            "receipt": self.receipt,
            "status": self.status,
            "work_dir": self.work_dir,
        }


def _graph_ids(n: int) -> List[str]:
    return [f"soak-g{i:02d}" for i in range(n)]


def _lease_count(store: InMemoryBranchStore) -> int:
    return len(getattr(store, "_leases", {}) or {})


def _live_cache_bytes(store: InMemoryBranchStore) -> int:
    """
    Live working-set footprint for leak detection.

    Heads and active leases must stay O(graph_count). Excludes durable
    growth that is expected under intentional writes:

    * revision history
    * published staged roots (kept as revision payloads after COMPLETE)
    * idempotency map (one entry per unique key)
    * content-addressed object / WAL store
    """
    total = 0
    for attr in ("_heads", "_leases"):
        mapping = getattr(store, attr, None) or {}
        try:
            # Keys may be tuples on InMemoryBranchStore; stringify safely.
            total += len(json.dumps(mapping, default=str).encode("utf-8"))
        except Exception:
            total += len(mapping) * 64
    return total


def _sample(
    *,
    mvcc: DurableMVCC,
    storage: _InMemoryJsonStorage,
) -> JSONDict:
    snap = sample_resources()
    d = snap.to_json_dict()
    d["cache_bytes"] = _live_cache_bytes(mvcc.store)  # type: ignore[arg-type]
    d["wal_entries"] = int(getattr(mvcc.wal, "_entry_count", 0) or 0)
    d["lease_count"] = _lease_count(mvcc.store)  # type: ignore[arg-type]
    # Diagnostics (not growth-gated as leak signals — intentional durability).
    d["object_store_bytes"] = sum(
        len(p) for p in getattr(storage, "_store", {}).values()
    )
    d["revision_count"] = len(getattr(mvcc.store, "_revisions", {}) or {})
    d["staged_root_count"] = len(getattr(mvcc.store, "_staged_roots", {}) or {})
    return d


def run_soak(
    profile: SoakProfile | str,
    *,
    work_dir: Optional[Path | str] = None,
    require_short_first: bool = True,
    short_already_passed: bool = False,
) -> SoakRunResult:
    """
    Execute a soak profile on an isolated in-memory durable MVCC.

    Parameters
    ----------
    require_short_first:
        When True and the profile is opt-in (medium/day), require that short
        profiles are acknowledged via ``short_already_passed`` or by running
        them first.
    """
    if isinstance(profile, str):
        profile = get_soak_profile(profile)
    profile = resolve_duration_override(profile)

    if profile.opt_in and require_short_first and not short_already_passed:
        # Auto-run mandatory short profiles first.
        for sp in short_profiles_required():
            pre = run_soak(sp, work_dir=work_dir, require_short_first=False)
            if pre.status != "success" or not pre.growth.ok:
                raise RuntimeError(
                    f"short soak profile {sp.name!r} failed before {profile.name!r}: "
                    f"status={pre.status} growth={pre.growth.summary}"
                )
        short_already_passed = True

    root = Path(work_dir) if work_dir else None
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)

    storage = _InMemoryJsonStorage()
    store = InMemoryBranchStore()
    wal = WriteAheadLog(storage)
    wal.compaction_threshold = 10_000
    mvcc = DurableMVCC(wal, branch_store=store, holder_id="soak-runner")

    gids = _graph_ids(profile.graph_count)
    tenant = "tenant-soak"
    for gid in gids:
        mvcc.open_snapshot(tenant, gid)

    latency = LatencyHistogram()
    counters = OperationCounters()
    samples: List[JSONDict] = []
    data_errors = 0
    security_errors = 0
    operations = 0
    ticks = 0
    rng_state = profile.seed

    def _rand() -> float:
        nonlocal rng_state
        # Minimal LCG for deterministic mix choices.
        rng_state = (1_103_515_245 * rng_state + 12_345) & 0x7FFFFFFF
        return rng_state / 0x7FFFFFFF

    samples.append(_sample(mvcc=mvcc, storage=storage))
    t_start = time.time()
    t_end = t_start + float(profile.duration_s)
    next_sample = t_start + float(profile.sample_interval_s)

    while time.time() < t_end:
        ticks += 1
        for op_i in range(profile.ops_per_tick):
            gid = gids[int(_rand() * len(gids)) % len(gids)]
            do_write = _rand() < profile.write_weight
            t0 = time.perf_counter()
            try:
                if do_write:
                    txn = mvcc.begin(tenant, gid, acquire_lease=True)
                    mvcc.stage_mutations(
                        txn,
                        entities=[
                            {
                                "id": f"e-{ticks}-{op_i}-{int(_rand()*1e6)}",
                                "tick": ticks,
                            }
                        ],
                    )
                    mvcc.commit(txn)
                    counters.record_op(ok=True)
                else:
                    snap = mvcc.open_snapshot(tenant, gid)
                    if not snap.revision_id:
                        data_errors += 1
                        counters.record_op(ok=False)
                    else:
                        counters.record_op(ok=True)
                operations += 1
            except Exception as exc:
                counters.record_op(ok=False)
                msg = str(exc).lower()
                if any(
                    k in msg
                    for k in ("unauthorized", "forbidden", "ucan", "tenant", "leak")
                ):
                    security_errors += 1
                else:
                    # Lease contention under mixed load is not a data error.
                    if "lease" in msg or "conflict" in msg:
                        pass
                    else:
                        data_errors += 1
            finally:
                latency.observe((time.perf_counter() - t0) * 1000.0)

        if profile.compact_every_ticks > 0 and ticks % profile.compact_every_ticks == 0:
            head = mvcc.wal.wal_head_cid
            if head:
                try:
                    mvcc.wal.compact(head)
                    if not mvcc.wal.verify_integrity():
                        data_errors += 1
                except Exception:
                    data_errors += 1

        now = time.time()
        if now >= next_sample:
            samples.append(_sample(mvcc=mvcc, storage=storage))
            next_sample = now + float(profile.sample_interval_s)

    # Final sample + recovery probe.
    samples.append(_sample(mvcc=mvcc, storage=storage))
    try:
        t_rec = time.perf_counter()
        mvcc.recover()
        counters.record_recovery(
            ok=True, recovery_ms=(time.perf_counter() - t_rec) * 1000.0
        )
        # Heads must remain addressable.
        for gid in gids:
            head = store.get_head(tenant, gid, "main")
            if not head:
                data_errors += 1
    except Exception:
        counters.record_recovery(ok=False, recovery_ms=0.0)
        data_errors += 1

    elapsed = time.time() - t_start
    growth = analyze_growth(
        samples, data_errors=data_errors, security_errors=security_errors
    )
    status = "success" if growth.ok else "failed"
    receipt = build_soak_receipt(
        profile=profile,
        elapsed_s=elapsed,
        ticks=ticks,
        operations=operations,
        samples=samples,
        growth=growth,
        latency=latency,
        counters=counters,
        status=status,
    )
    if root is not None:
        path = root / f"soak-{profile.name}-{receipt['receipt_id'][:12]}.json"
        path.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")

    return SoakRunResult(
        profile=profile,
        elapsed_s=elapsed,
        ticks=ticks,
        operations=operations,
        samples=samples,
        growth=growth,
        latency=latency,
        counters=counters,
        receipt=receipt,
        status=status,
        work_dir=str(root) if root else None,
    )


def build_soak_receipt(
    *,
    profile: SoakProfile,
    elapsed_s: float,
    ticks: int,
    operations: int,
    samples: Sequence[Mapping[str, Any]],
    growth: GrowthReport,
    latency: LatencyHistogram,
    counters: OperationCounters,
    status: str,
) -> JSONDict:
    body: JSONDict = {
        "schema": SOAK_RECEIPT_SCHEMA,
        "schema_version": SOAK_RECEIPT_SCHEMA_VERSION,
        "receipt_id": uuid.uuid4().hex,
        "created_at": time.time(),
        "profile": profile.to_json_dict(),
        "elapsed_s": float(elapsed_s),
        "ticks": int(ticks),
        "operations": int(operations),
        "ops_per_s": (operations / elapsed_s) if elapsed_s > 0 else 0.0,
        "latency_histogram": latency.to_json_dict(),
        "counters": counters.to_json_dict(),
        "samples": list(samples),
        "growth": growth.to_json_dict(),
        "status": status,
        "environment": {
            "pid": os.getpid(),
            "platform": os.name,
        },
    }
    # Content digest over stable fields (exclude receipt_id/created_at).
    digest_src = {
        k: body[k]
        for k in (
            "schema",
            "schema_version",
            "profile",
            "elapsed_s",
            "ticks",
            "operations",
            "growth",
            "status",
        )
    }
    payload = json.dumps(digest_src, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    body["digest"] = hashlib.sha256(payload).hexdigest()
    return body


def write_soak_receipt(receipt: Mapping[str, Any], path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(receipt), indent=2, sort_keys=True), encoding="utf-8")
    return path
