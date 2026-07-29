"""Liveness and readiness probes for knowledge-graph control plane (KGP-032)."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Union

from .logging import log_ops_event
from .redact import OPERATIONS_CONTRACT_VERSION, scrub_for_telemetry
from .telemetry import OpsTelemetry, get_default_telemetry

PathLike = Union[str, Path]

HEALTH_SCHEMA_VERSION = "kg-ops-health/v1"


@dataclass
class ProbeResult:
    name: str
    status: str  # pass | fail | warn
    detail: str = ""
    latency_ms: float = 0.0
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "latency_ms": self.latency_ms,
            "data": scrub_for_telemetry(self.data),
        }


@dataclass
class HealthReport:
    """Aggregated liveness / readiness report."""

    alive: bool
    ready: bool
    status: str  # healthy | degraded | not_ready | dead
    checked_at: float
    probes: List[ProbeResult] = field(default_factory=list)
    schema_version: str = HEALTH_SCHEMA_VERSION
    contract_version: str = OPERATIONS_CONTRACT_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "contract_version": self.contract_version,
            "alive": self.alive,
            "ready": self.ready,
            "status": self.status,
            "checked_at": self.checked_at,
            "probes": [p.to_dict() for p in self.probes],
        }


ProbeFn = Callable[[], ProbeResult]


class HealthRegistry:
    """Registry of named readiness probes with process liveness tracking."""

    def __init__(
        self,
        *,
        telemetry: Optional[OpsTelemetry] = None,
        process_started_at: Optional[float] = None,
    ) -> None:
        self._lock = threading.RLock()
        self._probes: Dict[str, ProbeFn] = {}
        self._telemetry = telemetry or get_default_telemetry()
        self._started_at = process_started_at if process_started_at is not None else time.time()
        self._shutting_down = False

    def register(self, name: str, probe: ProbeFn) -> None:
        with self._lock:
            self._probes[name] = probe

    def unregister(self, name: str) -> None:
        with self._lock:
            self._probes.pop(name, None)

    def mark_shutdown(self) -> None:
        self._shutting_down = True

    def liveness(self) -> HealthReport:
        """Liveness: process is running and not marked for shutdown."""
        now = time.time()
        if self._shutting_down:
            probe = ProbeResult(
                name="process",
                status="fail",
                detail="shutdown_in_progress",
                data={"uptime_s": now - self._started_at},
            )
            report = HealthReport(
                alive=False,
                ready=False,
                status="dead",
                checked_at=now,
                probes=[probe],
            )
        else:
            probe = ProbeResult(
                name="process",
                status="pass",
                detail="running",
                data={
                    "uptime_s": now - self._started_at,
                    "pid": os.getpid(),
                },
            )
            report = HealthReport(
                alive=True,
                ready=True,  # liveness alone does not gate readiness semantics
                status="healthy",
                checked_at=now,
                probes=[probe],
            )
        self._telemetry.metrics.set_gauge(
            "kg_ops_liveness", 1.0 if report.alive else 0.0
        )
        log_ops_event(
            "health.liveness",
            status="ok" if report.alive else "fail",
            alive=report.alive,
        )
        return report

    def readiness(self) -> HealthReport:
        """Readiness: all registered probes must pass (warn allowed)."""
        now = time.time()
        results: List[ProbeResult] = []
        with self._lock:
            probes = list(self._probes.items())

        if self._shutting_down:
            results.append(
                ProbeResult(
                    name="process",
                    status="fail",
                    detail="shutdown_in_progress",
                )
            )
        else:
            results.append(
                ProbeResult(
                    name="process",
                    status="pass",
                    detail="running",
                    data={"uptime_s": now - self._started_at},
                )
            )

        for name, fn in probes:
            started = time.perf_counter()
            try:
                result = fn()
                if not isinstance(result, ProbeResult):
                    result = ProbeResult(
                        name=name,
                        status="fail",
                        detail="probe_returned_invalid_type",
                    )
                else:
                    # Ensure name is stable even if probe forgot it.
                    if not result.name:
                        result = ProbeResult(
                            name=name,
                            status=result.status,
                            detail=result.detail,
                            latency_ms=result.latency_ms,
                            data=result.data,
                        )
            except Exception as exc:  # fail-closed
                result = ProbeResult(
                    name=name,
                    status="fail",
                    detail=f"probe_error:{type(exc).__name__}",
                    data={"error_type": type(exc).__name__},
                )
            if result.latency_ms <= 0:
                result.latency_ms = (time.perf_counter() - started) * 1000.0
            results.append(result)

        failed = [p for p in results if p.status == "fail"]
        warned = [p for p in results if p.status == "warn"]
        alive = not self._shutting_down
        ready = alive and not failed
        if not alive:
            status = "dead"
        elif failed:
            status = "not_ready"
        elif warned:
            status = "degraded"
        else:
            status = "healthy"

        report = HealthReport(
            alive=alive,
            ready=ready,
            status=status,
            checked_at=now,
            probes=results,
        )
        self._telemetry.metrics.set_gauge(
            "kg_ops_readiness", 1.0 if report.ready else 0.0
        )
        self._telemetry.metrics.set_gauge(
            "kg_ops_health_probe_failures", float(len(failed))
        )
        log_ops_event(
            "health.readiness",
            status="ok" if report.ready else "fail",
            ready=report.ready,
            health_status=status,
            probe_count=len(results),
            fail_count=len(failed),
        )
        return report


def catalog_probe(catalog: Any, *, name: str = "catalog") -> ProbeFn:
    """Build a readiness probe that opens a simple catalog read."""

    def _probe() -> ProbeResult:
        started = time.perf_counter()
        try:
            # Prefer list-style API; fall back to path existence.
            if hasattr(catalog, "list_graphs") and hasattr(catalog, "path"):
                # list requires tenant — just exercise a pragma / describe path
                path = Path(getattr(catalog, "path"))
                if not path.exists():
                    return ProbeResult(
                        name=name,
                        status="fail",
                        detail="catalog_path_missing",
                        latency_ms=(time.perf_counter() - started) * 1000.0,
                        data={"path": str(path)},
                    )
            if hasattr(catalog, "_conn") or hasattr(catalog, "path"):
                # Touch describe of empty tenant listing via internal sqlite if present
                if hasattr(catalog, "list_tombstones"):
                    catalog.list_tombstones(limit=1) if _accepts_limit(
                        catalog.list_tombstones
                    ) else None
            # Generic "is open" check
            closed = bool(getattr(catalog, "closed", False))
            if closed:
                return ProbeResult(
                    name=name,
                    status="fail",
                    detail="catalog_closed",
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                )
            return ProbeResult(
                name=name,
                status="pass",
                detail="catalog_reachable",
                latency_ms=(time.perf_counter() - started) * 1000.0,
            )
        except Exception as exc:
            return ProbeResult(
                name=name,
                status="fail",
                detail=f"catalog_error:{type(exc).__name__}",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                data={"error_type": type(exc).__name__},
            )

    return _probe


def _accepts_limit(fn: Callable[..., Any]) -> bool:
    try:
        import inspect

        sig = inspect.signature(fn)
        return "limit" in sig.parameters
    except Exception:
        return False


def catalog_path_probe(path: PathLike, *, name: str = "catalog_path") -> ProbeFn:
    """Readiness probe for a catalog filesystem path."""

    catalog_path = Path(path)

    def _probe() -> ProbeResult:
        started = time.perf_counter()
        if not catalog_path.exists():
            return ProbeResult(
                name=name,
                status="fail",
                detail="path_missing",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                data={"path": str(catalog_path)},
            )
        if not catalog_path.is_file() and not catalog_path.is_dir():
            return ProbeResult(
                name=name,
                status="fail",
                detail="path_not_file_or_dir",
                latency_ms=(time.perf_counter() - started) * 1000.0,
            )
        # SQLite catalog files must be readable.
        try:
            with open(catalog_path, "rb") as fh:
                fh.read(16)
        except IsADirectoryError:
            pass
        except OSError as exc:
            return ProbeResult(
                name=name,
                status="fail",
                detail=f"path_unreadable:{type(exc).__name__}",
                latency_ms=(time.perf_counter() - started) * 1000.0,
            )
        return ProbeResult(
            name=name,
            status="pass",
            detail="path_ok",
            latency_ms=(time.perf_counter() - started) * 1000.0,
            data={"path": str(catalog_path), "size": catalog_path.stat().st_size
            if catalog_path.is_file()
            else None},
        )

    return _probe


def hybrid_cache_probe(store: Any, *, name: str = "hybrid_cache") -> ProbeFn:
    """Readiness probe for a HybridGraphStore / VerifiedHybridCache."""

    def _probe() -> ProbeResult:
        started = time.perf_counter()
        try:
            if hasattr(store, "stats"):
                stats = store.stats()
                return ProbeResult(
                    name=name,
                    status="pass",
                    detail="cache_ok",
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    data={"stats_keys": sorted(stats.keys())[:32]},
                )
            if hasattr(store, "list_objects"):
                _ = list(store.list_objects())[:1]
                return ProbeResult(
                    name=name,
                    status="pass",
                    detail="inventory_ok",
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                )
            return ProbeResult(
                name=name,
                status="warn",
                detail="no_stats_api",
                latency_ms=(time.perf_counter() - started) * 1000.0,
            )
        except Exception as exc:
            return ProbeResult(
                name=name,
                status="fail",
                detail=f"cache_error:{type(exc).__name__}",
                latency_ms=(time.perf_counter() - started) * 1000.0,
            )

    return _probe


def build_default_health(
    *,
    catalog: Any = None,
    catalog_path: Optional[PathLike] = None,
    hybrid_store: Any = None,
    telemetry: Optional[OpsTelemetry] = None,
) -> HealthRegistry:
    """Wire common probes for a GraphService deployment."""
    registry = HealthRegistry(telemetry=telemetry)
    if catalog is not None:
        registry.register("catalog", catalog_probe(catalog))
    if catalog_path is not None:
        registry.register("catalog_path", catalog_path_probe(catalog_path))
    if hybrid_store is not None:
        registry.register("hybrid_cache", hybrid_cache_probe(hybrid_store))
    return registry


__all__ = [
    "HEALTH_SCHEMA_VERSION",
    "HealthRegistry",
    "HealthReport",
    "ProbeResult",
    "build_default_health",
    "catalog_path_probe",
    "catalog_probe",
    "hybrid_cache_probe",
]
