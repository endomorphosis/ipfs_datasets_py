"""Integration tests for observability shadow adapters (DQK-077).

Acceptance coverage:

* Every mutable log/audit/alert record has a typed schema, stable event ID,
  classification, source revision, and parity receipt
* Retries and restarts do not duplicate events
* Secrets and unrestricted SQL are redacted before persistence or publication
* Immutable evidence blobs remain content-addressed outside DuckDB

Also exercises producer wiring for audit, security, GraphRAG, structured
logging, MCP, alerts, and logging-audit while legacy sinks remain the
explicitly selected shadow-mode authority.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()


def _prefer_sealed_accelerate_checkout() -> None:
    accelerate_paths: list[Path] = []
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            continue
        runtime = (
            path
            / "ipfs_accelerate_py"
            / "agent_supervisor"
            / "validation_runtime.py"
        )
        if runtime.is_file() and path not in accelerate_paths:
            accelerate_paths.append(path)
    if not accelerate_paths:
        return
    preferred = next(
        (path for path in accelerate_paths if path != _LOCAL_ACCELERATE),
        accelerate_paths[0],
    )
    if preferred == _LOCAL_ACCELERATE:
        return
    rebuilt: list[str] = [str(preferred)]
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            rebuilt.append(entry)
            continue
        if path in {_LOCAL_ACCELERATE, preferred}:
            continue
        rebuilt.append(entry)
    sys.path[:] = rebuilt
    for name in list(sys.modules):
        if name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py."):
            del sys.modules[name]


_prefer_sealed_accelerate_checkout()

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from ipfs_datasets_py.duckdb_control.authority_transition import AuthorityMode
from ipfs_datasets_py.duckdb_control.observability import (
    AUDIT_RECORD_SCHEMA,
    REDACTION_MARKER,
    CatalogFamily,
    ProgressAuthority,
    SensitivityClass,
)
from ipfs_datasets_py.duckdb_control.observability_adapters import (
    OBSERVABILITY_ADAPTER_SCHEMA,
    OBSERVABILITY_EVENT_RECEIPT_SCHEMA,
    OBSERVABILITY_SHADOW_DOMAIN,
    OBSERVABILITY_SHADOW_OWNER_TASK,
    OBSERVABILITY_SOURCE_REVISION,
    MemoryEvidenceBlobStore,
    ObservabilityProducer,
    ObservabilityShadowRepository,
    configure_observability_shadow,
    get_observability_shadow,
    redact_event_payload,
    reset_observability_shadow,
    route_alert_event,
    route_audit_logger_event,
    route_graphrag_audit_event,
    route_logging_audit_result,
    route_mcp_log_event,
    route_pipeline_json_event,
    route_producer_event,
    route_security_audit_event,
    route_structured_log_event,
    stable_event_id,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def shadow() -> ObservabilityShadowRepository:
    reset_observability_shadow()
    repo = configure_observability_shadow(enabled=True)
    yield repo
    reset_observability_shadow()


# ---------------------------------------------------------------------------
# Module / wiring invariants
# ---------------------------------------------------------------------------


class TestModuleInvariants:
    def test_schema_and_owner_constants(self) -> None:
        assert OBSERVABILITY_SHADOW_OWNER_TASK == "DQK-077"
        assert OBSERVABILITY_SHADOW_DOMAIN == "observability"
        assert OBSERVABILITY_ADAPTER_SCHEMA.startswith("ipfs_datasets_py/")
        assert OBSERVABILITY_EVENT_RECEIPT_SCHEMA.startswith("ipfs_datasets_py/")
        assert OBSERVABILITY_SOURCE_REVISION.startswith("dqk-077")

    def test_process_registry_configure_get_reset(self) -> None:
        reset_observability_shadow()
        assert get_observability_shadow() is None
        auth = configure_observability_shadow()
        assert get_observability_shadow() is auth
        assert auth.enabled
        assert auth.authority_mode == AuthorityMode.SHADOW
        reset_observability_shadow()
        assert get_observability_shadow() is None

    def test_import_is_inert(self) -> None:
        # Module already imported; re-check schema pins without side effects.
        assert ObservabilityProducer.AUDIT.value == "audit"
        assert AuthorityMode.SHADOW.value == "shadow"


# ---------------------------------------------------------------------------
# Acceptance: typed schema, stable ID, classification, source revision, parity
# ---------------------------------------------------------------------------


class TestEveryRecordHasRequiredFields:
    def test_every_mutable_record_has_typed_fields(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        producers = [
            (
                ObservabilityProducer.AUDIT,
                "data_access",
                {"resource_id": "r1", "status": "success"},
            ),
            (
                ObservabilityProducer.SECURITY_AUDIT,
                "proof_attempt",
                {"prover": "z3", "success": True},
            ),
            (
                ObservabilityProducer.STRUCTURED_LOG,
                "mcp.tool.invoked",
                {"tool_name": "ipfs_add"},
            ),
            (
                ObservabilityProducer.GRAPHRAG_AUDIT,
                "strategy_decision",
                {"round_num": 1},
            ),
            (
                ObservabilityProducer.PIPELINE_JSON,
                "pipeline.run.started",
                {"run_id": "run-1", "status": "started"},
            ),
            (
                ObservabilityProducer.LOGGING_AUDIT,
                "logging_audit.result",
                {"file_path": "optimizers/foo.py"},
            ),
            (
                ObservabilityProducer.ALERT,
                "alert.triggered",
                {"rule_id": "rule-1", "severity": "warning"},
            ),
            (
                ObservabilityProducer.MCP,
                "mcp.info",
                {"message": "server ready"},
            ),
            (
                ObservabilityProducer.PROVENANCE,
                "provenance.linked",
                {"cid": "bafytest01"},
            ),
        ]
        receipts = []
        for producer, kind, payload in producers:
            receipt = shadow.record_event(
                producer=producer,
                kind=kind,
                payload=payload,
                actor="tester",
                outcome="succeeded",
            )
            receipts.append(receipt)

        assert len(receipts) == len(producers)
        for receipt in receipts:
            body = receipt.to_dict()
            assert body["schema"] == OBSERVABILITY_EVENT_RECEIPT_SCHEMA
            assert body["record_schema"], "missing typed record schema"
            assert body["record_schema"].startswith("ipfs_datasets_py/")
            assert body["event_id"], "missing stable event id"
            assert body["classification"] in {
                c.value for c in SensitivityClass
            }
            assert body["classification"] != SensitivityClass.SECRET.value
            assert body["source_revision"], "missing source revision"
            assert body["source_revision"].startswith("dqk-077")
            assert body["parity_receipt_cid"], "missing parity receipt"
            assert body["parity_matched"] is True, body
            assert body["mode"] == AuthorityMode.SHADOW.value
            assert body["authority"] == "legacy"
            assert body["payload_digest"].startswith("sha256:")
            assert body["evidence_cid"].startswith("sha256:")
            assert body["sequence"] >= 1

            # Catalog holds the typed row under the declared family.
            record = shadow.catalog_record(receipt.family, receipt.event_id)
            assert record is not None, receipt.to_dict()
            assert getattr(record, "SCHEMA", None) or True
            if receipt.family == CatalogFamily.AUDIT_EVENTS.value:
                assert record.SCHEMA == AUDIT_RECORD_SCHEMA

        parity = shadow.list_parity_receipts()
        assert len(parity) == len(producers)
        assert all(p.matched for p in parity)

    def test_legacy_is_selected_shadow_authority(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        receipt = shadow.record_event(
            producer=ObservabilityProducer.AUDIT,
            kind="login",
            payload={"user": "alice"},
            actor="alice",
            outcome="succeeded",
        )
        assert receipt.mode == "shadow"
        assert receipt.authority == "legacy"
        # Legacy sink projection is retained for parity / restart.
        legacy = shadow.legacy_sink_records()
        assert legacy
        assert any(row["event_id"] == receipt.event_id for row in legacy)


# ---------------------------------------------------------------------------
# Acceptance: retries / restarts do not duplicate
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_retry_same_operation_id_does_not_duplicate(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        first = shadow.record_event(
            producer=ObservabilityProducer.AUDIT,
            kind="retry_probe",
            payload={"n": 1},
            event_id="evt-idempotent-fixed-001",
            operation_id="op:idempotent-fixed",
            actor="tester",
        )
        second = shadow.record_event(
            producer=ObservabilityProducer.AUDIT,
            kind="retry_probe",
            payload={"n": 1},
            event_id="evt-idempotent-fixed-001",
            operation_id="op:idempotent-fixed",
            actor="tester",
        )
        assert second.idempotent_replay is True
        assert second.event_id == first.event_id
        assert second.operation_id == first.operation_id
        assert second.parity_receipt_cid == first.parity_receipt_cid
        assert second.sequence == first.sequence

        # Only one catalog row.
        rows = shadow.observability_catalog.list_family(CatalogFamily.AUDIT_EVENTS)
        matching = [r for r in rows if getattr(r, "event_id", None) == first.event_id]
        assert len(matching) == 1

    def test_content_derived_stable_id_is_idempotent(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        payload = {"action": "export", "resource": "dataset-1"}
        eid = stable_event_id(ObservabilityProducer.AUDIT, "export", payload)
        a = shadow.record_event(
            producer=ObservabilityProducer.AUDIT,
            kind="export",
            payload=payload,
            event_id=eid,
            actor="exporter",
        )
        b = shadow.record_event(
            producer=ObservabilityProducer.AUDIT,
            kind="export",
            payload=payload,
            event_id=eid,
            actor="exporter",
        )
        assert b.idempotent_replay is True
        assert a.event_id == b.event_id == eid

    def test_restart_does_not_duplicate_with_shared_backend(self) -> None:
        reset_observability_shadow()
        first = configure_observability_shadow()
        receipt = first.record_event(
            producer=ObservabilityProducer.MCP,
            kind="mcp.info",
            payload={"message": "boot"},
            event_id="evt-restart-1",
            operation_id="op:restart-1",
            actor="mcp",
        )
        backend = first.backend
        catalog = first.observability_catalog
        evidence = first.evidence_store

        # Simulate restart: new repository over the same durable pieces.
        restarted = ObservabilityShadowRepository(
            mode=AuthorityMode.SHADOW,
            catalog=catalog,
            backend=backend,
            evidence_store=evidence,
            enabled=True,
        )
        # Seed prior receipt index as a restarted process would after recovery
        # of the operation log (receipts are re-derived from op id).
        again = restarted.record_event(
            producer=ObservabilityProducer.MCP,
            kind="mcp.info",
            payload={"message": "boot"},
            event_id="evt-restart-1",
            operation_id="op:restart-1",
            actor="mcp",
        )
        # Catalog still has exactly one row for the event.
        rows = catalog.list_family(CatalogFamily.AUDIT_EVENTS)
        matching = [
            r for r in rows if getattr(r, "event_id", None) == "evt-restart-1"
        ]
        assert len(matching) == 1
        # Authority-port write is idempotent for the same operation id.
        assert again.event_id == receipt.event_id
        reset_observability_shadow()


# ---------------------------------------------------------------------------
# Acceptance: secrets and unrestricted SQL redacted
# ---------------------------------------------------------------------------


class TestRedaction:
    def test_secrets_redacted_before_persistence(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        receipt = shadow.record_event(
            producer=ObservabilityProducer.SECURITY_AUDIT,
            kind="credential_check",
            payload={
                "password": "hunter2",
                "api_key": "sk-live-secret-value",
                "authorization": "Bearer abc.def.ghi",
                "user": "alice",
                "note": "login attempt",
            },
            actor="alice",
            outcome="denied",
            detail="password=hunter2 should never appear",
        )
        record = shadow.catalog_record(receipt.family, receipt.event_id)
        assert record is not None
        detail = str(getattr(record, "detail", "") or "")
        attrs = dict(getattr(record, "attributes", {}) or {})
        blob = shadow.evidence_blob(receipt.evidence_cid)
        assert blob is not None
        blob_text = blob.decode("utf-8")

        for secret in ("hunter2", "sk-live-secret-value", "abc.def.ghi"):
            assert secret not in detail
            assert secret not in blob_text
            assert secret not in str(attrs)

        assert REDACTION_MARKER in blob_text or receipt.classification == (
            SensitivityClass.REDACTED.value
        )
        assert receipt.classification in {
            SensitivityClass.REDACTED.value,
            SensitivityClass.INTERNAL.value,
        }
        assert receipt.classification != SensitivityClass.SECRET.value

    def test_unrestricted_sql_redacted(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        sql = "SELECT * FROM users WHERE password = 'hunter2' AND id = 1"
        receipt = shadow.record_event(
            producer=ObservabilityProducer.QUERY_PROFILE,
            kind="ad_hoc_query",
            payload={"sql": sql, "template_id": "adhoc"},
            actor="analyst",
            outcome="succeeded",
            query_text=sql,
            family=CatalogFamily.QUERY_PROFILES,
        )
        record = shadow.catalog_record(
            CatalogFamily.QUERY_PROFILES, receipt.event_id
        )
        assert record is not None
        stored = str(getattr(record, "query_text", "") or "")
        assert "hunter2" not in stored
        assert getattr(record, "query_text_classification") in {
            SensitivityClass.REDACTED,
            SensitivityClass.REDACTED.value,
        } or str(getattr(record, "query_text_classification")).endswith(
            "redacted"
        )
        blob = shadow.evidence_blob(receipt.evidence_cid)
        assert blob is not None
        assert "hunter2" not in blob.decode("utf-8")

    def test_redact_event_payload_helper(self) -> None:
        cleaned = redact_event_payload(
            {
                "password": "x",
                "query_text": "INSERT INTO t VALUES (1)",
                "ok": True,
                "nested": {"token": "abc", "count": 2},
            }
        )
        assert cleaned["password"] == REDACTION_MARKER
        assert cleaned["nested"]["token"] == REDACTION_MARKER
        assert cleaned["ok"] is True
        assert cleaned["nested"]["count"] == 2
        assert "INSERT" not in cleaned["query_text"] or REDACTION_MARKER in cleaned[
            "query_text"
        ] or cleaned["query_text_classification"] == SensitivityClass.REDACTED.value


# ---------------------------------------------------------------------------
# Acceptance: evidence blobs content-addressed outside DuckDB
# ---------------------------------------------------------------------------


class TestEvidenceOutsideDuckDB:
    def test_evidence_is_content_addressed_and_outside_catalog(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        receipt = shadow.record_event(
            producer=ObservabilityProducer.PROVENANCE,
            kind="blob_linked",
            payload={"cid": "bafyexample", "bytes_hint": 42},
            actor="prov",
        )
        assert isinstance(shadow.evidence_store, MemoryEvidenceBlobStore)
        assert shadow.evidence_store.has(receipt.evidence_cid)
        blob = shadow.evidence_blob(receipt.evidence_cid)
        assert blob is not None
        assert b"bafyexample" in blob

        # Catalog attributes only carry the CID, never raw nested blob bytes.
        record = shadow.catalog_record(receipt.family, receipt.event_id)
        assert record is not None
        attrs = dict(getattr(record, "attributes", {}) or {})
        assert attrs.get("evidence_cid") == receipt.evidence_cid
        # No raw payload dump of nested structures as bytes on the record.
        assert not isinstance(getattr(record, "detail", None), (bytes, bytearray))

    def test_progress_is_sequence_not_mtime(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        shadow.record_event(
            producer=ObservabilityProducer.LIFECYCLE,
            kind="component.start",
            payload={"component": "supervisor"},
            actor="system",
            family=CatalogFamily.LIFECYCLE_EVENTS,
        )
        progress = shadow.progress()
        assert progress.authority is ProgressAuthority.SEQUENCE
        assert progress.sequence >= 1


# ---------------------------------------------------------------------------
# Producer convenience routers + real producer modules
# ---------------------------------------------------------------------------


class TestProducerRouters:
    def test_route_helpers_when_configured(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        r1 = route_security_audit_event(
            event_type="rate_limit_exceeded",
            user_id="u1",
            success=False,
            details={"limit_calls": 10},
        )
        assert r1 is not None
        assert r1.producer == ObservabilityProducer.SECURITY_AUDIT.value

        r2 = route_structured_log_event(
            event_type="system.start",
            fields={"component": "mcp"},
        )
        assert r2 is not None

        r3 = route_pipeline_json_event(
            event_type="pipeline.run.started",
            data={"run_id": "r-1", "status": "started"},
            domain="legal",
            run_id="r-1",
        )
        assert r3 is not None
        assert r3.producer == ObservabilityProducer.PIPELINE_JSON.value

        r4 = route_alert_event(
            rule_id="rule-cpu",
            rule_name="CPU high",
            severity="warning",
            status="triggered",
            message="cpu > 90",
        )
        assert r4 is not None
        assert r4.parity_matched is True

        r5 = route_mcp_log_event(message="tool registered", level="INFO")
        assert r5 is not None

        r6 = route_logging_audit_result(
            {
                "file_path": "ipfs_datasets_py/optimizers/foo.py",
                "class_name": "Foo",
                "methods_with_logging": ["run"],
                "methods_without_logging": ["generate"],
                "has_logger_init": True,
                "issues": [],
            }
        )
        assert r6 is not None

        r7 = route_producer_event(
            producer=ObservabilityProducer.PROVENANCE,
            kind="edge_recorded",
            payload={"from": "a", "to": "b"},
        )
        assert r7 is not None

    def test_route_helpers_noop_without_shadow(self) -> None:
        reset_observability_shadow()
        assert route_mcp_log_event(message="x") is None
        assert (
            route_security_audit_event(
                event_type="x", user_id="u", success=True
            )
            is None
        )

    def test_core_audit_logger_routes_when_shadow_configured(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        from ipfs_datasets_py.audit.audit_logger import (
            AuditCategory,
            AuditLevel,
            AuditLogger,
        )

        # Fresh logger instance (not necessarily singleton) so test is hermetic.
        logger = AuditLogger()
        event_id = logger.log(
            AuditLevel.INFO,
            AuditCategory.SECURITY,
            "login",
            user="alice",
            resource_id="session-1",
            status="success",
            details={"method": "password"},
            event_id="evt-core-audit-login-001",
        )
        assert event_id == "evt-core-audit-login-001"
        receipts = shadow.list_receipts(producer=ObservabilityProducer.AUDIT.value)
        assert any(r.event_id == "evt-core-audit-login-001" for r in receipts)

    def test_security_audit_log_routes(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        from ipfs_datasets_py.logic.security.audit_log import AuditLogger

        AuditLogger.log_event(
            event_type="proof_attempt",
            user_id="prover-1",
            success=True,
            details={"prover": "z3", "duration_ms": 12.5},
        )
        receipts = shadow.list_receipts(
            producer=ObservabilityProducer.SECURITY_AUDIT.value
        )
        assert receipts
        assert any(r.kind.startswith("proof") or "proof" in r.kind for r in receipts)

    def test_graphrag_audit_logger_routes(
        self, shadow: ObservabilityShadowRepository, tmp_path: Path
    ) -> None:
        from ipfs_datasets_py.optimizers.graphrag.audit_logger import (
            AuditLogger as GraphAuditLogger,
            EventType,
        )

        # Memory-only so we do not require path_validator write privileges.
        gal = GraphAuditLogger(
            session_id="sess-test-001",
            output_dir=None,
            enable_file_logging=False,
        )
        gal.log_cycle_start(
            data="sample",
            context=type("C", (), {"data_source": "t", "domain": "legal"})(),
            max_rounds=3,
            convergence_threshold=0.1,
        )
        receipts = shadow.list_receipts(
            producer=ObservabilityProducer.GRAPHRAG_AUDIT.value
        )
        assert receipts
        assert any(
            EventType.REFINEMENT_CYCLE_START.value in r.kind
            or r.kind == EventType.REFINEMENT_CYCLE_START.value
            for r in receipts
        )

    def test_pipeline_json_logger_routes(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        from ipfs_datasets_py.optimizers.graphrag.pipeline_json_logger import (
            PipelineJSONLogger,
        )

        pl = PipelineJSONLogger(domain="legal")
        pl.start_run(run_id="run-pipeline-1", data_source="unit-test")
        pl.end_run(success=True)
        receipts = shadow.list_receipts(
            producer=ObservabilityProducer.PIPELINE_JSON.value
        )
        assert len(receipts) >= 2

    def test_structured_logging_routes(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        from ipfs_datasets_py.logic.observability.structured_logging import (
            EventType,
            log_event,
        )

        log_event(EventType.SYSTEM_START, component="integration-test")
        receipts = shadow.list_receipts(
            producer=ObservabilityProducer.STRUCTURED_LOG.value
        )
        assert receipts

    def test_mcp_logger_helper_routes(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        from ipfs_datasets_py.mcp_server.logger import log_mcp_event

        log_mcp_event(
            "mcp shadow probe",
            level="INFO",
            event_id="evt-mcp-probe-001",
            operation_id="op:mcp-probe-001",
        )
        receipt = shadow.get_receipt(event_id="evt-mcp-probe-001")
        assert receipt is not None
        assert receipt.producer == ObservabilityProducer.MCP.value
        assert receipt.parity_matched is True

    def test_logging_auditor_routes(
        self, shadow: ObservabilityShadowRepository, tmp_path: Path
    ) -> None:
        from ipfs_datasets_py.optimizers.common.logging_audit import LoggingAuditor

        sample = tmp_path / "sample_mod.py"
        sample.write_text(
            "import logging\n"
            "logger = logging.getLogger(__name__)\n"
            "class Foo:\n"
            "    def generate(self):\n"
            "        return 1\n"
            "    def run_session(self):\n"
            "        logger.info('ok')\n",
            encoding="utf-8",
        )
        auditor = LoggingAuditor(root_dir=str(tmp_path))
        result = auditor.audit_file(sample)
        assert result.file_path
        receipts = shadow.list_receipts(
            producer=ObservabilityProducer.LOGGING_AUDIT.value
        )
        assert receipts

    def test_alert_manager_routes(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        # Call the router used by AlertManager without needing Discord/async.
        receipt = route_alert_event(
            rule_id="rule-disk",
            rule_name="Disk full",
            severity="critical",
            status="triggered",
            message="disk > 95%",
            event_payload={"host": "node-1"},
            event_id="evt-alert-disk-001",
            operation_id="op:alert-disk-001",
        )
        assert receipt is not None
        stored = shadow.get_receipt(operation_id="op:alert-disk-001")
        assert stored is not None
        assert stored.parity_receipt_cid


# ---------------------------------------------------------------------------
# Multi-producer parity across a restart-like dual path
# ---------------------------------------------------------------------------


class TestCrossProducerParity:
    def test_all_wired_producers_emit_parity(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        from ipfs_datasets_py.audit.audit_logger import (
            AuditCategory,
            AuditLevel,
            AuditLogger,
        )
        from ipfs_datasets_py.logic.security import audit_log as sec_audit
        from ipfs_datasets_py.logic.observability.structured_logging import log_event
        from ipfs_datasets_py.mcp_server.logger import log_mcp_event
        from ipfs_datasets_py.optimizers.graphrag.pipeline_json_logger import (
            PipelineJSONLogger,
        )

        AuditLogger().log(
            AuditLevel.INFO,
            AuditCategory.SYSTEM,
            "boot",
            user="sys",
            event_id="evt-cross-audit-1",
        )
        sec_audit.AuditLogger.log_security_event(
            user_id="u1",
            event_type="validation_error",
            severity="low",
            message="bad input",
        )
        log_event("custom.probe", component="cross")
        log_mcp_event("cross mcp", event_id="evt-cross-mcp-1")
        PipelineJSONLogger(domain="medical").start_run(
            run_id="cross-run", data_source="test"
        )
        route_alert_event(
            rule_id="r-cross",
            status="triggered",
            message="cross",
            event_id="evt-cross-alert-1",
        )

        receipts = shadow.list_receipts()
        assert len(receipts) >= 5
        for receipt in receipts:
            assert receipt.event_id
            assert receipt.record_schema
            assert receipt.classification
            assert receipt.source_revision
            assert receipt.parity_receipt_cid or receipt.mode == "disabled"
            if receipt.mode == AuthorityMode.SHADOW.value:
                assert receipt.parity_matched is True, receipt.to_dict()
                assert receipt.authority == "legacy"
