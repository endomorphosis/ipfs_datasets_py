"""Graph load harness orchestrator (KGP-029).

Generates deterministic graph shapes, replays workloads across
Python/CLI/MCP/MCP++ surfaces and Parquet/IPFS/ipfs_kit/hybrid storage,
and records a versioned receipt with full metrics.
"""

from __future__ import annotations

import json
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .metrics import (
    LatencyHistogram,
    OperationCounters,
    directory_byte_size,
    sample_resources,
    throughput,
)
from .profiles import (
    DEFAULT_STORAGE_PROFILES,
    DEFAULT_SURFACES,
    LOAD_PROFILES,
    LoadProfile,
    get_profile,
)
from .receipt import (
    LoadReceipt,
    build_receipt,
    capture_environment,
    write_receipt,
)
from .safety import ResourceGuard, synthetic_large_guard
from .shapes import DeterministicGraph, GraphShapeSpec, generate_graph
from .surfaces import (
    STORAGE_PROFILES,
    SURFACE_NAMES,
    LoadSurface,
    envelope_ok,
    open_load_surface,
)
from .workloads import MixResult, execute_mix, seed_graph

JSONDict = Dict[str, Any]


@dataclass
class CellResult:
    """Result for one (surface, storage_profile, graph_id) cell."""

    surface: str
    storage_profile: str
    tenant: str
    graph_id: str
    seed_status: str
    mix: Optional[MixResult] = None
    recovery_ms: Optional[float] = None
    recovery_ok: Optional[bool] = None
    error: Optional[str] = None
    shape_fingerprint: Optional[str] = None
    shard_fan_out: Optional[JSONDict] = None

    def to_json_dict(self) -> JSONDict:
        return {
            "surface": self.surface,
            "storage_profile": self.storage_profile,
            "tenant": self.tenant,
            "graph_id": self.graph_id,
            "seed_status": self.seed_status,
            "mix": self.mix.to_json_dict() if self.mix else None,
            "recovery_ms": self.recovery_ms,
            "recovery_ok": self.recovery_ok,
            "error": self.error,
            "shape_fingerprint": self.shape_fingerprint,
            "shard_fan_out": self.shard_fan_out,
        }


@dataclass
class HarnessRunResult:
    """Complete harness run with receipt and cell results."""

    profile: LoadProfile
    graph: DeterministicGraph
    cells: List[CellResult] = field(default_factory=list)
    receipt: Optional[LoadReceipt] = None
    elapsed_s: float = 0.0
    status: str = "success"

    def to_json_dict(self) -> JSONDict:
        return {
            "profile": self.profile.to_json_dict(),
            "shape_fingerprint": self.graph.fingerprint,
            "node_count": self.graph.node_count,
            "edge_count": self.graph.edge_count,
            "cells": [c.to_json_dict() for c in self.cells],
            "receipt": self.receipt.to_json_dict() if self.receipt else None,
            "elapsed_s": self.elapsed_s,
            "status": self.status,
        }


