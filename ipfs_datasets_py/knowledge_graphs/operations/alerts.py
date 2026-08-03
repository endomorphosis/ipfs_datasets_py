"""Alert guidance and rule catalog for knowledge-graph operations (KGP-032).

Defines bounded alert rules, severity, recommended runbook sections, and
metric/query bindings used by on-call and the disaster-recovery runbook.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .redact import OPERATIONS_CONTRACT_VERSION

ALERTS_SCHEMA_VERSION = "kg-ops-alerts/v1"


@dataclass(frozen=True, slots=True)
class AlertRule:
    """One production alert with operator guidance."""

    rule_id: str
    name: str
    severity: str  # info | warning | critical
    description: str
    metric: str
    condition: str
    for_duration: str
    runbook_section: str
    impact: str
    recommended_actions: tuple[str, ...] = ()
    labels: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "severity": self.severity,
            "description": self.description,
            "metric": self.metric,
            "condition": self.condition,
            "for_duration": self.for_duration,
            "runbook_section": self.runbook_section,
            "impact": self.impact,
            "recommended_actions": list(self.recommended_actions),
            "labels": dict(self.labels),
        }


def default_alert_rules() -> List[AlertRule]:
    """Return the closed set of KG operations alerts (v1)."""
    return [
        AlertRule(
            rule_id="kg-ops-liveness-down",
            name="KnowledgeGraphLivenessDown",
            severity="critical",
            description="Process liveness probe failed; service may be wedged or dead.",
            metric="kg_ops_liveness",
            condition="kg_ops_liveness == 0",
            for_duration="1m",
            runbook_section="Liveness failure",
            impact="All graph APIs unavailable from this instance.",
            recommended_actions=(
                "Check process status and recent structured logs for fatal errors",
                "Confirm no shutdown drain is in progress",
                "Restart instance only after capturing diagnostics snapshot",
            ),
            labels={"component": "knowledge_graphs", "probe": "liveness"},
        ),
        AlertRule(
            rule_id="kg-ops-readiness-fail",
            name="KnowledgeGraphReadinessFailed",
            severity="critical",
            description="Readiness probes failed; instance should be removed from load balancers.",
            metric="kg_ops_readiness",
            condition="kg_ops_readiness == 0",
            for_duration="2m",
            runbook_section="Readiness failure",
            impact="Instance cannot safely serve traffic; catalog/cache/WAL may be unhealthy.",
            recommended_actions=(
                "Inspect readiness probe details (catalog, cache, path)",
                "Run run_diagnostics() and capture the report",
                "Do not promote canary traffic until ready==true",
            ),
            labels={"component": "knowledge_graphs", "probe": "readiness"},
        ),
        AlertRule(
            rule_id="kg-ops-catalog-checksum-drift",
            name="KnowledgeGraphCatalogChecksumDrift",
            severity="critical",
            description="Catalog revision checksums diverge from manifest identity.",
            metric="kg_ops_diagnostics",
            condition="diagnostics.catalog.missing_checksums > 0 OR finding CATALOG_CHECKSUM_DRIFT",
            for_duration="5m",
            runbook_section="Manifest integrity / repair",
            impact="Readers may disagree on revision identity; queries can return inconsistent vectors.",
            recommended_actions=(
                "Run scrub_catalog_manifests and preview_repair (dry-run)",
                "Never apply repair without confirm=True and matching plan_digest",
                "Prefer restore from last verified immutable backup if drift is widespread",
            ),
            labels={"component": "catalog", "class": "integrity"},
        ),
        AlertRule(
            rule_id="kg-ops-unpinned-heads",
            name="KnowledgeGraphUnpinnedHeads",
            severity="warning",
            description="Active branch heads lack pin roots and may be GC-eligible incorrectly.",
            metric="diagnostics.pin.heads_without_pin",
            condition="heads_without_pin > 0",
            for_duration="15m",
            runbook_section="Pin / GC diagnostics",
            impact="GC dry-run may flag live data; risk of data loss if GC forced.",
            recommended_actions=(
                "Run diagnose_pins and re-pin heads from revision pin_root/manifest_cid",
                "Confirm GC remains dry-run until pins restored",
            ),
            labels={"component": "pins", "class": "durability"},
        ),
        AlertRule(
            rule_id="kg-ops-wal-head-missing",
            name="KnowledgeGraphWALHeadMissing",
            severity="warning",
            description="WAL head empty or path missing after writes expected.",
            metric="diagnostics.wal",
            condition="wal_head_cid_present == false AND write_traffic > 0",
            for_duration="10m",
            runbook_section="WAL / crash recovery",
            impact="Crash recovery may be incomplete; recent transactions at risk.",
            recommended_actions=(
                "Inspect diagnose_wal section",
                "Halt writers if publish phase incomplete",
                "Follow multi-phase recovery matrix (INTENT/PREPARE/PUBLISH/COMPLETE)",
            ),
            labels={"component": "wal", "class": "durability"},
        ),
        AlertRule(
            rule_id="kg-ops-backup-stale",
            name="KnowledgeGraphBackupStale",
            severity="warning",
            description="No successful immutable backup within the configured RPO window.",
            metric="kg_ops_operations_total{operation=\"backup.create\",status=\"ok\"}",
            condition="time since last successful backup > RPO",
            for_duration="1h",
            runbook_section="Backup and restore",
            impact="Disaster recovery may exceed RPO; data loss window expands.",
            recommended_actions=(
                "Run create_backup against the primary catalog",
                "verify_backup on the artifact",
                "Store backup off-box with the backup_digest recorded in the change ticket",
            ),
            labels={"component": "backup", "class": "dr"},
        ),
        AlertRule(
            rule_id="kg-ops-restore-proof-failed",
            name="KnowledgeGraphRestoreProofFailed",
            severity="critical",
            description="Restore completed but revision/checksum/query vector proof failed.",
            metric="kg_ops_operations_total{operation=\"backup.restore\",status=\"error\"}",
            condition="restore proof.ok == false",
            for_duration="0m",
            runbook_section="Backup and restore",
            impact="Restored catalog is not safe for traffic; identity drift possible.",
            recommended_actions=(
                "Do not point production at the restored catalog",
                "Compare RestoreProof mismatches",
                "Retry restore from a different verified backup_digest",
            ),
            labels={"component": "restore", "class": "dr"},
        ),
        AlertRule(
            rule_id="kg-ops-error-rate-high",
            name="KnowledgeGraphOpsErrorRateHigh",
            severity="warning",
            description="Elevated error rate on operational or query path.",
            metric="kg_ops_operations_total",
            condition="rate(errors) / rate(total) > 0.05",
            for_duration="10m",
            runbook_section="Alert response",
            impact="Degraded caller experience; possible partial outage.",
            recommended_actions=(
                "Inspect structured logs (redacted) for error_code spikes",
                "Correlate with OTel spans (operation duration p95)",
                "Check readiness and diagnostics before scaling out",
            ),
            labels={"component": "operations", "class": "slo"},
        ),
        AlertRule(
            rule_id="kg-ops-p95-latency-regression",
            name="KnowledgeGraphP95LatencyRegression",
            severity="warning",
            description="p95 operation latency regresses more than 10% vs baseline.",
            metric="kg_ops_operation_duration_ms",
            condition="p95 > baseline_p95 * 1.10",
            for_duration="30m",
            runbook_section="Alert response",
            impact="Release gate risk; sustained regression blocks promotion.",
            recommended_actions=(
                "Compare histogram snapshot against labelled baseline",
                "Check cache hit rate and shard routing diagnostics",
                "Hold release if unexplained >10% p95 regression",
            ),
            labels={"component": "performance", "class": "slo"},
        ),
    ]


def alert_catalog() -> Dict[str, Any]:
    """Machine-readable alert catalog for exporters and the runbook."""
    rules = default_alert_rules()
    return {
        "schema_version": ALERTS_SCHEMA_VERSION,
        "contract_version": OPERATIONS_CONTRACT_VERSION,
        "rule_count": len(rules),
        "rules": [r.to_dict() for r in rules],
    }


def render_alert_guidance_markdown(rules: Optional[Sequence[AlertRule]] = None) -> str:
    """Render alert guidance as Markdown for inclusion in the ops runbook."""
    rules = list(rules or default_alert_rules())
    lines = [
        "### Alert catalog (machine-aligned)",
        "",
        "These rules are defined in "
        "`ipfs_datasets_py.knowledge_graphs.operations.alerts` and must stay "
        "in sync with on-call dashboards.",
        "",
    ]
    for rule in rules:
        lines.append(f"#### `{rule.rule_id}` — {rule.name}")
        lines.append("")
        lines.append(f"- **Severity:** {rule.severity}")
        lines.append(f"- **Metric:** `{rule.metric}`")
        lines.append(f"- **Condition:** `{rule.condition}` (for {rule.for_duration})")
        lines.append(f"- **Impact:** {rule.impact}")
        lines.append(f"- **Runbook section:** {rule.runbook_section}")
        lines.append(f"- **Description:** {rule.description}")
        if rule.recommended_actions:
            lines.append("- **Recommended actions:**")
            for action in rule.recommended_actions:
                lines.append(f"  - {action}")
        lines.append("")
    return "\n".join(lines)


def evaluate_simple_alerts(
    *,
    liveness: Optional[bool] = None,
    readiness: Optional[bool] = None,
    heads_without_pin: int = 0,
    missing_checksums: int = 0,
    backup_age_hours: Optional[float] = None,
    rpo_hours: float = 24.0,
) -> List[Dict[str, Any]]:
    """Lightweight evaluator for unit/integration tests and local ops CLIs."""
    firing: List[Dict[str, Any]] = []
    if liveness is False:
        firing.append({"rule_id": "kg-ops-liveness-down", "severity": "critical"})
    if readiness is False:
        firing.append({"rule_id": "kg-ops-readiness-fail", "severity": "critical"})
    if missing_checksums > 0:
        firing.append(
            {"rule_id": "kg-ops-catalog-checksum-drift", "severity": "critical"}
        )
    if heads_without_pin > 0:
        firing.append({"rule_id": "kg-ops-unpinned-heads", "severity": "warning"})
    if backup_age_hours is not None and backup_age_hours > rpo_hours:
        firing.append({"rule_id": "kg-ops-backup-stale", "severity": "warning"})
    return firing


__all__ = [
    "ALERTS_SCHEMA_VERSION",
    "AlertRule",
    "alert_catalog",
    "default_alert_rules",
    "evaluate_simple_alerts",
    "render_alert_guidance_markdown",
]
