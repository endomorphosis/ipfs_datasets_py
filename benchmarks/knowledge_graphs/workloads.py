"""Workload mix execution: read / write / query (KGP-029)."""

from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .metrics import LatencyHistogram, OperationCounters
from .profiles import WorkloadMix
from .shapes import DeterministicGraph, batch_entities, batch_relationships
from .surfaces import (
    LoadSurface,
    envelope_conflict,
    envelope_ok,
    estimate_payload_bytes,
)

JSONDict = Dict[str, Any]


@dataclass
class MixResult:
    """Outcome of one mix execution against a single graph/surface/profile."""

    surface: str
    storage_profile: str
    tenant: str
    graph_id: str
    operations: int = 0
    ok: int = 0
    errors: int = 0
    conflicts: int = 0
    write_ops: int = 0
    read_ops: int = 0
    query_ops: int = 0
    elapsed_s: float = 0.0
    latency: LatencyHistogram = field(default_factory=LatencyHistogram)
    last_revision: Optional[str] = None
    error_samples: List[JSONDict] = field(default_factory=list)

    def to_json_dict(self) -> JSONDict:
        return {
            "surface": self.surface,
            "storage_profile": self.storage_profile,
            "tenant": self.tenant,
            "graph_id": self.graph_id,
            "operations": self.operations,
            "ok": self.ok,
            "errors": self.errors,
            "conflicts": self.conflicts,
            "write_ops": self.write_ops,
            "read_ops": self.read_ops,
            "query_ops": self.query_ops,
            "elapsed_s": self.elapsed_s,
            "latency": self.latency.to_json_dict(),
            "last_revision": self.last_revision,
            "error_samples": list(self.error_samples[:10]),
        }


def _pick_op(rng: random.Random, mix: WorkloadMix) -> str:
    n = mix.normalized()
    u = rng.random()
    if u < n.write_weight:
        return "write"
    if u < n.write_weight + n.read_weight:
        return "read"
    return "query"


def _record(
    result: MixResult,
    counters: OperationCounters,
    envelope: Mapping[str, Any],
    *,
    latency_ms: float,
    queue_wait_ms: float = 0.0,
    queue_depth: int = 0,
) -> None:
    ok = envelope_ok(envelope)
    conflict = envelope_conflict(envelope)
    result.operations += 1
    result.latency.observe(latency_ms)
    if ok:
        result.ok += 1
    else:
        result.errors += 1
        if len(result.error_samples) < 10:
            result.error_samples.append(
                {
                    "operation": envelope.get("operation"),
                    "error": envelope.get("error"),
                }
            )
    if conflict:
        result.conflicts += 1
    counters.record_op(
        ok=ok,
        conflict=conflict,
        queue_wait_ms=queue_wait_ms,
        queue_depth=queue_depth,
    )
    rev = None
    res = envelope.get("result")
    if isinstance(res, Mapping):
        rev = res.get("revision") or res.get("head_revision")
    if rev:
        result.last_revision = str(rev)


