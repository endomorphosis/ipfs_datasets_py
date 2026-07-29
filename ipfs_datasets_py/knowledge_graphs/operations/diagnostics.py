"""Catalog / WAL / shard / pin / cache diagnostics (KGP-032).

Produces bounded, redacted diagnostic snapshots suitable for readiness
dashboards and on-call triage. Never embeds raw queries, properties, or tokens.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from .logging import log_ops_event
from .redact import OPERATIONS_CONTRACT_VERSION, scrub_for_telemetry
from .telemetry import OpsTelemetry, get_default_telemetry

PathLike = Union[str, Path]
DIAGNOSTICS_SCHEMA_VERSION = "kg-ops-diagnostics/v1"


@dataclass
class DiagnosticSection:
    name: str
    status: str  # ok | warn | error | unavailable
    summary: str
    metrics: Dict[str, Any] = field(default_factory=dict)
    findings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "summary": self.summary,
            "metrics": scrub_for_telemetry(self.metrics),
            "findings": list(self.findings)[:64],
        }


@dataclass
class DiagnosticsReport:
    generated_at: float
    sections: List[DiagnosticSection] = field(default_factory=list)
    schema_version: str = DIAGNOSTICS_SCHEMA_VERSION
    contract_version: str = OPERATIONS_CONTRACT_VERSION
    overall_status: str = "ok"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "contract_version": self.contract_version,
            "generated_at": self.generated_at,
            "overall_status": self.overall_status,
            "sections": [s.to_dict() for s in self.sections],
        }


def _overall(sections: Sequence[DiagnosticSection]) -> str:
    statuses = {s.status for s in sections}
    if "error" in statuses:
        return "error"
    if "warn" in statuses:
        return "warn"
    if statuses and statuses <= {"unavailable"}:
        return "unavailable"
    return "ok"


def diagnose_catalog(
    catalog: Any,
    *,
    tenant: Optional[str] = None,
    max_graphs: int = 256,
) -> DiagnosticSection:
    """Summarize catalog control-plane health for one or all tenants."""
    findings: List[str] = []
    metrics: Dict[str, Any] = {
        "graph_count": 0,
        "branch_count": 0,
        "revision_count": 0,
        "pin_root_count": 0,
        "active_lease_count": 0,
        "tombstone_count": 0,
        "missing_checksums": 0,
        "missing_pin_roots": 0,
    }
    try:
        tenants: List[str]
        if tenant is not None:
            tenants = [tenant]
        else:
            tenants = _discover_tenants(catalog)

        graphs_seen = 0
        for t in tenants:
            if graphs_seen >= max_graphs:
                findings.append(f"graph_scan_capped_at_{max_graphs}")
                break
            try:
                graphs = catalog.list_graphs(t, include_tombstoned=True)
            except TypeError:
                graphs = catalog.list_graphs(t)
            for g in graphs:
                if graphs_seen >= max_graphs:
                    break
                graphs_seen += 1
                metrics["graph_count"] += 1
                gid = g.graph_id if hasattr(g, "graph_id") else g["graph_id"]
                status = g.status if hasattr(g, "status") else g.get("status")
                if status == "tombstoned":
                    metrics["tombstone_count"] += 1
                try:
                    branches = catalog.list_branches(t, gid, include_tombstoned=True)
                except TypeError:
                    try:
                        branches = catalog.list_branches(t, gid)
                    except Exception:
                        branches = []
                metrics["branch_count"] += len(branches)
                try:
                    revs = catalog.list_revisions(t, gid)
                except Exception:
                    revs = []
                metrics["revision_count"] += len(revs)
                for rev in revs:
                    checksum = (
                        rev.checksum if hasattr(rev, "checksum") else rev.get("checksum")
                    )
                    pin_root = (
                        rev.pin_root if hasattr(rev, "pin_root") else rev.get("pin_root")
                    )
                    if not checksum:
                        metrics["missing_checksums"] += 1
                    if not pin_root:
                        metrics["missing_pin_roots"] += 1
                try:
                    pins = catalog.list_pin_roots(t, gid)
                    metrics["pin_root_count"] += len(pins)
                except Exception:
                    pass
                for br in branches:
                    bname = br.branch if hasattr(br, "branch") else br.get("branch")
                    try:
                        lease = catalog.get_lease(t, gid, bname)
                        if lease is not None:
                            metrics["active_lease_count"] += 1
                    except Exception:
                        pass

        if metrics["missing_checksums"]:
            findings.append(
                f"{metrics['missing_checksums']} revision(s) missing checksum"
            )
        if metrics["missing_pin_roots"]:
            findings.append(
                f"{metrics['missing_pin_roots']} revision(s) missing pin_root"
            )
        status = "warn" if findings else "ok"
        return DiagnosticSection(
            name="catalog",
            status=status,
            summary=(
                f"{metrics['graph_count']} graphs, "
                f"{metrics['revision_count']} revisions, "
                f"{metrics['pin_root_count']} pin roots"
            ),
            metrics=metrics,
            findings=findings,
        )
    except Exception as exc:
        return DiagnosticSection(
            name="catalog",
            status="error",
            summary=f"catalog_diagnostic_failed:{type(exc).__name__}",
            metrics=metrics,
            findings=[f"error:{type(exc).__name__}"],
        )


def _discover_tenants(catalog: Any) -> List[str]:
    """Best-effort tenant discovery (catalog may not expose a list API)."""
    if hasattr(catalog, "list_tenants"):
        try:
            return list(catalog.list_tenants())
        except Exception:
            pass
    # Fall back to scanning sqlite if available.
    conn = getattr(catalog, "_conn", None)
    if conn is None and hasattr(catalog, "path"):
        return []
    try:
        # GraphCatalog uses per-txn connections; try a private helper pattern.
        if hasattr(catalog, "_txn"):
            with catalog._txn(immediate=False) as c:
                rows = c.execute(
                    "SELECT DISTINCT tenant FROM graphs ORDER BY tenant"
                ).fetchall()
                return [r[0] if not hasattr(r, "keys") else r["tenant"] for r in rows]
    except Exception:
        pass
    return []


def diagnose_wal(wal: Any = None, *, wal_path: Optional[PathLike] = None) -> DiagnosticSection:
    """Summarize WAL head / recovery posture."""
    metrics: Dict[str, Any] = {}
    findings: List[str] = []
    if wal is None and wal_path is None:
        return DiagnosticSection(
            name="wal",
            status="unavailable",
            summary="no_wal_configured",
            metrics=metrics,
        )
    try:
        if wal is not None:
            head = getattr(wal, "wal_head_cid", None)
            metrics["wal_head_cid_present"] = bool(head)
            metrics["wal_head_cid_prefix"] = (str(head)[:16] + "…") if head else None
            for attr in (
                "max_operations_per_entry",
                "max_entry_bytes",
                "compaction_threshold",
            ):
                if hasattr(wal, attr):
                    metrics[attr] = getattr(wal, attr)
            if hasattr(wal, "count_entries"):
                try:
                    metrics["entry_count"] = int(wal.count_entries())
                except Exception:
                    pass
            if head is None:
                findings.append("wal_head_empty")
        if wal_path is not None:
            p = Path(wal_path)
            metrics["wal_path_exists"] = p.exists()
            if p.exists() and p.is_file():
                metrics["wal_path_bytes"] = p.stat().st_size
            elif not p.exists():
                findings.append("wal_path_missing")
        status = "warn" if findings else "ok"
        return DiagnosticSection(
            name="wal",
            status=status,
            summary="wal_ok" if status == "ok" else "wal_attention",
            metrics=metrics,
            findings=findings,
        )
    except Exception as exc:
        return DiagnosticSection(
            name="wal",
            status="error",
            summary=f"wal_diagnostic_failed:{type(exc).__name__}",
            findings=[f"error:{type(exc).__name__}"],
        )


def diagnose_shards(
    manifests: Optional[Sequence[Mapping[str, Any]]] = None,
    *,
    catalog: Any = None,
    tenant: Optional[str] = None,
    graph_id: Optional[str] = None,
) -> DiagnosticSection:
    """Inspect shard descriptors from provided manifests or catalog revision JSON."""
    metrics: Dict[str, Any] = {
        "manifest_count": 0,
        "shard_count": 0,
        "missing_checksum": 0,
        "missing_cid": 0,
    }
    findings: List[str] = []
    payload: List[Mapping[str, Any]] = list(manifests or [])

    if not payload and catalog is not None and tenant and graph_id:
        try:
            revs = catalog.list_revisions(tenant, graph_id)
            for rev in revs:
                raw = (
                    rev.manifest_json
                    if hasattr(rev, "manifest_json")
                    else rev.get("manifest_json")
                )
                if not raw:
                    continue
                try:
                    data = json.loads(raw) if isinstance(raw, str) else raw
                    if isinstance(data, Mapping):
                        payload.append(data)
                except Exception:
                    findings.append("manifest_json_parse_error")
        except Exception as exc:
            return DiagnosticSection(
                name="shard",
                status="error",
                summary=f"shard_scan_failed:{type(exc).__name__}",
                findings=[f"error:{type(exc).__name__}"],
            )

    if not payload:
        return DiagnosticSection(
            name="shard",
            status="unavailable",
            summary="no_shard_manifests",
            metrics=metrics,
        )

    for man in payload:
        metrics["manifest_count"] += 1
        shards = man.get("shards") or man.get("physical_shards") or []
        if isinstance(shards, Mapping):
            shards = list(shards.values())
        for shard in shards:
            if not isinstance(shard, Mapping):
                continue
            metrics["shard_count"] += 1
            checksum = shard.get("checksum")
            if not checksum:
                metrics["missing_checksum"] += 1
            cid = shard.get("cid") or shard.get("root_cid")
            if not cid:
                metrics["missing_cid"] += 1

    if metrics["missing_checksum"]:
        findings.append(f"{metrics['missing_checksum']} shard(s) missing checksum")
    if metrics["missing_cid"]:
        findings.append(f"{metrics['missing_cid']} shard(s) missing cid")
    status = "warn" if findings else "ok"
    return DiagnosticSection(
        name="shard",
        status=status,
        summary=(
            f"{metrics['manifest_count']} manifests, "
            f"{metrics['shard_count']} shards"
        ),
        metrics=metrics,
        findings=findings,
    )


def diagnose_pins(
    catalog: Any,
    *,
    tenant: Optional[str] = None,
    max_graphs: int = 256,
) -> DiagnosticSection:
    """Pin-root coverage relative to branch heads."""
    metrics: Dict[str, Any] = {
        "pin_roots": 0,
        "heads_with_pin": 0,
        "heads_without_pin": 0,
        "graphs_scanned": 0,
    }
    findings: List[str] = []
    try:
        tenants = [tenant] if tenant else _discover_tenants(catalog)
        for t in tenants:
            try:
                graphs = catalog.list_graphs(t)
            except Exception:
                continue
            for g in graphs:
                if metrics["graphs_scanned"] >= max_graphs:
                    findings.append(f"pin_scan_capped_at_{max_graphs}")
                    break
                metrics["graphs_scanned"] += 1
                gid = g.graph_id if hasattr(g, "graph_id") else g["graph_id"]
                try:
                    pins = catalog.list_pin_roots(t, gid)
                    metrics["pin_roots"] += len(pins)
                    pin_revs = {
                        (p.revision_id if hasattr(p, "revision_id") else p["revision_id"])
                        for p in pins
                    }
                except Exception:
                    pin_revs = set()
                try:
                    branches = catalog.list_branches(t, gid)
                except Exception:
                    branches = []
                for br in branches:
                    head = (
                        br.head_revision
                        if hasattr(br, "head_revision")
                        else br.get("head_revision")
                    )
                    if head and head in pin_revs:
                        metrics["heads_with_pin"] += 1
                    elif head:
                        metrics["heads_without_pin"] += 1
                        findings.append(f"head_unpinned:{t}/{gid}@{head}")
        # Bound findings list
        findings = findings[:32]
        status = "warn" if metrics["heads_without_pin"] else "ok"
        return DiagnosticSection(
            name="pin",
            status=status,
            summary=(
                f"{metrics['pin_roots']} pins, "
                f"{metrics['heads_without_pin']} unpinned heads"
            ),
            metrics=metrics,
            findings=findings,
        )
    except Exception as exc:
        return DiagnosticSection(
            name="pin",
            status="error",
            summary=f"pin_diagnostic_failed:{type(exc).__name__}",
            findings=[f"error:{type(exc).__name__}"],
        )


def diagnose_cache(store: Any = None) -> DiagnosticSection:
    """Hybrid / verified cache stats."""
    if store is None:
        return DiagnosticSection(
            name="cache",
            status="unavailable",
            summary="no_cache_configured",
        )
    try:
        metrics: Dict[str, Any] = {}
        findings: List[str] = []
        if hasattr(store, "stats"):
            stats = store.stats()
            if isinstance(stats, Mapping):
                # Keep only scalar / shallow values.
                for k, v in list(stats.items())[:32]:
                    if isinstance(v, (int, float, str, bool)) or v is None:
                        metrics[str(k)] = v
                    elif isinstance(v, Mapping):
                        metrics[str(k)] = {
                            sk: sv
                            for sk, sv in list(v.items())[:16]
                            if isinstance(sv, (int, float, str, bool)) or sv is None
                        }
        if hasattr(store, "list_objects"):
            try:
                objs = list(store.list_objects())
                metrics["object_count"] = len(objs)
            except Exception:
                findings.append("list_objects_failed")
        status = "warn" if findings else "ok"
        return DiagnosticSection(
            name="cache",
            status=status,
            summary="cache_ok" if status == "ok" else "cache_attention",
            metrics=metrics,
            findings=findings,
        )
    except Exception as exc:
        return DiagnosticSection(
            name="cache",
            status="error",
            summary=f"cache_diagnostic_failed:{type(exc).__name__}",
            findings=[f"error:{type(exc).__name__}"],
        )


def run_diagnostics(
    *,
    catalog: Any = None,
    tenant: Optional[str] = None,
    wal: Any = None,
    wal_path: Optional[PathLike] = None,
    shard_manifests: Optional[Sequence[Mapping[str, Any]]] = None,
    hybrid_store: Any = None,
    telemetry: Optional[OpsTelemetry] = None,
) -> DiagnosticsReport:
    """Collect all diagnostic sections and emit a structured ops event."""
    started = time.perf_counter()
    tel = telemetry or get_default_telemetry()
    sections: List[DiagnosticSection] = []
    if catalog is not None:
        sections.append(diagnose_catalog(catalog, tenant=tenant))
        sections.append(diagnose_pins(catalog, tenant=tenant))
        sections.append(
            diagnose_shards(shard_manifests, catalog=catalog, tenant=tenant)
        )
    else:
        sections.append(
            DiagnosticSection(
                name="catalog", status="unavailable", summary="no_catalog"
            )
        )
        sections.append(
            DiagnosticSection(name="pin", status="unavailable", summary="no_catalog")
        )
        sections.append(diagnose_shards(shard_manifests))
    sections.append(diagnose_wal(wal, wal_path=wal_path))
    sections.append(diagnose_cache(hybrid_store))

    report = DiagnosticsReport(
        generated_at=time.time(),
        sections=sections,
        overall_status=_overall(sections),
    )
    duration_ms = (time.perf_counter() - started) * 1000.0
    tel.record_operation(
        "diagnostics",
        duration_ms,
        success=report.overall_status != "error",
        labels={"overall_status": report.overall_status},
    )
    log_ops_event(
        "diagnostics.completed",
        overall_status=report.overall_status,
        duration_ms=duration_ms,
        section_count=len(sections),
    )
    return report


__all__ = [
    "DIAGNOSTICS_SCHEMA_VERSION",
    "DiagnosticSection",
    "DiagnosticsReport",
    "diagnose_cache",
    "diagnose_catalog",
    "diagnose_pins",
    "diagnose_shards",
    "diagnose_wal",
    "run_diagnostics",
]
