"""Integration tests: observability, health, backup, restore, repair (KGP-032).

Acceptance:
  Add structured logs, OpenTelemetry metrics/traces, liveness/readiness,
  catalog/WAL/shard/pin/cache diagnostics, manifest scrub/verify/repair
  previews, immutable backup and restore, disaster-recovery runbook, and
  alert guidance. Restore proves the same revision/checksums/query vectors
  and repair never mutates without an explicit bounded plan.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from ipfs_datasets_py.knowledge_graphs.catalog import (
    bootstrap_revision_id,
    open_catalog,
)
from ipfs_datasets_py.knowledge_graphs.contracts.manifest import (
    GraphCounts,
    ProvenanceDescriptor,
    build_graph_revision_manifest,
)
from ipfs_datasets_py.knowledge_graphs.operations import (
    OPERATIONS_CONTRACT_VERSION,
    OpsLogContext,
    OpsTelemetry,
    apply_repair_plan,
    alert_catalog,
    attach_capture,
    build_default_health,
    create_backup,
    default_alert_rules,
    evaluate_simple_alerts,
    get_ops_logger,
    log_ops_event,
    preview_repair,
    reset_default_telemetry,
    restore_backup,
    run_diagnostics,
    scrub_catalog_manifests,
    scrub_for_telemetry,
    verify_backup,
    verify_manifest,
)
from ipfs_datasets_py.knowledge_graphs.operations.diagnostics import (
    diagnose_shards,
    diagnose_wal,
)
from ipfs_datasets_py.knowledge_graphs.operations.telemetry import SpanStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def telemetry() -> OpsTelemetry:
    reset_default_telemetry()
    return OpsTelemetry(service_name="kg-ops-test")


@pytest.fixture
def catalog(tmp_path: Path):
    path = tmp_path / "kg_catalog.sqlite"
    cat = open_catalog(path)
    yield cat
    cat.close()


def _provenance() -> ProvenanceDescriptor:
    return ProvenanceDescriptor(
        producer_id="kgp-032-tests",
        producer_version="1.0.0",
        source="integration",
        created_at="2026-07-29T12:00:00Z",
    )


def _seed_graph(catalog, tenant: str = "acme", graph_id: str = "orders"):
    """Create graph + verified revision with pin and branch head advanced."""
    catalog.create_graph(tenant, graph_id, storage_profile="parquet")
    boot = bootstrap_revision_id(tenant, graph_id)
    man = build_graph_revision_manifest(
        tenant=tenant,
        graph_id=graph_id,
        revision_id="rev-prod-1",
        schema_id="orders-schema",
        schema_version="1",
        ontology_id="orders-onto",
        ontology_version="1",
        graph_kind="generic",
        storage_profile="parquet",
        codec="json",
        counts=GraphCounts(node_count=0, edge_count=0),
        provenance=_provenance(),
        parent_revision=boot,
    )
    catalog.put_revision(
        tenant,
        graph_id,
        "rev-prod-1",
        parent_revision=boot,
        manifest_cid=man.root_cid,
        manifest_json=man.to_json(),
        pin_root=man.root_cid,
        checksum=man.checksum.hex_digest,
    )
    catalog.cas_set_head(
        tenant,
        graph_id,
        "main",
        expected_revision=boot,
        new_revision="rev-prod-1",
        pin_root=man.root_cid,
        idempotency_key=f"cas-{tenant}-{graph_id}-rev-prod-1",
    )
    catalog.set_pin_root(
        tenant, graph_id, "rev-prod-1", man.root_cid, pin_kind="branch"
    )
    return man


# ---------------------------------------------------------------------------
# Structured logs + redaction
# ---------------------------------------------------------------------------


def test_structured_logs_scrub_secrets_and_queries(telemetry: OpsTelemetry):
    logger = get_ops_logger("kg.ops.test.logs")
    capture = attach_capture(logger)
    with OpsLogContext(request_id="req-1", tenant="acme"):
        payload = log_ops_event(
            "query.executed",
            logger=logger,
            message="ran query",
            token="super-secret-ucan",
            ucan="eyJuc2VjcmV0IjogMX0",
            query_text="MATCH (n) RETURN n",
            raw_query="SELECT * FROM nodes",
            properties={"ssn": "000-00-0000"},
            graph_id="orders",
            duration_ms=12.5,
        )
    assert payload["token"] == "[REDACTED]"
    assert payload["ucan"] == "[REDACTED]"
    assert payload["query_text"] == "[REDACTED]"
    assert payload["raw_query"] == "[REDACTED]"
    assert payload["properties"] == "[REDACTED]"
    assert payload["graph_id"] == "orders"
    assert capture.records, "expected structured JSON log records"
    rec = capture.records[-1]
    assert rec["schema_version"] == "kg-ops-log/v1"
    assert rec["contract_version"] == OPERATIONS_CONTRACT_VERSION
    assert rec["event"] == "query.executed"
    assert rec["token"] == "[REDACTED]"
    assert "super-secret" not in json.dumps(rec)
    assert "MATCH" not in json.dumps(rec)


def test_scrub_for_telemetry_uses_auth_redaction_surface():
    safe = scrub_for_telemetry(
        {
            "authorization": "Bearer abc",
            "signature": "sig",
            "ok": True,
            "revision_id": "rev-1",
        }
    )
    assert safe["authorization"] == "[REDACTED]"
    assert safe["signature"] == "[REDACTED]"
    assert safe["ok"] is True
    assert safe["revision_id"] == "rev-1"


# ---------------------------------------------------------------------------
# OpenTelemetry metrics / traces
# ---------------------------------------------------------------------------


def test_otel_metrics_and_traces(telemetry: OpsTelemetry):
    with telemetry.tracer.span(
        "kg.query", attributes={"tenant": "acme", "token": "SECRET"}
    ) as span:
        telemetry.metrics.inc(
            "kg_ops_operations_total",
            labels={"operation": "query", "status": "ok", "token": "SECRET"},
        )
        telemetry.metrics.observe(
            "kg_ops_operation_duration_ms", 42.0, labels={"operation": "query"}
        )
        telemetry.tracer.add_event(span, "rows_scanned", {"count": "10"})
    assert span.status == SpanStatus.OK
    assert span.end_time is not None
    # Sensitive label scrubbed
    assert span.attributes.get("token") == "[REDACTED]"
    assert span.attributes.get("tenant") == "acme"

    snap = telemetry.metrics.snapshot()
    assert snap["counters"]
    counter = next(c for c in snap["counters"] if c["name"] == "kg_ops_operations_total")
    assert counter["labels"].get("token") == "[REDACTED]"

    prom = telemetry.metrics.export_prometheus()
    assert "kg_ops_operations_total" in prom
    assert "SECRET" not in prom

    export = telemetry.export()
    assert export["schema_version"] == "kg-ops-telemetry/v1"
    assert any(s["name"] == "kg.query" for s in export["spans"])


def test_record_operation_helper(telemetry: OpsTelemetry):
    telemetry.record_operation("diagnostics", 5.0, success=True)
    telemetry.record_operation("backup.create", 20.0, success=False)
    snap = telemetry.metrics.snapshot()
    names = {c["name"] for c in snap["counters"]}
    assert "kg_ops_operations_total" in names
    hist_names = {h["name"] for h in snap["histograms"]}
    assert "kg_ops_operation_duration_ms" in hist_names


# ---------------------------------------------------------------------------
# Liveness / readiness
# ---------------------------------------------------------------------------


def test_liveness_and_readiness(catalog, tmp_path: Path, telemetry: OpsTelemetry):
    _seed_graph(catalog)
    registry = build_default_health(
        catalog=catalog,
        catalog_path=catalog.path,
        telemetry=telemetry,
    )
    live = registry.liveness()
    assert live.alive is True
    assert live.schema_version == "kg-ops-health/v1"
    ready = registry.readiness()
    assert ready.ready is True
    assert ready.status == "healthy"
    names = {p.name for p in ready.probes}
    assert "process" in names
    assert "catalog" in names
    assert "catalog_path" in names

    registry.mark_shutdown()
    assert registry.liveness().alive is False
    assert registry.readiness().ready is False


def test_readiness_fails_on_missing_catalog_path(tmp_path: Path, telemetry: OpsTelemetry):
    registry = build_default_health(
        catalog_path=tmp_path / "does-not-exist.sqlite",
        telemetry=telemetry,
    )
    ready = registry.readiness()
    assert ready.ready is False
    assert ready.status == "not_ready"


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def test_diagnostics_catalog_pin_shard_wal_cache(catalog, telemetry: OpsTelemetry):
    man = _seed_graph(catalog)
    shard_manifest = {
        "version": "kg-shard-manifest/v2",
        "shards": [
            {
                "shard_id": "s0",
                "checksum": {"algorithm": "sha256", "hex_digest": "ab" * 32},
                "cid": man.root_cid,
            },
            {
                "shard_id": "s1",
                "checksum": None,
                "cid": None,
            },
        ],
    }
    report = run_diagnostics(
        catalog=catalog,
        tenant="acme",
        shard_manifests=[shard_manifest],
        wal=None,
        hybrid_store=None,
        telemetry=telemetry,
    )
    by_name = {s.name: s for s in report.sections}
    assert "catalog" in by_name
    assert "pin" in by_name
    assert "shard" in by_name
    assert "wal" in by_name
    assert "cache" in by_name
    assert by_name["catalog"].status in {"ok", "warn"}
    assert by_name["pin"].metrics.get("pin_roots", 0) >= 1
    assert by_name["shard"].metrics.get("shard_count") == 2
    assert by_name["wal"].status == "unavailable"
    assert by_name["cache"].status == "unavailable"
    assert report.contract_version == OPERATIONS_CONTRACT_VERSION


def test_diagnose_wal_with_stub():
    class _WAL:
        wal_head_cid = "bafywalheadcidexample000000000000000000000000000000"
        max_operations_per_entry = 1000
        max_entry_bytes = 4096

    section = diagnose_wal(_WAL())
    assert section.status == "ok"
    assert section.metrics["wal_head_cid_present"] is True


def test_diagnose_shards_missing_checksums():
    section = diagnose_shards(
        [{"shards": [{"shard_id": "a", "checksum": None, "cid": None}]}]
    )
    assert section.status == "warn"
    assert section.metrics["missing_checksum"] == 1


# ---------------------------------------------------------------------------
# Manifest scrub / verify / repair
# ---------------------------------------------------------------------------


def test_verify_manifest_and_scrub(catalog):
    man = _seed_graph(catalog)
    report = verify_manifest(
        man.to_dict(),
        expected_revision_id="rev-prod-1",
        expected_checksum=man.checksum.hex_digest,
    )
    assert report.ok is True
    assert report.checked >= 1

    scrub = scrub_catalog_manifests(catalog, tenant="acme", graph_id="orders")
    assert scrub.checked >= 1


def test_repair_never_mutates_without_confirm(catalog, tmp_path: Path):
    catalog.create_graph("acme", "broken", storage_profile="parquet")
    boot = bootstrap_revision_id("acme", "broken")
    catalog.put_revision(
        "acme",
        "broken",
        "rev-bad",
        parent_revision=boot,
        manifest_json='{"not":"a-valid-manifest"}',
        checksum="ab" * 32,
    )
    before = catalog.get_revision("acme", "broken", "rev-bad")

    plan = preview_repair(catalog, tenant="acme", graph_id="broken")
    assert plan.dry_run is True
    assert plan.plan_id.startswith("repair-")
    assert plan.plan_digest
    assert len(plan.actions) >= 1
    assert plan.to_dict()["mutates_without_confirm"] is False

    refused = apply_repair_plan(catalog, plan, confirm=False)
    assert refused.applied is False
    assert refused.dry_run is True
    assert "never mutates" in refused.notes[0]

    after = catalog.get_revision("acme", "broken", "rev-bad")
    assert after.manifest_json == before.manifest_json
    assert after.checksum == before.checksum

    # Wrong digest refused
    bad = apply_repair_plan(
        catalog, plan, confirm=True, expected_plan_digest="0" * 64
    )
    assert bad.applied is False
    assert bad.error == "PLAN_DIGEST_MISMATCH"
    still = catalog.get_revision("acme", "broken", "rev-bad")
    assert still.manifest_json == before.manifest_json

    # Confirm journals corrections but does not rewrite immutable revision row
    journal = tmp_path / "repair.json"
    applied = apply_repair_plan(
        catalog,
        plan,
        confirm=True,
        expected_plan_digest=plan.plan_digest,
        journal_path=str(journal),
    )
    assert applied.applied is True
    preserved = catalog.get_revision("acme", "broken", "rev-bad")
    assert preserved.manifest_json == before.manifest_json
    assert journal.is_file()
    journal_body = json.loads(journal.read_text(encoding="utf-8"))
    assert journal_body["plan_id"] == plan.plan_id
    assert journal_body["entries"]


# ---------------------------------------------------------------------------
# Immutable backup / restore with proof
# ---------------------------------------------------------------------------


def test_backup_restore_proves_revision_checksums_query_vectors(
    catalog, tmp_path: Path, telemetry: OpsTelemetry
):
    man_orders = _seed_graph(catalog, tenant="acme", graph_id="orders")
    man_inventory = _seed_graph(catalog, tenant="acme", graph_id="inventory")
    expected_checksums = {
        "orders": man_orders.checksum.hex_digest,
        "inventory": man_inventory.checksum.hex_digest,
    }

    backup_root = tmp_path / "backups"
    result = create_backup(
        catalog, backup_root, tenant="acme", telemetry=telemetry, notes=["kpg-032"]
    )
    assert result.backup_id.startswith("bak-")
    assert Path(result.path).is_dir()
    assert result.manifest.to_dict()["immutable"] is True
    assert result.query_vectors
    assert man_orders.checksum.hex_digest in result.manifest.checksums
    assert man_inventory.checksum.hex_digest in result.manifest.checksums
    assert "rev-prod-1" in result.manifest.revision_ids

    ok, issues = verify_backup(result.path)
    assert ok is True
    assert issues == []

    # Files are read-only (best-effort immutability)
    for child in Path(result.path).iterdir():
        assert child.is_file()
        # Owner write bit should be off
        assert child.stat().st_mode & 0o200 == 0

    target = tmp_path / "restored.sqlite"
    restored = restore_backup(result.path, target, telemetry=telemetry)
    assert restored.ok is True, restored.to_dict()
    assert restored.proof.ok is True
    assert restored.proof.mismatches == []
    assert restored.proof.expected_revision_ids == restored.proof.actual_revision_ids
    assert restored.proof.expected_checksums == restored.proof.actual_checksums
    assert (
        restored.proof.expected_query_vectors_digest
        == restored.proof.actual_query_vectors_digest
    )

    # Reopen restored catalog and compare heads + per-graph checksums
    with open_catalog(target) as restored_cat:
        for graph_id, expected_checksum in expected_checksums.items():
            desc = restored_cat.describe_graph("acme", graph_id)
            assert desc.head_revision == "rev-prod-1"
            rev = restored_cat.get_revision("acme", graph_id, "rev-prod-1")
            assert rev.checksum == expected_checksum


def test_restore_refuses_existing_target_without_replace(
    catalog, tmp_path: Path
):
    _seed_graph(catalog)
    bak = create_backup(catalog, tmp_path / "b")
    target = tmp_path / "exists.sqlite"
    target.write_text("nope", encoding="utf-8")
    result = restore_backup(bak.path, target, replace_existing=False)
    assert result.ok is False
    assert result.error == "TARGET_EXISTS"


# ---------------------------------------------------------------------------
# Alert guidance + runbook
# ---------------------------------------------------------------------------


def test_alert_catalog_and_evaluator():
    catalog = alert_catalog()
    assert catalog["schema_version"] == "kg-ops-alerts/v1"
    assert catalog["rule_count"] >= 8
    rules = default_alert_rules()
    ids = {r.rule_id for r in rules}
    assert "kg-ops-liveness-down" in ids
    assert "kg-ops-restore-proof-failed" in ids
    assert "kg-ops-backup-stale" in ids

    firing = evaluate_simple_alerts(
        liveness=False,
        readiness=False,
        heads_without_pin=2,
        missing_checksums=1,
        backup_age_hours=48,
        rpo_hours=24,
    )
    fired_ids = {f["rule_id"] for f in firing}
    assert "kg-ops-liveness-down" in fired_ids
    assert "kg-ops-readiness-fail" in fired_ids
    assert "kg-ops-unpinned-heads" in fired_ids
    assert "kg-ops-catalog-checksum-drift" in fired_ids
    assert "kg-ops-backup-stale" in fired_ids


def test_disaster_recovery_runbook_exists_and_covers_guidance():
    runbook = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "operations"
        / "knowledge_graphs_runbook.md"
    )
    assert runbook.is_file(), f"missing runbook at {runbook}"
    text = runbook.read_text(encoding="utf-8")
    for needle in (
        "Disaster recovery",
        "RestoreProof",
        "confirm=True",
        "kg-ops-liveness-down",
        "structured logs",
        "OpenTelemetry",
        "query vectors",
        "never mutates",
        "immutable backup",
        "Alert",
        "kg-operations/v1",
    ):
        assert needle.lower() in text.lower(), f"runbook missing guidance for {needle!r}"


# ---------------------------------------------------------------------------
# End-to-end operator path
# ---------------------------------------------------------------------------


def test_end_to_end_ops_path(catalog, tmp_path: Path, telemetry: OpsTelemetry):
    """Happy-path: seed → observe → diagnose → backup → restore → prove."""
    man = _seed_graph(catalog)
    logger = get_ops_logger("kg.ops.e2e")
    # Avoid polluting pytest output with JSON: attach capture only
    for h in list(logger.handlers):
        logger.removeHandler(h)
    capture = attach_capture(logger)
    logger.setLevel(logging.INFO)

    with OpsLogContext(request_id="e2e-1", tenant="acme", graph_id="orders"):
        log_ops_event("e2e.start", logger=logger, revision_id="rev-prod-1")

        health = build_default_health(
            catalog=catalog, catalog_path=catalog.path, telemetry=telemetry
        )
        assert health.liveness().alive and health.readiness().ready

        with telemetry.tracer.span("e2e.diagnostics"):
            diag = run_diagnostics(
                catalog=catalog, tenant="acme", telemetry=telemetry
            )
        assert diag.overall_status in {"ok", "warn"}

        scrub = scrub_catalog_manifests(catalog, tenant="acme")
        assert scrub.ok is True

        plan = preview_repair(catalog, tenant="acme", graph_id="orders")
        refused = apply_repair_plan(catalog, plan, confirm=False)
        assert refused.applied is False

        bak = create_backup(catalog, tmp_path / "e2e-bak", telemetry=telemetry)
        ok, _ = verify_backup(bak.path)
        assert ok
        restored = restore_backup(
            bak.path, tmp_path / "e2e-restored.sqlite", telemetry=telemetry
        )
        assert restored.ok and restored.proof.ok
        assert man.checksum.hex_digest in restored.proof.actual_checksums

        log_ops_event(
            "e2e.complete",
            logger=logger,
            backup_id=bak.backup_id,
            proof_ok=True,
        )

    events = [r.get("event") for r in capture.records]
    assert "e2e.start" in events
    assert "e2e.complete" in events
    # No secrets leaked even if operator mistakenly passes them
    leaked = scrub_for_telemetry({"ucan_token": "leak-me", "status": "ok"})
    assert leaked["ucan_token"] == "[REDACTED]"