def seed_graph(
    surface: LoadSurface,
    graph: DeterministicGraph,
    *,
    storage_profile: str,
    tenant: str,
    graph_id: str,
    branch: str = "main",
    batch_size: int = 64,
    counters: Optional[OperationCounters] = None,
    latency: Optional[LatencyHistogram] = None,
    idem_prefix: str = "seed",
) -> JSONDict:
    """Create a graph and write all entities/relationships in batches."""
    ctr = counters or OperationCounters()
    hist = latency or LatencyHistogram()
    t0 = time.perf_counter()
    created = surface.create(
        tenant=tenant,
        graph_id=graph_id,
        branch=branch,
        idempotency_key=f"{idem_prefix}-create-{uuid.uuid4().hex[:8]}",
        storage_profile=storage_profile,
    )
    dt = (time.perf_counter() - t0) * 1000.0
    hist.observe(dt)
    ctr.record_op(ok=envelope_ok(created), conflict=envelope_conflict(created))
    if not envelope_ok(created):
        return {
            "status": "error",
            "create": created,
            "writes": [],
            "elapsed_s": time.perf_counter() - t0,
        }

    # Batch entities and relationships together so edges land with nodes.
    ent_batches = batch_entities(graph.entities, batch_size)
    rel_batches = batch_relationships(graph.relationships, batch_size)
    n_batches = max(len(ent_batches), len(rel_batches), 1)
    writes: List[JSONDict] = []
    last_rev = None
    for i in range(n_batches):
        ents = ent_batches[i] if i < len(ent_batches) else []
        rels = rel_batches[i] if i < len(rel_batches) else []
        if not ents and not rels:
            continue
        nbytes = estimate_payload_bytes(ents, rels)
        tw = time.perf_counter()
        written = surface.write(
            tenant=tenant,
            graph_id=graph_id,
            branch=branch,
            idempotency_key=f"{idem_prefix}-w{i}-{uuid.uuid4().hex[:8]}",
            entities=ents,
            relationships=rels,
        )
        dw = (time.perf_counter() - tw) * 1000.0
        hist.observe(dw)
        ok = envelope_ok(written)
        ctr.record_op(ok=ok, conflict=envelope_conflict(written))
        if ok:
            ctr.record_storage(bytes_written=nbytes, ipfs_puts=1 if storage_profile != "parquet" else 0)
            # Approximate cache/IPFS accounting by profile.
            if storage_profile in ("ipfs_ipld", "ipfs_kit", "hybrid"):
                ctr.record_storage(ipfs_bytes=nbytes, ipfs_puts=1)
            if storage_profile == "hybrid":
                ctr.record_storage(cache_bytes=nbytes, cache_misses=1)
            if storage_profile == "parquet":
                ctr.record_storage(bytes_written=nbytes)
            res = written.get("result") or {}
            if isinstance(res, Mapping) and res.get("revision"):
                last_rev = str(res["revision"])
        writes.append(written)
        if not ok:
            break

    if not graph.entities and not graph.relationships:
        status = "success"
    elif not writes:
        status = "error"
    elif all(envelope_ok(w) for w in writes):
        status = "success"
    elif any(envelope_ok(w) for w in writes):
        status = "partial"
    else:
        status = "error"
    return {
        "status": status,
        "create": created,
        "writes": writes,
        "revision": last_rev,
        "elapsed_s": time.perf_counter() - t0,
        "batches": len(writes),
    }