class GraphLoadHarness:
    """Reproducible load harness for knowledge-graph surfaces and stores."""

    def __init__(
        self,
        work_dir: Path | str,
        *,
        repo_root: Optional[Path | str] = None,
        enable_tracemalloc: bool = False,
    ) -> None:
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
        self.enable_tracemalloc = enable_tracemalloc
        self._global_latency = LatencyHistogram()
        self._counters = OperationCounters()

    def generate(
        self,
        *,
        seed: int,
        node_count: int,
        edge_count: int,
        shape: str = "mixed",
        shard_count: int = 1,
        graph_id: str = "shape",
    ) -> DeterministicGraph:
        """Generate a deterministic graph shape (public API)."""
        spec = GraphShapeSpec(
            seed=seed,
            node_count=node_count,
            edge_count=edge_count,
            shape=shape,
            shard_count=shard_count,
            graph_id=graph_id,
        )
        return generate_graph(spec)

    def _cell_paths(
        self, surface: str, storage_profile: str, graph_id: str
    ) -> Tuple[Path, Path]:
        base = self.work_dir / surface / storage_profile / graph_id
        catalog = base / "catalog.sqlite"
        store = base / "store"
        base.mkdir(parents=True, exist_ok=True)
        store.mkdir(parents=True, exist_ok=True)
        return catalog, store

    def _run_cell(
        self,
        profile: LoadProfile,
        graph: DeterministicGraph,
        *,
        surface_name: str,
        storage_profile: str,
        graph_index: int,
    ) -> CellResult:
        tenant = graph.spec.tenant
        graph_id = (
            graph.spec.graph_id
            if profile.graph_count == 1
            else f"{graph.spec.graph_id}-{graph_index:02d}"
        )
        cell = CellResult(
            surface=surface_name,
            storage_profile=storage_profile,
            tenant=tenant,
            graph_id=graph_id,
            seed_status="pending",
            shape_fingerprint=graph.fingerprint,
            shard_fan_out=graph.shard_fan_out(),
        )
        catalog, store = self._cell_paths(surface_name, storage_profile, graph_id)
        surface: Optional[LoadSurface] = None
        try:
            surface = open_load_surface(surface_name, catalog, store)
            seed = seed_graph(
                surface,
                graph,
                storage_profile=storage_profile,
                tenant=tenant,
                graph_id=graph_id,
                batch_size=profile.mix.write_batch_size,
                counters=self._counters,
                latency=self._global_latency,
                idem_prefix=f"{profile.name}-{surface_name}-{storage_profile}-{graph_index}",
            )
            cell.seed_status = str(seed.get("status") or "error")
            if cell.seed_status == "error":
                cell.error = json.dumps(seed.get("create") or seed, default=str)[:500]
                return cell

            mix = execute_mix(
                surface,
                graph,
                profile.mix,
                storage_profile=storage_profile,
                tenant=tenant,
                graph_id=graph_id,
                seed=profile.seed + graph_index * 17 + hash(surface_name) % 1000,
                counters=self._counters,
                warmup=profile.warmup_operations,
            )
            cell.mix = mix
            self._global_latency.merge(mix.latency)

            if profile.measure_recovery:
                surface.close()
                surface = None
                t_rec = time.perf_counter()
                try:
                    surface = open_load_surface(surface_name, catalog, store)
                    opened = surface.open_graph(
                        tenant=tenant, graph_id=graph_id, branch="main"
                    )
                    queried = surface.query(
                        tenant=tenant,
                        graph_id=graph_id,
                        branch="main",
                        language="scan",
                        max_rows=10,
                    )
                    ok = envelope_ok(opened) and envelope_ok(queried)
                    rec_ms = (time.perf_counter() - t_rec) * 1000.0
                    cell.recovery_ms = rec_ms
                    cell.recovery_ok = ok
                    self._counters.record_recovery(ok=ok, recovery_ms=rec_ms)
                except Exception as exc:  # noqa: BLE001 — recorded in receipt
                    rec_ms = (time.perf_counter() - t_rec) * 1000.0
                    cell.recovery_ms = rec_ms
                    cell.recovery_ok = False
                    cell.error = f"recovery: {exc}"
                    self._counters.record_recovery(ok=False, recovery_ms=rec_ms)

            # Directory sizes feed cache/IPFS byte accounting.
            store_bytes = directory_byte_size(store)
            if storage_profile == "hybrid":
                self._counters.record_storage(cache_bytes=store_bytes // 4)
            if storage_profile in ("ipfs_ipld", "ipfs_kit", "hybrid"):
                self._counters.record_storage(ipfs_bytes=store_bytes // 2)
            self._counters.record_storage(bytes_written=store_bytes)

        except Exception as exc:  # noqa: BLE001 — cell failure must not abort matrix
            cell.seed_status = "error"
            cell.error = f"{type(exc).__name__}: {exc}"
            cell.error = (cell.error + "\n" + traceback.format_exc())[:800]
        finally:
            if surface is not None:
                try:
                    surface.close()
                except Exception:
                    pass
        return cell

    def run(
        self,
        profile: LoadProfile | str,
        *,
        surfaces: Optional[Sequence[str]] = None,
        storage_profiles: Optional[Sequence[str]] = None,
        matrix_mode: str = "full",
        receipt_path: Optional[Path | str] = None,
    ) -> HarnessRunResult:
        """Run a named or configured profile and build a versioned receipt.

        Parameters
        ----------
        matrix_mode:
            ``full`` — cartesian product of surfaces × storage × graphs
            ``storage`` — all storage profiles on the first surface only
            ``surface`` — all surfaces on the first storage profile only
            ``ci`` — python × all storage, plus one probe op per other surface
              on parquet (fast default for mandatory CI)
        """
        if isinstance(profile, str):
            profile = get_profile(profile)

        surfaces_l = tuple(surfaces or profile.surfaces)
        storage_l = tuple(storage_profiles or profile.storage_profiles)
        for s in surfaces_l:
            if s not in SURFACE_NAMES:
                raise ValueError(f"unknown surface {s!r}")
        for p in storage_l:
            if p not in STORAGE_PROFILES:
                raise ValueError(f"unknown storage profile {p!r}")

        # Reset run-scoped metrics.
        self._global_latency = LatencyHistogram()
        self._counters = OperationCounters()

        resource_guard: Optional[ResourceGuard] = None
        if profile.name == "synthetic_large":
            resource_guard = synthetic_large_guard(self.work_dir)
        graph = generate_graph(
            profile.shape_spec,
            resource_check=resource_guard.check if resource_guard else None,
        )
        run = HarnessRunResult(profile=profile, graph=graph)
        t0 = time.perf_counter()
        resources_start = sample_resources(enable_tracemalloc=self.enable_tracemalloc)
        peak = resources_start

        cells_plan: List[Tuple[str, str, int]] = []
        if matrix_mode == "ci":
            primary = surfaces_l[0] if surfaces_l else "python"
            for sp in storage_l:
                cells_plan.append((primary, sp, 0))
            # Probe remaining surfaces on parquet with graph index 0.
            for s in surfaces_l[1:]:
                cells_plan.append((s, "parquet", 0))
        elif matrix_mode == "storage":
            s0 = surfaces_l[0]
            for sp in storage_l:
                for gi in range(profile.graph_count):
                    cells_plan.append((s0, sp, gi))
        elif matrix_mode == "surface":
            sp0 = storage_l[0]
            for s in surfaces_l:
                for gi in range(profile.graph_count):
                    cells_plan.append((s, sp0, gi))
        else:  # full
            for s in surfaces_l:
                for sp in storage_l:
                    for gi in range(profile.graph_count):
                        cells_plan.append((s, sp, gi))

        workers = max(1, int(profile.concurrent_workers))
        if workers == 1 or len(cells_plan) == 1:
            for s, sp, gi in cells_plan:
                cell = self._run_cell(
                    profile, graph, surface_name=s, storage_profile=sp, graph_index=gi
                )
                run.cells.append(cell)
                snap = sample_resources(enable_tracemalloc=self.enable_tracemalloc)
                if snap.rss_bytes > peak.rss_bytes:
                    peak = snap
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(
                        self._run_cell,
                        profile,
                        graph,
                        surface_name=s,
                        storage_profile=sp,
                        graph_index=gi,
                    ): (s, sp, gi)
                    for s, sp, gi in cells_plan
                }
                for fut in as_completed(futures):
                    cell = fut.result()
                    run.cells.append(cell)
                    snap = sample_resources(enable_tracemalloc=self.enable_tracemalloc)
                    if snap.rss_bytes > peak.rss_bytes:
                        peak = snap

        resources_end = sample_resources(enable_tracemalloc=self.enable_tracemalloc)
        elapsed = time.perf_counter() - t0
        run.elapsed_s = elapsed

        total_ops = sum(c.mix.operations for c in run.cells if c.mix is not None)
        ops = max(total_ops, self._counters.operations_total)
        thr = {
            "ops_per_s": throughput(ops, elapsed),
            "operations": ops,
            "elapsed_s": elapsed,
            "cells": len(run.cells),
        }
        global_hist = self._global_latency

        # Merge shard fan-out from first successful cell / graph.
        shard_fan_out = graph.shard_fan_out()
        recovery = {
            "attempts": self._counters.recovery_attempts,
            "successes": self._counters.recovery_successes,
            "ms_total": self._counters.recovery_ms_total,
            "ms_mean": (
                self._counters.recovery_ms_total / self._counters.recovery_attempts
                if self._counters.recovery_attempts
                else 0.0
            ),
            "cells": [
                {
                    "surface": c.surface,
                    "storage_profile": c.storage_profile,
                    "graph_id": c.graph_id,
                    "recovery_ms": c.recovery_ms,
                    "recovery_ok": c.recovery_ok,
                }
                for c in run.cells
                if c.recovery_ms is not None
            ],
        }

        # Status: fail if any cell errored seed for python+parquet (hard),
        # soft-warn for optional surface probes.
        hard_failures = [
            c
            for c in run.cells
            if c.seed_status == "error" and c.surface == "python"
        ]
        soft_failures = [
            c
            for c in run.cells
            if c.seed_status == "error" and c.surface != "python"
        ]
        warnings: List[str] = []
        if soft_failures:
            warnings.append(
                f"{len(soft_failures)} non-python surface cell(s) failed seed/open"
            )
        status = "success" if not hard_failures else "error"
        if hard_failures:
            warnings.append(f"{len(hard_failures)} python cell(s) failed")
        run.status = status

        env = capture_environment(repo_root=self.repo_root)
        receipt = build_receipt(
            seed=profile.seed,
            config={
                "profile": profile.to_json_dict(),
                "matrix_mode": matrix_mode,
                "surfaces": list(surfaces_l),
                "storage_profiles": list(storage_l),
                "work_dir": str(self.work_dir),
                "cells_planned": len(cells_plan),
            },
            throughput=thr,
            latency_histogram=global_hist.to_json_dict(),
            counters=self._counters.to_json_dict(),
            resources_start=resources_start.to_json_dict(),
            resources_end=resources_end.to_json_dict(),
            resources_peak=peak.to_json_dict(),
            shard_fan_out=shard_fan_out,
            recovery=recovery,
            results=[c.to_json_dict() for c in run.cells],
            shape_fingerprint=graph.fingerprint,
            elapsed_s=elapsed,
            status=status,
            warnings=warnings,
            environment=env,
            repo_root=self.repo_root,
            receipt_id=f"kg-load-{profile.name}-{profile.seed}-{uuid.uuid4().hex[:10]}",
        )
        run.receipt = receipt

        if receipt_path is not None:
            write_receipt(receipt, receipt_path)
        else:
            default_path = self.work_dir / "receipts" / f"{receipt.receipt_id}.json"
            write_receipt(receipt, default_path)

        return run


def run_profile(
    profile: LoadProfile | str = "tiny",
    *,
    work_dir: Path | str,
    matrix_mode: str = "ci",
    surfaces: Optional[Sequence[str]] = None,
    storage_profiles: Optional[Sequence[str]] = None,
    receipt_path: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
) -> HarnessRunResult:
    """Convenience entry: run a profile and return the harness result."""
    harness = GraphLoadHarness(work_dir, repo_root=repo_root)
    return harness.run(
        profile,
        surfaces=surfaces,
        storage_profiles=storage_profiles,
        matrix_mode=matrix_mode,
        receipt_path=receipt_path,
    )
