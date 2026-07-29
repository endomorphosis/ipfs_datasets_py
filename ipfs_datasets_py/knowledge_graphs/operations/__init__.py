"""Knowledge-graph operations: observability, health, backup, restore, repair (KGP-032).

This package provides production operator surfaces:

* structured, redacted JSON logs
* OpenTelemetry-compatible metrics and traces
* liveness / readiness probes
* catalog / WAL / shard / pin / cache diagnostics
* manifest scrub / verify / repair previews (no mutation without confirm)
* immutable backup and restore with revision/checksum/query-vector proofs
* alert guidance catalog

Contract: ``kg-operations/v1``
"""

from __future__ import annotations

from .alerts import (
    ALERTS_SCHEMA_VERSION,
    AlertRule,
    alert_catalog,
    default_alert_rules,
    evaluate_simple_alerts,
    render_alert_guidance_markdown,
)
from .backup import (
    BACKUP_SCHEMA_VERSION,
    BackupManifest,
    BackupResult,
    QueryVector,
    RestoreProof,
    RestoreResult,
    collect_query_vectors,
    compute_query_fingerprint,
    create_backup,
    export_catalog_snapshot,
    load_backup_manifest,
    prove_restore_equivalence,
    restore_backup,
    verify_backup,
)
from .diagnostics import (
    DIAGNOSTICS_SCHEMA_VERSION,
    DiagnosticSection,
    DiagnosticsReport,
    diagnose_cache,
    diagnose_catalog,
    diagnose_pins,
    diagnose_shards,
    diagnose_wal,
    run_diagnostics,
)
from .health import (
    HEALTH_SCHEMA_VERSION,
    HealthRegistry,
    HealthReport,
    ProbeResult,
    build_default_health,
    catalog_path_probe,
    catalog_probe,
    hybrid_cache_probe,
)
from .logging import (
    LOG_SCHEMA_VERSION,
    InMemoryLogCapture,
    OpsJSONFormatter,
    OpsLogContext,
    OpsLogField,
    attach_capture,
    clear_ops_context,
    get_ops_context,
    get_ops_logger,
    log_ops_event,
    new_request_id,
    set_ops_context,
)
from .manifest_ops import (
    MANIFEST_OPS_SCHEMA,
    MAX_PLAN_ACTIONS,
    ManifestFinding,
    ManifestVerifyReport,
    RepairAction,
    RepairApplyResult,
    RepairJournal,
    RepairPlan,
    apply_repair_plan,
    preview_repair,
    scrub_catalog_manifests,
    scrub_manifest_dict,
    verify_manifest,
)
from .redact import (
    OPERATIONS_CONTRACT_VERSION,
    REDACT_KEYS,
    is_sensitive_key,
    scrub_for_telemetry,
)
from .telemetry import (
    TELEMETRY_SCHEMA_VERSION,
    OpsMetrics,
    OpsTelemetry,
    OpsTracer,
    Span,
    SpanStatus,
    get_default_telemetry,
    reset_default_telemetry,
)

__all__ = [
    "OPERATIONS_CONTRACT_VERSION",
    "ALERTS_SCHEMA_VERSION",
    "BACKUP_SCHEMA_VERSION",
    "DIAGNOSTICS_SCHEMA_VERSION",
    "HEALTH_SCHEMA_VERSION",
    "LOG_SCHEMA_VERSION",
    "MANIFEST_OPS_SCHEMA",
    "MAX_PLAN_ACTIONS",
    "TELEMETRY_SCHEMA_VERSION",
    "REDACT_KEYS",
    "AlertRule",
    "BackupManifest",
    "BackupResult",
    "DiagnosticSection",
    "DiagnosticsReport",
    "HealthRegistry",
    "HealthReport",
    "InMemoryLogCapture",
    "ManifestFinding",
    "ManifestVerifyReport",
    "OpsJSONFormatter",
    "OpsLogContext",
    "OpsLogField",
    "OpsMetrics",
    "OpsTelemetry",
    "OpsTracer",
    "ProbeResult",
    "QueryVector",
    "RepairAction",
    "RepairApplyResult",
    "RepairJournal",
    "RepairPlan",
    "RestoreProof",
    "RestoreResult",
    "Span",
    "SpanStatus",
    "alert_catalog",
    "apply_repair_plan",
    "attach_capture",
    "build_default_health",
    "catalog_path_probe",
    "catalog_probe",
    "clear_ops_context",
    "collect_query_vectors",
    "compute_query_fingerprint",
    "create_backup",
    "default_alert_rules",
    "diagnose_cache",
    "diagnose_catalog",
    "diagnose_pins",
    "diagnose_shards",
    "diagnose_wal",
    "evaluate_simple_alerts",
    "export_catalog_snapshot",
    "get_default_telemetry",
    "get_ops_context",
    "get_ops_logger",
    "hybrid_cache_probe",
    "is_sensitive_key",
    "load_backup_manifest",
    "log_ops_event",
    "new_request_id",
    "preview_repair",
    "prove_restore_equivalence",
    "render_alert_guidance_markdown",
    "reset_default_telemetry",
    "restore_backup",
    "run_diagnostics",
    "scrub_catalog_manifests",
    "scrub_for_telemetry",
    "scrub_manifest_dict",
    "set_ops_context",
    "verify_backup",
    "verify_manifest",
]