def execute_mix(
    surface: LoadSurface,
    graph: DeterministicGraph,
    mix: WorkloadMix,
    *,
    storage_profile: str,
    tenant: str,
    graph_id: str,
    branch: str = "main",
    seed: int = 0,
    counters: Optional[OperationCounters] = None,
    warmup: int = 0,
) -> MixResult:
    """Execute a weighted read/write/query mix against an already-seeded graph."""
    rng = random.Random(seed)
    ctr = counters or OperationCounters()
    mix = mix.normalized()
    result = MixResult(
        surface=surface.name,
        storage_profile=storage_profile,
        tenant=tenant,
        graph_id=graph_id,
    )

    ent_list = list(graph.entities)
    rel_list = list(graph.relationships)
    write_cursor = 0

    def do_write() -> JSONDict:
        nonlocal write_cursor
        # Append small deterministic synthetic entities so writes stay idempotent
        # across ops without clobbering seed IDs.
        batch_n = min(mix.write_batch_size, max(1, len(ent_list) // 4 or 1))
        extra_entities = []
        for j in range(batch_n):
            idx = write_cursor + j
            eid = f"w{seed:04d}{idx:06d}"
            extra_entities.append(
                {
                    "id": eid,
                    "type": "Concept",
                    "name": f"write-{idx}",
                    "properties": {"mix_seed": seed, "index": idx},
                }
            )
        write_cursor += batch_n
        # Optional edge between two new entities when we have at least two.
        extra_rels: List[JSONDict] = []
        if len(extra_entities) >= 2:
            extra_rels.append(
                {
                    "id": f"wr{seed:04d}{write_cursor:06d}",
                    "type": "RELATED_TO",
                    "source": extra_entities[0]["id"],
                    "target": extra_entities[1]["id"],
                    "properties": {"mix_seed": seed},
                }
            )
        nbytes = estimate_payload_bytes(extra_entities, extra_rels)
        env = surface.write(
            tenant=tenant,
            graph_id=graph_id,
            branch=branch,
            idempotency_key=f"mix-w-{seed}-{write_cursor}-{uuid.uuid4().hex[:8]}",
            entities=extra_entities,
            relationships=extra_rels,
        )
        if envelope_ok(env):
            if storage_profile in ("ipfs_ipld", "ipfs_kit", "hybrid"):
                ctr.record_storage(ipfs_bytes=nbytes, ipfs_puts=1, bytes_written=nbytes)
            else:
                ctr.record_storage(bytes_written=nbytes)
            if storage_profile == "hybrid":
                ctr.record_storage(cache_bytes=nbytes // 2, cache_hits=1)
        return env

    def do_read() -> JSONDict:
        t0 = time.perf_counter()
        env = surface.open_graph(tenant=tenant, graph_id=graph_id, branch=branch)
        # Treat describe as additional read when open succeeds.
        if envelope_ok(env):
            desc = surface.describe(tenant=tenant, graph_id=graph_id, branch=branch)
            if envelope_ok(desc):
                env = desc
                # Approximate read accounting.
                ctr.record_storage(
                    bytes_read=256,
                    cache_hits=1 if storage_profile == "hybrid" else 0,
                    ipfs_fetches=1 if storage_profile in ("ipfs_ipld", "ipfs_kit") else 0,
                    ipfs_bytes=128 if storage_profile in ("ipfs_ipld", "ipfs_kit", "hybrid") else 0,
                )
        _ = t0
        return env

    def do_query() -> JSONDict:
        env = surface.query(
            tenant=tenant,
            graph_id=graph_id,
            branch=branch,
            language=mix.query_language,
            text="",
            max_rows=mix.query_max_rows,
        )
        if envelope_ok(env):
            rows = 0
            res = env.get("result")
            if isinstance(res, Mapping):
                rows = int(res.get("row_count") or len(res.get("rows") or []))
            ctr.record_storage(
                bytes_read=max(64, rows * 32),
                cache_hits=1 if storage_profile == "hybrid" else 0,
                cache_misses=0 if storage_profile == "hybrid" else 1,
                ipfs_fetches=1 if storage_profile in ("ipfs_ipld", "ipfs_kit", "hybrid") else 0,
                ipfs_bytes=max(64, rows * 16)
                if storage_profile in ("ipfs_ipld", "ipfs_kit", "hybrid")
                else 0,
            )
        return env

    # Warmup (not counted toward mix result latency percentiles for ops,
    # but still executed for cache fill).
    for _ in range(max(0, warmup)):
        do_query()

    t_start = time.perf_counter()
    for i in range(mix.operations):
        op = _pick_op(rng, mix)
        # Simulated queue wait for concurrent-style accounting.
        queue_depth = 0
        queue_wait_ms = 0.0
        t0 = time.perf_counter()
        if op == "write":
            env = do_write()
            result.write_ops += 1
        elif op == "read":
            env = do_read()
            result.read_ops += 1
        else:
            env = do_query()
            result.query_ops += 1
        latency_ms = (time.perf_counter() - t0) * 1000.0
        _record(
            result,
            ctr,
            env,
            latency_ms=latency_ms,
            queue_wait_ms=queue_wait_ms,
            queue_depth=queue_depth,
        )
    result.elapsed_s = time.perf_counter() - t_start
    return result
